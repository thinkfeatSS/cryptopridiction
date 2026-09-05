import sys
import io

# Set UTF-8 encoding for stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import pandas as pd
import numpy as np

# Load user pasted CSV
csv_file = "user_pasted_signals.csv"
df = pd.read_csv(csv_file)

def clean_ret(val):
    if pd.isna(val) or val == '':
        return np.nan
    s = str(val).replace('%', '').replace('+', '').strip()
    try:
        return float(s)
    except:
        return np.nan

df['ret_num'] = df['realized_return_pct'].apply(clean_ret)
df['max_gain_num'] = pd.to_numeric(df['max_potential_gain_pct'], errors='coerce')

total_signals = len(df)
resolved_df = df[df['status'].isin(['WON_TP1', 'WON_TP2', 'WON_TP3', 'LOST_SL']) | df['outcome_label'].str.contains('WON|LOST', na=False)]
pending_df = df[df['status'] == 'PENDING_EVALUATION']

won_df = df[df['outcome_label'].str.contains('WON', na=False)]
lost_df = df[df['outcome_label'].str.contains('LOST', na=False)]

total_resolved = len(resolved_df)
won_count = len(won_df)
lost_count = len(lost_df)
pending_count = len(pending_df)
win_rate = (won_count / total_resolved * 100) if total_resolved > 0 else 0

total_gross_return = resolved_df['ret_num'].sum()
avg_return_per_trade = resolved_df['ret_num'].mean()

avg_win = won_df['ret_num'].mean()
avg_loss = lost_df['ret_num'].mean()

gross_win_sum = won_df['ret_num'].sum()
gross_loss_sum = abs(lost_df['ret_num'].sum())
profit_factor = (gross_win_sum / gross_loss_sum) if gross_loss_sum > 0 else np.nan

# Fee assumptions (0.08% taker roundtrip + 0.02% slippage = 0.10% per trade)
fee_per_trade = 0.10
net_return = (resolved_df['ret_num'] - fee_per_trade).sum()
net_avg_return = (resolved_df['ret_num'] - fee_per_trade).mean()

print(f"=== OVERALL METRICS ===")
print(f"Total Tracked: {total_signals}")
print(f"Resolved: {total_resolved} (Won: {won_count}, Lost: {lost_count}, Pending: {pending_count})")
print(f"Win Rate: {win_rate:.2f}%")
print(f"Gross Cumulative PnL: {total_gross_return:+.2f}%")
print(f"Avg Return / Trade: {avg_return_per_trade:+.2f}%")
print(f"Avg Win: {avg_win:+.2f}% | Avg Loss: {avg_loss:.2f}%")
print(f"Reward-to-Risk (Avg Win / |Avg Loss|): {abs(avg_win / avg_loss):.2f}")
print(f"Profit Factor: {profit_factor:.2f}")
print(f"Net Return (after 0.10% fee/trade): {net_return:+.2f}% (Avg Net: {net_avg_return:+.2f}%)")

print("\n=== TP HIT BREAKDOWN ===")
print(resolved_df['status'].value_counts())

print("\n=== BY HORIZON ===")
horizon_grp = resolved_df.groupby('horizon').agg(
    total=('signal_id', 'count'),
    won=('outcome_label', lambda s: s.str.contains('WON').sum()),
    lost=('outcome_label', lambda s: s.str.contains('LOST').sum()),
    gross_pnl=('ret_num', 'sum'),
    avg_pnl=('ret_num', 'mean'),
    max_win=('ret_num', 'max'),
    max_loss=('ret_num', 'min')
)
horizon_grp['win_rate'] = (horizon_grp['won'] / horizon_grp['total'] * 100).round(1)
print(horizon_grp.to_string())

print("\n=== BY DIRECTION ===")
dir_grp = resolved_df.groupby('direction').agg(
    total=('signal_id', 'count'),
    won=('outcome_label', lambda s: s.str.contains('WON').sum()),
    lost=('outcome_label', lambda s: s.str.contains('LOST').sum()),
    gross_pnl=('ret_num', 'sum'),
    avg_pnl=('ret_num', 'mean')
)
dir_grp['win_rate'] = (dir_grp['won'] / dir_grp['total'] * 100).round(1)
print(dir_grp.to_string())

print("\n=== BY QUALITY GRADE ===")
grade_grp = resolved_df.groupby('quality_grade').agg(
    total=('signal_id', 'count'),
    won=('outcome_label', lambda s: s.str.contains('WON').sum()),
    lost=('outcome_label', lambda s: s.str.contains('LOST').sum()),
    gross_pnl=('ret_num', 'sum'),
    avg_pnl=('ret_num', 'mean')
)
grade_grp['win_rate'] = (grade_grp['won'] / grade_grp['total'] * 100).round(1)
print(grade_grp.to_string())

print("\n=== BY TOP SYMBOLS ===")
sym_grp = resolved_df.groupby('symbol').agg(
    total=('signal_id', 'count'),
    won=('outcome_label', lambda s: s.str.contains('WON').sum()),
    lost=('outcome_label', lambda s: s.str.contains('LOST').sum()),
    gross_pnl=('ret_num', 'sum'),
    avg_pnl=('ret_num', 'mean')
).sort_values('total', ascending=False)
sym_grp['win_rate'] = (sym_grp['won'] / sym_grp['total'] * 100).round(1)
print(sym_grp.head(15).to_string())
