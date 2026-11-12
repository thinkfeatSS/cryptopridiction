"""
QUANT EDGE V16 — CANDLE PAGINATION & DELTA-CACHE TEST SUITE
Validates:
1. Deep Multi-Page Pagination (1,500+ contiguous bars across 4h, 1h, 15m).
2. Closed-Candle Enforcement (zero live unclosed bar leakage).
3. Deduplication and strictly ascending timestamp continuity.
4. Read-Through Delta Caching:
   - Zero API calls when cache is up to date with last closed candle.
   - Exactly 1 lightweight delta API call when missing closed bars.
5. Dual Storage Engines: Parquet (pyarrow) & SQLite WAL persistence.
6. Rate Limit & Anti-Ban Governor:
   - Dynamic Binance X-MBX-USED-WEIGHT-1M threshold throttling.
   - HTTP 429/418 Retry-After backoff.
   - Bybit failover formatting.
"""

import os
import time
import shutil
import asyncio
import unittest
from typing import Optional, List, Dict, Any
from unittest.mock import AsyncMock, patch, MagicMock
import numpy as np
import pandas as pd

from data.cache_manager import OHLCVCacheManager, REQUIRED_COLUMNS
from data.candle_paginator import (
    AsyncCandlePaginator,
    RateLimitGovernor,
    TIMEFRAME_MS,
    TARGET_CANDLE_DEPTHS,
    get_mtf_candles_batch,
    get_mtf_candles_batch_sync,
)


class TestCandlePaginationAndCache(unittest.TestCase):
    """Exhaustive test suite for OHLCV pagination, delta caching, and rate limiting."""

    def setUp(self):
        self.test_cache_dir = os.path.join("scratch", "test_ohlcv_cache")
        if os.path.exists(self.test_cache_dir):
            shutil.rmtree(self.test_cache_dir, ignore_errors=True)
        os.makedirs(self.test_cache_dir, exist_ok=True)

        self.cache_parquet = OHLCVCacheManager(base_dir=self.test_cache_dir, backend="parquet", max_bars=3000)
        self.cache_sqlite = OHLCVCacheManager(base_dir=self.test_cache_dir, backend="sqlite", max_bars=3000)

    def tearDown(self):
        if os.path.exists(self.test_cache_dir):
            shutil.rmtree(self.test_cache_dir, ignore_errors=True)

    def _generate_synthetic_candles(
        self,
        num_candles: int = 100,
        timeframe: str = "15m",
        start_ts: Optional[int] = None,
    ) -> pd.DataFrame:
        """Helper to generate contiguous synthetic candles."""
        tf_ms = TIMEFRAME_MS[timeframe]
        if start_ts is None:
            # End 1 hour ago so all candles are guaranteed closed
            end_ts = int(time.time() * 1000) - (4 * tf_ms)
            start_ts = end_ts - (num_candles * tf_ms)

        timestamps = [start_ts + i * tf_ms for i in range(num_candles)]
        opens = [100.0 + (i * 0.1) for i in range(num_candles)]
        highs = [o + 1.5 for o in opens]
        lows = [o - 1.0 for o in opens]
        closes = [o + 0.5 for o in opens]
        volumes = [1000.0 + (i * 10) for i in range(num_candles)]

        return pd.DataFrame({
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        })

    def test_01_cache_manager_parquet_save_and_load(self):
        """Verifies Parquet storage engine saves, loads, and tracks timestamps accurately."""
        df = self._generate_synthetic_candles(num_candles=150, timeframe="15m")
        saved = self.cache_parquet.save_candles("BTC/USDT", "15m", df, exchange="binance")
        self.assertTrue(saved, "Failed to save candles to Parquet cache")

        loaded = self.cache_parquet.load_cached_candles("BTC/USDT", "15m", exchange="binance")
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded), 150)
        self.assertEqual(list(loaded.columns), REQUIRED_COLUMNS)

        # Check precision
        np.testing.assert_allclose(loaded["close"].to_numpy(), df["close"].to_numpy(), rtol=1e-8)
        self.assertEqual(loaded["timestamp"].dtype, np.int64)
        self.assertEqual(loaded["close"].dtype, np.float64)

        # Check timestamps
        latest_ts = self.cache_parquet.get_latest_cached_timestamp("BTC/USDT", "15m", exchange="binance")
        earliest_ts = self.cache_parquet.get_earliest_cached_timestamp("BTC/USDT", "15m", exchange="binance")
        self.assertEqual(latest_ts, int(df["timestamp"].max()))
        self.assertEqual(earliest_ts, int(df["timestamp"].min()))

    def test_02_cache_manager_sqlite_save_and_load(self):
        """Verifies SQLite WAL storage engine saves, loads, and handles queries accurately."""
        df = self._generate_synthetic_candles(num_candles=200, timeframe="1h")
        saved = self.cache_sqlite.save_candles("ETH/USDT", "1h", df, exchange="binance")
        self.assertTrue(saved, "Failed to save candles to SQLite cache")

        loaded = self.cache_sqlite.load_cached_candles("ETH/USDT", "1h", exchange="binance")
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded), 200)

        latest_ts = self.cache_sqlite.get_latest_cached_timestamp("ETH/USDT", "1h", exchange="binance")
        self.assertEqual(latest_ts, int(df["timestamp"].max()))

        # Verify clear cache
        self.cache_sqlite.clear_cache(symbol="ETH/USDT", timeframe="1h")
        reloaded = self.cache_sqlite.load_cached_candles("ETH/USDT", "1h", exchange="binance")
        self.assertIsNone(reloaded)

    def test_03_merge_and_prune_deduplication_and_limit(self):
        """Verifies merge_and_prune eliminates duplicate timestamps and caps at max_bars."""
        cm = OHLCVCacheManager(base_dir=self.test_cache_dir, max_bars=50)

        # Base 40 candles: ts 0 to 39
        df_base = self._generate_synthetic_candles(num_candles=40, timeframe="15m", start_ts=1000000)
        # New 30 candles: ts 30 to 59 (overlapping 10 candles)
        tf_ms = TIMEFRAME_MS["15m"]
        df_new = self._generate_synthetic_candles(num_candles=30, timeframe="15m", start_ts=1000000 + (30 * tf_ms))

        merged = cm.merge_and_prune(df_base, df_new, max_bars=50)
        # Total unique candles = 60, capped at max_bars = 50
        self.assertEqual(len(merged), 50)
        # Verify timestamps are strictly ascending with no duplicates
        diffs = np.diff(merged["timestamp"].to_numpy())
        self.assertTrue(np.all(diffs == tf_ms), f"Non-contiguous diffs found: {diffs}")
        # Verify latest timestamp matches the newest candle
        self.assertEqual(merged["timestamp"].iloc[-1], df_new["timestamp"].iloc[-1])

    def test_04_closed_candle_filtering_zero_intrabar_leakage(self):
        """Verifies active unclosed live candles are strictly discarded."""
        now_ms = int(time.time() * 1000)
        tf_ms = TIMEFRAME_MS["15m"]

        # Candle 1: Closed 30 mins ago
        ts1 = now_ms - (2 * tf_ms)
        # Candle 2: Closed 15 mins ago
        ts2 = now_ms - (1 * tf_ms)
        # Candle 3: Forming right now (started 2 minutes ago, closes in 13 minutes)
        ts3_forming = now_ms - (2 * 60 * 1000)

        df = pd.DataFrame({
            "timestamp": [ts1, ts2, ts3_forming],
            "open": [100.0, 101.0, 102.0],
            "high": [105.0, 106.0, 107.0],
            "low": [99.0, 100.0, 101.0],
            "close": [101.0, 102.0, 103.0],
            "volume": [500.0, 600.0, 700.0],
        })

        filtered = AsyncCandlePaginator.filter_unclosed_candle(df, "15m")
        # Must retain only ts1 and ts2
        self.assertEqual(len(filtered), 2)
        self.assertNotIn(ts3_forming, filtered["timestamp"].values)
        self.assertEqual(list(filtered["timestamp"].values), [ts1, ts2])

    def test_05_parse_raw_klines_sanitization(self):
        """Verifies raw exchange kline arrays are parsed and cleaned with type safety."""
        # Binance format: [open_time, open, high, low, close, volume, close_time, ...]
        raw = [
            [1700000000000, "100.5", "105.2", "99.8", "104.1", "1250.5", 1700000899999],
            [1700000900000, "104.1", "108.0", "103.5", "107.2", "1430.0", 1700001799999],
            ["corrupted_row"],  # Bad row should be ignored
        ]

        df = AsyncCandlePaginator.parse_raw_klines(raw)
        self.assertEqual(len(df), 2)
        self.assertEqual(df["timestamp"].iloc[0], 1700000000000)
        self.assertEqual(df["close"].iloc[1], 107.2)
        self.assertEqual(df["volume"].dtype, np.float64)

    def test_06_multi_page_pagination_assembly(self):
        """Verifies backward pagination assembles 2,000 contiguous candles across multiple pages."""
        paginator = AsyncCandlePaginator(cache_manager=self.cache_parquet)
        tf_ms = TIMEFRAME_MS["15m"]
        now_ms = int(time.time() * 1000)
        base_start = now_ms - (2100 * tf_ms)

        # Generate 2,000 fake candles in 2 chunks of 1,000
        page1_bars = []  # Older 1000 bars
        for i in range(1000):
            ts = base_start + (i * tf_ms)
            page1_bars.append([ts, 100.0, 105.0, 95.0, 102.0, 1000.0, ts + tf_ms - 1])

        page2_bars = []  # Newer 1000 bars
        for i in range(1000, 2000):
            ts = base_start + (i * tf_ms)
            page2_bars.append([ts, 102.0, 107.0, 98.0, 104.0, 1200.0, ts + tf_ms - 1])

        # Mock _fetch_single_page_binance
        call_count = 0

        async def mock_fetch(session, symbol, timeframe, start_time=None, end_time=None, limit=1000):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First backward page returns newer bars (page2)
                return page2_bars
            elif call_count == 2:
                # Second backward page returns older bars (page1)
                return page1_bars
            return []

        paginator._fetch_single_page_binance = mock_fetch

        async def run_test():
            try:
                return await paginator.paginate_historical_depth("SOL/USDT", "15m", target_candles=2000)
            finally:
                await paginator.close()

        df = asyncio.run(run_test())
        self.assertGreaterEqual(len(df), 1950)
        # Check continuity
        diffs = np.diff(df["timestamp"].to_numpy())
        self.assertTrue(np.all(diffs == tf_ms), f"Non-contiguous assembly: {diffs[diffs != tf_ms]}")

    def test_07_warm_cache_zero_call_hit(self):
        """Verifies that a fully warm cache returns immediately with 0 REST calls."""
        paginator = AsyncCandlePaginator(cache_manager=self.cache_parquet)
        tf_ms = TIMEFRAME_MS["15m"]
        now_ms = int(time.time() * 1000)

        # Seed cache with candles up to the most recent closed candle
        last_closed_ts = (now_ms // tf_ms) * tf_ms - tf_ms
        num_candles = 1600
        start_ts = last_closed_ts - ((num_candles - 1) * tf_ms)
        df_seed = self._generate_synthetic_candles(num_candles=num_candles, timeframe="15m", start_ts=start_ts)
        self.cache_parquet.save_candles("BTC/USDT", "15m", df_seed)

        api_called = False

        async def mock_fetch(*args, **kwargs):
            nonlocal api_called
            api_called = True
            return []

        paginator._fetch_single_page_binance = mock_fetch

        async def run_test():
            try:
                return await paginator.get_candles_with_cache("BTC/USDT", "15m", min_candles=1500)
            finally:
                await paginator.close()

        result_df = asyncio.run(run_test())
        self.assertFalse(api_called, "API call was made despite warm cache!")
        self.assertEqual(len(result_df), 1600)
        self.assertEqual(result_df["timestamp"].iloc[-1], last_closed_ts)

    def test_08_warm_cache_single_delta_fetch(self):
        """Verifies that a cache missing 2 closed candles executes exactly 1 delta fetch."""
        paginator = AsyncCandlePaginator(cache_manager=self.cache_parquet)
        tf_ms = TIMEFRAME_MS["15m"]
        now_ms = int(time.time() * 1000)

        # Cache is missing the last 2 closed bars
        last_closed_ts = (now_ms // tf_ms) * tf_ms - tf_ms
        cached_last_ts = last_closed_ts - (2 * tf_ms)
        num_cached = 1500
        start_ts = cached_last_ts - ((num_cached - 1) * tf_ms)

        df_seed = self._generate_synthetic_candles(num_candles=num_cached, timeframe="15m", start_ts=start_ts)
        self.cache_parquet.save_candles("ETH/USDT", "15m", df_seed)

        delta_calls = 0

        async def mock_fetch(session, symbol, timeframe, start_time=None, end_time=None, limit=1000):
            nonlocal delta_calls
            delta_calls += 1
            # Return the 2 missing closed bars
            bar1 = [cached_last_ts + tf_ms, 2000.0, 2010.0, 1995.0, 2005.0, 500.0, cached_last_ts + 2 * tf_ms - 1]
            bar2 = [last_closed_ts, 2005.0, 2015.0, 2000.0, 2012.0, 600.0, last_closed_ts + tf_ms - 1]
            return [bar1, bar2]

        paginator._fetch_single_page_binance = mock_fetch

        async def run_test():
            try:
                return await paginator.get_candles_with_cache("ETH/USDT", "15m", min_candles=1500)
            finally:
                await paginator.close()

        result_df = asyncio.run(run_test())
        self.assertEqual(delta_calls, 1, f"Expected exactly 1 delta call, got {delta_calls}")
        self.assertEqual(len(result_df), 1502)
        self.assertEqual(result_df["timestamp"].iloc[-1], last_closed_ts)

        # Verify cache was updated on disk
        reloaded = self.cache_parquet.load_cached_candles("ETH/USDT", "15m")
        self.assertEqual(len(reloaded), 1502)
        self.assertEqual(reloaded["timestamp"].iloc[-1], last_closed_ts)

    def test_09_rate_limit_governor_high_weight_throttle(self):
        """Verifies governor throttles when Binance X-MBX-USED-WEIGHT-1M exceeds 75%."""
        governor = RateLimitGovernor(max_concurrent=4, weight_threshold_pct=0.75, minute_weight_cap=1200)

        # Simulate response header with weight 950 (> 900)
        headers = {"X-MBX-USED-WEIGHT-1M": "950"}
        governor.update_from_headers(headers, exchange="binance")

        self.assertEqual(governor.current_used_weight_1m, 950)

        # Test pacing trigger (mock sleep to avoid actual waiting)
        sleep_called = False
        async def mock_sleep(seconds):
            nonlocal sleep_called
            sleep_called = True

        with patch("asyncio.sleep", mock_sleep):
            asyncio.run(governor.acquire_pacing())

        self.assertTrue(sleep_called, "Governor did not throttle upon high weight threshold!")

    def test_10_rate_limit_governor_429_backoff(self):
        """Verifies governor triggers cooloff upon HTTP 429/418 with Retry-After."""
        governor = RateLimitGovernor()
        now = time.time()
        governor.trigger_rate_limit_backoff(retry_after=15.0)

        self.assertGreaterEqual(governor.cooloff_until, now + 14.5)

    def test_11_bybit_failover_formatting(self):
        """Verifies Bybit klines (descending) are reversed and mapped properly."""
        # Bybit format: list of [startTime, open, high, low, close, volume, turnover]
        bybit_list = [
            ["1700000900000", "104.1", "108.0", "103.5", "107.2", "1430.0", "150000.0"],  # Newer
            ["1700000000000", "100.5", "105.2", "99.8", "104.1", "1250.5", "130000.0"],   # Older
        ]

        paginator = AsyncCandlePaginator(cache_manager=self.cache_parquet)

        # Mock Bybit response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.headers = {}
        mock_response.json = AsyncMock(return_value={
            "retCode": 0,
            "result": {"list": bybit_list}
        })

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock()))

        async def run_bybit():
            return await paginator._fetch_single_page_bybit(mock_session, "BTC/USDT", "15m")

        formatted = asyncio.run(run_bybit())
        self.assertEqual(len(formatted), 2)
        # Should be ordered ascending
        self.assertEqual(formatted[0][0], 1700000000000)
        self.assertEqual(formatted[1][0], 1700000900000)
        self.assertEqual(formatted[1][4], 107.2)

    def test_12_batch_loader_multi_timeframe_sync_and_async(self):
        """Verifies get_mtf_candles_batch and get_mtf_candles_batch_sync return expected structure."""
        symbols = ["BTC/USDT", "ETH/USDT"]
        timeframes = ["4h", "1h", "15m"]

        # Pre-seed cache for both coins across all 3 timeframes
        now_ms = int(time.time() * 1000)
        for sym in symbols:
            for tf in timeframes:
                tf_ms = TIMEFRAME_MS[tf]
                last_closed = (now_ms // tf_ms) * tf_ms - tf_ms
                df = self._generate_synthetic_candles(num_candles=100, timeframe=tf, start_ts=last_closed - (99 * tf_ms))
                self.cache_parquet.save_candles(sym, tf, df)

        # Run synchronous batch loader
        batch_res = get_mtf_candles_batch_sync(
            symbols=symbols,
            timeframes=timeframes,
            min_candles=100,
            cache_manager=self.cache_parquet,
        )

        self.assertIn("BTC/USDT", batch_res)
        self.assertIn("ETH/USDT", batch_res)
        for tf in timeframes:
            self.assertIn(tf, batch_res["BTC/USDT"])
            self.assertEqual(len(batch_res["BTC/USDT"][tf]), 100)
            self.assertIn(tf, batch_res["ETH/USDT"])
            self.assertEqual(len(batch_res["ETH/USDT"][tf]), 100)

    def test_13_data_loader_bar_boundary_and_depth_invalidation(self):
        """
        Regression Test (Live Data & Training Depth Freshness):
        1. Crossing a 15m bar boundary invalidates cached 15m candles immediately even inside 30s TTL.
        2. Requesting deep TRAINING_CANDLE_LIMITS (1000 bars) bypasses a shallower SCANNING_CANDLE_LIMITS (120 bars) cache.
        """
        from app.engine.scanner.data_loader import MultiHorizonDataLoader
        from app.engine.config import TIMEFRAMES_9

        loader = MultiHorizonDataLoader()
        sym = "0G/USDT"
        base_df = self._generate_synthetic_candles(num_candles=120, timeframe="15m")
        base_df.attrs["requested_limit"] = 120

        # Pre-seed all 9 TFs at t0 = 20s before 15m close boundary (1700000100 is divisible by 900 -> 1700000100 % 900 == 0? Check: 1700000100 = 1888889 * 900)
        boundary_ts = 1888889 * 900
        t0 = float(boundary_ts - 20)
        t_after_boundary = float(boundary_ts + 5) # Only 25s later (< 30s TTL), but crossed 15m close boundary!

        with loader._cache_lock:
            for tf in TIMEFRAMES_9:
                df_copy = base_df.copy()
                df_copy.attrs["requested_limit"] = 120
                loader._candle_cache[f"{sym}_{tf}"] = (df_copy, t0)

        fetched_calls = []

        def fake_fetch_raw(symbol, timeframe, limit=120):
            fetched_calls.append((timeframe, limit))
            out = self._generate_synthetic_candles(num_candles=min(limit, 200), timeframe=timeframe)
            return out

        with patch.object(loader, "fetch_single_timeframe_raw", side_effect=fake_fetch_raw), \
             patch.object(loader, "_load_from_disk_cache", return_value=None), \
             patch.object(loader, "_save_to_disk_cache", return_value=None), \
             patch("app.engine.scanner.data_loader.time.time", return_value=t_after_boundary):
            loader.fetch_all_9_timeframes(sym, limits={tf: 120 for tf in TIMEFRAMES_9})

        fetched_tfs = [tf for tf, _ in fetched_calls]
        self.assertIn("15m", fetched_tfs, "15m cache MUST invalidate immediately on crossing a 15m candle close boundary")

        # Case 2: Requesting deep training limit (1000) within same bar and TTL MUST bypass 120-bar scanning cache
        fetched_calls.clear()
        same_bar_t1 = float(boundary_ts + 10)
        with loader._cache_lock:
            for tf in TIMEFRAMES_9:
                df_copy = base_df.copy()
                df_copy.attrs["requested_limit"] = 120
                loader._candle_cache[f"{sym}_{tf}"] = (df_copy, float(boundary_ts + 5))

        with patch.object(loader, "fetch_single_timeframe_raw", side_effect=fake_fetch_raw), \
             patch.object(loader, "_load_from_disk_cache", return_value=None), \
             patch.object(loader, "_save_to_disk_cache", return_value=None), \
             patch("app.engine.scanner.data_loader.time.time", return_value=same_bar_t1):
            loader.fetch_all_9_timeframes(sym, limits={"5m": 1000, "15m": 1000, "1h": 720, "4h": 500, "12h": 365, "1d": 500, "1w": 120, "15d": 60, "1M": 36})

        fetched_limits = dict(fetched_calls)
        self.assertGreaterEqual(fetched_limits.get("15m", 0), 1000, "Training depth limit must bypass shallow 120-bar scanning cache")
        self.assertGreaterEqual(fetched_limits.get("5m", 0), 1000)
        self.assertGreaterEqual(fetched_limits.get("1h", 0), 720)


if __name__ == "__main__":
    unittest.main()
