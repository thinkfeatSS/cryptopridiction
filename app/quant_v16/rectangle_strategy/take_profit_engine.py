"""
The Only 1 Minute Rectangle Strategy: Take Profit & Reward-to-Risk Engine
Based on Section 1.1, Section 11, and Part 3 (Step 3C) of "The Only 1 Minute Trading Strategy" by Anees Mehdi.

Calculates Take Profit targets using:
1. Priority 1: Next valid M15 structural target (opposing swing high/low)
2. Priority 2: Configured minimum Risk-to-Reward ratio (default 1:2, up to 1:4)
Accounts for exchange trading fees, slippage, and funding drag in net RR validation.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from app.quant_v16.rectangle_strategy.strategy_config import RectangleStrategyConfig
from app.quant_v16.rectangle_strategy.market_structure import SwingPoint
from app.quant_v16.entry_confirmation import format_dynamic_precision


@dataclass
class TakeProfitResult:
    is_valid: bool
    tp1_price: float
    tp2_price: float
    tp3_price: float
    gross_rr: float             # Target 1 gross reward / risk
    net_rr: float               # Net reward / risk after fees & slippage
    rr_string: str              # e.g. "1:2.0"
    target_type: str            # "STRUCTURAL_M15_TARGET" or "CALCULATED_RR_TARGET"
    rejection_reason: Optional[str] = None


class TakeProfitEngine:
    """
    Calculates dynamic Take Profit levels and validates net Risk-to-Reward hurdles.
    """

    def __init__(self, config: Optional[RectangleStrategyConfig] = None):
        self.config = config or RectangleStrategyConfig()

    def calculate_take_profit(
        self,
        direction: str,
        entry_price: float,
        stop_loss_price: float,
        opposing_target: Optional[SwingPoint] = None
    ) -> TakeProfitResult:
        """
        Calculates TP1, TP2, TP3 targets and verifies minimum 1:2 RR.
        """
        if entry_price <= 0 or stop_loss_price <= 0:
            return TakeProfitResult(False, 0.0, 0.0, 0.0, 0.0, 0.0, "1:0", "NONE", "Invalid price inputs")

        risk_amt = abs(entry_price - stop_loss_price)
        if risk_amt < 1e-8:
            return TakeProfitResult(False, 0.0, 0.0, 0.0, 0.0, 0.0, "1:0", "NONE", "Zero risk distance")

        min_rr = self.config.min_risk_reward

        # Friction estimation: 2 legs of taker fees (0.05% * 2 = 0.10%) + 2 legs slippage (0.05% * 2 = 0.10%)
        total_friction_pct = (self.config.taker_fee_pct * 2.0) + (self.config.max_slippage_pct * 2.0)
        friction_amt = entry_price * (total_friction_pct / 100.0)

        if direction == "LONG":
            # Priority 1: Check opposing M15 structural swing high
            tp_structural = None
            if self.config.use_structural_targets and opposing_target and opposing_target.price > entry_price:
                struct_rr = (opposing_target.price - entry_price) / risk_amt
                if struct_rr >= min_rr:
                    tp_structural = opposing_target.price

            # Standard RR multipliers: 2.0, 2.5, 3.5
            calc_tp1 = entry_price + (min_rr * risk_amt)
            calc_tp2 = entry_price + (max(min_rr + 0.5, 2.5) * risk_amt)
            calc_tp3 = entry_price + (max(min_rr + 1.5, 4.0) * risk_amt)

            final_tp1 = tp_structural if (tp_structural and tp_structural < calc_tp2) else calc_tp1
            final_tp2 = max(calc_tp2, final_tp1 + 0.5 * risk_amt)
            final_tp3 = max(calc_tp3, final_tp2 + risk_amt)

            tp1_fmt = format_dynamic_precision(final_tp1)
            tp2_fmt = format_dynamic_precision(final_tp2)
            tp3_fmt = format_dynamic_precision(final_tp3)

            # Invariant check: Entry < TP1 < TP2 < TP3
            if not (entry_price < tp1_fmt <= tp2_fmt <= tp3_fmt):
                return TakeProfitResult(False, 0.0, 0.0, 0.0, 0.0, 0.0, "1:0", "NONE", "Price geometry broken on Long TP")

            gross_rr = (tp1_fmt - entry_price) / risk_amt
            net_rr = max(0.0, (tp1_fmt - entry_price - friction_amt) / (risk_amt + friction_amt))

            if gross_rr < (min_rr - 0.05):
                return TakeProfitResult(
                    False, tp1_fmt, tp2_fmt, tp3_fmt, round(gross_rr, 2), round(net_rr, 2),
                    f"1:{gross_rr:.1f}", "NONE",
                    f"Risk-to-Reward ratio ({gross_rr:.2f}) below required minimum 1:{min_rr:.1f}"
                )

            return TakeProfitResult(
                is_valid=True,
                tp1_price=tp1_fmt,
                tp2_price=tp2_fmt,
                tp3_price=tp3_fmt,
                gross_rr=round(gross_rr, 2),
                net_rr=round(net_rr, 2),
                rr_string=f"1:{gross_rr:.1f}",
                target_type="STRUCTURAL_M15_TARGET" if tp_structural else "CALCULATED_RR_TARGET"
            )

        elif direction == "SHORT":
            tp_structural = None
            if self.config.use_structural_targets and opposing_target and opposing_target.price < entry_price:
                struct_rr = (entry_price - opposing_target.price) / risk_amt
                if struct_rr >= min_rr:
                    tp_structural = opposing_target.price

            calc_tp1 = max(entry_price * 0.001, entry_price - (min_rr * risk_amt))
            calc_tp2 = max(entry_price * 0.001, entry_price - (max(min_rr + 0.5, 2.5) * risk_amt))
            calc_tp3 = max(entry_price * 0.001, entry_price - (max(min_rr + 1.5, 4.0) * risk_amt))

            final_tp1 = tp_structural if (tp_structural and tp_structural > calc_tp2) else calc_tp1
            final_tp2 = min(calc_tp2, final_tp1 - 0.5 * risk_amt)
            final_tp3 = min(calc_tp3, final_tp2 - risk_amt)

            tp1_fmt = format_dynamic_precision(final_tp1)
            tp2_fmt = format_dynamic_precision(final_tp2)
            tp3_fmt = format_dynamic_precision(final_tp3)

            # Invariant check: Entry > TP1 > TP2 > TP3
            if not (entry_price > tp1_fmt >= tp2_fmt >= tp3_fmt):
                return TakeProfitResult(False, 0.0, 0.0, 0.0, 0.0, 0.0, "1:0", "NONE", "Price geometry broken on Short TP")

            gross_rr = (entry_price - tp1_fmt) / risk_amt
            net_rr = max(0.0, (entry_price - tp1_fmt - friction_amt) / (risk_amt + friction_amt))

            if gross_rr < (min_rr - 0.05):
                return TakeProfitResult(
                    False, tp1_fmt, tp2_fmt, tp3_fmt, round(gross_rr, 2), round(net_rr, 2),
                    f"1:{gross_rr:.1f}", "NONE",
                    f"Risk-to-Reward ratio ({gross_rr:.2f}) below required minimum 1:{min_rr:.1f}"
                )

            return TakeProfitResult(
                is_valid=True,
                tp1_price=tp1_fmt,
                tp2_price=tp2_fmt,
                tp3_price=tp3_fmt,
                gross_rr=round(gross_rr, 2),
                net_rr=round(net_rr, 2),
                rr_string=f"1:{gross_rr:.1f}",
                target_type="STRUCTURAL_M15_TARGET" if tp_structural else "CALCULATED_RR_TARGET"
            )

        return TakeProfitResult(False, 0.0, 0.0, 0.0, 0.0, 0.0, "1:0", "NONE", f"Unsupported direction: {direction}")

