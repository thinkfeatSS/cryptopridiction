import os
import sys
import warnings

# Suppress serialization & version warnings from pre-trained sklearn / xgboost bundles
try:
    from sklearn.exceptions import InconsistentVersionWarning
    warnings.filterwarnings("ignore", category=InconsistentVersionWarning)
except ImportError:
    pass
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*InconsistentVersionWarning.*")
warnings.filterwarnings("ignore", message=".*Trying to unpickle estimator.*")
warnings.filterwarnings("ignore", message=".*If you are loading a serialized model.*")

# Critical: Prevent OpenMP / BLAS threading deadlocks when called after multithreading
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import time
import traceback
import signal
import threading
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from test import HybridQuantEngine, CONFIG, trim_process_memory

try:
    from app.services.db_sync import migrate_files_to_db, sync_files_to_db_live
    HAS_DB_SYNC = True
except ImportError:
    HAS_DB_SYNC = False

try:
    from app.services.model_retrainer import check_and_trigger_async, purge_legacy_meta_models
    HAS_MODEL_RETRAINER = True
except ImportError:
    HAS_MODEL_RETRAINER = False
    purge_legacy_meta_models = lambda: {}


def get_seconds_until_next_candle(horizon: str = "15m", buffer_seconds: int = 2) -> tuple[float, datetime]:
    """
    Computes exact sleep duration until the next candle boundary + buffer gap.
    Guarantees models train on newly closed candle data.
    - 15m: boundaries at :00, :15, :30, :45 UTC
    - 1h: boundary at :00 UTC
    - 1d / 24h: boundary at 00:00 UTC
    """
    now = datetime.now(timezone.utc)
    h = horizon.lower()
    if h in ("15m", "scalp"):
        minute = now.minute
        if minute % 15 == 0 and now.second < buffer_seconds:
            target_dt = now.replace(second=buffer_seconds, microsecond=0)
        else:
            next_minute = ((minute // 15) + 1) * 15
            if next_minute >= 60:
                target_dt = (now + timedelta(hours=1)).replace(minute=0, second=buffer_seconds, microsecond=0)
            else:
                target_dt = now.replace(minute=next_minute, second=buffer_seconds, microsecond=0)
    elif h in ("1h", "day", "intraday"):
        if now.minute == 0 and now.second < buffer_seconds:
            target_dt = now.replace(second=buffer_seconds, microsecond=0)
        else:
            target_dt = (now + timedelta(hours=1)).replace(minute=0, second=buffer_seconds, microsecond=0)
    elif h in ("1d", "24h", "swing", "macro"):
        if now.hour == 0 and now.minute == 0 and now.second < buffer_seconds:
            target_dt = now.replace(second=buffer_seconds, microsecond=0)
        else:
            target_dt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=buffer_seconds, microsecond=0)
    else:
        next_minute = ((now.minute // 15) + 1) * 15
        if next_minute >= 60:
            target_dt = (now + timedelta(hours=1)).replace(minute=0, second=buffer_seconds, microsecond=0)
        else:
            target_dt = now.replace(minute=next_minute, second=buffer_seconds, microsecond=0)

    sleep_secs = max(0.5, (target_dt - now).total_seconds())
    return sleep_secs, target_dt


class CycleWatchdog:
    """
    Cross-platform watchdog timer.
    Uses signal.alarm on Linux/POSIX main thread, and threading.Timer fallback on Windows/other platforms.
    Guarantees that a hanging market scan cycle never halts the daemon permanently.
    """
    def __init__(self, timeout_secs: int = 240):
        self.timeout_secs = timeout_secs
        self._timer = None
        self._use_signal = hasattr(signal, "alarm") and hasattr(signal, "SIGALRM")

    def start(self):
        if self._use_signal:
            def _handle_timeout(signum, frame):
                print(f"[WATCHDOG 🚨] Hard timeout reached ({self.timeout_secs}s)! Forcing cycle recovery...", flush=True)
                raise TimeoutError(f"Scan iteration timed out after {self.timeout_secs} seconds! Watchdog reset triggered.")
            signal.signal(signal.SIGALRM, _handle_timeout)
            signal.alarm(self.timeout_secs)
        else:
            def _timer_fire():
                print(f"[WATCHDOG 🚨] Hard timeout warning: scan cycle running > {self.timeout_secs}s!", flush=True)
            self._timer = threading.Timer(self.timeout_secs, _timer_fire)
            self._timer.daemon = True
            self._timer.start()

    def cancel(self):
        if self._use_signal:
            try:
                signal.alarm(0)
            except Exception:
                pass
        if self._timer:
            try:
                self._timer.cancel()
            except Exception:
                pass
            self._timer = None


def start_heartbeat_worker(engine, heartbeat_secs: int = 4, stop_event: threading.Event = None) -> tuple[threading.Thread, threading.Event]:
    """
    Decoupled 24/7 Position Monitoring Heartbeat Worker:
    Continuously executes intra-candle target/stop checks, Tier-0 Breakeven ratchets,
    and BTC Market Beta Shield evaluations in an independent background daemon thread.
    Crucially: NEVER starved or delayed by heavy machine learning model retraining!
    """
    if stop_event is None:
        stop_event = threading.Event()

    def _worker():
        print(f"[HEARTBEAT 💓] Decoupled 24/7 position monitoring worker running every {heartbeat_secs}s", flush=True)
        last_eval_ts = 0.0
        while not stop_event.is_set():
            try:
                # 1. Fast real-time orderbook & wick fill checking + BTC Shield
                engine.check_open_positions_heartbeat()

                # 2. Real-time audit tracker evaluation every 15s
                now_t = time.time()
                if (now_t - last_eval_ts) >= 15.0:
                    try:
                        from app.services.signal_service import fetch_live_binance_prices
                        live_p = fetch_live_binance_prices()
                    except Exception:
                        live_p = getattr(engine, "live_prices", {})
                    engine.signal_tracker.evaluate_signals(live_p or {})
                    last_eval_ts = now_t
                    if HAS_DB_SYNC:
                        try:
                            sync_files_to_db_live(force=False)
                        except Exception:
                            pass
            except Exception:
                pass

            stop_event.wait(timeout=heartbeat_secs)

    t = threading.Thread(target=_worker, name="DecoupledPositionHeartbeatThread", daemon=True)
    t.start()
    return t, stop_event


def run_daemon():
    top_n = int(os.getenv("TOP_N_UNIVERSE", os.getenv("SCANNER_TOP_N", "100")))
    use_modular = os.getenv("USE_MODULAR_ENGINE", "true").lower() in ("true", "1", "yes")
    if use_modular:
        print(f"[SCANNER DAEMON 🚀] Launching Modular Multi-Horizon V16.1 Engine (Top {top_n} Assets x 9 Charts)...")
        from run_modular_daemon import main as run_modular_main
        run_modular_main()
        return

    sync_to_candle = os.getenv("SYNC_TO_CANDLE_CLOSE", "true").lower() in ("true", "1", "yes")
    candle_horizon = os.getenv("CANDLE_HORIZON", "15m")
    candle_gap_secs = int(os.getenv("CANDLE_GAP_SECONDS", "2"))
    force_fresh_training = os.getenv("FORCE_FRESH_TRAINING", "true").lower() in ("true", "1", "yes")

    interval_seconds = int(os.getenv("SCAN_INTERVAL_SECONDS", "60"))
    if os.getenv("SCAN_INTERVAL_MINUTES"):
        interval_seconds = int(os.getenv("SCAN_INTERVAL_MINUTES")) * 60

    run_once = os.getenv("RUN_ONCE", "false").lower() in ("true", "1", "yes")
    scan_top_n = int(os.getenv("SCANNER_TOP_N", str(CONFIG.get("scanner_top_n", 100))))
    max_workers = int(os.getenv("MAX_SCAN_WORKERS", str(CONFIG.get("max_scan_workers", 16))))
    heartbeat_secs = int(os.getenv("HEARTBEAT_SECONDS", str(CONFIG.get("heartbeat_interval_seconds", 4))))

    CONFIG["scanner_top_n"] = scan_top_n
    CONFIG["max_scan_workers"] = max_workers
    CONFIG["continuous_loop"] = False
    CONFIG["force_fresh_training_on_scan"] = force_fresh_training
    CONFIG["sync_to_candle_close"] = sync_to_candle
    CONFIG["candle_close_gap_seconds"] = candle_gap_secs

    print("=" * 88)
    print(f"🚀 QUANTITATIVE JIT CANDLE-SYNCHRONIZED RETRAINING SCANNER DAEMON")
    print(f"📊 Scanning Universe: Top {scan_top_n} Coins (Parallel Workers: {max_workers})")
    if sync_to_candle:
        print(f"⏱️  Scan Mode: Candle-Synchronized ({candle_horizon.upper()} close + {candle_gap_secs}s buffer)")
    else:
        print(f"⏱️  Scan Mode: Rolling Interval ({interval_seconds}s cycle)")
    print(f"🧠 Fresh Retraining: {'100% Zero-Cache Retraining on Newly Closed Candle' if force_fresh_training else 'Cached Mode'}")
    print(f"💓 Live Position Heartbeat: Decoupled 24/7 background worker ({heartbeat_secs}s interval)")
    print(f"📁 Export Directory: {os.path.abspath(CONFIG.get('app_export_dir', 'export_app_data'))}")
    print("=" * 88)

    # Initialize Engine
    print("[SCANNER DAEMON 🧠] Initializing HybridQuantEngine...")
    engine = HybridQuantEngine(CONFIG)

    # Disk Cleanliness Guard: Automatically purge any retired legacy meta-models from disk
    try:
        purge_legacy_meta_models()
    except Exception as e_purge:
        print(f"[SCANNER DAEMON ⚠️] Disk cleanup notice: {e_purge}")

    # Seed StrategyRegistry from authoritative trader signals tracker
    try:
        from app.quant_v16.strategies import StrategyRegistry
        strat_reg = StrategyRegistry()
        seeded = strat_reg.seed_from_tracker_csv()
        if seeded:
            print("[SCANNER DAEMON 📊] Successfully seeded StrategyRegistry priors & kill switches from trader_signals_tracker.csv.")
    except Exception as seed_err:
        print(f"[SCANNER DAEMON ⚠️] Could not seed StrategyRegistry: {seed_err}")

    # In production, Docker Compose brings up active exchange WebSocket feeds concurrently
    try:
        from app.database import is_test_environment
        ws_enabled = os.getenv("WEBSOCKET_FEED_ENABLED", "true").lower() in ("true", "1", "yes")
        if ws_enabled and (not is_test_environment() or os.environ.get("WS_TEST_CONNECT") == "1"):
            from app.engine.scanner.websocket_feed import ws_feed_manager
            ws_feed_manager.start()
            print("[SCANNER DAEMON ⚡] Concurrent Active Exchange WebSocket Feed Manager started.", flush=True)
        else:
            print("[SCANNER DAEMON ℹ️] Local test environment: Exchange WebSocket feed deferred (falling back to conservative taker-buy volume estimates).", flush=True)
    except Exception as ws_err:
        print(f"[SCANNER DAEMON ⚠️] WebSocket Feed Manager startup notice: {ws_err}", flush=True)

    # Start Decoupled 24/7 Position Heartbeat Thread
    stop_heartbeat_event = threading.Event()
    heartbeat_thread, stop_heartbeat_event = start_heartbeat_worker(engine, heartbeat_secs=heartbeat_secs, stop_event=stop_heartbeat_event)

    scan_cycle = 1

    try:
        while True:
            cycle_start = time.time()
            start_utc_dt = datetime.now(timezone.utc)
            start_utc_str = start_utc_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
            print(f"\n[SCANNER CYCLE #{scan_cycle}] Starting candle-synchronized market scan at {start_utc_str}...")

            watchdog = CycleWatchdog(timeout_secs=240)
            try:
                # Set a 4-minute watchdog to guarantee daemon never hangs indefinitely
                watchdog.start()

                # Execute scan with 100% freshly retrained models on newly closed candle
                engine.run_single_iteration()

                # Clear watchdog
                watchdog.cancel()

                # Trigger live database synchronization immediately
                if HAS_DB_SYNC:
                    print(f"[SCANNER CYCLE #{scan_cycle}] Syncing exported data with database...")
                    sync_files_to_db_live(force=True)
                    print(f"[SCANNER CYCLE #{scan_cycle}] Market scan & DB sync completed successfully! ✅")

                # Automated Model Retraining Trigger: Checks if >= 3 newly resolved signals available
                if HAS_MODEL_RETRAINER:
                    print(f"[SCANNER CYCLE #{scan_cycle}] Checking automated model retraining threshold...")
                    check_and_trigger_async(force=False, min_new_samples=3)

                # OS Memory Guard: Reclaim heap arenas back to operating system
                trim_process_memory()

            except Exception as e:
                watchdog.cancel()
                print(f"[SCANNER CYCLE #{scan_cycle} ERROR ❌] Exception during market scan: {e}")
                traceback.print_exc()

            elapsed = time.time() - cycle_start
            print(f"[SCANNER CYCLE #{scan_cycle}] Scan execution completed in {elapsed:.2f}s")

            if run_once:
                print("[SCANNER] RUN_ONCE is enabled. Exiting.")
                break

            # Calculate next target scan time
            if sync_to_candle:
                sleep_secs, next_scan_dt = get_seconds_until_next_candle(horizon=candle_horizon, buffer_seconds=candle_gap_secs)
                next_scan_str = next_scan_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                print(f"[SCANNER] Next candle scan at: {next_scan_str} (in {int(sleep_secs)}s | {candle_horizon.upper()} candle close + {candle_gap_secs}s buffer)...")
            else:
                sleep_secs = float(interval_seconds)
                next_scan_dt = datetime.now(timezone.utc) + timedelta(seconds=sleep_secs)
                next_scan_str = next_scan_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                print(f"[SCANNER] Next scan at: {next_scan_str} (in {int(sleep_secs)}s)...")

            end_sleep_ts = time.time() + sleep_secs

            while time.time() < end_sleep_ts:
                # Check if market regime or trend shift triggered an immediate rescan & retraining
                if getattr(engine, '_force_rescan_requested', False):
                    engine._force_rescan_requested = False
                    print(f"\n[SCANNER DAEMON ⚡] Market regime/trend shock detected! Breaking sleep to rescan & retrain immediately...", flush=True)
                    break
                time.sleep(min(1.0, max(0.1, end_sleep_ts - time.time())))

            scan_cycle += 1

    finally:
        stop_heartbeat_event.set()
        try:
            from app.engine.scanner.websocket_feed import ws_feed_manager
            ws_feed_manager.stop()
        except Exception:
            pass
        print("[SCANNER DAEMON] Shutdown complete. Heartbeat worker stopped.", flush=True)


if __name__ == "__main__":
    run_daemon()
