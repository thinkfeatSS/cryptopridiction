import unittest
from typing import Dict, Any

from app.engine.signals.signal_generator import SignalGenerationSystem
from app.quant_v16.cross_timeframe_matrix import CrossTimeframeMatrixEngine, InstitutionalArchetype
from app.quant_v16.fractal_consolidation import FractalTimeframeState, TimeframeConsolidationProfile


class TestV16MultiTimeframeAlignment(unittest.TestCase):
    """
    Quant Edge V16 Multi-Timeframe Alignment Verification Suite.
    Verifies:
    1. Trend vs Consolidation weighting (Consolidation = 0.0% directional alignment).
    2. Hierarchical Desk Triad Confluence (15M Scalp, 1H Intraday, 24H Swing).
    3. Institutional Order Block and SMC bypass of macro range middle chop.
    4. Cross-timeframe matrix internal range rotation.
    """

    def test_consolidation_has_zero_directional_alignment_score(self):
        """
        Verify that a dead flat coin in 8/9 consolidation receives 0.0% directional alignment score,
        preventing chop coins from dominating the Top Trend-Aligned leaderboard.
        """
        horizon_preds: Dict[str, Dict[str, Any]] = {
            "5m": {"trend_state": "CONSOLIDATION"},
            "15m": {"trend_state": "CONSOLIDATION"},
            "1h": {"trend_state": "CONSOLIDATION"},
            "4h": {"trend_state": "CONSOLIDATION"},
            "12h": {"trend_state": "CONSOLIDATION"},
            "1d": {"trend_state": "CONSOLIDATION"},
            "1w": {"trend_state": "CONSOLIDATION"},
            "15d": {"trend_state": "CONSOLIDATION"},
            "1M": {"trend_state": "BULLISH"},
        }

        t_align = SignalGenerationSystem.compute_trend_alignment(horizon_preds)
        self.assertEqual(t_align["dominant_trend"], "CONSOLIDATION")
        self.assertEqual(t_align["dominant_direction"], "CONSOLIDATION")
        self.assertEqual(t_align["alignment_score_pct"], 0.0)
        self.assertEqual(t_align["aligned_horizons_count"], 8)
        self.assertEqual(t_align["alignment_ratio"], "8/9")

    def test_strong_bullish_and_bearish_trend_alignment_scores(self):
        """
        Verify that 7/9 Bullish or Bearish coins receive a high weighted directional alignment score.
        """
        bull_preds: Dict[str, Dict[str, Any]] = {
            "5m": {"trend_state": "BULLISH"},
            "15m": {"trend_state": "BULLISH"},
            "1h": {"trend_state": "BULLISH"},
            "4h": {"trend_state": "BULLISH"},
            "12h": {"trend_state": "BULLISH"},
            "1d": {"trend_state": "BULLISH"},
            "1w": {"trend_state": "BULLISH"},
            "15d": {"trend_state": "CONSOLIDATION"},
            "1M": {"trend_state": "CONSOLIDATION"},
        }
        t_align_bull = SignalGenerationSystem.compute_trend_alignment(bull_preds)
        self.assertEqual(t_align_bull["dominant_trend"], "BULLISH")
        self.assertEqual(t_align_bull["dominant_direction"], "LONG")
        self.assertGreaterEqual(t_align_bull["alignment_score_pct"], 85.0)
        self.assertEqual(t_align_bull["alignment_ratio"], "7/9")

        bear_preds: Dict[str, Dict[str, Any]] = {
            "5m": {"trend_state": "BEARISH"},
            "15m": {"trend_state": "BEARISH"},
            "1h": {"trend_state": "BEARISH"},
            "4h": {"trend_state": "BEARISH"},
            "12h": {"trend_state": "BEARISH"},
            "1d": {"trend_state": "BEARISH"},
            "1w": {"trend_state": "BEARISH"},
            "15d": {"trend_state": "CONSOLIDATION"},
            "1M": {"trend_state": "CONSOLIDATION"},
        }
        t_align_bear = SignalGenerationSystem.compute_trend_alignment(bear_preds)
        self.assertEqual(t_align_bear["dominant_trend"], "BEARISH")
        self.assertEqual(t_align_bear["dominant_direction"], "SHORT")
        self.assertGreaterEqual(t_align_bear["alignment_score_pct"], 85.0)
        self.assertEqual(t_align_bear["alignment_ratio"], "7/9")

    def test_desk_triad_confluence_qualification(self):
        """
        Verify that:
        1. 15M Scalp qualifies when 15M is Bullish, 1H anchor is not opposing, >=3 bullish horizons.
        2. 15M Scalp fails when 1H anchor opposes (BEARISH).
        3. 1H Intraday qualifies when 1H is Bullish, 4H anchor is not opposing, >=4 bullish horizons.
        4. 1H Intraday fails when 4H anchor opposes (BEARISH).
        5. 24H Swing qualifies when 1D is Bullish, 1W anchor is not opposing, >=4 bullish horizons.
        """
        matrix_eval = {
            "trade_permitted": True,
            "strategy": "MOMENTUM_TREND_EXPANSION",
            "archetype": InstitutionalArchetype.ARCHETYPE_A_SECULAR_EXPANSION.value
        }
        h_preds_base = {
            "5m": {"is_cold_start": False, "candle_count": 50},
            "15m": {"is_cold_start": False, "candle_count": 50},
            "1h": {"is_cold_start": False, "candle_count": 50},
            "4h": {"is_cold_start": False, "candle_count": 50},
            "12h": {"is_cold_start": False, "candle_count": 50},
            "1d": {"is_cold_start": False, "candle_count": 50},
            "1w": {"is_cold_start": False, "candle_count": 50},
            "15d": {"is_cold_start": False, "candle_count": 50},
            "1M": {"is_cold_start": False, "candle_count": 50},
        }

        # Case 1: 15M Scalp Valid Confluence
        tm_15m_pass = {
            "5m": "BULLISH", "15m": "BULLISH", "1h": "CONSOLIDATION",
            "4h": "BULLISH", "12h": "CONSOLIDATION", "1d": "CONSOLIDATION",
            "1w": "CONSOLIDATION", "15d": "CONSOLIDATION", "1M": "CONSOLIDATION"
        }
        q_15, q_1h, q_24 = SignalGenerationSystem.evaluate_multi_horizon_gates(
            trend_matrix=tm_15m_pass,
            horizon_predictions=h_preds_base,
            matrix_eval=matrix_eval
        )
        self.assertTrue(q_15["qualified"])
        self.assertEqual(q_15["direction"], "LONG")

        # Case 2: 15M Scalp Rejected when 1H anchor actively opposes
        tm_15m_fail = {
            "5m": "BULLISH", "15m": "BULLISH", "1h": "BEARISH",
            "4h": "BULLISH", "12h": "CONSOLIDATION", "1d": "CONSOLIDATION",
            "1w": "CONSOLIDATION", "15d": "CONSOLIDATION", "1M": "CONSOLIDATION"
        }
        q_15_bad, _, _ = SignalGenerationSystem.evaluate_multi_horizon_gates(
            trend_matrix=tm_15m_fail,
            horizon_predictions=h_preds_base,
            matrix_eval=matrix_eval
        )
        self.assertFalse(q_15_bad["qualified"])

        # Case 3: 1H Intraday Valid Confluence (15M in healthy consolidation pullback)
        tm_1h_pass = {
            "5m": "CONSOLIDATION", "15m": "CONSOLIDATION", "1h": "BULLISH",
            "4h": "BULLISH", "12h": "BULLISH", "1d": "BULLISH",
            "1w": "CONSOLIDATION", "15d": "CONSOLIDATION", "1M": "CONSOLIDATION"
        }
        _, q_1h_good, _ = SignalGenerationSystem.evaluate_multi_horizon_gates(
            trend_matrix=tm_1h_pass,
            horizon_predictions=h_preds_base,
            matrix_eval=matrix_eval
        )
        self.assertTrue(q_1h_good["qualified"])
        self.assertEqual(q_1h_good["direction"], "LONG")

        # Case 4: 1H Intraday Rejected when 4H anchor actively opposes
        tm_1h_fail = {
            "5m": "BULLISH", "15m": "BULLISH", "1h": "BULLISH",
            "4h": "BEARISH", "12h": "BULLISH", "1d": "BULLISH",
            "1w": "CONSOLIDATION", "15d": "CONSOLIDATION", "1M": "CONSOLIDATION"
        }
        _, q_1h_bad, _ = SignalGenerationSystem.evaluate_multi_horizon_gates(
            trend_matrix=tm_1h_fail,
            horizon_predictions=h_preds_base,
            matrix_eval=matrix_eval
        )
        self.assertFalse(q_1h_bad["qualified"])

        # Case 5: 24H Swing Valid Confluence
        tm_24h_pass = {
            "5m": "CONSOLIDATION", "15m": "CONSOLIDATION", "1h": "BULLISH",
            "4h": "BULLISH", "12h": "BULLISH", "1d": "BULLISH",
            "1w": "CONSOLIDATION", "15d": "CONSOLIDATION", "1M": "CONSOLIDATION"
        }
        _, _, q_24_good = SignalGenerationSystem.evaluate_multi_horizon_gates(
            trend_matrix=tm_24h_pass,
            horizon_predictions=h_preds_base,
            matrix_eval=matrix_eval
        )
        self.assertTrue(q_24_good["qualified"])
        self.assertEqual(q_24_good["direction"], "LONG")

    def test_order_block_bypass_of_macro_middle_chop(self):
        """
        Verify that when price is in macro range chop (Section 35 veto active),
        a validated Zeiierman Rank 1 Order Block touch on 15M permits 15M signal qualification.
        """
        matrix_eval_chop = {
            "trade_permitted": False,
            "strategy": "CAPITAL_PRESERVATION_MIDDLE_CHOP_VETO",
            "archetype": InstitutionalArchetype.ARCHETYPE_C_RANGE_ROTATION.value
        }
        h_preds_base = {
            "5m": {"is_cold_start": False, "candle_count": 50},
            "15m": {"is_cold_start": False, "candle_count": 50},
            "1h": {"is_cold_start": False, "candle_count": 50},
            "4h": {"is_cold_start": False, "candle_count": 50},
            "12h": {"is_cold_start": False, "candle_count": 50},
            "1d": {"is_cold_start": False, "candle_count": 50},
            "1w": {"is_cold_start": False, "candle_count": 50},
            "15d": {"is_cold_start": False, "candle_count": 50},
            "1M": {"is_cold_start": False, "candle_count": 50},
        }
        tm_chop = {tf: "CONSOLIDATION" for tf in h_preds_base}

        # Without OB touch -> blocked
        q_15_no_ob, _, _ = SignalGenerationSystem.evaluate_multi_horizon_gates(
            trend_matrix=tm_chop,
            horizon_predictions=h_preds_base,
            matrix_eval=matrix_eval_chop,
            ob_setup_15m=None
        )
        self.assertFalse(q_15_no_ob["qualified"])

        # With Rank 1 Order Block Touch -> admitted
        ob_setup_rank1 = {
            "setup_detected": True,
            "direction": "LONG",
            "zeiierman_rank": 1,
            "zeiierman_rank_label": "RANK_1_SUPREME"
        }
        q_15_with_ob, _, _ = SignalGenerationSystem.evaluate_multi_horizon_gates(
            trend_matrix=tm_chop,
            horizon_predictions=h_preds_base,
            matrix_eval=matrix_eval_chop,
            ob_setup_15m=ob_setup_rank1
        )
        self.assertTrue(q_15_with_ob["qualified"])
        self.assertEqual(q_15_with_ob["direction"], "LONG")

    def test_middle_chop_capital_preservation_veto_in_matrix(self):
        """
        Verify that when price is in the middle of a 1D range box (0.25 < range_pos < 0.75),
        CrossTimeframeMatrix strictly locks capital preservation (Section 35 veto).
        """
        def make_profile(
            timeframe: str,
            state: FractalTimeframeState,
            adx: float = 20.0,
            chop_index: float = 50.0,
            range_high: float = 110.0,
            range_low: float = 90.0,
            headroom_to_high_pct: float = 10.0,
            headroom_to_low_pct: float = 10.0,
            current_price: float = 100.0,
            is_coiling_squeeze: bool = False
        ) -> TimeframeConsolidationProfile:
            return TimeframeConsolidationProfile(
                timeframe=timeframe,
                state=state,
                is_consolidation=(state in [FractalTimeframeState.CONSOLIDATION_RANGING, FractalTimeframeState.CONSOLIDATION_COILING]),
                is_coiling_squeeze=is_coiling_squeeze,
                chop_index=chop_index,
                adx=adx,
                bbw_pct=5.0,
                is_inside_bar=False,
                is_nr7=False,
                is_nr4=False,
                is_doji=False,
                compression_score=0.0,
                range_high=range_high,
                range_low=range_low,
                range_mid=(range_high + range_low) / 2.0,
                position_in_range_pct=0.5,
                headroom_to_high_pct=headroom_to_high_pct,
                headroom_to_low_pct=headroom_to_low_pct,
                current_price=current_price
            )

        p_1d = make_profile(
            timeframe="1d",
            state=FractalTimeframeState.CONSOLIDATION_RANGING,
            adx=18.0,
            chop_index=55.0,
            range_high=120.0,
            range_low=80.0,
            headroom_to_high_pct=15.0,
            headroom_to_low_pct=23.0,
            current_price=104.0
        )
        p_15m = make_profile(
            timeframe="15m",
            state=FractalTimeframeState.TREND_BULLISH,
            adx=20.0,
            chop_index=48.0,
            range_high=105.0,
            range_low=100.0,
            headroom_to_high_pct=5.0,
            headroom_to_low_pct=5.0,
            current_price=104.0
        )
        p_1h = make_profile(
            timeframe="1h",
            state=FractalTimeframeState.TREND_BULLISH,
            adx=20.0,
            chop_index=48.0,
            range_high=110.0,
            range_low=95.0,
            headroom_to_high_pct=8.0,
            headroom_to_low_pct=8.0,
            current_price=104.0
        )
        p_4h = make_profile(
            timeframe="4h",
            state=FractalTimeframeState.CONSOLIDATION_RANGING,
            adx=18.0,
            chop_index=52.0,
            range_high=115.0,
            range_low=90.0,
            headroom_to_high_pct=10.0,
            headroom_to_low_pct=10.0,
            current_price=104.0
        )

        profiles = {"1d": p_1d, "4h": p_4h, "1h": p_1h, "15m": p_15m}
        # Price at 104: range_pos = (104 - 80) / (120 - 80) = 24 / 40 = 0.60 (trapped in middle 50%)
        eval_result = CrossTimeframeMatrixEngine.evaluate_matrix(profiles, current_price=104.0)

        self.assertFalse(eval_result["trade_permitted"])
        self.assertEqual(eval_result["strategy"], "CAPITAL_PRESERVATION_MIDDLE_CHOP_VETO")
        self.assertEqual(eval_result["dominant_direction"], "NO_TRADE")


if __name__ == "__main__":
    unittest.main()
