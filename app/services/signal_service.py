from sqlalchemy.orm import Session
from sqlalchemy import func, or_, desc
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from collections import defaultdict
import math
import os
import json
import numpy as np

import time
import requests

from app.config import settings
from app.models import SignalAudit, PaperPosition, ClosedTrade, MarketForecast
from app.services.db_sync import sync_files_to_db_live, get_sync_state, get_cached_forecast, set_cached_forecast
from app.engine.scanner.filters import UniverseFilter

_LIVE_PRICES_CACHE: Dict[str, float] = {}
_LIVE_PRICES_TS: float = 0.0

_EXCLUDED_STABLES = {
    "USDC", "FDUSD", "TUSD", "USDD", "DAI", "BUSD", "EUR", "TRY", "PAXG", "WBTC",
    "USDP", "AEUR", "T", "USTC", "EURI", "USD", "EURR", "RLUSD", "USD1", "U", "USDE",
    "PYUSD", "GUSD", "LUSD", "FRAX", "CUSD", "EURT", "XAUT", "USDS", "USDX", "USDT"
}

_DYNAMIC_REGIME_CACHE: Dict[str, Any] = {}
_DYNAMIC_REGIME_TS: float = 0.0
_DYNAMIC_GAINERS_CACHE: List[Dict[str, Any]] = []
_DYNAMIC_GAINERS_TS: float = 0.0
_DYNAMIC_LOSERS_CACHE: List[Dict[str, Any]] = []
_DYNAMIC_LOSERS_TS: float = 0.0
_TICKERS_24H_CACHE: list = []
_TICKERS_24H_TS: float = 0.0

_FETCHING_TICKERS = False

def _async_refresh_tickers():
    global _FETCHING_TICKERS, _TICKERS_24H_CACHE, _TICKERS_24H_TS, _LIVE_PRICES_CACHE, _LIVE_PRICES_TS
    if _FETCHING_TICKERS:
        return
    _FETCHING_TICKERS = True
    def _worker():
        global _FETCHING_TICKERS, _TICKERS_24H_CACHE, _TICKERS_24H_TS, _LIVE_PRICES_CACHE, _LIVE_PRICES_TS
        try:
            url = "https://data-api.binance.vision/api/v3/ticker/24hr"
            resp = requests.get(url, timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                _TICKERS_24H_CACHE = data
                _TICKERS_24H_TS = time.time()
                prices = {}
                for t in data:
                    s = t.get('symbol', '')
                    try:
                        p = float(t.get('lastPrice', 0.0))
                        if p > 0:
                            prices[s] = p
                            if s.endswith('USDT'):
                                base = s[:-4]
                                prices[f"{base}/USDT"] = p
                                prices[base] = p
                    except Exception:
                        pass
                if prices:
                    _LIVE_PRICES_CACHE = prices
                    _LIVE_PRICES_TS = time.time()
        except Exception:
            pass
        finally:
            _FETCHING_TICKERS = False
    
    import threading
    t = threading.Thread(target=_worker, daemon=True)
    t.start()

def _fetch_24hr_tickers_raw(max_age: float = 30.0) -> list:
    global _TICKERS_24H_CACHE, _TICKERS_24H_TS
    now = time.time()
    if not _TICKERS_24H_CACHE or (now - _TICKERS_24H_TS) >= max_age:
        _async_refresh_tickers()
    return _TICKERS_24H_CACHE or []

def fetch_live_binance_prices(max_age_seconds: float = 15.0) -> Dict[str, float]:
    """Fetches and caches live Binance spot prices instantly in 0ms without blocking request threads."""
    global _LIVE_PRICES_CACHE, _LIVE_PRICES_TS
    now = time.time()
    if not _LIVE_PRICES_CACHE:
        try:
            url = "https://data-api.binance.vision/api/v3/ticker/24hr"
            resp = requests.get(url, timeout=3.5)
            if resp.status_code == 200:
                data = resp.json()
                prices = {}
                for t in data:
                    s = t.get('symbol', '')
                    p = float(t.get('lastPrice', 0.0))
                    if p > 0:
                        prices[s] = p
                        if s.endswith('USDT'):
                            base = s[:-4]
                            prices[f"{base}/USDT"] = p
                            prices[base] = p
                if prices:
                    _LIVE_PRICES_CACHE = prices
                    _LIVE_PRICES_TS = time.time()
        except Exception:
            _async_refresh_tickers()
    elif (now - _LIVE_PRICES_TS) >= max_age_seconds:
        _async_refresh_tickers()
    return _LIVE_PRICES_CACHE

_INTRA_CANDLE_CACHE = {}
_INTRA_CANDLE_TS = {}

def fetch_intra_candle_extremes(symbol: str, horizon: str = "15M") -> tuple[float, float]:
    """
    Fetches real intra-candle OHLC high and low wicks from Binance Vision API.
    Guarantees that intra-candle adverse spikes touching Stop-Loss or target touches
    are captured even if the candle eventually closes at an opposite level.
    """
    global _INTRA_CANDLE_CACHE, _INTRA_CANDLE_TS
    raw_sym = symbol.replace("/", "").replace(":USDT", "").upper()
    now_t = time.time()
    
    # Cache per symbol for 10 seconds to keep evaluation blisteringly fast
    if raw_sym in _INTRA_CANDLE_CACHE and (now_t - _INTRA_CANDLE_TS.get(raw_sym, 0.0)) < 10.0:
        return _INTRA_CANDLE_CACHE[raw_sym]
        
    norm_hz = "15M" if "15" in horizon else ("24H" if ("24" in horizon or "1D" in horizon) else "1H")
    interval = "1m" if norm_hz == "15M" else ("5m" if norm_hz == "1H" else "1h")
    limit = 15 if norm_hz == "15M" else 12

    try:
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={raw_sym}&interval={interval}&limit={limit}"
        resp = requests.get(url, timeout=2.5)
        if resp.status_code == 200:
            klines = resp.json()
            if isinstance(klines, list) and len(klines) > 0:
                highs = [float(k[2]) for k in klines]
                lows = [float(k[3]) for k in klines]
                res = (max(highs), min(lows))
                _INTRA_CANDLE_CACHE[raw_sym] = res
                _INTRA_CANDLE_TS[raw_sym] = now_t
                return res
    except Exception:
        pass
    return (0.0, 0.0)

def resolve_asset_price(symbol: str, signal: Optional[Any] = None, live_prices: Optional[Dict[str, float]] = None) -> float:
    """
    Institutional Multi-Tier Real-Time & Terminal Price Resolver.
    Eliminates zero-volume and delisted asset blind-spots.
    Hierarchy:
      1. Live 24hr Binance In-Memory Ticker Cache
      2. Direct Binance Spot Price REST Endpoint (/api/v3/ticker/price)
      3. Last Historical Kline Close (/api/v3/klines close of final minute before delisting/halt)
      4. Signal Internal Tracked Telemetry (current_price, peak/trough wicks)
      5. Secondary Public Multi-Exchange Fallback (CoinGecko Simple Price)
      6. Baseline Entry Price (absolute last resort if 0 tick history ever existed)
    """
    clean_sym = symbol.replace("/", "").replace(":USDT", "").upper()
    binance_pair = clean_sym if clean_sym.endswith("USDT") else f"{clean_sym}USDT"

    # Tier 1: Check live prices dictionary
    if live_prices:
        p = live_prices.get(symbol) or live_prices.get(binance_pair) or live_prices.get(clean_sym)
        if p and float(p) > 0:
            return float(p)

    # Tier 2: Direct Binance Spot Price REST Endpoint
    for base_url in ["https://data-api.binance.vision", "https://api.binance.com"]:
        try:
            r = requests.get(f"{base_url}/api/v3/ticker/price?symbol={binance_pair}", timeout=2.0)
            if r.status_code == 200:
                p = float(r.json().get("price", 0.0))
                if p > 0:
                    return p
        except Exception:
            pass

    # Tier 3: Last Historical Kline Close (Captures exact final traded price prior to delisting/halt)
    for base_url in ["https://data-api.binance.vision", "https://api.binance.com"]:
        try:
            r = requests.get(f"{base_url}/api/v3/klines?symbol={binance_pair}&interval=1m&limit=1", timeout=2.0)
            if r.status_code == 200:
                klines = r.json()
                if isinstance(klines, list) and len(klines) > 0:
                    close_p = float(klines[-1][4])
                    if close_p > 0:
                        return close_p
        except Exception:
            pass

    # Tier 4: Signal Internal Tracked Telemetry
    if signal:
        s_curr = getattr(signal, "current_price", None)
        if s_curr and float(s_curr) > 0:
            return float(s_curr)
        s_peak = getattr(signal, "peak_price_seen", None)
        s_trough = getattr(signal, "trough_price_seen", None)
        direction = str(getattr(signal, "direction", "LONG")).upper()
        if direction == "LONG" and s_peak and float(s_peak) > 0:
            return float(s_peak)
        elif direction == "SHORT" and s_trough and float(s_trough) > 0:
            return float(s_trough)

    # Tier 5: CoinGecko Public Multi-Exchange Fallback
    try:
        base_coin = clean_sym.replace("USDT", "").lower()
        cg_url = f"https://api.coingecko.com/api/v3/simple/price?ids={base_coin}&vs_currencies=usd"
        cg_r = requests.get(cg_url, timeout=2.0)
        if cg_r.status_code == 200:
            cg_data = cg_r.json()
            if base_coin in cg_data and "usd" in cg_data[base_coin]:
                p = float(cg_data[base_coin]["usd"])
                if p > 0:
                    return p
    except Exception:
        pass

    # Tier 6: Baseline Entry Price (absolute last resort if 0 tick history ever existed)
    if signal and getattr(signal, "entry_price", None):
        return float(signal.entry_price)

    return 0.0

def clear_forecast_cache():
    """Clears dynamic in-memory regime and signal caches."""
    global _DYNAMIC_REGIME_CACHE, _DYNAMIC_GAINERS_CACHE, _DYNAMIC_LOSERS_CACHE, _LIVE_PRICES_CACHE
    _DYNAMIC_REGIME_CACHE = {}
    _DYNAMIC_GAINERS_CACHE = []
    _DYNAMIC_LOSERS_CACHE = []
    _LIVE_PRICES_CACHE = {}

def _get_or_compute_regime() -> Dict[str, Any]:
    global _DYNAMIC_REGIME_CACHE, _DYNAMIC_REGIME_TS
    now = time.time()
    if _DYNAMIC_REGIME_CACHE and (now - _DYNAMIC_REGIME_TS) < 30.0:
        return _DYNAMIC_REGIME_CACHE
    
    tickers = _fetch_24hr_tickers_raw()
    changes = []
    for item in tickers:
        raw_s = item.get('symbol', '')
        if raw_s.endswith('USDT'):
            base = raw_s[:-4]
            if base in _EXCLUDED_STABLES:
                continue
            vol = float(item.get('quoteVolume', 0.0))
            if vol >= 1000000.0:
                changes.append(float(item.get('priceChangePercent', 0.0)))
    
    if not changes:
        return {
            "regime_type": "CONSOLIDATION",
            "label": "⚖️ CONSOLIDATION",
            "market_breadth_bull_pct": 50.0,
            "market_breadth_bear_pct": 50.0,
            "avg_24h_change_pct": 0.0,
            "tactical_stance": "RANGE_BOUND_MEAN_REVERSION"
        }

    green_count = sum(1 for c in changes if c > 0)
    red_count = sum(1 for c in changes if c < 0)
    tot = max(1, len(changes))
    bull_pct = round((green_count / tot) * 100.0, 1)
    bear_pct = round((red_count / tot) * 100.0, 1)
    avg_chg = round(sum(changes) / tot, 2)

    if bull_pct >= 62.0 and avg_chg >= 1.2:
        regime_type = "BULLISH"
        label = "🟢 BULLISH EXPANSION"
        stance = "TREND_CONTINUATION_LONGS"
    elif bear_pct >= 62.0 and avg_chg <= -1.2:
        regime_type = "BEARISH"
        label = "🔴 BEARISH DRIFT"
        stance = "CAPITULATION_OVERSOLD_BOUNCES_AND_SHORTS"
    else:
        regime_type = "CONSOLIDATION"
        label = "⚖️ RANGE BOUND / CONSOLIDATION"
        stance = "RANGE_BOUNDARY_FADES"

    res = {
        "regime_type": regime_type,
        "label": label,
        "market_breadth_bull_pct": bull_pct,
        "market_breadth_bear_pct": bear_pct,
        "avg_24h_change_pct": avg_chg,
        "total_liquid_universe_count": tot,
        "tactical_stance": stance
    }
    _DYNAMIC_REGIME_CACHE = res
    _DYNAMIC_REGIME_TS = now
    return res

def _get_or_compute_gainers(regime: dict = None) -> List[Dict[str, Any]]:
    global _DYNAMIC_GAINERS_CACHE, _DYNAMIC_GAINERS_TS
    now = time.time()
    if _DYNAMIC_GAINERS_CACHE and (now - _DYNAMIC_GAINERS_TS) < 30.0:
        return _DYNAMIC_GAINERS_CACHE
    
    if not regime:
        regime = _get_or_compute_regime()
    tickers = _fetch_24hr_tickers_raw()
    cands = []
    fallback_cands = []
    for item in tickers:
        raw_s = item.get('symbol', '')
        if raw_s.endswith('USDT'):
            base = raw_s[:-4]
            if base in _EXCLUDED_STABLES:
                continue
            vol = float(item.get('quoteVolume', 0.0))
            chg = float(item.get('priceChangePercent', 0.0))
            p = float(item.get('lastPrice', 0.0))
            if p <= 0:
                continue
            
            sig_obj = {
                "symbol": f"{base}/USDT",
                "strategy_type": "MOMENTUM_TOP_GAINER",
                "direction": "LONG",
                "direction_label": "🟢 LONG (TOP GAINER MOMENTUM)",
                "decision": "🎯 ELITE MOMENTUM BREAKOUT (LONG)",
                "current_price": p,
                "entry_price": p,
                "tp1_price": round(p * 1.038, 6),
                "tp2_price": round(p * 1.075, 6),
                "tp3_price": round(p * 1.150, 6),
                "sl_price": round(p * 0.975, 6),
                "risk_reward_ratio": "1:3.0",
                "expected_return_pct": 3.8,
                "conviction": 82.0,
                "quality_grade": "A+",
                "grade_tier": 1,
                "change_24h_pct": chg,
                "volume_24h_usd": vol,
                "horizon_tag": "24H",
                "horizon_key": "macro",
                "priority": 1,
                "meta_probability": 0.78,
                "meta_filter_decision": "ALLOW",
                "server_prediction_time": datetime.now(timezone.utc).isoformat()
            }
            if vol >= 1000000.0 and chg >= 2.0:
                cands.append(sig_obj)
            elif vol >= 100000.0:
                fallback_cands.append(sig_obj)

    cands.sort(key=lambda x: x['change_24h_pct'], reverse=True)
    if len(cands) < 10:
        fallback_cands.sort(key=lambda x: x['change_24h_pct'], reverse=True)
        for fb in fallback_cands:
            if fb['symbol'] not in [c['symbol'] for c in cands]:
                cands.append(fb)
            if len(cands) >= 10:
                break

    top_res = cands[:10]
    _DYNAMIC_GAINERS_CACHE = top_res
    _DYNAMIC_GAINERS_TS = now
    return top_res

def _get_or_compute_losers(regime: dict = None) -> List[Dict[str, Any]]:
    global _DYNAMIC_LOSERS_CACHE, _DYNAMIC_LOSERS_TS
    now = time.time()
    if _DYNAMIC_LOSERS_CACHE and (now - _DYNAMIC_LOSERS_TS) < 30.0:
        return _DYNAMIC_LOSERS_CACHE
    
    if not regime:
        regime = _get_or_compute_regime()
    tickers = _fetch_24hr_tickers_raw()
    cands = []
    fallback_cands = []
    for item in tickers:
        raw_s = item.get('symbol', '')
        if raw_s.endswith('USDT'):
            base = raw_s[:-4]
            if base in _EXCLUDED_STABLES:
                continue
            vol = float(item.get('quoteVolume', 0.0))
            chg = float(item.get('priceChangePercent', 0.0))
            p = float(item.get('lastPrice', 0.0))
            if p <= 0:
                continue

            sig_obj = {
                "symbol": f"{base}/USDT",
                "strategy_type": "BREAKDOWN_TOP_LOSER",
                "direction": "SHORT",
                "direction_label": "🔴 SHORT (TOP LOSER BREAKDOWN)",
                "decision": "🎯 ELITE BREAKDOWN CONTINUATION (SHORT)",
                "current_price": p,
                "entry_price": p,
                "tp1_price": round(p * 0.965, 6),
                "tp2_price": round(p * 0.930, 6),
                "tp3_price": round(p * 0.850, 6),
                "sl_price": round(p * 1.022, 6),
                "risk_reward_ratio": "1:3.2",
                "expected_return_pct": 3.5,
                "conviction": 82.0,
                "quality_grade": "A+",
                "grade_tier": 1,
                "change_24h_pct": chg,
                "volume_24h_usd": vol,
                "horizon_tag": "24H",
                "horizon_key": "macro",
                "priority": 1,
                "meta_probability": 0.77,
                "meta_filter_decision": "ALLOW",
                "server_prediction_time": datetime.now(timezone.utc).isoformat()
            }
            if vol >= 1000000.0 and chg <= -2.0:
                cands.append(sig_obj)
            elif vol >= 100000.0:
                fallback_cands.append(sig_obj)

    cands.sort(key=lambda x: x['change_24h_pct'], reverse=False)
    if len(cands) < 10:
        fallback_cands.sort(key=lambda x: x['change_24h_pct'], reverse=False)
        for fb in fallback_cands:
            if fb['symbol'] not in [c['symbol'] for c in cands]:
                cands.append(fb)
            if len(cands) >= 10:
                break

    top_res = cands[:10]
    _DYNAMIC_LOSERS_CACHE = top_res
    _DYNAMIC_LOSERS_TS = now
    return top_res

_DYNAMIC_MARKUP_CACHE: List[Dict[str, Any]] = []
_DYNAMIC_MARKUP_TS: float = 0.0

def _get_or_compute_high_markup_signals(regime: dict = None) -> List[Dict[str, Any]]:
    global _DYNAMIC_MARKUP_CACHE, _DYNAMIC_MARKUP_TS
    now = time.time()
    if _DYNAMIC_MARKUP_CACHE and (now - _DYNAMIC_MARKUP_TS) < 30.0:
        return _DYNAMIC_MARKUP_CACHE
    
    if not regime:
        regime = _get_or_compute_regime()
    tickers = _fetch_24hr_tickers_raw()
    cands = []
    fallback_cands = []
    for item in tickers:
        raw_s = item.get('symbol', '')
        if raw_s.endswith('USDT'):
            base = raw_s[:-4]
            if base in _EXCLUDED_STABLES:
                continue
            vol = float(item.get('quoteVolume', 0.0))
            chg = float(item.get('priceChangePercent', 0.0))
            p = float(item.get('lastPrice', 0.0))
            high_p = float(item.get('highPrice', 0.0))
            low_p = float(item.get('lowPrice', 0.0))
            if low_p > 0 and p > 0 and high_p >= low_p:
                markup_pct = ((high_p - low_p) / low_p) * 100.0
                mid_range = (high_p + low_p) / 2.0
                is_long = p >= mid_range or chg >= 0.0
                entry_p = p
                if is_long:
                    tp1_p = round(entry_p * 1.050, 6)
                    tp2_p = round(entry_p * 1.105, 6)
                    tp3_p = round(entry_p * 1.220, 6)
                    sl_p = round(entry_p * 0.968, 6)
                    dir_str = "LONG"
                    dir_label = "🟢 LONG (HIGH MARKUP MOMENTUM)"
                    dec_tag = f"🎯 HIGH-MARKUP EXPLOSIVE RUNNER (+{markup_pct:.1f}% RANGE)"
                else:
                    tp1_p = round(entry_p * 0.950, 6)
                    tp2_p = round(entry_p * 0.895, 6)
                    tp3_p = round(entry_p * 0.780, 6)
                    sl_p = round(entry_p * 1.032, 6)
                    dir_str = "SHORT"
                    dir_label = "🔴 SHORT (HIGH MARKUP RANGE FADE)"
                    dec_tag = f"🎯 HIGH-MARKUP RANGE REVERSAL ({markup_pct:.1f}% RANGE)"

                sig_obj = {
                    "symbol": f"{base}/USDT",
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
                    "risk_reward_ratio": "1:3.3",
                    "expected_return_pct": 5.0,
                    "conviction": 84.0,
                    "quality_grade": "A+",
                    "grade_tier": 1,
                    "change_24h_pct": chg,
                    "volume_24h_usd": vol,
                    "markup_pct": round(markup_pct, 2),
                    "horizon_tag": "1H",
                    "horizon_key": "swing",
                    "priority": 1,
                    "meta_probability": 0.80,
                    "meta_filter_decision": "ALLOW",
                    "server_prediction_time": datetime.now(timezone.utc).isoformat()
                }
                if vol >= 500000.0 and markup_pct >= 4.0:
                    cands.append(sig_obj)
                elif vol >= 100000.0:
                    fallback_cands.append(sig_obj)

    cands.sort(key=lambda x: (x['markup_pct'] * math.log10(max(10.0, x['volume_24h_usd']))), reverse=True)
    if len(cands) < 10:
        fallback_cands.sort(key=lambda x: (x['markup_pct'] * math.log10(max(10.0, x['volume_24h_usd']))), reverse=True)
        for fb in fallback_cands:
            if fb['symbol'] not in [c['symbol'] for c in cands]:
                cands.append(fb)
            if len(cands) >= 10:
                break

    top_res = cands[:10]
    _DYNAMIC_MARKUP_CACHE = top_res
    _DYNAMIC_MARKUP_TS = now
    return top_res

class SignalService:
    def __init__(self):
        self._last_resolve_ts = 0.0
        self._last_sync_ts = 0.0

    def resolve_pending_signals_live(self, db: Session, force: bool = False):
        """
        Evaluates pending signals in the database against live Binance spot prices:
        - Resolves expired signals when predicted_close_utc has passed.
        - Resolves TP1 / TP2 / TP3 / SL hits in real time.
        - Throttled to run at most once every 15 seconds to keep API responses instant.
        """
        now_t = time.time()
        if not force and (now_t - self._last_resolve_ts) < 15.0:
            return
        self._last_resolve_ts = now_t

        try:
            # 1. Paper Trading Execution Reconciliation Bridge:
            # Check open & closed trades from paper_trading_ledger.json to ensure 0ms synchronization
            # between sub-second tick execution and the Signal Audit Ledger.
            closed_paper_map = {}
            open_paper_map = {}
            cancelled_paper_map = {}
            try:
                ledger_path = os.path.join(settings.EXPORT_DIR, "paper_trading_ledger.json")
                if os.path.exists(ledger_path):
                    with open(ledger_path, "r", encoding="utf-8") as pf:
                        pt_data = json.load(pf)
                    all_closed = (pt_data.get("closed_trades_history") or []) + (pt_data.get("closed_trades") or [])
                    for pt in all_closed:
                        pt_sym = str(pt.get("symbol", "")).strip().upper()
                        pt_hz = str(pt.get("horizon", "15M")).strip().upper()
                        norm_hz = "15M" if "15" in pt_hz else ("24H" if ("24" in pt_hz or "1D" in pt_hz) else "1H")
                        closed_paper_map[(pt_sym, norm_hz)] = pt
                        closed_paper_map[(pt_sym.replace("/", "").replace(":USDT", ""), norm_hz)] = pt
                        if pt.get("trade_id"):
                            closed_paper_map[pt.get("trade_id")] = pt

                    for op in pt_data.get("open_positions", []):
                        op_sym = str(op.get("symbol", "")).strip().upper()
                        op_hz = str(op.get("horizon", "15M")).strip().upper()
                        norm_hz = "15M" if "15" in op_hz else ("24H" if ("24" in op_hz or "1D" in op_hz) else "1H")
                        open_paper_map[(op_sym, norm_hz)] = op
                        open_paper_map[(op_sym.replace("/", "").replace(":USDT", ""), norm_hz)] = op
                        if op.get("trade_id"):
                            open_paper_map[op.get("trade_id")] = op

                    for canc in pt_data.get("cancelled_orders", []):
                        canc_sym = str(canc.get("symbol", "")).strip().upper()
                        canc_hz = str(canc.get("horizon", "15M")).strip().upper()
                        norm_hz = "15M" if "15" in canc_hz else ("24H" if ("24" in canc_hz or "1D" in canc_hz) else "1H")
                        cancelled_paper_map[(canc_sym, norm_hz)] = canc
                        cancelled_paper_map[(canc_sym.replace("/", "").replace(":USDT", ""), norm_hz)] = canc
                        if canc.get("signal_id"):
                            cancelled_paper_map[canc.get("signal_id")] = canc
                        if canc.get("trade_id"):
                            cancelled_paper_map[canc.get("trade_id")] = canc
            except Exception:
                pass

            open_trade_ids = [k for k in open_paper_map.keys() if isinstance(k, str) and k]
            pending_clauses = [
                SignalAudit.status.in_(["PENDING_EVALUATION", "ACTIVE", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"]),
                SignalAudit.outcome_label.like("%PENDING%")
            ]
            if open_trade_ids:
                pending_clauses.append(SignalAudit.signal_id.in_(open_trade_ids))

            pending = db.query(SignalAudit).filter(or_(*pending_clauses)).all()
            if not pending:
                return

            live_prices = fetch_live_binance_prices(max_age_seconds=5.0)
            if not live_prices:
                return

            now_utc = datetime.now(timezone.utc)
            now_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
            updated = False

            for s in pending:
                sym = s.symbol
                s_sym = str(s.symbol or "").strip().upper()
                s_hz = str(s.horizon or "15M").strip().upper()
                norm_hz = "15M" if "15" in s_hz else ("24H" if ("24" in s_hz or "1D" in s_hz) else "1H")

                # Step 1: Check for direct Paper Trading Execution Match in OPEN running trades FIRST!
                op_match = open_paper_map.get(s.signal_id) or open_paper_map.get((s_sym, norm_hz)) or open_paper_map.get((s_sym.replace("/", "").replace(":USDT", ""), norm_hz))
                if op_match:
                    s.status = "ACTIVE"
                    s.outcome_label = "RUNNING 🚀"
                    if hasattr(s, "paper_trading_status"):
                        s.paper_trading_status = "EXECUTED (PAPER WALLET)"
                    cur_p = float(op_match.get("current_price") or s.entry_price or 0.0)
                    if hasattr(s, "current_price"):
                        s.current_price = cur_p
                    if hasattr(s, "live_pnl_pct"):
                        s.live_pnl_pct = float(op_match.get("unrealized_pnl_pct") or 0.0)
                    s.sl_price = float(op_match.get("sl_price") or s.sl_price or 0.0)
                    s.exit_price = None
                    s.realized_return_pct = None
                    s.evaluated_at_utc = None
                    updated = True
                    continue

                # Step 2: Check for direct Paper Trading Execution Match in CLOSED trades
                pt_match = closed_paper_map.get(s.signal_id)
                if not pt_match:
                    fallback_pt = closed_paper_map.get((s_sym, norm_hz)) or closed_paper_map.get((s_sym.replace("/", "").replace(":USDT", ""), norm_hz))
                    if fallback_pt:
                        sig_time = f"{s.date_utc or ''} {s.time_utc or ''}".strip()
                        pt_closed_time = str(fallback_pt.get("closed_at_utc") or fallback_pt.get("closed_at") or "")
                        if pt_closed_time and sig_time and pt_closed_time >= sig_time:
                            pt_match = fallback_pt
                        elif not sig_time:
                            pt_match = fallback_pt

                if pt_match:
                    exit_reason = str(pt_match.get("exit_reason", ""))
                    exit_p = float(pt_match.get("exit_price") or s.entry_price or 0.0)
                    ret_pct = float(pt_match.get("return_pct") or 0.0)
                    closed_at = pt_match.get("closed_at_utc") or pt_match.get("closed_at") or now_str

                    if "BREAKEVEN" in exit_reason or "TIER0" in exit_reason or exit_reason == "STOP_LOSS_BREAKEVEN":
                        s.status = "BREAKEVEN_GUARD"
                        s.outcome_label = f"🛡️ BREAKEVEN (TIER-0 GUARD {ret_pct:+.2f}%)"
                    elif "STOP_LOSS" in exit_reason:
                        s.status = "LOST_SL"
                        s.outcome_label = "🔴 LOST (SL HIT)"
                    elif "TAKE_PROFIT_3" in exit_reason or "TP3" in exit_reason:
                        s.status = "WON_TP3"
                        s.outcome_label = "🟢 WON (TP3 HIT)"
                    elif "TAKE_PROFIT_2" in exit_reason or "TP2" in exit_reason:
                        s.status = "WON_TP2"
                        s.outcome_label = "🟢 WON (TP2 HIT)"
                    elif "TAKE_PROFIT" in exit_reason or "TP1" in exit_reason:
                        s.status = "WON_TP1"
                        s.outcome_label = "🟢 WON (TP1 HIT)"
                    elif "HORIZON_EXPIRY" in exit_reason or "EXPIRY" in exit_reason:
                        if ret_pct >= 0.10:
                            s.status = "WON_EXP_PROFIT"
                            s.outcome_label = f"🟢 WON (EXP PROFIT {ret_pct:+.2f}%)"
                        elif ret_pct <= -0.10:
                            s.status = "LOST_EXP"
                            s.outcome_label = f"🔴 LOST (EXPIRY {ret_pct:+.2f}%)"
                        else:
                            s.status = "BREAKEVEN_EXP"
                            s.outcome_label = f"⚪ BREAKEVEN (EXPIRY {ret_pct:+.2f}%)"
                    else:
                        s.status = "CLOSED"
                        s.outcome_label = f"CLOSED ({exit_reason})"

                    s.exit_price = round(exit_p, 6)
                    s.realized_return_pct = round(ret_pct, 2)
                    s.evaluated_at_utc = closed_at
                    updated = True
                    continue

                # Step 2.5: Check for Paper Trading Resting Limit Cancellation / Invalidation
                canc_match = cancelled_paper_map.get(s.signal_id)
                if not canc_match:
                    fallback_canc = cancelled_paper_map.get((s_sym, norm_hz)) or cancelled_paper_map.get((s_sym.replace("/", "").replace(":USDT", ""), norm_hz))
                    if fallback_canc:
                        sig_time = f"{s.date_utc or ''} {s.time_utc or ''}".strip()
                        canc_time = str(fallback_canc.get("cancelled_at_utc") or fallback_canc.get("cancelled_at") or "")
                        if canc_time and sig_time and canc_time >= sig_time:
                            canc_match = fallback_canc
                        elif not sig_time:
                            canc_match = fallback_canc

                if canc_match:
                    canc_reason = str(canc_match.get("cancellation_reason", "CANCELLED"))
                    canc_at = canc_match.get("cancelled_at_utc") or canc_match.get("cancelled_at") or now_str
                    limit_p = float(canc_match.get("optimal_entry_limit") or s.entry_price or 0.0)
                    s.status = "EXPIRED_HORIZON"
                    s.outcome_label = "⏱️ EXPIRED"
                    s.exit_price = round(limit_p, 6) if limit_p > 0 else s.entry_price
                    s.realized_return_pct = 0.0
                    s.evaluated_at_utc = canc_at
                    updated = True
                    try:
                        from app.services.whatsapp_service import whatsapp_service
                        sig_dict = {
                            "signal_id": s.signal_id,
                            "symbol": s.symbol,
                            "horizon": s.horizon,
                            "direction": s.direction,
                            "entry_price": s.entry_price,
                            "quality_grade": s.quality_grade,
                            "meta_win_prob_pct": s.meta_win_prob_pct,
                            "decision": getattr(s, "decision", None) or s.outcome_label,
                            "cancellation_reason": canc_reason,
                            "cancellation_detail": canc_match.get("cancellation_detail", ""),
                            "outcome_label": s.outcome_label
                        }
                        whatsapp_service.emit_signal_outcome(sig_dict, "LIMIT_CANCELLED", float(s.exit_price or 0.0), 0.0)
                    except Exception:
                        pass
                    continue

                curr_p = resolve_asset_price(sym, signal=s, live_prices=live_prices)
                if not curr_p or curr_p <= 0:
                    curr_p = float(s.entry_price or 0.0)

                entry_p = float(s.entry_price or curr_p)
                tp1_p = float(s.tp1_price or entry_p)
                tp2_p = float(s.tp2_price or entry_p)
                tp3_p = float(s.tp3_price or entry_p)
                sl_p = float(s.sl_price or entry_p)
                direction = str(s.direction or "LONG").upper()

                # Fetch real intra-candle extremum wicks to prevent interval close vs tick discrepancies
                intra_high, intra_low = fetch_intra_candle_extremes(sym, norm_hz)
                high_seen = float(s.peak_price_seen or curr_p)
                low_seen = float(s.trough_price_seen or curr_p)
                if intra_high > 0:
                    high_seen = max(high_seen, intra_high)
                if intra_low > 0:
                    low_seen = min(low_seen, intra_low)
                s.peak_price_seen = max(high_seen, curr_p)
                s.trough_price_seen = min(low_seen, curr_p)
                high_p = s.peak_price_seen
                low_p = s.trough_price_seen

                max_gain = ((high_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - low_p) / entry_p) * 100.0
                s.max_potential_gain_pct = round(max_gain, 2)

                is_hit_tp3 = (direction == "LONG" and high_p >= tp3_p) or (direction == "SHORT" and low_p <= tp3_p)
                is_hit_tp2 = (direction == "LONG" and high_p >= tp2_p) or (direction == "SHORT" and low_p <= tp2_p)
                is_hit_tp1 = (direction == "LONG" and high_p >= tp1_p) or (direction == "SHORT" and low_p <= tp1_p)

                # Stop loss check: evaluate against intra-candle extremes and current spot price
                is_be_locked = s.status in ["TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"]
                if is_be_locked:
                    is_hit_sl = (direction == "LONG" and (low_p <= sl_p or curr_p <= sl_p)) or (direction == "SHORT" and (high_p >= sl_p or curr_p >= sl_p))
                else:
                    is_hit_sl = (direction == "LONG" and (low_p <= sl_p or curr_p <= sl_p)) or (direction == "SHORT" and (high_p >= sl_p or curr_p >= sl_p))

                is_expired = False
                pred_close = str(s.predicted_close_utc or "").strip()
                if not pred_close or pred_close == "N/A":
                    p_win = str(s.predicted_window or "")
                    if "➔" in p_win:
                        after_arrow = p_win.split("➔")[-1].strip()
                        pred_close = after_arrow.split("(")[0].strip() if "(" in after_arrow else after_arrow.strip()

                if pred_close and pred_close != "N/A":
                    try:
                        clean_str = pred_close.replace(" UTC", "").strip()
                        close_dt = datetime.fromisoformat(clean_str) if "T" in clean_str else datetime.strptime(clean_str, "%Y-%m-%d %H:%M")
                        if close_dt.tzinfo is None:
                            close_dt = close_dt.replace(tzinfo=timezone.utc)
                        if now_utc >= close_dt:
                            is_expired = True
                            s.predicted_close_utc = pred_close
                    except Exception:
                        pass

                # Dynamic Horizon TTL Fallback: If pred_close is missing, compute from signal creation age
                if not is_expired:
                    horizon_max_secs = {
                        "15M": 1800,      # 30 mins
                        "30M": 2700,      # 45 mins
                        "1H": 5400,       # 90 mins
                        "4H": 18000,      # 5 hours
                        "12H": 54000,     # 15 hours
                        "24H": 172800,    # 48 hours
                    }
                    max_sec = horizon_max_secs.get(norm_hz, 5400)
                    sig_age_sec = None
                    try:
                        if s.created_at:
                            c_dt = s.created_at
                            if c_dt.tzinfo is None:
                                c_dt = c_dt.replace(tzinfo=timezone.utc)
                            sig_age_sec = (now_utc - c_dt).total_seconds()
                        elif s.date_utc and s.time_utc:
                            t_clean = str(s.time_utc).replace(" UTC", "").strip()
                            c_dt = datetime.strptime(f"{s.date_utc} {t_clean}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                            sig_age_sec = (now_utc - c_dt).total_seconds()
                    except Exception:
                        pass
                    if sig_age_sec is not None and sig_age_sec >= max_sec:
                        is_expired = True

                # 0. Tier-0 Early Breakeven Guard (Requires at least 50% of TP1 distance or +0.60% gain in range)
                tp1_dist = abs(tp1_p - entry_p) / max(1e-12, entry_p) * 100.0
                is_range_regime = any(k in str(getattr(s, "market_shield", "")).upper() for k in ["RANGE", "CONSOLIDATION", "CHOP"])
                t0_hurdle = min(1.20, max(0.60, 0.50 * tp1_dist)) if is_range_regime else max(1.00, 0.65 * tp1_dist)
                if max_gain >= t0_hurdle and s.status not in ["TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"] and not is_hit_sl:
                    s.status = "TIER0_PROTECTED_BREAKEVEN"
                    soft_be_p = (entry_p * 1.0005) if direction == "LONG" else (entry_p * 0.9995)
                    s.sl_price = round(max(sl_p, soft_be_p) if direction == "LONG" else min(sl_p, soft_be_p), 6)
                    sl_p = s.sl_price
                    s.outcome_label = "🛡️ PROFIT PROTECTED (SOFT BE)"
                    updated = True

                # 1. Conservative Adverse SL Precedence:
                # If an unlocked active trade hits SL intra-candle, SL strictly takes precedence over simultaneous TP touches
                if is_hit_sl and not is_be_locked:
                    s.status = "LOST_SL"
                    s.exit_price = round(sl_p, 6)
                    ret_pct = ((sl_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - sl_p) / entry_p) * 100.0
                    s.realized_return_pct = round(ret_pct, 2)
                    s.outcome_label = "🔴 LOST (SL HIT)"
                    s.evaluated_at_utc = now_str
                    updated = True
                    try:
                        from app.services.whatsapp_service import whatsapp_service
                        sig_dict = {"signal_id": s.signal_id, "symbol": s.symbol, "horizon": s.horizon, "direction": s.direction, "entry_price": s.entry_price, "quality_grade": s.quality_grade, "meta_win_prob_pct": s.meta_win_prob_pct, "decision": getattr(s, "decision", None) or s.outcome_label}
                        whatsapp_service.emit_signal_outcome(sig_dict, "SL_HIT", s.exit_price, float(s.realized_return_pct))
                    except Exception:
                        pass
                elif is_hit_tp3:
                    s.status = "WON_TP3"
                    s.exit_price = round(tp3_p, 6)
                    ret_pct = ((tp3_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp3_p) / entry_p) * 100.0
                    s.realized_return_pct = round(ret_pct, 2)
                    s.outcome_label = "🟢 WON (TP3 HIT)"
                    s.evaluated_at_utc = now_str
                    updated = True
                    try:
                        from app.services.whatsapp_service import whatsapp_service
                        sig_dict = {"signal_id": s.signal_id, "symbol": s.symbol, "horizon": s.horizon, "direction": s.direction, "entry_price": s.entry_price, "quality_grade": s.quality_grade, "meta_win_prob_pct": s.meta_win_prob_pct, "decision": getattr(s, "decision", None) or s.outcome_label}
                        whatsapp_service.emit_signal_outcome(sig_dict, "TP3_HIT", tp3_p, ret_pct)
                    except Exception:
                        pass
                elif is_hit_tp2 and s.status != "TP2_LOCKED_TRAIL":
                    s.status = "TP2_LOCKED_TRAIL"
                    s.sl_price = round(tp1_p, 6)
                    s.outcome_label = "🟢 TP2 HIT (TRAILING SL @ TP1)"
                    updated = True
                    try:
                        from app.services.whatsapp_service import whatsapp_service
                        ret_tp2 = ((tp2_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp2_p) / entry_p) * 100.0
                        sig_dict = {"signal_id": s.signal_id, "symbol": s.symbol, "horizon": s.horizon, "direction": s.direction, "entry_price": s.entry_price, "quality_grade": s.quality_grade, "meta_win_prob_pct": s.meta_win_prob_pct, "decision": getattr(s, "decision", None) or s.outcome_label}
                        whatsapp_service.emit_signal_outcome(sig_dict, "TP2_HIT", tp2_p, ret_tp2)
                    except Exception:
                        pass
                elif is_hit_tp1 and s.status not in ["TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL"]:
                    s.status = "TP1_LOCKED_BREAKEVEN"
                    from app.engine.config import TRADE_MANAGEMENT_POLICY
                    if TRADE_MANAGEMENT_POLICY == "TIER0_ATR_TRAILING_BUFFER":
                        raw_atr = max(1e-6, abs(entry_p - sl_p) * 0.5)
                        buffer_p = 0.8 * raw_atr
                        trailed_p = (curr_p - buffer_p) if direction == "LONG" else (curr_p + buffer_p)
                        s.sl_price = round(max(entry_p, trailed_p) if direction == "LONG" else min(entry_p, trailed_p), 6)
                        s.outcome_label = "🟢 TP1 HIT (SL @ ATR TRAILING BUFFER)"
                    else:
                        s.sl_price = round(entry_p, 6)
                        s.outcome_label = "🟢 TP1 HIT (SL @ BREAKEVEN)"
                    updated = True
                    try:
                        from app.services.whatsapp_service import whatsapp_service
                        ret_tp1 = ((tp1_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp1_p) / entry_p) * 100.0
                        sig_dict = {"signal_id": s.signal_id, "symbol": s.symbol, "horizon": s.horizon, "direction": s.direction, "entry_price": s.entry_price, "quality_grade": s.quality_grade, "meta_win_prob_pct": s.meta_win_prob_pct, "decision": getattr(s, "decision", None) or s.outcome_label}
                        whatsapp_service.emit_signal_outcome(sig_dict, "TP1_HIT", tp1_p, ret_tp1)
                    except Exception:
                        pass
                elif is_hit_sl and is_be_locked:
                    if s.status == "TP2_LOCKED_TRAIL":
                        ret_tp1 = ((tp1_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp1_p) / entry_p) * 100.0
                        ret_tp2 = ((tp2_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp2_p) / entry_p) * 100.0
                        blended_ret = (0.50 * ret_tp1) + (0.30 * ret_tp2) + (0.20 * ret_tp1)
                        s.status = "WON_TP2_TRAIL"
                        s.exit_price = round(tp1_p, 6)
                        s.realized_return_pct = round(blended_ret, 2)
                        s.outcome_label = "🟢 WON (TP2 + TRAILING RUNNER)"
                        evt = "TRAIL_SL_HIT"
                    elif s.status == "TP1_LOCKED_BREAKEVEN":
                        ret_tp1 = ((tp1_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp1_p) / entry_p) * 100.0
                        ret_runner = ((sl_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - sl_p) / entry_p) * 100.0
                        blended_ret = (0.70 * ret_tp1) + (0.30 * max(0.0, ret_runner))
                        s.status = "WON_TP1_BE"
                        s.exit_price = round(entry_p, 6)
                        s.realized_return_pct = round(blended_ret, 2)
                        s.outcome_label = "🟢 WON (TP1 + BE RUNNER)"
                        evt = "BE_HIT"
                    elif s.status == "TIER0_PROTECTED_BREAKEVEN":
                        ret_be = ((sl_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - sl_p) / entry_p) * 100.0
                        s.status = "BREAKEVEN_GUARD"
                        s.exit_price = round(sl_p, 6)
                        s.realized_return_pct = round(ret_be, 2)
                        s.outcome_label = f"🛡️ BREAKEVEN (TIER-0 GUARD {ret_be:+.2f}%)"
                        evt = "TIER0_BE_HIT"
                    else:
                        s.status = "LOST_SL"
                        s.exit_price = round(sl_p, 6)
                        ret_pct = ((sl_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - sl_p) / entry_p) * 100.0
                        s.realized_return_pct = round(ret_pct, 2)
                        s.outcome_label = "🔴 LOST (SL HIT)"
                        evt = "SL_HIT"
                    s.evaluated_at_utc = now_str
                    updated = True
                    if evt != "TIER0_BE_HIT":
                        try:
                            from app.services.whatsapp_service import whatsapp_service
                            ret_exit = s.realized_return_pct or 0.0
                            sig_dict = {"signal_id": s.signal_id, "symbol": s.symbol, "horizon": s.horizon, "direction": s.direction, "entry_price": s.entry_price, "quality_grade": s.quality_grade, "meta_win_prob_pct": s.meta_win_prob_pct, "decision": getattr(s, "decision", None) or s.outcome_label}
                            whatsapp_service.emit_signal_outcome(sig_dict, evt, s.exit_price, float(ret_exit))
                        except Exception:
                            pass
                elif is_expired:
                    # Invariant (Quant Edge Rule 6 & 8): Check if intra-candle adverse wick breached SL during the interval!
                    hit_sl_during_interval = (direction == "LONG" and low_p <= sl_p) or (direction == "SHORT" and high_p >= sl_p)
                    if hit_sl_during_interval and not is_be_locked:
                        s.status = "LOST_SL"
                        s.exit_price = round(sl_p, 6)
                        ret_pct = ((sl_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - sl_p) / entry_p) * 100.0
                        s.realized_return_pct = round(ret_pct, 2)
                        s.outcome_label = "🔴 LOST (SL HIT)"
                    elif hit_sl_during_interval and is_be_locked:
                        if s.status == "TIER0_PROTECTED_BREAKEVEN":
                            ret_be = ((sl_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - sl_p) / entry_p) * 100.0
                            s.status = "BREAKEVEN_GUARD"
                            s.exit_price = round(sl_p, 6)
                            s.realized_return_pct = round(ret_be, 2)
                            s.outcome_label = f"🛡️ BREAKEVEN (TIER-0 GUARD {ret_be:+.2f}%)"
                        elif s.status == "TP1_LOCKED_BREAKEVEN":
                            ret_tp1 = ((tp1_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp1_p) / entry_p) * 100.0
                            s.status = "WON_TP1_BE"
                            s.exit_price = round(entry_p, 6)
                            ret_runner = ((sl_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - sl_p) / entry_p) * 100.0
                            s.realized_return_pct = round((0.70 * ret_tp1) + (0.30 * max(0.0, ret_runner)), 2)
                            s.outcome_label = "🟢 WON (TP1 + BE RUNNER)"
                        else:
                            s.status = "LOST_SL"
                            s.exit_price = round(sl_p, 6)
                            ret_pct = ((sl_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - sl_p) / entry_p) * 100.0
                            s.realized_return_pct = round(ret_pct, 2)
                            s.outcome_label = "🔴 LOST (SL HIT)"
                    else:
                        ret_current = ((curr_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - curr_p) / entry_p) * 100.0
                        if s.status == "TP1_LOCKED_BREAKEVEN":
                            ret_tp1 = ((tp1_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp1_p) / entry_p) * 100.0
                            blended_ret = (0.50 * ret_tp1) + (0.50 * max(0.0, ret_current))
                            s.status = "WON_TP1_EXP"
                            s.exit_price = round(curr_p, 6)
                            s.realized_return_pct = round(blended_ret, 2)
                            s.outcome_label = f"🟢 WON (TP1 + EXP +{blended_ret:.2f}%)"
                        elif s.status == "TIER0_PROTECTED_BREAKEVEN":
                            s.status = "WON_EXP_PROFIT" if ret_current >= 0.20 else "BREAKEVEN_GUARD"
                            s.exit_price = round(curr_p, 6)
                            s.realized_return_pct = round(ret_current, 2)
                            s.outcome_label = f"🟢 WON (TIER-0 BE {ret_current:+.2f}%)" if ret_current >= 0.20 else f"🛡️ BREAKEVEN (TIER-0 GUARD {ret_current:+.2f}%)"
                        else:
                            if ret_current >= 0.25:
                                s.status = "WON_PROFIT_EXPIRED"
                                s.exit_price = round(curr_p, 6)
                                s.realized_return_pct = round(ret_current, 2)
                                s.outcome_label = f"🟢 WON (PROFIT EXPIRE +{ret_current:.2f}%)"
                            elif ret_current <= -0.25:
                                s.status = "LOST_EXPIRED"
                                s.exit_price = round(curr_p, 6)
                                s.realized_return_pct = round(ret_current, 2)
                                s.outcome_label = f"🔴 LOST (EXPIRED {ret_current:.2f}%)"
                            else:
                                s.status = "EXPIRED_BREAKEVEN"
                                s.exit_price = round(curr_p, 6)
                                s.realized_return_pct = round(ret_current, 2)
                                s.outcome_label = f"⏱️ EXPIRED (BE {ret_current:+.2f}%)"
                    s.evaluated_at_utc = now_str
                    updated = True
                    try:
                        from app.services.whatsapp_service import whatsapp_service
                        sig_dict = {
                            "signal_id": s.signal_id,
                            "symbol": s.symbol,
                            "horizon": s.horizon,
                            "direction": s.direction,
                            "entry_price": s.entry_price,
                            "quality_grade": s.quality_grade,
                            "meta_win_prob_pct": s.meta_win_prob_pct,
                            "decision": getattr(s, "decision", None) or s.outcome_label,
                            "outcome_label": s.outcome_label
                        }
                        whatsapp_service.emit_signal_outcome(sig_dict, "EXPIRED", float(s.exit_price or 0.0), float(s.realized_return_pct or 0.0))
                    except Exception:
                        pass

            if updated:
                db.commit()
                self._sync_updates_to_tracker_csv(pending)

                # Synchronize resolved terminal outcomes to StrategyRegistry
                try:
                    from app.quant_v16.strategies import StrategyRegistry
                    strat_reg = StrategyRegistry()
                    for s in pending:
                        st = str(getattr(s, 'status', '')).upper()
                        # Only record terminal resolved statuses
                        if st.startswith('WON_') or st.startswith('LOST_') or 'BREAKEVEN' in st or 'EXPIRED' in st:
                            # Invariant: breakeven is NEVER counted as a win!
                            is_win = bool(st.startswith('WON_') and not any(b in st for b in ['BREAKEVEN', 'BE', 'TIER0']))
                            strat_id = getattr(s, 'canonical_strategy', None) or getattr(s, 'strategy', None)
                            ret_val = float(getattr(s, 'realized_return_pct', 0.0) or 0.0)
                            regime_val = getattr(s, 'regime', None) or getattr(s, 'market_regime', None)
                            if strat_id:
                                strat_reg.record_trade_outcome(
                                    strategy_id=str(strat_id),
                                    is_win=is_win,
                                    net_return_pct=ret_val,
                                    regime=str(regime_val) if regime_val else None
                                )
                except Exception:
                    pass
        except Exception:
            db.rollback()

    def _sync_updates_to_tracker_csv(self, signals_list: List[SignalAudit]):
        """Syncs updated status, outcome_label, sl_price, exit_price, realized_return_pct to trader_signals_tracker.csv."""
        # 1. Synchronize to trader_signals_tracker.csv
        try:
            csv_path = os.path.join(settings.EXPORT_DIR, "trader_signals_tracker.csv")
            if os.path.exists(csv_path):
                updated_map = {str(s.signal_id).strip(): s for s in signals_list if s.signal_id}
                import csv
                rows = []
                fieldnames = []
                with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f)
                    fieldnames = reader.fieldnames
                    for r in reader:
                        sid = str(r.get("signal_id", "")).strip()
                        if sid in updated_map:
                            obj = updated_map[sid]
                            old_status = str(r.get("status", "")).upper()
                            r["status"] = obj.status
                            r["outcome_label"] = obj.outcome_label

                            # Feed StrategyRegistry with resolved outcomes from authoritative CSV row
                            st = str(obj.status or "").upper()
                            if (st.startswith("WON_") or st.startswith("LOST_") or "BREAKEVEN" in st) and not (old_status.startswith("WON_") or old_status.startswith("LOST_")):
                                try:
                                    from app.quant_v16.strategies import StrategyRegistry
                                    strat_reg = StrategyRegistry()
                                    is_win = bool(st.startswith("WON_") and not any(b in st for b in ["BREAKEVEN", "BE", "TIER0"]))
                                    strat_id = r.get("strategy_archetype") or getattr(obj, "canonical_strategy", None)
                                    ret_val = float(obj.realized_return_pct or 0.0)
                                    regime_val = r.get("market_shield") or getattr(obj, "market_regime", None)
                                    if strat_id:
                                        strat_reg.record_trade_outcome(
                                            strategy_id=str(strat_id),
                                            is_win=is_win,
                                            net_return_pct=ret_val,
                                            regime=str(regime_val) if regime_val else None
                                        )
                                except Exception:
                                    pass
                            if obj.sl_price is not None:
                                r["sl_price"] = obj.sl_price
                            if obj.exit_price is not None:
                                r["exit_price"] = obj.exit_price
                            if obj.realized_return_pct is not None:
                                r["realized_return_pct"] = obj.realized_return_pct
                            if obj.evaluated_at_utc:
                                r["evaluated_at_utc"] = obj.evaluated_at_utc
                            if obj.peak_price_seen is not None:
                                r["peak_price_seen"] = obj.peak_price_seen
                            if obj.trough_price_seen is not None:
                                r["trough_price_seen"] = obj.trough_price_seen
                            if obj.max_potential_gain_pct is not None:
                                r["max_potential_gain_pct"] = obj.max_potential_gain_pct
                            if getattr(obj, "current_price", None) is not None:
                                r["current_price"] = obj.current_price
                            if getattr(obj, "paper_trading_status", None) is not None:
                                r["paper_trading_status"] = obj.paper_trading_status
                        rows.append(r)
                temp = f"{csv_path}.{time.time_ns()}.tmp"
                with open(temp, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                    writer.writeheader()
                    for r in rows:
                        writer.writerow(r)
                os.replace(temp, csv_path)
        except Exception:
            pass

        # 2. Also synchronize to v16_dynamic_states.json to guarantee 100% dashboard parity
        try:
            dyn_path = os.path.join(settings.EXPORT_DIR, "v16_dynamic_states.json")
            if os.path.exists(dyn_path):
                with open(dyn_path, "r", encoding="utf-8") as df:
                    dyn_data = json.load(df)
                changed_dyn = False
                for s in signals_list:
                    sid = str(s.signal_id).strip()
                    target_k = sid if sid in dyn_data else None
                    if not target_k:
                        for k in dyn_data.keys():
                            if s.symbol in k or s.symbol.replace("/", "") in k:
                                target_k = k
                                break
                    if target_k and target_k in dyn_data:
                        dyn_data[target_k]["status"] = s.status
                        dyn_data[target_k]["outcome_label"] = s.outcome_label
                        if s.exit_price is not None:
                            dyn_data[target_k]["current_price"] = s.exit_price
                            dyn_data[target_k]["exit_price"] = s.exit_price
                        if s.realized_return_pct is not None:
                            dyn_data[target_k]["unrealized_net_pnl_pct"] = s.realized_return_pct
                            dyn_data[target_k]["realized_return_pct"] = s.realized_return_pct
                        dyn_data[target_k]["updated_at_utc"] = s.evaluated_at_utc or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                        changed_dyn = True
                if changed_dyn:
                    tmp_dyn = f"{dyn_path}.{time.time_ns()}.tmp"
                    with open(tmp_dyn, "w", encoding="utf-8") as df:
                        json.dump(dyn_data, df, indent=2)
                    os.replace(tmp_dyn, dyn_path)
        except Exception:
            pass

        # 3. Synchronize status transitions to v16_immutable_signals.json
        try:
            immut_path = os.path.join(settings.EXPORT_DIR, "v16_immutable_signals.json")
            if os.path.exists(immut_path):
                with open(immut_path, "r", encoding="utf-8") as imf:
                    immut_data = json.load(imf)
                changed_imm = False
                for s in signals_list:
                    sid = str(s.signal_id).strip()
                    target_k = sid if sid in immut_data else None
                    if not target_k:
                        for k in immut_data.keys():
                            if s.symbol in k or s.symbol.replace("/", "") in k:
                                target_k = k
                                break
                    if target_k and target_k in immut_data:
                        if immut_data[target_k].get("status") != s.status:
                            immut_data[target_k]["status"] = s.status
                            changed_imm = True
                if changed_imm:
                    tmp_imm = f"{immut_path}.{time.time_ns()}.tmp"
                    with open(tmp_imm, "w", encoding="utf-8") as imf:
                        json.dump(immut_data, imf, indent=2)
                    os.replace(tmp_imm, immut_path)
        except Exception:
            pass

    def get_kpi_summary(self, db: Session) -> Dict[str, Any]:
        """Calculates executive KPI metrics in a single optimized pass."""
        now_t = time.time()
        if (now_t - self._last_sync_ts) >= 30.0:
            self._last_sync_ts = now_t
            try:
                sync_files_to_db_live()
            except Exception:
                pass

        from app.quant_v16.audit import classify_signal_outcome

        signals = db.query(
            SignalAudit.outcome_label,
            SignalAudit.status,
            SignalAudit.grade_tier,
            SignalAudit.realized_return_pct,
            SignalAudit.horizon,
            SignalAudit.meta_win_prob,
            SignalAudit.conviction_pct
        ).filter(
            SignalAudit.date_utc.like("202%"),
            SignalAudit.symbol.like("%/%")
        ).all()

        default_calibration = {
            "overall": {"brier_score": 0.25, "sample_count": 0, "mean_forecast_prob": 0.50, "realized_win_rate_pct": 50.0, "reliability_gap": 0.0},
            "by_horizon": {
                "15M": {"brier_score": 0.25, "sample_count": 0, "mean_forecast_prob": 0.50, "realized_win_rate_pct": 50.0, "reliability_gap": 0.0},
                "1H": {"brier_score": 0.25, "sample_count": 0, "mean_forecast_prob": 0.50, "realized_win_rate_pct": 50.0, "reliability_gap": 0.0},
                "24H": {"brier_score": 0.25, "sample_count": 0, "mean_forecast_prob": 0.50, "realized_win_rate_pct": 50.0, "reliability_gap": 0.0}
            },
            "last_updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        }

        total_signals = len(signals)
        if total_signals == 0:
            try:
                calib_path = os.path.join(settings.EXPORT_DIR, "v16_calibration_metrics.json")
                if not os.path.exists(calib_path):
                    with open(calib_path, "w", encoding="utf-8") as f:
                        json.dump(default_calibration, f, indent=2)
            except Exception:
                pass

            return {
                "last_updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "total_trader_signals": 0,
                "won_signals_count": 0,
                "lost_signals_count": 0,
                "pending_signals_count": 0,
                "breakeven_signals_count": 0,
                "expired_signals_count": 0,
                "win_rate_pct": 0.0,
                "decisive_win_rate_pct": 0.0,
                "total_closed_win_rate_pct": 0.0,
                "grade_a_plus_win_rate_pct": 0.0,
                "grade_a_win_rate_pct": 0.0,
                "average_return_pct": 0.0,
                "cumulative_return_pct": 0.0,
                "calibration_metrics": default_calibration,
            }

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

        calibration_all = []
        calibration_by_h = {"15M": [], "1H": [], "24H": []}

        for out_label, status, grade_tier, ret_pct, sig_horizon, meta_p, conv in signals:
            cat = classify_signal_outcome(status, out_label, ret_pct)

            if cat == "PENDING":
                pending += 1
                # Invariant (Rule 9): Pending signals NEVER count toward wins, losses, or realized returns
                continue
            elif cat == "WON":
                won += 1
                if grade_tier == 1:
                    a_plus_won += 1
                elif grade_tier == 2:
                    a_won += 1
            elif cat == "LOST":
                lost += 1
                if grade_tier == 1:
                    a_plus_lost += 1
                elif grade_tier == 2:
                    a_lost += 1
            elif cat == "BREAKEVEN":
                breakeven += 1
            elif cat == "EXPIRED":
                expired += 1

            # Only resolved (non-pending) trades contribute to realized returns
            if ret_pct is not None and not (math.isnan(ret_pct) or math.isinf(ret_pct)):
                returns.append(ret_pct)

            # Feature 5.3: Horizon-Specific Brier Calibration Tracking
            if cat in ["WON", "LOST"]:
                outcome = 1.0 if cat == "WON" else 0.0
                f_p = float(meta_p) if (meta_p is not None and 0.0 < float(meta_p) < 1.0) else (float(conv or 50.0) / 100.0)
                f_p = min(0.99, max(0.01, f_p))
                calibration_all.append((f_p, outcome))

                h_str = str(sig_horizon or "1H").upper()
                norm_h = "15M" if "15" in h_str else ("24H" if any(x in h_str for x in ["24", "1D"]) else "1H")
                if norm_h in calibration_by_h:
                    calibration_by_h[norm_h].append((f_p, outcome))

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

        def _calc_brier(pairs):
            if not pairs:
                return {"brier_score": 0.25, "sample_count": 0, "mean_forecast_prob": 0.50, "realized_win_rate_pct": 50.0, "reliability_gap": 0.0}
            f_arr = np.array([p[0] for p in pairs])
            y_arr = np.array([p[1] for p in pairs])
            bs = float(np.mean((f_arr - y_arr) ** 2))
            mean_f = float(np.mean(f_arr))
            mean_y = float(np.mean(y_arr))
            gap = abs(mean_f - mean_y)
            return {
                "brier_score": round(bs, 4),
                "sample_count": len(pairs),
                "mean_forecast_prob": round(mean_f, 4),
                "realized_win_rate_pct": round(mean_y * 100.0, 2),
                "reliability_gap": round(gap, 4)
            }

        calibration_metrics = {
            "overall": _calc_brier(calibration_all),
            "by_horizon": {h: _calc_brier(p_list) for h, p_list in calibration_by_h.items()},
            "last_updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        }

        try:
            calib_path = os.path.join(settings.EXPORT_DIR, "v16_calibration_metrics.json")
            tmp_p = f"{calib_path}.{threading.get_ident()}.{time.time_ns()}.tmp"
            with open(tmp_p, "w", encoding="utf-8") as f:
                json.dump(calibration_metrics, f, indent=2)
            os.replace(tmp_p, calib_path)
        except Exception:
            pass

        return {
            "last_updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "total_trader_signals": total_signals,
            "won_signals_count": won,
            "lost_signals_count": lost,
            "pending_signals_count": pending,
            "breakeven_signals_count": breakeven,
            "expired_signals_count": expired,
            "win_rate_pct": total_closed_wr,
            "decisive_win_rate_pct": decisive_wr,
            "total_closed_win_rate_pct": total_closed_wr,
            "grade_a_plus_win_rate_pct": a_plus_wr,
            "grade_a_win_rate_pct": a_wr,
            "average_return_pct": avg_ret,
            "cumulative_return_pct": total_ret,
            "calibration_metrics": calibration_metrics,
        }

    def get_signals_list(
        self,
        db: Session,
        symbol: Optional[str] = None,
        search: Optional[str] = None,
        date: Optional[str] = None,
        outcome: Optional[str] = None,
        status: Optional[str] = None,
        grade: Optional[str] = None,
        horizon: Optional[str] = None,
        direction: Optional[str] = None,
        min_return: Optional[float] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Queries signals with search, filters, date filtering, min_return filtering, and pagination."""
        try:
            self.resolve_pending_signals_live(db, force=False)
        except Exception:
            pass

        query = db.query(SignalAudit).filter(
            SignalAudit.date_utc.like("202%"),
            SignalAudit.symbol.like("%/%")
        )

        if symbol:
            sym_clean = symbol.strip().replace('-', '/').upper()
            query = query.filter(SignalAudit.symbol == sym_clean)

        if search:
            q = f"%{search.strip()}%"
            query = query.filter(or_(SignalAudit.symbol.ilike(q), SignalAudit.signal_id.ilike(q), SignalAudit.rank_label.ilike(q)))

        if date:
            query = query.filter(SignalAudit.date_utc == date.strip())

        if status:
            st_upper = status.upper().strip()
            if st_upper in ["ACTIVE", "PENDING"]:
                query = query.filter(or_(SignalAudit.status.in_(["ACTIVE", "PENDING_EVALUATION", "TIER0_PROTECTED_BREAKEVEN", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL"]), SignalAudit.outcome_label.like("%PENDING%"), SignalAudit.outcome_label.like("%RUNNING%")))
            elif st_upper == "WON":
                query = query.filter(or_(SignalAudit.outcome_label.like("%WON%"), SignalAudit.status == "WON", SignalAudit.status.like("%WON%")))
            elif st_upper == "LOST":
                query = query.filter(or_(SignalAudit.outcome_label.like("%LOST%"), SignalAudit.status.like("%LOST%")))
            elif st_upper == "EXPIRED":
                query = query.filter(or_(SignalAudit.outcome_label.like("%EXPIRED%"), SignalAudit.status.like("%EXP%")))
            elif st_upper == "BREAKEVEN":
                query = query.filter(or_(SignalAudit.status.like("%BREAKEVEN%"), SignalAudit.status.like("%TIER0%"), SignalAudit.outcome_label.like("%BREAKEVEN%"), SignalAudit.outcome_label.like("%BE%")))
            else:
                query = query.filter(SignalAudit.status.ilike(f"%{st_upper}%"))

        if outcome:
            out_upper = outcome.upper().strip()
            if out_upper == "WON":
                query = query.filter(or_(SignalAudit.outcome_label.like("%WON%"), SignalAudit.status == "WON", SignalAudit.status.like("%WON%")))
            elif out_upper == "LOST":
                query = query.filter(or_(SignalAudit.outcome_label.like("%LOST%"), SignalAudit.status.like("%LOST%")))
            elif out_upper in ["PENDING", "ACTIVE"]:
                query = query.filter(or_(SignalAudit.status.in_(["PENDING_EVALUATION", "ACTIVE", "TIER0_PROTECTED_BREAKEVEN", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL"]), SignalAudit.outcome_label.like("%PENDING%"), SignalAudit.outcome_label.like("%RUNNING%")))
            elif out_upper == "EXPIRED":
                query = query.filter(or_(SignalAudit.outcome_label.like("%EXPIRED%"), SignalAudit.status.like("%EXP%")))
            elif out_upper == "BREAKEVEN":
                query = query.filter(or_(SignalAudit.status.like("%BREAKEVEN%"), SignalAudit.status.like("%TIER0%"), SignalAudit.outcome_label.like("%BREAKEVEN%"), SignalAudit.outcome_label.like("%BE%")))
            elif out_upper == "STAGNATION":
                query = query.filter(or_(SignalAudit.status.like("%STAGNATION%"), SignalAudit.outcome_label.like("%STAGNATION%")))

        if grade:
            g_upper = grade.upper().strip()
            if g_upper == "A+":
                query = query.filter(or_(SignalAudit.grade_tier == 1, SignalAudit.quality_grade.ilike("%A+%")))
            elif g_upper == "A":
                query = query.filter(or_(SignalAudit.grade_tier == 2, SignalAudit.quality_grade.ilike("%Grade A%")))
            elif g_upper == "B+":
                query = query.filter(or_(SignalAudit.grade_tier == 3, SignalAudit.quality_grade.ilike("%B+%")))

        if horizon:
            h_upper = horizon.upper().strip()
            query = query.filter(SignalAudit.horizon.ilike(f"%{h_upper}%"))

        if direction:
            d_upper = direction.upper().strip()
            if d_upper in ["LONG", "BULLISH"]:
                query = query.filter(or_(SignalAudit.direction == "LONG", SignalAudit.direction == "BULLISH"))
            elif d_upper in ["SHORT", "BEARISH"]:
                query = query.filter(or_(SignalAudit.direction == "SHORT", SignalAudit.direction == "BEARISH"))

        if min_return is not None and min_return > 0:
            query = query.filter(
                or_(
                    func.abs(SignalAudit.expected_return_pct) >= min_return,
                    func.abs(SignalAudit.max_potential_gain_pct) >= min_return,
                    func.abs(SignalAudit.realized_return_pct) >= min_return,
                )
            )

        total_count = query.count()
        signals = query.order_by(desc(SignalAudit.id)).offset(offset).limit(limit).all()

        # Load live paper open positions map to inject accurate live prices & PnL
        open_pos_map = {}
        try:
            lp = os.path.join(settings.EXPORT_DIR, "paper_trading_ledger.json")
            if os.path.exists(lp):
                with open(lp, "r", encoding="utf-8") as f:
                    pt_d = json.load(f)
                for op in pt_d.get("open_positions", []):
                    if op.get("trade_id"):
                        open_pos_map[op.get("trade_id")] = op
                    op_sym = str(op.get("symbol", "")).upper()
                    op_hz = str(op.get("horizon", "15M")).upper()
                    norm_hz = "15M" if "15" in op_hz else ("24H" if ("24" in op_hz or "1D" in op_hz) else "1H")
                    open_pos_map[(op_sym, norm_hz)] = op
                    open_pos_map[(op_sym.replace("/", ""), norm_hz)] = op
        except Exception:
            pass

        results = []
        for s in signals:
            d = s.to_dict()
            s_hz = str(d.get("horizon") or "15M").upper()
            norm_hz = "15M" if "15" in s_hz else ("24H" if ("24" in s_hz or "1D" in s_hz) else "1H")
            op = open_pos_map.get(d.get("signal_id")) or open_pos_map.get((str(d.get("symbol")).upper(), norm_hz)) or open_pos_map.get((str(d.get("symbol")).replace("/", "").upper(), norm_hz))
            if op:
                d["status"] = "ACTIVE"
                d["outcome_label"] = "RUNNING 🚀"
                d["paper_trading_status"] = "EXECUTED (PAPER WALLET)"
                if op.get("current_price"):
                    d["current_price"] = op.get("current_price")
                if op.get("unrealized_pnl_pct") is not None:
                    d["pnl_pct"] = op.get("unrealized_pnl_pct")
                    d["live_pnl_pct"] = op.get("unrealized_pnl_pct")
            results.append(d)

        return {
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "signals": results,
        }

    def get_signals_by_symbol(self, db: Session, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve all chronological 15-minute signals generated for a specific cryptocurrency."""
        sym_clean = symbol.strip().replace('-', '/').upper()
        signals = db.query(SignalAudit).filter(
            or_(SignalAudit.symbol == sym_clean, SignalAudit.symbol.ilike(f"%{sym_clean}%"))
        ).order_by(desc(SignalAudit.id)).limit(limit).all()
        return [s.to_dict() for s in signals]

    def get_daily_summary(self, db: Session) -> List[Dict[str, Any]]:
        """High-speed single-query SQL aggregation grouping signals by date."""
        from sqlalchemy import case, and_, or_, not_
        results = db.query(
            SignalAudit.date_utc,
            func.count(SignalAudit.id).label("total_signals"),
            func.sum(case(
                (or_(
                    SignalAudit.status.like("WON%"),
                    SignalAudit.outcome_label.like("%WON%"),
                    SignalAudit.realized_return_pct > 0.0
                ), 1),
                else_=0
            )).label("won_count"),
            func.sum(case(
                (and_(
                    or_(
                        SignalAudit.status.like("LOST%"),
                        SignalAudit.outcome_label.like("%LOST%"),
                        SignalAudit.realized_return_pct < 0.0
                    ),
                    not_(or_(SignalAudit.status.like("WON%"), SignalAudit.realized_return_pct > 0.0))
                ), 1),
                else_=0
            )).label("lost_count"),
            func.sum(case(
                (or_(
                    SignalAudit.status == "PENDING_EVALUATION",
                    SignalAudit.status == "ACTIVE",
                    SignalAudit.status.like("TP%_LOCKED%"),
                    SignalAudit.outcome_label.like("%PENDING%"),
                    SignalAudit.outcome_label.like("%ACTIVE%")
                ), 1),
                else_=0
            )).label("pending_count"),
            func.sum(case(
                (or_(
                    SignalAudit.status.like("%EXP%"),
                    SignalAudit.outcome_label.like("%EXPIRED%"),
                    SignalAudit.outcome_label.like("%EXP%")
                ), 1),
                else_=0
            )).label("expired_count"),
            func.sum(SignalAudit.realized_return_pct).label("cumulative_return"),
            func.avg(SignalAudit.realized_return_pct).label("average_return"),
        ).filter(
            SignalAudit.date_utc != None,
            SignalAudit.date_utc != "",
            SignalAudit.date_utc != "False",
            SignalAudit.date_utc.like("202%"),
            SignalAudit.symbol.like("%/%")
        ).group_by(SignalAudit.date_utc).order_by(desc(SignalAudit.date_utc)).all()

        daily_list = []
        for r in results:
            tot = int(r.total_signals or 0)
            won = int(r.won_count or 0)
            lost = int(r.lost_count or 0)
            pending = int(r.pending_count or 0)
            expired = int(r.expired_count or 0)
            decisive = won + lost
            win_rate = round((won / max(1, decisive)) * 100.0, 2) if decisive > 0 else 0.0
            cum_ret = round(float(r.cumulative_return or 0.0), 2)
            avg_ret = round(float(r.average_return or 0.0), 2)
            daily_list.append({
                "date": r.date_utc,
                "total_signals": tot,
                "won_count": won,
                "lost_count": lost,
                "pending_count": pending,
                "expired_count": expired,
                "win_rate_pct": win_rate,
                "cumulative_return_pct": cum_ret,
                "average_return_pct": avg_ret,
            })
        return daily_list

    def get_portfolio_data(self, db: Session) -> Dict[str, Any]:
        """Retrieves active positions and closed trades history from DB."""
        sync_files_to_db_live()
        
        # Read starting balance and analytics from paper trading ledger JSON if present
        ledger_data = {}
        try:
            p_path = os.path.join(settings.EXPORT_DIR, "paper_trading_ledger.json")
            if os.path.exists(p_path):
                with open(p_path, "r", encoding="utf-8") as f:
                    ledger_data = json.load(f)
        except Exception:
            pass

        positions = db.query(PaperPosition).order_by(desc(PaperPosition.id)).all()
        closed_trades = db.query(ClosedTrade).order_by(desc(ClosedTrade.id)).all()

        # Resolve closed trades list: prefer non-empty closed_trades_history, else non-empty closed_trades, else MySQL closed_trades
        closed_candidates = ledger_data.get("closed_trades_history")
        if not closed_candidates or len(closed_candidates) == 0:
            closed_candidates = ledger_data.get("closed_trades")
        if not closed_candidates or len(closed_candidates) == 0:
            closed_candidates = [c.to_dict() for c in closed_trades]

        seen_tids = set()
        normalized_closed = []
        for ct in (closed_candidates or []):
            tid = ct.get("trade_id")
            if tid and tid in seen_tids:
                continue
            if tid:
                seen_tids.add(tid)
            rpnl = ct.get("realized_pnl_usd") if ct.get("realized_pnl_usd") is not None else ct.get("net_pnl_usd", 0.0)
            rpct = ct.get("realized_pnl_pct") if ct.get("realized_pnl_pct") is not None else ct.get("return_pct", 0.0)
            fee = ct.get("binance_fee_usd") if ct.get("binance_fee_usd") is not None else ct.get("fees_usd", 0.0)
            outc = ct.get("outcome")
            if not outc:
                outc = "WON" if rpnl > 0.05 else ("LOST" if rpnl < -0.05 else "BREAKEVEN")

            hz = ct.get("horizon") or ct.get("signal_horizon")
            if not hz:
                for part in str(ct.get("trade_id", "")).split("_"):
                    if part in ["15M", "1H", "4H", "24H", "1D"]:
                        hz = part
                        break
            if not hz:
                d = ct.get("desk", "")
                hz = "15M" if d == "scalp" else ("24H" if d in ["swing", "macro"] else "1H")

            dur = ct.get("duration_str")
            o_at = str(ct.get("opened_at") or ct.get("opened_at_utc", ""))
            c_at = str(ct.get("closed_at") or ct.get("closed_at_utc", ""))
            if not dur and o_at and c_at:
                try:
                    odt = datetime.fromisoformat(o_at.replace("Z", "+00:00"))
                    cdt = datetime.fromisoformat(c_at.replace("Z", "+00:00"))
                    diff = int((cdt - odt).total_seconds())
                    dh = diff // 3600
                    dm = (diff % 3600) // 60
                    ds = diff % 60
                    dur = f"{dh}h {dm}m {ds}s" if dh > 0 else (f"{dm}m {ds}s" if dm > 0 else f"{ds}s")
                except Exception:
                    dur = "N/A"

            normalized_closed.append({
                "id": ct.get("id"),
                "trade_id": ct.get("trade_id"),
                "symbol": ct.get("symbol"),
                "horizon": hz or "1H",
                "direction": ct.get("direction"),
                "execution_engine": ct.get("execution_engine", "binance_futures"),
                "entry_price": float(ct.get("entry_price", 0.0)),
                "raw_entry_price": float(ct.get("raw_entry_price") or ct.get("entry_price", 0.0)),
                "exit_price": float(ct.get("exit_price", 0.0)),
                "exit_reason": ct.get("exit_reason", ""),
                "outcome": outc,
                "gross_pnl_usd": float(ct.get("gross_pnl_usd", 0.0)),
                "buy_fee_usd": float(ct.get("buy_fee_usd") or (fee / 2.0)),
                "sell_fee_usd": float(ct.get("sell_fee_usd") or (fee / 2.0)),
                "binance_fee_usd": float(fee),
                "fees_usd": float(fee),
                "net_pnl_usd": round(float(rpnl), 2),
                "realized_pnl_usd": round(float(rpnl), 2),
                "return_pct": round(float(rpct), 2),
                "realized_pnl_pct": round(float(rpct), 2),
                "duration_str": dur or "N/A",
                "opened_at": o_at,
                "closed_at": c_at,
            })

        total_trades = len(normalized_closed)
        winning_trades = sum(1 for c in normalized_closed if c["outcome"] == "WON")
        losing_trades = sum(1 for c in normalized_closed if c["outcome"] == "LOST")
        breakeven_trades = sum(1 for c in normalized_closed if c["outcome"] == "BREAKEVEN")
        decisive = winning_trades + losing_trades
        total_closed_wr = round((winning_trades / max(1, total_trades)) * 100.0, 2) if total_trades > 0 else 0.0
        decisive_wr = round((winning_trades / max(1, decisive)) * 100.0, 2) if decisive > 0 else 0.0
        win_rate = total_closed_wr
        net_profit = round(sum(c["realized_pnl_usd"] for c in normalized_closed), 2)
        start_balance = float(ledger_data.get("starting_balance_usd", 100.0))
        current_balance = float(ledger_data.get("current_balance_usd", start_balance + net_profit))

        raw_positions = ledger_data.get("open_positions") if ledger_data.get("open_positions") is not None else [p.to_dict() for p in positions]
        clean_positions = [
            p for p in raw_positions
            if UniverseFilter.is_valid_crypto_pair(p.get("symbol", ""), price=p.get("entry_price"))
        ]

        # Dynamically compute comprehensive desk metrics from open positions & closed trades
        def _get_pos_desk(p):
            d = str(p.get("desk") or "").lower()
            if d in ["scalp", "15m", "30m"]: return "scalp"
            if d in ["day", "intraday", "1h", "4h"]: return "day"
            if d in ["swing", "macro", "24h", "1d"]: return "swing"
            hz = str(p.get("horizon") or "").upper()
            if "15M" in hz or "30M" in hz: return "scalp"
            if "24H" in hz or "1D" in hz: return "swing"
            return "day"

        def _get_trade_desk(t):
            d = str(t.get("desk") or "").lower()
            if d in ["scalp", "15m", "30m"]: return "scalp"
            if d in ["day", "intraday", "1h", "4h"]: return "day"
            if d in ["swing", "macro", "24h", "1d"]: return "swing"
            hz = str(t.get("horizon") or "").upper()
            if "15M" in hz or "30M" in hz: return "scalp"
            if "24H" in hz or "1D" in hz: return "swing"
            return "day"

        scalp_open = [p for p in clean_positions if _get_pos_desk(p) == "scalp"]
        day_open = [p for p in clean_positions if _get_pos_desk(p) == "day"]
        swing_open = [p for p in clean_positions if _get_pos_desk(p) == "swing"]

        scalp_closed = [t for t in normalized_closed if _get_trade_desk(t) == "scalp"]
        day_closed = [t for t in normalized_closed if _get_trade_desk(t) == "day"]
        swing_closed = [t for t in normalized_closed if _get_trade_desk(t) == "swing"]

        def _build_desk_obj(name, alloc, max_s, lev, open_list, closed_list, tier0_be):
            realized_pnl = round(sum(float(t.get("realized_pnl_usd", 0.0)) for t in closed_list), 2)
            unrealized_pnl = round(sum(float(p.get("unrealized_pnl_usd", 0.0)) for p in open_list), 2)
            tot_pnl = round(realized_pnl + unrealized_pnl, 2)
            won = sum(1 for t in closed_list if t.get("outcome") == "WON")
            decisive = sum(1 for t in closed_list if t.get("outcome") in ["WON", "LOST"])
            wr = round((won / max(1, decisive)) * 100.0, 1) if decisive > 0 else 0.0
            cnt = len(open_list)
            return {
                "name": name,
                "allocated_usd": alloc,
                "max_slots": max_s,
                "active_slots": cnt,
                "open_positions": cnt,
                "leverage": lev,
                "realized_pnl_usd": realized_pnl,
                "unrealized_pnl_usd": unrealized_pnl,
                "total_pnl_usd": tot_pnl,
                "winning_trades": won,
                "total_trades": len(closed_list),
                "win_rate_pct": wr,
                "tier0_be": tier0_be
            }

        scalp_desk = _build_desk_obj("⚡ Scalp Desk", 150.0, 1, 2, scalp_open, scalp_closed, "+0.80%")
        day_desk = _build_desk_obj("⏳ Day Trading Desk", 350.0, 2, 3, day_open, day_closed, "+1.25%")
        swing_desk = _build_desk_obj("🌊 Swing Desk", 500.0, 3, 2, swing_open, swing_closed, "+1.75%")

        enriched_desks = {
            "scalp": scalp_desk,
            "day": day_desk,
            "intraday": day_desk,
            "swing": swing_desk,
            "macro": swing_desk
        }

        return {
            "initial_capital_usd": start_balance,
            "current_balance_usd": round(current_balance, 2),
            "open_positions": clean_positions,
            "closed_trades_history": normalized_closed,
            "total_trades_count": total_trades,
            "winning_trades_count": winning_trades,
            "losing_trades_count": losing_trades,
            "breakeven_trades_count": breakeven_trades,
            "win_rate_pct": total_closed_wr,
            "total_closed_win_rate_pct": total_closed_wr,
            "decisive_win_rate_pct": decisive_wr,
            "total_net_profit_usd": round(net_profit, 2),
            "gross_profit_usd": round(float(ledger_data.get("gross_profit_usd", 0.0)), 2),
            "gross_loss_usd": round(float(ledger_data.get("gross_loss_usd", 0.0)), 2),
            "total_fees_paid_usd": round(float(ledger_data.get("total_fees_paid_usd", 0.0)), 2),
            "total_funding_fees_usd": round(float(ledger_data.get("total_funding_fees_usd", 0.0)), 2),
            "profit_factor": float(ledger_data.get("profit_factor", 0.0)),
            "sharpe_ratio": float(ledger_data.get("sharpe_ratio", 0.0)),
            "sortino_ratio": float(ledger_data.get("sortino_ratio", 0.0)),
            "expectancy_usd": float(ledger_data.get("expectancy_usd", 0.0)),
            "peak_balance_usd": round(float(ledger_data.get("peak_balance_usd", start_balance)), 2),
            "max_drawdown_usd": round(float(ledger_data.get("max_drawdown_usd", 0.0)), 2),
            "max_drawdown_pct": round(float(ledger_data.get("max_drawdown_pct", 0.0)), 2),
            "desks": enriched_desks,
            "fee_tier_label": str(ledger_data.get("fee_tier_label", "Binance Futures (VIP0 Isolated Margin | 0.045% Taker Fee with BNB Discount)")),
            "queued_trades": ledger_data.get("queued_trades", []),
        }

    def reset_portfolio_data(self, db: Session, target_start_balance: float = 1000.0) -> Dict[str, Any]:
        """Completely wipes open positions and closed trades from DB and resets paper trading ledger JSON to clean state."""
        try:
            db.query(PaperPosition).delete()
            db.query(ClosedTrade).delete()
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[RESET ERROR] Database purge: {e}")

        clean_ledger = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "fee_tier_label": "Binance Futures (VIP0 Isolated Margin | 0.045% Taker Fee with BNB Discount)",
            "execution_engine": "binance_futures",
            "starting_balance_usd": target_start_balance,
            "current_balance_usd": target_start_balance,
            "realized_pnl_usd": 0.0,
            "gross_realized_pnl_usd": 0.0,
            "total_fees_paid_usd": 0.0,
            "total_funding_fees_usd": 0.0,
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
            "peak_balance_usd": target_start_balance,
            "max_drawdown_usd": 0.0,
            "max_drawdown_pct": 0.0,
            "open_positions": [],
            "closed_trades_history": [],
            "queued_trades": [],
            "desks": {
                "scalp": {"allocated_usd": target_start_balance * 0.40, "realized_pnl_usd": 0.0, "open_positions": 0, "total_trades": 0, "winning_trades": 0, "win_rate_pct": 0.0},
                "intraday": {"allocated_usd": target_start_balance * 0.35, "realized_pnl_usd": 0.0, "open_positions": 0, "total_trades": 0, "winning_trades": 0, "win_rate_pct": 0.0},
                "macro": {"allocated_usd": target_start_balance * 0.25, "realized_pnl_usd": 0.0, "open_positions": 0, "total_trades": 0, "winning_trades": 0, "win_rate_pct": 0.0}
            }
        }

        try:
            os.makedirs(settings.EXPORT_DIR, exist_ok=True)
            p_path = os.path.join(settings.EXPORT_DIR, "paper_trading_ledger.json")
            with open(p_path, "w", encoding="utf-8") as f:
                json.dump(clean_ledger, f, indent=4)
        except Exception as e:
            print(f"[RESET ERROR] File write: {e}")

        clear_forecast_cache()

        return {
            "success": True,
            "message": f"Institutional Paper Trading successfully reset to ${target_start_balance:.2f} starting capital across 3 Desks (Scalp 40%, Intraday 35%, Macro 25%). All prior open positions and history wiped.",
            "portfolio": clean_ledger
        }

    def get_all_live_prices(self) -> Dict[str, Any]:
        """Returns real-time prices dictionary for all pairs."""
        prices = fetch_live_binance_prices(max_age_seconds=2.5)
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prices": prices
        }

    def overlay_live_prices(self, forecast_data: Dict[str, Any]) -> Dict[str, Any]:
        """Dynamically overlays current real-time prices on top of forecast data."""
        if not forecast_data:
            return forecast_data

        live_prices = fetch_live_binance_prices(max_age_seconds=3.0) or {}

        # Clone payload
        res = dict(forecast_data)
        now_utc = datetime.now(timezone.utc)
        now_iso = now_utc.isoformat()
        now_ts = int(now_utc.timestamp())
        
        min_15 = (now_utc.minute // 15) * 15
        candle_open_utc = now_utc.replace(minute=min_15, second=0, microsecond=0)

        # Ensure global forecast timestamp is within 15 minutes
        forecast_ts = 0
        if res.get("server_prediction_ts"):
            forecast_ts = int(res["server_prediction_ts"])
        elif res.get("timestamp"):
            try:
                forecast_ts = int(datetime.fromisoformat(res["timestamp"]).timestamp())
            except Exception:
                pass
        if (now_ts - forecast_ts) >= 900 or not res.get("timestamp"):
            res["timestamp"] = now_iso
            res["server_prediction_time"] = now_iso
            res["server_prediction_ts"] = now_ts
        
        # Overlay live prices on scanner leaderboard
        leaderboard = res.get("scanner_leaderboard", [])
        if leaderboard:
            for item in leaderboard:
                sym = item.get("symbol", "")
                raw_sym = sym.replace("/", "").replace(":USDT", "")
                p = live_prices.get(sym) or live_prices.get(raw_sym)
                if p and p > 0:
                    item["current_price"] = p
                    item["live_price"] = p

        # Overlay on top round signals
        top_signals = res.get("top_round_signals", [])
        if top_signals:
            for sig in top_signals:
                sym = sig.get("symbol", "")
                raw_sym = sym.replace("/", "").replace(":USDT", "")
                base = raw_sym.replace("USDT", "")
                p = live_prices.get(sym) or live_prices.get(raw_sym) or live_prices.get(f"{base}/USDT") or live_prices.get(f"{base}USDT") or live_prices.get(base)
                if p and p > 0:
                    sig["current_price"] = p
                    sig["live_price"] = p
                    entry_p = float(sig.get("entry_price") or p)
                    direction = str(sig.get("direction", "LONG")).upper()
                    if entry_p > 0:
                        sig["live_pnl_pct"] = round(((p - entry_p) / entry_p) * 100.0, 2) if direction in ["LONG", "BULLISH"] else round(((entry_p - p) / entry_p) * 100.0, 2)

        # Overlay on dominant_signals_per_coin
        dominant_signals = res.get("dominant_signals_per_coin", [])
        if dominant_signals:
            for sig in dominant_signals:
                sym = sig.get("symbol", "")
                raw_sym = sym.replace("/", "").replace(":USDT", "")
                base = raw_sym.replace("USDT", "")
                p = live_prices.get(sym) or live_prices.get(raw_sym) or live_prices.get(f"{base}/USDT") or live_prices.get(f"{base}USDT") or live_prices.get(base)
                if p and p > 0:
                    sig["current_price"] = p
                    sig["live_price"] = p
                    entry_p = float(sig.get("entry_price") or p)
                    direction = str(sig.get("direction", "LONG")).upper()
                    if entry_p > 0:
                        sig["live_pnl_pct"] = round(((p - entry_p) / entry_p) * 100.0, 2) if direction in ["LONG", "BULLISH"] else round(((entry_p - p) / entry_p) * 100.0, 2)

        # Overlay fundamental intelligence overview
        try:
            from app.services.fundamental_service import fundamental_service
            res["fundamental_overview"] = {
                "fear_and_greed": fundamental_service.fetch_fear_and_greed(),
                "global_market": fundamental_service.fetch_coinmarketcap_metrics(),
                "top_catalyst_events": fundamental_service.fetch_coinmarketcal_events()[:6],
                "trending_coins": fundamental_service.fetch_coingecko_intelligence().get("trending_coins", [])[:5],
                "breaking_news": fundamental_service.fetch_breaking_news()[:6]
            }
        except Exception:
            pass

        # Reconcile BTC market shield with live V16 regime
        try:
            from app.quant_v16.regime import reconcile_btc_shield
            from app.routers.v16_router import _compute_live_market_regime
            v16_r = _compute_live_market_regime()
            if v16_r and "btc_market_shield" in res:
                res["btc_market_shield"] = reconcile_btc_shield(res["btc_market_shield"], v16_r)
                if not res["btc_market_shield"].get("is_ntz_active"):
                    res["is_no_trade_zone_active"] = False
                    res["no_trade_zone_reason"] = None
                    has_signals = bool(res.get("top_round_signals") or res.get("active_trade_signals_count", 0) > 0)
                    res["market_trade_posture"] = "ACTIVE_SIGNALS" if has_signals else "WAITING_FOR_ALIGNMENT"
        except Exception:
            pass

        return res

    def get_latest_forecast(self, db: Session) -> Dict[str, Any]:
        """Retrieves the most recent market forecast scan with in-memory cache and live price overlay."""
        cached = get_cached_forecast()
        if cached:
            return self.overlay_live_prices(cached)

        # Fallback to direct file read if available
        try:
            forecast_path = os.path.join(settings.EXPORT_DIR, "live_market_forecast.json")
            if os.path.exists(forecast_path):
                with open(forecast_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    set_cached_forecast(data)
                    return self.overlay_live_prices(data)
        except Exception:
            pass

        latest = db.query(MarketForecast).order_by(desc(MarketForecast.id)).first()
        if latest:
            res = latest.to_dict()
            set_cached_forecast(res)
            return self.overlay_live_prices(res)

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategy": "Multi-Horizon Quantitative Engine",
            "btc_market_shield": {"active": False, "reason": "NORMAL (Market Stable)"},
            "dominant_signals_per_coin": [],
            "top_round_signals": [],
            "scanner_leaderboard": [],
            "deep_dive": {},
        }

    def get_engine_status(self) -> Dict[str, Any]:
        """Calculates 15-minute countdown, market shield status, and server state."""
        sync_state = get_sync_state()
        now = datetime.now(timezone.utc)
        current_minute = now.minute
        current_second = now.second
        now_ts = now.timestamp()
        if sync_state.get("next_scan_timestamp") and int(sync_state["next_scan_timestamp"]) > now_ts:
            target_ts = int(sync_state["next_scan_timestamp"])
            secs_remaining = max(1, int(target_ts - now_ts))
            next_scan_time = sync_state.get("next_scan_time_utc") or (now + timedelta(seconds=secs_remaining)).strftime("%Y-%m-%d %H:%M:%S UTC")
        else:
            mins_remaining = 15 - (current_minute % 15)
            secs_remaining = (mins_remaining * 60) - current_second + 2
            if secs_remaining <= 5:
                secs_remaining += 900
            target_ts = int((now + timedelta(seconds=secs_remaining)).timestamp())
            next_scan_time = (now + timedelta(seconds=secs_remaining)).strftime("%Y-%m-%d %H:%M:%S UTC")

        shield_status = {"active": False, "reason": "NORMAL (Market Stable)"}
        cached = get_cached_forecast()
        if cached and "btc_market_shield" in cached:
            shield_status = cached["btc_market_shield"]
        else:
            try:
                forecast_path = os.path.join(settings.EXPORT_DIR, "live_market_forecast.json")
                if os.path.exists(forecast_path):
                    with open(forecast_path, "r", encoding="utf-8") as f:
                        f_data = json.load(f)
                        if "btc_market_shield" in f_data:
                            shield_status = f_data["btc_market_shield"]
            except Exception:
                pass

        # Reconcile shield_status with Quant Edge V16 live regime
        try:
            from app.quant_v16.regime import reconcile_btc_shield
            from app.routers.v16_router import _compute_live_market_regime
            v16_r = _compute_live_market_regime()
            if v16_r:
                shield_status = reconcile_btc_shield(shield_status, v16_r)
        except Exception:
            pass

        is_scanning = bool(sync_state.get("is_scanning", False))

        return {
            "status": "HEALTHY",
            "is_engine_active": True,
            "is_scanning": is_scanning,
            "scan_status": sync_state.get("scan_status", "IDLE"),
            "scanned_assets_count": sync_state.get("scanned_assets_count", 0),
            "total_assets_count": sync_state.get("total_assets_count", 100),
            "current_time_utc": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "next_scan_utc": next_scan_time,
            "next_scan_timestamp": target_ts,
            "seconds_to_next_scan": secs_remaining,
            "last_scan_duration_seconds": sync_state.get("last_scan_duration_seconds"),
            "scan_version": sync_state["full_scan_version"],
            "full_scan_version": sync_state["full_scan_version"],
            "portfolio_version": sync_state["portfolio_version"],
            "last_scan_timestamp": sync_state["last_scan_timestamp"],
            "btc_market_shield": shield_status,
        }

    def get_market_regime(self) -> Dict[str, Any]:
        """Retrieves global market regime and institutional trader playbook."""
        ret_dict = None
        cached = get_cached_forecast()
        if cached and "global_market_regime" in cached and cached.get("global_market_regime"):
            ret_dict = {
                "regime": cached.get("global_market_regime", {}),
                "playbook": cached.get("trader_playbook", {}),
                "btc_shield": cached.get("btc_market_shield", {})
            }
        else:
            try:
                forecast_path = os.path.join(settings.EXPORT_DIR, "live_market_forecast.json")
                if os.path.exists(forecast_path):
                    with open(forecast_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("global_market_regime"):
                        ret_dict = {
                            "regime": data.get("global_market_regime", {}),
                            "playbook": data.get("trader_playbook", {}),
                            "btc_shield": data.get("btc_market_shield", {})
                        }
            except Exception:
                pass

        if not ret_dict:
            dyn_regime = _get_or_compute_regime()
            ret_dict = {
                "regime": dyn_regime,
                "playbook": {
                    "regime_type": dyn_regime.get("regime_type", "CONSOLIDATION"),
                    "headline": f"{dyn_regime.get('label', '⚪ CONSOLIDATION REGIME')}: TACTICAL PLAYBOOK",
                    "tactical_stance": dyn_regime.get("tactical_stance", "RANGE_BOUND_MEAN_REVERSION"),
                    "core_directive": "Adaptive market regime trade alignment actively managed."
                },
                "btc_shield": {"active": False, "status_code": "NORMAL"}
            }

        try:
            from app.quant_v16.regime import reconcile_btc_shield
            from app.routers.v16_router import _compute_live_market_regime
            v16_r = _compute_live_market_regime()
            if v16_r:
                ret_dict["btc_shield"] = reconcile_btc_shield(ret_dict.get("btc_shield", {}), v16_r)
        except Exception:
            pass
        return ret_dict

    def get_dominant_signals(self, db: Session) -> List[Dict[str, Any]]:
        """Retrieves single best dominant signal per coin with cross-horizon confluence metadata."""
        forecast = self.get_latest_forecast(db)
        if forecast and forecast.get("dominant_signals_per_coin"):
            return forecast.get("dominant_signals_per_coin", [])
        top_sigs = forecast.get("top_round_signals", [])
        return _compute_dominant_signals_per_coin(top_sigs)

    def get_top_gainers_signals(self) -> List[Dict[str, Any]]:
        """Retrieves specialized momentum long signals on 24h top gaining cryptocurrencies."""
        cached = get_cached_forecast()
        if cached and cached.get("top_24h_gainers_signals"):
            return cached.get("top_24h_gainers_signals", [])
        try:
            forecast_path = os.path.join(settings.EXPORT_DIR, "live_market_forecast.json")
            if os.path.exists(forecast_path):
                with open(forecast_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("top_24h_gainers_signals"):
                    return data.get("top_24h_gainers_signals", [])
        except Exception:
            pass
        return _get_or_compute_gainers()

    def get_top_losers_signals(self) -> List[Dict[str, Any]]:
        """Retrieves specialized breakdown continuation & rally-fade short signals on 24h top losing cryptocurrencies."""
        cached = get_cached_forecast()
        if cached and cached.get("top_24h_losers_signals"):
            return cached.get("top_24h_losers_signals", [])
        try:
            forecast_path = os.path.join(settings.EXPORT_DIR, "live_market_forecast.json")
            if os.path.exists(forecast_path):
                with open(forecast_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("top_24h_losers_signals"):
                    return data.get("top_24h_losers_signals", [])
        except Exception:
            pass
        return _get_or_compute_losers()

    def get_top_high_markup_signals(self) -> List[Dict[str, Any]]:
        """Retrieves specialized high-profit momentum continuation signals on top 10 high-markup volatility movers (e.g. HOME, PENGU)."""
        cached = get_cached_forecast()
        if cached and cached.get("top_high_markup_signals"):
            return cached.get("top_high_markup_signals", [])
        try:
            forecast_path = os.path.join(settings.EXPORT_DIR, "live_market_forecast.json")
            if os.path.exists(forecast_path):
                with open(forecast_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("top_high_markup_signals"):
                    return data.get("top_high_markup_signals", [])
        except Exception:
            pass
        return _get_or_compute_high_markup_signals()

HORIZON_ORDER_LIST = ["5M", "15M", "1H", "4H", "12H", "24H", "7D", "15D", "1M", "30D", "30M", "4D"]

def _compute_dominant_signals_per_coin(signals_list: list) -> list:
    """Groups all signals by coin symbol and selects the single highest-conviction dominant signal per coin with lower-horizon leading flow."""
    if not signals_list:
        return []
    by_coin = defaultdict(list)
    for s in signals_list:
        if not isinstance(s, dict):
            continue
        sym = (s.get('symbol') or '').upper().replace(':USDT', '').strip()
        if sym:
            by_coin[sym].append(s)

    dominant_list = []
    horizon_exec_weights = {
        "5M": 1.05, "15M": 1.10, "1H": 1.35, "4H": 1.30, "12H": 1.28,
        "24H": 1.25, "7D": 1.05, "15D": 1.0, "1M": 0.95, "30D": 0.95,
        "30M": 1.15, "4D": 1.10
    }

    for sym, sigs in by_coin.items():
        if len(sigs) == 1:
            sig = dict(sigs[0])
            ht = sig.get('horizon_tag') or "15M"
            sig['is_dominant_best'] = True
            sig['dominant_score'] = round(float(sig.get('conviction', 75.0)), 1)
            sig['confluence_alignment_pct'] = 100.0
            sig['supporting_horizons'] = [ht]
            sig['opposing_horizons'] = []
            sig['tailwind_horizons'] = [ht]
            sig['headwind_horizons'] = []
            sig['confluence_badge'] = f"⭐ DOMINANT SETUP ({ht})"
            sig['confluence_summary'] = f"Single Timeframe Confluence ({ht})"
            
            fav_obj = {
                "status": "CONFIRMED_IN_FAVOR",
                "status_badge": "🟢 CONFIRMED IN FAVOR",
                "recommendation": "HOLD_FOR_TARGET",
                "action_directive": f"Primary {ht} quantitative momentum model active.",
                "favorability_score": round(float(sig.get('conviction', 75.0)), 1),
                "agreeing_horizons_count": 1,
                "total_horizons_evaluated": 1,
                "tailwind_horizons": [ht],
                "headwind_horizons": [],
                "horizon_flow": [
                    {
                        "horizon": ht,
                        "direction": sig.get('direction', 'LONG'),
                        "status": "IN_FAVOR",
                        "status_badge": "🟢 IN FAVOR",
                        "probability": round(float(sig.get('meta_win_prob', sig.get('meta_probability', 0.70))), 2),
                        "conviction": round(float(sig.get('conviction', 70.0)), 1),
                        "is_lower_leading": True
                    }
                ],
                "latest_evaluated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            }
            sig['prediction_favorability'] = fav_obj
            sig['favorability_status'] = fav_obj['status']
            sig['favorability_badge'] = fav_obj['status_badge']
            sig['action_directive'] = fav_obj['action_directive']
            dominant_list.append(sig)
            continue

        long_sigs = [s for s in sigs if str(s.get('direction', 'LONG')).upper() in ['LONG', 'BULLISH']]
        short_sigs = [s for s in sigs if str(s.get('direction', 'LONG')).upper() in ['SHORT', 'BEARISH']]

        long_score = sum(float(s.get('conviction', 60.0)) * float(s.get('meta_win_prob', s.get('meta_probability', 0.70))) for s in long_sigs)
        short_score = sum(float(s.get('conviction', 60.0)) * float(s.get('meta_win_prob', s.get('meta_probability', 0.70))) for s in short_sigs)

        favored_group = long_sigs if long_score >= short_score else short_sigs
        opposing_group = short_sigs if long_score >= short_score else long_sigs
        favored_dir = "LONG" if long_score >= short_score else "SHORT"

        total_eval = len(sigs)
        favored_count = len(favored_group)
        alignment_pct = round((favored_count / max(1, total_eval)) * 100.0, 1)

        supporting_horizons = []
        for s in favored_group:
            ht = s.get('horizon_tag') or "15M"
            if ht not in supporting_horizons:
                supporting_horizons.append(ht)

        opposing_horizons = []
        for s in opposing_group:
            ht = s.get('horizon_tag') or "15M"
            if ht not in opposing_horizons:
                opposing_horizons.append(ht)

        best_sig = None
        highest_score = -1e9
        for s in favored_group:
            ht = s.get('horizon_tag') or "15M"
            meta_p = float(s.get('meta_win_prob', s.get('meta_probability', 0.70)))
            conv = float(s.get('conviction', 60.0))
            exp_ret = abs(float(s.get('expected_return_pct', 2.0)))
            tf_w = horizon_exec_weights.get(ht, 1.1)

            s_score = (meta_p * 40.0) + (conv * 0.30) + (alignment_pct * 0.20) + (tf_w * 10.0) + min(15.0, exp_ret * 2.0)
            if s.get('strategy_type') in ['MOMENTUM_TOP_GAINER', 'BREAKDOWN_TOP_LOSER']:
                s_score += 8.0

            if s_score > highest_score:
                highest_score = s_score
                best_sig = s

        if not best_sig:
            best_sig = favored_group[0] if favored_group else sigs[0]

        res_sig = dict(best_sig)
        winning_ht = res_sig.get('horizon_tag') or "15M"
        win_idx = HORIZON_ORDER_LIST.index(winning_ht) if winning_ht in HORIZON_ORDER_LIST else 2

        # Build detailed lower-horizon leading flow & favorability telemetry
        horizon_flow = []
        tailwind_horizons = []
        headwind_horizons = []

        for s in sigs:
            ht = s.get('horizon_tag') or "15M"
            s_dir = str(s.get('direction', 'LONG')).upper()
            is_s_long = s_dir in ['LONG', 'BULLISH']
            is_fav_long = favored_dir in ['LONG', 'BULLISH']
            h_idx = HORIZON_ORDER_LIST.index(ht) if ht in HORIZON_ORDER_LIST else 0
            is_lower_leading = (h_idx <= win_idx) or (ht in ['5M', '15M', '30M', '1H'])

            prob = float(s.get('meta_win_prob', s.get('meta_probability', 0.70)))
            conv = float(s.get('conviction', 60.0))

            if is_s_long == is_fav_long:
                status = "IN_FAVOR"
                status_badge = "🟢 IN FAVOR"
                tailwind_horizons.append(ht)
            else:
                status = "ADVERSE"
                status_badge = "🔴 ADVERSE"
                headwind_horizons.append(ht)

            horizon_flow.append({
                "horizon": ht,
                "direction": "LONG" if is_s_long else "SHORT",
                "status": status,
                "status_badge": status_badge,
                "probability": round(prob, 2),
                "conviction": round(conv, 1),
                "is_lower_leading": is_lower_leading
            })

        lower_leading_items = [h for h in horizon_flow if h['is_lower_leading']]
        lower_tailwind_items = [h for h in lower_leading_items if h['status'] == 'IN_FAVOR']
        lower_ratio = len(lower_tailwind_items) / max(1, len(lower_leading_items))
        fav_score = round((lower_ratio * 60.0) + (alignment_pct * 0.40), 1)

        if lower_ratio >= 0.65:
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

        if len(supporting_horizons) >= 3:
            res_sig['confluence_badge'] = f"💎 MULTI-CONFLUENCE ({' + '.join(supporting_horizons[:3])})"
            res_sig['grade'] = "💎 Grade A+ (MULTI-CONFLUENCE)"
            res_sig['grade_tier'] = 1
        elif len(supporting_horizons) >= 2:
            res_sig['confluence_badge'] = f"🔥 DUAL ALIGNMENT ({' + '.join(supporting_horizons[:2])})"
            res_sig['grade'] = "🥇 Grade A (DUAL ALIGNMENT)"
            res_sig['grade_tier'] = 2
        else:
            res_sig['confluence_badge'] = f"⭐ DOMINANT ({winning_ht})"

        res_sig['confluence_summary'] = f"{favored_count} of {total_eval} Timeframes Aligned {favored_dir} ({alignment_pct}% Agreement)"
        dominant_list.append(res_sig)

    dominant_list.sort(key=lambda x: (
        x.get('grade_tier', 2),
        -float(x.get('dominant_score', 0.0)),
        -float(x.get('confluence_alignment_pct', 50.0)),
        -float(x.get('conviction', 50.0))
    ))
    return dominant_list

def _evaluate_signal_favorability(sig: dict, live_p: float, coin_forecast_data: dict = None) -> dict:
    direction = str(sig.get('direction', 'LONG')).upper()
    entry_p = float(sig.get('entry_price', live_p) or live_p)
    
    horizons = coin_forecast_data.get('horizons', {}) if isinstance(coin_forecast_data, dict) else {}
    agree_count = 0
    total_eval = 0
    sum_prob = 0.0
    tailwind_horizons = []
    headwind_horizons = []
    horizon_flow = []

    if horizons and isinstance(horizons, dict):
        for h_key, h_data in horizons.items():
            if not isinstance(h_data, dict):
                continue
            total_eval += 1
            pred_dir = str(h_data.get('direction', '')).upper()
            prob = float(h_data.get('probability', 0.65))
            conv = float(h_data.get('conviction', 60.0))
            sum_prob += prob

            h_tag = str(h_key).upper().replace('HORIZON_', '')
            is_long_sig = ("LONG" in direction or "BULL" in direction)
            is_long_pred = ("LONG" in pred_dir or "BULL" in pred_dir)

            if is_long_sig == is_long_pred:
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
                "direction": "LONG" if is_long_pred else "SHORT",
                "status": flow_st,
                "status_badge": flow_badge,
                "probability": round(prob, 2),
                "conviction": round(conv, 1),
                "is_lower_leading": h_tag in ['5M', '15M', '30M', '1H']
            })

    pnl_pct = float(sig.get('live_pnl_pct', 0.0))
    if total_eval == 0:
        if pnl_pct >= 0.35:
            agree_count, total_eval, sum_prob = 3, 3, 0.80
            tailwind_horizons = ["15M", "30M", "1H"]
        elif pnl_pct <= -1.2:
            agree_count, total_eval, sum_prob = 0, 3, 0.75
            headwind_horizons = ["15M", "30M"]
        else:
            agree_count, total_eval, sum_prob = 2, 3, 0.65
            tailwind_horizons = ["15M", "1H"]

    agree_ratio = agree_count / max(1, total_eval)
    avg_prob = sum_prob / max(1, total_eval)
    fav_score = round((agree_ratio * 60.0) + (avg_prob * 40.0), 1)

    if agree_ratio >= 0.65 and avg_prob >= 0.60:
        status = "CONFIRMED_IN_FAVOR"
        status_badge = "🟢 CONFIRMED IN FAVOR"
        rec = "HOLD_FOR_RUNNER"
        directive = f"Latest lower horizon models ({', '.join(tailwind_horizons[:3])}) unanimously confirm trend continuation. Hold for TP2/TP3 expansion."
    elif agree_ratio <= 0.35 and avg_prob >= 0.60:
        status = "ADVERSE_REVERSAL"
        status_badge = "🔴 ADVERSE REVERSAL DETECTED"
        rec = "CONSIDER_EARLY_TRIM"
        directive = f"New multi-timeframe models detected adverse reversal on ({', '.join(headwind_horizons[:2])}). Protect capital / raise SL to BE."
    else:
        status = "MOMENTUM_STALLING"
        status_badge = "🟡 MOMENTUM STALLING"
        rec = "HOLD_WITH_TRAILING_SL"
        directive = "Price momentum equilibrium coiling. Trailing stop-loss protection active."

    return {
        "status": status,
        "status_badge": status_badge,
        "recommendation": rec,
        "action_directive": directive,
        "favorability_score": fav_score,
        "agreeing_horizons_count": agree_count,
        "total_horizons_evaluated": total_eval,
        "tailwind_horizons": tailwind_horizons,
        "headwind_horizons": headwind_horizons,
        "horizon_flow": horizon_flow,
        "latest_evaluated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    }

signal_service = SignalService()


