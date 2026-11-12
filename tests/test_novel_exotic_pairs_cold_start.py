import os
import shutil
import tempfile
import unittest
import numpy as np
import pandas as pd

from app.engine.signals.ensemble_classifier import FiveModelDirectionClassifier
from app.engine.signals.ensemble_regressor import FiveModelPriceRegressor
from app.engine.signals.per_coin_models import PerCoinModelRegistry
from app.engine.signals.signal_generator import SignalGenerationSystem


class TestNovelExoticPairsColdStart(unittest.TestCase):
    """
    Rigorously tests Cold-Start Laplace Prior model convergence on novel exotic pairs
    and newly listed coins with fewer than 15 historical candles:
    - Beta(1, 1) prior: P = (k + 1) / (N + 2)
    - Bayesian shrinkage return: R = (sum_r + prior_r * 5) / (N + 5)
    - Single-class sequence resilience
    - Numerical stability against NaNs and Infs
    - Disk persistence & atomic retrieval in PerCoinModelRegistry
    - Dynamic graduation to full 5-model ensemble once N >= 15
    - End-to-end signal generator gating for novel exotic pairs
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_registry_instance = PerCoinModelRegistry._instance
        PerCoinModelRegistry._instance = None

    def tearDown(self):
        PerCoinModelRegistry._instance = self.orig_registry_instance
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_zero_candle_brand_new_listing_laplace_prior(self):
        """Pairs with 0 candles engage neutral Beta(1,1) Laplace prior (P = 0.50, ret = 0.003)."""
        clf = FiveModelDirectionClassifier()
        reg = FiveModelPriceRegressor()

        is_fitted_clf = clf.fit(None, None)
        is_fitted_reg = reg.fit(None, None)

        self.assertFalse(is_fitted_clf, "Classifier must not be marked fitted for N=0")
        self.assertFalse(is_fitted_reg, "Regressor must not be marked fitted for N=0")
        self.assertTrue(clf.is_cold_start, "Classifier must flag cold-start active")
        self.assertTrue(reg.is_cold_start, "Regressor must flag cold-start active")
        self.assertAlmostEqual(clf.laplace_prob, 0.50, places=4)
        self.assertAlmostEqual(reg.laplace_base_ret, 0.003, places=4)

        pred_clf = clf.predict_live(None)
        self.assertEqual(pred_clf["model_type"], "COLD_START_LAPLACE_PRIOR")
        self.assertTrue(pred_clf["is_cold_start"])
        self.assertEqual(pred_clf["sample_size"], 0)
        self.assertAlmostEqual(pred_clf["prob_bullish"], 0.50, places=4)
        self.assertAlmostEqual(pred_clf["prob_bearish"], 0.50, places=4)
        self.assertAlmostEqual(pred_clf["prob_bullish"] + pred_clf["prob_bearish"], 1.0000, places=4)

        pred_reg = reg.predict_price_live(None, current_price=10.0, expected_direction="LONG")
        self.assertEqual(pred_reg["model_type"], "COLD_START_LAPLACE_PRIOR")
        self.assertTrue(pred_reg["is_cold_start"])
        self.assertAlmostEqual(pred_reg["predicted_target_price"], 10.0 * 1.003, places=4)

    def test_novel_exotic_pairs_empirical_laplace_smoothing(self):
        """Pairs with 1 to 14 candles smoothly regularize probability towards Beta(1,1) prior."""
        clf = FiveModelDirectionClassifier()
        reg = FiveModelPriceRegressor()

        # N=7 candles: 5 green (k=5), 2 red
        X = np.random.randn(7, 10).astype(np.float32)
        y_dir = np.array([1, 1, 0, 1, 1, 0, 1], dtype=int)
        y_ret = np.array([0.01, 0.02, -0.01, 0.015, 0.005, -0.02, 0.03], dtype=np.float32)

        clf.fit(X, y_dir)
        reg.fit(X, y_ret)

        self.assertTrue(clf.is_cold_start)
        self.assertTrue(reg.is_cold_start)
        self.assertEqual(clf.sample_size, 7)
        self.assertEqual(reg.sample_size, 7)

        # Expected Laplace: (k + 1) / (N + 2) = (5 + 1) / (7 + 2) = 6/9 = 0.6667
        expected_p = (5.0 + 1.0) / (7.0 + 2.0)
        self.assertAlmostEqual(clf.laplace_prob, expected_p, places=4)

        # Expected Shrinkage: (sum_r + 0.003 * 5) / (7 + 5)
        expected_ret = (float(np.sum(y_ret)) + 0.015) / 12.0
        self.assertAlmostEqual(reg.laplace_base_ret, expected_ret, places=4)

        pred_clf = clf.predict_live(np.random.randn(1, 10))
        self.assertAlmostEqual(pred_clf["prob_bullish"], expected_p, places=4)
        self.assertAlmostEqual(pred_clf["prob_bullish"] + pred_clf["prob_bearish"], 1.0000, places=4)

    def test_single_class_sequence_smoothed_prior(self):
        """Pairs with exclusively green (or red) candles engage smoothed Laplace prior without crashing."""
        clf = FiveModelDirectionClassifier()

        # N=10 candles, all green (k=10, 0 red -> single class)
        X = np.random.randn(10, 8).astype(np.float32)
        y_dir = np.ones(10, dtype=int)

        is_fitted = clf.fit(X, y_dir)
        self.assertFalse(is_fitted, "Single class cannot train 5-model ensemble")
        self.assertTrue(clf.is_cold_start)

        # Expected Laplace: (10 + 1) / (10 + 2) = 11/12 = 0.9167
        expected_p = 11.0 / 12.0
        self.assertAlmostEqual(clf.laplace_prob, expected_p, places=4)

        pred = clf.predict_live(np.random.randn(1, 8))
        self.assertEqual(pred["decision"], "GREEN_BULLISH")
        self.assertEqual(pred["direction"], "LONG")
        self.assertAlmostEqual(pred["prob_bullish"], expected_p, places=4)

    def test_nan_and_inf_numerical_resilience(self):
        """Sanitizes dirty arrays containing NaNs and Infs cleanly without throwing exceptions."""
        clf = FiveModelDirectionClassifier()
        reg = FiveModelPriceRegressor()

        X_dirty = np.array([[np.nan, 1.0], [np.inf, -np.inf], [2.0, 3.0]], dtype=np.float32)
        y_dir_dirty = np.array([1.0, np.nan, 0.0])
        y_ret_dirty = np.array([np.nan, 0.05, -np.inf])

        # Must not raise ValueError or NaN error
        clf.fit(X_dirty, y_dir_dirty)
        reg.fit(X_dirty, y_ret_dirty)

        self.assertTrue(clf.is_cold_start)
        self.assertTrue(reg.is_cold_start)
        self.assertFalse(np.isnan(clf.laplace_prob))
        self.assertFalse(np.isnan(reg.laplace_base_ret))

        pred_clf = clf.predict_live(X_dirty[0])
        pred_reg = reg.predict_price_live(X_dirty[0], current_price=50.0)

        self.assertFalse(np.isnan(pred_clf["prob_bullish"]))
        self.assertFalse(np.isnan(pred_reg["predicted_target_price"]))

    def test_per_coin_model_registry_atomic_persistence_and_graduation(self):
        """PerCoinModelRegistry persists cold-start bundles and promotes them to full ensemble on N >= 15."""
        registry = PerCoinModelRegistry(base_models_dir=self.temp_dir)
        sym = "EXOTIC_PAIR/USDT"
        tf = "15m"

        # 1. Cold start with N=8 candles
        X_cold = np.random.randn(8, 10).astype(np.float32)
        y_dir_cold = np.array([1, 0, 1, 1, 0, 1, 0, 1], dtype=int)
        y_ret_cold = np.random.uniform(-0.01, 0.01, 8).astype(np.float32)

        clfs, regs, is_fresh = registry.get_or_train_coin_models(
            symbol=sym, tf=tf, X_train=X_cold, y_train_dir=y_dir_cold,
            y_train_ret=y_ret_cold, last_candle_ts=1000, ttl_seconds=300
        )
        self.assertTrue(is_fresh)
        self.assertTrue(clfs.is_cold_start)
        self.assertTrue(regs.is_cold_start)

        # Check disk persistence
        disk_path = registry.get_model_path(sym, tf)
        self.assertTrue(os.path.exists(disk_path), "Dedicated model bundle must exist on disk")

        # 2. Simulate new candles arriving: N=20 candles (Graduation!)
        X_mature = np.random.randn(20, 10).astype(np.float32)
        y_dir_mature = np.array([1, 0] * 10, dtype=int)
        y_ret_mature = np.random.uniform(-0.02, 0.02, 20).astype(np.float32)

        m_clfs, m_regs, m_fresh = registry.get_or_train_coin_models(
            symbol=sym, tf=tf, X_train=X_mature, y_train_dir=y_dir_mature,
            y_train_ret=y_ret_mature, last_candle_ts=2000, ttl_seconds=300
        )
        self.assertTrue(m_fresh, "Must freshly train when graduating from cold-start to full ensemble")
        self.assertFalse(m_clfs.is_cold_start, "Graduated model must not be cold-start")
        self.assertTrue(m_clfs.is_fitted, "Graduated model must be fitted")

    def test_signal_generator_novel_exotic_pairs_sparse_timeframes(self):
        """SignalGenerationSystem handles novel exotic pairs with < 5 candles across higher timeframes."""
        sig_sys = SignalGenerationSystem()

        # Build synthetic 9-horizon dataset where 15M has 60 candles, but 12H, 1D, 1W have < 5 candles
        n_dense = 60
        base_p = 25.0
        df_dense = pd.DataFrame({
            "timestamp": np.arange(1700000000, 1700000000 + n_dense * 900, 900),
            "open": [base_p + i * 0.1 for i in range(n_dense)],
            "high": [base_p + i * 0.1 + 0.3 for i in range(n_dense)],
            "low": [base_p + i * 0.1 - 0.3 for i in range(n_dense)],
            "close": [base_p + (i + 1) * 0.1 for i in range(n_dense)],
            "volume": [20000.0] * n_dense
        })

        # Sparse DataFrame with only 3 candles (< 5)
        n_sparse = 3
        df_sparse = pd.DataFrame({
            "timestamp": np.arange(1700000000, 1700000000 + n_sparse * 86400, 86400),
            "open": [base_p, base_p + 0.5, base_p + 1.0],
            "high": [base_p + 0.6, base_p + 1.1, base_p + 1.6],
            "low": [base_p - 0.4, base_p + 0.1, base_p + 0.6],
            "close": [base_p + 0.5, base_p + 1.0, base_p + 1.5],
            "volume": [50000.0] * n_sparse
        })

        dfs_exotic = {
            "5m": df_dense.copy(),
            "15m": df_dense.copy(),
            "1h": df_dense.copy(),
            "4h": df_dense.copy(),
            "12h": df_sparse.copy(),  # 3 candles
            "1d": df_sparse.copy(),   # 3 candles
            "1w": df_sparse.copy(),   # 3 candles
            "15d": None,              # 0 candles (brand new)
            "1M": None                # 0 candles (brand new)
        }

        res = sig_sys.evaluate_asset_multi_horizon(
            symbol="NOVEL_EXOTIC/USDT",
            dfs_9=dfs_exotic,
            btc_shield_state={"status_code": "NORMAL", "altcoin_longs_allowed": True},
            live_price=31.0
        )

        self.assertIsNotNone(res, "SignalGenerationSystem must not return None for sparse novel exotic pairs")
        h_preds = res["horizon_predictions"]

        # All 9 timeframes must be populated in horizon_predictions
        self.assertIn("12h", h_preds)
        self.assertIn("1d", h_preds)
        self.assertIn("1w", h_preds)
        self.assertIn("15d", h_preds)
        self.assertIn("1M", h_preds)

        self.assertTrue(h_preds["12h"]["is_cold_start"])
        self.assertEqual(h_preds["12h"]["candle_count"], 3)
        self.assertEqual(h_preds["12h"]["trend_state"], "CONSOLIDATION")

        self.assertTrue(h_preds["15d"]["is_cold_start"])
        self.assertEqual(h_preds["15d"]["candle_count"], 0)
        self.assertEqual(h_preds["15d"]["trend_state"], "CONSOLIDATION")

        # 24H Swing Gate must be safely locked until 1D empirical accumulation reaches 15 candles
        gates = res["trend_criteria_gates"]
        self.assertFalse(gates["24H_gate"]["qualified"], "24H Swing must be locked for novel exotic pair with N=3 on 1D")
        self.assertIn("COLD_START_HORIZON_ACCUMULATION", " ".join(gates["24H_gate"]["conflicts"]))

    def test_data_loader_pre_listing_historical_backfill_promotes_to_ensemble(self):
        """Newly listed token on Binance with < 15 candles backfills pre-listing candles from Bybit and graduates."""
        from app.engine.scanner.data_loader import MultiHorizonDataLoader
        from unittest.mock import MagicMock

        loader = MultiHorizonDataLoader()

        # Binance has only 4 candles on 15m (listed 1 hour ago)
        ts_base = 1700000000000
        df_binance = pd.DataFrame({
            "timestamp": [ts_base + i * 900000 for i in range(4)],
            "open": [10.0 + i * 0.1 for i in range(4)],
            "high": [10.2 + i * 0.1 for i in range(4)],
            "low": [9.9 + i * 0.1 for i in range(4)],
            "close": [10.1 + i * 0.1 for i in range(4)],
            "volume": [1000.0] * 4,
            "taker_buy_vol": [500.0] * 4
        })

        # Bybit has 20 candles prior to Binance listing
        df_bybit = pd.DataFrame({
            "timestamp": [ts_base - (20 - i) * 900000 for i in range(20)],
            "open": [9.0 + i * 0.05 for i in range(20)],
            "high": [9.2 + i * 0.05 for i in range(20)],
            "low": [8.9 + i * 0.05 for i in range(20)],
            "close": [9.1 + i * 0.05 for i in range(20)],
            "volume": [2000.0] * 20,
            "taker_buy_vol": [1000.0] * 20
        })
        df_bybit.attrs["exchange_source"] = "bybit_tier2"

        # Mock secondary venues
        loader._fetch_bybit_timeframe_raw = MagicMock(return_value=df_bybit)
        loader._fetch_okx_timeframe_raw = MagicMock(return_value=None)
        loader._fetch_mexc_timeframe_raw = MagicMock(return_value=None)
        loader._fetch_gateio_timeframe_raw = MagicMock(return_value=None)
        loader._fetch_kucoin_timeframe_raw = MagicMock(return_value=None)

        stitched = loader._backfill_historical_macro_candles("NOVEL_PAIR/USDT", "15m", df_binance, min_required=15)
        self.assertEqual(len(stitched), 24, "Must stitch 20 Bybit bars with 4 Binance bars (Total 24)")
        self.assertTrue(stitched.attrs.get("is_backfilled", False))
        self.assertEqual(stitched.attrs.get("native_candle_count"), 24)

        # Graduating model: with 24 candles, ensemble direction classifier can train
        clf = FiveModelDirectionClassifier()
        X_train = np.random.randn(24, 10).astype(np.float32)
        y_train = np.array([1, 0] * 12, dtype=int)
        fitted = clf.fit(X_train, y_train)
        self.assertTrue(fitted, "Classifier must graduate to fitted 5-model ensemble on N=24")
        self.assertFalse(clf.is_cold_start, "Model must not be cold-start after backfill graduation")

    def test_cross_exchange_exhaustive_cold_start_laplace_prior(self):
        """When an asset has < 15 candles worldwide, Cold-Start Laplace Prior engages smoothly."""
        clf = FiveModelDirectionClassifier()
        reg = FiveModelPriceRegressor()

        # Asset has genuinely 6 historical candles worldwide (3 bullish, 3 bearish)
        n_candles = 6
        X_train = np.random.randn(n_candles, 8).astype(np.float32)
        y_dir = np.array([1, 0, 1, 0, 1, 0], dtype=int)  # 3 green, 3 red
        y_ret = np.array([0.01, -0.01, 0.012, -0.008, 0.005, -0.006], dtype=np.float32)

        is_fitted_clf = clf.fit(X_train, y_dir)
        is_fitted_reg = reg.fit(X_train, y_ret)

        self.assertFalse(is_fitted_clf, "Must not fit full ensemble with N=6 < 15")
        self.assertFalse(is_fitted_reg, "Must not fit full ensemble with N=6 < 15")
        self.assertTrue(clf.is_cold_start)
        self.assertTrue(reg.is_cold_start)

        # Expected Laplace probability: (3 + 1) / (6 + 2) = 4 / 8 = 0.50
        self.assertAlmostEqual(clf.laplace_prob, 0.50, places=4)
        pred_clf = clf.predict_live(X_train[0])
        self.assertEqual(pred_clf["model_type"], "COLD_START_LAPLACE_PRIOR")
        self.assertAlmostEqual(pred_clf["prob_bullish"], 0.50, places=2)
        self.assertAlmostEqual(pred_clf["prob_bearish"], 0.50, places=2)

        # Regressor Bayesian shrinkage return: (sum_r + 0.003 * 5) / (6 + 5)
        expected_ret = (float(np.sum(y_ret)) + 0.015) / 11.0
        self.assertAlmostEqual(reg.laplace_base_ret, expected_ret, places=4)


if __name__ == "__main__":
    unittest.main()

