"""Milestone 8 tests: eval on one module + one trap + report artifacts."""

import json
import shutil
from pathlib import Path

import pytest

from eval.report import load_results, module_rows, write_chart, write_replay
from eval.run import TRAP_CHECKS, evaluate_module, evaluate_trap

REPO = Path(__file__).resolve().parents[1]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node missing")


@needs_node
def test_eval_module_truthiness_small():
    corpus = REPO / "eval" / "corpus"
    row = evaluate_module(corpus, "truthiness", fuzz_examples=5, timeout_s=15, rel_tol=1e-9)
    assert row["static_clean"] is True, row["static_errors"]
    assert row["seeds"] == 7
    assert row["mismatches"] == [], row["mismatches"][:2]
    assert row["agreement_pct"] == 100.0


@needs_node
def test_eval_trap_division_caught():
    check = next(c for c in TRAP_CHECKS if c["id"] == "T3-division")
    out = evaluate_trap(check, timeout_s=15)
    assert out["caught"] is True and out["mismatches"] >= 1


def test_report_table_chart_replay(tmp_path):
    results = {
        "modules": [
            {
                "name": "demo",
                "functions": ["f"],
                "static_clean": True,
                "static_errors": [],
                "seeds": 3,
                "mismatches": [],
                "agreement_pct": 100.0,
                "any_density": 0.0,
                "iterations": 1,
                "tokens": 42,
            }
        ],
        "traps": [{"id": "T1", "description": "d", "caught": True, "mismatches": 2}],
    }
    rows = module_rows(results)
    assert rows[0]["module"] == "demo"
    html = write_chart(results, tmp_path / "report.html")
    assert html.exists() and html.stat().st_size > 100
    replay = write_replay(results, tmp_path / "run-report.json")
    payload = json.loads(replay.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert [m["module"] for m in payload["modules"]] == ["demo"]
    assert payload["traps"][0]["id"] == "T1"
    assert load_results(replay)["version"] == 1
