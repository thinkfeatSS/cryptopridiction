from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import sys

from app.config import settings

def get_engine():
    db_url = settings.DATABASE_URL
    # If explicitly using SQLite or MySQL isn't reachable
    try:
        engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False
        )
        # Test connection
        with engine.connect() as conn:
            pass
        print(f"[DATABASE] Connected to MySQL database at {settings.MYSQL_HOST}:{settings.MYSQL_PORT}/{settings.MYSQL_DB}")
        return engine
    except Exception as e:
        print(f"[DATABASE] MySQL server connection not established ({e}). Using local database fallback 'sqlite:///./crypto_trading.db'.")
        fallback_url = "sqlite:///./crypto_trading.db"
        return create_engine(fallback_url, connect_args={"check_same_thread": False})

engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
