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
import os
import json
import threading

CANONICAL_HORIZONS = ["5M", "15M", "1H", "4H", "12H", "24H", "7D", "15D", "1M"]
HORIZON_SORT_ORDER = {hz: idx for idx, hz in enumerate(CANONICAL_HORIZONS)}


def normalize_horizon(raw_hz: Optional[str]) -> str:
    """
    Normalizes any display, emoji-prefixed, or timeframe alias string to canonical format:
    '5M', '15M', '1H', '4H', '12H', '24H', '7D', '15D', '1M'.
    """
    if not raw_hz:
        return "1H"
    hz_u = str(raw_hz).upper().strip()

    # Exact canonical match
    if hz_u in HORIZON_SORT_ORDER:
        return hz_u

    # Substring search in reverse priority (e.g. 15D before 1D or 5D)
    for canonical in ["15D", "7D", "24H", "12H", "15M", "5M", "4H", "1H", "1M"]:
        if canonical in hz_u:
            return canonical

    if "1D" in hz_u or "DAILY" in hz_u or "SWING" in hz_u:
        return "24H"
    if "SCALP" in hz_u:
        return "15M"
    if "INTRADAY" in hz_u:
        return "1H"
    if "MACRO" in hz_u:
        return "24H"

    return "1H"


@dataclass
class TradeThesis:
    thesis_id: str                   # e.g. THESIS-BTCUSDT-LONG
    symbol: str                      # BTC/USDT
    primary_direction: str           # LONG or SHORT
    strategy_archetype: str          # BREAKOUT_LONG
    regime: str                      # BULL_TREND
    signals_count: int = 1
    participating_horizons: List[str] = field(default_factory=list)
    signals: List[str] = field(default_factory=list)
    thesis_strength: float = 75.0    # 0 - 100
    thesis_expected_net_return: float = 0.85
    highest_net_ev: float = 0.85
    created_at_utc: str = ""
    is_position_open: bool = False
    is_active: bool = True
    active_signals_count: int = 1
    current_price: float = 0.0
    unrealized_net_pnl_pct: float = 0.0
    mfe_pct: float = 0.0


class TradeThesisEngine:
    """
    Institutional Trade Thesis Engine:
    Groups multi-horizon signals into unified root trade theses to prevent
    duplicate exposure and over-leveraged stacking on the same underlying market idea (Section 25).
    Enforces maximum 1 position per thesis (Section 27 Zero Stacking Guard).
    """

    def __init__(self, export_dir: Optional[str] = None):
        self.export_dir = export_dir or os.getenv("EXPORT_DIR", "./export_app_data")
        # thesis_id -> TradeThesis
        self.active_theses: Dict[str, TradeThesis] = {}
        # (clean_sym, direction) -> thesis_id
        self.symbol_direction_map: Dict[Tuple[str, str], str] = {}
        self._lock = threading.RLock()
        self.load_theses_from_disk()

    @staticmethod
    def generate_thesis_id(symbol: str, direction: str, strategy: str = "", dt_str: Optional[str] = None) -> str:
        """
        Generates canonical thesis identifier.
        When dt_str is provided, appends timestamp bucket; otherwise returns stable root ID.
        """
        sym_clean = symbol.replace('/', '').replace(':', '').replace('-', '').upper()
        dir_clean = direction.strip().upper()
        if dir_clean.startswith("SHOR"):
            dir_clean = "SHORT"
        elif dir_clean.startswith("LONG"):
            dir_clean = "LONG"

        if dt_str:
            return f"THESIS-{sym_clean}-{dir_clean[:4]}-{dt_str}"
        return f"THESIS-{sym_clean}-{dir_clean}"

    def register_or_update(
        self,
        symbol: str,
        direction: str,
        horizon: str,
        strategy: str,
        regime: str,
        expected_net_return: float,
        signal_id: Optional[str] = None,
        dt_str: Optional[str] = None
    ) -> Tuple[TradeThesis, bool]:
        """
        Assigns signal to an existing thesis if same coin and direction, or creates new root thesis.
        Returns: (TradeThesis, is_new_thesis)
        """
        with self._lock:
            sym_clean = symbol.replace('/', '').replace(':', '').replace('-', '').strip().upper()
            dir_upper = direction.strip().upper()
            if dir_upper.startswith("SHOR"):
                dir_upper = "SHORT"
            elif dir_upper.startswith("LONG"):
                dir_upper = "LONG"

            pair_key = (sym_clean, dir_upper)
            norm_hz = normalize_horizon(horizon)
            ev_val = float(expected_net_return or 0.0)

            existing_thesis_id = self.symbol_direction_map.get(pair_key)
            if existing_thesis_id and existing_thesis_id in self.active_theses:
                thesis = self.active_theses[existing_thesis_id]
                # Increment signals and confirm horizon
                if norm_hz not in thesis.participating_horizons:
                    thesis.participating_horizons.append(norm_hz)
                    # Sort participating horizons in canonical timeframe order
                    thesis.participating_horizons.sort(key=lambda h: HORIZON_SORT_ORDER.get(h, 99))
                    thesis.signals_count += 1
                    # Dynamic strength scaling: confirmed across multiple horizons
                    thesis.thesis_strength = min(100.0, thesis.thesis_strength + 5.0)

                if signal_id and signal_id not in thesis.signals:
                    thesis.signals.append(signal_id)

                thesis.thesis_expected_net_return = max(thesis.thesis_expected_net_return, ev_val)
                thesis.highest_net_ev = max(thesis.highest_net_ev, ev_val)
                thesis.active_signals_count = len(thesis.signals) if thesis.signals else thesis.signals_count
                thesis.is_active = True
                return thesis, False

            # Create fresh Trade Thesis
            now_utc = datetime.now(timezone.utc)
            # Default to stable canonical thesis identifier
            th_id = self.generate_thesis_id(sym_clean, dir_upper, strategy, dt_str)

            new_thesis = TradeThesis(
                thesis_id=th_id,
                symbol=symbol.strip(),
                primary_direction=dir_upper,
                strategy_archetype=strategy,
                regime=regime,
                signals_count=1,
                participating_horizons=[norm_hz],
                signals=[signal_id] if signal_id else [],
                thesis_strength=75.0,
                thesis_expected_net_return=ev_val,
                highest_net_ev=ev_val,
                created_at_utc=now_utc.strftime('%Y-%m-%d %H:%M:%S UTC'),
                is_position_open=False,
                is_active=True,
                active_signals_count=1
            )

            self.active_theses[th_id] = new_thesis
            self.symbol_direction_map[pair_key] = th_id
            return new_thesis, True

    def can_open_position(self, thesis_id: str, symbol: Optional[str] = None) -> Tuple[bool, str]:
        """
        Section 27: Enforces max_thesis_exposure = 1 position.
        Prevents opening duplicate trades on the same thesis cluster.
        """
        with self._lock:
            thesis = self.active_theses.get(thesis_id)
            if not thesis:
                # If lookup by direct ID misses, check if symbol-direction has open position
                if symbol:
                    s_clean = symbol.replace('/', '').replace(':', '').replace('-', '').strip().upper()
                    for th in self.active_theses.values():
                        th_s_clean = th.symbol.replace('/', '').replace(':', '').replace('-', '').strip().upper()
                        if th_s_clean == s_clean and th.is_position_open:
                            return False, f"Symbol {symbol} already has an open executed position (Max 1 per asset rule)"
                return True, "Eligible"

            if thesis.is_position_open:
                return False, f"Thesis {thesis_id} already has an open executed position (Max 1 per thesis rule)"

            return True, "Eligible"

    def mark_position_opened(self, thesis_id: str, trade_id: Optional[str] = None):
        """Marks that an executed position is active on this thesis."""
        with self._lock:
            thesis = self.active_theses.get(thesis_id)
            if thesis:
                thesis.is_position_open = True
                thesis.is_active = True

    def mark_position_closed(
        self,
        thesis_id: str,
        outcome: Optional[str] = None,
        exit_price: Optional[float] = None,
        pnl_pct: Optional[float] = None
    ):
        """Marks that the position on this thesis has closed, releasing the execution cap."""
        with self._lock:
            thesis = self.active_theses.get(thesis_id)
            if thesis:
                thesis.is_position_open = False
                if exit_price:
                    thesis.current_price = exit_price
                if pnl_pct is not None:
                    thesis.unrealized_net_pnl_pct = pnl_pct

    def resolve_thesis(self, thesis_id: str):
        """Marks a thesis as resolved when all participating signals have reached terminal outcomes."""
        with self._lock:
            thesis = self.active_theses.get(thesis_id)
            if thesis:
                thesis.is_active = False
                thesis.is_position_open = False
                thesis.active_signals_count = 0
                th_clean = thesis.symbol.replace('/', '').replace(':', '').replace('-', '').strip().upper()
                pair_key = (th_clean, thesis.primary_direction.strip().upper())
                if self.symbol_direction_map.get(pair_key) == thesis_id:
                    del self.symbol_direction_map[pair_key]

    def get_thesis(self, thesis_id: str) -> Optional[TradeThesis]:
        """Thread-safe retrieval of a trade thesis by ID."""
        with self._lock:
            return self.active_theses.get(thesis_id)

    def get_all_theses(self) -> List[Dict[str, Any]]:
        """Returns list of all active and resolved theses formatted for API and dashboard."""
        with self._lock:
            out = []
            for t in self.active_theses.values():
                out.append({
                    "thesis_id": t.thesis_id,
                    "symbol": t.symbol,
                    "direction": t.primary_direction,
                    "strategy_archetype": t.strategy_archetype,
                    "regime": t.regime,
                    "signals_count": t.signals_count,
                    "participating_horizons": list(t.participating_horizons),
                    "signals": list(t.signals),
                    "thesis_strength": t.thesis_strength,
                    "thesis_expected_net_return": t.thesis_expected_net_return,
                    "highest_net_ev": t.highest_net_ev,
                    "created_at_utc": t.created_at_utc,
                    "is_position_open": t.is_position_open,
                    "is_active": t.is_active,
                    "active_signals_count": t.active_signals_count,
                    "current_price": t.current_price,
                    "unrealized_net_pnl_pct": t.unrealized_net_pnl_pct,
                    "mfe_pct": t.mfe_pct,
                })
            # Sort active first, then newest
            out.sort(key=lambda x: (1 if x["is_active"] else 0, x["created_at_utc"]), reverse=True)
            return out

    def save_theses_to_disk(self):
        """Atomically persists all clustered theses to JSON."""
        try:
            os.makedirs(self.export_dir, exist_ok=True)
            cache_file = os.path.join(self.export_dir, "trade_theses.json")
            tmp_file = f"{cache_file}.tmp_{os.getpid()}_{threading.get_ident()}"
            with self._lock:
                theses_data = self.get_all_theses()
                payload = {
                    "last_updated_utc": datetime.now(timezone.utc).isoformat(),
                    "total_theses": len(theses_data),
                    "active_theses_count": sum(1 for t in theses_data if t["is_active"]),
                    "theses": theses_data
                }
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp_file, cache_file)
        except Exception:
            pass

    def load_theses_from_disk(self):
        """Loads clustered theses from JSON on initialization."""
        try:
            cache_file = os.path.join(self.export_dir, "trade_theses.json")
            if os.path.exists(cache_file):
                with open(cache_file, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                theses_list = payload.get("theses", [])
                with self._lock:
                    for td in theses_list:
                        th_id = td.get("thesis_id")
                        if not th_id:
                            continue
                        th = TradeThesis(
                            thesis_id=th_id,
                            symbol=td.get("symbol", ""),
                            primary_direction=td.get("direction", "LONG"),
                            strategy_archetype=td.get("strategy_archetype", "MOMENTUM_TREND"),
                            regime=td.get("regime", "RANGE"),
                            signals_count=int(td.get("signals_count", 1)),
                            participating_horizons=td.get("participating_horizons", []),
                            signals=td.get("signals", []),
                            thesis_strength=float(td.get("thesis_strength", 75.0)),
                            thesis_expected_net_return=float(td.get("thesis_expected_net_return", 0.85)),
                            highest_net_ev=float(td.get("highest_net_ev", td.get("thesis_expected_net_return", 0.85))),
                            created_at_utc=td.get("created_at_utc", ""),
                            is_position_open=bool(td.get("is_position_open", False)),
                            is_active=bool(td.get("is_active", True)),
                            active_signals_count=int(td.get("active_signals_count", 0)),
                            current_price=float(td.get("current_price", 0.0)),
                            unrealized_net_pnl_pct=float(td.get("unrealized_net_pnl_pct", 0.0)),
                            mfe_pct=float(td.get("mfe_pct", 0.0))
                        )
                        self.active_theses[th_id] = th
                        if th.is_active:
                            th_clean = th.symbol.replace('/', '').replace(':', '').replace('-', '').strip().upper()
                            pair_key = (th_clean, th.primary_direction.strip().upper())
                            self.symbol_direction_map[pair_key] = th_id
        except Exception:
            pass

    def sync_from_audit_records(
        self,
        records: List[Dict[str, Any]],
        open_positions: Optional[List[Dict[str, Any]]] = None
    ):
        """
        Reconciles in-memory theses directly from authoritative CSV records and open ledger positions.
        Ensures all multi-horizon signals on the same coin and direction are cleanly clustered.
        """
        with self._lock:
            for r in records:
                sid = r.get("signal_id")
                if not sid:
                    continue
                sym = str(r.get("symbol", "")).strip().upper()
                dirn = str(r.get("direction", "LONG")).strip().upper()
                if dirn.startswith("SHOR"):
                    dirn = "SHORT"
                elif dirn.startswith("LONG"):
                    dirn = "LONG"

                hz = normalize_horizon(r.get("horizon"))
                strat = str(r.get("strategy_archetype") or r.get("canonical_strategy") or r.get("decision") or "MOMENTUM_TREND")
                regime = str(r.get("market_shield") or "RANGE")
                ev_val = float(r.get("expected_return_pct") or r.get("ev_net") or 0.85)

                th, _ = self.register_or_update(
                    symbol=sym,
                    direction=dirn,
                    horizon=hz,
                    strategy=strat,
                    regime=regime,
                    expected_net_return=ev_val,
                    signal_id=sid
                )

                st = str(r.get("status", "")).strip().upper()
                is_terminal = any(term in st for term in ["WON", "LOST", "STOP", "BE", "EXP", "CANCEL"])
                if is_terminal:
                    if sid in th.signals:
                        th.active_signals_count = max(0, th.active_signals_count - 1)

            # Reconcile open positions
            if open_positions:
                open_theses: Set[str] = set()
                for pos in open_positions:
                    th_id = pos.get("trade_thesis_id")
                    if th_id:
                        open_theses.add(th_id)
                    else:
                        p_sym = str(pos.get("symbol", "")).replace('/', '').replace(':', '').replace('-', '').strip().upper()
                        p_dir = str(pos.get("direction", "LONG")).strip().upper()
                        if p_dir.startswith("SHOR"):
                            p_dir = "SHORT"
                        elif p_dir.startswith("LONG"):
                            p_dir = "LONG"
                        th_key = self.symbol_direction_map.get((p_sym, p_dir))
                        if th_key:
                            open_theses.add(th_key)

                for th_id, th in self.active_theses.items():
                    if th_id in open_theses:
                        th.is_position_open = True
                        th.is_active = True
                    else:
                        th.is_position_open = False


# Global singleton instance
_GLOBAL_THESIS_ENGINE: Optional[TradeThesisEngine] = None
_GLOBAL_THESIS_LOCK = threading.RLock()


def get_thesis_engine(export_dir: Optional[str] = None) -> TradeThesisEngine:
    """Returns the shared TradeThesisEngine instance."""
    global _GLOBAL_THESIS_ENGINE
    with _GLOBAL_THESIS_LOCK:
        if _GLOBAL_THESIS_ENGINE is None:
            _GLOBAL_THESIS_ENGINE = TradeThesisEngine(export_dir=export_dir)
        return _GLOBAL_THESIS_ENGINE
