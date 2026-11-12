from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import event
import logging
import os
import sys
import socket

logger = logging.getLogger("database")

from app.config import settings

def is_test_environment() -> bool:
    if os.environ.get("TESTING") in ("1", "true", "True"):
        return True
    if os.environ.get("ENVIRONMENT", "").lower() in ("test", "testing"):
        return True
    if os.environ.get("CI", "").lower() in ("true", "1"):
        return True
    # Note: Do not check 'unittest' in sys.modules because numpy.testing imports unittest unconditionally
    if any(mod in sys.modules for mod in ("pytest", "fastapi.testclient", "starlette.testclient")):
        return True
    orig_args = getattr(sys, "orig_argv", [])
    all_args = list(sys.argv) + list(orig_args)
    for i, arg in enumerate(all_args):
        a_low = str(arg).lower()
        if a_low.endswith("test_suite_engine.py") or a_low.endswith("test_v16_regression.py") or "test_" in a_low or "_test" in a_low or "run_all_v16_tests" in a_low:
            return True
        if "pytest" in a_low or "unittest" in a_low or "testclient" in a_low:
            return True
        if arg == "-c" and i + 1 < len(all_args):
            c_code = all_args[i + 1].lower()
            if any(k in c_code for k in ("testclient", "pytest", "unittest", "test_suite", "test_v16")):
                return True
    return False

def is_socket_reachable(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        res = sock.connect_ex((host, port))
        sock.close()
        return res == 0
    except Exception:
        return False

def get_engine():
    db_url = settings.DATABASE_URL
    fallback_url = "sqlite:///./crypto_trading.db"

    # Fast-fail directly to local SQLite in test mode without blocking socket probes or diagnostic warnings
    if is_test_environment() and os.environ.get("MYSQL_TEST_CONNECT") != "1":
        logger.debug(f"[DATABASE] Offline test mode active: Using local SQLite fallback '{fallback_url}' without outbound socket probing.")
        return create_engine(
            fallback_url,
            connect_args={"check_same_thread": False, "timeout": 30},
            pool_pre_ping=True,
            pool_recycle=1800,
            echo=False
        )

    # If explicitly using SQLite or custom dialect
    if "mysql" not in db_url.lower():
        return create_engine(
            db_url,
            connect_args={"check_same_thread": False, "timeout": 30} if "sqlite" in db_url.lower() else {},
            pool_pre_ping=True,
            pool_recycle=1800,
            echo=False
        )

    # For MySQL connections: Perform lightweight non-blocking port check before attempting connection
    host = getattr(settings, "MYSQL_HOST", "localhost")
    port = int(getattr(settings, "MYSQL_PORT", 3306))

    mysql_reachable = is_socket_reachable(host, port, timeout=0.35)

    if not mysql_reachable:
        if is_test_environment():
            logger.debug(f"[DATABASE] Offline test mode: MySQL server on {host}:{port} offline. Using local SQLite fallback.")
        else:
            print(f"[DATABASE ℹ️] MySQL server on {host}:{port} is unreachable. Using local SQLite fallback '{fallback_url}'.")
        return create_engine(
            fallback_url,
            connect_args={"check_same_thread": False, "timeout": 30},
            pool_pre_ping=True,
            pool_recycle=1800,
            echo=False
        )

    # MySQL port is open: proceed with standard pooled engine
    try:
        eng = create_engine(
            db_url,
            connect_args={"connect_timeout": 3},
            pool_size=25,
            max_overflow=15,
            pool_timeout=30,
            pool_pre_ping=True,
            pool_recycle=1800,
            echo=False
        )
        with eng.connect() as conn:
            pass
        print(f"[DATABASE ✅] Connected to database at {host}:{port}")
        return eng
    except Exception as e:
        if is_test_environment():
            logger.debug(f"[DATABASE] MySQL connection deferred in test mode: {e}")
        else:
            print(f"[DATABASE ⚠️] Database connection warning ({e}). Using local database fallback '{fallback_url}'.")
        return create_engine(
            fallback_url,
            connect_args={"check_same_thread": False, "timeout": 30},
            pool_pre_ping=True,
            pool_recycle=1800,
            echo=False
        )

engine = get_engine()

# Enable WAL mode, busy timeout, and memory cache for SQLite instances
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-64000")  # 64MB memory cache
        cursor.execute("PRAGMA busy_timeout=30000")  # 30 second timeout on lock wait
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception as e:
        logger.debug(f"[DATABASE] SQLite PRAGMA configuration skipped/failed: {e}")

def ensure_schema_compatibility(eng):
    """
    Ensures newly required columns exist across signals_tracker, paper_positions,
    closed_trades, and market_forecasts in SQLite and MySQL without data loss.
    """
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(eng)
        existing_tables = set(inspector.get_table_names())

        table_columns_map = {
            "signals_tracker": [
                ("sl_original", "FLOAT"),
                ("meta_win_prob", "FLOAT"),
                ("meta_win_prob_pct", "FLOAT"),
                ("volume_24h_usd", "FLOAT"),
                ("spread_bps", "FLOAT"),
                ("tf_metrics_json", "TEXT"),
                ("card_text", "TEXT"),
                ("predicted_close_utc", "VARCHAR(64)"),
                ("max_potential_gain_pct", "FLOAT"),
                ("evaluated_at_utc", "VARCHAR(64)"),
                ("exit_price", "FLOAT"),
                ("realized_return_pct", "FLOAT"),
            ],
            "paper_positions": [
                ("execution_engine", "VARCHAR(64) DEFAULT 'paper'"),
                ("raw_entry_price", "FLOAT"),
                ("tp1_price", "FLOAT"),
                ("tp2_price", "FLOAT"),
                ("tp3_price", "FLOAT"),
                ("unrealized_gross_pnl_usd", "FLOAT DEFAULT 0.0"),
                ("buy_fee_usd", "FLOAT DEFAULT 0.0"),
                ("est_sell_fee_usd", "FLOAT DEFAULT 0.0"),
                ("unrealized_fee_usd", "FLOAT DEFAULT 0.0"),
            ],
            "closed_trades": [
                ("execution_engine", "VARCHAR(64) DEFAULT 'paper'"),
                ("raw_entry_price", "FLOAT"),
                ("gross_pnl_usd", "FLOAT DEFAULT 0.0"),
                ("buy_fee_usd", "FLOAT DEFAULT 0.0"),
                ("sell_fee_usd", "FLOAT DEFAULT 0.0"),
                ("total_fee_usd", "FLOAT DEFAULT 0.0"),
                ("binance_fee_usd", "FLOAT DEFAULT 0.0"),
            ],
            "market_forecasts": [
                ("top_round_signals_json", "TEXT"),
                ("scanner_leaderboard_json", "TEXT"),
                ("deep_dive_json", "TEXT"),
                ("btc_market_shield_json", "TEXT"),
            ],
        }

        with eng.begin() as conn:
            for tbl_name, new_cols in table_columns_map.items():
                if tbl_name in existing_tables:
                    existing_cols = {c["name"] for c in inspector.get_columns(tbl_name)}
                    for col_name, col_def in new_cols:
                        if col_name not in existing_cols:
                            try:
                                conn.execute(text(f"ALTER TABLE {tbl_name} ADD COLUMN {col_name} {col_def}"))
                                existing_cols.add(col_name)
                            except Exception as ex:
                                logger.debug(f"[DATABASE] Column add skipped ({tbl_name}.{col_name}): {ex}")
    except Exception as e:
        logger.warning(f"[DATABASE] Schema compatibility check warning: {e}")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_db(target_engine=None):
    eng = target_engine or engine
    try:
        from app.models import SignalAudit, PaperPosition, ClosedTrade, MarketForecast
        Base.metadata.create_all(bind=eng)
        ensure_schema_compatibility(eng)
    except Exception as e:
        logger.debug(f"[DATABASE] init_db note: {e}")

init_db(engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
