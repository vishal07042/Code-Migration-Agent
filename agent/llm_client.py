"""LLM client: OpenAI-compatible (Zen), SQLite cache, retries, structured output.

- Never hardcodes model names; caller passes role, model resolved from config.yaml.
- Cache key: model + sha256 of canonical prompt.
- Backoff on 429/5xx via tenacity.
- Structured outputs validated with Pydantic, retried up to N times with error appended.
- Concurrency cap from config via a semaphore.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from .config import AppConfig

T = TypeVar("T", bound=BaseModel)

# Prompt too large guard: refuse to send absurd payloads to free tier.
MAX_PROMPT_CHARS = 60_000


def _canonical_prompt(
    model: str, messages: Sequence[dict[str, Any]], response_format: str = "text"
) -> str:
    return json.dumps(
        {"model": model, "messages": list(messages), "format": response_format},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def prompt_hash(
    model: str, messages: Sequence[dict[str, Any]], response_format: str = "text"
) -> str:
    return hashlib.sha256(
        _canonical_prompt(model, messages, response_format).encode("utf-8")
    ).hexdigest()


def _is_retryable(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    if status in (429, 500, 502, 503, 504):
        return True
    msg = str(exc).lower()
    return any(s in msg for s in ("429", "rate limit", "overloaded", "timeout", "temporar"))


class LlmCache:
    """SQLite response cache. Key: model + prompt hash."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS responses "
                "(model TEXT NOT NULL, prompt_hash TEXT NOT NULL, response TEXT NOT NULL, "
                "tokens INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, "
                "PRIMARY KEY (model, prompt_hash))"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path), timeout=30)

    def get(self, model: str, phash: str) -> tuple[str, int] | None:
        with self._lock, self._connect() as con:
            row = con.execute(
                "SELECT response, tokens FROM responses WHERE model=? AND prompt_hash=?",
                (model, phash),
            ).fetchone()
        if row is None:
            return None
        return (row[0], int(row[1]))

    def put(self, model: str, phash: str, response: str, tokens: int = 0) -> None:
        with self._lock, self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO responses(model, prompt_hash, response, tokens, created_at)"
                " VALUES(?,?,?,?,?)",
                (model, phash, response, int(tokens), time.time()),
            )
            con.commit()


class LlmClient:
    def __init__(self, cfg: AppConfig, cache: LlmCache | None = None):
        self.cfg = cfg
        self.cache = cache or LlmCache(cfg.llm.cache_db)
        self._sema = threading.BoundedSemaphore(max(1, int(cfg.llm.concurrency)))

    # -- low-level transport (isolated for tests/mocking) -----------------

    def _transport(
        self, *, model: str, messages: list[dict[str, Any]], api_key: str | None
    ) -> tuple[str, int]:
        """Call the OpenAI-compatible chat endpoint. Returns (text, tokens)."""
        from openai import OpenAI

        extra: dict[str, Any] = {}
        if self.cfg.llm.provider == "openrouter":
            headers: dict[str, str] = {}
            if self.cfg.llm.referer:
                headers["HTTP-Referer"] = self.cfg.llm.referer
            if self.cfg.llm.title:
                headers["X-Title"] = self.cfg.llm.title
            if headers:
                extra["default_headers"] = headers
        client = OpenAI(base_url=self.cfg.llm.base_url, api_key=api_key or "no-key", **extra)
        call = retry(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(4),
            wait=wait_exponential(multiplier=1, min=1, max=20),
            reraise=True,
        )(client.chat.completions.create)
        resp = call(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=self.cfg.llm.max_tokens,
            timeout=self.cfg.llm.timeout_s,
        )
        text = resp.choices[0].message.content or ""
        tokens = 0
        try:
            usage = resp.usage
            if usage is not None:
                tokens = int((usage.prompt_tokens or 0) + (usage.completion_tokens or 0))
        except (AttributeError, TypeError, ValueError):
            tokens = 0
        return text, tokens

    # -- public API --------------------------------------------------------

    def chat(self, messages: list[dict[str, Any]], *, role: str = "converter") -> tuple[str, int]:
        """Plain chat call with cache. Returns (text, tokens_used)."""
        model = self.cfg.model_for(role)
        self._check_size(messages)
        phash = prompt_hash(model, messages)
        hit = self.cache.get(model, phash)
        if hit is not None:
            return hit
        with self._sema:
            # Re-check inside semaphore (another thread may have filled it).
            hit = self.cache.get(model, phash)
            if hit is not None:
                return hit
            text, tokens = self._transport(
                model=model, messages=messages, api_key=self.cfg.api_key()
            )
            if text.strip():
                self.cache.put(model, phash, text, tokens)
            return text, tokens

    def chat_structured(
        self, messages: list[dict[str, Any]], *, schema: type[T], role: str = "critic"
    ) -> tuple[T, int]:
        """Chat call parsed into a Pydantic model. Retries ≤ N with error appended."""
        max_retries = max(1, int(self.cfg.llm.max_structured_retries))
        total_tokens = 0
        errors: list[str] = []
        current = list(messages)
        last_text = ""
        for attempt in range(max_retries):
            if errors:
                current = current + [
                    {
                        "role": "user",
                        "content": (
                            "Previous response failed validation:\n"
                            + "\n".join(errors[-1:])
                            + "\nReturn ONLY valid JSON matching the schema."
                        ),
                    }
                ]
            text, tokens = self.chat(current, role=role)
            total_tokens += tokens
            last_text = text
            try:
                obj = schema.model_validate_json(_extract_json(text))
                return obj, total_tokens
            except (ValidationError, ValueError) as e:
                errors.append(f"attempt {attempt + 1}: {e}\nresponse was: {text[:2000]}")
        raise ValueError(
            f"Structured output failed after {max_retries} attempts: {errors} | last: {last_text[:500]}"
        )

    def _check_size(self, messages: Sequence[dict[str, Any]]) -> None:
        n = sum(len(str(m.get("content", ""))) for m in messages)
        if n > MAX_PROMPT_CHARS:
            raise ValueError(
                f"Prompt too large ({n} chars > {MAX_PROMPT_CHARS}). Refusing to send."
            )


def _extract_json(text: str) -> str:
    """Pull JSON out of a response that may contain fences/prose."""
    t = text.strip()
    if t.startswith("```"):
        # strip first/last fence
        lines = t.splitlines()
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        t = "\n".join(lines).strip()
    # If still has prose, take the first {...} span.
    if not t.startswith("{"):
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end != -1 and end > start:
            return t[start : end + 1]
    return t
