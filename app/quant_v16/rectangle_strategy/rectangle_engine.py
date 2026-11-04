"""
The Only 1 Minute Rectangle Strategy: Dynamic Rectangle Generation Engine
Based on Section 1.1, Section 8, and Part 3 (Step 3A) of "The Only 1 Minute Trading Strategy" by Anees Mehdi.

Generates the core trading boundary:
- Bullish Rectangle: Upper boundary = M15 candle Close, Lower boundary = M15 candle Low.
- Bearish Rectangle: Upper boundary = M15 candle High, Lower boundary = M15 candle Close.
Manages full state machine lifecycle and strict deduplication.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
import time
import pandas as pd

from app.quant_v16.rectangle_strategy.strategy_config import RectangleStrategyConfig
from app.quant_v16.rectangle_strategy.weakness_detector import WeaknessConfirmation


class RectangleStatus(str, Enum):
    CREATED = "CREATED"
    WAITING_FOR_M1_CONFIRMATION = "WAITING_FOR_M1_CONFIRMATION"
    ENTRY_CONFIRMED = "ENTRY_CONFIRMED"
    TRADE_TRIGGERED = "TRADE_TRIGGERED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


@dataclass
class DynamicRectangle:
    rectangle_id: str
    symbol: str
    direction: str              # "LONG" or "SHORT"
    upper_boundary: float
    lower_boundary: float
    width: float                # upper_boundary - lower_boundary
    formation_m15_idx: int
    formation_timestamp: Any
    related_m15_swing_level: float
    liquidity_sweep_id: str
    confirmation_candle_id: str
    expiration_timestamp: Optional[Any] = None
    expiration_m1_idx: Optional[int] = None
    status: RectangleStatus = RectangleStatus.CREATED
    entry_m1_idx: Optional[int] = None
    entry_price: Optional[float] = None
    retest_occurred: bool = False
    created_at_wall_ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rectangle_id": self.rectangle_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "upper_boundary": round(self.upper_boundary, 6),
            "lower_boundary": round(self.lower_boundary, 6),
            "width": round(self.width, 6),
            "formation_m15_idx": self.formation_m15_idx,
            "formation_timestamp": str(self.formation_timestamp),
            "related_m15_swing_level": round(self.related_m15_swing_level, 6),
            "liquidity_sweep_id": self.liquidity_sweep_id,
            "confirmation_candle_id": self.confirmation_candle_id,
            "expiration_timestamp": str(self.expiration_timestamp) if self.expiration_timestamp else None,
            "status": self.status.value,
            "entry_price": round(self.entry_price, 6) if self.entry_price else None,
            "retest_occurred": self.retest_occurred
        }


class RectangleEngine:
    """
    Constructs and manages dynamic rectangles generated from verified M15 weakness candles.
    Enforces idempotent creation to prevent duplicate rectangles on the same candle.
    """

    def __init__(self, config: Optional[RectangleStrategyConfig] = None):
        self.config = config or RectangleStrategyConfig()
        self.rectangles: Dict[str, DynamicRectangle] = {} # Keyed by rectangle_id

    def create_rectangle(
        self,
        symbol: str,
        weakness: WeaknessConfirmation,
        df_m15: pd.DataFrame
    ) -> Optional[DynamicRectangle]:
        """
        Creates a new DynamicRectangle from confirmed M15 weakness.
        """
        if not weakness.is_confirmed or weakness.sweep_event is None:
            return None

        sw = weakness.sweep_event
        idx = weakness.confirmation_candle_idx
        ts = weakness.confirmation_timestamp
        rect_id = f"RECT_{symbol}_{sw.direction}_{idx}_{int(ts) if isinstance(ts, (int, float)) else idx}"

        # Deduplication check: Do not re-create if already exists
        if rect_id in self.rectangles:
            return self.rectangles[rect_id]

        c = sw.sweep_candle_close
        h = sw.sweep_candle_high
        l = sw.sweep_candle_low

        if sw.direction == "BULLISH":
            # Bullish Rectangle: Upper boundary = Close, Lower boundary = Low
            upper = c
            lower = l
            trade_dir = "LONG"
        else:
            # Bearish Rectangle: Upper boundary = High, Lower boundary = Close
            upper = h
            lower = c
            trade_dir = "SHORT"

        width = max(1e-8, upper - lower)

        rect = DynamicRectangle(
            rectangle_id=rect_id,
            symbol=symbol,
            direction=trade_dir,
            upper_boundary=round(upper, 6),
            lower_boundary=round(lower, 6),
            width=round(width, 6),
            formation_m15_idx=idx,
            formation_timestamp=ts,
            related_m15_swing_level=weakness.target_swing_level,
            liquidity_sweep_id=sw.sweep_id,
            confirmation_candle_id=f"M15_CANDLE_{idx}_{ts}",
            status=RectangleStatus.WAITING_FOR_M1_CONFIRMATION
        )

        self.rectangles[rect_id] = rect
        return rect

    def get_active_rectangles(self, symbol: Optional[str] = None) -> List[DynamicRectangle]:
        """Returns all rectangles currently waiting for M1 confirmation."""
        active = []
        for r in self.rectangles.values():
            if r.status == RectangleStatus.WAITING_FOR_M1_CONFIRMATION:
                if symbol is None or r.symbol == symbol:
                    active.append(r)
        return active

