import os
from typing import Tuple, List, Dict, Any, Optional

# Critical: Prevent OpenMP / BLAS threading deadlocks when called inside ThreadPoolExecutor
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

# ==============================================================================
# GLOBAL QUANTITATIVE MULTI-HORIZON ENGINE CONFIGURATION
# ==============================================================================

# Active Multi-Horizon Matrix Timeframes (User Mandate: Strictly 15 Minutes, 1 Hour, 4 Hours)
# Used for Multi-Horizon Matrix alignment, cross-timeframe confluence, and terminal matrix displays
ACTIVE_MULTI_HORIZONS = [
    "15m",  # 15 Minutes (Primary Scalp & Signal Execution Horizon)
    "1h",   # 1 Hour (Intraday Momentum & Context Horizon)
    "4h",   # 4 Hours (Intermediate Swing & Macro Anchor Horizon)
]
TIMEFRAMES_3 = ACTIVE_MULTI_HORIZONS

# Full 9 Timeframes for CCXT Multi-Scale Ingestion & SWR Fallback Backends
TIMEFRAMES_9 = [
    "5m",   # 5 Minutes
    "15m",  # 15 Minutes
    "1h",   # 1 Hour
    "4h",   # 4 Hours
    "12h",  # 12 Hours
    "1d",   # 24 Hours / 1 Day
    "1w",   # 7 Days / 1 Week (Retired from active ML models)
    "15d",  # 15 Days (Retired from active ML models)
    "1M"    # 30 Days / 1 Month (Retired from active ML models)
]

# Active ML & Microstructure Modeling Timeframes (Week and Month models completely retired)
ACTIVE_MODEL_TIMEFRAMES = ["15m", "1h", "4h", "5m", "1m", "12h", "1d"]
RETIRED_MACRO_TIMEFRAMES = ["1w", "15d", "1M"]

# Timeframe metadata: native Binance interval strings vs resampling requirements
TIMEFRAME_META = {
    "15m": {"label": "15M (15 Minutes)", "binance_tf": "15m", "is_native": True,  "seconds": 900},
    "1h":  {"label": "1H (1 Hour)",      "binance_tf": "1h",  "is_native": True,  "seconds": 3600},
    "4h":  {"label": "4H (4 Hours)",     "binance_tf": "4h",  "is_native": True,  "seconds": 14400},
    # Secondary definitions preserved for backward compatibility
    "1m":  {"label": "1M (1 Minute)",    "binance_tf": "1m",  "is_native": True,  "seconds": 60},
    "5m":  {"label": "5M (5 Minutes)",   "binance_tf": "5m",  "is_native": True,  "seconds": 300},
    "12h": {"label": "12H (12 Hours)",   "binance_tf": "12h", "is_native": True,  "seconds": 43200},
    "1d":  {"label": "24H (1 Day)",      "binance_tf": "1d",  "is_native": True,  "seconds": 86400},
    "1w":  {"label": "7D (1 Week)",      "binance_tf": "1w",  "is_native": True,  "seconds": 604800},
    "15d": {"label": "15D (15 Days)",    "binance_tf": "1d",  "is_native": False, "seconds": 1296000},
    "1M":  {"label": "30D (1 Month)",    "binance_tf": "1M",  "is_native": True,  "seconds": 2592000}
}

# Universe & Filtering Specifications
ENABLE_SIGNAL_EXPIRY: bool = os.getenv("ENABLE_SIGNAL_EXPIRY", "false").lower() in ("true", "1", "yes")
TOP_N_UNIVERSE = int(os.getenv("TOP_N_UNIVERSE", os.getenv("SCANNER_TOP_N", "75"))) # Dynamically configured 75-coin institutional universe
MIN_24H_VOLUME_USD = float(os.getenv("MIN_24H_VOLUME_USD", "10000000.0")) # $10M min 24h institutional volume

# Scalp Desk Slot & Capital Allocation (Scalp 15M Mandate: 5 Slots)
SCALP_DESK_MAX_SLOTS = int(os.getenv("SCALP_DESK_MAX_SLOTS", "5"))
SCALP_DESK_ALLOCATED_USD = float(os.getenv("SCALP_DESK_ALLOCATED_USD", "500.0"))
DAY_DESK_MAX_SLOTS = int(os.getenv("DAY_DESK_MAX_SLOTS", "2"))
DAY_DESK_ALLOCATED_USD = float(os.getenv("DAY_DESK_ALLOCATED_USD", "200.0"))
SWING_DESK_MAX_SLOTS = int(os.getenv("SWING_DESK_MAX_SLOTS", "3"))
SWING_DESK_ALLOCATED_USD = float(os.getenv("SWING_DESK_ALLOCATED_USD", "300.0"))

# Anees Mehdi 15M Rectangle Strategy Gating
MIN_RECTANGLE_SIGNAL_SCORE = float(os.getenv("MIN_RECTANGLE_SIGNAL_SCORE", "65.0"))
RECTANGLE_EXPIRATION_BARS_15M = int(os.getenv("RECTANGLE_EXPIRATION_BARS_15M", "4")) # 4 x 15m candles = 60 minutes

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

CONTRACT_MULTIPLIER_PREFIXES: Tuple[Tuple[str, float], ...] = (
    ("100000000000000", 100_000_000_000_000.0), # 100 Trillion (100T)
    ("10000000000000", 10_000_000_000_000.0),   # 10 Trillion (10T)
    ("1000000000000", 1_000_000_000_000.0),     # 1 Trillion (1T)
    ("100000000000", 100_000_000_000.0),        # 100 Billion (100B)
    ("10000000000", 10_000_000_000.0),          # 10 Billion (10B)
    ("1MBABYDOGE", 1_000_000.0),                 # Binance BabyDoge Futures convention
    ("1000000000", 1_000_000_000.0),            # 1 Billion (1B, e.g. 1000000000BONK)
    ("100000000", 100_000_000.0),               # 100 Million (100M)
    ("10000000", 10_000_000.0),                 # 10 Million (10M, e.g. 10000000AIDOGE)
    ("1000000", 1_000_000.0),                   # 1 Million (1M, e.g. 1000000MOG, 1000000PEIPEI, 1000000CHEEMS)
    ("100000", 100_000.0),                      # 100 Thousand (100K, e.g. 100000SHIB)
    ("10000", 10_000.0),                         # 10 Thousand (10K, e.g. 10000LADYS, 10000SATS)
    ("1000", 1_000.0),                           # 1 Thousand (1K, e.g. 1000PEPE, 1000BONK, 1000FLOKI)
    ("100T", 100_000_000_000_000.0),
    ("100B", 100_000_000_000.0),
    ("100M", 100_000_000.0),
    ("100K", 100_000.0),
    ("100", 100.0),                              # 1 Hundred (100x, e.g. 100BTT)
    ("10T", 10_000_000_000_000.0),
    ("10B", 10_000_000_000.0),
    ("10M", 10_000_000.0),
    ("10K", 10_000.0),
    ("1T", 1_000_000_000_000.0),
    ("1B", 1_000_000_000.0),
    ("1M", 1_000_000.0),
    ("1K", 1_000.0),
    ("10", 10.0),                                # 10x multiplier
)

# Standard authorized quote currencies for Quant Edge V16 futures and spot contracts
STANDARD_QUOTE_CURRENCIES: frozenset = frozenset({
    "USDT", "USDC", "BUSD", "USD", "EUR", "BTC", "ETH"
})

# Known non-standard quote currencies across global crypto exchanges
KNOWN_NON_STANDARD_QUOTES: tuple = (
    "FDUSD", "TUSD", "USDD", "USDE", "PYUSD", "DAI", "FRAX", "GUSD",
    "TRY", "BRL", "RUB", "KRW", "JPY", "GBP", "AUD", "CAD", "PLN",
    "ZAR", "UAH", "IDR", "NGN", "ARS", "COP", "CLP", "PEN", "MXN",
    "INR", "PHP", "VND", "EURS"
)

# All quote candidates sorted by length descending so longer suffixes (e.g. FDUSD) take precedence over substrings (e.g. USD)
ALL_SORTED_QUOTES: tuple = tuple(sorted(
    list(STANDARD_QUOTE_CURRENCIES) + list(KNOWN_NON_STANDARD_QUOTES),
    key=lambda q: len(q),
    reverse=True
))

def strip_contract_multiplier(symbol: str) -> Tuple[str, float]:
    """
    Dynamically identifies and strips non-standard futures contract multipliers
    (e.g., 1000000MOG -> ('MOG', 1000000.0), 10000LADYS -> ('LADYS', 10000.0),
           1000PEPE -> ('PEPE', 1000.0), 1MBABYDOGE -> ('BABYDOGE', 1000000.0),
           100000SHIB -> ('SHIB', 100000.0), 10000000AIDOGE -> ('AIDOGE', 10000000.0),
           1000000000BONK -> ('BONK', 1000000000.0), BTC -> ('BTC', 1.0)).
    Guarantees zero false-positive stripping for coins like '1INCH', '0G', or '10SET'.

    Exotic Delisted Tokens Protection:
    If an exchange introduces a novel contract multiplier delimiter with non-Latin
    characters (e.g. '1000★PEPE', '1000・PEPE', '1000PEPE／USDT', '1000PEPE_元')
    or non-standard quote currencies outside {"USDT", "USDC", "BUSD", "USD", "EUR", "BTC", "ETH"}
    (e.g. '1000PEPE/TRY', '1000000MOG/FDUSD', '10000LADYS:KRW', '1000BONK-BRL', '1000PEPETRY'),
    it falls back closed to the unstripped symbol with multiplier 1.0.
    """
    if not symbol or not isinstance(symbol, str):
        return "", 1.0

    raw_unstripped = str(symbol).strip()

    # Rule 1: Non-Latin characters (novel multiplier delimiters or non-Latin token/quote characters)
    # Any non-ASCII code point (> 127) fails closed to unstripped symbol with 1.0
    if any(ord(c) > 127 for c in raw_unstripped):
        return raw_unstripped, 1.0

    raw = raw_unstripped.upper()

    # Strip common derivative venue suffixes first
    for suffix in [":USDT", ":USDC", ":USD", "-SWAP", "-PERP", "_SWAP", "_PERP", "SWAP", "PERP"]:
        if raw.endswith(suffix) and len(raw) > len(suffix):
            raw = raw[:-len(suffix)]
            break

    # Rule 2: Non-standard quote currencies outside {"USDT", "USDC", "BUSD", "USD", "EUR", "BTC", "ETH"}
    if "/" in raw:
        parts = raw.split("/")
        base_candidate = parts[0].strip()
        quote_candidate = parts[1].strip()
        clean_quote = quote_candidate.split(":")[0].split("-")[0].split("_")[0].strip()
        if clean_quote and clean_quote not in STANDARD_QUOTE_CURRENCIES:
            return raw_unstripped, 1.0
        base = base_candidate
    elif ":" in raw:
        parts = raw.split(":")
        base_candidate = parts[0].strip()
        quote_candidate = parts[1].strip()
        if quote_candidate in {"PERP", "SWAP"}:
            base = base_candidate
        elif quote_candidate in STANDARD_QUOTE_CURRENCIES:
            base = base_candidate
        else:
            return raw_unstripped, 1.0
    elif "_" in raw or "-" in raw:
        delim = "_" if "_" in raw else "-"
        parts = raw.split(delim)
        if len(parts) > 1:
            if parts[-1] in {"SWAP", "PERP"} and len(parts) > 2:
                cand_quote = parts[-2]
                base_parts = parts[:-2]
            else:
                cand_quote = parts[-1]
                base_parts = parts[:-1]

            if cand_quote in STANDARD_QUOTE_CURRENCIES:
                base = delim.join(base_parts)
            elif cand_quote in KNOWN_NON_STANDARD_QUOTES or len(parts) >= 3:
                return raw_unstripped, 1.0
            else:
                base = parts[0]
        else:
            base = raw
    else:
        # Unslashed / no delimiter
        matched_quote = None
        for q in ALL_SORTED_QUOTES:
            if raw.endswith(q) and len(raw) > len(q):
                matched_quote = q
                break

        if matched_quote:
            if matched_quote not in STANDARD_QUOTE_CURRENCIES:
                # Unslashed pair with non-standard quote currency (e.g. 1000PEPETRY, 1000000MOGFDUSD)
                return raw_unstripped, 1.0
            base = raw[:-len(matched_quote)]
        else:
            base = raw

    # Special exemption list for native asset names starting with digits or letters that resemble prefixes
    if base in {"1INCH", "0G", "1M", "10SET"}:
        return base, 1.0

    if base == "1MBABYDOGE" or base.startswith("1MBABYDOGE"):
        remainder = base[len("1MBABYDOGE"):].lstrip("_-.")
        return (remainder or "BABYDOGE"), 1_000_000.0

    for prefix, mult in CONTRACT_MULTIPLIER_PREFIXES:
        if prefix == "1MBABYDOGE":
            continue
        if base.startswith(prefix) and len(base) > len(prefix):
            remainder = base[len(prefix):].lstrip("_-.")
            if remainder:
                return remainder, mult

    # Lowercase 'k' or 'K' multiplier prefix check
    if (base.startswith("K") or base.startswith("k")) and len(base) > 1:
        if base not in {"KAVA", "KAS", "KDA", "KLAY", "KNC", "KP3R", "KEY", "KSM"}:
            remainder = base[1:].lstrip("_-.")
            if remainder:
                return remainder, 1000.0

    return base, 1.0


def resolve_symbol_aliases(symbol: str) -> List[str]:
    """
    Generates all canonical ticker naming variations for a symbol across spot
    and futures venues (e.g. '1000000MOG/USDT', 'MOG/USDT', '1000000MOGUSDT', 'MOGUSDT',
    '10000LADYS/USDT', 'LADYSUSDT', '100000SHIBUSDT', '1MBABYDOGEUSDT').
    Falls back closed to [symbol] for exotic delisted tokens with non-Latin characters
    or non-standard quote currencies outside {"USDT", "USDC", "BUSD", "USD", "EUR", "BTC", "ETH"}.
    """
    if not symbol or not isinstance(symbol, str):
        return []

    # Non-Latin characters fail closed
    if any(ord(c) > 127 for c in str(symbol)):
        return [str(symbol).strip()]

    raw = str(symbol).strip().upper()
    quote = "USDT"

    # Strip common derivative venue suffixes
    for suffix in [":USDT", ":USDC", ":USD", "-SWAP", "-PERP", "_SWAP", "_PERP", "SWAP", "PERP"]:
        if raw.endswith(suffix) and len(raw) > len(suffix):
            raw = raw[:-len(suffix)]
            break

    if "/" in raw:
        parts = raw.split("/")
        base = parts[0]
        quote = parts[1] if len(parts) > 1 else "USDT"
        clean_q = quote.split(":")[0].split("-")[0].split("_")[0].strip()
        if clean_q not in STANDARD_QUOTE_CURRENCIES:
            return [str(symbol).strip()]
    elif ":" in raw:
        parts = raw.split(":")
        base = parts[0]
        cand_q = parts[1].strip()
        if cand_q not in {"PERP", "SWAP"} and cand_q not in STANDARD_QUOTE_CURRENCIES:
            return [str(symbol).strip()]
        quote = cand_q if cand_q in STANDARD_QUOTE_CURRENCIES else "USDT"
    elif "_" in raw:
        parts = raw.split("_")
        if len(parts) > 1 and parts[-1] in STANDARD_QUOTE_CURRENCIES:
            base = "_".join(parts[:-1])
            quote = parts[-1]
        elif len(parts) > 1 and (parts[-1] in KNOWN_NON_STANDARD_QUOTES or len(parts) >= 3):
            return [str(symbol).strip()]
        else:
            base = parts[0]
    elif "-" in raw:
        parts = raw.split("-")
        if len(parts) > 1 and parts[-1] in STANDARD_QUOTE_CURRENCIES:
            base = "-".join(parts[:-1])
            quote = parts[-1]
        elif len(parts) > 1 and (parts[-1] in KNOWN_NON_STANDARD_QUOTES or len(parts) >= 3):
            return [str(symbol).strip()]
        else:
            base = parts[0]
    else:
        # Unslashed / no delimiter
        matched_q = None
        for q in ALL_SORTED_QUOTES:
            if raw.endswith(q) and len(raw) > len(q):
                matched_q = q
                break
        if matched_q:
            if matched_q not in STANDARD_QUOTE_CURRENCIES:
                return [str(symbol).strip()]
            base = raw[:-len(matched_q)]
            quote = matched_q
        else:
            base = raw

    core_base, mult = strip_contract_multiplier(base)

    # Candidate bases: original base first, stripped core base second, then dynamic exchange multiplier variants
    candidate_bases = [base]
    if core_base and core_base != base:
        candidate_bases.append(core_base)

    if core_base and core_base not in {"1INCH", "0G", "1M", "10SET"}:
        for p, _ in CONTRACT_MULTIPLIER_PREFIXES:
            if p == "1MBABYDOGE":
                if core_base == "BABYDOGE":
                    candidate_bases.append("1MBABYDOGE")
            else:
                candidate_bases.append(f"{p}{core_base}")

    # Deduplicate candidate bases preserving order
    seen = set()
    unique_bases = []
    for b in candidate_bases:
        if b and b not in seen:
            seen.add(b)
            unique_bases.append(b)

    results = []
    # Always include original symbol first
    if symbol not in results:
        results.append(symbol)

    for b in unique_bases:
        for fmt in [
            f"{b}/{quote}",
            f"{b}{quote}",
            f"{b}/{quote}:{quote}",
            f"{b}:{quote}",
            f"{b}_{quote}",
            f"{b}-{quote}",
            f"{b}-{quote}-SWAP",
            b
        ]:
            if fmt not in results:
                results.append(fmt)

    return results


def is_meme_coin(symbol: str) -> bool:
    """
    Authoritative Institutional Meme Coin & Speculative Shitcoin Gate:
    Strictly identifies and intercepts meme coins across all formatting variants:
    - Standard pairs (e.g. 'DOGE/USDT', 'PEPEUSDT')
    - Multiplier-prefixed futures contracts (e.g. '1000000MOG', '10000LADYS', '1000PEPE', '1000BONK', '1000SHIB', '1MBABYDOGE', '1000SATS')
    - Suffix variants (e.g. 'DOGE2', 'PEPE2', 'NEIROETH')
    - Core meme stems ('INU', 'DOGE', 'SHIB', 'PEPE', 'BONK', 'FLOKI', 'MEME', 'ELON', 'PENGU', 'LADYS', etc.)
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

    stripped, _ = strip_contract_multiplier(base)

    # 1. Exact match in comprehensive meme registry
    if base in MEME_AND_SHITCOIN_BASES or stripped in MEME_AND_SHITCOIN_BASES:
        return True

    # 2. Check for core meme stems and tokens
    meme_stems = [
        "DOGE", "SHIB", "PEPE", "BONK", "FLOKI", "BABYDOGE", "INU", "ELON",
        "MOODENG", "POPCAT", "NEIRO", "PENGU", "CHILLGUY", "FARTCOIN", "GOAT",
        "PNUT", "SLERF", "TURBO", "BRETT", "WOJAK", "DEGEN", "MOG", "PONKE", "LADYS"
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
# DYNAMIC CANDLE LIMIT CONFIGURATIONS (TRAINING vs SCANNING LOOKBACKS)
# ==============================================================================
SCANNING_CANDLE_LIMITS: Dict[str, int] = {
    "1m": 120,   # 2 Hours (Ultra-fast Microstructure & Execution Gate)
    "5m": 120,   # 10 Hours (Micro Scalp Trigger)
    "15m": 500,  # 5.2 Days (Maximum Depth Primary Scalp & Tactical Execution)
    "1h": 500,   # 20.8 Days (Maximum Depth Intraday Momentum & Context Horizon)
    "4h": 500,   # 83.3 Days (Maximum Depth Macro Structural Anchor Horizon)
    "12h": 120,  # 60 Days (Half-Day Trend)
    "1d": 365,   # 1 Year (Daily Anchor)
    "1w": 60,    # 1.1 Years (Weekly Structure)
    "15d": 60,   # Resampled from 1D
    "1M": 36     # 3 Years (Secular Macro)
}

# Institutional Optimal Training Candle Limits (Maximum Stationarity & Statistical Rigor)
TRAINING_CANDLE_LIMITS: Dict[str, int] = {
    "1m": 500,   # 8.3 Hours (Microstructure order flow & taker wicks)
    "5m": 1000,  # 3.47 Days (Micro intraday momentum & session liquidity)
    "15m": 1000, # 10.4 Days (~1.5 Weeks; 2 full weekly cycles)
    "1h": 720,   # 30 Days (1 Full monthly trading regime)
    "4h": 500,   # 83.3 Days (~1 Quarter; market structure)
    "12h": 365,  # 182.5 Days (~6 Months; semi-annual trend)
    "1d": 500,   # 1.37 Years (Covers 200 SMA + full annual macro cycle)
    "1w": 156,   # 3 Years (Multi-year macro structure)
    "15d": 60,   # Resampled from up to 900 1D candles (~2.5 Years)
    "1M": 48     # 4 Years (Full crypto 4-year halving cycle)
}

def get_candle_limits(mode: str = "scanning") -> Dict[str, int]:
    """Dynamically retrieves optimal candle limits based on operational mode."""
    if str(mode).strip().lower() == "training":
        return TRAINING_CANDLE_LIMITS.copy()
    return SCANNING_CANDLE_LIMITS.copy()

# ==============================================================================
# CANDLE SYNCHRONIZATION & DYNAMIC RESCAN TIMING (FRESH MODELS GUARANTEE)
# ==============================================================================
SCAN_PRIMARY_TRIGGER_HORIZON = os.getenv("SCAN_PRIMARY_TRIGGER_HORIZON", "15m") # 15M primary candle boundary
SCAN_BUFFER_SECONDS = int(os.getenv("SCAN_BUFFER_SECONDS", "3")) # 3s Binance exchange settlement buffer
SCAN_MAX_INTERVAL_SECONDS = int(os.getenv("SCAN_MAX_INTERVAL_SECONDS", "900")) # 15-minute maximum cadence

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
# Default: "15M" (Restricts active trade signal emission strictly to 15-Minute execution only)
# 1H and 4H provide multi-horizon trend context and anchor confluence without direct trade execution.
ACTIVE_TRADE_HORIZONS = os.getenv("ACTIVE_TRADE_HORIZONS", "15M").strip().upper()
ALLOWED_EMISSION_HORIZONS = {"15M"} if ACTIVE_TRADE_HORIZONS in ["15M", "15M_ONLY", "INTRADAY_SWING", "SCALP_ONLY"] else ({"15M"} if ACTIVE_TRADE_HORIZONS != "ALL" else None)

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



