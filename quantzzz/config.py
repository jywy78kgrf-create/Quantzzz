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
    min_positive_windows: int = 3       # of the 5 walk-forward OOS windows
    min_dsr_prob: float = 0.60          # deflated-Sharpe prob vs multiple-testing
                                        # noise floor (raise to 0.95 for strict mode)
    # drawdown gate is benchmark-relative: a long-only strategy cannot be
    # expected to draw down less than its own market in a crash. Allowed DD =
    # min(hard_cap, max(max_drawdown, benchmark_dd * bench_dd_multiple)).
    bench_dd_multiple: float = 1.15
    max_drawdown_hard_cap: float = 0.50
    # bootstrap robustness: 5th-percentile Sharpe across block-bootstrap
    # resamples of the OOS returns must stay above this (fights the
    # "profitable on the one realized path only" failure mode)
    min_bootstrap_q05: float = 0.0
    bootstrap_paths: int = 500


# Biotech is structurally higher-volatility (binary catalyst events), so it
# carries a looser drawdown cap and a higher Sharpe bar to compensate.
PROMOTION_THRESHOLDS = {
    "equity": PromotionThresholds(),
    "biotech": PromotionThresholds(min_oos_sharpe=1.1, max_drawdown=0.50,
                                   bench_dd_multiple=1.0,
                                   max_drawdown_hard_cap=0.55),
}

# Contaminated-discovery gate for the external-signal biotech families. The
# signals were surfaced by a multi-phase research scan on overlapping, partly
# whole-sample data, so backtest promotions carry extra overfitting risk. We
# tighten every defence that fights selection bias — deflated Sharpe, bootstrap
# robustness, OOS/IS consistency, walk-forward breadth — and treat the forward
# paper record as the real referee (README "forward paper record"). A backtest
# pass here is a *candidate for paper trading*, not a verdict.
PROMOTION_THRESHOLDS_EXTERNAL = PromotionThresholds(
    min_oos_sharpe=1.3,            # above the 1.1 biotech bar
    min_oos_alpha=0.0,
    max_drawdown=0.50,
    bench_dd_multiple=1.0,
    max_drawdown_hard_cap=0.55,
    min_trades=30,                 # more evidence before believing the edge
    min_oos_is_ratio=0.55,         # less OOS-vs-IS decay tolerated
    min_positive_windows=5,        # ALL five walk-forward windows profitable
    min_dsr_prob=0.90,             # strict deflated-Sharpe (vs 0.60 default)
    min_bootstrap_q05=0.10,        # robust, not just the one realized path
)


@dataclass(frozen=True)
class RiskLimits:
    max_position_pct: float            # single-name cap as fraction of equity
    max_gross_exposure: float          # gross exposure / equity
    max_positions: int
    stop_loss_pct: float               # per-position stop from entry (floor; vol-scaled up)
    drawdown_halt_pct: float           # catastrophic level: liquidate-only
    target_vol: float                  # annualized portfolio vol target
    kelly_cap: float = 0.25
    drawdown_derisk_pct: float = 0.20  # halve exposure here; must sit INSIDE the
                                       # halt level and OUTSIDE normal noise


# Halt levels must sit beyond the drawdowns the promotion gates explicitly
# accept (benchmark-relative, ~35-40% in crash windows) or the fund liquidates
# strategies at the bottom of moves they were validated to survive.
RISK_LIMITS = {
    "equity": RiskLimits(
        max_position_pct=0.08, max_gross_exposure=1.0, max_positions=20,
        stop_loss_pct=0.12, drawdown_halt_pct=0.35, target_vol=0.15,
        drawdown_derisk_pct=0.18,
    ),
    "biotech": RiskLimits(
        max_position_pct=0.05, max_gross_exposure=0.8, max_positions=16,
        stop_loss_pct=0.20, drawdown_halt_pct=0.45, target_vol=0.20,
        drawdown_derisk_pct=0.22,
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
    av_calls_per_min: int = 590             # premium tier allows 600/min; thin margin under it
    av_daily_budget: int = 100_000          # premium tier: effectively unlimited per day
    learning_review_every: int = 10         # closed trades per strategy between reviews
    pre_earnings_blackout_days: int = 3     # no new entries this close to a report
    max_halt_probability: float = 0.05      # MC sizing: P(drawdown halt in horizon)
    mc_horizon_days: int = 63               # forward horizon for the halt simulation
    min_catalyst_events: int = 8            # min history for catalyst scenario sizing
    catalyst_gate_days: int = 10            # EV gate applies only this close to events
    min_rebalance_weight: float = 0.005     # ignore weight deltas below 0.5% of equity
    llm_propose_every: int = 20             # research iterations between LLM proposal rounds

    promotion: PromotionThresholds = field(default_factory=PromotionThresholds)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    def risk_limits(self, fund: str) -> RiskLimits:
        return RISK_LIMITS[fund]

    def promotion_for(self, desk: str, family: str | None = None) -> PromotionThresholds:
        # External contaminated-discovery families face the stricter gate.
        if family is not None:
            from .research.strategies.biotech import EXTERNAL_FAMILIES
            if family in EXTERNAL_FAMILIES:
                return PROMOTION_THRESHOLDS_EXTERNAL
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
