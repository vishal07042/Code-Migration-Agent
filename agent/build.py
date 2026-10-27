"""Graph assembly.

Analyze -> Convert -> Static -> Harness -> Run -> Gate -> Fix/Critic/Commit/Escalate.
SQLite checkpointer + interrupt() on escalation, per the spec.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent.config import AppConfig
from agent.edges import decide
from agent.git_helper import commit_file, ensure_repo
from agent.llm_client import LlmClient
from agent.nodes.analyze import (
    dependency_order,
    exported_functions,
    extract_py_signatures,
    run_analyzer,
)
from agent.nodes.convert import convert_source
from agent.nodes.critic import (
    CriticVerdict,
    heuristic_flags,
    render_critic_prompt,
)
from agent.nodes.fix import (
    apply_patch,
    failure_count,
    fingerprint,
    render_fix_prompt_from_state,
)
from agent.state import MigrationState
from targets import get_adapter


class Ctx:
    """Per-run handles shared by all nodes."""

    def __init__(self, cfg: AppConfig, client: LlmClient, workdir: str | Path, target: str):
        self.cfg = cfg
        self.client = client
        self.workdir = Path(workdir)
        self.target = target
        self.adapter = get_adapter(target)
        self.repo = ensure_repo(self.workdir)
        (self.workdir / "converted").mkdir(parents=True, exist_ok=True)
        (self.workdir / ".migrate").mkdir(parents=True, exist_ok=True)

    def converted_path(self, rel: str) -> Path:
        return self.workdir / "converted" / Path(rel).with_suffix(".py")

    def sidecar(self, rel: str) -> Path:
        safe = rel.replace("/", "__").replace("\\", "__")
        return self.workdir / ".migrate" / f"{safe}.json"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _find_test_source(repo_path: str, rel: str) -> str:
    stem = Path(rel).stem
    cand = Path(repo_path) / Path(rel).parent / f"{stem}.test.js"
    return _read(cand) if cand.is_file() else ""


def build_graph(
    cfg: AppConfig,
    client: LlmClient,
    *,
    workdir: str | Path,
    target: str = "python",
    db_path: str | Path | None = None,
) -> tuple[Any, SqliteSaver]:
    """Compile the migration graph. Returns (graph, checkpointer). Caller owns both."""
    ctx = Ctx(cfg, client, workdir, target)
    max_attempts = cfg.max_attempts
    builder = StateGraph(MigrationState)

    def n_analyze(state: MigrationState) -> dict[str, Any]:
        if state.get("current"):
            return {}
        queue = list(state.get("queue") or [])
        if not queue:
            files = run_analyzer(state["repo_path"])
            queue = dependency_order(files)
        if not queue:
            return {"current": None}
        nxt = queue.pop(0)
        src = _read(Path(state["repo_path"]) / nxt)
        return {
            "queue": queue,
            "current": nxt,
            "source": src,
            "converted": "",
            "static_errors": [],
            "mismatches": [],
            "error_fingerprints": [],
            "attempts": 0,
            "cheat_flags": [],
        }

    def _dep_signatures(state: MigrationState) -> str:
        parts = []
        for rel in state.get("done") or []:
            p = ctx.converted_path(rel)
            if p.is_file():
                parts.append(f"# from {rel}\n" + extract_py_signatures(_read(p)))
        return "\n".join(parts)

    def n_convert(state: MigrationState) -> dict[str, Any]:
        if state.get("attempts", 0) != 0 or state.get("converted"):
            return {}
        code, tok = convert_source(
            ctx.client, cfg, state["source"], dep_signatures=_dep_signatures(state)
        )
        _write(ctx.converted_path(state["current"] or "out.js"), code)
        return {"converted": code, "tokens_used": tok, "attempts": state["attempts"] + 1}

    def n_static(state: MigrationState) -> dict[str, Any]:
        p = ctx.converted_path(state["current"] or "out.js")
        diags = ctx.adapter.static_check(state["converted"], filename=p.name, workdir=p.parent)
        return {"static_errors": diags}

    def n_harness(state: MigrationState) -> dict[str, Any]:
        import json as _json

        from harness.seeds import extract_seeds
        from oracle.tagged_json import dumps_tagged

        rel = state["current"] or ""
        test_src = _find_test_source(state["repo_path"], rel)
        fns = exported_functions(state["source"])
        seeds = {fn: extract_seeds(test_src, fn) for fn in fns}
        tagged = {fn: [dumps_tagged(a) for a in arg_lists] for fn, arg_lists in seeds.items()}
        ctx.sidecar(rel).write_text(_json.dumps(tagged), encoding="utf-8")
        ctx.adapter.harness_gen(
            js_module=str(Path(state["repo_path"]) / rel),
            py_module=str(ctx.converted_path(rel)),
            seeds=seeds,
            out_path=str(ctx.workdir / ".migrate" / f"test_diff_{Path(rel).stem}.py"),
            fuzz_examples=int(cfg.raw.get("harness", {}).get("fuzz_examples", 50)),
            rel_tol=float(cfg.raw.get("comparison", {}).get("float_rel_tolerance", 1e-9)),
            undefined_null_distinct=bool(
                cfg.raw.get("comparison", {}).get("undefined_null_distinct", True)
            ),
            timeout_s=float(cfg.raw.get("harness", {}).get("timeout_s", 10)),
        )
        return {}

    def _seeds_of(state: MigrationState) -> dict[str, list[list[Any]]]:
        import json as _json

        from oracle.tagged_json import loads_tagged

        sc = ctx.sidecar(state["current"] or "")
        if sc.is_file():
            tagged: dict[str, list[str]] = _json.loads(sc.read_text(encoding="utf-8"))
            data: dict[str, list[list[Any]]] = {
                fn: [loads_tagged(w) for w in wires] for fn, wires in tagged.items()
            }
            return data
        return {}

    def n_run(state: MigrationState) -> dict[str, Any]:
        from harness.fuzz import strategy_for_function

        rel = state["current"] or ""
        static_errors = list(state.get("static_errors") or [])
        mismatches: list[Any] = []
        if not static_errors:
            seeds = _seeds_of(state)
            strategies = {
                fn: strategy_for_function(state.get("source") or "", fn, seeds.get(fn, []))
                for fn in seeds
            }
            mismatches = ctx.adapter.run_diff(
                js_module=str(Path(state["repo_path"]) / rel),
                py_module=str(ctx.converted_path(rel)),
                seeds=seeds,
                strategies=strategies,
                fuzz_examples=int(cfg.raw.get("harness", {}).get("fuzz_examples", 50)),
                rel_tol=float(cfg.raw.get("comparison", {}).get("float_rel_tolerance", 1e-9)),
                undefined_null_distinct=bool(
                    cfg.raw.get("comparison", {}).get("undefined_null_distinct", True)
                ),
                timeout_s=float(cfg.raw.get("harness", {}).get("timeout_s", 10)),
            )
        fp = fingerprint(static_errors, mismatches)
        return {
            "mismatches": mismatches,
            "error_fingerprints": [*state.get("error_fingerprints", []), fp],
        }

    def _do_fix(state: MigrationState, *, wide: bool) -> dict[str, Any]:
        from agent.nodes.convert import strip_code_fences
        from agent.nodes.fix import PatchError

        prompt = render_fix_prompt_from_state(dict(state), wide=wide)
        text, tok = ctx.client.chat([{"role": "user", "content": prompt}], role="fixer")
        before = failure_count(
            list(state.get("static_errors") or []), list(state.get("mismatches") or [])
        )
        old_code: str = state.get("converted") or ""
        try:
            patched = apply_patch(old_code, strip_code_fences(text))
        except PatchError:
            # One retry with an explicit format nudge (small models often
            # return prose or a full rewrite on the first try).
            retry, tok2 = ctx.client.chat(
                [
                    {"role": "user", "content": prompt},
                    {
                        "role": "user",
                        "content": "No valid patch block found. Reply with ONLY "
                        "<<<<<<< SEARCH / ======= / >>>>>>> blocks.",
                    },
                ],
                role="fixer",
            )
            tok += tok2
            try:
                patched = apply_patch(old_code, strip_code_fences(retry))
            except PatchError:
                # Record the REAL fingerprint so repeat detection still works.
                fps = [
                    *state.get("error_fingerprints", []),
                    fingerprint(
                        list(state.get("static_errors") or []),
                        list(state.get("mismatches") or []),
                    ),
                ]
                return {
                    "attempts": state.get("attempts", 0) + 1,
                    "tokens_used": tok,
                    "error_fingerprints": fps,
                }
        p = ctx.converted_path(state["current"] or "out.js")
        _write(p, patched)
        recheck = ctx.adapter.static_check(patched, filename=p.name, workdir=p.parent)
        if len(recheck) > before:
            _write(p, old_code)  # revert on regression; try a different strategy next
            return {
                "attempts": state.get("attempts", 0) + 1,
                "tokens_used": tok,
                # Same fingerprint as the current failures: repeat detection
                # routes the next round through the widened strategy.
                "error_fingerprints": [
                    *state.get("error_fingerprints", []),
                    fingerprint(
                        list(state.get("static_errors") or []),
                        list(state.get("mismatches") or []),
                    ),
                ],
            }
        return {
            "converted": patched,
            "static_errors": recheck,
            "mismatches": [],
            "attempts": state.get("attempts", 0) + 1,
            "tokens_used": tok,
        }

    def n_fix(state: MigrationState) -> dict[str, Any]:
        return _do_fix(state, wide=False)

    def n_fix_wide(state: MigrationState) -> dict[str, Any]:
        return _do_fix(state, wide=True)

    def n_critic(state: MigrationState) -> dict[str, Any]:
        threshold = float(cfg.raw.get("cheat", {}).get("any_density_threshold", 0.05))
        fns = exported_functions(state.get("source") or "")
        flags = heuristic_flags(
            state.get("converted") or "", source_functions=fns, any_threshold=threshold
        )
        if flags:
            return {"cheat_flags": flags}
        prompt = render_critic_prompt(state.get("source") or "", state.get("converted") or "")
        try:
            verdict, tok = ctx.client.chat_structured(
                [{"role": "user", "content": prompt}], schema=CriticVerdict, role="critic"
            )
        except (ValueError, RuntimeError) as e:
            return {"cheat_flags": [f"critic-error: {e}"]}
        if verdict.passed and not verdict.flags:
            return {"cheat_flags": [], "tokens_used": tok}
        return {"cheat_flags": list(verdict.flags) or ["critic-rejected"], "tokens_used": tok}

    def _advance(state: MigrationState) -> dict[str, Any]:
        queue = list(state.get("queue") or [])
        nxt = queue.pop(0) if queue else None
        update: dict[str, Any] = {"queue": queue, "current": nxt}
        if nxt is not None:
            update["source"] = _read(Path(state["repo_path"]) / nxt)
        else:
            update["source"] = ""
        update.update(
            {
                "converted": "",
                "static_errors": [],
                "mismatches": [],
                "error_fingerprints": [],
                "attempts": 0,
                "cheat_flags": [],
            }
        )
        return update

    def n_commit(state: MigrationState) -> dict[str, Any]:
        rel = state["current"] or ""
        p = ctx.converted_path(rel)
        sha = commit_file(
            ctx.repo,
            ctx.workdir,
            str(p.relative_to(ctx.workdir)),
            f"migrate {rel} (iters {state.get('attempts', 0)}, +{state.get('tokens_used', 0)} tok)",
        )
        _ = sha
        update = _advance(state)
        update["done"] = [*state.get("done", []), rel]
        return update

    def n_escalate(state: MigrationState) -> dict[str, Any]:
        import json as _json

        # Record FIRST so the escalation survives even if nobody resumes.
        rel = state.get("current") or ""
        esc = {
            "file": rel,
            "attempts": state.get("attempts", 0),
            "static_errors": [d.model_dump() for d in (state.get("static_errors") or [])],
            "mismatches": [m.model_dump() for m in (state.get("mismatches") or [])],
        }
        (ctx.workdir / ".migrate" / f"{rel.replace('/', '__')}.escalation.json").write_text(
            _json.dumps(esc, indent=2), encoding="utf-8"
        )
        update = _advance(state)
        update["escalated"] = [*state.get("escalated", []), rel]
        return update

    def n_await_human(state: MigrationState) -> dict[str, Any]:
        _ = interrupt(
            {
                "files": state.get("escalated", []),
                "hint": "Last attempted file needs a human. Resume with any value to continue.",
            }
        )
        return {}

    def route_gate(state: MigrationState) -> str:
        return decide(
            static_errors=list(state.get("static_errors") or []),
            mismatches=list(state.get("mismatches") or []),
            attempts=int(state.get("attempts", 0)),
            fingerprints=list(state.get("error_fingerprints") or []),
            max_attempts=max_attempts,
        )

    def route_critic(state: MigrationState) -> str:
        if not state.get("cheat_flags"):
            return "commit"
        if int(state.get("attempts", 0)) < max_attempts:
            return "fix"
        return "escalate"

    def route_advance(state: MigrationState) -> str:
        if state.get("current") or state.get("queue"):
            return "analyze"
        return "end"

    builder.add_node("analyze", n_analyze)
    builder.add_node("convert", n_convert)
    builder.add_node("static", n_static)
    builder.add_node("harness", n_harness)
    builder.add_node("run", n_run)
    builder.add_node("fix", n_fix)
    builder.add_node("fix_wide", n_fix_wide)
    builder.add_node("critic", n_critic)
    builder.add_node("commit", n_commit)
    builder.add_node("escalate", n_escalate)
    builder.add_node("await_human", n_await_human)

    builder.add_edge(START, "analyze")
    builder.add_edge("analyze", "convert")
    builder.add_edge("convert", "static")
    builder.add_edge("static", "harness")
    builder.add_edge("harness", "run")
    builder.add_conditional_edges(
        "run",
        route_gate,
        {"critic": "critic", "fix": "fix", "fix_wide": "fix_wide", "escalate": "escalate"},
    )
    builder.add_edge("fix", "static")
    builder.add_edge("fix_wide", "static")
    builder.add_conditional_edges(
        "critic", route_critic, {"commit": "commit", "fix": "fix", "escalate": "escalate"}
    )
    builder.add_conditional_edges("commit", route_advance, {"analyze": "analyze", "end": END})
    builder.add_edge("escalate", "await_human")
    builder.add_conditional_edges("await_human", route_advance, {"analyze": "analyze", "end": END})

    db = Path(db_path) if db_path else ctx.workdir / ".migrate" / "checkpoints.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    graph = builder.compile(checkpointer=saver)
    return graph, saver


def initial_state(repo_path: str, target: str = "python") -> MigrationState:
    return MigrationState(
        repo_path=repo_path,
        target=target,
        queue=[],
        current=None,
        source="",
        converted="",
        static_errors=[],
        mismatches=[],
        error_fingerprints=[],
        attempts=0,
        done=[],
        escalated=[],
        cheat_flags=[],
        tokens_used=0,
    )


async def stream_run(graph: Any, state: MigrationState, thread_id: str) -> MigrationState:
    """Invoke the graph to completion (raises NodeInterrupt on escalation)."""
    result: MigrationState = await graph.ainvoke(
        state, config={"configurable": {"thread_id": thread_id}}
    )
    return result
