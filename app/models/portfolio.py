from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from datetime import datetime, timezone
from app.database import Base

class PaperPosition(Base):
    __tablename__ = "paper_positions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    trade_id = Column(String(128), unique=True, index=True, nullable=False)
    symbol = Column(String(32), index=True, nullable=False)
    horizon = Column(String(32))
    direction = Column(String(16))  # BULLISH / BEARISH
    allocated_usd = Column(Float, default=100.0)
    entry_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=False)
    tp_price = Column(Float, nullable=False)
    sl_price = Column(Float, nullable=False)
    unrealized_pnl_usd = Column(Float, default=0.0)
    unrealized_pnl_pct = Column(Float, default=0.0)
    target_progress_pct = Column(Float, default=0.0)
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
            "allocated_usd": self.allocated_usd,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "tp_price": self.tp_price,
            "sl_price": self.sl_price,
            "unrealized_pnl_usd": self.unrealized_pnl_usd,
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
            "target_progress_pct": self.target_progress_pct,
            "unrealized_fee_usd": self.unrealized_fee_usd,
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
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)
    exit_reason = Column(String(64))  # TAKE_PROFIT_HIT, STOP_LOSS_HIT, EXPIRED
    outcome = Column(String(16), index=True)  # WON, LOST, BREAKEVEN
    gross_pnl_usd = Column(Float, default=0.0)
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
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "exit_reason": self.exit_reason,
            "outcome": self.outcome,
            "gross_pnl_usd": self.gross_pnl_usd,
            "binance_fee_usd": self.binance_fee_usd,
            "realized_pnl_usd": self.realized_pnl_usd,
            "realized_pnl_pct": self.realized_pnl_pct,
            "duration_str": self.duration_str,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
        }
