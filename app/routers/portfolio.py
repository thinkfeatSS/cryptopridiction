from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.signal_service import signal_service

router = APIRouter(prefix="/api/portfolio", tags=["Portfolio"])

@router.get("")
def get_portfolio(db: Session = Depends(get_db)):
    """Retrieve paper trading portfolio ledger from MySQL."""
    return signal_service.get_portfolio_data(db)

@router.get("/open-positions")
def get_open_positions(db: Session = Depends(get_db)):
    """Retrieve active open paper positions."""
    data = signal_service.get_portfolio_data(db)
    return data.get("open_positions", [])

@router.get("/closed-trades")
def get_closed_trades(db: Session = Depends(get_db)):
    """Retrieve completed paper trading history."""
    data = signal_service.get_portfolio_data(db)
    return data.get("closed_trades_history", [])
