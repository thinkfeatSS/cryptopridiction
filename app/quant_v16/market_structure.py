"""
QUANT EDGE V16: Universal Market Structure, Order Block (OB), & Multi-Timeframe (MTF) Engine
Module: app/quant_v16/market_structure.py

Specifications:
1. Pre-AI Multi-Timeframe Gatekeeper:
   - Evaluates pure candlestick market structure strictly BEFORE any AI/ML model inference.
   - Enforces top-down hierarchy: 4H Macro (Weight 3) > 1H Intermediate (Weight 2) > 15M Tactical (Weight 1).
2. Non-Repainting Vectorized Fractal Swings:
   - Swing Highs (HH, LH) & Swing Lows (HL, LL) identified with strict right-bar confirmation.
   - Zero future-bar lookahead leakage.
3. Break of Structure (BOS) & Change of Character (CHoCH) State Machine:
   - Bullish BOS: Candle body close above prior Swing High in Bullish trend.
   - Bearish BOS: Candle body close below prior Swing Low in Bearish trend.
   - Bullish CHoCH: In Bearish trend, first candle body close above prior Lower High ceiling -> shifts state to BULLISH.
   - Bearish CHoCH: In Bullish trend, first candle body close below prior Higher Low floor -> shifts state to BEARISH.
   - Higher timeframe CHoCH has macro precedence and invalidates contrary lower timeframe trends.
4. Institutional Order Block (OB) Engine:
   - Bullish OB: Last down candle (close < open) prior to aggressive upward displacement causing Bullish BOS/CHoCH with FVG. Zone [Low, High].
   - Bearish OB: Last up candle (close > open) prior to aggressive downward displacement causing Bearish BOS/CHoCH with FVG. Zone [Low, High].
   - Lifecycle: ACTIVE -> TESTING (tapped) -> MITIGATED/INVALIDATED (body close beyond distal boundary).
   - Order Block Precedence: 4H OB > 1H OB > 15M OB.
5. Directional Routing Decision Matrix:
   - Scenario A: Price hits active Order Block -> Direction set strictly by OB (4H > 1H > 15M). Bullish OB -> LONG, Bearish OB -> SHORT.
   - Scenario B: No active Order Block hit -> Direction kept strictly aligned with unanimous 4H + 1H + 15M trend. Mixed -> NO_SIGNAL.
   - Opposing POI Guard: Vetoes trades into opposing unmitigated supply/demand blocks.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import pandas as pd

from app.quant_v16.entry_confirmation import format_dynamic_precision


class TrendDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    CHOP = "CHOP"


class TradeDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class OrderBlockCategory(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class OrderBlockStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TESTING = "TESTING"
    MITIGATED = "MITIGATED"
    INVALIDATED = "INVALIDATED"


@dataclass
class SwingPivot:
    index: int
    timestamp: Any
    price: float
    point_type: str             # "SWING_HIGH" or "SWING_LOW"
    structure_type: str         # "HH", "LH", "HL", "LL", or "INITIAL"
    is_broken: bool = False
    broken_timestamp: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "timestamp": str(self.timestamp),
            "price": format_dynamic_precision(self.price),
            "point_type": self.point_type,
            "structure_type": self.structure_type,
            "is_broken": self.is_broken,
            "broken_timestamp": str(self.broken_timestamp) if self.broken_timestamp is not None else None,
        }


@dataclass
class OrderBlockStructure:
    timeframe: str
    block_type: OrderBlockCategory
    status: OrderBlockStatus
    ob_low: float               # Distal boundary for Bullish OB, proximal boundary for Bearish OB
    ob_high: float              # Proximal boundary for Bullish OB, distal boundary for Bearish OB
    candle_index: int
    timestamp: Any
    displacement_pct: float
    has_fvg: bool
    fvg_gap_size: float = 0.0
    touch_count: int = 0
    is_touching: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "block_type": self.block_type.value,
            "status": self.status.value,
            "ob_low": format_dynamic_precision(self.ob_low),
            "ob_high": format_dynamic_precision(self.ob_high),
            "candle_index": self.candle_index,
            "timestamp": str(self.timestamp),
            "displacement_pct": round(self.displacement_pct, 3),
            "has_fvg": self.has_fvg,
            "touch_count": self.touch_count,
            "is_touching": self.is_touching,
        }


@dataclass
class TimeframeStructureProfile:
    timeframe: str
    trend: TrendDirection
    weight: float               # 4h = 3.0, 1h = 2.0, 15m = 1.0
    recent_swing_highs: List[SwingPivot] = field(default_factory=list)
    recent_swing_lows: List[SwingPivot] = field(default_factory=list)
    recent_hl: Optional[SwingPivot] = None
    recent_lh: Optional[SwingPivot] = None
    recent_hh: Optional[SwingPivot] = None
    recent_ll: Optional[SwingPivot] = None
    active_order_blocks: List[OrderBlockStructure] = field(default_factory=list)
    touched_bullish_ob: Optional[OrderBlockStructure] = None
    touched_bearish_ob: Optional[OrderBlockStructure] = None
    has_bos: bool = False
    bos_type: str = "NONE"      # "BULLISH_BOS", "BEARISH_BOS", or "NONE"
    has_choch: bool = False
    choch_type: str = "NONE"    # "BULLISH_CHOCH", "BEARISH_CHOCH", or "NONE"
    choch_price: Optional[float] = None
    structure_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "trend": self.trend.value,
            "weight": self.weight,
            "recent_swing_highs": [s.to_dict() for s in self.recent_swing_highs[-3:]],
            "recent_swing_lows": [s.to_dict() for s in self.recent_swing_lows[-3:]],
            "recent_hl": self.recent_hl.to_dict() if self.recent_hl else None,
            "recent_lh": self.recent_lh.to_dict() if self.recent_lh else None,
            "recent_hh": self.recent_hh.to_dict() if self.recent_hh else None,
            "recent_ll": self.recent_ll.to_dict() if self.recent_ll else None,
            "active_order_blocks_count": len(self.active_order_blocks),
            "has_touched_bullish_ob": self.touched_bullish_ob is not None,
            "has_touched_bearish_ob": self.touched_bearish_ob is not None,
            "has_bos": self.has_bos,
            "bos_type": self.bos_type,
            "has_choch": self.has_choch,
            "choch_type": self.choch_type,
            "choch_price": format_dynamic_precision(self.choch_price) if self.choch_price is not None else None,
            "structure_score": round(self.structure_score, 2),
        }


@dataclass
class PreAIMarketStructureDecision:
    is_unanimously_aligned: bool
    trade_direction: TradeDirection
    scenario: str                                   # "SCENARIO_A_ORDER_BLOCK_TRIGGER" or "SCENARIO_B_TREND_ALIGNMENT" or "NO_SIGNAL"
    dominant_ob_timeframe: Optional[str] = None     # "4H" > "1H" > "15M"
    dominant_order_block: Optional[OrderBlockStructure] = None
    has_order_block: bool = False
    order_block_source: str = "TREND_ALIGNMENT_DEFAULT"
    has_htf_choch: bool = False
    htf_choch_reason: str = ""
    profile_4h: Optional[TimeframeStructureProfile] = None
    profile_1h: Optional[TimeframeStructureProfile] = None
    profile_15m: Optional[TimeframeStructureProfile] = None
    entry_anchor_pivot: Optional[SwingPivot] = None  # 15M HL for Long, 15M LH for Short
    opposing_target_pivot: Optional[SwingPivot] = None
    opposing_ob_veto: bool = False
    veto_reason: str = ""
    reasons: List[str] = field(default_factory=list)

    @property
    def trend_direction(self) -> str:
        if isinstance(self.trade_direction, TradeDirection):
            return self.trade_direction.value
        return str(self.trade_direction)

    @property
    def active_direction(self) -> str:
        return self.trend_direction

    @property
    def dominant_trend(self) -> str:
        return self.scenario

    @property
    def structure_4h(self) -> Optional[TimeframeStructureProfile]:
        return self.profile_4h

    @property
    def structure_1h(self) -> Optional[TimeframeStructureProfile]:
        return self.profile_1h

    @property
    def structure_15m(self) -> Optional[TimeframeStructureProfile]:
        return self.profile_15m

    @property
    def active_ob_15m(self) -> Optional[OrderBlockStructure]:
        if self.profile_15m:
            return self.profile_15m.touched_bullish_ob or self.profile_15m.touched_bearish_ob
        return None

    @property
    def active_ob_1h(self) -> Optional[OrderBlockStructure]:
        if self.profile_1h:
            return self.profile_1h.touched_bullish_ob or self.profile_1h.touched_bearish_ob
        return None

    @property
    def active_ob_4h(self) -> Optional[OrderBlockStructure]:
        if self.profile_4h:
            return self.profile_4h.touched_bullish_ob or self.profile_4h.touched_bearish_ob
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_unanimously_aligned": self.is_unanimously_aligned,
            "trade_direction": self.trade_direction.value if hasattr(self.trade_direction, "value") else str(self.trade_direction),
            "trend_direction": self.trend_direction,
            "scenario": self.scenario,
            "dominant_ob_timeframe": self.dominant_ob_timeframe,
            "dominant_order_block": self.dominant_order_block.to_dict() if self.dominant_order_block else None,
            "has_order_block": self.has_order_block,
            "order_block_source": self.order_block_source,
            "has_htf_choch": self.has_htf_choch,
            "htf_choch_reason": self.htf_choch_reason,
            "profile_4h": self.profile_4h.to_dict() if self.profile_4h else None,
            "profile_1h": self.profile_1h.to_dict() if self.profile_1h else None,
            "profile_15m": self.profile_15m.to_dict() if self.profile_15m else None,
            "structure_4h": self.profile_4h.to_dict() if self.profile_4h else None,
            "structure_1h": self.profile_1h.to_dict() if self.profile_1h else None,
            "structure_15m": self.profile_15m.to_dict() if self.profile_15m else None,
            "active_ob_15m": self.active_ob_15m.to_dict() if self.active_ob_15m else None,
            "active_ob_1h": self.active_ob_1h.to_dict() if self.active_ob_1h else None,
            "active_ob_4h": self.active_ob_4h.to_dict() if self.active_ob_4h else None,
            "entry_anchor_pivot": self.entry_anchor_pivot.to_dict() if self.entry_anchor_pivot else None,
            "opposing_target_pivot": self.opposing_target_pivot.to_dict() if self.opposing_target_pivot else None,
            "opposing_ob_veto": self.opposing_ob_veto,
            "veto_reason": self.veto_reason,
            "reasons": self.reasons,
        }


class MarketStructureEngine:
    """
    Universal Quantitative Smart Money Concepts (SMC) & Multi-Timeframe Structure Engine.
    Operates strictly prior to AI/ML prediction across 4H, 1H, and 15M charts.
    """

    # Timeframe weights: Higher timeframes command superior structural respect
    TIMEFRAME_WEIGHTS = {
        "4h": 3.0,
        "1h": 2.0,
        "15m": 1.0,
    }

    # Non-repainting pivot confirmation windows (Left, Right)
    PIVOT_WINDOWS = {
        "4h": (3, 2),
        "1h": (3, 2),
        "15m": (3, 2),
    }

    @classmethod
    def get_window_params(cls, timeframe: str) -> Tuple[int, int]:
        tf = str(timeframe).lower()
        if "4h" in tf or "240" in tf:
            return cls.PIVOT_WINDOWS["4h"]
        elif "1h" in tf or "60" in tf:
            return cls.PIVOT_WINDOWS["1h"]
        elif "15m" in tf or "15" in tf:
            return cls.PIVOT_WINDOWS["15m"]
        return (3, 2)

    @classmethod
    def find_confirmed_fractals(
        cls,
        df: pd.DataFrame,
        timeframe: str = "15m",
        up_to_bar: int = -1
    ) -> Tuple[List[SwingPivot], List[SwingPivot]]:
        """
        Scans OHLCV history and detects strictly confirmed, non-repainting swing pivots.
        A bar at index i is confirmed ONLY after `right` subsequent bars have fully closed.
        Strict zero future lookahead.
        """
        if df is None or len(df) == 0:
            return [], []

        n = len(df)
        max_idx = n + up_to_bar if up_to_bar < 0 else up_to_bar
        left, right = cls.get_window_params(timeframe)

        if n < 30:
            left = min(left, max(2, n // 6))
            right = min(right, max(1, n // 10))

        if max_idx < (left + right + 1):
            return [], []

        h = df['high'].values.astype(float)
        l = df['low'].values.astype(float)
        c = df['close'].values.astype(float)
        ts = df['timestamp'].values if 'timestamp' in df.columns else list(range(n))

        swing_highs: List[SwingPivot] = []
        swing_lows: List[SwingPivot] = []

        for i in range(left, max_idx - right + 1):
            # Swing High: strictly higher than left bars and right bars
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
                st_type = "INITIAL"
                if swing_highs:
                    st_type = "HH" if h[i] > swing_highs[-1].price else "LH"

                # Check if broken by subsequent candle body closes
                is_broken = False
                broken_ts = None
                for k in range(i + right + 1, max_idx + 1):
                    if k < n and c[k] > h[i]:
                        is_broken = True
                        broken_ts = ts[k]
                        break

                swing_highs.append(SwingPivot(
                    index=i,
                    timestamp=ts[i],
                    price=float(h[i]),
                    point_type="SWING_HIGH",
                    structure_type=st_type,
                    is_broken=is_broken,
                    broken_timestamp=broken_ts
                ))

            # Swing Low: strictly lower than left bars and right bars
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
                st_type = "INITIAL"
                if swing_lows:
                    st_type = "HL" if l[i] > swing_lows[-1].price else "LL"

                # Check if broken by subsequent candle body closes
                is_broken = False
                broken_ts = None
                for k in range(i + right + 1, max_idx + 1):
                    if k < n and c[k] < l[i]:
                        is_broken = True
                        broken_ts = ts[k]
                        break

                swing_lows.append(SwingPivot(
                    index=i,
                    timestamp=ts[i],
                    price=float(l[i]),
                    point_type="SWING_LOW",
                    structure_type=st_type,
                    is_broken=is_broken,
                    broken_timestamp=broken_ts
                ))

        return swing_highs, swing_lows

    @classmethod
    def detect_institutional_order_blocks(
        cls,
        df: pd.DataFrame,
        timeframe: str = "15m",
        current_price: Optional[float] = None,
        max_blocks: int = 6
    ) -> List[OrderBlockStructure]:
        """
        Detects Institutional Order Blocks (OB) with Fair Value Gap (FVG) and displacement verification.
        - Bullish OB: Last down-candle (close < open) prior to aggressive upward displacement causing Bullish BOS/CHoCH with FVG.
        - Bearish OB: Last up-candle (close > open) prior to aggressive downward displacement causing Bearish BOS/CHoCH with FVG.
        - Lifecycle tracked: ACTIVE -> TESTING -> MITIGATED/INVALIDATED (body close beyond distal boundary).
        """
        if df is None or len(df) < 10:
            return []

        curr_p = current_price if (current_price is not None and current_price > 0) else float(df['close'].iloc[-1])
        n = len(df)
        o = df['open'].values.astype(float)
        h = df['high'].values.astype(float)
        l = df['low'].values.astype(float)
        c = df['close'].values.astype(float)
        ts = df['timestamp'].values if 'timestamp' in df.columns else list(range(n))

        # Dynamic ATR for displacement hurdle
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        atr = float(np.mean(tr[-14:])) if len(tr) >= 14 else float(np.mean(tr)) if len(tr) > 0 else (curr_p * 0.01)

        blocks: List[OrderBlockStructure] = []

        # Scan backwards up to 120 bars
        scan_start = max(1, n - 120)
        for i in range(scan_start, n - 2):
            # 1. Bullish Order Block Check
            # Candle i is a down candle (close < open)
            if c[i] < o[i]:
                # Subsequent displacement (candles i+1 and i+2)
                disp = c[i + 1] - o[i + 1]
                disp_2 = (c[i + 2] - o[i + 1]) if (i + 2 < n) else disp
                has_displacement = (disp > (1.2 * atr)) or (disp_2 > (1.8 * atr))

                # Fair Value Gap (FVG): Low of bar i+2 > High of bar i
                has_fvg = False
                fvg_gap = 0.0
                if i + 2 < n and l[i + 2] > h[i]:
                    has_fvg = True
                    fvg_gap = float(l[i + 2] - h[i])

                if has_displacement or has_fvg:
                    ob_low = float(l[i])      # Distal boundary (SL invalidation level)
                    ob_high = float(h[i])     # Proximal boundary (entry touch zone)
                    pct_move = float(disp_2 / max(1e-8, o[i])) * 100.0

                    # Lifecycle check: inspect subsequent bars i+2 to n-1
                    status = OrderBlockStatus.ACTIVE
                    touch_count = 0
                    is_touching = False

                    for k in range(i + 2, n):
                        # Touch check: price enters [ob_low, ob_high]
                        if l[k] <= ob_high and h[k] >= ob_low:
                            touch_count += 1
                            if k == n - 1:
                                is_touching = True
                            if status == OrderBlockStatus.ACTIVE:
                                status = OrderBlockStatus.TESTING

                        # Invalidation: decisive candle body close below distal boundary
                        if c[k] < ob_low:
                            status = OrderBlockStatus.INVALIDATED
                            break

                    # Check current price relation
                    if status != OrderBlockStatus.INVALIDATED:
                        if ob_low <= curr_p <= (ob_high * 1.001):
                            is_touching = True

                        blocks.append(OrderBlockStructure(
                            timeframe=timeframe,
                            block_type=OrderBlockCategory.BULLISH,
                            status=status,
                            ob_low=ob_low,
                            ob_high=ob_high,
                            candle_index=i,
                            timestamp=ts[i],
                            displacement_pct=pct_move,
                            has_fvg=has_fvg,
                            fvg_gap_size=fvg_gap,
                            touch_count=touch_count,
                            is_touching=is_touching
                        ))

            # 2. Bearish Order Block Check
            # Candle i is an up candle (close > open)
            elif c[i] > o[i]:
                # Subsequent downward displacement
                disp = o[i + 1] - c[i + 1]
                disp_2 = (o[i + 1] - c[i + 2]) if (i + 2 < n) else disp
                has_displacement = (disp > (1.2 * atr)) or (disp_2 > (1.8 * atr))

                # Fair Value Gap (FVG): High of bar i+2 < Low of bar i
                has_fvg = False
                fvg_gap = 0.0
                if i + 2 < n and h[i + 2] < l[i]:
                    has_fvg = True
                    fvg_gap = float(l[i] - h[i + 2])

                if has_displacement or has_fvg:
                    ob_low = float(l[i])      # Proximal boundary (entry touch zone)
                    ob_high = float(h[i])     # Distal boundary (SL invalidation level)
                    pct_move = float(disp_2 / max(1e-8, o[i])) * 100.0

                    status = OrderBlockStatus.ACTIVE
                    touch_count = 0
                    is_touching = False

                    for k in range(i + 2, n):
                        if h[k] >= ob_low and l[k] <= ob_high:
                            touch_count += 1
                            if k == n - 1:
                                is_touching = True
                            if status == OrderBlockStatus.ACTIVE:
                                status = OrderBlockStatus.TESTING

                        # Invalidation: decisive candle body close above distal boundary
                        if c[k] > ob_high:
                            status = OrderBlockStatus.INVALIDATED
                            break

                    if status != OrderBlockStatus.INVALIDATED:
                        if (ob_low * 0.999) <= curr_p <= ob_high:
                            is_touching = True

                        blocks.append(OrderBlockStructure(
                            timeframe=timeframe,
                            block_type=OrderBlockCategory.BEARISH,
                            status=status,
                            ob_low=ob_low,
                            ob_high=ob_high,
                            candle_index=i,
                            timestamp=ts[i],
                            displacement_pct=pct_move,
                            has_fvg=has_fvg,
                            fvg_gap_size=fvg_gap,
                            touch_count=touch_count,
                            is_touching=is_touching
                        ))

        # Filter out invalidated blocks and retain active/testing ones sorted by proximity and recency
        valid_blocks = [b for b in blocks if b.status in (OrderBlockStatus.ACTIVE, OrderBlockStatus.TESTING)]
        valid_blocks.sort(key=lambda b: (-b.candle_index, abs((b.ob_high + b.ob_low) / 2.0 - curr_p)))
        return valid_blocks[:max_blocks]

    @classmethod
    def analyze_timeframe(
        cls,
        df: pd.DataFrame,
        timeframe: str = "15m",
        current_price: Optional[float] = None,
        lookback_bars: int = 50
    ) -> TimeframeStructureProfile:
        """
        Analyzes a single timeframe: swing pivots, BOS/CHoCH state transitions, Order Blocks, and trend state.
        """
        weight = cls.TIMEFRAME_WEIGHTS.get(timeframe.lower(), 1.0)
        if df is None or len(df) < 15:
            return TimeframeStructureProfile(timeframe=timeframe, trend=TrendDirection.CHOP, weight=weight)

        curr_p = current_price if (current_price is not None and current_price > 0) else float(df['close'].iloc[-1])
        swing_highs, swing_lows = cls.find_confirmed_fractals(df, timeframe=timeframe)

        eval_idx = len(df) - 1
        recent_sh = [s for s in swing_highs if (eval_idx - s.index) <= lookback_bars]
        recent_sl = [s for s in swing_lows if (eval_idx - s.index) <= lookback_bars]

        recent_hh = next((s for s in reversed(recent_sh) if s.structure_type == "HH"), None)
        recent_lh = next((s for s in reversed(recent_sh) if s.structure_type == "LH"), None)
        recent_hl = next((s for s in reversed(recent_sl) if s.structure_type == "HL"), None)
        recent_ll = next((s for s in reversed(recent_sl) if s.structure_type == "LL"), None)

        hh_count = sum(1 for s in recent_sh if s.structure_type == "HH")
        hl_count = sum(1 for s in recent_sl if s.structure_type == "HL")
        lh_count = sum(1 for s in recent_sh if s.structure_type == "LH")
        ll_count = sum(1 for s in recent_sl if s.structure_type == "LL")

        # ----------------------------------------------------------------------
        # BOS & CHoCH State Machine with Candle Body Close Confirmation
        # ----------------------------------------------------------------------
        has_bos = False
        bos_type = "NONE"
        has_choch = False
        choch_type = "NONE"
        choch_price = None

        # 1. Break of Structure (BOS)
        if len(recent_sh) >= 2 and recent_sh[-1].price > recent_sh[-2].price:
            has_bos = True
            bos_type = "BULLISH_BOS"
        elif recent_sh and curr_p > recent_sh[-1].price:
            has_bos = True
            bos_type = "BULLISH_BOS"

        if len(recent_sl) >= 2 and recent_sl[-1].price < recent_sl[-2].price:
            has_bos = True
            bos_type = "BEARISH_BOS"
        elif recent_sl and curr_p < recent_sl[-1].price:
            has_bos = True
            bos_type = "BEARISH_BOS"

        # 2. Change of Character (CHoCH)
        # Bearish CHoCH: Candle closes decisively below confirmed Higher Low (HL) floor
        if recent_hl and curr_p < (recent_hl.price * 0.999):
            has_choch = True
            choch_type = "BEARISH_CHOCH"
            choch_price = recent_hl.price

        # Bullish CHoCH: Candle closes decisively above confirmed Lower High (LH) ceiling
        if recent_lh and curr_p > (recent_lh.price * 1.001):
            has_choch = True
            choch_type = "BULLISH_CHOCH"
            choch_price = recent_lh.price

        # Trend Decision
        trend = TrendDirection.CHOP
        last_sl = recent_sl[-1] if recent_sl else None
        last_sh = recent_sh[-1] if recent_sh else None

        if (hh_count + hl_count) >= 2 and (lh_count + ll_count) == 0:
            if last_sl is None or curr_p >= (last_sl.price * 0.998):
                if choch_type != "BEARISH_CHOCH":
                    trend = TrendDirection.BULLISH
                else:
                    trend = TrendDirection.CHOP
        elif (lh_count + ll_count) >= 2 and (hh_count + hl_count) == 0:
            if last_sh is None or curr_p <= (last_sh.price * 1.002):
                if choch_type != "BULLISH_CHOCH":
                    trend = TrendDirection.BEARISH
                else:
                    trend = TrendDirection.CHOP
        else:
            bull_points = hh_count + hl_count
            bear_points = lh_count + ll_count
            if bull_points >= 2 and bull_points > (bear_points * 1.5):
                if last_sl and curr_p >= last_sl.price and choch_type != "BEARISH_CHOCH":
                    trend = TrendDirection.BULLISH
            elif bear_points >= 2 and bear_points > (bull_points * 1.5):
                if last_sh and curr_p <= last_sh.price and choch_type != "BULLISH_CHOCH":
                    trend = TrendDirection.BEARISH

        # Momentum progression fallback for uninterrupted directional candles
        if trend == TrendDirection.CHOP:
            c_vals = df['close'].values.astype(float)
            n_bars = min(len(c_vals), lookback_bars)
            if n_bars >= 10:
                c_slice = c_vals[-n_bars:]
                up_moves = int(np.sum(c_slice[1:] > c_slice[:-1]))
                down_moves = int(np.sum(c_slice[1:] < c_slice[:-1]))
                tot_moves = max(1, up_moves + down_moves)
                net_ret = (c_slice[-1] - c_slice[0]) / max(1e-10, c_slice[0])

                if (up_moves / tot_moves) >= 0.65 and net_ret > 0.005:
                    trend = TrendDirection.BULLISH
                    if recent_hl is None:
                        l_vals = df['low'].values[-n_bars:].astype(float)
                        min_idx = len(df) - n_bars + int(np.argmin(l_vals))
                        ts_val = df['timestamp'].iloc[min_idx] if 'timestamp' in df.columns else min_idx
                        recent_hl = SwingPivot(
                            index=min_idx,
                            timestamp=ts_val,
                            price=float(np.min(l_vals)),
                            point_type="SWING_LOW",
                            structure_type="HL"
                        )
                elif (down_moves / tot_moves) >= 0.65 and net_ret < -0.005:
                    trend = TrendDirection.BEARISH
                    if recent_lh is None:
                        h_vals = df['high'].values[-n_bars:].astype(float)
                        max_idx = len(df) - n_bars + int(np.argmax(h_vals))
                        ts_val = df['timestamp'].iloc[max_idx] if 'timestamp' in df.columns else max_idx
                        recent_lh = SwingPivot(
                            index=max_idx,
                            timestamp=ts_val,
                            price=float(np.max(h_vals)),
                            point_type="SWING_HIGH",
                            structure_type="LH"
                        )

        # Detect active order blocks
        active_obs = cls.detect_institutional_order_blocks(
            df=df,
            timeframe=timeframe,
            current_price=curr_p,
            max_blocks=6
        )

        touched_bull = None
        touched_bear = None
        for ob in active_obs:
            if ob.is_touching or ob.status == OrderBlockStatus.TESTING:
                if ob.block_type == OrderBlockCategory.BULLISH and touched_bull is None:
                    touched_bull = ob
                elif ob.block_type == OrderBlockCategory.BEARISH and touched_bear is None:
                    touched_bear = ob

        score = 0.0
        if trend == TrendDirection.BULLISH:
            score += 4.0
            if hl_count >= 1: score += 2.0
            if hh_count >= 1: score += 2.0
            if has_bos: score += 1.0
            if touched_bull: score += 1.0
        elif trend == TrendDirection.BEARISH:
            score += 4.0
            if lh_count >= 1: score += 2.0
            if ll_count >= 1: score += 2.0
            if has_bos: score += 1.0
            if touched_bear: score += 1.0

        return TimeframeStructureProfile(
            timeframe=timeframe,
            trend=trend,
            weight=weight,
            recent_swing_highs=recent_sh,
            recent_swing_lows=recent_sl,
            recent_hl=recent_hl,
            recent_lh=recent_lh,
            recent_hh=recent_hh,
            recent_ll=recent_ll,
            active_order_blocks=active_obs,
            touched_bullish_ob=touched_bull,
            touched_bearish_ob=touched_bear,
            has_bos=has_bos,
            bos_type=bos_type,
            has_choch=has_choch,
            choch_type=choch_type,
            choch_price=choch_price,
            structure_score=min(10.0, score)
        )

    @classmethod
    def evaluate_pre_ai_structure(
        cls,
        df_4h: Optional[pd.DataFrame],
        df_1h: Optional[pd.DataFrame],
        df_15m: Optional[pd.DataFrame],
        current_price: Optional[float] = None
    ) -> PreAIMarketStructureDecision:
        """
        Evaluates pure multi-timeframe market structure and executes the Universal Pre-AI Decision Matrix:
        1. Hierarchy Respect: 4H (Weight 3) > 1H (Weight 2) > 15M (Weight 1).
        2. Scenario A (Active Order Block hit):
           - If price hits an active OB, set trade direction strictly by OB (4H OB > 1H OB > 15M OB).
           - Bullish OB -> LONG, Bearish OB -> SHORT.
        3. Scenario B (No active Order Block hit):
           - If no active OB is touched, direction kept strictly aligned with unanimous 4H + 1H + 15M trend.
           - All 3 Bullish -> LONG, All 3 Bearish -> SHORT.
           - Mixed/chop -> NO_SIGNAL (TradeDirection.NEUTRAL).
        4. Opposing POI Guard:
           - Long setup vetoed if price is colliding into unmitigated HTF Bearish supply.
           - Short setup vetoed if price is colliding into unmitigated HTF Bullish demand.
        """
        reasons: List[str] = []

        if df_15m is None or len(df_15m) < 15:
            return PreAIMarketStructureDecision(
                is_unanimously_aligned=False,
                trade_direction=TradeDirection.NEUTRAL,
                scenario="NO_SIGNAL",
                veto_reason="Insufficient 15M candle history",
                reasons=["15M candle history < 15 bars"]
            )

        curr_p = current_price if (current_price is not None and current_price > 0) else float(df_15m['close'].iloc[-1])
        p_1h = float(df_1h['close'].iloc[-1]) if (df_1h is not None and len(df_1h) > 0) else curr_p
        p_4h = float(df_4h['close'].iloc[-1]) if (df_4h is not None and len(df_4h) > 0) else curr_p

        prof_15m = cls.analyze_timeframe(df_15m, timeframe="15m", current_price=curr_p)
        prof_1h = cls.analyze_timeframe(df_1h, timeframe="1h", current_price=p_1h) if (df_1h is not None and len(df_1h) >= 15) else None
        prof_4h = cls.analyze_timeframe(df_4h, timeframe="4h", current_price=p_4h) if (df_4h is not None and len(df_4h) >= 15) else None

        t_15m = prof_15m.trend
        t_1h = prof_1h.trend if prof_1h else TrendDirection.CHOP
        t_4h = prof_4h.trend if prof_4h else TrendDirection.CHOP

        # ----------------------------------------------------------------------
        # HIGHER TIMEFRAME CHoCH STRUCTURAL GUARD (MACRO PRECEDENCE)
        # ----------------------------------------------------------------------
        # If 4H or 1H experienced an opposing or structural CHoCH, it takes macro authority
        # and immediately invalidates lower timeframe setups
        has_htf_choch = False
        htf_choch_reason = ""

        if t_15m == TrendDirection.BULLISH:
            if prof_4h and prof_4h.has_choch and prof_4h.choch_type == "BEARISH_CHOCH":
                has_htf_choch = True
                htf_choch_reason = f"4H Bearish Change of Character (CHoCH) broke Higher Low floor at ${prof_4h.choch_price}"
            elif prof_1h and prof_1h.has_choch and prof_1h.choch_type == "BEARISH_CHOCH":
                has_htf_choch = True
                htf_choch_reason = f"1H Bearish Change of Character (CHoCH) broke Higher Low floor at ${prof_1h.choch_price}"
        elif t_15m == TrendDirection.BEARISH:
            if prof_4h and prof_4h.has_choch and prof_4h.choch_type == "BULLISH_CHOCH":
                has_htf_choch = True
                htf_choch_reason = f"4H Bullish Change of Character (CHoCH) broke Lower High ceiling at ${prof_4h.choch_price}"
            elif prof_1h and prof_1h.has_choch and prof_1h.choch_type == "BULLISH_CHOCH":
                has_htf_choch = True
                htf_choch_reason = f"1H Bullish Change of Character (CHoCH) broke Lower High ceiling at ${prof_1h.choch_price}"
        elif prof_4h and prof_4h.has_choch:
            has_htf_choch = True
            htf_choch_reason = f"4H {prof_4h.choch_type} broke structural level at ${prof_4h.choch_price}"
        elif prof_1h and prof_1h.has_choch:
            has_htf_choch = True
            htf_choch_reason = f"1H {prof_1h.choch_type} broke structural level at ${prof_1h.choch_price}"

        if has_htf_choch:
            reasons.append(htf_choch_reason)
            return PreAIMarketStructureDecision(
                is_unanimously_aligned=False,
                trade_direction=TradeDirection.NEUTRAL,
                scenario="NO_SIGNAL",
                has_htf_choch=True,
                htf_choch_reason=htf_choch_reason,
                profile_4h=prof_4h,
                profile_1h=prof_1h,
                profile_15m=prof_15m,
                veto_reason=htf_choch_reason,
                reasons=reasons
            )

        # ----------------------------------------------------------------------
        # Check touched Order Blocks across timeframes with strict HTF precedence
        # Precedence: 4H OB > 1H OB > 15M OB
        # ----------------------------------------------------------------------
        touched_obs: List[Tuple[int, OrderBlockStructure]] = []
        # (priority, ob): priority 1 = 4H, 2 = 1H, 3 = 15M
        if prof_4h:
            if prof_4h.touched_bullish_ob: touched_obs.append((1, prof_4h.touched_bullish_ob))
            if prof_4h.touched_bearish_ob: touched_obs.append((1, prof_4h.touched_bearish_ob))
        if prof_1h:
            if prof_1h.touched_bullish_ob: touched_obs.append((2, prof_1h.touched_bullish_ob))
            if prof_1h.touched_bearish_ob: touched_obs.append((2, prof_1h.touched_bearish_ob))
        if prof_15m.touched_bullish_ob: touched_obs.append((3, prof_15m.touched_bullish_ob))
        if prof_15m.touched_bearish_ob: touched_obs.append((3, prof_15m.touched_bearish_ob))

        touched_obs.sort(key=lambda x: x[0])  # Sort by priority ascending (1 is highest)

        chosen_ob: Optional[OrderBlockStructure] = None
        chosen_ob_tf: Optional[str] = None
        scenario = "SCENARIO_B_TREND_ALIGNMENT"
        trade_dir = TradeDirection.NEUTRAL

        if touched_obs:
            # SCENARIO A: Price hits active Order Block
            # Direction set strictly by OB (HTF has highest authority)
            _, top_ob = touched_obs[0]
            chosen_ob = top_ob
            chosen_ob_tf = top_ob.timeframe.upper()
            scenario = "SCENARIO_A_ORDER_BLOCK_TRIGGER"

            if top_ob.block_type == OrderBlockCategory.BULLISH:
                trade_dir = TradeDirection.LONG
                reasons.append(f"Price tapped active {chosen_ob_tf} Bullish Order Block at [${top_ob.ob_low:.4f} - ${top_ob.ob_high:.4f}] -> Bias set to LONG")
            else:
                trade_dir = TradeDirection.SHORT
                reasons.append(f"Price tapped active {chosen_ob_tf} Bearish Order Block at [${top_ob.ob_low:.4f} - ${top_ob.ob_high:.4f}] -> Bias set to SHORT")
        else:
            # SCENARIO B: No active Order Block hit
            # Direction kept strictly aligned with unanimous 4H + 1H + 15M trend
            is_bullish_unanimous = (t_4h == TrendDirection.BULLISH and t_1h == TrendDirection.BULLISH and t_15m == TrendDirection.BULLISH)
            is_bearish_unanimous = (t_4h == TrendDirection.BEARISH and t_1h == TrendDirection.BEARISH and t_15m == TrendDirection.BEARISH)

            # Cold start fallback for missing HTFs
            if prof_4h is None and prof_1h is not None:
                is_bullish_unanimous = (t_1h == TrendDirection.BULLISH and t_15m == TrendDirection.BULLISH)
                is_bearish_unanimous = (t_1h == TrendDirection.BEARISH and t_15m == TrendDirection.BEARISH)
            elif prof_4h is None and prof_1h is None:
                is_bullish_unanimous = (t_15m == TrendDirection.BULLISH and prof_15m.recent_hl is not None)
                is_bearish_unanimous = (t_15m == TrendDirection.BEARISH and prof_15m.recent_lh is not None)

            if is_bullish_unanimous:
                trade_dir = TradeDirection.LONG
                reasons.append(f"No active order block hit; unanimous Bullish trend alignment (4H={t_4h.value}, 1H={t_1h.value}, 15M={t_15m.value}) -> Bias set to LONG")
            elif is_bearish_unanimous:
                trade_dir = TradeDirection.SHORT
                reasons.append(f"No active order block hit; unanimous Bearish trend alignment (4H={t_4h.value}, 1H={t_1h.value}, 15M={t_15m.value}) -> Bias set to SHORT")
            else:
                trade_dir = TradeDirection.NEUTRAL
                scenario = "NO_SIGNAL"
                veto = f"Timeframe divergence / chop: 4H={t_4h.value}, 1H={t_1h.value}, 15M={t_15m.value}"
                reasons.append(veto)
                return PreAIMarketStructureDecision(
                    is_unanimously_aligned=False,
                    trade_direction=TradeDirection.NEUTRAL,
                    scenario="NO_SIGNAL",
                    profile_4h=prof_4h,
                    profile_1h=prof_1h,
                    profile_15m=prof_15m,
                    veto_reason=veto,
                    reasons=reasons
                )

        # ----------------------------------------------------------------------
        # OPPOSING ORDER BLOCK COLLISION GUARD
        # ----------------------------------------------------------------------
        obs_15m = prof_15m.active_order_blocks
        obs_1h = prof_1h.active_order_blocks if prof_1h else []
        obs_4h = prof_4h.active_order_blocks if prof_4h else []

        opposing_ob_veto = False
        veto_reason = ""

        if trade_dir == TradeDirection.LONG:
            for ob in (obs_4h + obs_1h + obs_15m):
                if ob.block_type == OrderBlockCategory.BEARISH and ob.status in (OrderBlockStatus.ACTIVE, OrderBlockStatus.TESTING):
                    if curr_p >= (ob.ob_low - 0.001 * ob.ob_low) and curr_p <= (ob.ob_high + 0.001 * ob.ob_high):
                        opposing_ob_veto = True
                        veto_reason = f"Opposing Bearish Supply Block Collision on {ob.timeframe.upper()} [{ob.ob_low:.4f} - {ob.ob_high:.4f}]"
                        reasons.append(veto_reason)
                        break
        elif trade_dir == TradeDirection.SHORT:
            for ob in (obs_4h + obs_1h + obs_15m):
                if ob.block_type == OrderBlockCategory.BULLISH and ob.status in (OrderBlockStatus.ACTIVE, OrderBlockStatus.TESTING):
                    if curr_p >= (ob.ob_low - 0.001 * ob.ob_low) and curr_p <= (ob.ob_high + 0.001 * ob.ob_high):
                        opposing_ob_veto = True
                        veto_reason = f"Opposing Bullish Demand Block Collision on {ob.timeframe.upper()} [{ob.ob_low:.4f} - {ob.ob_high:.4f}]"
                        reasons.append(veto_reason)
                        break

        if opposing_ob_veto:
            return PreAIMarketStructureDecision(
                is_unanimously_aligned=False,
                trade_direction=TradeDirection.NEUTRAL,
                scenario="NO_SIGNAL",
                dominant_ob_timeframe=chosen_ob_tf,
                dominant_order_block=chosen_ob,
                has_order_block=(chosen_ob is not None),
                order_block_source=f"{chosen_ob_tf}_ORDER_BLOCK" if chosen_ob_tf else "TREND_ALIGNMENT_DEFAULT",
                profile_4h=prof_4h,
                profile_1h=prof_1h,
                profile_15m=prof_15m,
                opposing_ob_veto=True,
                veto_reason=veto_reason,
                reasons=reasons
            )

        # ----------------------------------------------------------------------
        # 15M TACTICAL EXECUTION ANCHORING (HL FOR LONG, LH FOR SHORT)
        # ----------------------------------------------------------------------
        entry_anchor: Optional[SwingPivot] = None
        opposing_target: Optional[SwingPivot] = None

        if trade_dir == TradeDirection.LONG:
            entry_anchor = prof_15m.recent_hl
            if entry_anchor is None and prof_15m.recent_swing_lows:
                # Strictly select a confirmed Higher Low (HL), never an invalid Lower Low (LL)
                hl_candidates = [s for s in prof_15m.recent_swing_lows if s.structure_type == "HL"]
                entry_anchor = hl_candidates[-1] if hl_candidates else None
            if prof_15m.recent_swing_highs:
                opposing_target = max(prof_15m.recent_swing_highs, key=lambda s: s.price)

        elif trade_dir == TradeDirection.SHORT:
            entry_anchor = prof_15m.recent_lh
            if entry_anchor is None and prof_15m.recent_swing_highs:
                # Strictly select a confirmed Lower High (LH), never an invalid Higher High (HH)
                lh_candidates = [s for s in prof_15m.recent_swing_highs if s.structure_type == "LH"]
                entry_anchor = lh_candidates[-1] if lh_candidates else None
            if prof_15m.recent_swing_lows:
                opposing_target = min(prof_15m.recent_swing_lows, key=lambda s: s.price)

        ob_src = f"{chosen_ob_tf}_ORDER_BLOCK" if chosen_ob_tf else "TREND_ALIGNMENT_DEFAULT"

        return PreAIMarketStructureDecision(
            is_unanimously_aligned=True,
            trade_direction=trade_dir,
            scenario=scenario,
            dominant_ob_timeframe=chosen_ob_tf or "15M",
            dominant_order_block=chosen_ob,
            has_order_block=(chosen_ob is not None),
            order_block_source=ob_src,
            profile_4h=prof_4h,
            profile_1h=prof_1h,
            profile_15m=prof_15m,
            entry_anchor_pivot=entry_anchor,
            opposing_target_pivot=opposing_target,
            opposing_ob_veto=False,
            veto_reason="",
            reasons=reasons
        )
