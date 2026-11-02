from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.services.signal_service import signal_service
from app.config import settings
import os

from app.services.cache_service import cache_service

router = APIRouter(prefix="/api/signals", tags=["Signals"])

@router.get("")
def get_signals(
    symbol: Optional[str] = Query(None, description="Filter by exact crypto symbol (e.g. BTC/USDT)"),
    search: Optional[str] = Query(None, description="Search symbol or signal ID"),
    date: Optional[str] = Query(None, description="Filter by date UTC (YYYY-MM-DD)"),
    outcome: Optional[str] = Query(None, description="Filter by outcome: WON, LOST, PENDING, EXPIRED"),
    status: Optional[str] = Query(None, description="Filter by status: ACTIVE, WON, LOST, EXPIRED"),
    grade: Optional[str] = Query(None, description="Filter by grade: A+, A, B+"),
    horizon: Optional[str] = Query(None, description="Filter by horizon: SCALP, SWING, MACRO, 2-DAY, 3-DAY, WEEKLY, BIWEEKLY, MONTHLY"),
    direction: Optional[str] = Query(None, description="Filter by direction: LONG or SHORT"),
    min_return: Optional[float] = Query(None, description="Filter by minimum target/realized return % (e.g. 3.0)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Retrieve paginated, filterable signals from MySQL database."""
    return signal_service.get_signals_list(
        db=db,
        symbol=symbol,
        search=search,
        date=date,
        outcome=outcome,
        status=status,
        grade=grade,
        horizon=horizon,
        direction=direction,
        min_return=min_return,
        limit=limit,
        offset=offset,
    )

@router.get("/by-symbol/{symbol_name:path}")
def get_signals_by_symbol(symbol_name: str, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    """Retrieve all historical 15-minute signals generated for a specific cryptocurrency."""
    return signal_service.get_signals_by_symbol(db, symbol=symbol_name, limit=limit)

@router.get("/kpi")
def get_kpi_summary(db: Session = Depends(get_db)):
    """Retrieve executive KPI audit metrics (Win rate %, returns, counts) with Redis caching."""
    cached = cache_service.get_json("api:kpi_summary")
    if cached:
        return cached
    data = signal_service.get_kpi_summary(db)
    cache_service.set_json("api:kpi_summary", data, ttl_seconds=15)
    return data

@router.get("/daily-summary")
def get_daily_summary(db: Session = Depends(get_db)):
    """Retrieve daily-based signal performance with Redis caching."""
    cached = cache_service.get_json("api:daily_summary")
    if cached:
        return cached
    data = signal_service.get_daily_summary(db)
    cache_service.set_json("api:daily_summary", data, ttl_seconds=20)
    return data

@router.get("/regime")
def get_market_regime():
    """Retrieve the live global market regime with Redis caching."""
    cached = cache_service.get_json("api:market_regime")
    if cached:
        return cached
    data = signal_service.get_market_regime()
    cache_service.set_json("api:market_regime", data, ttl_seconds=20)
    return data

@router.get("/dominant")
def get_dominant_signals(db: Session = Depends(get_db)):
    """Retrieve single best dominant signal per coin with cross-horizon confluence metadata."""
    return signal_service.get_dominant_signals(db)

@router.get("/gainers")
def get_top_gainers_signals():
    """Retrieve specialized momentum continuation long signals on top 24-hour gaining cryptocurrencies."""
    return signal_service.get_top_gainers_signals()

@router.get("/losers")
def get_top_losers_signals():
    """Retrieve specialized breakdown continuation & rally-fade short signals on top 24-hour losing cryptocurrencies."""
    return signal_service.get_top_losers_signals()

@router.get("/markup")
def get_top_high_markup_signals():
    """Retrieve specialized high-profit momentum continuation signals on top 10 high-markup volatility movers (e.g. HOME, PENGU)."""
    return signal_service.get_top_high_markup_signals()

@router.get("/download-csv")
def download_csv():
    """Download the raw trader_signals_tracker.csv backup."""
    csv_path = os.path.join(settings.EXPORT_DIR, "trader_signals_tracker.csv")
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8") as f:
            content = f.read()
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=trader_signals_tracker.csv"},
        )
    return Response(content="signal_id,status\n", media_type="text/csv")

