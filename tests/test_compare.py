"""Milestone 4 tests: normalized comparison."""

import datetime

from harness.compare import compare_values
from oracle.tagged_json import UNDEFINED


def test_match_simple():
    assert compare_values(1, 1) == (True, "match")
    assert compare_values("a", "a")[0]
    assert compare_values([1, {"x": None}], [1, {"x": None}])[0]


def test_nan_equals_nan():
    ok, _ = compare_values(float("nan"), float("nan"))
    assert ok
    assert not compare_values(float("nan"), 1.0)[0]
    assert not compare_values(1.0, float("nan"))[0]


def test_negzero_distinct_from_poszero():
    assert compare_values(float("-0.0"), float("-0.0"))[0]
    ok, reason = compare_values(float("-0.0"), 0.0)
    assert not ok and "-0" in reason
    assert compare_values(0, 0)[0]


def test_infinities():
    assert compare_values(float("inf"), float("inf"))[0]
    assert not compare_values(float("inf"), float("-inf"))[0]


def test_float_tolerance():
    assert compare_values(0.1 + 0.2, 0.3)[0]  # classic float dust
    assert compare_values(0.1 + 0.2, 0.3, rel_tol=1e-17)[0] is False
    assert compare_values(2**70, 2**70 + 1)[0] is False  # ints exact


def test_undefined_null_modes():
    assert not compare_values(UNDEFINED, None)[0]
    assert compare_values(UNDEFINED, UNDEFINED)[0]
    assert compare_values(None, None)[0]
    ok, _ = compare_values(UNDEFINED, None, undefined_null_distinct=False)
    assert ok


def test_bool_never_equals_number():
    assert not compare_values(True, 1)[0]
    assert compare_values(True, True)[0]


def test_nested_reason_points_at_index():
    ok, reason = compare_values({"a": [1, 2]}, {"a": [1, 3]})
    assert not ok and "$.a[1]" in reason


def test_key_set_mismatch():
    ok, reason = compare_values({"a": 1}, {"a": 1, "b": 2})
    assert not ok and "keys differ" in reason


def test_datetimes():
    d = datetime.datetime(2026, 5, 6, tzinfo=datetime.UTC)
    assert compare_values(d, d)[0]
    naive = datetime.datetime(2026, 5, 6)  # noqa: DTZ001 - intentionally naive
    assert not compare_values(naive, d)[0]
