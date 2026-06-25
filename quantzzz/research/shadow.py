"""Shadow book curation: pre-registered forward trials for benched near-misses.

A candidate that fails ONLY the strict contaminated-discovery gate (deflated
Sharpe below 0.90 while everything else passes) is eligible for a shadow slot:
its exact parameters are frozen on a date and its forward paper NAV is tracked
without committing capital. After the registration date, its record is free of
both contaminations (the discovery scan never saw the future; forward data has
no survivorship bias) and free of selection bias (the spec is pinned, not
re-picked each cycle).

Discipline that keeps the experiment honest:

* Few slots (MAX_ACTIVE), so a good forward record can't be cherry-picked from
  a crowd of shadows.
* One slot per signal basis (family + rank signal) — slots stay decorrelated.
* Pinned: a registered shadow is never swapped for a backtest-better cousin;
  it graduates (its strategy promotes), bleeds out (auto-deregistered), or
  keeps earning evidence.
* WHO gets the slots is a judgement call, so the LLM advisor acts as the
  selection committee when available (its rationale is journaled); otherwise a
  deterministic rule (best deflated Sharpe per basis) decides.
"""

from __future__ import annotations

from ..config import PROMOTION_THRESHOLDS, PROMOTION_THRESHOLDS_EXTERNAL

MAX_ACTIVE = 5
DEREGISTER_AFTER_DAYS = 60      # minimum forward sample before judging failure
DEREGISTER_BELOW_NAV = 0.85     # -15% forward = the gate was right; record it


def eligible(ev, reasons: list[str], family: str, external_families) -> bool:
    """Blocked solely by the strict deflated-Sharpe bar, strong everywhere else."""
    if family not in external_families or not reasons:
        return False
    if not all(r.strip().startswith("dsr_prob") for r in reasons):
        return False
    strict = PROMOTION_THRESHOLDS_EXTERNAL
    standard = PROMOTION_THRESHOLDS["biotech"]
    return (ev.oos_sharpe >= strict.min_oos_sharpe
            and (ev.dsr_prob or 0) >= standard.min_dsr_prob
            and (ev.bootstrap_q05 or 0) >= strict.min_bootstrap_q05)


def basis_key(family: str, params: dict) -> str:
    """The signal basis a slot occupies — keeps shadows decorrelated."""
    return f"{family}:{params.get('rank_signal', '')}"


def choose_registrations(candidates: list[dict], active_keys: set[str],
                         slots: int, llm=None) -> list[dict]:
    """Pick which eligible near-misses get the open shadow slots.

    ``candidates``: dossiers with strategy_id, family, params, basis, and the
    evaluation metrics. The advisor (when available) selects and explains;
    its picks are validated against the dossier set and the basis rule. The
    fallback — and the validator's tie-breaker — is best deflated Sharpe per
    unoccupied basis.
    """
    if slots <= 0 or not candidates:
        return []
    # best candidate per unoccupied basis, strongest DSR first
    per_basis: dict[str, dict] = {}
    for c in candidates:
        if c["basis"] in active_keys:
            continue
        cur = per_basis.get(c["basis"])
        if cur is None or (c["dsr_prob"] or 0) > (cur["dsr_prob"] or 0):
            per_basis[c["basis"]] = c
    pool = sorted(per_basis.values(), key=lambda c: -(c["dsr_prob"] or 0))
    if not pool:
        return []

    picks: list[dict] = []
    if llm is not None and getattr(llm, "available", False):
        try:
            chosen = llm.select_shadows(
                [{k: c[k] for k in ("strategy_id", "family", "params", "basis",
                                    "oos_sharpe", "dsr_prob", "bootstrap_q05",
                                    "n_trades", "window_sharpes")} for c in pool],
                slots)
        except Exception:
            chosen = None
        if chosen:
            by_id = {c["strategy_id"]: c for c in pool}
            seen_bases: set[str] = set()
            for item in chosen:
                c = by_id.get(item.get("strategy_id"))
                if c is None or c["basis"] in seen_bases:
                    continue
                seen_bases.add(c["basis"])
                c = dict(c)
                c["rationale"] = (item.get("rationale") or "advisor selection")[:300]
                picks.append(c)
                if len(picks) >= slots:
                    break
    if not picks:                       # NullAdvisor, API failure, or empty picks
        for c in pool[:slots]:
            c = dict(c)
            c["rationale"] = "highest deflated Sharpe on an unoccupied signal basis"
            picks.append(c)
    return picks
