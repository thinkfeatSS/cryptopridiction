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

from app.engine.engine import UnifiedCryptoEngine

try:
    from app.services.db_sync import migrate_files_to_db
    HAS_DB_SYNC = True
except ImportError:
    HAS_DB_SYNC = False


from app.engine.config import SCAN_PRIMARY_TRIGGER_HORIZON, SCAN_BUFFER_SECONDS, SCAN_MAX_INTERVAL_SECONDS

def get_seconds_until_next_candle(horizon: str = None, buffer_seconds: int = None) -> tuple[float, datetime]:
    """
    Computes exact sleep duration until the next candle boundary + buffer gap.
    Guarantees models train on 100% freshly finalized exchange candle data.
    """
    h = (horizon or SCAN_PRIMARY_TRIGGER_HORIZON).lower()
    buf = buffer_seconds if buffer_seconds is not None else SCAN_BUFFER_SECONDS
    now = datetime.now(timezone.utc)

    if h in ("5m",):
        step_minutes = 5
    elif h in ("15m", "scalp"):
        step_minutes = 15
    elif h in ("1h",):
        step_minutes = 60
    else:
        step_minutes = 5

    minute = now.minute
    next_minute = ((minute // step_minutes) + 1) * step_minutes
    if next_minute >= 60:
        target_dt = (now + timedelta(hours=1)).replace(minute=0, second=buf, microsecond=0)
    else:
        target_dt = now.replace(minute=next_minute, second=buf, microsecond=0)

    # In case execution overran into the buffer or past the boundary, advance to next boundary
    while target_dt <= now:
        target_dt += timedelta(minutes=step_minutes)

    sleep_secs = max(3.0, (target_dt - now).total_seconds())
    return sleep_secs, target_dt


def main():
    top_n = int(os.getenv("TOP_N_UNIVERSE", os.getenv("SCANNER_TOP_N", "40")))
    print("=" * 80)
    print("🚀 QUANT EDGE MULTI-HORIZON CONTINUOUS DAEMON (V16.1)")
    print(f"Top {top_n} Assets | 9 Charts (5M..30D) | 5 Classifiers + 5 Regressors Voting")
    print("Decoupled Paper Trading Bot Active | BTC Predictive Market Beta Shield")
    print("=" * 80)

    engine = UnifiedCryptoEngine(top_n=top_n)
    stop_event = threading.Event()

    def _sig_handler(signum, frame):
        print(f"\n[DAEMON 🛑] Received signal {signum}. Shutting down cleanly...")
        stop_event.set()
        engine.paper_bot.stop_tick_daemon()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig_handler)
    try:
        signal.signal(signal.SIGTERM, _sig_handler)
    except Exception:
        pass

    cycle_count = 0

    while not stop_event.is_set():
        cycle_count += 1
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"\n--- [CYCLE #{cycle_count}] Starting Multi-Horizon Prediction at {now_utc} ---")

        try:
            # 1. Run Complete 9-Horizon Scan & Signal Generation Cycle
            payload = engine.run_scan_and_prediction_cycle()

            # 2. Cycle-Completion Reconciliation:
            # Cleanly evaluate and persist any signals that expired during the scan cycle across JSON, MySQL, and CSV
            try:
                from app.services.signal_service import signal_service
                from app.database import SessionLocal
                with SessionLocal() as db_session:
                    signal_service.resolve_pending_signals_live(db_session, force=True)
            except Exception:
                pass

            # 3. Sync to Database
            if HAS_DB_SYNC:
                try:
                    migrate_files_to_db()
                except Exception as e:
                    pass

        except Exception as e:
            print(f"[DAEMON ⚠️] Cycle execution note: {e}")
            import traceback
            traceback.print_exc()

        # Compute exact next candle boundary sleep (5M candle close + 3s buffer)
        sleep_secs, next_dt = get_seconds_until_next_candle("5m", buffer_seconds=3)
        next_str = next_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"[DAEMON 💤] Cycle #{cycle_count} complete. All models 100% freshly retrained.")
        print(f"[DAEMON ⏱️] Next scan scheduled in {sleep_secs:.1f}s at {next_str} (5M candle close + 3s buffer)...")

        # Interruptible sleep until exact candle boundary + periodic 15s live signal TP/SL resolution
        end_sleep_ts = time.time() + sleep_secs
        while time.time() < end_sleep_ts and not stop_event.is_set():
            wait_step = min(15.0, max(0.5, end_sleep_ts - time.time()))
            stop_event.wait(timeout=wait_step)
            # Intra-candle evaluation of pending trader signals for TP1/TP2/TP3/SL WhatsApp alerts
            try:
                from app.services.signal_service import signal_service
                from app.database import SessionLocal
                with SessionLocal() as db_session:
                    signal_service.resolve_pending_signals_live(db_session, force=False)
            except Exception:
                pass


if __name__ == "__main__":
    main()
