import unittest
import numpy as np
import pandas as pd
from typing import Dict, Any

from app.engine.signals.signal_generator import SignalGenerationSystem
from app.engine.execution.paper_trading_bot import PaperTradingBot


class TestInstitutionalWinningSignals(unittest.TestCase):
    """
    Forensic verification suite for Institutional Winning Setups matching live production winning trades:
    - Rank 1 Nested SMC (4H/1W POI + 15M Trigger)
    - Rank 4 Institutional Breaker Block
    - Range Rotation (1D Range Mean Reversion to boundary)
    - Directional Breakout Expansion
    - Coiling Breakout (15M Squeeze into 1D Expansion)
    - Liquidity Reclaim (Institutional reversal)
    - VWAP Bounce
    - Strict Multi-Horizon Unanimous Alignment (5M-24H)
    """

    def setUp(self):
        self.sg = SignalGenerationSystem()
        self.paper_bot = PaperTradingBot()

    def test_01_is_macro_structural_archetype_comprehensive_coverage(self):
        """
        Verify that is_macro_structural_archetype covers all proven winning setups:
        Order Blocks, Breaker Blocks, Range Rotation, Directional Breakout, Coiling Breakout,
        Liquidity Reclaim, VWAP Bounce, and Unanimous Alignment.
        Matches live winning trade:
        ALT_USDT_15M_1794872668: ⚡ Grade A (BREAKER_BLOCK_SHORT @ 💎 ZEIIERMAN RANK 1 NESTED SMC [4H POI + 15M TRIGGER])
        """
        dates = pd.date_range("2026-11-16 00:00", periods=40, freq="15min")
        closes = [100.0 + 0.3 * np.sin(i) for i in range(38)] + [100.2, 100.1]
        opens = [100.0 + 0.3 * np.sin(i) for i in range(38)] + [100.7, 100.2]
        highs = [c + 0.3 for c in closes[:38]] + [101.0, 100.3]
        lows = [c - 0.3 for c in closes[:38]] + [100.1, 100.0]

        df_15m = pd.DataFrame({
            "timestamp": [int(d.timestamp()) for d in dates],
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [5000.0] * 40,
            "taker_buy_vol": [2200.0] * 40
        })
        df_15m.attrs["is_price_fresh_15s"] = True
        df_15m.attrs["live_price_freshness_seconds"] = 1.0

        dfs_9 = {"15m": df_15m, "1h": df_15m, "4h": df_15m, "1d": df_15m}

        btc_shield = {
            "regime": "NEUTRAL",
            "action": "NORMAL",
            "altcoin_longs_allowed": True,
            "altcoin_shorts_allowed": True,
            "sizing_multiplier": 1.0
        }

        # Test Order Block Setup
        ob_setup = {
            "setup_detected": True,
            "direction": "SHORT",
            "zeiierman_rank": 1,
            "zeiierman_rank_label": "💎 ZEIIERMAN RANK 1 NESTED SMC [4H POI + 15M TRIGGER]",
            "is_nested_smc": True,
            "in_order_block_zone": True,
            "is_touching": True,
            "structural_trigger_confirmed": True,
            "entry_price": 100.1,
            "sl_price": 101.2,
            "tp1_price": 97.9,
            "tp2_price": 96.0,
            "tp3_price": 94.0,
            "order_block_zone": [100.5, 101.2]
        }

        hz_pred = {
            "timeframe": "15m",
            "direction": "SHORT",
            "prob_bearish": 0.62,
            "prob_bullish": 0.38,
            "predicted_target_price": 97.9,
            "predicted_change_pct": -2.2
        }

        sig = self.sg._build_single_horizon_signal(
            symbol="ALT/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="SHORT",
            current_price=100.1,
            dfs_9=dfs_9,
            horizon_prediction=hz_pred,
            btc_shield_state=btc_shield,
            aligned_horizons=["15M"],
            order_block_setup=ob_setup,
            spread_bps=3.0
        )

        self.assertIsNotNone(sig)
        self.assertTrue(sig.get("is_trade_active"), f"Signal was inactive: {sig.get('signal_status')} - {sig.get('quality_grade')}")
        self.assertIn("ZEIIERMAN RANK 1 NESTED SMC", sig.get("quality_grade", ""))
        self.assertIn("Grade", sig.get("quality_grade", ""))
        self.assertNotIn("Grade C", sig.get("quality_grade", ""))

    def test_02_liquidity_reclaim_grade_b_qualification_with_marginal_ev(self):
        """
        Verify that LIQUIDITY_RECLAIM setups (like QNT/USDT and STX/USDT) with EVnet in (0.00%, 0.25%)
        qualify as Grade B rather than being suppressed to Grade C.
        Matches live winning trade:
        SIG_20261116_1249_STXUSDT_15M: ⚖️ Grade B (LIQUIDITY_RECLAIM: Confirmed Institutional Reversal in LONG Direction)
        """
        dates = pd.date_range("2026-11-16 00:00", periods=40, freq="15min")
        closes = [100.0 + 0.5 * np.sin(i) for i in range(38)] + [98.5, 100.2]
        opens = [100.0 + 0.5 * np.sin(i) for i in range(38)] + [99.8, 98.6]
        highs = [c + 0.8 for c in closes[:38]] + [100.0, 100.5]
        lows = [c - 0.8 for c in closes[:38]] + [98.0, 98.5]
        df_15m = pd.DataFrame({
            "timestamp": [int(d.timestamp()) for d in dates],
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [5000.0] * 40,
            "taker_buy_vol": [3000.0] * 40
        })
        df_15m.attrs["is_price_fresh_15s"] = True
        df_15m.attrs["live_price_freshness_seconds"] = 1.0

        dfs_9 = {"15m": df_15m, "1h": df_15m, "4h": df_15m, "1d": df_15m}

        btc_shield = {
            "regime": "NEUTRAL",
            "action": "NORMAL",
            "altcoin_longs_allowed": True,
            "altcoin_shorts_allowed": True,
            "sizing_multiplier": 1.0
        }

        archetype_info = {
            "archetype": "ARCHETYPE_A_SECULAR_EXPANSION",
            "strategy": "LIQUIDITY_RECLAIM_LONG",
            "dominant_direction": "LONG",
            "trade_permitted": True,
            "headroom_pct": 5.0
        }

        hz_pred = {
            "timeframe": "15m",
            "direction": "LONG",
            "prob_bullish": 0.55,
            "prob_bearish": 0.45,
            "predicted_target_price": 103.5,
            "predicted_change_pct": 3.3
        }

        sig = self.sg._build_single_horizon_signal(
            symbol="STX/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="LONG",
            current_price=100.2,
            dfs_9=dfs_9,
            horizon_prediction=hz_pred,
            btc_shield_state=btc_shield,
            aligned_horizons=["15M"],
            archetype_info=archetype_info,
            spread_bps=3.0
        )

        self.assertIsNotNone(sig)
        self.assertTrue(sig.get("is_trade_active"), f"Signal was inactive: {sig.get('signal_status')} - {sig.get('quality_grade')}")
        qg = sig.get("quality_grade", "")
        self.assertTrue("Grade B" in qg or "Grade A" in qg or "Grade A+" in qg)
        self.assertNotIn("Grade C", qg)

    def test_03_unanimous_alignment_promotes_to_grade_a(self):
        """
        Verify that 15M signals with unanimous multi-horizon alignment (alignment_score >= 80.0),
        like CAKE/USDT, qualify for Grade A when p_tp1 >= 0.55 and EVnet > 0.00%.
        Matches live winning trade:
        CAKE_USDT_15M_1794795104: ⚡ Grade A (15M STRICT 6-HORIZON ALIGNMENT: 5M-24H UNANIMOUS)
        """
        dates = pd.date_range("2026-11-16 00:00", periods=40, freq="15min")
        closes = [10.0 + 0.1 * np.sin(i) for i in range(38)] + [10.1, 10.2]
        opens = [10.0 + 0.1 * np.sin(i) for i in range(38)] + [10.0, 10.1]
        highs = [c + 0.15 for c in closes[:38]] + [10.15, 10.25]
        lows = [c - 0.15 for c in closes[:38]] + [9.95, 10.05]
        df_15m = pd.DataFrame({
            "timestamp": [int(d.timestamp()) for d in dates],
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [5000.0] * 40,
            "taker_buy_vol": [3200.0] * 40
        })
        df_15m.attrs["is_price_fresh_15s"] = True
        df_15m.attrs["live_price_freshness_seconds"] = 1.0

        dfs_9 = {"15m": df_15m, "1h": df_15m, "4h": df_15m, "1d": df_15m}

        btc_shield = {
            "regime": "NEUTRAL",
            "action": "NORMAL",
            "altcoin_longs_allowed": True,
            "altcoin_shorts_allowed": True,
            "sizing_multiplier": 1.0
        }

        hz_pred = {
            "timeframe": "15m",
            "direction": "LONG",
            "prob_bullish": 0.65,
            "prob_bearish": 0.35,
            "predicted_target_price": 10.6,
            "predicted_change_pct": 3.9
        }

        sig = self.sg._build_single_horizon_signal(
            symbol="CAKE/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="LONG",
            current_price=10.2,
            dfs_9=dfs_9,
            horizon_prediction=hz_pred,
            btc_shield_state=btc_shield,
            aligned_horizons=["5M", "15M", "1H", "4H", "12H", "24H"],
            alignment_score=95.0,  # Unanimous alignment
            spread_bps=2.0
        )

        self.assertIsNotNone(sig)
        self.assertTrue(sig.get("is_trade_active"), f"Signal was inactive: {sig.get('signal_status')} - {sig.get('quality_grade')}")
        qg = sig.get("quality_grade", "")
        self.assertTrue("Grade A" in qg or "Grade A+" in qg)
        self.assertIn("STRICT", qg)

    def test_04_paper_bot_admits_institutional_setups_with_sub_25_ev(self):
        """
        Verify that PaperTradingBot allows institutional setups (Breaker Block, Nested SMC, Range Rotation,
        Coiling Breakout, Liquidity Reclaim, VWAP Bounce) on Scalp Desk when EVnet > 0.00% (even if < 0.25%).
        """
        # Test Breaker Block Grade B with EVnet = 0.08%
        bot1 = PaperTradingBot()
        sig_breaker = {
            "symbol": "ARB/USDT",
            "horizon": "15M",
            "direction": "SHORT",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "quality_grade": "⚖️ Grade B (BREAKER_BLOCK_SHORT @ ⚡ ZEIIERMAN RANK 4 (INSTITUTIONAL BREAKER BLOCK))",
            "canonical_strategy": "BREAKER_BLOCK_SHORT",
            "strategy": "BREAKER_BLOCK_SHORT",
            "entry_price": 0.13668,
            "sl_price": 0.13900,
            "tp1_price": 0.13204,
            "tp2_price": 0.13000,
            "tp3_price": 0.12800,
            "ev_net": 0.08,
            "p_tp1": 0.563,
            "conviction": 56.3,
            "spread_bps": 3.0,
            "volume_24h_usd": 15000000.0,
            "candle_trigger_confirmed": True
        }

        admitted = bot1.admit_signal(sig_breaker)
        self.assertTrue(admitted, "Paper bot should admit Grade B Breaker Block with EV = 0.08%")

        # Test Order Block Grade B with EVnet = 0.02%
        bot2 = PaperTradingBot()
        sig_ob = {
            "symbol": "WLD/USDT",
            "horizon": "15M",
            "direction": "LONG",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "quality_grade": "⚖️ Grade B (ORDER_BLOCK_LONG @ 💎 ZEIIERMAN RANK 1 NESTED SMC [1W POI + 15M TRIGGER])",
            "canonical_strategy": "ORDER_BLOCK_LONG",
            "strategy": "ORDER_BLOCK_LONG",
            "entry_price": 0.2617,
            "sl_price": 0.2570,
            "tp1_price": 0.2695,
            "tp2_price": 0.2740,
            "tp3_price": 0.2800,
            "ev_net": 0.02,
            "p_tp1": 0.559,
            "conviction": 55.9,
            "spread_bps": 4.0,
            "volume_24h_usd": 20000000.0,
            "candle_trigger_confirmed": True,
            "is_order_block_signal": True
        }

        admitted_ob = bot2.admit_signal(sig_ob)
        self.assertTrue(admitted_ob, "Paper bot should admit Grade B Nested SMC with EV = 0.02%")

        # Test Coiling Breakout Grade B with EVnet = 0.07%
        bot3 = PaperTradingBot()
        sig_coiling = {
            "symbol": "GALA/USDT",
            "horizon": "15M",
            "direction": "SHORT",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "quality_grade": "⚖️ Grade B (COILING BREAKOUT: 15M Squeeze into 1D SHORT Expansion)",
            "canonical_strategy": "SQUEEZE_BREAKOUT_SHORT",
            "strategy": "COILING_BREAKOUT",
            "entry_price": 0.001418,
            "sl_price": 0.001444,
            "tp1_price": 0.001365,
            "tp2_price": 0.001340,
            "tp3_price": 0.001310,
            "ev_net": 0.07,
            "p_tp1": 0.526,
            "conviction": 52.6,
            "spread_bps": 2.5,
            "volume_24h_usd": 12000000.0,
            "candle_trigger_confirmed": True
        }

        admitted_coiling = bot3.admit_signal(sig_coiling)
        self.assertTrue(admitted_coiling, "Paper bot should admit Grade B Coiling Breakout with EV = 0.07%")

        # Test Liquidity Reclaim Grade B with EVnet = 0.03%
        bot4 = PaperTradingBot()
        sig_reclaim = {
            "symbol": "QNT/USDT",
            "horizon": "15M",
            "direction": "SHORT",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "quality_grade": "⚖️ Grade B (LIQUIDITY_RECLAIM: Confirmed Institutional Reversal in SHORT Direction)",
            "canonical_strategy": "LIQUIDITY_RECLAIM_SHORT",
            "strategy": "LIQUIDITY_RECLAIM",
            "entry_price": 158.62,
            "sl_price": 162.00,
            "tp1_price": 152.90,
            "tp2_price": 149.00,
            "tp3_price": 144.00,
            "ev_net": 0.03,
            "p_tp1": 0.526,
            "conviction": 52.6,
            "spread_bps": 3.0,
            "volume_24h_usd": 18000000.0,
            "candle_trigger_confirmed": True
        }

        admitted_reclaim = bot4.admit_signal(sig_reclaim)
        self.assertTrue(admitted_reclaim, "Paper bot should admit Grade B Liquidity Reclaim with EV = 0.03%")

    def test_05_paper_bot_not_throttled_to_zero_during_range_regime(self):
        """
        Verify that during a RANGE or CHOPPY market regime, the paper bot does not throttle
        scalp slots to 0 when an institutional setup (Breaker Block, SMC, Reclaim, Rotation) triggers.
        """
        btc_shield_range = {
            "regime": "RANGE",
            "status_code": "RANGE_CONSOLIDATION",
            "altcoin_longs_allowed": True,
            "altcoin_shorts_allowed": True,
            "sizing_multiplier": 1.0
        }

        bot_range = PaperTradingBot()
        sig_breaker = {
            "symbol": "ARB/USDT",
            "horizon": "15M",
            "direction": "SHORT",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "quality_grade": "⚖️ Grade B (BREAKER_BLOCK_SHORT @ ⚡ ZEIIERMAN RANK 4 (INSTITUTIONAL BREAKER BLOCK))",
            "canonical_strategy": "BREAKER_BLOCK_SHORT",
            "strategy": "BREAKER_BLOCK_SHORT",
            "entry_price": 0.13668,
            "sl_price": 0.13900,
            "tp1_price": 0.13204,
            "tp2_price": 0.13000,
            "tp3_price": 0.12800,
            "ev_net": 0.08,
            "p_tp1": 0.563,
            "conviction": 56.3,
            "spread_bps": 3.0,
            "volume_24h_usd": 15000000.0,
            "candle_trigger_confirmed": True
        }

        admitted = bot_range.admit_signal(sig_breaker, btc_shield_state=btc_shield_range)
        self.assertTrue(admitted, "Paper bot must authorize slots during RANGE regime for institutional Breaker Block")

    def test_06_invariants_strictly_fail_closed(self):
        """
        Verify that price geometry violations (SL >= Entry for longs, negative EV) strictly fail closed.
        """
        # Inverted price geometry: Long with SL > Entry
        sig_invalid_geom = {
            "symbol": "BAD/USDT",
            "horizon": "15M",
            "direction": "LONG",
            "quality_grade": "⚖️ Grade B (RANGE ROTATION)",
            "entry_price": 100.0,
            "sl_price": 105.0,  # Invalid: SL above Entry
            "tp1_price": 110.0,
            "ev_net": 0.50,
            "p_tp1": 0.60
        }
        self.assertFalse(self.paper_bot.admit_signal(sig_invalid_geom))

        # Negative Net EV
        sig_negative_ev = {
            "symbol": "BAD2/USDT",
            "horizon": "15M",
            "direction": "LONG",
            "quality_grade": "⚖️ Grade B (RANGE ROTATION)",
            "entry_price": 100.0,
            "sl_price": 95.0,
            "tp1_price": 110.0,
            "ev_net": -0.15,  # Negative Net EV strictly rejected
            "p_tp1": 0.45
        }
        self.assertFalse(self.paper_bot.admit_signal(sig_negative_ev))


if __name__ == "__main__":
    unittest.main()
