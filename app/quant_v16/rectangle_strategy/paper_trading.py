"""
The Only 1 Minute Rectangle Strategy: Paper Trading & Virtual Execution Tracker
Based on Section 19 of "The Only 1 Minute Trading Strategy" by Anees Mehdi.

Manages:
- Virtual order execution on confirmed signals
- Live mark-to-market tracking against subsequent ticks/candles
- Dynamic Stop Loss and Take Profit resolution
- Deduplication and state persistence to export_app_data/rectangle_paper_ledger.json
"""

import os
import json
import time
import threading
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional

from app.quant_v16.rectangle_strategy.strategy_config import RectangleStrategyConfig


@dataclass
class PaperPosition:
    position_id: str
    symbol: str
    direction: str              # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float
    signal_score: float
    risk_reward: str
    status: str                 # "OPEN", "WON_TP", "LOST_SL", "CANCELLED"
    created_at_utc: str
    entry_timestamp: float
    exit_price: Optional[float] = None
    exit_timestamp: Optional[float] = None
    gross_pnl_pct: float = 0.0
    net_pnl_pct: float = 0.0
    holding_seconds: float = 0.0
    fees_paid_usd: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RectanglePaperTradingTracker:
    """
    Tracks virtual positions and records signal execution outcomes.
    """

    def __init__(self, config: Optional[RectangleStrategyConfig] = None, ledger_path: Optional[str] = None):
        self.config = config or RectangleStrategyConfig()
        self._lock = threading.Lock()
        export_dir = os.getenv("EXPORT_DIR", "./export_app_data")
        self.ledger_path = ledger_path or os.path.join(export_dir, "rectangle_paper_ledger.json")
        self.positions: Dict[str, PaperPosition] = {}
        self.load_from_disk()

    def load_from_disk(self):
        with self._lock:
            if os.path.exists(self.ledger_path):
                try:
                    with open(self.ledger_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    for p_data in data.get("positions", []):
                        pos = PaperPosition(**p_data)
                        self.positions[pos.position_id] = pos
                except Exception:
                    pass

    def save_to_disk(self):
        with self._lock:
            try:
                os.makedirs(os.path.dirname(os.path.abspath(self.ledger_path)), exist_ok=True)
                data = {
                    "strategy": self.config.strategy_name,
                    "last_updated_utc": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
                    "total_positions": len(self.positions),
                    "open_positions": sum(1 for p in self.positions.values() if p.status == "OPEN"),
                    "won_positions": sum(1 for p in self.positions.values() if p.status == "WON_TP"),
                    "lost_positions": sum(1 for p in self.positions.values() if p.status == "LOST_SL"),
                    "positions": [p.to_dict() for p in self.positions.values()]
                }
                tmp_p = f"{self.ledger_path}.tmp.{threading.get_ident()}.{time.time_ns()}"
                with open(tmp_p, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                os.replace(tmp_p, self.ledger_path)
            except Exception:
                pass

    def open_virtual_position(self, signal: Dict[str, Any]) -> Optional[PaperPosition]:
        """Opens a virtual position from a valid signal dict."""
        if signal.get("signal_status") != "VALID":
            return None

        sym = signal["symbol"]
        dir_t = signal["direction"]
        p_id = f"PAPER_{sym}_{dir_t}_{int(time.time())}"

        with self._lock:
            # Prevent duplicate position if an open position already exists on this symbol
            existing_open = [p for p in self.positions.values() if p.symbol == sym and p.status == "OPEN"]
            if existing_open:
                return None

            pos = PaperPosition(
                position_id=p_id,
                symbol=sym,
                direction=dir_t,
                entry_price=signal["entry_price"],
                stop_loss=signal["stop_loss"],
                take_profit=signal["take_profit"],
                signal_score=signal["signal_score"],
                risk_reward=signal.get("risk_reward", "1:2.0"),
                status="OPEN",
                created_at_utc=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
                entry_timestamp=time.time()
            )
            self.positions[p_id] = pos

        self.save_to_disk()
        return pos

    def update_with_live_price(self, symbol: str, current_price: float) -> List[PaperPosition]:
        """Evaluates live market ticks against open positions."""
        closed = []
        now = time.time()
        friction_pct = (self.config.taker_fee_pct * 2.0) + (self.config.max_slippage_pct * 2.0)

        with self._lock:
            for pos in self.positions.values():
                if pos.symbol == symbol and pos.status == "OPEN":
                    if pos.direction == "LONG":
                        if current_price <= pos.stop_loss:
                            pos.status = "LOST_SL"
                            pos.exit_price = pos.stop_loss
                            pos.exit_timestamp = now
                            pos.holding_seconds = now - pos.entry_timestamp
                            raw = ((pos.exit_price - pos.entry_price) / pos.entry_price) * 100.0
                            pos.gross_pnl_pct = round(raw, 4)
                            pos.net_pnl_pct = round(raw - friction_pct, 4)
                            closed.append(pos)
                        elif current_price >= pos.take_profit:
                            pos.status = "WON_TP"
                            pos.exit_price = pos.take_profit
                            pos.exit_timestamp = now
                            pos.holding_seconds = now - pos.entry_timestamp
                            raw = ((pos.exit_price - pos.entry_price) / pos.entry_price) * 100.0
                            pos.gross_pnl_pct = round(raw, 4)
                            pos.net_pnl_pct = round(raw - friction_pct, 4)
                            closed.append(pos)
                    else: # SHORT
                        if current_price >= pos.stop_loss:
                            pos.status = "LOST_SL"
                            pos.exit_price = pos.stop_loss
                            pos.exit_timestamp = now
                            pos.holding_seconds = now - pos.entry_timestamp
                            raw = ((pos.entry_price - pos.exit_price) / pos.entry_price) * 100.0
                            pos.gross_pnl_pct = round(raw, 4)
                            pos.net_pnl_pct = round(raw - friction_pct, 4)
                            closed.append(pos)
                        elif current_price <= pos.take_profit:
                            pos.status = "WON_TP"
                            pos.exit_price = pos.take_profit
                            pos.exit_timestamp = now
                            pos.holding_seconds = now - pos.entry_timestamp
                            raw = ((pos.entry_price - pos.exit_price) / pos.entry_price) * 100.0
                            pos.gross_pnl_pct = round(raw, 4)
                            pos.net_pnl_pct = round(raw - friction_pct, 4)
                            closed.append(pos)

        if closed:
            self.save_to_disk()
        return closed

