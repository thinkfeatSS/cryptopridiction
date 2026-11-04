from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import json, os, traceback
from app.database import get_db
from app.services.signal_service import signal_service
from app.config import settings
from app.engine.scanner.filters import UniverseFilter

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
                raw_closed = data.get("closed_trades_history") or data.get("closed_trades") or []
                
                closed = []
                for ct in raw_closed:
                    rpnl = ct.get("realized_pnl_usd") if ct.get("realized_pnl_usd") is not None else ct.get("net_pnl_usd", 0.0)
                    rpct = ct.get("realized_pnl_pct") if ct.get("realized_pnl_pct") is not None else ct.get("return_pct", 0.0)
                    fee = ct.get("binance_fee_usd") if ct.get("binance_fee_usd") is not None else ct.get("fees_usd", 0.0)
                    outc = ct.get("outcome")
                    if not outc:
                        outc = "WON" if rpnl > 0.05 else ("LOST" if rpnl < -0.05 else "BREAKEVEN")
                    hz = ct.get("horizon") or ct.get("signal_horizon") or ("15M" if ct.get("desk") == "scalp" else "1H")
                    closed.append({
                        "trade_id": ct.get("trade_id"),
                        "symbol": ct.get("symbol"),
                        "horizon": hz,
                        "direction": ct.get("direction"),
                        "execution_engine": ct.get("execution_engine", "binance_futures"),
                        "entry_price": float(ct.get("entry_price", 0.0)),
                        "exit_price": float(ct.get("exit_price", 0.0)),
                        "exit_reason": ct.get("exit_reason", ""),
                        "outcome": outc,
                        "gross_pnl_usd": float(ct.get("gross_pnl_usd", 0.0)),
                        "binance_fee_usd": float(fee),
                        "realized_pnl_usd": round(float(rpnl), 2),
                        "realized_pnl_pct": round(float(rpct), 2),
                        "duration_str": ct.get("duration_str", "N/A"),
                        "opened_at": ct.get("opened_at") or ct.get("opened_at_utc", ""),
                        "closed_at": ct.get("closed_at") or ct.get("closed_at_utc", ""),
                    })

                won  = sum(1 for c in closed if c.get("outcome") == "WON")
                lost = sum(1 for c in closed if c.get("outcome") == "LOST")
                be   = sum(1 for c in closed if c.get("outcome") == "BREAKEVEN")
                tot_closed = len(closed)
                decisive = won + lost
                total_closed_wr = round((won / max(1, tot_closed)) * 100.0, 2) if tot_closed > 0 else 0.0
                decisive_wr = round((won / max(1, decisive)) * 100.0, 2) if decisive > 0 else 0.0
                raw_positions = data.get("open_positions", [])
                clean_positions = [
                    p for p in raw_positions
                    if UniverseFilter.is_valid_crypto_pair(p.get("symbol", ""), price=p.get("entry_price"))
                ]
                scalp_c = len([p for p in clean_positions if (p.get("desk") or "").lower() == "scalp" or "15M" in str(p.get("horizon", "")).upper()])
                day_c = len([p for p in clean_positions if (p.get("desk") or "").lower() in ["day", "intraday"] or "1H" in str(p.get("horizon", "")).upper()])
                swing_c = len([p for p in clean_positions if (p.get("desk") or "").lower() in ["swing", "macro"] or "24H" in str(p.get("horizon", "")).upper()])
                
                scalp_rpnl = round(sum(float(c.get("realized_pnl_usd", 0.0)) for c in closed if (c.get("desk") or "").lower() == "scalp" or "15M" in str(c.get("horizon", "")).upper()), 2)
                day_rpnl = round(sum(float(c.get("realized_pnl_usd", 0.0)) for c in closed if (c.get("desk") or "").lower() in ["day", "intraday"] or "1H" in str(c.get("horizon", "")).upper()), 2)
                swing_rpnl = round(sum(float(c.get("realized_pnl_usd", 0.0)) for c in closed if (c.get("desk") or "").lower() in ["swing", "macro"] or "24H" in str(c.get("horizon", "")).upper()), 2)

                scalp_d = {"name": "⚡ Scalp Desk", "allocated_usd": 150.0, "max_slots": 1, "active_slots": scalp_c, "open_positions": scalp_c, "leverage": 2, "realized_pnl_usd": scalp_rpnl, "total_pnl_usd": scalp_rpnl}
                day_d = {"name": "⏳ Day Trading Desk", "allocated_usd": 350.0, "max_slots": 2, "active_slots": day_c, "open_positions": day_c, "leverage": 3, "realized_pnl_usd": day_rpnl, "total_pnl_usd": day_rpnl}
                swing_d = {"name": "🌊 Swing Desk", "allocated_usd": 500.0, "max_slots": 3, "active_slots": swing_c, "open_positions": swing_c, "leverage": 2, "realized_pnl_usd": swing_rpnl, "total_pnl_usd": swing_rpnl}
                desks_enriched = {
                    "scalp": scalp_d,
                    "day": day_d,
                    "intraday": day_d,
                    "swing": swing_d,
                    "macro": swing_d
                }
                return {
                    "initial_capital_usd": start_bal,
                    "current_balance_usd": round(cur_bal, 2),
                    "open_positions": clean_positions,
                    "closed_trades_history": closed,
                    "queued_trades": data.get("queued_trades", []),
                    "total_trades_count": len(closed),
                    "winning_trades_count": won,
                    "losing_trades_count": lost,
                    "breakeven_trades_count": be,
                    "win_rate_pct": total_closed_wr,
                    "total_closed_win_rate_pct": total_closed_wr,
                    "decisive_win_rate_pct": decisive_wr,
                    "total_net_profit_usd": round(sum(c["realized_pnl_usd"] for c in closed), 2),
                    "profit_factor": float(data.get("profit_factor", 0.0)),
                    "sharpe_ratio": float(data.get("sharpe_ratio", 0.0)),
                    "sortino_ratio": float(data.get("sortino_ratio", 0.0)),
                    "expectancy_usd": float(data.get("expectancy_usd", 0.0)),
                    "desks": desks_enriched,
                    "fee_tier_label": str(data.get("fee_tier_label", "Binance Futures (VIP0 Isolated Margin | 0.045% Taker Fee with BNB Discount)")),
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

