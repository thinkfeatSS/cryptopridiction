import os
import sys
import time
import traceback
from datetime import datetime, timezone

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from test import HybridQuantEngine, CONFIG

try:
    from app.services.db_sync import migrate_files_to_db, sync_files_to_db_live
    HAS_DB_SYNC = True
except ImportError:
    HAS_DB_SYNC = False

try:
    from app.services.model_retrainer import check_and_trigger_async
    HAS_MODEL_RETRAINER = True
except ImportError:
    HAS_MODEL_RETRAINER = False

def run_daemon():
    interval_seconds = int(os.getenv("SCAN_INTERVAL_SECONDS", "900"))  # Default: 15 minutes (900s)
    if os.getenv("SCAN_INTERVAL_MINUTES"):
        interval_seconds = int(os.getenv("SCAN_INTERVAL_MINUTES")) * 60
    
    run_once = os.getenv("RUN_ONCE", "false").lower() in ("true", "1", "yes")
    scan_top_n = int(os.getenv("SCANNER_TOP_N", str(CONFIG.get("scanner_top_n", 100))))
    CONFIG["scanner_top_n"] = scan_top_n
    CONFIG["continuous_loop"] = False

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

        engine = None
        try:
            # Instantiate engine and execute 8-horizon multi-coin scan
            engine = HybridQuantEngine(CONFIG)
            engine.run_single_iteration()

            # Trigger live database synchronization immediately
            if HAS_DB_SYNC:
                print(f"[SCANNER CYCLE #{scan_cycle}] Syncing exported data with database...")
                sync_files_to_db_live(force=True)
                print(f"[SCANNER CYCLE #{scan_cycle}] Market scan & DB sync completed successfully! ✅")

            # Automated Model Retraining Trigger: Checks if >= 5 newly resolved signals available
            if HAS_MODEL_RETRAINER:
                print(f"[SCANNER CYCLE #{scan_cycle}] Checking automated model retraining threshold...")
                check_and_trigger_async(force=False, min_new_samples=5)

        except Exception as e:
            print(f"[SCANNER CYCLE #{scan_cycle} ERROR ❌] Exception during market scan: {e}")
            traceback.print_exc()

        elapsed = time.time() - cycle_start
        print(f"[SCANNER CYCLE #{scan_cycle}] Scan execution completed in {elapsed:.2f}s")

        if run_once:
            print("[SCANNER] RUN_ONCE is enabled. Exiting.")
            break

        # Calculate sleep time until next 15m candle boundary
        sleep_time = max(10, interval_seconds - elapsed)
        next_scan_time = datetime.now(timezone.utc).timestamp() + sleep_time
        next_scan_str = datetime.fromtimestamp(next_scan_time, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"[SCANNER] Next full scan scheduled at: {next_scan_str} (monitoring active trades every 10s)...")

        end_sleep_ts = time.time() + sleep_time
        while time.time() < end_sleep_ts:
            if engine is not None:
                try:
                    engine.check_open_positions_heartbeat()
                except Exception:
                    pass
            time.sleep(min(10, max(1, end_sleep_ts - time.time())))

        scan_cycle += 1

if __name__ == "__main__":
    run_daemon()
