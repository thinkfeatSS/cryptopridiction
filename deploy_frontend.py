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

run("cd /root/crypto && git pull origin main")
run("cd /root/crypto && docker compose build frontend && docker compose up -d frontend")
run("curl -s -o /dev/null -w 'Frontend HTTP: %{http_code}\n' http://127.0.0.1:3005")

ssh.close()
