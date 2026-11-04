"""
The Only 1 Minute Rectangle Strategy: M1 Rectangle Flip Entry Engine
Based on Section 1.2, Section 9, and Part 3 (Step 3B) of "The Only 1 Minute Trading Strategy" by Anees Mehdi.

Monitors closed 1-minute (M1) candles around the M15 rectangle.
Implements:
- Mode A (SAFE ENTRY - Default): Confirmed M1 candle close outside the rectangle
- Mode B (AGGRESSIVE ENTRY): Early entry inside rectangle on key-level rejection
Strictly enforces closed candle verification, anti-repainting, and one-trade-per-rectangle deduplication.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Tuple
import pandas as pd

from app.quant_v16.rectangle_strategy.strategy_config import RectangleStrategyConfig, EntryMode
from app.quant_v16.rectangle_strategy.rectangle_engine import DynamicRectangle, RectangleStatus


@dataclass
class M1EntryTriggerResult:
    is_triggered: bool
    direction: str              # "LONG" or "SHORT"
    entry_mode: str             # "SAFE" or "AGGRESSIVE"
    trigger_candle_idx: int
    trigger_timestamp: Any
    trigger_price: float        # Exact M1 close
    rectangle: DynamicRectangle
    m1_flip_score: float = 0.0  # Up to 10 points
    reason: str = ""


class M1EntryEngine:
    """
    Evaluates 1-minute (M1) closed candles for rectangle flip triggers.
    """

    def __init__(self, config: Optional[RectangleStrategyConfig] = None):
        self.config = config or RectangleStrategyConfig()

    def evaluate_m1_flip(
        self,
        rectangle: DynamicRectangle,
        df_m1: pd.DataFrame,
        current_m1_idx: int = -1
    ) -> Optional[M1EntryTriggerResult]:
        """
        Evaluates the closed M1 candle at `current_m1_idx` against an active rectangle.
        """
        # If rectangle is not in WAITING status, skip
        if rectangle.status != RectangleStatus.WAITING_FOR_M1_CONFIRMATION:
            return None

        n = len(df_m1)
        idx = n + current_m1_idx if current_m1_idx < 0 else current_m1_idx
        if idx < 0 or idx >= n:
            return None

        o = float(df_m1['open'].iloc[idx])
        h = float(df_m1['high'].iloc[idx])
        l = float(df_m1['low'].iloc[idx])
        c = float(df_m1['close'].iloc[idx])
        ts = df_m1['timestamp'].iloc[idx] if 'timestamp' in df_m1.columns else idx

        upper = rectangle.upper_boundary
        lower = rectangle.lower_boundary
        dir_trade = rectangle.direction

        # Check if price interacted with rectangle
        interacted = (l <= upper and h >= lower)
        if interacted:
            rectangle.retest_occurred = True

        # Check invalidation: Catastrophic blowout beyond opposite side of rectangle before flip
        # (e.g. for LONG, price crashes deep below lower boundary by > 0.50 * width)
        blowout_buf = max(1e-6, rectangle.width * 0.50)
        if dir_trade == "LONG" and c < (lower - blowout_buf):
            rectangle.status = RectangleStatus.INVALIDATED
            return None
        elif dir_trade == "SHORT" and c > (upper + blowout_buf):
            rectangle.status = RectangleStatus.INVALIDATED
            return None

        # Mode A: SAFE ENTRY (Default)
        if self.config.entry_mode == EntryMode.SAFE:
            if dir_trade == "LONG":
                # Bullish Entry: M1 candle must close ABOVE the rectangle's upper boundary
                if c > upper:
                    # Confirmed flip!
                    rectangle.status = RectangleStatus.ENTRY_CONFIRMED
                    rectangle.entry_m1_idx = idx
                    rectangle.entry_price = c
                    return M1EntryTriggerResult(
                        is_triggered=True,
                        direction="LONG",
                        entry_mode="SAFE",
                        trigger_candle_idx=idx,
                        trigger_timestamp=ts,
                        trigger_price=c,
                        rectangle=rectangle,
                        m1_flip_score=10.0,
                        reason=f"M1 candle confirmed close ({c:.4f}) above bullish rectangle upper boundary ({upper:.4f})"
                    )

            elif dir_trade == "SHORT":
                # Bearish Entry: M1 candle must close BELOW the rectangle's lower boundary
                if c < lower:
                    rectangle.status = RectangleStatus.ENTRY_CONFIRMED
                    rectangle.entry_m1_idx = idx
                    rectangle.entry_price = c
                    return M1EntryTriggerResult(
                        is_triggered=True,
                        direction="SHORT",
                        entry_mode="SAFE",
                        trigger_candle_idx=idx,
                        trigger_timestamp=ts,
                        trigger_price=c,
                        rectangle=rectangle,
                        m1_flip_score=10.0,
                        reason=f"M1 candle confirmed close ({c:.4f}) below bearish rectangle lower boundary ({lower:.4f})"
                    )

        # Mode B: AGGRESSIVE ENTRY (Inside rectangle on key-level rejection)
        elif self.config.entry_mode == EntryMode.AGGRESSIVE:
            if dir_trade == "LONG":
                # Inside rectangle with lower wick rejection
                if lower <= c <= upper:
                    lower_wick = min(o, c) - l
                    if lower_wick / max(1e-8, h - l) >= 0.35:
                        rectangle.status = RectangleStatus.ENTRY_CONFIRMED
                        rectangle.entry_m1_idx = idx
                        rectangle.entry_price = c
                        return M1EntryTriggerResult(
                            is_triggered=True,
                            direction="LONG",
                            entry_mode="AGGRESSIVE",
                            trigger_candle_idx=idx,
                            trigger_timestamp=ts,
                            trigger_price=c,
                            rectangle=rectangle,
                            m1_flip_score=8.0,
                            reason=f"Aggressive M1 entry inside rectangle with rejection wick ({lower_wick:.4f})"
                        )

            elif dir_trade == "SHORT":
                if lower <= c <= upper:
                    upper_wick = h - max(o, c)
                    if upper_wick / max(1e-8, h - l) >= 0.35:
                        rectangle.status = RectangleStatus.ENTRY_CONFIRMED
                        rectangle.entry_m1_idx = idx
                        rectangle.entry_price = c
                        return M1EntryTriggerResult(
                            is_triggered=True,
                            direction="SHORT",
                            entry_mode="AGGRESSIVE",
                            trigger_candle_idx=idx,
                            trigger_timestamp=ts,
                            trigger_price=c,
                            rectangle=rectangle,
                            m1_flip_score=8.0,
                            reason=f"Aggressive M1 entry inside rectangle with rejection wick ({upper_wick:.4f})"
                        )

        return None

