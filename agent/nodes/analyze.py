"""Analyze node (Milestone 7): dependency order (leaves first) + signatures.

- Runs tools/analyze.js (no npm deps) to get imports/exports per file.
- Topological order: dependencies before dependents ("leaves first").
- npm -> PyPI mapping for bare imports, flagging packages with no equivalent.
- extract_py_signatures: target signatures of converted deps for the prompt.
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path

# Well-known npm -> PyPI equivalents (v1 subset). Missing = flagged.
NPM_TO_PYPI: dict[str, str | None] = {
    "lodash": None,  # no single equivalent; use stdlib/825+ per-function
    "date-fns": "python-dateutil",
    "dayjs": None,
    "axios": "httpx",
    "chalk": "rich",
    "commander": "click",
    "express": "fastapi",
    "react": None,
    "validator": "validators",
    "uuid": None,  # stdlib uuid
}


class AnalyzeError(RuntimeError):
    pass


def run_analyzer(root: str | Path, *, node: str | None = None) -> dict[str, dict[str, list[str]]]:
    """Run tools/analyze.js, return {rel: {imports, exports, packages}}."""
    root = Path(root)
    script = Path(__file__).resolve().parents[2] / "tools" / "analyze.js"
    exe = node or shutil.which("node") or "node"
    try:
        p = subprocess.run(
            [exe, str(script), str(root)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        raise AnalyzeError(f"analyzer failed: {e}") from e
    if p.returncode != 0:
        raise AnalyzeError(f"analyzer failed: {p.stderr[-1000:]}")
    try:
        data = json.loads(p.stdout)
    except json.JSONDecodeError as e:
        raise AnalyzeError(f"analyzer output unparseable: {e}") from e
    return dict(data.get("files", {}))


def dependency_order(files: dict[str, dict[str, list[str]]]) -> list[str]:
    """Topological order, dependencies first. Raises AnalyzeError on cycles."""
    order: list[str] = []
    visited: dict[str, str] = {}  # rel -> white/gray/black

    def visit(node: str, stack: list[str]) -> None:
        state = visited.get(node, "white")
        if state == "black":
            return
        if state == "gray":
            raise AnalyzeError(f"import cycle: {' -> '.join([*stack, node])}")
        visited[node] = "gray"
        for dep in files.get(node, {}).get("imports", []):
            if dep in files:
                visit(dep, [*stack, node])
        visited[node] = "black"
        order.append(node)

    for rel in sorted(files):
        visit(rel, [])
    return order


def map_packages(packages: list[str]) -> dict[str, str | None]:
    """npm package -> PyPI equivalent (None = no equivalent, flagged)."""
    return {p: NPM_TO_PYPI.get(p) for p in packages}


def unmapped_packages(files: dict[str, dict[str, list[str]]]) -> list[str]:
    seen: list[str] = []
    for info in files.values():
        for pkg, mapped in map_packages(info.get("packages", [])).items():
            if mapped is None and pkg not in seen:
                seen.append(pkg)
    return seen


def exported_functions(js_source: str) -> list[str]:
    """Top-level function names (v1 heuristic for harness seeding)."""
    import re

    names: list[str] = []
    for m in re.finditer(
        r"(?:^|\n)\s*(?:function\s+([\w$]+)|const\s+([\w$]+)\s*=\s*(?:async\s*)?\()", js_source
    ):
        name = m.group(1) or m.group(2)
        if name and name not in names:
            names.append(name)
    return names


def function_arity(js_source: str, fn: str) -> int | None:
    """Parameter count from the JS definition. None if not found."""
    import re

    pats = [
        rf"function\s+{re.escape(fn)}\s*\(([^)]*)\)",
        rf"const\s+{re.escape(fn)}\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>",
        rf"const\s+{re.escape(fn)}\s*=\s*(?:async\s*)?function\s*\(([^)]*)\)",
    ]
    for pat in pats:
        m = re.search(pat, js_source)
        if m:
            raw = m.group(1).strip()
            if not raw:
                return 0
            return len([p for p in raw.split(",") if p.strip()])
    return None


def extract_py_signatures(py_code: str) -> str:
    """One-line-per-def signatures from converted Python (for dependent prompts)."""
    try:
        tree = ast.parse(py_code)
    except SyntaxError:
        return "(unparseable)"
    lines: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = []
            for a in node.args.args:
                ann = ast.unparse(a.annotation) if a.annotation else "?"
                args.append(f"{a.arg}: {ann}")
            ret = ast.unparse(node.returns) if node.returns else "?"
            lines.append(f"def {node.name}({', '.join(args)}) -> {ret}")
    return "\n".join(lines) or "(no functions)"
