"""Milestone 6 tests: critic heuristics + anti-cheat hashing."""

from agent.anticheat import any_density, scan, snapshot, verify
from agent.nodes.critic import CriticVerdict, review_offline

CLEAN = "def f(x: int) -> int:\n    return x + 1\n"


def test_verdict_alias_pass():
    v = CriticVerdict.model_validate_json('{"pass": true, "flags": []}')
    assert v.passed is True


def test_offline_clean():
    ok, flags = review_offline(CLEAN, source_functions=["f"])
    assert ok and flags == []


def test_stub_bodies_flagged():
    for body in ("    pass\n", "    raise NotImplementedError('todo')\n", "    return None\n"):
        ok, flags = review_offline(f"def f(x: int) -> int:\n{body}", source_functions=["f"])
        assert not ok and any("stub" in f for f in flags), body


def test_type_escapes_flagged():
    ok, flags = review_offline("def f(x: Any) -> Any:\n    return x  # type: ignore\n")
    assert not ok
    assert "type-ignore" in flags
    assert any("any-density" in f for f in flags)
    assert any_density("x: Any = 1\n" * 10) > 0.05


def test_scan_threshold_respected():
    ok, _ = review_offline(CLEAN, any_threshold=1.0)
    assert ok


def test_snapshot_detects_oracle_tampering(tmp_path):
    oracle = tmp_path / "runner.js"
    oracle.write_text("v1", encoding="utf-8")
    snap = snapshot([oracle])
    assert verify(snap) == []
    oracle.write_text("v1 // evil", encoding="utf-8")
    assert verify(snap) == [str(oracle.resolve())]


def test_scan_ts_escapes():
    flags = scan("const x = y as any; // @ts-ignore\n")
    assert "ts-any-escape" in flags
