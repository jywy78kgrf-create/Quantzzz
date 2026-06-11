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
from ..universe import universe_for
from . import evolution
from .backtest import Backtester, chronological_split
from .feature_loader import load_feature_bundle
from .promotion import check_promotion, evaluate
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

    @classmethod
    def build(cls, cfg: Config, desk: str) -> "ResearchDesk":
        conn = get_conn(cfg.db_path)
        store = SnapshotStore(cfg.snapshot_dir)
        tickers = universe_for(desk, cfg.snapshot_dir)
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
        train_dates, test_dates = chronological_split(prices.index)
        train_b = self.bundle.slice(train_dates)
        test_b = self.bundle.slice(test_dates)

        run_id = insert(self.conn, "research_runs", desk=self.desk,
                        started_ts=utcnow(), config_json=dumps({"iterations": iterations}))

        population: list[tuple[StrategySpec, float]] = self._load_population()
        seen: set[str] = set()
        promoted_returns = self._load_promoted_returns(test_b, bench)
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
                ev, promoted, reasons = self._evaluate_spec(
                    spec, train_b, test_b, bench, promoted_returns)
                strat_id = self._persist_strategy(spec, origin, promoted)
                self._persist_iteration(run_id, i, strat_id, ev, promoted, reasons)

                if ev is not None:
                    best = max(best, ev.oos_sharpe)
                    population.append((spec, ev.fitness))
                    population.sort(key=lambda x: x[1], reverse=True)
                    population[:] = population[:15]
                if promoted:
                    promotions += 1
                    promoted_returns.append(ev.oos_returns)
                    self._journal_promotion(spec, ev)

        self.conn.execute(
            "UPDATE research_runs SET ended_ts=?, iterations=?, promotions=? WHERE id=?",
            (utcnow(), iterations, promotions, run_id))
        self.conn.commit()
        return RunResult(self.desk, run_id, iterations, promotions, best)

    # ---- proposal ----
    def _propose(self, population: list[StrategySpec]):
        return evolution.propose(self.desk, population, self.rng)

    def _llm_proposals(self, population):
        summary = [{"family": s.family, "params": s.params, "fitness": round(f, 2)}
                   for s, f in population[:5]]
        spaces = {fam: [p.__dict__ for p in space_for(fam).params]
                  for fam in {s.family for s, _ in population}} or None
        try:
            proposals = self.llm.propose_strategies(self.desk, summary, spaces)
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
    def _evaluate_spec(self, spec, train_b, test_b, bench, promoted_returns):
        signal_fn = signal_fn_for(spec.family)
        try:
            is_w = signal_fn(train_b, spec.params)
            is_res = self.bt.run(is_w, train_b.prices)
        except Exception as e:
            return None, False, [f"error: {e}"]

        from . import metrics as M
        is_sharpe = M.sharpe(is_res.returns)
        if is_sharpe < self.cfg.promotion_for(self.desk).min_is_sharpe_bar:
            ev = _stub_eval(is_sharpe)
            return ev, False, ["weak in-sample"]

        try:
            oos_w = signal_fn(test_b, spec.params)
            oos_res = self.bt.run(oos_w, test_b.prices)
        except Exception as e:
            return None, False, [f"oos error: {e}"]

        ev = evaluate(is_res, oos_res, bench)
        passed, reasons = check_promotion(ev, self.cfg.promotion_for(self.desk), promoted_returns)
        return ev, passed, reasons

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
               equity_curve_json=curve_json)

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

    def _load_promoted_returns(self, test_b, bench) -> list[pd.Series]:
        rows = self.conn.execute(
            "SELECT family, params_json FROM strategies WHERE desk=? AND status='promoted'",
            (self.desk,)).fetchall()
        out = []
        for r in rows:
            try:
                spec = StrategySpec.from_row(r["family"], self.desk, r["params_json"])
                res = self.bt.run(signal_fn_for(spec.family)(test_b, spec.params), test_b.prices)
                out.append(res.returns)
            except Exception:
                continue
        return out


def _stub_eval(is_sharpe):
    from .promotion import Evaluation
    return Evaluation(is_sharpe, 0.0, 0.0, 0.0, 0.0, 0, 0.0, -1.0, pd.Series(dtype=float))


def _g(ev, attr):
    return getattr(ev, attr) if ev is not None else None
