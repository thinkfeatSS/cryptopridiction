import paramiko

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

run("docker logs --tail 30 crypto_scanner")
run("curl -s http://127.0.0.1:8005/api/forecast | jq '{status, symbols_count: (.scanner_leaderboard | length), top_signals_count: (.top_round_signals | length)}'")

ssh.close()
