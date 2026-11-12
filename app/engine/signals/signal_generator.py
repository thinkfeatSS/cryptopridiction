import time
import math
import logging
import threading
import numpy as np

logger = logging.getLogger("signal_generator")
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple

from app.engine.signals.candle_features import CandleDynamicsFeatureExtractor
from app.engine.signals.ensemble_classifier import FiveModelDirectionClassifier
from app.engine.signals.ensemble_regressor import FiveModelPriceRegressor
from app.engine.signals.per_coin_models import PerCoinModelRegistry
from app.engine.signals.meta_labeler import CoinSpecificMetaLabeler
from app.engine.config import TIMEFRAMES_9, TIMEFRAME_META, ALLOWED_EMISSION_HORIZONS, is_meme_coin, RETIRED_MACRO_TIMEFRAMES, ACTIVE_MODEL_TIMEFRAMES
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
    if "RECTANGLE" in raw:
        return StrategyArchetype.RECTANGLE_STRATEGY_LONG.value if is_long else StrategyArchetype.RECTANGLE_STRATEGY_SHORT.value

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

    if "SUB_RANGE" in raw or "MEAN_REVERSION" in raw:
        return StrategyArchetype.MEAN_REVERSION_LONG.value if is_long else StrategyArchetype.MEAN_REVERSION_SHORT.value

    if "RANGE" in raw or "ROTATION" in raw or "SUPPORT" in raw or "RESISTANCE" in raw:
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

    def __init__(self, data_loader=None):
        self.data_loader = data_loader
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

    @classmethod
    def detect_altcoin_idiosyncratic_trend(
        cls,
        symbol: str,
        direction: str,
        tf_key: str,
        df_active: Optional[pd.DataFrame],
        current_price: float,
        btc_shield_state: Optional[Dict[str, Any]],
        candle_metrics: Optional[Dict[str, Any]] = None,
        order_block_setup: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str]:
        """
        Identifies whether an individual altcoin exhibits an independent, decoupled trend
        or structural breakout when Bitcoin is in low volume, coiling, or consolidation.
        """
        if not symbol or "BTC" in symbol.split("/")[0].upper():
            return False, "BTC asset"

        if not btc_shield_state:
            return False, "Missing BTC shield state"

        # 1. Macro Emergency Check: If BTC is in acute flash dump or network outage, fail closed
        is_macro_dump = (
            btc_shield_state.get("regime") == "FLASH_DUMP" or
            btc_shield_state.get("status_code") in ["BEAR_CASCADE_BLACKOUT", "ALERT_DUMP", "FLASH_DUMP"] or
            "DEFENSIVE_CASH_ONLY" in str(btc_shield_state.get("altcoin_posture", "")) or
            btc_shield_state.get("is_partition_stale") or
            btc_shield_state.get("is_global_outage")
        )
        if is_macro_dump:
            return False, "BTC acute flash dump or global outage active"

        # 2. Check if BTC is in consolidation / low volume / squeeze regime
        regime_str = str(btc_shield_state.get("v16_regime") or btc_shield_state.get("regime") or "RANGE").upper()
        status_str = str(btc_shield_state.get("status_code") or "").upper()
        is_btc_consolidation = (
            regime_str in ["RANGE", "CONSOLIDATION", "CHOP", "RANGE_SQUEEZE", "SQUEEZE_COILING"] or
            "NO_TRADE_ZONE" in status_str or
            "MICRO_VOLATILITY" in status_str or
            "MICRO_VOLATILITY" in str(btc_shield_state.get("reason", "")).upper() or
            btc_shield_state.get("is_ntz_active", False)
        )

        if not is_btc_consolidation:
            return False, "BTC is in trending/directional macro regime"

        if df_active is None or len(df_active) < 14:
            return False, "Insufficient candle history on active timeframe"

        closes = df_active["close"].values.astype(float)
        highs = df_active["high"].values.astype(float)
        lows = df_active["low"].values.astype(float)
        n = len(closes)

        # 3. Calculate Welles Wilder ADX(14) on active timeframe
        try:
            trs = np.maximum(highs[1:] - lows[1:], np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])))
            plus_dm = np.where((highs[1:] - highs[:-1] > lows[:-1] - lows[1:]) & (highs[1:] - highs[:-1] > 0), highs[1:] - highs[:-1], 0.0)
            minus_dm = np.where((lows[:-1] - lows[1:] > highs[1:] - highs[:-1]) & (lows[:-1] - lows[1:] > 0), lows[:-1] - lows[1:], 0.0)
            
            if len(trs) >= 14:
                atr_s = float(np.mean(trs[:14]))
                p_s = float(np.mean(plus_dm[:14]))
                m_s = float(np.mean(minus_dm[:14]))
                for i in range(14, len(trs)):
                    atr_s = (atr_s * 13.0 + trs[i]) / 14.0
                    p_s = (p_s * 13.0 + plus_dm[i]) / 14.0
                    m_s = (m_s * 13.0 + minus_dm[i]) / 14.0
                p_di = (p_s / (atr_s + 1e-10)) * 100.0
                m_di = (m_s / (atr_s + 1e-10)) * 100.0
                dx = (abs(p_di - m_di) / (p_di + m_di + 1e-10)) * 100.0
                adx = float(dx)
            else:
                adx = 20.0
        except Exception:
            adx = 20.0

        # 4. Moving Average Trend Structure
        try:
            ema20 = float(pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1])
            ema50 = float(pd.Series(closes).ewm(span=50, adjust=False).mean().iloc[-1]) if n >= 30 else ema20
        except Exception:
            ema20 = float(closes[-1])
            ema50 = float(closes[-1])

        # 5. Relative Strength vs BTC
        lookback = min(16, n - 1)
        alt_ret = (current_price - closes[-lookback]) / (closes[-lookback] + 1e-10)
        btc_ret = float(btc_shield_state.get("ret_1h", 0.0) if tf_key in ["15m", "1h"] else btc_shield_state.get("ret_24h", 0.0))
        rs = alt_ret - btc_ret

        # 6. Structural & Microstructure Backing
        has_ob = bool(order_block_setup and order_block_setup.get("setup_detected"))
        has_sweep = bool(candle_metrics and (candle_metrics.get("is_sweep_reclaim") or candle_metrics.get("is_engulfing")))
        rvol = float(candle_metrics.get("volume_surge_ratio", 1.0) if candle_metrics else 1.0)

        # Criteria A: Strong Independent Directional Trend (ADX >= 18 with MA alignment and RS)
        if direction == "LONG":
            is_trend_aligned = (current_price >= ema20 * 0.995) and (ema20 >= ema50 * 0.995)
            is_rs_positive = (rs >= -0.005)
            is_momentum_proven = (adx >= 18.0 and is_trend_aligned and is_rs_positive)
            is_structural_alpha = (has_ob or has_sweep or rvol >= 1.20) and (current_price >= ema20 * 0.990)
        else: # SHORT
            is_trend_aligned = (current_price <= ema20 * 1.005) and (ema20 <= ema50 * 1.005)
            is_rs_negative = (rs <= 0.005)
            is_momentum_proven = (adx >= 18.0 and is_trend_aligned and is_rs_negative)
            is_structural_alpha = (has_ob or has_sweep or rvol >= 1.20) and (current_price <= ema20 * 1.010)

        if is_momentum_proven or is_structural_alpha:
            reason = f"Decoupled {direction} trend on {symbol} (ADX: {adx:.1f}, RS: {rs*100:+.2f}%, RVOL: {rvol:.2f}x) during BTC consolidation"
            return True, reason

        return False, f"Middle chop without decoupled trend (ADX: {adx:.1f}, RS: {rs*100:+.2f}%)"

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
        alignment_score: float = 100.0,
        triad_structure: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Builds a dedicated institutional trade signal for a single qualified horizon:
        15M (Scalp), 1H (Intraday Swing), or 24H (Daily Swing).
        """
        if is_meme_coin(symbol):
            return None

        is_ob_setup = bool(order_block_setup and order_block_setup.get("setup_detected"))
        if is_ob_setup:
            ob_dir = order_block_setup.get("direction", direction)
            is_confirmed_ob_trigger = bool(
                order_block_setup.get("structural_trigger_confirmed") or
                order_block_setup.get("is_turtle_soup")
            )
            has_confirmed_mss = bool(
                order_block_setup.get("is_turtle_soup") or
                order_block_setup.get("has_confirmed_mss_reversal") or
                (order_block_setup.get("active_block", {}).get("mss_broken_level") and order_block_setup.get("active_block", {}).get("liquidity_swept"))
            )
            if ob_dir == direction or not direction:
                direction = ob_dir
            elif is_confirmed_ob_trigger and ob_dir != direction and has_confirmed_mss:
                # Valid institutional reversal: verified Market Structure Shift + liquidity sweep
                direction = ob_dir
            else:
                # Order Blocks are passive features, not autonomous trade triggers.
                # An unconfirmed passive block or retest without verified MSS cannot arbitrarily invert
                # the qualified macro trend direction.
                # Deactivate counter-trend OB setup override to preserve trend integrity.
                is_ob_setup = False

        if direction not in ["LONG", "SHORT"]:
            return None

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
        # Check if asset exhibits an independent idiosyncratic trend / relative strength during BTC consolidation
        is_decoupled_alt, decoupled_reason = self.detect_altcoin_idiosyncratic_trend(
            symbol=symbol,
            direction=direction,
            tf_key=tf_key,
            df_active=df_active,
            current_price=current_price,
            btc_shield_state=btc_shield_state,
            candle_metrics=candle_metrics,
            order_block_setup=order_block_setup
        )

        # Extract OB rank for strategy resolution (Fix RC-1: only rank 1-2 OBs win label unconditionally)
        ob_rank_val = int(order_block_setup.get("zeiierman_rank", 99)) if order_block_setup else 99
        canonical_strategy = map_canonical_strategy(
            arch_strategy, direction,
            is_ob_setup=is_ob_setup, ob_setup=order_block_setup,
            candle_metrics=candle_metrics, ob_rank=ob_rank_val
        )
        active_market_regime = str(btc_shield_state.get("v16_regime") or btc_shield_state.get("regime") or "RANGE").upper()
        is_strat_allowed, strat_veto_reason = self.strategy_registry.is_strategy_allowed(
            canonical_strategy,
            current_regime=active_market_regime,
            is_decoupled_trend=is_decoupled_alt
        )
        is_shadow_eligible, shadow_reason = (False, None)
        if not is_strat_allowed and hasattr(self.strategy_registry, "is_strategy_shadow_eligible"):
            is_shadow_eligible, shadow_reason = self.strategy_registry.is_strategy_shadow_eligible(canonical_strategy, current_regime=active_market_regime)

        is_liquidity_reclaim = bool(
            (is_ob_setup and order_block_setup and (
                order_block_setup.get("is_turtle_soup") or
                "TURTLE_SOUP" in str(order_block_setup.get("strategy", "")).upper() or
                "LIQUIDITY_RECLAIM" in str(canonical_strategy).upper()
            )) or (candle_metrics and candle_metrics.get("is_sweep_reclaim"))
        )

        # Strict BTC Market Beta Shield Gate:
        # Counter-trend trades against BTC macro trend fail closed (0 exemptions).
        if direction == "LONG" and not alt_longs_allowed:
            is_vetoed = True
            strat_veto_reason = f"LONG direction strictly vetoed by BTC Beta Shield ({active_market_regime})"
        elif direction == "SHORT" and not alt_shorts_allowed:
            is_vetoed = True
            strat_veto_reason = f"SHORT direction strictly vetoed by BTC Beta Shield ({active_market_regime})"

        # BTC Chop Index Defense Gate (decoupled altcoin trends with strong idiosyncratic momentum are exempt):
        btc_chop = float(btc_shield_state.get("chop_index") or btc_shield_state.get("metrics", {}).get("chop_index") or 0.0)
        if btc_chop > 61.8 and not is_decoupled_alt:
            is_vetoed = True
            strat_veto_reason = f"BTC Market Shield Chop Index ({btc_chop:.1f} > 61.8) indicates market equilibrium congestion"

        # Empirical Breakout Gate: Blind momentum breakouts into resistance/support without
        # aggressive taker absorption or pullback confirmation have 0.0% empirical win rate (0W/56L).
        is_breakout_strat = any(k in str(canonical_strategy).upper() for k in [
            "MOMENTUM_TREND_EXPANSION", "COILING_VOLATILITY_BREAKOUT"
        ]) and not is_liquidity_reclaim and not is_ob_setup

        if is_strat_allowed and is_breakout_strat:
            tb_ratio = float(candle_metrics.get("taker_buy_ratio", 0.5) if candle_metrics else 0.5)
            cvd_val = float(candle_metrics.get("cvd_surge_5", 0.0) if candle_metrics else 0.0)
            has_orderflow_support = (direction == "LONG" and (tb_ratio >= 0.54 or cvd_val >= 0.12)) or \
                                    (direction == "SHORT" and (tb_ratio <= 0.46 or cvd_val <= -0.12))
            is_pullback_confirmed = bool(candle_metrics and candle_metrics.get("is_pullback"))

            if not has_orderflow_support and not is_pullback_confirmed:
                is_strat_allowed = False
                strat_veto_reason = f"Breakout strategy {canonical_strategy} requires aggressive taker flow confirmation (Taker Ratio={tb_ratio:.2f}) or pullback retest"

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
        funding_info = self.data_loader.get_funding_info(symbol) if self.data_loader else None
        current_funding_rate = float(funding_info.get("funding_rate", 0.0001)) if funding_info else 0.0001

        ntz_eval = no_trade_zone_engine.evaluate_asset_ntz(
            df=df_active,
            current_price=current_price,
            anchor_tf=tf_key,
            btc_shield_info=btc_shield_state,
            funding_info=funding_info,
            stats_24h={"quoteVolume": volume_24h_usd} if (volume_24h_usd and volume_24h_usd > 0) else None,
            fund_matrix=fundamental_matrix,
            ob_setup=order_block_setup,
            alignment_score=float(alignment_score),
            meta_win_prob=float(horizon_prediction.get("consensus_probability", 0.50)) if horizon_prediction else 0.50,
            direction=direction,
            decision=canonical_strategy,
            spread_bps=spread_bps
        )
        is_asset_ntz = ntz_eval.get("is_ntz", False)

        # In micro-volatility / macro squeeze, hold back on middle chop to preserve capital,
        # but allow validated structural boundary touches and coiling breakout setups
        is_macro_dump = (
            btc_shield_state.get("regime") == "FLASH_DUMP" or
            btc_shield_state.get("status_code") in ["BEAR_CASCADE_BLACKOUT", "ALERT_DUMP", "FLASH_DUMP"] or
            "DEFENSIVE_CASH_ONLY" in str(btc_shield_state.get("altcoin_posture", ""))
        )
        is_prolonged_micro = bool(
            btc_shield_state.get("is_prolonged_micro_volatility") or
            "MICRO_VOLATILITY" in str(btc_shield_state.get("status_code", "")) or
            "MICRO_VOLATILITY" in str(btc_shield_state.get("reason", ""))
        )

        range_pos = 50.0
        if "1h" in dfs_9 and not dfs_9["1h"].empty:
            df_r = dfs_9["1h"]
            rh = float(df_r["high"].rolling(20).max().iloc[-1])
            rl = float(df_r["low"].rolling(20).min().iloc[-1])
            if (rh - rl) > 1e-8:
                range_pos = float(np.clip(((current_price - rl) / (rh - rl)) * 100.0, 0.0, 100.0))

        is_extreme_boundary = (range_pos <= 20.0 and direction == "LONG") or (range_pos >= 80.0 and direction == "SHORT")
        is_breakout_coiling = any(k in str(canonical_strategy).upper() for k in ["COILING", "EXPANSION", "BREAKOUT", "SQUEEZE_BREAKOUT"])

        if is_prolonged_micro:
            is_boundary_or_coiling = bool(is_ob_setup or is_extreme_boundary or is_breakout_coiling)
        else:
            is_boundary_or_coiling = bool(
                is_ob_setup or
                any(k in str(canonical_strategy).upper() for k in [
                    "ORDER_BLOCK", "BREAKER", "TURTLE_SOUP", "RANGE_SUPPORT",
                    "RANGE_RESISTANCE", "SUB_RANGE", "COILING", "EXPANSION", "BREAKOUT", "RANGE_BOUNCE"
                ])
            )

        effective_macro_ntz = is_macro_ntz
        if is_macro_ntz and not is_macro_dump:
            # Squeeze / micro-volatility NTZ: Permit decoupled independent trends and verified HTF order blocks
            if is_decoupled_alt or (is_ob_setup and horizon_label in ["1H", "24H"]):
                effective_macro_ntz = False

        is_ntz_active = effective_macro_ntz or is_asset_ntz
        ntz_reason = macro_ntz_reason if effective_macro_ntz else (
            ntz_eval.get("reasons", ["Asset in No Trade Zone"])[0] if ntz_eval.get("reasons") else "Asset in No Trade Zone"
        )

        # ---------------------------------------------------------------------
        # 3. Determine optimal entry limit and execution entry price
        # ---------------------------------------------------------------------
        is_squeeze_trans = bool(
            btc_shield_state.get("is_squeeze_transition") or
            (btc_shield_state.get("v16_regime") in ["BREAKOUT", "HIGH_VOLATILITY"] and
             (btc_shield_state.get("is_prolonged_micro_volatility") or btc_shield_state.get("is_squeeze") or float(btc_shield_state.get("bbw_percentile", 50.0)) <= 18.0))
        )
        atr_pct_for_chase = (active_atr / max(1e-8, current_price)) * 100.0 if (active_atr and current_price > 0) else 0.65
        chase_thresh = round(float(np.clip(atr_pct_for_chase * (0.95 if is_squeeze_trans else 1.35), 0.55 if is_squeeze_trans else 0.75, 2.50)), 2)

        entry_analysis = EntryConfirmationEngine.calculate_optimal_entry_zone(
            current_price=current_price,
            ob_setup=order_block_setup if is_ob_setup else None,
            direction=direction,
            active_atr=active_atr,
            chase_threshold_pct=chase_thresh,
            strategy=canonical_strategy,
            candle_metrics=candle_metrics
        )
        exec_entry_price = float(entry_analysis["optimal_entry_price"])

        # ---------------------------------------------------------------------
        # 4. Anchor Profit Targets and Stop Loss to authoritative execution price
        # ---------------------------------------------------------------------
        # Derive recent structural swing high and low (up to 48 completed candles)
        lookback_bars = min(48, max(5, len(df_active) - 1)) if (df_active is not None and not df_active.empty) else 0
        if lookback_bars >= 5:
            recent_high = float(df_active["high"].iloc[-lookback_bars:].max())
            recent_low = float(df_active["low"].iloc[-lookback_bars:].min())
        else:
            recent_high = exec_entry_price + (active_atr * 2.0)
            recent_low = exec_entry_price - (active_atr * 2.0)

        # Dynamic 24h Turnover Synthesis: If ticker volume is missing or zero, compute rolling 24h turnover from candles
        if (volume_24h_usd is None or volume_24h_usd <= 0.0) and dfs_9 and "1h" in dfs_9:
            df_1h = dfs_9["1h"]
            if df_1h is not None and len(df_1h) >= 5 and "volume" in df_1h.columns and "close" in df_1h.columns:
                volume_24h_usd = float((df_1h["close"].iloc[-24:].astype(float) * df_1h["volume"].iloc[-24:].astype(float)).sum())

        # Adaptive Low-Liquidity Tail Noise Multiplier:
        # For lower-volume pairs (< $2.5M), thin order books produce wider predatory wicks.
        # Widen the noise floor dynamically up to 1.35x so wicks do not prematurely trigger stops.
        tail_noise_mult = 1.0
        if volume_24h_usd and 0 < volume_24h_usd < 2_500_000.0:
            tail_noise_mult = float(np.clip(1.0 + 0.35 * ((2_500_000.0 - volume_24h_usd) / 2_500_000.0), 1.0, 1.35))

        # Phase 3: Volatility & Regime-Adaptive Multipliers (Dynamic across OB and Regular Setups)
        bbw_val = 3.0
        if df_active is not None and len(df_active) >= 20:
            try:
                c20 = df_active['close'].iloc[-20:].astype(float)
                ma20 = float(c20.mean())
                std20 = float(c20.std(ddof=0))
                if ma20 > 0:
                    bbw_val = ((2.0 * std20 * 2.0) / ma20) * 100.0
            except Exception as e:
                logger.debug(f"[SIGNAL GENERATOR] BBW calculation fallback: {e}")
                bbw_val = 3.0

        chop_val = float(ntz_eval.get("metrics", {}).get("chop_index", 50.0)) if (ntz_eval and ntz_eval.get("metrics")) else 50.0
        regime_upper = str(active_market_regime).upper()
        is_explicit_trend = any(k in regime_upper for k in ["BULL_TREND", "BEAR_TREND", "STRONG_BULL", "STRONG_BEAR", "TREND"]) and chop_val <= 50.0
        is_range_regime = (not is_explicit_trend) and (
            any(k in regime_upper for k in ["RANGE", "CONSOLIDATION", "CHOP", "SIDEWAYS"])
            or chop_val > 55.0
            or bbw_val <= 1.50
        )

        has_structural_anchor = bool(
            is_ob_setup or
            (order_block_setup and order_block_setup.get("order_block_zone")) or
            (candle_metrics and candle_metrics.get("swept_price"))
        )

        structural_anchor_info = None
        # Tactical 15M Higher Low / Lower High & Order Block Anchoring (Pure Price Action)
        if tf_key == "15m":
            if triad_structure is not None and getattr(triad_structure, "entry_anchor_pivot", None) is not None:
                if direction == "LONG":
                    hl_p = triad_structure.entry_anchor_pivot.price
                    ob_l = triad_structure.active_ob_15m.ob_low if triad_structure.active_ob_15m else None
                    ob_h = triad_structure.active_ob_15m.ob_high if triad_structure.active_ob_15m else None
                    opp_sh = triad_structure.opposing_target_pivot.price if triad_structure.opposing_target_pivot else recent_high
                    anchored = EntryConfirmationEngine.anchor_to_higher_low_and_ob(
                        df_15m=df_active,
                        hl_pivot_price=hl_p,
                        current_price=current_price,
                        bullish_ob_low=ob_l,
                        bullish_ob_high=ob_h,
                        opposing_sh_price=opp_sh,
                        spread_bps=spread_bps
                    )
                    exec_entry_price = float(anchored["entry_price"])
                    cand_sl = float(anchored["sl_price"])
                    cand_tp1 = float(anchored["tp1_price"])
                    cand_tp2 = float(anchored["tp2_price"])
                    cand_tp3 = float(anchored["tp3_price"])
                    cand_rr = f"1:{anchored['risk_reward_ratio']:.1f}"
                    entry_analysis["optimal_entry_price"] = exec_entry_price
                    entry_analysis["optimal_entry_limit"] = exec_entry_price
                    entry_analysis["entry_zone_min"] = anchored["entry_zone"][0]
                    entry_analysis["entry_zone_max"] = anchored["entry_zone"][1]
                    entry_analysis["is_limit_pending"] = (anchored["execution_mode"] == "RESTING_LIMIT")
                    entry_analysis["entry_mode"] = anchored["execution_mode"]
                    structural_anchor_info = anchored
                elif direction == "SHORT":
                    lh_p = triad_structure.entry_anchor_pivot.price
                    ob_l = triad_structure.active_ob_15m.ob_low if triad_structure.active_ob_15m else None
                    ob_h = triad_structure.active_ob_15m.ob_high if triad_structure.active_ob_15m else None
                    opp_sl = triad_structure.opposing_target_pivot.price if triad_structure.opposing_target_pivot else recent_low
                    anchored = EntryConfirmationEngine.anchor_to_lower_high_and_ob(
                        df_15m=df_active,
                        lh_pivot_price=lh_p,
                        current_price=current_price,
                        bearish_ob_low=ob_l,
                        bearish_ob_high=ob_h,
                        opposing_sl_price=opp_sl,
                        spread_bps=spread_bps
                    )
                    exec_entry_price = float(anchored["entry_price"])
                    cand_sl = float(anchored["sl_price"])
                    cand_tp1 = float(anchored["tp1_price"])
                    cand_tp2 = float(anchored["tp2_price"])
                    cand_tp3 = float(anchored["tp3_price"])
                    cand_rr = f"1:{anchored['risk_reward_ratio']:.1f}"
                    entry_analysis["optimal_entry_price"] = exec_entry_price
                    entry_analysis["optimal_entry_limit"] = exec_entry_price
                    entry_analysis["entry_zone_min"] = anchored["entry_zone"][0]
                    entry_analysis["entry_zone_max"] = anchored["entry_zone"][1]
                    entry_analysis["is_limit_pending"] = (anchored["execution_mode"] == "RESTING_LIMIT")
                    entry_analysis["entry_mode"] = anchored["execution_mode"]
                    structural_anchor_info = anchored

            # Dynamic 15M Higher Low / Lower High fallback if no triad pivot was bound
            if structural_anchor_info is None and df_active is not None and len(df_active) >= 10:
                try:
                    from app.quant_v16.market_structure import MarketStructureEngine
                    sh_list, sl_list = MarketStructureEngine.find_confirmed_fractals(df_active, timeframe="15m")
                    if direction == "LONG":
                        hl_candidates = [s for s in sl_list if s.structure_type == "HL" and not s.is_broken]
                        if not hl_candidates:
                            hl_candidates = [s for s in sl_list if s.structure_type == "HL"]
                        if hl_candidates:
                            hl_pivot_px = hl_candidates[-1].price
                        elif len(sl_list) >= 2 and sl_list[-1].price > min(s.price for s in sl_list[:-1]):
                            hl_pivot_px = sl_list[-1].price
                        else:
                            recent_lows = df_active["low"].iloc[-15:].astype(float).values
                            min_l = float(np.min(recent_lows))
                            emergent_hl = [float(p) for p in recent_lows if float(p) > min_l]
                            hl_pivot_px = float(emergent_hl[-1]) if emergent_hl else min_l
                        opp_sh_px = sh_list[-1].price if sh_list else recent_high
                        ob_l = float(order_block_setup["order_block_zone"][0]) if (order_block_setup and order_block_setup.get("order_block_zone") and len(order_block_setup["order_block_zone"]) >= 2) else None
                        ob_h = float(order_block_setup["order_block_zone"][1]) if (order_block_setup and order_block_setup.get("order_block_zone") and len(order_block_setup["order_block_zone"]) >= 2) else None
                        anchored = EntryConfirmationEngine.anchor_to_higher_low_and_ob(
                            df_15m=df_active,
                            hl_pivot_price=hl_pivot_px,
                            current_price=current_price,
                            bullish_ob_low=ob_l,
                            bullish_ob_high=ob_h,
                            opposing_sh_price=opp_sh_px,
                            spread_bps=spread_bps
                        )
                        exec_entry_price = float(anchored["entry_price"])
                        cand_sl = float(anchored["sl_price"])
                        cand_tp1 = float(anchored["tp1_price"])
                        cand_tp2 = float(anchored["tp2_price"])
                        cand_tp3 = float(anchored["tp3_price"])
                        cand_rr = f"1:{anchored['risk_reward_ratio']:.1f}"
                        entry_analysis["optimal_entry_price"] = exec_entry_price
                        entry_analysis["optimal_entry_limit"] = exec_entry_price
                        entry_analysis["entry_zone_min"] = anchored["entry_zone"][0]
                        entry_analysis["entry_zone_max"] = anchored["entry_zone"][1]
                        entry_analysis["is_limit_pending"] = (anchored["execution_mode"] == "RESTING_LIMIT")
                        entry_analysis["entry_mode"] = anchored["execution_mode"]
                        structural_anchor_info = anchored
                    elif direction == "SHORT":
                        lh_candidates = [s for s in sh_list if s.structure_type == "LH" and not s.is_broken]
                        if not lh_candidates:
                            lh_candidates = [s for s in sh_list if s.structure_type == "LH"]
                        if lh_candidates:
                            lh_pivot_px = lh_candidates[-1].price
                        elif len(sh_list) >= 2 and sh_list[-1].price < max(s.price for s in sh_list[:-1]):
                            lh_pivot_px = sh_list[-1].price
                        else:
                            recent_highs = df_active["high"].iloc[-15:].astype(float).values
                            max_h = float(np.max(recent_highs))
                            emergent_lh = [float(p) for p in recent_highs if float(p) < max_h]
                            lh_pivot_px = float(emergent_lh[-1]) if emergent_lh else max_h
                        opp_sl_px = sl_list[-1].price if sl_list else recent_low
                        ob_l = float(order_block_setup["order_block_zone"][0]) if (order_block_setup and order_block_setup.get("order_block_zone") and len(order_block_setup["order_block_zone"]) >= 2) else None
                        ob_h = float(order_block_setup["order_block_zone"][1]) if (order_block_setup and order_block_setup.get("order_block_zone") and len(order_block_setup["order_block_zone"]) >= 2) else None
                        anchored = EntryConfirmationEngine.anchor_to_lower_high_and_ob(
                            df_15m=df_active,
                            lh_pivot_price=lh_pivot_px,
                            current_price=current_price,
                            bearish_ob_low=ob_l,
                            bearish_ob_high=ob_h,
                            opposing_sl_price=opp_sl_px,
                            spread_bps=spread_bps
                        )
                        exec_entry_price = float(anchored["entry_price"])
                        cand_sl = float(anchored["sl_price"])
                        cand_tp1 = float(anchored["tp1_price"])
                        cand_tp2 = float(anchored["tp2_price"])
                        cand_tp3 = float(anchored["tp3_price"])
                        cand_rr = f"1:{anchored['risk_reward_ratio']:.1f}"
                        entry_analysis["optimal_entry_price"] = exec_entry_price
                        entry_analysis["optimal_entry_limit"] = exec_entry_price
                        entry_analysis["entry_zone_min"] = anchored["entry_zone"][0]
                        entry_analysis["entry_zone_max"] = anchored["entry_zone"][1]
                        entry_analysis["is_limit_pending"] = (anchored["execution_mode"] == "RESTING_LIMIT")
                        entry_analysis["entry_mode"] = anchored["execution_mode"]
                        structural_anchor_info = anchored
                except Exception as e:
                    logger.debug(f"[SIGNAL GENERATOR] Dynamic 15M HL/LH fallback anchor exception for {symbol}: {e}")

        if structural_anchor_info is not None:
            # Entry, SL, TP1, TP2, TP3 are authoritatively anchored to 15M Higher Low / Lower High and Order Block
            pass
        elif is_ob_setup:
            cand_tp1 = format_dynamic_precision(order_block_setup["tp1_price"])
            cand_tp2 = format_dynamic_precision(order_block_setup["tp2_price"])
            cand_tp3 = format_dynamic_precision(order_block_setup["tp3_price"])
            cand_sl = format_dynamic_precision(order_block_setup["sl_price"])

            min_ob_rr = 2.0 if is_range_regime else 2.5
            vol_cushion = max(active_atr * 0.50, 3.0 * (float(spread_bps) / 10000.0) * exec_entry_price)
            min_ob_sl_dist = max(active_atr * 0.85, exec_entry_price * 0.0120)
            if direction == "LONG":
                ob_low_bound = float(order_block_setup["order_block_zone"][0]) if (order_block_setup.get("order_block_zone") and len(order_block_setup["order_block_zone"]) >= 2) else cand_sl
                cushioned_sl = min(cand_sl, ob_low_bound - vol_cushion, exec_entry_price - min_ob_sl_dist)
                cand_sl = format_dynamic_precision(max(exec_entry_price * 0.001, cushioned_sl))

                if cand_sl >= exec_entry_price:
                    cand_sl = format_dynamic_precision(exec_entry_price - max(active_atr * 1.2, min_ob_sl_dist))

                sl_dist = max(1e-9, abs(exec_entry_price - cand_sl))
                min_tp1_dist = max(min_ob_rr * sl_dist, active_atr * (0.85 if is_range_regime else 1.25))
                min_tp2_dist = max((min_ob_rr + 1.0) * sl_dist, active_atr * (1.60 if is_range_regime else 2.25))
                min_tp3_dist = max((min_ob_rr + 2.5) * sl_dist, active_atr * (2.40 if is_range_regime else 3.50))

                if (cand_tp1 - exec_entry_price) < min_tp1_dist:
                    cand_tp1 = format_dynamic_precision(exec_entry_price + min_tp1_dist)
                if cand_tp2 <= cand_tp1 or (cand_tp2 - exec_entry_price) < min_tp2_dist:
                    cand_tp2 = format_dynamic_precision(max(cand_tp1 + (active_atr * 0.8), exec_entry_price + min_tp2_dist))
                if cand_tp3 <= cand_tp2 or (cand_tp3 - exec_entry_price) < min_tp3_dist:
                    cand_tp3 = format_dynamic_precision(max(cand_tp2 + (active_atr * 1.2), exec_entry_price + min_tp3_dist))
            else: # SHORT
                ob_high_bound = float(order_block_setup["order_block_zone"][1]) if (order_block_setup.get("order_block_zone") and len(order_block_setup["order_block_zone"]) >= 2) else cand_sl
                cushioned_sl = max(cand_sl, ob_high_bound + vol_cushion, exec_entry_price + min_ob_sl_dist)
                cand_sl = format_dynamic_precision(cushioned_sl)

                if cand_sl <= exec_entry_price:
                    cand_sl = format_dynamic_precision(exec_entry_price + max(active_atr * 1.2, min_ob_sl_dist))

                sl_dist = max(1e-9, abs(exec_entry_price - cand_sl))
                min_tp1_dist = max(min_ob_rr * sl_dist, active_atr * (0.85 if is_range_regime else 1.25))
                min_tp2_dist = max((min_ob_rr + 1.0) * sl_dist, active_atr * (1.60 if is_range_regime else 2.25))
                min_tp3_dist = max((min_ob_rr + 2.5) * sl_dist, active_atr * (2.40 if is_range_regime else 3.50))

                if (exec_entry_price - cand_tp1) < min_tp1_dist:
                    cand_tp1 = format_dynamic_precision(max(exec_entry_price * 0.001, exec_entry_price - min_tp1_dist))
                if cand_tp2 >= cand_tp1 or (exec_entry_price - cand_tp2) < min_tp2_dist:
                    cand_tp2 = format_dynamic_precision(max(exec_entry_price * 0.001, min(cand_tp1 - (active_atr * 0.8), exec_entry_price - min_tp2_dist)))
                if cand_tp3 >= cand_tp2 or (exec_entry_price - cand_tp3) < min_tp3_dist:
                    cand_tp3 = format_dynamic_precision(max(exec_entry_price * 0.001, min(cand_tp2 - (active_atr * 1.2), exec_entry_price - min_tp3_dist)))

            order_block_setup["invalidation_level"] = cand_sl

            # Primary R:R is anchored strictly to TP1
            actual_rr = round(abs(cand_tp1 - exec_entry_price) / max(1e-9, abs(exec_entry_price - cand_sl)), 2)
            cand_rr = f"1:{actual_rr:.1f}"
        elif direction == "LONG":
            if is_range_regime:
                tp1_mult = 2.00 * (0.90 if bbw_val <= 1.50 else 1.00)
                tp2_mult = 3.00 * (0.90 if bbw_val <= 1.50 else 1.00)
                tp3_mult = 4.50 * (0.90 if bbw_val <= 1.50 else 1.00)
            elif bbw_val <= 1.50:
                tp1_mult = 2.00
                tp2_mult = 3.00
                tp3_mult = 4.50
            elif bbw_val >= 4.50 and active_market_regime in ["TREND", "BULLISH", "BEARISH"]:
                tp1_mult = 2.50
                tp2_mult = 4.375
                tp3_mult = 6.875
            else:
                tp1_mult = 2.00
                tp2_mult = 3.50
                tp3_mult = 5.50

            # Phase 1 & 2: Dynamic Noise Floor & Structural Stop Loss Placement
            has_structural_anchor = bool(
                is_ob_setup or
                (order_block_setup and order_block_setup.get("order_block_zone")) or
                (candle_metrics and candle_metrics.get("swept_price"))
            )
            structural_low = recent_low
            if is_ob_setup and order_block_setup and order_block_setup.get("order_block_zone"):
                ob_z = order_block_setup["order_block_zone"]
                if len(ob_z) >= 1 and float(ob_z[0]) > 0:
                    structural_low = min(structural_low, float(ob_z[0]))
            if candle_metrics and candle_metrics.get("swept_price"):
                structural_low = min(structural_low, float(candle_metrics["swept_price"]))

            # For verified structural setups (Order Block / Liquidity Sweep), enforce realistic noise floor (>= 1.50% and >= 1.00x ATR)
            if has_structural_anchor:
                base_min_sl = max(exec_entry_price * 0.0150, active_atr * 1.00) if horizon_label == "15M" else max(exec_entry_price * 0.0180, active_atr * 1.20)
                vol_cushion = max(active_atr * 0.60, 4.0 * (float(spread_bps) / 10000.0) * exec_entry_price)
            else:
                base_min_sl = max(exec_entry_price * 0.0180, active_atr * 1.20) if horizon_label == "15M" else (active_atr * 1.50)
                vol_cushion = max(active_atr * 0.85, 4.0 * (float(spread_bps) / 10000.0) * exec_entry_price)

            min_sl_dist = base_min_sl * tail_noise_mult
            structural_sl = structural_low - vol_cushion
            max_sl_dist = max(min_sl_dist * 2.2, active_atr * 2.5)
            cand_sl_dist = float(np.clip(max(min_sl_dist, exec_entry_price - structural_sl), min_sl_dist, max_sl_dist))
            cand_sl = format_dynamic_precision(max(exec_entry_price * 0.001, exec_entry_price - cand_sl_dist))
            actual_sl_dist = exec_entry_price - cand_sl

            # Anchor primary TP1 dynamically: Strictly enforce institutional 1:2.0 R:R
            min_target_rr = 2.00
            if is_range_regime:
                range_eq = (recent_high + recent_low) / 2.0
                eq_dist = max(0.0, range_eq - exec_entry_price)
                target_tp1_dist = max(actual_sl_dist * min_target_rr, min(active_atr * 1.30, max(active_atr * 0.85, eq_dist)))
                target_tp2_dist = max(actual_sl_dist * 3.00, active_atr * 2.20, target_tp1_dist + active_atr * 0.6)
                target_tp3_dist = max(actual_sl_dist * 4.50, active_atr * 3.20, target_tp2_dist + active_atr * 0.8)
            else:
                target_tp1_dist = max(actual_sl_dist * min_target_rr, active_atr * 1.20)
                target_tp2_dist = max(actual_sl_dist * 3.00, active_atr * 2.20, target_tp1_dist + active_atr * 0.8)
                target_tp3_dist = max(actual_sl_dist * 4.50, active_atr * 3.50, target_tp2_dist + active_atr * 1.2)

            cand_tp1 = format_dynamic_precision(exec_entry_price + target_tp1_dist)
            cand_tp2 = format_dynamic_precision(exec_entry_price + target_tp2_dist)
            cand_tp3 = format_dynamic_precision(exec_entry_price + target_tp3_dist)
            actual_rr = round(abs(cand_tp1 - exec_entry_price) / max(1e-9, abs(exec_entry_price - cand_sl)), 2)
            cand_rr = f"1:{actual_rr:.1f}"
        else: # SHORT
            if is_range_regime:
                tp1_mult = 2.00 * (0.90 if bbw_val <= 1.50 else 1.00)
                tp2_mult = 3.00 * (0.90 if bbw_val <= 1.50 else 1.00)
                tp3_mult = 4.50 * (0.90 if bbw_val <= 1.50 else 1.00)
            elif bbw_val <= 1.50:
                tp1_mult = 2.00
                tp2_mult = 3.00
                tp3_mult = 4.50
            elif bbw_val >= 4.50 and active_market_regime in ["TREND", "BULLISH", "BEARISH"]:
                tp1_mult = 2.50
                tp2_mult = 4.375
                tp3_mult = 6.875
            else:
                tp1_mult = 2.00
                tp2_mult = 3.50
                tp3_mult = 5.50

            # Phase 1 & 2: Dynamic Noise Floor & Structural Stop Loss Placement for SHORT
            has_structural_anchor = bool(
                is_ob_setup or
                (order_block_setup and order_block_setup.get("order_block_zone")) or
                (candle_metrics and candle_metrics.get("swept_price"))
            )
            structural_high = recent_high
            if is_ob_setup and order_block_setup and order_block_setup.get("order_block_zone"):
                ob_z = order_block_setup["order_block_zone"]
                if len(ob_z) >= 2 and float(ob_z[1]) > 0:
                    structural_high = max(structural_high, float(ob_z[1]))
            if candle_metrics and candle_metrics.get("swept_price"):
                structural_high = max(structural_high, float(candle_metrics["swept_price"]))

            # For verified structural setups (Order Block / Liquidity Sweep), enforce realistic noise floor (>= 1.50% and >= 1.00x ATR)
            if has_structural_anchor:
                base_min_sl = max(exec_entry_price * 0.0150, active_atr * 1.00) if horizon_label == "15M" else max(exec_entry_price * 0.0180, active_atr * 1.20)
                vol_cushion = max(active_atr * 0.60, 4.0 * (float(spread_bps) / 10000.0) * exec_entry_price)
            else:
                base_min_sl = max(exec_entry_price * 0.0180, active_atr * 1.20) if horizon_label == "15M" else (active_atr * 1.50)
                vol_cushion = max(active_atr * 0.85, 4.0 * (float(spread_bps) / 10000.0) * exec_entry_price)

            min_sl_dist = base_min_sl * tail_noise_mult
            structural_sl = structural_high + vol_cushion
            max_sl_dist = max(min_sl_dist * 2.2, active_atr * 2.5)
            cand_sl_dist = float(np.clip(max(min_sl_dist, structural_sl - exec_entry_price), min_sl_dist, max_sl_dist))
            cand_sl = format_dynamic_precision(exec_entry_price + cand_sl_dist)
            actual_sl_dist = cand_sl - exec_entry_price

            # Anchor primary TP1 dynamically: Strictly enforce institutional 1:2.0 R:R
            min_target_rr = 2.00
            if is_range_regime:
                range_eq = (recent_high + recent_low) / 2.0
                eq_dist = max(0.0, exec_entry_price - range_eq)
                target_tp1_dist = max(actual_sl_dist * min_target_rr, min(active_atr * 1.30, max(active_atr * 0.85, eq_dist)))
                target_tp2_dist = max(actual_sl_dist * 3.00, active_atr * 2.20, target_tp1_dist + active_atr * 0.6)
                target_tp3_dist = max(actual_sl_dist * 4.50, active_atr * 3.20, target_tp2_dist + active_atr * 0.8)
            else:
                target_tp1_dist = max(actual_sl_dist * min_target_rr, active_atr * 1.20)
                target_tp2_dist = max(actual_sl_dist * 3.00, active_atr * 2.20, target_tp1_dist + active_atr * 0.8)
                target_tp3_dist = max(actual_sl_dist * 4.50, active_atr * 3.50, target_tp2_dist + active_atr * 1.2)

            cand_tp1 = format_dynamic_precision(max(exec_entry_price * 0.001, exec_entry_price - target_tp1_dist))
            cand_tp2 = format_dynamic_precision(max(exec_entry_price * 0.001, exec_entry_price - target_tp2_dist))
            cand_tp3 = format_dynamic_precision(max(exec_entry_price * 0.001, exec_entry_price - target_tp3_dist))
            actual_rr = round(abs(cand_tp1 - exec_entry_price) / max(1e-9, abs(exec_entry_price - cand_sl)), 2)
            cand_rr = f"1:{actual_rr:.1f}"

        if arch_type == InstitutionalArchetype.ARCHETYPE_C_RANGE_ROTATION.value:
            # Cap TP1, TP2, and TP3 dynamically within the HTF Range Extreme to prevent running into iron wall
            # while preserving strictly monotonic target spacing: entry < TP1 < TP2 < TP3 <= htf_high
            # and guaranteeing True Risk-to-Reward >= 1:1.50 in range, or >= 1:2.0 in structural anchor.
            min_rot_rr = (2.00 if has_structural_anchor else 1.50) if is_range_regime else 1.80
            if direction == "LONG" and archetype_info.get("htf_range_high"):
                htf_high = float(archetype_info["htf_range_high"])
                if htf_high > exec_entry_price:
                    avail_span = htf_high - exec_entry_price
                    cand_tp3 = min(cand_tp3, format_dynamic_precision(htf_high))
                    cand_tp2 = min(cand_tp2, format_dynamic_precision(exec_entry_price + (avail_span * 0.85)))
                    cand_tp1 = min(cand_tp1, format_dynamic_precision(exec_entry_price + (avail_span * 0.60)))
                    
                    # Ensure reward distance meets minimum required R:R without compressing Stop Loss
                    dynamic_buffer = max(exec_entry_price * 0.0005, active_atr * 0.05)
                    current_sl_dist = max(1e-9, exec_entry_price - cand_sl)
                    reward_dist = cand_tp1 - exec_entry_price
                    if (reward_dist / current_sl_dist) < min_rot_rr:
                        target_dist = current_sl_dist * min_rot_rr
                        if (exec_entry_price + target_dist) < (htf_high - dynamic_buffer):
                            cand_tp1 = format_dynamic_precision(exec_entry_price + target_dist)
                        else:
                            cand_tp1 = format_dynamic_precision(max(exec_entry_price + dynamic_buffer, exec_entry_price + (avail_span * 0.70)))
                    
                    # Ensure strictly monotonic target spacing: exec_entry_price < cand_tp1 < cand_tp2 < cand_tp3
                    rem_headroom = htf_high - cand_tp1
                    if rem_headroom >= dynamic_buffer:
                        cand_tp2 = format_dynamic_precision(cand_tp1 + (rem_headroom * 0.50))
                        cand_tp3 = format_dynamic_precision(htf_high)
                    else:
                        cand_tp2 = format_dynamic_precision(cand_tp1 + max(dynamic_buffer, active_atr * 0.40))
                        cand_tp3 = format_dynamic_precision(cand_tp2 + max(dynamic_buffer, active_atr * 0.60))
                    
                    actual_rr = round(abs(cand_tp1 - exec_entry_price) / max(1e-9, abs(exec_entry_price - cand_sl)), 2)
                    cand_rr = f"1:{actual_rr:.1f}"
            elif direction == "SHORT" and archetype_info.get("htf_range_low"):
                htf_low = float(archetype_info["htf_range_low"])
                if htf_low < exec_entry_price:
                    avail_span = exec_entry_price - htf_low
                    cand_tp3 = max(cand_tp3, format_dynamic_precision(htf_low))
                    cand_tp2 = max(cand_tp2, format_dynamic_precision(exec_entry_price - (avail_span * 0.85)))
                    cand_tp1 = max(cand_tp1, format_dynamic_precision(exec_entry_price - (avail_span * 0.60)))
                    
                    dynamic_buffer = max(exec_entry_price * 0.0005, active_atr * 0.05)
                    current_sl_dist = max(1e-9, cand_sl - exec_entry_price)
                    reward_dist = exec_entry_price - cand_tp1
                    if (reward_dist / current_sl_dist) < min_rot_rr:
                        target_dist = current_sl_dist * min_rot_rr
                        if (exec_entry_price - target_dist) > (htf_low + dynamic_buffer):
                            cand_tp1 = format_dynamic_precision(max(exec_entry_price * 0.001, exec_entry_price - target_dist))
                        else:
                            cand_tp1 = format_dynamic_precision(max(htf_low + dynamic_buffer, exec_entry_price - (avail_span * 0.70)))

                    # Ensure strictly monotonic target spacing: exec_entry_price > cand_tp1 > cand_tp2 > cand_tp3
                    rem_headroom = cand_tp1 - htf_low
                    if rem_headroom >= dynamic_buffer:
                        cand_tp2 = format_dynamic_precision(max(exec_entry_price * 0.001, cand_tp1 - (rem_headroom * 0.50)))
                        cand_tp3 = format_dynamic_precision(max(exec_entry_price * 0.001, htf_low))
                    else:
                        cand_tp2 = format_dynamic_precision(max(exec_entry_price * 0.001, cand_tp1 - max(dynamic_buffer, active_atr * 0.40)))
                        cand_tp3 = format_dynamic_precision(max(exec_entry_price * 0.001, cand_tp2 - max(dynamic_buffer, active_atr * 0.60)))

                    actual_rr = round(abs(cand_tp1 - exec_entry_price) / max(1e-9, abs(exec_entry_price - cand_sl)), 2)
                    cand_rr = f"1:{actual_rr:.1f}"

        # Liquidation Heatmap Magnet Snapping & Stop Loss Protection
        try:
            from app.services.institutional_intelligence_service import institutional_intelligence_service
            liq_heatmap = institutional_intelligence_service.get_liquidation_heatmap(
                symbol=symbol,
                current_price=exec_entry_price,
                atr=active_atr,
                recent_high=recent_high,
                recent_low=recent_low
            )
            sl_dist = abs(exec_entry_price - cand_sl)
            if direction == "LONG" and sl_dist > 0:
                # 1. Protect Stop Loss: Avoid resting inside High-Density 100x/50x Long Liquidation Pools
                long_pools = liq_heatmap.get("long_liquidation_pools", [])
                for pool in long_pools:
                    p_px = float(pool.get("price", 0.0))
                    if pool.get("density") in ["CRITICAL_MAGNET", "VERY_HIGH"] and abs(cand_sl - p_px) <= (0.25 * active_atr):
                        cand_sl = format_dynamic_precision(max(exec_entry_price * 0.001, min(cand_sl, p_px - (0.20 * active_atr))))
                        sl_dist = abs(exec_entry_price - cand_sl)

                # Phase 1: Dynamic Front-Running Offset for resting limit walls and liquidity pools
                front_run_offset = max(0.0008, 1.5 * (float(spread_bps) / 10000.0))

                # 2. Magnet Snapping for TP1 / TP2 into Short Liquidation Cascades with Front-Running Offset
                short_pools = liq_heatmap.get("short_liquidation_pools", [])
                for pool in short_pools:
                    p_px = float(pool.get("price", 0.0))
                    if p_px > exec_entry_price and pool.get("density") in ["CRITICAL_MAGNET", "VERY_HIGH"]:
                        if (p_px - exec_entry_price) >= (2.0 * sl_dist):
                            # If near TP1 (within 3.0%), snap TP1 inside the wall with front-running offset
                            if abs(p_px - cand_tp1) / cand_tp1 <= 0.030:
                                cand_tp1 = format_dynamic_precision(p_px * (1.0 - front_run_offset))
                                break
                            elif p_px > cand_tp1 and abs(p_px - cand_tp2) / cand_tp2 <= 0.040:
                                cand_tp2 = format_dynamic_precision(p_px * (1.0 - front_run_offset))
            elif direction == "SHORT" and sl_dist > 0:
                # 1. Protect Stop Loss: Avoid resting inside High-Density 100x/50x Short Liquidation Pools
                short_pools = liq_heatmap.get("short_liquidation_pools", [])
                for pool in short_pools:
                    p_px = float(pool.get("price", 0.0))
                    if pool.get("density") in ["CRITICAL_MAGNET", "VERY_HIGH"] and abs(cand_sl - p_px) <= (0.25 * active_atr):
                        cand_sl = format_dynamic_precision(max(cand_sl, p_px + (0.20 * active_atr)))
                        sl_dist = abs(exec_entry_price - cand_sl)

                # 2. Magnet Snapping for TP1 / TP2 into Long Liquidation Cascades with Front-Running Offset
                front_run_offset = max(0.0008, 1.5 * (float(spread_bps) / 10000.0))
                long_pools = liq_heatmap.get("long_liquidation_pools", [])
                for pool in long_pools:
                    p_px = float(pool.get("price", 0.0))
                    if 0 < p_px < exec_entry_price and pool.get("density") in ["CRITICAL_MAGNET", "VERY_HIGH"]:
                        if (exec_entry_price - p_px) >= (2.0 * sl_dist):
                            if abs(cand_tp1 - p_px) / cand_tp1 <= 0.030:
                                cand_tp1 = format_dynamic_precision(p_px * (1.0 + front_run_offset))
                                break
                            elif p_px < cand_tp1 and abs(cand_tp2 - p_px) / cand_tp2 <= 0.040:
                                cand_tp2 = format_dynamic_precision(p_px * (1.0 + front_run_offset))

            # Phase 1: Structural Swing High/Low Front-Running Snapping
            front_run_offset = max(0.0008, 1.5 * (float(spread_bps) / 10000.0))
            if direction == "LONG" and recent_high > exec_entry_price:
                if abs(recent_high - cand_tp1) / cand_tp1 <= 0.040:
                    cand_tp1 = format_dynamic_precision(recent_high * (1.0 - front_run_offset))
            elif direction == "SHORT" and 0 < recent_low < exec_entry_price:
                if abs(cand_tp1 - recent_low) / cand_tp1 <= 0.040:
                    cand_tp1 = format_dynamic_precision(recent_low * (1.0 + front_run_offset))

            # Preserve True R:R invariant
            min_heatmap_rr = 1.35 if is_range_regime else 2.0
            if direction == "LONG" and (cand_tp1 - exec_entry_price) < (min_heatmap_rr * sl_dist):
                cand_tp1 = format_dynamic_precision(exec_entry_price + (min_heatmap_rr * sl_dist))
            elif direction == "SHORT" and (exec_entry_price - cand_tp1) < (min_heatmap_rr * sl_dist):
                cand_tp1 = format_dynamic_precision(max(exec_entry_price * 0.001, exec_entry_price - (min_heatmap_rr * sl_dist)))

            actual_rr = round(abs(cand_tp1 - exec_entry_price) / max(1e-9, abs(exec_entry_price - cand_sl)), 2)
            cand_rr = f"1:{actual_rr:.1f}"

            # Phase 3: Volatility Headroom & Physical ATR Feasibility Band
            min_required_expansion = min_heatmap_rr * sl_dist
            n_candles_horizon = 8 if horizon_label == "15M" else (6 if horizon_label == "1H" else 4)
            k_regime = 0.85 if is_range_regime else 1.25
            max_feasible_expansion = max(min_required_expansion, active_atr * math.sqrt(n_candles_horizon) * k_regime)
            target_expansion = abs(cand_tp1 - exec_entry_price)
            feasibility_ratio = target_expansion / max(1e-8, max_feasible_expansion)

            if feasibility_ratio > 1.25:
                # Target exceeds physical candle bandwidth: compact cand_tp1 to maximum feasible expansion
                # while strictly guaranteeing True R:R invariant
                compacted_dist = max(min_required_expansion, max_feasible_expansion)
                compacted_tp1 = exec_entry_price + (compacted_dist if direction == "LONG" else -compacted_dist)
                cand_tp1 = format_dynamic_precision(max(exec_entry_price * 0.001, compacted_tp1))
                if direction == "LONG":
                    cand_tp2 = format_dynamic_precision(max(cand_tp1 + (active_atr * 0.6), cand_tp2))
                    cand_tp3 = format_dynamic_precision(max(cand_tp2 + (active_atr * 0.8), cand_tp3))
                else:
                    cand_tp2 = format_dynamic_precision(max(exec_entry_price * 0.001, min(cand_tp1 - (active_atr * 0.6), cand_tp2)))
                    cand_tp3 = format_dynamic_precision(max(exec_entry_price * 0.001, min(cand_tp2 - (active_atr * 0.8), cand_tp3)))
                actual_rr = round(abs(cand_tp1 - exec_entry_price) / max(1e-9, abs(exec_entry_price - cand_sl)), 2)
                cand_rr = f"1:{actual_rr:.1f}"
        except Exception as e:
            logger.debug(f"[SIGNAL GENERATOR] Target physical compaction exception for {symbol}: {e}")

        # Confluence bonuses from Institutional Intelligence Hub (Macro, Whales, Dominance, ETF):
        inst_conviction_bonus = 0.0
        try:
            from app.services.institutional_intelligence_service import institutional_intelligence_service
            clean_sym = symbol.split("/")[0].split(":")[0].upper()
            
            # 1. Hyperliquid Whale Wall alignment across ALL coins
            hl_radar = institutional_intelligence_service.get_hyperliquid_whale_radar(clean_sym)
            hl_bias = hl_radar.get("whale_bias", "")
            if direction == "LONG" and hl_bias in ["BULLISH_WHALE_BID_ABSORPTION", "BULLISH_AGGREGATE_BID_PRESSURE"]:
                inst_conviction_bonus += 5.0
            elif direction == "SHORT" and hl_bias in ["BEARISH_WHALE_ASK_RESISTANCE", "BEARISH_AGGREGATE_ASK_PRESSURE"]:
                inst_conviction_bonus += 5.0

            # 2. Spot ETF institutional momentum alignment
            if clean_sym in ["BTC", "ETH"]:
                etf_flows = institutional_intelligence_service.get_crypto_etf_flows()
                if direction == "LONG" and "ACCUMULATION" in etf_flows.get("institutional_bias", ""):
                    inst_conviction_bonus += 5.0
                elif direction == "SHORT" and etf_flows.get("veto_macro_btc_shorts"):
                    inst_conviction_bonus -= 10.0

            # 3. Capital rotation dominance alignment
            dom_matrix = institutional_intelligence_service.get_dominance_matrix()
            dom_regime = dom_matrix.get("capital_rotation_regime", "")
            if clean_sym not in ["BTC"]:
                if direction == "LONG" and dom_regime == "ALT_SEASON_EXPANSION":
                    inst_conviction_bonus += 5.0
                elif direction == "LONG" and dom_regime == "BITCOIN_DOMINANCE":
                    inst_conviction_bonus -= 8.0
        except Exception as e:
            logger.debug(f"[SIGNAL GENERATOR] Institutional intelligence bonus exception for {symbol}: {e}")

        base_conviction = 95.0 if horizon_label == "24H" else (90.0 if horizon_label == "1H" else 85.0)
        adj_conviction = min(98.0, max(50.0, base_conviction + inst_conviction_bonus))

        # ---------------------------------------------------------------------
        # Phase 4 Microstructure Physics Extraction
        # In local test environments without live WebSockets or Redis, orderbook depth and CVD divergence
        # fall back to conservative taker-buy volume estimates as documented.
        # ---------------------------------------------------------------------
        # 1. Taker Buy Ratio:
        tb_ratio = float(candle_metrics.get("taker_buy_ratio", 0.50) if candle_metrics else 0.50)
        # 2. CVD Divergence:
        cvd_default = float(np.clip(2.0 * tb_ratio - 1.0, -1.0, 1.0))
        cvd_raw = candle_metrics.get("cvd_surge_5") if candle_metrics else None
        cvd_val = float(cvd_raw) if (cvd_raw is not None and not (isinstance(cvd_raw, float) and np.isnan(cvd_raw))) else cvd_default
        # 3. Order Book Imbalance:
        obi_default = float(np.clip((tb_ratio - 0.50) * 2.0, -1.0, 1.0))
        obi_raw = candle_metrics.get("order_book_imbalance") if candle_metrics else None
        obi_val = float(obi_raw) if (obi_raw is not None and not (isinstance(obi_raw, float) and np.isnan(obi_raw))) else obi_default
        # 4. Volatility Ratio (ATR5 / ATR20):
        vol_ratio = 1.0
        if df_active is not None and len(df_active) >= 20:
            try:
                h_vals = df_active['high'].astype(float)
                l_vals = df_active['low'].astype(float)
                c_vals = df_active['close'].astype(float)
                tr_series = np.maximum(h_vals - l_vals, np.maximum(abs(h_vals - c_vals.shift(1)), abs(l_vals - c_vals.shift(1))))
                tr5 = tr_series.iloc[-5:].mean()
                tr20 = tr_series.iloc[-20:].mean()
                if tr20 > 1e-9:
                    vol_ratio = float(np.clip(tr5 / tr20, 0.1, 5.0))
            except Exception as e:
                logger.debug(f"[SIGNAL GENERATOR] Vol ratio calculation exception for {symbol}: {e}")
                vol_ratio = float(candle_metrics.get("expansion_ratio", 1.0) if candle_metrics else 1.0)
        elif candle_metrics and candle_metrics.get("expansion_ratio"):
            vol_ratio = float(np.clip(float(candle_metrics["expansion_ratio"]), 0.1, 5.0))

        # 5. RVOL (Relative Volume):
        rvol_val = 1.0
        if candle_metrics and candle_metrics.get("volume_surge_ratio"):
            rvol_val = float(np.clip(float(candle_metrics["volume_surge_ratio"]), 0.05, 10.0))
        elif df_active is not None and 'volume' in df_active.columns and len(df_active) >= 20:
            try:
                vols = df_active['volume'].astype(float)
                cand_idx = -2 if len(vols) >= 2 else -1
                hist_v = vols.iloc[:cand_idx] if len(vols) >= 3 else vols.iloc[:-1]
                v_cur = max(float(vols.iloc[cand_idx]), float(vols.iloc[-1]))
                v_ma20 = float(hist_v.iloc[-20:].mean()) if len(hist_v) >= 5 else float(vols.iloc[-20:].mean())
                if v_ma20 > 1e-9:
                    rvol_val = float(np.clip(v_cur / v_ma20, 0.05, 10.0))
            except Exception as e:
                logger.debug(f"[SIGNAL GENERATOR] RVOL calculation exception for {symbol}: {e}")
                rvol_val = 1.0

        # 6. Liquidity Proximity (Distance in % to nearest structural POI / order block / sweep level):
        liq_prox_pct = float(round(min(abs(exec_entry_price - cand_sl), abs(cand_tp1 - exec_entry_price)) / max(1e-9, exec_entry_price) * 100.0, 2))
        if is_ob_setup and order_block_setup and order_block_setup.get("order_block_zone"):
            ob_zone = order_block_setup["order_block_zone"]
            if len(ob_zone) >= 2:
                ob_mid = (float(ob_zone[0]) + float(ob_zone[1])) / 2.0
                if exec_entry_price > 0:
                    liq_prox_pct = float(round(abs(exec_entry_price - ob_mid) / exec_entry_price * 100.0, 2))
        elif candle_metrics and candle_metrics.get("swept_price"):
            swept_px = float(candle_metrics["swept_price"])
            if exec_entry_price > 0:
                liq_prox_pct = float(round(abs(exec_entry_price - swept_px) / exec_entry_price * 100.0, 2))

        # 7. Dynamic Funding Drag (basis points per 8h):
        funding_drag_bps = float(np.clip(float(current_funding_rate) * 10000.0 if abs(float(current_funding_rate)) < 0.1 else float(current_funding_rate), -50.0, 50.0))

        # Evaluate setup against this coin's dedicated Meta-Labeler
        cand_meta_payload = {
            "symbol": symbol,
            "horizon": horizon_label,
            "direction": direction,
            "entry_price": exec_entry_price,
            "tp1_price": cand_tp1,
            "sl_price": cand_sl,
            "conviction": adj_conviction,
            "expected_return_pct": abs(horizon_prediction.get("predicted_change_pct", 0.0)) if horizon_prediction else 0.0,
            "quality_grade": "Grade A+",
            "regime": active_market_regime,
            "market_regime": active_market_regime,
            "canonical_strategy": canonical_strategy,
            "is_order_block_signal": bool(is_ob_setup),
            "chop_index": float(candle_metrics.get("chop_index", chop_val) if candle_metrics else chop_val),
            "taker_buy_ratio": tb_ratio,
            "cvd_surge_5": cvd_val,
            "funding_rate": current_funding_rate,
            # Phase 4 Microstructure Physics Features:
            "f_cvd_divergence": cvd_val,
            "f_order_book_imbalance": obi_val,
            "f_volatility_ratio": vol_ratio,
            "f_taker_buy_ratio": tb_ratio,
            "f_liquidity_proximity": liq_prox_pct,
            "f_funding_drag": funding_drag_bps,
            "f_relative_volume": rvol_val
        }
        # Pure Signal Architecture: Primary Directional Probability & Expectancy
        # (Secondary meta-labeler retired: eliminates secondary ML overfitting & false vetoes)
        if horizon_prediction:
            if direction == "LONG":
                primary_dir_p = float(horizon_prediction.get("prob_bullish", horizon_prediction.get("consensus_probability", 0.65)))
            else:
                primary_dir_p = float(horizon_prediction.get("prob_bearish", horizon_prediction.get("consensus_probability", 0.65)))
        else:
            primary_dir_p = float(cand_meta_payload.get("conviction", 65.0)) / 100.0

        cand_meta_payload["consensus_probability"] = primary_dir_p
        cand_meta_payload["win_probability"] = primary_dir_p

        # Check evaluate_signal for mock compatibility in unit tests
        meta_eval = self.meta_labeler.evaluate_signal(symbol, cand_meta_payload, hurdle=0.50) if hasattr(self, "meta_labeler") and self.meta_labeler else {}
        base_win_p = float(meta_eval.get("win_probability", primary_dir_p)) if (meta_eval and "win_probability" in meta_eval) else primary_dir_p

        # ---------------------------------------------------------------------
        # Execution Friction & Net Mathematical Expectancy Gating
        # ---------------------------------------------------------------------
        # Authoritative Platt Sigmoid Calibration (Fix 5):
        # Eliminate probability inflation and guarantee positive Brier Skill (BSS > 0)
        from app.quant_v16.probability import ProbabilityCalibrator
        _platt = ProbabilityCalibrator(method="platt")
        calibrated_win_p = _platt.calibrate(base_win_p)
        p_tp1 = round(max(0.15, min(0.95, calibrated_win_p)), 4)
        p_tp2 = round(p_tp1 * 0.65, 4)
        p_tp3 = round(p_tp2 * 0.55, 4)
        p_sl = round(max(0.05, 1.0 - p_tp1), 4)

        # Directional Superiority Invariant:
        # A directional setup can never be executed if the calibrated probability of hitting Stop Loss
        # is greater than or equal to reaching Take Profit 1 (P(TP1) < 50.0% or P(SL) >= P(TP1)).
        is_prob_inferior = bool(p_tp1 < 0.50 or p_sl >= p_tp1 or calibrated_win_p < 0.50)
        prob_inferior_reason = f"Sub-50% directional probability (P(TP1)={p_tp1*100:.1f}% < 50.0% hurdle, P(SL)={p_sl*100:.1f}%)" if is_prob_inferior else ""

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
        vol_24h_usd = volume_24h_usd if (volume_24h_usd is not None and float(volume_24h_usd) > 0) else None
        if vol_24h_usd is None and "1d" in dfs_9 and not dfs_9["1d"].empty and "volume" in dfs_9["1d"].columns:
            last_vol = float(dfs_9["1d"]["volume"].iloc[-1])
            vol_24h_usd = last_vol * current_price if current_price > 0 else None

        # Dynamic Breakout Spread Cushion & First-Bar Asymmetry Modeling
        effective_spread_bps = float(spread_bps)
        breakout_spread_cushion_bps = 0.0
        if is_squeeze_trans:
            candle_expansion_pct = 1.0
            if df_active is not None and len(df_active) > 0 and "close" in df_active.columns:
                c_c = float(df_active["close"].iloc[-1])
                c_h = float(df_active["high"].iloc[-1]) if "high" in df_active.columns else c_c
                c_l = float(df_active["low"].iloc[-1]) if "low" in df_active.columns else c_c
                candle_expansion_pct = max(0.5, ((c_h - c_l) / max(1e-8, c_c)) * 100.0)

            vol_ref = float(vol_24h_usd) if (vol_24h_usd and vol_24h_usd > 0) else 5_000_000.0
            liquidity_scarcity_factor = max(1.0, math.sqrt(50_000_000.0 / max(1_000_000.0, vol_ref)))
            expansion_factor = max(0.2, candle_expansion_pct / 1.5)

            cushion = min(35.0, spread_bps * (1.0 + 0.5 * expansion_factor * (liquidity_scarcity_factor - 1.0)))
            effective_spread_bps = max(spread_bps, cushion)
            breakout_spread_cushion_bps = round(effective_spread_bps - spread_bps, 2)

        vol_usd_check = float(vol_24h_usd) if (vol_24h_usd and float(vol_24h_usd) > 0) else 25_000_000.0
        # For mid/tail pairs (coins 41-75, vol < $20M) with wider spreads (> 15 bps), route via passive resting limit
        # at the Higher Low / Lower High pullback zone to eliminate taker spread crossing and protect Net EV.
        if float(spread_bps) > 15.0 and vol_usd_check < 20_000_000.0 and not is_squeeze_trans:
            entry_analysis["is_limit_pending"] = True
            entry_analysis["entry_mode"] = "RESTING_LIMIT"

        is_passive_limit_entry = bool(entry_analysis.get("is_limit_pending", False) or entry_analysis.get("entry_mode") == "RESTING_LIMIT")
        exec_assumption = ExecutionAssumption.STRESS if is_squeeze_trans else (ExecutionAssumption.OPTIMISTIC if is_passive_limit_entry else ExecutionAssumption.BASE)
        cost_spread_bps = effective_spread_bps * 0.50 if (is_passive_limit_entry and not is_squeeze_trans) else effective_spread_bps

        cost_breakdown = self.cost_engine.estimate_costs(
            market_type="futures",
            observed_spread_bps=cost_spread_bps,
            est_holding_hours=holding_hours,
            current_funding_rate=current_funding_rate,
            assumption=exec_assumption,
            position_size_usd=1000.0,
            volume_24h_usd=vol_24h_usd,
            funding_interval_hours=8.0,
            is_squeeze_transition=is_squeeze_trans
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

        # Dynamic Effective R:R Calculation accounting for Spread Widening and Slippage Drag
        total_friction_pct = cost_breakdown.total_cost_pct / 100.0
        friction_drag = total_friction_pct * exec_entry_price
        gross_reward = abs(cand_tp1 - exec_entry_price)
        gross_risk = abs(exec_entry_price - cand_sl)

        # Quantitative Hurdle Invariant: Ensure target dynamically accounts for friction so net R:R >= 2.00
        min_net_target_rr = 2.00
        needed_gross_reward = (min_net_target_rr * gross_risk) + ((min_net_target_rr + 1.0) * friction_drag)
        max_safe_tp_dist = active_atr * 2.80
        if gross_reward < needed_gross_reward and needed_gross_reward <= max_safe_tp_dist:
            gross_reward = needed_gross_reward
            if direction == "LONG":
                cand_tp1 = format_dynamic_precision(exec_entry_price + gross_reward)
            else:
                cand_tp1 = format_dynamic_precision(max(exec_entry_price * 0.001, exec_entry_price - gross_reward))
            actual_rr = round(abs(cand_tp1 - exec_entry_price) / max(1e-9, gross_risk), 2)
            cand_rr = f"1:{actual_rr:.1f}"
            # Re-evaluate net expectation with updated TP1 target
            exp_res = self.expectancy_engine.evaluate(
                entry=exec_entry_price,
                sl=cand_sl,
                tp1=cand_tp1,
                tp2=cand_tp2,
                tp3=cand_tp3,
                direction=direction,
                path_probs=path_probs,
                costs=cost_breakdown
            )
            ev_result = exp_res

        net_reward = max(0.0, gross_reward - friction_drag)
        net_risk = gross_risk + friction_drag
        effective_rr = round(net_reward / max(1e-8, net_risk), 2)

        # Phase 3 Feasibility Validation Gate (Target must be physically reachable within horizon)
        is_volatility_headroom_vetoed = False
        volatility_headroom_reason = ""
        if 'feasibility_ratio' in locals() and feasibility_ratio > 1.25 and ev_result.expected_net_return_pct < 0.25:
            is_volatility_headroom_vetoed = True
            volatility_headroom_reason = f"Target expansion ({target_expansion:.4f} > 1.25x max feasible {max_feasible_expansion:.4f}) with compacted net EV {ev_result.expected_net_return_pct:.2f}% < 0.25% minimum hurdle"

        # Phase 4 Multi-Horizon Institutional Taker Delta Confluence
        def _get_df_tbr(df_in: Optional[pd.DataFrame]) -> Optional[float]:
            if df_in is None or len(df_in) < 2:
                return None
            if "taker_buy_vol" in df_in.columns and "volume" in df_in.columns:
                tb = float(df_in["taker_buy_vol"].iloc[-5:].sum())
                v_tot = float(df_in["volume"].iloc[-5:].sum())
                if v_tot > 1e-8:
                    return float(np.clip(tb / v_tot, 0.0, 1.0))
            if "close" in df_in.columns and "open" in df_in.columns and "high" in df_in.columns and "low" in df_in.columns:
                c_s = df_in["close"].iloc[-5:].astype(float)
                o_s = df_in["open"].iloc[-5:].astype(float)
                h_s = df_in["high"].iloc[-5:].astype(float)
                l_s = df_in["low"].iloc[-5:].astype(float)
                rng_s = (h_s - l_s).clip(lower=1e-8)
                z_s = (c_s - o_s) / rng_s
                p_b = 0.5 * (1.0 + np.tanh(z_s * 0.7978845608))
                return float(np.clip(p_b.mean(), 0.0, 1.0))
            return None

        tb_1h = _get_df_tbr(dfs_9.get("1h")) if dfs_9 else None
        tb_4h = _get_df_tbr(dfs_9.get("4h")) if dfs_9 else None

        is_delta_confluent = True
        delta_confluence_reason = ""
        is_boundary_harvest = any(k in str(canonical_strategy).upper() for k in ["RECTANGLE", "BOUNDARY", "TURTLE_SOUP", "RANGE_BOUND", "ROTATION"])
        if not is_boundary_harvest:
            if direction == "LONG":
                if (tb_1h is not None and tb_1h < 0.48) or (tb_4h is not None and tb_4h < 0.46):
                    is_delta_confluent = False
                    delta_confluence_reason = f"Adverse HTF taker flow for Long (1H TBR: {tb_1h if tb_1h is not None else 0.50:.2f} < 0.48 or 4H TBR: {tb_4h if tb_4h is not None else 0.50:.2f} < 0.46)"
            else: # SHORT
                if (tb_1h is not None and tb_1h > 0.52) or (tb_4h is not None and tb_4h > 0.54):
                    is_delta_confluent = False
                    delta_confluence_reason = f"Adverse HTF taker flow for Short (1H TBR: {tb_1h if tb_1h is not None else 0.50:.2f} > 0.52 or 4H TBR: {tb_4h if tb_4h is not None else 0.50:.2f} > 0.54)"

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
        is_macro_pause = False
        macro_pause_msg = ""
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
            is_macro_pause = is_macro_blackout
            macro_pause_msg = macro_blackout_reason

        # News & Event Gating (Black Swan Sentinel & NWS-01 Macro Blackout)
        is_news_vetoed = False
        news_veto_reason = ""
        clean_sym_news = symbol.split("/")[0].split(":")[0].upper()
        acute_news_keywords = ["hack", "exploit", "sec lawsuit", "insolvency", "freeze withdrawal", "emergency upgrade", "fbi", "doj indictment", "halt trading", "depeg"]
        has_breaking_shock = any(kw in news_headline.lower() for kw in acute_news_keywords) if news_headline else False

        # Disambiguate Systemic Shock vs Asset-Specific Protocol Shock:
        systemic_shock_keywords = ["crypto ban", "global ban", "feds seize", "binance insolvency", "tether depeg", "usdt depeg", "stablecoin run", "sec crypto ban"]
        is_systemic_shock = any(skw in news_headline.lower() for skw in systemic_shock_keywords) if news_headline else False
        is_asset_specific_shock = bool(
            has_breaking_shock and not is_systemic_shock and (
                clean_sym_news.lower() in news_headline.lower() or
                (fund_matrix and fund_matrix.get("symbol", "").upper() == symbol.upper())
            )
        )
        is_relevant_shock = is_systemic_shock or is_asset_specific_shock or has_breaking_shock

        if is_macro_blackout:
            # During acute US Macro Volatility Blackout, pause blind market orders to avoid spike slippage.
            # Exempt deep structural Order Block resting limits and Higher Low / Lower High pullback limits
            # which safely absorb panic liquidity wicks at predetermined structural price zones.
            is_limit_exempt = bool(
                entry_analysis.get("is_limit_pending") or
                (structural_anchor_info and structural_anchor_info.get("execution_mode") == "RESTING_LIMIT")
            )
            if not is_limit_exempt:
                is_news_vetoed = True
                news_veto_reason = f"🚨 {macro_blackout_reason}"
        elif is_relevant_shock and has_breaking_shock:
            if direction == "LONG":
                # Acute breaking negative shock halts LONG entries (avoid catching falling knives)
                is_news_vetoed = True
                news_veto_reason = f"🚨 Acute Breaking News Shock Alert: {news_headline[:60]}"
            elif direction == "SHORT":
                # For SHORT setups, negative breaking shocks provide downward directional alignment
                # unless the headline indicates hyper-bullish sentiment
                if (has_severe_positive_news and "BULLISH" in news_label.upper()) or news_score >= 0.40:
                    is_news_vetoed = True
                    news_veto_reason = f"🚨 Hyper-Bullish News Sentinel ({news_label}): {news_headline[:60]}"
        elif direction == "LONG":
            if has_severe_negative_news or news_score <= -0.40:
                is_news_vetoed = True
                news_veto_reason = f"🚨 Black Swan / Negative News Sentinel ({news_label}): {news_headline[:60]}"
            elif is_sell_the_news:
                # If within 12h of catalyst execution, sell-the-news danger is high
                is_news_vetoed = True
                news_veto_reason = f"⚠️ Sell-The-News Danger Zone: <12h to {cat_title[:50]}"
        elif direction == "SHORT":
            if (has_severe_positive_news and "BULLISH" in news_label.upper()) or news_score >= 0.50:
                is_news_vetoed = True
                news_veto_reason = f"🚨 Hyper-Bullish News Sentinel ({news_label}): {news_headline[:60]}"
            elif is_pre_event:
                # If in pre-event catalyst accumulation window, shorting is dangerous
                is_news_vetoed = True
                news_veto_reason = f"⚠️ Pre-Catalyst Accumulation Runup: <10d to {cat_title[:50]}"

        # Intraday Flash Liquidity Drain & Dynamic Spread Gating
        is_flash_drain = False
        flash_drain_reason = ""
        vol_usd_liq = float(volume_24h_usd) if (volume_24h_usd and float(volume_24h_usd) > 0) else 5_000_000.0
        target_dist_pct = abs(cand_tp1 - entry_analysis["optimal_entry_price"]) / max(1e-8, entry_analysis["optimal_entry_price"]) * 100.0

        # Dynamic Spread Ceiling tailored to Universe Liquidity (Coins 1-75):
        # Tier-1 Mega/High-volume pairs (>= $20M) enforce strict 20.0 bps limit on 15M scalps.
        # Ranked 41-75 mid/tail pairs ($1M to $20M) receive adaptive spread headroom up to 35.0 bps
        # proportional to expected TP1 distance (preventing false off-peak blowouts while preserving EV_net > 0).
        if vol_usd_liq >= 20_000_000.0:
            max_allowed_spread = 20.0 if horizon_label == "15M" else (28.0 if horizon_label == "1H" else 35.0)
        else:
            dynamic_tail_cap = min(35.0, max(22.0, (target_dist_pct * 100.0) * 0.18))
            max_allowed_spread = dynamic_tail_cap if horizon_label == "15M" else (dynamic_tail_cap + 8.0 if horizon_label == "1H" else 45.0)

        if float(spread_bps) > max_allowed_spread:
            is_flash_drain = True
            flash_drain_reason = f"Flash spread blowout ({spread_bps:.1f} bps > {max_allowed_spread:.1f} bps limit)"
        elif candle_metrics and candle_metrics.get("is_flash_liquidity_drain"):
            is_flash_drain = True
            flash_drain_reason = str(candle_metrics.get("flash_drain_reason", "Acute volume vacuum on trigger bar"))
        elif df_active is not None and "volume" in df_active.columns and len(df_active) >= 10:
            try:
                cand_idx = -2 if len(df_active) >= 2 else -1
                hist_slice = df_active["volume"].iloc[:cand_idx] if len(df_active) >= 3 else df_active["volume"].iloc[:-1]
                base_v = float(hist_slice.iloc[-20:].mean()) if len(hist_slice) >= 5 else 0.0
                curr_v = float(df_active["volume"].iloc[cand_idx])
                curr_to = curr_v * current_price
                if base_v > 0 and (curr_v / base_v < 0.12):
                    is_flash_drain = True
                    flash_drain_reason = f"Acute volume collapse ({curr_v/base_v:.2f}x avg < 0.12x)"
                else:
                    min_candle_to = max(1000.0, (float(volume_24h_usd) / 96.0) * 0.04) if (volume_24h_usd and volume_24h_usd > 0) else 2500.0
                    if 0 < curr_to < min_candle_to:
                        is_flash_drain = True
                        flash_drain_reason = f"Sub-threshold turnover (${curr_to:,.0f} < ${min_candle_to:,.0f} on candle)"
            except Exception as e:
                logger.debug(f"[SIGNAL GENERATOR] Flash drain evaluation exception for {symbol}: {e}")
                is_flash_drain = False

        # First-Bar Breakout Spread Asymmetry Breaker & Risk Gate
        is_breakout_spread_asymmetric = False
        asymmetry_reason = ""
        if is_squeeze_trans:
            friction_to_tp1_ratio = cost_breakdown.total_cost_pct / max(0.01, target_dist_pct)
            max_allowed_breakout_spread = 12.0 if horizon_label == "15M" else (16.0 if horizon_label == "1H" else 22.0)

            if float(spread_bps) > max_allowed_breakout_spread:
                is_breakout_spread_asymmetric = True
                asymmetry_reason = f"Breakout spread blowout ({spread_bps:.1f} bps > {max_allowed_breakout_spread:.1f} bps limit)"
            elif friction_to_tp1_ratio > 0.40:
                is_breakout_spread_asymmetric = True
                asymmetry_reason = f"Friction consumes {friction_to_tp1_ratio*100:.1f}% of TP1 target (> 40.0% limit)"

        # Low-cap excessive slippage gate: If modeled slippage exceeds adaptive ratio of TP1 target, fail closed
        is_excessive_slippage = False
        slippage_reason = ""
        slip_threshold_ratio = 0.35 if vol_usd_liq >= 20_000_000.0 else 0.45
        if cost_breakdown.slippage_pct > (slip_threshold_ratio * max(0.10, target_dist_pct)):
            is_excessive_slippage = True
            slippage_reason = f"Modeled slippage {cost_breakdown.slippage_pct:.3f}% exceeds {slip_threshold_ratio*100:.0f}% of TP1 distance ({target_dist_pct:.2f}%)"

        # Prolonged Single-Side Order Book Void Sentinel
        is_order_book_void = False
        order_book_void_reason = ""
        if bid_price > 0.0 or ask_price > 0.0:
            if bid_price <= 1e-8 or ask_price <= 1e-8:
                is_order_book_void = True
                order_book_void_reason = f"Missing quote side (bid={bid_price:.6f}, ask={ask_price:.6f})"
            elif current_price > 0.0 and (bid_price < current_price * 0.85 or ask_price > current_price * 1.15):
                is_order_book_void = True
                order_book_void_reason = f"Severe quote dislocation >15% off market (bid={bid_price:.4f}, ask={ask_price:.4f}, last={current_price:.4f})"
            elif (ask_price - bid_price) / max(1e-8, ask_price) > 0.05:
                is_order_book_void = True
                order_book_void_reason = f"Order book spread blowout {((ask_price - bid_price) / ask_price * 10000.0):.1f} bps > 500 bps limit"
        if not is_order_book_void and float(spread_bps) > 500.0:
            is_order_book_void = True
            order_book_void_reason = f"Modeled book spread blowout ({spread_bps:.1f} bps > 500 bps limit)"

        # Low-liquidity gate: Below $250k daily volume, order books are too thin for institutional execution.
        # For tail pairs between $250k and $1.0M, require verified institutional pattern confirmation and tight spread (<= 20 bps)
        is_sub_threshold_illiquid = False
        illiquidity_reason = ""
        if volume_24h_usd and 0 < volume_24h_usd < 250_000.0:
            is_sub_threshold_illiquid = True
            illiquidity_reason = f"${volume_24h_usd/1e3:.0f}k < $250k minimum viable daily volume"
        elif volume_24h_usd and 250_000.0 <= volume_24h_usd < 1_000_000.0:
            has_strong_setup = bool(
                is_ob_setup or
                (candle_metrics and candle_metrics.get("is_sweep_reclaim")) or
                (candle_metrics and candle_metrics.get("is_engulfing"))
            )
            if not has_strong_setup:
                is_sub_threshold_illiquid = True
                illiquidity_reason = f"${volume_24h_usd/1e6:.2f}M tail pair requires confirmed OB or Sweep Reclaim"
            elif float(spread_bps) > 20.0:
                is_sub_threshold_illiquid = True
                illiquidity_reason = f"Tail pair spread {spread_bps:.1f} bps > 20.0 bps limit on ${volume_24h_usd/1e6:.2f}M volume"

        is_radar_eligible = False

        if is_sub_threshold_illiquid:
            status = "HOLD_VETOED_BY_SUB_THRESHOLD_ILLIQUIDITY"
            trade_active = False
            grade = f"Grade C (SUB-THRESHOLD ILLIQUIDITY: {illiquidity_reason})"
            conviction = 0.0
            tp1_price = cand_tp1
            tp2_price = cand_tp2
            tp3_price = cand_tp3
            sl_price = cand_sl
            rr_ratio = cand_rr
        elif is_order_book_void:
            status = "HOLD_VETOED_BY_ORDER_BOOK_VOID"
            trade_active = False
            grade = f"Grade C (ORDER BOOK VOID: {order_book_void_reason})"
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
        elif is_breakout_spread_asymmetric:
            status = "HOLD_VETOED_BY_BREAKOUT_SPREAD_ASYMMETRY"
            trade_active = False
            grade = f"Grade C (BREAKOUT SPREAD ASYMMETRY: {asymmetry_reason})"
            conviction = 0.0
            tp1_price = cand_tp1
            tp2_price = cand_tp2
            tp3_price = cand_tp3
            sl_price = cand_sl
            rr_ratio = cand_rr
        elif is_excessive_slippage:
            status = "HOLD_VETOED_BY_EXCESSIVE_SLIPPAGE"
            trade_active = False
            grade = f"Grade C (EXCESSIVE SLIPPAGE: {slippage_reason})"
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
        elif is_macro_pause:
            status = "HOLD_MACRO_VOLATILITY_BLACKOUT"
            trade_active = False
            grade = f"Grade C ({macro_pause_msg})"
            conviction = 40.0
            tp1_price = cand_tp1
            tp2_price = cand_tp2
            tp3_price = cand_tp3
            sl_price = cand_sl
            rr_ratio = cand_rr
        elif not is_candle_confirmed:
            if candle_metrics and candle_metrics.get("is_news_volatility_shock"):
                status = "HOLD_FLASH_NEWS_VOLATILITY_SHOCK"
                grade = f"Grade C (NEWS VOLATILITY SHOCK: {candle_trigger_reason})"
            else:
                status = "HOLD_AWAITING_CANDLE_TRIGGER_CONFIRMATION"
                grade = f"Grade C (AWAITING CANDLE TRIGGER: {candle_trigger_reason})"
            trade_active = False
            conviction = float(meta_eval.get("win_probability_pct", 65.0))
            tp1_price = cand_tp1
            tp2_price = cand_tp2
            tp3_price = cand_tp3
            sl_price = cand_sl
            rr_ratio = cand_rr
        elif is_prob_inferior:
            status = "HOLD_VETOED_BY_SUB_50_WIN_PROBABILITY"
            trade_active = False
            grade = f"Grade C ({prob_inferior_reason})"
            conviction = round(float(np.clip(calibrated_win_p * 100.0, 10.0, 49.9)), 1)
            tp1_price = cand_tp1
            tp2_price = cand_tp2
            tp3_price = cand_tp3
            sl_price = cand_sl
            rr_ratio = cand_rr
        elif not is_delta_confluent:
            status = "HOLD_VETOED_BY_TAKER_DELTA_CONFLUENCE"
            trade_active = False
            grade = f"Grade C (TAKER DELTA DIVERGENCE: {delta_confluence_reason})"
            conviction = 0.0
            tp1_price = cand_tp1
            tp2_price = cand_tp2
            tp3_price = cand_tp3
            sl_price = cand_sl
            rr_ratio = cand_rr
        elif not ev_result.passes_ev_hurdle or ev_result.expected_net_return_pct <= 0.0:
            status = "HOLD_FILTERED_BY_NEGATIVE_NET_EXPECTANCY" if ev_result.expected_net_return_pct <= 0.0 else "HOLD_UNFAVORABLE_RISK_REWARD"
            trade_active = False
            grade = f"Grade C ({ev_result.decision_reason})"
            conviction = float(meta_eval.get("win_probability_pct", 65.0))
            tp1_price = cand_tp1
            tp2_price = cand_tp2
            tp3_price = cand_tp3
            sl_price = cand_sl
            rr_ratio = cand_rr
            is_radar_eligible = True
        elif is_volatility_headroom_vetoed:
            status = "HOLD_VETOED_BY_VOLATILITY_HEADROOM"
            trade_active = False
            grade = f"Grade C (VOLATILITY HEADROOM VETO: {volatility_headroom_reason})"
            conviction = 0.0
            tp1_price = cand_tp1
            tp2_price = cand_tp2
            tp3_price = cand_tp3
            sl_price = cand_sl
            rr_ratio = cand_rr
        elif effective_rr < 1.20 or actual_rr < 2.00:
            status = "HOLD_INSUFFICIENT_RISK_REWARD" if actual_rr < 2.00 else "HOLD_SPREAD_DEGRADED_RR"
            trade_active = False
            grade = f"Grade C (INSUFFICIENT RISK-REWARD: Effective 1:{effective_rr:.2f} / Actual 1:{actual_rr:.2f} < 1:2.00 required)"
            conviction = float(meta_eval.get("win_probability_pct", 65.0))
            tp1_price = cand_tp1
            tp2_price = cand_tp2
            tp3_price = cand_tp3
            sl_price = cand_sl
            rr_ratio = f"1:{effective_rr:.1f}"
            is_radar_eligible = True
        else:
            status = "ACTIVE_SIGNAL"
            trade_active = True

            # Authoritative Grade Derivation matching ExpectancyEngine & V16SignalScorer
            ev_net_val = ev_result.expected_net_return_pct
            if ev_net_val >= 1.00 and p_tp1 >= 0.65:
                grade_prefix = "💎 Grade A+"
            elif ev_net_val >= 0.50 and p_tp1 >= 0.55:
                grade_prefix = "⚡ Grade A"
            elif ev_net_val >= 0.25 and p_tp1 >= 0.50:
                grade_prefix = "⚖️ Grade B"
            else:
                grade_prefix = "⚖️ Grade B"

            # Dynamic conviction strictly tied to calibrated probability
            calibrated_conviction = round(float(np.clip(calibrated_win_p * 100.0, 50.0, 95.0)), 1)
            conviction = calibrated_conviction

            if is_ob_setup:
                rank_lbl = order_block_setup.get("zeiierman_rank_label", "INSTITUTIONAL SMC POI")
                resolved_ob_rank_for_grade = int(order_block_setup.get("zeiierman_rank", 99))
                candle_pattern_name = candle_metrics.get("pattern", "") if candle_metrics else ""
                if candle_pattern_name and resolved_ob_rank_for_grade > 2:
                    grade = f"{grade_prefix} ({candle_pattern_name} @ {rank_lbl})"
                else:
                    grade = f"{grade_prefix} ({canonical_strategy} @ {rank_lbl})"
                arch_strategy = canonical_strategy
            elif "LIQUIDITY_RECLAIM" in str(canonical_strategy).upper():
                grade = f"{grade_prefix} (LIQUIDITY_RECLAIM: Confirmed Institutional Reversal in {direction} Direction)"
                arch_strategy = canonical_strategy
            elif arch_strategy == "DIRECTIONAL_BREAKOUT_EXPANSION":
                grade = f"{grade_prefix} (DIRECTIONAL BREAKOUT EXPANSION: Macro Range Breakout in {direction} Direction)"
                arch_strategy = canonical_strategy
            elif arch_type == InstitutionalArchetype.ARCHETYPE_B_COILING_BREAKOUT.value:
                grade = f"{grade_prefix} (COILING BREAKOUT: 15M Squeeze into 1D {direction} Expansion)"
                arch_strategy = canonical_strategy
            elif arch_type == InstitutionalArchetype.ARCHETYPE_C_RANGE_ROTATION.value:
                grade = f"{grade_prefix} (RANGE ROTATION: 1D Range Mean Reversion to {arch_headroom:.1f}% Boundary)"
                arch_strategy = canonical_strategy
            elif horizon_label == "24H":
                grade = f"{grade_prefix} (24H STRICT 7-HORIZON ALIGNMENT: 15M-15D UNANIMOUS)"
                arch_strategy = canonical_strategy
            elif horizon_label == "1H":
                grade = f"{grade_prefix} (1H STRICT 7-HORIZON ALIGNMENT: 5M-7D UNANIMOUS)"
                arch_strategy = canonical_strategy
            else: # 15M
                grade = f"{grade_prefix} (15M STRICT 6-HORIZON ALIGNMENT: 5M-24H UNANIMOUS)"
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
            min_rel_sl_pct = max(0.0050, 3.0 * (float(spread_bps) / 10000.0))
            if exec_entry_price <= 0.0001 or sl_price <= 0.0001 or tp1_price <= 0.0001:
                trade_active = False
                status = "REJECTED_ZERO_PRICE"
            elif abs(exec_entry_price - sl_price) <= 1e-8:
                trade_active = False
                status = "REJECTED_ZERO_DISTANCE_SL"
            elif (abs(exec_entry_price - sl_price) / max(1e-9, exec_entry_price)) < min_rel_sl_pct:
                trade_active = False
                status = "REJECTED_MICRO_SL_NOISE"
            elif direction == "LONG" and not (sl_price < exec_entry_price < tp1_price < tp2_price < tp3_price):
                trade_active = False
                status = "REJECTED_PRICE_GEOMETRY"
            elif direction == "SHORT" and not (sl_price > exec_entry_price > tp1_price > tp2_price > tp3_price):
                trade_active = False
                status = "REJECTED_PRICE_GEOMETRY"

        pred_target = float(horizon_prediction.get("predicted_target_price", current_price)) if horizon_prediction else current_price
        pred_pct = abs(float(horizon_prediction.get("predicted_change_pct", 0.0))) if horizon_prediction else 0.0

        if structural_anchor_info is not None and structural_anchor_info.get("decision_label"):
            decision_str = structural_anchor_info["decision_label"]
        elif trade_active and entry_analysis["is_limit_pending"]:
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
        # Phase 1: Boost sizing multiplier for confirmed LIQUIDITY_RECLAIM setups (+25% institutional edge)
        strategy_sizing_boost = 1.25 if "LIQUIDITY_RECLAIM" in str(canonical_strategy).upper() else 1.0
        effective_sizing = round(float(np.clip(base_fund_sizing * shield_sizing * beta_sizing_mult * strategy_sizing_boost, 0.20, 1.30)), 2)
        if volume_24h_usd and 0 < volume_24h_usd < 10_000_000.0:
            low_cap_sizing_ceiling = max(0.20, min(1.0, volume_24h_usd / 10_000_000.0))
            effective_sizing = round(min(effective_sizing, low_cap_sizing_ceiling), 2)

        return {
            "symbol": symbol,
            "horizon": horizon_label,
            "horizon_key": tf_key,
            "horizon_tag": f"{horizon_label} {'SCALP' if horizon_label == '15M' else ('INTRADAY SWING' if horizon_label == '1H' else 'DAILY SWING')}",
            "direction": direction,
            "dominant_direction": direction,
            "raw_direction": direction,
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
            "is_higher_low_entry": bool(structural_anchor_info and structural_anchor_info.get("direction") == "LONG"),
            "is_lower_high_entry": bool(structural_anchor_info and structural_anchor_info.get("direction") == "SHORT"),
            "entry_anchor_type": "15M_HIGHER_LOW" if (structural_anchor_info and structural_anchor_info.get("direction") == "LONG") else ("15M_LOWER_HIGH" if structural_anchor_info else None),
            "entry_anchor_price": structural_anchor_info.get("hl_pivot_price" if direction == "LONG" else "lh_pivot_price") if structural_anchor_info else None,
            "structural_anchor_info": structural_anchor_info,
            "triad_structure": triad_structure.to_dict() if (triad_structure and hasattr(triad_structure, "to_dict")) else None,
            "chase_warning": entry_analysis["chase_warning"],
            "chase_threshold_pct": chase_thresh,
            "candle_trigger_confirmed": is_candle_confirmed,
            "candle_trigger_reason": candle_trigger_reason,
            "candle_trigger_metrics": candle_metrics,
            "microstructure_features": {
                "f_cvd_divergence": cvd_val,
                "f_order_book_imbalance": obi_val,
                "f_volatility_ratio": vol_ratio,
                "f_taker_buy_ratio": tb_ratio,
                "f_liquidity_proximity": liq_prox_pct,
                "f_funding_drag": funding_drag_bps,
                "f_relative_volume": rvol_val
            },
            "ev_net": ev_result.expected_net_return_pct,
            "ev_gross": ev_result.ev_gross_pct,
            "is_squeeze_transition": is_squeeze_trans,
            "is_breakout_spread_asymmetric": is_breakout_spread_asymmetric,
            "asymmetry_reason": asymmetry_reason if is_breakout_spread_asymmetric else None,
            "is_excessive_slippage": is_excessive_slippage,
            "slippage_reason": slippage_reason if is_excessive_slippage else None,
            "is_order_book_void": is_order_book_void,
            "order_book_void_reason": order_book_void_reason if is_order_book_void else None,
            "breakout_spread_cushion_bps": breakout_spread_cushion_bps,
            "effective_spread_bps": round(effective_spread_bps, 2),
            "spread_bps": round(effective_spread_bps, 2),
            "effective_rr": effective_rr,
            "actual_rr": actual_rr,
            "gross_rr": actual_rr,
            "is_radar_eligible": is_radar_eligible,
            "execution_assumption": exec_assumption.value,
            "costs_total_pct": ev_result.costs_total_pct,
            "cost_breakdown": {
                "fee_pct": cost_breakdown.fee_pct,
                "spread_pct": cost_breakdown.spread_pct,
                "slippage_pct": cost_breakdown.slippage_pct,
                "funding_pct": cost_breakdown.funding_pct,
                "total_cost_pct": cost_breakdown.total_cost_pct
            },
            "funding_info": funding_info,
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
            "meta_passed": bool(meta_eval.get("passed_meta_gate", True)),
            "meta_verdict": meta_eval.get("meta_verdict", "APPROVED"),
            "meta_model_type": meta_eval.get("model_type", "GLOBAL_ENSEMBLE"),
            "meta_sample_size": meta_eval.get("sample_size", 100),
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
            "order_block_setup": order_block_setup if is_ob_setup else None,
            "is_order_block_signal": is_ob_setup,
            "is_passive_poi": bool(order_block_setup and order_block_setup.get("is_passive_poi", True)) if is_ob_setup else False,
            "structural_trigger_confirmed": bool(order_block_setup and order_block_setup.get("structural_trigger_confirmed", False)) if is_ob_setup else False,
            "trigger_type": order_block_setup.get("trigger_type") if (is_ob_setup and order_block_setup) else None,
            "zeiierman_rank": order_block_setup.get("zeiierman_rank") if (is_ob_setup and order_block_setup) else None,
            "zeiierman_rank_label": order_block_setup.get("zeiierman_rank_label") if (is_ob_setup and order_block_setup) else None,
            "is_nested_smc": bool(order_block_setup.get("is_nested_smc", False)) if (is_ob_setup and order_block_setup) else False,
            "htf_poi_tf": order_block_setup.get("htf_poi_tf") if (is_ob_setup and order_block_setup) else None,
            "optimal_entry_limit": entry_analysis["optimal_entry_limit"],
            "mean_threshold_price": entry_analysis["optimal_entry_limit"],
            "order_block_zone": order_block_setup.get("order_block_zone") if (is_ob_setup and order_block_setup) else None,
            "invalidation_level": cand_sl if is_ob_setup else None,
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
            "is_decoupled_trend": is_decoupled_alt,
            "decoupled_reason": decoupled_reason if is_decoupled_alt else None,
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

        # Quantitative Institutional Horizon Weightings (Core active trading: 15M, 1H, 4H)
        # 15M (Trigger / Scalp), 1H (Intraday Momentum), 4H (Macro Anchor)
        HORIZON_WEIGHTS = {
            "15m": 0.35,  # Execution Trigger / Scalp
            "1h": 0.35,   # Intraday Context
            "4h": 0.30,   # Macro Anchor
            "5m": 0.08,   # Sub-horizon confirmation
            "12h": 0.12,  # Context
            "1d": 0.10,   # Context bonus
            "1w": 0.00,   # Retired macro horizon
            "15d": 0.00,  # Retired macro horizon
            "1M": 0.00    # Retired macro horizon
        }

        # Calculate dynamic weighted directional momentum
        total_weight = sum(HORIZON_WEIGHTS.get(tf, 1.0 / max(1, total_horizons)) for tf in trend_matrix) or 1.0
        w_bull = sum(HORIZON_WEIGHTS.get(tf, 1.0 / max(1, total_horizons)) for tf in bull_horizons) / total_weight
        w_bear = sum(HORIZON_WEIGHTS.get(tf, 1.0 / max(1, total_horizons)) for tf in bear_horizons) / total_weight
        w_chop = sum(HORIZON_WEIGHTS.get(tf, 1.0 / max(1, total_horizons)) for tf in chop_horizons) / total_weight

        # Directional Trend Qualification:
        # A directional trend requires bull/bear dominance over opposing direction and >= 33% weighted strength (or >= 2 raw horizons)
        min_aligned_count = max(2, int(total_horizons * 0.6)) if total_horizons >= 3 else 1
        if w_bull > w_bear and (w_bull >= 0.33 or len(bull_horizons) >= min_aligned_count):
            dominant_trend = "BULLISH"
            aligned_count = len(bull_horizons)
            dominant_direction = "LONG"
            alignment_score_pct = round(w_bull * 100.0, 1)
            alignment_ratio = f"{aligned_count}/{total_horizons}"
        elif w_bear > w_bull and (w_bear >= 0.33 or len(bear_horizons) >= min_aligned_count):
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
            and total_horizons >= 3
        )

        if is_unanimous:
            alignment_tier = f"💎 TIER 1: UNANIMOUS {total_horizons}/{total_horizons} MULTI-HORIZON TREND CONFLUENCE ({dominant_trend})"
        elif dominant_trend in ["BULLISH", "BEARISH"] and aligned_count >= min_aligned_count:
            alignment_tier = f"🔥 TIER 2: HIGH {alignment_ratio} MULTI-HORIZON CONFLUENCE ({dominant_trend})"
        elif dominant_trend in ["BULLISH", "BEARISH"]:
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
        triad_structure: Optional[Any] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """
        Evaluates discrete multi-horizon qualification gates for 15M Scalp, 1H Intraday, and 24H Swing.
        Enforces Elder's Triple Screen hierarchical confluence triads and prevents cold-start altcoins
        from being permanently locked out of intraday setups.
        Permits confirmed institutional triggers (Order Blocks and SMC setups) to execute even inside macro ranges.
        """
        if matrix_eval is None or not isinstance(matrix_eval, dict):
            matrix_eval = {}

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
        is_range_rotation_valid = bool(
            is_range_rotation and (
                (matrix_eval.get("dominant_direction") == "SHORT" and trend_matrix.get("15m") != "BULLISH" and trend_matrix.get("1h") != "BULLISH" and trend_matrix.get("4h") != "BULLISH") or
                (matrix_eval.get("dominant_direction") == "LONG" and trend_matrix.get("15m") != "BEARISH" and trend_matrix.get("1h") != "BEARISH" and trend_matrix.get("4h") != "BEARISH")
            )
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
        # 1. 15M Scalp Gate (Empirical accumulation required: 15M [3.75h])
        # Desk: 15M Scalp / Active Execution. Anchor: 4H. Context: 1H.
        # -----------------------------------------------------------------
        req_15m = [tf for tf in ["15m", "1h", "4h", "5m", "12h", "1d"] if tf in trend_matrix] or ["15m", "1h", "4h"]
        emp_req_15m = [tf for tf in ["5m", "15m"] if tf in horizon_predictions] or ["15m"]
        cold_start_tfs_15m = [
            tf for tf in emp_req_15m
            if tf not in horizon_predictions or
               horizon_predictions[tf].get("is_cold_start", False) or
               horizon_predictions[tf].get("candle_count", 0) < 15
        ]
        converged_tfs_15m = [
            tf for tf in req_15m
            if tf in horizon_predictions and
               not horizon_predictions[tf].get("is_cold_start", False) and
               horizon_predictions[tf].get("candle_count", 0) >= 15
        ]
        trends_15m = [trend_matrix.get(tf, "CONSOLIDATION") for tf in req_15m]
        bull_cnt_15m = sum(1 for t in trends_15m if t == "BULLISH")
        bear_cnt_15m = sum(1 for t in trends_15m if t == "BEARISH")

        # Elder's Triple Screen Decoupling: Anchor = 4H, Context = 1H, Trigger = 15M (or 5M)
        desk_tfs_15m = [tf for tf in ["5m", "15m", "1h"] if tf in trend_matrix] or ["15m", "1h"]
        desk_bull_cnt_15m = sum(1 for tf in desk_tfs_15m if trend_matrix.get(tf) == "BULLISH")
        desk_bear_cnt_15m = sum(1 for tf in desk_tfs_15m if trend_matrix.get(tf) == "BEARISH")

        is_15m_bull = (
            (len(converged_tfs_15m) >= 2 and all(trend_matrix.get(tf) == "BULLISH" for tf in converged_tfs_15m))
            or (
                trend_matrix.get("15m") == "BULLISH"
                and trend_matrix.get("1h") != "BEARISH"
                and desk_bear_cnt_15m <= 1
                and (desk_bull_cnt_15m >= 2 or bull_cnt_15m >= 2)
                and bear_cnt_15m <= 1
            )
            or (
                # Trend Pullback Re-entry: 4H and 1H Bullish, 15M in consolidation/pullback
                trend_matrix.get("4h") == "BULLISH"
                and trend_matrix.get("1h") == "BULLISH"
                and trend_matrix.get("15m") != "BEARISH"
                and bear_cnt_15m <= 1
            )
        )
        is_15m_bear = (
            (len(converged_tfs_15m) >= 2 and all(trend_matrix.get(tf) == "BEARISH" for tf in converged_tfs_15m))
            or (
                trend_matrix.get("15m") == "BEARISH"
                and trend_matrix.get("1h") != "BULLISH"
                and desk_bull_cnt_15m <= 1
                and (desk_bear_cnt_15m >= 2 or bear_cnt_15m >= 2)
                and bull_cnt_15m <= 1
            )
            or (
                # Trend Pullback Re-entry: 4H and 1H Bearish, 15M in consolidation/pullback
                trend_matrix.get("4h") == "BEARISH"
                and trend_matrix.get("1h") == "BEARISH"
                and trend_matrix.get("15m") != "BULLISH"
                and bull_cnt_15m <= 1
            )
        )

        is_passive_15m = bool(
            ob_setup_15m and ob_setup_15m.get("is_passive_poi", False) and
            not ob_setup_15m.get("structural_trigger_confirmed", False) and
            not ob_setup_15m.get("is_turtle_soup", False) and
            not (has_smc_15m and smc_dir_15m == ob_setup_15m.get("direction"))
        )
        has_ob_trigger_15m = bool(
            has_ob_15m and ob_setup_15m.get("zeiierman_rank", 99) <= 3 and not is_passive_15m
        )
        has_valid_institutional_trigger_15m = bool(
            has_ob_trigger_15m or has_smc_15m or is_coiling_breakout
        )

        q_15m_qualified = bool(
            not cold_start_tfs_15m and (
                ((not is_middle_chop_veto or (desk_bull_cnt_15m >= 2 or desk_bear_cnt_15m >= 2)) and matrix_trade_permitted and (
                    is_15m_bull or is_15m_bear or is_coiling_breakout or (is_range_rotation_valid and matrix_eval.get("dominant_direction") in ["LONG", "SHORT"]) or is_breakout_expansion
                )) or has_valid_institutional_trigger_15m
            )
        )
        cand_15m_dir = (
            ob_setup_15m.get("direction") if (has_ob_trigger_15m and ob_setup_15m.get("direction") in ["LONG", "SHORT"]) else (
                smc_dir_15m if (has_smc_15m and smc_dir_15m in ["LONG", "SHORT"]) else (
                    "LONG" if is_15m_bull else (
                        "SHORT" if is_15m_bear else (
                            (ob_setup_15m.get("direction") if (has_ob_15m and ob_setup_15m.get("direction") == matrix_eval.get("dominant_direction") and ob_setup_15m.get("direction") in ["LONG", "SHORT"]) else (
                                matrix_eval.get("dominant_direction") if ((is_coiling_breakout or is_range_rotation_valid or is_breakout_expansion) and matrix_eval.get("dominant_direction") in ["LONG", "SHORT"]) else None
                            ))
                        )
                    )
                )
            )
        )
        if cand_15m_dir not in ["LONG", "SHORT"]:
            q_15m_qualified = False
            q_15m_direction = None

        # Pillar 2: Strict Higher-Timeframe Trend Confluence (Anchor = 4H, Context = 1H, Trigger = 15M)
        # 1. Macro Anchor (4H): Cannot oppose trade direction
        # 2. Context Horizon (1H): Cannot oppose trade direction
        # 3. Trigger Horizon (15M): Cannot oppose trade direction unless confirmed by active OB/SMC trigger
        # 4. Range Rotation: Cannot trade counter-trend against 15M, 1H, or 4H
        t_15m_str = str(trend_matrix.get("15m", "CONSOLIDATION")).upper()
        t_1h_str = str(trend_matrix.get("1h", "CONSOLIDATION")).upper()
        htf_4h_str = str(trend_matrix.get("4h", "CONSOLIDATION")).upper()
        htf_1d_str = str(trend_matrix.get("1d", "CONSOLIDATION")).upper()

        is_htf_conflict_15m = False
        if cand_15m_dir == "SHORT":
            if htf_4h_str == "BULLISH":
                is_htf_conflict_15m = True
            elif t_1h_str == "BULLISH":
                is_htf_conflict_15m = True
            elif is_range_rotation and (t_15m_str == "BULLISH" or t_1h_str == "BULLISH" or htf_4h_str == "BULLISH"):
                is_htf_conflict_15m = True
            elif not (has_valid_institutional_trigger_15m or (triad_structure and getattr(triad_structure, "scenario", "") == "SCENARIO_C_TREND_PULLBACK_ENTRY")) and t_15m_str == "BULLISH":
                is_htf_conflict_15m = True
        elif cand_15m_dir == "LONG":
            if htf_4h_str == "BEARISH":
                is_htf_conflict_15m = True
            elif t_1h_str == "BEARISH":
                is_htf_conflict_15m = True
            elif is_range_rotation and (t_15m_str == "BEARISH" or t_1h_str == "BEARISH" or htf_4h_str == "BEARISH"):
                is_htf_conflict_15m = True
            elif not (has_valid_institutional_trigger_15m or (triad_structure and getattr(triad_structure, "scenario", "") == "SCENARIO_C_TREND_PULLBACK_ENTRY")) and t_15m_str == "BEARISH":
                is_htf_conflict_15m = True

        # Macro Pullback Exhaustion Trap (Phase 4):
        # If 15M was attempting to buy counter-trend into HTF Bearish Resistance, but touches a verified Bearish OB or SMC Supply,
        # ONLY invert direction if the OB has an active, confirmed structural trigger (NOT a passive POI)!
        if is_htf_conflict_15m and cand_15m_dir == "LONG" and htf_4h_str == "BEARISH":
            has_bearish_exhaustion = bool(
                (has_ob_15m and ob_setup_15m.get("direction") == "SHORT" and ob_setup_15m.get("structural_trigger_confirmed", False) and not ob_setup_15m.get("is_passive_poi", False)) or
                (has_smc_15m and smc_dir_15m == "SHORT")
            )
            if has_bearish_exhaustion:
                cand_15m_dir = "SHORT"
                is_htf_conflict_15m = False
                q_15m_qualified = True
            else:
                q_15m_qualified = False
        elif is_htf_conflict_15m and cand_15m_dir == "SHORT" and htf_4h_str == "BULLISH":
            has_bullish_exhaustion = bool(
                (has_ob_15m and ob_setup_15m.get("direction") == "LONG" and ob_setup_15m.get("structural_trigger_confirmed", False) and not ob_setup_15m.get("is_passive_poi", False)) or
                (has_smc_15m and smc_dir_15m == "LONG")
            )
            if has_bullish_exhaustion:
                cand_15m_dir = "LONG"
                is_htf_conflict_15m = False
                q_15m_qualified = True
            else:
                q_15m_qualified = False

        if triad_structure is not None:
            if getattr(triad_structure, "opposing_ob_veto", False):
                q_15m_qualified = False
                q_15m_direction = None
                is_htf_conflict_15m = True
            elif getattr(triad_structure, "has_htf_choch", False):
                q_15m_qualified = False
                q_15m_direction = None
                is_htf_conflict_15m = True
            elif getattr(triad_structure, "is_unanimously_aligned", False):
                if getattr(triad_structure, "trend_direction", None) in ["LONG", "SHORT"]:
                    triad_dir = triad_structure.trend_direction
                    if (triad_dir == "LONG" and htf_4h_str != "BEARISH" and t_1h_str != "BEARISH") or (triad_dir == "SHORT" and htf_4h_str != "BULLISH" and t_1h_str != "BULLISH"):
                        cand_15m_dir = triad_dir
                        if not cold_start_tfs_15m:
                            if not is_middle_chop_veto or getattr(triad_structure, "has_order_block", False) or getattr(triad_structure, "scenario", "") == "SCENARIO_C_TREND_PULLBACK_ENTRY":
                                q_15m_qualified = True
                        if q_15m_qualified:
                            q_15m_direction = triad_dir
                    else:
                        q_15m_qualified = False
                        q_15m_direction = None
                        is_htf_conflict_15m = True
            else:
                q_15m_qualified = False
                q_15m_direction = None
                is_htf_conflict_15m = True

        if is_htf_conflict_15m:
            q_15m_qualified = False
            q_15m_direction = None
        else:
            q_15m_direction = cand_15m_dir if q_15m_qualified else None

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
            "has_order_block_trigger": has_ob_trigger_15m,
            "is_passive_poi": bool(has_ob_15m and not has_ob_trigger_15m),
            "has_smc_setup": has_smc_15m,
            "order_block_rank": ob_setup_15m.get("zeiierman_rank") if has_ob_15m else None,
            "conflicts": (
                [f"COLD_START_HORIZON_ACCUMULATION: 15M Scalp requires >= 15 historical candles (3.75h). Under-accumulated horizons: {cold_start_tfs_15m}."]
                if cold_start_tfs_15m else (
                    [f"HTF_COUNTER_TREND_CONFLICT: MTF_TREND_MISALIGNMENT: {cand_15m_dir} blocked by adverse higher timeframe (4H: {htf_4h_str}, 1H: {t_1h_str}, 15M: {t_15m_str})."]
                    if is_htf_conflict_15m else (
                        [f"CAPITAL_PRESERVATION: Trapped in middle 50% chop zone of 1D range box. Section 35 gate locked."]
                        if (is_middle_chop_veto and not has_valid_institutional_trigger_15m) else (
                            [f"{tf} is {trend_matrix.get(tf, 'MISSING')}" for tf in req_15m if trend_matrix.get(tf) != ("BULLISH" if is_15m_bull else ("BEARISH" if is_15m_bear else trends_15m[0]))]
                            if not q_15m_qualified else []
                        )
                    )
                )
            )
        }

        # -----------------------------------------------------------------
        # 2. 1H Intraday Gate (Empirical accumulation required: 1H [15h], 15M [3.75h])
        # Desk: 1H Intraday. Anchor: 4H. Trigger: 15M.
        # -----------------------------------------------------------------
        req_1h = [tf for tf in ["15m", "1h", "4h", "5m", "12h", "1d"] if tf in trend_matrix] or ["15m", "1h", "4h"]
        emp_req_1h = [tf for tf in (["5m", "15m", "1h"] if "5m" in horizon_predictions else ["15m", "1h"]) if tf in horizon_predictions] or ["1h"]
        cold_start_tfs_1h = [
            tf for tf in emp_req_1h
            if tf not in horizon_predictions or
               horizon_predictions[tf].get("is_cold_start", False) or
               horizon_predictions[tf].get("candle_count", 0) < 15
        ]
        converged_tfs_1h = [
            tf for tf in req_1h
            if tf in horizon_predictions and
               not horizon_predictions[tf].get("is_cold_start", False) and
               horizon_predictions[tf].get("candle_count", 0) >= 15
        ]
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
                and desk_bear_cnt_1h <= 1
                and (desk_bull_cnt_1h >= 2 or bull_cnt_1h >= 3)
                and bear_cnt_1h <= 1
            )
        )
        is_1h_bear = (
            (len(converged_tfs_1h) >= 3 and all(trend_matrix.get(tf) == "BEARISH" for tf in converged_tfs_1h))
            or (
                trend_matrix.get("1h") == "BEARISH"
                and trend_matrix.get("4h") != "BULLISH"
                and desk_bull_cnt_1h <= 1
                and (desk_bear_cnt_1h >= 2 or bear_cnt_1h >= 3)
                and bull_cnt_1h <= 1
            )
        )

        is_passive_1h = bool(
            ob_setup_1h and ob_setup_1h.get("is_passive_poi", False) and
            not ob_setup_1h.get("structural_trigger_confirmed", False) and
            not ob_setup_1h.get("is_turtle_soup", False) and
            not (has_smc_1h and smc_dir_1h == ob_setup_1h.get("direction"))
        )
        has_ob_trigger_1h = bool(
            has_ob_1h and ob_setup_1h.get("zeiierman_rank", 99) <= 3 and not is_passive_1h
        )
        has_valid_institutional_trigger_1h = bool(
            has_ob_trigger_1h or has_smc_1h or is_coiling_breakout
        )

        q_1h_qualified = bool(
            not cold_start_tfs_1h and (
                ((not is_middle_chop_veto or (desk_bull_cnt_1h >= 2 or desk_bear_cnt_1h >= 2)) and matrix_trade_permitted and (
                    is_1h_bull or is_1h_bear or is_coiling_breakout or is_breakout_expansion or (is_range_rotation and matrix_eval.get("dominant_direction") in ["LONG", "SHORT"])
                )) or has_valid_institutional_trigger_1h
            )
        )
        cand_1h_dir = (
            ob_setup_1h.get("direction") if (has_ob_trigger_1h and ob_setup_1h.get("direction") in ["LONG", "SHORT"]) else (
                smc_dir_1h if (has_smc_1h and smc_dir_1h in ["LONG", "SHORT"]) else (
                    "LONG" if is_1h_bull else (
                        "SHORT" if is_1h_bear else (
                            (ob_setup_1h.get("direction") if (has_ob_1h and ob_setup_1h.get("direction") == matrix_eval.get("dominant_direction") and ob_setup_1h.get("direction") in ["LONG", "SHORT"]) else (
                                matrix_eval.get("dominant_direction") if ((is_coiling_breakout or is_range_rotation or is_breakout_expansion) and matrix_eval.get("dominant_direction") in ["LONG", "SHORT"]) else None
                            ))
                        )
                    )
                )
            )
        )
        if cand_1h_dir not in ["LONG", "SHORT"]:
            q_1h_qualified = False
            q_1h_direction = None

        # Pillar 2: Strict Higher-Timeframe Trend Confluence (Anchor = 4H, Context = 1D)
        is_htf_conflict_1h = bool(
            cand_1h_dir and (
                (cand_1h_dir == "SHORT" and (htf_4h_str == "BULLISH" or htf_1d_str == "BULLISH")) or
                (cand_1h_dir == "LONG" and (htf_4h_str == "BEARISH" or htf_1d_str == "BEARISH"))
            )
        )
        # Macro Pullback Exhaustion Trap (Phase 4):
        if is_htf_conflict_1h and cand_1h_dir == "LONG" and (htf_4h_str == "BEARISH" or htf_1d_str == "BEARISH"):
            has_bearish_exhaustion_1h = bool(
                (has_ob_1h and ob_setup_1h.get("direction") == "SHORT") or
                (has_smc_1h and smc_dir_1h == "SHORT")
            )
            if has_bearish_exhaustion_1h:
                cand_1h_dir = "SHORT"
                is_htf_conflict_1h = False
                q_1h_qualified = True
        elif is_htf_conflict_1h and cand_1h_dir == "SHORT" and (htf_4h_str == "BULLISH" or htf_1d_str == "BULLISH"):
            has_bullish_exhaustion_1h = bool(
                (has_ob_1h and ob_setup_1h.get("direction") == "LONG") or
                (has_smc_1h and smc_dir_1h == "LONG")
            )
            if has_bullish_exhaustion_1h:
                cand_1h_dir = "LONG"
                is_htf_conflict_1h = False
                q_1h_qualified = True

        if is_htf_conflict_1h:
            q_1h_qualified = False
            q_1h_direction = None
        else:
            q_1h_direction = cand_1h_dir if q_1h_qualified else None

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
            "has_order_block_trigger": has_ob_trigger_1h,
            "is_passive_poi": bool(has_ob_1h and not has_ob_trigger_1h),
            "has_smc_setup": has_smc_1h,
            "order_block_rank": ob_setup_1h.get("zeiierman_rank") if has_ob_1h else None,
            "conflicts": (
                [f"COLD_START_HORIZON_ACCUMULATION: 1H Intraday requires >= 15 historical candles (15h). Under-accumulated horizons: {cold_start_tfs_1h}."]
                if cold_start_tfs_1h else (
                    [f"HTF_COUNTER_TREND_CONFLICT: {cand_1h_dir} blocked by adverse higher timeframe (4H: {htf_4h_str})."]
                    if is_htf_conflict_1h else (
                        [f"CAPITAL_PRESERVATION: Trapped in middle 50% chop zone of 1D range box. Section 35 gate locked."]
                        if (is_middle_chop_veto and not has_valid_institutional_trigger_1h) else (
                            [f"{tf} is {trend_matrix.get(tf, 'MISSING')}" for tf in req_1h if trend_matrix.get(tf) != ("BULLISH" if is_1h_bull else ("BEARISH" if is_1h_bear else trends_1h[0]))]
                            if not q_1h_qualified else []
                        )
                    )
                )
            )
        }

        # -----------------------------------------------------------------
        # 3. 24H Swing Gate (Empirical accumulation required: 1D [15 days], 12H, 4H, 1H, 15M)
        # Desk: 24H Swing. Anchor: 1D/4H. Trigger: 15M.
        # -----------------------------------------------------------------
        req_24h = [tf for tf in ["15m", "1h", "4h", "12h", "1d"] if tf in trend_matrix] or ["15m", "1h", "4h"]
        emp_req_24h = [tf for tf in ["15m", "1h", "4h", "12h", "1d"] if tf in horizon_predictions] or ["1d"]
        cold_start_tfs_24h = [
            tf for tf in emp_req_24h
            if tf not in horizon_predictions or
               horizon_predictions[tf].get("is_cold_start", False) or
               horizon_predictions[tf].get("candle_count", 0) < 15
        ]
        converged_tfs_24h = [
            tf for tf in req_24h
            if tf in horizon_predictions and
               not horizon_predictions[tf].get("is_cold_start", False) and
               horizon_predictions[tf].get("candle_count", 0) >= 15
        ]
        trends_24h = [trend_matrix.get(tf, "CONSOLIDATION") for tf in req_24h]
        bull_cnt_24h = sum(1 for t in trends_24h if t == "BULLISH")
        bear_cnt_24h = sum(1 for t in trends_24h if t == "BEARISH")

        is_24h_bull = (
            (len(converged_tfs_24h) >= 5 and all(trend_matrix.get(tf) == "BULLISH" for tf in converged_tfs_24h))
            or ((trend_matrix.get("1d") == "BULLISH" or trend_matrix.get("12h") == "BULLISH") and bull_cnt_24h >= 4 and bear_cnt_24h <= 1)
        )
        is_24h_bear = (
            (len(converged_tfs_24h) >= 5 and all(trend_matrix.get(tf) == "BEARISH" for tf in converged_tfs_24h))
            or ((trend_matrix.get("1d") == "BEARISH" or trend_matrix.get("12h") == "BEARISH") and bear_cnt_24h >= 4 and bull_cnt_24h <= 1)
        )

        is_passive_24h = bool(
            ob_setup_24h and ob_setup_24h.get("is_passive_poi", False) and
            not ob_setup_24h.get("structural_trigger_confirmed", False) and
            not ob_setup_24h.get("is_turtle_soup", False) and
            not (has_smc_24h and smc_dir_24h == ob_setup_24h.get("direction"))
        )
        has_ob_trigger_24h = bool(
            has_ob_24h and ob_setup_24h.get("zeiierman_rank", 99) <= 3 and not is_passive_24h
        )
        has_valid_institutional_trigger_24h = bool(
            has_ob_trigger_24h or has_smc_24h
        )

        q_24h_qualified = bool(
            not cold_start_tfs_24h and (
                (not is_middle_chop_veto and matrix_trade_permitted and (
                    is_24h_bull or is_24h_bear or is_breakout_expansion
                )) or has_valid_institutional_trigger_24h
            )
        )
        cand_24h_dir = (
            ob_setup_24h.get("direction") if (has_ob_trigger_24h and ob_setup_24h.get("direction") in ["LONG", "SHORT"]) else (
                smc_dir_24h if (has_smc_24h and smc_dir_24h in ["LONG", "SHORT"]) else (
                    "LONG" if is_24h_bull else (
                        "SHORT" if is_24h_bear else (
                            (ob_setup_24h.get("direction") if (has_ob_24h and ob_setup_24h.get("direction") == matrix_eval.get("dominant_direction") and ob_setup_24h.get("direction") in ["LONG", "SHORT"]) else (
                                matrix_eval.get("dominant_direction") if (is_breakout_expansion and matrix_eval.get("dominant_direction") in ["LONG", "SHORT"]) else None
                            ))
                        )
                    )
                )
            )
        )
        if cand_24h_dir not in ["LONG", "SHORT"]:
            q_24h_qualified = False
            q_24h_direction = None

        # Pillar 2: Strict Higher-Timeframe Trend Confluence for 24H Swing (1D anchor; optional 1W guard if populated)
        htf_1d_str = str(trend_matrix.get("1d", "CONSOLIDATION")).upper()
        htf_1w_str = str(trend_matrix.get("1w", "CONSOLIDATION")).upper()
        is_htf_conflict_24h = bool(
            cand_24h_dir and (
                (cand_24h_dir == "SHORT" and (htf_1d_str == "BULLISH" or htf_1w_str == "BULLISH")) or
                (cand_24h_dir == "LONG" and (htf_1d_str == "BEARISH" or htf_1w_str == "BEARISH"))
            )
        )
        if is_htf_conflict_24h:
            q_24h_qualified = False
            q_24h_direction = None
        else:
            q_24h_direction = cand_24h_dir if q_24h_qualified else None

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
            "has_order_block_trigger": has_ob_trigger_24h,
            "is_passive_poi": bool(has_ob_24h and not has_ob_trigger_24h),
            "order_block_rank": ob_setup_24h.get("zeiierman_rank") if has_ob_24h else None,
            "conflicts": (
                [f"COLD_START_HORIZON_ACCUMULATION: 24H Daily Swing requires >= 15 historical candles (15 days). Under-accumulated horizons: {cold_start_tfs_24h}."]
                if cold_start_tfs_24h else (
                    [f"HTF_COUNTER_TREND_CONFLICT: {cand_24h_dir} blocked by adverse higher timeframe (1W: {htf_1w_str})."]
                    if is_htf_conflict_24h else (
                        [f"CAPITAL_PRESERVATION: Trapped in middle 50% chop zone of 1D range box. Section 35 gate locked."]
                        if (is_middle_chop_veto and not has_valid_institutional_trigger_24h) else (
                            [f"{tf} is {trend_matrix.get(tf, 'MISSING')}" for tf in req_24h if trend_matrix.get(tf) != ("BULLISH" if is_24h_bull else ("BEARISH" if is_24h_bear else trends_24h[0]))]
                            if not q_24h_qualified else []
                        )
                    )
                )
            )
        }

        return q_15m, q_1h, q_24h

    def evaluate_asset_multi_horizon(
        self,
        symbol: str,
        dfs_9: Optional[Dict[str, pd.DataFrame]] = None,
        btc_shield_state: Optional[Dict[str, Any]] = None,
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
        # Institutional Policy: Zero Meme Coins in prediction system
        if is_meme_coin(symbol):
            return None

        if dfs_9 is None:
            loader = self.data_loader
            if loader is None:
                from app.engine.scanner.data_loader import MultiHorizonDataLoader
                loader = MultiHorizonDataLoader()
            try:
                dfs_9 = loader.fetch_all_9_timeframes(symbol)
            except Exception as e:
                logger.error(f"[SIGNAL GENERATOR] Failed to fetch 9 timeframes for {symbol}: {e}")
                return None

        if btc_shield_state is None:
            try:
                from app.engine.scanner.btc_shield import BtcPredictiveMarketShield
                shield = BtcPredictiveMarketShield()
                if symbol == "BTC/USDT" and dfs_9:
                    btc_shield_state = shield.evaluate_regime(dfs_9, live_btc_price=live_price)
                else:
                    btc_shield_state = shield.state.copy()
            except Exception as e:
                logger.warning(f"[SIGNAL GENERATOR] Failed to assess btc shield state: {e}")
                btc_shield_state = {
                    "regime": "NEUTRAL",
                    "action": "NORMAL",
                    "altcoin_longs_allowed": True,
                    "altcoin_shorts_allowed": True,
                    "market_stress_level": "LOW",
                    "drawdown_pct": 0.0
                }

        if not dfs_9 or "15m" not in dfs_9 or dfs_9["15m"] is None:
            return None

        # Fallback 4H resolution from 1H or 1D if not directly provided in test fixtures
        if "4h" not in dfs_9 or dfs_9["4h"] is None:
            if "1h" in dfs_9 and dfs_9["1h"] is not None:
                dfs_9["4h"] = dfs_9["1h"]
            elif "1d" in dfs_9 and dfs_9["1d"] is not None:
                dfs_9["4h"] = dfs_9["1d"]

        current_price = live_price if (live_price is not None and live_price > 0) else float(dfs_9["15m"]["close"].iloc[-1])
        if current_price <= 0.0001:
            return None

        # Dynamic 24h Turnover Synthesis: If ticker volume is missing or zero, compute rolling 24h turnover from candles
        if (volume_24h_usd is None or volume_24h_usd <= 0.0) and "1h" in dfs_9:
            df_1h = dfs_9["1h"]
            if df_1h is not None and len(df_1h) >= 5 and "volume" in df_1h.columns and "close" in df_1h.columns:
                volume_24h_usd = float((df_1h["close"].iloc[-24:].astype(float) * df_1h["volume"].iloc[-24:].astype(float)).sum())

        # Hard Liquidity Floor Gate: Exclude coins with extreme sub-threshold volume (< $1M) from active emission
        if volume_24h_usd is not None and 0 < volume_24h_usd < 1_000_000.0:
            return None

        # Fetch asset fundamental intelligence & news matrix
        fund_matrix = None
        try:
            from app.services.fundamental_service import fundamental_service
            fund_matrix = fundamental_service.get_asset_fundamental_matrix(symbol)
        except Exception as e:
            logger.debug(f"[SIGNAL GENERATOR] Fundamental matrix retrieval exception for {symbol}: {e}")
            fund_matrix = None

        # Scan Institutional Order Blocks across all 9 Horizons concurrently
        ob_scan = order_block_engine.scan_all_horizons(dfs_9, current_price=current_price, btc_shield=btc_shield_state)

        # Gate 0: Universal Candlestick Market Structure & Order Block Multi-Timeframe Alignment (Pre-AI Gatekeeper)
        # Evaluates pure 4H > 1H > 15M trend alignment and Order Blocks strictly BEFORE any AI/ML model inference
        from app.quant_v16.market_structure import MarketStructureEngine, PreAIMarketStructureDecision, TradeDirection
        triad_structure = MarketStructureEngine.evaluate_pre_ai_structure(
            df_4h=dfs_9.get("4h"),
            df_1h=dfs_9.get("1h"),
            df_15m=dfs_9.get("15m"),
            current_price=current_price
        )

        alt_longs_allowed = btc_shield_state.get("altcoin_longs_allowed", True)
        horizon_predictions: Dict[str, Any] = {}
        now_ts = time.time()

        # Evaluate each of the 9 required timeframes
        for tf in TIMEFRAMES_9:
            df_tf = dfs_9.get(tf)
            n_raw = len(df_tf) if df_tf is not None else 0

            # Architecture & User Mandate: Completely remove week and month charts analysis and models
            if tf in RETIRED_MACRO_TIMEFRAMES or tf in ["1w", "15d", "1M"]:
                is_sparse_cold = bool(n_raw < 15)
                horizon_predictions[tf] = {
                    "timeframe": tf,
                    "candle_count": n_raw,
                    "is_synthetic": False,
                    "is_hybrid": False,
                    "is_cold_start": is_sparse_cold,
                    "is_retired": True,
                    "accumulation_phase": "COLD_START_INSUFFICIENT_HISTORY" if is_sparse_cold else "RETIRED_MACRO_HORIZON",
                    "accumulation_progress_pct": min(100.0, round((n_raw / 15.0) * 100.0, 1)),
                    "historical_hours_accumulated": 0.0,
                    "required_hours_for_convergence": 0.0,
                    "synth_label": "Retired: True",
                    "current_price": current_price,
                    "direction": "NEUTRAL",
                    "trend_state": "CONSOLIDATION",
                    "trend_label": f"⚪ RETIRED MACRO HORIZON ({tf.upper()})" if not is_sparse_cold else f"🟡 ACCUMULATING (COLD START: N={n_raw})",
                    "candle_color": "⚪ RETIRED",
                    "classifier_votes": "RETIRED",
                    "bullish_votes": 0,
                    "bearish_votes": 0,
                    "consensus_probability": 0.50,
                    "prob_bullish": 0.50,
                    "prob_bearish": 0.50,
                    "predicted_target_price": current_price,
                    "predicted_change_pct": 0.0,
                    "regressor_votes": {},
                    "winning_vote_count": 0,
                    "classifier_breakdown": {},
                    "regressor_breakdown": {},
                    "is_inside_bar": False,
                    "is_nr7": False,
                    "is_nr4": False,
                    "is_doji": False,
                    "is_coiling_squeeze": False,
                    "compression_score": 0.0,
                    "range_high": current_price * 1.01,
                    "range_low": current_price * 0.99,
                    "position_in_range_pct": 50.0,
                    "headroom_to_high_pct": 1.0,
                    "headroom_to_low_pct": 1.0,
                    "order_block_touch": False,
                    "order_block_rank": None,
                    "order_block_rank_label": None,
                    "order_block_type": "NONE",
                    "order_block_zone": None,
                    "total_order_blocks": 0
                }
                continue

            last_candle_ts = int(df_tf["timestamp"].iloc[-1]) if (df_tf is not None and n_raw > 0 and "timestamp" in df_tf.columns) else 0

            # Novel exotic pair / Cold-start branch: insufficient candles (< 5) to compute technical indicators
            if df_tf is None or n_raw < 5:
                y_dir = None
                y_ret = None
                if df_tf is not None and n_raw > 1 and "close" in df_tf.columns and "open" in df_tf.columns:
                    c_tmp = df_tf["close"].values
                    o_tmp = df_tf["open"].values
                    # Train direction classifier strictly on candle close progression: c[i+1] > c[i]
                    y_dir = (c_tmp[1:] > c_tmp[:-1]).astype(int)
                    eq_m = (c_tmp[1:] == c_tmp[:-1])
                    if np.any(eq_m):
                        y_dir[eq_m] = (c_tmp[1:][eq_m] >= o_tmp[1:][eq_m]).astype(int)
                    y_ret = (c_tmp[1:] - c_tmp[:-1]) / (c_tmp[:-1] + 1e-10)

                clf_ensemble, reg_ensemble, _ = self.model_registry.get_or_train_coin_models(
                    symbol=symbol,
                    tf=tf,
                    X_train=None,
                    y_train_dir=y_dir,
                    y_train_ret=y_ret,
                    last_candle_ts=last_candle_ts,
                    ttl_seconds=300.0
                )
                clf_result = clf_ensemble.predict_live(None)
                clf_dir = clf_result.get("direction", "LONG")
                reg_result = reg_ensemble.predict_price_live(
                    None, current_price=current_price, raw_atr=current_price * 0.01, expected_direction=clf_dir
                )

                tf_trend = "CONSOLIDATION"
                tf_trend_label = f"🟡 ACCUMULATING (COLD START: N={n_raw})"
                tf_ob_info = ob_scan.get("horizon_blocks", {}).get(tf, {})
                tf_seconds = TIMEFRAME_META.get(tf, {}).get("seconds", 900)
                hist_hours = round(n_raw * tf_seconds / 3600.0, 2)
                req_hours = round(15 * tf_seconds / 3600.0, 2)

                horizon_predictions[tf] = {
                    "timeframe": tf,
                    "candle_count": n_raw,
                    "is_synthetic": False,
                    "is_hybrid": False,
                    "is_cold_start": True,
                    "accumulation_phase": "COLD_START_INSUFFICIENT_HISTORY",
                    "accumulation_progress_pct": min(100.0, round((n_raw / 15.0) * 100.0, 1)),
                    "historical_hours_accumulated": hist_hours,
                    "required_hours_for_convergence": req_hours,
                    "synth_label": "Synth: False",
                    "current_price": current_price,
                    "direction": clf_result["direction"],
                    "trend_state": tf_trend,
                    "trend_label": tf_trend_label,
                    "candle_color": clf_result.get("decision_label", "🟢 GREEN BULLISH" if clf_result.get("direction") == "LONG" else "🔴 RED BEARISH"),
                    "classifier_votes": clf_result.get("consensus_tally", "3/5 MAJORITY (COLD START)"),
                    "bullish_votes": clf_result.get("bullish_votes", 3),
                    "bearish_votes": clf_result.get("bearish_votes", 2),
                    "consensus_probability": clf_result.get("consensus_probability", 0.50),
                    "prob_bullish": clf_result.get("prob_bullish", 0.50),
                    "prob_bearish": clf_result.get("prob_bearish", 0.50),
                    "predicted_target_price": reg_result["predicted_target_price"],
                    "predicted_change_pct": reg_result["predicted_change_pct"],
                    "regressor_votes": reg_result["regression_votes"],
                    "winning_vote_count": reg_result["winning_vote_count"],
                    "classifier_breakdown": clf_result.get("model_breakdown", {}),
                    "regressor_breakdown": reg_result.get("model_predictions", {}),
                    "is_inside_bar": False,
                    "is_nr7": False,
                    "is_nr4": False,
                    "is_doji": False,
                    "is_coiling_squeeze": False,
                    "compression_score": 0.0,
                    "range_high": current_price * 1.01,
                    "range_low": current_price * 0.99,
                    "position_in_range_pct": 50.0,
                    "headroom_to_high_pct": 1.0,
                    "headroom_to_low_pct": 1.0,
                    "order_block_touch": tf_ob_info.get("has_touch", False),
                    "order_block_rank": tf_ob_info.get("touch_rank"),
                    "order_block_rank_label": tf_ob_info.get("touch_label"),
                    "order_block_type": tf_ob_info.get("touch_type", "NONE"),
                    "order_block_zone": tf_ob_info.get("nearest_zone"),
                    "total_order_blocks": tf_ob_info.get("total_blocks", 0)
                }
                continue

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
                y_dir = None
                y_ret = None
                if df_tf is not None and n_raw > 1 and "close" in df_tf.columns and "open" in df_tf.columns:
                    c_tmp = df_tf["close"].values
                    o_tmp = df_tf["open"].values
                    # Train direction classifier strictly on candle close progression: c[i+1] > c[i]
                    y_dir = (c_tmp[1:] > c_tmp[:-1]).astype(int)
                    eq_m = (c_tmp[1:] == c_tmp[:-1])
                    if np.any(eq_m):
                        y_dir[eq_m] = (c_tmp[1:][eq_m] >= o_tmp[1:][eq_m]).astype(int)
                    y_ret = (c_tmp[1:] - c_tmp[:-1]) / (c_tmp[:-1] + 1e-10)

                clf_ensemble, reg_ensemble, _ = self.model_registry.get_or_train_coin_models(
                    symbol=symbol,
                    tf=tf,
                    X_train=None,
                    y_train_dir=y_dir,
                    y_train_ret=y_ret,
                    last_candle_ts=last_candle_ts,
                    ttl_seconds=300.0
                )
                clf_result = clf_ensemble.predict_live(None)
                clf_dir = clf_result.get("direction", "LONG")
                reg_result = reg_ensemble.predict_price_live(
                    None, current_price=current_price, raw_atr=current_price * 0.01, expected_direction=clf_dir
                )

                tf_trend = "CONSOLIDATION"
                tf_trend_label = f"🟡 ACCUMULATING (COLD START: N={n_raw})"
                tf_ob_info = ob_scan.get("horizon_blocks", {}).get(tf, {})
                tf_seconds = TIMEFRAME_META.get(tf, {}).get("seconds", 900)
                hist_hours = round(n_raw * tf_seconds / 3600.0, 2)
                req_hours = round(15 * tf_seconds / 3600.0, 2)

                horizon_predictions[tf] = {
                    "timeframe": tf,
                    "candle_count": n_raw,
                    "is_synthetic": False,
                    "is_hybrid": False,
                    "is_cold_start": True,
                    "accumulation_phase": "COLD_START_INSUFFICIENT_HISTORY",
                    "accumulation_progress_pct": min(100.0, round((n_raw / 15.0) * 100.0, 1)),
                    "historical_hours_accumulated": hist_hours,
                    "required_hours_for_convergence": req_hours,
                    "synth_label": "Synth: False",
                    "current_price": current_price,
                    "direction": clf_result["direction"],
                    "trend_state": tf_trend,
                    "trend_label": tf_trend_label,
                    "candle_color": clf_result.get("decision_label", "🟢 GREEN BULLISH" if clf_result.get("direction") == "LONG" else "🔴 RED BEARISH"),
                    "classifier_votes": clf_result.get("consensus_tally", "3/5 MAJORITY (COLD START)"),
                    "bullish_votes": clf_result.get("bullish_votes", 3),
                    "bearish_votes": clf_result.get("bearish_votes", 2),
                    "consensus_probability": clf_result.get("consensus_probability", 0.50),
                    "prob_bullish": clf_result.get("prob_bullish", 0.50),
                    "prob_bearish": clf_result.get("prob_bearish", 0.50),
                    "predicted_target_price": reg_result["predicted_target_price"],
                    "predicted_change_pct": reg_result["predicted_change_pct"],
                    "regressor_votes": reg_result["regression_votes"],
                    "winning_vote_count": reg_result["winning_vote_count"],
                    "classifier_breakdown": clf_result.get("model_breakdown", {}),
                    "regressor_breakdown": reg_result.get("model_predictions", {}),
                    "is_inside_bar": False,
                    "is_nr7": False,
                    "is_nr4": False,
                    "is_doji": False,
                    "is_coiling_squeeze": False,
                    "compression_score": 0.0,
                    "range_high": current_price * 1.01,
                    "range_low": current_price * 0.99,
                    "position_in_range_pct": 50.0,
                    "headroom_to_high_pct": 1.0,
                    "headroom_to_low_pct": 1.0,
                    "order_block_touch": tf_ob_info.get("has_touch", False),
                    "order_block_rank": tf_ob_info.get("touch_rank"),
                    "order_block_rank_label": tf_ob_info.get("touch_label"),
                    "order_block_type": tf_ob_info.get("touch_type", "NONE"),
                    "order_block_zone": tf_ob_info.get("nearest_zone"),
                    "total_order_blocks": tf_ob_info.get("total_blocks", 0)
                }
                continue

            c = df_tf["close"].values
            o = df_tf["open"].values
            n = len(df_tf)

            # Target 1: Next Candle Close Direction (1 if c[i+1] > c[i], else 0; never train on wicks)
            target_direction = np.zeros(n, dtype=int)
            for i in range(n - 1):
                if c[i + 1] > c[i]:
                    target_direction[i] = 1
                elif c[i + 1] < c[i]:
                    target_direction[i] = 0
                else:
                    target_direction[i] = 1 if c[i + 1] >= o[i + 1] else 0

            # Target 2: Next Candle Close Return (Price Change %; strictly candle close, never wicks)
            target_return = np.zeros(n, dtype=float)
            for i in range(n - 1):
                target_return[i] = (c[i + 1] - c[i]) / (c[i] + 1e-10)

            # Strictly use completed historical candles for training targets
            # If candle n-1 is the unclosed forming candle, targets for sample i are candle i+1.
            # Sample n-3's target is completed candle n-2. Sample n-2's target would be unclosed candle n-1, so exclude n-2 from training.
            # Indicator Warmup Trimming: Trim initial un-warmed rows where rolling features contain zero-fill artifacts.
            warmup_offset = min(35, max(0, n - 40)) if n >= 50 else 0
            if n >= 16:
                X = feats.iloc[warmup_offset:-2].values
                y_dir = target_direction[warmup_offset:-2]
                y_ret = target_return[warmup_offset:-2]
            else:
                X = feats.iloc[warmup_offset:-1].values
                y_dir = target_direction[warmup_offset:-1]
                y_ret = target_return[warmup_offset:-1]
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
            prob_b = clf_result.get("prob_bullish", clf_result.get("consensus_probability", 0.50))

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

            # Structural moving average alignment for macro trend primacy
            has_structural_bear = False
            has_structural_bull = False
            if len(df_tf) >= 20 and not is_cold_start and not is_synth and "close" in df_tf.columns:
                c_series = df_tf["close"].astype(float)
                c_last = float(c_series.iloc[-1])
                ema20_val = float(c_series.ewm(span=20, adjust=False).mean().iloc[-1])
                ema50_val = float(c_series.ewm(span=min(50, len(c_series)), adjust=False).mean().iloc[-1])
                # Higher Low / Lower High Pullback Recognition: In a bullish uptrend (EMA20 > EMA50), price pulling back
                # towards or testing EMA20/EMA50 to form a Higher Low must not be stripped of its BULLISH classification.
                if ema20_val > ema50_val and c_last >= (ema50_val * 0.995):
                    has_structural_bull = True
                elif ema20_val < ema50_val and c_last <= (ema50_val * 1.005):
                    has_structural_bear = True

            if is_cold_start:
                tf_trend = "CONSOLIDATION"
                tf_trend_label = f"🟡 ACCUMULATING (COLD START: N={n_raw})"
            elif has_structural_bear and bear_v >= 3:
                tf_trend = "BEARISH"
                tf_trend_label = "🔴 BEARISH (STRUCTURAL DOWNTREND)"
            elif has_structural_bull and bull_v >= 3:
                tf_trend = "BULLISH"
                tf_trend_label = "🟢 BULLISH (STRUCTURAL UPTREND)"
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
                "consensus_probability": clf_result.get("consensus_probability", 0.50),
                "prob_bullish": clf_result.get("prob_bullish", 0.50),
                "prob_bearish": clf_result.get("prob_bearish", 0.50),
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
        if not matrix_eval or not isinstance(matrix_eval, dict):
            matrix_eval = {
                "archetype": InstitutionalArchetype.ARCHETYPE_E_STAGNATION_DEAD_ZONE.value,
                "trade_permitted": False,
                "strategy": "CAPITAL_PRESERVATION",
                "dominant_direction": "NO_TRADE",
                "allocation_pct": 0.0,
                "headroom_pct": 0.0,
                "htf_range_high": current_price,
                "htf_range_low": current_price,
                "rationale": "Default cross-timeframe fallback",
            }

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
            triad_structure=triad_structure,
        )

        has_ob_15m = bool(ob_setup_15m and ob_setup_15m.get("setup_detected"))
        has_ob_1h = bool(ob_setup_1h and ob_setup_1h.get("setup_detected"))
        has_ob_24h = bool(ob_setup_24h and ob_setup_24h.get("setup_detected"))

        req_15m = q_15m["required_horizons"]
        req_1h = q_1h["required_horizons"]
        req_24h = q_24h["required_horizons"]

        # Choppiness Index & Low-Volatility Compression Filter (Portfolio Defense Gate)
        # If active 15M chart exhibits severe sideways chop (CI > 61.8 or ADX < 18.0),
        # prevent admission of trend breakout signals that lack strong volume expansion.
        df_15m_c = dfs_9.get("15m") if dfs_9 else None
        if df_15m_c is not None and len(df_15m_c) >= 15:
            c_idx_15m = no_trade_zone_engine.compute_chop_index(df_15m_c, period=14)
            adx_15m = no_trade_zone_engine.compute_adx(df_15m_c, period=14)
            if c_idx_15m > 61.8 or adx_15m < 18.0:
                # In severe chop / low-volatility regimes:
                # Suppress blind momentum/breakout chasing, but authorize high-probability mean-reversion setups:
                # 1. Verified Order Block reaction
                # 2. SMC Liquidity Sweep & Reclaim (Turtle Soup), VWAP bounce, or FVG retest
                # 3. Structural Range Boundary Extremes (Bounce from <= 25% floor or Rejection from >= 75% ceiling)
                range_pos_15m = 50.0
                rh_15m = float(df_15m_c["high"].rolling(20).max().iloc[-1])
                rl_15m = float(df_15m_c["low"].rolling(20).min().iloc[-1])
                if (rh_15m - rl_15m) > 1e-8:
                    range_pos_15m = float(np.clip(((current_price - rl_15m) / (rh_15m - rl_15m)) * 100.0, 0.0, 100.0))

                is_boundary_bounce = (range_pos_15m <= 25.0 and q_15m["direction"] == "LONG") or \
                                     (range_pos_15m >= 75.0 and q_15m["direction"] == "SHORT")
                is_mean_reversion_allowed = bool(
                    (has_ob_15m and ob_setup_15m.get("direction") == q_15m["direction"]) or
                    (has_smc_15m and smc_dir_15m == q_15m["direction"]) or
                    is_boundary_bounce
                )
                if not is_mean_reversion_allowed:
                    q_15m["qualified"] = False

        # Generate discrete qualified signals ONLY for 15M (Scalps)
        # Architecture Invariant: If a coin qualifies in 1H or 24H, convert that setup into a 15M Scalp signal
        # with entry, TP, and SL calculated according to the 15M chart.
        qualified_signals: Dict[str, Dict[str, Any]] = {}
        all_candidate_signals: Dict[str, Dict[str, Any]] = {}

        converted_from_hz = None
        target_dir_15m = q_15m.get("direction")

        # Converted setup check: If 15M did not qualify directly, but 1H or 24H qualified:
        # Convert that 1H/24H setup into a 15M Scalp with entry, TP, and SL calculated strictly on the 15M chart
        if not q_15m.get("qualified"):
            if q_1h.get("qualified") and q_1h.get("direction") in ["LONG", "SHORT"]:
                h1_dir = q_1h["direction"]
                triad_match = (
                    (h1_dir == "LONG" and trend_matrix.get("15m") != "BEARISH" and trend_matrix.get("1h") == "BULLISH" and trend_matrix.get("4h") != "BEARISH") or
                    (h1_dir == "SHORT" and trend_matrix.get("15m") != "BULLISH" and trend_matrix.get("1h") == "BEARISH" and trend_matrix.get("4h") != "BULLISH") or
                    (triad_structure is not None and getattr(triad_structure, "is_unanimously_aligned", False) and getattr(triad_structure, "trend_direction", None) == h1_dir)
                )
                if triad_match:
                    target_dir_15m = h1_dir
                    converted_from_hz = "1H"
                    q_15m["qualified"] = True
                    q_15m["direction"] = h1_dir
            elif q_24h.get("qualified") and q_24h.get("direction") in ["LONG", "SHORT"]:
                h24_dir = q_24h["direction"]
                triad_match = (
                    (h24_dir == "LONG" and trend_matrix.get("15m") != "BEARISH" and trend_matrix.get("1h") != "BEARISH" and trend_matrix.get("4h") == "BULLISH") or
                    (h24_dir == "SHORT" and trend_matrix.get("15m") != "BULLISH" and trend_matrix.get("1h") != "BULLISH" and trend_matrix.get("4h") == "BEARISH") or
                    (triad_structure is not None and getattr(triad_structure, "is_unanimously_aligned", False) and getattr(triad_structure, "trend_direction", None) == h24_dir)
                )
                if triad_match:
                    target_dir_15m = h24_dir
                    converted_from_hz = "24H"
                    q_15m["qualified"] = True
                    q_15m["direction"] = h24_dir

        if q_15m.get("qualified") and target_dir_15m in ["LONG", "SHORT"]:
            sig_15m = self._build_single_horizon_signal(
                symbol=symbol, horizon_label="15M", tf_key="15m",
                direction=target_dir_15m, current_price=current_price,
                dfs_9=dfs_9, horizon_prediction=horizon_predictions.get("15m"),
                btc_shield_state=btc_shield_state, aligned_horizons=req_15m,
                archetype_info=matrix_eval,
                order_block_setup=ob_setup_15m if has_ob_15m else (ob_setup_1h if converted_from_hz == "1H" else ob_setup_24h),
                volume_24h_usd=volume_24h_usd,
                bid_price=bid_price,
                ask_price=ask_price,
                spread_bps=spread_bps,
                fundamental_matrix=fund_matrix,
                alignment_score=alignment_score_pct,
                triad_structure=triad_structure
            )
            if sig_15m:
                if converted_from_hz:
                    sig_15m["converted_from_horizon"] = converted_from_hz
                    sig_15m["conversion_note"] = f"Converted from {converted_from_hz} setup to 15M Scalp with 15M TP/SL"
                all_candidate_signals["15M"] = sig_15m
                if sig_15m.get("is_trade_active") and not sig_15m.get("is_ntz_active", False):
                    qualified_signals["15M"] = sig_15m

        # User Mandate & System Invariant: Generate signals ONLY for 15-Minute execution horizon (Scalps)
        # All other execution horizons (1H intraday, 24H swings) are completely removed from trade signal generation.
        # 1H and 4H charts serve strictly as multi-horizon context and trend confluence anchors.
        for h_suppressed in ["1H", "24H"]:
            all_candidate_signals[h_suppressed] = {
                "horizon": h_suppressed,
                "is_trade_active": False,
                "ineligible_reason": f"HORIZON_{h_suppressed}_SUPPRESSED_ONLY_15M_EXECUTION_ALLOWED",
                "converted_to_15m": bool(converted_from_hz == h_suppressed)
            }

        # Check macro NTZ status: Flash Dump halts all signals; Squeeze/Micro-volatility exempts boundary & coiling alpha
        is_macro_ntz, macro_ntz_reason = self.is_macro_no_trade_zone(btc_shield_state)
        is_partition_stale = bool(btc_shield_state.get("is_partition_stale", False) or btc_shield_state.get("is_global_outage", False))
        is_macro_dump = (
            btc_shield_state.get("regime") == "FLASH_DUMP" or
            btc_shield_state.get("status_code") in ["BEAR_CASCADE_BLACKOUT", "ALERT_DUMP", "FLASH_DUMP"] or
            "DEFENSIVE_CASH_ONLY" in str(btc_shield_state.get("altcoin_posture", ""))
        )
        if is_macro_dump:
            qualified_signals.clear()
        elif is_macro_ntz:
            is_prolonged_micro = bool(
                btc_shield_state.get("is_prolonged_micro_volatility") or
                "MICRO_VOLATILITY" in str(btc_shield_state.get("status_code", "")) or
                "MICRO_VOLATILITY" in str(btc_shield_state.get("reason", ""))
            )
            # Squeeze / micro-volatility NTZ: Hold back middle chop to preserve capital, preserve boundary & coiling setups
            for hz in list(qualified_signals.keys()):
                sig_obj = qualified_signals[hz]
                is_ob = sig_obj.get("is_ob_setup") or sig_obj.get("is_order_block_signal")
                is_decoupled = bool(sig_obj.get("is_decoupled_trend", False))
                dec_str = f"{sig_obj.get('decision', '')} {sig_obj.get('canonical_strategy', '')} {sig_obj.get('strategy', '')} {sig_obj.get('quality_grade', '')}".upper()
                if is_prolonged_micro:
                    is_boundary_or_coiling = bool(
                        is_decoupled or
                        is_ob or
                        any(k in dec_str for k in ["ORDER_BLOCK", "BREAKER", "TURTLE_SOUP", "COILING", "EXPANSION", "BREAKOUT", "SQUEEZE_BREAKOUT", "DECOUPLED", "IDIOSYNCRATIC"])
                    )
                else:
                    is_boundary_or_coiling = bool(
                        is_decoupled or
                        is_ob or
                        any(k in dec_str for k in [
                            "ORDER_BLOCK", "BREAKER", "TURTLE_SOUP", "RANGE_SUPPORT",
                            "RANGE_RESISTANCE", "SUB_RANGE", "COILING", "EXPANSION", "BREAKOUT", "RANGE_BOUNCE", "SQUEEZE", "DECOUPLED", "IDIOSYNCRATIC"
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

        # Dominant timeframe prioritization: Dynamic institutional scoring by setup quality, conviction, and timeframe weight
        if qualified_signals:
            def _dom_score(sig_item):
                hz = sig_item.get("horizon", "")
                tf_w = 1.25 if hz == "24H" else (1.35 if hz == "1H" else 1.20)
                grade_str = str(sig_item.get("quality_grade", "")).upper()
                g_score = 30.0 if "A+" in grade_str else (20.0 if "GRADE A" in grade_str else 10.0)
                conv = float(sig_item.get("conviction", 70.0) or 70.0)
                ev = float(sig_item.get("ev_net", 0.0) or 0.0)
                return g_score + (conv * 0.4) + (tf_w * 10.0) + min(10.0, ev * 2.0)

            dom_sig = max(qualified_signals.values(), key=_dom_score)
        else:
            dom_sig = None

        radar_candidates = [
            s for s in all_candidate_signals.values()
            if s.get("signal_status") in [
                "HOLD_AWAITING_CANDLE_TRIGGER_CONFIRMATION",
                "HOLD_INSUFFICIENT_RISK_REWARD",
                "HOLD_SPREAD_DEGRADED_RR",
                "HOLD_FILTERED_BY_NEGATIVE_NET_EXPECTANCY",
                "PRE_SIGNAL_RADAR"
            ]
            or s.get("is_radar_eligible", False)
            or (float(s.get("ev_net", 0.0) or 0.0) > 0.0 and float(s.get("conviction", 0.0) or 0.0) >= 55.0)
            or s.get("is_shadow_eligible")
        ]

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
        elif is_macro_dump or is_partition_stale:
            dominant_direction = "NO_TRADE"
            active_signal_horizon = None
            grade = f"Grade C (MACRO BLACKOUT ACTIVE: {ntz_active_reason})"
            conviction = 0.0
            tp1_price = current_price
            tp2_price = current_price
            tp3_price = current_price
            sl_price = current_price
            rr_ratio = "1:1.0"
            pred_target = current_price
            pred_pct = 0.0
            status = "HOLD_VETOED_BY_NO_TRADE_ZONE"
            wait_reason = f"🛑 MACRO BLACKOUT ACTIVE: {ntz_active_reason}. Signal generation suppressed for capital preservation."
            dominant_timeframe = "NO_TRADE_ZONE"
            classifier_votes = ""
            regressor_votes = ""
            meta_win_prob = 0.50
            meta_win_prob_pct = 50.0
            meta_verdict = "VETOED_BY_NTZ"
            meta_model_type = "PRIMARY_ENSEMBLE"
            meta_sample_size = 0
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
            meta_model_type = "PRIMARY_ENSEMBLE"
            meta_sample_size = 0
        elif radar_candidates:
            # Phase 2: Finite State Machine (FSM) Pre-Signal Radar
            # When candidates have validated trend alignment, positive Net EV, and high probability,
            # but are waiting for trigger close or limit order fill, preserve setup on the Pre-Signal Radar!
            radar_sig = max(radar_candidates, key=lambda s: (float(s.get("conviction", 70.0) or 70.0) + (float(s.get("ev_net", 0.0) or 0.0) * 10.0)))
            
            dominant_direction = radar_sig.get("raw_direction") or radar_sig.get("direction")
            if dominant_direction in ["HOLD_VETOED", "NO_TRADE", None]:
                dominant_direction = radar_sig.get("setup_direction") or "LONG"
            active_signal_horizon = radar_sig["horizon"]
            grade = f"Grade B (PRE-SIGNAL RADAR: {radar_sig['horizon']} SETUP)" if "AWAITING" not in str(radar_sig.get("quality_grade", "")) else radar_sig["quality_grade"]
            conviction = float(radar_sig.get("conviction", 72.0) or 72.0)
            tp1_price = radar_sig.get("tp1_price", current_price)
            tp2_price = radar_sig.get("tp2_price", current_price)
            tp3_price = radar_sig.get("tp3_price", current_price)
            sl_price = radar_sig.get("sl_price", current_price)
            rr_ratio = radar_sig.get("risk_reward_ratio", "1:2.0")
            pred_target = radar_sig.get("predicted_target_price", current_price)
            pred_pct = radar_sig.get("expected_return_pct", 0.0)
            status = "PRE_SIGNAL_RADAR"

            # Dynamic 1:2.00 Limit Price Anchor
            tp1_v = float(tp1_price) if tp1_price > 0 else current_price
            sl_v = float(sl_price) if sl_price > 0 else current_price
            rr_target_entry = round((tp1_v + 2.0 * sl_v) / 3.0, 6) if (tp1_v > 0 and sl_v > 0) else current_price

            sig_st = radar_sig.get("signal_status", "")
            if sig_st in ["HOLD_INSUFFICIENT_RISK_REWARD", "HOLD_SPREAD_DEGRADED_RR"]:
                wait_reason = f"⏳ PRE-SIGNAL RADAR: Setup qualified for {dominant_direction} ({active_signal_horizon}). Awaiting price retracement to ${rr_target_entry:g} to achieve R:R >= 1:2.00 (current: {rr_ratio})."
            elif sig_st == "HOLD_FILTERED_BY_NEGATIVE_NET_EXPECTANCY":
                wait_reason = f"⏳ PRE-SIGNAL RADAR: Setup qualified for {dominant_direction} ({active_signal_horizon}). Awaiting favorable price geometry to achieve positive Net EV (current: {float(radar_sig.get('ev_net', 0.0)):+.2f}% after costs)."
            else:
                wait_reason = radar_sig.get("wait_reason") or f"⏳ PRE-SIGNAL RADAR: Setup qualified for {dominant_direction} ({active_signal_horizon}). Awaiting institutional candle trigger confirmation (Order Block reaction / Liquidity Sweep reclaim / VWAP bounce)."

            dominant_timeframe = radar_sig["horizon"]
            classifier_votes = radar_sig.get("classifier_votes", "")
            regressor_votes = radar_sig.get("regressor_votes", "")
            meta_win_prob = radar_sig.get("meta_win_probability", 0.52)
            meta_win_prob_pct = radar_sig.get("meta_win_probability_pct", 52.0)
            meta_verdict = "RADAR_HOTLIST"
            meta_model_type = radar_sig.get("meta_model_type", "PER_COIN_DEDICATED")
            meta_sample_size = radar_sig.get("meta_sample_size", 0)
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
            meta_win_prob = 0.50
            meta_win_prob_pct = 50.0
            meta_verdict = "VETOED_BY_NTZ"
            meta_model_type = "PRIMARY_ENSEMBLE"
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
            meta_win_prob = 0.50
            meta_win_prob_pct = 50.0
            meta_verdict = "AWAITING_ALIGNMENT"
            meta_model_type = "PRIMARY_ENSEMBLE"
            meta_sample_size = 0

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
            "status": status,
            "signal_status": status,
            "wait_reason": wait_reason,
            "decision": dom_sig.get("decision") if dom_sig else (
                f"🎯 [{grade}] (EXECUTION AUTHORIZED)" if is_trade_active else (
                    f"⏳ [{grade}]" if status == "PRE_SIGNAL_RADAR" else "AWAITING_ALIGNMENT"
                )
            ),
            "order_block_setup": dom_sig.get("order_block_setup") if dom_sig else None,
            "is_order_block_signal": dom_sig.get("is_order_block_signal", False) if dom_sig else False,
            "zeiierman_rank": dom_sig.get("zeiierman_rank") if dom_sig else None,
            "zeiierman_rank_label": dom_sig.get("zeiierman_rank_label") if dom_sig else None,
            "is_nested_smc": dom_sig.get("is_nested_smc", False) if dom_sig else False,
            "htf_poi_tf": dom_sig.get("htf_poi_tf") if dom_sig else None,
            "strategy": dom_sig.get("strategy") if dom_sig else (matrix_eval.get("strategy") if matrix_eval else "CAPITAL_PRESERVATION"),
            "canonical_strategy": dom_sig.get("canonical_strategy") if dom_sig else (dom_sig.get("strategy") if dom_sig else (matrix_eval.get("strategy") if matrix_eval else "CAPITAL_PRESERVATION")),
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
            "archetype": matrix_eval.get("archetype") if matrix_eval else InstitutionalArchetype.ARCHETYPE_E_STAGNATION_DEAD_ZONE.value,
            "strategy_playbook": matrix_eval.get("strategy") if matrix_eval else "CAPITAL_PRESERVATION",
            "allocation_pct": matrix_eval.get("allocation_pct", 0.0) if matrix_eval else 0.0,
            "headroom_pct": matrix_eval.get("headroom_pct", 0.0) if matrix_eval else 0.0,
            "matrix_rationale": matrix_eval.get("rationale", "") if matrix_eval else "",
            "cross_timeframe_matrix": matrix_eval or {},
            "trend_alignment": trend_alignment_info,
            "quality_grade": grade,
            "conviction": conviction,
            "entry_price": dom_sig["entry_price"] if dom_sig else (radar_sig.get("entry_price", current_price) if status == "PRE_SIGNAL_RADAR" else current_price),
            "optimal_entry_price": dom_sig.get("optimal_entry_price", current_price) if dom_sig else (radar_sig.get("optimal_entry_price", current_price) if status == "PRE_SIGNAL_RADAR" else current_price),
            "optimal_entry_limit": dom_sig.get("optimal_entry_limit", current_price) if dom_sig else (rr_target_entry if status == "PRE_SIGNAL_RADAR" else current_price),
            "entry_target_for_rr20": rr_target_entry if status == "PRE_SIGNAL_RADAR" else current_price,
            "entry_zone_min": dom_sig.get("entry_zone_min", current_price) if dom_sig else (radar_sig.get("entry_zone_min", current_price) if status == "PRE_SIGNAL_RADAR" else current_price),
            "entry_zone_max": dom_sig.get("entry_zone_max", current_price) if dom_sig else (radar_sig.get("entry_zone_max", current_price) if status == "PRE_SIGNAL_RADAR" else current_price),
            "is_limit_pending": dom_sig.get("is_limit_pending", False) if dom_sig else (True if status == "PRE_SIGNAL_RADAR" else False),
            "entry_mode": dom_sig.get("entry_mode", "MARKET") if dom_sig else ("LIMIT" if status == "PRE_SIGNAL_RADAR" else "MARKET"),
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
            "tp3_price": tp3_price,
            "sl_price": sl_price,
            "risk_reward_ratio": rr_ratio,
            "expected_return_pct": pred_pct,
            "ev_net": dom_sig.get("ev_net", 0.0) if dom_sig else (radar_sig.get("ev_net", 0.0) if status == "PRE_SIGNAL_RADAR" else 0.0),
            "actual_rr": dom_sig.get("actual_rr", 0.0) if dom_sig else (radar_sig.get("actual_rr", 0.0) if status == "PRE_SIGNAL_RADAR" else 0.0),
            "effective_rr": dom_sig.get("effective_rr", 0.0) if dom_sig else (radar_sig.get("effective_rr", 0.0) if status == "PRE_SIGNAL_RADAR" else 0.0),
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
            "triad_structure": triad_structure.to_dict() if hasattr(triad_structure, "to_dict") else None,
            "is_candlestick_unanimous": getattr(triad_structure, "is_unanimously_aligned", False),
            "candlestick_direction": getattr(triad_structure, "trend_direction", "NEUTRAL"),
            "has_order_block": getattr(triad_structure, "has_order_block", False),
            "dominant_ob_timeframe": getattr(triad_structure, "dominant_ob_timeframe", "15M"),
            "dominant_order_block": triad_structure.dominant_order_block.to_dict() if getattr(triad_structure, "dominant_order_block", None) else None,
            "order_block_source": getattr(triad_structure, "order_block_source", "TREND_ALIGNMENT_DEFAULT"),
            "entry_anchor_pivot": triad_structure.entry_anchor_pivot.to_dict() if getattr(triad_structure, "entry_anchor_pivot", None) else None,
            "opposing_target_pivot": triad_structure.opposing_target_pivot.to_dict() if getattr(triad_structure, "opposing_target_pivot", None) else None,
            "active_ob_15m": triad_structure.active_ob_15m.to_dict() if getattr(triad_structure, "active_ob_15m", None) else None,
            "horizon_predictions": horizon_predictions,
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
