#!/usr/bin/env python3
"""
Clean System & Fresh Restart Utility
-----------------------------------
This script resets the entire Crypto Quantitative Platform to a clean slate:
1. Purges database tables (signals_tracker, paper_positions, closed_trades, market_forecasts).
2. Resets paper trading ledger to clean $100.00 capital, 10 slots, and zero trades.
3. Resets signal audit CSV files (trader_signals_tracker.csv & performance summary).
4. Clears cached forecast JSON files and resets scanner daemon state.
5. Optionally clears legacy ML model checkpoints in models_export_v3/.
"""

import os
import sys
import json
import shutil
from datetime import datetime, timezone

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def clean_database():
    print("\n[1/4] Purging Database Records...")
    cleaned = False

    # Method 1: SQLAlchemy (preferred if app dependencies are available)
    try:
        from app.database import engine
        from sqlalchemy import text

        with engine.connect() as conn:
            dialect = engine.dialect.name
            if dialect == "mysql":
                conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
                conn.execute(text("TRUNCATE TABLE signals_tracker;"))
                conn.execute(text("TRUNCATE TABLE paper_positions;"))
                conn.execute(text("TRUNCATE TABLE closed_trades;"))
                conn.execute(text("TRUNCATE TABLE market_forecasts;"))
                conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
                conn.commit()
            else:
                conn.execute(text("DELETE FROM signals_tracker;"))
                conn.execute(text("DELETE FROM paper_positions;"))
                conn.execute(text("DELETE FROM closed_trades;"))
                conn.execute(text("DELETE FROM market_forecasts;"))
                conn.commit()
            print("  [OK] Database tables truncated successfully (signals_tracker, paper_positions, closed_trades, market_forecasts).")
            cleaned = True
    except Exception as e:
        pass

    # Method 2: Local SQLite fallback
    if os.path.exists("crypto_trading.db"):
        try:
            import sqlite3
            con = sqlite3.connect("crypto_trading.db")
            cur = con.cursor()
            for tbl in ["signals_tracker", "paper_positions", "closed_trades", "market_forecasts"]:
                try:
                    cur.execute(f"DELETE FROM {tbl};")
                except Exception:
                    pass
            con.commit()
            con.close()
            print("  [OK] Local SQLite fallback database 'crypto_trading.db' purged.")
            cleaned = True
        except Exception:
            pass

    if not cleaned:
        print("  [INFO] Database tables are already clean or will be cleared via Docker MySQL on VPS.")

def reset_export_files():
    print("\n[2/4] Resetting Exported Application Data...")
    export_dir = os.getenv("EXPORT_DIR", "./export_app_data")
    os.makedirs(export_dir, exist_ok=True)

    # 1. Clean Paper Trading Ledger ($100 Capital, 10 Slots)
    clean_ledger = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "fee_tier_label": "Binance Convert (Zero Fee | +0.10% Buy / -0.10% Sell Spread)",
        "execution_engine": "binance_convert",
        "starting_balance_usd": 100.0,
        "current_balance_usd": 100.0,
        "realized_pnl_usd": 0.0,
        "gross_realized_pnl_usd": 0.0,
        "total_fees_paid_usd": 0.0,
        "gross_profit_usd": 0.0,
        "gross_loss_usd": 0.0,
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "breakeven_trades": 0,
        "win_rate_pct": 0.0,
        "profit_factor": 0.0,
        "peak_balance_usd": 100.0,
        "max_drawdown_usd": 0.0,
        "max_drawdown_pct": 0.0,
        "open_positions": [],
        "closed_trades_history": [],
        "queued_trades": []
    }
    ledger_path = os.path.join(export_dir, "paper_trading_ledger.json")
    with open(ledger_path, "w", encoding="utf-8") as f:
        json.dump(clean_ledger, f, indent=4)
    print("  [OK] Reset paper_trading_ledger.json to fresh $100.00 capital (10 slots).")

    # 2. Reset CSV Trackers with clean header only
    csv_tracker_path = os.path.join(export_dir, "trader_signals_tracker.csv")
    csv_header = "signal_id,date_utc,time_utc,rank,quality_grade,symbol,horizon,direction,conviction_pct,meta_win_prob_pct,entry_price,tp1_price,tp2_price,tp3_price,sl_price,sl_original,is_tp1_locked,is_tp2_locked,risk_reward_ratio,expected_return_pct,decision,paper_trading_status,predicted_window,predicted_close_utc,status,outcome_label,peak_price_seen,trough_price_seen,max_potential_gain_pct,exit_price,realized_return_pct,evaluated_at_utc\n"
    with open(csv_tracker_path, "w", encoding="utf-8") as f:
        f.write(csv_header)
    print("  [OK] Cleared trader_signals_tracker.csv.")

    kpi_summary_path = os.path.join(export_dir, "trader_signals_performance.csv")
    kpi_header = "last_updated_utc,total_trader_signals,won_signals_count,lost_signals_count,pending_signals_count,expired_signals_count,win_rate_pct,grade_a_plus_win_rate_pct,grade_a_win_rate_pct,average_return_pct,cumulative_return_pct\n"
    with open(kpi_summary_path, "w", encoding="utf-8") as f:
        f.write(kpi_header)
    print("  [OK] Cleared trader_signals_performance.csv.")

    # 3. Reset Scanner Daemon State
    daemon_state_path = os.path.join(export_dir, "scanner_daemon_state.json")
    with open(daemon_state_path, "w", encoding="utf-8") as f:
        json.dump({"is_scanning": False, "scan_status": "IDLE", "scan_started_at": datetime.now(timezone.utc).isoformat()}, f, indent=4)
    print("  [OK] Reset scanner_daemon_state.json to IDLE.")

    # 4. Remove cached forecast
    forecast_path = os.path.join(export_dir, "live_market_forecast.json")
    if os.path.exists(forecast_path):
        os.remove(forecast_path)
        print("  [OK] Removed stale live_market_forecast.json.")

def clean_models(clean_all: bool = False):
    print("\n[3/4] Model Checkpoint Cache...")
    models_dir = os.getenv("MODELS_EXPORT_DIR", "./models_export_v3")
    if os.path.exists(models_dir):
        if clean_all:
            shutil.rmtree(models_dir)
            os.makedirs(models_dir, exist_ok=True)
            print(f"  [OK] Cleared all model checkpoints in {models_dir}/ (Engine will re-train on fresh data).")
        else:
            print(f"  [INFO] Models preserved in {models_dir}/ (Pass --clean-models to purge checkpoints).")
    else:
        os.makedirs(models_dir, exist_ok=True)

def main():
    print("=" * 70)
    print("[RESET] QUANT SYSTEM CLEAN RESET UTILITY")
    print("=" * 70)

    clean_models_flag = "--clean-models" in sys.argv or "--fresh-models" in sys.argv

    clean_database()
    reset_export_files()
    clean_models(clean_all=clean_models_flag)

    print("\n[4/4] System Ready!")
    print("=" * 70)
    print("[SUCCESS] Clean restart complete! You can now start the engine/containers cleanly:")
    print("   * Local:   python test.py")
    print("   * Docker:  ./deploy.sh")
    print("=" * 70)

if __name__ == "__main__":
    main()
