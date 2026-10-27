"""Provider wiring tests: OpenRouter profile resolution + headers (no network)."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_openrouter_profile_resolved():
    from agent.config import load_config

    cfg = load_config(REPO / "config.yaml")
    assert cfg.llm.provider == "openrouter"
    assert cfg.llm.base_url == "https://openrouter.ai/api/v1"
    assert cfg.llm.api_key_env == "OPENROUTER_API_KEY"
    assert cfg.llm.models_endpoint.endswith("/models")
    assert cfg.llm.referer and cfg.llm.title
    assert cfg.model_for("converter") == "poolside/laguna-s-2.1"


def test_openrouter_headers_sent(monkeypatch, tmp_path):
    """Fake openai.OpenAI at the import site used by _transport."""
    import openai

    from agent.config import load_config
    from agent.llm_client import LlmCache, LlmClient

    seen: dict = {}

    class FakeCompletions:
        def create(self, **kwargs):
            seen["kwargs"] = kwargs

            class Msg:
                content = "hi"

            class Choice:
                message = Msg()

            class Usage:
                prompt_tokens = 1
                completion_tokens = 1

            from typing import ClassVar

            class Resp:
                choices: ClassVar[list] = [Choice()]
                usage = Usage()

            return Resp()

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            seen["client"] = kwargs
            self.chat = FakeChat()

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    cfg = load_config(REPO / "config.yaml")
    client = LlmClient(cfg, cache=LlmCache(tmp_path / "c.sqlite"))
    text, tokens = client.chat([{"role": "user", "content": "hi"}], role="converter")
    assert text == "hi" and tokens == 2
    assert seen["client"]["base_url"] == "https://openrouter.ai/api/v1"
    assert seen["client"]["default_headers"]["HTTP-Referer"].startswith("https://")
    assert seen["client"]["default_headers"]["X-Title"] == "code-migration-agent"
    assert seen["kwargs"]["model"] == "poolside/laguna-s-2.1"


def test_env_files_sane():
    example = (REPO / ".env.example").read_text(encoding="utf-8")
    assert "OPENROUTER_API_KEY=" in example
    assert "sk-or-" not in example  # no real secret in the example
    ignored = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored
