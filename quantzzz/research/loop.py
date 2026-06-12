"""The iterate-until-edge research loop for a desk.

Each iteration proposes a strategy spec (random / mutation / crossover /
heuristic, plus periodic LLM proposals), backtests it in-sample, cheaply
rejects weak ideas, evaluates survivors out-of-sample, persists the iteration,
and promotes strategies that clear the criteria and are de-correlated from
what's already promoted.
"""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass

import pandas as pd

from ..config import BENCHMARKS, Config
from ..db import dumps, get_conn, insert, utcnow
from ..data.snapshots import SnapshotStore
from ..universe import research_universe_for
from . import evolution
from .backtest import Backtester, walk_forward_windows
from .feature_loader import load_feature_bundle
from .promotion import check_promotion, evaluate_windows, should_replace
from .strategies import signal_fn_for, space_for
from .strategy_space import StrategySpec


@dataclass
class RunResult:
    desk: str
    run_id: int
    iterations: int
    promotions: int
    best_oos_sharpe: float

    def summary(self) -> str:
        return (f"[{self.desk}] run {self.run_id}: {self.iterations} iters, "
                f"{self.promotions} promoted, best OOS Sharpe {self.best_oos_sharpe:.2f}")


class ResearchDesk:
    def __init__(self, cfg: Config, desk: str, conn: sqlite3.Connection,
                 bundle, llm=None):
        self.cfg = cfg
        self.desk = desk
        self.conn = conn
        self.bundle = bundle
        self.llm = llm
        self.bt = Backtester(cost_bps=cfg.cost_bps)
        self.rng = random.Random()
        self.benchmark_ticker = BENCHMARKS[desk]
        # liquidity-aware per-name costs: small caps pay realistic spreads
        from ..data import features as F
        self.cost_panel = F.trading_cost_bps(bundle.prices, bundle.volume,
                                             fallback_bps=cfg.cost_bps)

    @classmethod
    def build(cls, cfg: Config, desk: str) -> "ResearchDesk":
        conn = get_conn(cfg.db_path)
        store = SnapshotStore(cfg.snapshot_dir)
        # research uses the survivorship-aware universe (live + delisted names)
        tickers = research_universe_for(desk, cfg.snapshot_dir)
        bundle = load_feature_bundle(cfg, desk, tickers, store, conn)
        from ..llm import get_llm
        return cls(cfg, desk, conn, bundle, llm=get_llm(cfg))

    # ---- benchmark returns aligned to OOS dates ----
    def _benchmark_returns(self, store: SnapshotStore) -> pd.Series:
        df = store.load_prices(self.benchmark_ticker)
        if df is None:
            return pd.Series(dtype=float)
        return df["close"].pct_change()

    def run(self, iterations: int) -> RunResult:
        store = SnapshotStore(self.cfg.snapshot_dir)
        bench = self._benchmark_returns(store)
        prices = self.bundle.prices
        is_dates, oos_windows = walk_forward_windows(prices.index)

        run_id = insert(self.conn, "research_runs", desk=self.desk,
                        started_ts=utcnow(), config_json=dumps({"iterations": iterations}))

        population: list[tuple[StrategySpec, float]] = self._load_population()
        seen: set[str] = set()
        promoted_returns = self._load_promoted_returns(oos_windows, bench)
        promotions, best = 0, -99.0

        for i in range(1, iterations + 1):
            specs = [self._propose([s for s, _ in population])]
            if self.llm and i % self.cfg.llm_propose_every == 0:
                specs += self._llm_proposals(population)

            for spec, origin in specs:
                h = spec.spec_hash()
                if h in seen:
                    continue
                seen.add(h)
                ev, promoted, reasons, corr_ids = self._evaluate_spec(
                    spec, is_dates, oos_windows, bench, promoted_returns)
                only_corr_blocked = (not promoted and ev is not None and corr_ids
                                     and all("correlated" in r for r in reasons))
                if only_corr_blocked:
                    swapped = self._try_refinement(spec, ev, corr_ids)
                    if swapped is not None:
                        promoted = True
                        reasons = []
                        promoted_returns[:] = [(sid, r) for sid, r in promoted_returns
                                               if sid != swapped]
                strat_id = self._persist_strategy(spec, origin, promoted)
                self._persist_iteration(run_id, i, strat_id, ev, promoted, reasons)

                if ev is not None:
                    best = max(best, ev.oos_sharpe)
                    population.append((spec, ev.fitness))
                    population.sort(key=lambda x: x[1], reverse=True)
                    population[:] = population[:15]
                if promoted:
                    promotions += 1
                    promoted_returns.append((strat_id, ev.oos_returns))
                    self._journal_promotion(spec, ev)

        self.conn.execute(
            "UPDATE research_runs SET ended_ts=?, iterations=?, promotions=? WHERE id=?",
            (utcnow(), iterations, promotions, run_id))
        self.conn.commit()
        self._maybe_advise_expansion(promotions)
        return RunResult(self.desk, run_id, iterations, promotions, best)

    def _maybe_advise_expansion(self, promotions_this_run: int) -> None:
        """When the search saturates, ask the human to widen the field.

        Saturation = a large recent sample with zero promotions/replacements
        and no improvement in best OOS Sharpe vs the prior sample. Surfaces as
        an 'advice' entry in the decision feed (throttled to once per 3 days).
        """
        recent = self.conn.execute(
            "SELECT COUNT(*) c, MAX(oos_sharpe) s, MAX(promoted) p FROM ("
            " SELECT oos_sharpe, promoted FROM research_iterations"
            " WHERE desk=? ORDER BY id DESC LIMIT 300)", (self.desk,)).fetchone()
        prior = self.conn.execute(
            "SELECT MAX(oos_sharpe) s FROM ("
            " SELECT oos_sharpe FROM research_iterations WHERE desk=?"
            " ORDER BY id DESC LIMIT 300 OFFSET 300)", (self.desk,)).fetchone()
        if (recent["c"] or 0) < 300 or promotions_this_run or (recent["p"] or 0):
            return
        if prior["s"] and recent["s"] and recent["s"] > prior["s"] * 1.02:
            return  # still climbing
        throttled = self.conn.execute(
            "SELECT 1 FROM journal_entries WHERE fund=? AND entry_type='advice' "
            "AND ts > datetime('now','-3 days') LIMIT 1", (self.desk,)).fetchone()
        if throttled:
            return
        insert(self.conn, "journal_entries", fund=self.desk, ts=utcnow(),
               entry_type="advice", action="expand_research",
               reasoning=(f"[{self.desk}] search saturating: 300 candidates, no "
                          "promotions, best OOS Sharpe flat. Options to widen the "
                          "field: (1) add ANTHROPIC_API_KEY secret for LLM strategy "
                          "hypotheses; (2) new data: intraday bars, macro regime "
                          "series, more tickers; (3) options-IV families once "
                          "accumulated history suffices; (4) new family ideas - "
                          "tell Claude what to build."))

    # ---- proposal ----
    def _propose(self, population: list[StrategySpec]):
        return evolution.propose(self.desk, population, self.rng)

    def _llm_proposals(self, population):
        summary = [{"family": s.family, "params": s.params, "fitness": round(f, 2)}
                   for s, f in population[:5]]
        spaces = {fam: [p.__dict__ for p in space_for(fam).params]
                  for fam in {s.family for s, _ in population}} or None
        fails = self.conn.execute(
            "SELECT fail_reasons FROM research_iterations WHERE desk=? AND "
            "promoted=0 AND fail_reasons IS NOT NULL ORDER BY id DESC LIMIT 300",
            (self.desk,)).fetchall()
        from collections import Counter
        counts = Counter()
        for r in fails:
            for reason in r["fail_reasons"].split(";"):
                head = reason.strip().split(" ")[0]
                if head:
                    counts[head] += 1
        context = {"top_fail_reasons": dict(counts.most_common(6)),
                   "sample": len(fails)}
        try:
            proposals = self.llm.propose_strategies(self.desk, summary, spaces,
                                                    search_context=context)
        except Exception:
            return []
        out = []
        for spec in proposals:
            try:
                space = space_for(spec.family)
                out.append((StrategySpec(spec.family, self.desk,
                                         space.clamp(spec.params)), "llm"))
            except Exception:
                continue
        return out

    # ---- evaluation ----
    def _effective_trials(self) -> int:
        """Correlation-adjusted trial count for the deflated Sharpe.

        Evolutionary candidates are heavily correlated (mutations of the same
        parents), so raw iteration count overstates the search breadth. We use
        sqrt(OOS-evaluated candidates) as the effective number of independent
        trials — a documented, deliberately rough haircut.
        """
        row = self.conn.execute(
            "SELECT COUNT(*) c FROM research_iterations WHERE desk=? AND n_trades IS NOT NULL",
            (self.desk,)).fetchone()
        return max(1, int(round((row["c"] or 0) ** 0.5)))

    # External-signal families only have data from ~2018 (options) / 2019
    # (insider). Judged on the full 2004+ panel they hold nothing in-sample and
    # auto-fail, so their walk-forward windows are computed over their own
    # active history instead — with a hard floor so thin coverage is rejected
    # explicitly, not silently passed on a short lucky stretch.
    MIN_EXTERNAL_HISTORY_DAYS = 756        # ~3 trading years

    def _evaluate_spec(self, spec, is_dates, oos_windows, bench, promoted_returns):
        """Compute causal weights ONCE on the full panel, then slice per window."""
        signal_fn = signal_fn_for(spec.family)
        try:
            weights = signal_fn(self.bundle, spec.params)
        except Exception as e:
            return None, False, [f"error: {e}"], []

        from .strategies.biotech import EXTERNAL_FAMILIES
        if spec.family in EXTERNAL_FAMILIES:
            active = weights.abs().sum(axis=1) > 0
            if not active.any():
                return None, False, ["no active days (external signals absent)"], []
            covered = weights.index[weights.index >= active.idxmax()]
            if len(covered) < self.MIN_EXTERNAL_HISTORY_DAYS:
                return None, False, [
                    f"insufficient external history ({len(covered)} days "
                    f"< {self.MIN_EXTERNAL_HISTORY_DAYS})"], []
            is_dates, oos_windows = walk_forward_windows(covered)

        from . import metrics as M
        prices = self.bundle.prices
        is_res = self.bt.run(weights.loc[weights.index.isin(is_dates)],
                             prices.loc[prices.index.isin(is_dates)],
                             cost_panel=self.cost_panel)
        thr = self.cfg.promotion_for(self.desk, spec.family)
        is_sharpe = M.sharpe(is_res.returns)
        if is_sharpe < thr.min_is_sharpe_bar:
            return _stub_eval(is_sharpe), False, ["weak in-sample"], []

        try:
            window_results = [
                self.bt.run(weights.loc[weights.index.isin(w)],
                            prices.loc[prices.index.isin(w)],
                            cost_panel=self.cost_panel)
                for w in oos_windows
            ]
        except Exception as e:
            return None, False, [f"oos error: {e}"], []

        ev = evaluate_windows(is_res, window_results, bench, self._effective_trials())
        passed, reasons, corr_ids = check_promotion(ev, thr, promoted_returns)
        return ev, passed, reasons, corr_ids

    # ---- refinement: a materially better cousin may replace its incumbent ----
    def _incumbent_metrics(self, sid: int) -> dict:
        row = self.conn.execute("""
            SELECT MAX(oos_sharpe) oos_sharpe, MAX(fitness) fitness,
                   MAX(bootstrap_q05) bootstrap_q05
            FROM research_iterations WHERE strategy_id=?""", (sid,)).fetchone()
        mult = self.conn.execute(
            "SELECT weight_multiplier FROM strategy_performance WHERE strategy_id=? "
            "ORDER BY as_of_ts DESC LIMIT 1", (sid,)).fetchone()
        return {"oos_sharpe": row["oos_sharpe"], "fitness": row["fitness"],
                "bootstrap_q05": row["bootstrap_q05"],
                "live_mult": mult["weight_multiplier"] if mult else 1.0}

    def _try_refinement(self, spec, ev, corr_ids) -> int | None:
        """Replace the (single) correlated incumbent if the challenger clears
        the margin. Returns the retired incumbent id, or None."""
        if len(corr_ids) != 1:
            return None     # correlated with several edges: genuinely redundant
        sid = corr_ids[0]
        ok, why = should_replace(ev, self._incumbent_metrics(sid))
        from ..db import insert
        if not ok:
            insert(self.conn, "journal_entries", fund=self.desk, ts=utcnow(),
                   entry_type="learning", action="challenger_rejected",
                   reasoning=f"Challenger {spec.family} kept out: {why}.",
                   ref_table="strategies", ref_id=sid)
            return None
        self.conn.execute(
            "UPDATE strategies SET status='retired', retired_ts=? WHERE id=?",
            (utcnow(), sid))
        self.conn.commit()
        insert(self.conn, "journal_entries", fund=self.desk, ts=utcnow(),
               entry_type="promotion", action="refined_replacement",
               reasoning=f"{spec.family} replaces #{sid}: {why}.",
               ref_table="strategies", ref_id=sid)
        return sid

    # ---- persistence ----
    def _persist_strategy(self, spec, origin, promoted) -> int:
        h = spec.spec_hash()
        row = self.conn.execute("SELECT id FROM strategies WHERE spec_hash=?", (h,)).fetchone()
        if row:
            sid = row["id"]
        else:
            sid = insert(self.conn, "strategies", desk=self.desk, family=spec.family,
                         params_json=spec.to_json(), spec_hash=h,
                         status="candidate", origin=origin, created_ts=utcnow())
        if promoted:
            self.conn.execute(
                "UPDATE strategies SET status='promoted', promoted_ts=? WHERE id=?",
                (utcnow(), sid))
            self.conn.commit()
        return sid

    def _persist_iteration(self, run_id, i, strat_id, ev, promoted, reasons):
        curve_json = None
        if ev is not None and len(ev.oos_returns):
            curve = (1 + ev.oos_returns).cumprod()
            curve_json = dumps({str(k.date()): round(float(v), 4)
                                for k, v in curve.items()})
        insert(self.conn, "research_iterations", run_id=run_id, desk=self.desk,
               iter_num=i, strategy_id=strat_id, ts=utcnow(),
               is_sharpe=_g(ev, "is_sharpe"), oos_sharpe=_g(ev, "oos_sharpe"),
               oos_alpha=_g(ev, "oos_alpha"), max_dd=_g(ev, "max_dd"),
               n_trades=_g(ev, "n_trades"), hit_rate=_g(ev, "hit_rate"),
               fitness=_g(ev, "fitness"), promoted=int(promoted),
               fail_reasons="; ".join(reasons) if reasons else None,
               equity_curve_json=curve_json,
               window_sharpes=dumps(_g(ev, "window_sharpes") or []),
               dsr_prob=_g(ev, "dsr_prob"),
               bootstrap_q05=_g(ev, "bootstrap_q05"))

    def _journal_promotion(self, spec, ev):
        insert(self.conn, "journal_entries", fund=self.desk, ts=utcnow(),
               entry_type="promotion", ticker=None, action=spec.family,
               inputs_json=dumps(spec.params),
               reasoning=(f"Promoted {spec.family}: OOS Sharpe {ev.oos_sharpe:.2f}, "
                          f"alpha {ev.oos_alpha:.3f}, maxDD {ev.max_dd:.2f}, "
                          f"{ev.n_trades} trades."),
               ref_table="strategies", ref_id=None)

    def _load_population(self):
        rows = self.conn.execute(
            "SELECT s.family, s.params_json, i.fitness FROM strategies s "
            "JOIN research_iterations i ON i.strategy_id=s.id "
            "WHERE s.desk=? AND i.fitness IS NOT NULL ORDER BY i.fitness DESC LIMIT 15",
            (self.desk,)).fetchall()
        return [(StrategySpec.from_row(r["family"], self.desk, r["params_json"]),
                 r["fitness"]) for r in rows]

    def _load_promoted_returns(self, oos_windows, bench) -> list[pd.Series]:
        rows = self.conn.execute(
            "SELECT id, family, params_json FROM strategies WHERE desk=? AND status='promoted'",
            (self.desk,)).fetchall()
        all_oos = oos_windows[0].append(list(oos_windows[1:]))
        prices = self.bundle.prices
        out = []
        for r in rows:
            try:
                spec = StrategySpec.from_row(r["family"], self.desk, r["params_json"])
                weights = signal_fn_for(spec.family)(self.bundle, spec.params)
                res = self.bt.run(weights.loc[weights.index.isin(all_oos)],
                                  prices.loc[prices.index.isin(all_oos)],
                                  cost_panel=self.cost_panel)
                out.append((r["id"], res.returns))
            except Exception:
                continue
        return out


def _stub_eval(is_sharpe):
    from .promotion import Evaluation
    return Evaluation(is_sharpe, 0.0, 0.0, 0.0, 0.0, 0, 0.0, -1.0, pd.Series(dtype=float))


def _g(ev, attr):
    return getattr(ev, attr) if ev is not None else None
