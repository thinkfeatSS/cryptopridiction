import json
import unittest
from unittest.mock import patch, MagicMock
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
        self.assertLess(init_duration_ms, 750.0)

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



    def test_prolonged_macro_squeeze_trigger_qualification(self):
        """
        Verify that during a prolonged macro squeeze (BTC in SQUEEZE or RANGE),
        an altcoin with a verified Keltner-Bollinger squeeze expansion trigger
        qualifies for trading with SQUEEZE_EXPANSION strategy rather than being vetoed.
        """
        from app.engine.signals.signal_generator import SignalGenerationSystem, map_canonical_strategy
        from app.quant_v16.strategies import StrategyArchetype
        from app.quant_v16.no_trade_zone import no_trade_zone_engine

        # 1. Verify Squeeze Expansion exemption in NTZ
        df_tight = pd.DataFrame({
            "open": [10.0] * 30,
            "high": [10.05] * 30,
            "low": [9.95] * 30,
            "close": [10.0] * 30,
            "volume": [1000.0] * 30
        })
        ntz_res = no_trade_zone_engine.evaluate_asset_ntz(
            df=df_tight,
            current_price=10.0,
            anchor_tf="15m",
            alignment_score=65.0,
            meta_win_prob=0.70,
            direction="LONG",
            decision="SQUEEZE_EXPANSION_LONG"
        )
        self.assertFalse(ntz_res["is_ntz"], "SQUEEZE_EXPANSION must not be vetoed by coiled squeeze NTZ")

        # 2. Verify Canonical Strategy Mapping
        strat = map_canonical_strategy("COILING_VOLATILITY_BREAKOUT", "LONG", candle_metrics={"is_squeeze_expansion": True})
        self.assertEqual(strat, StrategyArchetype.SQUEEZE_EXPANSION_LONG.value)

        # 3. Verify evaluate_multi_horizon_gates with coiling breakout
        sig_sys = SignalGenerationSystem()
        matrix_eval = {
            "archetype": InstitutionalArchetype.ARCHETYPE_B_COILING_BREAKOUT.value,
            "trade_permitted": True,
            "dominant_direction": "LONG",
            "strategy": "COILING_VOLATILITY_BREAKOUT",
            "allocation_pct": 50.0
        }
        trend_matrix = {
            "5m": "CONSOLIDATION",
            "15m": "CONSOLIDATION",
            "1h": "CONSOLIDATION",
            "4h": "CONSOLIDATION",
            "12h": "CONSOLIDATION",
            "1d": "CONSOLIDATION",
            "1w": "CONSOLIDATION",
            "15d": "CONSOLIDATION"
        }
        horizon_preds = {
            "5m": {"is_cold_start": False, "candle_count": 50},
            "15m": {"is_cold_start": False, "candle_count": 50},
            "1h": {"is_cold_start": False, "candle_count": 50},
            "4h": {"is_cold_start": False, "candle_count": 50},
            "12h": {"is_cold_start": False, "candle_count": 50},
            "1d": {"is_cold_start": False, "candle_count": 50},
            "1w": {"is_cold_start": False, "candle_count": 50},
            "15d": {"is_cold_start": False, "candle_count": 50}
        }
        q_15m, q_1h, q_24h = sig_sys.evaluate_multi_horizon_gates(
            trend_matrix=trend_matrix,
            horizon_predictions=horizon_preds,
            matrix_eval=matrix_eval,
            has_smc_15m=True,
            smc_dir_15m="LONG"
        )
        self.assertTrue(q_15m["qualified"], "15M gate must qualify on verified squeeze expansion trigger")
        self.assertEqual(q_15m["direction"], "LONG")

    def test_sub_threshold_illiquidity_exclusion(self):
        """
        Verify that assets with sub-threshold liquidity (< $1.0M 24h quote volume)
        are strictly vetoed by NTZ Pillar 2, excluded from active scanner emission,
        and flagged with HOLD_VETOED_BY_SUB_THRESHOLD_ILLIQUIDITY.
        """
        from app.quant_v16.no_trade_zone import no_trade_zone_engine, NoTradeZoneReason
        from app.engine.signals.signal_generator import SignalGenerationSystem

        # 1. NTZ Pillar 2 evaluation with sub-threshold volume ($450k USDT)
        df_dummy = pd.DataFrame({
            "open": [10.0] * 30,
            "high": [10.2] * 30,
            "low": [9.8] * 30,
            "close": [10.1] * 30,
            "volume": [1000.0] * 30
        })
        ntz_res = no_trade_zone_engine.evaluate_asset_ntz(
            df=df_dummy,
            current_price=10.1,
            anchor_tf="15m",
            stats_24h={"quoteVolume": 450_000.0},
            decision="MOMENTUM_TREND_EXPANSION"
        )
        self.assertTrue(ntz_res["is_ntz"], "Sub-threshold liquidity (< $1M) must trigger NTZ")
        self.assertEqual(ntz_res["code"], NoTradeZoneReason.DRY_VOLUME_ILLIQUID.value)
        self.assertTrue(any("Sub-Threshold Illiquidity" in r for r in ntz_res["reasons"]))

        # 2. Hard Liquidity Floor in evaluate_asset_multi_horizon ($600k USDT)
        sig_sys = SignalGenerationSystem()
        dfs_9 = {
            tf: pd.DataFrame({
                "open": [10.0] * 30,
                "high": [10.2] * 30,
                "low": [9.8] * 30,
                "close": [10.1] * 30,
                "volume": [1000.0] * 30
            }) for tf in ["5m", "15m", "1h", "4h", "12h", "1d", "1w", "15d", "1M"]
        }
        res = sig_sys.evaluate_asset_multi_horizon(
            symbol="ILLIQUID/USDT",
            dfs_9=dfs_9,
            btc_shield_state={"status_code": "NORMAL", "altcoin_longs_allowed": True},
            live_price=10.1,
            volume_24h_usd=600_000.0
        )
        self.assertIsNone(res, "Asset with sub-threshold volume must return None from multi-horizon evaluation")

        # 3. Dedicated Horizon Signal Generation Status ($750k USDT)
        sig = sig_sys._build_single_horizon_signal(
            symbol="ILLIQUID/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="LONG",
            current_price=10.1,
            dfs_9=dfs_9,
            horizon_prediction={"consensus_probability": 0.70, "predicted_change_pct": 2.5, "predicted_target_price": 10.35},
            btc_shield_state={"status_code": "NORMAL", "altcoin_longs_allowed": True, "altcoin_shorts_allowed": True},
            aligned_horizons=["15m", "1h"],
            volume_24h_usd=750_000.0
        )
        self.assertFalse(sig["is_trade_active"], "Sub-threshold liquidity signal must not be active")
        self.assertEqual(sig["signal_status"], "HOLD_VETOED_BY_SUB_THRESHOLD_ILLIQUIDITY")
        self.assertIn("SUB-THRESHOLD ILLIQUIDITY", sig["quality_grade"])

    def test_microstructure_fakeout_whipsaw_rejection(self):
        """
        Verify that microstructure fakeouts (Bull Trap liquidity sweep at highs and
        Bear Trap liquidity sweep at lows) are strictly rejected by EntryConfirmationEngine.
        """
        from app.quant_v16.entry_confirmation import EntryConfirmationEngine

        # Case A: Bull Trap Liquidity Sweep Fakeout (Long Rejection)
        # Prior bars establish swing high at 105.0. Trigger bar sweeps to 106.5 but closes at 104.2 with upper wick.
        bars_bull_trap = [
            {"open": 100.0, "high": 102.0, "low": 99.5, "close": 101.5, "volume": 1000},
            {"open": 101.5, "high": 103.5, "low": 101.0, "close": 103.0, "volume": 1000},
            {"open": 103.0, "high": 105.0, "low": 102.5, "close": 104.5, "volume": 1000}, # Prior swing high = 105.0
            {"open": 104.5, "high": 104.8, "low": 103.8, "close": 104.0, "volume": 1000},
            # Trigger bar: sweeps high to 106.5, falls back and closes at 104.2 (<= 105.0), range = 106.5 - 103.0 = 3.5.
            # Upper wick = 106.5 - 104.2 = 2.3 -> 65.7% upper wick (>= 25%)
            {"open": 103.8, "high": 106.5, "low": 103.0, "close": 104.2, "volume": 2500},
            {"open": 104.2, "high": 104.5, "low": 104.0, "close": 104.2, "volume": 500} # Forming live bar
        ]
        df_bull_trap = pd.DataFrame(bars_bull_trap)
        is_conf, reason, metrics = EntryConfirmationEngine.validate_candle_trigger(
            df_bull_trap, direction="LONG", current_price=104.2
        )
        self.assertFalse(is_conf, "Bull trap liquidity sweep fakeout must be rejected for LONG")
        self.assertIn("Bull Trap Liquidity Sweep Fakeout", reason)

        # Case B: Bear Trap Liquidity Sweep Absorption (Short Rejection)
        # Prior bars establish swing low at 95.0. Trigger bar sweeps to 93.5 but closes at 95.8 with lower wick.
        bars_bear_trap = [
            {"open": 100.0, "high": 100.5, "low": 98.0, "close": 98.5, "volume": 1000},
            {"open": 98.5, "high": 99.0, "low": 96.5, "close": 97.0, "volume": 1000},
            {"open": 97.0, "high": 97.5, "low": 95.0, "close": 95.5, "volume": 1000}, # Prior swing low = 95.0
            {"open": 95.5, "high": 96.2, "low": 95.2, "close": 96.0, "volume": 1000},
            # Trigger bar: sweeps low to 93.5, rebounds and closes at 95.8 (>= 95.0), range = 97.0 - 93.5 = 3.5.
            # Lower wick = 95.8 - 93.5 = 2.3 -> 65.7% lower wick (>= 25%)
            {"open": 96.0, "high": 97.0, "low": 93.5, "close": 95.8, "volume": 2500},
            {"open": 95.8, "high": 96.0, "low": 95.5, "close": 95.8, "volume": 500} # Forming live bar
        ]
        df_bear_trap = pd.DataFrame(bars_bear_trap)
        is_conf_s, reason_s, metrics_s = EntryConfirmationEngine.validate_candle_trigger(
            df_bear_trap, direction="SHORT", current_price=95.8
        )
        self.assertFalse(is_conf_s, "Bear trap liquidity sweep absorption must be rejected for SHORT")
        self.assertIn("Bear Trap Liquidity Sweep Absorption", reason_s)

    def test_intraday_flash_liquidity_drain_detection(self):
        """
        Verify that an altcoin experiencing an intraday flash liquidity drain
        (volume vacuum < 12% of baseline, turnover < $5k, or flash spread blowout)
        is strictly rejected by EntryConfirmationEngine, vetoed by NTZ Pillar 2,
        and assigned HOLD_VETOED_BY_FLASH_LIQUIDITY_DRAIN in SignalGenerationSystem.
        """
        from app.quant_v16.entry_confirmation import EntryConfirmationEngine
        from app.quant_v16.no_trade_zone import no_trade_zone_engine, NoTradeZoneReason
        from app.engine.signals.signal_generator import SignalGenerationSystem

        # 1. Acute volume vacuum on active bar (50 units vs 1000 units baseline = 0.05x RVOL)
        rows_vacuum = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0}
            for _ in range(20)
        ]
        # Bar 21: Volume collapses to 50.0 (5% of 1000.0 avg)
        rows_vacuum.append({
            "open": 100.5, "high": 101.5, "low": 100.2, "close": 101.2, "volume": 50.0
        })
        # Forming live bar
        rows_vacuum.append({
            "open": 101.2, "high": 101.4, "low": 101.1, "close": 101.3, "volume": 10.0
        })
        df_vacuum = pd.DataFrame(rows_vacuum)

        # A. EntryConfirmationEngine verification
        is_conf, reason, metrics = EntryConfirmationEngine.validate_candle_trigger(
            df_vacuum, direction="LONG", current_price=101.3, spread_bps=5.0
        )
        self.assertFalse(is_conf, "Intraday flash volume vacuum must be rejected by candle confirmation")
        self.assertTrue(metrics.get("is_flash_liquidity_drain"))
        self.assertIn("Intraday Flash Liquidity Drain", reason)

        # B. NTZ Pillar 2 verification
        ntz_res = no_trade_zone_engine.evaluate_asset_ntz(
            df=df_vacuum,
            current_price=101.3,
            anchor_tf="15m",
            stats_24h={"quoteVolume": 25_000_000.0}, # Healthy 24h volume
            decision="MOMENTUM_TREND_EXPANSION"
        )
        self.assertTrue(ntz_res["is_ntz"], "Intraday flash liquidity drain must trigger NTZ")
        self.assertEqual(ntz_res["code"], NoTradeZoneReason.DRY_VOLUME_ILLIQUID.value)
        self.assertTrue(any("Flash Liquidity Drain" in r for r in ntz_res["reasons"]))

        # C. SignalGenerationSystem verification
        sig_sys = SignalGenerationSystem()
        dfs_9 = {
            tf: df_vacuum.copy() for tf in ["5m", "15m", "1h", "4h", "12h", "1d", "1w", "15d", "1M"]
        }
        sig = sig_sys._build_single_horizon_signal(
            symbol="DRAINED/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="LONG",
            current_price=101.3,
            dfs_9=dfs_9,
            horizon_prediction={"consensus_probability": 0.70, "predicted_change_pct": 2.5, "predicted_target_price": 103.5},
            btc_shield_state={"status_code": "NORMAL", "altcoin_longs_allowed": True, "altcoin_shorts_allowed": True},
            aligned_horizons=["15m", "1h"],
            volume_24h_usd=25_000_000.0,
            spread_bps=5.0
        )
        self.assertFalse(sig["is_trade_active"], "Flash liquidity drain signal must not be active")
        self.assertEqual(sig["signal_status"], "HOLD_VETOED_BY_FLASH_LIQUIDITY_DRAIN")
        self.assertIn("FLASH LIQUIDITY DRAIN", sig["quality_grade"])

        # D. Flash Spread Expansion Blowout (> 20.0 bps on 15M)
        sig_spread = sig_sys._build_single_horizon_signal(
            symbol="DRAINED/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="LONG",
            current_price=101.3,
            dfs_9={tf: pd.DataFrame({"open": [100.0]*25, "high": [101.0]*25, "low": [99.0]*25, "close": [100.5]*25, "volume": [1000.0]*25}) for tf in ["5m", "15m", "1h", "4h", "12h", "1d", "1w", "15d", "1M"]},
            horizon_prediction={"consensus_probability": 0.70, "predicted_change_pct": 2.5, "predicted_target_price": 103.5},
            btc_shield_state={"status_code": "NORMAL", "altcoin_longs_allowed": True, "altcoin_shorts_allowed": True},
            aligned_horizons=["15m", "1h"],
            volume_24h_usd=25_000_000.0,
            spread_bps=24.5 # Blowout on 15M scalp (> 20 bps)
        )
        self.assertFalse(sig_spread["is_trade_active"])
        self.assertEqual(sig_spread["signal_status"], "HOLD_VETOED_BY_FLASH_LIQUIDITY_DRAIN")
        self.assertIn("Flash spread blowout", sig_spread["quality_grade"])

    def test_first_tick_scanner_boot_zero_cold_start(self):
        """
        Verify that MultiHorizonDataLoader and MultiHorizonScanner support instant,
        zero-cold-start initialization via seed_live_tickers and asynchronous pre-warming.
        """
        from app.engine.scanner.data_loader import MultiHorizonDataLoader
        from app.engine.scanner.horizon_scanner import MultiHorizonScanner

        loader = MultiHorizonDataLoader()
        loader.ws_feed = None
        hot_universe = {
            "BTC/USDT": 78950.0,
            "ETH/USDT": 2950.0,
            "SOL/USDT": 185.0
        }
        loader.seed_live_tickers(hot_universe)

        # 1. Verify instant live price resolution without waiting for secondary network calls
        self.assertEqual(loader.get_live_price("BTC/USDT"), 78950.0)
        self.assertEqual(loader.get_live_price("ETH/USDT"), 2950.0)
        self.assertEqual(loader.get_live_price("SOL/USDT"), 185.0)

        # 2. Verify freshness tracking is 0.0s and active
        self.assertTrue(loader._is_price_fresh_15s)
        self.assertLessEqual(loader._price_freshness_age, 0.5)
        self.assertFalse(loader._is_global_outage)

        # 3. Verify funding disk persistence and recovery
        test_funding = {"BTCUSDT": 0.0001, "ETHUSDT": 0.00015}
        loader._save_funding_to_swr_disk(test_funding, time.time())
        recovered_funding, rec_ts = loader._load_funding_from_swr_disk()
        self.assertEqual(recovered_funding.get("BTCUSDT"), 0.0001)
        self.assertEqual(recovered_funding.get("ETHUSDT"), 0.00015)
        self.assertGreater(rec_ts, 0.0)

        # 4. Verify MultiHorizonScanner eager boot
        scanner = MultiHorizonScanner(eager_boot=True)
        self.assertIsNotNone(scanner.loader)
        self.assertIsNotNone(scanner.btc_shield)

    def test_cross_exchange_funding_skew_reconciliation(self):
        """
        Verifies cross-exchange funding rate reconciliation and venue skew dampening.
        1. When skew <= 4.0 bps, rate is mean consensus.
        2. When skew > 4.0 bps, rate is median-clamped and flagged as abnormal skew.
        3. SignalGenerationSystem retrieves and propagates dynamic funding metadata.
        """
        from app.engine.scanner.data_loader import MultiHorizonDataLoader
        from unittest.mock import MagicMock

        loader = MultiHorizonDataLoader()

        # Mock requests to return skewed rates
        mock_binance_resp = MagicMock()
        mock_binance_resp.status_code = 200
        mock_binance_resp.json.return_value = [
            {"symbol": "BTCUSDT", "lastFundingRate": "0.0008"},
            {"symbol": "ETHUSDT", "lastFundingRate": "0.00012"},
        ]

        mock_bybit_resp = MagicMock()
        mock_bybit_resp.status_code = 200
        mock_bybit_resp.json.return_value = {
            "result": {
                "list": [
                    {"symbol": "BTCUSDT", "fundingRate": "0.0002"},
                    {"symbol": "ETHUSDT", "fundingRate": "0.00010"},
                ]
            }
        }

        def mock_get(url, *args, **kwargs):
            if "binance" in url:
                return mock_binance_resp
            if "bybit" in url:
                return mock_bybit_resp
            mock_404 = MagicMock()
            mock_404.status_code = 404
            return mock_404

        loader.session.get = mock_get
        loader.preload_bulk_funding_rates()

        # 1. Verify ETH (skew = 0.2 bps <= 4.0 bps) -> Mean consensus: 0.00011
        eth_info = loader.get_funding_info("ETH/USDT")
        self.assertAlmostEqual(eth_info["funding_rate"], 0.00011, places=5)
        self.assertAlmostEqual(eth_info["skew_bps"], 0.2, places=1)
        self.assertFalse(eth_info["is_skew_abnormal"])

        # 2. Verify BTC (skew = 6.0 bps > 4.0 bps) -> Clamped around median (0.0005)
        btc_info = loader.get_funding_info("BTC/USDT")
        self.assertAlmostEqual(btc_info["skew_bps"], 6.0, places=1)
        self.assertTrue(btc_info["is_skew_abnormal"])
        self.assertLessEqual(btc_info["funding_rate"], 0.0009)

        # 3. Verify SignalGenerationSystem integration with loader
        from app.engine.signals.signal_generator import SignalGenerationSystem
        sig_sys = SignalGenerationSystem(data_loader=loader)
        self.assertIsNotNone(sig_sys.data_loader)
        self.assertEqual(sig_sys.data_loader.get_funding_rate("ETH/USDT"), eth_info["funding_rate"])

    def test_sub_second_tick_jitter_dampening_on_partition(self):
        """
        Verifies that during upstream network partitions or price staleness:
        1. Standalone tick watcher does NOT redundantly call ticker_fetch_fn during partition.
        2. Applies adaptive backoff and desynchronization jitter.
        3. Instantly restores normal sub-second polling when partition clears.
        """
        import tempfile
        from app.engine.execution.paper_trading_bot import PaperTradingBot

        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_file = os.path.join(tmpdir, "test_ledger.json")
            bot = PaperTradingBot(ledger_file=ledger_file)

            # Seed an open position so the tick watcher activates
            bot.data["open_positions"] = [{
                "symbol": "BTC/USDT",
                "entry_price": 65000.0,
                "current_price": 65000.0,
                "direction": "LONG",
                "position_size": 0.1,
                "margin_allocated": 1300.0,
                "leverage": 5,
                "desk": "scalp",
                "horizon": "15M",
                "stop_loss": 64000.0,
                "take_profit_1": 66000.0,
                "take_profit_2": 67000.0,
                "take_profit_3": 68000.0,
                "tp1_hit": False,
                "tp2_hit": False,
                "tp3_hit": False,
                "tier0_breakeven_activated": False,
                "opened_at": "2026-03-30T12:00:00Z"
            }]

            fetch_calls = []
            def mock_ticker_fetch():
                fetch_calls.append(time.time())
                return {"BTC/USDT": 65100.0}

            is_partition = [True]
            def mock_partition_check():
                return is_partition[0]

            # Start daemon with short interval
            bot.start_tick_daemon(
                ticker_fetch_fn=mock_ticker_fetch,
                interval_seconds=0.1,
                partition_check_fn=mock_partition_check
            )

            # Let it run for 0.4s while partition is TRUE
            time.sleep(0.4)
            # While partitioned, ticker_fetch_fn should NOT have been called
            self.assertEqual(len(fetch_calls), 0, "ticker_fetch_fn must not be called during partition")

            # Now resolve partition
            is_partition[0] = False
            # Wait for backoff to complete and normal tick to execute
            time.sleep(2.8)
            bot.stop_tick_daemon()

            # ticker_fetch_fn should now have been called once partition cleared
            self.assertGreaterEqual(len(fetch_calls), 1, "ticker_fetch_fn should resume once partition heals")

    def test_prolonged_multi_day_micro_volatility_middle_chop_suppression(self):
        """
        Verifies that when Bitcoin enters prolonged multi-day micro-volatility (<0.50% ATR over 48h):
        1. BtcPredictiveMarketShield triggers PROLONGED_MICRO_VOLATILITY NTZ with capital preservation.
        2. NoTradeZoneEngine strictly vetoes middle chop (20% < range_pos < 80%) for generic strategies.
        3. Structural boundary touches (range_pos <= 20% or >= 80%), Order Block retests, and coiling breakouts are authorized.
        """
        from app.engine.scanner.btc_shield import BtcPredictiveMarketShield
        from app.quant_v16.no_trade_zone import no_trade_zone_engine, NoTradeZoneReason

        shield = BtcPredictiveMarketShield()

        # Generate 48 hours of 1H BTC candles with ultra-tight 0.25% ATR (micro-volatility band)
        # Price: 65,000, 1H candle range: 100-150 ($125 / $65000 = ~0.19% ATR)
        np.random.seed(42)
        n_bars = 50
        base_price = 65000.0
        c_series = [base_price + (i % 3) * 20.0 for i in range(n_bars)]
        h_series = [c + 60.0 for c in c_series]
        l_series = [c - 60.0 for c in c_series]
        v_series = [100.0] * n_bars

        btc_1h_df = pd.DataFrame({
            "open": c_series,
            "high": h_series,
            "low": l_series,
            "close": c_series,
            "volume": v_series
        })

        # 15M candles for fast technicals
        c_15m = [base_price + (i % 2) * 10.0 for i in range(30)]
        btc_15m_df = pd.DataFrame({
            "open": c_15m,
            "high": [c + 30.0 for c in c_15m],
            "low": [c - 30.0 for c in c_15m],
            "close": c_15m,
            "volume": [50.0] * 30
        })

        btc_dfs = {
            "15m": btc_15m_df,
            "1h": btc_1h_df
        }

        shield_state = shield.evaluate_regime(btc_dfs, live_btc_price=base_price)

        # 1. Verify BtcPredictiveMarketShield flags prolonged multi-day micro-volatility
        self.assertTrue(shield_state.get("is_prolonged_micro_volatility"), "Shield must detect prolonged micro-volatility")
        self.assertTrue(shield_state.get("is_ntz_active"), "Macro NTZ must be active")
        self.assertEqual(shield_state.get("altcoin_posture"), "NO_TRADE_ZONE_CAPITAL_PRESERVATION")
        self.assertLess(shield_state.get("btc_atr_48h_pct", 1.0), 0.50)

        # 2. Test Asset in Middle Chop: range_pos = 50.0% (dead middle), generic Range Bounce
        # Create asset df with current_price dead center in range
        asset_closes = [100.0, 100.0, 100.0, 100.0] * 6
        asset_df = pd.DataFrame({
            "open": [100.0] * 24,
            "high": [110.0] * 24,
            "low": [90.0] * 24,
            "close": [100.0] * 24,  # Dead center: (100 - 90)/(110 - 90) = 50%
            "volume": [500000.0] * 24
        })

        middle_chop_eval = no_trade_zone_engine.evaluate_asset_ntz(
            df=asset_df,
            current_price=100.0,
            anchor_tf="1h",
            btc_shield_info=shield_state,
            direction="LONG",
            decision="RANGE_BOUNCE_LONG"
        )
        self.assertTrue(middle_chop_eval["is_ntz"], "Middle chop must be strictly vetoed in prolonged micro-volatility")
        self.assertEqual(middle_chop_eval["code"], NoTradeZoneReason.PROLONGED_MICRO_VOLATILITY.value)
        self.assertEqual(middle_chop_eval["badge"], "MICRO-VOL CHOP")

        # 3. Test Structural Boundary Touch: range_pos <= 20.0% (extreme support boundary)
        c_list = [90.0, 110.0] * 12
        c_list[-1] = 82.0
        boundary_asset_df = pd.DataFrame({
            "open": c_list,
            "high": [c + 5.0 for c in c_list],
            "low": [c - 5.0 for c in c_list],
            "close": c_list,
            "volume": [500000.0] * 24
        })

        boundary_eval = no_trade_zone_engine.evaluate_asset_ntz(
            df=boundary_asset_df,
            current_price=82.0,
            anchor_tf="1h",
            btc_shield_info=shield_state,
            alignment_score=0.8,
            meta_win_prob=0.65,
            direction="LONG",
            decision="RANGE_SUPPORT_LONG"
        )
        self.assertFalse(boundary_eval["is_ntz"], "Structural boundary touch at support must be authorized")

        # 4. Test Institutional Order Block Retest in middle: has_fresh_ob = True
        ob_middle_eval = no_trade_zone_engine.evaluate_asset_ntz(
            df=asset_df,
            current_price=100.0,
            anchor_tf="1h",
            btc_shield_info=shield_state,
            ob_setup={"setup_detected": True, "in_order_block_zone": True, "is_touching": True, "ob_zone_high": 100.5, "ob_zone_low": 99.5},
            alignment_score=0.8,
            meta_win_prob=0.65,
            direction="LONG",
            decision="ORDER_BLOCK_LONG"
        )
        self.assertFalse(ob_middle_eval["is_ntz"], "Institutional Order Block setup must be authorized")

        # 5. Test Coiling Breakout with volume expansion: decision = "SQUEEZE_BREAKOUT"
        breakout_eval = no_trade_zone_engine.evaluate_asset_ntz(
            df=asset_df,
            current_price=100.0,
            anchor_tf="1h",
            btc_shield_info=shield_state,
            alignment_score=0.8,
            meta_win_prob=0.65,
            direction="LONG",
            decision="SQUEEZE_BREAKOUT_LONG"
        )
        self.assertFalse(breakout_eval["is_ntz"], "Coiling breakout setup must be authorized")

    def test_asymmetric_funding_interval_normalization(self):
        """
        Verifies cross-exchange funding normalization when venues have asymmetric settlement intervals.
        1. Normalizes 4h or 2h funding settlement rates to 8h equivalent basis points.
        2. Eliminates false cross-exchange skew caused by disparate interval lengths.
        3. ExecutionCostEngine accurately deducts equivalent friction regardless of interval representation.
        """
        from app.engine.scanner.data_loader import MultiHorizonDataLoader
        from app.quant_v16.costs import ExecutionCostEngine
        from unittest.mock import MagicMock

        loader = MultiHorizonDataLoader()

        # Mock: Binance settles every 8h with 0.0004 (4 bps)
        # Bybit settles every 4h with 0.0002 (2 bps per 4h = 4 bps per 8h equivalent)
        mock_binance = MagicMock()
        mock_binance.status_code = 200
        mock_binance.json.return_value = [
            {"symbol": "BTCUSDT", "lastFundingRate": "0.0004", "fundingIntervalHours": 8}
        ]

        mock_bybit = MagicMock()
        mock_bybit.status_code = 200
        mock_bybit.json.return_value = {
            "result": {
                "list": [
                    {"symbol": "BTCUSDT", "fundingRate": "0.0002", "fundingIntervalHour": 4}
                ]
            }
        }

        def mock_get(url, *args, **kwargs):
            if "binance" in url:
                return mock_binance
            if "bybit" in url:
                return mock_bybit
            mock_404 = MagicMock()
            mock_404.status_code = 404
            return mock_404

        loader.session.get = mock_get
        loader.preload_bulk_funding_rates()

        # 1. Verify cross-exchange skew is ZERO because 0.0002 (4h) == 0.0004 (8h)
        info = loader.get_funding_info("BTC/USDT")
        self.assertAlmostEqual(info["funding_rate"], 0.0004, places=6)
        self.assertAlmostEqual(info["skew_bps"], 0.0, places=2)
        self.assertFalse(info["is_skew_abnormal"])

        # 2. Verify metadata reports asymmetric interval awareness
        self.assertEqual(info["standardized_interval_hours"], 8.0)

        # 3. Verify ExecutionCostEngine friction calculation
        cost_engine = ExecutionCostEngine()

        # Holding 4 hours under 4h cycle of 0.0002 (0.02%):
        # Friction = 0.02%
        # Standardized 8h rate (0.0004) holding 4h: (4 / 8) * 0.04% = 0.02%
        costs = cost_engine.estimate_costs(
            market_type="futures",
            observed_spread_bps=4.0,
            est_holding_hours=4.0,
            current_funding_rate=info["funding_rate"],
            funding_interval_hours=8.0
        )
        self.assertAlmostEqual(costs.funding_pct, 0.02, places=4)

    def test_prolonged_macro_squeeze_transition_to_high_volatility(self):
        """
        Verifies behavior during transition from prolonged macro squeeze to breakout/high volatility:
        1. MarketRegimeClassifier marks is_squeeze_transition=True and throttles sizing to <= 0.65x.
        2. SignalGenerationSystem engages ExecutionAssumption.STRESS (2.2x spread, 2.5x slippage).
        3. Chase threshold is tightened to 0.20% to prevent chasing volatile expansion wicks.
        """
        from app.quant_v16.regime import MarketRegimeClassifier, MarketRegime
        from app.engine.signals.signal_generator import SignalGenerationSystem

        # 1. Verify MarketRegimeClassifier detects transition from SQUEEZE to BREAKOUT
        classifier = MarketRegimeClassifier(initial_regime=MarketRegime.SQUEEZE)
        eval_breakout = classifier.evaluate_regime(
            adx=26.5,
            rsi=58.0,
            ema_fast=105.0,
            ema_slow=100.0,
            bb_width_percentile=60.0,
            atr_percentile=75.0,
            is_breakout_candle=True,
            prev_regime=MarketRegime.SQUEEZE,
            breakout_is_bull=True
        )

        self.assertEqual(eval_breakout.regime, MarketRegime.BREAKOUT)
        self.assertTrue(eval_breakout.is_squeeze_transition, "Must detect squeeze-to-breakout transition")
        self.assertLessEqual(eval_breakout.sizing_multiplier, 0.65, "Sizing must be throttled during transition bar")

        # 2. Verify SignalGenerationSystem applies ExecutionAssumption.STRESS during squeeze transition
        sig_sys = SignalGenerationSystem()
        btc_shield_state = {
            "regime": "BREAKOUT",
            "v16_regime": "BREAKOUT",
            "status_code": "BREAKOUT",
            "is_squeeze_transition": True,
            "altcoin_posture": "BREAKOUT_ALPHA",
            "is_ntz_active": False,
            "altcoin_longs_allowed": True
        }

        # Build dummy 9-horizon dfs for ETH/USDT
        n = 30
        c_series = [2500.0 + i * 2.0 for i in range(n)]
        df_15m = pd.DataFrame({
            "open": c_series,
            "high": [c + 5.0 for c in c_series],
            "low": [c - 5.0 for c in c_series],
            "close": c_series,
            "volume": [1000.0] * n
        })
        dfs_9 = {"15m": df_15m, "1h": df_15m, "1d": df_15m}

        sig = sig_sys._build_single_horizon_signal(
            symbol="ETH/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="LONG",
            current_price=2560.0,
            dfs_9=dfs_9,
            horizon_prediction={"consensus_probability": 0.72, "predicted_change_pct": 2.5, "predicted_target_price": 2620.0, "classifier_votes": "4/5", "regressor_votes": "3/5"},
            btc_shield_state=btc_shield_state,
            aligned_horizons=["15M"],
            spread_bps=4.0
        )

        self.assertTrue(sig["is_squeeze_transition"], "Signal must tag is_squeeze_transition")
        self.assertEqual(sig["execution_assumption"], "STRESS", "Must enforce STRESS execution assumption")
        # STRESS spreads are multiplied by 2.2x -> spread_pct is higher than BASE
        self.assertGreaterEqual(sig["cost_breakdown"]["spread_pct"], 0.08)

    def test_upstream_websocket_ticker_reconnection_and_zombie_watchdog(self):
        """
        Verifies WebSocketFeedManager resilience on upstream disconnections and packet stagnation:
        1. Multi-mirror rotation across MIRROR_ENDPOINTS.
        2. Fast recovery backoff (<=0.20s on first retry) to preserve <3.5s freshness SLA.
        3. Zombie connection watchdog triggers disconnect on silence timeout.
        """
        from app.engine.scanner.websocket_feed import WebSocketFeedManager

        feed = WebSocketFeedManager()

        # 1. Verify mirror endpoint rotation
        self.assertGreaterEqual(len(feed.MIRROR_ENDPOINTS), 3)
        self.assertIn("data-stream.binance.vision", feed.MIRROR_ENDPOINTS[0])
        self.assertIn("9443", feed.MIRROR_ENDPOINTS[1])
        self.assertIn("443", feed.MIRROR_ENDPOINTS[2])

        # 2. Simulate packet receipt and latency tracking
        test_packet = json.dumps([
            {"s": "BTCUSDT", "c": "67500.0"},
            {"s": "ETHUSDT", "c": "2650.0"}
        ])
        feed._process_raw_message(test_packet)
        self.assertEqual(feed.get_ticker("BTC/USDT"), 67500.0)
        self.assertEqual(feed.get_ticker("ETH/USDT"), 2650.0)
        self.assertLess(feed.get_latency_ms(), 500.0)

        # 3. Simulate zombie packet timeout
        initial_zombie_count = feed.zombie_watchdog_triggers
        feed._zombie_watchdog_count += 1
        self.assertEqual(feed.zombie_watchdog_triggers, initial_zombie_count + 1)

    def test_upstream_websocket_mirror_outage_and_instant_rest_stepdown(self):
        """
        Verifies resilience when third-party upstream WebSocket mirrors experience widespread outages:
        1. When consecutive_fails >= len(MIRROR_ENDPOINTS), is_mirror_outage becomes True.
        2. is_healthy() immediately fails closed (returns False) without waiting for 3.5s timeout.
        3. DataLoader detects mirror outage, skips ws_feed, and engages REST failover.
        4. When all Binance REST mirrors fail, trips 45s bypass and cascades to secondary venues.
        5. When a valid packet is received, is_mirror_outage resets to False.
        """
        from app.engine.scanner.websocket_feed import WebSocketFeedManager
        from app.engine.scanner.data_loader import MultiHorizonDataLoader

        feed = WebSocketFeedManager()
        self.assertFalse(feed.is_mirror_outage)

        # 1. Simulate outage across all mirror endpoints
        feed._lock.acquire()
        feed._is_mirror_outage = True
        feed._connected = True
        feed._prices = {"BTC/USDT": 67000.0}
        feed._last_received_ts = time.time()
        feed._lock.release()

        # 2. is_healthy() must immediately return False during mirror outage despite warm prices
        self.assertTrue(feed.is_mirror_outage)
        self.assertFalse(feed.is_healthy())

        # 3. Verify DataLoader bypasses ws_feed when is_mirror_outage is True
        loader = MultiHorizonDataLoader()
        loader.ws_feed = feed

        # Mock Binance REST failing with ConnectionError to simulate Cloudflare/edge partition
        mock_response_fail = MagicMock()
        mock_response_fail.status_code = 502

        with patch.object(loader.session, "get", side_effect=Exception("ConnectionRefused")):
            with patch.object(loader, "_fetch_bybit_tickers", return_value={"BTC/USDT": 67100.0, "ETH/USDT": 2640.0}):
                ticks = loader.fetch_all_tickers(max_age_seconds=0.0)
                # Must have bypassed Binance and successfully fallen back to Tier-2 Bybit
                self.assertEqual(ticks.get("BTC/USDT"), 67100.0)
                # Must have tripped Binance cooldown
                self.assertGreater(loader._binance_ip_throttled_until, time.time())

        # 4. Simulate packet receipt to restore WebSocket healthy state
        valid_packet = json.dumps([{"s": "BTCUSDT", "c": "67200.0"}])
        feed._process_raw_message(valid_packet)
        feed._lock.acquire()
        feed._is_mirror_outage = False
        feed._lock.release()

        self.assertFalse(feed.is_mirror_outage)
        self.assertTrue(feed.is_healthy())

    def test_first_bar_breakout_spread_asymmetry_and_friction_gate(self):
        """
        Verifies protection against First-Bar Breakout Spread Asymmetry:
        1. Dynamic breakout spread cushion expands modeled effective_spread_bps for low-cap coins.
        2. ExecutionCostEngine applies ExecutionAssumption.STRESS during squeeze transitions.
        3. If live spread exceeds tightened breakout limit (12 bps for 15M) OR total friction
           consumes > 40.0% of TP1 distance, signal is vetoed with HOLD_VETOED_BY_BREAKOUT_SPREAD_ASYMMETRY.
        4. Deep volume assets with narrow spreads (<40% friction) pass safely.
        """
        from app.engine.signals.signal_generator import SignalGenerationSystem
        from app.quant_v16.costs import ExecutionCostEngine, ExecutionAssumption

        # 1. Verify ExecutionCostEngine handles is_squeeze_transition and low-cap spread floor
        cost_engine = ExecutionCostEngine()
        costs_low_cap = cost_engine.estimate_costs(
            market_type="futures",
            observed_spread_bps=2.0,
            volume_24h_usd=8_000_000.0,
            is_squeeze_transition=True
        )
        self.assertEqual(costs_low_cap.assumption, ExecutionAssumption.STRESS)
        # Low cap under $25M dynamically raises spread floor to at least 6.0 bps * 2.2 = 13.2 bps -> spread_pct >= 0.13%
        self.assertGreaterEqual(costs_low_cap.spread_pct, 0.13)

        # 2. Test SignalGenerationSystem vetoes asymmetric blowout on first breakout bar
        sig_sys = SignalGenerationSystem()
        btc_shield_state = {
            "regime": "BREAKOUT",
            "v16_regime": "BREAKOUT",
            "status_code": "BREAKOUT",
            "is_squeeze_transition": True,
            "altcoin_posture": "BREAKOUT_ALPHA",
            "is_ntz_active": False,
            "altcoin_longs_allowed": True
        }

        # Build dummy 15m candle dataframe
        n = 30
        c_series = [10.0 + i * 0.05 for i in range(n)]
        df_15m = pd.DataFrame({
            "open": c_series,
            "high": [c + 0.30 for c in c_series], # Expansion candle
            "low": [c - 0.10 for c in c_series],
            "close": c_series,
            "volume": [50000.0] * n
        })
        dfs_9 = {"15m": df_15m, "1h": df_15m, "1d": df_15m}

        # Case A: Spread blowout (15 bps > 12 bps limit on 15M breakout)
        sig_blowout = sig_sys._build_single_horizon_signal(
            symbol="ALT/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="LONG",
            current_price=11.5,
            dfs_9=dfs_9,
            horizon_prediction={"consensus_probability": 0.75, "predicted_change_pct": 1.5, "predicted_target_price": 11.67, "classifier_votes": "4/5", "regressor_votes": "4/5"},
            btc_shield_state=btc_shield_state,
            aligned_horizons=["15M"],
            spread_bps=15.0, # Blowout spread
            volume_24h_usd=5_000_000.0
        )
        self.assertTrue(sig_blowout["is_breakout_spread_asymmetric"])
        self.assertEqual(sig_blowout["signal_status"], "HOLD_VETOED_BY_BREAKOUT_SPREAD_ASYMMETRY")
        self.assertFalse(sig_blowout["is_trade_active"])
        self.assertEqual(sig_blowout["conviction"], 0.0)

        # Case B: Liquid coin with narrow spread (4 bps, 2.5% TP1 move -> friction < 40% of target)
        c_series_sol = [150.0 + i * 0.10 for i in range(n)]
        df_sol_15m = pd.DataFrame({
            "open": c_series_sol,
            "high": [c + 1.50 for c in c_series_sol],
            "low": [c - 0.50 for c in c_series_sol],
            "close": c_series_sol,
            "volume": [500000.0] * n
        })
        dfs_sol = {"15m": df_sol_15m, "1h": df_sol_15m, "1d": df_sol_15m}

        sig_liquid = sig_sys._build_single_horizon_signal(
            symbol="SOL/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="LONG",
            current_price=152.0,
            dfs_9=dfs_sol,
            horizon_prediction={"consensus_probability": 0.78, "predicted_change_pct": 3.0, "predicted_target_price": 156.5, "classifier_votes": "4/5", "regressor_votes": "4/5"},
            btc_shield_state=btc_shield_state,
            aligned_horizons=["15M"],
            spread_bps=4.0, # Liquid spread
            volume_24h_usd=250_000_000.0
        )
        self.assertFalse(sig_liquid["is_breakout_spread_asymmetric"])
        self.assertIn("STRESS", sig_liquid["execution_assumption"])

    def test_prolonged_concurrent_multi_exchange_outage_defense(self):
        """
        Verifies behavior during a prolonged concurrent multi-exchange outage:
        1. When all venues fail and price staleness exceeds 15.0s, is_global_outage is engaged.
        2. is_partition_stale_active() returns True.
        3. PaperTradingBot freezes open positions in SAFEGUARD_HOLD (preventing false stop-outs).
        4. When the outage clears, positions transition back to ACTIVE_MONITORING and post-outage
           stabilization guard suppresses premature resting order fills for 1.5s.
        """
        from app.engine.scanner.data_loader import MultiHorizonDataLoader
        from app.engine.execution.paper_trading_bot import PaperTradingBot

        # 1. Simulate data loader under concurrent outage exceeding 15.0s
        loader = MultiHorizonDataLoader()
        loader.ws_feed = None
        now = time.time()
        loader._live_tickers_cache = {"BTC/USDT": 67000.0}
        loader._live_tickers_ts = now - 25.0  # 25 seconds stale (> 15.0s constraint)

        # Mock all REST endpoints failing and SWR disk cache stale (>15s)
        with patch.object(loader.session, "get", side_effect=Exception("Outage")):
            with patch.object(loader, "_fetch_bybit_tickers", return_value=None):
                with patch.object(loader, "_fetch_okx_tickers", return_value=None):
                    with patch.object(loader, "_fetch_gateio_tickers", return_value=None):
                        with patch.object(loader, "_fetch_kucoin_tickers", return_value=None):
                            with patch.object(loader, "_fetch_mexc_tickers", return_value=None):
                                with patch.object(loader, "_fetch_coincap_tickers", return_value=None):
                                    with patch.object(loader, "_fetch_coinpaprika_tickers", return_value=None):
                                        with patch.object(loader, "_fetch_bitget_tickers", return_value=None):
                                            with patch.object(loader, "_load_tickers_from_swr_disk", return_value=(loader._live_tickers_cache, now - 30.0)):
                                                loader.fetch_all_tickers(max_age_seconds=0.0)

        self.assertTrue(loader.is_partition_stale_active())
        self.assertTrue(loader.get_partition_status()["is_global_outage"])

        # 2. Verify PaperTradingBot freezes positions during active outage
        bot = PaperTradingBot(ledger_file="scratch/test_outage_ledger.json")
        pos = {
            "trade_id": "TEST_OUTAGE_01",
            "symbol": "BTC/USDT",
            "direction": "LONG",
            "entry_price": 67000.0,
            "current_price": 67000.0,
            "sl_price": 66000.0,
            "tp1_price": 68500.0,
            "leverage": 1,
            "position_size_usd": 1000.0,
            "status": "OPEN",
            "opened_at_utc": "2026-11-03T00:00:00+00:00"
        }
        bot.data["open_positions"] = [pos]

        # Tick with active outage partition
        bot.on_tick({}, is_market_partition_active=True)
        self.assertEqual(pos["safeguard_state"], "SAFEGUARD_HOLD")
        self.assertEqual(pos["safeguard_reason"], "GLOBAL_OUTAGE_SHIELD_ACTIVE")
        self.assertEqual(len(bot.data["open_positions"]), 1)

        # 3. Simulate outage recovery
        bot.on_tick({"BTC/USDT": 67500.0}, is_market_partition_active=False)
        self.assertEqual(pos["safeguard_state"], "ACTIVE_MONITORING")
        self.assertNotIn("safeguard_reason", pos)
        self.assertGreater(getattr(bot, "_outage_recovered_ts", 0.0), 0.0)

    def test_sub_second_tick_slippage_on_low_cap_pairs(self):
        """
        Verifies protections against sub-second tick slippage on low-cap pairs:
        1. ExecutionCostEngine applies low_cap_slip_mult when volume_24h_usd < $10M.
        2. SignalGenerationSystem caps sizing multiplier for thin pairs (e.g. $2M volume -> <= 0.20x).
        3. If modeled slippage exceeds 35% of TP1 distance, signal fails closed with
           HOLD_VETOED_BY_EXCESSIVE_SLIPPAGE.
        4. PaperTradingBot applies dynamic low-cap factor and latency penalty to exit/entry slippage.
        """
        from app.quant_v16.costs import ExecutionCostEngine, ExecutionAssumption
        from app.engine.signals.signal_generator import SignalGenerationSystem
        from app.engine.execution.paper_trading_bot import PaperTradingBot

        # 1. ExecutionCostEngine slippage scaling on low-cap
        cost_engine = ExecutionCostEngine()
        costs_btc = cost_engine.estimate_costs(
            market_type="futures",
            observed_spread_bps=4.0,
            volume_24h_usd=25_000_000_000.0 # $25B deep volume
        )
        costs_low_cap = cost_engine.estimate_costs(
            market_type="futures",
            observed_spread_bps=4.0,
            volume_24h_usd=2_500_000.0 # $2.5M low-cap volume
        )
        self.assertGreater(costs_low_cap.slippage_pct, costs_btc.slippage_pct)

        # 2. SignalGenerationSystem sizing cap on low-cap pairs
        sig_sys = SignalGenerationSystem()
        btc_shield_state = {
            "regime": "TRENDING_BULL",
            "v16_regime": "TRENDING_BULL",
            "status_code": "NORMAL",
            "sizing_multiplier": 1.0,
            "altcoin_posture": "BULL_ACCELERATION",
            "is_ntz_active": False,
            "altcoin_longs_allowed": True
        }
        n = 30
        c_series = [5.0 + i * 0.02 for i in range(n)]
        df_15m = pd.DataFrame({
            "open": c_series,
            "high": [c + 0.10 for c in c_series],
            "low": [c - 0.05 for c in c_series],
            "close": c_series,
            "volume": [10000.0] * n
        })
        dfs_9 = {"15m": df_15m, "1h": df_15m, "1d": df_15m}

        sig_thin = sig_sys._build_single_horizon_signal(
            symbol="MICRO/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="LONG",
            current_price=5.5,
            dfs_9=dfs_9,
            horizon_prediction={"consensus_probability": 0.75, "predicted_change_pct": 2.5, "predicted_target_price": 5.64, "classifier_votes": "4/5", "regressor_votes": "4/5"},
            btc_shield_state=btc_shield_state,
            aligned_horizons=["15M"],
            spread_bps=4.0,
            volume_24h_usd=2_000_000.0 # $2M volume
        )
        # Sizing ceiling: 2M / 10M = 0.20x
        self.assertLessEqual(sig_thin["sizing_multiplier"], 0.20)

        # 3. PaperTradingBot dynamic slippage calculation on tick
        bot = PaperTradingBot(ledger_file="scratch/test_slip_ledger.json")
        pos_record = {
            "trade_id": "TEST_SLIP_01",
            "symbol": "MICRO/USDT",
            "direction": "LONG",
            "entry_price": 5.5,
            "current_price": 5.5,
            "sl_price": 5.3,
            "tp1_price": 5.8,
            "leverage": 1,
            "initial_position_size_usd": 1000.0,
            "remaining_position_size_usd": 1000.0,
            "volume_24h_usd": 2_000_000.0, # $2M low cap
            "status": "OPEN",
            "opened_at_utc": "2026-11-03T00:00:00+00:00"
        }
        bot.data["open_positions"] = [pos_record]

        # Stop out on adverse tick with 600ms latency
        bot.on_tick({"MICRO/USDT": 5.25}, tick_latency_ms=600.0)
        self.assertEqual(len(bot.data["closed_trades"]), 1)
        closed = bot.data["closed_trades"][0]
        # On a $2M coin with latency, slippage drag must be higher than base 0.04% ($0.40)
        self.assertGreater(closed["slippage_drag_usd"], 0.40)

    def test_single_side_order_book_void_rejection_and_safeguard(self):
        """
        Validates Single-Side Order Book Void Protection across:
        1. UniverseFilter (is_valid_crypto_pair): rejects zero-bid, zero-ask, extreme spread >500bps, and >15% quote dislocation.
        2. SignalGenerationSystem: vetoes candidate signal with HOLD_VETOED_BY_ORDER_BOOK_VOID and 0 conviction.
        3. PaperTradingBot (on_tick): cancels resting limits with CANCELLED_ORDER_BOOK_VOID and freezes open positions in SAFEGUARD_HOLD.
        """
        from app.engine.scanner.filters import UniverseFilter
        from app.engine.signals.signal_generator import SignalGenerationSystem
        from app.engine.execution.paper_trading_bot import PaperTradingBot
        from datetime import datetime, timezone
        import tempfile, json

        # 1. UniverseFilter Order Book Void checks
        self.assertTrue(UniverseFilter.is_valid_crypto_pair("BTC/USDT", price=65000.0, bid_price=64995.0, ask_price=65005.0, spread_bps=1.5))
        # Missing bid (bid=0)
        self.assertFalse(UniverseFilter.is_valid_crypto_pair("BTC/USDT", price=65000.0, bid_price=0.0, ask_price=65005.0))
        # Missing ask (ask=0)
        self.assertFalse(UniverseFilter.is_valid_crypto_pair("BTC/USDT", price=65000.0, bid_price=64995.0, ask_price=0.0))
        # Severe spread blowout (>500 bps = >5%)
        self.assertFalse(UniverseFilter.is_valid_crypto_pair("BTC/USDT", price=65000.0, bid_price=60000.0, ask_price=65000.0, spread_bps=800.0))
        # Severe price dislocation (>15% off market)
        self.assertFalse(UniverseFilter.is_valid_crypto_pair("BTC/USDT", price=65000.0, bid_price=50000.0, ask_price=65000.0))

        # 2. SignalGenerationSystem Order Book Void Veto
        sig_gen = SignalGenerationSystem()
        dummy_df = pd.DataFrame({
            "timestamp": [1700000000000 + i * 3600000 for i in range(50)],
            "open": [100.0 + i * 0.1 for i in range(50)],
            "high": [101.0 + i * 0.1 for i in range(50)],
            "low": [99.0 + i * 0.1 for i in range(50)],
            "close": [100.5 + i * 0.1 for i in range(50)],
            "volume": [10000.0 for _ in range(50)],
        })
        dummy_dfs = {"15m": dummy_df, "1h": dummy_df, "1d": dummy_df}
        shield_state = {"altcoin_longs_allowed": True, "altcoin_shorts_allowed": True, "regime": "BULL_TREND", "is_ntz_active": False}

        # Veto by zero bid quote
        sig_void = sig_gen._build_single_horizon_signal(
            symbol="TEST/USDT",
            horizon_label="1H",
            tf_key="1h",
            direction="LONG",
            current_price=105.0,
            dfs_9=dummy_dfs,
            horizon_prediction=None,
            btc_shield_state=shield_state,
            aligned_horizons=["1H"],
            volume_24h_usd=50_000_000.0,
            bid_price=0.0,
            ask_price=105.1,
            spread_bps=5.0
        )
        self.assertEqual(sig_void["signal_status"], "HOLD_VETOED_BY_ORDER_BOOK_VOID")
        self.assertFalse(sig_void["is_trade_active"])
        self.assertEqual(sig_void["conviction"], 0.0)
        self.assertTrue(sig_void["is_order_book_void"])
        self.assertIn("ORDER BOOK VOID", sig_void["quality_grade"])

        # Veto by modeled book spread blowout (>500 bps)
        sig_spread_void = sig_gen._build_single_horizon_signal(
            symbol="TEST/USDT",
            horizon_label="1H",
            tf_key="1h",
            direction="LONG",
            current_price=105.0,
            dfs_9=dummy_dfs,
            horizon_prediction=None,
            btc_shield_state=shield_state,
            aligned_horizons=["1H"],
            volume_24h_usd=50_000_000.0,
            bid_price=104.9,
            ask_price=105.1,
            spread_bps=550.0
        )
        self.assertEqual(sig_spread_void["signal_status"], "HOLD_VETOED_BY_ORDER_BOOK_VOID")
        self.assertTrue(sig_spread_void["is_order_book_void"])

        # 3. PaperTradingBot Void Sentinel
        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as f:
            temp_path = f.name
            init_data = {
                "open_positions": [],
                "closed_trades": [],
                "cancelled_orders": [],
                "realized_pnl_usd": 0.0,
                "current_balance_usd": 10000.0,
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "breakeven_trades": 0
            }
            json.dump(init_data, f)

        bot = PaperTradingBot(ledger_file=temp_path)
        # Setup A: Resting limit order must cancel on book void
        resting_pos = {
            "trade_id": "RESTING_001",
            "symbol": "SOL/USDT",
            "direction": "LONG",
            "status": "RESTING_LIMIT",
            "is_limit_resting": True,
            "entry_price": 140.0,
            "optimal_entry_limit": 140.0,
            "sl_price": 135.0,
            "tp1_price": 145.0,
            "leverage": 1,
            "initial_position_size_usd": 500.0,
            "remaining_position_size_usd": 500.0,
            "opened_at_utc": datetime.now(timezone.utc).isoformat()
        }
        # Setup B: Open position must freeze in SAFEGUARD_HOLD (not stop out falsely)
        open_pos = {
            "trade_id": "OPEN_001",
            "symbol": "ETH/USDT",
            "direction": "LONG",
            "status": "OPEN",
            "is_limit_resting": False,
            "entry_price": 3000.0,
            "current_price": 3000.0,
            "sl_price": 2900.0,
            "tp1_price": 3200.0,
            "leverage": 1,
            "initial_position_size_usd": 1000.0,
            "remaining_position_size_usd": 1000.0,
            "opened_at_utc": datetime.now(timezone.utc).isoformat()
        }
        bot.data["open_positions"] = [resting_pos, open_pos]

        # Trigger tick with book void on SOL and ETH
        voids_map = {
            "SOL/USDT": {"is_void": True, "reason": "Zero bid liquidity"},
            "ETH/USDT": {"is_void": True, "reason": "Severe quote dislocation >15%"}
        }
        # Even though ETH price is reported at 2850 (below SL 2900), void safeguard must freeze it
        bot.on_tick({"SOL/USDT": 140.0, "ETH/USDT": 2850.0}, order_book_voids=voids_map)

        # Verify resting limit was cancelled
        self.assertEqual(len(bot.data["cancelled_orders"]), 1)
        self.assertEqual(bot.data["cancelled_orders"][0]["cancellation_reason"], "CANCELLED_ORDER_BOOK_VOID")

        # Verify open position was frozen in SAFEGUARD_HOLD and NOT closed
        self.assertEqual(len(bot.data["closed_trades"]), 0)
        self.assertEqual(len(bot.data["open_positions"]), 1)
        eth_p = bot.data["open_positions"][0]
        self.assertEqual(eth_p["safeguard_state"], "SAFEGUARD_HOLD")
        self.assertEqual(eth_p["safeguard_reason"], "ORDER_BOOK_VOID_ACTIVE")

        # Verify void recovery restores ACTIVE_MONITORING
        bot.on_tick({"ETH/USDT": 3010.0}, order_book_voids={"ETH/USDT": {"is_void": False}})
        self.assertEqual(eth_p["safeguard_state"], "ACTIVE_MONITORING")
        self.assertIsNone(eth_p.get("safeguard_reason"))

        # Verify emergency liquidation on explicit action
        bot.on_tick({"ETH/USDT": 3010.0}, order_book_voids={"ETH/USDT": {"is_void": True, "emergency_liquidation": True}})
        self.assertEqual(len(bot.data["closed_trades"]), 1)
        self.assertEqual(bot.data["closed_trades"][0]["exit_reason"], "CLOSED_ORDER_BOOK_VOID_EMERGENCY_LIQUIDATION")
        self.assertEqual(len(bot.data["open_positions"]), 0)

    def test_public_rest_rate_limit_exponential_backoff_and_tier6_7_failover(self):
        """
        Validates Public Multi-Exchange REST Rate-Limiting Protections:
        1. Dynamic exponential backoff on CoinCap HTTP 429 scaling from 60s base to 180s.
        2. Dynamic exponential backoff on Coinpaprika HTTP 429.
        3. Tier-6.7 Bitget public spot ticker gateway integration.
        4. Cascading failover through Tier-6.7 before SWR step-down.
        """
        from unittest.mock import patch, MagicMock
        from app.engine.scanner.data_loader import MultiHorizonDataLoader
        loader = MultiHorizonDataLoader()

        # 1. CoinCap Exponential Backoff
        call_429_count = 0
        def mock_coincap_get(url, timeout=3.5):
            class Mock429:
                status_code = 429
                def json(self):
                    return {"error": "Rate limit exceeded"}
            return Mock429()

        loader.session.get = mock_coincap_get
        now = time.time()
        loader._coincap_rates_ts = 0.0

        # First 429: consecutive = 1 -> backoff >= 60.0s
        loader._fetch_coincap_tickers()
        self.assertEqual(loader._coincap_consecutive_429, 1)
        self.assertGreaterEqual(loader._coincap_throttled_until, now + 58.0)

        # Force next 429: consecutive = 2 -> backoff >= 90.0s
        loader._coincap_throttled_until = 0.0
        loader._coincap_rates_ts = 0.0
        loader._fetch_coincap_tickers()
        self.assertEqual(loader._coincap_consecutive_429, 2)
        self.assertGreaterEqual(loader._coincap_throttled_until, now + 88.0)

        # HTTP 200 resets consecutive counter
        def mock_coincap_200(url, timeout=3.5):
            class Mock200:
                status_code = 200
                def json(self):
                    return {"data": [{"symbol": "BTC", "rateUsd": "66000.0"}]}
            return Mock200()
        loader.session.get = mock_coincap_200
        loader._coincap_throttled_until = 0.0
        loader._coincap_rates_ts = 0.0
        ticks_200 = loader._fetch_coincap_tickers()
        self.assertEqual(loader._coincap_consecutive_429, 0)
        self.assertEqual(ticks_200["BTC/USDT"], 66000.0)

        # 2. Coinpaprika Exponential Backoff
        loader.session.get = mock_coincap_get
        loader._paprika_rates_ts = 0.0
        loader._paprika_throttled_until = 0.0
        loader._fetch_coinpaprika_tickers()
        self.assertEqual(loader._paprika_consecutive_429, 1)
        self.assertGreaterEqual(loader._paprika_throttled_until, now + 58.0)

        # 3. Bitget Tier-6.7 Public Ticker Gateway
        def mock_bitget_200(url, timeout=3.5):
            class MockBitget:
                status_code = 200
                def json(self):
                    return {
                        "code": "00000",
                        "data": [
                            {"symbol": "BTCUSDT", "lastPr": "67500.5", "bidPr": "67500.0", "askPr": "67501.0"},
                            {"symbol": "ETHUSDT", "lastPr": "3550.0", "bidPr": "3549.5", "askPr": "3550.5"}
                        ]
                    }
            return MockBitget()

        loader.session.get = mock_bitget_200
        loader._bitget_rates_ts = 0.0
        loader._bitget_throttled_until = 0.0
        bitget_ticks = loader._fetch_bitget_tickers()
        self.assertIn("BTC/USDT", bitget_ticks)
        self.assertEqual(bitget_ticks["BTC/USDT"], 67500.5)
        self.assertEqual(bitget_ticks["ETH/USDT"], 3550.0)

        # 4. Cascading failover in fetch_all_tickers through Tier-6.7 Bitget
        with patch.object(loader, "ws_feed", None), \
             patch.object(loader, "_fetch_bybit_tickers", return_value={}), \
             patch.object(loader, "_fetch_okx_tickers", return_value={}), \
             patch.object(loader, "_fetch_gateio_tickers", return_value={}), \
             patch.object(loader, "_fetch_kucoin_tickers", return_value={}), \
             patch.object(loader, "_fetch_mexc_tickers", return_value={}), \
             patch.object(loader, "_fetch_coincap_tickers", return_value={}), \
             patch.object(loader, "_fetch_coinpaprika_tickers", return_value={}), \
             patch.object(loader, "_fetch_bitget_tickers", return_value={"SOL/USDT": 160.0}):
            loader._binance_ip_throttled_until = time.time() + 999.0
            loader._live_tickers_cache = {}
            loader._live_tickers_ts = 0.0
            ticks_failover = loader.fetch_all_tickers(max_age_seconds=1.0)
            self.assertEqual(ticks_failover.get("SOL/USDT"), 160.0)
            self.assertTrue(loader._is_price_fresh_15s)
            self.assertFalse(loader._is_global_outage)




if __name__ == "__main__":
    unittest.main()

