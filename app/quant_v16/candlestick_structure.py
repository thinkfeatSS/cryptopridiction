"""
QUANT EDGE V16: Universal Candlestick Market Structure & Order Block Engine
Specifications:
- Pure Candlestick Price Action Trend Analysis executed BEFORE ML inferences across 4H, 1H, and 15M charts.
- Non-repainting Swing Pivot Detection (HH, HL, LH, LL) requiring right-bar confirmation.
- Strict Timeframe Respect Hierarchy: Weight(4H) > Weight(1H) > Weight(15M).
- Unanimous Structural Congruence: All 3 timeframes must agree (4H Bullish + 1H Bullish + 15M Bullish for Long,
  or 4H Bearish + 1H Bearish + 15M Bearish for Short). Non-aligned pairs fail closed to eliminate chop.
- Institutional Order Block Mitigation:
  * Bullish Order Block mitigation -> Triggers/confirms LONG direction.
  * Bearish Order Block mitigation -> Triggers/confirms SHORT direction.
  * Opposing Order Block Guard -> Vetoes trades into overhead supply or underlying demand.
- Tactical 15M Entry Anchoring:
  * LONG: Entry strictly anchored to confirmed 15M Higher Low (HL) inside/retesting Bullish OB.
  * SHORT: Entry strictly anchored to confirmed 15M Lower High (LH) inside/rejecting Bearish OB.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import pandas as pd

from app.quant_v16.entry_confirmation import format_dynamic_precision
from app.quant_v16.order_blocks import (
    InstitutionalOrderBlockEngine,
    OrderBlock,
    OrderBlockType,
    OrderBlockState,
    OrderBlockRank
)


@dataclass
class SwingPoint:
    index: int
    timestamp: Any
    price: float
    point_type: str             # "SWING_HIGH" or "SWING_LOW"
    structure_type: str         # "HH", "LH", "HL", "LL", or "INITIAL"
    is_broken: bool = False     # True if decisive close beyond level occurred (BOS)
    broken_timestamp: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "timestamp": str(self.timestamp),
            "price": format_dynamic_precision(self.price),
            "point_type": self.point_type,
            "structure_type": self.structure_type,
            "is_broken": self.is_broken,
        }


@dataclass
class TimeframeStructure:
    timeframe: str
    trend: str                  # "BULLISH", "BEARISH", or "CHOP"
    recent_swing_highs: List[SwingPoint] = field(default_factory=list)
    recent_swing_lows: List[SwingPoint] = field(default_factory=list)
    recent_hl: Optional[SwingPoint] = None
    recent_lh: Optional[SwingPoint] = None
    recent_hh: Optional[SwingPoint] = None
    recent_ll: Optional[SwingPoint] = None
    active_order_blocks: List[OrderBlock] = field(default_factory=list)
    touched_bullish_ob: Optional[OrderBlock] = None
    touched_bearish_ob: Optional[OrderBlock] = None
    has_bos: bool = False
    bos_type: str = "NONE"      # "BULLISH_BOS", "BEARISH_BOS", or "NONE"
    has_choch: bool = False
    choch_type: str = "NONE"    # "BULLISH_CHOCH", "BEARISH_CHOCH", or "NONE"
    choch_price: Optional[float] = None
    structure_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "trend": self.trend,
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
class TriadStructureResult:
    is_unanimously_aligned: bool
    trend_direction: str        # "LONG", "SHORT", or "NEUTRAL"
    structure_4h: Optional[TimeframeStructure] = None
    structure_1h: Optional[TimeframeStructure] = None
    structure_15m: Optional[TimeframeStructure] = None
    active_ob_15m: Optional[OrderBlock] = None
    active_ob_1h: Optional[OrderBlock] = None
    active_ob_4h: Optional[OrderBlock] = None
    dominant_ob_timeframe: str = "15M"                  # "4H" > "1H" > "15M"
    dominant_order_block: Optional[OrderBlock] = None
    has_order_block: bool = False
    order_block_source: str = "TREND_ALIGNMENT_DEFAULT" # "4H_ORDER_BLOCK", "1H_ORDER_BLOCK", "15M_ORDER_BLOCK", or "TREND_ALIGNMENT_DEFAULT"
    has_htf_choch: bool = False
    htf_choch_reason: str = ""
    entry_anchor_pivot: Optional[SwingPoint] = None     # 15M HL for Long, 15M LH for Short
    opposing_target_pivot: Optional[SwingPoint] = None  # 15M SH for Long, 15M SL for Short
    opposing_ob_veto: bool = False
    veto_reason: str = ""
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_unanimously_aligned": self.is_unanimously_aligned,
            "trend_direction": self.trend_direction,
            "structure_4h": self.structure_4h.to_dict() if self.structure_4h else None,
            "structure_1h": self.structure_1h.to_dict() if self.structure_1h else None,
            "structure_15m": self.structure_15m.to_dict() if self.structure_15m else None,
            "active_ob_15m": self.active_ob_15m.to_dict() if self.active_ob_15m else None,
            "active_ob_1h": self.active_ob_1h.to_dict() if self.active_ob_1h else None,
            "active_ob_4h": self.active_ob_4h.to_dict() if self.active_ob_4h else None,
            "dominant_ob_timeframe": self.dominant_ob_timeframe,
            "dominant_order_block": self.dominant_order_block.to_dict() if self.dominant_order_block else None,
            "has_order_block": self.has_order_block,
            "order_block_source": self.order_block_source,
            "has_htf_choch": self.has_htf_choch,
            "htf_choch_reason": self.htf_choch_reason,
            "entry_anchor_pivot": self.entry_anchor_pivot.to_dict() if self.entry_anchor_pivot else None,
            "opposing_target_pivot": self.opposing_target_pivot.to_dict() if self.opposing_target_pivot else None,
            "opposing_ob_veto": self.opposing_ob_veto,
            "veto_reason": self.veto_reason,
            "reasons": self.reasons,
        }


class CandlestickStructureEngine:
    """
    Core Pure Candlestick Price Action and Market Structure Analyzer.
    Operates strictly prior to ML prediction to enforce structural discipline and
    institutional order block mitigation rules across 4H, 1H, and 15M timeframes.
    """

    # Non-repainting pivot confirmation windows (Left, Right)
    LOOKBACK_WINDOWS = {
        "4h": (3, 2),    # 4H Macro: 3 left, 2 right (captures major multi-day turns)
        "1h": (3, 2),    # 1H Context: 3 left, 2 right (captures intraday shifts)
        "15m": (3, 2),   # 15M Tactical: 3 left, 2 right (high-fidelity scalp swing points)
    }

    @classmethod
    def get_window_params(cls, timeframe: str) -> Tuple[int, int]:
        tf = str(timeframe).lower()
        if "4h" in tf or "240" in tf:
            return cls.LOOKBACK_WINDOWS["4h"]
        elif "1h" in tf or "60" in tf:
            return cls.LOOKBACK_WINDOWS["1h"]
        elif "15m" in tf or "15" in tf:
            return cls.LOOKBACK_WINDOWS["15m"]
        return (4, 2)

    @classmethod
    def find_confirmed_swings(
        cls,
        df: pd.DataFrame,
        timeframe: str = "15m",
        up_to_bar: int = -1
    ) -> Tuple[List[SwingPoint], List[SwingPoint]]:
        """
        Scans OHLCV history to locate strictly confirmed, non-repainting swing pivots.
        A bar at index `i` is confirmed as a pivot ONLY after `right` bars have fully closed.
        Zero future-bar lookahead leakage.
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

        h = df['high'].values
        l = df['low'].values
        c = df['close'].values
        ts = df['timestamp'].values if 'timestamp' in df.columns else list(range(n))

        swing_highs: List[SwingPoint] = []
        swing_lows: List[SwingPoint] = []

        # Candidate pivots from `left` up to `max_idx - right`
        for i in range(left, max_idx - right + 1):
            # 1. Swing High Check: Strictly higher than left and right bars
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
                
                # Check if broken by subsequent candle closes
                is_broken = False
                broken_ts = None
                for k in range(i + right + 1, max_idx + 1):
                    if k < n and c[k] > h[i]:
                        is_broken = True
                        broken_ts = ts[k]
                        break

                swing_highs.append(SwingPoint(
                    index=i,
                    timestamp=ts[i],
                    price=float(h[i]),
                    point_type="SWING_HIGH",
                    structure_type=st_type,
                    is_broken=is_broken,
                    broken_timestamp=broken_ts
                ))

            # 2. Swing Low Check: Strictly lower than left and right bars
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

                # Check if broken by subsequent candle closes
                is_broken = False
                broken_ts = None
                for k in range(i + right + 1, max_idx + 1):
                    if k < n and c[k] < l[i]:
                        is_broken = True
                        broken_ts = ts[k]
                        break

                swing_lows.append(SwingPoint(
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
    def analyze_timeframe_structure(
        cls,
        df: pd.DataFrame,
        timeframe: str = "15m",
        current_price: Optional[float] = None,
        lookback_bars: int = 50
    ) -> TimeframeStructure:
        """
        Analyzes candlestick structure trend (BULLISH, BEARISH, or CHOP) for a single timeframe
        and identifies active Order Blocks and live mitigation touch states.
        """
        if df is None or len(df) < 15:
            return TimeframeStructure(timeframe=timeframe, trend="CHOP")

        curr_p = current_price if (current_price is not None and current_price > 0) else float(df['close'].iloc[-1])
        swing_highs, swing_lows = cls.find_confirmed_swings(df, timeframe=timeframe)

        # Restrict to recent structural window
        eval_idx = len(df) - 1
        recent_sh = [s for s in swing_highs if (eval_idx - s.index) <= lookback_bars]
        recent_sl = [s for s in swing_lows if (eval_idx - s.index) <= lookback_bars]

        # Extract specific swing types
        recent_hh = next((s for s in reversed(recent_sh) if s.structure_type == "HH"), None)
        recent_lh = next((s for s in reversed(recent_sh) if s.structure_type == "LH"), None)
        recent_hl = next((s for s in reversed(recent_sl) if s.structure_type == "HL"), None)
        recent_ll = next((s for s in reversed(recent_sl) if s.structure_type == "LL"), None)

        hh_count = sum(1 for s in recent_sh if s.structure_type == "HH")
        hl_count = sum(1 for s in recent_sl if s.structure_type == "HL")
        lh_count = sum(1 for s in recent_sh if s.structure_type == "LH")
        ll_count = sum(1 for s in recent_sl if s.structure_type == "LL")

        # Break of Structure (BOS) and Change of Character (CHOCH) Detection:
        has_bos = False
        bos_type = "NONE"       # "BULLISH_BOS", "BEARISH_BOS", or "NONE"
        has_choch = False
        choch_type = "NONE"     # "BULLISH_CHOCH", "BEARISH_CHOCH", or "NONE"
        choch_price = None

        # 1. Break of Structure (BOS) - Trend Continuation
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

        # 2. Change of Character (CHOCH) - Structural Trend Invalidation / Reversal
        # Bearish CHOCH: Price closes decisively below the last confirmed Higher Low (HL) floor
        if recent_hl and curr_p < (recent_hl.price * 0.999):
            has_choch = True
            choch_type = "BEARISH_CHOCH"
            choch_price = recent_hl.price

        # Bullish CHOCH: Price closes decisively above the last confirmed Lower High (LH) ceiling
        if recent_lh and curr_p > (recent_lh.price * 1.001):
            has_choch = True
            choch_type = "BULLISH_CHOCH"
            choch_price = recent_lh.price

        # Determine pure candlestick structure trend with CHOCH structural invalidation
        # BULLISH: Dominance of HH and HL, with price holding above the last confirmed swing low and NO Bearish CHOCH
        # BEARISH: Dominance of LH and LL, with price holding below the last confirmed swing high and NO Bullish CHOCH
        trend = "CHOP"
        last_sl = recent_sl[-1] if recent_sl else None
        last_sh = recent_sh[-1] if recent_sh else None

        if (hh_count + hl_count) >= 2 and (lh_count + ll_count) == 0:
            if last_sl is None or curr_p >= (last_sl.price * 0.998):
                if choch_type != "BEARISH_CHOCH":
                    trend = "BULLISH"
                else:
                    trend = "CHOP"  # Invalidated by Bearish CHOCH
        elif (lh_count + ll_count) >= 2 and (hh_count + hl_count) == 0:
            if last_sh is None or curr_p <= (last_sh.price * 1.002):
                if choch_type != "BULLISH_CHOCH":
                    trend = "BEARISH"
                else:
                    trend = "CHOP"  # Invalidated by Bullish CHOCH
        else:
            # Ratio-based structural trend when minor opposing swings exist
            bull_points = hh_count + hl_count
            bear_points = lh_count + ll_count
            if bull_points >= 2 and bull_points > (bear_points * 1.5):
                if last_sl and curr_p >= last_sl.price and choch_type != "BEARISH_CHOCH":
                    trend = "BULLISH"
            elif bear_points >= 2 and bear_points > (bull_points * 1.5):
                if last_sh and curr_p <= last_sh.price and choch_type != "BULLISH_CHOCH":
                    trend = "BEARISH"

        # Continuous sustained momentum progression (e.g. uninterrupted parabolic candles where pullbacks have not yet formed)
        if trend == "CHOP":
            c_vals = df['close'].values
            n_bars = min(len(c_vals), lookback_bars)
            if n_bars >= 10:
                c_slice = c_vals[-n_bars:]
                up_moves = int(np.sum(c_slice[1:] > c_slice[:-1]))
                down_moves = int(np.sum(c_slice[1:] < c_slice[:-1]))
                tot_moves = max(1, up_moves + down_moves)
                net_ret = (c_slice[-1] - c_slice[0]) / max(1e-10, c_slice[0])

                if (up_moves / tot_moves) >= 0.65 and net_ret > 0.005:
                    trend = "BULLISH"
                    if recent_hl is None:
                        l_vals = df['low'].values[-n_bars:]
                        min_idx = len(df) - n_bars + int(np.argmin(l_vals))
                        ts_val = df['timestamp'].iloc[min_idx] if 'timestamp' in df.columns else min_idx
                        recent_hl = SwingPoint(
                            index=min_idx,
                            timestamp=ts_val,
                            price=float(np.min(l_vals)),
                            point_type="SWING_LOW",
                            structure_type="HL"
                        )
                elif (down_moves / tot_moves) >= 0.65 and net_ret < -0.005:
                    trend = "BEARISH"
                    if recent_lh is None:
                        h_vals = df['high'].values[-n_bars:]
                        max_idx = len(df) - n_bars + int(np.argmax(h_vals))
                        ts_val = df['timestamp'].iloc[max_idx] if 'timestamp' in df.columns else max_idx
                        recent_lh = SwingPoint(
                            index=max_idx,
                            timestamp=ts_val,
                            price=float(np.max(h_vals)),
                            point_type="SWING_HIGH",
                            structure_type="LH"
                        )

        # Detect Institutional Order Blocks using the authoritative engine
        active_obs = InstitutionalOrderBlockEngine.detect_order_blocks(
            df=df,
            timeframe=timeframe,
            current_price=curr_p,
            max_active_blocks=6
        )

        # Check if price is currently touching/mitigating an Order Block
        touched_bull = None
        touched_bear = None
        for ob in active_obs:
            if ob.is_touching or ob.state == OrderBlockState.TESTING:
                if ob.block_type == OrderBlockType.BULLISH and touched_bull is None:
                    touched_bull = ob
                elif ob.block_type == OrderBlockType.BEARISH and touched_bear is None:
                    touched_bear = ob

        # Compute structure score (0.0 to 10.0)
        score = 0.0
        if trend == "BULLISH":
            score += 4.0
            if hl_count >= 1: score += 2.0
            if hh_count >= 1: score += 2.0
            if has_bos: score += 1.0
            if touched_bull: score += 1.0
        elif trend == "BEARISH":
            score += 4.0
            if lh_count >= 1: score += 2.0
            if ll_count >= 1: score += 2.0
            if has_bos: score += 1.0
            if touched_bear: score += 1.0

        return TimeframeStructure(
            timeframe=timeframe,
            trend=trend,
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
    def evaluate_triad_alignment(
        cls,
        df_4h: Optional[pd.DataFrame],
        df_1h: Optional[pd.DataFrame],
        df_15m: Optional[pd.DataFrame],
        current_price: Optional[float] = None
    ) -> TriadStructureResult:
        """
        Evaluates pure candlestick market structure across the triad: 4H, 1H, and 15M.
        Enforces strict Timeframe Respect Hierarchy: Weight(4H) > Weight(1H) > Weight(15M).
        
        Rules:
        1. 4H Macro Trend sets the primary direction constraint.
        2. 1H Intermediate Context must confirm the 4H direction.
        3. 15M Tactical Trigger must confirm the 1H/4H direction.
        4. Unanimous Congruence Required:
           - LONG: 4H == BULLISH and 1H == BULLISH and 15M == BULLISH
           - SHORT: 4H == BEARISH and 1H == BEARISH and 15M == BEARISH
        5. Institutional Order Block Direction Setting:
           - Bullish OB mitigation confirms LONG direction.
           - Bearish OB mitigation confirms SHORT direction.
           - Opposing OB Veto: If seeking Long, price cannot be in an unmitigated Bearish OB.
             If seeking Short, price cannot be in an unmitigated Bullish OB.
        """
        reasons: List[str] = []

        if df_15m is None or len(df_15m) < 15:
            return TriadStructureResult(
                is_unanimously_aligned=False,
                trend_direction="NEUTRAL",
                veto_reason="Insufficient 15M candle history",
                reasons=["15M candle history < 15 bars"]
            )

        curr_p = current_price if (current_price is not None and current_price > 0) else float(df_15m['close'].iloc[-1])
        p_1h = float(df_1h['close'].iloc[-1]) if (df_1h is not None and len(df_1h) > 0) else curr_p
        p_4h = float(df_4h['close'].iloc[-1]) if (df_4h is not None and len(df_4h) > 0) else curr_p

        # Analyze each timeframe's structure with respect to its own close progression
        struct_15m = cls.analyze_timeframe_structure(df_15m, timeframe="15m", current_price=curr_p)
        struct_1h = cls.analyze_timeframe_structure(df_1h, timeframe="1h", current_price=p_1h) if (df_1h is not None and len(df_1h) >= 15) else None
        struct_4h = cls.analyze_timeframe_structure(df_4h, timeframe="4h", current_price=p_4h) if (df_4h is not None and len(df_4h) >= 15) else None

        t_15m = struct_15m.trend
        t_1h = struct_1h.trend if struct_1h else "CHOP"
        t_4h = struct_4h.trend if struct_4h else "CHOP"

        # Timeframe Respect Hierarchy Check:
        # If HTF is available, it carries primary authority.
        is_bullish_unanimous = (t_4h == "BULLISH" and t_1h == "BULLISH" and t_15m == "BULLISH")
        is_bearish_unanimous = (t_4h == "BEARISH" and t_1h == "BEARISH" and t_15m == "BEARISH")

        # Fallback if 4H or 1H is missing due to cold-start listing: require agreement on available frames
        if struct_4h is None and struct_1h is not None:
            is_bullish_unanimous = (t_1h == "BULLISH" and t_15m == "BULLISH")
            is_bearish_unanimous = (t_1h == "BEARISH" and t_15m == "BEARISH")
        elif struct_4h is None and struct_1h is None:
            # Single timeframe cold-start: requires strong 15M structure
            is_bullish_unanimous = (t_15m == "BULLISH" and struct_15m.recent_hl is not None)
            is_bearish_unanimous = (t_15m == "BEARISH" and struct_15m.recent_lh is not None)

        if not (is_bullish_unanimous or is_bearish_unanimous):
            veto = f"Timeframe divergence / chop: 4H={t_4h}, 1H={t_1h}, 15M={t_15m}"
            reasons.append(veto)
            return TriadStructureResult(
                is_unanimously_aligned=False,
                trend_direction="NEUTRAL",
                structure_4h=struct_4h,
                structure_1h=struct_1h,
                structure_15m=struct_15m,
                veto_reason=veto,
                reasons=reasons
            )

        preliminary_dir = "LONG" if is_bullish_unanimous else "SHORT"

        # ----------------------------------------------------------------------
        # HIGHER-TIMEFRAME CHOCH (CHANGE OF CHARACTER) STRUCTURAL GUARD
        # ----------------------------------------------------------------------
        # If 4H or 1H experienced an opposing CHOCH, it takes precedence and invalidates the setup
        has_htf_choch = False
        htf_choch_reason = ""

        if preliminary_dir == "LONG":
            if struct_4h and struct_4h.has_choch and struct_4h.choch_type == "BEARISH_CHOCH":
                has_htf_choch = True
                htf_choch_reason = f"4H Bearish Change of Character (CHOCH) broke Higher Low floor at ${struct_4h.choch_price}"
            elif struct_1h and struct_1h.has_choch and struct_1h.choch_type == "BEARISH_CHOCH":
                has_htf_choch = True
                htf_choch_reason = f"1H Bearish Change of Character (CHOCH) broke Higher Low floor at ${struct_1h.choch_price}"
        elif preliminary_dir == "SHORT":
            if struct_4h and struct_4h.has_choch and struct_4h.choch_type == "BULLISH_CHOCH":
                has_htf_choch = True
                htf_choch_reason = f"4H Bullish Change of Character (CHOCH) broke Lower High ceiling at ${struct_4h.choch_price}"
            elif struct_1h and struct_1h.has_choch and struct_1h.choch_type == "BULLISH_CHOCH":
                has_htf_choch = True
                htf_choch_reason = f"1H Bullish Change of Character (CHOCH) broke Lower High ceiling at ${struct_1h.choch_price}"

        if has_htf_choch:
            reasons.append(htf_choch_reason)
            return TriadStructureResult(
                is_unanimously_aligned=False,
                trend_direction="NEUTRAL",
                structure_4h=struct_4h,
                structure_1h=struct_1h,
                structure_15m=struct_15m,
                has_htf_choch=True,
                htf_choch_reason=htf_choch_reason,
                veto_reason=htf_choch_reason,
                reasons=reasons
            )

        # ----------------------------------------------------------------------
        # ORDER BLOCK DETECTION & OPPOSING POI GUARD (HTF RESPECT)
        # ----------------------------------------------------------------------
        # Extract active order blocks across all timeframes
        obs_15m = struct_15m.active_order_blocks
        obs_1h = struct_1h.active_order_blocks if struct_1h else []
        obs_4h = struct_4h.active_order_blocks if struct_4h else []

        active_ob_15m = struct_15m.touched_bullish_ob if preliminary_dir == "LONG" else struct_15m.touched_bearish_ob
        active_ob_1h = struct_1h.touched_bullish_ob if (struct_1h and preliminary_dir == "LONG") else (struct_1h.touched_bearish_ob if struct_1h else None)
        active_ob_4h = struct_4h.touched_bullish_ob if (struct_4h and preliminary_dir == "LONG") else (struct_4h.touched_bearish_ob if struct_4h else None)

        # Order Blocks in Higher Timeframes carry more respect:
        # Precedence: 4H OB (Weight 0.50) > 1H OB (Weight 0.30) > 15M OB (Weight 0.20)
        dominant_ob_tf = "15M"
        dominant_ob = None

        if preliminary_dir == "LONG":
            if active_ob_4h:
                dominant_ob_tf = "4H"
                dominant_ob = active_ob_4h
                reasons.append(f"4H Bullish Order Block mitigation at [${active_ob_4h.ob_low:.4f} - ${active_ob_4h.ob_high:.4f}] has macro primacy")
            elif active_ob_1h:
                dominant_ob_tf = "1H"
                dominant_ob = active_ob_1h
                reasons.append(f"1H Bullish Order Block mitigation at [${active_ob_1h.ob_low:.4f} - ${active_ob_1h.ob_high:.4f}] has intermediate primacy")
            elif active_ob_15m:
                dominant_ob_tf = "15M"
                dominant_ob = active_ob_15m
        else: # SHORT
            if active_ob_4h:
                dominant_ob_tf = "4H"
                dominant_ob = active_ob_4h
                reasons.append(f"4H Bearish Order Block mitigation at [${active_ob_4h.ob_low:.4f} - ${active_ob_4h.ob_high:.4f}] has macro primacy")
            elif active_ob_1h:
                dominant_ob_tf = "1H"
                dominant_ob = active_ob_1h
                reasons.append(f"1H Bearish Order Block mitigation at [${active_ob_1h.ob_low:.4f} - ${active_ob_1h.ob_high:.4f}] has intermediate primacy")
            elif active_ob_15m:
                dominant_ob_tf = "15M"
                dominant_ob = active_ob_15m

        has_order_block = (dominant_ob is not None)
        if has_order_block:
            ob_source = f"{dominant_ob_tf}_ORDER_BLOCK"
        else:
            ob_source = "TREND_ALIGNMENT_DEFAULT"
            reasons.append(f"No active order block touched; maintaining direction ({preliminary_dir}) as per 4H, 1H, and 15M unanimous trend alignment")

        # Opposing Order Block Check with Higher Timeframe Respect:
        # A Long setup must NOT be directly colliding into an unmitigated 1H/4H Bearish Supply Block
        # A Short setup must NOT be directly colliding into an unmitigated 1H/4H Bullish Demand Block
        opposing_ob_veto = False
        veto_reason = ""

        if preliminary_dir == "LONG":
            # Higher-timeframe opposing order blocks (4H and 1H) have absolute respect
            for ob in (obs_4h + obs_1h + obs_15m):
                if ob.block_type == OrderBlockType.BEARISH and ob.state in (OrderBlockState.FRESH, OrderBlockState.TESTING):
                    if curr_p >= (ob.ob_low - 0.001 * ob.ob_low) and curr_p <= (ob.ob_high + 0.001 * ob.ob_high):
                        opposing_ob_veto = True
                        veto_reason = f"Opposing Bearish Supply Block Collision on {ob.timeframe.upper()} [{ob.ob_low:.4f} - {ob.ob_high:.4f}]"
                        reasons.append(veto_reason)
                        break

        elif preliminary_dir == "SHORT":
            # Higher-timeframe opposing order blocks (4H and 1H) have absolute respect
            for ob in (obs_4h + obs_1h + obs_15m):
                if ob.block_type == OrderBlockType.BULLISH and ob.state in (OrderBlockState.FRESH, OrderBlockState.TESTING):
                    if curr_p >= (ob.ob_low - 0.001 * ob.ob_low) and curr_p <= (ob.ob_high + 0.001 * ob.ob_high):
                        opposing_ob_veto = True
                        veto_reason = f"Opposing Bullish Demand Block Collision on {ob.timeframe.upper()} [{ob.ob_low:.4f} - {ob.ob_high:.4f}]"
                        reasons.append(veto_reason)
                        break

        if opposing_ob_veto:
            return TriadStructureResult(
                is_unanimously_aligned=False,
                trend_direction="NEUTRAL",
                structure_4h=struct_4h,
                structure_1h=struct_1h,
                structure_15m=struct_15m,
                active_ob_15m=active_ob_15m,
                active_ob_1h=active_ob_1h,
                active_ob_4h=active_ob_4h,
                dominant_ob_timeframe=dominant_ob_tf,
                dominant_order_block=dominant_ob,
                has_order_block=has_order_block,
                order_block_source=ob_source,
                opposing_ob_veto=True,
                veto_reason=veto_reason,
                reasons=reasons
            )

        # ----------------------------------------------------------------------
        # TACTICAL 15M EXECUTION ANCHORING (HL FOR LONG, LH FOR SHORT)
        # ----------------------------------------------------------------------
        entry_anchor: Optional[SwingPoint] = None
        opposing_target: Optional[SwingPoint] = None

        if preliminary_dir == "LONG":
            # Long requires confirmed 15M Higher Low (HL)
            entry_anchor = struct_15m.recent_hl
            if entry_anchor is None and struct_15m.recent_swing_lows:
                # Fallback to most recent confirmed swing low
                entry_anchor = struct_15m.recent_swing_lows[-1]
            
            # Opposing target is recent swing high
            if struct_15m.recent_swing_highs:
                opposing_target = max(struct_15m.recent_swing_highs, key=lambda s: s.price)

            reasons.append(f"Unanimous Bullish Trend (4H={t_4h}, 1H={t_1h}, 15M={t_15m})")
            if struct_15m.recent_hl:
                reasons.append(f"15M Higher Low confirmed at ${struct_15m.recent_hl.price:.4f}")
            if active_ob_15m:
                reasons.append(f"15M Bullish Order Block mitigation at [${active_ob_15m.ob_low:.4f} - ${active_ob_15m.ob_high:.4f}]")

        elif preliminary_dir == "SHORT":
            # Short requires confirmed 15M Lower High (LH)
            entry_anchor = struct_15m.recent_lh
            if entry_anchor is None and struct_15m.recent_swing_highs:
                # Fallback to most recent confirmed swing high
                entry_anchor = struct_15m.recent_swing_highs[-1]

            # Opposing target is recent swing low
            if struct_15m.recent_swing_lows:
                opposing_target = min(struct_15m.recent_swing_lows, key=lambda s: s.price)

            reasons.append(f"Unanimous Bearish Trend (4H={t_4h}, 1H={t_1h}, 15M={t_15m})")
            if struct_15m.recent_lh:
                reasons.append(f"15M Lower High confirmed at ${struct_15m.recent_lh.price:.4f}")
            if active_ob_15m:
                reasons.append(f"15M Bearish Order Block mitigation at [${active_ob_15m.ob_low:.4f} - ${active_ob_15m.ob_high:.4f}]")

        return TriadStructureResult(
            is_unanimously_aligned=True,
            trend_direction=preliminary_dir,
            structure_4h=struct_4h,
            structure_1h=struct_1h,
            structure_15m=struct_15m,
            active_ob_15m=active_ob_15m,
            active_ob_1h=active_ob_1h,
            active_ob_4h=active_ob_4h,
            dominant_ob_timeframe=dominant_ob_tf,
            dominant_order_block=dominant_ob,
            has_order_block=has_order_block,
            order_block_source=ob_source,
            entry_anchor_pivot=entry_anchor,
            opposing_target_pivot=opposing_target,
            opposing_ob_veto=False,
            veto_reason="",
            reasons=reasons
        )
