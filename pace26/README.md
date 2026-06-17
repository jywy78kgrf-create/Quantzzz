# PACE 2026 — Rooted Maximum Agreement Forest (MAF), Heuristic track

Solver and (forthcoming) evolutionary improvement loop for the PACE 2026
Heuristic challenge: given **two rooted binary trees** on the same `n` leaves,
output an agreement forest of **minimum size `k`**.

## Status

- **Phase 0 (environment): done.** `pace26stride` + `pace26checker` built,
  150 public heuristic instances downloaded, official checker verified to
  accept valid and reject invalid solutions.
- **Phase 1 (informed baseline): done — awaiting approval gate.**
  An anytime randomized-restart greedy solver. See results below.
- Phases 2–5 (fitness harness, evolutionary loop, portfolio, packaging): not
  started — gated on approval.

## Language

C++17 (`solver/maf_solver.cpp`). Chosen for speed, predictable memory, and
reliable SIGTERM handling on the largest instances (n up to ~15.7k).

## Algorithm (baseline)

Anytime randomized-restart greedy:

1. **Construction — "merge-first" common-cherry contraction.** Repeatedly
   contract any cherry `(a,b)` that is a cherry in *both* trees (a true
   agreement; never increases forest size). When no common cherry remains but
   the trees still disagree, cut one leaf of a conflicting `T1`-cherry — it
   becomes its own component. This is the constructive skeleton of the classic
   rooted-MAF 3-approximation (Bordewich–Semple; Whidden–Beiko–Zeh).
2. **Search.** Restart the construction with randomized cherry ordering and cut
   selection, keeping the smallest forest found, until the time budget expires.

**Feasibility guarantee.** Components are formed only from agreements (common
cherries) and singletons, so each component's induced restriction is identical
in both trees and components are disjoint — exactly the condition the official
checker (`bin_forest.rs::isolate_tree`) enforces.

**Robustness.** A `SIGTERM`/`SIGINT` handler always emits a valid best-so-far
solution (all-singletons until the first greedy completes, then the best forest
found), so the process never dies without a feasible answer within the PACE
soft (5 min) / hard (5 min 10 s) limits. Memory well under 8 GB.

## Build & run

```bash
cd solver && ./build.sh          # produces solver/maf_solver
./maf_solver < instance.nw       # solution (Newick forest) on stdout
```

The time budget defaults to 300 s (the PACE soft limit) and honours the
`STRIDE_TIMEOUT` environment variable when run under the STRIDE runner.

## Verifying with the official tooling

```bash
# single instance + solution
pace26stride/target/release/stride check instance.nw solution.out

# run + check + score against community best-known, in parallel
pace26stride/target/release/stride run -s solver/maf_solver -i list.lst -t 300 -g 5
# results in stride-logs/latest/summary.json
```

## Phase 1 results (official checker via `stride run`)

Sample of 22 size-spanning public instances, **20 s budget each** (the real
PACE limit is 300 s, so these are conservative). `score` is the official
per-instance heuristic score; `k*` is the community best-known size reported by
the STRIDE server.

- **Feasibility: 22/22 valid, 0 infeasible, 0 timeouts, 0 runtime errors.**
- **Mean official score 0.257, sum 5.66** (vs 0.190 / 4.18 for the single-shot
  greedy — randomized restarts help most on small/medium instances).
- Deficit vs best-known is ~15–30 % of `k` and is the target of the later
  evolutionary phases.

Reproduce: `stride run -s solver/maf_solver -i <list>.lst -t 300 -g 5 -p <cores>`.
