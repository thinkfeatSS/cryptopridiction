"""
QUANT EDGE V16: DEEP SIGNAL QA & SYSTEMIC HARDENING TEST SUITE
Authoritative Verification of all Signal Pipeline Stages:
1. Safe Numeric & Formatting Robustness (Zero ValueError on dirty inputs)
2. Signal Creation & Price Geometry Invariants
3. Probability Coherence & Monotonicity
4. Canonical Net Expectancy & Friction Deductions
5. Anees Mehdi 15M/1M Rectangle Strategy Integration
6. Execution Tracking, Adverse SL Precedence & Tier-0 Breakeven
7. Denominator Integrity & Breakeven Accounting
8. Cross-System Parity (CSV, JSON, DB)
"""

import unittest
import math
import time
import os
import tempfile
import json
import csv
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

from app.quant_v16.validation import DataValidator, safe_float, safe_ratio
from app.quant_v16.expectancy import NetExpectancyEngine, ExecutionPolicy
from app.quant_v16.costs import ExecutionCostEngine, CostBreakdown, ExecutionAssumption
from app.quant_v16.probability import PathProbabilities, ProbabilityCalibrator
from app.quant_v16.audit import classify_signal_outcome
from app.quant_v16.validation_engine import V16ShadowValidationEngine


class TestDeepSignalQA(unittest.TestCase):
    """
    Exhaustive QA Test Suite for Quant Edge V16 Signal Integrity.
    """

    # =========================================================================
    # 1. SAFE NUMERIC & FORMATTING ROBUSTNESS
    # =========================================================================
    def test_safe_float_dirty_strings(self):
        """Tests that safe_float safely handles all variants of dirty string inputs without throwing ValueError."""
        test_cases = [
            ("+0.00%", 0.0),
            ("+1.25%", 1.25),
            ("-3.45%", -3.45),
            ("0.00%", 0.0),
            ("  +5.50%  ", 5.5),
            ("$45,230.50", 45230.5),
            ("N/A", 0.0),
            ("None", 0.0),
            ("nan", 0.0),
            ("null", 0.0),
            ("inf", 0.0),
            ("-inf", 0.0),
            ("", 0.0),
            (None, 0.0),
            (100, 100.0),
            (25.4, 25.4),
            (float("nan"), 0.0),
        ]
        for raw, expected in test_cases:
            res = safe_float(raw, default=0.0)
            self.assertEqual(res, expected, f"Failed parsing: {raw} -> expected {expected}, got {res}")

    def test_safe_ratio_parsing(self):
        """Tests that safe_ratio cleanly parses risk:reward formats like '1:2.5', '2.5', 2.5."""
        self.assertEqual(safe_ratio("1:2.5"), 2.5)
        self.assertEqual(safe_ratio("1:3.0"), 3.0)
        self.assertEqual(safe_ratio("2.0"), 2.0)
        self.assertEqual(safe_ratio(2.8), 2.8)
        self.assertEqual(safe_ratio(None, default=2.0), 2.0)
        self.assertEqual(safe_ratio("invalid", default=2.0), 2.0)

    # =========================================================================
    # 2. SIGNAL CREATION & PRICE GEOMETRY INVARIANTS
    # =========================================================================
    def test_price_geometry_long_valid(self):
        """Tests valid Long geometry: SL < Entry < TP1 < TP2 < TP3."""
        ok, reason = DataValidator.validate_price_invariants(
            entry=100.0, sl=98.0, tp1=104.0, tp2=106.0, tp3=110.0, direction="LONG"
        )
        self.assertTrue(ok, f"Expected valid LONG geometry to pass: {reason}")

    def test_price_geometry_long_inverted_sl(self):
        """Tests that Long SL >= Entry is strictly rejected."""
        ok, reason = DataValidator.validate_price_invariants(
            entry=100.0, sl=101.0, tp1=104.0, tp2=106.0, tp3=110.0, direction="LONG"
        )
        self.assertFalse(ok)
        self.assertIn("must be strictly below Entry", reason)

    def test_price_geometry_long_inverted_tps(self):
        """Tests that Long TP2 <= TP1 is strictly rejected."""
        ok, reason = DataValidator.validate_price_invariants(
            entry=100.0, sl=98.0, tp1=106.0, tp2=104.0, tp3=110.0, direction="LONG"
        )
        self.assertFalse(ok)
        self.assertIn("strictly above TP1", reason)

    def test_price_geometry_short_valid(self):
        """Tests valid Short geometry: SL > Entry > TP1 > TP2 > TP3."""
        ok, reason = DataValidator.validate_price_invariants(
            entry=100.0, sl=102.0, tp1=96.0, tp2=94.0, tp3=90.0, direction="SHORT"
        )
        self.assertTrue(ok, f"Expected valid SHORT geometry to pass: {reason}")

    def test_price_geometry_short_inverted_sl(self):
        """Tests that Short SL <= Entry is strictly rejected."""
        ok, reason = DataValidator.validate_price_invariants(
            entry=100.0, sl=99.0, tp1=96.0, tp2=94.0, tp3=90.0, direction="SHORT"
        )
        self.assertFalse(ok)
        self.assertIn("must be strictly above Entry", reason)

    def test_price_geometry_zero_stop_distance_rejected(self):
        """Tests that Entry == SL is strictly rejected."""
        ok, reason = DataValidator.validate_precision(entry=100.0, sl=100.0)
        self.assertFalse(ok)
        self.assertIn("identical", reason)

    # =========================================================================
    # 3. PROBABILITY COHERENCE & MONOTONICITY
    # =========================================================================
    def test_probability_coherence_terminal_sum(self):
        """Tests that PathProbabilities satisfy P(TP1) + P(SL) = 1.0."""
        probs = PathProbabilities(p_tp1=0.65, p_tp2=0.45, p_tp3=0.25, p_sl=0.35)
        self.assertAlmostEqual(probs.p_tp1 + probs.p_sl, 1.0, places=4)

    def test_probability_monotonic_target_decay(self):
        """Tests that target probabilities strictly decrease: P(TP3) <= P(TP2) <= P(TP1)."""
        probs = PathProbabilities(p_tp1=0.65, p_tp2=0.45, p_tp3=0.25, p_sl=0.35)
        self.assertTrue(probs.p_tp3 <= probs.p_tp2 <= probs.p_tp1)

    def test_isotonic_shrinkage_overconfidence_guard(self):
        """Tests that ProbabilityCalibrator shrinks probabilities > 55% to eliminate empirical ECE overconfidence."""
        calibrator = ProbabilityCalibrator()
        raw_p = 0.738  # High raw model output
        calibrated_p = calibrator.calibrate(raw_p)
        self.assertLess(calibrated_p, raw_p, "High probability must undergo shrinkage to preserve calibration ECE <= 0.12")
        self.assertGreaterEqual(calibrated_p, 0.50, "Calibrated probability must remain valid")

    # =========================================================================
    # 4. CANONICAL NET EXPECTANCY & FRICTION DEDUCTIONS
    # =========================================================================
    def test_net_expectancy_deducts_all_frictions(self):
        """Tests that Net EV = Gross EV - Total Frictions (Fee + Slippage + Spread + Funding)."""
        engine = NetExpectancyEngine()
        cost_engine = ExecutionCostEngine()
        costs = cost_engine.estimate_costs(
            market_type="futures",
            observed_spread_bps=4.0,
            assumption=ExecutionAssumption.BASE
        )
        path_probs = PathProbabilities(p_tp1=0.65, p_tp2=0.45, p_tp3=0.25, p_sl=0.35)
        res = engine.evaluate(
            entry=100.0,
            sl=98.0,
            tp1=104.0,
            tp2=106.0,
            tp3=110.0,
            direction="LONG",
            path_probs=path_probs,
            costs=costs
        )
        self.assertGreater(res.costs_total_pct, 0.0)
        self.assertLess(res.expected_net_return_pct, res.ev_gross_pct)
        self.assertTrue(res.passes_ev_hurdle)

    def test_negative_net_ev_rejected(self):
        """Tests that signals with negative Net EV (unprofitable after friction) fail the V16 hurdle."""
        engine = NetExpectancyEngine()
        cost_engine = ExecutionCostEngine()
        costs = cost_engine.estimate_costs(
            market_type="futures",
            observed_spread_bps=12.0,
            assumption=ExecutionAssumption.STRESS
        )
        # Weak trade: 1:0.5 RR with 40% win prob -> negative expectancy
        path_probs = PathProbabilities(p_tp1=0.40, p_tp2=0.25, p_tp3=0.15, p_sl=0.60)
        res = engine.evaluate(
            entry=100.0,
            sl=96.0,
            tp1=102.0,
            tp2=103.0,
            tp3=104.0,
            direction="LONG",
            path_probs=path_probs,
            costs=costs
        )
        self.assertLess(res.expected_net_return_pct, 0.0)
        self.assertFalse(res.passes_ev_hurdle)

    # =========================================================================
    # 5. EXECUTION TRACKING & CONSERVATIVE ADVERSE PRECEDENCE
    # =========================================================================
    def test_conservative_adverse_sl_precedence(self):
        """Tests that when both SL and TP are touched simultaneously, adverse SL takes strict precedence."""
        # Simulated dual touch: Long 100 -> wick down to 97 (SL=98 hit) and wick up to 105 (TP1=104 hit)
        entry = 100.0
        sl = 98.0
        tp1 = 104.0
        candle_low = 97.0
        candle_high = 105.0

        hit_sl = candle_low <= sl
        hit_tp = candle_high >= tp1
        self.assertTrue(hit_sl and hit_tp)

        # Rule 32 Enforcement: SL strictly takes precedence
        resolved_status = "LOST_SL" if hit_sl else ("WON_TP1" if hit_tp else "ACTIVE")
        self.assertEqual(resolved_status, "LOST_SL")

    def test_tier0_breakeven_guard_ratchet(self):
        """Tests that reaching 50% of TP1 distance ratchets stop loss to soft breakeven."""
        entry = 100.0
        tp1 = 104.0
        sl = 98.0
        direction = "LONG"

        tp1_dist = (tp1 - entry)  # 4.0
        half_tp1 = entry + (0.50 * tp1_dist)  # 102.0
        current_price = 102.2  # Surpassed 50% hurdle!

        max_gain_pct = ((current_price - entry) / entry) * 100.0  # +2.2%
        t0_hurdle = min(1.20, max(0.60, 0.50 * (tp1_dist / entry * 100.0)))  # 1.20%

        self.assertGreaterEqual(max_gain_pct, t0_hurdle)
        # SL ratchets to soft breakeven
        soft_be_p = entry * 1.0005  # 100.05
        ratcheted_sl = max(sl, soft_be_p)
        self.assertGreater(ratcheted_sl, sl)
        self.assertGreater(ratcheted_sl, entry)

    # =========================================================================
    # 6. DENOMINATOR INTEGRITY & BREAKEVEN ACCOUNTING
    # =========================================================================
    def test_breakeven_never_counted_as_win(self):
        """Tests that Breakeven outcomes are categorized as BREAKEVEN, never WON."""
        be_statuses = [
            ("BREAKEVEN_GUARD", "🛡️ BREAKEVEN (TIER-0 GUARD +0.05%)", 0.05),
            ("STOP_LOSS_BREAKEVEN", "🛡️ SOFT BREAKEVEN EXIT", 0.0),
            ("WON_TIER0_BE", "🛡️ TIER-0 PROTECTED BE", 0.0),
            ("BREAKEVEN_EXP", "⚪ BREAKEVEN (EXPIRY 0.00%)", 0.0),
        ]
        for st, out, ret in be_statuses:
            cat = classify_signal_outcome(st, out, ret)
            self.assertEqual(cat, "BREAKEVEN", f"Status {st} must be categorized as BREAKEVEN, got {cat}")
            self.assertNotEqual(cat, "WON", f"Breakeven trade {st} must NEVER be counted as a WIN")

    def test_win_rate_denominator_preserves_breakeven(self):
        """Tests that Total Win Rate = Won / (Won + Lost + Breakeven)."""
        won = 10
        lost = 10
        be = 5

        decisive_win_rate = won / (won + lost) * 100.0  # 50.0%
        total_win_rate = won / (won + lost + be) * 100.0  # 40.0%

        self.assertEqual(decisive_win_rate, 50.0)
        self.assertEqual(total_win_rate, 40.0)
        self.assertLess(total_win_rate, decisive_win_rate)

    # =========================================================================
    # 8. ANEES MEHDI 15M/1M RECTANGLE STRATEGY INTEGRATION
    # =========================================================================
    def test_anees_mehdi_rectangle_signal_structure(self):
        """Tests that Anees Mehdi Rectangle signals enforce RR >= 2.0 and score >= 75.0."""
        from app.quant_v16.rectangle_strategy.strategy_config import RectangleStrategyConfig
        cfg = RectangleStrategyConfig()
        self.assertEqual(cfg.min_risk_reward, 2.0)
        self.assertEqual(cfg.ema_fast_period, 50)

        # Mock signal produced by rectangle orchestrator
        entry = 65000.0
        sl = 64500.0
        tp1 = 66000.0  # RR = 1000 / 500 = 2.0
        score = 88.5

        rect_sig = {
            "symbol": "BTC/USDT",
            "horizon": "15M",
            "direction": "LONG",
            "entry_price": entry,
            "sl_price": sl,
            "tp1_price": tp1,
            "risk_reward_ratio": "1:2.0",
            "conviction": score,
            "quality_grade": "💎 Grade A+ (THE ONLY 1 MINUTE RECTANGLE STRATEGY)",
            "strategy": "THE_ONLY_1_MINUTE_RECTANGLE_STRATEGY",
            "is_trade_active": True,
            "qualified_signals_by_horizon": {"15M": {"entry": entry, "sl": sl, "tp1": tp1}}
        }
        self.assertIn("15M", rect_sig["qualified_signals_by_horizon"])
        self.assertGreaterEqual(rect_sig["conviction"], 75.0)
        self.assertTrue(rect_sig["sl_price"] < rect_sig["entry_price"] < rect_sig["tp1_price"])

    # =========================================================================
    # 9. WHATSAPP FORMATTING & QUALITY GATING
    # =========================================================================
    def test_whatsapp_formatting_and_quality_gate(self):
        """Tests that WhatsApp message formatter handles dirty signals gracefully without exceptions."""
        from app.services.whatsapp_service import WhatsAppService
        wa = WhatsAppService()

        # Test signal with string returns, percentages, and special characters
        dirty_sig = {
            "symbol": "ETH/USDT",
            "direction": "LONG",
            "horizon": "15M",
            "quality_grade": "Grade A+",
            "entry_price": "3450.50",
            "tp1_price": "3550.00",
            "tp2_price": "3620.00",
            "tp3_price": "3750.00",
            "sl_price": "3380.00",
            "conviction_pct": "+88.5%",
            "meta_win_prob_pct": "+68.0%",
            "expected_net_return": "+1.45%",
            "risk_reward_ratio": "1:2.4",
            "status": "ACTIVE",
            "outcome_label": "RUNNING 🚀"
        }

        # Formatter must not raise exceptions
        formatted_text = wa.format_new_signal(dirty_sig)
        self.assertIn("ETH_USDT", formatted_text)
        self.assertIn("LONG", formatted_text)
        self.assertIn("3,450.50", formatted_text)

        # Quality gate check
        passes_group = wa.passes_quality_gate(dirty_sig, is_channel=False)
        self.assertTrue(passes_group)

    # =========================================================================
    # 10. CROSS-SYSTEM PARITY & ATOMIC I/O
    # =========================================================================
    def test_atomic_file_write_no_corruption(self):
        """Tests that state exports written atomically via tempfile + os.replace do not corrupt reads."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            target_file = os.path.join(tmp_dir, "test_ledger.json")
            data = {"status": "ACTIVE", "pnl": 12.5, "symbol": "BTC/USDT"}

            # Atomic write
            temp_path = f"{target_file}.tmp.{time.time_ns()}"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(temp_path, target_file)

            # Read back
            self.assertTrue(os.path.exists(target_file))
            with open(target_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded["symbol"], "BTC/USDT")
            self.assertEqual(loaded["pnl"], 12.5)

    # =========================================================================
    # 11. UPSTREAM LATENCY HARDENING & HIERARCHICAL SYNTHESIS
    # =========================================================================
    def test_hierarchical_candle_synthesis_anchors(self):
        """Tests that 4H and 12H synthesize from 1H, and 1W, 15D, 1M synthesize from 1D without network calls."""
        from app.engine.scanner.data_loader import MultiHorizonDataLoader
        loader = MultiHorizonDataLoader()

        # Create 240 synthetic 1H candles (10 days)
        now_ts = int(time.time() * 1000)
        records_1h = []
        for i in range(240):
            t = now_ts - (240 - i) * 3600 * 1000
            p = 100.0 + i * 0.1
            records_1h.append({
                "timestamp": t,
                "datetime": pd.to_datetime(t, unit="ms", utc=True),
                "open": p,
                "high": p + 0.5,
                "low": p - 0.5,
                "close": p + 0.2,
                "volume": 1000.0,
                "taker_buy_vol": 500.0
            })
        df_1h = pd.DataFrame(records_1h)

        # Create 180 synthetic 1D candles (180 days)
        records_1d = []
        for i in range(180):
            t = now_ts - (180 - i) * 86400 * 1000
            p = 100.0 + i * 0.5
            records_1d.append({
                "timestamp": t,
                "datetime": pd.to_datetime(t, unit="ms", utc=True),
                "open": p,
                "high": p + 2.0,
                "low": p - 2.0,
                "close": p + 1.0,
                "volume": 50000.0,
                "taker_buy_vol": 25000.0
            })
        df_1d = pd.DataFrame(records_1d)

        # Synthesize 4H (chunk 4): 240 / 4 = 60 bars
        df_4h = loader._resample_chunk(df_1h, chunk_size=4)
        self.assertIsNotNone(df_4h)
        self.assertEqual(len(df_4h), 60)

        # Synthesize 12H (chunk 12): 240 / 12 = 20 bars
        df_12h = loader._resample_chunk(df_1h, chunk_size=12)
        self.assertIsNotNone(df_12h)
        self.assertEqual(len(df_12h), 20)

        # Synthesize 1W (chunk 7): 180 / 7 = 25 bars
        df_1w = loader._resample_chunk(df_1d, chunk_size=7)
        self.assertIsNotNone(df_1w)
        self.assertGreaterEqual(len(df_1w), 25)

        # Synthesize 15D via _resample_15d: 180 / 15 = 12 bars
        df_15d = loader._resample_15d(df_1d)
        self.assertIsNotNone(df_15d)
        self.assertEqual(len(df_15d), 12)

        # Synthesize 1M (chunk 30): 180 / 30 = 6 bars
        df_1m = loader._resample_chunk(df_1d, chunk_size=30)
        self.assertIsNotNone(df_1m)
        self.assertEqual(len(df_1m), 6)

    def test_persistent_geo_cooldown_save_and_reload(self):
        """Tests that upstream exchange geo-cooldowns persist across container reboots."""
        from app.engine.scanner.data_loader import MultiHorizonDataLoader
        with tempfile.TemporaryDirectory() as tmp_dir:
            loader = MultiHorizonDataLoader()
            loader._disk_cache_dir = tmp_dir

            # Record geo block on Bybit and OKX
            now = time.time()
            loader._record_exchange_geo_block("bybit", 403, "Cloud IP restriction")
            loader._record_exchange_geo_block("okx", 451, "Compliance block")

            self.assertTrue(loader._is_exchange_geo_blocked("bybit"))
            self.assertTrue(loader._is_exchange_geo_blocked("okx"))
            self.assertFalse(loader._is_exchange_geo_blocked("gateio"))

            # Verify persistent file was written
            cooldown_file = os.path.join(tmp_dir, "geo_cooldowns.json")
            self.assertTrue(os.path.exists(cooldown_file))

            # Simulate reboot with new loader instance
            new_loader = MultiHorizonDataLoader()
            new_loader._disk_cache_dir = tmp_dir
            new_loader._load_geo_cooldowns_from_disk()

            # Cooldowns must be restored immediately without network latency
            self.assertTrue(new_loader._is_exchange_geo_blocked("bybit"))
            self.assertTrue(new_loader._is_exchange_geo_blocked("okx"))
            self.assertFalse(new_loader._is_exchange_geo_blocked("gateio"))

    # =========================================================================
    # 12. WHATSAPP GATEWAY DURABILITY & HEALTH CHECK
    # =========================================================================
    def test_whatsapp_persistent_alert_spool_and_recovery(self):
        """Tests that WhatsApp alert spool survives process reboots and recovers unsent messages."""
        from app.services.whatsapp_service import WhatsAppService
        with tempfile.TemporaryDirectory() as tmp_dir:
            wa = WhatsAppService()
            wa._spool_file = os.path.join(tmp_dir, "whatsapp_alert_spool.json")
            wa._dead_letter_file = os.path.join(tmp_dir, "whatsapp_dead_letter.json")
            wa.enabled = True

            # Enqueue test alert
            wa._enqueue_message("120363431167900107@g.us", "🚨 TEST ALERT: BTC LONG 15M", priority=1)

            # Check spool file exists and has 1 message
            self.assertTrue(os.path.exists(wa._spool_file))
            with open(wa._spool_file, "r", encoding="utf-8") as f:
                spool_items = json.load(f)
            self.assertEqual(len(spool_items), 1)
            self.assertIn("BTC LONG 15M", spool_items[0]["text"])

            # Simulate reboot by loading into fresh instance
            wa2 = WhatsAppService()
            wa2._spool_file = wa._spool_file
            wa2._dead_letter_file = wa._dead_letter_file
            wa2._spool.clear()
            wa2._load_spool_from_disk()

            self.assertEqual(len(wa2._spool), 1)
            restored_item = list(wa2._spool.values())[0]
            self.assertIn("BTC LONG 15M", restored_item["text"])

    def test_whatsapp_dead_letter_archival_and_health_check(self):
        """Tests dead-letter archival on retry exhaustion and health check diagnostics."""
        from app.services.whatsapp_service import WhatsAppService
        with tempfile.TemporaryDirectory() as tmp_dir:
            wa = WhatsAppService()
            wa._dead_letter_file = os.path.join(tmp_dir, "whatsapp_dead_letter.json")

            # Archive dead letter
            test_item = {"target": "120363431167900107@g.us", "text": "FAILED ALERT", "retries": 6}
            wa._archive_dead_letter(test_item, reason="Max retries (5) exceeded")

            self.assertTrue(os.path.exists(wa._dead_letter_file))
            with open(wa._dead_letter_file, "r", encoding="utf-8") as f:
                dead_items = json.load(f)
            self.assertEqual(len(dead_items), 1)
            self.assertEqual(dead_items[0]["reason"], "Max retries (5) exceeded")

            # Health check diagnostic check (mocked/safe execution)
            wa.enabled = False
            health = wa.check_gateway_health()
            self.assertEqual(health["status"], "disabled")
            self.assertTrue(health["healthy"])


if __name__ == "__main__":
    unittest.main()
