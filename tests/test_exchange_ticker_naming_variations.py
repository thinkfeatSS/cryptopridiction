"""
Quant Edge V16 - Exchange Ticker Naming Variations & Multiplier Scaling Test Suite
==================================================================================
Forensic verification for:
1. Dynamic contract multiplier prefix identification & stripping beyond 1000
   (10000LADYS, 100000SHIB, 1000000MOG, 10000000AIDOGE, 1000000000BONK, 1MBABYDOGE, etc.)
2. Zero false-positive exemption preservation (1INCH, 0G, 10SET, KAVA, KAS, BTC).
3. Bidirectional alias resolution across spot and futures venues.
4. Scale-accurate live price lookups across MultiHorizonDataLoader and CryptoDataLoader (test.py).
5. Dynamic orderbook depth scaling and turnover conservation.
6. Orderbook imbalance alias failover.
7. Funding rate alias resolution.
"""

import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np

from app.engine.config import (
    CONTRACT_MULTIPLIER_PREFIXES,
    strip_contract_multiplier,
    resolve_symbol_aliases,
    is_meme_coin
)
from app.engine.scanner.data_loader import MultiHorizonDataLoader
from test import CryptoDataLoader


class TestExchangeTickerNamingVariations(unittest.TestCase):
    """
    Authoritative test suite for non-standard contract multipliers beyond 1000
    and cross-exchange ticker alias resolution.
    """

    def setUp(self):
        self.scanner_loader = MultiHorizonDataLoader()
        self.crypto_loader = CryptoDataLoader()

    def test_strip_contract_multiplier_all_tiers_beyond_1000(self):
        """
        Verifies that strip_contract_multiplier dynamically identifies and scales
        non-standard contract multipliers beyond 1000 (10^4, 10^5, 10^6, 10^7, 10^8, 10^9, 10^12, 10^14).
        """
        cases = [
            # 10^4 (10 Thousand)
            ("10000LADYS", "LADYS", 10_000.0),
            ("10000SATS", "SATS", 10_000.0),
            ("10KLADYS", "LADYS", 10_000.0),
            # 10^5 (100 Thousand)
            ("100000SHIB", "SHIB", 100_000.0),
            ("100KSHIB", "SHIB", 100_000.0),
            # 10^6 (1 Million)
            ("1000000MOG", "MOG", 1_000_000.0),
            ("1000000PEIPEI", "PEIPEI", 1_000_000.0),
            ("1000000CHEEMS", "CHEEMS", 1_000_000.0),
            ("1MBABYDOGE", "BABYDOGE", 1_000_000.0),
            ("1MMOG", "MOG", 1_000_000.0),
            # 10^7 (10 Million)
            ("10000000AIDOGE", "AIDOGE", 10_000_000.0),
            ("10MAIDOGE", "AIDOGE", 10_000_000.0),
            # 10^8 (100 Million)
            ("100000000TOKEN", "TOKEN", 100_000_000.0),
            ("100MTOKEN", "TOKEN", 100_000_000.0),
            # 10^9 (1 Billion)
            ("1000000000BONK", "BONK", 1_000_000_000.0),
            ("1BBONK", "BONK", 1_000_000_000.0),
            # 10^12 (1 Trillion)
            ("1000000000000TOKEN", "TOKEN", 1_000_000_000_000.0),
            ("1TTOKEN", "TOKEN", 1_000_000_000_000.0),
            # 10^14 (100 Trillion)
            ("100000000000000TOKEN", "TOKEN", 100_000_000_000_000.0),
            ("100TTOKEN", "TOKEN", 100_000_000_000_000.0),
            # Baseline 1000
            ("1000PEPE", "PEPE", 1_000.0),
            ("1000BONK", "BONK", 1_000.0),
            ("1KPEPE", "PEPE", 1_000.0),
        ]
        for sym, expected_base, expected_mult in cases:
            base, mult = strip_contract_multiplier(sym)
            self.assertEqual(base, expected_base, f"Failed base extraction for {sym}")
            self.assertEqual(mult, expected_mult, f"Failed multiplier extraction for {sym}")

    def test_strip_contract_multiplier_formatting_variations(self):
        """
        Verifies multiplier stripping across all exchange syntax conventions:
        slashed, unslashed, colon perps, underscores, and dashes.
        """
        cases = [
            ("1000000MOG/USDT", "MOG", 1_000_000.0),
            ("1000000MOGUSDT", "MOG", 1_000_000.0),
            ("1000000MOG/USDT:USDT", "MOG", 1_000_000.0),
            ("1000000MOG:USDT", "MOG", 1_000_000.0),
            ("1000000MOG_USDT", "MOG", 1_000_000.0),
            ("1000000_MOG_USDT", "MOG", 1_000_000.0),
            ("1000000-MOG-USDT", "MOG", 1_000_000.0),
            ("1000000MOG-USDT", "MOG", 1_000_000.0),
            ("1000000MOG-USDT-SWAP", "MOG", 1_000_000.0),
            ("10000LADYS/USDT", "LADYS", 10_000.0),
            ("10000LADYS:USDT", "LADYS", 10_000.0),
            ("100000SHIB-USDT-SWAP", "SHIB", 100_000.0),
            ("1MBABYDOGE/USDT:USDT", "BABYDOGE", 1_000_000.0),
        ]
        for sym, expected_base, expected_mult in cases:
            base, mult = strip_contract_multiplier(sym)
            self.assertEqual(base, expected_base, f"Failed base extraction for {sym}")
            self.assertEqual(mult, expected_mult, f"Failed multiplier extraction for {sym}")

    def test_strip_contract_multiplier_zero_false_positives(self):
        """
        Verifies that native assets starting with digits or letters resembling
        prefixes are NEVER false-positively stripped.
        """
        exemptions = [
            ("1INCH/USDT", "1INCH", 1.0),
            ("1INCHUSDT", "1INCH", 1.0),
            ("0G/USDT", "0G", 1.0),
            ("0GUSDT", "0G", 1.0),
            ("10SET/USDT", "10SET", 1.0),
            ("10SETUSDT", "10SET", 1.0),
            ("KAVA/USDT", "KAVA", 1.0),
            ("KAS/USDT", "KAS", 1.0),
            ("KDA/USDT", "KDA", 1.0),
            ("KLAY/USDT", "KLAY", 1.0),
            ("BTC/USDT", "BTC", 1.0),
            ("ETHUSDT", "ETH", 1.0),
            ("SOL/USDT", "SOL", 1.0),
        ]
        for sym, expected_base, expected_mult in exemptions:
            base, mult = strip_contract_multiplier(sym)
            self.assertEqual(base, expected_base, f"False-positive detected for {sym}")
            self.assertEqual(mult, expected_mult, f"Incorrect multiplier for {sym}")

    def test_resolve_symbol_aliases_bidirectional(self):
        """
        Verifies bidirectional alias generation between spot and futures formats:
        - Futures 1000000MOG/USDT includes spot MOG/USDT and MOGUSDT.
        - Spot MOG/USDT includes futures 1000000MOGUSDT and 1000000MOG/USDT.
        - 10000LADYS/USDT includes LADYS/USDT and LADYSUSDT.
        """
        # Futures -> Spot
        mog_aliases = resolve_symbol_aliases("1000000MOG/USDT")
        self.assertIn("1000000MOG/USDT", mog_aliases)
        self.assertIn("1000000MOGUSDT", mog_aliases)
        self.assertIn("MOG/USDT", mog_aliases)
        self.assertIn("MOGUSDT", mog_aliases)
        self.assertIn("1000000MOG/USDT:USDT", mog_aliases)
        self.assertIn("MOG/USDT:USDT", mog_aliases)

        # Spot -> Futures
        spot_mog_aliases = resolve_symbol_aliases("MOG/USDT")
        self.assertIn("MOG/USDT", spot_mog_aliases)
        self.assertIn("MOGUSDT", spot_mog_aliases)
        self.assertIn("1000000MOG/USDT", spot_mog_aliases)
        self.assertIn("1000000MOGUSDT", spot_mog_aliases)

        # 10000LADYS
        ladys_aliases = resolve_symbol_aliases("10000LADYS/USDT")
        self.assertIn("10000LADYS/USDT", ladys_aliases)
        self.assertIn("10000LADYSUSDT", ladys_aliases)
        self.assertIn("LADYS/USDT", ladys_aliases)
        self.assertIn("LADYSUSDT", ladys_aliases)

        # 1MBABYDOGE
        baby_aliases = resolve_symbol_aliases("1MBABYDOGE/USDT")
        self.assertIn("1MBABYDOGE/USDT", baby_aliases)
        self.assertIn("BABYDOGE/USDT", baby_aliases)
        self.assertIn("BABYDOGEUSDT", baby_aliases)

        # Exempt coin preserves original identity without artificial prefixes
        inch_aliases = resolve_symbol_aliases("1INCH/USDT")
        self.assertIn("1INCH/USDT", inch_aliases)
        self.assertIn("1INCHUSDT", inch_aliases)
        self.assertNotIn("10000001INCH/USDT", inch_aliases)

    def test_price_lookup_with_multiplier_cross_loader_parity(self):
        """
        Verifies that both MultiHorizonDataLoader and CryptoDataLoader (test.py)
        correctly scale prices using the ratio (target_mult / alias_mult):
        - Spot -> Futures Multiplier: 1000000MOG price = MOG spot * 10^6
        - Futures Multiplier -> Spot: MOG spot = 1000000MOG price / 10^6
        - Cross-Multiplier: 100000SHIB price = 1000SHIB * 100
        - 10000LADYS price = LADYS spot * 10^4
        """
        tickers = {
            "MOGUSDT": 0.000002,           # Spot MOG
            "1000000MOGUSDT": 2.0,         # Futures 1000000MOG
            "LADYSUSDT": 0.00000005,       # Spot LADYS
            "1000SHIBUSDT": 0.02,          # 1000SHIB
            "1INCHUSDT": 0.40,             # 1INCH (exempt)
        }

        for loader in [self.scanner_loader, self.crypto_loader]:
            # 1. 1000000MOG derived from spot MOG (0.000002 * 10^6 = 2.0)
            mock_spot_only = {"MOGUSDT": 0.000002}
            p, key = loader._lookup_price_with_multiplier("1000000MOG/USDT", mock_spot_only)
            self.assertAlmostEqual(p, 2.0, places=6)
            self.assertEqual(key, "MOGUSDT")

            # 2. Spot MOG derived from futures 1000000MOG (2.0 / 10^6 = 0.000002)
            mock_futures_only = {"1000000MOGUSDT": 2.0}
            p_spot, key_spot = loader._lookup_price_with_multiplier("MOG/USDT", mock_futures_only)
            self.assertAlmostEqual(p_spot, 0.000002, places=10)
            self.assertEqual(key_spot, "1000000MOGUSDT")

            # 3. 10000LADYS derived from spot LADYS (0.00000005 * 10^4 = 0.0005)
            mock_ladys = {"LADYSUSDT": 0.00000005}
            p_ladys, key_ladys = loader._lookup_price_with_multiplier("10000LADYS/USDT", mock_ladys)
            self.assertAlmostEqual(p_ladys, 0.0005, places=8)
            self.assertEqual(key_ladys, "LADYSUSDT")

            # 4. Cross-multiplier: 100000SHIB derived from 1000SHIB (0.02 * (100000 / 1000) = 2.0)
            mock_shib = {"1000SHIBUSDT": 0.02}
            p_shib, key_shib = loader._lookup_price_with_multiplier("100000SHIB/USDT", mock_shib)
            self.assertAlmostEqual(p_shib, 2.0, places=6)
            self.assertEqual(key_shib, "1000SHIBUSDT")

            # 5. Exact match takes precedence
            mock_exact = {"1000000MOGUSDT": 2.15, "MOGUSDT": 0.000002}
            p_exact, key_exact = loader._lookup_price_with_multiplier("1000000MOG/USDT", mock_exact)
            self.assertAlmostEqual(p_exact, 2.15, places=6)

            # 6. Exempt native asset unchanged
            mock_inch = {"1INCHUSDT": 0.40}
            p_inch, key_inch = loader._lookup_price_with_multiplier("1INCH/USDT", mock_inch)
            self.assertAlmostEqual(p_inch, 0.40, places=6)

    def test_crypto_data_loader_get_live_price_and_freshness(self):
        """
        Verifies that CryptoDataLoader.get_live_price and get_live_price_with_freshness
        in test.py use alias resolution and multiplier scaling.
        """
        mock_tickers = {"MOGUSDT": 0.000002}
        with patch.object(self.crypto_loader, "fetch_all_tickers", return_value=mock_tickers):
            p = self.crypto_loader.get_live_price("1000000MOG/USDT")
            self.assertAlmostEqual(p, 2.0, places=6)

            price, is_fresh, age = self.crypto_loader.get_live_price_with_freshness("1000000MOG/USDT")
            self.assertAlmostEqual(price, 2.0, places=6)
            self.assertTrue(is_fresh)
            self.assertGreaterEqual(age, 0.0)

    def test_crypto_data_loader_fetch_orderbook_imbalance_alias_fallback(self):
        """
        Verifies that CryptoDataLoader.fetch_orderbook_imbalance tries alias symbols
        when the primary futures ticker name is not listed on spot depth.
        """
        def mock_get(url, *args, **kwargs):
            resp = MagicMock()
            params = kwargs.get("params") or {}
            sym = params.get("symbol")
            if not sym and "symbol=" in url:
                sym = url.split("symbol=")[1].split("&")[0]
            if sym == "MOGUSDT":
                resp.status_code = 200
                resp.json.return_value = {
                    "bids": [["0.000002", "3000000.0"]],
                    "asks": [["0.0000021", "1000000.0"]]
                }
            else:
                resp.status_code = 400
                resp.json.return_value = {"code": -1121, "msg": "Invalid symbol."}
            return resp

        with patch.object(self.crypto_loader.session, "get", side_effect=mock_get):
            imbalance = self.crypto_loader.fetch_orderbook_imbalance("1000000MOG/USDT")
            # (3M - 1M) / (3M + 1M) = 2M / 4M = +0.50
            self.assertAlmostEqual(imbalance, 0.50, places=2)

    def test_funding_rate_alias_lookup(self):
        """
        Verifies that funding rates are resolved bidirectionally across aliases
        in both MultiHorizonDataLoader and CryptoDataLoader.
        """
        # 1. MultiHorizonDataLoader
        self.scanner_loader._funding_cache["1000000MOGUSDT"] = 0.00045
        fr_scanner = self.scanner_loader.get_funding_rate("MOG/USDT")
        self.assertAlmostEqual(fr_scanner, 0.00045, places=6)

        # 2. CryptoDataLoader
        self.crypto_loader._funding_cache["1000000MOGUSDT"] = 0.00060
        funding_info = self.crypto_loader.fetch_funding_rate_and_oi("MOG/USDT")
        self.assertAlmostEqual(funding_info["funding_rate"], 0.00060, places=6)
        self.assertEqual(funding_info["regime"], "❄️ LONG SQUEEZE")

    def test_orderbook_depth_scaling_mathematical_conservation(self):
        """
        Verifies that fetch_top5_depth in MultiHorizonDataLoader scales bid/ask prices
        by ratio and quantities by 1/ratio, mathematically conserving total dollar liquidity.
        """
        mock_raw_depth = {
            "symbol": "MOGUSDT",
            "bids": [[0.000002, 5_000_000.0]],   # 5M tokens at $0.000002 = $10.0 depth
            "asks": [[0.0000022, 5_000_000.0]],  # 5M tokens at $0.0000022 = $11.0 depth
            "timestamp": 1234567.0,
            "venue": "binance"
        }

        def mock_fetch(raw_sym):
            if raw_sym == "MOGUSDT":
                return mock_raw_depth
            return None

        with patch.object(self.scanner_loader, "_fetch_raw_depth_from_exchanges", side_effect=mock_fetch):
            depth = self.scanner_loader.fetch_top5_depth("1000000MOG/USDT")
            self.assertIsNotNone(depth)
            scaled_bid_price = depth["bids"][0][0]
            scaled_bid_qty = depth["bids"][0][1]

            # Price scales by 10^6: 0.000002 * 10^6 = 2.0
            self.assertAlmostEqual(scaled_bid_price, 2.0, places=6)
            # Quantity scales by 10^-6: 5M / 10^6 = 5.0
            self.assertAlmostEqual(scaled_bid_qty, 5.0, places=6)
            # Total dollar depth is strictly conserved: 2.0 * 5.0 = 10.0
            self.assertAlmostEqual(scaled_bid_price * scaled_bid_qty,
                                   mock_raw_depth["bids"][0][0] * mock_raw_depth["bids"][0][1], places=6)

    def test_is_meme_coin_recognizes_future_multiplier_exotics(self):
        """
        Verifies that is_meme_coin correctly identifies meme coins regardless of
        contract multiplier prefixes or delimiter variations.
        """
        self.assertTrue(is_meme_coin("1000000MOG/USDT"))
        self.assertTrue(is_meme_coin("1000000_MOG_USDT"))
        self.assertTrue(is_meme_coin("10000LADYS/USDT"))
        self.assertTrue(is_meme_coin("100000SHIB/USDT"))
        self.assertTrue(is_meme_coin("1000000000BONK/USDT"))
        self.assertTrue(is_meme_coin("1MBABYDOGE/USDT"))
        self.assertTrue(is_meme_coin("1000PEPE/USDT"))
        # Non-meme coins remain False
        self.assertFalse(is_meme_coin("BTC/USDT"))
        self.assertFalse(is_meme_coin("ETH/USDT"))
        self.assertFalse(is_meme_coin("SOL/USDT"))
        self.assertFalse(is_meme_coin("1INCH/USDT"))

    def test_exotic_delisted_tokens_non_latin_and_non_standard_quotes(self):
        """
        Verifies that exotic delisted tokens with novel non-Latin delimiters
        or non-standard quote currencies outside {"USDT", "USDC", "BUSD", "USD", "EUR", "BTC", "ETH"}
        strictly fail closed to the unstripped symbol with multiplier 1.0, and
        resolve_symbol_aliases fails closed to [symbol] without artificial alias expansion.
        """
        # 1. Non-Latin delimiters & characters
        non_latin_cases = [
            "1000★PEPE/USDT",
            "1000・PEPE/USDT",
            "1000PEPE／USDT",
            "1000PEPE：USDT",
            "1000PEPE〜USDT",
            "1000PEPE※USDT",
            "1000PEPE_元",
            "１０００ＰＥＰＥ/USDT",
        ]
        for sym in non_latin_cases:
            base, mult = strip_contract_multiplier(sym)
            self.assertEqual(base, sym, f"Expected unstripped base for non-Latin symbol {sym}")
            self.assertEqual(mult, 1.0, f"Expected multiplier 1.0 for non-Latin symbol {sym}")

            aliases = resolve_symbol_aliases(sym)
            self.assertEqual(aliases, [sym], f"Expected single unstripped alias for non-Latin symbol {sym}")

        # 2. Non-standard quote currencies outside {"USDT", "USDC", "BUSD", "USD", "EUR", "BTC", "ETH"}
        non_standard_quotes = [
            "1000PEPE/TRY",
            "1000000MOG/FDUSD",
            "10000LADYS:KRW",
            "1000BONK-BRL",
            "1000PEPE_TRY",
            "1000PEPETRY",
            "1000000MOGFDUSD",
            "1000PEPE/BRL",
            "1000000MOG:JPY",
        ]
        for sym in non_standard_quotes:
            base, mult = strip_contract_multiplier(sym)
            self.assertEqual(base, sym, f"Expected unstripped base for non-standard quote {sym}")
            self.assertEqual(mult, 1.0, f"Expected multiplier 1.0 for non-standard quote {sym}")

            aliases = resolve_symbol_aliases(sym)
            self.assertEqual(aliases, [sym], f"Expected single unstripped alias for non-standard quote {sym}")

        # 3. Standard quote currencies & standard pairs continue normal stripping and alias resolution
        standard_cases = [
            ("1000000MOG/USDT", "MOG", 1_000_000.0),
            ("10000LADYS/USDT", "LADYS", 10_000.0),
            ("1000PEPE/USDT", "PEPE", 1_000.0),
            ("1MBABYDOGE/USDT", "BABYDOGE", 1_000_000.0),
            ("1000BONK/EUR", "BONK", 1_000.0),
            ("1000PEPE/BTC", "PEPE", 1_000.0),
            ("1INCH/USDT", "1INCH", 1.0),
            ("0G/USDT", "0G", 1.0),
            ("10SET/USDT", "10SET", 1.0),
        ]
        for sym, expected_base, expected_mult in standard_cases:
            base, mult = strip_contract_multiplier(sym)
            self.assertEqual(base, expected_base, f"Failed standard base extraction for {sym}")
            self.assertEqual(mult, expected_mult, f"Failed standard multiplier extraction for {sym}")

            aliases = resolve_symbol_aliases(sym)
            self.assertIn(sym, aliases)
            self.assertGreater(len(aliases), 1)


if __name__ == "__main__":
    unittest.main()
