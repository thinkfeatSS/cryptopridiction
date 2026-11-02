"""
QUANT EDGE V16: Strategy Archetypes & Performance Registry
Specifications:
- Section 7: Strategy Archetypes (14 initial strategies)
- Section 8: Strategy Performance Registry (Rolling PF, win rate, expectancy, status)
- Section 31: Strategy Kill Switch (ACTIVE, WARNING, PAUSED, DISABLED)
- Section 32: Regime-Specific Kill Switch
"""

from enum import Enum
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
import time

class StrategyArchetype(str, Enum):
    MOMENTUM_LONG = "MOMENTUM_LONG"
    MOMENTUM_SHORT = "MOMENTUM_SHORT"
    BREAKOUT_LONG = "BREAKOUT_LONG"
    BREAKOUT_SHORT = "BREAKOUT_SHORT"
    DIP_BUY_LONG = "DIP_BUY_LONG"
    TOP_REVERSAL_SHORT = "TOP_REVERSAL_SHORT"
    BOTTOM_REVERSAL_LONG = "BOTTOM_REVERSAL_LONG"
    BLOW_OFF_TOP_SHORT = "BLOW_OFF_TOP_SHORT"
    LIQUIDITY_SWEEP_LONG = "LIQUIDITY_SWEEP_LONG"
    LIQUIDITY_SWEEP_SHORT = "LIQUIDITY_SWEEP_SHORT"
    RANGE_BOUNCE_LONG = "RANGE_BOUNCE_LONG"
    RANGE_BOUNCE_SHORT = "RANGE_BOUNCE_SHORT"
    SQUEEZE_BREAKOUT_LONG = "SQUEEZE_BREAKOUT_LONG"
    SQUEEZE_BREAKOUT_SHORT = "SQUEEZE_BREAKOUT_SHORT"
    MEAN_REVERSION_LONG = "MEAN_REVERSION_LONG"
    MEAN_REVERSION_SHORT = "MEAN_REVERSION_SHORT"
    ORDER_BLOCK_LONG = "ORDER_BLOCK_LONG"
    ORDER_BLOCK_SHORT = "ORDER_BLOCK_SHORT"
    BREAKER_BLOCK_LONG = "BREAKER_BLOCK_LONG"
    BREAKER_BLOCK_SHORT = "BREAKER_BLOCK_SHORT"
    BREAKDOWN_SHORT = "BREAKDOWN_SHORT"
    RALLY_FADE_SHORT = "RALLY_FADE_SHORT"
    DIRECTIONAL_TREND_LONG = "DIRECTIONAL_TREND_LONG"
    DIRECTIONAL_TREND_SHORT = "DIRECTIONAL_TREND_SHORT"
    FVG_RETEST_LONG = "FVG_RETEST_LONG"
    FVG_RETEST_SHORT = "FVG_RETEST_SHORT"
    VWAP_BOUNCE_LONG = "VWAP_BOUNCE_LONG"
    VWAP_BOUNCE_SHORT = "VWAP_BOUNCE_SHORT"
    LIQUIDITY_RECLAIM_LONG = "LIQUIDITY_RECLAIM_LONG"
    LIQUIDITY_RECLAIM_SHORT = "LIQUIDITY_RECLAIM_SHORT"
    SQUEEZE_EXPANSION_LONG = "SQUEEZE_EXPANSION_LONG"
    SQUEEZE_EXPANSION_SHORT = "SQUEEZE_EXPANSION_SHORT"

class StrategyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WARNING = "WARNING"
    PAUSED = "PAUSED"
    DISABLED = "DISABLED"
    EXPERIMENTAL = "EXPERIMENTAL"

@dataclass
class StrategyPerformance:
    strategy_id: str
    sample_count: int = 0
    resolved_count: int = 0
    win_rate: float = 0.50
    profit_factor: float = 1.25
    rolling_50_pf: float = 1.20
    expectancy_net_pct: float = 0.45
    max_drawdown_pct: float = 4.5
    status: StrategyStatus = StrategyStatus.ACTIVE
    regime_status: Dict[str, StrategyStatus] = field(default_factory=dict)
    last_updated_ts: float = field(default_factory=time.time)

def normalize_regime_key(regime: Any) -> str:
    """Normalizes raw market regime labels and composite strings into canonical regime keys."""
    if not regime:
        return "RANGE"
    r = str(getattr(regime, "value", regime)).strip().upper()
    if any(k in r for k in ["BEAR", "DUMP", "FALLING", "DOWN"]):
        return "BEAR_TREND"
    if any(k in r for k in ["BULL", "PUMP", "RALLY", "UP"]):
        return "BULL_TREND"
    if "SQUEEZE" in r:
        return "SQUEEZE"
    if "BREAKOUT" in r:
        return "BREAKOUT"
    if "HIGH_VOLATILITY" in r or "VOLATILE" in r:
        return "HIGH_VOLATILITY"
    if any(k in r for k in ["RANGE", "CONSOLIDATION", "CHOP"]):
        return "RANGE"
    return r

class StrategyRegistry:
    """
    Maintains historical performance records and automated kill switches for all strategy archetypes.
    """

    def __init__(self):
        self.strategies: Dict[str, StrategyPerformance] = {}
        self._init_defaults()

    def _init_defaults(self):
        """Populate initial baseline priors from V15 empirical audit for all 32 StrategyArchetype members."""
        priors = {
            # Strong performers in V15
            StrategyArchetype.TOP_REVERSAL_SHORT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.TOP_REVERSAL_SHORT.value,
                sample_count=210, resolved_count=195, win_rate=0.64, profit_factor=1.45,
                rolling_50_pf=1.38, expectancy_net_pct=0.82,
                regime_status={"BULL_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.BOTTOM_REVERSAL_LONG.value: StrategyPerformance(
                strategy_id=StrategyArchetype.BOTTOM_REVERSAL_LONG.value,
                sample_count=100, resolved_count=92, win_rate=0.59, profit_factor=1.30,
                rolling_50_pf=1.24, expectancy_net_pct=0.52,
                regime_status={"BEAR_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.BLOW_OFF_TOP_SHORT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.BLOW_OFF_TOP_SHORT.value,
                sample_count=145, resolved_count=140, win_rate=0.68, profit_factor=1.62,
                rolling_50_pf=1.50, expectancy_net_pct=1.15
            ),
            StrategyArchetype.RANGE_BOUNCE_SHORT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.RANGE_BOUNCE_SHORT.value,
                sample_count=180, resolved_count=172, win_rate=0.58, profit_factor=1.28,
                rolling_50_pf=1.22, expectancy_net_pct=0.55
            ),
            StrategyArchetype.RANGE_BOUNCE_LONG.value: StrategyPerformance(
                strategy_id=StrategyArchetype.RANGE_BOUNCE_LONG.value,
                sample_count=165, resolved_count=158, win_rate=0.56, profit_factor=1.22,
                rolling_50_pf=1.18, expectancy_net_pct=0.48
            ),
            StrategyArchetype.BREAKOUT_LONG.value: StrategyPerformance(
                strategy_id=StrategyArchetype.BREAKOUT_LONG.value,
                sample_count=130, resolved_count=124, win_rate=0.52, profit_factor=1.25,
                rolling_50_pf=1.16, expectancy_net_pct=0.50,
                regime_status={"BEAR_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.BREAKOUT_SHORT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.BREAKOUT_SHORT.value,
                sample_count=110, resolved_count=105, win_rate=0.55, profit_factor=1.30,
                rolling_50_pf=1.25, expectancy_net_pct=0.62,
                regime_status={"BULL_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.MOMENTUM_SHORT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.MOMENTUM_SHORT.value,
                sample_count=190, resolved_count=182, win_rate=0.59, profit_factor=1.35,
                rolling_50_pf=1.28, expectancy_net_pct=0.68,
                regime_status={"BULL_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.MOMENTUM_LONG.value: StrategyPerformance(
                strategy_id=StrategyArchetype.MOMENTUM_LONG.value,
                sample_count=175, resolved_count=165, win_rate=0.50, profit_factor=1.12,
                rolling_50_pf=1.05, expectancy_net_pct=0.22,
                regime_status={"RANGE": StrategyStatus.PAUSED, "BEAR_TREND": StrategyStatus.DISABLED}
            ),
            StrategyArchetype.DIP_BUY_LONG.value: StrategyPerformance(
                strategy_id=StrategyArchetype.DIP_BUY_LONG.value,
                sample_count=135, resolved_count=128, win_rate=0.62, profit_factor=1.36,
                rolling_50_pf=1.30, expectancy_net_pct=0.64,
                regime_status={"BEAR_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.BREAKDOWN_SHORT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.BREAKDOWN_SHORT.value,
                sample_count=180, resolved_count=172, win_rate=0.62, profit_factor=1.35,
                rolling_50_pf=1.30, expectancy_net_pct=0.65,
                regime_status={"BULL_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.RALLY_FADE_SHORT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.RALLY_FADE_SHORT.value,
                sample_count=120, resolved_count=110, win_rate=0.58, profit_factor=1.28,
                rolling_50_pf=1.22, expectancy_net_pct=0.52,
                regime_status={"BULL_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.ORDER_BLOCK_SHORT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.ORDER_BLOCK_SHORT.value,
                sample_count=85, resolved_count=80, win_rate=0.60, profit_factor=1.32,
                rolling_50_pf=1.28, expectancy_net_pct=0.58,
                regime_status={"BULL_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.ORDER_BLOCK_LONG.value: StrategyPerformance(
                strategy_id=StrategyArchetype.ORDER_BLOCK_LONG.value,
                sample_count=85, resolved_count=80, win_rate=0.61, profit_factor=1.34,
                rolling_50_pf=1.30, expectancy_net_pct=0.60,
                regime_status={"BEAR_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.BREAKER_BLOCK_SHORT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.BREAKER_BLOCK_SHORT.value,
                sample_count=70, resolved_count=65, win_rate=0.57, profit_factor=1.26,
                rolling_50_pf=1.20, expectancy_net_pct=0.48,
                regime_status={"BULL_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.BREAKER_BLOCK_LONG.value: StrategyPerformance(
                strategy_id=StrategyArchetype.BREAKER_BLOCK_LONG.value,
                sample_count=70, resolved_count=65, win_rate=0.58, profit_factor=1.28,
                rolling_50_pf=1.22, expectancy_net_pct=0.50,
                regime_status={"BEAR_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.DIRECTIONAL_TREND_SHORT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.DIRECTIONAL_TREND_SHORT.value,
                sample_count=95, resolved_count=90, win_rate=0.61, profit_factor=1.34,
                rolling_50_pf=1.26, expectancy_net_pct=0.56,
                regime_status={"BULL_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.DIRECTIONAL_TREND_LONG.value: StrategyPerformance(
                strategy_id=StrategyArchetype.DIRECTIONAL_TREND_LONG.value,
                sample_count=110, resolved_count=105, win_rate=0.58, profit_factor=1.28,
                rolling_50_pf=1.22, expectancy_net_pct=0.50,
                regime_status={"BEAR_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.LIQUIDITY_SWEEP_SHORT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.LIQUIDITY_SWEEP_SHORT.value,
                sample_count=105, resolved_count=98, win_rate=0.62, profit_factor=1.35,
                rolling_50_pf=1.28, expectancy_net_pct=0.60,
                regime_status={"BULL_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.LIQUIDITY_SWEEP_LONG.value: StrategyPerformance(
                strategy_id=StrategyArchetype.LIQUIDITY_SWEEP_LONG.value,
                sample_count=95, resolved_count=88, win_rate=0.59, profit_factor=1.30,
                rolling_50_pf=1.24, expectancy_net_pct=0.52,
                regime_status={"BEAR_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.FVG_RETEST_LONG.value: StrategyPerformance(
                strategy_id=StrategyArchetype.FVG_RETEST_LONG.value,
                sample_count=115, resolved_count=108, win_rate=0.61, profit_factor=1.35,
                rolling_50_pf=1.30, expectancy_net_pct=0.62,
                regime_status={"BEAR_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.FVG_RETEST_SHORT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.FVG_RETEST_SHORT.value,
                sample_count=125, resolved_count=118, win_rate=0.63, profit_factor=1.40,
                rolling_50_pf=1.35, expectancy_net_pct=0.72,
                regime_status={"BULL_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.VWAP_BOUNCE_LONG.value: StrategyPerformance(
                strategy_id=StrategyArchetype.VWAP_BOUNCE_LONG.value,
                sample_count=100, resolved_count=94, win_rate=0.59, profit_factor=1.30,
                rolling_50_pf=1.25, expectancy_net_pct=0.55,
                regime_status={"BEAR_TREND": StrategyStatus.PAUSED, "RANGE": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.VWAP_BOUNCE_SHORT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.VWAP_BOUNCE_SHORT.value,
                sample_count=105, resolved_count=98, win_rate=0.60, profit_factor=1.32,
                rolling_50_pf=1.28, expectancy_net_pct=0.58,
                regime_status={"BULL_TREND": StrategyStatus.PAUSED, "RANGE": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.LIQUIDITY_RECLAIM_LONG.value: StrategyPerformance(
                strategy_id=StrategyArchetype.LIQUIDITY_RECLAIM_LONG.value,
                sample_count=130, resolved_count=122, win_rate=0.64, profit_factor=1.42,
                rolling_50_pf=1.36, expectancy_net_pct=0.75,
                regime_status={"BEAR_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.LIQUIDITY_RECLAIM_SHORT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.LIQUIDITY_RECLAIM_SHORT.value,
                sample_count=140, resolved_count=132, win_rate=0.65, profit_factor=1.45,
                rolling_50_pf=1.38, expectancy_net_pct=0.78,
                regime_status={"BULL_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.SQUEEZE_EXPANSION_LONG.value: StrategyPerformance(
                strategy_id=StrategyArchetype.SQUEEZE_EXPANSION_LONG.value,
                sample_count=85, resolved_count=80, win_rate=0.58, profit_factor=1.32,
                rolling_50_pf=1.26, expectancy_net_pct=0.54,
                regime_status={"BEAR_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.SQUEEZE_EXPANSION_SHORT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.SQUEEZE_EXPANSION_SHORT.value,
                sample_count=90, resolved_count=85, win_rate=0.60, profit_factor=1.36,
                rolling_50_pf=1.30, expectancy_net_pct=0.64,
                regime_status={"BULL_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.SQUEEZE_BREAKOUT_LONG.value: StrategyPerformance(
                strategy_id=StrategyArchetype.SQUEEZE_BREAKOUT_LONG.value,
                sample_count=95, resolved_count=90, win_rate=0.57, profit_factor=1.26,
                rolling_50_pf=1.22, expectancy_net_pct=0.48,
                regime_status={"BEAR_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.SQUEEZE_BREAKOUT_SHORT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.SQUEEZE_BREAKOUT_SHORT.value,
                sample_count=95, resolved_count=90, win_rate=0.58, profit_factor=1.28,
                rolling_50_pf=1.24, expectancy_net_pct=0.52,
                regime_status={"BULL_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.MEAN_REVERSION_LONG.value: StrategyPerformance(
                strategy_id=StrategyArchetype.MEAN_REVERSION_LONG.value,
                sample_count=110, resolved_count=104, win_rate=0.56, profit_factor=1.22,
                rolling_50_pf=1.18, expectancy_net_pct=0.45,
                regime_status={"BEAR_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.MEAN_REVERSION_SHORT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.MEAN_REVERSION_SHORT.value,
                sample_count=115, resolved_count=108, win_rate=0.58, profit_factor=1.25,
                rolling_50_pf=1.20, expectancy_net_pct=0.48,
                regime_status={"BULL_TREND": StrategyStatus.PAUSED}
            ),
        }

        # Initialize all archetypes cleanly
        for arch in StrategyArchetype:
            val = arch.value
            if val in priors:
                self.strategies[val] = priors[val]
            else:
                self.strategies[val] = StrategyPerformance(
                    strategy_id=val,
                    sample_count=50, resolved_count=45, win_rate=0.52, profit_factor=1.15,
                    rolling_50_pf=1.12, expectancy_net_pct=0.35, status=StrategyStatus.ACTIVE
                )

    def is_strategy_allowed(self, strategy_id: str, current_regime: str) -> Tuple[bool, str]:
        """
        Evaluates Section 31 Strategy Kill Switch & Section 32 Regime Kill Switch.
        Supports fuzzy regime normalization and alias matching.
        """
        perf = self.strategies.get(strategy_id)
        if not perf:
            return True, "Active (Unregistered Strategy)"

        # 1. Global Strategy Status check
        if perf.status == StrategyStatus.DISABLED:
            return False, f"Strategy {strategy_id} is permanently DISABLED (Expectancy < 0)"
        if perf.status == StrategyStatus.PAUSED:
            return False, f"Strategy {strategy_id} is PAUSED (Rolling 50 PF < 0.80)"

        # 2. Section 32: Regime-Specific Kill Switch
        norm_regime = normalize_regime_key(current_regime)
        raw_regime = str(getattr(current_regime, "value", current_regime)).strip().upper() if current_regime else "RANGE"
        regime_st = perf.regime_status.get(norm_regime) or perf.regime_status.get(raw_regime)
        if regime_st in [StrategyStatus.PAUSED, StrategyStatus.DISABLED]:
            return False, f"Strategy {strategy_id} is {regime_st.value} specifically in {norm_regime} regime"

        return True, "Eligible"

    def get_edge_multiplier(self, strategy_id: str) -> float:
        """Returns strategy performance weighting multiplier for probability adjustment."""
        perf = self.strategies.get(strategy_id)
        if not perf or perf.rolling_50_pf <= 0:
            return 1.0
        # Normalizes PF between 0.85x and 1.25x
        return max(0.85, min(1.25, perf.rolling_50_pf / 1.20))
