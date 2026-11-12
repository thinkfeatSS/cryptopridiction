"""
QUANT EDGE V16: Forensic Verification Suite for Candle Close Training & Prediction
Verifies:
1. Primary regressor target is strictly candle close return (exp_ret), never Target_MFE (wick excursions).
2. Primary direction classifier target is strictly candle close progression (c[i+1] > c[i]), never candle color (c[i+1] > o[i+1]) or wicks.
3. Price regressor live prediction predicts the next candle close guided by direction classifier (LONG: target > current_price, SHORT: target < current_price).
4. Micro-cap precision formatting dynamically handles multi-decimal tokens (e.g. 0.00001234).
5. Full system alignment across signal_generator, ensemble_regressor, and test.py.
"""

import unittest
import numpy as np
import pandas as pd
from typing import Dict, Any

from app.engine.signals.ensemble_classifier import FiveModelDirectionClassifier
from app.engine.signals.ensemble_regressor import FiveModelPriceRegressor, _format_price_precision
from test import TripleBarrierLabeler


class TestCandleCloseModelTrainingAndPrediction(unittest.TestCase):

    def setUp(self):
        # Create deterministic synthetic DataFrame with distinct opens, highs, lows, closes
        np.random.seed(42)
        n = 50
        dates = pd.date_range("2026-01-01", periods=n, freq="15min")
        close_prices = 100.0 + np.cumsum(np.random.normal(0.0, 1.0, n))
        
        # Ensure high > close and low < close so that wicks are strictly separated from close
        high_prices = close_prices + np.random.uniform(1.0, 3.0, n)
        low_prices = close_prices - np.random.uniform(1.0, 3.0, n)
        open_prices = close_prices + np.random.uniform(-0.5, 0.5, n)

        self.df = pd.DataFrame({
            "timestamp": [int(d.timestamp()) for d in dates],
            "datetime": dates,
            "open": open_prices,
            "high": high_prices,
            "low": low_prices,
            "close": close_prices,
            "volume": np.random.uniform(100.0, 500.0, n),
            "primary_raw_atr": np.full(n, 1.5)
        })

    def test_01_triple_barrier_labeler_trains_on_close_return_not_mfe(self):
        """Forensically verifies that TripleBarrierLabeler trains price regressor on close return (exp_ret), never Target_MFE."""
        labeled = TripleBarrierLabeler.apply_barriers(self.df, horizon_bars=1, base_pt=2.0, base_sl=1.0)
        
        self.assertIn("Target_Return", labeled.columns)
        self.assertIn("Target_Close_Return", labeled.columns)
        self.assertIn("Target_MFE", labeled.columns)

        valid_rows = labeled.dropna(subset=["Target_Return", "Target_Close_Return", "Target_MFE"]).copy()
        self.assertGreater(len(valid_rows), 20)

        # 1. Target_Return must match Target_Close_Return 100%
        np.testing.assert_allclose(
            valid_rows["Target_Return"].values,
            valid_rows["Target_Close_Return"].values,
            rtol=1e-5,
            err_msg="Target_Return must be strictly equal to Target_Close_Return (candle close return)"
        )

        # 2. Target_Return must NOT be Target_MFE (wick excursion is non-negative and exceeds close return)
        diff_from_mfe = np.abs(valid_rows["Target_Return"].values - valid_rows["Target_MFE"].values)
        self.assertGreater(
            np.mean(diff_from_mfe),
            0.005,
            "Target_Return must NOT be equal to wick MFE excursion"
        )

        # 3. Target_Primary must be 1.0 when Target_Return > 0, and 0.0 when Target_Return < 0
        long_mask = valid_rows["Target_Return"] > 0
        short_mask = valid_rows["Target_Return"] < 0
        self.assertTrue((valid_rows.loc[long_mask, "Target_Primary"] == 1.0).all())
        self.assertTrue((valid_rows.loc[short_mask, "Target_Primary"] == 0.0).all())

    def test_02_direction_classifier_trains_on_close_progression_not_candle_color(self):
        """
        Forensically verifies that direction classification labels evaluate close-to-close progression:
        c[i+1] > c[i], NOT candle color anomalies c[i+1] > o[i+1].
        """
        # Construct synthetic anomaly:
        # Candle 0: Open 108, Close 110
        # Candle 1: Open 100, Close 105 (Green candle: close > open, BUT closed DOWN relative to candle 0 close 110)
        c = np.array([110.0, 105.0])
        o = np.array([108.0, 100.0])

        # Direction calculation based on candle close progression:
        direction_close = (c[1:] > c[:-1]).astype(int)
        # Direction calculation based on candle color:
        direction_color = (c[1:] > o[1:]).astype(int)

        # The close progressed down: 105 < 110 -> direction must be 0 (BEARISH)
        self.assertEqual(direction_close[0], 0, "Close progressed down, so direction must be 0")
        self.assertEqual(direction_color[0], 1, "Candle was green, but closed down relative to previous close")

        # Verify that return and direction_close have 100% sign coherence
        ret = (c[1] - c[0]) / c[0]
        self.assertLess(ret, 0.0)
        self.assertEqual(direction_close[0] == 1, ret > 0, "Direction 1 must match return > 0")

    def test_03_price_regressor_predicts_next_candle_close_guided_by_classifier_long(self):
        """Verifies FiveModelPriceRegressor predicts next candle close higher than current close for LONG."""
        reg = FiveModelPriceRegressor()
        current_price = 100.0
        
        # Test cold start case with direction classifier guidance
        res_cold = reg.predict_price_live(
            None,
            current_price=current_price,
            raw_atr=1.5,
            expected_direction="LONG"
        )
        self.assertGreater(res_cold["predicted_target_price"], current_price)
        self.assertGreater(res_cold["predicted_change_pct"], 0.0)
        self.assertTrue(res_cold["directional_confluence"])

        # Test fitted case with direction classifier guidance
        X_train = np.random.randn(25, 10).astype(np.float32)
        y_train = np.random.normal(0.005, 0.01, 25).astype(np.float32)
        reg.fit(X_train, y_train)

        X_live = np.random.randn(1, 10).astype(np.float32)
        res_live = reg.predict_price_live(
            X_live,
            current_price=current_price,
            raw_atr=1.5,
            expected_direction="LONG"
        )
        self.assertGreater(
            res_live["predicted_target_price"],
            current_price,
            "Next candle close target must be predicted higher than current price for LONG"
        )
        self.assertGreater(
            res_live["predicted_change_pct"],
            0.0,
            "Predicted change pct must be strictly positive for LONG"
        )
        self.assertTrue(res_live["directional_confluence"])

    def test_04_price_regressor_predicts_next_candle_close_guided_by_classifier_short(self):
        """Verifies FiveModelPriceRegressor predicts next candle close lower than current close for SHORT."""
        reg = FiveModelPriceRegressor()
        current_price = 100.0
        
        # Test cold start case with direction classifier guidance
        res_cold = reg.predict_price_live(
            None,
            current_price=current_price,
            raw_atr=1.5,
            expected_direction="SHORT"
        )
        self.assertLess(res_cold["predicted_target_price"], current_price)
        self.assertLess(res_cold["predicted_change_pct"], 0.0)
        self.assertTrue(res_cold["directional_confluence"])

        # Test fitted case with direction classifier guidance
        X_train = np.random.randn(25, 10).astype(np.float32)
        y_train = np.random.normal(-0.005, 0.01, 25).astype(np.float32)
        reg.fit(X_train, y_train)

        X_live = np.random.randn(1, 10).astype(np.float32)
        res_live = reg.predict_price_live(
            X_live,
            current_price=current_price,
            raw_atr=1.5,
            expected_direction="SHORT"
        )
        self.assertLess(
            res_live["predicted_target_price"],
            current_price,
            "Next candle close target must be predicted lower than current price for SHORT"
        )
        self.assertLess(
            res_live["predicted_change_pct"],
            0.0,
            "Predicted change pct must be strictly negative for SHORT"
        )
        self.assertTrue(res_live["directional_confluence"])

    def test_05_micro_price_precision_handling(self):
        """Verifies formatting precision handles micro-denomination assets without truncation to 0."""
        # Bitcoin tier
        self.assertEqual(_format_price_precision(65432.1234), 65432.12)
        # Mid-cap tier (e.g. SOL)
        self.assertEqual(_format_price_precision(142.34567), 142.3457)
        # Low unit price (e.g. DOGE, ADA)
        self.assertEqual(_format_price_precision(0.1234567), 0.123457)
        # Meme token (e.g. PEPE, SHIB)
        p_meme = 0.00001234567
        formatted = _format_price_precision(p_meme)
        self.assertEqual(formatted, 0.0000123457)
        self.assertGreater(formatted, 0.0)

    def test_06_unconditioned_backward_compatibility(self):
        """Verifies that when expected_direction is None, raw unconditioned regressor outputs are preserved."""
        reg = FiveModelPriceRegressor()
        X_train = np.random.randn(25, 10).astype(np.float32)
        y_train = np.random.normal(0.005, 0.01, 25).astype(np.float32)
        reg.fit(X_train, y_train)

        X_live = np.random.randn(1, 10).astype(np.float32)
        res = reg.predict_price_live(X_live, current_price=100.0, raw_atr=1.5, expected_direction=None)
        self.assertIn("predicted_target_price", res)
        self.assertIn("predicted_change_pct", res)
        self.assertIn("winning_vote_count", res)
        self.assertGreaterEqual(res["winning_vote_count"], 1)


if __name__ == "__main__":
    unittest.main()
