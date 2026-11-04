"""
The Only 1 Minute Rectangle Strategy: Market Direction & Trend Detection Engine
Based on Section 1.4 & Part 2 of "The Only 1 Minute Trading Strategy" by Anees Mehdi.

Identifies mechanical market direction using EMA 50, EMA 200, or Both EMAs.
Enforces strict anti-ranging filters using ATR, EMA slope, and distance metrics.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple
import numpy as np
import pandas as pd

from app.quant_v16.rectangle_strategy.strategy_config import RectangleStrategyConfig, EmaFilterType


@dataclass
class TrendAnalysisResult:
    direction: str              # "BULLISH", "BEARISH", or "NEUTRAL"
    is_aligned: bool            # True if direction matches trade continuation
    ema_50: float
    ema_200: float
    ema_fast_slope: float
    ema_slow_slope: float
    dist_to_fast_ema_atr: float
    dist_to_slow_ema_atr: float
    is_ranging: bool            # True if price is chopping sideways around EMA
    ranging_reason: Optional[str] = None
    adx: float = 25.0
    trend_strength_score: float = 0.0 # 0 to 15 points


class TrendDetector:
    """
    Evaluates market direction and filters out sideways ranging periods.
    Supports EMA 50, EMA 200, or Both EMAs combined.
    """

    def __init__(self, config: Optional[RectangleStrategyConfig] = None):
        self.config = config or RectangleStrategyConfig()

    @staticmethod
    def compute_ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        h, l, c = df['high'], df['low'], df['close']
        tr1 = h - l
        tr2 = (h - c.shift(1)).abs()
        tr3 = (l - c.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean().fillna(0.0)

    @staticmethod
    def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Computes Welles Wilder's Average Directional Index (ADX)."""
        if len(df) < period * 2:
            return pd.Series(np.full(len(df), 25.0), index=df.index)

        h, l, c = df['high'], df['low'], df['close']
        up_move = h - h.shift(1)
        down_move = l.shift(1) - l

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        tr1 = h - l
        tr2 = (h - c.shift(1)).abs()
        tr3 = (l - c.shift(1)).abs()
        tr = np.maximum(tr1, np.maximum(tr2, tr3))

        tr_smooth = pd.Series(tr, index=df.index).ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()
        plus_di = 100.0 * pd.Series(plus_dm, index=df.index).ewm(alpha=1.0/period, min_periods=period, adjust=False).mean() / (tr_smooth + 1e-10)
        minus_di = 100.0 * pd.Series(minus_dm, index=df.index).ewm(alpha=1.0/period, min_periods=period, adjust=False).mean() / (tr_smooth + 1e-10)

        dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
        adx = dx.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()
        return adx.fillna(25.0)

    def evaluate_trend(self, df_m15: pd.DataFrame, bar_idx: int = -1) -> TrendAnalysisResult:
        """
        Evaluates trend direction and ranging status on fully closed M15 candles.
        """
        n = len(df_m15)
        idx = bar_idx if bar_idx >= 0 else n + bar_idx
        min_required = min(self.config.ema_fast_period, self.config.ema_slow_period)
        if n < min_required or idx < 0 or idx >= n:
            return TrendAnalysisResult(
                direction="NEUTRAL",
                is_aligned=False,
                ema_50=0.0,
                ema_200=0.0,
                ema_fast_slope=0.0,
                ema_slow_slope=0.0,
                dist_to_fast_ema_atr=0.0,
                dist_to_slow_ema_atr=0.0,
                is_ranging=True,
                ranging_reason="Insufficient history for EMA calculation"
            )

        c = df_m15['close']
        ema_fast = self.compute_ema(c, self.config.ema_fast_period)
        ema_slow = self.compute_ema(c, self.config.ema_slow_period)
        atr_series = self.compute_atr(df_m15, period=14)
        adx_series = self.compute_adx(df_m15, period=14)

        curr_c = float(c.iloc[idx])
        curr_fast = float(ema_fast.iloc[idx])
        curr_slow = float(ema_slow.iloc[idx])
        curr_atr = max(1e-8, float(atr_series.iloc[idx]))
        curr_adx = float(adx_series.iloc[idx])

        # Slope calculations (over configurable lookback)
        lookback = min(self.config.ema_slope_lookback, idx)
        prev_idx = idx - lookback
        fast_slope = (curr_fast - float(ema_fast.iloc[prev_idx])) / curr_atr
        slow_slope = (curr_slow - float(ema_slow.iloc[prev_idx])) / curr_atr

        # Distances in ATR units
        dist_fast_atr = (curr_c - curr_fast) / curr_atr
        dist_slow_atr = (curr_c - curr_slow) / curr_atr

        # Ranging detection:
        # 1. Price is stuck directly on top of the EMA (within proximity threshold)
        is_too_close_fast = abs(dist_fast_atr) < self.config.ema_proximity_atr_mult
        is_too_close_slow = abs(dist_slow_atr) < self.config.ema_proximity_atr_mult

        # 2. ATR Volatility compression: recent 5-bar ATR vs 20-bar ATR mean
        atr_ma20 = float(atr_series.rolling(20, min_periods=5).mean().iloc[idx]) if len(atr_series) >= 5 else curr_atr
        is_compressed = (curr_atr / max(1e-8, atr_ma20)) < self.config.ranging_atr_compression_mult

        # 3. Flat slope: EMAs have virtually zero slope
        is_flat_slope = abs(fast_slope) < 0.05 and abs(slow_slope) < 0.05

        # 4. Weak directional movement (ADX < threshold)
        is_weak_adx = curr_adx < self.config.ranging_adx_threshold

        is_ranging = False
        ranging_reasons = []
        if is_too_close_fast and is_too_close_slow:
            is_ranging = True
            ranging_reasons.append("Price coiled directly on both EMAs")
        if is_compressed and is_flat_slope:
            is_ranging = True
            ranging_reasons.append("Severe volatility compression with flat EMA slope")
        if is_weak_adx and (is_too_close_fast or is_too_close_slow):
            is_ranging = True
            ranging_reasons.append(f"Low ADX ({curr_adx:.1f}) coiling around EMA")

        # Direction resolution based on configured EMA type
        mode = self.config.ema_type
        direction = "NEUTRAL"
        has_slow_data = (n >= self.config.ema_slow_period)

        if mode == EmaFilterType.EMA_50 or not has_slow_data:
            if curr_c > curr_fast and not is_too_close_fast:
                direction = "BULLISH"
            elif curr_c < curr_fast and not is_too_close_fast:
                direction = "BEARISH"
        elif mode == EmaFilterType.EMA_200:
            if curr_c > curr_slow and not is_too_close_slow:
                direction = "BULLISH"
            elif curr_c < curr_slow and not is_too_close_slow:
                direction = "BEARISH"
        else: # BOTH (Default institutional mode)
            if curr_c > curr_fast and curr_c > curr_slow and not is_too_close_fast:
                direction = "BULLISH"
            elif curr_c < curr_fast and curr_c < curr_slow and not is_too_close_fast:
                direction = "BEARISH"

        # Trend strength scoring (up to 15 points)
        score = 0.0
        if direction in ("BULLISH", "BEARISH") and not is_ranging:
            score += 8.0 # Base trend alignment
            if mode == EmaFilterType.BOTH:
                if (direction == "BULLISH" and curr_fast > curr_slow) or (direction == "BEARISH" and curr_fast < curr_slow):
                    score += 4.0 # Stacked EMA order confirmation
            if curr_adx >= 25.0:
                score += 3.0 # Strong trend momentum

        return TrendAnalysisResult(
            direction=direction,
            is_aligned=(direction in ("BULLISH", "BEARISH") and not is_ranging),
            ema_50=round(curr_fast, 6),
            ema_200=round(curr_slow, 6),
            ema_fast_slope=round(fast_slope, 4),
            ema_slow_slope=round(slow_slope, 4),
            dist_to_fast_ema_atr=round(dist_fast_atr, 2),
            dist_to_slow_ema_atr=round(dist_slow_atr, 2),
            is_ranging=is_ranging,
            ranging_reason="; ".join(ranging_reasons) if ranging_reasons else None,
            adx=round(curr_adx, 2),
            trend_strength_score=score
        )
