# Code Migration Agent (LangGraph)

JS → Python (verified by differential testing) with a fix loop, critic,
multi-file support, eval harness, and an optional TS adapter + replay UI.
Full spec: `code-migration-agent-prompt.md`.

## Setup

```bash
uv sync --group dev
uv run pytest -q
```

## Model config

Provider profiles live in `config.yaml` under `providers:` (`zen`,
`openrouter`); `llm.provider` selects. Keys come from env — copy
`.env.example` to `.env` (gitignored, auto-loaded via python-dotenv) and
fill it in. Never commit real keys. Role models are
Pydantic-free plain names so rotation is a config edit; refresh via the
provider's `GET /models`.

- **OpenRouter (active):** `poolside/laguna-s-2.1` for all roles; verified
  live (549 tokens for the sample; relax `llm.max_tokens` only if outputs
  truncate). Free models rotate and rate-limit (429) — tenacity backs off.
- **Zen:** free-tier *chat* only works from inside the OpenCode runtime
  (`403 FreeTierError` standalone). Switch `provider: zen` + Zen role names
  when running there.

## Pipeline

```
Analyze (deps first) -> Convert -> Static (ruff/mypy or tsc)
  -> Harness gen -> Run diff (oracle runner.js + Hypothesis fuzz)
  -> Gate: green? critic : fix (patch; revert on regression)
  -> Critic (stub/Any/ignore heuristics + LLM verdict)
  -> Commit per file (GitPython) / escalate via interrupt() on cap
```

```bash
# single-file building blocks
uv run python eval/run.py --fuzz 30 --out eval/results.json
uv run python eval/report.py eval/results.json   # table + eval/report.html + web replay JSON
```

## Status

Live-verified via OpenRouter (`poolside/laguna-s-2.1`): convert → static
clean → 0 mismatches on the sample; full loop transitions proven
(Convert→Static→Harness→Run→Fix→Critic→Escalate with sidecar records).
The small model stalls on fidelity (over-wide `object` types the critic
correctly rejects) — a green live commit wants a stronger model or more
attempt budget. Free-tier quota: 50 req/day shared across `:free` models.

## Layout

- `agent/` state, config, LLM client (SQLite cache, retries), git helper,
  nodes (analyze/convert/fix/critic), edges (gate), build (graph)
- `oracle/` runner.js + tagged JSON (py mirror): undefined/NaN/±Inf/-0/BigInt/Date
- `targets/` python + typescript adapters (`static_check`, `harness_gen`,
  `run_diff`; TS diff compiles with tsc then runs oracle-vs-oracle)
- `harness/` normalized comparison, Jest seed extraction, differential runner
- `sandbox/` Dockerfile + runner (Docker when the daemon runs, else local;
  read-only hash checks in both; `docker build -t migrate-sandbox:latest sandbox/`)
- `eval/corpus/` 5 pure-function modules + tests + verified references
- `web/` optional replay UI (reads `web/public/run-report.json`)

## Conventions that matter

- `undefined` ≠ `None`: the `UNDEFINED` sentinel preserves the distinction.
- `-0` ≠ `+0`, `NaN` == `NaN` for diff purposes; JS `Set` canonicalizes -0→+0.
- Strings match **wire-observable** behavior: JSON recombines surrogate
  pairs, so char-level ports are correct except where JS yields a lone
  surrogate (e.g. `slice(0, 1)` of emoji — trap T5).
- Fuzz strategies follow JSDoc `@param` types; untyped functions get generic
  values (which only probes dynamic typing, not the conversion).
