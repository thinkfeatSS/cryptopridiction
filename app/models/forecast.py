from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime, timezone
import json
from app.database import Base

class MarketForecast(Base):
    __tablename__ = "market_forecasts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    timestamp_utc = Column(String(64), nullable=False)
    strategy_name = Column(String(128), default="Multi-Horizon Quantitative Engine")
    top_round_signals_json = Column(Text)
    scanner_leaderboard_json = Column(Text)
    deep_dive_json = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp_utc,
            "strategy": self.strategy_name,
            "top_round_signals": json.loads(self.top_round_signals_json) if self.top_round_signals_json else [],
            "scanner_leaderboard": json.loads(self.scanner_leaderboard_json) if self.scanner_leaderboard_json else [],
            "deep_dive": json.loads(self.deep_dive_json) if self.deep_dive_json else {},
        }
