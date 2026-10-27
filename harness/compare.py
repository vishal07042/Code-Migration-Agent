"""Normalized deep equality between the JS oracle value and the target value.

Rules (v1):
- NaN equals NaN (both sides); +/-Infinity equal by sign.
- -0 and +0 are DISTINCT (catches trap #3); use is_negzero.
- Numbers: int/int compare exactly; anything involving a float uses
  math.isclose with rel_tol (default 1e-9). bool never equals a number.
- undefined vs null: distinct unless undefined_null_distinct=False.
- Dict key order is ignored (Python dicts preserve insertion order anyway).
"""

from __future__ import annotations

import datetime as _dt
import math
from typing import Any

from oracle.tagged_json import UNDEFINED, is_negzero


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _eq(a: Any, b: Any, path: str, rel_tol: float) -> str | None:
    """Return None when equal, else a human-readable reason rooted at path."""
    if a is UNDEFINED or b is UNDEFINED:
        if a is UNDEFINED and b is UNDEFINED:
            return None
        return f"{path}: undefined !== {type(b).__name__}"
    if a is None or b is None:
        if a is None and b is None:
            return None
        return f"{path}: null !== {type(b if a is None else a).__name__}"
    if isinstance(a, bool) or isinstance(b, bool):
        if isinstance(a, bool) and isinstance(b, bool):
            return None if a == b else f"{path}: {a!r} !== {b!r}"
        return f"{path}: bool !== {type(b if isinstance(a, bool) else a).__name__}"
    if _is_num(a) and _is_num(b):
        if isinstance(a, float) and math.isnan(a):
            return None if (isinstance(b, float) and math.isnan(b)) else f"{path}: NaN !== {b!r}"
        if isinstance(b, float) and math.isnan(b):
            return f"{path}: {a!r} !== NaN"
        assert isinstance(a, (int, float)) and isinstance(b, (int, float))
        if a == 0 and b == 0:
            if is_negzero(float(a)) != is_negzero(float(b)):
                return f"{path}: -0 !== +0"
            return None
        if isinstance(a, int) and isinstance(b, int):
            return None if a == b else f"{path}: {a!r} !== {b!r}"
        if math.isinf(float(a)) or math.isinf(float(b)):
            return None if float(a) == float(b) else f"{path}: {a!r} !== {b!r}"
        if math.isclose(float(a), float(b), rel_tol=rel_tol, abs_tol=0.0):
            return None
        return f"{path}: {a!r} !== {b!r} (beyond {rel_tol} rel)"
    if isinstance(a, str) and isinstance(b, str):
        return None if a == b else f"{path}: {a!r} !== {b!r}"
    if isinstance(a, _dt.datetime) and isinstance(b, _dt.datetime):
        if (a.tzinfo is None) != (b.tzinfo is None):
            return f"{path}: naive datetime !== aware datetime"
        return None if a == b else f"{path}: {a.isoformat()} !== {b.isoformat()}"
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return f"{path}: len {len(a)} !== {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            r = _eq(x, y, f"{path}[{i}]", rel_tol)
            if r is not None:
                return r
        return None
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a.keys()) != set(b.keys()):
            extra = sorted(set(a.keys()) - set(b.keys()), key=repr)
            missing = sorted(set(b.keys()) - set(a.keys()), key=repr)
            return f"{path}: keys differ extra={extra} missing={missing}"
        for k in sorted(a.keys(), key=repr):
            r = _eq(a[k], b[k], f"{path}.{k}", rel_tol)
            if r is not None:
                return r
        return None
    if type(a) is not type(b):
        return f"{path}: {type(a).__name__} !== {type(b).__name__}"
    try:
        equal = bool(a == b)
    except (TypeError, ValueError):
        return f"{path}: uncomparable {type(a).__name__}"
    return None if equal else f"{path}: {a!r} !== {b!r}"


def compare_values(
    a: Any,
    b: Any,
    *,
    rel_tol: float = 1e-9,
    undefined_null_distinct: bool = True,
) -> tuple[bool, str]:
    """Return (equal, reason). reason is 'match' when equal."""
    if ((a is UNDEFINED and b is None) or (a is None and b is UNDEFINED)) and (
        not undefined_null_distinct
    ):
        return True, "match (undefined ~ null per config)"
    r = _eq(a, b, "$", rel_tol)
    return (True, "match") if r is None else (False, r)
