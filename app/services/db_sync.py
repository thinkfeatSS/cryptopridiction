import os
import json
import math
import time
import threading
import pandas as pd
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import engine, SessionLocal, Base, ensure_schema_compatibility
from app.models import SignalAudit, PaperPosition, ClosedTrade, MarketForecast
from app.config import settings
from app.engine.scanner.filters import UniverseFilter

_LAST_SYNC_TIMES = {
    "csv": 0.0,
    "portfolio": 0.0,
    "forecast": 0.0,
}
_LAST_CHECK_TIME = 0.0
_FULL_SCAN_VERSION = 1
_PORTFOLIO_VERSION = 1
_LAST_SCAN_TIMESTAMP = datetime.now(timezone.utc).isoformat()
_CACHED_FORECAST = None
_IS_SCANNING = False

def init_db():
    """Creates all database tables in MySQL / SQLite and applies schema updates."""
    try:
        Base.metadata.create_all(bind=engine)
        ensure_schema_compatibility(engine)
        is_mysql = "mysql" in settings.DATABASE_URL.lower()
        with engine.connect() as conn:
            # Note: Column definitions and types are managed by SQLAlchemy models.
            # Avoid runtime ALTER TABLE on market_forecasts to prevent metadata lock deadlocks.

            # ── paper_positions: add new columns (idempotent) ────────────────
            for _stmt in [
                "ALTER TABLE paper_positions ADD COLUMN execution_engine VARCHAR(64) DEFAULT 'paper'",
                "ALTER TABLE paper_positions ADD COLUMN raw_entry_price DOUBLE",
                "ALTER TABLE paper_positions ADD COLUMN tp1_price DOUBLE",
                "ALTER TABLE paper_positions ADD COLUMN tp2_price DOUBLE",
                "ALTER TABLE paper_positions ADD COLUMN tp3_price DOUBLE",
                "ALTER TABLE paper_positions ADD COLUMN unrealized_gross_pnl_usd DOUBLE DEFAULT 0.0",
                "ALTER TABLE paper_positions ADD COLUMN buy_fee_usd DOUBLE DEFAULT 0.0",
                "ALTER TABLE paper_positions ADD COLUMN est_sell_fee_usd DOUBLE DEFAULT 0.0",
                "ALTER TABLE paper_positions ADD COLUMN unrealized_fee_usd DOUBLE DEFAULT 0.0",
            ]:
                try:
                    conn.execute(text(_stmt))
                    conn.commit()
                except Exception:
                    pass  # Column already exists — harmless

            # ── closed_trades: add new columns (idempotent) ──────────────────
            for _stmt in [
                "ALTER TABLE closed_trades ADD COLUMN execution_engine VARCHAR(64) DEFAULT 'paper'",
                "ALTER TABLE closed_trades ADD COLUMN raw_entry_price DOUBLE",
                "ALTER TABLE closed_trades ADD COLUMN gross_pnl_usd DOUBLE DEFAULT 0.0",
                "ALTER TABLE closed_trades ADD COLUMN buy_fee_usd DOUBLE DEFAULT 0.0",
                "ALTER TABLE closed_trades ADD COLUMN sell_fee_usd DOUBLE DEFAULT 0.0",
                "ALTER TABLE closed_trades ADD COLUMN total_fee_usd DOUBLE DEFAULT 0.0",
                "ALTER TABLE closed_trades ADD COLUMN binance_fee_usd DOUBLE DEFAULT 0.0",
            ]:
                try:
                    conn.execute(text(_stmt))
                    conn.commit()
                except Exception:
                    pass  # Column already exists — harmless
        print("[DATABASE] All database tables verified and created.")
    except Exception as e:
        print(f"[DATABASE ERROR] Table creation error: {e}")

def get_daemon_state():
    """Reads lightweight scanner daemon state file if available with auto-timeout healing."""
    global _IS_SCANNING
    state_file = os.path.join(settings.EXPORT_DIR, "scanner_daemon_state.json")
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                is_sc = bool(data.get("is_scanning", False))
                # Check for stale scanning flag (> 300s without completion)
                if is_sc and "scan_started_at" in data:
                    try:
                        started_dt = datetime.fromisoformat(data["scan_started_at"])
                        elapsed_secs = (datetime.now(timezone.utc) - started_dt).total_seconds()
                        if elapsed_secs > 360:  # If scan started over 6 mins ago, auto-reset stale flag
                            is_sc = False
                            data["is_scanning"] = False
                            data["scan_status"] = "IDLE"
                    except Exception:
                        pass
                _IS_SCANNING = is_sc
                return data
        except Exception:
            pass
    return {"is_scanning": False, "scan_status": "IDLE"}

def get_sync_state():
    """Returns the current full scan version, portfolio version, scanning state, and last scan timestamp."""
    global _FULL_SCAN_VERSION, _PORTFOLIO_VERSION, _LAST_SCAN_TIMESTAMP, _IS_SCANNING
    d_state = get_daemon_state()
    return {
        "scan_version": _FULL_SCAN_VERSION,
        "full_scan_version": _FULL_SCAN_VERSION,
        "portfolio_version": _PORTFOLIO_VERSION,
        "is_scanning": d_state.get("is_scanning", _IS_SCANNING),
        "scan_status": d_state.get("scan_status", "IDLE"),
        "scanned_assets_count": d_state.get("scanned_assets_count", 0),
        "total_assets_count": d_state.get("total_assets_count", 100),
        "last_scan_timestamp": d_state.get("last_scan_completed_at_utc", _LAST_SCAN_TIMESTAMP),
        "last_scan_completed_at": d_state.get("last_scan_completed_at", None),
        "last_scan_duration_seconds": d_state.get("last_scan_duration_seconds", None),
        "next_scan_time_utc": d_state.get("next_scan_time_utc", None),
        "next_scan_timestamp": d_state.get("next_scan_timestamp", None),
        "seconds_to_next_scan": d_state.get("seconds_to_next_scan", None),
    }

def get_cached_forecast():
    """Returns in-memory cached forecast, automatically refreshing if disk file was updated."""
    global _CACHED_FORECAST, _LAST_SYNC_TIMES
    try:
        forecast_json = os.path.join(settings.EXPORT_DIR, "live_market_forecast.json")
        if os.path.exists(forecast_json):
            fmtime = os.path.getmtime(forecast_json)
            if fmtime > _LAST_SYNC_TIMES.get("forecast", 0.0) or _CACHED_FORECAST is None:
                with open(forecast_json, "r", encoding="utf-8") as f:
                    _CACHED_FORECAST = json.load(f)
                _LAST_SYNC_TIMES["forecast"] = fmtime
    except Exception:
        pass
    return _CACHED_FORECAST

def set_cached_forecast(data):
    """Sets in-memory cached forecast."""
    global _CACHED_FORECAST
    _CACHED_FORECAST = data

from app.quant_v16.lock import CrossProcessLock


_SYNC_LOCK = threading.Lock()

def sync_files_to_db_live(force: bool = False) -> bool:
    """
    High-performance live synchronizer:
    Detects if CSV or JSON files have been modified by test.py,
    and updates the database tables using bulk mappings.
    Guarded by thread-level and cross-process non-blocking locks to prevent contention.
    """
    global _LAST_SYNC_TIMES, _LAST_CHECK_TIME, _FULL_SCAN_VERSION, _PORTFOLIO_VERSION, _LAST_SCAN_TIMESTAMP, _CACHED_FORECAST
    
    if not _SYNC_LOCK.acquire(blocking=False):
        # Another thread in this process is actively executing; skip without blocking
        return False

    proc_lock = CrossProcessLock(os.path.join(settings.EXPORT_DIR, ".db_sync.lock"))
    if not proc_lock.acquire():
        _SYNC_LOCK.release()
        return False

    try:
        now_ts = time.time()
        
        # Cooldown check (skip disk stats if checked less than 2.0s ago unless forced)
        if not force and (now_ts - _LAST_CHECK_TIME) < 2.0:
            return False
        _LAST_CHECK_TIME = now_ts

        export_dir = settings.EXPORT_DIR
        signals_csv = os.path.join(export_dir, "trader_signals_tracker.csv")
        portfolio_json = os.path.join(export_dir, "paper_trading_ledger.json")
        forecast_json = os.path.join(export_dir, "live_market_forecast.json")

        portfolio_changed = False
        forecast_changed = False

        csv_mtime = os.path.getmtime(signals_csv) if os.path.exists(signals_csv) else 0.0
        portfolio_mtime = os.path.getmtime(portfolio_json) if os.path.exists(portfolio_json) else 0.0
        forecast_mtime = os.path.getmtime(forecast_json) if os.path.exists(forecast_json) else 0.0

        if not force and csv_mtime <= _LAST_SYNC_TIMES["csv"] and portfolio_mtime <= _LAST_SYNC_TIMES["portfolio"] and forecast_mtime <= _LAST_SYNC_TIMES["forecast"]:
            return False

        db: Session = SessionLocal()
        try:
            # 1. Sync Signals Tracker CSV (Insert new + update existing outcomes & returns)
            if os.path.exists(signals_csv) and (force or csv_mtime > _LAST_SYNC_TIMES["csv"]):
                for attempt in range(3):
                    try:
                        df = pd.read_csv(signals_csv, keep_default_na=False).fillna("")
                        records = df.to_dict(orient="records")
                        
                        # Ensure every unresolved signal in DB or CSV is eligible for outcome resolution,
                        # combined with the latest 300 records for fast new-signal ingestion.
                        if not force and len(records) > 300:
                            recent_records = records[-300:]
                            recent_ids = {str(r.get("signal_id", "")).strip() for r in recent_records if str(r.get("signal_id", "")).strip()}
                            
                            try:
                                unresolved_statuses = [
                                    "PENDING", "PENDING_EVALUATION", "ACTIVE", "PENDING_LIMIT",
                                    "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"
                                ]
                                unresolved_db_rows = db.query(SignalAudit.signal_id).filter(
                                    SignalAudit.status.in_(unresolved_statuses)
                                ).all()
                                unresolved_db_ids = {str(row[0]).strip() for row in unresolved_db_rows if row[0]}
                            except Exception:
                                unresolved_db_ids = set()

                            older_eligible = []
                            for r in records[:-300]:
                                sig_id = str(r.get("signal_id", "")).strip()
                                if not sig_id or sig_id in recent_ids:
                                    continue
                                st_val = str(r.get("status", "")).strip().upper()
                                out_val = str(r.get("outcome_label", "")).strip().upper()
                                is_pending_csv = (
                                    st_val in [
                                        "PENDING", "PENDING_EVALUATION", "ACTIVE", "PENDING_LIMIT",
                                        "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"
                                    ]
                                    or "PENDING" in out_val
                                    or "ACTIVE" in out_val
                                )
                                if sig_id in unresolved_db_ids or is_pending_csv:
                                    older_eligible.append(r)

                            records_to_process = older_eligible + recent_records
                        else:
                            records_to_process = records

                        # Forecast Bridge Guard: Ensure active trade signals displayed in live_market_forecast.json
                        # are never omitted from the SignalAudit ledger or CSV tracker
                        now_utc = datetime.now(timezone.utc)
                        if os.path.exists(forecast_json):
                            try:
                                with open(forecast_json, "r", encoding="utf-8") as ff:
                                    f_json = json.load(ff)
                                raw_active_sigs = list(
                                    f_json.get("active_institutional_signals")
                                    or f_json.get("top_round_signals")
                                    or []
                                )
                                sigs_by_hz = f_json.get("signals_by_horizon", {})
                                if isinstance(sigs_by_hz, dict):
                                    for hz_key in ["15M", "1H", "24H"]:
                                        for h_sig in sigs_by_hz.get(hz_key, []):
                                            raw_active_sigs.append(h_sig)

                                existing_proc_ids = {str(r.get("signal_id", "")).strip() for r in records_to_process}
                                existing_active_pairs = {
                                    (str(r.get("symbol", "")).strip().upper(), str(r.get("horizon", "")).strip().upper())
                                    for r in records_to_process
                                    if str(r.get("status", "")).strip().upper() in ["PENDING", "PENDING_EVALUATION", "ACTIVE", "TIER0_PROTECTED_BREAKEVEN"]
                                }
                                extra_rows_for_csv = []
                                for fs in raw_active_sigs:
                                    if not fs or not isinstance(fs, dict):
                                        continue
                                    if not fs.get("is_trade_active"):
                                        continue
                                    fs_sym = str(fs.get("symbol", "")).strip().upper()
                                    if not fs_sym or not UniverseFilter.is_valid_crypto_pair(fs_sym):
                                        continue
                                    fs_hz = str(fs.get("dominant_timeframe") or fs.get("horizon") or "15M").upper()
                                    norm_hz = "15M" if "15" in fs_hz else ("24H" if ("24" in fs_hz or "1D" in fs_hz) else "1H")
                                    
                                    # Anti-Duplication: Do not re-log if an active/pending signal already exists for this pair & horizon
                                    if (fs_sym, norm_hz) in existing_active_pairs:
                                        continue

                                    sym_clean = fs_sym.replace("/", "").replace("-", "")
                                    fs_sig_id = str(fs.get("signal_id") or "").strip()
                                    if not fs_sig_id:
                                        fs_sig_id = f"SIG_{now_utc.strftime('%Y%m%d_%H%M')}_{sym_clean}_{norm_hz}"
                                    if fs_sig_id in existing_proc_ids:
                                        continue

                                    fs_dir = str(fs.get("dominant_direction") or fs.get("direction") or "LONG").upper()
                                    entry_p = fs.get("entry_price") or fs.get("current_price") or 0.0
                                    tp1_p = fs.get("tp1_price") or entry_p
                                    tp2_p = fs.get("tp2_price") or tp1_p
                                    tp3_p = fs.get("tp3_price") or tp2_p
                                    sl_p = fs.get("sl_price") or entry_p
                                    q_grade = str(fs.get("quality_grade") or "Grade A")
                                    clean_g = "Grade A+" if "A+" in q_grade else ("Grade A" if "Grade A" in q_grade else "Grade B")
                                    tier_n = 1 if "A+" in q_grade else (2 if "Grade A" in q_grade else 3)

                                    row_bridge = {
                                        "signal_id": fs_sig_id,
                                        "trade_thesis_id": f"THESIS-{sym_clean}-{fs_dir[:4]}-{now_utc.strftime('%Y%m%d_%H%M')}",
                                        "date_utc": now_utc.strftime("%Y-%m-%d"),
                                        "time_utc": now_utc.strftime("%H:%M:%S UTC"),
                                        "rank": str(fs.get("rank") or "#1"),
                                        "quality_grade": q_grade,
                                        "grade": clean_g,
                                        "grade_tier": tier_n,
                                        "symbol": fs_sym,
                                        "horizon": norm_hz,
                                        "direction": fs_dir,
                                        "conviction_pct": fs.get("conviction") or fs.get("conviction_pct") or 85.0,
                                        "meta_win_prob_pct": fs.get("meta_win_probability_pct") or fs.get("win_probability_pct") or fs.get("win_prob") or 70.0,
                                        "entry_price": entry_p,
                                        "tp1_price": tp1_p,
                                        "tp2_price": tp2_p,
                                        "tp3_price": tp3_p,
                                        "sl_price": sl_p,
                                        "sl_original": sl_p,
                                        "is_tp1_locked": False,
                                        "is_tp2_locked": False,
                                        "risk_reward_ratio": fs.get("risk_reward_ratio", "1:2.0"),
                                        "expected_return_pct": fs.get("expected_return_pct", 0.0),
                                        "decision": fs.get("decision") or f"{fs_dir} {norm_hz}",
                                        "paper_trading_status": "MONITORED SCAN SIGNAL",
                                        "predicted_window": fs.get("predicted_window", ""),
                                        "predicted_close_utc": fs.get("predicted_close_utc", ""),
                                        "status": "PENDING_EVALUATION",
                                        "outcome_label": "PENDING ⏳",
                                        "peak_price_seen": entry_p,
                                        "trough_price_seen": entry_p,
                                        "max_potential_gain_pct": 0.0,
                                        "exit_price": "",
                                        "realized_return_pct": "",
                                        "evaluated_at_utc": "",
                                        "current_price": entry_p,
                                        "live_pnl_pct": 0.0,
                                        "is_tier0_locked": False,
                                        "p_tp1": fs.get("p_tp1_pct") or 70.0,
                                        "p_tp2": fs.get("p_tp2_pct") or 45.0,
                                        "p_tp3": fs.get("p_tp3_pct") or 25.0,
                                        "p_sl": fs.get("p_sl_pct") or 30.0,
                                        "market_shield": fs.get("btc_shield_status", "NORMAL"),
                                        "strategy_archetype": fs.get("strategy_playbook") or "MULTI_HORIZON_TREND",
                                        "order_block_setup": json.dumps(fs.get("order_block_setup", {})) if fs.get("order_block_setup") else "",
                                        "is_tp1_notified_wa": False,
                                        "is_tp2_notified_wa": False,
                                    }
                                    records_to_process.append(row_bridge)
                                    existing_proc_ids.add(fs_sig_id)
                                    existing_active_pairs.add((fs_sym, norm_hz))
                                    extra_rows_for_csv.append(row_bridge)

                                if extra_rows_for_csv and os.path.exists(signals_csv):
                                    try:
                                        import csv
                                        with open(signals_csv, "r", encoding="utf-8") as f_hdr:
                                            first_line = f_hdr.readline().strip()
                                            fnames = [c.strip() for c in first_line.split(",")]
                                        with open(signals_csv, "a", newline="", encoding="utf-8") as f_app:
                                            writer = csv.DictWriter(f_app, fieldnames=fnames, extrasaction="ignore")
                                            for r_extra in extra_rows_for_csv:
                                                writer.writerow(r_extra)
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                        
                        # Targeted batch query: fetch only existing signals in this specific batch (avoids full table scans)
                        batch_sig_ids = [str(r.get("signal_id", "")).strip() for r in records_to_process if str(r.get("signal_id", "")).strip()]
                        if batch_sig_ids:
                            existing_signals = {s.signal_id: s for s in db.query(SignalAudit).filter(SignalAudit.signal_id.in_(batch_sig_ids)).all()}
                        else:
                            existing_signals = {}
                        seen_in_batch = set(existing_signals.keys())

                        for r in records_to_process:
                            sig_id = str(r.get("signal_id", "")).strip()
                            if not sig_id:
                                continue

                            # Clean numeric return
                            ret_num = None
                            ret_raw = r.get("realized_return_pct")
                            if ret_raw is not None:
                                ret_str = str(ret_raw).replace("%", "").replace("+", "").strip()
                                if ret_str != "" and ret_str.lower() not in ["nan", "none", "null"]:
                                    try:
                                        val = float(ret_str)
                                        if not (math.isnan(val) or math.isinf(val)):
                                            ret_num = val
                                    except Exception:
                                        pass

                            # Validate and clean symbol strictly
                            sym_raw = str(r.get("symbol", "")).strip().upper()
                            if "/" not in sym_raw and sym_raw.endswith("USDT"):
                                sym_raw = sym_raw[:-4] + "/USDT"
                            if not UniverseFilter.is_valid_crypto_pair(sym_raw):
                                continue

                            # Validate date_utc and time_utc
                            d_raw = str(r.get("date_utc", "")).strip()
                            t_raw = str(r.get("time_utc", "")).strip()
                            if not d_raw.startswith("202") or d_raw.lower() == "false":
                                if "SIG_202" in sig_id:
                                    try:
                                        parts = sig_id.split("_")
                                        d_raw = f"{parts[1][:4]}-{parts[1][4:6]}-{parts[1][6:8]}"
                                    except Exception:
                                        d_raw = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                                else:
                                    d_raw = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                            if not t_raw or t_raw.lower() == "false":
                                t_raw = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

                            # Validate rank
                            rank_raw = str(r.get("rank", "") or r.get("rank_label", "")).strip()
                            if not rank_raw.startswith("#"):
                                rank_raw = f"#{rank_raw}" if rank_raw.isdigit() else "#1"

                            # Validate horizon
                            hz_raw = str(r.get("horizon", "")).strip().upper()
                            if "15" in hz_raw:
                                norm_hz = "15M"
                            elif "1H" in hz_raw:
                                norm_hz = "1H"
                            elif "24H" in hz_raw or "1D" in hz_raw:
                                norm_hz = "24H"
                            else:
                                norm_hz = "15M"

                            # Validate direction
                            dir_raw = str(r.get("direction", "")).strip().upper()
                            norm_dir = "LONG" if "LONG" in dir_raw or "BULL" in dir_raw else "SHORT"

                            q_grade = str(r.get("quality_grade", "")).strip()
                            if not q_grade or q_grade.replace(".", "").isdigit():
                                q_grade = "Grade A+"
                            raw_tier = r.get("grade_tier")
                            if raw_tier is not None and str(raw_tier).strip().isdigit():
                                tier = int(str(raw_tier).strip())
                            elif "A+" in q_grade:
                                tier = 1
                            elif "Grade A (" in q_grade or "Grade A\n" in q_grade or "GRADE A" in q_grade.upper():
                                tier = 2
                            elif "B+" in q_grade or "Grade B" in q_grade or "B (" in q_grade:
                                tier = 3
                            else:
                                tier = 4

                            def safe_f(v, fallback=0.0):
                                try:
                                    if v is None:
                                        return fallback
                                    if isinstance(v, float) and math.isnan(v):
                                        return fallback
                                    s = str(v).strip()
                                    if not s or s.lower() in ("none", "nan", "null"):
                                        return fallback
                                    return float(s)
                                except Exception:
                                    return fallback

                            pred_close = str(r.get("predicted_close_utc", "")).strip()
                            if not pred_close or pred_close == "N/A":
                                p_win = str(r.get("predicted_window", ""))
                                if "➔" in p_win:
                                    after_arrow = p_win.split("➔")[-1].strip()
                                    pred_close = after_arrow.split("(")[0].strip() if "(" in after_arrow else after_arrow.strip()

                            st_val = str(r.get("status", "PENDING_EVALUATION")).strip().upper()
                            out_val = str(r.get("outcome_label", "PENDING ⏳")).strip()
                            if not st_val or st_val.replace(".", "").isdigit():
                                st_val = "PENDING_EVALUATION"
                            if not out_val or out_val.replace(".", "").isdigit():
                                out_val = "PENDING ⏳"

                            if ret_num is not None and ret_num >= 0.25:
                                if st_val == "EXPIRED" or ("EXPIRED" in out_val and "WON" not in out_val):
                                    st_val = "WON"
                                    out_val = f"🟢 WON (PROFIT EXPIRE +{ret_num:.2f}%)"

                            if sig_id not in seen_in_batch:
                                sig_obj = SignalAudit(
                                    signal_id=sig_id,
                                    date_utc=d_raw,
                                    time_utc=t_raw,
                                    rank_label=rank_raw[:32],
                                    quality_grade=q_grade[:250],
                                    grade_tier=tier,
                                    symbol=sym_raw[:32],
                                    horizon=norm_hz[:32],
                                    direction=norm_dir[:16],
                                    conviction_pct=safe_f(r.get("conviction_pct"), 50.0),
                                    entry_price=safe_f(r.get("entry_price"), 0.0),
                                    tp1_price=safe_f(r.get("tp1_price"), 0.0),
                                    tp2_price=safe_f(r.get("tp2_price"), 0.0),
                                    tp3_price=safe_f(r.get("tp3_price"), 0.0),
                                    sl_price=safe_f(r.get("sl_price"), 0.0),
                                    risk_reward_ratio=str(r.get("risk_reward_ratio", "1:2.0"))[:16],
                                    expected_return_pct=safe_f(r.get("expected_return_pct"), 0.0),
                                    decision=str(r.get("decision", ""))[:250],
                                    paper_trading_status=str(r.get("paper_trading_status", ""))[:250],
                                    predicted_window=str(r.get("predicted_window", ""))[:250],
                                    predicted_close_utc=(pred_close or "N/A")[:64],
                                    status=st_val[:32],
                                    outcome_label=out_val[:250],
                                    peak_price_seen=safe_f(r.get("peak_price_seen"), 0.0),
                                    trough_price_seen=safe_f(r.get("trough_price_seen"), 0.0),
                                    max_potential_gain_pct=safe_f(r.get("max_potential_gain_pct"), 0.0),
                                    exit_price=safe_f(r.get("exit_price"), None) if str(r.get("exit_price", "")) != "" else None,
                                    realized_return_pct=ret_num,
                                    evaluated_at_utc=str(r.get("evaluated_at_utc", ""))[:64] or None,
                                    meta_win_prob=safe_f(r.get("meta_win_prob"), None),
                                    meta_win_prob_pct=safe_f(r.get("meta_win_prob_pct"), None),
                                    volume_24h_usd=safe_f(r.get("volume_24h_usd"), None),
                                    spread_bps=safe_f(r.get("spread_bps"), None),
                                )
                                db.merge(sig_obj)
                                seen_in_batch.add(sig_id)
                                existing_signals[sig_id] = sig_obj
                            else:
                                existing = existing_signals.get(sig_id)
                                if existing:
                                    existing.status = st_val if st_val != "PENDING_EVALUATION" else existing.status
                                    existing.outcome_label = out_val if out_val != "PENDING" else existing.outcome_label
                                    existing.peak_price_seen = safe_f(r.get("peak_price_seen"), existing.peak_price_seen)
                                    existing.trough_price_seen = safe_f(r.get("trough_price_seen"), existing.trough_price_seen)
                                    existing.max_potential_gain_pct = safe_f(r.get("max_potential_gain_pct"), existing.max_potential_gain_pct)
                                    if tier and tier != existing.grade_tier:
                                        existing.grade_tier = tier
                                    if str(r.get("sl_price", "")) != "":
                                        existing.sl_price = safe_f(r.get("sl_price"), existing.sl_price)
                                    if str(r.get("exit_price", "")) != "":
                                        existing.exit_price = safe_f(r.get("exit_price"), existing.exit_price)
                                    if ret_num is not None:
                                        existing.realized_return_pct = ret_num
                                        if ret_num >= 0.25 and (existing.status == "EXPIRED" or ("EXPIRED" in (existing.outcome_label or "") and "WON" not in (existing.outcome_label or ""))):
                                            existing.status = "WON"
                                            existing.outcome_label = f"🟢 WON (PROFIT EXPIRE +{ret_num:.2f}%)"
                                    # Mathematical Invariant (Quant Edge Rule 1 & 9): Resolved signals must never hold NULL exit_price or realized_return_pct
                                    if existing.status and any(k in str(existing.status).upper() for k in ["EXP", "CANCEL", "WON", "LOST", "CLOSE", "BE"]):
                                        if existing.exit_price is None:
                                            dyn_exit = safe_f(r.get("current_price"), getattr(existing, "current_price", None))
                                            if dyn_exit and dyn_exit > 0:
                                                existing.exit_price = dyn_exit
                                            else:
                                                existing.exit_price = safe_f(r.get("exit_price"), existing.entry_price)
                                        if existing.realized_return_pct is None:
                                            if ret_num is not None:
                                                existing.realized_return_pct = ret_num
                                            elif existing.exit_price and existing.entry_price and existing.entry_price > 0:
                                                dir_up = str(getattr(existing, "direction", "LONG")).upper()
                                                if dir_up == "LONG":
                                                    existing.realized_return_pct = round(((existing.exit_price - existing.entry_price) / existing.entry_price) * 100.0, 2)
                                                else:
                                                    existing.realized_return_pct = round(((existing.entry_price - existing.exit_price) / existing.entry_price) * 100.0, 2)
                                            else:
                                                existing.realized_return_pct = 0.0
                                    if r.get("evaluated_at_utc"):
                                        existing.evaluated_at_utc = str(r.get("evaluated_at_utc"))
                                    if pred_close and (not existing.predicted_close_utc or existing.predicted_close_utc == "N/A"):
                                        existing.predicted_close_utc = pred_close
                                    if r.get("meta_win_prob") is not None and str(r.get("meta_win_prob")).strip() not in ("", "None", "nan"):
                                        existing.meta_win_prob = safe_f(r.get("meta_win_prob"), existing.meta_win_prob)
                                    if r.get("meta_win_prob_pct") is not None and str(r.get("meta_win_prob_pct")).strip() not in ("", "None", "nan"):
                                        existing.meta_win_prob_pct = safe_f(r.get("meta_win_prob_pct"), existing.meta_win_prob_pct)
                                    if r.get("volume_24h_usd") is not None and str(r.get("volume_24h_usd")).strip() not in ("", "None", "nan"):
                                        existing.volume_24h_usd = safe_f(r.get("volume_24h_usd"), existing.volume_24h_usd)
                                    if r.get("spread_bps") is not None and str(r.get("spread_bps")).strip() not in ("", "None", "nan"):
                                        existing.spread_bps = safe_f(r.get("spread_bps"), existing.spread_bps)

                        db.commit()
                        _LAST_SYNC_TIMES["csv"] = csv_mtime
                        portfolio_changed = True
                        break
                    except Exception as e:
                        db.rollback()
                        if attempt < 2:
                            time.sleep(0.15 * (attempt + 1))
                        else:
                            print(f"[LIVE SYNC ERROR] Signals CSV sync: {e}")

            # 2. Sync Portfolio JSON
            if os.path.exists(portfolio_json) and (force or portfolio_mtime > _LAST_SYNC_TIMES["portfolio"]):
                for attempt in range(3):
                    try:
                        with open(portfolio_json, "r", encoding="utf-8") as f:
                            p_data = json.load(f)

                        def safe_float(v, fallback=0.0):
                            """Convert a value to float safely; returns fallback on None/empty/invalid."""
                            if v is None:
                                return fallback
                            try:
                                val = float(v)
                                return val if not (math.isnan(val) or math.isinf(val)) else fallback
                            except (TypeError, ValueError):
                                return fallback

                        # Replace current open positions
                        db.query(PaperPosition).delete()
                        for op in p_data.get("open_positions", []):
                            sym = str(op.get("symbol", ""))
                            e_p = safe_float(op.get("entry_price"))
                            if not UniverseFilter.is_valid_crypto_pair(sym, price=e_p):
                                continue
                            tid = op.get("trade_id") or f"POS_{op.get('symbol')}_{op.get('horizon')}"
                            pos = PaperPosition(
                                trade_id=tid,
                                symbol=str(op.get("symbol", "")),
                                horizon=str(op.get("horizon", "")),
                                direction=str(op.get("direction", "")),
                                execution_engine=str(op.get("execution_engine", "paper")),
                                allocated_usd=safe_float(op.get("allocated_usd"), 100.0),
                                entry_price=safe_float(op.get("entry_price")),
                                raw_entry_price=safe_float(op.get("raw_entry_price") or op.get("entry_price")),
                                current_price=safe_float(op.get("current_price")),
                                tp_price=safe_float(op.get("tp_price") or op.get("tp1_price")),
                                tp1_price=safe_float(op.get("tp1_price") or op.get("tp_price")),
                                tp2_price=safe_float(op.get("tp2_price")),
                                tp3_price=safe_float(op.get("tp3_price")),
                                sl_price=safe_float(op.get("sl_price")),
                                unrealized_gross_pnl_usd=safe_float(op.get("unrealized_gross_pnl_usd")),
                                unrealized_pnl_usd=safe_float(op.get("unrealized_pnl_usd")),
                                unrealized_pnl_pct=safe_float(op.get("unrealized_pnl_pct")),
                                target_progress_pct=safe_float(op.get("target_progress_pct")),
                                buy_fee_usd=safe_float(op.get("buy_fee_usd") or op.get("entry_fee_usd")),
                                est_sell_fee_usd=safe_float(op.get("est_sell_fee_usd")),
                                unrealized_fee_usd=safe_float(op.get("unrealized_fee_usd")),
                                opened_at=str(op.get("opened_at", "")),
                                expiry_time=str(op.get("expiry_time", "")),
                            )
                            db.add(pos)

                        # Sync Closed Trades in exact parity with ledger
                        ledger_closed = p_data.get("closed_trades_history") or p_data.get("closed_trades") or []
                        existing_trades = {t[0] for t in db.query(ClosedTrade.trade_id).all()}
                        for ct in ledger_closed:
                            tid = ct.get("trade_id") or f"TRADE_{ct.get('symbol')}_{ct.get('closed_at') or ct.get('closed_at_utc')}"
                            realized_pnl = safe_float(ct.get("realized_pnl_usd") if ct.get("realized_pnl_usd") is not None else ct.get("net_pnl_usd", 0.0))
                            realized_pct = safe_float(ct.get("realized_pnl_pct") if ct.get("realized_pnl_pct") is not None else ct.get("return_pct", 0.0))
                            binance_fee = safe_float(ct.get("binance_fee_usd") if ct.get("binance_fee_usd") is not None else ct.get("fees_usd", 0.0))
                            
                            outcome = ct.get("outcome")
                            if not outcome:
                                outcome = "WON" if realized_pnl > 0.05 else ("LOST" if realized_pnl < -0.05 else "BREAKEVEN")

                            horizon = ct.get("horizon") or ct.get("signal_horizon")
                            if not horizon:
                                for part in str(tid).split("_"):
                                    if part in ["15M", "1H", "4H", "24H", "1D"]:
                                        horizon = part
                                        break
                            if not horizon:
                                d = ct.get("desk", "")
                                horizon = "15M" if d == "scalp" else ("24H" if d in ["swing", "macro"] else "1H")

                            duration_str = ct.get("duration_str")
                            opened_at = str(ct.get("opened_at") or ct.get("opened_at_utc", ""))
                            closed_at = str(ct.get("closed_at") or ct.get("closed_at_utc", ""))
                            if not duration_str and opened_at and closed_at:
                                try:
                                    odt = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
                                    cdt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                                    diff = int((cdt - odt).total_seconds())
                                    dh = diff // 3600
                                    dm = (diff % 3600) // 60
                                    ds = diff % 60
                                    duration_str = f"{dh}h {dm}m {ds}s" if dh > 0 else (f"{dm}m {ds}s" if dm > 0 else f"{ds}s")
                                except Exception:
                                    duration_str = "N/A"

                            if tid not in existing_trades:
                                tr = ClosedTrade(
                                    trade_id=tid,
                                    symbol=str(ct.get("symbol", "")),
                                    horizon=str(horizon or "1H"),
                                    direction=str(ct.get("direction", "")),
                                    execution_engine=str(ct.get("execution_engine", "binance_futures")),
                                    entry_price=safe_float(ct.get("entry_price")),
                                    raw_entry_price=safe_float(ct.get("raw_entry_price") or ct.get("entry_price")),
                                    exit_price=safe_float(ct.get("exit_price")),
                                    exit_reason=str(ct.get("exit_reason", "")),
                                    outcome=str(outcome),
                                    gross_pnl_usd=safe_float(ct.get("gross_pnl_usd")),
                                    buy_fee_usd=safe_float(ct.get("buy_fee_usd") or (binance_fee / 2.0)),
                                    sell_fee_usd=safe_float(ct.get("sell_fee_usd") or (binance_fee / 2.0)),
                                    binance_fee_usd=binance_fee,
                                    realized_pnl_usd=realized_pnl,
                                    realized_pnl_pct=realized_pct,
                                    duration_str=str(duration_str or "N/A"),
                                    opened_at=opened_at,
                                    closed_at=closed_at,
                                )
                                db.add(tr)
                                existing_trades.add(tid)
                            else:
                                existing_tr = db.query(ClosedTrade).filter(ClosedTrade.trade_id == tid).first()
                                if existing_tr:
                                    if not existing_tr.outcome or existing_tr.outcome == "":
                                        existing_tr.outcome = outcome
                                    if not existing_tr.duration_str or existing_tr.duration_str == "N/A":
                                        existing_tr.duration_str = str(duration_str or "N/A")
                                    if not existing_tr.horizon:
                                        existing_tr.horizon = str(horizon or "1H")
                                    if not existing_tr.binance_fee_usd:
                                        existing_tr.binance_fee_usd = binance_fee
                                    if not existing_tr.realized_pnl_usd:
                                        existing_tr.realized_pnl_usd = realized_pnl
                                    if not existing_tr.realized_pnl_pct:
                                        existing_tr.realized_pnl_pct = realized_pct

                        db.commit()
                        _LAST_SYNC_TIMES["portfolio"] = portfolio_mtime
                        portfolio_changed = True
                        break
                    except Exception as e:
                        db.rollback()
                        if attempt < 2:
                            time.sleep(0.15 * (attempt + 1))
                        else:
                            print(f"[LIVE SYNC ERROR] Portfolio sync: {e}")

            # 3. Sync Forecast JSON (Full Update: Always refresh leaderboard & signals)
            if os.path.exists(forecast_json) and (force or forecast_mtime > _LAST_SYNC_TIMES["forecast"]):
                for attempt in range(3):
                    try:
                        with open(forecast_json, "r", encoding="utf-8") as f:
                            f_data = json.load(f)
                        ts = f_data.get("timestamp", datetime.now(timezone.utc).isoformat())
                        _LAST_SCAN_TIMESTAMP = ts
                        _CACHED_FORECAST = f_data

                        top_signals_json = json.dumps(f_data.get("top_round_signals", []))
                        leaderboard_json = json.dumps(f_data.get("scanner_leaderboard", []))
                        deep_dive_json = json.dumps(f_data.get("deep_dive", {}))
                        shield_json = json.dumps(f_data.get("btc_market_shield", {"active": False, "reason": "RANGE CONSOLIDATION"}))

                        # Fast O(1) check on latest forecast by ID rather than full-table scan
                        existing_f = db.query(MarketForecast).order_by(MarketForecast.id.desc()).first()
                        if existing_f and existing_f.timestamp_utc == ts:
                            existing_f.strategy_name = f_data.get("strategy", "Multi-Horizon Engine")
                            existing_f.top_round_signals_json = top_signals_json
                            existing_f.scanner_leaderboard_json = leaderboard_json
                            existing_f.deep_dive_json = deep_dive_json
                            existing_f.btc_market_shield_json = shield_json
                        else:
                            mf = MarketForecast(
                                timestamp_utc=ts,
                                strategy_name=f_data.get("strategy", "Multi-Horizon Engine"),
                                top_round_signals_json=top_signals_json,
                                scanner_leaderboard_json=leaderboard_json,
                                deep_dive_json=deep_dive_json,
                                btc_market_shield_json=shield_json,
                            )
                            db.add(mf)
                        db.commit()

                        # Auto-prune old forecasts: retain only latest 30 snapshots to keep table small (~100MB)
                        try:
                            db.execute(text("""
                                DELETE FROM market_forecasts 
                                WHERE id NOT IN (
                                    SELECT id FROM (
                                        SELECT id FROM market_forecasts ORDER BY id DESC LIMIT 30
                                    ) AS keep_rows
                                )
                            """))
                            db.commit()
                        except Exception:
                            db.rollback()

                        _LAST_SYNC_TIMES["forecast"] = forecast_mtime
                        forecast_changed = True
                        break
                    except Exception as e:
                        db.rollback()
                        if attempt < 2:
                            time.sleep(0.15 * (attempt + 1))
                        else:
                            print(f"[LIVE SYNC ERROR] Forecast sync: {e}")

            if forecast_changed:
                _FULL_SCAN_VERSION += 1
                print(f"[LIVE SYNC ⚡] Full AI 100-Coin Scan Synchronized to Scan Version v{_FULL_SCAN_VERSION} ({_LAST_SCAN_TIMESTAMP}).")
            
            if portfolio_changed:
                _PORTFOLIO_VERSION += 1

            return forecast_changed or portfolio_changed
        finally:
            db.close()
    finally:
        try:
            proc_lock.release()
        finally:
            _SYNC_LOCK.release()

def migrate_files_to_db():
    """Initial startup synchronization."""
    sync_files_to_db_live(force=True)
