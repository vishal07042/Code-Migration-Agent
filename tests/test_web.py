"""Web replay contract: scaffold exists and run-report.json matches App's shape."""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_web_scaffold_present():
    assert (REPO / "web" / "package.json").exists()
    assert (REPO / "web" / "src" / "App.tsx").exists()
    app = (REPO / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    for key in ("modules", "traps", "agreement_pct", "static_clean", "caught"):
        assert key in app, key


def test_replay_contract_keys():
    """Keys eval/report.write_replay must emit for the UI (mirrors App types)."""
    from eval.report import write_replay

    sample = {
        "modules": [
            {
                "name": "m",
                "static_clean": True,
                "agreement_pct": 100.0,
                "seeds": 1,
                "mismatches": [],
                "any_density": 0.0,
                "iterations": 0,
                "tokens": 0,
            }
        ],
        "traps": [{"id": "T", "description": "d", "caught": False, "mismatches": 0}],
    }
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        payload = json.loads(
            Path(write_replay(sample, Path(td) / "r.json")).read_text(encoding="utf-8")
        )
    mod_keys = {
        "module",
        "static_clean",
        "agreement_pct",
        "seeds",
        "mismatches",
        "iterations",
        "tokens",
    }
    assert mod_keys <= set(payload["modules"][0])
    assert {"id", "description", "caught", "mismatches"} <= set(payload["traps"][0])
