from sqlalchemy.orm import Session
from sqlalchemy import func, or_, desc
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from collections import defaultdict
import math
import os
import json
import numpy as np

import time
import requests

from app.config import settings
from app.models import SignalAudit, PaperPosition, ClosedTrade, MarketForecast
from app.services.db_sync import sync_files_to_db_live, get_sync_state, get_cached_forecast, set_cached_forecast

_LIVE_PRICES_CACHE: Dict[str, float] = {}
_LIVE_PRICES_TS: float = 0.0

def fetch_live_binance_prices(max_age_seconds: float = 2.5) -> Dict[str, float]:
    """Fetches real-time Binance spot prices with high-speed memory TTL cache."""
    global _LIVE_PRICES_CACHE, _LIVE_PRICES_TS
    now = time.time()
    if _LIVE_PRICES_CACHE and (now - _LIVE_PRICES_TS) < max_age_seconds:
        return _LIVE_PRICES_CACHE

    try:
        url = "https://data-api.binance.vision/api/v3/ticker/price"
        resp = requests.get(url, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            p_dict = {}
            for item in data:
                raw_s = item['symbol']
                p_val = float(item['price'])
                p_dict[raw_s] = p_val
                if raw_s.endswith('USDT'):
                    base = raw_s[:-4]
                    p_dict[f"{base}/USDT"] = p_val
            _LIVE_PRICES_CACHE = p_dict
            _LIVE_PRICES_TS = now
            return p_dict
    except Exception:
        pass
    return _LIVE_PRICES_CACHE or {}

class SignalService:
    def resolve_pending_signals_live(self, db: Session):
        """
        Evaluates pending signals in the database against live Binance spot prices:
        - Resolves expired signals when predicted_close_utc has passed.
        - Resolves TP1 / TP2 / TP3 / SL hits in real time.
        """
        try:
            pending = db.query(SignalAudit).filter(
                or_(
                    SignalAudit.status.in_(["PENDING_EVALUATION", "ACTIVE", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"]),
                    SignalAudit.outcome_label.like("%PENDING%")
                )
            ).all()
            if not pending:
                return

            live_prices = fetch_live_binance_prices(max_age_seconds=2.0)
            if not live_prices:
                return

            now_utc = datetime.now(timezone.utc)
            now_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
            updated = False

            for s in pending:
                sym = s.symbol
                curr_p = live_prices.get(sym) or live_prices.get(sym.replace('/', ''))
                if not curr_p:
                    continue

                entry_p = float(s.entry_price or curr_p)
                tp1_p = float(s.tp1_price or entry_p)
                tp2_p = float(s.tp2_price or entry_p)
                tp3_p = float(s.tp3_price or entry_p)
                sl_p = float(s.sl_price or entry_p)
                direction = str(s.direction or "LONG").upper()

                s.peak_price_seen = max(float(s.peak_price_seen or curr_p), curr_p)
                s.trough_price_seen = min(float(s.trough_price_seen or curr_p), curr_p)
                max_gain = ((s.peak_price_seen - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - s.trough_price_seen) / entry_p) * 100.0
                s.max_potential_gain_pct = round(max_gain, 2)

                is_hit_tp3 = (direction == "LONG" and curr_p >= tp3_p) or (direction == "SHORT" and curr_p <= tp3_p)
                is_hit_tp2 = (direction == "LONG" and curr_p >= tp2_p) or (direction == "SHORT" and curr_p <= tp2_p)
                is_hit_tp1 = (direction == "LONG" and curr_p >= tp1_p) or (direction == "SHORT" and curr_p <= tp1_p)
                is_hit_sl = (direction == "LONG" and curr_p <= sl_p) or (direction == "SHORT" and curr_p >= sl_p)

                is_expired = False
                pred_close = str(s.predicted_close_utc or "").strip()
                if not pred_close or pred_close == "N/A":
                    p_win = str(s.predicted_window or "")
                    if "➔" in p_win:
                        after_arrow = p_win.split("➔")[-1].strip()
                        pred_close = after_arrow.split("(")[0].strip() if "(" in after_arrow else after_arrow.strip()

                if pred_close and pred_close != "N/A":
                    try:
                        clean_str = pred_close.replace(" UTC", "").strip()
                        close_dt = datetime.fromisoformat(clean_str) if "T" in clean_str else datetime.strptime(clean_str, "%Y-%m-%d %H:%M")
                        if close_dt.tzinfo is None:
                            close_dt = close_dt.replace(tzinfo=timezone.utc)
                        if now_utc >= close_dt:
                            is_expired = True
                            s.predicted_close_utc = pred_close
                    except Exception:
                        pass

                # 0. Tier-0 Early Breakeven Guard (+0.65% gain raises SL to Soft BE)
                if max_gain >= 0.65 and s.status not in ["TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"] and not is_hit_sl:
                    s.status = "TIER0_PROTECTED_BREAKEVEN"
                    soft_be_p = (entry_p * 0.998) if direction == "LONG" else (entry_p * 1.002)
                    s.sl_price = round(max(sl_p, soft_be_p) if direction == "LONG" else min(sl_p, soft_be_p), 6)
                    sl_p = s.sl_price
                    s.outcome_label = "🛡️ PROFIT PROTECTED (SOFT BE)"
                    updated = True

                if is_hit_tp3:
                    s.status = "WON_TP3"
                    s.exit_price = round(tp3_p, 6)
                    ret_pct = ((tp3_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp3_p) / entry_p) * 100.0
                    s.realized_return_pct = round(ret_pct, 2)
                    s.outcome_label = "🟢 WON (TP3 HIT)"
                    s.evaluated_at_utc = now_str
                    updated = True
                elif is_hit_tp2 and s.status != "TP2_LOCKED_TRAIL":
                    s.status = "TP2_LOCKED_TRAIL"
                    s.sl_price = round(tp1_p, 6)
                    s.outcome_label = "🟢 TP2 HIT (TRAILING SL @ TP1)"
                    updated = True
                elif is_hit_tp1 and s.status not in ["TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL"] and not is_hit_sl:
                    s.status = "TP1_LOCKED_BREAKEVEN"
                    s.sl_price = round(entry_p, 6)
                    s.outcome_label = "🟢 TP1 HIT (SL @ BREAKEVEN)"
                    updated = True
                elif is_hit_sl:
                    if s.status == "TP2_LOCKED_TRAIL":
                        ret_tp1 = ((tp1_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp1_p) / entry_p) * 100.0
                        ret_tp2 = ((tp2_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp2_p) / entry_p) * 100.0
                        blended_ret = (0.50 * ret_tp1) + (0.30 * ret_tp2) + (0.20 * ret_tp1)
                        s.status = "WON_TP2_TRAIL"
                        s.exit_price = round(tp1_p, 6)
                        s.realized_return_pct = round(blended_ret, 2)
                        s.outcome_label = "🟢 WON (TP2 + TRAILING RUNNER)"
                    elif s.status == "TP1_LOCKED_BREAKEVEN":
                        ret_tp1 = ((tp1_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp1_p) / entry_p) * 100.0
                        blended_ret = 0.50 * ret_tp1
                        s.status = "WON_TP1_BE"
                        s.exit_price = round(entry_p, 6)
                        s.realized_return_pct = round(blended_ret, 2)
                        s.outcome_label = "🟢 WON (TP1 + BE RUNNER)"
                    elif s.status == "TIER0_PROTECTED_BREAKEVEN":
                        ret_be = ((sl_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - sl_p) / entry_p) * 100.0
                        s.status = "WON_TIER0_BE"
                        s.exit_price = round(sl_p, 6)
                        s.realized_return_pct = round(ret_be, 2)
                        s.outcome_label = f"🛡️ BREAKEVEN (TIER-0 GUARD {ret_be:+.2f}%)"
                    else:
                        s.status = "LOST_SL"
                        s.exit_price = round(sl_p, 6)
                        ret_pct = ((sl_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - sl_p) / entry_p) * 100.0
                        s.realized_return_pct = round(ret_pct, 2)
                        s.outcome_label = "🔴 LOST (SL HIT)"
                    s.evaluated_at_utc = now_str
                    updated = True
                elif is_expired:
                    ret_current = ((curr_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - curr_p) / entry_p) * 100.0
                    if s.status == "TP1_LOCKED_BREAKEVEN":
                        ret_tp1 = ((tp1_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp1_p) / entry_p) * 100.0
                        blended_ret = (0.50 * ret_tp1) + (0.50 * max(0.0, ret_current))
                        s.status = "WON_TP1_EXP"
                        s.exit_price = round(curr_p, 6)
                        s.realized_return_pct = round(blended_ret, 2)
                        s.outcome_label = f"🟢 WON (TP1 + EXP {blended_ret:+.2f}%)"
                    elif s.status == "TIER0_PROTECTED_BREAKEVEN":
                        s.status = "WON_TIER0_BE"
                        s.exit_price = round(curr_p, 6)
                        s.realized_return_pct = round(ret_current, 2)
                        s.outcome_label = f"🛡️ EXPIRED (TIER-0 BE {ret_current:+.2f}%)"
                    else:
                        s.status = "EXPIRED_PROFIT" if ret_current > 0 else ("EXPIRED_LOSS" if ret_current < 0 else "EXPIRED_FLAT")
                        s.exit_price = round(curr_p, 6)
                        s.realized_return_pct = round(ret_current, 2)
                        s.outcome_label = f"{'🟢' if ret_current>=0 else '🔴'} EXPIRED ({ret_current:+.2f}%)"
                    s.evaluated_at_utc = now_str
                    updated = True

            if updated:
                db.commit()
        except Exception:
            db.rollback()

    def get_kpi_summary(self, db: Session) -> Dict[str, Any]:
        """Calculates executive KPI metrics in a single optimized pass."""
        sync_files_to_db_live()
        self.resolve_pending_signals_live(db)
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
        direction: Optional[str] = None,
        min_return: Optional[float] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Queries signals with search, filters, date filtering, min_return filtering, and pagination."""
        sync_files_to_db_live()
        self.resolve_pending_signals_live(db)
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

        if direction:
            d_upper = direction.upper().strip()
            if d_upper in ["LONG", "BULLISH"]:
                query = query.filter(or_(SignalAudit.direction == "LONG", SignalAudit.direction == "BULLISH"))
            elif d_upper in ["SHORT", "BEARISH"]:
                query = query.filter(or_(SignalAudit.direction == "SHORT", SignalAudit.direction == "BEARISH"))

        if min_return is not None and min_return > 0:
            query = query.filter(
                or_(
                    func.abs(SignalAudit.expected_return_pct) >= min_return,
                    func.abs(SignalAudit.max_potential_gain_pct) >= min_return,
                    func.abs(SignalAudit.realized_return_pct) >= min_return,
                )
            )

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
        
        # Read starting balance and analytics from paper trading ledger JSON if present
        ledger_data = {}
        try:
            p_path = os.path.join(settings.EXPORT_DIR, "paper_trading_ledger.json")
            if os.path.exists(p_path):
                with open(p_path, "r", encoding="utf-8") as f:
                    ledger_data = json.load(f)
        except Exception:
            pass

        positions = db.query(PaperPosition).order_by(desc(PaperPosition.id)).all()
        closed_trades = db.query(ClosedTrade).order_by(desc(ClosedTrade.id)).all()

        total_trades = ledger_data.get("total_trades", len(closed_trades))
        winning_trades = ledger_data.get("winning_trades", sum(1 for c in closed_trades if c.outcome == "WON"))
        losing_trades = ledger_data.get("losing_trades", sum(1 for c in closed_trades if c.outcome == "LOST"))
        breakeven_trades = ledger_data.get("breakeven_trades", sum(1 for c in closed_trades if c.outcome == "BREAKEVEN"))
        net_profit = ledger_data.get("realized_pnl_usd", sum(c.realized_pnl_usd for c in closed_trades))
        decisive = winning_trades + losing_trades
        win_rate = ledger_data.get("win_rate_pct", round((winning_trades / max(1, decisive)) * 100.0, 2) if decisive > 0 else 0.0)
        start_balance = float(ledger_data.get("starting_balance_usd", 100.0))
        current_balance = float(ledger_data.get("current_balance_usd", start_balance + net_profit))

        return {
            "initial_capital_usd": start_balance,
            "current_balance_usd": round(current_balance, 2),
            "open_positions": [p.to_dict() for p in positions],
            "closed_trades_history": [c.to_dict() for c in closed_trades],
            "total_trades_count": total_trades,
            "winning_trades_count": winning_trades,
            "losing_trades_count": losing_trades,
            "breakeven_trades_count": breakeven_trades,
            "win_rate_pct": win_rate,
            "total_net_profit_usd": round(net_profit, 2),
            "gross_profit_usd": round(float(ledger_data.get("gross_profit_usd", 0.0)), 2),
            "gross_loss_usd": round(float(ledger_data.get("gross_loss_usd", 0.0)), 2),
            "total_fees_paid_usd": round(float(ledger_data.get("total_fees_paid_usd", 0.0)), 2),
            "profit_factor": float(ledger_data.get("profit_factor", 0.0)),
            "peak_balance_usd": round(float(ledger_data.get("peak_balance_usd", start_balance)), 2),
            "max_drawdown_usd": round(float(ledger_data.get("max_drawdown_usd", 0.0)), 2),
            "max_drawdown_pct": round(float(ledger_data.get("max_drawdown_pct", 0.0)), 2),
            "fee_tier_label": str(ledger_data.get("fee_tier_label", "Binance Convert (Zero Fee | +0.10% Buy / -0.10% Sell Spread)")),
            "queued_trades": ledger_data.get("queued_trades", []),
        }

    def reset_portfolio_data(self, db: Session, target_start_balance: float = 100.0) -> Dict[str, Any]:
        """Completely wipes open positions and closed trades from DB and resets paper trading ledger JSON to clean state."""
        try:
            db.query(PaperPosition).delete()
            db.query(ClosedTrade).delete()
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[RESET ERROR] Database purge: {e}")

        clean_ledger = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "fee_tier_label": "Binance Convert (Zero Fee | +0.10% Buy / -0.10% Sell Spread)",
            "execution_engine": "binance_convert",
            "starting_balance_usd": target_start_balance,
            "current_balance_usd": target_start_balance,
            "realized_pnl_usd": 0.0,
            "gross_realized_pnl_usd": 0.0,
            "total_fees_paid_usd": 0.0,
            "gross_profit_usd": 0.0,
            "gross_loss_usd": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "breakeven_trades": 0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "peak_balance_usd": target_start_balance,
            "max_drawdown_usd": 0.0,
            "max_drawdown_pct": 0.0,
            "open_positions": [],
            "closed_trades_history": [],
            "queued_trades": []
        }

        try:
            os.makedirs(settings.EXPORT_DIR, exist_ok=True)
            p_path = os.path.join(settings.EXPORT_DIR, "paper_trading_ledger.json")
            with open(p_path, "w", encoding="utf-8") as f:
                json.dump(clean_ledger, f, indent=4)
        except Exception as e:
            print(f"[RESET ERROR] File write: {e}")

        clear_forecast_cache()

        return {
            "success": True,
            "message": f"Paper trading successfully reset to ${target_start_balance:.2f} starting capital. All prior open positions and history wiped.",
            "portfolio": clean_ledger
        }

    def get_all_live_prices(self) -> Dict[str, Any]:
        """Returns real-time prices dictionary for all pairs."""
        prices = fetch_live_binance_prices(max_age_seconds=2.5)
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prices": prices
        }

    def overlay_live_prices(self, forecast_data: Dict[str, Any]) -> Dict[str, Any]:
        """Dynamically overlays current real-time prices on top of forecast data."""
        if not forecast_data:
            return forecast_data

        live_prices = fetch_live_binance_prices(max_age_seconds=3.0)
        if not live_prices:
            return forecast_data

        # Clone payload
        res = dict(forecast_data)
        
        # Overlay on scanner leaderboard
        leaderboard = res.get("scanner_leaderboard", [])
        if leaderboard:
            updated_board = []
            for item in leaderboard:
                coin_dict = dict(item)
                sym = coin_dict.get("symbol", "")
                raw_sym = sym.replace("/", "").replace(":USDT", "")
                p = live_prices.get(sym) or live_prices.get(raw_sym)
                if p and p > 0:
                    coin_dict["current_price"] = p
                    coin_dict["live_price"] = p
                    if "live_high" in coin_dict:
                        coin_dict["live_high"] = max(coin_dict["live_high"], p)
                    if "live_low" in coin_dict:
                        coin_dict["live_low"] = min(coin_dict["live_low"], p)
                updated_board.append(coin_dict)
            res["scanner_leaderboard"] = updated_board

        # Overlay on top round signals
        top_signals = res.get("top_round_signals", [])
        if top_signals:
            updated_top = []
            for sig in top_signals:
                s_dict = dict(sig)
                sym = s_dict.get("symbol", "")
                raw_sym = sym.replace("/", "").replace(":USDT", "")
                p = live_prices.get(sym) or live_prices.get(raw_sym)
                if p and p > 0:
                    s_dict["current_price"] = p
                    s_dict["live_price"] = p
                    entry_p = float(s_dict.get("entry_price") or p)
                    direction = str(s_dict.get("direction", "LONG")).upper()
                    if entry_p > 0:
                        s_dict["live_pnl_pct"] = round(((p - entry_p) / entry_p) * 100.0, 2) if direction in ["LONG", "BULLISH"] else round(((entry_p - p) / entry_p) * 100.0, 2)
                updated_top.append(s_dict)
            res["top_round_signals"] = updated_top

        # Overlay on signals_by_horizon
        signals_by_h = res.get("signals_by_horizon", {})
        if isinstance(signals_by_h, dict):
            updated_h = {}
            for h_tag, sig_list in signals_by_h.items():
                up_list = []
                for sig in sig_list:
                    s_dict = dict(sig)
                    sym = s_dict.get("symbol", "")
                    raw_sym = sym.replace("/", "").replace(":USDT", "")
                    p = live_prices.get(sym) or live_prices.get(raw_sym)
                    if p and p > 0:
                        s_dict["current_price"] = p
                        s_dict["live_price"] = p
                        entry_p = float(s_dict.get("entry_price") or p)
                        direction = str(s_dict.get("direction", "LONG")).upper()
                        if entry_p > 0:
                            s_dict["live_pnl_pct"] = round(((p - entry_p) / entry_p) * 100.0, 2) if direction in ["LONG", "BULLISH"] else round(((entry_p - p) / entry_p) * 100.0, 2)
                    up_list.append(s_dict)
                updated_h[h_tag] = up_list
            res["signals_by_horizon"] = updated_h

        return res

    def get_latest_forecast(self, db: Session) -> Dict[str, Any]:
        """Retrieves the most recent market forecast scan with in-memory cache and live price overlay."""
        cached = get_cached_forecast()
        if cached:
            return self.overlay_live_prices(cached)

        sync_files_to_db_live()
        cached = get_cached_forecast()
        if cached:
            return self.overlay_live_prices(cached)

        latest = db.query(MarketForecast).order_by(desc(MarketForecast.id)).first()
        if latest:
            res = latest.to_dict()
            set_cached_forecast(res)
            return self.overlay_live_prices(res)
        
        # Fallback to direct file read if available
        try:
            forecast_path = os.path.join(settings.EXPORT_DIR, "live_market_forecast.json")
            if os.path.exists(forecast_path):
                with open(forecast_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    set_cached_forecast(data)
                    return self.overlay_live_prices(data)
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
        now_ts = now.timestamp()
        if sync_state.get("next_scan_timestamp") and int(sync_state["next_scan_timestamp"]) > now_ts:
            target_ts = int(sync_state["next_scan_timestamp"])
            secs_remaining = max(1, int(target_ts - now_ts))
            next_scan_time = sync_state.get("next_scan_time_utc") or (now + timedelta(seconds=secs_remaining)).strftime("%Y-%m-%d %H:%M:%S UTC")
        else:
            mins_remaining = 15 - (current_minute % 15)
            secs_remaining = (mins_remaining * 60) - current_second + 2
            if secs_remaining <= 5:
                secs_remaining += 900
            target_ts = int((now + timedelta(seconds=secs_remaining)).timestamp())
            next_scan_time = (now + timedelta(seconds=secs_remaining)).strftime("%Y-%m-%d %H:%M:%S UTC")

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
            "scanned_assets_count": sync_state.get("scanned_assets_count", 0),
            "total_assets_count": sync_state.get("total_assets_count", 100),
            "current_time_utc": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "next_scan_utc": next_scan_time,
            "next_scan_timestamp": target_ts,
            "seconds_to_next_scan": secs_remaining,
            "last_scan_duration_seconds": sync_state.get("last_scan_duration_seconds"),
            "scan_version": sync_state["full_scan_version"],
            "full_scan_version": sync_state["full_scan_version"],
            "portfolio_version": sync_state["portfolio_version"],
            "last_scan_timestamp": sync_state["last_scan_timestamp"],
            "btc_market_shield": shield_status,
        }

signal_service = SignalService()
