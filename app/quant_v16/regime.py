"""
QUANT EDGE V16: Market Regime Engine
Specifications:
- Section 5: Market Regime Engine (BULL_TREND, BEAR_TREND, RANGE, HIGH_VOLATILITY, LOW_VOLATILITY, SQUEEZE, BREAKOUT, TRANSITION, UNKNOWN)
- Section 6: Regime Output
- Section 29: Regime Position Multipliers
- Section 35: Range Regime (prefer boundaries, avoid middle 50%)
- Section 36: Breakout Regime
- Section 37: Squeeze Regime
"""

from enum import Enum
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field
import math
import numpy as np
import pandas as pd
from datetime import datetime, timezone

class MarketRegime(str, Enum):
    BULL_TREND = "BULL_TREND"
    BEAR_TREND = "BEAR_TREND"
    RANGE = "RANGE"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    SQUEEZE = "SQUEEZE"
    BREAKOUT = "BREAKOUT"
    TRANSITION = "TRANSITION"
    UNKNOWN = "UNKNOWN"

@dataclass
class RegimeEvaluation:
    regime: MarketRegime
    probabilities: Dict[str, float]
    confidence: float
    volatility_state: str        # "LOW", "MEDIUM", "HIGH", "EXTREME"
    trend_strength: float         # 0.0 to 1.0 (e.g. ADX / 50)
    sizing_multiplier: float      # Section 29 Position Multiplier
    strategy_eligibility: List[str] = field(default_factory=list)
    is_squeeze_transition: bool = False

class MarketRegimeClassifier:
    """
    Classifies macro & micro market states to modulate signal eligibility and position sizing.
    Implements ADX Boundary Hysteresis (Schmitt Trigger) around the 25.0 threshold:
    - Entry hurdle from RANGE/SQUEEZE into TREND/BREAKOUT: ADX >= 25.0
    - Maintenance threshold once established in TREND/BREAKOUT: ADX >= 24.0 (1.0 ADX deadband)
    - Prevents rapid oscillation/flutter between RANGE and BEAR_TREND when ADX hovers between 24.9 and 25.1.
    """

    # Section 29: Baseline multipliers
    SIZING_MULTIPLIERS = {
        MarketRegime.BULL_TREND: 1.00,
        MarketRegime.BEAR_TREND: 1.00,
        MarketRegime.RANGE: 0.70,
        MarketRegime.HIGH_VOLATILITY: 0.50,
        MarketRegime.LOW_VOLATILITY: 0.85,
        MarketRegime.SQUEEZE: 0.60,
        MarketRegime.BREAKOUT: 1.00,
        MarketRegime.TRANSITION: 0.50,
        MarketRegime.UNKNOWN: 0.25,
    }

    def __init__(self, initial_regime: Optional[Union[str, MarketRegime]] = None):
        self.last_regime: Optional[MarketRegime] = None
        if isinstance(initial_regime, str):
            try:
                self.last_regime = MarketRegime(initial_regime)
            except Exception:
                self.last_regime = None
        elif isinstance(initial_regime, MarketRegime):
            self.last_regime = initial_regime

    def evaluate_regime(
        self,
        adx: float = 22.0,
        rsi: float = 50.0,
        ema_fast: float = 100.0,
        ema_slow: float = 100.0,
        bb_width_percentile: float = 50.0,
        atr_percentile: float = 50.0,
        btc_shield_status: str = "CONSOLIDATION",
        is_breakout_candle: bool = False,
        prev_regime: Optional[Union[str, MarketRegime]] = None,
        breakout_is_bull: Optional[bool] = None
    ) -> RegimeEvaluation:
        """
        Synthesizes technical and cross-asset features into definitive market regime.
        Implements ADX Boundary Hysteresis (Schmitt Trigger) around 25.0.
        """
        # Resolve prior regime state
        prior: Optional[MarketRegime] = None
        target_prev = prev_regime if prev_regime is not None else self.last_regime
        if isinstance(target_prev, str):
            try:
                prior = MarketRegime(target_prev)
            except Exception:
                prior = None
        elif isinstance(target_prev, MarketRegime):
            prior = target_prev

        # Dynamic Hysteresis Hurdle:
        # If already established in a trend/breakout regime, maintain down to ADX 24.0.
        # Otherwise require clear ADX >= 25.0 confirmation.
        breakout_adx_hurdle = 24.0 if prior == MarketRegime.BREAKOUT else 25.0
        bull_adx_hurdle = 24.0 if prior == MarketRegime.BULL_TREND else 25.0
        bear_adx_hurdle = 24.0 if prior == MarketRegime.BEAR_TREND else 25.0

        # Trend strength proxy
        trend_strength = round(min(1.0, max(0.0, adx / 50.0)), 2)

        # Volatility state
        if atr_percentile >= 80.0 or bb_width_percentile >= 85.0:
            vol_state = "HIGH"
        elif atr_percentile <= 20.0 or bb_width_percentile <= 20.0:
            vol_state = "LOW"
        else:
            vol_state = "MEDIUM"

        probs = {
            "bull": 0.20,
            "bear": 0.20,
            "range": 0.40,
            "breakout": 0.10,
            "squeeze": 0.10
        }

        # Squeeze Detection: Low volatility compression
        if bb_width_percentile <= 15.0 and adx < 20.0:
            regime = MarketRegime.SQUEEZE
            probs = {"bull": 0.15, "bear": 0.15, "range": 0.20, "breakout": 0.10, "squeeze": 0.40}
            confidence = 0.82
            eligible = [
                "SQUEEZE_BREAKOUT_LONG", "SQUEEZE_BREAKOUT_SHORT",
                "SQUEEZE_EXPANSION_LONG", "SQUEEZE_EXPANSION_SHORT",
                "RANGE_BOUNCE_LONG", "RANGE_BOUNCE_SHORT",
                "ORDER_BLOCK_LONG", "ORDER_BLOCK_SHORT",
                "BREAKER_BLOCK_LONG", "BREAKER_BLOCK_SHORT"
            ]

        # Breakout Detection (with 24.0/25.0 hysteresis)
        elif is_breakout_candle and adx >= breakout_adx_hurdle:
            regime = MarketRegime.BREAKOUT
            is_bull = breakout_is_bull if breakout_is_bull is not None else (ema_fast > ema_slow)
            probs = {"bull": 0.55 if is_bull else 0.10, "bear": 0.10 if is_bull else 0.55, "range": 0.15, "breakout": 0.20, "squeeze": 0.0}
            confidence = 0.85
            eligible = [
                "BREAKOUT_LONG", "BREAKOUT_SHORT",
                "MOMENTUM_LONG", "MOMENTUM_SHORT",
                "SQUEEZE_EXPANSION_LONG", "SQUEEZE_EXPANSION_SHORT",
                "DIRECTIONAL_TREND_LONG", "DIRECTIONAL_TREND_SHORT",
                "ORDER_BLOCK_LONG", "ORDER_BLOCK_SHORT",
                "BREAKER_BLOCK_LONG", "BREAKER_BLOCK_SHORT",
                "BREAKDOWN_SHORT", "SQUEEZE_BREAKOUT_LONG", "SQUEEZE_BREAKOUT_SHORT"
            ]

        # High Volatility
        elif vol_state == "HIGH" and adx > 35.0:
            regime = MarketRegime.HIGH_VOLATILITY
            confidence = 0.78
            eligible = [
                "BLOW_OFF_TOP_SHORT", "LIQUIDITY_SWEEP_LONG", "LIQUIDITY_SWEEP_SHORT",
                "LIQUIDITY_RECLAIM_LONG", "LIQUIDITY_RECLAIM_SHORT",
                "RALLY_FADE_SHORT", "TOP_REVERSAL_SHORT", "BOTTOM_REVERSAL_LONG", "BREAKDOWN_SHORT"
            ]

        # Strong Bull Trend (with 24.0/25.0 hysteresis & smooth probability transition)
        elif ema_fast > ema_slow and adx >= bull_adx_hurdle and rsi > 52.0:
            regime = MarketRegime.BULL_TREND
            if adx < 26.0:
                # Smooth continuous probability blending across boundary [24.0, 26.0]
                t = max(0.0, min(1.0, (adx - 24.0) / 2.0))
                bull_p = round(0.50 + 0.15 * t, 2)
                range_p = round(0.32 - 0.15 * t, 2)
                probs = {"bull": bull_p, "bear": 0.08, "range": range_p, "breakout": 0.10, "squeeze": 0.0}
                confidence = round(0.82 + 0.06 * t, 2)
            else:
                probs = {"bull": 0.65, "bear": 0.08, "range": 0.17, "breakout": 0.10, "squeeze": 0.0}
                confidence = 0.88
            eligible = [
                "MOMENTUM_LONG", "DIP_BUY_LONG", "BREAKOUT_LONG",
                "FVG_RETEST_LONG", "VWAP_BOUNCE_LONG",
                "ORDER_BLOCK_LONG", "BREAKER_BLOCK_LONG",
                "DIRECTIONAL_TREND_LONG", "LIQUIDITY_SWEEP_LONG", "LIQUIDITY_RECLAIM_LONG",
                "BOTTOM_REVERSAL_LONG", "SQUEEZE_BREAKOUT_LONG", "SQUEEZE_EXPANSION_LONG"
            ]

        # Strong Bear Trend (with 24.0/25.0 hysteresis & smooth probability transition)
        elif ema_fast < ema_slow and adx >= bear_adx_hurdle and rsi < 48.0:
            regime = MarketRegime.BEAR_TREND
            if adx < 26.0:
                # Smooth continuous probability blending across boundary [24.0, 26.0]
                t = max(0.0, min(1.0, (adx - 24.0) / 2.0))
                bear_p = round(0.50 + 0.15 * t, 2)
                range_p = round(0.32 - 0.15 * t, 2)
                probs = {"bull": 0.08, "bear": bear_p, "range": range_p, "breakout": 0.10, "squeeze": 0.0}
                confidence = round(0.82 + 0.06 * t, 2)
            else:
                probs = {"bull": 0.08, "bear": 0.65, "range": 0.17, "breakout": 0.10, "squeeze": 0.0}
                confidence = 0.88
            eligible = [
                "MOMENTUM_SHORT", "TOP_REVERSAL_SHORT", "BREAKOUT_SHORT",
                "FVG_RETEST_SHORT", "VWAP_BOUNCE_SHORT",
                "ORDER_BLOCK_SHORT", "BREAKER_BLOCK_SHORT",
                "DIRECTIONAL_TREND_SHORT", "BREAKDOWN_SHORT",
                "RALLY_FADE_SHORT", "LIQUIDITY_SWEEP_SHORT", "LIQUIDITY_RECLAIM_SHORT",
                "BLOW_OFF_TOP_SHORT", "SQUEEZE_EXPANSION_SHORT"
            ]

        # Range / Mean Reversion (Default for crypto 70% of time)
        else:
            regime = MarketRegime.RANGE
            if ema_fast < ema_slow and rsi < 48.0 and adx >= 20.0:
                # Smoothly approach bear trend probability from range
                t = max(0.0, min(1.0, (adx - 20.0) / 5.0))
                bear_p = round(0.17 + 0.25 * t, 2)
                range_p = round(0.55 - 0.25 * t, 2)
                probs = {"bull": 0.18, "bear": bear_p, "range": range_p, "breakout": 0.10, "squeeze": 0.0}
                confidence = 0.80
            elif ema_fast > ema_slow and rsi > 52.0 and adx >= 20.0:
                # Smoothly approach bull trend probability from range
                t = max(0.0, min(1.0, (adx - 20.0) / 5.0))
                bull_p = round(0.18 + 0.24 * t, 2)
                range_p = round(0.55 - 0.24 * t, 2)
                probs = {"bull": bull_p, "bear": 0.17, "range": range_p, "breakout": 0.10, "squeeze": 0.0}
                confidence = 0.80
            else:
                probs = {"bull": 0.18, "bear": 0.17, "range": 0.55, "breakout": 0.10, "squeeze": 0.0}
                confidence = 0.80
            eligible = [
                "MEAN_REVERSION_LONG", "MEAN_REVERSION_SHORT",
                "RANGE_BOUNCE_LONG", "RANGE_BOUNCE_SHORT",
                "LIQUIDITY_SWEEP_LONG", "LIQUIDITY_SWEEP_SHORT",
                "LIQUIDITY_RECLAIM_LONG", "LIQUIDITY_RECLAIM_SHORT",
                "ORDER_BLOCK_LONG", "ORDER_BLOCK_SHORT",
                "BREAKER_BLOCK_LONG", "BREAKER_BLOCK_SHORT",
                "DIP_BUY_LONG", "RALLY_FADE_SHORT",
                "TOP_REVERSAL_SHORT", "BOTTOM_REVERSAL_LONG",
                "SQUEEZE_EXPANSION_LONG", "SQUEEZE_EXPANSION_SHORT",
                "SQUEEZE_BREAKOUT_LONG", "SQUEEZE_BREAKOUT_SHORT"
            ]

        self.last_regime = regime
        sizing_mult = self.SIZING_MULTIPLIERS.get(regime, 0.70)

        # Macro Squeeze Transition to High Volatility:
        # Detect initial expansion bar breaking out of an extended squeeze/compression
        is_squeeze_transition = bool(
            prior in [MarketRegime.SQUEEZE, MarketRegime.LOW_VOLATILITY] and
            regime in [MarketRegime.BREAKOUT, MarketRegime.HIGH_VOLATILITY]
        )
        if is_squeeze_transition:
            # Moderate sizing to 0.65x during the volatile transition bar
            sizing_mult = min(sizing_mult, 0.65)

        return RegimeEvaluation(
            regime=regime,
            probabilities=probs,
            confidence=confidence,
            volatility_state=vol_state,
            trend_strength=trend_strength,
            sizing_multiplier=sizing_mult,
            strategy_eligibility=eligible,
            is_squeeze_transition=is_squeeze_transition
        )


def compute_live_btc_regime(
    data: Union[pd.DataFrame, List[List[Any]]],
    live_btc_price: Optional[float] = None,
    prev_regime: Optional[Union[str, MarketRegime]] = None
) -> Dict[str, Any]:
    """
    Unified quantitative market regime evaluation on BTC 1H klines/DataFrame (Section 28-29 Spec).
    Computes Welles Wilder ADX(14), RSI(14), EMA20, EMA50, BBW %ile, ATR %ile,
    and returns a standardized dictionary matching V16 API and market shield schemas.
    """
    if isinstance(data, pd.DataFrame):
        df = data.iloc[-100:].copy() if len(data) >= 100 else data.copy()
        closes = [float(x) for x in df["close"].values]
        highs = [float(x) for x in df["high"].values]
        lows = [float(x) for x in df["low"].values]
        opens = [float(x) for x in df["open"].values] if "open" in df.columns else closes
    else:
        sub_data = data[-100:] if len(data) >= 100 else data
        closes = [float(k[4]) for k in sub_data]
        highs = [float(k[2]) for k in sub_data]
        lows = [float(k[3]) for k in sub_data]
        opens = [float(k[1]) for k in sub_data]

    if live_btc_price is not None and live_btc_price > 0 and len(closes) > 0:
        closes[-1] = float(live_btc_price)

    n = len(closes)
    if n < 20:
        raise ValueError("Insufficient candle history (min 20) for regime evaluation")

    # Welles Wilder RSI(14)
    gains, losses = [], []
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        gains.append(max(0.0, d))
        losses.append(max(0.0, -d))
    if len(gains) >= 14:
        avg_gain = sum(gains[:14]) / 14.0
        avg_loss = sum(losses[:14]) / 14.0
        for i in range(14, len(gains)):
            avg_gain = (avg_gain * 13.0 + gains[i]) / 14.0
            avg_loss = (avg_loss * 13.0 + losses[i]) / 14.0
    else:
        avg_gain = sum(gains) / max(1, len(gains))
        avg_loss = sum(losses) / max(1, len(losses))
    rs = avg_gain / (avg_loss + 1e-10)
    rsi = round(100.0 - (100.0 / (1.0 + rs)), 1)

    # EMA 20 & 50 over full historical series for continuous convergence
    def calc_ema(s: List[float], period: int) -> float:
        if not s:
            return 0.0
        k = 2.0 / (period + 1.0)
        e = s[0]
        for v in s[1:]:
            e = v * k + e * (1.0 - k)
        return e

    ema_fast = round(calc_ema(closes, 20), 2)
    ema_slow = round(calc_ema(closes, 50), 2)

    # ATR(14) with Welles Wilder smoothing & percentile
    trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])) for i in range(1, n)]
    if len(trs) >= 14:
        cur_atr = sum(trs[:14]) / 14.0
        for i in range(14, len(trs)):
            cur_atr = (cur_atr * 13.0 + trs[i]) / 14.0
        atr_14 = cur_atr
    else:
        atr_14 = sum(trs) / max(1, len(trs))
    atr_pctile = round((sum(1 for t in trs if t <= atr_14) / max(1, len(trs))) * 100.0, 1)

    # Bollinger Band Width (20, 2) & percentile
    all_bbws = []
    for i in range(20, n):
        sub = closes[i - 20:i]
        m = sum(sub) / 20.0
        s = math.sqrt(sum((c - m) ** 2 for c in sub) / 20.0)
        all_bbws.append((4.0 * s) / (m + 1e-10))
    sub_now = closes[-20:]
    m_now = sum(sub_now) / 20.0
    s_now = math.sqrt(sum((c - m_now) ** 2 for c in sub_now) / 20.0)
    cur_bbw = (4.0 * s_now) / (m_now + 1e-10)
    bbw_pctile = round((sum(1 for b in all_bbws if b <= cur_bbw) / max(1, len(all_bbws))) * 100.0, 1)

    # ADX(14) with Welles Wilder canonical smoothing
    tr_list, plus_dm, minus_dm = [], [], []
    for i in range(1, n):
        h, l = highs[i], lows[i]
        ph, pl, pc = highs[i - 1], lows[i - 1], closes[i - 1]
        tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
        um = h - ph
        dm = pl - l
        plus_dm.append(um if (um > dm and um > 0) else 0.0)
        minus_dm.append(dm if (dm > um and dm > 0) else 0.0)

    if len(tr_list) >= 14:
        atr_smooth = sum(tr_list[:14])
        p_smooth = sum(plus_dm[:14])
        m_smooth = sum(minus_dm[:14])
        dx_list = []
        for i in range(14, len(tr_list)):
            atr_smooth = atr_smooth - (atr_smooth / 14.0) + tr_list[i]
            p_smooth = p_smooth - (p_smooth / 14.0) + plus_dm[i]
            m_smooth = m_smooth - (m_smooth / 14.0) + minus_dm[i]
            p_di = (p_smooth / (atr_smooth + 1e-10)) * 100.0
            m_di = (m_smooth / (atr_smooth + 1e-10)) * 100.0
            dx = (abs(p_di - m_di) / (p_di + m_di + 1e-10)) * 100.0
            dx_list.append(dx)

        if len(dx_list) >= 14:
            adx_val = sum(dx_list[:14]) / 14.0
            for i in range(14, len(dx_list)):
                adx_val = (adx_val * 13.0 + dx_list[i]) / 14.0
            adx = round(adx_val, 1)
        elif dx_list:
            adx = round(sum(dx_list) / len(dx_list), 1)
        else:
            adx = 20.0
    else:
        adx = 20.0

    # Directional Body Breakout vs Liquidity Sweep Reclaim:
    # A genuine expansion breakout requires directional close confirmation.
    # Wicks sweeping range extremes that close back in the opposite direction are liquidity sweeps (mean reversion), not breakouts.
    is_high_breakout = (highs[-1] > max(highs[-20:-1])) and (closes[-1] >= opens[-1] or (n >= 2 and closes[-1] > closes[-2]))
    is_low_breakdown = (lows[-1] < min(lows[-20:-1])) and (closes[-1] <= opens[-1] or (n >= 2 and closes[-1] < closes[-2]))
    is_breakout = is_high_breakout or is_low_breakdown
    breakout_is_bull = is_high_breakout if is_breakout else (ema_fast > ema_slow)

    classifier = MarketRegimeClassifier(initial_regime=prev_regime)
    evaluation = classifier.evaluate_regime(
        adx=adx,
        rsi=rsi,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        bb_width_percentile=bbw_pctile,
        atr_percentile=atr_pctile,
        btc_shield_status="NORMAL",
        is_breakout_candle=is_breakout,
        prev_regime=prev_regime,
        breakout_is_bull=breakout_is_bull
    )

    try:
        from app.quant_v16.strategies import StrategyArchetype
        all_strats = [a.value for a in StrategyArchetype]
    except Exception:
        all_strats = [
            "MEAN_REVERSION_LONG", "MEAN_REVERSION_SHORT",
            "RANGE_BOUNCE_LONG", "RANGE_BOUNCE_SHORT",
            "LIQUIDITY_SWEEP_LONG", "LIQUIDITY_SWEEP_SHORT",
            "MOMENTUM_LONG", "MOMENTUM_SHORT",
            "BREAKOUT_LONG", "BREAKOUT_SHORT",
            "DIP_BUY_LONG", "TOP_REVERSAL_SHORT",
            "BOTTOM_REVERSAL_LONG", "BLOW_OFF_TOP_SHORT",
            "SQUEEZE_BREAKOUT_LONG", "SQUEEZE_BREAKOUT_SHORT",
            "ORDER_BLOCK_LONG", "ORDER_BLOCK_SHORT",
            "BREAKER_BLOCK_LONG", "BREAKER_BLOCK_SHORT",
            "BREAKDOWN_SHORT", "RALLY_FADE_SHORT",
            "DIRECTIONAL_TREND_LONG", "DIRECTIONAL_TREND_SHORT"
        ]
    restricted = [s for s in all_strats if s not in evaluation.strategy_eligibility]

    return {
        "status": "success",
        "regime": evaluation.regime.value,
        "confidence": evaluation.confidence,
        "volatility_state": evaluation.volatility_state,
        "trend_strength": evaluation.trend_strength,
        "sizing_multiplier": evaluation.sizing_multiplier,
        "is_squeeze_transition": evaluation.is_squeeze_transition,
        "eligible_strategies": evaluation.strategy_eligibility,
        "restricted_strategies": restricted,
        "probabilities": evaluation.probabilities,
        "metrics": {
            "btc_price": closes[-1],
            "adx": adx,
            "rsi": rsi,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "bb_width_percentile": bbw_pctile,
            "atr_percentile": atr_pctile,
            "btc_shield_status": "NORMAL"
        },
        "capital_preservation_reason": f"Section 29: {evaluation.sizing_multiplier:.2f}x sizing throttle active in {evaluation.regime.value} regime.",
        "updated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    }


def reconcile_btc_shield(shield: Dict[str, Any], v16_regime: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Guarantees 100% authoritative alignment between Quant Edge V16 Market Regime (Section 28-29 Spec)
    and the BTC Predictive Market Beta Shield displayed across Navbar, Terminal, Scanner Matrix, and Paper Bot.
    """
    if not isinstance(shield, dict):
        shield = {}
    if not v16_regime or not isinstance(v16_regime, dict):
        return shield

    v16_reg = v16_regime.get("regime")
    if not v16_reg:
        return shield

    # If an upstream exchange network partition or global outage is active, preserve emergency defensive status
    if shield.get("is_partition_stale") or shield.get("is_global_outage"):
        return shield

    # If an acute systemic flash dump cascade is active, preserve emergency blackout
    curr_status = str(shield.get("status_code", "")).upper()
    curr_reg = str(shield.get("regime", "")).upper()
    if curr_status in ["ALERT_DUMP", "FLASH_DUMP", "BEAR_CASCADE_BLACKOUT"] or curr_reg == "FLASH_DUMP":
        return shield

    # If prolonged multi-day micro-volatility is active, preserve capital preservation NTZ
    if shield.get("is_prolonged_micro_volatility"):
        shield["status_code"] = "NO_TRADE_ZONE"
        shield["regime"] = "RANGE_SQUEEZE"
        shield["regime_label"] = "🛑 PROLONGED MULTI-DAY MICRO-VOLATILITY (NO TRADE ZONE ACTIVE)"
        shield["altcoin_posture"] = "NO_TRADE_ZONE_CAPITAL_PRESERVATION"
        shield["is_ntz_active"] = True
        return shield

    # Synchronize authoritative V16 regime properties
    shield["regime"] = v16_reg
    shield["status_code"] = v16_reg
    shield["predicted_trend"] = v16_reg
    shield["v16_regime"] = v16_reg
    shield["confidence"] = v16_regime.get("confidence", 0.85)
    shield["sizing_multiplier"] = v16_regime.get("sizing_multiplier", 1.0)
    shield["is_squeeze_transition"] = bool(v16_regime.get("is_squeeze_transition") or shield.get("is_squeeze_transition"))

    metrics = v16_regime.get("metrics", {})
    adx_val = metrics.get("adx", 25.0)
    rsi_val = metrics.get("rsi", 50.0)

    if v16_reg == "BEAR_TREND":
        shield["regime_label"] = "🔴 BEAR TREND (SHORT ALPHA AUTHORIZED)"
        shield["altcoin_longs_allowed"] = False
        shield["altcoin_shorts_allowed"] = True
        shield["altcoin_posture"] = "BEAR_TREND_SHORT_ALPHA"
        shield["reason"] = f"BTC confirmed macro bear trend below 1H EMA20/50 (ADX: {adx_val:.1f}, RSI: {rsi_val:.1f}). Short strategies authorized with Section 29 {shield['sizing_multiplier']:.2f}x risk multiplier."
        shield["is_ntz_active"] = False
        shield["active"] = False
        shield["breakout_prediction"] = "🔻 BEARISH MOMENTUM"
    elif v16_reg == "BULL_TREND":
        shield["regime_label"] = "🟢 BULL TREND (BULLISH ALPHA ACTIVE)"
        shield["altcoin_longs_allowed"] = True
        shield["altcoin_shorts_allowed"] = False
        shield["altcoin_posture"] = "AGGRESSIVE_MOMENTUM_LONGS"
        shield["reason"] = f"BTC confirmed macro bull trend above 1H EMA20/50 (ADX: {adx_val:.1f}, RSI: {rsi_val:.1f}). Long continuation setups active with Section 29 {shield['sizing_multiplier']:.2f}x sizing."
        shield["is_ntz_active"] = False
        shield["active"] = False
        shield["breakout_prediction"] = "🚀 BULLISH BREAKOUT"
    elif v16_reg == "BREAKOUT":
        shield["regime_label"] = "🚀 MOMENTUM BREAKOUT ACTIVE"
        shield["altcoin_longs_allowed"] = True
        shield["altcoin_posture"] = "BREAKOUT_ALPHA"
        shield["reason"] = f"BTC high-momentum breakout expansion (ADX: {adx_val:.1f}). Section 29 {shield['sizing_multiplier']:.2f}x sizing active."
        shield["is_ntz_active"] = False
        shield["active"] = False
        shield["breakout_prediction"] = "🚀 BREAKOUT EXPANSION"
    elif v16_reg == "SQUEEZE":
        bbw_pctile = float(metrics.get("bb_width_percentile", 15.0))
        is_dead_flatline = (adx_val < 12.0) or (bbw_pctile <= 3.0)
        shield["regime"] = "RANGE_SQUEEZE"
        shield["predicted_trend"] = "SQUEEZE_COILING"
        shield["breakout_prediction"] = "💤 VOLATILITY SQUEEZE"
        if is_dead_flatline:
            shield["status_code"] = "NO_TRADE_ZONE"
            shield["regime_label"] = "🛑 SEVERE FLATLINE STAGNATION (NO TRADE ZONE ACTIVE)"
            shield["altcoin_longs_allowed"] = False
            shield["altcoin_posture"] = "NO_TRADE_ZONE_CAPITAL_PRESERVATION"
            shield["reason"] = f"NO TRADE ZONE ACTIVE: Severe flatline stagnation (ADX: {adx_val:.1f}, BBW %ile: {bbw_pctile:.0f}%). Capital preservation mode active."
            shield["is_ntz_active"] = True
            shield["active"] = True
        else:
            shield["status_code"] = "SQUEEZE_COILING"
            shield["regime_label"] = "💤 VOLATILITY COMPRESSION (SELECTIVE ALPHA ACTIVE)"
            shield["altcoin_longs_allowed"] = True
            shield["altcoin_posture"] = "SQUEEZE_SELECTIVE_ALPHA"
            shield["sizing_multiplier"] = 0.60
            shield["reason"] = f"BTC in volatility squeeze coiling (ADX: {adx_val:.1f}, BBW %ile: {bbw_pctile:.0f}%). Section 29 0.60x sizing throttle active."
            shield["is_ntz_active"] = False
            shield["active"] = False
    elif v16_reg == "HIGH_VOLATILITY":
        shield["regime_label"] = "⚠️ HIGH VOLATILITY TURBULENCE"
        shield["altcoin_longs_allowed"] = True
        shield["altcoin_posture"] = "REDUCED_LEVERAGE"
        shield["reason"] = f"BTC high volatility expansion (ADX: {adx_val:.1f}). Section 29 {shield['sizing_multiplier']:.2f}x risk throttle active."
        shield["is_ntz_active"] = False
        shield["active"] = False
        shield["breakout_prediction"] = "⚡ TURBULENT VOLATILITY"
    else:  # RANGE
        shield["regime"] = "RANGE"
        shield["status_code"] = "RANGE"
        shield["predicted_trend"] = "CONSOLIDATION"
        shield["regime_label"] = "⚖️ RANGE BOUND / MEAN REVERSION"
        shield["altcoin_longs_allowed"] = True
        shield["altcoin_posture"] = "RANGE_BOUND_MEAN_REVERSION"
        shield["reason"] = f"BTC range-bound within statistical corridor (ADX: {adx_val:.1f}, RSI: {rsi_val:.1f}). Section 29 {shield['sizing_multiplier']:.2f}x sizing throttle active."
        shield["is_ntz_active"] = False
        shield["active"] = False
        shield["breakout_prediction"] = "⚖️ RANGE BOUND"

    if "probabilities" in v16_regime:
        probs = v16_regime["probabilities"]
        shield["bull_trend_prob"] = round(probs.get("bull", 0.08) * 100, 1)
        shield["bear_trend_prob"] = round(probs.get("bear", 0.65) * 100, 1)
        shield["consolidation_prob"] = round(probs.get("range", 0.17) * 100, 1)

    return shield


