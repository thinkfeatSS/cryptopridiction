import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("187.52.116.72", username="root", password="bCSy+h7kMuo.f+6h", timeout=15)

def run(cmd):
    print(f"\n[RUN] {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode().strip()
    if out: print(out)
    return out

run("curl -s -o /dev/null -w 'Status: %{http_code}\n' http://127.0.0.1:8005/api/status")
run("curl -s -o /dev/null -w 'Portfolio: %{http_code}\n' http://127.0.0.1:8005/api/portfolio")
run("curl -s -o /dev/null -w 'Signals KPI: %{http_code}\n' http://127.0.0.1:8005/api/signals/kpi")
run("curl -s -o /dev/null -w 'Frontend 3005: %{http_code}\n' http://127.0.0.1:3005")

ssh.close()
