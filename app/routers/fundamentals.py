"""
FASTAPI ROUTER: Crypto Fundamental, Event Catalyst & News Intelligence
Endpoints:
- GET /api/fundamentals/macro: Real-time Fear & Greed Index + Global Liquidity & Dominance
- GET /api/fundamentals/events: CoinMarketCal Scheduled Event Catalysts & Sell-The-News Warnings
- GET /api/fundamentals/sectors: CoinGecko Hot Categories & Trending Search Assets
- GET /api/fundamentals/news: Breaking Crypto News Sentinel with NLP Sentiment Polarity
- GET /api/fundamentals/asset/{symbol}: Comprehensive Single-Asset Fundamental Matrix
"""

from fastapi import APIRouter, Response, Query
from app.services.fundamental_service import fundamental_service

router = APIRouter(prefix="/api/fundamentals", tags=["Fundamentals & News Intelligence"])

@router.get("/macro")
def get_macro_fundamentals(response: Response):
    """Retrieve live Crypto Fear & Greed Index, Global Market Cap, and Dominance metrics."""
    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=120"
    fg = fundamental_service.fetch_fear_and_greed()
    cmc = fundamental_service.fetch_coinmarketcap_metrics()
    tvl = fundamental_service.fetch_defillama_intelligence()
    return {
        "status": "success",
        "fear_and_greed": fg,
        "global_market": cmc,
        "onchain_tvl_overview": tvl
    }

@router.get("/events")
def get_catalyst_events(response: Response, force: bool = False):
    """Retrieve scheduled CoinMarketCal events, token burns, mainnets, and sell-the-news flags."""
    response.headers["Cache-Control"] = "public, max-age=120, stale-while-revalidate=300"
    events = fundamental_service.fetch_coinmarketcal_events(force=force)
    return {
        "status": "success",
        "total_events": len(events),
        "events": events
    }

@router.get("/sectors")
def get_sectors_and_trending(response: Response):
    """Retrieve leading CoinGecko categories/sectors and top trending search coins."""
    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=120"
    intel = fundamental_service.fetch_coingecko_intelligence()
    return {
        "status": "success",
        "data": intel
    }

@router.get("/news")
def get_breaking_news(response: Response, force: bool = False):
    """Retrieve breaking crypto news feed with sentiment polarity labels."""
    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=120"
    news = fundamental_service.fetch_breaking_news(force=force)
    return {
        "status": "success",
        "total_items": len(news),
        "news": news
    }

@router.get("/asset/{symbol:path}")
def get_asset_fundamental_matrix(symbol: str, response: Response):
    """Retrieve deep-dive fundamental matrix, event catalyst proximity, and conviction modifier for a specific pair."""
    response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=60"
    # Normalize symbol format (e.g., BTCUSDT -> BTC/USDT)
    clean_sym = symbol.strip().upper()
    if "/" not in clean_sym and clean_sym.endswith("USDT"):
        clean_sym = clean_sym[:-4] + "/USDT"
    
    matrix = fundamental_service.get_asset_fundamental_matrix(clean_sym)
    return {
        "status": "success",
        "symbol": clean_sym,
        "matrix": matrix
    }
