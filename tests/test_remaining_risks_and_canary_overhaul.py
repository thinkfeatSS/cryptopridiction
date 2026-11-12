import unittest
import time
from datetime import datetime, timezone
from app.quant_v16.canary_execution import CanaryExecutionGate, CANARY_WHITELIST_BENCHMARKS
from app.quant_v16.entry_confirmation import EntryConfirmationEngine
from app.quant_v16.probability import ProbabilityCalibrator
from app.engine.execution.paper_trading_bot import PaperTradingBot

class TestRemainingRisksAndCanaryOverhaul(unittest.TestCase):
    def setUp(self):
        self.bot = PaperTradingBot(ledger_file="scratch/test_paper_ledger_canary_overhaul.json")
        self.bot.data = {
            "account_equity_usd": 1000.0,
            "open_positions": [],
            "closed_trades": [],
            "cancelled_orders": [],
            "desks": {
                "day": {"name": "Day Trading Desk", "allocated_usd": 350.0, "max_slots": 2, "active_slots": 0, "leverage": 3},
                "scalp": {"name": "High-Frequency Scalp Desk", "allocated_usd": 150.0, "max_slots": 2, "active_slots": 0, "leverage": 5},
                "swing": {"name": "Macro Swing Desk", "allocated_usd": 500.0, "max_slots": 2, "active_slots": 0, "leverage": 2}
            }
        }
        self.canary = CanaryExecutionGate(ledger_file="scratch/test_canary_ledger.json")
        self.canary.state = self.canary._load_or_initialize()
        self.canary.state["circuit_breaker_active"] = False
        self.canary.state["consecutive_losses"] = 0
        self.canary.state["realized_daily_pnl_usd"] = 0.0
        self.canary.state["realized_daily_pnl_pct"] = 0.0

    def test_01_macro_chop_boundary_harvest_admission_and_resting_preservation(self):
        """In low-volatility chop (CI > 61.8 / RANGE_SQUEEZE), boundary harvest setups are authorized while breakouts are throttled."""
        chop_shield_state = {
            "regime": "RANGE_SQUEEZE",
            "status_code": "NO_TRADE_ZONE",
            "is_ntz_active": True,
            "boundary_harvest_allowed": True,
            "reason": "Chop Equilibrium"
        }

        # 1. Blind breakout setup should be rejected
        breakout_signal = {
            "symbol": "BTC/USDT",
            "direction": "LONG",
            "entry_price": 70000.0,
            "tp1_price": 72000.0,
            "sl_price": 69000.0,
            "horizon": "15M",
            "canonical_strategy": "MOMENTUM_TREND_EXPANSION",
            "quality_grade": "Grade A+",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "is_range_boundary": False,
            "ev_net": 0.85
        }
        admitted_breakout = self.bot.admit_signal(breakout_signal, btc_shield_state=chop_shield_state)
        self.assertFalse(admitted_breakout, "Momentum breakout chasing must be blocked in chop equilibrium")

        # 2. Boundary mean-reversion setup should be authorized
        boundary_signal = {
            "symbol": "BTC/USDT",
            "direction": "LONG",
            "entry_price": 70000.0,
            "tp1_price": 71500.0,
            "sl_price": 69300.0,
            "horizon": "15M",
            "canonical_strategy": "RECTANGLE_HARVEST",
            "quality_grade": "Grade A+",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "is_range_boundary": True,
            "is_limit_pending": True,
            "optimal_entry_limit": 70000.0,
            "ev_net": 0.95
        }
        admitted_boundary = self.bot.admit_signal(boundary_signal, btc_shield_state=chop_shield_state)
        self.assertTrue(admitted_boundary, "Boundary harvest setup must be admitted during chop equilibrium")

        # 3. Resting boundary limit order must NOT be cancelled by chop NTZ on tick
        self.bot.on_tick(
            live_prices={"BTC/USDT": 70100.0},
            btc_shield_state=chop_shield_state
        )
        self.assertEqual(len(self.bot.data["open_positions"]), 1)
        self.assertEqual(self.bot.data["open_positions"][0]["status"], "RESTING_LIMIT")

    def test_02_sub_tick_gap_slippage_and_liquidity_sizing(self):
        """Micro-cap altcoin gaps through stop loss suffer realistic liquidity haircuts; sizing is pre-emptively damped."""
        # A. Pre-admission sizing dampening
        low_liq_signal = {
            "symbol": "XRP/USDT",
            "direction": "LONG",
            "entry_price": 2.00,
            "tp1_price": 2.20,
            "sl_price": 1.90,
            "horizon": "1H",
            "canonical_strategy": "MOMENTUM",
            "quality_grade": "Grade A",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "volume_24h_usd": 3_750_000.0, # 1/4 of $15M threshold -> sqrt(0.25) = 0.50x
            "ev_net": 0.80
        }
        admitted = self.bot.admit_signal(low_liq_signal)
        self.assertTrue(admitted, "Low liquidity signal should be admitted with damped size")
        pos = self.bot.data["open_positions"][-1]
        # Base allocated margin was $175, scaled by 0.50x -> ~$87.50, leverage 3 -> ~$262.50
        self.assertLessEqual(pos["position_size_usd"], 300.0)

        # B. Gap through stop loss
        pos["current_price"] = 1.80 # gapped through 1.90 SL down to 1.80 (-5.26% gap)
        self.bot.on_tick(live_prices={"XRP/USDT": 1.80})

        # Must be closed
        self.assertEqual(len(self.bot.data["open_positions"]), 0)
        closed = self.bot.data["closed_trades"][-1]
        self.assertEqual(closed["exit_reason"], "STOP_LOSS")
        # Exit price must be at or below 1.80 due to gap penetration and liquidity haircut
        self.assertLessEqual(closed["exit_price"], 1.80)

    def test_03_runner_fractional_slot_and_stagnation_recycling(self):
        """Runners consume only 0.25 slots; stagnant runners are harvested to admit fresh Grade A+ setups."""
        # Fill scalp desk with 1 active primary position and 1 active runner
        pos_runner = {
            "trade_id": "RUNNER_01",
            "symbol": "SOL/USDT",
            "direction": "LONG",
            "desk": "scalp",
            "status": "OPEN_TP1_LOCKED_BREAKEVEN",
            "tp1_hit": True,
            "entry_price": 150.0,
            "current_price": 156.0,
            "sl_price": 150.0,
            "initial_position_size_usd": 150.0,
            "remaining_position_size_usd": 75.0,
            "opened_at_utc": "2026-11-07T00:00:00+00:00" # > 2 hours ago (stagnant)
        }
        self.bot.data["open_positions"] = [pos_runner]
        self.bot.data["desks"]["scalp"]["max_slots"] = 1

        # Even with max_slots = 1, runner only uses 0.25 slots, so fresh primary signal can enter!
        new_signal = {
            "symbol": "ETH/USDT",
            "direction": "LONG",
            "entry_price": 2500.0,
            "tp1_price": 2600.0,
            "sl_price": 2450.0,
            "horizon": "15M",
            "canonical_strategy": "MOMENTUM",
            "quality_grade": "Grade A+",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "ev_net": 1.20
        }
        admitted = self.bot.admit_signal(new_signal)
        self.assertTrue(admitted, "Primary signal must be admitted via fractional runner slot accounting")

    def test_04_canary_execution_benchmark_whitelist_and_circuit_breakers(self):
        """Canary execution strictly approves benchmark assets (BTC, ETH, SOL) at 10% sizing and halts on circuit breakers."""
        # 1. Non-whitelist asset rejection
        non_wl_signal = {"symbol": "DOGE/USDT", "quality_grade": "Grade A"}
        appr, rsn, _ = self.canary.validate_canary_admission(non_wl_signal, "day")
        self.assertFalse(appr)
        self.assertIn("not in Canary benchmark whitelist", rsn)

        # 2. Benchmark asset approval
        btc_signal = {"symbol": "BTC/USDT", "quality_grade": "Grade A+"}
        appr, rsn, tel = self.canary.validate_canary_admission(btc_signal, "day")
        self.assertTrue(appr)
        self.assertEqual(tel["sizing_scale"], 0.10)

        # 3. High spread rejection
        appr, rsn, _ = self.canary.validate_canary_admission(btc_signal, "day", spread_bps=8.5)
        self.assertFalse(appr)
        self.assertIn("Spread", rsn)

        # 4. High feed latency rejection
        appr, rsn, _ = self.canary.validate_canary_admission(btc_signal, "day", tick_latency_ms=450.0)
        self.assertFalse(appr)
        self.assertIn("latency", rsn)

        # 5. Consecutive loss circuit breaker (3 losses)
        for i in range(3):
            self.canary.record_canary_trade_outcome(f"T{i}", "BTC/USDT", "LONG", 10.0, -0.50, -5.0, False, "STOP_LOSS")
        self.assertTrue(self.canary.state["circuit_breaker_active"])
        appr, rsn, _ = self.canary.validate_canary_admission(btc_signal, "day")
        self.assertFalse(appr)
        self.assertIn("CONSECUTIVE_LOSS_LIMIT_REACHED", rsn)

    def test_05_hyper_volatile_latency_adaptive_blowout_guard(self):
        """Blowout threshold dynamically tightens from 1.20% down to 0.60% when latency exceeds 350ms, and cancels at 2000ms."""
        pos = {
            "trade_id": "TEST_BLOWOUT_LATENCY",
            "symbol": "BTC/USDT",
            "direction": "LONG",
            "status": "RESTING_LIMIT",
            "is_limit_resting": True,
            "entry_price": 50000.0,
            "optimal_entry_limit": 50000.0,
            "current_price": 50000.0,
            "desk": "day",
            "opened_at_utc": datetime.now(timezone.utc).isoformat()
        }
        self.bot.data["open_positions"] = [pos]

        # A. At 2000ms latency, extreme network blackout safety engages immediately
        self.bot.on_tick(live_prices={"BTC/USDT": 50000.0}, tick_latency_ms=2100.0)
        self.assertEqual(len(self.bot.data["open_positions"]), 0)
        self.assertEqual(self.bot.data["cancelled_orders"][0]["cancellation_reason"], "CANCELLED_NETWORK_BLACKOUT_SAFETY")

    def test_06_synthetic_microstructure_estimator_fallback(self):
        """When order book depth is lagged or absent, synthetic taker flow confirms resting limit fills."""
        # High taker buy ratio (0.65) and positive CVD surge (+0.30) synthesize positive OBI
        is_conf, rsn, tel = EntryConfirmationEngine.validate_resting_limit_fill(
            direction="LONG",
            limit_price=50000.0,
            current_price=49990.0,
            depth_data={"latency_ms": 500.0}, # lagged depth
            candle_metrics={"taker_buy_ratio": 0.65, "cvd_surge_5": 0.30}
        )
        self.assertTrue(is_conf)
        self.assertEqual(tel["fill_confirmation_type"], "SYNTHETIC_MICROSTRUCTURE_CONFIRMED")
        self.assertGreater(tel["obi_5"], 0.20)

    def test_07_probability_calibration_platt(self):
        """Verifies Platt calibration eliminates uncalibrated overconfidence and bounds probabilities."""
        calibrator = ProbabilityCalibrator(method="platt")
        raw_prob = 0.90
        cal_prob = calibrator.calibrate(raw_prob)
        self.assertLess(cal_prob, raw_prob, "Extreme raw probabilities must be calibrated towards empirical frequency")
        self.assertGreaterEqual(cal_prob, 0.05)
        self.assertLessEqual(cal_prob, 0.95)

    def test_08_low_volatility_chop_boundary_rr_feasibility_rejection(self):
        """In chop (CI > 61.8), boundary setups with sub-hurdle R:R (< 1.35) or EV (< 0.25%) are strictly vetoed."""
        high_chop_shield = {
            "regime": "RANGE",
            "status_code": "RANGE",
            "is_ntz_active": False,
            "chop_index": 65.2, # > 61.8 market congestion
            "boundary_harvest_allowed": True
        }

        # Sub-hurdle R:R setup: Entry 100, TP1 101, SL 99 -> R:R = 1.0 < 1.35
        sub_rr_signal = {
            "symbol": "BTC/USDT",
            "direction": "LONG",
            "entry_price": 100.0,
            "tp1_price": 101.0,
            "sl_price": 99.0,
            "horizon": "15M",
            "canonical_strategy": "RECTANGLE_BOUNDARY",
            "quality_grade": "Grade A+",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "is_range_boundary": True,
            "ev_net": 0.50
        }
        admitted = self.bot.admit_signal(sub_rr_signal, btc_shield_state=high_chop_shield)
        self.assertFalse(admitted, "Boundary setup with R:R < 1.35 must be vetoed during macro chop")

        # Qualified R:R setup: Entry 100, TP1 103, SL 98 -> R:R = 1.50 >= 1.35, EV = 0.65%
        ok_signal = {
            "symbol": "BTC/USDT",
            "direction": "LONG",
            "entry_price": 100.0,
            "tp1_price": 103.0,
            "sl_price": 98.0,
            "horizon": "15M",
            "canonical_strategy": "RECTANGLE_BOUNDARY",
            "quality_grade": "Grade A+",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "is_range_boundary": True,
            "ev_net": 0.65
        }
        admitted_ok = self.bot.admit_signal(ok_signal, btc_shield_state=high_chop_shield)
        self.assertTrue(admitted_ok, "Boundary setup with R:R >= 1.35 and EVnet >= 0.25% must be admitted during chop")

    def test_09_low_volume_order_flow_spike_filtering_and_multi_factor_confluence(self):
        """On low-liquidity pairs, transient single-metric taker noise is filtered out; multi-factor confluence executes."""
        bot = PaperTradingBot(ledger_file="scratch/test_low_vol_ledger.json")
        bot.data = {
            "open_positions": [], "closed_trades": [], "cancelled_orders": [],
            "desks": {"scalp": {"name": "Scalp Desk", "allocated_usd": 150.0, "max_slots": 1, "active_slots": 0, "leverage": 2}}
        }

        # Low-volume token setup: Volume $1.2M < $5.0M
        low_vol_signal = {
            "signal_id": "TEST_LOW_VOL_COIN",
            "symbol": "MICRO/USDT",
            "desk": "scalp",
            "horizon": "15M",
            "direction": "LONG",
            "quality_grade": "Grade A+",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "entry_price": 10.0,
            "tp1_price": 11.0, # TP span = 1.0
            "tp2_price": 11.5,
            "sl_price": 9.5,
            "volume_24h_usd": 1_200_000.0,
            "ev_net": 0.80
        }
        admitted = bot.admit_signal(low_vol_signal)
        self.assertTrue(admitted)

        # 1. Price reaches 80% progress ($10.80) with ONLY single-metric adverse CVD (-0.18), but depth OBI is flat (0.0)
        single_cvd_noise = {"MICRO/USDT": {"cvd_surge": -0.18}}
        bot.on_tick({"MICRO/USDT": 10.80}, cvd_metrics=single_cvd_noise)
        pos = bot.data["open_positions"][0]
        self.assertFalse(pos.get("is_tp_harvested_early", False), "Single-metric taker spike on low-volume pair must NOT trigger false harvest")
        self.assertTrue(pos.get("transient_order_flow_spike_deferred", False))

        # 2. Confluent 2-factor resistance: CVD (-0.22) AND heavy Ask Wall OBI (-0.45)
        confluent_depth = {"MICRO/USDT": {"bids": [[10.79, 100]], "asks": [[10.81, 500]]}} # OBI = (100-500)/600 = -0.66
        confluent_cvd = {"MICRO/USDT": {"cvd_surge": -0.22}}
        bot.on_tick({"MICRO/USDT": 10.80}, cvd_metrics=confluent_cvd, order_book_depths=confluent_depth)
        pos = bot.data["open_positions"][0]
        self.assertTrue(pos.get("is_tp_harvested_early"), "Confluent multi-factor resistance on low-volume pair MUST trigger early harvest")
        self.assertEqual(pos.get("tp_harvest_reason"), "TAKE_PROFIT_1_HARVEST_EXHAUSTION")

    def test_10_canary_circuit_breaker_recovery_protocol_and_24h_reset(self):
        """Verifies Canary Circuit Breaker recovery via 24h reset window and operator reset."""
        # Trip breaker via 3 consecutive losses
        for i in range(3):
            self.canary.record_canary_trade_outcome(f"LOSS_{i}", "BTC/USDT", "LONG", 10.0, -0.60, -6.0, False, "STOP_LOSS")
        self.assertTrue(self.canary.state["circuit_breaker_active"])
        self.assertEqual(self.canary.state["consecutive_losses"], 3)

        # A. Immediate reset attempt during flash dump is rejected
        flash_dump_shield = {"regime": "FLASH_DUMP", "status_code": "BEAR_CASCADE_BLACKOUT", "reason": "Acute sell-off"}
        res, msg = self.canary.reset_circuit_breaker(manual=True, force=False, btc_shield_state=flash_dump_shield)
        self.assertFalse(res)
        self.assertTrue(self.canary.state["circuit_breaker_active"])

        # B. Manual operator reset under normalized volatility succeeds
        normal_shield = {"regime": "NORMAL", "status_code": "NORMAL", "reason": "Stable"}
        res, msg = self.canary.reset_circuit_breaker(manual=True, force=False, btc_shield_state=normal_shield)
        self.assertTrue(res)
        self.assertFalse(self.canary.state["circuit_breaker_active"])
        self.assertEqual(self.canary.state["consecutive_losses"], 0)

        # C. 24-hour reset window autonomous recovery
        # Re-trip breaker
        for i in range(3):
            self.canary.record_canary_trade_outcome(f"LOSS2_{i}", "ETH/USDT", "SHORT", 10.0, -0.60, -6.0, False, "STOP_LOSS")
        self.assertTrue(self.canary.state["circuit_breaker_active"])

        # Mock tripped_at to 25 hours ago
        tripped_25h_ago = datetime.fromtimestamp(time.time() - 90000, tz=timezone.utc).isoformat()
        self.canary.state["circuit_breaker_tripped_at"] = tripped_25h_ago

        # check_and_reset_daily should automatically lift circuit breaker once 24h has elapsed
        self.canary.check_and_reset_daily(btc_shield_state=normal_shield)
        self.assertFalse(self.canary.state["circuit_breaker_active"], "24h reset window must automatically recover Canary gate")
        self.assertEqual(self.canary.state["consecutive_losses"], 0)

if __name__ == "__main__":
    unittest.main()
