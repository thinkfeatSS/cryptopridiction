import unittest
import numpy as np
from typing import Dict, Any

from app.engine.signals.ensemble_regressor import FiveModelPriceRegressor
from app.engine.config import PRICE_CLUSTER_TOLERANCE_PCT


class MockRegressor:
    """Mock regressor that returns a pre-configured target return."""
    def __init__(self, ret: float):
        self.ret = ret

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.array([self.ret], dtype=np.float32)


class TestHighMarketVolatilityTargetClumping(unittest.TestCase):
    """
    Rigorously tests High Market Volatility Target Clumping:
    - If extreme market wicks widen ATR beyond standard ranges, price regressor modal consensus
      clustering dynamically scales its tolerance via (raw_atr * 0.25) to prevent cluster splintering.
    - Preserves standard baseline tolerance (0.20%) when volatility is normal.
    - Honors directional confluence under expanded volatility tolerance.
    - Handles dirty/invalid raw_atr inputs (NaN, Inf, negative, None) safely.
    - Enforces contract parity between cold-start and fitted predictions.
    """

    def setUp(self):
        self.reg = FiveModelPriceRegressor()
        self.current_price = 100.0
        self.standard_tolerance = self.current_price * PRICE_CLUSTER_TOLERANCE_PCT  # 0.20 USD

    def test_standard_volatility_baseline_tolerance(self):
        """Under normal/low volatility, tolerance defaults to standard PRICE_CLUSTER_TOLERANCE_PCT (0.20%)."""
        # raw_atr = 0.40 -> raw_atr * 0.25 = 0.10 <= 0.20 (baseline tolerance wins)
        self.reg.models = {
            "catboost": MockRegressor(0.010),
            "xgboost": MockRegressor(0.011),
            "hist_gb": MockRegressor(0.011),
            "extra_trees": MockRegressor(0.012),
            "random_forest": MockRegressor(0.012)
        }
        self.reg.is_fitted = True
        self.reg.fitted_models = list(self.reg.models.keys())

        res = self.reg.predict_price_live(
            X_live=np.zeros((1, 5)),
            current_price=self.current_price,
            raw_atr=0.40,
            expected_direction="LONG"
        )

        self.assertAlmostEqual(res["consensus_tolerance_usd"], self.standard_tolerance, places=4)
        self.assertEqual(res["winning_vote_count"], 5)
        self.assertEqual(res["cluster_agreement_pct"], 100.0)

    def test_extreme_wicks_dynamic_tolerance_scaling(self):
        """When extreme wicks widen ATR, tolerance dynamically scales via (raw_atr * 0.25)."""
        # Extreme volatility: raw_atr = 4.0 USD (4% of $100 price)
        # raw_atr * 0.25 = 1.0 USD >> 0.20 USD standard tolerance
        expected_vol_tolerance = 4.0 * 0.25  # 1.0 USD

        self.reg.models = {
            "catboost": MockRegressor(0.02),
            "xgboost": MockRegressor(0.02),
            "hist_gb": MockRegressor(0.02),
            "extra_trees": MockRegressor(0.02),
            "random_forest": MockRegressor(0.02)
        }
        self.reg.is_fitted = True
        self.reg.fitted_models = list(self.reg.models.keys())

        res = self.reg.predict_price_live(
            X_live=np.zeros((1, 5)),
            current_price=self.current_price,
            raw_atr=4.0,
            expected_direction="LONG"
        )

        self.assertAlmostEqual(res["consensus_tolerance_usd"], expected_vol_tolerance, places=4)
        self.assertGreater(res["consensus_tolerance_usd"], self.standard_tolerance)

    def test_cluster_splintering_prevention(self):
        """
        Crucial Forensic Test:
        Under high volatility, model predictions naturally disperse across a wider price span.
        Without dynamic tolerance, the cluster splinters into 1-vote singletons.
        With (raw_atr * 0.25), all proximate models coalesce into a 4-vote consensus.
        """
        # 4 Bullish models spaced 0.35 USD apart: 101.50, 101.85, 102.20, 102.55. 1 Bearish model: 98.00.
        # Step distance (0.35 USD) exceeds standard tolerance (0.20 USD), but is well within 1.0 USD.
        self.reg.models = {
            "catboost": MockRegressor(0.0150),      # 101.50
            "xgboost": MockRegressor(0.0185),       # 101.85
            "hist_gb": MockRegressor(0.0220),       # 102.20
            "extra_trees": MockRegressor(0.0255),   # 102.55
            "random_forest": MockRegressor(-0.0200) # 98.00 (Outlier)
        }
        self.reg.is_fitted = True
        self.reg.fitted_models = list(self.reg.models.keys())

        # 1. Simulation under static low tolerance (raw_atr = 0.1 -> tolerance = 0.20 USD)
        res_splintered = self.reg.predict_price_live(
            X_live=np.zeros((1, 5)),
            current_price=self.current_price,
            raw_atr=0.10,
            expected_direction="LONG"
        )
        # With tolerance = 0.20, distance between adjacent models is 0.35 > 0.20, so winning cluster has only 1 vote
        self.assertEqual(res_splintered["winning_vote_count"], 1, "Static tolerance must splinter dispersed models")

        # 2. Simulation under extreme volatility (raw_atr = 4.0 USD -> tolerance = 1.0 USD)
        res_cohesive = self.reg.predict_price_live(
            X_live=np.zeros((1, 5)),
            current_price=self.current_price,
            raw_atr=4.0,
            expected_direction="LONG"
        )
        # With tolerance = 1.0, distance between 101.85 or 102.20 and all other 3 bullish models is <= 1.0 USD!
        # All 4 bullish models coalesce into a single winning cluster of 4 votes!
        self.assertEqual(res_cohesive["winning_vote_count"], 4, "Dynamic tolerance must prevent cluster splintering")
        self.assertEqual(res_cohesive["cluster_agreement_pct"], 80.0)
        self.assertAlmostEqual(res_cohesive["consensus_tolerance_usd"], 1.0, places=4)
        self.assertEqual(res_cohesive["outlier_models"], ["random_forest"])
        self.assertTrue(res_cohesive["directional_confluence"])

    def test_directional_confluence_preservation_under_widened_tolerance(self):
        """Even under widened ATR tolerance, directional confluence breaks ties in favor of expected_direction."""
        # Bimodal distribution: 2 models Bullish (+3.0%), 2 models Bearish (-3.0%), 1 Flat (0.0%)
        self.reg.models = {
            "catboost": MockRegressor(0.03),
            "xgboost": MockRegressor(0.03),
            "hist_gb": MockRegressor(-0.03),
            "extra_trees": MockRegressor(-0.03),
            "random_forest": MockRegressor(0.00)
        }
        self.reg.is_fitted = True
        self.reg.fitted_models = list(self.reg.models.keys())

        # raw_atr = 3.0 -> tolerance = 0.75 USD (tight enough to keep +3% and -3% separate)
        res_bull = self.reg.predict_price_live(
            X_live=np.zeros((1, 5)),
            current_price=self.current_price,
            raw_atr=3.0,
            expected_direction="LONG"
        )
        self.assertGreater(res_bull["predicted_change_pct"], 0.0)
        self.assertTrue(res_bull["directional_confluence"])

        res_bear = self.reg.predict_price_live(
            X_live=np.zeros((1, 5)),
            current_price=self.current_price,
            raw_atr=3.0,
            expected_direction="SHORT"
        )
        self.assertLess(res_bear["predicted_change_pct"], 0.0)
        self.assertTrue(res_bear["directional_confluence"])

    def test_nan_inf_none_sanitization_for_raw_atr(self):
        """Dirty raw_atr values (NaN, Inf, None, negative) fail closed to standard baseline tolerance without error."""
        self.reg.models = {m: MockRegressor(0.01) for m in self.reg.models}
        self.reg.is_fitted = True
        self.reg.fitted_models = list(self.reg.models.keys())

        for dirty_val in [None, np.nan, np.inf, -5.0, 0.0, "invalid"]:
            res = self.reg.predict_price_live(
                X_live=np.zeros((1, 5)),
                current_price=self.current_price,
                raw_atr=dirty_val,
                expected_direction="LONG"
            )
            self.assertFalse(np.isnan(res["consensus_tolerance_usd"]))
            self.assertFalse(np.isinf(res["consensus_tolerance_usd"]))
            self.assertGreater(res["consensus_tolerance_usd"], 0.0)
            self.assertAlmostEqual(res["consensus_tolerance_usd"], self.standard_tolerance, places=4)

    def test_cold_start_tolerance_parity(self):
        """Cold-start predictions also calculate and return dynamic consensus_tolerance_usd."""
        self.reg.is_fitted = False
        res = self.reg.predict_price_live(
            X_live=None,
            current_price=self.current_price,
            raw_atr=4.0,
            expected_direction="LONG"
        )

        self.assertTrue(res["is_cold_start"])
        self.assertIn("consensus_tolerance_usd", res)
        self.assertAlmostEqual(res["consensus_tolerance_usd"], 1.0, places=4)
        self.assertEqual(res["outlier_models"], [])


if __name__ == "__main__":
    unittest.main()

