"""Target adapters behind one interface: static_check, harness_gen, run_diff."""

from __future__ import annotations

import importlib
from typing import Any

_TARGETS = ("python", "typescript")


def get_adapter(target: str) -> Any:
    if target not in _TARGETS:
        raise ValueError(f"Unknown target {target!r}. Expected one of {_TARGETS}.")
    return importlib.import_module(f"targets.{target}")
