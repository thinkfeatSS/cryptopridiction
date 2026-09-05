from sqlalchemy.orm import Session
from sqlalchemy import func, or_, desc
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
import math
import numpy as np

from app.models import SignalAudit, PaperPosition, ClosedTrade, MarketForecast

class SignalService:
    def get_kpi_summary(self, db: Session) -> Dict[str, Any]:
        """Calculates executive KPI metrics from MySQL database."""
        total_signals = db.query(SignalAudit).count()
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

        won = db.query(SignalAudit).filter(SignalAudit.outcome_label.like("%WON%")).count()
        lost = db.query(SignalAudit).filter(SignalAudit.outcome_label.like("%LOST%")).count()
        expired = db.query(SignalAudit).filter(SignalAudit.outcome_label.like("%EXPIRED%")).count()
        pending = db.query(SignalAudit).filter(
            or_(
                SignalAudit.status == "PENDING_EVALUATION",
                SignalAudit.outcome_label.like("%PENDING%")
            )
        ).count()
        
        decisive = won + lost
        win_rate = round((won / max(1, decisive)) * 100.0, 2) if decisive > 0 else 0.0

        # Grade A+ stats
        a_plus_won = db.query(SignalAudit).filter(
            SignalAudit.grade_tier == 1,
            SignalAudit.outcome_label.like("%WON%")
        ).count()
        a_plus_lost = db.query(SignalAudit).filter(
            SignalAudit.grade_tier == 1,
            SignalAudit.outcome_label.like("%LOST%")
        ).count()
        a_plus_decisive = a_plus_won + a_plus_lost
        a_plus_wr = round((a_plus_won / max(1, a_plus_decisive)) * 100.0, 2) if a_plus_decisive > 0 else 0.0

        # Grade A stats
        a_won = db.query(SignalAudit).filter(
            SignalAudit.grade_tier == 2,
            SignalAudit.outcome_label.like("%WON%")
        ).count()
        a_lost = db.query(SignalAudit).filter(
            SignalAudit.grade_tier == 2,
            SignalAudit.outcome_label.like("%LOST%")
        ).count()
        a_decisive = a_won + a_lost
        a_wr = round((a_won / max(1, a_decisive)) * 100.0, 2) if a_decisive > 0 else 0.0

        # Returns calculation
        resolved_returns = db.query(SignalAudit.realized_return_pct).filter(
            SignalAudit.realized_return_pct.isnot(None)
        ).all()

        returns = [r[0] for r in resolved_returns if r[0] is not None and not (math.isnan(r[0]) or math.isinf(r[0]))]
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
        search: Optional[str] = None,
        date: Optional[str] = None,
        outcome: Optional[str] = None,
        grade: Optional[str] = None,
        horizon: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Queries signals with search, filters, date filtering, and pagination."""
        query = db.query(SignalAudit)

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

    def get_daily_summary(self, db: Session) -> List[Dict[str, Any]]:
        """Groups signals by date with Won/Lost count, Win Rate %, and Cumulative Return for each day."""
        dates = db.query(SignalAudit.date_utc).distinct().order_by(desc(SignalAudit.date_utc)).all()
        daily_list = []

        for d_tuple in dates:
            d_str = d_tuple[0]
            if not d_str:
                continue

            day_signals = db.query(SignalAudit).filter(SignalAudit.date_utc == d_str).all()
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
        """Retrieves the most recent market forecast scan."""
        latest = db.query(MarketForecast).order_by(desc(MarketForecast.id)).first()
        if latest:
            return latest.to_dict()
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategy": "Multi-Horizon Quantitative Engine",
            "top_round_signals": [],
            "scanner_leaderboard": [],
            "deep_dive": {},
        }

    def get_engine_status(self) -> Dict[str, Any]:
        """Calculates 15-minute countdown and server state."""
        now = datetime.now(timezone.utc)
        current_minute = now.minute
        current_second = now.second
        
        mins_remaining = 15 - (current_minute % 15)
        secs_remaining = (mins_remaining * 60) - current_second
        if secs_remaining <= 0:
            secs_remaining = 15 * 60

        next_scan_time = (now + timedelta(seconds=secs_remaining)).strftime("%H:%M:%S UTC")

        return {
            "status": "HEALTHY",
            "is_engine_active": True,
            "current_time_utc": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "next_scan_utc": next_scan_time,
            "seconds_to_next_scan": secs_remaining,
        }

signal_service = SignalService()
