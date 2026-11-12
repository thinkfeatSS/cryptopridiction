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
from app.services.model_retrainer import purge_legacy_meta_models, get_model_status


class TestColdStartAndDiskCleanliness(unittest.TestCase):
    """
    Forensic verification suite for:
    1. Cold-Start Pairs:
       - < 15 candles engage Laplace Prior (Beta(1,1)) and Bayesian shrinkage return.
       - Capital protection: Gated from execution via COLD_START_HORIZON_ACCUMULATION.
       - Dynamic graduation upon 15th closed candle to full 5-model ensemble.
    2. Disk Cleanliness:
       - All legacy meta_classifier.joblib files purged.
       - Zero disk I/O and zero latency overhead from secondary meta-models.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_registry_instance = PerCoinModelRegistry._instance
        PerCoinModelRegistry._instance = None

    def tearDown(self):
        PerCoinModelRegistry._instance = self.orig_registry_instance
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_cold_start_laplace_prior_and_shrinkage(self):
        """Pairs with N < 15 candles engage Laplace prior (k+1)/(N+2) and Bayesian shrinkage."""
        clf = FiveModelDirectionClassifier()
        reg = FiveModelPriceRegressor()

        # N = 8 candles (5 green, 3 red)
        X = np.random.randn(8, 10).astype(np.float32)
        y_dir = np.array([1, 1, 0, 1, 1, 0, 1, 0], dtype=int)
        y_ret = np.array([0.01, 0.02, -0.01, 0.015, 0.005, -0.02, 0.03, -0.01], dtype=np.float32)

        is_fitted_clf = clf.fit(X, y_dir)
        is_fitted_reg = reg.fit(X, y_ret)

        self.assertFalse(is_fitted_clf, "Must not be fitted for N < 15")
        self.assertFalse(is_fitted_reg, "Must not be fitted for N < 15")
        self.assertTrue(clf.is_cold_start)
        self.assertTrue(reg.is_cold_start)

        # Expected Laplace: (5 + 1) / (8 + 2) = 6/10 = 0.60
        expected_p = 6.0 / 10.0
        self.assertAlmostEqual(clf.laplace_prob, expected_p, places=4)

        pred_clf = clf.predict_live(X[0])
        self.assertEqual(pred_clf["model_type"], "COLD_START_LAPLACE_PRIOR")
        self.assertAlmostEqual(pred_clf["prob_bullish"], expected_p, places=4)
        self.assertAlmostEqual(pred_clf["prob_bullish"] + pred_clf["prob_bearish"], 1.0000, places=4)

    def test_02_capital_protection_gate_blocks_cold_start_execution(self):
        """Signal generation strictly rejects under-accumulated cold-start coins to protect capital."""
        sig_sys = SignalGenerationSystem()

        # Sparse 15M DataFrame with only 6 candles (< 15)
        n_sparse = 6
        df_sparse = pd.DataFrame({
            "timestamp": np.arange(1700000000, 1700000000 + n_sparse * 900, 900),
            "open": [10.0 + i * 0.1 for i in range(n_sparse)],
            "high": [10.0 + i * 0.1 + 0.3 for i in range(n_sparse)],
            "low": [10.0 + i * 0.1 - 0.3 for i in range(n_sparse)],
            "close": [10.0 + (i + 1) * 0.1 for i in range(n_sparse)],
            "volume": [10000.0] * n_sparse
        })
        dfs_9 = {tf: df_sparse.copy() for tf in ["5m", "15m", "1h", "4h", "12h", "1d", "1w", "15d", "1M"]}

        btc_shield = {
            "status_code": "NORMAL",
            "altcoin_longs_allowed": True,
            "is_ntz_active": False,
            "regime": "NEUTRAL"
        }

        eval_res = sig_sys.evaluate_asset_multi_horizon(
            symbol="NEW_COLD_PAIR/USDT",
            dfs_9=dfs_9,
            btc_shield_state=btc_shield,
            live_price=10.6,
            volume_24h_usd=50_000_000.0
        )

        self.assertFalse(eval_res.get("is_trade_active"), "Cold-start pair must not have active trade")
        self.assertEqual(len(eval_res.get("qualified_signal_horizons", [])), 0, "No horizons can be qualified")
        
        conflicts = eval_res.get("trend_criteria_gates", {}).get("15M_gate", {}).get("conflicts", [])
        has_cold_gate = any("COLD_START_HORIZON_ACCUMULATION" in str(c) for c in conflicts)
        self.assertTrue(has_cold_gate, f"Must trigger COLD_START_HORIZON_ACCUMULATION rejection gate: {conflicts}")

    def test_03_dynamic_graduation_to_full_ensemble_on_15th_candle(self):
        """PerCoinModelRegistry automatically graduates from cold-start to full 5-model ensemble on N >= 15."""
        registry = PerCoinModelRegistry(base_models_dir=self.temp_dir)
        sym = "GRADUATING_COIN/USDT"
        tf = "15m"

        # Phase 1: N = 10 candles (Cold-start Laplace prior active)
        X_cold = np.random.randn(10, 8).astype(np.float32)
        y_dir_cold = np.array([1, 0, 1, 1, 0, 1, 0, 1, 1, 0], dtype=int)
        y_ret_cold = np.random.uniform(-0.01, 0.01, 10).astype(np.float32)

        clfs_c, regs_c, fresh_c = registry.get_or_train_coin_models(
            symbol=sym, tf=tf, X_train=X_cold, y_train_dir=y_dir_cold,
            y_train_ret=y_ret_cold, last_candle_ts=1000, ttl_seconds=300
        )
        self.assertTrue(fresh_c)
        self.assertTrue(clfs_c.is_cold_start)
        self.assertTrue(regs_c.is_cold_start)

        # Phase 2: 15th closed candle arrives -> N = 18 mature samples (Graduation!)
        X_mature = np.random.randn(18, 8).astype(np.float32)
        y_dir_mature = np.array([1, 0] * 9, dtype=int)
        y_ret_mature = np.random.uniform(-0.02, 0.02, 18).astype(np.float32)

        clfs_m, regs_m, fresh_m = registry.get_or_train_coin_models(
            symbol=sym, tf=tf, X_train=X_mature, y_train_dir=y_dir_mature,
            y_train_ret=y_ret_mature, last_candle_ts=2000, ttl_seconds=300
        )
        self.assertTrue(fresh_m, "Must re-train fresh when graduating from cold-start")
        self.assertFalse(clfs_m.is_cold_start, "Graduated classifier must not be cold-start")
        self.assertTrue(clfs_m.is_fitted, "Graduated classifier must be marked fitted")
        self.assertFalse(regs_m.is_cold_start, "Graduated regressor must not be cold-start")
        self.assertTrue(regs_m.is_fitted, "Graduated regressor must be marked fitted")

    def test_04_disk_cleanliness_purge_and_zero_meta_overhead(self):
        """Purge utility deletes all legacy meta_classifier.joblib files and reports zero meta overhead."""
        # Create a mock per-coin directory with dummy meta_classifier.joblib
        test_coin_dir = os.path.join(self.temp_dir, "per_coin", "DUMMY_COIN_USDT")
        os.makedirs(test_coin_dir, exist_ok=True)
        dummy_meta_path = os.path.join(test_coin_dir, "meta_classifier.joblib")
        with open(dummy_meta_path, "w") as f:
            f.write("mock legacy content")
        self.assertTrue(os.path.exists(dummy_meta_path))

        # Run purge
        purge_res = purge_legacy_meta_models(base_dir=self.temp_dir)
        self.assertTrue(purge_res["success"])
        self.assertEqual(purge_res["purged_count"], 1)
        self.assertFalse(os.path.exists(dummy_meta_path), "Legacy meta_classifier.joblib must be purged")

        # Verify get_model_status reports zero meta models overhead
        status = get_model_status()
        self.assertEqual(status["meta_models_overhead"], "0 (RETIRED)")
        self.assertIn("FiveModelDirectionClassifier", status["architecture"])


if __name__ == "__main__":
    unittest.main()
