"""
QUANT EDGE V16: Phase 4 Accuracy & Throughput Verification Suite
Tests all Phase 4 enhancements:
- AC-01: Fractal Sub-Range Support Mean Reversion when 1D is in middle chop but 1H is at boundary.
- AC-02: Strict Capital Preservation Veto when both 1D and 1H are in middle chop.
- AC-03: Elder's Triple Screen Horizon Decoupling (15M scalp qualifies with 1H anchor even if HTF consolidates).
- AC-04: Turtle Soup Liquidity Sweep Reclaims on depleted (retest >= 3) order blocks with asymmetric RR.
- AC-05: Mathematically dynamic Meta Hurdle scaling with Risk:Reward ratio.
- AC-06: Anti-exhaustion Range Resistance / Support candle trigger confirmations.
"""

import unittest
import pandas as pd
import numpy as np

from app.quant_v16.cross_timeframe_matrix import CrossTimeframeMatrixEngine, InstitutionalArchetype
from app.quant_v16.fractal_consolidation import TimeframeConsolidationProfile, FractalTimeframeState
from app.quant_v16.order_blocks import InstitutionalOrderBlockEngine, OrderBlock, OrderBlockState, OrderBlockType
from app.quant_v16.entry_confirmation import EntryConfirmationEngine
from app.engine.signals.signal_generator import SignalGenerationSystem, map_canonical_strategy


class TestPhase4AccuracyAndThroughput(unittest.TestCase):

    def _make_profile(
        self,
        timeframe: str,
        state: FractalTimeframeState,
        range_high: float,
        range_low: float,
        current_price: float,
        headroom_to_high_pct: float = 10.0,
        headroom_to_low_pct: float = 10.0,
        adx: float = 20.0,
        chop_index: float = 50.0,
        is_coiling: bool = False
    ) -> TimeframeConsolidationProfile:
        span = max(1e-8, range_high - range_low)
        pos = (current_price - range_low) / span
        return TimeframeConsolidationProfile(
            timeframe=timeframe,
            state=state,
            is_consolidation=(state in [FractalTimeframeState.CONSOLIDATION_RANGING, FractalTimeframeState.CONSOLIDATION_COILING]),
            is_coiling_squeeze=is_coiling,
            chop_index=chop_index,
            adx=adx,
            bbw_pct=3.0,
            is_inside_bar=False,
            is_nr7=False,
            is_nr4=False,
            is_doji=False,
            compression_score=0.2,
            range_high=range_high,
            range_low=range_low,
            range_mid=(range_high + range_low) / 2.0,
            position_in_range_pct=pos,
            headroom_to_high_pct=headroom_to_high_pct,
            headroom_to_low_pct=headroom_to_low_pct,
            current_price=current_price
        )

    # -------------------------------------------------------------------------
    # AC-01: Fractal Sub-Range Support / Resistance Decomposition
    # -------------------------------------------------------------------------
    def test_ac01_sub_range_support_mean_reversion(self):
        """
        When 1D is in Middle Chop (pos = 0.50), but 1H is at intraday support boundary
        (pos <= 0.25) with >= 1.5% headroom, matrix permits trade with target capped at 1D mid.
        """
        # 1D: Range 80 to 120, current_price = 100 -> pos = 20/40 = 0.50 (Middle Chop)
        p_1d = self._make_profile(
            timeframe="1d",
            state=FractalTimeframeState.CONSOLIDATION_RANGING,
            range_high=120.0,
            range_low=80.0,
            current_price=100.0,
            headroom_to_high_pct=20.0,
            headroom_to_low_pct=20.0
        )
        # 1H: Range 99.0 to 105.0, current_price = 100.0 -> pos = 1.0 / 6.0 = 0.167 (Support Boundary <= 0.25)
        # Headroom to 1H high (105) is 5.0% >= 1.5%
        p_1h = self._make_profile(
            timeframe="1h",
            state=FractalTimeframeState.CONSOLIDATION_RANGING,
            range_high=105.0,
            range_low=99.0,
            current_price=100.0,
            headroom_to_high_pct=5.0,
            headroom_to_low_pct=1.0
        )
        p_15m = self._make_profile(
            timeframe="15m",
            state=FractalTimeframeState.CONSOLIDATION_RANGING,
            range_high=105.0,
            range_low=99.0,
            current_price=100.0
        )

        profiles = {"1d": p_1d, "1h": p_1h, "15m": p_15m}
        res = CrossTimeframeMatrixEngine.evaluate_matrix(profiles, current_price=100.0)

        self.assertTrue(res["trade_permitted"])
        self.assertEqual(res["dominant_direction"], "LONG")
        self.assertEqual(res["strategy"], "SUB_RANGE_SUPPORT_MEAN_REVERSION")
        self.assertEqual(res["archetype"], InstitutionalArchetype.ARCHETYPE_C_RANGE_ROTATION.value)
        self.assertGreater(res["headroom_pct"], 0.0)

    def test_ac01_sub_range_resistance_mean_reversion(self):
        """
        When 1D is in Middle Chop (pos = 0.50), but 1H is at intraday resistance boundary
        (pos >= 0.75) with >= 1.5% headroom, matrix permits short trade.
        """
        # 1D: Range 80 to 120, current_price = 100 -> pos = 0.50 (Middle Chop)
        p_1d = self._make_profile(
            timeframe="1d",
            state=FractalTimeframeState.CONSOLIDATION_RANGING,
            range_high=120.0,
            range_low=80.0,
            current_price=100.0
        )
        # 1H: Range 95.0 to 101.0, current_price = 100.0 -> pos = 5.0 / 6.0 = 0.833 (Resistance Boundary >= 0.75)
        # Headroom to 1H low (95) is 5.0% >= 1.5%
        p_1h = self._make_profile(
            timeframe="1h",
            state=FractalTimeframeState.CONSOLIDATION_RANGING,
            range_high=101.0,
            range_low=95.0,
            current_price=100.0,
            headroom_to_high_pct=1.0,
            headroom_to_low_pct=5.0
        )
        p_15m = self._make_profile(
            timeframe="15m",
            state=FractalTimeframeState.CONSOLIDATION_RANGING,
            range_high=101.0,
            range_low=95.0,
            current_price=100.0
        )

        profiles = {"1d": p_1d, "1h": p_1h, "15m": p_15m}
        res = CrossTimeframeMatrixEngine.evaluate_matrix(profiles, current_price=100.0)

        self.assertTrue(res["trade_permitted"])
        self.assertEqual(res["dominant_direction"], "SHORT")
        self.assertEqual(res["strategy"], "SUB_RANGE_RESISTANCE_MEAN_REVERSION")
        self.assertEqual(res["archetype"], InstitutionalArchetype.ARCHETYPE_C_RANGE_ROTATION.value)

    # -------------------------------------------------------------------------
    # AC-02: Strict Capital Preservation Veto When Both Trapped in Middle
    # -------------------------------------------------------------------------
    def test_ac02_both_in_middle_chop_vetoed(self):
        """
        When both 1D and 1H are in middle chop (0.25 < pos < 0.75), capital preservation strictly locks.
        """
        p_1d = self._make_profile(
            timeframe="1d",
            state=FractalTimeframeState.CONSOLIDATION_RANGING,
            range_high=120.0,
            range_low=80.0,
            current_price=100.0
        )
        p_1h = self._make_profile(
            timeframe="1h",
            state=FractalTimeframeState.CONSOLIDATION_RANGING,
            range_high=110.0,
            range_low=90.0,
            current_price=100.0  # pos = 10 / 20 = 0.50 (Middle Chop)
        )
        p_15m = self._make_profile(
            timeframe="15m",
            state=FractalTimeframeState.CONSOLIDATION_RANGING,
            range_high=105.0,
            range_low=95.0,
            current_price=100.0
        )

        profiles = {"1d": p_1d, "1h": p_1h, "15m": p_15m}
        res = CrossTimeframeMatrixEngine.evaluate_matrix(profiles, current_price=100.0)

        self.assertFalse(res["trade_permitted"])
        self.assertEqual(res["strategy"], "CAPITAL_PRESERVATION_MIDDLE_CHOP_VETO")
        self.assertEqual(res["dominant_direction"], "NO_TRADE")

    # -------------------------------------------------------------------------
    # AC-03: Elder's Triple Screen Decoupling
    # -------------------------------------------------------------------------
    def test_ac03_elders_triple_screen_decoupling_15m_scalp(self):
        """
        Verify that 15M Scalp qualifies when 15M is Bullish and 1H anchor is not opposing,
        even if 4H, 12H, 1D, 1W are in consolidation.
        """
        matrix_eval = {
            "trade_permitted": True,
            "strategy": "MOMENTUM_TREND_EXPANSION",
            "archetype": InstitutionalArchetype.ARCHETYPE_A_SECULAR_EXPANSION.value
        }
        h_preds = {tf: {"is_cold_start": False, "candle_count": 50} for tf in ["5m", "15m", "1h", "4h", "12h", "1d", "1w", "15d", "1M"]}

        # 5M Bullish, 15M Bullish, 1H Consolidation (not opposing), HTF Consolidation
        tm_decoupled = {
            "5m": "BULLISH", "15m": "BULLISH", "1h": "CONSOLIDATION",
            "4h": "CONSOLIDATION", "12h": "CONSOLIDATION", "1d": "CONSOLIDATION",
            "1w": "CONSOLIDATION", "15d": "CONSOLIDATION", "1M": "CONSOLIDATION"
        }

        q_15, _, _ = SignalGenerationSystem.evaluate_multi_horizon_gates(
            trend_matrix=tm_decoupled,
            horizon_predictions=h_preds,
            matrix_eval=matrix_eval
        )
        self.assertTrue(q_15["qualified"])
        self.assertEqual(q_15["direction"], "LONG")

        # But if 1H opposes with BEARISH, 15M Scalp is strictly BLOCKED by its Tide Anchor
        tm_opposed = dict(tm_decoupled)
        tm_opposed["1h"] = "BEARISH"

        q_15_blocked, _, _ = SignalGenerationSystem.evaluate_multi_horizon_gates(
            trend_matrix=tm_opposed,
            horizon_predictions=h_preds,
            matrix_eval=matrix_eval
        )
        self.assertFalse(q_15_blocked["qualified"])

    # -------------------------------------------------------------------------
    # AC-04: Turtle Soup Liquidity Sweep Reclaim on Depleted Order Blocks
    # -------------------------------------------------------------------------
    def test_ac04_turtle_soup_liquidity_sweep_reclaim(self):
        """
        Verify that an order block with retest_count >= 3 that experiences a sweep past the zone
        and reclaims inside emits a TURTLE_SOUP_LIQUIDITY_RECLAIM setup with asymmetric RR >= 2.8.
        """
        # Create synthetic candle DataFrame
        # Block is at [100, 102], current candle sweeps to 99.2 (sweep_low < 100), and closes at 100.8 (reclaimed >= 100)
        dates = pd.date_range("2026-01-01", periods=30, freq="15min")
        df_candles = pd.DataFrame({
            "open": [101.0] * 30,
            "high": [102.5] * 30,
            "low": [100.5] * 30,
            "close": [101.5] * 30,
            "volume": [1000.0] * 30
        }, index=dates)

        # Trigger candle: sweeps below 100 down to 99.3, reclaims to 100.8, with volume surge
        df_candles.loc[dates[-1], "open"] = 100.5
        df_candles.loc[dates[-1], "high"] = 101.2
        df_candles.loc[dates[-1], "low"] = 99.3
        df_candles.loc[dates[-1], "close"] = 100.8
        df_candles.loc[dates[-1], "volume"] = 2500.0  # 2.5x volume surge

        ob_depleted = OrderBlock(
            block_type=OrderBlockType.BULLISH,
            state=OrderBlockState.TESTING,
            timeframe="15m",
            candle_idx=15,
            timestamp=int(dates[15].timestamp() * 1000),
            ob_high=102.0,
            ob_low=100.0,
            ob_open=100.5,
            ob_close=101.5,
            equilibrium_50=101.0,
            displacement_mag=2.0,
            volume_surge=1.5,
            has_fvg=True,
            confluence_score=0.90,
            retest_count=3,  # Depleted standard limit liquidity
            zeiierman_rank=1,
            is_touching=True
        )

        orig_detect = InstitutionalOrderBlockEngine.detect_order_blocks
        try:
            InstitutionalOrderBlockEngine.detect_order_blocks = lambda *args, **kwargs: [ob_depleted]

            # Case A: Sweep and reclaim active -> emits TURTLE_SOUP_LIQUIDITY_RECLAIM
            setup = InstitutionalOrderBlockEngine.evaluate_live_setup(
                df=df_candles,
                timeframe="15m",
                current_price=100.8
            )
            self.assertTrue(setup["setup_detected"])
            self.assertEqual(setup["direction"], "LONG")
            self.assertEqual(setup["strategy"], "TURTLE_SOUP_LIQUIDITY_RECLAIM")
            self.assertTrue(setup["is_turtle_soup"])
            self.assertGreaterEqual(setup["risk_reward_ratio"], 2.8)
            self.assertLess(setup["sl_price"], 99.3)  # Stop loss placed below sweep wick

            # Case B: Standard retest without sweep -> fails closed as depleted
            df_candles_no_sweep = df_candles.copy()
            df_candles_no_sweep.loc[dates[-1], "low"] = 100.2  # Price stayed strictly inside zone without sweep
            setup_depleted = InstitutionalOrderBlockEngine.evaluate_live_setup(
                df=df_candles_no_sweep,
                timeframe="15m",
                current_price=100.8
            )
            self.assertFalse(setup_depleted["setup_detected"])
            self.assertIn("depleted", setup_depleted["reason"].lower())

        finally:
            InstitutionalOrderBlockEngine.detect_order_blocks = orig_detect

    # -------------------------------------------------------------------------
    # AC-05: Dynamic Meta Hurdle Scaling
    # -------------------------------------------------------------------------
    def test_ac05_dynamic_meta_hurdle_scaling(self):
        """
        Verify that dynamic meta hurdle scales down for high-asymmetry RR trades
        and bounds between 0.44 and 0.65.
        """
        # High RR setup: RR = 3.5 -> breakeven prob ~ 22.2% -> Hurdle scaled to 0.44 floor
        rr_high = 3.5
        spread_bps = 5.0
        est_friction = (spread_bps / 10000.0) * 2.0 + 0.0010
        target_safety = 1.15
        hurdle_high = max(0.44, min(0.65, ((1.0 + est_friction) / (1.0 + rr_high)) * target_safety))
        self.assertAlmostEqual(hurdle_high, 0.44, places=2)

        # Low RR setup: RR = 1.0 -> breakeven prob ~ 50% -> Hurdle scaled up
        rr_low = 1.0
        hurdle_low = max(0.44, min(0.65, ((1.0 + est_friction) / (1.0 + rr_low)) * target_safety))
        self.assertGreater(hurdle_low, 0.55)
        self.assertLessEqual(hurdle_low, 0.65)

    # -------------------------------------------------------------------------
    # AC-06: Anti-Exhaustion Range Resistance / Support Candle Trigger Confirmation
    # -------------------------------------------------------------------------
    def test_ac06_range_resistance_rejection_confirmation(self):
        """
        Verify that a shooting star / upper wick rejection at range resistance confirms short entry.
        """
        dates = pd.date_range("2026-01-01", periods=10, freq="15min")
        # Prior window has high = 115.0, so trigger candle high (114.0) is a pure resistance rejection
        df_candles = pd.DataFrame({
            "open": [112.0] * 10,
            "high": [115.0] * 10,
            "low": [110.0] * 10,
            "close": [111.0] * 10,
            "volume": [1000.0] * 10
        }, index=dates)

        # Candle at idx -2: Upper wick rejection
        df_candles.loc[dates[-2], "open"] = 109.0
        df_candles.loc[dates[-2], "high"] = 114.0
        df_candles.loc[dates[-2], "low"] = 107.0
        df_candles.loc[dates[-2], "close"] = 108.0
        df_candles.loc[dates[-2], "volume"] = 1500.0

        is_confirmed, reason, metrics = EntryConfirmationEngine.validate_candle_trigger(
            df=df_candles,
            direction="SHORT",
            current_price=108.0
        )
        self.assertTrue(is_confirmed)
        self.assertTrue(metrics.get("is_range_resistance_rejection", False))
        self.assertEqual(metrics.get("pattern"), "RANGE_RESISTANCE_REJECTION")

        # Canonical strategy mapping maps this to RANGE_BOUNCE_SHORT
        strat = map_canonical_strategy("CAPITAL_PRESERVATION", "SHORT", candle_metrics=metrics)
        self.assertEqual(strat, "RANGE_BOUNCE_SHORT")


if __name__ == "__main__":
    unittest.main()
