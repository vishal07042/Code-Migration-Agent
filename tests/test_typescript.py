"""Milestone 9 tests: TypeScript adapter (real tsc) + web contract."""

import shutil
from pathlib import Path

import pytest

import targets.typescript as ts
from targets import get_adapter

REPO = Path(__file__).resolve().parents[1]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node missing")

GOOD_TS = "export function add(a: number, b: number): number {\n  return a + b;\n}\n"
BAD_TS = "export function add(a: number, b: number): number {\n  return a + 'x';\n}\n"


def test_registry_resolves_both_targets():
    assert get_adapter("python") is not None
    assert get_adapter("typescript") is ts
    with pytest.raises(ValueError):
        get_adapter("cobol")


@needs_node
def test_tsc_clean_and_dirty():
    assert ts.static_check(GOOD_TS, filename="good.ts") == []
    diags = ts.static_check(BAD_TS, filename="bad.ts")
    if any(d.code == "tsc-missing" for d in diags):
        pytest.skip("tsc unavailable")
    assert any(d.tool == "tsc" and d.code.startswith("TS") for d in diags), diags


def test_tsc_missing_is_graceful(monkeypatch):
    monkeypatch.setattr(ts, "_find_tsc", lambda: None)
    ts._tsc_cache = None
    try:
        diags = ts.static_check("const x = 1;", filename="a.ts")
    finally:
        ts._tsc_cache = None
    assert len(diags) == 1 and diags[0].code == "tsc-missing"


def test_ts_run_diff_green_and_catches_bug(tmp_path):
    good = "export function add(a: number, b: number): number {\n  return a + b;\n}\n"
    bad = "export function add(a: number, b: number): number {\n  return a - b;\n}\n"
    (tmp_path / "good.ts").write_text(good, encoding="utf-8")
    (tmp_path / "bad.ts").write_text(bad, encoding="utf-8")
    (tmp_path / "orig.js").write_text(
        "function add(a, b) { return a + b; }\nmodule.exports = { add };\n", encoding="utf-8"
    )
    seeds = {"add": [[2, 3], [0, 0]]}
    ok_mm = ts.run_diff(
        js_module=tmp_path / "orig.js",
        ts_module=tmp_path / "good.ts",
        seeds=seeds,
        fuzz_examples=0,
    )
    if ok_mm and "tsc-missing" in ok_mm[0].target_output:
        pytest.skip("tsc unavailable")
    assert ok_mm == [], ok_mm
    bad_mm = ts.run_diff(
        js_module=tmp_path / "orig.js",
        ts_module=tmp_path / "bad.ts",
        seeds=seeds,
        fuzz_examples=0,
    )
    assert len(bad_mm) >= 1 and all(m.function == "add" for m in bad_mm)


@needs_node
def test_ts_harness_gen_artifact(tmp_path):
    check = ts.harness_gen(
        js_module="mod.js",
        ts_module=str(tmp_path / "mod.ts"),
        seeds={"add": [[1, 2]]},
        out_path=tmp_path / "gen" / "diff.ts",
    )
    assert check.exists() and "typeof mod.add" in check.read_text(encoding="utf-8")
