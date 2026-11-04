"""
The Only 1 Minute Rectangle Strategy: Master Strategy Orchestrator
Translates the complete methodology from Anees Mehdi's "The Only 1 Minute Trading Strategy"
into an institutional, production-ready, non-repainting signal generation engine.

Produces outputs strictly conforming to the Section 15 JSON schema.
"""

from typing import Dict, Any, Optional, List, Tuple
import time
import pandas as pd

from app.quant_v16.rectangle_strategy.strategy_config import RectangleStrategyConfig
from app.quant_v16.rectangle_strategy.trend_detector import TrendDetector
from app.quant_v16.rectangle_strategy.market_structure import MarketStructureEngine
from app.quant_v16.rectangle_strategy.fvg_detector import FVGDetector
from app.quant_v16.rectangle_strategy.weakness_detector import WeaknessDetector
from app.quant_v16.rectangle_strategy.rectangle_engine import RectangleEngine, DynamicRectangle, RectangleStatus
from app.quant_v16.rectangle_strategy.m1_entry_engine import M1EntryEngine
from app.quant_v16.rectangle_strategy.stop_loss_engine import StopLossEngine
from app.quant_v16.rectangle_strategy.take_profit_engine import TakeProfitEngine
from app.quant_v16.rectangle_strategy.session_filter import SessionFilter
from app.quant_v16.rectangle_strategy.crypto_market_filter import CryptoMarketFilter
from app.quant_v16.rectangle_strategy.signal_scorer import SignalScorer, ScoreBreakdown
from app.quant_v16.entry_confirmation import format_dynamic_precision


class RectangleStrategyOrchestrator:
    """
    Coordinates the multi-timeframe pipeline across M15 structure and M1 entry execution.
    """

    def __init__(self, config: Optional[RectangleStrategyConfig] = None):
        self.config = config or RectangleStrategyConfig()
        self.trend_detector = TrendDetector(self.config)
        self.structure_engine = MarketStructureEngine(self.config)
        self.fvg_detector = FVGDetector(self.config)
        self.weakness_detector = WeaknessDetector(self.config)
        self.rectangle_engine = RectangleEngine(self.config)
        self.m1_entry_engine = M1EntryEngine(self.config)
        self.stop_loss_engine = StopLossEngine(self.config)
        self.take_profit_engine = TakeProfitEngine(self.config)
        self.session_filter = SessionFilter(self.config)
        self.market_filter = CryptoMarketFilter(self.config)
        self.signal_scorer = SignalScorer(self.config)

        # Internal state tracking
        self.last_signal_timestamp: Dict[str, float] = {}

    def scan_for_setups(
        self,
        symbol: str,
        df_m15: pd.DataFrame,
        df_m1: Optional[pd.DataFrame] = None,
        bid_price: Optional[float] = None,
        ask_price: Optional[float] = None,
        funding_rate: float = 0.0,
        m15_bar_idx: int = -1,
        m1_bar_idx: int = -1
    ) -> Dict[str, Any]:
        """
        Executes end-to-end evaluation for a trading pair.
        Returns validated signal dictionary conforming to Section 15 specification.
        """
        rejection_reasons = []

        if not self.config.enabled:
            return self._build_rejected_response(symbol, "Strategy is disabled by administrator")

        if len(df_m15) < max(self.config.ema_slow_period, 35):
            return self._build_rejected_response(symbol, "Insufficient M15 history for market analysis")

        atr_series = TrendDetector.compute_atr(df_m15, period=14)
        n_m15 = len(df_m15)
        eval_m15_idx = n_m15 + m15_bar_idx if m15_bar_idx < 0 else m15_bar_idx
        curr_atr = max(1e-8, float(atr_series.iloc[eval_m15_idx]))

        # ----------------------------------------------------------------------
        # STEP 1: Market Direction (Trend Detector)
        # ----------------------------------------------------------------------
        trend_res = self.trend_detector.evaluate_trend(df_m15, bar_idx=eval_m15_idx)
        if not trend_res.is_aligned:
            rejection_reasons.append(f"Trend not aligned: {trend_res.direction} (Ranging: {trend_res.is_ranging})")
            if trend_res.ranging_reason:
                rejection_reasons.append(trend_res.ranging_reason)

        direction = trend_res.direction # "BULLISH" or "BEARISH"

        # ----------------------------------------------------------------------
        # STEP 2: Market Structure (Swing Points & Continuation Level)
        # ----------------------------------------------------------------------
        struct_res = self.structure_engine.analyze_structure(df_m15, expected_direction=direction, current_bar_idx=eval_m15_idx)
        if not struct_res.is_continuation_supported or struct_res.active_target_level is None:
            rejection_reasons.append(f"No clean continuation structure for {direction} setup (Trend: {struct_res.structure_trend})")

        target_swing = struct_res.active_target_level

        # ----------------------------------------------------------------------
        # STEP 3: M15 Weakness Confirmation (Liquidity Sweep)
        # ----------------------------------------------------------------------
        weakness_res = None
        if target_swing is not None:
            weakness_res = self.weakness_detector.evaluate_m15_confirmation(
                df_m15=df_m15,
                target_swing=target_swing,
                direction=direction,
                atr_value=curr_atr,
                candle_idx=eval_m15_idx
            )
            if not weakness_res.is_confirmed:
                rejection_reasons.append(weakness_res.reason)
        else:
            rejection_reasons.append("Missing confirmed M15 swing target level")

        # ----------------------------------------------------------------------
        # STEP 4: Imbalance / FVG Confluence
        # ----------------------------------------------------------------------
        target_price = target_swing.price if target_swing else float(df_m15['close'].iloc[eval_m15_idx])
        fvg_res = self.fvg_detector.evaluate_confluence(
            df_m15=df_m15,
            target_price=target_price,
            expected_direction=direction,
            atr_value=curr_atr,
            current_bar_idx=eval_m15_idx
        )
        if self.config.fvg_mode.value == "STRICT" and not fvg_res.has_confluence:
            rejection_reasons.append("Mandatory FVG confluence not met in STRICT mode")

        # ----------------------------------------------------------------------
        # STEP 5: Session High / Low Filter
        # ----------------------------------------------------------------------
        session_info = self.session_filter.evaluate_session_confluence(
            target_price=target_price,
            df_m15=df_m15,
            atr_value=curr_atr,
            current_idx=eval_m15_idx
        )

        # ----------------------------------------------------------------------
        # STEP 6: Dynamic Rectangle Generation
        # ----------------------------------------------------------------------
        rectangle = None
        if weakness_res and weakness_res.is_confirmed:
            rectangle = self.rectangle_engine.create_rectangle(
                symbol=symbol,
                weakness=weakness_res,
                df_m15=df_m15
            )

        if rectangle is None:
            rejection_reasons.append("Rectangle could not be generated (Weakness unconfirmed)")

        # ----------------------------------------------------------------------
        # STEP 7: M1 Entry Trigger (Rectangle Flip)
        # ----------------------------------------------------------------------
        m1_trigger = None
        entry_price = 0.0
        signal_ts = str(time.time())

        if rectangle is not None and df_m1 is not None and len(df_m1) > 0:
            m1_trigger = self.m1_entry_engine.evaluate_m1_flip(
                rectangle=rectangle,
                df_m1=df_m1,
                current_m1_idx=m1_bar_idx
            )
            if m1_trigger and m1_trigger.is_triggered:
                entry_price = m1_trigger.trigger_price
                signal_ts = str(m1_trigger.trigger_timestamp)
            else:
                rejection_reasons.append("Awaiting confirmed M1 rectangle flip close outside the box")
        elif df_m1 is None:
            rejection_reasons.append("M1 candle stream not provided for entry evaluation")

        trade_dir = "LONG" if direction == "BULLISH" else "SHORT"

        # ----------------------------------------------------------------------
        # STEP 8: Stop Loss Engine
        # ----------------------------------------------------------------------
        sl_res = None
        if rectangle is not None and entry_price > 0:
            sl_res = self.stop_loss_engine.calculate_stop_loss(
                rectangle=rectangle,
                entry_price=entry_price,
                atr_value=curr_atr
            )
            if not sl_res.is_valid:
                rejection_reasons.append(sl_res.rejection_reason or "Invalid Stop Loss")

        # ----------------------------------------------------------------------
        # STEP 9: Take Profit Engine
        # ----------------------------------------------------------------------
        tp_res = None
        if sl_res and sl_res.is_valid and entry_price > 0:
            tp_res = self.take_profit_engine.calculate_take_profit(
                direction=trade_dir,
                entry_price=entry_price,
                stop_loss_price=sl_res.stop_loss_price,
                opposing_target=struct_res.opposing_target_level
            )
            if not tp_res.is_valid:
                rejection_reasons.append(tp_res.rejection_reason or "Invalid Take Profit / RR")

        # ----------------------------------------------------------------------
        # STEP 10: Crypto Market Filters
        # ----------------------------------------------------------------------
        current_live_p = entry_price if entry_price > 0 else float(df_m15['close'].iloc[eval_m15_idx])
        market_res = self.market_filter.validate_market_conditions(
            df_m15=df_m15,
            current_price=current_live_p,
            bid_price=bid_price,
            ask_price=ask_price,
            funding_rate=funding_rate,
            direction=trade_dir
        )
        if not market_res.passed_filters:
            rejection_reasons.extend(market_res.rejection_reasons)

        # ----------------------------------------------------------------------
        # STEP 11: 100-Point Scoring & Mandatory Condition Gating
        # ----------------------------------------------------------------------
        sweep_pts = weakness_res.sweep_event.sweep_score if (weakness_res and weakness_res.sweep_event) else 0.0
        wick_pts = weakness_res.sweep_event.rejection_strength if (weakness_res and weakness_res.sweep_event) else 0.0
        weak_pts = weakness_res.weakness_score if weakness_res else 0.0
        flip_pts = m1_trigger.m1_flip_score if m1_trigger else 0.0

        has_valid_trend = bool(trend_res.is_aligned)
        has_valid_structure = bool(struct_res.is_continuation_supported)
        has_valid_sweep = bool(weakness_res and weakness_res.sweep_event and weakness_res.sweep_event.is_valid_weakness)
        has_confirmed_weakness = bool(weakness_res and weakness_res.is_confirmed)
        has_valid_rectangle = bool(rectangle is not None)
        has_confirmed_m1_flip = bool(m1_trigger and m1_trigger.is_triggered)
        has_valid_sl = bool(sl_res and sl_res.is_valid)
        has_min_rr = bool(tp_res and tp_res.is_valid)

        score_res = self.signal_scorer.evaluate_score(
            ema_score=trend_res.trend_strength_score,
            structure_score=struct_res.structure_score,
            sweep_score=sweep_pts,
            wick_score=wick_pts,
            weakness_score=weak_pts,
            fvg_score=fvg_res.fvg_score,
            session_score=session_info.session_confluence_score,
            m1_flip_score=flip_pts,
            has_valid_trend=has_valid_trend,
            has_valid_structure=has_valid_structure,
            has_valid_sweep=has_valid_sweep,
            has_confirmed_weakness=has_confirmed_weakness,
            has_valid_rectangle=has_valid_rectangle,
            has_confirmed_m1_flip=has_confirmed_m1_flip,
            has_valid_sl=has_valid_sl,
            has_min_rr=has_min_rr
        )

        if not score_res.mandatory_gates_passed:
            rejection_reasons.extend(score_res.failed_mandatory_gates)

        if score_res.total_score < self.config.min_signal_score:
            rejection_reasons.append(f"Score ({score_res.total_score:.1f}) below threshold {self.config.min_signal_score:.1f}")

        is_valid_signal = (score_res.grade in ("HIGH_QUALITY", "VALID") and len(rejection_reasons) == 0)

        # Signal state update
        if is_valid_signal and rectangle:
            rectangle.status = RectangleStatus.TRADE_TRIGGERED

        # Format output exactly per Section 15 specification
        out = {
            "strategy": self.config.strategy_name,
            "symbol": symbol,
            "exchange": self.config.default_exchange,
            "direction": trade_dir,
            "timeframe_analysis": self.config.timeframe_analysis,
            "entry_timeframe": self.config.entry_timeframe,
            "entry_price": format_dynamic_precision(entry_price) if entry_price > 0 else 0.0,
            "stop_loss": sl_res.stop_loss_price if (sl_res and sl_res.is_valid) else 0.0,
            "take_profit": tp_res.tp1_price if (tp_res and tp_res.is_valid) else 0.0,
            "tp2_price": tp_res.tp2_price if (tp_res and tp_res.is_valid) else 0.0,
            "tp3_price": tp_res.tp3_price if (tp_res and tp_res.is_valid) else 0.0,
            "risk_reward": tp_res.rr_string if (tp_res and tp_res.is_valid) else "1:0",
            "signal_score": score_res.total_score,
            "score_grade": score_res.grade,
            "score_breakdown": score_res.to_dict(),
            "ema_direction": trend_res.direction,
            "market_structure": struct_res.structure_trend,
            "liquidity_sweep": bool(weakness_res and weakness_res.sweep_event and weakness_res.sweep_event.is_valid_weakness),
            "weakness_confirmed": bool(weakness_res and weakness_res.is_confirmed),
            "fvg_confluence": bool(fvg_res.has_confluence),
            "session_confluence": bool(session_info.is_near_session_extreme),
            "active_session": session_info.active_session,
            "rectangle_upper": rectangle.upper_boundary if rectangle else 0.0,
            "rectangle_lower": rectangle.lower_boundary if rectangle else 0.0,
            "rectangle_width": rectangle.width if rectangle else 0.0,
            "confirmation_timestamp": str(weakness_res.confirmation_timestamp) if (weakness_res and weakness_res.is_confirmed) else "",
            "signal_timestamp": signal_ts,
            "estimated_fees": market_res.estimated_fees_pct,
            "estimated_slippage": market_res.estimated_slippage_pct,
            "signal_status": "VALID" if is_valid_signal else "REJECTED",
            "rejection_reasons": rejection_reasons
        }

        return out

    def _build_rejected_response(self, symbol: str, reason: str) -> Dict[str, Any]:
        return {
            "strategy": self.config.strategy_name,
            "symbol": symbol,
            "exchange": self.config.default_exchange,
            "direction": "HOLD_REJECTED",
            "timeframe_analysis": self.config.timeframe_analysis,
            "entry_timeframe": self.config.entry_timeframe,
            "entry_price": 0.0,
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "risk_reward": "1:0",
            "signal_score": 0.0,
            "ema_direction": "NEUTRAL",
            "market_structure": "CHOP",
            "liquidity_sweep": False,
            "weakness_confirmed": False,
            "fvg_confluence": False,
            "session_confluence": False,
            "rectangle_upper": 0.0,
            "rectangle_lower": 0.0,
            "confirmation_timestamp": "",
            "signal_timestamp": str(time.time()),
            "estimated_fees": 0.0,
            "estimated_slippage": 0.0,
            "signal_status": "REJECTED",
            "rejection_reasons": [reason]
        }

