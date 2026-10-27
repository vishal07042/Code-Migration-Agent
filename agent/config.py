"""Load and validate config.yaml. No model names hardcoded in code."""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()  # .env (gitignored) supplies local keys like OPENROUTER_API_KEY


@dataclass(frozen=True)
class LlmSection:
    provider: str
    base_url: str
    api_key_env: str
    models_endpoint: str
    concurrency: int = 4
    timeout_s: int = 60
    max_tokens: int = 2048
    max_structured_retries: int = 3
    cache_db: str = ".cache/llm_cache.sqlite"
    referer: str | None = None
    title: str | None = None


@dataclass(frozen=True)
class AppConfig:
    raw: dict[str, Any]
    llm: LlmSection
    roles: dict[str, str]
    repo_root: Path = field(compare=False)

    @property
    def max_attempts(self) -> int:
        return int(self.raw.get("budgets", {}).get("max_attempts", 5))

    def model_for(self, role: str) -> str:
        try:
            return self.roles[role]
        except KeyError as e:
            raise KeyError(f"Unknown LLM role {role!r}. Known: {sorted(self.roles)}") from e

    def api_key(self) -> str | None:
        return os.environ.get(self.llm.api_key_env)


def _parse_yaml_simple(path: Path) -> dict[str, Any]:
    """Minimal YAML subset parser fallback (only used if pyyaml missing)."""
    text = path.read_text(encoding="utf-8")
    # Very small: delegate to json if it looks like json, else error.
    if text.strip().startswith("{"):
        parsed: dict[str, Any] = json.loads(text)
        return parsed
    raise RuntimeError(f"pyyaml is required to parse {path}" + f" (got {len(text)} chars)")


def load_config(path: str | Path | None = None) -> AppConfig:
    import yaml

    if path is None:
        # repo root = parent of agent/ when called from repo root
        here = Path.cwd()
        candidate = here / "config.yaml"
        path = (
            candidate if candidate.exists() else Path(__file__).resolve().parents[1] / "config.yaml"
        )
    path = Path(path)
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    llm_raw: Mapping[str, Any] = data.get("llm", {})
    provider = str(llm_raw.get("provider", "zen"))
    profiles: Mapping[str, Any] = data.get("providers", {})
    prof: Mapping[str, Any] = profiles.get(provider, {})
    llm = LlmSection(
        provider=provider,
        base_url=str(prof.get("base_url", llm_raw.get("base_url", "https://opencode.ai/zen/v1"))),
        api_key_env=str(prof.get("api_key_env", llm_raw.get("api_key_env", "ZEN_API_KEY"))),
        models_endpoint=str(
            prof.get(
                "models_endpoint",
                llm_raw.get("models_endpoint", "https://opencode.ai/zen/v1/models"),
            )
        ),
        concurrency=int(llm_raw.get("concurrency", 4)),
        timeout_s=int(llm_raw.get("timeout_s", 60)),
        max_tokens=int(llm_raw.get("max_tokens", 2048)),
        max_structured_retries=int(llm_raw.get("max_structured_retries", 3)),
        cache_db=str(llm_raw.get("cache_db", ".cache/llm_cache.sqlite")),
        referer=prof.get("referer"),
        title=prof.get("title"),
    )
    roles = dict(data.get("roles", {}))
    for required in ("converter", "fixer", "critic"):
        if required not in roles:
            raise ValueError(f"config.yaml roles missing required role: {required}")
    return AppConfig(raw=data, llm=llm, roles=roles, repo_root=path.parent)


def list_remote_models(cfg: AppConfig, timeout_s: int = 15) -> list[str]:
    """GET the Zen /models endpoint. Returns model id list. Raises on HTTP error."""
    import ssl

    req = urllib.request.Request(cfg.llm.models_endpoint, method="GET")
    key = cfg.api_key()
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = None
    with urllib.request.urlopen(req, timeout=timeout_s, context=ctx) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    ids: list[str] = []
    data = payload.get("data", payload if isinstance(payload, list) else [])
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("id"):
                ids.append(str(item["id"]))
            elif isinstance(item, str):
                ids.append(item)
    return ids
