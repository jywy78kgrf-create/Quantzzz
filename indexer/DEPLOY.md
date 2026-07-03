# Deploying the durable snapshot schedule

The recurring snapshot is the moat: each run writes an immutable, date-stamped
per-seller aggregate that you can never reconstruct after the fact. **The clock
does not start until this is deployed somewhere persistent.** Two options —
start with A (zero-infra), graduate to B only if you outgrow it.

---

## Option A — GitHub Actions (zero-infra, recommended to start)

Workflow: `.github/workflows/daily-index.yml`. It runs the Base + Solana
indexers daily, writes the immutable snapshot to
`data/indexer/snapshots/<UTC-date>/`, and commits it back to the repo. SQLite
state persists between runs via `actions/cache`; the committed snapshots are the
durable record.

### One-time setup (5 minutes)

1. **Merge the workflow to your DEFAULT branch.**
   GitHub only runs `schedule:` workflows from the repository's default branch.
   On a feature branch it will *never* fire. Merge `daily-index.yml` to `main`
   (or whatever your default is), or set the default branch accordingly.

2. **Add the Solana RPC secret.**
   Repo → Settings → Secrets and variables → Actions → New repository secret:
   - Name: `X402_SOLANA_RPC`
   - Value: your keyed Solana RPC URL (e.g. `https://mainnet.helius-rpc.com/?api-key=…`)
   Use a **fresh** Helius key here — not the one used during development. The
   secret is masked in logs and never exposed to forks.

3. **Allow Actions to push.**
   Settings → Actions → General → Workflow permissions → **Read and write
   permissions** (so the job can commit the daily snapshot).

4. **Kick the first run manually.**
   Actions tab → daily-x402-index → "Run workflow". The first run bootstraps
   ~1 day of Base history and the recent Solana window, writes the first
   snapshot, and commits it. Confirm a commit lands in
   `data/indexer/snapshots/`.

### Operating notes
- **Cadence:** daily at 02:17 UTC. Change the `cron:` line for weekly, etc.
  Daily gives the finest cohort-survival resolution; weekly keeps commits fewer.
- **Gap safety:** if the Base indexer ever detects a hole below its frontier the
  job FAILS loudly (it will not snapshot over a gap). Fix with
  `index_base.py --from <a> --to <b>` and re-run. This is by design — a silent
  hole would quietly poison the trend data.
- **Solana isolation:** a Solana RPC outage logs an error but does NOT block the
  Base snapshot; Solana resumes from its per-relayer cursors next run.
- **Cache eviction:** GitHub evicts caches after ~7 days unused or at 10 GB. A
  daily run keeps it warm. If it is ever evicted, the indexer re-bootstraps
  recent history — the already-committed snapshots are unaffected.

### Cost
Free tier is ample: a daily run is ~10–20 min; public repos get unlimited
Actions minutes, private repos 2,000 min/month (≈ 6.5 h/day headroom).

---

## Option B — always-on box (for scale / multi-year continuity)

When you want sub-daily cadence, full historical backfill, or bulletproof state
continuity, a $5/mo VPS with a persistent disk beats committing state:

```cron
# /etc/cron.d/x402-index   (UTC)
17 2 * * *  quant  cd /opt/Quantzzz && X402_SOLANA_RPC=… /usr/bin/python3 indexer/daily_snapshot.py >> /var/log/x402-index.log 2>&1
```

- SQLite lives on the local disk (no cache/commit dance).
- Put `X402_SOLANA_RPC` in the unit's environment / an `EnvironmentFile`, never
  in the repo.
- Back up `data/indexer/base_settlements.sqlite` and the `snapshots/` dir (e.g.
  nightly `rclone` to object storage) so the substrate survives a box loss.
- For historical backfill, run the range/`before`-cursor backfill separately
  from the daily forward job so a long backfill never blocks a daily snapshot.

---

## What accrues, and why it's defensible
Each run appends `data/indexer/snapshots/<date>/seller_aggregates.csv` +
`snapshot_meta.json`. Over weeks these become the one thing a competitor cannot
backfill: the observed per-seller trajectory over time (new-seller cohorts,
survival, churn, volume trend) derived independently from chain — not from any
third-party API. Guard them like the asset they are: they are append-only and
must never be regenerated or overwritten.
