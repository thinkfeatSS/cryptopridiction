import unittest
import os
import json
import tempfile
from datetime import datetime, timezone, timedelta
from app.engine.execution.paper_trading_bot import PaperTradingBot
from app.services.signal_service import SignalService

class TestTrailingExpiryAndRunnerProtection(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.ledger_file = os.path.join(self.tmp_dir, "test_paper_trading_ledger.json")

    def tearDown(self):
        import shutil
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_01_active_runner_tp1_hit_never_exits_on_hard_time_stop(self):
        """
        AC-01: An active runner that achieved TP1 (30% remaining position) must NEVER
        be forcefully terminated by the canonical 2h (7200s) time stop. It must remain
        protected by the trailed stop-loss up to the 4.0x safety ceiling (28,800s).
        """
        bot = PaperTradingBot(ledger_file=self.ledger_file)
        # Opened 8,000 seconds ago (> 7,200s canonical hold for 15M)
        opened_ts = (datetime.now(timezone.utc) - timedelta(seconds=8000)).isoformat()
        pos = {
            "trade_id": "RUNNER_TEST_01",
            "symbol": "BTC/USDT",
            "desk": "scalp",
            "direction": "LONG",
            "horizon": "15M",
            "signal_horizon": "15M",
            "leverage": 2,
            "position_size_usd": 150.0,
            "remaining_position_size_usd": 45.0,  # 30% runner remaining
            "entry_price": 60000.0,
            "initial_sl_price": 59000.0,
            "sl_price": 60500.0,  # Trailed profit buffer
            "tp1_price": 62000.0,
            "tp2_price": 64000.0,
            "tp3_price": 66000.0,
            "tp1_hit": True,
            "tp2_hit": False,
            "opened_at": opened_ts,
            "opened_at_utc": opened_ts,
            "status": "OPEN_TP1_LOCKED_TRAIL",
            "total_realized_partial_usd": 4.50,
            "total_gross_partial_usd": 4.80,
            "total_frictions_partial_usd": 0.30,
            "peak_price_seen": 62500.0,
            "scaling_policy": "MULTI_TRANCHE_SCALE"
        }
        bot.data["open_positions"] = [pos]
        bot.data["desks"]["scalp"]["active_slots"] = 1

        # Current tick at $62,400 (comfortably above trailed SL 60,500)
        bot.on_tick(live_prices={"BTC/USDT": 62400.0})

        # Runner position MUST remain open and NOT be expired by the clock
        self.assertEqual(len(bot.data["open_positions"]), 1)
        self.assertTrue(bot.data["open_positions"][0].get("is_runner_protected"))
        self.assertEqual(bot.data["open_positions"][0].get("trailing_expiry_mode"), "RUNNER_PROTECTED")
        self.assertEqual(len(bot.data.get("closed_trades", [])), 0)

    def test_02_runner_trailing_stop_ratchet_tp1_to_tp2(self):
        """
        AC-02: As price advances past TP1 towards TP2, the stop-loss must dynamically
        trail behind peak prices using the active ATR buffer.
        """
        bot = PaperTradingBot(ledger_file=self.ledger_file)
        opened_ts = (datetime.now(timezone.utc) - timedelta(seconds=3000)).isoformat()
        pos = {
            "trade_id": "RUNNER_TEST_02",
            "symbol": "ETH/USDT",
            "desk": "scalp",
            "direction": "LONG",
            "horizon": "15M",
            "signal_horizon": "15M",
            "leverage": 2,
            "position_size_usd": 150.0,
            "remaining_position_size_usd": 45.0,
            "entry_price": 3000.0,
            "initial_sl_price": 2950.0,
            "sl_price": 3025.0,  # Initial profit buffer: entry + 0.25*(tp1-entry)
            "tp1_price": 3100.0,
            "tp2_price": 3200.0,
            "tp3_price": 3300.0,
            "active_atr": 30.0,
            "tp1_hit": True,
            "tp2_hit": False,
            "opened_at": opened_ts,
            "opened_at_utc": opened_ts,
            "status": "OPEN_TP1_LOCKED_TRAIL",
            "peak_price_seen": 3100.0,
            "scaling_policy": "MULTI_TRANCHE_SCALE"
        }
        bot.data["open_positions"] = [pos]

        # Price rallies towards TP2 to 3160.0
        bot.on_tick(live_prices={"ETH/USDT": 3160.0})

        updated = bot.data["open_positions"][0]
        # SL must have trailed higher than the initial 3025.0
        self.assertTrue(float(updated["sl_price"]) > 3025.0)
        self.assertTrue(updated.get("is_tp1_trail_active"))
        self.assertEqual(float(updated["peak_price_seen"]), 3160.0)

    def test_03_runner_exit_via_trail_sl_mapped_to_won(self):
        """
        AC-03: When a runner position's trailed stop-loss is hit, the exit reason
        must be TAKE_PROFIT_1_TRAIL_SL and the outcome must be strictly WON.
        """
        bot = PaperTradingBot(ledger_file=self.ledger_file)
        opened_ts = (datetime.now(timezone.utc) - timedelta(seconds=5000)).isoformat()
        pos = {
            "trade_id": "RUNNER_TEST_03",
            "symbol": "SOL/USDT",
            "desk": "scalp",
            "direction": "LONG",
            "horizon": "15M",
            "signal_horizon": "15M",
            "leverage": 2,
            "position_size_usd": 150.0,
            "remaining_position_size_usd": 45.0,
            "entry_price": 150.0,
            "initial_sl_price": 145.0,
            "sl_price": 153.0,  # Trailed stop above entry
            "tp1_price": 158.0,
            "tp2_price": 165.0,
            "tp3_price": 172.0,
            "tp1_hit": True,
            "tp2_hit": False,
            "opened_at": opened_ts,
            "opened_at_utc": opened_ts,
            "status": "OPEN_TP1_LOCKED_TRAIL",
            "total_realized_partial_usd": 3.80,
            "total_gross_partial_usd": 4.10,
            "total_frictions_partial_usd": 0.30,
            "scaling_policy": "MULTI_TRANCHE_SCALE"
        }
        bot.data["open_positions"] = [pos]

        # Price drops to 152.0, breaching trailed SL at 153.0
        bot.on_tick(live_prices={"SOL/USDT": 152.0})

        # Trade must be closed as WON with TAKE_PROFIT_1_TRAIL_SL
        self.assertEqual(len(bot.data["open_positions"]), 0)
        self.assertEqual(len(bot.data["closed_trades"]), 1)
        closed = bot.data["closed_trades"][0]
        self.assertEqual(closed["exit_reason"], "TAKE_PROFIT_1_TRAIL_SL")
        self.assertEqual(closed["outcome"], "WON")
        self.assertTrue(float(closed["net_pnl_usd"]) > 0.0)

    def test_04_profitable_pre_tp1_trade_receives_trailing_expiry_extension(self):
        """
        AC-04: A pre-TP1 trade in solid profit (+1.2%) that exceeds the canonical
        hold time (7500s > 7200s) must NOT be killed by a hard time stop. It must
        receive a dynamic trailing expiry extension (+1.0x TTL, up to 2.5x).
        """
        bot = PaperTradingBot(ledger_file=self.ledger_file)
        # 7500s elapsed (> 7200s base hold for 15M)
        opened_ts = (datetime.now(timezone.utc) - timedelta(seconds=7500)).isoformat()
        pos = {
            "trade_id": "PROFIT_PRE_TP1_01",
            "symbol": "AVAX/USDT",
            "desk": "scalp",
            "direction": "LONG",
            "horizon": "15M",
            "signal_horizon": "15M",
            "leverage": 2,
            "position_size_usd": 150.0,
            "remaining_position_size_usd": 150.0,
            "entry_price": 30.0,
            "initial_sl_price": 29.0,
            "sl_price": 30.02,  # Soft BE active
            "tp1_price": 31.0,
            "tp2_price": 32.0,
            "tp3_price": 33.0,
            "is_breakeven_locked": True,
            "opened_at": opened_ts,
            "opened_at_utc": opened_ts,
            "status": "TIER0_PROTECTED_BREAKEVEN",
            "scaling_policy": "MULTI_TRANCHE_SCALE"
        }
        bot.data["open_positions"] = [pos]

        # Spot price at 30.36 (+1.2% unrealized gain)
        bot.on_tick(live_prices={"AVAX/USDT": 30.36})

        # Must NOT expire; must engage PROFIT_MOMENTUM_EXTENSION
        self.assertEqual(len(bot.data["open_positions"]), 1)
        self.assertTrue(bot.data["open_positions"][0].get("is_trailing_expiry_active"))
        self.assertEqual(bot.data["open_positions"][0].get("trailing_expiry_mode"), "PROFIT_MOMENTUM_EXTENSION")
        self.assertEqual(len(bot.data.get("closed_trades", [])), 0)

    def test_05_stagnant_losing_trade_cleanly_expires_at_canonical_ttl(self):
        """
        AC-05: An unprofitable or stagnant trade (-1.33%) that exceeds the canonical
        hold time (7300s > 7200s) must cleanly trigger HORIZON_EXPIRY to free desk slots.
        """
        bot = PaperTradingBot(ledger_file=self.ledger_file)
        opened_ts = (datetime.now(timezone.utc) - timedelta(seconds=7300)).isoformat()
        pos = {
            "trade_id": "LOSER_EXPIRE_01",
            "symbol": "SOL/USDT",
            "desk": "scalp",
            "direction": "LONG",
            "horizon": "15M",
            "signal_horizon": "15M",
            "leverage": 2,
            "position_size_usd": 150.0,
            "remaining_position_size_usd": 150.0,
            "entry_price": 150.0,
            "initial_sl_price": 140.0,
            "sl_price": 140.0,
            "tp1_price": 160.0,
            "tp2_price": 165.0,
            "tp3_price": 170.0,
            "opened_at": opened_ts,
            "opened_at_utc": opened_ts,
            "status": "OPEN",
            "scaling_policy": "MULTI_TRANCHE_SCALE"
        }
        bot.data["open_positions"] = [pos]

        # Spot price at 148.0 (-1.33% loss, SL 140 not breached)
        bot.on_tick(live_prices={"SOL/USDT": 148.0})

        # Stagnant losing trade must cleanly exit on HORIZON_EXPIRY
        self.assertEqual(len(bot.data["open_positions"]), 0)
        self.assertEqual(len(bot.data["closed_trades"]), 1)
        closed = bot.data["closed_trades"][0]
        self.assertTrue("HORIZON_EXPIRY" in closed["exit_reason"])
        self.assertEqual(closed["outcome"], "LOST")

    def test_06_signal_service_progression_with_trailing_expiry(self):
        """
        AC-06: SignalService must not expire signals that are in TP1_LOCKED_BREAKEVEN
        or in profit momentum extension when evaluating historical progression.
        """
        class MockSignal:
            def __init__(self, sid, sym, status, entry, curr, tp1, sl, age_sec):
                self.signal_id = sid
                self.symbol = sym
                self.horizon = "15M"
                self.direction = "LONG"
                self.entry_price = entry
                self.current_price = curr
                self.sl_price = sl
                self.tp1_price = tp1
                self.tp2_price = tp1 * 1.05
                self.tp3_price = tp1 * 1.10
                self.status = status
                self.outcome_label = status
                self.exit_price = None
                self.realized_return_pct = None
                self.peak_price_seen = curr
                self.trough_price_seen = curr
                self.created_at = datetime.now(timezone.utc) - timedelta(seconds=age_sec)
                self.date_utc = self.created_at.strftime("%Y-%m-%d")
                self.time_utc = self.created_at.strftime("%H:%M:%S UTC")
                self.predicted_close_utc = None
                self.quality_grade = "Grade A"
                self.meta_win_prob_pct = 75.0

        # Use MOCK symbols so live exchange wicks do not interfere with deterministic unit fixtures
        s1 = MockSignal("SIG_RUNNER_01", "MOCK_RUNNER/USDT", "TP1_LOCKED_BREAKEVEN", 100.0, 103.0, 105.0, 100.5, 8000)
        s2 = MockSignal("SIG_PROFIT_02", "MOCK_PROFIT/USDT", "TIER0_PROTECTED_BREAKEVEN", 100.0, 101.5, 105.0, 100.05, 8000)
        s3 = MockSignal("SIG_LOSER_03", "MOCK_LOSER/USDT", "ACTIVE", 100.0, 99.0, 105.0, 95.0, 8000)

        ss = SignalService()
        live_prices = {
            "MOCK_RUNNER/USDT": 103.0, "MOCK_RUNNERUSDT": 103.0,
            "MOCK_PROFIT/USDT": 101.5, "MOCK_PROFITUSDT": 101.5,
            "MOCK_LOSER/USDT": 99.0, "MOCK_LOSERUSDT": 99.0
        }
        now_test = datetime.now(timezone.utc)
        ss.evaluate_active_signals([s1, s2, s3], live_prices=live_prices, now_utc=now_test)

        # s1 must remain alive in runner mode (not expired)
        self.assertEqual(s1.status, "TP1_LOCKED_BREAKEVEN")
        self.assertIsNone(s1.exit_price)

        # s2 must remain alive in profit momentum mode (not expired)
        self.assertEqual(s2.status, "TIER0_PROTECTED_BREAKEVEN")
        self.assertIsNone(s2.exit_price)

        # s3 must cleanly expire
        self.assertIn("EXPIRED", s3.status)
        self.assertIsNotNone(s3.exit_price)

    def test_07_tp1_runner_expiry_preserves_tp1_classification_and_mfe_mae(self):
        """
        Regression Test (TIA_USDT_15M_1794387811 root cause):
        A TP1-hit runner that reaches the 4.0x runner safety ceiling (8h for 15M)
        must record TAKE_PROFIT_1_RUNNER_EXPIRY (not bare HORIZON_EXPIRY), preserve
        tp1_hit=True / sl_price / peak_price_seen / trough_price_seen / peak_gain_pct /
        max_drawdown_pct in closed_record, and classify as WON_TP1_EXP (never WON_EXP_PROFIT).
        """
        from app.quant_v16.audit import classify_signal_outcome

        bot = PaperTradingBot(ledger_file=self.ledger_file)
        # Opened 29,000s ago (> 28,800s 4.0x ceiling for 15M)
        opened_ts = (datetime.now(timezone.utc) - timedelta(seconds=29000)).isoformat()
        pos = {
            "trade_id": "TIA_RUNNER_REGRESSION_07",
            "symbol": "TIA/USDT",
            "desk": "scalp",
            "direction": "LONG",
            "horizon": "15M",
            "signal_horizon": "15M",
            "leverage": 1,
            "position_size_usd": 100.0,
            "remaining_position_size_usd": 30.0,
            "entry_price": 0.4265,
            "initial_sl_price": 0.423187,
            "sl_price": 0.428488,  # Profit-locked SL after TP1
            "tp1_price": 0.434452,
            "tp2_price": 0.440000,
            "tp3_price": 0.450000,
            "tp1_hit": True,
            "tp2_hit": False,
            "is_breakeven_locked": True,
            "opened_at": opened_ts,
            "opened_at_utc": opened_ts,
            "status": "OPEN_TP1_LOCKED_BREAKEVEN",
            "total_realized_partial_usd": 1.30,
            "total_gross_partial_usd": 1.40,
            "total_frictions_partial_usd": 0.10,
            "peak_price_seen": 0.4407,
            "trough_price_seen": 0.4250,
            "peak_gain_pct": 3.33,
            "max_drawdown_pct": 0.35,
            "scaling_policy": "MULTI_TRANCHE_SCALE"
        }
        bot.data["open_positions"] = [pos]
        bot.data["desks"]["scalp"]["active_slots"] = 1

        # Tick at $0.4340 (above profit-locked SL 0.428488, below TP2)
        bot.on_tick(live_prices={"TIA/USDT": 0.4340})

        self.assertEqual(len(bot.data["open_positions"]), 0)
        self.assertEqual(len(bot.data["closed_trades"]), 1)
        c = bot.data["closed_trades"][0]
        self.assertTrue(c["exit_reason"].startswith("TAKE_PROFIT_1_RUNNER_EXPIRY"))
        self.assertTrue(c["tp1_hit"])
        self.assertFalse(c["tp2_hit"])
        self.assertAlmostEqual(c["sl_price"], 0.428488, places=6)
        self.assertAlmostEqual(c["peak_price_seen"], 0.4407, places=4)
        self.assertAlmostEqual(c["trough_price_seen"], 0.4250, places=4)
        self.assertGreater(c["peak_gain_pct"], 0.0)
        self.assertGreater(c["max_drawdown_pct"], 0.0)
        self.assertEqual(classify_signal_outcome("WON_TP1_EXP", "", c["return_pct"]), "WON")
        self.assertEqual(classify_signal_outcome("WON_TP2_EXP", "", c["return_pct"]), "WON")

if __name__ == "__main__":
    unittest.main()
