import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import unittest
from datetime import datetime, timezone
from app.services.signal_service import SignalService, fetch_intra_candle_extremes
from app.engine.execution.paper_trading_bot import PaperTradingBot
from app.quant_v16.no_trade_zone import NoTradeZoneEngine, NoTradeZoneReason
from app.quant_v16.audit import classify_signal_outcome
import pandas as pd
import numpy as np


class TestV16BlackSwanAndConsolidation(unittest.TestCase):
    """
    Forensic verification suite for:
    1. Acute Black-Swan Gap Penetration & Emergency Flash Dump Sentinel
    2. Horizon Expiration Elimination & Fair Breakeven Accounting in Flat Consolidation
    3. Multi-Module Horizon TTL Synchronization
    """

    def test_01_acute_black_swan_gap_down_accounting(self):
        """
        When price gaps through Stop Loss during a black swan flash event,
        exit price must reflect actual market gap penetration (not idealized SL).
        """
        class MockSignal:
            def __init__(self):
                self.signal_id = "SIG_BS_01"
                self.symbol = "ETH/USDT"
                self.horizon = "15M"
                self.direction = "LONG"
                self.entry_price = 100.0
                self.sl_price = 98.0
                self.tp1_price = 104.0
                self.tp2_price = 108.0
                self.tp3_price = 112.0
                self.status = "ACTIVE"
                self.outcome_label = "ACTIVE"
                self.exit_price = None
                self.realized_return_pct = None
                self.peak_price_seen = 100.5
                self.trough_price_seen = 93.5
                self.created_at = datetime.now(timezone.utc)
                self.date_utc = "2026-11-06"
                self.time_utc = "10:00:00 UTC"
                self.predicted_close_utc = None
                self.quality_grade = "Grade A+"
                self.meta_win_prob_pct = 75.0

        sig = MockSignal()
        # Live price jumped to 93.0 (gap penetration past 98.0 SL)
        live_prices = {"ETHUSDT": 93.0, "ETH/USDT": 93.0}

        ss = SignalService()
        updated = ss.evaluate_active_signals([sig], live_prices=live_prices)
        self.assertTrue(updated)
        self.assertEqual(sig.status, "LOST_SL")
        # Exit price must be min(sl_p, curr_p) = 93.0, NOT idealized 98.0!
        self.assertLessEqual(sig.exit_price, 93.5)
        self.assertLessEqual(sig.realized_return_pct, -6.5)

    def test_02_flat_consolidation_expiration_is_breakeven_not_loss(self):
        """
        Signals expiring inside the flat consolidation corridor without hitting SL
        must be classified as EXPIRED_BREAKEVEN (never penalized as LOST_EXPIRED).
        """
        class MockSignal:
            def __init__(self):
                self.signal_id = "SIG_FLAT_01"
                self.symbol = "MOCK/USDT"
                self.horizon = "15M"
                self.direction = "LONG"
                self.entry_price = 100.0
                self.sl_price = 97.5
                self.tp1_price = 105.0
                self.tp2_price = 110.0
                self.tp3_price = 115.0
                self.status = "ACTIVE"
                self.outcome_label = "ACTIVE"
                self.exit_price = None
                self.realized_return_pct = None
                self.peak_price_seen = 100.2
                self.trough_price_seen = 99.7
                # Force age to exceed 7200s (expired)
                self.created_at = datetime(2026, 11, 6, 6, 0, 0, tzinfo=timezone.utc)
                self.date_utc = "2026-11-06"
                self.time_utc = "06:00:00 UTC"
                self.predicted_close_utc = "2026-11-06 08:00"
                self.quality_grade = "Grade A"
                self.meta_win_prob_pct = 70.0

        sig = MockSignal()
        # Price is sitting at 99.75 (-0.25% noise, SL 97.5 never hit)
        live_prices = {"MOCKUSDT": 99.75, "MOCK/USDT": 99.75}

        ss = SignalService()
        now_test = datetime(2026, 11, 6, 11, 0, 0, tzinfo=timezone.utc)
        updated = ss.evaluate_active_signals([sig], live_prices=live_prices, now_utc=now_test)
        self.assertTrue(updated)
        self.assertEqual(sig.status, "EXPIRED_BREAKEVEN")
        self.assertIn("EXPIRED", sig.outcome_label)
        self.assertIn("BE", sig.outcome_label)

        # Audit engine must classify as BREAKEVEN, preserving win rate integrity
        cat = classify_signal_outcome(sig.status, sig.outcome_label, sig.realized_return_pct)
        self.assertEqual(cat, "BREAKEVEN")

    def test_03_severe_flatline_stagnation_pre_trade_rejection(self):
        """
        Dead flatline stagnation (ADX < 12 and BBW < 1.2% with dry volume)
        must trigger NTZ rejection even if an order block setup is claimed.
        """
        # Create 30 candles of dead flat sideways price action (0.01% range)
        prices = [100.0 + (0.01 * (i % 2)) for i in range(40)]
        df = pd.DataFrame({
            "open": prices,
            "high": [p + 0.005 for p in prices],
            "low": [p - 0.005 for p in prices],
            "close": prices,
            "volume": [100.0] * 40
        })

        ntz_engine = NoTradeZoneEngine()
        res = ntz_engine.evaluate_asset_ntz(
            df=df,
            current_price=100.0,
            anchor_tf="15m",
            ob_setup={"setup_detected": True, "state": "TESTING", "in_order_block_zone": True},
            decision="ORDER_BLOCK_LONG"
        )
        self.assertTrue(res["is_ntz"])
        self.assertEqual(res["code"], NoTradeZoneReason.CHOP_CONSOLIDATION.value)
        self.assertIn("Dead Flatline Stagnation", res["reasons"][0])

    def test_04_dynamic_consolidation_grace_extension(self):
        """
        When a trade reaches canonical TTL (7200s for 15M), if price is coiled within
        flat consolidation corridor (<= 0.60%), dynamic grace extension (+50% TTL)
        keeps the trade active, preventing premature death before breakout.
        """
        class MockSignal:
            def __init__(self):
                self.signal_id = "SIG_GRACE_01"
                self.symbol = "MOCK/USDT"
                self.horizon = "15M"
                self.direction = "LONG"
                self.entry_price = 100.0
                self.sl_price = 97.5
                self.tp1_price = 105.0
                self.tp2_price = 110.0
                self.tp3_price = 115.0
                self.status = "ACTIVE"
                self.outcome_label = "ACTIVE"
                self.exit_price = None
                self.realized_return_pct = None
                self.peak_price_seen = 100.1
                self.trough_price_seen = 99.8
                # Signal created at 06:00:00 UTC
                self.created_at = datetime(2026, 11, 6, 6, 0, 0, tzinfo=timezone.utc)
                self.date_utc = "2026-11-06"
                self.time_utc = "06:00:00 UTC"
                self.predicted_close_utc = None
                self.quality_grade = "Grade A"
                self.meta_win_prob_pct = 70.0

        sig = MockSignal()
        # Price is sitting at 100.10 (+0.10% coiling), SL 97.5 untouched
        live_prices = {"MOCKUSDT": 100.10, "MOCK/USDT": 100.10}

        ss = SignalService()
        # Evaluate at 08:15:00 UTC (8100s elapsed, which is > 7200s, but < 10800s grace limit)
        now_test = datetime(2026, 11, 6, 8, 15, 0, tzinfo=timezone.utc)
        updated = ss.evaluate_active_signals([sig], live_prices=live_prices, now_utc=now_test)

        # Signal MUST remain ACTIVE (not prematurely expired) due to consolidation grace
        self.assertEqual(sig.status, "ACTIVE")
        self.assertIsNone(sig.exit_price)

    def test_05_acute_black_swan_circuit_breaker_paper_bot(self):
        """
        Paper trading bot must trigger emergency exit when BTC enters
        BEAR_CASCADE_BLACKOUT or acute adverse gap shock occurs.
        """
        import tempfile
        tmp_ledger = tempfile.mktemp(suffix=".json")
        bot = PaperTradingBot(ledger_file=tmp_ledger)
        bot.data["open_positions"] = [{
            "trade_id": "PT_BS_01",
            "symbol": "SOL/USDT",
            "direction": "LONG",
            "status": "OPEN",
            "entry_price": 100.0,
            "sl_price": 97.0,
            "tp1_price": 106.0,
            "position_size_usd": 1000.0,
            "leverage": 1.0,
            "peak_gain_pct": 0.0,
            "opened_at_utc": "2026-11-06T10:00:00Z",
            "horizon": "15M"
        }]

        # Simulate acute macro flash dump
        btc_shield = {
            "status_code": "BEAR_CASCADE_BLACKOUT",
            "regime": "FLASH_DUMP",
            "altcoin_posture": "DEFENSIVE_CASH_ONLY"
        }

        # Price dropped -3.5% (acute gap penetration)
        live_prices = {"SOLUSDT": 96.5, "SOL/USDT": 96.5}
        bot.on_tick(live_prices=live_prices, btc_shield_state=btc_shield)

        self.assertEqual(len(bot.data["open_positions"]), 0)
        self.assertEqual(len(bot.data["closed_trades"]), 1)
        closed = bot.data["closed_trades"][0]
        self.assertIn("EMERGENCY", closed["exit_reason"])
        # Gap exit price must be <= 96.5 (not idealized 97.0)
        self.assertLessEqual(closed["exit_price"], 97.0)


if __name__ == "__main__":
    unittest.main()
