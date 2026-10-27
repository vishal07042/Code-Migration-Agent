"""Milestone 4 tests: JS literal parsing + Jest seed extraction."""

import math

from harness.seeds import extract_seeds, parse_js_literal
from oracle.tagged_json import UNDEFINED, is_negzero


def test_numbers():
    assert parse_js_literal("42") == 42
    assert parse_js_literal("0xFF") == 255
    assert parse_js_literal("1e3") == 1000.0
    assert parse_js_literal("-0") == float("-0.0") and is_negzero(parse_js_literal("-0"))
    assert math.isnan(parse_js_literal("NaN"))
    assert parse_js_literal("Infinity") == float("inf")
    assert parse_js_literal("-Infinity") == float("-inf")
    assert parse_js_literal("10n") == 10
    assert parse_js_literal("0.5") == 0.5


def test_strings_keywords():
    assert parse_js_literal("'hi'") == "hi"
    assert parse_js_literal('"a\\nb"') == "a\nb"
    assert parse_js_literal("`tmpl`") == "tmpl"
    assert parse_js_literal("true") is True
    assert parse_js_literal("null") is None
    assert parse_js_literal("undefined") is UNDEFINED


def test_containers_and_holes():
    assert parse_js_literal("[1, 'a', null]") == [1, "a", None]
    assert parse_js_literal("[1,,3]") == [1, UNDEFINED, 3]
    assert parse_js_literal("{a: 1, 'b-c': [true]}") == {"a": 1, "b-c": [True]}
    assert parse_js_literal("{a: 1,}") == {"a": 1}  # trailing comma
    assert parse_js_literal("/*c*/ 5 // x") == 5


def test_extract_from_jest_style():
    src = """
    import { add, greet } from './m';
    test('add', () => {
      expect(add(2, 3)).toBe(5);
      expect(add(-0, 0)).toBe(0);
    });
    test('greet', () => {
      expect(greet('Ada', {loud: true})).toBe('Hi Ada');
      const name = getName();
      expect(greet(name)).toBe('?');       // non-literal: skipped
      expect(greet(`Bo`, undefined)).toBe('Hi Bo');
    });
    """
    assert extract_seeds(src, "add") == [[2, 3], [float("-0.0"), 0]]
    assert extract_seeds(src, "greet") == [["Ada", {"loud": True}], ["Bo", UNDEFINED]]
    assert extract_seeds(src, "missing") == []


def test_dedupe_and_cap():
    src = "expect(f(1)).toBe(1); expect(f(1)).toBe(1); expect(f(2)).toBe(2);"
    assert extract_seeds(src, "f") == [[1], [2]]
