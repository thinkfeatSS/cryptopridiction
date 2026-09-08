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
        print("[DATABASE] All database tables verified and created.")
    except Exception as e:
        print(f"[DATABASE ERROR] Table creation error: {e}")

def get_daemon_state():
    """Reads lightweight scanner daemon state file if available."""
    global _IS_SCANNING
    state_file = os.path.join(settings.EXPORT_DIR, "scanner_daemon_state.json")
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                _IS_SCANNING = bool(data.get("is_scanning", False))
                return data
        except Exception:
            pass
    return {"is_scanning": _IS_SCANNING, "scan_status": "IDLE"}

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
        "last_scan_timestamp": _LAST_SCAN_TIMESTAMP,
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
                            predicted_close_utc=str(r.get("predicted_close_utc", "")),
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

                # Replace current open positions
                db.query(PaperPosition).delete()
                for op in p_data.get("open_positions", []):
                    tid = op.get("trade_id", f"POS_{op.get('symbol')}_{op.get('horizon')}")
                    pos = PaperPosition(
                        trade_id=tid,
                        symbol=op.get("symbol"),
                        horizon=op.get("horizon"),
                        direction=op.get("direction"),
                        allocated_usd=float(op.get("allocated_usd", 100.0)),
                        entry_price=float(op.get("entry_price", 0.0)),
                        current_price=float(op.get("current_price", 0.0)),
                        tp_price=float(op.get("tp_price", 0.0)),
                        sl_price=float(op.get("sl_price", 0.0)),
                        unrealized_pnl_usd=float(op.get("unrealized_pnl_usd", 0.0)),
                        unrealized_pnl_pct=float(op.get("unrealized_pnl_pct", 0.0)),
                        target_progress_pct=float(op.get("target_progress_pct", 0.0)),
                        unrealized_fee_usd=float(op.get("unrealized_fee_usd", 0.0)),
                        opened_at=str(op.get("opened_at", "")),
                        expiry_time=str(op.get("expiry_time", "")),
                    )
                    db.add(pos)

                existing_trades = {t[0] for t in db.query(ClosedTrade.trade_id).all()}
                for ct in p_data.get("closed_trades_history", []):
                    tid = ct.get("trade_id", f"TRADE_{ct.get('symbol')}_{ct.get('closed_at')}")
                    if tid not in existing_trades:
                        tr = ClosedTrade(
                            trade_id=tid,
                            symbol=ct.get("symbol"),
                            horizon=ct.get("horizon"),
                            direction=ct.get("direction"),
                            entry_price=float(ct.get("entry_price", 0.0)),
                            exit_price=float(ct.get("exit_price", 0.0)),
                            exit_reason=str(ct.get("exit_reason", "")),
                            outcome=str(ct.get("outcome", "")),
                            gross_pnl_usd=float(ct.get("gross_pnl_usd", 0.0)),
                            binance_fee_usd=float(ct.get("binance_fee_usd", 0.0)),
                            realized_pnl_usd=float(ct.get("realized_pnl_usd", 0.0)),
                            realized_pnl_pct=float(ct.get("realized_pnl_pct", 0.0)),
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
                        btc_market_shield_json=json.dumps(f_data.get("btc_market_shield", {"active": False, "reason": "NORMAL (Market Stable)"})),
                    )
                    db.add(mf)
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
