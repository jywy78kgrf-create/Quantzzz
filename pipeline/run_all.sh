#!/usr/bin/env bash
# Reproducibility: regenerates the full x402 audit dataset from scratch.
# Raw pulls are immutable — to force a truly fresh snapshot, change
# snapshot.label in pipeline/config.yaml first (raw files never overwrite).
set -euo pipefail
cd "$(dirname "$0")"

python3 pull_bazaar.py        # Phase 1: CDP Bazaar catalog
python3 pull_census.py        # Phase 1: x402scan seller census
python3 pull_origins.py       # Phase 1: origin->wallet map
python3 coverage_join.py      # DELTA 2a: Bazaar vs index coverage
python3 classify_census.py    # Phase 2 pass 1 (census-level buckets)
python3 allocate_deep.py      # DELTA 1: deep-pull allocation (seeded)
python3 pull_deep.py          # Phase 2: transfer-level pulls (resumable)
python3 deep_features.py      # Phase 2: behavioral features
python3 classify_final.py     # Phase 2 pass 2 + DELTA 3 buyer inflation
python3 liveness_probe.py     # Phase 2: endpoint liveness (no payments)
python3 spot_audit.py         # DELTA 2b: on-chain index accuracy audit
