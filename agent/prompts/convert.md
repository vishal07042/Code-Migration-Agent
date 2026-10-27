Convert this JavaScript to idiomatic, fully type-hinted Python 3.11. Preserve behavior exactly, including edge cases. Watch for these traps: {trap_list}. Do not add features. Do not stub anything. Output only the code.

JavaScript source:
```javascript
{source}
```

Already-converted dependency signatures (target language):
```
{dep_signatures}
```

Rules:
- Pure functions only; no I/O, DOM, network.
- Use precise type hints (str, int, float, bool, list, dict); never use
  `object` or `Any` as a parameter or return type. Mirror the source's
  apparent contract.
- Distinguish `undefined` from `null` (map to a sentinel vs `None` per project convention).
- Keep float semantics: `/` is true division, watch `NaN`, `-0`, `Infinity`.
- Default sort is lexicographic; preserve comparator behavior.
- Strings: match wire-observable behavior (JSON recombines surrogate pairs;
  a lone-surrogate result such as slice(0, 1) of emoji stays lone).
