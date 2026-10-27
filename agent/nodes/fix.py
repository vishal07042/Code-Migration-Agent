"""Diagnose+fix helpers: patch formats, failure fingerprints, prompt rendering."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from agent.state import Diag, Mismatch

_SEARCH_OPEN = "<<<<<<< SEARCH"
_SEARCH_MID = "======="
_SEARCH_CLOSE = ">>>>>>>"


class PatchError(ValueError):
    """Patch is malformed or does not apply cleanly."""


def _norm_text(msg: str) -> str:
    m = msg.lower()
    m = re.sub(r"0x[0-9a-f]+", "#", m)
    m = re.sub(r"'[^']*'|\"[^\"]*\"", "#str", m)
    m = re.sub(r"\b\d+(\.\d+)?\b", "#", m)
    m = re.sub(r"[\w./\\-]+\.(py|js|ts)", "#file", m)
    return re.sub(r"\s+", " ", m).strip()[:300]


def fingerprint(static_errors: list[Diag], mismatches: list[Mismatch]) -> str:
    """Stable hash of normalized failures for repeated-error detection."""
    parts = [f"{d.tool}|{d.code or ''}|{_norm_text(d.message)}" for d in static_errors]
    parts += [
        f"{m.function}|{_norm_text(m.js_output)}|{_norm_text(m.target_output)}" for m in mismatches
    ]
    return hashlib.sha256("\n".join(sorted(parts)).encode()).hexdigest()[:16]


def apply_search_replace(original: str, patch_text: str) -> str:
    """Apply one or more search/replace blocks. Each SEARCH must match exactly once."""
    if _SEARCH_OPEN not in patch_text:
        raise PatchError("no search/replace blocks found")
    result = original
    blocks = patch_text.split(_SEARCH_OPEN)[1:]
    for n, block in enumerate(blocks, 1):
        if _SEARCH_MID not in block or _SEARCH_CLOSE not in block:
            raise PatchError(f"block {n}: missing ======= or >>>>>>> delimiter")
        search, rest = block.split(_SEARCH_MID, 1)
        replacement, _ = rest.split(_SEARCH_CLOSE, 1)
        search = search.strip("\n")
        # Preserve trailing-newline intent of the replacement.
        replacement = replacement.strip("\n")
        hits = result.count(search)
        if hits != 1:
            raise PatchError(f"block {n}: search text found {hits} times (need exactly 1)")
        result = result.replace(search, replacement)
        if not result.endswith("\n"):
            result += "\n"
    return result


def apply_unified_diff(original: str, diff_text: str) -> str:
    """Minimal single-file unified-diff applier (---/+++/@@ hunks)."""
    lines = original.split("\n")
    out: list[str] = []
    cursor = 0
    hunk_no = 0
    i = 0
    body = [ln for ln in diff_text.splitlines() if not ln.startswith(("--- ", "+++ "))]
    while i < len(body):
        line = body[i]
        m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if not m:
            i += 1
            continue
        hunk_no += 1
        start = int(m.group(1))
        idx = max(start - 1, 0)
        out.extend(lines[cursor:idx])
        cursor = idx
        i += 1
        while i < len(body) and not body[i].startswith("@@"):
            h = body[i]
            if h.startswith(" ") or h == "":
                if cursor >= len(lines):
                    raise PatchError(f"hunk {hunk_no}: context beyond EOF")
                out.append(lines[cursor])
                cursor += 1
            elif h.startswith("-"):
                if cursor >= len(lines) or lines[cursor] != h[1:]:
                    raise PatchError(f"hunk {hunk_no}: removal does not match source")
                cursor += 1
            elif h.startswith("+"):
                out.append(h[1:])
            elif h.startswith("\\"):
                pass  # "\ No newline at end of file"
            else:
                raise PatchError(f"hunk {hunk_no}: bad line {h[:40]!r}")
            i += 1
    out.extend(lines[cursor:])
    text = "\n".join(out)
    if original.endswith("\n") and not text.endswith("\n"):
        text += "\n"
    if hunk_no == 0:
        raise PatchError("no hunks found")
    return text


def apply_patch(original: str, patch_text: str) -> str:
    """Auto-detect format: unified diff (starts with ---) or search/replace."""
    stripped = patch_text.lstrip()
    if stripped.startswith(("--- ", "---\n")):
        return apply_unified_diff(original, patch_text)
    return apply_search_replace(original, patch_text)


def format_diags(diags: list[Diag], limit: int = 10) -> str:
    return (
        "\n".join(
            f"[{d.tool}] {d.file}:{d.line or '?'} {d.code or ''} {d.message}" for d in diags[:limit]
        )
        or "(no static errors)"
    )


def format_mismatches(mismatches: list[Mismatch], limit: int = 5) -> str:
    return (
        "\n".join(
            f"{m.function} input={m.input_json} js={m.js_output} target={m.target_output}"
            for m in mismatches[:limit]
        )
        or "(no mismatches)"
    )


def render_fix_prompt(
    converted: str,
    diags: list[Diag],
    mismatches: list[Mismatch],
    *,
    template_path: str | Path | None = None,
    strategy_note: str = "",
) -> str:
    """Fill agent/prompts/fix.md. Only failing-function evidence is passed in."""
    path = (
        Path(template_path)
        if template_path
        else Path(__file__).resolve().parents[1] / "prompts" / "fix.md"
    )
    template = path.read_text(encoding="utf-8")
    report = f"STATIC:\n{format_diags(diags)}\nMISMATCHES:\n{format_mismatches(mismatches)}"
    if strategy_note:
        report += f"\nSTRATEGY: {strategy_note}"
    out = template.replace("{diags_or_mismatches}", report)
    out = out.replace("{cases}", format_mismatches(mismatches))
    out = out.replace("{converted}", converted)
    return out


def failure_count(static_errors: list[Diag], mismatches: list[Mismatch]) -> int:
    return len(static_errors) + len(mismatches)


def render_fix_prompt_from_state(state: dict[str, Any], *, wide: bool = False) -> str:
    note = (
        "Rewrite the failing function(s) from scratch using the failing cases below."
        if wide
        else ""
    )
    return render_fix_prompt(
        state.get("converted", ""),
        list(state.get("static_errors", [])),
        list(state.get("mismatches", [])),
        strategy_note=note,
    )
