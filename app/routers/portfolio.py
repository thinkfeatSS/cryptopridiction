from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import json, os, traceback
from app.database import get_db
from app.services.signal_service import signal_service
from app.config import settings

router = APIRouter(prefix="/api/portfolio", tags=["Portfolio"])

def _safe_portfolio(db: Session) -> dict:
    """Returns portfolio data, falling back to ledger JSON on any DB error."""
    try:
        return signal_service.get_portfolio_data(db)
    except Exception as exc:
        # Log the full traceback for debugging
        tb = traceback.format_exc()
        print(f"[PORTFOLIO ERROR] DB path failed: {exc}\n{tb}")
        # Fallback: read directly from the ledger JSON file
        try:
            p_path = os.path.join(settings.EXPORT_DIR, "paper_trading_ledger.json")
            if os.path.exists(p_path):
                with open(p_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                start_bal = float(data.get("starting_balance_usd", 100.0))
                cur_bal   = float(data.get("current_balance_usd", start_bal))
                closed    = data.get("closed_trades_history", [])
                won  = sum(1 for c in closed if c.get("outcome") == "WON")
                lost = sum(1 for c in closed if c.get("outcome") == "LOST")
                be   = sum(1 for c in closed if c.get("outcome") == "BREAKEVEN")
                decisive = won + lost
                return {
                    "initial_capital_usd": start_bal,
                    "current_balance_usd": round(cur_bal, 2),
                    "open_positions": data.get("open_positions", []),
                    "closed_trades_history": closed,
                    "queued_trades": data.get("queued_trades", []),
                    "total_trades_count": len(closed),
                    "winning_trades_count": won,
                    "losing_trades_count": lost,
                    "breakeven_trades_count": be,
                    "win_rate_pct": round((won / max(1, decisive)) * 100.0, 2) if decisive > 0 else 0.0,
                    "total_net_profit_usd": round(float(data.get("realized_pnl_usd", 0.0)), 2),
                    "fee_tier_label": str(data.get("fee_tier_label", "Paper Trading")),
                    "_source": "ledger_json_fallback",
                }
        except Exception as fallback_exc:
            print(f"[PORTFOLIO ERROR] JSON fallback also failed: {fallback_exc}")
        raise HTTPException(status_code=500, detail=f"Portfolio unavailable: {exc}")

@router.get("")
def get_portfolio(db: Session = Depends(get_db)):
    """Retrieve paper trading portfolio ledger."""
    return _safe_portfolio(db)

@router.get("/open-positions")
def get_open_positions(db: Session = Depends(get_db)):
    """Retrieve active open paper positions."""
    return _safe_portfolio(db).get("open_positions", [])

@router.get("/closed-trades")
def get_closed_trades(db: Session = Depends(get_db)):
    """Retrieve completed paper trading history."""
    return _safe_portfolio(db).get("closed_trades_history", [])

@router.post("/reset")
def reset_portfolio(db: Session = Depends(get_db)):
    """Wipe all open positions, closed trades, and reset paper trading capital to $100.00."""
    try:
        return signal_service.reset_portfolio_data(db, target_start_balance=100.0)
    except Exception as exc:
        tb = traceback.format_exc()
        print(f"[PORTFOLIO RESET ERROR] {exc}\n{tb}")
        raise HTTPException(status_code=500, detail=f"Reset failed: {exc}")

