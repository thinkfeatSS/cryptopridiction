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
import os
import json
import time
import threading

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
    RECTANGLE_STRATEGY_LONG = "RECTANGLE_STRATEGY_LONG"
    RECTANGLE_STRATEGY_SHORT = "RECTANGLE_STRATEGY_SHORT"
    MULTI_HORIZON_TREND = "MULTI_HORIZON_TREND"
    MOMENTUM_TREND_EXPANSION = "MOMENTUM_TREND_EXPANSION"
    COILING_VOLATILITY_BREAKOUT = "COILING_VOLATILITY_BREAKOUT"

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
    shadow_sample_count: int = 0
    shadow_resolved_count: int = 0
    shadow_wins: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "sample_count": self.sample_count,
            "resolved_count": self.resolved_count,
            "win_rate": round(float(self.win_rate), 4),
            "profit_factor": round(float(self.profit_factor), 4),
            "rolling_50_pf": round(float(self.rolling_50_pf), 4),
            "expectancy_net_pct": round(float(self.expectancy_net_pct), 4),
            "max_drawdown_pct": round(float(self.max_drawdown_pct), 4),
            "status": self.status.value,
            "regime_status": {k: (v.value if hasattr(v, "value") else str(v)) for k, v in self.regime_status.items()},
            "last_updated_ts": float(self.last_updated_ts),
            "shadow_sample_count": int(self.shadow_sample_count),
            "shadow_resolved_count": int(self.shadow_resolved_count),
            "shadow_wins": int(self.shadow_wins)
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "StrategyPerformance":
        st_val = StrategyStatus(d.get("status", "ACTIVE")) if d.get("status") in [s.value for s in StrategyStatus] else StrategyStatus.ACTIVE
        regime_st = {}
        for r_k, r_v in d.get("regime_status", {}).items():
            if r_v in [s.value for s in StrategyStatus]:
                regime_st[r_k] = StrategyStatus(r_v)
            else:
                regime_st[r_k] = StrategyStatus.ACTIVE
        return cls(
            strategy_id=d.get("strategy_id", ""),
            sample_count=int(d.get("sample_count", 0)),
            resolved_count=int(d.get("resolved_count", 0)),
            win_rate=float(d.get("win_rate", 0.50)),
            profit_factor=float(d.get("profit_factor", 1.25)),
            rolling_50_pf=float(d.get("rolling_50_pf", 1.20)),
            expectancy_net_pct=float(d.get("expectancy_net_pct", 0.45)),
            max_drawdown_pct=float(d.get("max_drawdown_pct", 4.5)),
            status=st_val,
            regime_status=regime_st,
            last_updated_ts=float(d.get("last_updated_ts", time.time())),
            shadow_sample_count=int(d.get("shadow_sample_count", 0)),
            shadow_resolved_count=int(d.get("shadow_resolved_count", 0)),
            shadow_wins=int(d.get("shadow_wins", 0))
        )

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

    def __init__(self, persistence_file: Optional[str] = None):
        self._lock = threading.Lock()
        self.strategies: Dict[str, StrategyPerformance] = {}
        export_dir = os.getenv("EXPORT_DIR", "./export_app_data")
        self.persistence_file = persistence_file or os.path.join(export_dir, "v16_strategy_priors.json")
        self._init_defaults()
        self.load_from_disk()

    def save_to_disk(self, file_path: Optional[str] = None) -> bool:
        """Atomically persists current strategy performance priors and kill switch states to disk."""
        path = file_path or self.persistence_file
        with self._lock:
            try:
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
                data = {
                    "version": "16.1",
                    "last_updated_utc": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
                    "strategies": {k: v.to_dict() for k, v in self.strategies.items()}
                }
                tmp_p = f"{path}.tmp.{threading.get_ident()}.{time.time_ns()}"
                with open(tmp_p, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                os.replace(tmp_p, path)
                return True
            except Exception:
                return False

    def load_from_disk(self, file_path: Optional[str] = None) -> bool:
        """Loads persisted strategy performance priors from disk and updates in-memory registry."""
        path = file_path or self.persistence_file
        if not os.path.exists(path):
            return False
        with self._lock:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                loaded_strats = data.get("strategies", {})
                # Safeguard against loading corrupted priors where strategies collapsed to <= 0.40 PF or were erroneously mass-disabled
                disabled_count = sum(1 for v in loaded_strats.values() if v.get("status") == "DISABLED" or float(v.get("rolling_50_pf", 1.0) or 1.0) <= 0.40)
                if len(loaded_strats) > 10 and (disabled_count / len(loaded_strats)) > 0.40:
                    import logging
                    logging.getLogger("strategies").warning(f"[STRATEGY REGISTRY ⚠️] Detected corrupted strategy priors on disk ({disabled_count}/{len(loaded_strats)} disabled/collapsed). Restoring clean baseline defaults.")
                    self._init_defaults()
                    self.save_to_disk()
                    return True

                for k, v_dict in loaded_strats.items():
                    self.strategies[k] = StrategyPerformance.from_dict(v_dict)
                return True
            except Exception:
                return False

    def record_trade_outcome(
        self,
        strategy_id: str,
        is_win: bool,
        net_return_pct: float,
        regime: Optional[str] = None
    ):
        """
        Updates live performance records upon trade resolution:
        1. Recalculates win rate using Bayesian smoothing.
        2. Recalculates rolling profit factor and net expectancy.
        3. Enforces Section 31 automated kill switch (Warning / Pause / Disable).
        4. Persists updated priors atomically to disk.
        """
        strat_key = strategy_id.upper().strip() if strategy_id else ""
        perf = self.strategies.get(strat_key)
        if not perf:
            return

        with self._lock:
            perf.sample_count += 1
            perf.resolved_count += 1
            n = max(1, perf.resolved_count)

            # Bayesian update on win rate: prior weight = 10 trades
            prior_wr = 0.50
            prior_weight = 10.0
            actual_wins = (perf.win_rate * (n - 1)) + (1.0 if is_win else 0.0)
            perf.win_rate = round(float((actual_wins + (prior_wr * prior_weight)) / (n + prior_weight)), 4)

            # Rolling profit factor update using proportional update
            ret_factor = max(0.1, 1.0 + (net_return_pct / 100.0)) if is_win else max(0.1, 1.0 - (abs(net_return_pct) / 100.0))
            if is_win:
                perf.rolling_50_pf = round(min(3.0, (perf.rolling_50_pf * 0.98) + (ret_factor * 0.02 * 1.25)), 4)
            else:
                perf.rolling_50_pf = round(max(0.4, (perf.rolling_50_pf * 0.98) - (0.02 * (1.0 / ret_factor))), 4)

            # Update rolling net expectancy
            perf.expectancy_net_pct = round(float((perf.expectancy_net_pct * 0.95) + (net_return_pct * 0.05)), 4)
            perf.last_updated_ts = time.time()

            # Section 31 Automated Kill Switch Gating: only disable with statistical confidence (>= 20 trades)
            if n >= 20 and perf.expectancy_net_pct < -0.20:
                perf.status = StrategyStatus.DISABLED
            elif n >= 15 and perf.rolling_50_pf < 0.80:
                perf.status = StrategyStatus.PAUSED
            elif perf.rolling_50_pf < 1.00:
                perf.status = StrategyStatus.WARNING
            else:
                perf.status = StrategyStatus.ACTIVE

            # Section 32 Regime-Specific Status
            if regime:
                norm_r = normalize_regime_key(regime)
                if not is_win and perf.rolling_50_pf < 0.90:
                    perf.regime_status[norm_r] = StrategyStatus.PAUSED
                elif is_win and perf.rolling_50_pf >= 1.05:
                    perf.regime_status.pop(norm_r, None)

        self.save_to_disk()

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
                regime_status={"BULL_TREND": StrategyStatus.PAUSED, "RANGE": StrategyStatus.PAUSED, "BEAR_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.MOMENTUM_SHORT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.MOMENTUM_SHORT.value,
                sample_count=190, resolved_count=182, win_rate=0.59, profit_factor=1.35,
                rolling_50_pf=1.28, expectancy_net_pct=0.68,
                regime_status={"BULL_TREND": StrategyStatus.PAUSED, "RANGE": StrategyStatus.PAUSED, "BEAR_TREND": StrategyStatus.PAUSED}
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
                regime_status={"BULL_TREND": StrategyStatus.PAUSED, "RANGE": StrategyStatus.PAUSED, "BEAR_TREND": StrategyStatus.PAUSED}
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
                regime_status={"BULL_TREND": StrategyStatus.PAUSED, "RANGE": StrategyStatus.PAUSED, "BEAR_TREND": StrategyStatus.PAUSED}
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
                regime_status={"BEAR_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.VWAP_BOUNCE_SHORT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.VWAP_BOUNCE_SHORT.value,
                sample_count=105, resolved_count=98, win_rate=0.60, profit_factor=1.32,
                rolling_50_pf=1.28, expectancy_net_pct=0.58,
                regime_status={"BULL_TREND": StrategyStatus.PAUSED}
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
                regime_status={"BULL_TREND": StrategyStatus.PAUSED, "RANGE": StrategyStatus.PAUSED, "BEAR_TREND": StrategyStatus.PAUSED}
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
            StrategyArchetype.RECTANGLE_STRATEGY_LONG.value: StrategyPerformance(
                strategy_id=StrategyArchetype.RECTANGLE_STRATEGY_LONG.value,
                sample_count=80, resolved_count=75, win_rate=0.62, profit_factor=1.38,
                rolling_50_pf=1.32, expectancy_net_pct=0.65,
                regime_status={"BEAR_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.RECTANGLE_STRATEGY_SHORT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.RECTANGLE_STRATEGY_SHORT.value,
                sample_count=85, resolved_count=80, win_rate=0.63, profit_factor=1.40,
                rolling_50_pf=1.35, expectancy_net_pct=0.68,
                regime_status={"BULL_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.MULTI_HORIZON_TREND.value: StrategyPerformance(
                strategy_id=StrategyArchetype.MULTI_HORIZON_TREND.value,
                sample_count=69, resolved_count=69, win_rate=0.0588, profit_factor=0.20,
                rolling_50_pf=0.45, expectancy_net_pct=-0.99,
                regime_status={"RANGE": StrategyStatus.PAUSED, "CONSOLIDATION": StrategyStatus.PAUSED, "CHOP": StrategyStatus.PAUSED, "BEAR_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.MOMENTUM_TREND_EXPANSION.value: StrategyPerformance(
                strategy_id=StrategyArchetype.MOMENTUM_TREND_EXPANSION.value,
                sample_count=38, resolved_count=38, win_rate=0.0, profit_factor=0.10,
                rolling_50_pf=0.40, expectancy_net_pct=-0.77,
                regime_status={"RANGE": StrategyStatus.PAUSED, "CONSOLIDATION": StrategyStatus.PAUSED, "CHOP": StrategyStatus.PAUSED, "BEAR_TREND": StrategyStatus.PAUSED}
            ),
            StrategyArchetype.COILING_VOLATILITY_BREAKOUT.value: StrategyPerformance(
                strategy_id=StrategyArchetype.COILING_VOLATILITY_BREAKOUT.value,
                sample_count=29, resolved_count=29, win_rate=0.0, profit_factor=0.10,
                rolling_50_pf=0.40, expectancy_net_pct=-0.52,
                regime_status={"RANGE": StrategyStatus.PAUSED, "CONSOLIDATION": StrategyStatus.PAUSED, "CHOP": StrategyStatus.PAUSED}
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

    def is_strategy_allowed(self, strategy_id: str, current_regime: str, is_decoupled_trend: bool = False, asset_regime: Optional[str] = None) -> Tuple[bool, str]:
        """
        Evaluates Section 31 Strategy Kill Switch & Section 32 Regime Kill Switch.
        Supports fuzzy regime normalization, alias matching, and altcoin idiosyncratic decoupling.
        """
        norm_regime = normalize_regime_key(current_regime)
        raw_regime = str(getattr(current_regime, "value", current_regime)).strip().upper() if current_regime else "RANGE"

        perf = self.strategies.get(strategy_id)
        if not perf and strategy_id:
            norm_id = strategy_id.upper().strip()
            perf = self.strategies.get(norm_id)

        strat_upper = str(strategy_id or "").upper().strip()

        # Phase 2: Section 32 Strict Fail-Closed Veto for Trend-Following & Breakout Strategies in Range / Chop
        if norm_regime in ["RANGE", "CONSOLIDATION", "CHOP"]:
            if any(k in strat_upper for k in ["TREND", "MOMENTUM", "BREAKOUT", "EXPANSION", "COILING", "MULTI_HORIZON"]):
                if is_decoupled_trend:
                    return True, f"Eligible: Decoupled independent {strategy_id} active during macro consolidation"
                return False, f"Section 32: Trend continuation strategy {strategy_id} strictly PAUSED in {norm_regime} regime"

        if not perf:
            # Dynamic Safeguard: Unregistered continuation shorts must NOT bypass regime kill switches
            if "SHORT" in strat_upper and norm_regime in ["RANGE", "BEAR_TREND"]:
                if any(k in strat_upper for k in ["BREAKOUT", "BREAKDOWN", "MOMENTUM", "TREND", "COILING", "EXPANSION"]):
                    if is_decoupled_trend:
                        return True, f"Eligible: Decoupled independent {strategy_id} active during macro consolidation"
                    return False, f"Strategy {strategy_id} is PAUSED specifically in {norm_regime} regime (Unregistered Continuation Short)"
            return True, "Active (Unregistered Strategy)"

        # 1. Global Strategy Status check
        if perf.status == StrategyStatus.DISABLED:
            return False, f"Strategy {strategy_id} is permanently DISABLED (Expectancy < 0)"
        if perf.status == StrategyStatus.PAUSED:
            return False, f"Strategy {strategy_id} is PAUSED (Rolling 50 PF < 0.80)"

        # 2. Section 32: Regime-Specific Kill Switch
        regime_st = perf.regime_status.get(norm_regime) or perf.regime_status.get(raw_regime)
        if regime_st in [StrategyStatus.PAUSED, StrategyStatus.DISABLED]:
            return False, f"Strategy {strategy_id} is {regime_st.value} specifically in {norm_regime} regime"

        return True, "Eligible"

    def is_strategy_shadow_eligible(self, strategy_id: str, current_regime: str) -> Tuple[bool, str]:
        """
        Feature 5.1: Evaluates whether a strategy vetoed by Section 31/32 kill switch
        is eligible for shadow tracking simulation and pre-signal radar monitoring.
        """
        strat_key = strategy_id.upper().strip() if strategy_id else ""
        perf = self.strategies.get(strat_key)
        if not perf:
            return False, "Strategy not registered"
        if perf.status in [StrategyStatus.PAUSED, StrategyStatus.DISABLED, StrategyStatus.WARNING]:
            return True, f"Strategy {strategy_id} is {perf.status.value} - eligible for shadow simulation & pre-signal radar"
        norm_regime = normalize_regime_key(current_regime)
        raw_regime = str(getattr(current_regime, "value", current_regime)).strip().upper() if current_regime else "RANGE"
        regime_st = perf.regime_status.get(norm_regime) or perf.regime_status.get(raw_regime)
        if regime_st in [StrategyStatus.PAUSED, StrategyStatus.DISABLED]:
            return True, f"Strategy {strategy_id} is {regime_st.value} in {norm_regime} - eligible for shadow simulation & pre-signal radar"
        return False, f"Strategy {strategy_id} is active (not paused)"

    def record_shadow_outcome(
        self,
        strategy_id: str,
        is_win: bool,
        net_return_pct: float,
        regime: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Feature 5.1: Records the outcome of a simulated shadow paper trade for a PAUSED strategy.
        Updates Bayesian performance priors and automatically unpauses the strategy
        when rolling PF recovers above the dynamic recovery hurdle.
        """
        strat_key = strategy_id.upper().strip() if strategy_id else ""
        perf = self.strategies.get(strat_key)
        if not perf:
            return {"unpaused": False, "status": "UNKNOWN"}

        with self._lock:
            perf.shadow_sample_count += 1
            perf.shadow_resolved_count += 1
            if is_win:
                perf.shadow_wins += 1

            # Update rolling profit factor using same Bayesian smoothing
            ret_factor = max(0.1, 1.0 + (net_return_pct / 100.0)) if is_win else max(0.1, 1.0 - (abs(net_return_pct) / 100.0))
            if is_win:
                perf.rolling_50_pf = round(min(3.0, (perf.rolling_50_pf * 0.96) + (ret_factor * 0.04)), 4)
            else:
                perf.rolling_50_pf = round(max(0.4, (perf.rolling_50_pf * 0.96) - ((1.0 / ret_factor) * 0.04)), 4)

            # Update rolling net expectancy
            perf.expectancy_net_pct = round(float((perf.expectancy_net_pct * 0.95) + (net_return_pct * 0.05)), 4)
            perf.last_updated_ts = time.time()

            # Dynamic unpause recovery hurdle:
            # Scale dynamically with sample count (more samples required for faster unpausing)
            tot_n = perf.resolved_count + perf.shadow_resolved_count
            recovery_hurdle = max(1.02, 1.05 - (min(tot_n, 50) / 1000.0))

            was_paused = (perf.status == StrategyStatus.PAUSED)
            unpaused = False

            if perf.status == StrategyStatus.PAUSED and perf.rolling_50_pf >= recovery_hurdle and perf.expectancy_net_pct > 0.0:
                perf.status = StrategyStatus.ACTIVE
                unpaused = True

            # Regime-specific unpausing
            if regime:
                norm_r = normalize_regime_key(regime)
                if norm_r in perf.regime_status and perf.regime_status[norm_r] == StrategyStatus.PAUSED:
                    if is_win and perf.rolling_50_pf >= recovery_hurdle:
                        perf.regime_status.pop(norm_r, None)
                        unpaused = True

            res = {
                "unpaused": (perf.status == StrategyStatus.ACTIVE),
                "strategy_id": strat_key,
                "status": perf.status.value,
                "rolling_50_pf": perf.rolling_50_pf,
                "recovery_hurdle": round(recovery_hurdle, 4)
            }

        self.save_to_disk()
        return res

    def get_edge_multiplier(self, strategy_id: str) -> float:
        """Returns strategy performance weighting multiplier for probability adjustment."""
        perf = self.strategies.get(strategy_id)
        if not perf or perf.rolling_50_pf <= 0:
            return 1.0
        # Normalizes PF between 0.85x and 1.25x
        return max(0.85, min(1.25, perf.rolling_50_pf / 1.20))

    def seed_from_tracker_csv(self, csv_path: Optional[str] = None) -> bool:
        """
        Dynamically synchronizes historical strategy priors and regime statuses
        from the authoritative trader_signals_tracker.csv using true empirical rolling metrics.
        """
        export_dir = os.getenv("EXPORT_DIR", "./export_app_data")
        path = csv_path or os.path.join(export_dir, "trader_signals_tracker.csv")
        if not os.path.exists(path):
            return False

        try:
            import pandas as pd
            df = pd.read_csv(path)
            if df.empty or "strategy_archetype" not in df.columns or "outcome_label" not in df.columns:
                return False

            with self._lock:
                strat_groups: Dict[str, list] = {}
                for _, row in df.iterrows():
                    raw_strat = str(row.get("strategy_archetype") or "").strip()
                    if not raw_strat or raw_strat == "nan":
                        continue
                    strat_id = raw_strat.upper()
                    if strat_id not in self.strategies:
                        continue

                    outcome = str(row.get("outcome_label") or "")
                    if "BREAKEVEN" in outcome or "TIER0_BE" in outcome:
                        continue
                    elif "WON" in outcome:
                        is_win = True
                    elif "LOST" in outcome or "SL HIT" in outcome:
                        is_win = False
                    else:
                        continue

                    ret_str = str(row.get("realized_return_pct") or "").replace("+", "").replace("%", "").strip()
                    try:
                        ret_pct = float(ret_str) if ret_str and ret_str != "nan" else (1.5 if is_win else -1.0)
                    except Exception:
                        ret_pct = 1.5 if is_win else -1.0

                    regime = str(row.get("market_shield") or "RANGE")
                    if strat_id not in strat_groups:
                        strat_groups[strat_id] = []
                    strat_groups[strat_id].append({
                        "is_win": is_win,
                        "ret_pct": ret_pct,
                        "regime": regime
                    })

                for strat_id, trades in strat_groups.items():
                    perf = self.strategies[strat_id]
                    perf.sample_count = max(perf.sample_count, len(trades))
                    perf.resolved_count = len(trades)

                    # Last 50 resolved trades for rolling window
                    recent_50 = trades[-50:]
                    wins_50 = [t for t in recent_50 if t["is_win"]]
                    losses_50 = [t for t in recent_50 if not t["is_win"]]

                    gross_wins = sum(t["ret_pct"] for t in wins_50 if t["ret_pct"] > 0)
                    gross_losses = sum(abs(t["ret_pct"]) for t in losses_50 if t["ret_pct"] < 0)

                    prior_wr = 0.55
                    prior_pf = 1.25
                    prior_exp = 0.45

                    actual_wins_total = sum(1 for t in trades if t["is_win"])
                    n_total = len(trades)
                    perf.win_rate = round(float((actual_wins_total + prior_wr * 10.0) / (n_total + 10.0)), 4)

                    # Robust empirical Rolling 50 Profit Factor
                    if gross_losses > 0:
                        perf.rolling_50_pf = round(float((gross_wins + prior_pf * 5.0) / (gross_losses + 5.0)), 4)
                    elif gross_wins > 0:
                        perf.rolling_50_pf = 2.50
                    else:
                        perf.rolling_50_pf = 1.00

                    # Robust empirical Net Expectancy
                    sum_ret_50 = sum(t["ret_pct"] for t in recent_50)
                    perf.expectancy_net_pct = round(float((sum_ret_50 + prior_exp * 5.0) / (len(recent_50) + 5.0)), 4)
                    perf.last_updated_ts = time.time()

                    # Automated Kill Switch Gating: only disable with statistical confidence (>= 30 trades and severe negative expectancy < -0.35%)
                    if n_total >= 30 and perf.expectancy_net_pct < -0.35:
                        perf.status = StrategyStatus.DISABLED
                    elif n_total >= 15 and (perf.expectancy_net_pct < -0.15 or perf.rolling_50_pf < 0.80):
                        perf.status = StrategyStatus.PAUSED
                    elif perf.rolling_50_pf < 1.00:
                        perf.status = StrategyStatus.WARNING
                    else:
                        perf.status = StrategyStatus.ACTIVE

                    # Regime-specific gating: requires minimum 8 resolved trades in regime before pausing
                    regime_trades: Dict[str, list] = {}
                    for t in recent_50:
                        norm_r = normalize_regime_key(t["regime"])
                        if norm_r not in regime_trades:
                            regime_trades[norm_r] = []
                        regime_trades[norm_r].append(t)

                    for norm_r, r_trades in regime_trades.items():
                        if len(r_trades) >= 8:
                            r_wins = sum(t["ret_pct"] for t in r_trades if t["is_win"] and t["ret_pct"] > 0)
                            r_loss = sum(abs(t["ret_pct"]) for t in r_trades if not t["is_win"] and t["ret_pct"] < 0)
                            r_pf = (r_wins + prior_pf * 3.0) / max(0.01, r_loss + 3.0)
                            if r_pf < 0.85:
                                perf.regime_status[norm_r] = StrategyStatus.PAUSED
                            elif r_pf >= 1.05:
                                perf.regime_status.pop(norm_r, None)

            self.save_to_disk()
            return True
        except Exception:
            return False
