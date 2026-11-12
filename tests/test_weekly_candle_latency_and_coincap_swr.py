"""
Quant Edge V16 — Weekly Candle Latency & CoinCap/SWR Fallback Test Suite
======================================================================
Verifies:
1. Fast-path hierarchical 1D -> 1W resampling on newly listed coins (< 14 bars) eliminating network latency.
2. Graceful CoinCap/SWR reference rate fallback when primary exchanges return insufficient history (< 2 bars).
3. Wide-spread dampening / predatory wick mitigation on macro candles (spread > 40%).
4. Outage false-positive guard: single macro horizon missing never trips Global Outage NTZ.
5. Full mathematical and interface parity across MultiHorizonDataLoader and CryptoDataLoader (test.py).
"""

import unittest
import time
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock

from app.engine.scanner.data_loader import MultiHorizonDataLoader
from test import CryptoDataLoader


class TestWeeklyCandleLatencyAndCoinCapSWR(unittest.TestCase):
    """Forensic verification for weekly candle latency, wide-spread dampening, and CoinCap/SWR fallback."""

    def setUp(self):
        self.loader = MultiHorizonDataLoader()
        self.crypto_loader = CryptoDataLoader()

    def test_01_weekly_hierarchical_fast_path_low_latency(self):
        """
        AC-01: When 1D candles are present with >= 2 bars (even if < 14 bars, e.g. newly listed token with 5 days),
        fetch_all_9_timeframes immediately synthesizes 1W in-memory from 1D, avoiding 10-30s sequential exchange timeouts.
        """
        now = time.time()
        now_ms = int(now * 1000)
        day_ms = 86400 * 1000

        # Construct 5 daily candles (new token listed 5 days ago)
        df_1d_rows = []
        for i in range(5):
            t = now_ms - (4 - i) * day_ms
            p = 10.0 + i * 0.5
            df_1d_rows.append({
                "timestamp": t,
                "datetime": pd.to_datetime(t, unit="ms", utc=True),
                "open": p,
                "high": p + 0.5,
                "low": p - 0.3,
                "close": p + 0.2,
                "volume": 10000.0,
                "taker_buy_vol": 5000.0
            })
        df_1d = pd.DataFrame(df_1d_rows)

        # Mock fetch_single_timeframe_raw to track if network calls were made for 1w
        network_calls = []
        def mock_fetch(sym, tf, limit=120, allow_alias_fallback=True):
            network_calls.append(tf)
            if tf == "1d":
                return df_1d.copy()
            # 5m, 15m, 1h return baseline
            return df_1d.copy()

        with patch.object(self.loader, "fetch_single_timeframe_raw", side_effect=mock_fetch):
            t_start = time.perf_counter()
            results = self.loader.fetch_all_9_timeframes("NEWCOIN/USDT")
            elapsed = time.perf_counter() - t_start

        self.assertIn("1w", results)
        df_1w = results["1w"]
        self.assertIsNotNone(df_1w)
        self.assertGreaterEqual(len(df_1w), 2)
        self.assertEqual(df_1w.attrs.get("resampled_from"), "1d")
        # Ensure 1w was resampled in-memory and not queried via slow network fallback
        self.assertNotIn("1w", network_calls)
        self.assertLess(elapsed, 1.5, "Hierarchical synthesis must be sub-second in-memory without network blocking")

    def test_02_coincap_swr_fallback_macro_candles(self):
        """
        AC-02: When primary exchanges return insufficient history (< 2 candles or empty) for 1w,
        _build_coincap_swr_macro_fallback constructs a clean 2-candle baseline anchored to reference price.
        """
        symbol = "ILLIQUID/USDT"
        ref_price = 42.50

        with patch.object(self.loader, "get_live_price", return_value=ref_price):
            macro_df = self.loader._build_coincap_swr_macro_fallback(symbol, "1w")

        self.assertIsNotNone(macro_df)
        self.assertEqual(len(macro_df), 2)
        self.assertTrue(macro_df.attrs.get("is_synthetic"))
        self.assertEqual(macro_df.attrs.get("exchange_source"), "coincap_swr_fallback")
        self.assertEqual(macro_df.attrs.get("reference_price"), ref_price)

        # Verify OHLCV geometry
        for col in ["open", "high", "low", "close", "volume", "taker_buy_vol"]:
            self.assertIn(col, macro_df.columns)
            self.assertTrue((macro_df[col] > 0).all())

        # Verify close price is anchored to reference rate
        self.assertAlmostEqual(float(macro_df["close"].iloc[-1]), ref_price, places=2)

    def test_03_wide_spread_macro_wick_dampening(self):
        """
        AC-03: On low-liquidity assets with predatory wicks ((high - low) / close > 0.40),
        _dampen_wide_spread_macro_wicks clamps extreme wicks relative to reference price.
        """
        symbol = "WICKCOIN/USDT"
        ref_price = 10.0

        # Construct candle with blowout predatory wick: High = 100.0, Low = 1.0, Close = 10.0 (spread = 9.9)
        now_ms = int(time.time() * 1000)
        df_blowout = pd.DataFrame([
            {
                "timestamp": now_ms - 7 * 86400 * 1000,
                "open": 9.8,
                "high": 10.2,
                "low": 9.5,
                "close": 10.0,
                "volume": 1000.0,
                "taker_buy_vol": 500.0
            },
            {
                "timestamp": now_ms,
                "open": 10.0,
                "high": 100.0,  # 10x predatory spike
                "low": 1.0,     # 90% predatory dump
                "close": 10.0,
                "volume": 500.0,
                "taker_buy_vol": 250.0
            }
        ])

        with patch.object(self.loader, "get_live_price", return_value=ref_price):
            damped_df = self.loader._dampen_wide_spread_macro_wicks(symbol, "1w", df_blowout)

        self.assertTrue(damped_df.attrs.get("wide_spread_dampened"))
        damped_high = float(damped_df["high"].iloc[-1])
        damped_low = float(damped_df["low"].iloc[-1])

        # High must be clamped to safe boundary (< 20.0, not 100.0)
        self.assertLess(damped_high, 20.0)
        self.assertGreaterEqual(damped_high, 10.0)

        # Low must be clamped to safe boundary (> 5.0, not 1.0)
        self.assertGreater(damped_low, 5.0)
        self.assertLessEqual(damped_low, 10.0)

        # Structural price invariant: Low <= Close <= High
        self.assertTrue((damped_df["low"] <= damped_df["close"]).all())
        self.assertTrue((damped_df["close"] <= damped_df["high"]).all())

    def test_04_normal_spread_macro_wick_preserved(self):
        """
        AC-04: Standard market candles with spread <= 40% are not mutated by wick dampener.
        """
        symbol = "BTC/USDT"
        now_ms = int(time.time() * 1000)
        df_normal = pd.DataFrame([
            {
                "timestamp": now_ms,
                "open": 60000.0,
                "high": 61500.0,  # 2.5% wick
                "low": 59500.0,
                "close": 61000.0,
                "volume": 50000.0,
                "taker_buy_vol": 25000.0
            }
        ])

        with patch.object(self.loader, "get_live_price", return_value=61000.0):
            res_df = self.loader._dampen_wide_spread_macro_wicks(symbol, "1w", df_normal)

        self.assertFalse(res_df.attrs.get("wide_spread_dampened", False))
        self.assertEqual(float(res_df["high"].iloc[0]), 61500.0)
        self.assertEqual(float(res_df["low"].iloc[0]), 59500.0)

    def test_05_global_outage_guard_single_macro_missing_does_not_trip_ntz(self):
        """
        AC-05: Missing 1w alone on a newly listed token must NOT trip the Global Outage circuit breaker.
        """
        symbol = "NEWLISTED/USDT"
        now = time.time()
        now_ms = int(now * 1000)

        # 5m, 15m, 1h, 1d are live and healthy
        def create_sample_df(n=50):
            rows = []
            for i in range(n):
                rows.append({
                    "timestamp": now_ms - (n - i) * 60000,
                    "datetime": pd.to_datetime(now_ms - (n - i) * 60000, unit="ms", utc=True),
                    "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0,
                    "volume": 100.0, "taker_buy_vol": 50.0
                })
            return pd.DataFrame(rows)

        healthy_df = create_sample_df()

        # Mock: 1w fails, while 5m, 15m, 1h, 1d succeed
        def mock_fetch(sym, tf, limit=120, allow_alias_fallback=True):
            if tf in ["1w", "15d", "1M"]:
                return None
            return healthy_df.copy()

        with patch.object(self.loader, "fetch_single_timeframe_raw", side_effect=mock_fetch):
            with patch.object(self.loader, "get_live_price", return_value=10.0):
                with patch.object(self.loader, "get_live_price_with_freshness", return_value=(10.0, True, 1.0)):
                    output = self.loader.fetch_all_9_timeframes(symbol)

        # Crucial check: global outage is FALSE because core anchors are fresh
        self.assertFalse(self.loader.is_partition_stale_active())
        self.assertFalse(self.loader._is_global_outage)

    def test_06_global_outage_trips_when_all_core_anchors_fail(self):
        """
        AC-06: When all core intraday anchors (5m, 15m, 1h, 1d) fail and fall back to stale cache,
        global outage correctly activates.
        """
        symbol = "ALL_DOWN/USDT"
        now = time.time()
        now_ms = int(now * 1000)

        # Stale cached data (age: 1200 seconds > 600s intraday threshold)
        stale_df = pd.DataFrame([{
            "timestamp": now_ms - 1200000,
            "datetime": pd.to_datetime(now_ms - 1200000, unit="ms", utc=True),
            "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0,
            "volume": 100.0, "taker_buy_vol": 50.0
        }, {
            "timestamp": now_ms - 1100000,
            "datetime": pd.to_datetime(now_ms - 1100000, unit="ms", utc=True),
            "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0,
            "volume": 100.0, "taker_buy_vol": 50.0
        }])

        def mock_fetch(sym, tf, limit=120, allow_alias_fallback=True):
            return None

        def mock_load_cache(k):
            return (stale_df.copy(), now - 1200.0)

        with patch.object(self.loader, "fetch_single_timeframe_raw", side_effect=mock_fetch):
            with patch.object(self.loader, "_load_from_disk_cache", side_effect=mock_load_cache):
                with patch.object(self.loader, "get_live_price_with_freshness", return_value=(10.0, False, 1200.0)):
                    output = self.loader.fetch_all_9_timeframes(symbol)

        # Since all core anchors failed and intraday staleness > 600s is detected, global outage trips
        self.assertTrue(self.loader._is_global_outage)

    def test_07_test_py_crypto_data_loader_weekly_resampling_parity(self):
        """
        AC-07: In test.py, CryptoDataLoader.fetch_ohlcv_extended successfully resamples 1w from 1d candles
        when 1w has no direct exchange records, instead of raising ValueError.
        """
        symbol = "PARITY/USDT"
        now_ms = int(time.time() * 1000)
        day_ms = 86400 * 1000

        # Construct 14 daily candles in batch format [ts, o, h, l, c, v]
        batch_1d = []
        for i in range(14):
            t = now_ms - (13 - i) * day_ms
            p = 50.0 + i
            batch_1d.append([t, p, p + 2.0, p - 1.0, p + 1.0, 5000.0])

        def mock_bybit(sym, tf, limit=200):
            if tf == "1d":
                return batch_1d
            return []  # 1w returns empty

        with patch.object(self.crypto_loader, "_fetch_bybit_klines", side_effect=mock_bybit):
            with patch.object(self.crypto_loader, "_fetch_okx_klines", return_value=[]):
                with patch.object(self.crypto_loader, "_fetch_gateio_klines", return_value=[]):
                    with patch.object(self.crypto_loader, "_fetch_kucoin_klines", return_value=[]):
                        with patch.object(self.crypto_loader, "_fetch_binance_vision_klines", return_value=[]):
                            df_1w = self.crypto_loader.fetch_ohlcv_extended(symbol, "1w", total_candles=10)

        self.assertIsNotNone(df_1w)
        self.assertGreaterEqual(len(df_1w), 2)
        self.assertTrue(df_1w.attrs.get("is_synthetic"))
        self.assertEqual(df_1w.attrs.get("resampled_from"), "1d")

    def test_08_test_py_crypto_data_loader_coincap_swr_macro_fallback_no_crash(self):
        """
        AC-08: In test.py, CryptoDataLoader.fetch_ohlcv_extended falls back to CoinCap/SWR reference price
        when both 1w and 1d return no exchange data, returning a valid 2-candle DataFrame rather than throwing ValueError.
        """
        symbol = "NO_DATA/USDT"
        ref_price = 12.34

        with patch.object(self.crypto_loader, "_load_from_disk_cache", return_value=None):
            with patch.object(self.crypto_loader, "_fetch_binance_vision_klines", return_value=[]):
                with patch.object(self.crypto_loader, "_fetch_bybit_klines", return_value=[]):
                    with patch.object(self.crypto_loader, "_fetch_okx_klines", return_value=[]):
                        with patch.object(self.crypto_loader, "_fetch_gateio_klines", return_value=[]):
                            with patch.object(self.crypto_loader, "_fetch_kucoin_klines", return_value=[]):
                                with patch.object(self.crypto_loader, "fetch_all_tickers", return_value={symbol: ref_price}):
                                    df_1w = self.crypto_loader.fetch_ohlcv_extended(symbol, "1w", total_candles=5)

        self.assertIsNotNone(df_1w)
        self.assertEqual(len(df_1w), 2)
        self.assertTrue(df_1w.attrs.get("is_synthetic"))
        self.assertEqual(df_1w.attrs.get("exchange_source"), "coincap_swr_fallback")
        self.assertAlmostEqual(float(df_1w["close"].iloc[-1]), ref_price, places=2)

    def test_09_cross_loader_dampening_parity(self):
        """
        AC-09: Verifies that both MultiHorizonDataLoader and CryptoDataLoader (test.py) produce
        matching dampening behavior for identical extreme wicks.
        """
        now_ms = int(time.time() * 1000)
        df_extreme = pd.DataFrame([{
            "timestamp": now_ms,
            "datetime": pd.to_datetime(now_ms, unit="ms", utc=True),
            "open": 20.0,
            "high": 200.0,  # 10x spike
            "low": 2.0,     # 90% dump
            "close": 20.0,
            "volume": 1000.0,
            "taker_buy_vol": 500.0
        }])

        with patch.object(self.loader, "get_live_price", return_value=20.0):
            damped_loader = self.loader._dampen_wide_spread_macro_wicks("TEST/USDT", "1w", df_extreme)

        with patch.object(self.crypto_loader, "fetch_all_tickers", return_value={"TEST/USDT": 20.0}):
            damped_test = self.crypto_loader._dampen_wide_spread_macro_wicks("TEST/USDT", "1w", df_extreme)

        # High dampening parity
        self.assertAlmostEqual(float(damped_loader["high"].iloc[0]), float(damped_test["high"].iloc[0]), places=2)
        # Low dampening parity
        self.assertAlmostEqual(float(damped_loader["low"].iloc[0]), float(damped_test["low"].iloc[0]), places=2)
        self.assertTrue(damped_loader.attrs.get("wide_spread_dampened"))
        self.assertTrue(damped_test.attrs.get("wide_spread_dampened"))

    def test_10_public_aggregator_multiplier_reconciliation_mapping(self):
        """
        AC-10: CoinCap and Coinpaprika provide index rates for base coins (e.g. MOG, LADYS, PEPE, BABYDOGE)
        rather than derivatives (1000000MOG, 10000LADYS, 1000PEPE, 1MBABYDOGE).
        _reconcile_public_aggregator_multipliers resolves through resolve_symbol_aliases and scales by
        (target_mult / 1.0) so public aggregator failovers are correctly reconciled across both loaders.
        """
        raw_coincap_rates = {
            "MOG/USDT": 0.000002,
            "MOGUSDT": 0.000002,
            "LADYS/USDT": 0.00000005,
            "PEPE/USDT": 0.00001,
            "SHIB/USDT": 0.00002,
            "BABYDOGE/USDT": 0.000000002,
            "BTC/USDT": 65000.0,
            "1INCH/USDT": 0.40,
        }

        for loader in [self.loader, self.crypto_loader]:
            reconciled = loader._reconcile_public_aggregator_multipliers(raw_coincap_rates)

            # 1. 1000000MOG scaled by 10^6: 0.000002 * 10^6 / 1.0 = 2.0
            self.assertIn("1000000MOG/USDT", reconciled)
            self.assertAlmostEqual(reconciled["1000000MOG/USDT"], 2.0, places=6)
            self.assertAlmostEqual(reconciled["1000000MOGUSDT"], 2.0, places=6)

            # 2. 10000LADYS scaled by 10^4: 0.00000005 * 10^4 / 1.0 = 0.0005
            self.assertIn("10000LADYS/USDT", reconciled)
            self.assertAlmostEqual(reconciled["10000LADYS/USDT"], 0.0005, places=8)

            # 3. 1000PEPE scaled by 10^3: 0.00001 * 10^3 / 1.0 = 0.01
            self.assertIn("1000PEPE/USDT", reconciled)
            self.assertAlmostEqual(reconciled["1000PEPE/USDT"], 0.01, places=6)

            # 4. 100000SHIB scaled by 10^5: 0.00002 * 10^5 / 1.0 = 2.0
            self.assertIn("100000SHIB/USDT", reconciled)
            self.assertAlmostEqual(reconciled["100000SHIB/USDT"], 2.0, places=6)

            # 5. 1MBABYDOGE scaled by 10^6: 0.000000002 * 10^6 / 1.0 = 0.002
            self.assertIn("1MBABYDOGE/USDT", reconciled)
            self.assertAlmostEqual(reconciled["1MBABYDOGE/USDT"], 0.002, places=8)

            # 6. Standard BTC unscaled (mult = 1.0)
            self.assertAlmostEqual(reconciled["BTC/USDT"], 65000.0, places=2)

            # 7. Exempt 1INCH unscaled (mult = 1.0)
            self.assertAlmostEqual(reconciled["1INCH/USDT"], 0.40, places=4)

    def test_11_coincap_macro_fallback_derivative_multiplier_scaling(self):
        """
        AC-11: When primary exchanges return insufficient history on derivative contracts (1000000MOG/USDT),
        macro candle fallback accurately anchors reference price to scaled public aggregator price ($2.0)
        rather than unscaled base coin rate ($0.000002).
        """
        raw_rates = {"MOGUSDT": 0.000002, "MOG/USDT": 0.000002}

        # 1. MultiHorizonDataLoader macro fallback
        with patch.object(self.loader, "get_live_price", return_value=0.0):
            with patch.object(self.loader, "_fetch_coincap_tickers", return_value=self.loader._reconcile_public_aggregator_multipliers(raw_rates)):
                macro_df = self.loader._build_coincap_swr_macro_fallback("1000000MOG/USDT", "1w")

        self.assertIsNotNone(macro_df)
        self.assertEqual(len(macro_df), 2)
        # Macro candle close must be $2.0, NOT $0.000002
        self.assertAlmostEqual(float(macro_df["close"].iloc[-1]), 2.0, places=4)
        self.assertEqual(macro_df.attrs.get("exchange_source"), "coincap_swr_fallback")

        # 2. CryptoDataLoader (test.py) macro fallback parity
        with patch.object(self.crypto_loader, "_load_from_disk_cache", return_value=None):
            with patch.object(self.crypto_loader, "_fetch_binance_vision_klines", return_value=[]):
                with patch.object(self.crypto_loader, "_fetch_bybit_klines", return_value=[]):
                    with patch.object(self.crypto_loader, "_fetch_okx_klines", return_value=[]):
                        with patch.object(self.crypto_loader, "_fetch_gateio_klines", return_value=[]):
                            with patch.object(self.crypto_loader, "_fetch_kucoin_klines", return_value=[]):
                                with patch.object(self.crypto_loader, "get_live_price", return_value=0.0):
                                    with patch.object(self.crypto_loader, "fetch_all_tickers", return_value=self.crypto_loader._reconcile_public_aggregator_multipliers(raw_rates)):
                                        df_1w = self.crypto_loader.fetch_ohlcv_extended("1000000MOG/USDT", "1w", total_candles=5)

        self.assertIsNotNone(df_1w)
        self.assertEqual(len(df_1w), 2)
        self.assertAlmostEqual(float(df_1w["close"].iloc[-1]), 2.0, places=4)

    def test_12_coinpaprika_fallback_parity_in_crypto_data_loader(self):
        """
        AC-12: Verifies that CryptoDataLoader in test.py possesses Tier-6.6 Coinpaprika
        failover and correctly reconciles multiplier derivatives when CoinCap is throttled.
        """
        mock_paprika_data = [
            {"symbol": "MOG", "quotes": {"USD": {"price": 0.000002}}},
            {"symbol": "BTC", "quotes": {"USD": {"price": 68000.0}}}
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_paprika_data

        with patch.object(self.crypto_loader.session, "get", return_value=mock_resp):
            ticks = self.crypto_loader._fetch_coinpaprika_tickers()

        self.assertIn("1000000MOG/USDT", ticks)
        self.assertAlmostEqual(ticks["1000000MOG/USDT"], 2.0, places=6)
        self.assertAlmostEqual(ticks["BTC/USDT"], 68000.0, places=2)


if __name__ == "__main__":
    unittest.main()
