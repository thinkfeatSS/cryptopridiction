import paramiko
import time

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

# Check mysql status
run("docker ps | grep mysql")

# Run docker compose up
run("cd /root/crypto && git pull origin main && docker compose up -d backend scanner frontend")

time.sleep(5)
run("docker ps")

# Run db init inside backend
run("docker exec crypto_backend python3 -c 'from app.services.db_sync import init_db; init_db()'")

# Check status of endpoints
run("curl -s http://127.0.0.1:8005/api/status")
run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8005/api/portfolio")

# Inspect scanner logs
run("docker logs --tail 30 crypto_scanner")

ssh.close()
