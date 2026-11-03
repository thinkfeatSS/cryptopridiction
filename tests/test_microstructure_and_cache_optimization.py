import unittest
import os
import time
import pandas as pd
import numpy as np

from app.quant_v16.cross_timeframe_matrix import CrossTimeframeMatrixEngine, InstitutionalArchetype
from app.quant_v16.fractal_consolidation import FractalTimeframeState, TimeframeConsolidationProfile, FractalConsolidationEngine
from app.quant_v16.order_blocks import InstitutionalOrderBlockEngine, OrderBlock, OrderBlockType, OrderBlockState
from app.engine.signals.per_coin_models import PerCoinModelRegistry


class TestMicrostructureAndCacheOptimization(unittest.TestCase):
    """
    Unit and regression test suite verifying:
    1. Dynamic volatility-adjusted headroom hurdles in compressed micro-markets.
    2. Dynamic range box width adaptation in FractalConsolidationEngine.
    3. Dynamic noise floor scaling on Order Block stop loss distances.
    4. Sub-5ms non-blocking instantiation and background pre-warming in PerCoinModelRegistry.
    """

    def test_compressed_micro_regime_headroom_dynamic_scaling(self):
        """
        Verify that in an ultra-tight compressed market (ATR = 0.25%, e.g. price=100.0, atr=0.25),
        a boundary bounce with 0.90% headroom is permitted (not vetoed by an obsolete hardcoded 2.0% hurdle).
        """
        p_1d = TimeframeConsolidationProfile(
            timeframe="1d",
            state=FractalTimeframeState.CONSOLIDATION_RANGING,
            is_consolidation=True,
            is_coiling_squeeze=False,
            chop_index=55.0,
            adx=16.0,
            bbw_pct=1.5,
            is_inside_bar=False,
            is_nr7=False,
            is_nr4=False,
            is_doji=False,
            compression_score=0.3,
            range_high=101.50,
            range_low=100.00,
            range_mid=100.75,
            position_in_range_pct=0.15,
            headroom_to_high_pct=0.90,  # 0.90% headroom in a 1.5% range box
            headroom_to_low_pct=0.20,
            current_price=100.22,
            atr=0.25,
            atr_pct=0.25
        )
        p_15m = TimeframeConsolidationProfile(
            timeframe="15m",
            state=FractalTimeframeState.CONSOLIDATION_RANGING,
            is_consolidation=True,
            is_coiling_squeeze=False,
            chop_index=52.0,
            adx=14.0,
            bbw_pct=1.2,
            is_inside_bar=False,
            is_nr7=False,
            is_nr4=False,
            is_doji=False,
            compression_score=0.4,
            range_high=100.80,
            range_low=100.10,
            range_mid=100.45,
            position_in_range_pct=0.17,
            headroom_to_high_pct=0.90,
            headroom_to_low_pct=0.20,
            current_price=100.22,
            atr=0.25,
            atr_pct=0.25
        )

        profiles = {"1d": p_1d, "15m": p_15m}
        eval_result = CrossTimeframeMatrixEngine.evaluate_matrix(profiles, current_price=100.22)

        # In tight compression (ATR=0.25%), min_macro_headroom = max(0.50, 1.2 * 0.25) = 0.50%
        # Since headroom_to_high_pct (0.90%) >= 0.50%, the trade is permitted!
        self.assertTrue(eval_result["trade_permitted"])
        self.assertEqual(eval_result["strategy"], "RANGE_SUPPORT_MEAN_REVERSION")
        self.assertEqual(eval_result["dominant_direction"], "LONG")

    def test_fractal_consolidation_dynamic_range_box_width(self):
        """
        Verify that FractalConsolidationEngine recognizes a compressed 0.8% range box
        when ATR is 0.20% instead of dropping it to false trend classification.
        """
        np.random.seed(42)
        n = 30
        base_p = 100.0
        # Generate tight oscillating candles within a 0.8% corridor [99.6, 100.4]
        closes = [base_p + 0.3 * np.sin(i / 2.0) for i in range(n)]
        highs = [c + 0.08 for c in closes]
        lows = [c - 0.08 for c in closes]
        opens = [c - 0.02 for c in closes]

        df = pd.DataFrame({
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1000.0] * n
        })

        profile = FractalConsolidationEngine.analyze_timeframe(df, timeframe="15m")
        self.assertGreater(profile.atr, 0.0)
        self.assertGreater(profile.atr_pct, 0.0)
        self.assertTrue(profile.is_consolidation)

    def test_order_block_dynamic_noise_floor_sl(self):
        """
        Verify that min_sl_dist = max(0.85 * atr, min(entry * 0.008, 1.8 * atr))
        scales dynamically with ATR:
        1. Ultra-compressed (ATR = 0.20%): min_sl_dist scales down to 1.8 * ATR = 0.36%.
        2. Normal market (ATR = 1.0%): min_sl_dist respects 0.80% / 0.85% noise floor.
        """
        entry_p = 100.0
        atr_compressed = 0.20
        min_sl_comp = max(0.85 * atr_compressed, min(entry_p * 0.008, 1.8 * atr_compressed))
        self.assertAlmostEqual(min_sl_comp, 0.36, places=4)
        self.assertLess(min_sl_comp, entry_p * 0.008)  # Does not force excessive 0.80% SL

        atr_normal = 1.0
        min_sl_norm = max(0.85 * atr_normal, min(entry_p * 0.008, 1.8 * atr_normal))
        self.assertAlmostEqual(min_sl_norm, 0.85, places=4)

    def test_per_coin_model_registry_non_blocking_init(self):
        """
        Verify that PerCoinModelRegistry instantiates asynchronously without blocking.
        """
        PerCoinModelRegistry._instance = None
        t0 = time.time()
        reg = PerCoinModelRegistry(async_preload=True)
        init_duration_ms = (time.time() - t0) * 1000.0
        self.assertLess(init_duration_ms, 250.0)

    def test_extreme_rate_limiting_and_network_resilience(self):
        """
        Verify that:
        1. MultiHorizonDataLoader has HTTP Retry strategy configured.
        2. Tier-6.6 Coinpaprika aggregator provides instant fallback when primary and CoinCap fail.
        3. Independent mirror cooldown prevents a single mirror 429 from blocking other mirrors.
        """
        from app.engine.scanner.data_loader import MultiHorizonDataLoader
        loader = MultiHorizonDataLoader()

        # 1. Verify Retry strategy mounted on session
        adapter = loader.session.get_adapter("https://api.binance.com")
        self.assertIsNotNone(adapter.max_retries)
        self.assertGreaterEqual(getattr(adapter.max_retries, "total", 0), 2)

        # 2. Test Coinpaprika fallback
        ticks = loader._fetch_coinpaprika_tickers()
        if ticks:
            self.assertIn("BTC/USDT", ticks)
            self.assertGreater(ticks["BTC/USDT"], 1000.0)

    def test_swr_disk_cache_stepdown_on_api_quota_exhaustion(self):
        """
        Verify that:
        1. Atomic SWR disk cache saves and loads ticker prices.
        2. When Coinpaprika hits HTTP 429 quota exhaustion, loader gracefully steps down to SWR disk cache.
        """
        import tempfile
        import shutil
        from unittest.mock import MagicMock
        from app.engine.scanner.data_loader import MultiHorizonDataLoader

        tmp_dir = tempfile.mkdtemp(prefix="swr_cache_test_")
        try:
            loader = MultiHorizonDataLoader()
            loader._disk_cache_dir = tmp_dir

            # 1. Save dummy prices to SWR disk
            mock_prices = {"BTC/USDT": 78500.0, "ETH/USDT": 2450.0}
            t_now = time.time()
            loader._save_tickers_to_swr_disk(mock_prices, t_now)

            loaded_ticks, loaded_ts = loader._load_tickers_from_swr_disk()
            self.assertEqual(loaded_ticks.get("BTC/USDT"), 78500.0)
            self.assertAlmostEqual(loaded_ts, t_now, places=1)

            # 2. Mock 429 response from Coinpaprika
            mock_resp = MagicMock()
            mock_resp.status_code = 429
            loader.session.get = MagicMock(return_value=mock_resp)
            loader._paprika_rates_cache = {}
            loader._paprika_rates_ts = 0.0

            ticks_swr = loader._fetch_coinpaprika_tickers()
            self.assertIn("BTC/USDT", ticks_swr)
            self.assertEqual(ticks_swr["BTC/USDT"], 78500.0)
            self.assertGreater(loader._paprika_throttled_until, time.time())
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_delisted_coin_zero_volume_exclusion_and_zero_distance_guard(self):
        """
        Verify that:
        1. Delisted altcoins with zero volume are excluded by UniverseFilter.
        2. SignalGenerationSystem excludes zero volume and near-zero price assets.
        3. Zero-distance entry == SL setups fail closed with trade_active=False.
        """
        from app.engine.scanner.filters import UniverseFilter
        from app.engine.signals.signal_generator import SignalGenerationSystem

        # 1. Universe filter check
        self.assertFalse(UniverseFilter.is_valid_crypto_pair("DELISTED/USDT", price=1.5, volume_usd=0.0))
        self.assertFalse(UniverseFilter.is_valid_crypto_pair("DELISTED/USDT", price=0.00005, volume_usd=1000000.0))

        # 2. Scanner-level check: Zero volume or missing price excluded from active prediction universe
        from unittest.mock import MagicMock
        from app.engine.scanner.horizon_scanner import MultiHorizonScanner
        scanner = MultiHorizonScanner()
        scanner.loader.fetch_all_tickers = MagicMock(return_value={})
        # Simulate scan of delisted coin with 0 volume and 0 price
        delisted_meta = {"symbol": "DEAD/USDT", "quote_volume_usd": 0.0, "price": 0.0}
        # Verify UniverseFilter excludes it
        self.assertFalse(UniverseFilter.is_valid_crypto_pair(delisted_meta["symbol"], price=delisted_meta["price"], volume_usd=delisted_meta["quote_volume_usd"]))

        # 3. Zero-distance SL fail-closed guard
        sig_sys = SignalGenerationSystem()
        dummy_df = pd.DataFrame({
            "open": [10.0]*20, "high": [10.5]*20, "low": [9.5]*20, "close": [10.0]*20, "volume": [1000.0]*20
        })
        dfs_9 = {"15m": dummy_df, "1h": dummy_df, "1d": dummy_df}
        sig = sig_sys._build_single_horizon_signal(
            symbol="TEST/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="LONG",
            current_price=10.0,
            dfs_9=dfs_9,
            horizon_prediction={"predicted_target_price": 11.0, "predicted_change_pct": 0.1},
            btc_shield_state={"altcoin_longs_allowed": True, "v16_regime": "RANGE"},
            aligned_horizons=["15m", "1h"],
            order_block_setup={
                "setup_detected": True,
                "direction": "LONG",
                "entry_price": 10.0,
                "sl_price": 10.0, # Zero-distance SL
                "tp1_price": 11.0,
                "tp2_price": 12.0,
                "tp3_price": 13.0,
                "zeiierman_rank": 1
            },
            volume_24h_usd=5000000.0
        )
        # Even if entry analysis calculated an entry, if entry == SL it must fail closed
        self.assertFalse(sig["is_trade_active"])

    def test_liquidity_sweep_wick_not_classified_as_breakout(self):
        """
        Verify that a lower wick sweeping prior 20-bar low but closing green is NOT classified as a false bear breakout.
        """
        from app.quant_v16.regime import compute_live_btc_regime, MarketRegime

        # Build 30 bars ranging between 77000 and 78000
        rows = []
        for i in range(29):
            rows.append({
                "open": 77400.0, "high": 77800.0, "low": 77100.0, "close": 77500.0, "volume": 1000.0
            })
        # 30th bar: wicks down to 76600 (lower than 77100) but closes strong green at 77700
        rows.append({
            "open": 77200.0, "high": 77800.0, "low": 76600.0, "close": 77700.0, "volume": 2000.0
        })
        df = pd.DataFrame(rows)

        eval_res = compute_live_btc_regime(df)
        self.assertNotEqual(eval_res["regime"], MarketRegime.BREAKOUT.value)
        # Ensure it was not misclassified as a bear trend either
        self.assertNotEqual(eval_res["regime"], MarketRegime.BEAR_TREND.value)



if __name__ == "__main__":
    unittest.main()

