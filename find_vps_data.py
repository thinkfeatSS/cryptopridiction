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

run("find /root/crypto -name '*.csv'")
run("docker exec crypto_backend python3 -c 'from app.services.db_sync import engine; from sqlalchemy import text; conn=engine.connect(); res=conn.execute(text(\"SHOW TABLES;\")).fetchall(); print(res)'")
run("docker exec crypto_backend python3 -c 'from app.services.db_sync import engine; from sqlalchemy import text; import pandas as pd; conn=engine.connect(); df=pd.read_sql(\"SELECT * FROM signals_tracker\", conn); print(\"Signals count:\", len(df)); print(df.columns.tolist())'")

ssh.close()
