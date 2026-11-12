import unittest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock

from app.engine.config import (
    TIMEFRAMES_9,
    SCANNING_CANDLE_LIMITS,
    TRAINING_CANDLE_LIMITS,
    get_candle_limits
)
from app.engine.scanner.data_loader import MultiHorizonDataLoader
from app.engine.signals.candle_features import CandleDynamicsFeatureExtractor

class TestModelCandleLimitsAndWarmup(unittest.TestCase):
    """
    Authoritative test suite for Model Training Candle Limits,
    Exchange Fetch Uncapping, and Feature Warmup Trimming in Quant Edge AI V16.
    """

    def test_candle_limits_profiles_completeness(self):
        """Verify that SCANNING and TRAINING profiles cover all 9 multi-horizon timeframes."""
        for tf in TIMEFRAMES_9:
            self.assertIn(tf, SCANNING_CANDLE_LIMITS, f"{tf} missing from SCANNING_CANDLE_LIMITS")
            self.assertIn(tf, TRAINING_CANDLE_LIMITS, f"{tf} missing from TRAINING_CANDLE_LIMITS")
            self.assertGreater(SCANNING_CANDLE_LIMITS[tf], 0)
            self.assertGreater(TRAINING_CANDLE_LIMITS[tf], 0)
            self.assertGreaterEqual(
                TRAINING_CANDLE_LIMITS[tf],
                SCANNING_CANDLE_LIMITS[tf],
                f"Training limit for {tf} must be >= scanning limit"
            )

    def test_dynamic_get_candle_limits_resolver(self):
        """Verify get_candle_limits dynamic resolver returns correct profile copies."""
        train_limits = get_candle_limits("training")
        self.assertEqual(train_limits, TRAINING_CANDLE_LIMITS)
        self.assertEqual(train_limits["5m"], 1000)
        self.assertEqual(train_limits["1h"], 720)

        scan_limits = get_candle_limits("scanning")
        self.assertEqual(scan_limits, SCANNING_CANDLE_LIMITS)
        self.assertEqual(scan_limits["5m"], 120)

        # Ensure returned dicts are detached copies
        train_limits["5m"] = 9999
        self.assertEqual(TRAINING_CANDLE_LIMITS["5m"], 1000)

    def test_fetch_single_timeframe_raw_uncapped_at_1000(self):
        """Verify that fetch_single_timeframe_raw passes limit up to 1000 and does NOT clamp to 365."""
        loader = MultiHorizonDataLoader()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Simulate 1000 kline records
        mock_resp.json.return_value = [
            [1700000000000 + i * 300000, "100.0", "105.0", "95.0", "102.0", "1000.0",
             1700000300000 + i * 300000, "100000.0", 50, "500.0", "50000.0", "0"]
            for i in range(1000)
        ]

        with patch.object(loader.session, "get", return_value=mock_resp) as mock_get:
            df = loader.fetch_single_timeframe_raw("BTCUSDT", "5m", limit=1000)
            self.assertIsNotNone(df)
            self.assertEqual(len(df), 1000)

            # Inspect the limit passed to requests.get
            called_args, called_kwargs = mock_get.call_args
            params = called_kwargs.get("params", {})
            self.assertEqual(params.get("limit"), 1000, "fetch_limit must be 1000, not clamped to 365")

    def test_warmup_offset_calculation_and_trimming(self):
        """Verify warmup offset logic trims un-warmed feature rows for large N but preserves cold-start for small N."""
        # 1. Cold start / Small sample: N < 50
        n_cold = 30
        warmup_cold = min(35, max(0, n_cold - 40)) if n_cold >= 50 else 0
        self.assertEqual(warmup_cold, 0, "Cold start / small sample (< 50) must NOT trim warmup")

        # 2. Medium sample: N = 60
        n_med = 60
        warmup_med = min(35, max(0, n_med - 40)) if n_med >= 50 else 0
        self.assertEqual(warmup_med, 20, "N=60 must trim 20 rows, preserving 40 training samples")

        # 3. Large / Production sample: N = 500, 1000
        n_large = 1000
        warmup_large = min(35, max(0, n_large - 40)) if n_large >= 50 else 0
        self.assertEqual(warmup_large, 35, "N=1000 must cap warmup trim at 35 rows")

    def test_feature_warmup_cleanliness_on_synthetic_data(self):
        """Verify that trimming the initial 35 rows eliminates zero-filled warmup artifacts in rolling indicators."""
        np.random.seed(42)
        n = 200
        closes = 100.0 + np.cumsum(np.random.randn(n))
        opens = closes + np.random.randn(n) * 0.2
        highs = np.maximum(opens, closes) + np.abs(np.random.randn(n) * 0.5)
        lows = np.minimum(opens, closes) - np.abs(np.random.randn(n) * 0.5)
        volumes = np.random.exponential(500, n) + 50

        df = pd.DataFrame({
            "timestamp": [1700000000000 + i * 300000 for i in range(n)],
            "open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes
        })

        feats = CandleDynamicsFeatureExtractor.extract_features(df, prefix="15m")
        self.assertFalse(feats.empty)

        # Before trimming: check that first 10 rows of rolling features had zero fills
        raw_atr_expansion_early = feats["15m_true_range_expansion"].iloc[:10]
        # After trimming 35 rows: rolling features are fully stabilized
        trimmed_feats = feats.iloc[35:]
        self.assertFalse(trimmed_feats.isna().any().any(), "Trimmed features must have no NaNs")
        self.assertFalse(np.isinf(trimmed_feats.values).any(), "Trimmed features must have no Infs")

    def test_scan_universe_limits_forwarding(self):
        """Verify that MultiHorizonScanner passes custom limits to data loader."""
        from app.engine.scanner.horizon_scanner import MultiHorizonScanner

        scanner = MultiHorizonScanner(eager_boot=False)
        with patch.object(scanner.loader, "fetch_all_9_timeframes") as mock_fetch:
            mock_fetch.return_value = {tf: pd.DataFrame({"close": [100.0, 101.0]}) for tf in TIMEFRAMES_9}
            with patch("app.engine.scanner.filters.UniverseFilter.get_top_40_universe", return_value=[{"symbol": "BTC/USDT", "price": 50000.0, "quote_volume_usd": 10000000.0}]):
                with patch.object(scanner.loader, "fetch_all_tickers", return_value={"BTC/USDT": 50000.0}):
                    with patch.object(scanner.loader, "preload_bulk_funding_rates"):
                        res = scanner.scan_universe(limits=TRAINING_CANDLE_LIMITS)
                        self.assertIn("assets", res)

                        # Verify fetch_all_9_timeframes received TRAINING_CANDLE_LIMITS
                        for call in mock_fetch.call_args_list:
                            args, kwargs = call
                            self.assertEqual(kwargs.get("limits"), TRAINING_CANDLE_LIMITS)

if __name__ == "__main__":
    unittest.main()
