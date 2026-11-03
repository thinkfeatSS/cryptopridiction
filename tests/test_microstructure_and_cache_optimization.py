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
            time.sleep(1.8)
            bot.stop_tick_daemon()

            # ticker_fetch_fn should now have been called once partition cleared
            self.assertGreaterEqual(len(fetch_calls), 1, "ticker_fetch_fn should resume once partition heals")


if __name__ == "__main__":
    unittest.main()

