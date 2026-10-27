# Build Prompt: Code Migration Agent (LangGraph)

## Role
You are a senior engineer building a portfolio-grade code migration agent. Work in small, tested steps. Do not over-engineer. After each milestone, run the tests and show me the result before moving on.

## Goal
Convert a JavaScript module to another language, verify it automatically, and loop on failures until it is green or a retry cap is hit.

**Default target: Python**, verified by *differential testing* (the original JS is the oracle).
**Optional second target: TypeScript**, verified by `tsc --strict` plus the original tests. Implement targets as adapters behind one interface.

**Success criteria**
- Converted code passes static checks (Python: `ruff` + `mypy`; TS: `tsc --noEmit --strict`).
- Behavior matches the JS original on test-derived and fuzzed inputs.
- No cheating: no stubbed logic, no hardcoded outputs, no weakened checks.
- Every run reports iterations, tokens, cost (shadow-priced), and which semantic traps caused failures.

**Non-goals (v1)**
- Pure functions only. No I/O, DOM, network, classes with inheritance, or async. Add those later as stretch goals.
- No whole-repo migration. One module at a time, dependency order only.

## Tech stack (use exactly this)
- Python 3.11+, `uv`
- `langgraph` (conditional edges, `interrupt`, SQLite checkpointer), `langchain-openai`, `pydantic` v2
- Node 20+ for the oracle runner
- Python target tools: `ruff`, `mypy`, `pytest`, `hypothesis`
- `GitPython` for per-file commits (free rollback)
- Docker sandbox for running generated code (no network, CPU/memory/time limits)
- `tenacity`, SQLite response cache
- Optional UI: React + Vite + Tailwind + Framer Motion (iteration replay)

## LLM configuration
- Provider: OpenCode Zen free models, OpenAI-compatible.
  - `base_url`: `https://opencode.ai/zen/v1`, key from env `ZEN_API_KEY`, model list at `GET /models`
- Free models rotate. Never hardcode names. Put them in `config.yaml` under roles: `converter`, `fixer`, `critic`.
- Structured outputs validated with Pydantic, retry up to 3 times with the error appended.
- Cache every LLM response (key: model + prompt hash). Backoff on 429/5xx. Concurrency cap from config.
- Only send public or open-source code through free models.

## Architecture
```
Analyze -> pick next file (leaves first)
  -> Convert
  -> Static check (ruff/mypy or tsc)
  -> Harness gen (differential test)
  -> Run diff tests (sandboxed)
  -> all green? -> Critic -> Commit -> next file
  -> red? -> Gate:
        retries left -> Diagnose+Fix (patch) -> back to Static check
        same error twice -> widen context, change strategy
        cap hit -> human escalation node
```

## State schema
```python
from typing import Annotated, TypedDict
import operator
from pydantic import BaseModel

class Diag(BaseModel):
    tool: str            # ruff | mypy | tsc | pytest | diff
    file: str
    line: int | None
    code: str | None
    message: str

class Mismatch(BaseModel):
    function: str
    input_json: str
    js_output: str
    target_output: str

class MigrationState(TypedDict):
    repo_path: str
    target: str                      # "python" | "typescript"
    queue: list[str]                 # JS files in dependency order
    current: str | None
    source: str
    converted: str
    static_errors: list[Diag]
    mismatches: list[Mismatch]
    error_fingerprints: list[str]    # hash of normalized errors per attempt
    attempts: int
    done: list[str]
    escalated: list[str]
    cheat_flags: list[str]
    tokens_used: Annotated[int, operator.add]
```

## Nodes
**analyze**: parse imports/exports (use `@babel/parser` or `esprima` via a small Node script). Output the dependency order and an npm to PyPI mapping, flagging packages with no equivalent. Leaves first.

**convert**: rewrite the current file. Include the trap list below in the prompt. For files with already-converted dependencies, include their target signatures.

**static_check**: run `ruff` and `mypy` (or `tsc`). Parse output into `Diag`s. Do not rely on the LLM to read raw tool output.

**harness_gen**: build the differential test.
- `oracle/runner.js` loads the original JS module, reads `{function, args}` JSON from stdin, prints JSON result. Use **tagged JSON** to encode what JSON can't: `{"$undefined":1}`, `{"$nan":1}`, `{"$inf":1}`, `{"$neginf":1}`, `{"$bigint":"..."}`, `{"$date":"..."}`.
- Inputs come from (a) values extracted from the original Jest tests, (b) Hypothesis strategies derived from the function signatures and JSDoc.
- Comparison: normalized deep equality, float tolerance (default `1e-9` relative), `undefined`/`null` distinguished unless config says otherwise.
- The oracle and harness are **read-only to the fixer**.

**run_diff**: execute in the sandbox. Output `Mismatch`es. Shrink failing inputs (Hypothesis does this) so the fixer sees minimal cases.

**diagnose_fix**: input is the converted code plus errors/mismatches only for the failing function. Output is a patch (search/replace blocks or unified diff), never a full rewrite after attempt 1. Apply the patch, and if the number of failures goes UP, `git revert` and try a different strategy.

**gate (edge)**:
- all green: go to critic
- `attempts < max_attempts` (default 5): go to fix
- same error fingerprint twice in a row: add dependency context or switch prompt strategy ("rewrite this function from scratch, here are the failing cases")
- cap hit: `interrupt()` for a human

**critic**: reject if any of these:
- `Any` / `# type: ignore` / `@ts-ignore` / `as any` density above threshold
- function body is a stub, `pass`, `raise NotImplementedError`, or returns constants matching test expectations
- tests or oracle modified
- behavior differs in ways the fuzz inputs did not cover (spot-check by reading the code)

**commit**: one git commit per migrated file with the report line (iterations, tokens).

## Semantic trap list (put in the convert prompt, track failures per trap)
1. `==` vs `===`, JS truthiness (`[]`, `"0"`, `{}` are truthy in JS)
2. `undefined` vs `null` vs `None`
3. Numbers: all floats, 32-bit bitwise ops, `/` never integer division, `NaN`, `-0`, `Infinity`, `Number.MAX_SAFE_INTEGER`
4. Default `.sort()` is lexicographic and stable; comparator semantics differ
5. Strings are UTF-16: `.length`, indexing, and slicing differ for emoji
6. `Array` holes, `.map` with index, `parseInt` radix quirks
7. Object key order and mutation/aliasing semantics
8. `this`, prototypes, closures captured in loops
9. Regex flavor differences
10. Date and timezone handling

## Anti-cheat rules (enforced in code, not just prompts)
- Test files and oracle are mounted read-only in the sandbox.
- Hash the oracle and test files at start and end of every run, and fail if changed.
- Fail the file if cheat-flag density exceeds the threshold from `config.yaml`.

## Budgets
`max_attempts: 5`, `max_tokens_per_file`, sandbox timeout per run (default 10s), memory limit. On cap hit, escalate with a summary of the last errors.

## Eval harness
- Corpus: 10-20 small open-source JS libs with test suites (pure functions: string utils, math helpers, date/array utilities).
- Metrics per module: static clean (yes/no), differential agreement % over N fuzz inputs, iterations to green, `Any` density, tokens, escalations.
- Ablations: (a) no loop vs loop, (b) patch vs full rewrite, (c) with vs without trap list, (d) small vs large model from the Zen list.
- Report: pandas table, Plotly chart of failures by trap category. This chart is the headline result.

## Repo layout
```
config.yaml
agent/    state.py nodes/ edges.py build.py prompts/*.md
oracle/   runner.js tagged_json.js
targets/  python.py typescript.py     # adapters: static_check, harness_gen, run
sandbox/  Dockerfile run.py
eval/     corpus/ run.py report.py
web/      (optional replay UI)
tests/
```

## Milestones (stop and report after each)
1. **Scaffold:** config, LLM client with cache and structured-output retries, git helper.
2. **Oracle:** `runner.js` with tagged JSON, plus Python decoder. Test round-trip of `undefined`, `NaN`, `-0`, big ints.
3. **Single function, no loop:** convert one pure function, run `ruff`/`mypy`.
4. **Differential harness:** extract inputs from Jest tests, add Hypothesis fuzz, compare.
5. **Fix loop:** patch application, revert on regression, repeated-error detection, attempt cap.
6. **Critic + anti-cheat:** stub detection, file hashing, read-only mounts.
7. **Multi-file:** dependency order, signature passing.
8. **Eval + trap-category chart.**
9. **(Optional) TypeScript adapter, replay UI.**

## Rules for you (the coding agent)
- Tests first for the oracle encoding, comparison logic, patch apply/revert, and anti-cheat. Bugs here silently invalidate the eval.
- No new dependencies beyond the stack above without asking.
- Keep prompts in `agent/prompts/*.md`.
- If ambiguous, pick the simplest option, state the assumption, continue.

## Appendix: node prompt skeletons

**Convert**
> Convert this JavaScript to idiomatic, fully type-hinted Python 3.11. Preserve behavior exactly, including edge cases. Watch for these traps: {trap list}. Do not add features. Do not stub anything. Output only the code.

**Fix**
> The converted code has these failures: {diags / mismatches with minimal inputs, JS output vs target output}. Fix ONLY the failing function(s). Return a patch in search/replace format. Do not touch tests or the oracle. Do not use `Any`, `# type: ignore`, or hardcode expected outputs.

**Critic**
> Review this conversion for cheating and fidelity. Flag stubs, constant returns, type-escape hatches, or behavior that differs from the JS source in ways the tests might miss. Return JSON: `{ "pass": bool, "flags": [..] }`.
