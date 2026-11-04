"""
The Only 1 Minute Rectangle Strategy: Session High / Low Liquidity Filter
Based on Section 2.3 & Section 13 of "The Only 1 Minute Trading Strategy" by Anees Mehdi.

Tracks timezone-aware UTC sessions (Asia, London, New York) and identifies session high/low levels.
Provides up to 5 bonus points when an M15 liquidity sweep targets a session high/low.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple, List
import pandas as pd
from datetime import datetime, timezone

from app.quant_v16.rectangle_strategy.strategy_config import RectangleStrategyConfig


@dataclass
class SessionInfo:
    active_session: str         # "ASIA", "LONDON", "NEW_YORK", or "OFF_SESSION"
    session_high: float
    session_low: float
    is_near_session_extreme: bool
    session_confluence_score: float = 0.0 # 0 to 5 points


class SessionFilter:
    """
    Computes active trading session and detects proximity to session highs and lows.
    """

    def __init__(self, config: Optional[RectangleStrategyConfig] = None):
        self.config = config or RectangleStrategyConfig()

    def get_session_name(self, utc_hour: int) -> str:
        """Determines session name from UTC hour."""
        a_start, a_end = self.config.asian_session_utc
        l_start, l_end = self.config.london_session_utc
        ny_start, ny_end = self.config.ny_session_utc

        if l_start <= utc_hour < ny_start:
            return "LONDON"
        elif ny_start <= utc_hour < l_end:
            return "LONDON_NY_OVERLAP"
        elif l_end <= utc_hour < ny_end:
            return "NEW_YORK"
        elif a_start <= utc_hour < a_end:
            return "ASIA"
        return "OFF_SESSION"

    def evaluate_session_confluence(
        self,
        target_price: float,
        df_m15: pd.DataFrame,
        atr_value: float,
        current_idx: int = -1
    ) -> SessionInfo:
        """
        Calculates session high/low over recent session window and tests proximity to target price.
        """
        n = len(df_m15)
        idx = n + current_idx if current_idx < 0 else current_idx

        # Extract datetime / UTC hour
        ts = df_m15['timestamp'].iloc[idx] if 'timestamp' in df_m15.columns else None
        utc_hour = 12
        if ts is not None:
            try:
                if isinstance(ts, (int, float)):
                    # Assume ms or seconds
                    s = ts / 1000.0 if ts > 1e11 else float(ts)
                    dt = datetime.fromtimestamp(s, tz=timezone.utc)
                    utc_hour = dt.hour
                elif isinstance(ts, str):
                    dt = pd.to_datetime(ts, utc=True)
                    utc_hour = dt.hour
            except Exception:
                utc_hour = 12

        session_name = self.get_session_name(utc_hour)

        # Look back up to 32 bars (8 hours of M15) to calculate current session high/low
        window = min(32, idx + 1)
        recent_h = df_m15['high'].iloc[idx - window + 1: idx + 1]
        recent_l = df_m15['low'].iloc[idx - window + 1: idx + 1]

        sess_high = float(recent_h.max()) if not recent_h.empty else target_price
        sess_low = float(recent_l.min()) if not recent_l.empty else target_price

        curr_atr = max(1e-8, atr_value)
        dist_to_high = abs(target_price - sess_high) / curr_atr
        dist_to_low = abs(target_price - sess_low) / curr_atr

        is_near_extreme = (dist_to_high <= 0.35 or dist_to_low <= 0.35)
        score = 5.0 if is_near_extreme else 0.0

        return SessionInfo(
            active_session=session_name,
            session_high=round(sess_high, 6),
            session_low=round(sess_low, 6),
            is_near_session_extreme=is_near_extreme,
            session_confluence_score=score
        )

