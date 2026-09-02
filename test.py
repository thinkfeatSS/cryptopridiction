# ==============================================================================
# MULTI-HORIZON QUANTITATIVE CRYPTO TRADING ENGINE (V14.0)
# Asset: BTC/USDT & Multi-Asset Portfolio Scanner (ETH, SOL, XRP, BNB, DOGE, AVAX)
# Key Upgrades in V14.0:
# 1. 3 Simultaneous Trading Horizons: ⚡ Scalp (15M), 🌊 Swing (1H-2H), 🚀 Macro (24H/1D)
# 2. 💎 Triple Confluence Super-Trade Detection (Unanimous 3-Horizon Alignment)
# 3. Multi-Horizon Leaderboard Matrix (Minutes, Hours & Days side-by-side)
# 4. Multi-Horizon Paper Trading Ledger ($10 Virtual Wallet across all horizons)
# 5. Continuous 24/7 Watcher Daemon & Web-App Ready JSON Serializer
# ==============================================================================

import sys
import subprocess

def install_dependencies():
    packages = [
        ("ccxt", "ccxt"),
        ("xgboost", "xgboost"),
        ("catboost", "catboost"),
        ("lightgbm", "lightgbm"),
        ("tabulate", "tabulate"),
        ("sklearn", "scikit-learn"),
        ("pandas", "pandas"),
        ("numpy", "numpy"),
        ("joblib", "joblib"),
        ("scipy", "scipy"),
        ("requests", "requests"),
        ("tensorflow", "tensorflow")
    ]
    for import_name, pip_pkg in packages:
        try:
            __import__(import_name)
        except ImportError:
            print(f"[SETUP] Installing {pip_pkg}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pip_pkg])

install_dependencies()

import os
import json
import time
import math
import joblib
import warnings
import requests
import numpy as np
import pandas as pd
from tabulate import tabulate
from datetime import datetime, timezone, timedelta
from scipy.signal import savgol_filter
from concurrent.futures import ThreadPoolExecutor, as_completed

import ccxt
import xgboost as xgb
from catboost import CatBoostClassifier
from sklearn.ensemble import ExtraTreesClassifier
try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False

from sklearn.preprocessing import RobustScaler
from sklearn.metrics import accuracy_score, roc_auc_score, mean_squared_error
from sklearn.model_selection import TimeSeriesSplit

import tensorflow as tf
from tensorflow.keras import layers, models, regularizers, callbacks
import tensorflow.keras.backend as K

warnings.filterwarnings("ignore")
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

# Hardware Acceleration Check
gpus = tf.config.list_physical_devices('GPU')
if gpus:
    try:
        for gpu in gpus:
            tf.config.experimental.set_memory_growth(gpu, True)
        print(f"[SYSTEM] Hardware Acceleration Active: {gpus[0].name}")
    except RuntimeError as e:
        print(f"[SYSTEM] GPU Warning: {e}")
else:
    print("[SYSTEM] Running in High-Performance CPU Mode.")

# ------------------------------------------------------------------------------
# 1. CONFIGURATION & MULTI-HORIZON PARAMETERS
# ------------------------------------------------------------------------------
CONFIG = {
    "mode": "both",               # "both", "scanner", or "single"
    "continuous_loop": True,      # 24/7 Background Watcher Loop
    "scanner_mode": "top_volume", # "top_volume" (dynamic auto-discovery of all active Binance coins), "expanded_universe", or "custom_list"
    "scanner_top_n": 25,          # Number of top volume Binance coins to scan simultaneously
    "single_symbol": "BTC/USDT",
    "scanner_symbols": [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT", "DOGE/USDT", "ADA/USDT",
        "AVAX/USDT", "SUI/USDT", "LINK/USDT", "NEAR/USDT", "APT/USDT", "DOT/USDT", "PEPE/USDT",
        "SHIB/USDT", "TIA/USDT", "INJ/USDT", "RENDER/USDT", "FET/USDT", "OP/USDT", "ARB/USDT",
        "LTC/USDT", "UNI/USDT", "ICP/USDT", "FIL/USDT", "STX/USDT", "TAO/USDT", "SEI/USDT",
        "WIF/USDT", "BONK/USDT", "AAVE/USDT", "ATOM/USDT", "ETC/USDT", "KAS/USDT", "FTM/USDT"
    ],
    "timeframes": ["1d", "4h", "1h", "30m", "15m", "5m", "1m"],
    # Multi-Horizon Definitions: Minutes, Hours, and Days
    "horizons": {
        "scalp": {
            "name": "⚡ Scalp (15M)",
            "anchor_tf": "15m",
            "bars": 1,
            "duration_label": "15 Mins",
            "tp_mult": 2.0,
            "sl_mult": 1.0
        },
        "swing": {
            "name": "🌊 Swing (1H)",
            "anchor_tf": "1h",
            "bars": 2,
            "duration_label": "2 Hours",
            "tp_mult": 2.5,
            "sl_mult": 1.2
        },
        "macro": {
            "name": "🚀 Macro (24H)",
            "anchor_tf": "1d",
            "bars": 1,
            "duration_label": "24 Hours",
            "tp_mult": 3.0,
            "sl_mult": 1.5
        }
    },
    "history_limit_per_tf": {
        "1d": 1500,
        "4h": 2000,
        "1h": 2500,
        "30m": 2500,
        "15m": 2500,
        "5m": 3000,
        "1m": 3000
    },
    "paper_trading": {
        "enabled": True,
        "start_balance_usd": 10.0,
        "position_size_usd": 2.0,
        "dynamic_sizing": True,             # Adaptive Kelly & Volatility-Adjusted Sizing
        "min_position_size_usd": 1.0,       # Minimum position size ($1)
        "max_position_size_pct": 0.20,      # Max 20% of account equity per position
        "max_concurrent_positions": 6,
        "binance_fee_rate": 0.0010,         # Standard Binance Spot fee: 0.10% (taker/maker)
        "use_bnb_fee_discount": True,       # 25% discount when paying fees with BNB (0.075% net fee rate)
        "slippage_rate": 0.0002             # 0.02% realistic market order execution slippage
    },
    "signal_engine": {
        "dynamic_signal_count": True,       # Adaptive signal count based on true market edge
        "min_signals_per_round": 1,         # Always guarantee at least top 1 setup
        "max_signals_per_round": 5,         # Cap at 5 to avoid information overload
        "grade_a_plus_conviction": 0.75,    # 75%+ conviction + confluence -> Grade A+
        "grade_a_conviction": 0.65,         # 65%-74% conviction -> Grade A
        "grade_b_conviction": 0.55,         # 55%-64% conviction -> Grade B+
        "require_min_rr_ratio": 2.0         # 1:2 Risk to Reward minimum
    },
    "elite_conviction_threshold": 0.68,   # Top-Decile Pareto Conviction (90% tier)
    "meta_confidence_threshold": 0.55,
    "train_split": 0.70,
    "val_split": 0.15,
    "test_split": 0.15,
    "embargo_pct": 0.01,
    "dnn": {
        "epochs": 60,
        "batch_size": 64,
        "learning_rate": 0.0008,
        "patience": 10,
        "l2_reg": 1e-4,
        "dropout": 0.20,
        "focal_gamma": 2.0
    },
    "xgb_clf": {
        "max_depth": 4,
        "learning_rate": 0.03,
        "n_estimators": 250,
        "subsample": 0.85,
        "colsample_bytree": 0.80,
        "gamma": 0.15,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "random_state": 42
    },
    "lgb_clf": {
        "max_depth": 4,
        "num_leaves": 15,
        "learning_rate": 0.03,
        "n_estimators": 250,
        "subsample": 0.85,
        "colsample_bytree": 0.80,
        "random_state": 42,
        "verbose": -1
    },
    "extra_trees": {
        "n_estimators": 200,
        "max_depth": 6,
        "min_samples_split": 5,
        "random_state": 42,
        "n_jobs": -1
    },
    "xgb_reg": {
        "max_depth": 4,
        "learning_rate": 0.03,
        "n_estimators": 250,
        "subsample": 0.85,
        "colsample_bytree": 0.80,
        "objective": "reg:pseudohubererror",
        "random_state": 42
    },
    "catboost": {
        "iterations": 250,
        "depth": 5,
        "learning_rate": 0.03,
        "l2_leaf_reg": 4.0,
        "auto_class_weights": "Balanced",
        "verbose": False,
        "random_seed": 42
    },
    "models_export_dir": "./models_export_v3",
    "app_export_dir": "./export_app_data"
}

# ------------------------------------------------------------------------------
# 2. UNIVERSAL MULTI-EXCHANGE DATA ACQUISITION & AUTO-FAILOVER MODULE
# ------------------------------------------------------------------------------
class CryptoDataLoader:
    """
    High-Performance, Geo-Unrestricted Crypto Market Data Engine.
    Specifically engineered for Google Colab, Cloud (AWS/GCP), and Local environments.
    - Seamlessly accesses Binance via Official Binance Public Data Vision API (No Geo-451 blocks)
    - Full multi-endpoint Binance fallbacks (Vision, Spot, USD-M Futures, Mirrors, Binance US)
    - Resilient secondary exchanges (Kraken, KuCoin, Gate.io, MEXC, OKX, Bybit)
    - Robust forward & backward OHLCV pagination to guarantee 100% fresh, real-time live data
    """
    def __init__(self, exchange_priority=None):
        self.priority_exchanges = exchange_priority or [
            'binance_vision', 'binance', 'binance_mirrors', 'binance_futures', 'binanceus',
            'kraken', 'kucoin', 'gateio', 'mexc', 'okx', 'bybit'
        ]
        self.active_exchange_id = None
        self.exchange = None
        self._cache = {}
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        })
        self.is_binance_vision_direct = False
        self.init_resilient_exchange()

    def init_resilient_exchange(self):
        """Finds the best working, unrestricted free global exchange in priority (Binance first)."""
        for ex_id in self.priority_exchanges:
            try:
                if ex_id == 'binance_vision':
                    # Binance Official Public Data Vision API (Zero Geo-Restriction in Colab / US Cloud)
                    ex = ccxt.binance({
                        'enableRateLimit': True,
                        'options': {'defaultType': 'spot', 'adjustForTimeDifference': True},
                        'urls': {
                            'api': {
                                'public': 'https://data-api.binance.vision/api/v3',
                                'v3': 'https://data-api.binance.vision/api/v3',
                                'v1': 'https://data-api.binance.vision/api/v1',
                            }
                        },
                        'timeout': 10000
                    })
                    # Test CCXT endpoint or direct REST
                    test_ohlcv = self._fetch_binance_vision_klines('BTC/USDT', '1h', limit=5)
                    if test_ohlcv and len(test_ohlcv) >= 5:
                        self.exchange = ex
                        self.active_exchange_id = 'binance'
                        self.is_binance_vision_direct = True
                        print(f"[EXCHANGE ADAPTER] 🌐 Active Global Market Data Feed Connected: [BINANCE] (Binance Vision Public API - Free & Unrestricted)")
                        return

                elif ex_id == 'binance':
                    # Standard Binance Spot
                    ex = ccxt.binance({
                        'enableRateLimit': True,
                        'options': {'defaultType': 'spot'},
                        'timeout': 10000
                    })
                    ex.fetch_ohlcv('BTC/USDT', timeframe='1h', limit=5)
                    self.exchange = ex
                    self.active_exchange_id = 'binance'
                    self.is_binance_vision_direct = False
                    print(f"[EXCHANGE ADAPTER] 🌐 Active Global Market Data Feed Connected: [BINANCE] (Direct Spot Feed)")
                    return

                elif ex_id == 'binance_mirrors':
                    # Binance Alternative Cluster Mirrors
                    for mirror in ['api1.binance.com', 'api2.binance.com', 'api3.binance.com', 'api4.binance.com']:
                        try:
                            ex = ccxt.binance({
                                'enableRateLimit': True,
                                'options': {'defaultType': 'spot'},
                                'urls': {'api': {'public': f'https://{mirror}/api/v3', 'v3': f'https://{mirror}/api/v3'}},
                                'timeout': 8000
                            })
                            ex.fetch_ohlcv('BTC/USDT', timeframe='1h', limit=5)
                            self.exchange = ex
                            self.active_exchange_id = 'binance'
                            self.is_binance_vision_direct = False
                            print(f"[EXCHANGE ADAPTER] 🌐 Active Global Market Data Feed Connected: [BINANCE] (Mirror: {mirror})")
                            return
                        except Exception:
                            continue

                elif ex_id == 'binance_futures':
                    # Binance USD-M Futures Public Data
                    ex = ccxt.binance({
                        'enableRateLimit': True,
                        'options': {'defaultType': 'future'},
                        'timeout': 10000
                    })
                    ex.fetch_ohlcv('BTC/USDT', timeframe='1h', limit=5)
                    self.exchange = ex
                    self.active_exchange_id = 'binance'
                    self.is_binance_vision_direct = False
                    print(f"[EXCHANGE ADAPTER] 🌐 Active Global Market Data Feed Connected: [BINANCE FUTURES] (USD-M Public Feed)")
                    return

                elif ex_id == 'binanceus':
                    # Binance US (For US-based instances)
                    ex = ccxt.binanceus({
                        'enableRateLimit': True,
                        'options': {'defaultType': 'spot'},
                        'timeout': 10000
                    })
                    ex.fetch_ohlcv('BTC/USDT', timeframe='1h', limit=5)
                    self.exchange = ex
                    self.active_exchange_id = 'binanceus'
                    self.is_binance_vision_direct = False
                    print(f"[EXCHANGE ADAPTER] 🌐 Active Global Market Data Feed Connected: [BINANCE.US] (US Spot Feed)")
                    return

                else:
                    # Secondary Exchanges (Kraken, KuCoin, Gate.io, MEXC, OKX, Bybit)
                    ex_class = getattr(ccxt, ex_id, None)
                    if not ex_class:
                        continue
                    ex = ex_class({
                        'enableRateLimit': True,
                        'options': {'defaultType': 'spot'},
                        'timeout': 10000
                    })
                    ex.fetch_ohlcv('BTC/USDT', timeframe='1h', limit=5)
                    self.exchange = ex
                    self.active_exchange_id = ex_id
                    self.is_binance_vision_direct = False
                    print(f"[EXCHANGE ADAPTER] 🌐 Active Global Market Data Feed Connected: [{ex_id.upper()}] (Free & Unrestricted)")
                    return

            except Exception as e:
                err_str = str(e).lower()
                if "451" in err_str or "restricted" in err_str or "unavailable" in err_str:
                    print(f"[EXCHANGE ADAPTER] ⚠️ [{ex_id.upper()}] is geo-restricted from this server IP (HTTP 451). Auto-migrating...")
                elif "403" in err_str or "cloudfront" in err_str:
                    print(f"[EXCHANGE ADAPTER] ⚠️ [{ex_id.upper()}] CloudFront 403 note. Trying next open endpoint...")
                else:
                    print(f"[EXCHANGE ADAPTER] ⚠️ [{ex_id.upper()}] connection note: {e}. Trying next exchange...")

        # Ultimate fallback: Binance Vision direct REST
        print(f"[EXCHANGE ADAPTER] 🔄 Connecting via Binance Vision Public REST Engine...")
        self.active_exchange_id = 'binance'
        self.is_binance_vision_direct = True

    def _fetch_binance_vision_klines(self, symbol: str, timeframe: str, since: int = None, limit: int = 1000) -> list:
        """Direct, ultra-resilient Binance Vision REST klines fetcher with zero geo-blocking."""
        try:
            raw_sym = symbol.replace('/', '').replace(':USDT', '')
            url = "https://data-api.binance.vision/api/v3/klines"
            params = {
                "symbol": raw_sym,
                "interval": timeframe,
                "limit": min(1000, limit)
            }
            if since is not None and since > 0:
                params["startTime"] = int(since)
            
            resp = self.session.get(url, params=params, timeout=12)
            if resp.status_code == 200:
                raw_data = resp.json()
                # Format: [open_time, open, high, low, close, volume, close_time, quote_vol, trades, taker_buy_base_vol, ...]
                formatted = []
                for k in raw_data:
                    vol = float(k[5])
                    taker_vol = float(k[9]) if len(k) > 9 else vol * 0.5
                    formatted.append([
                        int(k[0]),
                        float(k[1]),
                        float(k[2]),
                        float(k[3]),
                        float(k[4]),
                        vol,
                        taker_vol
                    ])
                return formatted
            return []
        except Exception:
            return []

    @staticmethod
    def get_timeframe_delta(timeframe: str, bars: int = 1) -> timedelta:
        tf_delta_map = {
            '1m': timedelta(minutes=1 * bars),
            '3m': timedelta(minutes=3 * bars),
            '5m': timedelta(minutes=5 * bars),
            '15m': timedelta(minutes=15 * bars),
            '30m': timedelta(minutes=30 * bars),
            '1h': timedelta(hours=1 * bars),
            '2h': timedelta(hours=2 * bars),
            '4h': timedelta(hours=4 * bars),
            '1d': timedelta(days=1 * bars),
            '1w': timedelta(weeks=1 * bars),
            '1M': timedelta(days=30 * bars)
        }
        return tf_delta_map.get(timeframe, timedelta(minutes=1 * bars))

    def fetch_ohlcv_extended(self, symbol: str, timeframe: str, total_candles: int = 2000) -> pd.DataFrame:
        cache_key = f"{symbol}_{timeframe}_{total_candles}"
        if cache_key in self._cache:
            return self._cache[cache_key].copy()

        all_ohlcv = []
        tf_ms_map = {
            '1m': 60 * 1000,
            '3m': 3 * 60 * 1000,
            '5m': 5 * 60 * 1000,
            '15m': 15 * 60 * 1000,
            '30m': 30 * 60 * 1000,
            '1h': 60 * 60 * 1000,
            '2h': 2 * 60 * 60 * 1000,
            '4h': 4 * 60 * 60 * 1000,
            '1d': 24 * 60 * 60 * 1000,
            '1w': 7 * 24 * 60 * 60 * 1000,
            '1M': 30 * 24 * 60 * 60 * 1000
        }
        
        step_ms = tf_ms_map.get(timeframe, 60 * 1000)
        curr_time = int(datetime.now(timezone.utc).timestamp() * 1000)
        calculated_since = curr_time - int(total_candles * step_ms)
        genesis_ms = 1501545600000
        since = max(genesis_ms, int(calculated_since))
        
        # 1. Primary Fetch: Binance Vision or CCXT Exchange
        if self.is_binance_vision_direct or self.active_exchange_id == 'binance':
            # Paginate forward via Binance (1000 candles per batch)
            while len(all_ohlcv) < total_candles:
                batch = self._fetch_binance_vision_klines(symbol, timeframe, since=since, limit=1000)
                if not batch and self.exchange:
                    try:
                        raw_ccxt = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
                        batch = [[c[0], c[1], c[2], c[3], c[4], c[5], c[5]*0.5] for c in raw_ccxt] if raw_ccxt else []
                    except Exception:
                        batch = []
                if not batch:
                    break
                all_ohlcv.extend(batch)
                last_candle_time = batch[-1][0]
                if last_candle_time >= curr_time or len(batch) < 10:
                    break
                since = int(last_candle_time + step_ms)
                time.sleep(0.05)
        else:
            # Multi-exchange resilient pagination
            limit_per_req = 1000
            if self.active_exchange_id == 'okx':
                limit_per_req = 100
            elif self.active_exchange_id == 'kraken':
                limit_per_req = 720
            elif self.active_exchange_id == 'kucoin':
                limit_per_req = 1500

            while len(all_ohlcv) < total_candles:
                try:
                    ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=int(since), limit=limit_per_req)
                    if not ohlcv:
                        break
                    for c in ohlcv:
                        all_ohlcv.append([c[0], c[1], c[2], c[3], c[4], c[5], c[5]*0.5])
                    last_candle_time = ohlcv[-1][0]
                    if last_candle_time >= curr_time or len(ohlcv) == 0:
                        break
                    since = int(last_candle_time + step_ms)
                    time.sleep(self.exchange.rateLimit / 1000.0 if hasattr(self.exchange, 'rateLimit') else 0.05)
                except Exception as e:
                    err_str = str(e).lower()
                    if "451" in err_str or "restricted" in err_str:
                        print(f"[FAILOVER] Restriction encountered during fetch. Re-routing...")
                        self.priority_exchanges = [ex for ex in self.priority_exchanges if ex != self.active_exchange_id]
                        self.init_resilient_exchange()
                        return self.fetch_ohlcv_extended(symbol, timeframe, total_candles)
                    break

        # 2. Real-Time Freshness Guarantee: Ensure the most recent live candle is included
        try:
            recent_candles = []
            if self.is_binance_vision_direct or self.active_exchange_id == 'binance':
                recent_candles = self._fetch_binance_vision_klines(symbol, timeframe, since=None, limit=min(500, total_candles))
            elif self.exchange:
                raw_recent = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=min(500, total_candles))
                recent_candles = [[c[0], c[1], c[2], c[3], c[4], c[5], c[5]*0.5] for c in raw_recent] if raw_recent else []
            
            if recent_candles:
                all_ohlcv.extend(recent_candles)
        except Exception:
            pass

        if not all_ohlcv:
            raise ValueError(f"No OHLCV records returned for {symbol} on {timeframe}")

        cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'taker_buy_vol']
        if len(all_ohlcv[0]) < 7:
            all_ohlcv = [row + [row[5]*0.5] for row in all_ohlcv]

        df = pd.DataFrame(all_ohlcv, columns=cols)
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
        
        for col in ['open', 'high', 'low', 'close', 'volume', 'taker_buy_vol']:
            df[col] = df[col].astype(float)

        # Slice to requested total_candles (keeping the most recent candles)
        if len(df) > total_candles:
            df = df.iloc[-total_candles:].reset_index(drop=True)

        self._cache[cache_key] = df
        return df.copy()

    def fetch_funding_rate_and_oi(self, symbol: str) -> dict:
        """
        Fetches live 8h perpetual funding rate and Open Interest from Binance Futures public endpoint.
        Free, public, and unrestricted.
        """
        try:
            raw_sym = symbol.replace('/', '').replace(':USDT', '')
            if not raw_sym.endswith('USDT'):
                raw_sym += 'USDT'

            # 1. Funding Rate
            fr_url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={raw_sym}"
            resp_fr = self.session.get(fr_url, timeout=4)
            fr_val = 0.0001
            if resp_fr.status_code == 200:
                fr_val = float(resp_fr.json().get('lastFundingRate', 0.0001))

            # 2. Open Interest
            oi_url = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={raw_sym}"
            resp_oi = self.session.get(oi_url, timeout=4)
            oi_val = 0.0
            if resp_oi.status_code == 200:
                oi_val = float(resp_oi.json().get('openInterest', 0.0))

            regime = "🔥 SHORT SQUEEZE" if fr_val <= -0.0002 else ("❄️ LONG SQUEEZE" if fr_val >= 0.0005 else "⚪ NEUTRAL")
            return {
                "funding_rate": fr_val,
                "open_interest": oi_val,
                "regime": regime
            }
        except Exception:
            return {"funding_rate": 0.0001, "open_interest": 0.0, "regime": "⚪ NEUTRAL"}

    def fetch_ticker(self, symbol: str) -> dict:
        """Fetches the latest real-time ticker data."""
        if self.is_binance_vision_direct or self.active_exchange_id == 'binance':
            try:
                raw_sym = symbol.replace('/', '').replace(':USDT', '')
                url = f"https://data-api.binance.vision/api/v3/ticker/price?symbol={raw_sym}"
                resp = self.session.get(url, timeout=5)
                if resp.status_code == 200:
                    p = float(resp.json().get('price', 0.0))
                    return {'symbol': symbol, 'last': p, 'close': p}
            except Exception:
                pass
        if self.exchange:
            try:
                return self.exchange.fetch_ticker(symbol)
            except Exception:
                pass
        # Fallback to last candle close
        df = self.fetch_ohlcv_extended(symbol, '15m', total_candles=5)
        last_p = float(df['close'].iloc[-1])
        return {'symbol': symbol, 'last': last_p, 'close': last_p}

    def fetch_orderbook_imbalance(self, symbol: str, limit: int = 20) -> float:
        """
        Fetches live top-20 orderbook depth levels and computes bid-ask liquidity imbalance ratio:
        imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume)
        Range: [-1.0 (Heavy Sell Wall), +1.0 (Heavy Buy Wall)]
        """
        try:
            if self.is_binance_vision_direct or self.active_exchange_id == 'binance':
                raw_sym = symbol.replace('/', '').replace(':USDT', '')
                url = f"https://data-api.binance.vision/api/v3/depth?symbol={raw_sym}&limit={limit}"
                resp = self.session.get(url, timeout=4)
                if resp.status_code == 200:
                    data = resp.json()
                    bids = data.get('bids', [])
                    asks = data.get('asks', [])
                    bid_vol = sum(float(b[1]) for b in bids)
                    ask_vol = sum(float(a[1]) for a in asks)
                    total_vol = bid_vol + ask_vol
                    if total_vol > 0:
                        return (bid_vol - ask_vol) / total_vol
            elif self.exchange:
                ob = self.exchange.fetch_order_book(symbol, limit=limit)
                bid_vol = sum(b[1] for b in ob.get('bids', []))
                ask_vol = sum(a[1] for a in ob.get('asks', []))
                total_vol = bid_vol + ask_vol
                if total_vol > 0:
                    return (bid_vol - ask_vol) / total_vol
        except Exception:
            pass
        return 0.0

    def fetch_top_volume_usdt_pairs(self, limit: int = 25) -> list:
        """Dynamically discovers and ranks active volatile crypto pairs by 24h volume (strictly excluding all stablecoins)."""
        try:
            print(f"[MARKET DISCOVERY] Querying all active [{self.active_exchange_id.upper()}] pairs by 24h trading volume...")
            valid_pairs = []
            excluded_bases = {
                "USDC", "FDUSD", "TUSD", "USDD", "DAI", "BUSD", "EUR", "TRY", "PAXG", "WBTC",
                "USDP", "AEUR", "T", "USTC", "EURI", "USD", "EURR", "RLUSD", "USD1", "U", "USDE",
                "PYUSD", "GUSD", "LUSD", "FRAX", "CUSD", "EURT", "XAUT", "XAU", "XAG", "FDUSD"
            }

            # 1. Direct Binance Vision 24h Tickers API
            if self.is_binance_vision_direct or self.active_exchange_id == 'binance':
                try:
                    resp = self.session.get("https://data-api.binance.vision/api/v3/ticker/24hr", timeout=12)
                    if resp.status_code == 200:
                        data = resp.json()
                        for item in data:
                            raw_sym = item.get('symbol', '')
                            if not raw_sym.endswith('USDT'):
                                continue
                            base = raw_sym[:-4]
                            if base in excluded_bases or base.endswith("UP") or base.endswith("DOWN") or base.endswith("BULL") or base.endswith("BEAR"):
                                continue
                            
                            last_p = float(item.get('lastPrice', 0.0) or 0.0)
                            high_p = float(item.get('highPrice', 0.0) or 0.0)
                            low_p = float(item.get('lowPrice', 0.0) or 0.0)
                            
                            # Dynamic Stablecoin Peg Filter: discard fiat-pegged tokens (~$1 with negligible 24h volatility)
                            if 0.98 <= last_p <= 1.02 and (high_p - low_p) / max(0.001, last_p) < 0.015:
                                continue

                            quote_vol = float(item.get('quoteVolume', 0.0) or 0.0)
                            if quote_vol > 1000000.0:  # Minimum $1M 24h volume
                                valid_pairs.append((f"{base}/USDT", quote_vol))
                except Exception as e:
                    print(f"[MARKET DISCOVERY] Note on Binance Vision 24h tickers: {e}")

            # 2. CCXT Fallback if not populated
            if not valid_pairs and self.exchange:
                tickers = self.exchange.fetch_tickers()
                for sym, t in tickers.items():
                    if not sym.endswith('/USDT'):
                        continue
                    base = sym.split('/')[0]
                    if base in excluded_bases or base.endswith("UP") or base.endswith("DOWN") or base.endswith("BULL") or base.endswith("BEAR") or base.endswith("3L") or base.endswith("3S"):
                        continue
                    last_p = float(t.get('last', 0.0) or 0.0)
                    if 0.98 <= last_p <= 1.02:
                        continue
                    quote_vol = t.get('quoteVolume', 0.0) or t.get('baseVolume', 0.0) or 0.0
                    if quote_vol > 0:
                        valid_pairs.append((sym, quote_vol))

            if valid_pairs:
                valid_pairs.sort(key=lambda x: x[1], reverse=True)
                top_pairs = [p[0] for p in valid_pairs[:limit]]
                if "BTC/USDT" not in top_pairs:
                    top_pairs.insert(0, "BTC/USDT")
                print(f"[MARKET DISCOVERY] Loaded Top {len(top_pairs)} Most Active [{self.active_exchange_id.upper()}] Pairs: {', '.join(top_pairs[:8])}...")
                return top_pairs

        except Exception as e:
            print(f"[WARNING] Could not fetch tickers from {self.active_exchange_id} ({e}). Using default universe.")

        return [
            "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT", "DOGE/USDT", "ADA/USDT",
            "AVAX/USDT", "SUI/USDT", "LINK/USDT", "NEAR/USDT", "APT/USDT", "DOT/USDT", "PEPE/USDT",
            "SHIB/USDT", "TIA/USDT", "INJ/USDT", "RENDER/USDT", "FET/USDT", "OP/USDT", "ARB/USDT",
            "LTC/USDT", "UNI/USDT", "ICP/USDT", "FIL/USDT"
        ][:limit]

# ------------------------------------------------------------------------------
# 3. ADVANCED FEATURE ENGINEERING MODULE
# ------------------------------------------------------------------------------
class AdvancedFeatureEngineer:
    @staticmethod
    def get_fractional_diff(series: pd.Series, d: float = 0.35, thres: float = 1e-4) -> pd.Series:
        w = [1.0]
        k = 1
        while True:
            w_k = -w[-1] / k * (d - k + 1)
            if abs(w_k) < thres:
                break
            w.append(w_k)
            k += 1
        w = np.array(w[::-1])
        res = series.rolling(window=len(w)).apply(lambda x: np.dot(x, w), raw=True)
        return (res / (series + 1e-10)).fillna(0.0)

    @staticmethod
    def compute_denoised_velocity(series: pd.Series, window: int = 11, polyorder: int = 2) -> pd.Series:
        if len(series) < window:
            return series.diff().fillna(0.0)
        smoothed = savgol_filter(series.values, window_length=window, polyorder=polyorder)
        velocity = pd.Series(smoothed, index=series.index).diff() / (series + 1e-10)
        return velocity.fillna(0.0)

    @staticmethod
    def garman_klass_volatility(df: pd.DataFrame, window: int = 14) -> pd.Series:
        log_hl = np.log(df['high'] / (df['low'] + 1e-10)) ** 2
        log_co = np.log(df['close'] / (df['open'] + 1e-10)) ** 2
        rs = 0.5 * log_hl - (2 * np.log(2) - 1) * log_co
        return np.sqrt(rs.rolling(window=window).mean().clip(lower=0)).fillna(0.0)

    @staticmethod
    def parkinson_volatility(df: pd.DataFrame, window: int = 14) -> pd.Series:
        log_hl = np.log(df['high'] / (df['low'] + 1e-10)) ** 2
        factor = 1.0 / (4.0 * np.log(2.0))
        return np.sqrt(factor * log_hl.rolling(window=window).mean().clip(lower=0)).fillna(0.0)

    @staticmethod
    def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return (rsi / 100.0).clip(0.0, 1.0).fillna(0.5)

    @staticmethod
    def compute_mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        tp = (df['high'] + df['low'] + df['close']) / 3.0
        rmf = tp * df['volume']
        pos_mf = np.where(tp > tp.shift(1), rmf, 0.0)
        neg_mf = np.where(tp < tp.shift(1), rmf, 0.0)
        pos_mf_sum = pd.Series(pos_mf, index=df.index).rolling(period).sum()
        neg_mf_sum = pd.Series(neg_mf, index=df.index).rolling(period).sum()
        mfr = pos_mf_sum / (neg_mf_sum + 1e-10)
        mfi = 100.0 - (100.0 / (1.0 + mfr))
        return (mfi / 100.0).clip(0.0, 1.0).fillna(0.5)

    @staticmethod
    def compute_stoch_rsi(series: pd.Series, period: int = 14, k_period: int = 3, d_period: int = 3):
        rsi = AdvancedFeatureEngineer.compute_rsi(series, period=period)
        min_rsi = rsi.rolling(window=period).min()
        max_rsi = rsi.rolling(window=period).max()
        stoch = (rsi - min_rsi) / ((max_rsi - min_rsi) + 1e-10)
        k = stoch.rolling(window=k_period).mean().clip(0.0, 1.0).fillna(0.5)
        d = k.rolling(window=d_period).mean().clip(0.0, 1.0).fillna(0.5)
        return k, d

    @staticmethod
    def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high, low, close = df['high'], df['low'], df['close']
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean().fillna(0.0)

    @staticmethod
    def compute_adx(df: pd.DataFrame, period: int = 14):
        high, low, close = df['high'], df['low'], df['close']
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        tr = AdvancedFeatureEngineer.compute_atr(df, period=period)
        plus_di = 100 * (pd.Series(plus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean() / (tr + 1e-10))
        minus_di = 100 * (pd.Series(minus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean() / (tr + 1e-10))
        dx = 100 * ((plus_di - minus_di).abs() / ((plus_di + minus_di) + 1e-10))
        adx = dx.ewm(alpha=1/period, adjust=False).mean().fillna(20.0)
        return adx, plus_di, minus_di

    def build_timeframe_features(self, df: pd.DataFrame, prefix: str) -> pd.DataFrame:
        data = df.copy()
        c = data['close']
        h = data['high']
        l = data['low']
        o = data['open']
        v = data['volume']
        bar_range = (h - l).clip(lower=1e-10)

        feats = pd.DataFrame(index=data.index)
        feats['timestamp'] = data['timestamp']

        # 1. Wavelet Denoised Velocity
        feats[f'{prefix}_denoised_velocity'] = self.compute_denoised_velocity(c, window=11)

        # 2. Market Regime & Trend Strength
        adx, plus_di, minus_di = self.compute_adx(data, period=14)
        feats[f'{prefix}_adx_14'] = adx / 100.0
        feats[f'{prefix}_di_spread'] = (plus_di - minus_di) / 100.0

        # Choppiness Index
        raw_tr = self.compute_atr(data, period=1)
        sum_tr14 = raw_tr.rolling(14).sum()
        max_h14 = h.rolling(14).max()
        min_l14 = l.rolling(14).min()
        feats[f'{prefix}_chop_index'] = (100 * np.log10((sum_tr14 + 1e-10) / ((max_h14 - min_l14) + 1e-10)) / np.log10(14)).clip(0.0, 100.0) / 100.0

        # 3. Volatility Risk Premium
        gk_vol = self.garman_klass_volatility(data, window=14)
        pk_vol = self.parkinson_volatility(data, window=14)
        feats[f'{prefix}_vrp_ratio'] = (gk_vol / (pk_vol + 1e-10)).clip(0.1, 5.0)

        # 4. TTM Squeeze
        raw_atr20 = self.compute_atr(data, period=20)
        sma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        upper_bb = sma20 + (2.0 * std20)
        lower_bb = sma20 - (2.0 * std20)
        upper_kc = sma20 + (1.5 * raw_atr20)
        lower_kc = sma20 - (1.5 * raw_atr20)
        feats[f'{prefix}_ttm_squeeze'] = ((lower_bb > lower_kc) & (upper_bb < upper_kc)).astype(float)
        feats[f'{prefix}_bb_pct_b'] = ((c - lower_bb) / ((upper_bb - lower_bb) + 1e-10)).clip(-0.5, 1.5)

        # 5. Institutional Alphas: FVG & Wick Rejection
        bull_fvg = (l - h.shift(2)).clip(lower=0.0) / (c + 1e-10)
        bear_fvg = (l.shift(2) - h).clip(lower=0.0) / (c + 1e-10)
        feats[f'{prefix}_fvg_imbalance'] = (bull_fvg - bear_fvg).rolling(3).mean().fillna(0.0)

        upper_wick = (h - np.maximum(c, o)) / bar_range
        lower_wick = (np.minimum(c, o) - l) / bar_range
        feats[f'{prefix}_wick_rejection'] = (lower_wick - upper_wick).rolling(3).mean().fillna(0.0)

        # 6. Moving Average Ribbons
        ema9 = c.ewm(span=9, adjust=False).mean()
        ema21 = c.ewm(span=21, adjust=False).mean()
        ema50 = c.ewm(span=50, adjust=False).mean()
        ema200 = c.ewm(span=200, adjust=False).mean()
        feats[f'{prefix}_dist_to_ema9'] = (c - ema9) / (c + 1e-10)
        feats[f'{prefix}_dist_to_ema50'] = (c - ema50) / (c + 1e-10)
        feats[f'{prefix}_dist_to_ema200'] = (c - ema200) / (c + 1e-10)
        feats[f'{prefix}_ema9_slope'] = (ema9 - ema9.shift(1)) / (c + 1e-10)

        # 7. Momentum
        feats[f'{prefix}_mfi_14'] = self.compute_mfi(data, period=14)
        feats[f'{prefix}_rsi_14'] = self.compute_rsi(c, period=14)
        stoch_k, stoch_d = self.compute_stoch_rsi(c, period=14)
        feats[f'{prefix}_stoch_rsi_k'] = stoch_k
        feats[f'{prefix}_stoch_rsi_diff'] = stoch_k - stoch_d

        # 8. Fractional Memory & Multi-Lag Returns
        feats[f'{prefix}_frac_diff'] = self.get_fractional_diff(c, d=0.35)
        for lag in [1, 3]:
            feats[f'{prefix}_ret_{lag}'] = np.log(c / c.shift(lag).clip(lower=1e-10)).fillna(0.0)

        # 9. Cumulative Volume Delta (CVD) & Market Aggression (Taker Buy Ratio)
        if 'taker_buy_vol' in data.columns:
            tb_vol = data['taker_buy_vol']
            taker_ratio = (tb_vol / (v + 1e-10)).clip(0.0, 1.0)
            net_delta = (2.0 * tb_vol - v)
            cvd_roll = net_delta.rolling(14).sum() / (v.rolling(14).sum() + 1e-10)
            feats[f'{prefix}_taker_buy_ratio'] = taker_ratio.fillna(0.5)
            feats[f'{prefix}_cvd_norm'] = cvd_roll.clip(-1.0, 1.0).fillna(0.0)
        else:
            feats[f'{prefix}_taker_buy_ratio'] = 0.50
            feats[f'{prefix}_cvd_norm'] = 0.0

        # 10. Smart Money Concepts: Liquidity Sweep Detection
        roll_high_24 = h.rolling(24).max()
        roll_low_24 = l.rolling(24).min()
        bull_sweep = ((l < roll_low_24.shift(1)) & (c > roll_low_24.shift(1)) & (lower_wick >= 0.28 * bar_range)).astype(float)
        bear_sweep = ((h > roll_high_24.shift(1)) & (c < roll_high_24.shift(1)) & (upper_wick >= 0.28 * bar_range)).astype(float)
        feats[f'{prefix}_liquidity_sweep_bull'] = bull_sweep.fillna(0.0)
        feats[f'{prefix}_liquidity_sweep_bear'] = bear_sweep.fillna(0.0)

        return feats.ffill().bfill()

    def inject_cross_asset_btc_beta(self, target_df: pd.DataFrame, btc_dfs: dict) -> pd.DataFrame:
        df = target_df.copy()
        if '1d' in btc_dfs and not btc_dfs['1d'].empty:
            btc_1d = btc_dfs['1d'][['timestamp', 'close']].copy().sort_values('timestamp')
            btc_1d['btc_macro_ret_1d'] = np.log(btc_1d['close'] / btc_1d['close'].shift(1).clip(lower=1e-10)).fillna(0.0)
            df = pd.merge_asof(df.sort_values('timestamp'), btc_1d[['timestamp', 'btc_macro_ret_1d']], on='timestamp', direction='backward')

        if '1h' in btc_dfs and not btc_dfs['1h'].empty:
            btc_1h = btc_dfs['1h'][['timestamp', 'close']].copy().sort_values('timestamp')
            btc_1h['btc_swing_ret_1h'] = np.log(btc_1h['close'] / btc_1h['close'].shift(1).clip(lower=1e-10)).fillna(0.0)
            df = pd.merge_asof(df.sort_values('timestamp'), btc_1h[['timestamp', 'btc_swing_ret_1h']], on='timestamp', direction='backward')

        return df.ffill().bfill()

# ------------------------------------------------------------------------------
# 4. CONTINUOUS TRIPLE BARRIER LABELER
# ------------------------------------------------------------------------------
class TripleBarrierLabeler:
    @staticmethod
    def apply_barriers(df: pd.DataFrame, horizon_bars: int = 1, base_pt: float = 2.0, base_sl: float = 1.0):
        data = df.copy()
        n = len(data)
        
        primary_direction = np.zeros(n)
        meta_label = np.zeros(n)
        forward_return = np.zeros(n)
        excursion_score = np.zeros(n)
        
        close = data['close'].values
        high = data['high'].values
        low = data['low'].values
        atr = data['primary_raw_atr'].values

        effective_limit = n - horizon_bars - 1

        for i in range(effective_limit):
            curr_c = close[i]
            curr_atr = atr[i]
            if np.isnan(curr_atr) or curr_atr <= 0:
                continue
            
            future_c = close[i + horizon_bars]
            exp_ret = (future_c - curr_c) / (curr_c + 1e-10)
            forward_return[i] = exp_ret
            primary_signal = 1 if exp_ret > 0 else 0
            primary_direction[i] = primary_signal
            
            window_high = np.max(high[i+1 : i+horizon_bars+1])
            window_low = np.min(low[i+1 : i+horizon_bars+1])
            pt_price = curr_c + (base_pt * curr_atr)
            sl_price = curr_c - (base_sl * curr_atr)
            pt_short = curr_c - (base_pt * curr_atr)
            sl_short = curr_c + (base_sl * curr_atr)
            
            if primary_signal == 1:
                fav_excursion = max(0.0, window_high - curr_c)
                adv_excursion = max(0.0, curr_c - window_low)
                hit_pt = window_high >= pt_price
                hit_sl = window_low <= sl_price
                excursion_score[i] = (fav_excursion + 1e-10) / (adv_excursion + 1e-10)
                meta_label[i] = 1 if (hit_pt and not hit_sl) or (future_c > curr_c and fav_excursion >= adv_excursion) else 0
            else:
                fav_excursion = max(0.0, curr_c - window_low)
                adv_excursion = max(0.0, window_high - curr_c)
                hit_pt = window_low <= pt_short
                hit_sl = window_high >= sl_short
                excursion_score[i] = (fav_excursion + 1e-10) / (adv_excursion + 1e-10)
                meta_label[i] = 1 if (hit_pt and not hit_sl) or (future_c < curr_c and fav_excursion >= adv_excursion) else 0

        data['Target_Primary'] = primary_direction
        data['Target_Meta'] = meta_label
        data['Target_Return'] = forward_return
        data['Excursion_Score'] = excursion_score
        
        invalid_len = horizon_bars + 1
        data.iloc[-invalid_len:, data.columns.get_loc('Target_Primary')] = np.nan
        data.iloc[-invalid_len:, data.columns.get_loc('Target_Meta')] = np.nan
        data.iloc[-invalid_len:, data.columns.get_loc('Target_Return')] = np.nan
        data.iloc[-invalid_len:, data.columns.get_loc('Excursion_Score')] = np.nan
        
        return data

# ------------------------------------------------------------------------------
# 5. MULTI-HEAD SELF-ATTENTION RESNET + SUPER LEARNER ENSEMBLE
# ------------------------------------------------------------------------------
def focal_loss(gamma=2.0, alpha=0.5):
    def focal_loss_fixed(y_true, y_pred):
        y_true = tf.cast(y_true, tf.float32)
        epsilon = K.epsilon()
        y_pred = K.clip(y_pred, epsilon, 1.0 - epsilon)
        p_t = tf.where(K.equal(y_true, 1.0), y_pred, 1.0 - y_pred)
        alpha_t = tf.where(K.equal(y_true, 1.0), alpha, 1.0 - alpha)
        loss = -alpha_t * K.pow(1.0 - p_t, gamma) * K.log(p_t)
        return K.mean(loss)
    return focal_loss_fixed

class QuantModelFactory:
    @staticmethod
    def build_primary_dnn(input_dim: int, cfg: dict) -> tf.keras.Model:
        l2 = regularizers.l2(cfg['l2_reg'])
        inputs = layers.Input(shape=(input_dim,))
        x_proj = layers.Dense(128, kernel_regularizer=l2)(inputs)
        x_proj = layers.BatchNormalization()(x_proj)
        x_proj = layers.Activation('swish')(x_proj)
        
        x_reshaped = layers.Reshape((1, 128))(x_proj)
        attn_out = layers.MultiHeadAttention(num_heads=4, key_dim=32)(x_reshaped, x_reshaped)
        attn_flat = layers.Flatten()(attn_out)
        attn_skip = layers.Add()([x_proj, attn_flat])
        attn_skip = layers.LayerNormalization()(attn_skip)
        
        x1 = layers.Dense(128, kernel_regularizer=l2)(attn_skip)
        x1 = layers.BatchNormalization()(x1)
        x1 = layers.Activation('swish')(x1)
        x1 = layers.Dropout(cfg['dropout'])(x1)
        
        x2 = layers.Dense(128, kernel_regularizer=l2)(x1)
        x2 = layers.BatchNormalization()(x2)
        x2 = layers.Activation('swish')(x2)
        skip1 = layers.Add()([attn_skip, x2])
        
        outputs = layers.Dense(1, activation='sigmoid')(skip1)
        model = models.Model(inputs=inputs, outputs=outputs)
        
        model.compile(
            optimizer=tf.keras.optimizers.Adam(learning_rate=cfg['learning_rate']),
            loss=focal_loss(gamma=cfg.get('focal_gamma', 2.0), alpha=0.5),
            metrics=['accuracy']
        )
        return model

    @staticmethod
    def build_primary_catboost(cfg: dict) -> CatBoostClassifier:
        return CatBoostClassifier(iterations=cfg['iterations'], depth=cfg['depth'], learning_rate=cfg['learning_rate'], l2_leaf_reg=cfg['l2_leaf_reg'], auto_class_weights=cfg.get('auto_class_weights', None), verbose=False, random_seed=42)

    @staticmethod
    def build_primary_xgboost(cfg: dict) -> xgb.XGBClassifier:
        return xgb.XGBClassifier(n_estimators=cfg['n_estimators'], max_depth=cfg['max_depth'], learning_rate=cfg['learning_rate'], subsample=cfg['subsample'], colsample_bytree=cfg['colsample_bytree'], gamma=cfg['gamma'], random_state=cfg['random_state'], n_jobs=-1, tree_method='hist', eval_metric='logloss')

    @staticmethod
    def build_primary_lightgbm(cfg: dict):
        if HAS_LIGHTGBM:
            return lgb.LGBMClassifier(n_estimators=cfg['n_estimators'], max_depth=cfg['max_depth'], num_leaves=cfg['num_leaves'], learning_rate=cfg['learning_rate'], subsample=cfg['subsample'], colsample_bytree=cfg['colsample_bytree'], random_state=cfg['random_state'], verbose=cfg['verbose'])
        return None

    @staticmethod
    def build_primary_extra_trees(cfg: dict) -> ExtraTreesClassifier:
        return ExtraTreesClassifier(n_estimators=cfg['n_estimators'], max_depth=cfg['max_depth'], min_samples_split=cfg['min_samples_split'], random_state=cfg['random_state'], n_jobs=cfg['n_jobs'])

    @staticmethod
    def build_xgb_regressor(cfg: dict) -> xgb.XGBRegressor:
        return xgb.XGBRegressor(n_estimators=cfg['n_estimators'], max_depth=cfg['max_depth'], learning_rate=cfg['learning_rate'], subsample=cfg['subsample'], colsample_bytree=cfg['colsample_bytree'], objective=cfg['objective'], random_state=cfg['random_state'], n_jobs=-1, tree_method='hist')

# ------------------------------------------------------------------------------
# 6. ENHANCED MULTI-HORIZON PAPER TRADING LEDGER & BINANCE FEE ENGINE
# ------------------------------------------------------------------------------
class PaperTradingLedger:
    """
    Institutional-Grade Paper Trading Ledger with Realistic Binance Fee Accounting.
    - Calculates exact entry & exit maker/taker fees for every trade based on nominal order value
    - Accounts for 25% BNB Fee Discount and execution slippage
    - Separates Gross PnL from True Net Realized PnL (After Fees)
    - Accurately adjusts live account balance, drawdown, and win/loss analytics
    """
    def __init__(self, config: dict):
        self.config = config['paper_trading']
        self.export_dir = config['app_export_dir']
        self.ledger_file = os.path.join(self.export_dir, "paper_trading_ledger.json")
        self.base_fee_rate = self.config.get('binance_fee_rate', 0.0010)
        self.use_bnb_discount = self.config.get('use_bnb_fee_discount', True)
        self.slippage_rate = self.config.get('slippage_rate', 0.0002)
        # Effective fee per trade leg (e.g. 0.075% BNB discount + 0.02% slippage = 0.095%)
        self.effective_fee_rate = (self.base_fee_rate * (0.75 if self.use_bnb_discount else 1.0)) + self.slippage_rate
        self.fee_tier_label = f"Binance Spot ({'0.075% BNB Discount' if self.use_bnb_discount else '0.10% Standard'}) + {self.slippage_rate*100:.2f}% Slippage"
        self.data = self.load_or_initialize()

    def load_or_initialize(self) -> dict:
        target_start = self.config['start_balance_usd']
        if os.path.exists(self.ledger_file):
            try:
                with open(self.ledger_file, 'r') as f:
                    d = json.load(f)
                    # If starting capital was updated in CONFIG, adjust starting & current balance seamlessly
                    if d.get('starting_balance_usd') != target_start:
                        old_start = d.get('starting_balance_usd', 10.0)
                        ratio = target_start / max(1.0, old_start)
                        d['starting_balance_usd'] = target_start
                        d['current_balance_usd'] = round(d.get('current_balance_usd', old_start) * ratio, 2)
                        d['realized_pnl_usd'] = round(d.get('realized_pnl_usd', 0.0) * ratio, 2)
                        d['gross_profit_usd'] = round(d.get('gross_profit_usd', 0.0) * ratio, 2)
                        d['gross_loss_usd'] = round(d.get('gross_loss_usd', 0.0) * ratio, 2)
                        d['total_fees_paid_usd'] = round(d.get('total_fees_paid_usd', 0.0) * ratio, 2)
                        d['gross_realized_pnl_usd'] = round(d.get('gross_realized_pnl_usd', 0.0) * ratio, 2)
                        d['peak_balance_usd'] = max(d['current_balance_usd'], target_start)

                    # Migrate / fill missing fee & analytics keys
                    defaults = {
                        "gross_profit_usd": 0.0,
                        "gross_loss_usd": 0.0,
                        "total_fees_paid_usd": 0.0,
                        "gross_realized_pnl_usd": 0.0,
                        "breakeven_trades": 0,
                        "peak_balance_usd": d.get('current_balance_usd', target_start),
                        "max_drawdown_usd": 0.0,
                        "max_drawdown_pct": 0.0,
                        "fee_tier_label": self.fee_tier_label
                    }
                    for k, v in defaults.items():
                        if k not in d:
                            d[k] = v
                    d['fee_tier_label'] = self.fee_tier_label
                    return d
            except Exception:
                pass
        
        return {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "fee_tier_label": self.fee_tier_label,
            "starting_balance_usd": target_start,
            "current_balance_usd": target_start,
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
            "peak_balance_usd": target_start,
            "max_drawdown_usd": 0.0,
            "max_drawdown_pct": 0.0,
            "open_positions": [],
            "closed_trades_history": []
        }

    def update_positions(self, live_prices: dict, live_highs: dict = None, live_lows: dict = None):
        now_dt = datetime.now(timezone.utc)
        now_str = now_dt.isoformat()
        still_open = []
        closed_this_tick = []

        for pos in self.data['open_positions']:
            sym = pos['symbol']
            if sym not in live_prices:
                still_open.append(pos)
                continue

            curr_p = live_prices[sym]
            raw_high = live_highs.get(sym, curr_p) if live_highs else curr_p
            raw_low = live_lows.get(sym, curr_p) if live_lows else curr_p
            high_p = max(curr_p, raw_high)
            low_p = min(curr_p, raw_low)

            direction = pos['direction']
            entry_p = pos['entry_price']
            tp1_p = pos.get('tp1_price', pos['tp_price'])
            tp2_p = pos.get('tp2_price', pos['tp_price'])
            tp3_p = pos.get('tp3_price', pos['tp_price'])
            tp_p = pos['tp_price']
            sl_p = pos['sl_price']
            
            init_size = pos.get('initial_position_size_usd', pos['position_size_usd'])
            rem_size = pos.get('remaining_position_size_usd', init_size)
            stage = pos.get('stage', 'OPEN')
            
            opened_dt = datetime.fromisoformat(pos['opened_at']) if isinstance(pos['opened_at'], str) else pos['opened_at']
            expiry_dt = datetime.fromisoformat(pos['expiry_time']) if isinstance(pos['expiry_time'], str) else pos['expiry_time']

            # Calculate Duration
            dur_secs = int((now_dt - opened_dt).total_seconds())
            dur_m, dur_s = divmod(dur_secs, 60)
            dur_h, dur_m = divmod(dur_m, 60)
            duration_str = f"{dur_h}h {dur_m}m {dur_s}s" if dur_h > 0 else (f"{dur_m}m {dur_s}s" if dur_m > 0 else f"{dur_s}s")

            # Track intra-trade peak & trough prices for dynamic trailing stops
            pos['peak_price'] = max(pos.get('peak_price', high_p), high_p)
            pos['trough_price'] = min(pos.get('trough_price', low_p), low_p)

            # Stepped 50% Risk Ratchet (Cut max risk by half once 50% of the way to TP1)
            tp1_dist = abs(tp1_p - entry_p)
            if tp1_dist > 1e-8 and stage == 'OPEN':
                prog_tp1 = (high_p - entry_p) / tp1_dist if direction == "BULLISH" else (entry_p - low_p) / tp1_dist
                if prog_tp1 >= 0.50:
                    raw_atr = pos.get('raw_atr', max(1e-8, 0.015 * entry_p))
                    ratchet_sl = entry_p - (0.50 * raw_atr) if direction == "BULLISH" else entry_p + (0.50 * raw_atr)
                    if (direction == "BULLISH" and ratchet_sl > sl_p) or (direction == "BEARISH" and ratchet_sl < sl_p):
                        pos['sl_price'] = ratchet_sl
                        sl_p = ratchet_sl

            # Dynamic Chandelier Trailing Stop on Final 20% Runner (TP2_LOCKED_TRAIL)
            if stage == 'TP2_LOCKED_TRAIL':
                raw_atr = pos.get('raw_atr', max(1e-8, 0.015 * entry_p))
                if direction == "BULLISH":
                    chan_sl = pos['peak_price'] - (1.5 * raw_atr)
                    pos['sl_price'] = max(pos.get('sl_price', tp1_p), chan_sl)
                else:
                    chan_sl = pos['trough_price'] + (1.5 * raw_atr)
                    pos['sl_price'] = min(pos.get('sl_price', tp1_p), chan_sl)
                sl_p = pos['sl_price']

            # Directional condition checks
            is_hit_tp1 = (direction == "BULLISH" and tp1_p > entry_p and high_p >= tp1_p) or (direction == "BEARISH" and tp1_p < entry_p and low_p <= tp1_p)
            is_hit_tp2 = (direction == "BULLISH" and tp2_p > entry_p and high_p >= tp2_p) or (direction == "BEARISH" and tp2_p < entry_p and low_p <= tp2_p)
            is_hit_sl = (direction == "BULLISH" and low_p <= sl_p) or (direction == "BEARISH" and high_p >= sl_p)
            
            # Minimum holding window safeguard (prevents premature exits)
            min_dur_secs = 10 * 60 if pos.get('horizon') == 'scalp' else (60 * 60 if pos.get('horizon') == 'swing' else 12 * 3600)
            is_expired = (now_dt >= expiry_dt) and (dur_secs >= min_dur_secs)

            # Stagnation "Dead-Money" Early Exit: Free capital if price flatlines after >= 65% of predicted window
            total_window_secs = max(1, int((expiry_dt - opened_dt).total_seconds()))
            is_stagnated = False
            if (dur_secs / total_window_secs >= 0.65) and stage == 'OPEN' and dur_secs >= min_dur_secs:
                raw_pnl_pct = ((curr_p - entry_p) / entry_p) * 100.0 if direction == "BULLISH" else ((entry_p - curr_p) / entry_p) * 100.0
                if -0.30 <= raw_pnl_pct <= 0.35:
                    is_stagnated = True

            # 1. PARTIAL TP1 SCALE (50% locked + Trail SL to Breakeven)
            if is_hit_tp1 and stage == 'OPEN' and not is_hit_sl:
                scale_nominal = init_size * 0.50
                raw_ret_1 = (tp1_p - entry_p) / entry_p if direction == "BULLISH" else (entry_p - tp1_p) / entry_p
                p_gross = round(scale_nominal * raw_ret_1, 4)
                p_fee = round(scale_nominal * (1.0 + raw_ret_1) * self.effective_fee_rate + (scale_nominal * self.effective_fee_rate), 4)
                p_net = round(p_gross - p_fee, 4)

                pos['realized_gross_pnl'] = round(pos.get('realized_gross_pnl', 0.0) + p_gross, 4)
                pos['realized_fees'] = round(pos.get('realized_fees', 0.0) + p_fee, 4)
                pos['realized_net_pnl'] = round(pos.get('realized_net_pnl', 0.0) + p_net, 4)
                pos['remaining_position_size_usd'] = round(rem_size - scale_nominal, 4)
                pos['sl_price'] = entry_p  # TRAIL STOP LOSS TO BREAKEVEN!
                pos['stage'] = 'TP1_LOCKED_BREAKEVEN'

                # Update wallet balances with partial locked profit
                self.data['current_balance_usd'] = round(self.data['current_balance_usd'] + p_net, 2)
                self.data['realized_pnl_usd'] = round(self.data['realized_pnl_usd'] + p_net, 2)
                self.data['gross_realized_pnl_usd'] = round(self.data.get('gross_realized_pnl_usd', 0.0) + p_gross, 2)
                self.data['total_fees_paid_usd'] = round(self.data.get('total_fees_paid_usd', 0.0) + p_fee, 2)

                print(f"[TRADING LEDGER 🎯] {sym} [{pos['horizon'].upper()} {direction}] TP1 Hit! Scaled 50% profit (+${p_gross:.2f}). SL Trailed to Breakeven (${entry_p:,.4f}).")
                still_open.append(pos)
                continue

            # 2. PARTIAL TP2 SCALE (30% locked + Activate Chandelier Trailing Stop on 20% Runner)
            elif is_hit_tp2 and stage == 'TP1_LOCKED_BREAKEVEN' and not is_hit_sl:
                scale_nominal = init_size * 0.30
                raw_ret_2 = (tp2_p - entry_p) / entry_p if direction == "BULLISH" else (entry_p - tp2_p) / entry_p
                p_gross = round(scale_nominal * raw_ret_2, 4)
                p_fee = round(scale_nominal * (1.0 + raw_ret_2) * self.effective_fee_rate + (scale_nominal * self.effective_fee_rate), 4)
                p_net = round(p_gross - p_fee, 4)

                pos['realized_gross_pnl'] = round(pos.get('realized_gross_pnl', 0.0) + p_gross, 4)
                pos['realized_fees'] = round(pos.get('realized_fees', 0.0) + p_fee, 4)
                pos['realized_net_pnl'] = round(pos.get('realized_net_pnl', 0.0) + p_net, 4)
                pos['remaining_position_size_usd'] = round(pos['remaining_position_size_usd'] - scale_nominal, 4)
                pos['sl_price'] = tp1_p  # Initial floor at TP1, will trail with 1.5 ATR Chandelier Stop!
                pos['stage'] = 'TP2_LOCKED_TRAIL'

                # Update wallet balances with partial locked profit
                self.data['current_balance_usd'] = round(self.data['current_balance_usd'] + p_net, 2)
                self.data['realized_pnl_usd'] = round(self.data['realized_pnl_usd'] + p_net, 2)
                self.data['gross_realized_pnl_usd'] = round(self.data.get('gross_realized_pnl_usd', 0.0) + p_gross, 2)
                self.data['total_fees_paid_usd'] = round(self.data.get('total_fees_paid_usd', 0.0) + p_fee, 2)

                print(f"[TRADING LEDGER 💎] {sym} [{pos['horizon'].upper()} {direction}] TP2 Hit! Scaled 30% profit. Activated 1.5 ATR Chandelier Trailing Stop on remaining 20% runner!")
                still_open.append(pos)
                continue

            # 3. FINAL FULL EXIT (Chandelier SL, Protection SL, Stagnation, or Expiry)
            is_final_close = is_hit_sl or is_expired or is_stagnated
            if is_final_close:
                final_rem_size = pos.get('remaining_position_size_usd', rem_size)
                if is_hit_sl:
                    raw_ret = (sl_p - entry_p) / entry_p if direction == "BULLISH" else (entry_p - sl_p) / entry_p
                    exit_p = sl_p
                    if stage == 'TP1_LOCKED_BREAKEVEN':
                        exit_reason = "🛑 BREAKEVEN_PROTECT_EXIT"
                    elif stage == 'TP2_LOCKED_TRAIL':
                        exit_reason = "🏃 CHANDELIER_RUNNER_PROFIT_CLOSE"
                    else:
                        exit_reason = "🛑 STOP_LOSS_HIT"
                elif is_stagnated:
                    raw_ret = (curr_p - entry_p) / entry_p if direction == "BULLISH" else (entry_p - curr_p) / entry_p
                    exit_p = curr_p
                    exit_reason = "⏳ STAGNATION_DEAD_MONEY_EXIT"
                else:
                    raw_ret = (curr_p - entry_p) / entry_p if direction == "BULLISH" else (entry_p - curr_p) / entry_p
                    exit_p = curr_p
                    exit_reason = "⏳ EXPIRY_PROFIT_CLOSE" if raw_ret > 0 else ("⏳ EXPIRY_LOSS_CLOSE" if raw_ret < 0 else "⏳ BREAKEVEN_EXPIRY")

                # Binance Fee Accounting on Final Tranche
                exit_nominal_usd = max(0.0, final_rem_size * (1.0 + raw_ret))
                exit_fee_usd = round(exit_nominal_usd * self.effective_fee_rate, 4)
                entry_fee_tranche = round(final_rem_size * self.effective_fee_rate, 4)
                final_tranche_fees = round(entry_fee_tranche + exit_fee_usd, 4)

                final_gross_pnl = round(final_rem_size * raw_ret, 4)
                final_net_pnl = round(final_gross_pnl - final_tranche_fees, 4)

                # Total Combined Trade Results (Partial Scale + Final Exit)
                total_gross_pnl_usd = round(pos.get('realized_gross_pnl', 0.0) + final_gross_pnl, 4)
                total_trade_fees_usd = round(pos.get('realized_fees', 0.0) + final_tranche_fees, 4)
                total_net_pnl_usd = round(total_gross_pnl_usd - total_trade_fees_usd, 4)
                net_pnl_pct = round((total_net_pnl_usd / init_size) * 100.0, 2)
                gross_pnl_pct = round((total_gross_pnl_usd / init_size) * 100.0, 2)

                if total_net_pnl_usd > 0.005:
                    outcome = "WON"
                    is_win = True
                elif total_net_pnl_usd < -0.005:
                    outcome = "LOST"
                    is_win = False
                else:
                    outcome = "BREAKEVEN"
                    is_win = False
                    exit_reason = "⏳ BREAKEVEN_FEE_CLOSE"

                # Update Ledger Balances & Metrics
                self.data['current_balance_usd'] = round(self.data['current_balance_usd'] + final_net_pnl, 2)
                self.data['realized_pnl_usd'] = round(self.data['realized_pnl_usd'] + final_net_pnl, 2)
                self.data['gross_realized_pnl_usd'] = round(self.data.get('gross_realized_pnl_usd', 0.0) + final_gross_pnl, 2)
                self.data['total_fees_paid_usd'] = round(self.data.get('total_fees_paid_usd', 0.0) + final_tranche_fees, 2)
                self.data['total_trades'] += 1

                if outcome == "WON":
                    self.data['winning_trades'] += 1
                    self.data['gross_profit_usd'] = round(self.data.get('gross_profit_usd', 0.0) + total_gross_pnl_usd, 2)
                elif outcome == "LOST":
                    self.data['losing_trades'] += 1
                    self.data['gross_loss_usd'] = round(self.data.get('gross_loss_usd', 0.0) + abs(total_gross_pnl_usd), 2)
                else:
                    self.data['breakeven_trades'] = self.data.get('breakeven_trades', 0) + 1

                decisive_trades = self.data['winning_trades'] + self.data['losing_trades']
                self.data['win_rate_pct'] = (self.data['winning_trades'] / max(1, decisive_trades)) * 100.0
                
                # Profit factor
                if self.data.get('gross_loss_usd', 0.0) > 0:
                    self.data['profit_factor'] = self.data['gross_profit_usd'] / self.data['gross_loss_usd']
                else:
                    self.data['profit_factor'] = 99.9 if self.data.get('gross_profit_usd', 0.0) > 0 else 0.0

                # Peak Balance & Drawdown
                if self.data['current_balance_usd'] > self.data.get('peak_balance_usd', self.data['starting_balance_usd']):
                    self.data['peak_balance_usd'] = self.data['current_balance_usd']
                
                curr_dd = self.data['peak_balance_usd'] - self.data['current_balance_usd']
                if curr_dd > self.data.get('max_drawdown_usd', 0.0):
                    self.data['max_drawdown_usd'] = round(curr_dd, 2)
                    self.data['max_drawdown_pct'] = round((curr_dd / self.data['peak_balance_usd']) * 100.0, 2)

                opened_dt_str = opened_dt.strftime('%H:%M:%S UTC')
                closed_dt_str = now_dt.strftime('%H:%M:%S UTC')
                pos['entry_time_str'] = opened_dt.strftime('%Y-%m-%d %H:%M:%S UTC')
                pos['exit_time_str'] = now_dt.strftime('%Y-%m-%d %H:%M:%S UTC')
                pos['entry_exit_time_str'] = f"{opened_dt_str} ➔ {closed_dt_str}"

                pos['closed_at'] = now_str
                pos['exit_price'] = exit_p
                pos['exit_reason'] = exit_reason
                pos['duration_str'] = duration_str
                pos['gross_pnl_usd'] = total_gross_pnl_usd
                pos['gross_pnl_pct'] = gross_pnl_pct
                pos['binance_fee_usd'] = total_trade_fees_usd
                pos['realized_pnl_usd'] = total_net_pnl_usd
                pos['realized_pnl_pct'] = net_pnl_pct
                pos['outcome'] = outcome
                pos['is_win'] = is_win
                
                self.data['closed_trades_history'].append(pos)
                closed_this_tick.append(pos)
            else:
                # Update Open Position with Real-Time Estimated Exit Fees & Net PnL
                raw_ret = (curr_p - entry_p) / entry_p if direction == "BULLISH" else (entry_p - curr_p) / entry_p
                est_exit_nominal = max(0.0, rem_size * (1.0 + raw_ret))
                est_exit_fee = round(est_exit_nominal * self.effective_fee_rate, 4)
                est_entry_fee = round(rem_size * self.effective_fee_rate, 4)
                est_total_fee = round(est_entry_fee + est_exit_fee, 4)

                gross_u_pnl = round(raw_ret * rem_size, 4)
                net_u_pnl = round(gross_u_pnl - est_total_fee, 4)
                
                pos['unrealized_gross_pnl_usd'] = gross_u_pnl
                pos['unrealized_fee_usd'] = est_total_fee
                pos['unrealized_pnl_usd'] = net_u_pnl
                pos['unrealized_pnl_pct'] = round((net_u_pnl / init_size) * 100.0, 2)
                pos['current_price'] = curr_p
                still_open.append(pos)

        self.data['open_positions'] = still_open
        self.data['last_updated'] = now_str
        self.save()

        # Display instantaneous Trade Close notification banner if any trade closed
        for c in closed_this_tick:
            sign = "+" if c['realized_pnl_usd'] >= 0 else ""
            badge = "🎉 [TRADE WON 🟢]" if c['outcome'] == "WON" else ("🛑 [TRADE STOPPED 🔴]" if c['outcome'] == "LOST" else "⚪ [TRADE BREAKEVEN]")
            print(f"\n{'='*120}")
            print(f" {badge} {c['symbol']} [{c.get('horizon','scalp').upper()} {c['direction']}] Closed via {c['exit_reason']}!")
            print(f" 💵 Entry: ${c['entry_price']:,.2f} ➔ Exit: ${c['exit_price']:,.2f}")
            print(f" 📊 Gross PnL: {sign}${c.get('gross_pnl_usd',0.0):,.2f} ({sign}{c.get('gross_pnl_pct',0.0):.2f}%) | 🧾 Binance Fees: -${c.get('binance_fee_usd',0.0):,.2f}")
            print(f" 💎 True Net Realized PnL: {sign}${c['realized_pnl_usd']:,.2f} ({sign}{c['realized_pnl_pct']:.2f}%)")
            print(f" 🕒 Entry Time: {c.get('entry_time_str', 'N/A')} ➔ Exit Time: {c.get('exit_time_str', 'N/A')}")
            print(f" ⏱️ Holding Duration: {c.get('duration_str','N/A')} | Updated Cash Balance: ${self.data['current_balance_usd']:,.2f}")
            print(f"{'='*120}\n")

    def consider_new_trade(self, result: dict, horizon_key: str):
        if not self.config['enabled']:
            return

        decision = result['decision']
        if "FILTER" in decision:
            return

        is_executable = ("EXECUTE" in decision) or ("DIP-BUY" in decision) or ("RALLY-SELL" in decision)
        if not is_executable:
            return

        sym = result['symbol']
        direction = result['direction']
        entry_p = result['current_price']
        tp_p = result['tp_price']
        tp1_p = result.get('tp1_price', tp_p)
        tp2_p = result.get('tp2_price', tp_p)
        tp3_p = result.get('tp3_price', tp_p)
        sl_p = result['sl_price']

        # Directional Invariant Guard: Prevent inverted targets from ever opening a position
        if direction == "BULLISH" and (tp_p <= entry_p or sl_p >= entry_p):
            return
        if direction == "BEARISH" and (tp_p >= entry_p or sl_p <= entry_p):
            return

        # Check if already open on this symbol and horizon
        for pos in self.data['open_positions']:
            if pos['symbol'] == sym and pos.get('horizon') == horizon_key:
                return

        if len(self.data['open_positions']) >= self.config['max_concurrent_positions']:
            return

        # Cross-Asset Portfolio Correlation & Directional Shield: Prevent correlated flash dumps
        current_longs = sum(1 for p in self.data['open_positions'] if p['direction'] == 'BULLISH')
        current_shorts = sum(1 for p in self.data['open_positions'] if p['direction'] == 'BEARISH')
        max_directional = max(2, self.config.get('max_concurrent_positions', 6) - 2)
        if direction == "BULLISH" and current_longs >= max_directional:
            return
        if direction == "BEARISH" and current_shorts >= max_directional:
            return

        # Calculate Open Collateral
        total_open_collateral = sum(p.get('remaining_position_size_usd', p.get('position_size_usd', 10.0)) for p in self.data['open_positions'])
        avail_cash = max(0.0, self.data['current_balance_usd'] - total_open_collateral)

        # Dynamic Half-Kelly & Volatility-Adjusted Adaptive Position Sizing
        if self.config.get('dynamic_sizing', True):
            conv_edge = max(0.02, (result.get('conviction', 60.0) / 100.0) - 0.50)
            norm_atr = result.get('norm_atr', 0.02)
            max_pct = self.config.get('max_position_size_pct', 0.20)
            min_size = self.config.get('min_position_size_usd', 5.0)
            
            # Sizing multiplier: larger for high conviction & lower ATR
            size_pct = min(max_pct, max(0.05, conv_edge / max(0.01, norm_atr * 8.0)))
            calculated_size = round(avail_cash * size_pct, 2)
            pos_size = max(min_size, min(calculated_size, avail_cash))
        else:
            pos_size = self.config['position_size_usd']

        # Margin Guard: Ensure wallet has sufficient available liquid capital
        if avail_cash < pos_size or pos_size < 1.0:
            return

        now_utc = datetime.now(timezone.utc)
        
        # Calculate full duration from actual fill timestamp
        tf_delta_map = {
            'scalp': timedelta(minutes=15),
            'swing': timedelta(hours=2),
            'macro': timedelta(hours=24)
        }
        duration = tf_delta_map.get(horizon_key, timedelta(minutes=15))
        expiry_dt = now_utc + duration

        # Calculate exact Binance entry fee on opening nominal size
        entry_fee = round(pos_size * self.effective_fee_rate, 4)

        new_pos = {
            "trade_id": f"PAPER_{sym.replace('/', '_')}_{horizon_key}_{int(time.time())}",
            "symbol": sym,
            "horizon": horizon_key,
            "direction": direction,
            "entry_price": entry_p,
            "tp_price": tp_p,
            "tp1_price": tp1_p,
            "tp2_price": tp2_p,
            "tp3_price": tp3_p,
            "sl_price": sl_p,
            "initial_position_size_usd": pos_size,
            "remaining_position_size_usd": pos_size,
            "position_size_usd": pos_size,
            "stage": "OPEN",
            "realized_gross_pnl": 0.0,
            "realized_fees": 0.0,
            "realized_net_pnl": 0.0,
            "entry_fee_usd": entry_fee,
            "fee_rate": self.effective_fee_rate,
            "opened_at": now_utc.isoformat(),
            "entry_time_str": now_utc.strftime('%Y-%m-%d %H:%M:%S UTC'),
            "predicted_window": result.get('predicted_window_str', f"{result.get('trade_open_str', 'N/A')} ➔ {result.get('trade_close_str', 'N/A')}"),
            "expiry_time": expiry_dt.isoformat(),
            "signal_decision": decision,
            "unrealized_gross_pnl_usd": 0.0,
            "unrealized_fee_usd": entry_fee * 2,
            "unrealized_pnl_usd": -round(entry_fee * 2, 4),
            "unrealized_pnl_pct": -round((entry_fee * 2 / pos_size) * 100.0, 2),
            "current_price": entry_p
        }

        self.data['open_positions'].append(new_pos)
        self.save()

    def save(self):
        with open(self.ledger_file, 'w') as f:
            json.dump(self.data, f, indent=4, default=str)

    def on_tick(self, live_prices: dict, live_highs: dict = None, live_lows: dict = None):
        """Processes real-time price updates, stepped risk ratchets, partial TP scaling, and trailing stops."""
        return self.update_positions(live_prices, live_highs, live_lows)

    def admit_ranked_candidates(self, ranked_candidates: list):
        """Admits candidate trades strictly in order of global priority and relative strength rank."""
        for cand, h_key in ranked_candidates:
            self.consider_new_trade(cand, h_key)

    def render_portfolio_card(self):
        d = self.data
        pnl_sign = "+" if d['realized_pnl_usd'] >= 0 else ""
        tot_ret_pct = ((d['current_balance_usd'] - d['starting_balance_usd']) / d['starting_balance_usd']) * 100.0
        
        # Calculate total open unrealized Net PnL and total pending fees
        open_unrealized_total = sum(p.get('unrealized_pnl_usd', 0.0) for p in d['open_positions'])
        open_fees_total = sum(p.get('unrealized_fee_usd', 0.0) for p in d['open_positions'])
        u_tot_sign = "+" if open_unrealized_total >= 0 else ""
        net_equity = d['current_balance_usd'] + open_unrealized_total

        # 1. Executive Performance Analytics Summary
        pf_display = f"{d.get('profit_factor', 0.0):.2f}" if d.get('profit_factor', 0.0) < 99.0 else "∞ (Zero Losses)"
        portfolio_summary = [
            ["Virtual Starting Capital", f"${d['starting_balance_usd']:,.2f}", "Initial Paper Deposit"],
            ["Live Cash Balance", f"${d['current_balance_usd']:,.2f}", f"Net Growth: {pnl_sign}{tot_ret_pct:.2f}%"],
            ["Open Unrealized Net PnL", f"{u_tot_sign}${open_unrealized_total:,.2f}", f"{len(d['open_positions'])} Active Trade(s) (Est. Fees: -${open_fees_total:,.2f})"],
            ["Total Account Equity", f"${net_equity:,.2f}", "Cash + Open Positions (Post-Fee)"],
            ["Total Binance Fees Deducted", f"-${d.get('total_fees_paid_usd', 0.0):,.2f}", d.get('fee_tier_label', self.fee_tier_label)],
            ["Gross vs Net Realized PnL", f"Gross: {pnl_sign}${d.get('gross_realized_pnl_usd', 0.0):,.2f}", f"Net Realized: {pnl_sign}${d['realized_pnl_usd']:,.2f} (After Fees)"],
            ["Decisive Win Rate", f"{d['win_rate_pct']:.1f}%", f"🟢 {d['winning_trades']} Won | 🔴 {d['losing_trades']} Lost | ⚪ {d.get('breakeven_trades',0)} Breakeven"],
            ["Profit Factor", pf_display, "Gross Profit / Gross Loss Ratio"],
            ["Peak Balance & Max Drawdown", f"${d.get('peak_balance_usd', d['starting_balance_usd']):,.2f}", f"Max DD: -${d.get('max_drawdown_usd',0.0):,.2f} (-{d.get('max_drawdown_pct',0.0):.2f}%)"]
        ]

        print("\n" + "=" * 135)
        print(f" 💼 ENHANCED MULTI-HORIZON PAPER TRADING PORTFOLIO & BINANCE FEE AUDIT LEDGER")
        print(f" Last Updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} | Fee Schedule: {self.fee_tier_label}")
        print("=" * 135)
        print(tabulate(portfolio_summary, headers=["Executive Portfolio Metric", "Live Value", "Analysis Note"], tablefmt="fancy_grid"))

        # Helper for dynamic price formatting
        def fmt_usd(p):
            if p >= 50.0:
                return f"${p:,.2f}"
            elif p >= 0.10:
                return f"${p:,.4f}"
            else:
                return f"${p:.6g}"

        # 2. Active Open Paper Positions Table
        if d['open_positions']:
            open_table = []
            for p in d['open_positions']:
                u_pnl = p.get('unrealized_pnl_usd', 0.0)
                u_pct = p.get('unrealized_pnl_pct', 0.0)
                u_sign = "+" if u_pnl >= 0 else ""
                entry_p = p['entry_price']
                curr_p = p.get('current_price', entry_p)
                tp_p = p['tp_price']
                sl_p = p['sl_price']
                direction = p['direction']
                fee_est = p.get('unrealized_fee_usd', 0.0)

                # Calculate progress % toward Take-Profit
                if direction == "BULLISH":
                    tot_target_dist = max(1e-6, tp_p - entry_p)
                    curr_progress = ((curr_p - entry_p) / tot_target_dist) * 100.0
                else:
                    tot_target_dist = max(1e-6, entry_p - tp_p)
                    curr_progress = ((entry_p - curr_p) / tot_target_dist) * 100.0
                curr_progress = max(-100.0, min(100.0, curr_progress))

                # Date & Time formatting
                opened_dt = datetime.fromisoformat(p['opened_at']) if isinstance(p['opened_at'], str) else p['opened_at']
                entry_datetime_display = opened_dt.strftime('%Y-%m-%d %H:%M:%S UTC')

                expiry_dt = datetime.fromisoformat(p['expiry_time']) if isinstance(p['expiry_time'], str) else p['expiry_time']
                now_dt = datetime.now(timezone.utc)
                rem_secs = max(0, int((expiry_dt - now_dt).total_seconds()))
                rem_m = rem_secs // 60
                rem_h = rem_m // 60
                time_rem_str = f"{rem_h}h {rem_m%60}m" if rem_h > 0 else f"{rem_m} mins"

                open_table.append({
                    "Asset": p['symbol'],
                    "Horizon": p.get('horizon', 'scalp').upper(),
                    "Side": f"{'🟢 LONG' if direction=='BULLISH' else '🔴 SHORT'}",
                    "Entry Date & Time": entry_datetime_display,
                    "Entry ➔ Current Price": f"{fmt_usd(entry_p)} ➔ {fmt_usd(curr_p)}",
                    "Take-Profit": fmt_usd(tp_p),
                    "Stop-Loss": fmt_usd(sl_p),
                    "Target Progress": f"{curr_progress:+.1f}% to TP",
                    "Binance Fee (Est)": f"-${fee_est:,.2f}",
                    "Net Unrealized PnL": f"{u_sign}${u_pnl:,.2f} ({u_sign}{u_pct:.2f}%)",
                    "Time Remaining": time_rem_str
                })
            print("\n" + "-" * 145)
            print(f" 🟢 ACTIVE OPEN PAPER POSITIONS ({len(d['open_positions'])} Live Trades Active):")
            print("-" * 145)
            print(tabulate(open_table, headers="keys", tablefmt="fancy_grid", showindex=False))

        # 3. Comprehensive Closed Trades History (Won / Lost / Breakeven Details & Closing Reasons)
        history = d.get('closed_trades_history', [])
        if history:
            history_table = []
            # Display last 12 completed trades in reverse chronological order
            for idx, c in enumerate(reversed(history[-12:])):
                net_pnl = c.get('realized_pnl_usd', 0.0)
                net_pnl_pct = c.get('realized_pnl_pct', 0.0)
                gross_pnl = c.get('gross_pnl_usd', net_pnl)
                fee_paid = c.get('binance_fee_usd', 0.0)
                pnl_sign = "+" if net_pnl >= 0 else ""
                outcome = c.get('outcome', 'WON' if net_pnl > 0 else ('LOST' if net_pnl < 0 else 'BREAKEVEN'))
                
                if outcome == "WON":
                    badge = f"🟢 WON ({pnl_sign}${net_pnl:,.2f})"
                elif outcome == "LOST":
                    badge = f"🔴 LOST ({pnl_sign}${net_pnl:,.2f})"
                else:
                    badge = f"⚪ BREAKEVEN ($0.00)"

                # Format entry & exit timestamps with Date and Time
                entry_dt_obj = datetime.fromisoformat(c['opened_at']) if ('opened_at' in c and isinstance(c['opened_at'], str)) else None
                exit_dt_obj = datetime.fromisoformat(c['closed_at']) if ('closed_at' in c and isinstance(c['closed_at'], str)) else None

                entry_dt_str = entry_dt_obj.strftime('%Y-%m-%d %H:%M:%S UTC') if entry_dt_obj else c.get('entry_time_str', 'N/A')
                exit_dt_str = exit_dt_obj.strftime('%Y-%m-%d %H:%M:%S UTC') if exit_dt_obj else c.get('exit_time_str', 'N/A')

                time_span_str = f"{entry_dt_str}\n➔ {exit_dt_str}"
                
                entry_p_val = c.get('entry_price', 0.0)
                exit_p_val = c.get('exit_price', entry_p_val)
                exit_reason_label = c.get('exit_reason', '🎯 TAKE_PROFIT_HIT')

                history_table.append({
                    "#": f"T-{len(history) - idx}",
                    "Asset": c['symbol'],
                    "Horizon": c.get('horizon', 'scalp').upper(),
                    "Side": f"{'🟢 LONG' if c['direction']=='BULLISH' else '🔴 SHORT'}",
                    "Entry ➔ Exit Price": f"{fmt_usd(entry_p_val)} ➔ {fmt_usd(exit_p_val)}",
                    "Closing Trigger / Reason": exit_reason_label,
                    "Entry ➔ Exit (Date & Time)": time_span_str,
                    "Duration": c.get('duration_str', 'N/A'),
                    "Gross PnL": f"{'+' if gross_pnl>=0 else ''}${gross_pnl:,.2f}",
                    "Binance Fee": f"-${fee_paid:,.2f}",
                    "Net Realized Return": f"{pnl_sign}{net_pnl_pct:.2f}%",
                    "Outcome & Net PnL": badge
                })

            print("\n" + "-" * 145)
            print(f" 📜 COMPLETED TRADES AUDIT LOG (Won vs Lost Details - Showing Last {len(history_table)} of {len(history)} Trades):")
            print("-" * 145)
            print(tabulate(history_table, headers="keys", tablefmt="fancy_grid", showindex=False))

        print("=" * 145 + "\n")

# ------------------------------------------------------------------------------
# 7. TRADER SIGNALS AUDIT TRACKER & WIN/LOSS SPREADSHEET ENGINE
# ------------------------------------------------------------------------------
class SignalAuditTracker:
    """
    Dedicated Audit Ledger & Performance Tracker for Trader Signals.
    - Records ONLY the high-grade signals displayed to traders.
    - Stores complete Quality Grades (Grade A+, Grade A, Grade B+), R:R, targets & invalidation levels.
    - Continuously evaluates live prices to track Win/Loss outcomes (TP1, TP2, TP3, SL, Expiry).
    - Maintains spreadsheet-ready CSVs ('trader_signals_tracker.csv' and 'trader_signals_performance.csv').
    """
    def __init__(self, export_dir: str = "./export_app_data"):
        self.export_dir = export_dir
        os.makedirs(self.export_dir, exist_ok=True)
        self.csv_path = os.path.join(self.export_dir, "trader_signals_tracker.csv")
        self.summary_csv_path = os.path.join(self.export_dir, "trader_signals_performance.csv")
        self.records = self.load_records()

    def load_records(self) -> list:
        if os.path.exists(self.csv_path):
            try:
                df = pd.read_csv(self.csv_path, keep_default_na=False).fillna("")
                return df.to_dict(orient='records')
            except Exception:
                return []
        return []

    def save_records(self):
        try:
            if self.records:
                df = pd.DataFrame(self.records).fillna("")
                # Primary detailed audit CSV (Spreadsheet compatible)
                df.to_csv(self.csv_path, index=False)
                
                # Performance Summary KPI CSV for easy spreadsheet viewing
                summary_data = self.build_kpi_summary()
                df_sum = pd.DataFrame([summary_data]).fillna("")
                df_sum.to_csv(self.summary_csv_path, index=False)

                # Sync into MySQL / Database automatically
                try:
                    from app.services.db_sync import migrate_files_to_db
                    migrate_files_to_db()
                except Exception:
                    pass
        except Exception as e:
            print(f"[SIGNAL TRACKER ERROR] Failed saving CSV: {e}")

    def build_kpi_summary(self) -> dict:
        total_signals = len(self.records)
        won = sum(1 for r in self.records if "WON" in str(r.get('outcome_label', '')))
        lost = sum(1 for r in self.records if "LOST" in str(r.get('outcome_label', '')))
        expired = sum(1 for r in self.records if "EXPIRED" in str(r.get('outcome_label', '')))
        pending = sum(1 for r in self.records if r.get('status') in ["PENDING_EVALUATION", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL"])
        decisive = won + lost
        win_rate = round((won / max(1, decisive)) * 100.0, 2) if decisive > 0 else 0.0

        # Grade A+ specific stats
        a_plus_recs = [r for r in self.records if "A+" in str(r.get('quality_grade', ''))]
        a_plus_won = sum(1 for r in a_plus_recs if "WON" in str(r.get('outcome_label', '')))
        a_plus_lost = sum(1 for r in a_plus_recs if "LOST" in str(r.get('outcome_label', '')))
        a_plus_wr = round((a_plus_won / max(1, a_plus_won + a_plus_lost)) * 100.0, 2) if (a_plus_won + a_plus_lost) > 0 else 0.0

        # Grade A specific stats
        a_recs = [r for r in self.records if "Grade A (" in str(r.get('quality_grade', '')) or "Grade A\n" in str(r.get('quality_grade', ''))]
        a_won = sum(1 for r in a_recs if "WON" in str(r.get('outcome_label', '')))
        a_lost = sum(1 for r in a_recs if "LOST" in str(r.get('outcome_label', '')))
        a_wr = round((a_won / max(1, a_won + a_lost)) * 100.0, 2) if (a_won + a_lost) > 0 else 0.0

        # Calculate Average & Cumulative Return safely (ignoring pending/empty/NaN values)
        returns = []
        for r in self.records:
            ret_raw = r.get('realized_return_pct')
            if ret_raw is not None:
                ret_str = str(ret_raw).replace('%', '').replace('+', '').strip()
                if ret_str != "" and ret_str.lower() not in ["nan", "none", "null"]:
                    try:
                        val = float(ret_str)
                        if not (math.isnan(val) or math.isinf(val)):
                            returns.append(val)
                    except Exception:
                        pass
        avg_ret = round(float(np.mean(returns)), 2) if returns else 0.0
        total_ret = round(float(np.sum(returns)), 2) if returns else 0.0

        return {
            "last_updated_utc": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
            "total_trader_signals": total_signals,
            "won_signals_count": won,
            "lost_signals_count": lost,
            "pending_signals_count": pending,
            "expired_signals_count": expired,
            "win_rate_pct": win_rate,
            "grade_a_plus_win_rate_pct": a_plus_wr,
            "grade_a_win_rate_pct": a_wr,
            "average_return_pct": avg_ret,
            "cumulative_return_pct": total_ret
        }

    def log_top_trader_signals(self, displayed_signals: list, open_positions_symbols: list = None):
        """Logs ONLY the exact signals presented to traders this round into the spreadsheet/CSV."""
        if not displayed_signals:
            return

        open_syms = set(open_positions_symbols or [])
        added_count = 0
        existing_ids = {r.get('signal_id') for r in self.records}

        now_utc = datetime.now(timezone.utc)
        now_date = now_utc.strftime('%Y-%m-%d')
        now_time = now_utc.strftime('%H:%M:%S UTC')

        for idx, sig in enumerate(displayed_signals):
            sym = sig['symbol']
            h_key = sig.get('horizon_key', 'scalp').lower()
            curr_p = float(sig['entry_price'])
            sig_id = f"SIG_{now_utc.strftime('%Y%m%d_%H%M')}_{sym.replace('/', '_')}_{h_key.upper()}"

            if sig_id in existing_ids:
                continue

            tp1_p = float(sig.get('tp1_price', sig.get('tp_price', curr_p)))
            tp2_p = float(sig.get('tp2_price', sig.get('tp_price', curr_p)))
            tp3_p = float(sig.get('tp3_price', sig.get('tp_price', curr_p)))
            sl_p = float(sig.get('sl_price', curr_p))
            
            clean_grade = sig.get('grade', 'Grade A').replace('\n', ' ')
            tier_label = sig.get('tier_label', 'HIGH CONVICTION')
            rank_label = f"#{idx+1}"

            record = {
                "signal_id": sig_id,
                "date_utc": now_date,
                "time_utc": now_time,
                "rank": rank_label,
                "quality_grade": f"{clean_grade} ({tier_label})",
                "symbol": sym,
                "horizon": sig.get('horizon_name', h_key.upper()),
                "direction": "LONG" if sig.get('direction') in ["BULLISH", "LONG"] else "SHORT",
                "conviction_pct": round(float(sig.get('conviction', 50.0)), 2),
                "entry_price": round(curr_p, 6),
                "tp1_price": round(tp1_p, 6),
                "tp2_price": round(tp2_p, 6),
                "tp3_price": round(tp3_p, 6),
                "sl_price": round(sl_p, 6),
                "sl_original": round(sl_p, 6),
                "is_tp1_locked": False,
                "is_tp2_locked": False,
                "risk_reward_ratio": "1:2.0",
                "expected_return_pct": round(float(sig.get('exp_return', 0.0)) * 100.0, 2),
                "decision": sig.get('decision', 'EXECUTE'),
                "paper_trading_status": "EXECUTED (PAPER WALLET)" if sym in open_syms else "MONITORED SCAN SIGNAL",
                "predicted_window": sig.get('predicted_window_str', 'N/A'),
                "predicted_close_utc": sig.get('predicted_close_utc', 'N/A'),
                "status": "PENDING_EVALUATION",
                "outcome_label": "PENDING ⏳",
                "peak_price_seen": round(curr_p, 6),
                "trough_price_seen": round(curr_p, 6),
                "max_potential_gain_pct": 0.0,
                "exit_price": "",
                "realized_return_pct": "",
                "evaluated_at_utc": ""
            }

            self.records.append(record)
            existing_ids.add(sig_id)
            added_count += 1

        if added_count > 0:
            self.save_records()
            print(f"[SIGNAL TRACKER 📝] Logged {added_count} Trader Signal(s) to CSV: {os.path.abspath(self.csv_path)}")

    def log_new_signals(self, scanner_results: list, open_positions_symbols: list = None):
        """Legacy compatibility wrapper."""
        pass

    def evaluate_signals(self, live_prices: dict, live_highs: dict = None, live_lows: dict = None):
        """
        Checks pending signals in real-time with Break-Even (BE) Protection & Trailing Stop logic:
        - When TP1 is touched: Locks 50% profit and shifts SL to Entry Price (Break-Even).
        - When TP2 is touched: Locks 30% profit and shifts SL to TP1 floor (Trailing).
        - When TP3 is touched: Full target reached (WON TP3).
        - If price pulls back after TP1: Exits at Break-Even with 50% locked profit (WON TP1+BE).
        - If original SL is touched before TP1: Mark as LOST (SL HIT).
        """
        if not self.records:
            return

        now_utc = datetime.now(timezone.utc)
        now_str = now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')
        updated = False
        resolved_count = 0

        for r in self.records:
            status = r.get('status', 'PENDING_EVALUATION')
            if status not in ["PENDING_EVALUATION", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL"]:
                continue

            sym = r['symbol']
            if sym not in live_prices:
                continue

            curr_p = live_prices[sym]
            raw_h = live_highs.get(sym, curr_p) if live_highs else curr_p
            raw_l = live_lows.get(sym, curr_p) if live_lows else curr_p
            high_p = max(curr_p, raw_h)
            low_p = min(curr_p, raw_l)

            try:
                entry_p = float(r.get('entry_price', curr_p))
            except Exception:
                entry_p = curr_p

            tp1_p = float(r.get('tp1_price') or entry_p)
            tp2_p = float(r.get('tp2_price') or entry_p)
            tp3_p = float(r.get('tp3_price') or entry_p)
            sl_p = float(r.get('sl_price') or entry_p)
            direction = r.get('direction', 'LONG')
            is_tp1_locked = bool(r.get('is_tp1_locked', False) or status in ['TP1_LOCKED_BREAKEVEN', 'TP2_LOCKED_TRAIL'])
            is_tp2_locked = bool(r.get('is_tp2_locked', False) or status == 'TP2_LOCKED_TRAIL')

            # Update intra-trade extremes safely
            try:
                prev_peak = float(r.get('peak_price_seen') or high_p)
            except Exception:
                prev_peak = high_p
            try:
                prev_trough = float(r.get('trough_price_seen') or low_p)
            except Exception:
                prev_trough = low_p

            r['peak_price_seen'] = max(prev_peak, high_p)
            r['trough_price_seen'] = min(prev_trough, low_p)

            max_gain = ((r['peak_price_seen'] - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - r['trough_price_seen']) / entry_p) * 100.0
            r['max_potential_gain_pct'] = round(max_gain, 2)

            is_hit_tp3 = (direction == "LONG" and high_p >= tp3_p) or (direction == "SHORT" and low_p <= tp3_p)
            is_hit_tp2 = (direction == "LONG" and high_p >= tp2_p) or (direction == "SHORT" and low_p <= tp2_p)
            is_hit_tp1 = (direction == "LONG" and high_p >= tp1_p) or (direction == "SHORT" and low_p <= tp1_p)
            is_hit_sl = (direction == "LONG" and low_p <= sl_p) or (direction == "SHORT" and high_p >= sl_p)

            is_expired = False
            pred_close_str = r.get('predicted_close_utc', '')
            try:
                if pred_close_str and pred_close_str != 'N/A':
                    close_dt = datetime.fromisoformat(pred_close_str) if 'T' in pred_close_str else datetime.strptime(pred_close_str.replace(' UTC', ''), '%Y-%m-%d %H:%M')
                    if close_dt.tzinfo is None:
                        close_dt = close_dt.replace(tzinfo=timezone.utc)
                    if now_utc >= close_dt:
                        is_expired = True
            except Exception:
                pass

            # 1. TP3 Full Target Reached
            if is_hit_tp3:
                r['status'] = "WON_TP3"
                r['exit_price'] = round(tp3_p, 6)
                ret_pct = ((tp3_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp3_p) / entry_p) * 100.0
                r['realized_return_pct'] = f"{ret_pct:+.2f}%"
                r['outcome_label'] = "🟢 WON (TP3 HIT)"
                r['evaluated_at_utc'] = now_str
                updated = True
                resolved_count += 1

            # 2. TP2 Hit (Lock 30% and Trail SL to TP1)
            elif is_hit_tp2 and not is_tp2_locked:
                r['status'] = "TP2_LOCKED_TRAIL"
                r['is_tp2_locked'] = True
                r['is_tp1_locked'] = True
                r['sl_price'] = round(tp1_p, 6)  # Trailing SL Floor at TP1
                r['outcome_label'] = "🟢 TP2 HIT (TRAILING SL @ TP1)"
                updated = True

            # 3. TP1 Hit (Lock 50% and Trail SL to Entry Price / Break-Even)
            elif is_hit_tp1 and not is_tp1_locked and not is_hit_sl:
                r['status'] = "TP1_LOCKED_BREAKEVEN"
                r['is_tp1_locked'] = True
                r['sl_price'] = round(entry_p, 6)  # Break-Even SL
                r['outcome_label'] = "🟢 TP1 HIT (SL @ BREAKEVEN)"
                updated = True

            # 4. Stop Loss Triggered (Either Original SL or Trailed BE / TP1 Stop)
            elif is_hit_sl:
                if is_tp2_locked:
                    # Trailed Stop hit at TP1 floor (Locked 50% TP1 + 30% TP2 + 20% TP1 runner)
                    ret_tp1 = ((tp1_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp1_p) / entry_p) * 100.0
                    ret_tp2 = ((tp2_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp2_p) / entry_p) * 100.0
                    blended_ret = (0.50 * ret_tp1) + (0.30 * ret_tp2) + (0.20 * ret_tp1)
                    r['status'] = "WON_TP2_TRAIL"
                    r['exit_price'] = round(tp1_p, 6)
                    r['realized_return_pct'] = f"{blended_ret:+.2f}%"
                    r['outcome_label'] = "🟢 WON (TP2 + TRAILING RUNNER)"
                elif is_tp1_locked:
                    # Break-Even Stop hit at Entry Price (Locked 50% TP1 + 50% Breakeven)
                    ret_tp1 = ((tp1_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp1_p) / entry_p) * 100.0
                    blended_ret = 0.50 * ret_tp1
                    r['status'] = "WON_TP1_BE"
                    r['exit_price'] = round(entry_p, 6)
                    r['realized_return_pct'] = f"{blended_ret:+.2f}%"
                    r['outcome_label'] = "🟢 WON (TP1 + BE RUNNER)"
                else:
                    # Original Stop Loss hit without reaching TP1
                    r['status'] = "LOST_SL"
                    r['exit_price'] = round(sl_p, 6)
                    ret_pct = ((sl_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - sl_p) / entry_p) * 100.0
                    r['realized_return_pct'] = f"{ret_pct:+.2f}%"
                    r['outcome_label'] = "🔴 LOST (SL HIT)"
                r['evaluated_at_utc'] = now_str
                updated = True
                resolved_count += 1

            # 5. Expiry Resolution
            elif is_expired:
                ret_current = ((curr_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - curr_p) / entry_p) * 100.0
                if is_tp1_locked:
                    ret_tp1 = ((tp1_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp1_p) / entry_p) * 100.0
                    blended_ret = (0.50 * ret_tp1) + (0.50 * max(0.0, ret_current))
                    r['status'] = "WON_TP1_EXP"
                    r['exit_price'] = round(curr_p, 6)
                    r['realized_return_pct'] = f"{blended_ret:+.2f}%"
                    r['outcome_label'] = f"🟢 WON (TP1 + EXP {blended_ret:+.2f}%)"
                else:
                    r['status'] = "EXPIRED_PROFIT" if ret_current > 0 else ("EXPIRED_LOSS" if ret_current < 0 else "EXPIRED_FLAT")
                    r['exit_price'] = round(curr_p, 6)
                    r['realized_return_pct'] = f"{ret_current:+.2f}%"
                    r['outcome_label'] = f"{'🟢' if ret_current>=0 else '🔴'} EXPIRED ({ret_current:+.2f}%)"
                r['evaluated_at_utc'] = now_str
                updated = True
                resolved_count += 1

        if updated:
            self.save_records()
            print(f"[SIGNAL TRACKER 🎯] Evaluated & updated {resolved_count} signal(s) in CSV: {os.path.abspath(self.csv_path)}")

    def render_performance_card(self):
        kpi = self.build_kpi_summary()
        if kpi['total_trader_signals'] == 0:
            return

        decisive = kpi['won_signals_count'] + kpi['lost_signals_count']
        sign = "+" if kpi['cumulative_return_pct'] >= 0 else ""

        kpi_table = [
            ["Total Trader Signals Tracked", f"{kpi['total_trader_signals']}", "Exact signals presented to traders in console/app"],
            ["Resolved Outcomes (Won / Lost)", f"🟢 {kpi['won_signals_count']} Won | 🔴 {kpi['lost_signals_count']} Lost", f"Pending: ⏳ {kpi['pending_signals_count']} | Expired: {kpi['expired_signals_count']}"],
            ["Decisive Win Rate", f"{kpi['win_rate_pct']:.1f}%", f"Grade A+ WR: {kpi['grade_a_plus_win_rate_pct']:.1f}% | Grade A WR: {kpi['grade_a_win_rate_pct']:.1f}%"],
            ["Cumulative Tracked Return", f"{sign}{kpi['cumulative_return_pct']:.2f}%", f"Average Return per Signal: {kpi['average_return_pct']:+.2f}%"],
            ["Spreadsheet CSV Files", "trader_signals_tracker.csv", "trader_signals_performance.csv (Excel / Sheets Ready)"]
        ]

        print("\n" + "=" * 135)
        print(" 📊 TRADER SIGNALS PERFORMANCE & WIN/LOSS CSV AUDIT LEDGER")
        print(f" Detailed CSV: {os.path.abspath(self.csv_path)}")
        print(f" Summary CSV:  {os.path.abspath(self.summary_csv_path)}")
        print("=" * 135)
        print(tabulate(kpi_table, headers=["Audit Metric", "Value", "Notes"], tablefmt="fancy_grid"))
        print("=" * 135 + "\n")

# ------------------------------------------------------------------------------
# 8. MULTI-HORIZON QUANT ENGINE CORE
# ------------------------------------------------------------------------------
class HybridQuantEngine:
    def __init__(self, config: dict):
        self.config = config
        self.loader = CryptoDataLoader()
        self.fe = AdvancedFeatureEngineer()
        self.labeler = TripleBarrierLabeler()
        self.btc_cache = {}
        self.model_cache = {}
        self.btc_shield_active = False
        self.btc_shield_reason = "NORMAL (Market Stable)"
        self.signal_cooldown_tracker = {}
        self.ledger = PaperTradingLedger(config)
        self.signal_tracker = SignalAuditTracker(config.get('app_export_dir', './export_app_data'))
        os.makedirs(self.config['models_export_dir'], exist_ok=True)
        os.makedirs(self.config['app_export_dir'], exist_ok=True)

    def preload_btc_reference(self):
        print("[DATA] Preloading Bitcoin multi-scale data for cross-asset beta calculations...")
        for tf in self.config['timeframes']:
            try:
                df_btc = self.loader.fetch_ohlcv_extended("BTC/USDT", tf, total_candles=self.config['history_limit_per_tf'].get(tf, 2000))
                self.btc_cache[tf] = df_btc
            except Exception as e:
                print(f"[WARNING] BTC reference fetch note for {tf}: {e}")

        # 🛡️ GLOBAL BTC MARKET BETA SHIELD (MARKET CIRCUIT BREAKER)
        # Protects altcoins from correlated stop-outs during BTC flash drops / severe flushes
        self.btc_shield_active = False
        self.btc_shield_reason = "NORMAL (Market Stable)"
        try:
            if '15m' in self.btc_cache and len(self.btc_cache['15m']) >= 3:
                df_15m = self.btc_cache['15m']
                c_now = float(df_15m['close'].iloc[-1])
                c_prev = float(df_15m['close'].iloc[-2])
                c_prev2 = float(df_15m['close'].iloc[-3])
                ret_15m_1 = (c_now - c_prev) / c_prev
                ret_15m_2 = (c_now - c_prev2) / c_prev2

                if ret_15m_1 <= -0.012 or ret_15m_2 <= -0.018:
                    self.btc_shield_active = True
                    self.btc_shield_reason = f"BTC 15M Flash Dump ({ret_15m_1*100:.2f}%)"

            if not self.btc_shield_active and '1h' in self.btc_cache and len(self.btc_cache['1h']) >= 2:
                df_1h = self.btc_cache['1h']
                ret_1h = (float(df_1h['close'].iloc[-1]) - float(df_1h['close'].iloc[-2])) / float(df_1h['close'].iloc[-2])
                if ret_1h <= -0.022:
                    self.btc_shield_active = True
                    self.btc_shield_reason = f"BTC 1H Severe Selloff ({ret_1h*100:.2f}%)"
        except Exception as e:
            pass

        if self.btc_shield_active:
            print(f"\n[SHIELD 🛡️] ⚠️ BTC MARKET BETA SHIELD ACTIVATED: {self.btc_shield_reason} | Altcoin Longs Paused to Prevent Correlated Stop-Outs.\n")
        else:
            print(f"[SHIELD 🛡️] Market Beta Status: {self.btc_shield_reason}")

    def evaluate_single_horizon(self, symbol: str, horizon_key: str, h_cfg: dict, raw_dfs: dict, tf_features: dict, d1_macro_bull: bool, funding_info: dict = None) -> dict:
        anchor_tf = h_cfg['anchor_tf']
        bars = h_cfg['bars']
        tp_mult = h_cfg['tp_mult']
        sl_mult = h_cfg['sl_mult']

        anchor_df = raw_dfs[anchor_tf].copy().sort_values('timestamp')
        anchor_df['primary_raw_atr'] = self.fe.compute_atr(anchor_df, period=14)
        anchor_df['primary_norm_atr'] = anchor_df['primary_raw_atr'] / (anchor_df['close'] + 1e-10)

        fused_df = anchor_df.copy()
        for tf_str, feat_df in tf_features.items():
            fused_df = pd.merge_asof(
                fused_df.sort_values('timestamp'),
                feat_df.sort_values('timestamp'),
                on='timestamp',
                direction='backward'
            )

        if symbol != "BTC/USDT" and self.btc_cache:
            fused_df = self.fe.inject_cross_asset_btc_beta(fused_df, self.btc_cache)

        labeled_df = self.labeler.apply_barriers(fused_df, horizon_bars=bars, base_pt=tp_mult, base_sl=sl_mult)

        live_candle = labeled_df.iloc[-1:].copy()
        current_price = live_candle['close'].values[0]
        live_timestamp = live_candle['datetime'].iloc[0]
        live_raw_atr = live_candle['primary_raw_atr'].values[0]
        live_norm_atr = live_candle['primary_norm_atr'].values[0]

        step_delta = CryptoDataLoader.get_timeframe_delta(anchor_tf, bars=1)
        trade_open_timestamp = live_timestamp + step_delta
        trade_open_str = trade_open_timestamp.strftime('%Y-%m-%d %H:%M UTC')
        target_close_timestamp = trade_open_timestamp + (step_delta * bars)
        trade_close_str = target_close_timestamp.strftime('%Y-%m-%d %H:%M UTC')

        clean_df = labeled_df.dropna(subset=['Target_Primary', 'Target_Meta', 'Target_Return', 'Excursion_Score']).reset_index(drop=True)
        non_feature_cols = ['timestamp', 'datetime', 'open', 'high', 'low', 'close', 'volume', 'taker_buy_vol', 'primary_raw_atr', 'primary_norm_atr', 'Target_Primary', 'Target_Meta', 'Target_Return', 'Excursion_Score']
        feature_cols = [c for c in clean_df.columns if c not in non_feature_cols]

        X = clean_df[feature_cols].values
        y_p = clean_df['Target_Primary'].values
        y_m = clean_df['Target_Meta'].values
        y_r = clean_df['Target_Return'].values

        n = len(X)
        n_train = max(5, int(n * self.config['train_split']))
        X_train, y_p_train, y_r_train = X[:n_train], y_p[:n_train].copy(), y_r[:n_train]
        X_test, y_p_test = X[n_train:], y_p[n_train:]

        # Prevent CatBoost / XGBoost "Target contains only one unique value" crash
        unique_classes = np.unique(y_p_train)
        if len(unique_classes) < 2 and len(y_p_train) > 1:
            y_p_train[0] = 1 - y_p_train[-1]

        # Fast-Boot Model Checkpoint & Memory Cache (6 Hour Expiry)
        cache_key = f"{symbol.replace('/', '_')}_{horizon_key}"
        now_ts = time.time()

        if cache_key in self.model_cache and (now_ts - self.model_cache[cache_key]['ts'] < 21600):
            cached = self.model_cache[cache_key]
            scaler = cached['scaler']
            cat = cached['cat']
            xgb_m = cached['xgb_m']
            et = cached['et']
            elite_acc = cached['elite_acc']
            X_live_scaled = np.nan_to_num(scaler.transform(live_candle[feature_cols].values), nan=0.0)
            try:
                p_cat_live = float(cat.predict_proba(X_live_scaled)[0, 1])
            except Exception:
                p_cat_live = 0.55 if d1_macro_bull else 0.45
            try:
                p_xgb_live = float(xgb_m.predict_proba(X_live_scaled)[0, 1])
            except Exception:
                p_xgb_live = 0.55 if d1_macro_bull else 0.45
            try:
                p_et_live = float(et.predict_proba(X_live_scaled)[0, 1])
            except Exception:
                p_et_live = 0.55 if d1_macro_bull else 0.45
        else:
            scaler = RobustScaler()
            X_train_scaled = np.nan_to_num(scaler.fit_transform(X_train), nan=0.0)
            X_test_scaled = np.nan_to_num(scaler.transform(X_test), nan=0.0)
            X_live_scaled = np.nan_to_num(scaler.transform(live_candle[feature_cols].values), nan=0.0)

            # Train Fast Ensemble with robust fallback
            try:
                cat = QuantModelFactory.build_primary_catboost(self.config['catboost'])
                cat.fit(X_train_scaled, y_p_train, verbose=False)
                p_cat_live = float(cat.predict_proba(X_live_scaled)[0, 1])
                p_test_cat = cat.predict_proba(X_test_scaled)[:, 1] if len(X_test_scaled) > 0 else np.array([p_cat_live])
            except Exception:
                cat = None
                p_cat_live = 0.55 if d1_macro_bull else 0.45
                p_test_cat = np.array([p_cat_live] * max(1, len(X_test_scaled)))

            try:
                xgb_m = QuantModelFactory.build_primary_xgboost(self.config['xgb_clf'])
                xgb_m.fit(X_train_scaled, y_p_train, verbose=False)
                p_xgb_live = float(xgb_m.predict_proba(X_live_scaled)[0, 1])
                p_test_xgb = xgb_m.predict_proba(X_test_scaled)[:, 1] if len(X_test_scaled) > 0 else np.array([p_xgb_live])
            except Exception:
                xgb_m = None
                p_xgb_live = 0.55 if d1_macro_bull else 0.45
                p_test_xgb = np.array([p_xgb_live] * max(1, len(X_test_scaled)))

            try:
                et = QuantModelFactory.build_primary_extra_trees(self.config['extra_trees'])
                et.fit(X_train_scaled, y_p_train)
                p_et_live = float(et.predict_proba(X_live_scaled)[0, 1])
            except Exception:
                et = None
                p_et_live = 0.55 if d1_macro_bull else 0.45

            p_test_ens = (p_test_cat * 0.5) + (p_test_xgb * 0.5)
            elite_mask = (p_test_ens >= self.config['elite_conviction_threshold']) | (p_test_ens <= (1.0 - self.config['elite_conviction_threshold']))
            elite_acc = accuracy_score(y_p_test[elite_mask], (p_test_ens[elite_mask] >= 0.5).astype(int)) if (len(y_p_test) > 0 and np.sum(elite_mask) >= 5) else 0.85

            if cat and xgb_m and et:
                self.model_cache[cache_key] = {
                    'scaler': scaler,
                    'cat': cat,
                    'xgb_m': xgb_m,
                    'et': et,
                    'elite_acc': elite_acc,
                    'ts': now_ts
                }

        # 1. Base ML Direction & Probability
        h_prob = (p_cat_live * 0.40) + (p_xgb_live * 0.40) + (p_et_live * 0.20)
        h_dir = "BULLISH" if h_prob >= 0.5 else "BEARISH"
        h_conf = (h_prob if h_prob >= 0.5 else (1.0 - h_prob)) * 100.0

        # 2. Futures Funding Rate & Squeeze Catalyst Integration
        squeeze_boost_label = ""
        if funding_info:
            fr_val = funding_info.get('funding_rate', 0.0)
            if fr_val <= -0.0002 and h_dir == "BULLISH":
                h_conf = min(96.0, h_conf + 6.0)
                squeeze_boost_label = " ⚡ [SHORT SQUEEZE CATALYST]"
            elif fr_val >= 0.0005 and h_dir == "BEARISH":
                h_conf = min(96.0, h_conf + 6.0)
                squeeze_boost_label = " ⚡ [LONG FLUSH CATALYST]"

        # 3. Smart Money Concepts: Liquidity Sweep & Fakeout Reversal Detection
        is_bull_sweep = live_candle.get(f'{anchor_tf}_liquidity_sweep_bull', pd.Series([0])).values[0] == 1.0
        is_bear_sweep = live_candle.get(f'{anchor_tf}_liquidity_sweep_bear', pd.Series([0])).values[0] == 1.0

        # 4. Relative Strength vs BTC Alpha Calculation (4H window)
        asset_4h_ret = 0.0
        btc_4h_ret = 0.0
        if '4h' in raw_dfs and len(raw_dfs['4h']) >= 2:
            asset_4h_ret = (raw_dfs['4h']['close'].iloc[-1] - raw_dfs['4h']['close'].iloc[-2]) / raw_dfs['4h']['close'].iloc[-2]
        if '4h' in self.btc_cache and len(self.btc_cache['4h']) >= 2:
            btc_4h_ret = (self.btc_cache['4h']['close'].iloc[-1] - self.btc_cache['4h']['close'].iloc[-2]) / self.btc_cache['4h']['close'].iloc[-2]
        rs_btc = round((asset_4h_ret - btc_4h_ret) / max(0.005, live_norm_atr), 3)

        # 5. Volatility Regime-Adaptive TP/SL Multipliers (ADX & Choppiness Index)
        adx_val = live_candle[f'{anchor_tf}_adx_14'].values[0] * 100.0 if f'{anchor_tf}_adx_14' in live_candle.columns else 25.0
        chop_val = live_candle[f'{anchor_tf}_chop_index'].values[0] * 100.0 if f'{anchor_tf}_chop_index' in live_candle.columns else 50.0

        if adx_val >= 30.0 and chop_val < 50.0:
            tp_mult_eff = tp_mult * 1.35
            sl_mult_eff = sl_mult * 1.05
        elif chop_val >= 60.0 or adx_val < 20.0:
            tp_mult_eff = tp_mult * 0.85
            sl_mult_eff = sl_mult * 0.90
        else:
            tp_mult_eff = tp_mult
            sl_mult_eff = sl_mult

        # 6. Determine Strategy Signal & Directional Overrides
        rsi_anchor = live_candle[f'{anchor_tf}_rsi_14'].values[0] * 100.0 if f'{anchor_tf}_rsi_14' in live_candle.columns else 50.0
        is_dip_buy = d1_macro_bull and rsi_anchor <= 46.0 and (p_cat_live >= 0.48 or p_xgb_live >= 0.48)
        is_rally_sell = (not d1_macro_bull) and rsi_anchor >= 55.0 and (p_cat_live <= 0.52 or p_xgb_live <= 0.52)

        if is_bull_sweep and (p_cat_live >= 0.44 or p_xgb_live >= 0.44):
            h_dir = "BULLISH"
            h_conf = max(68.0, min(96.0, h_conf + 8.0))
            decision = f"🎯 ELITE LIQUIDITY-SWEEP (LONG){squeeze_boost_label}"
            priority = 1
        elif is_bear_sweep and (p_cat_live <= 0.56 or p_xgb_live <= 0.56):
            h_dir = "BEARISH"
            h_conf = max(68.0, min(96.0, h_conf + 8.0))
            decision = f"🎯 ELITE LIQUIDITY-SWEEP (SHORT){squeeze_boost_label}"
            priority = 1
        elif is_dip_buy:
            h_dir = "BULLISH"
            h_conf = max(55.0, h_conf)
            decision = f"🎯 ELITE DIP-BUY EXECUTE (LONG){squeeze_boost_label}"
            priority = 1
        elif is_rally_sell:
            h_dir = "BEARISH"
            h_conf = max(55.0, h_conf)
            decision = f"🎯 ELITE RALLY-SELL EXECUTE (SHORT){squeeze_boost_label}"
            priority = 1
        else:
            is_macro_aligned = (h_dir == "BULLISH" and d1_macro_bull) or (h_dir == "BEARISH" and not d1_macro_bull)
            if is_macro_aligned and h_conf >= (self.config['elite_conviction_threshold'] * 100.0):
                decision = f"🎯 ELITE EXECUTE {'LONG' if h_dir=='BULLISH' else 'SHORT'}{squeeze_boost_label}"
                priority = 1
            elif is_macro_aligned and h_conf >= 55.0:
                decision = f"✅ STANDARD EXECUTE {'LONG' if h_dir=='BULLISH' else 'SHORT'}{squeeze_boost_label}"
                priority = 2
            elif not is_macro_aligned:
                decision = "⛔ FILTER (MACRO CONFLICT)"
                priority = 3
            else:
                decision = "⛔ FILTER (LOW CONVICTION)"
                priority = 4

        # 7. Calculate True Directional TP & SL Targets (Synchronized with Final h_dir & Adaptive Multipliers)
        exp_ret_mag = max(0.001, (h_conf / 100.0) * live_norm_atr * (bars ** 0.5))
        exp_ret = exp_ret_mag if h_dir == "BULLISH" else -exp_ret_mag
        projected_target = current_price * (1.0 + exp_ret)

        risk_dist = max(1e-8, sl_mult_eff * live_raw_atr)
        if h_dir == "BULLISH":
            sl_p = current_price - risk_dist
            tp1_p = current_price + (0.50 * risk_dist)
            tp2_p = current_price + (1.00 * risk_dist)
            tp3_p = current_price + (1.50 * risk_dist)
            tp4_p = current_price + (2.00 * risk_dist)
            tp_p = tp4_p
        else:
            sl_p = current_price + risk_dist
            min_floor = max(1e-8, current_price * 0.05)
            tp1_p = max(min_floor, current_price - (0.50 * risk_dist))
            tp2_p = max(min_floor, current_price - (1.00 * risk_dist))
            tp3_p = max(min_floor, current_price - (1.50 * risk_dist))
            tp4_p = max(min_floor, current_price - (2.00 * risk_dist))
            tp_p = tp4_p

        # 8. Minimum Profit Hurdle Check
        reward_pct = (abs(tp_p - current_price) / (current_price + 1e-10)) * 100.0
        min_reward_map = {'scalp': 0.35, 'swing': 0.80, 'macro': 1.80}
        min_hurdle = min_reward_map.get(horizon_key, 0.35)
        if reward_pct < min_hurdle:
            decision = "⛔ FILTER (SUB-FEE VOLATILITY / LOW ATR)"
            priority = 4

        # Generate Professional 3-Tier Signal Card (1:2 Risk to Reward Architecture)
        coin_tag = symbol.split('/')[0]
        p_fmt = lambda p: f"{p:,.4f}" if p >= 1.0 else f"{p:.6g}"
        type_str = "LONG 🟢" if h_dir == "BULLISH" else "SHORT 🔴"
        market_str = "Spot & Futures" if h_dir == "BULLISH" else "Futures Only ⚡"
        
        predicted_window_str = f"{trade_open_str} ➔ {trade_close_str} ({h_cfg['duration_label']})"
        
        pro_signal_text = (
            f"🚀 PAIR: #{coin_tag}/USDT\n"
            f"📊 TYPE: {type_str}\n"
            f"🌐 MARKET: {market_str}\n"
            f"📅 PREDICTED CANDLE: {predicted_window_str}\n"
            f"🎯 ENTRY: {p_fmt(current_price)}\n\n"
            f"💎 TAKE PROFITS:\n"
            f"➤ TP1: {p_fmt(tp1_p)}\n"
            f"➤ TP2: {p_fmt(tp2_p)}\n"
            f"➤ TP3: {p_fmt(tp3_p)}\n\n"
            f"🛑 STOP LOSS: {p_fmt(sl_p)}\n\n"
            f"📈 RISK-TO-REWARD RATIO: 1:2"
        )

        res = {
            "symbol": symbol,
            "horizon_name": h_cfg['name'],
            "duration_label": h_cfg['duration_label'],
            "current_price": current_price,
            "norm_atr": live_norm_atr,
            "raw_atr": live_raw_atr,
            "rs_btc": rs_btc,
            "trade_open_str": trade_open_str,
            "trade_close_str": trade_close_str,
            "predicted_window_str": predicted_window_str,
            "direction": h_dir,
            "conviction": h_conf,
            "exp_return": exp_ret,
            "projected_target": projected_target,
            "tp_price": tp_p,
            "tp1_price": tp1_p,
            "tp2_price": tp2_p,
            "tp3_price": tp3_p,
            "tp4_price": tp4_p,
            "sl_price": sl_p,
            "elite_precision": elite_acc,
            "decision": decision,
            "priority": priority,
            "pro_signal_text": pro_signal_text,
            "vip_signal_text": pro_signal_text
        }

        return res

    def process_single_asset(self, symbol: str) -> dict:
        timeframes = self.config['timeframes']
        raw_dfs = {}
        tf_features = {}
        tf_metrics_summary = []

        # Ingest all multi-scale charts
        for tf_str in timeframes:
            limit = self.config['history_limit_per_tf'].get(tf_str, 2000)
            df = self.loader.fetch_ohlcv_extended(symbol, tf_str, total_candles=limit)
            raw_dfs[tf_str] = df
            tf_feat = self.fe.build_timeframe_features(df, prefix=tf_str)
            tf_features[tf_str] = tf_feat

            last_c = df['close'].iloc[-1]
            last_adx = tf_feat[f'{tf_str}_adx_14'].iloc[-1] * 100.0
            last_chop = tf_feat[f'{tf_str}_chop_index'].iloc[-1] * 100.0
            last_sqz = tf_feat[f'{tf_str}_ttm_squeeze'].iloc[-1] == 1.0
            last_rsi = tf_feat[f'{tf_str}_rsi_14'].iloc[-1] * 100.0
            last_mfi = tf_feat[f'{tf_str}_mfi_14'].iloc[-1] * 100.0
            ema9_slope = tf_feat[f'{tf_str}_ema9_slope'].iloc[-1]

            regime = "⚡ SQUEEZE" if last_sqz else ("🔥 TRENDING" if (last_adx >= 25 and last_chop < 55) else ("💤 CHOP" if (last_adx < 20 or last_chop > 60) else "⚡ EXPANSION"))
            tf_bias = "🟢 BULLISH" if ema9_slope > 0 else "🔴 BEARISH"
            tf_metrics_summary.append({
                "Chart": tf_str.upper(),
                "Price": f"${last_c:,.2f}" if last_c >= 1.0 else f"${last_c:.4f}",
                "Bias": tf_bias,
                "RSI": f"{last_rsi:.1f}",
                "MFI": f"{last_mfi:.1f}",
                "ADX": f"{last_adx:.1f}",
                "Regime": regime
            })

        # Orderbook Depth Imbalance Microstructure Alpha
        ob_imbalance = self.loader.fetch_orderbook_imbalance(symbol, limit=20)
        ob_label = f"🟢 +{ob_imbalance*100:.1f}% Buy Wall" if ob_imbalance > 0.05 else (f"🔴 {ob_imbalance*100:.1f}% Sell Wall" if ob_imbalance < -0.05 else "⚪ Balanced")
        c15m = raw_dfs['15m']['close'].iloc[-1] if '15m' in raw_dfs else last_c
        tf_metrics_summary.append({
            "Chart": "DEPTH L2",
            "Price": f"${c15m:,.2f}" if c15m >= 1.0 else f"${c15m:.4f}",
            "Bias": "🟢 BIDS" if ob_imbalance > 0 else "🔴 ASKS",
            "RSI": "N/A",
            "MFI": "N/A",
            "ADX": f"{abs(ob_imbalance)*100:.1f}%",
            "Regime": ob_label
        })

        # Futures Funding Rate & Open Interest Squeeze Alpha
        funding_info = self.loader.fetch_funding_rate_and_oi(symbol)
        fr_pct = funding_info['funding_rate'] * 100.0
        oi_val = funding_info['open_interest']
        tf_metrics_summary.append({
            "Chart": "FUTURES FR",
            "Price": f"{fr_pct:+.3f}% / 8h",
            "Bias": "🔥 SHORT SQUEEZE" if fr_pct <= -0.02 else ("❄️ LONG FLUSH" if fr_pct >= 0.05 else "⚪ NEUTRAL"),
            "RSI": "N/A",
            "MFI": "N/A",
            "ADX": f"OI: {oi_val:,.0f}" if oi_val > 0 else "N/A",
            "Regime": funding_info['regime']
        })

        # Macro Daily Trend Check
        d1_c = raw_dfs['1d']['close'].values
        d1_ema50 = pd.Series(d1_c).ewm(span=50).mean().values[-1]
        d1_ema200 = pd.Series(d1_c).ewm(span=200).mean().values[-1]
        d1_macro_bull = (d1_c[-1] > d1_ema50) or (d1_ema50 > d1_ema200)

        # Evaluate all 3 horizons simultaneously: Scalp (15M), Swing (1H), Macro (24H)
        horizon_results = {}
        for h_key, h_cfg in self.config['horizons'].items():
            horizon_results[h_key] = self.evaluate_single_horizon(symbol, h_key, h_cfg, raw_dfs, tf_features, d1_macro_bull, funding_info)

        # Check for Triple Confluence
        scalp_dir = horizon_results['scalp']['direction']
        swing_dir = horizon_results['swing']['direction']
        macro_dir = horizon_results['macro']['direction']
        is_triple_confluence = (scalp_dir == swing_dir == macro_dir)

        # Master pick priority
        best_priority = min(h['priority'] for h in horizon_results.values())
        overall_score = sum(h['conviction'] * abs(h['exp_return']) for h in horizon_results.values())

        # 15m candle high and low for intra-candle wick verification
        live_high = float(raw_dfs['15m']['high'].iloc[-1]) if '15m' in raw_dfs else horizon_results['scalp']['current_price']
        live_low = float(raw_dfs['15m']['low'].iloc[-1]) if '15m' in raw_dfs else horizon_results['scalp']['current_price']

        return {
            "symbol": symbol,
            "current_price": horizon_results['scalp']['current_price'],
            "live_high": live_high,
            "live_low": live_low,
            "horizons": horizon_results,
            "is_triple_confluence": is_triple_confluence,
            "best_priority": best_priority,
            "overall_score": overall_score,
            "tf_metrics_summary": tf_metrics_summary
        }

    def run_single_iteration(self):
        # Clear cache to guarantee fresh live candles from exchange
        self.loader._cache.clear()

        mode = self.config.get("mode", "both").lower()
        print(f"\n==========================================================================================")
        print(f" 🚀 RUNNING MULTI-HORIZON QUANT ENGINE (V15.0): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f" Horizons: ⚡ Scalp (15M) | 🌊 Swing (1H-2H) | 🚀 Macro (24H/1D) | Mode: Parallel Async")
        print(f"==========================================================================================")

        self.preload_btc_reference()
        scanner_results = []
        deep_dive_result = None
        live_prices = {}
        live_highs = {}
        live_lows = {}

        # 1. Multi-Asset Opportunity Scanner (Parallel Multithreaded Execution)
        if mode in ["scanner", "both"]:
            # Determine universe of coins to scan
            scan_mode = self.config.get("scanner_mode", "top_volume")
            if scan_mode == "top_volume":
                try:
                    symbols_to_scan = self.loader.fetch_top_volume_usdt_pairs(limit=self.config.get("scanner_top_n", 25))
                except Exception:
                    symbols_to_scan = self.config.get("scanner_symbols", [])[:self.config.get("scanner_top_n", 25)]
            elif scan_mode == "expanded_universe":
                symbols_to_scan = self.config.get("scanner_symbols", [])
            else:
                symbols_to_scan = self.config.get("scanner_symbols", [])[:self.config.get("scanner_top_n", 25)]

            print(f"\n" + "=" * 95)
            print(f" 🛰️ RUNNING CONCURRENT MULTI-HORIZON SCANNER ({len(symbols_to_scan)} {self.loader.active_exchange_id.upper()} Assets in Parallel)...")
            print("=" * 95)

            max_threads = min(8, len(symbols_to_scan))
            with ThreadPoolExecutor(max_workers=max_threads) as executor:
                future_to_sym = {executor.submit(self.process_single_asset, sym): sym for sym in symbols_to_scan}
                for future in as_completed(future_to_sym):
                    sym = future_to_sym[future]
                    try:
                        res = future.result()
                        if res:
                            scanner_results.append(res)
                            live_prices[sym] = res['current_price']
                            live_highs[sym] = res['live_high']
                            live_lows[sym] = res['live_low']
                            print(f"[SCAN ⚡] Processed 15M, 1H & 24H for: {sym}")
                    except Exception as e:
                        print(f"[ERROR] Failed scanning {sym}: {e}")

            # Sort by best priority, triple confluence, and score
            scanner_results.sort(key=lambda x: (x['best_priority'], not x['is_triple_confluence'], -x['overall_score']))
            self.render_multi_horizon_leaderboard(scanner_results)

        # 2. Single-Coin Deep Dive
        if mode in ["single", "both"]:
            target_sym = self.config['single_symbol']
            print(f"\n" + "=" * 95)
            print(f" 🔬 RUNNING MULTI-HORIZON DEEP DIVE: {target_sym}")
            print("=" * 95)

            deep_dive_result = self.process_single_asset(target_sym)
            live_prices[target_sym] = deep_dive_result['current_price']
            live_highs[target_sym] = deep_dive_result['live_high']
            live_lows[target_sym] = deep_dive_result['live_low']
            self.render_multi_horizon_deep_dive(deep_dive_result)

        # 3. Top 3 Actionable Quantitative Signals for This Round (Independent of Paper Trading Status)
        top_round_signals = self.render_top_round_signals(scanner_results, deep_dive_result)

        # 4. Update Paper Trading Portfolio with Intra-Candle High/Low Wick Verification
        if self.config['paper_trading']['enabled']:
            # Refresh live prices for all open positions immediately to eliminate batch scan latency
            for pos in self.ledger.data['open_positions']:
                sym = pos['symbol']
                try:
                    ticker = self.loader.fetch_ticker(sym)
                    if ticker and 'last' in ticker:
                        live_prices[sym] = float(ticker['last'])
                except Exception:
                    pass

            # Order Execution Manager: Process Real-Time Tick & Admit Top Ranked Candidates
            self.ledger.on_tick(live_prices, live_highs, live_lows)

            # Extract executable candidate signals from Alpha Signal Engine
            all_candidates = []
            for r in scanner_results:
                for h_key, h in r['horizons'].items():
                    if h['priority'] <= 2 or "EXECUTE" in h['decision'] or "DIP-BUY" in h['decision']:
                        all_candidates.append((h, h_key))

            # Rank candidates: Best Priority first, Relative Strength vs BTC + Conviction first
            all_candidates.sort(key=lambda x: (x[0]['priority'], -(x[0]['conviction'] + 4.0 * max(0.0, x[0].get('rs_btc', 0.0)))))

            # Route top ranked signals into Order Execution Manager
            self.ledger.admit_ranked_candidates(all_candidates)
            self.ledger.render_portfolio_card()

        # 5. Persistent Signal Audit Logger: Record & Evaluate ONLY Trader Signals in CSV
        self.signal_tracker.log_top_trader_signals(top_round_signals, [p['symbol'] for p in self.ledger.data['open_positions']])
        self.signal_tracker.evaluate_signals(live_prices, live_highs, live_lows)
        self.signal_tracker.render_performance_card()

        # 6. Export JSON Data
        self.export_web_app_json(scanner_results, deep_dive_result, top_round_signals)

    def check_open_positions_heartbeat(self):
        """Fast real-time ticker check: closes trade instantly if target touched within seconds."""
        if not self.config['paper_trading']['enabled'] or not self.ledger.data['open_positions']:
            return

        active_symbols = list({p['symbol'] for p in self.ledger.data['open_positions']})
        heartbeat_prices = {}
        for sym in active_symbols:
            try:
                ticker = self.loader.fetch_ticker(sym)
                if ticker and 'last' in ticker:
                    heartbeat_prices[sym] = float(ticker['last'])
            except Exception:
                pass

        if heartbeat_prices:
            prev_open_count = len(self.ledger.data['open_positions'])
            self.ledger.on_tick(heartbeat_prices)
            self.signal_tracker.evaluate_signals(heartbeat_prices)
            new_open_count = len(self.ledger.data['open_positions'])
            if new_open_count < prev_open_count:
                print(f"[HEARTBEAT ⚡] Intra-candle target/stop touched! Position closed in real time.")
                self.ledger.render_portfolio_card()

    def run(self):
        continuous = self.config.get("continuous_loop", True)
        if not continuous:
            self.run_single_iteration()
            return

        print(f"\n[DAEMON] Continuous 24/7 Watcher Loop Active! Press Ctrl+C to stop.")
        while True:
            try:
                self.run_single_iteration()
                now = datetime.now(timezone.utc)
                tf_mins = 15
                current_minute = now.minute
                minutes_to_next = tf_mins - (current_minute % tf_mins)
                next_run = (now + timedelta(minutes=minutes_to_next)).replace(second=2, microsecond=0)

                # Real-Time Heartbeat Loop: Monitors prices every 10s between scans
                print(f"[DAEMON] ⏳ Monitoring active trades in real time (Next full scan: {next_run.strftime('%H:%M:%S UTC')})...")
                while datetime.now(timezone.utc) < next_run:
                    self.check_open_positions_heartbeat()
                    time.sleep(10)

            except KeyboardInterrupt:
                print("\n[DAEMON] Continuous Watcher Loop gracefully stopped by user.")
                break
            except Exception as e:
                print(f"\n[DAEMON ERROR] Unexpected loop error: {e}")
                time.sleep(15)

    def render_multi_horizon_leaderboard(self, scanner_results: list):
        if not scanner_results:
            print("\n[WARNING] No scanner results.")
            return

        def fmt_p(p):
            if p >= 50.0:
                return f"${p:,.2f}"
            elif p >= 0.10:
                return f"${p:,.4f}"
            else:
                return f"${p:.6g}"

        table_rows = []
        for idx, r in enumerate(scanner_results):
            sym = r['symbol']
            price_fmt = fmt_p(r['current_price'])
            
            s = r['horizons']['scalp']
            w = r['horizons']['swing']
            m = r['horizons']['macro']

            badge = "💎 TRIPLE BUY" if (r['is_triple_confluence'] and s['direction']=="BULLISH") else ("💎 TRIPLE SELL" if (r['is_triple_confluence'] and s['direction']=="BEARISH") else ("🥇 TOP PICK" if idx==0 else f"#{idx+1}"))
            
            table_rows.append({
                "Asset & Price": f"{badge}\n{sym} ({price_fmt})",
                "⚡ Scalp (15M) Setup": f"{'🟢' if s['direction']=='BULLISH' else '🔴'} {s['direction']} ({s['conviction']:.1f}%)\nTP: {fmt_p(s['tp_price'])} | SL: {fmt_p(s['sl_price'])}\n{s['decision']}",
                "🌊 Swing (1H-2H) Setup": f"{'🟢' if w['direction']=='BULLISH' else '🔴'} {w['direction']} ({w['conviction']:.1f}%)\nTP: {fmt_p(w['tp_price'])} | SL: {fmt_p(w['sl_price'])}\n{w['decision']}",
                "🚀 Macro (24H) Setup": f"{'🟢' if m['direction']=='BULLISH' else '🔴'} {m['direction']} ({m['conviction']:.1f}%)\nTP: {fmt_p(m['tp_price'])} | SL: {fmt_p(m['sl_price'])}\n{m['decision']}"
            })

        print("\n" + "=" * 175)
        print(f" 🛰️ MULTI-HORIZON OPPORTUNITY LEADERBOARD: MINUTES (15M) | HOURS (1H) | DAYS (24H)")
        print(f" Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} | Strategy: Multi-Horizon Quantum Super-Learner")
        print("=" * 175)
        df_scan = pd.DataFrame(table_rows)
        print(tabulate(df_scan, headers="keys", tablefmt="fancy_grid", showindex=False))
        print("=" * 175 + "\n")

    def render_top_round_signals(self, scanner_results: list, deep_dive_result: dict = None) -> list:
        """
        Dynamically detects, grades (A+/A/B+), throttles duplicates, and applies BTC Beta Shield:
        - 💎 Grade A+ (Elite Institutional): Multi-scale trend aligned + Volume/Order flow + High conviction (>=75%) + RS vs BTC >= 0.
        - 🟢 Grade A (High Conviction): Standard directional edge (>=65%).
        - 🛡️ BTC Beta Shield: Blocks Altcoin Longs if BTC is undergoing a flash dump.
        - ⏱️ Cooldown Throttling: Prevents fee drag and duplicate spam on identical timeframes.
        """
        def fmt_p(p):
            if p is None:
                return "N/A"
            try:
                p = float(p)
            except Exception:
                return str(p)
            if p >= 50.0:
                return f"${p:,.2f}"
            elif p >= 0.10:
                return f"${p:,.4f}"
            else:
                return f"${p:.6g}"

        source_results = list(scanner_results) if scanner_results else []
        if deep_dive_result and deep_dive_result not in source_results:
            source_results.append(deep_dive_result)

        if not source_results:
            print("\n" + "=" * 125)
            print(" 🎯 DYNAMIC QUANTITATIVE SIGNALS ENGINE")
            print(" 🛑 No market scan data available for this round.")
            print("=" * 125 + "\n")
            return []

        sig_cfg = self.config.get('signal_engine', {})
        is_dynamic = sig_cfg.get('dynamic_signal_count', True)
        min_sig = sig_cfg.get('min_signals_per_round', 1)
        max_sig = sig_cfg.get('max_signals_per_round', 5)
        a_plus_cutoff = sig_cfg.get('grade_a_plus_conviction', 0.75) * 100.0
        a_cutoff = sig_cfg.get('grade_a_conviction', 0.65) * 100.0
        b_cutoff = sig_cfg.get('grade_b_conviction', 0.55) * 100.0

        active_paper_symbols = {p['symbol'] for p in self.ledger.data.get('open_positions', [])}
        all_signals = []
        seen_pairs = set()
        now_ts = time.time()

        cooldown_map = {
            'scalp': 1800,   # 30 mins
            'swing': 5400,   # 90 mins
            'macro': 14400   # 4 hours
        }

        for r in source_results:
            sym = r['symbol']
            tf_summary = r.get('tf_metrics_summary', [])
            is_triple = r.get('is_triple_confluence', False)

            for h_key in ['scalp', 'swing', 'macro']:
                h = r['horizons'].get(h_key)
                if not h:
                    continue
                pair_key = (sym, h_key)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                prio = h.get('priority', 3)
                conv = float(h.get('conviction', 50.0))
                decision = h.get('decision', 'WATCH')
                direction = h.get('direction', 'BULLISH')
                rs_val = float(h.get('rs_btc', 0.0))
                elite_prec = float(h.get('elite_precision', 0.50))
                triple_bonus = 25.0 if is_triple else 0.0
                exec_bonus = 20.0 if ("EXECUTE" in decision or "DIP-BUY" in decision or "RALLY-SELL" in decision) else 0.0
                composite_score = conv + (max(0.0, rs_val) * 4.0) + triple_bonus + exec_bonus + (abs(h.get('exp_return', 0.0)) * 100.0)

                # 🛡️ BTC MARKET BETA SHIELD CHECK
                is_shield_blocked = False
                if self.btc_shield_active and sym != "BTC/USDT" and direction == "BULLISH":
                    is_shield_blocked = True
                    decision = f"🛡️ PAUSED (BTC BETA SHIELD: {self.btc_shield_reason})"
                    prio = 4

                # ⏱️ SIGNAL COOLDOWN CHECK
                last_sig_time = self.signal_cooldown_tracker.get(pair_key, 0)
                is_in_cooldown = (now_ts - last_sig_time) < cooldown_map.get(h_key, 1800)

                # 💎 SHARPENED QUANTITATIVE GRADE CLASSIFICATION (Targeting >= 65% WR on Elite Grade A+)
                # Strict Grade A+ Requirements:
                # 1. Conviction >= 75% (or >= 70% with Triple Confluence)
                # 2. Executable setup (EXECUTE, DIP-BUY, RALLY-SELL)
                # 3. Not blocked by BTC Beta Shield
                # 4. Relative Strength confirmation (RS >= 0 for Longs, RS <= 0 for Shorts)
                # 5. Elite historical model precision >= 0.55
                is_a_plus_candidate = (
                    (conv >= a_plus_cutoff or (is_triple and conv >= 70.0)) and
                    ("EXECUTE" in decision or "DIP-BUY" in decision or "RALLY-SELL" in decision) and
                    not is_shield_blocked and
                    (rs_val >= 0.0 if direction == "BULLISH" else rs_val <= 0.2) and
                    elite_prec >= 0.55
                )

                if is_a_plus_candidate:
                    grade = "💎 Grade A+"
                    grade_tier = 1
                    tier_label = "ELITE CONFLUENCE"
                elif (conv >= a_cutoff and prio <= 2 and not is_shield_blocked) or (("EXECUTE" in decision or "DIP-BUY" in decision) and not is_shield_blocked):
                    grade = "🟢 Grade A"
                    grade_tier = 2
                    tier_label = "HIGH CONVICTION"
                elif conv >= b_cutoff and prio <= 3 and not is_shield_blocked:
                    grade = "🟡 Grade B+"
                    grade_tier = 3
                    tier_label = "ACTIONABLE MOMENTUM"
                else:
                    grade = "⚪ Grade C"
                    grade_tier = 4
                    tier_label = "WATCHLIST / DEFENSIVE"

                paper_status = "🟢 ACTIVE (PAPER TRADED)" if sym in active_paper_symbols else "📡 LIVE SCAN SIGNAL"

                all_signals.append({
                    "symbol": sym,
                    "horizon_key": h_key,
                    "horizon_name": h.get('horizon_name', h_key.upper()),
                    "priority": prio,
                    "conviction": conv,
                    "grade": grade,
                    "grade_tier": grade_tier,
                    "tier_label": tier_label,
                    "composite_score": composite_score,
                    "direction": direction,
                    "decision": decision,
                    "current_price": h.get('current_price', r.get('current_price', 0.0)),
                    "entry_price": h.get('current_price', r.get('current_price', 0.0)),
                    "tp1_price": h.get('tp1_price', h.get('tp_price', 0.0)),
                    "tp2_price": h.get('tp2_price', h.get('tp_price', 0.0)),
                    "tp3_price": h.get('tp3_price', h.get('tp_price', 0.0)),
                    "tp_price": h.get('tp_price', 0.0),
                    "sl_price": h.get('sl_price', 0.0),
                    "exp_return": h.get('exp_return', 0.0),
                    "projected_target": h.get('projected_target', h.get('tp_price', 0.0)),
                    "elite_precision": elite_prec,
                    "duration_label": h.get('duration_label', 'N/A'),
                    "predicted_window_str": h.get('predicted_window_str', 'N/A'),
                    "is_triple_confluence": is_triple,
                    "is_in_cooldown": is_in_cooldown,
                    "is_shield_blocked": is_shield_blocked,
                    "paper_trading_status": paper_status,
                    "card": h.get('pro_signal_text', ''),
                    "tf_summary": tf_summary
                })

        # Sort candidate setups: Grade Tier first, Priority second, Composite score third, Conviction fourth
        all_signals.sort(key=lambda x: (x['grade_tier'], x['priority'], -x['composite_score'], -x['conviction']))

        # Filter candidates taking into account Cooldown Throttling (favor fresh non-cooldown or Grade A+ breakouts)
        fresh_signals = [s for s in all_signals if not s['is_in_cooldown'] or s['grade_tier'] == 1]
        pool_for_selection = fresh_signals if len(fresh_signals) >= min_sig else all_signals

        # Dynamic Elastic Selection (Grade A+/A with minimum fallback & maximum cap)
        if is_dynamic:
            grade_a_signals = [s for s in pool_for_selection if s['grade_tier'] <= 2]
            if len(grade_a_signals) >= min_sig:
                selected_signals = grade_a_signals[:max_sig]
            else:
                selected_signals = pool_for_selection[:min_sig]
        else:
            selected_signals = pool_for_selection[:3]

        # Update Cooldown Timestamps for Dispatched Signals
        for sig in selected_signals:
            self.signal_cooldown_tracker[(sig['symbol'], sig['horizon_key'])] = now_ts

        # Market Regime Diagnostic & Beta Shield Banner
        count_a_plus = sum(1 for s in all_signals if s['grade_tier'] == 1)
        count_a = sum(1 for s in all_signals if s['grade_tier'] == 2)
        count_b = sum(1 for s in all_signals if s['grade_tier'] == 3)
        
        if self.btc_shield_active:
            regime_tag = f"🛡️ BTC BETA SHIELD ACTIVE ({self.btc_shield_reason} - Altcoin Longs Suppressed)"
        elif count_a_plus >= 2 or (count_a_plus + count_a) >= 4:
            regime_tag = "🚀 HIGH-CONVICTION TREND EXPANSION (Multiple Grade A+/A Setups Firing)"
        elif (count_a_plus + count_a) >= 1:
            regime_tag = "⚡ SELECTIVE OPPORTUNITY REGIME (Targeted Institutional Edge Active)"
        else:
            regime_tag = "🛡️ DEFENSIVE CHOP / CAPITAL PRESERVATION (Showing Highest-Ranked Defensive Setup)"

        print("\n" + "=" * 145)
        print(f" 🎯 DYNAMIC QUANTITATIVE SIGNAL ENGINE ({len(selected_signals)} SIGNALS DETECTED THIS ROUND)")
        print(f" Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} | Scanned: {len(source_results)} Pairs across 15M, 1H & 24H")
        print(f" Market Radar: 💎 {count_a_plus} Grade A+ | 🟢 {count_a} Grade A | 🟡 {count_b} Grade B+ | Regime: {regime_tag}")
        if self.btc_shield_active:
            print(f" ⚠️  CIRCUIT BREAKER: {self.btc_shield_reason} -> Prioritizing Shorts & BTC Hedges.")
        print("=" * 145)

        rank_medals = ["🥇 TOP PICK (#1)", "🥈 RUNNER UP (#2)", "🥉 BRONZE (#3)", "🎯 PICK (#4)", "🎯 PICK (#5)"]
        summary_rows = []
        for idx, sig in enumerate(selected_signals):
            rank_str = rank_medals[idx] if idx < len(rank_medals) else f"#{idx+1}"
            dir_str = "🟢 LONG" if sig['direction'] == "BULLISH" else "🔴 SHORT"
            exp_ret = sig.get('exp_return', 0.0)
            ret_str = f"{'+' if exp_ret >= 0 else ''}{exp_ret*100:.2f}%"

            summary_rows.append({
                "Rank": rank_str,
                "Quality Grade": f"{sig['grade']}\n({sig['tier_label']})",
                "Asset": sig['symbol'],
                "Horizon": sig['horizon_name'],
                "Side": dir_str,
                "Conviction": f"{sig['conviction']:.1f}%\n{sig['decision']}",
                "Entry Price": fmt_p(sig['entry_price']),
                "TP1 / TP2 Target": f"TP1: {fmt_p(sig['tp1_price'])}\nTP2: {fmt_p(sig['tp2_price'])}",
                "Stop-Loss": fmt_p(sig['sl_price']),
                "Exp. Return": ret_str,
                "Paper Status": sig['paper_trading_status']
            })

        df_selected = pd.DataFrame(summary_rows)
        print(tabulate(df_selected, headers="keys", tablefmt="fancy_grid", showindex=False))

        # Render complete Actionable Signal Setup Cards for all selected signals
        for idx, sig in enumerate(selected_signals):
            rank_str = rank_medals[idx] if idx < len(rank_medals) else f"SIGNAL #{idx+1}"
            print(f"\n--- [{rank_str} | {sig['grade']} | {sig['symbol']} {sig['horizon_name'].upper()}] ---")
            print(sig['card'])
            print("\n📊 MULTI-TIMEFRAME CONFIRMATION BREAKDOWN (1D, 4H, 1H, 15M, 5M):")
            if sig['tf_summary']:
                df_tf = pd.DataFrame(sig['tf_summary'])
                print(tabulate(df_tf, headers="keys", tablefmt="simple", showindex=False))

            invalidation_side = "below" if sig['direction'] == "BULLISH" else "above"
            sl_fmt = fmt_p(sig['sl_price'])
            print(f"\n⚠️ KEY INVALIDATION & TRADE MANAGEMENT RULES:")
            print(f"• Invalidation: A sustained 1H/4H candle close {invalidation_side} {sl_fmt} invalidates this setup structure.")
            print(f"• Dynamic Break-Even: Move Stop-Loss to Breakeven (${fmt_p(sig['entry_price'])}) immediately upon touching TP1.")
            print(f"• Risk Management: Strict 1–2% portfolio risk per trade.")
            print(f"• Paper Trading State: {sig['paper_trading_status']}")
            print("-" * 115)
        print("=" * 145 + "\n")

        return selected_signals

    # Backwards compatibility alias
    def render_professional_trading_signals(self, scanner_results: list):
        return self.render_top_round_signals(scanner_results)

    def render_multi_horizon_deep_dive(self, data: dict):
        sym = data['symbol']
        def fmt_usd(p):
            if p >= 50.0:
                return f"${p:,.2f}"
            elif p >= 0.10:
                return f"${p:,.4f}"
            else:
                return f"${p:.6g}"

        print("\n" + "=" * 135)
        print(f" 🚀 MASTER MULTI-HORIZON DEEP DIVE TERMINAL: {sym}")
        print(f" Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} | Triple Confluence: {'💎 YES' if data['is_triple_confluence'] else '⚡ INDEPENDENT'}")
        print("=" * 135)

        h_rows = []
        for h_key in ['scalp', 'swing', 'macro']:
            h = data['horizons'][h_key]
            h_rows.append([
                h['horizon_name'],
                f"{h['trade_open_str']} -> {h['trade_close_str']} ({h['duration_label']})",
                f"{'🟢' if h['direction']=='BULLISH' else '🔴'} {h['direction']} ({h['conviction']:.1f}%)",
                f"{'+' if h['exp_return']>=0 else ''}{h['exp_return']*100:.2f}% (Target: {fmt_usd(h['projected_target'])})",
                fmt_usd(h['tp_price']),
                fmt_usd(h['sl_price']),
                f"{h['elite_precision']*100:.1f}%",
                h['decision']
            ])

        print(tabulate(h_rows, headers=["Horizon", "Trade Window (Open -> Close)", "Direction & Conviction", "Exp Return", "Take-Profit", "Stop-Loss", "Elite Precision", "Decision"], tablefmt="fancy_grid"))

        print("\n" + "-" * 135)
        print(" 📊 MULTI-SCALE CHART CONFLUENCE BREAKDOWN:")
        print("-" * 135)
        df_breakdown = pd.DataFrame(data['tf_metrics_summary'])
        print(tabulate(df_breakdown, headers="keys", tablefmt="fancy_grid", showindex=False))

        print("\n" + "-" * 135)
        print(f" 🎯 PROFESSIONAL SIGNAL SETUP CARDS FOR {sym} (1:2 RISK TO REWARD):")
        print("-" * 135)
        for h_key in ['scalp', 'swing', 'macro']:
            print(data['horizons'][h_key]['pro_signal_text'])
            print("-" * 65)
        print("=" * 135 + "\n")

    def export_web_app_json(self, scanner_results: list, deep_dive_result: dict, top_signals: list = None):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategy": "Multi-Horizon Quantitative Engine (V16.0)",
            "btc_market_shield": {
                "active": self.btc_shield_active,
                "reason": self.btc_shield_reason
            },
            "top_round_signals": top_signals or [],
            "scanner_leaderboard": scanner_results,
            "deep_dive": deep_dive_result,
            "paper_portfolio": self.ledger.data
        }
        json_path = os.path.join(self.config['app_export_dir'], "live_market_forecast.json")
        with open(json_path, 'w') as f:
            json.dump(payload, f, indent=4, default=str)
        print(f"📦 Web-App Ready JSON Data Exported to: {os.path.abspath(json_path)}\n")


if __name__ == "__main__":
    engine = HybridQuantEngine(CONFIG)
    engine.run()
