import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('187.52.116.72', username='root', password='bCSy+h7kMuo.f+6h', timeout=10)

stdin, stdout, stderr = ssh.exec_command('docker logs crypto_scanner --tail 50')
print(stdout.read().decode('utf-8', errors='ignore'))
ssh.close()
