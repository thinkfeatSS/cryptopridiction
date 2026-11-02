"""
QUANT EDGE V16: Signal Audit, Dynamic State & Event Sourcing Engine
Specifications:
- Section 9: Immutable Signal Record
- Section 10: Dynamic Trade State (Separate storage, never overwrite initial values)
- Section 12: Outcome Record (WIN_TP1, WIN_TP2, WIN_TP3, LOSS_SL, BREAKEVEN, EXPIRED, etc.)
- Section 54: Event Sourcing (SIGNAL_CREATED, ENTRY_REACHED, TP1_REACHED, SL_MOVED, etc.)
"""

import json
import os
import time
from enum import Enum
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field, fields

class SignalEventType(str, Enum):
    SIGNAL_CREATED = "SIGNAL_CREATED"
    ENTRY_REACHED = "ENTRY_REACHED"
    TP1_REACHED = "TP1_REACHED"
    BREAKEVEN_LOCKED = "BREAKEVEN_LOCKED"
    TP2_REACHED = "TP2_REACHED"
    TRAILING_STOP_ACTIVATED = "TRAILING_STOP_ACTIVATED"
    TP3_REACHED = "TP3_REACHED"
    SL_HIT = "SL_HIT"
    BREAKEVEN_HIT = "BREAKEVEN_HIT"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"

@dataclass
class SignalEvent:
    event_id: str
    signal_id: str
    event_type: SignalEventType
    timestamp_utc: str
    price_at_event: float
    detail: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ImmutableSignalRecord:
    signal_id: str
    trade_thesis_id: str
    model_version: str
    strategy_version: str
    symbol: str
    direction: str
    horizon: str
    signal_generated_at: str
    entry_price_initial: float
    tp1_initial: float
    tp2_initial: float
    tp3_initial: float
    sl_initial: float
    regime: str
    p_tp1: float
    p_tp2: float
    p_tp3: float
    p_sl: float
    expected_gross_return: float
    expected_net_return: float
    total_execution_costs: float
    risk_reward: float
    signal_score: float
    grade: str
    status: str
    liquidity_score: float = 90.0
    data_quality_score: float = 95.0

@dataclass
class DynamicTradeState:
    signal_id: str
    current_price: float
    current_sl: float
    trailing_sl: Optional[float] = None
    locked_sl: Optional[float] = None
    unrealized_net_pnl_pct: float = 0.0
    mfe_pct: float = 0.0                # Maximum Favorable Excursion
    mae_pct: float = 0.0                # Maximum Adverse Excursion
    is_tp1_locked: bool = False
    is_tp2_locked: bool = False
    status: str = "ACTIVE"
    outcome_label: str = "ACTIVE 🟢"
    updated_at_utc: str = ""
    exit_price: Optional[float] = None
    realized_return_pct: Optional[float] = None

import math

@dataclass
class TradeOutcomeRecord:
    signal_id: str
    trade_thesis_id: str
    outcome: str
    exit_price: float
    gross_return_pct: float
    net_return_pct: float
    mfe_pct: float
    mae_pct: float
    duration_seconds: float
    resolved_at_utc: str


def classify_signal_outcome(
    status: Optional[str],
    outcome_label: Optional[str] = "",
    ret_pct: Optional[float] = None
) -> str:
    """
    Standardized Quant Edge V16 Outcome Classifier.
    Returns one of: 'PENDING', 'WON', 'LOST', 'BREAKEVEN', 'EXPIRED'.

    Invariants (Rule 9):
    1. Pending/Active states are strictly PENDING. They NEVER count as Won, Lost, Breakeven, or in returns.
    2. Explicit Breakeven outcomes are strictly BREAKEVEN (not conflated with Won or Lost).
    3. Won outcomes (TP1-3, Profit Expiry) are strictly WON.
    4. Lost outcomes (SL hit, Loss Expiry) are strictly LOST.
    5. Neutral Expiry / Missed are EXPIRED.
    """
    st = str(status or "").strip().upper()
    out = str(outcome_label or "").strip().upper()

    # 1. Pending / Active trades (Strict Gate: must be evaluated first)
    pending_statuses = {
        "PENDING_EVALUATION", "ACTIVE", "PENDING_LIMIT",
        "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"
    }
    if st in pending_statuses or "PENDING" in out or "AWAIT PULLBACK" in out or "ACTIVE" in out:
        return "PENDING"

    # 2. Breakeven outcomes
    be_statuses = {
        "WON_TIER0_BE", "WON_TP1_BE", "EXPIRED_BREAKEVEN",
        "BREAKEVEN_EXP", "TIER0_BE_HIT", "BREAKEVEN"
    }
    if (
        st in be_statuses
        or "BREAKEVEN" in out
        or "TIER-0" in out
        or "TP1 + BE RUNNER" in out
        or "EXPIRED (BE" in out
    ):
        return "BREAKEVEN"

    # 3. Won outcomes
    won_statuses = {"WON_TP3", "WON_TP2_TRAIL", "WON_EXP_PROFIT", "WON_PROFIT_EXPIRED", "WON"}
    if st in won_statuses or ("WON" in out and "LOST" not in out):
        return "WON"

    # 4. Lost outcomes
    lost_statuses = {"LOST_SL", "LOST_EXP", "LOST_EXPIRED", "LOST"}
    if st in lost_statuses or ("LOST" in out and "WON" not in out) or "STOPPED" in out:
        return "LOST"

    # 5. Expired outcomes
    if "EXPIRED" in out or "EXP" in st or "MISSED" in out:
        return "EXPIRED"

    # 6. Fallback based on validated realized return if status is ambiguous but closed
    if ret_pct is not None and not (math.isnan(ret_pct) or math.isinf(ret_pct)):
        if ret_pct > 0.05:
            return "WON"
        elif ret_pct < -0.05:
            return "LOST"
        else:
            return "BREAKEVEN"

    return "PENDING"

class V16AuditManager:
    """
    Manages immutable storage, event streams, and dynamic trade state transitions.
    """

    def __init__(self, export_dir: str = "./export_app_data"):
        self.export_dir = export_dir
        os.makedirs(self.export_dir, exist_ok=True)
        self.immutable_file = os.path.join(self.export_dir, "v16_immutable_signals.json")
        self.dynamic_file = os.path.join(self.export_dir, "v16_dynamic_states.json")
        self.events_file = os.path.join(self.export_dir, "v16_signal_events.json")

        self.immutable_signals: Dict[str, ImmutableSignalRecord] = {}
        self.dynamic_states: Dict[str, DynamicTradeState] = {}
        self.events_journal: List[SignalEvent] = []

        self._load_state()

    def _load_state(self):
        try:
            immut_fields = {f.name for f in fields(ImmutableSignalRecord)}
            dyn_fields = {f.name for f in fields(DynamicTradeState)}
            if os.path.exists(self.immutable_file):
                with open(self.immutable_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for k, v in data.items():
                        if isinstance(v, dict):
                            filtered = {key: val for key, val in v.items() if key in immut_fields}
                            self.immutable_signals[k] = ImmutableSignalRecord(**filtered)
            if os.path.exists(self.dynamic_file):
                with open(self.dynamic_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for k, v in data.items():
                        if isinstance(v, dict):
                            filtered = {key: val for key, val in v.items() if key in dyn_fields}
                            self.dynamic_states[k] = DynamicTradeState(**filtered)
        except Exception as e:
            print(f"[AUDIT V16 ⚠️] Error reading state files: {e}")

    def save_state(self):
        try:
            with open(self.immutable_file + ".tmp", 'w', encoding='utf-8') as f:
                json.dump({k: asdict(v) for k, v in self.immutable_signals.items()}, f, indent=2)
            os.replace(self.immutable_file + ".tmp", self.immutable_file)

            with open(self.dynamic_file + ".tmp", 'w', encoding='utf-8') as f:
                json.dump({k: asdict(v) for k, v in self.dynamic_states.items()}, f, indent=2)
            os.replace(self.dynamic_file + ".tmp", self.dynamic_file)
        except Exception as e:
            print(f"[AUDIT V16 ⚠️] Error saving state files: {e}")

    def record_new_signal(self, immutable: ImmutableSignalRecord, dynamic: DynamicTradeState):
        """Records initial immutable snapshot and initial dynamic state."""
        self.immutable_signals[immutable.signal_id] = immutable
        self.dynamic_states[immutable.signal_id] = dynamic
        
        self.log_event(
            signal_id=immutable.signal_id,
            event_type=SignalEventType.SIGNAL_CREATED,
            price=immutable.entry_price_initial,
            detail=f"V16 Qualified Signal Created - Grade: {immutable.grade}, Net EV: {immutable.expected_net_return:+.2f}%"
        )
        self.save_state()

    def log_event(self, signal_id: str, event_type: SignalEventType, price: float, detail: str = "", metadata: Optional[Dict[str, Any]] = None):
        """Appends an event to the immutable event log."""
        now_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        ev_id = f"EV_{int(time.time()*1000)}_{signal_id[-6:]}"
        event = SignalEvent(
            event_id=ev_id,
            signal_id=signal_id,
            event_type=event_type,
            timestamp_utc=now_utc,
            price_at_event=price,
            detail=detail,
            metadata=metadata or {}
        )
        self.events_journal.append(event)
        
        # Also persist to newline-delimited event log
        try:
            with open(self.events_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(asdict(event)) + "\n")
        except Exception:
            pass

    def get_all_immutable_records(self) -> List[ImmutableSignalRecord]:
        return list(self.immutable_signals.values())

    def get_all_dynamic_states(self) -> List[DynamicTradeState]:
        return list(self.dynamic_states.values())
