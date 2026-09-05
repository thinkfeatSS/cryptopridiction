from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.services.signal_service import signal_service
from app.config import settings
import os

router = APIRouter(prefix="/api/signals", tags=["Signals"])

@router.get("")
def get_signals(
    search: Optional[str] = Query(None, description="Search symbol or signal ID"),
    date: Optional[str] = Query(None, description="Filter by date UTC (YYYY-MM-DD)"),
    outcome: Optional[str] = Query(None, description="Filter by outcome: WON, LOST, PENDING, EXPIRED"),
    grade: Optional[str] = Query(None, description="Filter by grade: A+, A, B+"),
    horizon: Optional[str] = Query(None, description="Filter by horizon: SCALP, SWING, MACRO"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Retrieve paginated, filterable signals from MySQL database."""
    return signal_service.get_signals_list(
        db=db,
        search=search,
        date=date,
        outcome=outcome,
        grade=grade,
        horizon=horizon,
        limit=limit,
        offset=offset,
    )

@router.get("/kpi")
def get_kpi_summary(db: Session = Depends(get_db)):
    """Retrieve executive KPI audit metrics (Win rate %, returns, counts) from MySQL."""
    return signal_service.get_kpi_summary(db)

@router.get("/daily-summary")
def get_daily_summary(db: Session = Depends(get_db)):
    """Retrieve daily-based signal performance, win/loss breakdown, and returns."""
    return signal_service.get_daily_summary(db)

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
