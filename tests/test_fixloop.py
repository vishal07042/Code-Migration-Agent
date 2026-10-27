"""Milestone 5 tests: patch apply, fingerprints, gate, and a full fix-loop run."""

import copy
import shutil
from pathlib import Path

import pytest

from agent.build import build_graph, initial_state
from agent.config import load_config
from agent.edges import decide
from agent.llm_client import LlmCache, LlmClient
from agent.nodes.fix import (
    PatchError,
    apply_patch,
    fingerprint,
    format_diags,
    render_fix_prompt,
)
from agent.state import Diag, Mismatch

REPO = Path(__file__).resolve().parents[1]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node missing")

BUGGY = "def capitalize(s: str) -> str:\n    return s[0].upper() + s[1:].lower()\n"
GOOD = (
    "def capitalize(s: str) -> str:\n"
    '    """Return the string with the first character upper-cased."""\n'
    "    if not s:\n"
    "        return s\n"
    "    return s[0].upper() + s[1:]\n"
)
PATCH = (
    "<<<<<<< SEARCH\n"
    "def capitalize(s: str) -> str:\n"
    "    return s[0].upper() + s[1:].lower()\n"
    "=======\n" + GOOD + ">>>>>>>\n"
)

DIFF = """--- a/cap.py
+++ b/cap.py
@@ -1,2 +1,5 @@
 def capitalize(s: str) -> str:
-    return s[0].upper() + s[1:].lower()
+    \"\"\"Return the string with the first character upper-cased.\"\"\"
+    if not s:
+        return s
+    return s[0].upper() + s[1:]
"""


def _diag(msg: str = "bad", line: int | None = 3) -> Diag:
    return Diag(tool="mypy", file="a.py", line=line, code="x", message=msg)


def _mm(js: str = "1", py: str = "2") -> Mismatch:
    return Mismatch(function="f", input_json="[]", js_output=js, target_output=py)


def test_search_replace_roundtrip():
    assert apply_patch(BUGGY, PATCH) == GOOD


def test_search_replace_multi_block():
    src = "a = 1\nb = 2\n"
    patch = (
        "<<<<<<< SEARCH\na = 1\n=======\na = 10\n>>>>>>>\n"
        "<<<<<<< SEARCH\nb = 2\n=======\nb = 20\n>>>>>>>\n"
    )
    assert apply_patch(src, patch) == "a = 10\nb = 20\n"


def test_search_replace_requires_exactly_one_hit():
    with pytest.raises(PatchError):
        apply_patch("x = 1\n", "<<<<<<< SEARCH\nmissing\n=======\ny\n>>>>>>>\n")
    with pytest.raises(PatchError):
        apply_patch("v = 1\nv = 1\n", "<<<<<<< SEARCH\nv = 1\n=======\nv = 2\n>>>>>>>\n")


def test_unified_diff_apply_and_reject():
    assert apply_patch(BUGGY, DIFF) == GOOD
    with pytest.raises(PatchError):
        apply_patch("other = 1\n", DIFF)


def test_fingerprint_stable_ignores_lines():
    a = fingerprint([_diag("oops", line=3)], [_mm()])
    b = fingerprint([_diag("oops", line=99)], [_mm()])
    assert a == b
    assert fingerprint([_diag("oops")], [_mm()]) != fingerprint([_diag("different")], [_mm()])
    assert len(a) == 16


def test_gate_decisions():
    assert (
        decide(static_errors=[], mismatches=[], attempts=1, fingerprints=["a"], max_attempts=5)
        == "critic"
    )
    assert (
        decide(
            static_errors=[_diag()], mismatches=[], attempts=5, fingerprints=["a"], max_attempts=5
        )
        == "escalate"
    )
    assert (
        decide(
            static_errors=[_diag()],
            mismatches=[],
            attempts=1,
            fingerprints=["x", "x"],
            max_attempts=5,
        )
        == "fix_wide"
    )
    assert (
        decide(
            static_errors=[],
            mismatches=[_mm()],
            attempts=1,
            fingerprints=["x", "y"],
            max_attempts=5,
        )
        == "fix"
    )


def test_fix_prompt_mentions_failing_function_only():
    text = render_fix_prompt(
        BUGGY,
        [_diag("name-defined")],
        [_mm(js="1", py="2")],
    )
    assert "Fix ONLY" in text and "name-defined" in text and "s[0].upper" in text


def test_format_diags_empty():
    assert "no static errors" in format_diags([])


def test_graph_compiles(tmp_path):
    cfg = load_config(REPO / "config.yaml")
    client = LlmClient(cfg, cache=LlmCache(tmp_path / "c.sqlite"))
    graph, _ = build_graph(cfg, client, workdir=tmp_path / "work")
    assert graph is not None


def test_graph_escalation_recorded_on_cap(tmp_path):
    """Fixer garbage until the cap: file lands in escalated + sidecar, no raise."""
    import copy

    from agent.config import AppConfig

    src_repo = tmp_path / "repo"
    src_repo.mkdir()
    (src_repo / "stub.js").write_text(
        "function stub(x) { if (x) return 1; return 0; }\nmodule.exports = { stub };\n",
        encoding="utf-8",
    )
    (src_repo / "stub.test.js").write_text(
        "test('s', () => { expect(stub([])).toBe(1); });\n", encoding="utf-8"
    )
    cfg = load_config(REPO / "config.yaml")
    raw = copy.deepcopy(cfg.raw)
    raw["budgets"]["max_attempts"] = 2
    raw["harness"]["fuzz_examples"] = 0
    small = AppConfig(raw=raw, llm=cfg.llm, roles=cfg.roles, repo_root=cfg.repo_root)
    client = LlmClient(small, cache=LlmCache(tmp_path / "c.sqlite"))

    def fake(*, model: str, messages: list, api_key: str | None):
        content = str(messages[-1].get("content", ""))
        if "Convert this JavaScript" in content:
            return ("def stub(x):\n    return 0\n", 5)
        return ("not a patch", 5)

    client._transport = fake  # type: ignore[method-assign]
    graph, _ = build_graph(small, client, workdir=tmp_path / "work")
    final = graph.invoke(
        initial_state(str(src_repo), "python"), config={"configurable": {"thread_id": "esc1"}}
    )
    assert final["done"] == []
    assert final["escalated"] == ["stub.js"]
    assert (tmp_path / "work" / ".migrate" / "stub.js.escalation.json").exists()


@needs_node
def test_graph_end_to_end_fix_loop(tmp_path):
    """Buggy first conversion -> fixer patch -> green -> critic -> commit."""
    src_repo = tmp_path / "repo"
    src_repo.mkdir()
    (src_repo / "capitalize.js").write_text(
        "/** Capitalize. @param {string} s */\n"
        "function capitalize(s) {\n"
        "  if (!s) return s;\n"
        "  return s.charAt(0).toUpperCase() + s.slice(1);\n"
        "}\nmodule.exports = { capitalize };\n",
        encoding="utf-8",
    )
    (src_repo / "capitalize.test.js").write_text(
        "test('c', () => {\n"
        "  expect(capitalize('hello')).toBe('Hello');\n"
        "  expect(capitalize('')).toBe('');\n"
        "  expect(capitalize('aBC')).toBe('ABC');\n"
        "  expect(capitalize(undefined)).toBe(undefined);\n"
        "});\n",
        encoding="utf-8",
    )
    cfg = load_config(REPO / "config.yaml")

    def fake_transport(*, model: str, messages: list, api_key: str | None):
        content = str(messages[-1].get("content", ""))
        if "Convert this JavaScript" in content:
            return (BUGGY, 10)
        if "Fix ONLY" in content or "search/replace" in content:
            return (PATCH, 20)
        if "Review this conversion" in content:
            return ('{"pass": true, "flags": []}', 5)
        raise AssertionError(f"unexpected prompt: {content[:120]}")

    raw = copy.deepcopy(cfg.raw)
    raw["harness"]["fuzz_examples"] = 5
    from agent.config import AppConfig

    small = AppConfig(raw=raw, llm=cfg.llm, roles=cfg.roles, repo_root=cfg.repo_root)
    client = LlmClient(small, cache=LlmCache(tmp_path / "c.sqlite"))
    client._transport = fake_transport  # type: ignore[method-assign]

    graph, _ = build_graph(small, client, workdir=tmp_path / "work")
    final = graph.invoke(
        initial_state(str(src_repo), "python"), config={"configurable": {"thread_id": "t1"}}
    )
    assert final["done"] == ["capitalize.js"]
    assert final["escalated"] == []
    assert final["cheat_flags"] == []
    assert final["tokens_used"] == 10 + 20 + 5  # convert + fix + critic (cumulative)
    from git import Repo

    log = Repo(tmp_path / "work").git.log("--format=%s")
    assert "migrate capitalize.js (iters 2," in log  # convert + one fix
    committed = tmp_path / "work" / "converted" / "capitalize.py"
    assert committed.read_text(encoding="utf-8") == GOOD
