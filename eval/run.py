"""Eval harness (Milestone 8): agreement on reference conversions + trap sensitivity.

Reference conversions (*_expected.py) are hand-verified; they prove the
harness itself (static clean + 100% differential agreement). Trap checks use
intentionally buggy variants to prove each trap class is CAUGHT.
Live-model eval (iterations/tokens/escalations) plugs in via --converter live
once chat works from inside OpenCode or with a paid key.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agent.anticheat import any_density
from agent.config import load_config
from harness import fuzz as F
from harness.seeds import extract_seeds
from targets import python as py_adapter

MODULES = ["math", "strings", "arrays", "dates", "truthiness"]


def _numbers() -> Any:
    return F.st.one_of(F.js_int(), F.js_float())


def _args1(s: Any) -> Any:
    return F.st.lists(s, min_size=1, max_size=1)


def module_strategies(name: str) -> dict[str, Any]:
    finite = F.st.one_of(
        F.st.integers(-1000, 1000),
        F.st.floats(-1000, 1000, allow_nan=False, allow_infinity=False, allow_subnormal=False),
    )
    scalars = F.st.one_of(
        F.st.integers(-100, 100), F.js_float(), F.js_string(), F.st.booleans(), F.st.none()
    )
    words_alphabet = F.st.text(alphabet=F.st.sampled_from(list("abcXYZ019 \t\n-_.")), max_size=12)
    iso_days = F.st.dates(
        min_value=datetime.date(1900, 1, 1), max_value=datetime.date(2100, 1, 1)
    ).map(lambda d: [d.isoformat()])
    if name == "math":
        return {
            "add": F.st.lists(_numbers(), min_size=2, max_size=2),
            "clamp": F.st.lists(_numbers(), min_size=3, max_size=3),
            "factorial": F.st.integers(0, 12).map(lambda n: [n]),
        }
    if name == "strings":
        return {
            "capitalize": _args1(F.js_string()),
            "repeat": F.st.tuples(F.js_string(), F.st.integers(0, 8)).map(list),
            "words": _args1(words_alphabet),
        }
    if name == "arrays":
        nested = F.st.recursive(scalars, lambda c: F.st.lists(c, max_size=3), max_leaves=4)
        return {
            "unique": _args1(F.st.lists(scalars, max_size=5)),
            "sortedNumeric": _args1(F.st.lists(finite, max_size=6)),
            "flattenOnce": _args1(F.st.lists(nested, max_size=4)),
        }
    if name == "dates":
        return {
            "addDays": F.st.tuples(iso_days.map(lambda a: a[0]), F.st.integers(-3650, 3650)).map(
                list
            ),
            "dayOfWeekUtc": iso_days,
        }
    if name == "truthiness":
        return {"toLabel": _args1(F.js_value())}
    raise ValueError(f"unknown module {name}")


TRAP_CHECKS: list[dict[str, Any]] = [
    {
        "id": "T1-truthiness",
        "description": "[] '0' {} are truthy in JS; naive `if x` mistreats them",
        "fn": "toLabel",
        "js": "function toLabel(x) { if (x) return 'yes'; return 'no'; }\nmodule.exports = { toLabel };\n",
        "py": "def toLabel(x):\n    return 'yes' if x else 'no'\n",
        "seeds": [[[]], ["0"], [{}], [0]],
    },
    {
        "id": "T2-undefined-null",
        "description": "undefined vs null conflated to None",
        "fn": "coalesce",
        "js": "function coalesce(x) { return x === undefined ? 'ud' : x === null ? 'nu' : 'other'; }\nmodule.exports = { coalesce };\n",
        "py": "def coalesce(x):\n    return 'ud' if x is None else 'other'\n",
        "seeds": "UNDEFINED_AND_NONE",
    },
    {
        "id": "T3-division",
        "description": "`/` is true division; `//` truncates",
        "fn": "half",
        "js": "function half(x) { return x / 2; }\nmodule.exports = { half };\n",
        "py": "def half(x):\n    return x // 2\n",
        "seeds": [[5], [7]],
    },
    {
        "id": "T4-default-sort",
        "description": "JS default sort is lexicographic, not numeric",
        "fn": "sortDefault",
        "js": "function sortDefault(xs) { return [...xs].sort(); }\nmodule.exports = { sortDefault };\n",
        "py": "def sortDefault(xs):\n    return sorted(xs)\n",
        "seeds": [[[10, 9, 80]]],
    },
    {
        "id": "T5-utf16-emoji",
        "description": "strings are UTF-16: slice(0,1) of emoji is a lone surrogate",
        "fn": "firstOne",
        "js": "function firstOne(s) { return s.slice(0, 1); }\nmodule.exports = { firstOne };\n",
        "py": "def firstOne(s):\n    return s[:1]\n",
        "seeds": [["\U0001f600ab"], ["abc"]],
    },
    {
        "id": "T6-map-index",
        "description": ".map passes (value, index); ignoring the index drifts",
        "fn": "addIdx",
        "js": "function addIdx(xs) { return xs.map((v, i) => v + i); }\nmodule.exports = { addIdx };\n",
        "py": "def addIdx(xs):\n    return list(xs)\n",
        "seeds": [[[10, 20, 30]]],
    },
]


def _resolve_trap_seeds(seeds: Any) -> list[list[Any]]:
    from oracle.tagged_json import UNDEFINED

    if seeds == "UNDEFINED_AND_NONE":
        return [[UNDEFINED], [None]]
    return [list(a) for a in seeds]


def evaluate_module(
    corpus: Path, name: str, *, fuzz_examples: int, timeout_s: float, rel_tol: float
) -> dict[str, Any]:
    js = corpus / f"{name}.js"
    py = corpus / f"{name}_expected.py"
    test_src = (corpus / f"{name}.test.js").read_text(encoding="utf-8")
    code = py.read_text(encoding="utf-8")
    diags = py_adapter.static_check(code, filename=py.name)
    from agent.nodes.analyze import exported_functions

    fns = exported_functions(js.read_text(encoding="utf-8"))
    seeds = {fn: extract_seeds(test_src, fn) for fn in fns}
    strategies = module_strategies(name)
    mismatches = py_adapter.run_diff(
        js_module=js,
        py_module=py,
        seeds=seeds,
        strategies={k: v for k, v in strategies.items() if k in seeds},
        fuzz_examples=fuzz_examples,
        rel_tol=rel_tol,
        timeout_s=timeout_s,
    )
    total_seeds = sum(len(v) for v in seeds.values())
    return {
        "name": name,
        "functions": fns,
        "static_clean": not diags,
        "static_errors": [d.model_dump() for d in diags],
        "seeds": total_seeds,
        "mismatches": [m.model_dump() for m in mismatches],
        "agreement_pct": 100.0 if not mismatches else 0.0,
        "any_density": any_density(code),
        "iterations": 0,
        "tokens": 0,
    }


def evaluate_trap(check: dict[str, Any], *, timeout_s: float) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="trap-") as td:
        js = Path(td) / "mod.js"
        py = Path(td) / "mod.py"
        js.write_text(str(check["js"]), encoding="utf-8")
        py.write_text(str(check["py"]), encoding="utf-8")
        seeds = {str(check["fn"]): _resolve_trap_seeds(check["seeds"])}
        mismatches = py_adapter.run_diff(
            js_module=js, py_module=py, seeds=seeds, fuzz_examples=0, timeout_s=timeout_s
        )
    return {
        "id": check["id"],
        "description": check["description"],
        "caught": len(mismatches) > 0,
        "mismatches": len(mismatches),
    }


def run_eval(
    *, corpus_dir: Path | None = None, fuzz_examples: int = 50, timeout_s: float = 10
) -> dict[str, Any]:
    cfg = load_config(REPO / "config.yaml")
    corpus = corpus_dir or (REPO / str(cfg.raw.get("eval", {}).get("corpus_dir", "eval/corpus")))
    rel_tol = float(cfg.raw.get("comparison", {}).get("float_rel_tolerance", 1e-9))
    modules = [
        evaluate_module(
            corpus, m, fuzz_examples=fuzz_examples, timeout_s=timeout_s, rel_tol=rel_tol
        )
        for m in MODULES
    ]
    traps = [evaluate_trap(c, timeout_s=timeout_s) for c in TRAP_CHECKS]
    return {"modules": modules, "traps": traps}


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the migration eval harness")
    ap.add_argument("--fuzz", type=int, default=50, help="Hypothesis examples per function")
    ap.add_argument("--out", default="eval/results.json", help="Results JSON path")
    ap.add_argument("--timeout", type=float, default=10, help="Oracle call timeout (s)")
    args = ap.parse_args()
    results = run_eval(fuzz_examples=args.fuzz, timeout_s=args.timeout)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    n_mod = len(results["modules"])
    green = sum(1 for m in results["modules"] if m["static_clean"] and m["agreement_pct"] == 100.0)
    caught = sum(1 for t in results["traps"] if t["caught"])
    print(f"modules green: {green}/{n_mod} | traps caught: {caught}/{len(results['traps'])}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
