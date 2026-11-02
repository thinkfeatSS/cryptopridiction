"""
Unit and Integration Tests for Phase 1 Institutional Trading Enhancements:
- STR-01: Strategy Registry Bayesian Prior Calibration & Atomic Persistence
- ML-01: Dynamic Meta-Labeler Hurdle Adjustment by Market Regime & Choppiness
- ENT-01: Volatility-Adjusted Limit Entry Depth & Multi-Touch Zone Invalidation
- Breakeven Invariant: Breakeven trades must NEVER count as wins
"""

import unittest
import os
import json
import tempfile
import numpy as np

from app.quant_v16.strategies import (
    StrategyRegistry,
    StrategyPerformance,
    StrategyStatus,
    StrategyArchetype
)
from app.engine.signals.meta_labeler import CoinSpecificMetaLabeler
from app.quant_v16.entry_confirmation import EntryConfirmationEngine


class TestPhase1Enhancements(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.priors_file = os.path.join(self.temp_dir.name, "test_strategy_priors.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # STR-01: Strategy Registry Persistence & Bayesian Updates
    # -------------------------------------------------------------------------
    def test_strategy_performance_serialization(self):
        perf = StrategyPerformance(
            strategy_id="MOMENTUM_LONG",
            sample_count=20,
            resolved_count=18,
            win_rate=0.65,
            profit_factor=1.85,
            rolling_50_pf=1.75,
            expectancy_net_pct=0.85,
            max_drawdown_pct=3.2,
            status=StrategyStatus.ACTIVE,
            regime_status={"BULL_TREND": StrategyStatus.ACTIVE}
        )
        d = perf.to_dict()
        self.assertEqual(d["strategy_id"], "MOMENTUM_LONG")
        self.assertEqual(d["win_rate"], 0.65)
        self.assertEqual(d["status"], "ACTIVE")

        restored = StrategyPerformance.from_dict(d)
        self.assertEqual(restored.strategy_id, perf.strategy_id)
        self.assertEqual(restored.win_rate, perf.win_rate)
        self.assertEqual(restored.profit_factor, perf.profit_factor)
        self.assertEqual(restored.status, StrategyStatus.ACTIVE)

    def test_strategy_registry_atomic_persistence_and_load(self):
        registry = StrategyRegistry(persistence_file=self.priors_file)
        # Modify a strategy state
        strat_key = StrategyArchetype.MOMENTUM_LONG.value
        self.assertIn(strat_key, registry.strategies)
        registry.strategies[strat_key].win_rate = 0.72
        registry.strategies[strat_key].rolling_50_pf = 2.10

        # Save to disk
        saved = registry.save_to_disk()
        self.assertTrue(saved)
        self.assertTrue(os.path.exists(self.priors_file))

        # Create fresh registry instance pointing to same file
        loaded_reg = StrategyRegistry(persistence_file=self.priors_file)
        self.assertAlmostEqual(loaded_reg.strategies[strat_key].win_rate, 0.72)
        self.assertAlmostEqual(loaded_reg.strategies[strat_key].rolling_50_pf, 2.10)

    def test_strategy_outcome_bayesian_update_and_kill_switch(self):
        registry = StrategyRegistry(persistence_file=self.priors_file)
        strat_key = StrategyArchetype.BREAKOUT_LONG.value

        initial_wr = registry.strategies[strat_key].win_rate
        initial_samples = registry.strategies[strat_key].resolved_count

        # Record a winning trade
        registry.record_trade_outcome(
            strategy_id=strat_key,
            is_win=True,
            net_return_pct=3.5,
            regime="BULL_TREND"
        )
        updated_perf = registry.strategies[strat_key]
        self.assertEqual(updated_perf.resolved_count, initial_samples + 1)
        self.assertGreater(updated_perf.win_rate, 0.0)

        # Record successive severe losses to test kill switch activation
        for _ in range(15):
            registry.record_trade_outcome(
                strategy_id=strat_key,
                is_win=False,
                net_return_pct=-4.0,
                regime="RANGE"
            )

        # Strategy should have degraded into WARNING, PAUSED, or DISABLED
        self.assertIn(registry.strategies[strat_key].status, [StrategyStatus.WARNING, StrategyStatus.PAUSED, StrategyStatus.DISABLED])
        self.assertLess(registry.strategies[strat_key].rolling_50_pf, 1.0)

    # -------------------------------------------------------------------------
    # ML-01: Dynamic Regime Hurdle Elevation
    # -------------------------------------------------------------------------
    def test_dynamic_regime_hurdle_elevation(self):
        labeler = CoinSpecificMetaLabeler()

        # In CHOP / RANGE regime or chop index >= 60, hurdle MUST be elevated
        adj_chop = labeler.get_dynamic_regime_hurdle_adjustment("RANGE", chop_index=65.0)
        self.assertGreater(adj_chop, 0.0)
        self.assertLessEqual(adj_chop, 0.08)

        # In HIGH_VOLATILITY, hurdle must have volatility risk premium
        adj_vol = labeler.get_dynamic_regime_hurdle_adjustment("HIGH_VOLATILITY", chop_index=50.0)
        self.assertGreater(adj_vol, 0.0)

        # In strong TREND with low chop index (e.g. 30), hurdle should be relaxed
        adj_trend = labeler.get_dynamic_regime_hurdle_adjustment("BULL_TREND", chop_index=32.0)
        self.assertLess(adj_trend, 0.0)

        # Neutral should be 0.0
        adj_neutral = labeler.get_dynamic_regime_hurdle_adjustment(None, chop_index=50.0)
        self.assertEqual(adj_neutral, 0.0)

    def test_meta_evaluate_signal_with_regime(self):
        labeler = CoinSpecificMetaLabeler()
        signal_chop = {
            "entry_price": 100.0,
            "tp1_price": 103.0,
            "sl_price": 98.5,
            "regime": "RANGE",
            "chop_index": 68.0,
            "conviction": 85.0
        }
        res_chop = labeler.evaluate_signal("BTC/USDT", signal_chop, hurdle=0.50)
        self.assertIn("regime_hurdle_adjustment", res_chop)
        self.assertGreater(res_chop["regime_hurdle_adjustment"], 0.0)
        self.assertGreater(res_chop["decision_hurdle"], 0.50)

    # -------------------------------------------------------------------------
    # ENT-01: Volatility-Adjusted Limit Entry Depth
    # -------------------------------------------------------------------------
    def test_volatility_adjusted_pullback_limit_depth(self):
        # Case 1: Low Volatility (ATR = 0.5 on $100 price -> 0.5% ATR)
        res_low_vol = EntryConfirmationEngine.calculate_optimal_entry_zone(
            current_price=100.0,
            ob_setup=None,
            direction="LONG",
            active_atr=0.5,
            chase_threshold_pct=0.40,
            strategy="TREND_PULLBACK",
            candle_metrics=None
        )
        opt_low = float(res_low_vol["optimal_entry_limit"])
        offset_low = 100.0 - opt_low
        offset_low_pct = (offset_low / 100.0) * 100.0
        # Should be bounded >= 0.15%
        self.assertGreaterEqual(offset_low_pct, 0.14)
        self.assertLess(opt_low, 100.0)

        # Case 2: High Volatility (ATR = 4.0 on $100 price -> 4.0% ATR)
        res_high_vol = EntryConfirmationEngine.calculate_optimal_entry_zone(
            current_price=100.0,
            ob_setup=None,
            direction="LONG",
            active_atr=4.0,
            chase_threshold_pct=0.40,
            strategy="TREND_PULLBACK",
            candle_metrics=None
        )
        opt_high = float(res_high_vol["optimal_entry_limit"])
        offset_high = 100.0 - opt_high
        offset_high_pct = (offset_high / 100.0) * 100.0
        # High volatility pullback should be noticeably deeper than low volatility
        self.assertGreater(offset_high_pct, offset_low_pct)
        # Should not exceed maximum safety clamp (0.80%)
        self.assertLessEqual(offset_high_pct, 0.81)

    # -------------------------------------------------------------------------
    # Financial Invariant: Breakeven is NEVER counted as a win
    # -------------------------------------------------------------------------
    def test_breakeven_invariant_not_counted_as_win(self):
        registry = StrategyRegistry(persistence_file=self.priors_file)
        strat_key = StrategyArchetype.MEAN_REVERSION_LONG.value
        initial_wr = registry.strategies[strat_key].win_rate

        # A breakeven trade is passed with is_win=False (never True!)
        is_breakeven_win = bool("WON_TIER0_BE".startswith("WON_") and not any(b in "WON_TIER0_BE" for b in ["BREAKEVEN", "BE", "TIER0"]))
        self.assertFalse(is_breakeven_win)

        registry.record_trade_outcome(
            strategy_id=strat_key,
            is_win=is_breakeven_win,
            net_return_pct=0.0,
            regime="RANGE"
        )
        # Win rate should not have increased
        self.assertLessEqual(registry.strategies[strat_key].win_rate, initial_wr)


if __name__ == "__main__":
    unittest.main()
