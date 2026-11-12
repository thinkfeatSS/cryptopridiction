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
        """Verifies that all desks match the master 10-slot $1,000 portfolio allocation."""
        desks = self.bot.data["desks"]

        # Scalp Desk: 5 slots, $500, 2x leverage (Scalp Mandate)
        self.assertEqual(desks["scalp"]["max_slots"], int(os.getenv("SCALP_DESK_MAX_SLOTS", "5")))
        self.assertEqual(desks["scalp"]["allocated_usd"], float(os.getenv("SCALP_DESK_ALLOCATED_USD", "500.0")))
        self.assertEqual(desks["scalp"]["leverage"], 2)

        # Day Desk: 2 slots, $200, 3x leverage
        self.assertEqual(desks["day"]["max_slots"], int(os.getenv("DAY_DESK_MAX_SLOTS", "2")))
        self.assertEqual(desks["day"]["allocated_usd"], float(os.getenv("DAY_DESK_ALLOCATED_USD", "200.0")))
        self.assertEqual(desks["day"]["leverage"], 3)

        # Swing Desk: 3 slots, $300, 2x leverage
        self.assertEqual(desks["swing"]["max_slots"], int(os.getenv("SWING_DESK_MAX_SLOTS", "3")))
        self.assertEqual(desks["swing"]["allocated_usd"], float(os.getenv("SWING_DESK_ALLOCATED_USD", "300.0")))
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
        self.assertEqual(s_slots, int(os.getenv("SCALP_DESK_MAX_SLOTS", "5")))
        self.assertEqual(s_alloc, 0.50)
        self.assertEqual(s_lev, 2)

        d_desk, d_alloc, d_slots, d_lev, _ = bt._resolve_desk("1H")
        self.assertEqual(d_slots, int(os.getenv("DAY_DESK_MAX_SLOTS", "2")))
        self.assertEqual(d_alloc, 0.20)
        self.assertEqual(d_lev, 3)

        sw_desk, sw_alloc, sw_slots, sw_lev, _ = bt._resolve_desk("24H")
        self.assertEqual(sw_slots, int(os.getenv("SWING_DESK_MAX_SLOTS", "3")))
        self.assertEqual(sw_alloc, 0.30)
        self.assertEqual(sw_lev, 2)

    def test_02_scalp_desk_grade_aplus_and_ev_hurdle(self):
        """Verifies that Scalp desk strictly admits up to 5 concurrent scalp slots and enforces EVnet hurdle."""
        normal_btc = {"is_ntz_active": False, "regime": "BULL_TREND", "status_code": "NORMAL"}

        # Grade C scalp trade -> REJECTED
        sig_c = {
            "signal_id": "TEST_SCALP_C",
            "symbol": "BTC/USDT",
            "horizon": "15M",
            "direction": "LONG",
            "quality_grade": "Grade C",
            "ev_net": 0.40,
            "entry_price": 60000.0,
            "tp1_price": 61500.0,
            "sl_price": 59300.0
        }
        self.assertFalse(self.bot.admit_signal(sig_c, btc_shield_state=normal_btc))

        # Trade with EVnet < 0.25% -> REJECTED
        sig_low_ev = {
            "signal_id": "TEST_SCALP_LOW_EV",
            "symbol": "BTC/USDT",
            "horizon": "15M",
            "direction": "LONG",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "quality_grade": "Grade A",
            "ev_net": 0.10,
            "entry_price": 60000.0,
            "tp1_price": 60050.0,
            "sl_price": 59900.0
        }
        self.assertFalse(self.bot.admit_signal(sig_low_ev, btc_shield_state=normal_btc))

        # 5 Scalp Trades with EVnet >= 0.25% -> ALL ACCEPTED up to 5 slots
        symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT", "LINK/USDT"]
        for idx, sym in enumerate(symbols, start=1):
            sig = {
                "signal_id": f"TEST_SCALP_SLOT_{idx}",
                "symbol": sym,
                "horizon": "15M",
                "direction": "LONG",
                "is_trade_active": True,
                "signal_status": "ACTIVE_SIGNAL",
                "quality_grade": "Grade A+",
                "ev_net": 1.45,
                "entry_price": 100.0 * idx,
                "tp1_price": 105.0 * idx,
                "sl_price": 97.0 * idx
            }
            self.assertTrue(self.bot.admit_signal(sig, btc_shield_state=normal_btc), f"Slot {idx} should be admitted")

        # Slot cap: 6th scalp trade -> REJECTED (max 5 slots reached)
        sig_overflow = {
            "signal_id": "TEST_SCALP_OVERFLOW",
            "symbol": "NEAR/USDT",
            "horizon": "15M",
            "direction": "LONG",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "quality_grade": "Grade A+",
            "ev_net": 1.50,
            "entry_price": 5.0,
            "tp1_price": 5.5,
            "sl_price": 4.7
        }
        self.assertFalse(self.bot.admit_signal(sig_overflow, btc_shield_state=normal_btc))

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

    def test_05_btc_shield_beta_directional_veto_and_chop_gate(self):
        """Verifies that BTC Shield Beta Veto blocks counter-trend trades and chop congestion."""
        # Scenario A: Bear Trend disallows Longs
        bear_btc = {
            "is_ntz_active": False,
            "regime": "BEAR_TREND",
            "v16_regime": "BEAR_TREND",
            "status_code": "NORMAL",
            "altcoin_longs_allowed": False,
            "altcoin_shorts_allowed": True,
            "chop_index": 45.0
        }
        sig_long = {
            "signal_id": "TEST_BEAR_LONG", "symbol": "SOL/USDT", "horizon": "1H", "direction": "LONG",
            "is_trade_active": True, "signal_status": "ACTIVE_SIGNAL",
            "quality_grade": "Grade A+", "ev_net": 1.50, "entry_price": 150.0, "tp1_price": 160.0, "sl_price": 145.0
        }
        self.assertFalse(self.bot.admit_signal(sig_long, btc_shield_state=bear_btc), "Longs must be strictly blocked in BEAR_TREND")

        sig_short = {
            "signal_id": "TEST_BEAR_SHORT", "symbol": "SOL/USDT", "horizon": "1H", "direction": "SHORT",
            "is_trade_active": True, "signal_status": "ACTIVE_SIGNAL",
            "quality_grade": "Grade A+", "ev_net": 1.50, "entry_price": 150.0, "tp1_price": 140.0, "sl_price": 155.0
        }
        self.assertTrue(self.bot.admit_signal(sig_short, btc_shield_state=bear_btc), "Shorts must be admitted in BEAR_TREND")

        # Scenario B: Bull Trend disallows Shorts
        bull_btc = {
            "is_ntz_active": False,
            "regime": "BULL_TREND",
            "v16_regime": "BULL_TREND",
            "status_code": "NORMAL",
            "altcoin_longs_allowed": True,
            "altcoin_shorts_allowed": False,
            "chop_index": 42.0
        }
        self.bot.data["open_positions"] = []
        self.assertFalse(self.bot.admit_signal(sig_short, btc_shield_state=bull_btc), "Shorts must be strictly blocked in BULL_TREND")

        # Scenario C: Chop Index > 61.8 blocks all entries
        chop_btc = {
            "is_ntz_active": False,
            "regime": "RANGE",
            "status_code": "NORMAL",
            "altcoin_longs_allowed": True,
            "altcoin_shorts_allowed": True,
            "chop_index": 64.5
        }
        self.assertFalse(self.bot.admit_signal(sig_short, btc_shield_state=chop_btc), "Chop > 61.8 must block trade entry")


if __name__ == "__main__":
    unittest.main()
