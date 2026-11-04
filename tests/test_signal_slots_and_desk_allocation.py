"""
Quant Edge V16: Signal Slots & Desk Allocation Unit & Regression Suite
Tests master desk slot allocation, dynamic regime modulation, and quality admission gates.
"""

import unittest
import os
import shutil
from unittest.mock import MagicMock
from app.engine.execution.paper_trading_bot import PaperTradingBot
from app.quant_v16.backtest import InstitutionalBacktestEngine


class TestSignalSlotsAndDeskAllocation(unittest.TestCase):
    def setUp(self):
        self.test_export_dir = os.path.abspath("./scratch/test_slots_dir")
        os.makedirs(self.test_export_dir, exist_ok=True)
        self.test_ledger = os.path.join(self.test_export_dir, "test_ledger.json")
        self.bot = PaperTradingBot(ledger_file=self.test_ledger)
        # Clear any open positions
        self.bot.data["open_positions"] = []

    def tearDown(self):
        if os.path.exists(self.test_export_dir):
            shutil.rmtree(self.test_export_dir, ignore_errors=True)

    def test_01_master_desk_slots_and_margin_alignment(self):
        """Verifies that all desks match the master 6-slot $1,000 portfolio allocation."""
        desks = self.bot.data["desks"]

        # Scalp Desk: 1 slot, $150, 2x leverage
        self.assertEqual(desks["scalp"]["max_slots"], 1)
        self.assertEqual(desks["scalp"]["allocated_usd"], 150.0)
        self.assertEqual(desks["scalp"]["leverage"], 2)

        # Day Desk: 2 slots, $350, 3x leverage
        self.assertEqual(desks["day"]["max_slots"], 2)
        self.assertEqual(desks["day"]["allocated_usd"], 350.0)
        self.assertEqual(desks["day"]["leverage"], 3)

        # Swing Desk: 3 slots, $500, 2x leverage
        self.assertEqual(desks["swing"]["max_slots"], 3)
        self.assertEqual(desks["swing"]["allocated_usd"], 500.0)
        self.assertEqual(desks["swing"]["leverage"], 2)

        # Total capital parity
        total_alloc = (
            desks["scalp"]["allocated_usd"]
            + desks["day"]["allocated_usd"]
            + desks["swing"]["allocated_usd"]
        )
        self.assertEqual(total_alloc, 1000.0)

        # Verify Backtest engine alignment
        bt = InstitutionalBacktestEngine(initial_capital=1000.0)
        s_desk, s_alloc, s_slots, s_lev, _ = bt._resolve_desk("15M")
        self.assertEqual(s_slots, 1)
        self.assertEqual(s_alloc, 0.15)
        self.assertEqual(s_lev, 2)

        d_desk, d_alloc, d_slots, d_lev, _ = bt._resolve_desk("1H")
        self.assertEqual(d_slots, 2)
        self.assertEqual(d_alloc, 0.35)
        self.assertEqual(d_lev, 3)

        sw_desk, sw_alloc, sw_slots, sw_lev, _ = bt._resolve_desk("24H")
        self.assertEqual(sw_slots, 3)
        self.assertEqual(sw_alloc, 0.50)
        self.assertEqual(sw_lev, 2)

    def test_02_scalp_desk_grade_aplus_and_ev_hurdle(self):
        """Verifies that Scalp desk strictly admits Grade A+ with EVnet >= 1.25% only."""
        normal_btc = {"is_ntz_active": False, "regime": "BULL_TREND", "status_code": "NORMAL"}

        # Grade B scalp trade -> REJECTED
        sig_b = {
            "signal_id": "TEST_SCALP_B",
            "symbol": "BTC/USDT",
            "horizon": "15M",
            "direction": "LONG",
            "quality_grade": "Grade B",
            "ev_net": 0.40,
            "entry_price": 60000.0,
            "tp1_price": 61500.0,
            "sl_price": 59300.0
        }
        self.assertFalse(self.bot.admit_signal(sig_b, btc_shield_state=normal_btc))

        # Grade A scalp trade with EVnet < 1.25% -> REJECTED
        sig_a = {
            "signal_id": "TEST_SCALP_A",
            "symbol": "BTC/USDT",
            "horizon": "15M",
            "direction": "LONG",
            "quality_grade": "Grade A",
            "ev_net": 0.95,
            "entry_price": 60000.0,
            "tp1_price": 61500.0,
            "sl_price": 59300.0
        }
        self.assertFalse(self.bot.admit_signal(sig_a, btc_shield_state=normal_btc))

        # Grade A+ scalp trade with EVnet >= 1.25% -> ACCEPTED
        sig_aplus = {
            "signal_id": "TEST_SCALP_A_PLUS",
            "symbol": "BTC/USDT",
            "horizon": "15M",
            "direction": "LONG",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "quality_grade": "Grade A+",
            "ev_net": 1.45,
            "entry_price": 60000.0,
            "tp1_price": 62000.0,
            "sl_price": 59000.0
        }
        self.assertTrue(self.bot.admit_signal(sig_aplus, btc_shield_state=normal_btc))

        # Slot cap: Second scalp trade -> REJECTED (max 1 slot)
        sig_aplus_2 = {
            "signal_id": "TEST_SCALP_A_PLUS_2",
            "symbol": "ETH/USDT",
            "horizon": "15M",
            "direction": "LONG",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "quality_grade": "Grade A+",
            "ev_net": 1.50,
            "entry_price": 3000.0,
            "tp1_price": 3100.0,
            "sl_price": 2950.0
        }
        self.assertFalse(self.bot.admit_signal(sig_aplus_2, btc_shield_state=normal_btc))

    def test_03_dynamic_regime_slot_throttling(self):
        """Verifies that Choppy/Range regime throttles Scalp slots to 0."""
        choppy_btc = {"is_ntz_active": False, "regime": "RANGE", "status_code": "NORMAL"}

        sig_scalp = {
            "signal_id": "TEST_SCALP_CHOP",
            "symbol": "BTC/USDT",
            "horizon": "15M",
            "direction": "LONG",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "quality_grade": "Grade A+",
            "ev_net": 1.85,
            "entry_price": 60000.0,
            "tp1_price": 62000.0,
            "sl_price": 59000.0
        }
        # Even with Grade A+ and high EVnet, Scalp must be throttled to 0 slots in RANGE
        admitted = self.bot.admit_signal(sig_scalp, btc_shield_state=choppy_btc)
        self.assertFalse(admitted, "Scalp slots must be throttled to 0 during RANGE regime")

    def test_04_swing_desk_three_slot_capacity(self):
        """Verifies Swing desk accommodates up to 3 concurrent trades."""
        trend_btc = {"is_ntz_active": False, "regime": "BULL_TREND", "status_code": "NORMAL"}

        # Trade 1: BTC
        sig_sw1 = {
            "signal_id": "SWING_BTC", "symbol": "BTC/USDT", "horizon": "24H", "direction": "LONG",
            "is_trade_active": True, "signal_status": "ACTIVE_SIGNAL",
            "quality_grade": "Grade A+", "ev_net": 1.20, "entry_price": 60000.0, "tp1_price": 65000.0, "sl_price": 57500.0
        }
        self.assertTrue(self.bot.admit_signal(sig_sw1, btc_shield_state=trend_btc))

        # Trade 2: ETH
        sig_sw2 = {
            "signal_id": "SWING_ETH", "symbol": "ETH/USDT", "horizon": "24H", "direction": "LONG",
            "is_trade_active": True, "signal_status": "ACTIVE_SIGNAL",
            "quality_grade": "Grade A", "ev_net": 0.85, "entry_price": 3000.0, "tp1_price": 3300.0, "sl_price": 2850.0
        }
        self.assertTrue(self.bot.admit_signal(sig_sw2, btc_shield_state=trend_btc))

        # Trade 3: SOL
        sig_sw3 = {
            "signal_id": "SWING_SOL", "symbol": "SOL/USDT", "horizon": "24H", "direction": "LONG",
            "is_trade_active": True, "signal_status": "ACTIVE_SIGNAL",
            "quality_grade": "Grade A+", "ev_net": 1.60, "entry_price": 150.0, "tp1_price": 170.0, "sl_price": 140.0
        }
        self.assertTrue(self.bot.admit_signal(sig_sw3, btc_shield_state=trend_btc))

        # Trade 4: BNB -> REJECTED (max 3 slots reached)
        sig_sw4 = {
            "signal_id": "SWING_BNB", "symbol": "BNB/USDT", "horizon": "24H", "direction": "LONG",
            "is_trade_active": True, "signal_status": "ACTIVE_SIGNAL",
            "quality_grade": "Grade A+", "ev_net": 1.40, "entry_price": 550.0, "tp1_price": 600.0, "sl_price": 525.0
        }
        self.assertFalse(self.bot.admit_signal(sig_sw4, btc_shield_state=trend_btc))


if __name__ == "__main__":
    unittest.main()
