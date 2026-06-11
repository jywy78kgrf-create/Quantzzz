"""Central configuration loaded from environment / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "snapshots"
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
DB_PATH = PROJECT_ROOT / "quantzzz.db"

FUNDS = ("equity", "biotech")
BENCHMARKS = {"equity": "SPY", "biotech": "XBI"}


@dataclass(frozen=True)
class PromotionThresholds:
    min_oos_sharpe: float = 1.0
    min_oos_alpha: float = 0.0          # annualized alpha vs benchmark
    max_drawdown: float = 0.25
    min_trades: int = 20
    min_oos_is_ratio: float = 0.4       # OOS Sharpe must be >= 40% of IS Sharpe
    max_correlation: float = 0.8        # vs already-promoted strategies
    min_is_sharpe_bar: float = 0.5      # cheap in-sample rejection


# Biotech is structurally higher-volatility (binary catalyst events), so it
# carries a looser drawdown cap and a higher Sharpe bar to compensate.
PROMOTION_THRESHOLDS = {
    "equity": PromotionThresholds(),
    "biotech": PromotionThresholds(min_oos_sharpe=1.1, max_drawdown=0.50),
}


@dataclass(frozen=True)
class RiskLimits:
    max_position_pct: float            # single-name cap as fraction of equity
    max_gross_exposure: float          # gross exposure / equity
    max_positions: int
    stop_loss_pct: float               # per-position stop from entry
    drawdown_halt_pct: float           # fund-level halt from high-water mark
    target_vol: float                  # annualized portfolio vol target
    kelly_cap: float = 0.25


RISK_LIMITS = {
    "equity": RiskLimits(
        max_position_pct=0.08, max_gross_exposure=1.0, max_positions=20,
        stop_loss_pct=0.12, drawdown_halt_pct=0.15, target_vol=0.15,
    ),
    "biotech": RiskLimits(
        max_position_pct=0.05, max_gross_exposure=0.8, max_positions=16,
        stop_loss_pct=0.20, drawdown_halt_pct=0.20, target_vol=0.20,
    ),
}


@dataclass(frozen=True)
class Config:
    alpha_vantage_key: str = ""
    bpiq_api_key: str = ""
    edgar_user_agent: str = "Quantzzz research bot contact@example.com"
    anthropic_api_key: str = ""
    live_trading: bool = False
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""

    db_path: Path = DB_PATH
    snapshot_dir: Path = SNAPSHOT_DIR

    starting_cash: float = 1_000_000.0
    cost_bps: float = 10.0                  # round-trip transaction cost assumption in backtests
    slippage_bps: float = 5.0               # paper-broker fill slippage
    av_calls_per_min: int = 500             # premium tier allows ~600/min; stay under
    av_daily_budget: int = 100_000          # premium tier: effectively unlimited per day
    learning_review_every: int = 10         # closed trades per strategy between reviews
    llm_propose_every: int = 20             # research iterations between LLM proposal rounds

    promotion: PromotionThresholds = field(default_factory=PromotionThresholds)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    def risk_limits(self, fund: str) -> RiskLimits:
        return RISK_LIMITS[fund]

    def promotion_for(self, desk: str) -> PromotionThresholds:
        return PROMOTION_THRESHOLDS.get(desk, self.promotion)


def load_config() -> Config:
    load_dotenv(PROJECT_ROOT / ".env")
    return Config(
        alpha_vantage_key=os.environ.get("ALPHA_VANTAGE_API_KEY", ""),
        bpiq_api_key=os.environ.get("BPIQ_API_KEY", ""),
        edgar_user_agent=os.environ.get(
            "EDGAR_USER_AGENT", "Quantzzz research bot contact@example.com"
        ),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        live_trading=os.environ.get("LIVE_TRADING", "false").strip().lower() == "true",
        alpaca_api_key=os.environ.get("ALPACA_API_KEY", ""),
        alpaca_api_secret=os.environ.get("ALPACA_API_SECRET", ""),
    )
