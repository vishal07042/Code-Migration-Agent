"""Python mirror of oracle/tagged_json.js.

JS undefined <-> UNDEFINED sentinel (distinct from None).
JS NaN <-> float('nan'), Infinity <-> float('inf'), -Infinity <-> float('-inf').
JS -0 <-> NEGZERO (float('-0.0')); use is_negzero() to detect.
JS BigInt <-> Python int. JS Date <-> datetime (UTC).
"""

from __future__ import annotations

import datetime as _dt
import json
import math
from typing import Any

TAG_UNDEFINED = "$undefined"
TAG_NAN = "$nan"
TAG_INF = "$inf"
TAG_NEGINF = "$neginf"
TAG_NEGZERO = "$negzero"
TAG_BIGINT = "$bigint"
TAG_DATE = "$date"

_KNOWN_TAGS = frozenset(
    [TAG_UNDEFINED, TAG_NAN, TAG_INF, TAG_NEGINF, TAG_NEGZERO, TAG_BIGINT, TAG_DATE]
)


class _Undefined:
    _instance: _Undefined | None = None

    def __new__(cls) -> _Undefined:  # noqa: PYI034 - singleton must return cls instance
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNDEFINED"

    def __bool__(self) -> bool:
        return False


UNDEFINED = _Undefined()
NEGZERO: float = float("-0.0")
MAX_SAFE_INTEGER = 2**53 - 1


def is_negzero(v: Any) -> bool:
    return isinstance(v, float) and v == 0.0 and math.copysign(1.0, v) < 0


def _encode_value(v: Any) -> Any:
    if v is UNDEFINED:
        return {TAG_UNDEFINED: 1}
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        # JS Numbers lose precision beyond 2**53-1; tag those so JS
        # decodes them as BigInt instead of a rounded Number.
        if abs(v) > MAX_SAFE_INTEGER:
            return {TAG_BIGINT: str(v)}
        return v
    if isinstance(v, float):
        if math.isnan(v):
            return {TAG_NAN: 1}
        if v == float("inf"):
            return {TAG_INF: 1}
        if v == float("-inf"):
            return {TAG_NEGINF: 1}
        if is_negzero(v):
            return {TAG_NEGZERO: 1}
        return v
    if isinstance(v, str):
        return v
    if v is None:
        return None
    if isinstance(v, _dt.datetime):
        d = v if v.tzinfo is not None else v.replace(tzinfo=_dt.UTC)
        return {TAG_DATE: d.astimezone(_dt.UTC).isoformat().replace("+00:00", "Z")}
    if isinstance(v, (list, tuple)):
        return [_encode_value(x) for x in v]
    if isinstance(v, dict):
        keys = list(v.keys())
        if len(keys) == 1 and isinstance(keys[0], str) and keys[0] in _KNOWN_TAGS:
            return {"$escaped": _encode_value(v[keys[0]])}
        return {str(k): _encode_value(v[k]) for k in keys}
    raise TypeError(f"Cannot tagged-encode value of type {type(v).__name__}: {v!r}")


def _decode_value(v: Any) -> Any:
    if isinstance(v, list):
        return [_decode_value(x) for x in v]
    if isinstance(v, dict):
        keys = list(v.keys())
        if len(keys) == 1 and keys[0] in _KNOWN_TAGS:
            k = keys[0]
            if k == TAG_UNDEFINED:
                return UNDEFINED
            if k == TAG_NAN:
                return float("nan")
            if k == TAG_INF:
                return float("inf")
            if k == TAG_NEGINF:
                return float("-inf")
            if k == TAG_NEGZERO:
                return float("-0.0")
            if k == TAG_BIGINT:
                return int(str(v[k]))
            if k == TAG_DATE:
                s = str(v[k])
                if s.endswith("Z"):
                    s = s[:-1] + "+00:00"
                return _dt.datetime.fromisoformat(s)
        if len(keys) == 1 and keys[0] == "$escaped":
            return {"$escaped": _decode_value(v[keys[0]])}
        return {k: _decode_value(v[k]) for k in keys}
    return v


def dumps_tagged(obj: Any) -> str:
    return json.dumps(_encode_value(obj), ensure_ascii=False)


def loads_tagged(text: str) -> Any:
    return _decode_value(json.loads(text))


def encode(obj: Any) -> str:
    return dumps_tagged(obj)


def decode(text: str) -> Any:
    return loads_tagged(text)
