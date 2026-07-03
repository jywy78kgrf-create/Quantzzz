"""Strategy proposal operators: random, mutation, crossover, heuristic."""

from __future__ import annotations

import random

from .strategies import families_for, space_for
from .strategy_space import StrategySpec


def random_spec(desk: str, rng: random.Random,
                family_weights: dict | None = None) -> StrategySpec:
    fams = families_for(desk)
    if family_weights:   # meta-learning prior: favor families that survive forward
        w = [max(0.01, family_weights.get(f, 1.0)) for f in fams]
        family = rng.choices(fams, weights=w, k=1)[0]
    else:
        family = rng.choice(fams)
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
                       rng: random.Random, family_weights: dict | None = None) -> StrategySpec:
    """Jitter around the current best, or random when the board is empty."""
    if not leaderboard:
        return random_spec(desk, rng, family_weights)
    parent = leaderboard[0]
    return mutate(parent, rng, temperature=0.4)


def propose(desk: str, population: list[StrategySpec], rng: random.Random,
            family_weights: dict | None = None) -> tuple[StrategySpec, str, StrategySpec | None]:
    """Pick an operator by weighted draw; returns (spec, origin, parent). The
    parent is the population spec this proposal was derived from (None for fresh
    random draws), so lineage can be recorded. family_weights (meta-learning
    forward-survival prior) biases which family a fresh proposal explores;
    mutation/crossover stay anchored to the existing population."""
    r = rng.random()
    if r < 0.25 or len(population) < 2:
        return random_spec(desk, rng, family_weights), "random", None
    if r < 0.70:
        parent = _weighted_choice(population, rng)
        return mutate(parent, rng), "mutation", parent
    if r < 0.85:
        a, b = rng.sample(population[:8], 2) if len(population) >= 2 else (population[0], population[0])
        return crossover(a, b, rng), "crossover", a   # offspring anchors to fitter parent a
    parent = population[0] if population else None     # heuristic jitters the leader
    return heuristic_proposal(population, desk, rng, family_weights), "heuristic", parent


def _weighted_choice(population: list[StrategySpec], rng: random.Random) -> StrategySpec:
    """Fitness-weighted by rank (population assumed sorted best-first)."""
    n = len(population)
    weights = [n - i for i in range(n)]
    return rng.choices(population, weights=weights, k=1)[0]
