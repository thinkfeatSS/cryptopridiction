"""
QUANT EDGE V16 — LOCAL DELTA-CACHE MANAGER
High-Performance Read-Through Local Delta-Cache for OHLCV Market Data.
Supports both Partitioned Parquet (pyarrow) and SQLite WAL Storage Engines.
Enforces strict atomic persistence, continuous rolling-window pruning (max 3,000 bars),
and zero data corruption across concurrent access.
"""

import os
import sys
import time
import sqlite3
import tempfile
import threading
import logging
from typing import Optional, Tuple, Dict, Any, List
import pandas as pd
import numpy as np

logger = logging.getLogger("QuantEdge.CacheManager")

# Required canonical OHLCV columns and dtypes
REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
DTYPES_MAP = {
    "timestamp": np.int64,
    "open": np.float64,
    "high": np.float64,
    "low": np.float64,
    "close": np.float64,
    "volume": np.float64,
}


class OHLCVCacheManager:
    """
    Manages local disk-backed OHLCV candle storage and delta retrieval.
    Guarantees:
    - Zero lookahead leakage or out-of-order bars.
    - Atomic updates via tempfile + atomic filesystem rename.
    - Dual storage engines: Partitioned Parquet (primary) and SQLite WAL (fallback/configurable).
    - Rolling window capping at max_bars (default 3,000).
    """

    def __init__(
        self,
        base_dir: Optional[str] = None,
        backend: str = "parquet",
        max_bars: int = 3000,
    ):
        """
        Args:
            base_dir: Root cache directory. Defaults to <project_root>/data/cache.
            backend: 'parquet' or 'sqlite'.
            max_bars: Maximum historical bars to retain per symbol/timeframe (default 3000).
        """
        if base_dir is None:
            # Determine project root from this file's path
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            self.base_dir = os.path.join(project_root, "data", "cache")
        else:
            self.base_dir = os.path.abspath(base_dir)

        os.makedirs(self.base_dir, exist_ok=True)
        self.backend = backend.lower()
        self.max_bars = max_bars
        self._lock = threading.RLock()

        # Check pyarrow availability
        self._has_pyarrow = False
        try:
            import pyarrow  # noqa: F401
            self._has_pyarrow = True
        except ImportError:
            if self.backend == "parquet":
                logger.warning("[CACHE] pyarrow not found; falling back to SQLite backend.")
                self.backend = "sqlite"

        # SQLite database path if sqlite backend is used
        self.db_path = os.path.join(self.base_dir, "ohlcv_store.db")
        if self.backend == "sqlite" or not self._has_pyarrow:
            self._init_sqlite_db()

    def _get_sqlite_conn(self) -> sqlite3.Connection:
        """Returns a configured SQLite connection with WAL journal mode."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=10000;")
        return conn

    def _init_sqlite_db(self):
        """Initializes SQLite schema for OHLCV candles."""
        with self._lock:
            with self._get_sqlite_conn() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ohlcv_candles (
                        exchange TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        timeframe TEXT NOT NULL,
                        timestamp INTEGER NOT NULL,
                        open REAL NOT NULL,
                        high REAL NOT NULL,
                        low REAL NOT NULL,
                        close REAL NOT NULL,
                        volume REAL NOT NULL,
                        PRIMARY KEY (exchange, symbol, timeframe, timestamp)
                    ) WITHOUT ROWID;
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_ohlcv_lookup 
                    ON ohlcv_candles (exchange, symbol, timeframe, timestamp DESC);
                    """
                )
                conn.commit()

    @staticmethod
    def sanitize_symbol(symbol: str) -> str:
        """Sanitizes symbol for safe filesystem path (e.g. BTC/USDT -> BTC_USDT)."""
        return symbol.replace("/", "_").replace(":", "_").replace("-", "_").upper()

    def _get_parquet_path(self, exchange: str, symbol: str, timeframe: str) -> str:
        """Returns the file path for a parquet partition."""
        exchange_clean = exchange.lower().strip()
        exchange_dir = os.path.join(self.base_dir, exchange_clean)
        os.makedirs(exchange_dir, exist_ok=True)
        sym_clean = self.sanitize_symbol(symbol)
        tf_clean = timeframe.lower().strip()
        return os.path.join(exchange_dir, f"{sym_clean}_{tf_clean}.parquet")

    @classmethod
    def clean_and_validate_df(cls, df: pd.DataFrame) -> pd.DataFrame:
        """
        Validates column structure, casts to float64, removes duplicate timestamps,
        and enforces ascending chronological order.
        """
        if df is None or df.empty:
            return pd.DataFrame(columns=REQUIRED_COLUMNS)

        df_clean = df.copy()

        # If timestamp is the index, reset it
        if "timestamp" not in df_clean.columns and df_clean.index.name == "timestamp":
            df_clean = df_clean.reset_index()
        elif "timestamp" not in df_clean.columns:
            # Check for alternative timestamp column names
            for col in ["time", "open_time", "datetime", "date"]:
                if col in df_clean.columns:
                    df_clean = df_clean.rename(columns={col: "timestamp"})
                    break

        # Check required columns
        for col in REQUIRED_COLUMNS:
            if col not in df_clean.columns:
                raise ValueError(f"Missing required OHLCV column '{col}' in DataFrame")

        # Select only required columns
        df_clean = df_clean[REQUIRED_COLUMNS].copy()

        # Ensure correct dtypes
        df_clean["timestamp"] = pd.to_numeric(df_clean["timestamp"], errors="coerce").astype(np.int64)
        for col in ["open", "high", "low", "close", "volume"]:
            df_clean[col] = pd.to_numeric(df_clean[col], errors="coerce").astype(np.float64)

        # Drop any row with NaN values in core OHLCV
        df_clean = df_clean.dropna(subset=REQUIRED_COLUMNS)

        # Sort strictly ascending and drop duplicate timestamps keeping last
        df_clean = df_clean.sort_values(by="timestamp", ascending=True)
        df_clean = df_clean.drop_duplicates(subset=["timestamp"], keep="last")
        df_clean = df_clean.reset_index(drop=True)

        return df_clean

    def merge_and_prune(
        self,
        cached_df: Optional[pd.DataFrame],
        new_df: pd.DataFrame,
        max_bars: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Merges newly fetched candles with existing cached candles, deduplicating
        by timestamp and trimming to rolling window max_bars.
        """
        limit_bars = max_bars if max_bars is not None else self.max_bars

        if cached_df is None or cached_df.empty:
            return self.clean_and_validate_df(new_df).iloc[-limit_bars:].reset_index(drop=True)

        if new_df is None or new_df.empty:
            return self.clean_and_validate_df(cached_df).iloc[-limit_bars:].reset_index(drop=True)

        merged = pd.concat([cached_df, new_df], ignore_index=True)
        cleaned = self.clean_and_validate_df(merged)

        if len(cleaned) > limit_bars:
            cleaned = cleaned.iloc[-limit_bars:].reset_index(drop=True)

        return cleaned

    def load_cached_candles(
        self,
        symbol: str,
        timeframe: str,
        exchange: str = "binance",
    ) -> Optional[pd.DataFrame]:
        """
        Loads cached OHLCV candles from local disk storage.
        Returns None if cache does not exist or is empty.
        """
        with self._lock:
            if self.backend == "parquet" and self._has_pyarrow:
                parquet_path = self._get_parquet_path(exchange, symbol, timeframe)
                if not os.path.exists(parquet_path):
                    return None
                try:
                    df = pd.read_parquet(parquet_path, engine="pyarrow")
                    if df.empty:
                        return None
                    return self.clean_and_validate_df(df)
                except Exception as e:
                    logger.warning(f"[CACHE] Error reading Parquet {parquet_path}: {e}")
                    # Fallback to SQLite if parquet read fails
                    return self._load_from_sqlite(exchange, symbol, timeframe)
            else:
                return self._load_from_sqlite(exchange, symbol, timeframe)

    def _load_from_sqlite(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
    ) -> Optional[pd.DataFrame]:
        """Loads cached candles from SQLite database."""
        try:
            with self._get_sqlite_conn() as conn:
                query = """
                    SELECT timestamp, open, high, low, close, volume
                    FROM ohlcv_candles
                    WHERE exchange = ? AND symbol = ? AND timeframe = ?
                    ORDER BY timestamp ASC
                """
                df = pd.read_sql_query(query, conn, params=(exchange.lower(), symbol.upper(), timeframe.lower()))
                if df.empty:
                    return None
                return self.clean_and_validate_df(df)
        except Exception as e:
            logger.error(f"[CACHE] SQLite read error for {symbol} {timeframe}: {e}")
            return None

    def save_candles(
        self,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame,
        exchange: str = "binance",
    ) -> bool:
        """
        Atomically saves candles to local storage.
        Prunes to rolling window max_bars before saving.
        """
        if df is None or df.empty:
            return False

        clean_df = self.clean_and_validate_df(df)
        if len(clean_df) > self.max_bars:
            clean_df = clean_df.iloc[-self.max_bars:].reset_index(drop=True)

        with self._lock:
            success = False
            if self.backend == "parquet" and self._has_pyarrow:
                success = self._save_to_parquet(exchange, symbol, timeframe, clean_df)
                if not success:
                    # Fallback to SQLite
                    success = self._save_to_sqlite(exchange, symbol, timeframe, clean_df)
            else:
                success = self._save_to_sqlite(exchange, symbol, timeframe, clean_df)

            return success

    def _save_to_parquet(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame,
    ) -> bool:
        """Atomically saves DataFrame as compressed Parquet using tempfile + os.replace."""
        target_path = self._get_parquet_path(exchange, symbol, timeframe)
        target_dir = os.path.dirname(target_path)

        temp_file = None
        try:
            # Create a temporary file in the same directory to allow atomic rename
            with tempfile.NamedTemporaryFile(
                dir=target_dir,
                prefix="cache_tmp_",
                suffix=".parquet",
                delete=False,
            ) as tmp:
                temp_file = tmp.name

            # Write DataFrame with pyarrow snappy compression
            df.to_parquet(temp_file, engine="pyarrow", compression="snappy", index=False)

            # Atomic replace
            os.replace(temp_file, target_path)
            return True
        except Exception as e:
            logger.error(f"[CACHE] Error writing Parquet {target_path}: {e}")
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError:
                    pass
            return False

    def _save_to_sqlite(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame,
    ) -> bool:
        """Saves candles to SQLite database using batch insert or replace."""
        try:
            exchange_val = exchange.lower()
            sym_val = symbol.upper()
            tf_val = timeframe.lower()

            records = []
            for _, row in df.iterrows():
                records.append(
                    (
                        exchange_val,
                        sym_val,
                        tf_val,
                        int(row["timestamp"]),
                        float(row["open"]),
                        float(row["high"]),
                        float(row["low"]),
                        float(row["close"]),
                        float(row["volume"]),
                    )
                )

            with self._get_sqlite_conn() as conn:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO ohlcv_candles 
                    (exchange, symbol, timeframe, timestamp, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    records,
                )
                # Prune old records exceeding max_bars for this coin/tf
                conn.execute(
                    """
                    DELETE FROM ohlcv_candles
                    WHERE exchange = ? AND symbol = ? AND timeframe = ?
                      AND timestamp NOT IN (
                          SELECT timestamp FROM ohlcv_candles
                          WHERE exchange = ? AND symbol = ? AND timeframe = ?
                          ORDER BY timestamp DESC
                          LIMIT ?
                      )
                    """,
                    (exchange_val, sym_val, tf_val, exchange_val, sym_val, tf_val, self.max_bars),
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"[CACHE] SQLite write error for {symbol} {timeframe}: {e}")
            return False

    def get_latest_cached_timestamp(
        self,
        symbol: str,
        timeframe: str,
        exchange: str = "binance",
    ) -> Optional[int]:
        """
        Returns the latest (maximum) candle open timestamp in milliseconds.
        Returns None if cache is empty or does not exist.
        """
        with self._lock:
            if self.backend == "parquet" and self._has_pyarrow:
                parquet_path = self._get_parquet_path(exchange, symbol, timeframe)
                if not os.path.exists(parquet_path):
                    return None
                try:
                    import pyarrow.parquet as pq
                    # Fast column metadata read without reading entire file
                    table = pq.read_table(parquet_path, columns=["timestamp"])
                    if len(table) == 0:
                        return None
                    ts_array = table["timestamp"].to_numpy()
                    return int(np.max(ts_array))
                except Exception:
                    df = self.load_cached_candles(symbol, timeframe, exchange)
                    if df is not None and not df.empty:
                        return int(df["timestamp"].max())
                    return None
            else:
                try:
                    with self._get_sqlite_conn() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            """
                            SELECT MAX(timestamp) FROM ohlcv_candles
                            WHERE exchange = ? AND symbol = ? AND timeframe = ?
                            """,
                            (exchange.lower(), symbol.upper(), timeframe.lower()),
                        )
                        res = cursor.fetchone()
                        return int(res[0]) if res and res[0] is not None else None
                except Exception as e:
                    logger.error(f"[CACHE] Error fetching latest timestamp: {e}")
                    return None

    def get_earliest_cached_timestamp(
        self,
        symbol: str,
        timeframe: str,
        exchange: str = "binance",
    ) -> Optional[int]:
        """
        Returns the earliest (minimum) candle open timestamp in milliseconds.
        Returns None if cache is empty or does not exist.
        """
        with self._lock:
            if self.backend == "parquet" and self._has_pyarrow:
                parquet_path = self._get_parquet_path(exchange, symbol, timeframe)
                if not os.path.exists(parquet_path):
                    return None
                try:
                    import pyarrow.parquet as pq
                    table = pq.read_table(parquet_path, columns=["timestamp"])
                    if len(table) == 0:
                        return None
                    ts_array = table["timestamp"].to_numpy()
                    return int(np.min(ts_array))
                except Exception:
                    df = self.load_cached_candles(symbol, timeframe, exchange)
                    if df is not None and not df.empty:
                        return int(df["timestamp"].min())
                    return None
            else:
                try:
                    with self._get_sqlite_conn() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            """
                            SELECT MIN(timestamp) FROM ohlcv_candles
                            WHERE exchange = ? AND symbol = ? AND timeframe = ?
                            """,
                            (exchange.lower(), symbol.upper(), timeframe.lower()),
                        )
                        res = cursor.fetchone()
                        return int(res[0]) if res and res[0] is not None else None
                except Exception as e:
                    logger.error(f"[CACHE] Error fetching earliest timestamp: {e}")
                    return None

    def get_cached_bar_count(
        self,
        symbol: str,
        timeframe: str,
        exchange: str = "binance",
    ) -> int:
        """Returns the number of candles currently cached."""
        with self._lock:
            if self.backend == "parquet" and self._has_pyarrow:
                parquet_path = self._get_parquet_path(exchange, symbol, timeframe)
                if not os.path.exists(parquet_path):
                    return 0
                try:
                    import pyarrow.parquet as pq
                    meta = pq.read_metadata(parquet_path)
                    return meta.num_rows
                except Exception:
                    df = self.load_cached_candles(symbol, timeframe, exchange)
                    return len(df) if df is not None else 0
            else:
                try:
                    with self._get_sqlite_conn() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            """
                            SELECT COUNT(*) FROM ohlcv_candles
                            WHERE exchange = ? AND symbol = ? AND timeframe = ?
                            """,
                            (exchange.lower(), symbol.upper(), timeframe.lower()),
                        )
                        res = cursor.fetchone()
                        return int(res[0]) if res and res[0] is not None else 0
                except Exception:
                    return 0

    def clear_cache(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        exchange: Optional[str] = None,
    ):
        """Clears cached candles matching criteria, or all if none specified."""
        with self._lock:
            if self.backend == "parquet" and self._has_pyarrow:
                exchanges = [exchange.lower()] if exchange else [d for d in os.listdir(self.base_dir) if os.path.isdir(os.path.join(self.base_dir, d))]
                for ex in exchanges:
                    ex_dir = os.path.join(self.base_dir, ex)
                    if not os.path.exists(ex_dir):
                        continue
                    sym_pattern = self.sanitize_symbol(symbol) if symbol else ""
                    tf_pattern = timeframe.lower() if timeframe else ""
                    for f in os.listdir(ex_dir):
                        if not f.endswith(".parquet"):
                            continue
                        match = True
                        if sym_pattern and not f.startswith(f"{sym_pattern}_"):
                            match = False
                        if tf_pattern and not f.endswith(f"_{tf_pattern}.parquet"):
                            match = False
                        if match:
                            try:
                                os.remove(os.path.join(ex_dir, f))
                            except OSError:
                                pass
            # Also clear from SQLite
            if os.path.exists(self.db_path):
                try:
                    with self._get_sqlite_conn() as conn:
                        query = "DELETE FROM ohlcv_candles WHERE 1=1"
                        params = []
                        if exchange:
                            query += " AND exchange = ?"
                            params.append(exchange.lower())
                        if symbol:
                            query += " AND symbol = ?"
                            params.append(symbol.upper())
                        if timeframe:
                            query += " AND timeframe = ?"
                            params.append(timeframe.lower())
                        conn.execute(query, params)
                        conn.commit()
                except Exception as e:
                    logger.error(f"[CACHE] Error clearing SQLite cache: {e}")

