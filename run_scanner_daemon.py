import os
import sys
import time
import traceback
from datetime import datetime, timezone

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from test import HybridQuantEngine, CONFIG
from app.services.db_sync import migrate_files_to_db, sync_files_to_db_live

def run_daemon():
    interval_seconds = int(os.getenv("SCAN_INTERVAL_SECONDS", "900"))  # Default: 15 minutes (900s)
    if os.getenv("SCAN_INTERVAL_MINUTES"):
        interval_seconds = int(os.getenv("SCAN_INTERVAL_MINUTES")) * 60
    
    run_once = os.getenv("RUN_ONCE", "false").lower() in ("true", "1", "yes")
    scan_top_n = int(os.getenv("SCANNER_TOP_N", str(CONFIG.get("scanner_top_n", 100))))
    CONFIG["scanner_top_n"] = scan_top_n

    print("=" * 80)
    print("🚀 QUANTITATIVE 8-HORIZON CRYPTO PREDICTION SCANNER DAEMON")
    print(f"📊 Top Coins Scanning Universe: {scan_top_n} Coins")
    print(f"⏱️  Scan Frequency: Every {interval_seconds} seconds ({interval_seconds // 60} minutes)")
    print(f"📁 Export Directory: {os.path.abspath(CONFIG.get('app_export_dir', 'export_app_data'))}")
    print("=" * 80)

    scan_cycle = 1

    while True:
        cycle_start = time.time()
        start_utc_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"\n[SCANNER CYCLE #{scan_cycle}] Starting full market scan at {start_utc_str}...")

        try:
            # Instantiate engine and execute 8-horizon multi-coin scan
            engine = HybridQuantEngine(CONFIG)
            engine.run()

            # Trigger live database synchronization immediately
            print(f"[SCANNER CYCLE #{scan_cycle}] Syncing exported data with database...")
            sync_files_to_db_live(force=True)
            print(f"[SCANNER CYCLE #{scan_cycle}] Market scan & DB sync completed successfully! ✅")

        except Exception as e:
            print(f"[SCANNER CYCLE #{scan_cycle} ERROR ❌] Exception during market scan: {e}")
            traceback.print_exc()

        elapsed = time.time() - cycle_start
        print(f"[SCANNER CYCLE #{scan_cycle}] Elapsed time: {elapsed:.2f}s")

        if run_once:
            print("[SCANNER] RUN_ONCE is enabled. Exiting.")
            break

        # Calculate sleep time
        sleep_time = max(10, interval_seconds - elapsed)
        next_scan_time = datetime.now(timezone.utc).timestamp() + sleep_time
        next_scan_str = datetime.fromtimestamp(next_scan_time, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"[SCANNER] Next automated scan scheduled at: {next_scan_str} (sleeping for {sleep_time:.1f}s)...")

        scan_cycle += 1
        time.sleep(sleep_time)

if __name__ == "__main__":
    run_daemon()
