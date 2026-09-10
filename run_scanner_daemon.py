import os
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from test import HybridQuantEngine, CONFIG, trim_process_memory

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
    scan_top_n = int(os.getenv("SCANNER_TOP_N", str(CONFIG.get("scanner_top_n", 150))))
    heartbeat_secs = int(os.getenv("HEARTBEAT_SECONDS", str(CONFIG.get("heartbeat_interval_seconds", 4))))
    CONFIG["scanner_top_n"] = scan_top_n
    CONFIG["continuous_loop"] = False

    print("=" * 80)
    print("🚀 QUANTITATIVE 8-HORIZON CRYPTO PREDICTION SCANNER DAEMON")
    print(f"📊 Top Coins Scanning Universe: {scan_top_n} Coins")
    print(f"⏱️  Scan Frequency: Every {interval_seconds} seconds ({interval_seconds // 60} minutes)")
    print(f"💓 Live Position Heartbeat: Every {heartbeat_secs} seconds")
    print(f"📁 Export Directory: {os.path.abspath(CONFIG.get('app_export_dir', 'export_app_data'))}")
    print("=" * 80)

    # Initialize Engine once outside loop so self.model_cache persists across cycles
    print("[SCANNER DAEMON 🧠] Initializing HybridQuantEngine & warming model cache...")
    engine = HybridQuantEngine(CONFIG)

    scan_cycle = 1

    while True:
        cycle_start = time.time()
        start_utc_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"\n[SCANNER CYCLE #{scan_cycle}] Starting full market scan at {start_utc_str}...")

        try:
            # Execute 8-horizon multi-coin scan (reusing warm model cache)
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

            # OS Memory Guard: Reclaim heap arenas back to operating system
            trim_process_memory()

        except Exception as e:
            print(f"[SCANNER CYCLE #{scan_cycle} ERROR ❌] Exception during market scan: {e}")
            traceback.print_exc()

        elapsed = time.time() - cycle_start
        print(f"[SCANNER CYCLE #{scan_cycle}] Scan execution completed in {elapsed:.2f}s")

        if run_once:
            print("[SCANNER] RUN_ONCE is enabled. Exiting.")
            break

        # Exact Zero-Drift 15M Candle Boundary Alignment (:00:02, :15:02, :30:02, :45:02 UTC)
        now_cycle = datetime.now(timezone.utc)
        mins_past = now_cycle.minute % 15
        secs_to_boundary = ((15 - mins_past) * 60) - now_cycle.second + 2
        if secs_to_boundary <= 10:
            secs_to_boundary += 900
        next_scan_dt = now_cycle + timedelta(seconds=secs_to_boundary)
        next_scan_ts = int(next_scan_dt.timestamp())
        next_scan_str = next_scan_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"[SCANNER] Next full scan scheduled at: {next_scan_str} (in {secs_to_boundary}s, monitoring active trades every {heartbeat_secs}s)...")

        end_sleep_ts = next_scan_ts
        last_signal_eval_ts = 0.0

        while time.time() < end_sleep_ts:
            try:
                # 1. Real-time paper trading orderbook & wick fills
                engine.check_open_positions_heartbeat()

                # 2. Real-time audit tracker evaluation for pending signals
                if time.time() - last_signal_eval_ts >= 15.0:
                    engine.signal_tracker.evaluate_signals({})
                    last_signal_eval_ts = time.time()
                    if HAS_DB_SYNC:
                        sync_files_to_db_live(force=False)
            except Exception:
                pass
            time.sleep(min(heartbeat_secs, max(1, end_sleep_ts - time.time())))

        scan_cycle += 1

if __name__ == "__main__":
    run_daemon()
