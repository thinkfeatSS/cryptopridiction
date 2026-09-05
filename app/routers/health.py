from fastapi import APIRouter
from app.services.signal_service import signal_service

router = APIRouter(prefix="/api/status", tags=["Status"])

@router.get("")
def get_status():
    """Retrieve system health, server UTC time, and 15-minute countdown."""
    return signal_service.get_engine_status()
