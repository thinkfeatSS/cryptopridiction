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

import os
import sys

# Configure silent CPU & UTF-8 environment before heavy library imports
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

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
# Disable LightGBM in Linux container to eliminate OpenMP lib_lightgbm.so segfaults
HAS_LIGHTGBM = False
import threading
_LGBM_LOCK = threading.Lock()

try:
    from app.services.db_sync import sync_files_to_db_live
    HAS_DB_SYNC = True
except ImportError:
    HAS_DB_SYNC = False

from sklearn.preprocessing import RobustScaler
from sklearn.metrics import accuracy_score, roc_auc_score, mean_squared_error
from sklearn.model_selection import TimeSeriesSplit

warnings.filterwarnings("ignore")

import gc
import ctypes

def trim_process_memory():
    """
    OS Memory Guard: Forces Python cyclic garbage collection and invokes glibc malloc_trim
    on Linux/Docker environments to immediately return unmapped heap pages to the OS kernel.
    Safely no-ops on Windows.
    """
    gc.collect()
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except Exception:
        pass

print("[SYSTEM] Running in High-Performance CPU Mode.")

# ------------------------------------------------------------------------------
# 1. CONFIGURATION & MULTI-HORIZON PARAMETERS
# ------------------------------------------------------------------------------
CONFIG = {
    "mode": "both",               # "both", "scanner", or "single"
    "continuous_loop": True,      # 24/7 Background Watcher Loop
    "scanner_mode": "top_volume", # "top_volume" (dynamic auto-discovery of all active Binance coins), "expanded_universe", or "custom_list"
    "scanner_top_n": int(os.getenv("SCANNER_TOP_N", "200")), # Top 200 volume Binance coins (full market coverage)
    "max_scan_workers": int(os.getenv("MAX_SCAN_WORKERS", "8")), # Optimal 8 parallel worker threads (eliminates CPU contention & rate limits)
    "heartbeat_interval_seconds": int(os.getenv("HEARTBEAT_SECONDS", "4")), # Fast intra-candle position monitoring
    "history_limit_per_tf": {"15m": 250, "1h": 250, "4h": 250, "1d": 250}, # 250 candles per TF (1 fast REST fetch, zero pagination lag)
    "single_symbol": "BTC/USDT",
    "scanner_symbols": [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT", "ADA/USDT",
        "AVAX/USDT", "SUI/USDT", "LINK/USDT", "NEAR/USDT", "APT/USDT", "DOT/USDT", "PEPE/USDT",
        "SHIB/USDT", "TIA/USDT", "INJ/USDT", "RENDER/USDT", "FET/USDT", "OP/USDT", "ARB/USDT",
        "LTC/USDT", "UNI/USDT", "ICP/USDT", "FIL/USDT", "STX/USDT", "TAO/USDT", "SEI/USDT",
        "WIF/USDT", "BONK/USDT", "AAVE/USDT", "ATOM/USDT", "ETC/USDT", "KAS/USDT", "FTM/USDT",
        "WLD/USDT", "RUNE/USDT", "POL/USDT", "PYTH/USDT", "JUP/USDT", "BEAM/USDT", "ONDO/USDT",
        "FLOKI/USDT", "OM/USDT", "CORE/USDT", "GALA/USDT", "KAVA/USDT", "ALGO/USDT", "CHZ/USDT",
        "BLUR/USDT", "JASMY/USDT", "QNT/USDT", "DYDX/USDT", "IMX/USDT", "STG/USDT", "STRK/USDT",
        "GRT/USDT", "EOS/USDT", "FLOW/USDT", "ENA/USDT", "PENDLE/USDT", "CFX/USDT", "AXS/USDT",
        "MANA/USDT", "SAND/USDT", "CRV/USDT", "SNX/USDT", "DYM/USDT", "RON/USDT", "MKR/USDT",
        "COMP/USDT", "ZRO/USDT", "IO/USDT", "NOT/USDT", "TON/USDT", "MOVE/USDT", "ME/USDT",
        "VIRTUAL/USDT", "PENGU/USDT", "BOME/USDT", "MEW/USDT", "TURBO/USDT", "NEIRO/USDT",
        "BRETT/USDT", "1000SATS/USDT", "ORDI/USDT", "BIGTIME/USDT", "ETHFI/USDT", "EIGEN/USDT",
        "W/USDT", "SAFE/USDT", "ZK/USDT", "BANANA/USDT", "AKT/USDT", "ZETA/USDT", "BB/USDT",
        "LISTA/USDT", "VOXEL/USDT", "TRX/USDT", "BCH/USDT", "HBAR/USDT"
    ],
    "timeframes": ["1d", "4h", "1h", "15m"],
    # Multi-Horizon Definitions: 10 Horizons Spectrum + Radar Confluence
    "horizons": {
        "scalp": {
            "name": "⚡ Scalp (15M)",
            "anchor_tf": "15m",
            "bars": 1,
            "duration_label": "15 Mins",
            "tp_mult": 2.0,
            "sl_mult": 1.0
        },
        "horizon_30m": {
            "name": "⏱️ 30M",
            "anchor_tf": "15m",
            "bars": 2,
            "duration_label": "30 Mins",
            "tp_mult": 2.2,
            "sl_mult": 1.1
        },
        "swing": {
            "name": "🌊 Swing (1H)",
            "anchor_tf": "1h",
            "bars": 1,
            "duration_label": "1 Hour",
            "tp_mult": 2.5,
            "sl_mult": 1.2
        },
        "horizon_4h": {
            "name": "⏳ Intraday (4H)",
            "anchor_tf": "4h",
            "bars": 1,
            "duration_label": "4 Hours",
            "tp_mult": 2.8,
            "sl_mult": 1.4
        },
        "horizon_12h": {
            "name": "🌗 12H",
            "anchor_tf": "4h",
            "bars": 3,
            "duration_label": "12 Hours",
            "tp_mult": 2.9,
            "sl_mult": 1.45
        },
        "macro": {
            "name": "🚀 Macro (24H)",
            "anchor_tf": "1d",
            "bars": 1,
            "duration_label": "24 Hours",
            "tp_mult": 3.0,
            "sl_mult": 1.5
        },
        "horizon_4d": {
            "name": "📅 4D",
            "anchor_tf": "1d",
            "bars": 4,
            "duration_label": "4 Days",
            "tp_mult": 4.0,
            "sl_mult": 2.0
        },
        "weekly": {
            "name": "🗓️ Weekly (7D)",
            "anchor_tf": "1d",
            "bars": 7,
            "duration_label": "7 Days",
            "tp_mult": 5.0,
            "sl_mult": 2.5
        },
        "biweekly": {
            "name": "📆 15D",
            "anchor_tf": "1d",
            "bars": 15,
            "duration_label": "15 Days",
            "tp_mult": 6.5,
            "sl_mult": 3.25
        },
        "monthly": {
            "name": "🪐 Monthly (30D)",
            "anchor_tf": "1d",
            "bars": 30,
            "duration_label": "30 Days",
            "tp_mult": 8.0,
            "sl_mult": 4.0
        }
    },
    "history_limit_per_tf": {
        "1d": 250,
        "4h": 250,
        "1h": 250,
        "15m": 250
    },
    "paper_trading": {
        "enabled": True,
        "spot_only": False,                 # Allow both LONG and SHORT paper trades (Futures & Spot)
        "start_balance_usd": 100.0,         # $100.00 Virtual Wallet
        "position_size_usd": 10.0,          # Fixed $10.00 position size per trade
        "dynamic_sizing": False,            # Fixed $10.00 per trade (no over-leveraging)
        "min_position_size_usd": 10.0,
        "max_concurrent_positions": 10,     # Up to 10 active trades ($10.00 x 10 = $100.00 total capital)
        # Targeted Execution Horizons: Multi-horizon execution across all high-conviction timeframes
        "allowed_horizons": ["scalp", "horizon_30m", "swing", "horizon_4h", "horizon_12h", "macro", "horizon_2d", "horizon_3d", "weekly", "biweekly", "monthly"],
        "min_expected_return_pct": 0.40,    # Minimum expected return hurdle: >= 0.40% (clears round-trip Binance fees)
        "min_net_profit_usd": 0.04,         # Minimum $0.04 net profit target on $10.00 trades (0.40% of $10.00)
        "require_positive_track_record": False, # Do not block untested coins; 2-strike quarantine blocks toxic assets
        # Realistic Binance Trading Fee Engine (0.10% Buy Fee + 0.10% Sell Fee Standard, or 0.075% BNB discount)
        "execution_engine": "binance_spot", # "binance_spot" (100% real Binance fees) or "binance_convert"
        "binance_fee_rate": 0.0010,         # Standard Binance 0.10% Maker/Taker Fee
        "binance_buy_fee_rate": 0.0010,     # Explicit 0.10% Entry Fee
        "binance_sell_fee_rate": 0.0010,    # Explicit 0.10% Exit Fee
        "use_bnb_fee_discount": False,      # Set to True for 25% discount (0.075% fee)
        "slippage_rate": 0.0000,
        "convert_buy_spread_rate": 0.0010,  # Fallback for convert mode (+0.10% ask spread)
        "convert_sell_spread_rate": 0.0010  # Fallback for convert mode (-0.10% bid spread)
    },
    "signal_engine": {
        "dynamic_signal_count": True,       # Adaptive signal count based on true market edge
        "min_signals_per_round": 1,         # Always guarantee at least top 1 setup
        "max_signals_per_round": 5,         # Cap at 5 to avoid information overload
        "grade_a_plus_conviction": 0.75,    # 75%+ conviction + confluence -> Grade A+
        "grade_a_conviction": 0.65,         # 65%-74% conviction -> Grade A
        "grade_b_conviction": 0.55,         # 55%-64% conviction -> Grade B+
        "require_min_rr_ratio": 2.0,        # 1:2 Risk to Reward minimum
        "min_meta_probability": 0.65,       # Secondary ML meta-labeling win probability hurdle (>=65%)
        "ban_parabolic_shorts": True,       # Circuit breaker: Block SHORT if 24h pump > 12% or 1h RSI > 68
        "min_expected_return_pct": 0.40,    # Minimum expected return hurdle: >= 0.40% (guarantees net return after buy & sell fees)
        "min_scalp_gain_pct": 0.40,         # Minimum expected TP1 gain on 15M to clear taker fees (>= 0.40%)
        "min_swing_gain_pct": 0.75,         # Minimum expected TP1 gain on 1H
        "asset_cooldown_minutes": 60        # Deduping lockout window across horizons
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
        "max_depth": 3,
        "learning_rate": 0.05,
        "n_estimators": 25,
        "subsample": 0.85,
        "colsample_bytree": 0.80,
        "gamma": 0.15,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "random_state": 42,
        "n_jobs": 1
    },
    "lgb_clf": {
        "max_depth": 3,
        "num_leaves": 12,
        "learning_rate": 0.05,
        "n_estimators": 25,
        "subsample": 0.85,
        "colsample_bytree": 0.80,
        "random_state": 42,
        "verbose": -1,
        "n_jobs": 1
    },
    "extra_trees": {
        "n_estimators": 15,
        "max_depth": 4,
        "min_samples_split": 5,
        "random_state": 42,
        "n_jobs": 1
    },
    "xgb_reg": {
        "max_depth": 3,
        "learning_rate": 0.05,
        "n_estimators": 25,
        "subsample": 0.85,
        "colsample_bytree": 0.80,
        "objective": "reg:pseudohubererror",
        "random_state": 42,
        "n_jobs": 1
    },
    "catboost": {
        "iterations": 12,
        "depth": 3,
        "learning_rate": 0.05,
        "l2_leaf_reg": 4.0,
        "auto_class_weights": "Balanced",
        "verbose": False,
        "random_seed": 42,
        "thread_count": 1
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
        adapter = requests.adapters.HTTPAdapter(pool_connections=64, pool_maxsize=64, max_retries=2)
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        })
        self.is_binance_vision_direct = False
        self._live_tickers_cache = {}
        self._live_tickers_ts = 0.0
        self._funding_cache = {}
        self.init_resilient_exchange()

    def preload_bulk_funding_rates(self):
        """Pre-fetches all Binance pairs' funding rates in 1 single bulk call (~200ms)."""
        try:
            url = "https://fapi.binance.com/fapi/v1/premiumIndex"
            resp = self.session.get(url, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                for item in data:
                    sym = item.get('symbol')
                    if sym:
                        self._funding_cache[sym] = float(item.get('lastFundingRate', 0.0001))
                print(f"[DATA] Pre-cached {len(self._funding_cache)} Binance Futures funding rates in 1 bulk call.")
        except Exception:
            pass

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

    def _fetch_binance_vision_klines(self, symbol: str, timeframe: str, since: int = None, endTime: int = None, limit: int = 1000) -> list:
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
            if endTime is not None and endTime > 0:
                params["endTime"] = int(endTime)
            
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

        # 1. Primary Fetch: Backward Pagination Guarantee
        # We start by fetching the latest 1,000 candles up to the current second (endTime=None).
        # This guarantees that all_ohlcv always contains the live, in-progress candle.
        if self.is_binance_vision_direct or self.active_exchange_id == 'binance':
            current_end_time = None
            while len(all_ohlcv) < total_candles:
                req_limit = min(1000, total_candles - len(all_ohlcv) + 50)
                batch = self._fetch_binance_vision_klines(symbol, timeframe, since=None, endTime=current_end_time, limit=req_limit)
                if not batch and self.exchange:
                    try:
                        params = {'endTime': current_end_time} if current_end_time else {}
                        raw_ccxt = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=req_limit, params=params)
                        batch = [[c[0], c[1], c[2], c[3], c[4], c[5], c[5]*0.5] for c in raw_ccxt] if raw_ccxt else []
                    except Exception:
                        batch = []
                if not batch:
                    break
                all_ohlcv.extend(batch)
                oldest_in_batch = batch[0][0]
                if current_end_time is not None and oldest_in_batch >= current_end_time:
                    break
                current_end_time = int(oldest_in_batch - 1)
                if len(batch) < 10:
                    break
                time.sleep(0.03)
        else:
            # Multi-exchange resilient pagination: Get latest first, then paginate back
            limit_per_req = 1000
            if self.active_exchange_id == 'okx':
                limit_per_req = 100
            elif self.active_exchange_id == 'kraken':
                limit_per_req = 720
            elif self.active_exchange_id == 'kucoin':
                limit_per_req = 1500

            try:
                raw_recent = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=min(limit_per_req, total_candles))
                if raw_recent:
                    for c in raw_recent:
                        all_ohlcv.append([c[0], c[1], c[2], c[3], c[4], c[5], c[5]*0.5])
            except Exception:
                pass

            if len(all_ohlcv) < total_candles and all_ohlcv:
                oldest_ts = all_ohlcv[0][0]
                while len(all_ohlcv) < total_candles:
                    try:
                        since_ts = oldest_ts - (limit_per_req * step_ms)
                        batch = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=int(since_ts), limit=limit_per_req)
                        if not batch:
                            break
                        for c in batch:
                            all_ohlcv.append([c[0], c[1], c[2], c[3], c[4], c[5], c[5]*0.5])
                        first_ts = batch[0][0]
                        if first_ts >= oldest_ts:
                            break
                        oldest_ts = first_ts
                        time.sleep(self.exchange.rateLimit / 1000.0 if hasattr(self.exchange, 'rateLimit') else 0.05)
                    except Exception as e:
                        err_str = str(e).lower()
                        if "451" in err_str or "restricted" in err_str:
                            print(f"[FAILOVER] Restriction encountered during fetch. Re-routing...")
                            self.priority_exchanges = [ex for ex in self.priority_exchanges if ex != self.active_exchange_id]
                            self.init_resilient_exchange()
                            return self.fetch_ohlcv_extended(symbol, timeframe, total_candles)
                        break

        # Fallback to direct Binance Vision if still empty
        if not all_ohlcv:
            batch = self._fetch_binance_vision_klines(symbol, timeframe, since=None, limit=min(1000, total_candles))
            if batch:
                all_ohlcv.extend(batch)

        if not all_ohlcv:
            raise ValueError(f"No OHLCV records returned for {symbol} on {timeframe}")

        cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'taker_buy_vol']
        if len(all_ohlcv[0]) < 7:
            all_ohlcv = [row + [row[5]*0.5] for row in all_ohlcv]

        df = pd.DataFrame(all_ohlcv, columns=cols)
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
        
        for col in ['open', 'high', 'low', 'close', 'volume', 'taker_buy_vol']:
            df[col] = df[col].astype(np.float32)

        # Slice to requested total_candles (keeping the most recent candles)
        if len(df) > total_candles:
            df = df.iloc[-total_candles:].reset_index(drop=True)

        self._cache[cache_key] = df
        return df.copy()

    def fetch_funding_rate_and_oi(self, symbol: str) -> dict:
        """
        Fetches live 8h perpetual funding rate from pre-cached bulk dictionary.
        Zero latency (~0.001ms), non-blocking.
        """
        try:
            raw_sym = symbol.replace('/', '').replace(':USDT', '')
            if not raw_sym.endswith('USDT'):
                raw_sym += 'USDT'

            if hasattr(self, '_funding_cache') and raw_sym in self._funding_cache:
                fr_val = self._funding_cache[raw_sym]
            else:
                fr_val = 0.0001

            regime = "🔥 SHORT SQUEEZE" if fr_val <= -0.0002 else ("❄️ LONG SQUEEZE" if fr_val >= 0.0005 else "⚪ NEUTRAL")
            return {
                "funding_rate": fr_val,
                "open_interest": 0.0,
                "regime": regime
            }
        except Exception:
            return {"funding_rate": 0.0001, "open_interest": 0.0, "regime": "⚪ NEUTRAL"}

    def fetch_all_tickers(self, max_age_seconds: float = 3.0) -> dict:
        """
        Fetches real-time instantaneous prices for all Binance pairs in a single HTTP request (~150ms).
        Cached for max_age_seconds to prevent redundant network calls during concurrent scans.
        """
        now = time.time()
        if hasattr(self, '_live_tickers_cache') and self._live_tickers_cache and (now - getattr(self, '_live_tickers_ts', 0.0)) < max_age_seconds:
            return self._live_tickers_cache

        try:
            url = "https://data-api.binance.vision/api/v3/ticker/price"
            resp = self.session.get(url, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                price_dict = {}
                for item in data:
                    raw_s = item['symbol']
                    price_val = float(item['price'])
                    price_dict[raw_s] = price_val
                    if raw_s.endswith('USDT'):
                        base = raw_s[:-4]
                        price_dict[f"{base}/USDT"] = price_val
                self._live_tickers_cache = price_dict
                self._live_tickers_ts = now
                return price_dict
        except Exception:
            pass

        return getattr(self, '_live_tickers_cache', {})

    def get_live_price(self, symbol: str) -> float:
        """
        Gets instantaneous real-time spot price for a given symbol with fallback to fetch_ticker.
        """
        raw_sym = symbol.replace('/', '').replace(':USDT', '')
        tickers = self.fetch_all_tickers(max_age_seconds=4.0)
        if symbol in tickers:
            return float(tickers[symbol])
        if raw_sym in tickers:
            return float(tickers[raw_sym])
        
        try:
            t = self.fetch_ticker(symbol)
            if t and 'last' in t and float(t['last']) > 0:
                return float(t['last'])
        except Exception:
            pass
        return 0.0

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

    def fetch_orderbook_imbalance(self, symbol: str, limit: int = 5) -> float:
        """
        Fetches live top-5 orderbook depth levels and computes bid-ask liquidity imbalance ratio:
        imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume)
        Range: [-1.0 (Heavy Sell Wall), +1.0 (Heavy Buy Wall)]
        """
        try:
            if self.is_binance_vision_direct or self.active_exchange_id == 'binance':
                raw_sym = symbol.replace('/', '').replace(':USDT', '')
                url = f"https://data-api.binance.vision/api/v3/depth?symbol={raw_sym}&limit={limit}"
                resp = self.session.get(url, timeout=2)
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

    def fetch_top_volume_usdt_pairs(self, limit: int = 100) -> list:
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
            "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT", "ADA/USDT",
            "AVAX/USDT", "SUI/USDT", "LINK/USDT", "NEAR/USDT", "APT/USDT", "DOT/USDT", "PEPE/USDT",
            "SHIB/USDT", "TIA/USDT", "INJ/USDT", "RENDER/USDT", "FET/USDT", "OP/USDT", "ARB/USDT",
            "LTC/USDT", "UNI/USDT", "ICP/USDT", "FIL/USDT", "STX/USDT", "TAO/USDT", "SEI/USDT",
            "WIF/USDT", "BONK/USDT", "AAVE/USDT", "ATOM/USDT", "ETC/USDT", "KAS/USDT", "FTM/USDT",
            "WLD/USDT", "RUNE/USDT", "POL/USDT", "PYTH/USDT", "JUP/USDT", "BEAM/USDT", "ONDO/USDT",
            "FLOKI/USDT", "OM/USDT", "CORE/USDT", "GALA/USDT", "KAVA/USDT", "ALGO/USDT", "CHZ/USDT",
            "BLUR/USDT", "JASMY/USDT", "QNT/USDT", "DYDX/USDT", "IMX/USDT", "STG/USDT", "STRK/USDT",
            "GRT/USDT", "EOS/USDT", "FLOW/USDT", "ENA/USDT", "PENDLE/USDT", "CFX/USDT", "AXS/USDT",
            "MANA/USDT", "SAND/USDT", "CRV/USDT", "SNX/USDT", "DYM/USDT", "RON/USDT", "MKR/USDT",
            "COMP/USDT", "ZRO/USDT", "IO/USDT", "NOT/USDT", "TON/USDT", "MOVE/USDT", "ME/USDT",
            "VIRTUAL/USDT", "PENGU/USDT", "BOME/USDT", "MEW/USDT", "TURBO/USDT", "NEIRO/USDT",
            "BRETT/USDT", "1000SATS/USDT", "ORDI/USDT", "BIGTIME/USDT", "ETHFI/USDT", "EIGEN/USDT",
            "W/USDT", "SAFE/USDT", "ZK/USDT", "BANANA/USDT", "AKT/USDT", "ZETA/USDT", "BB/USDT",
            "LISTA/USDT", "VOXEL/USDT", "TRX/USDT", "BCH/USDT", "HBAR/USDT"
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
        w = np.array(w)
        vals = series.values
        if len(vals) < len(w):
            res_vals = np.zeros_like(vals)
        else:
            conv = np.convolve(vals, w, mode='valid')
            res_vals = np.zeros_like(vals)
            res_vals[len(w) - 1:] = conv
        res = pd.Series(res_vals, index=series.index)
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

    @staticmethod
    def compute_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        hist = macd_line - signal_line
        norm_factor = (series + 1e-10)
        norm_hist = hist / norm_factor
        hist_slope = (hist - hist.shift(1)) / norm_factor
        bull_cross = ((macd_line > signal_line) & (macd_line.shift(1) <= signal_line.shift(1))).astype(float)
        bear_cross = ((macd_line < signal_line) & (macd_line.shift(1) >= signal_line.shift(1))).astype(float)
        return norm_hist.fillna(0.0), hist_slope.fillna(0.0), bull_cross.fillna(0.0), bear_cross.fillna(0.0)

    @staticmethod
    def compute_rsi_divergences(df: pd.DataFrame, rsi: pd.Series, lookback: int = 14):
        low = df['low']
        high = df['high']
        prior_low_min = low.shift(1).rolling(lookback).min()
        prior_rsi_min = rsi.shift(1).rolling(lookback).min()
        prior_high_max = high.shift(1).rolling(lookback).max()
        prior_rsi_max = rsi.shift(1).rolling(lookback).max()
        
        # Bullish Divergence: Price creates new local low while RSI prints a higher low (oversold bounce setup)
        bull_div = ((low <= prior_low_min * 1.002) & (rsi > prior_rsi_min + 0.03) & (rsi < 0.45)).astype(float)
        # Bearish Divergence: Price creates new local high while RSI prints a lower high (overbought top setup)
        bear_div = ((high >= prior_high_max * 0.998) & (rsi < prior_rsi_max - 0.03) & (rsi > 0.55)).astype(float)
        return bull_div.fillna(0.0), bear_div.fillna(0.0)

    @staticmethod
    def compute_demark_td9(series: pd.Series):
        c = series.values
        n = len(c)
        buy_counts = np.zeros(n)
        sell_counts = np.zeros(n)
        curr_buy = 0
        curr_sell = 0
        for i in range(4, n):
            if c[i] < c[i-4]:
                curr_buy = min(9, curr_buy + 1)
                curr_sell = 0
            elif c[i] > c[i-4]:
                curr_sell = min(9, curr_sell + 1)
                curr_buy = 0
            else:
                curr_buy = 0
                curr_sell = 0
            buy_counts[i] = curr_buy
            sell_counts[i] = curr_sell
            
        buy_s = pd.Series(buy_counts, index=series.index)
        sell_s = pd.Series(sell_counts, index=series.index)
        buy_exhaustion = (buy_s >= 8).astype(float)
        sell_exhaustion = (sell_s >= 8).astype(float)
        return (buy_s / 9.0).fillna(0.0), (sell_s / 9.0).fillna(0.0), buy_exhaustion, sell_exhaustion

    @staticmethod
    def compute_candlestick_reversal_patterns(df: pd.DataFrame):
        o, h, l, c = df['open'], df['high'], df['low'], df['close']
        bar_range = (h - l).clip(lower=1e-10)
        upper_wick = h - np.maximum(c, o)
        lower_wick = np.minimum(c, o) - l
        
        # Hammer / Bullish Pin Bar
        is_hammer = ((lower_wick >= 0.55 * bar_range) & (upper_wick <= 0.20 * bar_range) & (c >= (l + 0.60 * bar_range))).astype(float)
        # Shooting Star / Bearish Pin Bar
        is_shooting_star = ((upper_wick >= 0.55 * bar_range) & (lower_wick <= 0.20 * bar_range) & (c <= (l + 0.40 * bar_range))).astype(float)
        
        # Bullish Engulfing
        prev_red = (c.shift(1) < o.shift(1))
        curr_green = (c > o)
        bull_engulf = (prev_red & curr_green & (c > o.shift(1)) & (o <= c.shift(1))).astype(float)
        
        # Bearish Engulfing
        prev_green = (c.shift(1) > o.shift(1))
        curr_red = (c < o)
        bear_engulf = (prev_green & curr_red & (c < o.shift(1)) & (o >= c.shift(1))).astype(float)
        
        bull_pattern = ((is_hammer > 0) | (bull_engulf > 0)).astype(float)
        bear_pattern = ((is_shooting_star > 0) | (bear_engulf > 0)).astype(float)
        return bull_pattern.fillna(0.0), bear_pattern.fillna(0.0)

    @staticmethod
    def compute_band_reversion_metrics(df: pd.DataFrame):
        c, h, l = df['close'], df['high'], df['low']
        sma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        upper_bb = sma20 + (2.0 * std20)
        lower_bb = sma20 - (2.0 * std20)
        
        # Spring: Low pierced lower band, close finished back inside bands
        bb_spring = ((l.shift(1) < lower_bb.shift(1)) & (c > lower_bb)).astype(float)
        # Upthrust: High pierced upper band, close finished back inside bands
        bb_upthrust = ((h.shift(1) > upper_bb.shift(1)) & (c < upper_bb)).astype(float)
        z_score_ema = ((c - sma20) / (std20 + 1e-10)).clip(-4.0, 4.0)
        return bb_spring.fillna(0.0), bb_upthrust.fillna(0.0), z_score_ema.fillna(0.0)

    @staticmethod
    def compute_volume_climax(df: pd.DataFrame):
        v = df['volume']
        c, o, h, l = df['close'], df['open'], df['high'], df['low']
        v_ma20 = v.rolling(20).mean()
        vol_surge = (v / (v_ma20 + 1e-10))
        bar_range = (h - l).clip(lower=1e-10)
        lower_wick = np.minimum(c, o) - l
        upper_wick = h - np.maximum(c, o)
        
        climax_bottom = ((vol_surge >= 1.8) & (lower_wick >= 0.35 * bar_range) & (c >= o)).astype(float)
        climax_top = ((vol_surge >= 1.8) & (upper_wick >= 0.35 * bar_range) & (c <= o)).astype(float)
        return vol_surge.clip(0.0, 10.0).fillna(1.0), climax_bottom.fillna(0.0), climax_top.fillna(0.0)

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

        # 4. TTM Squeeze & Bollinger Reversion Alpha
        raw_atr20 = self.compute_atr(data, period=20)
        sma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        upper_bb = sma20 + (2.0 * std20)
        lower_bb = sma20 - (2.0 * std20)
        upper_kc = sma20 + (1.5 * raw_atr20)
        lower_kc = sma20 - (1.5 * raw_atr20)
        feats[f'{prefix}_ttm_squeeze'] = ((lower_bb > lower_kc) & (upper_bb < upper_kc)).astype(float)
        feats[f'{prefix}_bb_pct_b'] = ((c - lower_bb) / ((upper_bb - lower_bb) + 1e-10)).clip(-0.5, 1.5)
        
        bb_spring, bb_upthrust, z_score_ema = self.compute_band_reversion_metrics(data)
        feats[f'{prefix}_bb_spring'] = bb_spring
        feats[f'{prefix}_bb_upthrust'] = bb_upthrust
        feats[f'{prefix}_zscore_ema20'] = z_score_ema

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

        # 7. Momentum & Oscillators
        feats[f'{prefix}_mfi_14'] = self.compute_mfi(data, period=14)
        rsi_series = self.compute_rsi(c, period=14)
        feats[f'{prefix}_rsi_14'] = rsi_series
        stoch_k, stoch_d = self.compute_stoch_rsi(c, period=14)
        feats[f'{prefix}_stoch_rsi_k'] = stoch_k
        feats[f'{prefix}_stoch_rsi_diff'] = stoch_k - stoch_d

        # 8. MACD Reversal & Divergences
        norm_hist, hist_slope, macd_bull_cross, macd_bear_cross = self.compute_macd(c)
        feats[f'{prefix}_macd_norm_hist'] = norm_hist
        feats[f'{prefix}_macd_hist_slope'] = hist_slope
        feats[f'{prefix}_macd_bull_cross'] = macd_bull_cross
        feats[f'{prefix}_macd_bear_cross'] = macd_bear_cross

        # 9. Regular RSI Divergences (Bottom Bounces & Top Pullbacks)
        rsi_bull_div, rsi_bear_div = self.compute_rsi_divergences(data, rsi_series, lookback=14)
        feats[f'{prefix}_rsi_bull_div'] = rsi_bull_div
        feats[f'{prefix}_rsi_bear_div'] = rsi_bear_div

        # 10. DeMark Sequential TD-9 Trend Exhaustion
        td_buy_norm, td_sell_norm, td9_buy_ex, td9_sell_ex = self.compute_demark_td9(c)
        feats[f'{prefix}_td_buy_count'] = td_buy_norm
        feats[f'{prefix}_td_sell_count'] = td_sell_norm
        feats[f'{prefix}_td9_buy_exhaustion'] = td9_buy_ex
        feats[f'{prefix}_td9_sell_exhaustion'] = td9_sell_ex

        # 11. Candlestick Price Action Reversal Formations
        candlestick_bull_rev, candlestick_bear_rev = self.compute_candlestick_reversal_patterns(data)
        feats[f'{prefix}_candlestick_bull_reversal'] = candlestick_bull_rev
        feats[f'{prefix}_candlestick_bear_reversal'] = candlestick_bear_rev

        # 12. Volume Climax & Absorption
        vol_surge, climax_bot, climax_top = self.compute_volume_climax(data)
        feats[f'{prefix}_vol_surge_ratio'] = vol_surge
        feats[f'{prefix}_vol_climax_bottom'] = climax_bot
        feats[f'{prefix}_vol_climax_top'] = climax_top

        # 13. Fractional Memory & Multi-Lag Returns
        feats[f'{prefix}_frac_diff'] = self.get_fractional_diff(c, d=0.35)
        for lag in [1, 3]:
            feats[f'{prefix}_ret_{lag}'] = np.log(c / c.shift(lag).clip(lower=1e-10)).fillna(0.0)

        # 14. Cumulative Volume Delta (CVD) & Market Aggression (Taker Buy Ratio)
        if 'taker_buy_vol' in data.columns:
            tb_vol = data['taker_buy_vol']
            taker_ratio = (tb_vol / (v + 1e-10)).clip(0.0, 1.0)
            net_delta = (2.0 * tb_vol - v)
            cvd_roll = net_delta.rolling(14).sum() / (v.rolling(14).sum() + 1e-10)
            feats[f'{prefix}_taker_buy_ratio'] = taker_ratio.fillna(0.5)
            feats[f'{prefix}_cvd_norm'] = cvd_roll.clip(-1.0, 1.0).fillna(0.0)
            feats[f'{prefix}_cvd_accel'] = (feats[f'{prefix}_cvd_norm'] - feats[f'{prefix}_cvd_norm'].shift(3)).fillna(0.0)
        else:
            feats[f'{prefix}_taker_buy_ratio'] = 0.50
            feats[f'{prefix}_cvd_norm'] = 0.0
            feats[f'{prefix}_cvd_accel'] = 0.0

        # 15. Smart Money Concepts: Liquidity Sweep & Wall Proximity
        roll_high_24 = h.rolling(24).max()
        roll_low_24 = l.rolling(24).min()
        bull_sweep = ((l < roll_low_24.shift(1)) & (c > roll_low_24.shift(1)) & (lower_wick >= 0.28 * bar_range)).astype(float)
        bear_sweep = ((h > roll_high_24.shift(1)) & (c < roll_high_24.shift(1)) & (upper_wick >= 0.28 * bar_range)).astype(float)
        feats[f'{prefix}_liquidity_sweep_bull'] = bull_sweep.fillna(0.0)
        feats[f'{prefix}_liquidity_sweep_bear'] = bear_sweep.fillna(0.0)
        feats[f'{prefix}_headroom_to_high24'] = ((roll_high_24 - c) / (c + 1e-10)).clip(lower=0.0)
        feats[f'{prefix}_headroom_to_low24'] = ((c - roll_low_24) / (c + 1e-10)).clip(lower=0.0)

        # 16. Multi-Timeframe EMA Alignment Cohesion Vector
        ema_bull_stack = ((ema9 > ema21) & (ema21 > ema50) & (ema50 > ema200)).astype(float)
        ema_bear_stack = ((ema9 < ema21) & (ema21 < ema50) & (ema50 < ema200)).astype(float)
        feats[f'{prefix}_ema_stack_cohesion'] = (ema_bull_stack - ema_bear_stack).fillna(0.0)

        # 17. Quantitative Composite Reversal Scores (0.0 to 1.0)
        rsi_oversold_factor = (0.50 - rsi_series).clip(lower=0.0) * 2.0
        rsi_overbought_factor = (rsi_series - 0.50).clip(lower=0.0) * 2.0

        bull_rev_score = (
            0.25 * rsi_bull_div +
            0.20 * rsi_oversold_factor +
            0.15 * (hist_slope > 0).astype(float) +
            0.15 * td9_buy_ex +
            0.15 * candlestick_bull_rev +
            0.15 * bb_spring +
            0.10 * climax_bot +
            0.10 * bull_sweep
        ).clip(0.0, 1.0)

        bear_rev_score = (
            0.25 * rsi_bear_div +
            0.20 * rsi_overbought_factor +
            0.15 * (hist_slope < 0).astype(float) +
            0.15 * td9_sell_ex +
            0.15 * candlestick_bear_rev +
            0.15 * bb_upthrust +
            0.10 * climax_top +
            0.10 * bear_sweep
        ).clip(0.0, 1.0)

        feats[f'{prefix}_bull_reversal_score'] = bull_rev_score.fillna(0.0)
        feats[f'{prefix}_bear_reversal_score'] = bear_rev_score.fillna(0.0)

        feats = feats.ffill().bfill()
        float_cols = feats.select_dtypes(include=['float64']).columns
        if len(float_cols) > 0:
            feats[float_cols] = feats[float_cols].astype(np.float32)
        return feats

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

        df = df.ffill().bfill()
        float_cols = df.select_dtypes(include=['float64']).columns
        if len(float_cols) > 0:
            df[float_cols] = df[float_cols].astype(np.float32)
        return df

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
            
            # Adaptive Triple-Barrier Target Labeling with 0.85% minimum gain hurdle (Ensures high net profitability)
            min_gain_hurdle = 0.0085 # 0.85% minimum return required to ensure robust profit after exchange fees
            if primary_signal == 1:
                fav_excursion = max(0.0, window_high - curr_c)
                adv_excursion = max(0.0, curr_c - window_low)
                hit_pt = window_high >= pt_price
                hit_sl = window_low <= sl_price
                excursion_score[i] = (fav_excursion + 1e-10) / (adv_excursion + 1e-10)
                meta_label[i] = 1 if (hit_pt and not hit_sl) or (exp_ret >= min_gain_hurdle and fav_excursion >= (adv_excursion * 1.5)) else 0
            else:
                fav_excursion = max(0.0, curr_c - window_low)
                adv_excursion = max(0.0, window_high - curr_c)
                hit_pt = window_low <= pt_short
                hit_sl = window_high >= sl_short
                excursion_score[i] = (fav_excursion + 1e-10) / (adv_excursion + 1e-10)
                meta_label[i] = 1 if (hit_pt and not hit_sl) or (exp_ret <= -min_gain_hurdle and fav_excursion >= (adv_excursion * 1.5)) else 0

        data['Target_Primary'] = primary_direction.astype(np.float32)
        data['Target_Meta'] = meta_label.astype(np.float32)
        data['Target_Return'] = forward_return.astype(np.float32)
        data['Excursion_Score'] = excursion_score.astype(np.float32)
        
        invalid_len = horizon_bars + 1
        data.iloc[-invalid_len:, data.columns.get_loc('Target_Primary')] = np.nan
        data.iloc[-invalid_len:, data.columns.get_loc('Target_Meta')] = np.nan
        data.iloc[-invalid_len:, data.columns.get_loc('Target_Return')] = np.nan
        data.iloc[-invalid_len:, data.columns.get_loc('Excursion_Score')] = np.nan
        
        return data

# ------------------------------------------------------------------------------
# 5. SUPER LEARNER MODEL FACTORY (CatBoost, XGBoost, ExtraTrees)
# ------------------------------------------------------------------------------
class QuantModelFactory:

    @staticmethod
    def build_primary_catboost(cfg: dict) -> CatBoostClassifier:
        return CatBoostClassifier(
            iterations=cfg['iterations'],
            depth=cfg['depth'],
            learning_rate=cfg['learning_rate'],
            l2_leaf_reg=cfg['l2_leaf_reg'],
            auto_class_weights=cfg.get('auto_class_weights', None),
            verbose=False,
            random_seed=42,
            thread_count=cfg.get('thread_count', 1)
        )

    @staticmethod
    def build_primary_xgboost(cfg: dict) -> xgb.XGBClassifier:
        return xgb.XGBClassifier(
            n_estimators=cfg['n_estimators'],
            max_depth=cfg['max_depth'],
            learning_rate=cfg['learning_rate'],
            subsample=cfg['subsample'],
            colsample_bytree=cfg['colsample_bytree'],
            gamma=cfg['gamma'],
            random_state=cfg['random_state'],
            n_jobs=cfg.get('n_jobs', 1),
            tree_method='hist',
            eval_metric='logloss'
        )

    @staticmethod
    def build_primary_lightgbm(cfg: dict):
        if HAS_LIGHTGBM:
            return lgb.LGBMClassifier(
                n_estimators=cfg['n_estimators'],
                max_depth=cfg['max_depth'],
                num_leaves=cfg['num_leaves'],
                learning_rate=cfg['learning_rate'],
                subsample=cfg['subsample'],
                colsample_bytree=cfg['colsample_bytree'],
                random_state=cfg['random_state'],
                verbose=cfg['verbose'],
                n_jobs=cfg.get('n_jobs', 1)
            )
        return None

    @staticmethod
    def build_primary_extra_trees(cfg: dict) -> ExtraTreesClassifier:
        return ExtraTreesClassifier(
            n_estimators=cfg['n_estimators'],
            max_depth=cfg['max_depth'],
            min_samples_split=cfg['min_samples_split'],
            random_state=cfg['random_state'],
            n_jobs=cfg.get('n_jobs', 1)
        )

    @staticmethod
    def build_xgb_regressor(cfg: dict) -> xgb.XGBRegressor:
        return xgb.XGBRegressor(
            n_estimators=cfg['n_estimators'],
            max_depth=cfg['max_depth'],
            learning_rate=cfg['learning_rate'],
            subsample=cfg['subsample'],
            colsample_bytree=cfg['colsample_bytree'],
            objective=cfg['objective'],
            random_state=cfg['random_state'],
            n_jobs=cfg.get('n_jobs', 1),
            tree_method='hist'
        )

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
        self.execution_engine = self.config.get('execution_engine', 'binance_spot')
        self.convert_buy_spread_rate = float(self.config.get('convert_buy_spread_rate', 0.0010))
        self.convert_sell_spread_rate = float(self.config.get('convert_sell_spread_rate', 0.0010))
        self.allowed_horizons = set(self.config.get('allowed_horizons', [
            "scalp", "horizon_30m", "swing", "horizon_4h", "horizon_12h", "macro", "horizon_2d", "horizon_3d", "weekly", "biweekly", "monthly"
        ]))
        self.min_expected_return_pct = float(self.config.get('min_expected_return_pct', 0.40))
        self.min_net_profit_usd = float(self.config.get('min_net_profit_usd', 0.04))

        self.base_fee_rate = float(self.config.get('binance_fee_rate', 0.0010))
        self.use_bnb_discount = self.config.get('use_bnb_fee_discount', False)
        self.slippage_rate = float(self.config.get('slippage_rate', 0.0))

        raw_discount = 0.75 if self.use_bnb_discount else 1.0
        self.buy_fee_rate = float(self.config.get('binance_buy_fee_rate', self.base_fee_rate)) * raw_discount + self.slippage_rate
        self.sell_fee_rate = float(self.config.get('binance_sell_fee_rate', self.base_fee_rate)) * raw_discount + self.slippage_rate

        if self.execution_engine == 'binance_convert':
            self.effective_fee_rate = 0.0
            self.fee_tier_label = f"Binance Convert (Zero Fee | +{self.convert_buy_spread_rate*100:.2f}% Buy / -{self.convert_sell_spread_rate*100:.2f}% Sell Spread)"
        else:
            self.effective_fee_rate = (self.base_fee_rate * raw_discount) + self.slippage_rate
            discount_str = "0.075% BNB Discount" if self.use_bnb_discount else "0.10% Standard"
            self.fee_tier_label = f"Binance Spot ({discount_str} | {self.buy_fee_rate*100:.2f}% Buy + {self.sell_fee_rate*100:.2f}% Sell)"

        self.cooldown_tracker = {}  # {symbol: datetime_of_last_breakeven_or_loss}
        self.data = self.load_or_initialize()

    def load_or_initialize(self) -> dict:
        target_start = float(self.config.get('start_balance_usd', 100.0))
        if os.path.exists(self.ledger_file):
            try:
                with open(self.ledger_file, 'r') as f:
                    d = json.load(f)
                    # If starting capital was updated in CONFIG (e.g. to $15.00), reset cleanly
                    if d.get('starting_balance_usd') != target_start:
                        d['starting_balance_usd'] = target_start
                        d['current_balance_usd'] = target_start
                        d['realized_pnl_usd'] = 0.0
                        d['gross_profit_usd'] = 0.0
                        d['gross_loss_usd'] = 0.0
                        d['total_fees_paid_usd'] = 0.0
                        d['gross_realized_pnl_usd'] = 0.0
                        d['peak_balance_usd'] = target_start
                        d['total_trades'] = 0
                        d['winning_trades'] = 0
                        d['losing_trades'] = 0
                        d['breakeven_trades'] = 0
                        d['win_rate_pct'] = 0.0
                        d['profit_factor'] = 0.0
                        d['max_drawdown_usd'] = 0.0
                        d['max_drawdown_pct'] = 0.0
                        d['open_positions'] = []
                        d['closed_trades_history'] = []

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
                        "fee_tier_label": self.fee_tier_label,
                        "queued_trades": []
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
            "closed_trades_history": [],
            "queued_trades": []
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
            entry_p = float(pos.get('entry_price', curr_p))
            tp1_p = float(pos.get('tp1_price', pos.get('tp_price', entry_p)))
            tp2_p = float(pos.get('tp2_price', pos.get('tp_price', entry_p)))
            tp3_p = float(pos.get('tp3_price', pos.get('tp_price', entry_p)))
            tp_p = float(pos.get('tp_price', entry_p))
            sl_p = float(pos.get('sl_price', entry_p))
            
            init_size = float(pos.get('initial_position_size_usd', pos.get('position_size_usd', 0.0)))
            rem_size = float(pos.get('remaining_position_size_usd', init_size))
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
            h_name = pos.get('horizon', 'horizon_4h')
            if h_name == 'scalp':
                min_dur_secs = 10 * 60
            elif h_name == 'swing':
                min_dur_secs = 60 * 60
            elif h_name == 'horizon_4h':
                min_dur_secs = 2 * 3600
            elif h_name == 'macro':
                min_dur_secs = 12 * 3600
            elif h_name == 'horizon_2d':
                min_dur_secs = 24 * 3600
            elif h_name == 'horizon_3d':
                min_dur_secs = 36 * 3600
            elif h_name == 'weekly':
                min_dur_secs = 3 * 86400
            elif h_name == 'biweekly':
                min_dur_secs = 7 * 86400
            elif h_name == 'monthly':
                min_dur_secs = 14 * 86400
            else:
                min_dur_secs = 2 * 3600
            is_expired = (now_dt >= expiry_dt) and (dur_secs >= min_dur_secs)

            # 1. PARTIAL TP1 SCALE (50% locked + Trail SL to Breakeven)
            if is_hit_tp1 and stage == 'OPEN':
                scale_size = round(rem_size * 0.50, 2)
                rem_size = round(rem_size - scale_size, 2)
                
                # Calculate True Binance Fees & Convert Execution for TP1 Exit Leg
                if self.execution_engine == 'binance_convert':
                    eff_tp1_exit = round(tp1_p * (1.0 - self.convert_sell_spread_rate), 8)
                    gross_tp1_gain = scale_size * ((eff_tp1_exit - entry_p) / entry_p)
                    exit_fee = 0.0
                else:
                    gross_tp1_gain = scale_size * (abs(tp1_p - entry_p) / entry_p)
                    exit_nominal = scale_size + gross_tp1_gain
                    exit_fee = round(exit_nominal * self.sell_fee_rate, 4)
                net_tp1_realized = round(gross_tp1_gain - exit_fee, 4)

                pos['realized_gross_pnl'] = round(pos.get('realized_gross_pnl', 0.0) + gross_tp1_gain, 4)
                pos['realized_fees'] = round(pos.get('realized_fees', 0.0) + exit_fee, 4)
                pos['realized_net_pnl'] = round(pos.get('realized_net_pnl', 0.0) + net_tp1_realized, 4)
                pos['remaining_position_size_usd'] = rem_size
                pos['stage'] = 'TP1_LOCKED_BREAKEVEN'
                pos['sl_price'] = entry_p  # Trail SL to strict breakeven entry
                sl_p = entry_p

            # 2. PARTIAL TP2 SCALE (30% locked + Dynamic ATR Chandelier Trail on 20% Runner)
            if is_hit_tp2 and stage == 'TP1_LOCKED_BREAKEVEN':
                scale_size = round(init_size * 0.30, 2)
                rem_size = round(rem_size - scale_size, 2)

                if self.execution_engine == 'binance_convert':
                    eff_tp2_exit = round(tp2_p * (1.0 - self.convert_sell_spread_rate), 8)
                    gross_tp2_gain = scale_size * ((eff_tp2_exit - entry_p) / entry_p)
                    exit_fee = 0.0
                else:
                    gross_tp2_gain = scale_size * (abs(tp2_p - entry_p) / entry_p)
                    exit_nominal = scale_size + gross_tp2_gain
                    exit_fee = round(exit_nominal * self.sell_fee_rate, 4)
                net_tp2_realized = round(gross_tp2_gain - exit_fee, 4)

                pos['realized_gross_pnl'] = round(pos.get('realized_gross_pnl', 0.0) + gross_tp2_gain, 4)
                pos['realized_fees'] = round(pos.get('realized_fees', 0.0) + exit_fee, 4)
                pos['realized_net_pnl'] = round(pos.get('realized_net_pnl', 0.0) + net_tp2_realized, 4)
                pos['remaining_position_size_usd'] = rem_size
                pos['stage'] = 'TP2_LOCKED_TRAIL'
                pos['sl_price'] = tp1_p  # Lock SL at guaranteed TP1 profit floor
                sl_p = tp1_p

            # Final Position Exit Condition
            is_final_exit = is_hit_sl or is_expired or (stage == 'TP2_LOCKED_TRAIL' and is_hit_tp2)

            if is_final_exit:
                raw_exit_p = sl_p if is_hit_sl else (tp2_p if (stage == 'TP2_LOCKED_TRAIL' and is_hit_tp2) else curr_p)
                
                # Calculate return on remaining allocated size with Convert markdown if applicable
                if self.execution_engine == 'binance_convert':
                    exit_p = round(raw_exit_p * (1.0 - self.convert_sell_spread_rate), 8)
                    raw_rem_return = (exit_p - entry_p) / entry_p if direction == "BULLISH" else (entry_p - exit_p) / entry_p
                    gross_rem_pnl = rem_size * raw_rem_return
                    exit_rem_fee = 0.0
                else:
                    exit_p = raw_exit_p
                    raw_rem_return = (exit_p - entry_p) / entry_p if direction == "BULLISH" else (entry_p - exit_p) / entry_p
                    gross_rem_pnl = rem_size * raw_rem_return
                    exit_rem_nominal = max(0.0, rem_size + gross_rem_pnl)
                    exit_rem_fee = round(exit_rem_nominal * self.sell_fee_rate, 4)
                net_rem_realized = gross_rem_pnl - exit_rem_fee

                # Total Combined Trade Accounting
                total_gross_pnl = round(pos.get('realized_gross_pnl', 0.0) + gross_rem_pnl, 4)
                buy_fee_usd = round(pos.get('buy_fee_usd', pos.get('entry_fee_usd', 0.0)), 4)
                sell_fee_usd = round(pos.get('realized_fees', 0.0) + exit_rem_fee, 4)
                total_fees_paid = round(buy_fee_usd + sell_fee_usd, 4)
                total_net_realized_pnl = round(total_gross_pnl - total_fees_paid, 4)
                net_pnl_pct = round((total_net_realized_pnl / init_size) * 100.0, 2)
                gross_pnl_pct = round((total_gross_pnl / init_size) * 100.0, 2)

                # Determine final outcome classification
                if total_net_realized_pnl > 0.0001:
                    outcome = "WON"
                elif total_net_realized_pnl < -0.0001:
                    outcome = "LOST"
                else:
                    outcome = "BREAKEVEN"

                # Exit reason string
                if is_hit_sl:
                    exit_reason = "TRAILING_SL_HIT" if stage != 'OPEN' else "STOP_LOSS_HIT"
                elif stage == 'TP2_LOCKED_TRAIL' and is_hit_tp2:
                    exit_reason = "TAKE_PROFIT_TP2_HIT"
                else:
                    exit_reason = f"HORIZON_EXPIRY ({duration_str})"

                # Cooldown activation if stopped out or breakeven
                if outcome in ["LOST", "BREAKEVEN"]:
                    self.cooldown_tracker[sym] = now_dt

                # Update Ledger Master Capital & Analytics
                self.data['current_balance_usd'] = round(self.data['current_balance_usd'] + total_net_realized_pnl, 2)
                self.data['realized_pnl_usd'] = round(self.data['realized_pnl_usd'] + total_net_realized_pnl, 2)
                self.data['gross_realized_pnl_usd'] = round(self.data['gross_realized_pnl_usd'] + total_gross_pnl, 2)
                self.data['total_fees_paid_usd'] = round(self.data['total_fees_paid_usd'] + total_fees_paid, 2)
                
                if total_gross_pnl > 0:
                    self.data['gross_profit_usd'] = round(self.data['gross_profit_usd'] + total_gross_pnl, 2)
                else:
                    self.data['gross_loss_usd'] = round(self.data['gross_loss_usd'] + abs(total_gross_pnl), 2)

                self.data['total_trades'] += 1
                if outcome == "WON":
                    self.data['winning_trades'] += 1
                elif outcome == "LOST":
                    self.data['losing_trades'] += 1
                else:
                    self.data['breakeven_trades'] = self.data.get('breakeven_trades', 0) + 1

                decisive_trades = self.data['winning_trades'] + self.data['losing_trades']
                self.data['win_rate_pct'] = round((self.data['winning_trades'] / max(1, decisive_trades)) * 100.0, 2) if decisive_trades > 0 else 0.0
                self.data['profit_factor'] = round(self.data['gross_profit_usd'] / max(0.01, self.data['gross_loss_usd']), 2)

                # Drawdown tracking
                self.data['peak_balance_usd'] = max(self.data.get('peak_balance_usd', self.data['starting_balance_usd']), self.data['current_balance_usd'])
                current_dd = round(self.data['peak_balance_usd'] - self.data['current_balance_usd'], 2)
                current_dd_pct = round((current_dd / self.data['peak_balance_usd']) * 100.0, 2)
                self.data['max_drawdown_usd'] = max(self.data.get('max_drawdown_usd', 0.0), current_dd)
                self.data['max_drawdown_pct'] = max(self.data.get('max_drawdown_pct', 0.0), current_dd_pct)

                pos['exit_price'] = exit_p
                pos['exit_reason'] = exit_reason
                pos['outcome'] = outcome
                pos['gross_pnl_usd'] = total_gross_pnl
                pos['gross_pnl_pct'] = gross_pnl_pct
                pos['buy_fee_usd'] = buy_fee_usd
                pos['sell_fee_usd'] = sell_fee_usd
                pos['binance_fee_usd'] = total_fees_paid
                pos['realized_pnl_usd'] = total_net_realized_pnl
                pos['realized_pnl_pct'] = net_pnl_pct
                pos['closed_at'] = now_str
                pos['exit_time_str'] = now_dt.strftime('%Y-%m-%d %H:%M:%S UTC')
                pos['duration_str'] = duration_str
                
                self.data['closed_trades_history'].append(pos)
                closed_this_tick.append(pos)
            else:
                # Update Open Position with Real-Time Estimated Exit Fees & Net PnL
                if self.execution_engine == 'binance_convert':
                    eff_curr_exit = round(curr_p * (1.0 - self.convert_sell_spread_rate), 8)
                    raw_ret = (eff_curr_exit - entry_p) / entry_p if direction == "BULLISH" else (entry_p - eff_curr_exit) / entry_p
                    est_exit_fee = 0.0
                    buy_fee_usd = 0.0
                    est_total_fee = 0.0
                    pos['convert_sell_rate'] = eff_curr_exit
                else:
                    raw_ret = (curr_p - entry_p) / entry_p if direction == "BULLISH" else (entry_p - curr_p) / entry_p
                    est_exit_nominal = max(0.0, rem_size * (1.0 + raw_ret))
                    est_exit_fee = round(est_exit_nominal * self.sell_fee_rate, 4)
                    buy_fee_usd = round(pos.get('buy_fee_usd', pos.get('entry_fee_usd', rem_size * self.buy_fee_rate)), 4)
                    est_total_fee = round(buy_fee_usd + est_exit_fee, 4)

                gross_u_pnl = round(raw_ret * rem_size, 4)
                net_u_pnl = round(gross_u_pnl - est_total_fee, 4)
                
                # Calculate Live Target Progress %:
                # If in profit (curr_p >= entry_p): percentage of (tp_p - entry_p) achieved [0 to +100%]
                # If in loss (curr_p < entry_p): percentage of (entry_p - sl_p) consumed towards SL [0 to -100%]
                if direction == "BULLISH":
                    if curr_p >= entry_p:
                        tp_span = max(1e-8, tp_p - entry_p)
                        target_prog = round(min(100.0, max(0.0, (curr_p - entry_p) / tp_span * 100.0)), 2)
                    else:
                        sl_span = max(1e-8, entry_p - sl_p)
                        target_prog = -round(min(100.0, max(0.0, (entry_p - curr_p) / sl_span * 100.0)), 2)
                else:
                    if curr_p <= entry_p:
                        tp_span = max(1e-8, entry_p - tp_p)
                        target_prog = round(min(100.0, max(0.0, (entry_p - curr_p) / tp_span * 100.0)), 2)
                    else:
                        sl_span = max(1e-8, sl_p - entry_p)
                        target_prog = -round(min(100.0, max(0.0, (curr_p - entry_p) / sl_span * 100.0)), 2)

                pos['unrealized_gross_pnl_usd'] = gross_u_pnl
                pos['buy_fee_usd'] = buy_fee_usd
                pos['est_sell_fee_usd'] = est_exit_fee
                pos['unrealized_fee_usd'] = est_total_fee
                pos['unrealized_pnl_usd'] = net_u_pnl
                pos['unrealized_pnl_pct'] = round((net_u_pnl / init_size) * 100.0, 2)
                pos['target_progress_pct'] = target_prog
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

    def consider_new_trade(self, result: dict, horizon_key: str, signal_history: list = None):
        if not self.config.get('enabled', True):
            return

        # 0. Targeted Execution Horizons Guard: Only execute trades on allowed horizons
        if horizon_key not in self.allowed_horizons:
            return

        decision = result.get('decision', '')
        if "FILTER" in decision or "PAUSED" in decision or "QUARANTINED" in decision:
            return

        is_executable = any(k in decision for k in ["EXECUTE", "DIP-BUY", "RALLY-SELL", "BREAKDOWN", "REVERSAL", "SWEEP"])
        if not is_executable:
            return

        sym = result['symbol']
        direction = result.get('direction', 'BULLISH')
        is_short = direction in ["BEARISH", "SHORT"]
        
        # 1. Spot Only Guard: If spot_only is True, skip SHORT / BEARISH trades
        if self.config.get('spot_only', False) and is_short:
            return

        entry_p = float(result.get('current_price', 0.0) or 0.0)
        tp_p = float(result.get('tp_price', 0.0) or 0.0)
        tp1_p = float(result.get('tp1_price', tp_p) or tp_p)
        tp2_p = float(result.get('tp2_price', tp_p) or tp_p)
        tp3_p = float(result.get('tp3_price', tp_p) or tp_p)
        sl_p = float(result.get('sl_price', 0.0) or 0.0)

        if entry_p <= 0 or tp1_p <= 0 or sl_p <= 0:
            return

        # Directional Invariant Guard: Prevent inverted targets from ever opening a position
        if not is_short and (tp_p <= entry_p or sl_p >= entry_p):
            return
        if is_short and (tp_p >= entry_p or sl_p <= entry_p):
            return

        # 2. Cooldown Guard on Choppy/Breakeven Coins (45 min cooldown)
        now_utc = datetime.now(timezone.utc)
        last_closed = self.cooldown_tracker.get(sym)
        if last_closed:
            elapsed_cd = (now_utc - last_closed).total_seconds()
            if elapsed_cd < 2700:  # 45 minutes cooldown
                return

        # 3. Strict Single-Asset Lockout: Maximum 1 position per asset across ALL horizons
        for pos in self.data.get('open_positions', []):
            if pos['symbol'] == sym:
                return

        # 4. Fixed Position Size: $10.00 per trade ($100 total capital / 10 trades)
        pos_size = float(self.config.get('position_size_usd', 10.0))

        # 5. Net Profit Hurdle: Must beat round-trip Binance trading fees
        if self.execution_engine == 'binance_convert':
            if is_short:
                eff_entry = round(entry_p * (1.0 - self.convert_sell_spread_rate), 8)
                eff_tp1_exit = round(tp1_p * (1.0 + self.convert_buy_spread_rate), 8)
                expected_net_gain_pct = (eff_entry - eff_tp1_exit) / eff_entry
            else:
                eff_entry = round(entry_p * (1.0 + self.convert_buy_spread_rate), 8)
                eff_tp1_exit = round(tp1_p * (1.0 - self.convert_sell_spread_rate), 8)
                expected_net_gain_pct = (eff_tp1_exit - eff_entry) / eff_entry
            est_net_profit_usd = round(pos_size * expected_net_gain_pct, 4)
            fill_entry_p = eff_entry
        else:
            eff_entry = entry_p
            fill_entry_p = entry_p
            expected_gain_pct = abs(entry_p - tp1_p) / entry_p
            est_nominal_fees = round((pos_size * self.buy_fee_rate) + (pos_size * (1.0 + expected_gain_pct) * self.sell_fee_rate), 4)
            est_net_profit_usd = (pos_size * expected_gain_pct) - est_nominal_fees
            expected_net_gain_pct = est_net_profit_usd / pos_size

        if (expected_net_gain_pct * 100.0) < self.min_expected_return_pct or est_net_profit_usd < self.min_net_profit_usd:
            return  # Skip trade: Expected net profit after fees is below hurdle

        # 6. Track Record & Quarantine Check: Block assets with proven negative alpha (2+ consecutive losses)
        past_won = 0
        past_lost = 0
        if signal_history:
            coin_signals = [s for s in signal_history if s.get('symbol') == sym]
            past_won = sum(1 for s in coin_signals if "WON" in str(s.get('outcome_label', '')).upper())
            past_lost = sum(1 for s in coin_signals if "LOST" in str(s.get('outcome_label', '')).upper())
            
            # Block asset if it has recorded 2+ stop-outs and negative win/loss track record
            if past_lost >= 2 and past_lost > past_won:
                return

        # Check Active Queue Capacity & Liquid Cash
        max_concurrent = int(self.config.get('max_concurrent_positions', 10))
        total_open_collateral = sum(p.get('remaining_position_size_usd', p.get('position_size_usd', 10.0)) for p in self.data.get('open_positions', []))
        avail_cash = max(0.0, self.data['current_balance_usd'] - total_open_collateral)
        queue_is_full = (len(self.data.get('open_positions', [])) >= max_concurrent) or (avail_cash < pos_size)

        if queue_is_full:
            # 7. Qualified Waitlist: Trade meets 100% of criteria, but active queue is currently full (10/10)
            queued_list = self.data.setdefault('queued_trades', [])
            if not any(q['symbol'] == sym for q in queued_list):
                queued_list.append({
                    "trade_id": f"QUEUED_{sym.replace('/', '_')}_{horizon_key}_{int(time.time())}",
                    "symbol": sym,
                    "horizon": horizon_key,
                    "direction": "SHORT" if is_short else "LONG",
                    "execution_engine": self.execution_engine,
                    "entry_price": fill_entry_p,
                    "raw_entry_price": entry_p,
                    "tp_price": tp_p,
                    "tp1_price": tp1_p,
                    "tp2_price": tp2_p,
                    "tp3_price": tp3_p,
                    "sl_price": sl_p,
                    "position_size_usd": pos_size,
                    "est_net_profit_usd": round(est_net_profit_usd, 2),
                    "est_net_gain_pct": round(expected_net_gain_pct * 100.0, 2),
                    "past_won": past_won,
                    "past_lost": past_lost,
                    "win_ratio_label": f"{past_won}W / {past_lost}L",
                    "signal_decision": decision,
                    "status": "QUALIFIED_WAITLIST",
                    "status_reason": f"Queue Full ({len(self.data.get('open_positions', []))}/{max_concurrent} active) - Next In Line",
                    "queued_at": now_utc.isoformat(),
                    "predicted_window": result.get('predicted_window_str', f"{result.get('trade_open_str', 'N/A')} ➔ {result.get('trade_close_str', 'N/A')}")
                })
            self.save()
            return

        # Calculate full duration from actual fill timestamp
        tf_delta_map = {
            'scalp': timedelta(minutes=15),
            'horizon_30m': timedelta(minutes=30),
            'swing': timedelta(hours=2),
            'horizon_4h': timedelta(hours=4),
            'horizon_12h': timedelta(hours=12),
            'macro': timedelta(hours=24),
            'horizon_2d': timedelta(days=2),
            'horizon_3d': timedelta(days=3),
            'weekly': timedelta(days=7),
            'biweekly': timedelta(days=15),
            'monthly': timedelta(days=30)
        }
        duration = tf_delta_map.get(horizon_key, timedelta(hours=4))
        expiry_dt = now_utc + duration

        if self.execution_engine == 'binance_convert':
            buy_fee = 0.0
            est_sell_fee = 0.0
            spread_cost_entry = round(pos_size * (self.convert_sell_spread_rate if is_short else self.convert_buy_spread_rate), 4)
            unrealized_fee = 0.0
            unrealized_pnl = -round(spread_cost_entry, 4)
            unrealized_pct = -round((spread_cost_entry / pos_size) * 100.0, 2)
        else:
            buy_fee = round(pos_size * self.buy_fee_rate, 4)
            est_sell_fee = round(pos_size * self.sell_fee_rate, 4)
            unrealized_fee = round(buy_fee + est_sell_fee, 4)
            unrealized_pnl = -unrealized_fee
            unrealized_pct = round((-unrealized_fee / pos_size) * 100.0, 2)

        # Initial target progress percentage is 0.0% at entry
        target_prog = 0.0

        new_pos = {
            "trade_id": f"PAPER_{sym.replace('/', '_')}_{horizon_key}_{int(time.time())}",
            "symbol": sym,
            "horizon": horizon_key,
            "direction": "BEARISH" if is_short else "BULLISH",
            "direction_label": "SHORT" if is_short else "LONG",
            "execution_engine": self.execution_engine,
            "entry_price": fill_entry_p,
            "raw_entry_price": entry_p,
            "tp_price": tp_p,
            "tp1_price": tp1_p,
            "tp2_price": tp2_p,
            "tp3_price": tp3_p,
            "sl_price": sl_p,
            "initial_position_size_usd": pos_size,
            "remaining_position_size_usd": pos_size,
            "position_size_usd": pos_size,
            "allocated_usd": pos_size,
            "stage": "OPEN",
            "realized_gross_pnl": 0.0,
            "realized_fees": 0.0,
            "realized_net_pnl": 0.0,
            "entry_fee_usd": buy_fee,
            "buy_fee_usd": buy_fee,
            "est_sell_fee_usd": est_sell_fee,
            "sell_fee_usd": 0.0,
            "fee_rate": self.effective_fee_rate,
            "buy_fee_rate": self.buy_fee_rate,
            "sell_fee_rate": self.sell_fee_rate,
            "opened_at": now_utc.isoformat(),
            "entry_time_str": now_utc.strftime('%Y-%m-%d %H:%M:%S UTC'),
            "predicted_window": result.get('predicted_window_str', f"{result.get('trade_open_str', 'N/A')} ➔ {result.get('trade_close_str', 'N/A')}"),
            "expiry_time": expiry_dt.isoformat(),
            "signal_decision": decision,
            "unrealized_gross_pnl_usd": 0.0,
            "unrealized_fee_usd": unrealized_fee,
            "unrealized_pnl_usd": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pct,
            "target_progress_pct": target_prog,
            "current_price": entry_p
        }

        self.data.setdefault('open_positions', []).append(new_pos)
        self.save()

    def save(self):
        with open(self.ledger_file, 'w') as f:
            json.dump(self.data, f, indent=4, default=str)

    def on_tick(self, live_prices: dict, live_highs: dict = None, live_lows: dict = None):
        """Processes real-time price updates, stepped risk ratchets, partial TP scaling, and trailing stops."""
        return self.update_positions(live_prices, live_highs, live_lows)

    def admit_ranked_candidates(self, ranked_candidates: list, signal_history: list = None):
        """Admits candidate trades strictly in order of global priority and relative strength rank."""
        self.data['queued_trades'] = []
        for cand, h_key in ranked_candidates:
            self.consider_new_trade(cand, h_key, signal_history=signal_history)

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

        print(f"[PORTFOLIO 💼] Balance: ${d['current_balance_usd']:,.2f} | Net Realized PnL: {pnl_sign}${d['realized_pnl_usd']:,.2f} ({tot_ret_pct:+.2f}%) | Active Positions: {len(d['open_positions'])} | Win Rate: {d['win_rate_pct']:.1f}%")

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

    def is_asset_quarantined(self, symbol: str, lookback_hours: float = 24.0, cooldown_hours: float = 12.0) -> tuple:
        """
        2-Strike Asset Blacklist Quarantine Engine:
        If an asset recorded >= 2 stop losses within past 24 hours,
        quarantines it for 12 hours after the latest stop loss to eliminate whipsaw chop bleeding.
        """
        now_utc = datetime.now(timezone.utc)
        recent_losses = []
        for r in self.records:
            if r.get('symbol') != symbol:
                continue
            status = str(r.get('status', '')).upper()
            outcome = str(r.get('outcome_label', '')).upper()
            if status == "LOST_SL" or "LOST (SL" in outcome or "STOPPED" in outcome:
                eval_str = str(r.get('evaluated_at_utc', '')).replace(' UTC', '').strip()
                loss_dt = None
                try:
                    if eval_str:
                        loss_dt = datetime.strptime(eval_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                    else:
                        date_u = str(r.get('date_utc', ''))
                        time_u = str(r.get('time_utc', '')).replace(' UTC', '').strip()
                        if date_u and time_u:
                            loss_dt = datetime.strptime(f"{date_u} {time_u}", '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                except Exception:
                    pass
                if loss_dt:
                    age_hours = (now_utc - loss_dt).total_seconds() / 3600.0
                    if age_hours <= lookback_hours:
                        recent_losses.append(loss_dt)

        if len(recent_losses) >= 2:
            latest_loss = max(recent_losses)
            hours_since_last = (now_utc - latest_loss).total_seconds() / 3600.0
            if hours_since_last < cooldown_hours:
                rem_hours = round(cooldown_hours - hours_since_last, 1)
                return True, f"QUARANTINED (2 SLs in 24h - cooldown active for {rem_hours}h)"

        return False, ""

    def build_kpi_summary(self) -> dict:
        total_signals = len(self.records)
        won = sum(1 for r in self.records if "WON" in str(r.get('outcome_label', '')) or "BREAKEVEN" in str(r.get('outcome_label', '')))
        lost = sum(1 for r in self.records if "LOST" in str(r.get('outcome_label', '')) and "BREAKEVEN" not in str(r.get('outcome_label', '')))
        expired = sum(1 for r in self.records if "EXPIRED" in str(r.get('outcome_label', '')))
        pending = sum(1 for r in self.records if r.get('status') in ["PENDING_EVALUATION", "ACTIVE", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"])
        decisive = won + lost
        win_rate = round((won / max(1, decisive)) * 100.0, 2) if decisive > 0 else 0.0

        # Grade A+ specific stats
        a_plus_recs = [r for r in self.records if "A+" in str(r.get('quality_grade', ''))]
        a_plus_won = sum(1 for r in a_plus_recs if "WON" in str(r.get('outcome_label', '')) or "BREAKEVEN" in str(r.get('outcome_label', '')))
        a_plus_lost = sum(1 for r in a_plus_recs if "LOST" in str(r.get('outcome_label', '')) and "BREAKEVEN" not in str(r.get('outcome_label', '')))
        a_plus_wr = round((a_plus_won / max(1, a_plus_won + a_plus_lost)) * 100.0, 2) if (a_plus_won + a_plus_lost) > 0 else 0.0

        # Grade A specific stats
        a_recs = [r for r in self.records if "Grade A (" in str(r.get('quality_grade', '')) or "Grade A\n" in str(r.get('quality_grade', ''))]
        a_won = sum(1 for r in a_recs if "WON" in str(r.get('outcome_label', '')) or "BREAKEVEN" in str(r.get('outcome_label', '')))
        a_lost = sum(1 for r in a_recs if "LOST" in str(r.get('outcome_label', '')) and "BREAKEVEN" not in str(r.get('outcome_label', '')))
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
                "meta_win_prob_pct": round(float(sig.get('meta_win_prob', 0.70)) * 100.0, 1),
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
                "predicted_close_utc": sig.get('predicted_close_utc') or sig.get('trade_close_str') or 'N/A',
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

        # Auto-fetch bulk ticker prices if any pending signals are not covered by live_prices
        live_prices = dict(live_prices or {})
        pending_missing_syms = {
            r['symbol'] for r in self.records
            if r.get('status') in ["PENDING_EVALUATION", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL"]
            and r.get('symbol') not in live_prices
        }
        if pending_missing_syms:
            try:
                resp = requests.get("https://data-api.binance.vision/api/v3/ticker/price", timeout=4)
                if resp.status_code == 200:
                    for item in resp.json():
                        raw_s = item['symbol']
                        p_val = float(item['price'])
                        live_prices[raw_s] = p_val
                        if raw_s.endswith('USDT'):
                            live_prices[f"{raw_s[:-4]}/USDT"] = p_val
            except Exception:
                pass

        for r in self.records:
            status = r.get('status', 'PENDING_EVALUATION')
            if status not in ["PENDING_EVALUATION", "ACTIVE", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"]:
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
            is_tier0_locked = bool(r.get('is_tier0_locked', False) or status == 'TIER0_PROTECTED_BREAKEVEN')

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
            pred_close_str = str(r.get('predicted_close_utc', '')).strip()
            # Resilient fallback: parse predicted close from predicted_window (e.g. "... ➔ 2026-09-09 19:15 UTC (15 Mins)")
            if not pred_close_str or pred_close_str == 'N/A':
                pred_win = str(r.get('predicted_window', ''))
                if '➔' in pred_win:
                    after_arrow = pred_win.split('➔')[-1].strip()
                    if '(' in after_arrow:
                        pred_close_str = after_arrow.split('(')[0].strip()
                    else:
                        pred_close_str = after_arrow.strip()

            try:
                if pred_close_str and pred_close_str != 'N/A':
                    clean_dt_str = pred_close_str.replace(' UTC', '').strip()
                    close_dt = datetime.fromisoformat(clean_dt_str) if 'T' in clean_dt_str else datetime.strptime(clean_dt_str, '%Y-%m-%d %H:%M')
                    if close_dt.tzinfo is None:
                        close_dt = close_dt.replace(tzinfo=timezone.utc)
                    if now_utc >= close_dt:
                        is_expired = True
                        if r.get('predicted_close_utc') in ('', 'N/A', None):
                            r['predicted_close_utc'] = pred_close_str
            except Exception:
                pass

            # Resilient Zombie Expiry Guard: If still not expired, evaluate against created timestamp + duration
            if not is_expired:
                try:
                    sig_id = str(r.get('signal_id', ''))
                    date_u = str(r.get('date_utc', '')).strip()
                    time_u = str(r.get('time_utc', '')).replace(' UTC', '').strip()
                    h_name = str(r.get('horizon', '15M')).upper()
                    h_tag = resolve_horizon_tag(h_name)
                    dur_sec = HORIZON_EXPIRY_SECONDS.get(h_tag, 3600)
                    created_dt = None
                    if date_u and time_u:
                        created_dt = datetime.strptime(f"{date_u} {time_u}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    elif 'SIG_' in sig_id:
                        parts = sig_id.split('_')
                        if len(parts) >= 3 and len(parts[1]) == 8 and len(parts[2]) == 4:
                            dt_str = f"{parts[1]}_{parts[2]}"
                            created_dt = datetime.strptime(dt_str, "%Y%m%d_%H%M").replace(tzinfo=timezone.utc)
                    if created_dt and (now_utc - created_dt).total_seconds() >= dur_sec:
                        is_expired = True
                        r['predicted_close_utc'] = (created_dt + timedelta(seconds=dur_sec)).strftime('%Y-%m-%d %H:%M:%S UTC')
                except Exception:
                    pass

            # 0. Tier-0 Early Breakeven Guard (+0.50% gain raises SL to Soft BE)
            if max_gain >= 0.50 and not is_tp1_locked and not is_tier0_locked and not is_hit_sl:
                r['is_tier0_locked'] = True
                r['status'] = "TIER0_PROTECTED_BREAKEVEN"
                soft_be_p = (entry_p * 1.001) if direction == "LONG" else (entry_p * 0.999)
                r['sl_price'] = round(max(sl_p, soft_be_p) if direction == "LONG" else min(sl_p, soft_be_p), 6)
                sl_p = r['sl_price']
                r['outcome_label'] = "🛡️ TIER-0 PROTECTED (SOFT BE)"
                is_tier0_locked = True
                updated = True

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

            # 4. Stop Loss Triggered (Either Original SL or Trailed BE / Tier-0 Stop)
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
                elif is_tier0_locked:
                    # Tier-0 Protected Breakeven Stop hit (saved trade from full -3% loss)
                    ret_be = ((sl_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - sl_p) / entry_p) * 100.0
                    r['status'] = "WON_TIER0_BE"
                    r['exit_price'] = round(sl_p, 6)
                    r['realized_return_pct'] = f"{ret_be:+.2f}%"
                    r['outcome_label'] = f"🛡️ BREAKEVEN (TIER-0 GUARD {ret_be:+.2f}%)"
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
                elif is_tier0_locked:
                    r['status'] = "WON_TIER0_BE"
                    r['exit_price'] = round(curr_p, 6)
                    r['realized_return_pct'] = f"{ret_current:+.2f}%"
                    r['outcome_label'] = f"🛡️ EXPIRED (TIER-0 BE {ret_current:+.2f}%)"
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

        print(f"[AUDIT LEDGER 📊] Tracked Signals: {kpi['total_trader_signals']} | Won: {kpi['won_signals_count']} | Lost: {kpi['lost_signals_count']} | Win Rate: {kpi['win_rate_pct']:.1f}% | Return: {sign}{kpi['cumulative_return_pct']:.2f}%")

# ------------------------------------------------------------------------------
# 7.4 PERSISTENT INSTITUTIONAL ACTIVE SIGNAL LIFECYCLE MANAGER
# ------------------------------------------------------------------------------
HORIZON_TAG_MAP = {
    'scalp': '15M',
    'horizon_30m': '30M',
    'swing': '1H',
    'horizon_4h': '4H',
    'horizon_12h': '12H',
    'macro': '24H',
    'horizon_4d': '4D',
    'weekly': '7D',
    'biweekly': '15D',
    'monthly': '30D',
}

HORIZON_EXPIRY_SECONDS = {
    '15M': 900,
    '30M': 1800,
    '1H': 3600,
    '4H': 14400,
    '12H': 43200,
    '24H': 86400,
    '4D': 345600,
    '7D': 604800,
    '15D': 1296000,
    '30D': 2592000,
}

def resolve_horizon_tag(h_key: str) -> str:
    hk = str(h_key or "").lower().strip()
    if hk in HORIZON_TAG_MAP:
        return HORIZON_TAG_MAP[hk]
    if 'scalp' in hk or '15m' in hk: return '15M'
    if '30m' in hk: return '30M'
    if 'swing' in hk or '1h' in hk: return '1H'
    if '4h' in hk or 'intraday' in hk: return '4H'
    if '12h' in hk: return '12H'
    if 'macro' in hk or '24h' in hk or '1d' in hk: return '24H'
    if '4d' in hk: return '4D'
    if 'weekly' in hk or '7d' in hk: return '7D'
    if 'biweekly' in hk or '15d' in hk: return '15D'
    if 'monthly' in hk or '30d' in hk: return '30D'
    return '15M'

class ActiveInstitutionalSignalManager:
    """
    Persistent Institutional Signal Lifecycle Registry:
    - Maintains exactly ONE active signal per (symbol, horizon).
    - Preserves signals across multiple 15-minute scans until they WIN (TP hit), LOSE (SL hit), or EXPIRE.
    - If a subsequent scan evaluates the same coin & horizon (e.g. entry shifted from 2.2 to 2.5),
      updates the existing signal in-place rather than creating duplicates.
    - Performs high-frequency evaluation on live prices during both scans and fast 15s heartbeats.
    - Persists state to active_institutional_signals.json.
    """
    def __init__(self, export_dir: str = "./export_app_data", audit_tracker=None):
        self.export_dir = export_dir
        self.audit_tracker = audit_tracker
        self.filepath = os.path.join(self.export_dir, "active_institutional_signals.json")
        self.active_signals = {}  # key: f"{symbol}:{horizon_tag}" -> dict
        self.load_state()

    def _clean_sym(self, sym: str) -> str:
        if not sym:
            return ""
        s = str(sym).strip().upper().replace(':USDT', '')
        if '/' not in s and s.endswith('USDT'):
            s = s[:-4] + '/USDT'
        return s

    def _make_key(self, sym: str, h_key: str) -> str:
        clean_s = self._clean_sym(sym)
        h_tag = resolve_horizon_tag(h_key)
        return f"{clean_s}:{h_tag.upper()}"

    def load_state(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        sym = item.get('symbol', '')
                        h_k = item.get('horizon_key', item.get('horizon_tag', 'scalp'))
                        if sym and h_k:
                            key = self._make_key(sym, h_k)
                            self.active_signals[key] = item
                elif isinstance(data, dict):
                    self.active_signals = data
            except Exception as e:
                print(f"[ACTIVE SIGNAL MGR] Error loading state: {e}")

    def save_state(self):
        try:
            os.makedirs(self.export_dir, exist_ok=True)
            temp = self.filepath + ".tmp"
            with open(temp, 'w', encoding='utf-8') as f:
                json.dump(list(self.active_signals.values()), f, indent=2, default=str)
            os.replace(temp, self.filepath)
        except Exception as e:
            print(f"[ACTIVE SIGNAL MGR] Error saving state: {e}")

    def get_active_symbols(self) -> list:
        syms = set()
        for s in self.active_signals.values():
            if s.get('status') in ["ACTIVE", "PENDING_EVALUATION", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"]:
                sym = s.get('symbol')
                if sym:
                    syms.add(sym)
        return list(syms)

    def is_asset_quarantined(self, symbol: str) -> tuple:
        if self.audit_tracker:
            return self.audit_tracker.is_asset_quarantined(symbol)
        return False, ""

    def upsert_signals(self, candidate_signals: list) -> list:
        """
        Upserts candidate signals:
        - If (symbol, horizon) is already active, updates the coin's data in place (entry price, TP/SL, conviction).
        - If new, registers it into the active pool.
        """
        now_utc = datetime.now(timezone.utc)
        now_str = now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')

        for cand in candidate_signals:
            sym = cand.get('symbol')
            h_k = cand.get('horizon_key', 'scalp')
            h_tag = resolve_horizon_tag(h_k)
            key = self._make_key(sym, h_tag)

            existing = self.active_signals.get(key)
            is_active = existing and existing.get('status') in [
                "ACTIVE", "PENDING_EVALUATION", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"
            ]

            if is_active:
                # 1. Update existing signal in-place
                old_entry = float(existing.get('entry_price', 0.0))
                new_entry = float(cand.get('entry_price', old_entry))

                # Check if entry shifted significantly (>0.05%)
                if old_entry > 0 and abs(new_entry - old_entry) / old_entry >= 0.0005:
                    existing['was_price_updated'] = True
                    existing['previous_entry_price'] = round(old_entry, 6)

                existing['entry_price'] = round(new_entry, 6)
                existing['current_price'] = round(float(cand.get('current_price', new_entry)), 6)
                existing['tp1_price'] = round(float(cand.get('tp1_price', existing.get('tp1_price'))), 6)
                existing['tp2_price'] = round(float(cand.get('tp2_price', existing.get('tp2_price'))), 6)
                existing['tp3_price'] = round(float(cand.get('tp3_price', existing.get('tp3_price'))), 6)

                # Maintain locked breakeven if already locked
                if not existing.get('is_tp1_locked') and not existing.get('is_tier0_locked'):
                    existing['sl_price'] = round(float(cand.get('sl_price', existing.get('sl_price'))), 6)

                existing['conviction'] = float(cand.get('conviction', existing.get('conviction', 50.0)))
                existing['conviction_pct'] = existing['conviction']
                existing['meta_win_prob'] = float(cand.get('meta_win_prob', existing.get('meta_win_prob', 0.70)))
                existing['meta_win_prob_pct'] = round(existing['meta_win_prob'] * 100.0, 1)
                existing['exp_return'] = float(cand.get('exp_return', existing.get('exp_return', 0.0)))
                existing['expected_return_pct'] = round(existing['exp_return'] * 100.0, 2)
                existing['decision'] = cand.get('decision', existing.get('decision'))
                existing['updated_at_utc'] = now_str
                existing['horizon_tag'] = h_tag

                # Update in audit tracker if matching ID found
                if self.audit_tracker:
                    for rec in self.audit_tracker.records:
                        if rec.get('signal_id') == existing.get('signal_id'):
                            rec['entry_price'] = existing['entry_price']
                            rec['tp1_price'] = existing['tp1_price']
                            rec['tp2_price'] = existing['tp2_price']
                            rec['tp3_price'] = existing['tp3_price']
                            if not rec.get('is_tp1_locked') and not rec.get('is_tier0_locked'):
                                rec['sl_price'] = existing['sl_price']
                            rec['conviction_pct'] = existing['conviction_pct']
                            rec['meta_win_prob_pct'] = existing['meta_win_prob_pct']
                            rec['expected_return_pct'] = existing['expected_return_pct']
                            rec['decision'] = existing['decision']
                            break
            else:
                # 2. Register as a fresh active signal
                sig_copy = dict(cand)
                sig_id = f"SIG_{now_utc.strftime('%Y%m%d_%H%M')}_{sym.replace('/', '_')}_{h_tag}"
                sig_copy['signal_id'] = sig_id
                sig_copy['horizon_tag'] = h_tag
                sig_copy['status'] = "ACTIVE"
                sig_copy['outcome_label'] = "ACTIVE 🟢"
                sig_copy['is_tp1_locked'] = False
                sig_copy['is_tp2_locked'] = False
                sig_copy['is_tier0_locked'] = False
                sig_copy['was_price_updated'] = False
                sig_copy['created_at_utc'] = now_str
                sig_copy['updated_at_utc'] = now_str
                sig_copy['created_ts'] = time.time()
                sig_copy['live_pnl_pct'] = 0.0

                # Ensure predicted expiration is robustly set
                pred_close = sig_copy.get('predicted_close_utc')
                if not pred_close or pred_close == 'N/A':
                    dur_sec = HORIZON_EXPIRY_SECONDS.get(h_tag, 3600)
                    sig_copy['predicted_close_utc'] = (now_utc + timedelta(seconds=dur_sec)).strftime('%Y-%m-%d %H:%M:%S UTC')

                self.active_signals[key] = sig_copy

                if self.audit_tracker:
                    self.audit_tracker.log_top_trader_signals([sig_copy])

        self.save_state()
        return self.get_display_signals()

    def evaluate_signals(self, live_prices: dict, live_highs: dict = None, live_lows: dict = None) -> bool:
        """
        Evaluates active signals in real time against live prices:
        - TP1 / TP2 / TP3 hits -> WIN
        - Stop Loss hits -> LOSS
        - Expiration time reached -> EXPIRE
        Returns True if any signal state or price updated.
        """
        if not self.active_signals:
            return False

        now_utc = datetime.now(timezone.utc)
        now_ts = time.time()
        now_str = now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')
        updated = False

        # 1. Clean up resolved signals past grace period (2 hours = 7200s)
        keys_to_delete = []
        for key, s in self.active_signals.items():
            status = s.get('status', 'ACTIVE')
            if status in ["WON_TP3", "WON_TP2_TRAIL", "WON_TP1_BE", "WON_TIER0_BE", "LOST_SL", "EXPIRED"]:
                resolved_ts = s.get('resolved_at_ts', 0.0)
                if resolved_ts > 0 and (now_ts - resolved_ts) > 7200.0:
                    keys_to_delete.append(key)
        for k in keys_to_delete:
            self.active_signals.pop(k, None)
            updated = True

        # 2. Evaluate active signals
        for key, s in self.active_signals.items():
            status = s.get('status', 'ACTIVE')
            if status not in ["ACTIVE", "PENDING_EVALUATION", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"]:
                continue

            sym = s.get('symbol')
            raw_sym = sym.replace('/', '').replace(':USDT', '') if sym else ''
            curr_p = live_prices.get(sym) or live_prices.get(raw_sym)
            if not curr_p or curr_p <= 0:
                continue

            entry_p = float(s.get('entry_price', curr_p))
            direction = str(s.get('direction', 'LONG')).upper()
            is_long = direction in ["LONG", "BULLISH"]

            # Real-time live PnL calculation
            pnl_pct = ((curr_p - entry_p) / entry_p) * 100.0 if is_long else ((entry_p - curr_p) / entry_p) * 100.0
            s['live_pnl_pct'] = round(pnl_pct, 2)
            s['current_price'] = curr_p
            s['live_price'] = curr_p

            raw_h = live_highs.get(sym, curr_p) if live_highs else curr_p
            raw_l = live_lows.get(sym, curr_p) if live_lows else curr_p
            high_p = max(curr_p, raw_h)
            low_p = min(curr_p, raw_l)

            tp1_p = float(s.get('tp1_price', entry_p))
            tp2_p = float(s.get('tp2_price', entry_p))
            tp3_p = float(s.get('tp3_price', entry_p))
            sl_p = float(s.get('sl_price', entry_p))

            is_tp1_locked = bool(s.get('is_tp1_locked', False) or status in ['TP1_LOCKED_BREAKEVEN', 'TP2_LOCKED_TRAIL'])
            is_tp2_locked = bool(s.get('is_tp2_locked', False) or status == 'TP2_LOCKED_TRAIL')
            is_tier0_locked = bool(s.get('is_tier0_locked', False) or status == 'TIER0_PROTECTED_BREAKEVEN')

            # Check expiration
            is_expired = False
            pred_close_str = str(s.get('predicted_close_utc', '')).strip()
            if pred_close_str and pred_close_str != 'N/A':
                try:
                    clean_dt_str = pred_close_str.replace(' UTC', '').strip()
                    close_dt = datetime.fromisoformat(clean_dt_str) if 'T' in clean_dt_str else datetime.strptime(clean_dt_str, '%Y-%m-%d %H:%M:%S' if len(clean_dt_str) > 16 else '%Y-%m-%d %H:%M')
                    if close_dt.tzinfo is None:
                        close_dt = close_dt.replace(tzinfo=timezone.utc)
                    if now_utc >= close_dt:
                        is_expired = True
                except Exception:
                    pass

            if not is_expired:
                created_ts = s.get('created_ts')
                h_tag = s.get('horizon_tag') or resolve_horizon_tag(s.get('horizon_key', 'scalp'))
                dur_sec = HORIZON_EXPIRY_SECONDS.get(h_tag, 3600)
                if created_ts and (now_ts - float(created_ts)) >= dur_sec:
                    is_expired = True

            # Target checks
            is_hit_tp3 = (high_p >= tp3_p) if is_long else (low_p <= tp3_p)
            is_hit_tp2 = (high_p >= tp2_p) if is_long else (low_p <= tp2_p)
            is_hit_tp1 = (high_p >= tp1_p) if is_long else (low_p <= tp1_p)
            is_hit_sl = (low_p <= sl_p) if is_long else (high_p >= sl_p)

            # 0. Tier-0 Early Breakeven Guard (+0.65% gain raises SL to Soft BE)
            if pnl_pct >= 0.65 and not is_tp1_locked and not is_tier0_locked and not is_hit_sl:
                s['is_tier0_locked'] = True
                s['status'] = "TIER0_PROTECTED_BREAKEVEN"
                soft_be_p = (entry_p * 0.998) if is_long else (entry_p * 1.002)
                s['sl_price'] = round(max(sl_p, soft_be_p) if is_long else min(sl_p, soft_be_p), 6)
                sl_p = s['sl_price']
                s['outcome_label'] = "🛡️ PROFIT PROTECTED (SOFT BE)"
                is_tier0_locked = True
                updated = True

            # Win/Loss Resolution Transitions
            if is_hit_tp3:
                s['status'] = "WON_TP3"
                s['outcome_label'] = f"🏆 WON TP3 (+{abs(tp3_p - entry_p)/entry_p*100.0:.2f}%)"
                s['exit_price'] = round(tp3_p, 6)
                s['resolved_at_ts'] = now_ts
                s['resolved_at_utc'] = now_str
                updated = True
            elif is_hit_tp2 and not is_tp2_locked and not is_hit_sl:
                s['status'] = "TP2_LOCKED_TRAIL"
                s['outcome_label'] = "🎯 TP2 HIT (TRAILING)"
                s['is_tp2_locked'] = True
                s['is_tp1_locked'] = True
                s['sl_price'] = round(tp1_p, 6)  # Trail SL to TP1 floor
                updated = True
            elif is_hit_tp1 and not is_tp1_locked and not is_hit_sl:
                s['status'] = "TP1_LOCKED_BREAKEVEN"
                s['outcome_label'] = "🎯 TP1 HIT (SL @ BE)"
                s['is_tp1_locked'] = True
                s['sl_price'] = round(entry_p, 6)  # Trail SL to Breakeven
                updated = True
            elif is_hit_sl:
                if is_tp2_locked:
                    s['status'] = "WON_TP2_TRAIL"
                    s['outcome_label'] = "🏆 WON (TP2 + TRAIL)"
                elif is_tp1_locked:
                    s['status'] = "WON_TP1_BE"
                    s['outcome_label'] = "🏆 WON (TP1 + BE)"
                elif is_tier0_locked:
                    s['status'] = "WON_TIER0_BE"
                    ret_be = ((sl_p - entry_p) / entry_p) * 100.0 if is_long else ((entry_p - sl_p) / entry_p) * 100.0
                    s['outcome_label'] = f"🛡️ BREAKEVEN (TIER-0 GUARD {ret_be:+.2f}%)"
                else:
                    s['status'] = "LOST_SL"
                    s['outcome_label'] = f"🛑 STOPPED (SL -{abs(sl_p - entry_p)/entry_p*100.0:.2f}%)"
                s['exit_price'] = round(sl_p, 6)
                s['resolved_at_ts'] = now_ts
                s['resolved_at_utc'] = now_str
                updated = True
            elif is_expired:
                if is_tier0_locked:
                    s['status'] = "WON_TIER0_BE"
                    s['outcome_label'] = f"🛡️ EXPIRED (TIER-0 BE {pnl_pct:+.2f}%)"
                else:
                    s['status'] = "EXPIRED"
                    ret_sign = "+" if pnl_pct >= 0 else ""
                    s['outcome_label'] = f"⏱️ EXPIRED ({ret_sign}{pnl_pct:.2f}%)"
                s['exit_price'] = round(curr_p, 6)
                s['resolved_at_ts'] = now_ts
                s['resolved_at_utc'] = now_str
                updated = True

        if updated:
            self.save_state()

        return updated

    def get_display_signals(self) -> list:
        """Returns sorted active signals followed by recently resolved signals, deduplicated to 1 latest per coin per horizon."""
        active_list = []
        resolved_list = []
        seen_active_pairs = set()

        for s in self.active_signals.values():
            status = s.get('status', 'ACTIVE')
            sym = self._clean_sym(s.get('symbol', ''))
            h_tag = s.get('horizon_tag') or resolve_horizon_tag(s.get('horizon_key', 'scalp'))
            pair_key = (sym, h_tag)

            if status in ["ACTIVE", "PENDING_EVALUATION", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"]:
                if pair_key not in seen_active_pairs:
                    seen_active_pairs.add(pair_key)
                    active_list.append(s)
            else:
                resolved_list.append(s)

        # Sort active: Grade Tier asc, Meta Win Prob desc, Conviction desc
        active_list.sort(key=lambda x: (
            x.get('grade_tier', 2),
            -float(x.get('meta_win_prob', 0.70)),
            -float(x.get('conviction', 50.0))
        ))

        # Sort resolved: Most recently resolved first
        resolved_list.sort(key=lambda x: -float(x.get('resolved_at_ts', 0.0)))

        # Assign clean rank labels #1, #2...
        combined = active_list + resolved_list
        medals = ["🥇 TOP PICK (#1)", "🥈 RUNNER UP (#2)", "🥉 BRONZE (#3)", "🎯 PICK (#4)", "🎯 PICK (#5)"]
        for idx, sig in enumerate(combined):
            if idx < len(medals):
                sig['rank'] = medals[idx]
            else:
                sig['rank'] = f"#{idx+1}"

        return combined

    def get_signals_by_horizon(self) -> dict:
        """Groups display signals by standard horizon tags, guaranteeing 1 latest active signal per coin."""
        tags = ["15M", "30M", "1H", "4H", "12H", "24H", "4D", "7D", "15D", "30D"]
        res = {t: [] for t in tags}
        seen_by_tag = {t: set() for t in tags}

        for s in self.get_display_signals():
            h_tag = s.get('horizon_tag') or resolve_horizon_tag(s.get('horizon_key', 'scalp'))
            if h_tag not in res:
                h_tag = "15M"

            sym = self._clean_sym(s.get('symbol', ''))
            if sym and sym in seen_by_tag[h_tag]:
                continue
            if sym:
                seen_by_tag[h_tag].add(sym)
            res[h_tag].append(s)

        return res

# ------------------------------------------------------------------------------
# 7.5 SECONDARY MACHINE LEARNING META-LABELING CLASSIFIER
# ------------------------------------------------------------------------------
class SignalMetaClassifier:
    """
    Two-Stage Meta-Labeling Classifier (Marcos López de Prado architecture).
    Predicts probability P(Trade hits TP before SL) using model agreement,
    timeframe confluence, R:R metrics, and market regime features.
    """
    def __init__(self, model_path: str = "./models_export_v3/signal_meta_classifier.joblib"):
        self.model_path = model_path
        self.bundle = None
        self.model = None
        self.feature_cols = []
        self._last_mtime = 0
        self.load_model()

    def load_model(self):
        if not os.path.exists(self.model_path):
            try:
                from app.services.model_retrainer import run_retraining_pipeline
                print(f"[META CLASSIFIER 🧠] Model not found at {self.model_path}. Auto-training initial model from dataset...")
                run_retraining_pipeline(force=True)
            except Exception as e:
                pass

        if os.path.exists(self.model_path):
            try:
                mtime = os.path.getmtime(self.model_path)
                if mtime != self._last_mtime or self.model is None:
                    self.bundle = joblib.load(self.model_path)
                    self.model = self.bundle.get('model')
                    self.feature_cols = self.bundle.get('feature_cols', [])
                    self._last_mtime = mtime
                    print(f"[META CLASSIFIER 🧠] Loaded / Hot-Reloaded Trained Secondary Meta-Labeling Model from {self.model_path}")
            except Exception as e:
                print(f"[META CLASSIFIER ⚠️] Model load fallback note: {e}")
                self.model = None

    def predict_win_probability(self, sig: dict) -> float:
        """Predicts calibrated win probability (0.0 to 1.0) for a candidate signal."""
        # Auto-check if model was updated on disk
        if os.path.exists(self.model_path):
            try:
                if os.path.getmtime(self.model_path) != self._last_mtime:
                    self.load_model()
            except Exception:
                pass
        conv = float(sig.get('conviction', 70.0))
        is_a_plus = 1.0 if "A+" in str(sig.get('grade', '')) else 0.0
        exp_ret = float(sig.get('exp_return', 0.0)) * 100.0
        h_key = str(sig.get('horizon_key', 'scalp')).lower()
        direction_str = str(sig.get('direction', 'LONG')).upper()
        decision_str = str(sig.get('decision', 'EXECUTE')).upper()

        curr_p = float(sig.get('entry_price', 1.0) or 1.0)
        tp1_p = float(sig.get('tp1_price', 1.0) or 1.0)
        sl_p = float(sig.get('sl_price', 1.0) or 1.0)

        if curr_p > 0 and sl_p > 0:
            tp_pct = abs(tp1_p - curr_p) / curr_p * 100.0
            sl_pct = abs(curr_p - sl_p) / curr_p * 100.0
        else:
            tp_pct = abs(exp_ret)
            sl_pct = abs(exp_ret) / 2.0

        if not self.model or not self.feature_cols:
            base_p = (conv / 100.0) * (0.88 if is_a_plus else 0.76)
            return round(min(0.95, max(0.40, base_p)), 3)

        try:
            is_bottom_reversal = 1.0 if "BOTTOM-REVERSAL" in decision_str else 0.0
            is_top_reversal = 1.0 if "TOP-REVERSAL" in decision_str else 0.0
            is_reversal = 1.0 if (is_bottom_reversal or is_top_reversal) else 0.0

            row = {
                'conviction_pct': conv,
                'expected_return_pct': exp_ret,
                'risk_reward_ratio': 2.0,
                'is_a_plus': is_a_plus,
                'is_scalp': 1.0 if ("scalp" in h_key or "15m" in h_key) else 0.0,
                'is_swing': 1.0 if ("swing" in h_key or "1h" in h_key) else 0.0,
                'is_macro': 1.0 if ("macro" in h_key or "24h" in h_key or "1d" in h_key or "2d" in h_key or "3d" in h_key or "7d" in h_key or "15d" in h_key or "30d" in h_key or "week" in h_key or "month" in h_key) else 0.0,
                'is_long': 1.0 if direction_str in ["LONG", "BULLISH"] else 0.0,
                'is_dip_buy': 1.0 if "DIP-BUY" in decision_str else 0.0,
                'is_rally_sell': 1.0 if "RALLY-SELL" in decision_str else 0.0,
                'is_bottom_reversal': is_bottom_reversal,
                'is_top_reversal': is_top_reversal,
                'is_reversal': is_reversal,
                'is_liq_sweep': 1.0 if "LIQUIDITY-SWEEP" in decision_str else 0.0,
                'is_squeeze': 1.0 if "SHORT SQUEEZE" in decision_str else 0.0,
                'is_paper_exec': 1.0 if "ACTIVE" in str(sig.get('paper_trading_status', '')).upper() else 0.0,
                'rank': float(sig.get('priority', 1)),
                'tp_pct': tp_pct,
                'sl_pct': sl_pct,
                'tp_sl_ratio': tp_pct / max(0.01, sl_pct)
            }
            df_feat = pd.DataFrame([row])[self.feature_cols]
            prob = float(self.model.predict_proba(df_feat)[0, 1])
            return round(prob, 3)
        except Exception:
            base_p = (conv / 100.0) * (0.88 if is_a_plus else 0.76)
            return round(min(0.95, max(0.40, base_p)), 3)

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
        self.model_cache_path = os.path.join(self.config.get('models_export_dir', './models_export_v3'), "models_cache.joblib")
        if os.path.exists(self.model_cache_path):
            try:
                self.model_cache = joblib.load(self.model_cache_path)
                print(f"[MODEL CACHE 🧠] Loaded {len(self.model_cache)} pre-warmed models from persistent cache: {self.model_cache_path}")
            except Exception as e:
                print(f"[MODEL CACHE ⚠️] Cache notice: {e}")
                self.model_cache = {}
        else:
            self.model_cache = {}
        self.btc_shield_active = False
        self.btc_shield_code = "CONSOLIDATION"
        self.btc_shield_regime = "CONSOLIDATION"
        self.btc_shield_regime_label = "💤 RANGE CONSOLIDATION"
        self.btc_shield_reason = "RANGE CONSOLIDATION"
        self.btc_composite_score = 0.0
        self.btc_price = 0.0
        self.btc_15m_change = 0.0
        self.btc_1h_change = 0.0
        self.btc_4h_change = 0.0
        self.btc_24h_change = 0.0
        self.btc_rsi_15m = 50.0
        self.btc_rsi_1h = 50.0
        self.btc_rsi_4h = 50.0
        self.btc_trend_structure = "Multi-Timeframe Range Consolidation"
        self.btc_is_squeeze = False
        self.btc_bbw_15m = 0.0
        self.btc_vol_ratio = 1.0
        self._last_btc_heartbeat_ts = 0.0
        self._last_shield_file_sync_ts = 0.0
        self.signal_cooldown_tracker = {}
        self.symbol_last_signal_time = {}
        self.ledger = PaperTradingLedger(config)
        self.signal_tracker = SignalAuditTracker(config.get('app_export_dir', './export_app_data'))
        self.institutional_signal_manager = ActiveInstitutionalSignalManager(
            config.get('app_export_dir', './export_app_data'),
            audit_tracker=self.signal_tracker
        )
        self.meta_classifier = SignalMetaClassifier(
            os.path.join(self.config.get('models_export_dir', './models_export_v3'), "signal_meta_classifier.joblib")
        )
        self.master_matrix_universe = {}
        forecast_path = os.path.join(self.config['app_export_dir'], "live_market_forecast.json")
        if os.path.exists(forecast_path):
            try:
                with open(forecast_path, "r", encoding="utf-8") as f:
                    f_data = json.load(f)
                    for item in f_data.get("scanner_leaderboard", []):
                        if isinstance(item, dict) and "symbol" in item:
                            self.master_matrix_universe[item["symbol"]] = item
                if self.master_matrix_universe:
                    print(f"[PREDICTION MATRIX 🌐] Preloaded {len(self.master_matrix_universe)} existing asset predictions into memory.")
            except Exception:
                pass
        os.makedirs(self.config['models_export_dir'], exist_ok=True)
        os.makedirs(self.config['app_export_dir'], exist_ok=True)

    def _prune_model_cache(self, max_size: int = 3000, max_age_seconds: float = 86400 * 14):
        """
        OS Memory Guard: Prunes expired and excess models from RAM cache.
        Prevents unbounded growth across continuous multi-day scanning cycles.
        """
        now_ts = time.time()
        # 1. Prune expired entries
        expired_keys = [k for k, v in self.model_cache.items() if (now_ts - v.get('ts', 0)) >= max_age_seconds]
        for k in expired_keys:
            self.model_cache.pop(k, None)
        # 2. If still exceeds max_size, drop oldest entries by timestamp
        if len(self.model_cache) > max_size:
            sorted_keys = sorted(self.model_cache.keys(), key=lambda k: self.model_cache[k].get('ts', 0))
            excess = len(self.model_cache) - max_size
            for k in sorted_keys[:excess]:
                self.model_cache.pop(k, None)

    def preload_btc_reference(self):
        print("[DATA] Preloading Bitcoin multi-scale data for cross-asset beta calculations...")
        for tf in self.config['timeframes']:
            try:
                df_btc = self.loader.fetch_ohlcv_extended("BTC/USDT", tf, total_candles=self.config['history_limit_per_tf'].get(tf, 2000))
                self.btc_cache[tf] = df_btc
            except Exception as e:
                print(f"[WARNING] BTC reference fetch note for {tf}: {e}")

        # 🛡️ GLOBAL BTC MARKET BETA SHIELD (MARKET REGIME & CIRCUIT BREAKER)
        self.evaluate_btc_market_regime()

    def evaluate_btc_market_regime(self, live_btc_price: float = None):
        """
        🛡️ ADVANCED MULTI-FACTOR BTC QUANTITATIVE MARKET REGIME & SENTIMENT ENGINE
        Accurately predicts real-time macro & intraday market states based on Bitcoin multi-scale dynamics:
        - 🚀 BULL_MOMENTUM / BULLISH EXPANSION: Strong upward trend acceleration & momentum markup
        - 💎 DIP ACCUMULATION: Oversold bounce off support within macro bull trend
        - 🐻 BEAR_MOMENTUM / BEARISH BREAKDOWN: Strong downward distribution & negative momentum drift
        - 💤 RANGE CONSOLIDATION: Volatility squeeze / tight Bollinger Band coiling / mean-reversion
        - ⚡ HIGH VOLATILITY CHOP: Expanding volatility ratio with mixed multi-timeframe direction
        - ⚠️ DEFENSIVE: Cascade drop circuit breaker (Altcoin longs paused)
        - 🚨 ALERT_DUMP: Severe flash flush (Emergency risk-off pause)
        - ⚖️ BALANCED EQUILIBRIUM: Neutral baseline market
        """
        try:
            df_15m = self.btc_cache.get('15m')
            df_1h = self.btc_cache.get('1h')
            df_4h = self.btc_cache.get('4h')
            df_1d = self.btc_cache.get('1d')

            if df_15m is None or len(df_15m) < 15:
                return

            c_now = float(live_btc_price) if (live_btc_price is not None and live_btc_price > 0) else float(df_15m['close'].iloc[-1])
            c_prev_15m = float(df_15m['close'].iloc[-2])
            c_prev3_15m = float(df_15m['close'].iloc[-4]) if len(df_15m) >= 4 else c_prev_15m
            ret_15m = (c_now - c_prev_15m) / (c_prev_15m + 1e-10)
            ret_45m = (c_now - c_prev3_15m) / (c_prev3_15m + 1e-10)

            # 1H metrics
            ret_1h = 0.0
            ema20_1h = c_now
            ema50_1h = c_now
            ema200_1h = c_now
            rsi_1h = 50.0
            if df_1h is not None and len(df_1h) >= 15:
                c_prev_1h = float(df_1h['close'].iloc[-2])
                ret_1h = (c_now - c_prev_1h) / (c_prev_1h + 1e-10)
                ema20_1h = float(df_1h['close'].ewm(span=20, adjust=False).mean().iloc[-1])
                ema50_1h = float(df_1h['close'].ewm(span=50, adjust=False).mean().iloc[-1])
                ema200_1h = float(df_1h['close'].ewm(span=200, adjust=False).mean().iloc[-1]) if len(df_1h) >= 200 else ema50_1h
                rsi_1h_series = self.fe.compute_rsi(df_1h['close'], period=14)
                rsi_1h = float(rsi_1h_series.iloc[-1]) * 100.0

            # 4H metrics
            ret_4h = 0.0
            ema50_4h = c_now
            ema200_4h = c_now
            rsi_4h = 50.0
            if df_4h is not None and len(df_4h) >= 5:
                c_prev_4h = float(df_4h['close'].iloc[-2])
                ret_4h = (c_now - c_prev_4h) / (c_prev_4h + 1e-10)
                ema50_4h = float(df_4h['close'].ewm(span=50, adjust=False).mean().iloc[-1])
                ema200_4h = float(df_4h['close'].ewm(span=200, adjust=False).mean().iloc[-1]) if len(df_4h) >= 200 else ema50_4h
                rsi_4h_series = self.fe.compute_rsi(df_4h['close'], period=14)
                rsi_4h = float(rsi_4h_series.iloc[-1]) * 100.0

            # 1D Macro metrics
            ret_24h = 0.0
            ema50_1d = c_now
            ema200_1d = c_now
            if df_1d is not None and len(df_1d) >= 5:
                c_prev_1d = float(df_1d['close'].iloc[-2])
                ret_24h = (c_now - c_prev_1d) / (c_prev_1d + 1e-10)
                ema50_1d = float(df_1d['close'].ewm(span=50, adjust=False).mean().iloc[-1])
                ema200_1d = float(df_1d['close'].ewm(span=200, adjust=False).mean().iloc[-1]) if len(df_1d) >= 200 else ema50_1d

            # 15M Technicals (EMA, RSI, Bollinger Bands, ATR)
            ema9_15m = float(df_15m['close'].ewm(span=9, adjust=False).mean().iloc[-1])
            ema21_15m = float(df_15m['close'].ewm(span=21, adjust=False).mean().iloc[-1])
            rsi_15m_series = self.fe.compute_rsi(df_15m['close'], period=14)
            rsi_15m = float(rsi_15m_series.iloc[-1]) * 100.0

            # Bollinger Bands 15M
            std_15m = float(df_15m['close'].rolling(20).std().iloc[-1]) if len(df_15m) >= 20 else 0.0
            bb_mid_15m = float(df_15m['close'].rolling(20).mean().iloc[-1]) if len(df_15m) >= 20 else ema21_15m
            bb_upper_15m = bb_mid_15m + 2.0 * std_15m
            bb_lower_15m = bb_mid_15m - 2.0 * std_15m
            bbw_15m = (bb_upper_15m - bb_lower_15m) / (bb_mid_15m + 1e-10)

            # Bollinger Bands 1H
            bbw_1h = 0.04
            if df_1h is not None and len(df_1h) >= 20:
                std_1h = float(df_1h['close'].rolling(20).std().iloc[-1])
                bb_mid_1h = float(df_1h['close'].rolling(20).mean().iloc[-1])
                bbw_1h = (4.0 * std_1h) / (bb_mid_1h + 1e-10)

            # Volatility ratio vs rolling baseline
            atr_15m_series = self.fe.compute_atr(df_15m, period=14)
            atr_15m = float(atr_15m_series.iloc[-1])
            baseline_atr = float(atr_15m_series.rolling(32).mean().iloc[-1]) if len(atr_15m_series) >= 32 else atr_15m
            vol_ratio = (atr_15m / (baseline_atr + 1e-10)) if baseline_atr > 0 else 1.0

            # Multi-timeframe trend states
            is_1d_bull = (c_now >= ema50_1d) and (ema50_1d >= ema200_1d)
            is_1d_bear = (c_now <= ema50_1d) and (ema50_1d <= ema200_1d)

            is_4h_bull = (c_now >= ema50_4h) and (ema50_4h >= ema200_4h)
            is_4h_bear = (c_now <= ema50_4h) and (ema50_4h <= ema200_4h)

            is_1h_bull = (c_now >= ema20_1h >= ema50_1h)
            is_1h_bear = (c_now <= ema20_1h <= ema50_1h)

            is_15m_bull = (c_now >= ema9_15m >= ema21_15m)
            is_15m_bear = (c_now <= ema9_15m <= ema21_15m)

            # Institutional Composite Market Score Calculation (-100 to +100)
            trend_pts = 0.0
            trend_pts += 15.0 if is_1d_bull else (-15.0 if is_1d_bear else 0.0)
            trend_pts += 15.0 if is_4h_bull else (-15.0 if is_4h_bear else 0.0)
            trend_pts += 10.0 if is_1h_bull else (-10.0 if is_1h_bear else 0.0)

            mom_pts = 0.0
            mom_pts += float(np.clip((rsi_1h - 50.0) * 0.5, -15.0, 15.0))
            mom_pts += float(np.clip((rsi_15m - 50.0) * 0.3, -10.0, 10.0))
            mom_pts += 10.0 if is_15m_bull else (-10.0 if is_15m_bear else 0.0)

            vel_pts = 0.0
            vel_pts += float(np.clip((ret_1h / 0.015) * 15.0, -15.0, 15.0))
            vel_pts += float(np.clip((ret_15m / 0.008) * 10.0, -10.0, 10.0))

            composite_score = round(float(np.clip(trend_pts + mom_pts + vel_pts, -100.0, 100.0)), 1)

            # Structural narrative description
            if is_1h_bull and is_4h_bull:
                trend_structure = "Bullish Alignment (1H & 4H Trend Up)"
            elif is_1h_bear and is_4h_bear:
                trend_structure = "Bearish Alignment (1H & 4H Trend Down)"
            elif is_1h_bear and is_1d_bull:
                trend_structure = "Intraday Pullback in Macro Bull Trend"
            elif is_1h_bull and is_1d_bear:
                trend_structure = "Bear Market Relief Rally"
            elif bbw_15m <= 0.018:
                trend_structure = "15M Volatility Squeeze (Coiling)"
            else:
                trend_structure = "Multi-Timeframe Range Consolidation"

            is_squeeze = (bbw_15m <= 0.018) or (bbw_1h <= 0.030)

            # --- REGIME CLASSIFICATION ENGINE HIERARCHY ---
            if ret_15m <= -0.018 or ret_1h <= -0.028 or (ret_15m <= -0.012 and ret_45m <= -0.022):
                # 1. ALERT_DUMP: Emergency risk-off flush
                active = True
                code = "ALERT_DUMP"
                regime = "DUMP"
                regime_label = "🚨 SEVERE SYSTEMIC DUMP"
                reason = f"ALERT DUMP (BTC: ${c_now:,.0f} | 15M: {ret_15m*100:+.2f}% | 1H: {ret_1h*100:+.2f}%)"

            elif ret_15m <= -0.009 or ret_1h <= -0.016 or (ret_15m <= -0.006 and c_now < bb_lower_15m and rsi_15m < 28.0):
                # 2. DEFENSIVE: Altcoin longs paused
                active = True
                code = "DEFENSIVE"
                regime = "DEFENSIVE"
                regime_label = "⚠️ BTC DUMP CIRCUIT BREAKER"
                reason = f"CIRCUIT BREAKER (BTC: ${c_now:,.0f} | 15M: {ret_15m*100:+.2f}% | 1H: {ret_1h*100:+.2f}%)"

            elif composite_score >= 25.0 or (is_1h_bull and ret_1h >= 0.003 and rsi_1h >= 52.0) or (ret_1h >= 0.007 and rsi_15m >= 54.0):
                # 3. BULL_MOMENTUM: Bullish expansion & markup
                active = False
                code = "BULL_MOMENTUM"
                regime = "BULLISH"
                regime_label = "🚀 BULLISH EXPANSION"
                reason = f"BULLISH EXPANSION (BTC: ${c_now:,.0f} | Score: +{composite_score:.0f} | 1H: {ret_1h*100:+.2f}% | RSI: {rsi_1h:.1f})"

            elif (rsi_15m <= 36.0 and ret_15m > 0 and (is_1d_bull or is_4h_bull) and c_now <= bb_lower_15m * 1.003):
                # 4. BULL_ACCUMULATION: Dip-buy reversal off oversold
                active = False
                code = "BULL_MOMENTUM"
                regime = "BULLISH"
                regime_label = "💎 DIP ACCUMULATION"
                reason = f"DIP ACCUMULATION (BTC: ${c_now:,.0f} | Oversold Bounce | RSI: {rsi_15m:.1f})"

            elif composite_score <= -25.0 or (is_1h_bear and ret_1h <= -0.003 and rsi_1h <= 48.0) or (ret_1h <= -0.007 and rsi_15m <= 46.0):
                # 5. BEAR_MOMENTUM: Bearish markdown & distribution
                active = False
                code = "BEAR_MOMENTUM"
                regime = "BEARISH"
                regime_label = "🐻 BEARISH BREAKDOWN"
                reason = f"BEARISH BREAKDOWN (BTC: ${c_now:,.0f} | Score: {composite_score:.0f} | 1H: {ret_1h*100:+.2f}% | RSI: {rsi_1h:.1f})"

            elif (vol_ratio >= 1.65 or abs(ret_15m) >= 0.010 or rsi_15m >= 82.0 or rsi_15m <= 18.0) and not is_squeeze:
                # 6. CAUTION: Elevated volatility whipsaw
                active = False
                code = "CAUTION"
                regime = "VOLATILE"
                regime_label = "⚡ HIGH VOLATILITY CHOP"
                reason = f"HIGH VOLATILITY (BTC: ${c_now:,.0f} | Vol Ratio: {vol_ratio:.1f}x | 15M: {ret_15m*100:+.2f}%)"

            elif is_squeeze or abs(composite_score) < 22.0 or (38.0 <= rsi_1h <= 62.0 and abs(ret_1h) <= 0.008):
                # 7. CONSOLIDATION: Range-bound squeeze / coiling inside bands
                active = False
                code = "CONSOLIDATION"
                regime = "CONSOLIDATION"
                regime_label = "💤 RANGE CONSOLIDATION"
                sq_note = f"Squeeze: {bbw_15m*100:.2f}%" if is_squeeze else f"RSI: {rsi_1h:.1f}"
                reason = f"RANGE CONSOLIDATION (BTC: ${c_now:,.0f} | Score: {composite_score:+.0f} | {sq_note})"

            else:
                # 8. NORMAL: Balanced Equilibrium
                active = False
                code = "NORMAL"
                regime = "STABLE"
                regime_label = "⚖️ BALANCED EQUILIBRIUM"
                reason = f"BALANCED MARKET (BTC: ${c_now:,.0f} | Score: {composite_score:+.0f})"

            # Assign properties
            self.btc_shield_active = active
            self.btc_shield_code = code
            self.btc_shield_regime = regime
            self.btc_shield_regime_label = regime_label
            self.btc_shield_reason = reason
            self.btc_composite_score = composite_score
            self.btc_price = round(c_now, 2)
            self.btc_15m_change = round(ret_15m * 100.0, 2)
            self.btc_1h_change = round(ret_1h * 100.0, 2)
            self.btc_4h_change = round(ret_4h * 100.0, 2)
            self.btc_24h_change = round(ret_24h * 100.0, 2)
            self.btc_rsi_15m = round(rsi_15m, 1)
            self.btc_rsi_1h = round(rsi_1h, 1)
            self.btc_rsi_4h = round(rsi_4h, 1)
            self.btc_trend_structure = trend_structure
            self.btc_is_squeeze = is_squeeze
            self.btc_bbw_15m = round(bbw_15m * 100.0, 2)
            self.btc_vol_ratio = round(vol_ratio, 2)

            if self.btc_shield_active:
                print(f"\n[SHIELD 🛡️] ⚠️ BTC MARKET BETA SHIELD ACTIVATED: {self.btc_shield_reason} | Altcoin Longs Paused to Prevent Correlated Stop-Outs.\n")
            else:
                print(f"[SHIELD 🛡️] Market Beta Status: {self.btc_shield_reason} | Regime: {self.btc_shield_regime_label}")

        except Exception as e:
            self.btc_shield_active = False
            self.btc_shield_code = "NORMAL"
            self.btc_shield_regime = "STABLE"
            self.btc_shield_regime_label = "⚖️ BALANCED EQUILIBRIUM"
            self.btc_shield_reason = "BALANCED MARKET"
            print(f"[SHIELD Note evaluating BTC regime: {e}")

    def evaluate_single_horizon(self, symbol: str, horizon_key: str, h_cfg: dict, raw_dfs: dict, tf_features: dict, d1_macro_bull: bool, funding_info: dict = None, live_price: float = None) -> dict:
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
        if live_price is not None and live_price > 0:
            current_price = float(live_price)
            live_candle.at[live_candle.index[0], 'close'] = current_price
        else:
            current_price = float(live_candle['close'].values[0])
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
        if n < 10 or len(feature_cols) == 0:
            # Low historical data fallback (e.g. newly listed or illiquid pair)
            p_cat_live = 0.55 if d1_macro_bull else 0.45
            p_xgb_live = 0.55 if d1_macro_bull else 0.45
            p_lgb_live = 0.55 if d1_macro_bull else 0.45
            p_et_live = 0.55 if d1_macro_bull else 0.45
            w_cat, w_xgb, w_lgb, w_et = (0.25, 0.25, 0.25, 0.25)
            elite_acc = 0.60
        else:
            n_train = max(5, int(n * self.config['train_split']))
            X_train, y_p_train, y_r_train = X[:n_train], y_p[:n_train].copy(), y_r[:n_train]
            X_test, y_p_test = X[n_train:], y_p[n_train:]

            # Prevent CatBoost / XGBoost "Target contains only one unique value" crash
            unique_classes = np.unique(y_p_train)
            if len(unique_classes) < 2 and len(y_p_train) > 1:
                y_p_train[0] = 1 - y_p_train[-1]

            # Fast-Boot Model Checkpoint & Memory Cache (14 Day Lifetime)
            cache_key = f"{symbol.replace('/', '_')}_{horizon_key}"
            now_ts = time.time()

            if cache_key in self.model_cache and (now_ts - self.model_cache[cache_key].get('ts', 0) < 86400 * 14):
                cached = self.model_cache[cache_key]
                cached['ts'] = now_ts  # Update LRU access timestamp
                scaler = cached['scaler']
                cat = cached['cat']
                xgb_m = cached['xgb_m']
                lgb_m = cached.get('lgb_m') if HAS_LIGHTGBM else None
                et = cached['et']
                w_cat, w_xgb, w_lgb, w_et = cached.get('weights', (0.35, 0.35, 0.20, 0.10))
                elite_acc = cached['elite_acc']
                X_live_scaled = np.nan_to_num(scaler.transform(live_candle[feature_cols].values), nan=0.0)
                
                p_cat_live = float(cat.predict_proba(X_live_scaled)[0, 1]) if cat else 0.50
                p_xgb_live = float(xgb_m.predict_proba(X_live_scaled)[0, 1]) if xgb_m else 0.50
                if lgb_m:
                    try:
                        with _LGBM_LOCK:
                            p_lgb_live = float(lgb_m.predict_proba(X_live_scaled)[0, 1])
                    except Exception:
                        p_lgb_live = p_xgb_live
                else:
                    p_lgb_live = p_xgb_live
                p_et_live = float(et.predict_proba(X_live_scaled)[0, 1]) if et else 0.50
            else:
                scaler = RobustScaler()
                X_train_scaled = np.nan_to_num(scaler.fit_transform(X_train), nan=0.0)
                X_test_scaled = np.nan_to_num(scaler.transform(X_test), nan=0.0)
                X_live_scaled = np.nan_to_num(scaler.transform(live_candle[feature_cols].values), nan=0.0)

                # 1. CatBoost Classifier
                try:
                    cat = QuantModelFactory.build_primary_catboost(self.config['catboost'])
                    cat.fit(X_train_scaled, y_p_train, verbose=False)
                    p_cat_live = float(cat.predict_proba(X_live_scaled)[0, 1])
                    p_test_cat = cat.predict_proba(X_test_scaled)[:, 1] if len(X_test_scaled) > 0 else np.array([p_cat_live])
                except Exception:
                    cat = None
                    p_cat_live = 0.55 if d1_macro_bull else 0.45
                    p_test_cat = np.array([p_cat_live] * max(1, len(X_test_scaled)))

                # 2. XGBoost Classifier
                try:
                    xgb_m = QuantModelFactory.build_primary_xgboost(self.config['xgb_clf'])
                    xgb_m.fit(X_train_scaled, y_p_train, verbose=False)
                    p_xgb_live = float(xgb_m.predict_proba(X_live_scaled)[0, 1])
                    p_test_xgb = xgb_m.predict_proba(X_test_scaled)[:, 1] if len(X_test_scaled) > 0 else np.array([p_xgb_live])
                except Exception:
                    xgb_m = None
                    p_xgb_live = 0.55 if d1_macro_bull else 0.45
                    p_test_xgb = np.array([p_xgb_live] * max(1, len(X_test_scaled)))

                # 3. LightGBM Classifier (Protected with _LGBM_LOCK for thread safety)
                try:
                    lgb_m = QuantModelFactory.build_primary_lightgbm(self.config['lgb_clf'])
                    if lgb_m:
                        with _LGBM_LOCK:
                            lgb_m.fit(X_train_scaled, y_p_train)
                            p_lgb_live = float(lgb_m.predict_proba(X_live_scaled)[0, 1])
                            p_test_lgb = lgb_m.predict_proba(X_test_scaled)[:, 1] if len(X_test_scaled) > 0 else np.array([p_lgb_live])
                    else:
                        lgb_m = None
                        p_lgb_live = p_xgb_live
                        p_test_lgb = p_test_xgb
                except Exception:
                    lgb_m = None
                    p_lgb_live = p_xgb_live
                    p_test_lgb = p_test_xgb

                # 4. ExtraTrees Classifier
                try:
                    et = QuantModelFactory.build_primary_extra_trees(self.config['extra_trees'])
                    et.fit(X_train_scaled, y_p_train)
                    p_et_live = float(et.predict_proba(X_live_scaled)[0, 1])
                    p_test_et = et.predict_proba(X_test_scaled)[:, 1] if len(X_test_scaled) > 0 else np.array([p_et_live])
                except Exception:
                    et = None
                    p_et_live = 0.55 if d1_macro_bull else 0.45
                    p_test_et = np.array([p_et_live] * max(1, len(X_test_scaled)))

                # Dynamic Validation-Loss Weighted Stacking
                losses = []
                for p_test in [p_test_cat, p_test_xgb, p_test_lgb, p_test_et]:
                    if len(y_p_test) >= 4:
                        p_c = np.clip(p_test, 1e-5, 1.0 - 1e-5)
                        loss = -np.mean(y_p_test * np.log(p_c) + (1 - y_p_test) * np.log(1 - p_c))
                        losses.append(max(0.01, float(loss)))
                    else:
                        losses.append(0.5)

                inv_losses = [1.0 / l for l in losses]
                sum_inv = sum(inv_losses)
                w_cat, w_xgb, w_lgb, w_et = [w / sum_inv for w in inv_losses]

                p_test_ens = (p_test_cat * w_cat) + (p_test_xgb * w_xgb) + (p_test_lgb * w_lgb) + (p_test_et * w_et)
                elite_mask = (p_test_ens >= self.config['elite_conviction_threshold']) | (p_test_ens <= (1.0 - self.config['elite_conviction_threshold']))
                elite_acc = accuracy_score(y_p_test[elite_mask], (p_test_ens[elite_mask] >= 0.5).astype(int)) if (len(y_p_test) > 0 and np.sum(elite_mask) >= 5) else 0.88

                if cat and xgb_m and et:
                    self.model_cache[cache_key] = {
                        'scaler': scaler,
                        'cat': cat,
                        'xgb_m': xgb_m,
                        'lgb_m': lgb_m,
                        'et': et,
                        'weights': (w_cat, w_xgb, w_lgb, w_et),
                        'elite_acc': elite_acc,
                        'ts': now_ts
                    }
                    if len(self.model_cache) > 3000:
                        self._prune_model_cache(max_size=2500, max_age_seconds=86400 * 14)

        # 1. Base ML Direction & Calibrated Probability with Hysteresis Smoothing
        h_prob = (p_cat_live * w_cat) + (p_xgb_live * w_xgb) + (p_lgb_live * w_lgb) + (p_et_live * w_et)
        
        # Hysteresis Band: [0.47, 0.53] represents low-conviction neutral consolidation zone
        if h_prob >= 0.53:
            h_dir = "BULLISH"
            h_conf = h_prob * 100.0
            is_neutral_zone = False
        elif h_prob <= 0.47:
            h_dir = "BEARISH"
            h_conf = (1.0 - h_prob) * 100.0
            is_neutral_zone = False
        else:
            # Inside the neutral consolidation band
            h_dir = "BULLISH" if d1_macro_bull else "BEARISH"
            h_conf = 50.0 + abs(h_prob - 0.50) * 100.0
            is_neutral_zone = True

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
        bull_rev_score = float(live_candle.get(f'{anchor_tf}_bull_reversal_score', pd.Series([0.0])).values[0])
        bear_rev_score = float(live_candle.get(f'{anchor_tf}_bear_reversal_score', pd.Series([0.0])).values[0])
        rsi_bull_div = live_candle.get(f'{anchor_tf}_rsi_bull_div', pd.Series([0])).values[0] == 1.0
        rsi_bear_div = live_candle.get(f'{anchor_tf}_rsi_bear_div', pd.Series([0])).values[0] == 1.0
        td9_buy_ex = live_candle.get(f'{anchor_tf}_td9_buy_exhaustion', pd.Series([0])).values[0] == 1.0
        td9_sell_ex = live_candle.get(f'{anchor_tf}_td9_sell_exhaustion', pd.Series([0])).values[0] == 1.0
        candlestick_bull = live_candle.get(f'{anchor_tf}_candlestick_bull_reversal', pd.Series([0])).values[0] == 1.0
        candlestick_bear = live_candle.get(f'{anchor_tf}_candlestick_bear_reversal', pd.Series([0])).values[0] == 1.0
        bb_spring = live_candle.get(f'{anchor_tf}_bb_spring', pd.Series([0])).values[0] == 1.0
        bb_upthrust = live_candle.get(f'{anchor_tf}_bb_upthrust', pd.Series([0])).values[0] == 1.0

        # Quantitative Reversal Detection: Bottom Bounces after Downtrends & Top Exhaustion after Uptrends
        is_bottom_reversal = (
            (bull_rev_score >= 0.45 or rsi_bull_div or (td9_buy_ex and (candlestick_bull or rsi_anchor <= 38.0)) or (bb_spring and rsi_anchor <= 42.0))
            and (p_cat_live >= 0.43 or p_xgb_live >= 0.43 or h_prob >= 0.45)
        )
        is_top_reversal = (
            (bear_rev_score >= 0.45 or rsi_bear_div or (td9_sell_ex and (candlestick_bear or rsi_anchor >= 62.0)) or (bb_upthrust and rsi_anchor >= 58.0))
            and (p_cat_live <= 0.57 or p_xgb_live <= 0.57 or h_prob <= 0.55)
        )

        is_dip_buy = d1_macro_bull and rsi_anchor <= 46.0 and (p_cat_live >= 0.48 or p_xgb_live >= 0.48)
        is_rally_sell = (not d1_macro_bull) and rsi_anchor >= 55.0 and (p_cat_live <= 0.52 or p_xgb_live <= 0.52)

        # Quantitative Breakdown Short & Breakout Long Engines
        btc_regime = getattr(self, 'btc_market_regime', 'RANGE_CONSOLIDATION')
        is_bear_regime = btc_regime in ["BEAR_MOMENTUM", "CIRCUIT_BREAKER", "ALERT_DUMP", "DUMP", "DEFENSIVE"]
        is_bull_regime = btc_regime in ["BULL_MOMENTUM", "BULLISH", "DIP_ACCUMULATION", "EXPANSION"] or d1_macro_bull

        # Quantitative Breakout Long Engine (activated on volume expansion, RS outperformance, or bullish price action)
        is_breakout_long = (
            (rs_btc >= 0.2 or is_bull_regime or d1_macro_bull) and
            (rsi_anchor >= 50.0 and rsi_anchor <= 72.0) and
            (h_dir == "BULLISH" or p_cat_live >= 0.50 or p_xgb_live >= 0.50 or h_prob >= 0.50) and
            not is_neutral_zone
        )
        is_momentum_long = (
            rs_btc >= 0.6 and
            (p_cat_live >= 0.48 or p_xgb_live >= 0.48 or h_prob >= 0.49) and
            rsi_anchor >= 46.0 and rsi_anchor <= 74.0
        )

        is_breakdown_short = (
            is_bear_regime and
            rs_btc < 0.0 and
            rsi_anchor <= 54.0 and
            (h_dir == "BEARISH" or p_cat_live <= 0.50 or p_xgb_live <= 0.50)
        )

        is_reversal_setup = False
        if is_bottom_reversal and (not is_top_reversal or bull_rev_score > bear_rev_score):
            h_dir = "BULLISH"
            h_conf = max(72.0, min(97.0, 62.0 + (bull_rev_score * 35.0)))
            decision = f"🎯 ELITE BOTTOM-REVERSAL (LONG){squeeze_boost_label}"
            priority = 1
            is_reversal_setup = True
            is_neutral_zone = False
        elif is_top_reversal and (not is_bottom_reversal or bear_rev_score > bull_rev_score):
            h_dir = "BEARISH"
            h_conf = max(72.0, min(97.0, 62.0 + (bear_rev_score * 35.0)))
            decision = f"🎯 ELITE TOP-REVERSAL (SHORT){squeeze_boost_label}"
            priority = 1
            is_reversal_setup = True
            is_neutral_zone = False
        elif is_bull_sweep and (p_cat_live >= 0.44 or p_xgb_live >= 0.44):
            h_dir = "BULLISH"
            h_conf = max(68.0, min(96.0, h_conf + 8.0))
            decision = f"🎯 ELITE LIQUIDITY-SWEEP (LONG){squeeze_boost_label}"
            priority = 1
            is_neutral_zone = False
        elif is_bear_sweep and (p_cat_live <= 0.56 or p_xgb_live <= 0.56):
            h_dir = "BEARISH"
            h_conf = max(68.0, min(96.0, h_conf + 8.0))
            decision = f"🎯 ELITE LIQUIDITY-SWEEP (SHORT){squeeze_boost_label}"
            priority = 1
            is_neutral_zone = False
        elif is_momentum_long and not is_neutral_zone:
            h_dir = "BULLISH"
            h_conf = max(70.0, min(96.0, h_conf + 10.0))
            decision = f"🎯 ELITE MOMENTUM BREAKOUT (LONG){squeeze_boost_label}"
            priority = 1
            is_neutral_zone = False
        elif is_dip_buy:
            h_dir = "BULLISH"
            h_conf = max(60.0, h_conf)
            decision = f"🎯 ELITE DIP-BUY EXECUTE (LONG){squeeze_boost_label}"
            priority = 1
            is_neutral_zone = False
        elif is_rally_sell:
            h_dir = "BEARISH"
            h_conf = max(60.0, h_conf)
            decision = f"🎯 ELITE RALLY-SELL EXECUTE (SHORT){squeeze_boost_label}"
            priority = 1
            is_neutral_zone = False
        elif is_breakout_long and not is_neutral_zone:
            h_dir = "BULLISH"
            h_conf = max(66.0, min(95.0, h_conf + 7.0))
            decision = f"🎯 ELITE BREAKOUT EXECUTE (LONG){squeeze_boost_label}"
            priority = 1
            is_neutral_zone = False
        elif is_breakdown_short and not is_neutral_zone:
            h_dir = "BEARISH"
            h_conf = max(66.0, min(95.0, h_conf + 7.0))
            decision = f"🎯 ELITE BREAKDOWN EXECUTE (SHORT){squeeze_boost_label}"
            priority = 1
            is_neutral_zone = False
        elif is_neutral_zone:
            decision = "⚪ CONSOLIDATION (RANGE-BOUND / WAIT)"
            priority = 4
        else:
            is_macro_aligned = (h_dir == "BULLISH" and d1_macro_bull) or (h_dir == "BEARISH" and not d1_macro_bull)
            is_alpha_exception = (h_dir == "BULLISH" and (rs_btc >= 0.4 or h_conf >= 62.0))
            is_15m_scalp_exception = (horizon_key == "scalp" and h_conf >= 60.0)

            if (is_macro_aligned or is_alpha_exception) and h_conf >= (self.config['elite_conviction_threshold'] * 100.0):
                decision = f"🎯 ELITE EXECUTE {'LONG' if h_dir=='BULLISH' else 'SHORT'}{squeeze_boost_label}"
                priority = 1
            elif (is_macro_aligned or is_alpha_exception or is_15m_scalp_exception) and h_conf >= 54.0:
                decision = f"✅ STANDARD EXECUTE {'LONG' if h_dir=='BULLISH' else 'SHORT'}{squeeze_boost_label}"
                priority = 2
            elif not is_macro_aligned and not is_alpha_exception and not is_15m_scalp_exception:
                decision = "⛔ FILTER (MACRO CONFLICT)"
                priority = 3
            else:
                decision = "⛔ FILTER (LOW CONVICTION)"
                priority = 4

        # 7. Calculate True Directional TP & SL Targets (Synchronized with Final h_dir & Adaptive Multipliers)
        exp_ret_mag = max(0.002, (h_conf / 100.0) * live_norm_atr * (bars ** 0.5))
        exp_ret = exp_ret_mag if h_dir == "BULLISH" else -exp_ret_mag
        projected_target = current_price * (1.0 + exp_ret)

        risk_dist = max(1e-8, sl_mult_eff * live_raw_atr)
        live_low_c = float(live_candle['low'].values[0]) if 'low' in live_candle.columns else current_price
        live_high_c = float(live_candle['high'].values[0]) if 'high' in live_candle.columns else current_price

        # Asymmetric R:R Architecture: TP1 at 1.25x actual risk (Enforces min 0.85% gain on 15M), TP2 at 2.0x, TP3 at 3.0x
        min_tp1_dist = (0.0085 * current_price) if horizon_key == "scalp" else (1.15 * risk_dist)
        if h_dir == "BULLISH":
            sl_base = current_price - risk_dist
            if is_reversal_setup or is_bull_sweep:
                sl_p = min(sl_base, live_low_c - (0.25 * live_raw_atr))
            else:
                sl_p = sl_base
            actual_risk = max(1e-8, current_price - sl_p)
            tp1_p = current_price + max(1.20 * actual_risk, min_tp1_dist)
            tp2_p = current_price + max(2.00 * actual_risk, min_tp1_dist * 1.8)
            tp3_p = current_price + max(3.00 * actual_risk, min_tp1_dist * 2.8)
            tp4_p = current_price + max(4.00 * actual_risk, min_tp1_dist * 3.8)
            tp_p = tp4_p
        else:
            sl_base = current_price + risk_dist
            if is_reversal_setup or is_bear_sweep:
                sl_p = max(sl_base, live_high_c + (0.25 * live_raw_atr))
            else:
                sl_p = sl_base
            actual_risk = max(1e-8, sl_p - current_price)
            min_floor = max(1e-8, current_price * 0.05)
            tp1_p = max(min_floor, current_price - max(1.20 * actual_risk, min_tp1_dist))
            tp2_p = max(min_floor, current_price - max(2.00 * actual_risk, min_tp1_dist * 1.8))
            tp3_p = max(min_floor, current_price - max(3.00 * actual_risk, min_tp1_dist * 2.8))
            tp4_p = max(min_floor, current_price - max(4.00 * actual_risk, min_tp1_dist * 3.8))
            tp_p = tp4_p

        # 8. Minimum Profit Hurdle Check (Enforces >= 0.85% return on 15M to guarantee high net profit after exchange fees)
        reward_pct = (abs(tp_p - current_price) / (current_price + 1e-10)) * 100.0
        min_reward_map = {
            'scalp': 0.85,       # Minimum 0.85% profit hurdle for 15M (clears buy & sell exchange fees + delivers clean profit)
            'swing': 0.80,
            'macro': 1.80,
            'horizon_2d': 2.50,
            'horizon_3d': 3.20,
            'weekly': 5.00,
            'biweekly': 8.00,
            'monthly': 12.00
        }
        min_hurdle = min_reward_map.get(horizon_key, 0.50)
        if reward_pct < min_hurdle or abs(exp_ret * 100.0) < (0.80 if horizon_key == 'scalp' else 0.40):
            decision = f"⛔ FILTER (SUB-{min_hurdle:.1f}% RETURN / FEE DRAG)"
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

        meta_win_prob = self.meta_classifier.predict_win_probability({
            "conviction": h_conf,
            "grade": "Grade A+" if h_conf >= 78.0 else "Grade A",
            "exp_return": exp_ret,
            "horizon_key": horizon_key,
            "direction": h_dir,
            "decision": decision,
            "entry_price": current_price,
            "tp1_price": tp1_p,
            "sl_price": sl_p
        })

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
            "predicted_close_utc": trade_close_str,
            "predicted_window_str": predicted_window_str,
            "direction": h_dir,
            "conviction": h_conf,
            "meta_win_prob": meta_win_prob,
            "meta_win_prob_pct": round(meta_win_prob * 100.0, 1),
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
            if len(df) < 20:
                # Insufficient candle history for newly listed or illiquid coin
                return None
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

        # Instantaneous live ticker price directly from exchange
        live_price = self.loader.get_live_price(symbol)
        if live_price <= 0:
            live_price = float(raw_dfs['15m']['close'].iloc[-1]) if '15m' in raw_dfs else float(last_c)

        # Synchronize latest candle close across timeframes to match live tick price
        for tf_str in raw_dfs:
            try:
                raw_dfs[tf_str].at[raw_dfs[tf_str].index[-1], 'close'] = live_price
            except Exception:
                pass

        # Macro Daily Trend Check
        d1_c = raw_dfs['1d']['close'].values
        d1_ema50 = pd.Series(d1_c).ewm(span=50).mean().values[-1]
        d1_ema200 = pd.Series(d1_c).ewm(span=200).mean().values[-1]
        d1_macro_bull = (d1_c[-1] > d1_ema50) or (d1_ema50 > d1_ema200)

        # Evaluate all horizons simultaneously: Scalp (15M), Swing (1H), Macro (24H), etc.
        horizon_results = {}
        for h_key, h_cfg in self.config['horizons'].items():
            horizon_results[h_key] = self.evaluate_single_horizon(
                symbol, h_key, h_cfg, raw_dfs, tf_features, d1_macro_bull, funding_info, live_price=live_price
            )

        # Multi-Horizon Alignment & Confluence Diagnostics
        bull_horizons = [k for k, h in horizon_results.items() if h['direction'] == "BULLISH" and "CONSOLIDATION" not in h['decision']]
        bear_horizons = [k for k, h in horizon_results.items() if h['direction'] == "BEARISH" and "CONSOLIDATION" not in h['decision']]
        neutral_horizons = [k for k, h in horizon_results.items() if "CONSOLIDATION" in h['decision']]
        
        total_h = len(horizon_results)
        bull_count = len(bull_horizons)
        bear_count = len(bear_horizons)
        neutral_count = len(neutral_horizons)
        alignment_score = round(((bull_count - bear_count) / max(1, total_h)) * 100.0, 1)

        # Determine Institutional Market Phase & Radar Confluence Tag
        scalp_h = horizon_results.get('scalp', {})
        swing_h = horizon_results.get('swing', {})
        macro_h = horizon_results.get('macro', {})

        is_scalp_bottom = "BOTTOM-REVERSAL" in scalp_h.get('decision', '') or "DIP-BUY" in scalp_h.get('decision', '')
        is_scalp_top = "TOP-REVERSAL" in scalp_h.get('decision', '') or "RALLY-SELL" in scalp_h.get('decision', '')
        
        if bull_count >= 8:
            confluence_tag = f"💎 {bull_count}/{total_h} BULL EXPANSION"
            market_phase = "🚀 BULL_TREND_EXPANSION"
            consistency_index = 95.0
        elif bear_count >= 8:
            confluence_tag = f"💎 {bear_count}/{total_h} BEAR BREAKDOWN"
            market_phase = "🩸 BEAR_TREND_EXPANSION"
            consistency_index = 95.0
        elif bull_count >= 6:
            confluence_tag = f"🟢 {bull_count}/{total_h} STRONG BULLISH"
            market_phase = "🚀 BULL_TREND_EXPANSION" if macro_h.get('direction') == 'BULLISH' else "💎 DIP_ACCUMULATION"
            consistency_index = 80.0
        elif bear_count >= 6:
            confluence_tag = f"🔴 {bear_count}/{total_h} STRONG BEARISH"
            market_phase = "🩸 BEAR_TREND_EXPANSION" if macro_h.get('direction') == 'BEARISH' else "🛑 TOP_DISTRIBUTION"
            consistency_index = 80.0
        elif bull_count >= 5:
            confluence_tag = f"⚡ {bull_count}/{total_h} MODERATE BULL"
            market_phase = "⚡ MODERATE_BULLISH"
            consistency_index = 70.0
        elif bear_count >= 5:
            confluence_tag = f"⚡ {bear_count}/{total_h} MODERATE BEAR"
            market_phase = "⚡ MODERATE_BEARISH"
            consistency_index = 70.0
        elif is_scalp_bottom:
            confluence_tag = f"⚡ 15M BOTTOM REVERSAL"
            market_phase = "💎 DIP_ACCUMULATION"
            consistency_index = 75.0
        elif is_scalp_top:
            confluence_tag = f"⚡ 15M TOP EXHAUSTION"
            market_phase = "🛑 TOP_DISTRIBUTION"
            consistency_index = 75.0
        else:
            confluence_tag = f"⚪ {neutral_count}/{total_h} RANGE CONSOLIDATION"
            market_phase = "💤 RANGE_CONSOLIDATION"
            consistency_index = 50.0

        is_triple_confluence = (
            scalp_h.get('direction') == swing_h.get('direction') == macro_h.get('direction')
            and "CONSOLIDATION" not in scalp_h.get('decision', '')
        )

        # Master pick priority
        best_priority = min(h['priority'] for h in horizon_results.values())
        overall_score = sum(h['conviction'] * abs(h['exp_return']) for h in horizon_results.values())

        # 15m candle high and low for intra-candle wick verification
        live_high = max(float(raw_dfs['15m']['high'].iloc[-1]) if '15m' in raw_dfs else live_price, live_price)
        live_low = min(float(raw_dfs['15m']['low'].iloc[-1]) if '15m' in raw_dfs else live_price, live_price)

        prediction_now = datetime.now(timezone.utc)
        out_dict = {
            "symbol": symbol,
            "current_price": live_price,
            "live_high": live_high,
            "live_low": live_low,
            "horizons": horizon_results,
            "is_triple_confluence": is_triple_confluence,
            "confluence_bull_count": bull_count,
            "confluence_bear_count": bear_count,
            "confluence_neutral_count": neutral_count,
            "alignment_score": alignment_score,
            "confluence_tag": confluence_tag,
            "market_phase": market_phase,
            "consistency_index": consistency_index,
            "best_priority": best_priority,
            "overall_score": overall_score,
            "tf_metrics_summary": tf_metrics_summary,
            "server_prediction_time": prediction_now.isoformat(),
            "server_prediction_ts": int(prediction_now.timestamp()),
        }
        del raw_dfs
        del tf_features
        return out_dict

    def run_single_iteration(self):
        # Clear cache to guarantee fresh live candles from exchange
        self.loader._cache.clear()
        self._prune_model_cache()

        self.last_scan_started_ts = time.time()
        now_start = datetime.now(timezone.utc)
        mins_past = now_start.minute % 15
        secs_to_next = ((15 - mins_past) * 60) - now_start.second + 2
        if secs_to_next <= 5:
            secs_to_next += 900
        next_scan_dt = now_start + timedelta(seconds=secs_to_next)
        next_scan_ts = int(next_scan_dt.timestamp())
        next_scan_utc = next_scan_dt.strftime("%Y-%m-%d %H:%M:%S UTC")

        # Publish scanner daemon state: SCANNING
        try:
            state_path = os.path.join(self.config['app_export_dir'], "scanner_daemon_state.json")
            with open(state_path + ".tmp", "w", encoding="utf-8") as f:
                json.dump({
                    "is_scanning": True,
                    "scan_status": "SCANNING",
                    "scan_started_at": now_start.isoformat(),
                    "next_scan_time_utc": next_scan_utc,
                    "next_scan_timestamp": next_scan_ts,
                    "seconds_to_next_scan": secs_to_next,
                    "scan_interval_seconds": 900
                }, f)
            os.replace(state_path + ".tmp", state_path)
        except Exception:
            pass

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
            # Pre-fetch all Binance futures funding rates in 1 single bulk API call (~200ms)
            self.loader.preload_bulk_funding_rates()

            # Determine universe of coins to scan
            scan_mode = self.config.get("scanner_mode", "top_volume")
            if scan_mode == "top_volume":
                try:
                    symbols_to_scan = self.loader.fetch_top_volume_usdt_pairs(limit=self.config.get("scanner_top_n", 100))
                except Exception:
                    symbols_to_scan = self.config.get("scanner_symbols", [])[:self.config.get("scanner_top_n", 100)]
            elif scan_mode == "expanded_universe":
                symbols_to_scan = self.config.get("scanner_symbols", [])
            else:
                symbols_to_scan = self.config.get("scanner_symbols", [])[:self.config.get("scanner_top_n", 100)]

            print(f"\n" + "=" * 95)
            print(f" 🛰️ RUNNING CONCURRENT MULTI-HORIZON SCANNER ({len(symbols_to_scan)} {self.loader.active_exchange_id.upper()} Assets in Parallel)...")
            print("=" * 95)

            scan_deadline_seconds = 750.0
            last_partial_sync_ts = time.time()
            last_synced_count = 0
            max_threads = min(int(self.config.get('max_scan_workers', 16)), len(symbols_to_scan))
            executor = ThreadPoolExecutor(max_workers=max_threads)
            try:
                future_to_sym = {executor.submit(self.process_single_asset, sym): sym for sym in symbols_to_scan}
                for future in as_completed(future_to_sym):
                    if (time.time() - self.last_scan_started_ts) > scan_deadline_seconds:
                        print(f"[DEADLINE ⏳] Total scan time reached {scan_deadline_seconds}s limit. Safely completing cycle with {len(scanner_results)} assets.")
                        for f in future_to_sym:
                            f.cancel()
                        break
                    sym = future_to_sym[future]
                    try:
                        res = future.result(timeout=20.0)
                        if res:
                            scanner_results.append(res)
                            live_prices[sym] = res['current_price']
                            live_highs[sym] = res['live_high']
                            live_lows[sym] = res['live_low']
                            
                            # High-frequency Concurrent Streaming to Web UI and Database
                            should_sync = (
                                (len(scanner_results) - last_synced_count >= 3 and (time.time() - last_partial_sync_ts) >= 1.5)
                                or len(scanner_results) == 1
                                or len(scanner_results) == len(symbols_to_scan)
                            )
                            if should_sync:
                                elapsed_now = time.time() - self.last_scan_started_ts
                                print(f"[SCANNER 🛰️ STREAM] Streamed {len(scanner_results)}/{len(symbols_to_scan)} assets to UI (Latest: {sym}) - Elapsed: {elapsed_now:.1f}s", flush=True)
                                try:
                                    partial_sorted = sorted(scanner_results, key=lambda x: (
                                        x['best_priority'],
                                        not x['is_triple_confluence'],
                                        -x.get('consistency_index', 50.0),
                                        -abs(x.get('alignment_score', 0.0)),
                                        -x['overall_score']
                                    ))
                                    partial_signals = self.render_top_round_signals(partial_sorted, verbose=False)
                                    self.export_web_app_json(
                                        partial_sorted,
                                        deep_dive_result=None,
                                        top_signals=partial_signals,
                                        is_partial=True,
                                        total_count=len(symbols_to_scan)
                                    )
                                    if HAS_DB_SYNC:
                                        sync_files_to_db_live(force=True)
                                    last_synced_count = len(scanner_results)
                                    last_partial_sync_ts = time.time()
                                except Exception:
                                    pass
                    except Exception as e:
                        pass
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

            print(f"[SCANNER ✅] Processed active horizons for {len(scanner_results)} assets.")

            # Persist warmed model cache to disk so subsequent scans load hot in zero seconds
            try:
                if hasattr(self, 'model_cache') and self.model_cache:
                    joblib.dump(self.model_cache, self.model_cache_path + ".tmp", compress=3)
                    os.replace(self.model_cache_path + ".tmp", self.model_cache_path)
            except Exception:
                pass

            # Bulk Live Ticker Price Sync: Guarantees zero scan-latency drift on all scanned coins
            try:
                latest_all_tickers = self.loader.fetch_all_tickers(max_age_seconds=1.0)
                if latest_all_tickers:
                    for r in scanner_results:
                        s_sym = r['symbol']
                        s_raw = s_sym.replace('/', '').replace(':USDT', '')
                        fresh_p = latest_all_tickers.get(s_sym) or latest_all_tickers.get(s_raw)
                        if fresh_p and fresh_p > 0:
                            fresh_p = float(fresh_p)
                            r['current_price'] = fresh_p
                            live_prices[s_sym] = fresh_p
                            r['live_high'] = max(r.get('live_high', fresh_p), fresh_p)
                            r['live_low'] = min(r.get('live_low', fresh_p), fresh_p)
                            if 'scalp' in r.get('horizons', {}):
                                r['horizons']['scalp']['current_price'] = fresh_p
            except Exception:
                pass

            # Sort by best priority, triple confluence, consistency index, and alignment strength
            scanner_results.sort(key=lambda x: (
                x['best_priority'],
                not x['is_triple_confluence'],
                -x.get('consistency_index', 50.0),
                -abs(x.get('alignment_score', 0.0)),
                -x['overall_score']
            ))
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

            # Extract executable candidate signals from Alpha Signal Engine (Filtered to Allowed Horizons)
            allowed_pt_horizons = self.ledger.allowed_horizons
            all_candidates = []

            # 1. Direct Top Priority: Institutional Top Signals for this round
            if top_round_signals:
                for sig in top_round_signals:
                    h_k = sig.get('horizon_key', 'scalp')
                    if h_k in allowed_pt_horizons:
                        all_candidates.append((sig, h_k))

            # 2. Scanner Leaderboard candidates
            for r in scanner_results:
                for h_key, h in r['horizons'].items():
                    if h_key not in allowed_pt_horizons:
                        continue
                    dec = h.get('decision', '')
                    if "FILTER" in dec or "PAUSED" in dec or "QUARANTINED" in dec:
                        continue
                    if h['priority'] <= 2 or any(k in dec for k in ["EXECUTE", "DIP-BUY", "RALLY-SELL", "BREAKDOWN", "BREAKOUT", "MOMENTUM", "REVERSAL", "SWEEP"]):
                        # Avoid duplicating signals already added from top_round_signals
                        if not any(c[0].get('symbol') == h.get('symbol') and c[1] == h_key for c in all_candidates):
                            all_candidates.append((h, h_key))

            # Rank candidates: Prioritize Institutional Top Picks first, then Grade A+, Macro/Daily/4H setups, and Conviction/Alpha edge
            horizon_tier = {
                'monthly': 8,
                'biweekly': 7,
                'weekly': 6,
                'horizon_3d': 5,
                'horizon_2d': 4,
                'macro': 3,
                'horizon_12h': 2.5,
                'horizon_4h': 2,
                'swing': 1,
                'horizon_30m': 0.5,
                'scalp': 0
            }
            top_sigs_set = set(id(s) for s in (top_round_signals or []))
            all_candidates.sort(key=lambda x: (
                0 if id(x[0]) in top_sigs_set else 1,
                x[0].get('priority', 2),
                -horizon_tier.get(x[1], 1),
                -(x[0].get('conviction', 50.0) * abs(x[0].get('exp_return', 0.01)) + 5.0 * max(0.0, x[0].get('rs_btc', 0.0)))
            ))

            # Route top ranked signals into Order Execution Manager
            self.ledger.admit_ranked_candidates(all_candidates, signal_history=self.signal_tracker.records)
            self.ledger.render_portfolio_card()

        # 5. Persistent Signal Audit Logger: Record & Evaluate ONLY Trader Signals in CSV
        self.signal_tracker.log_top_trader_signals(top_round_signals, [p['symbol'] for p in self.ledger.data['open_positions']])
        self.signal_tracker.evaluate_signals(live_prices, live_highs, live_lows)
        self.institutional_signal_manager.evaluate_signals(live_prices, live_highs, live_lows)
        self.signal_tracker.render_performance_card()

        # 6. Export JSON Data
        self.export_web_app_json(scanner_results, deep_dive_result, top_round_signals)

        # 7. OS-Level Memory Guard: Trim Process Memory & Defragment Heap
        trim_process_memory()

    def check_open_positions_heartbeat(self):
        """Fast real-time ticker check: closes trade instantly if target touched within seconds, and refreshes BTC Shield."""
        # Dynamic BTC Market Beta Shield Heartbeat (~every 15 seconds)
        now_ts = time.time()
        if (now_ts - getattr(self, "_last_btc_heartbeat_ts", 0)) >= 15.0:
            self._last_btc_heartbeat_ts = now_ts
            try:
                btc_ticker = self.loader.fetch_ticker("BTC/USDT")
                if btc_ticker and 'last' in btc_ticker and float(btc_ticker['last']) > 0:
                    prev_regime = getattr(self, "btc_shield_regime", "")
                    self.evaluate_btc_market_regime(live_btc_price=float(btc_ticker['last']))
                    new_regime = getattr(self, "btc_shield_regime", "")
                    time_since_sync = now_ts - getattr(self, "_last_shield_file_sync_ts", 0)
                    if (prev_regime != new_regime) or (time_since_sync >= 45.0):
                        self._last_shield_file_sync_ts = now_ts
                        self._sync_live_shield_to_file()
            except Exception:
                pass

        active_paper_symbols = {p['symbol'] for p in self.ledger.data.get('open_positions', [])} if self.config.get('paper_trading', {}).get('enabled') else set()
        active_signal_symbols = set(self.institutional_signal_manager.get_active_symbols())
        all_watch_symbols = list(active_paper_symbols | active_signal_symbols)

        if not all_watch_symbols:
            return

        heartbeat_prices = {}
        for sym in all_watch_symbols:
            try:
                ticker = self.loader.fetch_ticker(sym)
                if ticker and 'last' in ticker:
                    heartbeat_prices[sym] = float(ticker['last'])
            except Exception:
                pass

        if heartbeat_prices:
            if active_paper_symbols:
                prev_open_count = len(self.ledger.data['open_positions'])
                self.ledger.on_tick(heartbeat_prices)
                self.signal_tracker.evaluate_signals(heartbeat_prices)
                new_open_count = len(self.ledger.data['open_positions'])
                if new_open_count < prev_open_count:
                    print(f"[HEARTBEAT ⚡] Intra-candle target/stop touched! Position closed in real time.")
                    self.ledger.render_portfolio_card()

            # Real-time evaluation of institutional signals
            signals_changed = self.institutional_signal_manager.evaluate_signals(heartbeat_prices)
            if signals_changed:
                self._sync_live_signals_to_file()

    def _sync_live_signals_to_file(self):
        """Real-time synchronization of active institutional signals to live_market_forecast.json & database."""
        try:
            json_path = os.path.join(self.config['app_export_dir'], "live_market_forecast.json")
            if os.path.exists(json_path):
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                data["top_round_signals"] = self.institutional_signal_manager.get_display_signals()
                data["signals_by_horizon"] = self.institutional_signal_manager.get_signals_by_horizon()

                temp_path = json_path + ".tmp"
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, default=str)
                os.replace(temp_path, json_path)

                if HAS_DB_SYNC:
                    try:
                        sync_files_to_db_live(force=True)
                    except Exception:
                        pass
        except Exception:
            pass

    def _sync_live_shield_to_file(self):
        """High-frequency real-time update of BTC Market Shield in exported JSON & database."""
        try:
            json_path = os.path.join(self.config['app_export_dir'], "live_market_forecast.json")
            if os.path.exists(json_path):
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                shield_payload = {
                    "active": self.btc_shield_active,
                    "status_code": getattr(self, "btc_shield_code", "NORMAL"),
                    "regime": getattr(self, "btc_shield_regime", "STABLE"),
                    "regime_label": getattr(self, "btc_shield_regime_label", "MARKET STABLE"),
                    "reason": self.btc_shield_reason,
                    "composite_score": getattr(self, "btc_composite_score", 0.0),
                    "btc_price": getattr(self, "btc_price", 0.0),
                    "btc_15m_change_pct": getattr(self, "btc_15m_change", 0.0),
                    "btc_1h_change_pct": getattr(self, "btc_1h_change", 0.0),
                    "btc_4h_change_pct": getattr(self, "btc_4h_change", 0.0),
                    "btc_24h_change_pct": getattr(self, "btc_24h_change", 0.0),
                    "btc_rsi_15m": getattr(self, "btc_rsi_15m", 50.0),
                    "btc_rsi_1h": getattr(self, "btc_rsi_1h", 50.0),
                    "btc_rsi_4h": getattr(self, "btc_rsi_4h", 50.0),
                    "trend_structure": getattr(self, "btc_trend_structure", "Neutral / Stable"),
                    "is_squeeze": getattr(self, "btc_is_squeeze", False),
                    "bbw_15m_pct": getattr(self, "btc_bbw_15m", 0.0),
                    "vol_ratio": getattr(self, "btc_vol_ratio", 1.0),
                    "altcoin_longs_allowed": not self.btc_shield_active,
                }
                data["btc_market_shield"] = shield_payload
                temp_path = json_path + ".tmp"
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, default=str)
                os.replace(temp_path, json_path)

                if HAS_DB_SYNC:
                    sync_files_to_db_live()
        except Exception:
            pass

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

                # Real-Time Heartbeat Loop: Monitors prices every 3-4s between scans
                hb_secs = int(self.config.get('heartbeat_interval_seconds', 4))
                print(f"[DAEMON] ⏳ Monitoring active trades in real time every {hb_secs}s (Next full scan: {next_run.strftime('%H:%M:%S UTC')})...")
                while datetime.now(timezone.utc) < next_run:
                    self.check_open_positions_heartbeat()
                    time.sleep(hb_secs)

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

        # Display Top 5 Ranked Assets in console (complete 150-asset matrix synced to Web UI)
        df_scan = pd.DataFrame(table_rows[:5])
        print(f"\n[LEADERBOARD 🛰️] Top 5 Market Opportunities (Full 150-Asset Matrix on Web UI):")
        print(tabulate(df_scan, headers="keys", tablefmt="simple", showindex=False) + "\n")

    def render_top_round_signals(self, scanner_results: list, deep_dive_result: dict = None, verbose: bool = True) -> list:
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
        
        min_meta_prob = sig_cfg.get('min_meta_probability', 0.65)
        ban_parabolic_shorts = sig_cfg.get('ban_parabolic_shorts', True)
        min_scalp_gain = sig_cfg.get('min_scalp_gain_pct', 0.85)
        min_swing_gain = sig_cfg.get('min_swing_gain_pct', 0.85)
        asset_cooldown_sec = sig_cfg.get('asset_cooldown_minutes', 60) * 60

        active_paper_symbols = {p['symbol'] for p in self.ledger.data.get('open_positions', [])}
        active_mgr_symbols = set(self.institutional_signal_manager.get_active_symbols())
        all_signals = []
        seen_pairs = set()
        now_ts = time.time()

        cooldown_map = {
            'scalp': 1800,       # 30 mins
            'swing': 5400,       # 90 mins
            'macro': 14400,      # 4 hours
            'horizon_2d': 28800, # 8 hours
            'horizon_3d': 43200, # 12 hours
            'weekly': 86400,     # 24 hours
            'biweekly': 172800,  # 48 hours
            'monthly': 345600    # 4 days
        }

        for r in source_results:
            sym = r['symbol']
            tf_summary = r.get('tf_metrics_summary', [])
            is_triple = r.get('is_triple_confluence', False)
            
            # Compute 24h percentage change from 1D / 4H charts if available
            change_24h_pct = 0.0
            rsi_1h_val = 50.0
            for tf_item in tf_summary:
                if tf_item.get('Chart') in ['1D', '4H', '1H']:
                    try:
                        p_str = str(tf_item.get('Price', '')).replace('$', '').replace(',', '')
                        rsi_raw = str(tf_item.get('RSI', '50.0'))
                        if rsi_raw != 'N/A':
                            rsi_1h_val = float(rsi_raw)
                    except Exception:
                        pass

            for h_key in list(self.config.get('horizons', {}).keys()):
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
                exp_ret = float(h.get('exp_return', 0.0))
                
                curr_p = float(h.get('current_price', r.get('current_price', 0.0)) or 1.0)
                tp1_p = float(h.get('tp1_price', h.get('tp_price', curr_p)) or curr_p)
                sl_p = float(h.get('sl_price', curr_p) or curr_p)
                tp_pct = abs(tp1_p - curr_p) / max(1e-8, curr_p) * 100.0

                # --------------------------------------------------------------
                # 🛑 STRUCTURAL HEURISTIC CIRCUIT BREAKERS
                # --------------------------------------------------------------
                # 1. Parabolic Short Ban (Prevents catastrophic squeeze traps)
                is_parabolic_short = False
                if ban_parabolic_shorts and direction in ["BEARISH", "SHORT"]:
                    if rsi_1h_val >= 70.0 or rs_val >= 2.5:
                        is_parabolic_short = True
                        decision = f"🛡️ SUPPRESSED (PARABOLIC MOMENTUM SQUEEZE RISK)"
                        prio = 5

                # 2. Fee Hurdle: Filter out micro-targets where fees eat the profit (>= 0.40% minimum net profit hurdle)
                is_fee_drag_rejected = False
                min_return_hurdle = sig_cfg.get('min_expected_return_pct', 0.40)
                if tp_pct < min_return_hurdle or abs(exp_ret * 100.0) < min_return_hurdle:
                    is_fee_drag_rejected = True
                    decision = "⛔ FILTER (SUB-0.4% RETURN / FEE DRAG)"
                elif h_key == 'scalp' and tp_pct < min_scalp_gain:
                    is_fee_drag_rejected = True
                elif h_key == 'swing' and tp_pct < min_swing_gain:
                    is_fee_drag_rejected = True

                # 3. 2-Strike Asset Blacklist Quarantine Check & Deduplication
                is_quarantined, quar_reason = self.signal_tracker.is_asset_quarantined(sym)
                last_sym_time = self.symbol_last_signal_time.get(sym, 0)
                is_already_active = sym in active_mgr_symbols
                is_asset_locked = (((now_ts - last_sym_time) < asset_cooldown_sec and not is_triple) or is_quarantined) if not is_already_active else is_quarantined
                if is_quarantined:
                    decision = f"⛔ {quar_reason}"
                    prio = 5

                # 4. BTC Shield Check (with Alpha Decoupling Exception)
                is_shield_blocked = False
                is_alpha_decoupled = (direction == "BULLISH" and rs_val >= 0.8 and conv >= 62.0)
                is_systemic_crash = getattr(self, 'btc_shield_code', '') in ["ALERT_DUMP", "DUMP"]
                if self.btc_shield_active and sym != "BTC/USDT" and direction == "BULLISH":
                    if is_systemic_crash or not is_alpha_decoupled:
                        is_shield_blocked = True
                        decision = f"🛡️ PAUSED (BTC BETA SHIELD: {self.btc_shield_reason})"
                        prio = 5

                # ⏱️ Signal Cooldown Check
                last_sig_time = self.signal_cooldown_tracker.get(pair_key, 0)
                is_in_cooldown = (now_ts - last_sig_time) < cooldown_map.get(h_key, 1800)

                # 💎 Grade Classification
                is_exec_decision = any(k in decision for k in ["EXECUTE", "DIP-BUY", "RALLY-SELL", "BREAKDOWN", "BREAKOUT", "MOMENTUM", "REVERSAL", "SWEEP"])
                is_a_plus_candidate = (
                    (conv >= a_plus_cutoff or (is_triple and conv >= 70.0)) and
                    is_exec_decision and
                    not is_shield_blocked and
                    not is_parabolic_short and
                    not is_fee_drag_rejected and
                    not is_quarantined and
                    (rs_val >= -0.2 if direction == "BULLISH" else rs_val <= 0.2) and
                    elite_prec >= 0.55
                )

                if is_a_plus_candidate:
                    grade = "💎 Grade A+"
                    grade_tier = 1
                    tier_label = "ELITE CONFLUENCE"
                elif (conv >= a_cutoff and prio <= 2 and not is_shield_blocked and not is_parabolic_short and not is_quarantined) or (is_exec_decision and not is_shield_blocked and not is_parabolic_short and not is_quarantined):
                    grade = "🟢 Grade A"
                    grade_tier = 2
                    tier_label = "HIGH CONVICTION"
                elif conv >= b_cutoff and prio <= 3 and not is_shield_blocked and not is_quarantined:
                    grade = "🟡 Grade B+"
                    grade_tier = 3
                    tier_label = "ACTIONABLE MOMENTUM"
                else:
                    grade = "⚪ Grade C"
                    grade_tier = 4
                    tier_label = "WATCHLIST / DEFENSIVE"

                paper_status = "🟢 ACTIVE (PAPER TRADED)" if sym in active_paper_symbols else "📡 LIVE SCAN SIGNAL"

                # Construct Candidate Setup Object
                candidate_obj = {
                    "symbol": sym,
                    "horizon_key": h_key,
                    "horizon_name": h.get('horizon_name', h_key.upper()),
                    "priority": prio,
                    "conviction": conv,
                    "grade": grade,
                    "grade_tier": grade_tier,
                    "tier_label": tier_label,
                    "direction": direction,
                    "decision": decision,
                    "current_price": curr_p,
                    "entry_price": curr_p,
                    "tp1_price": tp1_p,
                    "tp2_price": float(h.get('tp2_price', h.get('tp_price', curr_p)) or curr_p),
                    "tp3_price": float(h.get('tp3_price', h.get('tp_price', curr_p)) or curr_p),
                    "tp_price": float(h.get('tp_price', curr_p) or curr_p),
                    "sl_price": sl_p,
                    "exp_return": exp_ret,
                    "projected_target": h.get('projected_target', h.get('tp_price', curr_p)),
                    "elite_precision": elite_prec,
                    "duration_label": h.get('duration_label', 'N/A'),
                    "predicted_window_str": h.get('predicted_window_str', 'N/A'),
                    "predicted_close_utc": h.get('predicted_close_utc', h.get('trade_close_str', 'N/A')),
                    "trade_close_str": h.get('trade_close_str', 'N/A'),
                    "is_triple_confluence": is_triple,
                    "is_in_cooldown": is_in_cooldown,
                    "is_asset_locked": is_asset_locked,
                    "is_parabolic_short": is_parabolic_short,
                    "is_fee_drag_rejected": is_fee_drag_rejected,
                    "is_shield_blocked": is_shield_blocked,
                    "paper_trading_status": paper_status,
                    "card": h.get('pro_signal_text', ''),
                    "tf_summary": tf_summary
                }

                # 🧠 ML SECONDARY META-LABELER WIN PROBABILITY SCORING
                meta_win_prob = self.meta_classifier.predict_win_probability(candidate_obj)
                candidate_obj['meta_win_prob'] = meta_win_prob
                
                # Composite Score combining Conviction, ML Meta-Score, Triple Confluence & Yield
                triple_bonus = 30.0 if is_triple else 0.0
                exec_bonus = 20.0 if is_exec_decision else 0.0
                composite_score = (conv * 0.4) + (meta_win_prob * 100.0 * 0.4) + (max(0.0, rs_val) * 4.0) + triple_bonus + exec_bonus + (abs(exp_ret) * 50.0)
                candidate_obj['composite_score'] = composite_score

                all_signals.append(candidate_obj)

        # Sort candidate setups: Grade Tier first, Meta Win Probability second, Composite score third
        all_signals.sort(key=lambda x: (x['grade_tier'], -x['meta_win_prob'], -x['composite_score'], -x['conviction']))

        # Filter candidates applying ML Meta-Probability Gate & Grade A+ Quality Enforcement
        qualified_pool = []
        for s in all_signals:
            if s['is_shield_blocked'] or s['is_parabolic_short'] or s['is_fee_drag_rejected']:
                continue
            # Pass Grade A+ (tier 1) or Grade A (tier 2) with conviction >= 72% and meta_win_prob >= 0.70
            # Strictly discard Grade B+ and Grade C to eliminate negative alpha drag
            is_tier1_ok = (s['grade_tier'] == 1 and (s['meta_win_prob'] >= 0.65 or s['conviction'] >= 75.0))
            is_tier2_ok = (s['grade_tier'] == 2 and s['conviction'] >= 72.0 and s['meta_win_prob'] >= 0.70)
            if (is_tier1_ok or is_tier2_ok) and not s['is_in_cooldown'] and not s['is_asset_locked']:
                qualified_pool.append(s)

        pool_for_selection = qualified_pool if len(qualified_pool) >= min_sig else all_signals

        # Horizon-Separated High-Potential Signal Buckets (>= 0.85% Return for Scalp & Quality Filter Enforcement)
        horizon_bucket_defs = [
            {"key": "scalp", "tag": "15M", "label": "⚡ Scalp (15M)", "min_return": 0.85},
            {"key": "horizon_30m", "tag": "30M", "label": "⏱️ 30M", "min_return": 0.85},
            {"key": "swing", "tag": "1H", "label": "🌊 Swing (1H)", "min_return": 0.85},
            {"key": "horizon_4h", "tag": "4H", "label": "⏳ Intraday (4H)", "min_return": 1.20},
            {"key": "horizon_12h", "tag": "12H", "label": "🌗 12H", "min_return": 1.50},
            {"key": "macro", "tag": "24H", "label": "🚀 Macro (24H)", "min_return": 1.80},
            {"key": "horizon_4d", "tag": "4D", "label": "📅 4D", "min_return": 2.50},
            {"key": "weekly", "tag": "7D", "label": "🗓️ Weekly (7D)", "min_return": 4.00},
            {"key": "biweekly", "tag": "15D", "label": "📆 15D", "min_return": 6.00},
            {"key": "monthly", "tag": "30D", "label": "🪐 Monthly (30D)", "min_return": 8.00}
        ]

        signals_by_horizon = {b["tag"]: [] for b in horizon_bucket_defs}
        selected_signals = []
        selected_symbols_horizon = set()

        for b in horizon_bucket_defs:
            h_k = b["key"]
            h_tag = b["tag"]
            min_ret = b["min_return"]

            # Filter candidates for this exact horizon with Quality Filter Gate
            h_candidates = [
                s for s in all_signals
                if (s['horizon_key'] == h_k or h_tag.lower() in s['horizon_key'].lower())
                and not s['is_shield_blocked']
                and not s['is_parabolic_short']
                and not s['is_fee_drag_rejected']
                and not s.get('is_asset_locked', False)
                and abs(s.get('exp_return', 0.0) * 100.0) >= min_ret
            ]

            # Priority 1: High Conviction Grade A+ / Grade A setups
            tier_high = [
                s for s in h_candidates
                if ((s['grade_tier'] == 1 and (s['meta_win_prob'] >= 0.60 or s['conviction'] >= 70.0)) or
                    (s['grade_tier'] == 2 and s['conviction'] >= 65.0 and s['meta_win_prob'] >= 0.60))
            ]
            pool = tier_high if tier_high else [s for s in h_candidates if s['conviction'] >= 52.0]
            pool.sort(key=lambda x: (x['grade_tier'], -x['meta_win_prob'], -x['composite_score'], -x['conviction']))

            # Deduplicate by symbol within this horizon: exactly 1 setup per coin
            seen_in_h = set()
            top_h_picks = []
            for pick in pool:
                clean_sym = self.institutional_signal_manager._clean_sym(pick['symbol'])
                if clean_sym not in seen_in_h:
                    seen_in_h.add(clean_sym)
                    top_h_picks.append(pick)
                if len(top_h_picks) >= 2:
                    break

            for pick in top_h_picks:
                pick['horizon_tag'] = h_tag
                if (pick['symbol'], h_k) not in selected_symbols_horizon:
                    selected_signals.append(pick)
                    selected_symbols_horizon.add((pick['symbol'], h_k))

        # Always upsert selected candidate signals into ActiveInstitutionalSignalManager
        if selected_signals:
            self.institutional_signal_manager.upsert_signals(selected_signals)

        # Synchronize signals_by_horizon authoritative state from signal manager
        self.signals_by_horizon = self.institutional_signal_manager.get_signals_by_horizon()

        # Update Cooldown Timestamps for Dispatched Signals (Final round only)
        if verbose:
            for sig in selected_signals:
                self.signal_cooldown_tracker[(sig['symbol'], sig['horizon_key'])] = now_ts
                self.symbol_last_signal_time[sig['symbol']] = now_ts

        # Market Regime Diagnostic & Beta Shield Banner
        count_a_plus = sum(1 for s in all_signals if s['grade_tier'] == 1 and s.get('meta_win_prob', 0) >= min_meta_prob)
        count_a = sum(1 for s in all_signals if s['grade_tier'] == 2 and s.get('meta_win_prob', 0) >= min_meta_prob)
        count_b = sum(1 for s in all_signals if s['grade_tier'] == 3)
        
        if self.btc_shield_active:
            regime_tag = f"🛡️ BTC BETA SHIELD ACTIVE ({self.btc_shield_reason} - Altcoin Longs Suppressed)"
        elif count_a_plus >= 2 or (count_a_plus + count_a) >= 4:
            regime_tag = "🚀 HIGH-CONVICTION TREND EXPANSION (Multiple Grade A+/A Setups Firing)"
        elif (count_a_plus + count_a) >= 1:
            regime_tag = "⚡ SELECTIVE OPPORTUNITY REGIME (Targeted Institutional Edge Active)"
        else:
            regime_tag = "🛡️ DEFENSIVE CHOP / CAPITAL PRESERVATION (Showing Highest-Ranked Defensive Setup)"

        if verbose:
            print("\n" + "=" * 145)
            print(f" 🎯 DYNAMIC QUANTITATIVE SIGNAL ENGINE ({len(selected_signals)} SIGNALS ACROSS HORIZONS THIS ROUND)")
            print(f" Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} | Scanned: {len(source_results)} Pairs across 15M, 1H, 4H, 24H, 7D, 30D")
            active_horizons = [f"{k} ({len(v)})" for k, v in signals_by_horizon.items() if len(v) > 0]
            print(f" Active Horizons Firing: {', '.join(active_horizons) if active_horizons else 'None (Defensive)'} | Regime: {regime_tag}")
            if self.btc_shield_active:
                print(f" ⚠️  CIRCUIT BREAKER: {self.btc_shield_reason} -> Prioritizing Shorts & BTC Hedges.")
            print("=" * 145)

            rank_medals = ["🥇 TOP PICK (#1)", "🥈 RUNNER UP (#2)", "🥉 BRONZE (#3)", "🎯 PICK (#4)", "🎯 PICK (#5)"]
            summary_rows = []
            for idx, sig in enumerate(selected_signals):
                rank_str = rank_medals[idx] if idx < len(rank_medals) else f"#{idx+1}"
                dir_str = "🟢 LONG" if sig['direction'] in ["BULLISH", "LONG"] else "🔴 SHORT"
                exp_ret = sig.get('exp_return', 0.0)
                ret_str = f"{'+' if exp_ret >= 0 else ''}{exp_ret*100:.2f}%"
                meta_p_str = f"{sig.get('meta_win_prob', 0.70)*100:.1f}%"

                summary_rows.append({
                    "Rank": rank_str,
                    "Quality Grade": f"{sig['grade']}\n({sig['tier_label']})",
                    "Asset": sig['symbol'],
                    "Horizon": sig['horizon_name'],
                    "Side": dir_str,
                    "Conviction": f"{sig['conviction']:.1f}%\n{sig['decision']}",
                    "ML Win Prob": f"🧠 {meta_p_str}",
                    "Entry Price": fmt_p(sig['entry_price']),
                    "TP1 / TP2 Target": f"TP1: {fmt_p(sig['tp1_price'])}\nTP2: {fmt_p(sig['tp2_price'])}",
                    "Stop-Loss": fmt_p(sig['sl_price']),
                    "Exp. Return": ret_str,
                    "Paper Status": sig['paper_trading_status']
                })

            df_selected = pd.DataFrame(summary_rows)
            print(tabulate(df_selected, headers="keys", tablefmt="simple", showindex=False))
            print("=" * 145 + "\n")

        return self.institutional_signal_manager.get_display_signals()

    # Backwards compatibility alias
    def render_professional_trading_signals(self, scanner_results: list):
        return self.render_top_round_signals(scanner_results)

    def render_multi_horizon_deep_dive(self, data: dict):
        sym = data['symbol']
        print(f"[DEEP DIVE 🔬] {sym} Multi-Horizon Analysis Complete (Triple Confluence: {'💎 YES' if data['is_triple_confluence'] else '⚡ INDEPENDENT'})\n")

    def export_web_app_json(self, scanner_results: list, deep_dive_result: dict = None, top_signals: list = None, is_partial: bool = False, total_count: int = 200):
        now_utc = datetime.now(timezone.utc)
        now_iso = now_utc.isoformat()
        now_ts = int(now_utc.timestamp())

        # Ensure all items in scanner_results have server_prediction_time
        for r in scanner_results:
            if "server_prediction_time" not in r:
                r["server_prediction_time"] = now_iso
                r["server_prediction_ts"] = now_ts

        payload = {
            "timestamp": now_iso,
            "server_prediction_time": now_iso,
            "server_prediction_ts": now_ts,
            "strategy": "Multi-Horizon Quantitative Engine (V16.0)",
            "btc_market_shield": {
                "active": self.btc_shield_active,
                "status_code": getattr(self, "btc_shield_code", "NORMAL"),
                "regime": getattr(self, "btc_shield_regime", "STABLE"),
                "regime_label": getattr(self, "btc_shield_regime_label", "MARKET STABLE"),
                "reason": self.btc_shield_reason,
                "composite_score": getattr(self, "btc_composite_score", 0.0),
                "btc_price": getattr(self, "btc_price", 0.0),
                "btc_15m_change_pct": getattr(self, "btc_15m_change", 0.0),
                "btc_1h_change_pct": getattr(self, "btc_1h_change", 0.0),
                "btc_4h_change_pct": getattr(self, "btc_4h_change", 0.0),
                "btc_24h_change_pct": getattr(self, "btc_24h_change", 0.0),
                "btc_rsi_15m": getattr(self, "btc_rsi_15m", 50.0),
                "btc_rsi_1h": getattr(self, "btc_rsi_1h", 50.0),
                "btc_rsi_4h": getattr(self, "btc_rsi_4h", 50.0),
                "trend_structure": getattr(self, "btc_trend_structure", "Neutral / Stable"),
                "is_squeeze": getattr(self, "btc_is_squeeze", False),
                "bbw_15m_pct": getattr(self, "btc_bbw_15m", 0.0),
                "vol_ratio": getattr(self, "btc_vol_ratio", 1.0),
                "altcoin_longs_allowed": not self.btc_shield_active,
            },
            "top_round_signals": self.institutional_signal_manager.get_display_signals() or top_signals or [],
            "signals_by_horizon": self.institutional_signal_manager.get_signals_by_horizon(),
            "scanner_leaderboard": (lambda: [
                self.master_matrix_universe.update({r['symbol']: r}) for r in scanner_results if isinstance(r, dict) and 'symbol' in r
            ] and sorted(list(self.master_matrix_universe.values()), key=lambda x: (
                x.get('best_priority', 4),
                not x.get('is_triple_confluence', False),
                -x.get('consistency_index', 50.0),
                -abs(x.get('alignment_score', 0.0)),
                -x.get('overall_score', 0.0)
            )) if getattr(self, 'master_matrix_universe', None) else scanner_results)(),
            "deep_dive": deep_dive_result,
            "paper_portfolio": self.ledger.data
        }
        json_path = os.path.join(self.config['app_export_dir'], "live_market_forecast.json")
        temp_path = json_path + ".tmp"
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=4, default=str)
        os.replace(temp_path, json_path)

        if not is_partial:
            print(f"📦 Web-App Ready JSON Data Exported to: {os.path.abspath(json_path)}\n")

            # Publish scanner daemon state: IDLE with authoritative next 15-minute prediction timestamp
            try:
                now_done = datetime.now(timezone.utc)
                scan_duration = round(time.time() - getattr(self, "last_scan_started_ts", time.time()), 2)
                mins_past = now_done.minute % 15
                secs_to_next = ((15 - mins_past) * 60) - now_done.second + 2
                if secs_to_next <= 5:
                    secs_to_next += 900
                next_scan_dt = now_done + timedelta(seconds=secs_to_next)
                next_scan_ts = int(next_scan_dt.timestamp())
                next_scan_utc = next_scan_dt.strftime("%Y-%m-%d %H:%M:%S UTC")

                state_path = os.path.join(self.config['app_export_dir'], "scanner_daemon_state.json")
                with open(state_path + ".tmp", "w", encoding="utf-8") as f:
                    json.dump({
                        "is_scanning": False,
                        "scan_status": "IDLE",
                        "scanned_assets_count": len(scanner_results),
                        "total_assets_count": len(scanner_results),
                        "last_scan_completed_at": now_done.isoformat(),
                        "last_scan_completed_at_utc": now_done.strftime("%Y-%m-%d %H:%M:%S UTC"),
                        "last_scan_duration_seconds": scan_duration,
                        "next_scan_time_utc": next_scan_utc,
                        "next_scan_timestamp": next_scan_ts,
                        "seconds_to_next_scan": secs_to_next,
                        "scan_interval_seconds": 900
                    }, f)
                os.replace(state_path + ".tmp", state_path)
            except Exception:
                pass
        else:
            # Partial streaming update: update daemon state with current scanned asset count
            try:
                state_path = os.path.join(self.config['app_export_dir'], "scanner_daemon_state.json")
                if os.path.exists(state_path):
                    with open(state_path, "r", encoding="utf-8") as f:
                        curr_state = json.load(f)
                    curr_state["scanned_assets_count"] = len(scanner_results)
                    curr_state["total_assets_count"] = total_count
                    with open(state_path + ".tmp", "w", encoding="utf-8") as f:
                        json.dump(curr_state, f)
                    os.replace(state_path + ".tmp", state_path)
            except Exception:
                pass


if __name__ == "__main__":
    engine = HybridQuantEngine(CONFIG)
    engine.run()
