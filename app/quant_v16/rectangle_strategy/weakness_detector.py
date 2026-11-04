"""
The Only 1 Minute Rectangle Strategy: M15 Weakness Confirmation Engine
Based on Section 7 & Part 3 (Step 2) of "The Only 1 Minute Trading Strategy" by Anees Mehdi.

Ensures that only fully closed M15 candles with verified wick rejections qualify as confirmed weakness.
Provides granular classification: VALID_WEAKNESS, BREAKOUT_STRENGTH, INVALID_WEAKNESS, EXPIRED.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional
import pandas as pd

from app.quant_v16.rectangle_strategy.strategy_config import RectangleStrategyConfig
from app.quant_v16.rectangle_strategy.market_structure import SwingPoint
from app.quant_v16.rectangle_strategy.liquidity_sweep import LiquiditySweepDetector, LiquiditySweepEvent


@dataclass
class WeaknessConfirmation:
    status: str                 # "CONFIRMED", "REJECTED_STRENGTH", "REJECTED_INSUFFICIENT", "NO_SWEEP"
    is_confirmed: bool
    confirmation_candle_idx: int
    confirmation_timestamp: Any
    direction: str
    target_swing_level: float
    sweep_event: Optional[LiquiditySweepEvent]
    weakness_score: float = 0.0 # Up to 15 points
    reason: str = ""


class WeaknessDetector:
    """
    Evaluates completed M15 candles to produce authoritative Weakness Confirmations.
    """

    def __init__(self, config: Optional[RectangleStrategyConfig] = None):
        self.config = config or RectangleStrategyConfig()
        self.sweep_detector = LiquiditySweepDetector(self.config)

    def evaluate_m15_confirmation(
        self,
        df_m15: pd.DataFrame,
        target_swing: SwingPoint,
        direction: str,
        atr_value: float,
        candle_idx: int = -1
    ) -> WeaknessConfirmation:
        """
        Evaluates a closed M15 candle for weakness confirmation against target swing level.
        """
        n = len(df_m15)
        eval_idx = n + candle_idx if candle_idx < 0 else candle_idx
        ts = df_m15['timestamp'].iloc[eval_idx] if 'timestamp' in df_m15.columns else eval_idx

        sweep_event = self.sweep_detector.evaluate_sweep(
            df_m15=df_m15,
            target_swing=target_swing,
            direction=direction,
            atr_value=atr_value,
            candle_idx=eval_idx
        )

        if sweep_event is None:
            return WeaknessConfirmation(
                status="NO_SWEEP",
                is_confirmed=False,
                confirmation_candle_idx=eval_idx,
                confirmation_timestamp=ts,
                direction=direction,
                target_swing_level=target_swing.price,
                sweep_event=None,
                weakness_score=0.0,
                reason=f"No sweep occurred past {target_swing.point_type} at {target_swing.price:.4f}"
            )

        if sweep_event.classification == "BREAKOUT_STRENGTH":
            return WeaknessConfirmation(
                status="REJECTED_STRENGTH",
                is_confirmed=False,
                confirmation_candle_idx=eval_idx,
                confirmation_timestamp=ts,
                direction=direction,
                target_swing_level=target_swing.price,
                sweep_event=sweep_event,
                weakness_score=0.0,
                reason=f"Candle closed beyond level ({sweep_event.sweep_candle_close:.4f}) indicating breakout STRENGTH, not weakness"
            )

        if not sweep_event.is_valid_weakness:
            return WeaknessConfirmation(
                status="REJECTED_INSUFFICIENT",
                is_confirmed=False,
                confirmation_candle_idx=eval_idx,
                confirmation_timestamp=ts,
                direction=direction,
                target_swing_level=target_swing.price,
                sweep_event=sweep_event,
                weakness_score=0.0,
                reason=f"Insufficient sweep depth ({sweep_event.sweep_depth_atr:.2f} ATR) or weak rejection wick ({sweep_event.rejection_wick_pct*100:.1f}%)"
            )

        # Valid weakness confirmed!
        return WeaknessConfirmation(
            status="CONFIRMED",
            is_confirmed=True,
            confirmation_candle_idx=eval_idx,
            confirmation_timestamp=ts,
            direction=direction,
            target_swing_level=target_swing.price,
            sweep_event=sweep_event,
            weakness_score=15.0, # Full 15 points
            reason=f"Verified M15 weakness: Swept stops past {target_swing.price:.4f} down to {sweep_event.extreme_price:.4f} and closed back inside with {sweep_event.rejection_wick_pct*100:.1f}% wick"
        )

