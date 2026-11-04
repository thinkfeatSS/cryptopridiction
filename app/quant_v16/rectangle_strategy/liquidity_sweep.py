"""
The Only 1 Minute Rectangle Strategy: Liquidity Sweep & Weakness Detection Engine
Based on Section 2.2, Section 6, and Part 3 (Step 2) of "The Only 1 Minute Trading Strategy" by Anees Mehdi.

Distinguishes between:
- WEAKNESS (Our Focus): Price sweeps past swing level, rejects, and closes back INSIDE, forming a wick rejection.
- STRENGTH (Disrespect of level): Price pierces level and closes BEYOND it (breakout continuation). Strictly rejected.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple
import numpy as np
import pandas as pd

from app.quant_v16.rectangle_strategy.strategy_config import RectangleStrategyConfig
from app.quant_v16.rectangle_strategy.market_structure import SwingPoint


@dataclass
class LiquiditySweepEvent:
    sweep_id: str
    direction: str              # "BULLISH" or "BEARISH"
    swept_level_price: float
    swept_level_type: str       # "SWING_LOW" or "SWING_HIGH"
    swept_swing_idx: int
    sweep_candle_idx: int
    sweep_timestamp: Any
    sweep_candle_open: float
    sweep_candle_high: float
    sweep_candle_low: float
    sweep_candle_close: float
    extreme_price: float        # Candle low for Bullish sweep, candle high for Bearish sweep
    sweep_depth: float          # Distance penetrated beyond level
    sweep_depth_atr: float
    rejection_wick_size: float
    rejection_wick_pct: float   # Wick size / Total candle range
    wick_to_body_ratio: float   # Wick size / Body size
    rejection_strength: float   # 0 to 10 points
    is_valid_weakness: bool     # True if closed on the correct side with rejection
    classification: str         # "VALID_WEAKNESS", "BREAKOUT_STRENGTH", or "INSUFFICIENT_SWEEP"
    sweep_score: float = 0.0    # Up to 20 points for valid sweep + 10 for wick


class LiquiditySweepDetector:
    """
    Evaluates completed M15 candles for liquidity sweeps and confirms weakness.
    """

    def __init__(self, config: Optional[RectangleStrategyConfig] = None):
        self.config = config or RectangleStrategyConfig()

    def evaluate_sweep(
        self,
        df_m15: pd.DataFrame,
        target_swing: SwingPoint,
        direction: str,
        atr_value: float,
        candle_idx: int = -1
    ) -> Optional[LiquiditySweepEvent]:
        """
        Evaluates whether candle at `candle_idx` executed a valid liquidity sweep on `target_swing`.
        """
        n = len(df_m15)
        eval_idx = n + candle_idx if candle_idx < 0 else candle_idx
        if eval_idx < 0 or eval_idx >= n:
            return None

        o = float(df_m15['open'].iloc[eval_idx])
        h = float(df_m15['high'].iloc[eval_idx])
        l = float(df_m15['low'].iloc[eval_idx])
        c = float(df_m15['close'].iloc[eval_idx])
        ts = df_m15['timestamp'].iloc[eval_idx] if 'timestamp' in df_m15.columns else eval_idx

        bar_rng = max(1e-8, h - l)
        body = max(1e-8, abs(c - o))
        curr_atr = max(1e-8, atr_value)

        # ----------------------------------------------------------------------
        # A. BULLISH LIQUIDITY SWEEP (SWEEPING A SWING LOW IN UPTREND)
        # ----------------------------------------------------------------------
        if direction == "BULLISH":
            swing_lvl = target_swing.price

            # Check if price penetrated below the swing low
            if l >= swing_lvl:
                return None # No sweep occurred

            sweep_depth = swing_lvl - l
            sweep_depth_atr = sweep_depth / curr_atr

            # Strength check: Candle closed below the swept swing low -> STRENGTH (Breakout), NOT WEAKNESS
            if c < swing_lvl:
                return LiquiditySweepEvent(
                    sweep_id=f"SWEEP_BULL_{eval_idx}_{int(ts) if isinstance(ts, (int, float)) else eval_idx}",
                    direction="BULLISH",
                    swept_level_price=swing_lvl,
                    swept_level_type="SWING_LOW",
                    swept_swing_idx=target_swing.index,
                    sweep_candle_idx=eval_idx,
                    sweep_timestamp=ts,
                    sweep_candle_open=o,
                    sweep_candle_high=h,
                    sweep_candle_low=l,
                    sweep_candle_close=c,
                    extreme_price=l,
                    sweep_depth=round(sweep_depth, 6),
                    sweep_depth_atr=round(sweep_depth_atr, 2),
                    rejection_wick_size=0.0,
                    rejection_wick_pct=0.0,
                    wick_to_body_ratio=0.0,
                    rejection_strength=0.0,
                    is_valid_weakness=False,
                    classification="BREAKOUT_STRENGTH",
                    sweep_score=0.0
                )

            # Weakness check: Candle closed back ABOVE the swept swing low!
            lower_wick = max(0.0, min(o, c) - l)
            wick_pct = lower_wick / bar_rng
            wick_body_ratio = lower_wick / body

            # Depth sanity bounds (must be genuine sweep, not micro noise or 5x ATR flash crash)
            valid_depth = (self.config.min_sweep_atr_mult <= sweep_depth_atr <= self.config.max_sweep_atr_mult)
            valid_wick = (wick_pct >= self.config.min_rejection_wick_pct) or (wick_body_ratio >= self.config.min_wick_to_body_ratio)

            is_valid_weakness = bool(c > swing_lvl and valid_depth and valid_wick)

            # Scoring:
            # - Valid liquidity sweep: up to 20 points
            # - Wick rejection strength: up to 10 points
            sweep_pts = 0.0
            wick_pts = 0.0
            if is_valid_weakness:
                sweep_pts = 20.0
                # Rejection wick quality score (0 to 10)
                wick_pts = min(10.0, (wick_pct / 0.50) * 10.0)

            return LiquiditySweepEvent(
                sweep_id=f"SWEEP_BULL_{eval_idx}_{int(ts) if isinstance(ts, (int, float)) else eval_idx}",
                direction="BULLISH",
                swept_level_price=swing_lvl,
                swept_level_type="SWING_LOW",
                swept_swing_idx=target_swing.index,
                sweep_candle_idx=eval_idx,
                sweep_timestamp=ts,
                sweep_candle_open=o,
                sweep_candle_high=h,
                sweep_candle_low=l,
                sweep_candle_close=c,
                extreme_price=l,
                sweep_depth=round(sweep_depth, 6),
                sweep_depth_atr=round(sweep_depth_atr, 2),
                rejection_wick_size=round(lower_wick, 6),
                rejection_wick_pct=round(wick_pct, 4),
                wick_to_body_ratio=round(wick_body_ratio, 2),
                rejection_strength=round(wick_pts, 2),
                is_valid_weakness=is_valid_weakness,
                classification="VALID_WEAKNESS" if is_valid_weakness else "INSUFFICIENT_SWEEP",
                sweep_score=sweep_pts + wick_pts
            )

        # ----------------------------------------------------------------------
        # B. BEARISH LIQUIDITY SWEEP (SWEEPING A SWING HIGH IN DOWNTREND)
        # ----------------------------------------------------------------------
        elif direction == "BEARISH":
            swing_lvl = target_swing.price

            # Check if price penetrated above the swing high
            if h <= swing_lvl:
                return None # No sweep occurred

            sweep_depth = h - swing_lvl
            sweep_depth_atr = sweep_depth / curr_atr

            # Strength check: Candle closed above the swept swing high -> STRENGTH (Breakout), NOT WEAKNESS
            if c > swing_lvl:
                return LiquiditySweepEvent(
                    sweep_id=f"SWEEP_BEAR_{eval_idx}_{int(ts) if isinstance(ts, (int, float)) else eval_idx}",
                    direction="BEARISH",
                    swept_level_price=swing_lvl,
                    swept_level_type="SWING_HIGH",
                    swept_swing_idx=target_swing.index,
                    sweep_candle_idx=eval_idx,
                    sweep_timestamp=ts,
                    sweep_candle_open=o,
                    sweep_candle_high=h,
                    sweep_candle_low=l,
                    sweep_candle_close=c,
                    extreme_price=h,
                    sweep_depth=round(sweep_depth, 6),
                    sweep_depth_atr=round(sweep_depth_atr, 2),
                    rejection_wick_size=0.0,
                    rejection_wick_pct=0.0,
                    wick_to_body_ratio=0.0,
                    rejection_strength=0.0,
                    is_valid_weakness=False,
                    classification="BREAKOUT_STRENGTH",
                    sweep_score=0.0
                )

            # Weakness check: Candle closed back BELOW the swept swing high!
            upper_wick = max(0.0, h - max(o, c))
            wick_pct = upper_wick / bar_rng
            wick_body_ratio = upper_wick / body

            valid_depth = (self.config.min_sweep_atr_mult <= sweep_depth_atr <= self.config.max_sweep_atr_mult)
            valid_wick = (wick_pct >= self.config.min_rejection_wick_pct) or (wick_body_ratio >= self.config.min_wick_to_body_ratio)

            is_valid_weakness = bool(c < swing_lvl and valid_depth and valid_wick)

            sweep_pts = 0.0
            wick_pts = 0.0
            if is_valid_weakness:
                sweep_pts = 20.0
                wick_pts = min(10.0, (wick_pct / 0.50) * 10.0)

            return LiquiditySweepEvent(
                sweep_id=f"SWEEP_BEAR_{eval_idx}_{int(ts) if isinstance(ts, (int, float)) else eval_idx}",
                direction="BEARISH",
                swept_level_price=swing_lvl,
                swept_level_type="SWING_HIGH",
                swept_swing_idx=target_swing.index,
                sweep_candle_idx=eval_idx,
                sweep_timestamp=ts,
                sweep_candle_open=o,
                sweep_candle_high=h,
                sweep_candle_low=l,
                sweep_candle_close=c,
                extreme_price=h,
                sweep_depth=round(sweep_depth, 6),
                sweep_depth_atr=round(sweep_depth_atr, 2),
                rejection_wick_size=round(upper_wick, 6),
                rejection_wick_pct=round(wick_pct, 4),
                wick_to_body_ratio=round(wick_body_ratio, 2),
                rejection_strength=round(wick_pts, 2),
                is_valid_weakness=is_valid_weakness,
                classification="VALID_WEAKNESS" if is_valid_weakness else "INSUFFICIENT_SWEEP",
                sweep_score=sweep_pts + wick_pts
            )

        return None

