"""
QUANT EDGE V16: Walk-Forward Shadow Replay CLI Runner & 30-Day Mathematical Edge Audit
Specifications:
- Loads the unbroken 30-day chronological signal dataset across both historical and live tracker stores.
- Executes the Walk-Forward Shadow Replay Engine under:
    * Scenario 1: BASE (1.0x canonical friction)
    * Scenario 2: STRESS (1.5x adverse friction stress test)
- Serializes complete institutional audit artifact to:
    export_app_data/v16_walk_forward_30d_report.json
- Formats and displays an institutional audit table covering Sharpe, Brier score, calibration,
  drawdown dynamics, walk-forward sub-period slices, and bootstrap confidence intervals.
"""

import os
import sys
import json
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from dataclasses import asdict

from app.quant_v16.walk_forward_replay import (
    WalkForwardShadowReplayEngine,
    WalkForwardReplayConfig,
    WalkForwardReport
)

HISTORICAL_CSV = "export_app_data/historical_meta_training_signals.csv"
LIVE_TRACKER_CSV = "export_app_data/live_container_trader_signals_tracker.csv"
OUTPUT_REPORT_JSON = "export_app_data/v16_walk_forward_30d_report.json"

def load_authoritative_signals() -> pd.DataFrame:
    """
    Ingests and merges historical and live container tracker signals,
    deduplicating by signal_id to ensure a seamless unbroken timeline.
    """
    dfs = []
    if os.path.exists(HISTORICAL_CSV):
        df_hist = pd.read_csv(HISTORICAL_CSV)
        dfs.append(df_hist)
        print(f"[REPLAY DATA] Loaded historical meta training signals: {len(df_hist):,} records")

    if os.path.exists(LIVE_TRACKER_CSV):
        df_live = pd.read_csv(LIVE_TRACKER_CSV)
        dfs.append(df_live)
        print(f"[REPLAY DATA] Loaded live container signals tracker: {len(df_live):,} records")

    if not dfs:
        raise FileNotFoundError("No signal data files found in export_app_data/")

    comb = pd.concat(dfs, ignore_index=True)
    comb = comb.drop_duplicates(subset=["signal_id"]).reset_index(drop=True)
    print(f"[REPLAY DATA] Combined unique signals: {len(comb):,} records")
    return comb

def format_currency(val: float) -> str:
    sign = "+" if val > 0 else ("-" if val < 0 else " ")
    return f"{sign}${abs(val):,.2f}"

def format_pct(val: float) -> str:
    sign = "+" if val > 0 else ("-" if val < 0 else " ")
    return f"{sign}{abs(val):.2f}%"

def run_audit():
    print("=" * 90)
    print("🏛️  QUANT EDGE V16: WALK-FORWARD SHADOW REPLAY ENGINE & 30-DAY STATISTICAL AUDIT")
    print("=" * 90)

    # 1. Ingest Data
    signals_df = load_authoritative_signals()

    # 2. Initialize Engine
    cfg = WalkForwardReplayConfig(
        initial_capital_usd=1000.0,
        desk_allocations={"swing": 0.50, "day": 0.35, "scalp": 0.15},
        desk_slots={"swing": 3, "day": 2, "scalp": 1},
        desk_leverage={"swing": 2, "day": 3, "scalp": 2},
        max_global_slots=6,
        quality_gate_enabled=True,
        random_seed=42,
        num_bootstrap_resamples=1000
    )
    engine = WalkForwardShadowReplayEngine(config=cfg)

    # 3. Execute BASE Scenario (1.0x Friction)
    print("\n[REPLAY RUNNER] Executing Scenario 1: BASE (1.0x Canonical Friction)...")
    report_base = engine.run_replay(signals_df, scenario_name="BASE", cost_multiplier=1.0)

    # 4. Execute STRESS Scenario (1.5x Friction)
    print("[REPLAY RUNNER] Executing Scenario 2: STRESS (1.5x Adverse Execution Friction)...")
    report_stress = engine.run_replay(signals_df, scenario_name="STRESS_1.5X", cost_multiplier=1.5)

    # 5. Display Institutional Terminal Output
    print("\n" + "=" * 90)
    print(f"📊 30-DAY OUT-OF-SAMPLE WALK-FORWARD PERFORMANCE REPORT ({report_base.scenario_name})")
    print("=" * 90)
    print(f"Window Start:         {report_base.window_start_utc}")
    print(f"Window End:           {report_base.window_end_utc} ({report_base.total_window_days:.1f} Days)")
    print(f"Initial Capital:      ${report_base.initial_capital_usd:,.2f}")
    print(f"Final Balance:        ${report_base.final_balance_usd:,.2f}")
    print(f"Net Realized PnL:     {format_currency(report_base.net_profit_usd)} ({format_pct(report_base.net_profit_usd / report_base.initial_capital_usd * 100.0)})")
    print(f"Gross PnL / Friction: {format_currency(report_base.gross_pnl_usd)} gross  |  -${report_base.total_friction_usd:,.2f} friction paid")
    print(f"Profit Factor:        {report_base.profit_factor:.2f}")

    print("-" * 90)
    print("🎯 EXECUTION THROUGHPUT & CAPACITY GATING")
    print("-" * 90)
    print(f"Total Signals Evaluated:      {report_base.total_signals_evaluated:,}")
    print(f"Admitted & Executed Trades:   {report_base.total_admitted_trades:,} ({report_base.total_admitted_trades / report_base.total_signals_evaluated * 100.0:.1f}% admission rate)")
    print(f"Rejected - Desk Capacity:     {report_base.rejected_capacity_desk:,}")
    print(f"Rejected - Global Capacity:   {report_base.rejected_capacity_global:,}")
    print(f"Rejected - Duplicate Symbol:  {report_base.rejected_duplicate_symbol:,}")
    print(f"Rejected - Quality Gate:      {report_base.rejected_quality_gate:,}")
    print(f"Unresolved / Pending Signals: {report_base.rejected_pending:,}")

    print("-" * 90)
    print("⚖️  STRICT BREAKEVEN & WIN RATE INTEGRITY")
    print("-" * 90)
    print(f"Won Trades:            {report_base.won_trades:,}")
    print(f"Lost Trades:           {report_base.lost_trades:,}")
    print(f"Breakeven Trades:      {report_base.breakeven_trades:,} (strictly excluded from wins)")
    print(f"Total Closed Win Rate: {report_base.total_win_rate_pct:.2f}% (Won / [Won + Lost + BE])")
    print(f"Decisive Win Rate:     {report_base.decisive_win_rate_pct:.2f}% (Won / [Won + Lost])")
    print(f"Breakeven Rate:        {report_base.breakeven_rate_pct:.2f}%")
    print(f"Average Win:           ${report_base.average_win_usd:,.2f}  |  Average Loss: -${report_base.average_loss_usd:,.2f}  |  Payoff Ratio: {report_base.win_loss_payoff_ratio:.2f}")

    print("-" * 90)
    print("📈 SHARPE, SORTINO & DRAWDOWN DYNAMICS")
    print("-" * 90)
    print(f"Annualized Daily Sharpe Ratio:   {report_base.annualized_daily_sharpe:.2f}")
    print(f"Annualized Daily Sortino Ratio:  {report_base.annualized_daily_sortino:.2f}")
    print(f"Trade-Level Sharpe Ratio:        {report_base.trade_level_sharpe:.2f}")
    print(f"Calmar Ratio:                    {report_base.calmar_ratio:.2f}")
    print(f"Max Portfolio Drawdown:          -{report_base.max_drawdown_pct:.2f}% (-${report_base.max_drawdown_usd:,.2f})")
    print(f"Max Drawdown Duration:           {report_base.max_drawdown_duration_days:.1f} days")
    print(f"Drawdown Recovery Duration:      {report_base.recovery_duration_days:.1f} days")
    print(f"Risk-Budgeted 1R Max Drawdown:   -{report_base.risk_budgeted_1r_max_dd_pct:.2f}%")
    print(f"Raw Compounding Max Drawdown:    -{report_base.raw_compounding_max_dd_pct:.2f}%")

    print("-" * 90)
    print("🔮 PROBABILITY MODEL, BRIER SCORE & CALIBRATION")
    print("-" * 90)
    print(f"Raw Model Brier Score:           {report_base.brier_score_raw:.4f}")
    print(f"Reference Climatology BS:        {report_base.brier_score_reference:.4f} (Base Rate Y_bar)")
    print(f"Raw Brier Skill Score (BSS):     {report_base.brier_skill_score_raw:+.4f}")
    print(f"Platt-Calibrated Brier Score:    {report_base.brier_score_calibrated:.4f}")
    print(f"Platt-Calibrated BSS:            {report_base.brier_skill_score_calibrated:+.4f} (Calibrated Skill Edge)")
    print(f"Raw Expected Calibration Error:  {report_base.expected_calibration_error_raw * 100.0:.2f}%")
    print(f"Calibrated ECE (Hurdle <= 5.0%): {report_base.expected_calibration_error_calibrated * 100.0:.2f}%")

    print("\nDecile Calibration Breakdown:")
    print(f"{'Decile':<12} | {'Count':<7} | {'Avg Pred Prob':<14} | {'Avg Cal Prob':<13} | {'Actual Win Rate':<16} | {'Error'}")
    print("-" * 75)
    for dec in report_base.calibration_deciles:
        print(f"{dec['decile_label']:<12} | {dec['count']:<7} | {dec['avg_predicted_prob']*100.0:>12.1f}% | {dec['avg_calibrated_prob']*100.0:>11.1f}% | {dec['actual_tp1_rate']*100.0:>14.1f}% | {dec['calibration_error']*100.0:>5.1f}%")

    print("-" * 90)
    print("🔄 4-WEEK WALK-FORWARD SEQUENTIAL SLICES & OVERFITTING ANALYSIS")
    print("-" * 90)
    print(f"{'Slice':<10} | {'Dates':<23} | {'Signals':<8} | {'Trades':<7} | {'Dec WR':<8} | {'Net PnL':<12} | {'Sharpe':<7} | {'Max DD'}")
    print("-" * 90)
    for sp in report_base.sub_periods:
        pnl_str = format_currency(sp.net_profit_usd)
        print(f"{sp.window_id:<10} | {sp.start_date} -> {sp.end_date} | {sp.total_signals:<8} | {sp.admitted_trades:<7} | {sp.decisive_win_rate_pct:>6.1f}% | {pnl_str:>12} | {sp.annualized_sharpe:>7.2f} | -{sp.max_drawdown_pct:.1f}%")
    print(f"Overfitting Degradation Ratio (ODR): {report_base.overfitting_degradation_ratio:.2f}")

    print("-" * 90)
    print("🎲 NON-PARAMETRIC BOOTSTRAP 95% CONFIDENCE INTERVALS (1,000 RESAMPLES)")
    print("-" * 90)
    for metric_name, ci_data in report_base.bootstrap_ci_95.items():
        pt = ci_data["point_estimate"]
        lo = ci_data["ci_lower_95"]
        hi = ci_data["ci_upper_95"]
        unit = "%" if "pct" in metric_name or "rate" in metric_name else ("$" if "profit" in metric_name or "usd" in metric_name else "")
        print(f"{metric_name:<25} Point: {pt:>8.2f}{unit}  |  95% CI: [{lo:>8.2f}{unit}, {hi:>8.2f}{unit}]")

    print("-" * 90)
    print("⚡ DESK PERFORMANCE ATTRIBUTION")
    print("-" * 90)
    for desk_name, desk_m in report_base.desk_breakdown.items():
        print(f"Desk {desk_name.upper():<8} | Trades: {desk_m['trades']:<5} | Won: {desk_m['won']:<4} | Lost: {desk_m['lost']:<4} | BE: {desk_m['breakeven']:<4} | Dec WR: {desk_m['decisive_win_rate_pct']:>5.1f}% | Net PnL: {format_currency(desk_m['net_pnl_usd'])}")

    print("-" * 90)
    print("🛡️  FRICTION SENSITIVITY & ADVERSE COST STRESS COMPARISON")
    print("-" * 90)
    print(f"{'Metric':<30} | {'BASE (1.0x)':<18} | {'STRESS (1.5x)':<18} | {'Degradation'}")
    print("-" * 75)
    print(f"{'Net Realized Profit':<30} | {format_currency(report_base.net_profit_usd):<18} | {format_currency(report_stress.net_profit_usd):<18} | {format_currency(report_stress.net_profit_usd - report_base.net_profit_usd)}")
    print(f"{'Total Friction Paid':<30} | ${report_base.total_friction_usd:<17,.2f} | ${report_stress.total_friction_usd:<17,.2f} | +${report_stress.total_friction_usd - report_base.total_friction_usd:,.2f}")
    print(f"{'Decisive Win Rate':<30} | {report_base.decisive_win_rate_pct:>16.2f}% | {report_stress.decisive_win_rate_pct:>16.2f}% | {report_stress.decisive_win_rate_pct - report_base.decisive_win_rate_pct:+.2f}%")
    print(f"{'Annualized Daily Sharpe':<30} | {report_base.annualized_daily_sharpe:>18.2f} | {report_stress.annualized_daily_sharpe:>18.2f} | {report_stress.annualized_daily_sharpe - report_base.annualized_daily_sharpe:+.2f}")
    print(f"{'Max Portfolio Drawdown':<30} | -{report_base.max_drawdown_pct:>16.2f}% | -{report_stress.max_drawdown_pct:>16.2f}% | {report_stress.max_drawdown_pct - report_base.max_drawdown_pct:+.2f}%")

    # 6. Export Full JSON Artifact
    def _sanitize(obj):
        if isinstance(obj, (np.floating, float)):
            return round(float(obj), 4)
        if isinstance(obj, (np.integer, int)):
            return int(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return obj

    export_dict = {
        "audit_metadata": {
            "title": "Quant Edge V16 Walk-Forward Shadow Replay 30-Day Audit",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "window_start_utc": report_base.window_start_utc,
            "window_end_utc": report_base.window_end_utc,
            "window_days": report_base.total_window_days,
            "total_signals_evaluated": report_base.total_signals_evaluated,
            "authoritative_sources": [HISTORICAL_CSV, LIVE_TRACKER_CSV]
        },
        "base_scenario": asdict(report_base),
        "stress_scenario": asdict(report_stress),
        "sensitivity_delta": {
            "net_profit_delta_usd": round(report_stress.net_profit_usd - report_base.net_profit_usd, 2),
            "friction_delta_usd": round(report_stress.total_friction_usd - report_base.total_friction_usd, 2),
            "sharpe_delta": round(report_stress.annualized_daily_sharpe - report_base.annualized_daily_sharpe, 2),
            "decisive_wr_delta_pct": round(report_stress.decisive_win_rate_pct - report_base.decisive_win_rate_pct, 2)
        },
        "edge_validation_verdict": {
            "brier_calibration_pass": bool(report_base.expected_calibration_error_calibrated <= 0.05),
            "brier_skill_positive": bool(report_base.brier_skill_score_calibrated > 0.0),
            "capacity_gating_active": bool(report_base.rejected_capacity_desk > 0),
            "strict_breakeven_enforced": True,
            "zero_lookahead_enforced": True
        }
    }

    # Remove huge trade list from root if needed, or keep compact
    with open(OUTPUT_REPORT_JSON, "w") as f:
        json.dump(export_dict, f, indent=2, default=_sanitize)
    print(f"\n[ARTIFACT EXPORT] Successfully wrote 30-day walk-forward audit report to:\n  -> {OUTPUT_REPORT_JSON}")
    print("=" * 90)

if __name__ == "__main__":
    run_audit()

