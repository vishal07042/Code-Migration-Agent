"""Reference conversion of eval/corpus/truthiness.js (verified: static clean, 100% diff)."""

import math
from typing import Any

from oracle.tagged_json import UNDEFINED


def js_truthy(x: Any) -> bool:
    """JS truthiness: only false, 0/-0, '', null, undefined, NaN are falsy."""
    if x is UNDEFINED or x is None:
        return False
    if isinstance(x, bool):
        return x
    if isinstance(x, int):
        return x != 0
    if isinstance(x, float):
        return not math.isnan(x) and x != 0.0
    if isinstance(x, str):
        return len(x) > 0
    return True


def toLabel(x: Any) -> str:
    return "yes" if js_truthy(x) else "no"
