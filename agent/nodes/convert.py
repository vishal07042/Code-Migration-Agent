"""Convert node (Milestone 3): render prompt, call LLM, return code + tokens."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import AppConfig
from ..llm_client import LlmClient

TEMPLATE_NAME = "convert.md"


def template_path(repo_root: str | Path) -> Path:
    return Path(repo_root) / "agent" / "prompts" / TEMPLATE_NAME


def trap_list_str(cfg: AppConfig) -> str:
    traps: list[str] = list(cfg.raw.get("traps", []))
    return "\n".join(f"{i + 1}. {t}" for i, t in enumerate(traps))


def render_convert_prompt(
    cfg: AppConfig, *, source: str, dep_signatures: str = "", template: str | None = None
) -> str:
    """Fill the convert template. Plain replaces (code may contain braces)."""
    if template is None:
        template = template_path(cfg.repo_root).read_text(encoding="utf-8")
    out = template.replace("{trap_list}", trap_list_str(cfg))
    out = out.replace("{source}", source)
    out = out.replace("{dep_signatures}", dep_signatures or "(none)")
    return out


def strip_code_fences(text: str) -> str:
    t = text.strip()
    if not t.startswith("```"):
        return t + "\n" if t else ""
    lines = t.splitlines()
    # Drop opening fence (``` or ```python) and closing fence.
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    while lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip() + "\n"


def convert_source(
    client: LlmClient,
    cfg: AppConfig,
    source: str,
    *,
    dep_signatures: str = "",
    role: str = "converter",
) -> tuple[str, int]:
    """Run the converter. Returns (code, tokens_used)."""
    prompt = render_convert_prompt(cfg, source=source, dep_signatures=dep_signatures)
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    text, tokens = client.chat(messages, role=role)
    return strip_code_fences(text), tokens
