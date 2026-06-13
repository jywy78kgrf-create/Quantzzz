"""Strategy capacity: how many dollars an edge can absorb before it eats itself.

Capacity = the portfolio size at which the strategy's largest position would
exceed a participation cap of the name's daily dollar liquidity. For weights
w_i and 63-day median dollar volume ADV_i:

    capacity = min over held names ( participation * ADV_i / w_i )

A 3+ Sharpe edge with $2M capacity is a real but small edge; knowing the
number is the difference between a finding and a fantasy.
"""

from __future__ import annotations

import pandas as pd

from ..data import features as F
from .strategies import signal_fn_for
from .strategy_space import StrategySpec


def strategy_capacity(bundle, family: str, params: dict,
                      participation: float = 0.025) -> float | None:
    """Deployable dollars at `participation` of ADV, from recent target weights."""
    if bundle.volume.empty:
        return None
    try:
        w = signal_fn_for(family)(bundle, params)
    except Exception:
        return None
    if w.empty:
        return None
    recent = w.tail(63)
    mean_w = recent[recent != 0].mean()              # avg weight when held
    adv = (bundle.prices * bundle.volume).rolling(63, min_periods=10).median().iloc[-1]
    worst = None
    for t, wi in mean_w.items():
        if wi is None or not wi == wi or wi < 0.005:
            continue
        a = adv.get(t)
        if a is None or not a == a or a <= 0:
            continue
        cap = participation * a / wi
        if worst is None or cap < worst:
            worst = cap
    return float(worst) if worst is not None else None


def promoted_capacities(conn, bundle, desk: str,
                        participation: float = 0.025) -> dict[int, float | None]:
    rows = conn.execute(
        "SELECT id, family, params_json FROM strategies "
        "WHERE desk=? AND status='promoted'", (desk,)).fetchall()
    out: dict[int, float | None] = {}
    for r in rows:
        spec = StrategySpec.from_row(r["family"], desk, r["params_json"])
        out[r["id"]] = strategy_capacity(bundle, spec.family, spec.params,
                                         participation)
    return out
