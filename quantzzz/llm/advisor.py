"""Advisor protocol and the no-op NullAdvisor."""

from __future__ import annotations

from typing import Protocol

from ..research.strategy_space import StrategySpec


class LLMAdvisor(Protocol):
    available: bool

    def propose_strategies(self, desk: str, leaderboard: list[dict],
                           param_spaces: dict | None) -> list[StrategySpec]:
        ...

    def review_journal(self, fund: str, entries: list[dict],
                       trade_outcomes: list[dict]) -> str | None:
        ...


class NullAdvisor:
    """Used whenever the LLM layer is unavailable; all methods are no-ops."""

    available = False

    def propose_strategies(self, desk, leaderboard, param_spaces) -> list[StrategySpec]:
        return []

    def review_journal(self, fund, entries, trade_outcomes) -> str | None:
        return None
