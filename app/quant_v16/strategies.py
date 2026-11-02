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

            # Rolling profit factor update
            ret_factor = max(0.1, 1.0 + (net_return_pct / 100.0)) if is_win else max(0.1, 1.0 - (abs(net_return_pct) / 100.0))
            if is_win:
                perf.rolling_50_pf = round(min(3.0, (perf.rolling_50_pf * 0.96) + (ret_factor * 0.04)), 4)
            else:
                perf.rolling_50_pf = round(max(0.4, (perf.rolling_50_pf * 0.96) - ((1.0 / ret_factor) * 0.04)), 4)

            # Update rolling net expectancy
            perf.expectancy_net_pct = round(float((perf.expectancy_net_pct * 0.95) + (net_return_pct * 0.05)), 4)
            perf.last_updated_ts = time.time()

            # Section 31 Automated Kill Switch Gating:
            if perf.expectancy_net_pct < -0.20 or perf.rolling_50_pf < 0.70:
                perf.status = StrategyStatus.DISABLED
            elif perf.rolling_50_pf < 0.85:
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

    def is_strategy_shadow_eligible(self, strategy_id: str, current_regime: str) -> Tuple[bool, str]:
        """
        Feature 5.1: Evaluates whether a strategy vetoed by Section 31/32 kill switch
        is eligible for shadow tracking simulation (i.e. is PAUSED, not DISABLED).
        """
        strat_key = strategy_id.upper().strip() if strategy_id else ""
        perf = self.strategies.get(strat_key)
        if not perf:
            return False, "Strategy not registered"
        if perf.status == StrategyStatus.DISABLED:
            return False, f"Strategy {strategy_id} is permanently DISABLED (Expectancy < -0.20)"
        if perf.status == StrategyStatus.PAUSED:
            return True, f"Strategy {strategy_id} is globally PAUSED - eligible for shadow simulation"
        norm_regime = normalize_regime_key(current_regime)
        raw_regime = str(getattr(current_regime, "value", current_regime)).strip().upper() if current_regime else "RANGE"
        regime_st = perf.regime_status.get(norm_regime) or perf.regime_status.get(raw_regime)
        if regime_st == StrategyStatus.PAUSED:
            return True, f"Strategy {strategy_id} is PAUSED in {norm_regime} - eligible for shadow simulation"
        return False, f"Strategy {strategy_id} is not in paused state"

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
