"""Python target adapter (Milestone 3): static_check via ruff + mypy.

Parses tool output into Diags. Never relies on the LLM to read raw output.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from agent.state import Diag, Mismatch

_MYPY_RE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<level>error|warning|note):\s*(?P<msg>.*)$"
)


def _run_ruff(path: Path) -> list[Diag]:
    exe = shutil.which("ruff")
    cmd = (
        [exe, "check", str(path), "--output-format", "json"]
        if exe
        else [sys.executable, "-m", "ruff", "check", str(path), "--output-format", "json"]
    )
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    try:
        items = json.loads(p.stdout or "[]")
    except json.JSONDecodeError:
        return [
            Diag(
                tool="ruff",
                file=path.name,
                line=None,
                code="parse-error",
                message=(p.stderr or p.stdout).strip()[:2000] or "ruff output unparseable",
            )
        ]
    diags: list[Diag] = []
    for it in items:
        loc: Any = it.get("location") or {}
        raw_row: Any = loc.get("row") if isinstance(loc, dict) else None
        lineno: int | None = None
        if raw_row is not None:
            try:
                lineno = int(raw_row)
            except (TypeError, ValueError):
                lineno = None
        diags.append(
            Diag(
                tool="ruff",
                file=path.name,
                line=lineno,
                code=str(it.get("code") or "ruff"),
                message=str(it.get("message") or it),
            )
        )
    return diags


def _run_mypy(path: Path) -> list[Diag]:
    cmd = [
        sys.executable,
        "-m",
        "mypy",
        str(path),
        "--strict",
        "--show-error-codes",
        "--no-error-summary",
        "--no-pretty",
        "--ignore-missing-imports",
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
    diags: list[Diag] = []
    for line in (p.stdout or "").splitlines():
        m = _MYPY_RE.match(line.strip())
        if not m:
            continue
        if m.group("level") == "note":
            continue
        msg = m.group("msg").strip()
        code = "mypy"
        cm = re.search(r"\[([a-z\-]+)\]\s*$", msg)
        if cm:
            code = cm.group(1)
            msg = msg[: cm.start()].strip()
        lineno2: int | None
        try:
            lineno2 = int(m.group("line"))
        except (TypeError, ValueError):
            lineno2 = None
        diags.append(Diag(tool="mypy", file=path.name, line=lineno2, code=code, message=msg))
    return diags


def static_check(
    code: str, *, filename: str = "converted.py", workdir: str | Path | None = None
) -> list[Diag]:
    """Write code to disk, run ruff + mypy, return parsed Diags (empty = clean)."""
    if workdir is None:
        with tempfile.TemporaryDirectory(prefix="migrate-py-") as td:
            target = Path(td) / filename
            target.write_text(code, encoding="utf-8")
            return _run_ruff(target) + _run_mypy(target)
    target = Path(workdir) / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(code, encoding="utf-8")
    return _run_ruff(target) + _run_mypy(target)


def harness_gen(
    *,
    js_module: str | Path,
    py_module: str | Path,
    seeds: dict[str, list[list[Any]]],
    out_path: str | Path,
    fuzz_examples: int = 50,
    rel_tol: float = 1e-9,
    undefined_null_distinct: bool = True,
    timeout_s: float = 10,
) -> Path:
    """Write a reproducible differential pytest file. Returns its path."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parents[1].as_posix()
    # Seeds may contain undefined/NaN/-0: serialize each arg-list tagged.
    from oracle.tagged_json import dumps_tagged

    payload = {
        "js_module": str(js_module),
        "py_module": str(py_module),
        "seeds": {fn: [dumps_tagged(a) for a in arg_lists] for fn, arg_lists in seeds.items()},
        "fuzz_examples": fuzz_examples,
        "rel_tol": rel_tol,
        "undefined_null_distinct": undefined_null_distinct,
        "timeout_s": timeout_s,
    }
    lines = [
        '"""Generated differential test. Regenerate via targets.python.harness_gen."""',
        "import json",
        "import sys",
        f'sys.path.insert(0, "{repo_root}")',
        "from agent.state import Mismatch",
        "from harness.fuzz import run_differential",
        "from oracle.tagged_json import loads_tagged",
        "",
        # Payload travels as a JSON string literal (repr-escaped) so that
        # JSON true/false/null never leak into Python source.
        f"_PAYLOAD = json.loads({json.dumps(payload, ensure_ascii=False)!r})",
        "",
    ]
    for fn in seeds:
        lines += [
            f"def test_diff_{fn}_seeds_and_fuzz():",
            f'    seeds = [loads_tagged(w) for w in _PAYLOAD["seeds"]["{fn}"]]',
            "    mismatches: list[Mismatch] = run_differential(",
            '        _PAYLOAD["js_module"],',
            '        _PAYLOAD["py_module"],',
            f'        "{fn}",',
            "        seeds,",
            '        fuzz_examples=_PAYLOAD["fuzz_examples"],',
            '        rel_tol=_PAYLOAD["rel_tol"],',
            '        undefined_null_distinct=_PAYLOAD["undefined_null_distinct"],',
            '        timeout_s=_PAYLOAD["timeout_s"],',
            "    )",
            "    assert mismatches == [], [",
            '        f"{m.function} {m.input_json} js={m.js_output} py={m.target_output}"',
            "        for m in mismatches",
            "    ]",
            "",
        ]
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def run_diff(
    *,
    js_module: str | Path,
    py_module: str | Path,
    seeds: dict[str, list[list[Any]]],
    strategies: dict[str, Any] | None = None,
    fuzz_examples: int = 50,
    rel_tol: float = 1e-9,
    undefined_null_distinct: bool = True,
    timeout_s: float = 10,
) -> list[Mismatch]:
    """Run seeds + fuzz now (used by the graph). Returns Mismatches."""
    from harness.fuzz import run_differential

    strategies = strategies or {}
    out: list[Mismatch] = []
    for fn, fn_seeds in seeds.items():
        out.extend(
            run_differential(
                js_module,
                py_module,
                fn,
                [list(a) for a in fn_seeds],
                strategy=strategies.get(fn),
                fuzz_examples=fuzz_examples,
                rel_tol=rel_tol,
                undefined_null_distinct=undefined_null_distinct,
                timeout_s=timeout_s,
            )
        )
    return out
