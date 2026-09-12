import paramiko
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('187.52.116.72', username='root', password='bCSy+h7kMuo.f+6h', timeout=15)

def run(cmd):
    print(f">> {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='ignore')
    err = stderr.read().decode('utf-8', errors='ignore')
    if out:
        print(out.strip())
    if err:
        print("ERR:", err.strip())
    return out

print("1. Pulling latest code on VPS...")
run("cd /root/crypto && git pull origin main")

print("2. Restarting crypto_scanner container...")
run("docker restart crypto_scanner")

print("3. Rebuilding frontend on VPS...")
run("cd /root/crypto/frontend && npm run build")
run("docker restart crypto_frontend")

print("4. Waiting for crypto_scanner to initialize and start scanning...")
time.sleep(15)

run("docker ps --filter 'name=crypto_'")

ssh.close()
