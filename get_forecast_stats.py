import paramiko
import json

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("187.52.116.72", username="root", password="bCSy+h7kMuo.f+6h", timeout=15)

def run(cmd):
    print(f"\n[RUN] {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out: print(out)
    if err: print("STDERR:\n" + err)
    return out

run("docker logs --tail 20 crypto_scanner")

# Fetch forecast via python inside docker or curl
out = run("curl -s http://127.0.0.1:8005/api/forecast")
try:
    data = json.loads(out)
    print("\n--- FORECAST STATS ---")
    print("Timestamp:", data.get("timestamp"))
    print("Scanner Leaderboard Count:", len(data.get("scanner_leaderboard", [])))
    print("Top Round Signals Count:", len(data.get("top_round_signals", [])))
    print("First 5 coins in leaderboard:", [x.get("symbol") for x in data.get("scanner_leaderboard", [])[:5]])
except Exception as e:
    print("Error parsing forecast JSON:", e)

ssh.close()
