"""
QUANT EDGE V16: Automated Regression Test for TP1 Hit vs Breakeven Isolation
Verifies that:
1. Breakeven Lock (Tier 0 / Risk Guard) does NOT falsely mark TP1 as Secured / Hit.
2. Price geometry invariants: TP1 is only hit when trough <= tp1 (SHORT) or peak >= tp1 (LONG).
3. The store healing pass cleanses false TP1 locks while preserving BE locks.
"""

import unittest
import os
import json
import tempfile
from fastapi.testclient import TestClient

from app.main import app
from app.routers.v16_router import _get_v16_store
from app.config import settings

class TestTP1BreakevenIsolation(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_01_breakeven_locked_does_not_lock_tp1(self):
        """A paper trading position with is_breakeven_locked=True must NOT set is_tp1_locked=True."""
        # Simulated position matching the NIL/USDT live scenario
        mock_position = {
            "trade_id": "NIL_USDT_15M_1794508666",
            "symbol": "NIL/USDT",
            "direction": "SHORT",
            "horizon": "15M",
            "entry_price": 0.05592,
            "current_price": 0.05524,
            "tp1_price": 0.054458,
            "tp2_price": 0.053907,
            "tp3_price": 0.053236,
            "sl_price": 0.055696,
            "initial_sl_price": 0.056591,
            "peak_price_seen": 0.05607,
            "trough_price_seen": 0.05503,  # 0.05503 > 0.054458 (DID NOT TOUCH TP1)
            "tp1_hit": False,
            "tp2_hit": False,
            "is_breakeven_locked": True,
            "peak_gain_pct": 1.59,
            "unrealized_pnl_pct": 1.21,
            "status": "OPEN",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            orig_export = settings.EXPORT_DIR
            try:
                settings.EXPORT_DIR = tmpdir
                ledger_path = os.path.join(tmpdir, "paper_trading_ledger.json")
                with open(ledger_path, "w") as f:
                    json.dump({"open_positions": [mock_position]}, f)

                immut, dyn = _get_v16_store()
                sid = "NIL_USDT_15M_1794508666"

                self.assertIn(sid, dyn, "Signal ID should be registered in dynamic states")
                d_state = dyn[sid]

                # Core assertions
                self.assertFalse(d_state.get("is_tp1_locked"), "is_tp1_locked MUST be False when TP1 was not touched")
                self.assertTrue(d_state.get("is_breakeven_locked"), "is_breakeven_locked MUST be True")
                self.assertEqual(d_state.get("locked_sl"), 0.055696, "locked_sl must reflect the breakeven SL")
                self.assertIsNotNone(d_state.get("trailing_sl"), "trailing_sl must be present when SL is trailed")
            finally:
                settings.EXPORT_DIR = orig_export

    def test_02_price_geometry_guard_prevents_false_tp1_short(self):
        """A SHORT signal where trough > tp1 MUST have is_tp1_locked=False even if dyn state had True."""
        sid = "SIG_BTC_SHORT_TP1_GUARD"
        mock_imm = {
            "signal_id": sid,
            "symbol": "BTC/USDT",
            "direction": "SHORT",
            "horizon": "15M",
            "entry_price_initial": 70000.0,
            "tp1_initial": 68000.0,
            "sl_initial": 71000.0,
            "p_tp1": 60.0,
            "status": "ACTIVE",
            "trough_price_seen": 68500.0,  # 68500 > 68000 (never reached TP1)
            "peak_price_seen": 70200.0,
        }
        # Pre-corrupted dynamic state claiming is_tp1_locked=True
        mock_dyn = {
            sid: {
                "signal_id": sid,
                "current_price": 68900.0,
                "current_sl": 69800.0,
                "trough_price_seen": 68500.0,
                "peak_price_seen": 70200.0,
                "mfe_pct": 2.14,
                "is_tp1_locked": True,  # FALSELY SET
                "status": "ACTIVE",
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            orig_export = settings.EXPORT_DIR
            try:
                settings.EXPORT_DIR = tmpdir
                with open(os.path.join(tmpdir, "v16_immutable_signals.json"), "w") as f:
                    json.dump({sid: mock_imm}, f)
                with open(os.path.join(tmpdir, "v16_dynamic_states.json"), "w") as f:
                    json.dump(mock_dyn, f)

                immut, dyn = _get_v16_store()
                self.assertFalse(dyn[sid]["is_tp1_locked"], "Store healing must clear false TP1 lock on SHORT")
            finally:
                settings.EXPORT_DIR = orig_export

    def test_03_price_geometry_guard_prevents_false_tp1_long(self):
        """A LONG signal where peak < tp1 MUST have is_tp1_locked=False even if dyn state had True."""
        sid = "SIG_ETH_LONG_TP1_GUARD"
        mock_imm = {
            "signal_id": sid,
            "symbol": "ETH/USDT",
            "direction": "LONG",
            "horizon": "15M",
            "entry_price_initial": 3000.0,
            "tp1_initial": 3150.0,
            "sl_initial": 2900.0,
            "p_tp1": 60.0,
            "status": "ACTIVE",
            "peak_price_seen": 3100.0,  # 3100 < 3150 (never reached TP1)
            "trough_price_seen": 2980.0,
        }
        mock_dyn = {
            sid: {
                "signal_id": sid,
                "current_price": 3080.0,
                "current_sl": 3010.0,
                "peak_price_seen": 3100.0,
                "trough_price_seen": 2980.0,
                "mfe_pct": 3.33,
                "is_tp1_locked": True,  # FALSELY SET
                "status": "ACTIVE",
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            orig_export = settings.EXPORT_DIR
            try:
                settings.EXPORT_DIR = tmpdir
                with open(os.path.join(tmpdir, "v16_immutable_signals.json"), "w") as f:
                    json.dump({sid: mock_imm}, f)
                with open(os.path.join(tmpdir, "v16_dynamic_states.json"), "w") as f:
                    json.dump(mock_dyn, f)

                immut, dyn = _get_v16_store()
                self.assertFalse(dyn[sid]["is_tp1_locked"], "Store healing must clear false TP1 lock on LONG")
            finally:
                settings.EXPORT_DIR = orig_export

    def test_04_genuine_tp1_hit_preserved(self):
        """When price genuinely touches TP1 (trough <= tp1 for SHORT), is_tp1_locked=True is preserved."""
        sid = "SIG_SOL_GENUINE_TP1"
        mock_imm = {
            "signal_id": sid,
            "symbol": "SOL/USDT",
            "direction": "SHORT",
            "horizon": "15M",
            "entry_price_initial": 150.0,
            "tp1_initial": 145.0,
            "sl_initial": 153.0,
            "p_tp1": 60.0,
            "status": "ACTIVE",
            "trough_price_seen": 144.5,  # 144.5 <= 145.0 (GENUINE TP1 HIT)
            "peak_price_seen": 150.2,
        }
        mock_dyn = {
            sid: {
                "signal_id": sid,
                "current_price": 145.5,
                "current_sl": 150.0,
                "trough_price_seen": 144.5,
                "peak_price_seen": 150.2,
                "mfe_pct": 3.67,
                "is_tp1_locked": True,
                "status": "TP1_LOCKED_BREAKEVEN",
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            orig_export = settings.EXPORT_DIR
            try:
                settings.EXPORT_DIR = tmpdir
                with open(os.path.join(tmpdir, "v16_immutable_signals.json"), "w") as f:
                    json.dump({sid: mock_imm}, f)
                with open(os.path.join(tmpdir, "v16_dynamic_states.json"), "w") as f:
                    json.dump(mock_dyn, f)

                immut, dyn = _get_v16_store()
                self.assertTrue(dyn[sid]["is_tp1_locked"], "Genuine TP1 hit must be preserved as True")
            finally:
                settings.EXPORT_DIR = orig_export

if __name__ == "__main__":
    unittest.main()
