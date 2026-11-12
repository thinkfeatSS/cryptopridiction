from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.dialects.mysql import LONGTEXT
from datetime import datetime, timezone
import json
from app.database import Base

class MarketForecast(Base):
    __tablename__ = "market_forecasts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    timestamp_utc = Column(String(64), nullable=False, index=True)
    strategy_name = Column(String(128), default="Multi-Horizon Quantitative Engine")
    top_round_signals_json = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    scanner_leaderboard_json = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    deep_dive_json = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    btc_market_shield_json = Column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    @staticmethod
    def _safe_json_loads(val, fallback):
        if not val:
            return fallback
        if not isinstance(val, str):
            return val
        try:
            return json.loads(val)
        except Exception:
            return fallback

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp_utc,
            "strategy": self.strategy_name,
            "btc_market_shield": self._safe_json_loads(self.btc_market_shield_json, {"active": False, "reason": "NORMAL (Market Stable)"}),
            "top_round_signals": self._safe_json_loads(self.top_round_signals_json, []),
            "scanner_leaderboard": self._safe_json_loads(self.scanner_leaderboard_json, []),
            "deep_dive": self._safe_json_loads(self.deep_dive_json, {}),
        }
