import os
import json
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.signal_service import signal_service
from app.config import settings

from app.services.cache_service import cache_service

router = APIRouter(prefix="/api/forecast", tags=["Forecast"])

@router.get("")
def get_live_forecast(response: Response, db: Session = Depends(get_db)):
    """Retrieve the latest multi-horizon forecast with sub-millisecond response."""
    cached_content = cache_service.get_raw("api:live_forecast_raw")
    if cached_content:
        return Response(
            content=cached_content,
            media_type="application/json",
            headers={"Cache-Control": "public, max-age=3, stale-while-revalidate=5", "X-Cache": "HIT"}
        )

    forecast_path = os.path.join(settings.EXPORT_DIR, "live_market_forecast.json")
    if os.path.exists(forecast_path):
        try:
            with open(forecast_path, "r", encoding="utf-8") as f:
                f_data = json.load(f)
            # Reconcile BTC shield with live Quant Edge V16 regime
            try:
                from app.quant_v16.regime import reconcile_btc_shield
                from app.routers.v16_router import _compute_live_market_regime
                v16_r = _compute_live_market_regime()
                if v16_r and "btc_market_shield" in f_data:
                    f_data["btc_market_shield"] = reconcile_btc_shield(f_data["btc_market_shield"], v16_r)
                    if v16_r.get("regime") in ["BEAR_TREND", "BULL_TREND", "BREAKOUT"] and not f_data["btc_market_shield"].get("is_ntz_active"):
                        f_data["is_no_trade_zone_active"] = False
                        f_data["market_trade_posture"] = "ACTIVE_SIGNALS"
            except Exception:
                pass
            content = json.dumps(f_data)
            cache_service.set_raw("api:live_forecast_raw", content, ttl_seconds=3)
            return Response(
                content=content,
                media_type="application/json",
                headers={"Cache-Control": "public, max-age=3, stale-while-revalidate=5", "X-Cache": "MISS"}
            )
        except Exception:
            pass
    data = signal_service.get_latest_forecast(db)
    content = json.dumps(data)
    cache_service.set_raw("api:live_forecast_raw", content, ttl_seconds=3)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=3, stale-while-revalidate=5", "X-Cache": "DB"}
    )

@router.get("/top-signals")
def get_top_signals(response: Response, db: Session = Depends(get_db)):
    """Retrieve only the top round signals selected by the engine."""
    response.headers["Cache-Control"] = "public, max-age=3, stale-while-revalidate=5"
    forecast = signal_service.get_latest_forecast(db)
    return forecast.get("top_round_signals") or []

@router.get("/leaderboard")
def get_leaderboard(response: Response, db: Session = Depends(get_db)):
    """Retrieve multi-horizon opportunity leaderboard with micro-caching."""
    response.headers["Cache-Control"] = "public, max-age=3, stale-while-revalidate=5"
    forecast = signal_service.get_latest_forecast(db)
    return forecast.get("scanner_leaderboard") or []

@router.get("/signals-by-horizon")
def get_signals_by_horizon(db: Session = Depends(get_db)):
    """Retrieve actionable signals separated by timeframe horizons (15M, 1H, 4H, 24H, 7D, 30D)."""
    forecast = signal_service.get_latest_forecast(db)
    return forecast.get("signals_by_horizon") or {}

@router.get("/deep-dive")
def get_deep_dive(db: Session = Depends(get_db)):
    """Retrieve multi-scale deep dive confirmation metrics."""
    forecast = signal_service.get_latest_forecast(db)
    return forecast.get("deep_dive") or {}

@router.get("/live-prices")
def get_live_prices():
    """Retrieve instantaneous real-time spot prices for all pairs."""
    return signal_service.get_all_live_prices()
