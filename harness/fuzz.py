"""Differential runner: JS oracle (Node subprocess) vs converted Python function.

Seeds come from Jest tests (see seeds.py); fuzz inputs come from Hypothesis
strategies (generic, or derived from JSDoc @param types). Hypothesis shrinks
failing inputs; the minimal case is recovered from the assertion payload.
"""

from __future__ import annotations

import importlib.util
import json
import queue
import re
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from agent.state import Mismatch
from harness.compare import compare_values
from oracle.tagged_json import UNDEFINED, dumps_tagged, loads_tagged

RUNNER_JS = Path(__file__).resolve().parents[1] / "oracle" / "runner.js"
_SAFE_INT = 2**53 - 1


class OracleError(RuntimeError):
    """The oracle subprocess failed or timed out."""


def node_exe(node: str | None = None) -> str:
    found = node or shutil.which("node") or "node"
    return found


class OracleRunner:
    """Persistent `node oracle/runner.js <module>` process speaking NDJSON."""

    def __init__(
        self,
        module: str | Path,
        *,
        node: str | None = None,
        runner_js: str | Path = RUNNER_JS,
        timeout_s: float = 10,
    ):
        self.timeout_s = timeout_s
        self._lines: queue.Queue[str | None] = queue.Queue()
        self.proc = subprocess.Popen(
            [node_exe(node), str(runner_js), str(module)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        try:
            assert self.proc.stdout is not None
            for line in self.proc.stdout:
                self._lines.put(line)
        finally:
            self._lines.put(None)

    def call(self, function: str, args: list[Any]) -> tuple[bool, Any]:
        """Return (ok, value_or_error_message). values are tagged-decoded."""
        assert self.proc.stdin is not None
        self.proc.stdin.write(dumps_tagged({"function": function, "args": list(args)}) + "\n")
        self.proc.stdin.flush()
        try:
            line = self._lines.get(timeout=self.timeout_s)
        except queue.Empty as e:
            self.close()
            raise OracleError(f"oracle timeout after {self.timeout_s}s on {function}") from e
        if line is None:
            err = self.proc.stderr.read() if self.proc.stderr else ""
            raise OracleError(f"oracle exited on {function}: {err[-2000:]}")
        resp = json.loads(line)
        if resp.get("ok"):
            return True, loads_tagged(json.dumps(resp["result"]))
        return False, str(resp.get("error", "unknown oracle error"))

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except (BrokenPipeError, ValueError):
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, ValueError):
            try:
                self.proc.kill()
            except (ProcessLookupError, ValueError, OSError):
                pass


def load_py_function(path: str | Path, name: str) -> Callable[..., Any]:
    """Import converted module from path, return function name. Raises ValueError."""
    path = Path(path)
    mod_name = f"_conv_{path.stem}_{abs(hash(str(path.resolve())))}"
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        raise ValueError(f"converted module threw on import: {e}") from e
    fn: Any = getattr(mod, name, None)
    if not callable(fn):
        raise TypeError(f"converted module has no callable {name!r}")
    return cast("Callable[..., Any]", fn)


def safe_dumps(v: Any) -> str:
    try:
        return dumps_tagged(v)
    except (TypeError, ValueError):
        return json.dumps(f"<unencodable {type(v).__name__}: {str(v)[:200]}>")


# -- Hypothesis strategies -------------------------------------------------


def js_int() -> Any:
    return st.integers(-_SAFE_INT, _SAFE_INT)


def js_float() -> Any:
    return st.one_of(
        st.floats(allow_nan=True, allow_infinity=True, allow_subnormal=False, width=32),
        st.just(-0.0),
    )


def js_string() -> Any:
    return st.text(max_size=12)


def js_scalar() -> Any:
    return st.one_of(
        js_int(), js_float(), js_string(), st.booleans(), st.none(), st.just(UNDEFINED)
    )


def js_value() -> Any:
    return st.recursive(
        js_scalar(),
        lambda c: st.one_of(
            st.lists(c, max_size=3),
            st.dictionaries(st.text(max_size=6), c, max_size=3),
        ),
        max_leaves=5,
    )


def strategy_for_arity(n: int) -> Any:
    return st.lists(js_value(), min_size=n, max_size=n)


_JSDOC_PARAM_RE = re.compile(r"@param\s+\{([^}]*)\}\s*[\w$]*")


def _strategy_for_type(t: str) -> Any:
    t = t.strip()
    if t == "string":
        return js_string()
    if t in ("number", "Number"):
        return st.one_of(js_int(), js_float())
    if t in ("boolean", "Boolean"):
        return st.booleans()
    if t in ("bigint", "BigInt"):
        return st.integers(min_value=_SAFE_INT + 1, max_value=10**30)
    if t in ("Array", "array", "any[]"):
        return st.lists(js_scalar(), max_size=4)
    if t in ("object", "Object"):
        return st.dictionaries(st.text(max_size=6), js_scalar(), max_size=3)
    if t in ("null",):
        return st.none()
    return js_value()


def strategy_from_jsdoc(func_js_text: str, arity: int) -> Any:
    """Per-arg strategies from @param {Type} tags; generic fallback per arg."""
    types = _JSDOC_PARAM_RE.findall(func_js_text)
    strats = [_strategy_for_type(types[i]) if i < len(types) else js_value() for i in range(arity)]
    return st.tuples(*strats).map(list) if strats else st.just([])


def strategy_for_function(js_source: str, fn: str, seeds: list[list[Any]]) -> Any:
    """Fuzz strategy for one function: JSDoc types when arity matches, else generic.

    Seed-less multi-arg functions fall back to their JS arity; a wrong-arity
    probe throws on both sides, which the differ matches (no false signal).
    """
    from agent.nodes.analyze import function_arity

    arity = function_arity(js_source, fn)
    if arity is None:
        arity = len(seeds[0]) if seeds else 1
    types = _JSDOC_PARAM_RE.findall(js_source)
    if len(types) == arity and arity > 0:
        return strategy_from_jsdoc(js_source, arity)
    return strategy_for_arity(arity)


# -- differential loop ------------------------------------------------------


def run_differential(
    js_module: str | Path,
    py_module: str | Path,
    function: str,
    seed_arg_lists: list[list[Any]],
    *,
    strategy: Any = None,
    fuzz_examples: int = 20,
    rel_tol: float = 1e-9,
    undefined_null_distinct: bool = True,
    timeout_s: float = 10,
    node: str | None = None,
) -> list[Mismatch]:
    """Compare oracle vs converted fn on seeds + fuzz. Returns Mismatches."""
    try:
        py_fn = load_py_function(py_module, function)
    except (TypeError, ValueError) as e:
        return [
            Mismatch(
                function=function,
                input_json="[]",
                js_output="(oracle not consulted)",
                target_output=f"load-error: {e}",
            )
        ]

    def target_call(args: list[Any]) -> tuple[bool, Any]:
        try:
            return True, py_fn(*args)
        except Exception as e:  # noqa: BLE001 - any throw is a data point
            return False, f"{type(e).__name__}: {e}"

    return _diff_with_target(
        js_module,
        function,
        seed_arg_lists,
        target_call,
        strategy=strategy,
        fuzz_examples=fuzz_examples,
        rel_tol=rel_tol,
        undefined_null_distinct=undefined_null_distinct,
        timeout_s=timeout_s,
        node=node,
    )


def run_differential_js(
    js_module: str | Path,
    target_module: str | Path,
    function: str,
    seed_arg_lists: list[list[Any]],
    *,
    strategy: Any = None,
    fuzz_examples: int = 20,
    rel_tol: float = 1e-9,
    undefined_null_distinct: bool = True,
    timeout_s: float = 10,
    node: str | None = None,
) -> list[Mismatch]:
    """Oracle-vs-oracle diff (e.g. original JS vs tsc-compiled TS)."""
    target_oracle = OracleRunner(target_module, node=node, timeout_s=timeout_s)
    try:

        def target_call(args: list[Any]) -> tuple[bool, Any]:
            try:
                return target_oracle.call(function, args)
            except OracleError as e:
                return False, f"oracle-error: {e}"

        return _diff_with_target(
            js_module,
            function,
            seed_arg_lists,
            target_call,
            strategy=strategy,
            fuzz_examples=fuzz_examples,
            rel_tol=rel_tol,
            undefined_null_distinct=undefined_null_distinct,
            timeout_s=timeout_s,
            node=node,
        )
    finally:
        target_oracle.close()


def _diff_with_target(
    js_module: str | Path,
    function: str,
    seed_arg_lists: list[list[Any]],
    target_call: Callable[[list[Any]], tuple[bool, Any]],
    *,
    strategy: Any = None,
    fuzz_examples: int = 20,
    rel_tol: float = 1e-9,
    undefined_null_distinct: bool = True,
    timeout_s: float = 10,
    node: str | None = None,
) -> list[Mismatch]:
    """Shared seeds + Hypothesis loop over an oracle and a target callable.

    target_call returns (True, value) or (False, throw_message).
    """
    oracle = OracleRunner(js_module, node=node, timeout_s=timeout_s)
    mismatches: list[Mismatch] = []
    try:

        def check_one(args: list[Any]) -> Mismatch | None:
            try:
                js_ok, js_val = oracle.call(function, args)
            except OracleError as e:
                return Mismatch(
                    function=function,
                    input_json=safe_dumps(args),
                    js_output=f"oracle-error: {e}",
                    target_output="(unknown)",
                )
            t_ok, t_val = target_call(args)
            args_wire = safe_dumps(args)
            if not js_ok and not t_ok:
                return None  # both threw: match for v1
            if not js_ok:
                return Mismatch(
                    function=function,
                    input_json=args_wire,
                    js_output=f"threw: {js_val}",
                    target_output=safe_dumps(t_val),
                )
            if not t_ok:
                return Mismatch(
                    function=function,
                    input_json=args_wire,
                    js_output=safe_dumps(js_val),
                    target_output=f"threw: {t_val}",
                )
            ok, _reason = compare_values(
                js_val,
                t_val,
                rel_tol=rel_tol,
                undefined_null_distinct=undefined_null_distinct,
            )
            if ok:
                return None
            return Mismatch(
                function=function,
                input_json=args_wire,
                js_output=safe_dumps(js_val),
                target_output=safe_dumps(t_val),
            )

        for args in seed_arg_lists:
            m = check_one(list(args))
            if m is not None:
                mismatches.append(m)

        strat = strategy
        if strat is None and seed_arg_lists:
            strat = strategy_for_arity(len(seed_arg_lists[0]))
        if strat is not None and fuzz_examples > 0:

            @given(args=strat)
            @settings(
                max_examples=fuzz_examples,
                deadline=None,
                database=None,
                suppress_health_check=list(HealthCheck),
            )
            def _prop(args: list[Any]) -> None:
                m = check_one(list(args))
                if m is not None:
                    raise AssertionError(
                        "PAYLOAD " + json.dumps([m.input_json, m.js_output, m.target_output])
                    )

            try:
                _prop()
            except AssertionError as e:
                payload = _payload_of(str(e))
                if payload is not None:
                    input_json, js_output, target_output = payload
                    mismatches.append(
                        Mismatch(
                            function=function,
                            input_json=input_json,
                            js_output=js_output,
                            target_output=target_output,
                        )
                    )
                else:
                    mismatches.append(
                        Mismatch(
                            function=function,
                            input_json="[]",
                            js_output="(fuzz failure unparseable)",
                            target_output=str(e)[:2000],
                        )
                    )
    finally:
        oracle.close()
    return mismatches


_PAYLOAD_RE = re.compile(r"PAYLOAD (\[.*\])\s*$", re.DOTALL)


def _payload_of(message: str) -> tuple[str, str, str] | None:
    m = _PAYLOAD_RE.search(message)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
        if isinstance(data, list) and len(data) == 3 and all(isinstance(x, str) for x in data):
            return (data[0], data[1], data[2])
    except (json.JSONDecodeError, ValueError):
        return None
    return None
