import unittest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.signal import SignalAudit

class TestV16RealizedReturnParity(unittest.TestCase):
    def test_expired_signal_unfilled_limit_returns_zero_pct(self):
        """Quant Edge Rule 1 & 9: Unfilled expired resting limit order must serialize with exact realized return +0.00%."""
        sig = SignalAudit(
            id=1,
            signal_id="NIL_USDT_1H_1793101263",
            symbol="NIL/USDT",
            horizon="1H",
            direction="LONG",
            entry_price=0.08898,
            sl_price=0.082424,
            tp1_price=0.13006,
            status="EXPIRED_HORIZON",
            outcome_label="⏱️ EXPIRED",
            exit_price=None,
            realized_return_pct=None,
        )
        d = sig.to_dict()
        self.assertEqual(d["outcome"], "EXPIRED")
        self.assertEqual(d["realized_return_pct"], "+0.00%")
        self.assertEqual(d["realized_return_num"], 0.0)
        self.assertEqual(d["exit_price"], 0.08898)
        self.assertEqual(d["pnl_pct"], 0.0)

    def test_resolved_signal_with_exit_price_calculates_realized_return_dynamically(self):
        """Quant Edge Rule 6 & 8: If realized_return_pct was NULL in DB but exit_price exists on resolved trade, compute exact return."""
        # Long loss: entry 100, exit 95 -> -5.00%
        sig_long_loss = SignalAudit(
            id=2,
            signal_id="TEST_LONG_LOSS",
            symbol="BTC/USDT",
            horizon="1H",
            direction="LONG",
            entry_price=100.0,
            exit_price=95.0,
            status="LOST_SL",
            outcome_label="🔴 LOST (SL HIT)",
            realized_return_pct=None,
        )
        d_long = sig_long_loss.to_dict()
        self.assertEqual(d_long["outcome"], "LOST")
        self.assertEqual(d_long["realized_return_pct"], "-5.00%")
        self.assertEqual(d_long["realized_return_num"], -5.0)
        self.assertEqual(d_long["exit_price"], 95.0)

        # Short win: entry 100, exit 90 -> +10.00%
        sig_short_win = SignalAudit(
            id=3,
            signal_id="TEST_SHORT_WIN",
            symbol="ETH/USDT",
            horizon="1H",
            direction="SHORT",
            entry_price=100.0,
            exit_price=90.0,
            status="WON_TP1",
            outcome_label="🟢 WON (TP1 HIT)",
            realized_return_pct=None,
        )
        d_short = sig_short_win.to_dict()
        self.assertEqual(d_short["outcome"], "WON")
        self.assertEqual(d_short["realized_return_pct"], "+10.00%")
        self.assertEqual(d_short["realized_return_num"], 10.0)
        self.assertEqual(d_short["exit_price"], 90.0)

    def test_active_pending_signal_preserves_evaluating_state(self):
        """Active trades in progress must remain PENDING with empty realized return string for live ticker evaluation."""
        sig_active = SignalAudit(
            id=4,
            signal_id="TEST_ACTIVE",
            symbol="SOL/USDT",
            horizon="1H",
            direction="LONG",
            entry_price=150.0,
            exit_price=None,
            status="ACTIVE",
            outcome_label="RUNNING 🚀",
            realized_return_pct=None,
        )
        d_active = sig_active.to_dict()
        self.assertEqual(d_active["outcome"], "PENDING")
        self.assertEqual(d_active["realized_return_pct"], "")
        self.assertIsNone(d_active["realized_return_num"])

if __name__ == "__main__":
    unittest.main()
