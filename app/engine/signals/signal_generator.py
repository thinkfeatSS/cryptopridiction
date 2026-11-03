import time
import threading
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple

from app.engine.signals.candle_features import CandleDynamicsFeatureExtractor
from app.engine.signals.ensemble_classifier import FiveModelDirectionClassifier
from app.engine.signals.ensemble_regressor import FiveModelPriceRegressor
from app.engine.signals.per_coin_models import PerCoinModelRegistry
from app.engine.signals.meta_labeler import CoinSpecificMetaLabeler
from app.engine.config import TIMEFRAMES_9, TIMEFRAME_META, ALLOWED_EMISSION_HORIZONS
from app.quant_v16.no_trade_zone import no_trade_zone_engine, NoTradeZoneReason
from app.quant_v16.fractal_consolidation import (
    FractalTimeframeState,
    TimeframeConsolidationProfile,
    FractalConsolidationEngine
)
from app.quant_v16.cross_timeframe_matrix import (
    InstitutionalArchetype,
    CrossTimeframeMatrixEngine
)
from app.quant_v16.order_blocks import (
    InstitutionalOrderBlockEngine,
    order_block_engine,
    OrderBlockRank
)
from app.quant_v16.costs import ExecutionCostEngine, ExecutionAssumption
from app.quant_v16.expectancy import NetExpectancyEngine
from app.quant_v16.probability import PathProbabilities
from app.quant_v16.entry_confirmation import EntryConfirmationEngine, format_dynamic_precision
from app.quant_v16.strategies import StrategyRegistry, StrategyArchetype, StrategyStatus

def map_canonical_strategy(
    raw_strategy: Optional[str],
    direction: str,
    is_ob_setup: bool = False,
    ob_setup: Optional[Dict[str, Any]] = None,
    candle_metrics: Optional[Dict[str, Any]] = None,
    ob_rank: int = 99
) -> str:
    """
    Dynamically maps raw matrix, order block, and candlestick price action setups to authoritative StrategyArchetype enum strings.

    OB Priority Rules (Fix RC-1, RC-2):
      - ob_rank <= 2 (Pristine: Extreme Origin, Decisional BOS): OB label wins unconditionally.
      - ob_rank 3-5 (Lower quality): Candle microstructure pattern gets priority; OB provides structural context only.
      - This ensures FVG, VWAP, Engulfing, Liquidity Sweep strategies can surface for non-pristine OB zones.
    """
    dir_upper = str(direction).upper()
    is_long = dir_upper in ["LONG", "BULLISH", "BUY"]

    # 1. Institutional Order Block — PRISTINE only (Rank 1-2) gets unconditional label priority.
    #    Rank 3-5: fall through to candle microstructure for richer strategy display.
    if is_ob_setup and ob_setup:
        ob_strat = str(ob_setup.get("strategy", "")).upper()
        resolved_ob_rank = int(ob_setup.get("zeiierman_rank", ob_rank))
        if resolved_ob_rank <= 2:
            # Rank 1 (Extreme Origin POI) and Rank 2 (Decisional BOS) — unconditional OB label
            if ob_strat in StrategyArchetype.__members__:
                return ob_strat
            if "BREAKER" in ob_strat:
                return StrategyArchetype.BREAKER_BLOCK_LONG.value if is_long else StrategyArchetype.BREAKER_BLOCK_SHORT.value
            return StrategyArchetype.ORDER_BLOCK_LONG.value if is_long else StrategyArchetype.ORDER_BLOCK_SHORT.value
        # Rank 3-5: Breaker blocks still use OB label; standard blocks fall through to candle pattern
        if "BREAKER" in ob_strat or ob_setup.get("state") == "BREAKER":
            return StrategyArchetype.BREAKER_BLOCK_LONG.value if is_long else StrategyArchetype.BREAKER_BLOCK_SHORT.value
        # For rank 3-5 non-breaker OBs: fall through to candle microstructure detection below

    # 2. Candlestick SMC Microstructure Pattern Priority (now reachable for rank 3-5 OB signals)
    if candle_metrics:
        if candle_metrics.get("is_sweep_reclaim"):
            # Highest candle priority: Liquidity sweep with reclaim is a high-confidence institutional pattern
            return StrategyArchetype.LIQUIDITY_RECLAIM_LONG.value if is_long else StrategyArchetype.LIQUIDITY_RECLAIM_SHORT.value
        if candle_metrics.get("is_range_resistance_rejection") or candle_metrics.get("is_range_support_rejection"):
            return StrategyArchetype.RANGE_BOUNCE_LONG.value if is_long else StrategyArchetype.RANGE_BOUNCE_SHORT.value
        if candle_metrics.get("is_fvg_retest"):
            return StrategyArchetype.FVG_RETEST_LONG.value if is_long else StrategyArchetype.FVG_RETEST_SHORT.value
        if candle_metrics.get("is_vwap_bounce"):
            return StrategyArchetype.VWAP_BOUNCE_LONG.value if is_long else StrategyArchetype.VWAP_BOUNCE_SHORT.value
        if candle_metrics.get("is_engulfing"):
            return StrategyArchetype.MOMENTUM_LONG.value if is_long else StrategyArchetype.MOMENTUM_SHORT.value
        if candle_metrics.get("is_squeeze_expansion"):
            return StrategyArchetype.SQUEEZE_EXPANSION_LONG.value if is_long else StrategyArchetype.SQUEEZE_EXPANSION_SHORT.value

    # 3. For rank 3-5 OB signals where no candle pattern fired, still use OB label as fallback
    if is_ob_setup and ob_setup:
        ob_strat = str(ob_setup.get("strategy", "")).upper()
        if ob_strat in StrategyArchetype.__members__:
            return ob_strat
        return StrategyArchetype.ORDER_BLOCK_LONG.value if is_long else StrategyArchetype.ORDER_BLOCK_SHORT.value

    raw = str(raw_strategy or "").upper().strip()

    # Exact match in StrategyArchetype
    if raw in StrategyArchetype.__members__:
        return raw

    # Keyword mapping — DIRECTIONAL/TREND checked BEFORE EXPANSION to avoid false BREAKOUT routing (Fix RC-4)
    if "FVG" in raw or "FAIR_VALUE" in raw or "IMBALANCE" in raw:
        return StrategyArchetype.FVG_RETEST_LONG.value if is_long else StrategyArchetype.FVG_RETEST_SHORT.value

    if "VWAP" in raw:
        return StrategyArchetype.VWAP_BOUNCE_LONG.value if is_long else StrategyArchetype.VWAP_BOUNCE_SHORT.value

    if "RECLAIM" in raw or "TURTLE" in raw or "JUDAS" in raw:
        return StrategyArchetype.LIQUIDITY_RECLAIM_LONG.value if is_long else StrategyArchetype.LIQUIDITY_RECLAIM_SHORT.value

    if "SQUEEZE_EXPANSION" in raw:
        return StrategyArchetype.SQUEEZE_EXPANSION_LONG.value if is_long else StrategyArchetype.SQUEEZE_EXPANSION_SHORT.value

    # DIRECTIONAL / TREND mapping must precede EXPANSION to correctly route MOMENTUM_TREND_EXPANSION (Fix RC-4)
    # Exception: DIRECTIONAL_BREAKOUT_EXPANSION contains BREAKOUT — let it fall through to BREAKOUT handler
    if ("DIRECTIONAL" in raw or ("TREND" in raw and "COUNTER" not in raw)) and "BREAKOUT" not in raw:
        return StrategyArchetype.DIRECTIONAL_TREND_LONG.value if is_long else StrategyArchetype.DIRECTIONAL_TREND_SHORT.value

    # MOMENTUM_TREND_EXPANSION: explicit matrix strategy key → DIRECTIONAL_TREND
    if raw in ("MOMENTUM_TREND_EXPANSION", "MOMENTUM_EXPANSION"):
        return StrategyArchetype.DIRECTIONAL_TREND_LONG.value if is_long else StrategyArchetype.DIRECTIONAL_TREND_SHORT.value

    if "BREAKOUT" in raw or "EXPANSION" in raw:
        if "SQUEEZE" in raw or "COILING" in raw:
            return StrategyArchetype.SQUEEZE_BREAKOUT_LONG.value if is_long else StrategyArchetype.SQUEEZE_BREAKOUT_SHORT.value
        if not is_long and "BREAKDOWN" in raw:
            return StrategyArchetype.BREAKDOWN_SHORT.value
        return StrategyArchetype.BREAKOUT_LONG.value if is_long else StrategyArchetype.BREAKOUT_SHORT.value

    if "MEAN_REVERSION" in raw or "RANGE" in raw or "ROTATION" in raw or "SUPPORT" in raw or "RESISTANCE" in raw:
        return StrategyArchetype.RANGE_BOUNCE_LONG.value if is_long else StrategyArchetype.RANGE_BOUNCE_SHORT.value

    if "DIP" in raw:
        return StrategyArchetype.DIP_BUY_LONG.value
    if "TOP" in raw or "BLOW_OFF" in raw:
        return StrategyArchetype.BLOW_OFF_TOP_SHORT.value if "BLOW_OFF" in raw else StrategyArchetype.TOP_REVERSAL_SHORT.value
    if "RALLY" in raw or "FADE" in raw:
        return StrategyArchetype.RALLY_FADE_SHORT.value

    if "LIQUIDITY" in raw or "SWEEP" in raw:
        return StrategyArchetype.LIQUIDITY_SWEEP_LONG.value if is_long else StrategyArchetype.LIQUIDITY_SWEEP_SHORT.value

    return StrategyArchetype.MOMENTUM_LONG.value if is_long else StrategyArchetype.MOMENTUM_SHORT.value

class SignalGenerationSystem:
    """
    Subsystem 2 Coordinator: Multi-Horizon Signal Generation System.
    - Evaluates 9 timeframes for each asset with strictly separate models per coin.
    - Learns from Bull/Bear candle streaks, volume dynamics, and volatility dynamics.
    - Executes 5 Top Classifiers to vote next candle direction (Green Bullish vs Red Bearish).
    - Executes 5 Top Regressors to predict target price (selected by higher votes).
    - Dedicated PerCoinModelRegistry: Persists coin-specific classifiers and regressors to disk.
    - Dedicated CoinSpecificMetaLabeler: Evaluates secondary P(Win) using each coin's own meta-model.
    - Gates setups via Institutional No Trade Zone (NTZ), BTC Market Shield, and Coin Meta-Labeler.
    - Resolves multi-horizon dominance to emit qualified trade signals strictly for 15M, 1H, and 24H.
    """

    def __init__(self):
        self.feature_extractor = CandleDynamicsFeatureExtractor()
        self.model_registry = PerCoinModelRegistry()
        self.meta_labeler = CoinSpecificMetaLabeler()
        self.cost_engine = ExecutionCostEngine()
        self.expectancy_engine = NetExpectancyEngine()
        self.strategy_registry = StrategyRegistry()
        self._model_cache: Dict[str, Tuple[Any, Any, float, int]] = {}  # key -> (clfs, regs, fit_ts, last_candle_ts)
        self._cache_lock = threading.RLock()

    @staticmethod
    def is_macro_no_trade_zone(btc_shield_state: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
        """
        Determines whether macro market conditions trigger an institutional No Trade Zone.
        When active, signal generation is locked and paper trading bot entries are halted.
        """
        if not btc_shield_state:
            return False, ""
        if btc_shield_state.get("is_ntz_active"):
            return True, btc_shield_state.get("reason", "BTC Macro Volatility Squeeze / Blackout Active")
        if btc_shield_state.get("status_code") == "NO_TRADE_ZONE":
            return True, btc_shield_state.get("reason", "BTC Macro Squeeze No Trade Zone Active")
        if "NO_TRADE_ZONE" in str(btc_shield_state.get("altcoin_posture", "")):
            return True, btc_shield_state.get("reason", "Altcoin Posture: No Trade Zone Capital Preservation")
        if btc_shield_state.get("regime") == "FLASH_DUMP" or btc_shield_state.get("status_code") == "BEAR_CASCADE_BLACKOUT":
            return True, btc_shield_state.get("reason", "Critical BTC Flash Dump Blackout Active")
        if "DEFENSIVE_CASH_ONLY" in str(btc_shield_state.get("altcoin_posture", "")):
            return True, btc_shield_state.get("reason", "BTC Flash Dump: Defensive Cash Only Posture")
        return False, ""

    def _get_timeframe_ttl(self, tf: str, active_atr_pct: Optional[float] = None) -> float:
        ttls = {
            "5m": 90.0,     # 1.5 min
            "15m": 240.0,   # 4 min
            "1h": 1200.0,   # 20 min
            "4h": 3600.0,   # 1 hour
            "12h": 7200.0,  # 2 hours
            "1d": 14400.0,  # 4 hours
            "1w": 28800.0,  # 8 hours
            "15d": 43200.0, # 12 hours
            "1M": 86400.0   # 24 hours
        }
        base_ttl = ttls.get(tf, 120.0)
        # SIG-02: Volatility-conditioned dynamic timeframe TTL
        if active_atr_pct is not None and active_atr_pct > 0:
            vol_multiplier = float(np.clip(1.50 / max(0.50, active_atr_pct), 0.40, 1.25))
            return round(base_ttl * vol_multiplier, 1)
        return base_ttl

    def _build_single_horizon_signal(
        self,
        symbol: str,
        horizon_label: str,
        tf_key: str,
        direction: str,
        current_price: float,
        dfs_9: Dict[str, pd.DataFrame],
        horizon_prediction: Optional[Dict[str, Any]],
        btc_shield_state: Dict[str, Any],
        aligned_horizons: List[str],
        archetype_info: Optional[Dict[str, Any]] = None,
        order_block_setup: Optional[Dict[str, Any]] = None,
        volume_24h_usd: float = 0.0,
        bid_price: float = 0.0,
        ask_price: float = 0.0,
        spread_bps: float = 5.0,
        fundamental_matrix: Optional[Dict[str, Any]] = None,
        alignment_score: float = 100.0
    ) -> Dict[str, Any]:
        """
        Builds a dedicated institutional trade signal for a single qualified horizon:
        15M (Scalp), 1H (Intraday Swing), or 24H (Daily Swing).
        """
        is_ob_setup = bool(order_block_setup and order_block_setup.get("setup_detected"))
        if is_ob_setup:
            ob_dir = order_block_setup.get("direction", direction)
            direction = ob_dir

        alt_longs_allowed = btc_shield_state.get("altcoin_longs_allowed", True)
        alt_shorts_allowed = btc_shield_state.get("altcoin_shorts_allowed", True)
        is_vetoed = (direction == "LONG" and not alt_longs_allowed) or (direction == "SHORT" and not alt_shorts_allowed)

        # 1. Macro No Trade Zone Check
        is_macro_ntz, macro_ntz_reason = self.is_macro_no_trade_zone(btc_shield_state)

        # Dynamic ATR for this specific horizon
        df_active = dfs_9.get(tf_key) if dfs_9 else None
        if df_active is not None and len(df_active) >= 14:
            active_atr = float(np.mean(np.maximum(
                df_active["high"].values[-14:] - df_active["low"].values[-14:], 1e-10
            )))
        else:
            active_atr = current_price * (0.01 if tf_key == "15m" else (0.02 if tf_key == "1h" else 0.04))

        # ---------------------------------------------------------------------
        # 1. Candlestick Price Action Trigger & Entry Zone Confirmation FIRST
        # ---------------------------------------------------------------------
        is_candle_confirmed, candle_trigger_reason, candle_metrics = EntryConfirmationEngine.validate_candle_trigger(
            df=df_active,
            direction=direction,
            current_price=current_price,
            spread_bps=spread_bps
        )

        # Archetype Adjustments (Headroom & Range Extremes)
        arch_type = archetype_info.get("archetype", InstitutionalArchetype.ARCHETYPE_A_SECULAR_EXPANSION.value) if archetype_info else InstitutionalArchetype.ARCHETYPE_A_SECULAR_EXPANSION.value
        arch_strategy = archetype_info.get("strategy", "MOMENTUM_TREND_EXPANSION") if archetype_info else "MOMENTUM_TREND_EXPANSION"
        arch_alloc = archetype_info.get("allocation_pct", 100.0) if archetype_info else 100.0
        arch_headroom = archetype_info.get("headroom_pct", 0.0) if archetype_info else 0.0

        # ---------------------------------------------------------------------
        # 2. Canonical Strategy Resolution & Section 31/32 Kill Switch
        # ---------------------------------------------------------------------
        # Extract OB rank for strategy resolution (Fix RC-1: only rank 1-2 OBs win label unconditionally)
        ob_rank_val = int(order_block_setup.get("zeiierman_rank", 99)) if order_block_setup else 99
        canonical_strategy = map_canonical_strategy(
            arch_strategy, direction,
            is_ob_setup=is_ob_setup, ob_setup=order_block_setup,
            candle_metrics=candle_metrics, ob_rank=ob_rank_val
        )
        active_market_regime = str(btc_shield_state.get("v16_regime") or btc_shield_state.get("regime") or "RANGE").upper()
        is_strat_allowed, strat_veto_reason = self.strategy_registry.is_strategy_allowed(canonical_strategy, current_regime=active_market_regime)
        is_shadow_eligible, shadow_reason = (False, None)
        if not is_strat_allowed and hasattr(self.strategy_registry, "is_strategy_shadow_eligible"):
            is_shadow_eligible, shadow_reason = self.strategy_registry.is_strategy_shadow_eligible(canonical_strategy, current_regime=active_market_regime)

        # Turtle Soup / Liquidity Reclaim exemption from broad BTC shield long vetoes
        is_liquidity_reclaim = bool(
            (is_ob_setup and order_block_setup and (
                order_block_setup.get("is_turtle_soup") or
                "TURTLE_SOUP" in str(order_block_setup.get("strategy", "")).upper() or
                "LIQUIDITY_RECLAIM" in str(canonical_strategy).upper()
            )) or (candle_metrics and candle_metrics.get("is_sweep_reclaim"))
        )
        if direction == "LONG" and not alt_longs_allowed and is_liquidity_reclaim:
            is_vetoed = False

        # Section 35 Floor Headroom Guard for SHORT entries:
        # If shorting near macro range support with insufficient headroom (< 1.20 * active_atr),
        # veto the short to avoid entering directly into the demand floor.
        if direction == "SHORT" and archetype_info:
            htf_low = float(archetype_info.get("htf_range_low") or 0.0)
            if htf_low > 0 and current_price > htf_low:
                avail_headroom = current_price - htf_low
                if avail_headroom < (1.20 * active_atr):
                    is_vetoed = True
                    strat_veto_reason = f"Insufficient headroom to 1D Range Floor ({avail_headroom:.4f} < {1.20*active_atr:.4f})"
                    is_strat_allowed = False

        # ---------------------------------------------------------------------
        # 2b. Asset-Level No Trade Zone Check on active timeframe with strategy context
        # ---------------------------------------------------------------------
        ntz_eval = no_trade_zone_engine.evaluate_asset_ntz(
            df=df_active,
            current_price=current_price,
            anchor_tf=tf_key,
            btc_shield_info=btc_shield_state,
            stats_24h={"quoteVolume": volume_24h_usd} if (volume_24h_usd and volume_24h_usd > 0) else None,
            ob_setup=order_block_setup,
            alignment_score=float(alignment_score),
            meta_win_prob=float(horizon_prediction.get("consensus_probability", 0.55)) if horizon_prediction else 0.55,
            direction=direction,
            decision=canonical_strategy
        )
        is_asset_ntz = ntz_eval.get("is_ntz", False)

        # In micro-volatility / macro squeeze, hold back on middle chop to preserve capital,
        # but allow validated structural boundary touches and coiling breakout setups
        is_macro_dump = (
            btc_shield_state.get("regime") == "FLASH_DUMP" or
            btc_shield_state.get("status_code") in ["BEAR_CASCADE_BLACKOUT", "ALERT_DUMP", "FLASH_DUMP"] or
            "DEFENSIVE_CASH_ONLY" in str(btc_shield_state.get("altcoin_posture", ""))
        )
        is_boundary_or_coiling = bool(
            is_ob_setup or
            any(k in str(canonical_strategy).upper() for k in [
                "ORDER_BLOCK", "BREAKER", "TURTLE_SOUP", "RANGE_SUPPORT",
                "RANGE_RESISTANCE", "SUB_RANGE", "COILING", "EXPANSION", "BREAKOUT", "RANGE_BOUNCE"
            ])
        )

        effective_macro_ntz = is_macro_ntz
        if is_macro_ntz and not is_macro_dump and is_boundary_or_coiling:
            effective_macro_ntz = False

        is_ntz_active = effective_macro_ntz or is_asset_ntz
        ntz_reason = macro_ntz_reason if effective_macro_ntz else (
            ntz_eval.get("reasons", ["Asset in No Trade Zone"])[0] if ntz_eval.get("reasons") else "Asset in No Trade Zone"
        )

        # ---------------------------------------------------------------------
        # 3. Determine optimal entry limit and execution entry price
        # ---------------------------------------------------------------------
        entry_analysis = EntryConfirmationEngine.calculate_optimal_entry_zone(
            current_price=current_price,
            ob_setup=order_block_setup if is_ob_setup else None,
            direction=direction,
            active_atr=active_atr,
            chase_threshold_pct=0.40,
            strategy=canonical_strategy,
            candle_metrics=candle_metrics
        )
        exec_entry_price = float(entry_analysis["optimal_entry_price"])

        # ---------------------------------------------------------------------
        # 4. Anchor Profit Targets and Stop Loss to authoritative execution price
        # ---------------------------------------------------------------------
        if is_ob_setup:
            cand_tp1 = format_dynamic_precision(order_block_setup["tp1_price"])
            cand_tp2 = format_dynamic_precision(order_block_setup["tp2_price"])
            cand_tp3 = format_dynamic_precision(order_block_setup["tp3_price"])
            cand_sl = format_dynamic_precision(order_block_setup["sl_price"])

            # Guarantee strict price invariants against exec_entry_price
            if direction == "LONG":
                if cand_sl >= exec_entry_price:
                    cand_sl = format_dynamic_precision(exec_entry_price - (active_atr * 1.2))
                if cand_tp1 <= exec_entry_price:
                    cand_tp1 = format_dynamic_precision(exec_entry_price + (active_atr * 1.5))
                if cand_tp2 <= cand_tp1:
                    cand_tp2 = format_dynamic_precision(cand_tp1 + (active_atr * 1.0))
                if cand_tp3 <= cand_tp2:
                    cand_tp3 = format_dynamic_precision(cand_tp2 + (active_atr * 1.5))
            else: # SHORT
                if cand_sl <= exec_entry_price:
                    cand_sl = format_dynamic_precision(exec_entry_price + (active_atr * 1.2))
                if cand_tp1 >= exec_entry_price:
                    cand_tp1 = format_dynamic_precision(max(exec_entry_price * 0.001, exec_entry_price - (active_atr * 1.5)))
                if cand_tp2 >= cand_tp1:
                    cand_tp2 = format_dynamic_precision(max(exec_entry_price * 0.001, cand_tp1 - (active_atr * 1.0)))
                if cand_tp3 >= cand_tp2:
                    cand_tp3 = format_dynamic_precision(max(exec_entry_price * 0.001, cand_tp2 - (active_atr * 1.5)))

            actual_rr = round(abs(cand_tp2 - exec_entry_price) / max(1e-9, abs(exec_entry_price - cand_sl)), 2)
            cand_rr = f"1:{actual_rr:.1f}"
        elif direction == "LONG":
            # Phase 4C: Volatility-adjusted dynamic target scaling (BBW scale factor)
            bbw_val = 3.0
            if df_active is not None and len(df_active) >= 20:
                try:
                    c20 = df_active['close'].iloc[-20:].astype(float)
                    ma20 = float(c20.mean())
                    std20 = float(c20.std(ddof=0))
                    if ma20 > 0:
                        bbw_val = ((2.0 * std20 * 2.0) / ma20) * 100.0
                except Exception:
                    bbw_val = 3.0

            is_range_regime = any(k in str(active_market_regime).upper() for k in ["RANGE", "CONSOLIDATION", "CHOP", "SIDEWAYS"])
            if is_range_regime:
                tp1_mult = 1.30 * (0.85 if bbw_val <= 1.50 else 1.00)
                tp2_mult = 2.40 * (0.85 if bbw_val <= 1.50 else 1.00)
                tp3_mult = 3.80 * (0.85 if bbw_val <= 1.50 else 1.00)
            elif bbw_val <= 1.50:
                tp1_mult = 1.70
                tp2_mult = 2.975
                tp3_mult = 4.675
            elif bbw_val >= 4.50 and active_market_regime in ["TREND", "BULLISH", "BEARISH"]:
                tp1_mult = 2.50
                tp2_mult = 4.375
                tp3_mult = 6.875
            else:
                tp1_mult = 2.00
                tp2_mult = 3.50
                tp3_mult = 5.50

            cand_tp1 = format_dynamic_precision(exec_entry_price + (active_atr * tp1_mult))
            cand_tp2 = format_dynamic_precision(exec_entry_price + (active_atr * tp2_mult))
            cand_tp3 = format_dynamic_precision(exec_entry_price + (active_atr * tp3_mult))
            cand_sl = format_dynamic_precision(max(exec_entry_price * 0.001, exec_entry_price - (active_atr * 1.2)))
            actual_rr = round(abs(cand_tp2 - exec_entry_price) / max(1e-9, abs(exec_entry_price - cand_sl)), 2)
            cand_rr = f"1:{actual_rr:.1f}"
        else: # SHORT
            bbw_val = 3.0
            if df_active is not None and len(df_active) >= 20:
                try:
                    c20 = df_active['close'].iloc[-20:].astype(float)
                    ma20 = float(c20.mean())
                    std20 = float(c20.std(ddof=0))
                    if ma20 > 0:
                        bbw_val = ((2.0 * std20 * 2.0) / ma20) * 100.0
                except Exception:
                    bbw_val = 3.0

            is_range_regime = any(k in str(active_market_regime).upper() for k in ["RANGE", "CONSOLIDATION", "CHOP", "SIDEWAYS"])
            if is_range_regime:
                tp1_mult = 1.30 * (0.85 if bbw_val <= 1.50 else 1.00)
                tp2_mult = 2.40 * (0.85 if bbw_val <= 1.50 else 1.00)
                tp3_mult = 3.80 * (0.85 if bbw_val <= 1.50 else 1.00)
            elif bbw_val <= 1.50:
                tp1_mult = 1.70
                tp2_mult = 2.975
                tp3_mult = 4.675
            elif bbw_val >= 4.50 and active_market_regime in ["TREND", "BULLISH", "BEARISH"]:
                tp1_mult = 2.50
                tp2_mult = 4.375
                tp3_mult = 6.875
            else:
                tp1_mult = 2.00
                tp2_mult = 3.50
                tp3_mult = 5.50

            cand_tp1 = format_dynamic_precision(max(exec_entry_price * 0.001, exec_entry_price - (active_atr * tp1_mult)))
            cand_tp2 = format_dynamic_precision(max(exec_entry_price * 0.001, exec_entry_price - (active_atr * tp2_mult)))
            cand_tp3 = format_dynamic_precision(max(exec_entry_price * 0.001, exec_entry_price - (active_atr * tp3_mult)))
            cand_sl = format_dynamic_precision(exec_entry_price + (active_atr * 1.2))
            actual_rr = round(abs(cand_tp2 - exec_entry_price) / max(1e-9, abs(exec_entry_price - cand_sl)), 2)
            cand_rr = f"1:{actual_rr:.1f}"

        if arch_type == InstitutionalArchetype.ARCHETYPE_C_RANGE_ROTATION.value:
            # Cap TP1, TP2, and TP3 dynamically within the HTF Range Extreme to prevent running into iron wall
            # while preserving strictly monotonic target spacing: entry < TP1 < TP2 < TP3 <= htf_high
            if direction == "LONG" and archetype_info.get("htf_range_high"):
                htf_high = float(archetype_info["htf_range_high"])
                if htf_high > exec_entry_price:
                    avail_span = htf_high - exec_entry_price
                    cand_tp3 = min(cand_tp3, format_dynamic_precision(htf_high))
                    cand_tp2 = min(cand_tp2, format_dynamic_precision(exec_entry_price + (avail_span * 0.85)))
                    cand_tp1 = min(cand_tp1, format_dynamic_precision(exec_entry_price + (avail_span * 0.60)))
                    actual_rr = round(abs(cand_tp2 - exec_entry_price) / max(1e-9, abs(exec_entry_price - cand_sl)), 2)
                    cand_rr = f"1:{actual_rr:.1f}"
            elif direction == "SHORT" and archetype_info.get("htf_range_low"):
                htf_low = float(archetype_info["htf_range_low"])
                if htf_low < exec_entry_price:
                    avail_span = exec_entry_price - htf_low
                    cand_tp3 = max(cand_tp3, format_dynamic_precision(htf_low))
                    cand_tp2 = max(cand_tp2, format_dynamic_precision(exec_entry_price - (avail_span * 0.85)))
                    cand_tp1 = max(cand_tp1, format_dynamic_precision(exec_entry_price - (avail_span * 0.60)))
                    actual_rr = round(abs(cand_tp2 - exec_entry_price) / max(1e-9, abs(exec_entry_price - cand_sl)), 2)
                    cand_rr = f"1:{actual_rr:.1f}"

        # Evaluate setup against this coin's dedicated Meta-Labeler
        cand_meta_payload = {
            "symbol": symbol,
            "horizon": horizon_label,
            "direction": direction,
            "entry_price": exec_entry_price,
            "tp1_price": cand_tp1,
            "sl_price": cand_sl,
            "conviction": 95.0 if horizon_label == "24H" else (90.0 if horizon_label == "1H" else 85.0),
            "expected_return_pct": abs(horizon_prediction["predicted_change_pct"]) if horizon_prediction else 0.0,
            "quality_grade": "Grade A+",
            "regime": active_market_regime,
            "market_regime": active_market_regime,
            "canonical_strategy": canonical_strategy,
            "chop_index": float(candle_metrics.get("chop_index", 50.0) if candle_metrics else 50.0)
        }
        # Phase 4B: Dynamic Meta Hurdle mathematically scaled to actual R:R
        # Hurdle = max(0.44, min(0.65, ((1.0 + friction) / (1.0 + actual_rr)) * 1.15))
        est_friction = (float(spread_bps) / 10000.0) * 2.0 + 0.0010
        target_safety_margin = 1.15
        breakeven_p = (1.0 + est_friction) / max(1.0, 1.0 + actual_rr)
        meta_hurdle = round(max(0.44, min(0.65 if horizon_label != "24H" else 0.60, breakeven_p * target_safety_margin)), 3)
        meta_eval = self.meta_labeler.evaluate_signal(symbol, cand_meta_payload, hurdle=meta_hurdle)

        # ---------------------------------------------------------------------
        # Execution Friction & Net Mathematical Expectancy Gating
        # ---------------------------------------------------------------------
        base_win_p = float(meta_eval.get("win_probability", 0.75))
        p_tp1 = max(0.15, min(0.95, base_win_p))
        p_tp2 = round(p_tp1 * 0.65, 3)
        p_tp3 = round(p_tp2 * 0.55, 3)
        p_sl = round(max(0.05, 1.0 - p_tp1), 3)

        path_probs = PathProbabilities(
            p_tp1=p_tp1,
            p_tp2=p_tp2,
            p_tp3=p_tp3,
            p_sl=p_sl,
            p_tp2_given_tp1=0.65,
            p_tp3_given_tp2=0.55,
            risk_reward=actual_rr
        )

        holding_hours = 0.25 if horizon_label == "15M" else (1.0 if horizon_label == "1H" else 24.0)

        # EXT-02: Non-Linear Liquidity Market Impact Slippage
        vol_24h_usd = None
        if "1d" in dfs_9 and not dfs_9["1d"].empty and "volume" in dfs_9["1d"].columns:
            last_vol = float(dfs_9["1d"]["volume"].iloc[-1])
            vol_24h_usd = last_vol * current_price if current_price > 0 else None

        cost_breakdown = self.cost_engine.estimate_costs(
            market_type="futures",
            observed_spread_bps=spread_bps,
            est_holding_hours=holding_hours,
            current_funding_rate=0.0001,
            assumption=ExecutionAssumption.BASE,
            position_size_usd=1000.0,
            volume_24h_usd=vol_24h_usd
        )

        ev_result = self.expectancy_engine.evaluate(
            entry=entry_analysis["optimal_entry_price"],
            sl=cand_sl,
            tp1=cand_tp1,
            tp2=cand_tp2,
            tp3=cand_tp3,
            direction=direction,
            path_probs=path_probs,
            costs=cost_breakdown
        )

        # ---------------------------------------------------------------------
        # Fundamental & Breaking News Sentiment Integration
        # ---------------------------------------------------------------------
        fund_matrix = fundamental_matrix
        has_severe_negative_news = False
        has_severe_positive_news = False
        is_sell_the_news = False
        is_pre_event = False
        news_score = 0.0
        news_label = "⚪ NEUTRAL"
        news_headline = ""
        cat_title = ""

        is_macro_blackout = False
        macro_blackout_reason = ""
        if fund_matrix:
            cat_ev = fund_matrix.get("catalyst_event", {})
            news_sent = fund_matrix.get("news_sentiment", {})
            macro_ev = fund_matrix.get("macro_economic_event", {})
            has_severe_negative_news = bool(fund_matrix.get("has_severe_negative_news", False) or news_sent.get("has_severe_negative_news", False))
            has_severe_positive_news = bool(fund_matrix.get("has_severe_positive_news", False) or (float(news_sent.get("score", 0.0)) >= 0.50))
            is_sell_the_news = bool(cat_ev.get("is_sell_the_news_danger_zone", False))
            is_pre_event = bool(cat_ev.get("is_pre_event_runup", False))
            news_score = float(news_sent.get("score", 0.0))
            news_label = news_sent.get("label", "⚪ NEUTRAL")
            news_headline = news_sent.get("top_headline") or (news_sent.get("recent_headlines", ["Negative News"])[0] if news_sent.get("recent_headlines") else "Negative News Alert")
            cat_title = cat_ev.get("title", "Catalyst Event")
            is_macro_blackout = bool(macro_ev.get("is_volatility_pause_active", False))
            macro_blackout_reason = macro_ev.get("pause_reason", "US Macro Release Blackout Active")

        # News & Event Gating (Black Swan Sentinel & NWS-01 Macro Blackout)
        is_news_vetoed = False
        news_veto_reason = ""
        if is_macro_blackout:
            # Blackout halts both LONG and SHORT setups during high-impact US macro release
            is_news_vetoed = True
            news_veto_reason = f"🚨 {macro_blackout_reason}"
        elif direction == "LONG":
            if has_severe_negative_news or news_score <= -0.40:
                is_news_vetoed = True
                news_veto_reason = f"🚨 Black Swan / Negative News Sentinel ({news_label}): {news_headline[:60]}"
            elif is_sell_the_news:
                # If within 12h of catalyst execution, sell-the-news danger is high
                is_news_vetoed = True
                news_veto_reason = f"⚠️ Sell-The-News Danger Zone: <12h to {cat_title[:50]}"
        elif direction == "SHORT":
            if has_severe_positive_news or news_score >= 0.50:
                is_news_vetoed = True
                news_veto_reason = f"🚨 Hyper-Bullish News Sentinel ({news_label}): {news_headline[:60]}"
            elif is_pre_event:
                # If in pre-event catalyst accumulation window, shorting is dangerous
                is_news_vetoed = True
                news_veto_reason = f"⚠️ Pre-Catalyst Accumulation Runup: <10d to {cat_title[:50]}"

        # Intraday Flash Liquidity Drain & Dynamic Spread Gating
        is_flash_drain = False
        flash_drain_reason = ""
        max_allowed_spread = 20.0 if horizon_label == "15M" else (28.0 if horizon_label == "1H" else 35.0)
        if float(spread_bps) > max_allowed_spread:
            is_flash_drain = True
            flash_drain_reason = f"Flash spread blowout ({spread_bps:.1f} bps > {max_allowed_spread:.1f} bps limit)"
        elif candle_metrics and candle_metrics.get("is_flash_liquidity_drain"):
            is_flash_drain = True
            flash_drain_reason = str(candle_metrics.get("flash_drain_reason", "Acute volume vacuum on trigger bar"))
        elif df_active is not None and "volume" in df_active.columns and len(df_active) >= 10:
            try:
                hist_v = df_active["volume"].iloc[:-1] if len(df_active) >= 2 else df_active["volume"]
                base_v = float(hist_v.iloc[-20:].mean()) if len(hist_v) >= 5 else 0.0
                curr_v = float(df_active["volume"].iloc[-1])
                curr_to = curr_v * current_price
                if base_v > 0 and (curr_v / base_v < 0.12):
                    is_flash_drain = True
                    flash_drain_reason = f"Acute volume collapse ({curr_v/base_v:.2f}x avg < 0.12x)"
                elif 0 < curr_to < 5000.0:
                    is_flash_drain = True
                    flash_drain_reason = f"Sub-threshold turnover (${curr_to:,.0f} < $5,000 on candle)"
            except Exception:
                is_flash_drain = False

        if volume_24h_usd and 0 < volume_24h_usd < 1_000_000.0:
            status = "HOLD_VETOED_BY_SUB_THRESHOLD_ILLIQUIDITY"
            trade_active = False
            grade = f"Grade C (SUB-THRESHOLD ILLIQUIDITY: ${volume_24h_usd/1e6:.2f}M < $1.00M minimum volume)"
            conviction = 0.0
            tp1_price = cand_tp1
            tp2_price = cand_tp2
            tp3_price = cand_tp3
            sl_price = cand_sl
            rr_ratio = cand_rr
        elif is_flash_drain:
            status = "HOLD_VETOED_BY_FLASH_LIQUIDITY_DRAIN"
            trade_active = False
            grade = f"Grade C (FLASH LIQUIDITY DRAIN: {flash_drain_reason})"
            conviction = 0.0
            tp1_price = cand_tp1
            tp2_price = cand_tp2
            tp3_price = cand_tp3
            sl_price = cand_sl
            rr_ratio = cand_rr
        elif is_ntz_active:
            status = "HOLD_VETOED_BY_NO_TRADE_ZONE"
            trade_active = False
            grade = f"Grade C (NO TRADE ZONE ACTIVE: {ntz_reason})"
            conviction = 0.0
            tp1_price = cand_tp1
            tp2_price = cand_tp2
            tp3_price = cand_tp3
            sl_price = cand_sl
            rr_ratio = cand_rr
        elif is_vetoed:
            status = "HOLD_VETOED_BY_BTC_SHIELD"
            trade_active = False
            grade = "Grade C (BTC MARKET SHIELD VETO)"
            conviction = 0.0
            tp1_price = cand_tp1
            tp2_price = cand_tp2
            tp3_price = cand_tp3
            sl_price = cand_sl
            rr_ratio = cand_rr
        elif is_news_vetoed:
            status = "HOLD_VETOED_BY_NEGATIVE_NEWS"
            trade_active = False
            grade = f"Grade C (NEWS SENTINEL VETO: {news_veto_reason})"
            conviction = 0.0
            tp1_price = cand_tp1
            tp2_price = cand_tp2
            tp3_price = cand_tp3
            sl_price = cand_sl
            rr_ratio = cand_rr
        elif not is_strat_allowed:
            status = "HOLD_VETOED_BY_REGIME_STRATEGY_KILL_SWITCH"
            trade_active = False
            grade = f"Grade C (SECTION 32 REGIME KILL SWITCH: {strat_veto_reason})"
            conviction = 0.0
            tp1_price = cand_tp1
            tp2_price = cand_tp2
            tp3_price = cand_tp3
            sl_price = cand_sl
            rr_ratio = cand_rr
        elif float(spread_bps) > 35.0:
            status = "HOLD_FILTERED_BY_EXCESSIVE_SPREAD"
            trade_active = False
            grade = f"Grade C (EXCESSIVE SPREAD: {spread_bps:.1f} bps > 35.0 bps limit)"
            conviction = max(40.0, float(meta_eval.get("win_probability_pct", 65.0)) * 0.6)
            tp1_price = cand_tp1
            tp2_price = cand_tp2
            tp3_price = cand_tp3
            sl_price = cand_sl
            rr_ratio = cand_rr
        elif not meta_eval["passed_meta_gate"]:
            status = "HOLD_FILTERED_BY_COIN_META_LABELER"
            trade_active = False
            grade = f"Grade C (COIN META-LABELER VETO: P(Win)={meta_eval['win_probability_pct']}%)"
            conviction = float(meta_eval["win_probability_pct"])
            tp1_price = cand_tp1
            tp2_price = cand_tp2
            tp3_price = cand_tp3
            sl_price = cand_sl
            rr_ratio = cand_rr
        elif not is_candle_confirmed:
            status = "HOLD_AWAITING_CANDLE_TRIGGER_CONFIRMATION"
            trade_active = False
            grade = f"Grade C (AWAITING CANDLE TRIGGER: {candle_trigger_reason})"
            conviction = float(meta_eval.get("win_probability_pct", 65.0))
            tp1_price = cand_tp1
            tp2_price = cand_tp2
            tp3_price = cand_tp3
            sl_price = cand_sl
            rr_ratio = cand_rr
        elif not ev_result.passes_ev_hurdle:
            status = "HOLD_FILTERED_BY_NEGATIVE_NET_EXPECTANCY" if ev_result.expected_net_return_pct <= 0.0 else "HOLD_UNFAVORABLE_RISK_REWARD"
            trade_active = False
            grade = f"Grade C ({ev_result.decision_reason})"
            conviction = float(meta_eval.get("win_probability_pct", 65.0))
            tp1_price = cand_tp1
            tp2_price = cand_tp2
            tp3_price = cand_tp3
            sl_price = cand_sl
            rr_ratio = cand_rr
        else:
            status = "ACTIVE_SIGNAL"
            trade_active = True
            if is_ob_setup:
                rank_lbl = order_block_setup.get("zeiierman_rank_label", "INSTITUTIONAL SMC POI")
                resolved_ob_rank_for_grade = int(order_block_setup.get("zeiierman_rank", 99))
                if resolved_ob_rank_for_grade <= 2:
                    # Pristine OB (Rank 1-2): OB is the dominant signal — full OB grade label
                    grade = f"💎 Grade A+ ({rank_lbl} RETEST)"
                    conviction = max(88.0, float(order_block_setup.get("conviction", 92.0)))
                else:
                    # Rank 3-5 OB: Candle pattern drives strategy; OB provides structural zone context
                    candle_pattern_name = candle_metrics.get("pattern", "") if candle_metrics else ""
                    if candle_pattern_name:
                        grade = f"⚡ Grade A+ ({candle_pattern_name} @ {rank_lbl})"
                    else:
                        grade = f"⚡ Grade A+ ({canonical_strategy} @ {rank_lbl})"
                    conviction = max(84.0, float(order_block_setup.get("conviction", 88.0)) - 2.0)
                arch_strategy = canonical_strategy
            elif arch_strategy == "DIRECTIONAL_BREAKOUT_EXPANSION":
                conviction = 92.0
                grade = f"🚀 Grade A+ (DIRECTIONAL BREAKOUT EXPANSION: Macro Range Breakout in {direction} Direction)"
                arch_strategy = canonical_strategy
            elif arch_type == InstitutionalArchetype.ARCHETYPE_B_COILING_BREAKOUT.value:
                conviction = 88.0
                grade = f"⚡ Grade A+ (COILING BREAKOUT: 15M Squeeze into 1D {direction} Expansion)"
                arch_strategy = canonical_strategy
            elif arch_type == InstitutionalArchetype.ARCHETYPE_C_RANGE_ROTATION.value:
                conviction = 84.0
                grade = f"⚖️ Grade A (RANGE ROTATION: 1D Range Mean Reversion to {arch_headroom:.1f}% Boundary)"
                arch_strategy = canonical_strategy
            elif horizon_label == "24H":
                conviction = 95.0
                grade = "💎 Grade A+ (24H STRICT 7-HORIZON ALIGNMENT: 15M-15D UNANIMOUS)"
                arch_strategy = canonical_strategy
            elif horizon_label == "1H":
                conviction = 90.0
                grade = "🔥 Grade A+ (1H STRICT 7-HORIZON ALIGNMENT: 5M-7D UNANIMOUS)"
                arch_strategy = canonical_strategy
            else: # 15M
                conviction = 85.0
                grade = "⚡ Grade A (15M STRICT 6-HORIZON ALIGNMENT: 5M-24H UNANIMOUS)"
                arch_strategy = canonical_strategy

            # Apply Fundamental Conviction Delta & Catalyst Boosting
            if fund_matrix:
                f_delta = float(fund_matrix.get("conviction_delta", 0.0))
                if direction == "LONG":
                    if is_pre_event:
                        conviction = min(98.0, conviction + max(6.0, f_delta))
                        grade += f" 🚀 [EVENT DRIFT: {cat_title[:18]}]"
                    elif news_score >= 0.30:
                        conviction = min(98.0, conviction + max(4.0, f_delta))
                        grade += " 📰 [CATALYST CONFIRMED]"
                    elif news_score <= -0.20:
                        conviction = max(60.0, conviction + min(-6.0, f_delta))
                elif direction == "SHORT":
                    if news_score <= -0.30 or has_severe_negative_news:
                        conviction = min(98.0, conviction + 6.0)
                        grade += " ⚡ [SHORT MOMENTUM: NEGATIVE CATALYST ALIGNED]"

            tp1_price = cand_tp1
            tp2_price = cand_tp2
            tp3_price = cand_tp3
            sl_price = cand_sl
            rr_ratio = cand_rr

        # Zero-distance & price geometry invariant guard (Section 4.2 AGENTS.md)
        if trade_active:
            if exec_entry_price <= 0.0001 or sl_price <= 0.0001 or tp1_price <= 0.0001:
                trade_active = False
                status = "REJECTED_ZERO_PRICE"
            elif abs(exec_entry_price - sl_price) <= 1e-8:
                trade_active = False
                status = "REJECTED_ZERO_DISTANCE_SL"
            elif direction == "LONG" and not (sl_price < exec_entry_price < tp1_price < tp2_price < tp3_price):
                trade_active = False
                status = "REJECTED_PRICE_GEOMETRY"
            elif direction == "SHORT" and not (sl_price > exec_entry_price > tp1_price > tp2_price > tp3_price):
                trade_active = False
                status = "REJECTED_PRICE_GEOMETRY"

        pred_target = horizon_prediction["predicted_target_price"] if horizon_prediction else current_price
        pred_pct = abs(horizon_prediction["predicted_change_pct"]) if horizon_prediction else 0.0

        if trade_active and entry_analysis["is_limit_pending"]:
            decision_str = f"🎯 {direction} RESTING LIMIT (AWAIT PULLBACK)" if direction == "LONG" else f"🎯 {direction} RESTING LIMIT (AWAIT BOUNCE)"
        elif is_ob_setup and order_block_setup.get("decision"):
            decision_str = order_block_setup.get("decision")
        else:
            decision_str = f"🟢 BUY {horizon_label}" if direction == "LONG" else f"🔴 SELL {horizon_label}"

        # TRD-01: Idiosyncratic Coin Beta & Volatility Parity Sizing (Section 29)
        coin_atr_pct = (active_atr / max(1e-8, current_price)) * 100.0 if current_price > 0 else 1.5
        btc_atr_pct = float(btc_shield_state.get("atr_pct") or btc_shield_state.get("btc_atr_pct") or 1.8)
        coin_beta = round(float(np.clip(coin_atr_pct / max(0.20, btc_atr_pct), 0.40, 3.50)), 2)
        beta_sizing_mult = float(np.clip(1.0 / coin_beta, 0.40, 1.25))

        base_fund_sizing = float((fund_matrix.get("sizing_multiplier") if fund_matrix else 1.0) or 1.0)
        shield_sizing = float(btc_shield_state.get("sizing_multiplier", 1.0) or 1.0)
        effective_sizing = round(float(np.clip(base_fund_sizing * shield_sizing * beta_sizing_mult, 0.20, 1.30)), 2)

        return {
            "symbol": symbol,
            "horizon": horizon_label,
            "horizon_key": tf_key,
            "horizon_tag": f"{horizon_label} {'SCALP' if horizon_label == '15M' else ('INTRADAY SWING' if horizon_label == '1H' else 'DAILY SWING')}",
            "direction": direction if (not is_vetoed and not is_ntz_active) else "HOLD_VETOED",
            "dominant_direction": direction if (not is_vetoed and not is_ntz_active) else "HOLD_VETOED",
            "dominant_timeframe": horizon_label,
            "decision": decision_str,
            "is_trade_active": trade_active,
            "signal_status": status,
            "is_macro_blackout": is_macro_blackout,
            "macro_economic_event": fund_matrix.get("macro_economic_event") if fund_matrix else None,
            "is_ntz_active": is_ntz_active,
            "ntz_reason": ntz_reason if is_ntz_active else None,
            "ntz_badge": ntz_eval.get("badge", "NO TRADE ZONE") if is_ntz_active else "TRADE ZONE APPROVED",
            "ntz_metrics": ntz_eval.get("metrics", {}),
            "expansion_readiness": btc_shield_state.get("expansion_readiness") if btc_shield_state else None,
            "current_price": current_price,
            "entry_price": entry_analysis["optimal_entry_price"],
            "optimal_entry_price": entry_analysis["optimal_entry_price"],
            "optimal_entry_limit": entry_analysis["optimal_entry_limit"],
            "entry_zone_min": entry_analysis["entry_zone_min"],
            "entry_zone_max": entry_analysis["entry_zone_max"],
            "is_limit_pending": entry_analysis["is_limit_pending"],
            "entry_mode": entry_analysis["entry_mode"],
            "chase_warning": entry_analysis["chase_warning"],
            "candle_trigger_confirmed": is_candle_confirmed,
            "candle_trigger_reason": candle_trigger_reason,
            "candle_trigger_metrics": candle_metrics,
            "ev_net": ev_result.expected_net_return_pct,
            "ev_gross": ev_result.ev_gross_pct,
            "costs_total_pct": ev_result.costs_total_pct,
            "cost_breakdown": {
                "fee_pct": cost_breakdown.fee_pct,
                "spread_pct": cost_breakdown.spread_pct,
                "slippage_pct": cost_breakdown.slippage_pct,
                "funding_pct": cost_breakdown.funding_pct,
                "total_cost_pct": cost_breakdown.total_cost_pct
            },
            "passes_ev_hurdle": ev_result.passes_ev_hurdle,
            "ev_decision_reason": ev_result.decision_reason,
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
            "tp3_price": tp3_price,
            "sl_price": sl_price,
            "risk_reward_ratio": rr_ratio,
            "expected_return_pct": pred_pct,
            "predicted_target_price": pred_target,
            "conviction": conviction,
            "quality_grade": grade,
            "classifier_votes": horizon_prediction.get("classifier_votes") if horizon_prediction else "",
            "regressor_votes": horizon_prediction.get("regressor_votes") if horizon_prediction else "",
            "aligned_horizons": aligned_horizons,
            "aligned_trend": "BULLISH" if direction == "LONG" else "BEARISH",
            "meta_win_probability": meta_eval["win_probability"],
            "meta_win_probability_pct": meta_eval["win_probability_pct"],
            "meta_win_prob": meta_eval["win_probability"],
            "meta_win_prob_pct": meta_eval["win_probability_pct"],
            "win_probability_pct": meta_eval["win_probability_pct"],
            "win_prob": meta_eval["win_probability_pct"],
            "path_probabilities": {
                "tp1": round(path_probs.p_tp1 * 100.0, 1),
                "tp2": round(path_probs.p_tp2 * 100.0, 1),
                "tp3": round(path_probs.p_tp3 * 100.0, 1),
                "sl": round(path_probs.p_sl * 100.0, 1)
            },
            "p_tp1_pct": round(path_probs.p_tp1 * 100.0, 1),
            "p_tp2_pct": round(path_probs.p_tp2 * 100.0, 1),
            "p_tp3_pct": round(path_probs.p_tp3 * 100.0, 1),
            "p_sl_pct": round(path_probs.p_sl * 100.0, 1),
            "meta_passed": meta_eval["passed_meta_gate"],
            "meta_verdict": meta_eval["meta_verdict"],
            "meta_model_type": meta_eval["model_type"],
            "meta_sample_size": meta_eval["sample_size"],
            "per_coin_models_active": True,
            "archetype": arch_type,
            "strategy": canonical_strategy,
            "canonical_strategy": canonical_strategy,
            "raw_strategy": arch_strategy,
            "is_strategy_allowed": is_strat_allowed,
            "strategy_veto_reason": strat_veto_reason if not is_strat_allowed else None,
            "is_shadow_eligible": is_shadow_eligible,
            "shadow_veto_reason": shadow_reason,
            "active_regime": active_market_regime,
            "allocation_pct": arch_alloc,
            "headroom_pct": arch_headroom,
            "btc_shield_status": btc_shield_state.get("status_code", "NORMAL"),
            "order_block_setup": order_block_setup,
            "is_order_block_signal": is_ob_setup,
            "zeiierman_rank": order_block_setup.get("zeiierman_rank") if order_block_setup else None,
            "zeiierman_rank_label": order_block_setup.get("zeiierman_rank_label") if order_block_setup else None,
            "is_nested_smc": bool(order_block_setup.get("is_nested_smc", False)) if order_block_setup else False,
            "htf_poi_tf": order_block_setup.get("htf_poi_tf") if order_block_setup else None,
            "optimal_entry_limit": entry_analysis["optimal_entry_limit"],
            "mean_threshold_price": entry_analysis["optimal_entry_limit"],
            "order_block_zone": order_block_setup.get("order_block_zone") if order_block_setup else None,
            "evaluated_at_utc": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "volume_24h_usd": volume_24h_usd,
            "bid_price": bid_price if bid_price > 0 else current_price,
            "ask_price": ask_price if ask_price > 0 else current_price,
            "spread_bps": spread_bps,
            "fundamental_matrix": fund_matrix,
            "news_sentiment": fund_matrix.get("news_sentiment") if fund_matrix else None,
            "catalyst_event": fund_matrix.get("catalyst_event") if fund_matrix else None,
            "active_atr": active_atr,
            "coin_beta": coin_beta,
            "sizing_multiplier": effective_sizing,
            "composite_fundamental_score": fund_matrix.get("composite_fundamental_score", 0.0) if fund_matrix else 0.0,
            "wait_reason": news_veto_reason if is_news_vetoed else (strat_veto_reason if not is_strat_allowed else (candle_trigger_reason if not is_candle_confirmed else (ev_result.decision_reason if not ev_result.passes_ev_hurdle else None)))
        }

    @classmethod
    def compute_trend_alignment(
        cls,
        horizon_predictions: Dict[str, Dict[str, Any]],
        matrix_eval: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Calculates multi-horizon trend alignment across 9 horizons (5M -> 1M)
        using institutional quantitative horizon weights.
        Consolidation represents the absence of directional trend and yields 0.0% alignment.
        """
        if matrix_eval is None:
            matrix_eval = {}

        trend_matrix = {tf: horizon_predictions[tf].get("trend_state", "CONSOLIDATION") for tf in horizon_predictions}
        bull_horizons = [tf for tf, st in trend_matrix.items() if st == "BULLISH"]
        bear_horizons = [tf for tf, st in trend_matrix.items() if st == "BEARISH"]
        chop_horizons = [tf for tf, st in trend_matrix.items() if st == "CONSOLIDATION"]
        total_horizons = len(trend_matrix)

        # Quantitative Institutional Horizon Weightings (Core active trading vs macro horizons)
        # 15M, 1H, 4H, 12H, 1D constitute 80% of trend decision weight.
        HORIZON_WEIGHTS = {
            "5m": 0.08,
            "15m": 0.14,
            "1h": 0.20,
            "4h": 0.20,
            "12h": 0.14,
            "1d": 0.12,
            "1w": 0.06,
            "15d": 0.04,
            "1M": 0.02
        }

        # Calculate dynamic weighted directional momentum
        total_weight = sum(HORIZON_WEIGHTS.get(tf, 1.0 / max(1, total_horizons)) for tf in trend_matrix) or 1.0
        w_bull = sum(HORIZON_WEIGHTS.get(tf, 1.0 / max(1, total_horizons)) for tf in bull_horizons) / total_weight
        w_bear = sum(HORIZON_WEIGHTS.get(tf, 1.0 / max(1, total_horizons)) for tf in bear_horizons) / total_weight
        w_chop = sum(HORIZON_WEIGHTS.get(tf, 1.0 / max(1, total_horizons)) for tf in chop_horizons) / total_weight

        # Directional Trend Qualification:
        # A directional trend requires bull/bear dominance over opposing direction and >= 33% weighted strength (or >= 4 raw horizons)
        if w_bull > w_bear and (w_bull >= 0.33 or len(bull_horizons) >= 4):
            dominant_trend = "BULLISH"
            aligned_count = len(bull_horizons)
            dominant_direction = "LONG"
            alignment_score_pct = round(w_bull * 100.0, 1)
            alignment_ratio = f"{aligned_count}/{total_horizons}"
        elif w_bear > w_bull and (w_bear >= 0.33 or len(bear_horizons) >= 4):
            dominant_trend = "BEARISH"
            aligned_count = len(bear_horizons)
            dominant_direction = "SHORT"
            alignment_score_pct = round(w_bear * 100.0, 1)
            alignment_ratio = f"{aligned_count}/{total_horizons}"
        else:
            dominant_trend = "CONSOLIDATION"
            aligned_count = len(chop_horizons)
            dominant_direction = "CONSOLIDATION"
            # Consolidation represents absence of directional trend alignment
            alignment_score_pct = 0.0
            alignment_ratio = f"{aligned_count}/{total_horizons}"

        is_unanimous = (
            (len(bull_horizons) == total_horizons or len(bear_horizons) == total_horizons)
            and total_horizons >= 7
        )

        if is_unanimous:
            alignment_tier = f"💎 TIER 1: UNANIMOUS {total_horizons}/{total_horizons} SECULAR SUPER-TREND ({dominant_trend})"
        elif dominant_trend in ["BULLISH", "BEARISH"] and aligned_count >= 7:
            alignment_tier = f"🔥 TIER 2: HIGH {alignment_ratio} MULTI-HORIZON CONFLUENCE ({dominant_trend})"
        elif dominant_trend in ["BULLISH", "BEARISH"] and aligned_count >= 4:
            alignment_tier = f"⚡ TIER 3: MODERATE {alignment_ratio} DIRECTIONAL SKEW ({dominant_trend})"
        else:
            alignment_tier = f"⚠️ TIER 4: FRAGMENTED / CHOPPY CONSOLIDATION ({alignment_ratio})"

        return {
            "dominant_trend": dominant_trend,
            "dominant_direction": dominant_direction,
            "alignment_score_pct": alignment_score_pct,
            "aligned_horizons_count": aligned_count,
            "total_horizons_count": total_horizons,
            "alignment_ratio": alignment_ratio,
            "alignment_tier": alignment_tier,
            "is_unanimous_9_of_9": is_unanimous,
            "bullish_horizons_count": len(bull_horizons),
            "bearish_horizons_count": len(bear_horizons),
            "consolidation_horizons_count": len(chop_horizons),
            "bullish_horizons": bull_horizons,
            "bearish_horizons": bear_horizons,
            "consolidation_horizons": chop_horizons,
            "trend_matrix": trend_matrix,
            # Institutional Archetype Extensions
            "cross_timeframe_matrix": matrix_eval,
            "archetype": matrix_eval.get("archetype"),
            "strategy_playbook": matrix_eval.get("strategy"),
            "allocation_pct": matrix_eval.get("allocation_pct", 0.0),
            "headroom_pct": matrix_eval.get("headroom_pct", 0.0),
            "matrix_rationale": matrix_eval.get("rationale", "")
        }

    @classmethod
    def evaluate_multi_horizon_gates(
        cls,
        trend_matrix: Dict[str, str],
        horizon_predictions: Dict[str, Dict[str, Any]],
        matrix_eval: Dict[str, Any],
        ob_setup_15m: Optional[Dict[str, Any]] = None,
        ob_setup_1h: Optional[Dict[str, Any]] = None,
        ob_setup_24h: Optional[Dict[str, Any]] = None,
        has_smc_15m: bool = False,
        smc_dir_15m: Optional[str] = None,
        has_smc_1h: bool = False,
        smc_dir_1h: Optional[str] = None,
        has_smc_24h: bool = False,
        smc_dir_24h: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """
        Evaluates discrete multi-horizon qualification gates for 15M Scalp, 1H Intraday, and 24H Swing.
        Enforces Elder's Triple Screen hierarchical confluence triads and prevents cold-start altcoins
        from being permanently locked out of intraday setups.
        Permits confirmed institutional triggers (Order Blocks and SMC setups) to execute even inside macro ranges.
        """
        has_ob_15m = bool(ob_setup_15m and ob_setup_15m.get("setup_detected"))
        has_ob_1h = bool(ob_setup_1h and ob_setup_1h.get("setup_detected"))
        has_ob_24h = bool(ob_setup_24h and ob_setup_24h.get("setup_detected"))

        is_coiling_breakout = bool(
            matrix_eval.get("archetype") == InstitutionalArchetype.ARCHETYPE_B_COILING_BREAKOUT.value and
            matrix_eval.get("trade_permitted")
        )
        is_range_rotation = bool(
            matrix_eval.get("archetype") == InstitutionalArchetype.ARCHETYPE_C_RANGE_ROTATION.value and
            matrix_eval.get("trade_permitted")
        )
        is_breakout_expansion = bool(
            matrix_eval.get("strategy") == "DIRECTIONAL_BREAKOUT_EXPANSION" and
            matrix_eval.get("trade_permitted")
        )
        is_middle_chop_veto = bool(
            matrix_eval.get("strategy") == "CAPITAL_PRESERVATION_MIDDLE_CHOP_VETO"
        )
        matrix_trade_permitted = bool(matrix_eval.get("trade_permitted", True))

        # -----------------------------------------------------------------
        # 1. 15M Scalp Gate (Empirical accumulation required: 15M [3.75h] & 5M [1.25h])
        # Desk: 15M Scalp. Anchor: 1H. Trigger: 5M.
        # -----------------------------------------------------------------
        req_15m = ["5m", "15m", "1h", "4h", "12h", "1d"]
        emp_req_15m = ["5m", "15m"]
        cold_start_tfs_15m = [
            tf for tf in emp_req_15m
            if horizon_predictions.get(tf, {}).get("is_cold_start", False) or
               horizon_predictions.get(tf, {}).get("candle_count", 99) < 15
        ]
        converged_tfs_15m = [tf for tf in req_15m if not horizon_predictions.get(tf, {}).get("is_cold_start", False)]
        trends_15m = [trend_matrix.get(tf, "CONSOLIDATION") for tf in req_15m]
        bull_cnt_15m = sum(1 for t in trends_15m if t == "BULLISH")
        bear_cnt_15m = sum(1 for t in trends_15m if t == "BEARISH")

        # Phase 4A Elder's Triple Screen Decoupling: Anchor = 1H, Context = 15M, Trigger = 5M
        desk_bull_cnt_15m = sum(1 for tf in ["5m", "15m", "1h"] if trend_matrix.get(tf) == "BULLISH")
        desk_bear_cnt_15m = sum(1 for tf in ["5m", "15m", "1h"] if trend_matrix.get(tf) == "BEARISH")

        is_15m_bull = (
            (len(converged_tfs_15m) >= 2 and all(trend_matrix.get(tf) == "BULLISH" for tf in converged_tfs_15m))
            or (
                trend_matrix.get("15m") == "BULLISH"
                and trend_matrix.get("1h") != "BEARISH"
                and desk_bear_cnt_15m == 0
                and (desk_bull_cnt_15m >= 2 or bull_cnt_15m >= 3)
                and bear_cnt_15m <= 1
            )
        )
        is_15m_bear = (
            (len(converged_tfs_15m) >= 2 and all(trend_matrix.get(tf) == "BEARISH" for tf in converged_tfs_15m))
            or (
                trend_matrix.get("15m") == "BEARISH"
                and trend_matrix.get("1h") != "BULLISH"
                and desk_bull_cnt_15m == 0
                and (desk_bear_cnt_15m >= 2 or bear_cnt_15m >= 3)
                and bull_cnt_15m <= 1
            )
        )

        has_valid_institutional_trigger_15m = bool(
            (has_ob_15m and ob_setup_15m.get("zeiierman_rank", 99) <= 3) or has_smc_15m or is_coiling_breakout
        )

        q_15m_qualified = bool(
            not cold_start_tfs_15m and (
                ((not is_middle_chop_veto or (desk_bull_cnt_15m >= 2 or desk_bear_cnt_15m >= 2)) and matrix_trade_permitted and (
                    is_15m_bull or is_15m_bear or is_coiling_breakout or is_range_rotation or is_breakout_expansion
                )) or has_valid_institutional_trigger_15m
            )
        )
        q_15m_direction = (
            ob_setup_15m.get("direction") if (has_ob_15m and ob_setup_15m.get("zeiierman_rank", 99) <= 3) else (
                "LONG" if is_15m_bull else (
                    "SHORT" if is_15m_bear else (
                        smc_dir_15m if has_smc_15m else (
                            matrix_eval.get("dominant_direction") if (is_coiling_breakout or is_range_rotation or is_breakout_expansion) else None
                        )
                    )
                )
            )
        ) if q_15m_qualified else None

        q_15m = {
            "qualified": q_15m_qualified,
            "direction": q_15m_direction,
            "required_horizons": req_15m,
            "bull_aligned_count": bull_cnt_15m,
            "bear_aligned_count": bear_cnt_15m,
            "chop_aligned_count": sum(1 for t in trends_15m if t == "CONSOLIDATION"),
            "archetype": matrix_eval.get("archetype"),
            "strategy": matrix_eval.get("strategy"),
            "has_order_block_touch": has_ob_15m,
            "has_smc_setup": has_smc_15m,
            "order_block_rank": ob_setup_15m.get("zeiierman_rank") if has_ob_15m else None,
            "conflicts": (
                [f"COLD_START_HORIZON_ACCUMULATION: 15M Scalp requires >= 15 historical candles (3.75h). Under-accumulated horizons: {cold_start_tfs_15m}."]
                if cold_start_tfs_15m else (
                    [f"CAPITAL_PRESERVATION: Trapped in middle 50% chop zone of 1D range box. Section 35 gate locked."]
                    if (is_middle_chop_veto and not has_valid_institutional_trigger_15m) else (
                        [f"{tf} is {trend_matrix.get(tf, 'MISSING')}" for tf in req_15m if trend_matrix.get(tf) != ("BULLISH" if is_15m_bull else ("BEARISH" if is_15m_bear else trends_15m[0]))]
                        if not q_15m_qualified else []
                    )
                )
            )
        }

        # -----------------------------------------------------------------
        # 2. 1H Intraday Gate (Empirical accumulation required: 1H [15h], 15M [3.75h], 5M)
        # Desk: 1H Intraday. Anchor: 4H. Trigger: 15M.
        # -----------------------------------------------------------------
        req_1h = ["5m", "15m", "1h", "4h", "12h", "1d", "1w"]
        emp_req_1h = ["5m", "15m", "1h"]
        cold_start_tfs_1h = [
            tf for tf in emp_req_1h
            if horizon_predictions.get(tf, {}).get("is_cold_start", False) or
               horizon_predictions.get(tf, {}).get("candle_count", 99) < 15
        ]
        converged_tfs_1h = [tf for tf in req_1h if not horizon_predictions.get(tf, {}).get("is_cold_start", False)]
        trends_1h = [trend_matrix.get(tf, "CONSOLIDATION") for tf in req_1h]
        bull_cnt_1h = sum(1 for t in trends_1h if t == "BULLISH")
        bear_cnt_1h = sum(1 for t in trends_1h if t == "BEARISH")

        # Phase 4A Elder's Triple Screen Decoupling: Anchor = 4H, Context = 1H, Trigger = 15M
        desk_bull_cnt_1h = sum(1 for tf in ["15m", "1h", "4h"] if trend_matrix.get(tf) == "BULLISH")
        desk_bear_cnt_1h = sum(1 for tf in ["15m", "1h", "4h"] if trend_matrix.get(tf) == "BEARISH")

        is_1h_bull = (
            (len(converged_tfs_1h) >= 3 and all(trend_matrix.get(tf) == "BULLISH" for tf in converged_tfs_1h))
            or (
                trend_matrix.get("1h") == "BULLISH"
                and trend_matrix.get("4h") != "BEARISH"
                and desk_bear_cnt_1h == 0
                and (desk_bull_cnt_1h >= 2 or bull_cnt_1h >= 4)
                and bear_cnt_1h <= 1
            )
        )
        is_1h_bear = (
            (len(converged_tfs_1h) >= 3 and all(trend_matrix.get(tf) == "BEARISH" for tf in converged_tfs_1h))
            or (
                trend_matrix.get("1h") == "BEARISH"
                and trend_matrix.get("4h") != "BULLISH"
                and desk_bull_cnt_1h == 0
                and (desk_bear_cnt_1h >= 2 or bear_cnt_1h >= 4)
                and bull_cnt_1h <= 1
            )
        )

        has_valid_institutional_trigger_1h = bool(
            (has_ob_1h and ob_setup_1h.get("zeiierman_rank", 99) <= 3) or has_smc_1h or is_coiling_breakout
        )

        q_1h_qualified = bool(
            not cold_start_tfs_1h and (
                ((not is_middle_chop_veto or (desk_bull_cnt_1h >= 2 or desk_bear_cnt_1h >= 2)) and matrix_trade_permitted and (
                    is_1h_bull or is_1h_bear or is_coiling_breakout or is_breakout_expansion or (is_range_rotation and matrix_eval.get("dominant_direction") in ["LONG", "SHORT"])
                )) or has_valid_institutional_trigger_1h
            )
        )
        q_1h_direction = (
            ob_setup_1h.get("direction") if (has_ob_1h and ob_setup_1h.get("zeiierman_rank", 99) <= 3) else (
                "LONG" if is_1h_bull else (
                    "SHORT" if is_1h_bear else (
                        smc_dir_1h if has_smc_1h else (
                            matrix_eval.get("dominant_direction") if (is_coiling_breakout or is_range_rotation or is_breakout_expansion) else None
                        )
                    )
                )
            )
        ) if q_1h_qualified else None

        q_1h = {
            "qualified": q_1h_qualified,
            "direction": q_1h_direction,
            "required_horizons": req_1h,
            "bull_aligned_count": bull_cnt_1h,
            "bear_aligned_count": bear_cnt_1h,
            "chop_aligned_count": sum(1 for t in trends_1h if t == "CONSOLIDATION"),
            "archetype": matrix_eval.get("archetype"),
            "strategy": matrix_eval.get("strategy"),
            "has_order_block_touch": has_ob_1h,
            "has_smc_setup": has_smc_1h,
            "order_block_rank": ob_setup_1h.get("zeiierman_rank") if has_ob_1h else None,
            "conflicts": (
                [f"COLD_START_HORIZON_ACCUMULATION: 1H Intraday requires >= 15 historical candles (15h). Under-accumulated horizons: {cold_start_tfs_1h}."]
                if cold_start_tfs_1h else (
                    [f"CAPITAL_PRESERVATION: Trapped in middle 50% chop zone of 1D range box. Section 35 gate locked."]
                    if (is_middle_chop_veto and not has_valid_institutional_trigger_1h) else (
                        [f"{tf} is {trend_matrix.get(tf, 'MISSING')}" for tf in req_1h if trend_matrix.get(tf) != ("BULLISH" if is_1h_bull else ("BEARISH" if is_1h_bear else trends_1h[0]))]
                        if not q_1h_qualified else []
                    )
                )
            )
        }

        # -----------------------------------------------------------------
        # 3. 24H Swing Gate (Empirical accumulation required: 1D [15 days], 12H, 4H, 1H, 15M)
        # Desk: 24H Swing. Anchor: 1W. Trigger: 4H/12H.
        # -----------------------------------------------------------------
        req_24h = ["15m", "1h", "4h", "12h", "1d", "1w", "15d"]
        emp_req_24h = ["15m", "1h", "4h", "12h", "1d"]
        cold_start_tfs_24h = [
            tf for tf in emp_req_24h
            if horizon_predictions.get(tf, {}).get("is_cold_start", False) or
               horizon_predictions.get(tf, {}).get("candle_count", 99) < 15
        ]
        converged_tfs_24h = [tf for tf in req_24h if not horizon_predictions.get(tf, {}).get("is_cold_start", False)]
        trends_24h = [trend_matrix.get(tf, "CONSOLIDATION") for tf in req_24h]
        bull_cnt_24h = sum(1 for t in trends_24h if t == "BULLISH")
        bear_cnt_24h = sum(1 for t in trends_24h if t == "BEARISH")

        is_24h_bull = (
            (len(converged_tfs_24h) >= 5 and all(trend_matrix.get(tf) == "BULLISH" for tf in converged_tfs_24h))
            or ((trend_matrix.get("1d") == "BULLISH" or trend_matrix.get("12h") == "BULLISH") and trend_matrix.get("1w") != "BEARISH" and bull_cnt_24h >= 4 and bear_cnt_24h <= 1)
        )
        is_24h_bear = (
            (len(converged_tfs_24h) >= 5 and all(trend_matrix.get(tf) == "BEARISH" for tf in converged_tfs_24h))
            or ((trend_matrix.get("1d") == "BEARISH" or trend_matrix.get("12h") == "BEARISH") and trend_matrix.get("1w") != "BULLISH" and bear_cnt_24h >= 4 and bull_cnt_24h <= 1)
        )

        has_valid_institutional_trigger_24h = bool(
            (has_ob_24h and ob_setup_24h.get("zeiierman_rank", 99) <= 3) or has_smc_24h
        )

        q_24h_qualified = bool(
            not cold_start_tfs_24h and (
                (not is_middle_chop_veto and matrix_trade_permitted and (
                    is_24h_bull or is_24h_bear or is_breakout_expansion
                )) or has_valid_institutional_trigger_24h
            )
        )
        q_24h_direction = (
            ob_setup_24h.get("direction") if (has_ob_24h and ob_setup_24h.get("zeiierman_rank", 99) <= 3) else (
                "LONG" if is_24h_bull else (
                    "SHORT" if is_24h_bear else (
                        smc_dir_24h if has_smc_24h else (
                            matrix_eval.get("dominant_direction") if is_breakout_expansion else None
                        )
                    )
                )
            )
        ) if q_24h_qualified else None

        q_24h = {
            "qualified": q_24h_qualified,
            "direction": q_24h_direction,
            "required_horizons": req_24h,
            "bull_aligned_count": bull_cnt_24h,
            "bear_aligned_count": bear_cnt_24h,
            "chop_aligned_count": sum(1 for t in trends_24h if t == "CONSOLIDATION"),
            "archetype": matrix_eval.get("archetype"),
            "strategy": matrix_eval.get("strategy"),
            "has_order_block_touch": has_ob_24h,
            "has_smc_setup": has_smc_24h,
            "order_block_rank": ob_setup_24h.get("zeiierman_rank") if has_ob_24h else None,
            "conflicts": (
                [f"COLD_START_HORIZON_ACCUMULATION: 24H Daily Swing requires >= 15 historical candles (15 days). Under-accumulated horizons: {cold_start_tfs_24h}."]
                if cold_start_tfs_24h else (
                    [f"CAPITAL_PRESERVATION: Trapped in middle 50% chop zone of 1D range box. Section 35 gate locked."]
                    if (is_middle_chop_veto and not has_valid_institutional_trigger_24h) else (
                        [f"{tf} is {trend_matrix.get(tf, 'MISSING')}" for tf in req_24h if trend_matrix.get(tf) != ("BULLISH" if is_24h_bull else ("BEARISH" if is_24h_bear else trends_24h[0]))]
                        if not q_24h_qualified else []
                    )
                )
            )
        }

        return q_15m, q_1h, q_24h

    def evaluate_asset_multi_horizon(
        self,
        symbol: str,
        dfs_9: Dict[str, pd.DataFrame],
        btc_shield_state: Dict[str, Any],
        live_price: float = None,
        volume_24h_usd: float = 0.0,
        bid_price: float = 0.0,
        ask_price: float = 0.0,
        spread_bps: float = 5.0
    ) -> Dict[str, Any]:
        """
        Evaluates an individual cryptocurrency pair across all 9 charts.
        Returns complete multi-horizon predictions and dominant trade signal.
        """
        if not dfs_9 or "15m" not in dfs_9 or dfs_9["15m"] is None:
            return None

        current_price = live_price if (live_price is not None and live_price > 0) else float(dfs_9["15m"]["close"].iloc[-1])
        if current_price <= 0.0001:
            return None

        # Hard Liquidity Floor Gate: Exclude coins with sub-threshold volume (< $1M) from active emission
        if volume_24h_usd is not None and 0 < volume_24h_usd < 1_000_000.0:
            return None

        # Fetch asset fundamental intelligence & news matrix
        fund_matrix = None
        try:
            from app.services.fundamental_service import fundamental_service
            fund_matrix = fundamental_service.get_asset_fundamental_matrix(symbol)
        except Exception:
            fund_matrix = None

        # Scan Institutional Order Blocks across all 9 Horizons concurrently
        ob_scan = order_block_engine.scan_all_horizons(dfs_9, current_price=current_price, btc_shield=btc_shield_state)

        alt_longs_allowed = btc_shield_state.get("altcoin_longs_allowed", True)
        horizon_predictions: Dict[str, Any] = {}
        now_ts = time.time()

        # Evaluate each of the 9 required timeframes
        for tf in TIMEFRAMES_9:
            df_tf = dfs_9.get(tf)
            if df_tf is None or len(df_tf) < 5:
                continue

            last_candle_ts = int(df_tf["timestamp"].iloc[-1]) if "timestamp" in df_tf.columns else 0
            cache_key = f"{symbol}_{tf}"
            # SIG-02: Volatility-conditioned dynamic timeframe TTL
            c_close = float(df_tf["close"].iloc[-1]) if len(df_tf) > 0 else 1.0
            high_s = df_tf["high"] if "high" in df_tf.columns else df_tf["close"]
            low_s = df_tf["low"] if "low" in df_tf.columns else df_tf["close"]
            tr_proxy = float((high_s.iloc[-1] - low_s.iloc[-1])) if len(df_tf) > 0 else (c_close * 0.015)
            tf_atr_pct = (tr_proxy / max(1e-8, c_close)) * 100.0
            ttl = self._get_timeframe_ttl(tf, active_atr_pct=tf_atr_pct)

            # 1. Extract Candle Dynamics Features
            feats = self.feature_extractor.extract_features(df_tf, prefix=tf)
            if feats.empty or len(feats) < 5:
                continue

            c = df_tf["close"].values
            o = df_tf["open"].values
            n = len(df_tf)

            # Target 1: Next Candle Color (Green Bullish = 1, Red Bearish = 0)
            target_direction = np.zeros(n, dtype=int)
            for i in range(n - 1):
                target_direction[i] = 1 if c[i + 1] > o[i + 1] else 0

            # Target 2: Next Candle Return (Price Change %)
            target_return = np.zeros(n, dtype=float)
            for i in range(n - 1):
                target_return[i] = (c[i + 1] - c[i]) / (c[i] + 1e-10)

            # Strictly use completed historical candles for training targets
            # If candle n-1 is the unclosed forming candle, targets for sample i are candle i+1.
            # Sample n-3's target is completed candle n-2. Sample n-2's target would be unclosed candle n-1, so exclude n-2 from training.
            if n >= 16:
                X = feats.iloc[:-2].values
                y_dir = target_direction[:-2]
                y_ret = target_return[:-2]
            else:
                X = feats.iloc[:-1].values
                y_dir = target_direction[:-1]
                y_ret = target_return[:-1]
            X_live = feats.iloc[-1:].values

            # Calculate raw ATR
            h = df_tf["high"].values
            l = df_tf["low"].values
            tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
            raw_atr = float(np.mean(tr[-14:])) if len(tr) >= 14 else (current_price * 0.01)

            # Fast-Boot Dedicated Per-Coin Model Checkpoint or Fresh Fit
            clf_ensemble, reg_ensemble, is_fresh = self.model_registry.get_or_train_coin_models(
                symbol=symbol,
                tf=tf,
                X_train=X,
                y_train_dir=y_dir,
                y_train_ret=y_ret,
                last_candle_ts=last_candle_ts,
                ttl_seconds=ttl
            )

            # 2. Execute 5 Top Classifiers (Next Candle Direction by Majority Votes)
            clf_result = clf_ensemble.predict_live(X_live) if hasattr(clf_ensemble, "predict_live") else clf_ensemble.train_and_predict(X, y_dir, X_live)

            # 3. Execute 5 Top Regressors (Target Price with Directional Confluence)
            clf_dir = clf_result.get("direction", "LONG")
            reg_result = reg_ensemble.predict_price_live(
                X_live, current_price=current_price, raw_atr=raw_atr, expected_direction=clf_dir
            ) if hasattr(reg_ensemble, "predict_price_live") else reg_ensemble.train_and_predict_price(
                X, y_ret, X_live, current_price=current_price, raw_atr=raw_atr, expected_direction=clf_dir
            )

            # Trend Classification: Fractal Candlestick Analysis + ML Confluence
            f_prof = FractalConsolidationEngine.analyze_timeframe(df_tf, timeframe=tf)

            pred_chg = reg_result["predicted_change_pct"]
            bull_v = clf_result["bullish_votes"]
            bear_v = clf_result["bearish_votes"]
            prob_b = clf_result.get("prob_bullish", clf_result.get("consensus_probability", 0.55))

            c_vals = df_tf["close"].values
            o_vals = df_tf["open"].values
            body_sizes = np.abs(c_vals[-5:] - o_vals[-5:])
            candle_ranges = np.maximum(df_tf["high"].values[-5:] - df_tf["low"].values[-5:], 1e-10)
            avg_body_wick = float(np.mean(body_sizes / candle_ranges))

            # Scale chop threshold dynamically by ATR percentage of this timeframe
            atr_pct = (raw_atr / (current_price + 1e-10)) * 100.0
            min_trend_ret = max(0.08, atr_pct * 0.15)

            # High ADX or strong directional consensus invalidates chop
            has_strong_momentum = bool(f_prof.adx >= 22.0 and (bull_v >= 4 or bear_v >= 4))

            is_chop = (
                not has_strong_momentum and (
                    (abs(pred_chg) < min_trend_ret and (0.46 <= prob_b <= 0.54)) or
                    (bull_v == 3 and bear_v == 2 and abs(pred_chg) < (min_trend_ret * 0.75)) or
                    (avg_body_wick < 0.20 and abs(pred_chg) < min_trend_ret and f_prof.adx < 20.0)
                )
            )

            n_raw = len(df_tf)
            is_synth = bool(getattr(df_tf, "attrs", {}).get("is_synthetic", False))
            is_hyb = bool(getattr(df_tf, "attrs", {}).get("is_hybrid", False))
            n_nat = int(getattr(df_tf, "attrs", {}).get("native_candle_count", 0 if is_synth else n_raw))
            is_cold_start = bool(n_raw < 15 or is_synth or clf_result.get("is_cold_start", False) or reg_result.get("is_cold_start", False))

            if is_cold_start:
                tf_trend = "CONSOLIDATION"
                tf_trend_label = f"🟡 ACCUMULATING (COLD START: N={n_raw})"
            elif f_prof.is_coiling_squeeze:
                tf_trend = "CONSOLIDATION"
                tf_trend_label = "🟡 COILING SQUEEZE"
            elif (f_prof.state == FractalTimeframeState.CONSOLIDATION_RANGING and not has_strong_momentum) or is_chop:
                tf_trend = "CONSOLIDATION"
                tf_trend_label = "🟡 CONSOLIDATION"
            elif clf_result["direction"] == "LONG" and bull_v >= 3 and pred_chg >= (min_trend_ret * 0.4):
                tf_trend = "BULLISH"
                tf_trend_label = "🟢 BULLISH"
            elif clf_result["direction"] == "SHORT" and bear_v >= 3 and pred_chg <= -(min_trend_ret * 0.4):
                tf_trend = "BEARISH"
                tf_trend_label = "🔴 BEARISH"
            elif f_prof.state == FractalTimeframeState.TREND_BULLISH:
                tf_trend = "BULLISH"
                tf_trend_label = "🟢 BULLISH"
            elif f_prof.state == FractalTimeframeState.TREND_BEARISH:
                tf_trend = "BEARISH"
                tf_trend_label = "🔴 BEARISH"
            else:
                tf_trend = "CONSOLIDATION"
                tf_trend_label = "🟡 CONSOLIDATION"

            # Order Block Telemetry for this specific timeframe
            tf_ob_info = ob_scan.get("horizon_blocks", {}).get(tf, {})
            ob_touch = tf_ob_info.get("has_touch", False)
            ob_rank = tf_ob_info.get("touch_rank")
            ob_label = tf_ob_info.get("touch_label")
            ob_type = tf_ob_info.get("touch_type", "NONE")
            ob_zone = tf_ob_info.get("nearest_zone")

            tf_seconds = TIMEFRAME_META.get(tf, {}).get("seconds", 900)
            hist_hours = round(n_nat * tf_seconds / 3600.0, 2)
            req_hours = round(15 * tf_seconds / 3600.0, 2)
            acc_phase = "CONVERGED_ENSEMBLE" if (n_raw >= 15 and not is_synth) else "COLD_START_INSUFFICIENT_HISTORY"

            horizon_predictions[tf] = {
                "timeframe": tf,
                "candle_count": n_nat,
                "is_synthetic": is_synth,
                "is_hybrid": is_hyb,
                "is_cold_start": is_cold_start,
                "accumulation_phase": acc_phase,
                "accumulation_progress_pct": min(100.0, round((n_raw / 15.0) * 100.0, 1)),
                "historical_hours_accumulated": hist_hours,
                "required_hours_for_convergence": req_hours,
                "synth_label": "Synth: True" if is_synth else "Synth: False",
                "current_price": current_price,
                "direction": clf_result["direction"],
                "trend_state": tf_trend,
                "trend_label": tf_trend_label,
                "candle_color": clf_result.get("decision_label", "🟢 GREEN BULLISH" if clf_result.get("direction") == "LONG" else "🔴 RED BEARISH"),
                "classifier_votes": clf_result.get("consensus_tally", "3/5 MAJORITY"),
                "bullish_votes": clf_result.get("bullish_votes", 3),
                "bearish_votes": clf_result.get("bearish_votes", 2),
                "consensus_probability": clf_result.get("consensus_probability", 0.55),
                "predicted_target_price": reg_result["predicted_target_price"],
                "predicted_change_pct": reg_result["predicted_change_pct"],
                "regressor_votes": reg_result["regression_votes"],
                "winning_vote_count": reg_result["winning_vote_count"],
                "classifier_breakdown": clf_result["model_breakdown"],
                "regressor_breakdown": reg_result["model_predictions"],
                # Fractal Candlestick & Volatility Metrics
                "is_inside_bar": f_prof.is_inside_bar,
                "is_nr7": f_prof.is_nr7,
                "is_nr4": f_prof.is_nr4,
                "is_doji": f_prof.is_doji,
                "is_coiling_squeeze": f_prof.is_coiling_squeeze,
                "compression_score": f_prof.compression_score,
                "range_high": f_prof.range_high,
                "range_low": f_prof.range_low,
                "position_in_range_pct": f_prof.position_in_range_pct,
                "headroom_to_high_pct": f_prof.headroom_to_high_pct,
                "headroom_to_low_pct": f_prof.headroom_to_low_pct,
                # Institutional Order Block Telemetry
                "order_block_touch": ob_touch,
                "order_block_rank": ob_rank,
                "order_block_rank_label": ob_label,
                "order_block_type": ob_type,
                "order_block_zone": ob_zone,
                "total_order_blocks": tf_ob_info.get("total_blocks", 0)
            }

        if not horizon_predictions:
            return None

        # ---------------------------------------------------------------------
        # MULTI-HORIZON TREND ALIGNMENT (5M, 15M, 1H, 4H, 12H, 24H, 7D, 15D, 1M)
        # ---------------------------------------------------------------------
        # Multi-Timeframe Fractal Profiles & Cross-Timeframe Matrix
        fractal_profiles = {
            tf: FractalConsolidationEngine.analyze_timeframe(dfs_9[tf], timeframe=tf)
            for tf in dfs_9 if dfs_9[tf] is not None and len(dfs_9[tf]) >= 5
        }
        matrix_eval = CrossTimeframeMatrixEngine.evaluate_matrix(fractal_profiles, current_price)

        trend_alignment_info = self.compute_trend_alignment(horizon_predictions, matrix_eval)
        trend_matrix = trend_alignment_info["trend_matrix"]
        dominant_trend = trend_alignment_info["dominant_trend"]
        alignment_score_pct = trend_alignment_info["alignment_score_pct"]

        # ---------------------------------------------------------------------
        # STRICT MULTI-HORIZON CRITERIA GATING FOR 15M, 1H, AND 24H SIGNALS
        # ---------------------------------------------------------------------
        # Check active Order Block Touches across Horizons
        ob_touches_by_tf = ob_scan.get("touch_setups_by_horizon", {})
        ob_setup_15m = ob_touches_by_tf.get("15m") or ob_touches_by_tf.get("5m")
        ob_setup_1h = ob_touches_by_tf.get("1h") or ob_touches_by_tf.get("4h")
        ob_setup_24h = ob_touches_by_tf.get("1d") or ob_touches_by_tf.get("12h")

        # Check active SMC Price Action Setups on 15M, 1H, and 24H charts
        has_smc_15m = False
        smc_dir_15m = None
        df_15m = dfs_9.get("15m")
        if df_15m is not None and len(df_15m) >= 4:
            c_l, _, m_l = EntryConfirmationEngine.validate_candle_trigger(df_15m, direction="LONG", current_price=current_price, spread_bps=spread_bps)
            c_s, _, m_s = EntryConfirmationEngine.validate_candle_trigger(df_15m, direction="SHORT", current_price=current_price, spread_bps=spread_bps)
            if c_l and (m_l.get("is_sweep_reclaim") or m_l.get("is_fvg_retest") or m_l.get("is_vwap_bounce") or m_l.get("is_engulfing") or m_l.get("is_squeeze_expansion")):
                has_smc_15m = True
                smc_dir_15m = "LONG"
            elif c_s and (m_s.get("is_sweep_reclaim") or m_s.get("is_fvg_retest") or m_s.get("is_vwap_bounce") or m_s.get("is_engulfing") or m_s.get("is_squeeze_expansion")):
                has_smc_15m = True
                smc_dir_15m = "SHORT"

        has_smc_1h = False
        smc_dir_1h = None
        df_1h = dfs_9.get("1h")
        if df_1h is not None and len(df_1h) >= 4:
            c_l, _, m_l = EntryConfirmationEngine.validate_candle_trigger(df_1h, direction="LONG", current_price=current_price, spread_bps=spread_bps)
            c_s, _, m_s = EntryConfirmationEngine.validate_candle_trigger(df_1h, direction="SHORT", current_price=current_price, spread_bps=spread_bps)
            if c_l and (m_l.get("is_sweep_reclaim") or m_l.get("is_fvg_retest") or m_l.get("is_vwap_bounce") or m_l.get("is_engulfing") or m_l.get("is_squeeze_expansion")):
                has_smc_1h = True
                smc_dir_1h = "LONG"
            elif c_s and (m_s.get("is_sweep_reclaim") or m_s.get("is_fvg_retest") or m_s.get("is_vwap_bounce") or m_s.get("is_engulfing") or m_s.get("is_squeeze_expansion")):
                has_smc_1h = True
                smc_dir_1h = "SHORT"

        has_smc_24h = False
        smc_dir_24h = None
        df_24h = dfs_9.get("1d") if dfs_9.get("1d") is not None else dfs_9.get("12h")
        if df_24h is not None and len(df_24h) >= 4:
            c_l, _, m_l = EntryConfirmationEngine.validate_candle_trigger(df_24h, direction="LONG", current_price=current_price, spread_bps=spread_bps)
            c_s, _, m_s = EntryConfirmationEngine.validate_candle_trigger(df_24h, direction="SHORT", current_price=current_price, spread_bps=spread_bps)
            if c_l and (m_l.get("is_sweep_reclaim") or m_l.get("is_fvg_retest") or m_l.get("is_vwap_bounce") or m_l.get("is_engulfing") or m_l.get("is_squeeze_expansion")):
                has_smc_24h = True
                smc_dir_24h = "LONG"
            elif c_s and (m_s.get("is_sweep_reclaim") or m_s.get("is_fvg_retest") or m_s.get("is_vwap_bounce") or m_s.get("is_engulfing") or m_s.get("is_squeeze_expansion")):
                has_smc_24h = True
                smc_dir_24h = "SHORT"

        q_15m, q_1h, q_24h = self.evaluate_multi_horizon_gates(
            trend_matrix=trend_matrix,
            horizon_predictions=horizon_predictions,
            matrix_eval=matrix_eval,
            ob_setup_15m=ob_setup_15m,
            ob_setup_1h=ob_setup_1h,
            ob_setup_24h=ob_setup_24h,
            has_smc_15m=has_smc_15m,
            smc_dir_15m=smc_dir_15m,
            has_smc_1h=has_smc_1h,
            smc_dir_1h=smc_dir_1h,
            has_smc_24h=has_smc_24h,
            smc_dir_24h=smc_dir_24h,
        )

        has_ob_15m = bool(ob_setup_15m and ob_setup_15m.get("setup_detected"))
        has_ob_1h = bool(ob_setup_1h and ob_setup_1h.get("setup_detected"))
        has_ob_24h = bool(ob_setup_24h and ob_setup_24h.get("setup_detected"))

        req_15m = q_15m["required_horizons"]
        req_1h = q_1h["required_horizons"]
        req_24h = q_24h["required_horizons"]

        # Generate discrete qualified signals ONLY for 15M, 1H, and 24H
        qualified_signals: Dict[str, Dict[str, Any]] = {}
        all_candidate_signals: Dict[str, Dict[str, Any]] = {}

        if q_15m["qualified"]:
            sig_15m = self._build_single_horizon_signal(
                symbol=symbol, horizon_label="15M", tf_key="15m",
                direction=q_15m["direction"], current_price=current_price,
                dfs_9=dfs_9, horizon_prediction=horizon_predictions.get("15m"),
                btc_shield_state=btc_shield_state, aligned_horizons=req_15m,
                archetype_info=matrix_eval,
                order_block_setup=ob_setup_15m if has_ob_15m else None,
                volume_24h_usd=volume_24h_usd,
                bid_price=bid_price,
                ask_price=ask_price,
                spread_bps=spread_bps,
                fundamental_matrix=fund_matrix,
                alignment_score=alignment_score_pct
            )
            all_candidate_signals["15M"] = sig_15m
            if sig_15m["is_trade_active"] and not sig_15m.get("is_ntz_active", False):
                qualified_signals["15M"] = sig_15m

        if q_1h["qualified"]:
            sig_1h = self._build_single_horizon_signal(
                symbol=symbol, horizon_label="1H", tf_key="1h",
                direction=q_1h["direction"], current_price=current_price,
                dfs_9=dfs_9, horizon_prediction=horizon_predictions.get("1h"),
                btc_shield_state=btc_shield_state, aligned_horizons=req_1h,
                archetype_info=matrix_eval,
                order_block_setup=ob_setup_1h if has_ob_1h else None,
                volume_24h_usd=volume_24h_usd,
                bid_price=bid_price,
                ask_price=ask_price,
                spread_bps=spread_bps,
                fundamental_matrix=fund_matrix,
                alignment_score=alignment_score_pct
            )
            all_candidate_signals["1H"] = sig_1h
            if sig_1h["is_trade_active"] and not sig_1h.get("is_ntz_active", False):
                qualified_signals["1H"] = sig_1h

        if q_24h["qualified"]:
            sig_24h = self._build_single_horizon_signal(
                symbol=symbol, horizon_label="24H", tf_key="1d",
                direction=q_24h["direction"], current_price=current_price,
                dfs_9=dfs_9, horizon_prediction=horizon_predictions.get("1d"),
                btc_shield_state=btc_shield_state, aligned_horizons=req_24h,
                archetype_info=matrix_eval,
                order_block_setup=ob_setup_24h if has_ob_24h else None,
                volume_24h_usd=volume_24h_usd,
                bid_price=bid_price,
                ask_price=ask_price,
                spread_bps=spread_bps,
                fundamental_matrix=fund_matrix,
                alignment_score=alignment_score_pct
            )
            all_candidate_signals["24H"] = sig_24h
            if sig_24h["is_trade_active"] and not sig_24h.get("is_ntz_active", False):
                qualified_signals["24H"] = sig_24h

        # Controlled Experiment 1: Reversible Horizon Trade Eligibility Filter
        if ALLOWED_EMISSION_HORIZONS is not None:
            for hz_label in list(qualified_signals.keys()):
                if hz_label not in ALLOWED_EMISSION_HORIZONS:
                    suppressed_sig = qualified_signals.pop(hz_label)
                    suppressed_sig["is_trade_active"] = False
                    suppressed_sig["ineligible_reason"] = f"HORIZON_{hz_label}_SUPPRESSED_IN_EXPERIMENT_1"

        # Check macro NTZ status: Flash Dump halts all signals; Squeeze/Micro-volatility exempts boundary & coiling alpha
        is_macro_ntz, macro_ntz_reason = self.is_macro_no_trade_zone(btc_shield_state)
        is_macro_dump = (
            btc_shield_state.get("regime") == "FLASH_DUMP" or
            btc_shield_state.get("status_code") in ["BEAR_CASCADE_BLACKOUT", "ALERT_DUMP", "FLASH_DUMP"] or
            "DEFENSIVE_CASH_ONLY" in str(btc_shield_state.get("altcoin_posture", ""))
        )
        if is_macro_dump:
            qualified_signals.clear()
        elif is_macro_ntz:
            # Squeeze / micro-volatility NTZ: Hold back middle chop to preserve capital, preserve boundary & coiling setups
            for hz in list(qualified_signals.keys()):
                sig_obj = qualified_signals[hz]
                is_boundary_or_coiling = bool(
                    sig_obj.get("is_ob_setup") or
                    any(k in str(sig_obj.get("decision", "")).upper() for k in [
                        "ORDER_BLOCK", "BREAKER", "TURTLE_SOUP", "RANGE_SUPPORT",
                        "RANGE_RESISTANCE", "SUB_RANGE", "COILING", "EXPANSION", "BREAKOUT", "RANGE_BOUNCE", "SQUEEZE"
                    ])
                )
                if not is_boundary_or_coiling:
                    qualified_signals.pop(hz)

        is_trade_active = len(qualified_signals) > 0
        qualified_horizons = list(qualified_signals.keys())

        # Check if asset was vetoed by No Trade Zone or Negative News
        ntz_vetoed = [s for s in all_candidate_signals.values() if s.get("is_ntz_active")]
        is_asset_in_ntz = (is_macro_dump or (is_macro_ntz and len(qualified_signals) == 0) or (len(ntz_vetoed) > 0 and len(qualified_signals) == 0))
        ntz_active_reason = macro_ntz_reason if (is_macro_dump or (is_macro_ntz and len(qualified_signals) == 0)) else (
            ntz_vetoed[0].get("ntz_reason", "Asset in No Trade Zone") if ntz_vetoed else None
        )
        ntz_active_badge = "MACRO NTZ" if (is_macro_dump or (is_macro_ntz and len(qualified_signals) == 0)) else (
            ntz_vetoed[0].get("ntz_badge", "NO TRADE ZONE") if ntz_vetoed else "TRADE ZONE APPROVED"
        )

        news_vetoed = [s for s in all_candidate_signals.values() if s.get("signal_status") == "HOLD_VETOED_BY_NEGATIVE_NEWS"]
        is_asset_news_vetoed = (len(news_vetoed) > 0)
        news_veto_active_reason = news_vetoed[0].get("wait_reason", "Negative News Alert") if news_vetoed else None

        # Dominant timeframe prioritization: 24H > 1H > 15M (Macro stability over micro)
        if "24H" in qualified_signals:
            dom_sig = qualified_signals["24H"]
        elif "1H" in qualified_signals:
            dom_sig = qualified_signals["1H"]
        elif "15M" in qualified_signals:
            dom_sig = qualified_signals["15M"]
        else:
            dom_sig = None

        if is_trade_active and dom_sig:
            dominant_direction = dom_sig["direction"]
            active_signal_horizon = dom_sig["horizon"]
            grade = dom_sig["quality_grade"]
            conviction = dom_sig["conviction"]
            tp1_price = dom_sig["tp1_price"]
            tp2_price = dom_sig["tp2_price"]
            tp3_price = dom_sig["tp3_price"]
            sl_price = dom_sig["sl_price"]
            rr_ratio = dom_sig["risk_reward_ratio"]
            pred_target = dom_sig["predicted_target_price"]
            pred_pct = dom_sig["expected_return_pct"]
            status = "ACTIVE_SIGNAL"
            wait_reason = None
            dominant_timeframe = active_signal_horizon
            classifier_votes = dom_sig["classifier_votes"]
            regressor_votes = dom_sig["regressor_votes"]
            meta_win_prob = dom_sig.get("meta_win_probability", 0.50)
            meta_win_prob_pct = dom_sig.get("meta_win_probability_pct", 50.0)
            meta_verdict = dom_sig.get("meta_verdict", "APPROVED")
            meta_model_type = dom_sig.get("meta_model_type", "PER_COIN_DEDICATED")
            meta_sample_size = dom_sig.get("meta_sample_size", 0)
        elif is_asset_in_ntz:
            dominant_direction = "NO_TRADE"
            active_signal_horizon = None
            grade = f"Grade C (NO TRADE ZONE ACTIVE: {ntz_active_reason})"
            conviction = 0.0
            tp1_price = current_price
            tp2_price = current_price
            tp3_price = current_price
            sl_price = current_price
            rr_ratio = "1:1.0"
            pred_target = current_price
            pred_pct = 0.0
            status = "HOLD_VETOED_BY_NO_TRADE_ZONE"
            wait_reason = f"🛑 NO TRADE ZONE ACTIVE: {ntz_active_reason}. Signal generation suppressed for capital preservation."
            dominant_timeframe = "NO_TRADE_ZONE"
            classifier_votes = ""
            regressor_votes = ""
            meta_eval = self.meta_labeler.evaluate_signal(symbol, {
                "conviction": 0.0,
                "quality_grade": grade,
                "entry_price": current_price,
                "expected_return_pct": 0.0
            })
            meta_win_prob = meta_eval["win_probability"]
            meta_win_prob_pct = meta_eval["win_probability_pct"]
            meta_verdict = "VETOED_BY_NTZ"
            meta_model_type = meta_eval["model_type"]
            meta_sample_size = meta_eval["sample_size"]
        elif is_asset_news_vetoed:
            dominant_direction = "NO_TRADE"
            active_signal_horizon = None
            grade = f"Grade C (NEWS SENTINEL VETO: {news_veto_active_reason})"
            conviction = 0.0
            tp1_price = current_price
            tp2_price = current_price
            tp3_price = current_price
            sl_price = current_price
            rr_ratio = "1:1.0"
            pred_target = current_price
            pred_pct = 0.0
            status = "HOLD_VETOED_BY_NEGATIVE_NEWS"
            wait_reason = f"{news_veto_active_reason}. Signal generation suppressed for capital preservation."
            dominant_timeframe = "NEWS_VETO"
            classifier_votes = ""
            regressor_votes = ""
            meta_win_prob = 0.50
            meta_win_prob_pct = 50.0
            meta_verdict = "VETOED_BY_NEWS_SENTINEL"
            meta_model_type = "PER_COIN_DEDICATED"
            meta_sample_size = 0
        else:
            dominant_direction = "NO_TRADE"
            active_signal_horizon = None
            grade = "Grade C (NO TRADE: AWAITING STRICT MULTI-HORIZON ALIGNMENT)"
            conviction = 0.0
            tp1_price = current_price
            tp2_price = current_price
            tp3_price = current_price
            sl_price = current_price
            rr_ratio = "1:1.0"
            pred_target = current_price
            pred_pct = 0.0
            status = "WAITING_FOR_ALIGNMENT"
            wait_reason = "No trend alignment meets criteria (15M: 5M-24H, 1H: 5M-7D, 24H: 15M-15D). Waiting for right time to generate signals."
            dominant_timeframe = "AWAITING_ALIGNMENT"
            classifier_votes = ""
            regressor_votes = ""
            meta_eval = self.meta_labeler.evaluate_signal(symbol, {
                "conviction": 70.0,
                "quality_grade": grade,
                "entry_price": current_price,
                "expected_return_pct": 0.0
            })
            meta_win_prob = meta_eval["win_probability"]
            meta_win_prob_pct = meta_eval["win_probability_pct"]
            meta_verdict = meta_eval["meta_verdict"]
            meta_model_type = meta_eval["model_type"]
            meta_sample_size = meta_eval["sample_size"]

        return {
            "symbol": symbol,
            "current_price": current_price,
            "dominant_direction": dominant_direction,
            "direction": dominant_direction,
            "is_trade_active": is_trade_active,
            "horizon": active_signal_horizon or dominant_timeframe,
            "horizon_tag": active_signal_horizon or dominant_timeframe,
            "horizon_name": active_signal_horizon or dominant_timeframe,
            "active_signal_horizon": active_signal_horizon,
            "qualified_signal_horizons": qualified_horizons,
            "qualified_signals_by_horizon": qualified_signals,
            "signal_status": status,
            "wait_reason": wait_reason,
            "decision": dom_sig.get("decision") if dom_sig else (
                f"🎯 [{grade}] (EXECUTION AUTHORIZED)" if is_trade_active else "AWAITING_ALIGNMENT"
            ),
            "order_block_setup": dom_sig.get("order_block_setup") if dom_sig else None,
            "is_order_block_signal": dom_sig.get("is_order_block_signal", False) if dom_sig else False,
            "zeiierman_rank": dom_sig.get("zeiierman_rank") if dom_sig else None,
            "zeiierman_rank_label": dom_sig.get("zeiierman_rank_label") if dom_sig else None,
            "is_nested_smc": dom_sig.get("is_nested_smc", False) if dom_sig else False,
            "htf_poi_tf": dom_sig.get("htf_poi_tf") if dom_sig else None,
            "strategy": dom_sig.get("strategy") if dom_sig else matrix_eval.get("strategy"),
            "canonical_strategy": dom_sig.get("canonical_strategy") if dom_sig else (dom_sig.get("strategy") if dom_sig else matrix_eval.get("strategy")),
            "candle_trigger_confirmed": dom_sig.get("candle_trigger_confirmed", True) if dom_sig else True,
            "candle_trigger_reason": dom_sig.get("candle_trigger_reason", "") if dom_sig else "",
            "candle_metrics": dom_sig.get("candle_metrics", {}) if dom_sig else {},
            "is_ntz_active": is_asset_in_ntz,
            "ntz_reason": ntz_active_reason,
            "ntz_badge": ntz_active_badge,
            "trend_criteria_gates": {
                "15M_gate": q_15m,
                "1H_gate": q_1h,
                "24H_gate": q_24h
            },
            "dominant_trend": dominant_trend,
            "archetype": matrix_eval.get("archetype"),
            "strategy_playbook": matrix_eval.get("strategy"),
            "allocation_pct": matrix_eval.get("allocation_pct", 0.0),
            "headroom_pct": matrix_eval.get("headroom_pct", 0.0),
            "matrix_rationale": matrix_eval.get("rationale", ""),
            "cross_timeframe_matrix": matrix_eval,
            "trend_alignment": trend_alignment_info,
            "quality_grade": grade,
            "conviction": conviction,
            "entry_price": dom_sig["entry_price"] if dom_sig else current_price,
            "optimal_entry_price": dom_sig.get("optimal_entry_price", current_price) if dom_sig else current_price,
            "optimal_entry_limit": dom_sig.get("optimal_entry_limit", current_price) if dom_sig else current_price,
            "entry_zone_min": dom_sig.get("entry_zone_min", current_price) if dom_sig else current_price,
            "entry_zone_max": dom_sig.get("entry_zone_max", current_price) if dom_sig else current_price,
            "is_limit_pending": dom_sig.get("is_limit_pending", False) if dom_sig else False,
            "entry_mode": dom_sig.get("entry_mode", "MARKET") if dom_sig else "MARKET",
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
            "tp3_price": tp3_price,
            "sl_price": sl_price,
            "risk_reward_ratio": rr_ratio,
            "expected_return_pct": pred_pct,
            "dominant_timeframe": dominant_timeframe,
            "classifier_votes": classifier_votes,
            "regressor_votes": regressor_votes,
            "meta_win_probability": meta_win_prob,
            "meta_win_probability_pct": meta_win_prob_pct,
            "meta_win_prob": meta_win_prob,
            "meta_win_prob_pct": meta_win_prob_pct,
            "win_probability_pct": meta_win_prob_pct,
            "win_prob": meta_win_prob_pct,
            "path_probabilities": dom_sig["path_probabilities"] if dom_sig else {
                "tp1": max(15.0, min(95.0, round(float(meta_win_prob_pct or 75.0), 1))),
                "tp2": round(max(15.0, min(95.0, float(meta_win_prob_pct or 75.0))) * 0.65, 1),
                "tp3": round(max(15.0, min(95.0, float(meta_win_prob_pct or 75.0))) * 0.65 * 0.55, 1),
                "sl": max(5.0, round(100.0 - max(15.0, min(95.0, float(meta_win_prob_pct or 75.0))), 1))
            },
            "p_tp1_pct": dom_sig["p_tp1_pct"] if dom_sig else max(15.0, min(95.0, round(float(meta_win_prob_pct or 75.0), 1))),
            "p_tp2_pct": dom_sig["p_tp2_pct"] if dom_sig else round(max(15.0, min(95.0, float(meta_win_prob_pct or 75.0))) * 0.65, 1),
            "p_tp3_pct": dom_sig["p_tp3_pct"] if dom_sig else round(max(15.0, min(95.0, float(meta_win_prob_pct or 75.0))) * 0.65 * 0.55, 1),
            "p_sl_pct": dom_sig["p_sl_pct"] if dom_sig else max(5.0, round(100.0 - max(15.0, min(95.0, float(meta_win_prob_pct or 75.0))), 1)),
            "meta_verdict": meta_verdict,
            "meta_model_type": meta_model_type,
            "meta_sample_size": meta_sample_size,
            "per_coin_models_active": True,
            "all_9_timeframe_predictions": horizon_predictions,
            "btc_shield_status": btc_shield_state.get("status_code", "NORMAL"),
            "order_blocks_scan": ob_scan,
            "has_order_block_touch": ob_scan.get("has_active_touch", False),
            "touched_order_block_horizons": ob_scan.get("touched_horizons", []),
            "nearest_demand_level": ob_scan.get("nearest_demand_level"),
            "nearest_demand_dist_pct": ob_scan.get("nearest_demand_dist_pct", 0.0),
            "nearest_supply_level": ob_scan.get("nearest_supply_level"),
            "nearest_supply_dist_pct": ob_scan.get("nearest_supply_dist_pct", 0.0),
            "evaluated_at_utc": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "volume_24h_usd": volume_24h_usd,
            "bid_price": bid_price if bid_price > 0 else current_price,
            "ask_price": ask_price if ask_price > 0 else current_price,
            "spread_bps": spread_bps,
            "fundamental_matrix": fund_matrix,
            "news_sentiment": fund_matrix.get("news_sentiment") if fund_matrix else None,
            "catalyst_event": fund_matrix.get("catalyst_event") if fund_matrix else None,
            "macro_economic_event": fund_matrix.get("macro_economic_event") if fund_matrix else None,
            "is_macro_blackout": dom_sig.get("is_macro_blackout", False) if dom_sig else False,
            "sizing_multiplier": dom_sig.get("sizing_multiplier", fund_matrix.get("sizing_multiplier", 1.0) if fund_matrix else 1.0) if dom_sig else (fund_matrix.get("sizing_multiplier", 1.0) if fund_matrix else 1.0),
            "coin_beta": dom_sig.get("coin_beta", 1.0) if dom_sig else 1.0,
            "active_atr": dom_sig.get("active_atr", 0.0) if dom_sig else 0.0,
            "composite_fundamental_score": fund_matrix.get("composite_fundamental_score", 0.0) if fund_matrix else 0.0
        }
