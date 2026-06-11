"""Strategy proposal operators: random, mutation, crossover, heuristic."""

from __future__ import annotations

import random

from .strategies import families_for, space_for
from .strategy_space import StrategySpec


def random_spec(desk: str, rng: random.Random) -> StrategySpec:
    family = rng.choice(families_for(desk))
    space = space_for(family)
    return StrategySpec(family=family, desk=desk, params=space.random_params(rng))


def mutate(parent: StrategySpec, rng: random.Random, temperature: float = 1.0) -> StrategySpec:
    space = space_for(parent.family)
    params = dict(parent.params)
    # perturb 1-3 parameters
    targets = rng.sample(space.params, k=min(len(space.params), rng.randint(1, 3)))
    for pdef in targets:
        params[pdef.name] = pdef.mutate(params.get(pdef.name), rng, temperature)
    return StrategySpec(parent.family, parent.desk, space.clamp(params))


def crossover(a: StrategySpec, b: StrategySpec, rng: random.Random) -> StrategySpec:
    """Cross two specs. If different families, just mutate the fitter parent (a)."""
    if a.family != b.family:
        return mutate(a, rng)
    space = space_for(a.family)
    params = {p.name: rng.choice([a.params.get(p.name), b.params.get(p.name)])
              for p in space.params}
    return StrategySpec(a.family, a.desk, space.clamp(params))


def heuristic_proposal(leaderboard: list[StrategySpec], desk: str,
                       rng: random.Random) -> StrategySpec:
    """Jitter around the current best, or random when the board is empty."""
    if not leaderboard:
        return random_spec(desk, rng)
    parent = leaderboard[0]
    return mutate(parent, rng, temperature=0.4)


def propose(desk: str, population: list[StrategySpec], rng: random.Random) -> tuple[StrategySpec, str]:
    """Pick an operator by weighted draw; returns (spec, origin)."""
    r = rng.random()
    if r < 0.25 or len(population) < 2:
        return random_spec(desk, rng), "random"
    if r < 0.70:
        parent = _weighted_choice(population, rng)
        return mutate(parent, rng), "mutation"
    if r < 0.85:
        a, b = rng.sample(population[:8], 2) if len(population) >= 2 else (population[0], population[0])
        return crossover(a, b, rng), "crossover"
    return heuristic_proposal(population, desk, rng), "heuristic"


def _weighted_choice(population: list[StrategySpec], rng: random.Random) -> StrategySpec:
    """Fitness-weighted by rank (population assumed sorted best-first)."""
    n = len(population)
    weights = [n - i for i in range(n)]
    return rng.choices(population, weights=weights, k=1)[0]
