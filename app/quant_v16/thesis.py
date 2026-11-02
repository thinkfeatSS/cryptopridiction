"""
QUANT EDGE V16: Trade Thesis Engine & Correlation Guard
Specifications:
- Section 3: G3 (Separate signal from trade thesis)
- Section 25: Trade Thesis Engine (thesis_direction, thesis_strength, 1 position per thesis)
- Section 26: Correlation Engine (LOW, MEDIUM, HIGH, EXTREME, CRYPTO_BETA cluster)
- Section 27: Portfolio Risk Engine (max thesis exposure = 1, max asset exposure = 1)
"""

from typing import Dict, Any, List, Set, Optional, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, field
import hashlib

@dataclass
class TradeThesis:
    thesis_id: str                   # e.g. THESIS-BTC-BREAKOUT-20261008-01
    symbol: str                      # BTC/USDT
    primary_direction: str           # LONG or SHORT
    strategy_archetype: str          # BREAKOUT_LONG
    regime: str                      # BULL_TREND
    signals_count: int = 1
    participating_horizons: List[str] = field(default_factory=list)
    thesis_strength: float = 80.0    # 0 - 100
    thesis_expected_net_return: float = 0.85
    created_at_utc: str = ""
    is_position_open: bool = False

class TradeThesisEngine:
    """
    Groups multi-horizon signals into unified root trade theses to prevent
    duplicate exposure and over-leveraged stacking on the same underlying market idea.
    """

    def __init__(self):
        # thesis_id -> TradeThesis
        self.active_theses: Dict[str, TradeThesis] = {}
        # (clean_sym, direction) -> thesis_id
        self.symbol_direction_map: Dict[Tuple[str, str], str] = {}

    @staticmethod
    def generate_thesis_id(symbol: str, direction: str, strategy: str, dt_str: Optional[str] = None) -> str:
        sym_clean = symbol.replace('/', '').replace(':', '')
        d_str = dt_str or datetime.now(timezone.utc).strftime("%Y%m%d_%H")
        return f"THESIS-{sym_clean}-{direction[:4]}-{d_str}"

    def register_or_update(
        self,
        symbol: str,
        direction: str,
        horizon: str,
        strategy: str,
        regime: str,
        expected_net_return: float
    ) -> Tuple[TradeThesis, bool]:
        """
        Assigns signal to an existing thesis if same coin and direction, or creates new thesis.
        Returns: (TradeThesis, is_new_thesis)
        """
        clean_sym = symbol.strip().upper()
        dir_upper = direction.strip().upper()
        pair_key = (clean_sym, dir_upper)

        existing_thesis_id = self.symbol_direction_map.get(pair_key)
        if existing_thesis_id and existing_thesis_id in self.active_theses:
            thesis = self.active_theses[existing_thesis_id]
            if horizon not in thesis.participating_horizons:
                thesis.participating_horizons.append(horizon)
                thesis.signals_count += 1
                # Increase thesis strength when confirmed across multiple horizons
                thesis.thesis_strength = min(100.0, thesis.thesis_strength + 5.0)
                thesis.thesis_expected_net_return = max(thesis.thesis_expected_net_return, expected_net_return)
            return thesis, False

        # Create fresh Trade Thesis
        now_utc = datetime.now(timezone.utc)
        th_id = self.generate_thesis_id(clean_sym, dir_upper, strategy, now_utc.strftime("%Y%m%d_%H%M"))
        
        new_thesis = TradeThesis(
            thesis_id=th_id,
            symbol=clean_sym,
            primary_direction=dir_upper,
            strategy_archetype=strategy,
            regime=regime,
            signals_count=1,
            participating_horizons=[horizon],
            thesis_strength=75.0,
            thesis_expected_net_return=expected_net_return,
            created_at_utc=now_utc.strftime('%Y-%m-%d %H:%M:%S UTC'),
            is_position_open=False
        )

        self.active_theses[th_id] = new_thesis
        self.symbol_direction_map[pair_key] = th_id
        return new_thesis, True

    def can_open_position(self, thesis_id: str) -> Tuple[bool, str]:
        """
        Section 27: Enforces max_thesis_exposure = 1 position.
        """
        thesis = self.active_theses.get(thesis_id)
        if not thesis:
            return True, "Valid"
        if thesis.is_position_open:
            return False, f"Thesis {thesis_id} already has an open executed position (Max 1 per thesis rule)"
        return True, "Eligible"
