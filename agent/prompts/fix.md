The converted code has these failures: {diags_or_mismatches}. Fix ONLY the failing function(s). Do not touch tests or the oracle. Do not use `Any`, `# type: ignore`, or hardcode expected outputs.

Reply with ONLY one or more patch blocks in exactly this format (no prose,
no fences):

<<<<<<< SEARCH
<exact lines copied from the current file>
=======
<replacement lines>
>>>>>>>

Failing cases (minimal inputs, JS output vs target output):
```
{cases}
```

Current converted code:
```python
{converted}
```
