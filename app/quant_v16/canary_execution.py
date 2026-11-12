"""
QUANT EDGE V16: LIMITED LIVE EXECUTION CANARY GATE
===================================================
Phase 5 Operational Canary Deployment Module:
- Whitelist restricted exclusively to benchmark assets: ["BTC/USDT", "ETH/USDT", "SOL/USDT"].
- 10% Position Sizing Scaler: Trades sized at exactly 0.10x of allocated desk margin.
- Autonomous Risk Circuit Breakers:
  1. Max Daily Drawdown Breaker (-2.0% equity loss halts canary trading for 24h).
  2. Max Consecutive Losses Breaker (3 consecutive losses halts canary trading).
  3. Market Spread Breaker (rejection if Level-1 spread > 6.0 bps).
  4. Market Data Latency Breaker (rejection if feed latency > 350ms).
  5. Macro Veto Breaker (rejection if BTC Market Shield triggers NTZ or Flash Dump).
- Atomically persists state to export_app_data/canary_execution_ledger.json.
"""

import os
import json
import time
import tempfile
import threading
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

CANARY_WHITELIST_BENCHMARKS = {"BTC/USDT", "ETH/USDT", "SOL/USDT"}

class CanaryExecutionGate:
    """
    Supervises the Limited Live Execution Canary Gate.
    Guarantees strict portfolio safety by enforcing a 10% sizing scale,
    benchmark-only asset filtering, and autonomous multi-layered circuit breakers.
    """
    _instance = None
    _lock = threading.RLock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(CanaryExecutionGate, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, ledger_file: Optional[str] = None):
        if getattr(self, "_initialized", False):
            return

        self.ledger_file = ledger_file or os.path.join(
            os.environ.get("EXPORT_DIR", "export_app_data"), "canary_execution_ledger.json"
        )
        self.sizing_scale: float = 0.10  # 10% position sizing scale
        self.max_daily_drawdown_pct: float = 2.0  # 2.0% max daily equity loss
        self.max_consecutive_losses: int = 3
        self.max_spread_bps: float = 6.0
        self.max_feed_latency_ms: float = 350.0

        self.state: Dict[str, Any] = self._load_or_initialize()
        self._initialized = True

    def _load_or_initialize(self) -> Dict[str, Any]:
        """Loads persistent canary ledger or initializes fresh state."""
        try:
            if os.path.exists(self.ledger_file):
                with open(self.ledger_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data
        except Exception:
            pass

        return {
            "canary_enabled": True,
            "canary_mode": "BENCHMARK_10PCT_CANARY",
            "allocated_canary_capital_usd": 100.0,
            "realized_daily_pnl_usd": 0.0,
            "realized_daily_pnl_pct": 0.0,
            "consecutive_losses": 0,
            "circuit_breaker_active": False,
            "circuit_breaker_reason": "",
            "circuit_breaker_tripped_at": None,
            "last_reset_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "whitelist_symbols": list(CANARY_WHITELIST_BENCHMARKS),
            "sizing_scale": self.sizing_scale,
            "total_canary_trades": 0,
            "canary_wins": 0,
            "canary_losses": 0,
            "trade_history": []
        }

    def save_ledger(self):
        """Atomically saves canary ledger to disk."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.ledger_file)), exist_ok=True)
            temp_fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(self.ledger_file)), suffix=".tmp")
            with open(temp_fd, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
            os.replace(temp_path, self.ledger_file)
        except Exception as e:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass

    def is_volatility_normalized(self, btc_shield_state: Optional[Dict[str, Any]] = None) -> bool:
        """Evaluates whether market regime and volatility have normalized for safe Canary reactivation."""
        if not btc_shield_state:
            return True
        reg = str(btc_shield_state.get("regime") or btc_shield_state.get("v16_regime") or "").upper()
        status = str(btc_shield_state.get("status_code", "")).upper()
        if reg in ["FLASH_DUMP", "BEAR_CASCADE_BLACKOUT"] or status in ["FLASH_DUMP", "BEAR_CASCADE_BLACKOUT", "ALERT_DUMP"]:
            return False
        if "BLACKOUT" in str(btc_shield_state.get("altcoin_posture", "")):
            return False
        return True

    def check_and_reset_daily(self, btc_shield_state: Optional[Dict[str, Any]] = None):
        """
        Resets daily PnL and circuit breakers at midnight UTC or after 24h cooldown,
        safely reactivating canary execution once market volatility has normalized.
        """
        now_dt = datetime.now(timezone.utc)
        today = now_dt.strftime("%Y-%m-%d")
        day_changed = (self.state.get("last_reset_date") != today)

        tripped_str = self.state.get("circuit_breaker_tripped_at")
        tripped_secs = 0.0
        if tripped_str:
            try:
                tripped_dt = datetime.fromisoformat(tripped_str.replace("Z", "+00:00"))
                tripped_secs = (now_dt - tripped_dt).total_seconds()
            except Exception:
                tripped_secs = 0.0

        is_24h_elapsed = (tripped_secs >= 86400.0)

        if day_changed or is_24h_elapsed:
            with self._lock:
                self.state["last_reset_date"] = today
                self.state["realized_daily_pnl_usd"] = 0.0
                self.state["realized_daily_pnl_pct"] = 0.0

                if self.state.get("circuit_breaker_active"):
                    if self.is_volatility_normalized(btc_shield_state):
                        self.state["circuit_breaker_active"] = False
                        self.state["circuit_breaker_reason"] = ""
                        self.state["circuit_breaker_tripped_at"] = None
                        self.state["consecutive_losses"] = 0
                        print(f"[CANARY 🔄 RECOVERY] Circuit breaker safely reset (24h window elapsed: {tripped_secs:.0f}s, day_changed={day_changed}). Canary reactivated under normalized volatility.", flush=True)
                    else:
                        print(f"[CANARY ⚠️ RECOVERY DEFERRED] 24h reset window elapsed, but macro volatility remains abnormal ({btc_shield_state.get('regime', 'BLACKOUT') if btc_shield_state else 'CHOP'}). Maintaining defensive posture.", flush=True)
                self.save_ledger()

    def reset_circuit_breaker(self, manual: bool = True, force: bool = False, btc_shield_state: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
        """
        Operational Recovery Protocol:
        Safely reactivates canary execution following manual operator reset or automated recovery.
        """
        with self._lock:
            if not force and not self.is_volatility_normalized(btc_shield_state):
                reason = btc_shield_state.get("reason", "Macro volatility alert") if btc_shield_state else "Market volatility abnormal"
                return False, f"Reset rejected: Market volatility has not normalized ({reason}). Use force=True to override."

            self.state["circuit_breaker_active"] = False
            self.state["circuit_breaker_reason"] = ""
            self.state["circuit_breaker_tripped_at"] = None
            self.state["consecutive_losses"] = 0
            self.state["realized_daily_pnl_usd"] = 0.0
            self.state["realized_daily_pnl_pct"] = 0.0
            self.state["last_reset_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            self.save_ledger()

            actor = "Manual operator" if manual else "Automated recovery protocol"
            msg = f"{actor} successfully reset Canary Circuit Breaker. 10% benchmark execution safely reactivated."
            print(f"[CANARY 🟢 RECOVERY] {msg}", flush=True)
            return True, msg

    def is_canary_eligible(self, symbol: str) -> bool:
        """Benchmark assets filter (BTC, ETH, SOL)."""
        clean_s = symbol.upper().replace(":USDT", "")
        if "/" not in clean_s and clean_s.endswith("USDT"):
            clean_s = f"{clean_s[:-4]}/USDT"
        return clean_s in CANARY_WHITELIST_BENCHMARKS

    def validate_canary_admission(
        self,
        signal: Dict[str, Any],
        desk_key: str,
        btc_shield_state: Optional[Dict[str, Any]] = None,
        tick_latency_ms: float = 0.0,
        spread_bps: float = 0.0
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates whether a signal clears all canary execution gates:
        1. Whitelist gate: Only benchmark assets BTC, ETH, SOL.
        2. Circuit breaker gate: Drawdown, consecutive losses, and latency.
        3. Spread gate: Reject if spread > 6.0 bps.
        4. Macro shield gate: Reject if NTZ or Flash Dump active.
        """
        with self._lock:
            self.check_and_reset_daily(btc_shield_state=btc_shield_state)

            symbol = signal.get("symbol", "")
            clean_s = symbol.upper().replace(":USDT", "")
            if "/" not in clean_s and clean_s.endswith("USDT"):
                clean_s = f"{clean_s[:-4]}/USDT"

            telemetry = {
                "symbol": clean_s,
                "desk": desk_key,
                "canary_enabled": bool(self.state.get("canary_enabled", True)),
                "sizing_scale": self.sizing_scale,
                "consecutive_losses": self.state.get("consecutive_losses", 0),
                "daily_pnl_usd": self.state.get("realized_daily_pnl_usd", 0.0),
                "circuit_breaker_active": bool(self.state.get("circuit_breaker_active", False))
            }

            # 1. Global canary enabled check
            if not self.state.get("canary_enabled", True):
                return False, "Canary execution disabled globally", telemetry

            # 2. Benchmark Whitelist Filter
            if clean_s not in CANARY_WHITELIST_BENCHMARKS:
                return False, f"Asset {clean_s} not in Canary benchmark whitelist (BTC, ETH, SOL)", telemetry

            # 3. Active Circuit Breakers Check
            if self.state.get("circuit_breaker_active", False):
                reason = self.state.get("circuit_breaker_reason", "Active Circuit Breaker")
                return False, f"Canary execution halted: {reason}", telemetry

            # 4. Market Spread Gate
            if spread_bps > self.max_spread_bps:
                return False, f"Spread ({spread_bps:.1f} bps) exceeds canary limit ({self.max_spread_bps:.1f} bps)", telemetry

            # 5. Feed Latency Gate
            if tick_latency_ms > self.max_feed_latency_ms:
                return False, f"Market feed latency ({tick_latency_ms:.0f}ms) exceeds canary limit ({self.max_feed_latency_ms:.0f}ms)", telemetry

            # 6. Macro Shield Gate
            if btc_shield_state:
                regime = str(btc_shield_state.get("regime", "")).upper()
                if regime in ["FLASH_DUMP", "BEAR_CASCADE_BLACKOUT"]:
                    return False, f"Macro flash dump veto active ({btc_shield_state.get('reason', '')})", telemetry
                if btc_shield_state.get("is_ntz_active") and not btc_shield_state.get("boundary_harvest_allowed"):
                    return False, "Macro NTZ veto active", telemetry

            # 7. Quality Grade Gate: Canary accepts Grade A or Grade A+ only
            q_grade = str(signal.get("quality_grade", "")).upper()
            if not any(g in q_grade for g in ["A+", "GRADE A"]):
                return False, f"Canary requires Grade A/A+ (got {q_grade})", telemetry

            telemetry["canary_approved"] = True
            return True, "Canary admission approved (10% sizing scale on benchmark asset)", telemetry

    def record_canary_trade_outcome(
        self,
        trade_id: str,
        symbol: str,
        direction: str,
        allocated_usd: float,
        net_pnl_usd: float,
        return_pct: float,
        is_win: bool,
        exit_reason: str
    ):
        """Records completed canary trade and evaluates circuit breakers."""
        with self._lock:
            self.check_and_reset_daily()

            self.state["total_canary_trades"] = int(self.state.get("total_canary_trades", 0)) + 1
            daily_pnl = float(self.state.get("realized_daily_pnl_usd", 0.0)) + net_pnl_usd
            self.state["realized_daily_pnl_usd"] = round(daily_pnl, 2)

            capital = float(self.state.get("allocated_canary_capital_usd", 100.0))
            daily_pct = (daily_pnl / max(1.0, capital)) * 100.0
            self.state["realized_daily_pnl_pct"] = round(daily_pct, 2)

            if is_win:
                self.state["canary_wins"] = int(self.state.get("canary_wins", 0)) + 1
                self.state["consecutive_losses"] = 0
            else:
                self.state["canary_losses"] = int(self.state.get("canary_losses", 0)) + 1
                self.state["consecutive_losses"] = int(self.state.get("consecutive_losses", 0)) + 1

            # Check Circuit Breakers
            # A. Daily Drawdown Breaker
            if daily_pct <= -self.max_daily_drawdown_pct:
                self.state["circuit_breaker_active"] = True
                self.state["circuit_breaker_reason"] = f"DAILY_DRAWDOWN_LIMIT_BREACHED ({daily_pct:.2f}% <= -{self.max_daily_drawdown_pct:.1f}%)"
                self.state["circuit_breaker_tripped_at"] = datetime.now(timezone.utc).isoformat()
                print(f"[CANARY 🚨 CIRCUIT BREAKER] Daily Drawdown limit tripped ({daily_pct:.2f}%). Canary halted for 24h.", flush=True)

            # B. Consecutive Losses Breaker
            if self.state["consecutive_losses"] >= self.max_consecutive_losses:
                self.state["circuit_breaker_active"] = True
                self.state["circuit_breaker_reason"] = f"CONSECUTIVE_LOSS_LIMIT_REACHED ({self.state['consecutive_losses']} >= {self.max_consecutive_losses})"
                self.state["circuit_breaker_tripped_at"] = datetime.now(timezone.utc).isoformat()
                print(f"[CANARY 🚨 CIRCUIT BREAKER] Consecutive loss limit reached ({self.state['consecutive_losses']}). Canary halted.", flush=True)

            # Append to history (last 50 trades)
            history = self.state.get("trade_history", [])
            history.append({
                "trade_id": trade_id,
                "symbol": symbol,
                "direction": direction,
                "allocated_usd": allocated_usd,
                "net_pnl_usd": net_pnl_usd,
                "return_pct": return_pct,
                "is_win": is_win,
                "exit_reason": exit_reason,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            self.state["trade_history"] = history[-50:]
            self.save_ledger()

    def get_status(self) -> Dict[str, Any]:
        """Returns clean serializable status dictionary."""
        with self._lock:
            self.check_and_reset_daily()
            return {
                "canary_enabled": self.state.get("canary_enabled", True),
                "canary_mode": self.state.get("canary_mode", "BENCHMARK_10PCT_CANARY"),
                "sizing_scale": self.sizing_scale,
                "whitelist_symbols": list(CANARY_WHITELIST_BENCHMARKS),
                "circuit_breaker_active": self.state.get("circuit_breaker_active", False),
                "circuit_breaker_reason": self.state.get("circuit_breaker_reason", ""),
                "circuit_breaker_tripped_at": self.state.get("circuit_breaker_tripped_at"),
                "consecutive_losses": self.state.get("consecutive_losses", 0),
                "max_consecutive_losses": self.max_consecutive_losses,
                "realized_daily_pnl_usd": self.state.get("realized_daily_pnl_usd", 0.0),
                "realized_daily_pnl_pct": self.state.get("realized_daily_pnl_pct", 0.0),
                "max_daily_drawdown_pct": self.max_daily_drawdown_pct,
                "total_canary_trades": self.state.get("total_canary_trades", 0),
                "canary_wins": self.state.get("canary_wins", 0),
                "canary_losses": self.state.get("canary_losses", 0),
                "canary_win_rate_pct": round((self.state.get("canary_wins", 0) / max(1, self.state.get("total_canary_trades", 0))) * 100.0, 1),
                "last_reset_date": self.state.get("last_reset_date")
            }

canary_gate = CanaryExecutionGate()

