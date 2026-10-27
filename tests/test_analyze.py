"""Milestone 7 tests: dependency order (leaves first) + signatures."""

import shutil

import pytest

from agent.nodes.analyze import (
    dependency_order,
    exported_functions,
    extract_py_signatures,
    function_arity,
    map_packages,
    run_analyzer,
    unmapped_packages,
)

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node missing")


def test_order_leaves_first():
    files = {
        "a.js": {"imports": ["b.js", "c.js"]},
        "b.js": {"imports": ["c.js"]},
        "c.js": {"imports": []},
        "lonely.js": {"imports": []},
    }
    order = dependency_order(files)
    assert order.index("c.js") < order.index("b.js") < order.index("a.js")
    assert set(order) == set(files)


def test_cycle_raises():
    import re

    from agent.nodes.analyze import AnalyzeError

    with pytest.raises(AnalyzeError, match=re.compile("cycle")):
        dependency_order({"a.js": {"imports": ["b.js"]}, "b.js": {"imports": ["a.js"]}})


def test_package_mapping_flags_unknown():
    mapped = map_packages(["date-fns", "left-pad"])
    assert mapped["date-fns"] == "python-dateutil"
    assert mapped["left-pad"] is None
    files = {"a.js": {"packages": ["left-pad", "axios"]}}
    assert unmapped_packages(files) == ["left-pad"]


def test_signatures_and_arity():
    py = "def add(a: int, b: int) -> int:\n    return a + b\n"
    sigs = extract_py_signatures(py)
    assert "def add(a: int, b: int) -> int" in sigs
    assert extract_py_signatures("x = 1\n") == "(no functions)"
    js = "function add(a, b) { return a + b; }\nconst sub = (x, y) => x - y;\n"
    assert set(exported_functions(js)) == {"add", "sub"}
    assert function_arity(js, "add") == 2
    assert function_arity(js, "sub") == 2
    assert function_arity(js, "nope") is None


@needs_node
def test_analyzer_on_fixture_repo(tmp_path):
    (tmp_path / "b.js").write_text(
        "function b() { return 1; }\nmodule.exports = { b };\n", encoding="utf-8"
    )
    (tmp_path / "a.js").write_text(
        "const { b } = require('./b');\nconst _ = require('left-pad');\n"
        "function a() { return b(); }\nmodule.exports = { a };\n",
        encoding="utf-8",
    )
    files = run_analyzer(tmp_path)
    assert set(files) == {"a.js", "b.js"}
    assert files["a.js"]["imports"] == ["b.js"]
    assert "b" in files["b.js"]["exports"]
    order = dependency_order(files)
    assert order == ["b.js", "a.js"]
    assert unmapped_packages(files) == ["left-pad"]
