"""Milestone 2 tests: tagged-JSON round-trips + oracle runner.js e2e.

Covers: undefined, NaN, -0, big ints (plus Inf, Date, null-distinct).
Bugs here silently invalidate the eval, so this is the most thorough suite.
"""

from __future__ import annotations

import datetime
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from oracle.tagged_json import (
    NEGZERO,
    UNDEFINED,
    decode,
    dumps_tagged,
    encode,
    is_negzero,
    loads_tagged,
)

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not found on PATH")


def test_undefined_distinct_from_none():
    assert loads_tagged('{"$undefined":1}') is UNDEFINED
    assert loads_tagged("null") is None
    assert UNDEFINED is not None
    assert dumps_tagged(UNDEFINED) == '{"$undefined": 1}'
    assert dumps_tagged(None) == "null"
    assert not UNDEFINED


def test_nan_roundtrip():
    v = loads_tagged(dumps_tagged(float("nan")))
    assert isinstance(v, float) and math.isnan(v)
    assert '{"$nan"' in dumps_tagged(float("nan"))


def test_negzero_roundtrip_and_detected():
    assert is_negzero(float("-0.0"))
    assert not is_negzero(0.0)
    assert not is_negzero(1.0)
    assert is_negzero(loads_tagged(dumps_tagged(float("-0.0"))))
    assert '{"$negzero"' in dumps_tagged(NEGZERO)
    # +0 must NOT use the tag
    assert dumps_tagged(0.0) == "0.0"


def test_infinities():
    assert loads_tagged(dumps_tagged(float("inf"))) == float("inf")
    assert loads_tagged(dumps_tagged(float("-inf"))) == float("-inf")


def test_bigint_as_int_beyond_safe_integer():
    big = 2**70 + 12345
    assert big > 9007199254740991  # Number.MAX_SAFE_INTEGER
    wire = dumps_tagged({"n": big})
    # Unsafe ints are tagged so JS decodes them as BigInt, not rounded Number.
    assert json.loads(wire) == {"n": {"$bigint": str(big)}}
    assert loads_tagged(wire) == {"n": big}
    # Safe ints stay plain JSON numbers.
    assert json.loads(dumps_tagged({"n": 42})) == {"n": 42}


def test_date_roundtrip_utc():
    d = datetime.datetime(2026, 3, 4, 5, 6, 7, tzinfo=datetime.UTC)
    v = loads_tagged(dumps_tagged(d))
    assert isinstance(v, datetime.datetime)
    assert v.astimezone(datetime.UTC) == d


def test_nested_and_holes_like():
    obj = {"a": [1, UNDEFINED, {"b": float("nan")}], "c": None}
    assert loads_tagged(dumps_tagged(obj))["c"] is None
    rt = loads_tagged(dumps_tagged(obj))
    assert rt["a"][1] is UNDEFINED
    assert math.isnan(rt["a"][2]["b"])


@needs_node
def test_js_encode_python_decode_parity(tmp_path):
    """Encode edge values in Node, decode in Python."""
    script = tmp_path / "enc.js"
    script.write_text(
        "const {encode} = require(" + json.dumps(str(REPO / "oracle" / "tagged_json.js")) + ");\n"
        "const cases = [undefined, null, NaN, -0, 0, Infinity, -Infinity,"
        " 10n ** 30n, new Date('2026-01-02T03:04:05.000Z'),"
        " [1, undefined, 3], {a: undefined, b: NaN}];\n"
        "for (const c of cases) console.log(encode(c));\n",
        encoding="utf-8",
    )
    p = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=30, check=False)
    assert p.returncode == 0, p.stderr
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    assert len(lines) == 11
    assert loads_tagged(lines[0]) is UNDEFINED
    assert loads_tagged(lines[1]) is None
    assert math.isnan(loads_tagged(lines[2]))
    assert is_negzero(loads_tagged(lines[3]))
    assert loads_tagged(lines[4]) == 0.0 and not is_negzero(loads_tagged(lines[4]))
    assert loads_tagged(lines[5]) == float("inf")
    assert loads_tagged(lines[6]) == float("-inf")
    assert loads_tagged(lines[7]) == 10**30
    assert loads_tagged(lines[8]) == datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.UTC)
    holey = loads_tagged(lines[9])
    assert holey == [1, UNDEFINED, 3]
    obj = loads_tagged(lines[10])
    assert obj["a"] is UNDEFINED and math.isnan(obj["b"])


@needs_node
def test_python_encode_js_decode_parity(tmp_path):
    """Encode in Python, decode in Node, compare with Object.is semantics."""
    wire_lines = [
        dumps_tagged(UNDEFINED),
        dumps_tagged(None),
        dumps_tagged(float("nan")),
        dumps_tagged(float("-0.0")),
        dumps_tagged(10**40),
    ]
    script = tmp_path / "dec.js"
    script.write_text(
        "const {decodeValue} = require("
        + json.dumps(str(REPO / "oracle" / "tagged_json.js"))
        + ");\n"
        "const fs = require('fs');\n"
        "const lines = fs.readFileSync(0, 'utf8').split(/\\r?\\n/).filter(Boolean);\n"
        "const out = lines.map((l) => decodeValue(JSON.parse(l)));\n"
        "const checks = [\n"
        "  out[0] === undefined,\n"
        "  out[1] === null,\n"
        "  Number.isNaN(out[2]),\n"
        "  Object.is(out[3], -0),\n"
        "  out[4] === 10n ** 40n,\n"
        "];\n"
        "console.log(JSON.stringify(checks));\n",
        encoding="utf-8",
    )
    p = subprocess.run(
        [NODE, str(script)],
        input="\n".join(wire_lines),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout.strip()) == [True] * 5


@needs_node
def test_runner_js_end_to_end(tmp_path):
    mod = tmp_path / "sample.js"
    mod.write_text(
        "module.exports = {\n"
        "  add: (a, b) => a + b,\n"
        "  retUndefined: () => undefined,\n"
        "  retNull: () => null,\n"
        "  retNaN: () => NaN,\n"
        "  retNegZero: () => -0,\n"
        "  retBig: () => 2n ** 70n,\n"
        "  retDate: () => new Date('2026-05-06T00:00:00.000Z'),\n"
        "  boom: () => { throw new Error('kaput'); },\n"
        "};\n",
        encoding="utf-8",
    )
    reqs = [
        {"function": "add", "args": [2, 3]},
        {"function": "retUndefined", "args": []},
        {"function": "retNull", "args": []},
        {"function": "retNaN", "args": []},
        {"function": "retNegZero", "args": []},
        {"function": "retBig", "args": []},
        {"function": "retDate", "args": []},
        {"function": "boom", "args": []},
        {"function": "missing", "args": []},
    ]
    stdin = "\n".join(dumps_tagged(r) for r in reqs) + "\n"
    p = subprocess.run(
        [NODE, str(REPO / "oracle" / "runner.js"), str(mod)],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert p.returncode == 0, p.stderr
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    assert len(lines) == len(reqs)
    resps = [json.loads(ln) for ln in lines]

    assert resps[0] == {"ok": True, "result": 5}
    assert resps[1]["ok"] is True and loads_tagged(json.dumps(resps[1]["result"])) is UNDEFINED
    assert resps[2] == {"ok": True, "result": None}
    assert math.isnan(loads_tagged(json.dumps(resps[3]["result"])))
    assert is_negzero(loads_tagged(json.dumps(resps[4]["result"])))
    assert loads_tagged(json.dumps(resps[5]["result"])) == 2**70
    assert loads_tagged(json.dumps(resps[6]["result"])) == datetime.datetime(
        2026, 5, 6, tzinfo=datetime.UTC
    )
    assert resps[7]["ok"] is False and "kaput" in resps[7]["error"]
    assert resps[8]["ok"] is False


def test_oracle_module_importable_from_repo_root():
    # Guards against sys.path issues when pytest runs from elsewhere.
    assert (REPO / "oracle" / "tagged_json.py").exists()
    assert encode is not None and decode is not None
    assert sys.version_info >= (3, 11)
