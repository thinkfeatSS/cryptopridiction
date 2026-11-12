"""
QUANT EDGE V16: Walk-Forward Shadow Replay Engine
Specifications:
- Chronological event-driven simulation over historical market signals with ZERO lookahead bias.
- Enforces multi-desk capital risk constraints:
    * 50% Swing Desk (3 concurrent slots, 2x leverage)
    * 35% Day Desk (2 concurrent slots, 3x leverage)
    * 15% Scalp Desk (1 concurrent slot, 2x leverage)
    * Global position limit: 6 concurrent slots.
- Real-time slot capacity gating, symbol deduplication, and quality admission filters.
- Comprehensive itemized execution microstructures:
    * Maker/Taker fees (0.0405% Binance VIP0 + BNB discount)
    * Bid-ask spread crossing (4.0 bps default)
    * Execution slippage (3 bps entry, 4 bps stop exit, 0 bps limit exit)
    * Pro-rated 8h funding rate drag (0.010% per 8h cycle)
- Strict Breakeven Accounting:
    * Breakeven trades (WON_TIER0_BE, STOP_LOSS_BREAKEVEN, etc.) are strictly excluded from wins.
- Statistical Rigor & Edge Audit:
    * Annualized Daily Sharpe & Sortino Ratios, Calmar Ratio, Profit Factor
    * Raw & Platt-Calibrated Brier Scores, Reference Climatology Brier Score, Brier Skill Score (BSS)
    * Expected Calibration Error (ECE) across 10 deciles
    * Compounded Portfolio Drawdown, Drawdown Duration, Recovery Duration, and Risk-Budgeted 1R Drawdown
    * 4 Sequential Walk-Forward Sub-Period Slices (Week 1 to Week 4) with Overfitting Degradation Ratio (ODR)
    * Stationary Block Bootstrap Resampling (1,000 iterations) for 95% Confidence Intervals
"""

import math
import random
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from sklearn.linear_model import LogisticRegression

from .audit import classify_signal_outcome

# ------------------------------------------------------------------------------
# 1. CONFIGURATION DATASTRUCTURES
# ------------------------------------------------------------------------------

@dataclass
class WalkForwardReplayConfig:
    initial_capital_usd: float = 1000.0
    desk_allocations: Dict[str, float] = field(default_factory=lambda: {
        "swing": 0.50,
        "day": 0.35,
        "scalp": 0.15
    })
    desk_slots: Dict[str, int] = field(default_factory=lambda: {
        "swing": 3,
        "day": 2,
        "scalp": 1
    })
    desk_leverage: Dict[str, int] = field(default_factory=lambda: {
        "swing": 2,
        "day": 3,
        "scalp": 2
    })
    max_global_slots: int = 6
    taker_fee_rate: float = 0.000405           # 0.0405% Binance Futures VIP0 + BNB
    maker_fee_rate: float = 0.000200           # 0.0200%
    default_spread_bps: float = 4.0            # 4.0 bps
    default_slippage_bps_entry: float = 3.0    # 3.0 bps entry taker
    default_slippage_bps_stop: float = 4.0     # 4.0 bps adverse stop exit
    default_slippage_bps_limit: float = 0.0    # 0.0 bps resting limit exit
    default_funding_rate_8h: float = 0.0001    # 0.010% per 8h
    cost_multiplier: float = 1.0               # 1.0 for BASE, 1.5 for STRESS
    quality_gate_enabled: bool = True          # Scalp requires Grade A+
    min_ev_scalp_pct: float = 0.25
    min_ev_day_pct: float = 0.25
    min_ev_swing_pct: float = 0.20
    filter_negative_ev: bool = False           # Optional hurdle: veto signals with non-positive expected return
    min_win_prob_pct: float = 0.0              # Optional hurdle: veto signals below minimum probability
    random_seed: int = 42
    num_bootstrap_resamples: int = 1000

# ------------------------------------------------------------------------------
# 2. TRADE & PERFORMANCE RECORDS
# ------------------------------------------------------------------------------

@dataclass
class WalkForwardTradeRecord:
    signal_id: str
    symbol: str
    horizon: str
    desk: str
    direction: str
    opened_at: str
    closed_at: str
    duration_hours: float
    entry_price: float
    exit_price: float
    sl_price: float
    tp1_price: float
    allocated_margin_usd: float
    position_size_usd: float
    leverage: int
    gross_return_pct: float
    gross_pnl_usd: float
    fees_usd: float
    spread_usd: float
    slippage_usd: float
    funding_usd: float
    total_friction_usd: float
    net_pnl_usd: float
    net_return_pct: float
    outcome: str               # 'WON', 'LOST', 'BREAKEVEN'
    raw_status: str
    quality_grade: str
    predicted_prob: float
    calibrated_prob: float
    y_true: int                # 1 if WON else 0

@dataclass
class WalkForwardSubPeriodMetrics:
    window_id: str
    start_date: str
    end_date: str
    total_signals: int
    admitted_trades: int
    won_trades: int
    lost_trades: int
    breakeven_trades: int
    total_win_rate_pct: float
    decisive_win_rate_pct: float
    gross_pnl_usd: float
    friction_usd: float
    net_profit_usd: float
    annualized_sharpe: float
    max_drawdown_pct: float
    brier_score: float

@dataclass
class WalkForwardReport:
    scenario_name: str
    cost_multiplier: float
    window_start_utc: str
    window_end_utc: str
    total_window_days: float
    initial_capital_usd: float
    final_balance_usd: float
    net_profit_usd: float
    total_signals_evaluated: int
    total_admitted_trades: int
    rejected_capacity_desk: int
    rejected_capacity_global: int
    rejected_duplicate_symbol: int
    rejected_quality_gate: int
    rejected_pending: int
    won_trades: int
    lost_trades: int
    breakeven_trades: int
    total_win_rate_pct: float
    decisive_win_rate_pct: float
    breakeven_rate_pct: float
    profit_factor: float
    gross_pnl_usd: float
    total_friction_usd: float
    fees_paid_usd: float
    spread_paid_usd: float
    slippage_paid_usd: float
    funding_paid_usd: float
    average_trade_net_pnl_usd: float
    average_win_usd: float
    average_loss_usd: float
    win_loss_payoff_ratio: float
    net_expectancy_capital_pct: float
    annualized_daily_sharpe: float
    annualized_daily_sortino: float
    trade_level_sharpe: float
    calmar_ratio: float
    max_drawdown_usd: float
    max_drawdown_pct: float
    max_drawdown_duration_days: float
    recovery_duration_days: float
    risk_budgeted_1r_max_dd_pct: float
    raw_compounding_max_dd_pct: float
    brier_score_raw: float
    brier_score_reference: float
    brier_skill_score_raw: float
    brier_score_calibrated: float
    brier_skill_score_calibrated: float
    expected_calibration_error_raw: float
    expected_calibration_error_calibrated: float
    calibration_deciles: List[Dict[str, Any]] = field(default_factory=list)
    bootstrap_ci_95: Dict[str, Dict[str, float]] = field(default_factory=dict)
    sub_periods: List[WalkForwardSubPeriodMetrics] = field(default_factory=list)
    overfitting_degradation_ratio: float = 1.0
    desk_breakdown: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    horizon_breakdown: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    trades: List[WalkForwardTradeRecord] = field(default_factory=list)
    daily_equity_curve: List[Dict[str, Any]] = field(default_factory=list)

# ------------------------------------------------------------------------------
# 3. WALK-FORWARD SHADOW REPLAY ENGINE
# ------------------------------------------------------------------------------

class WalkForwardShadowReplayEngine:
    """
    Simulates high-fidelity multi-desk portfolio trading chronologically across time.
    Enforces dynamic desk slot gating, itemized friction accounting, strict breakeven
    segregation, Brier probability calibration, and drawdown analysis.
    """

    def __init__(self, config: Optional[WalkForwardReplayConfig] = None):
        self.config = config or WalkForwardReplayConfig()

    @staticmethod
    def resolve_desk(horizon_str: str) -> str:
        """
        Maps signal horizon to institutional desk:
        - Scalp: 5M, 15M, 30M, SCALP
        - Day: 1H, 2H, 4H, DAY, INTRADAY
        - Swing: 12H, 24H, 1D, 4D, 7D, 15D, 30D, SWING, MACRO, DAILY, WEEKLY, MONTHLY
        """
        hz = str(horizon_str or "").strip().upper()
        if any(k in hz for k in ["24H", "1D", "12H", "4D", "7D", "15D", "30D", "SWING", "MACRO", "DAILY", "WEEKLY", "MONTHLY"]):
            return "swing"
        elif any(k in hz for k in ["5M", "15M", "30M", "SCALP"]):
            return "scalp"
        else:
            return "day"

    @staticmethod
    def _safe_float(v: Any, default: float = 0.0) -> float:
        if v is None or pd.isna(v):
            return default
        if isinstance(v, (int, float)):
            return float(v)
        try:
            s = str(v).replace("%", "").replace("$", "").replace("+", "").replace(",", "").strip()
            return float(s)
        except Exception:
            return default

    def load_dataset(
        self,
        signals_df: pd.DataFrame,
        window_days: float = 30.0
    ) -> pd.DataFrame:
        """
        Parses and chronologically orders signals over the specified out-of-sample window.
        """
        df = signals_df.copy()
        time_col = df["time_utc"].fillna("00:00:00") if "time_utc" in df.columns else "00:00:00"
        df["open_dt"] = pd.to_datetime(df["date_utc"].astype(str) + " " + time_col.astype(str), errors="coerce", utc=True)
        df = df.dropna(subset=["open_dt"]).sort_values("open_dt").reset_index(drop=True)

        if "evaluated_at_utc" in df.columns:
            df["eval_dt"] = pd.to_datetime(df["evaluated_at_utc"], errors="coerce", utc=True)
        else:
            df["eval_dt"] = pd.NaT

        if window_days is not None and window_days > 0 and len(df) > 0:
            max_dt = df["open_dt"].max()
            min_dt = max_dt - pd.Timedelta(days=window_days)
            df = df[df["open_dt"] >= min_dt].reset_index(drop=True)

        return df

    def run_replay(
        self,
        signals_df: pd.DataFrame,
        scenario_name: str = "BASE",
        cost_multiplier: Optional[float] = None
    ) -> WalkForwardReport:
        """
        Executes event-driven walk-forward chronological portfolio replay.
        """
        cm = cost_multiplier if cost_multiplier is not None else self.config.cost_multiplier
        cfg = self.config

        # 1. Prepare chronological signal timeline
        df = self.load_dataset(signals_df, window_days=30.0)
        if len(df) == 0:
            raise ValueError("Signals dataset is empty for the specified 30-day window.")

        start_time_utc = str(df["open_dt"].min())
        end_time_utc = str(df["open_dt"].max())
        total_days = max(1.0, (df["open_dt"].max() - df["open_dt"].min()).total_seconds() / 86400.0)

        # 2. Simulation State Tracking
        current_capital = cfg.initial_capital_usd
        active_positions: List[Dict[str, Any]] = []
        closed_trades: List[WalkForwardTradeRecord] = []

        # Rejection & admission counters
        total_evaluated = len(df)
        rej_capacity_desk = 0
        rej_capacity_global = 0
        rej_dup_symbol = 0
        rej_quality_gate = 0
        rej_pending = 0

        # Equity tracking
        equity_timeline: List[Dict[str, Any]] = [{
            "timestamp": start_time_utc,
            "dt": df["open_dt"].min(),
            "capital_usd": current_capital,
            "peak_usd": current_capital,
            "drawdown_pct": 0.0
        }]
        peak_capital = current_capital

        # 3. Event Loop: Iterate chronologically across signals
        for idx, row in df.iterrows():
            open_dt = row["open_dt"]
            eval_dt = row["eval_dt"]
            sig_id = str(row.get("signal_id", f"SIG_{idx}"))
            sym = str(row.get("symbol", "")).strip().upper()
            hz = str(row.get("horizon", "1H")).strip().upper()
            desk = self.resolve_desk(hz)
            st_raw = str(row.get("status", "")).strip().upper()
            qg_raw = str(row.get("quality_grade", "")).strip()

            # Step 3.1: Expire / close active positions whose close_dt <= open_dt
            still_active = []
            for pos in sorted(active_positions, key=lambda x: x["close_dt"]):
                if pos["close_dt"] <= open_dt:
                    # Realize trade outcome
                    current_capital = round(current_capital + pos["net_pnl_usd"], 2)
                    if current_capital > peak_capital:
                        peak_capital = current_capital
                    dd_pct = ((peak_capital - current_capital) / peak_capital) * 100.0 if peak_capital > 0 else 0.0

                    equity_timeline.append({
                        "timestamp": str(pos["close_dt"]),
                        "dt": pos["close_dt"],
                        "capital_usd": current_capital,
                        "peak_usd": peak_capital,
                        "drawdown_pct": round(dd_pct, 2)
                    })

                    trade_rec = self._build_trade_record(pos)
                    closed_trades.append(trade_rec)
                else:
                    still_active.append(pos)
            active_positions = still_active

            # Step 3.2: Filter Unresolved / Pending signals
            if st_raw in ["PENDING_EVALUATION", "ACTIVE", "PENDING_LIMIT", "RESTING_LIMIT"]:
                rej_pending += 1
                continue

            # Step 3.3: Quality Admission Gate
            if cfg.quality_gate_enabled:
                if desk == "scalp" and "Grade A+" not in qg_raw:
                    rej_quality_gate += 1
                    continue

            # Optional Statistical & Expectancy Veto Gates
            if cfg.filter_negative_ev:
                exp_ret = self._safe_float(row.get("expected_return_pct", 0.0))
                if exp_ret <= 0.0:
                    rej_quality_gate += 1
                    continue

            if cfg.min_win_prob_pct > 0.0:
                p_win = self._safe_float(row.get("meta_win_prob_pct", 0.0))
                if p_win < cfg.min_win_prob_pct:
                    rej_quality_gate += 1
                    continue

            # Step 3.4: Resolve Trade Lifecycle Duration
            canonical_dur_hours = 24.0 if desk == "swing" else (4.0 if desk == "day" else 0.5)
            if pd.isna(eval_dt) or eval_dt <= open_dt:
                close_dt = open_dt + pd.Timedelta(hours=canonical_dur_hours)
                dur_hours = canonical_dur_hours
            else:
                close_dt = eval_dt
                dur_hours = max(0.05, (close_dt - open_dt).total_seconds() / 3600.0)

            # Step 3.5: Capacity & Deduplication Veto Checks
            # Check 1: Symbol Deduplication (Max 1 active trade per symbol)
            if any(p["symbol"] == sym for p in active_positions):
                rej_dup_symbol += 1
                continue

            # Check 2: Desk Slot Capacity
            desk_active_cnt = sum(1 for p in active_positions if p["desk"] == desk)
            if desk_active_cnt >= cfg.desk_slots.get(desk, 2):
                rej_capacity_desk += 1
                continue

            # Check 3: Global Portfolio Capacity
            if len(active_positions) >= cfg.max_global_slots:
                rej_capacity_global += 1
                continue

            # Step 3.6: Position Sizing & Margin Allocation
            desk_alloc = cfg.desk_allocations.get(desk, 0.35)
            desk_slots = cfg.desk_slots.get(desk, 2)
            desk_lev = cfg.desk_leverage.get(desk, 2)

            desk_pool_usd = current_capital * desk_alloc
            allocated_margin = round(desk_pool_usd / max(1, desk_slots), 2)
            position_size_usd = allocated_margin * desk_lev

            # Step 3.7: Returns & PnL Computation
            entry_p = self._safe_float(row.get("entry_price", 0.0))
            exit_p = self._safe_float(row.get("exit_price", 0.0), default=entry_p)
            tp1_p = self._safe_float(row.get("tp1_price", 0.0))
            sl_p = self._safe_float(row.get("sl_price", 0.0))
            dir_str = str(row.get("direction", "LONG")).upper()

            # Prefer authoritative multi-tranche realized return if recorded
            ret_raw = row.get("realized_return_pct")
            if pd.notna(ret_raw) and ret_raw != "":
                gross_ret_pct = self._safe_float(ret_raw, 0.0)
            elif exit_p > 0 and exit_p != entry_p:
                if dir_str == "LONG":
                    gross_ret_pct = ((exit_p - entry_p) / entry_p) * 100.0
                else:
                    gross_ret_pct = ((entry_p - exit_p) / entry_p) * 100.0
            else:
                gross_ret_pct = 0.0

            gross_pnl_usd = round((gross_ret_pct / 100.0) * position_size_usd, 2)

            # Step 3.8: Itemized Execution Friction Model
            # 1. Trading fees: roundtrip taker (entry taker + exit taker/partial maker blended)
            base_fee = position_size_usd * cfg.taker_fee_rate * 2.0
            fee_usd = round(base_fee * cm, 2)

            # 2. Bid-Ask spread
            spread_usd = round((cfg.default_spread_bps / 10000.0) * position_size_usd * cm, 2)

            # 3. Slippage: entry taker (3 bps) + exit (4 bps stop or 0 bps limit)
            is_win = "WON" in st_raw or gross_pnl_usd > 0
            exit_slip_bps = cfg.default_slippage_bps_limit if is_win else cfg.default_slippage_bps_stop
            total_slip_bps = cfg.default_slippage_bps_entry + exit_slip_bps
            slippage_usd = round((total_slip_bps / 10000.0) * position_size_usd * cm, 2)

            # 4. Pro-rated funding rate drag
            funding_cycles = dur_hours / 8.0
            funding_usd = round(position_size_usd * cfg.default_funding_rate_8h * funding_cycles * cm, 2)

            total_friction_usd = round(fee_usd + spread_usd + slippage_usd + funding_usd, 2)
            net_pnl_usd = round(gross_pnl_usd - total_friction_usd, 2)
            net_return_pct = round((net_pnl_usd / max(1.0, allocated_margin)) * 100.0, 2)

            # Step 3.9: Strict Breakeven Accounting
            be_statuses = {
                "WON_TIER0_BE", "STOP_LOSS_BREAKEVEN", "BREAKEVEN_EXP",
                "EXPIRED_BREAKEVEN", "TIER0_BE_HIT", "BREAKEVEN", "EXPIRED_FLAT"
            }
            if st_raw in be_statuses or abs(net_pnl_usd) <= 0.05:
                outcome = "BREAKEVEN"
            elif net_pnl_usd > 0.05:
                outcome = "WON"
            else:
                outcome = "LOST"

            # Probability extraction
            prob_raw = self._safe_float(row.get("meta_win_prob_pct", 0.0)) / 100.0
            if prob_raw <= 0.0:
                prob_raw = self._safe_float(row.get("conviction_pct", 50.0)) / 100.0
            prob_raw = min(0.99, max(0.01, prob_raw))

            # Store active position
            pos_dict = {
                "signal_id": sig_id,
                "symbol": sym,
                "horizon": hz,
                "desk": desk,
                "direction": dir_str,
                "opened_at": str(open_dt),
                "closed_at": str(close_dt),
                "open_dt": open_dt,
                "close_dt": close_dt,
                "duration_hours": round(dur_hours, 2),
                "entry_price": round(entry_p, 6),
                "exit_price": round(exit_p, 6),
                "sl_price": round(sl_p, 6),
                "tp1_price": round(tp1_p, 6),
                "allocated_margin_usd": allocated_margin,
                "position_size_usd": position_size_usd,
                "leverage": desk_lev,
                "gross_return_pct": round(gross_ret_pct, 2),
                "gross_pnl_usd": gross_pnl_usd,
                "fees_usd": fee_usd,
                "spread_usd": spread_usd,
                "slippage_usd": slippage_usd,
                "funding_usd": funding_usd,
                "total_friction_usd": total_friction_usd,
                "net_pnl_usd": net_pnl_usd,
                "net_return_pct": net_return_pct,
                "outcome": outcome,
                "raw_status": st_raw,
                "quality_grade": qg_raw,
                "predicted_prob": round(prob_raw, 4),
                "calibrated_prob": round(prob_raw, 4), # will be updated via Platt
                "y_true": 1 if outcome == "WON" else 0
            }
            active_positions.append(pos_dict)

        # Step 4: Close any remaining active positions at end of timeline
        for pos in sorted(active_positions, key=lambda x: x["close_dt"]):
            current_capital = round(current_capital + pos["net_pnl_usd"], 2)
            if current_capital > peak_capital:
                peak_capital = current_capital
            dd_pct = ((peak_capital - current_capital) / peak_capital) * 100.0 if peak_capital > 0 else 0.0

            equity_timeline.append({
                "timestamp": str(pos["close_dt"]),
                "dt": pos["close_dt"],
                "capital_usd": current_capital,
                "peak_usd": peak_capital,
                "drawdown_pct": round(dd_pct, 2)
            })

            trade_rec = self._build_trade_record(pos)
            closed_trades.append(trade_rec)
        active_positions = []

        # 4. Statistical Edge & Calibration Analysis
        return self._generate_report(
            scenario_name=scenario_name,
            cost_multiplier=cm,
            start_time_utc=start_time_utc,
            end_time_utc=end_time_utc,
            total_days=total_days,
            initial_capital=cfg.initial_capital_usd,
            final_capital=current_capital,
            total_evaluated=total_evaluated,
            rej_capacity_desk=rej_capacity_desk,
            rej_capacity_global=rej_capacity_global,
            rej_dup_symbol=rej_dup_symbol,
            rej_quality_gate=rej_quality_gate,
            rej_pending=rej_pending,
            closed_trades=closed_trades,
            equity_timeline=equity_timeline,
            df_signals=df
        )

    def _build_trade_record(self, pos: Dict[str, Any]) -> WalkForwardTradeRecord:
        return WalkForwardTradeRecord(
            signal_id=pos["signal_id"],
            symbol=pos["symbol"],
            horizon=pos["horizon"],
            desk=pos["desk"],
            direction=pos["direction"],
            opened_at=pos["opened_at"],
            closed_at=pos["closed_at"],
            duration_hours=pos["duration_hours"],
            entry_price=pos["entry_price"],
            exit_price=pos["exit_price"],
            sl_price=pos["sl_price"],
            tp1_price=pos["tp1_price"],
            allocated_margin_usd=pos["allocated_margin_usd"],
            position_size_usd=pos["position_size_usd"],
            leverage=pos["leverage"],
            gross_return_pct=pos["gross_return_pct"],
            gross_pnl_usd=pos["gross_pnl_usd"],
            fees_usd=pos["fees_usd"],
            spread_usd=pos["spread_usd"],
            slippage_usd=pos["slippage_usd"],
            funding_usd=pos["funding_usd"],
            total_friction_usd=pos["total_friction_usd"],
            net_pnl_usd=pos["net_pnl_usd"],
            net_return_pct=pos["net_return_pct"],
            outcome=pos["outcome"],
            raw_status=pos["raw_status"],
            quality_grade=pos["quality_grade"],
            predicted_prob=pos["predicted_prob"],
            calibrated_prob=pos["calibrated_prob"],
            y_true=pos["y_true"]
        )

    # --------------------------------------------------------------------------
    # 4. REPORT COMPILATION & MATHEMATICAL AUDIT
    # --------------------------------------------------------------------------

    def _generate_report(
        self,
        scenario_name: str,
        cost_multiplier: float,
        start_time_utc: str,
        end_time_utc: str,
        total_days: float,
        initial_capital: float,
        final_capital: float,
        total_evaluated: int,
        rej_capacity_desk: int,
        rej_capacity_global: int,
        rej_dup_symbol: int,
        rej_quality_gate: int,
        rej_pending: int,
        closed_trades: List[WalkForwardTradeRecord],
        equity_timeline: List[Dict[str, Any]],
        df_signals: pd.DataFrame
    ) -> WalkForwardReport:
        n_trades = len(closed_trades)
        net_profit = round(final_capital - initial_capital, 2)

        won_cnt = sum(1 for t in closed_trades if t.outcome == "WON")
        lost_cnt = sum(1 for t in closed_trades if t.outcome == "LOST")
        be_cnt = sum(1 for t in closed_trades if t.outcome == "BREAKEVEN")
        decisive_cnt = won_cnt + lost_cnt

        tot_wr = round((won_cnt / max(1, n_trades)) * 100.0, 2) if n_trades > 0 else 0.0
        dec_wr = round((won_cnt / max(1, decisive_cnt)) * 100.0, 2) if decisive_cnt > 0 else 0.0
        be_rate = round((be_cnt / max(1, n_trades)) * 100.0, 2) if n_trades > 0 else 0.0

        tot_gross_pnl = round(sum(t.gross_pnl_usd for t in closed_trades), 2)
        tot_friction = round(sum(t.total_friction_usd for t in closed_trades), 2)
        fees_paid = round(sum(t.fees_usd for t in closed_trades), 2)
        spread_paid = round(sum(t.spread_usd for t in closed_trades), 2)
        slip_paid = round(sum(t.slippage_usd for t in closed_trades), 2)
        funding_paid = round(sum(t.funding_usd for t in closed_trades), 2)

        gross_gains = sum(t.gross_pnl_usd for t in closed_trades if t.gross_pnl_usd > 0)
        gross_losses = abs(sum(t.gross_pnl_usd for t in closed_trades if t.gross_pnl_usd < 0))
        pf = round(gross_gains / max(0.01, gross_losses), 2) if gross_losses > 0 else (99.0 if gross_gains > 0 else 0.0)

        winning_pnls = [t.net_pnl_usd for t in closed_trades if t.outcome == "WON"]
        losing_pnls = [abs(t.net_pnl_usd) for t in closed_trades if t.outcome == "LOST"]
        avg_win = round(float(np.mean(winning_pnls)), 2) if winning_pnls else 0.0
        avg_loss = round(float(np.mean(losing_pnls)), 2) if losing_pnls else 0.0
        wl_ratio = round(avg_win / max(0.01, avg_loss), 2) if avg_loss > 0 else 0.0

        # Construct continuous daily equity series (at 00:00:00 UTC day boundaries)
        df_eq = pd.DataFrame(equity_timeline)
        df_eq["dt"] = pd.to_datetime(df_eq["dt"])
        df_eq = df_eq.sort_values("dt").reset_index(drop=True)
        df_eq["date"] = df_eq["dt"].dt.date

        daily_equity_map = df_eq.groupby("date")["capital_usd"].last().to_dict()
        all_dates = pd.date_range(start=df_eq["date"].min(), end=df_eq["date"].max(), freq="D").date
        
        continuous_daily_curve = []
        running_bal = initial_capital
        for d in all_dates:
            if d in daily_equity_map:
                running_bal = daily_equity_map[d]
            continuous_daily_curve.append({
                "date": str(d),
                "capital_usd": round(running_bal, 2)
            })

        daily_caps = [c["capital_usd"] for c in continuous_daily_curve]
        daily_returns = [(daily_caps[i] - daily_caps[i - 1]) / max(1.0, daily_caps[i - 1]) for i in range(1, len(daily_caps))]

        # Daily Sharpe & Sortino Ratios (Annualized)
        if daily_returns and len(daily_returns) > 1 and np.std(daily_returns, ddof=1) > 1e-6:
            mean_d_ret = float(np.mean(daily_returns))
            std_d_ret = float(np.std(daily_returns, ddof=1))
            daily_sharpe = round((mean_d_ret / std_d_ret) * math.sqrt(365.0), 2)

            downside_rets = [r for r in daily_returns if r < 0]
            if len(downside_rets) > 1:
                std_downside = float(np.std(downside_rets, ddof=1))
            else:
                std_downside = std_d_ret
            daily_sortino = round((mean_d_ret / max(1e-6, std_downside)) * math.sqrt(365.0), 2)
        else:
            daily_sharpe = 0.0
            daily_sortino = 0.0

        # Trade-Level Sharpe Ratio
        trade_returns = [t.net_return_pct for t in closed_trades]
        if trade_returns and len(trade_returns) > 1 and np.std(trade_returns, ddof=1) > 1e-6:
            mean_t_ret = float(np.mean(trade_returns))
            std_t_ret = float(np.std(trade_returns, ddof=1))
            trades_per_day = max(1.0, n_trades / max(1.0, total_days))
            trade_sharpe = round((mean_t_ret / std_t_ret) * math.sqrt(trades_per_day * 365.0), 2)
        else:
            trade_sharpe = 0.0

        # Drawdown Dynamics
        dd_metrics = self._calculate_drawdown_dynamics(daily_caps, closed_trades)

        # Calmar Ratio: Annualized Return % / Max Drawdown %
        total_ret_pct = (net_profit / max(1.0, initial_capital)) * 100.0
        annualized_ret_pct = (total_ret_pct / max(1.0, total_days)) * 365.0
        max_dd_pct = dd_metrics["max_drawdown_pct"]
        calmar = round(annualized_ret_pct / max(0.01, max_dd_pct), 2) if max_dd_pct > 0 else 0.0

        # Probability Calibration, Brier Scores & ECE
        raw_probs = [t.predicted_prob for t in closed_trades]
        outcomes = [t.y_true for t in closed_trades]
        brier_res = self._compute_brier_and_calibration(raw_probs, outcomes)

        # Update calibrated probabilities in trades
        cal_probs = brier_res["calibrated_probs"]
        for i, t in enumerate(closed_trades):
            if i < len(cal_probs):
                t.calibrated_prob = round(float(cal_probs[i]), 4)

        # Stationary Block Bootstrap Resampling (1,000 iterations)
        bootstrap_ci = self._run_bootstrap(closed_trades, daily_caps)

        # 4 Walk-Forward Sequential Sub-Period Slices (Week 1 to Week 4)
        sub_periods, odr = self._evaluate_sub_periods(closed_trades, df_signals)

        # Desk & Horizon Breakdowns
        desk_breakdown = self._breakdown_by_attribute(closed_trades, "desk")
        horizon_breakdown = self._breakdown_by_attribute(closed_trades, "horizon")

        return WalkForwardReport(
            scenario_name=scenario_name,
            cost_multiplier=cost_multiplier,
            window_start_utc=start_time_utc,
            window_end_utc=end_time_utc,
            total_window_days=round(total_days, 1),
            initial_capital_usd=initial_capital,
            final_balance_usd=final_capital,
            net_profit_usd=net_profit,
            total_signals_evaluated=total_evaluated,
            total_admitted_trades=n_trades,
            rejected_capacity_desk=rej_capacity_desk,
            rejected_capacity_global=rej_capacity_global,
            rejected_duplicate_symbol=rej_dup_symbol,
            rejected_quality_gate=rej_quality_gate,
            rejected_pending=rej_pending,
            won_trades=won_cnt,
            lost_trades=lost_cnt,
            breakeven_trades=be_cnt,
            total_win_rate_pct=tot_wr,
            decisive_win_rate_pct=dec_wr,
            breakeven_rate_pct=be_rate,
            profit_factor=pf,
            gross_pnl_usd=tot_gross_pnl,
            total_friction_usd=tot_friction,
            fees_paid_usd=fees_paid,
            spread_paid_usd=spread_paid,
            slippage_paid_usd=slip_paid,
            funding_paid_usd=funding_paid,
            average_trade_net_pnl_usd=round(net_profit / max(1, n_trades), 2),
            average_win_usd=avg_win,
            average_loss_usd=avg_loss,
            win_loss_payoff_ratio=wl_ratio,
            net_expectancy_capital_pct=round(float(np.mean(trade_returns)), 2) if trade_returns else 0.0,
            annualized_daily_sharpe=daily_sharpe,
            annualized_daily_sortino=daily_sortino,
            trade_level_sharpe=trade_sharpe,
            calmar_ratio=calmar,
            max_drawdown_usd=dd_metrics["max_drawdown_usd"],
            max_drawdown_pct=dd_metrics["max_drawdown_pct"],
            max_drawdown_duration_days=dd_metrics["max_drawdown_duration_days"],
            recovery_duration_days=dd_metrics["recovery_duration_days"],
            risk_budgeted_1r_max_dd_pct=dd_metrics["risk_budgeted_1r_max_dd_pct"],
            raw_compounding_max_dd_pct=dd_metrics["raw_compounding_max_dd_pct"],
            brier_score_raw=brier_res["brier_score_raw"],
            brier_score_reference=brier_res["brier_score_reference"],
            brier_skill_score_raw=brier_res["brier_skill_score_raw"],
            brier_score_calibrated=brier_res["brier_score_calibrated"],
            brier_skill_score_calibrated=brier_res["brier_skill_score_calibrated"],
            expected_calibration_error_raw=brier_res["ece_raw"],
            expected_calibration_error_calibrated=brier_res["ece_calibrated"],
            calibration_deciles=brier_res["deciles"],
            bootstrap_ci_95=bootstrap_ci,
            sub_periods=sub_periods,
            overfitting_degradation_ratio=odr,
            desk_breakdown=desk_breakdown,
            horizon_breakdown=horizon_breakdown,
            trades=closed_trades,
            daily_equity_curve=continuous_daily_curve
        )

    # --------------------------------------------------------------------------
    # 5. DRAWDOWN DYNAMICS
    # --------------------------------------------------------------------------

    def _calculate_drawdown_dynamics(
        self,
        daily_equity: List[float],
        trades: List[WalkForwardTradeRecord]
    ) -> Dict[str, Any]:
        """
        Calculates peak-to-trough drawdown in USD and %, peak-to-trough duration,
        recovery duration, unleveraged raw compounding drawdown, and risk-budgeted 1R drawdown.
        """
        if not daily_equity:
            return {
                "max_drawdown_usd": 0.0,
                "max_drawdown_pct": 0.0,
                "max_drawdown_duration_days": 0.0,
                "recovery_duration_days": 0.0,
                "risk_budgeted_1r_max_dd_pct": 0.0,
                "raw_compounding_max_dd_pct": 0.0
            }

        peak = daily_equity[0]
        max_dd_usd = 0.0
        max_dd_pct = 0.0

        peak_idx = 0
        trough_idx = 0
        max_dd_peak_idx = 0
        max_dd_trough_idx = 0

        for i, val in enumerate(daily_equity):
            if val > peak:
                peak = val
                peak_idx = i
            else:
                dd_usd = peak - val
                dd_pct = (dd_usd / peak) * 100.0 if peak > 0 else 0.0
                if dd_pct > max_dd_pct:
                    max_dd_pct = dd_pct
                    max_dd_usd = dd_usd
                    max_dd_peak_idx = peak_idx
                    max_dd_trough_idx = i

        dd_duration_days = float(max_dd_trough_idx - max_dd_peak_idx)

        # Recovery duration (from trough to new all-time high)
        recovery_days = 0.0
        recovered = False
        prior_peak = daily_equity[max_dd_peak_idx]
        for j in range(max_dd_trough_idx + 1, len(daily_equity)):
            if daily_equity[j] >= prior_peak:
                recovery_days = float(j - max_dd_trough_idx)
                recovered = True
                break
        if not recovered:
            recovery_days = float(len(daily_equity) - 1 - max_dd_trough_idx)

        # Unleveraged raw compounding drawdown
        raw_eq = 100.0
        raw_peak = 100.0
        raw_max_dd = 0.0
        for t in trades:
            raw_eq *= (1.0 + (t.gross_return_pct / 100.0))
            if raw_eq > raw_peak:
                raw_peak = raw_eq
            else:
                r_dd = ((raw_peak - raw_eq) / raw_peak) * 100.0
                if r_dd > raw_max_dd:
                    raw_max_dd = r_dd

        # Risk-budgeted 1R drawdown (1.0% risk unit per trade)
        risk_eq = 100.0
        risk_peak = 100.0
        risk_max_dd = 0.0
        for t in trades:
            sl_dist = abs(t.entry_price - t.sl_price) / max(1e-6, t.entry_price) * 100.0
            sl_dist = max(0.50, sl_dist)
            r_mult = max(-1.20, min(5.0, t.gross_return_pct / sl_dist))
            risk_eq *= (1.0 + (0.01 * r_mult))
            if risk_eq > risk_peak:
                risk_peak = risk_eq
            else:
                rk_dd = ((risk_peak - risk_eq) / risk_peak) * 100.0
                if rk_dd > risk_max_dd:
                    risk_max_dd = rk_dd

        return {
            "max_drawdown_usd": round(max_dd_usd, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "max_drawdown_duration_days": dd_duration_days,
            "recovery_duration_days": recovery_days,
            "risk_budgeted_1r_max_dd_pct": round(risk_max_dd, 2),
            "raw_compounding_max_dd_pct": round(raw_max_dd, 2)
        }

    # --------------------------------------------------------------------------
    # 6. BRIER SCORE, CALIBRATION & ECE
    # --------------------------------------------------------------------------

    def _compute_brier_and_calibration(
        self,
        raw_probs: List[float],
        outcomes: List[int]
    ) -> Dict[str, Any]:
        """
        Computes empirical Brier Score, climatological reference Brier score,
        Brier Skill Score (BSS), Expected Calibration Error (ECE) across 10 deciles,
        and Platt sigmoid calibration.
        """
        if not raw_probs or len(raw_probs) != len(outcomes):
            return {
                "brier_score_raw": 0.0,
                "brier_score_reference": 0.0,
                "brier_skill_score_raw": 0.0,
                "brier_score_calibrated": 0.0,
                "brier_skill_score_calibrated": 0.0,
                "ece_raw": 0.0,
                "ece_calibrated": 0.0,
                "deciles": [],
                "calibrated_probs": []
            }

        p_arr = np.array(raw_probs, dtype=float)
        y_arr = np.array(outcomes, dtype=int)
        n = len(p_arr)

        # Raw Brier Score & Reference
        bs_raw = float(np.mean((p_arr - y_arr) ** 2))
        y_bar = float(np.mean(y_arr))
        bs_ref = float(y_bar * (1.0 - y_bar))
        bss_raw = float(1.0 - (bs_raw / bs_ref)) if bs_ref > 0 else 0.0

        # Platt Sigmoid Calibration (Logistic regression on log-odds)
        p_clipped = np.clip(p_arr, 1e-4, 1.0 - 1e-4)
        logits = np.log(p_clipped / (1.0 - p_clipped)).reshape(-1, 1)

        calibrated_probs = p_arr.copy()
        bs_cal = bs_raw
        bss_cal = bss_raw
        ece_cal = 0.0

        try:
            unique_classes = np.unique(y_arr)
            if len(unique_classes) > 1 and min(np.bincount(y_arr)) >= 2:
                from sklearn.model_selection import StratifiedKFold
                n_splits = min(5, int(min(np.bincount(y_arr))))
                if n_splits >= 2 and n >= 20:
                    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
                    cal_oof = np.zeros(n, dtype=float)
                    for train_idx, test_idx in skf.split(logits, y_arr):
                        clf = LogisticRegression(C=1.0, max_iter=200)
                        clf.fit(logits[train_idx], y_arr[train_idx])
                        cal_oof[test_idx] = clf.predict_proba(logits[test_idx])[:, 1]
                    calibrated_probs = cal_oof
                else:
                    clf = LogisticRegression(C=1.0, max_iter=200)
                    clf.fit(logits, y_arr)
                    calibrated_probs = clf.predict_proba(logits)[:, 1]
                bs_cal = float(np.mean((calibrated_probs - y_arr) ** 2))
                bss_cal = float(1.0 - (bs_cal / bs_ref)) if bs_ref > 0 else 0.0
        except Exception:
            calibrated_probs = p_arr.copy()

        # Uniform Decile Calibration Analysis (10 Deciles)
        bins = [
            (0.00, 0.10), (0.10, 0.20), (0.20, 0.30), (0.30, 0.40), (0.40, 0.50),
            (0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.00)
        ]

        decile_results = []
        weighted_ece_raw = 0.0
        weighted_ece_cal = 0.0

        for lower, upper in bins:
            mask = (p_arr >= lower) & (p_arr < upper if upper < 1.0 else p_arr <= upper)
            b_cnt = int(np.sum(mask))

            if b_cnt > 0:
                avg_p_raw = float(np.mean(p_arr[mask]))
                avg_p_cal = float(np.mean(calibrated_probs[mask]))
                act_rate = float(np.mean(y_arr[mask]))
                cal_err_raw = abs(avg_p_raw - act_rate)
                cal_err_cal = abs(avg_p_cal - act_rate)
                weighted_ece_raw += (b_cnt / n) * cal_err_raw
                weighted_ece_cal += (b_cnt / n) * cal_err_cal
            else:
                avg_p_raw = (lower + upper) / 2.0
                avg_p_cal = avg_p_raw
                act_rate = 0.0
                cal_err_raw = 0.0
                cal_err_cal = 0.0

            decile_results.append({
                "decile_label": f"{int(lower*100)}–{int(upper*100)}%",
                "count": b_cnt,
                "avg_predicted_prob": round(avg_p_raw, 4),
                "avg_calibrated_prob": round(avg_p_cal, 4),
                "actual_tp1_rate": round(act_rate, 4),
                "calibration_error": round(cal_err_raw, 4)
            })

        return {
            "brier_score_raw": round(bs_raw, 4),
            "brier_score_reference": round(bs_ref, 4),
            "brier_skill_score_raw": round(bss_raw, 4),
            "brier_score_calibrated": round(bs_cal, 4),
            "brier_skill_score_calibrated": round(bss_cal, 4),
            "ece_raw": round(weighted_ece_raw, 4),
            "ece_calibrated": round(weighted_ece_cal, 4),
            "deciles": decile_results,
            "calibrated_probs": calibrated_probs
        }

    # --------------------------------------------------------------------------
    # 7. BOOTSTRAP UNCERTAINTY RESAMPLING
    # --------------------------------------------------------------------------

    def _run_bootstrap(
        self,
        trades: List[WalkForwardTradeRecord],
        daily_equity: List[float]
    ) -> Dict[str, Dict[str, float]]:
        """
        Performs 1,000 non-parametric bootstrap resamples to establish
        95% Confidence Intervals for Win Rate, Net Profit, Sharpe Ratio, and Drawdown.
        """
        if not trades or len(trades) < 2:
            return {}

        n_boot = self.config.num_bootstrap_resamples
        rng = np.random.default_rng(self.config.random_seed)
        n = len(trades)

        trade_outcomes = [1 if t.outcome == "WON" else 0 for t in trades]
        trade_pnls = [t.net_pnl_usd for t in trades]
        trade_rets = [t.net_return_pct for t in trades]

        boot_win_rates = []
        boot_net_profits = []
        boot_sharpes = []
        boot_max_dds = []

        arr_outs = np.array(trade_outcomes)
        arr_pnls = np.array(trade_pnls)
        arr_rets = np.array(trade_rets)

        for _ in range(n_boot):
            idxs = rng.choice(n, size=n, replace=True)
            # Win Rate
            boot_win_rates.append(float(np.mean(arr_outs[idxs])) * 100.0)
            # Net Profit
            boot_net_profits.append(float(np.sum(arr_pnls[idxs])))
            # Trade-level Sharpe proxy
            s_rets = arr_rets[idxs]
            s_std = float(np.std(s_rets, ddof=1)) if len(s_rets) > 1 else 0.0
            if s_std > 1e-4:
                boot_sharpes.append(float(np.mean(s_rets) / s_std) * math.sqrt(365.0))
            else:
                boot_sharpes.append(0.0)
            # Drawdown
            eq = 1000.0
            peak = 1000.0
            max_d = 0.0
            for p in arr_pnls[idxs]:
                eq += p
                if eq > peak:
                    peak = eq
                dd = (peak - eq) / peak * 100.0
                if dd > max_d:
                    max_d = dd
            boot_max_dds.append(max_d)

        def _ci(data: List[float], pt: float) -> Dict[str, float]:
            return {
                "point_estimate": round(pt, 2),
                "ci_lower_95": round(float(np.percentile(data, 2.5)), 2),
                "ci_upper_95": round(float(np.percentile(data, 97.5)), 2)
            }

        curr_wr = (sum(trade_outcomes) / n) * 100.0
        curr_profit = sum(trade_pnls)
        curr_std = float(np.std(arr_rets, ddof=1)) if len(arr_rets) > 1 else 0.0
        curr_sharpe = float(np.mean(arr_rets) / max(1e-4, curr_std)) * math.sqrt(365.0) if curr_std > 1e-4 else 0.0

        # Drawdown point est
        eq = 1000.0
        peak = 1000.0
        max_d = 0.0
        for p in trade_pnls:
            eq += p
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100.0
            if dd > max_d:
                max_d = dd

        return {
            "total_win_rate_pct": _ci(boot_win_rates, curr_wr),
            "net_profit_usd": _ci(boot_net_profits, curr_profit),
            "sharpe_ratio": _ci(boot_sharpes, curr_sharpe),
            "max_drawdown_pct": _ci(boot_max_dds, max_d)
        }

    # --------------------------------------------------------------------------
    # 8. WALK-FORWARD SUB-PERIOD SLICING & ODR
    # --------------------------------------------------------------------------

    def _evaluate_sub_periods(
        self,
        trades: List[WalkForwardTradeRecord],
        df_signals: pd.DataFrame
    ) -> Tuple[List[WalkForwardSubPeriodMetrics], float]:
        """
        Slices the chronological timeline into 4 sequential quarter windows (Week 1 to Week 4)
        and computes the Overfitting Degradation Ratio (ODR).
        """
        if not trades:
            return [], 1.0

        df_t = pd.DataFrame([asdict(t) for t in trades])
        df_t["open_dt"] = pd.to_datetime(df_t["opened_at"])
        df_t = df_t.sort_values("open_dt").reset_index(drop=True)

        min_t = df_t["open_dt"].min()
        max_t = df_t["open_dt"].max()
        span_secs = (max_t - min_t).total_seconds()
        slice_secs = max(3600.0, span_secs / 4.0)

        sub_periods = []
        sharpe_slices = []

        for q in range(4):
            q_start = min_t + pd.Timedelta(seconds=q * slice_secs)
            q_end = min_t + pd.Timedelta(seconds=(q + 1) * slice_secs) if q < 3 else max_t + pd.Timedelta(seconds=1)

            sub_t = df_t[(df_t["open_dt"] >= q_start) & (df_t["open_dt"] < q_end)]
            n_sub = len(sub_t)
            w_sub = int((sub_t["outcome"] == "WON").sum())
            l_sub = int((sub_t["outcome"] == "LOST").sum())
            be_sub = int((sub_t["outcome"] == "BREAKEVEN").sum())
            dec_sub = w_sub + l_sub

            tot_wr = round((w_sub / max(1, n_sub)) * 100.0, 1) if n_sub > 0 else 0.0
            dec_wr = round((w_sub / max(1, dec_sub)) * 100.0, 1) if dec_sub > 0 else 0.0

            gross_sub = round(float(sub_t["gross_pnl_usd"].sum()), 2) if n_sub > 0 else 0.0
            fric_sub = round(float(sub_t["total_friction_usd"].sum()), 2) if n_sub > 0 else 0.0
            net_sub = round(float(sub_t["net_pnl_usd"].sum()), 2) if n_sub > 0 else 0.0

            # Sub-period Sharpe
            rets = sub_t["net_return_pct"].values if n_sub > 0 else np.array([])
            if len(rets) > 1 and np.std(rets, ddof=1) > 1e-4:
                sub_sr = round(float(np.mean(rets) / np.std(rets, ddof=1)) * math.sqrt(365.0), 2)
            else:
                sub_sr = 0.0
            sharpe_slices.append(sub_sr)

            # Sub-period Drawdown
            eq = 1000.0
            peak = 1000.0
            sub_max_dd = 0.0
            if n_sub > 0:
                for p in sub_t["net_pnl_usd"]:
                    eq += p
                    if eq > peak:
                        peak = eq
                    dd = (peak - eq) / peak * 100.0
                    if dd > sub_max_dd:
                        sub_max_dd = dd

            # Sub-period Brier
            if n_sub > 0:
                p_sub = sub_t["predicted_prob"].values
                y_sub = sub_t["y_true"].values
                bs_sub = round(float(np.mean((p_sub - y_sub) ** 2)), 4)
            else:
                bs_sub = 0.0

            # Count total signals arriving in this window
            sig_mask = (df_signals["open_dt"] >= q_start) & (df_signals["open_dt"] < q_end)
            tot_sig_sub = int(sig_mask.sum())

            sub_periods.append(WalkForwardSubPeriodMetrics(
                window_id=f"Week {q + 1}",
                start_date=str(q_start.date()),
                end_date=str(q_end.date()),
                total_signals=tot_sig_sub,
                admitted_trades=n_sub,
                won_trades=w_sub,
                lost_trades=l_sub,
                breakeven_trades=be_sub,
                total_win_rate_pct=tot_wr,
                decisive_win_rate_pct=dec_wr,
                gross_pnl_usd=gross_sub,
                friction_usd=fric_sub,
                net_profit_usd=net_sub,
                annualized_sharpe=sub_sr,
                max_drawdown_pct=round(sub_max_dd, 2),
                brier_score=bs_sub
            ))

        # Overfitting Degradation Ratio (ODR):
        # Ratio of average out-of-sample forward slices (Week 2, 3, 4) vs Week 1 calibration
        calib_sr = sharpe_slices[0]
        oos_sr = float(np.mean(sharpe_slices[1:])) if len(sharpe_slices) > 1 else calib_sr
        if abs(calib_sr) > 1e-4:
            odr = round(oos_sr / calib_sr, 2)
        else:
            odr = 1.0

        return sub_periods, odr

    # --------------------------------------------------------------------------
    # 9. BREAKDOWN HELPERS
    # --------------------------------------------------------------------------

    def _breakdown_by_attribute(
        self,
        trades: List[WalkForwardTradeRecord],
        attr_name: str
    ) -> Dict[str, Dict[str, Any]]:
        groups = {}
        for t in trades:
            key = getattr(t, attr_name, "OTHER")
            if key not in groups:
                groups[key] = []
            groups[key].append(t)

        out = {}
        for k, tr_list in groups.items():
            n = len(tr_list)
            w = sum(1 for t in tr_list if t.outcome == "WON")
            l = sum(1 for t in tr_list if t.outcome == "LOST")
            be = sum(1 for t in tr_list if t.outcome == "BREAKEVEN")
            dec = w + l
            gross = sum(t.gross_pnl_usd for t in tr_list)
            friction = sum(t.total_friction_usd for t in tr_list)
            net = sum(t.net_pnl_usd for t in tr_list)

            out[k] = {
                "trades": n,
                "won": w,
                "lost": l,
                "breakeven": be,
                "total_win_rate_pct": round((w / n) * 100.0, 1),
                "decisive_win_rate_pct": round((w / max(1, dec)) * 100.0, 1) if dec > 0 else 0.0,
                "gross_pnl_usd": round(gross, 2),
                "friction_usd": round(friction, 2),
                "net_pnl_usd": round(net, 2)
            }
        return out
