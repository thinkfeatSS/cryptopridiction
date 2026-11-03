"""
QUANT EDGE V16: Institutional Order Block & Smart Money Concepts Engine
Specifications:
- Mathematical identification of Institutional Order Blocks (OBs) based on:
  1. Swing Pivot Highs/Lows (Zigzag Structure & Liquidity Sweeps)
  2. Market Structure Shift (MSS / BOS - Break of Structure)
  3. Directional Displacement (>1.25x ATR) & Volume Aggression
  4. Fair Value Gap (FVG) Imbalance Creation
  5. Strict State Machine: FRESH (Unmitigated) -> TESTING -> MITIGATED -> BREAKER -> INVALIDATED
  6. 5-Tier Institutional Ranking Hierarchy:
     - Rank 1: 🏆 Extreme Origin Structural POI (Prime SMC Zone - Swing Extreme + FVG + High Vol)
     - Rank 2: 🥈 Decisional Breakout Order Block (Last Base before BOS candle)
     - Rank 3: 💎 Multi-Horizon Nested Confluence POI (LTF Block inside HTF Macro POI)
     - Rank 4: ⚡ Institutional Breaker Block (Support-flipped-to-Resistance & Vice-Versa)
     - Rank 5: 🔹 High-Volume Continuation / Intra-Trend Mitigation Block
  7. Multi-Horizon Touch & Retest Detection across all 9 Charts (5M -> 1M)
  8. Mean Threshold (50% Equilibrium) Limit Fills & Asymmetric 1:2.5+ to 1:6.5 R:R Invalidations
"""

from enum import Enum
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

from app.quant_v16.entry_confirmation import format_dynamic_precision


class OrderBlockType(str, Enum):
    BULLISH = "BULLISH"   # Demand Block: Last down-close candle before upward MSS displacement
    BEARISH = "BEARISH"   # Supply Block: Last up-close candle before downward MSS displacement


class OrderBlockState(str, Enum):
    FRESH = "FRESH"             # Unmitigated: Price has not retested the block yet (Highest Edge)
    TESTING = "TESTING"         # Currently inside the retest entry window (Live Touch)
    MITIGATED = "MITIGATED"     # Already retested and liquidity absorbed (Degraded probability)
    BREAKER = "BREAKER"         # Violated block: Flipped from support to resistance (or vice-versa)
    INVALIDATED = "INVALIDATED" # Completely blown through, no institutional structure remains


class OrderBlockRank(int, Enum):
    RANK_1_EXTREME_ORIGIN = 1       # 🏆 Extreme Origin Structural POI & Nested SMC Macro POI
    RANK_2_DECISIONAL_BOS = 2       # 🥈 Decisional Breakout Order Block
    RANK_3_CONTINUATION_POI = 3     # 🥉 High-Volume Continuation / Intra-Swing POI
    RANK_4_BREAKER_FLIP = 4         # ⚡ Institutional Breaker Block (Polarity Flip)
    RANK_5_MINOR_MITIGATION = 5     # 🔹 Minor Mitigation / Depleted Zone


@dataclass
class OrderBlock:
    block_type: OrderBlockType
    state: OrderBlockState
    timeframe: str
    candle_idx: int
    timestamp: Any
    ob_high: float
    ob_low: float
    ob_open: float
    ob_close: float
    equilibrium_50: float
    displacement_mag: float       # Displacement range / ATR
    volume_surge: float           # Volume / Volume MA20
    has_fvg: bool
    fvg_low: float = 0.0
    fvg_high: float = 0.0
    mss_broken_level: float = 0.0 # Swing pivot broken
    confluence_score: float = 0.80
    retest_count: int = 0
    breaker_flipped: bool = False
    zeiierman_rank: int = 1
    zeiierman_rank_label: str = "🏆 ZEIIERMAN RANK 1 (PRIME SMC ZONE)"
    is_touching: bool = False
    touch_type: str = "NONE"      # "NONE", "PROXIMAL_TOUCH", "MEAN_THRESHOLD_50", "BREAKER_RETEST"
    is_extreme_origin: bool = False
    liquidity_swept: bool = False
    is_decisional: bool = False
    is_nested: bool = False
    htf_parent_tf: Optional[str] = None
    dist_to_price_pct: float = 0.0
    dist_to_price_atr: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "block_type": self.block_type.value,
            "state": self.state.value,
            "timeframe": self.timeframe,
            "candle_idx": self.candle_idx,
            "timestamp": str(self.timestamp),
            "ob_high": round(self.ob_high, 6),
            "ob_low": round(self.ob_low, 6),
            "ob_open": round(self.ob_open, 6),
            "ob_close": round(self.ob_close, 6),
            "equilibrium_50": round(self.equilibrium_50, 6),
            "displacement_mag": round(self.displacement_mag, 2),
            "volume_surge": round(self.volume_surge, 2),
            "has_fvg": self.has_fvg,
            "fvg_low": round(self.fvg_low, 6) if self.has_fvg else 0.0,
            "fvg_high": round(self.fvg_high, 6) if self.has_fvg else 0.0,
            "mss_broken_level": round(self.mss_broken_level, 6),
            "confluence_score": round(self.confluence_score, 2),
            "retest_count": self.retest_count,
            "breaker_flipped": self.breaker_flipped,
            "zeiierman_rank": self.zeiierman_rank,
            "zeiierman_rank_label": self.zeiierman_rank_label,
            "is_touching": self.is_touching,
            "touch_type": self.touch_type,
            "is_extreme_origin": self.is_extreme_origin,
            "liquidity_swept": self.liquidity_swept,
            "is_decisional": self.is_decisional,
            "is_nested": self.is_nested,
            "htf_parent_tf": self.htf_parent_tf,
            "dist_to_price_pct": round(self.dist_to_price_pct, 2),
            "dist_to_price_atr": round(self.dist_to_price_atr, 2),
        }


class InstitutionalOrderBlockEngine:
    """
    High-Performance Institutional Order Block & Smart Money Concepts Engine.
    Detects unmitigated institutional order blocks, breaker blocks, nested multi-horizon POIs,
    and precision discount/premium touches across multiple horizons.
    """

    @staticmethod
    def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        h, l, c = df['high'], df['low'], df['close']
        tr1 = h - l
        tr2 = (h - c.shift(1)).abs()
        tr3 = (l - c.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean().fillna(0.0)

    @classmethod
    def find_swing_pivots(cls, df: pd.DataFrame, lookback: int = 3) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
        """
        Identifies structural swing highs and swing lows (zigzag pivot vertices).
        Returns: (swing_highs, swing_lows) as [(index, price), ...]
        """
        n = len(df)
        if n < (lookback * 2 + 1):
            return [], []

        h = df['high'].values
        l = df['low'].values

        swing_highs = []
        swing_lows = []

        for i in range(lookback, n - lookback):
            # Swing High: Highest point within lookback window on left and right
            is_sh = True
            for j in range(1, lookback + 1):
                if h[i] <= h[i - j] or h[i] <= h[i + j]:
                    is_sh = False
                    break
            if is_sh:
                swing_highs.append((i, float(h[i])))

            # Swing Low: Lowest point within lookback window on left and right
            is_sl = True
            for j in range(1, lookback + 1):
                if l[i] >= l[i - j] or l[i] >= l[i + j]:
                    is_sl = False
                    break
            if is_sl:
                swing_lows.append((i, float(l[i])))

        return swing_highs, swing_lows

    @classmethod
    def detect_order_blocks(
        cls,
        df: pd.DataFrame,
        timeframe: str = "1h",
        min_displacement_mult: float = 1.25,
        max_active_blocks: int = 8,
        current_price: Optional[float] = None
    ) -> List[OrderBlock]:
        """
        Scans OHLCV history to mathematically construct Institutional Order Blocks.
        Tracks live mitigation status, touch events, and ranks across all subsequent candles.
        """
        n = len(df)
        if n < 25:
            return []

        c = df['close'].values
        o = df['open'].values
        h = df['high'].values
        l = df['low'].values
        v = df['volume'].values if 'volume' in df.columns else np.ones(n)
        ts = df['timestamp'].values if 'timestamp' in df.columns else list(range(n))

        atr = cls.compute_atr(df, period=14).values
        vol_ma20 = pd.Series(v).rolling(20, min_periods=3).mean().values

        # 1. Identify Structural Pivots
        swing_highs, swing_lows = cls.find_swing_pivots(df, lookback=3)
        sh_indices = [item[0] for item in swing_highs]
        sh_prices = [item[1] for item in swing_highs]
        sl_indices = [item[0] for item in swing_lows]
        sl_prices = [item[1] for item in swing_lows]

        order_blocks: List[OrderBlock] = []

        # Scan for Market Structure Shifts and Displacement Impulses
        for i in range(10, n - 1):
            curr_atr = max(1e-8, atr[i])
            bar_rng = h[i] - l[i]
            body_rng = abs(c[i] - o[i])
            v_ratio = v[i] / (vol_ma20[i] + 1e-10)

            # ------------------------------------------------------------------
            # A. BULLISH MARKET STRUCTURE SHIFT & BULLISH ORDER BLOCK (DEMAND)
            # ------------------------------------------------------------------
            if c[i] > o[i] and bar_rng >= (min_displacement_mult * curr_atr) and (body_rng / bar_rng) >= 0.50:
                # Check if this candle broke any prior swing high (MSS / BOS)
                prior_sh = [p for idx, p in zip(sh_indices, sh_prices) if idx < i and (i - idx) <= 45]
                prior_sl = [p for idx, p in zip(sl_indices, sl_prices) if idx < i and (i - idx) <= 45]

                if prior_sh and c[i] > max(prior_sh):
                    broken_level = max(prior_sh)

                    # Trace back to find the origin down-close (red) candle before the move
                    ob_idx = i - 1
                    while ob_idx >= max(0, i - 6):
                        if c[ob_idx] <= o[ob_idx]:  # Found origin down candle
                            break
                        ob_idx -= 1

                    if ob_idx >= 0:
                        # Deduplicate: if an order block already exists with the same ob_idx or identical zone, do not append a clone
                        existing = [b for b in order_blocks if b.block_type == OrderBlockType.BULLISH and (b.candle_idx == ob_idx or abs(b.ob_high - float(h[ob_idx])) <= 1e-6)]
                        if existing:
                            existing[0].displacement_mag = max(existing[0].displacement_mag, round(bar_rng / curr_atr, 2))
                            existing[0].volume_surge = max(existing[0].volume_surge, round(v_ratio, 2))
                            continue

                        ob_h = float(h[ob_idx])
                        ob_l = float(l[ob_idx])
                        ob_o = float(o[ob_idx])
                        ob_c = float(c[ob_idx])
                        eq_50 = (ob_h + ob_l) / 2.0

                        # Check for Fair Value Gap: low of candle i+1 > high of candle i-1 or OB candle
                        has_fvg = False
                        fvg_l, fvg_h = 0.0, 0.0
                        bound_h = float(max(ob_h, h[i - 1]))
                        if i + 1 < n and l[i + 1] > bound_h:
                            has_fvg = True
                            fvg_l, fvg_h = bound_h, float(l[i + 1])
                        elif i + 1 < n and l[i + 1] > ob_h:
                            has_fvg = True
                            fvg_l, fvg_h = ob_h, float(l[i + 1])

                        # Liquidity sweep check: did the OB candle or prior 2 bars sweep a prior swing low?
                        liquidity_swept = False
                        if prior_sl and ob_l <= min(prior_sl):
                            liquidity_swept = True

                        # Extreme Origin vs Decisional identification
                        is_extreme_origin = False
                        is_decisional = False
                        if sl_indices:
                            closest_sl = min(sl_indices, key=lambda idx: abs(idx - ob_idx))
                            if abs(closest_sl - ob_idx) <= 2:
                                is_extreme_origin = True
                        if ob_idx == i - 1:
                            is_decisional = True

                        # Confluence score
                        conf = 0.65
                        if has_fvg: conf += 0.12
                        if v_ratio >= 1.30: conf += 0.12
                        if bar_rng >= 1.7 * curr_atr: conf += 0.08
                        if liquidity_swept: conf += 0.08

                        ob = OrderBlock(
                            block_type=OrderBlockType.BULLISH,
                            state=OrderBlockState.FRESH,
                            timeframe=timeframe,
                            candle_idx=ob_idx,
                            timestamp=ts[ob_idx],
                            ob_high=ob_h,
                            ob_low=ob_l,
                            ob_open=ob_o,
                            ob_close=ob_c,
                            equilibrium_50=eq_50,
                            displacement_mag=round(bar_rng / curr_atr, 2),
                            volume_surge=round(v_ratio, 2),
                            has_fvg=has_fvg,
                            fvg_low=fvg_l,
                            fvg_high=fvg_h,
                            mss_broken_level=broken_level,
                            confluence_score=min(0.98, conf),
                            liquidity_swept=liquidity_swept,
                            is_extreme_origin=is_extreme_origin,
                            is_decisional=is_decisional
                        )
                        order_blocks.append(ob)

            # ------------------------------------------------------------------
            # B. BEARISH MARKET STRUCTURE SHIFT & BEARISH ORDER BLOCK (SUPPLY)
            # ------------------------------------------------------------------
            elif c[i] < o[i] and bar_rng >= (min_displacement_mult * curr_atr) and (body_rng / bar_rng) >= 0.50:
                prior_sl = [p for idx, p in zip(sl_indices, sl_prices) if idx < i and (i - idx) <= 45]
                prior_sh = [p for idx, p in zip(sh_indices, sh_prices) if idx < i and (i - idx) <= 45]

                if prior_sl and c[i] < min(prior_sl):
                    broken_level = min(prior_sl)

                    # Trace back to find the origin up-close (green) candle before the breakdown
                    ob_idx = i - 1
                    while ob_idx >= max(0, i - 6):
                        if c[ob_idx] >= o[ob_idx]:  # Found origin up candle
                            break
                        ob_idx -= 1

                    if ob_idx >= 0:
                        # Deduplicate: if an order block already exists with the same ob_idx or identical zone, do not append a clone
                        existing = [b for b in order_blocks if b.block_type == OrderBlockType.BEARISH and (b.candle_idx == ob_idx or abs(b.ob_low - float(l[ob_idx])) <= 1e-6)]
                        if existing:
                            existing[0].displacement_mag = max(existing[0].displacement_mag, round(bar_rng / curr_atr, 2))
                            existing[0].volume_surge = max(existing[0].volume_surge, round(v_ratio, 2))
                            continue

                        ob_h = float(h[ob_idx])
                        ob_l = float(l[ob_idx])
                        ob_o = float(o[ob_idx])
                        ob_c = float(c[ob_idx])
                        eq_50 = (ob_h + ob_l) / 2.0

                        # Check for Fair Value Gap: high of candle i+1 < low of candle i-1 or OB candle
                        has_fvg = False
                        fvg_l, fvg_h = 0.0, 0.0
                        bound_l = float(min(ob_l, l[i - 1]))
                        if i + 1 < n and h[i + 1] < bound_l:
                            has_fvg = True
                            fvg_l, fvg_h = float(h[i + 1]), bound_l
                        elif i + 1 < n and h[i + 1] < ob_l:
                            has_fvg = True
                            fvg_l, fvg_h = float(h[i + 1]), ob_l

                        # Liquidity sweep check: did the OB candle or prior 2 bars sweep a prior swing high?
                        liquidity_swept = False
                        if prior_sh and ob_h >= max(prior_sh):
                            liquidity_swept = True

                        is_extreme_origin = False
                        is_decisional = False
                        if sh_indices:
                            closest_sh = min(sh_indices, key=lambda idx: abs(idx - ob_idx))
                            if abs(closest_sh - ob_idx) <= 2:
                                is_extreme_origin = True
                        if ob_idx == i - 1:
                            is_decisional = True

                        conf = 0.65
                        if has_fvg: conf += 0.12
                        if v_ratio >= 1.30: conf += 0.12
                        if bar_rng >= 1.7 * curr_atr: conf += 0.08
                        if liquidity_swept: conf += 0.08

                        ob = OrderBlock(
                            block_type=OrderBlockType.BEARISH,
                            state=OrderBlockState.FRESH,
                            timeframe=timeframe,
                            candle_idx=ob_idx,
                            timestamp=ts[ob_idx],
                            ob_high=ob_h,
                            ob_low=ob_l,
                            ob_open=ob_o,
                            ob_close=ob_c,
                            equilibrium_50=eq_50,
                            displacement_mag=round(bar_rng / curr_atr, 2),
                            volume_surge=round(v_ratio, 2),
                            has_fvg=has_fvg,
                            fvg_low=fvg_l,
                            fvg_high=fvg_h,
                            mss_broken_level=broken_level,
                            confluence_score=min(0.98, conf),
                            liquidity_swept=liquidity_swept,
                            is_extreme_origin=is_extreme_origin,
                            is_decisional=is_decisional
                        )
                        order_blocks.append(ob)

        # ----------------------------------------------------------------------
        # 2. EVALUATE MITIGATION & STATE MACHINE UP TO LATEST CANDLE
        # ----------------------------------------------------------------------
        curr_price = current_price or float(c[-1])
        curr_low = float(l[-1])
        curr_high = float(h[-1])
        curr_atr = max(1e-8, float(atr[-1]))

        active_blocks: List[OrderBlock] = []

        for ob in order_blocks:
            tested = False
            broken = False
            in_zone = False

            for k in range(ob.candle_idx + 2, n):
                bar_h = float(h[k])
                bar_l = float(l[k])
                bar_c = float(c[k])

                if ob.block_type == OrderBlockType.BULLISH:
                    touching = (bar_l <= ob.ob_high and bar_h >= ob.ob_low)
                    if touching:
                        if not in_zone:
                            ob.retest_count += 1
                            tested = True
                            in_zone = True
                    else:
                        in_zone = False
                    # Decisive close below OB low -> Flips to Breaker Block
                    if bar_c < (ob.ob_low - 0.002 * ob.ob_low):
                        broken = True
                        ob.state = OrderBlockState.BREAKER
                        ob.breaker_flipped = True
                        break

                elif ob.block_type == OrderBlockType.BEARISH:
                    touching = (bar_h >= ob.ob_low and bar_l <= ob.ob_high)
                    if touching:
                        if not in_zone:
                            ob.retest_count += 1
                            tested = True
                            in_zone = True
                    else:
                        in_zone = False
                    # Decisive close above OB high -> Flips to Breaker Block
                    if bar_c > (ob.ob_high + 0.002 * ob.ob_high):
                        broken = True
                        ob.state = OrderBlockState.BREAKER
                        ob.breaker_flipped = True
                        break

            # Distance calculation to live market price
            if ob.block_type == OrderBlockType.BULLISH:
                if curr_price > ob.ob_high:
                    ob.dist_to_price_pct = ((curr_price - ob.ob_high) / curr_price) * 100.0
                    ob.dist_to_price_atr = (curr_price - ob.ob_high) / curr_atr
                elif curr_price < ob.ob_low:
                    ob.dist_to_price_pct = ((ob.ob_low - curr_price) / curr_price) * 100.0
                    ob.dist_to_price_atr = (ob.ob_low - curr_price) / curr_atr
                else:
                    ob.dist_to_price_pct = 0.0
                    ob.dist_to_price_atr = 0.0
            else:
                if curr_price < ob.ob_low:
                    ob.dist_to_price_pct = ((ob.ob_low - curr_price) / curr_price) * 100.0
                    ob.dist_to_price_atr = (ob.ob_low - curr_price) / curr_atr
                elif curr_price > ob.ob_high:
                    ob.dist_to_price_pct = ((curr_price - ob.ob_high) / curr_price) * 100.0
                    ob.dist_to_price_atr = (curr_price - ob.ob_high) / curr_atr
                else:
                    ob.dist_to_price_pct = 0.0
                    ob.dist_to_price_atr = 0.0

            if broken:
                # Retesting the flipped breaker zone
                if ob.block_type == OrderBlockType.BULLISH: # Bearish Breaker (Resistance)
                    is_touch = (curr_high >= ob.ob_low and curr_low <= (ob.ob_high + 0.05 * curr_atr))
                    if is_touch:
                        ob.is_touching = True
                        ob.touch_type = "BREAKER_RETEST"
                        ob.state = OrderBlockState.BREAKER
                        active_blocks.append(ob)
                    elif ob.dist_to_price_pct <= 2.0:
                        ob.is_touching = False
                        ob.touch_type = "NONE"
                        ob.state = OrderBlockState.BREAKER
                        active_blocks.append(ob)
                elif ob.block_type == OrderBlockType.BEARISH: # Bullish Breaker (Support)
                    is_touch = (curr_low <= ob.ob_high and curr_high >= (ob.ob_low - 0.05 * curr_atr))
                    if is_touch:
                        ob.is_touching = True
                        ob.touch_type = "BREAKER_RETEST"
                        ob.state = OrderBlockState.BREAKER
                        active_blocks.append(ob)
                    elif ob.dist_to_price_pct <= 2.0:
                        ob.is_touching = False
                        ob.touch_type = "NONE"
                        ob.state = OrderBlockState.BREAKER
                        active_blocks.append(ob)
                continue

            # Check live bar physical touch & mitigation state
            if ob.block_type == OrderBlockType.BULLISH:
                # Real physical touch: the current bar low dips into [ob_low, ob_high] without catastrophic breach
                in_demand_zone = (curr_low <= ob.ob_high and curr_high >= ob.ob_low)
                has_not_broken_sl = curr_price >= (ob.ob_low - 0.002 * ob.ob_low)

                if in_demand_zone and has_not_broken_sl:
                    ob.state = OrderBlockState.TESTING
                    ob.is_touching = True
                    # 50% Mean Threshold test
                    if curr_low <= ob.equilibrium_50:
                        ob.touch_type = "MEAN_THRESHOLD_50"
                    else:
                        ob.touch_type = "PROXIMAL_TOUCH"
                elif tested and ob.retest_count >= 2:
                    ob.state = OrderBlockState.MITIGATED
                    ob.is_touching = False
                    ob.touch_type = "NONE"
                else:
                    ob.state = OrderBlockState.FRESH
                    ob.is_touching = False
                    ob.touch_type = "NONE"

            elif ob.block_type == OrderBlockType.BEARISH:
                # Real physical touch: the current bar high reaches into [ob_low, ob_high] without catastrophic breach
                in_supply_zone = (curr_high >= ob.ob_low and curr_low <= ob.ob_high)
                has_not_broken_sl = curr_price <= (ob.ob_high + 0.002 * ob.ob_high)

                if in_supply_zone and has_not_broken_sl:
                    ob.state = OrderBlockState.TESTING
                    ob.is_touching = True
                    # 50% Mean Threshold test
                    if curr_high >= ob.equilibrium_50:
                        ob.touch_type = "MEAN_THRESHOLD_50"
                    else:
                        ob.touch_type = "PROXIMAL_TOUCH"
                elif tested and ob.retest_count >= 2:
                    ob.state = OrderBlockState.MITIGATED
                    ob.is_touching = False
                    ob.touch_type = "NONE"
                else:
                    ob.state = OrderBlockState.FRESH
                    ob.is_touching = False
                    ob.touch_type = "NONE"

            active_blocks.append(ob)

        # ----------------------------------------------------------------------
        # 3. ASSIGN 5-TIER INSTITUTIONAL ORDER BLOCK RANKS (RANK 1 TO RANK 5)
        # ----------------------------------------------------------------------
        for ob in active_blocks:
            # Rank 4: Breaker Block (Support flipped to Resistance or vice versa)
            if ob.state == OrderBlockState.BREAKER or ob.breaker_flipped:
                ob.zeiierman_rank = OrderBlockRank.RANK_4_BREAKER_FLIP.value
                ob.zeiierman_rank_label = "⚡ ZEIIERMAN RANK 4 (INSTITUTIONAL BREAKER BLOCK)"

            # Rank 1: Nested Multi-Horizon Confluence (HTF + LTF dual institutional confluence)
            elif ob.is_nested:
                ob.zeiierman_rank = OrderBlockRank.RANK_1_EXTREME_ORIGIN.value
                parent = ob.htf_parent_tf.upper() if ob.htf_parent_tf else "HTF"
                ob.zeiierman_rank_label = f"💎 ZEIIERMAN RANK 1 NESTED SMC [{parent} POI + {ob.timeframe.upper()} TRIGGER]"

            # Fresh / Testing Order Blocks
            elif ob.state in (OrderBlockState.FRESH, OrderBlockState.TESTING) and ob.retest_count <= 1:
                # Rank 1: Extreme Origin POI / Liquidity Swept Prime SMC Zone
                if (ob.is_extreme_origin or ob.liquidity_swept) and ob.displacement_mag >= 1.40:
                    ob.zeiierman_rank = OrderBlockRank.RANK_1_EXTREME_ORIGIN.value
                    ob.zeiierman_rank_label = "🏆 ZEIIERMAN RANK 1 (EXTREME ORIGIN SMC POI)"
                elif ob.displacement_mag >= 1.65 and ob.volume_surge >= 1.25 and ob.has_fvg:
                    ob.zeiierman_rank = OrderBlockRank.RANK_1_EXTREME_ORIGIN.value
                    ob.zeiierman_rank_label = "🏆 ZEIIERMAN RANK 1 (PRIME SMC ZONE)"

                # Rank 2: Decisional BOS Breakout Block
                elif ob.displacement_mag >= 1.25 and (ob.volume_surge >= 1.10 or ob.has_fvg or ob.is_decisional):
                    ob.zeiierman_rank = OrderBlockRank.RANK_2_DECISIONAL_BOS.value
                    ob.zeiierman_rank_label = "🥈 ZEIIERMAN RANK 2 (DECISIONAL BOS BREAKOUT)"

                # Rank 3: Continuation / Intra-Swing POI
                else:
                    ob.zeiierman_rank = OrderBlockRank.RANK_3_CONTINUATION_POI.value
                    ob.zeiierman_rank_label = "🥉 ZEIIERMAN RANK 3 (CONTINUATION SMC POI)"

            # Moderate retests (Retest == 2)
            elif ob.retest_count <= 2:
                ob.zeiierman_rank = OrderBlockRank.RANK_3_CONTINUATION_POI.value
                ob.zeiierman_rank_label = "🥉 ZEIIERMAN RANK 3 (CONTINUATION SMC POI)"

            # Depleted
            else:
                ob.zeiierman_rank = OrderBlockRank.RANK_5_MINOR_MITIGATION.value
                ob.zeiierman_rank_label = "⚪ ZEIIERMAN RANK 5 (DEPLETED / MULTI-MITIGATED)"

        return active_blocks[-max_active_blocks:]

    @classmethod
    def evaluate_live_setup(
        cls,
        df: pd.DataFrame,
        timeframe: str = "1h",
        current_price: Optional[float] = None,
        market_regime: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Synthesizes active order blocks with live candle price to evaluate precision trade setups.
        Evaluates Ranks 1 to 5 with tight invalidation and asymmetric targets dynamically scaled for market regimes.
        """
        n = len(df)
        if n < 25:
            return {"setup_detected": False, "reason": "Insufficient history"}

        # Dynamic target multipliers: in range/consolidation, scale targets so TP1 is quickly reachable
        is_range_regime = bool(market_regime and any(k in str(market_regime).upper() for k in ["RANGE", "CONSOLIDATION", "CHOP", "SIDEWAYS"]))
        ob_tp1_mult = 1.65 if is_range_regime else 2.80
        ob_tp2_mult = 2.80 if is_range_regime else 4.50
        ob_tp3_mult = 4.50 if is_range_regime else 7.00

        bb_tp1_mult = 1.60 if is_range_regime else 2.20
        bb_tp2_mult = 2.60 if is_range_regime else 3.50
        bb_tp3_mult = 4.00 if is_range_regime else 5.50

        live_p = current_price or float(df['close'].iloc[-1])
        live_low = float(df['low'].iloc[-1])
        live_high = float(df['high'].iloc[-1])
        atr = float(cls.compute_atr(df, period=14).iloc[-1])

        blocks = cls.detect_order_blocks(df, timeframe=timeframe, current_price=live_p)
        if not blocks:
            return {"setup_detected": False, "reason": "No active order blocks in range"}

        # Candidate blocks: Touching blocks take immediate priority
        touching_blocks = [b for b in blocks if (b.is_touching or b.state == OrderBlockState.TESTING) and b.zeiierman_rank <= 4]
        breaker_blocks = [b for b in blocks if b.state == OrderBlockState.BREAKER and b.is_touching]

        # ----------------------------------------------------------------------
        # 1. BULLISH ORDER BLOCK RETEST (PRECISION DISCOUNT ENTRY - RANKS 1 TO 4)
        # ----------------------------------------------------------------------
        bull_test = [b for b in touching_blocks if b.block_type == OrderBlockType.BULLISH]
        if bull_test:
            # Sort by Rank (1 best), then confluence score, then proximity
            best_ob = min(bull_test, key=lambda b: (
                b.zeiierman_rank,
                -b.confluence_score,
                abs(live_p - b.ob_high)
            ))

            sweep_low = min(live_low, float(df['low'].iloc[-2])) if len(df) >= 2 else live_low
            is_valid_sweep_long = bool(best_ob.retest_count >= 3 and sweep_low < best_ob.ob_low and sweep_low >= (best_ob.ob_low - 1.20 * atr) and live_p >= best_ob.ob_low)
            in_bull_zone = bool((live_low <= best_ob.ob_high and live_high >= best_ob.ob_low) or (is_valid_sweep_long and live_p <= (best_ob.ob_high + 0.50 * atr)))
            has_not_broken_sl = bool(live_low >= (best_ob.ob_low - 0.05 * atr) or is_valid_sweep_long)

            if in_bull_zone and has_not_broken_sl:
                # SMC-01: Order Block Mitigation Degradation & Turtle Soup Liquidity Reclaims
                # Blocks with >= 3 retests are depleted of standard resting limit liquidity.
                # However, if price sweeps past the zone boundary and reclaims inside with aggression,
                # convert into an asymmetric Turtle Soup Liquidity Reclaim setup!
                if best_ob.retest_count >= 3:
                    vol_series = df['volume'] if 'volume' in df.columns else None
                    vol_sma20 = float(vol_series.rolling(20).mean().iloc[-1]) if vol_series is not None and len(vol_series) >= 20 else 1.0
                    current_vol = float(vol_series.iloc[-1]) if vol_series is not None else 1.0
                    vol_ratio = current_vol / max(1e-8, vol_sma20)
                    is_wick_rejection = (live_high > live_low) and ((min(live_p, float(df['open'].iloc[-1])) - live_low) / max(1e-8, live_high - live_low) >= 0.25)

                    if is_valid_sweep_long and (vol_ratio >= 1.25 or is_wick_rejection):
                        entry_p = live_p
                        sl_p = format_dynamic_precision(sweep_low - (0.05 * atr))
                        risk_amt = max(1e-6, entry_p - sl_p)
                        tp1_p = format_dynamic_precision(entry_p + (ob_tp1_mult * risk_amt))
                        tp2_p = format_dynamic_precision(entry_p + (ob_tp2_mult * risk_amt))
                        tp3_p = format_dynamic_precision(entry_p + (ob_tp3_mult * risk_amt))
                        rr_ratio = round((tp1_p - entry_p) / risk_amt, 2)
                        return {
                            "setup_detected": True,
                            "direction": "LONG",
                            "strategy": "TURTLE_SOUP_LIQUIDITY_RECLAIM",
                            "decision": f"🐢 [{best_ob.zeiierman_rank_label}] TURTLE SOUP RECLAIM (LONG)",
                            "block_type": "BULLISH_DEMAND_BLOCK",
                            "state": best_ob.state.value,
                            "zeiierman_rank": best_ob.zeiierman_rank,
                            "zeiierman_rank_label": best_ob.zeiierman_rank_label,
                            "entry_price": entry_p,
                            "optimal_entry_limit": best_ob.ob_low,
                            "mean_threshold_price": best_ob.equilibrium_50,
                            "order_block_zone": [round(best_ob.ob_low, 6), round(best_ob.ob_high, 6)],
                            "fvg_zone": [round(best_ob.fvg_low, 6), round(best_ob.fvg_high, 6)] if best_ob.has_fvg else None,
                            "sl_price": sl_p,
                            "tp1_price": tp1_p,
                            "tp2_price": tp2_p,
                            "tp3_price": tp3_p,
                            "risk_reward_ratio": rr_ratio,
                            "conviction": 84.0 + min(12.0, max(0.0, (vol_ratio - 1.0) * 10.0)),
                            "meta_win_prob": 0.68,
                            "retest_count": best_ob.retest_count,
                            "mitigation_factor": 0.60,
                            "active_block": best_ob.to_dict(),
                            "in_order_block_zone": True,
                            "is_touching": best_ob.is_touching,
                            "touch_type": best_ob.touch_type,
                            "mitigated": True,
                            "is_testing": True,
                            "is_nested_smc": best_ob.is_nested,
                            "htf_poi_tf": best_ob.htf_parent_tf,
                            "is_turtle_soup": True,
                            "reasons": [
                                f"Turtle Soup Liquidity Sweep Reclaim on {timeframe.upper()} {best_ob.zeiierman_rank_label}",
                                f"Price swept stops below {best_ob.ob_low:.4f} down to {sweep_low:.4f} and reclaimed inside zone with aggression",
                            ],
                        }

                    return {
                        "setup_detected": False,
                        "reason": f"Order block depleted after {best_ob.retest_count} touches",
                        "retest_count": best_ob.retest_count,
                        "mitigation_factor": 0.40,
                        "order_block_zone": [round(best_ob.ob_low, 6), round(best_ob.ob_high, 6)],
                    }

                entry_p = live_p
                min_sl_dist = max(0.85 * atr, min(entry_p * 0.008, 1.8 * atr))
                sl_p = min(best_ob.ob_low - (0.20 * atr), entry_p - min_sl_dist)
                # Enforce strict price invariant: entry must be comfortably above stop loss
                if entry_p > (sl_p + 0.05 * atr):
                    risk_amt = max(1e-6, entry_p - sl_p)
                    tp1_p = format_dynamic_precision(entry_p + (ob_tp1_mult * risk_amt))
                    tp2_p = format_dynamic_precision(entry_p + (ob_tp2_mult * risk_amt))
                    tp3_p = format_dynamic_precision(entry_p + (ob_tp3_mult * risk_amt))
                    entry_p = format_dynamic_precision(entry_p)
                    sl_p = format_dynamic_precision(sl_p)

                    rr_ratio = round((tp1_p - entry_p) / risk_amt, 2)
                    rank_boosts = {1: 8.0, 2: 5.0, 3: 7.0, 4: 3.0, 5: 0.0}
                    base_conv = 80.0 if best_ob.zeiierman_rank <= 2 else 74.0
                    raw_conviction = min(98.5, base_conv + (best_ob.confluence_score * 12.0) + rank_boosts.get(best_ob.zeiierman_rank, 0.0))

                    # Mitigation degradation: 15% discount per prior touch
                    mitigation_factor = max(0.50, 1.0 - (0.15 * float(best_ob.retest_count)))
                    conviction = max(60.0, raw_conviction - (float(best_ob.retest_count) * 6.0))
                    raw_prob = 0.72 + (best_ob.confluence_score * 0.18)
                    meta_win_prob = round(max(0.48, min(0.95, raw_prob - (float(best_ob.retest_count) * 0.04))), 2)

                return {
                    "setup_detected": True,
                    "direction": "LONG",
                    "strategy": "ORDER_BLOCK_LONG",
                    "decision": f"🎯 [{best_ob.zeiierman_rank_label}] RETEST (LONG)",
                    "block_type": "BULLISH_DEMAND_BLOCK",
                    "state": best_ob.state.value,
                    "zeiierman_rank": best_ob.zeiierman_rank,
                    "zeiierman_rank_label": best_ob.zeiierman_rank_label,
                    "entry_price": entry_p,
                    "optimal_entry_limit": best_ob.equilibrium_50,
                    "mean_threshold_price": best_ob.equilibrium_50,
                    "order_block_zone": [round(best_ob.ob_low, 6), round(best_ob.ob_high, 6)],
                    "fvg_zone": [round(best_ob.fvg_low, 6), round(best_ob.fvg_high, 6)] if best_ob.has_fvg else None,
                    "sl_price": sl_p,
                    "tp1_price": tp1_p,
                    "tp2_price": tp2_p,
                    "tp3_price": tp3_p,
                    "risk_reward_ratio": rr_ratio,
                    "conviction": conviction,
                    "meta_win_prob": meta_win_prob,
                    "retest_count": best_ob.retest_count,
                    "mitigation_factor": round(mitigation_factor, 2),
                    "active_block": best_ob.to_dict(),
                    "in_order_block_zone": True,
                    "is_touching": best_ob.is_touching,
                    "touch_type": best_ob.touch_type,
                    "mitigated": (best_ob.retest_count > 0),
                    "is_testing": True,
                    "is_nested_smc": best_ob.is_nested,
                    "htf_poi_tf": best_ob.htf_parent_tf,
                    "reasons": [
                        f"Retest of verified {timeframe.upper()} {best_ob.zeiierman_rank_label} [{best_ob.ob_low:.4f} - {best_ob.ob_high:.4f}]",
                        f"Preceded by {best_ob.displacement_mag:.1f}x ATR displacement breaking swing structure at {best_ob.mss_broken_level:.4f}",
                        f"Tight structural invalidation below Order Block Low ({sl_p:.4f})"
                    ]
                }

        # ----------------------------------------------------------------------
        # 2. BEARISH ORDER BLOCK RETEST (PRECISION PREMIUM ENTRY - RANKS 1 TO 4)
        # ----------------------------------------------------------------------
        bear_test = [b for b in touching_blocks if b.block_type == OrderBlockType.BEARISH]
        if bear_test:
            best_ob = min(bear_test, key=lambda b: (
                b.zeiierman_rank,
                -b.confluence_score,
                abs(live_p - b.ob_low)
            ))

            sweep_high = max(live_high, float(df['high'].iloc[-2])) if len(df) >= 2 else live_high
            is_valid_sweep_short = bool(best_ob.retest_count >= 3 and sweep_high > best_ob.ob_high and sweep_high <= (best_ob.ob_high + 1.20 * atr) and live_p <= best_ob.ob_high)
            in_bear_zone = bool((live_high >= best_ob.ob_low and live_low <= best_ob.ob_high) or (is_valid_sweep_short and live_p >= (best_ob.ob_low - 0.50 * atr)))
            has_not_broken_sl = bool(live_high <= (best_ob.ob_high + 0.05 * atr) or is_valid_sweep_short)

            if in_bear_zone and has_not_broken_sl:
                # SMC-01: Order Block Mitigation Degradation & Turtle Soup Liquidity Reclaims
                # Blocks with >= 3 retests are depleted of standard resting limit liquidity.
                # However, if price sweeps past the supply boundary and reclaims inside with aggression,
                # convert into an asymmetric Turtle Soup Liquidity Reclaim setup!
                if best_ob.retest_count >= 3:
                    vol_series = df['volume'] if 'volume' in df.columns else None
                    vol_sma20 = float(vol_series.rolling(20).mean().iloc[-1]) if vol_series is not None and len(vol_series) >= 20 else 1.0
                    current_vol = float(vol_series.iloc[-1]) if vol_series is not None else 1.0
                    vol_ratio = current_vol / max(1e-8, vol_sma20)
                    is_wick_rejection = (live_high > live_low) and ((live_high - max(live_p, float(df['open'].iloc[-1]))) / max(1e-8, live_high - live_low) >= 0.25)

                    if is_valid_sweep_short and (vol_ratio >= 1.25 or is_wick_rejection):
                        entry_p = live_p
                        sl_p = format_dynamic_precision(sweep_high + (0.05 * atr))
                        risk_amt = max(1e-6, sl_p - entry_p)
                        tp1_p = format_dynamic_precision(max(entry_p * 0.001, entry_p - (ob_tp1_mult * risk_amt)))
                        tp2_p = format_dynamic_precision(max(entry_p * 0.001, entry_p - (ob_tp2_mult * risk_amt)))
                        tp3_p = format_dynamic_precision(max(entry_p * 0.001, entry_p - (ob_tp3_mult * risk_amt)))
                        rr_ratio = round((entry_p - tp1_p) / risk_amt, 2)
                        return {
                            "setup_detected": True,
                            "direction": "SHORT",
                            "strategy": "TURTLE_SOUP_LIQUIDITY_RECLAIM",
                            "decision": f"🐢 [{best_ob.zeiierman_rank_label}] TURTLE SOUP RECLAIM (SHORT)",
                            "block_type": "BEARISH_SUPPLY_BLOCK",
                            "state": best_ob.state.value,
                            "zeiierman_rank": best_ob.zeiierman_rank,
                            "zeiierman_rank_label": best_ob.zeiierman_rank_label,
                            "entry_price": entry_p,
                            "optimal_entry_limit": best_ob.ob_high,
                            "mean_threshold_price": best_ob.equilibrium_50,
                            "order_block_zone": [round(best_ob.ob_low, 6), round(best_ob.ob_high, 6)],
                            "fvg_zone": [round(best_ob.fvg_low, 6), round(best_ob.fvg_high, 6)] if best_ob.has_fvg else None,
                            "sl_price": sl_p,
                            "tp1_price": tp1_p,
                            "tp2_price": tp2_p,
                            "tp3_price": tp3_p,
                            "risk_reward_ratio": rr_ratio,
                            "conviction": 84.0 + min(12.0, max(0.0, (vol_ratio - 1.0) * 10.0)),
                            "meta_win_prob": 0.68,
                            "retest_count": best_ob.retest_count,
                            "mitigation_factor": 0.60,
                            "active_block": best_ob.to_dict(),
                            "in_order_block_zone": True,
                            "is_touching": best_ob.is_touching,
                            "touch_type": best_ob.touch_type,
                            "mitigated": True,
                            "is_testing": True,
                            "is_nested_smc": best_ob.is_nested,
                            "htf_poi_tf": best_ob.htf_parent_tf,
                            "is_turtle_soup": True,
                            "reasons": [
                                f"Turtle Soup Liquidity Sweep Reclaim on {timeframe.upper()} {best_ob.zeiierman_rank_label}",
                                f"Price swept stops above {best_ob.ob_high:.4f} up to {sweep_high:.4f} and reclaimed inside zone with aggression",
                            ],
                        }

                    return {
                        "setup_detected": False,
                        "reason": f"Order block depleted after {best_ob.retest_count} touches",
                        "retest_count": best_ob.retest_count,
                        "mitigation_factor": 0.40,
                        "order_block_zone": [round(best_ob.ob_low, 6), round(best_ob.ob_high, 6)],
                    }

                entry_p = live_p
                min_sl_dist = max(0.85 * atr, min(entry_p * 0.008, 1.8 * atr))
                sl_p = max(best_ob.ob_high + (0.20 * atr), entry_p + min_sl_dist)
                # Enforce strict price invariant: entry must be comfortably below stop loss
                if entry_p < (sl_p - 0.05 * atr):
                    risk_amt = max(1e-6, sl_p - entry_p)
                    tp1_p = format_dynamic_precision(max(entry_p * 0.001, entry_p - (ob_tp1_mult * risk_amt)))
                    tp2_p = format_dynamic_precision(max(entry_p * 0.001, entry_p - (ob_tp2_mult * risk_amt)))
                    tp3_p = format_dynamic_precision(max(entry_p * 0.001, entry_p - (ob_tp3_mult * risk_amt)))
                    entry_p = format_dynamic_precision(entry_p)
                    sl_p = format_dynamic_precision(sl_p)

                    rr_ratio = round((entry_p - tp1_p) / risk_amt, 2)
                    rank_boosts = {1: 8.0, 2: 5.0, 3: 7.0, 4: 3.0, 5: 0.0}
                    base_conv = 80.0 if best_ob.zeiierman_rank <= 2 else 74.0
                    raw_conviction = min(98.5, base_conv + (best_ob.confluence_score * 12.0) + rank_boosts.get(best_ob.zeiierman_rank, 0.0))

                    # Mitigation degradation: 15% discount per prior touch
                    mitigation_factor = max(0.50, 1.0 - (0.15 * float(best_ob.retest_count)))
                    conviction = max(60.0, raw_conviction - (float(best_ob.retest_count) * 6.0))
                    raw_prob = 0.70 + (best_ob.confluence_score * 0.20)
                    meta_win_prob = round(max(0.48, min(0.95, raw_prob - (float(best_ob.retest_count) * 0.04))), 2)

                return {
                    "setup_detected": True,
                    "direction": "SHORT",
                    "strategy": "ORDER_BLOCK_SHORT",
                    "decision": f"🎯 [{best_ob.zeiierman_rank_label}] RETEST (SHORT)",
                    "block_type": "BEARISH_SUPPLY_BLOCK",
                    "state": best_ob.state.value,
                    "zeiierman_rank": best_ob.zeiierman_rank,
                    "zeiierman_rank_label": best_ob.zeiierman_rank_label,
                    "entry_price": entry_p,
                    "optimal_entry_limit": best_ob.equilibrium_50,
                    "mean_threshold_price": best_ob.equilibrium_50,
                    "order_block_zone": [round(best_ob.ob_low, 6), round(best_ob.ob_high, 6)],
                    "fvg_zone": [round(best_ob.fvg_low, 6), round(best_ob.fvg_high, 6)] if best_ob.has_fvg else None,
                    "sl_price": sl_p,
                    "tp1_price": tp1_p,
                    "tp2_price": tp2_p,
                    "tp3_price": tp3_p,
                    "risk_reward_ratio": rr_ratio,
                    "conviction": conviction,
                    "meta_win_prob": meta_win_prob,
                    "retest_count": best_ob.retest_count,
                    "mitigation_factor": round(mitigation_factor, 2),
                    "active_block": best_ob.to_dict(),
                    "in_order_block_zone": True,
                    "is_touching": best_ob.is_touching,
                    "touch_type": best_ob.touch_type,
                    "mitigated": (best_ob.retest_count > 0),
                    "is_testing": True,
                    "is_nested_smc": best_ob.is_nested,
                    "htf_poi_tf": best_ob.htf_parent_tf,
                    "reasons": [
                        f"Retest of verified {timeframe.upper()} {best_ob.zeiierman_rank_label} [{best_ob.ob_low:.4f} - {best_ob.ob_high:.4f}]",
                        f"Preceded by {best_ob.displacement_mag:.1f}x ATR displacement breaking swing support at {best_ob.mss_broken_level:.4f}",
                        f"Tight structural invalidation above Order Block High ({sl_p:.4f})"
                    ]
                }

        # ----------------------------------------------------------------------
        # 3. BREAKER BLOCK RETEST (RANK 4 POLARITY FLIP)
        # ----------------------------------------------------------------------
        if breaker_blocks:
            for bb in breaker_blocks:
                # Bearish Breaker: Former Demand Block broken downward, now acting as Supply Resistance
                if bb.block_type == OrderBlockType.BULLISH and live_p <= (bb.ob_high + 0.20 * atr) and live_high >= (bb.ob_low - 0.20 * atr):
                    entry_p = live_p
                    min_sl_dist = max(0.85 * atr, min(entry_p * 0.008, 1.8 * atr))
                    sl_p = max(bb.ob_high + (0.25 * atr), entry_p + min_sl_dist)
                    risk_amt = max(1e-8, sl_p - entry_p)
                    tp1_p = format_dynamic_precision(max(entry_p * 0.001, entry_p - (bb_tp1_mult * risk_amt)))
                    tp2_p = format_dynamic_precision(max(entry_p * 0.001, entry_p - (bb_tp2_mult * risk_amt)))
                    tp3_p = format_dynamic_precision(max(entry_p * 0.001, entry_p - (bb_tp3_mult * risk_amt)))
                    entry_p = format_dynamic_precision(entry_p)
                    sl_p = format_dynamic_precision(sl_p)
                    return {
                        "setup_detected": True,
                        "direction": "SHORT",
                        "strategy": "BREAKER_BLOCK_SHORT",
                        "decision": "🎯 ZEIIERMAN RANK 4 BREAKER-BLOCK REJECTION (SHORT)",
                        "block_type": "BEARISH_BREAKER_BLOCK",
                        "state": OrderBlockState.BREAKER.value,
                        "zeiierman_rank": 4,
                        "zeiierman_rank_label": "⚡ ZEIIERMAN RANK 4 (INSTITUTIONAL BREAKER BLOCK)",
                        "entry_price": entry_p,
                        "optimal_entry_limit": format_dynamic_precision(bb.equilibrium_50),
                        "mean_threshold_price": format_dynamic_precision(bb.equilibrium_50),
                        "order_block_zone": [format_dynamic_precision(bb.ob_low), format_dynamic_precision(bb.ob_high)],
                        "sl_price": sl_p,
                        "tp1_price": tp1_p,
                        "tp2_price": tp2_p,
                        "tp3_price": tp3_p,
                        "risk_reward_ratio": round((entry_p - tp1_p) / risk_amt, 2),
                        "conviction": 84.0,
                        "meta_win_prob": 0.78,
                        "active_block": bb.to_dict(),
                        "in_order_block_zone": True,
                        "is_touching": True,
                        "touch_type": "BREAKER_RETEST",
                        "mitigated": True,
                        "is_testing": True,
                        "is_nested_smc": False,
                        "htf_poi_tf": None,
                        "reasons": [
                            f"Retest of confirmed {timeframe.upper()} Breaker Block (Support flipped to Resistance)",
                            f"Broken demand level at {bb.ob_low:.4f} rejecting price upward relief"
                        ]
                    }
                # Bullish Breaker: Former Supply Block broken upward, now acting as Demand Support
                elif bb.block_type == OrderBlockType.BEARISH and live_p >= (bb.ob_low - 0.20 * atr) and live_low <= (bb.ob_high + 0.20 * atr):
                    entry_p = live_p
                    min_sl_dist = max(0.85 * atr, min(entry_p * 0.008, 1.8 * atr))
                    sl_p = min(bb.ob_low - (0.25 * atr), entry_p - min_sl_dist)
                    risk_amt = max(1e-8, entry_p - sl_p)
                    tp1_p = format_dynamic_precision(entry_p + (bb_tp1_mult * risk_amt))
                    tp2_p = format_dynamic_precision(entry_p + (bb_tp2_mult * risk_amt))
                    tp3_p = format_dynamic_precision(entry_p + (bb_tp3_mult * risk_amt))
                    entry_p = format_dynamic_precision(entry_p)
                    sl_p = format_dynamic_precision(sl_p)
                    return {
                        "setup_detected": True,
                        "direction": "LONG",
                        "strategy": "BREAKER_BLOCK_LONG",
                        "decision": "🎯 ZEIIERMAN RANK 4 BREAKER-BLOCK SUPPORT (LONG)",
                        "block_type": "BULLISH_BREAKER_BLOCK",
                        "state": OrderBlockState.BREAKER.value,
                        "zeiierman_rank": 4,
                        "zeiierman_rank_label": "⚡ ZEIIERMAN RANK 4 (INSTITUTIONAL BREAKER BLOCK)",
                        "entry_price": entry_p,
                        "optimal_entry_limit": format_dynamic_precision(bb.equilibrium_50),
                        "mean_threshold_price": format_dynamic_precision(bb.equilibrium_50),
                        "order_block_zone": [format_dynamic_precision(bb.ob_low), format_dynamic_precision(bb.ob_high)],
                        "sl_price": sl_p,
                        "tp1_price": tp1_p,
                        "tp2_price": tp2_p,
                        "tp3_price": tp3_p,
                        "risk_reward_ratio": round((tp1_p - entry_p) / risk_amt, 2),
                        "conviction": 84.0,
                        "meta_win_prob": 0.78,
                        "active_block": bb.to_dict(),
                        "in_order_block_zone": True,
                        "is_touching": True,
                        "touch_type": "BREAKER_RETEST",
                        "mitigated": True,
                        "is_testing": True,
                        "is_nested_smc": False,
                        "htf_poi_tf": None,
                        "reasons": [
                            f"Retest of confirmed {timeframe.upper()} Breaker Block (Resistance flipped to Support)",
                            f"Broken supply level at {bb.ob_high:.4f} providing structural launchpad"
                        ]
                    }

        return {
            "setup_detected": False,
            "reason": "Price outside active order block zones",
            "active_blocks_count": len(blocks)
        }

    @classmethod
    def scan_all_horizons(
        cls,
        dfs_9: Dict[str, pd.DataFrame],
        current_price: Optional[float] = None,
        btc_shield: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Deep Multi-Horizon Institutional Order Block Scanner across 9 Charts.
        - Evaluates order blocks on 5m, 15m, 1h, 4h, 12h, 1d, 1w.
        - Detects Nested Confluence (LTF order blocks inside HTF POIs -> Rank 3).
        - Identifies exact TOUCH / RETEST events on active bars.
        - Computes distance to nearest Demand, Supply, and Breaker levels.
        - Returns structured telemetry and candidate trade setups.
        """
        if not dfs_9:
            return {"has_active_touch": False, "touched_horizons": [], "horizon_blocks": {}}

        # Anchor price
        ref_tf = "15m" if ("15m" in dfs_9 and dfs_9["15m"] is not None) else list(dfs_9.keys())[0]
        live_p = current_price or float(dfs_9[ref_tf]['close'].iloc[-1])

        # Helper to resolve dataframe with case and alias support
        def _get_df_for_tf(tf_name: str) -> Optional[pd.DataFrame]:
            if tf_name in dfs_9 and dfs_9[tf_name] is not None:
                return dfs_9[tf_name]
            aliases = {
                "1d": ["24h", "1D", "24H"],
                "24h": ["1d", "1D", "24H"],
                "1w": ["7d", "1W", "7D"],
                "7d": ["1w", "1W", "7D"],
                "1M": ["30d", "1m", "30D"],
                "30d": ["1M", "1m", "30D"],
                "5m": ["5M"],
                "15m": ["15M"],
                "1h": ["1H"],
                "4h": ["4H"],
                "12h": ["12H"],
                "15d": ["15D"]
            }
            for a in aliases.get(tf_name, []):
                if a in dfs_9 and dfs_9[a] is not None:
                    return dfs_9[a]
            return None

        # Scan all 9 horizons with fallback alias handling
        timeframes_to_scan = ["5m", "15m", "1h", "4h", "12h", "1d", "1w", "15d", "1M"]
        horizon_blocks: Dict[str, List[OrderBlock]] = {}
        horizon_setups: Dict[str, Dict[str, Any]] = {}
        touched_horizons: List[str] = []

        all_active_blocks: List[OrderBlock] = []

        # 1. Detect order blocks across all timeframes
        for tf in timeframes_to_scan:
            df = _get_df_for_tf(tf)
            if df is not None and len(df) >= 25:
                blocks = cls.detect_order_blocks(df, timeframe=tf, current_price=live_p)
                horizon_blocks[tf] = blocks
                all_active_blocks.extend(blocks)
                regime_str = ""
                if btc_shield:
                    regime_str = str(btc_shield.get("btc_shield_status") or btc_shield.get("btc_regime") or "")
                live_setup = cls.evaluate_live_setup(df, timeframe=tf, current_price=live_p, market_regime=regime_str)
                # Only genuine active touches on valid institutional blocks (Ranks 1..4) qualify
                if live_setup.get("setup_detected") and live_setup.get("is_touching") and live_setup.get("zeiierman_rank", 5) <= 4:
                    horizon_setups[tf] = live_setup
                    touched_horizons.append(tf)

        # 2. Cross-Timeframe Nested SMC Analysis (Rank 1 Upgrades)
        # Check if an LTF block (5m, 15m, 1h) falls inside an HTF block (4h, 12h, 1d, 1w, 15d, 1M)
        htf_tfs = ["4h", "12h", "1d", "1w", "15d", "1M"]
        ltf_tfs = ["5m", "15m", "1h"]

        upgraded_tfs = set()
        for ltf in ltf_tfs:
            for l_ob in horizon_blocks.get(ltf, []):
                for htf in htf_tfs:
                    for h_ob in horizon_blocks.get(htf, []):
                        if l_ob.block_type == h_ob.block_type:
                            # Overlap condition: LTF block intersects with HTF block
                            overlaps = (l_ob.ob_low <= h_ob.ob_high and l_ob.ob_high >= h_ob.ob_low)
                            if overlaps:
                                l_ob.is_nested = True
                                l_ob.htf_parent_tf = htf
                                l_ob.zeiierman_rank = OrderBlockRank.RANK_1_EXTREME_ORIGIN.value
                                l_ob.zeiierman_rank_label = f"💎 ZEIIERMAN RANK 1 NESTED SMC [{htf.upper()} POI + {ltf.upper()} TRIGGER]"
                                l_ob.confluence_score = min(0.99, l_ob.confluence_score + 0.15)

                                # If setup was generated for this timeframe, upgrade it once (deduplicated against compounding)
                                if ltf in horizon_setups and horizon_setups[ltf].get("setup_detected") and ltf not in upgraded_tfs:
                                    s = horizon_setups[ltf]
                                    s["is_nested_smc"] = True
                                    s["htf_poi_tf"] = htf
                                    s["zeiierman_rank"] = 1
                                    s["zeiierman_rank_label"] = l_ob.zeiierman_rank_label
                                    s["decision"] = f"🎯 ZEIIERMAN RANK 1 NESTED SMC ORDER-BLOCK ({'LONG' if l_ob.block_type == OrderBlockType.BULLISH else 'SHORT'})"
                                    s["conviction"] = min(95.0, float(s.get("conviction", 84.0)) + 6.0)
                                    s["meta_win_prob"] = min(0.88, float(s.get("meta_win_prob", 0.76)) + 0.08)
                                    upgraded_tfs.add(ltf)
                                break
                    if l_ob.is_nested:
                        break

        # 3. Identify Nearest Demand, Supply, and Breaker levels
        nearest_demand_lvl = None
        nearest_demand_dist = 999.0
        nearest_supply_lvl = None
        nearest_supply_dist = 999.0

        for b in all_active_blocks:
            if b.block_type == OrderBlockType.BULLISH and b.state != OrderBlockState.BREAKER:
                if b.ob_low <= live_p:
                    d = ((live_p - b.ob_high) / live_p) * 100.0 if live_p > b.ob_high else 0.0
                    if d < nearest_demand_dist:
                        nearest_demand_dist = round(d, 2)
                        nearest_demand_lvl = b.ob_high if live_p >= b.ob_high else b.ob_low
            elif b.block_type == OrderBlockType.BEARISH and b.state != OrderBlockState.BREAKER:
                if b.ob_high >= live_p:
                    d = ((b.ob_low - live_p) / live_p) * 100.0 if live_p < b.ob_low else 0.0
                    if d < nearest_supply_dist:
                        nearest_supply_dist = round(d, 2)
                        nearest_supply_lvl = b.ob_low if live_p <= b.ob_low else b.ob_high

        # 4. Determine Best Live Touch Setup
        best_setup = None
        if horizon_setups:
            # Prioritize 24H / 1D > 1H > 15M > 4H > 12H > 1W > 15D > 1M > 5M, and Rank 1 > Rank 3 > Rank 2 > Rank 4 > Rank 5
            tf_weights = {
                "1M": 12, "30d": 12, "1m": 12,
                "15d": 11, "15D": 11,
                "1w": 10, "7d": 10, "1W": 10, "7D": 10,
                "1d": 10, "24h": 10, "1D": 10, "24H": 10,
                "1h": 8, "1H": 8,
                "15m": 6, "15M": 6,
                "4h": 5, "4H": 5,
                "12h": 4, "12H": 4,
                "5m": 3, "5M": 3
            }
            best_tf = max(horizon_setups.keys(), key=lambda t: (
                -horizon_setups[t].get("zeiierman_rank", 5),
                tf_weights.get(t, 1),
                horizon_setups[t].get("conviction", 0.0)
            ))
            best_setup = horizon_setups[best_tf]

        # 5. Build concise summary for each timeframe
        horizon_blocks_summary = {}
        for tf in timeframes_to_scan:
            b_list = horizon_blocks.get(tf, [])
            touch_b = [b for b in b_list if (b.is_touching or b.state == OrderBlockState.TESTING) and b.zeiierman_rank <= 4]
            if touch_b:
                touch_b.sort(key=lambda b: (b.zeiierman_rank, -b.confluence_score))
                best_t = touch_b[0]
                has_touch = True
                touch_rank = best_t.zeiierman_rank
                touch_label = best_t.zeiierman_rank_label
                touch_type = best_t.touch_type
                nearest_z = [round(best_t.ob_low, 6), round(best_t.ob_high, 6)]
            else:
                has_touch = False
                touch_rank = None
                touch_label = None
                touch_type = "NONE"
                nearest_z = [round(b_list[-1].ob_low, 6), round(b_list[-1].ob_high, 6)] if b_list else None

            horizon_blocks_summary[tf] = {
                "total_blocks": len(b_list),
                "has_touch": has_touch,
                "touch_rank": touch_rank,
                "touch_label": touch_label,
                "touch_type": touch_type,
                "nearest_zone": nearest_z,
                "blocks": [b.to_dict() for b in b_list[-3:]]
            }

        return {
            "has_active_touch": bool(len(touched_horizons) > 0),
            "touched_horizons": touched_horizons,
            "active_touches_count": len(touched_horizons),
            "best_touch_setup": best_setup,
            "touch_setups_by_horizon": horizon_setups,
            "nearest_demand_level": nearest_demand_lvl,
            "nearest_demand_dist_pct": nearest_demand_dist if nearest_demand_dist < 999.0 else 0.0,
            "nearest_supply_level": nearest_supply_lvl,
            "nearest_supply_dist_pct": nearest_supply_dist if nearest_supply_dist < 999.0 else 0.0,
            "horizon_blocks": horizon_blocks_summary,
            "active_blocks_count": len(all_active_blocks)
        }

    @classmethod
    def evaluate_nested_setup(
        cls,
        raw_dfs: Dict[str, pd.DataFrame],
        anchor_tf: str = "1h",
        current_price: Optional[float] = None,
        btc_regime: str = "NORMAL",
        rs_btc: float = 0.0
    ) -> Dict[str, Any]:
        """
        Full Multi-Timeframe Nested SMC Order Block Engine.
        Directly backed by scan_all_horizons.
        """
        scan = cls.scan_all_horizons(raw_dfs, current_price=current_price)
        best = scan.get("best_touch_setup")
        if best:
            # Counter-trend short suppression in strong bull regime
            if best.get("direction") == "SHORT" and (rs_btc > 0.15 or btc_regime in ["BULL", "UPTREND", "STRONG_BULL"]):
                return {
                    "setup_detected": False,
                    "reason": f"Bearish Order Block filtered: Counter-trend short suppressed by macro bull regime (RS: {rs_btc:+.2f})"
                }
            return best

        anchor_df = raw_dfs.get(anchor_tf)
        if anchor_df is not None and len(anchor_df) >= 25:
            return cls.evaluate_live_setup(anchor_df, timeframe=anchor_tf, current_price=current_price)

        return {"setup_detected": False, "reason": "No active order block setup in range"}

    @classmethod
    def extract_features(cls, df: pd.DataFrame, prefix: str = "1h") -> pd.DataFrame:
        """
        Calculates stationary features for ML and quantitative pipelines.
        """
        feats = pd.DataFrame(index=df.index)
        n = len(df)
        if n < 25:
            feats[f'{prefix}_in_bull_ob'] = 0.0
            feats[f'{prefix}_in_bear_ob'] = 0.0
            feats[f'{prefix}_dist_to_bull_ob'] = 3.0
            feats[f'{prefix}_dist_to_bear_ob'] = 3.0
            feats[f'{prefix}_ob_confluence'] = 0.0
            return feats

        atr = cls.compute_atr(df, period=14)
        c = df['close']

        blocks = cls.detect_order_blocks(df, timeframe=prefix)

        in_bull = np.zeros(n, dtype=np.float32)
        in_bear = np.zeros(n, dtype=np.float32)
        dist_bull = np.full(n, 3.0, dtype=np.float32)
        dist_bear = np.full(n, 3.0, dtype=np.float32)
        ob_conf = np.zeros(n, dtype=np.float32)

        for b in blocks:
            if b.state in [OrderBlockState.FRESH, OrderBlockState.TESTING]:
                for k in range(max(0, n - 10), n):
                    curr_c = float(c.iloc[k])
                    curr_atr = max(1e-8, float(atr.iloc[k]))
                    if b.block_type == OrderBlockType.BULLISH:
                        if b.ob_low <= curr_c <= b.ob_high:
                            in_bull[k] = 1.0
                            ob_conf[k] = max(ob_conf[k], float(b.confluence_score))
                        d = (curr_c - b.ob_high) / curr_atr
                        dist_bull[k] = min(dist_bull[k], max(0.0, d))
                    elif b.block_type == OrderBlockType.BEARISH:
                        if b.ob_low <= curr_c <= b.ob_high:
                            in_bear[k] = 1.0
                            ob_conf[k] = max(ob_conf[k], float(b.confluence_score))
                        d = (b.ob_low - curr_c) / curr_atr
                        dist_bear[k] = min(dist_bear[k], max(0.0, d))

        feats[f'{prefix}_in_bull_ob'] = in_bull
        feats[f'{prefix}_in_bear_ob'] = in_bear
        feats[f'{prefix}_dist_to_bull_ob'] = dist_bull
        feats[f'{prefix}_dist_to_bear_ob'] = dist_bear
        feats[f'{prefix}_ob_confluence'] = ob_conf
        return feats


# Global Singleton Instance
order_block_engine = InstitutionalOrderBlockEngine()
