"""TypeScript target adapter: `tsc --strict` static check + harness scaffold.

Differential execution for TS reuses the original test suite (`tsc --noEmit`
plus jest); the full jest runner is follow-up work, so run_diff raises a
clear NotImplementedError instead of pretending.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from agent.state import Diag, Mismatch

_TSC_RE = re.compile(r"^(.+?)\((\d+),(\d+)\):\s*error\s+(TS\d+):\s*(.*)$")
_tsc_cache: list[str] | None | bool = None


def _find_tsc() -> list[str] | None:
    """tsc command, or None when TypeScript is unavailable."""
    global _tsc_cache
    if _tsc_cache is not None:
        return None if _tsc_cache is False else list(_tsc_cache)  # type: ignore[arg-type]
    local = shutil.which("tsc")
    if local:
        _tsc_cache = [local]
        return [local]
    npx = shutil.which("npx")  # .cmd on Windows; resolved here, not by CreateProcess
    if npx is None:
        _tsc_cache = False
        return None
    base = [npx, "--yes", "--package", "typescript", "tsc"]
    try:
        p = subprocess.run(
            [*base, "--version"], capture_output=True, text=True, timeout=180, check=False
        )
    except (subprocess.TimeoutExpired, OSError):
        _tsc_cache = False
        return None
    if p.returncode != 0:
        _tsc_cache = False
        return None
    _tsc_cache = base
    return list(base)


def static_check(
    code: str, *, filename: str = "converted.ts", workdir: str | Path | None = None
) -> list[Diag]:
    """Run tsc --strict --noEmit; parse errors into Diags."""
    tsc = _find_tsc()
    if tsc is None:
        return [
            Diag(
                tool="tsc",
                file=filename,
                line=None,
                code="tsc-missing",
                message="TypeScript compiler not found; install typescript to enable the TS target",
            )
        ]
    if workdir is None:
        with tempfile.TemporaryDirectory(prefix="migrate-ts-") as td:
            target = Path(td) / filename
            target.write_text(code, encoding="utf-8")
            return _run_tsc(tsc, target)
    target = Path(workdir) / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(code, encoding="utf-8")
    return _run_tsc(tsc, target)


def _run_tsc(tsc: list[str], path: Path) -> list[Diag]:
    p = subprocess.run(
        [*tsc, "--noEmit", "--strict", "--target", "es2022", "--module", "commonjs", str(path)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    diags: list[Diag] = []
    for line in (p.stdout + p.stderr).splitlines():
        m = _TSC_RE.match(line.strip())
        if not m:
            continue
        try:
            lineno: int | None = int(m.group(2))
        except ValueError:
            lineno = None
        diags.append(
            Diag(
                tool="tsc",
                file=Path(m.group(1)).name,
                line=lineno,
                code=m.group(4),
                message=m.group(5),
            )
        )
    return diags


def harness_gen(
    *,
    js_module: str | Path,
    ts_module: str | Path,
    seeds: dict[str, list[list[Any]]],
    out_path: str | Path,
) -> Path:
    """Write a tsconfig + type-level check importing the converted module."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tsconfig = {
        "compilerOptions": {
            "strict": True,
            "target": "es2022",
            "module": "commonjs",
            "noEmit": True,
            "allowJs": False,
        },
        "files": [str(ts_module), str(out.with_suffix(".check.ts"))],
    }
    (out.parent / "tsconfig.migrate.json").write_text(
        json.dumps(tsconfig, indent=2), encoding="utf-8"
    )
    check = Path(str(out.with_suffix("")) + ".check.ts")
    lines = [f'import * as mod from "{Path(str(ts_module)).as_posix()}";']
    for fn in seeds:
        lines.append(f"const _check_{fn}: typeof mod.{fn} = mod.{fn};")
    lines.append("export { _check_" + ", _check_".join(seeds) + " };") if seeds else None
    check.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return check


def run_diff(
    *,
    js_module: str | Path,
    ts_module: str | Path,
    seeds: dict[str, list[list[Any]]],
    strategies: dict[str, Any] | None = None,
    fuzz_examples: int = 20,
    rel_tol: float = 1e-9,
    undefined_null_distinct: bool = True,
    timeout_s: float = 10,
    workdir: str | Path | None = None,
) -> list[Mismatch]:
    """Compile the TS with tsc, then diff original JS vs compiled JS (oracle-vs-oracle)."""
    from harness.fuzz import run_differential_js

    tsc = _find_tsc()
    if tsc is None:
        return [
            Mismatch(
                function=next(iter(seeds), "?"),
                input_json="[]",
                js_output="(oracle not consulted)",
                target_output="tsc-missing: install typescript to enable the TS target",
            )
        ]
    ts_module = Path(ts_module)
    if workdir is None:
        import tempfile

        build_root = Path(tempfile.mkdtemp(prefix="migrate-ts-"))
    else:
        build_root = Path(workdir) / ".tsbuild"
        build_root.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(
        [
            *tsc,
            "--strict",
            "--target",
            "es2022",
            "--module",
            "commonjs",
            "--outDir",
            str(build_root),
            str(ts_module),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if p.returncode != 0:
        return [
            Mismatch(
                function=next(iter(seeds), "?"),
                input_json="[]",
                js_output="(oracle not consulted)",
                target_output=f"tsc-compile-error: {(p.stdout + p.stderr).strip()[:1000]}",
            )
        ]
    compiled = build_root / f"{ts_module.stem}.js"
    if not compiled.is_file():
        return [
            Mismatch(
                function=next(iter(seeds), "?"),
                input_json="[]",
                js_output="(oracle not consulted)",
                target_output=f"tsc-emit-missing: {compiled} not produced",
            )
        ]
    strategies = strategies or {}
    out: list[Mismatch] = []
    for fn, fn_seeds in seeds.items():
        out.extend(
            run_differential_js(
                js_module,
                compiled,
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
