import json

log_path = r'C:\Users\ismail\.gemini\antigravity-ide\brain\b578290f-949c-4b93-9408-f7bcebc69ade\.system_generated\logs\transcript_full.jsonl'
with open(log_path, 'r', encoding='utf-8') as f:
    for line in f:
        if 'SIG_20260901_0737_SUI_USDT_SWING' in line:
            obj = json.loads(line)
            # Find the string inside obj
            def find_str(o):
                if isinstance(o, str) and 'SIG_20260901_0737_SUI_USDT_SWING' in o:
                    return o
                if isinstance(o, dict):
                    for v in o.values():
                        res = find_str(v)
                        if res: return res
                if isinstance(o, list):
                    for v in o:
                        res = find_str(v)
                        if res: return res
                return None
            
            raw_str = find_str(obj)
            if raw_str:
                start = raw_str.find('signal_id,date_utc')
                csv_data = raw_str[start:].strip()
                # Clean if ends with anything trailing
                with open('user_pasted_signals.csv', 'w', encoding='utf-8') as out:
                    out.write(csv_data)
                print("Total extracted lines:", len(csv_data.splitlines()))
                break
