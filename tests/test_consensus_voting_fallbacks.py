import unittest
from unittest.mock import MagicMock
import numpy as np
import pandas as pd
from app.engine.signals.ensemble_classifier import FiveModelDirectionClassifier
from app.engine.signals.signal_generator import SignalGenerationSystem


class TestConsensusVotingFallbacks(unittest.TestCase):
    """
    Forensic test suite for FiveModelDirectionClassifier Consensus Voting & Fallbacks.
    Verifies elimination of hardcoded 0.55/0.58/0.45 fallbacks, enforcement of dynamic
    peer consensus during partial model outages, and strict 0.50 neutral cold-start priors.
    """

    def test_01_unfitted_initialization_zero_bias(self):
        """Verify FiveModelDirectionClassifier initializes with strict 0.50 neutral prior (no 0.55 bias)."""
        clf = FiveModelDirectionClassifier()
        self.assertEqual(clf.baseline_prob, 0.50)
        self.assertEqual(clf.last_y_mean, 0.50)
        self.assertEqual(clf.laplace_prob, 0.50)
        self.assertTrue(clf.is_cold_start)
        self.assertFalse(clf.is_fitted)

        # Cold start prediction without data
        res = clf.predict_live(np.zeros((1, 10)))
        self.assertEqual(res["consensus_probability"], 0.50)
        self.assertEqual(res["prob_bullish"], 0.50)
        self.assertEqual(res["prob_bearish"], 0.50)
        self.assertEqual(res["model_type"], "COLD_START_LAPLACE_PRIOR")

    def test_02_laplace_cold_start_dynamic_scaling(self):
        """Verify Laplace prior scales dynamically with observations without hardcoded constants."""
        clf = FiveModelDirectionClassifier()
        
        # 5 samples: 4 bullish (y=1), 1 bearish (y=0)
        # Laplace smoothing Beta(1,1): (4 + 1) / (5 + 2) = 5/7 ~ 0.7143
        X_tiny = np.ones((5, 10))
        y_tiny = np.array([1, 1, 1, 1, 0])
        clf.fit(X_tiny, y_tiny)
        self.assertTrue(clf.is_cold_start)  # < 15 samples triggers cold start prior
        self.assertAlmostEqual(clf.laplace_prob, 5.0 / 7.0, places=3)

        res = clf.predict_live(np.ones((1, 10)))
        self.assertEqual(res["decision"], "GREEN_BULLISH")
        self.assertEqual(res["direction"], "LONG")
        self.assertAlmostEqual(res["prob_bullish"], 5.0 / 7.0, places=3)
        self.assertAlmostEqual(res["prob_bearish"], 1.0 - (5.0 / 7.0), places=3)

    def test_03_dynamic_peer_consensus_fallback_on_partial_failure(self):
        """
        Verify that when 1 or 2 models fail during live prediction,
        they dynamically adopt the live peer consensus of the successful models,
        rather than diluting the ensemble with a static historical prior or hardcoded 0.55.
        """
        clf = FiveModelDirectionClassifier()
        clf.is_fitted = True
        clf.fitted_models = list(clf.models.keys())
        clf.last_y_mean = 0.40  # Historical prior was bearish (40%)

        # Mock 4 models succeeding with strong bullish predictions (prob ~ 0.85)
        for m_name in ["catboost", "xgboost", "hist_gb", "extra_trees"]:
            m_mock = MagicMock()
            m_mock.predict_proba.return_value = np.array([[0.15, 0.85]])
            m_mock.classes_ = np.array([0, 1])
            m_mock.n_features_in_ = 10
            clf.models[m_name] = m_mock

        # Mock random_forest failing with an exception
        rf_mock = MagicMock()
        rf_mock.predict_proba.side_effect = RuntimeError("GPU memory allocation failure")
        rf_mock.classes_ = np.array([0, 1])
        rf_mock.n_features_in_ = 10
        clf.models["random_forest"] = rf_mock

        res = clf.predict_live(np.ones((1, 10)))
        
        # The failing model should have adopted the live peer consensus (0.85), NOT 0.40 or 0.55!
        rf_breakdown = res["model_breakdown"]["random_forest"]
        self.assertEqual(rf_breakdown["vote"], "GREEN_BULLISH")
        self.assertAlmostEqual(rf_breakdown["prob_bullish"], 0.85, places=2)
        self.assertIn("fallback_note", rf_breakdown)

        # Full unanimous consensus preserved
        self.assertEqual(res["bullish_votes"], 5)
        self.assertEqual(res["decision"], "GREEN_BULLISH")
        self.assertAlmostEqual(res["consensus_probability"], 0.85, places=2)

    def test_04_all_models_failing_falls_back_to_dynamic_laplace_prior(self):
        """Verify that if ALL 5 models fail, ensemble falls back to dynamic Laplace prior."""
        clf = FiveModelDirectionClassifier()
        clf.is_fitted = True
        clf.fitted_models = list(clf.models.keys())
        clf.laplace_prob = 0.62  # Calibrated prior

        for m_name in clf.models.keys():
            m_mock = MagicMock()
            m_mock.predict_proba.side_effect = RuntimeError("All models offline")
            m_mock.n_features_in_ = 10
            clf.models[m_name] = m_mock

        res = clf.predict_live(np.ones((1, 10)))
        self.assertEqual(res["decision"], "GREEN_BULLISH")
        self.assertAlmostEqual(res["consensus_probability"], 0.62, places=2)
        for m_name in clf.models.keys():
            self.assertAlmostEqual(res["model_breakdown"][m_name]["prob_bullish"], 0.62, places=2)

    def test_05_probability_coherence_and_monotonicity(self):
        """Verify P(bull) + P(bear) = 1.0 and consensus probability >= 0.50."""
        clf = FiveModelDirectionClassifier()
        clf.is_fitted = True
        clf.fitted_models = list(clf.models.keys())

        # Mock mixed vote: 3 bullish (0.60), 2 bearish (0.35)
        for m_name in ["catboost", "xgboost", "hist_gb"]:
            m_mock = MagicMock()
            m_mock.predict_proba.return_value = np.array([[0.40, 0.60]])
            m_mock.classes_ = np.array([0, 1])
            m_mock.n_features_in_ = 10
            clf.models[m_name] = m_mock

        for m_name in ["extra_trees", "random_forest"]:
            m_mock = MagicMock()
            m_mock.predict_proba.return_value = np.array([[0.65, 0.35]])
            m_mock.classes_ = np.array([0, 1])
            m_mock.n_features_in_ = 10
            clf.models[m_name] = m_mock

        res = clf.predict_live(np.ones((1, 10)))
        self.assertEqual(res["decision"], "GREEN_BULLISH")
        self.assertEqual(res["bullish_votes"], 3)
        self.assertEqual(res["bearish_votes"], 2)
        self.assertAlmostEqual(res["prob_bullish"] + res["prob_bearish"], 1.0, places=4)
        self.assertGreaterEqual(res["consensus_probability"], 0.50)


if __name__ == "__main__":
    unittest.main()

