"""Reference conversion of eval/corpus/strings.js (verified: static clean, 100% diff)."""

import re


def capitalize(s: str) -> str:
    # Char-level indexing is observably correct: JS unit-level output for
    # astral chars recombines over the JSON wire to the same scalar value.
    # (A lone-surrogate result, e.g. slice(0, 1) of emoji, stays lone: T5.)
    if not s:
        return s
    return s[0].upper() + s[1:]


def repeat(s: str, n: int) -> str:
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError("repeat: non-negative integer expected")
    if n < 0:
        raise ValueError("repeat: non-negative integer expected")
    return s * n


def words(s: str) -> list[str]:
    t = s.strip()
    if t == "":
        return []
    return re.split(r"\s+", t)
