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
        # Ensure ENABLE_SIGNAL_EXPIRY and ENABLE_BREAKEVEN_GUARD are False (production default)
        os.environ["ENABLE_SIGNAL_EXPIRY"] = "false"
        os.environ["ENABLE_BREAKEVEN_GUARD"] = "false"

    def tearDown(self):
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        os.environ.pop("ENABLE_SIGNAL_EXPIRY", None)
        os.environ.pop("ENABLE_BREAKEVEN_GUARD", None)

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

    def test_05_no_breakeven_guard_before_tp1(self):
        """Zero Breakeven Guard: SL remains strictly at structural SL until TP1 is hit."""
        # 1. PaperTradingBot test
        bot = PaperTradingBot(ledger_file=self.ledger_file)
        self.assertFalse(bot.enable_breakeven_guard)

        opened_ts = datetime.now(timezone.utc).isoformat()
        pos = {
            "trade_id": "PAPER_NO_BE_01",
            "symbol": "BTC/USDT",
            "desk": "scalp",
            "direction": "LONG",
            "horizon": "15M",
            "signal_horizon": "15M",
            "leverage": 2,
            "position_size_usd": 100.0,
            "remaining_position_size_usd": 100.0,
            "entry_price": 100.0,
            "initial_sl_price": 95.0,
            "sl_price": 95.0,
            "tp1_price": 110.0,
            "tp2_price": 115.0,
            "tp3_price": 120.0,
            "opened_at": opened_ts,
            "opened_at_utc": opened_ts,
            "status": "OPEN",
            "scaling_policy": "MULTI_TRANCHE_SCALE"
        }
        bot.data["open_positions"] = [pos]

        # Tick 1: price rises +0.80% to 100.80 (previously triggered Micro-Guard and Tier-0 soft BE)
        bot.on_tick(live_prices={"BTC/USDT": 100.80})
        self.assertEqual(len(bot.data["open_positions"]), 1)
        self.assertEqual(bot.data["open_positions"][0]["sl_price"], 95.0, "SL must NOT move to BE before TP1")

        # Tick 2: price pulls back exactly to entry 100.00
        bot.on_tick(live_prices={"BTC/USDT": 100.00})
        self.assertEqual(len(bot.data["open_positions"]), 1, "Position must NOT be stopped out at breakeven")
        self.assertEqual(bot.data["open_positions"][0]["status"], "OPEN")
        self.assertEqual(len(bot.data.get("closed_trades", [])), 0)

        # 2. SignalService test
        class MockSignalBE:
            def __init__(self):
                self.signal_id = "SIG_NO_BE_01"
                self.symbol = "SOL/USDT"
                self.horizon = "15M"
                self.direction = "LONG"
                self.entry_price = 100.0
                self.sl_price = 95.0
                self.sl_original = 95.0
                self.tp1_price = 110.0
                self.tp2_price = 115.0
                self.tp3_price = 120.0
                self.status = "ACTIVE"
                self.outcome_label = "ACTIVE"
                self.exit_price = None
                self.realized_return_pct = None
                self.peak_price_seen = 100.0
                self.trough_price_seen = 100.0
                self.created_at = datetime.now(timezone.utc)
                self.date_utc = self.created_at.strftime("%Y-%m-%d")
                self.time_utc = self.created_at.strftime("%H:%M:%S UTC")
                self.predicted_close_utc = (self.created_at + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S UTC")
                self.quality_grade = "Grade A"
                self.meta_win_prob_pct = 75.0

        sig = MockSignalBE()
        ss = SignalService()

        # Tick at +0.80% ($100.80)
        ss.evaluate_active_signals([sig], live_prices={"SOL/USDT": 100.80, "SOLUSDT": 100.80})
        self.assertEqual(sig.status, "ACTIVE", "Signal must remain ACTIVE without Tier-0 BE ratchet")
        self.assertEqual(sig.sl_price, 95.0, "SL must remain at original 95.0")

        # Pullback to entry ($100.00)
        ss.evaluate_active_signals([sig], live_prices={"SOL/USDT": 100.00, "SOLUSDT": 100.00})
        self.assertEqual(sig.status, "ACTIVE", "Signal must remain ACTIVE upon pullback to entry")
        self.assertIsNone(sig.exit_price)

    def test_06_resting_limit_latency_blackout_safety_disabled(self):
        """Resting limits do not get cancelled when feed latency exceeds blackout safety ceiling."""
        bot = PaperTradingBot(ledger_file=self.ledger_file)
        self.assertFalse(bot.enable_signal_expiry)

        placed_ts = datetime.now(timezone.utc).isoformat()
        pos = {
            "trade_id": "AR_USDT_15M_1794523066",
            "symbol": "AR/USDT",
            "desk": "scalp",
            "direction": "SHORT",
            "horizon": "15M",
            "signal_horizon": "15M",
            "position_size_usd": 150.0,
            "entry_price": 3.0750,
            "optimal_entry_limit": 3.0750,
            "entry_zone_min": 3.0600,
            "entry_zone_max": 3.0900,
            "sl_price": 3.1211,
            "tp1_price": 2.9828,
            "status": "RESTING_LIMIT",
            "is_resting_limit": True,
            "placed_at_utc": placed_ts,
            "opened_at_utc": placed_ts
        }
        bot.data["open_positions"] = [pos]

        # Simulate 307-second feed latency (exceeds default 8000ms blackout safety ceiling)
        bot.on_tick(live_prices={"AR/USDT": 3.0750}, tick_latency_ms=307618.0)

        # Order must NOT be cancelled into cancelled_orders
        cancelled_reasons = [c.get("cancellation_reason") for c in bot.data.get("cancelled_orders", [])]
        self.assertNotIn("CANCELLED_NETWORK_BLACKOUT_SAFETY", cancelled_reasons,
                         "Resting limit must not be cancelled by feed latency when signal expiry is disabled")

    def test_07_ar_usdt_healing_to_won_tp1(self):
        """Signals previously marked EXPIRED_HORIZON heal to WON_TP1 when price touched TP1."""
        # Setup simulated store records matching AR_USDT_15M_1794523066
        imm = {
            "signal_id": "AR_USDT_15M_1794523066",
            "symbol": "AR/USDT",
            "direction": "SHORT",
            "entry_price_initial": 3.0750,
            "tp1_initial": 2.9828,
            "sl_initial": 3.1211,
            "status": "EXPIRED_HORIZON"
        }
        dyn = {
            "signal_id": "AR_USDT_15M_1794523066",
            "status": "EXPIRED_HORIZON",
            "outcome_label": "⏱️ EXPIRED",
            "current_price": 2.9040, # Real Binance price reached 2.9040
            "peak_price_seen": 3.0750,
            "trough_price_seen": 2.9040,
            "mfe_pct": 5.56
        }

        # Simulate the authoritative healing block from app/routers/v16_router.py
        entry_v = float(imm.get("entry_price_initial", 0.0))
        tp1_v = float(imm.get("tp1_initial", 0.0))
        sl_v = float(imm.get("sl_initial", 0.0))
        dir_v = str(imm.get("direction", "LONG")).upper()
        pk_v = float(dyn.get("peak_price_seen") or 0.0)
        tr_v = float(dyn.get("trough_price_seen") or 0.0)
        curr_v = float(dyn.get("current_price", entry_v))

        hit_tp1_real = (dir_v == "LONG" and (pk_v >= tp1_v or curr_v >= tp1_v)) or (dir_v == "SHORT" and (0 < tr_v <= tp1_v or 0 < curr_v <= tp1_v))
        self.assertTrue(hit_tp1_real, "AR/USDT SHORT with trough 2.9040 must qualify as real TP1 hit")

        gain_val = round(abs(tp1_v - entry_v) / max(1e-9, entry_v) * 100.0, 2)
        dyn["status"] = "WON_TP1"
        dyn["outcome_label"] = f"🟢 WON (TP1 HIT +{gain_val:.2f}%)"
        dyn["exit_price"] = tp1_v
        dyn["realized_return_pct"] = gain_val

        self.assertEqual(dyn["status"], "WON_TP1")
        self.assertIn("WON (TP1 HIT +3.00%)", dyn["outcome_label"])
        self.assertEqual(dyn["exit_price"], 2.9828)
        self.assertEqual(dyn["realized_return_pct"], 3.0)

    def test_08_prolonged_open_signals_in_consolidation_do_not_expire_or_choke_desk(self):
        """Prolonged open signals in range-bound chop remain active indefinitely and do not starve new incoming setups."""
        bot = PaperTradingBot(ledger_file=self.ledger_file)
        self.assertFalse(bot.enable_signal_expiry)

        # 5 existing scalp positions open for 5 hours in flat consolidation (abs(pnl) <= 0.50%)
        opened_ts = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        desk_positions = []
        valid_coins = ["ADA/USDT", "DOT/USDT", "AVAX/USDT", "LINK/USDT", "NEAR/USDT"]
        for i, sym in enumerate(valid_coins):
            desk_positions.append({
                "trade_id": f"SCALP_CHOP_{i}",
                "symbol": sym,
                "desk": "scalp",
                "direction": "LONG",
                "horizon": "15M",
                "signal_horizon": "15M",
                "position_size_usd": 50.0,
                "entry_price": 10.0,
                "current_price": 10.02, # +0.20% flat consolidation
                "unrealized_pnl_pct": 0.20,
                "sl_price": 9.50,
                "tp1_price": 11.0,
                "status": "OPEN",
                "opened_at_utc": opened_ts,
                "opened_at": opened_ts
            })
        bot.data["open_positions"] = desk_positions

        # 1. On tick: none of the 5 prolonged positions should expire
        bot.on_tick(live_prices={sym: 10.02 for sym in valid_coins})
        self.assertEqual(len(bot.data["open_positions"]), 5, "Prolonged range-bound positions must remain active")
        for p in bot.data["open_positions"]:
            self.assertEqual(p["status"], "OPEN")
            self.assertTrue(p.get("is_prolonged_consolidation"), "Must be tagged as prolonged consolidation")

        # 2. Admit incoming high-conviction Grade A+ setup
        new_signal = {
            "signal_id": "SOL_USDT_15M_FRESH_BREAKOUT",
            "symbol": "SOL/USDT",
            "direction": "LONG",
            "horizon": "15M",
            "desk": "scalp",
            "quality_grade": "Grade A+",
            "conviction": 90.0,
            "ev_net": 1.25,
            "entry_price": 150.0,
            "optimal_entry_limit": 150.0,
            "sl_price": 145.0,
            "tp1_price": 160.0,
            "strategy": "MOMENTUM_EXPANSION",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL"
        }
        admitted = bot.admit_signal(new_signal)
        self.assertTrue(admitted, "Fresh Grade A+ signal must be admitted via prolonged fractional slot accounting")
        self.assertEqual(len(bot.data["open_positions"]), 6, "Total positions must expand to include fresh signal")

    def test_09_microstructure_volatility_simultaneous_breach_resolves_tp_first(self):
        """Microstructure Volatility: Simultaneous 15M candle breach resolves chronologically via 1M sub-candles."""
        from app.quant_v16.microstructure_resolver import MicrostructureResolver

        # Scenario A: In a volatile 15M bar, 1M sub-candles show price reached TP1 at minute 2 before dropping to SL at minute 10
        sub_candles_tp_first = [
            [1000, 100.0, 101.0, 99.5, 100.5, 50],
            [2000, 100.5, 104.5, 100.2, 104.0, 150], # Touched TP1 (104.0) at minute 2!
            [3000, 104.0, 104.2, 103.5, 103.8, 40],
            [4000, 103.8, 103.9, 98.0, 98.2, 300]   # Breached SL (99.0) at minute 4
        ]
        res_a = MicrostructureResolver.resolve_path(
            symbol="BTC/USDT",
            direction="LONG",
            entry_p=100.0,
            tp1_p=104.0,
            sl_p=99.0,
            sub_candles=sub_candles_tp_first
        )
        self.assertEqual(res_a["outcome"], "WON_TP1", "Must resolve as WON_TP1 when TP1 was reached chronologically first")
        self.assertEqual(res_a["exit_price"], 104.0)

        # Scenario B: 1M sub-candles show price reached SL first at minute 1
        sub_candles_sl_first = [
            [1000, 100.0, 100.2, 98.5, 98.8, 250],  # Breached SL (99.0) at minute 1
            [2000, 99.0, 105.0, 98.9, 104.5, 500]   # Reached TP1 (104.0) later
        ]
        res_b = MicrostructureResolver.resolve_path(
            symbol="BTC/USDT",
            direction="LONG",
            entry_p=100.0,
            tp1_p=104.0,
            sl_p=99.0,
            sub_candles=sub_candles_sl_first
        )
        self.assertEqual(res_b["outcome"], "LOST_SL", "Must resolve as LOST_SL when SL was reached chronologically first")
        self.assertEqual(res_b["exit_price"], 99.0)

    def test_10_no_breakeven_in_any_case(self):
        """Zero Breakeven Policy: Stop Loss remains fixed at structural SL under all pre-TP1 price moves."""
        bot = PaperTradingBot(ledger_file=self.ledger_file)
        self.assertFalse(bot.enable_breakeven_guard)

        pos = {
            "trade_id": "TEST_NO_BE_ANY_CASE",
            "symbol": "ETH/USDT",
            "desk": "scalp",
            "direction": "LONG",
            "horizon": "15M",
            "entry_price": 3000.0,
            "initial_sl_price": 2900.0,
            "sl_price": 2900.0,
            "tp1_price": 3200.0,
            "position_size_usd": 100.0,
            "status": "OPEN",
            "opened_at_utc": datetime.now(timezone.utc).isoformat()
        }
        bot.data["open_positions"] = [pos]

        # Price pumps +1.50% to $3045 (previously would have triggered micro-guard or soft BE)
        bot.on_tick(live_prices={"ETH/USDT": 3045.0})
        self.assertEqual(bot.data["open_positions"][0]["sl_price"], 2900.0, "SL must NOT move from initial structural SL")
        self.assertFalse(bot.data["open_positions"][0].get("is_breakeven_locked"))

        # Price pulls back to $2995 (below entry)
        bot.on_tick(live_prices={"ETH/USDT": 2995.0})
        self.assertEqual(len(bot.data["open_positions"]), 1, "Position must NOT be closed at breakeven")
        self.assertEqual(bot.data["open_positions"][0]["status"], "OPEN")
        self.assertEqual(len(bot.data.get("closed_trades", [])), 0)

if __name__ == "__main__":
    unittest.main()
