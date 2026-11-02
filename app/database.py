from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import sys

from app.config import settings

from sqlalchemy import event

def get_engine():
    db_url = settings.DATABASE_URL
    # If explicitly using SQLite or MySQL isn't reachable
    try:
        if "mysql" in db_url.lower():
            eng = create_engine(
                db_url,
                pool_size=25,
                max_overflow=15,
                pool_timeout=30,
                pool_pre_ping=True,
                pool_recycle=1800,
                echo=False
            )
        else:
            eng = create_engine(
                db_url,
                connect_args={"check_same_thread": False} if "sqlite" in db_url.lower() else {},
                pool_pre_ping=True,
                pool_recycle=1800,
                echo=False
            )
        # Test connection
        with eng.connect() as conn:
            pass
        print(f"[DATABASE] Connected to database at {settings.MYSQL_HOST if 'mysql' in db_url.lower() else 'SQLite'}")
        return eng
    except Exception as e:
        print(f"[DATABASE] Database connection warning ({e}). Using local database fallback 'sqlite:///./crypto_trading.db'.")
        fallback_url = "sqlite:///./crypto_trading.db"
        return create_engine(fallback_url, connect_args={"check_same_thread": False})

engine = get_engine()

def ensure_schema_compatibility(eng):
    """Ensures newly required columns exist in signals_tracker across SQLite and MySQL without data loss."""
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(eng)
        if "signals_tracker" in inspector.get_table_names():
            existing_cols = {c["name"] for c in inspector.get_columns("signals_tracker")}
            new_cols = [
                ("meta_win_prob", "FLOAT"),
                ("meta_win_prob_pct", "FLOAT"),
                ("volume_24h_usd", "FLOAT"),
                ("spread_bps", "FLOAT")
            ]
            with eng.begin() as conn:
                for col_name, col_type in new_cols:
                    if col_name not in existing_cols:
                        conn.execute(text(f"ALTER TABLE signals_tracker ADD COLUMN {col_name} {col_type}"))
    except Exception as e:
        pass

ensure_schema_compatibility(engine)

# Enable WAL mode and optimized cache for SQLite instances
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-64000")  # 64MB memory cache
        cursor.close()
    except Exception:
        pass

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
