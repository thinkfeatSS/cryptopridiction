import os
import json
import math
import pandas as pd
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.database import engine, SessionLocal, Base
from app.models import SignalAudit, PaperPosition, ClosedTrade, MarketForecast
from app.config import settings

def init_db():
    """Creates all database tables in MySQL / SQLite."""
    try:
        Base.metadata.create_all(bind=engine)
        print("[DATABASE] All database tables verified and created.")
    except Exception as e:
        print(f"[DATABASE ERROR] Table creation error: {e}")

def migrate_files_to_db():
    """One-time / startup migrator: Imports historical CSV/JSON files into database if tables are empty."""
    init_db()
    db: Session = SessionLocal()
    try:
        export_dir = settings.EXPORT_DIR
        signals_csv = os.path.join(export_dir, "trader_signals_tracker.csv")
        portfolio_json = os.path.join(export_dir, "paper_trading_ledger.json")
        forecast_json = os.path.join(export_dir, "live_market_forecast.json")

        # 1. Migrate Signals Tracker CSV
        if os.path.exists(signals_csv):
            try:
                df = pd.read_csv(signals_csv, keep_default_na=False).fillna("")
                records = df.to_dict(orient="records")
                existing_count = db.query(SignalAudit).count()
                if existing_count < len(records):
                    imported = 0
                    for r in records:
                        sig_id = str(r.get("signal_id", "")).strip()
                        if not sig_id:
                            continue
                        
                        existing = db.query(SignalAudit).filter(SignalAudit.signal_id == sig_id).first()
                        
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

                        # Determine grade tier
                        q_grade = str(r.get("quality_grade", ""))
                        if "A+" in q_grade:
                            tier = 1
                        elif "GRADE A" in q_grade.upper():
                            tier = 2
                        elif "B+" in q_grade:
                            tier = 3
                        else:
                            tier = 4

                        def safe_f(v, fallback=0.0):
                            try:
                                return float(v) if v != "" else fallback
                            except Exception:
                                return fallback

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
                            imported += 1
                    db.commit()
                    print(f"[MIGRATION] Imported {imported} signals from CSV into database.")
            except Exception as e:
                db.rollback()
                print(f"[MIGRATION ERROR] Signals CSV migration error: {e}")

        # 2. Migrate Portfolio JSON
        if os.path.exists(portfolio_json):
            try:
                with open(portfolio_json, "r", encoding="utf-8") as f:
                    p_data = json.load(f)

                # Open positions
                open_positions = p_data.get("open_positions", [])
                for op in open_positions:
                    tid = op.get("trade_id", f"POS_{op.get('symbol')}_{op.get('horizon')}")
                    existing_pos = db.query(PaperPosition).filter(PaperPosition.trade_id == tid).first()
                    if not existing_pos:
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

                # Closed trades
                closed_trades = p_data.get("closed_trades_history", [])
                for ct in closed_trades:
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
            except Exception as e:
                db.rollback()
                print(f"[MIGRATION ERROR] Portfolio migration error: {e}")

        # 3. Migrate Forecast JSON
        if os.path.exists(forecast_json):
            try:
                with open(forecast_json, "r", encoding="utf-8") as f:
                    f_data = json.load(f)
                ts = f_data.get("timestamp", datetime.now(timezone.utc).isoformat())
                existing_f = db.query(MarketForecast).order_by(MarketForecast.id.desc()).first()
                if not existing_f:
                    mf = MarketForecast(
                        timestamp_utc=ts,
                        strategy_name=f_data.get("strategy", "Multi-Horizon Engine"),
                        top_round_signals_json=json.dumps(f_data.get("top_round_signals", [])),
                        scanner_leaderboard_json=json.dumps(f_data.get("scanner_leaderboard", [])),
                        deep_dive_json=json.dumps(f_data.get("deep_dive", {})),
                    )
                    db.add(mf)
                    db.commit()
            except Exception as e:
                db.rollback()
                print(f"[MIGRATION ERROR] Forecast migration error: {e}")

    finally:
        db.close()
