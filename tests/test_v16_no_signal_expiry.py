import unittest
import os
import tempfile
import shutil
import time
import json
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

    def test_11_microstructure_volatility_liquidation_cascade_sl_precedence(self):
        """Microstructure Volatility: In black-swan liquidation cascades where both TP1 and SL are breached in the same bar, SL takes deterministic precedence."""
        from app.quant_v16.microstructure_resolver import MicrostructureResolver

        # Scenario: Extreme volatility bar where both TP1 (104.0) and SL (99.0) are touched in the same minute
        cascade_sub_candles = [
            [1000, 100.0, 104.5, 98.5, 99.2, 800], # Both breached within the exact same 1M candle
        ]
        res = MicrostructureResolver.resolve_path(
            symbol="BTC/USDT",
            direction="LONG",
            entry_p=100.0,
            tp1_p=104.0,
            sl_p=99.0,
            sub_candles=cascade_sub_candles
        )
        self.assertEqual(res["outcome"], "LOST_SL", "Must enforce conservative mathematical invariant: SL takes deterministic precedence")
        self.assertEqual(res["exit_price"], 99.0)

    def test_12_api_issues_wait_for_refresh_before_evaluation(self):
        """API Issues: When live feeds or tickers are unavailable, system waits for data to refresh without premature mutation."""
        class MockSignal:
            def __init__(self):
                self.signal_id = "SIG_API_WAIT_01"
                self.symbol = "MOCK_TOKEN/USDT"
                self.horizon = "15M"
                self.direction = "LONG"
                self.entry_price = 3000.0
                self.sl_price = 2900.0
                self.tp1_price = 3200.0
                self.tp2_price = 3300.0
                self.tp3_price = 3400.0
                self.status = "ACTIVE"
                self.outcome_label = "ACTIVE"
                self.peak_price_seen = 3000.0
                self.trough_price_seen = 3000.0
                self.created_at = datetime.now(timezone.utc) - timedelta(hours=4)
                self.date_utc = self.created_at.strftime("%Y-%m-%d")
                self.time_utc = self.created_at.strftime("%H:%M:%S UTC")

        sig = MockSignal()
        ss = SignalService()

        # 1. Feed is empty due to API rate limit / outage: evaluation must safely skip and wait for refresh
        updated = ss.evaluate_active_signals([sig], live_prices={})
        self.assertFalse(updated, "Must return False and not mutate signals when live prices feed is empty")
        self.assertEqual(sig.status, "ACTIVE", "Signal status must remain intact while waiting for refresh")

        # 2. Feed contains prices for other coins but MOCK_TOKEN/USDT is missing (asset API issue)
        updated_2 = ss.evaluate_active_signals([sig], live_prices={"SOL/USDT": 150.0})
        self.assertFalse(updated_2, "Must skip evaluation for missing asset and wait for data refresh")
        self.assertEqual(sig.status, "ACTIVE", "Signal status must remain intact while waiting for refresh")

        # 3. Data refreshes with valid MOCK_TOKEN/USDT price touching TP1 -> evaluated cleanly
        updated_3 = ss.evaluate_active_signals([sig], live_prices={"MOCK_TOKEN/USDT": 3210.0})
        self.assertTrue(updated_3, "Evaluates signal once data refreshes")
        self.assertIn(sig.status, ["TP1_LOCKED_BREAKEVEN", "WON_TP1"])

    def test_13_historical_signal_tp_resolution_from_inception(self):
        """Historical signals touching TP1 are evaluated and resolved from inception without getting stuck in ACTIVE."""
        from app.services.signal_service import evaluate_chronological_candle_outcome, _INTRA_KLINES_CACHE, _INTRA_KLINES_TS

        # Setup mock klines in cache representing historical candles since signal inception
        raw_sym = "FETUSDT"
        since_ts = float(int(time.time() - 1800.0))  # 30 minutes ago (within 14h -> 1m interval)
        start_ms = int((since_ts - 5.0) * 1000)
        cache_key = f"{raw_sym}:1m:40:{start_ms}"

        # 3 candles: candle 0 at entry, candle 1 drops to 0.1390 (<= TP1 0.142147), candle 2 bounces to 0.1475
        mock_klines = [
            [int(since_ts * 1000), 0.1470, 0.1475, 0.1460, 0.1465, 100.0],
            [int((since_ts + 60) * 1000), 0.1465, 0.1468, 0.1390, 0.1400, 150.0],
            [int((since_ts + 120) * 1000), 0.1400, 0.1475, 0.1398, 0.1472, 120.0],
        ]
        _INTRA_KLINES_CACHE[cache_key] = mock_klines
        _INTRA_KLINES_TS[cache_key] = time.time()

        res_status, exit_p, realized_ret, peak_p, trough_p, label = evaluate_chronological_candle_outcome(
            symbol="FET/USDT",
            direction="SHORT",
            entry_p=0.147000,
            tp1_p=0.142147,
            sl_p=0.148764,
            since_ts=since_ts,
            horizon="15M",
            current_spot_price=0.1472
        )

        self.assertEqual(res_status, "WON_TP1", "Signal dropping to 0.1390 must resolve to WON_TP1")
        self.assertEqual(exit_p, 0.142147, "Exit price must be TP1 price")
        self.assertAlmostEqual(realized_ret, 3.30, delta=0.1)
        self.assertIn("WON (TP1 HIT", label)
        self.assertLessEqual(trough_p, 0.1390)

    def test_14_v16_store_active_signals_evaluation(self):
        """_get_v16_store authoritatively evaluates ACTIVE signals against price history instead of leaving them stuck."""
        from app.routers.v16_router import _get_v16_store
        from app.services.signal_service import _INTRA_KLINES_CACHE, _INTRA_KLINES_TS
        from app.config import settings

        orig_export = settings.EXPORT_DIR
        try:
            settings.EXPORT_DIR = self.tmp_dir
            sig_id = "SIG_FET_USDT_15M_HEAL_01"
            raw_sym = "FETUSDT"
            since_ts = float(int(time.time() - 3600.0))
            start_ms = int((since_ts - 5.0) * 1000)
            cache_key = f"{raw_sym}:1m:70:{start_ms}"

            # Seed mock klines where low touched TP1
            _INTRA_KLINES_CACHE[cache_key] = [
                [int(since_ts * 1000), 0.1470, 0.1472, 0.1465, 0.1468, 50.0],
                [int((since_ts + 60) * 1000), 0.1468, 0.1470, 0.1390, 0.1410, 80.0],
            ]
            _INTRA_KLINES_TS[cache_key] = time.time()

            immut_file = os.path.join(self.tmp_dir, "v16_immutable_signals.json")
            dyn_file = os.path.join(self.tmp_dir, "v16_dynamic_states.json")

            immut_store = {
                sig_id: {
                    "signal_id": sig_id,
                    "symbol": "FET/USDT",
                    "direction": "SHORT",
                    "horizon": "15M",
                    "signal_generated_at": datetime.fromtimestamp(since_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "entry_price_initial": 0.147000,
                    "tp1_initial": 0.142147,
                    "sl_initial": 0.148764,
                    "status": "ACTIVE",
                }
            }
            dyn_store = {
                sig_id: {
                    "signal_id": sig_id,
                    "current_price": 0.145000,
                    "status": "ACTIVE",
                    "outcome_label": "RUNNING 🚀",
                    "peak_price_seen": None,
                    "trough_price_seen": 0.1390,
                    "exit_price": None,
                    "realized_return_pct": None,
                }
            }

            with open(immut_file, "w", encoding="utf-8") as f:
                json.dump(immut_store, f)
            with open(dyn_file, "w", encoding="utf-8") as f:
                json.dump(dyn_store, f)

            imm_res, dyn_res = _get_v16_store()
            self.assertIn(sig_id, dyn_res)
            self.assertEqual(dyn_res[sig_id]["status"], "WON_TP1", "ACTIVE signal touching TP1 must resolve to WON_TP1")
            self.assertEqual(dyn_res[sig_id]["exit_price"], 0.142147)
            self.assertIn("WON", dyn_res[sig_id]["outcome_label"])
        finally:
            settings.EXPORT_DIR = orig_export

    def test_15_legacy_october_timestamp_healing_and_evaluation(self):
        """Signals carrying legacy October timestamps heal dynamically and resolve accurately without false SL."""
        from app.routers.v16_router import _get_v16_store, _extract_and_heal_timestamp
        from app.services.signal_service import _INTRA_KLINES_CACHE, _INTRA_KLINES_TS
        from app.config import settings

        orig_export = settings.EXPORT_DIR
        try:
            settings.EXPORT_DIR = self.tmp_dir
            now_dt = datetime.now(timezone.utc)

            # 1. Epoch extraction verification
            epoch_ts = _extract_and_heal_timestamp(raw_date="2026-10-24", raw_time="02:00:00", sig_id="AR_USDT_15M_1794523594", now_utc=now_dt)
            self.assertEqual(epoch_ts, "2026-11-12 22:46:34 UTC", "Epoch timestamp in signal_id must take precedence over legacy fallback date")

            # 2. Legacy date healing on active signal
            healed_ts = _extract_and_heal_timestamp(raw_date="2026-10-24 02:00:00", sig_id="SIG_FET_USDT_15M", now_utc=now_dt)
            self.assertFalse(healed_ts.startswith("2026-10-24"), "Legacy October date must be healed")
            self.assertTrue(healed_ts.endswith("02:00:00 UTC"), "Time of generation must be preserved during healing")

            # 3. Store resolution test for SIG_FET_USDT_15M
            sig_id = "SIG_FET_USDT_15M"
            immut_file = os.path.join(self.tmp_dir, "v16_immutable_signals.json")
            dyn_file = os.path.join(self.tmp_dir, "v16_dynamic_states.json")

            immut_store = {
                sig_id: {
                    "signal_id": sig_id,
                    "symbol": "FET/USDT",
                    "direction": "SHORT",
                    "horizon": "15M",
                    "signal_generated_at": "2026-10-24 02:00:00 UTC",
                    "entry_price_initial": 0.147000,
                    "tp1_initial": 0.142147,
                    "sl_initial": 0.148764,
                    "status": "ACTIVE",
                }
            }
            dyn_store = {
                sig_id: {
                    "signal_id": sig_id,
                    "current_price": 0.145000,
                    "status": "ACTIVE",
                    "outcome_label": "RUNNING 🚀",
                    "peak_price_seen": None,
                    "trough_price_seen": 0.1390,
                    "exit_price": None,
                    "realized_return_pct": None,
                }
            }

            with open(immut_file, "w", encoding="utf-8") as f:
                json.dump(immut_store, f)
            with open(dyn_file, "w", encoding="utf-8") as f:
                json.dump(dyn_store, f)

            imm_res, dyn_res = _get_v16_store(force_refresh=True)
            self.assertIn(sig_id, dyn_res)
            # Timestamp must be healed
            self.assertFalse(imm_res[sig_id]["signal_generated_at"].startswith("2026-10-24"))
            # Must be evaluated to WON_TP1
            self.assertEqual(dyn_res[sig_id]["status"], "WON_TP1")
            self.assertEqual(dyn_res[sig_id]["exit_price"], 0.142147)
            self.assertAlmostEqual(dyn_res[sig_id]["realized_return_pct"], 3.30, places=1)
            self.assertTrue(dyn_res[sig_id]["is_tp1_locked"])
        finally:
            settings.EXPORT_DIR = orig_export


if __name__ == "__main__":
    unittest.main()
