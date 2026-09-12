import os
import json
import math
import time
import pandas as pd
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import engine, SessionLocal, Base
from app.models import SignalAudit, PaperPosition, ClosedTrade, MarketForecast
from app.config import settings

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
        if "mysql" in settings.DATABASE_URL.lower():
            with engine.connect() as conn:
                try:
                    conn.execute(text("ALTER TABLE market_forecasts MODIFY scanner_leaderboard_json LONGTEXT"))
                    conn.execute(text("ALTER TABLE market_forecasts MODIFY top_round_signals_json LONGTEXT"))
                    conn.execute(text("ALTER TABLE market_forecasts MODIFY deep_dive_json LONGTEXT"))
                    conn.execute(text("ALTER TABLE market_forecasts MODIFY btc_market_shield_json LONGTEXT"))
                    conn.commit()
                except Exception:
                    pass

                # ── paper_positions: add new columns (idempotent) ────────────────
                for _stmt in [
                    "ALTER TABLE paper_positions ADD COLUMN execution_engine VARCHAR(64) DEFAULT 'paper'",
                    "ALTER TABLE paper_positions ADD COLUMN raw_entry_price DOUBLE",
                    "ALTER TABLE paper_positions ADD COLUMN tp1_price DOUBLE",
                    "ALTER TABLE paper_positions ADD COLUMN tp2_price DOUBLE",
                    "ALTER TABLE paper_positions ADD COLUMN tp3_price DOUBLE",
                    "ALTER TABLE paper_positions ADD COLUMN unrealized_gross_pnl_usd DOUBLE DEFAULT 0.0",
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
    """Returns in-memory cached forecast if available."""
    global _CACHED_FORECAST
    return _CACHED_FORECAST

def set_cached_forecast(data):
    """Sets in-memory cached forecast."""
    global _CACHED_FORECAST
    _CACHED_FORECAST = data

def sync_files_to_db_live(force: bool = False) -> bool:
    """
    High-performance live synchronizer:
    Detects if CSV or JSON files have been modified by test.py,
    and updates the database tables using bulk mappings.
    """
    global _LAST_SYNC_TIMES, _LAST_CHECK_TIME, _FULL_SCAN_VERSION, _PORTFOLIO_VERSION, _LAST_SCAN_TIMESTAMP, _CACHED_FORECAST
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
            try:
                df = pd.read_csv(signals_csv, keep_default_na=False).fillna("")
                records = df.to_dict(orient="records")
                
                # Bulk fetch existing signals into dictionary
                existing_signals = {s.signal_id: s for s in db.query(SignalAudit).all()}

                for r in records:
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

                    q_grade = str(r.get("quality_grade", ""))
                    tier = 1 if "A+" in q_grade else (2 if "GRADE A" in q_grade.upper() else (3 if "B+" in q_grade else 4))

                    def safe_f(v, fallback=0.0):
                        try:
                            return float(v) if v != "" else fallback
                        except Exception:
                            return fallback

                    pred_close = str(r.get("predicted_close_utc", "")).strip()
                    if not pred_close or pred_close == "N/A":
                        p_win = str(r.get("predicted_window", ""))
                        if "➔" in p_win:
                            after_arrow = p_win.split("➔")[-1].strip()
                            pred_close = after_arrow.split("(")[0].strip() if "(" in after_arrow else after_arrow.strip()

                    existing = existing_signals.get(sig_id)
                    if not existing:
                        sig_obj = SignalAudit(
                            signal_id=sig_id,
                            date_utc=str(r.get("date_utc", "")),
                            time_utc=str(r.get("time_utc", "")),
                            rank_label=str(r.get("rank", "")),
                            quality_grade=q_grade,
                            grade_tier=tier,
                            symbol=str(r.get("symbol", "")),
                            horizon=str(r.get("horizon", "")),
                            direction=str(r.get("direction", "LONG")),
                            conviction_pct=safe_f(r.get("conviction_pct"), 50.0),
                            entry_price=safe_f(r.get("entry_price"), 0.0),
                            tp1_price=safe_f(r.get("tp1_price"), 0.0),
                            tp2_price=safe_f(r.get("tp2_price"), 0.0),
                            tp3_price=safe_f(r.get("tp3_price"), 0.0),
                            sl_price=safe_f(r.get("sl_price"), 0.0),
                            risk_reward_ratio=str(r.get("risk_reward_ratio", "1:2.0")),
                            expected_return_pct=safe_f(r.get("expected_return_pct"), 0.0),
                            decision=str(r.get("decision", "")),
                            paper_trading_status=str(r.get("paper_trading_status", "")),
                            predicted_window=str(r.get("predicted_window", "")),
                            predicted_close_utc=pred_close or "N/A",
                            status=str(r.get("status", "PENDING_EVALUATION")),
                            outcome_label=str(r.get("outcome_label", "PENDING")),
                            peak_price_seen=safe_f(r.get("peak_price_seen"), 0.0),
                            trough_price_seen=safe_f(r.get("trough_price_seen"), 0.0),
                            max_potential_gain_pct=safe_f(r.get("max_potential_gain_pct"), 0.0),
                            exit_price=safe_f(r.get("exit_price"), None) if str(r.get("exit_price", "")) != "" else None,
                            realized_return_pct=ret_num,
                            evaluated_at_utc=str(r.get("evaluated_at_utc", "")) or None,
                        )
                        db.add(sig_obj)
                        existing_signals[sig_id] = sig_obj
                    else:
                        existing.status = str(r.get("status", existing.status))
                        existing.outcome_label = str(r.get("outcome_label", existing.outcome_label))
                        existing.peak_price_seen = safe_f(r.get("peak_price_seen"), existing.peak_price_seen)
                        existing.trough_price_seen = safe_f(r.get("trough_price_seen"), existing.trough_price_seen)
                        existing.max_potential_gain_pct = safe_f(r.get("max_potential_gain_pct"), existing.max_potential_gain_pct)
                        if str(r.get("exit_price", "")) != "":
                            existing.exit_price = safe_f(r.get("exit_price"), existing.exit_price)
                        if ret_num is not None:
                            existing.realized_return_pct = ret_num
                        if r.get("evaluated_at_utc"):
                            existing.evaluated_at_utc = str(r.get("evaluated_at_utc"))
                        if pred_close and (not existing.predicted_close_utc or existing.predicted_close_utc == "N/A"):
                            existing.predicted_close_utc = pred_close

                db.commit()
                _LAST_SYNC_TIMES["csv"] = csv_mtime
                portfolio_changed = True
            except Exception as e:
                db.rollback()
                print(f"[LIVE SYNC ERROR] Signals CSV sync: {e}")

        # 2. Sync Portfolio JSON
        if os.path.exists(portfolio_json) and (force or portfolio_mtime > _LAST_SYNC_TIMES["portfolio"]):
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
                ledger_closed = p_data.get("closed_trades_history", [])
                ledger_trade_ids = {ct.get("trade_id") for ct in ledger_closed if ct.get("trade_id")}
                
                # If ledger was reset (0 closed trades), purge historical DB records
                if not ledger_closed:
                    db.query(ClosedTrade).delete()
                else:
                    # Remove any DB closed trades that are not in the current ledger
                    db.query(ClosedTrade).filter(~ClosedTrade.trade_id.in_(ledger_trade_ids)).delete(synchronize_session=False)

                existing_trades = {t[0] for t in db.query(ClosedTrade.trade_id).all()}
                for ct in ledger_closed:
                    tid = ct.get("trade_id") or f"TRADE_{ct.get('symbol')}_{ct.get('closed_at')}"
                    if tid not in existing_trades:
                        tr = ClosedTrade(
                            trade_id=tid,
                            symbol=str(ct.get("symbol", "")),
                            horizon=str(ct.get("horizon", "")),
                            direction=str(ct.get("direction", "")),
                            execution_engine=str(ct.get("execution_engine", "paper")),
                            entry_price=safe_float(ct.get("entry_price")),
                            raw_entry_price=safe_float(ct.get("raw_entry_price") or ct.get("entry_price")),
                            exit_price=safe_float(ct.get("exit_price")),
                            exit_reason=str(ct.get("exit_reason", "")),
                            outcome=str(ct.get("outcome", "")),
                            gross_pnl_usd=safe_float(ct.get("gross_pnl_usd")),
                            buy_fee_usd=safe_float(ct.get("buy_fee_usd")),
                            sell_fee_usd=safe_float(ct.get("sell_fee_usd")),
                            binance_fee_usd=safe_float(ct.get("binance_fee_usd")),
                            realized_pnl_usd=safe_float(ct.get("realized_pnl_usd")),
                            realized_pnl_pct=safe_float(ct.get("realized_pnl_pct")),
                            duration_str=str(ct.get("duration_str", "")),
                            opened_at=str(ct.get("opened_at", "")),
                            closed_at=str(ct.get("closed_at", "")),
                        )
                        db.add(tr)
                        existing_trades.add(tid)

                db.commit()
                _LAST_SYNC_TIMES["portfolio"] = portfolio_mtime
                portfolio_changed = True
            except Exception as e:
                db.rollback()
                print(f"[LIVE SYNC ERROR] Portfolio sync: {e}")

        # 3. Sync Forecast JSON
        if os.path.exists(forecast_json) and (force or forecast_mtime > _LAST_SYNC_TIMES["forecast"]):
            try:
                with open(forecast_json, "r", encoding="utf-8") as f:
                    f_data = json.load(f)
                ts = f_data.get("timestamp", datetime.now(timezone.utc).isoformat())
                _LAST_SCAN_TIMESTAMP = ts
                _CACHED_FORECAST = f_data

                # Insert new forecast record
                existing_f = db.query(MarketForecast).filter(MarketForecast.timestamp_utc == ts).first()
                if not existing_f:
                    mf = MarketForecast(
                        timestamp_utc=ts,
                        strategy_name=f_data.get("strategy", "Multi-Horizon Engine"),
                        top_round_signals_json=json.dumps(f_data.get("top_round_signals", [])),
                        scanner_leaderboard_json=json.dumps(f_data.get("scanner_leaderboard", [])),
                        deep_dive_json=json.dumps(f_data.get("deep_dive", {})),
                        btc_market_shield_json=json.dumps(f_data.get("btc_market_shield", {"active": False, "reason": "RANGE CONSOLIDATION"})),
                    )
                    db.add(mf)
                    db.commit()
                else:
                    existing_f.btc_market_shield_json = json.dumps(f_data.get("btc_market_shield", {"active": False, "reason": "RANGE CONSOLIDATION"}))
                    db.commit()

                _LAST_SYNC_TIMES["forecast"] = forecast_mtime
                forecast_changed = True
            except Exception as e:
                db.rollback()
                print(f"[LIVE SYNC ERROR] Forecast sync: {e}")

        if forecast_changed:
            _FULL_SCAN_VERSION += 1
            print(f"[LIVE SYNC ⚡] Full AI 100-Coin Scan Synchronized to Scan Version v{_FULL_SCAN_VERSION} ({_LAST_SCAN_TIMESTAMP}).")
        
        if portfolio_changed:
            _PORTFOLIO_VERSION += 1

        return forecast_changed or portfolio_changed
    finally:
        db.close()

def migrate_files_to_db():
    """Initial startup synchronization."""
    sync_files_to_db_live(force=True)
