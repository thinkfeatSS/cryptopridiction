import os
import time
import threading
import requests
from urllib3.util import Retry
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional, Tuple
from app.engine.config import TIMEFRAMES_9, TIMEFRAME_META
from app.engine.scanner.websocket_feed import ws_feed_manager

BINANCE_HOST_MIRRORS = [
    {"url": "https://data-api.binance.vision/api/v3/klines", "name": "vision", "type": "spot"},
    {"url": "https://api.binance.com/api/v3/klines", "name": "spot_primary", "type": "spot"},
    {"url": "https://api1.binance.com/api/v3/klines", "name": "spot_mirror1", "type": "spot"},
    {"url": "https://api2.binance.com/api/v3/klines", "name": "spot_mirror2", "type": "spot"},
    {"url": "https://api3.binance.com/api/v3/klines", "name": "spot_mirror3", "type": "spot"},
    {"url": "https://fapi.binance.com/fapi/v1/klines", "name": "futures_usd_m", "type": "futures"}
]

BYBIT_KLINES_URL = "https://api.bybit.com/v5/market/kline"
BYBIT_TICKERS_URL = "https://api.bybit.com/v5/market/tickers?category=spot"
BYBIT_TF_MAP = {
    "5m": "5",
    "15m": "15",
    "1h": "60",
    "4h": "240",
    "12h": "720",
    "1d": "D",
    "1w": "W",
    "1M": "M"
}

# Tier-3 OKX Public Market Data Endpoints
OKX_KLINES_URL = "https://www.okx.com/api/v5/market/candles"
OKX_TICKERS_URL = "https://www.okx.com/api/v5/market/tickers?instType=SPOT"
OKX_TF_MAP = {
    "5m": "5m",
    "15m": "15m",
    "1h": "1H",
    "4h": "4H",
    "12h": "12H",
    "1d": "1D",
    "1w": "1W",
    "15d": "1D",
    "1M": "1M"
}

# Tier-3 & Tier-4 Gateway Mirrors for Global Outage Resilience
MEXC_KLINES_URL = "https://api.mexc.com/api/v3/klines"
MEXC_TICKERS_URL = "https://api.mexc.com/api/v3/ticker/price"
MEXC_TF_MAP = {
    "5m": "5m",
    "15m": "15m",
    "1h": "60m",
    "4h": "4h",
    "12h": "4h",  # Resampled from 4h chunk
    "1d": "1d",
    "1w": "1W",
    "1M": "1M"
}

GATEIO_KLINES_URL = "https://api.gateio.ws/api/v4/spot/candlesticks"
GATEIO_TICKERS_URL = "https://api.gateio.ws/api/v4/spot/tickers"
GATEIO_TF_MAP = {
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "12h": "12h",
    "1d": "1d",
    "1w": "7d",
    "1M": "30d"
}

KUCOIN_KLINES_URL = "https://api.kucoin.com/api/v1/market/candles"
KUCOIN_TICKERS_URL = "https://api.kucoin.com/api/v1/market/allTickers"
KUCOIN_TF_MAP = {
    "5m": "5min",
    "15m": "15min",
    "1h": "1hour",
    "4h": "4hour",
    "12h": "12hour",
    "1d": "1day",
    "1w": "1week",
    "15d": "1day",
    "1M": "1week"
}

class MultiHorizonDataLoader:
    """
    High-Performance 9-Timeframe Crypto Data Ingestion Engine.
    Concurrently fetches:
    - 5M, 15M, 1H, 4H, 12H, 24H (1D), 7D (1W), 15D (Resampled), 30D (1M)
    Features:
    - Multi-host failover gateway with automatic circuit breakers
    - Tier-2 Secondary Exchange Gateway (Bybit Public Spot)
    - Persistent Disk-Backed Stale-While-Revalidate (SWR) candle caching
    - Adaptive X-MBX-USED-WEIGHT-1M rate limit governor
    - Bottom-up Hierarchical Candle Pyramid with Hybrid Anchor Back-Stitching
    - Automated transition from synthetic chunks to native klines
    - Upstream Network Partition Defense & NTZ safety triggers
    """

    def __init__(self, max_workers: int = 9):
        self.max_workers = max_workers
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            connect=3,
            read=2,
            backoff_factor=0.25,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
            raise_on_status=False
        )
        adapter = requests.adapters.HTTPAdapter(pool_connections=64, pool_maxsize=64, max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update({
            "User-Agent": "QuantEdge-MultiHorizon-Engine/16.1 (Institutional High-Throughput)"
        })

        self._candle_cache: Dict[str, Tuple[pd.DataFrame, float]] = {}  # key: f"{sym}_{tf}" -> (df, ts)
        self._cache_lock = threading.RLock()
        self._live_tickers_cache: Dict[str, float] = {}
        self._live_tickers_ts: float = 0.0
        self._funding_cache: Dict[str, float] = {}
        self.ws_feed = ws_feed_manager

        # Circuit breaker & rate limit tracking
        self._host_failures: Dict[str, int] = {}
        self._host_cooldowns: Dict[str, float] = {}
        self._last_weight_1m: int = 0
        self._weight_lock = threading.Lock()

        # Upstream partition & global outage defense tracking
        self._is_partition_stale: bool = False
        self._is_global_outage: bool = False
        self._global_outage_reason: str = ""
        self._stale_timeframes_count: int = 0
        self._binance_ip_throttled_until: float = 0.0

        # Strict 15-second price freshness constraint tracking
        self.MAX_LIVE_PRICE_AGE_SECONDS: float = 15.0
        self._is_price_fresh_15s: bool = True
        self._price_freshness_age: float = 0.0
        self._symbol_price_timestamps: Dict[str, float] = {}

        # Regional geo-restriction and Cloudflare/WAF IP block tracking
        self._exchange_geo_cooldowns: Dict[str, float] = {}

        # Tier-6.5 CoinCap public rates cache and rate limiting (<= 1 call per 2.0s)
        self._coincap_rates_cache: Dict[str, float] = {}
        self._coincap_rates_ts: float = 0.0
        self._coincap_throttled_until: float = 0.0
        self.COINCAP_MIN_INTERVAL_SECONDS: float = 2.0

        # Tier-6.6 Coinpaprika global rates cache (fallback on CoinCap 429/DNS drops)
        self._paprika_rates_cache: Dict[str, float] = {}
        self._paprika_rates_ts: float = 0.0
        self._paprika_throttled_until: float = 0.0

        # Persistent disk cache setup
        self._disk_cache_dir = os.path.join(os.environ.get("EXPORT_DIR", "export_app_data"), "candle_cache")
        try:
            os.makedirs(self._disk_cache_dir, exist_ok=True)
        except Exception:
            pass

    def _is_exchange_geo_blocked(self, exchange_name: str) -> bool:
        """Returns True if the upstream exchange is currently in a geo-restriction / cloud IP ban cooldown."""
        with self._cache_lock:
            return time.time() < self._exchange_geo_cooldowns.get(exchange_name.lower(), 0.0)

    def _record_exchange_geo_block(self, exchange_name: str, status_code: int, reason: str = ""):
        """Records an upstream geo-restriction / Cloudflare block, setting a 900s fast-fail circuit breaker."""
        now = time.time()
        with self._cache_lock:
            self._exchange_geo_cooldowns[exchange_name.lower()] = now + 900.0
        print(f"[DATA LOADER [GEO-RESTRICTION CIRCUIT BREAKER]] Upstream {exchange_name.upper()} returned {status_code} ({reason}). Fast-fail bypass active for 900s.", flush=True)

    def preload_bulk_funding_rates(self):
        """Fetches all funding rates with multi-exchange failover (Binance -> Bybit -> Gate.io)."""
        # Tier-1: Binance Futures
        try:
            url = "https://fapi.binance.com/fapi/v1/premiumIndex"
            resp = self.session.get(url, timeout=4.5)
            if resp.status_code == 200:
                data = resp.json()
                for item in data:
                    sym = item.get("symbol")
                    if sym:
                        self._funding_cache[sym] = float(item.get("lastFundingRate", 0.0001))
                if self._funding_cache:
                    return
        except Exception:
            pass

        # Tier-2 Failover: Bybit Linear Tickers (Funding Rates)
        try:
            url = "https://api.bybit.com/v5/market/tickers?category=linear"
            resp = self.session.get(url, timeout=4.5)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("result", {}).get("list", [])
                for it in items:
                    sym = it.get("symbol")
                    fr = it.get("fundingRate")
                    if sym and fr:
                        self._funding_cache[sym] = float(fr)
                if self._funding_cache:
                    print(f"[DATA LOADER [FUNDING TIER-2]] Loaded {len(self._funding_cache)} funding rates from Bybit linear.", flush=True)
                    return
        except Exception:
            pass

        # Tier-3 Failover: Gate.io Futures Contracts
        try:
            url = "https://api.gateio.ws/api/v4/futures/usdt/contracts"
            resp = self.session.get(url, timeout=4.5)
            if resp.status_code == 200:
                data = resp.json()
                for it in data:
                    name = it.get("name", "")
                    fr = it.get("funding_rate")
                    if name and fr:
                        sym = name.replace("_", "")
                        self._funding_cache[sym] = float(fr)
                if self._funding_cache:
                    print(f"[DATA LOADER [FUNDING TIER-3]] Loaded {len(self._funding_cache)} funding rates from Gate.io futures.", flush=True)
                    return
        except Exception:
            pass

        # Tier-4 Failover: KuCoin Futures Active Contracts
        try:
            url = "https://api-futures.kucoin.com/api/v1/contracts/active"
            resp = self.session.get(url, timeout=4.5)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data", [])
                for it in items:
                    sym = it.get("symbol", "")
                    fr = it.get("fundingFeeRate")
                    if sym and fr is not None:
                        clean_sym = sym.replace("USDTM", "USDT").replace("XBT", "BTC")
                        self._funding_cache[clean_sym] = float(fr)
                if self._funding_cache:
                    print(f"[DATA LOADER [FUNDING TIER-4]] Loaded {len(self._funding_cache)} funding rates from KuCoin futures.", flush=True)
                    return
        except Exception:
            pass

    def _save_to_disk_cache(self, key: str, df: pd.DataFrame, ts: float):
        """Persists warm candles to disk for zero-downtime container reboot & partition recovery."""
        try:
            clean_key = key.replace("/", "_").replace(":", "_")
            cache_file = os.path.join(self._disk_cache_dir, f"{clean_key}.pkl")
            df_to_save = df.copy()
            df_to_save.attrs["cache_ts"] = ts
            df_to_save.to_pickle(cache_file)
        except Exception:
            pass

    def _load_from_disk_cache(self, key: str) -> Optional[Tuple[pd.DataFrame, float]]:
        """Loads cached candles from persistent disk."""
        try:
            clean_key = key.replace("/", "_").replace(":", "_")
            cache_file = os.path.join(self._disk_cache_dir, f"{clean_key}.pkl")
            if os.path.exists(cache_file):
                df = pd.read_pickle(cache_file)
                ts = float(df.attrs.get("cache_ts", os.path.getmtime(cache_file)))
                return df, ts
        except Exception:
            pass
        return None

    def _fetch_okx_tickers(self) -> Dict[str, float]:
        """Tier-1.5 Failover: Bulk fetches spot tickers from OKX with mirror support and geo-restriction detection."""
        if self._is_exchange_geo_blocked("okx"):
            return {}
        res = {}
        urls = [
            "https://www.okx.com/api/v5/market/tickers?instType=SPOT",
            "https://aws.okx.com/api/v5/market/tickers?instType=SPOT"
        ]
        for url in urls:
            try:
                resp = self.session.get(url, timeout=3.5)
                if resp.status_code == 200:
                    data = resp.json()
                    msg = str(data.get("msg", "")).lower()
                    code = str(data.get("code", ""))
                    if "access denied" in msg or "restricted" in msg or "jurisdiction" in msg or code in ["50005", "50101"]:
                        self._record_exchange_geo_block("okx", 200, msg or "Geo-restricted IP")
                        return {}
                    if code == "0":
                        ticker_list = data.get("data", [])
                        for it in ticker_list:
                            inst_id = it.get("instId", "")  # e.g. "BTC-USDT"
                            last_p = it.get("last")
                            if inst_id and last_p:
                                p = float(last_p)
                                clean_sym = inst_id.replace("-", "")
                                res[clean_sym] = p
                                if inst_id.endswith("-USDT"):
                                    base = inst_id[:-5]
                                    res[f"{base}/USDT"] = p
                        if res:
                            print(f"[DATA LOADER [TIER-1.5]] Engaged Tier-1.5 OKX Spot Tickers ({len(res)} prices via {url}).", flush=True)
                            return res
                elif resp.status_code in [403, 451]:
                    self._record_exchange_geo_block("okx", resp.status_code, "Geo-restriction/Forbidden")
                    break
            except Exception:
                continue
        return res

    def _fetch_bybit_tickers(self) -> Dict[str, float]:
        """Tier-2 Failover: Bulk fetches spot tickers from Bybit with mirror support and geo-restriction detection."""
        if self._is_exchange_geo_blocked("bybit"):
            return {}
        res = {}
        urls = [
            "https://api.bybit.com/v5/market/tickers?category=spot",
            "https://api.bytick.com/v5/market/tickers?category=spot"
        ]
        for url in urls:
            try:
                resp = self.session.get(url, timeout=3.5)
                if resp.status_code == 200:
                    data = resp.json()
                    ret_code = data.get("retCode")
                    ret_msg = str(data.get("retMsg", "")).lower()
                    if "ip restricted" in ret_msg or "country" in ret_msg or "jurisdiction" in ret_msg or "forbidden" in ret_msg or ret_code in [10006, 10009]:
                        self._record_exchange_geo_block("bybit", 200, ret_msg or "Geo-restricted IP")
                        return {}
                    if ret_code == 0:
                        items = data.get("result", {}).get("list", [])
                        for it in items:
                            sym = it.get("symbol")
                            p_val = it.get("lastPrice")
                            if sym and p_val:
                                p = float(p_val)
                                res[sym] = p
                                if sym.endswith("USDT"):
                                    base = sym[:-4]
                                    res[f"{base}/USDT"] = p
                        if res:
                            print(f"[DATA LOADER [TIER-2]] Engaged Tier-2 Bybit Spot Tickers ({len(res)} prices via {url}).", flush=True)
                            return res
                elif resp.status_code in [403, 451]:
                    self._record_exchange_geo_block("bybit", resp.status_code, "Geo-restriction/Forbidden")
                    break
            except Exception:
                continue
        return res

    def _fetch_bybit_timeframe_raw(self, symbol: str, tf: str, limit: int = 120) -> Optional[pd.DataFrame]:
        """
        Tier-2 Failover Gateway: Fetches public OHLCV candles from Bybit Spot
        with mirror support and geo-restriction detection when Binance experiences outages.
        """
        if self._is_exchange_geo_blocked("bybit"):
            return None
        raw_sym = symbol.replace("/", "").replace(":USDT", "")
        if not raw_sym.endswith("USDT"):
            raw_sym = f"{raw_sym}USDT"

        bybit_interval = BYBIT_TF_MAP.get(tf)
        if not bybit_interval:
            return None

        # 15D is resampled from 1D candles
        fetch_interval = "D" if tf == "15d" else bybit_interval
        fetch_limit = min(1000, limit * 15 if tf == "15d" else limit)

        params = {
            "category": "spot",
            "symbol": raw_sym,
            "interval": fetch_interval,
            "limit": min(200, fetch_limit)
        }
        urls = [
            "https://api.bybit.com/v5/market/kline",
            "https://api.bytick.com/v5/market/kline"
        ]
        for url in urls:
            try:
                resp = self.session.get(url, params=params, timeout=4.5)
                if resp.status_code == 200:
                    data = resp.json()
                    ret_code = data.get("retCode")
                    ret_msg = str(data.get("retMsg", "")).lower()
                    if "ip restricted" in ret_msg or "country" in ret_msg or "jurisdiction" in ret_msg or ret_code in [10006, 10009]:
                        self._record_exchange_geo_block("bybit", 200, ret_msg)
                        return None
                    if ret_code == 0:
                        raw_list = data.get("result", {}).get("list", [])
                        if raw_list and len(raw_list) >= (2 if tf in ["1w", "15d", "1M"] else 5):
                            raw_list = raw_list[::-1]  # Chronological order
                            records = []
                            for c in raw_list:
                                records.append({
                                    "timestamp": int(c[0]),
                                    "open": float(c[1]),
                                    "high": float(c[2]),
                                    "low": float(c[3]),
                                    "close": float(c[4]),
                                    "volume": float(c[5]),
                                    "taker_buy_vol": float(c[5]) * 0.5
                                })
                            df = pd.DataFrame(records)
                            df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                            if tf == "15d":
                                df = self._resample_15d(df)
                            df.attrs["exchange_source"] = "bybit_tier2"
                            print(f"[DATA LOADER [TIER-2]] Engaged Tier-2 Bybit Gateway for {symbol} {tf} ({len(df)} bars via {url}).", flush=True)
                            return df
                elif resp.status_code in [403, 451]:
                    self._record_exchange_geo_block("bybit", resp.status_code, "Geo-restriction/Forbidden")
                    break
            except Exception:
                continue
        return None

    def _fetch_okx_timeframe_raw(self, symbol: str, tf: str, limit: int = 120) -> Optional[pd.DataFrame]:
        """
        Tier-3 Failover Gateway: Fetches public OHLCV candles from OKX Spot
        with mirror support and geo-restriction detection.
        """
        if self._is_exchange_geo_blocked("okx"):
            return None
        raw_sym = symbol.replace("/", "").replace(":USDT", "")
        if raw_sym.endswith("USDT"):
            okx_inst = f"{raw_sym[:-4]}-USDT"
        else:
            okx_inst = f"{raw_sym}-USDT"

        okx_bar = OKX_TF_MAP.get(tf)
        if not okx_bar:
            return None

        fetch_bar = "1D" if tf == "15d" else okx_bar
        fetch_limit = min(100, limit * 15 if tf == "15d" else limit)

        params = {
            "instId": okx_inst,
            "bar": fetch_bar,
            "limit": min(100, fetch_limit)
        }
        urls = [
            "https://www.okx.com/api/v5/market/candles",
            "https://aws.okx.com/api/v5/market/candles"
        ]
        for url in urls:
            try:
                resp = self.session.get(url, params=params, timeout=4.5)
                if resp.status_code == 200:
                    data = resp.json()
                    msg = str(data.get("msg", "")).lower()
                    code = str(data.get("code", ""))
                    if "access denied" in msg or "restricted" in msg or "jurisdiction" in msg or code in ["50005", "50101"]:
                        self._record_exchange_geo_block("okx", 200, msg or "Geo-restricted IP")
                        return None
                    if code == "0":
                        raw_list = data.get("data", [])
                        if raw_list and len(raw_list) >= (2 if tf in ["1w", "15d", "1M"] else 5):
                            raw_list = raw_list[::-1]
                            records = []
                            for c in raw_list:
                                records.append({
                                    "timestamp": int(c[0]),
                                    "open": float(c[1]),
                                    "high": float(c[2]),
                                    "low": float(c[3]),
                                    "close": float(c[4]),
                                    "volume": float(c[5]),
                                    "taker_buy_vol": float(c[5]) * 0.5
                                })
                            df = pd.DataFrame(records)
                            df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                            if tf == "15d":
                                df = self._resample_15d(df)
                            df.attrs["exchange_source"] = "okx_tier3"
                            print(f"[DATA LOADER [TIER-3]] Engaged Tier-3 OKX Gateway for {symbol} {tf} ({len(df)} bars via {url}).", flush=True)
                            return df
                elif resp.status_code in [403, 451]:
                    self._record_exchange_geo_block("okx", resp.status_code, "Geo-restriction/Forbidden")
                    break
            except Exception:
                continue
        return None

    def _fetch_mexc_tickers(self) -> Dict[str, float]:
        """Tier-6 Failover: Bulk fetches spot tickers from MEXC with geo-restriction detection."""
        if self._is_exchange_geo_blocked("mexc"):
            return {}
        res = {}
        try:
            resp = self.session.get(MEXC_TICKERS_URL, timeout=4.5)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and ("restricted" in str(data).lower() or "forbidden" in str(data).lower() or "access denied" in str(data).lower()):
                    self._record_exchange_geo_block("mexc", 200, str(data.get("msg", "")))
                    return {}
                if isinstance(data, list):
                    for it in data:
                        sym = it.get("symbol")
                        p_val = it.get("price")
                        if sym and p_val:
                            p = float(p_val)
                            res[sym] = p
                            if sym.endswith("USDT"):
                                base = sym[:-4]
                                res[f"{base}/USDT"] = p
                    if res:
                        print(f"[DATA LOADER [TIER-6]] Engaged Tier-6 MEXC Spot Tickers ({len(res)} prices).", flush=True)
            elif resp.status_code in [403, 451]:
                self._record_exchange_geo_block("mexc", resp.status_code, "Geo-restriction/Forbidden")
        except Exception:
            pass
        return res

    def _fetch_gateio_tickers(self) -> Dict[str, float]:
        """Tier-4 Failover: Bulk fetches spot tickers from Gate.io with geo-restriction detection."""
        if self._is_exchange_geo_blocked("gateio"):
            return {}
        res = {}
        try:
            resp = self.session.get(GATEIO_TICKERS_URL, timeout=4.5)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and ("restricted" in str(data).lower() or "forbidden" in str(data).lower() or "access denied" in str(data).lower()):
                    self._record_exchange_geo_block("gateio", 200, str(data.get("message", "")))
                    return {}
                if isinstance(data, list):
                    for it in data:
                        cp = it.get("currency_pair")
                        last_p = it.get("last")
                        if cp and last_p:
                            p = float(last_p)
                            sym = cp.replace("_", "")
                            res[sym] = p
                            if cp.endswith("_USDT"):
                                base = cp.replace("_USDT", "")
                                res[f"{base}/USDT"] = p
                    if res:
                        print(f"[DATA LOADER [TIER-4]] Engaged Tier-4 Gate.io Spot Tickers ({len(res)} prices).", flush=True)
            elif resp.status_code in [403, 451]:
                self._record_exchange_geo_block("gateio", resp.status_code, "Geo-restriction/Forbidden")
        except Exception:
            pass
        return res

    def _fetch_mexc_timeframe_raw(self, symbol: str, tf: str, limit: int = 120) -> Optional[pd.DataFrame]:
        """Tier-6 Failover Gateway: Fetches public OHLCV candles from MEXC Spot with geo-restriction detection."""
        if self._is_exchange_geo_blocked("mexc"):
            return None
        raw_sym = symbol.replace("/", "").replace(":USDT", "")
        if not raw_sym.endswith("USDT"):
            raw_sym = f"{raw_sym}USDT"

        mexc_interval = MEXC_TF_MAP.get(tf)
        if not mexc_interval:
            return None

        fetch_tf = "1d" if tf == "15d" else mexc_interval
        fetch_limit = min(1000, limit * 15 if tf == "15d" else (limit * 3 if tf == "12h" else limit))

        params = {"symbol": raw_sym, "interval": fetch_tf, "limit": min(500, fetch_limit)}
        try:
            resp = self.session.get(MEXC_KLINES_URL, params=params, timeout=4.5)
            if resp.status_code == 200:
                raw_candles = resp.json()
                if isinstance(raw_candles, dict) and ("restricted" in str(raw_candles).lower() or "forbidden" in str(raw_candles).lower()):
                    self._record_exchange_geo_block("mexc", 200, str(raw_candles.get("msg", "")))
                    return None
                if raw_candles and isinstance(raw_candles, list) and len(raw_candles) >= (2 if tf in ["1w", "15d", "1M"] else 5):
                    records = []
                    for c in raw_candles:
                        records.append({
                            "timestamp": int(c[0]),
                            "open": float(c[1]),
                            "high": float(c[2]),
                            "low": float(c[3]),
                            "close": float(c[4]),
                            "volume": float(c[5]),
                            "taker_buy_vol": float(c[5]) * 0.5
                        })
                    df = pd.DataFrame(records)
                    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                    if tf == "15d":
                        df = self._resample_15d(df)
                    elif tf == "12h" and mexc_interval == "4h":
                        df = self._resample_chunk(df, chunk_size=3)
                    df.attrs["exchange_source"] = "mexc_tier3"
                    print(f"[DATA LOADER [TIER-6]] Engaged Tier-6 MEXC Gateway for {symbol} {tf} ({len(df)} bars).", flush=True)
                    return df
            elif resp.status_code in [403, 451]:
                self._record_exchange_geo_block("mexc", resp.status_code, "Geo-restriction/Forbidden")
        except Exception:
            pass
        return None

    def _fetch_gateio_timeframe_raw(self, symbol: str, tf: str, limit: int = 120) -> Optional[pd.DataFrame]:
        """Tier-4 Failover Gateway: Fetches public OHLCV candles from Gate.io Spot with geo-restriction detection."""
        if self._is_exchange_geo_blocked("gateio"):
            return None
        raw_sym = symbol.replace("/", "").replace(":USDT", "")
        if not raw_sym.endswith("USDT"):
            raw_sym = f"{raw_sym}USDT"
        gate_cp = f"{raw_sym[:-4]}_USDT" if raw_sym.endswith("USDT") else f"{raw_sym}_USDT"

        gate_interval = GATEIO_TF_MAP.get(tf)
        if not gate_interval:
            return None

        fetch_tf = "1d" if tf == "15d" else gate_interval
        fetch_limit = min(1000, limit * 15 if tf == "15d" else limit)

        params = {"currency_pair": gate_cp, "interval": fetch_tf, "limit": min(500, fetch_limit)}
        try:
            resp = self.session.get(GATEIO_KLINES_URL, params=params, timeout=4.5)
            if resp.status_code == 200:
                raw_candles = resp.json()
                if isinstance(raw_candles, dict) and ("restricted" in str(raw_candles).lower() or "forbidden" in str(raw_candles).lower()):
                    self._record_exchange_geo_block("gateio", 200, str(raw_candles.get("message", "")))
                    return None
                if raw_candles and isinstance(raw_candles, list) and len(raw_candles) >= (2 if tf in ["1w", "15d", "1M"] else 5):
                    # Gate.io returns newest first: [ [t_sec, vol, close, high, low, open], ... ]
                    raw_candles = raw_candles[::-1]
                    records = []
                    for c in raw_candles:
                        records.append({
                            "timestamp": int(c[0]) * 1000,
                            "open": float(c[5]),
                            "high": float(c[3]),
                            "low": float(c[4]),
                            "close": float(c[2]),
                            "volume": float(c[1]),
                            "taker_buy_vol": float(c[1]) * 0.5
                        })
                    df = pd.DataFrame(records)
                    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                    if tf == "15d":
                        df = self._resample_15d(df)
                    df.attrs["exchange_source"] = "gateio_tier4"
                    print(f"[DATA LOADER [TIER-4]] Engaged Tier-4 Gate.io Gateway for {symbol} {tf} ({len(df)} bars).", flush=True)
                    return df
            elif resp.status_code in [403, 451]:
                self._record_exchange_geo_block("gateio", resp.status_code, "Geo-restriction/Forbidden")
        except Exception:
            pass
        return None

    def _fetch_kucoin_tickers(self) -> Dict[str, float]:
        """Tier-5 Failover: Bulk fetches spot tickers from KuCoin with geo-restriction detection."""
        if self._is_exchange_geo_blocked("kucoin"):
            return {}
        res = {}
        try:
            resp = self.session.get(KUCOIN_TICKERS_URL, timeout=4.5)
            if resp.status_code == 200:
                data = resp.json()
                msg = str(data.get("msg", "")).lower()
                if "forbidden" in msg or "restricted" in msg or "access denied" in msg or str(data.get("code")) in ["400003"]:
                    self._record_exchange_geo_block("kucoin", 200, msg or "Geo-restricted IP")
                    return {}
                if data.get("code") == "200000":
                    ticker_list = data.get("data", {}).get("ticker", [])
                    for it in ticker_list:
                        sym = it.get("symbol")
                        last_p = it.get("last")
                        if sym and last_p:
                            p = float(last_p)
                            clean_sym = sym.replace("-", "")
                            res[clean_sym] = p
                            if sym.endswith("-USDT"):
                                base = sym[:-5]
                                res[f"{base}/USDT"] = p
                    if res:
                        print(f"[DATA LOADER [TIER-5]] Engaged Tier-5 KuCoin Spot Tickers ({len(res)} prices).", flush=True)
            elif resp.status_code in [403, 451]:
                self._record_exchange_geo_block("kucoin", resp.status_code, "Geo-restriction/Forbidden")
        except Exception:
            pass
        return res

    def _fetch_kucoin_timeframe_raw(self, symbol: str, tf: str, limit: int = 120) -> Optional[pd.DataFrame]:
        """Tier-5 Failover Gateway: Fetches public OHLCV candles from KuCoin Spot with geo-restriction detection."""
        if self._is_exchange_geo_blocked("kucoin"):
            return None
        raw_sym = symbol.replace("/", "").replace(":USDT", "")
        if not raw_sym.endswith("USDT"):
            raw_sym = f"{raw_sym}USDT"
        kc_sym = f"{raw_sym[:-4]}-USDT" if raw_sym.endswith("USDT") else f"{raw_sym}-USDT"

        kc_interval = KUCOIN_TF_MAP.get(tf)
        if not kc_interval:
            return None

        fetch_tf = "1day" if tf == "15d" else kc_interval
        params = {"symbol": kc_sym, "type": fetch_tf}
        try:
            resp = self.session.get(KUCOIN_KLINES_URL, params=params, timeout=4.5)
            if resp.status_code == 200:
                data = resp.json()
                msg = str(data.get("msg", "")).lower()
                if "forbidden" in msg or "restricted" in msg or "access denied" in msg or str(data.get("code")) in ["400003"]:
                    self._record_exchange_geo_block("kucoin", 200, msg or "Geo-restricted IP")
                    return None
                if data.get("code") == "200000":
                    raw_candles = data.get("data", [])
                    if raw_candles and isinstance(raw_candles, list) and len(raw_candles) >= (2 if tf in ["1w", "15d", "1M"] else 5):
                        # KuCoin returns newest first: [ [time_sec, open, close, high, low, volume, turnover], ... ]
                        raw_candles = raw_candles[::-1]
                        records = []
                        for c in raw_candles:
                            records.append({
                                "timestamp": int(c[0]) * 1000,
                                "open": float(c[1]),
                                "high": float(c[3]),
                                "low": float(c[4]),
                                "close": float(c[2]),
                                "volume": float(c[5]),
                                "taker_buy_vol": float(c[5]) * 0.5
                            })
                        df = pd.DataFrame(records)
                        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                        if tf == "15d":
                            df = self._resample_15d(df)
                        elif tf == "1M" and kc_interval == "1week":
                            df = self._resample_chunk(df, chunk_size=4)
                        df.attrs["exchange_source"] = "kucoin_tier5"
                        print(f"[DATA LOADER [TIER-5]] Engaged Tier-5 KuCoin Gateway for {symbol} {tf} ({len(df)} bars).", flush=True)
                        return df
            elif resp.status_code in [403, 451]:
                self._record_exchange_geo_block("kucoin", resp.status_code, "Geo-restriction/Forbidden")
        except Exception:
            pass
        return None

    def _fetch_coincap_tickers(self) -> Dict[str, float]:
        """
        Tier-6.5 Failover: Global decentralized price aggregator (CoinCap API) when all CEX endpoints are geo-fenced.
        Operates without API key; strictly throttled to <= 1 call per 2.0s with 60s backoff on HTTP 429.
        """
        now = time.time()
        # 1. Enforce public rate limit cooldown: <= 1 call per 2.0s
        if (now - getattr(self, '_coincap_rates_ts', 0.0)) < getattr(self, 'COINCAP_MIN_INTERVAL_SECONDS', 2.0) and getattr(self, '_coincap_rates_cache', None):
            return self._coincap_rates_cache.copy()

        # 2. Check 429 backoff cooldown (60 seconds)
        if now < getattr(self, '_coincap_throttled_until', 0.0):
            return getattr(self, '_coincap_rates_cache', {}).copy()

        res = {}
        try:
            url = "https://api.coincap.io/v2/rates"
            resp = self.session.get(url, timeout=3.5)
            if resp.status_code == 200:
                data = resp.json()
                for it in data.get("data", []):
                    sym = it.get("symbol")
                    rate_usd = it.get("rateUsd")
                    if sym and rate_usd:
                        p = float(rate_usd)
                        res[f"{sym}USDT"] = p
                        res[f"{sym}/USDT"] = p
                        res[f"{sym}/USDT:USDT"] = p
                if res:
                    self._coincap_rates_cache = res
                    self._coincap_rates_ts = now
                    print(f"[DATA LOADER [TIER-6.5]] Engaged CoinCap Global Rates Aggregator ({len(res)} prices).", flush=True)
            elif resp.status_code == 429:
                self._coincap_throttled_until = now + 60.0
                print(f"[DATA LOADER [TIER-6.5]] CoinCap public endpoint rate-limited (HTTP 429). 60s backoff active.", flush=True)
                return getattr(self, '_coincap_rates_cache', {}).copy()
        except Exception:
            pass

        if res:
            return res
        return getattr(self, '_coincap_rates_cache', {}).copy()

    def _fetch_coinpaprika_tickers(self) -> Dict[str, float]:
        """
        Tier-6.6 Failover: Coinpaprika Global Price Aggregator (2000+ USD pairs).
        Engaged when CEX endpoints and Tier-6.5 CoinCap are rate-limited or experiencing network drops.
        """
        now = time.time()
        if (now - getattr(self, '_paprika_rates_ts', 0.0)) < 3.0 and getattr(self, '_paprika_rates_cache', None):
            return self._paprika_rates_cache.copy()

        if now < getattr(self, '_paprika_throttled_until', 0.0):
            return getattr(self, '_paprika_rates_cache', {}).copy()

        res = {}
        try:
            url = "https://api.coinpaprika.com/v1/tickers"
            resp = self.session.get(url, timeout=3.5)
            if resp.status_code == 200:
                data = resp.json()
                for it in data:
                    sym = it.get("symbol")
                    p_usd = it.get("quotes", {}).get("USD", {}).get("price")
                    if sym and p_usd and float(p_usd) > 0:
                        p = float(p_usd)
                        res[f"{sym}USDT"] = p
                        res[f"{sym}/USDT"] = p
                        res[f"{sym}/USDT:USDT"] = p
                if res:
                    self._paprika_rates_cache = res
                    self._paprika_rates_ts = now
                    print(f"[DATA LOADER [TIER-6.6]] Engaged Coinpaprika Global Rates Aggregator ({len(res)} prices).", flush=True)
            elif resp.status_code == 429:
                self._paprika_throttled_until = now + 60.0
                return getattr(self, '_paprika_rates_cache', {}).copy()
        except Exception:
            pass

        return res or getattr(self, '_paprika_rates_cache', {}).copy()


    def _backfill_historical_macro_candles(self, symbol: str, tf: str, df_binance: pd.DataFrame) -> pd.DataFrame:
        """
        Backfills pre-listing historical candles from secondary gateways (Bybit, MEXC)
        when a newly listed token on Binance has sparse macro candles (len < 30 for 1d, 1w, 1M).
        Stitches pre-listing historical prefix before Binance's listing date.
        """
        if df_binance is None or len(df_binance) == 0:
            return df_binance
        if tf not in ["1d", "1w", "1M"] or len(df_binance) >= 30:
            return df_binance

        first_ts = int(df_binance["timestamp"].iloc[0])

        # Try Bybit first, then MEXC, Gate.io, and KuCoin
        df_sec = self._fetch_bybit_timeframe_raw(symbol, tf, limit=200)
        if df_sec is None or len(df_sec) == 0:
            df_sec = self._fetch_mexc_timeframe_raw(symbol, tf, limit=200)
        if df_sec is None or len(df_sec) == 0:
            df_sec = self._fetch_gateio_timeframe_raw(symbol, tf, limit=200)
        if df_sec is None or len(df_sec) == 0:
            df_sec = self._fetch_kucoin_timeframe_raw(symbol, tf, limit=200)

        if df_sec is not None and len(df_sec) > 0:
            pre_listing = df_sec[df_sec["timestamp"] < first_ts]
            if len(pre_listing) > 0:
                stitched = pd.concat([pre_listing, df_binance], ignore_index=True)
                stitched.sort_values("timestamp", inplace=True)
                stitched.drop_duplicates(subset=["timestamp"], keep="last", inplace=True)
                stitched.reset_index(drop=True, inplace=True)
                stitched.attrs["is_synthetic"] = False
                stitched.attrs["is_backfilled"] = True
                stitched.attrs["native_candle_count"] = len(stitched)
                stitched.attrs["exchange_source"] = f"stitched_{df_sec.attrs.get('exchange_source', 'secondary')}_binance"
                print(f"[DATA LOADER [BACKFILL]] Stitched {len(pre_listing)} pre-listing {tf} bars for {symbol} (Total: {len(stitched)} bars).", flush=True)
                return stitched

        return df_binance

    def is_partition_stale_active(self) -> bool:
        """Returns True if upstream exchange partition or global multi-exchange outage is active."""
        with self._cache_lock:
            return self._is_partition_stale or self._is_global_outage

    def get_partition_status(self) -> Dict[str, Any]:
        """Provides partition health metrics for dashboard and telemetry."""
        with self._cache_lock:
            return {
                "is_partition_stale": self._is_partition_stale or self._is_global_outage,
                "is_global_outage": self._is_global_outage,
                "global_outage_reason": self._global_outage_reason,
                "stale_timeframes_count": self._stale_timeframes_count,
                "cached_symbols_count": len(self._candle_cache),
                "last_weight_1m": self._last_weight_1m,
                "host_failures": dict(self._host_failures)
            }

    def start_websocket_feed(self):
        """Starts the decoupled sub-second real-time WebSocket market data feed."""
        if self.ws_feed:
            self.ws_feed.start()

    def stop_websocket_feed(self):
        """Stops the real-time WebSocket feed cleanly."""
        if self.ws_feed:
            self.ws_feed.stop()

    def get_feed_latency_ms(self) -> float:
        """Returns the current market data feed latency in milliseconds."""
        if self.ws_feed and self.ws_feed.is_healthy():
            return self.ws_feed.get_latency_ms()
        with self._cache_lock:
            if self._live_tickers_ts > 0:
                return round((time.time() - self._live_tickers_ts) * 1000.0, 1)
        return 9999.0

    def fetch_all_tickers(self, max_age_seconds: float = 1.0) -> Dict[str, float]:
        """Fetches all live prices with ultra-low latency: Tier-0 WebSocket -> Tier-1 Binance REST -> Tier-1.5 OKX -> Bybit -> MEXC -> Gate.io -> KuCoin -> Cache."""
        now = time.time()
        # Tier-0: Real-Time WebSocket stream (<500ms latency, 0ms HTTP round-trip)
        if self.ws_feed and self.ws_feed.is_healthy():
            ws_ticks = self.ws_feed.get_prices()
            if ws_ticks and len(ws_ticks) > 10:
                with self._cache_lock:
                    self._live_tickers_cache = ws_ticks
                    self._live_tickers_ts = self.ws_feed.last_update_ts
                    self._is_price_fresh_15s = True
                    self._price_freshness_age = max(0.0, now - self._live_tickers_ts)
                    self._is_global_outage = False
                    for s in ws_ticks:
                        self._symbol_price_timestamps[s] = self._live_tickers_ts
                return ws_ticks

        with self._cache_lock:
            if self._live_tickers_cache and (now - self._live_tickers_ts) < max_age_seconds:
                return self._live_tickers_cache.copy()

        binance_ip_blocked = False
        with self._weight_lock:
            binance_ip_blocked = (now < self._binance_ip_throttled_until)

        data = None
        if not binance_ip_blocked:
            urls = [
                "https://data-api.binance.vision/api/v3/ticker/price",
                "https://api.binance.com/api/v3/ticker/price",
                "https://api1.binance.com/api/v3/ticker/price",
                "https://api2.binance.com/api/v3/ticker/price",
                "https://api3.binance.com/api/v3/ticker/price",
                "https://fapi.binance.com/fapi/v1/ticker/price"
            ]
            all_rate_limited = True
            for u in urls:
                # Skip mirror if currently in host cooldown
                if now < self._host_cooldowns.get(u, 0.0):
                    continue
                try:
                    r = self.session.get(u, timeout=1.8)
                    if r.status_code == 200:
                        data = r.json()
                        all_rate_limited = False
                        break
                    elif r.status_code in [403, 418, 429]:
                        # Cooldown only this specific mirror, then try remaining mirrors (including futures!)
                        self._host_cooldowns[u] = now + 45.0
                        continue
                    else:
                        all_rate_limited = False
                except Exception:
                    all_rate_limited = False
                    continue

            # Only trip total Binance IP ban if ALL mirrors were rate-limited or blocked
            if all_rate_limited and not data:
                with self._weight_lock:
                    self._binance_ip_throttled_until = now + 90.0

        if data and isinstance(data, list):
            res = {}
            for item in data:
                sym = item.get("symbol")
                price_val = item.get("price")
                if sym and price_val:
                    p = float(price_val)
                    res[sym] = p
                    if sym.endswith("USDT"):
                        base = sym[:-4]
                        res[f"{base}/USDT"] = p
            with self._cache_lock:
                self._live_tickers_cache = res
                self._live_tickers_ts = now
                self._is_price_fresh_15s = True
                self._price_freshness_age = 0.0
                self._is_global_outage = False
                for s in res:
                    self._symbol_price_timestamps[s] = now
            return res

        # Tier-2 Failover: Bybit Tickers
        bybit_ticks = self._fetch_bybit_tickers()
        if bybit_ticks:
            with self._cache_lock:
                self._live_tickers_cache = bybit_ticks
                self._live_tickers_ts = now
                self._is_price_fresh_15s = True
                self._price_freshness_age = 0.0
                self._is_global_outage = False
                for s in bybit_ticks:
                    self._symbol_price_timestamps[s] = now
            return bybit_ticks

        # Tier-3 Failover: OKX Tickers
        okx_ticks = self._fetch_okx_tickers()
        if okx_ticks:
            with self._cache_lock:
                self._live_tickers_cache = okx_ticks
                self._live_tickers_ts = now
                self._is_price_fresh_15s = True
                self._price_freshness_age = 0.0
                self._is_global_outage = False
                for s in okx_ticks:
                    self._symbol_price_timestamps[s] = now
            return okx_ticks

        # Tier-4 Failover: Gate.io Tickers
        gate_ticks = self._fetch_gateio_tickers()
        if gate_ticks:
            with self._cache_lock:
                self._live_tickers_cache = gate_ticks
                self._live_tickers_ts = now
                self._is_price_fresh_15s = True
                self._price_freshness_age = 0.0
                self._is_global_outage = False
                for s in gate_ticks:
                    self._symbol_price_timestamps[s] = now
            return gate_ticks

        # Tier-5 Failover: KuCoin Tickers
        kucoin_ticks = self._fetch_kucoin_tickers()
        if kucoin_ticks:
            with self._cache_lock:
                self._live_tickers_cache = kucoin_ticks
                self._live_tickers_ts = now
                self._is_price_fresh_15s = True
                self._price_freshness_age = 0.0
                self._is_global_outage = False
                for s in kucoin_ticks:
                    self._symbol_price_timestamps[s] = now
            return kucoin_ticks

        # Tier-6 Failover: MEXC Tickers
        mexc_ticks = self._fetch_mexc_tickers()
        if mexc_ticks:
            with self._cache_lock:
                self._live_tickers_cache = mexc_ticks
                self._live_tickers_ts = now
                self._is_price_fresh_15s = True
                self._price_freshness_age = 0.0
                self._is_global_outage = False
                for s in mexc_ticks:
                    self._symbol_price_timestamps[s] = now
            return mexc_ticks

        # Tier-6.5 Failover: Global Decentralized Price Aggregator (CoinCap)
        coincap_ticks = self._fetch_coincap_tickers()
        if coincap_ticks:
            with self._cache_lock:
                self._live_tickers_cache = coincap_ticks
                self._live_tickers_ts = now
                self._is_price_fresh_15s = True
                self._price_freshness_age = 0.0
                self._is_global_outage = False
                for s in coincap_ticks:
                    self._symbol_price_timestamps[s] = now
            return coincap_ticks

        # Tier-6.6 Failover: Coinpaprika Global Rates Aggregator (Fallback on CoinCap 429/DNS drops)
        paprika_ticks = self._fetch_coinpaprika_tickers()
        if paprika_ticks:
            with self._cache_lock:
                self._live_tickers_cache = paprika_ticks
                self._live_tickers_ts = now
                self._is_price_fresh_15s = True
                self._price_freshness_age = 0.0
                self._is_global_outage = False
                for s in paprika_ticks:
                    self._symbol_price_timestamps[s] = now
            return paprika_ticks

        # Catastrophic Global Multi-Exchange Outage / Multi-Exchange Rate Limiting
        cache_age = max(0.0, now - self._live_tickers_ts) if self._live_tickers_ts > 0 else 999.0
        is_fresh = (cache_age <= self.MAX_LIVE_PRICE_AGE_SECONDS) and bool(self._live_tickers_cache)

        with self._cache_lock:
            self._is_price_fresh_15s = is_fresh
            self._price_freshness_age = cache_age
            if not is_fresh:
                self._is_global_outage = True
                self._global_outage_reason = (
                    f"PRICE_STALENESS_EXCEEDED: Live market ticker freshness ({cache_age:.1f}s) "
                    f"exceeded {self.MAX_LIVE_PRICE_AGE_SECONDS:.0f}s maximum constraint. "
                    "All upstream exchange gateways rate-limited or unreachable. Holding entries."
                )
                print(f"[DATA LOADER [PRICE STALENESS CRITICAL]] {self._global_outage_reason}", flush=True)
            else:
                print(f"[DATA LOADER [RATE-LIMIT RECOVERY]] Serving warm cached prices ({cache_age:.1f}s <= 15.0s constraint) while upstream gateways rate-limited.", flush=True)
            return self._live_tickers_cache.copy()

    def get_live_price(self, symbol: str) -> float:
        tickers = self.fetch_all_tickers(max_age_seconds=2.0)
        raw_s = symbol.replace("/", "").replace(":USDT", "")
        return float(tickers.get(symbol) or tickers.get(raw_s) or 0.0)

    def get_live_price_with_freshness(self, symbol: str) -> Tuple[float, bool, float]:
        """
        Returns (live_price, is_fresh_15s, age_seconds).
        Guarantees that live price freshness remains strictly within 15 seconds during exchange rate-limiting.
        """
        now = time.time()
        tickers = self.fetch_all_tickers(max_age_seconds=2.0)
        raw_s = symbol.replace("/", "").replace(":USDT", "")
        price = float(tickers.get(symbol) or tickers.get(raw_s) or 0.0)
        with self._cache_lock:
            sym_ts = self._symbol_price_timestamps.get(symbol) or self._symbol_price_timestamps.get(raw_s) or self._live_tickers_ts
            age = max(0.0, now - sym_ts) if sym_ts > 0 else 999.0
            is_fresh = (age <= self.MAX_LIVE_PRICE_AGE_SECONDS) and (price > 0)
        return price, is_fresh, age

    def fetch_single_timeframe_raw(self, symbol: str, tf: str, limit: int = 120) -> Optional[pd.DataFrame]:
        """
        Fetches OHLCV candles with multi-host failover gateway, circuit breakers,
        and adaptive X-MBX-USED-WEIGHT-1M rate limit governor.
        """
        raw_sym = symbol.replace("/", "").replace(":USDT", "")
        native_tf = TIMEFRAME_META.get(tf, {}).get("binance_tf", tf)

        # 15D is resampled from 1D candles
        fetch_tf = "1d" if tf == "15d" else native_tf
        fetch_limit = min(365, limit * 15 if tf == "15d" else limit)
        now = time.time()

        with self._weight_lock:
            binance_ip_blocked = (now < self._binance_ip_throttled_until)

        if not binance_ip_blocked:
            for mirror in BINANCE_HOST_MIRRORS:
                host_name = mirror["name"]
                url = mirror["url"]

                # Circuit Breaker Check: Skip hosts under active cooldown
                cooldown_expiry = self._host_cooldowns.get(host_name, 0.0)
                if now < cooldown_expiry:
                    continue

                # Adaptive Governor Check: If IP weight is critical (>4800/6000), skip low-priority macro timeframes on spot
                with self._weight_lock:
                    current_weight = self._last_weight_1m
                if current_weight > 4800 and tf in ["1w", "15d", "1M"] and mirror["type"] == "spot":
                    continue

                params = {"symbol": raw_sym, "interval": fetch_tf, "limit": fetch_limit}

                try:
                    resp = self.session.get(url, params=params, timeout=4.5)

                    # Track X-MBX-USED-WEIGHT-1M header
                    weight_hdr = resp.headers.get("X-MBX-USED-WEIGHT-1M") or resp.headers.get("x-mbx-used-weight-1m")
                    if weight_hdr:
                        try:
                            w_val = int(weight_hdr)
                            with self._weight_lock:
                                self._last_weight_1m = w_val
                        except Exception:
                            pass

                    if resp.status_code == 200:
                        # Successful request: Reset failure count for this host
                        self._host_failures[host_name] = 0
                        raw_candles = resp.json()
                        if not raw_candles or not isinstance(raw_candles, list):
                            continue

                        records = []
                        for c in raw_candles:
                            records.append({
                                "timestamp": int(c[0]),
                                "open": float(c[1]),
                                "high": float(c[2]),
                                "low": float(c[3]),
                                "close": float(c[4]),
                                "volume": float(c[5]),
                                "taker_buy_vol": float(c[9]) if len(c) > 9 else float(c[5]) * 0.5
                            })

                        df = pd.DataFrame(records)
                        if df.empty or len(df) < (2 if tf in ["1w", "15d", "1M"] else 5):
                            continue

                        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                        if tf == "15d":
                            df = self._resample_15d(df)

                        # Seamless Historical Backfill for newly listed tokens with sparse macro candles
                        if tf in ["1d", "1w", "1M"] and len(df) < 30:
                            df = self._backfill_historical_macro_candles(symbol, tf, df)

                        return df

                    elif resp.status_code in [403, 418]:
                        # Cloudflare WAF IP Block or Binance IP Ban: Fast-path failover to Tier-2 Bybit & Tier-3 MEXC
                        cooldown = 180.0
                        with self._weight_lock:
                            self._binance_ip_throttled_until = now + cooldown
                        print(f"[DATA LOADER [IP BLOCK {resp.status_code}]] Cloudflare/IP block detected on {host_name}. Shifting all requests to Tier-2 Bybit & Tier-3 MEXC for {cooldown:.0f}s.", flush=True)
                        break

                    elif resp.status_code == 429:
                        # Rate limit exceeded: Respect Retry-After header and cooldown host
                        retry_after = 60.0
                        try:
                            ra = resp.headers.get("Retry-After")
                            if ra:
                                retry_after = max(10.0, float(ra))
                        except Exception:
                            pass
                        self._host_cooldowns[host_name] = now + retry_after
                        failures = self._host_failures.get(host_name, 0) + 1
                        self._host_failures[host_name] = failures
                        if failures >= 2:
                            with self._weight_lock:
                                self._binance_ip_throttled_until = now + retry_after
                            print(f"[DATA LOADER [IP THROTTLE 429]] Multiple Binance mirrors rate limited. Shifting traffic to Tier-2 Bybit & Tier-3 MEXC for {retry_after:.0f}s.", flush=True)
                            break
                        continue

                    else:
                        # HTTP error (500, 502, 504, 400): Increment failure count
                        failures = self._host_failures.get(host_name, 0) + 1
                        self._host_failures[host_name] = failures
                        if failures >= 3:
                            self._host_cooldowns[host_name] = now + 60.0
                            print(f"[DATA LOADER [CIRCUIT BREAKER]] Host {host_name} tripped circuit breaker ({failures} failures). Cooldown 60s.", flush=True)
                        continue

                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                    failures = self._host_failures.get(host_name, 0) + 1
                    self._host_failures[host_name] = failures
                    if failures >= 3:
                        self._host_cooldowns[host_name] = now + 60.0
                        print(f"[DATA LOADER [TIMEOUT]] Host {host_name} network timeout. Tripping circuit breaker for 60s.", flush=True)
                    continue
                except Exception:
                    continue

        # All Binance mirrors failed or under cooldown -> Tier-2 Bybit Gateway
        bybit_df = self._fetch_bybit_timeframe_raw(symbol, tf, limit=limit)
        if bybit_df is not None and len(bybit_df) >= (2 if tf in ["1w", "15d", "1M"] else 5):
            return bybit_df

        # Tier-3 OKX Gateway
        okx_df = self._fetch_okx_timeframe_raw(symbol, tf, limit=limit)
        if okx_df is not None and len(okx_df) >= (2 if tf in ["1w", "15d", "1M"] else 5):
            return okx_df

        # Tier-4 Gate.io Gateway
        gateio_df = self._fetch_gateio_timeframe_raw(symbol, tf, limit=limit)
        if gateio_df is not None and len(gateio_df) >= (2 if tf in ["1w", "15d", "1M"] else 5):
            return gateio_df

        # Tier-5 KuCoin Gateway
        kucoin_df = self._fetch_kucoin_timeframe_raw(symbol, tf, limit=limit)
        if kucoin_df is not None and len(kucoin_df) >= (2 if tf in ["1w", "15d", "1M"] else 5):
            return kucoin_df

        # Tier-6 MEXC Gateway
        mexc_df = self._fetch_mexc_timeframe_raw(symbol, tf, limit=limit)
        if mexc_df is not None and len(mexc_df) >= (2 if tf in ["1w", "15d", "1M"] else 5):
            return mexc_df

        # Tier-6 Persistent Disk Cache SWR Fallback (Catastrophic Multi-Exchange Outage Recovery)
        cached_entry = self._load_from_disk_cache(f"{symbol}_{tf}")
        if cached_entry is not None:
            cached_df, cached_ts = cached_entry
            if cached_df is not None and len(cached_df) >= (2 if tf in ["1w", "15d", "1M"] else 5):
                swr_df = cached_df.copy()
                swr_df.attrs["is_stale"] = True
                swr_df.attrs["exchange_source"] = "persistent_disk_cache"
                swr_df.attrs["cache_age_seconds"] = now - cached_ts

                # Synchronize live price freshness (15-second constraint)
                live_p, is_fresh, price_age = self.get_live_price_with_freshness(symbol)
                swr_df.attrs["live_price_freshness_seconds"] = price_age
                swr_df.attrs["is_price_fresh_15s"] = is_fresh
                if live_p > 0 and is_fresh and not swr_df.empty:
                    swr_df.at[swr_df.index[-1], "close"] = live_p
                    swr_df.at[swr_df.index[-1], "high"] = max(float(swr_df["high"].iloc[-1]), live_p)
                    swr_df.at[swr_df.index[-1], "low"] = min(float(swr_df["low"].iloc[-1]), live_p)

                print(f"[DATA LOADER [DISK CACHE SWR]] Restored {symbol} {tf} from disk cache (all 5 exchange gateways unreachable; live price age: {price_age:.1f}s, fresh_15s: {is_fresh}).", flush=True)
                return swr_df

        return None

    @classmethod
    def _resample_chunk(cls, df: pd.DataFrame, chunk_size: int = 7) -> pd.DataFrame:
        """Resamples finer candles into coarser institutional bars (e.g. 1H -> 4H, 1D -> 7D)."""
        if df is None or len(df) < 2:
            return df

        n = len(df)
        resampled_rows = []
        for i in range(0, n, chunk_size):
            chunk = df.iloc[i:min(i + chunk_size, n)]
            if len(chunk) < 1:
                continue
            resampled_rows.append({
                "timestamp": int(chunk["timestamp"].iloc[0]),
                "datetime": chunk["datetime"].iloc[0] if "datetime" in chunk.columns else pd.to_datetime(int(chunk["timestamp"].iloc[0]), unit="ms", utc=True),
                "open": float(chunk["open"].iloc[0]),
                "high": float(chunk["high"].max()),
                "low": float(chunk["low"].min()),
                "close": float(chunk["close"].iloc[-1]),
                "volume": float(chunk["volume"].sum()),
                "taker_buy_vol": float(chunk.get("taker_buy_vol", chunk["volume"] * 0.5).sum())
            })

        if not resampled_rows:
            return df
        res_df = pd.DataFrame(resampled_rows).reset_index(drop=True)
        return res_df

    @classmethod
    def _resample_15d(cls, df_1d: pd.DataFrame) -> pd.DataFrame:
        """
        Resamples 1D daily candles into 15-day institutional bars.
        Automatic Transition:
        - If N_1D < 30 bars (< 30 calendar days accumulated, fewer than 2 full 15-day bars):
          is_synthetic = True, native_candle_count = 0.
        - As 1D bars accumulate at standard calendar time (15 days per bar) to N_1D >= 30 bars:
          is_synthetic = False, native_candle_count = len(df_15d).
        """
        if df_1d is None or len(df_1d) < 2:
            return df_1d
        n_1d = len(df_1d)
        c_size = 15 if n_1d >= 15 else max(2, n_1d // 2)
        res = cls._resample_chunk(df_1d, chunk_size=c_size)
        is_synth = (c_size < 15) or (n_1d < 30) or bool(df_1d.attrs.get("is_synthetic", False))
        res.attrs["is_synthetic"] = is_synth
        res.attrs["native_candle_count"] = 0 if is_synth else len(res)
        return res

    @classmethod
    def _resample_hierarchical_pyramid(cls, output_dfs: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        """
        Builds a bottom-up hierarchical candle pyramid for sparse or newly listed tokens (e.g. HYPE):
        1. 1H -> 4H (chunk 4), 12H (chunk 12), 1D (chunk 24)
        2. 1D -> 7D (chunk 7), 15D (chunk 15), 30D/1M (chunk 30)
        Automated Transition: Preserves native candles and uses hybrid anchor back-stitching
        when native candles are sparse (2 <= N < 5), automatically phasing out synthetic chunks
        as native klines accumulate over calendar time.
        """
        # Tier 1: Synthesize intraday bars from 1H if 4H/12H/1D are sparse or missing
        df_1h = output_dfs.get("1h")
        if df_1h is not None and len(df_1h) >= 8:
            for tf_key, chunk_sz in [("4h", 4), ("12h", 12), ("1d", 24)]:
                existing = output_dfs.get(tf_key)
                if existing is None or len(existing) < 2:
                    synth = cls._resample_chunk(df_1h, chunk_size=chunk_sz)
                    if len(synth) >= 2:
                        synth.attrs["is_synthetic"] = True
                        synth.attrs["native_candle_count"] = 0
                        output_dfs[tf_key] = synth
                elif not existing.attrs.get("is_synthetic", False):
                    existing.attrs["native_candle_count"] = len(existing)

        # Tier 2: Synthesize macro horizons (1w, 15d, 1M) from 1D
        df_1d = output_dfs.get("1d")
        if df_1d is not None and len(df_1d) >= 2:
            n_1d = len(df_1d)
            is_1d_synth = bool(df_1d.attrs.get("is_synthetic", False))

            # 1W Transition
            existing_1w = output_dfs.get("1w")
            if existing_1w is not None and len(existing_1w) >= 2 and not existing_1w.attrs.get("is_synthetic", False):
                n_nat = len(existing_1w)
                if n_nat < 5 and df_1d is not None and len(df_1d) >= 7 and not is_1d_synth:
                    t_first = int(existing_1w["timestamp"].iloc[0])
                    pre_df_1d = df_1d[df_1d["timestamp"] < t_first]
                    if len(pre_df_1d) >= 7:
                        pre_synth = cls._resample_chunk(pre_df_1d, chunk_size=7)
                        if len(pre_synth) >= 1:
                            hybrid_1w = pd.concat([pre_synth, existing_1w], ignore_index=True)
                            hybrid_1w.attrs["is_synthetic"] = False
                            hybrid_1w.attrs["is_hybrid"] = True
                            hybrid_1w.attrs["native_candle_count"] = n_nat
                            output_dfs["1w"] = hybrid_1w
                        else:
                            existing_1w.attrs["is_synthetic"] = False
                            existing_1w.attrs["native_candle_count"] = n_nat
                    else:
                        existing_1w.attrs["is_synthetic"] = False
                        existing_1w.attrs["native_candle_count"] = n_nat
                else:
                    existing_1w.attrs["is_synthetic"] = False
                    existing_1w.attrs["native_candle_count"] = n_nat
            elif "1w" not in output_dfs or len(output_dfs.get("1w", [])) < 2:
                c_size = 7 if n_1d >= 7 else max(2, n_1d // 2)
                synth_1w = cls._resample_chunk(df_1d, chunk_size=c_size)
                if len(synth_1w) >= 2:
                    is_synth_1w = (c_size < 7) or (n_1d < 14) or is_1d_synth
                    synth_1w.attrs["is_synthetic"] = is_synth_1w
                    synth_1w.attrs["native_candle_count"] = 0 if is_synth_1w else len(synth_1w)
                    output_dfs["1w"] = synth_1w

            # 15D Resampling & Natural Accumulation
            # Binance 15D bars accumulate at standard calendar time (15 days per bar)
            existing_15d = output_dfs.get("15d")
            if existing_15d is None or len(existing_15d) < 2:
                c_size = 15 if n_1d >= 15 else (7 if n_1d >= 7 else max(2, n_1d // 2))
                synth_15d = cls._resample_chunk(df_1d, chunk_size=c_size)
                if len(synth_15d) >= 2:
                    is_synth_15d = (c_size < 15) or (n_1d < 30) or is_1d_synth
                    synth_15d.attrs["is_synthetic"] = is_synth_15d
                    synth_15d.attrs["native_candle_count"] = 0 if is_synth_15d else len(synth_15d)
                    output_dfs["15d"] = synth_15d
            else:
                # Existing 15D: Check if native daily bars accumulated to >= 30 days (standard calendar time)
                if n_1d >= 30 and not is_1d_synth:
                    existing_15d.attrs["is_synthetic"] = False
                    existing_15d.attrs["native_candle_count"] = len(existing_15d)
                elif n_1d < 30:
                    existing_15d.attrs["is_synthetic"] = True
                    existing_15d.attrs["native_candle_count"] = 0

            # 1M Transition & Natural Accumulation
            # Binance native 1M bars accumulate at standard calendar time (30 days per bar)
            existing_1m = output_dfs.get("1M")
            if existing_1m is not None and len(existing_1m) >= 2 and not existing_1m.attrs.get("is_synthetic", False):
                n_nat = len(existing_1m)
                if n_nat < 5 and df_1d is not None and len(df_1d) >= 15 and not is_1d_synth:
                    t_first = int(existing_1m["timestamp"].iloc[0])
                    pre_df_1d = df_1d[df_1d["timestamp"] < t_first]
                    if len(pre_df_1d) >= 15:
                        pre_synth = cls._resample_chunk(pre_df_1d, chunk_size=15)
                        if len(pre_synth) >= 1:
                            hybrid_1m = pd.concat([pre_synth, existing_1m], ignore_index=True)
                            hybrid_1m.attrs["is_synthetic"] = False
                            hybrid_1m.attrs["is_hybrid"] = True
                            hybrid_1m.attrs["native_candle_count"] = n_nat
                            output_dfs["1M"] = hybrid_1m
                        else:
                            existing_1m.attrs["is_synthetic"] = False
                            existing_1m.attrs["native_candle_count"] = n_nat
                    else:
                        existing_1m.attrs["is_synthetic"] = False
                        existing_1m.attrs["native_candle_count"] = n_nat
                else:
                    existing_1m.attrs["is_synthetic"] = False
                    existing_1m.attrs["native_candle_count"] = n_nat
            elif "1M" not in output_dfs or len(output_dfs.get("1M", [])) < 2:
                # Synthesize 1M from 1D until native 1M candles arrive (30 days per bar on Binance)
                c_size = 30 if n_1d >= 30 else (15 if n_1d >= 15 else max(2, n_1d // 2))
                synth_1m = cls._resample_chunk(df_1d, chunk_size=c_size)
                if len(synth_1m) >= 2:
                    is_synth_1m = (c_size < 30) or (n_1d < 60) or is_1d_synth
                    synth_1m.attrs["is_synthetic"] = is_synth_1m
                    synth_1m.attrs["native_candle_count"] = 0 if is_synth_1m else len(synth_1m)
                    output_dfs["1M"] = synth_1m

        return output_dfs

    def fetch_all_9_timeframes(self, symbol: str, limits: Dict[str, int] = None) -> Dict[str, pd.DataFrame]:
        """
        Concurrently fetches and assembles all 9 required charts:
        5M, 15M, 1H, 4H, 12H, 24H (1D), 7D (1W), 15D, 30D (1M).
        Uses smart TTL caching, persistent disk SWR retention,
        4-Tier failover gateways, and partition staleness protection.
        """
        now = time.time()
        limits = limits or {
            "5m": 120, "15m": 120, "1h": 120, "4h": 120, "12h": 120,
            "1d": 180, "1w": 60, "15d": 60, "1M": 36
        }

        # Timeframe-specific cache TTLs
        ttls = {
            "5m": 45.0,    # 45s
            "15m": 120.0,  # 2m
            "1h": 600.0,   # 10m
            "4h": 1800.0,  # 30m
            "12h": 3600.0, # 1h
            "1d": 7200.0,  # 2h
            "1w": 14400.0, # 4h
            "15d": 21600.0,# 6h
            "1M": 43200.0  # 12h
        }

        output_dfs = {}
        missing_tfs = []

        with self._cache_lock:
            for tf in TIMEFRAMES_9:
                cache_key = f"{symbol}_{tf}"
                if cache_key in self._candle_cache:
                    cached_df, cached_ts = self._candle_cache[cache_key]
                    if (now - cached_ts) < ttls.get(tf, 60.0):
                        output_dfs[tf] = cached_df.copy()
                        continue
                else:
                    # Persistent disk cache pre-check for zero-downtime reboots & partition recovery
                    disk_entry = self._load_from_disk_cache(cache_key)
                    if disk_entry:
                        disk_df, disk_ts = disk_entry
                        if (now - disk_ts) < ttls.get(tf, 60.0) and len(disk_df) >= (2 if tf in ["1w", "15d", "1M"] else 5):
                            self._candle_cache[cache_key] = (disk_df, disk_ts)
                            output_dfs[tf] = disk_df.copy()
                            continue
                missing_tfs.append(tf)

        if not missing_tfs:
            return output_dfs

        # Fetch remaining timeframes using failover gateways & SWR disk cache
        stale_intraday_detected = False
        stale_count = 0

        for tf_target in missing_tfs:
            # High-efficiency in-memory resampling: If 15D is needed and 1D is already available, resample directly
            if tf_target == "15d" and "1d" in output_dfs and len(output_dfs["1d"]) >= 30:
                df_result = self._resample_15d(output_dfs["1d"])
            else:
                df_result = self.fetch_single_timeframe_raw(symbol, tf_target, limit=limits.get(tf_target, 120))

            if df_result is not None and len(df_result) >= (2 if tf_target in ["1w", "15d", "1M"] else 5):
                output_dfs[tf_target] = df_result
                with self._cache_lock:
                    self._candle_cache[f"{symbol}_{tf_target}"] = (df_result, now)
                self._save_to_disk_cache(f"{symbol}_{tf_target}", df_result, now)
            else:
                # Stale-While-Revalidate (SWR): Fall back to memory or disk-cached DataFrame
                cache_k = f"{symbol}_{tf_target}"
                cached_entry = None
                with self._cache_lock:
                    if cache_k in self._candle_cache:
                        cached_entry = self._candle_cache[cache_k]

                if not cached_entry:
                    cached_entry = self._load_from_disk_cache(cache_k)
                    if cached_entry:
                        with self._cache_lock:
                            self._candle_cache[cache_k] = cached_entry

                if cached_entry:
                    cached_df, cached_ts = cached_entry
                    if cached_df is not None and len(cached_df) >= 2:
                        age = now - cached_ts
                        swr_df = cached_df.copy()
                        swr_df.attrs["is_stale"] = True
                        swr_df.attrs["cache_age_seconds"] = age

                        # Synchronize live price freshness (15-second constraint)
                        live_p, is_fresh, price_age = self.get_live_price_with_freshness(symbol)
                        swr_df.attrs["live_price_freshness_seconds"] = price_age
                        swr_df.attrs["is_price_fresh_15s"] = is_fresh
                        if live_p > 0 and is_fresh and not swr_df.empty:
                            swr_df.at[swr_df.index[-1], "close"] = live_p
                            swr_df.at[swr_df.index[-1], "high"] = max(float(swr_df["high"].iloc[-1]), live_p)
                            swr_df.at[swr_df.index[-1], "low"] = min(float(swr_df["low"].iloc[-1]), live_p)

                        output_dfs[tf_target] = swr_df
                        stale_count += 1

                        # Intraday partition staleness threshold: 10 minutes (600s)
                        if tf_target in ["5m", "15m"] and age > 600.0:
                            stale_intraday_detected = True
                            swr_df.attrs["is_partition_stale"] = True

                        print(f"[DATA LOADER [SWR]] Serving persistent cached klines for {symbol} {tf_target} (age: {age:.0f}s). Upstream live gateways down.", flush=True)

        # Check if all upstream gateways are unreachable worldwide (Global Outage)
        global_outage_detected = (stale_count == len(missing_tfs) and len(missing_tfs) > 0)
        with self._cache_lock:
            self._is_partition_stale = stale_intraday_detected or global_outage_detected
            self._is_global_outage = global_outage_detected
            self._stale_timeframes_count = stale_count
            if global_outage_detected:
                self._global_outage_reason = "GLOBAL_OUTAGE_DEFENSE: All live exchange gateways (Binance, Bybit, MEXC, Gate.io, KuCoin) simultaneously unreachable worldwide. Serving warm persistent disk cache. Global Outage NTZ locked."
                print(f"[DATA LOADER [GLOBAL OUTAGE]] {self._global_outage_reason}", flush=True)
            elif not stale_intraday_detected:
                self._is_global_outage = False

        # Run Hierarchical Bottom-Up Candle Pyramid for newly listed or sparse tokens
        output_dfs = self._resample_hierarchical_pyramid(output_dfs)

        return output_dfs
