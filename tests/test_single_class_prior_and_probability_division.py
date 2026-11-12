import unittest
import numpy as np
import pandas as pd
from app.engine.signals.meta_labeler import SingleClassPriorModel, CoinSpecificMetaLabeler, PurgedTimeSeriesSplit


class TestSingleClassPriorAndProbabilityDivision(unittest.TestCase):
    """
    Forensic test suite for SingleClassPriorModel and Probability Calculations.
    Verifies 100% resilience against division by zero, corrupted sample sizes,
    unusual input shapes, NaN/Inf values, and edge cases.
    """

    def test_01_single_class_prior_division_by_zero_protection(self):
        """Verify that negative and boundary sample sizes NEVER trigger ZeroDivisionError."""
        # sample_size = -2 would cause (-2 + 2.0) = 0.0 without protection
        m_neg2 = SingleClassPriorModel(target_class=1, sample_size=-2)
        self.assertAlmostEqual(m_neg2.prob, 0.50, delta=1e-4)

        m_neg100 = SingleClassPriorModel(target_class=1, sample_size=-100)
        self.assertAlmostEqual(m_neg100.prob, 0.50, delta=1e-4)

        m_zero = SingleClassPriorModel(target_class=1, sample_size=0)
        self.assertAlmostEqual(m_zero.prob, 0.50, delta=1e-4)

        m_zero_loss = SingleClassPriorModel(target_class=0, sample_size=0)
        self.assertAlmostEqual(m_zero_loss.prob, 0.50, delta=1e-4)

        m_none = SingleClassPriorModel(target_class=1, sample_size=None)
        self.assertAlmostEqual(m_none.prob, 0.50, delta=1e-4)

    def test_02_single_class_prior_target_class_robustness(self):
        """Verify non-standard target class types are handled safely."""
        m_str1 = SingleClassPriorModel(target_class="1", sample_size=3)
        self.assertEqual(m_str1.target_class, 1)
        self.assertAlmostEqual(m_str1.prob, 4.0 / 5.0, delta=1e-4)

        m_str_win = SingleClassPriorModel(target_class="WON", sample_size=3)
        self.assertEqual(m_str_win.target_class, 1)

        m_str0 = SingleClassPriorModel(target_class="0", sample_size=3)
        self.assertEqual(m_str0.target_class, 0)
        self.assertAlmostEqual(m_str0.prob, 1.0 / 5.0, delta=1e-4)

        m_invalid = SingleClassPriorModel(target_class="INVALID", sample_size=3)
        self.assertEqual(m_invalid.target_class, 0)

    def test_03_single_class_prior_predict_proba_shapes(self):
        """Verify predict_proba handles None, empty, 1D, and 2D inputs properly."""
        m = SingleClassPriorModel(target_class=1, sample_size=8)
        p1 = m.prob
        p0 = round(1.0 - p1, 6)

        # None input
        res_none = m.predict_proba(None)
        self.assertEqual(res_none.shape, (0, 2))

        # Empty array
        res_empty = m.predict_proba(np.empty((0, 25)))
        self.assertEqual(res_empty.shape, (0, 2))

        # Empty DataFrame
        res_empty_df = m.predict_proba(pd.DataFrame())
        self.assertEqual(res_empty_df.shape, (0, 2))

        # 1D feature array representing 1 sample
        feat_1d = np.ones(25)
        res_1d = m.predict_proba(feat_1d)
        self.assertEqual(res_1d.shape, (1, 2))
        self.assertAlmostEqual(res_1d[0, 1], p1, delta=1e-4)
        self.assertAlmostEqual(res_1d[0, 0], p0, delta=1e-4)

        # 2D array of 5 samples
        feat_2d = np.ones((5, 25))
        res_2d = m.predict_proba(feat_2d)
        self.assertEqual(res_2d.shape, (5, 2))
        for i in range(5):
            self.assertAlmostEqual(res_2d[i, 1], p1, delta=1e-4)

        # DataFrame of 3 samples
        df_3 = pd.DataFrame({"f1": [1, 2, 3], "f2": [4, 5, 6]})
        res_df = m.predict_proba(df_3)
        self.assertEqual(res_df.shape, (3, 2))

    def test_04_single_class_prior_estimator_contract(self):
        """Verify classes_ and predict() method adhere to scikit-learn classifier contract."""
        m = SingleClassPriorModel(target_class=1, sample_size=10)
        self.assertTrue(hasattr(m, "classes_"))
        self.assertEqual(list(m.classes_), [0, 1])

        # predict on single sample (prob ~ 0.9167 >= 0.50 -> 1)
        preds = m.predict(np.ones(25))
        self.assertEqual(len(preds), 1)
        self.assertEqual(preds[0], 1)

        # predict on loss model (prob ~ 0.0833 < 0.50 -> 0)
        m_loss = SingleClassPriorModel(target_class=0, sample_size=10)
        preds_loss = m_loss.predict(np.ones(25))
        self.assertEqual(len(preds_loss), 1)
        self.assertEqual(preds_loss[0], 0)

        # predict on empty
        preds_empty = m.predict(np.empty((0, 25)))
        self.assertEqual(len(preds_empty), 0)

    def test_05_purged_time_series_split_division_safety(self):
        """Verify PurgedTimeSeriesSplit does not divide by zero on edge splits or empty inputs."""
        # Empty input
        cv_empty = PurgedTimeSeriesSplit(n_splits=3)
        splits = list(cv_empty.split([]))
        self.assertEqual(len(splits), 0)

        # Small sample size
        cv_small = PurgedTimeSeriesSplit(n_splits=5)
        splits_small = list(cv_small.split(np.arange(3)))
        self.assertEqual(len(splits_small), 2)

        # n_splits = -1 edge case
        cv_neg = PurgedTimeSeriesSplit(n_splits=-1)
        self.assertGreaterEqual(cv_neg.n_splits, 1)

    def test_06_meta_labeler_extract_model_prob_safety(self):
        """Verify _extract_model_prob safely handles None, empty, NaN, and Inf."""
        class NanModel:
            classes_ = np.array([0, 1])
            def predict_proba(self, X):
                return np.array([[np.nan, np.nan]])

        class InfModel:
            classes_ = np.array([0, 1])
            def predict_proba(self, X):
                return np.array([[np.inf, np.inf]])

        class EmptyModel:
            classes_ = np.array([0, 1])
            def predict_proba(self, X):
                return np.empty((0, 2))

        # None model
        p_none = CoinSpecificMetaLabeler._extract_model_prob(None, pd.DataFrame(), default_prob=0.50)
        self.assertEqual(p_none, 0.50)

        # NaN model
        p_nan = CoinSpecificMetaLabeler._extract_model_prob(NanModel(), pd.DataFrame(), default_prob=0.50)
        self.assertEqual(p_nan, 0.50)

        # Inf model
        p_inf = CoinSpecificMetaLabeler._extract_model_prob(InfModel(), pd.DataFrame(), default_prob=0.50)
        self.assertEqual(p_inf, 0.50)

        # Empty output model
        p_empty = CoinSpecificMetaLabeler._extract_model_prob(EmptyModel(), pd.DataFrame(), default_prob=0.50)
        self.assertEqual(p_empty, 0.50)

    def test_07_meta_labeler_shrinkage_and_saerens_zero_division(self):
        """Verify Empirical Bayes shrinkage and Saerens shift do not divide by zero."""
        meta = CoinSpecificMetaLabeler()

        # Signal with entry_price == 0 or negative
        sig_data_zero_entry = {
            "entry_price": 0.0,
            "tp1_price": 105.0,
            "sl_price": 95.0,
            "direction": "LONG",
            "conviction": 80.0
        }
        prob, mtype, sz = meta.predict_coin_win_probability("BTC/USDT", sig_data_zero_entry)
        self.assertFalse(np.isnan(prob))
        self.assertFalse(np.isinf(prob))
        self.assertGreaterEqual(prob, 0.05)
        self.assertLessEqual(prob, 0.95)

        # Signal with identical entry and SL
        sig_data_zero_dist = {
            "entry_price": 100.0,
            "tp1_price": 100.0,
            "sl_price": 100.0,
            "direction": "LONG",
            "conviction": 80.0
        }
        prob2, mtype2, sz2 = meta.predict_coin_win_probability("ETH/USDT", sig_data_zero_dist)
        self.assertFalse(np.isnan(prob2))
        self.assertFalse(np.isinf(prob2))

    def test_08_evaluate_signal_economic_hurdle_zero_safety(self):
        """Verify evaluate_signal computes valid dynamic hurdles without dividing by zero."""
        meta = CoinSpecificMetaLabeler()
        eval_res = meta.evaluate_signal("BTC/USDT", {
            "entry_price": 0.0,
            "tp1_price": 0.0,
            "sl_price": 0.0,
            "conviction": 85.0
        })
        self.assertIn("win_probability", eval_res)
        self.assertFalse(np.isnan(eval_res["win_probability"]))
        self.assertIn("decision_hurdle", eval_res)
        self.assertFalse(np.isnan(eval_res["decision_hurdle"]))
        self.assertIn(eval_res["meta_verdict"], ["APPROVED", "FILTERED"])


if __name__ == "__main__":
    unittest.main()

