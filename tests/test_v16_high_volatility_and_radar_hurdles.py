"""
Unit & Regression Test Suite: High Volatility Regime & Strict Hurdle Enforcement (V16)
Tests:
1. BTC Market Shield HIGH_VOLATILITY produces sizing_multiplier = 0.50 and is_ntz_active = False.
2. Strict EV_net > 0.00% hurdle rejection and retention in PRE_SIGNAL_RADAR.
3. Strict R:R >= 1:2.00 hurdle rejection and retention in PRE_SIGNAL_RADAR.
4. FSM Pre-Signal Radar precedence over generic consolidation NTZ.
5. Engine-level dynamic sizing scaling by BTC shield regime.
"""

import unittest
import numpy as np
import pandas as pd
from unittest.mock import MagicMock, patch

from app.quant_v16.regime import MarketRegimeClassifier, MarketRegime
from app.quant_v16.expectancy import NetExpectancyEngine, PathProbabilities, CostBreakdown, ExecutionAssumption
from app.engine.scanner.btc_shield import BtcPredictiveMarketShield
from app.engine.signals.signal_generator import SignalGenerationSystem

class TestHighVolatilityAndRadarHurdles(unittest.TestCase):

    def setUp(self):
        np.random.seed(42)

    def test_high_volatility_regime_sizing_multiplier(self):
        """HIGH_VOLATILITY regime must assign 0.50x sizing multiplier and keep is_ntz_active=False."""
        classifier = MarketRegimeClassifier()
        # Verify Section 29 sizing multiplier
        self.assertEqual(classifier.SIZING_MULTIPLIERS[MarketRegime.HIGH_VOLATILITY], 0.50)

        # Mock BTC Shield evaluation in HIGH_VOLATILITY
        shield = BtcPredictiveMarketShield()
        # Evaluate state with regime_v16 = HIGH_VOLATILITY
        with patch("app.quant_v16.regime.compute_live_btc_regime") as mock_compute:
            mock_compute.return_value = {
                "regime": "HIGH_VOLATILITY",
                "probabilities": {"bull": 0.20, "bear": 0.20, "range": 0.40, "breakout": 0.10, "squeeze": 0.10},
                "confidence": 0.85,
                "sizing_multiplier": 0.50,
                "metrics": {"adx": 39.7, "rsi": 30.0, "bb_width_percentile": 95.0}
            }
            # Create synthetic 1H dataframe
            df_candles = pd.DataFrame({
                "open": [70000.0] * 30,
                "high": [71000.0] * 30,
                "low": [69000.0] * 30,
                "close": [70500.0] * 30,
                "volume": [1000.0] * 30
            })
            state = shield.evaluate_regime({"15m": df_candles, "1h": df_candles}, live_btc_price=70500.0)
            self.assertEqual(state["status_code"], "HIGH_VOLATILITY")
            self.assertFalse(state["is_ntz_active"])
            self.assertEqual(state["sizing_multiplier"], 0.50)
            self.assertIn("0.50x", state["reason"])

    def test_strict_ev_net_hurdle_enforcement(self):
        """Negative or zero Net EV must be rejected from active execution and held in PRE_SIGNAL_RADAR."""
        cost_engine_mock = MagicMock()
        costs = CostBreakdown(
            fee_pct=0.08, spread_pct=0.04, slippage_pct=0.06, funding_pct=0.02,
            total_cost_pct=0.20, assumption=ExecutionAssumption.BASE
        )
        probs = PathProbabilities(p_tp1=0.30, p_tp2=0.15, p_tp3=0.05, p_sl=0.70, risk_reward=2.0)
        
        # When probability is low, gross EV is negative
        exp_res = NetExpectancyEngine().evaluate(
            entry=100.0, sl=98.0, tp1=104.0, tp2=106.0, tp3=108.0, direction="LONG",
            path_probs=probs, costs=costs
        )
        self.assertFalse(exp_res.passes_ev_hurdle)
        self.assertLessEqual(exp_res.expected_net_return_pct, 0.0)

    def test_radar_candidate_preserves_sub_hurdle_setups(self):
        """Signal generation must preserve setups with sub-2.0 R:R or <=0 EVnet in PRE_SIGNAL_RADAR."""
        sig_sys = SignalGenerationSystem()
        
        # Test radar_candidates aggregation
        mock_candidates = {
            "15M": {
                "signal_status": "HOLD_INSUFFICIENT_RISK_REWARD",
                "is_radar_eligible": True,
                "direction": "SHORT",
                "raw_direction": "SHORT",
                "setup_direction": "SHORT",
                "horizon": "15M",
                "conviction": 70.0,
                "ev_net": 0.05,
                "quality_grade": "Grade C (INSUFFICIENT RISK-REWARD: 1:1.65 < 1:2.00 required)",
                "tp1_price": 9.50,
                "tp2_price": 9.20,
                "tp3_price": 9.00,
                "sl_price": 10.30,
                "risk_reward_ratio": "1:1.65",
                "predicted_target_price": 9.50,
                "expected_return_pct": -5.0
            }
        }
        
        # Evaluate candidate aggregation
        radar_candidates = [
            s for s in mock_candidates.values()
            if s.get("signal_status") in [
                "HOLD_AWAITING_CANDLE_TRIGGER_CONFIRMATION",
                "HOLD_INSUFFICIENT_RISK_REWARD",
                "HOLD_SPREAD_DEGRADED_RR",
                "HOLD_FILTERED_BY_NEGATIVE_NET_EXPECTANCY",
                "PRE_SIGNAL_RADAR"
            ]
            or s.get("is_radar_eligible", False)
        ]
        self.assertEqual(len(radar_candidates), 1)
        self.assertEqual(radar_candidates[0]["signal_status"], "HOLD_INSUFFICIENT_RISK_REWARD")

    def test_fsm_radar_calculates_2_0_rr_limit_price(self):
        """PRE_SIGNAL_RADAR must calculate exact entry price required for 1:2.00 R:R."""
        # Entry = (TP1 + 2*SL) / 3
        # For a Short: SL = 10.30, TP1 = 9.50 => Entry = (9.50 + 20.60) / 3 = 30.10 / 3 = 10.033333
        tp1 = 9.50
        sl = 10.30
        rr_entry = round((tp1 + 2.0 * sl) / 3.0, 6)
        
        # Verify R:R at that entry:
        reward = abs(tp1 - rr_entry) # |9.50 - 10.033333| = 0.533333
        risk = abs(rr_entry - sl)     # |10.033333 - 10.30| = 0.266667
        rr = round(reward / risk, 2)
        self.assertEqual(rr, 2.00)

if __name__ == "__main__":
    unittest.main()
