"""
QUANT EDGE V16: Institutional Expected Value Engine & Canonical Financial Accounting
Specifications:
- Section 19: Canonical Expected Value Engine across multiple unit systems:
    1. Return on Position Notional (% price movement)
    2. Return on Allocated Capital (% margin return = notional * leverage)
    3. R-Multiples (payoff normalized by initial risk at stop loss: EV / R_sl)
    4. Monetary Realized Value (USD payoff based on position size)
- Section 20: Comprehensive Execution Friction Accounting:
    Friction = Entry Fee + Exit Fee + Entry Spread + Exit Spread + Entry Slippage + Exit Slippage + Funding Drag
- Section 21: Minimum EV Hurdles and Exact Grade Boundaries:
    A+: Expected Net Return >= 1.00%
    A:  Expected Net Return >= 0.50%
    B:  Expected Net Return >= 0.25%
    WATCH: Expected Net Return > 0.00%
    NO TRADE: Expected Net Return <= 0.00%
- Section 22: Risk/Reward Requirements (R:R >= 1.2 for scalps, >= 1.5 baseline, preferred >= 2.0)
- Execution Policies:
    - SINGLE_TARGET_TP1: 100% position closed at TP1 (matching baseline paper execution)
    - MULTI_TRANCHE_SCALE: 50% TP1, 30% TP2, 20% TP3 with breakeven stop ratchets
"""

import math
import os
from enum import Enum
from typing import Dict, Any, Tuple, Optional
from dataclasses import dataclass, field

from .probability import PathProbabilities
from .costs import CostBreakdown, ExecutionAssumption

class ExpectancyUnit(str, Enum):
    """
    Explicit Canonical Unit Systems for Institutional Expectancy.
    Guarantees no conflation between percentage returns, leverage-scaled capital returns,
    dimensionless R-multiples, and dollar-denominated monetary amounts.
    """
    RETURN_ON_NOTIONAL_PCT = "RETURN_ON_NOTIONAL_PCT"       # Delta price % on total position notional
    RETURN_ON_ALLOCATED_CAPITAL_PCT = "RETURN_ON_ALLOCATED_CAPITAL_PCT" # Return on initial margin = notional % * leverage
    R_MULTIPLES = "R_MULTIPLES"                             # Units of initial risk at SL: EV / R_sl
    MONETARY_USD = "MONETARY_USD"                           # Net expected dollar PnL: (EV_pct / 100) * position_size_usd

class ExecutionPolicy(str, Enum):
    """Execution policy governing exit tranche distribution and stop ratchets."""
    SINGLE_TARGET_TP1 = "SINGLE_TARGET_TP1"                 # 100% closed at TP1
    MULTI_TRANCHE_SCALE = "MULTI_TRANCHE_SCALE"             # 50% TP1, 30% TP2, 20% TP3 with BE ratchets

@dataclass
class CanonicalFriction:
    """Itemized execution friction breakdown preventing double-counting."""
    entry_fee_pct: float
    exit_fee_pct: float
    entry_spread_pct: float
    exit_spread_pct: float
    entry_slippage_pct: float
    exit_slippage_pct: float
    funding_drag_pct: float
    total_friction_pct: float

    def to_usd(self, position_notional_usd: float) -> Dict[str, float]:
        """Converts percentage friction components to USD for a given position size."""
        factor = position_notional_usd / 100.0
        return {
            "entry_fee_usd": round(self.entry_fee_pct * factor, 4),
            "exit_fee_usd": round(self.exit_fee_pct * factor, 4),
            "entry_spread_usd": round(self.entry_spread_pct * factor, 4),
            "exit_spread_usd": round(self.exit_spread_pct * factor, 4),
            "entry_slippage_usd": round(self.entry_slippage_pct * factor, 4),
            "exit_slippage_usd": round(self.exit_slippage_pct * factor, 4),
            "funding_drag_usd": round(self.funding_drag_pct * factor, 4),
            "total_friction_usd": round(self.total_friction_pct * factor, 4)
        }

@dataclass
class ExpectancyResult:
    """Comprehensive mathematical expectancy evaluation across all institutional metrics."""
    # Target and stop return percentages on position notional
    r_tp1_pct: float
    r_tp2_pct: float
    r_tp3_pct: float
    r_sl_pct: float
    risk_reward: float

    # Canonical Expectancy Metrics
    ev_gross_pct: float                     # Gross expected return on position notional (%)
    costs_total_pct: float                  # Total execution friction (%)
    expected_net_return_pct: float          # Net expected return on position notional (%)

    # Multi-Unit System Representations
    ev_net_notional_pct: float              # Return on position notional (%)
    ev_net_capital_pct: float               # Return on allocated capital / margin (%)
    ev_net_r_multiple: float                # Payoff normalized by initial risk (R)
    ev_net_monetary_usd: float              # Expected dollar PnL ($)

    # Decision Gates & Classification
    passes_ev_hurdle: bool
    grade_boundary: str                     # 'A+', 'A', 'B', 'WATCH', or 'NO_TRADE'
    execution_policy: ExecutionPolicy
    fill_fraction: float                    # Partial fill fraction (0.0 < f <= 1.0)
    decision_reason: str = ""
    friction: Optional[CanonicalFriction] = None

    # Diagnostic metadata
    unit_breakdown: Dict[str, float] = field(default_factory=dict)

class NetExpectancyEngine:
    """
    Institutional Net Expectancy Engine.
    Computes mathematically rigorous payoff expectations accounting for:
    - Directional entry/exit price geometries
    - Execution friction (Maker/taker fees, crossing spread, slippage, funding drag)
    - Single-target vs. multi-tranche scaling policies
    - Canonical unit conversions (Notional %, Capital %, R-Multiples, USD)
    - Partial fills and fill ratios
    - Exact grade boundary hurdles
    """

    @staticmethod
    def validate_inputs(
        entry: float,
        sl: float,
        tp1: float,
        direction: str,
        path_probs: PathProbabilities,
        leverage: float = 1.0,
        fill_fraction: float = 1.0
    ) -> Tuple[bool, str]:
        """Enforces mathematical invariants before evaluation."""
        if entry <= 0.0 or sl <= 0.0 or tp1 <= 0.0:
            return False, f"Non-positive prices provided: entry={entry}, sl={sl}, tp1={tp1}"

        dir_upper = str(direction).upper()
        is_long = dir_upper in ["LONG", "BULLISH", "BUY"]
        is_short = dir_upper in ["SHORT", "BEARISH", "SELL"]

        if not (is_long or is_short):
            return False, f"Invalid direction '{direction}'; must be LONG or SHORT"

        if is_long:
            if not (sl < entry < tp1):
                return False, f"Long boundary violation: must have SL ({sl}) < Entry ({entry}) < TP1 ({tp1})"
        else:
            if not (sl > entry > tp1):
                return False, f"Short boundary violation: must have SL ({sl}) > Entry ({entry}) > TP1 ({tp1})"

        p_sum = path_probs.p_tp1 + path_probs.p_sl
        if p_sum > 1.0001:
            return False, f"Probability sum P(TP1) + P(SL) = {p_sum:.4f} exceeds 1.0"

        if path_probs.p_tp1 < 0.0 or path_probs.p_sl < 0.0:
            return False, f"Negative probabilities: p_tp1={path_probs.p_tp1}, p_sl={path_probs.p_sl}"

        if leverage < 1.0:
            return False, f"Leverage must be >= 1.0, got {leverage}"

        if fill_fraction <= 0.0 or fill_fraction > 1.0:
            return False, f"Fill fraction must be in (0.0, 1.0], got {fill_fraction}"

        return True, ""

    @staticmethod
    def calculate_returns(
        entry: float,
        sl: float,
        tp1: float,
        tp2: float,
        tp3: float,
        direction: str
    ) -> Tuple[float, float, float, float, float]:
        """
        Calculates percentage price movements for TP1, TP2, TP3, and SL on position notional.
        Returns: (r_tp1_pct, r_tp2_pct, r_tp3_pct, r_sl_pct, risk_reward)
        """
        dir_upper = str(direction).upper()
        is_long = dir_upper in ["LONG", "BULLISH", "BUY"]

        if is_long:
            r1 = ((tp1 - entry) / entry) * 100.0
            r2 = ((tp2 - entry) / entry) * 100.0
            r3 = ((tp3 - entry) / entry) * 100.0
            r_sl = ((entry - sl) / entry) * 100.0
        else:
            r1 = ((entry - tp1) / entry) * 100.0
            r2 = ((entry - tp2) / entry) * 100.0
            r3 = ((entry - tp3) / entry) * 100.0
            r_sl = ((sl - entry) / entry) * 100.0

        # R:R is computed using TP2 for campaign target (Section 22)
        rr = r2 / max(1e-6, r_sl) if r_sl > 0 else 0.0
        return round(r1, 4), round(r2, 4), round(r3, 4), round(r_sl, 4), round(rr, 2)

    @classmethod
    def resolve_grade_boundary(cls, expected_net_return_pct: float, risk_reward: float) -> Tuple[str, bool, str]:
        """
        Documents and applies exact signal grade boundaries matching Section 21:
        A+: Expected Net Return >= 1.00%
        A:  Expected Net Return >= 0.50%
        B:  Expected Net Return >= 0.25%
        WATCH: Expected Net Return > 0.00%
        NO TRADE: Expected Net Return <= 0.00%
        """
        min_ev_hurdle = float(os.getenv("MIN_NET_EV_HURDLE", "0.10"))
        if risk_reward < 1.2:
            return "NO_TRADE", False, f"Unfavorable Risk:Reward ({risk_reward:.2f} < 1.2 minimum threshold)"

        if expected_net_return_pct >= 1.00:
            return "A+", True, f"Grade A+ Expectancy ({expected_net_return_pct:+.2f}% net return)"
        elif expected_net_return_pct >= 0.50:
            return "A", True, f"Grade A Expectancy ({expected_net_return_pct:+.2f}% net return)"
        elif expected_net_return_pct >= 0.25:
            return "B", True, f"Grade B Expectancy ({expected_net_return_pct:+.2f}% net return)"
        elif expected_net_return_pct >= min_ev_hurdle and expected_net_return_pct > 0.00:
            return "B", True, f"Grade B Expectancy ({expected_net_return_pct:+.2f}% net return)"
        elif expected_net_return_pct > 0.00:
            return "WATCH", False, f"Blocked: Marginal Net Expectancy ({expected_net_return_pct:+.2f}% < {min_ev_hurdle:.2f}% threshold)"
        else:
            return "NO_TRADE", False, f"Negative/Zero Net Expectancy ({expected_net_return_pct:+.2f}% after costs)"

    def evaluate(
        self,
        entry: float,
        sl: float,
        tp1: float,
        tp2: float,
        tp3: float,
        direction: str,
        path_probs: PathProbabilities,
        costs: CostBreakdown,
        allocation_weights: Tuple[float, float, float] = (0.50, 0.30, 0.20),
        policy: ExecutionPolicy = ExecutionPolicy.SINGLE_TARGET_TP1,
        leverage: float = 1.0,
        position_size_usd: float = 1000.0,
        fill_fraction: float = 1.0,
        expected_expiry_return_pct: float = 0.0
    ) -> ExpectancyResult:
        """
        Canonical Institutional Evaluation:
        Computes mathematically rigorous net expectation across Notional, Capital, R-Multiple, and USD units.
        """
        # 1. Input Invariant Validation
        is_valid, err_msg = self.validate_inputs(
            entry=entry,
            sl=sl,
            tp1=tp1,
            direction=direction,
            path_probs=path_probs,
            leverage=leverage,
            fill_fraction=fill_fraction
        )
        if not is_valid:
            r1, r2, r3, r_sl, rr = 0.0, 0.0, 0.0, 0.0, 0.0
            return ExpectancyResult(
                r_tp1_pct=r1,
                r_tp2_pct=r2,
                r_tp3_pct=r3,
                r_sl_pct=r_sl,
                risk_reward=rr,
                ev_gross_pct=0.0,
                costs_total_pct=costs.total_cost_pct if costs else 0.0,
                expected_net_return_pct=-999.0,
                ev_net_notional_pct=-999.0,
                ev_net_capital_pct=-999.0,
                ev_net_r_multiple=-999.0,
                ev_net_monetary_usd=-999.0,
                passes_ev_hurdle=False,
                grade_boundary="NO_TRADE",
                execution_policy=policy,
                fill_fraction=fill_fraction,
                decision_reason=f"REJECTED: {err_msg}"
            )

        # 2. Geometric Returns
        r1, r2, r3, r_sl, rr = self.calculate_returns(entry, sl, tp1, tp2, tp3, direction)

        # 3. Itemize Canonical Friction (Preventing Double Counting)
        entry_fee = costs.fee_pct * 0.50
        exit_fee = costs.fee_pct * 0.50
        entry_spread = costs.spread_pct * 0.50
        exit_spread = costs.spread_pct * 0.50
        entry_slip = costs.slippage_pct * 0.50
        exit_slip = costs.slippage_pct * 0.50
        funding_drag = costs.funding_pct

        total_friction = round(float(costs.total_cost_pct), 4)
        friction = CanonicalFriction(
            entry_fee_pct=round(entry_fee, 4),
            exit_fee_pct=round(exit_fee, 4),
            entry_spread_pct=round(entry_spread, 4),
            exit_spread_pct=round(exit_spread, 4),
            entry_slippage_pct=round(entry_slip, 4),
            exit_slippage_pct=round(exit_slip, 4),
            funding_drag_pct=round(funding_drag, 4),
            total_friction_pct=total_friction
        )

        # 4. Compute Gross Expectancy Based on Execution Policy
        p_tp1 = path_probs.p_tp1
        p_sl = path_probs.p_sl
        p_exp = max(0.0, round(1.0 - p_tp1 - p_sl, 4))

        if policy == ExecutionPolicy.SINGLE_TARGET_TP1:
            # Single-target execution (matching current paper trading bot):
            # EV = P(TP1)*R1 - P(SL)*R_SL + P(EXP)*R_EXP
            ev_gross = (p_tp1 * r1) - (p_sl * r_sl) + (p_exp * expected_expiry_return_pct)
        else:
            # Multi-tranche scale out (50% TP1, 30% TP2, 20% TP3 runner with BE ratchet)
            w1, w2, w3 = allocation_weights
            p_tp2_cond = getattr(path_probs, "p_tp2_given_tp1", 0.65)
            p_tp3_cond = getattr(path_probs, "p_tp3_given_tp2", 0.55)

            # If TP1 is hit:
            # - Tranche 1 locks r1
            # - Tranches 2 and 3 have stop moved to entry (BE, loss = 0)
            # - Tranche 2 reaches TP2 with conditional prob p_tp2_cond locking r2, else BE (0)
            # - Tranche 3 reaches TP3 with conditional prob p_tp3_cond locking r3, else trailing lock at r1
            payoff_if_tp1_reached = (
                (w1 * r1) +
                (w2 * (p_tp2_cond * r2 + (1.0 - p_tp2_cond) * 0.0)) +
                (w3 * (p_tp2_cond * (p_tp3_cond * r3 + (1.0 - p_tp3_cond) * r1) + (1.0 - p_tp2_cond) * 0.0))
            )
            payoff_if_sl_reached = -1.0 * r_sl
            payoff_if_expiry = expected_expiry_return_pct

            ev_gross = (p_tp1 * payoff_if_tp1_reached) + (p_sl * payoff_if_sl_reached) + (p_exp * payoff_if_expiry)

        # 5. Partial Fill Adjustment
        effective_ev_gross = ev_gross * fill_fraction
        effective_friction = friction.total_friction_pct * fill_fraction

        # 6. Canonical Unit Conversions
        ev_net_notional = effective_ev_gross - effective_friction
        ev_net_capital = ev_net_notional * leverage
        r_risk = max(1e-6, r_sl)
        ev_net_r = ev_net_notional / r_risk
        effective_position_usd = position_size_usd * fill_fraction
        ev_net_monetary = (ev_net_notional / 100.0) * effective_position_usd

        # 7. Grade Boundary and Gate Hurdles
        grade, passes, reason = self.resolve_grade_boundary(ev_net_notional, rr)

        unit_dict = {
            ExpectancyUnit.RETURN_ON_NOTIONAL_PCT.value: round(ev_net_notional, 4),
            ExpectancyUnit.RETURN_ON_ALLOCATED_CAPITAL_PCT.value: round(ev_net_capital, 4),
            ExpectancyUnit.R_MULTIPLES.value: round(ev_net_r, 4),
            ExpectancyUnit.MONETARY_USD.value: round(ev_net_monetary, 4),
        }

        return ExpectancyResult(
            r_tp1_pct=r1,
            r_tp2_pct=r2,
            r_tp3_pct=r3,
            r_sl_pct=r_sl,
            risk_reward=rr,
            ev_gross_pct=round(effective_ev_gross, 4),
            costs_total_pct=round(effective_friction, 4),
            expected_net_return_pct=round(ev_net_notional, 4),
            ev_net_notional_pct=round(ev_net_notional, 4),
            ev_net_capital_pct=round(ev_net_capital, 4),
            ev_net_r_multiple=round(ev_net_r, 4),
            ev_net_monetary_usd=round(ev_net_monetary, 4),
            passes_ev_hurdle=passes,
            grade_boundary=grade,
            execution_policy=policy,
            fill_fraction=fill_fraction,
            decision_reason=reason,
            friction=friction,
            unit_breakdown=unit_dict
        )

