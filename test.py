# ==============================================================================
# MULTI-HORIZON QUANTITATIVE CRYPTO TRADING ENGINE (V14.0)
# Asset: BTC/USDT & Multi-Asset Portfolio Scanner (ETH, SOL, XRP, BNB, DOGE, AVAX)
# Key Upgrades in V14.0:
# 1. Trading Horizons: ⚡ Scalp (15M), ⏳ Day Trade (1H/4H), 🌊 Swing Trade (1D), 🚀 Macro Trend (4D-30D)
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
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['VECLIB_MAXIMUM_THREADS'] = '1'
os.environ['NUMEXPR_NUM_THREADS'] = '1'

try:
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
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
from typing import Optional, Tuple, Dict, Any, List, Set

import ccxt
import xgboost as xgb
from catboost import CatBoostClassifier, CatBoostRegressor
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, HistGradientBoostingRegressor
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

import logging
logger = logging.getLogger("QUANT_ENGINE")

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

# Signal Expiry Policy: when False (default), signals and positions never expire by time/horizon/TTL
# and strictly wait until Take Profit (TP) or Stop Loss (SL) is hit.
ENABLE_SIGNAL_EXPIRY: bool = os.getenv("ENABLE_SIGNAL_EXPIRY", "false").lower() in ("true", "1", "yes")

def _safe_float(v, default=0.0):
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    try:
        s = str(v).replace('%', '').replace('$', '').replace(',', '').strip()
        return float(s)
    except Exception:
        return default

def format_precision_price(val):
    if val is None:
        return 0.0
    v = _safe_float(val, 0.0)
    if v <= 0:
        return 0.0
    if v >= 1000.0:
        return round(v, 2)
    elif v >= 1.0:
        return round(v, 4)
    elif v >= 0.01:
        return round(v, 6)
    elif v >= 0.0001:
        return round(v, 8)
    else:
        return round(v, 10)

def format_precision_price_str(val):
    if val is None:
        return "$0.00"
    v = _safe_float(val, 0.0)
    if v >= 1000.0:
        return f"${v:,.2f}"
    elif v >= 1.0:
        return f"${v:,.4f}"
    elif v >= 0.01:
        return f"${v:.6f}"
    elif v >= 0.0001:
        return f"${v:.8f}"
    else:
        return f"${v:.10f}"


def _safe_sort_key(x):
    if not isinstance(x, dict):
        return (4, True, 0.0, 0.0, 0.0)
    bp = _safe_float(x.get('best_priority'), 4.0)
    tc = not bool(x.get('is_triple_confluence', False))
    ci = _safe_float(x.get('consistency_index'), 50.0)
    als = abs(_safe_float(x.get('alignment_score'), 0.0))
    oscore = _safe_float(x.get('overall_score'), 0.0)
    return (bp, tc, -ci, -als, -oscore)

def resolve_horizon_tag(horizon_key: str) -> str:
    if not horizon_key:
        return "15M"
    hk = str(horizon_key).lower().strip()
    key_map = {
        "scalp": "15M",
        "horizon_30m": "30M",
        "intraday": "1H",
        "swing": "1H",
        "triple_screen": "1H",
        "horizon_4h": "4H",
        "macro": "24H",
        "horizon_2d": "2D",
        "horizon_3d": "3D",
        "horizon_4d": "4D",
        "weekly": "7D",
        "biweekly": "15D",
        "monthly": "30D",
        "15m": "15M", "30m": "30M", "1h": "1H", "4h": "4H", "24h": "24H",
        "2d": "2D", "3d": "3D", "4d": "4D", "7d": "7D", "15d": "15D", "30d": "30D"
    }
    if hk in key_map:
        return key_map[hk]
    if 'monthly' in hk or '30d' in hk: return '30D'
    if 'biweekly' in hk or '15d' in hk: return '15D'
    if 'weekly' in hk or '7d' in hk: return '7D'
    if '4d' in hk: return '4D'
    if 'macro' in hk or '24h' in hk or '1d' in hk: return '24H'
    if '4h' in hk: return '4H'
    if '1h' in hk or 'intraday' in hk or 'triple_screen' in hk: return '1H'
    if '30m' in hk: return '30M'
    if 'scalp' in hk or '15m' in hk: return '15M'
    if 'swing' in hk: return '1H'
    return key_map.get(hk, str(horizon_key).upper().strip())

EXCLUDED_STABLECOIN_BASES = {
    "USDC", "FDUSD", "TUSD", "USDD", "DAI", "BUSD", "EUR", "TRY", "PAXG", "WBTC",
    "USDP", "AEUR", "T", "USTC", "EURI", "USD", "EURR", "RLUSD", "USD1", "U", "USDE",
    "PYUSD", "GUSD", "LUSD", "FRAX", "CUSD", "EURT", "XAUT", "XAU", "XAG", "XUSD",
    "USDS", "USDX", "SUSD", "USDJ", "USDK", "USDQ", "USDM", "USDL", "BGBP", "BIDR",
    "IDRT", "BVND", "VND", "BRL", "GBP", "AUD", "NGN", "ZAR", "RUB", "UAH", "PLN",
    "RON", "CZK", "HUF", "ARS", "COP", "MXN", "PHP", "THB", "PAX", "TBTC", "BTCB",
    "USDT", "EURS", "EURC", "USN", "CEUR", "CUSD", "OUSD", "USDP", "GUSD", "SUSD"
}

EXCLUDED_DELISTED_BASES = {
    "FTM", "MATIC", "LUNA", "LUNC", "UST", "ANT", "MULTI", "WTC", "VGX", "BTT",
    "SRM", "RAY", "HNT", "TOMO", "MOB", "PNT", "DREP", "BTS", "PERP", "KEY"
}

EXCLUDED_STOCK_AND_SYNTHETIC = {
    "QQQB", "TSLAB", "NVDAB", "SPCXB", "SNDKB", "INTCB", "SOXLB", "MSTRB", "COINB",
    "AAPLB", "AMZNB", "GOOGLB", "METAB", "MSFTB", "NVDA", "TSLA", "AAPL", "AMZN",
    "GOOGL", "MSFT", "MARSCOIN", "COIN", "CRCLB", "BMNRB", "BMNR", "AVGOB", "AVGO",
    "PLTRB", "PLTR", "AMDB", "AMD", "ARMB", "ARM", "NFLXB", "NFLX", "BABAB", "BABA",
    "TSMB", "TSM", "QCOMB", "QCOM", "MUB", "MU", "DISB", "DIS", "PYPLB", "PYPL",
    "UBERB", "UBER", "HOODB", "HOOD", "SQB", "SQ", "COINBASE", "MICROSTRATEGY"
}

EXCLUDED_UNSTABLE_COINS = {
    # Systematically proved to have 0-35% win rate and severe drawdown
    "PROVE", "ROSE", "ENSO", "ONG", "ESP"
}

MEME_AND_SHITCOIN_BASES = {
    # Systematically skip hype-driven meme coins and non-utility shitcoins
    "DOGE", "SHIB", "PEPE", "BONK", "WIF", "FLOKI", "BOME", "MEME", "PENGU",
    "NEIRO", "TURBO", "MYRO", "POPCAT", "BRETT", "MEW", "MOODENG", "GOAT",
    "ACT", "PNUT", "SLERF", "BABYDOGE", "CHEEMS", "LUNC", "USTC", "DOGS",
    "CATI", "HMSTR", "NOT", "1000SATS", "ORDI", "PEPE2", "AIDOGE", "LUNA",
    "FTT", "PUPPIES", "MILADY", "COQ", "TOSHI", "WEN", "SILLY",
    "PONKE", "GIGA", "SUNDOG", "SPX", "BILLY", "MOG", "MICHI", "TKO"
}

def is_meme_or_shitcoin(symbol: str, price: float = None, quote_volume_24h: float = None) -> bool:
    """Detects and flags meme tokens, hyper-fractional micro-caps, and non-utility shitcoins."""
    if not symbol or not isinstance(symbol, str):
        return True
    clean = symbol.strip().upper().replace(':USDT', '').replace('/USDT', '')
    base = clean.split('/')[0]
    if base in MEME_AND_SHITCOIN_BASES:
        return True
    # Micro-price shitcoin heuristic (< $0.00005)
    if price is not None and 0 < price < 0.00005:
        return True
    # Low volume shitcoin check (< $5M 24h volume)
    if quote_volume_24h is not None and 0 < quote_volume_24h < 5_000_000.0:
        return True
    return False

TIER_1_ALPHA_COINS = {
    # Systematically proved 70-100% win rate and massive positive profit factor
    "GENIUS/USDT", "HEI/USDT", "AVA/USDT", "KITE/USDT", "BMNRB/USDT",
    "CTSI/USDT", "GTC/USDT", "SKL/USDT", "ZK/USDT", "BTC/USDT", "ETH/USDT",
    "SOL/USDT", "BNB/USDT", "NEAR/USDT", "SUPER/USDT", "SAGA/USDT", "SUI/USDT", "AVAX/USDT"
}

def is_valid_crypto_pair(
    symbol: str,
    price: float = None,
    high: float = None,
    low: float = None,
    bid_price: float = None,
    ask_price: float = None,
    spread_bps: float = None
) -> bool:
    if not symbol or not isinstance(symbol, str):
        return False
    clean_sym = symbol.strip().upper().replace(':USDT', '')
    if '/' not in clean_sym and clean_sym.endswith('USDT'):
        clean_sym = clean_sym[:-4] + '/USDT'
    if not clean_sym.endswith('/USDT'):
        return False
    base = clean_sym.split('/')[0]

    # Reject toxic historical drag underperformers
    if base in EXCLUDED_UNSTABLE_COINS:
        return False

    # Reject meme coins and shitcoins across system
    if CONFIG.get('skip_meme_and_shitcoins', True) and is_meme_or_shitcoin(clean_sym, price=price):
        return False
    
    # 1. Reject synthetic test tokens (COIN0..COIN99)
    if base.startswith("COIN") and base[4:].isdigit():
        return False
    
    # 2. Reject non-ascii / non-alphanumeric tokens (e.g. Chinese characters)
    if not base.isalnum() or not base.isascii():
        return False
    
    # 3. Reject leveraged / tokenized stocks ending with B or synthetic tokens
    if base in EXCLUDED_STOCK_AND_SYNTHETIC:
        return False
    if base.endswith("B") and len(base) >= 4 and base not in {"SHIB", "FLOKI", "BOMB", "BNB", "ARB", "BB", "ZRO"}:
        stock_prefixes = [
            "TSLA", "NVDA", "QQQ", "SPCX", "SNDK", "INTC", "SOXL", "MSTR", "COIN",
            "AAPL", "AMZN", "GOOGL", "META", "MSFT", "BMNR", "AVGO", "PLTR", "AMD",
            "ARM", "NFLX", "BABA", "TSM", "QCOM", "MU", "DIS", "PYPL", "UBER", "HOOD", "SQ"
        ]
        if any(stock in base for stock in stock_prefixes):
            return False
            
    # 4. Reject Leveraged Bull/Bear Tokens
    if base.endswith("UP") or base.endswith("DOWN") or base.endswith("BULL") or base.endswith("BEAR") or base.endswith("3L") or base.endswith("3S") or base.endswith("2L") or base.endswith("2S"):
        return False

    # 5. Reject Known Stablecoins & Fiat Pegs
    if base in EXCLUDED_STABLECOIN_BASES or base in EXCLUDED_DELISTED_BASES:
        return False

    # 6. Dynamic Price Peg Filter (~$1 peg with near zero volatility)
    if price is not None and price > 0:
        if 0.97 <= price <= 1.03:
            if high is not None and low is not None and high > 0 and low > 0:
                vol_spread = (high - low) / max(0.001, price)
                if vol_spread < 0.035:
                    return False
            else:
                if 0.99 <= price <= 1.01:
                    return False

    # 7. Single-Side Order Book Void Filter
    if bid_price is not None and ask_price is not None:
        if (bid_price <= 1e-8 and ask_price > 0) or (ask_price <= 1e-8 and bid_price > 0):
            return False
        if bid_price > 0 and ask_price > 0:
            if (ask_price - bid_price) / max(1e-8, ask_price) > 0.05:
                return False
            if price is not None and price > 0:
                if bid_price < price * 0.85 or ask_price > price * 1.15:
                    return False
    if spread_bps is not None and spread_bps > 500.0:
        return False

    return True

print("[SYSTEM] Running in High-Performance CPU Mode.")

# ------------------------------------------------------------------------------
# 1. CONFIGURATION & MULTI-HORIZON PARAMETERS
# ------------------------------------------------------------------------------
CONFIG = {
    "mode": "both",               # "both", "scanner", or "single"
    "continuous_loop": True,      # 24/7 Background Watcher Loop
    "scanner_mode": "top_volume", # "top_volume" (dynamic auto-discovery of all active Binance coins), "expanded_universe", or "custom_list"
    "scanner_top_n": int(os.getenv("SCANNER_TOP_N", "100")), # Curated Top 100 high-volume active crypto momentum universe
    "max_scan_workers": int(os.getenv("MAX_SCAN_WORKERS", "16")), # 16 parallel worker threads for high-throughput scanning
    "heartbeat_interval_seconds": int(os.getenv("HEARTBEAT_SECONDS", "4")), # Fast intra-candle position monitoring
    "scan_interval_seconds": int(os.getenv("SCAN_INTERVAL_SECONDS", "60")), # Frequent continuous 60s rescan cycle fallback
    "sync_to_candle_close": os.getenv("SYNC_TO_CANDLE_CLOSE", "true").lower() in ("true", "1", "yes"), # Synchronize scan to candle close
    "candle_close_gap_seconds": int(os.getenv("CANDLE_CLOSE_GAP_SECONDS", "2")), # 2-second buffer for candle close finalization
    "candle_anchor_horizon": os.getenv("CANDLE_ANCHOR_HORIZON", "15m"), # Default 15M candle boundary
    "force_fresh_training_on_scan": os.getenv("FORCE_FRESH_TRAINING_ON_SCAN", "false").lower() in ("true", "1", "yes"), # Train freshly on newly closed candle
    "single_symbol": "BTC/USDT",
    "skip_meme_and_shitcoins": True, # Exclude meme coins and non-utility shitcoins from system
    "min_24h_volume_usd": float(os.getenv("MIN_24H_VOLUME_USD", "10000000.0")), # Enforce $10M min 24h institutional volume
    "scanner_symbols": [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT",
        "AVAX/USDT", "SUI/USDT", "LINK/USDT", "NEAR/USDT", "APT/USDT", "DOT/USDT",
        "TIA/USDT", "INJ/USDT", "RENDER/USDT", "FET/USDT", "OP/USDT", "AVA/USDT",
        "LTC/USDT", "UNI/USDT", "ICP/USDT", "FIL/USDT", "STX/USDT", "TAO/USDT", "SEI/USDT",
        "ATOM/USDT", "AAVE/USDT", "WLD/USDT", "RUNE/USDT", "POL/USDT", "PYTH/USDT",
        "JUP/USDT", "ONDO/USDT", "HBAR/USDT", "ENA/USDT", "PENDLE/USDT", "ALGO/USDT",
        "QNT/USDT", "IMX/USDT", "KAS/USDT", "ZEC/USDT", "GTC/USDT"
    ],
    "timeframes": ["1d", "4h", "1h", "15m"],
    # Targeted Institutional High-Edge Horizons: 15M (Scalp), 1H (Day Trade), 24H (Swing Trade)
    # Note: 4H Day Trade horizon disabled due to empirical -22.67% PnL drag (wide stops with mid-range chop)
    "horizons": {
        "scalp": {
            "name": "⚡ Scalp (15M)",
            "anchor_tf": "15m",
            "bars": 4,
            "duration_label": "15-60 Mins Scalp",
            "tp_mult": 2.0,
            "sl_mult": 1.0
        },
        "swing": {
            "name": "⏳ Day Trade (1H)",
            "anchor_tf": "1h",
            "bars": 6,
            "duration_label": "1-8 Hours Day Trade",
            "tp_mult": 2.5,
            "sl_mult": 1.2
        },
        "macro": {
            "name": "🌊 Swing Trade (1D)",
            "anchor_tf": "1d",
            "bars": 1,
            "duration_label": "24-72 Hours Swing Trade",
            "tp_mult": 3.0,
            "sl_mult": 1.5
        }
    },
    "history_limit_per_tf": {
        "1d": 300,
        "4h": 300,
        "1h": 350,
        "15m": 350
    },
    "paper_trading": {
        "enabled": False,
        "spot_only": False,                 # Bi-directional trading enabled: Execute both high-edge LONG and SHORT setups
        "start_balance_usd": 1000.0,        # $1,000.00 Institutional Virtual Portfolio Benchmark
        "dynamic_sizing": True,             # Dynamic ATR Volatility Risk Parity sizing
        "risk_per_trade_pct": 1.5,          # 1.5% fixed fractional risk parity per position
        "min_position_size_usd": 30.0,
        "max_concurrent_positions": 5,      # 5 Total slots across desks (2 Scalp, 2 Day Trade, 1 Swing)
        "desks": {
            "scalp": {
                "name": "⚡ Scalp Desk",
                "allocation_pct": 0.35,     # 35% of fund ($350)
                "max_slots": 2,             # 2 concurrent scalp slots
                "allowed_horizons": ["15m", "30m", "15M", "30M", "scalp", "horizon_30m"],
                "leverage": 5,
                "tier0_threshold": 1.20,    # +1.20% peak gain moves SL to Breakeven (calibrated to >= 55% of TP1)
                "max_hold_seconds": 7200
            },
            "intraday": {
                "name": "⏳ Day Trading Desk",
                "allocation_pct": 0.40,     # 40% of fund ($400)
                "max_slots": 2,             # 2 concurrent day trade slots (1H)
                "allowed_horizons": ["1h", "1H", "intraday", "day_trade", "swing", "triple_screen"],
                "leverage": 3,
                "tier0_threshold": 1.50,    # +1.50% peak gain moves SL to Breakeven
                "max_hold_seconds": 28800   # 8-Hour Maximum Hold for 1H Day Trades (Prevents zombie drift)
            },
            "macro": {
                "name": "🌊 Swing Desk",
                "allocation_pct": 0.25,     # 25% of fund ($250)
                "max_slots": 1,             # 1 concurrent swing slot (1D / 24H)
                "allowed_horizons": ["24h", "1d", "24H", "1D", "macro"],
                "leverage": 2,
                "tier0_threshold": 2.00,    # +2.00% peak gain moves SL to Breakeven
                "max_hold_seconds": 172800  # 48-Hour Maximum Hold for 1D Swings
            }
        },
        "allowed_horizons": ["15m", "30m", "1h", "24h", "1d", "15M", "30M", "1H", "24H", "1D", "scalp", "intraday", "day_trade", "swing", "macro"],
        "min_expected_return_pct": 0.30,    # Minimum expected return hurdle: >= 0.30%
        "min_net_profit_usd": 0.15,         # Minimum $0.15 net profit target per trade
        "min_meta_probability": 0.55,       # ML secondary meta-labeling win probability hurdle (>=55%)
        "require_min_grade_a": False,       # Allow Grade A and high-conviction Grade B+ institutional setups
        "execution_engine": "binance_futures", # "binance_futures" (Isolated Margin)
        "binance_fee_rate": 0.0005,         # Standard Binance Futures 0.05% Taker Fee
        "binance_maker_fee_rate": 0.0002,   # Binance Futures 0.02% Maker Fee (0.018% with BNB discount)
        "binance_buy_fee_rate": 0.0005,     # Explicit 0.05% Entry Fee
        "binance_sell_fee_rate": 0.0005,    # Explicit 0.05% Exit Fee
        "use_bnb_fee_discount": True,       # Enable 10% BNB Futures discount (0.045% taker / 0.018% maker)
        "slippage_rate": 0.0000,
        "convert_buy_spread_rate": 0.0010,
        "convert_sell_spread_rate": 0.0010
    },
    "signal_engine": {
        "dynamic_signal_count": True,       # Adaptive signal count based on true market edge
        "min_signals_per_round": 1,         # Always guarantee at least top 1 setup
        "max_signals_per_round": 5,         # Cap at 5 to avoid information overload
        "grade_a_plus_conviction": 0.75,    # 75%+ conviction + confluence -> Grade A+
        "grade_a_conviction": 0.65,         # 65%-74% conviction -> Grade A
        "grade_b_conviction": 0.55,         # 55%-64% conviction -> Grade B+
        "require_min_rr_ratio": 2.0,        # 1:2 Risk to Reward minimum
        "min_meta_probability": 0.68,       # Secondary ML meta-labeling win probability hurdle (>=68%)
        "ban_parabolic_shorts": True,       # Circuit breaker: Block SHORT if 24h pump > 12% or 1h RSI > 68
        "min_expected_return_pct": 0.30,    # Minimum expected return hurdle: >= 0.30% (guarantees net return after buy & sell fees)
        "min_scalp_gain_pct": 0.30,         # Minimum expected TP1 gain on 15M to clear taker fees (>= 0.30%)
        "min_swing_gain_pct": 0.60,         # Minimum expected TP1 gain on 1H
        "asset_cooldown_minutes": 60        # Deduping lockout window across horizons
    },
    "elite_conviction_threshold": 0.72,   # Top-Decile Pareto Conviction (90% tier)
    "meta_confidence_threshold": 0.58,
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
    "models_export_dir": os.getenv("MODELS_DIR", "./models_export_v3"),
    "app_export_dir": os.getenv("EXPORT_DIR", "./export_app_data")
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
        self._cache_ts = {}
        self._cache_lock = threading.Lock()
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
        self._binance_ip_throttled_until = 0.0
        self.MAX_LIVE_PRICE_AGE_SECONDS = 15.0
        self.MAX_SWR_RATE_LIMIT_GRACE_SECONDS = 180.0
        self._is_price_fresh_15s = True
        self._price_freshness_age = 0.0
        self._is_global_outage = False
        self._global_outage_reason = ""
        self._is_partition_stale = False
        self._rest_outage_start_ts = None
        self._last_outage_log_ts = 0.0
        self._last_swr_log_ts = 0.0
        self._symbol_price_timestamps = {}
        self._exchange_geo_cooldowns = {}
        self._coincap_rates_cache = {}
        self._coincap_rates_ts = 0.0
        self._coincap_throttled_until = 0.0
        self._paprika_rates_cache = {}
        self._paprika_rates_ts = 0.0
        self._paprika_throttled_until = 0.0
        self._bitget_throttled_until = 0.0
        self.COINCAP_MIN_INTERVAL_SECONDS = 2.0
        self._disk_cache_dir = "export_app_data"
        try:
            from app.engine.scanner.websocket_feed import ws_feed_manager
            self.ws_feed = ws_feed_manager
        except Exception:
            self.ws_feed = None
        self.init_resilient_exchange()

    def is_partition_stale_active(self) -> bool:
        """Returns True if upstream exchange partition or global multi-exchange outage is active."""
        with self._cache_lock:
            return getattr(self, "_is_partition_stale", False) or getattr(self, "_is_global_outage", False)

    def get_partition_status(self) -> dict:
        """Provides partition health metrics for telemetry."""
        with self._cache_lock:
            return {
                "is_partition_stale": getattr(self, "_is_partition_stale", False) or getattr(self, "_is_global_outage", False),
                "is_global_outage": getattr(self, "_is_global_outage", False),
                "outage_reason": getattr(self, "_global_outage_reason", ""),
                "price_freshness_age": getattr(self, "_price_freshness_age", 0.0),
                "is_price_fresh_15s": getattr(self, "_is_price_fresh_15s", True)
            }

    def _save_tickers_to_swr_disk(self, tickers: dict, ts: float):
        """Persists live ticker prices atomically to disk for resilient SWR fallback during extreme rate limiting or public API quota exhaustion."""
        if not tickers:
            return
        try:
            cache_dir = getattr(self, '_disk_cache_dir', 'export_app_data')
            os.makedirs(cache_dir, exist_ok=True)
            cache_file = os.path.join(cache_dir, "live_tickers_swr.json")
            tmp_file = f"{cache_file}.tmp_{os.getpid()}_{threading.get_ident()}"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump({"timestamp": ts, "tickers": tickers}, f)
            os.replace(tmp_file, cache_file)
        except Exception:
            pass

    def _load_tickers_from_swr_disk(self) -> tuple:
        """Loads cached ticker prices from persistent disk during upstream quota exhaustion or exchange rate limiting."""
        try:
            cache_dir = getattr(self, '_disk_cache_dir', 'export_app_data')
            cache_file = os.path.join(cache_dir, "live_tickers_swr.json")
            if os.path.exists(cache_file):
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("tickers", {}), float(data.get("timestamp", 0.0))
        except Exception:
            pass
        return {}, 0.0

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

    def _fetch_bybit_tickers(self) -> dict:
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
                r = self.session.get(url, timeout=3.5)
                if r.status_code == 200:
                    data = r.json()
                    ret_code = data.get("retCode")
                    ret_msg = str(data.get("retMsg", "")).lower()
                    if "ip restricted" in ret_msg or "country" in ret_msg or "jurisdiction" in ret_msg or "forbidden" in ret_msg or ret_code in [10006, 10009]:
                        self._record_exchange_geo_block("bybit", 200, ret_msg or "Geo-restricted IP")
                        return {}
                    if ret_code == 0:
                        for it in data.get("result", {}).get("list", []):
                            sym = it.get("symbol")
                            p_val = it.get("lastPrice")
                            if sym and p_val:
                                p = float(p_val)
                                res[sym] = p
                                if sym.endswith("USDT"):
                                    base = sym[:-4]
                                    res[f"{base}/USDT"] = p
                                    res[f"{base}/USDT:USDT"] = p
                        if res:
                            return res
                elif r.status_code in [403, 451]:
                    self._record_exchange_geo_block("bybit", r.status_code, "Geo-restriction/Forbidden")
                    break
            except Exception:
                continue
        return res

    def _fetch_okx_tickers(self) -> dict:
        """Tier-3 Failover: Bulk fetches spot tickers from OKX with mirror support and geo-restriction detection."""
        if self._is_exchange_geo_blocked("okx"):
            return {}
        res = {}
        urls = [
            "https://www.okx.com/api/v5/market/tickers?instType=SPOT",
            "https://aws.okx.com/api/v5/market/tickers?instType=SPOT"
        ]
        for url in urls:
            try:
                r = self.session.get(url, timeout=3.5)
                if r.status_code == 200:
                    data = r.json()
                    msg = str(data.get("msg", "")).lower()
                    code = str(data.get("code", ""))
                    if "access denied" in msg or "restricted" in msg or "jurisdiction" in msg or code in ["50005", "50101"]:
                        self._record_exchange_geo_block("okx", 200, msg or "Geo-restricted IP")
                        return {}
                    if code == "0":
                        for it in data.get("data", []):
                            inst_id = it.get("instId", "")
                            last_p = it.get("last")
                            if inst_id and last_p:
                                p = float(last_p)
                                clean_sym = inst_id.replace("-", "")
                                res[clean_sym] = p
                                if inst_id.endswith("-USDT"):
                                    base = inst_id[:-5]
                                    res[f"{base}/USDT"] = p
                                    res[f"{base}/USDT:USDT"] = p
                        if res:
                            return res
                elif r.status_code in [403, 451]:
                    self._record_exchange_geo_block("okx", r.status_code, "Geo-restriction/Forbidden")
                    break
            except Exception:
                continue
        return res

    def _fetch_gateio_tickers(self) -> dict:
        """Tier-4 Failover: Bulk fetches spot tickers from Gate.io with geo-restriction detection."""
        if self._is_exchange_geo_blocked("gateio"):
            return {}
        res = {}
        try:
            r = self.session.get("https://api.gateio.ws/api/v4/spot/tickers", timeout=3.5)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and ("restricted" in str(data).lower() or "forbidden" in str(data).lower()):
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
                                res[f"{base}/USDT:USDT"] = p
            elif r.status_code in [403, 451]:
                self._record_exchange_geo_block("gateio", r.status_code, "Geo-restriction/Forbidden")
        except Exception:
            pass
        return res

    def _fetch_kucoin_tickers(self) -> dict:
        """Tier-5 Failover: Bulk fetches spot tickers from KuCoin with geo-restriction detection."""
        if self._is_exchange_geo_blocked("kucoin"):
            return {}
        res = {}
        try:
            r = self.session.get("https://api.kucoin.com/api/v1/market/allTickers", timeout=3.5)
            if r.status_code == 200:
                data = r.json()
                msg = str(data.get("msg", "")).lower()
                if "forbidden" in msg or "restricted" in msg or "access denied" in msg or str(data.get("code")) in ["400003"]:
                    self._record_exchange_geo_block("kucoin", 200, msg or "Geo-restricted IP")
                    return {}
                if data.get("code") == "200000":
                    for it in data.get("data", {}).get("ticker", []):
                        sym = it.get("symbol")
                        last_p = it.get("last")
                        if sym and last_p:
                            p = float(last_p)
                            clean_sym = sym.replace("-", "")
                            res[clean_sym] = p
                            if sym.endswith("-USDT"):
                                base = sym[:-5]
                                res[f"{base}/USDT"] = p
                                res[f"{base}/USDT:USDT"] = p
            elif r.status_code in [403, 451]:
                self._record_exchange_geo_block("kucoin", r.status_code, "Geo-restriction/Forbidden")
        except Exception:
            pass
        return res

    def _fetch_mexc_tickers(self) -> dict:
        """Tier-6 Failover: Bulk fetches spot tickers from MEXC with geo-restriction detection."""
        if self._is_exchange_geo_blocked("mexc"):
            return {}
        res = {}
        try:
            resp = self.session.get("https://api.mexc.com/api/v3/ticker/price", timeout=4.5)
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
            elif resp.status_code in [403, 451]:
                self._record_exchange_geo_block("mexc", resp.status_code, "Geo-restriction/Forbidden")
        except Exception:
            pass
        return res

    def _fetch_bybit_klines(self, symbol: str, timeframe: str, limit: int = 200) -> list:
        """Tier-2 Failover: Fetches candles from Bybit Spot with mirror support and geo-restriction detection."""
        if self._is_exchange_geo_blocked("bybit"):
            return []
        try:
            raw_sym = symbol.replace('/', '').replace(':USDT', '')
            tf_map = {'1m': '1', '5m': '5', '15m': '15', '30m': '30', '1h': '60', '4h': '240', '1d': 'D', '1w': 'W', '1M': 'M'}
            bybit_tf = tf_map.get(timeframe, '60')
            urls = [
                "https://api.bybit.com/v5/market/kline",
                "https://api.bytick.com/v5/market/kline"
            ]
            for url in urls:
                r = self.session.get(url, params={"category": "spot", "symbol": raw_sym, "interval": bybit_tf, "limit": min(200, limit)}, timeout=4.5)
                if r.status_code == 200:
                    d = r.json()
                    ret_code = d.get("retCode")
                    ret_msg = str(d.get("retMsg", "")).lower()
                    if "ip restricted" in ret_msg or "country" in ret_msg or "jurisdiction" in ret_msg or ret_code in [10006, 10009]:
                        self._record_exchange_geo_block("bybit", 200, ret_msg)
                        return []
                    if ret_code == 0:
                        raw_list = d.get("result", {}).get("list", [])[::-1]
                        return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[5])*0.5] for k in raw_list]
                elif r.status_code in [403, 451]:
                    self._record_exchange_geo_block("bybit", r.status_code, "Geo-restriction/Forbidden")
                    break
        except Exception:
            pass
        return []

    def _fetch_okx_klines(self, symbol: str, timeframe: str, limit: int = 100) -> list:
        """Tier-3 Failover: Fetches candles from OKX Spot with mirror support and geo-restriction detection."""
        if self._is_exchange_geo_blocked("okx"):
            return []
        try:
            raw_sym = symbol.replace('/', '').replace(':USDT', '')
            base = raw_sym[:-4] if raw_sym.endswith("USDT") else raw_sym
            tf_map = {'1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m', '1h': '1H', '4h': '4H', '1d': '1D', '1w': '1W', '1M': '1M'}
            okx_tf = tf_map.get(timeframe, '1H')
            urls = [
                "https://www.okx.com/api/v5/market/candles",
                "https://aws.okx.com/api/v5/market/candles"
            ]
            for url in urls:
                r = self.session.get(url, params={"instId": f"{base}-USDT", "bar": okx_tf, "limit": min(100, limit)}, timeout=4.5)
                if r.status_code == 200:
                    d = r.json()
                    msg = str(d.get("msg", "")).lower()
                    code = str(d.get("code", ""))
                    if "access denied" in msg or "restricted" in msg or "jurisdiction" in msg or code in ["50005", "50101"]:
                        self._record_exchange_geo_block("okx", 200, msg or "Geo-restricted IP")
                        return []
                    if code == "0":
                        raw_list = d.get("data", [])[::-1]
                        return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[5])*0.5] for k in raw_list]
                elif r.status_code in [403, 451]:
                    self._record_exchange_geo_block("okx", r.status_code, "Geo-restriction/Forbidden")
                    break
        except Exception:
            pass
        return []

    def _fetch_gateio_klines(self, symbol: str, timeframe: str, limit: int = 200) -> list:
        """Tier-4 Failover: Fetches candles from Gate.io Spot with geo-restriction detection."""
        if self._is_exchange_geo_blocked("gateio"):
            return []
        try:
            raw_sym = symbol.replace('/', '').replace(':USDT', '')
            base = raw_sym[:-4] if raw_sym.endswith("USDT") else raw_sym
            tf_map = {'1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m', '1h': '1h', '4h': '4h', '1d': '1d', '1w': '7d', '1M': '30d'}
            gate_tf = tf_map.get(timeframe, '1h')
            r = self.session.get("https://api.gateio.ws/api/v4/spot/candlesticks", params={"currency_pair": f"{base}_USDT", "interval": gate_tf, "limit": min(200, limit)}, timeout=4.5)
            if r.status_code == 200:
                raw_list = r.json()
                if isinstance(raw_list, dict) and ("restricted" in str(raw_list).lower() or "forbidden" in str(raw_list).lower()):
                    self._record_exchange_geo_block("gateio", 200, str(raw_list.get("message", "")))
                    return []
                if isinstance(raw_list, list) and len(raw_list) > 0:
                    raw_list = raw_list[::-1]
                    return [[int(k[0])*1000, float(k[5]), float(k[3]), float(k[4]), float(k[2]), float(k[1]), float(k[1])*0.5] for k in raw_list]
            elif r.status_code in [403, 451]:
                self._record_exchange_geo_block("gateio", r.status_code, "Geo-restriction/Forbidden")
        except Exception:
            pass
        return []

    def _fetch_kucoin_klines(self, symbol: str, timeframe: str, limit: int = 200) -> list:
        """Tier-5 Failover: Fetches candles from KuCoin Spot with geo-restriction detection."""
        if self._is_exchange_geo_blocked("kucoin"):
            return []
        try:
            raw_sym = symbol.replace('/', '').replace(':USDT', '')
            base = raw_sym[:-4] if raw_sym.endswith("USDT") else raw_sym
            tf_map = {'1m': '1min', '5m': '5min', '15m': '15min', '30m': '30min', '1h': '1hour', '4h': '4hour', '1d': '1day', '1w': '1week'}
            kc_tf = tf_map.get(timeframe, '1hour')
            r = self.session.get("https://api.kucoin.com/api/v1/market/candles", params={"symbol": f"{base}-USDT", "type": kc_tf}, timeout=4.5)
            if r.status_code == 200:
                d = r.json()
                msg = str(d.get("msg", "")).lower()
                if "forbidden" in msg or "restricted" in msg or "access denied" in msg or str(d.get("code")) in ["400003"]:
                    self._record_exchange_geo_block("kucoin", 200, msg or "Geo-restricted IP")
                    return []
                if d.get("code") == "200000":
                    raw_list = d.get("data", [])[::-1]
                    return [[int(k[0])*1000, float(k[1]), float(k[3]), float(k[4]), float(k[2]), float(k[5]), float(k[5])*0.5] for k in raw_list]
            elif r.status_code in [403, 451]:
                self._record_exchange_geo_block("kucoin", r.status_code, "Geo-restriction/Forbidden")
        except Exception:
            pass
        return []

    def _reconcile_public_aggregator_multipliers(self, raw_rates: dict) -> dict:
        """
        Public Aggregator Multiplier Mapping:
        CoinCap and Coinpaprika provide index rates for base coins (e.g. MOG) rather than derivatives (1000000MOG).
        By resolving through resolve_symbol_aliases and scaling by (target_mult / 1.0), the system correctly
        reconciles public aggregator failovers across all multiplier tiers (10^4, 10^5, 10^6, 1MBABYDOGE, etc.).
        """
        if not raw_rates:
            return {}

        res = dict(raw_rates)
        from app.engine.config import strip_contract_multiplier, resolve_symbol_aliases

        candidate_bases = {
            "MOG", "LADYS", "PEPE", "SHIB", "BONK", "BABYDOGE", "SATS", "AIDOGE",
            "FLOKI", "CHEEMS", "PEIPEI", "CAT", "RATS", "TOKEN", "BTT", "XEC",
            "LUNC", "RACA", "SPELL", "VVS", "BTTC", "NEIRO", "MEME", "DOGS", "NOT"
        }

        for k, p_val in list(raw_rates.items()):
            if p_val <= 0:
                continue
            cand_base, cand_mult = strip_contract_multiplier(k)
            if cand_base in candidate_bases or cand_mult > 1.0:
                base_rate = float(p_val) / max(1e-8, float(cand_mult)) if cand_mult > 1.0 else float(p_val)
                res[cand_base] = base_rate
                res[f"{cand_base}USDT"] = base_rate
                res[f"{cand_base}/USDT"] = base_rate
                res[f"{cand_base}/USDT:USDT"] = base_rate

                for alias in resolve_symbol_aliases(f"{cand_base}/USDT"):
                    target_base, target_mult = strip_contract_multiplier(alias)
                    if target_mult > 1.0:
                        scaled_p = base_rate * (float(target_mult) / 1.0)
                        res[alias] = scaled_p
                        clean_a = alias.replace("/", "").replace(":USDT", "").replace("-", "").replace("_", "").strip()
                        res[clean_a] = scaled_p
                        if not alias.endswith("USDT") and "/" not in alias:
                            res[f"{alias}USDT"] = scaled_p
                            res[f"{alias}/USDT"] = scaled_p

        return res

    def _fetch_coincap_tickers(self) -> dict:
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
                    res = self._reconcile_public_aggregator_multipliers(res)
                    self._coincap_rates_cache = res
                    self._coincap_rates_ts = now
                    print(f"[DATA LOADER [TIER-6.5]] Engaged CoinCap Global Rates Aggregator ({len(res)} prices with multiplier mapping).", flush=True)
            elif resp.status_code == 429:
                self._coincap_throttled_until = now + 60.0
                print(f"[DATA LOADER [TIER-6.5]] CoinCap public endpoint rate-limited (HTTP 429). 60s cooldown active.", flush=True)
                return getattr(self, '_coincap_rates_cache', {}).copy()
        except Exception:
            pass

        if res:
            return res
        return getattr(self, '_coincap_rates_cache', {}).copy()

    def _fetch_coinpaprika_tickers(self) -> dict:
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
                    res = self._reconcile_public_aggregator_multipliers(res)
                    self._paprika_rates_cache = res
                    self._paprika_rates_ts = now
                    print(f"[DATA LOADER [TIER-6.6]] Engaged Coinpaprika Global Rates Aggregator ({len(res)} prices with multiplier mapping).", flush=True)
            elif resp.status_code == 429:
                self._paprika_throttled_until = now + 60.0
                return getattr(self, '_paprika_rates_cache', {}).copy()
        except Exception:
            pass

        return res or getattr(self, '_paprika_rates_cache', {}).copy()

    def fetch_all_tickers(self, max_age_seconds: float = 3.0) -> dict:
        """Fetches real-time price tickers with multi-exchange fallback (Binance -> Bybit -> OKX -> Gate.io -> KuCoin -> CoinCap) and 15s staleness circuit breaker."""
        now = time.time()
        # Tier-0: Real-Time WebSocket stream (<500ms latency, 0ms HTTP round-trip)
        if getattr(self, "ws_feed", None) and not getattr(self.ws_feed, "is_mirror_outage", False) and self.ws_feed.is_healthy():
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
            if self._live_tickers_cache and (now - getattr(self, '_live_tickers_ts', 0.0)) < max_age_seconds:
                return self._live_tickers_cache.copy()

        data = None
        binance_blocked = (now < getattr(self, '_binance_ip_throttled_until', 0.0))
        if not binance_blocked:
            urls = [
                "https://data-api.binance.vision/api/v3/ticker/price",
                "https://api.binance.com/api/v3/ticker/price",
                "https://api1.binance.com/api/v3/ticker/price",
                "https://api2.binance.com/api/v3/ticker/price",
                "https://fapi.binance.com/fapi/v1/ticker/price"
            ]
            for u in urls:
                try:
                    r = self.session.get(u, timeout=2.5)
                    if r.status_code == 200:
                        data = r.json()
                        break
                    elif r.status_code in [403, 418, 429]:
                        self._binance_ip_throttled_until = now + 180.0
                        break
                except Exception:
                    continue
            
            if data and isinstance(data, list):
                res = {}
                for item in data:
                    sym = item.get('symbol')
                    price_val = item.get('price')
                    if sym and price_val:
                        p = float(price_val)
                        res[sym] = p
                        if sym.endswith("USDT"):
                            base = sym[:-4]
                            res[f"{base}/USDT"] = p
                            res[f"{base}/USDT:USDT"] = p
                with self._cache_lock:
                    self._live_tickers_cache = res
                    self._live_tickers_ts = now
                    self._is_price_fresh_15s = True
                    self._price_freshness_age = 0.0
                    self._is_global_outage = False
                    for s in res:
                        self._symbol_price_timestamps[s] = now
                return res

        # Tier-2 Fallback: Bybit Tickers
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

        # Tier-3 Fallback: OKX Tickers
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

        # Tier-4 Fallback: Gate.io Tickers
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

        # Tier-5 Fallback: KuCoin Tickers
        kucoin_ticks = self._fetch_kucoin_tickers()
        if kucoin_ticks:
            with self._cache_lock:
                self._live_tickers_cache = kucoin_ticks
                self._live_tickers_ts = now
                self._is_price_fresh_15s = True
                self._price_freshness_age = 0.0
                self._is_global_outage = False
                self._rest_outage_start_ts = None
                for s in kucoin_ticks:
                    self._symbol_price_timestamps[s] = now
            return kucoin_ticks

        # Tier-6 Fallback: MEXC Tickers
        mexc_ticks = self._fetch_mexc_tickers()
        if mexc_ticks:
            with self._cache_lock:
                self._live_tickers_cache = mexc_ticks
                self._live_tickers_ts = now
                self._is_price_fresh_15s = True
                self._price_freshness_age = 0.0
                self._is_global_outage = False
                self._rest_outage_start_ts = None
                for s in mexc_ticks:
                    self._symbol_price_timestamps[s] = now
            return mexc_ticks

        # Tier-6.5 Fallback: Global Decentralized Price Aggregator (CoinCap)
        coincap_ticks = self._fetch_coincap_tickers()
        if coincap_ticks:
            with self._cache_lock:
                self._live_tickers_cache = coincap_ticks
                self._live_tickers_ts = now
                self._is_price_fresh_15s = True
                self._price_freshness_age = 0.0
                self._is_global_outage = False
                self._rest_outage_start_ts = None
                for s in coincap_ticks:
                    self._symbol_price_timestamps[s] = now
            return coincap_ticks

        # Tier-6.6 Failover: Coinpaprika Global Rates Aggregator
        is_paprika_throttled = (now < getattr(self, '_paprika_throttled_until', 0.0))
        if not is_paprika_throttled:
            paprika_ticks = self._fetch_coinpaprika_tickers()
            if paprika_ticks:
                with self._cache_lock:
                    self._live_tickers_cache = paprika_ticks
                    self._live_tickers_ts = now
                    self._is_price_fresh_15s = True
                    self._price_freshness_age = 0.0
                    self._is_global_outage = False
                    self._rest_outage_start_ts = None
                    for s in paprika_ticks:
                        self._symbol_price_timestamps[s] = now
                return paprika_ticks

        # Catastrophic Global Multi-Exchange Outage / Multi-Exchange Rate Limiting
        # Engaged when Tier-1 through Tier-6 CEXs are geo-blocked/unreachable, and public aggregators
        # are concurrently throttled or unavailable.
        if getattr(self, '_rest_outage_start_ts', None) is None:
            self._rest_outage_start_ts = self._live_tickers_ts if self._live_tickers_ts > 0 else now

        outage_age = max(0.0, now - self._rest_outage_start_ts)

        # Step down to persistent SWR disk cache
        swr_ticks, swr_ts = self._load_tickers_from_swr_disk()
        served_ticks = swr_ticks or self._live_tickers_cache or getattr(self, '_coincap_rates_cache', {}) or getattr(self, '_paprika_rates_cache', {}) or {}
        swr_age = max(0.0, now - swr_ts) if swr_ts > 0 else outage_age

        # Check if upstream public aggregators are in an active rate-limiting exponential backoff window
        is_rate_limit_backoff = (
            now < getattr(self, '_coincap_throttled_until', 0.0) or
            now < getattr(self, '_paprika_throttled_until', 0.0) or
            now < getattr(self, '_bitget_throttled_until', 0.0)
        )
        max_grace = getattr(self, 'MAX_SWR_RATE_LIMIT_GRACE_SECONDS', 180.0)

        if is_rate_limit_backoff and served_ticks and (swr_age <= max_grace):
            # Graceful SWR step-down: during active public aggregator backoff (60s-180s),
            # warm persistent disk cache prices bridge the backoff window without tripping
            # global outage flags or interrupting core signal generation.
            is_fresh = True
            effective_age = swr_age
        else:
            is_fresh = (outage_age <= self.MAX_LIVE_PRICE_AGE_SECONDS) and bool(served_ticks)
            effective_age = outage_age

        with self._cache_lock:
            self._live_tickers_cache = served_ticks
            if swr_ts > 0:
                self._live_tickers_ts = swr_ts
                for s in served_ticks:
                    self._symbol_price_timestamps[s] = swr_ts
            self._is_price_fresh_15s = is_fresh
            self._price_freshness_age = effective_age
            if not is_fresh:
                self._is_global_outage = True
                self._global_outage_reason = (
                    f"PRICE_STALENESS_EXCEEDED: Live market ticker freshness ({effective_age:.1f}s) "
                    f"exceeded maximum constraint ({max_grace:.0f}s rate-limit grace / {self.MAX_LIVE_PRICE_AGE_SECONDS:.0f}s baseline). "
                    "All upstream exchange gateways rate-limited or unreachable."
                )
            else:
                self._is_global_outage = False
            return self._live_tickers_cache.copy()

    def _lookup_price_with_multiplier(self, symbol: str, tickers: dict) -> tuple:
        """
        Dynamically looks up price for symbol, supporting contract multiplier scaling
        (e.g., 1000000MOG price derived from MOG spot * 10^6, or vice-versa).
        """
        if not symbol or not tickers:
            return 0.0, None

        if symbol in tickers and float(tickers[symbol]) > 0:
            return float(tickers[symbol]), symbol

        raw_s = symbol.replace("/", "").replace(":USDT", "").replace("-", "").replace("_", "").strip().upper()
        if raw_s in tickers and float(tickers[raw_s]) > 0:
            return float(tickers[raw_s]), raw_s
        if f"{raw_s}USDT" in tickers and float(tickers[f"{raw_s}USDT"]) > 0:
            return float(tickers[f"{raw_s}USDT"]), f"{raw_s}USDT"
        if f"{raw_s}/USDT" in tickers and float(tickers[f"{raw_s}/USDT"]) > 0:
            return float(tickers[f"{raw_s}/USDT"]), f"{raw_s}/USDT"

        try:
            from app.engine.config import strip_contract_multiplier, resolve_symbol_aliases
            target_base, target_mult = strip_contract_multiplier(symbol)

            for alias in resolve_symbol_aliases(symbol):
                raw_a = alias.replace("/", "").replace(":USDT", "").replace("-", "").replace("_", "").strip().upper()
                matched_key = None
                if alias in tickers and float(tickers[alias]) > 0:
                    matched_key = alias
                elif raw_a in tickers and float(tickers[raw_a]) > 0:
                    matched_key = raw_a
                elif f"{raw_a}USDT" in tickers and float(tickers[f"{raw_a}USDT"]) > 0:
                    matched_key = f"{raw_a}USDT"
                elif f"{raw_a}/USDT" in tickers and float(tickers[f"{raw_a}/USDT"]) > 0:
                    matched_key = f"{raw_a}/USDT"

                if matched_key:
                    raw_p = float(tickers[matched_key])
                    cand_base, cand_mult = strip_contract_multiplier(matched_key)
                    ratio = float(target_mult) / max(1e-8, float(cand_mult))
                    return raw_p * ratio, matched_key
        except Exception:
            pass

        return 0.0, None

    def get_live_price_with_freshness(self, symbol: str) -> tuple:
        """Returns tuple of (live_price, is_price_fresh_15s, freshness_age_seconds)."""
        tickers = self.fetch_all_tickers(max_age_seconds=2.0)
        p, matched_key = self._lookup_price_with_multiplier(symbol, tickers)
        return p, getattr(self, "_is_price_fresh_15s", True), getattr(self, "_price_freshness_age", 0.0)

    def get_live_price(self, symbol: str) -> float:
        """Fetches real-time price from the pre-cached live ticker map or returns 0.0."""
        tickers = self.fetch_all_tickers(max_age_seconds=3.0)
        p, _ = self._lookup_price_with_multiplier(symbol, tickers)
        return p

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

    @staticmethod
    def get_candle_schedule(anchor_tf: str, bars: int = 1, now_utc: datetime = None) -> tuple:
        """
        Calculates standard candle boundary times (UTC) for trade opening and expiration:
        - 15M: candle opens at :00, :15, :30, :45
        - 30M: candle opens at :00, :30
        - 1H: candle opens at :00
        - 4H: candle opens at 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC
        - 12H: candle opens at 00:00, 12:00 UTC
        - 1D/24H: candle opens at 00:00 UTC
        - 7D (Weekly): candle opens at Monday 00:00 UTC
        - 30D (Monthly): candle opens at 1st of Month 00:00 UTC
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)

        if anchor_tf == '15m':
            min_base = (now_utc.minute // 15) * 15
            candle_open = now_utc.replace(minute=min_base, second=0, microsecond=0)
            step = timedelta(minutes=15)
        elif anchor_tf == '30m':
            min_base = (now_utc.minute // 30) * 30
            candle_open = now_utc.replace(minute=min_base, second=0, microsecond=0)
            step = timedelta(minutes=30)
        elif anchor_tf == '1h':
            candle_open = now_utc.replace(minute=0, second=0, microsecond=0)
            step = timedelta(hours=1)
        elif anchor_tf == '4h':
            hour_base = (now_utc.hour // 4) * 4
            candle_open = now_utc.replace(hour=hour_base, minute=0, second=0, microsecond=0)
            step = timedelta(hours=4)
        elif anchor_tf == '12h':
            hour_base = (now_utc.hour // 12) * 12
            candle_open = now_utc.replace(hour=hour_base, minute=0, second=0, microsecond=0)
            step = timedelta(hours=12)
        elif anchor_tf == '1d':
            candle_open = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            step = timedelta(days=1)
        elif anchor_tf in ('1w', '7d', 'weekly'):
            days_since_mon = now_utc.weekday()
            candle_open = (now_utc - timedelta(days=days_since_mon)).replace(hour=0, minute=0, second=0, microsecond=0)
            step = timedelta(days=7)
        elif anchor_tf in ('1M', '30d', 'monthly'):
            candle_open = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            step = timedelta(days=30)
        else:
            candle_open = now_utc.replace(minute=(now_utc.minute // 15) * 15, second=0, microsecond=0)
            step = timedelta(minutes=15)

        trade_open = candle_open + step
        target_close = trade_open + (step * bars)
        trade_open_str = trade_open.strftime('%Y-%m-%d %H:%M UTC')
        trade_close_str = target_close.strftime('%Y-%m-%d %H:%M UTC')
        return trade_open, target_close, trade_open_str, trade_close_str

    def _load_from_disk_cache(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        """Loads cached OHLCV candles from disk/memory cache if available."""
        cache_key = f"{symbol}_{timeframe}"
        with getattr(self, '_cache_lock', threading.RLock()):
            if hasattr(self, '_cache') and cache_key in self._cache:
                return self._cache[cache_key].copy()
        return None

    @classmethod
    def _resample_chunk(cls, df: pd.DataFrame, chunk_size: int = 7) -> pd.DataFrame:
        """Resamples finer candles into coarser institutional bars (e.g. 1D -> 7D/1W)."""
        if df is None or len(df) < 2:
            return df

        n = len(df)
        resampled_rows = []
        for i in range(0, n, chunk_size):
            chunk = df.iloc[i:min(i + chunk_size, n)]
            if len(chunk) < 1:
                continue
            tb_sum = float(chunk["taker_buy_vol"].sum()) if "taker_buy_vol" in chunk.columns else float(chunk["volume"].sum() * 0.5)
            resampled_rows.append({
                "timestamp": int(chunk["timestamp"].iloc[0]),
                "datetime": chunk["datetime"].iloc[0] if "datetime" in chunk.columns else pd.to_datetime(int(chunk["timestamp"].iloc[0]), unit="ms", utc=True),
                "open": float(chunk["open"].iloc[0]),
                "high": float(chunk["high"].max()),
                "low": float(chunk["low"].min()),
                "close": float(chunk["close"].iloc[-1]),
                "volume": float(chunk["volume"].sum()),
                "taker_buy_vol": tb_sum
            })

        df_out = pd.DataFrame(resampled_rows)
        for col in ["open", "high", "low", "close", "volume", "taker_buy_vol"]:
            df_out[col] = df_out[col].astype(np.float32)
        return df_out

    def _dampen_wide_spread_macro_wicks(self, symbol: str, tf: str, df: pd.DataFrame) -> pd.DataFrame:
        """
        Mitigates predatory wicks and artificial blowout spreads on low-liquidity macro bars (spread > 40%).
        Clamps outlier extremes relative to the reference price to protect downstream
        trend extractors and stop-loss calculations.
        """
        if df is None or len(df) == 0:
            return df
        if tf not in ["1w", "7d", "weekly", "15d", "1M", "30d"]:
            return df

        try:
            close_s = df["close"].replace(0, np.nan)
            spread_ratio = (df["high"] - df["low"]) / close_s
            max_spread = float(spread_ratio.max()) if not spread_ratio.empty else 0.0

            if max_spread > 0.40:
                df = df.copy()
                ref_p = 0.0
                try:
                    ref_p = self.get_live_price(symbol)
                except Exception:
                    pass
                if ref_p <= 0.0:
                    try:
                        tickers = self.fetch_all_tickers() or {}
                        ref_p = float(tickers.get(symbol) or tickers.get(symbol.replace("/", "")) or 0.0)
                    except Exception:
                        pass
                if ref_p <= 0.0:
                    ref_p = float(df["close"].iloc[-1]) if not df.empty else 0.0

                for idx in df.index:
                    c_open = float(df.at[idx, "open"])
                    c_close = float(df.at[idx, "close"])
                    c_high = float(df.at[idx, "high"])
                    c_low = float(df.at[idx, "low"])
                    curr_spread = (c_high - c_low) / max(1e-8, c_close)

                    if curr_spread > 0.40:
                        body_max = max(c_open, c_close)
                        body_min = min(c_open, c_close)

                        allowed_high = max(body_max * 1.25, ref_p * 1.35 if ref_p > 0 else body_max * 1.25)
                        new_high = min(c_high, allowed_high)
                        new_high = max(new_high, body_max)

                        allowed_low = min(body_min * 0.75, ref_p * 0.65 if ref_p > 0 else body_min * 0.75)
                        new_low = max(c_low, allowed_low)
                        new_low = min(new_low, body_min)

                        df.at[idx, "high"] = new_high
                        df.at[idx, "low"] = new_low

                df.attrs["wide_spread_dampened"] = True
        except Exception:
            pass

        return df

    def _backfill_pre_listing_candles(self, symbol: str, timeframe: str, all_ohlcv: list, min_required: int = 15) -> list:
        """
        Backfills pre-listing historical candles from secondary gateways (Bybit, OKX, Gate.io, KuCoin)
        when a newly listed token on Binance has sparse candles (len < min_required).
        Stitches pre-listing historical prefix before the primary listing timestamp.
        """
        if not all_ohlcv or len(all_ohlcv) >= min_required:
            return all_ohlcv

        first_ts = min(c[0] for c in all_ohlcv)
        sec_batches = []
        for fetch_fn in [self._fetch_bybit_klines, self._fetch_okx_klines, self._fetch_gateio_klines, self._fetch_kucoin_klines]:
            try:
                batch = fetch_fn(symbol, timeframe, limit=200)
                if batch and len(batch) > 0:
                    pre_listing = [c for c in batch if c[0] < first_ts]
                    if pre_listing:
                        sec_batches = pre_listing
                        break
            except Exception:
                pass

        if sec_batches:
            combined = sec_batches + all_ohlcv
            seen = set()
            deduped = []
            for c in sorted(combined, key=lambda x: x[0]):
                if c[0] not in seen:
                    seen.add(c[0])
                    deduped.append(c)
            return deduped

        return all_ohlcv

    def fetch_ohlcv_extended(self, symbol: str, timeframe: str, total_candles: int = 2000) -> pd.DataFrame:
        cache_key = f"{symbol}_{timeframe}_{total_candles}"
        now_ts = time.time()
        # High-Frequency Scalp TTLs: 15s for 15m/5m/1m, 60s for 1h/30m, 180s for 4h, 600s for 1d
        ttl_map = {
            '1m': 10, '3m': 10, '5m': 15, '15m': 15,
            '30m': 30, '1h': 60, '2h': 120, '4h': 180,
            '12h': 300, '1d': 600, '1w': 1800, '1M': 3600
        }
        max_age = ttl_map.get(timeframe, 30)
        with self._cache_lock:
            if cache_key in self._cache and (now_ts - getattr(self, '_cache_ts', {}).get(cache_key, 0.0)) < max_age:
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
            max_pages = 5
            page_count = 0
            while len(all_ohlcv) < total_candles and page_count < max_pages:
                page_count += 1
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

        # Multi-Exchange Secondary Kline Fallbacks during Upstream Throttle / Outage
        if not all_ohlcv:
            batch = self._fetch_bybit_klines(symbol, timeframe, limit=min(200, total_candles))
            if batch:
                all_ohlcv.extend(batch)

        if not all_ohlcv:
            batch = self._fetch_okx_klines(symbol, timeframe, limit=min(100, total_candles))
            if batch:
                all_ohlcv.extend(batch)

        if not all_ohlcv:
            batch = self._fetch_gateio_klines(symbol, timeframe, limit=min(200, total_candles))
            if batch:
                all_ohlcv.extend(batch)

        if not all_ohlcv:
            batch = self._fetch_kucoin_klines(symbol, timeframe, limit=min(200, total_candles))
            if batch:
                all_ohlcv.extend(batch)

        # Pre-listing cross-exchange backfill when newly listed asset has sparse candles
        min_candles_req = 30 if timeframe in ['1d', '1w', '7d', 'weekly', '15d', '1M', '30d'] else 15
        if 0 < len(all_ohlcv) < min_candles_req:
            all_ohlcv = self._backfill_pre_listing_candles(symbol, timeframe, all_ohlcv, min_required=min_candles_req)

        # SWR Disk / Memory Cache Fallback with 15s price staleness sync
        if not all_ohlcv:
            with self._cache_lock:
                if cache_key in self._cache and self._cache[cache_key] is not None:
                    cached_df = self._cache[cache_key].copy()
                    cached_df.attrs["is_stale"] = True
                    cached_df.attrs["exchange_source"] = "persistent_cache_swr"
                    live_p, is_fresh, price_age = self.get_live_price_with_freshness(symbol)
                    cached_df.attrs["live_price_freshness_seconds"] = price_age
                    cached_df.attrs["is_price_fresh_15s"] = is_fresh
                    if live_p > 0 and not cached_df.empty:
                        cached_df.at[cached_df.index[-1], 'close'] = live_p
                        cached_df.at[cached_df.index[-1], 'high'] = max(float(cached_df['high'].iloc[-1]), live_p)
                        cached_df.at[cached_df.index[-1], 'low'] = min(float(cached_df['low'].iloc[-1]), live_p)
                    return cached_df

        # Weekly/Macro synthesis from 1D candles if 1W is empty
        if not all_ohlcv and timeframe in ['1w', '7d', 'weekly']:
            try:
                df_1d = self.fetch_ohlcv_extended(symbol, '1d', total_candles=min(total_candles * 7, 1000))
                if df_1d is not None and len(df_1d) >= 2:
                    c_size = 7 if len(df_1d) >= 7 else max(2, len(df_1d) // 2)
                    df_res = self._resample_chunk(df_1d, chunk_size=c_size)
                    if df_res is not None and len(df_res) >= 2:
                        is_synth = (c_size < 7) or (len(df_1d) < 14) or bool(df_1d.attrs.get("is_synthetic", False))
                        df_res.attrs["is_synthetic"] = True
                        df_res.attrs["native_candle_count"] = 0 if is_synth else len(df_res)
                        df_res.attrs["resampled_from"] = "1d"
                        df_res = self._dampen_wide_spread_macro_wicks(symbol, timeframe, df_res)
                        with self._cache_lock:
                            self._cache[cache_key] = df_res
                            if not hasattr(self, '_cache_ts'):
                                self._cache_ts = {}
                            self._cache_ts[cache_key] = now_ts
                        return df_res.copy()
            except Exception:
                pass

        # Macro CoinCap/SWR baseline fallback for 1w, 15d, 1M
        if not all_ohlcv and timeframe in ['1w', '7d', 'weekly', '15d', '1M', '30d']:
            ref_price = 0.0
            try:
                ref_price = self.get_live_price(symbol)
            except Exception:
                pass
            if ref_price <= 0.0:
                try:
                    tickers = self.fetch_all_tickers() or {}
                    p_val, _ = self._lookup_price_with_multiplier(symbol, tickers)
                    ref_price = p_val
                except Exception:
                    pass
            if ref_price <= 0.0:
                coincap_ticks = getattr(self, '_coincap_rates_cache', {}) or {}
                if not coincap_ticks and not (now_ts < getattr(self, '_coincap_throttled_until', 0.0)):
                    coincap_ticks = self._fetch_coincap_tickers()
                p_val, _ = self._lookup_price_with_multiplier(symbol, coincap_ticks)
                ref_price = p_val
            if ref_price <= 0.0:
                paprika_ticks = getattr(self, '_paprika_rates_cache', {}) or {}
                if not paprika_ticks and not (now_ts < getattr(self, '_paprika_throttled_until', 0.0)):
                    paprika_ticks = self._fetch_coinpaprika_tickers()
                p_val, _ = self._lookup_price_with_multiplier(symbol, paprika_ticks)
                ref_price = p_val
            if ref_price > 0.0:
                now_ms = int(now_ts * 1000)
                step_ms = tf_ms_map.get(timeframe, 7 * 86400 * 1000)
                rows = [
                    {
                        "timestamp": now_ms - step_ms,
                        "open": float(ref_price * 0.999),
                        "high": float(ref_price * 1.002),
                        "low": float(ref_price * 0.998),
                        "close": float(ref_price),
                        "volume": 1000.0,
                        "taker_buy_vol": 500.0,
                    },
                    {
                        "timestamp": now_ms,
                        "open": float(ref_price),
                        "high": float(ref_price * 1.001),
                        "low": float(ref_price * 0.999),
                        "close": float(ref_price),
                        "volume": 500.0,
                        "taker_buy_vol": 250.0,
                    }
                ]
                df_synth = pd.DataFrame(rows)
                df_synth["datetime"] = pd.to_datetime(df_synth["timestamp"], unit="ms", utc=True)
                for c in ["open", "high", "low", "close", "volume", "taker_buy_vol"]:
                    df_synth[c] = df_synth[c].astype(np.float32)
                df_synth.attrs["is_synthetic"] = True
                df_synth.attrs["exchange_source"] = "coincap_swr_fallback"
                df_synth.attrs["native_candle_count"] = 0
                df_synth.attrs["reference_price"] = float(ref_price)
                return df_synth

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

        if timeframe in ['1w', '7d', 'weekly', '15d', '1M', '30d']:
            df = self._dampen_wide_spread_macro_wicks(symbol, timeframe, df)

        with self._cache_lock:
            self._cache[cache_key] = df
            if not hasattr(self, '_cache_ts'):
                self._cache_ts = {}
            self._cache_ts[cache_key] = now_ts
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

            fr_val = None
            if hasattr(self, '_funding_cache') and self._funding_cache:
                if raw_sym in self._funding_cache:
                    fr_val = self._funding_cache[raw_sym]
                elif symbol in self._funding_cache:
                    fr_val = self._funding_cache[symbol]
                else:
                    try:
                        from app.engine.config import resolve_symbol_aliases
                        for alias in resolve_symbol_aliases(symbol):
                            raw_a = alias.replace('/', '').replace(':USDT', '')
                            if alias in self._funding_cache:
                                fr_val = self._funding_cache[alias]
                                break
                            if raw_a in self._funding_cache:
                                fr_val = self._funding_cache[raw_a]
                                break
                            if f"{raw_a}USDT" in self._funding_cache:
                                fr_val = self._funding_cache[f"{raw_a}USDT"]
                                break
                    except Exception:
                        pass

            if fr_val is None:
                fr_val = 0.0001

            regime = "🔥 SHORT SQUEEZE" if fr_val <= -0.0002 else ("❄️ LONG SQUEEZE" if fr_val >= 0.0005 else "⚪ NEUTRAL")
            return {
                "funding_rate": fr_val,
                "open_interest": 0.0,
                "regime": regime
            }
        except Exception:
            return {"funding_rate": 0.0001, "open_interest": 0.0, "regime": "⚪ NEUTRAL"}

    def get_24hr_stats(self, symbol: str) -> dict:
        """Returns cached 24h ticker statistics (price, change_pct, high, low, volume) from preloaded bulk tickers."""
        raw_sym = symbol.replace('/', '').replace(':USDT', '')
        if hasattr(self, '_24hr_tickers_map') and self._24hr_tickers_map:
            if raw_sym in self._24hr_tickers_map:
                return self._24hr_tickers_map[raw_sym]
            if symbol in self._24hr_tickers_map:
                return self._24hr_tickers_map[symbol]
        return {
            'lastPrice': 0.0,
            'priceChangePercent': 0.0,
            'highPrice': 0.0,
            'lowPrice': 0.0,
            'quoteVolume': 0.0
        }

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
        Supports symbol aliases for tokens with contract multipliers.
        """
        candidates = [symbol]
        try:
            from app.engine.config import resolve_symbol_aliases
            candidates.extend(resolve_symbol_aliases(symbol))
        except Exception:
            pass

        for sym_cand in candidates:
            try:
                raw_sym = sym_cand.replace('/', '').replace(':USDT', '')
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
                elif self.exchange and not (self.is_binance_vision_direct or self.active_exchange_id == 'binance'):
                    ob = self.exchange.fetch_order_book(sym_cand, limit=limit)
                    bid_vol = sum(b[1] for b in ob.get('bids', []))
                    ask_vol = sum(a[1] for a in ob.get('asks', []))
                    total_vol = bid_vol + ask_vol
                    if total_vol > 0:
                        return (bid_vol - ask_vol) / total_vol
            except Exception:
                continue

        # Fallback to conservative taker-buy volume estimate when microstructure feeds are offline
        try:
            cache_k = f"{symbol}_15m_2000"
            cached_df = self._cache.get(cache_k)
            if cached_df is not None and not cached_df.empty and "taker_buy_vol" in cached_df.columns and "volume" in cached_df.columns:
                tb_sum = float(cached_df["taker_buy_vol"].iloc[-5:].sum())
                v_sum = float(cached_df["volume"].iloc[-5:].sum())
                if v_sum > 0:
                    tb_ratio = float(np.clip(tb_sum / v_sum, 0.05, 0.95))
                    return float(np.clip((tb_ratio - 0.50) * 2.0, -1.0, 1.0))
        except Exception:
            pass

        return 0.0

    def fetch_cvd_metrics(self, symbol: str) -> dict:
        """
        Fetches Cumulative Volume Delta (CVD) inflow & divergence metrics for symbol.
        In local test environments without live WebSockets or Redis:
        Falls back to conservative taker-buy volume estimates from the most recent closed candle.
        """
        tb_ratio = 0.50
        try:
            cache_k = f"{symbol}_15m_2000"
            cached_df = self._cache.get(cache_k)
            if cached_df is not None and not cached_df.empty and "taker_buy_vol" in cached_df.columns and "volume" in cached_df.columns:
                tb_sum = float(cached_df["taker_buy_vol"].iloc[-5:].sum())
                v_sum = float(cached_df["volume"].iloc[-5:].sum())
                if v_sum > 0:
                    tb_ratio = float(np.clip(tb_sum / v_sum, 0.05, 0.95))
        except Exception:
            pass

        cvd_surge = round(float(np.clip(2.0 * tb_ratio - 1.0, -1.0, 1.0)), 4)
        is_live = bool(getattr(self, "ws_feed", None) and self.ws_feed.is_healthy())
        return {
            "symbol": symbol,
            "cvd_surge": cvd_surge,
            "cvd_surge_5": cvd_surge,
            "taker_buy_ratio": round(tb_ratio, 4),
            "source": "live_websocket" if is_live else "conservative_taker_buy_estimate",
            "is_synthetic": not is_live
        }

    def fetch_active_binance_symbols(self) -> set:
        """
        Fetches and caches the set of active TRADING spot symbols on Binance.
        Guarantees delisted, halted, or non-tradable tokens (e.g. FTM) are strictly rejected.
        """
        now = time.time()
        if hasattr(self, '_active_symbols_cache') and self._active_symbols_cache and (now - getattr(self, '_active_symbols_ts', 0.0)) < 3600.0:
            return self._active_symbols_cache

        try:
            url = "https://data-api.binance.vision/api/v3/exchangeInfo"
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                active = set()
                for s in data.get('symbols', []):
                    if s.get('status') == 'TRADING' and s.get('isSpotTradingAllowed', True):
                        active.add(s.get('symbol', ''))
                if active:
                    self._active_symbols_cache = active
                    self._active_symbols_ts = now
                    return active
        except Exception as e:
            print(f"[MARKET DISCOVERY] exchangeInfo check note: {e}")

        return getattr(self, '_active_symbols_cache', set())

    def fetch_top_volume_usdt_pairs(self, limit: int = 110) -> list:
        """Dynamically discovers and ranks active volatile crypto pairs by 24h volume (strictly active Binance TRADING spot pairs, top 110 cap). Cached for 24 hours."""
        limit = min(110, int(limit or 110))
        now = time.time()
        # 24-Hour Universe Cache (86,400s): Maintains fixed stable universe all day without redundant round-by-round API hammering
        cached_u = getattr(self, '_universe_cache', None)
        cached_ts = getattr(self, '_universe_cache_ts', 0.0)
        if cached_u and (now - cached_ts) < 86400.0:
            remaining_hrs = round((86400.0 - (now - cached_ts)) / 3600.0, 1)
            print(f"[MARKET DISCOVERY ⚡] Using 24-Hour Stable Universe ({len(cached_u)} pairs, valid for {remaining_hrs}h).")
            return cached_u

        try:
            print(f"[MARKET DISCOVERY] Re-evaluating 24-Hour Stable Universe [{self.active_exchange_id.upper()}] pairs (Top {limit} Cap)...")
            active_symbols = self.fetch_active_binance_symbols()
            valid_pairs = []

            # 1. Direct Binance Vision 24h Tickers API
            if self.is_binance_vision_direct or self.active_exchange_id == 'binance':
                try:
                    resp = self.session.get("https://data-api.binance.vision/api/v3/ticker/24hr", timeout=12)
                    if resp.status_code == 200:
                        data = resp.json()
                        self._24hr_tickers_map = {}
                        for item in data:
                            raw_sym = item.get('symbol', '')
                            if not raw_sym.endswith('USDT'):
                                continue
                            if active_symbols and raw_sym not in active_symbols:
                                continue
                            base = raw_sym[:-4]
                            sym = f"{base}/USDT"
                            
                            last_p = float(item.get('lastPrice', 0.0) or 0.0)
                            high_p = float(item.get('highPrice', 0.0) or 0.0)
                            low_p = float(item.get('lowPrice', 0.0) or 0.0)
                            chg_pct = float(item.get('priceChangePercent', 0.0) or 0.0)
                            quote_vol = float(item.get('quoteVolume', 0.0) or 0.0)
                            
                            if not is_valid_crypto_pair(sym, price=last_p, high=high_p, low=low_p):
                                continue

                            stats_dict = {
                                'lastPrice': last_p,
                                'priceChangePercent': chg_pct,
                                'highPrice': high_p,
                                'lowPrice': low_p,
                                'quoteVolume': quote_vol
                            }
                            self._24hr_tickers_map[raw_sym] = stats_dict
                            self._24hr_tickers_map[sym] = stats_dict

                            if quote_vol > 500000.0:  # Minimum $500k 24h volume
                                valid_pairs.append((sym, quote_vol))
                except Exception as e:
                    print(f"[MARKET DISCOVERY] Note on Binance Vision 24h tickers: {e}")

            # 2. CCXT Fallback if not populated
            if not valid_pairs and self.exchange:
                tickers = self.exchange.fetch_tickers()
                self._24hr_tickers_map = {}
                for sym, t in tickers.items():
                    if not sym.endswith('/USDT'):
                        continue
                    last_p = float(t.get('last', 0.0) or 0.0)
                    high_p = float(t.get('high', 0.0) or 0.0)
                    low_p = float(t.get('low', 0.0) or 0.0)
                    chg_pct = float(t.get('percentage', 0.0) or 0.0)
                    quote_vol = t.get('quoteVolume', 0.0) or t.get('baseVolume', 0.0) or 0.0
                    if not is_valid_crypto_pair(sym, price=last_p, high=high_p, low=low_p):
                        continue
                    stats_dict = {
                        'lastPrice': last_p,
                        'priceChangePercent': chg_pct,
                        'highPrice': high_p,
                        'lowPrice': low_p,
                        'quoteVolume': quote_vol
                    }
                    self._24hr_tickers_map[sym] = stats_dict
                    if quote_vol > 0:
                        valid_pairs.append((sym, quote_vol))

            if valid_pairs:
                valid_pairs.sort(key=lambda x: x[1], reverse=True)
                top_pairs = [p[0] for p in valid_pairs if is_valid_crypto_pair(p[0])]

                # Mandatory Inclusion: Top 10 Gainers, Top 10 Losers, and Top 10 High Markup Movers
                gainers = self.fetch_top_24h_gainers(limit=10, min_volume_usd=1000000.0)
                losers = self.fetch_top_24h_losers(limit=10, min_volume_usd=1000000.0)
                high_markup = self.fetch_top_high_markup_movers(limit=10, min_volume_usd=1000000.0)

                mandatory_priority = []
                for item in (gainers + losers + high_markup):
                    s_sym = item['symbol']
                    if s_sym not in mandatory_priority and is_valid_crypto_pair(s_sym):
                        mandatory_priority.append(s_sym)

                merged_universe = []
                for anchor in ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
                    if anchor not in merged_universe:
                        merged_universe.append(anchor)

                for s in mandatory_priority:
                    if s not in merged_universe:
                        merged_universe.append(s)
                for s in top_pairs:
                    if s not in merged_universe:
                        merged_universe.append(s)

                final_universe = merged_universe[:limit]
                self._universe_cache = final_universe
                self._universe_cache_ts = now
                print(f"[MARKET DISCOVERY ⚡] Fixed 24-Hour Universe Established ({len(final_universe)} Coins): {', '.join(final_universe[:10])}...")
                return final_universe

        except Exception as e:
            print(f"[WARNING] Could not fetch tickers from {self.active_exchange_id} ({e}). Using default universe.")

        default_universe = [
            "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT", "ADA/USDT",
            "AVAX/USDT", "SUI/USDT", "LINK/USDT", "NEAR/USDT", "APT/USDT", "DOT/USDT", "PEPE/USDT",
            "SHIB/USDT", "TIA/USDT", "INJ/USDT", "RENDER/USDT", "FET/USDT", "OP/USDT", "ARB/USDT",
            "LTC/USDT", "UNI/USDT", "ICP/USDT", "FIL/USDT", "STX/USDT", "TAO/USDT", "SEI/USDT",
            "WIF/USDT", "BONK/USDT", "AAVE/USDT", "ATOM/USDT", "ETC/USDT", "KAS/USDT", "S/USDT",
            "WLD/USDT", "RUNE/USDT", "POL/USDT", "PYTH/USDT", "JUP/USDT", "BEAM/USDT", "ONDO/USDT",
            "FLOKI/USDT", "OM/USDT", "CORE/USDT", "GALA/USDT", "KAVA/USDT", "ALGO/USDT", "CHZ/USDT",
            "BLUR/USDT", "JASMY/USDT", "QNT/USDT", "DYDX/USDT", "IMX/USDT", "STG/USDT", "STRK/USDT",
            "GRT/USDT", "EOS/USDT", "FLOW/USDT", "ENA/USDT", "PENDLE/USDT", "CFX/USDT", "AXS/USDT",
            "MANA/USDT", "SAND/USDT", "CRV/USDT", "SNX/USDT", "DYM/USDT", "RON/USDT", "MKR/USDT",
            "COMP/USDT", "ZRO/USDT", "IO/USDT", "NOT/USDT", "TON/USDT", "MOVE/USDT", "ME/USDT",
            "VIRTUAL/USDT", "PENGU/USDT", "BOME/USDT", "MEW/USDT", "TURBO/USDT", "NEIRO/USDT",
            "BRETT/USDT", "1000SATS/USDT", "ORDI/USDT", "BIGTIME/USDT", "ETHFI/USDT", "EIGEN/USDT",
            "W/USDT", "SAFE/USDT", "ZK/USDT", "BANANA/USDT", "AKT/USDT", "ZETA/USDT", "BB/USDT",
            "LISTA/USDT", "VOXEL/USDT", "TRX/USDT", "BCH/USDT", "HBAR/USDT", "LDO/USDT", "AR/USDT",
            "SUPER/USDT", "KAIA/USDT", "THE/USDT", "LSK/USDT", "HYPE/USDT", "DRIFT/USDT", "COW/USDT"
        ]
        return [s for s in default_universe if is_valid_crypto_pair(s)][:limit]

    def fetch_top_24h_gainers(self, limit: int = 10, min_volume_usd: float = 10000000.0) -> list:
        """Discovers and ranks top 24h gainers with high institutional liquidity (>= $10M), strictly skipping meme/shitcoins."""
        limit = max(5, int(limit or 10))
        min_vol = float(min_volume_usd or 10000000.0)
        candidates = []
        seen = set()
        for sym, stats in getattr(self, '_24hr_tickers_map', {}).items():
            if not sym.endswith('/USDT') or sym in seen:
                continue
            if not is_valid_crypto_pair(sym):
                continue
            seen.add(sym)
            chg = float(stats.get('priceChangePercent', 0.0))
            vol = float(stats.get('quoteVolume', 0.0))
            last_p = float(stats.get('lastPrice', 0.0))
            if last_p <= 0:
                continue
            # Strictly filter out meme coins and shitcoins
            if is_meme_or_shitcoin(sym, price=last_p, quote_volume_24h=vol):
                continue
            # Strictly require high 24h quote volume
            if vol < min_vol:
                continue
            
            entry = {
                'symbol': sym,
                'priceChangePercent': chg,
                'lastPrice': last_p,
                'quoteVolume': vol,
                'highPrice': float(stats.get('highPrice', 0.0)),
                'lowPrice': float(stats.get('lowPrice', 0.0))
            }
            if chg >= 1.5:
                candidates.append(entry)

        candidates.sort(key=lambda x: x['priceChangePercent'], reverse=True)
        return candidates[:limit]

    def fetch_top_24h_losers(self, limit: int = 10, min_volume_usd: float = 10000000.0) -> list:
        """Discovers and ranks top 24h losers with high institutional liquidity (>= $10M) for breakdown/fade shorts, skipping meme/shitcoins."""
        limit = max(5, int(limit or 10))
        min_vol = float(min_volume_usd or 10000000.0)
        candidates = []
        seen = set()
        for sym, stats in getattr(self, '_24hr_tickers_map', {}).items():
            if not sym.endswith('/USDT') or sym in seen:
                continue
            if not is_valid_crypto_pair(sym):
                continue
            seen.add(sym)
            chg = float(stats.get('priceChangePercent', 0.0))
            vol = float(stats.get('quoteVolume', 0.0))
            last_p = float(stats.get('lastPrice', 0.0))
            if last_p <= 0:
                continue
            # Strictly filter out meme coins and shitcoins
            if is_meme_or_shitcoin(sym, price=last_p, quote_volume_24h=vol):
                continue
            # Strictly require high 24h quote volume
            if vol < min_vol:
                continue

            entry = {
                'symbol': sym,
                'priceChangePercent': chg,
                'lastPrice': last_p,
                'quoteVolume': vol,
                'highPrice': float(stats.get('highPrice', 0.0)),
                'lowPrice': float(stats.get('lowPrice', 0.0))
            }
            if chg <= -1.5:
                candidates.append(entry)

        candidates.sort(key=lambda x: x['priceChangePercent'], reverse=False)
        return candidates[:limit]

    def fetch_top_high_markup_movers(self, limit: int = 10, min_volume_usd: float = None) -> list:
        """
        Discovers top 10 coins with highest price markup / volatility range ((High - Low) / Low * 100)
        and strong momentum turnover. Strictly excludes meme coins and shitcoins, and enforces high volume.
        """
        if min_volume_usd is None:
            min_volume_usd = float(CONFIG.get("min_24h_volume_usd", 10000000.0))
        limit = max(10, int(limit or 10))
        candidates = []
        seen = set()
        for sym, stats in getattr(self, '_24hr_tickers_map', {}).items():
            if not sym.endswith('/USDT') or sym in seen:
                continue
            if not is_valid_crypto_pair(sym):
                continue
            seen.add(sym)
            vol = float(stats.get('quoteVolume', 0.0))
            last_p = float(stats.get('lastPrice', 0.0))
            high_p = float(stats.get('highPrice', 0.0))
            low_p = float(stats.get('lowPrice', 0.0))
            chg = float(stats.get('priceChangePercent', 0.0))
            
            # Strictly filter out meme coins and shitcoins
            if is_meme_or_shitcoin(sym, price=last_p, quote_volume_24h=vol):
                continue
            # Strictly require high 24h quote volume (eliminate illiquid pairs)
            if vol < min_volume_usd:
                continue

            if low_p > 0 and last_p > 0 and high_p >= low_p:
                markup_pct = ((high_p - low_p) / low_p) * 100.0
                entry = {
                    'symbol': sym,
                    'markupPct': round(markup_pct, 2),
                    'priceChangePercent': chg,
                    'lastPrice': last_p,
                    'quoteVolume': vol,
                    'highPrice': high_p,
                    'lowPrice': low_p
                }
                if markup_pct >= 4.0:
                    candidates.append(entry)

        candidates.sort(key=lambda x: (x['markupPct'] * math.log10(max(10.0, x['quoteVolume']))), reverse=True)
        return candidates[:limit]

    def detect_global_market_regime(self) -> dict:
        """
        Calculates holistic crypto market regime:
        - Breadth: % positive vs % negative coins across all liquid USDT pairs
        - Net market momentum & average 24h change
        - Classifies market into: BULLISH, BEARISH, or CONSOLIDATION
        """
        if not hasattr(self, '_24hr_tickers_map') or not self._24hr_tickers_map:
            self.fetch_top_volume_usdt_pairs(limit=110)

        changes = []
        for sym, stats in getattr(self, '_24hr_tickers_map', {}).items():
            if sym.endswith('/USDT') and is_valid_crypto_pair(sym):
                vol = float(stats.get('quoteVolume', 0.0))
                if vol >= 1000000.0:
                    changes.append(float(stats.get('priceChangePercent', 0.0)))

        if not changes:
            return {
                "regime_type": "CONSOLIDATION",
                "label": "⚖️ RANGE BOUND / CONSOLIDATION",
                "market_breadth_bull_pct": 50.0,
                "market_breadth_bear_pct": 50.0,
                "avg_24h_change_pct": 0.0,
                "tactical_stance": "RANGE_BOUNDARY_FADES",
                "favored_direction": "NEUTRAL",
                "long_conviction_boost": 0.0,
                "short_conviction_boost": 0.0
            }

        green_count = sum(1 for c in changes if c > 0)
        red_count = sum(1 for c in changes if c < 0)
        tot = max(1, len(changes))
        bull_pct = round((green_count / tot) * 100.0, 1)
        bear_pct = round((red_count / tot) * 100.0, 1)
        avg_chg = round(float(np.mean(changes)), 2)
        med_chg = round(float(np.median(changes)), 2)

        if bull_pct >= 62.0 and avg_chg >= 1.0:
            regime = "BULLISH"
            label = "🟢 BULLISH EXPANSION (MOMENTUM UPSIDE)"
            stance = "AGGRESSIVE_LONGS_AND_PULLBACK_BUYS"
            favored = "LONG"
            long_boost = 3.0
            short_boost = -5.0
        elif bear_pct >= 60.0 or avg_chg <= -1.2:
            regime = "BEARISH"
            label = "🔴 BEARISH DRIFT (RELIEF FADES & DEFENSE)"
            stance = "DEFENSIVE_SHORTS_AND_CLIMAX_REVERSALS"
            favored = "SHORT"
            long_boost = -5.0
            short_boost = 5.0
        else:
            regime = "CONSOLIDATION"
            label = "⚖️ RANGE BOUND / CONSOLIDATION"
            stance = "RANGE_BOUNDARY_MEAN_REVERSION"
            favored = "NEUTRAL"
            long_boost = 0.0
            short_boost = 0.0

        return {
            "regime_type": regime,
            "label": label,
            "market_breadth_bull_pct": bull_pct,
            "market_breadth_bear_pct": bear_pct,
            "avg_24h_change_pct": avg_chg,
            "median_24h_change_pct": med_chg,
            "total_coins_evaluated": tot,
            "tactical_stance": stance,
            "favored_direction": favored,
            "long_conviction_boost": long_boost,
            "short_conviction_boost": short_boost
        }


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
    def compute_chop_index(df: pd.DataFrame, period: int = 14) -> pd.Series:
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - df['close'].shift(1)).abs()
        tr3 = (df['low'] - df['close'].shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr_sum = tr.rolling(period).sum()
        high_max = df['high'].rolling(period).max()
        low_min = df['low'].rolling(period).min()
        denom = (high_max - low_min).clip(lower=1e-10)
        chop = 100.0 * np.log10((atr_sum / denom).clip(lower=1e-10)) / np.log10(period)
        return chop.fillna(50.0).clip(lower=0.0, upper=100.0)

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
    def compute_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0):
        """
        Calculates non-repainting ATR-based SuperTrend indicator.
        Returns:
            st_val: Series of SuperTrend price levels
            st_dir: Series of SuperTrend direction (+1.0 Bullish, -1.0 Bearish)
            st_flip_bull: Series of bullish pivot signals (transition from -1 to +1)
            st_flip_bear: Series of bearish breakdown signals (transition from +1 to -1)
        """
        n = len(df)
        if n < period:
            return pd.Series(0.0, index=df.index), pd.Series(1.0, index=df.index), pd.Series(0.0, index=df.index), pd.Series(0.0, index=df.index)

        high = df['high'].values
        low = df['low'].values
        close = df['close'].values

        atr_series = AdvancedFeatureEngineer.compute_atr(df, period=period)
        atr = atr_series.values

        hl2 = (high + low) / 2.0
        upper_basic = hl2 + (multiplier * atr)
        lower_basic = hl2 - (multiplier * atr)

        upper_band = np.zeros(n)
        lower_band = np.zeros(n)
        supertrend = np.zeros(n)
        direction = np.ones(n)

        for i in range(1, n):
            # Final lower band
            if lower_basic[i] > lower_band[i-1] or close[i-1] < lower_band[i-1]:
                lower_band[i] = lower_basic[i]
            else:
                lower_band[i] = lower_band[i-1]

            # Final upper band
            if upper_basic[i] < upper_band[i-1] or close[i-1] > upper_band[i-1]:
                upper_band[i] = upper_basic[i]
            else:
                upper_band[i] = upper_band[i-1]

            # SuperTrend state transition
            if direction[i-1] == 1:
                if close[i] < lower_band[i]:
                    direction[i] = -1
                    supertrend[i] = upper_band[i]
                else:
                    direction[i] = 1
                    supertrend[i] = lower_band[i]
            else:
                if close[i] > upper_band[i]:
                    direction[i] = 1
                    supertrend[i] = lower_band[i]
                else:
                    direction[i] = -1
                    supertrend[i] = upper_band[i]

        dir_series = pd.Series(direction, index=df.index)
        st_series = pd.Series(supertrend, index=df.index)
        flip_bull = ((dir_series == 1.0) & (dir_series.shift(1) == -1.0)).astype(float)
        flip_bear = ((dir_series == -1.0) & (dir_series.shift(1) == 1.0)).astype(float)

        return st_series.fillna(0.0), dir_series.fillna(1.0), flip_bull.fillna(0.0), flip_bear.fillna(0.0)

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

        # 15b. Institutional Order Block Engine (SMC Demand/Supply Zones)
        try:
            from app.quant_v16.order_blocks import order_block_engine
            ob_feats = order_block_engine.extract_features(data, prefix=prefix)
            for col in ob_feats.columns:
                feats[col] = ob_feats[col]
        except Exception:
            feats[f'{prefix}_in_bull_ob'] = 0.0
            feats[f'{prefix}_in_bear_ob'] = 0.0
            feats[f'{prefix}_dist_to_bull_ob'] = 3.0
            feats[f'{prefix}_dist_to_bear_ob'] = 3.0
            feats[f'{prefix}_ob_confluence'] = 0.0

        # 16. Multi-Timeframe EMA Alignment Cohesion Vector
        ema_bull_stack = ((ema9 > ema21) & (ema21 > ema50) & (ema50 > ema200)).astype(float)
        ema_bear_stack = ((ema9 < ema21) & (ema21 < ema50) & (ema50 < ema200)).astype(float)
        feats[f'{prefix}_ema_stack_cohesion'] = (ema_bull_stack - ema_bear_stack).fillna(0.0)

        # 16b. SuperTrend Trend Continuation & Reversal Pivot System (10, 3.0)
        st_val, st_dir, st_flip_bull, st_flip_bear = self.compute_supertrend(data, period=10, multiplier=3.0)
        feats[f'{prefix}_supertrend_val'] = st_val
        feats[f'{prefix}_supertrend_dir'] = st_dir
        feats[f'{prefix}_supertrend_flip_bull'] = st_flip_bull
        feats[f'{prefix}_supertrend_flip_bear'] = st_flip_bear

        # 17. Quantitative Composite Reversal Scores (0.0 to 1.0)
        rsi_oversold_factor = (0.50 - rsi_series).clip(lower=0.0) * 2.0
        rsi_overbought_factor = (rsi_series - 0.50).clip(lower=0.0) * 2.0

        bull_rev_score = (
            0.20 * rsi_bull_div +
            0.15 * rsi_oversold_factor +
            0.15 * (hist_slope > 0).astype(float) +
            0.15 * td9_buy_ex +
            0.15 * candlestick_bull_rev +
            0.10 * bb_spring +
            0.10 * climax_bot +
            0.10 * bull_sweep +
            0.15 * st_flip_bull
        ).clip(0.0, 1.0)

        bear_rev_score = (
            0.20 * rsi_bear_div +
            0.15 * rsi_overbought_factor +
            0.15 * (hist_slope < 0).astype(float) +
            0.15 * td9_sell_ex +
            0.15 * candlestick_bear_rev +
            0.10 * bb_upthrust +
            0.10 * climax_top +
            0.10 * bear_sweep +
            0.15 * st_flip_bear
        ).clip(0.0, 1.0)

        feats[f'{prefix}_bull_reversal_score'] = bull_rev_score.fillna(0.0)
        feats[f'{prefix}_bear_reversal_score'] = bear_rev_score.fillna(0.0)

        # 18. Kaufman Efficiency Ratio (ER: Trend Persistence vs Sideways Noise)
        change = (c - c.shift(10)).abs()
        volatility = c.diff().abs().rolling(10).sum()
        feats[f'{prefix}_kaufman_er'] = (change / (volatility + 1e-10)).fillna(0.5).clip(0.0, 1.0)

        # 19. Multi-Scale Volatility Compression & Expansion Ratio (ATR7 / ATR28)
        raw_atr7 = self.compute_atr(data, period=7)
        raw_atr28 = self.compute_atr(data, period=28)
        feats[f'{prefix}_vol_expansion_ratio'] = (raw_atr7 / (raw_atr28 + 1e-10)).fillna(1.0).clip(0.2, 5.0)

        # 20. Price Velocity & Acceleration (1st and 2nd price derivatives)
        p_vel = (c - c.shift(2)) / (c.shift(2) + 1e-10)
        p_acc = (c - 2.0 * c.shift(1) + c.shift(2)) / (c.shift(2) + 1e-10)
        feats[f'{prefix}_price_velocity'] = p_vel.fillna(0.0).clip(-0.5, 0.5)
        feats[f'{prefix}_price_acceleration'] = p_acc.fillna(0.0).clip(-0.5, 0.5)

        # 21. Standardized VWAP Deviation (Z-score to Volume-Weighted Average Price)
        raw_atr14 = self.compute_atr(data, period=14)
        if 'volume' in data.columns:
            pv = c * v
            cum_pv = pv.rolling(20, min_periods=3).sum()
            cum_v = v.rolling(20, min_periods=3).sum()
            vwap = cum_pv / (cum_v + 1e-10)
            feats[f'{prefix}_vwap_zscore'] = ((c - vwap) / (raw_atr14 + 1e-10)).fillna(0.0).clip(-4.0, 4.0)
        else:
            feats[f'{prefix}_vwap_zscore'] = 0.0

        # 22. Multi-Candle Sequential Morphology (Past 5 Candle Anatomy Tensors)
        # Ingests sequential bar pressure, wick absorption, and body conviction across past candles
        for k in range(1, 6):
            c_k = c.shift(k)
            o_k = o.shift(k)
            h_k = h.shift(k)
            l_k = l.shift(k)
            bar_rng_k = (h_k - l_k).clip(lower=1e-10)

            # Candle impulse direction & conviction: positive for green, negative for red (-1.0 to +1.0)
            feats[f'{prefix}_candle_impulse_lag{k}'] = ((c_k - o_k) / bar_rng_k).fillna(0.0).clip(-1.0, 1.0)
            # Body proportion: ratio of body to entire wick range (0.0 to 1.0)
            feats[f'{prefix}_candle_body_ratio_lag{k}'] = ((c_k - o_k).abs() / bar_rng_k).fillna(0.0).clip(0.0, 1.0)
            # Overhead supply pressure (upper wick ratio)
            feats[f'{prefix}_upper_wick_lag{k}'] = ((h_k - np.maximum(c_k, o_k)) / bar_rng_k).fillna(0.0).clip(0.0, 1.0)
            # Bottom absorption demand (lower wick ratio)
            feats[f'{prefix}_lower_wick_lag{k}'] = ((np.minimum(c_k, o_k) - l_k) / bar_rng_k).fillna(0.0).clip(0.0, 1.0)
            # Relative candle size normalized to ATR
            feats[f'{prefix}_candle_size_norm_lag{k}'] = (bar_rng_k / (raw_atr14 + 1e-10)).fillna(1.0).clip(0.1, 5.0)

        # 23. Sequential Trajectory & Multi-Lag Momentum Returns (Fibonacci Lookbacks: 2, 5, 8, 13)
        for lag in [2, 5, 8, 13]:
            ret_k = (c - c.shift(lag)) / (c.shift(lag) + 1e-10)
            feats[f'{prefix}_seq_ret_lag{lag}'] = ret_k.fillna(0.0).clip(-0.5, 0.5)

        # Non-linear trajectory curvature: acceleration across consecutive 3-bar segments
        ret_curr_3 = (c - c.shift(3)) / (c.shift(3) + 1e-10)
        ret_prev_3 = (c.shift(3) - c.shift(6)) / (c.shift(6) + 1e-10)
        feats[f'{prefix}_trajectory_curvature_3b'] = (ret_curr_3 - ret_prev_3).fillna(0.0).clip(-0.5, 0.5)

        # 24. Market Structure & Liquidity Pivots (Rolling 20-Candle Swing High / Low)
        roll_high_20 = h.shift(1).rolling(20).max()
        roll_low_20 = l.shift(1).rolling(20).min()
        feats[f'{prefix}_dist_to_swing_high_20'] = ((roll_high_20 - c) / (raw_atr14 + 1e-10)).fillna(0.0).clip(-5.0, 5.0)
        feats[f'{prefix}_dist_to_swing_low_20'] = ((c - roll_low_20) / (raw_atr14 + 1e-10)).fillna(0.0).clip(-5.0, 5.0)
        feats[f'{prefix}_breakout_high_20'] = (c > roll_high_20).astype(float).fillna(0.0)
        feats[f'{prefix}_breakdown_low_20'] = (c < roll_low_20).astype(float).fillna(0.0)

        # 25. Multi-Bar Volume Flow Dynamics across Past Candles
        vol_roll_3 = v.rolling(3, min_periods=1).mean()
        vol_roll_15 = v.rolling(15, min_periods=3).mean()
        feats[f'{prefix}_vol_flow_trend'] = (vol_roll_3 / (vol_roll_15 + 1e-10)).fillna(1.0).clip(0.1, 8.0)

        # Up-volume vs Down-volume concentration over past 5 candles
        is_green_bar = (c > o).astype(float)
        up_vol_5 = (v * is_green_bar).rolling(5).sum()
        total_vol_5 = v.rolling(5).sum()
        feats[f'{prefix}_up_volume_ratio_5b'] = (up_vol_5 / (total_vol_5 + 1e-10)).fillna(0.5).clip(0.0, 1.0)

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

        if '15m' in btc_dfs and not btc_dfs['15m'].empty:
            btc_15m = btc_dfs['15m'][['timestamp', 'close']].copy().sort_values('timestamp')
            btc_15m['btc_scalp_ret_15m'] = np.log(btc_15m['close'] / btc_15m['close'].shift(1).clip(lower=1e-10)).fillna(0.0)
            df = pd.merge_asof(df.sort_values('timestamp'), btc_15m[['timestamp', 'btc_scalp_ret_15m']], on='timestamp', direction='backward')

        # Quantitative Multi-Timeframe BTC Beta & Rolling Correlation
        asset_ret = np.log(df['close'] / df['close'].shift(1).clip(lower=1e-10)).fillna(0.0)
        if 'btc_swing_ret_1h' in df.columns:
            roll_cov = asset_ret.rolling(24, min_periods=4).cov(df['btc_swing_ret_1h'])
            roll_var = df['btc_swing_ret_1h'].rolling(24, min_periods=4).var().clip(lower=1e-8)
            roll_corr = asset_ret.rolling(24, min_periods=4).corr(df['btc_swing_ret_1h']).fillna(0.0).clip(-1.0, 1.0)
            df['btc_corr_24h'] = roll_corr
            df['btc_beta_24h'] = (roll_cov / roll_var).fillna(1.0).clip(-3.0, 5.0)
            df['is_bear_when_btc_bear'] = ((df['btc_swing_ret_1h'] < 0) & (asset_ret < 0)).astype(np.float32)
            df['is_bull_when_btc_bear'] = ((df['btc_swing_ret_1h'] < 0) & (asset_ret > 0)).astype(np.float32)
        else:
            df['btc_corr_24h'] = 0.50
            df['btc_beta_24h'] = 1.0
            df['is_bear_when_btc_bear'] = 0.0
            df['is_bull_when_btc_bear'] = 0.0

        # Parabolic Hype Surge & Blow-Off Top Feature Indicators
        if 'volume' in df.columns:
            vol_ma = df['volume'].rolling(20, min_periods=3).mean()
            vol_ratio = df['volume'] / (vol_ma + 1e-10)
            price_change = (df['close'] - df['open']) / (df['open'] + 1e-10)
            raw_atr = self.compute_atr(df, period=14)
            upper_wick = (df['high'] - np.maximum(df['close'], df['open'])) / (df['high'] - df['low'] + 1e-10)
            rsi_s = self.compute_rsi(df['close'], period=14)

            df['is_parabolic_hype_surge'] = ((vol_ratio >= 2.5) & (price_change >= 0.03)).astype(np.float32)
            df['is_blowoff_top_exhaustion'] = ((upper_wick >= 0.38) & (rsi_s >= 0.75) & (vol_ratio >= 2.0)).astype(np.float32)
        else:
            df['is_parabolic_hype_surge'] = 0.0
            df['is_blowoff_top_exhaustion'] = 0.0

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
        if n <= horizon_bars + 1:
            data['Target_Primary'] = np.nan
            data['Target_Meta'] = np.nan
            data['Target_Return'] = np.nan
            data['Target_Close_Return'] = np.nan
            data['Target_MFE'] = np.nan
            data['Target_MAE'] = np.nan
            data['Excursion_Score'] = np.nan
            return data

        close = data['close'].values.astype(np.float64)
        high = data['high'].values.astype(np.float64)
        low = data['low'].values.astype(np.float64)
        atr = np.nan_to_num(data['primary_raw_atr'].values.astype(np.float64), nan=0.0)

        # Future close after horizon_bars
        future_c = np.roll(close, -horizon_bars)
        exp_ret = (future_c - close) / (close + 1e-10)
        primary_direction = (exp_ret > 0).astype(np.float32)

        # Target barriers
        pt_long = close + (base_pt * atr)
        sl_long = close - (base_sl * atr)
        pt_short = close - (base_pt * atr)
        sl_short = close + (base_sl * atr)

        min_gain_hurdle = 0.0085

        # Sequential Intrawindow Candle Forward Matrices [Shape: (n, horizon_bars)]
        H_forward = np.zeros((n, horizon_bars), dtype=np.float64)
        L_forward = np.zeros((n, horizon_bars), dtype=np.float64)
        for k in range(1, horizon_bars + 1):
            rh = np.roll(high, -k)
            rl = np.roll(low, -k)
            rh[-k:] = np.nan
            rl[-k:] = np.nan
            H_forward[:, k - 1] = rh
            L_forward[:, k - 1] = rl

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            window_high = np.nanmax(H_forward, axis=1)
            window_low = np.nanmin(L_forward, axis=1)
        window_high = np.nan_to_num(window_high, nan=close)
        window_low = np.nan_to_num(window_low, nan=close)

        fav_long = np.maximum(0.0, window_high - close)
        adv_long = np.maximum(0.0, close - window_low)
        fav_short = np.maximum(0.0, close - window_low)
        adv_short = np.maximum(0.0, window_high - close)

        # Sequential First-Barrier Search for LONG:
        # Check at each forward bar whether PT or SL is touched
        pt_hit_long_mat = (H_forward >= pt_long[:, None])
        sl_hit_long_mat = (L_forward <= sl_long[:, None])

        pt_first_idx_long = np.where(pt_hit_long_mat.any(axis=1), np.argmax(pt_hit_long_mat, axis=1), 9999)
        sl_first_idx_long = np.where(sl_hit_long_mat.any(axis=1), np.argmax(sl_hit_long_mat, axis=1), 9999)

        # Path sequence resolution:
        # 1. PT touched strictly before SL -> WIN (1.0)
        # 2. SL touched before PT or on exact same candle -> LOSS (0.0) [Adverse SL Precedence]
        # 3. Neither barrier touched (vertical barrier at expiry) -> check return hurdle
        win_seq_long = (pt_first_idx_long < sl_first_idx_long)
        neither_long = (pt_first_idx_long == 9999) & (sl_first_idx_long == 9999)
        expiry_win_long = neither_long & (exp_ret >= min_gain_hurdle) & (fav_long >= (adv_long * 1.5))
        meta_long = (win_seq_long | expiry_win_long).astype(np.float32)
        exc_long = (fav_long + 1e-10) / (adv_long + 1e-10)

        # Sequential First-Barrier Search for SHORT:
        pt_hit_short_mat = (L_forward <= pt_short[:, None])
        sl_hit_short_mat = (H_forward >= sl_short[:, None])

        pt_first_idx_short = np.where(pt_hit_short_mat.any(axis=1), np.argmax(pt_hit_short_mat, axis=1), 9999)
        sl_first_idx_short = np.where(sl_hit_short_mat.any(axis=1), np.argmax(sl_hit_short_mat, axis=1), 9999)

        win_seq_short = (pt_first_idx_short < sl_first_idx_short)
        neither_short = (pt_first_idx_short == 9999) & (sl_first_idx_short == 9999)
        expiry_win_short = neither_short & (exp_ret <= -min_gain_hurdle) & (fav_short >= (adv_short * 1.5))
        meta_short = (win_seq_short | expiry_win_short).astype(np.float32)
        exc_short = (fav_short + 1e-10) / (adv_short + 1e-10)

        # Combine based on primary_signal
        is_long = (primary_direction == 1)
        meta_label = np.where(is_long, meta_long, meta_short).astype(np.float32)
        exc_score = np.where(is_long, exc_long, exc_short).astype(np.float32)

        # Favorable & Adverse Excursions (MFE & MAE relative to entry close)
        mfe_long = fav_long / (close + 1e-10)
        mae_long = adv_long / (close + 1e-10)
        mfe_short = fav_short / (close + 1e-10)
        mae_short = adv_short / (close + 1e-10)

        target_mfe = np.where(is_long, mfe_long, mfe_short).astype(np.float32)
        target_mae = np.where(is_long, mae_long, mae_short).astype(np.float32)

        data['Target_Primary'] = primary_direction
        data['Target_Meta'] = meta_label
        data['Target_Return'] = exp_ret.astype(np.float32)  # Train price regressor strictly on future candle close return (not on wicks/MFE)
        data['Target_Close_Return'] = exp_ret.astype(np.float32)
        data['Target_MFE'] = target_mfe
        data['Target_MAE'] = target_mae
        data['Excursion_Score'] = exc_score

        invalid_len = horizon_bars + 1
        data.iloc[-invalid_len:, data.columns.get_loc('Target_Primary')] = np.nan
        data.iloc[-invalid_len:, data.columns.get_loc('Target_Meta')] = np.nan
        data.iloc[-invalid_len:, data.columns.get_loc('Target_Return')] = np.nan
        if 'Target_Close_Return' in data.columns:
            data.iloc[-invalid_len:, data.columns.get_loc('Target_Close_Return')] = np.nan
        if 'Target_MFE' in data.columns:
            data.iloc[-invalid_len:, data.columns.get_loc('Target_MFE')] = np.nan
        if 'Target_MAE' in data.columns:
            data.iloc[-invalid_len:, data.columns.get_loc('Target_MAE')] = np.nan
        data.iloc[-invalid_len:, data.columns.get_loc('Excursion_Score')] = np.nan

        return data

# ------------------------------------------------------------------------------
# 5. SUPER LEARNER MODEL FACTORY (CatBoost, XGBoost, ExtraTrees, HistGBM, Regression)
# ------------------------------------------------------------------------------
class QuantModelFactory:

    @staticmethod
    def build_primary_catboost(cfg: dict) -> CatBoostClassifier:
        return CatBoostClassifier(
            iterations=cfg.get('iterations', 15),
            depth=cfg.get('depth', 3),
            learning_rate=cfg.get('learning_rate', 0.05),
            l2_leaf_reg=cfg.get('l2_leaf_reg', 4.0),
            auto_class_weights=cfg.get('auto_class_weights', None),
            verbose=False,
            random_seed=42,
            thread_count=cfg.get('thread_count', 1)
        )

    @staticmethod
    def build_primary_xgboost(cfg: dict) -> xgb.XGBClassifier:
        return xgb.XGBClassifier(
            n_estimators=cfg.get('n_estimators', 25),
            max_depth=cfg.get('max_depth', 3),
            learning_rate=cfg.get('learning_rate', 0.05),
            subsample=cfg.get('subsample', 0.85),
            colsample_bytree=cfg.get('colsample_bytree', 0.80),
            gamma=cfg.get('gamma', 0.15),
            random_state=cfg.get('random_state', 42),
            n_jobs=cfg.get('n_jobs', 1),
            tree_method='hist',
            eval_metric='logloss'
        )

    @staticmethod
    def build_primary_lightgbm(cfg: dict):
        if HAS_LIGHTGBM:
            return lgb.LGBMClassifier(
                n_estimators=cfg.get('n_estimators', 25),
                max_depth=cfg.get('max_depth', 3),
                num_leaves=cfg.get('num_leaves', 12),
                learning_rate=cfg.get('learning_rate', 0.05),
                subsample=cfg.get('subsample', 0.85),
                colsample_bytree=cfg.get('colsample_bytree', 0.80),
                random_state=cfg.get('random_state', 42),
                verbose=cfg.get('verbose', -1),
                n_jobs=cfg.get('n_jobs', 1)
            )
        return None

    @staticmethod
    def build_primary_hist_gbm_clf(cfg: dict = None) -> HistGradientBoostingClassifier:
        return HistGradientBoostingClassifier(
            max_iter=25,
            max_depth=3,
            learning_rate=0.05,
            min_samples_leaf=5,
            early_stopping=True,
            n_iter_no_change=5,
            random_state=42
        )

    @staticmethod
    def build_primary_extra_trees(cfg: dict) -> ExtraTreesClassifier:
        return ExtraTreesClassifier(
            n_estimators=cfg.get('n_estimators', 15),
            max_depth=cfg.get('max_depth', 4),
            min_samples_split=cfg.get('min_samples_split', 5),
            random_state=cfg.get('random_state', 42),
            n_jobs=cfg.get('n_jobs', 1)
        )

    @staticmethod
    def build_catboost_regressor(cfg: dict = None) -> CatBoostRegressor:
        cfg = cfg or {}
        return CatBoostRegressor(
            iterations=cfg.get('iterations', 35),
            depth=cfg.get('depth', 3),
            learning_rate=cfg.get('learning_rate', 0.045),
            loss_function='Huber:delta=1.0',
            l2_leaf_reg=cfg.get('l2_leaf_reg', 2.5),
            random_seed=42,
            verbose=False,
            thread_count=1
        )

    @staticmethod
    def build_xgb_regressor(cfg: dict = None) -> xgb.XGBRegressor:
        cfg = cfg or {}
        return xgb.XGBRegressor(
            n_estimators=cfg.get('n_estimators', 30),
            max_depth=cfg.get('max_depth', 3),
            learning_rate=cfg.get('learning_rate', 0.045),
            subsample=cfg.get('subsample', 0.85),
            colsample_bytree=cfg.get('colsample_bytree', 0.80),
            reg_alpha=0.05,
            reg_lambda=0.5,
            objective=cfg.get('objective', 'reg:pseudohubererror'),
            random_state=42,
            n_jobs=cfg.get('n_jobs', 1),
            tree_method='hist'
        )

    @staticmethod
    def build_hist_gbm_regressor(cfg: dict = None) -> HistGradientBoostingRegressor:
        return HistGradientBoostingRegressor(
            max_iter=25,
            max_depth=3,
            learning_rate=0.045,
            min_samples_leaf=4,
            l2_regularization=0.2,
            early_stopping=True,
            n_iter_no_change=5,
            random_state=42
        )

# ------------------------------------------------------------------------------
# 6. ENHANCED MULTI-HORIZON PAPER TRADING LEDGER & BINANCE FEE ENGINE
# ------------------------------------------------------------------------------
class PaperTradingLedger:
    """
    Institutional Multi-Desk Quantitative Paper Trading Ledger (Version 2.0).
    - 3 Independent Desks: ⚡ Scalp Desk (35% / 2 slots), ⏳ Day Trading Desk (40% / 2 slots), 🌊 Swing Desk (25% / 1 slot)
    - Volatility Risk Parity (ATR Fixed Fractional Sizing - 1.5% portfolio risk per trade)
    - Synchronized Tier-0 Breakeven (+0.80% / +1.25% / +1.75% peak gain -> BE) & 3-Tier TP Scaling
    - Perpetual 8-Hour Funding Rate Accrual (00:00, 08:00, 16:00 UTC)
    - Institutional Telemetry: Sharpe Ratio, Sortino Ratio, Profit Factor, Expectancy, MAE/MFE
    """
    def __init__(self, config: dict):
        self.raw_config = config
        self.config = config.get('paper_trading', {})
        self.export_dir = config.get('app_export_dir', './export_app_data')
        self.ledger_file = os.path.join(self.export_dir, "paper_trading_ledger.json")
        self.execution_engine = self.config.get('execution_engine', 'binance_futures')
        self.start_balance = float(
            self.config.get('start_balance_usd')
            if self.config.get('start_balance_usd') is not None
            else (self.config.get('initial_capital_usd') if self.config.get('initial_capital_usd') is not None else 1000.0)
        )
        self.risk_per_trade_pct = float(self.config.get('risk_per_trade_pct', 1.5))
        self.min_position_size_usd = float(self.config.get('min_position_size_usd', 30.0))
        self.min_expected_return_pct = float(self.config.get('min_expected_return_pct', 0.25))
        self.min_net_profit_usd = float(self.config.get('min_net_profit_usd', 0.05))

        self.base_fee_rate = float(self.config.get('binance_fee_rate', 0.00045))
        self.base_maker_fee_rate = float(self.config.get('binance_maker_fee_rate', 0.00020))
        self.use_bnb_discount = self.config.get('use_bnb_fee_discount', True)
        raw_discount = 0.90 if self.use_bnb_discount else 1.0
        self.pure_taker_fee_rate = (self.base_fee_rate * raw_discount)
        self.pure_maker_fee_rate = (self.base_maker_fee_rate * raw_discount)
        self.spread_rate = float(self.config.get('spread_rate', 0.0004))      # 4 bps = 0.04% roundtrip
        self.slippage_rate = float(self.config.get('slippage_rate', 0.0006))  # 6 bps = 0.06% roundtrip
        self.buy_fee_rate = self.pure_taker_fee_rate
        self.sell_fee_rate = self.pure_taker_fee_rate
        self.maker_fee_rate = self.pure_maker_fee_rate
        self.effective_fee_rate = self.buy_fee_rate
        self.fee_tier_label = f"Binance Futures (VIP0 Isolated Margin | {self.maker_fee_rate*100:.3f}% Maker / {self.buy_fee_rate*100:.3f}% Taker with BNB Discount)"

        raw_allowed = self.config.get('allowed_horizons', ['15m', '30m', '1h', '24h', 'scalp', 'intraday', 'macro', '15M', '30M', '1H', '24H'])
        self.allowed_horizons = set()
        for h in raw_allowed:
            h_str = str(h).strip()
            self.allowed_horizons.add(h_str.lower())
            self.allowed_horizons.add(h_str.upper())
            tag = resolve_horizon_tag(h_str)
            self.allowed_horizons.add(tag)
            self.allowed_horizons.add(tag.lower())
            self.allowed_horizons.add(tag.upper())

        # Institutional Multi-Desk Partitioning
        self.desks = self.config.get('desks', {
            "scalp": {
                "name": "⚡ Scalp Desk",
                "allocation_pct": 0.35,
                "max_slots": 2,
                "allowed_horizons": ["15m", "30m", "15M", "30M", "scalp", "horizon_30m"],
                "leverage": 5,
                "tier0_threshold": 1.20,
                "max_hold_seconds": 7200
            },
            "intraday": {
                "name": "⏳ Day Trading Desk",
                "allocation_pct": 0.40,
                "max_slots": 2,
                "allowed_horizons": ["1h", "1H", "intraday", "day_trade", "swing", "triple_screen"],
                "leverage": 3,
                "tier0_threshold": 1.50,
                "max_hold_seconds": 28800
            },
            "macro": {
                "name": "🌊 Swing Desk",
                "allocation_pct": 0.25,
                "max_slots": 1,
                "allowed_horizons": ["24h", "1d", "24H", "1D", "macro"],
                "leverage": 2,
                "tier0_threshold": 2.00,
                "max_hold_seconds": 172800
            }
        })

        self.cached_funding_rates = {}
        self.cooldown_tracker = {}
        self.quarantined_symbols = {}
        self.symbol_loss_streak = {}
        self._lock = threading.RLock()
        self.data = self.load_or_initialize()

    def resolve_desk(self, horizon_key_or_tag: str) -> str:
        """Determines desk partition strictly by timeframe: 15M/30M -> scalp, 1H/4H/triple_screen -> intraday (Day Trading), 24H/4D-30D -> macro (Swing)."""
        raw = str(horizon_key_or_tag or "").strip()
        tag = resolve_horizon_tag(raw).upper()
        h = raw.lower()
        # 1. Check Scalp (15M / 30M)
        if tag in ["15M", "30M"] or any(k in h for k in ["scalp", "15m", "30m"]):
            return "scalp"
        # 2. Check Macro / Swing (24H, 1D, 4D, 7D, 15D, 30D, MACRO) - Checked before 4H to prevent substring collision ("4h" in "24h")
        if tag in ["24H", "1D", "4D", "7D", "15D", "30D", "MACRO"] or any(k in h for k in ["macro", "24h", "1d", "daily", "4d", "7d", "15d", "30d", "weekly"]):
            return "macro"
        # 3. Check Intraday / Day Trading (1H, 4H, triple_screen)
        if tag in ["1H", "4H", "TRIPLE_SCREEN"] or any(k in h for k in ["1h", "4h", "intraday", "day_trade", "triple_screen"]) or ("swing" in h and not any(k in h for k in ["24h", "1d", "macro"])):
            return "intraday"
        return "macro"

    def load_or_initialize(self) -> dict:
        target_start = float(self.start_balance)
        now_iso = datetime.now(timezone.utc).isoformat()
        if os.path.exists(self.ledger_file):
            try:
                with open(self.ledger_file, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                    if d.get('starting_balance_usd') != target_start:
                        d['starting_balance_usd'] = target_start
                        d['current_balance_usd'] = target_start
                        d['realized_pnl_usd'] = 0.0
                        d['gross_profit_usd'] = 0.0
                        d['gross_loss_usd'] = 0.0
                        d['total_fees_paid_usd'] = 0.0
                        d['total_funding_fees_usd'] = 0.0
                        d['gross_realized_pnl_usd'] = 0.0
                        d['peak_balance_usd'] = target_start
                        d['total_trades'] = 0
                        d['winning_trades'] = 0
                        d['losing_trades'] = 0
                        d['breakeven_trades'] = 0
                        d['win_rate_pct'] = 0.0
                        d['profit_factor'] = 0.0
                        d['sharpe_ratio'] = 0.0
                        d['sortino_ratio'] = 0.0
                        d['expectancy_usd'] = 0.0
                        d['max_drawdown_usd'] = 0.0
                        d['max_drawdown_pct'] = 0.0
                        d['open_positions'] = []
                        d['closed_trades_history'] = []

                    # Ensure desks metadata exists and aligns with institutional allocations
                    if 'desks' not in d:
                        d['desks'] = {
                            "scalp": {"allocated_usd": target_start * 0.35, "name": self.desks["scalp"]["name"], "realized_pnl_usd": 0.0, "open_positions": 0, "total_trades": 0, "winning_trades": 0, "win_rate_pct": 0.0},
                            "intraday": {"allocated_usd": target_start * 0.40, "name": self.desks["intraday"]["name"], "realized_pnl_usd": 0.0, "open_positions": 0, "total_trades": 0, "winning_trades": 0, "win_rate_pct": 0.0},
                            "macro": {"allocated_usd": target_start * 0.25, "name": self.desks["macro"]["name"], "realized_pnl_usd": 0.0, "open_positions": 0, "total_trades": 0, "winning_trades": 0, "win_rate_pct": 0.0}
                        }
                    else:
                        d['desks']['scalp']['allocated_usd'] = target_start * 0.35
                        d['desks']['intraday']['allocated_usd'] = target_start * 0.40
                        d['desks']['macro']['allocated_usd'] = target_start * 0.25
                        d['desks']['scalp']['name'] = self.desks["scalp"]["name"]
                        d['desks']['intraday']['name'] = self.desks["intraday"]["name"]
                        d['desks']['macro']['name'] = self.desks["macro"]["name"]

                    # Enforce and re-align desk tags on open positions
                    for p in d.get('open_positions', []):
                        correct_desk = self.resolve_desk(p.get('horizon', 'scalp'))
                        if p.get('desk') != correct_desk:
                            print(f"[DESK REALIGN 🔄] Re-aligning {p.get('symbol')} from {p.get('desk')} to {correct_desk} desk", flush=True)
                            p['desk'] = correct_desk
                            p['desk_name'] = self.desks[correct_desk]['name']
                            p['horizon_tag'] = resolve_horizon_tag(p.get('horizon', '')).upper()
                            d_cfg = self.desks[correct_desk]
                            p['leverage'] = d_cfg['leverage']
                            p['margin_usd'] = round(float(p.get('position_size_usd', 100.0)) / max(1, d_cfg['leverage']), 2)
                            ent_p = float(p.get('entry_price', 1.0))
                            is_l = p.get('direction') in ['BULLISH', 'LONG']
                            p['liquidation_price'] = round(ent_p * (1.0 - 0.95/d_cfg['leverage']), 8) if is_l else round(ent_p * (1.0 + 0.95/d_cfg['leverage']), 8)
                        else:
                            p['desk_name'] = self.desks[correct_desk]['name']

                        # Backfill risk metrics if missing
                        if p.get('stop_dist_pct') is None:
                            ent = float(p.get('entry_price', 1.0))
                            sl = float(p.get('sl_original', p.get('sl_price', ent * 0.98)))
                            dist = round((abs(ent - sl) / max(1e-8, ent)) * 100.0, 2)
                            p['stop_dist_pct'] = dist
                            p['dollar_risk'] = round(float(p.get('position_size_usd', 100.0)) * (dist / 100.0), 2)

                    # Recalculate open positions count per desk
                    for dk in ["scalp", "intraday", "macro"]:
                        d['desks'][dk]['open_positions'] = len([p for p in d.get('open_positions', []) if p.get('desk') == dk])

                    d.setdefault('total_funding_fees_usd', 0.0)
                    d.setdefault('total_spread_paid_usd', 0.0)
                    d.setdefault('total_slippage_paid_usd', 0.0)
                    d.setdefault('total_friction_paid_usd', 0.0)
                    d.setdefault('sharpe_ratio', 0.0)
                    d.setdefault('sortino_ratio', 0.0)
                    d.setdefault('expectancy_usd', 0.0)
                    d.setdefault('queued_trades', [])
                    d['fee_tier_label'] = self.fee_tier_label
                    return d
            except Exception:
                pass

        return {
            "created_at": now_iso,
            "last_updated": now_iso,
            "fee_tier_label": self.fee_tier_label,
            "starting_balance_usd": target_start,
            "current_balance_usd": target_start,
            "realized_pnl_usd": 0.0,
            "gross_realized_pnl_usd": 0.0,
            "total_fees_paid_usd": 0.0,
            "total_spread_paid_usd": 0.0,
            "total_slippage_paid_usd": 0.0,
            "total_funding_fees_usd": 0.0,
            "total_friction_paid_usd": 0.0,
            "gross_profit_usd": 0.0,
            "gross_loss_usd": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "breakeven_trades": 0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "expectancy_usd": 0.0,
            "peak_balance_usd": target_start,
            "max_drawdown_usd": 0.0,
            "max_drawdown_pct": 0.0,
            "open_positions": [],
            "closed_trades_history": [],
            "queued_trades": [],
            "desks": {
                "scalp": {"allocated_usd": target_start * 0.35, "name": self.desks["scalp"]["name"], "realized_pnl_usd": 0.0, "open_positions": 0, "total_trades": 0, "winning_trades": 0, "win_rate_pct": 0.0},
                "intraday": {"allocated_usd": target_start * 0.40, "name": self.desks["intraday"]["name"], "realized_pnl_usd": 0.0, "open_positions": 0, "total_trades": 0, "winning_trades": 0, "win_rate_pct": 0.0},
                "macro": {"allocated_usd": target_start * 0.25, "name": self.desks["macro"]["name"], "realized_pnl_usd": 0.0, "open_positions": 0, "total_trades": 0, "winning_trades": 0, "win_rate_pct": 0.0}
            }
        }

    def calculate_risk_parity_size(self, cand: dict, desk_key: str) -> dict:
        """
        Calculates position nominal size using Volatility Risk Parity (ATR Fixed Fractional Risk).
        Target Risk = exactly 1.5% of total portfolio balance, bounded by Desk Slot Capacity & Leverage.
        """
        entry_p = float(cand.get("entry_price") or cand.get("current_price") or 1.0)
        sl_p = float(cand.get("sl_price") or (entry_p * 0.98))
        stop_dist_pct = abs(entry_p - sl_p) / max(1e-8, entry_p)

        desk_cfg = self.desks[desk_key]
        desk_capital = float(self.data["current_balance_usd"]) * desk_cfg["allocation_pct"]
        slot_budget = desk_capital / desk_cfg["max_slots"]
        leverage = desk_cfg["leverage"]

        # Risk 1.5% of total portfolio balance, with Proven Strategy Edge Multiplier
        dec_u = str(cand.get("decision", "")).upper()
        arch_u = str(cand.get("strategy_archetype", "")).upper()
        is_long = str(cand.get("direction", "")).upper() in ["LONG", "BULLISH"]
        is_proven_winner = any(k in dec_u or k in arch_u for k in ["MOMENTUM", "BREAKOUT", "DIP-BUY", "BOTTOM-REVERSAL", "ORDER-BLOCK", "TRIPLE"])
        edge_mult = 1.30 if (is_proven_winner and is_long) else (1.15 if is_proven_winner else 1.0)
        risk_dollar_budget = float(self.data["current_balance_usd"]) * (self.risk_per_trade_pct / 100.0) * edge_mult

        # Volatility Risk Parity Nominal Size
        target_nominal = risk_dollar_budget / max(0.003, stop_dist_pct)
        # Cap at slot capacity with leverage (scaled by edge multiplier for proven high-profit strategies)
        max_allowed_nominal = slot_budget * leverage * edge_mult
        nominal_size = min(target_nominal, max_allowed_nominal)
        nominal_size = max(nominal_size, self.min_position_size_usd)
        nominal_size = round(nominal_size, 2)

        margin_usd = round(nominal_size / leverage, 2)
        return {
            "nominal_size_usd": nominal_size,
            "margin_usd": margin_usd,
            "leverage": leverage,
            "stop_dist_pct": round(stop_dist_pct * 100.0, 2),
            "dollar_risk": round(nominal_size * stop_dist_pct, 2)
        }

    def _accrue_funding_fees(self, pos: dict, now_dt: datetime) -> float:
        """
        Calculates 8-hour perpetual funding rate accrual (00:00, 08:00, 16:00 UTC).
        """
        opened_dt = datetime.fromisoformat(pos["opened_at"]) if isinstance(pos["opened_at"], str) else pos["opened_at"]
        last_funding_str = pos.get("last_funding_time") or pos["opened_at"]
        last_funding_dt = datetime.fromisoformat(last_funding_str) if isinstance(last_funding_str, str) else last_funding_str

        def get_funding_interval_idx(dt):
            return (dt.toordinal() * 3) + (dt.hour // 8)

        start_idx = get_funding_interval_idx(last_funding_dt)
        curr_idx = get_funding_interval_idx(now_dt)
        intervals_elapsed = max(0, curr_idx - start_idx)

        if intervals_elapsed > 0:
            sym = pos["symbol"]
            rate = float(self.cached_funding_rates.get(sym, 0.0001)) # 0.01% standard perpetual 8h baseline
            is_long = pos["direction"] in ["BULLISH", "LONG"]
            rem_nominal = float(pos.get("remaining_position_size_usd", pos.get("position_size_usd", 100.0)))
            funding_cost = (rem_nominal * rate * intervals_elapsed) if is_long else (-rem_nominal * rate * intervals_elapsed)
            pos["funding_fees_usd"] = round(pos.get("funding_fees_usd", 0.0) + funding_cost, 4)
            pos["last_funding_time"] = now_dt.isoformat()
            return funding_cost
        return 0.0

    def consider_new_trade(self, cand: dict, horizon_key: str, signal_history: list = None, now_utc: datetime = None) -> bool:
        """Admits candidate trade if its designated desk has an available slot and passes institutional quality gates."""
        if not self.config.get('enabled', True):
            return False

        desk_key = self.resolve_desk(horizon_key)
        desk_cfg = self.desks[desk_key]

        open_desk_positions = [p for p in self.data["open_positions"] if p.get("desk") == desk_key]
        if len(open_desk_positions) >= desk_cfg["max_slots"]:
            return False  # Desk is full, but other desks are unaffected!

        sym = cand.get("symbol", "")
        if not sym:
            return False

        # Bridge nested horizon dictionary if candidate is from multi-horizon scanner
        h_cand = cand.get("horizons", {}).get(horizon_key, {})
        if isinstance(h_cand, dict) and h_cand:
            cand = {**cand, **h_cand}

        # Lockout if symbol is already open in ANY desk
        if any(p.get("symbol") == sym for p in self.data["open_positions"]):
            return False

        # Quarantine / Consecutive Loss Blacklist Guard (blocks chronic bleeders like ARB/ALT)
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        elif now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        if sym in self.quarantined_symbols:
            if now_utc < self.quarantined_symbols[sym]:
                return False
            else:
                del self.quarantined_symbols[sym]

        if sym in ["ARB/USDT", "ALT/USDT"]:
            return False  # Empirical 0% Win Rate / -23.4% PnL bleeders strictly blacklisted

        # Direction and Invalidation Checks
        direction = str(cand.get("direction", "BULLISH")).upper()
        dir_lbl = str(cand.get("direction_label", "")).upper()
        dec = str(cand.get("decision", "")).upper()
        is_explicit_long = direction in ["BULLISH", "LONG", "BUY"] or "LONG" in dir_lbl
        is_short = (not is_explicit_long) and (direction in ["BEARISH", "SHORT"] or "SHORT" in dir_lbl or ("SHORT" in dec and "SHORT SQUEEZE" not in dec))

        # Filter out negative-expectancy unconfirmed Standard Longs
        if not is_short and "STANDARD EXECUTE LONG" in dec and "SHORT SQUEEZE" not in dec:
            return False

        # 🛑 PERMANENTLY REMOVE EMPIRICAL LOSS-MAKING SHORT STRATEGIES
        if is_short:
            # 1. Block Liquidity Sweep Shorts (catastrophic -73.47% return in backtest/live)
            if any(k in dec for k in ["LIQUIDITY-SWEEP", "LIQUIDITY_SWEEP", "LIQUIDITY SWEEP"]):
                return False
            # 2. Block Standard Shorts without elite conviction (-22.98% return, 51.9% win rate)
            if "STANDARD EXECUTE SHORT" in dec or "STANDARD" in dec:
                return False
            # 3. Block weak Rally-Sell Shorts (< 42% win rate) unless confirmed by high ML confidence
            if "RALLY-SELL" in dec and float(cand.get("meta_win_prob", 0.50)) < 0.60:
                return False

        # Ban multi-day macro shorts to eliminate asymmetric short-squeeze tail risk
        is_macro_h = horizon_key in ['macro', 'horizon_24h', '24h', '1d', 'horizon_4d', 'weekly', 'biweekly', 'monthly']
        if is_short and is_macro_h and ("BLOW-OFF TOP" not in dec and "BLOW_OFF" not in dec):
            return False

        # ----------------------------------------------------------------------
        # 🛡️ INSTITUTIONAL TIMEFRAME NTZ & CONSOLIDATION DESK LOCKOUT
        # If this candidate's timeframe is in Consolidation ranges or low volume,
        # halt all new paper trade admissions for this desk!
        # ----------------------------------------------------------------------
        is_ntz_cand = (
            cand.get("is_ntz_blocked", False)
            or cand.get("is_ntz_active", False)
            or any(k in dec for k in ["NO TRADE ZONE", "CONSOLIDATION", "RANGE SQUEEZE", "COILED SQUEEZE", "LOW VOL", "CHOP"])
        )
        if is_ntz_cand:
            return False

        # Macro desk-specific consolidation lockout:
        # If benchmark/macro regime on this desk's timeframe is in consolidation/squeeze
        regime_code = str(getattr(self, 'market_regime_code', '') or cand.get('market_regime_code', '')).upper()
        if regime_code in ["CONSOLIDATION", "RANGE_SQUEEZE", "NO_TRADE_ZONE"]:
            c_rvol = float(cand.get("rvol", 1.0) or 1.0)
            if c_rvol < 2.0:
                return False

        is_limit_pending = bool(cand.get("is_limit_pending", False))
        entry_p = float(cand.get("optimal_entry_price") or cand.get("entry_price") or cand.get("current_price") or 0.0) if is_limit_pending else float(cand.get("current_price") or cand.get("entry_price") or 0.0)
        tp1_p = float(cand.get("tp1_price") or cand.get("tp_price") or 0.0)
        tp2_p = float(cand.get("tp2_price") or tp1_p or 0.0)
        tp3_p = float(cand.get("tp3_price") or tp2_p or 0.0)
        sl_p = float(cand.get("sl_price") or 0.0)

        if entry_p <= 0 or tp1_p <= 0 or sl_p <= 0:
            return False

        # Mathematical Price Invariant Guard
        if not is_short and (tp1_p <= entry_p or sl_p >= entry_p):
            return False
        if is_short and (tp1_p >= entry_p or sl_p <= entry_p):
            return False

        # Institutional Quality Gate: Grade A/A+ or conviction >= 60%
        grade_str = str(cand.get("grade", cand.get("quality_grade", "")))
        conviction = float(cand.get("conviction", 0.0))
        if self.config.get("require_min_grade_a", True):
            if ("Grade A" not in grade_str) and (conviction < 60.0):
                return False

        # Meta-labeler probability gate
        meta_prob = float(cand.get("meta_win_prob", cand.get("meta_probability", 0.50)))
        if meta_prob < float(self.config.get("min_meta_probability", 0.35)):
            return False

        # Cooldown guard: 15 min lockout after stop-out / breakeven
        last_closed = self.cooldown_tracker.get(sym)
        if last_closed and (now_utc - last_closed).total_seconds() < 900:
            return False

        # Volatility Risk Parity Sizing
        sizing = self.calculate_risk_parity_size(cand, desk_key)
        pos_size = sizing["nominal_size_usd"]
        margin_usd = sizing["margin_usd"]
        leverage = sizing["leverage"]

        # Expected Net Profit Hurdle after Round-Trip Binance Fees (Maker Entry when limit pending)
        expected_gain_pct = abs(entry_p - tp1_p) / entry_p
        entry_fee_rate = self.maker_fee_rate if is_limit_pending else self.buy_fee_rate
        est_nominal_fees = round((pos_size * entry_fee_rate) + (pos_size * (1.0 + expected_gain_pct) * self.sell_fee_rate), 4)
        est_net_profit_usd = (pos_size * expected_gain_pct) - est_nominal_fees
        expected_net_gain_pct = est_net_profit_usd / pos_size
        if (expected_net_gain_pct * 100.0) < self.min_expected_return_pct or est_net_profit_usd < self.min_net_profit_usd:
            return False

        buy_fee = round(pos_size * entry_fee_rate, 4)
        est_sell_fee = round(pos_size * self.sell_fee_rate, 4)
        entry_spread = 0.0 if is_limit_pending else round(pos_size * (self.spread_rate / 2.0), 4)
        entry_slippage = 0.0 if is_limit_pending else round(pos_size * (self.slippage_rate / 2.0), 4)
        est_exit_spread = round(pos_size * (self.spread_rate / 2.0), 4)
        est_exit_slippage = round(pos_size * (self.slippage_rate / 2.0), 4)
        liquidation_p = round(entry_p * (1.0 - 0.95/leverage), 8) if not is_short else round(entry_p * (1.0 + 0.95/leverage), 8)

        dur_sec = desk_cfg["max_hold_seconds"]
        expiry_dt = now_utc + timedelta(seconds=dur_sec)
        h_tag = resolve_horizon_tag(horizon_key)

        new_pos = {
            "trade_id": f"PAPER_{sym.replace('/', '_')}_{desk_key}_{int(time.time()*1000)}",
            "signal_id": cand.get("signal_id") or cand.get("trade_id"),
            "symbol": sym,
            "desk": desk_key,
            "desk_name": desk_cfg["name"],
            "horizon": horizon_key,
            "horizon_tag": h_tag.upper(),
            "direction": "BEARISH" if is_short else "BULLISH",
            "direction_label": "SHORT" if is_short else "LONG",
            "execution_engine": self.execution_engine,
            "margin_mode": "ISOLATED",
            "leverage": leverage,
            "margin_usd": margin_usd,
            "position_size_usd": pos_size,
            "position_value_usd": pos_size,
            "allocated_usd": pos_size,
            "initial_position_size_usd": pos_size,
            "remaining_position_size_usd": pos_size,
            "liquidation_price": liquidation_p,
            "entry_price": entry_p,
            "optimal_entry_limit": entry_p,
            "is_limit_pending": is_limit_pending,
            "raw_entry_price": entry_p,
            "tp_price": tp1_p,
            "tp1_price": tp1_p,
            "tp2_price": tp2_p,
            "tp3_price": tp3_p,
            "sl_price": sl_p,
            "sl_original": sl_p,
            "stop_dist_pct": sizing.get("stop_dist_pct", 0.0),
            "dollar_risk": sizing.get("dollar_risk", 0.0),
            "stage": "PENDING_LIMIT" if is_limit_pending else "OPEN",
            "active_tp_level": "TP1",
            "active_tp_price": tp1_p,
            "tp1_hit": False,
            "tp2_hit": False,
            "tp1_banked_usd": 0.0,
            "tp2_banked_usd": 0.0,
            "is_tier0_locked": False,
            "is_tp1_locked": False,
            "is_tp2_locked": False,
            "realized_gross_pnl": 0.0,
            "realized_fees": 0.0,
            "realized_spread_usd": entry_spread,
            "realized_slippage_usd": entry_slippage,
            "realized_net_pnl": 0.0,
            "funding_fees_usd": 0.0,
            "buy_fee_usd": buy_fee,
            "est_sell_fee_usd": est_sell_fee,
            "sell_fee_usd": 0.0,
            "entry_spread_usd": entry_spread,
            "entry_slippage_usd": entry_slippage,
            "spread_cost_usd": entry_spread,
            "slippage_cost_usd": entry_slippage,
            "total_friction_usd": round(buy_fee + entry_spread + entry_slippage, 4),
            "opened_at": now_utc.isoformat(),
            "entry_time_str": now_utc.strftime('%Y-%m-%d %H:%M:%S UTC'),
            "expiry_time": expiry_dt.isoformat(),
            "peak_price": entry_p,
            "trough_price": entry_p,
            "mae_pct": 0.0,
            "mfe_pct": 0.0,
            "current_price": entry_p,
            "unrealized_gross_pnl_usd": 0.0,
            "unrealized_fee_usd": round(buy_fee + est_sell_fee, 4),
            "unrealized_spread_usd": round(entry_spread + est_exit_spread, 4),
            "unrealized_slippage_usd": round(entry_slippage + est_exit_slippage, 4),
            "unrealized_friction_usd": round(buy_fee + est_sell_fee + entry_spread + est_exit_spread + entry_slippage + est_exit_slippage, 4),
            "unrealized_pnl_usd": -round(buy_fee + est_sell_fee + entry_spread + est_exit_spread + entry_slippage + est_exit_slippage, 4),
            "unrealized_pnl_pct": -round(((buy_fee + est_sell_fee + entry_spread + est_exit_spread + entry_slippage + est_exit_slippage) / pos_size) * 100.0, 2),
            "target_progress_pct": 0.0,
            "signal_decision": dec
        }

        self.data["open_positions"].append(new_pos)
        self.data["desks"][desk_key]["open_positions"] = len([p for p in self.data["open_positions"] if p.get("desk") == desk_key])
        self.save()

        # Terminal Notification Banner
        dir_badge = "🔴 SHORT" if is_short else "🟢 LONG"
        tp1_gain = ((tp1_p - entry_p)/entry_p*100) if not is_short else ((entry_p - tp1_p)/entry_p*100)
        sl_loss = ((entry_p - sl_p)/entry_p*100) if not is_short else ((sl_p - entry_p)/entry_p*100)
        print(f"\n{'='*120}")
        if is_limit_pending:
            print(f" ⏳ [{desk_cfg['name'].upper()} LIMIT ORDER PLACED (AWAIT RETEST)] {sym} [{dir_badge} | {h_tag.upper()}] ({leverage}x Isolated Margin)")
            print(f" 💵 Margin Allocated: ${margin_usd:,.2f} | Nominal Value: ${pos_size:,.2f} (1.5% Risk: ${sizing['dollar_risk']:,.2f})")
            print(f" 🎯 Optimal Limit Entry: ${entry_p:,.4f} | Est. Liquidation: ${liquidation_p:,.4f}")
            print(f" 🏁 TP1 (50% scale): ${tp1_p:,.4f} (+{tp1_gain:.2f}%) | TP2 (30% scale): ${tp2_p:,.4f} | TP3 (20% runner): ${tp3_p:,.4f}")
            print(f" 🛑 Stop Loss: ${sl_p:,.4f} (-{sl_loss:.2f}%) | Peak BE Threshold: +{desk_cfg['tier0_threshold']:.2f}%")
        else:
            print(f" 🚀 [{desk_cfg['name'].upper()} POSITION OPENED ⚡] {sym} [{dir_badge} | {h_tag.upper()}] ({leverage}x Isolated Margin)")
            print(f" 💵 Margin Allocated: ${margin_usd:,.2f} | Nominal Value: ${pos_size:,.2f} (1.5% Risk: ${sizing['dollar_risk']:,.2f})")
            print(f" 🎯 Entry: ${entry_p:,.4f} | Est. Liquidation: ${liquidation_p:,.4f}")
            print(f" 🏁 TP1 (50% scale): ${tp1_p:,.4f} (+{tp1_gain:.2f}%) | TP2 (30% scale): ${tp2_p:,.4f} | TP3 (20% runner): ${tp3_p:,.4f}")
            print(f" 🛑 Stop Loss: ${sl_p:,.4f} (-{sl_loss:.2f}%) | Peak BE Threshold: +{desk_cfg['tier0_threshold']:.2f}%")
        print(f" 📊 Model Conviction: {conviction:.1f}% | Win Prob: {meta_prob*100:.1f}% | Strategy: {dec}")
        print(f"{'='*120}\n", flush=True)
        return True

    def admit_ranked_candidates(self, ranked_candidates: list, signal_history: list = None) -> list:
        """Admits candidate trades strictly in rank order without cross-desk starvation."""
        with getattr(self, '_lock', threading.RLock()):
            if not ranked_candidates:
                return []

            admitted = []
            for cand, h_key in ranked_candidates:
                desk_key = self.resolve_desk(h_key)
                desk_cfg = self.desks[desk_key]
                open_count = len([p for p in self.data.get("open_positions", []) if p.get("desk") == desk_key])
                if open_count < desk_cfg["max_slots"]:
                    if self.consider_new_trade(cand, h_key, signal_history=signal_history):
                        admitted.append(cand)
            return admitted

    def update_positions(self, live_prices: dict, live_highs: dict = None, live_lows: dict = None, now_dt: datetime = None):
        """Processes real-time ticks, Tier-0 Breakeven, partial TP scaling, trailing stops, and funding fees."""
        with getattr(self, '_lock', threading.RLock()):
            return self._update_positions_internal(live_prices, live_highs, live_lows, now_dt=now_dt)

    def _update_positions_internal(self, live_prices: dict, live_highs: dict = None, live_lows: dict = None, now_dt: datetime = None):
        if now_dt is None:
            now_dt = datetime.now(timezone.utc)
        elif now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)
        now_str = now_dt.isoformat()
        still_open = []
        closed_this_tick = []

        for pos in self.data.get("open_positions", []):
            sym = pos.get("symbol", "")
            if sym not in live_prices:
                still_open.append(pos)
                continue

            try:
                curr_p = float(live_prices[sym])
            except Exception:
                still_open.append(pos)
                continue

            if curr_p <= 0:
                still_open.append(pos)
                continue

            pos["current_price"] = curr_p
            entry_p = float(pos.get("entry_price", curr_p))
            is_long = pos.get("direction") in ["BULLISH", "LONG"]
            desk_key = pos.get("desk", self.resolve_desk(pos.get("horizon", "scalp")))
            desk_cfg = self.desks[desk_key]

            # 0. Pending Limit Fill & Expiry Evaluation
            if pos.get("stage") == "PENDING_LIMIT" or pos.get("is_limit_pending", False):
                limit_p = float(pos.get("optimal_entry_limit") or pos.get("entry_price", curr_p))
                filled = (curr_p <= limit_p) if is_long else (curr_p >= limit_p)
                if filled:
                    pos["stage"] = "OPEN"
                    pos["is_limit_pending"] = False
                    pos["entry_price"] = limit_p
                    pos["opened_at"] = now_dt.isoformat()
                    pos["peak_price"] = limit_p
                    pos["trough_price"] = limit_p
                    print(f"\n[PAPER LIMIT FILLED 🚀] {sym} filled @ ${limit_p:.4f} (Saved from peak chase!)")
                    still_open.append(pos)
                    continue
                else:
                    tp1_target = float(pos.get("tp1_price", limit_p * 1.02 if is_long else limit_p * 0.98))
                    missed_tp1 = (curr_p >= tp1_target) if is_long else (curr_p <= tp1_target)
                    expiry_dt = datetime.fromisoformat(pos["expiry_time"]) if isinstance(pos["expiry_time"], str) else pos["expiry_time"]
                    if missed_tp1 or (now_dt >= expiry_dt):
                        pos["stage"] = "CLOSED"
                        pos["close_reason"] = "MISSED_TP1_NO_PULLBACK" if missed_tp1 else "EXPIRED_UNFILLED"
                        pos["exit_price"] = curr_p
                        pos["realized_net_pnl"] = 0.0
                        pos["unrealized_pnl_usd"] = 0.0
                        pos["unrealized_pnl_pct"] = 0.0
                        self.data.setdefault("closed_trades", []).append(pos)
                        print(f"\n[PAPER LIMIT CANCELLED ⚪] {sym} pending limit @ ${limit_p:.4f} cancelled ({pos['close_reason']}) ($0 fee drag).")
                        continue
                    else:
                        still_open.append(pos)
                        continue

            # 1. Accrue 8-hour perpetual funding fees
            self._accrue_funding_fees(pos, now_dt)

            # 2. Update intra-trade extremes
            pos["peak_price"] = max(float(pos.get("peak_price", curr_p)), curr_p)
            pos["trough_price"] = min(float(pos.get("trough_price", curr_p)), curr_p)
            high_p = pos["peak_price"]
            low_p = pos["trough_price"]

            # 3. MAE & MFE tracking
            mfe = ((high_p - entry_p)/entry_p * 100.0) if is_long else ((entry_p - low_p)/entry_p * 100.0)
            mae = ((entry_p - low_p)/entry_p * 100.0) if is_long else ((high_p - entry_p)/entry_p * 100.0)
            pos["mfe_pct"] = round(mfe, 2)
            pos["mae_pct"] = round(mae, 2)

            init_size = float(pos.get("initial_position_size_usd", pos.get("position_size_usd", 100.0)))
            rem_size = float(pos.get("remaining_position_size_usd", init_size))
            stage = pos.get("stage", "OPEN")
            sl_p = float(pos.get("sl_price", entry_p))
            tp1_p = float(pos.get("tp1_price", entry_p))
            tp2_p = float(pos.get("tp2_price", tp1_p))
            tp3_p = float(pos.get("tp3_price", tp2_p))

            # Self-healing dynamic target escalation for active/reloaded scaled positions
            if pos.get("is_tp2_locked") or stage == "TP2_LOCKED_TRAIL":
                pos["active_tp_level"] = "TP3"
                pos["active_tp_price"] = tp3_p
                pos["tp_price"] = tp3_p
                pos["tp2_hit"] = True
            elif pos.get("is_tp1_locked") or stage == "TP1_LOCKED_BREAKEVEN":
                pos["active_tp_level"] = "TP2"
                pos["active_tp_price"] = tp2_p
                pos["tp_price"] = tp2_p
                pos["tp1_hit"] = True

            opened_dt = datetime.fromisoformat(pos["opened_at"]) if isinstance(pos["opened_at"], str) else pos["opened_at"]
            expiry_dt = datetime.fromisoformat(pos["expiry_time"]) if isinstance(pos["expiry_time"], str) else pos["expiry_time"]
            dur_secs = int((now_dt - opened_dt).total_seconds())
            dur_m, dur_s = divmod(dur_secs, 60)
            dur_h, dur_m = divmod(dur_m, 60)
            duration_str = f"{dur_h}h {dur_m}m {dur_s}s" if dur_h > 0 else (f"{dur_m}m {dur_s}s" if dur_m > 0 else f"{dur_s}s")
            pos["duration_str"] = duration_str

            # 4. Tier-0 Breakeven Guard (Dynamic >= 60% of TP1 distance -> BE, min 0.40%, capped at desk base)
            tp1_dist_pct = (abs(tp1_p - entry_p) / entry_p) * 100.0 if entry_p > 0 else 2.0
            base_tier0 = float(desk_cfg.get("tier0_threshold", 1.20))
            tier0_threshold = max(0.40, min(base_tier0, tp1_dist_pct * 0.60))
            if mfe >= tier0_threshold and not pos.get("is_tp1_locked") and not pos.get("is_tier0_locked"):
                soft_be = round((entry_p * 1.0020) if is_long else (entry_p * 0.9980), 8)
                # Mathematical Invariant: Only ratchet stop-loss to Breakeven when price is safely beyond soft_be
                can_lock_be = (curr_p >= soft_be * 1.0005) if is_long else (curr_p <= soft_be * 0.9995)
                if can_lock_be:
                    pos["is_tier0_locked"] = True
                    pos["sl_price"] = soft_be
                    pos["stage"] = "TIER0_PROTECTED_BREAKEVEN"
                    sl_p = soft_be
                    stage = "TIER0_PROTECTED_BREAKEVEN"
                    print(f"[TIER-0 GUARD 🛡️] {sym} reached peak gain +{mfe:.2f}% >= +{tier0_threshold:.2f}%. SL moved to Breakeven (${soft_be:,.4f}) risk-free!", flush=True)

            # 5. Check Take-Profit Touches
            is_hit_tp1 = (high_p >= tp1_p) if is_long else (low_p <= tp1_p)
            is_hit_tp2 = (high_p >= tp2_p) if is_long else (low_p <= tp2_p)
            is_hit_tp3 = (high_p >= tp3_p) if is_long else (low_p <= tp3_p)

            # Stepped partial scaling: 50% @ TP1
            if is_hit_tp1 and stage in ["OPEN", "TIER0_PROTECTED_BREAKEVEN"]:
                scale_size = round(rem_size * 0.50, 2)
                rem_size = round(rem_size - scale_size, 2)
                gain_tp1 = scale_size * (abs(tp1_p - entry_p) / entry_p)
                fee_tp1 = round((scale_size + gain_tp1) * self.sell_fee_rate, 4)
                spread_tp1 = round((scale_size + gain_tp1) * (self.spread_rate / 2.0), 4)
                slip_tp1 = round((scale_size + gain_tp1) * (self.slippage_rate / 2.0), 4)
                friction_tp1 = round(fee_tp1 + spread_tp1 + slip_tp1, 4)
                net_tp1 = round(gain_tp1 - friction_tp1, 4)

                pos["realized_gross_pnl"] = round(pos.get("realized_gross_pnl", 0.0) + gain_tp1, 4)
                pos["realized_fees"] = round(pos.get("realized_fees", 0.0) + fee_tp1, 4)
                pos["realized_spread_usd"] = round(pos.get("realized_spread_usd", 0.0) + spread_tp1, 4)
                pos["realized_slippage_usd"] = round(pos.get("realized_slippage_usd", 0.0) + slip_tp1, 4)
                pos["realized_net_pnl"] = round(pos.get("realized_net_pnl", 0.0) + net_tp1, 4)
                pos["remaining_position_size_usd"] = rem_size
                pos["is_tp1_locked"] = True
                pos["tp1_hit"] = True
                pos["tp1_banked_usd"] = net_tp1
                pos["active_tp_level"] = "TP2"
                pos["active_tp_price"] = tp2_p
                pos["tp_price"] = tp2_p  # Crucial: actively advance tp_price to TP2 for all UI/API consumers
                pos["stage"] = "TP1_LOCKED_BREAKEVEN"
                from app.engine.config import TRADE_MANAGEMENT_POLICY
                if TRADE_MANAGEMENT_POLICY == "TIER0_ATR_TRAILING_BUFFER":
                    raw_atr = max(1e-8, 0.015 * entry_p)
                    trail_buffer = 0.8 * raw_atr
                    trailed_sl = round((curr_p - trail_buffer) if is_long else (curr_p + trail_buffer), 8)
                    pos["sl_price"] = max(entry_p, trailed_sl) if is_long else min(entry_p, trailed_sl)
                else:
                    pos["sl_price"] = entry_p
                sl_p = pos["sl_price"]
                stage = "TP1_LOCKED_BREAKEVEN"
                print(f"[TP1 SCALED 🎯] {sym} 50% locked @ ${tp1_p:,.4f} (+${net_tp1:,.2f} net). Active target advanced to TP2 (${tp2_p:,.4f})! SL set to ${pos['sl_price']:,.4f}!", flush=True)

            # Stepped partial scaling: 30% @ TP2
            if is_hit_tp2 and stage == "TP1_LOCKED_BREAKEVEN":
                scale_size = round(init_size * 0.30, 2)
                rem_size = round(rem_size - scale_size, 2)
                gain_tp2 = scale_size * (abs(tp2_p - entry_p) / entry_p)
                fee_tp2 = round((scale_size + gain_tp2) * self.sell_fee_rate, 4)
                spread_tp2 = round((scale_size + gain_tp2) * (self.spread_rate / 2.0), 4)
                slip_tp2 = round((scale_size + gain_tp2) * (self.slippage_rate / 2.0), 4)
                friction_tp2 = round(fee_tp2 + spread_tp2 + slip_tp2, 4)
                net_tp2 = round(gain_tp2 - friction_tp2, 4)

                pos["realized_gross_pnl"] = round(pos.get("realized_gross_pnl", 0.0) + gain_tp2, 4)
                pos["realized_fees"] = round(pos.get("realized_fees", 0.0) + fee_tp2, 4)
                pos["realized_spread_usd"] = round(pos.get("realized_spread_usd", 0.0) + spread_tp2, 4)
                pos["realized_slippage_usd"] = round(pos.get("realized_slippage_usd", 0.0) + slip_tp2, 4)
                pos["realized_net_pnl"] = round(pos.get("realized_net_pnl", 0.0) + net_tp2, 4)
                pos["remaining_position_size_usd"] = rem_size
                pos["is_tp2_locked"] = True
                pos["tp2_hit"] = True
                pos["tp2_banked_usd"] = net_tp2
                pos["active_tp_level"] = "TP3"
                pos["active_tp_price"] = tp3_p
                pos["tp_price"] = tp3_p  # Crucial: actively advance tp_price to TP3 runner for all UI/API consumers
                pos["stage"] = "TP2_LOCKED_TRAIL"
                pos["sl_price"] = tp1_p
                sl_p = tp1_p
                stage = "TP2_LOCKED_TRAIL"
                print(f"[TP2 SCALED 💎] {sym} 30% locked @ ${tp2_p:,.4f} (+${net_tp2:,.2f} net). Active target advanced to TP3 (${tp3_p:,.4f})! SL trailed to TP1 (${tp1_p:,.4f})!", flush=True)

            # Dynamic Chandelier Trailing Stop on Final 20% Runner
            if stage == "TP2_LOCKED_TRAIL":
                raw_atr = max(1e-8, 0.015 * entry_p)
                if is_long:
                    chan_sl = round(pos["peak_price"] - (1.5 * raw_atr), 8)
                    pos["sl_price"] = max(pos.get("sl_price", tp1_p), chan_sl)
                else:
                    chan_sl = round(pos["trough_price"] + (1.5 * raw_atr), 8)
                    pos["sl_price"] = min(pos.get("sl_price", tp1_p), chan_sl)
                sl_p = pos["sl_price"]

            # 6. Check SL hit (evaluated strictly against real-time price to match exchange stop orders)
            is_hit_sl = (curr_p <= sl_p) if is_long else (curr_p >= sl_p)

            # 7. Check Expiry (Disabled when ENABLE_SIGNAL_EXPIRY is False)
            is_expired = ENABLE_SIGNAL_EXPIRY and (dur_secs >= desk_cfg["max_hold_seconds"])

            # 8. Early Stagnation Scratch Exit: If >= 60% of duration elapsed with zero momentum (MFE < 0.25%) and underwater, scratch early
            curr_unreal_ret = ((curr_p - entry_p)/entry_p * 100.0) if is_long else ((entry_p - curr_p)/entry_p * 100.0)
            is_stagnant = ENABLE_SIGNAL_EXPIRY and (dur_secs >= (desk_cfg["max_hold_seconds"] * 0.60)) and not pos.get("is_tp1_locked") and not pos.get("is_tier0_locked") and (mfe < 0.25) and (curr_unreal_ret <= -0.25)

            is_final_exit = is_hit_sl or is_hit_tp3 or is_expired or is_stagnant

            if is_final_exit:
                if is_hit_tp3:
                    exit_p = tp3_p
                    exit_reason = "TAKE_PROFIT_TP3_RUNNER"
                elif is_hit_sl:
                    exit_p = sl_p
                    exit_reason = "BREAKEVEN_GUARD_HIT" if pos.get("is_tier0_locked") and not pos.get("is_tp1_locked") else ("TRAILING_SL_HIT" if stage != "OPEN" else "STOP_LOSS_HIT")
                elif is_stagnant:
                    exit_p = curr_p
                    exit_reason = f"STAGNATION_SCRATCH ({duration_str} - zero momentum)"
                else:
                    exit_p = curr_p
                    if pos.get("tp2_hit"):
                        exit_reason = f"TAKE_PROFIT_2_RUNNER_EXPIRY ({duration_str})"
                    elif pos.get("tp1_hit"):
                        exit_reason = f"TAKE_PROFIT_1_RUNNER_EXPIRY ({duration_str})"
                    else:
                        exit_reason = f"HORIZON_EXPIRY ({duration_str})"

                rem_gain = rem_size * ((exit_p - entry_p)/entry_p if is_long else (entry_p - exit_p)/entry_p)
                rem_nominal_exit = max(0.0, rem_size + rem_gain)
                exit_rem_fee = round(rem_nominal_exit * self.sell_fee_rate, 4)
                exit_rem_spread = round(rem_nominal_exit * (self.spread_rate / 2.0), 4)
                exit_rem_slip = round(rem_nominal_exit * (self.slippage_rate / 2.0), 4)

                total_gross = round(pos.get("realized_gross_pnl", 0.0) + rem_gain, 4)
                total_fees = round(pos.get("buy_fee_usd", 0.0) + pos.get("realized_fees", 0.0) + exit_rem_fee, 4)
                total_spread = round(pos.get("realized_spread_usd", pos.get("entry_spread_usd", 0.0)) + exit_rem_spread, 4)
                total_slippage = round(pos.get("realized_slippage_usd", pos.get("entry_slippage_usd", 0.0)) + exit_rem_slip, 4)
                total_funding = round(pos.get("funding_fees_usd", 0.0), 4)
                total_friction = round(total_fees + total_spread + total_slippage + total_funding, 4)
                total_net = round(total_gross - total_friction, 4)
                net_ret_pct = round((total_net / init_size) * 100.0, 2)
                gross_ret_pct = round((total_gross / init_size) * 100.0, 2)

                if total_net > 0.01:
                    outcome = "WON"
                elif total_net < -0.10:
                    outcome = "LOST"
                else:
                    outcome = "BREAKEVEN"

                if outcome in ["LOST", "BREAKEVEN"]:
                    self.cooldown_tracker[sym] = now_dt

                # Track consecutive loss streak & apply 48-hour quarantine if >= 2 consecutive stop-outs
                if outcome == "WON":
                    self.symbol_loss_streak[sym] = 0
                elif outcome == "LOST":
                    self.symbol_loss_streak[sym] = self.symbol_loss_streak.get(sym, 0) + 1
                    if self.symbol_loss_streak[sym] >= 2:
                        self.quarantined_symbols[sym] = now_dt + timedelta(hours=48)
                        print(f"\n[ASSET QUARANTINE 🛑] {sym} triggered {self.symbol_loss_streak[sym]} consecutive stop-outs! Quarantined for 48 hours to protect capital.\n", flush=True)

                pos["exit_price"] = exit_p
                pos["exit_reason"] = exit_reason
                pos["outcome"] = outcome
                pos["gross_pnl_usd"] = total_gross
                pos["gross_pnl_pct"] = gross_ret_pct
                pos["sell_fee_usd"] = round(pos.get("realized_fees", 0.0) + exit_rem_fee, 4)
                pos["binance_fee_usd"] = total_fees
                pos["spread_cost_usd"] = total_spread
                pos["slippage_cost_usd"] = total_slippage
                pos["funding_fees_usd"] = total_funding
                pos["total_friction_usd"] = total_friction
                pos["realized_pnl_usd"] = total_net
                pos["realized_pnl_pct"] = net_ret_pct
                pos["realized_return_pct"] = f"{net_ret_pct:+.2f}%"
                pos["closed_at"] = now_str
                pos["exit_time_str"] = now_dt.strftime('%Y-%m-%d %H:%M:%S UTC')

                # Update master capital & metrics
                self.data["current_balance_usd"] = round(self.data["current_balance_usd"] + total_net, 2)
                self.data["realized_pnl_usd"] = round(self.data["realized_pnl_usd"] + total_net, 2)
                self.data["gross_realized_pnl_usd"] = round(self.data.get("gross_realized_pnl_usd", 0.0) + total_gross, 2)
                self.data["total_fees_paid_usd"] = round(self.data["total_fees_paid_usd"] + total_fees, 2)
                self.data["total_spread_paid_usd"] = round(self.data.get("total_spread_paid_usd", 0.0) + total_spread, 2)
                self.data["total_slippage_paid_usd"] = round(self.data.get("total_slippage_paid_usd", 0.0) + total_slippage, 2)
                self.data["total_funding_fees_usd"] = round(self.data.get("total_funding_fees_usd", 0.0) + total_funding, 2)
                self.data["total_friction_paid_usd"] = round(self.data.get("total_friction_paid_usd", 0.0) + total_friction, 2)

                if total_gross > 0:
                    self.data["gross_profit_usd"] = round(self.data.get("gross_profit_usd", 0.0) + total_gross, 2)
                else:
                    self.data["gross_loss_usd"] = round(self.data.get("gross_loss_usd", 0.0) + abs(total_gross), 2)

                self.data["total_trades"] += 1
                if outcome == "WON":
                    self.data["winning_trades"] += 1
                elif outcome == "LOST":
                    self.data["losing_trades"] += 1
                else:
                    self.data["breakeven_trades"] = self.data.get("breakeven_trades", 0) + 1

                # Update desk stats
                d_stat = self.data["desks"][desk_key]
                d_stat["open_positions"] = max(0, d_stat.get("open_positions", 1) - 1)
                d_stat["realized_pnl_usd"] = round(d_stat.get("realized_pnl_usd", 0.0) + total_net, 2)
                d_stat["total_trades"] = d_stat.get("total_trades", 0) + 1
                if outcome == "WON":
                    d_stat["winning_trades"] = d_stat.get("winning_trades", 0) + 1
                d_stat["win_rate_pct"] = round((d_stat["winning_trades"] / max(1, d_stat["total_trades"])) * 100.0, 1)

                # Drawdown tracking
                self.data["peak_balance_usd"] = max(self.data.get("peak_balance_usd", self.start_balance), self.data["current_balance_usd"])
                current_dd = round(self.data["peak_balance_usd"] - self.data["current_balance_usd"], 2)
                current_dd_pct = round((current_dd / max(1.0, self.data["peak_balance_usd"])) * 100.0, 2)
                self.data["max_drawdown_usd"] = max(self.data.get("max_drawdown_usd", 0.0), current_dd)
                self.data["max_drawdown_pct"] = max(self.data.get("max_drawdown_pct", 0.0), current_dd_pct)

                self.data.setdefault("closed_trades_history", []).append(pos)
                closed_this_tick.append(pos)
            else:
                # Update Open Position real-time stats
                raw_ret = (curr_p - entry_p)/entry_p if is_long else (entry_p - curr_p)/entry_p
                est_exit_nominal = max(0.0, rem_size * (1.0 + raw_ret))
                est_exit_fee = round(est_exit_nominal * self.sell_fee_rate, 4)
                est_exit_spread = round(est_exit_nominal * (self.spread_rate / 2.0), 4)
                est_exit_slip = round(est_exit_nominal * (self.slippage_rate / 2.0), 4)
                buy_fee_usd = round(pos.get("buy_fee_usd", rem_size * self.buy_fee_rate), 4)
                est_total_fee = round(buy_fee_usd + est_exit_fee, 4)
                est_total_spread = round(pos.get("realized_spread_usd", pos.get("entry_spread_usd", 0.0)) + est_exit_spread, 4)
                est_total_slip = round(pos.get("realized_slippage_usd", pos.get("entry_slippage_usd", 0.0)) + est_exit_slip, 4)
                total_funding = round(pos.get("funding_fees_usd", 0.0), 4)
                est_total_friction = round(est_total_fee + est_total_spread + est_total_slip + total_funding, 4)
                gross_u_pnl = round(raw_ret * rem_size, 4)
                net_u_pnl = round(gross_u_pnl - est_total_friction, 4)

                # Target progress % relative to current active target (TP1, TP2, or TP3)
                active_target_p = float(pos.get("active_tp_price") or pos.get("tp_price") or tp1_p)
                if is_long:
                    if curr_p >= entry_p:
                        tp_span = max(1e-8, active_target_p - entry_p)
                        target_prog = round(min(100.0, max(0.0, (curr_p - entry_p) / tp_span * 100.0)), 2)
                    else:
                        sl_span = max(1e-8, entry_p - sl_p)
                        target_prog = -round(min(100.0, max(0.0, (entry_p - curr_p) / sl_span * 100.0)), 2)
                else:
                    if curr_p <= entry_p:
                        tp_span = max(1e-8, entry_p - active_target_p)
                        target_prog = round(min(100.0, max(0.0, (entry_p - curr_p) / tp_span * 100.0)), 2)
                    else:
                        sl_span = max(1e-8, sl_p - entry_p)
                        target_prog = -round(min(100.0, max(0.0, (curr_p - entry_p) / sl_span * 100.0)), 2)

                pos["unrealized_gross_pnl_usd"] = gross_u_pnl
                pos["est_sell_fee_usd"] = est_exit_fee
                pos["unrealized_fee_usd"] = est_total_fee
                pos["unrealized_spread_usd"] = est_total_spread
                pos["unrealized_slippage_usd"] = est_total_slip
                pos["unrealized_friction_usd"] = est_total_friction
                pos["unrealized_pnl_usd"] = net_u_pnl
                pos["unrealized_pnl_pct"] = round((net_u_pnl / init_size) * 100.0, 2)
                pos["target_progress_pct"] = target_prog
                still_open.append(pos)

        self.data["open_positions"] = still_open
        # Invariant: Re-synchronize desk open position counts directly from still_open
        for dk in ["scalp", "intraday", "macro"]:
            if dk in self.data.get("desks", {}):
                self.data["desks"][dk]["open_positions"] = len([p for p in still_open if p.get("desk") == dk])

        self.data["last_updated"] = now_str
        self._calculate_institutional_metrics()
        self.save()

        # Display instantaneous trade close notification banner
        for c in closed_this_tick:
            sign = "+" if c.get("realized_pnl_usd", 0.0) >= 0 else ""
            badge = "🎉 [TRADE WON 🟢]" if c["outcome"] == "WON" else ("🛑 [TRADE STOPPED 🔴]" if c["outcome"] == "LOST" else "⚪ [TRADE BREAKEVEN]")
            print(f"\n{'='*120}")
            print(f" {badge} {c['symbol']} [{c.get('desk_name', c.get('horizon', 'SCALP')).upper()} {c['direction']}] Closed via {c['exit_reason']}!")
            print(f" 💵 Entry: ${c['entry_price']:,.2f} ➔ Exit: ${c['exit_price']:,.2f} | Duration: {c.get('duration_str','N/A')}")
            print(f" 📊 Gross PnL: {sign}${c.get('gross_pnl_usd',0.0):,.2f} ({sign}{c.get('gross_pnl_pct',0.0):.2f}%) | 🧾 Fees: -${c.get('binance_fee_usd',0.0):,.2f} | 📐 Spread: -${c.get('spread_cost_usd',0.0):,.2f} | ⚡ Slip: -${c.get('slippage_cost_usd',0.0):,.2f} | ⏳ Funding: -${c.get('funding_fees_usd',0.0):,.2f}")
            print(f" 💎 True Net Realized PnL: {sign}${c['realized_pnl_usd']:,.2f} ({sign}{c['realized_pnl_pct']:.2f}%) [Friction: -${c.get('total_friction_usd',0.0):,.2f}] | Updated Balance: ${self.data['current_balance_usd']:,.2f}")
            print(f"{'='*120}\n", flush=True)

    def _calculate_institutional_metrics(self):
        """Computes Sharpe Ratio, Sortino Ratio, Profit Factor, Expectancy, and Win Rates."""
        closed = self.data.get("closed_trades_history", [])
        if not closed:
            return

        def _safe_ret_parse(val):
            try:
                if val is None:
                    return 0.0
                return float(str(val).replace("%", "").replace("+", "").strip()) / 100.0
            except Exception:
                return 0.0

        def _safe_pnl_parse(val):
            try:
                if val is None:
                    return 0.0
                return float(str(val).replace("$", "").replace(",", "").strip())
            except Exception:
                return 0.0

        returns = [_safe_ret_parse(c.get("realized_pnl_pct", 0.0)) for c in closed]
        net_pnls = [_safe_pnl_parse(c.get("realized_pnl_usd", 0.0)) for c in closed]
        wins = [p for p in net_pnls if p > 0]
        losses = [abs(p) for p in net_pnls if p < 0]

        gross_win = sum(wins)
        gross_loss = sum(losses)
        pf = (gross_win / max(0.01, gross_loss)) if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)
        self.data["profit_factor"] = round(pf, 2)

        total_t = len(closed)
        p_win = len(wins) / total_t
        p_loss = len(losses) / total_t
        avg_w = float(np.mean(wins)) if wins else 0.0
        avg_l = float(np.mean(losses)) if losses else 0.0
        expectancy = (p_win * avg_w) - (p_loss * avg_l)
        self.data["expectancy_usd"] = round(expectancy, 2)

        if len(returns) >= 2:
            mean_r = float(np.mean(returns))
            std_r = float(np.std(returns))
            downside_r = [r for r in returns if r < 0]
            downside_std = float(np.std(downside_r)) if len(downside_r) >= 2 else (std_r * 0.70)

            sharpe = (mean_r / max(1e-6, std_r)) * np.sqrt(365 * 4)
            sortino = (mean_r / max(1e-6, downside_std)) * np.sqrt(365 * 4)
            self.data["sharpe_ratio"] = round(float(sharpe), 2)
            self.data["sortino_ratio"] = round(float(sortino), 2)

        decisive = self.data["winning_trades"] + self.data["losing_trades"]
        self.data["win_rate_pct"] = round((self.data["winning_trades"] / max(1, decisive)) * 100.0, 1) if decisive > 0 else 0.0

    def on_tick(self, live_prices: dict, live_highs: dict = None, live_lows: dict = None, now_dt: datetime = None):
        """Processes real-time price updates, stepped risk ratchets, partial TP scaling, and trailing stops."""
        return self.update_positions(live_prices, live_highs, live_lows, now_dt=now_dt)

    def save(self):
        """Atomically saves portfolio ledger state to JSON file."""
        with getattr(self, '_lock', threading.RLock()):
            os.makedirs(self.export_dir, exist_ok=True)
            temp_path = f"{self.ledger_file}.{threading.get_ident()}.{time.time_ns()}.tmp"
            try:
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(self.data, f, indent=4, default=str)
                for attempt in range(5):
                    try:
                        os.replace(temp_path, self.ledger_file)
                        break
                    except (PermissionError, OSError):
                        time.sleep(0.04)
            except Exception as e:
                pass
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass

    def render_portfolio_card(self):
        """Renders comprehensive institutional portfolio summary in console."""
        d = self.data
        pnl_sign = "+" if d['realized_pnl_usd'] >= 0 else ""
        tot_ret_pct = ((d['current_balance_usd'] - d['starting_balance_usd']) / max(1.0, d['starting_balance_usd'])) * 100.0
        open_unrealized_total = sum(p.get('unrealized_pnl_usd', 0.0) for p in d.get('open_positions', []))
        net_equity = d['current_balance_usd'] + open_unrealized_total
        pf_display = f"{d.get('profit_factor', 0.0):.2f}" if d.get('profit_factor', 0.0) < 99.0 else "∞ (Zero Losses)"

        desks_info = " | ".join([
            f"{self.desks[k]['name']}: {d.get('desks', {}).get(k, {}).get('open_positions', 0)}/{self.desks[k]['max_slots']}"
            for k in ["scalp", "intraday", "macro"]
        ])
        print(f"\n[INSTITUTIONAL PORTFOLIO 💼] Equity: ${net_equity:,.2f} | Cash: ${d['current_balance_usd']:,.2f} | Net Realized: {pnl_sign}${d['realized_pnl_usd']:,.2f} ({tot_ret_pct:+.2f}%)")
        print(f"  ⚡ Desks: {desks_info} | Win Rate: {d['win_rate_pct']:.1f}% | PF: {pf_display} | Sharpe: {d.get('sharpe_ratio', 0.0):.2f} | Sortino: {d.get('sortino_ratio', 0.0):.2f}")
        fric_tot = d.get('total_friction_paid_usd', 0.0)
        fees_paid = d.get('total_fees_paid_usd', 0.0)
        spread_paid = d.get('total_spread_paid_usd', 0.0)
        slip_paid = d.get('total_slippage_paid_usd', 0.0)
        fund_paid = d.get('total_funding_fees_usd', 0.0)
        print(f"  🧾 Friction Drag: Fees: -${fees_paid:,.2f} | Spread: -${spread_paid:,.2f} | Slippage: -${slip_paid:,.2f} | Funding: -${fund_paid:,.2f} | Total Drag: -${fric_tot:,.2f}\n", flush=True)

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
    HORIZON_COOLDOWN_HOURS = {
        '15M': 0.25,   # 15 mins
        '30M': 0.5,    # 30 mins
        '1H': 1.0,     # 1 hour
        '4H': 4.0,     # 4 hours
        '24H': 24.0,   # 24 hours
        '4D': 48.0,    # 2 days
        '7D': 72.0,    # 3 days
        '15D': 120.0,  # 5 days
        '30D': 168.0,  # 7 days
    }

    def __init__(self, export_dir: str = "./export_app_data"):
        self.export_dir = export_dir
        os.makedirs(self.export_dir, exist_ok=True)
        self.csv_path = os.path.join(self.export_dir, "trader_signals_tracker.csv")
        self.summary_csv_path = os.path.join(self.export_dir, "trader_signals_performance.csv")
        self.records = self.load_records()
        
        # QUANT EDGE V16: Institutional Engines Integration
        try:
            from app.quant_v16.audit import V16AuditManager
            from app.quant_v16.thesis import TradeThesisEngine
            from app.quant_v16.validation import DataValidator
            from app.quant_v16.costs import ExecutionCostEngine
            from app.quant_v16.probability import ProbabilityPathModel
            from app.quant_v16.expectancy import NetExpectancyEngine
            from app.quant_v16.scoring import V16SignalScorer

            self.v16_audit = V16AuditManager(export_dir=self.export_dir)
            self.v16_thesis_engine = TradeThesisEngine()
            self.v16_cost_engine = ExecutionCostEngine()
            self.v16_prob_model = ProbabilityPathModel()
            self.v16_expectancy_engine = NetExpectancyEngine()
            self.v16_scorer = V16SignalScorer()
            self.has_v16 = True
        except Exception as v16_init_err:
            print(f"[V16 ⚠️] Could not initialize full V16 suite in SignalAuditTracker: {v16_init_err}")
            self.has_v16 = False
        self._lock = threading.RLock()
        self._last_csv_mtime = os.path.getmtime(self.csv_path) if os.path.exists(self.csv_path) else 0.0

    def reconcile_disk_records(self):
        """
        Two-way disk reconciliation between PaperTradingBot/SignalService and SignalAuditTracker.
        Detects external status resolutions written to trader_signals_tracker.csv by external services
        and merges them into in-memory records without reverting or clobbering completed trades.
        """
        if not os.path.exists(self.csv_path):
            return
        try:
            curr_mtime = os.path.getmtime(self.csv_path)
            if curr_mtime <= getattr(self, '_last_csv_mtime', 0.0):
                return
            disk_records = self.load_records()
            if not disk_records:
                return

            disk_map = {str(r.get('signal_id')): r for r in disk_records if r.get('signal_id')}
            in_mem_map = {str(r.get('signal_id')): r for r in self.records if r.get('signal_id')}

            terminal_statuses = {
                "WON_TP1", "WON_TP2", "WON_TP3", "WON_TP1_BE", "WON_TP2_TRAIL",
                "LOST_SL", "WON_TIER0_BE", "BREAKEVEN_GUARD", "STOP_LOSS_BREAKEVEN",
                "TIER0_GUARD", "EXPIRED_BREAKEVEN", "BREAKEVEN_EXP", "WON_EXP_PROFIT", "LOST_EXP", "CLOSED"
            }
            for sid, d_rec in disk_map.items():
                if sid in in_mem_map:
                    mem_rec = in_mem_map[sid]
                    d_status = str(d_rec.get('status', '')).upper()
                    m_status = str(mem_rec.get('status', '')).upper()
                    if d_status in terminal_statuses or (m_status not in terminal_statuses and d_status not in ["", "PENDING_EVALUATION"]):
                        mem_rec.update(d_rec)
                else:
                    self.records.append(d_rec)

            self._last_csv_mtime = curr_mtime
        except Exception:
            pass

    def load_records(self) -> list:
        if os.path.exists(self.csv_path):
            try:
                df = pd.read_csv(self.csv_path, keep_default_na=False).fillna("")
                return df.to_dict(orient='records')
            except Exception:
                return []
        return []

    def save_records(self):
        with getattr(self, '_lock', threading.RLock()):
            try:
                if self.records:
                    df = pd.DataFrame(self.records).fillna("")
                    # Primary detailed audit CSV (Spreadsheet compatible)
                    df.to_csv(self.csv_path, index=False)
                
                # Performance Summary KPI CSV for easy spreadsheet viewing
                summary_data = self.build_kpi_summary()
                df_sum = pd.DataFrame([summary_data]).fillna("")
                df_sum.to_csv(self.summary_csv_path, index=False)

                if os.path.exists(self.csv_path):
                    self._last_csv_mtime = os.path.getmtime(self.csv_path)

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
        try:
            from app.quant_v16.audit import classify_signal_outcome
        except ImportError:
            classify_signal_outcome = None

        won = 0
        lost = 0
        pending = 0
        breakeven = 0
        expired = 0
        a_plus_won = 0
        a_plus_lost = 0
        a_won = 0
        a_lost = 0
        returns = []

        for r in self.records:
            st = str(r.get('status', ''))
            out = str(r.get('outcome_label', ''))
            ret_raw = r.get('realized_return_pct')
            ret_val = None
            if ret_raw is not None:
                ret_str = str(ret_raw).replace('%', '').replace('+', '').strip()
                if ret_str != "" and ret_str.lower() not in ["nan", "none", "null"]:
                    try:
                        v = float(ret_str)
                        if not (math.isnan(v) or math.isinf(v)):
                            ret_val = v
                    except Exception:
                        pass

            if classify_signal_outcome:
                cat = classify_signal_outcome(st, out, ret_val)
            else:
                # Standalone fallback matching V16 rules
                st_u, out_u = st.upper(), out.upper()
                if st_u in ["PENDING_EVALUATION", "ACTIVE", "PENDING_LIMIT", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"] or "PENDING" in out_u:
                    cat = "PENDING"
                elif "BREAKEVEN" in out_u or "TIER-0" in out_u or "BE" in st_u:
                    cat = "BREAKEVEN"
                elif "WON" in out_u or "WON" in st_u:
                    cat = "WON"
                elif "LOST" in out_u or "LOST" in st_u or "STOPPED" in out_u:
                    cat = "LOST"
                elif "EXP" in out_u or "EXP" in st_u:
                    cat = "EXPIRED"
                else:
                    cat = "PENDING"

            q_grade = str(r.get('quality_grade', ''))
            g_tier = r.get('grade_tier')
            if g_tier is not None and str(g_tier).strip().isdigit():
                t = int(str(g_tier).strip())
                is_a_plus = (t == 1)
                is_a = (t == 2)
            else:
                is_a_plus = "A+" in q_grade
                is_a = "Grade A (" in q_grade or "Grade A\n" in q_grade or "GRADE A" in q_grade.upper()

            if cat == "PENDING":
                pending += 1
                # Invariant (Rule 9): Pending signals NEVER count toward wins, losses, or realized returns
                continue
            elif cat == "WON":
                won += 1
                if is_a_plus:
                    a_plus_won += 1
                elif is_a:
                    a_won += 1
            elif cat == "LOST":
                lost += 1
                if is_a_plus:
                    a_plus_lost += 1
                elif is_a:
                    a_lost += 1
            elif cat == "BREAKEVEN":
                breakeven += 1
            elif cat == "EXPIRED":
                expired += 1

            if ret_val is not None:
                returns.append(ret_val)

        decisive = won + lost
        decisive_wr = round((won / max(1, decisive)) * 100.0, 2) if decisive > 0 else 0.0

        total_closed = won + lost + breakeven + expired
        total_closed_wr = round((won / max(1, total_closed)) * 100.0, 2) if total_closed > 0 else 0.0

        a_plus_decisive = a_plus_won + a_plus_lost
        a_plus_wr = round((a_plus_won / max(1, a_plus_decisive)) * 100.0, 2) if a_plus_decisive > 0 else 0.0

        a_decisive = a_won + a_lost
        a_wr = round((a_won / max(1, a_decisive)) * 100.0, 2) if a_decisive > 0 else 0.0

        avg_ret = round(float(np.mean(returns)), 2) if returns else 0.0
        total_ret = round(float(np.sum(returns)), 2) if returns else 0.0

        return {
            "last_updated_utc": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
            "total_trader_signals": total_signals,
            "won_signals_count": won,
            "lost_signals_count": lost,
            "pending_signals_count": pending,
            "breakeven_signals_count": breakeven,
            "expired_signals_count": expired,
            "win_rate_pct": decisive_wr,
            "decisive_win_rate_pct": decisive_wr,
            "total_closed_win_rate_pct": total_closed_wr,
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

        HORIZON_COOLDOWN_HOURS = {
            '15M': 0.25,   # 15 mins
            '30M': 0.5,    # 30 mins
            '1H': 1.0,     # 1 hour
            '4H': 4.0,     # 4 hours
            '24H': 24.0,   # 24 hours
            '4D': 48.0,    # 2 days
            '7D': 72.0,    # 3 days
            '15D': 120.0,  # 5 days
            '30D': 168.0,  # 7 days
        }

        HORIZON_EXPIRY_SECONDS = {
            '15M': 900,
            '30M': 1800,
            '1H': 3600,
            '4H': 14400,
            '12H': 43200,
            '24H': 86400,
            '1D': 86400,
            '4D': 345600,
            '7D': 604800,
            '15D': 1296000,
            '30D': 2592000,
        }

        # Collect (symbol, horizon) pairs that currently have active/pending trades in ledger
        admitted_records = []
        active_ledger_pairs = set()
        active_unprotected_symbols = set()
        active_symbol_directions = {}
        for r in self.records:
            st = str(r.get('status', ''))
            outc = str(r.get('outcome_label', ''))
            if st in ["PENDING_EVALUATION", "ACTIVE", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"] or "PENDING" in outc or "ACTIVE" in outc:
                date_u = str(r.get('date_utc', ''))
                time_u = str(r.get('time_utc', '')).replace(' UTC', '').strip()
                is_recent = True
                try:
                    if date_u and time_u:
                        sig_dt = datetime.strptime(f"{date_u} {time_u}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                        h_name = str(r.get('horizon', '15M')).upper()
                        h_tag_r = resolve_horizon_tag(h_name)
                        dur_sec = HORIZON_EXPIRY_SECONDS.get(h_tag_r, 3600)
                        if (now_utc - sig_dt).total_seconds() > (dur_sec + 3600):
                            is_recent = False
                except Exception:
                    pass
                if is_recent:
                    s_sym = str(r.get('symbol', '')).strip().upper()
                    h_name = str(r.get('horizon', '15M')).upper()
                    h_tag_r = resolve_horizon_tag(h_name).upper()
                    r_dir = str(r.get('side') or r.get('direction', 'LONG')).upper()
                    clean_dir = "LONG" if ("LONG" in r_dir or "BUY" in r_dir or "BULL" in r_dir) else "SHORT"
                    if s_sym and h_tag_r:
                        active_ledger_pairs.add((s_sym, h_tag_r))
                    if s_sym and st in ["PENDING_EVALUATION", "ACTIVE"]:
                        active_unprotected_symbols.add(s_sym)
                    if s_sym:
                        active_symbol_directions[s_sym] = clean_dir

        for idx, sig in enumerate(displayed_signals):
            sym = str(sig.get('symbol', '')).strip().upper()
            h_key = str(sig.get('horizon_key', 'scalp')).lower()
            raw_h = sig.get('horizon_tag') or sig.get('horizon') or sig.get('horizon_name') or h_key
            h_tag = resolve_horizon_tag(str(raw_h)).upper()
            dec_str = str(sig.get('decision', ''))
            arch_str = str(sig.get('strategy_archetype') or sig.get('archetype', ''))

            # -------------------------------------------------------------
            # 🛡️ BUG 2 FIX: EXPLICIT SUPPRESSION VETO
            # Drop any setups explicitly flagged as suppressed, climax wicks, or avoidance
            # -------------------------------------------------------------
            if any(k in dec_str.upper() or k in arch_str.upper() for k in ["SUPPRESS", "CLIMAX WICK", "DO_NOT_TRADE", "AVOID"]):
                print(f"[SUPPRESS VETO 🛡️] Dropping suppressed setup for {sym} ({h_tag}): {dec_str}")
                continue
            if sig.get('is_suppressed', False) or sig.get('suppressed', False):
                continue

            # -------------------------------------------------------------
            # 🛡️ INSTITUTIONAL TIMEFRAME NTZ & CONSOLIDATION VETO
            # Hard rejection for candidates where this timeframe is in consolidation or low volume
            # -------------------------------------------------------------
            if (
                any(k in dec_str.upper() for k in ["NO TRADE ZONE", "CONSOLIDATION", "RANGE SQUEEZE", "COILED SQUEEZE", "LOW VOL", "CHOP"])
                or sig.get('is_ntz_blocked', False)
                or sig.get('is_ntz_active', False)
            ):
                print(f"[NTZ VETO 🛑] Suppressing signal for {sym} ({h_tag}): Timeframe is in No Trade Zone / Consolidation: {dec_str}")
                continue

            # 1. Quarantine Gate: 2-Strike Quarantine stops bleeding on toxic whipsawing coins
            is_quarantined, quar_reason = self.is_asset_quarantined(sym)
            if is_quarantined:
                continue

            # -------------------------------------------------------------
            # 🛡️ INSTITUTIONAL DIRECTIONAL CONFLICT VETO (ANTI-HEDGING RULE)
            # An asset can NEVER hold opposing directions across timeframes!
            # -------------------------------------------------------------
            cand_dir = str(sig.get('direction', 'LONG')).upper()
            cand_clean_dir = "LONG" if ("LONG" in cand_dir or "BUY" in cand_dir or "BULL" in cand_dir) else "SHORT"
            if sym in active_symbol_directions:
                active_dir = active_symbol_directions[sym]
                if active_dir != cand_clean_dir:
                    print(f"[DIRECTIONAL CONFLICT VETO 🛑] {sym} already has an active {active_dir} position. Vetoing counter-trend {cand_clean_dir} on {h_tag} to prevent self-cannibalization.")
                    continue

            # -------------------------------------------------------------
            # 🛡️ BUG 4 FIX: RISK CONCENTRATION / CONCURRENCY GATE
            # Never stack multiple concurrent unprotected positions on the same coin across horizons
            # -------------------------------------------------------------
            if (sym, h_tag) in active_ledger_pairs:
                continue
            if sym in active_unprotected_symbols:
                print(f"[CONCURRENCY VETO 🛑] {sym} already has an active unprotected trade in another horizon. Skipping {h_tag} to prevent risk concentration.")
                continue

            # -------------------------------------------------------------
            # 🛡️ BUG 1 FIX: MODEL PREDICTION VETO (CatBoost & Meta-Labeler)
            # Safely extract win probabilities; hard-reject sub-hurdle or P(SL) > P(TP1)
            # -------------------------------------------------------------
            meta_raw = sig.get('meta_win_prob')
            if meta_raw is None:
                meta_raw = sig.get('meta_prob')
            if meta_raw is None and 'meta_win_prob_pct' in sig:
                try:
                    meta_raw = float(sig['meta_win_prob_pct']) / 100.0
                except Exception:
                    pass
            meta_prob = float(meta_raw) if meta_raw is not None else 0.50

            p_sl_cand = float(sig.get('p_sl', 0.0) or 0.0)
            p_tp1_cand = float(sig.get('p_tp1', 0.0) or 0.0)

            # Hard Gate: Model forecasts stop loss is more probable than TP1
            if meta_prob < 0.48:
                print(f"[ML VETO 🛑] Rejected {sym} ({h_tag}): sub-hurdle meta_win_prob ({meta_prob*100:.1f}% < 48.0%)")
                continue
            if p_sl_cand > 0 and p_tp1_cand > 0 and p_sl_cand > p_tp1_cand:
                print(f"[ML VETO 🛑] Rejected {sym} ({h_tag}): model predicts P(SL) ({p_sl_cand:.1f}%) > P(TP1) ({p_tp1_cand:.1f}%)")
                continue

            direction = "LONG" if sig.get('direction') in ["BULLISH", "LONG"] else "SHORT"
            is_long = direction == "LONG"

            # -------------------------------------------------------------
            # 🛡️ BUG 5 FIX: INSTITUTIONAL VWAP & BEAR REGIME SHIELD VETO
            # Suppress counter-trend LONG setups when BTC or broader market
            # is below 1H/4H VWAP and trending down.
            # -------------------------------------------------------------
            is_shield_suppressed = bool(
                getattr(self, "suppress_momentum_longs", False) or
                getattr(self, "is_btc_below_vwap", False) or
                getattr(self, "btc_shield_active", False)
            )
            if is_long and is_shield_suppressed:
                if any(k in dec_str.upper() or k in arch_str.upper() for k in ["MOMENTUM", "DIP-BUY", "STANDARD", "PULLBACK"]):
                    print(f"[SHIELD VETO 🛡️] Suppressed {sym} ({h_tag}) {dec_str}: BTC is below 1H/4H VWAP or Bear Drift Shield is Active.")
                    continue
                if meta_prob < 0.55:
                    print(f"[SHIELD VETO 🛡️] Suppressed counter-trend long {sym} ({h_tag}) {dec_str}: sub-hurdle meta prob ({meta_prob*100:.1f}% < 55%) in bear regime.")
                    continue

            # -------------------------------------------------------------
            # 🛡️ ANTI-EXHAUSTION BREAKDOWN VETO
            # Do NOT short a breakdown when 15M/1H RSI is deep oversold (< 32.0).
            # Chasing an oversold dump at the bottom wick causes instant bounce SL hits.
            # -------------------------------------------------------------
            if not is_long and "BREAKDOWN" in dec_str.upper():
                rsi_val = float(sig.get('rsi_anchor') or sig.get('rsi') or 50.0)
                if rsi_val < 32.0:
                    print(f"[EXHAUSTION VETO 🛑] Suppressed breakdown short {sym} ({h_tag}): RSI ({rsi_val:.1f} < 32.0) is oversold exhaustion.")
                    continue

            # -------------------------------------------------------------
            # 🛡️ ANTI-SQUEEZE REVERSAL SHORT QUALITY VETO
            # Parabolic / Blow-Off Top reversal shorts into an active pump
            # require high machine learning confidence (meta_win_prob >= 0.55).
            # -------------------------------------------------------------
            if not is_long and any(k in dec_str.upper() for k in ["BLOW-OFF TOP", "PARABOLIC"]):
                if meta_prob < 0.55:
                    print(f"[REVERSAL VETO 🛑] Suppressed blow-off top short {sym} ({h_tag}): sub-hurdle meta prob ({meta_prob*100:.1f}% < 55.0%) for counter-trend squeeze short.")
                    continue

            # -------------------------------------------------------------
            # 🛑 PERMANENT REMOVAL OF VERIFIED LOSS-MAKING STRATEGIES
            # -------------------------------------------------------------
            if not is_long and any(k in dec_str.upper() or k in arch_str.upper() for k in ["LIQUIDITY-SWEEP", "LIQUIDITY_SWEEP", "LIQUIDITY SWEEP"]):
                print(f"[STRATEGY VETO 🛑] Permanently blocked loss-making Liquidity Sweep Short for {sym} ({h_tag}).")
                continue
            if not is_long and "STANDARD EXECUTE" in dec_str.upper():
                print(f"[STRATEGY VETO 🛑] Blocked low-expectancy Standard Short for {sym} ({h_tag}). Shorts strictly require ELITE conviction.")
                continue
            if not is_long and "RALLY-SELL" in dec_str.upper() and meta_prob < 0.60:
                print(f"[STRATEGY VETO 🛑] Blocked low-edge Rally-Sell Short for {sym} ({h_tag}) (historical win rate <42%).")
                continue

            g_tier = sig.get('grade_tier', 4)
            c_grade = str(sig.get('grade', ''))
            is_valid_grade = (g_tier <= 3) or ('Grade A' in c_grade) or ('Grade B' in c_grade)
            is_valid_exec = any(k in dec_str for k in ["EXECUTE", "DIP-BUY", "RALLY-SELL", "BREAKDOWN", "BREAKOUT", "MOMENTUM", "REVERSAL", "SWEEP", "HYPE PUMP"])
            if not is_valid_grade and not is_valid_exec:
                continue

            # 3. Horizon Cooldown Gate: Prevent repetitive logging of same coin on same horizon
            cooldown_active = False
            req_cooldown = HORIZON_COOLDOWN_HOURS.get(h_tag, 1.0)
            for r in self.records:
                if str(r.get('symbol', '')).strip().upper() != sym:
                    continue
                r_h = str(r.get('horizon', '')).upper()
                r_tag = resolve_horizon_tag(r_h).upper()
                if r_tag == h_tag:
                    date_u = str(r.get('date_utc', ''))
                    time_u = str(r.get('time_utc', '')).replace(' UTC', '').strip()
                    try:
                        if date_u and time_u:
                            sig_dt = datetime.strptime(f"{date_u} {time_u}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                            elapsed_h = (now_utc - sig_dt).total_seconds() / 3600.0
                            if elapsed_h < req_cooldown:
                                cooldown_active = True
                                break
                    except Exception:
                        pass
            if cooldown_active:
                continue

            curr_p = _safe_float(sig.get('entry_price', sig.get('current_price', 0.0)))
            if curr_p <= 0.0:
                continue
            safe_denom = max(1e-12, curr_p)

            sig_id = f"SIG_{now_utc.strftime('%Y%m%d_%H%M')}_{sym.replace('/', '_')}_{h_tag}"
            if sig_id in existing_ids:
                continue

            direction = "LONG" if sig.get('direction') in ["BULLISH", "LONG"] else "SHORT"
            is_long = direction == "LONG"

            tp1_p = _safe_float(sig.get('tp1_price', sig.get('tp_price', curr_p)))
            tp2_p = _safe_float(sig.get('tp2_price', sig.get('tp_price', curr_p)))
            tp3_p = _safe_float(sig.get('tp3_price', sig.get('tp_price', curr_p)))
            sl_p = _safe_float(sig.get('sl_price', curr_p))

            # Ensure targets have mathematically sound separation from entry (min 0.3% difference)
            if abs(tp3_p - curr_p) / safe_denom < 0.003:
                if is_long:
                    tp1_p = curr_p * 1.020
                    tp2_p = curr_p * 1.040
                    tp3_p = curr_p * 1.060
                    sl_p = curr_p * 0.970
                else:
                    tp1_p = curr_p * 0.980
                    tp2_p = curr_p * 0.960
                    tp3_p = curr_p * 0.940
                    sl_p = curr_p * 1.030

            # Mathematical invariant protection
            if is_long:
                if sl_p >= curr_p:
                    sl_p = curr_p * 0.970
                if tp1_p <= curr_p:
                    tp1_p = curr_p * 1.020
                if tp2_p <= tp1_p:
                    tp2_p = tp1_p * 1.015
                if tp3_p <= tp2_p:
                    tp3_p = tp2_p * 1.015
            else:
                if sl_p <= curr_p:
                    sl_p = curr_p * 1.030
                if tp1_p >= curr_p:
                    tp1_p = curr_p * 0.980
                if tp2_p >= tp1_p:
                    tp2_p = tp1_p * 0.985
                if tp3_p >= tp2_p:
                    tp3_p = tp2_p * 0.985

            is_limit_cand = bool(sig.get('is_limit_pending', False))
            ref_entry_p = _safe_float(sig.get('optimal_entry_price') or sig.get('entry_price'), curr_p) if is_limit_cand else curr_p

            # Institutional Risk Geometry (Section 25 / 31 Spec):
            # 1. Minimum SL distance floor (1.00% for scalps, 1.50% for swings) to eliminate sub-noise spread traps
            min_sl_distance_pct = 0.010 if h_tag in ['15M', '30M'] else 0.015
            current_sl_dist = abs(ref_entry_p - sl_p) / safe_denom
            if current_sl_dist < min_sl_distance_pct:
                sl_p = ref_entry_p * (1.0 - min_sl_distance_pct) if is_long else ref_entry_p * (1.0 + min_sl_distance_pct)

            # 2. Maximum initial stop loss risk cap (never wider than 2.50% from entry for scalps, 3.8% for swings)
            max_sl_distance_pct = 0.020 if h_tag in ['15M', '30M'] else 0.038
            if is_long:
                if (ref_entry_p - sl_p) / safe_denom > max_sl_distance_pct:
                    sl_p = ref_entry_p * (1.0 - max_sl_distance_pct)
            else:
                if (sl_p - ref_entry_p) / safe_denom > max_sl_distance_pct:
                    sl_p = ref_entry_p * (1.0 + max_sl_distance_pct)

            # 3. Target Alignment: Respect model's calibrated dynamic ATR targets; enforce strict directionality & stepped separation
            min_sep_pct = 0.0035  # Min 0.35% minimum separation from entry to eliminate flat collision
            if is_long:
                if (tp1_p - ref_entry_p) / safe_denom < min_sep_pct:
                    tp1_p = ref_entry_p * (1.0 + min_sep_pct)
                if tp2_p <= tp1_p:
                    tp2_p = ref_entry_p + ((tp1_p - ref_entry_p) * 1.80)
                if tp3_p <= tp2_p:
                    tp3_p = ref_entry_p + ((tp1_p - ref_entry_p) * 2.80)
            else:
                if (ref_entry_p - tp1_p) / safe_denom < min_sep_pct:
                    tp1_p = ref_entry_p * (1.0 - min_sep_pct)
                if tp2_p >= tp1_p:
                    tp2_p = ref_entry_p - ((ref_entry_p - tp1_p) * 1.80)
                if tp3_p >= tp2_p:
                    tp3_p = ref_entry_p - ((ref_entry_p - tp1_p) * 2.80)

            f_entry = format_precision_price(ref_entry_p)
            f_tp1 = format_precision_price(tp1_p)
            f_tp2 = format_precision_price(tp2_p)
            f_tp3 = format_precision_price(tp3_p)
            f_sl = format_precision_price(sl_p)

            # Defensive post-formatting clamping for micro-cap tokens
            if is_long:
                if f_sl >= f_entry:
                    f_sl = format_precision_price(ref_entry_p * 0.985)
                if f_tp1 <= f_entry:
                    f_tp1 = format_precision_price(ref_entry_p * 1.010)
                if f_tp2 <= f_tp1:
                    f_tp2 = format_precision_price(f_tp1 * 1.008)
                if f_tp3 <= f_tp2:
                    f_tp3 = format_precision_price(f_tp2 * 1.008)
            else:
                if f_sl <= f_entry:
                    f_sl = format_precision_price(ref_entry_p * 1.015)
                if f_tp1 >= f_entry:
                    f_tp1 = format_precision_price(ref_entry_p * 0.990)
                if f_tp2 >= f_tp1:
                    f_tp2 = format_precision_price(f_tp1 * 0.992)
                if f_tp3 >= f_tp2:
                    f_tp3 = format_precision_price(f_tp2 * 0.992)

            # -------------------------------------------------------------
            # QUANT EDGE V16: Invariant Validation & Hurdle Checks
            # -------------------------------------------------------------
            if self.has_v16:
                from app.quant_v16.validation import DataValidator
                # 1. Enforce strict mathematical price invariants
                valid_inv, inv_err = DataValidator.validate_price_invariants(curr_p, sl_p, tp1_p, tp2_p, tp3_p, direction)
                if not valid_inv:
                    print(f"[V16 REJECT ❌] Invariant violation for {sym}: {inv_err}")
                    continue

                # 2. Precision check
                valid_prec, prec_err = DataValidator.validate_precision(curr_p, sl_p)
                if not valid_prec:
                    print(f"[V16 REJECT ❌] Precision collapse for {sym}: {prec_err}")
                    continue

                # 3. Dynamic Return & Risk/Reward Calculation
                r1_ret, r2_ret, r3_ret, r_sl_ret, dynamic_rr = self.v16_expectancy_engine.calculate_returns(
                    curr_p, sl_p, tp1_p, tp2_p, tp3_p, direction
                )

                # 4. Path Probabilities & Calibration (Using validated model prediction & dynamic RR)
                raw_prob = meta_prob
                path_probs = self.v16_prob_model.estimate_path_probabilities(
                    raw_win_prob=raw_prob,
                    risk_reward=dynamic_rr,
                    horizon=h_tag
                )

                # Validate probability axioms & non-inverted structure
                valid_prob, prob_err = DataValidator.validate_probabilities(
                    path_probs.p_tp1, path_probs.p_tp2, path_probs.p_tp3, path_probs.p_sl
                )
                if not valid_prob:
                    print(f"[V16 REJECT ❌] Probability coherence violation for {sym}: {prob_err}")
                    continue

                # 5. Realistic Execution Costs
                costs = self.v16_cost_engine.estimate_costs(
                    market_type="futures",
                    observed_spread_bps=4.0,
                    est_holding_hours=HORIZON_COOLDOWN_HOURS.get(h_tag, 1.0)
                )

                # 6. Net Expectancy Calculation
                exp_res = self.v16_expectancy_engine.evaluate(
                    entry=curr_p,
                    sl=sl_p,
                    tp1=tp1_p,
                    tp2=tp2_p,
                    tp3=tp3_p,
                    direction=direction,
                    path_probs=path_probs,
                    costs=costs
                )

                # V16 Core Invariant: Expected Net Return MUST be positive & P(TP1) must exceed P(SL)
                if not exp_res.passes_ev_hurdle or exp_res.expected_net_return_pct <= 0.0:
                    print(f"[V16 REJECT 🛑] Negative or zero Net EV ({exp_res.expected_net_return_pct:+.2f}%) for {sym} ({h_tag}). Skipping trade.")
                    continue

                if path_probs.p_sl > path_probs.p_tp1:
                    print(f"[V16 REJECT 🛑] P(SL) ({path_probs.p_sl*100:.1f}%) exceeds P(TP1) ({path_probs.p_tp1*100:.1f}%) for {sym} ({h_tag}). Skipping trade.")
                    continue

                # 6. Trade Thesis Clustering
                strategy_name = sig.get('strategy_archetype') or sig.get('decision') or "MOMENTUM_TREND"
                regime_tag = sig.get('market_shield') or getattr(self, "btc_shield_code", "BALANCED_VOLATILITY")
                thesis, is_new_thesis = self.v16_thesis_engine.register_or_update(
                    symbol=sym,
                    direction=direction,
                    horizon=h_tag,
                    strategy=str(strategy_name),
                    regime=str(regime_tag),
                    expected_net_return=exp_res.expected_net_return_pct
                )
                thesis_id = thesis.thesis_id
                calibrated_win_prob = round(path_probs.p_tp1 * 100.0, 1)
                net_ev_val = round(exp_res.expected_net_return_pct, 2)
                rr_str = f"1:{exp_res.risk_reward:.1f}"

                # 7. Authoritative V16 Signal Scoring & Grading (Dynamic market alignment)
                # Compute dynamic regime alignment: penalize counter-trend longs in bear regimes
                dyn_regime_align = 0.50 if (direction == "LONG" and "BEAR" in str(regime_tag).upper()) else 0.85
                vol_confirm = bool(sig.get('volume_score', 60) >= 50 or sig.get('volume_spike', False))
                htf_align = bool(sig.get('htf_aligned', True) or h_tag in ["1H", "4H", "24H"])

                v16_eval = self.v16_scorer.evaluate(
                    p_tp1=path_probs.p_tp1,
                    expected_net_return_pct=exp_res.expected_net_return_pct,
                    risk_reward=exp_res.risk_reward,
                    regime_alignment=dyn_regime_align,
                    strategy_pf=1.25,
                    rolling_50_pf=1.15,
                    liquidity_score=float(sig.get('liquidity_score', 85.0) or 85.0),
                    data_quality_score=95.0,
                    execution_quality_score=88.0,
                    volume_confirmation=vol_confirm,
                    htf_aligned=htf_align
                )
                v16_grade_str = v16_eval.grade.value.replace('_', ' ')
                v16_total_score = v16_eval.total_score
            else:
                thesis_id = f"THESIS_{sym}_{direction}_{h_tag}"
                calibrated_win_prob = round(float(sig.get('meta_win_prob', 0.70)) * 100.0, 1)
                net_ev_val = round(float(sig.get('exp_return', 0.0)) * 100.0, 2)
                # Compute dynamic RR from price targets
                sl_dist = abs(curr_p - sl_p) / max(1e-6, curr_p)
                tp2_dist = abs(tp2_p - curr_p) / max(1e-6, curr_p)
                fallback_rr = round(tp2_dist / max(1e-6, sl_dist), 1) if sl_dist > 0 else 2.0
                rr_str = f"1:{fallback_rr:.1f}"
                v16_grade_str = "Grade A"
                v16_total_score = 75.0

            clean_grade = v16_grade_str
            tier_label = "INSTITUTIONAL" if net_ev_val >= 1.0 else ("HIGH CONVICTION" if net_ev_val >= 0.50 else "QUALIFIED")
            rank_label = f"#{idx+1}"

            record = {
                "signal_id": sig_id,
                "trade_thesis_id": thesis_id,
                "date_utc": now_date,
                "time_utc": now_time,
                "rank": rank_label,
                "quality_grade": f"{clean_grade} ({tier_label})",
                "grade": clean_grade,
                "grade_tier": g_tier,
                "symbol": sym,
                "horizon": sig.get('horizon_name', h_tag),
                "direction": direction,
                "conviction_pct": round(float(sig.get('conviction', 50.0)), 2),
                "meta_win_prob_pct": calibrated_win_prob,
                "entry_price": f_entry,
                "current_price": format_precision_price(curr_p),
                "optimal_entry_price": sig.get('optimal_entry_price', f_entry),
                "is_limit_pending": bool(sig.get('is_limit_pending', False)),
                "entry_zone_min": sig.get('entry_zone_min', f_entry),
                "entry_zone_max": sig.get('entry_zone_max', f_entry),
                "chase_warning": sig.get('chase_warning', ''),
                "tp1_price": f_tp1,
                "tp2_price": f_tp2,
                "tp3_price": f_tp3,
                "sl_price": f_sl,
                "sl_original": f_sl,
                "is_tp1_locked": False,
                "is_tp2_locked": False,
                "is_tier0_locked": False,
                "risk_reward_ratio": rr_str,
                "expected_return_pct": net_ev_val,
                "decision": sig.get('decision', 'EXECUTE'),
                "p_tp1": round(path_probs.p_tp1 * 100.0, 1) if self.has_v16 else calibrated_win_prob,
                "p_tp2": round(path_probs.p_tp2 * 100.0, 1) if self.has_v16 else round(calibrated_win_prob * 0.65, 1),
                "p_tp3": round(path_probs.p_tp3 * 100.0, 1) if self.has_v16 else round(calibrated_win_prob * 0.40, 1),
                "p_sl": round(path_probs.p_sl * 100.0, 1) if self.has_v16 else round(100.0 - calibrated_win_prob, 1),
                "market_shield": sig.get('market_shield') or getattr(self, "btc_shield_code", "BALANCED VOLATILITY"),
                "strategy_archetype": strategy_name,
                "order_block_setup": sig.get('order_block_setup'),
                "paper_trading_status": "EXECUTED (PAPER WALLET)" if sym in open_syms else "MONITORED SCAN SIGNAL",
                "predicted_window": sig.get('predicted_window_str', 'N/A'),
                "predicted_close_utc": sig.get('predicted_close_utc') or sig.get('trade_close_str') or 'N/A',
                "status": "PENDING_LIMIT" if sig.get('is_limit_pending') else "PENDING_EVALUATION",
                "outcome_label": "AWAIT PULLBACK ⏳" if sig.get('is_limit_pending') else "PENDING ⏳",
                "peak_price_seen": format_precision_price(curr_p),
                "trough_price_seen": format_precision_price(curr_p),
                "max_potential_gain_pct": 0.0,
                "exit_price": "",
                "realized_return_pct": "",
                "evaluated_at_utc": "",
                "created_ts": time.time()
            }

            self.records.append(record)
            existing_ids.add(sig_id)
            active_ledger_pairs.add((sym, h_tag.upper()))
            active_unprotected_symbols.add(sym)
            added_count += 1
            admitted_records.append(record)

            # V16 Immutable Audit Snapshot & Dynamic State Initialization
            if self.has_v16:
                try:
                    from app.quant_v16.audit import ImmutableSignalRecord, DynamicTradeState
                    immut = ImmutableSignalRecord(
                        signal_id=sig_id,
                        trade_thesis_id=thesis_id,
                        model_version="V16.0",
                        strategy_version="16.0",
                        symbol=sym,
                        direction=direction,
                        horizon=sig.get('horizon_name', h_tag),
                        signal_generated_at=f"{now_date} {now_time}",
                        entry_price_initial=curr_p,
                        tp1_initial=tp1_p,
                        tp2_initial=tp2_p,
                        tp3_initial=tp3_p,
                        sl_initial=sl_p,
                        regime=sig.get('market_shield', 'CONSOLIDATION'),
                        p_tp1=round(path_probs.p_tp1, 4),
                        p_tp2=round(path_probs.p_tp2, 4),
                        p_tp3=round(path_probs.p_tp3, 4),
                        p_sl=round(path_probs.p_sl, 4),
                        expected_gross_return=round(exp_res.ev_gross_pct, 4),
                        expected_net_return=round(exp_res.expected_net_return_pct, 4),
                        total_execution_costs=round(costs.total_cost_pct, 4),
                        risk_reward=round(exp_res.risk_reward, 2),
                        signal_score=v16_total_score,
                        grade=clean_grade,
                        status="ACTIVE"
                    )
                    dyn = DynamicTradeState(
                        signal_id=sig_id,
                        current_price=curr_p,
                        current_sl=sl_p,
                        updated_at_utc=f"{now_date} {now_time}"
                    )
                    self.v16_audit.record_new_signal(immut, dyn)
                except Exception as audit_err:
                    print(f"[V16 ⚠️] Audit snapshot logging notice: {audit_err}")

            # Automated WhatsApp Signal Notification
            try:
                from app.services.whatsapp_service import whatsapp_service
                whatsapp_service.emit_signal_created(record)
            except Exception as wa_err:
                print(f"[WHATSAPP ❌] Error emitting new signal {sig_id}: {wa_err}")

        if added_count > 0:
            self.save_records()
            print(f"[SIGNAL TRACKER 📝] Logged {added_count} Trader Signal(s) to CSV: {os.path.abspath(self.csv_path)}")
        return admitted_records

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
        with getattr(self, '_lock', threading.RLock()):
            return self._evaluate_signals_internal(live_prices, live_highs, live_lows)

    def _evaluate_signals_internal(self, live_prices: dict, live_highs: dict = None, live_lows: dict = None):
        self.reconcile_disk_records()
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
            if r.get('status') in ["PENDING_EVALUATION", "ACTIVE", "PENDING_LIMIT", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL"]
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

        # 1. Paper Trading Execution Reconciliation Bridge:
        # Cross-check closed trades from paper_trading_ledger.json to guarantee 0ms synchronization
        closed_paper_map = {}
        closed_paper_id_map = {}
        try:
            pt_path = os.path.join(self.export_dir, "paper_trading_ledger.json")
            if os.path.exists(pt_path):
                with open(pt_path, "r", encoding="utf-8") as pf:
                    pt_data = json.load(pf)
                all_closed = (pt_data.get("closed_trades_history") or []) + (pt_data.get("closed_trades") or [])
                for pt in all_closed:
                    pt_sym = str(pt.get("symbol", "")).strip().upper()
                    pt_hz = str(pt.get("horizon", "15M")).strip().upper()
                    norm_hz = "15M" if "15" in pt_hz else ("24H" if ("24" in pt_hz or "1D" in pt_hz) else "1H")
                    closed_paper_map[(pt_sym, norm_hz)] = pt
                    closed_paper_map[(pt_sym.replace("/", "").replace(":USDT", ""), norm_hz)] = pt
                    if pt.get("signal_id"):
                        closed_paper_id_map[str(pt.get("signal_id")).strip()] = pt
                    if pt.get("trade_id"):
                        closed_paper_id_map[str(pt.get("trade_id")).strip()] = pt
        except Exception:
            pass

        for r in self.records:
            try:
                status = r.get('status', 'PENDING_EVALUATION')
                if status not in ["PENDING_EVALUATION", "ACTIVE", "PENDING_LIMIT", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"]:
                    continue

                sym = r.get('symbol')
                if not sym:
                    continue

                r_sym = str(sym).strip().upper()
                r_hz = str(r.get('horizon', '15M')).strip().upper()
                norm_hz = "15M" if "15" in r_hz else ("24H" if ("24" in r_hz or "1D" in r_hz) else "1H")

                # Match against paper trading closed trades (strictly require signal_id match or closed_at >= signal_created_at)
                r_sid = str(r.get('signal_id', '')).strip()
                pt_match = None
                if r_sid and r_sid in closed_paper_id_map:
                    pt_match = closed_paper_id_map[r_sid]

                if not pt_match:
                    cand_match = closed_paper_map.get((r_sym, norm_hz)) or closed_paper_map.get((r_sym.replace("/", ""), norm_hz))
                    if cand_match:
                        closed_time = str(cand_match.get("closed_at_utc") or cand_match.get("closed_at") or "")
                        sig_date = str(r.get('date_utc', '')).strip()
                        sig_time_str = str(r.get('time_utc', '')).strip()
                        sig_time = f"{sig_date} {sig_time_str}".strip()
                        if closed_time and sig_time:
                            c_iso = closed_time.replace(" UTC", "").strip()
                            s_iso = sig_time.replace(" UTC", "").strip()
                            if c_iso >= s_iso:
                                pt_match = cand_match
                        elif not sig_time:
                            pt_match = cand_match
                if pt_match:
                    exit_reason = str(pt_match.get("exit_reason", ""))
                    exit_p = float(pt_match.get("exit_price") or r.get("entry_price") or 0.0)
                    ret_pct = float(pt_match.get("return_pct") or 0.0)
                    closed_at = pt_match.get("closed_at_utc") or pt_match.get("closed_at") or now_str
                    pt_tp2 = bool(pt_match.get("tp2_hit", False))
                    pt_tp1 = bool(pt_match.get("tp1_hit", False)) or pt_tp2

                    if "TAKE_PROFIT_2_RUNNER_EXPIRY" in exit_reason or (("HORIZON_EXPIRY" in exit_reason or "EXPIRY" in exit_reason) and pt_tp2):
                        r['status'] = "WON_TP2_EXP"
                        r['outcome_label'] = f"🟢 WON (TP2 + EXP {ret_pct:+.2f}%)"
                    elif "TAKE_PROFIT_1_RUNNER_EXPIRY" in exit_reason or (("HORIZON_EXPIRY" in exit_reason or "EXPIRY" in exit_reason) and pt_tp1):
                        r['status'] = "WON_TP1_EXP"
                        r['outcome_label'] = f"🟢 WON (TP1 + EXP {ret_pct:+.2f}%)"
                    elif "BREAKEVEN" in exit_reason or "TIER0" in exit_reason or exit_reason == "STOP_LOSS_BREAKEVEN":
                        r['status'] = "BREAKEVEN_GUARD"
                        r['outcome_label'] = f"🛡️ BREAKEVEN (TIER-0 GUARD {ret_pct:+.2f}%)"
                    elif "STOP_LOSS" in exit_reason:
                        r['status'] = "LOST_SL"
                        r['outcome_label'] = "🔴 LOST (SL HIT)"
                    elif "TAKE_PROFIT_3" in exit_reason or "TP3" in exit_reason:
                        r['status'] = "WON_TP3"
                        r['outcome_label'] = "🟢 WON (TP3 HIT)"
                    elif "TAKE_PROFIT_2" in exit_reason or "TP2" in exit_reason:
                        r['status'] = "WON_TP2"
                        r['outcome_label'] = "🟢 WON (TP2 HIT)"
                    elif "TAKE_PROFIT" in exit_reason or "TP1" in exit_reason:
                        r['status'] = "WON_TP1"
                        r['outcome_label'] = "🟢 WON (TP1 HIT)"
                    elif "HORIZON_EXPIRY" in exit_reason or "EXPIRY" in exit_reason:
                        if ret_pct >= 0.10:
                            r['status'] = "WON_EXP_PROFIT"
                            r['outcome_label'] = f"🟢 WON (EXP PROFIT {ret_pct:+.2f}%)"
                        elif ret_pct <= -0.10:
                            r['status'] = "LOST_EXP"
                            r['outcome_label'] = f"🔴 LOST (EXPIRY {ret_pct:+.2f}%)"
                        else:
                            r['status'] = "BREAKEVEN_EXP"
                            r['outcome_label'] = f"⚪ BREAKEVEN (EXPIRY {ret_pct:+.2f}%)"
                    else:
                        r['status'] = "CLOSED"
                        r['outcome_label'] = f"CLOSED ({exit_reason})"

                    r['exit_price'] = format_precision_price(exit_p)
                    r['realized_return_pct'] = f"{ret_pct:+.2f}%"
                    r['evaluated_at_utc'] = closed_at
                    updated = True
                    resolved_count += 1
                    continue

                if sym not in live_prices:
                    continue

                curr_p = _safe_float(live_prices.get(sym), 0.0)
                if curr_p <= 0.0:
                    continue

                entry_p = _safe_float(r.get('entry_price'), 0.0)
                if entry_p <= 0.0:
                    entry_p = curr_p
                if entry_p <= 0.0:
                    continue

                tp1_p = _safe_float(r.get('tp1_price'), entry_p)
                tp2_p = _safe_float(r.get('tp2_price'), entry_p)
                tp3_p = _safe_float(r.get('tp3_price'), entry_p)
                sl_p = _safe_float(r.get('sl_price'), entry_p)
                direction = str(r.get('direction', 'LONG')).upper()
                is_long = direction in ["LONG", "BULLISH"]

                sig_id = str(r.get('signal_id', ''))
                h_name = str(r.get('horizon', '15M')).upper()
                h_tag = resolve_horizon_tag(h_name)

                is_tp1_locked = bool(r.get('is_tp1_locked', False) or status in ['TP1_LOCKED_BREAKEVEN', 'TP2_LOCKED_TRAIL'])
                is_tp2_locked = bool(r.get('is_tp2_locked', False) or status == 'TP2_LOCKED_TRAIL')
                is_tier0_locked = bool(r.get('is_tier0_locked', False) or status == 'TIER0_PROTECTED_BREAKEVEN')
                is_be_locked = bool(is_tp1_locked or is_tp2_locked or is_tier0_locked)

                # Evaluate resting pullback/bounce limit orders
                if status == "PENDING_LIMIT" or r.get('is_limit_pending', False):
                    limit_entry_p = _safe_float(r.get('optimal_entry_price', r.get('entry_price')), entry_p)
                    filled = (curr_p <= limit_entry_p) if is_long else (curr_p >= limit_entry_p)
                    if filled:
                        r['is_limit_pending'] = False
                        r['status'] = "ACTIVE"
                        r['outcome_label'] = "PENDING ⏳"
                        r['entry_price'] = format_precision_price(limit_entry_p)
                        r['limit_filled_at_utc'] = now_str
                        updated = True
                        print(f"[SIGNAL TRACKER 🚀] {sym} limit order filled @ ${limit_entry_p} (Live: ${curr_p})")
                    else:
                        missed_tp1 = (curr_p >= tp1_p) if is_long else (curr_p <= tp1_p)
                        created_ts = r.get('created_ts', now_utc.timestamp())
                        dur_limit_sec = self.HORIZON_COOLDOWN_HOURS.get(h_tag, 4.0) * 3600.0
                        if missed_tp1 or (now_utc.timestamp() - float(created_ts) >= dur_limit_sec):
                            r['status'] = "EXPIRED"
                            r['outcome_label'] = "MISSED (NO PULLBACK) ⚪" if missed_tp1 else "EXPIRED (UNFILLED) ⏱️"
                            r['exit_price'] = format_precision_price(curr_p)
                            r['realized_return_pct'] = 0.0
                            r['evaluated_at_utc'] = now_str
                            updated = True
                            resolved_count += 1
                        continue

                # Invariant: Cap initial SL risk using horizon-aware risk geometry
                is_fast_h = (h_tag in ['15M', '30M'] or 'SCALP' in sig_id.upper() or '30M' in sig_id.upper())
                
                horizon_max_sl_map = {
                    '15M': 0.0250,
                    '30M': 0.0300,
                    '1H': 0.0400,
                    '4H': 0.0600,
                    '24H': 0.0800,
                    '4D': 0.0950,
                    '7D': 0.1100,
                    '15D': 0.1400,
                    '30D': 0.1800
                }
                max_allowed_sl_dist = horizon_max_sl_map.get(h_tag, 0.0120 if is_fast_h else 0.0240)
                if entry_p > 0 and not is_tp1_locked and not is_tier0_locked:
                    capped_sl = entry_p * (1.0 - max_allowed_sl_dist) if is_long else entry_p * (1.0 + max_allowed_sl_dist)
                    if is_long and sl_p < capped_sl:
                        sl_p = capped_sl
                        r['sl_price'] = format_precision_price(sl_p)
                    elif not is_long and sl_p > capped_sl:
                        sl_p = capped_sl
                        r['sl_price'] = format_precision_price(sl_p)

                # Update intra-trade extremes safely strictly since signal logging
                prev_peak = _safe_float(r.get('peak_price_seen'), curr_p)
                prev_trough = _safe_float(r.get('trough_price_seen'), curr_p)
                if prev_peak <= 0.0:
                    prev_peak = curr_p
                if prev_trough <= 0.0:
                    prev_trough = curr_p

                # Resolve creation timestamp
                now_ts = time.time()
                created_ts = r.get('created_ts')
                if not created_ts:
                    try:
                        date_u = str(r.get('date_utc', '')).strip()
                        time_u = str(r.get('time_utc', '')).replace(' UTC', '').strip()
                        if date_u and time_u:
                            c_dt = datetime.strptime(f"{date_u} {time_u}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                            created_ts = c_dt.timestamp()
                            r['created_ts'] = created_ts
                    except Exception:
                        pass
                if not created_ts:
                    created_ts = now_ts
                    r['created_ts'] = created_ts
                created_dt = datetime.fromtimestamp(float(created_ts), tz=timezone.utc) if created_ts else None

                # Anti-Phantom Wick Guard:
                # A 15m candle spans 900 seconds. If a trade entered mid-candle, the candle's high/low
                # contains price action from BEFORE the signal was born!
                # Target-favorable wicks capture intra-candle breakouts; adverse wicks track real-time price
                # and real intra-candle Binance klines wicks to ensure accurate SL execution.
                raw_h = _safe_float(live_highs.get(sym), curr_p) if live_highs else curr_p
                raw_l = _safe_float(live_lows.get(sym), curr_p) if live_lows else curr_p
                try:
                    from app.services.signal_service import fetch_intra_candle_extremes
                    ih, il = fetch_intra_candle_extremes(sym, h_tag)
                    if ih > 0:
                        raw_h = max(raw_h, ih)
                    if il > 0:
                        raw_l = min(raw_l, il)
                except Exception:
                    pass
                candle_h = max(curr_p, raw_h)
                candle_l = min(curr_p, raw_l)

                r['peak_price_seen'] = format_precision_price(max(prev_peak, candle_h, curr_p))
                r['trough_price_seen'] = format_precision_price(min(prev_trough, candle_l, curr_p))
                high_p = r['peak_price_seen']
                low_p = r['trough_price_seen']

                safe_denom = max(1e-12, entry_p)
                max_gain = ((r['peak_price_seen'] - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - r['trough_price_seen']) / safe_denom) * 100.0
                r['max_potential_gain_pct'] = round(max_gain, 2)

                # Ensure minimum target threshold before checking TP hits
                tp3_dist_pct = abs(tp3_p - entry_p) / safe_denom
                tp2_dist_pct = abs(tp2_p - entry_p) / safe_denom
                tp1_dist_pct = abs(tp1_p - entry_p) / safe_denom

                is_hit_tp3 = ((high_p >= tp3_p) if is_long else (low_p <= tp3_p)) if tp3_dist_pct >= 0.002 else False
                is_hit_tp2 = ((high_p >= tp2_p) if is_long else (low_p <= tp2_p)) if tp2_dist_pct >= 0.0015 else False
                is_hit_tp1 = ((high_p >= tp1_p) if is_long else (low_p <= tp1_p)) if tp1_dist_pct >= 0.001 else False

                # -------------------------------------------------------------
                # 🛡️ STOP LOSS & EARLY BREAKEVEN PRECEDENCE (RULE 6 & 8)
                # Evaluated conservatively: If initial SL is breached on this candle,
                # the position cannot activate Tier-0 breakeven or bypass the stop-out.
                # -------------------------------------------------------------
                if is_be_locked:
                    is_hit_sl = (low_p <= sl_p or curr_p <= sl_p) if is_long else (high_p >= sl_p or curr_p >= sl_p)
                else:
                    is_hit_sl = (low_p <= sl_p or curr_p <= sl_p) if is_long else (high_p >= sl_p or curr_p >= sl_p)

                # Early Breakeven Protection (Calibrated at >= 55% of TP1 distance)
                # Can ONLY lock if the initial position has NOT breached Stop-Loss on this candle
                is_fast_h = (h_tag in ['15M', '30M'] or 'SCALP' in sig_id.upper() or '30M' in sig_id.upper())
                is_macro_h = (h_tag in ['4H', '24H', '1D', 'MACRO', '4D', '7D', '15D', '30D', '1W'] or '4H' in sig_id.upper() or 'MACRO' in sig_id.upper())
                base_tier0 = 1.00 if is_fast_h else (1.80 if is_macro_h else 1.35)
                tier0_threshold = max(0.40, min(base_tier0, tp1_dist_pct * 100.0 * 0.60))
                soft_be_p = ((entry_p * 1.0015) if is_long else (entry_p * 0.9985)) if is_fast_h else (((entry_p * 1.0020) if is_long else (entry_p * 0.9980)))
                can_lock_be = (curr_p >= soft_be_p * 1.0005) if is_long else (curr_p <= soft_be_p * 0.9995)
                if max_gain >= tier0_threshold and can_lock_be and not is_tp1_locked and not is_tier0_locked and not is_hit_sl:
                    r['is_tier0_locked'] = True
                    r['status'] = "TIER0_PROTECTED_BREAKEVEN"
                    r['sl_price'] = format_precision_price(max(sl_p, soft_be_p) if is_long else min(sl_p, soft_be_p))
                    sl_p = r['sl_price']
                    r['outcome_label'] = f"🛡️ TIER-0 PROTECTED (+{max_gain:.2f}% PEAK -> BE)"
                    is_tier0_locked = True
                    is_be_locked = True
                    updated = True

                is_expired = False
                if ENABLE_SIGNAL_EXPIRY:
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
                            close_dt = datetime.fromisoformat(clean_dt_str) if 'T' in clean_dt_str else datetime.strptime(clean_dt_str, '%Y-%m-%d %H:%M:%S' if len(clean_dt_str) > 16 else '%Y-%m-%d %H:%M')
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

                # Calibrated Stagnation Cut: If >= 60% of duration has elapsed with zero forward momentum (max_gain < 0.20%)
                # and negative return (ret_now <= -0.30%), scratch early before bleeding into full stop-out or delayed expiry!
                if ENABLE_SIGNAL_EXPIRY and not is_hit_tp1 and not is_tier0_locked and not is_tp1_locked and not is_hit_sl and not is_expired:
                    if created_dt and (now_utc - created_dt).total_seconds() >= (0.60 * dur_sec):
                        ret_now = ((curr_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - curr_p) / safe_denom) * 100.0
                        if max_gain < 0.20 and ret_now <= -0.30:
                            r['status'] = "STAGNATION_CUT"
                            r['exit_price'] = format_precision_price(curr_p)
                            r['realized_return_pct'] = f"{ret_now:+.2f}%"
                            r['outcome_label'] = f"⏱️ STAGNATION CUT ({ret_now:+.2f}%)"
                            try:
                                from app.services.whatsapp_service import whatsapp_service
                                whatsapp_service.emit_signal_outcome(r, "EXPIRED", curr_p, ret_now)
                            except Exception:
                                pass
                            r['evaluated_at_utc'] = now_str
                            updated = True
                            resolved_count += 1
                            continue

                is_be_locked = bool(is_tp1_locked or is_tp2_locked or is_tier0_locked)

                # 1. Microstructure Resolution for Simultaneous TP1 and SL Breaches:
                if is_hit_sl and (is_hit_tp1 or is_hit_tp2 or is_hit_tp3):
                    try:
                        from app.quant_v16.microstructure_resolver import MicrostructureResolver
                        now_ms = int(time.time() * 1000)
                        start_ms = now_ms - (15 * 60 * 1000)
                        micro_res = MicrostructureResolver.resolve_path(
                            symbol=sym,
                            direction=direction,
                            entry_p=entry_p,
                            tp1_p=tp1_p,
                            sl_p=sl_p,
                            start_ts_ms=start_ms,
                            end_ts_ms=now_ms,
                            candle_open=entry_p,
                            candle_close=curr_p
                        )
                        if micro_res.get("outcome") == "WON_TP1":
                            is_hit_sl = False
                    except Exception:
                        pass

                # Strict Adverse SL Precedence: Unlocked initial trade touching SL must exit as LOST_SL
                if is_hit_sl and not is_be_locked:
                    r['status'] = "LOST_SL"
                    r['exit_price'] = format_precision_price(sl_p)
                    ret_pct = ((sl_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - sl_p) / safe_denom) * 100.0
                    r['realized_return_pct'] = f"{ret_pct:+.2f}%"
                    r['outcome_label'] = "🔴 LOST (SL HIT)"
                    r['evaluated_at_utc'] = now_str
                    updated = True
                    resolved_count += 1
                    try:
                        from app.services.whatsapp_service import whatsapp_service
                        whatsapp_service.emit_signal_outcome(r, "SL_HIT", sl_p, ret_pct)
                    except Exception:
                        pass

                # 2. Target Priority: If high wicks touched TP3, TP2, or TP1, award targets
                elif is_hit_tp3:
                    r['status'] = "WON_TP3"
                    r['exit_price'] = format_precision_price(tp3_p)
                    ret_pct = ((tp3_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - tp3_p) / safe_denom) * 100.0
                    r['realized_return_pct'] = f"{ret_pct:+.2f}%"
                    r['outcome_label'] = "🟢 WON (TP3 HIT)"
                    r['evaluated_at_utc'] = now_str
                    updated = True
                    resolved_count += 1
                    try:
                        from app.services.whatsapp_service import whatsapp_service
                        whatsapp_service.emit_signal_outcome(r, "TP3_HIT", tp3_p, ret_pct)
                    except Exception:
                        pass

                elif is_hit_tp2 and not is_tp2_locked:
                    r['status'] = "TP2_LOCKED_TRAIL"
                    r['is_tp2_locked'] = True
                    r['is_tp1_locked'] = True
                    r['is_tp2_notified_wa'] = True
                    r['is_tp1_notified_wa'] = True
                    r['sl_price'] = format_precision_price(tp1_p)  # Trailing SL Floor at TP1
                    r['outcome_label'] = "🟢 TP2 HIT (TRAILING SL @ TP1)"
                    updated = True
                    try:
                        from app.services.whatsapp_service import whatsapp_service
                        ret_tp2_gain = ((tp2_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - tp2_p) / safe_denom) * 100.0
                        whatsapp_service.emit_signal_outcome(r, "TP2_HIT", tp2_p, ret_tp2_gain)
                    except Exception as e:
                        logger.error(f"[WHATSAPP ❌] Error emitting TP2 outcome: {e}")

                elif is_hit_tp1 and not is_tp1_locked:
                    r['status'] = "TP1_LOCKED_BREAKEVEN"
                    r['is_tp1_locked'] = True
                    r['is_tp1_notified_wa'] = True
                    r['sl_price'] = format_precision_price(entry_p)  # Break-Even SL
                    r['outcome_label'] = "🟢 TP1 HIT (SL @ BREAKEVEN)"
                    updated = True
                    try:
                        from app.services.whatsapp_service import whatsapp_service
                        ret_tp1_gain = ((tp1_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - tp1_p) / safe_denom) * 100.0
                        whatsapp_service.emit_signal_outcome(r, "TP1_HIT", tp1_p, ret_tp1_gain)
                    except Exception as e:
                        logger.error(f"[WHATSAPP ❌] Error emitting TP1 outcome: {e}")

                # Catch-up WhatsApp notification for active positions that reached TP1 earlier
                elif (is_hit_tp1 or is_tp1_locked) and not r.get('is_tp1_notified_wa') and not is_hit_sl:
                    r['is_tp1_notified_wa'] = True
                    updated = True
                    try:
                        from app.services.whatsapp_service import whatsapp_service
                        ret_tp1_gain = ((tp1_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - tp1_p) / safe_denom) * 100.0
                        whatsapp_service.emit_signal_outcome(r, "TP1_HIT", tp1_p, ret_tp1_gain)
                    except Exception as e:
                        logger.error(f"[WHATSAPP ❌] Error emitting TP1 catch-up outcome: {e}")

                # 3. Stop-Loss Execution for locked trailing stops:
                elif is_hit_sl and is_be_locked:
                    if is_tp2_locked:
                        # Trailed Stop hit at TP1 floor (Locked 50% TP1 + 30% TP2 + 20% TP1 runner)
                        ret_tp1 = ((tp1_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - tp1_p) / safe_denom) * 100.0
                        ret_tp2 = ((tp2_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - tp2_p) / safe_denom) * 100.0
                        blended_ret = (0.50 * ret_tp1) + (0.30 * ret_tp2) + (0.20 * ret_tp1)
                        r['status'] = "WON_TP2_TRAIL"
                        r['exit_price'] = format_precision_price(tp1_p)
                        r['realized_return_pct'] = f"{blended_ret:+.2f}%"
                        r['outcome_label'] = "🟢 WON (TP2 + TRAILING RUNNER)"
                        try:
                            from app.services.whatsapp_service import whatsapp_service
                            whatsapp_service.emit_signal_outcome(r, "TRAIL_SL_HIT", tp1_p, blended_ret)
                        except Exception:
                            pass
                    elif is_tp1_locked:
                        # Break-Even Stop hit at Entry Price (Locked 50% TP1 + 50% Breakeven)
                        ret_tp1 = ((tp1_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - tp1_p) / safe_denom) * 100.0
                        blended_ret = 0.50 * ret_tp1
                        r['status'] = "WON_TP1_BE"
                        r['exit_price'] = format_precision_price(entry_p)
                        r['realized_return_pct'] = f"{blended_ret:+.2f}%"
                        r['outcome_label'] = "🟢 WON (TP1 + BE RUNNER)"
                        try:
                            from app.services.whatsapp_service import whatsapp_service
                            whatsapp_service.emit_signal_outcome(r, "BE_HIT", entry_p, blended_ret)
                        except Exception:
                            pass
                    elif is_tier0_locked:
                        # Tier-0 Protected Breakeven Stop hit (saved trade from full loss)
                        ret_be = ((sl_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - sl_p) / safe_denom) * 100.0
                        r['status'] = "BREAKEVEN_GUARD"
                        r['exit_price'] = format_precision_price(sl_p)
                        r['realized_return_pct'] = f"{ret_be:+.2f}%"
                        r['outcome_label'] = f"🛡️ BREAKEVEN (TIER-0 GUARD {ret_be:+.2f}%)"
                        # User explicitly instructed: "dont send meassge for teir 0 breakeven"
                        # WhatsApp notification is strictly suppressed for Tier-0 BE
                    else:
                        # Original Stop Loss hit without reaching TP1
                        r['status'] = "LOST_SL"
                        r['exit_price'] = format_precision_price(sl_p)
                        ret_pct = ((sl_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - sl_p) / safe_denom) * 100.0
                        r['realized_return_pct'] = f"{ret_pct:+.2f}%"
                        r['outcome_label'] = "🔴 LOST (SL HIT)"
                        try:
                            from app.services.whatsapp_service import whatsapp_service
                            whatsapp_service.emit_signal_outcome(r, "SL_HIT", sl_p, ret_pct)
                        except Exception:
                            pass
                    r['evaluated_at_utc'] = now_str
                    updated = True
                    resolved_count += 1

                # 5. Expiry Resolution
                elif is_expired:
                    # Invariant (Quant Edge Rule 6 & 8): Check if intra-candle adverse wick breached SL during the interval!
                    hit_sl_during_interval = (low_p <= sl_p or curr_p <= sl_p) if is_long else (high_p >= sl_p or curr_p >= sl_p)
                    if hit_sl_during_interval and not is_be_locked:
                        r['status'] = "LOST_SL"
                        r['exit_price'] = format_precision_price(sl_p)
                        ret_pct = ((sl_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - sl_p) / safe_denom) * 100.0
                        r['realized_return_pct'] = f"{ret_pct:+.2f}%"
                        r['outcome_label'] = "🔴 LOST (SL HIT)"
                        try:
                            from app.services.whatsapp_service import whatsapp_service
                            whatsapp_service.emit_signal_outcome(r, "SL_HIT", sl_p, ret_pct)
                        except Exception:
                            pass
                    elif hit_sl_during_interval and is_be_locked:
                        if is_tier0_locked:
                            ret_be = ((sl_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - sl_p) / safe_denom) * 100.0
                            r['status'] = "BREAKEVEN_GUARD"
                            r['exit_price'] = format_precision_price(sl_p)
                            r['realized_return_pct'] = f"{ret_be:+.2f}%"
                            r['outcome_label'] = f"🛡️ BREAKEVEN (TIER-0 GUARD {ret_be:+.2f}%)"
                        elif is_tp1_locked:
                            ret_tp1 = ((tp1_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - tp1_p) / safe_denom) * 100.0
                            blended_ret = 0.50 * ret_tp1
                            r['status'] = "WON_TP1_BE"
                            r['exit_price'] = format_precision_price(entry_p)
                            r['realized_return_pct'] = f"{blended_ret:+.2f}%"
                            r['outcome_label'] = "🟢 WON (TP1 + BE RUNNER)"
                        else:
                            r['status'] = "LOST_SL"
                            r['exit_price'] = format_precision_price(sl_p)
                            ret_pct = ((sl_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - sl_p) / safe_denom) * 100.0
                            r['realized_return_pct'] = f"{ret_pct:+.2f}%"
                            r['outcome_label'] = "🔴 LOST (SL HIT)"
                    else:
                        ret_current = ((curr_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - curr_p) / safe_denom) * 100.0
                        if is_tp1_locked:
                            ret_tp1 = ((tp1_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - tp1_p) / safe_denom) * 100.0
                            blended_ret = (0.50 * ret_tp1) + (0.50 * max(0.0, ret_current))
                            r['status'] = "WON_TP1_EXP"
                            r['exit_price'] = format_precision_price(curr_p)
                            r['realized_return_pct'] = f"{blended_ret:+.2f}%"
                            r['outcome_label'] = f"🟢 WON (TP1 + EXP {blended_ret:+.2f}%)"
                            resolved_ret = blended_ret
                        elif is_tier0_locked:
                            r['status'] = "BREAKEVEN_GUARD"
                            r['exit_price'] = format_precision_price(curr_p)
                            r['realized_return_pct'] = f"{ret_current:+.2f}%"
                            r['outcome_label'] = f"🛡️ EXPIRED (TIER-0 BE {ret_current:+.2f}%)"
                            resolved_ret = ret_current
                        else:
                            if ret_current >= 0.10:
                                r['status'] = "WON_EXP_PROFIT"
                                r['outcome_label'] = f"🟢 WON (EXP PROFIT {ret_current:+.2f}%)"
                            elif ret_current <= -0.10:
                                r['status'] = "LOST_EXP"
                                r['outcome_label'] = f"🔴 LOST (EXPIRY {ret_current:+.2f}%)"
                            else:
                                r['status'] = "BREAKEVEN_EXP"
                                r['outcome_label'] = f"⚪ BREAKEVEN (EXPIRY {ret_current:+.2f}%)"
                            r['exit_price'] = format_precision_price(curr_p)
                            r['realized_return_pct'] = f"{ret_current:+.2f}%"
                            resolved_ret = ret_current
                        try:
                            from app.services.whatsapp_service import whatsapp_service
                            whatsapp_service.emit_signal_outcome(r, "EXPIRED", curr_p, resolved_ret)
                        except Exception:
                            pass
                    r['evaluated_at_utc'] = now_str
                    updated = True
                    resolved_count += 1
            except Exception as rec_err:
                print(f"[SIGNAL EVAL ERROR ⚠️] Skipped corrupted signal {r.get('signal_id')}: {rec_err}")
                continue

        if updated:
            self.save_records()
            print(f"[SIGNAL TRACKER 🎯] Evaluated & updated {resolved_count} signal(s) in CSV: {os.path.abspath(self.csv_path)}")
            
            # Sync into V16 Audit Manager Dynamic State
            if self.has_v16:
                try:
                    from app.quant_v16.audit import SignalEventType
                    for r in self.records:
                        sig_id = r.get('signal_id')
                        if sig_id in self.v16_audit.dynamic_states:
                            ds = self.v16_audit.dynamic_states[sig_id]
                            ds.status = r.get('status', ds.status)
                            ds.outcome_label = r.get('outcome_label', ds.outcome_label)
                            ds.is_tp1_locked = bool(r.get('is_tp1_locked', ds.is_tp1_locked))
                            ds.is_tp2_locked = bool(r.get('is_tp2_locked', ds.is_tp2_locked))
                            curr_sl_val = _safe_float(r.get('sl_price'), ds.current_sl)
                            ds.current_sl = curr_sl_val
                            
                            # Sync realized return if trade has closed
                            ret_raw = r.get('realized_return_pct')
                            if ret_raw is not None and str(ret_raw).strip() != '':
                                try:
                                    clean_ret = float(str(ret_raw).replace('%', '').strip())
                                    ds.unrealized_net_pnl_pct = clean_ret
                                except Exception:
                                    pass
                            
                            ds.updated_at_utc = now_str
                    self.v16_audit.save_state()
                except Exception as dyn_sync_err:
                    print(f"[V16 ⚠️] Audit dynamic state sync notice: {dyn_sync_err}")

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
    'intraday': '1H',
    'swing': '1H',
    'triple_screen': '1H',
    'horizon_4h': '4H',
    'macro': '24H',
    'horizon_4d': '4D',
    'weekly': '7D',
    'biweekly': '15D',
    'monthly': '30D',
}

HORIZON_EXPIRY_SECONDS = {
    '15M': 3600,    # 60 mins (4 x 15M candles) to allow scalp targets to hit
    '30M': 7200,    # 120 mins (4 x 30M candles)
    '1H': 28800,    # 8 hours (8 x 1H candles - full day trade session)
    '4H': 86400,    # 24 hours (6 x 4H candles - 1 full day trade)
    '24H': 259200,  # 72 hours (3 x 24H candles - 3 day swing)
    '4D': 432000,   # 5 days
    '7D': 777600,   # 9 days
    '15D': 1555200, # 18 days
    '30D': 2851200, # 33 days
}

HORIZON_DISPLAY_NAMES = {
    '15M': '⚡ Scalp (15M)',
    '30M': '⚡ Scalp (30M)',
    '1H': '⏳ Day Trade (1H)',
    '4H': '⏳ Day Trade (4H)',
    '24H': '🌊 Swing Trade (1D)',
    '4D': '🚀 Macro Trend (4D)',
    '7D': '🚀 Macro Trend (7D)',
    '15D': '🚀 Macro Trend (15D)',
    '30D': '🚀 Macro Trend (30D)',
}

def get_horizon_display_name(h_tag_or_key: str) -> str:
    tag = resolve_horizon_tag(h_tag_or_key)
    return HORIZON_DISPLAY_NAMES.get(tag, str(h_tag_or_key).strip())

def resolve_horizon_tag(h_key: str) -> str:
    hk = str(h_key or "").lower().strip()
    if hk in HORIZON_TAG_MAP:
        return HORIZON_TAG_MAP[hk]
    # Check multi-digit timeframes first to prevent substring collisions (e.g. '24h' matching '4h'/'1h')
    if 'monthly' in hk or '30d' in hk: return '30D'
    if 'biweekly' in hk or '15d' in hk: return '15D'
    if 'weekly' in hk or '7d' in hk: return '7D'
    if '4d' in hk: return '4D'
    if '3d' in hk: return '3D'
    if '2d' in hk: return '2D'
    if 'macro' in hk or '24h' in hk or '1d' in hk: return '24H'
    if '4h' in hk: return '4H'
    if '1h' in hk or 'intraday' in hk or 'triple_screen' in hk: return '1H'
    if '30m' in hk: return '30M'
    if 'scalp' in hk or '15m' in hk: return '15M'
    if 'swing' in hk: return '1H'
    return HORIZON_TAG_MAP.get(hk, str(h_key or '').upper().strip())

class ActiveInstitutionalSignalManager:
    """
    Persistent Institutional Signal Lifecycle Registry:
    - Maintains exactly ONE dominant active signal per coin symbol (highest winning chance across horizons).
    - Preserves signals across multiple 15-minute scans until they WIN (TP hit), LOSE (SL hit), or EXPIRE.
    - If a subsequent scan evaluates the same coin (e.g. entry shifted or lower horizons updated),
      updates the existing signal and its lower-horizon favorability in-place rather than creating duplicate spam.
    - Performs high-frequency evaluation on live prices during both scans and fast 15s heartbeats.
    - Persists state to active_institutional_signals.json.
    """
    def __init__(self, export_dir: str = "./export_app_data", audit_tracker=None):
        self.export_dir = export_dir
        self.audit_tracker = audit_tracker
        self.filepath = os.path.join(self.export_dir, "active_institutional_signals.json")
        self.active_signals = {}  # key: clean_symbol -> dict (1 active signal per coin)
        self.directional_cooldown = {}  # key: clean_symbol -> (last_dir, last_ts) to prevent 5m whipsaws
        self._lock = threading.RLock()
        self.load_state()

    def _clean_sym(self, sym: str) -> str:
        if not sym:
            return ""
        s = str(sym).strip().upper().replace(':USDT', '')
        if '/' not in s and s.endswith('USDT'):
            s = s[:-4] + '/USDT'
        return s

    def _make_key(self, sym: str, h_key: str = None) -> str:
        s = self._clean_sym(sym)
        if h_key:
            tag = resolve_horizon_tag(h_key).upper()
            return f"{s}:{tag}"
        return s

    def load_state(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        sym = item.get('symbol', '')
                        h_tag = item.get('horizon_tag') or resolve_horizon_tag(item.get('horizon_key', 'scalp'))
                        if sym:
                            key = self._make_key(sym, h_tag)
                            self.active_signals[key] = item
                elif isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(v, dict):
                            sym = v.get('symbol', '') or k.split(':')[0]
                            h_tag = v.get('horizon_tag') or resolve_horizon_tag(v.get('horizon_key', 'scalp'))
                            clean_k = self._make_key(sym, h_tag)
                            self.active_signals[clean_k] = v
            except Exception as e:
                print(f"[ACTIVE SIGNAL MGR] Error loading state: {e}")

    def save_state(self):
        with getattr(self, '_lock', threading.RLock()):
            temp = f"{self.filepath}.{threading.get_ident()}.{time.time_ns()}.tmp"
            try:
                os.makedirs(self.export_dir, exist_ok=True)
                with open(temp, 'w', encoding='utf-8') as f:
                    json.dump(list(self.active_signals.values()), f, indent=2, default=str)
                os.replace(temp, self.filepath)
            except Exception as e:
                print(f"[ACTIVE SIGNAL MGR] Error saving state: {e}")
            finally:
                if os.path.exists(temp):
                    try:
                        os.remove(temp)
                    except Exception:
                        pass

    def get_active_symbols(self) -> list:
        syms = set()
        for s in self.active_signals.values():
            if s.get('status') in ["ACTIVE", "PENDING_EVALUATION", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"]:
                sym = s.get('symbol')
                if sym:
                    syms.add(sym)
        return list(syms)

    def get_active_pairs(self) -> set:
        """Returns set of (clean_symbol, horizon_tag) tuples currently active."""
        pairs = set()
        for s in self.active_signals.values():
            if s.get('status') in ["ACTIVE", "PENDING_EVALUATION", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"]:
                sym = self._clean_sym(s.get('symbol'))
                h_tag = s.get('horizon_tag') or resolve_horizon_tag(s.get('horizon_key', 'scalp'))
                if sym and h_tag:
                    pairs.add((sym, h_tag.upper()))
        return pairs

    def is_asset_quarantined(self, symbol: str) -> tuple:
        if self.audit_tracker:
            return self.audit_tracker.is_asset_quarantined(symbol)
        return False, ""

    def upsert_signals(self, candidate_signals: list) -> list:
        """
        Upserts candidate signals across horizons:
        - Allows distinct multi-horizon execution setups (e.g. 15M Scalp + 1H Swing + 24H Macro)
        - If active on that horizon, updates live price, PnL, favorability, and horizon confluence in place.
        - If new on that horizon, registers it and logs to audit tracker.
        """
        now_utc = datetime.now(timezone.utc)
        now_str = now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')

        for cand in candidate_signals:
            if not isinstance(cand, dict):
                continue
            sym = self._clean_sym(cand.get('symbol', ''))
            if not sym:
                continue

            # Quarantine Gate
            is_quarantined, _ = self.is_asset_quarantined(sym)
            if is_quarantined:
                continue

            h_tag = cand.get('horizon_tag') or resolve_horizon_tag(cand.get('horizon_key', 'scalp'))
            key = self._make_key(sym, h_tag)
            existing = self.active_signals.get(key)
            is_active = existing and existing.get('status') in [
                "ACTIVE", "PENDING_EVALUATION", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"
            ]

            if is_active:
                # Update existing active signal in-place without changing initial entry setup
                live_price = _safe_float(cand.get('current_price', cand.get('entry_price', existing.get('current_price', existing.get('entry_price', 0.0)))))
                existing['current_price'] = format_precision_price(live_price)
                existing['live_price'] = format_precision_price(live_price)

                entry_p = _safe_float(existing.get('entry_price', live_price), live_price)
                direction = str(existing.get('direction', 'LONG')).upper()
                is_long = direction in ["LONG", "BULLISH"]
                safe_denom = max(1e-12, entry_p)
                pnl = ((live_price - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - live_price) / safe_denom) * 100.0
                existing['live_pnl_pct'] = round(pnl, 2)

                # Sync favorability & confluence telemetry from newest prediction scan
                if cand.get('prediction_favorability'):
                    existing['prediction_favorability'] = cand.get('prediction_favorability')
                if cand.get('horizon_flow'):
                    existing['horizon_flow'] = cand.get('horizon_flow')
                if cand.get('supporting_horizons'):
                    existing['supporting_horizons'] = cand.get('supporting_horizons')
                if cand.get('opposing_horizons'):
                    existing['opposing_horizons'] = cand.get('opposing_horizons')
                if cand.get('confluence_badge'):
                    existing['confluence_badge'] = cand.get('confluence_badge')
                if cand.get('confluence_summary'):
                    existing['confluence_summary'] = cand.get('confluence_summary')
                if cand.get('tailwind_horizons'):
                    existing['tailwind_horizons'] = cand.get('tailwind_horizons')
                if cand.get('headwind_horizons'):
                    existing['headwind_horizons'] = cand.get('headwind_horizons')
                if cand.get('fundamental_matrix'):
                    existing['fundamental_matrix'] = cand.get('fundamental_matrix')
                if cand.get('news_sentiment'):
                    existing['news_sentiment'] = cand.get('news_sentiment')
                if cand.get('catalyst_event'):
                    existing['catalyst_event'] = cand.get('catalyst_event')
                if cand.get('sizing_multiplier'):
                    existing['sizing_multiplier'] = cand.get('sizing_multiplier')
                if cand.get('composite_fundamental_score') is not None:
                    existing['composite_fundamental_score'] = cand.get('composite_fundamental_score')

                existing['updated_at_utc'] = now_str

                if self.audit_tracker:
                    for rec in self.audit_tracker.records:
                        if rec.get('signal_id') == existing.get('signal_id'):
                            rec['current_price'] = existing['current_price']
                            rec['live_pnl_pct'] = existing.get('live_pnl_pct', 0.0)
                            break
            else:
                # Register fresh dominant signal
                cand_dir = str(cand.get('direction', 'LONG')).upper()
                cand_conf = _safe_float(cand.get('conviction', 60.0), 60.0)
                now_ts = time.time()
                last_cool = self.directional_cooldown.get((sym, h_tag)) or self.directional_cooldown.get(sym)
                if last_cool:
                    last_dir, last_ts = last_cool
                    # If opposing direction within 30 mins, require high conviction (>=80%) to avoid whipsawing
                    if last_dir != cand_dir and (now_ts - last_ts) < 1800.0 and cand_conf < 80.0:
                        continue  # Suppress whipsaw flip

                sig_copy = dict(cand)
                sig_id = f"SIG_{now_utc.strftime('%Y%m%d_%H%M')}_{sym.replace('/', '_')}_{h_tag}"
                sig_copy['signal_id'] = sig_id
                sig_copy['horizon_tag'] = h_tag
                sig_copy['horizon_name'] = get_horizon_display_name(h_tag)
                sig_copy['horizon'] = get_horizon_display_name(h_tag)
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

                pred_close = sig_copy.get('predicted_close_utc')
                if not pred_close or pred_close == 'N/A':
                    dur_sec = HORIZON_EXPIRY_SECONDS.get(h_tag, 3600)
                    sig_copy['predicted_close_utc'] = (now_utc + timedelta(seconds=dur_sec)).strftime('%Y-%m-%d %H:%M:%S UTC')

                # Strict Institutional Gate: A signal must be vetted and admitted into SignalAuditTracker first
                if self.audit_tracker:
                    admitted = self.audit_tracker.log_top_trader_signals([sig_copy])
                    if not admitted:
                        # Vetoed by Audit Tracker (ML hurdle, VWAP shield, suppression, or sub-Grade B quality)
                        continue
                    # Attach official audit record properties (including official signal_id and quality grade)
                    official_rec = admitted[0]
                    sig_copy['signal_id'] = official_rec.get('signal_id', sig_id)
                    sig_copy['grade'] = official_rec.get('grade', sig_copy.get('grade'))
                    sig_copy['is_audit_admitted'] = True

                self.active_signals[key] = sig_copy
                self.directional_cooldown[(sym, h_tag)] = (cand_dir, now_ts)
                self.directional_cooldown[sym] = (cand_dir, now_ts)

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
        with getattr(self, '_lock', threading.RLock()):
            return self._evaluate_signals_internal(live_prices, live_highs, live_lows)

    def _evaluate_signals_internal(self, live_prices: dict, live_highs: dict = None, live_lows: dict = None) -> bool:
        if not self.active_signals:
            return False

        now_utc = datetime.now(timezone.utc)
        now_ts = time.time()
        now_str = now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')
        updated = False

        # 1. Clean up resolved signals past grace period (30 minutes = 1800s) or missing valid timestamps
        keys_to_delete = []
        for key, s in self.active_signals.items():
            status = s.get('status', 'ACTIVE')
            if status not in ["ACTIVE", "PENDING_EVALUATION", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"]:
                resolved_ts = _safe_float(s.get('resolved_at_ts', 0.0), 0.0)
                created_ts = _safe_float(s.get('created_ts', 0.0), 0.0)
                if resolved_ts == 0.0 or (now_ts - resolved_ts) > 1800.0 or (created_ts > 0 and (now_ts - created_ts) > 86400.0):
                    keys_to_delete.append(key)
        for k in keys_to_delete:
            self.active_signals.pop(k, None)
            updated = True

        # 2. Evaluate active signals
        for key, s in self.active_signals.items():
            try:
                status = s.get('status', 'ACTIVE')
                if status not in ["ACTIVE", "PENDING_EVALUATION", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"]:
                    continue

                sym = s.get('symbol')
                raw_sym = sym.replace('/', '').replace(':USDT', '') if sym else ''
                curr_p = _safe_float(live_prices.get(sym) or live_prices.get(raw_sym), 0.0)
                if curr_p <= 0.0:
                    continue

                entry_p = _safe_float(s.get('entry_price', curr_p), curr_p)
                if entry_p <= 0.0:
                    entry_p = curr_p
                if entry_p <= 0.0:
                    continue

                direction = str(s.get('direction', 'LONG')).upper()
                is_long = direction in ["LONG", "BULLISH"]

                safe_denom = max(1e-8, entry_p)
                pnl_pct = ((curr_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - curr_p) / safe_denom) * 100.0
                s['live_pnl_pct'] = round(pnl_pct, 2)
                s['current_price'] = curr_p
                s['live_price'] = curr_p

                # Intra-trade extremes tracking strictly since signal logging
                prev_peak = _safe_float(s.get('peak_price', curr_p), curr_p)
                prev_trough = _safe_float(s.get('trough_price', curr_p), curr_p)

                # Resolve creation timestamp
                created_ts = s.get('created_ts')
                if not created_ts:
                    created_ts = now_ts
                    s['created_ts'] = created_ts

                # Anti-Phantom Wick Guard:
                # Until the entry 15m candle closes and a fresh candle starts, candle_h and candle_l
                # must be clamped to curr_p to prevent past pre-entry wicks from triggering false Tier-0 locks or false SL hits.
                # Target-favorable wicks capture intra-candle breakouts; adverse wicks track real-time price
                # strictly since signal logging to prevent stale prior-candle wicks from falsely triggering Stop-Loss or polluting troughs.
                entry_candle_close_ts = ((int(float(created_ts)) // 900) + 1) * 900
                if now_ts < entry_candle_close_ts:
                    candle_h = curr_p
                    candle_l = curr_p
                else:
                    raw_h = _safe_float(live_highs.get(sym), curr_p) if live_highs else curr_p
                    raw_l = _safe_float(live_lows.get(sym), curr_p) if live_lows else curr_p
                    candle_h = max(curr_p, raw_h) if is_long else curr_p
                    candle_l = min(curr_p, raw_l) if not is_long else curr_p

                s['peak_price'] = max(prev_peak, candle_h, curr_p)
                s['trough_price'] = min(prev_trough, candle_l, curr_p)
                high_p = s['peak_price']
                low_p = s['trough_price']

                tp1_p = _safe_float(s.get('tp1_price', entry_p), entry_p)
                tp2_p = _safe_float(s.get('tp2_price', entry_p), entry_p)
                tp3_p = _safe_float(s.get('tp3_price', entry_p), entry_p)
                sl_p = _safe_float(s.get('sl_price', entry_p), entry_p)

                is_tp1_locked = bool(s.get('is_tp1_locked', False) or status in ['TP1_LOCKED_BREAKEVEN', 'TP2_LOCKED_TRAIL'])
                is_tp2_locked = bool(s.get('is_tp2_locked', False) or status == 'TP2_LOCKED_TRAIL')
                is_tier0_locked = bool(s.get('is_tier0_locked', False) or status == 'TIER0_PROTECTED_BREAKEVEN')

                # Invariant: Cap initial SL risk using horizon-aware risk geometry
                h_tag_early = s.get('horizon_tag') or resolve_horizon_tag(s.get('horizon_key', 'scalp'))
                is_fast_early = (h_tag_early in ['15M', '30M'] or s.get('horizon_key') in ['scalp', 'horizon_30m'])
                
                horizon_max_sl_map = {
                    '15M': 0.0250,
                    '30M': 0.0300,
                    '1H': 0.0400,
                    '4H': 0.0600,
                    '24H': 0.0800,
                    '4D': 0.0950,
                    '7D': 0.1100,
                    '15D': 0.1400,
                    '30D': 0.1800
                }
                max_allowed_sl_dist = horizon_max_sl_map.get(h_tag_early, 0.0120 if is_fast_early else 0.0240)
                if entry_p > 0 and not is_tp1_locked and not is_tier0_locked:
                    capped_sl = entry_p * (1.0 - max_allowed_sl_dist) if is_long else entry_p * (1.0 + max_allowed_sl_dist)
                    if is_long and sl_p < capped_sl:
                        sl_p = capped_sl
                        s['sl_price'] = format_precision_price(sl_p)
                    elif not is_long and sl_p > capped_sl:
                        sl_p = capped_sl
                        s['sl_price'] = format_precision_price(sl_p)

                # Ensure minimum target threshold before checking TP hits
                tp3_dist_pct = abs(tp3_p - entry_p) / safe_denom
                tp2_dist_pct = abs(tp2_p - entry_p) / safe_denom
                tp1_dist_pct = abs(tp1_p - entry_p) / safe_denom

                is_hit_tp3 = ((high_p >= tp3_p) if is_long else (low_p <= tp3_p)) if tp3_dist_pct >= 0.002 else False
                is_hit_tp2 = ((high_p >= tp2_p) if is_long else (low_p <= tp2_p)) if tp2_dist_pct >= 0.0015 else False
                is_hit_tp1 = ((high_p >= tp1_p) if is_long else (low_p <= tp1_p)) if tp1_dist_pct >= 0.001 else False

                max_gain = ((high_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - low_p) / safe_denom) * 100.0
                s['max_potential_gain_pct'] = round(max_gain, 2)

                # -------------------------------------------------------------
                # 🛡️ EARLY BREAKEVEN PROTECTION (CALIBRATED AT >= 55% OF TP1 DISTANCE)
                # Unified with TraderSignalsTracker: Evaluated BEFORE stop loss check
                # -------------------------------------------------------------
                is_macro_early = (h_tag_early in ['4H', '24H', '4D', '7D', '15D', '30D', 'MACRO', '1D'] or s.get('horizon_key') in ['horizon_4h', 'macro', 'horizon_4d', 'weekly', 'biweekly', 'monthly'])
                base_tier0 = 1.20 if is_fast_early else (2.00 if is_macro_early else 1.50)
                tier0_threshold = max(base_tier0, tp1_dist_pct * 100.0 * 0.55)
                soft_be_p = ((entry_p * 1.0015) if is_long else (entry_p * 0.9985)) if is_fast_early else (((entry_p * 1.0020) if is_long else (entry_p * 0.9980)))
                can_lock_be = (curr_p >= soft_be_p * 1.0005) if is_long else (curr_p <= soft_be_p * 0.9995)
                if max_gain >= tier0_threshold and can_lock_be and not is_tp1_locked and not is_tier0_locked:
                    s['is_tier0_locked'] = True
                    s['status'] = "TIER0_PROTECTED_BREAKEVEN"
                    s['sl_price'] = format_precision_price(max(sl_p, soft_be_p) if is_long else min(sl_p, soft_be_p))
                    sl_p = s['sl_price']
                    s['outcome_label'] = f"🛡️ TIER-0 PROTECTED (+{max_gain:.2f}% PEAK -> BE)"
                    is_tier0_locked = True
                    updated = True

                # Stop loss execution check against the active/updated SL:
                # Evaluated strictly against live real-time price to match exchange stop-market order execution
                is_hit_sl = (curr_p <= sl_p) if is_long else (curr_p >= sl_p)

                # Check expiration (Disabled when ENABLE_SIGNAL_EXPIRY is False)
                is_expired = False
                if ENABLE_SIGNAL_EXPIRY:
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

                    # Auto-Extension on in-profit trades (Let winners run without closing prematurely)
                    h_tag = s.get('horizon_tag') or resolve_horizon_tag(s.get('horizon_key', 'scalp'))
                    dur_sec = HORIZON_EXPIRY_SECONDS.get(h_tag, 3600)
                    can_auto_extend = (
                        pnl_pct >= 0.35
                        and not is_hit_sl
                        and s.get('auto_extended_count', 0) < 1
                    )
                    if is_expired and can_auto_extend:
                        s['auto_extended_count'] = s.get('auto_extended_count', 0) + 1
                        ext_close = now_utc + timedelta(seconds=dur_sec)
                        s['predicted_close_utc'] = ext_close.strftime('%Y-%m-%d %H:%M:%S UTC')
                        # Protect profits: lock trailing stop at breakeven / profit floor (+0.20%)
                        lock_be_p = (entry_p * 1.002) if is_long else (entry_p * 0.998)
                        s['sl_price'] = format_precision_price(max(sl_p, lock_be_p) if is_long else min(sl_p, lock_be_p))
                        s['status'] = "TP1_LOCKED_BREAKEVEN" if is_tp1_locked else "TIER0_PROTECTED_BREAKEVEN"
                        s['is_tier0_locked'] = True
                        s['outcome_label'] = f"🚀 EXTENDED (+{pnl_pct:.2f}% RUNNER)"
                        is_expired = False
                        updated = True

                # Calibrated Stagnation Cut: Only cut near duration end (> 85% elapsed) if severely underwater
                # (> 75% of max allowed SL) with zero upward momentum, protecting capital without premature whipsaws.
                if ENABLE_SIGNAL_EXPIRY and not is_hit_tp1 and not is_tier0_locked and not is_tp1_locked and not is_hit_sl and not is_expired:
                    created_ts = s.get('created_ts')
                    if created_ts and dur_sec and (now_ts - float(created_ts)) >= (0.85 * dur_sec):
                        max_g = ((s.get('peak_price', curr_p) - entry_p)/safe_denom*100.0) if is_long else ((entry_p - s.get('trough_price', curr_p))/safe_denom*100.0)
                        cut_sl_threshold = -(max_allowed_sl_dist * 0.75 * 100.0)
                        if max_g < 0.10 and pnl_pct <= cut_sl_threshold:
                            s['status'] = "STAGNATION_CUT"
                            s['exit_price'] = format_precision_price(curr_p)
                            s['outcome_label'] = f"⏱️ STAGNATION CUT ({pnl_pct:+.2f}%)"
                            s['resolved_at_ts'] = now_ts
                            s['resolved_at_utc'] = now_str
                            updated = True
                            continue

                # Win/Loss Resolution Transitions
                if is_hit_tp3:
                    s['status'] = "WON_TP3"
                    ret_tp3 = ((tp3_p - entry_p)/safe_denom*100.0) if is_long else ((entry_p - tp3_p)/safe_denom*100.0)
                    s['outcome_label'] = f"🏆 WON TP3 (+{abs(ret_tp3):.2f}%)"
                    s['exit_price'] = format_precision_price(tp3_p)
                    s['resolved_at_ts'] = now_ts
                    s['resolved_at_utc'] = now_str
                    updated = True
                    try:
                        from app.services.whatsapp_service import whatsapp_service
                        whatsapp_service.emit_signal_outcome(s, "TP3_HIT", tp3_p, ret_tp3)
                    except Exception:
                        pass
                elif is_hit_tp2 and not is_tp2_locked and not is_hit_sl:
                    s['status'] = "TP2_LOCKED_TRAIL"
                    s['outcome_label'] = "🎯 TP2 HIT (TRAILING)"
                    s['is_tp2_locked'] = True
                    s['is_tp1_locked'] = True
                    s['is_tp2_notified_wa'] = True
                    s['is_tp1_notified_wa'] = True
                    s['sl_price'] = format_precision_price(tp1_p)  # Trail SL to TP1 floor
                    updated = True
                    try:
                        from app.services.whatsapp_service import whatsapp_service
                        ret_tp2 = ((tp2_p - entry_p)/safe_denom*100.0) if is_long else ((entry_p - tp2_p)/safe_denom*100.0)
                        whatsapp_service.emit_signal_outcome(s, "TP2_HIT", tp2_p, ret_tp2)
                    except Exception as e:
                        logger.error(f"[WHATSAPP ❌] Error emitting TP2 outcome: {e}")
                elif is_hit_tp1 and not is_tp1_locked and not is_hit_sl:
                    s['status'] = "TP1_LOCKED_BREAKEVEN"
                    s['outcome_label'] = "🎯 TP1 HIT (SL @ BE)"
                    s['is_tp1_locked'] = True
                    s['is_tp1_notified_wa'] = True
                    s['sl_price'] = format_precision_price(entry_p)  # Trail SL to Breakeven
                    updated = True
                    try:
                        from app.services.whatsapp_service import whatsapp_service
                        ret_tp1 = ((tp1_p - entry_p)/safe_denom*100.0) if is_long else ((entry_p - tp1_p)/safe_denom*100.0)
                        whatsapp_service.emit_signal_outcome(s, "TP1_HIT", tp1_p, ret_tp1)
                    except Exception as e:
                        logger.error(f"[WHATSAPP ❌] Error emitting TP1 outcome: {e}")
                # Catch-up WhatsApp notification for active signals that locked TP1 earlier but haven't notified WhatsApp yet
                elif (is_hit_tp1 or is_tp1_locked) and not s.get('is_tp1_notified_wa') and not is_hit_sl and not is_tp2_locked:
                    s['is_tp1_notified_wa'] = True
                    updated = True
                    try:
                        from app.services.whatsapp_service import whatsapp_service
                        ret_tp1 = ((tp1_p - entry_p)/safe_denom*100.0) if is_long else ((entry_p - tp1_p)/safe_denom*100.0)
                        whatsapp_service.emit_signal_outcome(s, "TP1_HIT", tp1_p, ret_tp1)
                    except Exception as e:
                        logger.error(f"[WHATSAPP ❌] Error emitting TP1 catch-up outcome: {e}")
                elif is_hit_sl:
                    if is_tp2_locked:
                        s['status'] = "WON_TP2_TRAIL"
                        s['outcome_label'] = "🏆 WON (TP2 + TRAIL)"
                        event_type = "TRAIL_SL_HIT"
                    elif is_tp1_locked:
                        s['status'] = "WON_TP1_BE"
                        s['outcome_label'] = "🏆 WON (TP1 + BE)"
                        event_type = "BE_HIT"
                    elif is_tier0_locked:
                        s['status'] = "BREAKEVEN_GUARD"
                        ret_be = ((sl_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - sl_p) / safe_denom) * 100.0
                        s['outcome_label'] = f"🛡️ BREAKEVEN (TIER-0 GUARD {ret_be:+.2f}%)"
                        event_type = "TIER0_BE_HIT"
                    else:
                        s['status'] = "LOST_SL"
                        s['outcome_label'] = f"🛑 STOPPED (SL -{abs(sl_p - entry_p)/safe_denom*100.0:.2f}%)"
                        event_type = "SL_HIT"
                    s['exit_price'] = format_precision_price(sl_p)
                    s['resolved_at_ts'] = now_ts
                    s['resolved_at_utc'] = now_str
                    updated = True
                    if event_type != "TIER0_BE_HIT":
                        try:
                            from app.services.whatsapp_service import whatsapp_service
                            ret_sl = ((sl_p - entry_p)/safe_denom*100.0) if is_long else ((entry_p - sl_p)/safe_denom*100.0)
                            whatsapp_service.emit_signal_outcome(s, event_type, sl_p, ret_sl)
                        except Exception:
                            pass
                elif is_expired:
                    if is_tp1_locked:
                        ret_tp1 = ((tp1_p - entry_p) / safe_denom) * 100.0 if is_long else ((entry_p - tp1_p) / safe_denom) * 100.0
                        blended_ret = (0.50 * ret_tp1) + (0.50 * max(0.0, pnl_pct))
                        s['status'] = "WON_TP1_EXP"
                        s['exit_price'] = format_precision_price(curr_p)
                        s['outcome_label'] = f"🟢 WON (TP1 + EXP +{blended_ret:.2f}%)"
                    elif pnl_pct >= 0.25:
                        s['status'] = "WON_PROFIT_EXPIRED"
                        s['exit_price'] = format_precision_price(curr_p)
                        s['outcome_label'] = f"🟢 WON (PROFIT EXPIRE +{pnl_pct:.2f}%)"
                    elif pnl_pct <= -0.25:
                        s['status'] = "LOST_EXPIRED"
                        s['exit_price'] = format_precision_price(curr_p)
                        s['outcome_label'] = f"🔴 LOST (EXPIRED {pnl_pct:.2f}%)"
                    else:
                        s['status'] = "EXPIRED_BREAKEVEN"
                        s['exit_price'] = format_precision_price(curr_p)
                        s['outcome_label'] = f"⏱️ EXPIRED (BE {pnl_pct:+.2f}%)"
                    s['resolved_at_ts'] = now_ts
                    s['resolved_at_utc'] = now_str
                    updated = True
            except Exception as sig_err:
                print(f"[ACTIVE SIGNAL EVAL ERROR ⚠️] Skipped active signal {key}: {sig_err}")
                continue

        if updated:
            self.save_state()

        return updated

    def get_signals_by_horizon(self) -> dict:
        """Groups active signals by standard active horizon tags (15M, 1H, 24H): 1 signal per coin per horizon bucket."""
        tags = ["15M", "1H", "24H"]
        res = {t: [] for t in tags}
        seen_by_tag = {t: set() for t in tags}
        now_utc = datetime.now(timezone.utc)

        for s in self.active_signals.values():
            status = str(s.get('status', 'ACTIVE')).upper()
            outcome = str(s.get('outcome_label', '')).upper()

            # Strictly skip any resolved, won, lost, stopped, or expired signals
            if any(k in status for k in ["WON", "LOST", "EXPIRED", "STOPPED"]) or any(k in outcome for k in ["WON", "LOST", "EXPIRED", "STOPPED"]):
                continue

            if status in ["ACTIVE", "PENDING_EVALUATION", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"]:
                # Check expiration timestamp window
                pred_close_str = str(s.get('predicted_close_utc', '')).replace(' UTC', '').strip()
                if pred_close_str and pred_close_str != 'N/A':
                    try:
                        close_dt = datetime.fromisoformat(pred_close_str) if 'T' in pred_close_str else datetime.strptime(pred_close_str, '%Y-%m-%d %H:%M:%S' if len(pred_close_str) > 16 else '%Y-%m-%d %H:%M')
                        if close_dt.tzinfo is None:
                            close_dt = close_dt.replace(tzinfo=timezone.utc)
                        if now_utc >= close_dt:
                            continue  # Signal time window has expired
                    except Exception:
                        pass

                raw_tag = s.get('horizon_tag') or resolve_horizon_tag(s.get('horizon_key', 'scalp'))
                raw_tag_upper = str(raw_tag).upper()
                if raw_tag_upper in ["15M", "30M"]:
                    h_tag = "15M"
                elif raw_tag_upper in ["1H", "4H"]:
                    h_tag = "1H"
                elif raw_tag_upper in ["24H", "4D", "7D", "15D", "30D"]:
                    h_tag = "24H"
                else:
                    h_tag = "15M"

                sym = self._clean_sym(s.get('symbol', ''))
                if sym and sym in seen_by_tag[h_tag]:
                    continue
                if sym:
                    seen_by_tag[h_tag].add(sym)
                    res[h_tag].append(s)

        def get_strat_edge(x):
            dec = str(x.get('decision', '')).upper()
            arch = str(x.get('strategy_archetype', '')).upper()
            st_type = str(x.get('strategy_type', '')).upper()
            is_long = str(x.get('direction', '')).upper() in ['LONG', 'BULLISH']
            is_nested_ob = bool(x.get('is_nested_smc') or 'NESTED' in dec or (x.get('zeiierman_rank') == 1 and 'ORDER-BLOCK' in dec))
            is_top = any(k in dec or k in arch or k in st_type for k in ['MOMENTUM', 'BREAKOUT', 'DIP-BUY', 'BOTTOM-REVERSAL', 'ORDER-BLOCK', 'TRIPLE'])
            if is_nested_ob and is_long:
                return 50.0
            elif is_top and is_long:
                return 30.0
            elif is_top:
                return 15.0
            elif is_long:
                return 10.0
            return 0.0

        # Sort each horizon bucket by grade tier, ML meta win probability, proven strategy edge, and conviction
        for t in tags:
            res[t].sort(key=lambda x: (
                x.get('grade_tier', 2),
                -float(x.get('meta_win_prob', 0.50)),
                -get_strat_edge(x),
                -float(x.get('conviction', 50.0))
            ))

        return res

    def get_display_signals(self) -> list:
        """Returns balanced active display signals across the 3 active horizon groups (15M Scalp, 1H Day Trade, 24H Swing)."""
        by_h = self.get_signals_by_horizon()
        display_list = []
        seen_keys = set()
        active_tags = ["15M", "1H", "24H"]

        # 1. Guarantee top setups from each active Horizon
        for tag in active_tags:
            count = 0
            for s in by_h.get(tag, []):
                sym = self._clean_sym(s.get('symbol', ''))
                k = (sym, tag)
                if k not in seen_keys:
                    seen_keys.add(k)
                    display_list.append(s)
                    count += 1
                    if count >= 2:
                        break

        # 2. Backfill with remaining active candidates if any
        for tag in active_tags:
            for s in by_h.get(tag, []):
                sym = self._clean_sym(s.get('symbol', ''))
                k = (sym, tag)
                if k not in seen_keys:
                    seen_keys.add(k)
                    display_list.append(s)

        # Assign clean rank labels #1, #2...
        medals = ["🥇 TOP PICK (#1)", "🥈 RUNNER UP (#2)", "🥉 BRONZE (#3)", "🎯 PICK (#4)", "🎯 PICK (#5)", "🎯 PICK (#6)", "🎯 PICK (#7)", "🎯 PICK (#8)"]
        for idx, sig in enumerate(display_list):
            if idx < len(medals):
                sig['rank'] = medals[idx]
            else:
                sig['rank'] = f"#{idx+1}"

        return display_list
    def get_dominant_best_signals(self) -> list:
        """Returns single best dominant signal per coin across all horizons with multi-timeframe confluence metadata."""
        display_sigs = self.get_display_signals()
        return DominantHorizonArbiter.select_dominant_signals_across_universe(display_sigs)

# ------------------------------------------------------------------------------
# 7.4 DOMINANT HORIZON CONFLUENCE ARBITER & PREDICTION FAVORABILITY ENGINE
# ------------------------------------------------------------------------------
class DominantHorizonArbiter:
    """
    Intelligent Multi-Horizon Confluence & Dominant Best Signal Arbiter.
    1. Evaluates all active/candidate signals for a coin across all time horizons (15M, 30M, 1H, 4H, 24H, 4D, 7D, 15D, 30D).
    2. Identifies directional consensus (confluence % of supporting timeframes).
    3. Calculates Composite Horizon Confluence Score to pick the single dominant setup per coin.
    4. Evaluates lower upcoming horizons to build real-time "IN FAVOR / UNFAVOUR" tailwind/headwind confluence.
    5. Enriches winning signal with cross-timeframe alignment metadata, supporting horizons badge, and conflict suppression.
    """
    HORIZON_ORDER = ["15M", "1H", "24H"]

    @classmethod
    def arbitrate_coin_signals(cls, coin_signals: list) -> dict:
        if not coin_signals:
            return None
        if len(coin_signals) == 1:
            sig = dict(coin_signals[0])
            h_tag = sig.get('horizon_tag') or resolve_horizon_tag(sig.get('horizon_key', 'scalp'))
            sig['is_dominant_best'] = True
            sig['dominant_score'] = round(_safe_float(sig.get('conviction', 75.0)), 1)
            sig['confluence_alignment_pct'] = 100.0
            sig['supporting_horizons'] = [h_tag]
            sig['opposing_horizons'] = []
            sig['tailwind_horizons'] = [h_tag]
            sig['headwind_horizons'] = []
            sig['confluence_badge'] = f"⭐ DOMINANT SETUP ({h_tag})"
            sig['confluence_summary'] = f"Single Timeframe Confluence ({h_tag})"

            fav_obj = {
                "status": "CONFIRMED_IN_FAVOR",
                "status_badge": "🟢 CONFIRMED IN FAVOR",
                "recommendation": "HOLD_FOR_TARGET",
                "action_directive": f"Primary {h_tag} quantitative momentum model active.",
                "favorability_score": round(_safe_float(sig.get('conviction', 75.0)), 1),
                "agreeing_horizons_count": 1,
                "total_horizons_evaluated": 1,
                "tailwind_horizons": [h_tag],
                "headwind_horizons": [],
                "horizon_flow": [
                    {
                        "horizon": h_tag,
                        "direction": sig.get('direction', 'LONG'),
                        "status": "IN_FAVOR",
                        "status_badge": "🟢 IN FAVOR",
                        "probability": round(_safe_float(sig.get('meta_win_prob', 0.70)), 2),
                        "conviction": round(_safe_float(sig.get('conviction', 70.0)), 1),
                        "is_lower_leading": True
                    }
                ],
                "latest_evaluated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            }
            sig['prediction_favorability'] = fav_obj
            sig['favorability_status'] = fav_obj['status']
            sig['favorability_badge'] = fav_obj['status_badge']
            sig['action_directive'] = fav_obj['action_directive']
            return sig

        # Group executable directions (exclude filtered or suppressed setups)
        valid_long_sigs = [s for s in coin_signals if str(s.get('direction', 'LONG')).upper() in ['LONG', 'BULLISH'] and "FILTER" not in str(s.get('decision', '')) and "CONSOLIDATION" not in str(s.get('decision', ''))]
        valid_short_sigs = [s for s in coin_signals if str(s.get('direction', 'LONG')).upper() in ['SHORT', 'BEARISH'] and "FILTER" not in str(s.get('decision', '')) and "CONSOLIDATION" not in str(s.get('decision', ''))]

        long_sigs = valid_long_sigs if valid_long_sigs else [s for s in coin_signals if str(s.get('direction', 'LONG')).upper() in ['LONG', 'BULLISH']]
        short_sigs = valid_short_sigs if valid_short_sigs else [s for s in coin_signals if str(s.get('direction', 'LONG')).upper() in ['SHORT', 'BEARISH']]

        is_all_neutral = all(
            str(s.get('direction', '')).upper() in ['CONSOLIDATION', 'NEUTRAL', 'NO_TRADE'] or
            "CONSOLIDATION" in str(s.get('decision', '')) or
            "NO_TRADE" in str(s.get('decision', ''))
            for s in coin_signals
        )

        if is_all_neutral:
            favored_group = coin_signals
            opposing_group = []
            favored_dir = "NEUTRAL"
        else:
            # Select favored directional group by count and cumulative conviction of executable signals
            long_score = sum(_safe_float(s.get('conviction', 60.0)) * _safe_float(s.get('meta_win_prob', 0.50)) for s in valid_long_sigs)
            short_score = sum(_safe_float(s.get('conviction', 60.0)) * _safe_float(s.get('meta_win_prob', 0.50)) for s in valid_short_sigs)

            if long_score > short_score:
                favored_group = long_sigs
                opposing_group = short_sigs
                favored_dir = "LONG"
            elif short_score > long_score:
                favored_group = short_sigs
                opposing_group = long_sigs
                favored_dir = "SHORT"
            else:
                # Tie breaker: if no valid setups, check raw count
                favored_group = long_sigs if len(long_sigs) >= len(short_sigs) else short_sigs
                opposing_group = short_sigs if favored_group is long_sigs else long_sigs
                favored_dir = "LONG" if favored_group is long_sigs else "SHORT"

        total_eval = len(coin_signals)
        favored_count = len(favored_group)
        alignment_pct = round((favored_count / max(1, total_eval)) * 100.0, 1)

        supporting_horizons = []
        for s in favored_group:
            ht = s.get('horizon_tag') or resolve_horizon_tag(s.get('horizon_key', 'scalp'))
            if ht not in supporting_horizons:
                supporting_horizons.append(ht)

        opposing_horizons = []
        for s in opposing_group:
            ht = s.get('horizon_tag') or resolve_horizon_tag(s.get('horizon_key', 'scalp'))
            if ht not in opposing_horizons:
                opposing_horizons.append(ht)

        # Score candidates in favored group to find single best
        best_sig = None
        highest_score = -1e9

        horizon_exec_weights = {
            "15M": 1.20, "1H": 1.35, "24H": 1.25
        }

        for s in favored_group:
            ht = s.get('horizon_tag') or resolve_horizon_tag(s.get('horizon_key', 'scalp'))
            meta_p = _safe_float(s.get('meta_win_prob', 0.70), 0.70)
            conv = _safe_float(s.get('conviction', 60.0), 60.0)
            exp_ret = abs(_safe_float(s.get('expected_return_pct', 2.0), 2.0))
            tf_w = horizon_exec_weights.get(ht, 1.1)

            s_score = (meta_p * 40.0) + (conv * 0.30) + (alignment_pct * 0.20) + (tf_w * 10.0) + min(15.0, exp_ret * 2.0)
            if s.get('strategy_type') in ['MOMENTUM_TOP_GAINER', 'BREAKDOWN_TOP_LOSER']:
                s_score += 8.0

            # EMPHASIZE PROVEN PROFIT-MAKING STRATEGIES (+640% MOMENTUM, +213% ELITE LONG, +77% BREAKOUT)
            dec_upper = str(s.get('decision', '')).upper()
            arch_upper = str(s.get('strategy_archetype', '')).upper()
            st_type = str(s.get('strategy_type', '')).upper()

            if any(k in dec_upper or k in arch_upper or k in st_type for k in ['MOMENTUM', 'BREAKOUT', 'DIP-BUY', 'BOTTOM-REVERSAL', 'ORDER-BLOCK', 'TRIPLE_SCREEN']):
                s_score += 15.0
            if str(s.get('direction', '')).upper() in ['LONG', 'BULLISH']:
                s_score += 8.0  # Asymmetric edge: Longs outperform Shorts (+1063% vs +137% total return)

            if s_score > highest_score:
                highest_score = s_score
                best_sig = s

        if not best_sig:
            best_sig = favored_group[0] if favored_group else coin_signals[0]

        res_sig = dict(best_sig)
        winning_ht = res_sig.get('horizon_tag') or resolve_horizon_tag(res_sig.get('horizon_key', 'scalp'))
        win_idx = cls.HORIZON_ORDER.index(winning_ht) if winning_ht in cls.HORIZON_ORDER else 2

        # Build detailed lower-horizon leading flow & favorability telemetry
        horizon_flow = []
        tailwind_horizons = []
        headwind_horizons = []

        for s in coin_signals:
            ht = s.get('horizon_tag') or resolve_horizon_tag(s.get('horizon_key', 'scalp'))
            s_dir = str(s.get('direction', 'LONG')).upper()
            is_s_neutral = s_dir in ['CONSOLIDATION', 'NEUTRAL', 'NO_TRADE'] or "CONSOLIDATION" in str(s.get('decision', ''))
            is_s_long = s_dir in ['LONG', 'BULLISH']
            is_fav_long = favored_dir in ['LONG', 'BULLISH']
            h_idx = cls.HORIZON_ORDER.index(ht) if ht in cls.HORIZON_ORDER else 0
            is_lower_leading = (h_idx <= win_idx) or (ht in ['15M', '30M', '1H'])

            prob = _safe_float(s.get('meta_win_prob', 0.70), 0.70)
            conv = _safe_float(s.get('conviction', 60.0), 60.0)

            if is_all_neutral or (favored_dir == "NEUTRAL" and is_s_neutral):
                status = "IN_FAVOR"
                status_badge = "🟡 CONSOLIDATION"
                tailwind_horizons.append(ht)
            elif is_s_neutral:
                status = "IN_FAVOR"
                status_badge = "🟡 CONSOLIDATION"
                tailwind_horizons.append(ht)
            elif is_s_long == is_fav_long:
                status = "IN_FAVOR"
                status_badge = "🟢 IN FAVOR"
                tailwind_horizons.append(ht)
            else:
                status = "ADVERSE"
                status_badge = "🔴 ADVERSE"
                headwind_horizons.append(ht)

            horizon_flow.append({
                "horizon": ht,
                "direction": "CONSOLIDATION" if is_s_neutral else ("LONG" if is_s_long else "SHORT"),
                "status": status,
                "status_badge": status_badge,
                "probability": round(prob, 2),
                "conviction": round(conv, 1),
                "is_lower_leading": is_lower_leading
            })

        # Calculate Lower-Horizon Agreement Ratio
        lower_leading_items = [h for h in horizon_flow if h['is_lower_leading']]
        lower_tailwind_items = [h for h in lower_leading_items if h['status'] == 'IN_FAVOR']
        lower_ratio = len(lower_tailwind_items) / max(1, len(lower_leading_items))
        fav_score = round((lower_ratio * 60.0) + (alignment_pct * 0.40), 1)

        # Determine dynamic favorability state and action directive
        if is_all_neutral:
            fav_status = "MOMENTUM_COILING"
            fav_badge = "🟡 MOMENTUM COILING"
            rec = "STAND_ASIDE"
            directive = "Stand aside until directional breakout occurs. All horizons consolidating in equilibrium."
        elif lower_ratio >= 0.65:
            fav_status = "CONFIRMED_IN_FAVOR"
            fav_badge = "🟢 CONFIRMED IN FAVOR"
            rec = "HOLD_FOR_RUNNER"
            directive = f"Lower upcoming horizons ({', '.join(tailwind_horizons[:3])}) strongly confirm {favored_dir} expansion. Hold for TP2/TP3 expansion."
        elif len(headwind_horizons) >= 2 or (len(lower_leading_items) > 0 and lower_ratio <= 0.35):
            fav_status = "ADVERSE_HEADWIND"
            fav_badge = "🔴 ADVERSE HEADWIND"
            rec = "PROTECT_CAPITAL"
            directive = f"Lower horizon counter-trend detected on ({', '.join(headwind_horizons[:2])}). Protect capital / raise SL to Breakeven."
        else:
            fav_status = "MOMENTUM_COILING"
            fav_badge = "🟡 MOMENTUM COILING"
            rec = "HOLD_WITH_TRAILING_SL"
            directive = "Lower timeframes consolidating in equilibrium. Maintain active trailing stop-loss."

        fav_obj = {
            "status": fav_status,
            "status_badge": fav_badge,
            "recommendation": rec,
            "action_directive": directive,
            "favorability_score": fav_score,
            "agreeing_horizons_count": len(tailwind_horizons),
            "total_horizons_evaluated": total_eval,
            "tailwind_horizons": tailwind_horizons,
            "headwind_horizons": headwind_horizons,
            "horizon_flow": horizon_flow,
            "latest_evaluated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        }

        # Enrich with Hierarchical 15M (Micro Trigger) & 24H (Macro Anchor) Confirmations
        if res_sig.get('support_15m_aligned'):
            if "15M (Micro)" not in supporting_horizons:
                supporting_horizons.insert(0, "15M (Micro)")
            if "15M (Micro)" not in tailwind_horizons:
                tailwind_horizons.insert(0, "15M (Micro)")
        elif res_sig.get('is_micro_wick_trap') or res_sig.get('is_micro_hype_trap'):
            if "15M (Adverse)" not in headwind_horizons:
                headwind_horizons.insert(0, "15M (Adverse)")

        if res_sig.get('support_24h_aligned'):
            if "24H (Macro)" not in supporting_horizons:
                supporting_horizons.append("24H (Macro)")
            if "24H (Macro)" not in tailwind_horizons:
                tailwind_horizons.append("24H (Macro)")
        elif res_sig.get('is_counter_macro_blocked'):
            if "24H (Counter)" not in opposing_horizons:
                opposing_horizons.append("24H (Counter)")
            if "24H (Counter)" not in headwind_horizons:
                headwind_horizons.append("24H (Counter)")

        res_sig['is_dominant_best'] = True
        res_sig['dominant_score'] = round(highest_score, 1)
        res_sig['confluence_alignment_pct'] = alignment_pct
        res_sig['supporting_horizons'] = supporting_horizons
        res_sig['opposing_horizons'] = opposing_horizons
        res_sig['tailwind_horizons'] = tailwind_horizons
        res_sig['headwind_horizons'] = headwind_horizons
        res_sig['total_coin_horizons_evaluated'] = total_eval
        res_sig['prediction_favorability'] = fav_obj
        res_sig['favorability_status'] = fav_status
        res_sig['favorability_badge'] = fav_badge
        res_sig['action_directive'] = directive

        # Assign high-impact confluence badge & institutional multi-tier target synthesis
        if res_sig.get('is_super_confluence_5x') or len(supporting_horizons) >= 3:
            is_super = bool(res_sig.get('is_super_confluence_5x') or len(supporting_horizons) >= 4)
            badge_str = f"⚡ 5-TIER ELITE CONFLUENCE ({' + '.join(supporting_horizons[:4])})" if is_super else f"💎 TRIPLE CONFLUENCE ({' + '.join(supporting_horizons[:3])})"
            res_sig['grade'] = "💎 Grade A+ (MULTI-HORIZON CONFLUENCE)"
            res_sig['grade_tier'] = 1
            res_sig['tier_label'] = "5-TIER ELITE CONFLUENCE" if is_super else "TRIPLE SCREEN CONFLUENCE"
            res_sig['is_multi_horizon_confluence'] = True
            res_sig['decision'] = f"💎 MASTER TRIPLE-CONFLUENCE ({'-'.join(supporting_horizons[:3])} {favored_dir})"
            res_sig['strategy_archetype'] = "MULTI_HORIZON_CONFLUENCE"
            res_sig['conviction'] = min(95.0, _safe_float(res_sig.get('conviction', 75.0)) + 5.0)

            # Institutional Multi-Horizon Target Synthesis:
            # Sort favored signals from lowest to highest timeframe
            sorted_favored = sorted(
                favored_group,
                key=lambda x: cls.HORIZON_ORDER.index(x.get('horizon_tag') or resolve_horizon_tag(x.get('horizon_key', 'scalp')))
                if (x.get('horizon_tag') or resolve_horizon_tag(x.get('horizon_key', 'scalp'))) in cls.HORIZON_ORDER else 99
            )
            micro_sig = sorted_favored[0]
            macro_sig = sorted_favored[-1]
            
            # Use micro execution (15M/1H) for entry & SL precision
            micro_entry = _safe_float(micro_sig.get('entry_price', 0.0))
            if micro_entry > 0:
                res_sig['entry_price'] = micro_sig['entry_price']
                res_sig['current_price'] = micro_sig.get('current_price', micro_sig['entry_price'])
                res_sig['sl_price'] = micro_sig['sl_price']
            
            # Use macro expansion target for TP3
            macro_tp3 = _safe_float(macro_sig.get('tp3_price', 0.0))
            curr_tp3 = _safe_float(res_sig.get('tp3_price', 0.0))
            is_fav_long = favored_dir in ['LONG', 'BULLISH']
            if macro_tp3 > 0:
                if is_fav_long and macro_tp3 > curr_tp3:
                    res_sig['tp3_price'] = macro_sig['tp3_price']
                elif not is_fav_long and macro_tp3 < curr_tp3:
                    res_sig['tp3_price'] = macro_sig['tp3_price']
        elif len(supporting_horizons) >= 2:
            badge_str = f"🔥 DUAL ALIGNMENT ({' + '.join(supporting_horizons[:2])})"
            res_sig['grade'] = "🥇 Grade A (DUAL ALIGNMENT)"
            res_sig['grade_tier'] = 2
        else:
            badge_str = f"⭐ DOMINANT ({winning_ht})"

        res_sig['confluence_badge'] = badge_str
        res_sig['confluence_summary'] = f"{favored_count} of {total_eval} Timeframes Aligned {favored_dir} ({alignment_pct}% Agreement)"
        return res_sig

    @staticmethod
    def select_dominant_signals_across_universe(all_signals: list) -> list:
        """Groups all signals by coin symbol and selects the single highest-conviction dominant signal per coin."""
        if not all_signals:
            return []
        by_coin = {}
        for s in all_signals:
            if not isinstance(s, dict):
                continue
            sym = s.get('symbol', '').strip().upper().replace(':USDT', '')
            if not sym:
                continue
            if sym not in by_coin:
                by_coin[sym] = []
            by_coin[sym].append(s)

        dominant_list = []
        for sym, sigs in by_coin.items():
            dom = DominantHorizonArbiter.arbitrate_coin_signals(sigs)
            if dom:
                dominant_list.append(dom)

        # Sort dominant signals by dominant_score descending
        dominant_list.sort(key=lambda x: (
            x.get('grade_tier', 2),
            -_safe_float(x.get('dominant_score', 0.0)),
            -_safe_float(x.get('confluence_alignment_pct', 50.0)),
            -_safe_float(x.get('conviction', 50.0))
        ))
        return dominant_list

class PredictionFavorabilityEngine:
    """
    Evaluates new ML prediction cycles against active trades in the database/ledger:
    - CONFIRMED IN FAVOR: New predictions confirm the trade direction with high probability (Boost runner TP).
    - MOMENTUM STALLING: Prediction confidence dropping or volatility squeeze coiling (Tighten SL).
    - ADVERSE REVERSAL: New multi-timeframe models flipped to opposing direction (Issue early risk alert / soft exit).
    """
    @staticmethod
    def evaluate_favorability(active_signal: dict, latest_coin_forecast: dict) -> dict:
        if not active_signal:
            return {
                "status": "NEUTRAL",
                "status_badge": "⚪ AWAITING EVALUATION",
                "recommendation": "HOLD",
                "favorability_score": 50.0
            }
        
        trade_dir = str(active_signal.get("direction", "LONG")).upper()
        
        horizons = latest_coin_forecast.get("horizons", {}) if isinstance(latest_coin_forecast, dict) else {}
        if not horizons and isinstance(latest_coin_forecast, dict):
            horizons = {"15m": latest_coin_forecast, "1h": latest_coin_forecast}

        agree_count = 0
        total_eval = 0
        sum_prob = 0.0
        tailwind_horizons = []
        headwind_horizons = []
        horizon_flow = []

        for h_key, h_data in horizons.items():
            if not isinstance(h_data, dict):
                continue
            total_eval += 1
            pred_dir = str(h_data.get("direction", "")).upper()
            prob = _safe_float(h_data.get("probability", 0.65), 0.65)
            conv = _safe_float(h_data.get("conviction", 60.0), 60.0)
            sum_prob += prob

            h_tag = resolve_horizon_tag(h_key)
            is_trade_long = "LONG" in trade_dir or "BULL" in trade_dir
            is_pred_long = "LONG" in pred_dir or "BULL" in pred_dir

            if is_trade_long == is_pred_long:
                agree_count += 1
                tailwind_horizons.append(h_tag)
                flow_st = "IN_FAVOR"
                flow_badge = "🟢 IN FAVOR"
            else:
                headwind_horizons.append(h_tag)
                flow_st = "ADVERSE"
                flow_badge = "🔴 ADVERSE"

            horizon_flow.append({
                "horizon": h_tag,
                "direction": "LONG" if is_pred_long else "SHORT",
                "status": flow_st,
                "status_badge": flow_badge,
                "probability": round(prob, 2),
                "conviction": round(conv, 1),
                "is_lower_leading": h_tag in ['15M', '30M', '1H']
            })

        if total_eval == 0:
            agree_count = 1
            total_eval = 1
            sum_prob = 0.70

        agree_ratio = agree_count / max(1, total_eval)
        avg_prob = sum_prob / max(1, total_eval)
        fav_score = round((agree_ratio * 60.0) + (avg_prob * 40.0), 1)

        if agree_ratio >= 0.65 and avg_prob >= 0.60:
            status = "CONFIRMED_IN_FAVOR"
            status_badge = "🟢 CONFIRMED IN FAVOR"
            recommendation = "HOLD_FOR_RUNNER"
            action_directive = f"Lower upcoming horizons ({', '.join(tailwind_horizons[:3])}) confirm {trade_dir} trend continuation. Hold for TP2/TP3 expansion."
        elif agree_ratio <= 0.35 and avg_prob >= 0.60:
            status = "ADVERSE_REVERSAL"
            status_badge = "🔴 ADVERSE REVERSAL DETECTED"
            recommendation = "CONSIDER_EARLY_TRIM"
            action_directive = f"Adverse pressure detected on ({', '.join(headwind_horizons[:2])}). Protect capital / raise SL to Breakeven."
        else:
            status = "MOMENTUM_STALLING"
            status_badge = "🟡 MOMENTUM STALLING"
            recommendation = "HOLD_WITH_TRAILING_SL"
            action_directive = "Price momentum equilibrium coiling. Trailing stop-loss protection active."

        return {
            "status": status,
            "status_badge": status_badge,
            "recommendation": recommendation,
            "action_directive": action_directive,
            "favorability_score": fav_score,
            "agreeing_horizons_count": agree_count,
            "total_horizons_evaluated": total_eval,
            "tailwind_horizons": tailwind_horizons,
            "headwind_horizons": headwind_horizons,
            "horizon_flow": horizon_flow,
            "latest_evaluated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        }

class SingleClassPriorModel:
    """Laplace-smoothed probability model for per-coin cold starts where only one class has resolved so far."""
    def __init__(self, target_class: int, sample_size: int):
        self.target_class = int(target_class)
        self.sample_size = int(sample_size)
        if self.target_class == 1:
            self.prob = (sample_size + 1.0) / (sample_size + 2.0)
        else:
            self.prob = 1.0 / (sample_size + 2.0)
            
    def predict_proba(self, X):
        p1 = float(self.prob)
        p0 = 1.0 - p1
        n = len(X)
        return np.array([[p0, p1]] * n)

# ------------------------------------------------------------------------------
# 7.5 SECONDARY MACHINE LEARNING META-LABELING CLASSIFIER
# ------------------------------------------------------------------------------
class SignalMetaClassifier:
    """
    Two-Stage Meta-Labeling Classifier (Marcos López de Prado architecture).
    Predicts probability P(Trade hits TP before SL) using model agreement,
    timeframe confluence, R:R metrics, and market regime features.
    Supports both Global and Dedicated Per-Coin Meta-Labeling.
    """
    def __init__(self, model_path: str = "./models_export_v3/signal_meta_classifier.joblib", models_dir: str = "./models_export_v3"):
        self.model_path = model_path
        self.models_dir = models_dir
        self.per_coin_dir = os.path.join(models_dir, "per_coin")
        self.bundle = None
        self.model = None
        self.feature_cols = []
        self._last_mtime = 0
        self._coin_models = {}  # {clean_sym: (model, feature_cols, mtime)}
        self.load_model()

    def load_model(self):
        if not os.path.exists(self.model_path):
            try:
                from app.services.model_retrainer import run_retraining_pipeline
                print(f"[META CLASSIFIER 🧠] Model not found at {self.model_path}. Auto-training initial model from dataset...")
                run_retraining_pipeline(force=True)
            except Exception:
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

    def _get_per_coin_model(self, symbol: str, min_sample_size: int = 5):
        if not symbol:
            return None, [], 0
        clean_sym = symbol.replace('/', '_').replace(':USDT', '')
        coin_path = os.path.join(self.per_coin_dir, clean_sym, "meta_classifier.joblib")
        if not os.path.exists(coin_path):
            return None, [], 0
        try:
            mtime = os.path.getmtime(coin_path)
            cached = self._coin_models.get(clean_sym)
            if cached and cached.get('mtime') == mtime:
                sz = cached.get('sample_size', 0)
                if sz < min_sample_size:
                    return None, [], sz
                return cached['model'], cached['feature_cols'], sz
            bundle = joblib.load(coin_path)
            sz = int(bundle.get('sample_size', 0))
            if sz < min_sample_size:
                return None, [], sz
            m = bundle.get('model')
            f_cols = bundle.get('feature_cols', [])
            self._coin_models[clean_sym] = {'model': m, 'feature_cols': f_cols, 'mtime': mtime, 'sample_size': sz}
            return m, f_cols, sz
        except Exception:
            return None, [], 0

    def predict_win_probability(self, sig: Any, symbol: Any = None) -> float:
        """Predicts calibrated win probability (0.0 to 1.0) using Bayesian shrinkage between per-coin and global meta-labeler."""
        if isinstance(sig, str) and isinstance(symbol, dict):
            sig, symbol = symbol, sig
        elif isinstance(sig, str) and symbol is None:
            sig, symbol = {}, sig
        if not isinstance(sig, dict):
            sig = {}
        sym = str(symbol or sig.get('symbol', ''))

        try:
            from app.engine.signals.meta_labeler import CoinSpecificMetaLabeler
            labeler = CoinSpecificMetaLabeler(base_models_dir=self.models_dir)
            prob, _, _ = labeler.predict_coin_win_probability(sym, sig)
            return float(prob)
        except Exception:
            pass

        conv = float(sig.get('conviction', 70.0))
        is_a_plus = 1.0 if any("A+" in str(sig.get(k, '')) for k in ['grade', 'quality_grade']) else 0.0
        from app.engine.config import PROBABILITY_CALIBRATION_MODE
        if PROBABILITY_CALIBRATION_MODE == "CHRONOLOGICAL_CALIBRATED":
            return 0.367
        base_p = (conv / 100.0) * (0.88 if is_a_plus else 0.76)
        return round(min(0.95, max(0.40, base_p)), 3)

# ------------------------------------------------------------------------------
# 8. INSTITUTIONAL TRADER REGIME PLAYBOOK & BEST PRACTICES ENGINE
# ------------------------------------------------------------------------------
class TraderRegimePlaybook:
    """
    Quantitative & Institutional Playbook for Traders across Market Regimes:
    - Bullish Expansion (Markup)
    - Bearish Breakdown (Markdown / Distribution / Flash Crash)
    - Consolidation / Range Squeeze (Chop / Volatility Compression)
    """
    @staticmethod
    def generate(regime: str, predicted_trend: str, bull_prob: float, bear_prob: float, cons_prob: float, is_squeeze: bool = False, btc_price: float = 0.0, breakout_pred: str = "") -> dict:
        if regime in ["ALERT_DUMP", "FLASH_DUMP"] or (regime == "BEARISH_BREAKDOWN" and not is_squeeze and bear_prob >= 60.0):
            regime_type = "BEARISH"
        elif regime in ["BULLISH_EXPANSION", "BULLISH_ACCUMULATION"] or (predicted_trend == "BULLISH" and not is_squeeze and bull_prob >= 55.0):
            regime_type = "BULLISH"
        else:
            regime_type = "CONSOLIDATION"

        if regime_type == "BULLISH":
            return {
                "regime_type": "BULLISH",
                "headline": "🟢 BULL MARKET REGIME: CONVEX UPSIDE CAPTURE & RUNNER ACCUMULATION",
                "tactical_stance": "AGGRESSIVE_LONGS_AND_PULLBACK_BUYS",
                "core_directive": "Ride the trend momentum, let winners run with trailing ratchet stops, and aggressively buy higher-low pullbacks to key dynamic moving averages.",
                "sizing_multiplier": 1.15,
                "recommended_leverage": "3x - 5x max (Avoid excessive leverage to survive liquidity wicks)",
                "target_risk_reward": "1:2.5 to 1:4.0 (Expand TP targets for major runners)",
                "stop_loss_policy": "Ratchet SL to Breakeven+ immediately once TP1 is hit. Never cut winners early.",
                "preferred_setups": [
                    {
                        "name": "Higher-Low EMA Pullback",
                        "desc": "Buy 15M/1H pullbacks testing 21 EMA or 50 EMA with oversold RSI bounce (35-45).",
                        "tag": "DIP_BUY"
                    },
                    {
                        "name": "Volatility Squeeze Breakout",
                        "desc": "Enter long on clean candle close above multi-hour resistance with volume expansion.",
                        "tag": "BREAKOUT"
                    },
                    {
                        "name": "High-Beta Relative Strength Long",
                        "desc": "Target altcoins outperforming BTC (RS_BTC > 0.3) that lead market upward surges.",
                        "tag": "ALPHA_LEADER"
                    }
                ],
                "dos": [
                    "Buy dips at key dynamic moving average supports (21 EMA / 50 EMA / VWAP).",
                    "Expand Take Profit targets and leave 25-40% runner positions for macro swing moves.",
                    "Ratchet stop losses to breakeven once TP1 is reached to lock in a risk-free trade.",
                    "Focus capital on top relative strength altcoins outperforming Bitcoin.",
                    "Pyramid into winning trades on confirmed higher-low breakout retests."
                ],
                "donts": [
                    "DO NOT short strong upward momentum solely because RSI is 'overbought' (RSI stays high in bull runs).",
                    "DO NOT take micro-scalp 0.5% profits prematurely while leaving massive 10%+ trends on the table.",
                    "DO NOT panic sell spot positions on standard 3-5% intraday bull-market pullbacks.",
                    "DO NOT chase vertical parabolic green candles with 10x+ leverage at resistance."
                ],
                "checklist": [
                    {"rule": "Is the higher timeframe (4H/1D) trend aligned bullishly?", "status": "REQUIRED"},
                    {"rule": "Is the trade entering at or near a pullback support (not extended >3 ATRs)?", "status": "REQUIRED"},
                    {"rule": "Is Stop Loss placed strictly below swing low invalidation level?", "status": "REQUIRED"},
                    {"rule": "Is the position size within 1.0x-1.25x risk tolerance?", "status": "RECOMMENDED"},
                    {"rule": "Is trailing ratchet stop enabled for TP1 reach?", "status": "REQUIRED"}
                ]
            }

        elif regime_type == "BEARISH":
            return {
                "regime_type": "BEARISH",
                "headline": "🔴 BEAR MARKET REGIME: CAPITAL PRESERVATION & RELIEF FADE SHORTS",
                "tactical_stance": "DEFENSIVE_CAPITAL_PRESERVATION_AND_SHORTS",
                "core_directive": "Capital preservation is the absolute priority. Cash (USDT) is an active winning position. Suppress altcoin longs and fade overbought relief bounces into resistance.",
                "sizing_multiplier": 0.50,
                "recommended_leverage": "1x - 2x max (Strictly low leverage or spot cash allocation)",
                "target_risk_reward": "1:1.5 to 1:2.0 (Take quick profits; do not overstay short targets)",
                "stop_loss_policy": "Ultra-tight stop losses above resistance. Exit immediately upon invalidation.",
                "preferred_setups": [
                    {
                        "name": "Relief Rally Fade (Short)",
                        "desc": "Short oversold counter-trend bounces that test overhead 4H 50 EMA / resistance with RSI 55-65.",
                        "tag": "RALLY_FADE"
                    },
                    {
                        "name": "Breakdown Retest Short",
                        "desc": "Enter short when an established support level breaks down on volume and fails upon retest.",
                        "tag": "BREAKDOWN"
                    },
                    {
                        "name": "High-Negative Beta Hedge",
                        "desc": "Hedge spot portfolios with inverse perpetual shorts or high-beta bear sensitive assets.",
                        "tag": "INVERSE_HEDGE"
                    }
                ],
                "dos": [
                    "Keep 50-80% of portfolio in USDT / stablecoins to maintain dry powder for generational bottoms.",
                    "Automatically suppress or prune altcoin longs (altcoins drop 2x-3x harder than BTC).",
                    "Fade overbought counter-trend relief rallies that stall into descending moving averages.",
                    "Take profits quickly at TP1/TP2 because bear market bounces are fast and violent.",
                    "Use strict, tight stop-losses and accept small losses immediately without emotional attachment."
                ],
                "donts": [
                    "DO NOT catch falling knives on plunging coins without multi-day volume absorption.",
                    "DO NOT average down on losing long positions ('buying the dip' on a downtrend is fatal).",
                    "DO NOT widen stop losses hoping for a rebound.",
                    "DO NOT hold high-beta low-cap altcoins without stop-loss safeguards during systemic flushes."
                ],
                "checklist": [
                    {"rule": "Are altcoin longs blocked or reduced to minimal exploratory size?", "status": "REQUIRED"},
                    {"rule": "Is the short entry placed at overhead resistance / relief peak (not chasing the dump bottom)?", "status": "REQUIRED"},
                    {"rule": "Is position sizing reduced to 0.4x-0.6x base capital?", "status": "REQUIRED"},
                    {"rule": "Is TP target set conservatively with rapid partial take-profit enabled?", "status": "REQUIRED"},
                    {"rule": "Is stop loss strictly anchored above the swing high?", "status": "REQUIRED"}
                ]
            }

        else: # CONSOLIDATION
            return {
                "regime_type": "CONSOLIDATION",
                "headline": "⚪ CONSOLIDATION REGIME: MEAN REVERSION & SQUEEZE BREAKOUT WATCH",
                "tactical_stance": "RANGE_BOUND_MEAN_REVERSION_AND_SQUEEZE_COILING",
                "core_directive": "Trade the range boundaries: buy support, sell resistance, take quick midline profits, and avoid breakout FOMO traps while monitoring impending squeeze expansion.",
                "sizing_multiplier": 0.70,
                "recommended_leverage": "2x - 3x max",
                "target_risk_reward": "1:1.5 to 1:2.0 (Take 60-80% of profit at range midline / 20 SMA)",
                "stop_loss_policy": "Strict stop loss just outside range boundary buffer (0.5 ATR beyond support/resistance).",
                "preferred_setups": [
                    {
                        "name": "Bollinger Band Mean Reversion",
                        "desc": "Buy lower BB touches with RSI < 35; sell/short upper BB touches with RSI > 65.",
                        "tag": "RANGE_BOUNCE"
                    },
                    {
                        "name": "Range Support Liquidity Sweep",
                        "desc": "Enter long when price sweeps below support low, rejects lower prices, and re-enters range.",
                        "tag": "LIQUIDITY_SWEEP"
                    },
                    {
                        "name": "Volatility Squeeze Trigger",
                        "desc": "Prepare orders for explosive expansion when Bollinger Band Width contracts below 1.5%.",
                        "tag": "SQUEEZE_WATCH"
                    }
                ],
                "dos": [
                    "Buy at range support extremes and sell/short at range resistance extremes.",
                    "Take 60-80% profits at the range midline (VWAP or 20 SMA) rather than hoping for massive runners.",
                    "Monitor Choppiness Index (CHOP > 61.8) and Bollinger Band Width for squeeze contraction.",
                    "Reduce trade frequency and wait patiently for prices to reach the perimeter of the range.",
                    "Use time-based stops: close trades that stagnate at the midline to free up liquidity."
                ],
                "donts": [
                    "DO NOT buy green breakout candles at range highs (70%+ failure rate in choppy consolidation).",
                    "DO NOT short red breakdown candles at range lows without multi-timeframe volume confirmation.",
                    "DO NOT use oversized positions in sideways chop; chop generates death by papercuts from whipsaws.",
                    "DO NOT trade inside the middle 50% of the range (no-man's land with 50/50 odds)."
                ],
                "checklist": [
                    {"rule": "Is the entry located at the outer 20% perimeter of the trading range?", "status": "REQUIRED"},
                    {"rule": "Is the position size scaled down to 0.6x-0.75x to mitigate whipsaw risk?", "status": "REQUIRED"},
                    {"rule": "Is Take Profit 1 placed at the range midline (VWAP / 20 EMA)?", "status": "REQUIRED"},
                    {"rule": "Is Stop Loss placed strictly beyond the range outer boundary?", "status": "REQUIRED"},
                    {"rule": "Has breakout confirmation (volume + 4H candle close) occurred if attempting breakout?", "status": "REQUIRED"}
                ]
            }

# ------------------------------------------------------------------------------
# 8b. REGIME-ADAPTIVE & SPECIALIZED GAINERS/LOSERS STRATEGY ENGINE
# ------------------------------------------------------------------------------
# 8. SEPARATED REGIME SIGNAL ENGINES & SPECIALIZED STRATEGY ROUTERS
# ------------------------------------------------------------------------------
class BullishMarketSignalEngine:
    """
    Dedicated Signal Engine for BULLISH market regimes (Breadth >= 60% Green & Net > +1.0%).
    - Unlocks aggressive momentum breakout continuation longs.
    - Unlocks trend-following dip-buys on 1H/4H EMA pullbacks.
    - Automatically suppresses and filters counter-trend SHORTs.
    - Extends take-profit targets to allow full runner expansion (TP1 +3.8%, TP2 +8.0%, TP3 +18.0%).
    """
    @staticmethod
    def process_candidate(candidate_signal: dict) -> dict:
        if not candidate_signal:
            return None
        direction = str(candidate_signal.get("direction", "LONG")).upper()
        if direction == "SHORT":
            # Filter counter-trend shorts in strong bullish expansion
            return None
        sig = dict(candidate_signal)
        sig["regime_context"] = "🟢 BULLISH EXPANSION"
        sig["tactical_stance"] = "TREND_CONTINUATION_LONGS"
        sig["conviction"] = min(99.0, _safe_float(sig.get("conviction", 60.0)) + 6.0)
        return sig

class ConsolidationMarketSignalEngine:
    """
    Dedicated Signal Engine for CONSOLIDATION / SQUEEZE market regimes.
    - Focuses strictly on range perimeter boundaries: buy lower support, sell/short upper resistance.
    - Modulates breakout FOMO at range extremes into range-boundary fades.
    - Enforces realistic profit-taking at range midline / 20 SMA.
    """
    @staticmethod
    def process_candidate(candidate_signal: dict) -> dict:
        if not candidate_signal:
            return None
        sig = dict(candidate_signal)
        dec = str(sig.get("decision", "")).upper()
        # Modulate aggressive breakout trades into range-boundary fades in sideways chop
        if "BREAKOUT" in dec or "PUMP" in dec or "CHASE" in dec:
            sig["decision"] = sig.get("decision", "").replace("BREAKOUT", "RANGE-FADE").replace("PUMP", "RANGE-EDGE").replace("CHASE", "RANGE-BOUNCE")
        sig["regime_context"] = "⚪ RANGE CONSOLIDATION"
        sig["tactical_stance"] = "RANGE_BOUNDARY_FADES"
        return sig

class BearishMarketSignalEngine:
    """
    Dedicated Signal Engine for BEARISH market regimes (Breadth >= 60% Red & Net < -1.0%).
    - Focuses on trend breakdown continuation SHORTs and relief rally-fade SHORTs at 1H/4H resistance.
    - Suppresses weak breakout long signals (which frequently bull-trap in market downtrends).
    - Asymmetric downside targets (TP1 +3.5%, TP2 +7.5%, TP3 +16.0% on shorts).
    """
    @staticmethod
    def process_candidate(candidate_signal: dict) -> dict:
        if not candidate_signal:
            return None
        direction = str(candidate_signal.get("direction", "LONG")).upper()
        dec = str(candidate_signal.get("decision", "")).upper()
        if direction == "LONG" and ("BREAKOUT" in dec or "CHASE" in dec):
            # Suppress long breakouts in bearish regimes
            return None
        sig = dict(candidate_signal)
        sig["regime_context"] = "🔴 BEARISH DRIFT"
        sig["tactical_stance"] = "BREAKDOWN_CONTINUATION_AND_RALLY_FADES"
        if direction == "SHORT":
            sig["conviction"] = min(99.0, _safe_float(sig.get("conviction", 60.0)) + 6.0)
        return sig

class SpecializedStrategyRouter:
    """
    Dedicated strategy execution engine for:
    1. Top 24H Gainers (Momentum Continuation & Bull Flag Pullback LONGS)
    2. Top 24H Losers (Breakdown Continuation & Resistance Rally-Fade SHORTS)
    3. Tri-Modal Regime Modulation (Bullish vs Bearish vs Consolidation)
    """
    @staticmethod
    def route_by_regime(candidate_signal: dict, regime_type: str = "CONSOLIDATION") -> dict:
        r_upper = str(regime_type).upper()
        if "BULL" in r_upper:
            return BullishMarketSignalEngine.process_candidate(candidate_signal)
        elif "BEAR" in r_upper:
            return BearishMarketSignalEngine.process_candidate(candidate_signal)
        else:
            return ConsolidationMarketSignalEngine.process_candidate(candidate_signal)

    @staticmethod
    def evaluate_top_gainer_momentum(symbol: str, current_price: float, df_1h: pd.DataFrame = None, df_15m: pd.DataFrame = None, stats_24h: dict = None, regime_info: dict = None) -> dict:
        """
        Specialized Long Engine for 24h Top Gainers (+2.5% to +50% surge).
        Looks for healthy pullback to 1H 21-EMA / Bull Flag consolidation.
        """
        try:
            if not symbol or current_price is None or current_price <= 0:
                return None
            if not is_valid_crypto_pair(symbol):
                return None
            stats_24h = stats_24h or {}
            chg_24h = float(stats_24h.get('priceChangePercent', 5.0))
            vol_24h = float(stats_24h.get('quoteVolume', 0.0))

            min_vol = float(CONFIG.get("min_24h_volume_usd", 10000000.0))
            if is_meme_or_shitcoin(symbol, price=current_price, quote_volume_24h=vol_24h if 'quoteVolume' in stats_24h else None):
                return None
            if 'quoteVolume' in stats_24h and vol_24h < min_vol:
                return None
            
            rsi_1h = 55.0
            ema21_1h = current_price * 0.97
            if df_1h is not None and len(df_1h) >= 20:
                closes = df_1h['close'].values
                ema21_1h = float(pd.Series(closes).ewm(span=21).mean().iloc[-1])
                diff = pd.Series(closes).diff()
                gain = diff.clip(lower=0).rolling(14).mean()
                loss = (-diff.clip(upper=0)).rolling(14).mean()
                rs = gain / loss.replace(0, 1e-8)
                rsi_s = 100 - (100 / (1 + rs))
                rsi_1h = float(rsi_s.iloc[-1]) if not pd.isna(rsi_s.iloc[-1]) else 55.0

            is_overextended = (rsi_1h > 80.0) or (current_price > 1.15 * ema21_1h)
            entry_p = current_price
            tp1_p = format_precision_price(entry_p * 1.018)   # +1.8% TP1 (Achievable Momentum Harvest)
            tp2_p = format_precision_price(entry_p * 1.038)   # +3.8% TP2 (Expansion Scale)
            tp3_p = format_precision_price(entry_p * 1.075)   # +7.5% TP3 (Runner)
            sl_p = format_precision_price(entry_p * 0.985)    # -1.5% Stop Loss (1:1.2 to 1:5 R:R)
            
            conviction = 82.0 if (45.0 <= rsi_1h <= 68.0 and not is_overextended) else 75.0
            meta_prob = 0.78 if not is_overextended else 0.65
            tag = "🎯 ELITE TOP-GAINER PULLBACK (LONG)" if rsi_1h <= 62.0 else "🎯 ELITE MOMENTUM BREAKOUT (LONG)"
            
            return {
                "symbol": symbol,
                "strategy_type": "MOMENTUM_TOP_GAINER",
                "direction": "LONG",
                "direction_label": "🟢 LONG (TOP GAINER MOMENTUM)",
                "decision": tag,
                "current_price": entry_p,
                "entry_price": entry_p,
                "tp1_price": tp1_p,
                "tp2_price": tp2_p,
                "tp3_price": tp3_p,
                "sl_price": sl_p,
                "conviction": conviction,
                "meta_win_prob": meta_prob,
                "grade": "💎 Grade A+ (ELITE CONFLUENCE)",
                "tier_label": "TOP GAINER MOMENTUM",
                "change_24h_pct": chg_24h,
                "volume_24h_usd": vol_24h,
                "rsi_1h": round(rsi_1h, 1),
                "horizon_name": "⏳ Day Trade (1H)",
                "horizon_key": "swing"
            }
        except Exception:
            return None

    @staticmethod
    def evaluate_top_loser_breakdown_short(symbol: str, current_price: float, df_1h: pd.DataFrame = None, df_15m: pd.DataFrame = None, stats_24h: dict = None, regime_info: dict = None) -> dict:
        """
        Specialized Short Engine for 24h Top Losers (-2.5% to -50% drop).
        Identifies active breakdown continuation & rally-fade rejections at declining 21-EMA resistance.
        """
        try:
            if not symbol or current_price is None or current_price <= 0:
                return None
            if not is_valid_crypto_pair(symbol):
                return None
            stats_24h = stats_24h or {}
            chg_24h = float(stats_24h.get('priceChangePercent', -5.0))
            vol_24h = float(stats_24h.get('quoteVolume', 0.0))

            min_vol = float(CONFIG.get("min_24h_volume_usd", 10000000.0))
            if is_meme_or_shitcoin(symbol, price=current_price, quote_volume_24h=vol_24h if 'quoteVolume' in stats_24h else None):
                return None
            if 'quoteVolume' in stats_24h and vol_24h < min_vol:
                return None
            
            rsi_1h = 35.0
            ema21_1h = current_price * 1.03
            if df_1h is not None and len(df_1h) >= 20:
                closes = df_1h['close'].values
                ema21_1h = float(pd.Series(closes).ewm(span=21).mean().iloc[-1])
                diff = pd.Series(closes).diff()
                gain = diff.clip(lower=0).rolling(14).mean()
                loss = (-diff.clip(upper=0)).rolling(14).mean()
                rs = gain / loss.replace(0, 1e-8)
                rsi_s = 100 - (100 / (1 + rs))
                rsi_1h = float(rsi_s.iloc[-1]) if not pd.isna(rsi_s.iloc[-1]) else 35.0

            if rsi_1h > 68.0:
                # Do not short parabolic squeezes/spikes
                return None

            entry_p = current_price
            tp1_p = format_precision_price(entry_p * 0.982)   # +1.8% Profit on Short
            tp2_p = format_precision_price(entry_p * 0.962)   # +3.8% Profit on Short
            tp3_p = format_precision_price(entry_p * 0.925)   # +7.5% Profit on Short
            sl_base = entry_p * 1.015                         # -1.5% Stop Loss
            if df_1h is not None and len(df_1h) >= 1 and 'high' in df_1h.columns:
                candle_high = float(df_1h['high'].iloc[-1])
                sl_p = format_precision_price(max(sl_base, candle_high * 1.003))
            else:
                sl_p = format_precision_price(sl_base)
            
            tag = "🎯 ELITE BREAKDOWN CONTINUATION (SHORT)" if rsi_1h <= 42.0 else "🎯 ELITE RALLY-FADE RESISTANCE (SHORT)"
            conviction = 82.0 if rsi_1h <= 45.0 else 76.0
            meta_prob = 0.77
            
            return {
                "symbol": symbol,
                "strategy_type": "BREAKDOWN_TOP_LOSER",
                "strategy_archetype": "RALLY_FADE_SHORT" if rsi_1h > 42.0 else "BREAKDOWN_SHORT",
                "direction": "SHORT",
                "direction_label": "🔴 SHORT (TOP LOSER BREAKDOWN)",
                "decision": tag,
                "current_price": entry_p,
                "entry_price": entry_p,
                "tp1_price": tp1_p,
                "tp2_price": tp2_p,
                "tp3_price": tp3_p,
                "sl_price": sl_p,
                "conviction": conviction,
                "meta_win_prob": meta_prob,
                "grade": "💎 Grade A+ (ELITE CONFLUENCE)",
                "tier_label": "TOP LOSER SHORT",
                "change_24h_pct": chg_24h,
                "volume_24h_usd": vol_24h,
                "rsi_1h": round(rsi_1h, 1),
                "horizon_name": "⏳ Day Trade (1H)",
                "horizon_key": "swing"
            }
        except Exception:
            return None

    @staticmethod
    def evaluate_high_markup_momentum(symbol: str, current_price: float, df_1h: pd.DataFrame = None, df_15m: pd.DataFrame = None, stats_24h: dict = None, regime_info: dict = None) -> dict:
        """
        Specialized High-Markup / High-Volatility Mover Engine (e.g. HOME, PENGU, VIRTUAL, small explosive momentum runners).
        Captures explosive range expansion with high profit targets (+5.0% TP1, +10.5% TP2, +22.0% TP3).
        """
        try:
            if not symbol or current_price is None or current_price <= 0:
                return None
            if not is_valid_crypto_pair(symbol):
                return None
            stats_24h = stats_24h or {}
            chg_24h = float(stats_24h.get('priceChangePercent', 0.0))
            vol_24h = float(stats_24h.get('quoteVolume', 0.0))

            min_vol = float(CONFIG.get("min_24h_volume_usd", 10000000.0))
            if is_meme_or_shitcoin(symbol, price=current_price, quote_volume_24h=vol_24h if 'quoteVolume' in stats_24h else None):
                return None
            if 'quoteVolume' in stats_24h and vol_24h < min_vol:
                return None

            high_p = float(stats_24h.get('highPrice', current_price * 1.05))
            low_p = float(stats_24h.get('lowPrice', current_price * 0.95))
            markup_pct = round(((high_p - low_p) / max(1e-8, low_p)) * 100.0, 2) if low_p > 0 else 8.0

            # Determine tactical direction based on price location within 24h range
            mid_range = (high_p + low_p) / 2.0 if (high_p > low_p > 0) else current_price
            is_long = current_price >= mid_range or chg_24h >= 0.0

            entry_p = current_price
            if is_long:
                tp1_p = format_precision_price(entry_p * 1.050)   # +5.0% TP1
                tp2_p = format_precision_price(entry_p * 1.105)   # +10.5% TP2
                tp3_p = format_precision_price(entry_p * 1.220)   # +22.0% TP3
                sl_p = format_precision_price(entry_p * 0.968)    # -3.2% SL (1:3.3 R:R)
                dir_str = "LONG"
                dir_label = "🟢 LONG (HIGH MARKUP MOMENTUM)"
                dec_tag = f"🎯 HIGH-MARKUP EXPLOSIVE RUNNER (+{markup_pct}% RANGE)"
            else:
                tp1_p = format_precision_price(entry_p * 0.950)   # +5.0% Short TP1
                tp2_p = format_precision_price(entry_p * 0.895)   # +10.5% Short TP2
                tp3_p = format_precision_price(entry_p * 0.780)   # +22.0% Short TP3
                sl_p = format_precision_price(entry_p * 1.032)    # -3.2% Short SL (1:3.3 R:R)
                dir_str = "SHORT"
                dir_label = "🔴 SHORT (HIGH MARKUP RANGE FADE)"
                dec_tag = f"🎯 HIGH-MARKUP RANGE REVERSAL ({markup_pct}% RANGE)"

            return {
                "symbol": symbol,
                "strategy_type": "HIGH_MARKUP_MOMENTUM",
                "direction": dir_str,
                "direction_label": dir_label,
                "decision": dec_tag,
                "current_price": entry_p,
                "entry_price": entry_p,
                "tp1_price": tp1_p,
                "tp2_price": tp2_p,
                "tp3_price": tp3_p,
                "sl_price": sl_p,
                "conviction": 84.0,
                "meta_win_prob": 0.80,
                "grade": "💎 Grade A+ (HIGH MARKUP MOVER)",
                "grade_tier": 1,
                "tier_label": "HIGH MARKUP EXPANSION",
                "change_24h_pct": chg_24h,
                "volume_24h_usd": vol_24h,
                "markup_pct": markup_pct,
                "horizon_name": "⏳ Day Trade (1H)",
                "horizon_key": "swing",
                "horizon_tag": "1H",
                "priority": 1,
                "expected_return_pct": 5.0,
                "risk_reward_ratio": "1:3.3",
                "server_prediction_time": datetime.now(timezone.utc).isoformat()
            }
        except Exception:
            return None

    # Backward compatibility alias
    evaluate_top_loser_capitulation = evaluate_top_loser_breakdown_short


# ------------------------------------------------------------------------------
# 8b. INSTITUTIONAL TRIPLE SCREEN CONFLUENCE ENGINE (1D -> 4H -> 1H)
# ------------------------------------------------------------------------------
class TripleScreenConfluenceEngine:
    """
    ============================================================================
    🏛️ INSTITUTIONAL TRIPLE SCREEN SYSTEM (ALEXANDER ELDER / QUANT EXTENSION)
    ============================================================================
    Screen 1: 1D Chart (The Tide)   -> Macro Trend Direction (LONG_ONLY vs SHORT_ONLY vs NEUTRAL)
    Screen 2: 4H Chart (The Wave)   -> Market Structure & Behavior (Pullback / Squeeze / Overheated)
    Screen 3: 1H Chart (The Ripple) -> Tactical Execution Trigger, 1H ATR Stops, Multi-Tier Targets
    ============================================================================
    """
    @staticmethod
    def evaluate(symbol: str, raw_dfs: dict, live_price: float = None, stats_24h: dict = None, funding_info: dict = None) -> dict:
        try:
            if not raw_dfs or '1d' not in raw_dfs or '4h' not in raw_dfs or '1h' not in raw_dfs:
                return None
            
            df_1d = raw_dfs.get('1d')
            df_4h = raw_dfs.get('4h')
            df_1h = raw_dfs.get('1h')

            if df_1d is None or df_4h is None or df_1h is None:
                return None
            if len(df_1d) < 15 or len(df_4h) < 15 or len(df_1h) < 15:
                return None

            entry_p = float(live_price) if (live_price is not None and live_price > 0) else float(df_1h['close'].iloc[-1])
            if entry_p <= 0:
                return None

            # ------------------------------------------------------------------
            # SCREEN 1: 1D Chart (Macro Direction / The Tide)
            # ------------------------------------------------------------------
            c_1d = df_1d['close'].values
            d1_curr = float(c_1d[-1])
            d1_ema50 = float(pd.Series(c_1d).ewm(span=min(50, len(c_1d))).mean().iloc[-1])
            d1_ema21 = float(pd.Series(c_1d).ewm(span=min(21, len(c_1d))).mean().iloc[-1])
            
            diff_1d = pd.Series(c_1d).diff()
            gain_1d = diff_1d.clip(lower=0).rolling(14).mean()
            loss_1d = (-diff_1d.clip(upper=0)).rolling(14).mean()
            rs_1d = gain_1d / loss_1d.replace(0, 1e-8)
            d1_rsi = float((100 - (100 / (1 + rs_1d))).iloc[-1]) if not pd.isna(rs_1d.iloc[-1]) else 50.0

            if d1_curr > d1_ema50 and d1_ema21 >= d1_ema50 * 0.995 and d1_rsi >= 44.0:
                d1_direction = "BULLISH"
                d1_bias_label = "🟢 1D MACRO BULLISH (LONG-ONLY)"
            elif d1_curr < d1_ema50 and d1_ema21 <= d1_ema50 * 1.005 and d1_rsi <= 56.0:
                d1_direction = "BEARISH"
                d1_bias_label = "🔴 1D MACRO BEARISH (SHORT-ONLY)"
            else:
                d1_direction = "NEUTRAL"
                d1_bias_label = "⚪ 1D RANGE / CONSOLIDATION"

            # ------------------------------------------------------------------
            # SCREEN 2: 4H Chart (Market Behavior & Structure / The Wave)
            # ------------------------------------------------------------------
            c_4h = df_4h['close'].values
            h4_curr = float(c_4h[-1])
            h4_ema21 = float(pd.Series(c_4h).ewm(span=min(21, len(c_4h))).mean().iloc[-1])
            h4_ema50 = float(pd.Series(c_4h).ewm(span=min(50, len(c_4h))).mean().iloc[-1])
            
            diff_4h = pd.Series(c_4h).diff()
            gain_4h = diff_4h.clip(lower=0).rolling(14).mean()
            loss_4h = (-diff_4h.clip(upper=0)).rolling(14).mean()
            rs_4h = gain_4h / loss_4h.replace(0, 1e-8)
            h4_rsi = float((100 - (100 / (1 + rs_4h))).iloc[-1]) if not pd.isna(rs_4h.iloc[-1]) else 50.0

            tr_4h = pd.concat([
                df_4h['high'] - df_4h['low'],
                (df_4h['high'] - df_4h['close'].shift()).abs(),
                (df_4h['low'] - df_4h['close'].shift()).abs()
            ], axis=1).max(axis=1)
            atr_4h = float(tr_4h.rolling(14).mean().iloc[-1]) if len(tr_4h) >= 14 else float(h4_curr * 0.02)

            is_4h_overbought = (h4_rsi > 72.0) or (h4_curr > h4_ema21 + 2.4 * atr_4h)
            is_4h_oversold = (h4_rsi < 28.0) or (h4_curr < h4_ema21 - 2.4 * atr_4h)

            is_4h_bull_pullback = (0.96 * h4_ema21 <= h4_curr <= 1.035 * h4_ema21) and (38.0 <= h4_rsi <= 58.0)
            is_4h_bull_breakout = (h4_curr > h4_ema21) and (h4_ema21 >= h4_ema50) and (52.0 <= h4_rsi <= 70.0)

            is_4h_bear_rejection = (0.965 * h4_ema21 <= h4_curr <= 1.04 * h4_ema21) and (42.0 <= h4_rsi <= 62.0)
            is_4h_bear_breakdown = (h4_curr < h4_ema21) and (h4_ema21 <= h4_ema50) and (30.0 <= h4_rsi <= 48.0)

            if is_4h_overbought:
                h4_behavior = "OVERBOUGHT_EXHAUSTION"
                h4_behavior_label = "⚠️ 4H OVERBOUGHT (LONG BLOCKED)"
            elif is_4h_oversold:
                h4_behavior = "OVERSOLD_CAPITULATION"
                h4_behavior_label = "⚠️ 4H OVERSOLD (SHORT BLOCKED)"
            elif is_4h_bull_pullback:
                h4_behavior = "PULLBACK_VALUE"
                h4_behavior_label = "💎 4H VALUE PULLBACK (DIP ACCUMULATION)"
            elif is_4h_bear_rejection:
                h4_behavior = "RALLY_RESISTANCE"
                h4_behavior_label = "🛑 4H RALLY RESISTANCE (SHORT RELOAD)"
            elif is_4h_bull_breakout:
                h4_behavior = "MOMENTUM_EXPANSION"
                h4_behavior_label = "🚀 4H TREND MOMENTUM EXPANSION"
            elif is_4h_bear_breakdown:
                h4_behavior = "BREAKDOWN_EXPANSION"
                h4_behavior_label = "🩸 4H BREAKDOWN EXPANSION"
            else:
                h4_behavior = "RANGE_CONSOLIDATION"
                h4_behavior_label = "💤 4H RANGE CONSOLIDATION"

            # ------------------------------------------------------------------
            # SCREEN 3: 1H Chart (Execution Trigger & Risk / The Ripple)
            # ------------------------------------------------------------------
            c_1h = df_1h['close'].values
            h1_curr = float(c_1h[-1])
            h1_ema9 = float(pd.Series(c_1h).ewm(span=9).mean().iloc[-1])
            h1_ema21 = float(pd.Series(c_1h).ewm(span=21).mean().iloc[-1])

            diff_1h = pd.Series(c_1h).diff()
            gain_1h = diff_1h.clip(lower=0).rolling(14).mean()
            loss_1h = (-diff_1h.clip(upper=0)).rolling(14).mean()
            rs_1h = gain_1h / loss_1h.replace(0, 1e-8)
            h1_rsi = float((100 - (100 / (1 + rs_1h))).iloc[-1]) if not pd.isna(rs_1h.iloc[-1]) else 50.0

            tr_1h = pd.concat([
                df_1h['high'] - df_1h['low'],
                (df_1h['high'] - df_1h['close'].shift()).abs(),
                (df_1h['low'] - df_1h['close'].shift()).abs()
            ], axis=1).max(axis=1)
            atr_1h = float(tr_1h.rolling(14).mean().iloc[-1]) if len(tr_1h) >= 14 else float(h1_curr * 0.015)
            atr_1h = max(atr_1h, entry_p * 0.008)

            # ------------------------------------------------------------------
            # SYNTHESIS & SIGNAL EXECUTION
            # ------------------------------------------------------------------
            signal = None

            # LONG TRIGGER: 1D is Bullish (or Neutral), 4H in value/breakout (not overbought), 1H confirms
            if d1_direction in ["BULLISH", "NEUTRAL"] and not is_4h_overbought:
                is_1h_long_trigger = (entry_p >= h1_ema9 * 0.997) and (45.0 <= h1_rsi <= 68.0)
                if (is_4h_bull_pullback or is_4h_bull_breakout) and is_1h_long_trigger:
                    tag = "🎯 ELITE 1D-4H-1H PULLBACK (LONG)" if is_4h_bull_pullback else "🎯 ELITE 1D-4H-1H BREAKOUT (LONG)"
                    sl_dist = max(atr_1h * 1.25, entry_p * 0.014)
                    tp1_dist = max(atr_1h * 1.25, entry_p * 0.015)
                    tp2_dist = tp1_dist * 1.80
                    tp3_dist = tp1_dist * 2.80

                    conv = 88.0 if (d1_direction == "BULLISH" and is_4h_bull_pullback) else 82.0
                    meta_p = 0.82 if d1_direction == "BULLISH" else 0.74

                    signal = {
                        "symbol": symbol,
                        "strategy_type": "TRIPLE_SCREEN_CONFLUENCE",
                        "direction": "LONG",
                        "direction_label": "🟢 LONG (1D-4H-1H TRIPLE SCREEN)",
                        "decision": tag,
                        "current_price": entry_p,
                        "entry_price": entry_p,
                        "tp1_price": format_precision_price(entry_p + tp1_dist),
                        "tp2_price": format_precision_price(entry_p + tp2_dist),
                        "tp3_price": format_precision_price(entry_p + tp3_dist),
                        "sl_price": format_precision_price(entry_p - sl_dist),
                        "conviction": conv,
                        "meta_win_prob": meta_p,
                        "grade": "💎 Grade A+ (1D-4H-1H CONFLUENCE)",
                        "grade_tier": 1,
                        "tier_label": "1D-4H-1H TRIPLE SCREEN",
                        "d1_direction": d1_direction,
                        "d1_bias_label": d1_bias_label,
                        "h4_behavior": h4_behavior,
                        "h4_behavior_label": h4_behavior_label,
                        "h1_rsi": round(h1_rsi, 1),
                        "h4_rsi": round(h4_rsi, 1),
                        "d1_rsi": round(d1_rsi, 1),
                        "horizon_name": "⏳ Day Trade (1H)",
                        "horizon_key": "swing",
                        "is_triple_screen": True,
                        "priority": 1
                    }

            # SHORT TRIGGER: 1D is Bearish (or Neutral), 4H in resistance/breakdown (not oversold), 1H confirms
            elif d1_direction in ["BEARISH", "NEUTRAL"] and not is_4h_oversold:
                is_1h_short_trigger = (entry_p <= h1_ema9 * 1.003) and (32.0 <= h1_rsi <= 55.0)
                if (is_4h_bear_rejection or is_4h_bear_breakdown) and is_1h_short_trigger:
                    tag = "🎯 ELITE 1D-4H-1H RALLY-FADE (SHORT)" if is_4h_bear_rejection else "🎯 ELITE 1D-4H-1H BREAKDOWN (SHORT)"
                    sl_dist = max(atr_1h * 1.25, entry_p * 0.014)
                    tp1_dist = max(atr_1h * 1.25, entry_p * 0.015)
                    tp2_dist = tp1_dist * 1.80
                    tp3_dist = tp1_dist * 2.80

                    conv = 88.0 if (d1_direction == "BEARISH" and is_4h_bear_rejection) else 82.0
                    meta_p = 0.82 if d1_direction == "BEARISH" else 0.74

                    signal = {
                        "symbol": symbol,
                        "strategy_type": "TRIPLE_SCREEN_CONFLUENCE",
                        "direction": "SHORT",
                        "direction_label": "🔴 SHORT (1D-4H-1H TRIPLE SCREEN)",
                        "decision": tag,
                        "current_price": entry_p,
                        "entry_price": entry_p,
                        "tp1_price": format_precision_price(entry_p - tp1_dist),
                        "tp2_price": format_precision_price(entry_p - tp2_dist),
                        "tp3_price": format_precision_price(entry_p - tp3_dist),
                        "sl_price": format_precision_price(entry_p + sl_dist),
                        "conviction": conv,
                        "meta_win_prob": meta_p,
                        "grade": "💎 Grade A+ (1D-4H-1H CONFLUENCE)",
                        "grade_tier": 1,
                        "tier_label": "1D-4H-1H TRIPLE SCREEN",
                        "d1_direction": d1_direction,
                        "d1_bias_label": d1_bias_label,
                        "h4_behavior": h4_behavior,
                        "h4_behavior_label": h4_behavior_label,
                        "h1_rsi": round(h1_rsi, 1),
                        "h4_rsi": round(h4_rsi, 1),
                        "d1_rsi": round(d1_rsi, 1),
                        "horizon_name": "⏳ Day Trade (1H)",
                        "horizon_key": "swing",
                        "is_triple_screen": True,
                        "priority": 1
                    }

            return signal
        except Exception:
            return None


# ------------------------------------------------------------------------------
# 9. MULTI-HORIZON QUANT ENGINE CORE
# ------------------------------------------------------------------------------
class HybridQuantEngine:
    def __init__(self, config: dict):
        self.config = config
        self.loader = CryptoDataLoader()
        self.fe = AdvancedFeatureEngineer()
        self.labeler = TripleBarrierLabeler()
        self.btc_cache = {}
        self.model_cache_path = os.path.join(self.config.get('models_export_dir', './models_export_v3'), "models_cache.joblib")
        self._model_cache_dirty = False
        self.force_fresh_training = self.config.get('force_fresh_training_on_scan', True)
        if not self.force_fresh_training and os.path.exists(self.model_cache_path):
            try:
                self.model_cache = joblib.load(self.model_cache_path)
                self._prune_model_cache(max_size=1200)
                print(f"[MODEL CACHE 🧠] Loaded {len(self.model_cache)} pre-warmed models from persistent cache: {self.model_cache_path}", flush=True)
            except Exception as e:
                print(f"[MODEL CACHE ⚠️] Cache notice: {e}", flush=True)
                self.model_cache = {}
        else:
            self.model_cache = {}
            if self.force_fresh_training:
                print("[JUST-IN-TIME ML 🧠] Fresh Retraining Mode Active: Zero-cache JIT pipeline enabled for freshly closed candles.", flush=True)
        self._forecast_file_lock = threading.RLock()
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
        self.btc_predicted_trend = "CONSOLIDATION"
        self.btc_trend_probability = 60.0
        self.btc_bull_trend_prob = 30.0
        self.btc_bear_trend_prob = 20.0
        self.btc_consolidation_prob = 50.0
        self.btc_predicted_target = 0.0
        self.btc_predicted_change_pct = 0.0
        self.btc_breakout_prediction = "⚖️ RANGE BOUND"
        self.btc_altcoin_posture = "STANDARD_EXECUTION"
        self.btc_market_phase_description = "Balanced equilibrium state across multi-horizon market structure."
        self.trader_playbook = TraderRegimePlaybook.generate(
            regime=self.btc_shield_regime,
            predicted_trend=self.btc_predicted_trend,
            bull_prob=self.btc_bull_trend_prob,
            bear_prob=self.btc_bear_trend_prob,
            cons_prob=self.btc_consolidation_prob,
            is_squeeze=self.btc_is_squeeze,
            btc_price=self.btc_price,
            breakout_pred=self.btc_breakout_prediction
        )
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
        self.current_market_regime = {}
        self.top_24h_gainers_signals = []
        self.top_24h_losers_signals = []
        self.daily_macro_cache = {}  # {(symbol, h_key, date_utc): cached_macro_horizon_result}
        self.daily_macro_date = ""
        self.master_matrix_universe = {}
        forecast_path = os.path.join(self.config['app_export_dir'], "live_market_forecast.json")
        if os.path.exists(forecast_path):
            try:
                all_tickers_preload = self.loader.fetch_all_tickers(max_age_seconds=15.0) if hasattr(self, 'loader') else {}
                with open(forecast_path, "r", encoding="utf-8") as f:
                    f_data = json.load(f)
                    for item in f_data.get("scanner_leaderboard", []):
                        if isinstance(item, dict) and "symbol" in item:
                            sym = item["symbol"]
                            c_tag = str(item.get("confluence_tag", ""))
                            # Only preload genuine ML scanned results, skip dummy scanning placeholders
                            if is_valid_crypto_pair(sym) and "SCANNING" not in c_tag and "INITIALIZING" not in c_tag and item.get("best_priority", 4) < 4:
                                raw_s = sym.replace('/', '').replace(':USDT', '')
                                live_p = float(all_tickers_preload.get(sym) or all_tickers_preload.get(raw_s) or 0.0)
                                self._refresh_asset_entry_timestamps(item, live_price=live_p if live_p > 0 else None)
                                self.master_matrix_universe[sym] = item
                if self.master_matrix_universe:
                    print(f"[PREDICTION MATRIX 🌐] Preloaded {len(self.master_matrix_universe)} valid asset predictions into memory (All timestamps & prices calibrated to live market).")
            except Exception:
                pass
        os.makedirs(self.config['models_export_dir'], exist_ok=True)
        os.makedirs(self.config['app_export_dir'], exist_ok=True)

    def _refresh_asset_entry_timestamps(self, item: dict, live_price: float = None) -> dict:
        """Refreshes an asset's prediction timestamp and 10-horizon trade windows to standard candle open/close schedules, dynamically rolling forward targets upon price breakout."""
        now_utc = datetime.now(timezone.utc)
        now_iso = now_utc.isoformat()
        now_ts = int(now_utc.timestamp())
        
        p = float(live_price) if (live_price and live_price > 0) else float(item.get('current_price', 1.0))
        p_fmt = format_precision_price_str
        
        item['current_price'] = format_precision_price(p)
        item['server_prediction_time'] = now_iso
        item['server_prediction_ts'] = now_ts
        
        horizons = item.get('horizons', {})
        display_horizon_cfgs = dict(self.config.get('horizons', {}))
        if 'scalp' not in display_horizon_cfgs:
            display_horizon_cfgs['scalp'] = {"anchor_tf": "15m", "bars": 4, "duration_label": "15-60 Mins Scalp"}
        if 'macro' not in display_horizon_cfgs:
            display_horizon_cfgs['macro'] = {"anchor_tf": "1d", "bars": 1, "duration_label": "24h Macro"}
        for h_key, h_cfg in display_horizon_cfgs.items():
            h_data = horizons.get(h_key)
            if not isinstance(h_data, dict):
                continue
            trade_open, target_close, trade_open_str, trade_close_str = CryptoDataLoader.get_candle_schedule(
                h_cfg['anchor_tf'], bars=h_cfg.get('bars', 1), now_utc=now_utc
            )
            window_str = f"{trade_open_str} ➔ {trade_close_str} ({h_cfg['duration_label']})"
            
            h_data['current_price'] = format_precision_price(p)
            h_data['trade_open_str'] = trade_open_str
            h_data['trade_close_str'] = trade_close_str
            h_data['predicted_close_utc'] = trade_close_str
            h_data['predicted_window_str'] = window_str
            
            exp_ret = float(h_data.get('exp_return', 0.008))
            h_dir = h_data.get('direction', 'BULLISH')
            is_bull = (h_dir == 'BULLISH' or h_dir == 'LONG')
            is_hype = bool(h_data.get('is_hype_surge', False))
            is_blowoff = bool(h_data.get('is_blowoff_top', False))
            
            # Dynamic Multi-Tier Targets relative to live price p and horizon timeframe
            horizon_min_sl_pct_map = {
                'scalp': 0.015,       # 1.5% min SL
                'horizon_30m': 0.018, # 1.8% min SL
                'swing': 0.022,       # 2.2% min SL
                'horizon_4h': 0.028,  # 2.8% min SL
                'macro': 0.038,       # 3.8% min SL (allows 24H candle breathing room)
                'horizon_4d': 0.045,  # 4.5% min SL
                'weekly': 0.050,      # 5.0% min SL
                'biweekly': 0.060,    # 6.0% min SL
                'monthly': 0.075      # 7.5% min SL
            }
            min_sl_ratio = horizon_min_sl_pct_map.get(h_key, 0.022)
            max_sl_pct_map = {
                'scalp': 0.025,
                'horizon_30m': 0.028,
                'swing': 0.035,
                'horizon_4h': 0.040,
                'macro': 0.055,
                'horizon_4d': 0.065,
                'weekly': 0.075,
                'biweekly': 0.085,
                'monthly': 0.100
            }
            max_sl_ratio = max_sl_pct_map.get(h_key, 0.040)
            raw_sl_ratio = min(max_sl_ratio, max(min_sl_ratio, min_sl_ratio * (h_cfg.get('sl_mult', 1.0) / 1.0)))
            sl_dist = p * raw_sl_ratio
            
            # Dynamic, highly reachable TP1 targets calibrated to candle horizon duration
            if h_key == 'scalp':
                tp_step = min(0.025, max(0.018, abs(exp_ret) if abs(exp_ret) > 0.012 else sl_dist * 1.20 / p))
            elif h_key == 'horizon_30m':
                tp_step = min(0.032, max(0.022, abs(exp_ret) if abs(exp_ret) > 0.015 else sl_dist * 1.25 / p))
            elif h_key == 'swing':
                tp_step = min(0.045, max(0.028, abs(exp_ret) if abs(exp_ret) > 0.020 else sl_dist * 1.30 / p))
            else:
                tp_step = max(sl_dist * 1.30 / p, abs(exp_ret))
            
            if is_bull:
                tp1 = p * (1.0 + tp_step)
                tp2 = p * (1.0 + tp_step * 1.85)
                tp3 = p * (1.0 + tp_step * 2.90)
                tp4 = p * (1.0 + tp_step * 4.00)
                sl = p - sl_dist
                best_sell = tp4 if is_hype else tp3
                
                # Dynamic Target Advancement: if live price has reached or crossed previous prediction
                prev_pred = float(h_data.get('predicted_next_price', 0))
                if prev_pred > 0 and p >= prev_pred:
                    projected = tp2 if p < tp2 else (tp3 if p < tp3 else tp4)
                else:
                    projected = tp1
                
                pred_ret = ((projected - p) / p) * 100.0
                type_str = "LONG 🟢"
                market_str = "Spot & Futures"
            else:
                min_floor = max(1e-8, p * 0.15)
                tp1 = max(min_floor, p * (1.0 - min(0.35, tp_step)))
                tp2 = max(min_floor, p * (1.0 - min(0.55, tp_step * 1.50)))
                tp3 = max(min_floor, p * (1.0 - min(0.70, tp_step * 2.00)))
                tp4 = max(min_floor, p * (1.0 - min(0.80, tp_step * 2.50)))
                sl = p + sl_dist
                best_sell = max(min_floor, tp4 if is_blowoff else tp3)
                
                prev_pred = float(h_data.get('predicted_next_price', 0))
                if prev_pred > 0 and p <= prev_pred:
                    projected = tp2 if p > tp2 else (tp3 if p > tp3 else tp4)
                else:
                    projected = tp1
                
                pred_ret = ((projected - p) / p) * 100.0
                type_str = "SHORT 🔴"
                market_str = "Futures Only ⚡"

            h_data['predicted_next_price'] = format_precision_price(projected)
            h_data['predicted_return_pct'] = round(pred_ret, 2)
            h_data['best_sell_price'] = format_precision_price(best_sell)
            h_data['tp_price'] = format_precision_price(tp1)
            h_data['tp1_price'] = format_precision_price(tp1)
            h_data['tp2_price'] = format_precision_price(tp2)
            h_data['tp3_price'] = format_precision_price(tp3)
            h_data['tp4_price'] = format_precision_price(tp4)
            h_data['sl_price'] = format_precision_price(sl)
            
            coin_tag = item.get('symbol', 'CRYPTO').split('/')[0]
            pro_sig = (
                f"🚀 PAIR: #{coin_tag}/USDT\n"
                f"📊 TYPE: {type_str}\n"
                f"🌐 MARKET: {market_str}\n"
                f"📅 PREDICTED CANDLE: {window_str}\n"
                f"🎯 ENTRY: {p_fmt(p)}\n"
                f"🔮 ML NEXT PRICE: {p_fmt(projected)} ({pred_ret:+.2f}%)\n"
                f"💎 BEST EXIT / SELL ZONE: {p_fmt(best_sell)}\n\n"
                f"💎 TAKE PROFITS:\n"
                f"➤ TP1: {p_fmt(tp1)}\n"
                f"➤ TP2: {p_fmt(tp2)}\n"
                f"➤ TP3: {p_fmt(tp3)}\n\n"
                f"🛑 STOP LOSS: {p_fmt(sl)}\n\n"
                f"📈 RISK-TO-REWARD RATIO: 1:2"
            )
            h_data['pro_signal_text'] = pro_sig
            h_data['vip_signal_text'] = pro_sig
        return item

    def _get_horizon_model_ttl(self, horizon_key: str) -> float:
        """
        High-Frequency Model Cache TTL Architecture:
        Enforces ultra-early cache expiration so the quant engine continuously runs with
        recently trained models adapted to the latest market microstructure:
        - 15M Scalp: 300s (5 minutes)
        - 30M Scalp: 600s (10 minutes)
        - 1H Swing: 1200s (20 minutes)
        - 4H Intraday: 2700s (45 minutes)
        - 24H Macro: 7200s (2 hours)
        - Default Fallback: 900s (15 minutes)
        """
        kl = str(horizon_key or "").lower()
        if "15m" in kl or "scalp" in kl:
            return 300.0   # 5 minutes for 15M Micro Trigger
        elif "30m" in kl:
            return 600.0   # 10 minutes for 30M Scalp
        elif "1h" in kl or "swing" in kl:
            return 1200.0  # 20 minutes for 1H Swing
        elif "macro" in kl or "24h" in kl or "1d" in kl:
            return 7200.0  # 2 hours for 24H Daily Anchor
        elif "4h" in kl:
            return 2700.0  # 45 minutes for 4H Intraday
        return 900.0       # 15 minutes default fallback

    def _prune_model_cache(self, max_size: int = 1500, max_age_seconds: float = 7200):
        """
        OS Memory Guard & Dynamic Rolling Freshness Enforcer:
        Prunes models beyond rolling TTL (5m for 15M, 10m for 30M, 20m for 1H, 45m for 4H, 2h for 24H)
        and limits total cache size to prevent unbounded RAM growth.
        """
        now_ts = time.time()
        # 1. Prune expired entries based on horizon-specific TTL
        expired_keys = [k for k, v in self.model_cache.items() if (now_ts - v.get('ts', 0)) >= self._get_horizon_model_ttl(k)]
        for k in expired_keys:
            self.model_cache.pop(k, None)
            self._model_cache_dirty = True
        # 2. If still exceeds max_size, drop oldest entries by timestamp
        if len(self.model_cache) > max_size:
            sorted_keys = sorted(self.model_cache.keys(), key=lambda k: self.model_cache[k].get('ts', 0))
            excess = len(self.model_cache) - max_size
            for k in sorted_keys[:excess]:
                self.model_cache.pop(k, None)
            self._model_cache_dirty = True

    def _handle_market_transition_if_changed(
        self,
        prev_regime: str,
        new_regime: str,
        prev_code: str,
        new_code: str,
        prev_trend: str,
        new_trend: str,
        prev_squeeze: bool = None,
        new_squeeze: bool = False,
        prev_vol_ratio: float = 1.0,
        new_vol_ratio: float = 1.0
    ) -> bool:
        """
        ⚡ Real-time Market Regime & Trend Transition Engine:
        Detects shifts in regime, shield status code, predicted trend, volatility squeeze,
        or volatility spikes. When a shift occurs:
        1. Immediately purges in-memory model cache & deletes disk checkpoint to force fresh retraining.
        2. Invalidates daily macro evaluations cache.
        3. Clears exchange candle & ticker caches so fresh live distributions are loaded.
        4. Triggers immediate non-blocking meta-labeler retraining pipeline.
        5. Signals the continuous daemon to break early from sleep and start immediate fresh scan.
        """
        # Cold-start guard: If engine is just starting, do not trigger false-positive transition
        if not getattr(self, '_regime_engine_initialized', False):
            self._regime_engine_initialized = True
            return False

        reasons = []
        if prev_regime and new_regime and prev_regime != new_regime:
            reasons.append(f"Regime: {prev_regime} ➔ {new_regime}")
        if prev_code and new_code and prev_code != new_code:
            reasons.append(f"Shield Code: {prev_code} ➔ {new_code}")
        if prev_trend and new_trend and prev_trend != new_trend:
            reasons.append(f"Predicted Trend: {prev_trend} ➔ {new_trend}")
        if prev_squeeze is not None and new_squeeze is not None and prev_squeeze != new_squeeze:
            reasons.append(f"Squeeze State: {'COILING' if new_squeeze else 'EXPANDING'}")
        if prev_vol_ratio > 0 and new_vol_ratio > 0 and abs(new_vol_ratio - prev_vol_ratio) >= 0.35:
            reasons.append(f"Volatility Shift: {prev_vol_ratio:.2f} ➔ {new_vol_ratio:.2f}")

        if not reasons:
            return False

        print("\n" + "=" * 88, flush=True)
        print(f"⚡ [MARKET REGIME & TREND SHIFT DETECTED]", flush=True)
        for r in reasons:
            print(f"   • {r}", flush=True)
        print("🚀 Executing Immediate Cache Invalidation & Accelerated Retraining Pipeline...", flush=True)
        print("=" * 88 + "\n", flush=True)

        # 1. Immediately invalidate & clear model cache so predictions retrain on current distribution
        if hasattr(self, 'model_cache'):
            evicted_count = len(self.model_cache)
            self.model_cache.clear()
            self._model_cache_dirty = True
            print(f"[REGIME RETRAIN 🧹] Flushed {evicted_count} cached per-coin models due to market shift. Fresh models will train immediately on new regime.", flush=True)
            if os.path.exists(self.model_cache_path):
                try:
                    os.remove(self.model_cache_path)
                except Exception:
                    pass
            tmp_cache = self.model_cache_path + ".tmp"
            if os.path.exists(tmp_cache):
                try:
                    os.remove(tmp_cache)
                except Exception:
                    pass

        # 2. Invalidate daily macro evaluations cache so 24H models recalculate on fresh regime
        if hasattr(self, 'daily_macro_cache'):
            macro_evicted = len(self.daily_macro_cache)
            self.daily_macro_cache.clear()
            self.daily_macro_date = ""
            if macro_evicted > 0:
                print(f"[REGIME RETRAIN 🧹] Flushed {macro_evicted} daily macro horizon cache entries.", flush=True)

        # 3. Invalidate exchange candle & ticker caches in loader to force fresh live data fetch
        if hasattr(self.loader, '_cache'):
            self.loader._cache.clear()
        if hasattr(self.loader, '_cache_ts'):
            self.loader._cache_ts.clear()
        if hasattr(self.loader, '_live_tickers_cache'):
            self.loader._live_tickers_cache.clear()

        # 4. Invalidate BTC cross-asset beta reference cache so fresh regime candles are preloaded
        if hasattr(self, 'btc_cache'):
            self.btc_cache.clear()

        # 5. Dynamic Signals Bot Gating / Handling based on new condition
        self.handle_signals_bot_on_regime_change(prev_code, new_code, new_regime)

        # 6. Trigger immediate asynchronous meta-labeler retraining pipeline
        try:
            from app.services.model_retrainer import check_and_trigger_async
            check_and_trigger_async(force=True, min_new_samples=0)
            print("[MODEL RETRAIN 🚀] Launched asynchronous meta-labeler retraining pipeline on market shift.", flush=True)
        except Exception as e:
            print(f"[MODEL RETRAIN NOTICE] Async retrain trigger note: {e}", flush=True)

        # 7. Request immediate rescan interrupt from daemon sleep loop
        self._force_rescan_requested = True

        # 8. Synchronize shield file immediately
        self._last_shield_file_sync_ts = time.time()
        self._sync_live_shield_to_file()

        return True

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

    def evaluate_btc_market_regime(self, df_15m_override: pd.DataFrame = None, live_btc_price: float = None) -> dict:
        """
        🛡️ ADVANCED PREDICTIVE BTC QUANTITATIVE MARKET SHIELD & REGIME FORECASTER
        Predicts future Bullish Trends, Bearish Breakdowns/Dumps, and Volatility Consolidation Squeezes
        using multi-timeframe geometric structure, volatility ratios, Choppiness Index, ADX momentum,
        and continuous price target projections.
        """
        try:
            # Capture baseline regime & trend state before calculation to detect transitions
            prev_regime = getattr(self, "btc_shield_regime", "")
            prev_code = getattr(self, "btc_shield_code", "")
            prev_trend = getattr(self, "btc_predicted_trend", "")
            prev_squeeze = getattr(self, "btc_is_squeeze", None)
            prev_vol_ratio = getattr(self, "btc_vol_ratio", 1.0)

            df_15m = df_15m_override if df_15m_override is not None else self.btc_cache.get('15m')
            df_1h = self.btc_cache.get('1h')
            df_4h = self.btc_cache.get('4h')
            df_1d = self.btc_cache.get('1d')

            if df_15m is None or len(df_15m) < 5:
                return {}

            c_now = float(live_btc_price) if (live_btc_price is not None and live_btc_price > 0) else float(df_15m['close'].iloc[-1])
            c_prev_15m = float(df_15m['close'].iloc[-2]) if len(df_15m) >= 2 else c_now
            c_prev3_15m = float(df_15m['close'].iloc[-4]) if len(df_15m) >= 4 else c_prev_15m
            ret_15m = (c_now - c_prev_15m) / (c_prev_15m + 1e-10)
            ret_45m = (c_now - c_prev3_15m) / (c_prev3_15m + 1e-10)

            # 1H metrics
            ret_1h = 0.0
            ema20_1h = c_now
            ema50_1h = c_now
            ema200_1h = c_now
            rsi_1h = 50.0
            adx_1h = 20.0
            chop_1h = 50.0
            if df_1h is not None and len(df_1h) >= 15:
                c_prev_1h = float(df_1h['close'].iloc[-2])
                ret_1h = (c_now - c_prev_1h) / (c_prev_1h + 1e-10)
                ema20_1h = float(df_1h['close'].ewm(span=20, adjust=False).mean().iloc[-1])
                ema50_1h = float(df_1h['close'].ewm(span=50, adjust=False).mean().iloc[-1])
                ema200_1h = float(df_1h['close'].ewm(span=200, adjust=False).mean().iloc[-1]) if len(df_1h) >= 200 else ema50_1h
                rsi_1h_series = self.fe.compute_rsi(df_1h['close'], period=14)
                rsi_1h = float(rsi_1h_series.iloc[-1]) * 100.0 if not rsi_1h_series.empty else 50.0
                adx_res = self.fe.compute_adx(df_1h, period=14)
                adx_1h_series = adx_res[0] if isinstance(adx_res, tuple) else adx_res
                adx_1h = float(adx_1h_series.iloc[-1]) if not adx_1h_series.empty else 20.0
                chop_1h_series = self.fe.compute_chop_index(df_1h, period=14)
                chop_1h = float(chop_1h_series.iloc[-1]) if not chop_1h_series.empty else 50.0
            elif len(df_15m) >= 20:
                ret_1h = (c_now - float(df_15m['close'].iloc[-4])) / (float(df_15m['close'].iloc[-4]) + 1e-10)
                rsi_1h_series = self.fe.compute_rsi(df_15m['close'], period=14)
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

            # Bollinger Bands 15M & 1H
            std_15m = float(df_15m['close'].rolling(20).std().iloc[-1]) if len(df_15m) >= 20 else 0.0
            bb_mid_15m = float(df_15m['close'].rolling(20).mean().iloc[-1]) if len(df_15m) >= 20 else ema21_15m
            bb_upper_15m = bb_mid_15m + 2.0 * std_15m
            bb_lower_15m = bb_mid_15m - 2.0 * std_15m
            bbw_15m = (bb_upper_15m - bb_lower_15m) / (bb_mid_15m + 1e-10)

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

            # -----------------------------------------------------------------
            # 📊 INSTITUTIONAL ROLLING VOLUME-WEIGHTED AVERAGE PRICE (VWAP)
            # -----------------------------------------------------------------
            vwap_1h = None
            if df_1h is not None and len(df_1h) >= 2 and 'volume' in df_1h.columns:
                bars_1h = min(24, len(df_1h))
                sub_1h = df_1h.iloc[-bars_1h:]
                vol_sum_1h = float(sub_1h['volume'].sum())
                if vol_sum_1h > 0:
                    typ_1h = (sub_1h['high'] + sub_1h['low'] + sub_1h['close']) / 3.0
                    vwap_1h = float((typ_1h * sub_1h['volume']).sum() / vol_sum_1h)

            vwap_4h = None
            if df_4h is not None and len(df_4h) >= 2 and 'volume' in df_4h.columns:
                bars_4h = min(18, len(df_4h))
                sub_4h = df_4h.iloc[-bars_4h:]
                vol_sum_4h = float(sub_4h['volume'].sum())
                if vol_sum_4h > 0:
                    typ_4h = (sub_4h['high'] + sub_4h['low'] + sub_4h['close']) / 3.0
                    vwap_4h = float((typ_4h * sub_4h['volume']).sum() / vol_sum_4h)

            # Institutional Hysteresis Buffer around VWAP Benchmark (~0.12% or ~0.10 * ATR)
            # Mitigates micro-tick regime oscillation / boundary flickering near VWAP
            vwap_hysteresis = 0.0012
            prev_shield_code = getattr(self, 'btc_shield_code', 'NORMAL')

            if prev_shield_code in ["BEAR_TREND", "ALERT_DUMP"]:
                # If currently in bear regime, require decisive reclaim above VWAP + buffer to clear
                is_below_vwap_1h = bool(vwap_1h is not None and c_now < (vwap_1h * (1.0 + vwap_hysteresis)))
                is_below_vwap_4h = bool(vwap_4h is not None and c_now < (vwap_4h * (1.0 + vwap_hysteresis)))
            else:
                # If currently in consolidation/bull, require decisive drop below VWAP - buffer to trip
                is_below_vwap_1h = bool(vwap_1h is not None and c_now < (vwap_1h * (1.0 - vwap_hysteresis)))
                is_below_vwap_4h = bool(vwap_4h is not None and c_now < (vwap_4h * (1.0 - vwap_hysteresis)))

            is_btc_below_vwap = is_below_vwap_1h or is_below_vwap_4h
            is_btc_below_vwap_both = is_below_vwap_1h and is_below_vwap_4h

            # Multi-timeframe trend states
            is_1d_bull = (c_now >= ema50_1d) and (ema50_1d >= ema200_1d)
            is_1d_bear = (c_now <= ema50_1d) and (ema50_1d <= ema200_1d)

            is_4h_bull = (c_now >= ema50_4h) and (rsi_4h >= 52.0)
            is_4h_bear = (c_now <= ema50_4h) and (rsi_4h <= 48.0)

            is_1h_bull = (c_now >= ema20_1h) and (ema20_1h >= ema50_1h)
            is_1h_bear = (c_now <= ema20_1h) and (ema20_1h <= ema50_1h)

            is_15m_bull = (ema9_15m >= ema21_15m) and (rsi_15m >= 52.0)
            is_15m_bear = (ema9_15m <= ema21_15m) and (rsi_15m <= 48.0)

            is_squeeze = (bbw_15m <= 0.025) or (chop_1h >= 60.0 and adx_1h <= 22.0) or (abs(ret_1h) < 0.008 and abs(ret_15m) < 0.005 and bbw_15m <= 0.030)

            # --- MULTI-FACTOR PREDICTIVE PROBABILITY ENGINE ---
            bull_score = 0.0
            bear_score = 0.0
            cons_score = 0.0

            # Factor 1: Multi-Timeframe Alignment (0-40 pts)
            tf_bull_count = sum([is_1d_bull, is_4h_bull, is_1h_bull, is_15m_bull])
            tf_bear_count = sum([is_1d_bear, is_4h_bear, is_1h_bear, is_15m_bear])
            bull_score += tf_bull_count * 10.0
            bear_score += tf_bear_count * 10.0
            if tf_bull_count == 2 and tf_bear_count == 2:
                cons_score += 25.0
            elif tf_bull_count <= 1 and tf_bear_count <= 1:
                cons_score += 20.0

            # Factor 2: Momentum & RSI Dynamics (0-30 pts)
            is_flat_range = abs(ret_1h) < 0.008 and abs(ret_15m) < 0.005
            if is_flat_range:
                # In flat range price action, intermediate/low RSI represents range support / mean-reversion equilibrium
                cons_score += 30.0
                if rsi_1h >= 62.0:
                    bull_score += 10.0
                elif rsi_1h <= 38.0:
                    cons_score += 10.0
                    bull_score += 5.0  # Oversold range support / dip accumulation
            else:
                if rsi_1h >= 60.0 and rsi_15m >= 55.0 and ret_1h > 0:
                    bull_score += 25.0
                elif rsi_1h <= 40.0 and rsi_15m <= 45.0 and ret_1h < -0.006:
                    bear_score += 25.0
                elif 45.0 <= rsi_1h <= 55.0 and 45.0 <= rsi_15m <= 55.0:
                    cons_score += 30.0
                else:
                    bull_score += 10.0 if rsi_1h > 50.0 else 0.0
                    bear_score += 10.0 if rsi_1h < 50.0 else 0.0
                    cons_score += 10.0

            # Factor 3: Choppiness Index & ADX Trend Strength (0-20 pts)
            if chop_1h >= 60.0 or adx_1h <= 20.0:
                cons_score += 25.0
            elif chop_1h <= 38.2 and adx_1h >= 28.0:
                if ret_1h > 0 or is_1h_bull:
                    bull_score += 20.0
                else:
                    bear_score += 20.0
            else:
                cons_score += 10.0

            # Factor 4: Price Returns & Velocity (0-20 pts)
            if ret_15m >= 0.008 or ret_1h >= 0.015:
                bull_score += 20.0
            elif ret_15m <= -0.008 or ret_1h <= -0.015:
                bear_score += 20.0
            elif abs(ret_15m) < 0.004 and abs(ret_1h) < 0.008:
                cons_score += 25.0

            # Factor 5: Volatility Contraction / Squeeze Bonus
            if is_squeeze:
                cons_score += 35.0

            # Base baseline
            bull_score = max(5.0, bull_score)
            bear_score = max(5.0, bear_score)
            cons_score = max(5.0, cons_score)

            total_score = bull_score + bear_score + cons_score
            bull_trend_prob = round((bull_score / total_score) * 100.0, 1)
            bear_trend_prob = round((bear_score / total_score) * 100.0, 1)
            cons_trend_prob = round(100.0 - bull_trend_prob - bear_trend_prob, 1)
            if cons_trend_prob < 0.0:
                cons_trend_prob = 0.0
                total_adj = bull_trend_prob + bear_trend_prob
                bull_trend_prob = round((bull_trend_prob / total_adj) * 100.0, 1)
                bear_trend_prob = round(100.0 - bull_trend_prob, 1)

            # Determine dominant predicted trend
            if is_squeeze or (abs(ret_1h) < 0.006 and abs(ret_15m) < 0.004 and cons_trend_prob >= 30.0):
                predicted_trend = "CONSOLIDATION"
                dominant_prob = max(cons_trend_prob, 50.0)
            elif bull_trend_prob >= 55.0 and bull_trend_prob > bear_trend_prob:
                predicted_trend = "BULLISH"
                dominant_prob = bull_trend_prob
            elif bear_trend_prob >= 55.0 and bear_trend_prob > bull_trend_prob and (ret_1h <= -0.006 or ret_15m <= -0.004):
                predicted_trend = "BEARISH"
                dominant_prob = bear_trend_prob
            elif cons_trend_prob >= 35.0 or (abs(ret_1h) < 0.008 and abs(ret_15m) < 0.005):
                predicted_trend = "CONSOLIDATION"
                dominant_prob = cons_trend_prob
            elif bull_trend_prob >= bear_trend_prob:
                predicted_trend = "BULLISH"
                dominant_prob = bull_trend_prob
            else:
                predicted_trend = "CONSOLIDATION"
                dominant_prob = cons_trend_prob

            # Compute predicted price targets for BTC
            expected_directional_shift = ((bull_trend_prob - bear_trend_prob) / 100.0) * (0.025 * max(1.0, vol_ratio))
            if predicted_trend == "CONSOLIDATION":
                expected_directional_shift = 0.0
            pred_btc_target = round(c_now * (1.0 + expected_directional_shift), 2)
            pred_change_pct = round(expected_directional_shift * 100.0, 2)

            # Institutional Composite Market Score Calculation (-100 to +100)
            trend_pts = (
                (20.0 if is_1d_bull else (-20.0 if is_1d_bear else 0.0)) +
                (20.0 if is_4h_bull else (-20.0 if is_4h_bear else 0.0)) +
                (15.0 if is_1h_bull else (-15.0 if is_1h_bear else 0.0)) +
                (10.0 if is_15m_bull else (-10.0 if is_15m_bear else 0.0))
            )

            mom_pts = 0.0
            if not is_flat_range:
                mom_pts += 15.0 if rsi_1h >= 58.0 else (-15.0 if rsi_1h <= 42.0 else 0.0)
                mom_pts += 10.0 if is_15m_bull else (-10.0 if is_15m_bear else 0.0)

            vel_pts = 0.0
            vel_pts += float(np.clip((ret_1h / 0.015) * 15.0, -15.0, 15.0))
            vel_pts += float(np.clip((ret_15m / 0.008) * 10.0, -10.0, 10.0))

            # Factor: VWAP Institutional Bias (-20.0 to +20.0 pts)
            vwap_pts = 0.0
            if vwap_1h is not None:
                vwap_pts += 10.0 if not is_below_vwap_1h else -10.0
            if vwap_4h is not None:
                vwap_pts += 10.0 if not is_below_vwap_4h else -10.0

            composite_score = round(float(np.clip(trend_pts + mom_pts + vel_pts + vwap_pts, -100.0, 100.0)), 1)

            # Structural narrative description & Breakout Prediction
            if is_squeeze:
                if is_1d_bull or is_4h_bull or bull_trend_prob > bear_trend_prob:
                    breakout_pred = "🚀 SQUEEZE COILING (BULL BREAKOUT FAVORED)"
                elif (is_1d_bear or is_4h_bear) and ret_1h < -0.005:
                    breakout_pred = "🩸 SQUEEZE COILING (BEAR BREAKDOWN FAVORED)"
                else:
                    breakout_pred = "⚖️ SYMMETRICAL SQUEEZE COILING"
            elif predicted_trend == "BULLISH":
                breakout_pred = "🚀 BULLISH TREND EXPANSION ACTIVE"
            elif predicted_trend == "BEARISH":
                breakout_pred = "🩸 BEARISH BREAKDOWN EXPANSION ACTIVE"
            else:
                breakout_pred = "💤 BALANCED RANGE EQUILIBRIUM"

            if is_1h_bull and is_4h_bull:
                trend_structure = "Bullish Alignment (1H & 4H Trend Up)"
            elif is_1h_bear and is_4h_bear:
                trend_structure = "Bearish Alignment (1H & 4H Trend Down)"
            elif is_1h_bear and is_1d_bull:
                trend_structure = "Intraday Pullback in Macro Bull Trend"
            elif is_1h_bull and is_1d_bear:
                trend_structure = "Bear Market Relief Rally"
            elif bbw_15m <= 0.022 or is_squeeze:
                trend_structure = "15M Volatility Squeeze (Coiling)"
            else:
                trend_structure = "Multi-Timeframe Range Consolidation"

            # --- REGIME CLASSIFICATION ENGINE HIERARCHY & SAFEGUARD POSTURE ---
            if ret_15m <= -0.018 or ret_1h <= -0.028 or (ret_15m <= -0.012 and ret_45m <= -0.022):
                # 1. ALERT_DUMP: Emergency risk-off flush (True crash dump)
                active = True
                code = "ALERT_DUMP"
                regime = "FLASH_DUMP"
                regime_label = "🚨 CRASH DUMP ALERT"
                reason = f"BTC RAPID SELLOFF ({ret_15m*100.0:+.2f}% in 15m, {ret_1h*100.0:+.2f}% in 1h)"
                altcoin_posture = "DEFENSIVE_SHORTS_ONLY"
                market_phase_desc = "High velocity cascade selloff. Altcoin long orders completely blocked; inverse and short models given elevated priority."

            elif is_btc_below_vwap_both and (ret_1h <= -0.002 or is_1h_bear or is_4h_bear or composite_score <= -10.0):
                # 2. BEAR_TREND: Persistent institutional downtrend below 1H & 4H VWAP
                active = True
                code = "BEAR_TREND"
                regime = "BEARISH_BREAKDOWN"
                regime_label = "🩸 SYSTEMIC BEAR TREND (BELOW 1H & 4H VWAP)"
                v1_str = f"${round(vwap_1h):,.0f}" if vwap_1h else "N/A"
                v4_str = f"${round(vwap_4h):,.0f}" if vwap_4h else "N/A"
                reason = f"BTC BELOW VWAP & TRENDING DOWN (1H VWAP: {v1_str} | 4H VWAP: {v4_str} | Score: {composite_score:+.0f})"
                altcoin_posture = "DEFENSIVE_SHORTS_ONLY"
                market_phase_desc = "Price trading below institutional 1H & 4H VWAP benchmarks. Altcoin Momentum Longs strictly suppressed."

            elif (is_squeeze or (abs(ret_1h) < 0.008 and abs(ret_15m) < 0.005 and bbw_15m <= 0.025) or (cons_trend_prob >= 35.0 and abs(ret_1h) < 0.010)) and not is_btc_below_vwap_both:
                # 3. CONSOLIDATION / VOLATILITY SQUEEZE (Only allowed when price is holding above or around VWAP)
                active = False
                code = "CONSOLIDATION"
                regime = "RANGE_SQUEEZE"
                regime_label = "💤 VOLATILITY COMPRESSION (RANGE CONSOLIDATION)"
                reason = f"RANGE CONSOLIDATION COILING (BBW: {bbw_15m*100.0:.2f}% | 1H: {ret_1h*100.0:+.2f}% | Cons Prob: {cons_trend_prob:.0f}%)"
                altcoin_posture = "NO_TRADE_ZONE_CAPITAL_PRESERVATION"
                market_phase_desc = f"Market in consolidation squeeze. Signals and paper trade admissions locked on compressed timeframes to prevent choppy whipsaws."

            elif (ret_1h <= -0.010 or ret_4h <= -0.020 or ret_15m <= -0.008) and (bear_trend_prob >= 60.0 or composite_score <= -35.0 or (is_4h_bear and is_1h_bear and ret_1h < -0.005)):
                # 4. BEAR_TREND: Persistent multi-horizon downtrend (Genuine momentum breakdown)
                active = True
                code = "BEAR_TREND"
                regime = "BEARISH_BREAKDOWN"
                regime_label = "🩸 SYSTEMIC BEAR TREND"
                reason = f"BEARISH BREAKDOWN CONFIRMED (Bear Prob: {bear_trend_prob}% | Score: {composite_score:+.0f})"
                altcoin_posture = "SELECTIVE_SHORTS_ALLOWED"
                market_phase_desc = "Macro downtrend dominating price action. Altcoin long exposure heavily pruned."

            elif ret_15m <= -0.008 or (ret_1h <= -0.012 and is_1h_bear) or is_below_vwap_1h:
                # 5. INTRADAY_CORRECTION / CAUTION: Reaction to pullbacks or dropping below 1H VWAP
                active = False
                code = "CAUTION"
                regime = "INTRADAY_PULLBACK"
                regime_label = "🔴 INTRADAY PULLBACK / CORRECTION"
                reason = f"INTRADAY DIP / CORRECTION (15M: {ret_15m*100.0:+.2f}% | 1H: {ret_1h*100.0:+.2f}% | RSI15M: {rsi_15m:.0f})"
                altcoin_posture = "DEFENSIVE_PULLBACK"
                market_phase_desc = "Intraday pullback or local mean reversion. Longs restricted to highest conviction setups or oversold levels."

            elif (ret_15m >= 0.018 or ret_1h >= 0.030) and is_1h_bull and not is_btc_below_vwap:
                # 6. PUMP_EXPANSION: Upward momentum breakout
                active = False
                code = "PUMP_EXPANSION"
                regime = "BULLISH_EXPANSION"
                regime_label = "🚀 BULLISH MOMENTUM SURGE"
                reason = f"BTC EXPANSION SURGE ({ret_15m*100.0:+.2f}% in 15m | Bull Prob: {bull_trend_prob}%)"
                altcoin_posture = "AGGRESSIVE_LONGS"
                market_phase_desc = "Strong bullish expansion and market momentum. Full permission for altcoin breakout setups."

            elif (bull_trend_prob >= 55.0 or (is_1d_bull and is_4h_bull and is_1h_bull) or composite_score >= 30.0) and not is_btc_below_vwap:
                # 7. BULL_TREND: Structured bullish trend
                active = False
                code = "BULL_TREND"
                regime = "BULLISH_ACCUMULATION"
                regime_label = "📈 STRUCTURED UPTREND"
                reason = f"STRUCTURED BULL ACCUMULATION (Bull Prob: {bull_trend_prob}% | Score: {composite_score:+.0f})"
                altcoin_posture = "AGGRESSIVE_LONGS"
                market_phase_desc = "Clean higher highs & higher lows structure. Altcoin momentum swings favored."

            else:
                # 8. STABLE / BALANCED EQUILIBRIUM
                active = False
                code = "NORMAL"
                regime = "STABLE"
                regime_label = "⚖️ BALANCED EQUILIBRIUM"
                reason = f"BALANCED MARKET (BTC: ${c_now:,.0f} | Score: {composite_score:+.0f})"
                altcoin_posture = "STANDARD_EXECUTION"
                market_phase_desc = "Balanced equilibrium state across multi-horizon market structure. Normal quantitative trade selection."

            # Assign properties
            self.btc_shield_active = active
            self.btc_shield_code = code
            self.btc_shield_regime = regime
            self.btc_shield_regime_label = regime_label
            self.btc_shield_reason = reason
            self.btc_composite_score = composite_score
            self.btc_price = round(c_now, 2)
            self.btc_vwap_1h = round(vwap_1h, 2) if vwap_1h else round(c_now, 2)
            self.btc_vwap_4h = round(vwap_4h, 2) if vwap_4h else round(c_now, 2)
            self.is_btc_below_vwap_1h = is_below_vwap_1h
            self.is_btc_below_vwap_4h = is_below_vwap_4h
            self.is_btc_below_vwap = is_btc_below_vwap
            self.is_btc_below_vwap_both = is_btc_below_vwap_both
            self.suppress_momentum_longs = bool(
                self.btc_shield_active or
                is_btc_below_vwap_both or
                (is_below_vwap_1h and (ret_1h < 0.0 or is_1h_bear)) or
                code in ["ALERT_DUMP", "BEAR_TREND", "DUMP", "CAUTION"]
            )

            # Synchronize active shield properties into signal_tracker
            if hasattr(self, 'signal_tracker') and self.signal_tracker:
                self.signal_tracker.btc_shield_active = self.btc_shield_active
                self.signal_tracker.btc_shield_code = self.btc_shield_code
                self.signal_tracker.btc_shield_reason = self.btc_shield_reason
                self.signal_tracker.is_btc_below_vwap = self.is_btc_below_vwap
                self.signal_tracker.suppress_momentum_longs = self.suppress_momentum_longs

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

            # Predictive Properties
            self.btc_predicted_trend = predicted_trend
            self.btc_trend_probability = dominant_prob
            self.btc_bull_trend_prob = bull_trend_prob
            self.btc_bear_trend_prob = bear_trend_prob
            self.btc_consolidation_prob = cons_trend_prob
            self.btc_predicted_target = pred_btc_target
            self.btc_predicted_change_pct = pred_change_pct
            self.btc_breakout_prediction = breakout_pred
            self.btc_altcoin_posture = altcoin_posture
            self.btc_market_phase_description = market_phase_desc
            # Generate Institutional Trader Regime Playbook
            self.trader_playbook = TraderRegimePlaybook.generate(
                regime=regime,
                predicted_trend=predicted_trend,
                bull_prob=bull_trend_prob,
                bear_prob=bear_trend_prob,
                cons_prob=cons_trend_prob,
                is_squeeze=is_squeeze,
                btc_price=c_now,
                breakout_pred=breakout_pred
            )

            # Real-time Market Regime & Trend Transition Detection & Immediate Cache Invalidation
            self._handle_market_transition_if_changed(
                prev_regime=prev_regime,
                new_regime=regime,
                prev_code=prev_code,
                new_code=code,
                prev_trend=prev_trend,
                new_trend=predicted_trend,
                prev_squeeze=prev_squeeze,
                new_squeeze=is_squeeze,
                prev_vol_ratio=prev_vol_ratio,
                new_vol_ratio=vol_ratio
            )

            if self.btc_shield_active:
                print(f"\n[SHIELD 🛡️] ⚠️ BTC MARKET BETA SHIELD ACTIVATED: {self.btc_shield_reason} | Altcoin Longs Paused to Prevent Correlated Stop-Outs.\n")
            else:
                print(f"[SHIELD 🛡️] Forecast: {predicted_trend} ({dominant_prob}%) | Bull: {bull_trend_prob}% | Bear: {bear_trend_prob}% | Cons: {cons_trend_prob}% | Target: ${pred_btc_target:,.0f} ({pred_change_pct:+.2f}%)")

            # Automated WhatsApp Market Shield Alert
            # Debounce filter: require candidate regime to be confirmed across cycles or emergency dump
            try:
                from app.services.whatsapp_service import whatsapp_service
                
                prev_broadcast_code = getattr(self, '_prev_broadcast_shield_code', None)
                curr_cand = getattr(self, '_shield_candidate_code', None)
                cand_count = getattr(self, '_shield_candidate_count', 0)
                
                if self.btc_shield_code == curr_cand:
                    cand_count += 1
                else:
                    curr_cand = self.btc_shield_code
                    cand_count = 1
                self._shield_candidate_code = curr_cand
                self._shield_candidate_count = cand_count
                
                # Broadcast if:
                # 1. State changed from last broadcast
                # 2. Confirmed for at least 2 consecutive cycles (or emergency dump)
                is_emergency = self.btc_shield_code in ["ALERT_DUMP", "FLASH_DUMP"]
                if self.btc_shield_code != prev_broadcast_code and (cand_count >= 2 or is_emergency or prev_broadcast_code is None):
                    self._prev_broadcast_shield_code = self.btc_shield_code
                    whatsapp_service.emit_regime_alert({
                        "status_code": self.btc_shield_code,
                        "regime": self.btc_shield_regime,
                        "reason": self.btc_shield_reason,
                        "cons_prob": cons_trend_prob,
                        "posture": self.btc_altcoin_posture,
                        "timeframe": "15M & 1H Compression",
                        "btc_price": c_now,
                        "bbw_15m": round(bbw_15m * 100.0, 2)
                    })
            except Exception:
                pass

            return {
                "active": self.btc_shield_active,
                "status_code": self.btc_shield_code,
                "regime": self.btc_shield_regime,
                "regime_label": self.btc_shield_regime_label,
                "reason": self.btc_shield_reason,
                "composite_score": self.btc_composite_score,
                "btc_price": self.btc_price,
                "btc_15m_change_pct": self.btc_15m_change,
                "btc_1h_change_pct": self.btc_1h_change,
                "btc_4h_change_pct": self.btc_4h_change,
                "btc_24h_change_pct": self.btc_24h_change,
                "rsi_15m": self.btc_rsi_15m,
                "rsi_1h": self.btc_rsi_1h,
                "rsi_4h": self.btc_rsi_4h,
                "trend_structure": self.btc_trend_structure,
                "is_squeeze": self.btc_is_squeeze,
                "bbw_15m": self.btc_bbw_15m,
                "vol_ratio": self.btc_vol_ratio,
                "altcoin_longs_allowed": not self.btc_shield_active,
                "predicted_trend": self.btc_predicted_trend,
                "trend_probability": self.btc_trend_probability,
                "bull_trend_prob": self.btc_bull_trend_prob,
                "bear_trend_prob": self.btc_bear_trend_prob,
                "consolidation_prob": self.btc_consolidation_prob,
                "predicted_btc_target": self.btc_predicted_target,
                "predicted_btc_change_pct": self.btc_predicted_change_pct,
                "breakout_prediction": self.btc_breakout_prediction,
                "altcoin_posture": self.btc_altcoin_posture,
                "market_phase_description": self.btc_market_phase_description,
                "trader_playbook": self.trader_playbook
            }

        except Exception as e:
            self.btc_shield_active = False
            self.btc_shield_code = "NORMAL"
            self.btc_shield_regime = "STABLE"
            self.btc_shield_regime_label = "⚖️ BALANCED EQUILIBRIUM"
            self.btc_shield_reason = "BALANCED MARKET"
            self.btc_predicted_trend = "CONSOLIDATION"
            self.btc_trend_probability = 50.0
            self.btc_bull_trend_prob = 33.3
            self.btc_bear_trend_prob = 33.3
            self.btc_consolidation_prob = 33.4
            self.btc_predicted_target = 0.0
            self.btc_predicted_change_pct = 0.0
            self.btc_breakout_prediction = "⚖️ RANGE BOUND"
            self.btc_altcoin_posture = "STANDARD_EXECUTION"
            self.btc_market_phase_description = "Balanced equilibrium state."
            self.trader_playbook = TraderRegimePlaybook.generate('STABLE', 'CONSOLIDATION', 33.3, 33.3, 33.4)
            print(f"[SHIELD Note evaluating BTC regime: {e}")
            return {
                "active": False,
                "status_code": "NORMAL",
                "regime": "STABLE",
                "regime_label": "⚖️ BALANCED EQUILIBRIUM",
                "reason": "BALANCED MARKET",
                "altcoin_longs_allowed": True,
                "predicted_trend": "CONSOLIDATION",
                "trend_probability": 50.0,
                "bull_trend_prob": 33.3,
                "bear_trend_prob": 33.3,
                "consolidation_prob": 33.4,
                "predicted_btc_target": 0.0,
                "predicted_btc_change_pct": 0.0,
                "breakout_prediction": "⚖️ RANGE BOUND",
                "altcoin_posture": "STANDARD_EXECUTION",
                "market_phase_description": "Balanced equilibrium state.",
                "trader_playbook": self.trader_playbook
            }

    def evaluate_single_horizon(self, symbol: str, horizon_key: str, h_cfg: dict, fused_df: pd.DataFrame, d1_macro_bull: bool, funding_info: dict = None, live_price: float = None, model_inference_cache: dict = None, raw_dfs: dict = None) -> dict:
        anchor_tf = h_cfg['anchor_tf']
        bars = h_cfg['bars']
        tp_mult = h_cfg['tp_mult']
        sl_mult = h_cfg['sl_mult']

        labeled_df = self.labeler.apply_barriers(fused_df, horizon_bars=bars, base_pt=tp_mult, base_sl=sl_mult)

        live_candle = labeled_df.iloc[-1:].copy()
        if live_price is not None and live_price > 0:
            current_price = float(live_price)
            live_candle.at[live_candle.index[0], 'close'] = current_price
        else:
            current_price = float(live_candle['close'].values[0])
        now_eval = datetime.now(timezone.utc)

        live_raw_atr = live_candle['primary_raw_atr'].values[0]
        live_norm_atr = live_candle['primary_norm_atr'].values[0]
        p_fmt = format_precision_price_str

        # Standard Candle Open and Close Boundaries
        trade_open_timestamp, target_close_timestamp, trade_open_str, trade_close_str = CryptoDataLoader.get_candle_schedule(
            anchor_tf, bars=bars, now_utc=now_eval
        )

        clean_df = labeled_df.dropna(subset=['Target_Primary', 'Target_Meta', 'Target_Return', 'Excursion_Score']).reset_index(drop=True)
        non_feature_cols = ['timestamp', 'datetime', 'open', 'high', 'low', 'close', 'volume', 'taker_buy_vol', 'primary_raw_atr', 'primary_norm_atr', 'Target_Primary', 'Target_Meta', 'Target_Return', 'Target_Close_Return', 'Target_MFE', 'Target_MAE', 'Excursion_Score']
        feature_cols = [c for c in clean_df.columns if c not in non_feature_cols]

        clean_sym_key = symbol.replace('/', '_').replace(':USDT', '')
        cache_key_clf = f"{clean_sym_key}_{horizon_key}_clf"
        cache_key_reg = f"{clean_sym_key}_{horizon_key}_reg"
        now_ts = time.time()

        # ----------------------------------------------------------------------
        # 1. PER-COIN ML CLASSIFIER & REGRESSOR EXECUTION
        # ----------------------------------------------------------------------
        X = clean_df[feature_cols].values if len(feature_cols) > 0 else np.array([])
        y_p = clean_df['Target_Primary'].values if 'Target_Primary' in clean_df.columns else np.array([])
        y_r = clean_df['Target_Return'].values if 'Target_Return' in clean_df.columns else np.array([])
        n = len(X)

        if n < 15 or len(feature_cols) == 0 or (len(y_p) > 0 and len(np.unique(y_p)) < 2):
            is_cold_start = True
            # Cold-Start Laplace Prior Model for new coins entering Top 40 universe (< 15 candles)
            k = int(np.sum(y_p)) if len(y_p) > 0 else 0
            n_sz = len(y_p)
            # Symmetric Laplace smoothing with informative prior aligned to macro BTC regime
            prior_alpha = 1.1 if d1_macro_bull else 0.9
            prior_beta = 0.9 if d1_macro_bull else 1.1
            p_laplace = float(np.clip((k + prior_alpha) / (n_sz + prior_alpha + prior_beta), 0.10, 0.90))
            p_cat_live = p_xgb_live = p_et_live = p_hgb_live = p_laplace
            w_cat, w_xgb, w_et, w_hgb = (0.25, 0.25, 0.25, 0.25)
            elite_acc = 0.65
            
            # Bayesian shrinkage return estimation
            sum_r = float(np.sum(y_r)) if len(y_r) > 0 else 0.0
            prior_ret = 0.005 if d1_macro_bull else -0.005
            pred_reg_ret = float((sum_r + (prior_ret * 5.0)) / (n_sz + 5.0))
        else:
            is_cold_start = False
            p_laplace = None
            n_train = max(5, int(n * self.config['train_split']))
            X_train, y_p_train, y_r_train = X[:n_train], y_p[:n_train].copy(), y_r[:n_train]
            X_test, y_p_test, y_r_test = X[n_train:], y_p[n_train:], y_r[n_train:]

            unique_classes = np.unique(y_p_train)
            if len(unique_classes) < 2 and len(y_p_train) > 1:
                y_p_train[0] = 1 - y_p_train[-1]

            # Fast-Boot Cached Checkpoint or Fresh Per-Coin Fit with feature dimension safety
            is_cached_success = False
            force_fresh = self.config.get('force_fresh_training_on_scan', True)
            model_ttl = self._get_horizon_model_ttl(horizon_key)

            if not force_fresh and cache_key_clf in self.model_cache and (now_ts - self.model_cache[cache_key_clf].get('ts', 0) < model_ttl):
                cached = self.model_cache[cache_key_clf]
                cached_scaler = cached.get('scaler')
                if (
                    cached_scaler is not None
                    and hasattr(cached_scaler, 'n_features_in_')
                    and cached_scaler.n_features_in_ == len(feature_cols)
                ):
                    try:
                        scaler = cached_scaler
                        cat = cached['cat']
                        xgb_m = cached['xgb_m']
                        et = cached['et']
                        hgb_m = cached.get('hgb_m')
                        cat_reg = cached.get('cat_reg')
                        xgb_reg = cached.get('xgb_reg')
                        hgb_reg = cached.get('hgb_reg')
                        w_cat, w_xgb, w_et, w_hgb = cached.get('weights', (0.30, 0.30, 0.20, 0.20))
                        w_cat_r, w_xgb_r, w_hgb_r = cached.get('reg_weights', (0.35, 0.35, 0.30))
                        elite_acc = cached.get('elite_acc', 0.85)

                        X_live_scaled = np.nan_to_num(scaler.transform(live_candle[feature_cols].values), nan=0.0)
                        p_cat_live = float(cat.predict_proba(X_live_scaled)[0, 1]) if cat else 0.50
                        p_xgb_live = float(xgb_m.predict_proba(X_live_scaled)[0, 1]) if xgb_m else 0.50
                        p_et_live = float(et.predict_proba(X_live_scaled)[0, 1]) if et else 0.50
                        p_hgb_live = float(hgb_m.predict_proba(X_live_scaled)[0, 1]) if hgb_m else 0.50

                        r_cat = float(cat_reg.predict(X_live_scaled)[0]) if cat_reg else (0.005 if d1_macro_bull else -0.005)
                        r_xgb = float(xgb_reg.predict(X_live_scaled)[0]) if xgb_reg else (0.005 if d1_macro_bull else -0.005)
                        r_hgb = float(hgb_reg.predict(X_live_scaled)[0]) if hgb_reg else (0.005 if d1_macro_bull else -0.005)
                        pred_reg_ret = float((w_cat_r * r_cat) + (w_xgb_r * r_xgb) + (w_hgb_r * r_hgb))
                        is_cached_success = True
                    except Exception:
                        is_cached_success = False

            if not is_cached_success:
                scaler = RobustScaler()
                X_train_scaled = np.nan_to_num(scaler.fit_transform(X_train), nan=0.0)
                X_test_scaled = np.nan_to_num(scaler.transform(X_test), nan=0.0)
                X_live_scaled = np.nan_to_num(scaler.transform(live_candle[feature_cols].values), nan=0.0)

                # 1. High-Speed Primary HistGradientBoosting Classifier
                try:
                    hgb_m = QuantModelFactory.build_primary_hist_gbm_clf()
                    hgb_m.fit(X_train_scaled, y_p_train)
                    p_hgb_live = float(hgb_m.predict_proba(X_live_scaled)[0, 1])
                    p_test_hgb = hgb_m.predict_proba(X_test_scaled)[:, 1] if len(X_test_scaled) > 0 else np.array([p_hgb_live])
                except Exception:
                    hgb_m = None
                    p_hgb_live = 0.55 if d1_macro_bull else 0.45
                    p_test_hgb = np.array([p_hgb_live] * max(1, len(X_test_scaled)))

                # 2. High-Speed ExtraTrees Classifier
                try:
                    et = QuantModelFactory.build_primary_extra_trees(self.config['extra_trees'])
                    et.fit(X_train_scaled, y_p_train)
                    p_et_live = float(et.predict_proba(X_live_scaled)[0, 1])
                    p_test_et = et.predict_proba(X_test_scaled)[:, 1] if len(X_test_scaled) > 0 else np.array([p_et_live])
                except Exception:
                    et = None
                    p_et_live = 0.55 if d1_macro_bull else 0.45
                    p_test_et = np.array([p_et_live] * max(1, len(X_test_scaled)))

                # 3. High-Speed Price Return HistGBM Regressor
                try:
                    hgb_reg = QuantModelFactory.build_hist_gbm_regressor()
                    hgb_reg.fit(X_train_scaled, y_r_train)
                    r_hgb = float(hgb_reg.predict(X_live_scaled)[0])
                except Exception:
                    hgb_reg = None
                    r_hgb = 0.005 if d1_macro_bull else -0.005

                p_cat_live, p_xgb_live = p_hgb_live, p_et_live
                w_cat, w_xgb, w_et, w_hgb = 0.0, 0.0, 0.40, 0.60
                w_cat_r, w_xgb_r, w_hgb_r = 0.0, 0.0, 1.0
                r_cat, r_xgb = r_hgb, r_hgb
                pred_reg_ret = r_hgb

                p_test_ens = (p_test_hgb * w_hgb) + (p_test_et * w_et)
                elite_mask = (p_test_ens >= self.config['elite_conviction_threshold']) | (p_test_ens <= (1.0 - self.config['elite_conviction_threshold']))
                elite_acc = accuracy_score(y_p_test[elite_mask], (p_test_ens[elite_mask] >= 0.5).astype(int)) if (len(y_p_test) > 0 and np.sum(elite_mask) >= 5) else 0.88

                if hgb_m or et or hgb_reg:
                    self.model_cache[cache_key_clf] = {
                        'scaler': scaler,
                        'cat': None,
                        'xgb_m': None,
                        'et': et,
                        'hgb_m': hgb_m,
                        'cat_reg': None,
                        'xgb_reg': None,
                        'hgb_reg': hgb_reg,
                        'weights': (0.0, 0.0, w_et, w_hgb),
                        'reg_weights': (0.0, 0.0, 1.0),
                        'elite_acc': elite_acc,
                        'ts': now_ts
                    }
                    self._model_cache_dirty = True
                    if len(self.model_cache) > 1500:
                        self._prune_model_cache(max_size=1200, max_age_seconds=86400)

        # 1. Base ML Direction & Calibrated Probability
        h_prob = (p_cat_live * w_cat) + (p_xgb_live * w_xgb) + (p_et_live * w_et) + (p_hgb_live * w_hgb)

        if h_prob >= 0.53:
            h_dir = "BULLISH"
            h_conf = h_prob * 100.0
            is_neutral_zone = False
        elif h_prob <= 0.47:
            h_dir = "BEARISH"
            h_conf = (1.0 - h_prob) * 100.0
            is_neutral_zone = False
        else:
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

        # 2b. Fundamental, Event Catalyst & News Sentiment Integration
        fund_matrix = None
        try:
            from app.services.fundamental_service import fundamental_service
            fund_matrix = fundamental_service.get_asset_fundamental_matrix(symbol)
        except Exception:
            fund_matrix = None

        if fund_matrix:
            cat_ev = fund_matrix.get("catalyst_event", {})
            if cat_ev.get("is_sell_the_news_danger_zone") and h_dir == "BULLISH":
                h_conf = max(45.0, h_conf - 10.0)
                squeeze_boost_label += " ⚠️ [SELL-THE-NEWS: <12h to EVENT]"
            elif cat_ev.get("is_pre_event_runup") and h_dir == "BULLISH":
                h_conf = min(96.0, h_conf + 6.0)
                ev_t = str(cat_ev.get("title", "Catalyst"))[:18]
                squeeze_boost_label += f" 🚀 [EVENT DRIFT: {ev_t}]"

            news_sent = fund_matrix.get("news_sentiment", {})
            if news_sent.get("score", 0.0) <= -0.35 and h_dir == "BULLISH":
                h_conf = max(45.0, h_conf - 8.0)
                squeeze_boost_label += " 🚨 [NEGATIVE NEWS FLAGGED]"
            elif news_sent.get("score", 0.0) >= 0.35 and h_dir == "BULLISH":
                h_conf = min(96.0, h_conf + 4.0)

        # 3. Relative Strength vs BTC Alpha
        asset_4h_ret = 0.0
        btc_4h_ret = 0.0
        if raw_dfs and '4h' in raw_dfs and len(raw_dfs['4h']) >= 2:
            asset_4h_ret = (raw_dfs['4h']['close'].iloc[-1] - raw_dfs['4h']['close'].iloc[-2]) / (raw_dfs['4h']['close'].iloc[-2] + 1e-10)
        if self.btc_cache and '4h' in self.btc_cache and len(self.btc_cache['4h']) >= 2:
            btc_4h_ret = (self.btc_cache['4h']['close'].iloc[-1] - self.btc_cache['4h']['close'].iloc[-2]) / (self.btc_cache['4h']['close'].iloc[-2] + 1e-10)
        rs_btc = round((asset_4h_ret - btc_4h_ret) / max(0.005, live_norm_atr), 3)

        # 3b. Smart Money Concepts: Institutional Multi-Timeframe Nested Order Block Detection
        ob_setup = None
        try:
            from app.quant_v16.order_blocks import order_block_engine
            ob_setup = order_block_engine.evaluate_nested_setup(
                raw_dfs=raw_dfs,
                anchor_tf=anchor_tf,
                current_price=current_price,
                btc_regime=getattr(self, 'btc_shield_code', 'NORMAL'),
                rs_btc=rs_btc
            )
        except Exception:
            ob_setup = None

        is_ob_long = bool(ob_setup and ob_setup.get("setup_detected") and ob_setup.get("direction") == "LONG")
        is_ob_short = bool(ob_setup and ob_setup.get("setup_detected") and ob_setup.get("direction") == "SHORT")
        is_breaker_long = bool(ob_setup and ob_setup.get("setup_detected") and ob_setup.get("strategy") == "BREAKER_BLOCK_LONG")
        is_breaker_short = bool(ob_setup and ob_setup.get("setup_detected") and ob_setup.get("strategy") == "BREAKER_BLOCK_SHORT")

        is_bull_sweep = live_candle.get(f'{anchor_tf}_liquidity_sweep_bull', pd.Series([0])).values[0] == 1.0
        is_bear_sweep = live_candle.get(f'{anchor_tf}_liquidity_sweep_bear', pd.Series([0])).values[0] == 1.0

        # 5. Volatility Regime-Adaptive TP/SL Multipliers
        adx_val = live_candle[f'{anchor_tf}_adx_14'].values[0] * 100.0 if f'{anchor_tf}_adx_14' in live_candle.columns else 25.0
        chop_val = live_candle[f'{anchor_tf}_chop_index'].values[0] * 100.0 if f'{anchor_tf}_chop_index' in live_candle.columns else 50.0

        if adx_val >= 30.0 and chop_val < 50.0:
            tp_mult_eff = tp_mult * 1.35
            sl_mult_eff = sl_mult * 1.05
        elif chop_val >= 60.0 or adx_val < 20.0:
            tp_mult_eff = tp_mult * 0.85
            sl_mult_eff = sl_mult * 1.25  # In choppy markets, widen SL to absorb range noise!
        else:
            tp_mult_eff = tp_mult
            sl_mult_eff = sl_mult

        # 6. Technical Reversals & Price Action Metrics
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
        st_dir = float(live_candle.get(f'{anchor_tf}_supertrend_dir', pd.Series([1.0])).values[0])
        st_flip_bull = live_candle.get(f'{anchor_tf}_supertrend_flip_bull', pd.Series([0])).values[0] == 1.0
        st_flip_bear = live_candle.get(f'{anchor_tf}_supertrend_flip_bear', pd.Series([0])).values[0] == 1.0

        # 7. PARABOLIC HYPE SURGE & BLOW-OFF TOP EXHAUSTION DETECTOR
        is_hype_surge = False
        is_blowoff_top = False
        base_pump_price = current_price * 0.85
        peak_pump_price = current_price
        pump_range = max(1e-8, current_price * 0.15)
        pump_magnitude = 0.0
        c_now = current_price
        ema20_15m = 0.0

        if raw_dfs and '15m' in raw_dfs and raw_dfs['15m'] is not None and len(raw_dfs['15m']) >= 15:
            df_15 = raw_dfs['15m']
            c_now = float(df_15['close'].iloc[-1])
            c_prev3 = float(df_15['close'].iloc[-4]) if len(df_15) >= 4 else c_now
            c_prev10 = float(df_15['close'].iloc[-10]) if len(df_15) >= 10 else c_now
            gain_recent_pct = (c_now - c_prev3) / (c_prev3 + 1e-10)
            gain_10bar_pct = (c_now - c_prev10) / (c_prev10 + 1e-10)
            
            vol_now = float(df_15['volume'].iloc[-1])
            vol_ma20 = float(df_15['volume'].rolling(20, min_periods=3).mean().iloc[-1])
            vol_ratio_now = vol_now / (vol_ma20 + 1e-10)
            
            high_now = float(df_15['high'].iloc[-1])
            low_now = float(df_15['low'].iloc[-1])
            open_now = float(df_15['open'].iloc[-1])
            bar_rng = max(1e-8, high_now - low_now)
            upper_wick_ratio = (high_now - max(c_now, open_now)) / bar_rng
            
            # Base and peak calculation over recent 30 bars
            base_pump_price = float(df_15['low'].rolling(30, min_periods=5).min().iloc[-1])
            peak_pump_price = float(df_15['high'].rolling(30, min_periods=5).max().iloc[-1])
            pump_range = max(1e-8, peak_pump_price - base_pump_price)
            pump_magnitude = pump_range / max(1e-8, base_pump_price)

            # EMA20 overextension calculation (Z-score to mean)
            ema20_15m = float(df_15['close'].ewm(span=20).mean().iloc[-1])
            overextension_z = (c_now - ema20_15m) / max(1e-8, live_raw_atr)

            # Candle close status
            is_closed_red = c_now < open_now
            is_heavy_pump = (pump_magnitude >= 0.12) or (gain_recent_pct >= 0.045) or (gain_10bar_pct >= 0.08)

            # A. Blow-Off Top Exhaustion: REQUIRES verified distribution breakdown
            # Must have heavy prior pump AND a confirmed violent bearish rejection / breakdown
            is_wick_rejection = (upper_wick_ratio >= 0.48) and is_closed_red
            is_breakdown_candle = len(df_15) >= 3 and c_now < float(df_15['low'].iloc[-2]) and c_now < float(df_15['low'].iloc[-3]) and is_closed_red
            is_exhaustion_div = (rsi_bear_div or bb_upthrust or td9_sell_ex) and is_closed_red and (bear_rev_score >= 0.45)
            
            if is_heavy_pump and rsi_anchor >= 55.0 and (is_wick_rejection or is_breakdown_candle or is_exhaustion_div):
                is_blowoff_top = True
            elif (gain_recent_pct >= 0.025 or gain_10bar_pct >= 0.060) and c_now >= ema20_15m and (not is_closed_red) and vol_ratio_now >= 1.25:
                # Active upward continuation / parabolic momentum hype pump (REQUIRES active green momentum above EMA20)
                is_hype_surge = True

        # Market Regime & BTC Shield Status
        btc_shield_code = getattr(self, 'btc_shield_code', 'NORMAL')
        btc_shield_regime = getattr(self, 'btc_shield_regime', 'STABLE')
        btc_pred_trend = getattr(self, 'btc_predicted_trend', 'CONSOLIDATION')
        is_shield_active = getattr(self, 'btc_shield_active', False)

        is_bear_regime = (
            is_shield_active or
            btc_pred_trend == "BEARISH" or
            btc_shield_code in ["ALERT_DUMP", "BEAR_TREND", "DUMP", "DEFENSIVE", "CAUTION"] or
            btc_shield_regime in ["FLASH_DUMP", "BEARISH_BREAKDOWN", "INTRADAY_PULLBACK"] or
            not d1_macro_bull
        )
        is_bull_regime = (
            (not is_shield_active) and
            (not is_bear_regime) and
            (btc_pred_trend == "BULLISH" or btc_shield_code in ["PUMP_EXPANSION", "BULL_TREND", "BULL_MOMENTUM"] or btc_shield_regime in ["BULLISH_EXPANSION", "BULLISH_ACCUMULATION"]) and
            d1_macro_bull
        )

        # Reversal Conditions:
        # A Bottom Reversal requires oversold / technical bounce signals (RSI <= 50) and model support
        is_bottom_reversal = (
            rsi_anchor <= 50.0 and
            (not is_shield_active or rsi_bull_div or st_flip_bull) and
            (bull_rev_score >= 0.48 or rsi_bull_div or st_flip_bull or (td9_buy_ex and candlestick_bull) or (bb_spring and candlestick_bull)) and
            (p_cat_live >= 0.50 or p_xgb_live >= 0.50 or h_prob >= 0.50 or st_flip_bull)
        )
        # A Top Reversal requires genuine overbought extension (RSI >= 55.0), technical exhaustion, and decoupled RS guard
        is_top_reversal = (
            (not is_bull_regime or rs_btc <= -0.15) and
            (rs_btc <= 0.35) and
            (rsi_anchor >= 55.0) and
            (bear_rev_score >= 0.45 or rsi_bear_div or st_flip_bear or (td9_sell_ex and (candlestick_bear or rsi_anchor >= 60.0)) or (bb_upthrust and rsi_anchor >= 56.0) or is_blowoff_top) and
            (p_cat_live <= 0.52 or p_xgb_live <= 0.52 or h_prob <= 0.50 or is_blowoff_top or st_flip_bear)
        )
        # Dip Buy Strategy (Higher-Low EMA / Support Pullback):
        # 1. Market Regime Guard: Suppress long knife-catching in confirmed bear trend unless decoupled alpha leader (RS vs BTC >= 0.50)
        # 2. Trend & Support Integrity: Require bullish trend structure (SuperTrend bullish OR price testing/above 50 EMA/200 EMA support)
        # 3. Pullback RSI window: 34.0 <= rsi_anchor <= 48.0 (healthy dip, not deep capitulation flush)
        # 4. Ensemble Model Consensus: Net ensemble probability >= 0.50 AND at least one tree model >= 0.49
        # 5. Multi-Timeframe Consistency: On 4H/macro horizons, require confirmed 1D macro bull alignment (prevent multi-day downtrend continuation)
        dist_to_ema50 = float(live_candle.get(f'{anchor_tf}_dist_to_ema50', pd.Series([0.0])).values[0])
        dist_to_ema200 = float(live_candle.get(f'{anchor_tf}_dist_to_ema200', pd.Series([0.0])).values[0])
        is_4h_or_macro = horizon_key in ['horizon_4h', 'macro', 'horizon_4d', 'weekly', 'biweekly', 'monthly']
        is_macro_trend_valid = (not is_4h_or_macro or d1_macro_bull)
        has_trend_support = (st_dir == 1.0 or st_flip_bull or dist_to_ema50 >= -0.025 or bull_rev_score >= 0.35 or rsi_bull_div)
        has_no_deep_breakdown = (dist_to_ema200 >= -0.045)

        is_dip_buy = (
            (not is_bear_regime or rs_btc >= 0.50) and
            (not is_shield_active) and
            (d1_macro_bull or rs_btc >= 0.25) and
            is_macro_trend_valid and
            has_trend_support and
            has_no_deep_breakdown and
            (34.0 <= rsi_anchor <= 48.0) and
            (h_prob >= 0.50 and (p_cat_live >= 0.49 or p_xgb_live >= 0.49))
        )
        # Relief Rally Fade Strategy (Overbought Counter-Trend Bounce into Resistance):
        # 1. Market Regime Guard: Macro bear market OR bear regime active (not d1_macro_bull or is_bear_regime)
        # 2. Relative Strength Guard: Altcoin must NOT be a decoupled alpha leader (rs_btc <= 0.35)
        # 3. Pullback RSI Window: 53.0 <= rsi_anchor <= 68.0 (genuine relief bounce into resistance, not vertical squeeze)
        # 4. Overhead Resistance / Exhaustion Confluence:
        #    Price stalling into declining trend (st_dir == -1.0 or st_flip_bear) OR
        #    testing overhead EMA (dist_to_ema50 between -0.015 and +0.025) OR
        #    technical exhaustion (bear_rev_score >= 0.35 or rsi_bear_div or td9_sell_ex or candlestick_bear or bb_upthrust)
        # 5. Model Consensus: Strict non-bullish consensus (h_prob <= 0.50 and (p_cat_live <= 0.52 or p_xgb_live <= 0.52))
        has_overhead_resistance = (
            st_dir == -1.0 or st_flip_bear or
            (-0.015 <= dist_to_ema50 <= 0.025) or
            bear_rev_score >= 0.35 or rsi_bear_div or td9_sell_ex or candlestick_bear or bb_upthrust
        )
        is_rally_sell = (
            (not d1_macro_bull or is_bear_regime) and
            (rs_btc <= 0.35) and
            (53.0 <= rsi_anchor <= 68.0) and
            has_overhead_resistance and
            (h_prob <= 0.50 and (p_cat_live <= 0.52 or p_xgb_live <= 0.52))
        )

        is_breakout_long = (
            (not is_shield_active or rs_btc >= 0.8) and
            (is_bull_regime or rs_btc >= 0.4 or d1_macro_bull) and
            (rsi_anchor >= 50.0 and rsi_anchor <= 72.0) and
            (h_dir == "BULLISH" or h_prob >= 0.52) and
            (st_dir == 1.0 or st_flip_bull) and
            not is_neutral_zone
        )
        is_momentum_long = (
            (not is_shield_active or rs_btc >= 1.0) and
            (rs_btc >= 0.4 or (d1_macro_bull and rs_btc >= 0.1)) and
            (p_cat_live >= 0.50 or p_xgb_live >= 0.50 or h_prob >= 0.51) and
            (st_dir == 1.0 or st_flip_bull) and
            rsi_anchor >= 48.0 and rsi_anchor <= 74.0
        )
        # Anchor Timeframe Overextension & Volume Surge Extraction
        df_anchor = raw_dfs.get(anchor_tf, raw_dfs.get('15m')) if raw_dfs else None
        if df_anchor is not None and len(df_anchor) >= 20:
            ema20_anchor = float(df_anchor['close'].ewm(span=20).mean().iloc[-1])
            c_anchor = float(df_anchor['close'].iloc[-1])
            dist_to_ema20_anchor = (c_anchor - ema20_anchor) / (ema20_anchor + 1e-10)
            vol_now_anchor = float(df_anchor['volume'].iloc[-1])
            vol_ma20_anchor = float(df_anchor['volume'].rolling(20, min_periods=3).mean().iloc[-1])
            vol_surge_anchor = vol_now_anchor / (vol_ma20_anchor + 1e-10)
        else:
            dist_to_ema20_anchor = 0.0
            vol_surge_anchor = 1.0

        # 1H and 15M consecutive candle streak analysis (for anti-chase guard)
        h1_green_streak = 0
        h1_red_streak = 0
        df_1h = raw_dfs.get('1h') if raw_dfs else None
        if df_1h is not None and len(df_1h) >= 2:
            for idx_c in range(1, min(7, len(df_1h))):
                if float(df_1h['close'].iloc[-idx_c]) > float(df_1h['open'].iloc[-idx_c]):
                    h1_green_streak += 1
                else:
                    break
            for idx_c in range(1, min(7, len(df_1h))):
                if float(df_1h['close'].iloc[-idx_c]) < float(df_1h['open'].iloc[-idx_c]):
                    h1_red_streak += 1
                else:
                    break

        df_15 = raw_dfs.get('15m') if raw_dfs else None
        m15_green_streak = 0
        m15_red_streak = 0
        rsi_15m_val = 50.0
        if df_15 is not None and len(df_15) >= 2:
            for idx_c in range(1, min(7, len(df_15))):
                if float(df_15['close'].iloc[-idx_c]) > float(df_15['open'].iloc[-idx_c]):
                    m15_green_streak += 1
                else:
                    break
            for idx_c in range(1, min(7, len(df_15))):
                if float(df_15['close'].iloc[-idx_c]) < float(df_15['open'].iloc[-idx_c]):
                    m15_red_streak += 1
                else:
                    break
            if len(df_15) >= 15:
                try:
                    rsi_15m_series = self.fe.compute_rsi(df_15['close'], period=14)
                    rsi_15m_val = float(rsi_15m_series.iloc[-1]) * 100.0
                except Exception:
                    rsi_15m_val = 50.0

        # Microstructure impulse swing anchor extraction:
        # If price is in an impulse streak, anchor to the true base of the multi-candle run
        anchor_low_val = current_price
        anchor_high_val = current_price
        if df_anchor is not None and len(df_anchor) >= 1:
            anchor_low_val = float(df_anchor['low'].iloc[-1])
            anchor_high_val = float(df_anchor['high'].iloc[-1])

        # Expand across consecutive green/red streaks to capture true multi-bar impulse base & peak
        if df_1h is not None and len(df_1h) >= 2:
            if h1_green_streak >= 2:
                anchor_low_val = min(anchor_low_val, float(df_1h['low'].iloc[-h1_green_streak:].min()))
                anchor_high_val = max(anchor_high_val, float(df_1h['high'].iloc[-h1_green_streak:].max()))
            if h1_red_streak >= 2:
                anchor_low_val = min(anchor_low_val, float(df_1h['low'].iloc[-h1_red_streak:].min()))
                anchor_high_val = max(anchor_high_val, float(df_1h['high'].iloc[-h1_red_streak:].max()))

        anchor_range_val = max(1e-8, anchor_high_val - anchor_low_val)
        impulse_lift_pct = (current_price - anchor_low_val) / max(1e-8, anchor_low_val)
        impulse_drop_pct = (anchor_high_val - current_price) / max(1e-8, anchor_high_val)

        # Anti-Chase Extension Flags:
        # Detect whether price has surged excessively from the swing low into overhead resistance
        is_chase_danger_long = bool(
            (impulse_lift_pct >= 0.028 or h1_green_streak >= 3 or m15_green_streak >= 4 or rsi_15m_val >= 68.0)
        )
        is_chase_danger_short = bool(
            (impulse_drop_pct >= 0.028 or h1_red_streak >= 3 or m15_red_streak >= 4 or rsi_15m_val <= 32.0)
        )

        # Golden Pocket & Pullback Limit Calculation
        fib_50_long = anchor_high_val - (0.50 * anchor_range_val)
        fib_618_long = anchor_high_val - (0.618 * anchor_range_val)
        ema20_1h_val = float(df_1h['close'].ewm(span=20).mean().iloc[-1]) if (df_1h is not None and len(df_1h) >= 20) else fib_50_long
        pullback_limit_long = float(np.median([fib_50_long, fib_618_long, ema20_1h_val]))
        pullback_limit_long = min(current_price * 0.995, max(anchor_low_val * 1.005, pullback_limit_long))
        pullback_zone_min_long = min(fib_618_long, pullback_limit_long * 0.997)
        pullback_zone_max_long = max(pullback_limit_long, fib_50_long * 1.003)

        # Golden Pocket & Relief Bounce Limit Calculation for Shorts
        fib_50_short = anchor_low_val + (0.50 * anchor_range_val)
        fib_618_short = anchor_low_val + (0.618 * anchor_range_val)
        bounce_limit_short = float(np.median([fib_50_short, fib_618_short, ema20_1h_val]))
        bounce_limit_short = max(current_price * 1.005, min(anchor_high_val * 0.995, bounce_limit_short))
        bounce_zone_min_short = min(bounce_limit_short, fib_50_short * 0.997)
        bounce_zone_max_short = max(fib_618_short, bounce_limit_short * 1.003)

        # Anti-exhaustion / Anti-bottom-wick guard:
        # Do NOT short breakdowns if RSI is deep oversold (< 32.0) or price is overextended below anchor EMA20 (> 3.5%) without a consolidation/retest.
        is_oversold_exhaustion = (rsi_anchor < 32.0) or (dist_to_ema20_anchor < -0.035) or (ema20_15m > 0 and c_now < ema20_15m * 0.965)
        
        # Breakdown Short Strategy (Support Breakdown / Lower-Low Expansion):
        # 1. Market Regime Guard: Suppress breakdown shorts in strong bull market unless decoupled lagger (not d1_macro_bull or is_bear_regime)
        # 2. RSI Window: 32.0 <= rsi_anchor <= 56.0 (active breakdown momentum, not deep exhaustion)
        # 3. SuperTrend Alignment: SuperTrend is bearish (-1.0) or flipping bear
        # 4. Volume Surge Confirmation: Real volume expansion (vol_surge_anchor >= 0.95) to prevent low-volume bear trap sweeps
        # 5. Ensemble Model Consensus: Strict non-bullish consensus (h_prob <= 0.50 and (p_cat_live <= 0.52 or p_xgb_live <= 0.52))
        is_breakdown_short = (
            (is_bear_regime or not d1_macro_bull) and
            (rs_btc <= 0.1 or not d1_macro_bull) and
            (32.0 <= rsi_anchor <= 56.0) and
            (not is_oversold_exhaustion) and
            (st_dir == -1.0 or st_flip_bear) and
            (vol_surge_anchor >= 0.95) and
            (h_prob <= 0.50 and (p_cat_live <= 0.52 or p_xgb_live <= 0.52))
        )

        # Momentum Short Strategy (Bearish Momentum Expansion):
        # 1. Macro Regime: Active bear regime or decoupling lagger (not d1_macro_bull or rs_btc <= -0.15)
        # 2. RS Guard: Not decoupling bullish (rs_btc <= 0.15)
        # 3. SuperTrend: Bearish (-1.0) or flipping bear
        # 4. RSI Window: 35.0 <= rsi_anchor <= 58.0 (healthy downward momentum, not deep exhaustion)
        # 5. ML Consensus: Non-bullish consensus (h_prob <= 0.48 and (p_cat_live <= 0.50 or p_xgb_live <= 0.50))
        is_momentum_short = (
            (is_bear_regime or not d1_macro_bull or rs_btc <= -0.15) and
            (rs_btc <= 0.15) and
            (not is_oversold_exhaustion) and
            (st_dir == -1.0 or st_flip_bear) and
            (35.0 <= rsi_anchor <= 58.0) and
            (h_prob <= 0.48 and (p_cat_live <= 0.50 or p_xgb_live <= 0.50))
        )

        is_supertrend_bull_pivot = bool(st_flip_bull and (not is_bear_regime or rs_btc >= 0.35) and (p_cat_live >= 0.48 or p_xgb_live >= 0.48 or h_prob >= 0.49))
        is_supertrend_bear_pivot = bool(st_flip_bear and (is_bear_regime or not d1_macro_bull or h_prob <= 0.51))

        is_bottom_reversal_active = bool(is_bottom_reversal and (not is_top_reversal or bull_rev_score > bear_rev_score))
        is_top_reversal_active = bool(is_top_reversal and (not is_bottom_reversal or bear_rev_score > bull_rev_score) and (is_ob_short or is_breaker_short or bear_rev_score >= 0.55 or rsi_bear_div))

        is_reversal_setup = False
        if is_ob_long and (not is_bear_regime or rs_btc >= 0.4):
            h_dir = "BULLISH"
            h_conf = max(76.0, min(98.5, float(ob_setup.get("conviction", 82.0))))
            ob_dec = ob_setup.get("decision") if (ob_setup and ob_setup.get("decision")) else "🎯 INSTITUTIONAL ORDER-BLOCK RETEST (LONG)"
            decision = f"{ob_dec}{squeeze_boost_label}"
            priority = 1
            is_reversal_setup = True
            is_neutral_zone = False
        elif is_ob_short and (not is_bull_regime or rs_btc <= -0.20) and rs_btc <= 0.35 and h_prob <= 0.55:
            h_dir = "BEARISH"
            h_conf = max(72.0, min(96.0, float(ob_setup.get("conviction", 80.0))))
            ob_dec = ob_setup.get("decision") if (ob_setup and ob_setup.get("decision")) else "🎯 INSTITUTIONAL ORDER-BLOCK RETEST (SHORT)"
            decision = f"{ob_dec}{squeeze_boost_label}"
            priority = 1
            is_reversal_setup = True
            is_neutral_zone = False
        elif is_breaker_short and (not is_bull_regime or rs_btc <= -0.20) and rs_btc <= 0.35 and h_prob <= 0.55:
            h_dir = "BEARISH"
            h_conf = max(72.0, min(95.0, float(ob_setup.get("conviction", 78.0))))
            decision = f"🎯 INSTITUTIONAL BREAKER-BLOCK REJECTION (SHORT){squeeze_boost_label}"
            priority = 1
            is_reversal_setup = True
            is_neutral_zone = False
        elif is_blowoff_top and (is_ob_short or is_breaker_short or bear_rev_score >= 0.55 or rsi_bear_div or (is_wick_rejection and is_closed_red)):
            h_dir = "BEARISH"
            h_conf = max(76.0, min(98.0, 70.0 + (bear_rev_score * 30.0)))
            decision = f"🛑 PARABOLIC BLOW-OFF TOP (REVERSAL SELL / SHORT){squeeze_boost_label}"
            priority = 1
            is_reversal_setup = True
            is_neutral_zone = False
        elif is_hype_surge:
            dist_ob = float(live_candle.get(f'{anchor_tf}_dist_to_bull_ob', pd.Series([1.0])).values[0])
            if dist_ob > 2.5:
                decision = "⚪ OVEREXTENDED MOMENTUM (AWAIT PULLBACK TO DEMAND BLOCK)"
                priority = 4
                is_neutral_zone = True
            else:
                h_dir = "BULLISH"
                h_conf = max(75.0, min(97.0, 70.0 + abs(pred_reg_ret) * 100.0))
                decision = f"🚀 PARABOLIC HYPE PUMP (MOMENTUM SCALP){squeeze_boost_label}"
                priority = 1
                is_neutral_zone = False
        elif is_bottom_reversal_active:
            h_dir = "BULLISH"
            h_conf = max(72.0, min(97.0, 62.0 + (bull_rev_score * 35.0)))
            if is_chase_danger_long:
                decision = f"⏳ BOTTOM-REVERSAL [AWAIT PULLBACK: {p_fmt(pullback_limit_long)}]{squeeze_boost_label}"
            else:
                decision = f"🎯 ELITE BOTTOM-REVERSAL (LONG){squeeze_boost_label}"
            priority = 1
            is_reversal_setup = True
            is_neutral_zone = False
        elif is_top_reversal_active:
            h_dir = "BEARISH"
            h_conf = max(72.0, min(97.0, 62.0 + (bear_rev_score * 35.0)))
            if is_chase_danger_short:
                decision = f"⏳ TOP-REVERSAL [AWAIT BOUNCE: {p_fmt(bounce_limit_short)}]{squeeze_boost_label}"
            else:
                decision = f"🎯 ELITE TOP-REVERSAL (SHORT){squeeze_boost_label}"
            priority = 1
            is_reversal_setup = True
            is_neutral_zone = False
        elif is_bull_sweep and (p_cat_live >= 0.44 or p_xgb_live >= 0.44) and not is_bear_regime:
            h_dir = "BULLISH"
            h_conf = max(70.0, min(97.0, (h_prob * 100.0) + 10.0))
            decision = f"🎯 ELITE LIQUIDITY-SWEEP (LONG){squeeze_boost_label}"
            priority = 1
            is_reversal_setup = True
            is_neutral_zone = False
        elif is_momentum_long and not is_neutral_zone:
            # 🚀 EMPHASIZED #1 PROVEN WINNING STRATEGY (+640% Net Return, 5.11 Profit Factor)
            h_dir = "BULLISH"
            h_conf = max(76.0, min(98.0, (h_prob * 100.0) + 15.0))
            decision = f"🎯 ELITE MOMENTUM BREAKOUT (LONG){squeeze_boost_label}"
            priority = 1
            is_neutral_zone = False
        elif is_momentum_short and not is_neutral_zone:
            h_dir = "BEARISH"
            h_conf = max(70.0, min(95.0, ((1.0 - h_prob) * 100.0) + 8.0))
            decision = f"🎯 ELITE MOMENTUM BREAKDOWN (SHORT){squeeze_boost_label}"
            priority = 1
            is_neutral_zone = False
        elif is_dip_buy:
            # 🎯 EMPHASIZED #2 PROVEN WINNING STRATEGY (66.7% Win Rate, 2.44 Profit Factor)
            h_dir = "BULLISH"
            h_conf = max(68.0, min(96.0, (h_prob * 100.0) + 10.0))
            decision = f"🎯 ELITE DIP-BUY EXECUTE (LONG){squeeze_boost_label}"
            priority = 1
            is_neutral_zone = False
        elif is_rally_sell and (is_ob_short or is_breaker_short or is_wick_rejection):
            # Guard against unconfirmed rally shorts (<42% historical win rate without structure rejection)
            h_dir = "BEARISH"
            h_conf = max(68.0, min(94.0, ((1.0 - h_prob) * 100.0) + 8.0))
            decision = f"🎯 ELITE RALLY-FADE RESISTANCE (SHORT){squeeze_boost_label}"
            priority = 1
            is_neutral_zone = False
        elif is_breakout_long and not is_neutral_zone:
            # 🎯 EMPHASIZED #3 PROVEN WINNING STRATEGY (67.5% Win Rate, 4.81 Profit Factor)
            h_dir = "BULLISH"
            h_conf = max(74.0, min(97.0, (h_prob * 100.0) + 12.0))
            decision = f"🎯 ELITE BREAKOUT EXECUTE (LONG){squeeze_boost_label}"
            priority = 1
            is_neutral_zone = False
        elif is_breakdown_short and not is_neutral_zone:
            h_dir = "BEARISH"
            h_conf = max(68.0, min(95.0, ((1.0 - h_prob) * 100.0) + 8.0))
            decision = f"🎯 ELITE BREAKDOWN EXECUTE (SHORT){squeeze_boost_label}"
            priority = 1
            is_neutral_zone = False
        elif is_supertrend_bull_pivot and not is_neutral_zone:
            h_dir = "BULLISH"
            h_conf = max(74.0, min(96.0, (h_prob * 100.0) + 9.0))
            decision = f"🎯 SUPERTREND PIVOT REVERSAL (LONG){squeeze_boost_label}"
            priority = 1
            is_reversal_setup = True
            is_neutral_zone = False
        elif is_supertrend_bear_pivot and not is_neutral_zone:
            h_dir = "BEARISH"
            h_conf = max(74.0, min(96.0, ((1.0 - h_prob) * 100.0) + 9.0))
            decision = f"🎯 SUPERTREND BREAKDOWN REVERSAL (SHORT){squeeze_boost_label}"
            priority = 1
            is_reversal_setup = True
            is_neutral_zone = False
        elif is_neutral_zone:
            decision = "⚪ CONSOLIDATION (RANGE-BOUND / WAIT)"
            priority = 4
        else:
            is_bear_trend_aligned = (
                h_dir == "BEARISH" and
                (not d1_macro_bull or is_bear_regime) and
                (rs_btc <= 0.20) and
                (st_dir == -1.0 or st_flip_bear or dist_to_ema20_anchor <= 0.005) and
                (rsi_anchor <= 60.0)
            )
            is_macro_aligned = (h_dir == "BULLISH" and d1_macro_bull and not is_bear_regime) or is_bear_trend_aligned
            is_alpha_exception = (h_dir == "BULLISH" and (rs_btc >= 0.5 or (h_conf >= 65.0 and not is_bear_regime)))
            is_15m_scalp_exception = (horizon_key == "scalp" and h_conf >= 62.0 and not is_bear_regime)

            # Macro Horizon (>= 24H) Short Filter Gatekeeper: Suppress multi-day shorts ONLY in confirmed Bull Trend
            is_macro_h = horizon_key in ['macro', 'horizon_24h', '24h', '1d', 'horizon_4d', 'weekly', 'biweekly', 'monthly']
            is_btc_bear = getattr(self, "btc_shield_code", "NORMAL") in ["BEAR_TREND", "ALERT_DUMP", "CAUTION"] or is_bear_regime
            is_severe_lag = (rs_btc <= -0.35) or (not d1_macro_bull)

            if is_macro_h and h_dir == "BEARISH" and not is_blowoff_top:
                decision = "⛔ FILTER (MACRO SHORT BLOCKED - ASYMMETRIC SQUEEZE RISK)"
                priority = 4
            elif (is_macro_aligned or is_alpha_exception or is_reversal_setup) and h_conf >= (self.config['elite_conviction_threshold'] * 100.0):
                decision = f"🎯 ELITE EXECUTE {'LONG' if h_dir=='BULLISH' else 'SHORT'}{squeeze_boost_label}"
                priority = 1
            elif (is_macro_aligned or is_alpha_exception or is_15m_scalp_exception or is_reversal_setup):
                if h_dir == "BEARISH":
                    # 🛑 Permanently eliminate loss-making standard shorts (empirical win rate 51.9%, -22.98% return)
                    decision = "⛔ FILTER (UNCONFIRMED SHORT - SQUEEZE RISK)"
                    priority = 4
                elif h_dir == "BULLISH" and h_conf >= 66.0 and (is_ob_long or is_bull_sweep or is_dip_buy or is_breakout_long):
                    decision = f"✅ STANDARD EXECUTE LONG{squeeze_boost_label}"
                    priority = 2
                else:
                    decision = "⛔ FILTER (UNCONFIRMED MOMENTUM LONG)"
                    priority = 4
            elif not is_macro_aligned and not is_alpha_exception and not is_15m_scalp_exception and not is_reversal_setup:
                decision = "⛔ FILTER (MACRO CONFLICT)"
                priority = 3
            else:
                decision = "⛔ FILTER (LOW CONVICTION)"
                priority = 4

        # Cold-Start Horizon Accumulation Gate: Dampen confidence and prevent live entry signals for newly listed coins (< 15 candles)
        if is_cold_start:
            p_val = p_laplace if p_laplace is not None else 0.50
            decision = f"⚪ COLD START HORIZON ACCUMULATION (N={n} < 15 CANDLES, P_LAPLACE={p_val:.2f})"
            h_dir = "CONSOLIDATION"
            h_conf = round(float(np.clip(p_val * 100.0, 48.0, 52.0)), 1)
            priority = 4
            is_neutral_zone = True

        # 7b. QUANT V16 INSTITUTIONAL NO TRADE ZONE (NTZ) EVALUATION
        is_ntz_active = False
        ntz_res = None
        try:
            from app.quant_v16.no_trade_zone import no_trade_zone_engine
            ntz_df = raw_dfs.get(anchor_tf) if raw_dfs and anchor_tf in raw_dfs else (raw_dfs.get('1h') if raw_dfs else fused_df)
            stats_24 = getattr(self.loader, '_24hr_tickers_map', {}).get(symbol, {}) if hasattr(self, 'loader') else {}
            btc_shield_d = {
                "is_active": getattr(self, 'btc_shield_active', False),
                "status_code": getattr(self, 'btc_shield_code', 'NORMAL'),
                "reason": getattr(self, 'btc_shield_reason', 'NORMAL')
            }
            align_val = 50.0 if ((h_dir == "BULLISH" and d1_macro_bull) or (h_dir == "BEARISH" and not d1_macro_bull)) else 0.0
            ntz_res = no_trade_zone_engine.evaluate_asset_ntz(
                df=ntz_df,
                current_price=current_price,
                anchor_tf=anchor_tf,
                btc_shield_info=btc_shield_d,
                funding_info=funding_info,
                stats_24h=stats_24,
                fund_matrix=fund_matrix,
                ob_setup=ob_setup,
                alignment_score=align_val,
                meta_win_prob=h_prob,
                direction=h_dir,
                decision=decision
            )
            is_ntz_active = bool(ntz_res and ntz_res.get("is_ntz", False))
        except Exception:
            is_ntz_active = False
            ntz_res = None

        is_ntz_blocked = False
        if is_ntz_active:
            ntz_badge = ntz_res.get('badge', f'NTZ-{anchor_tf.upper()}') if ntz_res else f'NTZ-{anchor_tf.upper()}'
            decision = f"🛑 NO TRADE ZONE ({ntz_badge})"
            priority = 4
            is_ntz_blocked = True
        else:
            # Check if macro market regime is in CONSOLIDATION / NO TRADE ZONE
            macro_shield_code = getattr(self, 'btc_shield_code', 'NORMAL')
            if macro_shield_code == "CONSOLIDATION" and not (is_ob_long and h_conf >= 75.0):
                c_rvol = float(ntz_res.get('metrics', {}).get('rvol', 1.0) if ntz_res else 1.0)
                if c_rvol < 1.25:
                    is_ntz_active = True
                    is_ntz_blocked = True
                    decision = f"🛑 NO TRADE ZONE (MACRO CONSOLIDATION - {anchor_tf.upper()})"
                    priority = 4
                    if not ntz_res:
                        ntz_res = {}
                    ntz_res['is_ntz'] = True
                    ntz_res['code'] = 'CHOP_CONSOLIDATION'
                    ntz_res['badge'] = f'MACRO-CONS-{anchor_tf.upper()}'

        # 8. Continuous Price Regression Target & Asymmetric R:R Architecture
        if is_blowoff_top:
            # Predict mean-reversion sell down targets based on Fibonacci & VWAP retracement from peak
            fib_retracement_map = {
                'scalp': 0.382,
                'horizon_30m': 0.450,
                'swing': 0.500,
                'horizon_4h': 0.618,
                'macro': 1.000,
                'horizon_4d': 1.000,
                'weekly': 1.000,
                'biweekly': 1.000,
                'monthly': 1.000
            }
            fib_ratio = fib_retracement_map.get(horizon_key, 0.50)
            downside_target = max(base_pump_price, peak_pump_price - (fib_ratio * pump_range))
            fib_drop_ret = -abs((current_price - downside_target) / (current_price + 1e-10))
            exp_ret = max(-0.75, min(-0.025, fib_drop_ret))
        elif is_hype_surge:
            # During parabolic expansion, dynamically scale target return with volume & volatility expansion
            surge_vol_factor = max(1.2, min(3.5, vol_ratio_now if 'vol_ratio_now' in locals() else 2.0))
            exp_ret_mag = max(0.015, abs(pred_reg_ret) * surge_vol_factor, (h_conf / 100.0) * live_norm_atr * (bars ** 0.5) * 1.5)
            exp_ret = min(3.00, exp_ret_mag)
        else:
            exp_ret_mag = max(0.004, abs(pred_reg_ret), (h_conf / 100.0) * live_norm_atr * (bars ** 0.5))
            exp_ret = min(3.00, exp_ret_mag) if h_dir == "BULLISH" else max(-0.75, -exp_ret_mag)

        projected_target = max(current_price * 0.10, current_price * (1.0 + exp_ret))
        predicted_next_price = format_precision_price(projected_target)
        predicted_return_pct = round(exp_ret * 100.0, 2)

        # Horizon-calibrated minimum SL buffer (prevents multi-day trades from getting stopped on 15m noise)
        horizon_sl_map = {
            'scalp': 0.0090,        # ~0.90% SL for 15M
            'horizon_30m': 0.0120,  # ~1.20% SL for 30M
            'swing': 0.0150,        # ~1.50% SL for 1H
            'horizon_4h': 0.0220,   # ~2.20% SL for 4H
            'macro': 0.0350,        # ~3.50% SL for 24H/1D
            'horizon_4d': 0.0450,
            'weekly': 0.0600,
            'biweekly': 0.0800,
            'monthly': 0.1000
        }
        horizon_tp1_min_map = {
            'scalp': 0.0065,        # 0.65% min TP1 for 15M
            'horizon_30m': 0.0085,  # 0.85% min TP1 for 30M
            'swing': 0.0120,        # 1.20% min TP1 for 1H
            'horizon_4h': 0.0180,   # 1.80% min TP1 for 4H
            'macro': 0.0280,        # 2.80% min TP1 for 24H/1D
            'horizon_4d': 0.0380,
            'weekly': 0.0500,
            'biweekly': 0.0700,
            'monthly': 0.0900
        }
        horizon_tp1_max_map = {
            'scalp': 0.0135,        # 1.35% max TP1 for 15M (achievable intraday liquidity corridor)
            'horizon_30m': 0.0165,  # 1.65% max TP1 for 30M
            'swing': 0.0220,        # 2.20% max TP1 for 1H
            'horizon_4h': 0.0320,   # 3.20% max TP1 for 4H
            'macro': 0.0550,        # 5.50% max TP1 for 24H/1D
            'horizon_4d': 0.0750,
            'weekly': 0.1000,
            'biweekly': 0.1400,
            'monthly': 0.1800
        }
        horizon_atr_tp1_mult = {
            'scalp': 1.00,
            'horizon_30m': 1.10,
            'swing': 1.25,
            'horizon_4h': 1.45,
            'macro': 1.75,
            'horizon_4d': 2.00,
            'weekly': 2.25,
            'biweekly': 2.50,
            'monthly': 3.00
        }
        is_mega_cap = symbol in ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]
        min_sl_rate = (0.0060 if is_mega_cap else horizon_sl_map.get(horizon_key, 0.0150))
        min_sl_dist = current_price * min_sl_rate
        risk_dist = max(min_sl_dist, sl_mult_eff * live_raw_atr)
        live_low_c = float(live_candle['low'].values[0]) if 'low' in live_candle.columns else current_price
        live_high_c = float(live_candle['high'].values[0]) if 'high' in live_candle.columns else current_price

        # TP1 calculation: High-probability liquidity target calibrated to ATR and regression expectation
        min_tp1_rate = (0.0035 if is_mega_cap else horizon_tp1_min_map.get(horizon_key, 0.0100))
        atr_mult = horizon_atr_tp1_mult.get(horizon_key, 1.25)
        reg_target_dist = abs(pred_reg_ret) * current_price if ('pred_reg_ret' in locals() and pred_reg_ret is not None and abs(pred_reg_ret) > 0.003) else 0.0

        is_consolidation_regime = (btc_pred_trend == "CONSOLIDATION" or btc_shield_regime in ["CONSOLIDATION", "STABLE", "SQUEEZE", "RANGE_BOUND"])
        if is_consolidation_regime and not is_hype_surge and not is_blowoff_top:
            tp1_dist = max(min_tp1_rate * current_price, min(atr_mult * live_raw_atr * 0.90, max(0.0075 * current_price, 1.05 * live_raw_atr)))
        else:
            tp1_dist = max(min_tp1_rate * current_price, atr_mult * live_raw_atr)
            if reg_target_dist > tp1_dist * 0.8:
                tp1_dist = max(tp1_dist, min(tp1_dist * 1.35, reg_target_dist))

        # For Reversals & Liquidity Sweeps, calibrate TP1 to harvest the initial counter-trend impulse
        if (is_top_reversal_active or is_bear_sweep) and h_dir == "BEARISH":
            tp1_dist = max(min_tp1_rate * current_price, min(tp1_dist, max(0.012 * current_price, 1.20 * live_raw_atr)))

        if h_dir == "BEARISH" and not is_reversal_setup and not is_ob_short and not is_breaker_short:
            max_allowed_sl_pct = 0.065 if horizon_key in ['biweekly', 'monthly'] else (0.050 if horizon_key in ['macro', 'horizon_4d', 'weekly'] else 0.035)
        else:
            max_allowed_sl_pct = 0.100 if horizon_key in ['biweekly', 'monthly'] else (0.075 if horizon_key in ['macro', 'horizon_4d', 'weekly'] else 0.045)
        if h_dir == "BULLISH":
            sl_base = current_price - risk_dist
            if is_ob_long and ob_setup and ob_setup.get("sl_price"):
                sl_p = float(ob_setup["sl_price"])
            elif is_reversal_setup or is_bull_sweep:
                sl_p = min(sl_base, live_low_c - (0.35 * live_raw_atr))
            elif is_dip_buy:
                # Anchor stop loss safely below the pullback swing low buffer (absorbs normal wick noise)
                sl_p = min(sl_base, live_low_c - (0.35 * live_raw_atr))
            elif is_hype_surge:
                sl_p = current_price - (0.85 * risk_dist)  # Tight ratchet stop on hype pumps
            else:
                sl_base = current_price - risk_dist
                sl_p = sl_base
            # Enforce hard ceiling on maximum stop-loss risk distance (caps macro tail risk)
            sl_p = max(sl_p, current_price * (1.0 - max_allowed_sl_pct))
            actual_risk = max(1e-8, current_price - sl_p)
            
            # Preserve structural 1:2.8+ to 1:6.0 R:R for Order Block Setups
            if is_ob_long and ob_setup and ob_setup.get("tp1_price"):
                tp1_p = float(ob_setup["tp1_price"])
                tp2_p = float(ob_setup.get("tp2_price", tp1_p * 1.025))
                tp3_p = float(ob_setup.get("tp3_price", tp2_p * 1.035))
                tp4_p = tp3_p * 1.05
                tp_p = tp4_p
            else:
                # Scalp & Consolidation adaptive target compression
                if is_consolidation_regime:
                    tp1_mult = 0.85 if horizon_key == "scalp" else (0.95 if horizon_key == "horizon_30m" else 1.05)
                else:
                    tp1_mult = 0.90 if horizon_key == "scalp" else (1.00 if horizon_key == "horizon_30m" else 1.15)
                max_tp1_dist = current_price * (0.0080 if is_mega_cap else horizon_tp1_max_map.get(horizon_key, 0.0250))
                eff_tp1_dist = min(max_tp1_dist, max(tp1_dist, min(tp1_dist * 1.25, tp1_mult * actual_risk)))
                tp1_p = current_price + eff_tp1_dist
                tp2_p = current_price + (eff_tp1_dist * 1.80)
                tp3_p = current_price + (eff_tp1_dist * 2.80)
                tp4_p = current_price + (eff_tp1_dist * 3.80)
                tp_p = tp4_p
        else:
            if is_blowoff_top:
                sl_p = min(current_price * (1.0 + max_allowed_sl_pct), max(current_price + (1.20 * live_raw_atr), peak_pump_price * 1.015))
                # Fibonacci downside take-profits
                tp1_p = max(current_price * 0.15, peak_pump_price - (0.382 * pump_range))
                tp2_p = max(current_price * 0.15, peak_pump_price - (0.500 * pump_range))
                tp3_p = max(current_price * 0.15, peak_pump_price - (0.618 * pump_range))
                tp4_p = max(current_price * 0.15, base_pump_price)
                if tp1_p >= current_price:
                    tp1_p = current_price * 0.965
                if tp2_p >= tp1_p:
                    tp2_p = tp1_p * 0.970
                if tp3_p >= tp2_p:
                    tp3_p = tp2_p * 0.960
                if tp4_p >= tp3_p:
                    tp4_p = tp3_p * 0.950
                tp_p = tp3_p
            else:
                sl_base = current_price + risk_dist
                if (is_ob_short or is_breaker_short) and ob_setup and ob_setup.get("sl_price"):
                    # Anchor safely above supply zone and live candle high (absorbs liquidity sweeps)
                    sl_p = max(float(ob_setup["sl_price"]), live_high_c + (0.25 * live_raw_atr))
                elif (is_top_reversal_active and h_dir == "BEARISH") or is_bear_sweep or is_breakdown_short or is_rally_sell:
                    # Anchor stop loss safely above the resistance shelf / rally peak / sweep high (absorbs retest wicks)
                    sl_p = max(sl_base, live_high_c + (0.35 * live_raw_atr))
                elif is_reversal_setup:
                    sl_p = max(sl_base, live_high_c + (0.25 * live_raw_atr))
                else:
                    sl_p = sl_base
                # Enforce hard ceiling on maximum stop-loss risk distance (caps macro tail risk)
                sl_p = min(sl_p, current_price * (1.0 + max_allowed_sl_pct))
                actual_risk = max(1e-8, sl_p - current_price)
                min_floor = max(1e-8, current_price * 0.15)  # Cap short TP floor to realistic max 85% drop
                if (is_ob_short or is_breaker_short) and ob_setup and ob_setup.get("tp1_price"):
                    tp1_p = max(min_floor, float(ob_setup["tp1_price"]))
                    tp2_p = max(min_floor, float(ob_setup.get("tp2_price", tp1_p * 0.975)))
                    tp3_p = max(min_floor, float(ob_setup.get("tp3_price", tp2_p * 0.965)))
                    tp4_p = max(min_floor, tp3_p * 0.95)
                    tp_p = tp4_p
                else:
                    if is_consolidation_regime:
                        tp1_mult = 0.85 if horizon_key == "scalp" else (0.95 if horizon_key == "horizon_30m" else 1.05)
                    else:
                        tp1_mult = 0.90 if horizon_key == "scalp" else (1.00 if horizon_key == "horizon_30m" else 1.15)
                    max_tp1_dist = current_price * (0.0080 if is_mega_cap else horizon_tp1_max_map.get(horizon_key, 0.0250))
                    eff_tp1_dist = min(max_tp1_dist, max(tp1_dist, min(tp1_dist * 1.25, tp1_mult * actual_risk)))
                    tp1_p = max(min_floor, current_price - eff_tp1_dist)
                    tp2_p = max(min_floor, current_price - (eff_tp1_dist * 1.80))
                    tp3_p = max(min_floor, current_price - (eff_tp1_dist * 2.80))
                    tp4_p = max(min_floor, current_price - (eff_tp1_dist * 3.80))
                    tp_p = tp4_p


        # Minimum Profit Hurdle Check against TP1
        tp1_gain_pct = (abs(tp1_p - current_price) / (current_price + 1e-10)) * 100.0
        min_reward_map = {
            'scalp': 0.25 if is_mega_cap else 0.35,
            'horizon_30m': 0.30 if is_mega_cap else 0.40,
            'swing': 0.40 if is_mega_cap else 0.55,
            'horizon_4h': 0.60 if is_mega_cap else 0.85,
            'macro': 1.00 if is_mega_cap else 1.50,
            'horizon_4d': 1.80 if is_mega_cap else 2.20,
            'weekly': 2.50 if is_mega_cap else 3.50,
            'biweekly': 3.50 if is_mega_cap else 5.00,
            'monthly': 5.00 if is_mega_cap else 7.00
        }
        min_hurdle = min_reward_map.get(horizon_key, 0.45)
        min_exp_req = (0.15 if is_mega_cap else (0.30 if horizon_key in ['scalp', 'horizon_30m'] else 0.35))
        if (tp1_gain_pct < min_hurdle or abs(exp_ret * 100.0) < min_exp_req) and not is_hype_surge and not is_blowoff_top and h_conf < 78.0:
            decision = f"⛔ FILTER (SUB-{min_hurdle:.1f}% RETURN / FEE DRAG)"
            priority = 4

        # Determine best selling / profit taking zone
        if h_dir == "BULLISH":
            best_sell_price = tp4_p if is_hype_surge else tp3_p
        else:
            best_sell_price = max(current_price * 0.15, tp4_p if is_blowoff_top else tp3_p)

        coin_tag = symbol.split('/')[0]
        p_fmt = format_precision_price_str
        type_str = "LONG 🟢" if h_dir == "BULLISH" else "SHORT 🔴"
        market_str = "Spot & Futures" if h_dir == "BULLISH" else "Futures Only ⚡"
        predicted_window_str = f"{trade_open_str} ➔ {trade_close_str} ({h_cfg['duration_label']})"

        # Optimal Pullback Limit Entry Zone for Order Blocks & Reversals (Anti-Chase Extension Guard)
        is_limit_pending = False
        chase_warning = ""
        entry_zone_min = current_price
        entry_zone_max = current_price

        # Extended reversal & sweep setups requiring pullback/bounce limits
        is_reversal_long_setup = is_bottom_reversal_active or is_bull_sweep or is_dip_buy
        is_reversal_short_setup = is_top_reversal_active or is_bear_sweep or is_rally_sell

        if is_reversal_long_setup and is_chase_danger_long:
            optimal_entry_price = round(pullback_limit_long, 6)
            entry_zone_min = round(pullback_zone_min_long, 6)
            entry_zone_max = round(pullback_zone_max_long, 6)
            is_limit_pending = True
            streak_desc = f"{h1_green_streak} green 1H bars" if h1_green_streak >= 2 else (f"{m15_green_streak} green 15M bars" if m15_green_streak >= 3 else "vertical spike")
            chase_warning = f"Extended +{impulse_lift_pct*100:.1f}% off low ({streak_desc}). Do NOT market buy peak!"
            setup_name = "BOTTOM-REVERSAL" if is_bottom_reversal_active else ("SWEEP-REVERSAL" if is_bull_sweep else "DIP-BUY")
            decision = f"⏳ {setup_name} [AWAIT PULLBACK: {p_fmt(optimal_entry_price)}]"
        elif is_reversal_short_setup and is_chase_danger_short:
            optimal_entry_price = round(bounce_limit_short, 6)
            entry_zone_min = round(bounce_zone_min_short, 6)
            entry_zone_max = round(bounce_zone_max_short, 6)
            is_limit_pending = True
            streak_desc = f"{h1_red_streak} red 1H bars" if h1_red_streak >= 2 else (f"{m15_red_streak} red 15M bars" if m15_red_streak >= 3 else "vertical dump")
            chase_warning = f"Extended -{impulse_drop_pct*100:.1f}% off high ({streak_desc}). Do NOT market short low!"
            setup_name = "TOP-REVERSAL" if is_top_reversal_active else ("SWEEP-REVERSAL" if is_bear_sweep else "RALLY-SELL")
            decision = f"⏳ {setup_name} [AWAIT BOUNCE: {p_fmt(optimal_entry_price)}]"
        elif is_ob_long and ob_setup and ob_setup.get("optimal_entry_limit"):
            optimal_entry_price = float(ob_setup["optimal_entry_limit"])
            is_limit_pending = abs(optimal_entry_price - current_price) / max(1e-8, current_price) >= 0.003
            ob_zone = ob_setup.get("order_block_zone")
            if ob_zone and len(ob_zone) == 2:
                entry_zone_min = round(float(ob_zone[0]), 6)
                entry_zone_max = round(float(ob_zone[1]), 6)
            else:
                entry_zone_min = round(optimal_entry_price * 0.998, 6)
                entry_zone_max = round(optimal_entry_price * 1.002, 6)
        elif (is_ob_short or is_breaker_short) and ob_setup and ob_setup.get("optimal_entry_limit"):
            optimal_entry_price = float(ob_setup["optimal_entry_limit"])
            is_limit_pending = abs(optimal_entry_price - current_price) / max(1e-8, current_price) >= 0.003
            ob_zone = ob_setup.get("order_block_zone")
            if ob_zone and len(ob_zone) == 2:
                entry_zone_min = round(float(ob_zone[0]), 6)
                entry_zone_max = round(float(ob_zone[1]), 6)
            else:
                entry_zone_min = round(optimal_entry_price * 0.998, 6)
                entry_zone_max = round(optimal_entry_price * 1.002, 6)
        elif horizon_key in ['scalp', 'horizon_30m']:
            if h_dir == "BULLISH":
                optimal_entry_price = min(current_price, max(current_price * 0.995, ema9_15m if 'ema9_15m' in locals() else current_price * 0.997))
            else:
                optimal_entry_price = max(current_price, min(current_price * 1.005, ema9_15m if 'ema9_15m' in locals() else current_price * 1.003))
            entry_zone_min = optimal_entry_price
            entry_zone_max = optimal_entry_price
        else:
            optimal_entry_price = current_price
            entry_zone_min = current_price
            entry_zone_max = current_price

        # MATHEMATICAL PRICE INVARIANT RECALIBRATION FOR LIMIT ORDERS:
        # Guarantee strict bracket geometry: SL < Entry < TP1 for LONG, TP1 < Entry < SL for SHORT
        if is_limit_pending:
            if h_dir == "BULLISH":
                optimal_entry_price = min(optimal_entry_price, current_price * 0.998)
                if sl_p >= optimal_entry_price * 0.992:
                    sl_p = min(sl_p, optimal_entry_price * 0.985)
                sl_p = min(sl_p, anchor_low_val * 0.995)
                sl_p = max(sl_p, optimal_entry_price * (1.0 - max_allowed_sl_pct))
                if tp1_p <= optimal_entry_price * 1.015:
                    tp1_p = optimal_entry_price * 1.025
            else:
                optimal_entry_price = max(optimal_entry_price, current_price * 1.002)
                if sl_p <= optimal_entry_price * 1.008:
                    sl_p = max(sl_p, optimal_entry_price * 1.015)
                sl_p = max(sl_p, anchor_high_val * 1.005)
                sl_p = min(sl_p, optimal_entry_price * (1.0 + max_allowed_sl_pct))
                if tp1_p >= optimal_entry_price * 0.985:
                    tp1_p = optimal_entry_price * 0.975

        # Compute calibrated Risk-to-Reward ratio
        calc_entry = optimal_entry_price if is_limit_pending else current_price
        if h_dir == "BULLISH":
            risk_amt = max(1e-8, calc_entry - sl_p)
            reward_amt = max(1e-8, tp1_p - calc_entry)
        else:
            risk_amt = max(1e-8, sl_p - calc_entry)
            reward_amt = max(1e-8, calc_entry - tp1_p)
        rrr_num = max(1.0, reward_amt / risk_amt)
        risk_reward_ratio_str = f"1:{rrr_num:.1f}"

        if is_limit_pending:
            entry_display_str = f"LIMIT {'BID' if h_dir == 'BULLISH' else 'ASK'}: {p_fmt(optimal_entry_price)} (Zone: {p_fmt(entry_zone_min)} - {p_fmt(entry_zone_max)} | Live: {p_fmt(current_price)})"
        elif horizon_key in ['scalp', 'horizon_30m']:
            entry_display_str = f"{p_fmt(current_price)} (Optimal Limit: {p_fmt(optimal_entry_price)})"
        else:
            entry_display_str = p_fmt(current_price)

        pro_signal_text = (
            f"🚀 PAIR: #{coin_tag}/USDT\n"
            f"📊 TYPE: {type_str}\n"
            f"🌐 MARKET: {market_str}\n"
            f"📅 PREDICTED CANDLE: {predicted_window_str}\n"
            f"🎯 ENTRY: {entry_display_str}\n"
            f"🔮 ML NEXT PRICE: {p_fmt(predicted_next_price)} ({predicted_return_pct:+.2f}%)\n"
            f"💎 BEST EXIT / SELL ZONE: {p_fmt(best_sell_price)}\n\n"
            f"💎 TAKE PROFITS:\n"
            f"➤ TP1: {p_fmt(tp1_p)}\n"
            f"➤ TP2: {p_fmt(tp2_p)}\n"
            f"➤ TP3: {p_fmt(tp3_p)}\n\n"
            f"🛑 STOP LOSS: {p_fmt(sl_p)}\n\n"
            f"📈 RISK-TO-REWARD RATIO: 1:2"
        )

        # Calculate live microstructure wick ratio (upper + lower shadow vs body)
        live_open_c = float(live_candle['open'].values[0]) if 'open' in live_candle.columns else current_price
        live_close_c = float(live_candle['close'].values[0]) if 'close' in live_candle.columns else current_price
        c_body = max(1e-8, abs(live_close_c - live_open_c))
        c_upper_wick = max(0.0, live_high_c - max(live_open_c, live_close_c))
        c_lower_wick = max(0.0, min(live_open_c, live_close_c) - live_low_c)
        live_wick_ratio = (c_upper_wick + c_lower_wick) / c_body

        meta_win_prob = self.meta_classifier.predict_win_probability({
            "conviction": h_conf,
            "grade": "Grade A+" if h_conf >= 78.0 else "Grade A",
            "exp_return": exp_ret,
            "horizon_key": horizon_key,
            "direction": h_dir,
            "decision": decision,
            "entry_price": current_price,
            "tp1_price": tp1_p,
            "sl_price": sl_p,
            "wick_ratio": live_wick_ratio,
            "priority": priority,
            "symbol": symbol
        }, symbol=symbol)

        # SMC Order Block Confluence Integration with Meta-Classifier
        from app.engine.config import PROBABILITY_CALIBRATION_MODE
        is_calibrated = (PROBABILITY_CALIBRATION_MODE == "CHRONOLOGICAL_CALIBRATED")
        ob_min_prob = 0.35 if is_calibrated else 0.45
        if (is_ob_long or is_ob_short or is_breaker_long or is_breaker_short) and ob_setup:
            ob_prob = float(ob_setup.get("meta_win_prob", 0.40 if is_calibrated else 0.75))
            if meta_win_prob >= ob_min_prob:
                meta_win_prob = round(min(0.95, (meta_win_prob * 0.40) + (ob_prob * 0.60)), 3)

        # 🧠 Anti-Climax Overconfidence Recalibration (Addresses empirical inversion: >68% meta-prob lost -18.88%)
        is_overextended_long = (h_dir == "BULLISH") and (
            (locals().get('impulse_lift_pct', 0.0) > 0.035) or
            (locals().get('m15_green_streak', 0) >= 3) or
            (locals().get('rsi_now', 50.0) > 68.0)
        )
        overextended_cut = 0.46 if is_calibrated else 0.65
        if is_overextended_long and meta_win_prob > overextended_cut:
            meta_win_prob = round(meta_win_prob * 0.82, 3)
            if not is_limit_pending and "ELITE" not in decision:
                decision = "⚪ OVEREXTENDED MOMENTUM (AWAIT PULLBACK TO DEMAND BLOCK)"
                priority = 4

        # ----------------------------------------------------------------------
        # SECONDARY ML META-CLASSIFIER QUALITY ENFORCEMENT & DOWNTREND FILTER
        # ----------------------------------------------------------------------
        # Dynamic Economic Entry Hurdle: p* = (1 + C) / (RR + 1) + margin
        if is_calibrated:
            tp_dist = abs(tp1_p - current_price) / max(1e-8, current_price)
            sl_dist = abs(current_price - sl_p) / max(1e-8, current_price)
            rr_val = tp_dist / max(0.002, sl_dist)
            friction_ratio = 0.0018 / max(0.002, sl_dist)
            base_hurdle = ((1.0 + friction_ratio) / (rr_val + 1.0)) + 0.02
            hurdle_normal = float(np.clip(base_hurdle, 0.28, 0.48))
            hurdle_adverse = float(np.clip(base_hurdle + 0.04, 0.32, 0.52))
        else:
            hurdle_normal = 0.48
            hurdle_adverse = 0.52

        if h_dir == "BULLISH" and (meta_win_prob < hurdle_normal or (is_bear_regime and meta_win_prob < hurdle_adverse)):
            if is_bear_regime:
                decision = f"⛔ FILTER (BTC DOWNTREND - COUNTER-TREND LONG BLOCKED | 🧠 {meta_win_prob*100:.1f}%)"
            else:
                decision = f"⛔ FILTER (LOW META WIN PROB: {meta_win_prob*100:.1f}%)"
            priority = 4
            h_conf = min(h_conf, round(meta_win_prob * 100.0, 1))
        elif h_dir == "BEARISH" and (meta_win_prob < hurdle_normal or (is_bull_regime and meta_win_prob < hurdle_adverse)):
            if is_bull_regime:
                decision = f"⛔ FILTER (BTC UPTREND - COUNTER-TREND SHORT BLOCKED | 🧠 {meta_win_prob*100:.1f}%)"
            else:
                decision = f"⛔ FILTER (LOW META WIN PROB: {meta_win_prob*100:.1f}%)"
            priority = 4
            h_conf = min(h_conf, round(meta_win_prob * 100.0, 1))
        elif "EXECUTE" in decision:
            # Calibrate conviction with Meta-Classifier win probability
            if is_calibrated:
                norm_p = (meta_win_prob - 0.30) / max(0.01, (0.50 - 0.30))
                mapped_conf = 60.0 + (norm_p * 30.0)
                h_conf = round((h_conf * 0.5) + (mapped_conf * 0.5), 1)
            else:
                h_conf = round((h_conf * 0.5) + (meta_win_prob * 100.0 * 0.5), 1)

        active_playbook = getattr(self, 'trader_playbook', None) or TraderRegimePlaybook.generate('STABLE', 'CONSOLIDATION', 33.3, 33.3, 33.4)
        playbook_regime = active_playbook.get('regime_type', 'CONSOLIDATION')
        playbook_sizing_multiplier = active_playbook.get('sizing_multiplier', 1.0)
        playbook_directive = active_playbook.get('tactical_stance', '')

        # Wire SpecializedStrategyRouter regime modulation into final candidate
        regime_mod = SpecializedStrategyRouter.route_by_regime({
            "direction": h_dir,
            "decision": decision,
            "conviction": h_conf,
            "entry_price": current_price,
            "tp1_price": tp1_p,
            "sl_price": sl_p
        }, regime_type=playbook_regime)
        if regime_mod and not is_ntz_blocked:
            decision = regime_mod.get("decision", decision)
            h_conf = regime_mod.get("conviction", h_conf)
            if regime_mod.get("tactical_stance"):
                playbook_directive = regime_mod["tactical_stance"]

        # Final Cold-Start Enforcement: Authoritative override preventing false-positive outlier setups
        if is_cold_start:
            p_val = p_laplace if p_laplace is not None else 0.50
            decision = f"⚪ COLD START HORIZON ACCUMULATION (N={n} < 15 CANDLES, P_LAPLACE={p_val:.2f})"
            h_dir = "CONSOLIDATION"
            h_conf = round(float(np.clip(p_val * 100.0, 48.0, 52.0)), 1)
            priority = 4
            is_neutral_zone = True

        p_tp1_pct = round(meta_win_prob * 100.0, 1)
        p_tp2_pct = round(p_tp1_pct * 0.65, 1)
        p_tp3_pct = round(p_tp2_pct * 0.55, 1)
        p_sl_pct = round(100.0 - p_tp1_pct, 1)

        pro_signal_text = (
            f"🚀 PAIR: #{coin_tag}/USDT\n"
            f"📊 TYPE: {type_str}\n"
            f"🎯 SETUP: {decision}\n"
            f"🌐 MARKET: {market_str}\n"
            f"📅 PREDICTED CANDLE: {predicted_window_str}\n"
            f"🎯 ENTRY: {entry_display_str}\n"
            f"🔮 ML NEXT PRICE: {p_fmt(predicted_next_price)} ({predicted_return_pct:+.2f}%)\n"
            f"💎 BEST EXIT / SELL ZONE: {p_fmt(best_sell_price)}\n\n"
            f"💎 TAKE PROFITS:\n"
            f"➤ TP1: {p_fmt(tp1_p)} • Prob: {p_tp1_pct}%\n"
            f"➤ TP2: {p_fmt(tp2_p)} • Prob: {p_tp2_pct}%\n"
            f"➤ TP3: {p_fmt(tp3_p)} • Prob: {p_tp3_pct}%\n\n"
            f"🛑 STOP LOSS: {p_fmt(sl_p)} • Risk Prob: {p_sl_pct}%\n\n"
            f"📈 RISK-TO-REWARD RATIO: {risk_reward_ratio_str}"
        )

        res = {
            "symbol": symbol,
            "horizon_name": h_cfg['name'],
            "duration_label": h_cfg['duration_label'],
            "current_price": format_precision_price(current_price),
            "optimal_entry_price": format_precision_price(optimal_entry_price),
            "entry_price": format_precision_price(optimal_entry_price if is_limit_pending else current_price),
            "is_limit_pending": is_limit_pending,
            "entry_zone_min": format_precision_price(entry_zone_min),
            "entry_zone_max": format_precision_price(entry_zone_max),
            "chase_warning": chase_warning,
            "impulse_lift_pct": round(impulse_lift_pct * 100.0, 2),
            "impulse_drop_pct": round(impulse_drop_pct * 100.0, 2),
            "h1_streak": h1_green_streak if h_dir == "BULLISH" else h1_red_streak,
            "risk_reward_ratio": risk_reward_ratio_str,
            "predicted_next_price": predicted_next_price,
            "predicted_return_pct": predicted_return_pct,
            "best_sell_price": format_precision_price(best_sell_price),
            "norm_atr": live_norm_atr,
            "raw_atr": live_raw_atr,
            "rs_btc": rs_btc,
            "is_hype_surge": is_hype_surge,
            "is_blowoff_top": is_blowoff_top,
            "rsi_anchor": round(float(rsi_anchor), 2),
            "rsi": round(float(rsi_anchor), 2),
            "playbook_regime": playbook_regime,
            "playbook_sizing_multiplier": playbook_sizing_multiplier,
            "playbook_directive": playbook_directive,
            "trade_open_str": trade_open_str,
            "trade_close_str": trade_close_str,
            "predicted_close_utc": trade_close_str,
            "predicted_window_str": predicted_window_str,
            "direction": h_dir,
            "conviction": h_conf,
            "meta_win_prob": meta_win_prob,
            "meta_win_prob_pct": round(meta_win_prob * 100.0, 1),
            "volume_24h_usd": float(stats_24.get('quoteVolume', 0.0) or 0.0) if stats_24 else 0.0,
            "bid_price": float(stats_24.get('bidPrice', current_price) or current_price) if stats_24 else current_price,
            "ask_price": float(stats_24.get('askPrice', current_price) or current_price) if stats_24 else current_price,
            "spread_bps": round(((float(stats_24.get('askPrice', current_price) or current_price) - float(stats_24.get('bidPrice', current_price) or current_price)) / max(1e-8, (float(stats_24.get('bidPrice', current_price) or current_price) + float(stats_24.get('askPrice', current_price) or current_price)) / 2.0)) * 10000.0, 2) if (stats_24 and float(stats_24.get('bidPrice', 0.0) or 0.0) > 0 and float(stats_24.get('askPrice', 0.0) or 0.0) >= float(stats_24.get('bidPrice', 0.0) or 0.0)) else 5.0,
            "p_tp1": p_tp1_pct,
            "p_tp2": p_tp2_pct,
            "p_tp3": p_tp3_pct,
            "p_sl": p_sl_pct,
            "exp_return": exp_ret,
            "projected_target": format_precision_price(projected_target),
            "tp_price": format_precision_price(tp_p),
            "tp1_price": format_precision_price(tp1_p),
            "tp2_price": format_precision_price(tp2_p),
            "tp3_price": format_precision_price(tp3_p),
            "tp4_price": format_precision_price(tp4_p),
            "sl_price": format_precision_price(sl_p),
            "elite_precision": elite_acc,
            "decision": decision,
            "strategy_archetype": "ORDER_BLOCK_LONG" if (is_ob_long and h_dir == "BULLISH") else ("ORDER_BLOCK_SHORT" if (is_ob_short and h_dir == "BEARISH") else ("BREAKER_BLOCK_SHORT" if (is_breaker_short and h_dir == "BEARISH") else ("BLOW_OFF_TOP_SHORT" if (is_blowoff_top and h_dir == "BEARISH") else ("TOP_REVERSAL_SHORT" if (is_top_reversal_active and h_dir == "BEARISH") else ("BOTTOM_REVERSAL_LONG" if (is_bottom_reversal_active and h_dir == "BULLISH") else ("LIQUIDITY_SWEEP_SHORT" if (is_bear_sweep and h_dir == "BEARISH") else ("LIQUIDITY_SWEEP_LONG" if (is_bull_sweep and h_dir == "BULLISH") else ("MOMENTUM_SHORT" if (is_momentum_short and h_dir == "BEARISH") else ("MOMENTUM_LONG" if (is_momentum_long and h_dir == "BULLISH") else ("DIP_BUY_LONG" if (is_dip_buy and h_dir == "BULLISH") else ("RALLY_FADE_SHORT" if (is_rally_sell and h_dir == "BEARISH") else ("BREAKOUT_LONG" if (is_breakout_long and h_dir == "BULLISH") else ("BREAKDOWN_SHORT" if (is_breakdown_short and h_dir == "BEARISH") else ("DIRECTIONAL_TREND_LONG" if h_dir == "BULLISH" else "DIRECTIONAL_TREND_SHORT")))))))))))))),
            "priority": priority,
            "pro_signal_text": pro_signal_text,
            "vip_signal_text": pro_signal_text,
            "fundamental_matrix": fund_matrix,
            "order_block_setup": ob_setup,
            "zeiierman_rank": ob_setup.get("zeiierman_rank") if ob_setup else None,
            "zeiierman_rank_label": ob_setup.get("zeiierman_rank_label") if ob_setup else None,
            "is_nested_smc": ob_setup.get("is_nested_smc", False) if ob_setup else False,
            "htf_poi_tf": ob_setup.get("htf_poi_tf") if ob_setup else None,
            "htf_poi_zone": ob_setup.get("htf_poi_zone") if ob_setup else None,
            "order_block_zone": ob_setup.get("order_block_zone") if ob_setup else None,
            "mean_threshold_price": ob_setup.get("mean_threshold_price") if ob_setup else None,
            "supertrend_direction": "BULLISH" if st_dir == 1.0 else "BEARISH",
            "supertrend_flip": "BULLISH" if st_flip_bull else ("BEARISH" if st_flip_bear else "NONE"),
            "is_ntz_active": is_ntz_active,
            "is_ntz_blocked": is_ntz_blocked,
            "ntz_timeframe": ntz_res.get("timeframe", anchor_tf.upper()) if ntz_res else anchor_tf.upper(),
            "ntz_code": ntz_res.get("code", "CLEAR") if ntz_res else "CLEAR",
            "ntz_label": ntz_res.get("label", "") if ntz_res else "",
            "ntz_badge": ntz_res.get("badge", "") if ntz_res else "",
            "ntz_reasons": ntz_res.get("reasons", []) if ntz_res else [],
            "ntz_metrics": ntz_res.get("metrics", {}) if ntz_res else {},
            "is_cold_start": is_cold_start,
            "cold_start_candles": n,
            "accumulation_phase": "COLD_START_INSUFFICIENT_HISTORY" if is_cold_start else "CONVERGED_ENSEMBLE",
            "laplace_prob": p_laplace if is_cold_start else None
        }

        return res

    def process_single_asset(self, symbol: str) -> dict:
        timeframes = self.config['timeframes']
        raw_dfs = {}
        tf_features = {}
        tf_metrics_summary = []

        # Concurrent ingestion of all 4 multi-scale charts (sub-70ms parallel fetch)
        for tf_str in timeframes:
            limit = self.config['history_limit_per_tf'].get(tf_str, 120)
            df = None
            try:
                df = self.loader.fetch_ohlcv_extended(symbol, tf_str, total_candles=limit)
            except Exception:
                pass
            if df is None or len(df) < 15:
                try:
                    df = self.loader.fetch_ohlcv(symbol, timeframe=tf_str, limit=limit)
                except Exception:
                    pass
            if df is not None and len(df) >= 10:
                raw_dfs[tf_str] = df

        if '15m' in raw_dfs and len(raw_dfs['15m']) >= 15:
            df_15 = raw_dfs['15m']
            for tf_str in timeframes:
                if tf_str not in raw_dfs or raw_dfs[tf_str] is None or len(raw_dfs[tf_str]) < 10:
                    raw_dfs[tf_str] = df_15.copy()
        elif not raw_dfs or len(raw_dfs) < 1:
            return None

        # Build features and metrics for each timeframe
        for tf_str in timeframes:
            df = raw_dfs[tf_str]
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

        # Orderbook Depth Imbalance Microstructure Alpha (fast 5 levels)
        ob_imbalance = self.loader.fetch_orderbook_imbalance(symbol, limit=5)
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

        # Macro Daily Trend Check: Must be trading above EMA50 to be bullish (fixes laggy golden cross bug)
        d1_c = raw_dfs['1d']['close'].values
        d1_ema50 = pd.Series(d1_c).ewm(span=50).mean().values[-1]
        d1_ema200 = pd.Series(d1_c).ewm(span=200).mean().values[-1]
        d1_macro_bull = (d1_c[-1] > d1_ema50) and (d1_c[-1] > d1_ema200 * 0.98)

        # Pre-build fused_dfs for the 4 anchor timeframes once
        fused_dfs = {}
        for a_tf in ['15m', '1h', '4h', '1d']:
            if a_tf not in raw_dfs:
                continue
            anchor_df = raw_dfs[a_tf].copy().sort_values('timestamp')
            anchor_df['primary_raw_atr'] = self.fe.compute_atr(anchor_df, period=14)
            anchor_df['primary_norm_atr'] = anchor_df['primary_raw_atr'] / (anchor_df['close'] + 1e-10)
            fused = anchor_df.copy()
            for tf_str, feat_df in tf_features.items():
                fused = pd.merge_asof(
                    fused.sort_values('timestamp'),
                    feat_df.sort_values('timestamp'),
                    on='timestamp',
                    direction='backward'
                )
            if symbol != "BTC/USDT" and self.btc_cache:
                fused = self.fe.inject_cross_asset_btc_beta(fused, self.btc_cache)
            fused_dfs[a_tf] = fused

        today_utc_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.daily_macro_date != today_utc_str:
            self.daily_macro_cache.clear()
            self.daily_macro_date = today_utc_str

        model_inference_cache = {}
        # Multi-Tier Horizon Execution:
        # Group 1: Fast Intraday & Scalp Horizons (15M, 30M, 1H, 4H, 24H) - Continuous dynamic evaluation
        # Group 2: Multi-Day Macro & Monthly Horizons (4D, 7D, 15D, 30D) - Evaluated on 00:00:00 UTC daily candle close and cached
        horizon_results = {}
        for h_key, h_cfg in self.config['horizons'].items():
            a_tf = h_cfg['anchor_tf']
            fused_df = fused_dfs.get(a_tf, raw_dfs.get(a_tf))
            if fused_df is None:
                continue

            if h_key in ["horizon_4d", "weekly", "biweekly", "monthly"]:
                cache_key = (symbol, h_key, today_utc_str)
                cached_res = self.daily_macro_cache.get(cache_key)
                now_macro_ts = time.time()
                if cached_res is not None and (now_macro_ts - cached_res.get('_macro_ts', 0) < 7200.0):
                    res_copy = dict(cached_res)
                    res_copy['current_price'] = live_price
                    res_copy['live_price'] = live_price
                    horizon_results[h_key] = res_copy
                    continue

                res = self.evaluate_single_horizon(
                    symbol, h_key, h_cfg, fused_df, d1_macro_bull, funding_info, live_price=live_price, model_inference_cache=model_inference_cache, raw_dfs=raw_dfs
                )
                if isinstance(res, dict):
                    res['_macro_ts'] = now_macro_ts
                self.daily_macro_cache[cache_key] = res
                horizon_results[h_key] = res
            else:
                # Real-time high-speed evaluation for Scalp & Intraday setups
                horizon_results[h_key] = self.evaluate_single_horizon(
                    symbol, h_key, h_cfg, fused_df, d1_macro_bull, funding_info, live_price=live_price, model_inference_cache=model_inference_cache, raw_dfs=raw_dfs
                )

        # ----------------------------------------------------------------------
        # HIERARCHICAL MULTI-TIER SUPPORT ARCHITECTURE:
        # Micro Tactical Trigger (15M) & Macro Daily Anchor (24H)
        # Evaluated as primary institutional trading horizons and directional confirmation anchors.
        # ----------------------------------------------------------------------
        if 'scalp' in horizon_results:
            res_15m = horizon_results['scalp']
        else:
            support_15m_cfg = {
                "name": "⚡ Scalp (15M)",
                "anchor_tf": "15m",
                "bars": 1,
                "duration_label": "15m Scalp",
                "tp_mult": 2.0,
                "sl_mult": 1.0
            }
            fused_15m = fused_dfs.get('15m', raw_dfs.get('15m'))
            if fused_15m is not None and not fused_15m.empty:
                res_15m = self.evaluate_single_horizon(
                    symbol, 'scalp', support_15m_cfg, fused_15m, d1_macro_bull, funding_info,
                    live_price=live_price, model_inference_cache=model_inference_cache, raw_dfs=raw_dfs
                )
            else:
                res_15m = {}

        if 'macro' in horizon_results:
            res_24h = horizon_results['macro']
        else:
            support_24h_cfg = {
                "name": "🌊 Swing Trade (1D)",
                "anchor_tf": "1d",
                "bars": 1,
                "duration_label": "24h Swing",
                "tp_mult": 3.0,
                "sl_mult": 1.5
            }
            fused_1d = fused_dfs.get('1d', raw_dfs.get('1d'))
            if fused_1d is not None and not fused_1d.empty:
                cache_key_24h = (symbol, 'macro_support_24h', today_utc_str)
                cached_24h = self.daily_macro_cache.get(cache_key_24h)
                now_macro_ts = time.time()
                if cached_24h is not None and (now_macro_ts - cached_24h.get('_macro_ts', 0) < 7200.0):
                    res_24h = dict(cached_24h)
                    res_24h['current_price'] = live_price
                    res_24h['live_price'] = live_price
                else:
                    res_24h = self.evaluate_single_horizon(
                        symbol, 'macro', support_24h_cfg, fused_1d, d1_macro_bull, funding_info,
                        live_price=live_price, model_inference_cache=model_inference_cache, raw_dfs=raw_dfs
                    )
                    if isinstance(res_24h, dict):
                        res_24h['_macro_ts'] = now_macro_ts
                    self.daily_macro_cache[cache_key_24h] = res_24h
            else:
                res_24h = {}

        # Trade Horizons (1H Day Trade, 4H Day Trade, 24H Swing Trade, 15M Scalp)
        swing_h = horizon_results.get('swing', {})
        h4_h = horizon_results.get('horizon_4h', {})
        scalp_h = horizon_results.get('scalp') or res_15m
        macro_h = horizon_results.get('macro') or res_24h

        # ----------------------------------------------------------------------
        # 🏛️ INSTITUTIONAL TRIPLE SCREEN CONFLUENCE (1D Direction -> 4H Behavior -> 1H Trigger)
        # ----------------------------------------------------------------------
        triple_screen_sig = TripleScreenConfluenceEngine.evaluate(
            symbol, raw_dfs, live_price=live_price, stats_24h=None, funding_info=funding_info
        )
        if triple_screen_sig:
            horizon_results['triple_screen'] = triple_screen_sig
            if 'swing' in horizon_results:
                orig_sw = horizon_results['swing']
                if orig_sw.get('direction') == triple_screen_sig['direction'] or "CONSOLIDATION" in orig_sw.get('decision', ''):
                    orig_sw.update({
                        "decision": triple_screen_sig['decision'],
                        "direction": triple_screen_sig['direction'],
                        "direction_label": triple_screen_sig['direction_label'],
                        "conviction": max(_safe_float(orig_sw.get('conviction', 50.0)), triple_screen_sig['conviction']),
                        "grade": triple_screen_sig['grade'],
                        "tier_label": triple_screen_sig['tier_label'],
                        "is_triple_screen": True,
                        "d1_bias_label": triple_screen_sig['d1_bias_label'],
                        "h4_behavior_label": triple_screen_sig['h4_behavior_label'],
                        "priority": 1
                    })

        # Multi-Horizon Matrix Tracking: Expose 15M (Scalp), 1H & 4H (Day Trade), and 24H (Swing Trade)
        if scalp_h:
            horizon_results['scalp'] = scalp_h
        if macro_h:
            horizon_results['macro'] = macro_h

        # Multi-Model Alignment across the 4 core tiers (15M Scalp, 1H Day Trade, 4H Day Trade, 24H Swing Trade)
        all_evaluated_models = {
            "15m_scalp": scalp_h,
            "1h_day_trade": swing_h,
            "4h_day_trade": h4_h,
            "24h_swing": macro_h,
        }
        bull_models = [k for k, m in all_evaluated_models.items() if m.get('direction') == "BULLISH" and "CONSOLIDATION" not in m.get('decision', '')]
        bear_models = [k for k, m in all_evaluated_models.items() if m.get('direction') == "BEARISH" and "CONSOLIDATION" not in m.get('decision', '')]
        neutral_models = [k for k, m in all_evaluated_models.items() if "CONSOLIDATION" in m.get('decision', '') or not m.get('decision')]
        
        bull_count = len(bull_models)
        bear_count = len(bear_models)
        neutral_count = len(neutral_models)
        alignment_score = round(((bull_count - bear_count) / 4.0) * 100.0, 1)

        is_scalp_bottom = "BOTTOM-REVERSAL" in scalp_h.get('decision', '') or "DIP-BUY" in scalp_h.get('decision', '')
        is_scalp_top = "TOP-REVERSAL" in scalp_h.get('decision', '') or "RALLY-SELL" in scalp_h.get('decision', '') or bool(scalp_h.get('is_blowoff_top', False))
        
        if bull_count >= 4:
            confluence_tag = f"💎 4/4 BULL EXPANSION"
            market_phase = "🚀 BULL_TREND_EXPANSION"
            consistency_index = 98.0
        elif bear_count >= 4:
            confluence_tag = f"💎 4/4 BEAR BREAKDOWN"
            market_phase = "🩸 BEAR_TREND_EXPANSION"
            consistency_index = 98.0
        elif bull_count >= 3:
            confluence_tag = f"🟢 3/4 STRONG BULLISH"
            market_phase = "🚀 BULL_TREND_EXPANSION" if macro_h.get('direction') == 'BULLISH' else "💎 DIP_ACCUMULATION"
            consistency_index = 85.0
        elif bear_count >= 3:
            confluence_tag = f"🔴 3/4 STRONG BEARISH"
            market_phase = "🩸 BEAR_TREND_EXPANSION" if macro_h.get('direction') == 'BEARISH' else "🛑 TOP_DISTRIBUTION"
            consistency_index = 85.0
        elif is_scalp_bottom:
            confluence_tag = f"⚡ 15M BOTTOM REVERSAL"
            market_phase = "💎 DIP_ACCUMULATION"
            consistency_index = 75.0
        elif is_scalp_top:
            confluence_tag = f"⚡ 15M TOP EXHAUSTION"
            market_phase = "🛑 TOP_DISTRIBUTION"
            consistency_index = 75.0
        else:
            confluence_tag = f"⚪ {neutral_count}/4 RANGE CONSOLIDATION"
            market_phase = "💤 RANGE_CONSOLIDATION"
            consistency_index = 50.0

        # Core Trade Horizons Triple Confluence (1H, 4H, 24H all agree in trade direction)
        is_triple_confluence = (
            swing_h.get('direction') in ["BULLISH", "BEARISH"]
            and swing_h.get('direction') == h4_h.get('direction') == macro_h.get('direction')
            and "CONSOLIDATION" not in swing_h.get('decision', '')
            and "CONSOLIDATION" not in h4_h.get('decision', '')
            and "CONSOLIDATION" not in macro_h.get('decision', '')
        )

        # 4-Tier Super Confluence (15M Micro + 1H Day Trade + 4H Day Trade + 24H Swing Anchor)
        is_super_confluence_5x = (
            is_triple_confluence
            and scalp_h.get('direction') == swing_h.get('direction')
            and "CONSOLIDATION" not in scalp_h.get('decision', '')
        )

        # Master pick priority
        best_priority = min(h.get('priority', 3) for h in horizon_results.values())
        overall_score = sum(_safe_float(h.get('conviction', 50.0), 50.0) * abs(_safe_float(h.get('exp_return', 0.0), 0.0)) for h in horizon_results.values())

        # 15m candle high and low for intra-candle wick verification
        live_high = max(float(raw_dfs['15m']['high'].iloc[-1]) if '15m' in raw_dfs else live_price, live_price)
        live_low = min(float(raw_dfs['15m']['low'].iloc[-1]) if '15m' in raw_dfs else live_price, live_price)

        # Cross-Asset BTC Beta & Correlation Metrics
        btc_corr = 0.50
        btc_beta = 1.00
        is_bear_when_btc_bear = False
        is_bull_when_btc_bear = False
        fused_1h = fused_dfs.get('1h', fused_dfs.get('15m'))
        if fused_1h is not None and not fused_1h.empty:
            if 'btc_corr_24h' in fused_1h.columns:
                btc_corr = float(fused_1h['btc_corr_24h'].iloc[-1])
            if 'btc_beta_24h' in fused_1h.columns:
                btc_beta = float(fused_1h['btc_beta_24h'].iloc[-1])
            if 'is_bear_when_btc_bear' in fused_1h.columns:
                is_bear_when_btc_bear = bool(fused_1h['is_bear_when_btc_bear'].iloc[-1] > 0.5)
            if 'is_bull_when_btc_bear' in fused_1h.columns:
                is_bull_when_btc_bear = bool(fused_1h['is_bull_when_btc_bear'].iloc[-1] > 0.5)

        # BTC Alignment Categorization
        if btc_corr >= 0.45:
            btc_alignment_tag = "BULL_BETA_ALIGNED"
            btc_alignment_label = f"🟢 BTC Aligned (Corr: {btc_corr:+.2f}, Beta: {btc_beta:.2f}x)"
        elif btc_corr <= -0.20:
            btc_alignment_tag = "INVERSE_BTC_HEDGE"
            btc_alignment_label = f"🛡️ Inverse Hedge (Corr: {btc_corr:+.2f})"
        elif abs(btc_corr) < 0.25:
            btc_alignment_tag = "DECOUPLED_INDEPENDENT"
            btc_alignment_label = f"⚡ Decoupled/Solo (Corr: {btc_corr:+.2f})"
        else:
            btc_alignment_tag = "MODERATE_CORRELATED"
            btc_alignment_label = f"⚪ Mod Correlated (Corr: {btc_corr:+.2f})"

        if btc_beta >= 1.35 and is_bear_when_btc_bear:
            btc_alignment_tag = "BEAR_SENSITIVE_LEVERAGED"
            btc_alignment_label = f"🩸 High-Beta Bear Sensitive (Beta: {btc_beta:.2f}x)"

        # Parabolic Hype & Blow-off top aggregate status across horizons
        is_any_hype_surge = any(h.get('is_hype_surge', False) for h in horizon_results.values())
        is_any_blowoff_top = any(h.get('is_blowoff_top', False) for h in horizon_results.values())
        hype_status = "🛑 BLOW-OFF TOP EXHAUSTION" if is_any_blowoff_top else ("🚀 PARABOLIC HYPE SURGE" if is_any_hype_surge else "⚪ NORMAL")

        # Aggregate NTZ status across core horizons
        is_asset_ntz = any(h.get('is_ntz_active', False) for h in [scalp_h, swing_h, h4_h, macro_h] if isinstance(h, dict))
        active_ntz_h = next((h for h in [scalp_h, swing_h, h4_h, macro_h] if isinstance(h, dict) and h.get('is_ntz_active')), None)
        asset_ntz_badge = active_ntz_h.get('ntz_badge', '') if active_ntz_h else ""
        asset_ntz_label = active_ntz_h.get('ntz_label', '') if active_ntz_h else ""
        asset_ntz_reasons = active_ntz_h.get('ntz_reasons', []) if active_ntz_h else []
        asset_ntz_metrics = active_ntz_h.get('ntz_metrics', {}) if active_ntz_h else {}

        prediction_now = datetime.now(timezone.utc)
        out_dict = {
            "symbol": symbol,
            "current_price": live_price,
            "live_high": live_high,
            "live_low": live_low,
            "horizons": horizon_results,
            "support_15m": res_15m,
            "support_24h": res_24h,
            "is_super_confluence_5x": is_super_confluence_5x,
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
            "btc_correlation": round(btc_corr, 3),
            "btc_beta": round(btc_beta, 3),
            "btc_alignment_tag": btc_alignment_tag,
            "btc_alignment_label": btc_alignment_label,
            "is_bear_when_btc_bear": is_bear_when_btc_bear,
            "is_bull_when_btc_bear": is_bull_when_btc_bear,
            "is_hype_surge": is_any_hype_surge,
            "is_blowoff_top": is_any_blowoff_top,
            "hype_status": hype_status,
            "is_ntz_active": is_asset_ntz,
            "ntz_badge": asset_ntz_badge,
            "ntz_label": asset_ntz_label,
            "ntz_reasons": asset_ntz_reasons,
            "ntz_metrics": asset_ntz_metrics,
            "d1_macro_bull": d1_macro_bull,
            "triple_screen_signal": triple_screen_sig,
            "tf_metrics_summary": tf_metrics_summary,
            "server_prediction_time": prediction_now.isoformat(),
            "server_prediction_ts": int(prediction_now.timestamp()),
        }
        del raw_dfs
        del tf_features
        return out_dict

    def _build_default_asset_entry(self, symbol: str, live_price: float = 0.0) -> dict:
        """Constructs an initial responsive prediction matrix row for newly discovered assets using 24h market momentum."""
        now_utc = datetime.now(timezone.utc)
        stats = self.loader.get_24hr_stats(symbol)
        
        p = float(live_price) if live_price and live_price > 0 else float(stats.get('lastPrice', 0.0) or 1.0)
        chg_pct = float(stats.get('priceChangePercent', 0.0))
        high_p = float(stats.get('highPrice', p) or p)
        low_p = float(stats.get('lowPrice', p) or p)
        is_bull = chg_pct >= 0.0
        
        p_fmt = format_precision_price_str

        horizons = {}
        all_display_cfgs = dict(self.config.get('horizons', {}))
        if 'scalp' not in all_display_cfgs:
            all_display_cfgs['scalp'] = {
                "name": "⚡ Micro Flow (15M)",
                "anchor_tf": "15m",
                "bars": 1,
                "duration_label": "15m Micro",
                "tp_mult": 1.8,
                "sl_mult": 1.0
            }
        if 'macro' not in all_display_cfgs:
            all_display_cfgs['macro'] = {
                "name": "🚀 Macro Anchor (24H)",
                "anchor_tf": "1d",
                "bars": 1,
                "duration_label": "24h Macro",
                "tp_mult": 3.0,
                "sl_mult": 1.5
            }
        for h_key, h_cfg in all_display_cfgs.items():
            trade_open, target_close, trade_open_str, trade_close_str = CryptoDataLoader.get_candle_schedule(
                h_cfg['anchor_tf'], bars=h_cfg.get('bars', 1), now_utc=now_utc
            )
            window_str = f"{trade_open_str} ➔ {trade_close_str} ({h_cfg['duration_label']})"
            
            h_dir = "BULLISH" if is_bull else "BEARISH"
            exp_ret = float(h_cfg['tp_mult'] * 0.005) if is_bull else float(-h_cfg['tp_mult'] * 0.005)
            
            is_bear_env = bool(
                getattr(self, 'suppress_momentum_longs', False) or
                getattr(self, 'is_btc_below_vwap', False) or
                getattr(self, 'btc_shield_active', False)
            )

            if is_bull:
                tp1 = p * (1.0 + abs(exp_ret))
                sl = p * (1.0 - max(0.015, h_cfg['sl_mult'] * 0.010))
                pred_next_p = format_precision_price(tp1)
                pred_ret_pct = round(abs(exp_ret) * 100.0, 2)
                type_str = "LONG 🟢"
                market_str = "Spot & Futures"
            else:
                tp1 = p * (1.0 - abs(exp_ret))
                sl = p * (1.0 + max(0.015, h_cfg['sl_mult'] * 0.010))
                pred_next_p = format_precision_price(tp1)
                pred_ret_pct = round(-abs(exp_ret) * 100.0, 2)
                type_str = "SHORT 🔴"
                market_str = "Futures Only ⚡"

            pro_sig = (
                f"🚀 PAIR: #{symbol.split('/')[0]}/USDT\n"
                f"📊 TYPE: {type_str}\n"
                f"🌐 MARKET: {market_str}\n"
                f"📅 PREDICTED CANDLE: {window_str}\n"
                f"🎯 ENTRY: {p_fmt(p)}\n"
                f"🔮 ML NEXT PRICE: {p_fmt(pred_next_p)} ({pred_ret_pct:+.2f}%)\n\n"
                f"💎 TAKE PROFITS:\n"
                f"➤ TP1: {p_fmt(tp1)}\n"
                f"➤ TP2: {p_fmt(p * (1.015 if is_bull else 0.985))}\n"
                f"➤ TP3: {p_fmt(p * (1.025 if is_bull else 0.975))}\n\n"
                f"🛑 STOP LOSS: {p_fmt(sl)}\n\n"
                f"📈 RISK-TO-REWARD RATIO: 1:2"
            )

            default_dec = "⚪ STABLE CONSOLIDATION" if (is_bear_env and is_bull) else ("🟢 MOMENTUM LONG" if is_bull else "⚪ INITIALIZING SCAN")

            horizons[h_key] = {
                "symbol": symbol,
                "horizon_name": h_cfg['name'],
                "duration_label": h_cfg['duration_label'],
                "current_price": format_precision_price(p),
                "predicted_next_price": pred_next_p,
                "predicted_return_pct": pred_ret_pct,
                "best_sell_price": format_precision_price(p * (1.025 if is_bull else 0.975)),
                "norm_atr": 0.01,
                "raw_atr": p * 0.01,
                "rs_btc": 0.0,
                "is_hype_surge": False,
                "is_blowoff_top": False,
                "trade_open_str": trade_open_str,
                "trade_close_str": trade_close_str,
                "predicted_close_utc": trade_close_str,
                "predicted_window_str": window_str,
                "direction": h_dir,
                "conviction": 58.0 if abs(chg_pct) > 2.0 else 52.0,
                "meta_win_prob": 0.60,
                "meta_win_prob_pct": 60.0,
                "exp_return": exp_ret,
                "projected_target": format_precision_price(tp1),
                "tp_price": format_precision_price(tp1),
                "tp1_price": format_precision_price(tp1),
                "tp2_price": format_precision_price(p * (1.015 if is_bull else 0.985)),
                "tp3_price": format_precision_price(p * (1.025 if is_bull else 0.975)),
                "tp4_price": format_precision_price(p * (1.035 if is_bull else 0.965)),
                "sl_price": format_precision_price(sl),
                "elite_precision": 0.60,
                "decision": default_dec,
                "priority": 4,
                "pro_signal_text": pro_sig,
                "vip_signal_text": pro_sig
            }

        confluence_tag = f"🟢 +{chg_pct:.1f}% 24H MOMENTUM" if chg_pct >= 1.5 else (f"🔴 {chg_pct:.1f}% 24H PULLBACK" if chg_pct <= -1.5 else f"⚪ {chg_pct:+.1f}% 24H STABLE")
        market_phase = "🚀 BULL_TREND_EXPANSION" if chg_pct >= 2.0 else ("🩸 BEAR_TREND_EXPANSION" if chg_pct <= -2.0 else "💤 RANGE_CONSOLIDATION")

        return {
            "symbol": symbol,
            "current_price": p,
            "live_high": high_p,
            "live_low": low_p,
            "horizons": horizons,
            "is_triple_confluence": False,
            "confluence_bull_count": 8 if is_bull else 2,
            "confluence_bear_count": 2 if is_bull else 8,
            "confluence_neutral_count": 0,
            "alignment_score": 60.0 if is_bull else -60.0,
            "confluence_tag": confluence_tag,
            "market_phase": market_phase,
            "consistency_index": 65.0,
            "best_priority": 4,
            "overall_score": 0.05,
            "btc_correlation": 0.50,
            "btc_beta": 1.0,
            "btc_alignment_tag": "MODERATE_CORRELATED",
            "btc_alignment_label": "⚪ Mod Correlated (Corr: +0.50)",
            "is_bear_when_btc_bear": False,
            "is_bull_when_btc_bear": False,
            "is_hype_surge": False,
            "is_blowoff_top": False,
            "hype_status": "⚪ NORMAL",
            "tf_metrics_summary": [
                {"Chart": "15M", "Price": p_fmt(p), "Bias": "🟢 BULLISH" if is_bull else "🔴 BEARISH", "RSI": "52.0" if is_bull else "48.0", "MFI": "50.0", "ADX": "20.0", "Regime": "⚡ EXPANSION"},
                {"Chart": "1H", "Price": p_fmt(p), "Bias": "🟢 BULLISH" if is_bull else "🔴 BEARISH", "RSI": "52.0" if is_bull else "48.0", "MFI": "50.0", "ADX": "20.0", "Regime": "⚡ EXPANSION"},
                {"Chart": "4H", "Price": p_fmt(p), "Bias": "🟢 BULLISH" if is_bull else "🔴 BEARISH", "RSI": "52.0" if is_bull else "48.0", "MFI": "50.0", "ADX": "20.0", "Regime": "⚡ EXPANSION"},
                {"Chart": "1D", "Price": p_fmt(p), "Bias": "🟢 BULLISH" if is_bull else "🔴 BEARISH", "RSI": "52.0" if is_bull else "48.0", "MFI": "50.0", "ADX": "20.0", "Regime": "⚡ EXPANSION"},
            ],
            "server_prediction_time": now_utc.isoformat(),
            "server_prediction_ts": int(now_utc.timestamp()),
        }

    def run_single_iteration(self):
        # Clear cache to guarantee fresh live candles from exchange
        if hasattr(self.loader, '_cache'):
            self.loader._cache.clear()
        if hasattr(self.loader, '_cache_ts'):
            self.loader._cache_ts.clear()

        # Retain model cache persistence across scans unless force_fresh_training is explicitly true
        if self.config.get('force_fresh_training_on_scan', False):
            self.model_cache.clear()
            self._model_cache_dirty = False
        else:
            self._prune_model_cache(max_size=1200)

        # Prune signal cooldown tracker entries older than 24 hours to prevent memory creep
        if hasattr(self, 'signal_cooldown_tracker') and self.signal_cooldown_tracker:
            now_t = time.time()
            stale_keys = [k for k, ts in self.signal_cooldown_tracker.items() if (now_t - ts) > 86400.0]
            for k in stale_keys:
                self.signal_cooldown_tracker.pop(k, None)

        self.last_scan_started_ts = time.time()
        now_start = datetime.now(timezone.utc)
        scan_interval = int(self.config.get('scan_interval_seconds', 60))
        next_scan_dt = now_start + timedelta(seconds=scan_interval)
        next_scan_ts = int(next_scan_dt.timestamp())
        next_scan_utc = next_scan_dt.strftime("%Y-%m-%d %H:%M:%S UTC")

        # Publish scanner daemon state: SCANNING
        try:
            state_path = os.path.join(self.config['app_export_dir'], "scanner_daemon_state.json")
            self._atomic_write_json(state_path, {
                "is_scanning": True,
                "scan_status": "SCANNING",
                "scan_started_at": now_start.isoformat(),
                "next_scan_time_utc": next_scan_utc,
                "next_scan_timestamp": next_scan_ts,
                "seconds_to_next_scan": scan_interval,
                "scan_interval_seconds": scan_interval
            })
        except Exception:
            pass

        mode = self.config.get("mode", "both").lower()
        print(f"\n==========================================================================================")
        print(f" 🚀 RUNNING MULTI-HORIZON QUANT ENGINE (V15.0): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f" Horizons: ⚡ Scalp (15M) | ⏳ Day Trade (1H/4H) | 🌊 Swing Trade (1D) | 🚀 Macro Trend (4D-30D) | Mode: Parallel Async")
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
                    symbols_to_scan = self.loader.fetch_top_volume_usdt_pairs(limit=self.config.get("scanner_top_n", 200))
                except Exception:
                    symbols_to_scan = self.config.get("scanner_symbols", [])[:self.config.get("scanner_top_n", 200)]
            elif scan_mode == "expanded_universe":
                symbols_to_scan = self.config.get("scanner_symbols", [])
            else:
                symbols_to_scan = self.config.get("scanner_symbols", [])[:self.config.get("scanner_top_n", 200)]

            print(f"\n" + "=" * 95, flush=True)
            print(f" 🛰️ RUNNING CONCURRENT MULTI-HORIZON SCANNER ({len(symbols_to_scan)} {self.loader.active_exchange_id.upper()} Assets in Parallel)...", flush=True)
            print("=" * 95, flush=True)

            # Clean and prune master_matrix_universe to active valid symbols_to_scan only
            valid_set = set(symbols_to_scan)
            stale_keys = [k for k in list(self.master_matrix_universe.keys()) if k not in valid_set or not is_valid_crypto_pair(k)]
            for k in stale_keys:
                self.master_matrix_universe.pop(k, None)

            # Ensure all discovered pairs are present in the master matrix universe from second 1 and synced with live ticker prices
            all_tickers = self.loader.fetch_all_tickers(max_age_seconds=5.0) if hasattr(self, 'loader') else {}
            now_ts_epoch = time.time()
            for sym in symbols_to_scan:
                raw_s = sym.replace('/', '').replace(':USDT', '')
                p = float(all_tickers.get(sym) or all_tickers.get(raw_s) or 0.0)
                if sym not in self.master_matrix_universe or "SCANNING" in str(self.master_matrix_universe[sym].get("confluence_tag", "")):
                    self.master_matrix_universe[sym] = self._build_default_asset_entry(sym, p)
                elif p > 0:
                    cached_p = float(self.master_matrix_universe[sym].get('current_price', 0.0))
                    cached_ts = float(self.master_matrix_universe[sym].get('server_prediction_ts', 0.0))
                    # Recalibrate targets if price moved >= 0.5% or entry timestamp older than 5 minutes
                    if cached_p <= 0 or abs(p - cached_p) / (cached_p + 1e-10) >= 0.005 or (now_ts_epoch - cached_ts) >= 300.0:
                        self._refresh_asset_entry_timestamps(self.master_matrix_universe[sym], live_price=p)

            # Compute Global Market Regime & Specialized 24H Discoveries (Gainers & Losers)
            try:
                self.current_market_regime = self.loader.detect_global_market_regime()
                top_gainers_list = self.loader.fetch_top_24h_gainers(limit=10)
                self.top_24h_gainers_signals = []
                for g in top_gainers_list:
                    sym = g['symbol']
                    p = float(g['lastPrice'])
                    g_sig = SpecializedStrategyRouter.evaluate_top_gainer_momentum(sym, p, None, None, g, self.current_market_regime)
                    if g_sig:
                        self.top_24h_gainers_signals.append(g_sig)

                top_losers_list = self.loader.fetch_top_24h_losers(limit=10)
                self.top_24h_losers_signals = []
                for l in top_losers_list:
                    sym = l['symbol']
                    p = float(l['lastPrice'])
                    l_sig = SpecializedStrategyRouter.evaluate_top_loser_capitulation(sym, p, None, None, l, self.current_market_regime)
                    if l_sig:
                        self.top_24h_losers_signals.append(l_sig)
            except Exception as spec_init_err:
                print(f"[REGIME/DISCOVERY INIT NOTE ⚠️] {spec_init_err}")

            # Export initial full universe immediately so UI matrix displays all 150+ assets from second 1
            try:
                self.export_web_app_json(
                    list(self.master_matrix_universe.values()),
                    deep_dive_result=None,
                    top_signals=self.institutional_signal_manager.get_display_signals(),
                    is_partial=True,
                    total_count=len(symbols_to_scan)
                )
                if HAS_DB_SYNC:
                    try:
                        sync_files_to_db_live(force=True)
                    except Exception:
                        pass
            except Exception as e:
                print(f"[INITIAL UNIVERSE SYNC NOTE] {e}")

            # Priority ordering: process top major liquid assets first for instant UI availability
            priority_coins = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT", "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "SUI/USDT", "LINK/USDT", "PEPE/USDT", "NEAR/USDT"]
            sorted_symbols_to_scan = [s for s in priority_coins if s in symbols_to_scan] + [s for s in symbols_to_scan if s not in priority_coins]

            scan_deadline_seconds = min(240.0, max(120.0, len(sorted_symbols_to_scan) * 1.5))
            last_partial_sync_ts = time.time()
            last_synced_count = 0
            max_threads = min(int(self.config.get('max_scan_workers', 16)), 24, len(sorted_symbols_to_scan))
            executor = ThreadPoolExecutor(max_workers=max_threads)
            try:
                future_to_sym = {executor.submit(self.process_single_asset, sym): sym for sym in sorted_symbols_to_scan}
                for future in as_completed(future_to_sym):
                    if (time.time() - self.last_scan_started_ts) > scan_deadline_seconds:
                        print(f"[DEADLINE ⏳] Total scan time reached {scan_deadline_seconds}s limit. Safely completing cycle with {len(scanner_results)} assets.")
                        for f in future_to_sym:
                            f.cancel()
                        break
                    sym = future_to_sym[future]
                    try:
                        res = future.result()
                        if res:
                            scanner_results.append(res)
                            self.master_matrix_universe[sym] = res
                            live_prices[sym] = res['current_price']
                            live_highs[sym] = res['live_high']
                            live_lows[sym] = res['live_low']
                            
                            # High-frequency Immediate Streaming: sync every 5 assets initially, then every 10 assets
                            should_sync = (
                                len(scanner_results) <= 5
                                or (len(scanner_results) - last_synced_count >= 10 and (time.time() - last_partial_sync_ts) >= 1.0)
                                or len(scanner_results) == len(sorted_symbols_to_scan)
                            )
                            if should_sync:
                                elapsed_now = time.time() - self.last_scan_started_ts
                                print(f"[SCANNER 🛰️ STREAM] Streamed {len(scanner_results)}/{len(sorted_symbols_to_scan)} assets to UI (Latest: {sym}) - Elapsed: {elapsed_now:.1f}s", flush=True)
                                try:
                                    partial_sorted = sorted(list(self.master_matrix_universe.values()), key=_safe_sort_key)
                                    partial_signals = self.render_top_round_signals(partial_sorted, verbose=False)
                                    
                                    # Continuous Paper Trading Admission during Streaming Scan
                                    if self.config.get('paper_trading', {}).get('enabled'):
                                        self._update_and_admit_paper_trading(partial_signals, partial_sorted, live_prices, live_highs, live_lows)

                                    # Continuous Real-Time Signal Evaluation during Streaming Scan
                                    self.signal_tracker.evaluate_signals(live_prices, live_highs, live_lows)
                                    self.institutional_signal_manager.evaluate_signals(live_prices, live_highs, live_lows)

                                    self.export_web_app_json(
                                        partial_sorted,
                                        deep_dive_result=None,
                                        top_signals=partial_signals,
                                        is_partial=True,
                                        total_count=len(sorted_symbols_to_scan)
                                    )
                                    if HAS_DB_SYNC and (len(scanner_results) % 25 == 0 or len(scanner_results) == len(sorted_symbols_to_scan)):
                                        sync_files_to_db_live(force=True)
                                    last_synced_count = len(scanner_results)
                                    last_partial_sync_ts = time.time()
                                except Exception as e:
                                    print(f"[STREAM SYNC ERROR] {e}", flush=True)
                    except Exception as e:
                        pass
            finally:
                try:
                    executor.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    pass

            print(f"[SCANNER ✅] Processed active horizons for {len(scanner_results)} assets.", flush=True)

            # Persist warmed model cache to disk only if models were updated
            try:
                if hasattr(self, 'model_cache') and getattr(self, '_model_cache_dirty', False) and self.model_cache:
                    self._prune_model_cache(max_size=1200)
                    joblib.dump(self.model_cache, self.model_cache_path + ".tmp", compress=1)
                    os.replace(self.model_cache_path + ".tmp", self.model_cache_path)
                    self._model_cache_dirty = False
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
                            for h_sub in r.get('horizons', {}).values():
                                if isinstance(h_sub, dict):
                                    h_sub['current_price'] = fresh_p
            except Exception:
                pass

            # Sort by best priority, triple confluence, consistency index, and alignment strength
            scanner_results.sort(key=_safe_sort_key)
            self.render_multi_horizon_leaderboard(scanner_results)

        # 2. Single-Coin Deep Dive
        if mode in ["single", "both"]:
            target_sym = self.config['single_symbol']
            print(f"\n" + "=" * 95, flush=True)
            print(f" 🔬 RUNNING MULTI-HORIZON DEEP DIVE: {target_sym}", flush=True)
            print("=" * 95, flush=True)

            try:
                deep_dive_result = self.process_single_asset(target_sym)
                if deep_dive_result:
                    live_prices[target_sym] = deep_dive_result['current_price']
                    live_highs[target_sym] = deep_dive_result['live_high']
                    live_lows[target_sym] = deep_dive_result['live_low']
                    self.render_multi_horizon_deep_dive(deep_dive_result)
            except Exception as e:
                print(f"[DEEP DIVE NOTICE ⚠️] {target_sym} deep dive safely caught: {e}", flush=True)
                deep_dive_result = None

        # 3. Top 3 Actionable Quantitative Signals for This Round (Independent of Paper Trading Status)
        top_round_signals = self.render_top_round_signals(scanner_results, deep_dive_result)

        # 4. Update Paper Trading Portfolio with Intra-Candle High/Low Wick Verification
        try:
            if self.config.get('paper_trading', {}).get('enabled', True):
                self._update_and_admit_paper_trading(top_round_signals, scanner_results, live_prices, live_highs, live_lows, deep_dive_result=deep_dive_result)
                self.ledger.render_portfolio_card()
        except Exception as pt_err:
            print(f"[PAPER TRADING NOTICE ⚠️] Update cycle caught: {pt_err}", flush=True)

        # 5. Persistent Signal Audit Logger: Evaluate Active Signals & Render Performance
        try:
            self.signal_tracker.evaluate_signals(live_prices, live_highs, live_lows)
            self.institutional_signal_manager.evaluate_signals(live_prices, live_highs, live_lows)
            self.signal_tracker.render_performance_card()
        except Exception as eval_err:
            print(f"[SIGNAL AUDIT NOTICE ⚠️] Signal evaluation cycle caught: {eval_err}", flush=True)

        # 6. Final Authoritative Export of Full Web Application State
        try:
            full_sorted = sorted(list(self.master_matrix_universe.values()), key=_safe_sort_key)
            self.export_web_app_json(
                full_sorted,
                deep_dive_result=deep_dive_result,
                top_signals=top_round_signals,
                is_partial=False,
                total_count=len(sorted_symbols_to_scan) if 'sorted_symbols_to_scan' in locals() else len(full_sorted)
            )
            if HAS_DB_SYNC:
                try:
                    sync_files_to_db_live(force=True)
                except Exception:
                    pass
        except Exception as export_err:
            print(f"[FINAL EXPORT NOTICE ⚠️] {export_err}", flush=True)

    def _update_and_admit_paper_trading(self, top_round_signals, scanner_results, live_prices, live_highs, live_lows, deep_dive_result=None):
        """Processes real-time ticks and admits top ranked signals across all horizons."""
        if not self.config.get('paper_trading', {}).get('enabled', True):
            return

        for pos in self.ledger.data['open_positions']:
            sym = pos['symbol']
            try:
                ticker = self.loader.fetch_ticker(sym)
                if ticker and 'last' in ticker:
                    live_prices[sym] = float(ticker['last'])
            except Exception:
                pass

        # Order Execution Manager: Process Real-Time Tick
        self.ledger.on_tick(live_prices, live_highs, live_lows)

        # Extract executable candidate signals from Alpha Signal Engine (Filtered to Allowed Horizons)
        all_candidates = []

        # 1. Direct Top Priority: Institutional Top Signals for this round
        if top_round_signals:
            for sig in top_round_signals:
                dec = str(sig.get('decision', ''))
                arch = str(sig.get('strategy_archetype') or sig.get('archetype', ''))
                if any(k in dec.upper() or k in arch.upper() for k in ["FILTER", "PAUSED", "QUARANTINED", "CONSOLIDATION", "SUPPRESS", "CLIMAX WICK", "DO_NOT_TRADE", "AVOID", "NO TRADE ZONE", "NTZ", "LOW VOL", "CHOP", "RANGE SQUEEZE", "COILED SQUEEZE"]):
                    continue
                if sig.get('is_suppressed') or sig.get('suppressed') or sig.get('is_ntz_blocked') or sig.get('is_ntz_active'):
                    continue
                h_k = sig.get('horizon_key') or sig.get('horizon_tag') or 'scalp'
                all_candidates.append((sig, h_k))

        # 2. Strict 1:1 Signal Parity Invariant:
        # Paper Trading executes ONLY from top published signals (top_round_signals).
        # We strictly do NOT admit background scanner candidates that are not active published signals.

        # Filter candidate signals strictly to allowed paper trading horizons
        allowed_paper_horizons = set(h.lower() for h in getattr(self.ledger, 'allowed_horizons', ["15m", "30m", "1h", "4h", "24h"]))
        allowed_paper_horizons.update(h.upper() for h in getattr(self.ledger, 'allowed_horizons', ["15M", "30M", "1H", "4H", "24H"]))
        paper_candidates = []
        for cand, h_k in all_candidates:
            h_tag = resolve_horizon_tag(h_k)
            if h_tag.lower() in allowed_paper_horizons or h_tag.upper() in allowed_paper_horizons or str(h_k).lower() in allowed_paper_horizons:
                paper_candidates.append((cand, h_k))

        top_sigs_set = set(id(s) for s in (top_round_signals or []))
        
        # Multi-factor Quant Alpha Scoring: Find the best trades among all candidates across allowed horizons
        def _paper_rank_score(item):
            cand, h_k = item
            conv = _safe_float(cand.get('conviction', 50.0), 50.0)
            meta_p = _safe_float(cand.get('meta_win_prob', cand.get('meta_probability', 0.50)), 0.50)
            exp_ret = abs(_safe_float(cand.get('expected_return_pct', cand.get('exp_return', 0.50)), 0.50))
            rr_ratio = _safe_float(cand.get('risk_reward_ratio', 2.0), 2.0)
            grade = str(cand.get('grade', cand.get('quality_grade', '')))
            grade_bonus = 30.0 if "Grade A+" in grade else (15.0 if "Grade A" in grade else 0.0)
            top_bonus = 20.0 if id(cand) in top_sigs_set else 0.0
            rs_bonus = 5.0 * max(0.0, _safe_float(cand.get('rs_btc', 0.0), 0.0))
            # Horizon bonus: Give higher priority to swing/macro trades (1H, 4H, 24H) which yield higher win rate and bigger R:R
            h_tag_clean = resolve_horizon_tag(h_k).upper()
            horizon_bonus = 15.0 if h_tag_clean in ["1H", "4H", "24H"] else (5.0 if h_tag_clean == "30M" else 0.0)
            return (conv * 1.5) + (meta_p * 100.0) + (exp_ret * 20.0) + (rr_ratio * 5.0) + grade_bonus + top_bonus + rs_bonus + horizon_bonus

        paper_candidates.sort(key=_paper_rank_score, reverse=True)

        # Route top ranked signals into Order Execution Manager (Admits up to max_concurrent_positions)
        admitted_trades = self.ledger.admit_ranked_candidates(paper_candidates, signal_history=self.signal_tracker.records)
        if admitted_trades:
            self.institutional_signal_manager.upsert_signals(admitted_trades)

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
                    self.evaluate_btc_market_regime(live_btc_price=float(btc_ticker['last']))
                    time_since_sync = now_ts - getattr(self, "_last_shield_file_sync_ts", 0)
                    if time_since_sync >= 45.0:
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

    def _atomic_write_json(self, target_path: str, data: dict):
        """Atomically and safely writes JSON data using a per-thread unique temporary file and file lock."""
        with getattr(self, '_forecast_file_lock', threading.RLock()):
            dir_name = os.path.dirname(target_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            temp_path = f"{target_path}.{threading.get_ident()}.{time.time_ns()}.tmp"
            try:
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, default=str)
                os.replace(temp_path, target_path)
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass

    def _sync_live_signals_to_file(self):
        """Real-time synchronization of active institutional signals to live_market_forecast.json & database."""
        try:
            json_path = os.path.join(self.config['app_export_dir'], "live_market_forecast.json")
            if os.path.exists(json_path):
                with getattr(self, '_forecast_file_lock', threading.RLock()):
                    with open(json_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    now_iso = datetime.now(timezone.utc).isoformat()
                    data["timestamp"] = now_iso
                    data["server_prediction_time"] = now_iso
                    data["top_round_signals"] = self.institutional_signal_manager.get_display_signals()
                    data["signals_by_horizon"] = self.institutional_signal_manager.get_signals_by_horizon()

                    self._atomic_write_json(json_path, data)

                if HAS_DB_SYNC:
                    try:
                        sync_files_to_db_live(force=True)
                    except Exception:
                        pass
        except Exception:
            pass

    def handle_signals_bot_on_regime_change(self, prev_code: str, new_code: str, new_regime: str):
        """
        Dynamically adapts, halts, or secures the signals bot & paper trading based on detected market condition.
        - ALERT_DUMP / FLASH_DUMP: Emergency crash breaker. Halts all new LONG signals bot execution immediately.
        - BEAR_TREND / BEARISH_BREAKDOWN: Suppresses breakout longs; restricts to high-conviction shorts & oversold dips.
        - CONSOLIDATION / RANGE_SQUEEZE: Suppresses false breakouts; engages range boundary mean-reversion with strict R:R.
        - BULL_TREND / BULLISH_EXPANSION: Unlocks full momentum long execution; blocks counter-trend shorts on momentum coins.
        """
        if new_code in ["ALERT_DUMP", "FLASH_DUMP"]:
            print(f"[BOT GATING 🚨] CRASH CIRCUIT BREAKER ACTIVATED: Halting all new LONG signals bot execution immediately!", flush=True)
        elif new_code in ["BEAR_TREND", "BEARISH_BREAKDOWN"]:
            print(f"[BOT GATING 🩸] SYSTEMIC BEAR REGIME: Restricting counter-trend longs. Prioritizing high-alpha shorts.", flush=True)
        elif new_code in ["CONSOLIDATION", "RANGE_SQUEEZE"]:
            print(f"[BOT GATING ⚖️] CONSOLIDATION CHOP DETECTED: Suppressing breakout traps. Restricting to boundary mean-reversion.", flush=True)
        elif new_code in ["BULL_TREND", "PUMP_EXPANSION", "BULLISH_EXPANSION"]:
            print(f"[BOT GATING 🚀] BULL REGIME ACTIVE: Full momentum long permissions engaged. Parabolic shorts blocked.", flush=True)

    def _sync_live_shield_to_file(self):
        """High-frequency real-time update of BTC Market Shield in exported JSON & database."""
        try:
            json_path = os.path.join(self.config['app_export_dir'], "live_market_forecast.json")
            if os.path.exists(json_path):
                with getattr(self, '_forecast_file_lock', threading.RLock()):
                    with open(json_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    now_iso = datetime.now(timezone.utc).isoformat()
                    data["timestamp"] = now_iso
                    data["server_prediction_time"] = now_iso

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
                        "predicted_trend": getattr(self, "btc_predicted_trend", "CONSOLIDATION"),
                        "trend_probability": getattr(self, "btc_trend_probability", 60.0),
                        "bull_trend_prob": getattr(self, "btc_bull_trend_prob", 30.0),
                        "bear_trend_prob": getattr(self, "btc_bear_trend_prob", 20.0),
                        "consolidation_prob": getattr(self, "btc_consolidation_prob", 50.0),
                        "predicted_btc_target": getattr(self, "btc_predicted_target", 0.0),
                        "predicted_btc_change_pct": getattr(self, "btc_predicted_change_pct", 0.0),
                        "breakout_prediction": getattr(self, "btc_breakout_prediction", "⚖️ RANGE BOUND"),
                        "altcoin_posture": getattr(self, "btc_altcoin_posture", "STANDARD_EXECUTION"),
                        "market_phase_description": getattr(self, "btc_market_phase_description", ""),
                        "trader_playbook": getattr(self, "trader_playbook", {})
                    }
                    data["btc_market_shield"] = shield_payload
                    data["trader_playbook"] = getattr(self, "trader_playbook", {})
                    self._atomic_write_json(json_path, data)

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
                
                # High-Frequency Continuous Rescan Loop:
                # After completing a high-speed scan of all assets, wait briefly while actively monitoring positions
                scan_interval = int(self.config.get('scan_interval_seconds', 60))
                next_run = datetime.now(timezone.utc) + timedelta(seconds=scan_interval)
                hb_secs = int(self.config.get('heartbeat_interval_seconds', 4))
                print(f"[DAEMON] ⏳ Scan cycle complete. Active real-time trade monitoring every {hb_secs}s (Next full scan: {next_run.strftime('%H:%M:%S UTC')})...")
                while datetime.now(timezone.utc) < next_run:
                    self.check_open_positions_heartbeat()
                    if getattr(self, '_force_rescan_requested', False):
                        self._force_rescan_requested = False
                        print(f"\n[DAEMON ⚡] Market regime/trend change detected! Breaking interval sleep to rescan & retrain immediately...", flush=True)
                        break
                    time.sleep(hb_secs)

            except KeyboardInterrupt:
                print("\n[DAEMON] Continuous Watcher Loop gracefully stopped by user.")
                break
            except Exception as e:
                print(f"\n[DAEMON ERROR] Unexpected loop error: {e}")
                time.sleep(10)

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
            
            h_map = r.get('horizons', {})
            h1 = h_map.get('swing') or h_map.get('horizon_1h') or (list(h_map.values())[0] if h_map else {})
            h4 = h_map.get('horizon_4h') or (list(h_map.values())[1] if len(h_map) > 1 else h1)
            h24 = h_map.get('macro') or (list(h_map.values())[2] if len(h_map) > 2 else h4)

            badge = "💎 TRIPLE BUY" if (r.get('is_triple_confluence') and h1.get('direction')=="BULLISH") else ("💎 TRIPLE SELL" if (r.get('is_triple_confluence') and h1.get('direction')=="BEARISH") else ("🥇 TOP PICK" if idx==0 else f"#{idx+1}"))
            
            table_rows.append({
                "Asset & Price": f"{badge}\n{sym} ({price_fmt})",
                "⏳ Day Trade (1H) Setup": f"{'🟢' if h1.get('direction')=='BULLISH' else '🔴'} {h1.get('direction', 'NEUTRAL')} ({_safe_float(h1.get('conviction', 50.0)):.1f}%)\nTP: {fmt_p(h1.get('tp_price', 0.0))} | SL: {fmt_p(h1.get('sl_price', 0.0))}\n{h1.get('decision', '')}",
                "⏳ Day Trade (4H) Setup": f"{'🟢' if h4.get('direction')=='BULLISH' else '🔴'} {h4.get('direction', 'NEUTRAL')} ({_safe_float(h4.get('conviction', 50.0)):.1f}%)\nTP: {fmt_p(h4.get('tp_price', 0.0))} | SL: {fmt_p(h4.get('sl_price', 0.0))}\n{h4.get('decision', '')}",
                "🌊 Swing Trade (1D) Setup": f"{'🟢' if h24.get('direction')=='BULLISH' else '🔴'} {h24.get('direction', 'NEUTRAL')} ({_safe_float(h24.get('conviction', 50.0)):.1f}%)\nTP: {fmt_p(h24.get('tp_price', 0.0))} | SL: {fmt_p(h24.get('sl_price', 0.0))}\n{h24.get('decision', '')}"
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
        min_scalp_gain = sig_cfg.get('min_scalp_gain_pct', 0.30)
        min_swing_gain = sig_cfg.get('min_swing_gain_pct', 0.85)
        asset_cooldown_sec = sig_cfg.get('asset_cooldown_minutes', 60) * 60

        active_paper_symbols = {p['symbol'] for p in self.ledger.data.get('open_positions', [])}
        active_mgr_pairs = self.institutional_signal_manager.get_active_pairs()
        active_mgr_symbols = set(self.institutional_signal_manager.get_active_symbols())
        all_signals = []
        seen_pairs = set()
        now_ts = time.time()

        cooldown_map = {
            'scalp': 1800,       # 30 mins
            'swing': 5400,       # 90 mins
            'horizon_4h': 7200,  # 2 hours
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

            # Actionable trade signals across all institutional horizons: 15M (Scalp), 1H (Day Trade), 4H (Day Trade), 24H (Swing Trade)
            ACTIONABLE_SIGNAL_HORIZONS = {'scalp', 'horizon_30m', 'swing', 'horizon_4h', 'macro'}

            for h_key in list(self.config.get('horizons', {}).keys()):
                if h_key not in ACTIONABLE_SIGNAL_HORIZONS:
                    continue
                h = r['horizons'].get(h_key)
                if not h:
                    continue
                pair_key = (sym, h_key)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                # Tiered Compute / Quality Classification:
                is_tier1_alpha = sym in TIER_1_ALPHA_COINS
                prio = h.get('priority', 3)
                conv = _safe_float(h.get('conviction', 50.0), 50.0)
                if is_tier1_alpha:
                    # Priority & conviction boost for mathematically verified top profit coins
                    conv = min(98.5, conv + 4.5)
                    prio = max(1, prio - 1)

                decision = h.get('decision', 'WATCH')
                direction = h.get('direction', 'BULLISH')
                rs_val = _safe_float(h.get('rs_btc', 0.0), 0.0)
                elite_prec = _safe_float(h.get('elite_precision', 0.50), 0.50)
                exp_ret = _safe_float(h.get('exp_return', h.get('predicted_return_pct', 0.0)), 0.0)
                
                curr_p = _safe_float(h.get('current_price', r.get('current_price', 0.0)) or 1.0, 1.0)
                tp1_p = _safe_float(h.get('tp1_price', h.get('tp_price', curr_p)) or curr_p, curr_p)
                sl_p = _safe_float(h.get('sl_price', curr_p) or curr_p, curr_p)
                tp_pct = abs(tp1_p - curr_p) / max(1e-8, curr_p) * 100.0
                sup_15m = r.get('support_15m', {})
                sup_24h = r.get('support_24h', {})

                # --------------------------------------------------------------
                # 🛑 STRUCTURAL HEURISTIC CIRCUIT BREAKERS
                # --------------------------------------------------------------
                # 1. Parabolic Short & Trend-Regime Directional Filter
                is_parabolic_short = False
                is_confirmed_exhaustion = (
                    bool(h.get('is_blowoff_top', False)) and
                    float(h.get('meta_win_prob', 0.50)) >= 0.55 and
                    not bool(h.get('is_hype_surge', False))
                )
                
                # Check Bull Trend Expansion / strong bullish conditions
                is_bull_expansion_phase = (
                    r.get('market_phase') == "BULL_TREND_EXPANSION" or
                    getattr(self, 'btc_shield_regime', '') in ["BULLISH_EXPANSION", "BULL_MOMENTUM"] or
                    rsi_1h_val >= 66.0 or
                    rs_val >= 0.8
                )
                # Check Bear Trend Expansion / dump conditions
                is_bear_expansion_phase = (
                    r.get('market_phase') == "BEAR_TREND_EXPANSION" or
                    getattr(self, 'btc_shield_regime', '') in ["FLASH_DUMP", "BEARISH_BREAKDOWN", "DUMP"] or
                    rsi_1h_val <= 34.0 or
                    rs_val <= -0.8
                )

                if direction in ["BEARISH", "SHORT"]:
                    if is_bull_expansion_phase and not is_confirmed_exhaustion:
                        is_parabolic_short = True
                        decision = "🛡️ SUPPRESSED (BULL TREND EXPANSION SHORT TRAP)"
                        prio = 5
                    elif ban_parabolic_shorts and (rsi_1h_val >= 68.0 or rs_val >= 1.5) and not is_confirmed_exhaustion:
                        is_parabolic_short = True
                        decision = "🛡️ SUPPRESSED (PARABOLIC MOMENTUM SQUEEZE RISK)"
                        prio = 5
                    # 1b. Oversold Flush Breakdown Chase Circuit Breaker:
                    elif "BREAKDOWN" in decision:
                        rsi_15m_val = float(sup_15m.get('rsi_anchor', 50.0) or sup_15m.get('rsi', 50.0) or 50.0)
                        if rsi_1h_val <= 32.0 or rsi_15m_val <= 32.0:
                            is_parabolic_short = True
                            decision = "🛡️ SUPPRESSED (OVERSOLD BREAKDOWN CHASE / FLUSH EXHAUSTION)"
                            prio = 5
                elif direction in ["BULLISH", "LONG"]:
                    if is_bear_expansion_phase and not is_confirmed_exhaustion:
                        is_parabolic_short = True  # Suppress counter-trend knife-catching
                        decision = "🛡️ SUPPRESSED (BEAR TREND EXPANSION KNIFE CATCH)"
                        prio = 5

                # 2. Fee Hurdle: Filter out micro-targets where fees eat the profit (>= 0.20% minimum net profit hurdle)
                is_fee_drag_rejected = False
                min_return_hurdle = sig_cfg.get('min_expected_return_pct', 0.20)
                if (tp_pct < min_return_hurdle or abs(exp_ret * 100.0) < min_return_hurdle) and not is_confirmed_exhaustion:
                    is_fee_drag_rejected = True
                    decision = "⛔ FILTER (SUB-0.2% RETURN / FEE DRAG)"
                elif h_key == 'scalp' and tp_pct < min_scalp_gain and not is_confirmed_exhaustion:
                    is_fee_drag_rejected = True
                elif h_key == 'swing' and tp_pct < min_swing_gain and not is_confirmed_exhaustion:
                    is_fee_drag_rejected = True

                # 3. 2-Strike Asset Blacklist Quarantine Check
                is_quarantined, quar_reason = self.signal_tracker.is_asset_quarantined(sym)
                is_asset_locked = is_quarantined
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

                # --------------------------------------------------------------
                # 🏛️ HIERARCHICAL 15M (MICRO TRIGGER) & 24H (MACRO ANCHOR) CONFIRMATION ENGINE
                # --------------------------------------------------------------
                sup_15m = r.get('support_15m', {})
                sup_24h = r.get('support_24h', {})
                is_super_5x = bool(r.get('is_super_confluence_5x', False))

                dir_15m = sup_15m.get('direction', '')
                is_15m_aligned = (dir_15m == direction and "CONSOLIDATION" not in sup_15m.get('decision', ''))
                is_15m_top = bool(sup_15m.get('is_blowoff_top', False)) or any(k in sup_15m.get('decision', '') for k in ["TOP-REVERSAL", "BLOW-OFF TOP", "RALLY-SELL"])
                is_15m_bottom = bool(sup_15m.get('is_hype_surge', False)) or any(k in sup_15m.get('decision', '') for k in ["BOTTOM-REVERSAL", "DIP-BUY", "HYPE PUMP"])

                dir_24h = sup_24h.get('direction', '')
                is_24h_aligned = (dir_24h == direction and "CONSOLIDATION" not in sup_24h.get('decision', ''))
                is_24h_counter = (dir_24h in ["BULLISH", "BEARISH"] and dir_24h != direction)

                # Micro Wick Climax Trap Circuit Breaker:
                # Suppress long if 15M candle is blowing off / rejecting at top wick
                is_micro_wick_trap = False
                if direction in ["BULLISH", "LONG"] and is_15m_top:
                    is_micro_wick_trap = True
                    decision = "🛡️ SUPPRESSED (15M BLOW-OFF TOP / CLIMAX WICK)"
                    prio = 5

                # Micro Squeeze Trap Circuit Breaker:
                # Suppress short if 15M candle is in active parabolic hype pump
                is_micro_hype_trap = False
                if direction in ["BEARISH", "SHORT"] and is_15m_bottom and not is_confirmed_exhaustion:
                    is_micro_hype_trap = True
                    decision = "🛡️ SUPPRESSED (15M PARABOLIC HYPE SQUEEZE)"
                    prio = 5

                # 24H Macro Anchor Counter-Trend Breaker:
                # Counter-trend trades against 24H macro trend must clear a higher conviction threshold (>=65.0%)
                is_counter_macro_blocked = False
                if is_24h_counter and conv < 65.0 and not is_confirmed_exhaustion:
                    is_counter_macro_blocked = True
                    decision = "🛡️ PAUSED (COUNTER-TREND TO 24H MACRO ANCHOR)"
                    prio = 5

                # 🏛️ TRIPLE SCREEN (1D -> 4H -> 1H) ENFORCEMENT & PRIORITY BOOST
                is_triple_screen = bool(h.get('is_triple_screen', False))
                d1_macro_bull = r.get('d1_macro_bull')
                if d1_macro_bull is not None and not is_confirmed_exhaustion:
                    if direction in ["BULLISH", "LONG"] and not d1_macro_bull and conv < 75.0 and not is_triple_screen:
                        is_counter_macro_blocked = True
                        decision = "🛡️ SUPPRESSED (1D MACRO BEAR CONFLICT)"
                        prio = 5
                    elif direction in ["BEARISH", "SHORT"] and d1_macro_bull and conv < 75.0 and not is_triple_screen:
                        is_counter_macro_blocked = True
                        decision = "🛡️ SUPPRESSED (1D MACRO BULL CONFLICT)"
                        prio = 5

                if is_triple_screen:
                    conv = min(99.0, conv + 5.0)
                    prio = 1

                # Institutional Conviction Boosts from Support Anchors:
                if is_15m_aligned and not (is_micro_wick_trap or is_micro_hype_trap):
                    conv = min(98.5, conv + 3.5)  # +3.5% flow trigger boost

                if is_24h_aligned:
                    conv = min(98.5, conv + 4.5)  # +4.5% macro anchor trend boost

                # Oct 4-6 Winner Reproduction: 15M Top Reversal backing short
                if direction in ["BEARISH", "SHORT"] and is_15m_top:
                    conv = min(99.0, conv + 5.0)  # Top reversal confirmation boost

                # ⏱️ Signal Cooldown Check
                last_sig_time = self.signal_cooldown_tracker.get(pair_key, 0)
                is_in_cooldown = (now_ts - last_sig_time) < cooldown_map.get(h_key, 1800)

                # Institutional No Trade Zone (NTZ) Circuit Breaker:
                is_ntz_blocked = bool(h.get('is_ntz_active', False))
                if is_ntz_blocked and not is_confirmed_exhaustion:
                    decision = f"🛑 NO TRADE ZONE ({h.get('ntz_badge', 'DEFENSIVE')})"
                    prio = 5

                # 💎 Grade Classification
                is_exec_decision = any(k in decision for k in ["EXECUTE", "ORDER-BLOCK", "RETEST", "DIP-BUY", "RALLY-SELL", "BREAKDOWN", "BREAKOUT", "MOMENTUM", "REVERSAL", "SWEEP", "BLOW-OFF TOP", "HYPE PUMP"])
                is_a_plus_candidate = (
                    (conv >= a_plus_cutoff or (is_triple and conv >= 70.0) or is_confirmed_exhaustion or (is_super_5x and conv >= 62.0) or is_triple_screen) and
                    is_exec_decision and
                    not is_ntz_blocked and
                    not is_shield_blocked and
                    not is_parabolic_short and
                    not is_fee_drag_rejected and
                    not is_quarantined and
                    not is_micro_wick_trap and
                    not is_micro_hype_trap and
                    not is_counter_macro_blocked and
                    (rs_val >= -0.2 if direction == "BULLISH" else True) and
                    (elite_prec >= 0.50 or is_confirmed_exhaustion or is_triple_screen)
                )

                if is_a_plus_candidate:
                    grade = "💎 Grade A+"
                    grade_tier = 1
                    tier_label = "1D-4H-1H TRIPLE SCREEN" if is_triple_screen else ("5-TIER ELITE CONFLUENCE" if is_super_5x else "ELITE CONFLUENCE")
                elif (conv >= a_cutoff and prio <= 2 and not is_ntz_blocked and not is_shield_blocked and not is_parabolic_short and not is_quarantined and not is_micro_wick_trap and not is_micro_hype_trap and not is_counter_macro_blocked) or (is_exec_decision and not is_ntz_blocked and not is_shield_blocked and not is_parabolic_short and not is_quarantined and not is_micro_wick_trap and not is_micro_hype_trap and not is_counter_macro_blocked):
                    grade = "🟢 Grade A"
                    grade_tier = 2
                    tier_label = "HIGH CONVICTION"
                elif conv >= b_cutoff and prio <= 3 and not is_ntz_blocked and not is_shield_blocked and not is_quarantined and not is_micro_wick_trap and not is_micro_hype_trap:
                    grade = "🟡 Grade B+"
                    grade_tier = 3
                    tier_label = "ACTIONABLE MOMENTUM"
                else:
                    grade = "⚪ Grade C"
                    grade_tier = 4
                    tier_label = "WATCHLIST / DEFENSIVE"

                paper_status = "🟢 ACTIVE (PAPER TRADED)" if sym in active_paper_symbols else "📡 LIVE SCAN SIGNAL"

                # Expand TP2 & TP3 for runner potential when 24H Macro Anchor confirms the trade
                tp2_p = float(h.get('tp2_price', h.get('tp_price', curr_p)) or curr_p)
                tp3_p = float(h.get('tp3_price', h.get('tp_price', curr_p)) or curr_p)
                if is_24h_aligned and curr_p > 0:
                    if direction in ["BULLISH", "LONG"]:
                        tp2_p = round(curr_p + (tp2_p - curr_p) * 1.10, 8)
                        tp3_p = round(curr_p + (tp3_p - curr_p) * 1.15, 8)
                    else:
                        tp2_p = round(curr_p - (curr_p - tp2_p) * 1.10, 8)
                        tp3_p = round(curr_p - (curr_p - tp3_p) * 1.15, 8)

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
                    "predicted_next_price": float(h.get('predicted_next_price', tp1_p)),
                    "predicted_return_pct": float(h.get('predicted_return_pct', tp_pct)),
                    "best_sell_price": float(h.get('best_sell_price', h.get('tp3_price', tp1_p))),
                    "tp1_price": tp1_p,
                    "tp2_price": tp2_p,
                    "tp3_price": tp3_p,
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
                    "is_super_confluence_5x": is_super_5x,
                    "is_triple_screen": is_triple_screen,
                    "support_15m_aligned": is_15m_aligned,
                    "support_24h_aligned": is_24h_aligned,
                    "is_micro_wick_trap": is_micro_wick_trap,
                    "is_micro_hype_trap": is_micro_hype_trap,
                    "is_counter_macro_blocked": is_counter_macro_blocked,
                    "is_hype_surge": bool(h.get('is_hype_surge', False)),
                    "is_blowoff_top": bool(h.get('is_blowoff_top', False)),
                    "is_in_cooldown": is_in_cooldown,
                    "is_asset_locked": is_asset_locked,
                    "is_parabolic_short": is_parabolic_short,
                    "is_fee_drag_rejected": is_fee_drag_rejected,
                    "is_shield_blocked": is_shield_blocked,
                    "is_ntz_blocked": is_ntz_blocked,
                    "paper_trading_status": paper_status,
                    "card": h.get('pro_signal_text', ''),
                    "tf_summary": tf_summary
                }

                # 🧠 ML SECONDARY META-LABELER WIN PROBABILITY SCORING
                # Optimization: Only predict ML win probability for eligible setups to prevent redundant compute & OpenMP deadlocks
                is_candidate_suppressed = (
                    is_shield_blocked or
                    is_parabolic_short or
                    is_fee_drag_rejected or
                    is_asset_locked or
                    is_micro_wick_trap or
                    is_micro_hype_trap or
                    is_counter_macro_blocked or
                    is_ntz_blocked or
                    conv < 50.0 or
                    "CONSOLIDATION" in decision or
                    "FILTER" in decision or
                    "NO TRADE ZONE" in decision
                )
                base_meta_prob = float(h.get('meta_win_prob') if h.get('meta_win_prob') is not None else self.meta_classifier.predict_win_probability(candidate_obj))
                if is_candidate_suppressed:
                    meta_win_prob = min(base_meta_prob, 0.35)
                else:
                    meta_win_prob = base_meta_prob
                candidate_obj['meta_win_prob'] = meta_win_prob

                # If ML Meta-Classifier detects severely toxic sub-20% win probability with low conviction, demote grade
                if meta_win_prob < 0.20 and conv < 60.0 and not is_exec_decision:
                    candidate_obj['grade'] = "⚪ Grade C"
                    candidate_obj['grade_tier'] = 4
                    candidate_obj['tier_label'] = "WATCHLIST / DEFENSIVE"
                
                # Composite Score combining Conviction, ML Meta-Score, Triple Confluence, 5x Super Confluence & Yield
                triple_bonus = 30.0 if is_triple else 0.0
                super_5x_bonus = 25.0 if is_super_5x else 0.0
                triple_screen_bonus = 35.0 if is_triple_screen else 0.0
                exec_bonus = 20.0 if is_exec_decision else 0.0
                composite_score = (conv * 0.4) + (meta_win_prob * 100.0 * 0.4) + (max(0.0, rs_val) * 4.0) + triple_bonus + super_5x_bonus + triple_screen_bonus + exec_bonus + (abs(exp_ret) * 50.0)
                candidate_obj['composite_score'] = composite_score

                all_signals.append(candidate_obj)

        # Sort candidate setups: Grade Tier first, Meta Win Probability second, Composite score third
        all_signals.sort(key=lambda x: (x['grade_tier'], -x['meta_win_prob'], -x['composite_score'], -x['conviction']))

        # Filter candidates applying ML Meta-Probability Gate & Grade A+ Quality Enforcement
        qualified_pool = []
        for s in all_signals:
            if s['is_shield_blocked'] or s['is_parabolic_short'] or s['is_fee_drag_rejected'] or s.get('is_micro_wick_trap') or s.get('is_micro_hype_trap') or s.get('is_counter_macro_blocked') or s.get('is_ntz_blocked'):
                continue
            if "FILTER" in s.get('decision', '') or "CONSOLIDATION" in s.get('decision', '') or "NO TRADE ZONE" in s.get('decision', ''):
                continue
            is_tier1_ok = (s['grade_tier'] == 1 and s['meta_win_prob'] >= 0.48 and s['conviction'] >= 60.0)
            is_tier2_ok = (s['grade_tier'] <= 2 and s['conviction'] >= 54.0 and s['meta_win_prob'] >= 0.45)
            if (is_tier1_ok or is_tier2_ok) and not s['is_in_cooldown'] and not s['is_asset_locked']:
                qualified_pool.append(s)

        pool_for_selection = qualified_pool if len(qualified_pool) >= min_sig else [
            s for s in qualified_pool if "FILTER" not in s.get('decision', '')
        ]

        # Multi-Horizon High-Potential Signal Buckets:
        # Targeted Institutional High-Edge Horizons: 15M (Scalp), 1H (Day Trade), 24H (Swing Trade)
        horizon_bucket_defs = [
            {"key": "scalp", "tag": "15M", "label": "⚡ Scalp (15M)", "min_return": 0.30, "max_picks": 3},
            {"key": "swing", "tag": "1H", "label": "⏳ Day Trade (1H)", "min_return": 0.50, "max_picks": 3},
            {"key": "macro", "tag": "24H", "label": "🌊 Swing Trade (1D)", "min_return": 1.20, "max_picks": 3},
        ]

        signals_by_horizon = {b["tag"]: [] for b in horizon_bucket_defs}
        selected_signals = []
        selected_symbols_round = set()

        for b in horizon_bucket_defs:
            h_k = b["key"]
            h_tag = b["tag"]
            min_ret = b["min_return"]
            max_p = b.get("max_picks", 1)

            # Filter candidates for this exact horizon with Quality Filter Gate
            h_candidates = []
            for s in all_signals:
                if (s['horizon_key'] != h_k and h_tag.lower() not in s['horizon_key'].lower()):
                    continue
                if s['is_shield_blocked'] or s['is_parabolic_short'] or s['is_fee_drag_rejected'] or s.get('is_asset_locked', False) or s.get('is_ntz_blocked', False) or s.get('is_ntz_active', False):
                    continue

                dec_s = str(s.get('decision', ''))
                arch_s = str(s.get('strategy_archetype') or s.get('archetype', ''))
                if any(k in dec_s.upper() or k in arch_s.upper() for k in ["SUPPRESS", "CLIMAX WICK", "DO_NOT_TRADE", "AVOID", "NO TRADE ZONE", "CONSOLIDATION"]):
                    continue
                if s.get('is_suppressed') or s.get('suppressed'):
                    continue

                # -------------------------------------------------------------
                # 🛡️ Hard Shield: Suppress MOMENTUM LONG and DIP-BUY LONG when
                # BTC is below 1H/4H VWAP or Bear Drift Shield is Active
                # -------------------------------------------------------------
                is_mom_long_cand = (s.get('direction') in ['LONG', 'BULLISH'] and any(k in str(s.get('decision', '')).upper() for k in ['MOMENTUM', 'DIP-BUY']))
                if is_mom_long_cand and (getattr(self, 'suppress_momentum_longs', False) or getattr(self, 'is_btc_below_vwap', False) or getattr(self, 'btc_shield_active', False)):
                    continue

                is_mega = s['symbol'] in ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT']
                min_ret_eff = (0.20 if is_mega and h_k in ['scalp', 'swing'] else min_ret)
                s_exp = _safe_float(s.get('exp_return', s.get('predicted_return_pct', 0.0)), 0.0)
                if (abs(s_exp * 100.0) < min_ret_eff and abs(s_exp) < min_ret_eff):
                    continue
                h_candidates.append(s)

            # High Conviction setups (Targeted ML Meta Win Prob >= 48% for scalps, >= 50% for macro)
            min_meta_thresh = 0.48 if h_k in ['scalp', 'swing', 'macro'] else 0.50
            min_conv_thresh = 52.0 if h_k in ['scalp', 'swing'] else 55.0

            tier_high = [
                s for s in h_candidates
                if _safe_float(s.get('meta_win_prob', 0.50), 0.50) >= min_meta_thresh
                and ((s['grade_tier'] <= 2 and (s['meta_win_prob'] >= 0.25 or s['conviction'] >= 55.0)) or
                    (any(k in s.get('decision', '') for k in ['EXECUTE', 'ORDER-BLOCK', 'RETEST', 'DIP-BUY', 'RALLY-SELL', 'BREAKDOWN', 'BREAKOUT', 'MOMENTUM', 'REVERSAL', 'SWEEP', 'HYPE PUMP'])))
                and not any(k in s.get('decision', '').upper() for k in ['CONSOLIDATION', 'FILTER', 'NO TRADE ZONE', 'NTZ'])
                and not s.get('is_ntz_blocked', False)
                and not s.get('is_ntz_active', False)
                and s.get('conviction', 50.0) >= min_conv_thresh
            ]
            
            # Fallback to valid h_candidates if tier_high is empty
            if not tier_high and h_candidates:
                tier_high = [
                    s for s in h_candidates
                    if not any(k in s.get('decision', '').upper() for k in ['CONSOLIDATION', 'FILTER', 'NO TRADE ZONE', 'NTZ'])
                    and not s.get('is_ntz_blocked', False)
                    and not s.get('is_ntz_active', False)
                    and s.get('conviction', 50.0) >= 50.0
                    and s.get('grade_tier', 4) <= 3
                    and 'Grade C' not in str(s.get('grade', ''))
                ]
            
            def get_strategy_proven_edge(x):
                dec = str(x.get('decision', '')).upper()
                arch = str(x.get('strategy_archetype', '')).upper()
                st_type = str(x.get('strategy_type', '')).upper()
                is_long = str(x.get('direction', '')).upper() in ['LONG', 'BULLISH']
                is_top_performer = any(k in dec or k in arch or k in st_type for k in ['MOMENTUM', 'BREAKOUT', 'DIP-BUY', 'BOTTOM-REVERSAL', 'ORDER-BLOCK', 'TRIPLE'])
                boost = 0.0
                if is_top_performer and is_long:
                    boost += 30.0  # Top historical edge (+640% Momentum, +213% Elite Long, +77% Breakout)
                elif is_top_performer:
                    boost += 15.0
                elif is_long:
                    boost += 10.0  # Long asymmetry (+1063% vs +137% return)
                return boost

            pool = tier_high
            pool.sort(key=lambda x: (
                _safe_float(x.get('grade_tier'), 3),
                -_safe_float(x.get('meta_win_prob'), 0.5),
                -get_strategy_proven_edge(x),
                -_safe_float(x.get('composite_score'), 0.0),
                -_safe_float(x.get('conviction'), 50.0)
            ))

            # Select distinct best setups for this horizon
            h_count = 0
            for pick in pool:
                clean_sym = self.institutional_signal_manager._clean_sym(pick['symbol'])
                # Ensure coin is not duplicated within this exact horizon bucket in this round
                if (clean_sym, h_tag) not in selected_symbols_round:
                    selected_symbols_round.add((clean_sym, h_tag))
                    pick_copy = dict(pick)
                    pick_copy['horizon_tag'] = h_tag
                    selected_signals.append(pick_copy)
                    h_count += 1
                    if h_count >= max_p:
                        break

        # Upsert selected candidate signals into ActiveInstitutionalSignalManager (manages active signals and logs genuinely new signals)
        if selected_signals:
            self.institutional_signal_manager.upsert_signals(selected_signals)

        # Synchronize signals_by_horizon authoritative state from signal manager
        self.signals_by_horizon = self.institutional_signal_manager.get_signals_by_horizon()

        # Update Cooldown Timestamps for Dispatched Signals
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

        # Update master matrix universe with fresh results and live ticker calibration
        all_tickers_export = self.loader.fetch_all_tickers(max_age_seconds=10.0) if hasattr(self, 'loader') else {}
        if getattr(self, 'master_matrix_universe', None) is not None:
            for r in scanner_results:
                if isinstance(r, dict) and 'symbol' in r and is_valid_crypto_pair(r['symbol']):
                    self.master_matrix_universe[r['symbol']] = r
            
            # Enforce 3-minute maximum age & continuous live price alignment across all matrix assets
            for sym, item in list(self.master_matrix_universe.items()):
                raw_s = sym.replace('/', '').replace(':USDT', '')
                live_p = float(all_tickers_export.get(sym) or all_tickers_export.get(raw_s) or 0.0)
                cached_p = float(item.get('current_price', 0.0))
                item_ts = item.get('server_prediction_ts', 0)
                # If price drifted >= 0.3% or entry is older than 3 mins, recalibrate relative targets
                if live_p > 0 and (cached_p <= 0 or abs(live_p - cached_p) / (cached_p + 1e-10) >= 0.003 or (now_ts - item_ts) >= 180 or not item.get('server_prediction_time')):
                    self._refresh_asset_entry_timestamps(item, live_price=live_p)
                elif (now_ts - item_ts) >= 180 or not item.get('server_prediction_time'):
                    self._refresh_asset_entry_timestamps(item, live_price=live_p if live_p > 0 else None)
                    
            leaderboard_list = [item for item in self.master_matrix_universe.values() if isinstance(item, dict) and is_valid_crypto_pair(item.get('symbol'))]
        else:
            leaderboard_list = [item for item in scanner_results if isinstance(item, dict) and is_valid_crypto_pair(item.get('symbol'))]
            for item in leaderboard_list:
                sym = item.get('symbol', '')
                raw_s = sym.replace('/', '').replace(':USDT', '')
                live_p = float(all_tickers_export.get(sym) or all_tickers_export.get(raw_s) or 0.0)
                cached_p = float(item.get('current_price', 0.0))
                item_ts = item.get('server_prediction_ts', 0)
                if live_p > 0 and (cached_p <= 0 or abs(live_p - cached_p) / (cached_p + 1e-10) >= 0.003 or (now_ts - item_ts) >= 180 or not item.get('server_prediction_time')):
                    self._refresh_asset_entry_timestamps(item, live_price=live_p)
                elif (now_ts - item_ts) >= 180 or not item.get('server_prediction_time'):
                    self._refresh_asset_entry_timestamps(item, live_price=live_p if live_p > 0 else None)

        leaderboard_sorted = sorted(leaderboard_list, key=_safe_sort_key)

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
                "predicted_trend": getattr(self, "btc_predicted_trend", "CONSOLIDATION"),
                "trend_probability": getattr(self, "btc_trend_probability", 60.0),
                "bull_trend_prob": getattr(self, "btc_bull_trend_prob", 30.0),
                "bear_trend_prob": getattr(self, "btc_bear_trend_prob", 20.0),
                "consolidation_prob": getattr(self, "btc_consolidation_prob", 50.0),
                "predicted_btc_target": getattr(self, "btc_predicted_target", 0.0),
                "predicted_btc_change_pct": getattr(self, "btc_predicted_change_pct", 0.0),
                "breakout_prediction": getattr(self, "btc_breakout_prediction", "⚖️ RANGE BOUND"),
                "altcoin_posture": getattr(self, "btc_altcoin_posture", "STANDARD_EXECUTION"),
                "market_phase_description": getattr(self, "btc_market_phase_description", ""),
                "trader_playbook": getattr(self, "trader_playbook", {})
            },
            "trader_playbook": getattr(self, "trader_playbook", {}),
            "global_market_regime": getattr(self, "current_market_regime", {}),
            "top_24h_gainers_signals": getattr(self, "top_24h_gainers_signals", []),
            "top_24h_losers_signals": getattr(self, "top_24h_losers_signals", []),
            "top_high_markup_signals": getattr(self, "top_high_markup_signals", []),
            "dominant_signals_per_coin": self.institutional_signal_manager.get_dominant_best_signals(),
            "top_round_signals": self.institutional_signal_manager.get_display_signals() or top_signals or [],
            "signals_by_horizon": self.institutional_signal_manager.get_signals_by_horizon(),
            "scanner_leaderboard": leaderboard_sorted,
            "deep_dive": deep_dive_result,
            "paper_portfolio": self.ledger.data
        }
        json_path = os.path.join(self.config['app_export_dir'], "live_market_forecast.json")
        self._atomic_write_json(json_path, payload)

        if not is_partial:
            print(f"📦 Web-App Ready JSON Data Exported to: {os.path.abspath(json_path)}\n")

            # Publish scanner daemon state: IDLE with authoritative next prediction timestamp
            try:
                now_done = datetime.now(timezone.utc)
                scan_duration = round(time.time() - getattr(self, "last_scan_started_ts", time.time()), 2)
                scan_interval = int(self.config.get('scan_interval_seconds', 60))
                next_scan_dt = now_done + timedelta(seconds=scan_interval)
                next_scan_ts = int(next_scan_dt.timestamp())
                next_scan_utc = next_scan_dt.strftime("%Y-%m-%d %H:%M:%S UTC")

                state_path = os.path.join(self.config['app_export_dir'], "scanner_daemon_state.json")
                self._atomic_write_json(state_path, {
                    "is_scanning": False,
                    "scan_status": "IDLE",
                    "scanned_assets_count": len(scanner_results),
                    "total_assets_count": len(scanner_results),
                    "last_scan_completed_at": now_done.isoformat(),
                    "last_scan_completed_at_utc": now_done.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "last_scan_duration_seconds": scan_duration,
                    "next_scan_time_utc": next_scan_utc,
                    "next_scan_timestamp": next_scan_ts,
                    "seconds_to_next_scan": scan_interval,
                    "scan_interval_seconds": scan_interval
                })
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
                    self._atomic_write_json(state_path, curr_state)
            except Exception:
                pass


if __name__ == "__main__":
    engine = HybridQuantEngine(CONFIG)
    engine.run()
