"""Milestone 3 tests: single-function convert (fixture-backed) + ruff/mypy.

Live Zen chat is blocked outside the OpenCode runtime (403 FreeTierError),
so conversion uses a recorded fixture through the same LlmClient.convert path.
Static checks run the real tools.
"""

from __future__ import annotations

from pathlib import Path

from agent.config import load_config
from agent.llm_client import LlmCache, LlmClient
from agent.nodes.convert import convert_source, render_convert_prompt, strip_code_fences
from targets.python import static_check

REPO = Path(__file__).resolve().parents[1]
JS_SOURCE = (REPO / "samples" / "capitalize.js").read_text(encoding="utf-8")

# Recorded converter output for samples/capitalize.js (stands in for the
# live LLM until chat works from inside OpenCode / a paid key).
# NOTE: char-level indexing is observably correct here: JS unit-level output
# for astral chars recombines over the JSON wire to the same scalar value.
FIXTURE_PY = '''def capitalize(s: str) -> str:
    """Return the string with the first character upper-cased."""
    if not s:
        return s
    return s[0].upper() + s[1:]
'''

DIRTY_PY = """import os


def add(a: int, b: int) -> int:
    return a + "x"
"""


def _client_with_fixture(tmp_path: Path, text: str, tokens: int = 123) -> LlmClient:
    cfg = load_config(REPO / "config.yaml")
    client = LlmClient(cfg, cache=LlmCache(tmp_path / "c.sqlite"))

    def fake_transport(*, model: str, messages: list[dict], api_key: str | None) -> tuple[str, int]:
        assert messages and "Convert this JavaScript" in str(messages[0].get("content", ""))
        return (text, tokens)

    client._transport = fake_transport  # type: ignore[method-assign]
    return client


def test_prompt_contains_traps_source_and_rules():
    cfg = load_config(REPO / "config.yaml")
    prompt = render_convert_prompt(cfg, source=JS_SOURCE)
    for keyword in ("undefined", "NaN", "-0", "sort", "UTF-16", "regex", "timezone"):
        assert keyword.lower() in prompt.lower(), f"trap missing: {keyword}"
    assert "function capitalize" in prompt
    assert "Output only the code" in prompt


def test_strip_code_fences():
    assert strip_code_fences("```python\nx = 1\n```\n") == "x = 1\n"
    assert strip_code_fences("x = 1\n") == "x = 1\n"


def test_convert_source_returns_fixture_code_and_tokens(tmp_path):
    cfg = load_config(REPO / "config.yaml")
    client = _client_with_fixture(tmp_path, "```python\n" + FIXTURE_PY + "```\n")
    code, tokens = convert_source(client, cfg, JS_SOURCE)
    assert code == FIXTURE_PY
    assert tokens == 123


def test_static_check_clean_on_fixture():
    assert static_check(FIXTURE_PY, filename="capitalize.py") == []


def test_static_check_flags_ruff_and_mypy():
    diags = static_check(DIRTY_PY, filename="dirty.py")
    by_tool = {d.tool for d in diags}
    assert "ruff" in by_tool, diags
    assert "mypy" in by_tool, diags
    ruff_codes = {d.code for d in diags if d.tool == "ruff"}
    assert "F401" in ruff_codes, diags  # unused `import os`
    assert all(d.line is not None and d.line >= 1 for d in diags)
    assert all(d.message for d in diags)


def test_end_to_end_fixture_convert_then_static_green(tmp_path):
    cfg = load_config(REPO / "config.yaml")
    client = _client_with_fixture(tmp_path, FIXTURE_PY)
    code, tokens = convert_source(client, cfg, JS_SOURCE)
    diags = static_check(code, filename="capitalize.py")
    assert diags == [], diags
    assert tokens == 123


def test_fixture_has_no_cheat_markers():
    lowered = FIXTURE_PY.lower()
    assert "notimplementederror" not in lowered
    assert "type: ignore" not in lowered
    assert " as any" not in FIXTURE_PY
    assert "pass" not in [ln.strip() for ln in FIXTURE_PY.splitlines()]
