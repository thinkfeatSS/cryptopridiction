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
    # Trailing Stop Evolution & Risk-Free Accounting
    is_risk_free: bool = False
    residual_risk_usd: float = 0.0
    locked_profit_usd: float = 0.0
    trailing_runner_rr: Optional[float] = None
    trailing_rr_ratio: str = ""
    structural_risk_reward: float = 2.0


@dataclass
class TrailingEvolutionMetrics:
    is_risk_free: bool
    residual_risk_distance: float
    residual_risk_usd: float
    locked_profit_usd: float
    structural_rr: float
    trailing_runner_rr: Optional[float]
    active_rr_ratio: str
    risk_state: str  # "STRUCTURAL_RISK", "MICRO_GUARDED", "BREAKEVEN_LOCKED", "PROFIT_BUFFER_LOCKED", "TRAILING_RUNNER"


def calculate_trailing_stop_evolution(
    entry_price: float,
    current_sl: float,
    current_price: float,
    next_target: float,
    initial_sl: float,
    initial_target: float,
    direction: str = "LONG",
    position_size_usd: float = 100.0,
    remaining_size_usd: Optional[float] = None,
    total_realized_partial_usd: float = 0.0,
    is_tp1_locked: bool = False,
    is_tp2_locked: bool = False,
    is_breakeven_locked: bool = False,
) -> TrailingEvolutionMetrics:
    """
    Quant Edge V16 Trailing Stop Evolution & Residual Risk Calculator.
    
    Invariants:
    1. Initial entry snapshot preserves immutable structural R:R (e.g. 1:2.0).
    2. Subsequent Breakeven ratchets on TP1 hit dynamically compress residual capital risk
       to zero (R -> 0).
    3. Active Trailing R:R in the terminal phase is evaluated from giveback risk vs
       remaining runner upside to prevent division-by-zero or infinite representations.
    """
    entry_p = max(1e-8, float(entry_price or 0.0))
    sl_p = float(current_sl or entry_p)
    curr_p = float(current_price or entry_p)
    target_p = float(next_target or entry_p)
    init_sl = float(initial_sl or sl_p)
    init_target = float(initial_target or target_p)
    is_long = str(direction).upper() in ["LONG", "BUY", "BULLISH"]
    rem_size = float(remaining_size_usd if remaining_size_usd is not None else position_size_usd)

    # 1. Immutable structural risk & reward geometry
    init_risk_dist = max(1e-8, abs(entry_p - init_sl))
    init_reward_dist = abs(init_target - entry_p)
    structural_rr = round(init_reward_dist / init_risk_dist, 2)

    # 2. Dynamic residual capital risk distance
    if is_long:
        # Residual capital risk is strictly distance from entry down to SL (0 if SL >= entry)
        residual_risk_dist = max(0.0, entry_p - sl_p)
        is_rf = (sl_p >= (entry_p * 0.9999)) or is_breakeven_locked or is_tp1_locked or is_tp2_locked
        locked_buffer = max(0.0, sl_p - entry_p)
    else:
        # Short residual risk is distance from entry up to SL (0 if SL <= entry)
        residual_risk_dist = max(0.0, sl_p - entry_p)
        is_rf = (sl_p <= (entry_p * 1.0001)) or is_breakeven_locked or is_tp1_locked or is_tp2_locked
        locked_buffer = max(0.0, entry_p - sl_p)

    if is_rf:
        residual_risk_dist = 0.0

    residual_risk_usd = round((residual_risk_dist / entry_p) * rem_size, 4)
    locked_profit_usd = round(((locked_buffer / entry_p) * rem_size) + float(total_realized_partial_usd or 0.0), 4)

    # 3. Dynamic operational risk state
    if not is_rf:
        if residual_risk_dist <= (0.55 * init_risk_dist):
            risk_state = "MICRO_GUARDED"
        else:
            risk_state = "STRUCTURAL_RISK"
    else:
        if is_tp2_locked or (is_tp1_locked and locked_buffer > (0.005 * entry_p)):
            risk_state = "TRAILING_RUNNER"
        elif is_tp1_locked or locked_buffer >= (0.0025 * entry_p):
            risk_state = "PROFIT_BUFFER_LOCKED"
        else:
            risk_state = "BREAKEVEN_LOCKED"

    # 4. Trailing Runner R:R in Terminal Phase (Giveback Risk vs Remaining Upside)
    giveback_risk = max(1e-6, abs(curr_p - sl_p))
    remaining_upside = max(0.0, (target_p - curr_p) if is_long else (curr_p - target_p))

    trailing_runner_rr: Optional[float] = None
    if target_p > 0 and remaining_upside > 0:
        trailing_runner_rr = round(remaining_upside / giveback_risk, 2)

    # 5. Active R:R String Format (Zero inf or ZeroDivisionError)
    if is_rf:
        if trailing_runner_rr is not None and trailing_runner_rr > 0:
            active_rr_ratio = f"1:FREE (Runner 1:{trailing_runner_rr:.1f})"
        else:
            active_rr_ratio = "RISK_FREE (LOCKED)"
    else:
        if residual_risk_dist > 0:
            current_active_rr = round(init_reward_dist / residual_risk_dist, 2)
            active_rr_ratio = f"1:{current_active_rr:.1f}"
        else:
            active_rr_ratio = "RISK_FREE (LOCKED)"

    return TrailingEvolutionMetrics(
        is_risk_free=is_rf,
        residual_risk_distance=residual_risk_dist,
        residual_risk_usd=residual_risk_usd,
        locked_profit_usd=locked_profit_usd,
        structural_rr=structural_rr,
        trailing_runner_rr=trailing_runner_rr,
        active_rr_ratio=active_rr_ratio,
        risk_state=risk_state
    )

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
        "PENDING_EVALUATION", "ACTIVE", "PENDING_LIMIT", "RESTING_LIMIT",
        "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"
    }
    if st in pending_statuses or "PENDING" in out or "AWAIT PULLBACK" in out or "AWAIT BOUNCE" in out or "RESTING" in out or "ACTIVE" in out:
        return "PENDING"

    # 2. Breakeven outcomes
    be_statuses = {
        "WON_TIER0_BE", "WON_TP1_BE", "EXPIRED_BREAKEVEN",
        "BREAKEVEN_EXP", "TIER0_BE_HIT", "BREAKEVEN", "BREAKEVEN_GUARD",
        "STOP_LOSS_BREAKEVEN", "TIER0_GUARD"
    }
    if (
        st in be_statuses
        or "BREAKEVEN" in out
        or "TIER-0" in out
        or "BREAKEVEN" in st
        or "GUARD" in st
        or "TP1 + BE RUNNER" in out
        or "EXPIRED (BE" in out
    ):
        return "BREAKEVEN"

    # 3. Won outcomes
    won_statuses = {
        "WON_TP3", "WON_TP2_TRAIL", "WON_TP2", "WON_TP1",
        "WON_TP2_EXP", "WON_TP1_EXP", "WON_EXP_PROFIT", "WON_PROFIT_EXPIRED", "WON"
    }
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
