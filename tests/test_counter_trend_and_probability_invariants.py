import unittest
import numpy as np
import pandas as pd
from unittest.mock import MagicMock, patch
from app.engine.signals.signal_generator import SignalGenerationSystem
from app.quant_v16.expectancy import ExpectancyResult, PathProbabilities
from app.quant_v16.costs import CostBreakdown, ExecutionAssumption

class TestCounterTrendAndProbabilityInvariants(unittest.TestCase):
    """
    Forensic Verification Suite for Counter-Trend Invariants, Directional Superiority,
    and Expectancy Grade Integrity (Remediating Incident AERO_USDT_1H_1794118996).
    """

    def setUp(self):
        self.sig_sys = SignalGenerationSystem()

    def _create_downtrend_df(self, n=50, start_price=0.6265, end_price=0.6041):
        prices = np.linspace(start_price, end_price, n)
        df = pd.DataFrame({
            "open": prices * 1.001,
            "high": prices * 1.003,
            "low": prices * 0.997,
            "close": prices,
            "volume": np.random.uniform(50000, 100000, n),
            "taker_buy_vol": np.random.uniform(15000, 35000, n) # TBR ~ 0.35 - 0.40 (Heavy selling)
        })
        return df

    def test_01_aero_forensic_incident_fail_closed(self):
        """
        Forensic Case Study AERO_USDT_1H_1794118996:
        An asset in a 6-hour downtrend touches a historical breaker block at 0.6058.
        Under updated invariants:
        1. Passive OB cannot flip direction to LONG without MSS.
        2. Sub-50% probability (P(TP1) = 48.6%, P(SL) = 51.4%) strictly fails closed.
        3. Never awarded Grade A+ with marginal EV (+0.012%).
        """
        df_1h = self._create_downtrend_df(50, 0.6265, 0.6041)
        dfs_9 = {"1h": df_1h, "15m": df_1h.iloc[-15:].copy(), "4h": df_1h.iloc[-30:].copy()}

        passive_ob = {
            "setup_detected": True,
            "direction": "LONG",
            "strategy": "BREAKER_BLOCK_LONG",
            "block_type": "BULLISH_BREAKER_BLOCK",
            "zeiierman_rank": 4,
            "zeiierman_rank_label": "⚡ ZEIIERMAN RANK 4 (INSTITUTIONAL BREAKER BLOCK)",
            "structural_trigger_confirmed": True,
            "is_turtle_soup": False,
            "has_confirmed_mss_reversal": False,
            "active_block": {
                "ob_high": 0.615,
                "ob_low": 0.6051,
                "mss_broken_level": 0.6214,
                "liquidity_swept": False # No liquidity swept!
            },
            "entry_price": 0.6058,
            "sl_price": 0.599985,
            "tp1_price": 0.622055,
            "tp2_price": 0.758242,
            "tp3_price": 0.8944,
            "conviction": 84.0
        }

        btc_shield = {"regime": "RANGE", "v16_regime": "RANGE", "altcoin_longs_allowed": True, "altcoin_shorts_allowed": True}

        # Mock meta labeler to return empirical sub-50% probability matching AERO incident
        with patch.object(self.sig_sys.meta_labeler, "evaluate_signal", return_value={"win_probability": 0.498, "win_probability_pct": 49.8, "passed_meta_gate": True}):
            sig = self.sig_sys._build_single_horizon_signal(
                symbol="AERO/USDT",
                horizon_label="1H",
                tf_key="1h",
                direction="SHORT", # Qualified macro trend was SHORT
                current_price=0.6058,
                dfs_9=dfs_9,
                horizon_prediction={"classifier_votes": "3/5", "regressor_votes": "3/5", "predicted_change_pct": 0.012},
                btc_shield_state=btc_shield,
                aligned_horizons=["15m", "1h", "4h"],
                order_block_setup=passive_ob
            )

        self.assertIsNotNone(sig)
        # 1. Trade MUST NOT be active
        self.assertFalse(sig["is_trade_active"])
        # 2. Quality grade must NOT be Grade A+
        self.assertNotIn("Grade A+", sig["quality_grade"])
        # 3. Status must reflect failure to pass directional probability or taker flow
        self.assertIn("HOLD_VETOED", sig["signal_status"])

    def test_02_passive_order_block_cannot_invert_htf_downtrend(self):
        """
        Anti-Inversion Invariant:
        When direction is SHORT, an opposing passive Order Block without confirmed MSS
        cannot flip direction to LONG.
        """
        df_1h = self._create_downtrend_df()
        dfs_9 = {"1h": df_1h}

        counter_trend_ob = {
            "setup_detected": True,
            "direction": "LONG",
            "structural_trigger_confirmed": True,
            "is_turtle_soup": False,
            "has_confirmed_mss_reversal": False,
            "active_block": {"liquidity_swept": False},
            "entry_price": 0.6050,
            "sl_price": 0.5990,
            "tp1_price": 0.6200,
            "tp2_price": 0.6300,
            "tp3_price": 0.6400
        }

        btc_shield = {"regime": "RANGE", "altcoin_longs_allowed": True, "altcoin_shorts_allowed": True}

        sig = self.sig_sys._build_single_horizon_signal(
            symbol="TEST/USDT",
            horizon_label="1H",
            tf_key="1h",
            direction="SHORT",
            current_price=0.6050,
            dfs_9=dfs_9,
            horizon_prediction={"predicted_change_pct": -1.5},
            btc_shield_state=btc_shield,
            aligned_horizons=["1h"],
            order_block_setup=counter_trend_ob
        )

        self.assertIsNotNone(sig)
        # Direction MUST remain SHORT (not flipped to LONG)
        self.assertEqual(sig["direction"], "SHORT")

    def test_03_sub_50_percent_win_probability_hard_veto(self):
        """
        Directional Superiority Invariant:
        Any setup where calibrated P(TP1) < 50.0% or P(SL) >= P(TP1) is rejected immediately,
        even if nominal R:R is high (e.g. 1:3.0).
        """
        df = self._create_downtrend_df()
        dfs_9 = {"1h": df}
        btc_shield = {"regime": "BULL_TREND", "altcoin_longs_allowed": True, "altcoin_shorts_allowed": True}

        curr_p = float(df["close"].iloc[-1])
        # Mock meta labeler to return 48.0% probability (< 50%)
        with patch.object(self.sig_sys.meta_labeler, "evaluate_signal", return_value={"win_probability": 0.48, "win_probability_pct": 48.0, "passed_meta_gate": True}):
            sig = self.sig_sys._build_single_horizon_signal(
                symbol="TEST/USDT",
                horizon_label="1H",
                tf_key="1h",
                direction="LONG",
                current_price=curr_p,
                dfs_9=dfs_9,
                horizon_prediction={"predicted_change_pct": 3.0},
                btc_shield_state=btc_shield,
                aligned_horizons=["1h"],
                volume_24h_usd=25_000_000.0,
                spread_bps=2.0
            )

        self.assertIsNotNone(sig)
        self.assertFalse(sig["is_trade_active"])
        self.assertEqual(sig["signal_status"], "HOLD_VETOED_BY_SUB_50_WIN_PROBABILITY")
        self.assertIn("Sub-50%", sig["quality_grade"])

    def test_04_expectancy_grade_integrity_prevents_false_a_plus(self):
        """
        Expectancy Grade Integrity:
        A setup with marginal net return (< 0.50%) or win probability < 0.60
        can NEVER be awarded Grade A+.
        """
        df = self._create_downtrend_df()
        dfs_9 = {"1h": df}
        btc_shield = {"regime": "BULL_TREND", "altcoin_longs_allowed": True, "altcoin_shorts_allowed": True}

        # Mock modest win probability (52%) which produces modest EV
        with patch.object(self.sig_sys.meta_labeler, "evaluate_signal", return_value={"win_probability": 0.52, "win_probability_pct": 52.0, "passed_meta_gate": True}):
            sig = self.sig_sys._build_single_horizon_signal(
                symbol="TEST/USDT",
                horizon_label="1H",
                tf_key="1h",
                direction="LONG",
                current_price=100.0,
                dfs_9=dfs_9,
                horizon_prediction={"predicted_change_pct": 1.5},
                btc_shield_state=btc_shield,
                aligned_horizons=["1h"]
            )

        self.assertIsNotNone(sig)
        if sig["is_trade_active"]:
            # Grade MUST NOT be Grade A+
            self.assertNotIn("Grade A+", sig["quality_grade"])

    def test_05_adverse_taker_flow_vetoes_long_in_range_regime(self):
        """
        Unconditional Order Flow Confluence:
        When BTC is in RANGE, adverse taker selling (TBR < 0.48) halts Long entries.
        """
        # Create DF with heavy selling volume (TBR = 0.25)
        n = 30
        prices = np.linspace(100.0, 99.0, n)
        df_sell_flow = pd.DataFrame({
            "open": prices,
            "high": prices * 1.002,
            "low": prices * 0.998,
            "close": prices,
            "volume": [10000.0] * n,
            "taker_buy_vol": [2500.0] * n # TBR = 0.25
        })
        dfs_9 = {"1h": df_sell_flow, "4h": df_sell_flow}
        btc_shield = {"regime": "RANGE", "v16_regime": "RANGE", "altcoin_longs_allowed": True, "altcoin_shorts_allowed": True}

        with patch.object(self.sig_sys.meta_labeler, "evaluate_signal", return_value={"win_probability": 0.70, "win_probability_pct": 70.0, "passed_meta_gate": True}):
            sig = self.sig_sys._build_single_horizon_signal(
                symbol="TEST/USDT",
                horizon_label="1H",
                tf_key="1h",
                direction="LONG",
                current_price=99.0,
                dfs_9=dfs_9,
                horizon_prediction={"predicted_change_pct": 2.0},
                btc_shield_state=btc_shield,
                aligned_horizons=["1h"],
                volume_24h_usd=25_000_000.0,
                spread_bps=2.0
            )

        self.assertIsNotNone(sig)
        self.assertFalse(sig["is_trade_active"])
        self.assertEqual(sig["signal_status"], "HOLD_VETOED_BY_TAKER_DELTA_CONFLUENCE")

if __name__ == "__main__":
    unittest.main()
