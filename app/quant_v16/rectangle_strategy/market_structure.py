"""
The Only 1 Minute Rectangle Strategy: Market Structure Engine
Based on Part 2 & Part 3 (Step 1) of "The Only 1 Minute Trading Strategy" by Anees Mehdi.

Identifies:
- Confirmed Swing Highs and Swing Lows (strictly non-repainting, requiring right-bar confirmation)
- Structural sequences: Higher Highs (HH), Higher Lows (HL), Lower Highs (LH), Lower Lows (LL)
- Break of Structure (BOS) and Change of Character (CHOCH)
- Active continuation levels: Swing Low in an Uptrend, Swing High in a Downtrend
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import pandas as pd

from app.quant_v16.rectangle_strategy.strategy_config import RectangleStrategyConfig


@dataclass
class SwingPoint:
    index: int
    timestamp: Any
    price: float
    point_type: str            # "SWING_HIGH" or "SWING_LOW"
    structure_type: str        # "HH", "LH", "HL", "LL", or "INITIAL"
    is_swept: bool = False
    sweep_timestamp: Optional[Any] = None
    is_broken: bool = False    # True if decisive close beyond level occurred (BOS)
    broken_timestamp: Optional[Any] = None


@dataclass
class MarketStructureResult:
    structure_trend: str       # "HH_HL" (Uptrend), "LH_LL" (Downtrend), or "CHOP"
    recent_swing_highs: List[SwingPoint] = field(default_factory=list)
    recent_swing_lows: List[SwingPoint] = field(default_factory=list)
    active_target_level: Optional[SwingPoint] = None # The swing low to sweep in Uptrend, or swing high in Downtrend
    opposing_target_level: Optional[SwingPoint] = None # Target for take profit (opposing swing high/low)
    has_bos: bool = False
    has_choch: bool = False
    structure_score: float = 0.0 # 0 to 15 points
    is_continuation_supported: bool = False


class MarketStructureEngine:
    """
    Identifies non-repainting market structure pivots on closed M15 candles.
    Enforces right-side bar confirmation so historical swing points never change once confirmed.
    """

    def __init__(self, config: Optional[RectangleStrategyConfig] = None):
        self.config = config or RectangleStrategyConfig()

    def find_confirmed_swings(
        self,
        df_m15: pd.DataFrame,
        up_to_bar: int = -1
    ) -> Tuple[List[SwingPoint], List[SwingPoint]]:
        """
        Scans OHLCV history up to `up_to_bar` to locate strictly confirmed swing pivots.
        A candle at index `i` is confirmed as a pivot ONLY after `right_bars` candles have closed.
        """
        n = len(df_m15)
        max_idx = n + up_to_bar if up_to_bar < 0 else up_to_bar
        left = self.config.swing_pivot_left_bars
        right = self.config.swing_pivot_right_bars

        if max_idx < (left + right + 1):
            return [], []

        h = df_m15['high'].values
        l = df_m15['low'].values
        ts = df_m15['timestamp'].values if 'timestamp' in df_m15.columns else list(range(n))

        swing_highs: List[SwingPoint] = []
        swing_lows: List[SwingPoint] = []

        # We can evaluate candidate pivots from `left` up to `max_idx - right`
        for i in range(left, max_idx - right + 1):
            # 1. Swing High Check
            is_sh = True
            for offset in range(1, left + 1):
                if h[i] <= h[i - offset]:
                    is_sh = False
                    break
            if is_sh:
                for offset in range(1, right + 1):
                    if h[i] <= h[i + offset]:
                        is_sh = False
                        break
            if is_sh:
                # Classify HH vs LH
                st_type = "INITIAL"
                if swing_highs:
                    st_type = "HH" if h[i] > swing_highs[-1].price else "LH"
                swing_highs.append(SwingPoint(
                    index=i,
                    timestamp=ts[i],
                    price=float(h[i]),
                    point_type="SWING_HIGH",
                    structure_type=st_type
                ))

            # 2. Swing Low Check
            is_sl = True
            for offset in range(1, left + 1):
                if l[i] >= l[i - offset]:
                    is_sl = False
                    break
            if is_sl:
                for offset in range(1, right + 1):
                    if l[i] >= l[i + offset]:
                        is_sl = False
                        break
            if is_sl:
                # Classify HL vs LL
                st_type = "INITIAL"
                if swing_lows:
                    st_type = "HL" if l[i] > swing_lows[-1].price else "LL"
                swing_lows.append(SwingPoint(
                    index=i,
                    timestamp=ts[i],
                    price=float(l[i]),
                    point_type="SWING_LOW",
                    structure_type=st_type
                ))

        return swing_highs, swing_lows

    def analyze_structure(
        self,
        df_m15: pd.DataFrame,
        expected_direction: str,
        current_bar_idx: int = -1
    ) -> MarketStructureResult:
        """
        Analyzes market structure trend (HH_HL or LH_LL) and selects the active continuation level.
        - For BULLISH (Uptrend): We focus on Lows (Continuation setup sweeps a recent Swing Low).
        - For BEARISH (Downtrend): We focus on Highs (Continuation setup sweeps a recent Swing High).
        """
        n = len(df_m15)
        eval_idx = n + current_bar_idx if current_bar_idx < 0 else current_bar_idx

        swing_highs, swing_lows = self.find_confirmed_swings(df_m15, up_to_bar=eval_idx)

        # Restrict to configurable lookback window
        window = self.config.structure_lookback_bars
        recent_sh = [s for s in swing_highs if (eval_idx - s.index) <= window]
        recent_sl = [s for s in swing_lows if (eval_idx - s.index) <= window]

        # Determine overall structure trend
        hh_count = sum(1 for s in recent_sh if s.structure_type == "HH")
        hl_count = sum(1 for s in recent_sl if s.structure_type == "HL")
        lh_count = sum(1 for s in recent_sh if s.structure_type == "LH")
        ll_count = sum(1 for s in recent_sl if s.structure_type == "LL")

        structure_trend = "CHOP"
        if (hh_count + hl_count) > (lh_count + ll_count):
            structure_trend = "HH_HL"
        elif (lh_count + ll_count) > (hh_count + hl_count):
            structure_trend = "LH_LL"

        # Check BOS / CHOCH
        has_bos = False
        has_choch = False
        if len(recent_sh) >= 2 and recent_sh[-1].price > recent_sh[-2].price:
            has_bos = True
        if len(recent_sl) >= 2 and recent_sl[-1].price < recent_sl[-2].price:
            has_bos = True

        active_target: Optional[SwingPoint] = None
        opposing_target: Optional[SwingPoint] = None
        is_continuation_supported = False
        score = 0.0

        if expected_direction == "BULLISH":
            # In an Uptrend, we focus on the Lows to find the level to sweep
            if recent_sl:
                # Active target is the most recent confirmed swing low that hasn't been structurally broken by closes
                active_target = recent_sl[-1]
            if recent_sh:
                # Opposing target is recent swing high (TP target)
                opposing_target = max(recent_sh, key=lambda s: s.price)

            if structure_trend == "HH_HL" or hl_count >= 1:
                is_continuation_supported = True
                score += 10.0
                if has_bos:
                    score += 5.0
            elif structure_trend == "CHOP" and recent_sl:
                score += 5.0

        elif expected_direction == "BEARISH":
            # In a Downtrend, we focus on the Highs to find the level to sweep
            if recent_sh:
                active_target = recent_sh[-1]
            if recent_sl:
                opposing_target = min(recent_sl, key=lambda s: s.price)

            if structure_trend == "LH_LL" or lh_count >= 1:
                is_continuation_supported = True
                score += 10.0
                if has_bos:
                    score += 5.0
            elif structure_trend == "CHOP" and recent_sh:
                score += 5.0

        return MarketStructureResult(
            structure_trend=structure_trend,
            recent_swing_highs=recent_sh,
            recent_swing_lows=recent_sl,
            active_target_level=active_target,
            opposing_target_level=opposing_target,
            has_bos=has_bos,
            has_choch=has_choch,
            structure_score=min(15.0, score),
            is_continuation_supported=is_continuation_supported
        )

