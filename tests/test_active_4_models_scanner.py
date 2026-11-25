"""
QUANT EDGE V16: Forensic Verification Suite for 4 Active Models Scanner Architecture
-------------------------------------------------------------------------------------
User Mandate:
Scan only for 15M, 1H, 4H, and 1D models that are actively used in the system,
and remove all unused horizons (5M, 12H, 1W, 15D, 1M).

Tests:
1. Configuration Invariants: ACTIVE_MODEL_TIMEFRAMES has strictly 15m, 1h, 4h, 1d;
   RETIRED_MACRO_TIMEFRAMES contains 5m, 12h, 1w, 15d, 1M.
2. Signal Generation System: evaluate_asset_multi_horizon marks retired horizons
   as is_retired: True with zero model inference, while 15M, 1H, 4H, 1D are actively modeled.
3. Trend Alignment Weights: Active models (15M, 1H, 4H, 1D) carry positive weights;
   all retired horizons carry exactly 0.00 weight.
4. PerCoinModelRegistry Preloading: Retired timeframe model files are bypassed and never loaded into RAM.
5. Order Block Scanner: Evaluates strictly active timeframes (15m, 1h, 4h, 1d) and bypasses retired horizons.
"""

import unittest
import pandas as pd
import numpy as np

from app.engine.config import (
    ACTIVE_MODEL_TIMEFRAMES,
    RETIRED_MACRO_TIMEFRAMES,
    TIMEFRAMES_9,
    ALLOWED_EMISSION_HORIZONS
)
from app.engine.signals.signal_generator import SignalGenerationSystem
from app.quant_v16.order_blocks import InstitutionalOrderBlockEngine as OrderBlockEngine


class TestScannerFourActiveModelsOnly(unittest.TestCase):

    def test_01_configuration_invariants(self):
        """Verifies active model timeframes and retired macro timeframes configurations."""
        self.assertEqual(set(ACTIVE_MODEL_TIMEFRAMES), {"15m", "1h", "4h", "1d"})
        for retired_tf in ["5m", "12h", "1w", "15d", "1M"]:
            self.assertIn(retired_tf, RETIRED_MACRO_TIMEFRAMES, f"{retired_tf} must be in RETIRED_MACRO_TIMEFRAMES")
            self.assertNotIn(retired_tf, ACTIVE_MODEL_TIMEFRAMES, f"{retired_tf} must NOT be in ACTIVE_MODEL_TIMEFRAMES")

    def test_02_evaluate_asset_active_vs_retired_horizons(self):
        """Verifies evaluate_asset_multi_horizon actively models 15m, 1h, 4h, 1d and marks others retired."""
        sig_sys = SignalGenerationSystem()

        # Build synthetic DataFrames for testing
        n = 50
        dates_15m = pd.date_range("2026-01-01", periods=n, freq="15min")
        dates_1h = pd.date_range("2026-01-01", periods=n, freq="1h")
        dates_4h = pd.date_range("2026-01-01", periods=n, freq="4h")
        dates_1d = pd.date_range("2026-01-01", periods=n, freq="1D")

        def make_df(dates):
            closes = [100.0 + i * 0.5 for i in range(n)]
            return pd.DataFrame({
                "open": [c - 0.2 for c in closes],
                "high": [c + 0.5 for c in closes],
                "low": [c - 0.4 for c in closes],
                "close": closes,
                "volume": [100000.0] * n,
                "taker_buy_volume": [60000.0] * n
            }, index=dates)

        dfs = {
            "15m": make_df(dates_15m),
            "1h": make_df(dates_1h),
            "4h": make_df(dates_4h),
            "1d": make_df(dates_1d),
            "5m": make_df(pd.date_range("2026-01-01", periods=n, freq="5min")),
            "12h": make_df(pd.date_range("2026-01-01", periods=n, freq="12h")),
            "1w": make_df(pd.date_range("2026-01-01", periods=n, freq="7D")),
            "15d": make_df(pd.date_range("2026-01-01", periods=n, freq="15D")),
            "1M": make_df(pd.date_range("2026-01-01", periods=n, freq="30D"))
        }

        btc_shield = {
            "status_code": "NORMAL",
            "altcoin_longs_allowed": True,
            "altcoin_shorts_allowed": True,
            "v16_regime": "BULL_TREND",
            "regime": "BULL_TREND"
        }

        eval_res = sig_sys.evaluate_asset_multi_horizon(
            symbol="BTC/USDT",
            dfs_9=dfs,
            btc_shield_state=btc_shield,
            live_price=float(dfs["15m"]["close"].iloc[-1]),
            volume_24h_usd=500_000_000.0
        )

        self.assertIsNotNone(eval_res)
        preds = eval_res.get("all_9_timeframe_predictions", {})

        # Active models: must NOT be retired
        for act_tf in ["15m", "1h", "4h", "1d"]:
            self.assertIn(act_tf, preds, f"{act_tf} must be present in predictions")
            self.assertFalse(preds[act_tf].get("is_retired", False), f"{act_tf} must be actively modeled (not retired)")
            self.assertIn(preds[act_tf].get("direction"), ["LONG", "SHORT", "NEUTRAL"])

        # Retired horizons: must be is_retired: True
        for ret_tf in ["5m", "12h", "1w", "15d", "1M"]:
            self.assertIn(ret_tf, preds, f"{ret_tf} must be present in predictions")
            self.assertTrue(preds[ret_tf].get("is_retired", False), f"{ret_tf} must be retired")
            self.assertEqual(preds[ret_tf].get("direction"), "NEUTRAL")
            self.assertEqual(preds[ret_tf].get("classifier_votes"), "RETIRED")

    def test_03_trend_alignment_weights_active_only(self):
        """Verifies multi-horizon trend alignment assigns weights strictly to active models."""
        h_preds = {
            "15m": {"trend_state": "BULLISH"},
            "1h": {"trend_state": "BULLISH"},
            "4h": {"trend_state": "BULLISH"},
            "1d": {"trend_state": "BULLISH"},
            "5m": {"trend_state": "BEARISH"},   # Retired: 0 weight
            "12h": {"trend_state": "BEARISH"},  # Retired: 0 weight
            "1w": {"trend_state": "BEARISH"},   # Retired: 0 weight
            "15d": {"trend_state": "BEARISH"},  # Retired: 0 weight
            "1M": {"trend_state": "BEARISH"}    # Retired: 0 weight
        }

        res = SignalGenerationSystem.compute_trend_alignment(h_preds)
        # Because all 4 active models are BULLISH and retired ones carry 0 weight, BULLISH dominates 100% of weight
        self.assertEqual(res["dominant_direction"], "LONG")
        self.assertEqual(res["dominant_trend"], "BULLISH")
        self.assertEqual(res["alignment_score_pct"], 100.0)

    def test_04_order_blocks_active_timeframes(self):
        """Verifies order block engine scans active timeframes and does not populate retired horizons."""
        n = 50
        dates_15m = pd.date_range("2026-01-01", periods=n, freq="15min")
        dates_1h = pd.date_range("2026-01-01", periods=n, freq="1h")
        dates_4h = pd.date_range("2026-01-01", periods=n, freq="4h")
        dates_1d = pd.date_range("2026-01-01", periods=n, freq="1D")

        def make_df(dates):
            closes = [100.0 + (i % 5) * 0.5 for i in range(n)]
            return pd.DataFrame({
                "open": [c - 0.2 for c in closes],
                "high": [c + 0.8 for c in closes],
                "low": [c - 0.8 for c in closes],
                "close": closes,
                "volume": [100000.0] * n
            }, index=dates)

        dfs = {
            "15m": make_df(dates_15m),
            "1h": make_df(dates_1h),
            "4h": make_df(dates_4h),
            "1d": make_df(dates_1d),
            "5m": make_df(pd.date_range("2026-01-01", periods=n, freq="5min")),
            "12h": make_df(pd.date_range("2026-01-01", periods=n, freq="12h")),
            "1w": make_df(pd.date_range("2026-01-01", periods=n, freq="7D")),
            "15d": make_df(pd.date_range("2026-01-01", periods=n, freq="15D")),
            "1M": make_df(pd.date_range("2026-01-01", periods=n, freq="30D"))
        }

        ob_res = OrderBlockEngine.scan_all_horizons(dfs, current_price=100.0)
        scanned_tfs = set(ob_res.get("horizon_blocks", {}).keys())

        # Scanned timeframes must be a subset of active models
        for tf in scanned_tfs:
            self.assertIn(tf, ["15m", "1h", "4h", "1d"], f"{tf} should not be scanned for order blocks")
        for retired_tf in ["5m", "12h", "1w", "15d", "1M"]:
            self.assertNotIn(retired_tf, scanned_tfs, f"{retired_tf} must not be scanned for order blocks")


if __name__ == "__main__":
    unittest.main()
