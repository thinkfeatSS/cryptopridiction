import math
import os
import json
import time
import threading
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from app.engine.config import EXPORT_DIR
from app.engine.scanner.filters import UniverseFilter
from app.quant_v16.entry_confirmation import format_dynamic_precision

class PaperTradingBot:
    """
    Subsystem 3: Standalone High-Speed 24/7 Paper Trading Execution Bot.
    - Decoupled from heavy machine learning scanning.
    - Runs a fast 1-2s tick watcher to monitor open positions.
    - Evaluates intra-candle fills, Tier-0 Breakeven ratchets, and TP partial scaling.
    - Multi-Desk Capital Allocation:
      1. ⚡ Scalp Desk (35% allocation, 2 max slots, 5x leverage)
      2. ⏳ Day Trading Desk (40% allocation, 2 max slots, 3x leverage)
      3. 🌊 Swing Desk (25% allocation, 1 max slot, 2x leverage)
    - Realistic Binance Futures fee ($0.0405% taker with BNB discount) and funding rates.
    """

    def __init__(self, ledger_file: str = None):
        self.ledger_file = ledger_file or os.path.join(EXPORT_DIR, "paper_trading_ledger.json")
        self.taker_fee_rate = 0.000405 # 0.045% with 10% BNB discount
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

                    if purged_symbols:
                        print(f"[PAPER BOT 🧹 PURGE] Evicted delisted/ghost positions from ledger: {purged_symbols}")
                        loaded["open_positions"] = valid_positions
                        # Resynchronize desk active slots
                        desks = loaded.get("desks", {})
                        for d_key, d_val in desks.items():
                            d_val["active_slots"] = sum(1 for p in valid_positions if p.get("desk") == d_key)

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
            except Exception:
                pass

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
                "scalp": {"name": "⚡ Scalp Desk", "allocated_usd": 350.0, "max_slots": 2, "active_slots": 0, "leverage": 5},
                "day": {"name": "⏳ Day Trading Desk", "allocated_usd": 400.0, "max_slots": 2, "active_slots": 0, "leverage": 3},
                "swing": {"name": "🌊 Swing Desk", "allocated_usd": 250.0, "max_slots": 1, "active_slots": 0, "leverage": 2}
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
                    except Exception:
                        pass

    def resolve_desk(self, timeframe_or_horizon: str) -> str:
        tf = str(timeframe_or_horizon).lower().strip()
        desks = self.data.get("desks", {})

        # 1. 24H / Daily Swing Desk (Check first so '4h' does not false-match '24h')
        if any(x in tf for x in ["24h", "1d", "daily", "swing", "macro"]):
            if "swing" in desks:
                return "swing"
            if "macro" in desks:
                return "macro"
            return list(desks.keys())[-1]

        # 2. 1H / Intraday Desk
        if any(x in tf for x in ["1h", "day", "intraday"]):
            if "day" in desks:
                return "day"
            if "intraday" in desks:
                return "intraday"
            return list(desks.keys())[0]

        # 3. 15M / Scalp Desk
        if any(x in tf for x in ["5m", "15m", "scalp"]):
            if "scalp" in desks:
                return "scalp"
            return list(desks.keys())[0]

        # Default fallback
        if "day" in desks:
            return "day"
        if "intraday" in desks:
            return "intraday"
        return list(desks.keys())[0]

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
                if btc_shield_state.get("is_ntz_active"):
                    print(f"[PAPER BOT 🛑 NTZ REJECT] Rejected trade entry: Macro BTC No Trade Zone is active ({btc_shield_state.get('reason')}).")
                    return False
                if btc_shield_state.get("status_code") == "NO_TRADE_ZONE":
                    print(f"[PAPER BOT 🛑 NTZ REJECT] Rejected trade entry: Macro BTC status is NO_TRADE_ZONE.")
                    return False
                if "NO_TRADE_ZONE" in str(btc_shield_state.get("altcoin_posture", "")):
                    print(f"[PAPER BOT 🛑 NTZ REJECT] Rejected trade entry: Altcoin posture is NO_TRADE_ZONE.")
                    return False
                if btc_shield_state.get("regime") == "FLASH_DUMP" or btc_shield_state.get("status_code") == "BEAR_CASCADE_BLACKOUT":
                    print(f"[PAPER BOT 🛑 NTZ REJECT] Rejected trade entry: BTC regime is {btc_shield_state.get('regime')} / {btc_shield_state.get('status_code')}.")
                    return False
                if "DEFENSIVE_CASH_ONLY" in str(btc_shield_state.get("altcoin_posture", "")):
                    print(f"[PAPER BOT 🛑 NTZ REJECT] Rejected trade entry: Altcoin posture is DEFENSIVE_CASH_ONLY.")
                    return False

            if not signal:
                return False

            # 0b. Reject if Asset is in No Trade Zone
            if signal.get("is_ntz_active", False):
                sym = signal.get("symbol", "UNKNOWN")
                print(f"[PAPER BOT 🛑 NTZ REJECT] Rejected trade entry for {sym}: Asset No Trade Zone is active ({signal.get('ntz_reason', 'NTZ Filter')}).")
                return False

            # 0c. Reject if Macro Economic Blackout or Volatility Pause is active (NWS-01)
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

            direction = signal.get("direction") or signal.get("dominant_direction")
            if direction not in ["LONG", "SHORT"]:
                return False

            # 2. Validate Horizon: Strictly 15M, 1H, or 24H
            horizon_raw = str(signal.get("horizon") or signal.get("active_signal_horizon") or signal.get("dominant_timeframe") or "").upper()
            if not any(h in horizon_raw for h in ["15M", "1H", "24H", "1D"]):
                return False

            if "15M" in horizon_raw:
                norm_horizon = "15M"
            elif "1H" in horizon_raw:
                norm_horizon = "1H"
            elif "24H" in horizon_raw or "1D" in horizon_raw:
                norm_horizon = "24H"
            else:
                return False

            symbol = signal.get("symbol")
            if not symbol:
                return False

            # 2b. Strictly Reject Delisted, Inactive, Synthetic, or Dead Pairs
            entry_p = float(signal.get("entry_price", signal.get("current_price", 0.0)))
            if not UniverseFilter.is_valid_crypto_pair(symbol, price=entry_p):
                print(f"[PAPER BOT 🛑 REJECT] Rejected trade entry for {symbol}: Token is delisted, inactive, or not an active Binance spot crypto pair.")
                return False

            # 3. Position Cap: Check if position already open on symbol
            for pos in self.data.get("open_positions", []):
                if pos.get("symbol") == symbol:
                    return False

            # 4. Resolve Desk strictly matching the horizon
            desks = self.data.get("desks", {})
            desk_key = self.resolve_desk(norm_horizon)
            desk = desks.get(desk_key)
            if not desk:
                desk_key = list(desks.keys())[0] if desks else "default"
                desk = desks.get(desk_key, {"name": "Standard Desk", "allocated_usd": 350.0, "max_slots": 2, "leverage": 3})

            # Check desk availability
            max_slots = int(desk.get("max_slots", 2))
            active_desk_count = sum(1 for p in self.data.get("open_positions", []) if p.get("desk") == desk_key)
            if active_desk_count >= max_slots:
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
                # Tier-0 BE thresholds raised (Fix RC-1): require stronger excursion before locking BE
                # Scalp: 1.2% → 2.0%, Day: 1.5% → 2.5%, Swing: 2.0% → 3.5%
                # These align with the TP1 proximity gate so Tier-0 doesn't fire before TP1 is approached
                "tier0_threshold_pct": 2.00 if desk_key == "scalp" else (2.50 if desk_key in ["day", "intraday"] else 3.50),
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
                "risk_reward_ratio": signal.get("risk_reward_ratio", "1:2.0"),
                "classifier_votes": signal.get("classifier_votes", ""),
                "regressor_votes": signal.get("regressor_votes", ""),
                "aligned_horizons": signal.get("aligned_horizons", []),
                "meta_win_probability": float(signal.get("meta_win_probability", 0.50)),
                "meta_model_type": signal.get("meta_model_type", "PER_COIN_DEDICATED"),
                "per_coin_models_active": bool(signal.get("per_coin_models_active", True)),
                "pattern_name": signal.get("pattern_name") or signal.get("decision"),
                "decision": signal.get("decision"),
                "zeiierman_rank": signal.get("zeiierman_rank"),
                "zeiierman_rank_label": signal.get("zeiierman_rank_label"),
                "order_block_setup": signal.get("order_block_setup"),
                "is_nested_smc": bool(signal.get("is_nested_smc", False)),
                "path_probabilities": signal.get("path_probabilities", {}),
                "p_tp1_pct": signal.get("p_tp1_pct"),
                "p_tp2_pct": signal.get("p_tp2_pct"),
                "p_tp3_pct": signal.get("p_tp3_pct"),
                "p_sl_pct": signal.get("p_sl_pct"),
                "fundamental_matrix": signal.get("fundamental_matrix"),
                "composite_fundamental_score": float(signal.get("composite_fundamental_score", 0.0)),
                "news_sentiment": signal.get("news_sentiment"),
                "catalyst_event": signal.get("catalyst_event"),
                "sizing_multiplier": float(signal.get("sizing_multiplier", 1.0))
            }

            if "open_positions" not in self.data:
                self.data["open_positions"] = []
            self.data["open_positions"].append(pos_record)
            self.data["total_fees_paid_usd"] = float(self.data.get("total_fees_paid_usd", 0.0)) + buy_fee

            # Keep desk active slots synchronized
            if desk_key in self.data.get("desks", {}):
                self.data["desks"][desk_key]["active_slots"] = active_desk_count + 1

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
            return True

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
            if not symbol:
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

            for pos in self.data.get("open_positions", []):
                if pos.get("symbol") == symbol:
                    return False
            for pos in self.data.get("shadow_positions", []):
                if pos.get("symbol") == symbol:
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

    def _create_cancellation_record(self, pos: Dict[str, Any], reason: str, detail: str) -> Dict[str, Any]:
        """Creates a standardized cancellation record for resting limit orders."""
        now_utc = datetime.now(timezone.utc)
        return {
            "trade_id": pos.get("trade_id"),
            "signal_id": pos.get("signal_id"),
            "symbol": pos.get("symbol"),
            "direction": pos.get("direction"),
            "horizon": pos.get("signal_horizon") or pos.get("horizon", "1H"),
            "optimal_entry_limit": pos.get("optimal_entry_limit", pos.get("entry_price")),
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

    def on_tick(self, live_prices: Dict[str, float], is_market_partition_active: bool = False, btc_shield_state: Optional[Dict[str, Any]] = None, tick_latency_ms: float = 0.0):
        """Evaluates live prices against open positions and resting limits with sub-second latency and impulse shields."""
        with self._lock:
            if not self.data["open_positions"]:
                return

            # Outage Position Frozen Shield: If exchange partition / global outage is active,
            # freeze stop-loss and horizon expiry to protect capital from stale/frozen executions.
            if is_market_partition_active:
                for pos in self.data["open_positions"]:
                    pos["safeguard_state"] = "SAFEGUARD_HOLD"
                    pos["safeguard_reason"] = "GLOBAL_OUTAGE_SHIELD_ACTIVE"
                return
            else:
                for pos in self.data["open_positions"]:
                    if pos.get("safeguard_state") == "SAFEGUARD_HOLD":
                        pos["safeguard_state"] = "ACTIVE_MONITORING"
                        pos.pop("safeguard_reason", None)

            remaining_positions = []
            for pos in self.data["open_positions"]:
                sym = pos["symbol"]
                entry_p = float(pos.get("entry_price", 0.0))
                # Auto-evict delisted, dead, or ghost pairs immediately
                if not UniverseFilter.is_valid_crypto_pair(sym, price=entry_p):
                    print(f"[PAPER BOT 🧹 PURGE] Evicted delisted/inactive position on tick: {sym}")
                    continue

                curr_p = live_prices.get(sym) or live_prices.get(sym.replace("/", "").replace(":USDT", ""))
                if not curr_p or curr_p <= 0:
                    remaining_positions.append(pos)
                    continue

                pos["current_price"] = curr_p
                entry_p = pos["entry_price"]
                direction = pos["direction"]
                leverage = pos["leverage"]
                norm_h = pos.get("signal_horizon") or pos.get("horizon", "1H")

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

                    # A. Extreme Macro Impulse / Adverse Blowout Guard
                    # Base threshold: 1.20% adverse penetration through resting limit.
                    # Latency-adaptive gate: If feed latency exceeds 800ms (e.g. queueing lag on REST),
                    # dynamically tighten the blowout gate to cancel earlier and eliminate knife-catch slippage:
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

                    # B. Chase Buffer Exceeded / Structure Invalidated
                    # Cancel if price rallies/drops away from admission point without pulling back to fill the resting limit
                    admission_p = float(pos.get("admission_price", pos.get("current_price", limit_p)))
                    chase_thresh = float(pos.get("chase_threshold_pct", 0.40))
                    max_allowed_long = max(float(pos.get("entry_zone_max", 0.0)), admission_p * (1.0 + chase_thresh / 100.0))
                    min_allowed_short = min(float(pos.get("entry_zone_min", float('inf'))), admission_p * (1.0 - chase_thresh / 100.0))
                    if direction == "LONG" and curr_p > max_allowed_long:
                        canc_rec = self._create_cancellation_record(pos, "CANCELLED_CHASE_EXCEEDED", "Price expanded beyond chase threshold without fill")
                        self._archive_cancelled_order(canc_rec, pos.get("desk"))
                        continue
                    elif direction == "SHORT" and curr_p < min_allowed_short:
                        canc_rec = self._create_cancellation_record(pos, "CANCELLED_CHASE_EXCEEDED", "Price dropped beyond chase threshold without fill")
                        self._archive_cancelled_order(canc_rec, pos.get("desk"))
                        continue

                    # C. Macro Regime / NTZ Shift Invalidation
                    if btc_shield_state:
                        if btc_shield_state.get("is_ntz_active") or btc_shield_state.get("status_code") == "NO_TRADE_ZONE" or btc_shield_state.get("regime") in ["RANGE_SQUEEZE", "FLASH_DUMP"]:
                            canc_rec = self._create_cancellation_record(pos, "CANCELLED_MACRO_NTZ_ACTIVATED", f"Macro BTC NTZ engaged ({btc_shield_state.get('reason', 'Market Shield')})")
                            self._archive_cancelled_order(canc_rec, pos.get("desk"))
                            continue

                    # D. Resting Order TTL Expiration (45m for 15M, 3h for 1H, 12h for 24H)
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

                    if is_in_zone and not prev_in_zone:
                        pos["bracket_touch_count"] = int(pos.get("bracket_touch_count", 0)) + 1
                    pos["_in_zone_last_tick"] = is_in_zone

                    if int(pos.get("bracket_touch_count", 0)) >= 3 and not is_in_zone:
                        canc_rec = self._create_cancellation_record(
                            pos,
                            "CANCELLED_MULTI_TOUCH_DEPLETION",
                            f"Zone depleted after {pos.get('bracket_touch_count')} re-tests without fill"
                        )
                        self._archive_cancelled_order(canc_rec, pos.get("desk"))
                        continue

                    # F. Clean Limit Fill (Touched limit within the safe bracket)
                    if (direction == "LONG" and curr_p <= limit_p) or (direction == "SHORT" and curr_p >= limit_p):
                        pos["status"] = "OPEN"
                        pos["is_limit_resting"] = False
                        pos["entry_price"] = limit_p
                        pos["current_price"] = limit_p
                        pos["opened_at"] = now_utc.isoformat()
                        pos["opened_at_utc"] = now_utc.isoformat()
                        print(f"[PAPER BOT [FILL] RESTING LIMIT FILLED] {sym} ({direction} {norm_h}) limit filled at ${limit_p:,.4f}!")
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

                    # EXT-01: Parabolic Trailing Ratchet for Runners (Section 20 & 24)
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

                    hit_sl = curr_p <= pos["sl_price"]
                else:
                    gain_pct = ((entry_p - curr_p) / entry_p) * 100.0
                    is_tp1 = curr_p <= tp1_p if tp1_p > 0 else False
                    is_tp2 = curr_p <= tp2_p if tp2_p > 0 else False
                    is_tp3 = curr_p <= tp3_p if tp3_p > 0 else False
                    pos["trough_price_seen"] = min(float(pos.get("trough_price_seen") or curr_p), curr_p)

                    # EXT-01: Parabolic Trailing Ratchet for Runners (Section 20 & 24)
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

                    hit_sl = curr_p >= pos["sl_price"]

                pos["unrealized_pnl_pct"] = gain_pct * leverage
                pos["unrealized_pnl_usd"] = (gain_pct / 100.0) * remaining_size_usd
                pos["peak_gain_pct"] = max(pos["peak_gain_pct"], gain_pct)

                # Emergency Macro Impulse Exit for Open Positions:
                # If an active position experiences an extreme sudden adverse spike (gain_pct <= -2.5%)
                # while BTC shield enters FLASH_DUMP or acute cascade, enforce emergency stop-out:
                is_macro_severe = bool(btc_shield_state and (
                    btc_shield_state.get("regime") in ["FLASH_DUMP"] or
                    btc_shield_state.get("status_code") == "FLASH_DUMP" or
                    "FLASH_DUMP" in str(btc_shield_state.get("altcoin_posture", ""))
                ))
                hit_emergency_exit = (gain_pct <= -2.50) and is_macro_severe

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

                norm_h = pos.get("signal_horizon") or pos.get("horizon", "1H")
                # Hold time extended (Fix RC-2): 15M → 2h, 1H → 6h, 24H stays 48h
                max_hold_secs = 7200 if "15M" in norm_h else (172800 if any(x in norm_h for x in ["24H", "1D", "SWING", "MACRO"]) else 21600)
                hit_expiry = elapsed_secs >= max_hold_secs

                # -------------------------------------------------------------
                # Feature 5.2: Dynamic Time-Decay TP Compaction (Section 20 & Phase 5)
                # -------------------------------------------------------------
                if elapsed_secs >= (0.80 * max_hold_secs) and not pos.get("tp1_hit") and tp1_p > 0:
                    final_window = max(1.0, 0.20 * max_hold_secs)
                    elapsed_in_window = min(final_window, max(0.0, elapsed_secs - (0.80 * max_hold_secs)))
                    decay_lambda = math.exp(-2.5 * (elapsed_in_window / final_window))

                    if "original_tp1_price" not in pos:
                        pos["original_tp1_price"] = tp1_p

                    orig_tp1 = float(pos["original_tp1_price"])
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
                    elif direction == "SHORT" and cand_compacted < (entry_p - min_friction_buffer):
                        cand_p = format_dynamic_precision(cand_compacted)
                        if cand_p > tp1_p:
                            pos["tp1_price"] = cand_p
                            pos["is_tp_compacted"] = True
                            tp1_p = cand_p
                            is_tp1 = curr_p <= tp1_p

                # Tier-0 Breakeven Ratchet: Tied to TP1 proximity (90% of TP1 range touched)
                tp1_p_pos = float(pos.get("tp1_price", 0.0))
                if direction == "LONG":
                    tp1_proximity_reached = (tp1_p_pos > entry_p and curr_p >= (entry_p + (tp1_p_pos - entry_p) * 0.90))
                else:
                    tp1_proximity_reached = (tp1_p_pos < entry_p and curr_p <= (entry_p - (entry_p - tp1_p_pos) * 0.90))

                if not pos.get("is_breakeven_locked") and not pos.get("tp1_hit") and not pos.get("tp2_hit") and tp1_proximity_reached and pos["peak_gain_pct"] >= pos.get("tier0_threshold_pct", 2.50):
                    pos["is_breakeven_locked"] = True
                    pos["sl_price"] = entry_p * (1.0005 if direction == "LONG" else 0.9995)
                    try:
                        print(f"[PAPER BOT 🛡️] Tier-0 Breakeven Ratchet Activated for {sym}! Stop-loss locked at Entry.")
                    except Exception:
                        pass

                # Multi-Tranche Scale Check 1: TP1 Hit (Realize 50%, lock Breakeven, hold 50% for TP2)
                if policy == "MULTI_TRANCHE_SCALE" and has_multi_tp and is_tp1 and not pos.get("tp1_hit"):
                    pos["tp1_hit"] = True
                    t1_notional = initial_size_usd * 0.50
                    t1_gain = ((tp1_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp1_p) / entry_p) * 100.0
                    t1_gross = (t1_gain / 100.0) * t1_notional
                    t1_fee = (float(pos.get("entry_fee_usd", initial_size_usd * self.taker_fee_rate)) * 0.50) + (t1_notional * (1.0 + t1_gain / 100.0) * self.taker_fee_rate)
                    t1_spread = (float(pos.get("spread_bps", 4.0)) / 20000.0) * t1_notional if not pos.get("optimal_entry_limit") else 0.0
                    t1_slip = 0.0003 * t1_notional if not pos.get("optimal_entry_limit") else 0.0
                    t1_friction = t1_fee + t1_spread + t1_slip
                    t1_net = t1_gross - t1_friction

                    pos["total_realized_partial_usd"] = float(pos.get("total_realized_partial_usd", 0.0)) + t1_net
                    pos["total_gross_partial_usd"] = float(pos.get("total_gross_partial_usd", 0.0)) + t1_gross
                    pos["total_frictions_partial_usd"] = float(pos.get("total_frictions_partial_usd", 0.0)) + t1_friction
                    pos["remaining_position_size_usd"] = initial_size_usd * 0.50
                    pos["is_breakeven_locked"] = True
                    pos["sl_price"] = entry_p * (1.0005 if direction == "LONG" else 0.9995)
                    pos["status"] = "OPEN_TP1_LOCKED_BREAKEVEN"

                    try:
                        print(f"[PAPER BOT 🎯 TP1 SCALED] {sym} TP1 Hit at ${tp1_p:,.4f}! 50% locked (${t1_net:+,.2f}). SL ratcheted to Breakeven (${pos['sl_price']:,.4f}). Holding 50% for TP2.", flush=True)
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

                # Multi-Tranche Scale Check 2: TP2 Hit (Realize 30%, ratchet SL to TP1, hold 20% for TP3)
                if policy == "MULTI_TRANCHE_SCALE" and has_tp3 and is_tp2 and pos.get("tp1_hit") and not pos.get("tp2_hit"):
                    pos["tp2_hit"] = True
                    t2_notional = initial_size_usd * 0.30
                    t2_gain = ((tp2_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - tp2_p) / entry_p) * 100.0
                    t2_gross = (t2_gain / 100.0) * t2_notional
                    t2_fee = (float(pos.get("entry_fee_usd", initial_size_usd * self.taker_fee_rate)) * 0.30) + (t2_notional * (1.0 + t2_gain / 100.0) * self.taker_fee_rate)
                    t2_spread = (float(pos.get("spread_bps", 4.0)) / 20000.0) * t2_notional if not pos.get("optimal_entry_limit") else 0.0
                    t2_slip = 0.0003 * t2_notional if not pos.get("optimal_entry_limit") else 0.0
                    t2_friction = t2_fee + t2_spread + t2_slip
                    t2_net = t2_gross - t2_friction

                    pos["total_realized_partial_usd"] = float(pos.get("total_realized_partial_usd", 0.0)) + t2_net
                    pos["total_gross_partial_usd"] = float(pos.get("total_gross_partial_usd", 0.0)) + t2_gross
                    pos["total_frictions_partial_usd"] = float(pos.get("total_frictions_partial_usd", 0.0)) + t2_friction
                    pos["remaining_position_size_usd"] = initial_size_usd * 0.20
                    pos["sl_price"] = tp1_p
                    pos["status"] = "OPEN_TP2_LOCKED_TRAIL"

                    try:
                        print(f"[PAPER BOT 🎯 TP2 SCALED] {sym} TP2 Hit at ${tp2_p:,.4f}! 30% locked (${t2_net:+,.2f}). SL ratcheted to TP1 (${tp1_p:,.4f}). Holding 20% runner for TP3.", flush=True)
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

                # Check Exit Triggers (TP, SL, Horizon Expiry, or Emergency Macro Impulse)
                if hit_tp or hit_sl or hit_expiry or hit_emergency_exit:
                    if hit_emergency_exit:
                        exit_reason = "EMERGENCY_MACRO_IMPULSE_EXIT"
                        exit_p = curr_p
                    elif hit_tp3:
                        exit_reason = "TAKE_PROFIT_3"
                        exit_p = tp3_p
                    elif hit_tp2_final:
                        exit_reason = "TAKE_PROFIT_2"
                        exit_p = tp2_p
                    elif hit_tp1_final:
                        exit_reason = "TAKE_PROFIT_1"
                        exit_p = tp1_p
                    elif hit_sl:
                        if pos.get("tp2_hit"):
                            exit_reason = "TAKE_PROFIT_2_TRAIL_SL"
                        elif pos.get("tp1_hit"):
                            exit_reason = "STOP_LOSS_BREAKEVEN"
                        else:
                            exit_reason = "STOP_LOSS_BREAKEVEN" if pos.get("is_breakeven_locked") else "STOP_LOSS"
                        # Account for physical candle gap penetration / gap slippage:
                        sl_target = float(pos["sl_price"])
                        if direction == "LONG":
                            exit_p = min(sl_target, float(curr_p))
                        else:
                            exit_p = max(sl_target, float(curr_p))
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
                    exit_spread_usd = 0.0 if hit_tp else (spread_bps / 20000.0) * rem_notional
                    spread_drag_usd = entry_spread_usd + exit_spread_usd

                    # 3. Execution Slippage Drag
                    entry_slip_usd = 0.0 if entry_was_limit else (0.0003 * rem_notional)
                    exit_slip_usd = 0.0 if hit_tp else (0.0004 * rem_notional)
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

                    closed_record = {
                        "trade_id": pos["trade_id"],
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
                        "closed_at_utc": now_utc.isoformat()
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
                    print(f"[PAPER BOT 🏁] Position Closed: {sym} ({exit_reason}) | Outcome: {outcome} | Net PnL: ${net_pnl:+,.2f} ({realized_ret_pct:+.2f}%) | Friction: ${total_frictions:.2f}")
                    self._sync_paper_exit_to_audit(closed_record)
                else:
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
                    s_hz = spos.get("signal_horizon") or spos.get("horizon", "1H")

                    s_opened = datetime.fromisoformat(spos["opened_at_utc"].replace("Z", "+00:00")) if spos.get("opened_at_utc") else datetime.now(timezone.utc)
                    s_elapsed = (datetime.now(timezone.utc) - s_opened).total_seconds()
                    s_max_hold = 7200 if "15M" in s_hz else (172800 if any(x in s_hz for x in ["24H", "1D", "SWING", "MACRO"]) else 21600)

                    s_gain = ((curr_p - e_p) / e_p) * 100.0 if s_dir == "LONG" else ((e_p - curr_p) / e_p) * 100.0
                    spos["peak_gain_pct"] = max(spos.get("peak_gain_pct", 0.0), s_gain)

                    # Dynamic time decay on shadow TP1 if >80% TTL elapsed
                    s_tp1 = spos["tp1_price"]
                    if s_elapsed >= 0.80 * s_max_hold and not spos.get("tp1_hit"):
                        decay_w = max(1.0, 0.20 * s_max_hold)
                        decay_t = min(decay_w, max(0.0, s_elapsed - 0.80 * s_max_hold))
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
                    s_hit_expiry = s_elapsed >= s_max_hold

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

    def _sync_paper_partial_tp_to_audit(self, pos: Dict[str, Any], tp_stage: str, tp_price: float, gain_pct: float):
        """
        Real-Time Execution Bridge for Partial Scale-Out:
        Instantly synchronizes sub-second paper trade partial TP events (TP1 / TP2) into:
        1. trader_signals_tracker.csv & today_trader_signals_tracker.csv
        2. MySQL signals_tracker (SignalAudit)
        3. v16_dynamic_states.json & v16_immutable_signals.json
        Maintains lockstep consistency across terminal, audit ledger, and paper trading.
        """
        try:
            sym = str(pos.get("symbol", "")).strip().upper()
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

            # 1. Update CSV files: trader_signals_tracker.csv and today_trader_signals_tracker.csv
            for fname in ["trader_signals_tracker.csv", "today_trader_signals_tracker.csv"]:
                csv_path = os.path.join(EXPORT_DIR, fname)
                if os.path.exists(csv_path):
                    import csv
                    updated_rows = []
                    csv_changed = False
                    with open(csv_path, "r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        fieldnames = reader.fieldnames
                        for row in reader:
                            r_sym = str(row.get("symbol", "")).strip().upper()
                            r_hz = str(row.get("horizon", "")).strip().upper()
                            r_norm_hz = "15M" if "15" in r_hz else ("24H" if ("24" in r_hz or "1D" in r_hz) else "1H")
                            r_st = str(row.get("status", "")).strip().upper()

                            is_match = (
                                (r_sym == sym or r_sym.replace("/", "") == sym.replace("/", ""))
                                and (r_norm_hz == norm_hz)
                                and r_st in ["PENDING_EVALUATION", "ACTIVE", "PENDING_LIMIT", "TP1_LOCKED_BREAKEVEN"]
                            )
                            if is_match and not csv_changed:
                                row["status"] = audit_status
                                row["outcome_label"] = outcome_label
                                row["current_price"] = str(round(tp_price, 6))
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
                    db_sig = db.query(SignalAudit).filter(
                        or_(SignalAudit.symbol == sym, SignalAudit.symbol == sym.replace("/", "")),
                        SignalAudit.status.in_(["PENDING_EVALUATION", "ACTIVE", "PENDING_LIMIT", "TP1_LOCKED_BREAKEVEN"])
                    ).order_by(SignalAudit.id.desc()).first()

                    if db_sig:
                        db_sig.status = audit_status
                        db_sig.outcome_label = outcome_label
                        db_sig.current_price = round(tp_price, 6)
                        db_sig.updated_at_utc = updated_at
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
                        dyn_data[target_k]["is_breakeven_active"] = True
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
            hz = str(closed_record.get("horizon", "15M")).strip().upper()
            norm_hz = "15M" if "15" in hz else ("24H" if ("24" in hz or "1D" in hz) else "1H")
            exit_reason = str(closed_record.get("exit_reason", ""))
            exit_p = float(closed_record.get("exit_price", 0.0))
            ret_pct = float(closed_record.get("return_pct", 0.0))
            now_utc = datetime.now(timezone.utc)
            closed_at = closed_record.get("closed_at_utc") or closed_record.get("closed_at") or now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

            # Map paper exit reason to authoritative SignalAudit status and outcome label
            if "BREAKEVEN" in exit_reason or "TIER0" in exit_reason or exit_reason == "STOP_LOSS_BREAKEVEN":
                audit_status = "BREAKEVEN_GUARD"
                outcome_label = f"🛡️ BREAKEVEN (TIER-0 GUARD {ret_pct:+.2f}%)"
            elif "STOP_LOSS" in exit_reason:
                audit_status = "LOST_SL"
                outcome_label = "🔴 LOST (SL HIT)"
            elif "TAKE_PROFIT_3" in exit_reason or "TP3" in exit_reason:
                audit_status = "WON_TP3"
                outcome_label = "🟢 WON (TP3 HIT)"
            elif "TAKE_PROFIT_2" in exit_reason or "TP2" in exit_reason:
                audit_status = "WON_TP2"
                outcome_label = "🟢 WON (TP2 HIT)"
            elif "TAKE_PROFIT_1" in exit_reason or "TP1" in exit_reason or "TAKE_PROFIT" in exit_reason:
                audit_status = "WON_TP1"
                outcome_label = "🟢 WON (TP1 HIT)"
            elif "HORIZON_EXPIRY" in exit_reason or "EXPIRY" in exit_reason:
                if ret_pct >= 0.10:
                    audit_status = "WON_EXP_PROFIT"
                    outcome_label = f"🟢 WON (EXP PROFIT {ret_pct:+.2f}%)"
                elif ret_pct <= -0.10:
                    audit_status = "LOST_EXP"
                    outcome_label = f"🔴 LOST (EXPIRY {ret_pct:+.2f}%)"
                else:
                    audit_status = "BREAKEVEN_EXP"
                    outcome_label = f"⚪ BREAKEVEN (EXPIRY {ret_pct:+.2f}%)"
            else:
                audit_status = "CLOSED"
                outcome_label = f"CLOSED ({exit_reason})"

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
                        r_sym = str(row.get("symbol", "")).strip().upper()
                        r_hz = str(row.get("horizon", "")).strip().upper()
                        r_norm_hz = "15M" if "15" in r_hz else ("24H" if ("24" in r_hz or "1D" in r_hz) else "1H")
                        r_st = str(row.get("status", "")).strip().upper()
                        
                        is_match = (
                            (r_sym == sym or r_sym.replace("/", "") == sym.replace("/", ""))
                            and (r_norm_hz == norm_hz)
                            and r_st in ["PENDING_EVALUATION", "ACTIVE", "PENDING_LIMIT", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"]
                        )
                        if is_match and not csv_changed:
                            row["status"] = audit_status
                            row["outcome_label"] = outcome_label
                            row["exit_price"] = str(round(exit_p, 6))
                            row["realized_return_pct"] = f"{ret_pct:+.2f}%"
                            row["evaluated_at_utc"] = closed_at
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
                strat_name = closed_record.get("strategy") or closed_record.get("canonical_strategy")
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
            limit_p = float(rec.get("optimal_entry_limit", 0.0))
            now_utc = datetime.now(timezone.utc)
            cancelled_at = rec.get("cancelled_at_utc") or now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

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

                        is_match = (
                            (sig_id and r_sid == sig_id)
                            or (
                                (r_sym == sym or r_sym.replace("/", "") == sym.replace("/", ""))
                                and (r_norm_hz == norm_hz)
                                and r_st in ["PENDING_EVALUATION", "ACTIVE", "PENDING_LIMIT", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"]
                            )
                        )
                        if is_match and not csv_changed:
                            row["status"] = audit_status
                            row["outcome_label"] = outcome_label
                            if limit_p > 0:
                                row["exit_price"] = str(round(limit_p, 6))
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
                        if limit_p > 0:
                            db_sig.exit_price = round(limit_p, 6)
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
                        dyn_data[target_k]["status"] = audit_status
                        dyn_data[target_k]["outcome_label"] = outcome_label
                        dyn_data[target_k]["exit_price"] = round(limit_p, 6) if limit_p > 0 else dyn_data[target_k].get("current_price", 0.0)
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

    def start_tick_daemon(self, ticker_fetch_fn, interval_seconds: float = 0.5, partition_check_fn = None, latency_fetch_fn = None):
        """Starts the decoupled 24/7 high-speed sub-second position monitoring thread with latency and outage awareness."""
        if self._running:
            return
        self._running = True

        def _tick_loop():
            print(f"[PAPER BOT [HEARTBEAT]] Standalone 24/7 Tick Watcher Active (Sub-second polling every {interval_seconds}s)")
            while self._running:
                try:
                    if self.data["open_positions"]:
                        is_partition = partition_check_fn() if partition_check_fn else False
                        latency_ms = latency_fetch_fn() if latency_fetch_fn else 0.0
                        prices = ticker_fetch_fn()
                        if prices or is_partition:
                            self.on_tick(prices or {}, is_market_partition_active=is_partition, tick_latency_ms=latency_ms)
                except Exception as e:
                    pass
                time.sleep(interval_seconds)

        self._worker_thread = threading.Thread(target=_tick_loop, daemon=True, name="paper_bot_tick_daemon")
        self._worker_thread.start()

    def stop_tick_daemon(self):
        self._running = False
