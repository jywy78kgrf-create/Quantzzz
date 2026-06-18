# PACE 2026 Heuristic (Rooted MAF) — submission package

## Solver (one paragraph)

The solver computes a small **agreement forest** of the two input rooted binary
trees by an *anytime randomized-restart greedy*. It repeatedly contracts every
*cherry* `(a,b)` that is a cherry in **both** trees (a true agreement, which
never enlarges the forest); when no common cherry remains it resolves a
conflicting cherry by cutting one leaf into its own component. The leaf to cut is
chosen by a **one-ply lookahead over the three rooted-MAF 3-approximation
candidates** (the two cherry leaves and the conflicting "intruder" leaf on the
other tree), picking the cut that immediately unlocks the most new agreements,
with a tie-break that avoids breaking existing cherries. The whole construction
is restarted under the time budget — driven alternately from either tree, with
diversified (reservoir) tie-breaking — keeping the smallest forest found. A
`SIGTERM` handler always prints the best forest found so far, so the process is
robust to the soft/hard time limits; memory stays a few MB even at n≈15k.

## Files

- `solver/maf_solver.cpp` — the complete solver (single C++17 file, no deps).
- `solver/build.sh` — builds it with `g++ -O2 -std=c++17`.
- `results_full150_20s.tsv` — per-instance k / score on the 150 public instances.
- `LICENSE` — MIT.

## Build

```bash
cd solver && ./build.sh          # -> solver/maf_solver
# or directly:
g++ -O2 -std=c++17 -o maf_solver solver/maf_solver.cpp
```

No external libraries. Requires a C++17 compiler (tested with g++ 13).

## Run

```bash
./maf_solver < instance.nw > solution.out
```

Instance on stdin (PACE 2026 format), forest on stdout (one `;`-terminated
Newick tree per line). The time budget defaults to 300 s (the PACE soft limit)
and honours `STRIDE_TIMEOUT` when run under the STRIDE runner.

## Results (official checker)

Full 150 public instances, 20 s each (the solver plateaus well before 300 s):
**150/150 feasible, mean official score 0.539, mean deficit 12.6 % vs
community best-known.** See `results_full150_20s.tsv`.

## Manual upload to optil.io (you must do this — I cannot submit)

1. Go to the PACE 2026 **Rooted Maximum Agreement Forest — Heuristic** problem
   on optil.io and open the **SUBMIT** tab.
2. Language: **C++** (the entry is a single self-contained `.cpp`). Upload
   `solver/maf_solver.cpp` as the submission source.
3. Run the **lite / format check** first (optil's quick smoke test) to confirm
   it compiles and the I/O format is accepted before spending a full run.
4. Submit the full run. **Respect the 1-hour throttle** between full submissions
   on the problem — plan resubmissions accordingly.
5. After it finishes, read the per-instance scores on the **STANDING** tab;
   compare against `results_full150_20s.tsv` to confirm parity (optil best-known
   equals the STRIDE best-known we used: optil column N ↔ `heuristic(N-1)`).

This deliverable is **submission-ready**; the actual upload and the resulting
leaderboard placement are yours to complete.
