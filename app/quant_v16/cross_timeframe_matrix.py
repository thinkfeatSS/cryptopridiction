"""
QUANT EDGE V16: Institutional Cross-Timeframe Matrix Engine
Evaluates Higher Timeframe (4H / 1D / Macro) vs Lower Timeframe (5M / 15M / 1H)
to assign one of the 5 Institutional Archetypes:
- Archetype A: Secular Super-Trend Expansion (LTF Trend == HTF Trend)
- Archetype B: Coiling Spring / Breakout Preparation (HTF Trend + LTF Coiling Squeeze)
- Archetype C: Range Rotation / Ping-Pong (HTF Range Box + LTF Trend toward boundary)
- Archetype D: Discount Pullback / Liquidity Hunt (HTF Trend + LTF Counter-Trend)
- Archetype E: Dead Market Stagnation (LTF Chop + HTF Chop) -> Strict No Trade Zone
"""

from enum import Enum
from typing import Dict, Any, Optional, List
from app.quant_v16.fractal_consolidation import (
    FractalTimeframeState,
    TimeframeConsolidationProfile,
    FractalConsolidationEngine
)


class InstitutionalArchetype(str, Enum):
    ARCHETYPE_A_SECULAR_EXPANSION = "ARCHETYPE_A_SECULAR_EXPANSION"
    ARCHETYPE_B_COILING_BREAKOUT = "ARCHETYPE_B_COILING_BREAKOUT"
    ARCHETYPE_C_RANGE_ROTATION = "ARCHETYPE_C_RANGE_ROTATION"
    ARCHETYPE_D_DISCOUNT_PULLBACK = "ARCHETYPE_D_DISCOUNT_PULLBACK"
    ARCHETYPE_E_STAGNATION_DEAD_ZONE = "ARCHETYPE_E_STAGNATION_DEAD_ZONE"


class CrossTimeframeMatrixEngine:
    """
    Synthesizes multi-horizon profiles to govern signal qualification, trade direction,
    target headroom, and paper trading bot execution.
    """

    @staticmethod
    def evaluate_matrix(
        profiles: Dict[str, TimeframeConsolidationProfile],
        current_price: float
    ) -> Dict[str, Any]:
        """
        Takes profiles for all 9 horizons (5m, 15m, 1h, 4h, 12h, 1d, 7d, 15d, 30d)
        and evaluates the cross-timeframe dynamic.
        """
        # Helper for case-insensitive and alias profile retrieval
        def _get_prof(keys: List[str]) -> Optional[TimeframeConsolidationProfile]:
            for k in keys:
                if k in profiles and profiles[k] is not None:
                    return profiles[k]
                k_lower = k.lower()
                for pk, pv in profiles.items():
                    if pk.lower() == k_lower and pv is not None:
                        return pv
            return None

        # 1. Extract Primary Anchors with alias and hierarchy fallback
        p_15m = _get_prof(["15m", "15M", "5m", "5M"])
        p_1h = _get_prof(["1h", "1H"]) or p_15m
        p_4h = _get_prof(["4h", "4H", "12h", "12H"]) or p_1h
        p_1d = _get_prof(["1d", "1D", "24h", "24H", "1w", "7d", "15d", "1M", "30d"]) or p_4h

        # Fallback if profiles missing
        if not p_15m or not p_1d:
            return {
                "archetype": InstitutionalArchetype.ARCHETYPE_E_STAGNATION_DEAD_ZONE.value,
                "trade_permitted": False,
                "strategy": "CAPITAL_PRESERVATION",
                "dominant_direction": "NO_TRADE",
                "allocation_pct": 0.0,
                "rationale": "Insufficient multi-horizon profile data",
                "headroom_pct": 0.0,
                "htf_range_high": current_price,
                "htf_range_low": current_price,
            }

        # Determine Higher Timeframe (HTF) Posture: 4H & 1D
        # 1D is the dominant macro anchor, 4H is the intermediate anchor
        is_1d_bull = (p_1d.state == FractalTimeframeState.TREND_BULLISH)
        is_1d_bear = (p_1d.state == FractalTimeframeState.TREND_BEARISH)
        is_1d_ranging = (p_1d.state == FractalTimeframeState.CONSOLIDATION_RANGING)
        is_1d_coiling = (p_1d.state == FractalTimeframeState.CONSOLIDATION_COILING)

        is_4h_bull = (p_4h.state == FractalTimeframeState.TREND_BULLISH)
        is_4h_bear = (p_4h.state == FractalTimeframeState.TREND_BEARISH)
        is_4h_ranging = (p_4h.state == FractalTimeframeState.CONSOLIDATION_RANGING)
        is_4h_coiling = (p_4h.state == FractalTimeframeState.CONSOLIDATION_COILING)

        # Determine Lower Timeframe (LTF) Posture: 15M & 1H
        ltf_bullish = (p_15m.state == FractalTimeframeState.TREND_BULLISH or p_1h.state == FractalTimeframeState.TREND_BULLISH) and (p_15m.state != FractalTimeframeState.TREND_BEARISH)
        ltf_bearish = (p_15m.state == FractalTimeframeState.TREND_BEARISH or p_1h.state == FractalTimeframeState.TREND_BEARISH) and (p_15m.state != FractalTimeframeState.TREND_BULLISH)
        ltf_coiling = (p_15m.state == FractalTimeframeState.CONSOLIDATION_COILING or p_15m.is_coiling_squeeze)
        ltf_ranging = (p_15m.state == FractalTimeframeState.CONSOLIDATION_RANGING)

        htf_high = p_1d.range_high
        htf_low = p_1d.range_low
        headroom_to_high = p_1d.headroom_to_high_pct
        headroom_to_low = p_1d.headroom_to_low_pct

        # Breakout status on 1D (price outside 1D range boundaries or headroom >= 90.0)
        is_1d_breakout_up = bool(headroom_to_high >= 90.0 or (htf_high > 0 and current_price >= htf_high))
        is_1d_breakout_down = bool(headroom_to_low >= 90.0 or (htf_low > 0 and current_price <= htf_low))
        has_real_4h = bool(p_4h and p_4h.timeframe in ["4h", "4H", "12h", "12H"])
        is_4h_breakout_up = bool(has_real_4h and (p_4h.headroom_to_high_pct >= 90.0 or (p_4h.range_high > 0 and current_price >= p_4h.range_high)))
        is_4h_breakout_down = bool(has_real_4h and (p_4h.headroom_to_low_pct >= 90.0 or (p_4h.range_low > 0 and current_price <= p_4h.range_low)))

        # Breakout expansion occurs when price breaks outside the macro HTF range box
        is_breakout_expansion_up = bool((is_1d_breakout_up or (is_4h_breakout_up and (htf_high <= 0 or current_price >= htf_high))) and not is_1d_bear and not ltf_bearish)
        is_breakout_expansion_down = bool((is_1d_breakout_down or (is_4h_breakout_down and (htf_low <= 0 or current_price <= htf_low))) and not is_1d_bull and not ltf_bullish)

        htf_bullish = bool((is_1d_bull or is_1d_breakout_up or (is_4h_bull and not is_1d_ranging and not is_1d_bear)) and not is_1d_bear)
        htf_bearish = bool((is_1d_bear or is_1d_breakout_down or (is_4h_bear and not is_1d_ranging and not is_1d_bull)) and not is_1d_bull)
        htf_ranging = bool((is_1d_ranging or (is_4h_ranging and not is_1d_bull and not is_1d_bear)) and not is_1d_breakout_up and not is_1d_breakout_down and not is_breakout_expansion_up and not is_breakout_expansion_down)
        htf_coiling = bool((is_1d_coiling or is_4h_coiling) and not htf_bullish and not htf_bearish)

        # =====================================================================
        # ARCHETYPE CLASSIFICATION HIERARCHY
        # =====================================================================

        # PRIORITY 0: Directional Breakout Expansion (Macro Trend Emergence from Range Box)
        # When price breaches the 1D/4H range boundaries, directional expansion unlocks high-confluence trend signals
        if is_breakout_expansion_up:
            return {
                "archetype": InstitutionalArchetype.ARCHETYPE_A_SECULAR_EXPANSION.value,
                "trade_permitted": True,
                "strategy": "DIRECTIONAL_BREAKOUT_EXPANSION",
                "dominant_direction": "LONG",
                "allocation_pct": 100.0,
                "headroom_pct": 99.0,
                "htf_range_high": htf_high,
                "htf_range_low": htf_low,
                "rationale": f"Directional breakout expansion active: Price broke above macro range ceiling ({htf_high:.4f}). Blue-sky trend expansion unlocked.",
            }
        elif is_breakout_expansion_down:
            return {
                "archetype": InstitutionalArchetype.ARCHETYPE_A_SECULAR_EXPANSION.value,
                "trade_permitted": True,
                "strategy": "DIRECTIONAL_BREAKOUT_EXPANSION",
                "dominant_direction": "SHORT",
                "allocation_pct": 100.0,
                "headroom_pct": 99.0,
                "htf_range_high": htf_high,
                "htf_range_low": htf_low,
                "rationale": f"Directional breakdown expansion active: Price broke below macro range floor ({htf_low:.4f}). Downside trend expansion unlocked.",
            }

        # PRIORITY 1: Middle-Range Chop Capital Preservation Gate
        # Section 35: When trapped in the middle 50% chop zone (0.25 < range_pos < 0.75),
        # the quantitative matrix strictly preserves capital and suppresses low-edge trades.
        # Trades are ONLY admitted at validated boundaries (range_pos <= 0.25 or range_pos >= 0.75),
        # spring-loaded coiling breakout preparations (ltf_coiling with HTF trend), or confirmed secular expansions.
        range_span = max(1e-8, htf_high - htf_low) if (htf_high > htf_low > 0) else 0.0
        range_pos = ((current_price - htf_low) / range_span) if range_span > 0 else 0.50
        price_rel_pct = range_pos * 100.0

        p_1d_adx = getattr(p_1d, "adx", 20.0)
        p_1d_chop = getattr(p_1d, "chop_index", 50.0)
        p_15m_adx = getattr(p_15m, "adx", 20.0)

        is_coiling_spring = bool((htf_bullish or htf_bearish or htf_ranging) and ltf_coiling)
        is_strong_secular_trend = bool(
            ((htf_bullish and ltf_bullish) or (htf_bearish and ltf_bearish)) and
            p_1d_adx >= 25.0 and p_15m_adx >= 25.0 and p_1d_chop < 42.0
        )

        if range_span > 0 and (0.25 < range_pos < 0.75) and not is_coiling_spring and not is_strong_secular_trend:
            # Section 35 Fractal Sub-Range Decomposition:
            # Even when 1D/macro is trapped in the middle 50% chop zone,
            # evaluate whether 1H (or 15M) intraday horizon has formed a validated sub-range boundary.
            sub_prof = p_1h if (p_1h is not None and getattr(p_1h, "range_high", 0) > 0 and getattr(p_1h, "range_low", 0) > 0) else p_15m
            sub_span = max(1e-8, sub_prof.range_high - sub_prof.range_low) if (sub_prof and sub_prof.range_high > sub_prof.range_low > 0) else 0.0
            sub_pos = ((current_price - sub_prof.range_low) / sub_span) if sub_span > 0 else 0.50
            htf_mid = (htf_high + htf_low) / 2.0

            # Sub-Range Support Mean Reversion (Intraday floor bounce within macro box)
            if sub_span > 0 and (0.0 <= sub_pos <= 0.25) and sub_prof.headroom_to_high_pct >= 1.5:
                # Target TP1 capped at macro equilibrium (1D mid) to eliminate fighting macro chop
                target_mid_cap = ((htf_mid - current_price) / max(1e-8, current_price)) * 100.0 if htf_mid > current_price else sub_prof.headroom_to_high_pct
                sub_headroom = round(min(sub_prof.headroom_to_high_pct, max(1.0, target_mid_cap)), 2)
                return {
                    "archetype": InstitutionalArchetype.ARCHETYPE_C_RANGE_ROTATION.value,
                    "trade_permitted": True,
                    "strategy": "SUB_RANGE_SUPPORT_MEAN_REVERSION",
                    "dominant_direction": "LONG",
                    "allocation_pct": 50.0,
                    "headroom_pct": sub_headroom,
                    "htf_range_high": htf_high,
                    "htf_range_low": htf_low,
                    "rationale": f"Fractal Sub-Range Support Reversion active: 1D trapped in middle chop ({price_rel_pct:.1f}%), but {sub_prof.timeframe.upper()} is at intraday support boundary ({sub_pos*100:.1f}%) with {sub_headroom:.1f}% headroom to macro equilibrium.",
                }

            # Sub-Range Resistance Mean Reversion (Intraday ceiling rejection within macro box)
            if sub_span > 0 and (0.75 <= sub_pos <= 1.0) and sub_prof.headroom_to_low_pct >= 1.5:
                # Target TP1 capped at macro equilibrium (1D mid) to eliminate fighting macro chop
                target_mid_cap = ((current_price - htf_mid) / max(1e-8, current_price)) * 100.0 if current_price > htf_mid else sub_prof.headroom_to_low_pct
                sub_headroom = round(min(sub_prof.headroom_to_low_pct, max(1.0, target_mid_cap)), 2)
                return {
                    "archetype": InstitutionalArchetype.ARCHETYPE_C_RANGE_ROTATION.value,
                    "trade_permitted": True,
                    "strategy": "SUB_RANGE_RESISTANCE_MEAN_REVERSION",
                    "dominant_direction": "SHORT",
                    "allocation_pct": 50.0,
                    "headroom_pct": sub_headroom,
                    "htf_range_high": htf_high,
                    "htf_range_low": htf_low,
                    "rationale": f"Fractal Sub-Range Resistance Reversion active: 1D trapped in middle chop ({price_rel_pct:.1f}%), but {sub_prof.timeframe.upper()} is at intraday resistance boundary ({sub_pos*100:.1f}%) with {sub_headroom:.1f}% headroom to macro equilibrium.",
                }

            # If both 1D and intraday sub-range are in the dead middle chop, strictly preserve capital
            return {
                "archetype": InstitutionalArchetype.ARCHETYPE_C_RANGE_ROTATION.value,
                "trade_permitted": False,
                "strategy": "CAPITAL_PRESERVATION_MIDDLE_CHOP_VETO",
                "dominant_direction": "NO_TRADE",
                "allocation_pct": 0.0,
                "headroom_pct": min(headroom_to_high, headroom_to_low),
                "htf_range_high": htf_high,
                "htf_range_low": htf_low,
                "rationale": f"Trapped in middle 50% chop zone of macro range box (range_pos={range_pos:.3f}, {price_rel_pct:.1f}%) and intraday {sub_prof.timeframe.upper()} sub-range ({sub_pos*100:.1f}%). Section 35 capital preservation gate strictly locked: Trades only admitted at validated boundaries (range_pos <= 0.25 or >= 0.75), spring-loaded coiling squeezes, or confirmed macro breakout expansions.",
            }


        # PRIORITY 2: Range Rotation at Validated Boundaries (HTF Trapped in Range Box)
        # If 1D is actively ranging in a horizontal box, check boundary position and headroom (Section 35)
        if htf_ranging:

            # Range Support Boundary (Lower Quartile: price_rel_pct <= 25.0%)
            if price_rel_pct <= 25.0:
                if headroom_to_high >= 2.0:
                    return {
                        "archetype": InstitutionalArchetype.ARCHETYPE_C_RANGE_ROTATION.value,
                        "trade_permitted": True,
                        "strategy": "RANGE_SUPPORT_MEAN_REVERSION",
                        "dominant_direction": "LONG",
                        "allocation_pct": 60.0,
                        "headroom_pct": headroom_to_high,
                        "htf_range_high": htf_high,
                        "htf_range_low": htf_low,
                        "rationale": f"1D Range Support boundary active (price at lower quartile {price_rel_pct:.1f}%): Bounce zone with {headroom_to_high:.1f}% headroom to range ceiling.",
                    }
                else:
                    return {
                        "archetype": InstitutionalArchetype.ARCHETYPE_C_RANGE_ROTATION.value,
                        "trade_permitted": False,
                        "strategy": "RANGE_BOUNDARY_VETO",
                        "dominant_direction": "NO_TRADE",
                        "allocation_pct": 0.0,
                        "headroom_pct": headroom_to_high,
                        "htf_range_high": htf_high,
                        "htf_range_low": htf_low,
                        "rationale": f"Vetoed by 1D Range Extreme: Only {headroom_to_high:.1f}% headroom remaining before hitting range ceiling.",
                    }

            # Range Resistance Boundary (Upper Quartile: price_rel_pct >= 75.0%)
            if price_rel_pct >= 75.0:
                if headroom_to_low >= 2.0:
                    return {
                        "archetype": InstitutionalArchetype.ARCHETYPE_C_RANGE_ROTATION.value,
                        "trade_permitted": True,
                        "strategy": "RANGE_RESISTANCE_MEAN_REVERSION",
                        "dominant_direction": "SHORT",
                        "allocation_pct": 60.0,
                        "headroom_pct": headroom_to_low,
                        "htf_range_high": htf_high,
                        "htf_range_low": htf_low,
                        "rationale": f"1D Range Resistance boundary active (price at upper quartile {price_rel_pct:.1f}%): Rejection zone with {headroom_to_low:.1f}% headroom to range floor.",
                    }
                else:
                    return {
                        "archetype": InstitutionalArchetype.ARCHETYPE_C_RANGE_ROTATION.value,
                        "trade_permitted": False,
                        "strategy": "RANGE_BOUNDARY_VETO",
                        "dominant_direction": "NO_TRADE",
                        "allocation_pct": 0.0,
                        "headroom_pct": headroom_to_low,
                        "htf_range_high": htf_high,
                        "htf_range_low": htf_low,
                        "rationale": f"Vetoed by 1D Range Extreme: Only {headroom_to_low:.1f}% headroom remaining before hitting range floor.",
                    }

        # PRIORITY 3: Coiling Spring / Breakout Preparation (HTF Trending or Ranging + LTF Coiling Squeeze)
        # 15M is compressed in an Inside Bar/NR7/BBW squeeze ready to erupt
        elif (htf_bullish or htf_bearish or htf_ranging) and ltf_coiling:
            if htf_bullish:
                direction = "LONG"
                headroom = headroom_to_high
            elif htf_bearish:
                direction = "SHORT"
                headroom = headroom_to_low
            else:
                # Squeeze inside macro range box: directed towards opposite boundary with ample headroom
                direction = "LONG" if range_pos < 0.50 else "SHORT"
                headroom = headroom_to_high if direction == "LONG" else headroom_to_low

            return {
                "archetype": InstitutionalArchetype.ARCHETYPE_B_COILING_BREAKOUT.value,
                "trade_permitted": True,
                "strategy": "COILING_VOLATILITY_BREAKOUT",
                "dominant_direction": direction,
                "allocation_pct": 85.0,
                "headroom_pct": headroom,
                "htf_range_high": htf_high,
                "htf_range_low": htf_low,
                "rationale": f"Spring-loaded coiling compression on 15M (Inside Bar/NR7/BBW Squeeze) ready to expand {direction} with {headroom:.1f}% headroom.",
            }

        # PRIORITY 4: Secular Super-Trend Expansion (Both HTF and LTF Trending in Same Direction)
        elif (htf_bullish and ltf_bullish) or (htf_bearish and ltf_bearish):
            direction = "LONG" if htf_bullish else "SHORT"
            return {
                "archetype": InstitutionalArchetype.ARCHETYPE_A_SECULAR_EXPANSION.value,
                "trade_permitted": True,
                "strategy": "MOMENTUM_TREND_EXPANSION",
                "dominant_direction": direction,
                "allocation_pct": 100.0,
                "headroom_pct": headroom_to_high if direction == "LONG" else headroom_to_low,
                "htf_range_high": htf_high,
                "htf_range_low": htf_low,
                "rationale": f"Secular multi-horizon trend alignment: Both LTF (15M) and HTF (1D) expanding {direction}.",
            }

        # Archetype D: Discount Pullback (HTF Trending + LTF Counter-Trending)
        elif (htf_bullish and ltf_bearish) or (htf_bearish and ltf_bullish):
            primary_htf = "BULLISH" if htf_bullish else "BEARISH"
            counter_ltf = "BEARISH" if ltf_bearish else "BULLISH"
            return {
                "archetype": InstitutionalArchetype.ARCHETYPE_D_DISCOUNT_PULLBACK.value,
                "trade_permitted": False,  # Queued until counter-trend exhausts and flips
                "strategy": "AWAITING_LIQUIDITY_SWEEP_REVERSAL",
                "dominant_direction": "QUEUED_DIP_BUY" if htf_bullish else "QUEUED_RALLY_SHORT",
                "allocation_pct": 0.0,
                "headroom_pct": headroom_to_high if htf_bullish else headroom_to_low,
                "htf_range_high": htf_high,
                "htf_range_low": htf_low,
                "rationale": f"Discount pullback active: 1D {primary_htf} while 15M {counter_ltf}. Waiting for LTF exhaustion into HTF order block.",
            }

        # Archetype E: Dead Market Stagnation (Both LTF and HTF in Chop / Low Volume)
        else:
            return {
                "archetype": InstitutionalArchetype.ARCHETYPE_E_STAGNATION_DEAD_ZONE.value,
                "trade_permitted": False,
                "strategy": "STRICT_NO_TRADE_ZONE",
                "dominant_direction": "NO_TRADE",
                "allocation_pct": 0.0,
                "headroom_pct": 0.0,
                "htf_range_high": htf_high,
                "htf_range_low": htf_low,
                "rationale": "Multi-horizon stagnation: Both LTF and HTF compressed in low-liquidity chop. Signals locked for capital preservation.",
            }
