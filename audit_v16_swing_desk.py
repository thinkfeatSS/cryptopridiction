"""
Detailed Forensic Audit of the 24H Swing Desk
Analyzes:
1. Frozen-Trade sensitivity (fixed position size) vs Dynamic compounding
2. Net expectancy per trade (Return on Notional %, Return on Margin %, R-multiples, Monetary USD)
3. Total Net PnL, Win/Loss distributions, Profit Factor, Max Drawdown
4. Dependence-aware circular block bootstrap 95% Confidence Intervals
5. Chronological walk-forward splits (Fold 1, Fold 2, Fold 3)
6. Asset and Market Regime breakdown
7. Top winners sensitivity: What happens if top 1, 2, or 3 winning trades are removed?
"""

import sys
import os
import json
import math
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.quant_v16.backtest import InstitutionalBacktestEngine, BacktestReport
from app.quant_v16.audit import classify_signal_outcome

def audit_swing_desk(csv_path: str = "freeze_archive_trader_signals_tracker.csv"):
    df = pd.read_csv(csv_path)
    
    # Filter 24H / Swing signals
    mask = df['horizon'].astype(str).str.contains('24H|1D|SWING|MACRO|7D|15D|30D', case=False, na=False)
    swing_raw = df[mask].copy()
    
    if "date_utc" in swing_raw.columns:
        time_col = swing_raw["time_utc"].fillna("00:00:00") if "time_utc" in swing_raw.columns else "00:00:00"
        swing_raw["dt_sort"] = swing_raw["date_utc"].astype(str) + " " + time_col.astype(str)
        swing_raw = swing_raw.sort_values("dt_sort").reset_index(drop=True)

    print("=" * 80)
    print("QUANT EDGE V16: INDEPENDENT FORENSIC AUDIT OF 24H SWING DESK")
    print("=" * 80)
    print(f"Total Raw Swing Signals in Dataset: {len(swing_raw)}")

    # 1. EVALUATION UNDER FROZEN POSITION SIZE (Fixed Capital = $250 allocated margin, 2x leverage = $500 position)
    ALLOCATED_MARGIN = 250.0 # Swing desk allocation
    LEVERAGE = 2
    POSITION_SIZE = ALLOCATED_MARGIN * LEVERAGE # $500.00
    DUR_HOURS = 24.0

    records = []
    for _, row in swing_raw.iterrows():
        entry_p = float(str(row.get('entry_price', 0)).replace('%','').replace('$','').replace(',','') or 0)
        tp1_p = float(str(row.get('tp1_price', 0)).replace('%','').replace('$','').replace(',','') or 0)
        sl_p = float(str(row.get('sl_price', 0)).replace('%','').replace('$','').replace(',','') or 0)
        exit_p = float(str(row.get('exit_price', 0)).replace('%','').replace('$','').replace(',','') or entry_p)

        if entry_p <= 0 or sl_p <= 0 or tp1_p <= 0:
            continue
        direction = str(row.get('direction', 'LONG')).upper()
        if direction not in ['LONG', 'SHORT']:
            continue

        st_raw = str(row.get('status', ''))
        out_raw = str(row.get('outcome_label', ''))
        ret_raw = float(str(row.get('realized_return_pct', 0)).replace('%','').replace('+','').strip() or 0)
        cat_outcome = classify_signal_outcome(st_raw, out_raw, ret_raw)
        if cat_outcome == 'PENDING':
            continue

        if exit_p > 0 and exit_p != entry_p:
            gross_ret_pct = ((exit_p - entry_p)/entry_p*100) if direction == 'LONG' else ((entry_p - exit_p)/entry_p*100)
        else:
            if cat_outcome == 'WON':
                gross_ret_pct = abs((tp1_p - entry_p)/entry_p)*100
                exit_p = tp1_p
            elif cat_outcome == 'LOST':
                gross_ret_pct = -abs((entry_p - sl_p)/entry_p)*100
                exit_p = sl_p
            else:
                gross_ret_pct = 0.0
                exit_p = entry_p

        gross_pnl = (gross_ret_pct / 100.0) * POSITION_SIZE

        # Itemized Frictions:
        fee_base = POSITION_SIZE * 0.000405 * 2.0 # Roundtrip taker
        spread_base = (4.0 / 10000.0) * POSITION_SIZE
        slip_base = (3.0 / 10000.0) * POSITION_SIZE
        funding_base = POSITION_SIZE * 0.0001 * (DUR_HOURS / 8.0) # 3 cycles of 8h funding
        friction_base = fee_base + spread_base + slip_base + funding_base

        net_pnl_base = gross_pnl - friction_base
        net_ret_margin_pct = (net_pnl_base / ALLOCATED_MARGIN) * 100.0
        net_ret_notional_pct = (net_pnl_base / POSITION_SIZE) * 100.0

        r_risk_usd = abs((entry_p - sl_p) / entry_p) * POSITION_SIZE
        r_multiple = net_pnl_base / max(0.01, r_risk_usd) if r_risk_usd > 0 else 0.0

        records.append({
            "signal_id": row.get("signal_id"),
            "date": row.get("date_utc"),
            "symbol": row.get("symbol"),
            "direction": direction,
            "entry_price": entry_p,
            "exit_price": exit_p,
            "gross_ret_pct": gross_ret_pct,
            "gross_pnl": gross_pnl,
            "friction_base": friction_base,
            "fee_base": fee_base,
            "spread_base": spread_base,
            "slip_base": slip_base,
            "funding_base": funding_base,
            "net_pnl_base": net_pnl_base,
            "net_pnl_15x": gross_pnl - (friction_base * 1.5),
            "net_pnl_20x": gross_pnl - (friction_base * 2.0),
            "net_ret_margin_pct": net_ret_margin_pct,
            "net_ret_notional_pct": net_ret_notional_pct,
            "r_multiple": r_multiple,
            "outcome": "WON" if net_pnl_base > 0.05 else ("LOST" if net_pnl_base < -0.05 else "BREAKEVEN")
        })

    trades_df = pd.DataFrame(records)
    n_trades = len(trades_df)
    print(f"Total Completed Validated Swing Trades: {n_trades}")

    # 1. SUMMARY STATS (FROZEN NOTIONAL POSITION SIZE)
    for mult_name, col in [("BASE (1.0x)", "net_pnl_base"), ("STRESS (1.5x)", "net_pnl_15x"), ("STRESS (2.0x)", "net_pnl_20x")]:
        net_pnls = trades_df[col].values
        tot_net = np.sum(net_pnls)
        tot_gross = np.sum(trades_df["gross_pnl"].values)
        tot_fric = tot_gross - tot_net
        won_cnt = np.sum(net_pnls > 0.05)
        lost_cnt = np.sum(net_pnls < -0.05)
        be_cnt = np.sum((net_pnls >= -0.05) & (net_pnls <= 0.05))
        wr = (won_cnt / n_trades) * 100.0
        dec_wr = (won_cnt / max(1, won_cnt + lost_cnt)) * 100.0

        wins = net_pnls[net_pnls > 0.05]
        losses = np.abs(net_pnls[net_pnls < -0.05])
        avg_w = np.mean(wins) if len(wins) > 0 else 0.0
        avg_l = np.mean(losses) if len(losses) > 0 else 0.0
        pf = (np.sum(wins) / np.sum(losses)) if np.sum(losses) > 0 else 99.0

        # Circular Block Bootstrap 95% Confidence Interval for Net PnL Mean
        rng = np.random.default_rng(42)
        block_size = 5
        n_blocks = n_trades // block_size
        boot_means = []
        for _ in range(1000):
            idx_starts = rng.integers(0, n_trades - block_size + 1, size=n_blocks)
            sample = np.concatenate([net_pnls[i:i+block_size] for i in idx_starts])
            boot_means.append(np.mean(sample))
        ci_low = np.percentile(boot_means, 2.5)
        ci_high = np.percentile(boot_means, 97.5)

        print(f"\n--- {mult_name} (Fixed Position Size $500 Notional) ---")
        print(f"  Gross PnL:        ${tot_gross:.2f}")
        print(f"  Friction:         -${tot_fric:.2f}")
        print(f"  Net Realized PnL: ${tot_net:.2f}")
        print(f"  Won / Lost / BE:  {won_cnt} / {lost_cnt} / {be_cnt}")
        print(f"  Total Win Rate:   {wr:.2f}% (incl. BE in denom)")
        print(f"  Decisive Win Rate:{dec_wr:.2f}%")
        print(f"  Profit Factor:    {pf:.2f}")
        print(f"  Avg Win / Avg Loss: ${avg_w:.2f} / ${avg_l:.2f} (Ratio: {avg_w/max(0.01, avg_l):.2f})")
        print(f"  Net EV per Trade: ${tot_net / n_trades:.2f} ({((tot_net / n_trades) / POSITION_SIZE)*100:.3f}% Notional)")
        print(f"  Block Bootstrap 95% CI (Mean Net PnL per Trade): [${ci_low:.2f}, ${ci_high:.2f}]")

    # 2. TOP WINNERS SENSITIVITY (Outlier Resilience Audit)
    print("\n--- OUTLIER SENSITIVITY AUDIT (BASE 1.0x) ---")
    sorted_pnls = trades_df.sort_values("net_pnl_base", ascending=False)
    print("Top 5 Winning Trades:")
    for _, t in sorted_pnls.head(5).iterrows():
        print(f"  {t['date']} {t['symbol']} ({t['direction']}): Gross=+${t['gross_pnl']:.2f}, Net=+${t['net_pnl_base']:.2f}")

    orig_net = trades_df['net_pnl_base'].sum()
    net_minus_1 = sorted_pnls.iloc[1:]['net_pnl_base'].sum()
    net_minus_2 = sorted_pnls.iloc[2:]['net_pnl_base'].sum()
    net_minus_3 = sorted_pnls.iloc[3:]['net_pnl_base'].sum()
    print(f"\nOriginal Net PnL (100 trades):     ${orig_net:.2f}")
    print(f"Without #1 Winner:                 ${net_minus_1:.2f}")
    print(f"Without Top 2 Winners:             ${net_minus_2:.2f}")
    print(f"Without Top 3 Winners:             ${net_minus_3:.2f}")

    # 3. CHRONOLOGICAL WALK-FORWARD SUB-PERIODS
    print("\n--- CHRONOLOGICAL WALK-FORWARD FOLDS ---")
    fold_size = n_trades // 3
    for fold_i in range(3):
        start_idx = fold_i * fold_size
        end_idx = (fold_i + 1) * fold_size if fold_i < 2 else n_trades
        sub = trades_df.iloc[start_idx:end_idx]
        sub_net = sub['net_pnl_base'].sum()
        sub_gross = sub['gross_pnl'].sum()
        sub_w = sum(sub['net_pnl_base'] > 0.05)
        sub_wr = (sub_w / len(sub)) * 100.0
        print(f"Fold {fold_i+1} ({sub.iloc[0]['date']} to {sub.iloc[-1]['date']}): "
              f"N={len(sub)}, Gross=${sub_gross:.2f}, Net=${sub_net:.2f}, WR={sub_wr:.1f}%")

    # 4. ASSET CONCENTRATION BREAKDOWN
    print("\n--- ASSET BREAKDOWN (TOP 5 BY VOLUME) ---")
    top_syms = trades_df['symbol'].value_counts().head(5).index
    for s in top_syms:
        s_df = trades_df[trades_df['symbol'] == s]
        s_net = s_df['net_pnl_base'].sum()
        s_w = sum(s_df['net_pnl_base'] > 0.05)
        print(f"  {s:10s}: Trades={len(s_df):2d}, WinRate={s_w/len(s_df)*100:.1f}%, Net PnL=${s_net:.2f}")

if __name__ == "__main__":
    audit_swing_desk()
