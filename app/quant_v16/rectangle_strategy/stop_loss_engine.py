"""
The Only 1 Minute Rectangle Strategy: Stop Loss Calculation Engine
Based on Section 1.1, Section 10, and Part 3 (Step 3C) of "The Only 1 Minute Trading Strategy" by Anees Mehdi.

Places SL slightly below/above the M15 candle that formed the rectangle (sweep extreme).
Applies dynamic ATR-based volatility buffer and exchange tick precision formatting.
Strictly enforces price invariants: SL < Entry (Long) and SL > Entry (Short).
"""

from dataclasses import dataclass
from typing import Optional, Tuple
import math

from app.quant_v16.rectangle_strategy.strategy_config import RectangleStrategyConfig
from app.quant_v16.rectangle_strategy.rectangle_engine import DynamicRectangle
from app.quant_v16.entry_confirmation import format_dynamic_precision


@dataclass
class StopLossResult:
    is_valid: bool
    stop_loss_price: float
    risk_amount: float          # abs(entry_price - stop_loss_price)
    risk_pct: float             # risk_amount / entry_price * 100
    sl_distance_atr: float      # risk_amount / ATR
    rejection_reason: Optional[str] = None


class StopLossEngine:
    """
    Computes volatility-buffered stop loss based on rectangle extreme boundary.
    """

    def __init__(self, config: Optional[RectangleStrategyConfig] = None):
        self.config = config or RectangleStrategyConfig()

    def calculate_stop_loss(
        self,
        rectangle: DynamicRectangle,
        entry_price: float,
        atr_value: float,
        tick_size: float = 1e-4
    ) -> StopLossResult:
        """
        Calculates Stop Loss for Long or Short setups.
        """
        if entry_price <= 0:
            return StopLossResult(False, 0.0, 0.0, 0.0, 0.0, "Invalid non-positive entry price")

        curr_atr = max(1e-8, atr_value)
        buffer_amt = self.config.sl_buffer_atr_mult * curr_atr

        if rectangle.direction == "LONG":
            # Place SL below rectangle lower boundary (sweep extreme low)
            raw_sl = rectangle.lower_boundary - buffer_amt
            formatted_sl = format_dynamic_precision(raw_sl)

            # Invariant: SL must be strictly below Entry
            if formatted_sl >= entry_price:
                return StopLossResult(
                    False, formatted_sl, 0.0, 0.0, 0.0,
                    f"Price invariant violation: Bullish SL ({formatted_sl:.4f}) >= Entry ({entry_price:.4f})"
                )

            risk_amt = entry_price - formatted_sl
            risk_pct = (risk_amt / entry_price) * 100.0

            # Guard against microscopic or excessive stop loss
            if risk_pct < self.config.min_sl_pct:
                return StopLossResult(
                    False, formatted_sl, risk_amt, risk_pct, risk_amt / curr_atr,
                    f"Stop loss distance too tight ({risk_pct:.2f}% < {self.config.min_sl_pct}%) - fee chop danger"
                )
            if risk_pct > self.config.max_sl_pct:
                return StopLossResult(
                    False, formatted_sl, risk_amt, risk_pct, risk_amt / curr_atr,
                    f"Stop loss distance too wide ({risk_pct:.2f}% > {self.config.max_sl_pct}%) - excessive capital risk"
                )

            return StopLossResult(
                is_valid=True,
                stop_loss_price=formatted_sl,
                risk_amount=round(risk_amt, 6),
                risk_pct=round(risk_pct, 4),
                sl_distance_atr=round(risk_amt / curr_atr, 2)
            )

        elif rectangle.direction == "SHORT":
            # Place SL above rectangle upper boundary (sweep extreme high)
            raw_sl = rectangle.upper_boundary + buffer_amt
            formatted_sl = format_dynamic_precision(raw_sl)

            # Invariant: SL must be strictly above Entry
            if formatted_sl <= entry_price:
                return StopLossResult(
                    False, formatted_sl, 0.0, 0.0, 0.0,
                    f"Price invariant violation: Bearish SL ({formatted_sl:.4f}) <= Entry ({entry_price:.4f})"
                )

            risk_amt = formatted_sl - entry_price
            risk_pct = (risk_amt / entry_price) * 100.0

            if risk_pct < self.config.min_sl_pct:
                return StopLossResult(
                    False, formatted_sl, risk_amt, risk_pct, risk_amt / curr_atr,
                    f"Stop loss distance too tight ({risk_pct:.2f}% < {self.config.min_sl_pct}%) - fee chop danger"
                )
            if risk_pct > self.config.max_sl_pct:
                return StopLossResult(
                    False, formatted_sl, risk_amt, risk_pct, risk_amt / curr_atr,
                    f"Stop loss distance too wide ({risk_pct:.2f}% > {self.config.max_sl_pct}%) - excessive capital risk"
                )

            return StopLossResult(
                is_valid=True,
                stop_loss_price=formatted_sl,
                risk_amount=round(risk_amt, 6),
                risk_pct=round(risk_pct, 4),
                sl_distance_atr=round(risk_amt / curr_atr, 2)
            )

        return StopLossResult(False, 0.0, 0.0, 0.0, 0.0, f"Unsupported direction: {rectangle.direction}")

