"""LangGraph state schema. Mirrors the spec exactly."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from pydantic import BaseModel


class Diag(BaseModel):
    tool: str  # ruff | mypy | tsc | pytest | diff
    file: str
    line: int | None = None
    code: str | None = None
    message: str


class Mismatch(BaseModel):
    function: str
    input_json: str
    js_output: str
    target_output: str


class MigrationState(TypedDict):
    repo_path: str
    target: str  # "python" | "typescript"
    queue: list[str]  # JS files in dependency order
    current: str | None
    source: str
    converted: str
    static_errors: list[Diag]
    mismatches: list[Mismatch]
    error_fingerprints: list[str]  # hash of normalized errors per attempt
    attempts: int
    done: list[str]
    escalated: list[str]
    cheat_flags: list[str]
    tokens_used: Annotated[int, operator.add]
