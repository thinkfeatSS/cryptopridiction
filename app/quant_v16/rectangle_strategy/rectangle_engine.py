"""
The Only 1 Minute Rectangle Strategy: Dynamic Rectangle Generation Engine
Based on Section 1.1, Section 8, and Part 3 (Step 3A) of "The Only 1 Minute Trading Strategy" by Anees Mehdi.

Generates the core trading boundary:
- Bullish Rectangle: Upper boundary = M15 candle Close, Lower boundary = M15 candle Low.
- Bearish Rectangle: Upper boundary = M15 candle High, Lower boundary = M15 candle Close.
Manages full state machine lifecycle and strict deduplication.
"""

import os
import json
import tempfile
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
            "retest_occurred": self.retest_occurred,
            "created_at_wall_ts": self.created_at_wall_ts
        }


class RectangleEngine:
    """
    Constructs and manages dynamic rectangles generated from verified M15 weakness candles.
    Enforces idempotent creation, multi-bar lifecycle persistence, and atomic state exports.
    """

    def __init__(self, config: Optional[RectangleStrategyConfig] = None, state_file: Optional[str] = None):
        self.config = config or RectangleStrategyConfig()
        self.state_file = state_file or os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "export_app_data", "active_rectangles.json"
        ))
        self.rectangles: Dict[str, DynamicRectangle] = {} # Keyed by rectangle_id
        self.active_rectangles_by_symbol: Dict[str, DynamicRectangle] = {} # Keyed by normalized symbol
        self.load_state()

    def register_rectangle(self, rect: DynamicRectangle) -> DynamicRectangle:
        """Registers a dynamic rectangle and tracks it as active for the symbol."""
        self.rectangles[rect.rectangle_id] = rect
        clean_sym = rect.symbol.upper()
        if rect.status in (RectangleStatus.CREATED, RectangleStatus.WAITING_FOR_M1_CONFIRMATION):
            self.active_rectangles_by_symbol[clean_sym] = rect
        self.save_state()
        return rect

    def get_active_rectangle(self, symbol: str) -> Optional[DynamicRectangle]:
        """Returns the current active unexpired rectangle for a symbol if present."""
        clean_sym = symbol.upper()
        rect = self.active_rectangles_by_symbol.get(clean_sym)
        if rect:
            if rect.status != RectangleStatus.WAITING_FOR_M1_CONFIRMATION:
                self.active_rectangles_by_symbol.pop(clean_sym, None)
                return None
            # Check wall-clock expiration (60 minutes = 3600 seconds default)
            age_sec = time.time() - float(getattr(rect, "created_at_wall_ts", time.time()))
            if age_sec > 3600.0:
                rect.status = RectangleStatus.EXPIRED
                self.active_rectangles_by_symbol.pop(clean_sym, None)
                self.save_state()
                return None
        return rect

    def prune_expired(self, current_ts: Optional[float] = None, max_age_seconds: float = 3600.0):
        """Prunes expired rectangles older than max_age_seconds."""
        now = current_ts or time.time()
        expired_symbols = []
        for sym, rect in list(self.active_rectangles_by_symbol.items()):
            age = now - float(getattr(rect, "created_at_wall_ts", now))
            if age > max_age_seconds:
                rect.status = RectangleStatus.EXPIRED
                expired_symbols.append(sym)
        for sym in expired_symbols:
            self.active_rectangles_by_symbol.pop(sym, None)
        if expired_symbols:
            self.save_state()

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
            status=RectangleStatus.WAITING_FOR_M1_CONFIRMATION,
            created_at_wall_ts=time.time()
        )

        return self.register_rectangle(rect)

    def get_active_rectangles(self, symbol: Optional[str] = None) -> List[DynamicRectangle]:
        """Returns all rectangles currently waiting for M1 confirmation."""
        active = []
        clean_sym = symbol.upper() if symbol else None
        for r in self.rectangles.values():
            if r.status == RectangleStatus.WAITING_FOR_M1_CONFIRMATION:
                if clean_sym is None or r.symbol.upper() == clean_sym:
                    active.append(r)
        return active

    def save_state(self) -> bool:
        """Atomically persists active rectangles to state_file on disk."""
        if not self.state_file:
            return False
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            export_data = {
                "active_rectangles": {k: v.to_dict() for k, v in self.active_rectangles_by_symbol.items()},
                "total_active": len(self.active_rectangles_by_symbol),
                "last_updated_wall_ts": time.time()
            }
            dir_name = os.path.dirname(self.state_file)
            with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, suffix=".tmp") as tf:
                json.dump(export_data, tf, indent=2)
                temp_name = tf.name
            os.replace(temp_name, self.state_file)
            return True
        except Exception:
            return False

    def load_state(self) -> bool:
        """Loads persistent active rectangles from disk on initialization."""
        if not self.state_file or not os.path.exists(self.state_file):
            return False
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw_active = data.get("active_rectangles", {})
            now = time.time()
            for sym, r_data in raw_active.items():
                rect = DynamicRectangle(
                    rectangle_id=r_data["rectangle_id"],
                    symbol=r_data["symbol"],
                    direction=r_data["direction"],
                    upper_boundary=float(r_data["upper_boundary"]),
                    lower_boundary=float(r_data["lower_boundary"]),
                    width=float(r_data["width"]),
                    formation_m15_idx=int(r_data["formation_m15_idx"]),
                    formation_timestamp=r_data["formation_timestamp"],
                    related_m15_swing_level=float(r_data["related_m15_swing_level"]),
                    liquidity_sweep_id=r_data["liquidity_sweep_id"],
                    confirmation_candle_id=r_data["confirmation_candle_id"],
                    status=RectangleStatus(r_data.get("status", "WAITING_FOR_M1_CONFIRMATION")),
                    created_at_wall_ts=float(r_data.get("created_at_wall_ts", now))
                )
                # Only restore unexpired rectangles (< 3600 seconds)
                if (now - rect.created_at_wall_ts) <= 3600.0 and rect.status == RectangleStatus.WAITING_FOR_M1_CONFIRMATION:
                    self.rectangles[rect.rectangle_id] = rect
                    self.active_rectangles_by_symbol[sym.upper()] = rect
            return True
        except Exception:
            return False

