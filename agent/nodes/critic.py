"""Critic node: reject stubs, type escapes, and fidelity gaps.

Code-enforced heuristics run first; the LLM verdict (structured output)
adds a fidelity spot-check. No cheating: the fixer never sees the oracle.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from agent.anticheat import scan
from agent.config import AppConfig
from agent.llm_client import LlmClient


class CriticVerdict(BaseModel):
    model_config = {"populate_by_name": True}

    passed: bool = Field(alias="pass")
    flags: list[str] = []


def heuristic_flags(
    converted: str, *, source_functions: list[str] | None = None, any_threshold: float = 0.05
) -> list[str]:
    return scan(converted, source_functions=source_functions, any_threshold=any_threshold)


def render_critic_prompt(
    source: str, converted: str, template_path: str | Path | None = None
) -> str:
    path = (
        Path(template_path)
        if template_path
        else Path(__file__).resolve().parents[1] / "prompts" / "critic.md"
    )
    template = path.read_text(encoding="utf-8")
    return template.replace("{source}", source).replace("{converted}", converted)


def review(
    client: LlmClient,
    cfg: AppConfig,
    *,
    source: str,
    converted: str,
    source_functions: list[str] | None = None,
) -> tuple[bool, list[str], int]:
    """Return (passed, flags, tokens). Heuristics OR-ed with the LLM verdict."""
    threshold = float(cfg.raw.get("cheat", {}).get("any_density_threshold", 0.05))
    flags = heuristic_flags(converted, source_functions=source_functions, any_threshold=threshold)
    prompt = render_critic_prompt(source, converted)
    try:
        verdict, tokens = client.chat_structured(
            [{"role": "user", "content": prompt}], schema=CriticVerdict, role="critic"
        )
    except (ValueError, RuntimeError) as e:
        return False, flags + [f"critic-error: {e}"], 0
    all_flags = flags + [f for f in verdict.flags if f not in flags]
    return bool(verdict.passed) and not flags, all_flags, tokens


def review_offline(
    converted: str, *, source_functions: list[str] | None = None, any_threshold: float = 0.3
) -> tuple[bool, list[str]]:
    """Heuristic-only verdict (no LLM). Used by tests and the eval harness."""
    flags = heuristic_flags(
        converted, source_functions=source_functions, any_threshold=any_threshold
    )
    return (not flags, flags)
