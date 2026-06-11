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
rejects weak ideas, then evaluates survivors out-of-sample on a chronological split
with an embargo gap. A candidate is **promoted** only when it clears desk-specific
criteria — OOS Sharpe, positive alpha vs benchmark (SPY for equity, XBI for biotech),
bounded drawdown, a minimum trade count, IS/OOS consistency — and is de-correlated
(< 0.8) from already-promoted strategies. Every iteration is persisted so the labs
show the search progressing.

## Trader & recursive learning

Each session: mark-to-market, drawdown-halt check, process exits (stops / retired
strategies / exit signals), then rank and enter new candidates with vol-target ×
capped-Kelly sizing and hard risk limits. Every accept/reject/resize/halt is written
to the decision journal. After enough trades close, the learning loop recomputes
per-strategy hit-rate/payoff, adjusts each strategy's weight multiplier (clipped
0.25–2.0), retires persistent losers, and journals the adjustment.

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
