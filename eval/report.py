"""Eval report (Milestone 8): table + trap-category chart + replay JSON.

pandas/plotly are used when installed; otherwise plain-text table and a
built-in HTML bar chart so the report never hard-requires them.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agent.config import load_config


def load_results(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def module_rows(results: dict) -> list[dict]:
    rows = []
    for m in results.get("modules", []):
        rows.append(
            {
                "module": m["name"],
                "static_clean": m["static_clean"],
                "agreement_pct": m["agreement_pct"],
                "seeds": m["seeds"],
                "mismatches": len(m["mismatches"]),
                "any_density": round(m["any_density"], 4),
                "iterations": m["iterations"],
                "tokens": m["tokens"],
            }
        )
    return rows


def print_table(results: dict) -> None:
    rows = module_rows(results)
    try:
        import pandas as pd

        print(pd.DataFrame(rows).to_string(index=False))
    except ImportError:
        widths = {k: max(len(k), *(len(str(r[k])) for r in rows)) for k in rows[0]} if rows else {}
        print(" | ".join(k.ljust(widths[k]) for k in widths))
        for r in rows:
            print(" | ".join(str(r[k]).ljust(widths[k]) for k in widths))
    print("\ntraps:")
    for t in results.get("traps", []):
        mark = "CAUGHT" if t["caught"] else "MISSED"
        print(f"  [{mark}] {t['id']}: {t['description']} ({t['mismatches']} mismatches)")


def write_chart(results: dict, out_html: str | Path) -> Path:
    """Bar chart of trap sensitivity + module agreement. Returns the path."""
    out = Path(out_html)
    out.parent.mkdir(parents=True, exist_ok=True)
    traps = results.get("traps", [])
    ids = [t["id"] for t in traps]
    caught = [1 if t["caught"] else 0 for t in traps]
    try:
        import plotly.graph_objects as go

        fig = go.Figure(
            data=[
                go.Bar(name="trap caught", x=ids, y=caught),
                go.Bar(
                    name="module agreement",
                    x=[m["name"] for m in results.get("modules", [])],
                    y=[m["agreement_pct"] for m in results.get("modules", [])],
                ),
            ]
        )
        fig.update_layout(title="Eval: failures by trap category + module agreement")
        out.write_text(fig.to_html(include_plotlyjs="cdn"), encoding="utf-8")
        return out
    except ImportError:
        bars = "\n".join(
            f"<div>{t['id']}: {'█' if t['caught'] else '░'} {t['mismatches']}</div>" for t in traps
        )
        out.write_text(
            f"<html><body><h1>Trap sensitivity</h1>{bars}</body></html>", encoding="utf-8"
        )
        return out


def write_replay(results: dict, out_json: str | Path) -> Path:
    """run-report.json consumed by the web replay UI (see web/src/App.tsx)."""
    out = Path(out_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "modules": module_rows(results),
        "traps": results.get("traps", []),
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Render the eval report")
    ap.add_argument("results", nargs="?", default="eval/results.json")
    args = ap.parse_args()
    cfg = load_config(REPO / "config.yaml")
    results = load_results(args.results)
    print_table(results)
    html = write_chart(
        results, REPO / str(cfg.raw.get("eval", {}).get("report_html", "eval/report.html"))
    )
    replay = write_replay(
        results,
        REPO / str(cfg.raw.get("eval", {}).get("replay_json", "web/public/run-report.json")),
    )
    print(f"\nwrote {html}\nwrote {replay}")


if __name__ == "__main__":
    main()
