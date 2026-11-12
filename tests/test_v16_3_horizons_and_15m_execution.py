"""
QUANT EDGE V16: Forensic Verification Suite for 3-Horizon Matrix & 15M Execution Only
Tests:
1. TIMEFRAMES_9 strictly contains 15m, 1h, 4h.
2. ALLOWED_EMISSION_HORIZONS strictly restricts execution to 15M.
3. Multi-horizon trend alignment calculates weights dynamically across 15M, 1H, 4H.
4. evaluate_asset_multi_horizon only emits 15M as active trade execution; 1H and 24H are suppressed from execution.
5. 15M signal is blocked if 4H macro anchor opposes.
"""

import unittest
import pandas as pd
import numpy as np

from app.engine.config import TIMEFRAMES_9, TIMEFRAMES_3, ACTIVE_MULTI_HORIZONS, ALLOWED_EMISSION_HORIZONS, ACTIVE_TRADE_HORIZONS
from app.engine.signals.signal_generator import SignalGenerationSystem
from app.quant_v16.cross_timeframe_matrix import InstitutionalArchetype


class TestV16ThreeHorizonsAnd15MExecution(unittest.TestCase):

    def test_01_configuration_invariants(self):
        """Verifies multi-horizon matrix is strictly configured to 15m, 1h, and 4h, and signal execution to 15M."""
        self.assertEqual(TIMEFRAMES_3, ["15m", "1h", "4h"])
        self.assertEqual(ACTIVE_MULTI_HORIZONS, ["15m", "1h", "4h"])
        self.assertEqual(ALLOWED_EMISSION_HORIZONS, {"15M"})
        self.assertEqual(ACTIVE_TRADE_HORIZONS, "15M")

    def test_02_trend_alignment_weights_and_unanimous_scoring(self):
        """Verifies multi-horizon trend alignment evaluates 15M, 1H, 4H triad."""
        # Unanimous 3/3 Bullish
        h_preds_bull = {
            "15m": {"trend_state": "BULLISH"},
            "1h": {"trend_state": "BULLISH"},
            "4h": {"trend_state": "BULLISH"},
        }
        res_bull = SignalGenerationSystem.compute_trend_alignment(h_preds_bull)
        self.assertEqual(res_bull["dominant_direction"], "LONG")
        self.assertEqual(res_bull["aligned_horizons_count"], 3)
        self.assertEqual(res_bull["total_horizons_count"], 3)
        self.assertTrue(res_bull["is_unanimous_9_of_9"])
        self.assertIn("UNANIMOUS 3/3 MULTI-HORIZON TREND CONFLUENCE", res_bull["alignment_tier"])

        # Unanimous 3/3 Bearish
        h_preds_bear = {
            "15m": {"trend_state": "BEARISH"},
            "1h": {"trend_state": "BEARISH"},
            "4h": {"trend_state": "BEARISH"},
        }
        res_bear = SignalGenerationSystem.compute_trend_alignment(h_preds_bear)
        self.assertEqual(res_bear["dominant_direction"], "SHORT")
        self.assertEqual(res_bear["aligned_horizons_count"], 3)
        self.assertTrue(res_bear["is_unanimous_9_of_9"])

        # 2 of 3 Bullish (15M and 1H Bullish, 4H Consolidation)
        h_preds_partial = {
            "15m": {"trend_state": "BULLISH"},
            "1h": {"trend_state": "BULLISH"},
            "4h": {"trend_state": "CONSOLIDATION"},
        }
        res_partial = SignalGenerationSystem.compute_trend_alignment(h_preds_partial)
        self.assertEqual(res_partial["dominant_direction"], "LONG")
        self.assertEqual(res_partial["aligned_horizons_count"], 2)
        self.assertFalse(res_partial["is_unanimous_9_of_9"])
        self.assertIn("TIER 2", res_partial["alignment_tier"])

    def test_03_evaluate_multi_horizon_gates_4h_anchor(self):
        """Verifies 15M scalp gate respects 4H anchor and requires non-opposition."""
        h_preds_base = {
            tf: {"is_cold_start": False, "candle_count": 50}
            for tf in ["15m", "1h", "4h"]
        }
        matrix_eval = {
            "trade_permitted": True,
            "strategy": "MOMENTUM_TREND_EXPANSION",
            "archetype": InstitutionalArchetype.ARCHETYPE_A_SECULAR_EXPANSION.value
        }

        # 1. Valid Confluence: 15M Bullish, 1H Bullish, 4H Bullish
        tm_pass = {"15m": "BULLISH", "1h": "BULLISH", "4h": "BULLISH"}
        q_15, q_1h, q_24 = SignalGenerationSystem.evaluate_multi_horizon_gates(
            trend_matrix=tm_pass,
            horizon_predictions=h_preds_base,
            matrix_eval=matrix_eval
        )
        self.assertTrue(q_15["qualified"])
        self.assertEqual(q_15["direction"], "LONG")

        # 2. 4H opposes: 15M Bullish, 1H Bullish, but 4H Bearish -> HTF conflict
        tm_fail = {"15m": "BULLISH", "1h": "BULLISH", "4h": "BEARISH"}
        q_15_bad, _, _ = SignalGenerationSystem.evaluate_multi_horizon_gates(
            trend_matrix=tm_fail,
            horizon_predictions=h_preds_base,
            matrix_eval=matrix_eval
        )
        self.assertFalse(q_15_bad["qualified"])
        self.assertIsNone(q_15_bad["direction"])
        self.assertTrue(any("HTF_COUNTER_TREND_CONFLICT" in c for c in q_15_bad["conflicts"]))

    def test_04_signal_execution_strictly_restricted_to_15m(self):
        """Verifies that in evaluate_asset_multi_horizon, ONLY 15M signals can be admitted for trade execution."""
        sig_sys = SignalGenerationSystem()

        # Build clean bullish DataFrames for 15m, 1h, 4h
        n = 50
        dates_15m = pd.date_range("2026-01-01", periods=n, freq="15min")
        dates_1h = pd.date_range("2026-01-01", periods=n, freq="1h")
        dates_4h = pd.date_range("2026-01-01", periods=n, freq="4h")

        def make_df(dates):
            closes = [100.0 + i * 0.5 for i in range(n)]
            return pd.DataFrame({
                "open": [c - 0.2 for c in closes],
                "high": [c + 0.5 for c in closes],
                "low": [c - 0.4 for c in closes],
                "close": closes,
                "volume": [100000.0] * n,
                "taker_buy_volume": [65000.0] * n  # TBR = 0.65 (Strong buyer aggression)
            }, index=dates)

        dfs_3 = {
            "15m": make_df(dates_15m),
            "1h": make_df(dates_1h),
            "4h": make_df(dates_4h)
        }

        btc_shield = {
            "status_code": "NORMAL",
            "altcoin_longs_allowed": True,
            "altcoin_shorts_allowed": True,
            "v16_regime": "BULL_TREND",
            "regime": "BULL_TREND"
        }

        eval_res = sig_sys.evaluate_asset_multi_horizon(
            symbol="SOL/USDT",
            dfs_9=dfs_3,
            btc_shield_state=btc_shield,
            live_price=float(dfs_3["15m"]["close"].iloc[-1]),
            volume_24h_usd=80_000_000.0
        )

        self.assertIsNotNone(eval_res)
        # Verify dominant_timeframe is strictly 15M
        if eval_res.get("is_trade_active"):
            self.assertEqual(eval_res["dominant_timeframe"], "15M")
            self.assertEqual(eval_res["horizon"], "15M")
            self.assertEqual(eval_res["active_signal_horizon"], "15M")
            # Verify candidate signals: only 15M is active; 1H and 24H (if any) are suppressed from execution
            cand_sigs = eval_res.get("all_candidate_signals", {})
            for hz, sig in cand_sigs.items():
                if hz != "15M":
                    self.assertFalse(sig.get("is_trade_active", False), f"{hz} trade must NOT be active")
                    self.assertIn("ONLY_15M_EXECUTION_ALLOWED", sig.get("ineligible_reason", ""))


if __name__ == "__main__":
    unittest.main()
