import unittest
import os
import tempfile
import shutil
from datetime import datetime, timezone, timedelta
from app.services.signal_service import SignalService
from app.engine.execution.paper_trading_bot import PaperTradingBot

class TestV16NoSignalExpiry(unittest.TestCase):
    """
    Verification suite for User Request #7:
    Remove signal expiry from the system and wait for signals/positions to go to TP or SL.
    """

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.ledger_file = os.path.join(self.tmp_dir, "test_paper_trading_ledger.json")
        # Ensure ENABLE_SIGNAL_EXPIRY is False (production default)
        os.environ["ENABLE_SIGNAL_EXPIRY"] = "false"

    def tearDown(self):
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        os.environ.pop("ENABLE_SIGNAL_EXPIRY", None)

    def test_01_active_signal_never_expires_by_time_and_waits_for_tp(self):
        """Active signal past predicted close / duration remains ACTIVE until TP is hit."""
        class MockSignal:
            def __init__(self):
                self.signal_id = "SIG_NO_EXP_01"
                self.symbol = "MOCK_SOL/USDT"
                self.horizon = "15M"
                self.direction = "LONG"
                self.entry_price = 150.0
                self.sl_price = 145.0
                self.tp1_price = 160.0
                self.tp2_price = 165.0
                self.tp3_price = 170.0
                self.status = "ACTIVE"
                self.outcome_label = "ACTIVE"
                self.exit_price = None
                self.realized_return_pct = None
                self.peak_price_seen = 150.2
                self.trough_price_seen = 149.0
                # Far past 15M duration (e.g. 5 hours ago)
                self.created_at = datetime.now(timezone.utc) - timedelta(hours=5)
                self.date_utc = self.created_at.strftime("%Y-%m-%d")
                self.time_utc = self.created_at.strftime("%H:%M:%S UTC")
                self.predicted_close_utc = (self.created_at + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S UTC")
                self.quality_grade = "Grade A"
                self.meta_win_prob_pct = 75.0

        sig = MockSignal()
        ss = SignalService()
        
        # 1. Tick at entry ($150.0) after 5 hours: must NOT expire
        ss.evaluate_active_signals([sig], live_prices={"MOCK_SOL/USDT": 150.0, "MOCK_SOLUSDT": 150.0})
        self.assertEqual(sig.status, "ACTIVE", "Signal must remain ACTIVE and not expire past horizon")
        self.assertIsNone(sig.exit_price)

        # 2. Tick at TP1 ($160.0): must hit TP1
        ss.evaluate_active_signals([sig], live_prices={"MOCK_SOL/USDT": 160.0, "MOCK_SOLUSDT": 160.0})
        self.assertIn(sig.status, ["TP1_LOCKED_BREAKEVEN", "WON_TP1"], "Signal must trigger TP1 when touched")

    def test_02_active_signal_waits_indefinitely_until_sl(self):
        """Active signal past predicted close remains ACTIVE until SL is hit."""
        class MockSignal:
            def __init__(self):
                self.signal_id = "SIG_NO_EXP_02"
                self.symbol = "MOCK_AVAX/USDT"
                self.horizon = "1H"
                self.direction = "LONG"
                self.entry_price = 30.0
                self.sl_price = 28.5
                self.tp1_price = 33.0
                self.tp2_price = 35.0
                self.tp3_price = 37.0
                self.status = "ACTIVE"
                self.outcome_label = "ACTIVE"
                self.exit_price = None
                self.realized_return_pct = None
                self.peak_price_seen = 30.1
                self.trough_price_seen = 29.5
                self.created_at = datetime.now(timezone.utc) - timedelta(hours=24)
                self.date_utc = self.created_at.strftime("%Y-%m-%d")
                self.time_utc = self.created_at.strftime("%H:%M:%S UTC")
                self.predicted_close_utc = (self.created_at + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S UTC")
                self.quality_grade = "Grade A"
                self.meta_win_prob_pct = 70.0

        sig = MockSignal()
        ss = SignalService()

        # Tick at $29.0 (adverse, but SL is 28.5) after 24 hours: must NOT expire
        ss.evaluate_active_signals([sig], live_prices={"MOCK_AVAX/USDT": 29.0, "MOCK_AVAXUSDT": 29.0})
        self.assertEqual(sig.status, "ACTIVE")

        # Tick at $28.4 (SL breached): must exit as LOST_SL
        ss.evaluate_active_signals([sig], live_prices={"MOCK_AVAX/USDT": 28.4, "MOCK_AVAXUSDT": 28.4})
        self.assertEqual(sig.status, "LOST_SL")
        self.assertIsNotNone(sig.exit_price)

    def test_03_paper_position_never_expires_and_waits_for_tp(self):
        """Paper trading bot position never exits on HORIZON_EXPIRY and waits for TP."""
        bot = PaperTradingBot(ledger_file=self.ledger_file)
        self.assertFalse(bot.enable_signal_expiry)

        opened_ts = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
        pos = {
            "trade_id": "PAPER_NO_EXP_01",
            "symbol": "NEAR/USDT",
            "desk": "scalp",
            "direction": "LONG",
            "horizon": "15M",
            "signal_horizon": "15M",
            "leverage": 2,
            "position_size_usd": 100.0,
            "remaining_position_size_usd": 100.0,
            "entry_price": 5.0,
            "initial_sl_price": 4.80,
            "sl_price": 4.80,
            "tp1_price": 5.40,
            "tp2_price": 5.60,
            "tp3_price": 5.80,
            "opened_at": opened_ts,
            "opened_at_utc": opened_ts,
            "status": "OPEN",
            "scaling_policy": "MULTI_TRANCHE_SCALE"
        }
        bot.data["open_positions"] = [pos]

        # Tick at 4.95 (underwater, 10 hours elapsed >> 2h hold): must remain OPEN
        bot.on_tick(live_prices={"NEAR/USDT": 4.95})
        self.assertEqual(len(bot.data["open_positions"]), 1, "Position must remain open indefinitely")
        self.assertEqual(len(bot.data.get("closed_trades", [])), 0)

        # Tick at 5.42 (TP1 reached): must scale TP1
        bot.on_tick(live_prices={"NEAR/USDT": 5.42})
        updated = bot.data["open_positions"][0]
        self.assertTrue(updated.get("tp1_hit"), "Must bank TP1 when price target is reached")

    def test_04_resting_limit_order_does_not_expire_on_ttl(self):
        """Resting limit orders wait for price pullback/fill and do not expire on TTL."""
        bot = PaperTradingBot(ledger_file=self.ledger_file)
        self.assertFalse(bot.enable_signal_expiry)

        placed_ts = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        pos = {
            "trade_id": "RESTING_NO_EXP_01",
            "symbol": "BTC/USDT",
            "desk": "scalp",
            "direction": "LONG",
            "horizon": "15M",
            "signal_horizon": "15M",
            "position_size_usd": 200.0,
            "entry_price": 60000.0,
            "optimal_entry_limit": 59800.0,
            "entry_zone_min": 59700.0,
            "entry_zone_max": 59900.0,
            "sl_price": 59000.0,
            "tp1_price": 61500.0,
            "status": "RESTING_LIMIT",
            "is_resting_limit": True,
            "placed_at_utc": placed_ts,
            "opened_at_utc": placed_ts
        }
        bot.data["open_positions"] = [pos]

        # Price hovering at 60100 (5 hours elapsed >> 45m limit TTL): must NOT be cancelled for TTL
        bot.on_tick(live_prices={"BTC/USDT": 60100.0})
        self.assertEqual(len(bot.data["open_positions"]), 1, "Resting limit order must remain active")
        self.assertEqual(bot.data["open_positions"][0]["status"], "RESTING_LIMIT")

if __name__ == "__main__":
    unittest.main()
