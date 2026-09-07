import os
import json
import math
import time
import pandas as pd
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.database import engine, SessionLocal, Base
from app.models import SignalAudit, PaperPosition, ClosedTrade, MarketForecast
from app.config import settings

_LAST_SYNC_TIMES = {
    "csv": 0.0,
    "portfolio": 0.0,
    "forecast": 0.0,
}
_SCAN_VERSION = 1
_LAST_SCAN_TIMESTAMP = datetime.now(timezone.utc).isoformat()

def init_db():
    """Creates all database tables in MySQL / SQLite."""
    try:
        Base.metadata.create_all(bind=engine)
        print("[DATABASE] All database tables verified and created.")
    except Exception as e:
        print(f"[DATABASE ERROR] Table creation error: {e}")

def get_sync_state():
    """Returns the current scan version and last scan timestamp."""
    global _SCAN_VERSION, _LAST_SCAN_TIMESTAMP
    return {
        "scan_version": _SCAN_VERSION,
        "last_scan_timestamp": _LAST_SCAN_TIMESTAMP,
    }

def sync_files_to_db_live(force: bool = False) -> bool:
    """
    High-performance live synchronizer:
    Detects if CSV or JSON files have been modified by test.py,
    and updates the database tables (inserting new signals and updating existing ones).
    """
    global _LAST_SYNC_TIMES, _SCAN_VERSION, _LAST_SCAN_TIMESTAMP
    export_dir = settings.EXPORT_DIR
    signals_csv = os.path.join(export_dir, "trader_signals_tracker.csv")
    portfolio_json = os.path.join(export_dir, "paper_trading_ledger.json")
    forecast_json = os.path.join(export_dir, "live_market_forecast.json")

    changed = False

    csv_mtime = os.path.getmtime(signals_csv) if os.path.exists(signals_csv) else 0.0
    portfolio_mtime = os.path.getmtime(portfolio_json) if os.path.exists(portfolio_json) else 0.0
    forecast_mtime = os.path.getmtime(forecast_json) if os.path.exists(forecast_json) else 0.0

    if not force and csv_mtime <= _LAST_SYNC_TIMES["csv"] and portfolio_mtime <= _LAST_SYNC_TIMES["portfolio"] and forecast_mtime <= _LAST_SYNC_TIMES["forecast"]:
        return False

    init_db()
    db: Session = SessionLocal()
    try:
        # 1. Sync Signals Tracker CSV (Insert new + update existing outcomes & returns)
        if os.path.exists(signals_csv) and (force or csv_mtime > _LAST_SYNC_TIMES["csv"]):
            try:
                df = pd.read_csv(signals_csv, keep_default_na=False).fillna("")
                records = df.to_dict(orient="records")
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

                    existing = db.query(SignalAudit).filter(SignalAudit.signal_id == sig_id).first()
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
                    else:
                        # Update outcome, peak/trough, and exit return in existing record
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
                changed = True
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

                for ct in p_data.get("closed_trades_history", []):
                    tid = ct.get("trade_id", f"TRADE_{ct.get('symbol')}_{ct.get('closed_at')}")
                    existing_tr = db.query(ClosedTrade).filter(ClosedTrade.trade_id == tid).first()
                    if not existing_tr:
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

                db.commit()
                _LAST_SYNC_TIMES["portfolio"] = portfolio_mtime
                changed = True
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
                changed = True
            except Exception as e:
                db.rollback()
                print(f"[LIVE SYNC ERROR] Forecast sync: {e}")

        if changed:
            _SCAN_VERSION += 1
            print(f"[LIVE SYNC ⚡] Database synchronized to Scan Version v{_SCAN_VERSION} ({_LAST_SCAN_TIMESTAMP}).")

        return changed
    finally:
        db.close()

def migrate_files_to_db():
    """Initial startup synchronization."""
    sync_files_to_db_live(force=True)
