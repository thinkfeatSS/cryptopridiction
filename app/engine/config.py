import os

# Critical: Prevent OpenMP / BLAS threading deadlocks when called inside ThreadPoolExecutor
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

# ==============================================================================
# GLOBAL QUANTITATIVE MULTI-HORIZON ENGINE CONFIGURATION
# ==============================================================================

# 9 Required Multi-Horizon Timeframes / Charts
TIMEFRAMES_9 = [
    "5m",   # 5 Minutes (Micro Momentum & Scalp Trigger)
    "15m",  # 15 Minutes (Primary Scalp Horizon)
    "1h",   # 1 Hour (Day Trade / Hourly Momentum)
    "4h",   # 4 Hours (Intermediate Swing & Structure)
    "12h",  # 12 Hours (Half-Day Directional Trend)
    "1d",   # 24 Hours / 1 Day (Daily Anchor Horizon)
    "1w",   # 7 Days / 1 Week (Macro Weekly Structure)
    "15d",  # 15 Days (Bi-Weekly Cycle - aggregated from 1D)
    "1M"    # 30 Days / 1 Month (Macro Secular Trend)
]

# Timeframe metadata: native Binance interval strings vs resampling requirements
TIMEFRAME_META = {
    "1m":  {"label": "1M (1 Minute)",    "binance_tf": "1m",  "is_native": True,  "seconds": 60},
    "5m":  {"label": "5M (5 Minutes)",   "binance_tf": "5m",  "is_native": True,  "seconds": 300},
    "15m": {"label": "15M (15 Minutes)", "binance_tf": "15m", "is_native": True,  "seconds": 900},
    "1h":  {"label": "1H (1 Hour)",      "binance_tf": "1h",  "is_native": True,  "seconds": 3600},
    "4h":  {"label": "4H (4 Hours)",     "binance_tf": "4h",  "is_native": True,  "seconds": 14400},
    "12h": {"label": "12H (12 Hours)",   "binance_tf": "12h", "is_native": True,  "seconds": 43200},
    "1d":  {"label": "24H (1 Day)",      "binance_tf": "1d",  "is_native": True,  "seconds": 86400},
    "1w":  {"label": "7D (1 Week)",      "binance_tf": "1w",  "is_native": True,  "seconds": 604800},
    "15d": {"label": "15D (15 Days)",    "binance_tf": "1d",  "is_native": False, "seconds": 1296000},
    "1M":  {"label": "30D (1 Month)",    "binance_tf": "1M",  "is_native": True,  "seconds": 2592000}
}

# Universe & Filtering Specifications
TOP_N_UNIVERSE = int(os.getenv("TOP_N_UNIVERSE", os.getenv("SCANNER_TOP_N", "40"))) # Dynamically configured universe size
MIN_24H_VOLUME_USD = float(os.getenv("MIN_24H_VOLUME_USD", "10000000.0")) # $10M min 24h institutional volume

# Strict Meme & Shitcoin Registry (Zero Memes for Predictions)
MEME_AND_SHITCOIN_BASES = {
    "DOGE", "SHIB", "PEPE", "BONK", "WIF", "FLOKI", "BOME", "MEME", "PENGU",
    "NEIRO", "TURBO", "MYRO", "POPCAT", "BRETT", "MEW", "MOODENG", "GOAT",
    "ACT", "PNUT", "SLERF", "BABYDOGE", "CHEEMS", "LUNC", "USTC", "DOGS",
    "CATI", "HMSTR", "NOT", "1000SATS", "ORDI", "PEPE2", "AIDOGE", "LUNA",
    "FTT", "PUPPIES", "MILADY", "COQ", "TOSHI", "WEN", "SILLY", "PUMP",
    "PONKE", "GIGA", "SUNDOG", "SPX", "BILLY", "MOG", "MICHI", "TKO",
    "TRUMP", "MELANIA", "KAMALA", "BIDEN", "MAGA", "PEOPLE", "FARTCOIN",
    "CHILLGUY", "LUCE", "DEGEN", "WOJAK", "BAN", "CORGIAI", "SAMO", "ELON",
    "1000PEPE", "1000BONK", "1000FLOKI", "1000SHIB", "1000CHEEMS", "1000MOG",
    "1MBABYDOGE", "NEIROETH", "DOGE2", "SHIB2", "KISHU", "AKITA", "MONKY",
    "AI16Z", "GRIFFAIN", "VIRTUAL", "SWARMS", "ZEREBRO", "TEE", "BIO",
    "RIF", "URO", "VINE", "MAJOR", "FOXY", "KARRAT", "LADYS", "1000RATS",
    "1000CAT", "SATS", "RATS"
}

def is_meme_coin(symbol: str) -> bool:
    """
    Authoritative Institutional Meme Coin & Speculative Shitcoin Gate:
    Strictly identifies and intercepts meme coins across all formatting variants:
    - Standard pairs (e.g. 'DOGE/USDT', 'PEPEUSDT')
    - Multiplier-prefixed futures contracts (e.g. '1000PEPE', '1000BONK', '1000SHIB', '1MBABYDOGE', '1000SATS')
    - Suffix variants (e.g. 'DOGE2', 'PEPE2', 'NEIROETH')
    - Core meme stems ('INU', 'DOGE', 'SHIB', 'PEPE', 'BONK', 'FLOKI', 'MEME', 'ELON', 'PENGU', etc.)
    """
    if not symbol or not isinstance(symbol, str):
        return False

    raw = str(symbol).strip().upper().replace(":USDT", "")
    if "/" in raw:
        base = raw.split("/")[0]
    else:
        base = raw
        for quote in ["USDT", "USDC", "BUSD", "USD", "EUR", "BTC", "ETH"]:
            if base.endswith(quote) and len(base) > len(quote):
                base = base[:-len(quote)]
                break

    stripped = base
    if stripped.startswith("1000000"):
        stripped = stripped[7:]
    elif stripped.startswith("1000"):
        stripped = stripped[4:]
    elif stripped.startswith("1M") and len(stripped) > 2 and stripped != "1M":
        stripped = stripped[2:]
    elif stripped.startswith("K") and len(stripped) > 1 and stripped not in {"KAVA", "KAS", "KDA", "KLAY", "KNC", "KP3R", "KEY"}:
        stripped = stripped[1:]

    # 1. Exact match in comprehensive meme registry
    if base in MEME_AND_SHITCOIN_BASES or stripped in MEME_AND_SHITCOIN_BASES:
        return True

    # 2. Check for core meme stems and tokens
    meme_stems = [
        "DOGE", "SHIB", "PEPE", "BONK", "FLOKI", "BABYDOGE", "INU", "ELON",
        "MOODENG", "POPCAT", "NEIRO", "PENGU", "CHILLGUY", "FARTCOIN", "GOAT",
        "PNUT", "SLERF", "TURBO", "BRETT", "WOJAK", "DEGEN", "MOG", "PONKE"
    ]
    for stem in meme_stems:
        if stem in base or stem in stripped:
            return True

    return False

# Known Stablecoins & Fiat Pegs
EXCLUDED_STABLECOINS = {
    "USDC", "FDUSD", "TUSD", "USDD", "DAI", "BUSD", "EUR", "TRY", "PAXG", "WBTC",
    "USDP", "AEUR", "T", "USTC", "EURI", "USD", "EURR", "RLUSD", "USD1", "U", "USDE",
    "PYUSD", "GUSD", "LUSD", "FRAX", "CUSD", "EURT", "XAUT", "XAU", "XAG", "XUSD",
    "USDS", "USDSOLD", "USDSB", "USDX", "SUSD", "USDJ", "USDK", "USDQ", "USDM", "USDL", "BGBP", "BIDR",
    "IDRT", "BVND", "VND", "BRL", "GBP", "AUD", "NGN", "ZAR", "RUB", "UAH", "PLN",
    "RON", "CZK", "HUF", "ARS", "COP", "MXN", "PHP", "THB", "PAX", "TBTC", "BTCB",
    "USDT", "EURS", "EURC", "USN", "CEUR", "OUSD", "BFUSD", "RWUSD"
}

# Delisted / Inactive Binance Legacy Tokens (Must never be scanned)
DELISTED_AND_INACTIVE_COINS = {
    "USDSOLD", "USDSB", "ERD", "VEN", "BCC", "BCHABC", "BCHSV", "BTT", "NANO",
    "MCO", "LEND", "XZC", "STRAT", "HC", "GXS", "WABI", "OST", "AION", "SNGLS",
    "ARN", "CDT", "MDA", "QLC", "NEBL", "AUTOBUSD", "BTG", "HSR", "BCX", "SBTC",
    "ETF", "YOYO", "CHAT", "RPX", "TRIG", "MOD", "BQX", "SALT", "SUB", "ICN",
    "BEAM", "TORN", "WTC", "MOB", "PIVX", "DREP", "PNT", "VITE", "DOCK", "POLS"
}

# Synthetic & Tokenized Equities (e.g. endings with B)
EXCLUDED_SYNTHETIC_STOCKS = {
    "QQQB", "TSLAB", "NVDAB", "SPCXB", "SNDKB", "INTCB", "SOXLB", "MSTRB", "COINB",
    "AAPLB", "AMZNB", "GOOGLB", "METAB", "MSFTB", "NVDA", "TSLA", "AAPL", "AMZN",
    "GOOGL", "MSFT", "MARSCOIN", "COIN", "CRCLB", "BMNRB", "BMNR", "AVGOB", "AVGO",
    "PLTRB", "PLTR", "AMDB", "AMD", "ARMB", "ARM", "NFLXB", "NFLX", "BABAB", "BABA",
    "TSMB", "TSM", "QCOMB", "QCOM", "MUB", "MU", "DISB", "DIS", "PYPLB", "PYPL",
    "UBERB", "UBER", "HOODB", "HOOD", "SQB", "SQ", "COINBASE", "MICROSTRATEGY", "SKHYB"
}

# 5 Top Classification & 5 Top Regression Ensemble Hyperparameters
MODEL_CONFIGS = {
    "classifiers": {
        "catboost": {"iterations": 25, "depth": 4, "learning_rate": 0.08, "verbose": 0, "random_seed": 42, "thread_count": 1, "allow_writing_files": False},
        "xgboost": {"n_estimators": 25, "max_depth": 3, "learning_rate": 0.08, "subsample": 0.85, "n_jobs": 1, "random_state": 42},
        "hist_gb": {"max_iter": 25, "max_depth": 4, "learning_rate": 0.08, "random_state": 42},
        "extra_trees": {"n_estimators": 25, "max_depth": 5, "n_jobs": 1, "random_state": 42},
        "random_forest": {"n_estimators": 25, "max_depth": 5, "n_jobs": 1, "random_state": 42}
    },
    "regressors": {
        "catboost": {"iterations": 25, "depth": 4, "learning_rate": 0.08, "verbose": 0, "random_seed": 42, "thread_count": 1, "allow_writing_files": False},
        "xgboost": {"n_estimators": 25, "max_depth": 3, "learning_rate": 0.08, "subsample": 0.85, "n_jobs": 1, "random_state": 42},
        "hist_gb": {"max_iter": 25, "max_depth": 4, "learning_rate": 0.08, "random_state": 42},
        "extra_trees": {"n_estimators": 25, "max_depth": 5, "n_jobs": 1, "random_state": 42},
        "random_forest": {"n_estimators": 25, "max_depth": 5, "n_jobs": 1, "random_state": 42}
    }
}

# Consensus Voting Parameters
CONSENSUS_VOTE_THRESHOLD = 3   # 3 out of 5 models required for majority consensus
PRICE_CLUSTER_TOLERANCE_PCT = 0.0020 # 0.20% price band for regression consensus voting

# ==============================================================================
# CANDLE SYNCHRONIZATION & DYNAMIC RESCAN TIMING (FRESH MODELS GUARANTEE)
# ==============================================================================
SCAN_PRIMARY_TRIGGER_HORIZON = os.getenv("SCAN_PRIMARY_TRIGGER_HORIZON", "5m") # 5M primary candle boundary
SCAN_BUFFER_SECONDS = int(os.getenv("SCAN_BUFFER_SECONDS", "3")) # 3s Binance exchange settlement buffer
SCAN_MAX_INTERVAL_SECONDS = int(os.getenv("SCAN_MAX_INTERVAL_SECONDS", "300")) # 5-minute maximum cadence

# Paths
WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EXPORT_DIR = os.path.join(WORKSPACE_ROOT, "export_app_data")
MODELS_DIR = os.path.join(WORKSPACE_ROOT, "models_export_v3")
os.makedirs(EXPORT_DIR, exist_ok=True)
MODELS_DIR = os.path.join(WORKSPACE_ROOT, "models_export_v3")
os.makedirs(MODELS_DIR, exist_ok=True)

# ==============================================================================
# CONTROLLED EXPERIMENTS: QUANT EDGE V16
# ==============================================================================
# Experiment 1: Reversible Horizon Trade Eligibility Filter
# Default: "ALL" (Production baseline behavior: all eligible horizons can emit trades)
# "INTRADAY_SWING": Restricts active trade emission strictly to {"15M", "1H", "24H"}.
# Note: Full 9-timeframe CCXT ingestion, Order Block Engine, and BTC Predictive Market Shield
# remain 100% active and unpruned across all configurations.
ACTIVE_TRADE_HORIZONS = os.getenv("ACTIVE_TRADE_HORIZONS", "ALL").strip().upper()
ALLOWED_EMISSION_HORIZONS = {"15M", "1H", "24H"} if ACTIVE_TRADE_HORIZONS == "INTRADAY_SWING" else None

# Experiment 3: Probability Calibration Method
# Options: "SAERENS_LEGACY" (Production Baseline), "CHRONOLOGICAL_CALIBRATED" (Platt Sigmoid / Empirical)
# Default: "SAERENS_LEGACY" (Strict backward compatibility)
PROBABILITY_CALIBRATION_MODE = os.getenv("PROBABILITY_CALIBRATION_MODE", "SAERENS_LEGACY").strip().upper()

# Experiment 4: Stop-Loss & Breakeven Management Policy
# Options:
#   "PRODUCTION_TIER0_BE"       -> Production Baseline: Tier-0 Guard + exact entry breakeven at TP1
#   "TIER0_ATR_TRAILING_BUFFER" -> Policy E: Tier-0 Guard + 0.8x ATR trailing buffer after TP1
# Default: "PRODUCTION_TIER0_BE" (Strict backward compatibility)
TRADE_MANAGEMENT_POLICY = os.getenv("TRADE_MANAGEMENT_POLICY", "PRODUCTION_TIER0_BE").strip().upper()



