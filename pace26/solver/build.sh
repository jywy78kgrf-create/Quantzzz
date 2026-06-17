#!/usr/bin/env bash
# Build the PACE 2026 MAF solver.
set -e
cd "$(dirname "$0")"
g++ -O2 -std=c++17 -o maf_solver maf_solver.cpp
echo "built: $(pwd)/maf_solver"
