"""Promotion criteria and walk-forward evaluation for the research loop."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..config import PromotionThresholds
from . import metrics as M
from .backtest import BacktestResult


@dataclass
class Evaluation:
    is_sharpe: float
    oos_sharpe: float                  # over all OOS windows combined
    oos_alpha: float
    oos_beta: float
    max_dd: float
    n_trades: int
    hit_rate: float
    fitness: float
    oos_returns: pd.Series
    window_sharpes: list[float] = field(default_factory=list)
    dsr_prob: float = 0.0              # deflated-Sharpe probability vs noise floor
    bench_max_dd: float = 0.0          # benchmark's drawdown over the same window
    bootstrap_q05: float | None = None  # 5th-pct Sharpe across bootstrap resamples
    downside_capture: float | None = None  # loss vs benchmark on its down days

    def as_row(self) -> dict:
        return {
            "is_sharpe": self.is_sharpe, "oos_sharpe": self.oos_sharpe,
            "oos_alpha": self.oos_alpha, "max_dd": self.max_dd,
            "n_trades": self.n_trades, "hit_rate": self.hit_rate,
            "fitness": self.fitness, "dsr_prob": self.dsr_prob,
        }


def evaluate_windows(is_res: BacktestResult, window_results: list[BacktestResult],
                     benchmark: pd.Series, n_effective_trials: int) -> Evaluation:
    """Combine walk-forward OOS windows into a single evaluation."""
    is_sharpe = M.sharpe(is_res.returns)
    window_sharpes = [M.sharpe(w.returns) for w in window_results]
    oos_returns = pd.concat([w.returns for w in window_results]).sort_index()
    oos_returns = oos_returns[~oos_returns.index.duplicated(keep="first")]
    trade_pnls = [p for w in window_results for p in w.trade_pnls]

    oos_sharpe = M.sharpe(oos_returns)
    alpha, beta = M.alpha_beta(oos_returns, benchmark)
    max_dd = M.max_drawdown(oos_returns)
    stats = M.trade_stats(trade_pnls)
    dsr = M.deflated_sharpe_prob(oos_returns, n_effective_trials)
    bench_oos = benchmark.reindex(oos_returns.index).dropna()
    bench_max_dd = M.max_drawdown(bench_oos)
    from .montecarlo import bootstrap_sharpe_quantile
    bootstrap_q05 = bootstrap_sharpe_quantile(oos_returns)
    dcap = M.downside_capture(oos_returns, benchmark)

    # fitness rewards OOS Sharpe and consistency, penalizes drawdown + overfit gap
    consistency_bonus = 0.2 * sum(1 for s in window_sharpes if s > 0) / max(len(window_sharpes), 1)
    overfit_penalty = max(0.0, is_sharpe - oos_sharpe) * 0.3
    dd_penalty = max_dd * 0.5
    fitness = oos_sharpe + consistency_bonus - overfit_penalty - dd_penalty

    return Evaluation(
        is_sharpe=is_sharpe, oos_sharpe=oos_sharpe, oos_alpha=alpha, oos_beta=beta,
        max_dd=max_dd, n_trades=stats.n_trades, hit_rate=stats.hit_rate,
        fitness=fitness, oos_returns=oos_returns,
        window_sharpes=[round(s, 3) for s in window_sharpes], dsr_prob=dsr,
        bench_max_dd=bench_max_dd, bootstrap_q05=bootstrap_q05,
        downside_capture=dcap,
    )


# A genuinely UNCORRELATED new edge carries portfolio value even at a slightly
# weaker standalone Sharpe, so it earns a modest reduction of the deflated-Sharpe
# bar — up to DSR_DIVERSIFY_CREDIT as its overlap with the book approaches 0,
# ramping to zero credit at DIVERSIFY_CORR. Only the DSR gate flexes; every other
# gate is untouched, and redundant candidates get nothing. This is the deliberate
# lever that lets a diversifying family (options greeks, low-vol) break a
# saturated, momentum-heavy book instead of the search stalling forever.
DSR_DIVERSIFY_CREDIT = 0.10
DIVERSIFY_CORR = 0.30


def check_promotion(ev: Evaluation, thr: PromotionThresholds,
                    promoted_returns: list[pd.Series]) -> tuple[bool, list[str]]:
    """Return (passed, fail_reasons)."""
    reasons = []
    if ev.oos_sharpe < thr.min_oos_sharpe:
        reasons.append(f"oos_sharpe {ev.oos_sharpe:.2f} < {thr.min_oos_sharpe}")
    if ev.oos_alpha < thr.min_oos_alpha:
        reasons.append(f"oos_alpha {ev.oos_alpha:.3f} < {thr.min_oos_alpha}")
    allowed_dd = min(thr.max_drawdown_hard_cap,
                     max(thr.max_drawdown, ev.bench_max_dd * thr.bench_dd_multiple))
    if ev.max_dd > allowed_dd:
        reasons.append(f"max_dd {ev.max_dd:.2f} > {allowed_dd:.2f} "
                       f"(bench dd {ev.bench_max_dd:.2f})")
    if ev.n_trades < thr.min_trades:
        reasons.append(f"n_trades {ev.n_trades} < {thr.min_trades}")
    if ev.is_sharpe > 0 and ev.oos_sharpe < ev.is_sharpe * thr.min_oos_is_ratio:
        reasons.append("oos/is consistency too low")

    # walk-forward consistency: most OOS windows must be profitable
    positive = sum(1 for s in ev.window_sharpes if s > 0)
    if ev.window_sharpes and positive < thr.min_positive_windows:
        reasons.append(f"only {positive}/{len(ev.window_sharpes)} OOS windows positive")

    # ---- overlap with the promoted book: measured ONCE, feeding both the
    # de-correlation rejection gates and the diversification DSR credit ----
    corr_ids: list[int] = []
    peer_corrs: list[float] = []
    for sid, pr in promoted_returns:
        joined = pd.concat([ev.oos_returns, pr], axis=1, join="inner").dropna()
        if len(joined) > 20:
            corr = joined.iloc[:, 0].corr(joined.iloc[:, 1])
            if corr is not None:
                peer_corrs.append(abs(corr))
                if corr > thr.max_correlation:
                    reasons.append(f"correlated {corr:.2f} with promoted #{sid}")
                    corr_ids.append(sid)
    # portfolio-aware: also reject redundancy with the BLEND of the whole book —
    # a correlated bloc (each pair under the cap) is still one factor.
    blend_corr = 0.0
    if promoted_returns:
        blend = pd.concat([pr for _, pr in promoted_returns], axis=1).mean(axis=1)
        joined = pd.concat([ev.oos_returns, blend], axis=1, join="inner").dropna()
        if len(joined) > 20:
            bc = joined.iloc[:, 0].corr(joined.iloc[:, 1])
            if bc is not None:
                blend_corr = abs(bc)
                if bc > thr.max_portfolio_correlation:
                    reasons.append(f"correlated {bc:.2f} with the promoted book "
                                   f"(adds no diversification)")
    # strongest tie to any single peer OR to the blended book (0 when book empty)
    book_corr = max([blend_corr, *peer_corrs]) if (peer_corrs or promoted_returns) else 0.0

    # deflated Sharpe: must beat the multiple-testing noise floor — with a
    # diversification credit for genuinely uncorrelated edges (see the constants).
    dsr_credit = DSR_DIVERSIFY_CREDIT * max(0.0, (DIVERSIFY_CORR - book_corr) / DIVERSIFY_CORR)
    eff_min_dsr = thr.min_dsr_prob - dsr_credit
    if ev.dsr_prob < eff_min_dsr:
        note = f" (uncorrelated credit -{dsr_credit:.2f})" if dsr_credit > 0.005 else ""
        reasons.append(f"dsr_prob {ev.dsr_prob:.2f} < {eff_min_dsr:.2f} (noise floor){note}")

    # bootstrap robustness: profitable across resampled histories, not just the
    # single realized path
    if ev.bootstrap_q05 is not None and ev.bootstrap_q05 < thr.min_bootstrap_q05:
        reasons.append(f"bootstrap q05 Sharpe {ev.bootstrap_q05:.2f} < "
                       f"{thr.min_bootstrap_q05} (not robust to resampling)")

    # regime robustness: don't amplify sector drawdowns. A strategy that
    # loses materially MORE than its benchmark on the benchmark's down days is
    # leveraged beta dressed as edge — independent of the time windows above.
    if (ev.downside_capture is not None
            and ev.downside_capture > thr.max_downside_capture):
        reasons.append(f"downside capture {ev.downside_capture:.2f} > "
                       f"{thr.max_downside_capture} (amplifies sector drawdowns)")

    return (len(reasons) == 0), reasons, corr_ids


REFINE_MARGIN = 1.15        # challenger must beat incumbent OOS Sharpe by >= 15%
LIVE_RESPECT_MULT = 1.25    # never swap out a strategy the learning loop rates this highly


def should_replace(ev: Evaluation, incumbent: dict) -> tuple[bool, str]:
    """Decide whether a correlated challenger may replace its incumbent.

    A backtest-better cousin only takes the seat when it clears a material
    margin (parameter-twin differences are usually noise), is at least as
    robust under resampling, and the incumbent is not currently being
    up-weighted by its LIVE trading record — forward evidence outranks
    backtest evidence.
    """
    inc_sharpe = incumbent.get("oos_sharpe") or 0.0
    if (incumbent.get("live_mult") or 1.0) >= LIVE_RESPECT_MULT:
        return False, "incumbent is outperforming live (learning multiplier high)"
    if inc_sharpe > 0 and ev.oos_sharpe < inc_sharpe * REFINE_MARGIN:
        return False, (f"margin too thin ({ev.oos_sharpe:.2f} vs {inc_sharpe:.2f}; "
                       f"needs +{(REFINE_MARGIN-1)*100:.0f}%)")
    if (ev.bootstrap_q05 or 0.0) < (incumbent.get("bootstrap_q05") or 0.0):
        return False, "less robust under bootstrap resampling"
    if ev.fitness <= (incumbent.get("fitness") or 0.0):
        return False, "fitness not higher"
    gain = (ev.oos_sharpe / inc_sharpe - 1) * 100 if inc_sharpe > 0 else 0.0
    return True, (f"refined replacement: OOS Sharpe {ev.oos_sharpe:.2f} vs "
                  f"{inc_sharpe:.2f} (+{gain:.0f}%), bootstrap and fitness superior")
