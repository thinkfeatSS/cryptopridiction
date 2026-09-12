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

run("cd /root/crypto && docker compose up -d backend scanner")
run("sleep 3")
run("docker ps")
run("docker exec crypto_backend python3 -c 'from app.services.db_sync import init_db; init_db()'")
run("curl -s http://127.0.0.1:8005/api/status")

ssh.close()
