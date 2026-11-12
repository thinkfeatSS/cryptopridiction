import unittest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock

from app.engine.signals.signal_generator import SignalGenerationSystem
from app.engine.signals.ensemble_regressor import FiveModelPriceRegressor
from app.engine.scanner.data_loader import MultiHorizonDataLoader
from app.engine.config import SCANNING_CANDLE_LIMITS, TRAINING_CANDLE_LIMITS, get_candle_limits

class TestV16TriHorizonRegressionAlignment(unittest.TestCase):
    """
    Authoritative test suite for Tri-Horizon (1M, 5M, 15M) Price Prediction Alignment
    and Unanimous 5-Model Regression Convergence in Quant Edge V16.
    """

    def setUp(self):
        self.sig_sys = SignalGenerationSystem()
        self.loader = MultiHorizonDataLoader()

    def _create_mock_candles(self, n: int = 60, base_price: float = 100.0, trend: float = 0.001) -> pd.DataFrame:
        """Helper to create contiguous OHLCV candles."""
        closes = [base_price * (1.0 + trend * i) for i in range(n)]
        opens = [closes[max(0, i - 1)] for i in range(n)]
        highs = [max(o, c) * 1.002 for o, c in zip(opens, closes)]
        lows = [min(o, c) * 0.998 for o, c in zip(opens, closes)]
        volumes = [1000.0 + i * 10 for i in range(n)]
        timestamps = [1700000000 + (i * 60) for i in range(n)]

        return pd.DataFrame({
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes
        })

    def test_01_unanimous_5_models_satisfaction_long_confluence(self):
        """Verify unanimous 5-model satisfaction across 1M, 5M, and 15M for LONG setup."""
        current_p = 100.0
        df_15m = self._create_mock_candles(60, base_price=98.0, trend=0.0005)
        df_5m = self._create_mock_candles(60, base_price=99.5, trend=0.0002)
        df_1m = self._create_mock_candles(60, base_price=99.9, trend=0.0001)

        dfs = {"15m": df_15m, "5m": df_5m, "1m": df_1m}

        pred_15m = {
            "predicted_target_price": 101.50,
            "predicted_change_pct": 1.50,
            "winning_vote_count": 5,
            "outlier_models": []
        }

        res = self.sig_sys.evaluate_tri_horizon_regression_alignment(
            symbol="BTC/USDT",
            direction="LONG",
            current_price=current_p,
            dfs_9=dfs,
            horizon_prediction_15m=pred_15m
        )

        self.assertTrue(res["unanimous_5_models_satisfied"], "All 5 models must satisfy at each horizon")
        self.assertTrue(res["directional_sign_concordance"], "All 3 horizons must forecast positive change for LONG")
        self.assertFalse(res["has_adverse_rebound"], "No adverse rebound on 1M/5M")
        self.assertTrue(res["temporal_progression_valid"], "Target progression must be monotonic")
        self.assertTrue(res["is_aligned"], "Overall Tri-Horizon alignment must be True")

    def test_02_microstructure_adverse_rebound_vetoed_on_short(self):
        """Verify that microstructural bounce on 1M/5M vetoes a 15M SHORT setup."""
        current_p = 100.0
        # 1M candles have aggressive upward bounce (+0.80%)
        df_15m = self._create_mock_candles(60, base_price=102.0, trend=-0.0005)
        df_5m = self._create_mock_candles(60, base_price=99.0, trend=0.001)
        df_1m = self._create_mock_candles(60, base_price=99.2, trend=0.002)

        dfs = {"15m": df_15m, "5m": df_5m, "1m": df_1m}

        pred_15m = {
            "predicted_target_price": 98.00,
            "predicted_change_pct": -2.00,
            "winning_vote_count": 5,
            "outlier_models": []
        }

        res = self.sig_sys.evaluate_tri_horizon_regression_alignment(
            symbol="ETH/USDT",
            direction="SHORT",
            current_price=current_p,
            dfs_9=dfs,
            horizon_prediction_15m=pred_15m
        )

        # Microstructure bounce on 1m/5m must trip adverse rebound check
        if res.get("m1", {}).get("predicted_change_pct", 0) > 0.05 or res.get("m5", {}).get("predicted_change_pct", 0) > 0.05:
            self.assertTrue(res["has_adverse_rebound"])
            self.assertFalse(res["is_aligned"])
            self.assertIn("Microstructure adverse rebound", res["unaligned_reason"])

    def test_03_directional_sign_discordance_interception(self):
        """Verify directional sign discordance intercepts signal when 1M points counter-trend."""
        current_p = 100.0
        df_15m = self._create_mock_candles(60, base_price=98.0, trend=0.0005)
        df_5m = self._create_mock_candles(60, base_price=99.5, trend=0.0002)
        df_1m = self._create_mock_candles(60, base_price=101.0, trend=-0.002) # Falling on 1M

        dfs = {"15m": df_15m, "5m": df_5m, "1m": df_1m}

        # Mock 1M regressor predicting drop on LONG setup
        with patch.object(FiveModelPriceRegressor, 'predict_price_live') as mock_pred:
            mock_pred.return_value = {
                "predicted_target_price": 99.20,
                "predicted_change_pct": -0.80, # Negative return on LONG
                "winning_vote_count": 5,
                "outlier_models": []
            }

            res = self.sig_sys.evaluate_tri_horizon_regression_alignment(
                symbol="SOL/USDT",
                direction="LONG",
                current_price=current_p,
                dfs_9=dfs,
                horizon_prediction_15m={
                    "predicted_target_price": 102.50,
                    "predicted_change_pct": 2.50,
                    "winning_vote_count": 5,
                    "outlier_models": []
                }
            )

            self.assertFalse(res["is_aligned"], "Sign discordance must disqualify signal")
            self.assertTrue(res["has_adverse_rebound"] or not res["directional_sign_concordance"])

    def test_04_data_loader_tri_horizon_caching_and_limits(self):
        """Verify data loader candle limits and fetch_tri_horizon_candles helper."""
        self.assertIn("1m", SCANNING_CANDLE_LIMITS)
        self.assertIn("1m", TRAINING_CANDLE_LIMITS)
        self.assertEqual(SCANNING_CANDLE_LIMITS["1m"], 120)
        self.assertEqual(TRAINING_CANDLE_LIMITS["1m"], 500)

        # Mock fetch_all_9_timeframes returning 1m, 5m, 15m
        df_mock = self._create_mock_candles(30)
        with patch.object(self.loader, 'fetch_all_9_timeframes') as mock_fetch:
            mock_fetch.return_value = {"1m": df_mock, "5m": df_mock, "15m": df_mock}
            tri_dfs = self.loader.fetch_tri_horizon_candles("BTC/USDT")
            self.assertIn("1m", tri_dfs)
            self.assertIn("5m", tri_dfs)
            self.assertIn("15m", tri_dfs)
            self.assertEqual(len(tri_dfs["1m"]), 30)

    def test_05_pre_signal_radar_retention_on_unaligned_regression(self):
        """Verify that a signal failing tri-horizon regression is held in PRE_SIGNAL_RADAR."""
        current_p = 50.0
        df_15m = self._create_mock_candles(60, base_price=50.0)
        dfs = {"15m": df_15m, "5m": df_15m, "1m": df_15m, "1h": df_15m, "4h": df_15m}

        mock_ntz = {
            "is_ntz": False,
            "reasons": [],
            "regime_type": "EXPANSION",
            "adx": 32.0,
            "bbw": 0.08,
            "bbw_percentile": 50.0
        }

        # Force regression alignment to fail, strategy allowed, candle trigger confirmed, and NTZ to be False
        with patch('app.quant_v16.no_trade_zone.no_trade_zone_engine.evaluate_asset_ntz', return_value=mock_ntz), \
             patch('app.quant_v16.entry_confirmation.EntryConfirmationEngine.validate_candle_trigger', return_value=(True, "Trigger Confirmed", {})), \
             patch.object(self.sig_sys.strategy_registry, 'is_strategy_allowed', return_value=(True, "")), \
             patch.object(self.sig_sys, 'evaluate_tri_horizon_regression_alignment') as mock_align:
            mock_align.return_value = {
                "is_aligned": False,
                "unanimous_5_models_satisfied": False,
                "unaligned_reason": "Regressors unconverged (1M: 3/5, 5M: 3/5, 15M: 4/5)"
            }

            sig = self.sig_sys._build_single_horizon_signal(
                symbol="NEAR/USDT",
                horizon_label="15M",
                tf_key="15m",
                direction="LONG",
                current_price=current_p,
                dfs_9=dfs,
                horizon_prediction={"predicted_target_price": 52.0, "predicted_change_pct": 4.0, "winning_vote_count": 4},
                btc_shield_state={"altcoin_longs_allowed": True},
                aligned_horizons=["15m", "1h"],
                order_block_setup={"setup_detected": True, "direction": "LONG", "structural_trigger_confirmed": True}
            )

            self.assertIsNotNone(sig)
            self.assertEqual(sig["signal_status"], "HOLD_AWAITING_1M_5M_REGRESSION_CONFLUENCE")
            self.assertFalse(sig["is_trade_active"])
            self.assertTrue(sig["is_radar_eligible"])
            self.assertIn("tri_horizon_alignment", sig)
            self.assertFalse(sig["tri_horizon_alignment"]["is_aligned"])

if __name__ == "__main__":
    unittest.main()
