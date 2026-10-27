"""Anti-cheat enforcement (code, not just prompts).

- snapshot/verify: hash oracle + test files at start/end of every run.
- scan: stub / type-escape-hatch / hardcoded-output heuristics with density.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

_ANY_RE = re.compile(r"\bAny\b")
_TYPE_IGNORE_RE = re.compile(r"#\s*type:\s*ignore")
_TS_IGNORE_RE = re.compile(r"@ts-ignore|@ts-nocheck")
_AS_ANY_RE = re.compile(r"\bas\s+any\b")
_STUB_RES = [
    re.compile(r"raise\s+NotImplementedError"),
    re.compile(r"^\s*\.\.\.\s*$", re.MULTILINE),
]


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(paths: list[str | Path]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in paths:
        pp = Path(p)
        if pp.is_file():
            out[str(pp.resolve())] = sha256_file(pp)
    return out


def verify(snap: dict[str, str]) -> list[str]:
    """Files changed or missing since snapshot (empty = untouched)."""
    changed: list[str] = []
    for name, digest in snap.items():
        pp = Path(name)
        if not pp.is_file() or sha256_file(pp) != digest:
            changed.append(name)
    return changed


def any_density(code: str) -> float:
    """Occurrences of bare `Any` per non-empty line."""
    lines = [ln for ln in code.splitlines() if ln.strip()]
    if not lines:
        return 0.0
    return len(_ANY_RE.findall(code)) / len(lines)


def _is_stub_body(code: str, func_name: str) -> bool:
    """True if func_name's body is only pass/.../raise/stub."""
    m = re.search(
        rf"^def\s+{re.escape(func_name)}\s*\(.*?\)[^:]*:(.*?)(?=^def\s|\Z)",
        code,
        re.DOTALL | re.MULTILINE,
    )
    if not m:
        return False
    body_lines = [
        ln
        for ln in m.group(1).splitlines()
        if ln.strip() and not ln.strip().startswith(("#", '"""', "'''"))
    ]
    if not body_lines:
        return True
    stripped = [ln.strip() for ln in body_lines]
    return all(
        ln
        in (
            "pass",
            "...",
            "return None",
            "return",
            "return {}",
            "return []",
            'return ""',
            "return 0",
            "return False",
        )
        or ln.startswith("raise NotImplementedError")
        for ln in stripped
    )


def scan(
    converted: str,
    *,
    source_functions: list[str] | None = None,
    any_threshold: float = 0.05,
) -> list[str]:
    """Return cheat flag strings (empty = clean)."""
    flags: list[str] = []
    if _TYPE_IGNORE_RE.search(converted):
        flags.append("type-ignore")
    if _TS_IGNORE_RE.search(converted) or _AS_ANY_RE.search(converted):
        flags.append("ts-any-escape")
    density = any_density(converted)
    if density > any_threshold:
        flags.append(f"any-density {density:.3f} > {any_threshold}")
    if any(r.search(converted) for r in _STUB_RES):
        flags.append("stub-marker")
    for fn in source_functions or []:
        if _is_stub_body(converted, fn):
            flags.append(f"stub-body:{fn}")
    return flags


def report_line(extra: dict[str, Any] | None = None) -> str:
    extra = extra or {}
    bits = [f"{k} {v}" for k, v in extra.items()]
    return "migrated " + (" ".join(bits) if bits else "(no stats)")
