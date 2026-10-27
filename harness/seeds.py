"""Extract seed inputs from Jest-style tests by parsing JS call literals.

Only plain literals are understood (numbers, strings, booleans, null,
undefined, NaN, Infinity, -0, BigInt, arrays incl. holes, plain objects).
Calls with non-literal args (identifiers, calls, arrows, new, ...) are
skipped and counted. Deterministic: no Node needed.
"""

from __future__ import annotations

import re
from typing import Any

from oracle.tagged_json import UNDEFINED, dumps_tagged

_CALL_RE = re.compile(r"(?<![\w$])(?P<name>[A-Za-z_$][\w$]*)\s*\(")
_MAX_SEEDS = 200


class JsLiteralError(ValueError):
    """Test argument text is not a plain JS literal."""


_WS = " \t\n\r"


class _Parser:
    def __init__(self, s: str):
        self.s = s
        self.i = 0

    def ws(self) -> None:
        s = self.s
        while self.i < len(s):
            c = s[self.i]
            if c in _WS:
                self.i += 1
            elif s.startswith("//", self.i):
                j = s.find("\n", self.i)
                self.i = len(s) if j == -1 else j + 1
            elif s.startswith("/*", self.i):
                j = s.find("*/", self.i + 2)
                if j == -1:
                    raise JsLiteralError("unterminated block comment")
                self.i = j + 2
            else:
                return

    def parse_value(self) -> Any:
        self.ws()
        if self.i >= len(self.s):
            raise JsLiteralError("unexpected end of input")
        c = self.s[self.i]
        if c in "\"'":
            return self.parse_string()
        if c == "`":
            return self.parse_template()
        if c == "[":
            return self.parse_array()
        if c == "{":
            return self.parse_object()
        if c == "-" or c.isdigit() or c == ".":
            return self.parse_number()
        if c.isalpha() or c in "_$":
            return self.parse_keyword()
        raise JsLiteralError(f"unexpected character {c!r}")

    def parse_string(self) -> str:
        quote = self.s[self.i]
        self.i += 1
        out: list[str] = []
        s = self.s
        while True:
            if self.i >= len(s):
                raise JsLiteralError("unterminated string")
            c = s[self.i]
            if c == quote:
                self.i += 1
                return "".join(out)
            if c == "\\":
                self.i += 1
                if self.i >= len(s):
                    raise JsLiteralError("bad escape")
                e = s[self.i]
                table = {
                    "n": "\n",
                    "t": "\t",
                    "r": "\r",
                    "b": "\b",
                    "f": "\f",
                    "v": "\v",
                    "0": "\0",
                    "'": "'",
                    '"': '"',
                    "\\": "\\",
                    "/": "/",
                }
                if e in table:
                    out.append(table[e])
                    self.i += 1
                elif e == "u":
                    hex4 = s[self.i + 1 : self.i + 5]
                    if len(hex4) != 4 or not re.fullmatch(r"[0-9a-fA-F]{4}", hex4):
                        raise JsLiteralError("bad unicode escape")
                    out.append(chr(int(hex4, 16)))
                    self.i += 5
                elif e == "\n":
                    self.i += 1  # line continuation
                else:
                    raise JsLiteralError(f"unsupported escape \\{e}")
            elif c == "\n":
                raise JsLiteralError("newline in string")
            else:
                out.append(c)
                self.i += 1

    def parse_template(self) -> str:
        self.i += 1  # consume backtick
        j = self.s.find("`", self.i)
        if j == -1:
            raise JsLiteralError("unterminated template literal")
        body = self.s[self.i : j]
        if "${" in body:
            raise JsLiteralError("interpolated template is not a literal")
        self.i = j + 1
        return body

    def parse_array(self) -> list[Any]:
        self.i += 1  # consume [
        out: list[Any] = []
        self.ws()
        if self.i < len(self.s) and self.s[self.i] == "]":
            self.i += 1
            return out
        if self.i < len(self.s) and self.s[self.i] == ",":
            out.append(UNDEFINED)  # leading hole
        while True:
            self.ws()
            if self.i >= len(self.s):
                raise JsLiteralError("unterminated array")
            if self.s[self.i] == "]":
                self.i += 1
                return out
            if self.s[self.i] == ",":
                out.append(UNDEFINED)  # hole
                self.i += 1
                continue
            out.append(self.parse_value())
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1

    def parse_object(self) -> dict[str, Any]:
        self.i += 1  # consume {
        out: dict[str, Any] = {}
        self.ws()
        if self.i < len(self.s) and self.s[self.i] == "}":
            self.i += 1
            return out
        while True:
            self.ws()
            if self.i >= len(self.s):
                raise JsLiteralError("unterminated object")
            c = self.s[self.i]
            if c in "\"'":
                key = self.parse_string()
            elif c.isalpha() or c in "_$":
                m = re.match(r"[A-Za-z_$][\w$]*", self.s[self.i :])
                assert m is not None
                key = m.group(0)
                self.i += len(key)
            else:
                raise JsLiteralError(f"bad object key at {c!r}")
            self.ws()
            if self.i >= len(self.s) or self.s[self.i] != ":":
                raise JsLiteralError("object shorthand/method is not a literal")
            self.i += 1
            out[key] = self.parse_value()
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1
                self.ws()
                if self.i < len(self.s) and self.s[self.i] == "}":
                    self.i += 1
                    return out
                continue
            if self.i < len(self.s) and self.s[self.i] == "}":
                self.i += 1
                return out
            raise JsLiteralError("expected , or } in object")

    def parse_number(self) -> int | float:
        if self.s.startswith("-Infinity", self.i):
            self.i += len("-Infinity")
            return float("-inf")
        if self.s.startswith("-NaN", self.i):
            self.i += len("-NaN")
            return float("nan")
        m = re.match(
            r"-?(?:0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+"
            r"|\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)(n?)",
            self.s[self.i :],
        )
        if not m:
            raise JsLiteralError("bad number")
        token = m.group(0)
        self.i += len(token)
        if token.endswith("n"):
            return int(token[:-1], 0)
        negative = token.startswith("-")
        body = token[1:] if negative else token
        if re.fullmatch(r"0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+|\d+", body or "0"):
            v: int | float = int(token, 0)
            if v == 0 and negative:
                return float("-0.0")
            return v
        f = float(body)
        if f == 0.0 and negative:
            return float("-0.0")
        return -f if negative else f

    def parse_keyword(self) -> Any:
        m = re.match(r"[A-Za-z_$][\w$]*", self.s[self.i :])
        assert m is not None
        word = m.group(0)
        self.i += len(word)
        if word == "true":
            return True
        if word == "false":
            return False
        if word == "null":
            return None
        if word == "undefined":
            return UNDEFINED
        if word == "NaN":
            return float("nan")
        if word == "Infinity":
            return float("inf")
        raise JsLiteralError(f"identifier {word!r} is not a literal")

    def end(self) -> None:
        self.ws()
        if self.i != len(self.s):
            raise JsLiteralError(f"trailing text: {self.s[self.i :][:40]!r}")


def parse_js_literal(text: str) -> Any:
    """Parse one JS literal expression. Raises JsLiteralError if not literal."""
    p = _Parser(text)
    v = p.parse_value()
    p.end()
    return v


def split_top_level(s: str) -> list[str]:
    """Split on commas at nesting depth 0, respecting strings/templates."""
    parts: list[str] = []
    depth = 0
    cur: list[str] = []
    i, n = 0, len(s)
    quote: str | None = None
    while i < n:
        c = s[i]
        if quote is not None:
            cur.append(c)
            if c == "\\" and i + 1 < n:
                cur.append(s[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "\"'`":
            quote = c
            cur.append(c)
            i += 1
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    tail = "".join(cur)
    if tail.strip() or parts:
        parts.append(tail)
    return parts


def _find_call_end(s: str, open_paren: int) -> int:
    """Index of the close paren matching s[open_paren] == '('."""
    depth = 0
    i = open_paren
    n = len(s)
    quote: str | None = None
    while i < n:
        c = s[i]
        if quote is not None:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "\"'`":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise JsLiteralError("unbalanced parens")


def extract_seeds(test_source: str, function: str) -> list[list[Any]]:
    """Find literal calls `function(...)` in test source; return arg lists.

    Non-literal calls are skipped. Results deduped, capped at _MAX_SEEDS.
    """
    seeds: list[list[Any]] = []
    seen: set[str] = set()
    for m in _CALL_RE.finditer(test_source):
        if m.group("name") != function:
            continue
        open_paren = m.end() - 1
        try:
            close = _find_call_end(test_source, open_paren)
        except JsLiteralError:
            continue
        inner = test_source[open_paren + 1 : close]
        if not inner.strip():
            arg_lists: list[list[Any]] = [[]]
        else:
            try:
                arg_lists = [[parse_js_literal(a) for a in split_top_level(inner)]]
            except JsLiteralError:
                continue
        for args in arg_lists:
            try:
                key = dumps_tagged(args)
            except (TypeError, ValueError):
                continue
            if key not in seen:
                seen.add(key)
                seeds.append(args)
            if len(seeds) >= _MAX_SEEDS:
                return seeds
    return seeds


def count_skipped_calls(test_source: str, function: str) -> int:
    """Calls found minus seeds extracted (diagnostic for eval reports)."""
    total = sum(1 for m in _CALL_RE.finditer(test_source) if m.group("name") == function)
    return total - len(extract_seeds(test_source, function))
