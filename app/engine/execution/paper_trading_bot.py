import math
import random
import os
import sys
import json
import time
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("paper_trading_bot")

from app.config import settings
from app.engine.config import EXPORT_DIR, is_meme_coin
from app.engine.scanner.filters import UniverseFilter
from app.quant_v16.entry_confirmation import format_dynamic_precision, EntryConfirmationEngine
from app.quant_v16.validation import safe_ratio
from app.quant_v16.audit import calculate_trailing_stop_evolution

class PaperTradingBot:
    """
    Subsystem 3: Standalone High-Speed 24/7 Paper Trading Execution Bot.
    - Decoupled from heavy machine learning scanning.
    - Runs a fast 1-2s tick watcher to monitor open positions.
    - Evaluates intra-candle fills, Tier-0 Breakeven ratchets, and TP partial scaling.
    - Multi-Desk Capital Allocation:
      1. ⚡ Scalp Desk (20% allocation, 2 max slots, 2x leverage)
      2. ⏳ Day Trading Desk (35% allocation, 2 max slots, 3x leverage)
      3. 🌊 Swing Desk (45% allocation, 2 max slots, 2x leverage)
    - Realistic Binance Futures fee ($0.0405% taker with BNB discount) and funding rates.
    """

    def __init__(self, ledger_file: str = None):
        if ledger_file:
            self.ledger_file = ledger_file
        elif os.environ.get("TESTING") == "1" or "pytest" in sys.modules or "unittest" in sys.modules:
            import tempfile
            self._temp_ledger = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
            self.ledger_file = self._temp_ledger.name
        else:
            self.ledger_file = os.path.join(EXPORT_DIR, "paper_trading_ledger.json")
        self.taker_fee_rate = 0.000405 # 0.045% with 10% BNB discount
        self.enable_signal_expiry: bool = getattr(settings, "ENABLE_SIGNAL_EXPIRY", False) or (os.getenv("ENABLE_SIGNAL_EXPIRY", "false").lower() in ("true", "1", "yes"))
        self.enable_breakeven_guard: bool = getattr(settings, "ENABLE_BREAKEVEN_GUARD", False) or (os.getenv("ENABLE_BREAKEVEN_GUARD", "false").lower() in ("true", "1", "yes"))
        self.blackout_ceiling_ms: float = float(os.getenv("BLACKOUT_CEILING_MS", "8000.0"))
        self.MAX_SAFEGUARD_VOID_HOLD_SECONDS: float = 1800.0  # 30m maximum safeguard hold before auto-liquidation
        self.ABANDONED_MICRO_CAP_VOID_TIMEOUT: float = 60.0  # 60s fast auto-liquidation on abandoned/depleted micro-caps
        self._lock = threading.RLock()
        self._running = False
        self._worker_thread = None
        self.data = self._load_or_initialize()

    def _load_or_initialize(self) -> Dict[str, Any]:
        if os.path.exists(self.ledger_file):
            try:
                with open(self.ledger_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    # Automatically purge any delisted, dead, or ghost positions
                    valid_positions = []
                    purged_symbols = []
                    for pos in loaded.get("open_positions", []):
                        if str(pos.get("trade_id", "")).startswith("TEST_") or "TEST" in str(pos.get("trade_id", "")):
                            continue
                        sym = pos.get("symbol", "")
                        entry_p = float(pos.get("entry_price", 0.0))
                        if UniverseFilter.is_valid_crypto_pair(sym, price=entry_p) and entry_p > 0.0001:
                            hz = pos.get("signal_horizon") or pos.get("horizon")
                            if not hz:
                                d = str(pos.get("desk") or "").lower()
                                hz = "15M" if d == "scalp" else ("24H" if d in ["swing", "macro"] else "1H")
                            pos["horizon"] = hz
                            pos["signal_horizon"] = hz
                            if not pos.get("opened_at") and pos.get("opened_at_utc"):
                                pos["opened_at"] = pos["opened_at_utc"]
                            if not pos.get("opened_at_utc") and pos.get("opened_at"):
                                pos["opened_at_utc"] = pos["opened_at"]
                            valid_positions.append(pos)
                        else:
                            purged_symbols.append(sym)

                    # Resynchronize desk targets to 5-slot Scalp allocation:
                    # Scalp Desk (5M-30M): $500 (50%), 5 slots, 2x leverage (strictly Grade A / A+ with EVnet >= 0.25%)
                    # Day Desk (1H-4H): $250 (25%), 2 slots, 3x leverage
                    # Swing Desk (12H-30D): $250 (25%), 2 slots, 2x leverage
                    desks = loaded.get("desks", {})
                    if "swing" in desks:
                        desks["swing"]["allocated_usd"] = float(os.getenv("SWING_DESK_ALLOCATED_USD", "300.0"))
                        desks["swing"]["max_slots"] = int(os.getenv("SWING_DESK_MAX_SLOTS", "3"))
                        desks["swing"]["leverage"] = 2
                    if "day" in desks:
                        desks["day"]["allocated_usd"] = float(os.getenv("DAY_DESK_ALLOCATED_USD", "200.0"))
                        desks["day"]["max_slots"] = int(os.getenv("DAY_DESK_MAX_SLOTS", "2"))
                        desks["day"]["leverage"] = 3
                    if "scalp" in desks:
                        desks["scalp"]["allocated_usd"] = float(os.getenv("SCALP_DESK_ALLOCATED_USD", "500.0"))
                        desks["scalp"]["max_slots"] = int(os.getenv("SCALP_DESK_MAX_SLOTS", "5"))
                        desks["scalp"]["leverage"] = 2
                    for d_key, d_val in desks.items():
                        d_val["active_slots"] = sum(1 for p in valid_positions if p.get("desk") == d_key)
                    loaded["desks"] = desks

                    if purged_symbols:
                        print(f"[PAPER BOT 🧹 PURGE] Evicted delisted/ghost positions from ledger: {purged_symbols}")
                        loaded["open_positions"] = valid_positions

                    # Ensure both closed_trades and closed_trades_history exist and are synchronized
                    c_trades = loaded.get("closed_trades") or []
                    c_hist = loaded.get("closed_trades_history") or []
                    combined = c_hist if len(c_hist) >= len(c_trades) else c_trades

                    # Deduplicate by trade_id
                    seen_tids = set()
                    unique_trades = []
                    for ct in combined:
                        tid = ct.get("trade_id")
                        if tid and tid in seen_tids:
                            continue
                        if tid:
                            seen_tids.add(tid)
                        unique_trades.append(ct)

                    # Normalize all closed trade records
                    normalized_trades = []
                    for ct in unique_trades:
                        rpnl = ct.get("realized_pnl_usd") if ct.get("realized_pnl_usd") is not None else ct.get("net_pnl_usd", 0.0)
                        rpct = ct.get("realized_pnl_pct") if ct.get("realized_pnl_pct") is not None else ct.get("return_pct", 0.0)
                        fee = ct.get("binance_fee_usd") if ct.get("binance_fee_usd") is not None else ct.get("fees_usd", 0.0)
                        outc = ct.get("outcome")
                        if not outc:
                            outc = "WON" if rpnl > 0.05 else ("LOST" if rpnl < -0.05 else "BREAKEVEN")
                        
                        hz = ct.get("horizon") or ct.get("signal_horizon")
                        if not hz:
                            tid = str(ct.get("trade_id", ""))
                            for part in tid.split("_"):
                                if part in ["15M", "1H", "4H", "24H", "1D"]:
                                    hz = part
                                    break
                        if not hz:
                            d = ct.get("desk", "")
                            hz = "15M" if d == "scalp" else ("24H" if d in ["swing", "macro"] else "1H")

                        dur = ct.get("duration_str")
                        o_at = ct.get("opened_at") or ct.get("opened_at_utc", "")
                        c_at = ct.get("closed_at") or ct.get("closed_at_utc", "")
                        if not dur and o_at and c_at:
                            try:
                                odt = datetime.fromisoformat(o_at.replace("Z", "+00:00"))
                                cdt = datetime.fromisoformat(c_at.replace("Z", "+00:00"))
                                diff = int((cdt - odt).total_seconds())
                                dh = diff // 3600
                                dm = (diff % 3600) // 60
                                ds = diff % 60
                                dur = f"{dh}h {dm}m {ds}s" if dh > 0 else (f"{dm}m {ds}s" if dm > 0 else f"{ds}s")
                            except Exception:
                                dur = "N/A"

                        norm_rec = dict(ct)
                        norm_rec["outcome"] = outc
                        norm_rec["horizon"] = hz
                        norm_rec["duration_str"] = dur or "N/A"
                        norm_rec["realized_pnl_usd"] = round(float(rpnl), 2)
                        norm_rec["net_pnl_usd"] = round(float(rpnl), 2)
                        norm_rec["realized_pnl_pct"] = round(float(rpct), 2)
                        norm_rec["return_pct"] = round(float(rpct), 2)
                        norm_rec["binance_fee_usd"] = round(float(fee), 4)
                        norm_rec["fees_usd"] = round(float(fee), 4)
                        norm_rec["opened_at"] = o_at
                        norm_rec["opened_at_utc"] = o_at
                        norm_rec["closed_at"] = c_at
                        norm_rec["closed_at_utc"] = c_at
                        normalized_trades.append(norm_rec)

                    loaded["closed_trades"] = normalized_trades
                    loaded["closed_trades_history"] = normalized_trades
                    loaded.setdefault("shadow_positions", [])
                    return loaded
            except Exception as e:
                logger.warning(f"[PAPER BOT ⚠️] Failed to load persistent state from {self.ledger_file}: {e}")

        # Initial baseline state
        return {
            "initial_balance_usd": 1000.0,
            "current_balance_usd": 1000.0,
            "total_equity_usd": 1000.0,
            "realized_pnl_usd": 0.0,
            "total_fees_paid_usd": 0.0,
            "win_rate_pct": 0.0,
            "total_trades_count": 0,
            "winning_trades_count": 0,
            "losing_trades_count": 0,
            "desks": {
                "scalp": {"name": "⚡ Scalp Desk", "allocated_usd": float(os.getenv("SCALP_DESK_ALLOCATED_USD", "500.0")), "max_slots": int(os.getenv("SCALP_DESK_MAX_SLOTS", "5")), "active_slots": 0, "leverage": 2},
                "day": {"name": "⏳ Day Trading Desk", "allocated_usd": float(os.getenv("DAY_DESK_ALLOCATED_USD", "200.0")), "max_slots": int(os.getenv("DAY_DESK_MAX_SLOTS", "2")), "active_slots": 0, "leverage": 3},
                "swing": {"name": "🌊 Swing Desk", "allocated_usd": float(os.getenv("SWING_DESK_ALLOCATED_USD", "300.0")), "max_slots": int(os.getenv("SWING_DESK_MAX_SLOTS", "3")), "active_slots": 0, "leverage": 2}
            },
            "open_positions": [],
            "shadow_positions": [],
            "closed_trades": [],
            "closed_trades_history": [],
            "last_updated_utc": datetime.now(timezone.utc).isoformat()
        }

    def save_ledger(self):
        with self._lock:
            temp = f"{self.ledger_file}.{threading.get_ident()}.{time.time_ns()}.tmp"
            try:
                # Protect production ledger against synthetic test records leaking from tests
                if os.path.basename(self.ledger_file) == "paper_trading_ledger.json":
                    self.data["open_positions"] = [
                        p for p in self.data.get("open_positions", [])
                        if not str(p.get("trade_id", "")).startswith("TEST_") and "TEST" not in str(p.get("trade_id", ""))
                    ]
                self.data["last_updated_utc"] = datetime.now(timezone.utc).isoformat()
                with open(temp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, indent=2)
                os.replace(temp, self.ledger_file)
            except Exception as e:
                print(f"[PAPER BOT ERROR] Failed saving ledger: {e}")
            finally:
                if os.path.exists(temp):
                    try:
                        os.remove(temp)
                    except Exception as ex:
                        logger.debug(f"[PAPER BOT] Failed removing temp file {temp}: {ex}")

    def resolve_desk(self, timeframe_or_horizon: str) -> str:
        tf = str(timeframe_or_horizon).lower().strip()
        desks = self.data.get("desks", {})

        # 1. 24H / Daily Swing Desk (Check first so '4h' does not false-match '24h')
        if any(x in tf for x in ["24h", "1d", "12h", "7d", "15d", "30d", "daily", "swing", "macro"]):
            if "swing" in desks:
                return "swing"
            if "macro" in desks:
                return "macro"
            return list(desks.keys())[-1]

        # 2. 1H / Intraday Desk
        if any(x in tf for x in ["1h", "4h", "day", "intraday"]):
            if "day" in desks:
                return "day"
            if "intraday" in desks:
                return "intraday"
            return list(desks.keys())[0]

        # 3. 15M / Scalp Desk
        if any(x in tf for x in ["5m", "15m", "30m", "scalp"]):
            if "scalp" in desks:
                return "scalp"
            return list(desks.keys())[0]

        # Default fallback
        if "day" in desks:
            return "day"
        if "intraday" in desks:
            return "intraday"
        return list(desks.keys())[0]

    def calculate_effective_rr(
        self,
        entry_p: float,
        tp1_p: float,
        sl_p: float,
        spread_bps: float,
        volume_24h_usd: float = 0.0,
        tick_latency_ms: float = 0.0,
        is_limit: bool = False
    ) -> Tuple[float, float, float]:
        """
        Calculates effective Risk-to-Reward ratio accounting for spread widening,
        slippage dampening, and execution friction during flash liquidity voids.
        """
        if entry_p <= 0 or tp1_p <= 0 or sl_p <= 0 or entry_p == sl_p:
            return 0.0, 0.0, 0.0

        gross_reward = abs(tp1_p - entry_p)
        gross_risk = abs(entry_p - sl_p)

        # 1. Spread Drag: Full spread crossed on round-trip (half entry + half exit) or exit-only for limits
        spread_rate = (float(spread_bps) / 10000.0) if not is_limit else (float(spread_bps) / 20000.0)

        # 2. Dynamic Slippage Dampener scaled by 24h liquidity and network latency
        low_cap_factor = max(1.0, math.sqrt(15_000_000.0 / max(1_000_000.0, volume_24h_usd))) if volume_24h_usd > 0 else 1.0
        lat_factor = 1.0 + min(1.5, max(0.0, tick_latency_ms - 300.0) / 1000.0)

        entry_slip_rate = 0.0 if is_limit else (0.0003 * low_cap_factor * lat_factor)
        exit_slip_rate = 0.0004 * low_cap_factor * lat_factor

        total_friction_rate = spread_rate + entry_slip_rate + exit_slip_rate
        friction_drag = total_friction_rate * entry_p

        net_reward = max(0.0, gross_reward - friction_drag)
        net_risk = gross_risk + friction_drag
        effective_rr = round(net_reward / max(1e-8, net_risk), 2)

        return effective_rr, net_reward, net_risk

    def admit_signal(self, signal: Dict[str, Any], btc_shield_state: Optional[Dict[str, Any]] = None) -> bool:
        """
        Executes a paper trade strictly following the Signal Generation System.
        Enforces:
        0. STRICT NO TRADE ZONE (NTZ) GATING:
           - NEVER place trades when Macro No Trade Zone is active (BTC squeeze/blackout/cascade).
           - NEVER place trades when signal has is_ntz_active == True or signal_status indicates NO_TRADE_ZONE.
        1. Signal must be active (is_trade_active == True, signal_status == 'ACTIVE_SIGNAL').
        2. Signal horizon must be strictly 15M (Scalp), 1H (Intraday), or 24H (Daily Swing).
        3. Dominant direction must be LONG or SHORT (NO_TRADE, HOLD_VETOED, and WAITING rejected).
        4. Strict price invariants: SL < Entry < TP for LONG, SL > Entry > TP for SHORT.
        5. Position cap: max slots per desk, exactly 1 active trade per symbol.
        """
        with self._lock:
            # 0a. Reject if Macro No Trade Zone or Partition Outage is active
            if btc_shield_state:
                if btc_shield_state.get("is_partition_stale") or btc_shield_state.get("is_global_outage"):
                    print("[PAPER BOT 🛑 NTZ REJECT] Rejected trade entry: Global multi-exchange outage / partition defense active.")
                    return False
                if btc_shield_state.get("regime") == "FLASH_DUMP" or btc_shield_state.get("status_code") == "BEAR_CASCADE_BLACKOUT":
                    print(f"[PAPER BOT 🛑 NTZ REJECT] Rejected trade entry: BTC regime is {btc_shield_state.get('regime')} / {btc_shield_state.get('status_code')}.")
                    return False

                if "DEFENSIVE_CASH_ONLY" in str(btc_shield_state.get("altcoin_posture", "")):
                    print(f"[PAPER BOT 🛑 NTZ REJECT] Rejected trade entry: Altcoin posture is DEFENSIVE_CASH_ONLY.")
                    return False

                is_boundary_harvest = bool(
                    signal.get("is_range_boundary") or
                    any(k in str(signal.get("canonical_strategy") or signal.get("strategy") or "").upper() for k in ["RECTANGLE", "RANGE_BOUND", "BOUNDARY", "ORDER_BLOCK_BOUNDARY"])
                )
                allow_boundary = bool(btc_shield_state.get("boundary_harvest_allowed", False))

                if btc_shield_state.get("is_ntz_active") or btc_shield_state.get("status_code") == "NO_TRADE_ZONE" or "NO_TRADE_ZONE" in str(btc_shield_state.get("altcoin_posture", "")):
                    # Fix 1: Authorize boundary mean-reversion setups when boundary_harvest_allowed is True
                    if is_boundary_harvest and allow_boundary:
                        print(f"[PAPER BOT ⚖️ BOUNDARY HARVEST] Authorizing boundary harvest setup during chop equilibrium: {signal.get('symbol')} ({signal.get('canonical_strategy')})")
                    else:
                        print(f"[PAPER BOT 🛑 NTZ REJECT] Rejected trade entry: Macro BTC No Trade Zone is active ({btc_shield_state.get('reason')}).")
                        return False

                # 0b. BTC Shield Beta Directional Veto Gate (Strict Market Physics Alignment)
                dir_check = str(signal.get("direction") or signal.get("dominant_direction") or "").upper() if signal else ""
                alt_longs_ok = btc_shield_state.get("altcoin_longs_allowed", True)
                alt_shorts_ok = btc_shield_state.get("altcoin_shorts_allowed", True)

                if dir_check == "LONG" and not alt_longs_ok:
                    reg_lbl = btc_shield_state.get("regime") or btc_shield_state.get("v16_regime") or "BEAR_TREND"
                    print(f"[PAPER BOT 🛑 BETA VETO] Blocked LONG entry for {signal.get('symbol')}: BTC Beta Shield ({reg_lbl}) strictly disallows altcoin longs.")
                    return False

                if dir_check == "SHORT" and not alt_shorts_ok:
                    reg_lbl = btc_shield_state.get("regime") or btc_shield_state.get("v16_regime") or "BULL_TREND"
                    print(f"[PAPER BOT 🛑 BETA VETO] Blocked SHORT entry for {signal.get('symbol')}: BTC Beta Shield ({reg_lbl}) strictly disallows altcoin shorts.")
                    return False

                # 0c. BTC Chop Index Portfolio Defense Gate (Section 35 & Fix 1)
                chop_val = float(btc_shield_state.get("chop_index") or btc_shield_state.get("metrics", {}).get("chop_index") or 0.0)
                if chop_val > 61.8:
                    if is_boundary_harvest and allow_boundary:
                        # Validate that the boundary mean-reversion trade satisfies strict R:R and EV hurdles
                        e_p = float(signal.get("entry_price", 0.0) or 0.0)
                        tp_p = float(signal.get("tp1_price", 0.0) or 0.0)
                        sl_p = float(signal.get("sl_price", 0.0) or 0.0)
                        risk = abs(e_p - sl_p)
                        reward = abs(tp_p - e_p)
                        cand_rr = (reward / risk) if risk > 1e-8 else 0.0
                        cand_ev = float(signal.get("ev_net") or 0.0)
                        if cand_rr < 1.35 or cand_ev < 0.25:
                            print(f"[PAPER BOT 🛑 CHOP VETO] Blocked boundary setup on {signal.get('symbol')}: Insufficient R:R ({cand_rr:.2f} < 1.35) or EVnet ({cand_ev:.2f}% < 0.25%) during chop (CI={chop_val:.1f}).")
                            return False
                        print(f"[PAPER BOT ⚖️ BOUNDARY HARVEST] Authorizing boundary harvest setup during chop congestion (CI={chop_val:.1f}, R:R={cand_rr:.2f}, EV={cand_ev:.2f}%): {signal.get('symbol')}")
                    else:
                        print(f"[PAPER BOT 🛑 CHOP VETO] Blocked trade on {signal.get('symbol')}: BTC Chop Index ({chop_val:.1f} > 61.8) indicates market congestion. Cash preservation active.")
                        return False

            if not signal:
                return False

            # 0a. Reject Meme Coins and Speculative Shitcoins
            sym = str(signal.get("symbol", "")).upper()
            if is_meme_coin(sym):
                print(f"[PAPER BOT 🛑 MEME REJECT] Rejected trade entry for meme coin {sym}.")
                return False

            # 0b. Reject if Asset is in No Trade Zone
            if signal.get("is_ntz_active", False):
                sym = signal.get("symbol", "UNKNOWN")
                print(f"[PAPER BOT 🛑 NTZ REJECT] Rejected trade entry for {sym}: Asset No Trade Zone is active ({signal.get('ntz_reason', 'NTZ Filter')}).")
                return False

            # 0c. Reject if Macro Economic Blackout or Volatility Pause is active (NWS-01 & Macro Sentinel)
            try:
                from app.services.institutional_intelligence_service import institutional_intelligence_service
                inst_cal = institutional_intelligence_service.get_macro_economic_calendar()
                if inst_cal.get("is_volatility_pause_active"):
                    sym = signal.get("symbol", "UNKNOWN")
                    ev_name = inst_cal.get("event_name", "US Macro Event")
                    print(f"[PAPER BOT 🚨 MACRO BLACKOUT REJECT] Blocked entry for {sym}: High-impact macroeconomic release window active ({ev_name}).", flush=True)
                    return False
            except Exception as e:
                logger.debug(f"[PAPER BOT] Macro calendar check failed: {e}")

            fund_matrix = signal.get("fundamental_matrix") or {}
            macro_ev = fund_matrix.get("macro_economic_event") or signal.get("macro_economic_event") or {}
            if signal.get("is_macro_blackout") or macro_ev.get("is_volatility_pause_active"):
                sym = signal.get("symbol", "UNKNOWN")
                ev_name = macro_ev.get("event_name", "US Macro Event")
                try:
                    print(f"[PAPER BOT [MACRO REJECT]] Rejected trade entry for {sym}: High-impact macroeconomic release in progress ({ev_name}).")
                except Exception:
                    pass
                return False

            sig_status = str(signal.get("signal_status", ""))
            if "NO_TRADE_ZONE" in sig_status or "VETO" in sig_status or "WAITING" in sig_status:
                sym = signal.get("symbol", "UNKNOWN")
                print(f"[PAPER BOT 🛑 NTZ REJECT] Rejected trade entry for {sym}: Signal status is '{sig_status}'.")
                return False

            # 1. Reject inactive, vetoed, or waiting signals
            if not signal.get("is_trade_active", False) or sig_status != "ACTIVE_SIGNAL":
                return False

            # Phase 4 Microstructure Meta Gate Validation
            if signal.get("meta_passed") is False:
                sym = signal.get("symbol", "UNKNOWN")
                print(f"[PAPER BOT [META GATE]] Signal rejected for {sym}: Failed secondary meta-labeler gate")
                return False

            direction = signal.get("direction") or signal.get("dominant_direction")
            if direction not in ["LONG", "SHORT"]:
                return False

            # 2. Validate Horizon: Mapped to 15M (Scalp), 1H (Intraday), or 24H (Daily Swing)
            horizon_raw = str(signal.get("horizon") or signal.get("active_signal_horizon") or signal.get("dominant_timeframe") or "").upper()
            if not any(h in horizon_raw for h in ["15M", "5M", "1H", "4H", "12H", "24H", "1D", "SWING", "MACRO"]):
                return False

            if "15M" in horizon_raw or "5M" in horizon_raw or "SCALP" in horizon_raw:
                norm_horizon = "15M"
            elif "24H" in horizon_raw or "1D" in horizon_raw or "SWING" in horizon_raw or "MACRO" in horizon_raw or "7D" in horizon_raw:
                norm_horizon = "24H"
            elif "1H" in horizon_raw or "4H" in horizon_raw or "12H" in horizon_raw or "DAY" in horizon_raw or "INTRADAY" in horizon_raw:
                norm_horizon = "1H"
            else:
                return False

            symbol = signal.get("symbol")
            if not symbol or is_meme_coin(symbol):
                return False

            # 2b. Strictly Reject Delisted, Inactive, Synthetic, or Dead Pairs
            entry_p = float(signal.get("entry_price", signal.get("current_price", 0.0)))
            if not UniverseFilter.is_valid_crypto_pair(symbol, price=entry_p):
                print(f"[PAPER BOT 🛑 REJECT] Rejected trade entry for {symbol}: Token is delisted, inactive, or not an active Binance spot crypto pair.")
                return False

            # 3. Position Cap: Check if position already open on symbol or trade thesis
            sig_thesis_id = signal.get("trade_thesis_id") or f"THESIS-{symbol.replace('/', '').replace(':', '').replace('-', '')}-{direction.upper()}"
            for pos in self.data.get("open_positions", []):
                if pos.get("symbol") == symbol or (sig_thesis_id and pos.get("trade_thesis_id") == sig_thesis_id):
                    return False

            # 4. Resolve Desk strictly matching the horizon
            desks = self.data.get("desks", {})
            desk_key = self.resolve_desk(norm_horizon)
            desk = desks.get(desk_key)
            if not desk:
                desk_key = list(desks.keys())[0] if desks else "default"
                desk = desks.get(desk_key, {"name": "Standard Desk", "allocated_usd": 350.0, "max_slots": 2, "leverage": 3})

            # Check desk availability with Dynamic Regime Modulation (Phase 3 & Fix 1)
            max_slots = int(desk.get("max_slots", 2))
            is_boundary_harvest = bool(
                signal.get("is_range_boundary") or
                any(k in str(signal.get("canonical_strategy") or signal.get("strategy") or "").upper() for k in ["RECTANGLE", "RANGE_BOUND", "BOUNDARY", "ORDER_BLOCK_BOUNDARY"])
            )
            allow_boundary = bool(btc_shield_state.get("boundary_harvest_allowed", False)) if btc_shield_state else False

            if btc_shield_state:
                regime = str(btc_shield_state.get("regime", "")).upper()
                if regime in ["RANGE", "CHOPPY", "COMPRESSION", "HIGH_VOLATILITY_CHOP", "RANGE_SQUEEZE"]:
                    if desk_key == "scalp":
                        is_smc_or_coiling = bool(
                            is_boundary_harvest or
                            signal.get("is_order_block_signal") or
                            signal.get("order_block_setup") or
                            signal.get("candle_trigger_confirmed") or
                            any(k in str(signal.get("canonical_strategy") or signal.get("strategy") or "").upper()
                                for k in ["COILING", "SQUEEZE", "BREAKOUT", "ORDER_BLOCK", "REVERSAL", "TURTLE_SOUP", "FVG"])
                        )
                        if is_boundary_harvest and allow_boundary:
                            max_slots = int(desk.get("max_slots", 5))
                            print(f"[PAPER BOT [REGIME GATING]] Scalp boundary harvest slot authorized ({max_slots} slots) in {regime} market regime.")
                        elif is_smc_or_coiling:
                            max_slots = int(desk.get("max_slots", 5))
                            print(f"[PAPER BOT [REGIME GATING]] Scalp institutional trigger authorized ({max_slots} slots) in {regime} market regime.")
                        else:
                            max_slots = 0
                            print(f"[PAPER BOT [REGIME GATING]] Scalp slots throttled to 0 in {regime} market regime.")
                    elif desk_key == "day":
                        max_slots = min(max_slots, 1)
                    elif desk_key == "swing":
                        max_slots = min(max_slots, 2)
                elif regime in ["BULL_TREND", "BEAR_TREND"]:
                    if desk_key == "scalp":
                        max_slots = int(desk.get("max_slots", 5))
                    elif desk_key == "swing":
                        max_slots = max(max_slots, 2)

            # 4b. Desk Quality Admission Gating (Phase 2 Canonical Alignment)
            quality_grade = str(signal.get("quality_grade") or signal.get("grade") or "").upper()
            is_grade_ok = any(g in quality_grade for g in ["A+", "GRADE A", "GRADE B", "A", "B"]) and "GRADE C" not in quality_grade
            if not is_grade_ok:
                print(f"[PAPER BOT [QUALITY GATE]] Signal rejected for {symbol}: Ineligible grade ({quality_grade})")
                return False

            # Compute true mathematical Net Expectancy dynamically from price geometry
            e_p = float(signal.get("entry_price", 0.0) or 0.0)
            tp_p = float(signal.get("tp1_price", 0.0) or 0.0)
            sl_p = float(signal.get("sl_price", 0.0) or 0.0)
            raw_win = signal.get("meta_win_prob_pct") or signal.get("meta_win_probability") or signal.get("p_tp1") or 60.0
            win_p = float(raw_win) / 100.0 if float(raw_win) > 1.0 else float(raw_win)

            if e_p > 0 and tp_p > 0 and sl_p > 0 and e_p != sl_p:
                r_gain = abs(tp_p - e_p) / e_p
                r_loss = abs(e_p - sl_p) / e_p
                gross_ev = (win_p * r_gain) - ((1.0 - win_p) * r_loss)
                friction = 0.0015  # 0.15% round-trip taker fees + slippage
                ev_net = round((gross_ev - friction) * 100.0, 2)
            else:
                raw_ev = signal.get("ev_net") or signal.get("expected_net_return") or signal.get("expected_return_pct") or 0.0
                ev_net = float(raw_ev)
                if 0.0 < ev_net <= 0.10:
                    ev_net = round(ev_net * 100.0, 2)

            conviction_score = float(signal.get("conviction") or signal.get("conviction_pct") or 80.0)

            # Dynamic Slippage Dampener & Effective R:R Guard (Flash Liquidity Void Defense)
            spread_bps = float(signal.get("spread_bps") or signal.get("effective_spread_bps") or 5.0)
            v_24h = float(signal.get("volume_24h_usd") or signal.get("volume_24h") or 0.0)
            is_limit_pending = bool(signal.get("is_limit_pending", False))

            effective_rr, net_reward, net_risk = self.calculate_effective_rr(
                entry_p=e_p,
                tp1_p=tp_p,
                sl_p=sl_p,
                spread_bps=spread_bps,
                volume_24h_usd=v_24h,
                tick_latency_ms=0.0,
                is_limit=is_limit_pending
            )

            # Strict Invariant: Effective R:R must not be degraded below 1:1.20 by spread widening or slippage
            if effective_rr < 1.20:
                print(f"[PAPER BOT 🛑 SPREAD DEGRADED R:R] Blocked entry for {sym}: Spread widening ({spread_bps:.1f} bps) degraded effective R:R ({effective_rr:.2f} < 1.20).")
                return False

            # Canonical V16 Market Opportunity Hurdle Gating (EVnet > 0.00% hurdle strictly enforced)
            is_acceptable_grade = any(g in quality_grade for g in ["A+", "GRADE A", "GRADE B", "A", "B"]) and "GRADE C" not in quality_grade
            if not is_acceptable_grade:
                print(f"[PAPER BOT [QUALITY GATE]] Rejected for {symbol}: Ineligible grade ({quality_grade})")
                return False
            if ev_net <= 0.00:
                print(f"[PAPER BOT [QUALITY GATE]] Rejected for {symbol}: Requires positive EVnet > 0.00% (got {ev_net:.2f}%)")
                return False

            # Desk Allocation & Runner Fractional Slot Accounting (Fix 4)
            desk_positions = [p for p in self.data.get("open_positions", []) if p.get("desk") == desk_key]
            active_primary_count = sum(1 for p in desk_positions if not (p.get("tp1_hit") or p.get("tp2_hit")))
            active_runner_count = sum(1 for p in desk_positions if (p.get("tp1_hit") or p.get("tp2_hit")))
            effective_desk_slots = active_primary_count + (active_runner_count * 0.25)

            if max_slots <= 0 or active_primary_count >= max_slots or effective_desk_slots >= (max_slots + 0.50):
                # Check for stagnant runner recycling if incoming signal is Grade A+
                is_recycled = False
                if "A+" in quality_grade:
                    for p_run in desk_positions:
                        if p_run.get("tp1_hit") or p_run.get("tp2_hit"):
                            opened_str = p_run.get("opened_at_utc") or p_run.get("opened_at")
                            if opened_str:
                                try:
                                    dt = datetime.fromisoformat(opened_str.replace("Z", "+00:00"))
                                    if (datetime.now(timezone.utc) - dt).total_seconds() > 7200:
                                        print(f"[PAPER BOT ♻️ RUNNER RECYCLE] Harvesting stagnant runner {p_run.get('symbol')} to free margin for Grade A+ setup {symbol}")
                                        self._harvest_stagnant_runner(p_run)
                                        is_recycled = True
                                        break
                                except Exception:
                                    pass
                if not is_recycled:
                    return False

            # Cross-Desk Archetype Concentration Guard (Fix 5.1): Max 2 concurrent positions per archetype family
            strat_key = str(signal.get("canonical_strategy") or signal.get("strategy") or "").upper()
            archetype_family = "OTHER"
            for fam in ["BREAKOUT", "BREAKDOWN", "MOMENTUM", "ORDER_BLOCK", "BREAKER", "RANGE_BOUNCE", "DIP_BUY", "RALLY_FADE", "LIQUIDITY"]:
                if fam in strat_key:
                    archetype_family = fam
                    break

            if archetype_family != "OTHER":
                same_fam_count = sum(
                    1 for p in self.data.get("open_positions", [])
                    if archetype_family in str(p.get("strategy", "") or p.get("canonical_strategy", "")).upper()
                )
                if same_fam_count >= 2:
                    return False

            # 5. Price Invariants Validation
            entry_p = float(signal.get("entry_price", signal.get("current_price", 0.0)))
            tp1_p = float(signal.get("tp1_price", 0.0))
            tp2_p = float(signal.get("tp2_price", 0.0))
            tp3_p = float(signal.get("tp3_price", 0.0))
            sl_p = float(signal.get("sl_price", 0.0))

            if entry_p <= 0 or sl_p <= 0 or tp1_p <= 0:
                return False

            if direction == "LONG":
                if not (sl_p < entry_p < tp1_p):
                    return False
            else: # SHORT
                if not (sl_p > entry_p > tp1_p):
                    return False

            # 6. Capital Allocation & Sizing (Scaled by Institutional Archetype & Fundamental Sizing Multiplier)
            alloc_mult = float(signal.get("allocation_pct", 100.0)) / 100.0
            sizing_mult = float(signal.get("sizing_multiplier") or (signal.get("fundamental_matrix") or {}).get("sizing_multiplier") or 1.0)
            # Boost sizing multiplier for confirmed LIQUIDITY_RECLAIM setups (+25% institutional edge)
            strat_str = str(signal.get("canonical_strategy") or signal.get("strategy") or signal.get("strategy_archetype") or "").upper()
            if "LIQUIDITY_RECLAIM" in strat_str:
                sizing_mult = max(sizing_mult, 1.25)

            # Pre-admission Liquidity Haircut (Fix 3):
            # Scale down position size for shallow order books (V_24h < $15M) to eliminate sub-tick gap risk
            v_24h = float(signal.get("volume_24h_usd") or signal.get("volume_24h") or 0.0)
            if 0 < v_24h < 15_000_000.0:
                liq_mult = max(0.20, min(1.0, math.sqrt(v_24h / 15_000_000.0)))
                sizing_mult = sizing_mult * liq_mult
                print(f"[PAPER BOT 💧 LIQUIDITY SIZING] {symbol} 24h vol ${v_24h:,.0f} < $15M: Sizing damped to {liq_mult:.2f}x to eliminate sub-tick gap risk.")

            # Phase 4 Cold-Start Universe Maturation & Capital Containment:
            # If coin is relying on cold-start Laplace prior or has minimal historical trade samples (< 10),
            # strictly dampen position sizing to max 0.50x to protect portfolio equity.
            meta_mtype = str(signal.get("meta_model_type", "")).upper()
            meta_samples = int(signal.get("meta_sample_size", 100) or 100)
            if "COLD_START" in meta_mtype or meta_samples < 10:
                sizing_mult = min(sizing_mult, 0.50)

            alloc_mult = max(0.20, min(1.30, alloc_mult * sizing_mult))
            alloc_usd = float(desk.get("allocated_usd", 350.0))
            allocated_margin = round((alloc_usd / max(1, max_slots)) * alloc_mult, 2)
            leverage = int(desk.get("leverage", 3))
            position_size_usd = allocated_margin * leverage
            position_units = position_size_usd / entry_p
            buy_fee = position_size_usd * self.taker_fee_rate

            is_limit_pending = bool(signal.get("is_limit_pending", False))
            optimal_limit = float(signal.get("optimal_entry_limit") or entry_p)
            entry_zone_min = float(signal.get("entry_zone_min") or min(entry_p, optimal_limit))
            entry_zone_max = float(signal.get("entry_zone_max") or max(entry_p, optimal_limit))

            pos_record = {
                "trade_id": signal.get("signal_id") or signal.get("trade_id") or f"{symbol.replace('/', '_')}_{norm_horizon}_{int(time.time())}",
                "signal_id": signal.get("signal_id") or signal.get("trade_id"),
                "trade_thesis_id": sig_thesis_id,
                "symbol": symbol,
                "desk": desk_key,
                "desk_name": desk["name"],
                "fundamental_matrix": signal.get("fundamental_matrix"),
                "archetype": signal.get("archetype", "ARCHETYPE_A_SECULAR_EXPANSION"),
                "strategy": signal.get("strategy_playbook", signal.get("strategy", "MOMENTUM_EXPANSION")),
                "headroom_pct": signal.get("headroom_pct", 0.0),
                "direction": direction,
                "leverage": leverage,
                "allocated_margin_usd": allocated_margin,
                "position_size_usd": position_size_usd,
                "position_units": position_units,
                "entry_price": optimal_limit if is_limit_pending else entry_p,
                "admission_price": float(signal.get("current_price") or entry_p),
                "current_price": float(signal.get("current_price") or entry_p),
                "optimal_entry_limit": optimal_limit,
                "entry_zone_min": entry_zone_min,
                "entry_zone_max": entry_zone_max,
                "chase_threshold_pct": float(signal.get("chase_threshold_pct", 0.40)),
                "status": "RESTING_LIMIT" if is_limit_pending else "OPEN",
                "is_limit_resting": is_limit_pending,
                "tp1_price": tp1_p,
                "tp2_price": tp2_p if tp2_p > 0 else tp1_p,
                "tp3_price": tp3_p if tp3_p > 0 else tp1_p,
                "sl_price": sl_p,
                "initial_sl_price": sl_p,
                "initial_tp1_price": tp1_p,
                "active_atr": float(signal.get("active_atr") or abs(entry_p - sl_p) / 1.5),
                "coin_beta": float(signal.get("coin_beta", 1.0)),
                "sizing_multiplier": sizing_mult,
                "peak_price_seen": optimal_limit if is_limit_pending else entry_p,
                "trough_price_seen": optimal_limit if is_limit_pending else entry_p,
                "scaling_policy": signal.get("scaling_policy", "MULTI_TRANCHE_SCALE"),
                "tp1_hit": False,
                "tp2_hit": False,
                "tp3_hit": False,
                "total_realized_partial_usd": 0.0,
                "total_gross_partial_usd": 0.0,
                "total_frictions_partial_usd": 0.0,
                "remaining_position_size_usd": position_size_usd,
                "volume_24h_usd": float(signal.get("volume_24h_usd") or 0.0),
                # Dynamic Tier-0 BE threshold: scaled by desk and range-regime awareness
                # Scalp: 0.70%, Day: 1.00%, Swing: 1.50%
                "tier0_threshold_pct": 0.70 if desk_key == "scalp" else (1.00 if desk_key in ["day", "intraday"] else 1.50),
                "is_breakeven_locked": False,
                "peak_gain_pct": 0.0,
                "unrealized_pnl_usd": 0.0,
                "unrealized_pnl_pct": 0.0,
                "entry_fee_usd": buy_fee,
                "opened_at": datetime.now(timezone.utc).isoformat(),
                "opened_at_utc": datetime.now(timezone.utc).isoformat(),
                # Strict Signal System Provenance Tracking
                "signal_origin": "SIGNAL_SYSTEM",
                "signal_horizon": norm_horizon,
                "horizon": norm_horizon,
                "signal_quality_grade": signal.get("quality_grade", "Grade A"),
                "signal_conviction": float(signal.get("conviction", 0.0)),
                "predicted_target_price": float(signal.get("predicted_target_price", tp1_p)),
                "expected_return_pct": float(signal.get("expected_return_pct", 0.0)),
                "risk_reward_ratio": signal.get("risk_reward_ratio", f"1:{effective_rr:.1f}"),
                "structural_risk_reward": signal.get("risk_reward_ratio", f"1:{effective_rr:.1f}"),
                "is_risk_free": False,
                "residual_risk_usd": round((abs(entry_p - sl_p) / entry_p) * position_size_usd, 4),
                "locked_profit_usd": 0.0,
                "trailing_runner_rr": None,
                "active_risk_reward_ratio": signal.get("risk_reward_ratio", f"1:{effective_rr:.1f}"),
                "trailing_risk_reward_ratio": signal.get("risk_reward_ratio", f"1:{effective_rr:.1f}"),
                "risk_state": "STRUCTURAL_RISK",
                "effective_rr": effective_rr,
                "spread_bps": spread_bps,
                "classifier_votes": signal.get("classifier_votes", ""),
                "regressor_votes": signal.get("regressor_votes", ""),
                "aligned_horizons": signal.get("aligned_horizons", []),
                "meta_win_probability": float(signal.get("meta_win_probability", 0.50)),
                "meta_model_type": signal.get("meta_model_type", "PER_COIN_DEDICATED"),
                "per_coin_models_active": bool(signal.get("per_coin_models_active", True)),
                "strategy": signal.get("strategy") or signal.get("canonical_strategy"),
                "canonical_strategy": signal.get("canonical_strategy") or signal.get("strategy"),
                "strategy_archetype": signal.get("strategy_archetype") or signal.get("canonical_strategy") or signal.get("strategy"),
                "market_regime": signal.get("active_regime") or signal.get("regime") or signal.get("market_regime") or signal.get("btc_shield_status"),
                "regime": signal.get("active_regime") or signal.get("regime") or signal.get("market_regime") or signal.get("btc_shield_status"),
                "pattern_name": signal.get("pattern_name") or signal.get("decision"),
                "decision": signal.get("decision"),
                "zeiierman_rank": signal.get("zeiierman_rank"),
                "zeiierman_rank_label": signal.get("zeiierman_rank_label"),
                "order_block_setup": signal.get("order_block_setup"),
                "is_nested_smc": bool(signal.get("is_nested_smc", False)),
                "htf_poi_tf": signal.get("htf_poi_tf") or (signal.get("order_block_setup") or {}).get("htf_poi_tf"),
                "order_block_zone": signal.get("order_block_zone") or (signal.get("order_block_setup") or {}).get("order_block_zone"),
                "ob_invalidation_level": self._resolve_ob_invalidation_level(signal),
                "path_probabilities": signal.get("path_probabilities", {}),
                "p_tp1_pct": signal.get("p_tp1_pct"),
                "p_tp2_pct": signal.get("p_tp2_pct"),
                "p_tp3_pct": signal.get("p_tp3_pct"),
                "p_sl_pct": signal.get("p_sl_pct"),
                "fundamental_matrix": signal.get("fundamental_matrix"),
                "composite_fundamental_score": float(signal.get("composite_fundamental_score", 0.0)),
                "news_sentiment": signal.get("news_sentiment"),
                "catalyst_event": signal.get("catalyst_event"),
                "sizing_multiplier": float(signal.get("sizing_multiplier", 1.0)),
                "microstructure_features": signal.get("microstructure_features", {}),
                "metrics": signal.get("metrics") or {},
                "is_range_boundary": bool(signal.get("is_range_boundary") or any(k in str(signal.get("canonical_strategy") or signal.get("strategy") or "").upper() for k in ["RECTANGLE", "RANGE_BOUND", "BOUNDARY", "ORDER_BLOCK_BOUNDARY"])),
                "awaiting_microstructure_inflow": False,
                "microstructure_deferral_count": 0,
                "last_microstructure_reason": "",
                "fill_obi": None,
                "fill_cvd": None,
                "fill_bid_depth_usd": None,
                "fill_ask_depth_usd": None,
                "fill_confirmation_type": None,
                # Candlestick Structure & Universal Trend Rule Tracking
                "is_higher_low_entry": bool(signal.get("is_higher_low_entry", False)),
                "is_lower_high_entry": bool(signal.get("is_lower_high_entry", False)),
                "entry_anchor_type": signal.get("entry_anchor_type"),
                "entry_anchor_price": float(signal.get("entry_anchor_price")) if signal.get("entry_anchor_price") is not None else None,
                "execution_mode": signal.get("execution_mode", "MARKET"),
                "is_candlestick_unanimous": bool(signal.get("is_candlestick_unanimous", False)),
                "candlestick_direction": signal.get("candlestick_direction"),
                "triad_structure": signal.get("triad_structure"),
            }

            # Limited Live Execution Canary Gate Integration (Fix 6)
            try:
                from app.quant_v16.canary_execution import canary_gate
                spread_bps = float(signal.get("spread_bps") or 2.0)
                is_canary, canary_reason, canary_telemetry = canary_gate.validate_canary_admission(
                    signal=signal,
                    desk_key=desk_key,
                    btc_shield_state=btc_shield_state,
                    tick_latency_ms=0.0,
                    spread_bps=spread_bps
                )
                if is_canary:
                    pos_record["is_canary_eligible"] = True
                    pos_record["canary_scale"] = 0.10
                    pos_record["canary_allocated_usd"] = round(position_size_usd * 0.10, 2)
                    print(f"[CANARY 🐥 ADMISSION APPROVED] {symbol} benchmark Canary active (10% sizing scale: ${pos_record['canary_allocated_usd']:.2f})")
                else:
                    pos_record["is_canary_eligible"] = False
                    pos_record["canary_ineligible_reason"] = canary_reason
            except Exception as e:
                pos_record["is_canary_eligible"] = False

            if "open_positions" not in self.data:
                self.data["open_positions"] = []
            self.data["open_positions"].append(pos_record)
            self.data["total_fees_paid_usd"] = float(self.data.get("total_fees_paid_usd", 0.0)) + buy_fee

            # Keep desk active slots synchronized
            if desk_key in self.data.get("desks", {}):
                self.data["desks"][desk_key]["active_slots"] = sum(1 for p in self.data.get("open_positions", []) if p.get("desk") == desk_key)

            self.save_ledger()
            if is_limit_pending:
                try:
                    print(f"[PAPER BOT [LIMIT] RESTING LIMIT] Placed Resting Order: {symbol} ({direction} {norm_horizon}) at ${optimal_limit:,.4f} (Zone: ${entry_zone_min:,.4f}-${entry_zone_max:,.4f}) on {desk['name']} | Size: ${position_size_usd:,.2f}")
                except UnicodeEncodeError:
                    safe_desk = str(desk.get('name', '')).encode('ascii', 'ignore').decode('ascii')
                    print(f"[PAPER BOT [LIMIT] RESTING LIMIT] Placed Resting Order: {symbol} ({direction} {norm_horizon}) at ${optimal_limit:,.4f} (Zone: ${entry_zone_min:,.4f}-${entry_zone_max:,.4f}) on {safe_desk} | Size: ${position_size_usd:,.2f}")
            else:
                try:
                    print(f"[PAPER BOT [EXEC] TRADE] Executed Signal Trade: {symbol} ({direction} {norm_horizon}) on {desk['name']} | Size: ${position_size_usd:,.2f} | Entry: ${entry_p:,.4f} | TP1: ${tp1_p:,.4f} | SL: ${sl_p:,.4f}")
                except UnicodeEncodeError:
                    safe_desk = str(desk.get('name', '')).encode('ascii', 'ignore').decode('ascii')
                    print(f"[PAPER BOT [EXEC] TRADE] Executed Signal Trade: {symbol} ({direction} {norm_horizon}) on {safe_desk} | Size: ${position_size_usd:,.2f} | Entry: ${entry_p:,.4f} | TP1: ${tp1_p:,.4f} | SL: ${sl_p:,.4f}")

            # Automated WhatsApp Signal Notification Dispatch for Executed Paper Trade
            try:
                from app.services.whatsapp_service import whatsapp_service
                sig_wa = dict(pos_record)
                sig_wa["is_trade_active"] = True
                sig_wa["quality_grade"] = pos_record.get("signal_quality_grade") or signal.get("quality_grade", "Grade A")
                sig_wa["conviction_pct"] = pos_record.get("signal_conviction") or signal.get("conviction", 80.0)
                sig_wa["meta_win_prob_pct"] = float(pos_record.get("meta_win_probability", 0.70)) * 100.0
                sig_wa["ev_net"] = float(pos_record.get("expected_return_pct", 0.0))
                sig_wa["risk_reward_ratio"] = pos_record.get("risk_reward_ratio", "1:2.0")
                whatsapp_service.emit_signal_created(sig_wa)
            except Exception as wa_err:
                print(f"[WHATSAPP ❌] Error emitting paper trade execution to WhatsApp: {wa_err}", flush=True)

            return True

    def _update_position_trailing_evolution(self, pos: Dict[str, Any], curr_p: float):
        """
        Updates the position's dynamic trailing evolution metrics.
        Preserves the initial structural R:R snapshot, while accounting for risk compression
        to zero (R -> 0) on breakeven / TP1 hit, and evaluating active trailing runner R:R
        against giveback risk rather than residual capital risk to avoid division-by-zero / inf.
        """
        try:
            entry_p = float(pos.get("entry_price") or curr_p)
            sl_p = float(pos.get("sl_price") or entry_p)
            init_sl = float(pos.get("initial_sl_price") or pos.get("sl_original") or sl_p)
            direction = pos.get("direction", "LONG")

            # Determine next active target
            if pos.get("tp2_hit"):
                next_target = float(pos.get("tp3_price") or pos.get("tp2_price") or entry_p)
            elif pos.get("tp1_hit"):
                next_target = float(pos.get("tp2_price") or pos.get("tp1_price") or entry_p)
            else:
                next_target = float(pos.get("tp1_price") or entry_p)

            initial_target = float(pos.get("initial_tp1_price") or pos.get("tp1_price") or next_target)
            pos_size = float(pos.get("position_size_usd") or 100.0)
            rem_size = float(pos.get("remaining_position_size_usd") or pos_size)
            realized_partial = float(pos.get("total_realized_partial_usd") or 0.0)

            evo = calculate_trailing_stop_evolution(
                entry_price=entry_p,
                current_sl=sl_p,
                current_price=curr_p,
                next_target=next_target,
                initial_sl=init_sl,
                initial_target=initial_target,
                direction=direction,
                position_size_usd=pos_size,
                remaining_size_usd=rem_size,
                total_realized_partial_usd=realized_partial,
                is_tp1_locked=bool(pos.get("tp1_hit") or "TP1" in str(pos.get("status", ""))),
                is_tp2_locked=bool(pos.get("tp2_hit") or "TP2" in str(pos.get("status", ""))),
                is_breakeven_locked=bool(pos.get("is_breakeven_locked")),
            )

            pos["is_risk_free"] = evo.is_risk_free
            pos["residual_risk_usd"] = evo.residual_risk_usd
            pos["locked_profit_usd"] = evo.locked_profit_usd
            pos["trailing_runner_rr"] = evo.trailing_runner_rr
            pos["active_risk_reward_ratio"] = evo.active_rr_ratio
            pos["trailing_risk_reward_ratio"] = evo.active_rr_ratio
            pos["risk_state"] = evo.risk_state

            if not pos.get("structural_risk_reward"):
                pos["structural_risk_reward"] = pos.get("risk_reward_ratio") or f"1:{evo.structural_rr:.1f}"

            # Defensively sanitize risk_reward_ratio so it is never "1:inf", "1:Infinity", or non-finite
            raw_cur_rr = str(pos.get("risk_reward_ratio") or "")
            if any(bad in raw_cur_rr.lower() for bad in ["inf", "infinity", "nan", "none", "1:0.0", "1:0"]):
                pos["risk_reward_ratio"] = pos["structural_risk_reward"]
        except Exception:
            pass

    def admit_shadow_signal(self, signal: Dict[str, Any], btc_shield_state: Optional[Dict[str, Any]] = None) -> bool:
        """
        Feature 5.1: Admits candidate signal whose strategy was vetoed because the strategy is PAUSED.
        Tracks position in shadow simulation mode without capital risk or desk slot consumption.
        """
        with self._lock:
            if not signal:
                return False
            
            if btc_shield_state and (btc_shield_state.get("is_partition_stale") or btc_shield_state.get("is_global_outage")):
                return False

            symbol = signal.get("symbol")
            if not symbol or is_meme_coin(symbol):
                return False

            entry_p = float(signal.get("entry_price", signal.get("current_price", 0.0)))
            if not UniverseFilter.is_valid_crypto_pair(symbol, price=entry_p) or entry_p <= 0:
                return False

            direction = signal.get("direction") or signal.get("dominant_direction")
            if direction not in ["LONG", "SHORT"]:
                return False

            horizon_raw = str(signal.get("horizon") or signal.get("active_signal_horizon") or signal.get("dominant_timeframe") or "").upper()
            if not any(h in horizon_raw for h in ["15M", "1H", "24H", "1D"]):
                return False

            norm_horizon = "15M" if "15M" in horizon_raw else ("24H" if any(x in horizon_raw for x in ["24H", "1D"]) else "1H")
            sig_thesis_id = signal.get("trade_thesis_id") or f"THESIS-{symbol.replace('/', '').replace(':', '').replace('-', '')}-{direction.upper()}"

            for pos in self.data.get("open_positions", []):
                if pos.get("symbol") == symbol or (sig_thesis_id and pos.get("trade_thesis_id") == sig_thesis_id):
                    return False
            for pos in self.data.get("shadow_positions", []):
                if pos.get("symbol") == symbol or (sig_thesis_id and pos.get("trade_thesis_id") == sig_thesis_id):
                    return False

            tp1_p = float(signal.get("tp1_price", 0.0))
            tp2_p = float(signal.get("tp2_price", 0.0))
            tp3_p = float(signal.get("tp3_price", 0.0))
            sl_p = float(signal.get("sl_price", 0.0))

            if entry_p <= 0 or sl_p <= 0 or tp1_p <= 0:
                return False

            if direction == "LONG" and not (sl_p < entry_p < tp1_p):
                return False
            if direction == "SHORT" and not (sl_p > entry_p > tp1_p):
                return False

            strategy = signal.get("canonical_strategy") or signal.get("strategy", "MOMENTUM_LONG")
            regime = signal.get("active_regime") or signal.get("regime") or (btc_shield_state.get("v16_regime") if btc_shield_state else "RANGE")

            shadow_rec = {
                "trade_id": f"SHADOW_{symbol.replace('/', '_')}_{norm_horizon}_{int(time.time()*1000)}",
                "signal_id": signal.get("signal_id") or signal.get("trade_id"),
                "trade_thesis_id": sig_thesis_id,
                "symbol": symbol,
                "desk": "shadow",
                "is_shadow": True,
                "strategy": strategy,
                "canonical_strategy": strategy,
                "regime": regime,
                "direction": direction,
                "horizon": norm_horizon,
                "signal_horizon": norm_horizon,
                "entry_price": entry_p,
                "current_price": entry_p,
                "tp1_price": tp1_p,
                "tp2_price": tp2_p if tp2_p > 0 else tp1_p,
                "tp3_price": tp3_p if tp3_p > 0 else tp1_p,
                "sl_price": sl_p,
                "peak_gain_pct": 0.0,
                "opened_at": datetime.now(timezone.utc).isoformat(),
                "opened_at_utc": datetime.now(timezone.utc).isoformat(),
                "status": "SHADOW_OPEN"
            }

            self.data.setdefault("shadow_positions", []).append(shadow_rec)
            self.save_ledger()
            try:
                print(f"[PAPER BOT 👻 SHADOW ADMIT] Admitted Shadow Simulation Trade: {symbol} ({direction} {norm_horizon}) for PAUSED strategy '{strategy}' | Entry: ${entry_p:,.4f} | TP1: ${tp1_p:,.4f} | SL: ${sl_p:,.4f}")
            except Exception:
                pass
            return True

    def _resolve_ob_invalidation_level(self, item: Dict[str, Any]) -> Optional[float]:
        """
        Dynamically derives the authoritative Order Block invalidation level for intrabar whipsaw mitigation.
        Handles Higher-Timeframe Order Blocks (4H, 24H), Nested SMC setups, and passive POIs.
        """
        if not isinstance(item, dict):
            return None

        # 1. Direct explicit invalidation level
        if item.get("ob_invalidation_level") is not None:
            try:
                val = float(item["ob_invalidation_level"])
                if val > 0:
                    return val
            except (ValueError, TypeError):
                pass

        if item.get("invalidation_level") is not None:
            try:
                val = float(item["invalidation_level"])
                if val > 0:
                    return val
            except (ValueError, TypeError):
                pass

        # 2. Extract from order_block_setup dictionary
        ob_setup = item.get("order_block_setup")
        if isinstance(ob_setup, dict):
            if ob_setup.get("invalidation_level") is not None:
                try:
                    val = float(ob_setup["invalidation_level"])
                    if val > 0:
                        return val
                except (ValueError, TypeError):
                    pass

            ob_zone = ob_setup.get("order_block_zone")
            if isinstance(ob_zone, (list, tuple)) and len(ob_zone) >= 2:
                try:
                    direction = str(item.get("direction", "LONG")).upper()
                    if direction == "LONG":
                        cand_lvl = float(ob_setup.get("sl_price") or ob_zone[0])
                    else:
                        cand_lvl = float(ob_setup.get("sl_price") or ob_zone[1])
                    if cand_lvl > 0:
                        return cand_lvl
                except (ValueError, TypeError):
                    pass

        # 3. Extract from top-level order_block_zone
        top_zone = item.get("order_block_zone")
        if isinstance(top_zone, (list, tuple)) and len(top_zone) >= 2:
            try:
                direction = str(item.get("direction", "LONG")).upper()
                if direction == "LONG":
                    cand_lvl = float(item.get("sl_price") or top_zone[0])
                else:
                    cand_lvl = float(item.get("sl_price") or top_zone[1])
                if cand_lvl > 0:
                    return cand_lvl
            except (ValueError, TypeError):
                pass

        # 4. If it is explicitly an order block strategy, nested SMC, or passive POI, fall back to structural sl_price
        strat = str(item.get("strategy") or item.get("canonical_strategy") or item.get("strategy_archetype") or "").upper()
        if "ORDER_BLOCK" in strat or item.get("is_nested_smc") or item.get("is_order_block_signal"):
            try:
                sl_val = float(item.get("sl_price") or 0.0)
                if sl_val > 0:
                    return sl_val
            except (ValueError, TypeError):
                pass

        return None

    def _create_cancellation_record(self, pos: Dict[str, Any], reason: str, detail: str, market_price: Optional[float] = None) -> Dict[str, Any]:
        """Creates a standardized cancellation record for resting limit orders."""
        now_utc = datetime.now(timezone.utc)
        mkt_p = float(market_price or pos.get("current_price") or 0.0)
        return {
            "trade_id": pos.get("trade_id"),
            "signal_id": pos.get("signal_id"),
            "symbol": pos.get("symbol"),
            "direction": pos.get("direction"),
            "horizon": pos.get("signal_horizon") or pos.get("horizon", "1H"),
            "optimal_entry_limit": pos.get("optimal_entry_limit", pos.get("entry_price")),
            "cancel_market_price": round(mkt_p, 6) if mkt_p > 0 else 0.0,
            "status": "CANCELLED",
            "cancellation_reason": reason,
            "cancellation_detail": detail,
            "cancelled_at": now_utc.isoformat(),
            "cancelled_at_utc": now_utc.isoformat()
        }

    def _archive_cancelled_order(self, rec: Dict[str, Any], desk_key: Optional[str] = None):
        """Archives a cancelled resting order and logs event."""
        if "cancelled_orders" not in self.data:
            self.data["cancelled_orders"] = []
        self.data["cancelled_orders"].append(rec)
        print(f"[PAPER BOT [CANCEL] CANCELLED] {rec['symbol']} Resting Limit Cancelled: {rec['cancellation_reason']} ({rec['cancellation_detail']})")
        self.sync_cancelled_order_to_tracker(rec)

    def on_tick(self, live_prices: Dict[str, float], is_market_partition_active: bool = False, btc_shield_state: Optional[Dict[str, Any]] = None, tick_latency_ms: float = 0.0, order_book_voids: Optional[Dict[str, Any]] = None, order_book_depths: Optional[Dict[str, Any]] = None, cvd_metrics: Optional[Dict[str, Any]] = None):
        """Evaluates live prices against open positions and resting limits with sub-second latency and impulse shields."""
        with self._lock:
            if not self.data["open_positions"]:
                return

            # Outage Position Frozen Shield: If exchange partition / global outage is active,
            # freeze stop-loss and horizon expiry to protect capital from stale/frozen executions.
            if is_market_partition_active:
                self._was_partition_active = True
                if not getattr(self, "_partition_active_since", None):
                    self._partition_active_since = time.time()
                for pos in self.data["open_positions"]:
                    pos["safeguard_state"] = "SAFEGUARD_HOLD"
                    pos["safeguard_reason"] = "GLOBAL_OUTAGE_SHIELD_ACTIVE"
                return
            else:
                outage_duration = 0.0
                if getattr(self, "_was_partition_active", False):
                    outage_duration = time.time() - (self._partition_active_since or time.time())
                    self._was_partition_active = False
                    self._partition_active_since = None
                    self._outage_recovered_ts = time.time()
                    try:
                        print(f"[PAPER BOT [OUTAGE RECOVERED]] Partition cleared after {outage_duration:.1f}s outage. Engaging post-outage gap guard.", flush=True)
                    except Exception:
                        pass

                for pos in self.data["open_positions"]:
                    if pos.get("safeguard_state") == "SAFEGUARD_HOLD" and pos.get("safeguard_reason") == "GLOBAL_OUTAGE_SHIELD_ACTIVE":
                        pos["safeguard_state"] = "ACTIVE_MONITORING"
                        pos.pop("safeguard_reason", None)

            # Dynamic Sub-Second Tick Slippage Helper for shallow order books and latency
            def _calc_tick_slip_rates(p_pos: Dict[str, Any]) -> Tuple[float, float]:
                v_24h = float(p_pos.get("volume_24h_usd") or p_pos.get("volume_24h") or 0.0)
                low_cap_factor = max(1.0, math.sqrt(15_000_000.0 / max(1_000_000.0, v_24h))) if v_24h > 0 else 1.0
                lat_factor = 1.0 + min(1.5, max(0.0, tick_latency_ms - 300.0) / 1000.0)
                entry_rate = 0.0003 * low_cap_factor * lat_factor
                exit_rate = 0.0004 * low_cap_factor * lat_factor
                return entry_rate, exit_rate

            remaining_positions = []
            for pos in self.data["open_positions"]:
                sym = pos["symbol"]
                entry_p = float(pos.get("entry_price", 0.0))
                # Auto-evict delisted, dead, or ghost pairs immediately
                if not UniverseFilter.is_valid_crypto_pair(sym, price=entry_p, allow_quarantined=True):
                    print(f"[PAPER BOT 🧹 PURGE] Evicted delisted/inactive position on tick: {sym}")
                    continue

                curr_p = live_prices.get(sym) or live_prices.get(sym.replace("/", "").replace(":USDT", ""))
                if not curr_p or curr_p <= 0:
                    remaining_positions.append(pos)
                    continue

                pos["current_price"] = curr_p
                entry_p = pos["entry_price"]
                direction = pos["direction"]
                leverage = float(pos.get("leverage", 1.0))
                norm_h = pos.get("signal_horizon") or pos.get("horizon", "1H")

                # Live Top-5 Order Book Bid / Ask Extraction for Microstructure Invalidation
                sym_depth = None
                if order_book_depths and isinstance(order_book_depths, dict):
                    sym_depth = order_book_depths.get(sym) or order_book_depths.get(sym.replace("/", "").replace(":USDT", ""))

                live_bid = None
                live_ask = None
                if sym_depth:
                    try:
                        depth_info = EntryConfirmationEngine.calculate_top5_obi(sym_depth)
                        if depth_info.get("best_bid", 0.0) > 0:
                            live_bid = float(depth_info["best_bid"])
                        if depth_info.get("best_ask", 0.0) > 0:
                            live_ask = float(depth_info["best_ask"])
                    except Exception:
                        pass

                if not live_bid or live_bid <= 0:
                    live_bid = float(live_prices.get(f"{sym}:bid") or live_prices.get(f"{sym}_bid") or live_prices.get(f"{sym.replace('/', '')}:bid") or curr_p)
                if not live_ask or live_ask <= 0:
                    live_ask = float(live_prices.get(f"{sym}:ask") or live_prices.get(f"{sym}_ask") or live_prices.get(f"{sym.replace('/', '')}:ask") or curr_p)

                # Single-Side Order Book Void Sentinel
                is_void = False
                void_reason = ""
                is_emergency_liq = False
                if order_book_voids:
                    v_entry = order_book_voids.get(sym) or order_book_voids.get(sym.replace("/", "").replace(":USDT", ""))
                    if isinstance(v_entry, dict):
                        if v_entry.get("is_void") or v_entry.get("is_order_book_void"):
                            is_void = True
                            void_reason = v_entry.get("reason") or v_entry.get("order_book_void_reason") or "Single-side order book void detected"
                            is_emergency_liq = bool(v_entry.get("emergency_liquidation") or v_entry.get("action") == "EMERGENCY_LIQUIDATION")
                    elif bool(v_entry):
                        is_void = True
                        void_reason = "Single-side order book void detected"
                elif live_prices.get(f"{sym}_book_void"):
                    is_void = True
                    void_reason = "Order book void reported in live ticker feed"

                if is_void:
                    if pos.get("is_limit_resting") or pos.get("status") == "RESTING_LIMIT":
                        canc_rec = self._create_cancellation_record(
                            pos,
                            "CANCELLED_ORDER_BOOK_VOID",
                            f"Order book void active: {void_reason}"
                        )
                        self._archive_cancelled_order(canc_rec, pos.get("desk"))
                        continue

                    # Track when position entered SAFEGUARD_HOLD for order book void
                    pos["safeguard_hold_ts"] = float(pos.get("safeguard_hold_ts") or time.time())
                    void_dur = max(0.0, time.time() - pos["safeguard_hold_ts"])

                    # Prolonged Single-Side Order Book Void / Abandoned Micro-Cap Sentinel
                    v_dict = v_entry if (order_book_voids and isinstance(v_entry, dict)) else {}
                    is_explicit_abandoned = bool(v_dict.get("is_abandoned") or v_dict.get("abandoned_token") or pos.get("is_abandoned_micro_cap"))
                    v_24h = float(pos.get("volume_24h_usd") or pos.get("volume_24h") or v_dict.get("volume_24h", 0.0) or 0.0)
                    is_depleted_volume = (0.0 < v_24h < 100_000.0) or (v_24h == 0.0 and pos.get("volume_24h_usd") is not None)

                    max_void_hold_secs = float(pos.get("max_void_hold_secs") or getattr(self, "MAX_SAFEGUARD_VOID_HOLD_SECONDS", 1800.0))
                    abandoned_timeout = float(getattr(self, "ABANDONED_MICRO_CAP_VOID_TIMEOUT", 60.0))

                    if not is_emergency_liq:
                        if void_dur >= max_void_hold_secs:
                            is_emergency_liq = True
                            pos["is_auto_abandoned_liq"] = True
                            void_reason = f"Automated emergency liquidation: Prolonged order book void ({void_dur:.1f}s >= {max_void_hold_secs:.0f}s timeout)"
                            try:
                                print(f"[PAPER BOT [AUTO-LIQUIDATION]] {sym} Auto Emergency Liquidation triggered after prolonged order book void ({void_dur:.1f}s >= {max_void_hold_secs:.0f}s).", flush=True)
                            except Exception:
                                pass
                        elif (is_explicit_abandoned or is_depleted_volume) and void_dur >= abandoned_timeout:
                            is_emergency_liq = True
                            pos["is_auto_abandoned_liq"] = True
                            void_reason = f"Automated emergency liquidation: Abandoned micro-cap book void persistent for {void_dur:.1f}s >= {abandoned_timeout:.0f}s"
                            try:
                                print(f"[PAPER BOT [AUTO-LIQUIDATION]] {sym} Auto Emergency Liquidation triggered on abandoned micro-cap ({void_dur:.1f}s >= {abandoned_timeout:.0f}s).", flush=True)
                            except Exception:
                                pass

                    if is_emergency_liq:
                        pass # Liquidated below
                    else:
                        pos["safeguard_state"] = "SAFEGUARD_HOLD"
                        pos["safeguard_reason"] = "ORDER_BOOK_VOID_ACTIVE"
                        pos["safeguard_detail"] = void_reason
                        remaining_positions.append(pos)
                        continue
                elif pos.get("safeguard_state") == "SAFEGUARD_HOLD" and pos.get("safeguard_reason") == "ORDER_BOOK_VOID_ACTIVE":
                    pos["safeguard_state"] = "ACTIVE_MONITORING"
                    pos.pop("safeguard_reason", None)
                    pos.pop("safeguard_detail", None)
                    pos.pop("safeguard_hold_ts", None)
                    pos.pop("is_auto_abandoned_liq", None)

                # Calculate elapsed time and duration
                opened_dt = None
                try:
                    opened_str = pos.get("opened_at_utc") or pos.get("opened_at")
                    if opened_str:
                        opened_dt = datetime.fromisoformat(opened_str.replace("Z", "+00:00"))
                except Exception:
                    pass

                now_utc = datetime.now(timezone.utc)
                elapsed_secs = (now_utc - opened_dt).total_seconds() if opened_dt else 0

                dur_h = int(elapsed_secs // 3600)
                dur_m = int((elapsed_secs % 3600) // 60)
                dur_s = int(elapsed_secs % 60)
                dur_str = f"{dur_h}h {dur_m}m {dur_s}s" if dur_h > 0 else (f"{dur_m}m {dur_s}s" if dur_m > 0 else f"{dur_s}s")

                # -------------------------------------------------------------
                # 1. EVALUATE RESTING LIMIT ORDERS DYNAMICALLY
                # -------------------------------------------------------------
                if pos.get("is_limit_resting") or pos.get("status") == "RESTING_LIMIT":
                    limit_p = float(pos.get("optimal_entry_limit", entry_p))

                    # A0. Macro Economic Blackout / Volatility Pause Guard (CPI/FOMC Event Blackout)
                    is_macro_pause = False
                    macro_pause_ev = ""
                    try:
                        from app.services.institutional_intelligence_service import institutional_intelligence_service
                        inst_cal = institutional_intelligence_service.get_macro_economic_calendar()
                        if inst_cal.get("is_volatility_pause_active"):
                            is_macro_pause = True
                            macro_pause_ev = inst_cal.get("event_name") or inst_cal.get("pause_reason", "US Macro Event")
                    except Exception:
                        pass

                    fund_matrix = pos.get("fundamental_matrix") or {}
                    macro_ev = fund_matrix.get("macro_economic_event") or {}
                    if macro_ev.get("is_volatility_pause_active") or pos.get("is_macro_blackout"):
                        is_macro_pause = True
                        macro_pause_ev = macro_ev.get("event_name") or "US Macro Release Window"

                    if is_macro_pause:
                        canc_rec = self._create_cancellation_record(
                            pos,
                            "CANCELLED_MACRO_EVENT_BLACKOUT",
                            f"Macro volatility blackout active ({macro_pause_ev}): resting limit cancelled to eliminate news spike blowout"
                        )
                        self._archive_cancelled_order(canc_rec, pos.get("desk"))
                        continue

                    # A. Extreme Macro Impulse / Adverse Blowout Guard
                    # Base threshold: 1.20% adverse penetration through resting limit.
                    # Hyper-Volatile Latency-Adaptive gate (Fix 7): In high-volatility events, network ping is ~150ms.
                    # If queueing latency exceeds 800ms, dynamically tighten blowout gate from 1.20% down to 0.80%:
                    base_blowout_pct = 1.20
                    if tick_latency_ms > 800.0:
                        lag_penalty = min(0.40, ((tick_latency_ms - 800.0) / 2000.0) * 0.40)
                        effective_blowout_pct = max(0.80, base_blowout_pct - lag_penalty)
                    else:
                        effective_blowout_pct = base_blowout_pct

                    if direction == "LONG":
                        adverse_p_pct = ((limit_p - curr_p) / limit_p) * 100.0
                        if adverse_p_pct > effective_blowout_pct:
                            canc_rec = self._create_cancellation_record(
                                pos,
                                "CANCELLED_EXTREME_MACRO_BLOWOUT",
                                f"Price dumped {adverse_p_pct:.2f}% through limit (Gate: {effective_blowout_pct:.2f}%, Latency: {tick_latency_ms:.0f}ms)"
                            )
                            self._archive_cancelled_order(canc_rec, pos.get("desk"))
                            continue
                    else: # SHORT
                        adverse_p_pct = ((curr_p - limit_p) / limit_p) * 100.0
                        if adverse_p_pct > effective_blowout_pct:
                            canc_rec = self._create_cancellation_record(
                                pos,
                                "CANCELLED_EXTREME_MACRO_BLOWOUT",
                                f"Price rallied +{adverse_p_pct:.2f}% through limit (Gate: {effective_blowout_pct:.2f}%, Latency: {tick_latency_ms:.0f}ms)"
                            )
                            self._archive_cancelled_order(canc_rec, pos.get("desk"))
                            continue

                    # Extreme Network Blackout Sentinel (Fix 7): If latency exceeds blackout safety ceiling (default 8000ms),
                    # pre-emptively cancel resting limit orders only when signal expiry is enabled:
                    blackout_ceiling = float(getattr(self, "blackout_ceiling_ms", 8000.0))
                    if getattr(self, "enable_signal_expiry", False) and tick_latency_ms >= blackout_ceiling:
                        canc_rec = self._create_cancellation_record(
                            pos,
                            "CANCELLED_NETWORK_BLACKOUT_SAFETY",
                            f"Feed latency ({tick_latency_ms:.0f}ms) exceeded {blackout_ceiling:.0f}ms blackout safety ceiling"
                        )
                        self._archive_cancelled_order(canc_rec, pos.get("desk"))
                        continue

                    # A2. Intrabar Order Block Invalidation Sentinel (Resting Limit Protection)
                    # For higher-timeframe order blocks (e.g. 4H or 24H), a live candle may exhibit lower-wick
                    # absorption mid-candle before subsequently getting crushed by closing time.
                    # The PaperTradingBot tick-watcher mitigates this by evaluating the actual live bid/ask price
                    # against the Order Block invalidation level on each tick.
                    ob_inval_lvl = self._resolve_ob_invalidation_level(pos)
                    if getattr(self, "enable_signal_expiry", False) and ob_inval_lvl is not None and ob_inval_lvl > 0:
                        is_ob_inval_breached = False
                        if direction == "LONG" and live_bid <= ob_inval_lvl:
                            is_ob_inval_breached = True
                            inval_detail = f"Live bid (${live_bid:,.4f}) breached HTF Order Block invalidation level (${ob_inval_lvl:,.4f}) mid-candle"
                        elif direction == "SHORT" and live_ask >= ob_inval_lvl:
                            is_ob_inval_breached = True
                            inval_detail = f"Live ask (${live_ask:,.4f}) breached HTF Order Block invalidation level (${ob_inval_lvl:,.4f}) mid-candle"

                        if is_ob_inval_breached:
                            canc_rec = self._create_cancellation_record(
                                pos,
                                "CANCELLED_ORDER_BLOCK_INVALIDATED",
                                f"HTF Order Block Invalidation: {inval_detail}"
                            )
                            self._archive_cancelled_order(canc_rec, pos.get("desk"))
                            continue

                    # B. Chase Buffer Exceeded / Structure Invalidated vs Runaway Reversal Conversion
                    # In runaway parabolic markets, if price reverses before retesting the LH/HL zone
                    # and begins expanding in the trade direction with institutional R:R (>= 1.00), convert to market fill
                    admission_p = float(pos.get("admission_price", pos.get("current_price", limit_p)))
                    chase_thresh = float(pos.get("chase_threshold_pct", 0.40))
                    max_allowed_long = max(float(pos.get("entry_zone_max", 0.0)), admission_p * (1.0 + chase_thresh / 100.0))
                    min_allowed_short = min(float(pos.get("entry_zone_min", float('inf'))), admission_p * (1.0 - chase_thresh / 100.0))

                    is_runaway_long = (direction == "LONG" and curr_p > max_allowed_long)
                    is_runaway_short = (direction == "SHORT" and curr_p < min_allowed_short)

                    if is_runaway_long or is_runaway_short:
                        tp1_p = float(pos.get("tp1_price", 0.0))
                        sl_p = float(pos.get("sl_price", 0.0))
                        tp_not_reached = (curr_p < tp1_p) if direction == "LONG" else (curr_p > tp1_p)
                        eff_rr = 0.0
                        if tp_not_reached and sl_p > 0 and tp1_p > 0:
                            live_spread_bps = float(pos.get("spread_bps", 4.0))
                            eff_rr, _, _ = self.calculate_effective_rr(
                                entry_p=curr_p,
                                tp1_p=tp1_p,
                                sl_p=sl_p,
                                spread_bps=live_spread_bps,
                                volume_24h_usd=float(pos.get("volume_24h_usd", 0.0)),
                                tick_latency_ms=tick_latency_ms,
                                is_limit=False
                            )

                        if tp_not_reached and eff_rr >= 1.00:
                            pos["status"] = "OPEN"
                            pos["is_limit_resting"] = False
                            pos["entry_price"] = curr_p
                            pos["current_price"] = curr_p
                            pos["opened_at"] = now_utc.isoformat()
                            pos["opened_at_utc"] = now_utc.isoformat()
                            pos["awaiting_microstructure_inflow"] = False
                            pos["fill_confirmation_type"] = "RUNAWAY_REVERSAL_CONVERTED"
                            print(f"[PAPER BOT 🚀 RUNAWAY REVERSAL CONVERTED] {sym} ({direction} {norm_h}) price reversed early! Filled at ${curr_p:,.4f} with effective R:R 1:{eff_rr:.2f}")
                            remaining_positions.append(pos)
                            continue
                        elif getattr(self, "enable_signal_expiry", False):
                            canc_detail = "Price expanded beyond chase threshold without fill" if not tp_not_reached else f"Price dropped/expanded beyond chase threshold (R:R {eff_rr:.2f} < 1:1.00) without limit fill"
                            canc_rec = self._create_cancellation_record(pos, "CANCELLED_CHASE_EXCEEDED", canc_detail)
                            self._archive_cancelled_order(canc_rec, pos.get("desk"))
                            continue
                        else:
                            # In no-expiry mode, continue waiting for fill
                            remaining_positions.append(pos)
                            continue

                    # C. Macro Regime / NTZ Shift Invalidation (Fix 1)
                    if btc_shield_state and getattr(self, "enable_signal_expiry", False):
                        is_flash_dump = btc_shield_state.get("regime") in ["FLASH_DUMP"] or btc_shield_state.get("status_code") in ["BEAR_CASCADE_BLACKOUT", "FLASH_DUMP"]
                        is_ntz = btc_shield_state.get("is_ntz_active") or btc_shield_state.get("status_code") == "NO_TRADE_ZONE" or btc_shield_state.get("regime") in ["RANGE_SQUEEZE"]
                        is_pos_boundary = bool(pos.get("is_range_boundary") or any(k in str(pos.get("strategy") or "").upper() for k in ["RECTANGLE", "RANGE_BOUND", "BOUNDARY"]))
                        boundary_ok = bool(btc_shield_state.get("boundary_harvest_allowed", False))

                        if is_flash_dump or (is_ntz and not (is_pos_boundary and boundary_ok)):
                            canc_rec = self._create_cancellation_record(pos, "CANCELLED_MACRO_NTZ_ACTIVATED", f"Macro BTC NTZ engaged ({btc_shield_state.get('reason', 'Market Shield')})")
                            self._archive_cancelled_order(canc_rec, pos.get("desk"))
                            continue

                    # D. Resting Order TTL Expiration (Disabled when ENABLE_SIGNAL_EXPIRY is False)
                    if getattr(self, "enable_signal_expiry", False):
                        limit_ttl_secs = 2700 if "15M" in norm_h else (43200 if any(x in norm_h for x in ["24H", "1D", "SWING", "MACRO"]) else 10800)
                        if elapsed_secs >= limit_ttl_secs:
                            canc_rec = self._create_cancellation_record(pos, "CANCELLED_RESTING_TTL_EXPIRED", f"Resting limit expired after {dur_str}")
                            self._archive_cancelled_order(canc_rec, pos.get("desk"))
                            continue

                    # E. Multi-Touch Zone Invalidation (Support/Resistance Depletion)
                    # When price enters the optimal entry zone without filling the limit order,
                    # multiple subsequent retests indicate liquidity exhaustion rather than fresh institutional absorption.
                    zone_min = float(pos.get("entry_zone_min", limit_p * 0.998))
                    zone_max = float(pos.get("entry_zone_max", limit_p * 1.002))
                    is_in_zone = (zone_min <= curr_p <= zone_max)
                    prev_in_zone = bool(pos.get("_in_zone_last_tick", False))

                    now_ts = time.time()
                    last_touch_ts = float(pos.get("_last_touch_ts", 0.0))
                    if is_in_zone and not prev_in_zone:
                        if (now_ts - last_touch_ts) >= 10.0:
                            pos["bracket_touch_count"] = int(pos.get("bracket_touch_count", 0)) + 1
                            pos["_last_touch_ts"] = now_ts
                    pos["_in_zone_last_tick"] = is_in_zone

                    if getattr(self, "enable_signal_expiry", False) and int(pos.get("bracket_touch_count", 0)) >= 6 and not is_in_zone and elapsed_secs >= 180:
                        canc_rec = self._create_cancellation_record(
                            pos,
                            "CANCELLED_MULTI_TOUCH_DEPLETION",
                            f"Zone depleted after {pos.get('bracket_touch_count')} re-tests without fill"
                        )
                        self._archive_cancelled_order(canc_rec, pos.get("desk"))
                        continue

                    # F. Clean Limit Fill (Touched limit within the safe bracket)
                    # Post-Outage Stabilization: wait 1.5s after outage recovery before filling resting orders
                    if (time.time() - getattr(self, "_outage_recovered_ts", 0.0)) < 1.5:
                        remaining_positions.append(pos)
                        continue

                    touch_tol = min(pos.get("active_atr", 0.0) * 0.10, limit_p * 0.0008) if pos.get("active_atr") else (limit_p * 0.0008)
                    is_price_touched = (
                        (direction == "LONG" and (curr_p <= (limit_p + touch_tol) or (live_bid > 0 and live_bid <= limit_p))) or
                        (direction == "SHORT" and (curr_p >= (limit_p - touch_tol) or (live_ask > 0 and live_ask >= limit_p)))
                    )

                    if is_price_touched:
                        # Live Spread Widening & Effective R:R Guard (Flash Liquidity Void Defense)
                        live_spread_bps = 0.0
                        if live_ask and live_bid and live_ask > live_bid and curr_p > 0:
                            live_spread_bps = ((live_ask - live_bid) / curr_p) * 10000.0
                        else:
                            live_spread_bps = float(pos.get("spread_bps", 4.0))

                        eff_rr, _, _ = self.calculate_effective_rr(
                            entry_p=limit_p,
                            tp1_p=float(pos.get("tp1_price", 0.0)),
                            sl_p=float(pos.get("sl_price", 0.0)),
                            spread_bps=live_spread_bps,
                            volume_24h_usd=float(pos.get("volume_24h_usd", 0.0)),
                            tick_latency_ms=tick_latency_ms,
                            is_limit=True
                        )

                        if eff_rr < 1.20:
                            canc_rec = self._create_cancellation_record(
                                pos,
                                "CANCELLED_SPREAD_BLOWOUT_RR_DEGRADED",
                                f"Spread blowout ({live_spread_bps:.1f} bps) degraded effective R:R ({eff_rr:.2f} < 1:1.20)"
                            )
                            self._archive_cancelled_order(canc_rec, pos.get("desk"))
                            continue

                        # Live OBI / CVD Inflow Confirmation Gate
                        sym_depth = None
                        if order_book_depths and isinstance(order_book_depths, dict):
                            sym_depth = order_book_depths.get(sym) or order_book_depths.get(sym.replace("/", "").replace(":USDT", ""))

                        sym_cvd = None
                        if cvd_metrics and isinstance(cvd_metrics, dict):
                            sym_cvd = cvd_metrics.get(sym) or cvd_metrics.get(sym.replace("/", "").replace(":USDT", ""))

                        is_confirmed, fill_reason, fill_telemetry = EntryConfirmationEngine.validate_resting_limit_fill(
                            direction=direction,
                            limit_price=limit_p,
                            current_price=curr_p,
                            depth_data=sym_depth,
                            cvd_metrics=sym_cvd,
                            candle_metrics=pos.get("metrics") or pos.get("microstructure_features") or {},
                            obi_threshold=0.25,
                            cvd_threshold=0.20,
                            touch_tolerance=touch_tol
                        )

                        if not is_confirmed:
                            # Microstructure inflow deferral: adverse depth wall or heavy aggressive market pressure
                            pos["awaiting_microstructure_inflow"] = True
                            pos["microstructure_deferral_count"] = int(pos.get("microstructure_deferral_count", 0)) + 1
                            pos["last_microstructure_reason"] = fill_reason
                            pos["microstructure_telemetry"] = fill_telemetry
                            remaining_positions.append(pos)
                            continue

                        # Confirmed fill: Buyer absorption on Long / Seller resistance on Short
                        pos["status"] = "OPEN"
                        pos["is_limit_resting"] = False
                        pos["entry_price"] = limit_p
                        pos["current_price"] = limit_p
                        pos["opened_at"] = now_utc.isoformat()
                        pos["opened_at_utc"] = now_utc.isoformat()
                        pos["awaiting_microstructure_inflow"] = False
                        pos["fill_obi"] = fill_telemetry.get("obi_5", 0.0)
                        pos["fill_cvd"] = fill_telemetry.get("cvd_surge", 0.0)
                        pos["fill_bid_depth_usd"] = fill_telemetry.get("bid_depth_usd", 0.0)
                        pos["fill_ask_depth_usd"] = fill_telemetry.get("ask_depth_usd", 0.0)
                        pos["fill_confirmation_type"] = fill_telemetry.get("fill_confirmation_type", "LIVE_OBI_CVD_CONFIRMED")
                        print(f"[PAPER BOT [FILL] RESTING LIMIT FILLED ({pos['fill_confirmation_type']})] {sym} ({direction} {norm_h}) limit filled at ${limit_p:,.4f}! Reason: {fill_reason}")
                        remaining_positions.append(pos)
                        continue

                    # Still resting validly
                    remaining_positions.append(pos)
                    continue

                # -------------------------------------------------------------
                # 2. EVALUATE ACTIVE OPEN POSITIONS
                # -------------------------------------------------------------
                initial_size_usd = float(pos.get("initial_position_size_usd", pos.get("position_size_usd", 100.0)))
                remaining_size_usd = float(pos.get("remaining_position_size_usd", pos.get("position_size_usd", 100.0)))
                tp1_p = float(pos.get("tp1_price", 0.0))
                tp2_p = float(pos.get("tp2_price", 0.0))
                tp3_p = float(pos.get("tp3_price", 0.0))
                policy = str(pos.get("scaling_policy", "MULTI_TRANCHE_SCALE")).upper()

                has_multi_tp = (tp2_p > tp1_p if direction == "LONG" else tp2_p < tp1_p) and tp2_p > 0
                has_tp3 = (tp3_p > tp2_p if direction == "LONG" else tp3_p < tp2_p) and tp3_p > 0

                # PnL calculation on current market tick
                if direction == "LONG":
                    gain_pct = ((curr_p - entry_p) / entry_p) * 100.0
                    is_tp1 = curr_p >= tp1_p if tp1_p > 0 else False
                    is_tp2 = curr_p >= tp2_p if tp2_p > 0 else False
                    is_tp3 = curr_p >= tp3_p if tp3_p > 0 else False
                    pos["peak_price_seen"] = max(float(pos.get("peak_price_seen") or curr_p), curr_p)
                    pos["trough_price_seen"] = min(float(pos.get("trough_price_seen") or curr_p), curr_p)

                    # EXT-01: Parabolic & Dynamic Trailing Ratchet for Runners (Section 20 & 24)
                    if pos.get("tp2_hit"):
                        active_atr = float(pos.get("active_atr") or abs(entry_p - float(pos.get("initial_sl_price") or (entry_p * 0.98))) / 1.5)
                        risk_r = max(1e-6, abs(entry_p - float(pos.get("initial_sl_price") or (entry_p * 0.98))))
                        peak_p = pos["peak_price_seen"]
                        r_mult = abs(peak_p - entry_p) / risk_r
                        is_parabolic = (r_mult >= 3.0)
                        trail_dist = (0.80 * active_atr) if is_parabolic else (1.50 * active_atr)
                        cand_sl = peak_p - trail_dist
                        new_sl = max(float(pos.get("sl_price", tp1_p)), float(tp1_p), cand_sl)
                        if new_sl > float(pos["sl_price"]) and new_sl < curr_p:
                            pos["sl_price"] = format_dynamic_precision(new_sl)
                            pos["is_parabolic_trail_active"] = is_parabolic
                    elif pos.get("tp1_hit"):
                        # Dynamic ATR Trailing Stop for TP1 -> TP2 Runner (30% remaining position)
                        active_atr = float(pos.get("active_atr") or abs(entry_p - float(pos.get("initial_sl_price") or (entry_p * 0.98))) / 1.5)
                        peak_p = pos["peak_price_seen"]
                        if peak_p > tp1_p and tp1_p > 0:
                            trail_dist = max(1.20 * active_atr, 0.40 * abs(tp2_p - tp1_p) if tp2_p > tp1_p else 1.20 * active_atr)
                            cand_sl = peak_p - trail_dist
                            profit_buffer_sl = entry_p + (tp1_p - entry_p) * 0.25
                            new_sl = max(float(pos.get("sl_price", profit_buffer_sl)), profit_buffer_sl, cand_sl)
                            if new_sl > float(pos["sl_price"]) and new_sl < curr_p:
                                pos["sl_price"] = format_dynamic_precision(new_sl)
                                pos["is_tp1_trail_active"] = True

                    hit_sl = curr_p <= pos["sl_price"]
                else:
                    gain_pct = ((entry_p - curr_p) / entry_p) * 100.0
                    is_tp1 = curr_p <= tp1_p if tp1_p > 0 else False
                    is_tp2 = curr_p <= tp2_p if tp2_p > 0 else False
                    is_tp3 = curr_p <= tp3_p if tp3_p > 0 else False
                    pos["peak_price_seen"] = max(float(pos.get("peak_price_seen") or curr_p), curr_p)
                    pos["trough_price_seen"] = min(float(pos.get("trough_price_seen") or curr_p), curr_p)

                    # EXT-01: Parabolic & Dynamic Trailing Ratchet for Runners (Section 20 & 24)
                    if pos.get("tp2_hit"):
                        active_atr = float(pos.get("active_atr") or abs(float(pos.get("initial_sl_price") or (entry_p * 1.02)) - entry_p) / 1.5)
                        risk_r = max(1e-6, abs(float(pos.get("initial_sl_price") or (entry_p * 1.02)) - entry_p))
                        trough_p = pos["trough_price_seen"]
                        r_mult = abs(entry_p - trough_p) / risk_r
                        is_parabolic = (r_mult >= 3.0)
                        trail_dist = (0.80 * active_atr) if is_parabolic else (1.50 * active_atr)
                        cand_sl = trough_p + trail_dist
                        new_sl = min(float(pos.get("sl_price", tp1_p)), float(tp1_p), cand_sl)
                        if new_sl < float(pos["sl_price"]) and new_sl > curr_p:
                            pos["sl_price"] = format_dynamic_precision(new_sl)
                            pos["is_parabolic_trail_active"] = is_parabolic
                    elif pos.get("tp1_hit"):
                        # Dynamic ATR Trailing Stop for SHORT TP1 -> TP2 Runner (30% remaining position)
                        active_atr = float(pos.get("active_atr") or abs(float(pos.get("initial_sl_price") or (entry_p * 1.02)) - entry_p) / 1.5)
                        trough_p = pos["trough_price_seen"]
                        if trough_p < tp1_p and tp1_p > 0:
                            trail_dist = max(1.20 * active_atr, 0.40 * abs(tp1_p - tp2_p) if (tp2_p > 0 and tp1_p > tp2_p) else 1.20 * active_atr)
                            cand_sl = trough_p + trail_dist
                            profit_buffer_sl = entry_p - (entry_p - tp1_p) * 0.25
                            new_sl = min(float(pos.get("sl_price", profit_buffer_sl)), profit_buffer_sl, cand_sl)
                            if new_sl < float(pos["sl_price"]) and new_sl > curr_p:
                                pos["sl_price"] = format_dynamic_precision(new_sl)
                                pos["is_tp1_trail_active"] = True

                    hit_sl = curr_p >= pos["sl_price"]

                pos["unrealized_pnl_pct"] = gain_pct * leverage
                pos["unrealized_pnl_usd"] = (gain_pct / 100.0) * remaining_size_usd
                pos["peak_gain_pct"] = max(float(pos.get("peak_gain_pct") or 0.0), gain_pct)
                pos["max_drawdown_pct"] = max(float(pos.get("max_drawdown_pct") or 0.0), max(0.0, -gain_pct))

                # Intrabar Mid-Candle Order Block Invalidation Sentinel for Open Positions
                # For higher-timeframe order blocks (e.g., 4H or 24H), a live candle may exhibit lower-wick
                # absorption mid-candle before subsequently getting crushed by closing time.
                # The PaperTradingBot tick-watcher mitigates this by evaluating the actual live bid/ask price
                # against the Order Block invalidation level on each tick.
                hit_ob_invalidation = False
                ob_inval_lvl = self._resolve_ob_invalidation_level(pos)
                if ob_inval_lvl is not None and ob_inval_lvl > 0:
                    if direction == "LONG" and live_bid <= ob_inval_lvl:
                        hit_ob_invalidation = True
                    elif direction == "SHORT" and live_ask >= ob_inval_lvl:
                        hit_ob_invalidation = True

                # Emergency News Volatility Shock & Macro Impulse Sentinel for Open Positions:
                is_macro_severe = bool(btc_shield_state and (
                    btc_shield_state.get("regime") in ["FLASH_DUMP"] or
                    btc_shield_state.get("status_code") in ["FLASH_DUMP", "BEAR_CASCADE_BLACKOUT", "ALERT_DUMP"] or
                    "FLASH_DUMP" in str(btc_shield_state.get("altcoin_posture", "")) or
                    "DEFENSIVE_CASH_ONLY" in str(btc_shield_state.get("altcoin_posture", "")) or
                    "BLACKOUT" in str(btc_shield_state.get("status_code", ""))
                ))
                is_news_shock_active = bool(pos.get("is_news_shock_active", False))
                if not is_news_shock_active:
                    try:
                        from app.services.institutional_intelligence_service import institutional_intelligence_service
                        inst_cal = institutional_intelligence_service.get_macro_economic_calendar()
                        if inst_cal.get("is_volatility_pause_active"):
                            is_news_shock_active = True
                    except Exception:
                        pass

                # If news shock or macro impulse strikes while position touched profit (>= 0.30%), lock stop loss to BE
                if (is_news_shock_active or is_macro_severe) and pos["peak_gain_pct"] >= 0.30 and not pos.get("is_breakeven_locked"):
                    pos["is_breakeven_locked"] = True
                    pos["sl_price"] = format_dynamic_precision(entry_p * (1.0005 if direction == "LONG" else 0.9995))
                    try:
                        print(f"[PAPER BOT 🛡️ SHOCK BREAKER] Volatility shock triggered Breakeven Lock for {sym} at ${pos['sl_price']:,.4f}.")
                    except Exception:
                        pass

                # If news shock strikes and position experiences an adverse move, cut at half-loss to prevent blowout slippage
                init_sl_p = float(pos.get("initial_sl_price") or (entry_p * (0.98 if direction == "LONG" else 1.02)))
                init_sl_dist_pct = abs(entry_p - init_sl_p) / max(1e-8, entry_p) * 100.0
                hit_news_shock_cut = is_news_shock_active and (gain_pct <= -max(0.50, 0.50 * init_sl_dist_pct))
                # Acute black-swan asset dump/shock exit (drop >= 2.5% against position or macro severe)
                hit_acute_gap_shock = (gain_pct <= -2.50) and (is_macro_severe or gain_pct <= -(1.5 * init_sl_dist_pct))
                hit_emergency_exit = hit_acute_gap_shock or hit_news_shock_cut

                # Calculate elapsed time and duration
                opened_dt = None
                try:
                    opened_str = pos.get("opened_at_utc") or pos.get("opened_at")
                    if opened_str:
                        opened_dt = datetime.fromisoformat(opened_str.replace("Z", "+00:00"))
                except Exception:
                    pass

                now_utc = datetime.now(timezone.utc)
                elapsed_secs = (now_utc - opened_dt).total_seconds() if opened_dt else 0

                dur_h = int(elapsed_secs // 3600)
                dur_m = int((elapsed_secs % 3600) // 60)
                dur_s = int(elapsed_secs % 60)
                if dur_h > 0:
                    dur_str = f"{dur_h}h {dur_m}m {dur_s}s"
                elif dur_m > 0:
                    dur_str = f"{dur_m}m {dur_s}s"
                else:
                    dur_str = f"{dur_s}s"

                norm_h = str(pos.get("signal_horizon") or pos.get("horizon", "1H")).upper()
                # Canonical hold time: 15M → 2h, 1H → 6h, 4H → 12h, 24H stays 48h
                base_hold_secs = 7200 if any(x in norm_h for x in ["15M", "5M", "30M", "SCALP"]) else (172800 if any(x in norm_h for x in ["24H", "1D", "SWING", "MACRO", "DAILY", "7D", "15D", "30D"]) else (43200 if "4H" in norm_h else 21600))
                max_hold_secs = base_hold_secs
                
                # Dynamic Trailing Expiry & Runner Protection Engine:
                is_runner_active = bool(pos.get("tp1_hit") or pos.get("tp2_hit"))
                is_be_or_t0_locked = bool(pos.get("is_breakeven_locked") or pos.get("status") in ["TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"])
                is_profitable = (gain_pct >= 0.40) or (is_be_or_t0_locked and gain_pct >= 0.15)

                if not getattr(self, "enable_signal_expiry", False):
                    hit_expiry = False
                elif elapsed_secs < base_hold_secs:
                    hit_expiry = False
                else:
                    # Elapsed time has exceeded canonical base hold time
                    if is_runner_active:
                        # 1. Runner Protection: Risk is strictly ring-fenced by trailed Stop-Loss.
                        # Never liquidate an active runner via hard clock stops; allow them to trail to TP2/TP3
                        # up to a generous 4.0x safety ceiling (e.g. 8h for 15M, 24h for 1H, 8 days for 24H).
                        runner_ceiling_secs = base_hold_secs * 4.0
                        if elapsed_secs < runner_ceiling_secs:
                            hit_expiry = False
                            pos["is_runner_protected"] = True
                            pos["trailing_expiry_mode"] = "RUNNER_PROTECTED"
                        else:
                            hit_expiry = True
                    elif is_profitable and not hit_sl:
                        # 2. Dynamic Trailing Expiry for Profitable Pre-TP1 Trades:
                        # Winner in expansion with protected downside (Tier-0 BE / half-risk SL).
                        # Extend TTL up to 2.5x base hold time to allow the trade to achieve structural TP1.
                        profit_ceiling_secs = base_hold_secs * 2.5
                        if elapsed_secs < profit_ceiling_secs:
                            hit_expiry = False
                            pos["is_trailing_expiry_active"] = True
                            pos["trailing_expiry_mode"] = "PROFIT_MOMENTUM_EXTENSION"
                        else:
                            hit_expiry = True
                    elif abs(gain_pct) <= 0.60:
                        # 3. Dynamic Consolidation Grace Extension (+50% TTL if coiled in flat consolidation)
                        consol_ceiling_secs = base_hold_secs * 1.50
                        if elapsed_secs < consol_ceiling_secs:
                            hit_expiry = False
                            pos["is_consolidation_grace_active"] = True
                            pos["trailing_expiry_mode"] = "CONSOLIDATION_GRACE"
                        else:
                            hit_expiry = True
                    else:
                        # 4. Stagnant or losing trade: strictly enforce canonical base hold time
                        hit_expiry = True
                        pos["trailing_expiry_mode"] = "CANONICAL_TTL"

                # -------------------------------------------------------------
                # Feature 5.2: Dynamic Time-Decay TP Compaction (Section 20 & Phase 5)
                # -------------------------------------------------------------
                compaction_base = (base_hold_secs * 2.5) if pos.get("is_trailing_expiry_active") else base_hold_secs
                if getattr(self, "enable_signal_expiry", False) and elapsed_secs >= (0.80 * compaction_base) and not pos.get("tp1_hit") and tp1_p > 0:
                    final_window = max(1.0, 0.20 * compaction_base)
                    elapsed_in_window = min(final_window, max(0.0, elapsed_secs - (0.80 * compaction_base)))
                    decay_lambda = math.exp(-2.5 * (elapsed_in_window / final_window))

                    if "original_tp1_price" not in pos:
                        pos["original_tp1_price"] = tp1_p
                    if "original_sl_price" not in pos:
                        pos["original_sl_price"] = float(pos.get("sl_price", 0.0))

                    orig_tp1 = float(pos["original_tp1_price"])
                    orig_sl = float(pos["original_sl_price"])
                    # Compact towards entry, retaining at least 35% of original profit target
                    cand_compacted = entry_p + (orig_tp1 - entry_p) * (0.35 + 0.65 * decay_lambda)

                    # Ensure minimal profit hurdle to cover friction (at least 15 bps beyond entry)
                    min_friction_buffer = 0.0015 * entry_p
                    if direction == "LONG" and cand_compacted > (entry_p + min_friction_buffer):
                        cand_p = format_dynamic_precision(cand_compacted)
                        if cand_p < tp1_p:
                            pos["tp1_price"] = cand_p
                            pos["is_tp_compacted"] = True
                            tp1_p = cand_p
                            is_tp1 = curr_p >= tp1_p
                            # Symmetrically compact SL towards entry so downside risk shrinks proportionally
                            if not pos.get("is_breakeven_locked") and orig_sl < entry_p:
                                sl_compacted = entry_p - (entry_p - orig_sl) * (0.35 + 0.65 * decay_lambda)
                                pos["sl_price"] = format_dynamic_precision(max(orig_sl, sl_compacted))
                    elif direction == "SHORT" and cand_compacted < (entry_p - min_friction_buffer):
                        cand_p = format_dynamic_precision(cand_compacted)
                        if cand_p > tp1_p:
                            pos["tp1_price"] = cand_p
                            pos["is_tp_compacted"] = True
                            tp1_p = cand_p
                            is_tp1 = curr_p <= tp1_p
                            # Symmetrically compact SL towards entry for SHORT
                            if not pos.get("is_breakeven_locked") and orig_sl > entry_p:
                                sl_compacted = entry_p + (orig_sl - entry_p) * (0.35 + 0.65 * decay_lambda)
                                pos["sl_price"] = format_dynamic_precision(min(orig_sl, sl_compacted))

                # Tier-0 Breakeven Ratchet: Tied to TP1 proximity (65% of TP1 range touched OR peak_gain reaches tier0 threshold)
                tp1_p_pos = float(pos.get("tp1_price", 0.0))
                tp1_dist = abs(tp1_p_pos - entry_p) / max(1e-12, entry_p) * 100.0
                if direction == "LONG":
                    tp1_proximity_reached = (tp1_p_pos > entry_p and curr_p >= (entry_p + (tp1_p_pos - entry_p) * 0.50))
                else:
                    tp1_proximity_reached = (tp1_p_pos < entry_p and curr_p <= (entry_p - (entry_p - tp1_p_pos) * 0.50))

                # Phase 4: Dynamic 2-Stage Profit Ratchet (+0.50% Micro-Guard & +0.75% Tier-0 Breakeven)
                # Stage 1: Micro-Guard at +0.50% MFE (Cut risk by strictly 50% from immutable original anchor)
                if getattr(self, "enable_breakeven_guard", False) and pos["peak_gain_pct"] >= 0.50 and not pos.get("is_breakeven_locked") and not pos.get("tp1_hit"):
                    orig_sl = float(pos.get("initial_sl_price") or pos.get("sl_original") or entry_p)
                    if orig_sl <= 0.0 or (direction == "LONG" and orig_sl >= entry_p) or (direction == "SHORT" and orig_sl <= entry_p):
                        orig_sl = float(pos.get("sl_price") or entry_p)
                        if not pos.get("initial_sl_price"):
                            pos["initial_sl_price"] = orig_sl

                    spread_bps = float(pos.get("spread_bps") or 5.0)
                    min_sl_dist = max(entry_p * 0.0035, 2.5 * (spread_bps / 10000.0) * entry_p)

                    if direction == "LONG" and orig_sl < entry_p:
                        full_risk = entry_p - orig_sl
                        if full_risk > (min_sl_dist * 1.5):
                            target_half_sl = entry_p - max(min_sl_dist, full_risk * 0.50)
                            if target_half_sl > float(pos.get("sl_price", 0.0)) and target_half_sl < entry_p:
                                pos["sl_price"] = format_dynamic_precision(target_half_sl)
                    elif direction == "SHORT" and orig_sl > entry_p:
                        full_risk = orig_sl - entry_p
                        if full_risk > (min_sl_dist * 1.5):
                            target_half_sl = entry_p + max(min_sl_dist, full_risk * 0.50)
                            if target_half_sl < float(pos.get("sl_price", 1e9)) and target_half_sl > entry_p:
                                pos["sl_price"] = format_dynamic_precision(target_half_sl)

                effective_t0_thresh = min(float(pos.get("tier0_threshold_pct", 0.75)), max(0.50, 0.35 * tp1_dist))

                if getattr(self, "enable_breakeven_guard", False) and not pos.get("is_breakeven_locked") and not pos.get("tp1_hit") and not pos.get("tp2_hit") and (tp1_proximity_reached or pos["peak_gain_pct"] >= effective_t0_thresh):
                    pos["is_breakeven_locked"] = True
                    pos["sl_price"] = format_dynamic_precision(entry_p * (1.0005 if direction == "LONG" else 0.9995))
                    self._update_position_trailing_evolution(pos, curr_p)
                    try:
                        print(f"[PAPER BOT 🛡️] Tier-0 Breakeven Ratchet Activated for {sym}! Stop-loss locked at Entry.")
                    except Exception:
                        pass
                    try:
                        from app.services.whatsapp_service import whatsapp_service
                        sig_dict = dict(pos)
                        sig_dict["signal_id"] = pos.get("trade_id") or pos.get("signal_id")
                        sig_dict["entry_price"] = entry_p
                        gain_now = ((curr_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - curr_p) / entry_p) * 100.0
                        whatsapp_service.emit_signal_outcome(sig_dict, "BE_LOCKED", curr_p, gain_now)
                    except Exception:
                        pass

                # Multi-Stage Pre-TP1 Trailing Profit Ratchet (Locking in real profits before TP1)
                # Guarantees that trades moving +1.2% to +4.8% never regress back to Breakeven or a Loss!
                if getattr(self, "enable_breakeven_guard", False) and not pos.get("tp1_hit") and not pos.get("tp2_hit") and pos["peak_gain_pct"] >= 1.20:
                    peak_gain = float(pos["peak_gain_pct"])
                    pos_atr = float(pos.get("active_atr") or (entry_p * 0.015))
                    new_pre_tp1_sl = None

                    if peak_gain >= 4.00:
                        # Lock in at least +2.80% or trail within 0.65x ATR of peak
                        trail_pts = 0.65 * pos_atr
                        if direction == "LONG":
                            cand = max(entry_p * 1.0280, float(pos["peak_price_seen"]) - trail_pts)
                            if cand > float(pos["sl_price"]) and cand < curr_p:
                                new_pre_tp1_sl = cand
                        else:
                            cand = min(entry_p * 0.9720, float(pos["trough_price_seen"]) + trail_pts)
                            if cand < float(pos["sl_price"]) and cand > curr_p:
                                new_pre_tp1_sl = cand
                    elif peak_gain >= 3.00:
                        # Lock in at least +2.00% or trail within 0.75x ATR of peak
                        trail_pts = 0.75 * pos_atr
                        if direction == "LONG":
                            cand = max(entry_p * 1.0200, float(pos["peak_price_seen"]) - trail_pts)
                            if cand > float(pos["sl_price"]) and cand < curr_p:
                                new_pre_tp1_sl = cand
                        else:
                            cand = min(entry_p * 0.9800, float(pos["trough_price_seen"]) + trail_pts)
                            if cand < float(pos["sl_price"]) and cand > curr_p:
                                new_pre_tp1_sl = cand
                    elif peak_gain >= 2.00:
                        # Lock in at least +1.20% or trail within 0.85x ATR of peak
                        trail_pts = 0.85 * pos_atr
                        if direction == "LONG":
                            cand = max(entry_p * 1.0120, float(pos["peak_price_seen"]) - trail_pts)
                            if cand > float(pos["sl_price"]) and cand < curr_p:
                                new_pre_tp1_sl = cand
                        else:
                            cand = min(entry_p * 0.9880, float(pos["trough_price_seen"]) + trail_pts)
                            if cand < float(pos["sl_price"]) and cand > curr_p:
                                new_pre_tp1_sl = cand
                    elif peak_gain >= 1.20:
                        # Lock in fee-covered net-green profit buffer (+0.40%)
                        if direction == "LONG":
                            cand = entry_p * 1.0040
                            if cand > float(pos["sl_price"]) and cand < curr_p:
                                new_pre_tp1_sl = cand
                        else:
                            cand = entry_p * 0.9960
                            if cand < float(pos["sl_price"]) and cand > curr_p:
                                new_pre_tp1_sl = cand

                    if new_pre_tp1_sl is not None:
                        pos["sl_price"] = format_dynamic_precision(new_pre_tp1_sl)
                        pos["is_profit_ratchet_active"] = True
                        pos["profit_ratchet_locked_gain_pct"] = peak_gain
                        self._update_position_trailing_evolution(pos, curr_p)

                # Phase 2: Dynamic Order Flow Exhaustion Harvester (Near-Target Profit Harvester)
                # Evaluates whether the position has reached >= 75% proximity to TP1 and order flow exhibits aggressive exhaustion/absorption.
                if getattr(self, "enable_breakeven_guard", False) and not pos.get("tp1_hit") and tp1_p > 0 and entry_p > 0:
                    tp1_total_span = abs(tp1_p - entry_p)
                    current_progress = (curr_p - entry_p) if direction == "LONG" else (entry_p - curr_p)
                    proximity_ratio = current_progress / max(1e-12, tp1_total_span)

                    if proximity_ratio >= 0.75:
                        # Extract order flow / CVD metrics for exhaustion detection
                        sym_cvd = None
                        if cvd_metrics and isinstance(cvd_metrics, dict):
                            sym_cvd = cvd_metrics.get(sym) or cvd_metrics.get(sym.replace("/", "").replace(":USDT", ""))
                        cvd_val = float(sym_cvd.get("cvd_surge") or sym_cvd.get("cvd_surge_5") or 0.0) if isinstance(sym_cvd, dict) else float(pos.get("metrics", {}).get("cvd_surge_5") or 0.0)

                        sym_depth = None
                        if order_book_depths and isinstance(order_book_depths, dict):
                            sym_depth = order_book_depths.get(sym) or order_book_depths.get(sym.replace("/", "").replace(":USDT", ""))
                        depth_info = EntryConfirmationEngine.calculate_top5_obi(sym_depth) if sym_depth else {}
                        obi_val = float(depth_info.get("obi_5", 0.0))
                        tb_ratio = float(pos.get("metrics", {}).get("taker_buy_ratio", 0.50))

                        # Multi-Factor Order Flow Exhaustion Evaluation (CVD + OBI + TBR Confluence)
                        # Avoid single-metric false positives on low-volume / micro-cap pairs
                        vol_24h = float(pos.get("volume_24h_usd") or pos.get("volume_24h") or 50_000_000.0)
                        is_low_volume_pair = (vol_24h < 5_000_000.0)

                        is_exhaustion = False
                        exhaustion_reason = ""
                        headwinds = []

                        if direction == "LONG":
                            cvd_adverse = (cvd_val <= -0.15)
                            obi_adverse = (obi_val <= -0.30)
                            tbr_adverse = (tb_ratio < 0.40)
                            cvd_extreme = (cvd_val <= -0.40)
                            obi_extreme = (obi_val <= -0.65)

                            if cvd_adverse:
                                headwinds.append(f"CVD: {cvd_val:+.2f} <= -0.15")
                            if obi_adverse:
                                headwinds.append(f"OBI: {obi_val:+.2f} <= -0.30")
                            if tbr_adverse:
                                headwinds.append(f"TBR: {tb_ratio:.2f} < 0.40")

                            confluence_count = len(headwinds)
                            if is_low_volume_pair:
                                # Low-volume pairs require multi-factor confluence (>= 2 factors) or extreme blowout
                                if confluence_count >= 2 or cvd_extreme or obi_extreme:
                                    is_exhaustion = True
                                    exhaustion_reason = f"Confluent taker exhaustion near TP1 on low-vol asset ({confluence_count}/3 factors: {', '.join(headwinds)})"
                                else:
                                    pos["transient_order_flow_spike_deferred"] = True
                            else:
                                if confluence_count >= 1:
                                    is_exhaustion = True
                                    detail_prefix = f"Multi-factor taker exhaustion ({confluence_count}/3 factors)" if confluence_count >= 2 else "Aggressive institutional headwind"
                                    exhaustion_reason = f"{detail_prefix} near TP1 ({', '.join(headwinds)})"
                        else:  # SHORT
                            cvd_adverse = (cvd_val >= 0.15)
                            obi_adverse = (obi_val >= 0.30)
                            tbr_adverse = (tb_ratio > 0.60)
                            cvd_extreme = (cvd_val >= 0.40)
                            obi_extreme = (obi_val >= 0.65)

                            if cvd_adverse:
                                headwinds.append(f"CVD: {cvd_val:+.2f} >= +0.15")
                            if obi_adverse:
                                headwinds.append(f"OBI: {obi_val:+.2f} >= +0.30")
                            if tbr_adverse:
                                headwinds.append(f"TBR: {tb_ratio:.2f} > 0.60")

                            confluence_count = len(headwinds)
                            if is_low_volume_pair:
                                if confluence_count >= 2 or cvd_extreme or obi_extreme:
                                    is_exhaustion = True
                                    exhaustion_reason = f"Confluent taker exhaustion near TP1 on low-vol asset ({confluence_count}/3 factors: {', '.join(headwinds)})"
                                else:
                                    pos["transient_order_flow_spike_deferred"] = True
                            else:
                                if confluence_count >= 1:
                                    is_exhaustion = True
                                    detail_prefix = f"Multi-factor taker exhaustion ({confluence_count}/3 factors)" if confluence_count >= 2 else "Aggressive institutional headwind"
                                    exhaustion_reason = f"{detail_prefix} near TP1 ({', '.join(headwinds)})"

                        # Near-Target Retracement Harvest: If price achieved >= 70% of TP1 (or >= +2.0% gain) and starts pulling back, bank profit immediately!
                        is_retracing_from_target = False
                        if proximity_ratio >= 0.70 or pos["peak_gain_pct"] >= 2.00:
                            pullback_from_peak = (pos["peak_price_seen"] - curr_p) if direction == "LONG" else (curr_p - pos["trough_price_seen"])
                            pos_atr = float(pos.get("active_atr") or (entry_p * 0.015))
                            if pullback_from_peak >= (0.35 * pos_atr) or (pos["peak_gain_pct"] - gain_pct) >= 0.35:
                                is_retracing_from_target = True
                                exhaustion_reason = f"Target zone pullback ({pullback_from_peak / pos_atr:.2f}x ATR from peak +{pos['peak_gain_pct']:.2f}%)"

                        if is_exhaustion or is_retracing_from_target:
                            # Compact TP1 directly to current market price to bank profits immediately!
                            pos["tp1_price"] = curr_p
                            pos["is_tp_harvested_early"] = True
                            pos["tp_harvest_reason"] = "TAKE_PROFIT_1_HARVEST_RETRACEMENT" if is_retracing_from_target else "TAKE_PROFIT_1_HARVEST_EXHAUSTION"
                            pos["tp_harvest_detail"] = exhaustion_reason
                            tp1_p = curr_p
                            is_tp1 = True
                            print(f"[PAPER BOT 🌾 MICRO-HARVEST] {sym} Near-target profit harvest at {proximity_ratio*100:.1f}% progress: {exhaustion_reason}. Compacting TP1 to ${curr_p:,.4f} to bank profits!", flush=True)

                # Multi-Tranche Scale Check 1: TP1 Hit (Realize 70%, lock Profit Buffer, hold 30% for TP2)
                if policy == "MULTI_TRANCHE_SCALE" and has_multi_tp and is_tp1 and not pos.get("tp1_hit"):
                    pos["tp1_hit"] = True
                    t1_notional = initial_size_usd * 0.70
                    t1_gain = ((tp1_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp1_p) / entry_p) * 100.0
                    t1_gross = (t1_gain / 100.0) * t1_notional
                    t1_fee = (float(pos.get("entry_fee_usd", initial_size_usd * self.taker_fee_rate)) * 0.70) + (t1_notional * (1.0 + t1_gain / 100.0) * self.taker_fee_rate)
                    t1_spread = (float(pos.get("spread_bps", 4.0)) / 20000.0) * t1_notional if not pos.get("optimal_entry_limit") else 0.0
                    dyn_entry_slip_rate, dyn_exit_slip_rate = _calc_tick_slip_rates(pos)
                    t1_slip = dyn_entry_slip_rate * t1_notional if not pos.get("optimal_entry_limit") else 0.0
                    t1_friction = t1_fee + t1_spread + t1_slip
                    t1_net = t1_gross - t1_friction

                    pos["total_realized_partial_usd"] = float(pos.get("total_realized_partial_usd", 0.0)) + t1_net
                    pos["total_gross_partial_usd"] = float(pos.get("total_gross_partial_usd", 0.0)) + t1_gross
                    pos["total_frictions_partial_usd"] = float(pos.get("total_frictions_partial_usd", 0.0)) + t1_friction
                    pos["remaining_position_size_usd"] = initial_size_usd * 0.30
                    pos["is_breakeven_locked"] = True
                    # Lock in +0.5R profit buffer (covering all trading fees and guaranteeing net profit on runner stop)
                    lock_buffer = max(0.0035 * entry_p, abs(tp1_p - entry_p) * 0.25)
                    pos["sl_price"] = format_dynamic_precision(entry_p + lock_buffer if direction == "LONG" else entry_p - lock_buffer)
                    pos["status"] = "OPEN_TP1_LOCKED_BREAKEVEN"
                    self._update_position_trailing_evolution(pos, curr_p)

                    try:
                        print(f"[PAPER BOT 🎯 TP1 SCALED] {sym} TP1 Hit at ${tp1_p:,.4f}! 70% locked (${t1_net:+,.2f}). SL ratcheted to Profit Buffer (${pos['sl_price']:,.4f}). Holding 30% for TP2.", flush=True)
                    except Exception:
                        pass

                    try:
                        from app.services.whatsapp_service import whatsapp_service
                        sig_dict = dict(pos)
                        sig_dict["exit_price"] = tp1_p
                        sig_dict["realized_return_pct"] = t1_gain
                        whatsapp_service.emit_signal_outcome(sig_dict, "TP1_HIT", tp1_p, t1_gain)
                    except Exception:
                        pass

                    self._sync_paper_partial_tp_to_audit(pos, "TP1_HIT", tp1_p, t1_gain)
                    remaining_positions.append(pos)
                    continue

                # Multi-Tranche Scale Check 2: TP2 Hit (Realize 20%, ratchet SL to TP1, hold 10% for TP3)
                if policy == "MULTI_TRANCHE_SCALE" and has_tp3 and is_tp2 and pos.get("tp1_hit") and not pos.get("tp2_hit"):
                    pos["tp2_hit"] = True
                    t2_notional = initial_size_usd * 0.20
                    t2_gain = ((tp2_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp2_p) / entry_p) * 100.0
                    t2_gross = (t2_gain / 100.0) * t2_notional
                    t2_fee = (float(pos.get("entry_fee_usd", initial_size_usd * self.taker_fee_rate)) * 0.20) + (t2_notional * (1.0 + t2_gain / 100.0) * self.taker_fee_rate)
                    t2_spread = (float(pos.get("spread_bps", 4.0)) / 20000.0) * t2_notional if not pos.get("optimal_entry_limit") else 0.0
                    dyn_entry_slip_rate, dyn_exit_slip_rate = _calc_tick_slip_rates(pos)
                    t2_slip = dyn_entry_slip_rate * t2_notional if not pos.get("optimal_entry_limit") else 0.0
                    t2_friction = t2_fee + t2_spread + t2_slip
                    t2_net = t2_gross - t2_friction

                    pos["total_realized_partial_usd"] = float(pos.get("total_realized_partial_usd", 0.0)) + t2_net
                    pos["total_gross_partial_usd"] = float(pos.get("total_gross_partial_usd", 0.0)) + t2_gross
                    pos["total_frictions_partial_usd"] = float(pos.get("total_frictions_partial_usd", 0.0)) + t2_friction
                    pos["remaining_position_size_usd"] = initial_size_usd * 0.10
                    pos["sl_price"] = tp1_p
                    pos["status"] = "OPEN_TP2_LOCKED_TRAIL"
                    self._update_position_trailing_evolution(pos, curr_p)

                    try:
                        print(f"[PAPER BOT 🎯 TP2 SCALED] {sym} TP2 Hit at ${tp2_p:,.4f}! 20% locked (${t2_net:+,.2f}). SL ratcheted to TP1 (${tp1_p:,.4f}). Holding 10% runner for TP3.", flush=True)
                    except Exception:
                        pass

                    try:
                        from app.services.whatsapp_service import whatsapp_service
                        sig_dict = dict(pos)
                        sig_dict["exit_price"] = tp2_p
                        sig_dict["realized_return_pct"] = t2_gain
                        whatsapp_service.emit_signal_outcome(sig_dict, "TP2_HIT", tp2_p, t2_gain)
                    except Exception:
                        pass

                    self._sync_paper_partial_tp_to_audit(pos, "TP2_HIT", tp2_p, t2_gain)
                    remaining_positions.append(pos)
                    continue

                # Complete Exit Triggers
                hit_tp3 = is_tp3 and pos.get("tp2_hit")
                hit_tp2_final = is_tp2 and pos.get("tp1_hit") and not has_tp3
                hit_tp1_final = is_tp1 and (not has_multi_tp or policy == "SINGLE_TARGET_TP1")
                hit_tp = hit_tp3 or hit_tp2_final or hit_tp1_final

                hit_order_book_void_exit = is_void and is_emergency_liq

                # Check Exit Triggers (TP, SL, OB Invalidation, Horizon Expiry, Emergency Macro Impulse, or Order Book Void Emergency Liquidation)
                if hit_tp or hit_sl or hit_ob_invalidation or hit_expiry or hit_emergency_exit or hit_order_book_void_exit:
                    if hit_order_book_void_exit:
                        if pos.get("is_auto_abandoned_liq"):
                            exit_reason = "CLOSED_ORDER_BOOK_VOID_ABANDONED_AUTO_LIQUIDATION"
                        else:
                            exit_reason = "CLOSED_ORDER_BOOK_VOID_EMERGENCY_LIQUIDATION"
                        v_dict = v_entry if (order_book_voids and isinstance(v_entry, dict)) else {}
                        haircut_pct = float(v_dict.get("liquidation_haircut_pct", 5.0))
                        base_p = curr_p if curr_p > 0 else entry_p
                        if direction == "LONG":
                            exit_p = base_p * (1.0 - haircut_pct / 100.0)
                        else:
                            exit_p = base_p * (1.0 + haircut_pct / 100.0)
                    elif hit_tp3:
                        exit_reason = "TAKE_PROFIT_3"
                        exit_p = tp3_p
                    elif hit_tp2_final:
                        exit_reason = "TAKE_PROFIT_2"
                        exit_p = tp2_p
                    elif hit_tp1_final:
                        exit_reason = "TAKE_PROFIT_1"
                        exit_p = tp1_p
                    elif hit_sl or (hit_ob_invalidation and getattr(self, "enable_breakeven_guard", False)):
                        if (pos.get("is_profit_ratchet_active") or pos.get("profit_ratchet_locked_gain_pct")) and gain_pct > 0.15:
                            exit_reason = "TAKE_PROFIT_PRE_TP1_RATCHET"
                        elif pos.get("tp2_hit"):
                            exit_reason = "TAKE_PROFIT_2_TRAIL_SL"
                        elif pos.get("tp1_hit"):
                            exit_reason = "TAKE_PROFIT_1_TRAIL_SL"
                        elif pos.get("is_breakeven_locked"):
                            exit_reason = "STOP_LOSS_BREAKEVEN"
                        elif hit_ob_invalidation:
                            exit_reason = "CLOSED_ORDER_BLOCK_INTRABAR_INVALIDATION"
                        else:
                            exit_reason = "STOP_LOSS"
                        # Account for physical candle gap penetration / gap slippage (Fix 3):
                        sl_target = float(ob_inval_lvl if (hit_ob_invalidation and not pos.get("is_breakeven_locked") and not pos.get("tp1_hit")) else pos["sl_price"])
                        v_24h = float(pos.get("volume_24h_usd") or pos.get("volume_24h") or 0.0)
                        low_cap_fac = max(1.0, math.sqrt(15_000_000.0 / max(1_000_000.0, v_24h))) if v_24h > 0 else 1.0

                        eval_price = live_bid if direction == "LONG" else live_ask
                        if direction == "LONG":
                            exit_p = min(sl_target, float(eval_price))
                            if float(eval_price) < sl_target:
                                gap_pct = ((sl_target - float(eval_price)) / max(1e-8, sl_target)) * 100.0
                                if gap_pct > 0.15 and low_cap_fac > 1.0:
                                    extra_slip = exit_p * (gap_pct / 100.0) * 0.15 * (low_cap_fac - 1.0)
                                    exit_p = max(0.0001, exit_p - extra_slip)
                        else:
                            exit_p = max(sl_target, float(eval_price))
                            if float(eval_price) > sl_target:
                                gap_pct = ((float(eval_price) - sl_target) / max(1e-8, sl_target)) * 100.0
                                if gap_pct > 0.15 and low_cap_fac > 1.0:
                                    extra_slip = exit_p * (gap_pct / 100.0) * 0.15 * (low_cap_fac - 1.0)
                                    exit_p = exit_p + extra_slip
                    elif hit_emergency_exit:
                        exit_reason = "EMERGENCY_NEWS_SHOCK_EXIT" if hit_news_shock_cut else "EMERGENCY_MACRO_IMPULSE_EXIT"
                        exit_p = curr_p
                    else:
                        if pos.get("tp2_hit"):
                            exit_reason = f"TAKE_PROFIT_2_RUNNER_EXPIRY ({dur_str})"
                        elif pos.get("tp1_hit"):
                            exit_reason = f"TAKE_PROFIT_1_RUNNER_EXPIRY ({dur_str})"
                        elif gain_pct >= 0.35:
                            exit_reason = f"PROFIT_HORIZON_CLOSE ({dur_str})"
                        else:
                            exit_reason = f"HORIZON_EXPIRY ({dur_str})"
                        exit_p = curr_p

                    # Runner exit accounting on remaining position notional
                    rem_notional = float(pos.get("remaining_position_size_usd", pos.get("position_size_usd", initial_size_usd)))
                    if direction == "LONG":
                        runner_gain_pct = ((exit_p - entry_p) / entry_p) * 100.0
                    else:
                        runner_gain_pct = ((entry_p - exit_p) / entry_p) * 100.0

                    runner_gross_pnl = (runner_gain_pct / 100.0) * rem_notional

                    # 1. Commission Fees on runner exit
                    buy_fee_runner = float(pos.get("entry_fee_usd", initial_size_usd * self.taker_fee_rate)) * (rem_notional / max(1.0, initial_size_usd))
                    sell_fee_runner = rem_notional * (1.0 + (runner_gain_pct / 100.0)) * self.taker_fee_rate
                    total_fees_runner = buy_fee_runner + sell_fee_runner

                    # 2. Bid-Ask Spread Drag
                    spread_bps = float(pos.get("spread_bps") or 4.0)
                    entry_was_limit = bool(pos.get("optimal_entry_limit") and not pos.get("is_limit_resting"))
                    entry_spread_usd = 0.0 if entry_was_limit else (spread_bps / 20000.0) * rem_notional
                    exit_spread_usd = 0.0 if (hit_tp or hit_order_book_void_exit) else (spread_bps / 20000.0) * rem_notional
                    spread_drag_usd = entry_spread_usd + exit_spread_usd

                    # 3. Execution Slippage Drag
                    dyn_entry_slip_rate, dyn_exit_slip_rate = _calc_tick_slip_rates(pos)
                    entry_slip_usd = 0.0 if entry_was_limit else (dyn_entry_slip_rate * rem_notional)
                    exit_slip_usd = 0.0 if (hit_tp or hit_order_book_void_exit) else (dyn_exit_slip_rate * rem_notional)
                    slippage_drag_usd = entry_slip_usd + exit_slip_usd

                    # 4. Accrued Funding Rate Drag (Pro-rated per 8-hour cycle)
                    funding_cycles = max(0.0, elapsed_secs / 28800.0)
                    funding_rate = float(pos.get("current_funding_rate") or 0.0001)
                    funding_drag_usd = rem_notional * abs(funding_rate) * funding_cycles

                    runner_frictions = total_fees_runner + spread_drag_usd + slippage_drag_usd + funding_drag_usd
                    runner_net_pnl = runner_gross_pnl - runner_frictions

                    # Combine runner with prior partial scale realizations
                    gross_pnl = round(float(pos.get("total_gross_partial_usd", 0.0)) + runner_gross_pnl, 2)
                    total_frictions = round(float(pos.get("total_frictions_partial_usd", 0.0)) + runner_frictions, 4)
                    net_pnl = round(float(pos.get("total_realized_partial_usd", 0.0)) + runner_net_pnl, 2)
                    realized_ret_pct = round(((net_pnl / max(1.0, initial_size_usd)) * 100.0) * leverage, 2)
                    buy_fee = round(buy_fee_runner, 4)
                    sell_fee = round(sell_fee_runner, 4)
                    total_fees = round(total_fees_runner, 4)

                    if net_pnl > 0.05:
                        outcome = "WON"
                    elif net_pnl < -0.05:
                        outcome = "LOST"
                    else:
                        outcome = "BREAKEVEN"

                    if "TAKE_PROFIT_PRE_TP1_RATCHET" in exit_reason or "PROFIT_RATCHET" in exit_reason:
                        outcome_label = f"🟢 WON (PROFIT RATCHET {realized_ret_pct:+.2f}%)"
                    elif "PROFIT_HORIZON_CLOSE" in exit_reason:
                        outcome_label = f"🟢 WON (HORIZON PROFIT {realized_ret_pct:+.2f}%)"
                    elif hit_tp3:
                        outcome_label = "🟢 WON (TP3 HIT)"
                    elif hit_tp2_final:
                        outcome_label = "🟢 WON (TP2 HIT)"
                    elif hit_tp1_final:
                        outcome_label = "🟢 WON (TP1 HIT)"
                    elif outcome == "WON":
                        outcome_label = f"🟢 WON ({exit_reason} {realized_ret_pct:+.2f}%)"
                    elif outcome == "BREAKEVEN":
                        outcome_label = f"🛡️ BREAKEVEN ({exit_reason} {realized_ret_pct:+.2f}%)"
                    else:
                        outcome_label = f"🔴 LOST ({exit_reason} {realized_ret_pct:+.2f}%)"

                    closed_record = {
                        "trade_id": pos.get("trade_id") or pos.get("signal_id") or f"TRADE_{int(time.time()*1000)}",
                        "trade_thesis_id": pos.get("trade_thesis_id") or f"THESIS-{sym.replace('/', '').replace(':', '').replace('-', '')}-{direction.upper()}",
                        "symbol": sym,
                        "horizon": norm_h,
                        "desk": pos.get("desk", "default"),
                        "desk_name": pos.get("desk_name", "Standard Desk"),
                        "direction": direction,
                        "execution_engine": "binance_futures",
                        "entry_price": round(entry_p, 6),
                        "raw_entry_price": round(entry_p, 6),
                        "exit_price": round(exit_p, 6),
                        "exit_reason": exit_reason,
                        "outcome": outcome,
                        "outcome_label": outcome_label,
                        "tp1_hit": bool(pos.get("tp1_hit", False)),
                        "tp2_hit": bool(pos.get("tp2_hit", False)),
                        "tp3_hit": bool(pos.get("tp3_hit", False)),
                        "is_breakeven_locked": bool(pos.get("is_breakeven_locked", False)),
                        "sl_price": round(float(pos.get("sl_price") or 0.0), 6),
                        "initial_sl_price": round(float(pos.get("initial_sl_price") or pos.get("sl_price") or 0.0), 6),
                        "peak_price_seen": round(float(pos.get("peak_price_seen") or exit_p), 6),
                        "trough_price_seen": round(float(pos.get("trough_price_seen") or exit_p), 6),
                        "peak_gain_pct": round(float(pos.get("peak_gain_pct") or 0.0), 2),
                        "max_drawdown_pct": round(float(pos.get("max_drawdown_pct") or 0.0), 2),
                        "gross_pnl_usd": round(gross_pnl, 2),
                        "net_pnl_usd": round(net_pnl, 2),
                        "realized_pnl_usd": round(net_pnl, 2),
                        "return_pct": round(realized_ret_pct, 2),
                        "realized_pnl_pct": round(realized_ret_pct, 2),
                        "buy_fee_usd": round(buy_fee, 4),
                        "sell_fee_usd": round(sell_fee, 4),
                        "fees_usd": round(total_fees, 4),
                        "binance_fee_usd": round(total_fees, 4),
                        "spread_drag_usd": round(spread_drag_usd, 4),
                        "slippage_drag_usd": round(slippage_drag_usd, 4),
                        "funding_drag_usd": round(funding_drag_usd, 4),
                        "total_frictions_usd": round(total_frictions, 4),
                        "duration_str": dur_str,
                        "opened_at": pos.get("opened_at_utc") or pos.get("opened_at"),
                        "opened_at_utc": pos.get("opened_at_utc") or pos.get("opened_at"),
                        "closed_at": now_utc.isoformat(),
                        "closed_at_utc": now_utc.isoformat(),
                        "strategy": pos.get("strategy") or pos.get("canonical_strategy") or pos.get("strategy_archetype"),
                        "canonical_strategy": pos.get("canonical_strategy") or pos.get("strategy"),
                        "strategy_archetype": pos.get("strategy_archetype") or pos.get("canonical_strategy") or pos.get("strategy"),
                        "regime": pos.get("market_regime") or pos.get("regime"),
                        "market_regime": pos.get("market_regime") or pos.get("regime"),
                        "meta_win_probability": pos.get("meta_win_probability"),
                        "meta_model_type": pos.get("meta_model_type"),
                        "microstructure_features": pos.get("microstructure_features", {})
                    }

                    if "closed_trades" not in self.data:
                        self.data["closed_trades"] = []
                    if not any(c.get("trade_id") == closed_record["trade_id"] for c in self.data["closed_trades"]):
                        self.data["closed_trades"].append(closed_record)

                    if "closed_trades_history" not in self.data:
                        self.data["closed_trades_history"] = []
                    if not any(c.get("trade_id") == closed_record["trade_id"] for c in self.data["closed_trades_history"]):
                        self.data["closed_trades_history"].append(closed_record)

                    self.data["realized_pnl_usd"] = round(float(self.data.get("realized_pnl_usd", 0.0)) + net_pnl, 2)
                    self.data["current_balance_usd"] = round(float(self.data.get("current_balance_usd", 1000.0)) + net_pnl, 2)
                    self.data["total_fees_paid_usd"] = round(float(self.data.get("total_fees_paid_usd", 0.0)) + total_fees, 4)
                    self.data["total_frictions_paid_usd"] = round(float(self.data.get("total_frictions_paid_usd", 0.0)) + total_frictions, 4)

                    tot_trades = int(self.data.get("total_trades", self.data.get("total_trades_count", 0))) + 1
                    win_trades = int(self.data.get("winning_trades", self.data.get("winning_trades_count", 0))) + (1 if outcome == "WON" else 0)
                    lose_trades = int(self.data.get("losing_trades", self.data.get("losing_trades_count", 0))) + (1 if outcome == "LOST" else 0)
                    be_trades = int(self.data.get("breakeven_trades", self.data.get("breakeven_trades_count", 0))) + (1 if outcome == "BREAKEVEN" else 0)

                    self.data["total_trades"] = tot_trades
                    self.data["total_trades_count"] = tot_trades
                    self.data["winning_trades"] = win_trades
                    self.data["winning_trades_count"] = win_trades
                    self.data["losing_trades"] = lose_trades
                    self.data["losing_trades_count"] = lose_trades
                    self.data["breakeven_trades"] = be_trades
                    self.data["breakeven_trades_count"] = be_trades

                    decisive = win_trades + lose_trades
                    total_closed_wr = round((win_trades / max(1, tot_trades)) * 100.0, 1) if tot_trades > 0 else 0.0
                    decisive_wr = round((win_trades / max(1, decisive)) * 100.0, 1) if decisive > 0 else 0.0
                    self.data["win_rate_pct"] = total_closed_wr
                    self.data["total_closed_win_rate_pct"] = total_closed_wr
                    self.data["decisive_win_rate_pct"] = decisive_wr
                    try:
                        print(f"[PAPER BOT [CLOSED]] Position Closed: {sym} ({exit_reason}) | Outcome: {outcome} | Net PnL: ${net_pnl:+,.2f} ({realized_ret_pct:+.2f}%) | Friction: ${total_frictions:.2f}")
                    except Exception:
                        pass
                    self._sync_paper_exit_to_audit(closed_record)
                    # Canary execution outcome tracking (Fix 6)
                    if pos.get("is_canary_eligible"):
                        try:
                            from app.quant_v16.canary_execution import canary_gate
                            canary_gate.record_canary_trade_outcome(
                                trade_id=closed_record["trade_id"],
                                symbol=closed_record["symbol"],
                                direction=closed_record["direction"],
                                allocated_usd=float(pos.get("canary_allocated_usd", 10.0)),
                                net_pnl_usd=round(net_pnl * 0.10, 2),
                                return_pct=realized_ret_pct,
                                is_win=(outcome == "WON"),
                                exit_reason=exit_reason
                            )
                        except Exception:
                            pass
                else:
                    self._update_position_trailing_evolution(pos, curr_p)
                    remaining_positions.append(pos)

            self.data["open_positions"] = remaining_positions
            # Synchronize active slots per desk
            desks = self.data.get("desks", {})
            for d_key, d_val in desks.items():
                d_val["active_slots"] = sum(1 for p in remaining_positions if p.get("desk") == d_key)

            # -----------------------------------------------------------------
            # 3. EVALUATE SHADOW TRACKING POSITIONS FOR PAUSED STRATEGIES (Feature 5.1)
            # -----------------------------------------------------------------
            remaining_shadow = []
            shadow_positions = self.data.get("shadow_positions", [])
            if shadow_positions:
                from app.quant_v16.strategies import StrategyRegistry
                strat_reg = StrategyRegistry()

                for spos in shadow_positions:
                    sym = spos.get("symbol")
                    curr_p = live_prices.get(sym) or live_prices.get(sym.replace("/", "").replace(":USDT", ""))
                    if not curr_p or curr_p <= 0:
                        remaining_shadow.append(spos)
                        continue

                    spos["current_price"] = curr_p
                    e_p = spos["entry_price"]
                    s_dir = spos["direction"]
                    s_hz = str(spos.get("signal_horizon") or spos.get("horizon", "1H")).upper()

                    s_opened = datetime.fromisoformat(spos["opened_at_utc"].replace("Z", "+00:00")) if spos.get("opened_at_utc") else datetime.now(timezone.utc)
                    s_elapsed = (datetime.now(timezone.utc) - s_opened).total_seconds()
                    s_base_hold = 7200 if any(x in s_hz for x in ["15M", "5M", "30M", "SCALP"]) else (172800 if any(x in s_hz for x in ["24H", "1D", "SWING", "MACRO", "DAILY", "7D", "15D", "30D"]) else 21600)

                    s_gain = ((curr_p - e_p) / e_p) * 100.0 if s_dir == "LONG" else ((e_p - curr_p) / e_p) * 100.0
                    spos["peak_gain_pct"] = max(spos.get("peak_gain_pct", 0.0), s_gain)

                    # Dynamic Trailing Expiry for Shadow Trades
                    s_is_runner = bool(spos.get("tp1_hit"))
                    s_is_profitable = (s_gain >= 0.40)
                    if s_is_runner:
                        s_eff_hold = s_base_hold * 4.0
                    elif s_is_profitable:
                        s_eff_hold = s_base_hold * 2.5
                    elif abs(s_gain) <= 0.60:
                        s_eff_hold = s_base_hold * 1.5
                    else:
                        s_eff_hold = s_base_hold

                    # Dynamic time decay on shadow TP1 if >80% TTL elapsed
                    s_tp1 = spos["tp1_price"]
                    s_compaction_base = (s_base_hold * 2.5) if (s_is_profitable and not s_is_runner) else s_base_hold
                    if s_elapsed >= 0.80 * s_compaction_base and not spos.get("tp1_hit"):
                        decay_w = max(1.0, 0.20 * s_compaction_base)
                        decay_t = min(decay_w, max(0.0, s_elapsed - 0.80 * s_compaction_base))
                        decay_l = math.exp(-2.5 * (decay_t / decay_w))
                        s_orig_tp1 = float(spos.get("original_tp1_price", s_tp1))
                        spos["original_tp1_price"] = s_orig_tp1
                        cand_s_tp1 = e_p + (s_orig_tp1 - e_p) * (0.35 + 0.65 * decay_l)
                        min_buf = 0.0015 * e_p
                        if s_dir == "LONG" and cand_s_tp1 > (e_p + min_buf) and cand_s_tp1 < s_tp1:
                            spos["tp1_price"] = format_dynamic_precision(cand_s_tp1)
                            s_tp1 = spos["tp1_price"]
                        elif s_dir == "SHORT" and cand_s_tp1 < (e_p - min_buf) and cand_s_tp1 > s_tp1:
                            spos["tp1_price"] = format_dynamic_precision(cand_s_tp1)
                            s_tp1 = spos["tp1_price"]

                    s_hit_tp1 = (curr_p >= s_tp1) if s_dir == "LONG" else (curr_p <= s_tp1)
                    s_hit_sl = (curr_p <= spos["sl_price"]) if s_dir == "LONG" else (curr_p >= spos["sl_price"])
                    s_hit_expiry = getattr(self, "enable_signal_expiry", False) and (s_elapsed >= s_eff_hold)

                    if s_hit_tp1 or s_hit_sl or s_hit_expiry:
                        is_win = s_hit_tp1 or (s_hit_expiry and s_gain > 0.05)
                        net_ret = s_gain - (self.taker_fee_rate * 200.0 + 0.04 + 0.03)
                        strat_id = spos.get("canonical_strategy") or spos.get("strategy")
                        regime = spos.get("regime")
                        unpause_info = strat_reg.record_shadow_outcome(strat_id, is_win=is_win, net_return_pct=net_ret, regime=regime)
                        try:
                            print(f"[PAPER BOT 👻 SHADOW RESOLVED] Shadow trade {sym} ({s_dir}) resolved: Win={is_win}, NetRet={net_ret:+.2f}%. Strategy '{strat_id}' status: {unpause_info.get('status')} (Unpaused: {unpause_info.get('unpaused')}, Rolling PF: {unpause_info.get('rolling_50_pf')})")
                        except Exception:
                            pass
                        continue

                    remaining_shadow.append(spos)

                self.data["shadow_positions"] = remaining_shadow

            self.save_ledger()

    def _harvest_stagnant_runner(self, pos: Dict[str, Any], reason: str = "CLOSED_RUNNER_STAGNATION_HARVEST"):
        """Gracefully harvests a stagnant runner to liberate margin for fresh Grade A+ setups."""
        with self._lock:
            curr_p = float(pos.get("current_price", pos.get("entry_price", 0.0)))
            entry_p = float(pos.get("entry_price", 0.0))
            direction = pos.get("direction", "LONG")
            initial_size_usd = float(pos.get("initial_position_size_usd", pos.get("position_size_usd", 100.0)))
            rem_notional = float(pos.get("remaining_position_size_usd", initial_size_usd))

            if direction == "LONG":
                gain_pct = ((curr_p - entry_p) / entry_p) * 100.0 if entry_p > 0 else 0.0
            else:
                gain_pct = ((entry_p - curr_p) / entry_p) * 100.0 if entry_p > 0 else 0.0

            runner_gross = (gain_pct / 100.0) * rem_notional
            fees = rem_notional * self.taker_fee_rate * 2.0
            net_pnl = round(float(pos.get("total_gross_partial_usd", 0.0)) + runner_gross - fees, 2)
            ret_pct = round((net_pnl / max(1.0, initial_size_usd)) * 100.0, 2)

            closed_rec = {
                "trade_id": pos.get("trade_id"),
                "trade_thesis_id": pos.get("trade_thesis_id") or f"THESIS-{str(pos.get('symbol', '')).replace('/', '').replace(':', '').replace('-', '')}-{direction.upper()}",
                "symbol": pos.get("symbol"),
                "direction": direction,
                "desk": pos.get("desk"),
                "entry_price": entry_p,
                "exit_price": curr_p,
                "exit_reason": reason,
                "outcome": "WON" if net_pnl > 0.05 else ("BREAKEVEN" if abs(net_pnl) <= 0.05 else "LOST"),
                "tp1_hit": bool(pos.get("tp1_hit", False)),
                "tp2_hit": bool(pos.get("tp2_hit", False)),
                "tp3_hit": bool(pos.get("tp3_hit", False)),
                "is_breakeven_locked": bool(pos.get("is_breakeven_locked", False)),
                "sl_price": round(float(pos.get("sl_price") or 0.0), 6),
                "initial_sl_price": round(float(pos.get("initial_sl_price") or pos.get("sl_price") or 0.0), 6),
                "peak_price_seen": round(float(pos.get("peak_price_seen") or curr_p), 6),
                "trough_price_seen": round(float(pos.get("trough_price_seen") or curr_p), 6),
                "peak_gain_pct": round(float(pos.get("peak_gain_pct") or 0.0), 2),
                "max_drawdown_pct": round(float(pos.get("max_drawdown_pct") or 0.0), 2),
                "realized_return_pct": ret_pct,
                "net_pnl_usd": net_pnl,
                "frictions_usd": fees,
                "closed_at_utc": datetime.now(timezone.utc).isoformat()
            }
            if "closed_trades" not in self.data:
                self.data["closed_trades"] = []
            self.data["closed_trades"].append(closed_rec)
            self.data["open_positions"] = [p for p in self.data.get("open_positions", []) if p.get("trade_id") != pos.get("trade_id")]
            self._sync_paper_exit_to_audit(closed_rec)
            self.save_ledger()

    def _sync_paper_partial_tp_to_audit(self, pos: Dict[str, Any], tp_stage: str, tp_price: float, gain_pct: float):
        """
        Real-Time Execution Bridge for Partial Scale-Out:
        Instantly synchronizes sub-second paper trade partial TP events (TP1 / TP2) into:
        1. trader_signals_tracker.csv
        2. MySQL signals_tracker (SignalAudit)
        3. v16_dynamic_states.json & v16_immutable_signals.json
        Maintains lockstep consistency across terminal, audit ledger, and paper trading.
        """
        try:
            sym = str(pos.get("symbol", "")).strip().upper()
            pos_sid = str(pos.get("trade_id") or pos.get("signal_id") or "").strip()
            hz = str(pos.get("horizon", "15M")).strip().upper()
            norm_hz = "15M" if "15" in hz else ("24H" if ("24" in hz or "1D" in hz) else "1H")
            now_utc = datetime.now(timezone.utc)
            updated_at = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

            if tp_stage == "TP1_HIT":
                audit_status = "TP1_LOCKED_BREAKEVEN"
                outcome_label = f"🎯 TP1 HIT ({gain_pct:+.2f}%) - BREAKEVEN LOCKED"
            elif tp_stage == "TP2_HIT":
                audit_status = "TP2_LOCKED_TRAIL"
                outcome_label = f"🎯 TP2 HIT ({gain_pct:+.2f}%) - TRAILING PROFIT"
            else:
                audit_status = "PARTIAL_TP_HIT"
                outcome_label = f"🎯 PARTIAL TP ({gain_pct:+.2f}%)"

            is_tp1_locked_flag = bool(pos.get("tp1_hit") or tp_stage in ("TP1_HIT", "TP2_HIT"))
            is_tp2_locked_flag = bool(pos.get("tp2_hit") or tp_stage == "TP2_HIT")
            pos_sl = float(pos.get("sl_price") or 0.0)
            pos_peak = float(pos.get("peak_price_seen") or tp_price)
            pos_trough = float(pos.get("trough_price_seen") or tp_price)
            pos_mfe = round(float(pos.get("peak_gain_pct") or max(0.0, gain_pct)), 2)
            pos_mae = round(float(pos.get("max_drawdown_pct") or 0.0), 2)

            # 1. Update authoritative CSV: trader_signals_tracker.csv
            csv_path = os.path.join(EXPORT_DIR, "trader_signals_tracker.csv")
            if os.path.exists(csv_path):
                import csv
                updated_rows = []
                csv_changed = False
                with open(csv_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    fieldnames = reader.fieldnames
                    for row in reader:
                        r_sid = str(row.get("signal_id", "")).strip()
                        r_sym = str(row.get("symbol", "")).strip().upper()
                        r_hz = str(row.get("horizon", "")).strip().upper()
                        r_norm_hz = "15M" if "15" in r_hz else ("24H" if ("24" in r_hz or "1D" in r_hz) else "1H")
                        r_st = str(row.get("status", "")).strip().upper()

                        is_id_match = bool(pos_sid and r_sid == pos_sid)
                        is_match = is_id_match or (
                            (r_sym == sym or r_sym.replace("/", "") == sym.replace("/", ""))
                            and (r_norm_hz == norm_hz)
                            and r_st in ["PENDING_EVALUATION", "ACTIVE", "PENDING_LIMIT", "TP1_LOCKED_BREAKEVEN"]
                        )
                        if is_match and not csv_changed:
                            row["status"] = audit_status
                            row["outcome_label"] = outcome_label
                            row["current_price"] = str(round(tp_price, 6))
                            if pos_sl > 0 and "sl_price" in (fieldnames or []):
                                row["sl_price"] = str(round(pos_sl, 6))
                            if "is_tp1_locked" in (fieldnames or []):
                                row["is_tp1_locked"] = str(is_tp1_locked_flag)
                            if "is_tp2_locked" in (fieldnames or []):
                                row["is_tp2_locked"] = str(is_tp2_locked_flag)
                            if "peak_price_seen" in (fieldnames or []):
                                row["peak_price_seen"] = str(round(pos_peak, 6))
                            if "trough_price_seen" in (fieldnames or []):
                                row["trough_price_seen"] = str(round(pos_trough, 6))
                            if "max_potential_gain_pct" in (fieldnames or []):
                                row["max_potential_gain_pct"] = str(pos_mfe)
                            if "updated_at_utc" in (fieldnames or []):
                                row["updated_at_utc"] = updated_at
                            csv_changed = True
                        updated_rows.append(row)

                if csv_changed and fieldnames:
                    tmp_f = f"{csv_path}.tmp.{time.time_ns()}"
                    with open(tmp_f, "w", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(updated_rows)
                    os.replace(tmp_f, csv_path)

            # 2. Update MySQL Database directly
            try:
                from app.database import SessionLocal
                from app.models.signal import SignalAudit
                from sqlalchemy import or_

                db = SessionLocal()
                try:
                    db_sig = None
                    if pos_sid:
                        db_sig = db.query(SignalAudit).filter(SignalAudit.signal_id == pos_sid).first()
                    if not db_sig:
                        db_sig = db.query(SignalAudit).filter(
                            or_(SignalAudit.symbol == sym, SignalAudit.symbol == sym.replace("/", "")),
                            SignalAudit.status.in_(["PENDING_EVALUATION", "ACTIVE", "PENDING_LIMIT", "TP1_LOCKED_BREAKEVEN"])
                        ).order_by(SignalAudit.id.desc()).first()

                    if db_sig:
                        db_sig.status = audit_status
                        db_sig.outcome_label = outcome_label
                        if pos_sl > 0:
                            db_sig.sl_price = round(pos_sl, 6)
                        db_sig.peak_price_seen = round(pos_peak, 6)
                        db_sig.trough_price_seen = round(pos_trough, 6)
                        db_sig.max_potential_gain_pct = pos_mfe
                        db_sig.evaluated_at_utc = updated_at
                        db.commit()
                        print(f"[PAPER-AUDIT BRIDGE 🔗] Successfully synced partial TP to MySQL for {sym} ({norm_hz}): {audit_status}")
                finally:
                    db.close()
            except Exception:
                pass

            # 3. Synchronize to v16_dynamic_states.json and v16_immutable_signals.json
            try:
                dyn_path = os.path.join(EXPORT_DIR, "v16_dynamic_states.json")
                target_k = None
                if os.path.exists(dyn_path):
                    with open(dyn_path, "r", encoding="utf-8") as df:
                        dyn_data = json.load(df)
                    if pos_sid and pos_sid in dyn_data:
                        target_k = pos_sid
                    if not target_k:
                        for k, v in dyn_data.items():
                            if (sym in k or sym.replace("/", "") in k) and (norm_hz in k or v.get("horizon") == norm_hz):
                                target_k = k
                                break
                    if not target_k:
                        for k in dyn_data.keys():
                            if sym in k or sym.replace("/", "") in k:
                                target_k = k
                                break
                    if target_k and target_k in dyn_data:
                        dyn_data[target_k]["status"] = audit_status
                        dyn_data[target_k]["outcome_label"] = outcome_label
                        dyn_data[target_k]["current_price"] = round(tp_price, 6)
                        if pos_sl > 0:
                            dyn_data[target_k]["current_sl"] = round(pos_sl, 6)
                            dyn_data[target_k]["locked_sl"] = round(pos_sl, 6)
                            dyn_data[target_k]["trailing_sl"] = round(pos_sl, 6)
                        dyn_data[target_k]["is_tp1_locked"] = is_tp1_locked_flag
                        dyn_data[target_k]["is_tp2_locked"] = is_tp2_locked_flag
                        dyn_data[target_k]["mfe_pct"] = max(float(dyn_data[target_k].get("mfe_pct") or 0.0), pos_mfe)
                        dyn_data[target_k]["mae_pct"] = max(float(dyn_data[target_k].get("mae_pct") or 0.0), pos_mae)
                        dyn_data[target_k]["is_breakeven_active"] = True
                        dyn_data[target_k]["is_risk_free"] = True
                        dyn_data[target_k]["residual_risk_usd"] = 0.0
                        dyn_data[target_k]["locked_profit_usd"] = float(pos.get("locked_profit_usd") or pos.get("total_realized_partial_usd") or 0.0)
                        dyn_data[target_k]["trailing_runner_rr"] = pos.get("trailing_runner_rr")
                        dyn_data[target_k]["trailing_rr_ratio"] = pos.get("active_risk_reward_ratio") or "RISK_FREE (LOCKED)"
                        dyn_data[target_k]["structural_risk_reward"] = pos.get("structural_risk_reward")
                        dyn_data[target_k]["updated_at_utc"] = updated_at
                        tmp_dp = f"{dyn_path}.tmp.{time.time_ns()}"
                        with open(tmp_dp, "w", encoding="utf-8") as df:
                            json.dump(dyn_data, df, indent=2)
                        os.replace(tmp_dp, dyn_path)

                imm_path = os.path.join(EXPORT_DIR, "v16_immutable_signals.json")
                if os.path.exists(imm_path):
                    with open(imm_path, "r", encoding="utf-8") as imf:
                        imm_data = json.load(imf)
                    imm_k = target_k if target_k in imm_data else None
                    if not imm_k:
                        for k in imm_data.keys():
                            if sym in k or sym.replace("/", "") in k:
                                imm_k = k
                                break
                    if imm_k and imm_k in imm_data:
                        imm_data[imm_k]["status"] = audit_status
                        tmp_im = f"{imm_path}.tmp.{time.time_ns()}"
                        with open(tmp_im, "w", encoding="utf-8") as imf:
                            json.dump(imm_data, imf, indent=2)
                        os.replace(tmp_im, imm_path)
            except Exception:
                pass
        except Exception as err:
            print(f"[PAPER-AUDIT BRIDGE ⚠️] Error syncing partial TP: {err}")

    def _sync_paper_exit_to_audit(self, closed_record: Dict[str, Any]):
        """
        Real-Time Execution Bridge:
        Instantly synchronizes sub-second paper trade exit events into:
        1. trader_signals_tracker.csv
        2. MySQL signals_tracker (SignalAudit)
        Eliminating all intra-candle vs. candle close discrepancies.
        """
        try:
            sym = str(closed_record.get("symbol", "")).strip().upper()
            rec_sid = str(closed_record.get("trade_id") or closed_record.get("signal_id") or "").strip()
            hz = str(closed_record.get("horizon", "15M")).strip().upper()
            norm_hz = "15M" if "15" in hz else ("24H" if ("24" in hz or "1D" in hz) else "1H")
            exit_reason = str(closed_record.get("exit_reason", ""))
            exit_p = float(closed_record.get("exit_price", 0.0))
            ret_pct = float(closed_record.get("return_pct", 0.0))
            tp2_hit = bool(closed_record.get("tp2_hit", False))
            tp1_hit = bool(closed_record.get("tp1_hit", False)) or tp2_hit
            tp3_hit = bool(closed_record.get("tp3_hit", False))
            rec_sl = float(closed_record.get("sl_price") or 0.0)
            rec_peak = float(closed_record.get("peak_price_seen") or exit_p)
            rec_trough = float(closed_record.get("trough_price_seen") or exit_p)
            rec_mfe = round(float(closed_record.get("peak_gain_pct") or 0.0), 2)
            rec_mae = round(float(closed_record.get("max_drawdown_pct") or 0.0), 2)
            now_utc = datetime.now(timezone.utc)
            closed_at = closed_record.get("closed_at_utc") or closed_record.get("closed_at") or now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

            # Map paper exit reason to authoritative SignalAudit status and outcome label
            if "TAKE_PROFIT_2_TRAIL_SL" in exit_reason or "WON_TP2_TRAIL" in exit_reason:
                audit_status = "WON_TP2_TRAIL"
                outcome_label = f"🟢 WON (TP2 + TRAILING RUNNER {ret_pct:+.2f}%)"
                wa_event = "TRAIL_SL_HIT"
                tp2_hit = True
                tp1_hit = True
            elif "TAKE_PROFIT_1_TRAIL_SL" in exit_reason or "WON_TP1_BE" in exit_reason:
                audit_status = "WON_TP1_BE"
                outcome_label = f"🟢 WON (TP1 + TRAILING RUNNER {ret_pct:+.2f}%)"
                wa_event = "TRAIL_SL_HIT"
                tp1_hit = True
            elif "TAKE_PROFIT_2_RUNNER_EXPIRY" in exit_reason or (("HORIZON_EXPIRY" in exit_reason or "EXPIRY" in exit_reason) and tp2_hit):
                audit_status = "WON_TP2_EXP"
                outcome_label = f"🟢 WON (TP2 + EXP {ret_pct:+.2f}%)"
                wa_event = "TP2_HIT"
                tp2_hit = True
                tp1_hit = True
            elif "TAKE_PROFIT_1_RUNNER_EXPIRY" in exit_reason or (("HORIZON_EXPIRY" in exit_reason or "EXPIRY" in exit_reason) and tp1_hit):
                audit_status = "WON_TP1_EXP"
                outcome_label = f"🟢 WON (TP1 + EXP {ret_pct:+.2f}%)"
                wa_event = "TP1_HIT"
                tp1_hit = True
            elif "TAKE_PROFIT_PRE_TP1_RATCHET" in exit_reason or "PROFIT_RATCHET" in exit_reason:
                audit_status = "WON_PROFIT_RATCHET"
                outcome_label = f"🟢 WON (PROFIT RATCHET {ret_pct:+.2f}%)"
                wa_event = "TP1_HIT"
                tp1_hit = True
            elif "PROFIT_HORIZON_CLOSE" in exit_reason:
                audit_status = "WON_EXP_PROFIT"
                outcome_label = f"🟢 WON (HORIZON PROFIT {ret_pct:+.2f}%)"
                wa_event = "TP1_HIT"
                tp1_hit = True
            elif "BREAKEVEN" in exit_reason or "TIER0" in exit_reason or exit_reason == "STOP_LOSS_BREAKEVEN":
                audit_status = "BREAKEVEN_GUARD"
                outcome_label = f"🛡️ BREAKEVEN (TIER-0 GUARD {ret_pct:+.2f}%)"
                wa_event = "BE_HIT"
            elif "STOP_LOSS" in exit_reason or "EMERGENCY" in exit_reason or "INVALIDATION" in exit_reason or "ORDER_BLOCK" in exit_reason:
                if "EMERGENCY" in exit_reason:
                    if tp2_hit and ret_pct >= 0.0:
                        audit_status = "WON_TP2_EXP"
                        outcome_label = f"🟢 WON (TP2 + EMERGENCY EXIT {ret_pct:+.2f}%)"
                        wa_event = "TP2_HIT"
                    elif tp1_hit and ret_pct >= 0.0:
                        audit_status = "WON_TP1_EXP"
                        outcome_label = f"🟢 WON (TP1 + EMERGENCY EXIT {ret_pct:+.2f}%)"
                        wa_event = "TP1_HIT"
                    elif ret_pct >= 0.05:
                        audit_status = "WON_EXP_PROFIT"
                        outcome_label = f"🟢 WON (EMERGENCY EXIT {ret_pct:+.2f}%)"
                        wa_event = "EXPIRED"
                    elif ret_pct <= -0.05:
                        audit_status = "LOST_SL"
                        outcome_label = f"🔴 LOST (EMERGENCY SHOCK {ret_pct:+.2f}%)"
                        wa_event = "SL_HIT"
                    else:
                        audit_status = "BREAKEVEN_GUARD"
                        outcome_label = f"🛡️ BREAKEVEN (EMERGENCY SHOCK {ret_pct:+.2f}%)"
                        wa_event = "BE_HIT"
                elif "INVALIDATION" in exit_reason or "ORDER_BLOCK" in exit_reason:
                    audit_status = "LOST_SL"
                    outcome_label = f"🔴 LOST (OB INTRABAR INVALIDATION {ret_pct:+.2f}%)"
                    wa_event = "SL_HIT"
                else:
                    audit_status = "LOST_SL"
                    outcome_label = "🔴 LOST (SL HIT)"
                    wa_event = "SL_HIT"
            elif "TAKE_PROFIT_3" in exit_reason or "TP3" in exit_reason:
                audit_status = "WON_TP3"
                outcome_label = "🟢 WON (TP3 HIT)"
                wa_event = "TP3_HIT"
                tp1_hit = True
                tp2_hit = True
                tp3_hit = True
            elif "TAKE_PROFIT_2" in exit_reason or "TP2" in exit_reason:
                audit_status = "WON_TP2"
                outcome_label = "🟢 WON (TP2 HIT)"
                wa_event = "TP2_HIT"
                tp1_hit = True
                tp2_hit = True
            elif "TAKE_PROFIT_1" in exit_reason or "TP1" in exit_reason or "TAKE_PROFIT" in exit_reason:
                audit_status = "WON_TP1"
                outcome_label = "🟢 WON (TP1 HIT)"
                wa_event = "TP1_HIT"
                tp1_hit = True
            elif "HORIZON_EXPIRY" in exit_reason or "EXPIRY" in exit_reason:
                if ret_pct >= 0.10:
                    audit_status = "WON_EXP_PROFIT"
                    outcome_label = f"🟢 WON (EXP PROFIT {ret_pct:+.2f}%)"
                    wa_event = "EXPIRED"
                elif ret_pct <= -0.10:
                    audit_status = "LOST_EXP"
                    outcome_label = f"🔴 LOST (EXPIRY {ret_pct:+.2f}%)"
                    wa_event = "EXPIRED"
                else:
                    audit_status = "BREAKEVEN_EXP"
                    outcome_label = f"⚪ BREAKEVEN (EXPIRY {ret_pct:+.2f}%)"
                    wa_event = "BE_HIT"
            else:
                audit_status = "CLOSED"
                outcome_label = f"CLOSED ({exit_reason})"
                wa_event = "CLOSED"

            # Automated WhatsApp Signal Outcome Notification Dispatch
            try:
                from app.services.whatsapp_service import whatsapp_service
                sig_dict = dict(closed_record)
                sig_dict["signal_id"] = closed_record.get("trade_id") or closed_record.get("signal_id")
                sig_dict["outcome_label"] = outcome_label
                sig_dict["status"] = audit_status
                whatsapp_service.emit_signal_outcome(sig_dict, wa_event, exit_p, ret_pct)
            except Exception as wa_err:
                print(f"[WHATSAPP ❌] Error emitting exit outcome {closed_record.get('trade_id')}: {wa_err}", flush=True)

            # 1. Update CSV: trader_signals_tracker.csv
            csv_path = os.path.join(EXPORT_DIR, "trader_signals_tracker.csv")
            if os.path.exists(csv_path):
                import csv
                updated_rows = []
                csv_changed = False
                with open(csv_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    fieldnames = reader.fieldnames
                    for row in reader:
                        r_sid = str(row.get("signal_id", "")).strip()
                        r_sym = str(row.get("symbol", "")).strip().upper()
                        r_hz = str(row.get("horizon", "")).strip().upper()
                        r_norm_hz = "15M" if "15" in r_hz else ("24H" if ("24" in r_hz or "1D" in r_hz) else "1H")
                        r_st = str(row.get("status", "")).strip().upper()

                        is_id_match = bool(rec_sid and r_sid == rec_sid)
                        is_match = is_id_match or (
                            (r_sym == sym or r_sym.replace("/", "") == sym.replace("/", ""))
                            and (r_norm_hz == norm_hz)
                            and r_st in ["PENDING_EVALUATION", "ACTIVE", "PENDING_LIMIT", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"]
                        )
                        if is_match and not csv_changed:
                            row["status"] = audit_status
                            row["outcome_label"] = outcome_label
                            row["exit_price"] = str(round(exit_p, 6))
                            row["current_price"] = str(round(exit_p, 6))
                            row["realized_return_pct"] = f"{ret_pct:+.2f}%"
                            row["evaluated_at_utc"] = closed_at
                            if rec_sl > 0 and "sl_price" in (fieldnames or []):
                                row["sl_price"] = str(round(rec_sl, 6))
                            if "is_tp1_locked" in (fieldnames or []):
                                row["is_tp1_locked"] = str(bool(tp1_hit))
                            if "is_tp2_locked" in (fieldnames or []):
                                row["is_tp2_locked"] = str(bool(tp2_hit))
                            if "peak_price_seen" in (fieldnames or []) and rec_peak > 0:
                                prev_pk = float(row.get("peak_price_seen") or 0.0) if str(row.get("peak_price_seen") or "").strip() not in ("", "None") else 0.0
                                row["peak_price_seen"] = str(round(max(prev_pk, rec_peak, exit_p), 6))
                            if "trough_price_seen" in (fieldnames or []) and rec_trough > 0:
                                prev_tr = float(row.get("trough_price_seen") or 0.0) if str(row.get("trough_price_seen") or "").strip() not in ("", "None") else 0.0
                                row["trough_price_seen"] = str(round(min(prev_tr, rec_trough, exit_p) if prev_tr > 0 else min(rec_trough, exit_p), 6))
                            if "max_potential_gain_pct" in (fieldnames or []):
                                prev_mfe = float(row.get("max_potential_gain_pct") or 0.0) if str(row.get("max_potential_gain_pct") or "").strip() not in ("", "None") else 0.0
                                row["max_potential_gain_pct"] = str(round(max(prev_mfe, rec_mfe), 2))
                            csv_changed = True
                        updated_rows.append(row)

                if csv_changed and fieldnames:
                    tmp_f = f"{csv_path}.tmp.{time.time_ns()}"
                    with open(tmp_f, "w", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(updated_rows)
                    os.replace(tmp_f, csv_path)

            # 2. Update MySQL Database directly
            try:
                from app.database import SessionLocal
                from app.models.signal import SignalAudit
                from sqlalchemy import or_

                db = SessionLocal()
                try:
                    db_sig = None
                    if rec_sid:
                        db_sig = db.query(SignalAudit).filter(SignalAudit.signal_id == rec_sid).first()
                    if not db_sig:
                        db_sig = db.query(SignalAudit).filter(
                            or_(SignalAudit.symbol == sym, SignalAudit.symbol == sym.replace("/", "")),
                            SignalAudit.status.in_(["PENDING_EVALUATION", "ACTIVE", "PENDING_LIMIT", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"])
                        ).order_by(SignalAudit.id.desc()).first()

                    if db_sig:
                        db_sig.status = audit_status
                        db_sig.outcome_label = outcome_label
                        db_sig.exit_price = round(exit_p, 6)
                        db_sig.realized_return_pct = round(ret_pct, 2)
                        db_sig.evaluated_at_utc = closed_at
                        if rec_sl > 0:
                            db_sig.sl_price = round(rec_sl, 6)
                        if rec_peak > 0:
                            db_sig.peak_price_seen = round(max(float(db_sig.peak_price_seen or 0.0), rec_peak, exit_p), 6)
                        if rec_trough > 0:
                            prev_tr = float(db_sig.trough_price_seen or 0.0)
                            db_sig.trough_price_seen = round(min(prev_tr, rec_trough, exit_p) if prev_tr > 0 else min(rec_trough, exit_p), 6)
                        db_sig.max_potential_gain_pct = round(max(float(db_sig.max_potential_gain_pct or 0.0), rec_mfe), 2)
                        db.commit()
                        print(f"[PAPER-AUDIT BRIDGE 🔗] Successfully synced tick exit to MySQL for {sym} ({norm_hz}): {outcome_label}")
                finally:
                    db.close()
            except Exception as db_err:
                pass

            # 3. Synchronize to v16_dynamic_states.json and v16_immutable_signals.json
            try:
                dyn_path = os.path.join(EXPORT_DIR, "v16_dynamic_states.json")
                target_k = None
                if os.path.exists(dyn_path):
                    with open(dyn_path, "r", encoding="utf-8") as df:
                        dyn_data = json.load(df)
                    if rec_sid and rec_sid in dyn_data:
                        target_k = rec_sid
                    if not target_k:
                        for k, v in dyn_data.items():
                            if (sym in k or sym.replace("/", "") in k) and (norm_hz in k or v.get("horizon") == norm_hz):
                                target_k = k
                                break
                    if not target_k:
                        for k in dyn_data.keys():
                            if sym in k or sym.replace("/", "") in k:
                                target_k = k
                                break
                    if target_k and target_k in dyn_data:
                        dyn_data[target_k]["status"] = audit_status
                        dyn_data[target_k]["outcome_label"] = outcome_label
                        dyn_data[target_k]["exit_price"] = round(exit_p, 6)
                        dyn_data[target_k]["current_price"] = round(exit_p, 6)
                        if rec_sl > 0:
                            dyn_data[target_k]["current_sl"] = round(rec_sl, 6)
                            if tp1_hit or closed_record.get("is_breakeven_locked"):
                                dyn_data[target_k]["locked_sl"] = round(rec_sl, 6)
                                dyn_data[target_k]["trailing_sl"] = round(rec_sl, 6)
                        dyn_data[target_k]["is_tp1_locked"] = bool(tp1_hit)
                        dyn_data[target_k]["is_tp2_locked"] = bool(tp2_hit)
                        dyn_data[target_k]["is_risk_free"] = bool(tp1_hit or closed_record.get("is_breakeven_locked"))
                        dyn_data[target_k]["mfe_pct"] = max(float(dyn_data[target_k].get("mfe_pct") or 0.0), rec_mfe)
                        dyn_data[target_k]["mae_pct"] = max(float(dyn_data[target_k].get("mae_pct") or 0.0), rec_mae)
                        dyn_data[target_k]["realized_return_pct"] = round(ret_pct, 2)
                        dyn_data[target_k]["unrealized_net_pnl_pct"] = round(ret_pct, 2)
                        dyn_data[target_k]["updated_at_utc"] = closed_at
                        tmp_dp = f"{dyn_path}.tmp.{time.time_ns()}"
                        with open(tmp_dp, "w", encoding="utf-8") as df:
                            json.dump(dyn_data, df, indent=2)
                        os.replace(tmp_dp, dyn_path)

                imm_path = os.path.join(EXPORT_DIR, "v16_immutable_signals.json")
                if os.path.exists(imm_path):
                    with open(imm_path, "r", encoding="utf-8") as imf:
                        imm_data = json.load(imf)
                    imm_k = target_k if target_k in imm_data else None
                    if not imm_k:
                        for k in imm_data.keys():
                            if sym in k or sym.replace("/", "") in k:
                                imm_k = k
                                break
                    if imm_k and imm_k in imm_data:
                        imm_data[imm_k]["status"] = audit_status
                        tmp_im = f"{imm_path}.tmp.{time.time_ns()}"
                        with open(tmp_im, "w", encoding="utf-8") as imf:
                            json.dump(imm_data, imf, indent=2)
                        os.replace(tmp_im, imm_path)
            except Exception:
                pass

            # 4. Synchronize trade outcome to StrategyRegistry for dynamic Bayesian prior calibration
            try:
                from app.quant_v16.strategies import StrategyRegistry
                # Invariant: breakeven is NEVER counted as a win!
                is_win = bool(audit_status.startswith("WON_") and not any(b in audit_status for b in ["BREAKEVEN", "TIER0_BE", "STOP_LOSS_BREAKEVEN"]))
                strat_name = closed_record.get("strategy") or closed_record.get("canonical_strategy") or closed_record.get("strategy_archetype")
                regime_name = closed_record.get("regime") or closed_record.get("market_regime")
                if strat_name:
                    strat_reg = StrategyRegistry()
                    strat_reg.record_trade_outcome(
                        strategy_id=str(strat_name),
                        is_win=is_win,
                        net_return_pct=ret_pct,
                        regime=str(regime_name) if regime_name else None
                    )
            except Exception:
                pass
        except Exception as err:
            print(f"[PAPER-AUDIT BRIDGE ⚠️] Error syncing paper exit: {err}")

    def sync_cancelled_order_to_tracker(self, rec: Dict[str, Any]):
        """
        Real-Time Cancellation Bridge:
        Instantly synchronizes resting limit cancellations into:
        1. trader_signals_tracker.csv
        2. MySQL signals_tracker (SignalAudit)
        3. v16_dynamic_states.json
        4. WhatsApp notification queue
        Eliminating all discrepancies across dashboards.
        """
        try:
            sym = str(rec.get("symbol", "")).strip().upper()
            sig_id = rec.get("signal_id")
            hz = str(rec.get("horizon", "1H")).strip().upper()
            norm_hz = "15M" if "15" in hz else ("24H" if any(x in hz for x in ["24", "1D", "SWING", "MACRO"]) else "1H")
            reason = str(rec.get("cancellation_reason", "CANCELLED"))
            detail = str(rec.get("cancellation_detail", ""))
            limit_p = float(rec.get("optimal_entry_limit", 0.0) or 0.0)
            market_p = float(rec.get("cancel_market_price", 0.0) or 0.0)
            live_exit_p = market_p if market_p > 0 else limit_p
            now_utc = datetime.now(timezone.utc)
            cancelled_at = rec.get("cancelled_at_utc") or now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

            if "ORDER_BLOCK_INVALIDATED" in reason:
                audit_status = "CANCELLED_OB_INVALIDATED"
                outcome_label = "🛑 CANCELLED (OB INVALIDATED)"
            elif "SPREAD_BLOWOUT" in reason or "MACRO_EVENT_BLACKOUT" in reason or "MACRO_BLOWOUT" in reason:
                audit_status = "CANCELLED_VOLATILITY_BLOWOUT"
                outcome_label = "🛑 CANCELLED (VOLATILITY BLOWOUT)"
            else:
                audit_status = "EXPIRED_HORIZON"
                outcome_label = "⏱️ EXPIRED"

            # 1. Update CSV: trader_signals_tracker.csv
            csv_path = os.path.join(EXPORT_DIR, "trader_signals_tracker.csv")
            if os.path.exists(csv_path):
                import csv
                updated_rows = []
                csv_changed = False
                with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f)
                    fieldnames = reader.fieldnames
                    for row in reader:
                        r_sid = str(row.get("signal_id", "")).strip()
                        r_sym = str(row.get("symbol", "")).strip().upper()
                        r_hz = str(row.get("horizon", "")).strip().upper()
                        r_norm_hz = "15M" if "15" in r_hz else ("24H" if any(x in r_hz for x in ["24", "1D", "SWING", "MACRO"]) else "1H")
                        r_st = str(row.get("status", "")).strip().upper()

                        r_date = str(row.get("date_utc", "")).strip()
                        r_time = str(row.get("time_utc", "")).strip()
                        sig_time = f"{r_date} {r_time}".strip()
                        is_time_ok = (not sig_time) or (str(cancelled_at).replace(" UTC", "") >= sig_time.replace(" UTC", ""))

                        is_match = (
                            (sig_id and r_sid == sig_id)
                            or (
                                not sig_id
                                and (r_sym == sym or r_sym.replace("/", "") == sym.replace("/", ""))
                                and (r_norm_hz == norm_hz)
                                and is_time_ok
                            )
                        )
                        # Never overwrite active running trades or protected breakeven trades with resting cancellations
                        if is_match and r_st in ["PENDING_LIMIT", "RESTING_LIMIT", "PENDING_EVALUATION"] and not csv_changed:
                            row["status"] = audit_status
                            row["outcome_label"] = outcome_label
                            if live_exit_p > 0:
                                row["exit_price"] = str(round(live_exit_p, 6))
                                if "current_price" in row:
                                    row["current_price"] = str(round(live_exit_p, 6))
                            row["realized_return_pct"] = "0.00%"
                            row["evaluated_at_utc"] = cancelled_at
                            csv_changed = True
                        updated_rows.append(row)

                if csv_changed and fieldnames:
                    tmp_f = f"{csv_path}.tmp.{time.time_ns()}"
                    with open(tmp_f, "w", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                        writer.writeheader()
                        writer.writerows(updated_rows)
                    os.replace(tmp_f, csv_path)

            # 2. Update MySQL Database directly
            try:
                from app.database import SessionLocal
                from app.models.signal import SignalAudit
                from sqlalchemy import or_

                db = SessionLocal()
                try:
                    db_sig = None
                    if sig_id:
                        db_sig = db.query(SignalAudit).filter(SignalAudit.signal_id == sig_id).first()
                    if not db_sig:
                        db_sig = db.query(SignalAudit).filter(
                            or_(SignalAudit.symbol == sym, SignalAudit.symbol == sym.replace("/", "")),
                            SignalAudit.status.in_(["PENDING_EVALUATION", "ACTIVE", "PENDING_LIMIT", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"])
                        ).order_by(SignalAudit.id.desc()).first()

                    if db_sig:
                        db_sig.status = audit_status
                        db_sig.outcome_label = outcome_label
                        if live_exit_p > 0:
                            db_sig.exit_price = round(live_exit_p, 6)
                            if hasattr(db_sig, "current_price"):
                                db_sig.current_price = round(live_exit_p, 6)
                        db_sig.realized_return_pct = 0.0
                        db_sig.evaluated_at_utc = cancelled_at
                        db.commit()
                        print(f"[PAPER-AUDIT BRIDGE 🔗] Successfully synced resting order cancellation to MySQL for {sym} ({norm_hz}): {outcome_label}")
                finally:
                    db.close()
            except Exception as db_err:
                pass

            # 3. Update v16_dynamic_states.json
            try:
                dyn_path = os.path.join(EXPORT_DIR, "v16_dynamic_states.json")
                if os.path.exists(dyn_path):
                    with open(dyn_path, "r", encoding="utf-8") as df:
                        dyn_data = json.load(df)
                    target_k = sig_id if sig_id in dyn_data else None
                    if not target_k:
                        for k, v in dyn_data.items():
                            if sym in k or sym.replace("/", "") in k:
                                target_k = k
                                break
                    if target_k and target_k in dyn_data:
                        existing_curr_p = float(dyn_data[target_k].get("current_price") or 0.0)
                        best_curr_p = market_p if market_p > 0 else (existing_curr_p if existing_curr_p > 0 else limit_p)
                        dyn_data[target_k]["status"] = audit_status
                        dyn_data[target_k]["outcome_label"] = outcome_label
                        dyn_data[target_k]["exit_price"] = round(best_curr_p, 6) if best_curr_p > 0 else existing_curr_p
                        dyn_data[target_k]["current_price"] = dyn_data[target_k]["exit_price"]
                        dyn_data[target_k]["realized_return_pct"] = 0.0
                        dyn_data[target_k]["unrealized_net_pnl_pct"] = 0.0
                        dyn_data[target_k]["updated_at_utc"] = cancelled_at
                        tmp_dp = f"{dyn_path}.tmp.{time.time_ns()}"
                        with open(tmp_dp, "w", encoding="utf-8") as df:
                            json.dump(dyn_data, df, indent=2)
                        os.replace(tmp_dp, dyn_path)

                imm_path = os.path.join(EXPORT_DIR, "v16_immutable_signals.json")
                if os.path.exists(imm_path):
                    with open(imm_path, "r", encoding="utf-8") as imf:
                        imm_data = json.load(imf)
                    imm_k = target_k if target_k in imm_data else None
                    if not imm_k:
                        for k in imm_data.keys():
                            if sym in k or sym.replace("/", "") in k:
                                imm_k = k
                                break
                    if imm_k and imm_k in imm_data:
                        imm_data[imm_k]["status"] = audit_status
                        tmp_im = f"{imm_path}.tmp.{time.time_ns()}"
                        with open(tmp_im, "w", encoding="utf-8") as imf:
                            json.dump(imm_data, imf, indent=2)
                        os.replace(tmp_im, imm_path)
            except Exception:
                pass

            # 4. Dispatch WhatsApp Cancellation Alert
            try:
                from app.services.whatsapp_service import whatsapp_service
                sig_dict = {
                    "signal_id": sig_id or f"{sym}_{norm_hz}",
                    "symbol": sym,
                    "horizon": norm_hz,
                    "direction": rec.get("direction", "LONG"),
                    "entry_price": limit_p,
                    "quality_grade": rec.get("quality_grade", "Grade A"),
                    "meta_win_prob_pct": rec.get("meta_win_probability", 50.0),
                    "cancellation_reason": reason,
                    "cancellation_detail": detail,
                    "outcome_label": outcome_label
                }
                whatsapp_service.emit_signal_outcome(sig_dict, "LIMIT_CANCELLED", limit_p, 0.0)
            except Exception:
                pass

        except Exception as err:
            print(f"[PAPER-AUDIT BRIDGE ⚠️] Error syncing paper cancellation: {err}")

    def purge_invalid_positions(self):
        """Immediately removes any delisted or dead pairs from open_positions and persists ledger."""
        with self._lock:
            valid_positions = []
            purged = []
            for pos in self.data.get("open_positions", []):
                sym = pos.get("symbol", "")
                entry_p = float(pos.get("entry_price", 0.0))
                if UniverseFilter.is_valid_crypto_pair(sym, price=entry_p) and entry_p > 0.0001:
                    valid_positions.append(pos)
                else:
                    purged.append(sym)
            if purged:
                print(f"[PAPER BOT 🧹 PURGE] Explicitly purged invalid positions: {purged}")
                self.data["open_positions"] = valid_positions
                desks = self.data.get("desks", {})
                for d_key, d_val in desks.items():
                    d_val["active_slots"] = sum(1 for p in valid_positions if p.get("desk") == d_key)
                self.save_ledger()

    def start_tick_daemon(self, ticker_fetch_fn, interval_seconds: float = 0.5, partition_check_fn = None, latency_fetch_fn = None, order_book_voids_fn = None, depth_fetch_fn = None, cvd_fetch_fn = None):
        """Starts the decoupled 24/7 high-speed sub-second position monitoring thread with latency, depth, and outage awareness."""
        if self._running:
            return
        self._running = True

        def _tick_loop():
            print(f"[PAPER BOT [HEARTBEAT]] Standalone 24/7 Tick Watcher Active (Sub-second polling every {interval_seconds}s)")
            current_interval = interval_seconds
            consecutive_partitions = 0
            while self._running:
                try:
                    if self.data["open_positions"]:
                        is_partition = partition_check_fn() if partition_check_fn else False
                        latency_ms = latency_fetch_fn() if latency_fetch_fn else 0.0
                        voids = order_book_voids_fn() if order_book_voids_fn else None

                        if is_partition:
                            consecutive_partitions += 1
                            # Adaptive backoff (1.5s - 4.0s) with desynchronization jitter (+/- 0.1s)
                            jitter = random.uniform(-0.1, 0.1)
                            current_interval = min(4.0, max(1.5, 1.5 + (consecutive_partitions * 0.5))) + jitter
                            # Pass empty dict to avoid redundant ticker_fetch_fn calls during active partition
                            self.on_tick({}, is_market_partition_active=True, tick_latency_ms=latency_ms, order_book_voids=voids)
                        else:
                            consecutive_partitions = 0
                            current_interval = interval_seconds
                            prices = ticker_fetch_fn()
                            if prices:
                                # Microstructure depth and inflow evaluation for active resting limit orders
                                depths = {}
                                cvds = {}
                                resting_syms = set()
                                with self._lock:
                                    for p in self.data.get("open_positions", []):
                                        if p.get("is_limit_resting") or p.get("status") == "RESTING_LIMIT":
                                            resting_syms.add(p.get("symbol"))

                                if depth_fetch_fn and resting_syms:
                                    for s in resting_syms:
                                        try:
                                            d = depth_fetch_fn(s)
                                            if d:
                                                depths[s] = d
                                        except Exception:
                                            pass

                                if cvd_fetch_fn and resting_syms:
                                    for s in resting_syms:
                                        try:
                                            c = cvd_fetch_fn(s)
                                            if c:
                                                cvds[s] = c
                                        except Exception:
                                            pass

                                self.on_tick(
                                    prices,
                                    is_market_partition_active=False,
                                    tick_latency_ms=latency_ms,
                                    order_book_voids=voids,
                                    order_book_depths=depths if depths else None,
                                    cvd_metrics=cvds if cvds else None
                                )
                except Exception as e:
                    pass
                time.sleep(max(0.1, current_interval))

        self._worker_thread = threading.Thread(target=_tick_loop, daemon=True, name="paper_bot_tick_daemon")
        self._worker_thread.start()

    def stop_tick_daemon(self):
        self._running = False
