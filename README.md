# Quantzzz — Autonomous AI Quant Fund

Quantzzz runs two self-improving quant funds end to end:

- **Equity Quant Desk** — a team of research agents iteratively propose, backtest,
  mutate, and promote stock strategies until they find out-of-sample *edge* and
  *alpha*. Signals come from price/volume (Alpha Vantage), "beat and raise"
  earnings and insider buying (SEC EDGAR).
- **Biotech Quant Desk** — the same iterate-until-edge loop on biotech, driven by
  catalyst data (PDUFA dates, post-catalyst drift, cash-runway screens) from BPIQ.
- **Two AI Trader Agents** (one per fund) — paper-trade the promoted strategies:
  pick candidates, size positions (vol-target × capped Kelly), enforce risk limits,
  journal *why* every decision was made, and run a **recursive learning loop** that
  reweights and retires strategies based on realized outcomes.
- **Streamlit dashboards** — firm overview, both quant labs, both trader desks,
  the decision journal / learning view, and a data-health page.

Real (live) trading is supported behind a hard safety gate and is **off by default**.

## How the pieces fit

```
 data providers          research desks            trader agents          dashboards
 ┌───────────────┐       ┌──────────────────┐      ┌────────────────┐     ┌──────────┐
 │ Alpha Vantage │──┐    │ propose → backtest│      │ candidates →   │     │ firm     │
 │ SEC EDGAR     │  ├──▶ │ → evaluate (OOS)  │─────▶│ size → risk →  │────▶│ labs     │
 │ BPIQ          │  │    │ → promote (edge)  │ prom-│ paper fill →   │     │ desks    │
 └───────────────┘  │    └──────────────────┘ oted │ journal → learn│     │ journal  │
   snapshots/cache ─┘       (SQLite-persisted)      └────────────────┘     └──────────┘
```

Everything is persisted in SQLite (`quantzzz.db`) and a committed offline data
bundle (`data/snapshots/`), so the system is restart-safe and runs without a
network connection.

## Quick start

```bash
pip install -e ".[dev]"          # add ".[llm]" for the optional Anthropic advisor
cp .env.example .env             # fill in API keys (all optional; snapshots work offline)

python -m quantzzz init-db                               # create the schema
python -m quantzzz refresh-data --desk all               # build/refresh snapshots (cached)
python -m quantzzz research --desk equity  --iterations 50   # find edge (equity)
python -m quantzzz research --desk biotech --iterations 50   # find edge (biotech)
python -m quantzzz replay --fund equity  --lookback-days 365 # build a paper track record
python -m quantzzz replay --fund biotech --lookback-days 365
python -m quantzzz dashboard                             # launch the dashboards
```

Or run the whole thing continuously:

```bash
python -m quantzzz run --interval-s 900   # refresh → research → trade, looped (Ctrl-C safe)
```

## Configuration (`.env`)

| Var | Purpose | Default |
|-----|---------|---------|
| `ALPHA_VANTAGE_API_KEY` | price/quote data | — (offline snapshots used if absent) |
| `BPIQ_API_KEY` | biotech catalysts (`api.bpiq.com`) | — |
| `EDGAR_USER_AGENT` | required UA for SEC EDGAR | generic fallback |
| `ANTHROPIC_API_KEY` | enables LLM strategy proposals + journal reviews | — (NullAdvisor) |
| `LIVE_TRADING` | must be `true` **and** broker keys set to leave paper mode | `false` |

## Agent brains: hybrid

The research and trading loops are **fully algorithmic** and need no LLM. If
`ANTHROPIC_API_KEY` is set, an optional advisor (`claude-sonnet-4-6`) adds novel
strategy proposals (validated/clamped to the parameter space) and natural-language
trade-journal reviews. With no key, a `NullAdvisor` no-ops and behavior is identical
otherwise.

## Research loop (find edge / alpha)

Each iteration proposes a strategy spec (random / fitness-weighted mutation /
crossover / heuristic, plus periodic LLM proposals), backtests it in-sample, cheaply
rejects weak ideas, then evaluates survivors across **three walk-forward OOS
windows**. Research runs on a survivorship-aware universe that includes ~34 delisted
companies (Foot Locker, Marathon Oil, Avon...) so strategies are tested against the
firms that died, not just the winners. A candidate is **promoted** only when it
clears the full gauntlet:

- OOS Sharpe and positive alpha vs benchmark (SPY / XBI)
- **benchmark-relative drawdown** (a long-only strategy can't be expected to draw
  down less than its own market in a crash; hard-capped at 50/55%)
- a majority of walk-forward windows independently profitable
- **deflated Sharpe** (Bailey & López de Prado) above the expected-max-Sharpe noise
  floor of the whole search — corrects for multiple testing
- **bootstrap robustness**: 5th-percentile Sharpe across 500 block-bootstrap
  resamples must stay positive (profitable beyond the single realized path)
- de-correlation (< 0.8) from already-promoted strategies

Every iteration is persisted so the labs show the search progressing.

### External biotech signals (contaminated-discovery candidates)

The biotech desk also ingests a committed external signal export under
`data/snapshots/external/` — `signal_history_export.parquet` (point-in-time
signal observations), `catalyst_events_export.csv` (the pinned `event_id`
catalyst calendar), and `signal_spec_extract.csv` (research provenance). The
loader (`quantzzz/data/external_signals.py`) builds strictly point-in-time
feature panels, handling the export's **three different `as_of` semantics**:
pre-catalyst **candle days** (event-pinned price signals), **options market
days** (IV / skew / risk-reversal / open-interest), and **SEC filing dates**
(insider net-purchase signals) — each with its own staleness tolerance and an
as-of (never future) merge.

Three families consume them: `options_iv_runup` (high pre-catalyst ATM IV drifts
up into events), `insider_conviction` (point-in-time net Form-4 buying), and the
event-anchored `event_anchored` family (trades the pinned catalyst calendar,
ranked by one external signal). The **reconciliation flags** from the spec are
encoded, not re-litigated: no `short_float` (look-ahead), `rc_*` excluded
(temporal audit pending), risk-reversal in **unsigned `|RR|` form only**
(bimodal), and only one member of any correlated cluster is rankable (the IV
tenor ladder collapses to `iv_atm_30d`).

These signals were surfaced by a multi-phase research scan on overlapping data,
so they are treated as **contaminated-discovery** candidates: a stricter
promotion gate (`PROMOTION_THRESHOLDS_EXTERNAL` — deflated-Sharpe ≥ 0.90, all
three walk-forward windows profitable, bootstrap 5th-pct Sharpe ≥ 0.10, 30+
trades) and the **forward paper record as the referee**. A backtest pass makes a
family a *candidate for paper trading*, not a validated edge.

## Trader & recursive learning

The trader is a **weight-tracking rebalancer**: each session it computes the
combined target portfolio of its fund's promoted strategies (equal-capital blend ×
learned multipliers) and rebalances toward it — so live execution is mathematically
consistent with how the strategies were validated. Intelligence sits as overlays on
the targets:

- graduated risk: halve exposure at the de-risk drawdown (−18%/−22%), liquidate
  only at catastrophic levels (−35%/−45%), auto-recover when healed
- volatility-aware disaster stops (≥ 2.5× a 21-day vol move) with a 14-day
  re-entry cooldown
- pre-earnings blackout on weight increases (3 days before a scheduled report)
- biotech **catalyst scenario engine**: empirical EV/tail/Kelly from 548 real
  historical catalyst price reactions; blocks holding into near events with a
  negative event profile
- **Monte Carlo halt-risk throttle**: bootstraps the live book 5,000 paths forward
  and shrinks exposure increases when P(hitting the halt within 63d) exceeds 5%

Every adjustment is journaled with its reasoning. After enough trades close, the
learning loop recomputes per-strategy hit-rate/payoff (no action under 15 closed
trades — small samples are noise), adjusts weight multipliers (clipped 0.25–2.0),
retires persistent losers (20+ closed trades, < 35% hit rate, negative P&L), and
journals the adjustment.

## Safety

The broker factory returns the `PaperBroker` unless `LIVE_TRADING=true` **and** broker
credentials are present; the `AlpacaBroker` adapter is an unimplemented stub that
documents the drop-in path. There is no way to place a real order with the default
config.

## Tests

```bash
python -m pytest        # metrics, backtester no-lookahead, sizing, risk, paper broker,
                        # evolution bounds, learning, and a research smoke test
```

## Layout

- `quantzzz/data/` — Alpha Vantage, EDGAR, BPIQ clients; caching, rate limiting, snapshots, features
- `quantzzz/research/` — strategy space, families, backtester, metrics, evolution, promotion, the loop
- `quantzzz/trading/` — broker interface + paper broker, sizing, risk, signals, journal, learning, trader
- `quantzzz/llm/` — optional Anthropic advisor + NullAdvisor
- `dashboards/` — Streamlit multi-page app
