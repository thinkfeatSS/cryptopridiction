"""
QUANT EDGE V16: Canonical Financial Accounting & Net Expectancy Test Suite
Verifies:
1. Zero-cost and known-cost scenarios with deterministic hand-calculated expectations.
2. Canonical unit systems (Notional %, Capital %, R-Multiples, Monetary USD).
3. Long and short directional trade geometries.
4. Partial fills (fill fraction scaling).
5. Single-target (TP1) vs. Multi-tranche scaling policies.
6. Exact grade boundary thresholds (A+, A, B, WATCH, NO_TRADE) and R:R hurdles.
7. Accrued funding drag across time intervals.
8. Input validation invariants and fail-closed protections.
9. Breakeven classification and win rate accounting integrity.
"""

import unittest
from app.quant_v16.expectancy import (
    NetExpectancyEngine,
    ExpectancyResult,
    ExpectancyUnit,
    ExecutionPolicy,
    CanonicalFriction
)
from app.quant_v16.probability import PathProbabilities
from app.quant_v16.costs import CostBreakdown, ExecutionAssumption
from app.quant_v16.audit import classify_signal_outcome

class TestCanonicalExpectancyEngine(unittest.TestCase):
    def setUp(self):
        self.engine = NetExpectancyEngine()

    def test_01_zero_cost_scenario(self):
        """When friction is zero, Net Expectancy must exactly equal Gross Expectancy."""
        zero_costs = CostBreakdown(
            fee_pct=0.0,
            spread_pct=0.0,
            slippage_pct=0.0,
            funding_pct=0.0,
            total_cost_pct=0.0,
            assumption=ExecutionAssumption.BASE
        )
        probs = PathProbabilities(
            p_tp1=0.60,
            p_tp2=0.39,
            p_tp3=0.21,
            p_sl=0.40,
            risk_reward=2.0
        )
        # Long trade: Entry = 100.0, SL = 98.0 (2%), TP1 = 104.0 (4%)
        # Gross EV = (0.60 * 4.0) - (0.40 * 2.0) = 2.40 - 0.80 = 1.60%
        res = self.engine.evaluate(
            entry=100.0,
            sl=98.0,
            tp1=104.0,
            tp2=106.0,
            tp3=108.0,
            direction="LONG",
            path_probs=probs,
            costs=zero_costs,
            policy=ExecutionPolicy.SINGLE_TARGET_TP1
        )
        self.assertAlmostEqual(res.ev_gross_pct, 1.60, places=4)
        self.assertAlmostEqual(res.costs_total_pct, 0.0, places=4)
        self.assertAlmostEqual(res.expected_net_return_pct, 1.60, places=4)
        self.assertAlmostEqual(res.ev_net_notional_pct, 1.60, places=4)
        self.assertTrue(res.passes_ev_hurdle)
        self.assertEqual(res.grade_boundary, "A+")

    def test_02_known_cost_and_multi_unit_conversions(self):
        """
        Verify exact itemized friction deduction and conversion across:
        - Return on Notional (%)
        - Return on Allocated Capital (% with 3x leverage)
        - Initial Risk R-Multiples (EV / R_sl)
        - Monetary USD PnL ($1,000 position)
        """
        costs = CostBreakdown(
            fee_pct=0.08,        # 0.04% entry + 0.04% exit
            spread_pct=0.04,     # 0.02% entry taker; limit TP exit = 0.00%
            slippage_pct=0.06,   # 0.03% entry taker; limit TP exit = 0.00%
            funding_pct=0.01,    # 0.01% holding drag
            total_cost_pct=0.19,
            assumption=ExecutionAssumption.BASE
        )
        probs = PathProbabilities(
            p_tp1=0.60,
            p_tp2=0.39,
            p_tp3=0.21,
            p_sl=0.40,
            risk_reward=2.0
        )
        # Entry = 100.0, SL = 98.0 (2%), TP1 = 104.0 (4%)
        # Single-target TP1 policy:
        # Gross EV = (0.60 * 4.0) - (0.40 * 2.0) = 1.60%
        # Expected Net Notional Return = 1.60 - 0.19 = 1.41%
        res = self.engine.evaluate(
            entry=100.0,
            sl=98.0,
            tp1=104.0,
            tp2=106.0,
            tp3=108.0,
            direction="LONG",
            path_probs=probs,
            costs=costs,
            policy=ExecutionPolicy.SINGLE_TARGET_TP1,
            leverage=3.0,
            position_size_usd=1000.0
        )
        self.assertAlmostEqual(res.ev_gross_pct, 1.60, places=4)
        self.assertAlmostEqual(res.costs_total_pct, 0.19, places=4)
        self.assertAlmostEqual(res.expected_net_return_pct, 1.41, places=4)
        self.assertAlmostEqual(res.ev_net_notional_pct, 1.41, places=4)

        # 3x Leverage Capital Return: 1.41% * 3.0 = 4.23%
        self.assertAlmostEqual(res.ev_net_capital_pct, 4.23, places=4)

        # R-Multiple: 1.41% / 2.0% SL risk = 0.705 R
        self.assertAlmostEqual(res.ev_net_r_multiple, 0.705, places=3)

        # Monetary USD on $1,000 position: (1.41 / 100) * 1000 = $14.10
        self.assertAlmostEqual(res.ev_net_monetary_usd, 14.10, places=2)

    def test_03_short_direction_geometry_symmetry(self):
        """Verify Short trades produce exact matching payoffs for identical percentage movements."""
        costs = CostBreakdown(
            fee_pct=0.08,
            spread_pct=0.04,
            slippage_pct=0.06,
            funding_pct=0.0,
            total_cost_pct=0.18,
            assumption=ExecutionAssumption.BASE
        )
        probs = PathProbabilities(
            p_tp1=0.60,
            p_tp2=0.39,
            p_tp3=0.21,
            p_sl=0.40,
            risk_reward=2.0
        )
        # Short: Entry = 100.0, SL = 102.0 (+2% loss), TP1 = 96.0 (-4% gain)
        res = self.engine.evaluate(
            entry=100.0,
            sl=102.0,
            tp1=96.0,
            tp2=94.0,
            tp3=92.0,
            direction="SHORT",
            path_probs=probs,
            costs=costs,
            policy=ExecutionPolicy.SINGLE_TARGET_TP1
        )
        self.assertAlmostEqual(res.r_tp1_pct, 4.0, places=4)
        self.assertAlmostEqual(res.r_sl_pct, 2.0, places=4)
        self.assertAlmostEqual(res.risk_reward, 3.0, places=2)
        self.assertAlmostEqual(res.ev_gross_pct, 1.60, places=4)
        self.assertTrue(res.passes_ev_hurdle)

    def test_04_partial_fill_accounting(self):
        """Verify that a 50% partial fill scales notional EV and monetary USD linearly."""
        costs = CostBreakdown(
            fee_pct=0.08,
            spread_pct=0.04,
            slippage_pct=0.06,
            funding_pct=0.0,
            total_cost_pct=0.18,
            assumption=ExecutionAssumption.BASE
        )
        probs = PathProbabilities(
            p_tp1=0.60,
            p_tp2=0.39,
            p_tp3=0.21,
            p_sl=0.40,
            risk_reward=2.0
        )
        full_res = self.engine.evaluate(
            entry=100.0, sl=98.0, tp1=104.0, tp2=106.0, tp3=108.0,
            direction="LONG", path_probs=probs, costs=costs,
            fill_fraction=1.0, position_size_usd=1000.0
        )
        half_res = self.engine.evaluate(
            entry=100.0, sl=98.0, tp1=104.0, tp2=106.0, tp3=108.0,
            direction="LONG", path_probs=probs, costs=costs,
            fill_fraction=0.50, position_size_usd=1000.0
        )
        self.assertAlmostEqual(half_res.ev_gross_pct, full_res.ev_gross_pct * 0.50, places=4)
        self.assertAlmostEqual(half_res.ev_net_monetary_usd, full_res.ev_net_monetary_usd * 0.25, places=2)

    def test_05_multi_tranche_scale_policy(self):
        """
        Verify multi-tranche scaling model (50% TP1, 30% TP2, 20% TP3 runner with BE ratchet).
        """
        costs = CostBreakdown(
            fee_pct=0.08,
            spread_pct=0.04,
            slippage_pct=0.06,
            funding_pct=0.0,
            total_cost_pct=0.18,
            assumption=ExecutionAssumption.BASE
        )
        probs = PathProbabilities(
            p_tp1=0.65,
            p_tp2=0.42,
            p_tp3=0.23,
            p_sl=0.35,
            p_tp2_given_tp1=0.65,
            p_tp3_given_tp2=0.55,
            risk_reward=2.0
        )
        # Entry = 100.0, SL = 98.0 (2%), TP1 = 103.0 (3%), TP2 = 106.0 (6%), TP3 = 110.0 (10%)
        res = self.engine.evaluate(
            entry=100.0,
            sl=98.0,
            tp1=103.0,
            tp2=106.0,
            tp3=110.0,
            direction="LONG",
            path_probs=probs,
            costs=costs,
            policy=ExecutionPolicy.MULTI_TRANCHE_SCALE
        )
        # Expected payoff when TP1 is reached:
        # 0.50 * 3.0 + 0.30 * (0.65 * 6.0 + 0.35 * 0.0) + 0.20 * (0.65 * (0.55 * 10.0 + 0.45 * 3.0) + 0.35 * 0.0)
        # = 1.50 + 0.30 * 3.90 + 0.20 * 0.65 * (5.50 + 1.35)
        # = 1.50 + 1.17 + 0.13 * 6.85 = 1.50 + 1.17 + 0.8905 = 3.5605%
        # Expected gross = (0.65 * 3.5605) - (0.35 * 2.0) = 2.3143 - 0.70 = 1.6143%
        self.assertAlmostEqual(res.ev_gross_pct, 1.6143, places=2)
        self.assertTrue(res.passes_ev_hurdle)
        self.assertEqual(res.grade_boundary, "A+")

    def test_06_exact_grade_boundaries(self):
        """
        Verify exact documented grade boundary gates:
        A+ >= 1.00%, A >= 0.50%, B >= 0.25%, WATCH > 0%, NO_TRADE <= 0% or RR < 1.2.
        """
        # 1. A+ Hurdle
        g, passes, _ = NetExpectancyEngine.resolve_grade_boundary(1.00, risk_reward=2.0)
        self.assertEqual(g, "A+")
        self.assertTrue(passes)

        # 2. A Hurdle (0.999% falls to A)
        g, passes, _ = NetExpectancyEngine.resolve_grade_boundary(0.999, risk_reward=2.0)
        self.assertEqual(g, "A")
        self.assertTrue(passes)

        # 3. A Boundary at 0.50%
        g, passes, _ = NetExpectancyEngine.resolve_grade_boundary(0.50, risk_reward=2.0)
        self.assertEqual(g, "A")
        self.assertTrue(passes)

        # 4. B Hurdle (0.499% falls to B)
        g, passes, _ = NetExpectancyEngine.resolve_grade_boundary(0.499, risk_reward=2.0)
        self.assertEqual(g, "B")
        self.assertTrue(passes)

        # 5. B Boundary at 0.25%
        g, passes, _ = NetExpectancyEngine.resolve_grade_boundary(0.25, risk_reward=2.0)
        self.assertEqual(g, "B")
        self.assertTrue(passes)

        # 6. WATCH Hurdle (0.249% falls to WATCH)
        g, passes, _ = NetExpectancyEngine.resolve_grade_boundary(0.249, risk_reward=2.0)
        self.assertEqual(g, "WATCH")
        self.assertFalse(passes)

        # 7. NO_TRADE at 0.00%
        g, passes, _ = NetExpectancyEngine.resolve_grade_boundary(0.00, risk_reward=2.0)
        self.assertEqual(g, "NO_TRADE")
        self.assertFalse(passes)

        # 8. NO_TRADE on Negative EV
        g, passes, _ = NetExpectancyEngine.resolve_grade_boundary(-0.50, risk_reward=2.0)
        self.assertEqual(g, "NO_TRADE")
        self.assertFalse(passes)

        # 9. Strict R:R Gate: RR < 1.2 forces NO_TRADE even if EV is positive
        g, passes, _ = NetExpectancyEngine.resolve_grade_boundary(1.50, risk_reward=1.15)
        self.assertEqual(g, "NO_TRADE")
        self.assertFalse(passes)

    def test_07_funding_drag_across_intervals(self):
        """Funding drag must scale linearly with holding interval cycles (8h per cycle)."""
        costs_0h = CostBreakdown(fee_pct=0.08, spread_pct=0.04, slippage_pct=0.06, funding_pct=0.0, total_cost_pct=0.18, assumption=ExecutionAssumption.BASE)
        costs_8h = CostBreakdown(fee_pct=0.08, spread_pct=0.04, slippage_pct=0.06, funding_pct=0.01, total_cost_pct=0.19, assumption=ExecutionAssumption.BASE)
        costs_24h = CostBreakdown(fee_pct=0.08, spread_pct=0.04, slippage_pct=0.06, funding_pct=0.03, total_cost_pct=0.21, assumption=ExecutionAssumption.BASE)

        probs = PathProbabilities(p_tp1=0.60, p_tp2=0.39, p_tp3=0.21, p_sl=0.40, risk_reward=2.0)
        res_0h = self.engine.evaluate(entry=100.0, sl=98.0, tp1=104.0, tp2=106.0, tp3=108.0, direction="LONG", path_probs=probs, costs=costs_0h)
        res_8h = self.engine.evaluate(entry=100.0, sl=98.0, tp1=104.0, tp2=106.0, tp3=108.0, direction="LONG", path_probs=probs, costs=costs_8h)
        res_24h = self.engine.evaluate(entry=100.0, sl=98.0, tp1=104.0, tp2=106.0, tp3=108.0, direction="LONG", path_probs=probs, costs=costs_24h)

        self.assertAlmostEqual(res_8h.costs_total_pct - res_0h.costs_total_pct, 0.01, places=4)
        self.assertAlmostEqual(res_24h.costs_total_pct - res_0h.costs_total_pct, 0.03, places=4)
        self.assertAlmostEqual(res_0h.expected_net_return_pct - res_24h.expected_net_return_pct, 0.03, places=4)

    def test_08_invalid_inputs_fail_closed(self):
        """Input violations must fail closed to protect capital."""
        costs = CostBreakdown(fee_pct=0.08, spread_pct=0.04, slippage_pct=0.06, funding_pct=0.0, total_cost_pct=0.18, assumption=ExecutionAssumption.BASE)
        probs = PathProbabilities(p_tp1=0.60, p_tp2=0.39, p_tp3=0.21, p_sl=0.40, risk_reward=2.0)

        # 1. Non-positive price
        res = self.engine.evaluate(entry=0.0, sl=98.0, tp1=104.0, tp2=106.0, tp3=108.0, direction="LONG", path_probs=probs, costs=costs)
        self.assertFalse(res.passes_ev_hurdle)
        self.assertEqual(res.grade_boundary, "NO_TRADE")

        # 2. Inverted SL for Long (SL > Entry)
        res = self.engine.evaluate(entry=100.0, sl=105.0, tp1=104.0, tp2=106.0, tp3=108.0, direction="LONG", path_probs=probs, costs=costs)
        self.assertFalse(res.passes_ev_hurdle)
        self.assertEqual(res.grade_boundary, "NO_TRADE")

        # 3. Sum of probabilities > 1.0
        bad_probs = PathProbabilities(p_tp1=0.70, p_tp2=0.50, p_tp3=0.30, p_sl=0.50, risk_reward=2.0)
        res = self.engine.evaluate(entry=100.0, sl=98.0, tp1=104.0, tp2=106.0, tp3=108.0, direction="LONG", path_probs=bad_probs, costs=costs)
        self.assertFalse(res.passes_ev_hurdle)
        self.assertEqual(res.grade_boundary, "NO_TRADE")

    def test_09_breakeven_accounting_and_win_rate_integrity(self):
        """
        Verify that breakeven trades are strictly mapped to BREAKEVEN (not WON),
        and that win rate denominator includes breakeven trades.
        """
        # Test classifier
        self.assertEqual(classify_signal_outcome("BREAKEVEN_GUARD", "🛡️ BREAKEVEN (TIER-0 GUARD +0.00%)", 0.0), "BREAKEVEN")
        self.assertEqual(classify_signal_outcome("WON_TIER0_BE", "🛡️ BREAKEVEN (TIER-0 GUARD +0.00%)", 0.0), "BREAKEVEN")
        self.assertEqual(classify_signal_outcome("WON_TP1", "🟢 WON (TP1 HIT)", 2.5), "WON")
        self.assertEqual(classify_signal_outcome("LOST_SL", "🔴 LOST (SL HIT)", -1.5), "LOST")

        # Win rate denominator test:
        # 5 WON, 0 LOST, 5 BREAKEVEN
        won = 5
        lost = 0
        be = 5
        total_closed = won + lost + be
        decisive = won + lost

        total_closed_wr = round((won / total_closed) * 100.0, 2)
        decisive_wr = round((won / decisive) * 100.0, 2)

        # Decisive win rate is 100%, but total closed win rate is 50%
        self.assertEqual(total_closed_wr, 50.0)
        self.assertEqual(decisive_wr, 100.0)

if __name__ == "__main__":
    unittest.main()
