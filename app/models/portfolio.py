from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from datetime import datetime, timezone
import math
from app.database import Base

def _safe_float(v, fallback=0.0):
    if v is None:
        return fallback
    try:
        val = float(v)
        return fallback if (math.isnan(val) or math.isinf(val)) else val
    except Exception:
        return fallback

class PaperPosition(Base):
    __tablename__ = "paper_positions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    trade_id = Column(String(128), unique=True, index=True, nullable=False)
    symbol = Column(String(32), index=True, nullable=False)
    horizon = Column(String(32))
    direction = Column(String(16))  # BULLISH / BEARISH
    execution_engine = Column(String(64), default="paper")
    allocated_usd = Column(Float, default=100.0)
    entry_price = Column(Float, nullable=False)
    raw_entry_price = Column(Float, nullable=True)
    current_price = Column(Float, nullable=False)
    tp_price = Column(Float, nullable=False)
    tp1_price = Column(Float, nullable=True)
    tp2_price = Column(Float, nullable=True)
    tp3_price = Column(Float, nullable=True)
    sl_price = Column(Float, nullable=False)
    unrealized_gross_pnl_usd = Column(Float, default=0.0)
    unrealized_pnl_usd = Column(Float, default=0.0)
    unrealized_pnl_pct = Column(Float, default=0.0)
    target_progress_pct = Column(Float, default=0.0)
    buy_fee_usd = Column(Float, default=0.0)
    est_sell_fee_usd = Column(Float, default=0.0)
    unrealized_fee_usd = Column(Float, default=0.0)
    opened_at = Column(String(64))
    expiry_time = Column(String(64))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "horizon": self.horizon,
            "direction": self.direction,
            "execution_engine": self.execution_engine or "paper",
            "allocated_usd": _safe_float(self.allocated_usd, 100.0),
            "entry_price": _safe_float(self.entry_price, 0.0),
            "raw_entry_price": _safe_float(self.raw_entry_price or self.entry_price, 0.0),
            "current_price": _safe_float(self.current_price, 0.0),
            "tp_price": _safe_float(self.tp_price, 0.0),
            "tp1_price": _safe_float(self.tp1_price or self.tp_price, 0.0),
            "tp2_price": _safe_float(self.tp2_price, None),
            "tp3_price": _safe_float(self.tp3_price, None),
            "sl_price": _safe_float(self.sl_price, 0.0),
            "unrealized_gross_pnl_usd": _safe_float(self.unrealized_gross_pnl_usd, 0.0),
            "unrealized_pnl_usd": _safe_float(self.unrealized_pnl_usd, 0.0),
            "unrealized_pnl_pct": _safe_float(self.unrealized_pnl_pct, 0.0),
            "target_progress_pct": _safe_float(self.target_progress_pct, 0.0),
            "buy_fee_usd": _safe_float(self.buy_fee_usd, 0.0),
            "est_sell_fee_usd": _safe_float(self.est_sell_fee_usd, 0.0),
            "unrealized_fee_usd": _safe_float(self.unrealized_fee_usd, 0.0),
            "opened_at": self.opened_at,
            "expiry_time": self.expiry_time,
        }

class ClosedTrade(Base):
    __tablename__ = "closed_trades"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    trade_id = Column(String(128), unique=True, index=True, nullable=False)
    symbol = Column(String(32), index=True, nullable=False)
    horizon = Column(String(32))
    direction = Column(String(16))
    execution_engine = Column(String(64), default="paper")
    entry_price = Column(Float, nullable=False)
    raw_entry_price = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=False)
    exit_reason = Column(String(64))  # TAKE_PROFIT_HIT, STOP_LOSS_HIT, EXPIRED
    outcome = Column(String(16), index=True)  # WON, LOST, BREAKEVEN
    gross_pnl_usd = Column(Float, default=0.0)
    buy_fee_usd = Column(Float, default=0.0)
    sell_fee_usd = Column(Float, default=0.0)
    binance_fee_usd = Column(Float, default=0.0)
    realized_pnl_usd = Column(Float, default=0.0)
    realized_pnl_pct = Column(Float, default=0.0)
    duration_str = Column(String(64))
    opened_at = Column(String(64))
    closed_at = Column(String(64))

    def to_dict(self):
        return {
            "id": self.id,
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "horizon": self.horizon,
            "direction": self.direction,
            "execution_engine": self.execution_engine or "paper",
            "entry_price": _safe_float(self.entry_price, 0.0),
            "raw_entry_price": _safe_float(self.raw_entry_price or self.entry_price, 0.0),
            "exit_price": _safe_float(self.exit_price, 0.0),
            "exit_reason": self.exit_reason,
            "outcome": self.outcome,
            "gross_pnl_usd": _safe_float(self.gross_pnl_usd, 0.0),
            "buy_fee_usd": _safe_float(self.buy_fee_usd, 0.0),
            "sell_fee_usd": _safe_float(self.sell_fee_usd, 0.0),
            "binance_fee_usd": _safe_float(self.binance_fee_usd, 0.0),
            "realized_pnl_usd": _safe_float(self.realized_pnl_usd, 0.0),
            "realized_pnl_pct": _safe_float(self.realized_pnl_pct, 0.0),
            "duration_str": self.duration_str,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
        }
