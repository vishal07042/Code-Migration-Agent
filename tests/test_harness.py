"""Milestone 4 tests: differential runs (seeds + fuzz) and harness artifacts."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import strategies as st

from harness.fuzz import js_string, run_differential
from harness.seeds import extract_seeds
from targets.python import harness_gen, run_diff

REPO = Path(__file__).resolve().parents[1]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node missing")

GOOD_PY = '''def capitalize(s: str) -> str:
    """Return the string with the first character upper-cased."""
    if not s:
        return s
    return s[0].upper() + s[1:]
'''

# Buggy: no empty-string guard (IndexError) AND lowercases rest (.toLowerCase drift).
BUGGY_PY = """def capitalize(s: str) -> str:
    return s[0].upper() + s[1:].lower()
"""

TEST_SRC = """
test('capitalize', () => {
  expect(capitalize('hello')).toBe('Hello');
  expect(capitalize('')).toBe('');
  expect(capitalize('aBC')).toBe('ABC');
});
"""


@needs_node
def test_run_diff_green_on_correct_conversion(tmp_path):
    js = REPO / "samples" / "capitalize.js"
    py = tmp_path / "cap.py"
    py.write_text(GOOD_PY, encoding="utf-8")
    seeds = {"capitalize": extract_seeds(TEST_SRC, "capitalize")}
    assert len(seeds["capitalize"]) == 3
    # capitalize is a string-domain function: fuzz strings, since generic
    # values would only probe JS-vs-Python dynamic typing (e.g. [] is truthy
    # in JS, falsy in Python) rather than the conversion itself.
    strat = st.lists(js_string(), min_size=1, max_size=1)
    mismatches = run_diff(
        js_module=js,
        py_module=py,
        seeds=seeds,
        strategies={"capitalize": strat},
        fuzz_examples=10,
        timeout_s=15,
    )
    assert mismatches == []


@needs_node
def test_run_diff_catches_buggy_conversion(tmp_path):
    js = REPO / "samples" / "capitalize.js"
    py = tmp_path / "cap_buggy.py"
    py.write_text(BUGGY_PY, encoding="utf-8")
    seeds = {"capitalize": extract_seeds(TEST_SRC, "capitalize")}
    mismatches = run_differential(js, py, "capitalize", seeds["capitalize"], fuzz_examples=0)
    assert len(mismatches) >= 2  # '' throws; 'aBC' lowercases rest
    by_input = {m.input_json: m for m in mismatches}
    assert any("threw" in m.target_output for m in by_input.values())
    assert all(m.function == "capitalize" for m in mismatches)
    assert all(m.js_output and m.target_output for m in mismatches)


@needs_node
def test_run_diff_missing_function_reports_load_error(tmp_path):
    js = REPO / "samples" / "capitalize.js"
    py = tmp_path / "empty.py"
    py.write_text("x = 1\n", encoding="utf-8")
    out = run_differential(js, py, "nope", [[]], fuzz_examples=0)
    assert len(out) == 1 and "load-error" in out[0].target_output


@needs_node
def test_harness_gen_artifact_runs_green(tmp_path):
    js = REPO / "samples" / "capitalize.js"
    py = tmp_path / "cap.py"
    py.write_text(GOOD_PY, encoding="utf-8")
    seeds = {"capitalize": extract_seeds(TEST_SRC, "capitalize")}
    gen = harness_gen(
        js_module=js,
        py_module=py,
        seeds=seeds,
        out_path=tmp_path / "test_gen_diff.py",
        # seeds only: generic fuzz would probe dynamic typing, not conversion
        fuzz_examples=0,
        timeout_s=15,
    )
    assert gen.exists()
    p = subprocess.run(
        [sys.executable, "-m", "pytest", str(gen), "-q", "-p", "no:cacheprovider"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]


def test_sandbox_run_marks_untrusted_changes(tmp_path):
    from sandbox.run import run_command

    victim = tmp_path / "oracle.js"
    victim.write_text("original", encoding="utf-8")
    r = run_command(
        [sys.executable, "-c", "import pathlib; pathlib.Path('oracle.js').write_text('tampered')"],
        cwd=tmp_path,
        timeout_s=30,
        readonly_paths=[victim],
    )
    assert r.returncode == 0
    assert r.readonly_ok is False
    assert len(r.readonly_changed) == 1
    victim.write_text("original", encoding="utf-8")
    r2 = run_command(
        [sys.executable, "-c", "print('hi')"],
        cwd=tmp_path,
        timeout_s=30,
        readonly_paths=[victim],
    )
    assert r2.returncode == 0 and r2.readonly_ok and r2.stdout.strip() == "hi"
