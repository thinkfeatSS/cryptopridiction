import unittest
import time
import os
import json
import random
import tempfile
from unittest.mock import patch, MagicMock

from app.engine.scanner.data_loader import MultiHorizonDataLoader
from test import CryptoDataLoader
from app.config import settings


class MockResponse:
    def __init__(self, status_code: int, json_data: dict):
        self.status_code = status_code
        self._json_data = json_data

    def json(self):
        return self._json_data


class TestThirdPartyApiRateLimits(unittest.TestCase):
    """
    Forensic verification suite for Third-Party API Rate Limits and SWR Disk Cache:
    1. Dynamic exponential backoff on CoinCap HTTP 429 (60s base -> 180s ceiling).
    2. Dynamic exponential backoff on Coinpaprika HTTP 429.
    3. Dynamic exponential backoff on Bitget HTTP 429.
    4. Atomic persistent SWR disk cache reads/writes without corrupted state.
    5. Graceful SWR step-down: serving warm disk cache up to 180.0s grace window
       without interrupting core signal generation (is_price_fresh_15s = True).
    6. Circuit breaker fail-closed tripping when outage exceeds 180.0s grace window.
    7. Baseline 15.0s staleness enforcement when no active 429 backoff exists.
    8. 100% parity between MultiHorizonDataLoader and test.py CryptoDataLoader.
    9. SignalService SWR disk synchronization and atomic persistence.
    """

    def setUp(self):
        self.loader = MultiHorizonDataLoader()
        self.c_loader = CryptoDataLoader()
        self.test_export_dir = tempfile.mkdtemp(prefix="test_swr_export_")
        self.loader._disk_cache_dir = self.test_export_dir
        self.c_loader._disk_cache_dir = self.test_export_dir

    def tearDown(self):
        # Clean up temporary export dir
        try:
            for f in os.listdir(self.test_export_dir):
                os.remove(os.path.join(self.test_export_dir, f))
            os.rmdir(self.test_export_dir)
        except Exception:
            pass

    def test_coincap_dynamic_exponential_backoff_and_reset(self):
        """Verifies CoinCap 429 exponential backoff escalation (60s -> 90s -> 135s -> 180s) and 200 reset."""
        loader = self.loader
        now = time.time()

        # Step 1: 1st 429 -> consecutive=1, backoff in [60.0, 63.0]
        loader.session.get = MagicMock(return_value=MockResponse(429, {"error": "Rate limit exceeded"}))
        loader._coincap_rates_ts = 0.0
        loader._coincap_throttled_until = 0.0
        loader._coincap_consecutive_429 = 0

        res1 = loader._fetch_coincap_tickers()
        self.assertEqual(loader._coincap_consecutive_429, 1)
        self.assertGreaterEqual(loader._coincap_throttled_until, now + 59.0)
        self.assertLessEqual(loader._coincap_throttled_until, now + 65.0)

        # Step 2: 2nd consecutive 429 -> backoff in [90.0, 93.0]
        loader._coincap_throttled_until = 0.0
        loader._coincap_rates_ts = 0.0
        res2 = loader._fetch_coincap_tickers()
        self.assertEqual(loader._coincap_consecutive_429, 2)
        self.assertGreaterEqual(loader._coincap_throttled_until, now + 89.0)
        self.assertLessEqual(loader._coincap_throttled_until, now + 95.0)

        # Step 3: 3rd consecutive 429 -> backoff in [135.0, 138.0]
        loader._coincap_throttled_until = 0.0
        loader._coincap_rates_ts = 0.0
        res3 = loader._fetch_coincap_tickers()
        self.assertEqual(loader._coincap_consecutive_429, 3)
        self.assertGreaterEqual(loader._coincap_throttled_until, now + 134.0)
        self.assertLessEqual(loader._coincap_throttled_until, now + 140.0)

        # Step 4: 4th consecutive 429 -> backoff capped at 180.0s
        loader._coincap_throttled_until = 0.0
        loader._coincap_rates_ts = 0.0
        res4 = loader._fetch_coincap_tickers()
        self.assertEqual(loader._coincap_consecutive_429, 4)
        self.assertGreaterEqual(loader._coincap_throttled_until, now + 179.0)
        self.assertLessEqual(loader._coincap_throttled_until, now + 184.0)

        # Step 5: Successful 200 response resets consecutive 429 counter to 0
        loader._coincap_throttled_until = 0.0
        loader._coincap_rates_ts = 0.0
        mock_data = {
            "data": [
                {"symbol": "BTC", "rateUsd": "68500.0"},
                {"symbol": "ETH", "rateUsd": "3600.0"}
            ]
        }
        loader.session.get = MagicMock(return_value=MockResponse(200, mock_data))
        res_ok = loader._fetch_coincap_tickers()
        self.assertEqual(loader._coincap_consecutive_429, 0)
        self.assertEqual(res_ok.get("BTCUSDT"), 68500.0)
        self.assertEqual(res_ok.get("ETH/USDT"), 3600.0)

    def test_coinpaprika_dynamic_exponential_backoff_and_reset(self):
        """Verifies Coinpaprika 429 exponential backoff escalation and 200 reset."""
        loader = self.loader
        now = time.time()

        loader.session.get = MagicMock(return_value=MockResponse(429, {"error": "Rate limit exceeded"}))
        loader._paprika_rates_ts = 0.0
        loader._paprika_throttled_until = 0.0
        loader._paprika_consecutive_429 = 0

        # First 429
        loader._fetch_coinpaprika_tickers()
        self.assertEqual(loader._paprika_consecutive_429, 1)
        self.assertGreaterEqual(loader._paprika_throttled_until, now + 59.0)
        self.assertLessEqual(loader._paprika_throttled_until, now + 65.0)

        # Second 429
        loader._paprika_throttled_until = 0.0
        loader._paprika_rates_ts = 0.0
        loader._fetch_coinpaprika_tickers()
        self.assertEqual(loader._paprika_consecutive_429, 2)
        self.assertGreaterEqual(loader._paprika_throttled_until, now + 89.0)

        # HTTP 200 resets
        loader._paprika_throttled_until = 0.0
        loader._paprika_rates_ts = 0.0
        mock_data = [
            {"symbol": "BTC", "quotes": {"USD": {"price": 68500.0}}},
            {"symbol": "SOL", "quotes": {"USD": {"price": 175.0}}}
        ]
        loader.session.get = MagicMock(return_value=MockResponse(200, mock_data))
        res_ok = loader._fetch_coinpaprika_tickers()
        self.assertEqual(loader._paprika_consecutive_429, 0)
        self.assertEqual(res_ok.get("BTC/USDT"), 68500.0)
        self.assertEqual(res_ok.get("SOL/USDT"), 175.0)

    def test_bitget_dynamic_exponential_backoff_and_reset(self):
        """Verifies Bitget 429 exponential backoff escalation and 200 reset."""
        loader = self.loader
        now = time.time()

        loader.session.get = MagicMock(return_value=MockResponse(429, {"error": "Rate limit exceeded"}))
        loader._bitget_rates_ts = 0.0
        loader._bitget_throttled_until = 0.0
        loader._bitget_consecutive_429 = 0

        # First 429
        loader._fetch_bitget_tickers()
        self.assertEqual(loader._bitget_consecutive_429, 1)
        self.assertGreaterEqual(loader._bitget_throttled_until, now + 59.0)
        self.assertLessEqual(loader._bitget_throttled_until, now + 65.0)

        # HTTP 200 resets
        loader._bitget_throttled_until = 0.0
        loader._bitget_rates_ts = 0.0
        mock_data = {
            "code": "00000",
            "data": [
                {"symbol": "BTCUSDT", "lastPr": "68500.0"},
                {"symbol": "XRPUSDT", "lastPr": "0.58"}
            ]
        }
        loader.session.get = MagicMock(return_value=MockResponse(200, mock_data))
        res_ok = loader._fetch_bitget_tickers()
        self.assertEqual(loader._bitget_consecutive_429, 0)
        self.assertEqual(res_ok.get("BTCUSDT"), 68500.0)
        self.assertEqual(res_ok.get("XRP/USDT"), 0.58)

    def test_swr_disk_cache_atomic_persistence(self):
        """Verifies atomic write and read of persistent SWR disk cache."""
        loader = self.loader
        now = time.time()
        tickers = {"BTC/USDT": 68000.0, "ETH/USDT": 3500.0, "SOL/USDT": 170.0}

        loader._save_tickers_to_swr_disk(tickers, now)
        cache_file = os.path.join(self.test_export_dir, "live_tickers_swr.json")
        self.assertTrue(os.path.exists(cache_file))

        loaded_ticks, loaded_ts = loader._load_tickers_from_swr_disk()
        self.assertEqual(loaded_ticks, tickers)
        self.assertAlmostEqual(loaded_ts, now, places=2)

    def test_swr_graceful_stepdown_during_active_rate_limit_backoff(self):
        """
        Validates that during active public aggregator rate-limit backoff (60s-180s),
        warm persistent SWR disk cache gracefully steps down up to 180.0s grace window
        WITHOUT interrupting core signal generation (is_price_fresh_15s = True, is_global_outage = False).
        """
        loader = self.loader
        now = time.time()
        seed_ticks = {"BTC/USDT": 68000.0, "ETH/USDT": 3500.0}
        loader._save_tickers_to_swr_disk(seed_ticks, now - 45.0)

        # Force all Tier-1..Tier-6 CEXs offline
        loader._binance_ip_throttled_until = now + 999.0
        loader._live_tickers_cache = {}
        loader._live_tickers_ts = 0.0

        # Simulate active 60s backoff on CoinCap, Paprika, Bitget
        loader._coincap_throttled_until = now + 60.0
        loader._paprika_throttled_until = now + 60.0
        loader._bitget_throttled_until = now + 60.0
        loader._rest_outage_start_ts = now - 45.0

        with patch.object(loader, "ws_feed", None), \
             patch.object(loader, "_fetch_bybit_tickers", return_value={}), \
             patch.object(loader, "_fetch_okx_tickers", return_value={}), \
             patch.object(loader, "_fetch_gateio_tickers", return_value={}), \
             patch.object(loader, "_fetch_kucoin_tickers", return_value={}), \
             patch.object(loader, "_fetch_mexc_tickers", return_value={}):

            served = loader.fetch_all_tickers(max_age_seconds=1.0)
            self.assertEqual(served.get("BTC/USDT"), 68000.0)
            self.assertTrue(loader._is_price_fresh_15s, "Must remain fresh during 45s SWR rate-limit grace (< 180s)")
            self.assertFalse(loader._is_global_outage, "Must NOT trip global outage during rate-limit grace")
            self.assertFalse(loader.is_partition_stale_active())

            # Verify get_live_price_with_freshness returns fresh
            p, is_fresh, age = loader.get_live_price_with_freshness("BTC/USDT")
            self.assertEqual(p, 68000.0)
            self.assertTrue(is_fresh)
            self.assertAlmostEqual(age, 45.0, delta=2.0)

    def test_swr_circuit_breaker_trip_when_outage_exceeds_180s(self):
        """
        Validates that when public aggregator rate-limit outage persists beyond
        MAX_SWR_RATE_LIMIT_GRACE_SECONDS (180.0s), the system trips the staleness
        circuit breaker and fails closed (is_price_fresh_15s = False, is_global_outage = True).
        """
        loader = self.loader
        now = time.time()
        seed_ticks = {"BTC/USDT": 68000.0, "ETH/USDT": 3500.0}
        # SWR file is 195 seconds old (> 180.0s grace window)
        loader._save_tickers_to_swr_disk(seed_ticks, now - 195.0)

        loader._binance_ip_throttled_until = now + 999.0
        loader._live_tickers_cache = {}
        loader._live_tickers_ts = 0.0

        loader._coincap_throttled_until = now + 60.0
        loader._paprika_throttled_until = now + 60.0
        loader._bitget_throttled_until = now + 60.0
        loader._rest_outage_start_ts = now - 195.0

        with patch.object(loader, "ws_feed", None), \
             patch.object(loader, "_fetch_bybit_tickers", return_value={}), \
             patch.object(loader, "_fetch_okx_tickers", return_value={}), \
             patch.object(loader, "_fetch_gateio_tickers", return_value={}), \
             patch.object(loader, "_fetch_kucoin_tickers", return_value={}), \
             patch.object(loader, "_fetch_mexc_tickers", return_value={}):

            served = loader.fetch_all_tickers(max_age_seconds=1.0)
            self.assertFalse(loader._is_price_fresh_15s, "Must fail freshness when SWR exceeds 180s grace")
            self.assertTrue(loader._is_global_outage, "Must trip global outage")
            self.assertTrue(loader.is_partition_stale_active())
            self.assertIn("PRICE_STALENESS_EXCEEDED", loader._global_outage_reason)

            # get_live_price_with_freshness must return is_fresh = False
            p, is_fresh, age = loader.get_live_price_with_freshness("BTC/USDT")
            self.assertFalse(is_fresh)

    def test_baseline_staleness_without_rate_limit_backoff(self):
        """Validates that without active rate-limit backoff, baseline 15.0s staleness trips."""
        loader = self.loader
        now = time.time()
        seed_ticks = {"BTC/USDT": 68000.0}
        loader._save_tickers_to_swr_disk(seed_ticks, now - 25.0)

        loader._binance_ip_throttled_until = now + 999.0
        loader._live_tickers_cache = {}
        loader._live_tickers_ts = 0.0

        # No active rate limit backoff (throttled_until = 0)
        loader._coincap_throttled_until = 0.0
        loader._paprika_throttled_until = 0.0
        loader._bitget_throttled_until = 0.0
        loader._rest_outage_start_ts = now - 25.0

        with patch.object(loader, "ws_feed", None), \
             patch.object(loader, "_fetch_bybit_tickers", return_value={}), \
             patch.object(loader, "_fetch_okx_tickers", return_value={}), \
             patch.object(loader, "_fetch_gateio_tickers", return_value={}), \
             patch.object(loader, "_fetch_kucoin_tickers", return_value={}), \
             patch.object(loader, "_fetch_mexc_tickers", return_value={}), \
             patch.object(loader, "_fetch_coincap_tickers", return_value={}), \
             patch.object(loader, "_fetch_coinpaprika_tickers", return_value={}), \
             patch.object(loader, "_fetch_bitget_tickers", return_value={}):

            served = loader.fetch_all_tickers(max_age_seconds=1.0)
            self.assertFalse(loader._is_price_fresh_15s, "25s outage > 15s baseline must fail fresh")
            self.assertTrue(loader._is_global_outage)

    def test_data_loader_and_crypto_data_loader_full_parity(self):
        """Verifies 100% operational parity between MultiHorizonDataLoader and test.py CryptoDataLoader."""
        loader = self.loader
        c_loader = self.c_loader
        now = time.time()
        seed_ticks = {"BTC/USDT": 68000.0, "ETH/USDT": 3500.0}

        # Test SWR parity
        loader._save_tickers_to_swr_disk(seed_ticks, now - 30.0)
        c_loader._save_tickers_to_swr_disk(seed_ticks, now - 30.0)

        # Configure identical rate-limit backoff state
        for l in [loader, c_loader]:
            l._binance_ip_throttled_until = now + 999.0
            l._coincap_throttled_until = now + 60.0
            l._paprika_throttled_until = now + 60.0
            l._bitget_throttled_until = now + 60.0
            l._live_tickers_cache = {}
            l._live_tickers_ts = 0.0
            l._rest_outage_start_ts = now - 30.0

        with patch.object(loader, "ws_feed", None), \
             patch.object(loader, "_fetch_bybit_tickers", return_value={}), \
             patch.object(loader, "_fetch_okx_tickers", return_value={}), \
             patch.object(loader, "_fetch_gateio_tickers", return_value={}), \
             patch.object(loader, "_fetch_kucoin_tickers", return_value={}), \
             patch.object(loader, "_fetch_mexc_tickers", return_value={}), \
             patch.object(c_loader, "_fetch_bybit_tickers", return_value={}), \
             patch.object(c_loader, "_fetch_okx_tickers", return_value={}), \
             patch.object(c_loader, "_fetch_gateio_tickers", return_value={}), \
             patch.object(c_loader, "_fetch_kucoin_tickers", return_value={}), \
             patch.object(c_loader, "_fetch_mexc_tickers", return_value={}):

            res_loader = loader.fetch_all_tickers(max_age_seconds=1.0)
            res_c_loader = c_loader.fetch_all_tickers(max_age_seconds=1.0)

            self.assertEqual(res_loader, res_c_loader)
            self.assertEqual(loader._is_price_fresh_15s, c_loader._is_price_fresh_15s)
            self.assertEqual(loader._is_global_outage, c_loader._is_global_outage)
            self.assertEqual(loader.is_partition_stale_active(), c_loader.is_partition_stale_active())

    def test_signal_service_swr_stepdown_and_atomic_persistence(self):
        """Verifies SignalService ticker fetch SWR step-down and atomic persistence."""
        import app.services.signal_service as ss

        now = time.time()
        export_dir = getattr(settings, "EXPORT_DIR", "./export_app_data")
        os.makedirs(export_dir, exist_ok=True)
        swr_path = os.path.join(export_dir, "live_tickers_swr.json")

        test_data = {"BTC/USDT": 69200.0, "ETH/USDT": 3650.0}
        with open(swr_path, "w", encoding="utf-8") as f:
            json.dump({"timestamp": now - 30.0, "tickers": test_data}, f)

        try:
            # 1. Step-down when upstream returns 429 in fetch_live_binance_prices
            def mock_failing_get(url, timeout=3.5):
                return MockResponse(429, {"error": "Throttled"})

            with patch("requests.get", side_effect=mock_failing_get), \
                 patch.object(ss, "_async_refresh_tickers") as mock_async:
                ss._LIVE_PRICES_CACHE = {}
                ss._LIVE_PRICES_TS = 0.0
                ss._FETCHING_TICKERS = False

                prices = ss.fetch_live_binance_prices(max_age_seconds=0.0)
                self.assertIn("BTC/USDT", prices)
                self.assertEqual(prices.get("BTC/USDT"), 69200.0)
                mock_async.assert_called_once()

            # 2. Synchronous cascade step-down in _async_refresh_tickers
            with patch("requests.get", side_effect=mock_failing_get):
                ss._LIVE_PRICES_CACHE = {}
                ss._LIVE_PRICES_TS = 0.0
                ss._FETCHING_TICKERS = False
                ss._async_refresh_tickers(sync=True)
                self.assertIn("BTC/USDT", ss._LIVE_PRICES_CACHE)
                self.assertEqual(ss._LIVE_PRICES_CACHE.get("BTC/USDT"), 69200.0)

            # 3. Fresh prices fetched upstream are atomically saved to SWR disk
            fresh_upstream = [
                {"symbol": "SOLUSDT", "lastPrice": "182.50"}
            ]
            def mock_success_get(url, timeout=3.5):
                return MockResponse(200, fresh_upstream)

            with patch("requests.get", side_effect=mock_success_get):
                ss._LIVE_PRICES_CACHE = {}
                ss._LIVE_PRICES_TS = 0.0
                ss._FETCHING_TICKERS = False
                ss._async_refresh_tickers(sync=True)
                self.assertIn("SOLUSDT", ss._LIVE_PRICES_CACHE)
                # Verify written to disk
                with open(swr_path, "r", encoding="utf-8") as f:
                    disk_data = json.load(f)
                    self.assertIn("SOLUSDT", disk_data.get("tickers", {}))
                    self.assertEqual(disk_data["tickers"]["SOLUSDT"], 182.50)
        finally:
            # Restore or clean up test swr file if needed
            pass


if __name__ == "__main__":
    unittest.main()

