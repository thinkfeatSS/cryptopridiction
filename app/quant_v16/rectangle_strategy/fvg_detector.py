"""
The Only 1 Minute Rectangle Strategy: Fair Value Gap (FVG) & Imbalance Engine
Based on Section 2.3 & Part 3 (Step 1) of "The Only 1 Minute Trading Strategy" by Anees Mehdi.

Detects 3-candle Fair Value Gaps (Bullish & Bearish Imbalances),
tracks mitigation status, and evaluates confluence with M15 swing levels.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import pandas as pd

from app.quant_v16.rectangle_strategy.strategy_config import RectangleStrategyConfig, FvgFilterMode


@dataclass
class FairValueGap:
    direction: str              # "BULLISH" or "BEARISH"
    upper_boundary: float
    lower_boundary: float
    gap_size: float
    formation_idx: int
    formation_timestamp: Any
    is_mitigated: bool = False
    mitigation_idx: Optional[int] = None
    mitigation_pct: float = 0.0 # 0.0 to 1.0 (1.0 = fully filled)
    is_invalidated: bool = False # Completely blown through


@dataclass
class FvgAnalysisResult:
    has_confluence: bool        # True if swing level or setup is inside/near a valid FVG
    active_fvgs: List[FairValueGap]
    nearest_fvg: Optional[FairValueGap] = None
    dist_to_fvg_atr: float = 999.0
    fvg_score: float = 0.0      # 0 to 10 points


class FVGDetector:
    """
    Detects 3-candle Fair Value Gaps and tracks their life cycle.
    Provides strict or relaxed imbalance confluence filtering.
    """

    def __init__(self, config: Optional[RectangleStrategyConfig] = None):
        self.config = config or RectangleStrategyConfig()

    def detect_fvgs(
        self,
        df_m15: pd.DataFrame,
        up_to_bar: int = -1
    ) -> List[FairValueGap]:
        """
        Scans OHLCV history up to `up_to_bar` to identify unmitigated FVGs.
        A 3-candle pattern forms at bar i (using bars i-2, i-1, i).
        """
        n = len(df_m15)
        eval_idx = n + up_to_bar if up_to_bar < 0 else up_to_bar
        lookback = min(self.config.fvg_lookback_bars, eval_idx - 2)

        if eval_idx < 2:
            return []

        h = df_m15['high'].values
        l = df_m15['low'].values
        ts = df_m15['timestamp'].values if 'timestamp' in df_m15.columns else list(range(n))

        fvgs: List[FairValueGap] = []
        start_idx = max(2, eval_idx - lookback)

        for i in range(start_idx, eval_idx + 1):
            # 1. Bullish FVG: Low of bar i > High of bar i-2
            if l[i] > h[i - 2]:
                lower = float(h[i - 2])
                upper = float(l[i])
                gap = upper - lower
                if gap > 0:
                    fvg = FairValueGap(
                        direction="BULLISH",
                        upper_boundary=upper,
                        lower_boundary=lower,
                        gap_size=gap,
                        formation_idx=i,
                        formation_timestamp=ts[i]
                    )
                    # Check mitigation in bars between i+1 and eval_idx
                    for k in range(i + 1, eval_idx + 1):
                        bar_low = float(l[k])
                        if bar_low <= upper:
                            fvg.is_mitigated = True
                            fill_dist = upper - bar_low
                            fvg.mitigation_pct = min(1.0, max(fvg.mitigation_pct, fill_dist / gap))
                            if bar_low <= lower:
                                fvg.is_invalidated = True
                                break
                    if not fvg.is_invalidated:
                        fvgs.append(fvg)

            # 2. Bearish FVG: High of bar i < Low of bar i-2
            elif h[i] < l[i - 2]:
                upper = float(l[i - 2])
                lower = float(h[i])
                gap = upper - lower
                if gap > 0:
                    fvg = FairValueGap(
                        direction="BEARISH",
                        upper_boundary=upper,
                        lower_boundary=lower,
                        gap_size=gap,
                        formation_idx=i,
                        formation_timestamp=ts[i]
                    )
                    for k in range(i + 1, eval_idx + 1):
                        bar_high = float(h[k])
                        if bar_high >= lower:
                            fvg.is_mitigated = True
                            fill_dist = bar_high - lower
                            fvg.mitigation_pct = min(1.0, max(fvg.mitigation_pct, fill_dist / gap))
                            if bar_high >= upper:
                                fvg.is_invalidated = True
                                break
                    if not fvg.is_invalidated:
                        fvgs.append(fvg)

        return fvgs

    def evaluate_confluence(
        self,
        df_m15: pd.DataFrame,
        target_price: float,
        expected_direction: str,
        atr_value: float,
        current_bar_idx: int = -1
    ) -> FvgAnalysisResult:
        """
        Evaluates whether a target swing level or setup price is inside or close to a valid FVG.
        """
        fvgs = self.detect_fvgs(df_m15, up_to_bar=current_bar_idx)
        dir_fvgs = [f for f in fvgs if f.direction == expected_direction]

        has_confluence = False
        nearest_fvg: Optional[FairValueGap] = None
        min_dist_atr = 999.0
        score = 0.0

        for fvg in dir_fvgs:
            # Check if target price is inside the FVG zone
            if fvg.lower_boundary <= target_price <= fvg.upper_boundary:
                has_confluence = True
                nearest_fvg = fvg
                min_dist_atr = 0.0
                score = 10.0
                break
            else:
                dist = min(abs(target_price - fvg.lower_boundary), abs(target_price - fvg.upper_boundary))
                dist_atr = dist / max(1e-8, atr_value)
                if dist_atr < min_dist_atr:
                    min_dist_atr = dist_atr
                    nearest_fvg = fvg
                    if dist_atr <= 0.50: # Within 0.5 ATR proximity
                        has_confluence = True
                        score = 7.0
                    elif dist_atr <= 1.00:
                        score = 4.0

        return FvgAnalysisResult(
            has_confluence=has_confluence,
            active_fvgs=dir_fvgs,
            nearest_fvg=nearest_fvg,
            dist_to_fvg_atr=round(min_dist_atr, 2),
            fvg_score=score
        )
