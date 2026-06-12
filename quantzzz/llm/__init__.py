"""Optional LLM advisor layer. Degrades to NullAdvisor when no key is present."""

from __future__ import annotations

from ..config import Config
from .advisor import LLMAdvisor, NullAdvisor


def get_llm(cfg: Config) -> LLMAdvisor:
    if not cfg.llm_enabled:
        return NullAdvisor()
    try:
        from .anthropic_advisor import AnthropicAdvisor
        return AnthropicAdvisor(cfg)
    except Exception as e:
        # a key is set, so a silent no-op would mask a real misconfiguration
        print(f"LLM advisor unavailable ({type(e).__name__}: {e}); "
              f"continuing algorithmically")
        return NullAdvisor()
