from sqlalchemy.orm import Session
from sqlalchemy import func, or_, desc
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from collections import defaultdict
import math
import os
import json
import numpy as np

from app.config import settings
from app.models import SignalAudit, PaperPosition, ClosedTrade, MarketForecast
from app.services.db_sync import sync_files_to_db_live, get_sync_state, get_cached_forecast, set_cached_forecast

class SignalService:
    def get_kpi_summary(self, db: Session) -> Dict[str, Any]:
        """Calculates executive KPI metrics in a single optimized pass."""
        sync_files_to_db_live()
        signals = db.query(
            SignalAudit.outcome_label,
            SignalAudit.status,
            SignalAudit.grade_tier,
            SignalAudit.realized_return_pct
        ).all()

        total_signals = len(signals)
        if total_signals == 0:
            return {
                "last_updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "total_trader_signals": 0,
                "won_signals_count": 0,
                "lost_signals_count": 0,
                "pending_signals_count": 0,
                "expired_signals_count": 0,
                "win_rate_pct": 0.0,
                "grade_a_plus_win_rate_pct": 0.0,
                "grade_a_win_rate_pct": 0.0,
                "average_return_pct": 0.0,
                "cumulative_return_pct": 0.0,
            }

        won = 0
        lost = 0
        pending = 0
        expired = 0
        a_plus_won = 0
        a_plus_lost = 0
        a_won = 0
        a_lost = 0
        returns = []

        for out_label, status, grade_tier, ret_pct in signals:
            out_upper = (out_label or "").upper()
            st_upper = (status or "").upper()

            is_won = "WON" in out_upper
            is_lost = "LOST" in out_upper
            is_pending = "PENDING" in out_upper or st_upper == "PENDING_EVALUATION"
            is_expired = "EXPIRED" in out_upper

            if is_won:
                won += 1
                if grade_tier == 1:
                    a_plus_won += 1
                elif grade_tier == 2:
                    a_won += 1
            elif is_lost:
                lost += 1
                if grade_tier == 1:
                    a_plus_lost += 1
                elif grade_tier == 2:
                    a_lost += 1
            elif is_pending:
                pending += 1
            elif is_expired:
                expired += 1

            if ret_pct is not None and not (math.isnan(ret_pct) or math.isinf(ret_pct)):
                returns.append(ret_pct)

        decisive = won + lost
        win_rate = round((won / max(1, decisive)) * 100.0, 2) if decisive > 0 else 0.0

        a_plus_decisive = a_plus_won + a_plus_lost
        a_plus_wr = round((a_plus_won / max(1, a_plus_decisive)) * 100.0, 2) if a_plus_decisive > 0 else 0.0

        a_decisive = a_won + a_lost
        a_wr = round((a_won / max(1, a_decisive)) * 100.0, 2) if a_decisive > 0 else 0.0

        avg_ret = round(float(np.mean(returns)), 2) if returns else 0.0
        total_ret = round(float(np.sum(returns)), 2) if returns else 0.0

        return {
            "last_updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "total_trader_signals": total_signals,
            "won_signals_count": won,
            "lost_signals_count": lost,
            "pending_signals_count": pending,
            "expired_signals_count": expired,
            "win_rate_pct": win_rate,
            "grade_a_plus_win_rate_pct": a_plus_wr,
            "grade_a_win_rate_pct": a_wr,
            "average_return_pct": avg_ret,
            "cumulative_return_pct": total_ret,
        }

    def get_signals_list(
        self,
        db: Session,
        symbol: Optional[str] = None,
        search: Optional[str] = None,
        date: Optional[str] = None,
        outcome: Optional[str] = None,
        grade: Optional[str] = None,
        horizon: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Queries signals with search, filters, date filtering, and pagination."""
        sync_files_to_db_live()
        query = db.query(SignalAudit)

        if symbol:
            sym_clean = symbol.strip().replace('-', '/').upper()
            query = query.filter(SignalAudit.symbol == sym_clean)

        if search:
            q = f"%{search.strip()}%"
            query = query.filter(or_(SignalAudit.symbol.ilike(q), SignalAudit.signal_id.ilike(q)))

        if date:
            query = query.filter(SignalAudit.date_utc == date.strip())

        if outcome:
            out_upper = outcome.upper().strip()
            if out_upper == "WON":
                query = query.filter(SignalAudit.outcome_label.like("%WON%"))
            elif out_upper == "LOST":
                query = query.filter(SignalAudit.outcome_label.like("%LOST%"))
            elif out_upper == "PENDING":
                query = query.filter(or_(SignalAudit.status == "PENDING_EVALUATION", SignalAudit.outcome_label.like("%PENDING%")))
            elif out_upper == "EXPIRED":
                query = query.filter(SignalAudit.outcome_label.like("%EXPIRED%"))

        if grade:
            g_upper = grade.upper().strip()
            if g_upper == "A+":
                query = query.filter(SignalAudit.grade_tier == 1)
            elif g_upper == "A":
                query = query.filter(SignalAudit.grade_tier == 2)
            elif g_upper == "B+":
                query = query.filter(SignalAudit.grade_tier == 3)

        if horizon:
            h_upper = horizon.upper().strip()
            query = query.filter(SignalAudit.horizon.ilike(f"%{h_upper}%"))

        total_count = query.count()
        signals = query.order_by(desc(SignalAudit.id)).offset(offset).limit(limit).all()

        return {
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "signals": [s.to_dict() for s in signals],
        }

    def get_signals_by_symbol(self, db: Session, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve all chronological 15-minute signals generated for a specific cryptocurrency."""
        sync_files_to_db_live()
        sym_clean = symbol.strip().replace('-', '/').upper()
        signals = db.query(SignalAudit).filter(
            or_(SignalAudit.symbol == sym_clean, SignalAudit.symbol.ilike(f"%{sym_clean}%"))
        ).order_by(desc(SignalAudit.id)).limit(limit).all()
        return [s.to_dict() for s in signals]

    def get_daily_summary(self, db: Session) -> List[Dict[str, Any]]:
        """Optimized single-query aggregation grouping signals by date."""
        sync_files_to_db_live()
        signals = db.query(SignalAudit).order_by(desc(SignalAudit.date_utc)).all()
        
        grouped = defaultdict(list)
        for s in signals:
            if s.date_utc:
                grouped[s.date_utc].append(s)

        daily_list = []
        for d_str, day_signals in grouped.items():
            total_day = len(day_signals)
            won = sum(1 for s in day_signals if "WON" in (s.outcome_label or ""))
            lost = sum(1 for s in day_signals if "LOST" in (s.outcome_label or ""))
            pending = sum(1 for s in day_signals if s.status == "PENDING_EVALUATION" or "PENDING" in (s.outcome_label or ""))
            expired = sum(1 for s in day_signals if "EXPIRED" in (s.outcome_label or ""))

            decisive = won + lost
            win_rate = round((won / max(1, decisive)) * 100.0, 2) if decisive > 0 else 0.0

            returns = [
                s.realized_return_pct
                for s in day_signals
                if s.realized_return_pct is not None and not (math.isnan(s.realized_return_pct) or math.isinf(s.realized_return_pct))
            ]
            cum_ret = round(float(np.sum(returns)), 2) if returns else 0.0
            avg_ret = round(float(np.mean(returns)), 2) if returns else 0.0

            daily_list.append({
                "date": d_str,
                "total_signals": total_day,
                "won_count": won,
                "lost_count": lost,
                "pending_count": pending,
                "expired_count": expired,
                "win_rate_pct": win_rate,
                "cumulative_return_pct": cum_ret,
                "average_return_pct": avg_ret,
            })

        return daily_list

    def get_portfolio_data(self, db: Session) -> Dict[str, Any]:
        """Retrieves active positions and closed trades history from DB."""
        sync_files_to_db_live()
        positions = db.query(PaperPosition).order_by(desc(PaperPosition.id)).all()
        closed_trades = db.query(ClosedTrade).order_by(desc(ClosedTrade.id)).all()

        total_trades = len(closed_trades)
        winning_trades = sum(1 for c in closed_trades if c.outcome == "WON")
        losing_trades = sum(1 for c in closed_trades if c.outcome == "LOST")
        net_profit = sum(c.realized_pnl_usd for c in closed_trades)
        win_rate = round((winning_trades / max(1, total_trades)) * 100.0, 2) if total_trades > 0 else 0.0

        current_balance = 10000.0 + net_profit

        return {
            "initial_capital_usd": 10000.0,
            "current_balance_usd": round(current_balance, 2),
            "open_positions": [p.to_dict() for p in positions],
            "closed_trades_history": [c.to_dict() for c in closed_trades],
            "total_trades_count": total_trades,
            "winning_trades_count": winning_trades,
            "losing_trades_count": losing_trades,
            "win_rate_pct": win_rate,
            "total_net_profit_usd": round(net_profit, 2),
        }

    def get_latest_forecast(self, db: Session) -> Dict[str, Any]:
        """Retrieves the most recent market forecast scan with in-memory cache."""
        cached = get_cached_forecast()
        if cached:
            return cached

        sync_files_to_db_live()
        cached = get_cached_forecast()
        if cached:
            return cached

        latest = db.query(MarketForecast).order_by(desc(MarketForecast.id)).first()
        if latest:
            res = latest.to_dict()
            set_cached_forecast(res)
            return res
        
        # Fallback to direct file read if available
        try:
            forecast_path = os.path.join(settings.EXPORT_DIR, "live_market_forecast.json")
            if os.path.exists(forecast_path):
                with open(forecast_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    set_cached_forecast(data)
                    return data
        except Exception:
            pass

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategy": "Multi-Horizon Quantitative Engine",
            "btc_market_shield": {"active": False, "reason": "NORMAL (Market Stable)"},
            "top_round_signals": [],
            "scanner_leaderboard": [],
            "deep_dive": {},
        }

    def get_engine_status(self) -> Dict[str, Any]:
        """Calculates 15-minute countdown, market shield status, and server state."""
        sync_files_to_db_live()
        sync_state = get_sync_state()

        now = datetime.now(timezone.utc)
        current_minute = now.minute
        current_second = now.second
        
        mins_remaining = 15 - (current_minute % 15)
        secs_remaining = (mins_remaining * 60) - current_second
        if secs_remaining <= 0:
            secs_remaining = 15 * 60

        next_scan_time = (now + timedelta(seconds=secs_remaining)).strftime("%H:%M:%S UTC")

        shield_status = {"active": False, "reason": "NORMAL (Market Stable)"}
        cached = get_cached_forecast()
        if cached and "btc_market_shield" in cached:
            shield_status = cached["btc_market_shield"]
        else:
            try:
                forecast_path = os.path.join(settings.EXPORT_DIR, "live_market_forecast.json")
                if os.path.exists(forecast_path):
                    with open(forecast_path, "r", encoding="utf-8") as f:
                        f_data = json.load(f)
                        if "btc_market_shield" in f_data:
                            shield_status = f_data["btc_market_shield"]
            except Exception:
                pass

        is_scanning = bool(sync_state.get("is_scanning", False))

        return {
            "status": "HEALTHY",
            "is_engine_active": True,
            "is_scanning": is_scanning,
            "scan_status": sync_state.get("scan_status", "IDLE"),
            "current_time_utc": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "next_scan_utc": next_scan_time,
            "seconds_to_next_scan": secs_remaining,
            "scan_version": sync_state["full_scan_version"],
            "full_scan_version": sync_state["full_scan_version"],
            "portfolio_version": sync_state["portfolio_version"],
            "last_scan_timestamp": sync_state["last_scan_timestamp"],
            "btc_market_shield": shield_status,
        }

signal_service = SignalService()
