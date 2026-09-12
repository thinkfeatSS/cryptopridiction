import paramiko
import pandas as pd
import io

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("187.52.116.72", username="root", password="bCSy+h7kMuo.f+6h", timeout=15)

# Download signals_tracker_history.csv or query db
stdin, stdout, stderr = ssh.exec_command("cat /root/crypto/export_app_data/signals_tracker_history.csv")
csv_data = stdout.read().decode('utf-8', errors='ignore')
ssh.close()

if csv_data:
    df = pd.read_csv(io.StringIO(csv_data))
    print(f"Loaded {len(df)} records from VPS CSV")
    
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
