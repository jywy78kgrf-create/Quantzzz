"""The liquidation halt must be a real circuit breaker: it persists for a
cooldown (not an instant self-clear), then books the loss and recovers (not a
permanent trap)."""

import pytest

from quantzzz.config import RISK_LIMITS
from quantzzz.db import insert
from quantzzz.trading.broker import Account
from quantzzz.trading.trader import TraderAgent


class _RiskStub:
    LIQUIDATE_COOLDOWN_DAYS = TraderAgent.LIQUIDATE_COOLDOWN_DAYS
    _update_risk_mode = TraderAgent._update_risk_mode
    _halt_cooldown_elapsed = TraderAgent._halt_cooldown_elapsed
    _reset_hwm_to_equity = TraderAgent._reset_hwm_to_equity
    _set_mode = TraderAgent._set_mode

    def __init__(self, conn, equity, now):
        self.conn = conn
        self.fund = "biotech"
        self.limits = RISK_LIMITS["biotech"]
        self._now = now
        self._eq = equity

        class _J:
            def record(self, *a, **k):
                pass

        self.journal = _J()
        outer = self

        class _B:
            def get_account(self):
                return Account("biotech", outer._eq, outer._eq)

        self.broker = _B()

    def _ts(self):
        return self._now


def test_liquidate_only_persists_then_recovers_on_cooldown(tmp_db):
    insert(tmp_db, "fund_state", fund="biotech", mode="liquidate_only",
           hwm=2_000_000, halted_since="2026-06-14T00:00:00Z")

    # 1 day after the halt (< 3-day cooldown): the halt PERSISTS, hwm not reset
    s = _RiskStub(tmp_db, equity=1_000_000, now="2026-06-15T00:00:00Z")
    assert s._update_risk_mode("liquidate_only", -0.5) == "liquidate_only"
    assert tmp_db.execute("SELECT hwm FROM fund_state WHERE fund='biotech'"
                          ).fetchone()["hwm"] == pytest.approx(2_000_000)

    # 4 days after (>= cooldown): recover to normal, booking the loss (hwm -> equity)
    s2 = _RiskStub(tmp_db, equity=1_000_000, now="2026-06-18T00:00:00Z")
    assert s2._update_risk_mode("liquidate_only", -0.5) == "normal"
    assert tmp_db.execute("SELECT hwm FROM fund_state WHERE fund='biotech'"
                          ).fetchone()["hwm"] == pytest.approx(1_000_000)
