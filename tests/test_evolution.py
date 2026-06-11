import random

from quantzzz.research import evolution
from quantzzz.research.strategies import families_for, space_for


def test_random_spec_in_bounds():
    rng = random.Random(0)
    for _ in range(50):
        spec = evolution.random_spec("equity", rng)
        space = space_for(spec.family)
        for p in space.params:
            v = spec.params[p.name]
            if p.kind == "choice":
                assert v in p.choices
            else:
                assert p.low <= v <= p.high


def test_mutation_stays_in_bounds():
    rng = random.Random(1)
    spec = evolution.random_spec("biotech", rng)
    for _ in range(50):
        child = evolution.mutate(spec, rng, temperature=2.0)
        space = space_for(child.family)
        for p in space.params:
            v = child.params[p.name]
            if p.kind != "choice":
                assert p.low <= v <= p.high


def test_crossover_same_family_mixes_params():
    rng = random.Random(2)
    fam = families_for("equity")[0]
    space = space_for(fam)
    from quantzzz.research.strategy_space import StrategySpec
    a = StrategySpec(fam, "equity", space.random_params(random.Random(3)))
    b = StrategySpec(fam, "equity", space.random_params(random.Random(4)))
    child = evolution.crossover(a, b, rng)
    assert child.family == fam
    for p in space.params:
        assert child.params[p.name] in (a.params[p.name], b.params[p.name])


def test_spec_hash_stable_and_distinct():
    rng = random.Random(5)
    s1 = evolution.random_spec("equity", rng)
    s2 = evolution.random_spec("equity", rng)
    assert s1.spec_hash() == s1.spec_hash()
    assert s1.spec_hash() != s2.spec_hash()


def test_propose_returns_origin():
    rng = random.Random(6)
    spec, origin = evolution.propose("equity", [], rng)
    assert origin == "random"
