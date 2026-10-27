"""Tests for Milestone 1: config, state, LLM cache/retries, git helper."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from agent.config import load_config
from agent.git_helper import commit_file, ensure_repo, hash_file, revert_file
from agent.llm_client import LlmCache, LlmClient, prompt_hash
from agent.state import Diag, MigrationState, Mismatch


def test_state_schema_defaults():
    d = Diag(tool="ruff", file="a.py", message="x")
    assert d.line is None
    m = Mismatch(function="f", input_json="[]", js_output="1", target_output="1")
    assert m.function == "f"
    s: MigrationState = {
        "repo_path": ".",
        "target": "python",
        "queue": [],
        "current": None,
        "source": "",
        "converted": "",
        "static_errors": [],
        "mismatches": [],
        "error_fingerprints": [],
        "attempts": 0,
        "done": [],
        "escalated": [],
        "cheat_flags": [],
        "tokens_used": 0,
    }
    assert s["tokens_used"] == 0


def test_config_loads_roles():
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_config(repo_root / "config.yaml")
    assert cfg.model_for("converter")
    assert cfg.model_for("fixer")
    assert cfg.model_for("critic")
    with pytest.raises(KeyError):
        cfg.model_for("nope")
    assert cfg.max_attempts == 5


def test_prompt_hash_stable():
    msgs = [{"role": "user", "content": "hi"}]
    assert prompt_hash("m", msgs) == prompt_hash("m", msgs)
    assert prompt_hash("m", msgs) != prompt_hash("other", msgs)


def test_llm_cache_hit_avoids_transport(tmp_path):
    cfg = load_config()
    cache = LlmCache(tmp_path / "c.sqlite")
    client = LlmClient(cfg, cache=cache)

    calls = {"n": 0}

    def fake_transport(*, model, messages, api_key):
        calls["n"] += 1
        return ("hello", 7)

    client._transport = fake_transport  # type: ignore[method-assign]
    msgs = [{"role": "user", "content": "hello world"}]
    t1, tok1 = client.chat(msgs, role="converter")
    t2, tok2 = client.chat(msgs, role="converter")
    assert (t1, tok1) == (t2, tok2) == ("hello", 7)
    assert calls["n"] == 1  # second call served from SQLite cache


class Verdict(BaseModel):
    ok: bool
    reason: str = ""


def test_chat_structured_retries_with_error_appended(tmp_path):
    cfg = load_config()
    client = LlmClient(cfg, cache=LlmCache(tmp_path / "c2.sqlite"))
    responses = ["not json at all", '{"ok": true, "reason": "fine"}']
    seen_prompts: list[int] = []

    def fake_transport(*, model, messages, api_key):
        seen_prompts.append(len(messages))
        return (responses.pop(0), 3)

    client._transport = fake_transport  # type: ignore[method-assign]
    # Bypass cache so retry actually hits transport twice.
    client.cache.get = lambda model, ph: None  # type: ignore[method-assign]
    client.cache.put = lambda *a, **k: None  # type: ignore[method-assign]
    out, tokens = client.chat_structured([{"role": "user", "content": "judge"}], schema=Verdict)
    assert out.ok is True
    assert tokens == 6
    assert seen_prompts == [1, 2]  # second attempt appended the validation error


def test_git_commit_and_revert(tmp_path):
    repo = ensure_repo(tmp_path)
    f = tmp_path / "out.py"
    f.write_text("x = 1\n", encoding="utf-8")
    sha = commit_file(repo, tmp_path, "out.py", "feat: migrate out.py (iter 1, 10 tokens)")
    assert len(sha) == 40
    h1 = hash_file(f)
    f.write_text("x = 2  # regression\n", encoding="utf-8")
    assert hash_file(f) != h1
    revert_file(repo, "out.py", ref="HEAD")
    assert hash_file(f) == h1
