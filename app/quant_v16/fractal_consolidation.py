"""
QUANT EDGE V16: Fractal Consolidation & Multi-Timeframe Candlestick Engine
Analyzes candlestick patterns and statistical volatility on each timeframe independently to classify:
1. TREND_BULLISH / TREND_BEARISH
2. CONSOLIDATION_COILING (Tight Inside Bar/NR7/BBW squeeze - spring loaded)
3. CONSOLIDATION_RANGING (Wide horizontal box between Range High & Range Low)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional
import numpy as np
import pandas as pd


class FractalTimeframeState(str, Enum):
    TREND_BULLISH = "TREND_BULLISH"
    TREND_BEARISH = "TREND_BEARISH"
    CONSOLIDATION_COILING = "CONSOLIDATION_COILING"
    CONSOLIDATION_RANGING = "CONSOLIDATION_RANGING"


@dataclass
class TimeframeConsolidationProfile:
    timeframe: str
    state: FractalTimeframeState
    is_consolidation: bool
    is_coiling_squeeze: bool
    chop_index: float
    adx: float
    bbw_pct: float
    is_inside_bar: bool
    is_nr7: bool
    is_nr4: bool
    is_doji: bool
    compression_score: float
    range_high: float
    range_low: float
    range_mid: float
    position_in_range_pct: float  # 0.0 at range low, 1.0 at range high
    headroom_to_high_pct: float
    headroom_to_low_pct: float
    current_price: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "state": self.state.value,
            "is_consolidation": self.is_consolidation,
            "is_coiling_squeeze": self.is_coiling_squeeze,
            "chop_index": round(self.chop_index, 1),
            "adx": round(self.adx, 1),
            "bbw_pct": round(self.bbw_pct, 2),
            "is_inside_bar": self.is_inside_bar,
            "is_nr7": self.is_nr7,
            "is_nr4": self.is_nr4,
            "is_doji": self.is_doji,
            "compression_score": round(self.compression_score, 2),
            "range_high": self.range_high,
            "range_low": self.range_low,
            "range_mid": self.range_mid,
            "position_in_range_pct": round(self.position_in_range_pct, 2),
            "headroom_to_high_pct": round(self.headroom_to_high_pct, 2),
            "headroom_to_low_pct": round(self.headroom_to_low_pct, 2),
            "current_price": self.current_price,
        }


class FractalConsolidationEngine:
    """
    Evaluates individual horizon candles to diagnose consolidation vs trend with institutional precision.
    """

    @staticmethod
    def analyze_timeframe(df: pd.DataFrame, timeframe: str = "15m", lookback_box: int = 20) -> TimeframeConsolidationProfile:
        if df is None or len(df) < 15:
            return TimeframeConsolidationProfile(
                timeframe=timeframe,
                state=FractalTimeframeState.CONSOLIDATION_COILING,
                is_consolidation=True,
                is_coiling_squeeze=True,
                chop_index=50.0,
                adx=20.0,
                bbw_pct=1.0,
                is_inside_bar=False,
                is_nr7=False,
                is_nr4=False,
                is_doji=False,
                compression_score=0.5,
                range_high=0.0,
                range_low=0.0,
                range_mid=0.0,
                position_in_range_pct=0.5,
                headroom_to_high_pct=0.0,
                headroom_to_low_pct=0.0,
                current_price=0.0,
            )

        c = df["close"]
        h = df["high"]
        l = df["low"]
        o = df["open"]
        v = df["volume"] if "volume" in df.columns else pd.Series(1.0, index=df.index)

        current_price = float(c.iloc[-1])
        cur_high = float(h.iloc[-1])
        cur_low = float(l.iloc[-1])
        cur_open = float(o.iloc[-1])
        prev_high = float(h.iloc[-2]) if len(df) >= 2 else cur_high
        prev_low = float(l.iloc[-2]) if len(df) >= 2 else cur_low

        # 1. Candlestick Anatomy
        # For discrete candlestick patterns (Inside Bar, NR4, NR7, Doji):
        # We MUST evaluate the most recently completed candle (iloc[-2]) against its predecessors
        # to prevent incomplete, newly opened live candles from generating 100% false positives!
        if len(df) >= 3:
            closed_high = float(h.iloc[-2])
            closed_low = float(l.iloc[-2])
            closed_open = float(o.iloc[-2])
            closed_close = float(c.iloc[-2])
            mother_high = float(h.iloc[-3])
            mother_low = float(l.iloc[-3])

            closed_bar_range = max(1e-10, closed_high - closed_low)
            closed_body = abs(closed_close - closed_open)
            closed_body_ratio = closed_body / closed_bar_range

            # Inside Bar: Last completed bar was inside mother bar, and live price has not broken out yet
            raw_inside_bar = bool(closed_high <= mother_high and closed_low >= mother_low)
            has_broken_out = bool(current_price > mother_high or current_price < mother_low)
            is_inside_bar = bool(raw_inside_bar and not has_broken_out)

            # NR4 & NR7 over preceding completed candles
            prior_ranges = (h - l).iloc[-8:-1] if len(df) >= 8 else (h - l).iloc[:-1]
            is_nr4 = bool(closed_bar_range <= prior_ranges.iloc[-4:].min() + 1e-10) if len(prior_ranges) >= 4 else False
            is_nr7 = bool(closed_bar_range <= prior_ranges.min() + 1e-10) if len(prior_ranges) >= 7 else False
            is_doji = bool(closed_body_ratio < 0.20)
        else:
            is_inside_bar = False
            is_nr4 = False
            is_nr7 = False
            is_doji = False

        # 2. Bollinger Band Width
        sma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        upper_bb = sma20 + 2.0 * std20
        lower_bb = sma20 - 2.0 * std20
        bbw_series = ((upper_bb - lower_bb) / (sma20 + 1e-10)) * 100.0
        cur_bbw = float(bbw_series.iloc[-1]) if not np.isnan(bbw_series.iloc[-1]) else 1.0

        # Squeeze Thresholds by Timeframe
        bbw_squeeze_threshold = 1.2 if timeframe in ["5m", "15m"] else (2.0 if timeframe in ["1h", "4h"] else 3.8)

        # 3. Choppiness Index (14)
        period = 14
        tr1 = h - l
        tr2 = (h - c.shift(1)).abs()
        tr3 = (l - c.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr_sum = tr.rolling(period).sum()
        high_max = h.rolling(period).max()
        low_min = l.rolling(period).min()
        denom = high_max - low_min
        chop_series = 100.0 * (np.log10(atr_sum / (denom + 1e-10)) / np.log10(period))
        chop_val = float(chop_series.iloc[-1]) if not np.isnan(chop_series.iloc[-1]) else 50.0
        chop_val = max(0.0, min(100.0, chop_val))

        # 4. ADX (14)
        up_move = h - h.shift(1)
        down_move = l.shift(1) - l
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        atr_smooth = tr.ewm(alpha=1.0 / period, adjust=False).mean()
        plus_di = 100.0 * pd.Series(plus_dm, index=df.index).ewm(alpha=1.0 / period, adjust=False).mean() / (atr_smooth + 1e-10)
        minus_di = 100.0 * pd.Series(minus_dm, index=df.index).ewm(alpha=1.0 / period, adjust=False).mean() / (atr_smooth + 1e-10)
        dx = 100.0 * (plus_di - minus_di).abs() / ((plus_di + minus_di) + 1e-10)
        adx_series = dx.ewm(alpha=1.0 / period, adjust=False).mean()
        adx_val = float(adx_series.iloc[-1]) if not np.isnan(adx_series.iloc[-1]) else 20.0

        # 5. Moving Average Alignment (Directional velocity)
        ema20 = c.ewm(span=20, adjust=False).mean().iloc[-1]
        ema50 = c.ewm(span=50, adjust=False).mean().iloc[-1]
        ema20_prev = c.ewm(span=20, adjust=False).mean().iloc[-2] if len(df) >= 2 else ema20
        ema_slope = (ema20 - ema20_prev) / (current_price + 1e-10)

        # 6. Range Box Calculation (Over lookback window)
        box_n = min(len(df), lookback_box)
        prior_high_window = h.iloc[-box_n:-1] if box_n > 1 else h.iloc[-box_n:]
        prior_low_window = l.iloc[-box_n:-1] if box_n > 1 else l.iloc[-box_n:]
        range_high = float(prior_high_window.max())
        range_low = float(prior_low_window.min())
        range_span = max(1e-10, range_high - range_low)
        range_mid = range_low + (range_span * 0.5)

        position_in_range_pct = max(0.0, min(1.0, (current_price - range_low) / range_span))

        # Breakout handling: If price breaches range ceiling or floor, headroom expands
        is_breakout_high = bool(current_price >= range_high)
        is_breakout_low = bool(current_price <= range_low)

        if is_breakout_high:
            headroom_to_high_pct = 99.0  # Blue-sky expansion headroom
        else:
            headroom_to_high_pct = max(0.0, ((range_high - current_price) / current_price) * 100.0)

        if is_breakout_low:
            headroom_to_low_pct = 99.0  # Blue-sky breakdown headroom
        else:
            headroom_to_low_pct = max(0.0, ((current_price - range_low) / current_price) * 100.0)

        # 7. Compression Score
        comp_score = 0.0
        if is_inside_bar: comp_score += 0.35
        if is_nr7: comp_score += 0.35
        elif is_nr4: comp_score += 0.20
        if is_doji: comp_score += 0.15
        if cur_bbw <= bbw_squeeze_threshold: comp_score += 0.25
        if chop_val >= 60.0: comp_score += 0.20
        compression_score = min(1.0, comp_score)

        # 8. State Classification
        # Coiling squeeze: either statistical BBW squeeze OR candlestick anatomy squeeze (Inside Bar + NR7/NR4)
        is_coiling = bool(
            not is_breakout_high and not is_breakout_low and (
                (cur_bbw <= bbw_squeeze_threshold and (is_inside_bar or is_nr7 or is_nr4 or chop_val >= 58.0)) or
                (is_inside_bar and (is_nr7 or is_nr4)) or
                (is_inside_bar and cur_bbw <= 3.5) or
                (compression_score >= 0.50 and cur_bbw <= (bbw_squeeze_threshold * 2.0))
            )
        )

        is_ranging = bool(
            not is_coiling and not is_breakout_high and not is_breakout_low and
            (chop_val >= 55.0 or adx_val < 20.0 or abs(ema_slope) < 0.0003) and
            range_span / (current_price + 1e-10) > 0.015  # wide enough box
        )

        # Breakouts take precedence over consolidation
        if is_breakout_high and current_price > ema20 and ema20 >= ema50:
            state = FractalTimeframeState.TREND_BULLISH
            is_consolidation = False
        elif is_breakout_low and current_price < ema20 and ema20 <= ema50:
            state = FractalTimeframeState.TREND_BEARISH
            is_consolidation = False
        elif is_coiling:
            state = FractalTimeframeState.CONSOLIDATION_COILING
            is_consolidation = True
        elif is_ranging:
            state = FractalTimeframeState.CONSOLIDATION_RANGING
            is_consolidation = True
        else:
            is_consolidation = False
            if current_price > ema20 and ema20 >= ema50 and adx_val >= 18.0:
                state = FractalTimeframeState.TREND_BULLISH
            elif current_price < ema20 and ema20 <= ema50 and adx_val >= 18.0:
                state = FractalTimeframeState.TREND_BEARISH
            else:
                # Weak slope defaults to ranging
                state = FractalTimeframeState.CONSOLIDATION_RANGING
                is_consolidation = True

        return TimeframeConsolidationProfile(
            timeframe=timeframe,
            state=state,
            is_consolidation=is_consolidation,
            is_coiling_squeeze=is_coiling,
            chop_index=chop_val,
            adx=adx_val,
            bbw_pct=cur_bbw,
            is_inside_bar=is_inside_bar,
            is_nr7=is_nr7,
            is_nr4=is_nr4,
            is_doji=is_doji,
            compression_score=compression_score,
            range_high=range_high,
            range_low=range_low,
            range_mid=range_mid,
            position_in_range_pct=position_in_range_pct,
            headroom_to_high_pct=headroom_to_high_pct,
            headroom_to_low_pct=headroom_to_low_pct,
            current_price=current_price,
        )

    @staticmethod
    def analyze_all_horizons(horizons_dfs: Dict[str, pd.DataFrame]) -> Dict[str, TimeframeConsolidationProfile]:
        profiles = {}
        for tf, df in horizons_dfs.items():
            profiles[tf] = FractalConsolidationEngine.analyze_timeframe(df, timeframe=tf)
        return profiles
