import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from app.engine.signals.signal_generator import SignalGenerationSystem
from app.engine.execution.paper_trading_bot import PaperTradingBot


class TestLossAvoidanceAndWinningSignals(unittest.TestCase):
    """
    Forensic verification suite for:
    1. Blocking low-edge / toxic losing setups (e.g. CHIP, POL, ZEC, W, RARE, XLM, MMT).
    2. Admitting genuine high-conviction institutional setups (e.g. SENT, ALT, ENA, ARB, PLUME, ATOM).
    """

    def setUp(self):
        self.sg = SignalGenerationSystem()
        self.paper_bot = PaperTradingBot()

    def _create_mock_dfs(self, base_price: float = 100.0, trend: str = "FLAT"):
        dates = pd.date_range("2026-11-18 00:00", periods=40, freq="15min")
        if trend == "DOWN":
            closes = [base_price * (1.0 - 0.0005 * i) for i in range(40)]
        elif trend == "UP":
            closes = [base_price * (1.0 + 0.0005 * i) for i in range(40)]
        else:
            closes = [base_price * (1.0 + 0.0003 * np.sin(i)) for i in range(40)]

        opens = [c * 1.0001 for c in closes]
        highs = [c * 1.0025 for c in closes]
        lows = [c * 0.9975 for c in closes]

        df_15m = pd.DataFrame({
            "timestamp": [int(d.timestamp()) for d in dates],
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [5000000.0] * 40,
            "taker_buy_vol": [2500000.0] * 40
        })
        df_15m.attrs["is_price_fresh_15s"] = True
        df_15m.attrs["live_price_freshness_seconds"] = 1.0

        # Choppy / unaligned higher timeframe data
        c_htf = [base_price * (1.0 - 0.0003 * (i % 6)) for i in range(40)]
        df_htf = pd.DataFrame({
            "timestamp": [int(d.timestamp()) for d in dates],
            "open": c_htf,
            "high": [c * 1.003 for c in c_htf],
            "low": [c * 0.997 for c in c_htf],
            "close": c_htf,
            "volume": [5000000.0] * 40,
            "taker_buy_vol": [2400000.0] * 40
        })
        df_htf.attrs["is_price_fresh_15s"] = True
        df_htf.attrs["live_price_freshness_seconds"] = 1.0

        return {"15m": df_15m, "1h": df_htf, "4h": df_htf, "1d": df_htf}

    def test_01_marginal_ev_without_elite_anchor_is_blocked(self):
        """
        Verify that marginal Net EV setups (< +0.10%) without elite institutional backing
        (like CHIP +0.02%, ZEC +0.04%, POL +0.06%) fail closed and are not admitted.
        """
        from unittest.mock import patch
        from app.quant_v16.expectancy import ExpectancyResult, ExecutionPolicy

        dfs_9 = self._create_mock_dfs(0.03816)
        btc_shield = {"regime": "NEUTRAL", "action": "NORMAL", "altcoin_longs_allowed": True}

        # Mock expectancy result matching CHIP's exact live values (+0.02% Net EV, 55.6% win prob)
        mock_ev = ExpectancyResult(
            r_tp1_pct=3.6, r_tp2_pct=5.4, r_tp3_pct=7.2, r_sl_pct=1.8, risk_reward=2.0,
            ev_gross_pct=0.45, costs_total_pct=0.43, expected_net_return_pct=0.02,
            ev_net_notional_pct=0.02, ev_net_capital_pct=0.02, ev_net_r_multiple=0.01, ev_net_monetary_usd=0.20,
            passes_ev_hurdle=False, grade_boundary="WATCH", execution_policy=ExecutionPolicy.SINGLE_TARGET_TP1, fill_fraction=1.0,
            decision_reason="Blocked: Marginal Net Expectancy (+0.02% < 0.25% threshold)"
        )

        with patch.object(self.sg.expectancy_engine, "evaluate", return_value=mock_ev):
            hz_pred = {
                "timeframe": "15m",
                "direction": "LONG",
                "prob_bullish": 0.556,
                "prob_bearish": 0.444,
                "predicted_target_price": 0.03953,
                "predicted_change_pct": 3.6
            }

            sig = self.sg._build_single_horizon_signal(
                symbol="CHIP/USDT",
                horizon_label="15M",
                tf_key="15m",
                direction="LONG",
                current_price=0.03816,
                dfs_9=dfs_9,
                horizon_prediction=hz_pred,
                btc_shield_state=btc_shield,
                aligned_horizons=["15M"],
                order_block_setup=None,
                volume_24h_usd=5000000.0,
                spread_bps=12.0
            )

        self.assertIsNotNone(sig)
        # Must fail closed: not active, held due to marginal Net EV
        self.assertFalse(sig["is_trade_active"], f"CHIP-like marginal EV setup must not be active: {sig.get('signal_status')}")
        self.assertEqual(sig["signal_status"], "HOLD_MARGINAL_NET_EXPECTANCY")
        self.assertIn("MARGINAL NET EXPECTANCY", sig["quality_grade"])

    def test_02_standalone_engulfing_without_smc_is_blocked(self):
        """
        Verify that standalone BEARISH_ENGULFING (like W/USDT) without Order Block or Liquidity Sweep
        is not treated as institutional SMC and fails admission.
        """
        dfs_9 = self._create_mock_dfs(0.1872)
        btc_shield = {"regime": "NEUTRAL", "action": "NORMAL", "altcoin_shorts_allowed": True}

        hz_pred = {
            "timeframe": "15m",
            "direction": "SHORT",
            "prob_bearish": 0.52,
            "prob_bullish": 0.48,
            "predicted_target_price": 0.1850,
            "predicted_change_pct": -1.2
        }

        sig = self.sg._build_single_horizon_signal(
            symbol="W/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="SHORT",
            current_price=0.1872,
            dfs_9=dfs_9,
            horizon_prediction=hz_pred,
            btc_shield_state=btc_shield,
            aligned_horizons=["15M"],
            order_block_setup=None,
            volume_24h_usd=5000000.0,
            spread_bps=12.0
        )

        self.assertIsNotNone(sig)
        self.assertFalse(sig["is_trade_active"], "Standalone pattern without OB must fail closed")

    def test_03_falling_knife_defense_and_consecutive_loss_quarantine(self):
        """
        Verify that repeated long entries on falling knives (like RARE/USDT) are strictly
        intercepted by the anti-whipsaw falling knife defense and directional quarantine.
        """
        now = datetime.now(timezone.utc)

        # Simulate prior stopped-out trade on RARE/USDT 30 minutes ago at exit price 0.00140
        self.paper_bot.data["closed_trades"] = [
            {
                "symbol": "RARE/USDT",
                "direction": "LONG",
                "entry_price": 0.00142,
                "exit_price": 0.00140,
                "outcome": "LOST",
                "audit_status": "LOST_SL_HIT",
                "exit_reason": "STOP_LOSS",
                "closed_at_utc": (now - timedelta(minutes=30)).isoformat()
            }
        ]

        # Case A: Attempt repeated LONG at lower price 0.00138 (falling knife)
        sig_knife = {
            "symbol": "RARE/USDT",
            "horizon": "15M",
            "direction": "LONG",
            "quality_grade": "⚖️ Grade B (RANGE ROTATION)",
            "entry_price": 0.00138, # Lower than SL exit price 0.00140
            "sl_price": 0.00135,
            "tp1_price": 0.00145,
            "ev_net": 0.20,
            "p_tp1": 0.58
        }
        admitted, reason = self.paper_bot.validate_anti_whipsaw_guard(
            symbol="RARE/USDT",
            direction="LONG",
            norm_horizon="15M",
            signal=sig_knife
        )
        self.assertFalse(admitted, "Falling knife entry below previous SL price must be rejected")
        self.assertIn("Falling knife defense", reason)

        # Case B: Simulate 2 consecutive LONG stop losses within 12h -> Directional quarantine
        self.paper_bot.data["closed_trades"].append({
            "symbol": "RARE/USDT",
            "direction": "LONG",
            "entry_price": 0.00137,
            "exit_price": 0.00135,
            "outcome": "LOST",
            "audit_status": "LOST_SL_HIT",
            "exit_reason": "STOP_LOSS",
            "closed_at_utc": (now - timedelta(minutes=10)).isoformat()
        })

        sig_third_attempt = {
            "symbol": "RARE/USDT",
            "horizon": "15M",
            "direction": "LONG",
            "quality_grade": "⚖️ Grade B (RANGE ROTATION)",
            "entry_price": 0.00136,
            "sl_price": 0.00133,
            "tp1_price": 0.00143,
            "ev_net": 0.25,
            "p_tp1": 0.60
        }
        admitted, reason = self.paper_bot.validate_anti_whipsaw_guard(
            symbol="RARE/USDT",
            direction="LONG",
            norm_horizon="15M",
            signal=sig_third_attempt
        )
        self.assertFalse(admitted, ">=2 consecutive losses in same direction must trigger directional quarantine")
        self.assertIn("Persistent directional drawdown quarantine", reason)

    def test_04_macro_bearish_regime_counter_trend_long_filter(self):
        """
        Verify that in a macro BEARISH regime, altcoin LONG setups require elevated hurdle
        (P(win) >= 58%, Net EV >= 0.15%, RR >= 2.00) and fail closed if sub-hurdle.
        """
        dfs_9 = self._create_mock_dfs(100.0)
        btc_shield_bear = {
            "regime": "BEARISH",
            "action": "DEFENSIVE",
            "status_code": "BEAR_CASCADE_BLACKOUT",
            "altcoin_longs_allowed": True
        }

        # Moderate LONG signal (54% win prob, +0.08% EV) during macro bear cascade
        hz_pred = {
            "timeframe": "15m",
            "direction": "LONG",
            "prob_bullish": 0.54,
            "prob_bearish": 0.46,
            "predicted_target_price": 103.0,
            "predicted_change_pct": 3.0
        }

        sig = self.sg._build_single_horizon_signal(
            symbol="ETH/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="LONG",
            current_price=100.0,
            dfs_9=dfs_9,
            horizon_prediction=hz_pred,
            btc_shield_state=btc_shield_bear,
            aligned_horizons=["15M"],
            volume_24h_usd=5000000.0,
            spread_bps=3.0
        )

        self.assertIsNotNone(sig)
        self.assertFalse(sig["is_trade_active"], "Sub-hurdle counter-trend long in macro bear must fail closed")
        self.assertIn("HOLD", sig["signal_status"])

    def test_05_winning_nested_smc_rank_1_passes_cleanly(self):
        """
        Verify that genuine institutional winning setups (like SENT/USDT Rank 1 Nested SMC)
        are authorized and admitted cleanly.
        """
        dfs_9 = self._create_mock_dfs(0.01922)
        btc_shield = {"regime": "NEUTRAL", "action": "NORMAL", "altcoin_longs_allowed": True}

        ob_setup_nested = {
            "setup_detected": True,
            "direction": "LONG",
            "strategy": "ORDER_BLOCK_LONG",
            "zeiierman_rank": 1,
            "zeiierman_rank_label": "💎 ZEIIERMAN RANK 1 NESTED SMC [4H POI + 15M TRIGGER]",
            "is_nested_smc": True,
            "in_order_block_zone": True,
            "is_touching": True,
            "structural_trigger_confirmed": True,
            "entry_price": 0.01922,
            "sl_price": 0.01876,
            "tp1_price": 0.02014,
            "tp2_price": 0.02100,
            "tp3_price": 0.02200,
            "order_block_zone": [0.01876, 0.01922]
        }

        hz_pred = {
            "timeframe": "15m",
            "direction": "LONG",
            "prob_bullish": 0.58,
            "prob_bearish": 0.42,
            "predicted_target_price": 0.02014,
            "predicted_change_pct": 4.8
        }

        sig = self.sg._build_single_horizon_signal(
            symbol="SENT/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="LONG",
            current_price=0.01922,
            dfs_9=dfs_9,
            horizon_prediction=hz_pred,
            btc_shield_state=btc_shield,
            aligned_horizons=["15M"],
            order_block_setup=ob_setup_nested,
            volume_24h_usd=5000000.0,
            spread_bps=2.0
        )

        self.assertIsNotNone(sig)
        self.assertTrue(sig["is_trade_active"], f"Rank 1 Nested SMC winning setup must be active: {sig.get('signal_status')}")
        self.assertEqual(sig["signal_status"], "ACTIVE_SIGNAL")
        self.assertIn("Grade", sig["quality_grade"])

    def test_06_winning_breaker_block_rank_4_passes_cleanly(self):
        """
        Verify that Breaker Block setups (like ENA/USDT or ARB/USDT)
        are authorized and admitted cleanly.
        """
        dfs_9 = self._create_mock_dfs(0.1184)
        btc_shield = {"regime": "NEUTRAL", "action": "NORMAL", "altcoin_shorts_allowed": True}

        ob_setup_breaker = {
            "setup_detected": True,
            "direction": "SHORT",
            "strategy": "BREAKER_BLOCK_SHORT",
            "zeiierman_rank": 4,
            "zeiierman_rank_label": "⚡ ZEIIERMAN RANK 4 (INSTITUTIONAL BREAKER BLOCK)",
            "in_order_block_zone": True,
            "is_touching": True,
            "structural_trigger_confirmed": True,
            "entry_price": 0.1184,
            "sl_price": 0.12075,
            "tp1_price": 0.1137,
            "tp2_price": 0.1100,
            "tp3_price": 0.1060,
            "order_block_zone": [0.1184, 0.12075]
        }

        hz_pred = {
            "timeframe": "15m",
            "direction": "SHORT",
            "prob_bearish": 0.60,
            "prob_bullish": 0.40,
            "predicted_target_price": 0.1137,
            "predicted_change_pct": -4.0
        }

        sig = self.sg._build_single_horizon_signal(
            symbol="ENA/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="SHORT",
            current_price=0.1184,
            dfs_9=dfs_9,
            horizon_prediction=hz_pred,
            btc_shield_state=btc_shield,
            aligned_horizons=["15M"],
            order_block_setup=ob_setup_breaker,
            volume_24h_usd=5000000.0,
            spread_bps=2.0
        )

        self.assertIsNotNone(sig)
        self.assertTrue(sig["is_trade_active"], f"Rank 4 Breaker Block winning setup must be active: {sig.get('signal_status')}")
        self.assertEqual(sig["signal_status"], "ACTIVE_SIGNAL")
        self.assertIn("Grade", sig["quality_grade"])


if __name__ == "__main__":
    unittest.main()
