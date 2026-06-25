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

    def propose_strategies(self, desk, leaderboard, param_spaces,
                           search_context=None) -> list[StrategySpec]:
        if not param_spaces:
            return []
        system = (
            "You are a quant strategist EXPANDING a research search. Evolutionary "
            "search (mutation/crossover) already tunes the parameters of "
            "known-good strategies well — do NOT compete with it on fine-tuning. "
            "Your edge is STRUCTURE: reach for families that have not yet promoted "
            "and especially COMBINATION families (which condition one signal on "
            "another, e.g. momentum gated by a regime, a dip bought only on "
            "quality names). Propose parameter sets that genuinely exercise those, "
            "not near-twins of the dominant family. Respond ONLY with a JSON array "
            'of {"family": str, "params": {...}} within documented bounds. Use the '
            "rejection stats to avoid known failure modes (dying on drawdown -> "
            "less exposure; on trade count -> more active variants)."
        )
        user = json.dumps({
            "desk": desk,
            "top_strategies": leaderboard,
            "parameter_spaces": param_spaces,
            "search_context": search_context or {},
            "instruction": ("Propose 3 specs that EXPAND coverage: prefer the "
                            "unpromoted_families and any combination families over "
                            "the already-promoted ones; avoid re-proposing the "
                            "dominant family unless materially different."),
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


    def select_shadows(self, candidates: list[dict], slots: int) -> list[dict] | None:
        """Research-committee call: which benched near-misses earn the
        pre-registered forward-trial slots. Returns picks with rationales."""
        system = (
            "You are a quant research committee selecting which benched "
            "strategies earn scarce pre-registered forward-trial (shadow "
            "paper-trading) slots. Prefer decorrelated signal bases, high "
            "deflated-Sharpe probability, bootstrap robustness, adequate trade "
            "counts, and consistency across walk-forward windows. Respond ONLY "
            "with a JSON array of {\"strategy_id\": int, \"rationale\": str} "
            "(rationale under 40 words), at most the requested number of slots."
        )
        user = json.dumps({"open_slots": slots, "candidates": candidates},
                          default=str)
        try:
            text = self._complete(system, user, max_tokens=600)
            payload = json.loads(_extract_json(text))
            return payload if isinstance(payload, list) else None
        except Exception:
            return None

    def synthesize_week(self, stats: dict) -> str | None:
        system = (
            "You are the head of research writing the weekly note for an "
            "autonomous quant fund. Given the week's statistics, write a concise "
            "(<200 word) synthesis: what the search found, how the strict "
            "external-signal bench moved (deflated-Sharpe trend), what the live "
            "forward record says, and the single most decision-relevant fact. "
            "Plain prose, no headers."
        )
        try:
            return self._complete(system, json.dumps(stats, default=str),
                                  max_tokens=500).strip()
        except Exception:
            return None


def _extract_json(text: str) -> str:
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        return text[start:end + 1]
    return text
