"""
QUANT EDGE V16: 15-Minute Scalp Signal Execution Engine & Pre-AI Gatekeeper
Module: app/quant_v16/signal_engine_15m.py

Specifications:
1. Strict 15-Minute Scalp Execution Horizon Only:
   - Signals generated strictly and exclusively for the 15-Minute (15M) execution horizon.
   - All legacy execution horizons (Intraday, Day Trading, Swings) are stripped from signal generation.
2. Pre-AI Gatekeeper Architecture:
   - Evaluates pure candlestick market structure and Order Block mitigation across 4H, 1H, and 15M
     strictly BEFORE running any AI/ML model inferences.
   - Non-aligned, choppy, or opposing POI setups fail closed immediately.
3. Tactical 15M Structural Entry Anchoring:
   - LONG: Entry strictly anchored to confirmed 15M Higher Low (HL) rejection close or active Bullish OB tap.
     Anti-chase policy: Never buy at 15M Higher High (HH).
   - SHORT: Entry strictly anchored to confirmed 15M Lower High (LH) rejection close or active Bearish OB tap.
     Anti-chase policy: Never short at 15M Lower Low (LL).
4. Strict 1:2 Risk-to-Reward Geometry:
   - Stop Loss: Invalidation anchor minus (Long) or plus (Short) 0.15 * ATR_15m buffer.
   - TP1: Entry +/- 2.0 * Risk (immutable 1:2.0 R:R).
   - Invariant: SL < Entry < TP1 < TP2 < TP3 (Long) | SL > Entry > TP1 > TP2 > TP3 (Short).
5. Seamless Handoff to AI Prediction Models:
   - Delivers validated candidate structural trade to ML model ensemble for probability calibration and net EV hurdle.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Tuple, List
import math
import numpy as np
import pandas as pd

from app.quant_v16.entry_confirmation import format_dynamic_precision
from app.quant_v16.market_structure import (
    MarketStructureEngine,
    PreAIMarketStructureDecision,
    TradeDirection,
    TrendDirection,
    OrderBlockStructure,
    OrderBlockCategory,
)


@dataclass
class ScalpTradeSetup15M:
    symbol: str
    is_valid: bool
    direction: str                  # "LONG", "SHORT", or "NEUTRAL"
    horizon: str = "15M"            # Strictly 15M execution horizon
    execution_mode: str = "RESTING_LIMIT" # "RESTING_LIMIT" or "MARKET_CONFIRMED"
    entry_price: float = 0.0
    sl_price: float = 0.0
    tp1_price: float = 0.0          # Strict 1:2.0 Target
    tp2_price: float = 0.0          # Runner Target (1:3.0)
    tp3_price: float = 0.0          # Extended Target (1:4.0)
    risk_amount: float = 0.0
    risk_reward_ratio: float = 2.0  # Exact 1:2.0
    atr_15m: float = 0.0
    sl_buffer: float = 0.0          # 0.15 * ATR_15m
    entry_zone: List[float] = field(default_factory=list)
    scenario: str = "NO_SIGNAL"     # "SCENARIO_A_ORDER_BLOCK_TRIGGER" or "SCENARIO_B_TREND_ALIGNMENT"
    dominant_ob_timeframe: Optional[str] = None
    has_order_block: bool = False
    order_block_source: str = "TREND_ALIGNMENT_DEFAULT"
    structural_anchor_price: float = 0.0 # 15M HL (Long) or 15M LH (Short)
    invalidation_reason: str = ""
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "is_valid": self.is_valid,
            "direction": self.direction,
            "horizon": self.horizon,
            "execution_mode": self.execution_mode,
            "entry_price": format_dynamic_precision(self.entry_price),
            "sl_price": format_dynamic_precision(self.sl_price),
            "tp1_price": format_dynamic_precision(self.tp1_price),
            "tp2_price": format_dynamic_precision(self.tp2_price),
            "tp3_price": format_dynamic_precision(self.tp3_price),
            "risk_amount": format_dynamic_precision(self.risk_amount),
            "risk_reward_ratio": self.risk_reward_ratio,
            "atr_15m": format_dynamic_precision(self.atr_15m),
            "sl_buffer": format_dynamic_precision(self.sl_buffer),
            "entry_zone": [format_dynamic_precision(p) for p in self.entry_zone],
            "scenario": self.scenario,
            "dominant_ob_timeframe": self.dominant_ob_timeframe,
            "has_order_block": self.has_order_block,
            "order_block_source": self.order_block_source,
            "structural_anchor_price": format_dynamic_precision(self.structural_anchor_price),
            "invalidation_reason": self.invalidation_reason,
            "reasons": self.reasons,
        }


class SignalEngine15M:
    """
    Core 15-Minute Scalp Signal Engine.
    Executes Gate 0 Market Structure Filtering, anchors structural HL/LH entries,
    and enforces strict 1:2 R:R geometry before AI model invocation.
    """

    ATR_SL_MULTIPLIER = 0.15 # 0.15 * ATR buffer below HL / above LH
    MIN_RISK_ATR_RATIO = 0.25 # Minimum risk must be at least 0.25 * ATR to prevent micro-stops
    TARGET_RR = 2.0          # Strict 1:2.0 Risk-to-Reward ratio

    @classmethod
    def calculate_atr_15m(cls, df_15m: pd.DataFrame, period: int = 14) -> float:
        """Calculates dynamic 15M Average True Range (ATR)."""
        if df_15m is None or len(df_15m) < 5:
            return 0.0

        h = df_15m['high'].values.astype(float)
        l = df_15m['low'].values.astype(float)
        c = df_15m['close'].values.astype(float)

        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        if len(tr) < period:
            return float(np.mean(tr)) if len(tr) > 0 else (float(c[-1]) * 0.01)

        return float(np.mean(tr[-period:]))

    @classmethod
    def evaluate_15m_scalp_setup(
        cls,
        symbol: str,
        df_4h: Optional[pd.DataFrame],
        df_1h: Optional[pd.DataFrame],
        df_15m: Optional[pd.DataFrame],
        current_price: Optional[float] = None,
        pre_ai_decision: Optional[PreAIMarketStructureDecision] = None
    ) -> ScalpTradeSetup15M:
        """
        Evaluates and generates a validated 15-Minute Scalp Trade Setup.
        Enforces:
        1. Pre-AI Gatekeeper market structure decision (4H > 1H > 15M).
        2. Structural HL (Long) or LH (Short) entry anchoring.
        3. Strict 1:2 R:R geometry with 0.15 * ATR SL buffer.
        """
        if df_15m is None or len(df_15m) < 15:
            return ScalpTradeSetup15M(
                symbol=symbol,
                is_valid=False,
                direction="NEUTRAL",
                invalidation_reason="Insufficient 15M candle history (< 15 bars)"
            )

        curr_p = current_price if (current_price is not None and current_price > 0) else float(df_15m['close'].iloc[-1])
        atr_15m = cls.calculate_atr_15m(df_15m)
        if atr_15m <= 0:
            atr_15m = curr_p * 0.01

        sl_buffer = atr_15m * cls.ATR_SL_MULTIPLIER

        # ----------------------------------------------------------------------
        # Step 1: Pre-AI Gatekeeper Market Structure Evaluation
        # ----------------------------------------------------------------------
        if pre_ai_decision is not None:
            decision = pre_ai_decision
        else:
            decision = MarketStructureEngine.evaluate_pre_ai_structure(
                df_4h=df_4h,
                df_1h=df_1h,
                df_15m=df_15m,
                current_price=curr_p
            )

        if not decision.is_unanimously_aligned or decision.trade_direction == TradeDirection.NEUTRAL:
            return ScalpTradeSetup15M(
                symbol=symbol,
                is_valid=False,
                direction="NEUTRAL",
                scenario=decision.scenario,
                invalidation_reason=decision.veto_reason or "Market structure not unanimously aligned",
                reasons=decision.reasons
            )

        trade_dir = decision.trade_direction.value # "LONG" or "SHORT"
        reasons = list(decision.reasons)

        # ----------------------------------------------------------------------
        # Step 2: Tactical 15M Entry Anchoring & Anti-Chase Policy
        # ----------------------------------------------------------------------
        prof_15m = decision.profile_15m
        entry_price = curr_p
        sl_price = 0.0
        anchor_price = 0.0
        zone: List[float] = []

        if trade_dir == "LONG":
            # Invalidation floor: confirmed 15M Higher Low or Bullish OB low
            hl_pivot = decision.entry_anchor_pivot
            ob = decision.dominant_order_block if (decision.has_order_block and decision.dominant_order_block and decision.dominant_order_block.block_type == OrderBlockCategory.BULLISH) else None

            if hl_pivot is not None:
                anchor_price = hl_pivot.price
            elif ob is not None:
                anchor_price = ob.ob_low
            else:
                anchor_price = float(df_15m['low'].iloc[-10:].min())

            # If inside active Bullish OB, entry is anchored to the OB zone
            if ob is not None:
                zone_floor = ob.ob_low
                zone_ceiling = ob.ob_high
                structural_floor = min(anchor_price, ob.ob_low)
            else:
                zone_floor = anchor_price
                zone_ceiling = anchor_price + (0.50 * atr_15m)
                structural_floor = anchor_price

            # Anti-chase check: If price has extended above Higher Low zone,
            # execute resting limit near pullback zone rather than chasing at highs
            if curr_p > zone_ceiling:
                execution_mode = "RESTING_LIMIT"
                entry_price = format_dynamic_precision(zone_ceiling)
                reasons.append(f"Price extended above 15M Higher Low zone (${zone_floor:.4f}-${zone_ceiling:.4f}); resting limit placed at entry zone ${entry_price}")
            elif curr_p < zone_floor:
                execution_mode = "RESTING_LIMIT"
                entry_price = format_dynamic_precision(structural_floor)
                reasons.append(f"Price below 15M Higher Low floor (${zone_floor:.4f}); resting limit placed at structural floor ${entry_price}")
            else:
                execution_mode = "MARKET_CONFIRMED"
                entry_price = format_dynamic_precision(curr_p)
                reasons.append(f"Price within 15M Higher Low zone (${zone_floor:.4f}-${zone_ceiling:.4f}); market confirmed entry at ${entry_price}")

            # SL: Structural floor minus 0.15 * ATR buffer
            sl_candidate = structural_floor - sl_buffer
            risk = entry_price - sl_candidate

            # Enforce minimum risk floor to prevent micro-stops
            if risk < (cls.MIN_RISK_ATR_RATIO * atr_15m):
                risk = cls.MIN_RISK_ATR_RATIO * atr_15m
                sl_candidate = entry_price - risk

            sl_price = format_dynamic_precision(sl_candidate)
            risk_amount = entry_price - sl_price

            # TP1: Strict 1:2.0 Risk-to-Reward
            tp1_candidate = entry_price + (cls.TARGET_RR * risk_amount)
            tp1_price = format_dynamic_precision(tp1_candidate)

            # Runner Targets
            tp2_candidate = entry_price + (3.0 * risk_amount)
            tp3_candidate = entry_price + (4.0 * risk_amount)
            tp2_price = format_dynamic_precision(tp2_candidate)
            tp3_price = format_dynamic_precision(tp3_candidate)

            # Strict Price Geometry Assertion
            if not (sl_price < entry_price < tp1_price < tp2_price < tp3_price):
                return ScalpTradeSetup15M(
                    symbol=symbol,
                    is_valid=False,
                    direction="NEUTRAL",
                    invalidation_reason=f"Long geometry invariant violation: SL={sl_price}, Entry={entry_price}, TP1={tp1_price}"
                )

            zone = [format_dynamic_precision(zone_floor), format_dynamic_precision(zone_ceiling)]

        elif trade_dir == "SHORT":
            # Invalidation ceiling: confirmed 15M Lower High or Bearish OB high
            lh_pivot = decision.entry_anchor_pivot
            ob = decision.dominant_order_block if (decision.has_order_block and decision.dominant_order_block and decision.dominant_order_block.block_type == OrderBlockCategory.BEARISH) else None

            if lh_pivot is not None:
                anchor_price = lh_pivot.price
            elif ob is not None:
                anchor_price = ob.ob_high
            else:
                anchor_price = float(df_15m['high'].iloc[-10:].max())

            if ob is not None:
                zone_floor = ob.ob_low
                zone_ceiling = ob.ob_high
                structural_ceiling = max(anchor_price, ob.ob_high)
            else:
                zone_floor = anchor_price - (0.50 * atr_15m)
                zone_ceiling = anchor_price
                structural_ceiling = anchor_price

            # Anti-chase check: If price has extended below Lower High zone,
            # execute resting limit near pullback zone rather than selling at lows
            if curr_p < zone_floor:
                execution_mode = "RESTING_LIMIT"
                entry_price = format_dynamic_precision(zone_floor)
                reasons.append(f"Price extended below 15M Lower High zone (${zone_floor:.4f}-${zone_ceiling:.4f}); resting limit placed at entry zone ${entry_price}")
            elif curr_p > zone_ceiling:
                execution_mode = "RESTING_LIMIT"
                entry_price = format_dynamic_precision(structural_ceiling)
                reasons.append(f"Price above 15M Lower High ceiling (${zone_ceiling:.4f}); resting limit placed at structural ceiling ${entry_price}")
            else:
                execution_mode = "MARKET_CONFIRMED"
                entry_price = format_dynamic_precision(curr_p)
                reasons.append(f"Price within 15M Lower High zone (${zone_floor:.4f}-${zone_ceiling:.4f}); market confirmed entry at ${entry_price}")

            # SL: Structural ceiling plus 0.15 * ATR buffer
            sl_candidate = structural_ceiling + sl_buffer
            risk = sl_candidate - entry_price

            if risk < (cls.MIN_RISK_ATR_RATIO * atr_15m):
                risk = cls.MIN_RISK_ATR_RATIO * atr_15m
                sl_candidate = entry_price + risk

            sl_price = format_dynamic_precision(sl_candidate)
            risk_amount = sl_price - entry_price

            # TP1: Strict 1:2.0 Risk-to-Reward
            tp1_candidate = entry_price - (cls.TARGET_RR * risk_amount)
            tp1_price = format_dynamic_precision(tp1_candidate)

            # Runner Targets
            tp2_candidate = entry_price - (3.0 * risk_amount)
            tp3_candidate = entry_price - (4.0 * risk_amount)
            tp2_price = format_dynamic_precision(tp2_candidate)
            tp3_price = format_dynamic_precision(tp3_candidate)

            # Strict Price Geometry Assertion
            if not (sl_price > entry_price > tp1_price > tp2_price > tp3_price):
                return ScalpTradeSetup15M(
                    symbol=symbol,
                    is_valid=False,
                    direction="NEUTRAL",
                    invalidation_reason=f"Short geometry invariant violation: SL={sl_price}, Entry={entry_price}, TP1={tp1_price}"
                )

            zone = [format_dynamic_precision(zone_floor), format_dynamic_precision(zone_ceiling)]

        else:
            return ScalpTradeSetup15M(
                symbol=symbol,
                is_valid=False,
                direction="NEUTRAL",
                invalidation_reason="Neutral direction"
            )

        rr_ratio = round(abs(tp1_price - entry_price) / max(1e-8, risk_amount), 2)

        return ScalpTradeSetup15M(
            symbol=symbol,
            is_valid=True,
            direction=trade_dir,
            horizon="15M",
            execution_mode=execution_mode,
            entry_price=entry_price,
            sl_price=sl_price,
            tp1_price=tp1_price,
            tp2_price=tp2_price,
            tp3_price=tp3_price,
            risk_amount=format_dynamic_precision(risk_amount),
            risk_reward_ratio=rr_ratio,
            atr_15m=format_dynamic_precision(atr_15m),
            sl_buffer=format_dynamic_precision(sl_buffer),
            entry_zone=zone,
            scenario=decision.scenario,
            dominant_ob_timeframe=decision.dominant_ob_timeframe,
            has_order_block=decision.has_order_block,
            order_block_source=decision.order_block_source,
            structural_anchor_price=format_dynamic_precision(anchor_price),
            invalidation_reason="",
            reasons=reasons
        )

