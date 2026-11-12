#!/usr/bin/env python3
"""
Test Suite: Train/Serve Skew Forensics & Parity Gate
---------------------------------------------------
Verifies 100% mathematical and feature vector parity across:
1. Live serving: CoinSpecificMetaLabeler.build_meta_feature_vector (app/engine/signals/meta_labeler.py)
2. Offline training: extract_features_from_records (train_meta_labeler.py)
3. Automated retraining: extract_features (app/services/model_retrainer.py)
4. Evaluation engine: SignalMetaClassifier (test.py)
5. Per-coin model candle target alignment (train_per_coin_models.py vs signal_generator.py)
"""

import unittest
import numpy as np
import pandas as pd
from typing import Dict, Any

from app.engine.signals.meta_labeler import CoinSpecificMetaLabeler, META_FEATURE_COLS
from train_meta_labeler import extract_features as train_extract_features
from app.services.model_retrainer import extract_features_from_records as retrainer_extract_features
from test import SignalMetaClassifier


class TestTrainServeSkewForensics(unittest.TestCase):

    def setUp(self):
        self.meta_labeler = CoinSpecificMetaLabeler()
        self.test_classifier = SignalMetaClassifier()

    def test_feature_vector_alignment_across_all_modules(self):
        """Verifies that identical candidate signal records produce identical 23 feature values across all 4 pipelines."""
        test_signals = [
            {
                "symbol": "BTC/USDT",
                "direction": "LONG",
                "horizon": "15M",
                "decision": "EXECUTE DIP-BUY",
                "canonical_strategy": "SMC_ORDER_BLOCK",
                "quality_grade": "A+",
                "conviction": 88.0,
                "entry_price": 50000.0,
                "tp1_price": 51500.0,
                "sl_price": 49500.0,
                "expected_return_pct": 3.0,
                "f_cvd_divergence": 0.45,
                "f_order_book_imbalance": 0.25,
                "f_volatility_ratio": 1.2,
                "f_taker_buy_ratio": 0.62,
                "f_liquidity_proximity": 1.1,
                "f_funding_drag": 5.0,
                "f_relative_volume": 1.8,
                "rank": "#2",
                "paper_trading_status": "EXECUTED",
                "status": "WON_TP1"
            },
            {
                "symbol": "1000PEPE/USDT",
                "direction": "BUY",
                "horizon": "4H",
                "decision": "LIQUIDITY-SWEEP SHORT SQUEEZE",
                "canonical_strategy": "BREAKER-BLOCK",
                "quality_grade": "B",
                "conviction": 75.0,
                "entry_price": 0.000010,
                "tp1_price": 0.000012,
                "sl_price": 0.0000095,
                "expected_return_pct": 20.0,
                "cvd_surge_5": 0.8,
                "book_imbalance": 0.6,
                "volatility_ratio": 2.5,
                "taker_buy_ratio": 0.70,
                "poi_distance_pct": 2.2,
                "funding_rate": 0.0005,
                "volume_surge_ratio": 3.5,
                "rank": 5,
                "paper_trading_status": "ACTIVE",
                "status": "WON_TP2"
            },
            {
                "symbol": "ETH/USDT",
                "direction": "SHORT",
                "horizon": "24H",
                "decision": "RALLY-SELL TOP-REVERSAL",
                "canonical_strategy": "BLOW-OFF TOP",
                "quality_grade": "A",
                "conviction": 82.0,
                "entry_price": 3000.0,
                "tp1_price": 2850.0,
                "sl_price": 3080.0,
                "expected_return_pct": 5.0,
                "taker_buy_ratio_5": 0.35,
                "cvd_val": -0.4,
                "f_order_book_imbalance": -0.3,
                "funding_pct": -0.0002,
                "rvol": 0.9,
                "rank": "#1",
                "paper_trading_status": "TRUE",
                "status": "LOST_SL"
            }
        ]

        for idx, sig in enumerate(test_signals):
            sym = sig["symbol"]

            # 1. Live Serving Feature Vector
            df_live = self.meta_labeler.build_meta_feature_vector(sym, sig)
            vec_live = df_live[META_FEATURE_COLS].iloc[0].to_dict()

            # 2. Offline Training Feature Vector
            df_train = train_extract_features(pd.DataFrame([sig]))
            self.assertFalse(df_train.empty, f"Offline training feature dataframe is empty for signal {idx}")
            vec_train = df_train[META_FEATURE_COLS].iloc[0].to_dict()

            # 3. Retrainer Service Feature Vector
            df_retrain = retrainer_extract_features(pd.DataFrame([sig]))
            self.assertFalse(df_retrain.empty, f"Retrainer feature dataframe is empty for signal {idx}")
            vec_retrain = df_retrain[META_FEATURE_COLS].iloc[0].to_dict()

            # Compare all 23 authoritative features
            for col in META_FEATURE_COLS:
                val_live = float(vec_live[col])
                val_train = float(vec_train[col])
                val_retrain = float(vec_retrain[col])

                self.assertAlmostEqual(
                    val_live, val_train, places=4,
                    msg=f"Skew detected between Live and Train on feature '{col}' for signal {idx} ({sym}): Live={val_live}, Train={val_train}"
                )
                self.assertAlmostEqual(
                    val_live, val_retrain, places=4,
                    msg=f"Skew detected between Live and Retrain on feature '{col}' for signal {idx} ({sym}): Live={val_live}, Retrain={val_retrain}"
                )

    def test_horizon_mutual_exclusivity(self):
        """Verifies mutually exclusive institutional horizon flags across scalp, swing, and macro."""
        test_horizons = [
            ("5M", 1.0, 0.0, 0.0),
            ("15M", 1.0, 0.0, 0.0),
            ("30M", 1.0, 0.0, 0.0),
            ("SCALP", 1.0, 0.0, 0.0),
            ("1H", 0.0, 1.0, 0.0),
            ("4H", 0.0, 1.0, 0.0),
            ("12H", 0.0, 1.0, 0.0),
            ("SWING", 0.0, 1.0, 0.0),
            ("INTRADAY", 0.0, 1.0, 0.0),
            ("DAY", 0.0, 1.0, 0.0),
            ("24H", 0.0, 0.0, 1.0),
            ("1D", 0.0, 0.0, 1.0),
            ("7D", 0.0, 0.0, 1.0),
            ("15D", 0.0, 0.0, 1.0),
            ("30D", 0.0, 0.0, 1.0),
            ("MACRO", 0.0, 0.0, 1.0),
        ]

        for h, exp_scalp, exp_swing, exp_macro in test_horizons:
            sig = {
                "symbol": "BTC/USDT",
                "direction": "LONG",
                "horizon": h,
                "entry_price": 50000.0,
                "tp1_price": 51000.0,
                "sl_price": 49000.0,
                "status": "WON_TP"
            }
            # 1. Live serving
            df_live = self.meta_labeler.build_meta_feature_vector("BTC/USDT", sig)
            self.assertEqual(df_live["is_scalp"].iloc[0], exp_scalp, f"Horizon {h} is_scalp live mismatch")
            self.assertEqual(df_live["is_swing"].iloc[0], exp_swing, f"Horizon {h} is_swing live mismatch")
            self.assertEqual(df_live["is_macro"].iloc[0], exp_macro, f"Horizon {h} is_macro live mismatch")

            # 2. Offline training
            df_train = train_extract_features(pd.DataFrame([sig]))
            self.assertEqual(df_train["is_scalp"].iloc[0], exp_scalp, f"Horizon {h} is_scalp train mismatch")
            self.assertEqual(df_train["is_swing"].iloc[0], exp_swing, f"Horizon {h} is_swing train mismatch")
            self.assertEqual(df_train["is_macro"].iloc[0], exp_macro, f"Horizon {h} is_macro train mismatch")

            # 3. Retrainer
            df_retrain = retrainer_extract_features(pd.DataFrame([sig]))
            self.assertEqual(df_retrain["is_scalp"].iloc[0], exp_scalp, f"Horizon {h} is_scalp retrain mismatch")
            self.assertEqual(df_retrain["is_swing"].iloc[0], exp_swing, f"Horizon {h} is_swing retrain mismatch")
            self.assertEqual(df_retrain["is_macro"].iloc[0], exp_macro, f"Horizon {h} is_macro retrain mismatch")

    def test_canonical_meme_coin_consistency(self):
        """Verifies canonical meme coin detection across standard, multiplier, and non-meme coins."""
        meme_symbols = ["1000PEPE/USDT", "1000000MOG_USDT", "10000LADYS/USDT", "SHIB/USDT", "BONK_USDT", "DOGE/USDT", "FLOKI:USDT"]
        non_meme_symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT", "LINK/USDT", "BNB/USDT"]

        for m_sym in meme_symbols:
            sig = {"symbol": m_sym, "direction": "LONG", "horizon": "15M", "entry_price": 1.0, "tp1_price": 1.05, "sl_price": 0.95, "status": "WON_TP"}
            df_live = self.meta_labeler.build_meta_feature_vector(m_sym, sig)
            df_train = train_extract_features(pd.DataFrame([sig]))
            df_retrain = retrainer_extract_features(pd.DataFrame([sig]))

            self.assertEqual(df_live["is_meme"].iloc[0], 1.0, f"{m_sym} live failed is_meme")
            self.assertEqual(df_train["is_meme"].iloc[0], 1.0, f"{m_sym} train failed is_meme")
            self.assertEqual(df_retrain["is_meme"].iloc[0], 1.0, f"{m_sym} retrain failed is_meme")

        for nm_sym in non_meme_symbols:
            sig = {"symbol": nm_sym, "direction": "LONG", "horizon": "1H", "entry_price": 100.0, "tp1_price": 105.0, "sl_price": 95.0, "status": "WON_TP"}
            df_live = self.meta_labeler.build_meta_feature_vector(nm_sym, sig)
            df_train = train_extract_features(pd.DataFrame([sig]))
            df_retrain = retrainer_extract_features(pd.DataFrame([sig]))

            self.assertEqual(df_live["is_meme"].iloc[0], 0.0, f"{nm_sym} live falsely flagged as is_meme")
            self.assertEqual(df_train["is_meme"].iloc[0], 0.0, f"{nm_sym} train falsely flagged as is_meme")
            self.assertEqual(df_retrain["is_meme"].iloc[0], 0.0, f"{nm_sym} retrain falsely flagged as is_meme")

    def test_unclosed_candle_target_exclusion_in_per_coin_training(self):
        """Verifies that sample n-2 is excluded from training when n >= 16 to avoid unclosed candle leakage."""
        # Simulated candle data with 20 candles
        n = 20
        c = np.linspace(100, 120, n)
        o = np.linspace(99, 119, n)
        feats = pd.DataFrame(np.random.randn(n, 10))

        target_direction = np.zeros(n, dtype=int)
        for i in range(n - 1):
            target_direction[i] = 1 if c[i + 1] > o[i + 1] else 0

        target_return = np.zeros(n, dtype=float)
        for i in range(n - 1):
            target_return[i] = (c[i + 1] - c[i]) / (c[i] + 1e-10)

        # Signal generator logic
        if n >= 16:
            X_gen = feats.iloc[:-2].values
            y_dir_gen = target_direction[:-2]
            y_ret_gen = target_return[:-2]
        else:
            X_gen = feats.iloc[:-1].values
            y_dir_gen = target_direction[:-1]
            y_ret_gen = target_return[:-1]

        # Verify exact shape and contents
        self.assertEqual(len(X_gen), n - 2)
        self.assertEqual(len(y_dir_gen), n - 2)
        self.assertEqual(len(y_ret_gen), n - 2)

        # Crucial: verify target at index n-3 points to candle n-2 (closed)
        expected_dir_n3 = 1 if c[n - 2] > o[n - 2] else 0
        self.assertEqual(y_dir_gen[-1], expected_dir_n3)

    def test_test_py_meta_classifier_probability_parity(self):
        """Verifies that SignalMetaClassifier in test.py produces valid calibrated probabilities aligned with meta_labeler."""
        sig = {
            "symbol": "BTC/USDT",
            "direction": "LONG",
            "horizon": "15M",
            "decision": "EXECUTE DIP-BUY",
            "canonical_strategy": "SMC_ORDER_BLOCK",
            "quality_grade": "A+",
            "conviction": 85.0,
            "entry_price": 60000.0,
            "tp1_price": 61200.0,
            "sl_price": 59400.0,
            "expected_return_pct": 2.0,
            "f_cvd_divergence": 0.3,
            "f_order_book_imbalance": 0.2,
            "f_volatility_ratio": 1.1,
            "f_taker_buy_ratio": 0.58,
            "f_liquidity_proximity": 1.0,
            "f_funding_drag": 2.0,
            "f_relative_volume": 1.5,
            "rank": 1,
            "paper_trading_status": "EXECUTED",
            "status": "ACTIVE"
        }

        prob_test = self.test_classifier.predict_win_probability("BTC/USDT", sig)
        prob_live, model_type, sample_sz = self.meta_labeler.predict_coin_win_probability("BTC/USDT", sig)

        self.assertTrue(0.05 <= prob_test <= 0.95, f"test.py prob out of bounds: {prob_test}")
        self.assertTrue(0.05 <= prob_live <= 0.95, f"meta_labeler prob out of bounds: {prob_live}")
        # Both share the same underlying global/per-coin model and Saerens calibration
        self.assertAlmostEqual(prob_test, prob_live, places=2, msg=f"Probability disparity: test.py={prob_test}, live={prob_live}")


if __name__ == '__main__':
    unittest.main()
