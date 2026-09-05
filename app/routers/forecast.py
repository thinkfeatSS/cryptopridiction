from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.signal_service import signal_service

router = APIRouter(prefix="/api/forecast", tags=["Forecast"])

@router.get("")
def get_live_forecast(db: Session = Depends(get_db)):
    """Retrieve the latest multi-horizon forecast from MySQL."""
    return signal_service.get_latest_forecast(db)

@router.get("/top-signals")
def get_top_signals(db: Session = Depends(get_db)):
    """Retrieve only the top round signals selected by the engine."""
    forecast = signal_service.get_latest_forecast(db)
    return forecast.get("top_round_signals", [])

@router.get("/leaderboard")
def get_leaderboard(db: Session = Depends(get_db)):
    """Retrieve multi-horizon opportunity leaderboard."""
    forecast = signal_service.get_latest_forecast(db)
    return forecast.get("scanner_leaderboard", [])

@router.get("/deep-dive")
def get_deep_dive(db: Session = Depends(get_db)):
    """Retrieve multi-scale deep dive confirmation metrics."""
    forecast = signal_service.get_latest_forecast(db)
    return forecast.get("deep_dive", {})
