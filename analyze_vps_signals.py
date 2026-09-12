import sys
import io

# Force UTF-8 encoding for console output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import paramiko
import pandas as pd

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("187.52.116.72", username="root", password="bCSy+h7kMuo.f+6h", timeout=15)

# Download trader_signals_tracker.csv via SFTP
sftp = ssh.open_sftp()
with sftp.open("/root/crypto/export_app_data/trader_signals_tracker.csv", "r") as f:
    df = pd.read_csv(f)

sftp.close()
ssh.close()

def clean_ret(val):
    if pd.isna(val) or val == '':
        return None
    s = str(val).replace('%', '').replace('+', '').strip()
    try:
        return float(s)
    except:
        return None

df['ret_num'] = df['realized_return_pct'].apply(clean_ret)
resolved_df = df[df['status'].isin(['WON_TP1', 'WON_TP2', 'WON_TP3', 'LOST_SL']) | df['outcome_label'].str.contains('WON|LOST', na=False)].copy()

print("=" * 80)
print(f"📊 VPS LIVE SIGNALS AUDIT LEDGER ({len(df)} Total Signals Logged)")
print("=" * 80)

total_resolved = len(resolved_df)
won_mask = resolved_df['outcome_label'].str.contains('WON', na=False)
lost_mask = resolved_df['outcome_label'].str.contains('LOST', na=False)
won_cnt = won_mask.sum()
lost_cnt = lost_mask.sum()
win_rate = (won_cnt / total_resolved * 100) if total_resolved > 0 else 0.0

print(f"• Total Resolved Signals : {total_resolved}")
print(f"• Wins                   : {won_cnt}")
print(f"• Losses                 : {lost_cnt}")
print(f"• Decisive Win Rate      : {win_rate:.1f}%")
print(f"• Cumulative Return      : {resolved_df['ret_num'].sum():+.2f}%")
print(f"• Average PnL per Trade  : {resolved_df['ret_num'].mean():+.2f}%")
print(f"• Avg Win / Avg Loss     : {resolved_df[resolved_df['ret_num'] > 0]['ret_num'].mean():+.2f}% / {resolved_df[resolved_df['ret_num'] < 0]['ret_num'].mean():.2f}%")

print("\n📈 PERFORMANCE BY DIRECTION:")
print("-" * 80)
dir_grp = resolved_df.groupby('direction').agg(
    total=('signal_id', 'count'),
    won=('outcome_label', lambda s: s.str.contains('WON').sum()),
    lost=('outcome_label', lambda s: s.str.contains('LOST').sum()),
    sum_pnl=('ret_num', 'sum'),
    avg_pnl=('ret_num', 'mean'),
    avg_win=('ret_num', lambda s: s[s > 0].mean()),
    avg_loss=('ret_num', lambda s: s[s < 0].mean())
)
dir_grp['win_rate%'] = (dir_grp['won'] / dir_grp['total'] * 100).round(1)
print(dir_grp.to_string())

print("\n⏱️ PERFORMANCE BY HORIZON:")
print("-" * 80)
h_grp = resolved_df.groupby('horizon').agg(
    total=('signal_id', 'count'),
    won=('outcome_label', lambda s: s.str.contains('WON').sum()),
    lost=('outcome_label', lambda s: s.str.contains('LOST').sum()),
    sum_pnl=('ret_num', 'sum'),
    avg_pnl=('ret_num', 'mean')
)
h_grp['win_rate%'] = (h_grp['won'] / h_grp['total'] * 100).round(1)
print(h_grp.to_string())
print("=" * 80)
