"""Gate: pure routing decision after static check + differential run."""

from __future__ import annotations

from typing import Literal

from agent.state import Diag, Mismatch

GateDecision = Literal["critic", "fix", "fix_wide", "escalate"]


def decide(
    *,
    static_errors: list[Diag],
    mismatches: list[Mismatch],
    attempts: int,
    fingerprints: list[str],
    max_attempts: int,
) -> GateDecision:
    """all green -> critic; cap hit -> escalate; repeat error -> widen; else fix."""
    if not static_errors and not mismatches:
        return "critic"
    if attempts >= max_attempts:
        return "escalate"
    if len(fingerprints) >= 2 and fingerprints[-1] == fingerprints[-2]:
        return "fix_wide"
    return "fix"
