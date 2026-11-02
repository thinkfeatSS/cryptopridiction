import os
import time
import unittest
import pandas as pd
import numpy as np

from app.quant_v16.entry_confirmation import EntryConfirmationEngine
from app.quant_v16.strategies import StrategyRegistry, StrategyArchetype, StrategyStatus, normalize_regime_key
from app.quant_v16.regime import MarketRegime
from app.engine.execution.paper_trading_bot import PaperTradingBot
from app.engine.signals.signal_generator import map_canonical_strategy


class TestV16EntryAndRegimeDebugging(unittest.TestCase):
    """
    Forensic test suite verifying the resolution of all identified confirmation candle,
    regime activation, resting limit execution, and module alignment issues.
    """

    def setUp(self):
        self.reg = StrategyRegistry()

    def test_01_fvg_retest_strictly_prior_to_trigger(self):
        """
        Verify that a 3-candle FVG formed prior to trigger candle is correctly detected,
        and that a normal monotonic trend candle does NOT trigger false FVG retest.
        """
        # Scenario A: Monotonic uptrend with no FVG formed prior to trigger
        # Prices: 100 -> 101 -> 102 -> 103 -> 104 -> 105 (Live)
        bars_monotonic = [
            {"open": 100.0, "high": 100.5, "low": 99.8, "close": 100.4, "volume": 1000},
            {"open": 100.4, "high": 101.5, "low": 100.2, "close": 101.4, "volume": 1000},
            {"open": 101.4, "high": 102.5, "low": 101.2, "close": 102.4, "volume": 1000},
            {"open": 102.4, "high": 103.5, "low": 102.2, "close": 103.4, "volume": 1000},
            {"open": 103.4, "high": 104.5, "low": 103.2, "close": 104.4, "volume": 1000}, # Trigger candle
            {"open": 104.4, "high": 105.0, "low": 104.3, "close": 104.9, "volume": 1000}, # Live candle
        ]
        df_mono = pd.DataFrame(bars_monotonic)
        conf, reason, metrics = EntryConfirmationEngine.validate_candle_trigger(
            df_mono, direction="LONG", current_price=104.9
        )
        # Should NOT be flagged as FVG retest
        self.assertFalse(metrics.get("is_fvg_retest", False), "Monotonic trend should not be falsely marked as FVG retest")

        # Scenario B: Genuine Bullish FVG formed at bars 0, 1, 2, then retested at bar 3 (trigger)
        # Bar 0: High = 100.0
        # Bar 1 (Displacement): Low = 100.2, High = 103.0
        # Bar 2: Low = 101.5 (Gap between Bar 0 High 100.0 and Bar 2 Low 101.5 = 1.5; CE = 100.75)
        # Bar 3 (Trigger): Dips to Low 101.0 (into gap) and closes at 101.8 (above CE 100.75)
        # Bar 4 (Live bar)
        bars_fvg = [
            {"open": 99.0, "high": 100.0, "low": 98.8, "close": 99.8, "volume": 1000},     # c1
            {"open": 100.0, "high": 103.0, "low": 99.9, "close": 102.8, "volume": 2500},   # c2 (displacement)
            {"open": 102.8, "high": 103.5, "low": 101.5, "close": 103.2, "volume": 1200},   # c3 (gap: 100.0 to 101.5, CE = 100.75)
            {"open": 103.2, "high": 103.3, "low": 101.0, "close": 101.8, "volume": 1500},   # Trigger candle: dips to 101.0 (<= 101.5) and closes 101.8 (>= 100.75)
            {"open": 101.8, "high": 102.0, "low": 101.7, "close": 101.9, "volume": 800},    # Live bar
        ]
        df_fvg = pd.DataFrame(bars_fvg)
        conf_fvg, reason_fvg, metrics_fvg = EntryConfirmationEngine.validate_candle_trigger(
            df_fvg, direction="LONG", current_price=101.9
        )
        self.assertTrue(metrics_fvg.get("is_fvg_retest"), "Genuine FVG retest must be recognized")
        self.assertEqual(metrics_fvg.get("pattern"), "FVG_RETEST_LONG")

    def test_02_live_bar_blowout_guard_with_live_current_price(self):
        """
        Verify that an acute adverse market dump in the active live bar
        is immediately intercepted via current_price.
        """
        bars = [
            {"open": 100.0, "high": 101.0, "low": 99.8, "close": 100.5, "volume": 1000},
            {"open": 100.5, "high": 100.6, "low": 98.5, "close": 100.5, "volume": 1000}, # Live bar with stale close
        ]
        df = pd.DataFrame(bars)
        # Real-time market tick dumped to 98.5 (adverse -2.0% dump with no absorption wick)
        conf, reason, metrics = EntryConfirmationEngine.validate_candle_trigger(
            df, direction="LONG", current_price=98.5
        )
        self.assertFalse(conf, "Acute adverse live dump must be rejected by blowout guard")
        self.assertTrue(metrics.get("is_live_blowout"))
        self.assertIn("Waterfall Dump", reason)

    def test_03_adverse_candle_fallthrough_rejection(self):
        """
        Verify that a falling red bar without buyer absorption is strictly rejected for Long entry,
        and a rising green bar without seller rejection is strictly rejected for Short entry.
        """
        # Red bar that does not trigger Marubozu (body_ratio 0.40 < 0.65) but has insufficient wick absorption
        # Open 100.2, High 100.5, Low 99.5, Close 99.8. Range = 1.0. Lower wick = 0.3 (30%? let's make low 99.65 -> lower wick 0.15 = 15%).
        # Body = 0.4. Body ratio = 0.40. Close pos = (99.8 - 99.65)/1.0 = 0.35
        bars_red = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000},
            {"open": 100.2, "high": 100.65, "low": 99.65, "close": 99.8, "volume": 1000}, # Trigger candle: Red, body_ratio 0.40, lower_wick_ratio 0.15 (<0.25)
            {"open": 99.8, "high": 99.9, "low": 99.7, "close": 99.8, "volume": 500},
        ]
        df_red = pd.DataFrame(bars_red)
        conf_long, reason_long, _ = EntryConfirmationEngine.validate_candle_trigger(
            df_red, direction="LONG", current_price=99.8
        )
        self.assertFalse(conf_long, "Red candle without buyer absorption must NOT confirm Long entry")
        self.assertIn("Awaiting Bullish Absorption", reason_long)

        # Green bar that does not trigger Marubozu but has insufficient seller rejection
        # Open 99.8, High 100.35, Low 99.35, Close 100.2. Range = 1.0. Upper wick = 0.15 (15% < 25%).
        # Body = 0.4. Body ratio = 0.40. Close pos = (100.2 - 99.35)/1.0 = 0.85 (or let's adjust high to 100.5 and close to 100.0, close pos 0.65)
        # Open 99.8, High 100.15, Low 99.15, Close 100.0. Rng = 1.0. Upper wick = 100.15 - 100.0 = 0.15 (15%). Body = 0.20.
        bars_green = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000},
            {"open": 99.8, "high": 100.2, "low": 99.2, "close": 100.1, "volume": 1000}, # Trigger candle: Green, upper wick 0.10/1.0 = 10% (<25%)
            {"open": 100.1, "high": 100.2, "low": 100.0, "close": 100.1, "volume": 500},
        ]
        df_green = pd.DataFrame(bars_green)
        conf_short, reason_short, _ = EntryConfirmationEngine.validate_candle_trigger(
            df_green, direction="SHORT", current_price=100.1
        )
        self.assertFalse(conf_short, "Green candle without seller rejection must NOT confirm Short entry")
        self.assertIn("Awaiting Bearish Rejection", reason_short)

    def test_04_order_block_in_zone_no_false_chase(self):
        """
        Verify that when price is inside the detected Order Block zone,
        it is recognized as MARKET_CONFIRMED without falsely flagging is_chasing = True.
        """
        ob_setup = {
            "setup_detected": True,
            "order_block_zone": [100.0, 102.0],
            "optimal_entry_limit": 101.0,
            "tp1_price": 106.0,
            "sl_price": 98.5
        }
        # Price is 101.8 (within [100.0, 102.0])
        res = EntryConfirmationEngine.calculate_optimal_entry_zone(
            current_price=101.8,
            ob_setup=ob_setup,
            direction="LONG",
            active_atr=1.5,
            chase_threshold_pct=0.40,
            strategy="ORDER_BLOCK_LONG"
        )
        self.assertFalse(res["is_limit_pending"], "Price inside Order Block zone must not be flagged as resting limit")
        self.assertEqual(res["entry_mode"], "MARKET_CONFIRMED")
        self.assertGreaterEqual(float(res["entry_zone_max"]), 101.8)
        self.assertLessEqual(float(res["entry_zone_min"]), 101.0)

    def test_05_strategy_registry_regime_kill_switches_all_archetypes(self):
        """
        Verify that all 32 archetypes are fully registered with priors,
        and that normalize_regime_key correctly enforces kill switches.
        """
        # 1. Total registered strategies must match StrategyArchetype enum count (32)
        self.assertEqual(len(self.reg.strategies), len(StrategyArchetype))

        # 2. Bull/Bear normalization
        self.assertEqual(normalize_regime_key("BEAR"), "BEAR_TREND")
        self.assertEqual(normalize_regime_key("FLASH_DUMP"), "BEAR_TREND")
        self.assertEqual(normalize_regime_key("BULL"), "BULL_TREND")
        self.assertEqual(normalize_regime_key("RANGE_SQUEEZE"), "SQUEEZE")
        self.assertEqual(normalize_regime_key("CONSOLIDATION"), "RANGE")

        # 3. Kill-switch enforcement: Longs paused in BEAR_TREND
        long_strats = [
            StrategyArchetype.ORDER_BLOCK_LONG.value,
            StrategyArchetype.BREAKER_BLOCK_LONG.value,
            StrategyArchetype.DIP_BUY_LONG.value,
            StrategyArchetype.MOMENTUM_LONG.value,
            StrategyArchetype.DIRECTIONAL_TREND_LONG.value,
            StrategyArchetype.FVG_RETEST_LONG.value
        ]
        for s in long_strats:
            allowed, reason = self.reg.is_strategy_allowed(s, current_regime="BEAR_TREND")
            self.assertFalse(allowed, f"{s} must be paused in BEAR_TREND. Reason: {reason}")
            # Also test alias "BEAR"
            allowed_alias, _ = self.reg.is_strategy_allowed(s, current_regime="BEAR")
            self.assertFalse(allowed_alias, f"{s} must be paused in BEAR alias")

        # 4. Shorts paused in BULL_TREND
        short_strats = [
            StrategyArchetype.ORDER_BLOCK_SHORT.value,
            StrategyArchetype.BREAKER_BLOCK_SHORT.value,
            StrategyArchetype.RALLY_FADE_SHORT.value,
            StrategyArchetype.TOP_REVERSAL_SHORT.value,
            StrategyArchetype.MOMENTUM_SHORT.value,
            StrategyArchetype.DIRECTIONAL_TREND_SHORT.value
        ]
        for s in short_strats:
            allowed, reason = self.reg.is_strategy_allowed(s, current_regime="BULL_TREND")
            self.assertFalse(allowed, f"{s} must be paused in BULL_TREND. Reason: {reason}")
            # Also test alias "BULL"
            allowed_alias, _ = self.reg.is_strategy_allowed(s, current_regime="BULL")
            self.assertFalse(allowed_alias, f"{s} must be paused in BULL alias")

    def test_06_paper_trading_bot_resting_limit_no_instant_cancellation(self):
        """
        Verify that a resting limit order is NOT instantly cancelled on tick 1,
        and cleanly fills when price touches limit.
        """
        import tempfile
        temp_ledger = os.path.join(tempfile.gettempdir(), f"test_ledger_{int(time.time()*1000)}.json")
        bot = PaperTradingBot(ledger_file=temp_ledger)
        signal = {
            "signal_id": "TEST_RESTING_001",
            "symbol": "SOL/USDT",
            "dominant_direction": "LONG",
            "direction": "LONG",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "current_price": 100.0,
            "entry_price": 99.0,
            "optimal_entry_limit": 99.0,
            "entry_zone_min": 98.5,
            "entry_zone_max": 100.5,
            "is_limit_pending": True,
            "entry_mode": "RESTING_LIMIT",
            "tp1_price": 104.0,
            "tp2_price": 108.0,
            "sl_price": 97.0,
            "quality_grade": "Grade A+",
            "conviction": 85.0,
            "meta_win_prob_pct": 72.0,
            "dominant_timeframe": "15M",
            "horizon": "15M",
            "desk": "scalp"
        }
        # 1. Admit signal as resting limit
        opened = bot.admit_signal(signal)
        self.assertTrue(opened, "Resting limit signal must be admitted")

        # Find the resting position
        open_pos = [p for p in bot.data["open_positions"] if p["trade_id"] == "TEST_RESTING_001"]
        self.assertEqual(len(open_pos), 1)
        pos = open_pos[0]
        self.assertEqual(pos["status"], "RESTING_LIMIT")
        self.assertEqual(pos.get("admission_price"), 100.0)

        # 2. Tick 1: Price still at 100.0 (admission price) -> Must NOT be cancelled!
        bot.on_tick({"SOL/USDT": 100.0})
        self.assertEqual(pos["status"], "RESTING_LIMIT", "Must remain RESTING_LIMIT on initial price tick")

        # 3. Tick 2: Price pulls back to 99.0 -> Limit touches and fills to OPEN!
        bot.on_tick({"SOL/USDT": 99.0})
        self.assertEqual(pos["status"], "OPEN", "Must fill and transition to OPEN when touching limit price")
        self.assertEqual(pos["entry_price"], 99.0)

    def test_07_canonical_strategy_and_metadata_alignment(self):
        """
        Verify that is_engulfing maps to MOMENTUM_LONG / MOMENTUM_SHORT,
        and that canonical_strategy, candle_trigger_confirmed, candle_trigger_reason,
        and candle_metrics are properly integrated.
        """
        # Bullish engulfing mapping
        m_long = map_canonical_strategy("UNKNOWN_RAW", "LONG", candle_metrics={"is_engulfing": True})
        self.assertEqual(m_long, StrategyArchetype.MOMENTUM_LONG.value)

        # Bearish engulfing mapping
        m_short = map_canonical_strategy("UNKNOWN_RAW", "SHORT", candle_metrics={"is_engulfing": True})
        self.assertEqual(m_short, StrategyArchetype.MOMENTUM_SHORT.value)

        # Liquidity sweep reclaim mapping
        m_sweep = map_canonical_strategy("UNKNOWN_RAW", "LONG", candle_metrics={"is_sweep_reclaim": True})
        self.assertEqual(m_sweep, StrategyArchetype.LIQUIDITY_RECLAIM_LONG.value)

        # FVG retest mapping
        m_fvg = map_canonical_strategy("UNKNOWN_RAW", "SHORT", candle_metrics={"is_fvg_retest": True})
        self.assertEqual(m_fvg, StrategyArchetype.FVG_RETEST_SHORT.value)


if __name__ == "__main__":
    unittest.main()
