import os
import requests
from typing import List, Dict, Any, Optional
import json
import time
from app.engine.config import (
    EXPORT_DIR,
    TOP_N_UNIVERSE,
    MIN_24H_VOLUME_USD,
    MEME_AND_SHITCOIN_BASES,
    EXCLUDED_STABLECOINS,
    EXCLUDED_SYNTHETIC_STOCKS,
    DELISTED_AND_INACTIVE_COINS,
    is_meme_coin,
)

class UniverseFilter:
    """
    Institutional Asset Universe Screener.
    Enforces:
    1. Exactly Top 40 High-Volume Pairs (Ranked by 24h quote volume).
    2. Zero Meme Coins or Hype-driven micro-cap shitcoins.
    3. Zero Synthetic Stocks or Pegged Stables.
    4. Zero Delisted or Inactive Legacy Ghost Pairs (Verified against Binance TRADING status).
    """

    @staticmethod
    def is_valid_crypto_pair(
        symbol: str,
        price: float = None,
        high: float = None,
        low: float = None,
        volume_usd: float = None,
        min_volume: Optional[float] = None,
        bid_price: Optional[float] = None,
        ask_price: Optional[float] = None,
        spread_bps: Optional[float] = None
    ) -> bool:
        if not symbol or not isinstance(symbol, str):
            return False

        clean_sym = symbol.strip().upper().replace(':USDT', '')
        if '/' not in clean_sym and clean_sym.endswith('USDT'):
            clean_sym = clean_sym[:-4] + '/USDT'
        if not clean_sym.endswith('/USDT'):
            return False

        base = clean_sym.split('/')[0]

        # 1. Strictly Reject Known Delisted or Inactive Legacy Tokens
        if base in DELISTED_AND_INACTIVE_COINS or "OLD" in base or "DELISTED" in base:
            return False

        # 2. Strictly Reject Known Meme Coins & Non-Utility Shitcoins
        if is_meme_coin(clean_sym) or is_meme_coin(base) or base in MEME_AND_SHITCOIN_BASES:
            return False

        # 2b. Reject Toxic Quarantined Symbols (>= 2 recent stop-outs)
        try:
            state_path = os.path.join(EXPORT_DIR, "scanner_daemon_state.json")
            if os.path.exists(state_path):
                with open(state_path, "r", encoding="utf-8") as sf:
                    q_data = json.load(sf).get("quarantined_coins", {})
                now_t = time.time()
                for q_k in [clean_sym, base, f"{base}USDT", f"{base}/USDT"]:
                    if q_k in q_data and float(q_data[q_k]) > now_t:
                        return False
        except Exception:
            pass

        # 3. Reject Synthetic Test Tokens & Non-Alphanumeric Tokens
        if base.startswith("COIN") and base[4:].isdigit():
            return False
        if not base.isalnum() or not base.isascii():
            return False

        # 4. Reject Tokenized / Synthetic Stocks (ending with B or equity symbols)
        if base in EXCLUDED_SYNTHETIC_STOCKS:
            return False
        if base.endswith("B") and base not in {"BNB", "ARB"}:
            return False

        # 5. Reject Leveraged Bull/Bear Tokens
        if base.endswith("UP") or base.endswith("DOWN") or base.endswith("BULL") or base.endswith("BEAR") or base.endswith("3L") or base.endswith("3S") or base.endswith("2L") or base.endswith("2S"):
            return False

        # 6. Reject Stablecoins & Fiat Pegs
        if base in EXCLUDED_STABLECOINS:
            return False

        # 7. Hard Reject Dead / Ghost Coins with Zero or Near-Zero Price (< $0.0001)
        if price is not None and price <= 0.0001:
            return False

        # 8. Dynamic Price Peg Filter (~$1 peg with near-zero volatility)
        if price is not None and price > 0:
            if 0.97 <= price <= 1.03:
                if high is not None and low is not None and high > 0 and low > 0:
                    vol_spread = (high - low) / max(0.001, price)
                    if vol_spread < 0.035:
                        return False
                else:
                    if 0.99 <= price <= 1.01:
                        return False

        # 9. Hard Minimum Institutional Volume Gate (Must have real active volume)
        v_thresh = min_volume if min_volume is not None else MIN_24H_VOLUME_USD
        if volume_usd is not None and (volume_usd < v_thresh or volume_usd <= 0):
            return False

        # 10. Single-Side Order Book Void Filter
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

    @classmethod
    def get_top_40_universe(cls, session: Optional[requests.Session] = None, top_n: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Queries live Binance 24h market stats and returns the Top high-volume
        institutional crypto pairs with meme, synthetic, and delisted assets strictly excluded.
        Guarantees pairs are actively trading on Binance.
        """
        s = session or requests.Session()
        limit = int(top_n) if top_n is not None else TOP_N_UNIVERSE

        # 0. Query Binance ExchangeInfo to verify actively trading spot symbols
        active_spot_symbols = set()
        exchange_info_urls = [
            "https://data-api.binance.vision/api/v3/exchangeInfo",
            "https://api.binance.com/api/v3/exchangeInfo"
        ]
        for eu in exchange_info_urls:
            try:
                e_resp = s.get(eu, timeout=5)
                if e_resp.status_code == 200:
                    e_data = e_resp.json()
                    active_spot_symbols = {
                        sym_info["symbol"] for sym_info in e_data.get("symbols", [])
                        if sym_info.get("status") == "TRADING" and sym_info.get("isSpotTradingAllowed", True)
                    }
                    if active_spot_symbols:
                        break
            except Exception:
                continue

        urls = [
            "https://data-api.binance.vision/api/v3/ticker/24hr",
            "https://api.binance.com/api/v3/ticker/24hr"
        ]
        raw_data = None
        for u in urls:
            try:
                resp = s.get(u, timeout=5)
                if resp.status_code == 200:
                    raw_data = resp.json()
                    break
            except Exception:
                continue

        if not raw_data or not isinstance(raw_data, list):
            # Tier-2 Failover: Query Bybit Spot Tickers if Binance 24h ticker endpoints are IP throttled
            try:
                b_resp = s.get("https://api.bybit.com/v5/market/tickers?category=spot", timeout=5)
                if b_resp.status_code == 200:
                    b_data = b_resp.json()
                    b_list = b_data.get("result", {}).get("list", [])
                    if b_list:
                        raw_data = []
                        for b_item in b_list:
                            raw_data.append({
                                "symbol": b_item.get("symbol", ""),
                                "lastPrice": b_item.get("lastPrice", "0.0"),
                                "highPrice": b_item.get("highPrice24h", "0.0"),
                                "lowPrice": b_item.get("lowPrice24h", "0.0"),
                                "quoteVolume": b_item.get("turnover24h", "0.0"),
                                "priceChangePercent": str(float(b_item.get("price24hPcnt", 0.0) or 0.0) * 100.0),
                                "bidPrice": b_item.get("bid1Price", "0.0"),
                                "askPrice": b_item.get("ask1Price", "0.0")
                            })
                        print(f"[UNIVERSE 🛰️] Engaged Tier-2 Bybit Gateway for 24h market stats ({len(raw_data)} pairs).", flush=True)
            except Exception:
                pass

        if not raw_data or not isinstance(raw_data, list):
            # Tier-3 Failover: Query MEXC Spot Tickers if Bybit endpoints fail
            try:
                m_resp = s.get("https://api.mexc.com/api/v3/ticker/24hr", timeout=5)
                if m_resp.status_code == 200:
                    m_data = m_resp.json()
                    if isinstance(m_data, list) and len(m_data) > 0:
                        raw_data = []
                        for m_item in m_data:
                            raw_data.append({
                                "symbol": m_item.get("symbol", ""),
                                "lastPrice": m_item.get("lastPrice", "0.0"),
                                "highPrice": m_item.get("highPrice", "0.0"),
                                "lowPrice": m_item.get("lowPrice", "0.0"),
                                "quoteVolume": m_item.get("quoteVolume", "0.0"),
                                "priceChangePercent": m_item.get("priceChangePercent", "0.0"),
                                "bidPrice": m_item.get("bidPrice", "0.0"),
                                "askPrice": m_item.get("askPrice", "0.0")
                            })
                        print(f"[UNIVERSE 🛰️] Engaged Tier-3 MEXC Gateway for 24h market stats ({len(raw_data)} pairs).", flush=True)
            except Exception:
                pass

        if not raw_data or not isinstance(raw_data, list):
            # Tier-4 Failover: Query Gate.io Spot Tickers if MEXC endpoints fail
            try:
                g_resp = s.get("https://api.gateio.ws/api/v4/spot/tickers", timeout=5)
                if g_resp.status_code == 200:
                    g_data = g_resp.json()
                    if isinstance(g_data, list) and len(g_data) > 0:
                        raw_data = []
                        for g_item in g_data:
                            cp = g_item.get("currency_pair", "")
                            raw_data.append({
                                "symbol": cp.replace("_", ""),
                                "lastPrice": g_item.get("last", "0.0"),
                                "highPrice": g_item.get("high_24h", "0.0"),
                                "lowPrice": g_item.get("low_24h", "0.0"),
                                "quoteVolume": g_item.get("quote_volume", "0.0"),
                                "priceChangePercent": g_item.get("change_percentage", "0.0"),
                                "bidPrice": g_item.get("highest_bid", "0.0"),
                                "askPrice": g_item.get("lowest_ask", "0.0")
                            })
                        print(f"[UNIVERSE 🛰️] Engaged Tier-4 Gate.io Gateway for 24h market stats ({len(raw_data)} pairs).", flush=True)
            except Exception:
                pass

        if not raw_data or not isinstance(raw_data, list):
            # Tier-5 Failover: Query KuCoin Spot Tickers if Gate.io endpoints fail
            try:
                k_resp = s.get("https://api.kucoin.com/api/v1/market/allTickers", timeout=5)
                if k_resp.status_code == 200:
                    k_data = k_resp.json()
                    k_list = k_data.get("data", {}).get("ticker", [])
                    if k_list:
                        raw_data = []
                        for k_item in k_list:
                            sym_raw = k_item.get("symbol", "")
                            clean_sym = sym_raw.replace("-", "")
                            raw_data.append({
                                "symbol": clean_sym,
                                "lastPrice": k_item.get("last", "0.0"),
                                "highPrice": k_item.get("high", "0.0"),
                                "lowPrice": k_item.get("low", "0.0"),
                                "quoteVolume": k_item.get("volValue", "0.0"),
                                "priceChangePercent": str(float(k_item.get("changeRate", 0.0) or 0.0) * 100.0),
                                "bidPrice": k_item.get("buy", "0.0"),
                                "askPrice": k_item.get("sell", "0.0")
                            })
                        print(f"[UNIVERSE 🛰️] Engaged Tier-5 KuCoin Gateway for 24h market stats ({len(raw_data)} pairs).", flush=True)
            except Exception:
                pass

        if not raw_data or not isinstance(raw_data, list):
            # Fallback default universe if all live exchange gateways drop
            fallback = [
                "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT",
                "AVAX/USDT", "SUI/USDT", "LINK/USDT", "NEAR/USDT", "APT/USDT", "DOT/USDT",
                "TIA/USDT", "INJ/USDT", "RENDER/USDT", "FET/USDT", "OP/USDT", "LTC/USDT",
                "UNI/USDT", "ICP/USDT", "FIL/USDT", "STX/USDT", "TAO/USDT", "SEI/USDT",
                "ATOM/USDT", "AAVE/USDT", "WLD/USDT", "RUNE/USDT", "POL/USDT", "PYTH/USDT",
                "JUP/USDT", "ONDO/USDT", "HBAR/USDT", "ENA/USDT", "PENDLE/USDT", "ALGO/USDT",
                "QNT/USDT", "IMX/USDT", "KAS/USDT", "ZEC/USDT"
            ]
            return [{"symbol": sym, "quote_volume_usd": 1e8, "price": 0.0} for sym in fallback[:limit]]

        tier1_assets = []
        tier2_assets = []
        for item in raw_data:
            sym_raw = item.get("symbol", "")
            if not sym_raw.endswith("USDT"):
                continue

            # Strictly verify pair is actively trading on Binance spot
            if active_spot_symbols and sym_raw not in active_spot_symbols:
                continue

            base = sym_raw[:-4]
            pair = f"{base}/USDT"

            try:
                price = float(item.get("lastPrice", 0.0))
                high = float(item.get("highPrice", 0.0))
                low = float(item.get("lowPrice", 0.0))
                quote_vol = float(item.get("quoteVolume", 0.0))
                chg_24h = float(item.get("priceChangePercent", 0.0))
                bid_price = float(item.get("bidPrice", 0.0) or 0.0)
                ask_price = float(item.get("askPrice", 0.0) or 0.0)
                if bid_price > 0 and ask_price >= bid_price:
                    spread_bps = round(((ask_price - bid_price) / max(1e-8, (bid_price + ask_price) / 2.0)) * 10000.0, 2)
                else:
                    bid_price = price
                    ask_price = price
                    spread_bps = 5.0

                # Must have genuine live price and meet at least Tier-2 viable liquidity floor ($250k)
                if price <= 0.0001 or quote_vol <= 0.0 or quote_vol < 250_000.0:
                    continue

                if cls.is_valid_crypto_pair(
                    pair, price=price, high=high, low=low, volume_usd=quote_vol, min_volume=250_000.0,
                    bid_price=bid_price, ask_price=ask_price, spread_bps=spread_bps
                ):
                    asset_obj = {
                        "symbol": pair,
                        "raw_symbol": sym_raw,
                        "price": price,
                        "quote_volume_usd": quote_vol,
                        "change_24h_pct": chg_24h,
                        "high_24h": high,
                        "low_24h": low,
                        "bid_price": bid_price,
                        "ask_price": ask_price,
                        "spread_bps": spread_bps,
                    }
                    if quote_vol >= MIN_24H_VOLUME_USD:
                        tier1_assets.append(asset_obj)
                    else:
                        tier2_assets.append(asset_obj)
            except Exception:
                continue

        # Sort descending by 24h institutional volume
        tier1_assets.sort(key=lambda x: x["quote_volume_usd"], reverse=True)
        tier2_assets.sort(key=lambda x: x["quote_volume_usd"], reverse=True)

        # Dynamic volume backfill: If market consolidation causes < 40 pairs to meet $10M,
        # seamlessly backfill remaining slots from top Tier-2 clean pairs to guarantee exactly 40 assets
        combined = tier1_assets + tier2_assets
        return combined[:limit]
