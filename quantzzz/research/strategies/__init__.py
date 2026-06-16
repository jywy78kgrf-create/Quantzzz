"""Strategy registry mapping family name -> (ParamSpace, signal_fn).

A signal_fn takes (FeatureBundle, params) and returns a DataFrame of target
weights (dates x tickers) that sums to <= 1 in gross terms per row.
"""

from __future__ import annotations

from ..strategy_space import ParamSpace
from . import biotech, equity

# family -> (ParamSpace, signal_fn)
REGISTRY: dict[str, tuple[ParamSpace, callable]] = {}


def _register(module):
    for space, fn in module.STRATEGIES:
        REGISTRY[space.family] = (space, fn)


_register(equity)
_register(biotech)


# sub-desks that reuse another desk's family registry (their own universe / risk
# / book, but the same signal families to search).
_FAMILY_ALIAS = {"biotech_smallcap": "biotech"}


def families_for(desk: str) -> list[str]:
    d = _FAMILY_ALIAS.get(desk, desk)
    return [name for name, (space, _) in REGISTRY.items() if space.desk == d]


def space_for(family: str) -> ParamSpace:
    return REGISTRY[family][0]


def signal_fn_for(family: str):
    return REGISTRY[family][1]
