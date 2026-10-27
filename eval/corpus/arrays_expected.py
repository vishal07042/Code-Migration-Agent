"""Reference conversion of eval/corpus/arrays.js (verified: static clean, 100% diff)."""

import functools
import math
from typing import Any


def _same_value_zero(a: Any, b: Any) -> bool:
    """JS Set semantics: NaN equals NaN; -0/+0/0 all equal; bool never equals a number."""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return bool(a == b)


def unique(xs: list[Any]) -> list[Any]:
    out: list[Any] = []
    for x in xs:
        if not any(_same_value_zero(x, y) for y in out):
            # JS Sets canonicalize -0 to +0 (SameValueZero): observable via -0 vs +0.
            out.append(0.0 if isinstance(x, float) and x == 0 else x)
    return out


def sortedNumeric(xs: list[float]) -> list[float]:
    def cmp(a: float, b: float) -> int:
        if a < b:
            return -1
        if a > b:
            return 1
        return 0

    return sorted(xs, key=functools.cmp_to_key(cmp))


def flattenOnce(xs: list[Any]) -> list[Any]:
    out: list[Any] = []
    for x in xs:
        if isinstance(x, list):
            out.extend(x)
        else:
            out.append(x)
    return out
