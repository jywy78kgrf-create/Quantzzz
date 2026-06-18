# PACE 2026 — Rooted Maximum Agreement Forest (MAF), Heuristic track

Solver and (forthcoming) evolutionary improvement loop for the PACE 2026
Heuristic challenge: given **two rooted binary trees** on the same `n` leaves,
output an agreement forest of **minimum size `k`**.

## Status

- **Phase 0 (environment): done.** `pace26stride` + `pace26checker` built,
  150 public heuristic instances downloaded, official checker verified to
  accept valid and reject invalid solutions.
- **Phase 1 (informed baseline): done and approved.**
- **Baseline strengthening: done.** Anytime randomized-restart greedy with a
  lookahead / 3-approximation cut rule. Full-150 mean official score lifted from
  0.19 (single-shot) to **0.539**, 150/150 feasible. See results below.
- Phases 3–5 (evolutionary loop, portfolio, packaging): not started — the
  evolutionary loop is gated on an LLM/API budget decision.

## Language

C++17 (`solver/maf_solver.cpp`). Chosen for speed, predictable memory, and
reliable SIGTERM handling on the largest instances (n up to ~15.7k).

## Algorithm (baseline)

Anytime randomized-restart greedy:

1. **Construction — "merge-first" common-cherry contraction.** Repeatedly
   contract any cherry `(a,b)` that is a cherry in *both* trees (a true
   agreement; never increases forest size), draining an incremental worklist
   that propagates each merge to its new neighbour. Only when no common cherry
   remains do we cut one leaf of a conflicting `T1`-cherry — it becomes its own
   component. A guaranteed global merge-first invariant (rescan before any cut)
   keeps the forest as small as a merge-first greedy allows. This is the
   constructive skeleton of the classic rooted-MAF 3-approximation
   (Bordewich–Semple; Whidden–Beiko–Zeh).
2. **Search.** Restart the construction with randomized cherry ordering, random
   conflict selection, randomized cut choice, and **alternating drive tree**
   (T1-driven vs T2-driven — different trees expose different cuts), keeping the
   smallest forest found, until the time budget expires.

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

## Results (official checker via `stride run`)

**Full 150 public instances, 20 s budget each** (the solver plateaus well
before 300 s — verified 120 s ≈ 20 s — so this closely tracks the real
submission score). `score` is the official PACE per-instance heuristic score
`f(k)=(max(0,(u-k)/(u-k*)))²`; `k*` is the community best-known size reported by
the STRIDE server (validated to equal the live optil best-known). Per-instance
numbers are in [`results_full150_20s.tsv`](results_full150_20s.tsv).

- **Feasibility: 150/150 valid, 0 infeasible, 0 timeouts, 0 runtime errors.**
- **Mean official score 0.539** (≈ 53.9/100 optil-style), mean deficit vs
  best-known **12.6 %**.
- By size: n≤200 → 0.509 (8.2 % deficit) · 200–1k → 0.603 (12.4 %) ·
  1k–5k → 0.532 (15.3 %) · >5k → 0.546 (14.6 %).
- Peak memory ~7 MB on the largest instance (n=14482); SIGTERM emits a valid
  best-so-far immediately (verified by killing mid-run).

### How the algorithm was strengthened (tuning sample of 22, 20 s each)

Each step measured against the official checker; gains confirmed on a disjoint
26-instance held-out set (held-out mean 0.508 vs tuning 0.508 — no overfitting).

| variant                                       | mean  | large-inst. deficit |
|-----------------------------------------------|-------|---------------------|
| single-shot greedy                            | 0.190 | ~30 %               |
| + anytime randomized restarts                 | 0.257 | —                   |
| + merge-first invariant + bidirectional drive | 0.284 | ~25 %               |
| + 1-ply lookahead cut                          | 0.384 | ~22 %               |
| + max-gain conflict selection                 | 0.416 | ~20 %               |
| + 3-candidate (3-approximation) cut           | 0.496 | ~16 %               |
| + harm tie-break                              | 0.508 | —                   |
| + diversified restarts                        | 0.527 | ~13 %               |

The high-value lever was the cut rule (lookahead + the three rooted-MAF
3-approximation candidates + max-gain selection), which lowers the deterministic
greedy floor and so helps the large instances where restarts cannot
(empirically, 6× the restarts yields 0 improvement on large instances — the
greedy reaches a robust local optimum).

### Known ceiling

The remaining ~13 % deficit is algorithmic, not a search-budget issue. These
instances have *large* agreement forests (k ≈ 0.5–0.8·n), so FPT/exact methods
are out, and the greedy's local optimum resists restarts and single-step
perturbation. Closing it toward the leaders (who sit near-optimal, ~99/100)
needs a different class: a strong large-neighbourhood/destroy-repair
metaheuristic, cluster/treewidth decomposition (the instances ship `#x
treedecomp` hints), or the LLM-driven evolutionary loop (Phase 3).

Reproduce: `stride run -s solver/maf_solver -i <list>.lst -t 300 -g 5 -p <cores>`.
