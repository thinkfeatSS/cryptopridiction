import paramiko
import json

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('187.52.116.72', username='root', password='bCSy+h7kMuo.f+6h', timeout=10)

def run(cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd)
    return stdout.read().decode('utf-8', errors='ignore')

print("--- Active Institutional Signals File ---")
print(run("docker exec crypto_scanner python3 -c \"import json, os; print(os.path.exists('/app/export_app_data/active_institutional_signals.json'))\""))

print("--- Signals in JSON ---")
script = """
import json, os
p = '/app/export_app_data/active_institutional_signals.json'
if os.path.exists(p):
    with open(p) as f:
        data = json.load(f)
    print(f'Total signals: {len(data)}')
    for d in data:
        print(f\"{d.get('symbol')} | {d.get('horizon_tag')} | {d.get('direction')} | {d.get('status')} | Entry: {d.get('entry_price')} | TP1: {d.get('tp1_price')} | SL: {d.get('sl_price')}\")
else:
    print('File not found')
"""
print(run(f"docker exec crypto_scanner python3 -c \"{script}\""))

print("--- Live Market Forecast signals_by_horizon ---")
script2 = """
import json
p = '/app/export_app_data/live_market_forecast.json'
with open(p) as f:
    d = json.load(f)
print('top_round_signals count:', len(d.get('top_round_signals', [])))
sbh = d.get('signals_by_horizon', {})
for k, v in sbh.items():
    print(f'Horizon {k}: {len(v)} signals')
"""
print(run(f"docker exec crypto_scanner python3 -c \"{script2}\""))

ssh.close()
