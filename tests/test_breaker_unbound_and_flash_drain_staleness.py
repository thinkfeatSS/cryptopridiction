import unittest
import numpy as np
import pandas as pd
from app.quant_v16.order_blocks import InstitutionalOrderBlockEngine, OrderBlockType, OrderBlockState, OrderBlock
from app.quant_v16.no_trade_zone import no_trade_zone_engine, NoTradeZoneReason
from app.engine.signals.signal_generator import SignalGenerationSystem


class TestBreakerUnboundAndFlashDrainStaleness(unittest.TestCase):
    """
    Forensic regression tests ensuring:
    1. Breaker block evaluation in evaluate_live_setup never raises UnboundLocalError
       for is_live_green_ramp or is_live_red_waterfall.
    2. compute_rvol and is_flash_drain evaluate the completed candle (iloc[-2]) rather
       than an unclosed 3-second live candle (iloc[-1]), preventing false-positive lockouts.
    3. Flash liquidity drain true positive is reliably caught when completed candle collapses.
    4. Hyper-Bullish News Sentinel does not veto SHORT signals when composite sentiment is NEUTRAL.
    """

    def setUp(self):
        self.sig_sys = SignalGenerationSystem()

    def test_breaker_blocks_no_unbound_local_error(self):
        """
        Validates that evaluate_live_setup handles breaker blocks without UnboundLocalError
        when no standard touching order blocks exist.
        """
        # Create a 30-bar dataframe
        dates = pd.date_range("2026-11-01", periods=30, freq="15min")
        df = pd.DataFrame({
            "timestamp": [int(d.timestamp() * 1000) for d in dates],
            "open": [100.0 + i * 0.1 for i in range(30)],
            "high": [101.0 + i * 0.1 for i in range(30)],
            "low": [99.5 + i * 0.1 for i in range(30)],
            "close": [100.5 + i * 0.1 for i in range(30)],
            "volume": [1000.0 for _ in range(30)]
        })

        # Mock detect_order_blocks to return a breaker block without standard touching blocks
        bb_mock = OrderBlock(
            block_type=OrderBlockType.BULLISH,
            state=OrderBlockState.BREAKER,
            timeframe="15m",
            candle_idx=10,
            timestamp=1700000000000,
            ob_high=102.0,
            ob_low=101.0,
            ob_open=101.2,
            ob_close=101.8,
            equilibrium_50=101.5,
            displacement_mag=2.5,
            volume_surge=2.0,
            has_fvg=False,
            retest_count=1,
            breaker_flipped=True,
            is_touching=True,
            zeiierman_rank=4,
            zeiierman_rank_label="Rank 4 (Standard Breaker)",
            confluence_score=75.0
        )

        orig_detect = InstitutionalOrderBlockEngine.detect_order_blocks
        try:
            InstitutionalOrderBlockEngine.detect_order_blocks = staticmethod(lambda df_in, timeframe="15m", current_price=None: [bb_mock])
            # Price is within breaker zone
            res = InstitutionalOrderBlockEngine.evaluate_live_setup(df, timeframe="15m", current_price=101.5)
            self.assertIsInstance(res, dict)
            self.assertTrue(res.get("setup_detected"))
            self.assertEqual(res.get("direction"), "SHORT")
        finally:
            InstitutionalOrderBlockEngine.detect_order_blocks = orig_detect

    def test_rvol_and_flash_drain_on_open_candle(self):
        """
        Validates that a newly opened live candle with near-zero volume does NOT falsely
        trigger Intraday Flash Liquidity Drain or Dry Volume Consolidation when the
        preceding completed candle had healthy volume.
        """
        rows = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0}
            for _ in range(20)
        ]
        # Bar 21: Fully completed candle with 1,200 volume ($120k turnover)
        rows.append({
            "open": 100.5, "high": 102.0, "low": 100.2, "close": 101.8, "volume": 1200.0
        })
        # Bar 22: Newly opened live bar (<5s old) with only 2.0 volume ($200 turnover)
        rows.append({
            "open": 101.8, "high": 101.9, "low": 101.7, "close": 101.85, "volume": 2.0
        })
        df = pd.DataFrame(rows)

        # 1. compute_rvol must reflect the healthy completed bar (1200/1000 = 1.2x)
        rvol = no_trade_zone_engine.compute_rvol(df, period=20)
        self.assertGreaterEqual(rvol, 1.0, f"RVOL should evaluate completed bar volume, got {rvol}")

        # 2. evaluate_asset_ntz must NOT trigger Flash Liquidity Drain or Dry Volume
        ntz_res = no_trade_zone_engine.evaluate_asset_ntz(
            df=df,
            current_price=101.85,
            anchor_tf="15m",
            stats_24h={"quoteVolume": 25_000_000.0},
            decision="MOMENTUM_TREND_EXPANSION"
        )
        self.assertFalse(
            any("Flash Liquidity Drain" in r for r in ntz_res.get("reasons", [])),
            f"Open candle must not trigger flash liquidity drain: {ntz_res.get('reasons')}"
        )
        self.assertFalse(
            any("Dry Volume" in r for r in ntz_res.get("reasons", [])),
            f"Open candle must not trigger dry volume consolidation: {ntz_res.get('reasons')}"
        )

    def test_flash_drain_true_positive_on_collapsed_closed_candle(self):
        """
        Validates that when the completed candle legitimately suffers an acute volume collapse
        (<12% of 20-bar avg or <$5k turnover), Flash Liquidity Drain correctly engages.
        """
        rows = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0}
            for _ in range(20)
        ]
        # Bar 21: Completed candle with severe volume collapse (50.0 units vs 1000.0 avg = 0.05x RVOL)
        rows.append({
            "open": 100.5, "high": 101.0, "low": 100.2, "close": 100.8, "volume": 50.0
        })
        # Bar 22: Live developing bar
        rows.append({
            "open": 100.8, "high": 101.0, "low": 100.7, "close": 100.9, "volume": 10.0
        })
        df = pd.DataFrame(rows)

        ntz_res = no_trade_zone_engine.evaluate_asset_ntz(
            df=df,
            current_price=100.9,
            anchor_tf="15m",
            stats_24h={"quoteVolume": 25_000_000.0},
            decision="MOMENTUM_TREND_EXPANSION"
        )
        self.assertTrue(ntz_res["is_ntz"])
        self.assertTrue(any("Flash Liquidity Drain" in r for r in ntz_res.get("reasons", [])))

    def test_hyper_bullish_news_sentinel_neutral_headline_does_not_veto_short(self):
        """
        Validates that a SHORT signal is not vetoed by Hyper-Bullish News Sentinel
        when composite sentiment is NEUTRAL (score < 0.20), even if an isolated historical
        item had a raw score >= 0.50.
        """
        dfs_9 = {
            tf: pd.DataFrame({
                "timestamp": [1700000000000 + i * 900000 for i in range(30)],
                "open": [100.0 - i * 0.1 for i in range(30)],
                "high": [100.5 - i * 0.1 for i in range(30)],
                "low": [99.0 - i * 0.1 for i in range(30)],
                "close": [99.5 - i * 0.1 for i in range(30)],
                "volume": [1000.0 for _ in range(30)]
            })
            for tf in ["5m", "15m", "1h", "4h", "12h", "1d", "1w", "15d", "1M"]
        }

        fund_matrix_neutral = {
            "has_severe_negative_news": False,
            "has_severe_positive_news": True,  # Isolated item had score 0.50
            "news_sentiment": {
                "score": 0.05,
                "label": "⚪ NEUTRAL",
                "top_headline": "Zcash Foundation updates development grants",
                "recent_headlines": ["Zcash Foundation updates development grants"]
            },
            "catalyst_event": {"is_sell_the_news_danger_zone": False, "is_pre_event_runup": False},
            "macro_economic_event": {"is_volatility_pause_active": False}
        }

        sig = self.sig_sys._build_single_horizon_signal(
            symbol="ZEC/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="SHORT",
            current_price=96.5,
            dfs_9=dfs_9,
            horizon_prediction={"consensus_probability": 0.70, "predicted_change_pct": -2.5, "predicted_target_price": 94.0},
            btc_shield_state={"status_code": "BEAR_TREND", "regime": "BEAR_TREND", "altcoin_shorts_allowed": True, "altcoin_longs_allowed": False},
            aligned_horizons=["5m", "15m", "1h"],
            volume_24h_usd=25_000_000.0,
            fundamental_matrix=fund_matrix_neutral
        )

        self.assertIsNotNone(sig)
        self.assertNotEqual(sig.get("signal_status"), "HOLD_VETOED_BY_NEGATIVE_NEWS")
        self.assertFalse("Hyper-Bullish News Sentinel" in str(sig.get("wait_reason", "")))

    def test_evaluate_multi_horizon_gates_none_matrix_eval(self):
        """
        Validates that evaluate_multi_horizon_gates gracefully handles matrix_eval=None
        without raising AttributeError: 'NoneType' object has no attribute 'get'.
        """
        trend_matrix = {tf: "BEARISH" for tf in ["5m", "15m", "1h", "4h", "12h", "1d", "7d", "15d", "1m"]}
        horizon_predictions = {
            tf: {
                "consensus_probability": 0.65,
                "is_cold_start": False,
                "candle_count": 50,
                "predicted_change_pct": -2.0,
                "predicted_target_price": 98.0
            }
            for tf in trend_matrix
        }

        # Should not raise AttributeError when matrix_eval is None
        q_15, q_1h, q_24 = self.sig_sys.evaluate_multi_horizon_gates(
            trend_matrix=trend_matrix,
            horizon_predictions=horizon_predictions,
            matrix_eval=None,
            ob_setup_15m=None,
            ob_setup_1h=None,
            ob_setup_24h=None
        )
        self.assertIsInstance(q_15, dict)
        self.assertIsInstance(q_1h, dict)
        self.assertIsInstance(q_24, dict)

    def test_cross_timeframe_matrix_zero_range_span_returns_dict(self):
        """
        Validates that CrossTimeframeMatrixEngine.evaluate_matrix returns a valid dictionary
        (and never None) even when range_span <= 0 and htf_ranging is True.
        """
        from app.quant_v16.cross_timeframe_matrix import CrossTimeframeMatrixEngine
        from app.quant_v16.fractal_consolidation import TimeframeConsolidationProfile, FractalTimeframeState

        # Flat range: range_high == range_low
        p_15 = TimeframeConsolidationProfile(
            timeframe="15m",
            state=FractalTimeframeState.CONSOLIDATION_RANGING,
            is_consolidation=True,
            is_coiling_squeeze=False,
            chop_index=55.0,
            adx=15.0,
            bbw_pct=1.0,
            is_inside_bar=False,
            is_nr7=False,
            is_nr4=False,
            is_doji=False,
            compression_score=50.0,
            range_high=100.0,
            range_low=100.0,
            range_mid=100.0,
            position_in_range_pct=0.5,
            headroom_to_high_pct=0.0,
            headroom_to_low_pct=0.0,
            current_price=100.0,
            atr=0.5,
            atr_pct=0.5
        )
        p_1d = TimeframeConsolidationProfile(
            timeframe="1d",
            state=FractalTimeframeState.CONSOLIDATION_RANGING,
            is_consolidation=True,
            is_coiling_squeeze=False,
            chop_index=55.0,
            adx=15.0,
            bbw_pct=1.5,
            is_inside_bar=False,
            is_nr7=False,
            is_nr4=False,
            is_doji=False,
            compression_score=50.0,
            range_high=100.0,
            range_low=100.0,
            range_mid=100.0,
            position_in_range_pct=0.5,
            headroom_to_high_pct=0.0,
            headroom_to_low_pct=0.0,
            current_price=100.0,
            atr=1.0,
            atr_pct=1.0
        )

        res = CrossTimeframeMatrixEngine.evaluate_matrix(
            profiles={"15m": p_15, "1d": p_1d},
            current_price=100.0
        )
        self.assertIsNotNone(res)
        self.assertIsInstance(res, dict)
        self.assertIn("archetype", res)
        self.assertIn("strategy", res)


if __name__ == "__main__":
    unittest.main()
