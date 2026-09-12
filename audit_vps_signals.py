import paramiko
import os
import pandas as pd

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("187.52.116.72", username="root", password="bCSy+h7kMuo.f+6h", timeout=15)

sftp = ssh.open_sftp()
local_path = r"C:\Users\ismail\.gemini\antigravity-ide\brain\07d4f59a-aa32-4405-a210-1e8cd4263536\scratch\trader_signals_tracker.csv"

# Download trader_signals_tracker.csv
try:
    sftp.get("/root/crypto/export_app_data/trader_signals_tracker.csv", local_path)
    print("Downloaded /root/crypto/export_app_data/trader_signals_tracker.csv successfully!")
except Exception as e:
    print(f"Error downloading trader_signals_tracker.csv: {e}")

sftp.close()
ssh.close()

if os.path.exists(local_path):
    df = pd.read_csv(local_path)
    print(f"\nLoaded {len(df)} total signals from VPS")
    
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
    
    print("\n=== FULL VPS LEDGER: RESOLVED STATS ===")
    print(f"Total resolved: {len(resolved_df)}")
    won_mask = resolved_df['outcome_label'].str.contains('WON', na=False)
    lost_mask = resolved_df['outcome_label'].str.contains('LOST', na=False)
    print(f"Won: {won_mask.sum()}, Lost: {lost_mask.sum()}, Win Rate: {won_mask.sum()/len(resolved_df)*100:.2f}%")
    print(f"Total Gross Return: {resolved_df['ret_num'].sum():.2f}%")
    print(f"Avg Return: {resolved_df['ret_num'].mean():.2f}%")
    
    print("\n=== BY DIRECTION ===")
    dir_grp = resolved_df.groupby('direction').agg(
        total=('signal_id', 'count'),
        won=('outcome_label', lambda s: s.str.contains('WON').sum()),
        lost=('outcome_label', lambda s: s.str.contains('LOST').sum()),
        sum_pnl=('ret_num', 'sum'),
        avg_pnl=('ret_num', 'mean'),
        avg_win=('ret_num', lambda s: s[s > 0].mean()),
        avg_loss=('ret_num', lambda s: s[s < 0].mean())
    )
    dir_grp['win_rate'] = (dir_grp['won'] / dir_grp['total'] * 100).round(1)
    print(dir_grp.to_string())
    
    print("\n=== BY HORIZON ===")
    h_grp = resolved_df.groupby('horizon').agg(
        total=('signal_id', 'count'),
        won=('outcome_label', lambda s: s.str.contains('WON').sum()),
        lost=('outcome_label', lambda s: s.str.contains('LOST').sum()),
        sum_pnl=('ret_num', 'sum'),
        avg_pnl=('ret_num', 'mean'),
        avg_win=('ret_num', lambda s: s[s > 0].mean()),
        avg_loss=('ret_num', lambda s: s[s < 0].mean())
    )
    h_grp['win_rate'] = (h_grp['won'] / h_grp['total'] * 100).round(1)
    print(h_grp.to_string())

    print("\n=== LONG SIGNALS DEEP DIVE ===")
    longs = resolved_df[resolved_df['direction'] == 'LONG']
    print(f"Total Longs: {len(longs)}")
    print("Longs by Horizon:")
    long_h = longs.groupby('horizon').agg(
        total=('signal_id', 'count'),
        won=('outcome_label', lambda s: s.str.contains('WON').sum()),
        lost=('outcome_label', lambda s: s.str.contains('LOST').sum()),
        sum_pnl=('ret_num', 'sum'),
        avg_pnl=('ret_num', 'mean'),
        avg_win=('ret_num', lambda s: s[s > 0].mean()),
        avg_loss=('ret_num', lambda s: s[s < 0].mean())
    )
    long_h['win_rate'] = (long_h['won'] / long_h['total'] * 100).round(1)
    print(long_h.to_string())
    
    print("\n=== WORST PERFORMING PATTERNS IN LONGS ===")
    # Check decision types
    dec_grp = longs.groupby('decision').agg(
        total=('signal_id', 'count'),
        won=('outcome_label', lambda s: s.str.contains('WON').sum()),
        lost=('outcome_label', lambda s: s.str.contains('LOST').sum()),
        sum_pnl=('ret_num', 'sum'),
        avg_pnl=('ret_num', 'mean')
    )
    dec_grp['win_rate'] = (dec_grp['won'] / dec_grp['total'] * 100).round(1)
    print(dec_grp.to_string())
