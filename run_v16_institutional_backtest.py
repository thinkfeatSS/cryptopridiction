"""
Institutional Backtest Runner for Quant Edge V16
Runs:
1. Evaluation Mode A: FROZEN_NOTIONAL_SENSITIVITY (Fixed Position Size, pure cost scaling)
2. Evaluation Mode B: DYNAMIC_COMPOUNDING (Simulated dynamic portfolio with capital compounding)
For BASE (1.0x), STRESS_15X (1.5x), and STRESS_20X (2.0x).
"""
import sys
import os
import json
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from app.quant_v16.backtest import InstitutionalBacktestEngine, BacktestReport

def run_all_scenarios(csv_path: str = "freeze_archive_trader_signals_tracker.csv"):
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} does not exist.")
        return

    df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} signals from {csv_path}")

    engine = InstitutionalBacktestEngine(
        initial_capital=1000.0,
        taker_fee_rate=0.000405, # 0.0405%
        default_spread_bps=4.0,   # 4 bps
        default_slippage_bps=3.0, # 3 bps
        default_funding_rate_8h=0.0001 # 0.01%
    )

    scenarios = [
        ("BASE", 1.0),
        ("STRESS_15X", 1.5),
        ("STRESS_20X", 2.0)
    ]

    all_reports = {}

    for mode in ["FROZEN_NOTIONAL_SENSITIVITY", "DYNAMIC_COMPOUNDING"]:
        print("\n" + "#" * 80)
        print(f"### SIMULATION MODE: {mode} ###")
        print("#" * 80)
        mode_reports = {}

        for name, mult in scenarios:
            rep = engine.run_simulation(df, cost_multiplier=mult, scenario_name=name, simulation_mode=mode)
            mode_reports[name] = rep
            reconciled_diff = round(rep.gross_pnl_usd - rep.total_friction_usd - rep.net_profit_usd, 4)
            print(f"\n================ SCENARIO: {name} ({mult}x Cost) ================")
            print(f"Initial Capital:          ${rep.initial_capital_usd:.2f}")
            print(f"Final Balance:            ${rep.final_balance_usd:.2f}")
            print(f"Net Realized Profit:      ${rep.net_profit_usd:.2f}")
            print(f"Total Trades Evaluated:   {rep.total_trades}")
            print(f"Won / Lost / Breakeven:   {rep.won_trades} / {rep.lost_trades} / {rep.breakeven_trades}")
            print(f"Total Closed Win Rate:    {rep.total_closed_win_rate_pct:.2f}% (incl. BE in denom)")
            print(f"Decisive Win Rate:        {rep.decisive_win_rate_pct:.2f}% (Won / (Won + Lost))")
            print(f"Profit Factor:            {rep.profit_factor:.2f}")
            print(f"Gross PnL / Friction:     ${rep.gross_pnl_usd:.2f} / -${rep.total_friction_usd:.2f}")
            print(f"Accounting Reconciliation: Gross (${rep.gross_pnl_usd:.2f}) - Friction (${rep.total_friction_usd:.2f}) = Net (${rep.gross_pnl_usd - rep.total_friction_usd:.2f}) | Discrepancy: ${reconciled_diff:.2f}")
            print(f"  - Fees Paid:            ${rep.fees_paid_usd:.2f}")
            print(f"  - Spread Paid:          ${rep.spread_paid_usd:.2f}")
            print(f"  - Slippage Paid:        ${rep.slippage_paid_usd:.2f}")
            print(f"  - Funding Paid:         ${rep.funding_paid_usd:.2f}")
            print(f"Max Drawdown:             ${rep.max_drawdown_usd:.2f} ({rep.max_drawdown_pct:.2f}%)")
            print(f"Avg Win / Avg Loss:       ${rep.average_win_usd:.2f} / ${rep.average_loss_usd:.2f} (Ratio: {rep.win_loss_ratio:.2f})")
            print(f"Sharpe / Sortino:         {rep.sharpe_ratio:.2f} / {rep.sortino_ratio:.2f}")
            print(f"Net EV (Notional %):      {rep.net_expectancy_notional_pct:.3f}%")
            print(f"Net EV (Margin Return %): {rep.net_expectancy_capital_pct:.2f}%")
            print(f"Bootstrap 95% CI (Return):[{rep.ci_95_lower_pct:.2f}%, {rep.ci_95_upper_pct:.2f}%]")
            print("\nHorizon Breakdown:")
            for hz, st in rep.horizon_breakdown.items():
                print(f"  - {hz:5s}: Trades={st.get('trades',0):4d}, WR={st.get('win_rate_pct',0):.1f}%, Net PnL=${st.get('net_pnl_usd',0):.2f}")
            print("\nGrade Breakdown:")
            for g, st in rep.grade_breakdown.items():
                print(f"  - {g:8s}: Trades={st.get('trades',0):4d}, WR={st.get('win_rate_pct',0):.1f}%, Net PnL=${st.get('net_pnl_usd',0):.2f}")

        all_reports[mode] = mode_reports

    return all_reports

if __name__ == "__main__":
    run_all_scenarios()
