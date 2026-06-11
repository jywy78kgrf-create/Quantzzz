"""Anthropic-backed advisor: strategy proposals + journal reviews.

Imports `anthropic` lazily so the package is optional. All outputs are validated
and clamped to the parameterized strategy space; malformed proposals are dropped.
"""

from __future__ import annotations

import json

from ..config import Config
from ..research.strategy_space import StrategySpec

DEFAULT_MODEL = "claude-sonnet-4-6"


class AnthropicAdvisor:
    available = True

    def __init__(self, cfg: Config, model: str = DEFAULT_MODEL):
        import anthropic  # lazy: optional dependency
        self.client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        self.model = model

    def _complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        msg = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")

    def propose_strategies(self, desk, leaderboard, param_spaces) -> list[StrategySpec]:
        if not param_spaces:
            return []
        system = (
            "You are a quant strategist proposing new parameter sets within a fixed "
            "strategy space. Respond ONLY with a JSON array of objects "
            '{"family": str, "params": {...}}. Stay within documented parameter bounds.'
        )
        user = json.dumps({
            "desk": desk,
            "top_strategies": leaderboard,
            "parameter_spaces": param_spaces,
            "instruction": "Propose 3 diverse, promising parameter sets.",
        })
        try:
            text = self._complete(system, user)
            payload = json.loads(_extract_json(text))
        except Exception:
            return []
        out = []
        for item in payload if isinstance(payload, list) else []:
            family, params = item.get("family"), item.get("params")
            if family in param_spaces and isinstance(params, dict):
                out.append(StrategySpec(family=family, desk=desk, params=params))
        return out

    def review_journal(self, fund, entries, trade_outcomes) -> str | None:
        system = (
            "You are a trading desk risk reviewer. Given recent decision-journal "
            "entries and closed-trade outcomes, write a concise (<150 word) review "
            "noting what is working, what is not, and one concrete adjustment."
        )
        user = json.dumps({"fund": fund, "journal": entries[-30:],
                           "outcomes": trade_outcomes[-30:]}, default=str)
        try:
            return self._complete(system, user, max_tokens=400).strip()
        except Exception:
            return None


def _extract_json(text: str) -> str:
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        return text[start:end + 1]
    return text
