from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Index
from datetime import datetime, timezone
from app.database import Base

class SignalAudit(Base):
    __tablename__ = "signals_tracker"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    signal_id = Column(String(128), unique=True, index=True, nullable=False)
    date_utc = Column(String(32), index=True)
    time_utc = Column(String(32))
    rank_label = Column(String(32))
    quality_grade = Column(String(64), index=True)
    grade_tier = Column(Integer, default=2, index=True)  # 1: A+, 2: A, 3: B+, 4: C
    symbol = Column(String(32), index=True, nullable=False)
    horizon = Column(String(32), index=True)  # SCALP (15M), SWING (1H), MACRO (24H)
    direction = Column(String(16), index=True)  # LONG / SHORT
    conviction_pct = Column(Float, default=50.0)
    entry_price = Column(Float, nullable=False)
    tp1_price = Column(Float)
    tp2_price = Column(Float)
    tp3_price = Column(Float)
    sl_price = Column(Float)
    risk_reward_ratio = Column(String(16), default="1:2.0")
    expected_return_pct = Column(Float, default=0.0)
    decision = Column(String(128))
    paper_trading_status = Column(String(64))
    predicted_window = Column(String(128))
    predicted_close_utc = Column(String(64))
    status = Column(String(32), default="PENDING_EVALUATION", index=True)
    outcome_label = Column(String(64), default="PENDING ⏳", index=True)
    peak_price_seen = Column(Float)
    trough_price_seen = Column(Float)
    max_potential_gain_pct = Column(Float, default=0.0)
    exit_price = Column(Float, nullable=True)
    realized_return_pct = Column(Float, nullable=True)  # Clean float for aggregations
    evaluated_at_utc = Column(String(64), nullable=True)
    tf_metrics_json = Column(Text, nullable=True)
    card_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "signal_id": self.signal_id,
            "date_utc": self.date_utc,
            "time_utc": self.time_utc,
            "rank": self.rank_label,
            "quality_grade": self.quality_grade,
            "grade_tier": self.grade_tier,
            "symbol": self.symbol,
            "horizon": self.horizon,
            "direction": self.direction,
            "conviction_pct": self.conviction_pct,
            "entry_price": self.entry_price,
            "tp1_price": self.tp1_price,
            "tp2_price": self.tp2_price,
            "tp3_price": self.tp3_price,
            "sl_price": self.sl_price,
            "risk_reward_ratio": self.risk_reward_ratio,
            "expected_return_pct": self.expected_return_pct,
            "decision": self.decision,
            "paper_trading_status": self.paper_trading_status,
            "predicted_window": self.predicted_window,
            "predicted_close_utc": self.predicted_close_utc,
            "status": self.status,
            "outcome_label": self.outcome_label,
            "peak_price_seen": self.peak_price_seen,
            "trough_price_seen": self.trough_price_seen,
            "max_potential_gain_pct": self.max_potential_gain_pct,
            "exit_price": self.exit_price,
            "realized_return_pct": f"{self.realized_return_pct:+.2f}%" if self.realized_return_pct is not None else "",
            "realized_return_num": self.realized_return_pct,
            "evaluated_at_utc": self.evaluated_at_utc or "",
            "tf_metrics_json": self.tf_metrics_json,
            "card": self.card_text,
        }
