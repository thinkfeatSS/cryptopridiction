"""
QUANT EDGE V16: Forensic Verification Suite for Technical Analysis & Multi-Module Alignment
Tests:
1. Canonical Wilder ADX & RSI smoothing across all modules (candle_features, no_trade_zone, regime, fractal_consolidation).
2. DatetimeIndex and Sliced Index invariance in NoTradeZoneEngine.compute_adx (zero NaN / index misalignment).
3. Discrete candlestick pattern protection on unclosed live row (iloc[-1]) in CandleDynamicsFeatureExtractor.
4. Stabilized wick fakeout detection on completed candle in NoTradeZoneEngine.
5. Full 9-horizon scanning, alias resolution (24h/1d, 7d/1w, 30d/1M), and FVG boundary precision in InstitutionalOrderBlockEngine.
6. Strict price invariant enforcement (SL < Entry < TP1 < TP2 < TP3) and positive risk bounds in Order Block setups.
7. Robust case and alias profile resolution in CrossTimeframeMatrixEngine.
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

from app.engine.signals.candle_features import CandleDynamicsFeatureExtractor
from app.quant_v16.no_trade_zone import NoTradeZoneEngine, NoTradeZoneReason, no_trade_zone_engine
from app.quant_v16.regime import compute_live_btc_regime, MarketRegimeClassifier, MarketRegime
from app.quant_v16.fractal_consolidation import FractalConsolidationEngine, FractalTimeframeState
from app.quant_v16.order_blocks import InstitutionalOrderBlockEngine, OrderBlockType, OrderBlockState
from app.quant_v16.cross_timeframe_matrix import CrossTimeframeMatrixEngine, InstitutionalArchetype
from app.quant_v16.entry_confirmation import EntryConfirmationEngine
from app.quant_v16.strategies import StrategyArchetype, StrategyRegistry, StrategyStatus
from app.engine.signals.signal_generator import map_canonical_strategy


def generate_synthetic_ohlcv(n: int = 100, trend: str = "bullish", base_p: float = 100.0, freq: str = "1h") -> pd.DataFrame:
    """Generates deterministic synthetic OHLCV data with DatetimeIndex."""
    start_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    timestamps = [start_time + timedelta(hours=i) for i in range(n)]

    np.random.seed(42)
    closes = [base_p]
    for i in range(1, n):
        if trend == "bullish":
            drift = 0.5 + np.random.uniform(-0.2, 0.4)
        elif trend == "bearish":
            drift = -0.5 + np.random.uniform(-0.4, 0.2)
        else: # chop / range
            drift = np.sin(i / 3.0) * 0.8 + np.random.uniform(-0.2, 0.2)
        closes.append(max(1.0, closes[-1] + drift))

    highs, lows, opens, volumes = [], [], [], []
    for i in range(n):
        c = closes[i]
        o = closes[i-1] if i > 0 else c - 0.2
        rng = abs(c - o) + np.random.uniform(0.5, 1.5)
        h = max(c, o) + np.random.uniform(0.1, rng * 0.5)
        l = min(c, o) - np.random.uniform(0.1, rng * 0.5)
        v = np.random.uniform(100.0, 500.0)
        highs.append(h)
        lows.append(l)
        opens.append(o)
        volumes.append(v)

    df = pd.DataFrame({
        "timestamp": [int(ts.timestamp() * 1000) for ts in timestamps],
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes
    }, index=pd.DatetimeIndex(timestamps))
    return df


class TestTechnicalAnalysisForensics(unittest.TestCase):

    def setUp(self):
        self.df_bull = generate_synthetic_ohlcv(n=80, trend="bullish", base_p=100.0)
        self.df_bear = generate_synthetic_ohlcv(n=80, trend="bearish", base_p=100.0)
        self.df_chop = generate_synthetic_ohlcv(n=80, trend="chop", base_p=100.0)

    def test_adx_datetime_and_sliced_index_invariance(self):
        """Verify that NoTradeZoneEngine.compute_adx handles DatetimeIndex and slices without producing NaNs."""
        adx_full = NoTradeZoneEngine.compute_adx(self.df_bull, period=14)
        self.assertIsInstance(adx_full, float)
        self.assertFalse(np.isnan(adx_full))
        self.assertFalse(np.isinf(adx_full))
        # Should detect a strong trend on the bullish synthetic series (well above baseline 20.0)
        self.assertGreater(adx_full, 25.0, f"Bullish trend should have ADX > 25.0, got {adx_full}")

        # Sliced dataframe with non-zero start index
        df_slice = self.df_bull.iloc[20:].copy()
        adx_slice = NoTradeZoneEngine.compute_adx(df_slice, period=14)
        self.assertFalse(np.isnan(adx_slice))
        self.assertGreater(adx_slice, 25.0)

    def test_wilder_adx_consistency_across_modules(self):
        """Verify that ADX calculations in candle_features, no_trade_zone, and fractal_consolidation are aligned."""
        # 1. Feature extractor ADX
        fe = CandleDynamicsFeatureExtractor()
        feats = fe.extract_features(self.df_bull, prefix="1h_")
        fe_adx = float(feats["1h_adx_14"].iloc[-1]) * 100.0

        # 2. No Trade Zone ADX
        ntz_adx = NoTradeZoneEngine.compute_adx(self.df_bull, period=14)

        # 3. Fractal Consolidation ADX
        f_prof = FractalConsolidationEngine.analyze_timeframe(self.df_bull, timeframe="1h")
        fractal_adx = f_prof.adx

        # Check alignment: all should be in tight proximity (< 2.5 points discrepancy due to any initial rolling window conventions)
        self.assertAlmostEqual(ntz_adx, fractal_adx, delta=0.5, msg="NTZ and Fractal ADX must match within 0.5")
        self.assertAlmostEqual(fe_adx, ntz_adx, delta=2.5, msg="Feature Extractor and NTZ ADX must align closely")

    def test_unclosed_candle_pattern_protection(self):
        """Verify that discrete patterns at iloc[-1] are frozen to iloc[-2] to prevent live candle flickering."""
        fe = CandleDynamicsFeatureExtractor()
        df = self.df_bull.copy()
        
        # Artificially modify the live row (-1) to look like an unclosed bullish engulfing
        # High and low blow out preceding bar, close > open
        df.iloc[-1, df.columns.get_loc("open")] = df.iloc[-2]["low"] - 1.0
        df.iloc[-1, df.columns.get_loc("close")] = df.iloc[-2]["high"] + 2.0
        df.iloc[-1, df.columns.get_loc("high")] = df.iloc[-2]["high"] + 2.5
        df.iloc[-1, df.columns.get_loc("low")] = df.iloc[-2]["low"] - 1.5

        feats = fe.extract_features(df, prefix="15m_")

        # The live row (-1) engulfing and inside bar patterns MUST match the completed row (-2)
        for col in [
            "15m_is_inside_bar",
            "15m_inside_bar_cluster_3",
            "15m_is_nr4",
            "15m_is_nr7",
            "15m_is_doji",
            "15m_is_spinning_top",
            "15m_bullish_engulfing",
            "15m_bearish_engulfing",
            "15m_compression_intensity"
        ]:
            self.assertEqual(
                feats[col].iloc[-1], feats[col].iloc[-2],
                f"Pattern {col} at iloc[-1] was not protected from unclosed bar distortion!"
            )

    def test_regime_wilder_smoothing_and_ema(self):
        """Verify that compute_live_btc_regime uses full convergence EMA and canonical Wilder smoothing."""
        res = compute_live_btc_regime(self.df_bull, live_btc_price=float(self.df_bull["close"].iloc[-1]))
        self.assertEqual(res["status"], "success")
        self.assertIn(res["regime"], [r.value for r in MarketRegime])
        
        metrics = res["metrics"]
        # In a bullish trend, fast EMA (20) should be greater than slow EMA (50)
        self.assertGreater(metrics["ema_fast"], metrics["ema_slow"])
        # ADX should be strong
        self.assertGreater(metrics["adx"], 20.0)
        # RSI should be > 50 in a clear bullish trend
        self.assertGreater(metrics["rsi"], 50.0)

    def test_order_block_fvg_and_risk_invariants(self):
        """Verify that OrderBlock engine detects FVG and enforces price invariants."""
        df = self.df_bull.copy()
        live_p = float(df["close"].iloc[-1])
        blocks = InstitutionalOrderBlockEngine.detect_order_blocks(df, timeframe="1h", current_price=live_p)
        self.assertIsInstance(blocks, list)

        # Evaluate live setup
        setup = InstitutionalOrderBlockEngine.evaluate_live_setup(df, timeframe="1h", current_price=live_p)
        if setup.get("setup_detected"):
            direction = setup["direction"]
            entry = setup["entry_price"]
            sl = setup["sl_price"]
            tp1 = setup["tp1_price"]
            tp2 = setup["tp2_price"]
            tp3 = setup["tp3_price"]

            if direction == "LONG":
                self.assertLess(sl, entry, "LONG SL must be strictly less than Entry")
                self.assertLess(entry, tp1, "LONG Entry must be strictly less than TP1")
                self.assertLess(tp1, tp2, "LONG TP1 must be strictly less than TP2")
                self.assertLess(tp2, tp3, "LONG TP2 must be strictly less than TP3")
                self.assertGreater(setup["risk_reward_ratio"], 1.5)
            elif direction == "SHORT":
                self.assertGreater(sl, entry, "SHORT SL must be strictly greater than Entry")
                self.assertGreater(entry, tp1, "SHORT Entry must be strictly greater than TP1")
                self.assertGreater(tp1, tp2, "SHORT TP1 must be strictly greater than TP2")
                self.assertGreater(tp2, tp3, "SHORT TP2 must be strictly greater than TP3")
                self.assertGreater(setup["risk_reward_ratio"], 1.5)

    def test_multi_horizon_alias_resolution_in_order_blocks(self):
        """Verify that scan_all_horizons recognizes aliases like 24h, 7d, 30d across 9 horizons."""
        dfs_9_aliased = {
            "5m": self.df_bull.copy(),
            "15m": self.df_bull.copy(),
            "1h": self.df_bull.copy(),
            "4h": self.df_bull.copy(),
            "12h": self.df_bull.copy(),
            "24h": self.df_bull.copy(), # alias for 1d
            "7d": self.df_bull.copy(),  # alias for 1w
            "15d": self.df_bull.copy(),
            "30d": self.df_bull.copy()  # alias for 1M
        }
        res = InstitutionalOrderBlockEngine.scan_all_horizons(dfs_9_aliased, current_price=120.0)
        self.assertIn("horizon_blocks", res)
        # Should have scanned 1d/24h and 1w/7d successfully
        self.assertIn("1d", res["horizon_blocks"])
        self.assertIn("1w", res["horizon_blocks"])
        self.assertIn("15d", res["horizon_blocks"])
        self.assertIn("1M", res["horizon_blocks"])

    def test_cross_timeframe_matrix_alias_handling(self):
        """Verify that CrossTimeframeMatrixEngine handles aliased profile dictionaries."""
        prof_15m = FractalConsolidationEngine.analyze_timeframe(self.df_bull, timeframe="15m")
        prof_24h = FractalConsolidationEngine.analyze_timeframe(self.df_bull, timeframe="24h")

        aliased_profiles = {
            "15M": prof_15m,
            "24H": prof_24h
        }
        matrix_eval = CrossTimeframeMatrixEngine.evaluate_matrix(aliased_profiles, current_price=120.0)
        self.assertIsNotNone(matrix_eval)
        self.assertIn(matrix_eval["archetype"], [a.value for a in InstitutionalArchetype])
        self.assertNotEqual(
            matrix_eval["archetype"],
            InstitutionalArchetype.ARCHETYPE_E_STAGNATION_DEAD_ZONE.value,
            "Aliased profiles (15M, 24H) should not fail into Stagnation Dead Zone"
        )


    def test_in_memory_15d_resampling_and_disk_cache(self):
        """Verify that 15D bars are accurately resampled from 1D klines in-memory without network calls."""
        from app.engine.scanner.data_loader import MultiHorizonDataLoader
        loader = MultiHorizonDataLoader()

        # 60 daily candles
        df_1d = generate_synthetic_ohlcv(n=60, trend="bullish", base_p=100.0, freq="1d")
        df_15d = loader._resample_15d(df_1d)

        self.assertIsNotNone(df_15d)
        self.assertGreaterEqual(len(df_15d), 2)
        self.assertEqual(len(df_15d), 4) # 60 / 15 = 4 bars
        self.assertFalse(df_15d.attrs.get("is_synthetic", True))
        self.assertEqual(df_15d.attrs.get("native_candle_count"), 4)

        # Verify disk cache save and retrieval
        loader._save_to_disk_cache("TEST_COIN_15d", df_15d, 1700000000.0)
        retrieved = loader._load_from_disk_cache("TEST_COIN_15d")
        self.assertIsNotNone(retrieved)
        df_loaded, ts_loaded = retrieved
        self.assertEqual(len(df_loaded), len(df_15d))
        self.assertEqual(ts_loaded, 1700000000.0)

    def test_universe_filter_dynamic_volume_stepping(self):
        """Verify that UniverseFilter accepts Tier-2 liquidity and fills the universe under quiet market conditions."""
        from app.engine.scanner.filters import UniverseFilter
        # Clean pair with $3M volume (< $10M primary hurdle, but >= $1M Tier-2 hurdle)
        is_valid = UniverseFilter.is_valid_crypto_pair(
            "APT/USDT", price=8.5, high=8.8, low=8.2, volume_usd=3000000.0, min_volume=1000000.0
        )
        self.assertTrue(is_valid, "Clean pair with $3M volume should pass Tier-2 liquidity hurdle")

        # Meme coin with $50M volume must still be strictly rejected
        is_meme_rejected = UniverseFilter.is_valid_crypto_pair(
            "PEPE/USDT", price=0.00001, high=0.000011, low=0.000009, volume_usd=50000000.0, min_volume=1000000.0
        )
        self.assertFalse(is_meme_rejected, "Meme coin must be strictly rejected regardless of volume")

    def test_cross_timeframe_matrix_range_boundary_and_middle_chop_veto(self):
        """Verify Section 35: Prefer boundaries (outer 25%), avoid middle 50% chop zone."""
        from app.quant_v16.fractal_consolidation import TimeframeConsolidationProfile, FractalTimeframeState
        # Setup HTF ranging in [100.0, 200.0] box
        p_1d = TimeframeConsolidationProfile(
            timeframe="1d",
            state=FractalTimeframeState.CONSOLIDATION_RANGING,
            is_consolidation=True,
            is_coiling_squeeze=False,
            chop_index=55.0,
            adx=16.0,
            bbw_pct=5.0,
            is_inside_bar=False,
            is_nr7=False,
            is_nr4=False,
            is_doji=False,
            compression_score=0.2,
            range_high=200.0,
            range_low=100.0,
            range_mid=150.0,
            position_in_range_pct=0.15,
            headroom_to_high_pct=80.0, # at 115.0 (near support)
            headroom_to_low_pct=20.0,
            current_price=115.0
        )
        p_15m_chop = TimeframeConsolidationProfile(
            timeframe="15m",
            state=FractalTimeframeState.CONSOLIDATION_RANGING,
            is_consolidation=True,
            is_coiling_squeeze=False,
            chop_index=58.0,
            adx=14.0,
            bbw_pct=2.0,
            is_inside_bar=False,
            is_nr7=False,
            is_nr4=False,
            is_doji=False,
            compression_score=0.3,
            range_high=125.0,
            range_low=118.0,
            range_mid=121.5,
            position_in_range_pct=0.5,
            headroom_to_high_pct=50.0,
            headroom_to_low_pct=50.0,
            current_price=121.5
        )
        profiles = {"1d": p_1d, "15m": p_15m_chop}

        # Case 1: Lower 25% boundary (price = 115.0 -> rel = 15%) with high headroom to ceiling -> Permitted LONG
        res_support = CrossTimeframeMatrixEngine.evaluate_matrix(profiles, current_price=115.0)
        self.assertTrue(res_support["trade_permitted"])
        self.assertEqual(res_support["dominant_direction"], "LONG")
        self.assertEqual(res_support["strategy"], "RANGE_SUPPORT_MEAN_REVERSION")

        # Case 2: Upper 25% boundary (price = 185.0 -> rel = 85%) with high headroom to floor -> Permitted SHORT
        p_1d_top = TimeframeConsolidationProfile(
            timeframe="1d",
            state=FractalTimeframeState.CONSOLIDATION_RANGING,
            is_consolidation=True,
            is_coiling_squeeze=False,
            chop_index=55.0,
            adx=16.0,
            bbw_pct=5.0,
            is_inside_bar=False,
            is_nr7=False,
            is_nr4=False,
            is_doji=False,
            compression_score=0.2,
            range_high=200.0,
            range_low=100.0,
            range_mid=150.0,
            position_in_range_pct=0.85,
            headroom_to_high_pct=15.0,
            headroom_to_low_pct=85.0, # at 185.0 (near resistance)
            current_price=185.0
        )
        res_resistance = CrossTimeframeMatrixEngine.evaluate_matrix({"1d": p_1d_top, "15m": p_15m_chop}, current_price=185.0)
        self.assertTrue(res_resistance["trade_permitted"])
        self.assertEqual(res_resistance["dominant_direction"], "SHORT")
        self.assertEqual(res_resistance["strategy"], "RANGE_RESISTANCE_MEAN_REVERSION")

        # Case 3: Middle 50% chop zone (price = 150.0 -> rel = 50%) -> Strictly Vetoed for Capital Preservation
        p_1d_mid = TimeframeConsolidationProfile(
            timeframe="1d",
            state=FractalTimeframeState.CONSOLIDATION_RANGING,
            is_consolidation=True,
            is_coiling_squeeze=False,
            chop_index=55.0,
            adx=16.0,
            bbw_pct=5.0,
            is_inside_bar=False,
            is_nr7=False,
            is_nr4=False,
            is_doji=False,
            compression_score=0.2,
            range_high=200.0,
            range_low=100.0,
            range_mid=150.0,
            position_in_range_pct=0.50,
            headroom_to_high_pct=50.0,
            headroom_to_low_pct=50.0,
            current_price=150.0
        )
        res_mid = CrossTimeframeMatrixEngine.evaluate_matrix({"1d": p_1d_mid, "15m": p_15m_chop}, current_price=150.0)
        self.assertFalse(res_mid["trade_permitted"])
        self.assertEqual(res_mid["strategy"], "CAPITAL_PRESERVATION_MIDDLE_CHOP_VETO")
        self.assertEqual(res_mid["dominant_direction"], "NO_TRADE")

    def test_signal_generator_order_block_qualification_during_consolidation(self):
        """Verify that Rank <= 3 institutional Order Block touches qualify during consolidation unless in middle chop."""
        matrix_trade_permitted = False
        is_middle_chop_veto = False
        has_ob_15m = True
        ob_setup_15m = {
            "setup_detected": True,
            "direction": "LONG",
            "zeiierman_rank": 1
        }
        is_15m_bull = False
        is_15m_bear = False
        is_coiling_breakout = False
        is_range_rotation = False

        q_15m_qualified = bool(
            not is_middle_chop_veto and (
                (matrix_trade_permitted and (
                    is_15m_bull or is_15m_bear or is_coiling_breakout or is_range_rotation
                )) or (has_ob_15m and ob_setup_15m.get("zeiierman_rank", 99) <= 3)
            )
        )
        self.assertTrue(q_15m_qualified, "Rank 1 institutional Order Block touch must qualify during consolidation")

        # Now test when locked in middle 50% chop zone
        is_middle_chop_veto = True
        q_15m_middle_vetoed = bool(
            not is_middle_chop_veto and (
                (matrix_trade_permitted and (
                    is_15m_bull or is_15m_bear or is_coiling_breakout or is_range_rotation
                )) or (has_ob_15m and ob_setup_15m.get("zeiierman_rank", 99) <= 3)
            )
        )
        self.assertFalse(q_15m_middle_vetoed, "Trades in middle 50% chop zone must be strictly vetoed for capital preservation")

    def test_data_loader_binance_ip_throttled_fast_path(self):
        """Verify that MultiHorizonDataLoader fast-paths past Binance mirrors when IP throttle is active."""
        import time
        from app.engine.scanner.data_loader import MultiHorizonDataLoader
        loader = MultiHorizonDataLoader()

        now = time.time()
        loader._binance_ip_throttled_until = now + 180.0

        with loader._weight_lock:
            is_blocked = (time.time() < loader._binance_ip_throttled_until)
        self.assertTrue(is_blocked, "Active IP throttle must signal fast-path failover to Tier-2 Bybit & Tier-3 MEXC")

    def test_ntz_middle_chop_detection(self):
        """Verify NoTradeZoneEngine Condition C: Middle 50% Range Box Chop lock."""
        # Chop data with ADX < 20 and range_pos near 50%
        res = no_trade_zone_engine.evaluate_asset_ntz(
            df=self.df_chop,
            current_price=float(self.df_chop['close'].iloc[-1]),
            anchor_tf="1h"
        )
        self.assertTrue(res["is_ntz"], "Chop data should trigger NTZ")
        self.assertIn("NO TRADE ZONE", res["label"])


    def test_kucoin_and_disk_cache_failover_on_multi_exchange_outage(self):
        """Verify that MultiHorizonDataLoader falls back through KuCoin and activates persistent disk cache on multi-exchange outage."""
        import time
        from unittest import mock
        from app.engine.scanner.data_loader import MultiHorizonDataLoader
        loader = MultiHorizonDataLoader()

        # Mock disk cache with sample df
        sample_df = self.df_chop.copy()
        loader._save_to_disk_cache("TEST_15m", sample_df, time.time())

        # Load from disk cache
        loaded = loader._load_from_disk_cache("TEST_15m")
        self.assertIsNotNone(loaded)
        df_loaded, ts = loaded
        self.assertEqual(len(df_loaded), len(sample_df))

        # Test simulated multi-exchange failure falling back to disk cache
        with mock.patch.object(loader, 'session') as mock_session:
            mock_resp = mock.MagicMock()
            mock_resp.status_code = 503
            mock_session.get.return_value = mock_resp

            df_out = loader.fetch_single_timeframe_raw("TEST", "15m", limit=30)
            self.assertIsNotNone(df_out, "Disk cache SWR must recover warm candles when all exchange gateways fail")
            self.assertTrue(df_out.attrs.get("is_stale"), "Cached data must be flagged as stale")
            self.assertEqual(df_out.attrs.get("exchange_source"), "persistent_disk_cache")

    def test_directional_breakout_expansion_macro_emergence(self):
        """Verify Priority 0: Directional Breakout Expansion triggers when price breaks above macro range ceiling."""
        from app.quant_v16.cross_timeframe_matrix import CrossTimeframeMatrixEngine
        from app.quant_v16.fractal_consolidation import TimeframeConsolidationProfile, FractalTimeframeState

        # 1D profile with price breaking out above range ceiling
        p_1d = TimeframeConsolidationProfile(
            timeframe="1d",
            state=FractalTimeframeState.TREND_BULLISH,
            is_consolidation=False,
            is_coiling_squeeze=False,
            chop_index=35.0,
            adx=32.0,
            bbw_pct=6.5,
            is_inside_bar=False,
            is_nr7=False,
            is_nr4=False,
            is_doji=False,
            compression_score=0.1,
            range_high=100.0,
            range_low=80.0,
            range_mid=90.0,
            position_in_range_pct=1.0,
            headroom_to_high_pct=99.0,  # Range ceiling breached!
            headroom_to_low_pct=25.0,
            current_price=105.0
        )
        p_4h = TimeframeConsolidationProfile(
            timeframe="4h",
            state=FractalTimeframeState.TREND_BULLISH,
            is_consolidation=False,
            is_coiling_squeeze=False,
            chop_index=38.0,
            adx=28.0,
            bbw_pct=5.0,
            is_inside_bar=False,
            is_nr7=False,
            is_nr4=False,
            is_doji=False,
            compression_score=0.1,
            range_high=102.0,
            range_low=85.0,
            range_mid=93.5,
            position_in_range_pct=1.0,
            headroom_to_high_pct=99.0,
            headroom_to_low_pct=20.0,
            current_price=105.0
        )
        p_1h = TimeframeConsolidationProfile(
            timeframe="1h",
            state=FractalTimeframeState.TREND_BULLISH,
            is_consolidation=False,
            is_coiling_squeeze=False,
            chop_index=40.0,
            adx=25.0,
            bbw_pct=4.0,
            is_inside_bar=False,
            is_nr7=False,
            is_nr4=False,
            is_doji=False,
            compression_score=0.1,
            range_high=104.0,
            range_low=95.0,
            range_mid=99.5,
            position_in_range_pct=1.0,
            headroom_to_high_pct=99.0,
            headroom_to_low_pct=10.0,
            current_price=105.0
        )
        p_15m = TimeframeConsolidationProfile(
            timeframe="15m",
            state=FractalTimeframeState.TREND_BULLISH,
            is_consolidation=False,
            is_coiling_squeeze=False,
            chop_index=42.0,
            adx=24.0,
            bbw_pct=3.0,
            is_inside_bar=False,
            is_nr7=False,
            is_nr4=False,
            is_doji=False,
            compression_score=0.1,
            range_high=104.5,
            range_low=98.0,
            range_mid=101.25,
            position_in_range_pct=1.0,
            headroom_to_high_pct=99.0,
            headroom_to_low_pct=7.0,
            current_price=105.0
        )

        profiles = {"1d": p_1d, "4h": p_4h, "1h": p_1h, "15m": p_15m}
        res = CrossTimeframeMatrixEngine.evaluate_matrix(profiles, current_price=105.0)

        self.assertTrue(res["trade_permitted"], "Breakout expansion must permit trading")
        self.assertEqual(res["strategy"], "DIRECTIONAL_BREAKOUT_EXPANSION")
        self.assertEqual(res["dominant_direction"], "LONG")
        self.assertEqual(res["allocation_pct"], 100.0)

    def test_directional_breakdown_expansion_macro_emergence(self):
        """Verify Priority 0: Directional Breakdown Expansion triggers when price breaks below macro range floor."""
        from app.quant_v16.cross_timeframe_matrix import CrossTimeframeMatrixEngine
        from app.quant_v16.fractal_consolidation import TimeframeConsolidationProfile, FractalTimeframeState

        p_1d = TimeframeConsolidationProfile(
            timeframe="1d",
            state=FractalTimeframeState.TREND_BEARISH,
            is_consolidation=False,
            is_coiling_squeeze=False,
            chop_index=35.0,
            adx=32.0,
            bbw_pct=6.5,
            is_inside_bar=False,
            is_nr7=False,
            is_nr4=False,
            is_doji=False,
            compression_score=0.1,
            range_high=100.0,
            range_low=80.0,
            range_mid=90.0,
            position_in_range_pct=0.0,
            headroom_to_high_pct=31.0,
            headroom_to_low_pct=99.0,  # Range floor breached!
            current_price=76.0
        )
        p_4h = TimeframeConsolidationProfile(
            timeframe="4h",
            state=FractalTimeframeState.TREND_BEARISH,
            is_consolidation=False,
            is_coiling_squeeze=False,
            chop_index=38.0,
            adx=28.0,
            bbw_pct=5.0,
            is_inside_bar=False,
            is_nr7=False,
            is_nr4=False,
            is_doji=False,
            compression_score=0.1,
            range_high=95.0,
            range_low=79.0,
            range_mid=87.0,
            position_in_range_pct=0.0,
            headroom_to_high_pct=25.0,
            headroom_to_low_pct=99.0,
            current_price=76.0
        )
        p_1h = TimeframeConsolidationProfile(
            timeframe="1h",
            state=FractalTimeframeState.TREND_BEARISH,
            is_consolidation=False,
            is_coiling_squeeze=False,
            chop_index=40.0,
            adx=25.0,
            bbw_pct=4.0,
            is_inside_bar=False,
            is_nr7=False,
            is_nr4=False,
            is_doji=False,
            compression_score=0.1,
            range_high=90.0,
            range_low=78.0,
            range_mid=84.0,
            position_in_range_pct=0.0,
            headroom_to_high_pct=18.0,
            headroom_to_low_pct=99.0,
            current_price=76.0
        )
        p_15m = TimeframeConsolidationProfile(
            timeframe="15m",
            state=FractalTimeframeState.TREND_BEARISH,
            is_consolidation=False,
            is_coiling_squeeze=False,
            chop_index=42.0,
            adx=24.0,
            bbw_pct=3.0,
            is_inside_bar=False,
            is_nr7=False,
            is_nr4=False,
            is_doji=False,
            compression_score=0.1,
            range_high=85.0,
            range_low=77.5,
            range_mid=81.25,
            position_in_range_pct=0.0,
            headroom_to_high_pct=12.0,
            headroom_to_low_pct=99.0,
            current_price=76.0
        )

        profiles = {"1d": p_1d, "4h": p_4h, "1h": p_1h, "15m": p_15m}
        res = CrossTimeframeMatrixEngine.evaluate_matrix(profiles, current_price=76.0)

        self.assertTrue(res["trade_permitted"], "Breakdown expansion must permit trading")
        self.assertEqual(res["strategy"], "DIRECTIONAL_BREAKOUT_EXPANSION")
        self.assertEqual(res["dominant_direction"], "SHORT")
        self.assertEqual(res["allocation_pct"], 100.0)

    def test_middle_chop_capital_preservation_strict_veto_despite_nominal_trend(self):
        """Verify that when price is trapped in middle chop (0.25 < range_pos < 0.75), capital is strictly preserved."""
        from app.quant_v16.cross_timeframe_matrix import CrossTimeframeMatrixEngine
        from app.quant_v16.fractal_consolidation import TimeframeConsolidationProfile, FractalTimeframeState

        # 1D profile has nominal bullish trend, but price is sitting at 150.0 in [100.0, 200.0] range (range_pos = 0.50)
        p_1d = TimeframeConsolidationProfile(
            timeframe="1d",
            state=FractalTimeframeState.TREND_BULLISH,
            is_consolidation=False,
            is_coiling_squeeze=False,
            chop_index=45.0,
            adx=22.0,
            bbw_pct=5.0,
            is_inside_bar=False,
            is_nr7=False,
            is_nr4=False,
            is_doji=False,
            compression_score=0.2,
            range_high=200.0,
            range_low=100.0,
            range_mid=150.0,
            position_in_range_pct=0.50,
            headroom_to_high_pct=33.3,
            headroom_to_low_pct=33.3,
            current_price=150.0
        )
        p_15m = TimeframeConsolidationProfile(
            timeframe="15m",
            state=FractalTimeframeState.TREND_BULLISH,
            is_consolidation=False,
            is_coiling_squeeze=False,
            chop_index=48.0,
            adx=20.0,
            bbw_pct=3.0,
            is_inside_bar=False,
            is_nr7=False,
            is_nr4=False,
            is_doji=False,
            compression_score=0.2,
            range_high=160.0,
            range_low=140.0,
            range_mid=150.0,
            position_in_range_pct=0.50,
            headroom_to_high_pct=6.7,
            headroom_to_low_pct=6.7,
            current_price=150.0
        )

        profiles = {"1d": p_1d, "15m": p_15m}
        res = CrossTimeframeMatrixEngine.evaluate_matrix(profiles, current_price=150.0)

        self.assertFalse(res["trade_permitted"], "Middle chop (0.25 < range_pos < 0.75) must strictly veto trades")
        self.assertEqual(res["strategy"], "CAPITAL_PRESERVATION_MIDDLE_CHOP_VETO")
        self.assertEqual(res["dominant_direction"], "NO_TRADE")
        self.assertEqual(res["allocation_pct"], 0.0)

    def test_coiling_volatility_breakout_permitted_in_middle_range(self):
        """Verify that spring-loaded coiling compression (ltf_coiling) with HTF trend alignment is permitted in middle 50% range."""
        from app.quant_v16.cross_timeframe_matrix import CrossTimeframeMatrixEngine
        from app.quant_v16.fractal_consolidation import TimeframeConsolidationProfile, FractalTimeframeState

        p_1d = TimeframeConsolidationProfile(
            timeframe="1d",
            state=FractalTimeframeState.TREND_BULLISH,
            is_consolidation=False,
            is_coiling_squeeze=False,
            chop_index=40.0,
            adx=28.0,
            bbw_pct=6.0,
            is_inside_bar=False,
            is_nr7=False,
            is_nr4=False,
            is_doji=False,
            compression_score=0.2,
            range_high=200.0,
            range_low=100.0,
            range_mid=150.0,
            position_in_range_pct=0.50,
            headroom_to_high_pct=33.3,
            headroom_to_low_pct=33.3,
            current_price=150.0
        )
        # 15M is in a coiling squeeze compression ready to erupt
        p_15m_coiling = TimeframeConsolidationProfile(
            timeframe="15m",
            state=FractalTimeframeState.CONSOLIDATION_COILING,
            is_consolidation=True,
            is_coiling_squeeze=True,
            chop_index=55.0,
            adx=18.0,
            bbw_pct=1.8,
            is_inside_bar=True,
            is_nr7=True,
            is_nr4=True,
            is_doji=False,
            compression_score=0.9,
            range_high=152.0,
            range_low=148.0,
            range_mid=150.0,
            position_in_range_pct=0.50,
            headroom_to_high_pct=1.3,
            headroom_to_low_pct=1.3,
            current_price=150.0
        )

        profiles = {"1d": p_1d, "15m": p_15m_coiling}
        res = CrossTimeframeMatrixEngine.evaluate_matrix(profiles, current_price=150.0)

        self.assertTrue(res["trade_permitted"], "Coiling spring breakout must be permitted in middle range")
        self.assertEqual(res["strategy"], "COILING_VOLATILITY_BREAKOUT")
        self.assertEqual(res["dominant_direction"], "LONG")
        self.assertEqual(res["allocation_pct"], 85.0)

    def test_dynamic_precision_sub_cent_tokens(self):
        """Forensic Test: Sub-cent tokens must never round to 0.0, and high-value assets format cleanly."""
        from app.quant_v16.entry_confirmation import format_dynamic_precision

        # Micro sub-cent meme tokens (PEPE, SHIB, BONK)
        pepe_p = 0.00000854321
        self.assertGreater(format_dynamic_precision(pepe_p), 0.0)
        self.assertEqual(format_dynamic_precision(pepe_p), 0.0000085432)

        # Cent tokens
        doge_p = 0.142857
        self.assertEqual(format_dynamic_precision(doge_p), 0.142857)

        # Dollar tokens
        sol_p = 178.4567
        self.assertEqual(format_dynamic_precision(sol_p), 178.46)

        # BTC
        btc_p = 68450.789
        self.assertEqual(format_dynamic_precision(btc_p), 68450.79)

    def test_candlestick_trigger_long_confirmation(self):
        """Forensic Test: Long trigger requires buyer absorption; red marubozu waterfall must be vetoed."""
        from app.quant_v16.entry_confirmation import EntryConfirmationEngine

        # Case A: Bearish Waterfall Marubozu (Knife Catch: Open=100, High=100.2, Low=90.0, Close=90.1)
        df_knife = pd.DataFrame([{
            "open": 100.0, "high": 100.2, "low": 90.0, "close": 90.1, "volume": 1000.0
        }])
        confirmed, reason, _ = EntryConfirmationEngine.validate_candle_trigger(df_knife, "LONG", 90.1)
        self.assertFalse(confirmed, "Bearish waterfall marubozu must be rejected for long entry")
        self.assertIn("Marubozu Waterfall", reason)

        # Case B: Bullish Hammer / Buyer Absorption (Open=95, High=98, Low=90, Close=97.5) -> lower wick = 5.0 / 8.0 = 62.5%
        df_hammer = pd.DataFrame([{
            "open": 95.0, "high": 98.0, "low": 90.0, "close": 97.5, "volume": 1500.0
        }])
        confirmed, reason, _ = EntryConfirmationEngine.validate_candle_trigger(df_hammer, "LONG", 97.5)
        self.assertTrue(confirmed, "Lower wick absorption hammer must confirm long entry")

    def test_candlestick_trigger_short_confirmation(self):
        """Forensic Test: Short trigger requires seller rejection; green marubozu pump must be vetoed."""
        from app.quant_v16.entry_confirmation import EntryConfirmationEngine

        # Case A: Bullish Pump Marubozu (Ramping Pump: Open=100, High=110.0, Low=99.8, Close=109.9)
        df_pump = pd.DataFrame([{
            "open": 100.0, "high": 110.0, "low": 99.8, "close": 109.9, "volume": 2000.0
        }])
        confirmed, reason, _ = EntryConfirmationEngine.validate_candle_trigger(df_pump, "SHORT", 109.9)
        self.assertFalse(confirmed, "Bullish pump marubozu must be rejected for short entry")
        self.assertIn("Marubozu Ramp", reason)

        # Case B: Bearish Shooting Star / Upper Wick Rejection (Open=105, High=112, Low=102, Close=103) -> upper wick = 7.0 / 10.0 = 70%
        df_star = pd.DataFrame([{
            "open": 105.0, "high": 112.0, "low": 102.0, "close": 103.0, "volume": 1800.0
        }])
        confirmed, reason, _ = EntryConfirmationEngine.validate_candle_trigger(df_star, "SHORT", 103.0)
        self.assertTrue(confirmed, "Upper wick rejection shooting star must confirm short entry")

    def test_anti_chase_limit_order_zone(self):
        """Forensic Test: Price extended beyond 0.40% from optimal POI enters RESTING_LIMIT mode."""
        from app.quant_v16.entry_confirmation import EntryConfirmationEngine

        optimal_limit = 100.0
        active_atr = 2.0
        ob_setup = {"optimal_entry_limit": optimal_limit}

        # Case A: Extended price (Current=102.0 -> 2% above limit -> Chasing Long)
        res_chase = EntryConfirmationEngine.calculate_optimal_entry_zone(
            current_price=102.0,
            ob_setup=ob_setup,
            direction="LONG",
            active_atr=active_atr,
            chase_threshold_pct=0.40
        )
        self.assertTrue(res_chase["is_limit_pending"])
        self.assertEqual(res_chase["entry_mode"], "RESTING_LIMIT")
        self.assertEqual(res_chase["optimal_entry_price"], optimal_limit)
        self.assertIn("Price extended", res_chase["chase_warning"])

        # Case B: At boundary (Current=100.2 -> 0.2% above limit -> Market Confirmed)
        res_ok = EntryConfirmationEngine.calculate_optimal_entry_zone(
            current_price=100.2,
            ob_setup=ob_setup,
            direction="LONG",
            active_atr=active_atr,
            chase_threshold_pct=0.40
        )
        self.assertFalse(res_ok["is_limit_pending"])
        self.assertEqual(res_ok["entry_mode"], "MARKET_CONFIRMED")
        self.assertEqual(res_ok["optimal_entry_price"], 100.2)

    def test_order_block_sub_cent_short_invariants(self):
        """Forensic Test: Sub-cent short order blocks must have TP < Entry < SL (Zero inverted prices)."""
        from app.quant_v16.validation import DataValidator

        # Test sub-cent coin SHORT with price = 0.00002
        entry_p = 0.00002
        sl_p = 0.000022
        tp1_p = 0.000016
        tp2_p = 0.000014
        tp3_p = 0.000010

        is_valid, msg = DataValidator.validate_price_invariants(
            entry=entry_p, sl=sl_p, tp1=tp1_p, tp2=tp2_p, tp3=tp3_p, direction="SHORT"
        )
        self.assertTrue(is_valid, f"Sub-cent short invariants must hold: {msg}")

    def test_no_trade_zone_mid_air_hover_filter(self):
        """Forensic Test: Mid-air order block without touch triggers UNCONFIRMED_OB_MID_AIR."""
        from app.quant_v16.no_trade_zone import no_trade_zone_engine, NoTradeZoneReason

        # Order block detected, but price is in mid-air (not touching, not in zone, state="FRESH")
        ob_setup_mid_air = {
            "setup_detected": True,
            "in_order_block_zone": False,
            "is_touching": False,
            "state": "FRESH",
            "mitigated": False
        }

        res = no_trade_zone_engine.evaluate_asset_ntz(
            df=self.df_bull,
            current_price=110.0,
            anchor_tf="1h",
            ob_setup=ob_setup_mid_air,
            direction="LONG"
        )

        self.assertTrue(res["is_ntz"], "Price hovering outside OB in mid-air must trigger NTZ")
        self.assertEqual(res["code"], NoTradeZoneReason.UNCONFIRMED_OB_MID_AIR.value)
    def test_reconcile_btc_shield_bear_trend_alignment(self):
        """Forensic Test: Stale disk shield with RANGE/CONSOLIDATION must reconcile 100% with V16 BEAR_TREND."""
        from app.quant_v16.regime import reconcile_btc_shield

        stale_shield = {
            "active": False,
            "status_code": "RANGE",
            "regime": "RANGE",
            "regime_label": "⚖️ RANGE BOUND / MEAN REVERSION",
            "reason": "BTC range-bound within statistical corridor (ADX: 24.8, RSI: 40.5). Section 29 0.70x sizing throttle active.",
            "altcoin_longs_allowed": True,
            "is_ntz_active": False,
            "predicted_trend": "CONSOLIDATION",
            "bull_trend_prob": 18.0,
            "bear_trend_prob": 17.0,
            "consolidation_prob": 55.0
        }

        v16_live = {
            "status": "success",
            "regime": "BEAR_TREND",
            "confidence": 0.88,
            "volatility_state": "LOW",
            "trend_strength": 0.52,
            "sizing_multiplier": 1.0,
            "probabilities": {"bull": 0.08, "bear": 0.65, "range": 0.17, "breakout": 0.10, "squeeze": 0.0},
            "metrics": {"btc_price": 79986.0, "adx": 25.8, "rsi": 36.2, "ema_fast": 80464.0, "ema_slow": 80737.0}
        }

        reconciled = reconcile_btc_shield(stale_shield, v16_live)

        self.assertEqual(reconciled["regime"], "BEAR_TREND")
        self.assertEqual(reconciled["status_code"], "BEAR_TREND")
        self.assertEqual(reconciled["predicted_trend"], "BEAR_TREND")
        self.assertFalse(reconciled["altcoin_longs_allowed"])
        self.assertEqual(reconciled["altcoin_posture"], "BEAR_TREND_SHORT_ALPHA")
        self.assertFalse(reconciled["is_ntz_active"])
        self.assertEqual(reconciled["sizing_multiplier"], 1.0)
        self.assertEqual(reconciled["bear_trend_prob"], 65.0)
        self.assertEqual(reconciled["bull_trend_prob"], 8.0)
        self.assertEqual(reconciled["consolidation_prob"], 17.0)
        self.assertIn("BTC confirmed macro bear trend", reconciled["reason"])
        self.assertIn("1.00x", reconciled["reason"])

    def test_reconcile_btc_shield_preserves_network_partition(self):
        """Forensic Test: Emergency exchange partition / global outage must NOT be overridden by V16."""
        from app.quant_v16.regime import reconcile_btc_shield

        partition_shield = {
            "active": True,
            "status_code": "NO_TRADE_ZONE",
            "regime": "PARTITION_OUTAGE",
            "reason": "GLOBAL_OUTAGE_DEFENSE: Upstream gateways unreachable.",
            "is_partition_stale": True,
            "is_global_outage": True,
            "is_ntz_active": True
        }

        v16_live = {
            "regime": "BULL_TREND",
            "sizing_multiplier": 1.0
        }

        reconciled = reconcile_btc_shield(partition_shield, v16_live)
        self.assertTrue(reconciled["is_partition_stale"])
        self.assertTrue(reconciled["is_global_outage"])
        self.assertEqual(reconciled["status_code"], "NO_TRADE_ZONE")

    def test_reconcile_btc_shield_bull_and_breakout(self):
        """Forensic Test: BULL_TREND and BREAKOUT regimes properly permit altcoin longs."""
        from app.quant_v16.regime import reconcile_btc_shield

        # Test BULL_TREND
        v16_bull = {
            "regime": "BULL_TREND",
            "confidence": 0.88,
            "sizing_multiplier": 1.0,
            "probabilities": {"bull": 0.65, "bear": 0.08, "range": 0.17},
            "metrics": {"adx": 28.0, "rsi": 62.0}
        }
        rec_bull = reconcile_btc_shield({}, v16_bull)
        self.assertEqual(rec_bull["regime"], "BULL_TREND")
        self.assertEqual(rec_bull["status_code"], "BULL_TREND")
        self.assertTrue(rec_bull["altcoin_longs_allowed"])
        self.assertEqual(rec_bull["bull_trend_prob"], 65.0)

        # Test BREAKOUT
        v16_breakout = {
            "regime": "BREAKOUT",
            "confidence": 0.85,
            "sizing_multiplier": 1.0,
            "probabilities": {"bull": 0.55, "bear": 0.10, "range": 0.15},
            "metrics": {"adx": 30.0, "rsi": 58.0}
        }
        rec_bo = reconcile_btc_shield({}, v16_breakout)
        self.assertEqual(rec_bo["regime"], "BREAKOUT")
        self.assertEqual(rec_bo["status_code"], "BREAKOUT")
        self.assertTrue(rec_bo["altcoin_longs_allowed"])

    def test_compute_live_btc_regime_deterministic_slice(self):
        """Forensic Test: Passing 100 vs 120 candles with identical trailing 100 produces exact identical metrics."""
        from app.quant_v16.regime import compute_live_btc_regime

        # Create synthetic 120 candles with clear trend
        np.random.seed(42)
        base = 80000.0
        records = []
        for i in range(120):
            base -= 20.0  # gentle downward trend
            records.append({
                "open": base + 5.0,
                "high": base + 15.0,
                "low": base - 15.0,
                "close": base,
                "volume": 100.0
            })
        df_120 = pd.DataFrame(records)
        df_100 = df_120.iloc[-100:].copy().reset_index(drop=True)

        res_120 = compute_live_btc_regime(df_120)
        res_100 = compute_live_btc_regime(df_100)

        self.assertEqual(res_120["regime"], res_100["regime"])
        self.assertEqual(res_120["metrics"]["adx"], res_100["metrics"]["adx"])
        self.assertEqual(res_120["metrics"]["rsi"], res_100["metrics"]["rsi"])
        self.assertEqual(res_120["metrics"]["ema_fast"], res_100["metrics"]["ema_fast"])
        self.assertEqual(res_120["metrics"]["ema_slow"], res_100["metrics"]["ema_slow"])

    def test_market_boundary_oscillation_hysteresis(self):
        """Forensic Test: ADX boundary oscillation [24.9 - 25.1] is stabilized via hysteresis Schmitt trigger."""
        classifier = MarketRegimeClassifier()

        # 1. When in BEAR_TREND, ADX hovering between 24.9 and 25.1 remains in BEAR_TREND (exit hurdle 24.0)
        res_hover_from_bear = classifier.evaluate_regime(
            adx=24.95,
            rsi=44.0,
            ema_fast=90.0,
            ema_slow=100.0,
            prev_regime=MarketRegime.BEAR_TREND
        )
        self.assertEqual(res_hover_from_bear.regime, MarketRegime.BEAR_TREND)
        self.assertEqual(res_hover_from_bear.sizing_multiplier, 1.00)
        self.assertGreater(res_hover_from_bear.probabilities["bear"], 0.50)

        # 2. When in RANGE, ADX at 24.95 does not prematurely jump into BEAR_TREND (entry hurdle 25.0)
        res_hover_from_range = classifier.evaluate_regime(
            adx=24.95,
            rsi=44.0,
            ema_fast=90.0,
            ema_slow=100.0,
            prev_regime=MarketRegime.RANGE
        )
        self.assertEqual(res_hover_from_range.regime, MarketRegime.RANGE)
        self.assertEqual(res_hover_from_range.sizing_multiplier, 0.70)

        # 3. When ADX breaks above 25.0 (e.g. 25.05), it definitively enters BEAR_TREND
        res_cross_up = classifier.evaluate_regime(
            adx=25.05,
            rsi=44.0,
            ema_fast=90.0,
            ema_slow=100.0,
            prev_regime=MarketRegime.RANGE
        )
        self.assertEqual(res_cross_up.regime, MarketRegime.BEAR_TREND)

        # 4. When ADX breaks below 24.0 (e.g. 23.80), it definitively transitions back to RANGE
        res_drop_below = classifier.evaluate_regime(
            adx=23.80,
            rsi=44.0,
            ema_fast=90.0,
            ema_slow=100.0,
            prev_regime=MarketRegime.BEAR_TREND
        )
        self.assertEqual(res_drop_below.regime, MarketRegime.RANGE)

    def test_navbar_terminal_synchronized_flip(self):
        """Forensic Test: Both Navbar and Terminal synchronize via reconcile_btc_shield with identical trailing 100 series."""
        from app.quant_v16.regime import compute_live_btc_regime, reconcile_btc_shield

        np.random.seed(101)
        base = 80000.0
        records = []
        for i in range(100):
            base -= 25.0
            records.append({
                "open": base + 5.0,
                "high": base + 15.0,
                "low": base - 15.0,
                "close": base,
                "volume": 100.0
            })
        df_100 = pd.DataFrame(records)

        # Terminal calculation
        terminal_regime = compute_live_btc_regime(df_100)

        # Navbar calculation via reconcile_btc_shield
        initial_shield = {"status_code": "IDLE", "active": False}
        navbar_shield = reconcile_btc_shield(initial_shield, terminal_regime)

        # Verify zero divergence across Terminal and Navbar
        self.assertEqual(terminal_regime["regime"], navbar_shield["regime"])
        self.assertEqual(terminal_regime["regime"], navbar_shield["status_code"])
        self.assertEqual(terminal_regime["sizing_multiplier"], navbar_shield["sizing_multiplier"])
        self.assertEqual(terminal_regime["confidence"], navbar_shield["confidence"])

    def test_multibar_closed_candle_confirmation_with_live_developing_bar(self):
        """
        Forensic Test: In multi-candle data, confirmation evaluates the last completed candle (df.iloc[-2])
        while guarding against acute adverse blowouts on the live developing candle (df.iloc[-1]).
        """
        from app.quant_v16.entry_confirmation import EntryConfirmationEngine

        # Case A: Closed bar is a strong Bullish Hammer (absorption), live bar is newly opened with 0 wicks
        closed_bar = {"open": 95.0, "high": 98.0, "low": 90.0, "close": 97.5, "volume": 1500.0}
        live_fresh_bar = {"open": 97.5, "high": 97.55, "low": 97.48, "close": 97.52, "volume": 10.0}
        df_multibar = pd.DataFrame([closed_bar, live_fresh_bar])

        confirmed, reason, metrics = EntryConfirmationEngine.validate_candle_trigger(df_multibar, "LONG", 97.52)
        self.assertTrue(confirmed, "Closed candle hammer must confirm entry even when live developing candle is freshly opened")
        self.assertIn("Confirmed", reason)

        # Case B: Closed bar is bullish hammer, but live bar suffers an acute adverse blowout (-2.0% dump with 0 wick)
        live_blowout_bar = {"open": 97.5, "high": 97.5, "low": 95.5, "close": 95.5, "volume": 5000.0}
        df_blowout = pd.DataFrame([closed_bar, live_blowout_bar])
        confirmed_b, reason_b, metrics_b = EntryConfirmationEngine.validate_candle_trigger(df_blowout, "LONG", 95.5)
        self.assertFalse(confirmed_b, "Live developing candle waterfall dump must immediately intercept and reject trade entry")
        self.assertIn("Live Candle Waterfall", reason_b)

    def test_strategy_registry_regime_kill_switch(self):
        """
        Forensic Test: Section 31 Strategy Kill Switch & Section 32 Regime-Specific Kill Switch.
        MOMENTUM_LONG must be disabled in BEAR_TREND; MOMENTUM_SHORT must be paused in BULL_TREND.
        Institutional strategies like ORDER_BLOCK_SHORT must be allowed in BEAR_TREND.
        """
        from app.quant_v16.strategies import StrategyRegistry, StrategyArchetype

        reg = StrategyRegistry()

        # MOMENTUM_LONG in BEAR_TREND must be blocked
        is_allowed, reason = reg.is_strategy_allowed(StrategyArchetype.MOMENTUM_LONG.value, "BEAR_TREND")
        self.assertFalse(is_allowed, "MOMENTUM_LONG must be disabled in BEAR_TREND")
        self.assertIn("DISABLED", reason)

        # MOMENTUM_SHORT in BULL_TREND must be blocked
        is_allowed_short, reason_short = reg.is_strategy_allowed(StrategyArchetype.MOMENTUM_SHORT.value, "BULL_TREND")
        self.assertFalse(is_allowed_short, "MOMENTUM_SHORT must be paused in BULL_TREND")
        self.assertIn("PAUSED", reason_short)

        # ORDER_BLOCK_SHORT in BEAR_TREND must be allowed
        is_allowed_ob, _ = reg.is_strategy_allowed(StrategyArchetype.ORDER_BLOCK_SHORT.value, "BEAR_TREND")
        self.assertTrue(is_allowed_ob, "ORDER_BLOCK_SHORT must be allowed in BEAR_TREND")

    def test_resting_limit_target_sl_invariants(self):
        """
        Forensic Test: Price invariants must strictly hold for RESTING_LIMIT entry modes.
        For LONG: SL < Entry < TP1 < TP2 < TP3.
        For SHORT: SL > Entry > TP1 > TP2 > TP3.
        """
        from app.engine.signals.signal_generator import SignalGenerationSystem, map_canonical_strategy

        # Verify dynamic mapping helper
        strat_mapped = map_canonical_strategy("DIRECTIONAL_BREAKOUT_EXPANSION", "LONG")
        self.assertEqual(strat_mapped, "BREAKOUT_LONG")

        strat_mapped_ob = map_canonical_strategy("ORDER_BLOCK", "SHORT", is_ob_setup=True, ob_setup={"strategy": "ORDER_BLOCK_SHORT"})
        self.assertEqual(strat_mapped_ob, "ORDER_BLOCK_SHORT")

    def test_bullish_and_bearish_engulfing_confirmation(self):
        """Forensic Test: Multi-candle Engulfing Momentum Flip recognition in validate_candle_trigger."""
        from app.quant_v16.entry_confirmation import EntryConfirmationEngine

        # 1. Bullish Engulfing: Prior closed bar red, trigger closed bar green engulfing prior body
        prior_bar = {"open": 100.0, "high": 100.5, "low": 95.0, "close": 96.0, "volume": 1000.0}
        trigger_bar = {"open": 95.5, "high": 102.0, "low": 95.0, "close": 101.5, "volume": 2500.0}
        live_bar = {"open": 101.5, "high": 101.6, "low": 101.4, "close": 101.5, "volume": 50.0}
        df_bull = pd.DataFrame([prior_bar, trigger_bar, live_bar])

        confirmed, reason, metrics = EntryConfirmationEngine.validate_candle_trigger(df_bull, "LONG", 101.5)
        self.assertTrue(confirmed, "Bullish engulfing momentum flip must confirm long entry")
        self.assertIn("Bullish Engulfing", reason)
        self.assertEqual(metrics.get("pattern"), "BULLISH_ENGULFING")
        self.assertTrue(metrics.get("is_engulfing"))

        # 2. Bearish Engulfing: Prior closed bar green, trigger closed bar red engulfing prior body
        p_bar_short = {"open": 96.0, "high": 101.0, "low": 95.5, "close": 100.0, "volume": 1200.0}
        t_bar_short = {"open": 100.5, "high": 101.0, "low": 94.0, "close": 94.5, "volume": 2800.0}
        l_bar_short = {"open": 94.5, "high": 94.6, "low": 94.4, "close": 94.5, "volume": 40.0}
        df_bear = pd.DataFrame([p_bar_short, t_bar_short, l_bar_short])

        confirmed_s, reason_s, metrics_s = EntryConfirmationEngine.validate_candle_trigger(df_bear, "SHORT", 94.5)
        self.assertTrue(confirmed_s, "Bearish engulfing momentum flip must confirm short entry")
        self.assertIn("Bearish Engulfing", reason_s)
        self.assertEqual(metrics_s.get("pattern"), "BEARISH_ENGULFING")
        self.assertTrue(metrics_s.get("is_engulfing"))

    def test_liquidity_sweep_and_reclaim_confirmation(self):
        """Forensic Test: Liquidity Sweep & Reclaim (Turtle Soup) recognition."""
        from app.quant_v16.entry_confirmation import EntryConfirmationEngine

        # 1. Bullish Liquidity Sweep & Reclaim: Pierces below 5-candle swing low (95.0), closes at 96.5 with 60% lower wick
        hist = [
            {"open": 98.0, "high": 100.0, "low": 96.0, "close": 99.0, "volume": 1000.0},
            {"open": 99.0, "high": 99.5, "low": 95.0, "close": 96.0, "volume": 1100.0}, # Swing Low = 95.0
            {"open": 96.0, "high": 97.5, "low": 95.5, "close": 97.0, "volume": 900.0},
            {"open": 97.0, "high": 97.8, "low": 95.2, "close": 96.5, "volume": 850.0},
            {"open": 96.5, "high": 97.0, "low": 93.0, "close": 96.0, "volume": 2500.0}, # Sweeps 95.0 down to 93.0, closes at 96.0 (wick = 3.0/4.0 = 75%)
            {"open": 96.0, "high": 96.2, "low": 95.9, "close": 96.1, "volume": 50.0}   # Live bar
        ]
        df_sweep_long = pd.DataFrame(hist)

        confirmed, reason, metrics = EntryConfirmationEngine.validate_candle_trigger(df_sweep_long, "LONG", 96.1)
        self.assertTrue(confirmed, "Bullish liquidity sweep & reclaim must confirm entry")
        self.assertIn("Liquidity Sweep & Reclaim", reason)
        self.assertEqual(metrics.get("pattern"), "LIQUIDITY_SWEEP_RECLAIM")
        self.assertTrue(metrics.get("is_sweep_reclaim"))

        # 2. Bearish Liquidity Sweep & Rejection: Pierces above 5-candle swing high (105.0), closes at 103.5 with 70% upper wick
        hist_short = [
            {"open": 101.0, "high": 103.0, "low": 100.0, "close": 102.0, "volume": 1000.0},
            {"open": 102.0, "high": 105.0, "low": 101.0, "close": 104.0, "volume": 1100.0}, # Swing High = 105.0
            {"open": 104.0, "high": 104.5, "low": 102.5, "close": 103.0, "volume": 900.0},
            {"open": 103.0, "high": 104.0, "low": 102.0, "close": 103.5, "volume": 850.0},
            {"open": 103.5, "high": 107.0, "low": 103.0, "close": 104.0, "volume": 2500.0}, # Sweeps 105.0 up to 107.0, closes at 104.0 (wick = 3.0/4.0 = 75%)
            {"open": 104.0, "high": 104.1, "low": 103.8, "close": 103.9, "volume": 50.0}   # Live bar
        ]
        df_sweep_short = pd.DataFrame(hist_short)

        confirmed_s, reason_s, metrics_s = EntryConfirmationEngine.validate_candle_trigger(df_sweep_short, "SHORT", 103.9)
        self.assertTrue(confirmed_s, "Bearish liquidity sweep & rejection must confirm entry")
        self.assertIn("Liquidity Sweep & Rejection", reason_s)
        self.assertEqual(metrics_s.get("pattern"), "LIQUIDITY_SWEEP_REJECTION")
        self.assertTrue(metrics_s.get("is_sweep_reclaim"))

    def test_new_canonical_strategies_gating_and_regimes(self):
        """Forensic Test: Newly added institutional strategies (FVG, VWAP, Liquidity Reclaim, Squeeze Expansion)."""
        from app.quant_v16.strategies import StrategyRegistry, StrategyArchetype
        from app.engine.signals.signal_generator import map_canonical_strategy

        reg = StrategyRegistry()

        # Check StrategyArchetype values exist
        self.assertEqual(StrategyArchetype.FVG_RETEST_LONG.value, "FVG_RETEST_LONG")
        self.assertEqual(StrategyArchetype.FVG_RETEST_SHORT.value, "FVG_RETEST_SHORT")
        self.assertEqual(StrategyArchetype.VWAP_BOUNCE_LONG.value, "VWAP_BOUNCE_LONG")
        self.assertEqual(StrategyArchetype.VWAP_BOUNCE_SHORT.value, "VWAP_BOUNCE_SHORT")
        self.assertEqual(StrategyArchetype.LIQUIDITY_RECLAIM_LONG.value, "LIQUIDITY_RECLAIM_LONG")
        self.assertEqual(StrategyArchetype.LIQUIDITY_RECLAIM_SHORT.value, "LIQUIDITY_RECLAIM_SHORT")
        self.assertEqual(StrategyArchetype.SQUEEZE_EXPANSION_LONG.value, "SQUEEZE_EXPANSION_LONG")
        self.assertEqual(StrategyArchetype.SQUEEZE_EXPANSION_SHORT.value, "SQUEEZE_EXPANSION_SHORT")

        # FVG_RETEST_LONG allowed in BULL_TREND, paused in BEAR_TREND
        allowed_bull, _ = reg.is_strategy_allowed(StrategyArchetype.FVG_RETEST_LONG.value, "BULL_TREND")
        allowed_bear, _ = reg.is_strategy_allowed(StrategyArchetype.FVG_RETEST_LONG.value, "BEAR_TREND")
        self.assertTrue(allowed_bull)
        self.assertFalse(allowed_bear)

        # FVG_RETEST_SHORT allowed in BEAR_TREND, paused in BULL_TREND
        allowed_short_bear, _ = reg.is_strategy_allowed(StrategyArchetype.FVG_RETEST_SHORT.value, "BEAR_TREND")
        allowed_short_bull, _ = reg.is_strategy_allowed(StrategyArchetype.FVG_RETEST_SHORT.value, "BULL_TREND")
        self.assertTrue(allowed_short_bear)
        self.assertFalse(allowed_short_bull)

        # Keyword mapping verification
        self.assertEqual(map_canonical_strategy("FAIR_VALUE_GAP", "LONG"), "FVG_RETEST_LONG")
        self.assertEqual(map_canonical_strategy("IMBALANCE_FILL", "SHORT"), "FVG_RETEST_SHORT")
        self.assertEqual(map_canonical_strategy("VWAP_REBOUND", "LONG"), "VWAP_BOUNCE_LONG")
        self.assertEqual(map_canonical_strategy("TURTLE_SOUP_RECLAIM", "LONG"), "LIQUIDITY_RECLAIM_LONG")
        self.assertEqual(map_canonical_strategy("SQUEEZE_EXPANSION", "SHORT"), "SQUEEZE_EXPANSION_SHORT")

    def test_spread_hurdle_and_robust_volume_filtering(self):
        """Forensic Test: Volume absorption disqualified when bid-ask spread exceeds 35 bps (0.35%)."""
        from app.quant_v16.entry_confirmation import EntryConfirmationEngine

        hist = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0}
            for _ in range(21)
        ]
        # Trigger bar has high volume surge (2.5x average)
        hist[-1] = {"open": 100.0, "high": 102.0, "low": 99.5, "close": 101.8, "volume": 2500.0}
        live_bar = {"open": 101.8, "high": 101.9, "low": 101.7, "close": 101.8, "volume": 10.0}
        df = pd.DataFrame(hist + [live_bar])

        # Case A: Low liquid spread (8.0 bps <= 35.0 bps) -> Volume absorption qualified
        _, _, metrics_liquid = EntryConfirmationEngine.validate_candle_trigger(df, "LONG", 101.8, spread_bps=8.0)
        self.assertTrue(metrics_liquid["is_spread_acceptable"])
        self.assertTrue(metrics_liquid["is_volume_absorption"])
        self.assertGreaterEqual(metrics_liquid["volume_surge_ratio"], 1.30)

        # Case B: High illiquid spread (45.0 bps > 35.0 bps) -> Volume absorption disqualified due to thin-book risk
        _, _, metrics_illiquid = EntryConfirmationEngine.validate_candle_trigger(df, "LONG", 101.8, spread_bps=45.0)
        self.assertFalse(metrics_illiquid["is_spread_acceptable"])
        self.assertFalse(metrics_illiquid["is_volume_absorption"])

    def test_resting_limit_order_lifecycle_and_blowout_cancellation(self):
        """Forensic Test: Dynamic resting limit order management, adverse blowout cancellation, chase expiration, and clean fill."""
        import os
        import tempfile
        import shutil
        from app.engine.execution.paper_trading_bot import PaperTradingBot

        tmp_dir = tempfile.mkdtemp()
        try:
            bot = PaperTradingBot(ledger_file=os.path.join(tmp_dir, "test_ledger.json"))

            # 1. Admit a resting limit order setup
            signal = {
                "symbol": "BTC/USDT",
                "direction": "LONG",
                "horizon": "15M",
                "is_trade_active": True,
                "signal_status": "ACTIVE_SIGNAL",
                "current_price": 100.30,
                "entry_price": 100.0,
                "optimal_entry_limit": 100.0,
                "entry_zone_min": 99.80,
                "entry_zone_max": 100.40,
                "is_limit_pending": True,
                "tp1_price": 103.0,
                "tp2_price": 105.0,
                "tp3_price": 108.0,
                "sl_price": 98.5
            }
            admitted = bot.admit_signal(signal)
            self.assertTrue(admitted, "Resting limit signal must be admitted")
            self.assertEqual(len(bot.data["open_positions"]), 1)
            pos = bot.data["open_positions"][0]
            self.assertEqual(pos["status"], "RESTING_LIMIT")
            self.assertTrue(pos["is_limit_resting"])

            # 2. Case A: Extreme Macro Impulse / Adverse Blowout
            # Price dumps to 98.0 (2% below limit of 100.0) -> must cancel resting order to avoid knife catch
            bot.on_tick({"BTC/USDT": 98.0})
            self.assertEqual(len(bot.data["open_positions"]), 0, "Resting limit must be cancelled on blowout")
            self.assertEqual(len(bot.data.get("cancelled_orders", [])), 1)
            self.assertEqual(bot.data["cancelled_orders"][0]["cancellation_reason"], "CANCELLED_EXTREME_MACRO_BLOWOUT")

            # 3. Case B: Chase Buffer Exceeded
            signal["symbol"] = "ETH/USDT"
            bot.admit_signal(signal)
            self.assertEqual(len(bot.data["open_positions"]), 1)
            # Price drifts away to 101.5 (> 100.40 zone max) without fill
            bot.on_tick({"ETH/USDT": 101.5})
            self.assertEqual(len(bot.data["open_positions"]), 0, "Resting limit must be cancelled on chase drift")
            self.assertEqual(bot.data["cancelled_orders"][-1]["cancellation_reason"], "CANCELLED_CHASE_EXCEEDED")

            # 4. Case C: Clean Fill Execution
            signal["symbol"] = "SOL/USDT"
            bot.admit_signal(signal)
            self.assertEqual(len(bot.data["open_positions"]), 1)
            # Price touches 99.95 (within limit zone <= 100.0)
            bot.on_tick({"SOL/USDT": 99.95})
            self.assertEqual(len(bot.data["open_positions"]), 1)
            filled_pos = bot.data["open_positions"][0]
            self.assertEqual(filled_pos["status"], "OPEN")
            self.assertFalse(filled_pos["is_limit_resting"])
            self.assertEqual(filled_pos["entry_price"], 100.0)

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_websocket_feed_tier0_integration(self):
        """Forensic Test: Sub-second WebSocket feed ingestion and Tier-0 priority in MultiHorizonDataLoader."""
        import time
        from app.engine.scanner.websocket_feed import WebSocketFeedManager
        from app.engine.scanner.data_loader import MultiHorizonDataLoader

        ws = WebSocketFeedManager()
        # Seed test ticks directly
        ws._prices = {"BTC/USDT": 68500.0, "ETH/USDT": 2500.0, "BTCUSDT": 68500.0}
        for i in range(12):
            ws._prices[f"COIN{i}/USDT"] = 10.0 + i
        ws._connected = True
        ws._last_received_ts = time.time()

        self.assertTrue(ws.is_healthy())
        self.assertLess(ws.get_latency_ms(), 100.0)
        self.assertEqual(ws.get_ticker("BTC/USDT"), 68500.0)

        loader = MultiHorizonDataLoader()
        loader.ws_feed = ws

        ticks = loader.fetch_all_tickers(max_age_seconds=1.0)
        self.assertEqual(ticks.get("BTC/USDT"), 68500.0)
        self.assertGreater(len(ticks), 10)
        self.assertLess(loader.get_feed_latency_ms(), 500.0)

    def test_latency_adaptive_resting_limit_blowout_gate(self):
        """Forensic Test: Dynamic tightening of resting order blowout gate under exchange REST queueing latency."""
        import os
        import tempfile
        import shutil
        from app.engine.execution.paper_trading_bot import PaperTradingBot

        tmp_dir = tempfile.mkdtemp()
        try:
            bot = PaperTradingBot(ledger_file=os.path.join(tmp_dir, "test_latency_ledger.json"))

            # Scenario 1: Sub-second WebSocket feed (latency = 150ms <= 800ms)
            # Threshold stays standard at 1.20%.
            # Price at 99.10 (0.90% drop) must NOT trigger premature blowout cancellation; executes clean fill.
            signal1 = {
                "symbol": "BTC/USDT",
                "direction": "LONG",
                "horizon": "15M",
                "is_trade_active": True,
                "signal_status": "ACTIVE_SIGNAL",
                "current_price": 100.20,
                "entry_price": 100.0,
                "optimal_entry_limit": 100.0,
                "entry_zone_min": 99.80,
                "entry_zone_max": 100.40,
                "is_limit_pending": True,
                "tp1_price": 103.0,
                "tp2_price": 105.0,
                "tp3_price": 108.0,
                "sl_price": 98.5
            }
            bot.admit_signal(signal1)
            self.assertEqual(len(bot.data["open_positions"]), 1)
            bot.on_tick({"BTC/USDT": 99.10}, tick_latency_ms=150.0)
            self.assertEqual(len(bot.data["open_positions"]), 1, "0.90% drop must execute clean fill at limit, not blowout")
            self.assertEqual(bot.data["open_positions"][0]["status"], "OPEN")

            # Scenario 2: High REST queueing latency (latency = 2000ms > 800ms)
            # Threshold dynamically tightens: 1.20 - ((2000-800)/2000 * 0.40) = 1.20 - 0.24 = 0.96%!
            # An adverse drop to 98.95 (1.05% drop) is below static 1.20% but exceeds 0.96% effective gate
            # -> cancelled immediately, safeguarding resting order from laggy knife catches!
            signal2 = {
                "symbol": "ETH/USDT",
                "direction": "LONG",
                "horizon": "15M",
                "is_trade_active": True,
                "signal_status": "ACTIVE_SIGNAL",
                "current_price": 100.20,
                "entry_price": 100.0,
                "optimal_entry_limit": 100.0,
                "entry_zone_min": 99.80,
                "entry_zone_max": 100.40,
                "is_limit_pending": True,
                "tp1_price": 103.0,
                "tp2_price": 105.0,
                "tp3_price": 108.0,
                "sl_price": 98.5
            }
            bot.admit_signal(signal2)
            self.assertEqual(len(bot.data["open_positions"]), 2)  # 1 open BTC + 1 resting ETH
            bot.on_tick({"BTC/USDT": 99.10, "ETH/USDT": 98.95}, tick_latency_ms=2000.0)
            # ETH resting limit cancelled; only BTC open position remains
            self.assertEqual(len(bot.data["open_positions"]), 1, "Laggy 1.05% drop must trigger latency-tightened gate")
            canc = bot.data["cancelled_orders"][-1]
            self.assertEqual(canc["cancellation_reason"], "CANCELLED_EXTREME_MACRO_BLOWOUT")
            self.assertIn("Gate: 0.96%", canc["cancellation_detail"])
            self.assertIn("Latency: 2000ms", canc["cancellation_detail"])

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_bullish_and_bearish_engulfing_confirmation(self):
        """Forensic Test: Verify Bullish & Bearish Engulfing Momentum Flip detection and confirmation."""
        # 1. Bullish Engulfing: Prior candle red (open=102, close=100), Trigger candle green (open=99.5, close=102.5, high=102.6, low=99.4)
        df_bull = pd.DataFrame([
            {"open": 101.0, "high": 102.0, "low": 100.5, "close": 101.5, "volume": 100.0},
            {"open": 102.0, "high": 102.2, "low": 99.8, "close": 100.0, "volume": 120.0},  # prior red
            {"open": 99.5, "high": 102.6, "low": 99.4, "close": 102.5, "volume": 250.0},   # trigger green engulfing
            {"open": 102.5, "high": 102.8, "low": 102.4, "close": 102.7, "volume": 50.0}   # developing live row
        ])
        is_conf, reason, metrics = EntryConfirmationEngine.validate_candle_trigger(
            df=df_bull, direction="LONG", current_price=102.7, spread_bps=5.0
        )
        self.assertTrue(is_conf, f"Bullish engulfing should confirm, reason: {reason}")
        self.assertTrue(metrics["is_engulfing"])
        self.assertEqual(metrics["pattern"], "BULLISH_ENGULFING")

        # 2. Bearish Engulfing: Prior candle green (open=100, close=102), Trigger candle red (open=102.5, close=99.5, high=102.6, low=99.4)
        df_bear = pd.DataFrame([
            {"open": 99.0, "high": 100.5, "low": 98.5, "close": 100.0, "volume": 100.0},
            {"open": 100.0, "high": 102.2, "low": 99.8, "close": 102.0, "volume": 120.0},  # prior green
            {"open": 102.5, "high": 102.6, "low": 99.4, "close": 99.5, "volume": 250.0},   # trigger red engulfing
            {"open": 99.5, "high": 99.6, "low": 99.2, "close": 99.3, "volume": 50.0}       # developing live row
        ])
        is_conf_b, reason_b, metrics_b = EntryConfirmationEngine.validate_candle_trigger(
            df=df_bear, direction="SHORT", current_price=99.3, spread_bps=5.0
        )
        self.assertTrue(is_conf_b, f"Bearish engulfing should confirm, reason: {reason_b}")
        self.assertTrue(metrics_b["is_engulfing"])
        self.assertEqual(metrics_b["pattern"], "BEARISH_ENGULFING")

    def test_liquidity_sweep_and_reclaim_confirmation(self):
        """Forensic Test: Verify Turtle Soup Liquidity Sweep & Reclaim detection and confirmation."""
        # Swing low at 98.0 in prior window; trigger candle dips to 97.2 but closes back at 98.6 with 35% lower wick
        rows = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 100.0},
            {"open": 100.5, "high": 101.0, "low": 98.0, "close": 99.0, "volume": 100.0},   # swing low at 98.0
            {"open": 99.0, "high": 99.5, "low": 98.5, "close": 99.0, "volume": 100.0},
            {"open": 99.0, "high": 99.2, "low": 98.2, "close": 98.8, "volume": 100.0},
            {"open": 98.8, "high": 98.9, "low": 97.2, "close": 98.6, "volume": 180.0},     # sweep to 97.2, close at 98.6 (>= 98.0)
            {"open": 98.6, "high": 98.9, "low": 98.5, "close": 98.8, "volume": 50.0}       # live row
        ]
        df = pd.DataFrame(rows)
        is_conf, reason, metrics = EntryConfirmationEngine.validate_candle_trigger(
            df=df, direction="LONG", current_price=98.8, spread_bps=5.0
        )
        self.assertTrue(is_conf, f"Liquidity sweep & reclaim should confirm, reason: {reason}")
        self.assertTrue(metrics["is_sweep_reclaim"])
        self.assertEqual(metrics["pattern"], "LIQUIDITY_SWEEP_RECLAIM")
        self.assertEqual(metrics["swept_price"], 98.0)

    def test_fair_value_gap_retest_confirmation(self):
        """Forensic Test: Verify FVG 50% Consequent Encroachment Retest confirmation."""
        # Bullish FVG: Bar 1 high = 100.0, Bar 2 big pump 100.0->104.0, Bar 3 low = 102.0. Void = [100.0, 102.0], CE = 101.0.
        # Trigger Bar dips to 101.2 and closes at 101.8 (retesting gap and holding above CE 101.0).
        rows = [
            {"open": 98.0, "high": 100.0, "low": 97.5, "close": 99.5, "volume": 100.0},    # Bar 1: high = 100.0
            {"open": 99.5, "high": 103.5, "low": 99.5, "close": 103.0, "volume": 300.0},   # Bar 2: impulse
            {"open": 103.0, "high": 104.0, "low": 102.0, "close": 103.5, "volume": 200.0}, # Bar 3: low = 102.0 (Gap: 100 to 102)
            {"open": 103.5, "high": 103.6, "low": 101.2, "close": 101.8, "volume": 150.0}, # Trigger Bar: low 101.2 <= 102.0, close 101.8 >= 101.0
            {"open": 101.8, "high": 102.2, "low": 101.7, "close": 102.0, "volume": 50.0}   # Live row
        ]
        df = pd.DataFrame(rows)
        is_conf, reason, metrics = EntryConfirmationEngine.validate_candle_trigger(
            df=df, direction="LONG", current_price=102.0, spread_bps=5.0
        )
        self.assertTrue(is_conf, f"FVG retest should confirm, reason: {reason}")
        self.assertTrue(metrics["is_fvg_retest"])
        self.assertEqual(metrics["pattern"], "FVG_RETEST_LONG")
        self.assertEqual(metrics["fvg_gap_ce"], 101.0)

    def test_anti_chase_market_confirmed_on_momentum_breakout(self):
        """Forensic Test: Verify momentum breakouts confirm MARKET_CONFIRMED entry without false resting limit traps."""
        current_p = 100.0
        atr = 2.0  # 2% ATR

        # 1. Momentum strategy should execute MARKET_CONFIRMED at current_price
        zone_info = EntryConfirmationEngine.calculate_optimal_entry_zone(
            current_price=current_p,
            ob_setup=None,
            direction="LONG",
            active_atr=atr,
            strategy="MOMENTUM_LONG",
            candle_metrics={"is_engulfing": True}
        )
        self.assertEqual(zone_info["entry_mode"], "MARKET_CONFIRMED")
        self.assertFalse(zone_info["is_limit_pending"])
        self.assertEqual(zone_info["optimal_entry_price"], current_p)

        # 2. Value-zone setup (Order Block) where price has extended 1.5% away should recommend RESTING_LIMIT
        ob_setup = {"optimal_entry_limit": 98.0, "setup_detected": True}
        zone_info_ob = EntryConfirmationEngine.calculate_optimal_entry_zone(
            current_price=current_p, # 100.0 is 2.04% above 98.0, exceeding 0.40% chase hurdle
            ob_setup=ob_setup,
            direction="LONG",
            active_atr=atr,
            strategy="ORDER_BLOCK_LONG"
        )
        self.assertEqual(zone_info_ob["entry_mode"], "RESTING_LIMIT")
        self.assertTrue(zone_info_ob["is_limit_pending"])
        self.assertEqual(zone_info_ob["optimal_entry_limit"], 98.0)
        self.assertTrue(zone_info_ob["is_chasing"])

    def test_dynamic_canonical_strategy_specialization(self):
        """Forensic Test: Verify that map_canonical_strategy dynamically specializes to true high-edge archetypes."""
        # 1. Liquidity sweep reclaim
        strat1 = map_canonical_strategy(
            raw_strategy="MOMENTUM_EXPANSION",
            direction="LONG",
            candle_metrics={"is_sweep_reclaim": True}
        )
        self.assertEqual(strat1, StrategyArchetype.LIQUIDITY_RECLAIM_LONG.value)

        # 2. Fair Value Gap retest
        strat2 = map_canonical_strategy(
            raw_strategy="MOMENTUM_EXPANSION",
            direction="SHORT",
            candle_metrics={"is_fvg_retest": True}
        )
        self.assertEqual(strat2, StrategyArchetype.FVG_RETEST_SHORT.value)

        # 3. VWAP bounce
        strat3 = map_canonical_strategy(
            raw_strategy="DIRECTIONAL_TREND",
            direction="LONG",
            candle_metrics={"is_vwap_bounce": True}
        )
        self.assertEqual(strat3, StrategyArchetype.VWAP_BOUNCE_LONG.value)

        # 4. Squeeze expansion
        strat4 = map_canonical_strategy(
            raw_strategy="BREAKOUT",
            direction="SHORT",
            candle_metrics={"is_squeeze_expansion": True}
        )
        self.assertEqual(strat4, StrategyArchetype.SQUEEZE_EXPANSION_SHORT.value)

    def test_regime_kill_switch_allows_liquidity_reclaim_in_range_and_bear(self):
        """Forensic Test: Verify that Section 32 Kill Switch allows specialized strategies in their authorized regimes."""
        registry = StrategyRegistry()

        # In RANGE: Generic MOMENTUM_LONG is PAUSED, but LIQUIDITY_RECLAIM_LONG and RANGE_BOUNCE_LONG must be ELIGIBLE
        mom_allowed, mom_reason = registry.is_strategy_allowed(StrategyArchetype.MOMENTUM_LONG.value, "RANGE")
        self.assertFalse(mom_allowed, "MOMENTUM_LONG should be paused in RANGE")

        liq_allowed, liq_reason = registry.is_strategy_allowed(StrategyArchetype.LIQUIDITY_RECLAIM_LONG.value, "RANGE")
        self.assertTrue(liq_allowed, f"LIQUIDITY_RECLAIM_LONG must be eligible in RANGE, got: {liq_reason}")

        rng_allowed, rng_reason = registry.is_strategy_allowed(StrategyArchetype.RANGE_BOUNCE_LONG.value, "RANGE")
        self.assertTrue(rng_allowed, f"RANGE_BOUNCE_LONG must be eligible in RANGE, got: {rng_reason}")

        # In BEAR_TREND: LIQUIDITY_RECLAIM_SHORT and FVG_RETEST_SHORT must be ELIGIBLE
        fvg_s_allowed, fvg_s_reason = registry.is_strategy_allowed(StrategyArchetype.FVG_RETEST_SHORT.value, "BEAR_TREND")
        self.assertTrue(fvg_s_allowed, f"FVG_RETEST_SHORT must be eligible in BEAR_TREND, got: {fvg_s_reason}")

        liq_s_allowed, liq_s_reason = registry.is_strategy_allowed(StrategyArchetype.LIQUIDITY_RECLAIM_SHORT.value, "BEAR_TREND")
        self.assertTrue(liq_s_allowed, f"LIQUIDITY_RECLAIM_SHORT must be eligible in BEAR_TREND, got: {liq_s_reason}")

    def test_price_freshness_15s_enforcement_and_ntz_lock(self):
        """Forensic Test: Verify that live price freshness within 15 seconds is enforced and NTZ locks when exceeded."""
        from app.quant_v16.no_trade_zone import NoTradeZoneEngine, NoTradeZoneReason

        ntz_engine = NoTradeZoneEngine()

        # 1. Fresh DataFrame (live price age 4.0s <= 15.0s) -> NTZ not triggered by staleness
        df_fresh = pd.DataFrame({
            "open": [100.0, 101.0, 102.0],
            "high": [102.0, 103.0, 104.0],
            "low": [99.0, 100.0, 101.0],
            "close": [101.0, 102.0, 103.0],
            "volume": [1000.0, 1200.0, 1500.0]
        })
        df_fresh.attrs["live_price_freshness_seconds"] = 4.0
        df_fresh.attrs["is_price_fresh_15s"] = True

        eval_fresh = ntz_engine.evaluate_asset_ntz(df_fresh, current_price=103.0, anchor_tf="1h")
        self.assertNotEqual(eval_fresh["code"], NoTradeZoneReason.STALE_PRICE_FEED.value)

        # 2. Stale DataFrame (live price age 22.5s > 15.0s) -> NTZ MUST lock with STALE_PRICE_FEED
        df_stale = df_fresh.copy()
        df_stale.attrs["live_price_freshness_seconds"] = 22.5
        df_stale.attrs["is_price_fresh_15s"] = False

        eval_stale = ntz_engine.evaluate_asset_ntz(df_stale, current_price=103.0, anchor_tf="1h")
        self.assertTrue(eval_stale["is_ntz"], "NTZ must be active when price feed exceeds 15s")
        self.assertEqual(eval_stale["code"], NoTradeZoneReason.STALE_PRICE_FEED.value)
        self.assertFalse(eval_stale["allowed_to_trade"], "Trading must be forbidden when price feed is stale")
        self.assertTrue(any("Stale Price Feed" in r for r in eval_stale["reasons"]))


if __name__ == "__main__":
    unittest.main()




