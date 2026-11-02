import os
import time
import unittest
import numpy as np
import pandas as pd
from typing import Dict, Any

from app.engine.signals.ensemble_classifier import FiveModelDirectionClassifier
from app.engine.signals.ensemble_regressor import FiveModelPriceRegressor
from app.engine.signals.candle_features import CandleDynamicsFeatureExtractor
from app.engine.signals.meta_labeler import CoinSpecificMetaLabeler
from app.engine.signals.per_coin_models import PerCoinModelRegistry
from app.engine.signals.signal_generator import SignalGenerationSystem

class TestModelClassificationAndRegression(unittest.TestCase):
    """
    Forensic Verification Suite for Classification & Regression Models:
    - FiveModelDirectionClassifier: shape robustness, safe predict_proba indexing, direction probability alignment
    - FiveModelPriceRegressor: shape robustness, direction-confluent modal consensus clustering, variance tie-breaking
    - CandleDynamicsFeatureExtractor: inf/nan sanitization, no SettingWithCopy warnings
    - CoinSpecificMetaLabeler: dynamic meta-feature extraction, zero hardcoded setup flags
    - SignalGenerationSystem: zero-lookahead training sequences, path probability coherence
    """

    def setUp(self):
        np.random.seed(42)
        # Generate synthetic realistic OHLCV
        n = 60
        base_p = 100.0
        returns = np.random.normal(0.001, 0.015, n)
        closes = base_p * np.cumprod(1.0 + returns)
        opens = np.roll(closes, 1)
        opens[0] = base_p
        highs = np.maximum(opens, closes) + np.random.uniform(0.1, 0.5, n)
        lows = np.minimum(opens, closes) - np.random.uniform(0.1, 0.5, n)
        volumes = np.random.uniform(1000.0, 50000.0, n)

        self.df_synthetic = pd.DataFrame({
            "timestamp": np.arange(1700000000, 1700000000 + n * 300, 300),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes
        })

    def test_classifier_input_shape_robustness(self):
        """Tests that classifier accepts both 1D and 2D arrays without crashing."""
        clf = FiveModelDirectionClassifier()
        # Train on synthetic data
        X_train = np.random.randn(30, 20).astype(np.float32)
        y_train = np.random.choice([0, 1], size=30)
        fit_ok = clf.fit(X_train, y_train)
        self.assertTrue(fit_ok)

        # 1. 2D array input of shape (1, 20)
        x_2d = np.random.randn(1, 20).astype(np.float32)
        res_2d = clf.predict_live(x_2d)
        self.assertIn("direction", res_2d)
        self.assertIn(res_2d["direction"], ["LONG", "SHORT"])

        # 2. 1D array input of shape (20,)
        x_1d = np.random.randn(20).astype(np.float32)
        res_1d = clf.predict_live(x_1d)
        self.assertIn("direction", res_1d)
        self.assertIn(res_1d["direction"], ["LONG", "SHORT"])
        self.assertGreaterEqual(res_1d["consensus_probability"], 0.50)

    def test_classifier_inf_nan_sanitization(self):
        """Tests that classifier sanitizes NaNs and Infs during fit and predict."""
        clf = FiveModelDirectionClassifier()
        X_dirty = np.random.randn(30, 15).astype(np.float32)
        X_dirty[0, 0] = np.nan
        X_dirty[1, 1] = np.inf
        X_dirty[2, 2] = -np.inf
        y_train = np.random.choice([0, 1], size=30)

        fit_ok = clf.fit(X_dirty, y_train)
        self.assertTrue(fit_ok)

        x_live_dirty = np.full((1, 15), np.nan)
        res = clf.predict_live(x_live_dirty)
        self.assertIn("direction", res)
        self.assertGreaterEqual(res["consensus_probability"], 0.50)

    def test_classifier_short_consensus_probability_alignment(self):
        """Tests that when direction is SHORT, consensus_probability represents confidence in SHORT."""
        clf = FiveModelDirectionClassifier()
        # Train on predominantly bearish labels
        X_train = np.random.randn(40, 10).astype(np.float32)
        y_train = np.zeros(40, dtype=int)
        y_train[:5] = 1 # 35 red, 5 green

        fit_ok = clf.fit(X_train, y_train)
        self.assertTrue(fit_ok)

        x_live = np.zeros((1, 10), dtype=np.float32)
        res = clf.predict_live(x_live)
        if res["direction"] == "SHORT":
            # For SHORT, consensus_probability must be >= 0.50, not the raw bullish fraction
            self.assertGreaterEqual(res["consensus_probability"], 0.50)
            self.assertLessEqual(res["prob_bullish"], 0.50)
            self.assertAlmostEqual(res["consensus_probability"] + res["prob_bullish"], 1.0, places=1)

    def test_regressor_input_shape_robustness(self):
        """Tests that regressor accepts both 1D and 2D arrays without crashing."""
        reg = FiveModelPriceRegressor()
        X_train = np.random.randn(30, 20).astype(np.float32)
        y_ret = np.random.normal(0.005, 0.02, 30).astype(np.float32)
        fit_ok = reg.fit(X_train, y_ret)
        self.assertTrue(fit_ok)

        # 1. 2D array input
        x_2d = np.random.randn(1, 20).astype(np.float32)
        res_2d = reg.predict_price_live(x_2d, current_price=100.0, raw_atr=1.5)
        self.assertGreater(res_2d["predicted_target_price"], 0.0)

        # 2. 1D array input
        x_1d = np.random.randn(20).astype(np.float32)
        res_1d = reg.predict_price_live(x_1d, current_price=100.0, raw_atr=1.5)
        self.assertGreater(res_1d["predicted_target_price"], 0.0)

    def test_regressor_direction_confluent_modal_clustering(self):
        """Tests that modal clustering honors expected_direction when resolving candidate price clusters."""
        reg = FiveModelPriceRegressor()
        # Mock models dictionary to simulate a bimodal prediction: 2 models Bullish (+2%), 2 models Bearish (-2%), 1 Flat (0%)
        class MockModel:
            def __init__(self, ret):
                self.ret = ret
            def predict(self, X):
                return np.array([self.ret])

        reg.models = {
            "catboost": MockModel(0.02),
            "xgboost": MockModel(0.02),
            "hist_gb": MockModel(-0.02),
            "extra_trees": MockModel(-0.02),
            "random_forest": MockModel(0.00)
        }
        reg.is_fitted = True
        reg.fitted_models = list(reg.models.keys())

        x_live = np.zeros((1, 5))
        # Case A: Classifier voted LONG -> Regressor must select the Bullish cluster (+2%)
        res_long = reg.predict_price_live(x_live, current_price=100.0, raw_atr=0.1, expected_direction="LONG")
        self.assertGreater(res_long["predicted_change_pct"], 0.0)
        self.assertTrue(res_long["directional_confluence"])

        # Case B: Classifier voted SHORT -> Regressor must select the Bearish cluster (-2%)
        res_short = reg.predict_price_live(x_live, current_price=100.0, raw_atr=0.1, expected_direction="SHORT")
        self.assertLess(res_short["predicted_change_pct"], 0.0)
        self.assertTrue(res_short["directional_confluence"])

    def test_feature_extractor_inf_and_nan_cleaning(self):
        """Tests that CandleDynamicsFeatureExtractor cleans infs and does not raise warnings."""
        extractor = CandleDynamicsFeatureExtractor()
        df = self.df_synthetic.copy()
        # Introduce zero volume and identical high/low to stress test divisions
        df.loc[5, "volume"] = 0.0
        df.loc[6, "high"] = df.loc[6, "low"]

        feats = extractor.extract_features(df, prefix="15m")
        self.assertFalse(feats.empty)
        # Assert no NaNs or Infs exist in output
        self.assertEqual(feats.isna().sum().sum(), 0)
        self.assertEqual(np.isinf(feats.values).sum(), 0)

    def test_meta_labeler_dynamic_feature_extraction(self):
        """Tests that CoinSpecificMetaLabeler extracts all 25 features dynamically without hardcoded constants."""
        labeler = CoinSpecificMetaLabeler()

        # Signal A: Institutional Order Block
        sig_ob = {
            "conviction": 90.0,
            "expected_return_pct": 3.5,
            "quality_grade": "💎 Grade A+ (ORDER-BLOCK RETEST)",
            "horizon": "1H",
            "direction": "LONG",
            "entry_price": 100.0,
            "tp1_price": 104.0,
            "sl_price": 98.0,
            "canonical_strategy": "ORDER_BLOCK_LONG",
            "decision": "🎯 INSTITUTIONAL ORDER-BLOCK RETEST (LONG)",
            "is_order_block_signal": True
        }
        feats_ob = labeler.build_meta_feature_vector("BTC/USDT", sig_ob)
        self.assertEqual(feats_ob["is_order_block"].iloc[0], 1.0)
        self.assertEqual(feats_ob["is_squeeze"].iloc[0], 0.0)
        self.assertEqual(feats_ob["is_long"].iloc[0], 1.0)

        # Signal B: Squeeze Expansion
        sig_sq = {
            "conviction": 85.0,
            "expected_return_pct": 2.8,
            "quality_grade": "⚡ Grade A+ (SQUEEZE EXPANSION)",
            "horizon": "15M",
            "direction": "SHORT",
            "entry_price": 100.0,
            "tp1_price": 97.0,
            "sl_price": 101.5,
            "canonical_strategy": "SQUEEZE_EXPANSION_SHORT",
            "decision": "🔴 SHORT SQUEEZE EXPANSION",
            "is_order_block_signal": False
        }
        feats_sq = labeler.build_meta_feature_vector("SOL/USDT", sig_sq)
        self.assertEqual(feats_sq["is_order_block"].iloc[0], 0.0)
        self.assertEqual(feats_sq["is_squeeze"].iloc[0], 1.0)
        self.assertEqual(feats_sq["is_long"].iloc[0], 0.0)
        self.assertEqual(feats_sq["is_rally_sell"].iloc[0], 0.0)

    def test_signal_generator_path_probability_coherence(self):
        """Tests that PathProbabilities satisfy P(TP1) + P(SL) = 1.0 and monotonic decay."""
        sig_sys = SignalGenerationSystem()
        dfs_9 = {tf: self.df_synthetic.copy() for tf in ["5m", "15m", "1h", "4h", "12h", "1d", "1w", "15d", "1M"]}
        btc_shield = {
            "status_code": "NORMAL",
            "altcoin_longs_allowed": True,
            "is_ntz_active": False,
            "regime": "NEUTRAL"
        }

        # Build a single horizon signal
        sig = sig_sys._build_single_horizon_signal(
            symbol="ETH/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="LONG",
            current_price=100.0,
            dfs_9=dfs_9,
            horizon_prediction={"predicted_change_pct": 2.0, "predicted_target_price": 102.0, "consensus_probability": 0.70},
            btc_shield_state=btc_shield,
            aligned_horizons=["5m", "15m", "1h", "4h", "12h", "1d"]
        )

        # Verify Path Probabilities Invariants
        probs = sig["path_probabilities"]
        self.assertAlmostEqual(probs["tp1"] + probs["sl"], 100.0, delta=1.0)
        self.assertLessEqual(probs["tp2"], probs["tp1"])
        self.assertLessEqual(probs["tp3"], probs["tp2"])
        self.assertEqual(sig["p_tp1_pct"], probs["tp1"])
        self.assertEqual(sig["p_sl_pct"], probs["sl"])

    def test_meta_labeler_hierarchical_global_fallback_and_shrinkage(self):
        """Tests that CoinSpecificMetaLabeler blends per-coin models via Empirical Bayes and falls back to global meta-model."""
        labeler = CoinSpecificMetaLabeler()

        # 1. Unknown synthetic pair -> must respect pure cold start prior
        p_cold, m_cold, sz_cold = labeler.predict_coin_win_probability("UNKNOWN_PAIR/USDT", {
            "conviction": 80.0,
            "expected_return_pct": 2.0,
            "quality_grade": "Grade A"
        })
        self.assertEqual(m_cold, "COLD_START_PRIOR")
        self.assertEqual(sz_cold, 0)
        self.assertGreaterEqual(p_cold, 0.05)
        self.assertLessEqual(p_cold, 0.95)

        # 2. BTC/USDT -> has dedicated model in per_coin/BTC_USDT/meta_classifier.joblib
        p_btc, m_btc, sz_btc = labeler.predict_coin_win_probability("BTC/USDT", {
            "conviction": 85.0,
            "expected_return_pct": 2.5,
            "quality_grade": "Grade A",
            "entry_price": 60000.0,
            "tp1_price": 61500.0,
            "sl_price": 59250.0
        })
        self.assertIn(m_btc, ["PER_COIN_CALIBRATED", "PER_COIN_PRIOR"])
        self.assertGreater(sz_btc, 0)
        self.assertGreaterEqual(p_btc, 0.05)
        self.assertLessEqual(p_btc, 0.95)

        # 3. Dynamic economic hurdle derivation in calibrated mode
        import app.engine.config as config_module
        orig_mode = config_module.PROBABILITY_CALIBRATION_MODE
        try:
            config_module.PROBABILITY_CALIBRATION_MODE = "CHRONOLOGICAL_CALIBRATED"
            eval_res = labeler.evaluate_signal("BTC/USDT", {
                "entry_price": 100.0,
                "tp1_price": 104.0,
                "sl_price": 98.0
            })
            self.assertIn("decision_hurdle", eval_res)
            self.assertGreaterEqual(eval_res["decision_hurdle"], 0.28)
            self.assertLessEqual(eval_res["decision_hurdle"], 0.48)
        finally:
            config_module.PROBABILITY_CALIBRATION_MODE = orig_mode

    def test_triple_barrier_labeling_no_stop_out_mfe_overwrite(self):
        """Tests that realized stop-outs (LOST_SL) are NEVER overwritten into wins by post-invalidation MFE."""
        from train_meta_labeler import extract_features
        from app.services.model_retrainer import extract_features_from_records

        df_stopped = pd.DataFrame([{
            'signal_id': 'STOPPED_01',
            'symbol': 'BTC/USDT',
            'status': 'CLOSED',
            'outcome_label': 'LOST_SL',
            'entry_price': 100.0,
            'tp1_price': 104.0,
            'sl_price': 98.0,
            'sl_original': 98.0,
            'max_potential_gain_pct': 10.0, # Massive post-invalidation rebound!
            'conviction_pct': 85.0,
            'expected_return_pct': '4.0%',
            'quality_grade': 'Grade A+',
            'horizon': '1H',
            'direction': 'LONG',
            'decision': 'EXECUTE'
        }])

        df_won = pd.DataFrame([{
            'signal_id': 'WON_01',
            'symbol': 'BTC/USDT',
            'status': 'WON_TP1',
            'outcome_label': 'WON_TP1',
            'entry_price': 100.0,
            'tp1_price': 104.0,
            'sl_price': 98.0,
            'sl_original': 98.0,
            'max_potential_gain_pct': 4.5,
            'conviction_pct': 85.0,
            'expected_return_pct': '4.0%',
            'quality_grade': 'Grade A+',
            'horizon': '1H',
            'direction': 'LONG',
            'decision': 'EXECUTE'
        }])

        # Train pipeline
        feats_train_stopped = extract_features(df_stopped)
        self.assertEqual(feats_train_stopped['target'].iloc[0], 0, "LOST_SL must have target=0 despite MFE >= TP!")

        feats_train_won = extract_features(df_won)
        self.assertEqual(feats_train_won['target'].iloc[0], 1, "WON_TP1 must have target=1")

        # Retrainer service pipeline
        feats_retrain_stopped = extract_features_from_records(df_stopped)
        self.assertEqual(feats_retrain_stopped['target'].iloc[0], 0, "LOST_SL in retrainer service must have target=0!")

        feats_retrain_won = extract_features_from_records(df_won)
        self.assertEqual(feats_retrain_won['target'].iloc[0], 1, "WON_TP1 in retrainer service must have target=1")

    def test_meta_feature_bounded_rr_and_untrailed_sl(self):
        """Tests that build_meta_feature_vector bounds RR ratios and uses sl_original over trailed stop."""
        labeler = CoinSpecificMetaLabeler()

        # Signal with trailed stop-loss at entry price (breakeven lock)
        sig_trailed = {
            "entry_price": 100.0,
            "tp1_price": 105.0,
            "sl_price": 100.0,        # Trailed to breakeven!
            "sl_original": 97.5,      # Original 2.5% stop
            "conviction": 85.0,
            "expected_return_pct": 5.0
        }
        feats = labeler.build_meta_feature_vector("ETH/USDT", sig_trailed)

        # Expected: Uses sl_original=97.5 -> sl_pct = 2.5%, tp_pct = 5.0%, rr_ratio = 2.0
        self.assertAlmostEqual(feats["sl_pct"].iloc[0], 2.5, places=1)
        self.assertAlmostEqual(feats["tp_pct"].iloc[0], 5.0, places=1)
        self.assertAlmostEqual(feats["risk_reward_ratio"].iloc[0], 2.0, places=1)
        self.assertEqual(feats["risk_reward_ratio"].iloc[0], feats["tp_sl_ratio"].iloc[0])

    def test_cold_start_laplace_prior_classifiers_and_regressors(self):
        """Tests that new coins with < 15 candles or single class strictly engage Cold-Start Laplace Prior models."""
        clf = FiveModelDirectionClassifier()
        reg = FiveModelPriceRegressor()

        # Case 1: Cold start with 6 candles, 5 bullish and 1 bearish (k=5, N=6)
        X_cold = np.random.randn(6, 12).astype(np.float32)
        y_dir_cold = np.array([1, 1, 1, 0, 1, 1], dtype=int)
        y_ret_cold = np.array([0.01, 0.02, 0.015, -0.01, 0.025, 0.03], dtype=np.float32)

        is_fitted_clf = clf.fit(X_cold, y_dir_cold)
        is_fitted_reg = reg.fit(X_cold, y_ret_cold)

        self.assertFalse(is_fitted_clf, "Ensemble fit must return False for < 15 samples")
        self.assertFalse(is_fitted_reg, "Regressor fit must return False for < 15 samples")
        self.assertTrue(clf.is_cold_start, "Classifier must flag cold-start active")
        self.assertTrue(reg.is_cold_start, "Regressor must flag cold-start active")

        # Laplace smoothing formula: (k + 1) / (N + 2) = (5 + 1) / (6 + 2) = 6/8 = 0.75
        expected_laplace_prob = (5.0 + 1.0) / (6.0 + 2.0)
        self.assertAlmostEqual(clf.laplace_prob, expected_laplace_prob, places=4)

        # Live prediction under cold-start
        pred_clf = clf.predict_live(np.random.randn(1, 12).astype(np.float32))
        self.assertEqual(pred_clf["model_type"], "COLD_START_LAPLACE_PRIOR")
        self.assertTrue(pred_clf["is_cold_start"])
        self.assertAlmostEqual(pred_clf["prob_bullish"], expected_laplace_prob, places=4)
        self.assertEqual(pred_clf["direction"], "LONG")

        pred_reg = reg.predict_price_live(np.random.randn(1, 12).astype(np.float32), current_price=100.0, expected_direction="LONG")
        self.assertEqual(pred_reg["model_type"], "COLD_START_LAPLACE_PRIOR")
        self.assertTrue(pred_reg["is_cold_start"])
        self.assertGreater(pred_reg["predicted_target_price"], 100.0)

        # Case 2: Full ensemble graduation when 20 candles accumulate
        X_warm = np.random.randn(20, 12).astype(np.float32)
        y_dir_warm = np.array([1, 0] * 10, dtype=int)
        y_ret_warm = np.random.uniform(-0.02, 0.02, 20).astype(np.float32)

        is_graduated_clf = clf.fit(X_warm, y_dir_warm)
        is_graduated_reg = reg.fit(X_warm, y_ret_warm)

        self.assertTrue(is_graduated_clf, "Must graduate to fitted ensemble when >= 15 candles")
        self.assertTrue(is_graduated_reg, "Must graduate to fitted ensemble when >= 15 candles")
        self.assertFalse(clf.is_cold_start)
        self.assertFalse(reg.is_cold_start)

    def test_per_coin_model_registry_persistence_and_preloading(self):
        """Tests that PerCoinModelRegistry persists models, preloads them on reboot, and promotes cold-starts."""
        import tempfile
        import shutil

        temp_dir = tempfile.mkdtemp()
        orig_instance = PerCoinModelRegistry._instance
        PerCoinModelRegistry._instance = None
        try:
            registry = PerCoinModelRegistry(base_models_dir=temp_dir)
            sym = "NEWCOIN/USDT"
            tf = "15m"

            # 1. First fit: Cold start (< 15 candles)
            X_cold = np.random.randn(8, 10).astype(np.float32)
            y_dir_cold = np.array([1, 1, 0, 1, 0, 1, 1, 0], dtype=int)
            y_ret_cold = np.random.uniform(-0.01, 0.01, 8).astype(np.float32)

            clfs, regs, is_fresh = registry.get_or_train_coin_models(
                symbol=sym, tf=tf, X_train=X_cold, y_train_dir=y_dir_cold,
                y_train_ret=y_ret_cold, last_candle_ts=1000, ttl_seconds=300
            )
            self.assertTrue(is_fresh)
            self.assertTrue(clfs.is_cold_start)

            # Check disk file exists
            model_path = registry.get_model_path(sym, tf)
            self.assertTrue(os.path.exists(model_path))

            # 2. Test preloading on reboot
            PerCoinModelRegistry._instance = None
            new_registry = PerCoinModelRegistry(base_models_dir=temp_dir)
            self.assertIn(f"NEWCOIN_USDT_{tf}", new_registry._cache)

            # 3. Model graduation: 18 candles arrive -> re-train into full 5-model ensemble
            X_mature = np.random.randn(18, 10).astype(np.float32)
            y_dir_mature = np.array([1, 0] * 9, dtype=int)
            y_ret_mature = np.random.uniform(-0.02, 0.02, 18).astype(np.float32)

            m_clfs, m_regs, m_fresh = new_registry.get_or_train_coin_models(
                symbol=sym, tf=tf, X_train=X_mature, y_train_dir=y_dir_mature,
                y_train_ret=y_ret_mature, last_candle_ts=2000, ttl_seconds=300
            )
            self.assertTrue(m_fresh, "Must freshly train when graduating from cold-start to full ensemble")
            self.assertFalse(m_clfs.is_cold_start, "Graduated model must not be cold-start")
            self.assertTrue(m_clfs.is_fitted)

        finally:
            PerCoinModelRegistry._instance = orig_instance
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_multi_exchange_fallback_and_15s_price_staleness(self):
        """Tests that MultiHorizonDataLoader and CryptoDataLoader failover properly and enforce 15s staleness breaker."""
        from test import CryptoDataLoader
        loader = CryptoDataLoader()

        # 1. Test 15s staleness circuit breaker
        now = time.time()
        loader._live_tickers_cache = {"BTC/USDT": 65000.0, "ETH/USDT": 3500.0}
        
        # Fresh prices (age = 1s <= 2s TTL, <= 15s circuit breaker)
        loader._live_tickers_ts = now - 1.0
        p, is_fresh, age = loader.get_live_price_with_freshness("BTC/USDT")
        self.assertEqual(p, 65000.0)
        self.assertTrue(is_fresh)
        self.assertLessEqual(age, 15.0)

        # Stale prices (age = 20s > 15s) -> Circuit breaker trips
        loader._live_tickers_ts = now - 20.0
        # Simulate all upstream endpoints returning rate limit / network error
        loader._binance_ip_throttled_until = now + 180.0
        loader._fetch_bybit_tickers = lambda: {}
        loader._fetch_okx_tickers = lambda: {}
        loader._fetch_gateio_tickers = lambda: {}
        loader._fetch_kucoin_tickers = lambda: {}

        p_stale, is_fresh_stale, age_stale = loader.get_live_price_with_freshness("BTC/USDT")
        self.assertFalse(is_fresh_stale, "Must trip circuit breaker when price age > 15s")
        self.assertTrue(loader._is_global_outage)
        self.assertIn("PRICE_STALENESS_EXCEEDED", loader._global_outage_reason)

        # 2. Test failover to Tier-2 Bybit when Binance is throttled
        loader._live_tickers_ts = 0.0 # Force re-fetch
        loader._binance_ip_throttled_until = now + 180.0 # Binance throttled
        loader._fetch_bybit_tickers = lambda: {"BTC/USDT": 65100.0, "SOL/USDT": 150.0}

        ticks = loader.fetch_all_tickers(max_age_seconds=1.0)
        self.assertIn("BTC/USDT", ticks)
        self.assertEqual(ticks["BTC/USDT"], 65100.0)
        self.assertEqual(ticks["SOL/USDT"], 150.0)
        self.assertTrue(loader._is_price_fresh_15s)
        self.assertFalse(loader._is_global_outage)

    def test_exchange_geo_restriction_fast_fail_and_cooldown(self):
        """Tests that regional cloud IP bans trigger 900s fast-fail cooldown and fall back to Tier-6.5 CoinCap."""
        from test import CryptoDataLoader
        loader = CryptoDataLoader()
        now = time.time()

        # 1. Test fast-fail cooldown registry recording and lookup
        self.assertFalse(loader._is_exchange_geo_blocked("bybit"))
        loader._record_exchange_geo_block("bybit", 403, "Cloud IP range blocked by regional compliance")
        self.assertTrue(loader._is_exchange_geo_blocked("bybit"))
        # Verify independence of exchange cooldowns
        self.assertFalse(loader._is_exchange_geo_blocked("okx"))

        # Check cooldown duration (900 seconds)
        blocked_until = loader._exchange_geo_cooldowns.get("bybit", 0.0)
        self.assertGreaterEqual(blocked_until, now + 890.0)
        self.assertLessEqual(blocked_until, now + 910.0)

        # 2. Test fast-fail bypass without network latency
        # When geo-blocked, fetch methods return immediately without making HTTP calls
        self.assertEqual(loader._fetch_bybit_tickers(), {})
        self.assertEqual(loader._fetch_bybit_klines("BTC/USDT", "1h"), [])

        # 3. Test Tier-6.5 CoinCap Fallback and <= 1 call per 2.0s Rate Limiting
        loader._live_tickers_ts = 0.0
        loader._binance_ip_throttled_until = now + 900.0
        loader._record_exchange_geo_block("bybit", 451, "Geo-restricted")
        loader._record_exchange_geo_block("okx", 403, "Geo-restricted")
        loader._record_exchange_geo_block("gateio", 403, "Geo-restricted")
        loader._record_exchange_geo_block("kucoin", 403, "Geo-restricted")
        loader._record_exchange_geo_block("mexc", 403, "Geo-restricted")

        # Test CoinCap 2.0s rate throttling directly on _fetch_coincap_tickers
        call_count = {"count": 0}
        def mock_coincap_get(url, timeout=3.5):
            call_count["count"] += 1
            class MockResponse:
                status_code = 200
                def json(self):
                    return {"data": [{"symbol": "BTC", "rateUsd": "67800.0"}, {"symbol": "ETH", "rateUsd": "3650.0"}]}
            return MockResponse()

        loader.session.get = mock_coincap_get
        # Call 1: Makes HTTP request
        ticks1 = loader._fetch_coincap_tickers()
        self.assertEqual(call_count["count"], 1)
        self.assertIn("BTC/USDT", ticks1)
        self.assertEqual(ticks1["BTC/USDT"], 67800.0)

        # Call 2 (0.1s later < 2.0s interval): Must hit cache and NOT make HTTP request
        ticks2 = loader._fetch_coincap_tickers()
        self.assertEqual(call_count["count"], 1, "Must throttle CoinCap requests to <= 1 call per 2.0s")
        self.assertEqual(ticks2["BTC/USDT"], 67800.0)

        # Test HTTP 429 backoff trigger (60s cooldown)
        def mock_coincap_429(url, timeout=3.5):
            class Mock429Response:
                status_code = 429
                def json(self):
                    return {"error": "Too Many Requests"}
            return Mock429Response()

        loader.session.get = mock_coincap_429
        loader._coincap_rates_ts = 0.0 # Force interval expiry
        ticks_429 = loader._fetch_coincap_tickers()
        self.assertGreaterEqual(loader._coincap_throttled_until, time.time() + 55.0)
        self.assertEqual(ticks_429["BTC/USDT"], 67800.0) # Returns cached rates safely

        # Verify integration through fetch_all_tickers
        ticks_all = loader.fetch_all_tickers(max_age_seconds=1.0)
        self.assertIn("BTC/USDT", ticks_all)
        self.assertTrue(loader._is_price_fresh_15s)
        self.assertFalse(loader._is_global_outage)

    def test_cold_start_universe_horizon_accumulation_gating(self):
        """
        Tests Cold-Start Listing Progression:
        Newly listed tokens naturally transition from COLD_START to CONVERGED_ENSEMBLE
        after accumulating 15 historical candles on each timeframe:
        - 15M Scalp requires 15 historical candles (3.75 hours on 15M)
        - 1H Intraday requires 15 historical candles (15 hours on 1H)
        - 24H Daily Swing requires 15 historical candles (15 days on 24H)
        """
        from test import CONFIG, HybridQuantEngine
        from app.engine.signals.signal_generator import SignalGenerationSystem

        # 1. Test single horizon dampening in evaluate_single_horizon
        engine = HybridQuantEngine(CONFIG)
        h_cfg = {"anchor_tf": "15m", "bars": 1, "tp_mult": 1.5, "sl_mult": 1.0, "name": "15m", "duration_label": "15m Micro"}

        # Short DataFrame with only 8 candles (< 15 minimum required for convergence)
        n = 8
        base_p = 50.0
        df_cold = pd.DataFrame({
            "timestamp": np.arange(1700000000, 1700000000 + n * 900, 900),
            "open": [base_p + i * 0.2 for i in range(n)],
            "high": [base_p + i * 0.2 + 0.5 for i in range(n)],
            "low": [base_p + i * 0.2 - 0.5 for i in range(n)],
            "close": [base_p + (i + 1) * 0.2 for i in range(n)],
            "volume": [10000.0] * n,
            "taker_buy_vol": [5000.0] * n
        })

        fused_df = df_cold.copy()
        fused_df['primary_raw_atr'] = engine.fe.compute_atr(fused_df, period=14)
        fused_df['primary_norm_atr'] = fused_df['primary_raw_atr'] / (fused_df['close'] + 1e-10)
        feat_df = engine.fe.build_timeframe_features(df_cold, prefix="15m")
        fused_df = pd.merge_asof(
            fused_df.sort_values('timestamp'),
            feat_df.sort_values('timestamp'),
            on='timestamp',
            direction='backward'
        )

        res = engine.evaluate_single_horizon(
            symbol="NEWCOIN/USDT",
            horizon_key="scalp",
            h_cfg=h_cfg,
            fused_df=fused_df,
            d1_macro_bull=True,
            live_price=51.6
        )

        self.assertTrue(res["is_cold_start"])
        self.assertEqual(res["accumulation_phase"], "COLD_START_INSUFFICIENT_HISTORY")
        self.assertIn("COLD START HORIZON ACCUMULATION", res["decision"])
        self.assertEqual(res["direction"], "CONSOLIDATION")
        self.assertGreaterEqual(res["conviction"], 48.0)
        self.assertLessEqual(res["conviction"], 52.0)
        self.assertEqual(res["priority"], 4)

        # 2. Test Master Signal Cold-Start Listing Progression
        sig_sys = SignalGenerationSystem()

        # Case A: T < 3.75 hours (15M has 8 candles < 15) -> Disqualified on ALL horizons
        dfs_case_a = {}
        for tf in ["5m", "15m", "1h", "4h", "12h", "1d", "1w", "15d", "1M"]:
            dfs_case_a[tf] = df_cold.copy() # 8 candles < 15

        res_a = sig_sys.evaluate_asset_multi_horizon(
            symbol="NEWCOIN/USDT",
            dfs_9=dfs_case_a,
            btc_shield_state={"status_code": "NORMAL", "altcoin_longs_allowed": True},
            live_price=51.6
        )
        self.assertFalse(res_a["trend_criteria_gates"]["15M_gate"]["qualified"], "15M must be disqualified when 15M has < 15 candles")
        self.assertFalse(res_a["trend_criteria_gates"]["1H_gate"]["qualified"], "1H must be disqualified when 1H has < 15 candles")
        self.assertFalse(res_a["trend_criteria_gates"]["24H_gate"]["qualified"], "24H must be disqualified when 24H has < 15 candles")
        self.assertIn("COLD_START_HORIZON_ACCUMULATION", " ".join(res_a["trend_criteria_gates"]["15M_gate"]["conflicts"]))

        # Case B: T = 5 hours (15M has 20 candles >= 15 [3.75h accumulated], but 1H has 5 candles < 15)
        # 15M transitions to CONVERGED_ENSEMBLE! 1H and 24H remain in COLD_START accumulation.
        dfs_case_b = {}
        dfs_case_b["5m"] = self.df_synthetic.copy() # 60 candles >= 15
        dfs_case_b["15m"] = self.df_synthetic.copy() # 60 candles >= 15 (> 3.75h)
        for tf in ["1h", "4h", "12h", "1d", "1w", "15d", "1M"]:
            dfs_case_b[tf] = df_cold.copy() # 8 candles < 15

        res_b = sig_sys.evaluate_asset_multi_horizon(
            symbol="NEWCOIN/USDT",
            dfs_9=dfs_case_b,
            btc_shield_state={"status_code": "NORMAL", "altcoin_longs_allowed": True},
            live_price=51.6
        )
        # 15M has empirical history (>= 15 candles on 15M and 5M) -> not blocked by cold start!
        conflicts_15m = " ".join(res_b["trend_criteria_gates"]["15M_gate"]["conflicts"])
        self.assertNotIn("COLD_START_HORIZON_ACCUMULATION", conflicts_15m, "15M must NOT be blocked by cold start once 15M has >= 15 candles")
        
        # 1H and 24H must STILL be disqualified awaiting their empirical accumulation
        self.assertFalse(res_b["trend_criteria_gates"]["1H_gate"]["qualified"], "1H must remain disqualified (< 15h)")
        self.assertFalse(res_b["trend_criteria_gates"]["24H_gate"]["qualified"], "24H must remain disqualified (< 15 days)")
        self.assertIn("COLD_START_HORIZON_ACCUMULATION", " ".join(res_b["trend_criteria_gates"]["1H_gate"]["conflicts"]))
        self.assertIn("COLD_START_HORIZON_ACCUMULATION", " ".join(res_b["trend_criteria_gates"]["24H_gate"]["conflicts"]))


if __name__ == "__main__":
    unittest.main()



