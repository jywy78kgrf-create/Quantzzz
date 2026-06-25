"""Shadow book: eligibility, committee fallback, and forward marking."""

from __future__ import annotations

from types import SimpleNamespace


from quantzzz.research import shadow as SH

EXT = frozenset({"event_anchored", "options_iv_runup", "insider_conviction"})


def _ev(sharpe=2.5, dsr=0.75, boot=0.8):
    return SimpleNamespace(oos_sharpe=sharpe, dsr_prob=dsr, bootstrap_q05=boot,
                           n_trades=60, window_sharpes=[1.0, 2.0, 1.5])


def test_eligible_only_for_strict_gate_blockers():
    assert SH.eligible(_ev(), ["dsr_prob 0.75 < 0.9 (noise floor)"],
                       "event_anchored", EXT)
    # any other failing gate disqualifies
    assert not SH.eligible(_ev(), ["dsr_prob 0.75 < 0.9", "n_trades 12 < 30"],
                           "event_anchored", EXT)
    # weak evidence disqualifies even when DSR is the only blocker
    assert not SH.eligible(_ev(sharpe=1.0), ["dsr_prob 0.75 < 0.9"],
                           "event_anchored", EXT)
    assert not SH.eligible(_ev(dsr=0.4), ["dsr_prob 0.4 < 0.9"],
                           "event_anchored", EXT)
    # non-external families never shadow
    assert not SH.eligible(_ev(), ["dsr_prob 0.75 < 0.9"], "momentum", EXT)


def _cand(sid, basis, dsr):
    return {"strategy_id": sid, "family": basis.split(":")[0],
            "params": {}, "basis": basis, "oos_sharpe": 3.0, "dsr_prob": dsr,
            "bootstrap_q05": 1.0, "n_trades": 60, "window_sharpes": [1, 2, 3]}


def test_fallback_picks_best_per_unoccupied_basis():
    cands = [_cand(1, "event_anchored:iv_atm_30d", 0.70),
             _cand(2, "event_anchored:iv_atm_30d", 0.80),   # better twin
             _cand(3, "event_anchored:total_open_interest", 0.65),
             _cand(4, "insider_conviction:", 0.62)]
    picks = SH.choose_registrations(cands, active_keys=set(), slots=2, llm=None)
    assert [p["strategy_id"] for p in picks] == [2, 3]      # one per basis, by DSR
    # occupied basis is skipped entirely
    picks = SH.choose_registrations(cands, {"event_anchored:iv_atm_30d"}, 2, None)
    assert {p["strategy_id"] for p in picks} == {3, 4}


def test_llm_committee_picks_validated_against_basis_rule():
    class Committee:
        available = True
        def select_shadows(self, candidates, slots):
            return [{"strategy_id": 1, "rationale": "iv basis, robust"},
                    {"strategy_id": 2, "rationale": "duplicate basis sneak"}]
    cands = [_cand(1, "event_anchored:iv_atm_30d", 0.70),
             _cand(2, "event_anchored:iv_atm_30d", 0.80),
             _cand(3, "insider_conviction:", 0.62)]
    picks = SH.choose_registrations(cands, set(), 2, llm=Committee())
    # NOTE: per-basis pre-filter keeps only the better twin (#2); #1 is gone,
    # so the committee's valid pick is #2's dossier... it asked for #1 which
    # was collapsed away — only #2 survives validation, once.
    assert len(picks) == 1 and picks[0]["strategy_id"] == 2
    assert "rationale" in picks[0]
