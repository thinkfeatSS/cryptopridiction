import os
import sys
import time
import json
import logging
import threading
import queue
import uuid
import requests
from typing import Dict, Any, Optional, List, Union, Set
from datetime import datetime, timezone

from app.config import settings
from app.quant_v16.validation import safe_float, safe_ratio

logger = logging.getLogger("whatsapp_service")
logger.setLevel(logging.INFO)
if not logger.handlers:
    class _SafeStreamHandler(logging.StreamHandler):
        def emit(self, record):
            try:
                msg = self.format(record)
                stream = self.stream
                try:
                    stream.write(msg + self.terminator)
                except UnicodeEncodeError:
                    safe_msg = msg.encode("ascii", errors="backslashreplace").decode("ascii")
                    stream.write(safe_msg + self.terminator)
                self.flush()
            except Exception:
                self.handleError(record)

    _sh = _SafeStreamHandler(sys.stdout)
    _sh.setFormatter(logging.Formatter("[%(asctime)s] [%(name)s] %(message)s"))
    logger.addHandler(_sh)

# Optional Redis connection for atomic cluster-wide deduplication
try:
    import redis
    r_url = os.getenv("REDIS_URL", getattr(settings, "REDIS_URL", "redis://crypto_redis:6379/0"))
    # In Docker container, localhost/127.0.0.1 resolves to container itself; fallback to crypto_redis
    hosts_to_try = []
    if "localhost" in r_url or "127.0.0.1" in r_url:
        hosts_to_try.append(r_url.replace("localhost", "crypto_redis").replace("127.0.0.1", "crypto_redis"))
    hosts_to_try.append(r_url)
    hosts_to_try.append("redis://crypto_redis:6379/0")

    _redis_client = None
    HAS_REDIS = False
    for u in hosts_to_try:
        try:
            client = redis.Redis.from_url(u, decode_responses=True, socket_timeout=1.0, socket_connect_timeout=1.0)
            client.ping()
            _redis_client = client
            HAS_REDIS = True
            break
        except Exception:
            continue
except Exception:
    _redis_client = None
    HAS_REDIS = False

class WhatsAppService:
    """
    Automated WhatsApp Signal Dispatcher.
    - Connects Quant Engine events to WhatsApp Groups and WhatsApp Channels.
    - Supports Self-Hosted Evolution API (Baileys), Whapi.cloud, or Generic Webhooks.
    - Built-in Leaky Bucket Rate Limiter (anti-ban pacing).
    - Redis-backed / in-memory idempotency guard (zero duplicate alerts).
    """

    def __init__(self):
        self._queue: queue.Queue = queue.Queue(maxsize=1000)
        self._in_memory_dedup: Dict[str, float] = {}
        self._last_dispatch_ts: float = 0.0
        self._worker_thread: Optional[threading.Thread] = None
        self._running: bool = True
        self._lock = threading.Lock()
        self._broadcasted_signals: Set[str] = set()
        self._enabled_override: Optional[bool] = None

        # Persistent Alert Spool & Gateway Resilience
        export_dir = getattr(settings, "EXPORT_DIR", None) or os.getenv("EXPORT_DIR", "export_app_data")
        self._spool_file = os.path.join(export_dir, "whatsapp_alert_spool.json")
        self._dead_letter_file = os.path.join(export_dir, "whatsapp_dead_letter.json")
        self._spool: Dict[str, Dict[str, Any]] = {}
        self._max_retries: int = 5
        self._gateway_circuit_breaker_until: float = 0.0
        self._last_health_check_ts: float = 0.0
        self._gateway_connected: bool = True

        # Preload pending alerts from persistent disk spool
        self._load_spool_from_disk()
        
        # Start async consumer worker
        self._start_worker()

    def _save_spool_to_disk(self):
        """Persists pending outbound alerts atomically to disk so they survive restarts."""
        try:
            os.makedirs(os.path.dirname(self._spool_file), exist_ok=True)
            tmp_file = f"{self._spool_file}.tmp_{os.getpid()}_{threading.get_ident()}"
            with self._lock:
                data = list(self._spool.values())
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_file, self._spool_file)
        except Exception as e:
            logger.warning(f"[WHATSAPP ⚠️] Failed to persist alert spool: {e}")

    def _load_spool_from_disk(self):
        """Preloads pending alerts from disk spool on daemon/backend boot."""
        try:
            if os.path.exists(self._spool_file):
                with open(self._spool_file, "r", encoding="utf-8") as f:
                    items = json.load(f)
                now = time.time()
                restored = 0
                with self._lock:
                    for it in items:
                        msg_id = it.get("id") or str(uuid.uuid4())
                        it["id"] = msg_id
                        # Discard stale alerts older than 24 hours
                        if now - it.get("ts", now) < 86400.0:
                            self._spool[msg_id] = it
                            try:
                                self._queue.put_nowait(it)
                                restored += 1
                            except queue.Full:
                                break
                if restored > 0:
                    logger.info(f"[WHATSAPP 🔄] Restored {restored} pending alerts from persistent disk spool.")
        except Exception as e:
            logger.warning(f"[WHATSAPP ⚠️] Failed to load alert spool: {e}")

    def _archive_dead_letter(self, item: Dict[str, Any], reason: str = ""):
        """Archives dropped messages that exceeded max retries for audit."""
        try:
            os.makedirs(os.path.dirname(self._dead_letter_file), exist_ok=True)
            dead_entry = {
                "failed_at": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
                "item": item
            }
            dead_letters = []
            if os.path.exists(self._dead_letter_file):
                try:
                    with open(self._dead_letter_file, "r", encoding="utf-8") as f:
                        dead_letters = json.load(f)
                except Exception:
                    dead_letters = []
            dead_letters.append(dead_entry)
            if len(dead_letters) > 100:
                dead_letters = dead_letters[-100:]
            tmp_f = f"{self._dead_letter_file}.tmp_{os.getpid()}_{threading.get_ident()}"
            with open(tmp_f, "w", encoding="utf-8") as f:
                json.dump(dead_letters, f, indent=2)
            os.replace(tmp_f, self._dead_letter_file)
        except Exception:
            pass

    def _start_worker(self):
        """Starts background worker thread to process outbound messages with pacing."""
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._worker_thread = threading.Thread(
                target=self._process_queue,
                name="whatsapp_dispatcher_worker",
                daemon=True
            )
            self._worker_thread.start()

    def _get_setting(self, name: str, default: Any = None) -> Any:
        val = getattr(settings, name, None)
        if val is None or val == "":
            val = os.getenv(name, default)
        return val

    @property
    def enabled(self) -> bool:
        if self._enabled_override is not None:
            return self._enabled_override
        v = self._get_setting("WHATSAPP_ENABLED", "true")
        if isinstance(v, bool):
            return v
        return str(v).lower() in ("true", "1", "yes")

    @enabled.setter
    def enabled(self, val: Optional[bool]):
        self._enabled_override = val

    @property
    def gateway_type(self) -> str:
        return str(self._get_setting("WHATSAPP_GATEWAY_TYPE", "evolution_api")).lower()

    @property
    def api_url(self) -> str:
        return str(self._get_setting("WHATSAPP_API_URL", "http://whatsapp:8080")).rstrip('/')

    @property
    def api_key(self) -> str:
        return str(self._get_setting("WHATSAPP_API_KEY", "crypto_quant_secret_2026"))

    @property
    def instance_name(self) -> str:
        return str(self._get_setting("WHATSAPP_INSTANCE_NAME", "crypto_bot"))

    @property
    def group_id(self) -> str:
        return str(self._get_setting("WHATSAPP_GROUP_ID", "120363431167900107@g.us"))

    @property
    def channel_id(self) -> str:
        cid = str(self._get_setting("WHATSAPP_CHANNEL_ID", "") or "").strip()
        return cid

    @property
    def min_grade(self) -> str:
        return str(self._get_setting("WHATSAPP_MIN_GRADE", "ALL"))

    @property
    def min_win_prob(self) -> float:
        try:
            return float(self._get_setting("WHATSAPP_MIN_WIN_PROB", 0.0))
        except Exception:
            return 0.0

    @property
    def send_tp_updates(self) -> bool:
        v = self._get_setting("WHATSAPP_SEND_TP_UPDATES", "true")
        return v is True or str(v).lower() in ("true", "1", "yes")

    @property
    def send_sl_updates(self) -> bool:
        v = self._get_setting("WHATSAPP_SEND_SL_UPDATES", "true")
        return v is True or str(v).lower() in ("true", "1", "yes")

    @property
    def send_regime_alerts(self) -> bool:
        v = self._get_setting("WHATSAPP_SEND_REGIME_ALERTS", "true")
        return v is True or str(v).lower() in ("true", "1", "yes")

    @property
    def rate_limit_seconds(self) -> float:
        try:
            return float(self._get_setting("WHATSAPP_RATE_LIMIT_SECONDS", 2.0))
        except Exception:
            return 2.0

    # =========================================================================
    # DEDUPLICATION & IDEMPOTENCY
    # =========================================================================
    def is_already_sent(self, dedup_key: str, ttl_seconds: int = 86400) -> bool:
        """
        Returns True if this signal event was already dispatched within TTL.
        Uses atomic Redis key if available; falls back to in-memory TTL dictionary.
        """
        if not dedup_key:
            return False

        if HAS_REDIS and _redis_client:
            try:
                # SET key 1 EX ttl NX returns True if set (was not present), None/False if already present
                redis_key = f"whatsapp:sent:{dedup_key}"
                is_new = _redis_client.set(redis_key, "1", ex=ttl_seconds, nx=True)
                return not bool(is_new)
            except Exception as e:
                logger.warning(f"[WHATSAPP ⚠️] Redis dedup check error: {e}")

        # In-memory fallback
        with self._lock:
            now = time.time()
            # Clean expired items
            expired = [k for k, exp in self._in_memory_dedup.items() if exp < now]
            for k in expired:
                del self._in_memory_dedup[k]

            if dedup_key in self._in_memory_dedup:
                return True
            self._in_memory_dedup[dedup_key] = now + ttl_seconds
            return False

    # =========================================================================
    # QUALITY GATE & FILTERS
    # =========================================================================
    def passes_quality_gate(self, sig: Dict[str, Any], is_channel: bool = False) -> bool:
        """
        Determines whether a signal qualifies for automated broadcast.
        - Group: Sends signals admitted by SignalAuditTracker according to WHATSAPP_MIN_GRADE and WHATSAPP_MIN_WIN_PROB.
        - Channel: Grade A+, Grade A, or Meta-Win Prob >= 60%
        """
        raw_grade = str(sig.get("quality_grade") or sig.get("grade") or "").upper()
        try:
            grade_tier = int(sig.get("grade_tier", 2))
        except (ValueError, TypeError):
            grade_tier = 2
        raw_meta = sig.get("meta_win_prob_pct")
        if raw_meta is not None:
            win_prob = safe_float(raw_meta, 70.0)
        else:
            p_val = safe_float(sig.get("meta_win_prob"), 0.7)
            win_prob = p_val * 100.0 if p_val <= 1.0 else p_val
        conviction = safe_float(sig.get("conviction_pct") or sig.get("conviction"), 50.0)

        min_grade_setting = str(self.min_grade).upper()

        # Check grade classification flexibly (e.g. "A+", "A (INSTITUTIONAL)", "B (HIGH CONVICTION)")
        has_grade_a_plus = "A+" in raw_grade or "GRADE A+" in raw_grade
        has_grade_a = has_grade_a_plus or raw_grade.startswith("A ") or "GRADE A" in raw_grade or "A (" in raw_grade or (grade_tier <= 2)
        has_grade_b = has_grade_a or "GRADE B" in raw_grade or raw_grade.startswith("B ") or "B (" in raw_grade or (grade_tier <= 3)

        # Baseline: Grade C (or tier 4+) is strictly Watchlist / Defensive noise, never broadcast to traders
        if (grade_tier >= 4) or ("GRADE C" in raw_grade):
            return False

        # Strict NTZ Gate: NEVER broadcast any signal vetoed by Macro No Trade Zone
        dec = str(sig.get("decision", "")).upper()
        dirn = str(sig.get("dominant_direction") or sig.get("direction") or "").upper()
        if (
            sig.get("is_ntz_blocked")
            or sig.get("is_ntz_active")
            or dirn in ["NO_TRADE", "HOLD_VETOED", "HOLD"]
            or any(k in dec for k in ["NO TRADE ZONE", "HOLD (QUARANTINED)", "VETOED BY NO TRADE ZONE"])
        ):
            return False

        # If user sets "ALL", send all created signals of at least Grade B
        if min_grade_setting == "ALL":
            pass
        elif "GRADE B" in min_grade_setting or "B" in min_grade_setting:
            if not has_grade_b:
                return False
        else:
            # Baseline default: Grade must be A or A+
            if not has_grade_a:
                return False

        # Channel gate (higher hurdle for public channel)
        if is_channel:
            if not has_grade_a and win_prob < 60.0 and conviction < 70.0:
                return False

        # ML Win Probability gate (for public channel only or when strictly configured)
        min_prob = self.min_win_prob * 100.0 if self.min_win_prob <= 1.0 else self.min_win_prob
        if is_channel and min_prob > 0 and win_prob < min_prob and conviction < min_prob:
            return False

        return True

    # =========================================================================
    # MESSAGE FORMATTERS (WHATSAPP NATIVE MARKDOWN)
    # =========================================================================
    @staticmethod
    def _format_price(val: Any) -> str:
        try:
            f = float(val)
            if f <= 0.0:
                return "N/A"
            elif f >= 1000:
                return f"${f:,.2f}"
            elif f >= 1:
                return f"${f:.4f}"
            elif f >= 0.01:
                return f"${f:.6f}"
            elif f >= 0.0001:
                return f"${f:.8f}"
            else:
                # Dynamic precision for micro assets (PEPE, SHIB, etc.)
                s = f"{f:.10f}".rstrip('0')
                return f"${s}"
        except Exception:
            return f"${val}"

    @staticmethod
    def _extract_path_probabilities(sig: Dict[str, Any], base_win_prob: float) -> Dict[str, float]:
        """
        Extracts or calculates calibrated path probabilities for TP1, TP2, TP3, and SL.
        Returns percentage values (e.g., 78.5 for 78.5%).
        """
        def _to_pct(val: Any) -> Optional[float]:
            if val is None or val == "":
                return None
            try:
                f = float(val)
                return f * 100.0 if 0.0 < f <= 1.0 else f
            except Exception:
                return None

        # Base TP1 probability
        p_tp1 = _to_pct(sig.get("p_tp1")) or _to_pct(sig.get("p_tp1_pct")) or _to_pct(sig.get("prob_tp1")) or base_win_prob
        p_tp1 = max(15.0, min(95.0, p_tp1))

        # SL probability: P(SL before TP1) = 1.0 - P(TP1)
        p_sl = _to_pct(sig.get("p_sl")) or _to_pct(sig.get("p_sl_pct")) or _to_pct(sig.get("prob_sl")) or max(5.0, round(100.0 - p_tp1, 1))

        # TP2 probability: P(TP2) = P(TP1) * P(TP2 | TP1) (typically ~65% conditional)
        p_tp2 = _to_pct(sig.get("p_tp2")) or _to_pct(sig.get("p_tp2_pct")) or _to_pct(sig.get("prob_tp2")) or round(p_tp1 * 0.65, 1)

        # TP3 probability: P(TP3) = P(TP2) * P(TP3 | TP2) (typically ~55% conditional)
        p_tp3 = _to_pct(sig.get("p_tp3")) or _to_pct(sig.get("p_tp3_pct")) or _to_pct(sig.get("prob_tp3")) or round(p_tp2 * 0.55, 1)

        return {
            "tp1": round(p_tp1, 1),
            "tp2": round(p_tp2, 1),
            "tp3": round(p_tp3, 1),
            "sl": round(p_sl, 1)
        }

    def _format_horizon_display(self, sig: Dict[str, Any]) -> str:
        h = sig.get("horizon_name") or sig.get("horizon") or sig.get("duration_label") or sig.get("horizon_tag") or sig.get("horizon_key") or "⏳ Day Trade (1H)"
        h_str = str(h).strip()
        h_upper = h_str.upper()

        # Multi-Day Macro Horizons
        if "30D" in h_upper or "MONTHLY" in h_upper:
            return "🚀 Macro Trend (30D)"
        if "15D" in h_upper or "BIWEEKLY" in h_upper:
            return "🚀 Macro Trend (15D)"
        if "7D" in h_upper or "WEEKLY" in h_upper:
            return "🚀 Macro Trend (7D)"
        if "4D" in h_upper:
            return "🚀 Macro Trend (4D)"

        # Swing Trade Horizons (24H / 1D)
        if "24H" in h_upper or "1D" in h_upper or "MACRO" in h_upper or "DAILY" in h_upper:
            return "🌊 Swing Trade (1D)"

        # Day Trade Horizons (1H / 4H)
        if "4H" in h_upper:
            return "⏳ Day Trade (4H)"
        if "1H" in h_upper or "INTRADAY" in h_upper:
            return "⏳ Day Trade (1H)"

        # Scalp Horizons (15M / 30M)
        if "30M" in h_upper or "30" in h_upper:
            return "⚡ Scalp (30M)"
        if "15M" in h_upper or "15" in h_upper or "5M" in h_upper or "SCALP" in h_upper:
            return "⚡ Scalp (15M)"

        if "SWING" in h_upper:
            return "🌊 Swing Trade (1D)"

        return h_str

    def format_new_signal(self, sig: Dict[str, Any]) -> str:
        sym = sig.get("symbol", "BTC/USDT")
        direction = str(sig.get("dominant_direction") or sig.get("direction") or "LONG").upper()
        is_long = direction in ["LONG", "BULLISH", "BUY"]
        dir_emoji = "🟢 *LONG BUY*" if is_long else "🔴 *SHORT SELL*"
        horizon = self._format_horizon_display(sig)
        grade = sig.get("quality_grade") or sig.get("grade") or "Grade A"
        thesis_id = sig.get("trade_thesis_id") or sig.get("thesis_id") or "N/A"
        
        # Strategy Archetype / Execution Setup (Order Blocks, Breakdowns, Reversals, Sweeps)
        decision = (
            sig.get("decision")
            or sig.get("setup")
            or sig.get("setup_label")
            or sig.get("strategy_archetype")
            or (sig.get("order_block_setup") or {}).get("setup_label")
            or (sig.get("grade") if isinstance(sig.get("grade"), str) and "(" in sig.get("grade") else None)
            or ("🎯 INSTITUTIONAL ORDER-BLOCK RETEST (LONG)" if is_long else "🎯 ELITE BREAKDOWN EXECUTE (SHORT)")
        )
        decision_str = str(decision).strip()
        if not any(decision_str.startswith(icon) for icon in ["🎯", "🛑", "🚀", "✅", "⚪", "💎", "⚡", "⚖️"]):
            decision_display = f"🎯 {decision_str}"
        else:
            decision_display = decision_str

        conviction = safe_float(sig.get("conviction_pct") or sig.get("signal_score") or sig.get("conviction"), 75.0)
        raw_win = (
            sig.get("meta_win_prob_pct")
            or sig.get("win_probability_pct")
            or sig.get("p_tp1")
            or sig.get("meta_win_prob")
            or 70.0
        )
        f_win = safe_float(raw_win, 70.0)
        win_prob = f_win * 100.0 if 0.0 < f_win <= 1.0 else f_win
        
        # Calibrated path probabilities for targets and invalidation
        probs = self._extract_path_probabilities(sig, win_prob)

        # Predicted candle timeframe / resolution window
        pred_window = sig.get("predicted_window") or sig.get("predicted_window_str") or ""
        pred_close_utc = sig.get("predicted_close_utc") or sig.get("trade_close_str") or ""
        
        candle_time_str = ""
        if pred_close_utc and pred_close_utc != "N/A":
            candle_time_str = f"⏳ *Candle Close (UTC):* `{pred_close_utc}`"
        elif pred_window and pred_window != "N/A":
            candle_time_str = f"⏳ *Horizon Window:* `{pred_window}`"

        entry_val = safe_float(
            sig.get("entry_price")
            or sig.get("entry_price_initial")
            or sig.get("optimal_entry_price")
            or sig.get("current_price"),
            0.0
        )
        tp1_val = safe_float(sig.get("tp1_price") or sig.get("tp1_initial") or sig.get("tp1"), 0.0)
        tp2_val = safe_float(sig.get("tp2_price") or sig.get("tp2_initial") or sig.get("tp2"), 0.0)
        tp3_val = safe_float(sig.get("tp3_price") or sig.get("tp3_initial") or sig.get("tp3"), 0.0)
        sl_val = safe_float(sig.get("sl_price") or sig.get("sl_initial") or sig.get("current_sl") or sig.get("sl"), 0.0)

        entry = self._format_price(entry_val)
        tp1 = self._format_price(tp1_val)
        tp2 = self._format_price(tp2_val)
        tp3 = self._format_price(tp3_val)
        sl = self._format_price(sl_val)
        
        raw_rr = safe_ratio(sig.get("risk_reward_ratio") or sig.get("risk_reward"), 2.0)
        rr = f"1:{raw_rr:.1f}"

        exp_ret = safe_float(sig.get("expected_net_return") or sig.get("expected_return_pct") or sig.get("ev_net"), 3.5)
        market_shield = sig.get("market_shield") or sig.get("regime") or "BALANCED VOLATILITY"

        candle_line = f"{candle_time_str}\n" if candle_time_str else ""

        is_limit_pending = bool(sig.get("is_limit_pending") or "AWAIT PULLBACK" in decision_display or "AWAIT BOUNCE" in decision_display)
        optimal_entry_val = safe_float(sig.get("optimal_entry_price"), entry_val)
        curr_val = safe_float(sig.get("current_price"), entry_val)
        zone_min = sig.get("entry_zone_min")
        zone_max = sig.get("entry_zone_max")

        if is_limit_pending:
            if zone_min and zone_max and str(zone_min) != str(zone_max):
                zone_str = f"{self._format_price(zone_min)} – {self._format_price(zone_max)}"
            else:
                zone_str = self._format_price(optimal_entry_val)
            live_label = "Peak" if is_long else "Trough"
            action_warn = "DO NOT MARKET-BUY AT PEAK (Wait for Retest)" if is_long else "DO NOT MARKET-SHORT LOW (Wait for Bounce)"
            chase_note = f"• ⚠️ *Metric:* {sig.get('chase_warning')}\n" if sig.get('chase_warning') else ""
            anti_chase_block = (
                f"⚠️ *ANTI-CHASE POLICY ACTIVE*:\n"
                f"• Live {live_label}: *{self._format_price(curr_val)}*\n"
                f"{chase_note}"
                f"• 🛑 *{action_warn}*\n"
                f"• 🎯 *Resting Limit Zone:* *{zone_str}*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
            )
            entry_line = f"📍 *Optimal Limit {'Bid' if is_long else 'Ask'}:* {self._format_price(optimal_entry_val)}\n"
        else:
            anti_chase_block = ""
            entry_line = f"📍 *Entry Zone:* {entry}\n"

        # Fundamental & News Catalyst Intelligence
        fund_line = ""
        raw_news = sig.get("news_sentiment")
        news_sent = raw_news if isinstance(raw_news, dict) else ({"label": str(raw_news)} if raw_news else {})
        raw_cat = sig.get("catalyst_event")
        cat_ev = raw_cat if isinstance(raw_cat, dict) else ({"title": str(raw_cat)} if raw_cat else {})

        # If passed as JSON string (from CSV)
        if isinstance(sig.get("fundamental_matrix"), str) and sig["fundamental_matrix"]:
            try:
                fm = json.loads(sig["fundamental_matrix"])
                if isinstance(fm, dict):
                    news_sent = fm.get("news_sentiment") or news_sent
                    cat_ev = fm.get("catalyst_event") or cat_ev
            except Exception:
                pass

        news_lbl = (news_sent.get("label") if isinstance(news_sent, dict) else str(news_sent)) or sig.get("news_sentiment")
        news_sc = float((news_sent.get("score") if isinstance(news_sent, dict) else 0.0) or sig.get("news_score") or 0.0)
        top_hl = (news_sent.get("top_headline") if isinstance(news_sent, dict) else "") or (news_sent.get("recent_headlines", [""])[0] if isinstance(news_sent, dict) and news_sent.get("recent_headlines") else "")

        cat_title = (cat_ev.get("title") if isinstance(cat_ev, dict) else str(cat_ev)) or sig.get("catalyst_title")
        days_ev = cat_ev.get("days_until") if isinstance(cat_ev, dict) else None

        fund_parts = []
        if cat_title and cat_title != "None":
            days_str = f" (~{days_ev}d)" if days_ev is not None else ""
            fund_parts.append(f"🚀 *Catalyst:* {cat_title[:28]}{days_str}")
        if news_lbl and "NEUTRAL" not in news_lbl:
            fund_parts.append(f"📰 *News Flow:* {news_lbl} ({news_sc:+.2f})")
        elif top_hl:
            fund_parts.append(f"📰 *News Flow:* {top_hl[:32]}...")

        if fund_parts:
            fund_line = "\n".join(fund_parts) + "\n"

        ev_net_val = sig.get("expected_net_return") or sig.get("ev_net")
        costs_val = sig.get("total_execution_costs") or sig.get("costs_total_pct")
        if ev_net_val is not None and str(ev_net_val) != "":
            try:
                ev_line = f"📈 *Expected Net Value (EVnet):* *+{float(ev_net_val):.2f}%* (Costs: {float(costs_val or 0.145):.2f}%)\n"
            except Exception:
                ev_line = f"📈 *Expected Net Value (EVnet):* *+{abs(exp_ret):.2f}%* (Post-Fees)\n"
        else:
            ev_line = f"📈 *Expected Net Value (EVnet):* *+{abs(exp_ret):.2f}%* (Post-Fees)\n"

        candle_trig_reason = sig.get("candle_trigger_reason")
        candle_trig_line = f"🕯️ *Trigger Confirm:* `{candle_trig_reason}`\n" if candle_trig_reason else ""

        msg = (
            f"⚡ *QUANT EDGE V16 • INSTITUTIONAL SIGNAL* ⚡\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Pair:* #{sym.replace('/', '_')} ({horizon})\n"
            f"📊 *Direction:* {dir_emoji}\n"
            f"🎯 *Setup:* *{decision_display}*\n"
            f"💎 *Grade:* *{grade}*\n"
            f"🧠 *Confidence Score:* *{win_prob:.1f}%* (Calibrated Win Rate)\n"
            f"🎯 *AI Conviction:* *{conviction:.1f}%*\n"
            f"{ev_line}"
            f"{candle_trig_line}"
            f"{candle_line}"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{anti_chase_block}"
            f"{entry_line}"
            f"🎯 *Target 1 (TP1):* {tp1} • *Prob: {probs['tp1']:.1f}%*\n"
            f"🎯 *Target 2 (TP2):* {tp2} • *Prob: {probs['tp2']:.1f}%*\n"
            f"🎯 *Target 3 (TP3):* {tp3} • *Prob: {probs['tp3']:.1f}%*\n"
            f"🛑 *Invalidation (SL):* {sl} • *Risk Prob: {probs['sl']:.1f}%*\n"
            f"⚖️ *Risk:Reward:* {rr}\n"
            f"🏷️ *Trade Thesis:* `{thesis_id}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{fund_line}"
            f"🛡️ *Regime / Shield:* {market_shield}\n"
            f"🔗 *Live Terminal:* https://bullsandbears.binaryunit.tech"
        )
        return msg

    def format_tp_hit(self, sig: Dict[str, Any], level: str, current_price: float, gain_pct: float) -> str:
        sym = sig.get("symbol", "BTC/USDT")
        horizon = self._format_horizon_display(sig)
        f_price = self._format_price(current_price)
        decision = (
            sig.get("decision")
            or sig.get("strategy_archetype")
            or (sig.get("grade") if isinstance(sig.get("grade"), str) and "(" in sig.get("grade") else "")
            or ""
        )
        setup_line = f"🎯 Setup: *{decision}*\n" if decision else ""

        entry_val = float(sig.get("entry_price") or sig.get("entry_price_initial") or 0.0)
        if (gain_pct is None or gain_pct == 0.0) and entry_val > 0 and current_price > 0:
            dirn = str(sig.get("dominant_direction") or sig.get("direction") or "LONG").upper()
            gain_pct = ((current_price - entry_val) / entry_val * 100.0) if dirn in ["LONG", "BUY"] else ((entry_val - current_price) / entry_val * 100.0)

        if level == "TP1":
            action_text = (
                f"Gain: *+{gain_pct:.2f}%* secured! 💰\n"
                f"Action: 🛡️ *Stop-Loss automatically raised to Entry (Break-Even)*.\n"
                f"This trade is now completely *Risk-Free*."
            )
            title = "🎯 *PROFIT TARGET 1 REACHED!* 🟢"
        elif level == "TP2":
            action_text = (
                f"Gain: *+{gain_pct:.2f}%* captured! 🚀\n"
                f"Action: 📈 *Trailing Stop raised to TP1 floor* to guarantee profits."
            )
            title = "🎯 *PROFIT TARGET 2 SMASHED!* 🟢"
        else: # TP3
            action_text = (
                f"Peak Gain: *+{gain_pct:.2f}%* locked! 🏆\n"
                f"Outcome: *Full Target Hit (All TPs Filled)*.\n"
                f"Trade closed with maximum quantitative return."
            )
            title = "🚀 *MAX TARGET SMASHED (TP3 WON)!* 🏆"

        grade = sig.get("quality_grade") or sig.get("grade") or "Grade A"
        raw_prob = sig.get("meta_win_prob_pct") or sig.get("win_probability_pct") or sig.get("p_tp1") or sig.get("meta_win_prob")
        prob_str = ""
        if raw_prob is not None:
            try:
                f_prob = float(raw_prob)
                f_prob = f_prob * 100.0 if 0.0 < f_prob <= 1.0 else f_prob
                prob_str = f"🧠 P(TP1): *{f_prob:.1f}%* | "
            except Exception:
                pass

        msg = (
            f"{title}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Coin: *{sym}* ({horizon})\n"
            f"{setup_line}"
            f"💎 Grade: *{grade}*\n"
            f"{prob_str}Current Price: *{f_price}*\n"
            f"{action_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 Track live: https://bullsandbears.binaryunit.tech"
        )
        return msg

    def format_sl_hit(self, sig: Dict[str, Any], exit_price: float, loss_pct: float) -> str:
        sym = sig.get("symbol", "BTC/USDT")
        horizon = self._format_horizon_display(sig)
        grade = sig.get("quality_grade") or sig.get("grade") or "Grade A"
        raw_prob = sig.get("meta_win_prob_pct") or sig.get("win_probability_pct") or sig.get("p_tp1") or sig.get("meta_win_prob")
        prob_str = ""
        if raw_prob is not None:
            try:
                f_prob = float(raw_prob)
                f_prob = f_prob * 100.0 if 0.0 < f_prob <= 1.0 else f_prob
                prob_str = f"🧠 P(TP1): *{f_prob:.1f}%* | "
            except Exception:
                pass

        decision = (
            sig.get("decision")
            or sig.get("strategy_archetype")
            or (sig.get("grade") if isinstance(sig.get("grade"), str) and "(" in sig.get("grade") else "")
            or ""
        )
        setup_line = f"🎯 Setup: *{decision}*\n" if decision else ""
        f_price = self._format_price(exit_price)

        entry_val = float(sig.get("entry_price") or sig.get("entry_price_initial") or 0.0)
        if (loss_pct is None or loss_pct == 0.0) and entry_val > 0 and exit_price > 0:
            dirn = str(sig.get("dominant_direction") or sig.get("direction") or "LONG").upper()
            loss_pct = ((exit_price - entry_val) / entry_val * 100.0) if dirn in ["LONG", "BUY"] else ((entry_val - exit_price) / entry_val * 100.0)

        msg = (
            f"🛑 *TRADE INVALIDATION / STOP-LOSS ALERT* ⚠️\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Coin: *{sym}* ({horizon})\n"
            f"{setup_line}"
            f"💎 Grade: *{grade}*\n"
            f"{prob_str}Exit Price: *{f_price}* (-{abs(loss_pct):.2f}%)\n"
            f"Status: *Closed under strict risk control*\n"
            f"Capital preservation rule executed. Waiting for next high-probability setup.\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 https://bullsandbears.binaryunit.tech"
        )
        return msg

    def format_trail_or_be_hit(self, sig: Dict[str, Any], exit_price: float, ret_pct: float, label: str) -> str:
        sym = sig.get("symbol", "BTC/USDT")
        horizon = self._format_horizon_display(sig)
        grade = sig.get("quality_grade") or sig.get("grade") or "Grade A"
        raw_prob = sig.get("meta_win_prob_pct") or sig.get("win_probability_pct") or sig.get("p_tp1") or sig.get("meta_win_prob")
        prob_str = ""
        if raw_prob is not None:
            try:
                f_prob = float(raw_prob)
                f_prob = f_prob * 100.0 if 0.0 < f_prob <= 1.0 else f_prob
                prob_str = f"🧠 P(TP1): *{f_prob:.1f}%* | "
            except Exception:
                pass

        decision = (
            sig.get("decision")
            or sig.get("strategy_archetype")
            or (sig.get("grade") if isinstance(sig.get("grade"), str) and "(" in sig.get("grade") else "")
            or ""
        )
        setup_line = f"🎯 Setup: *{decision}*\n" if decision else ""
        f_price = self._format_price(exit_price)
        msg = (
            f"🛡️ *PROFIT LOCK / BREAK-EVEN EXIT* 🟢\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Coin: *{sym}* ({horizon})\n"
            f"{setup_line}"
            f"💎 Grade: *{grade}*\n"
            f"{prob_str}Exit Price: *{f_price}* ({ret_pct:+.2f}%)\n"
            f"Outcome: *{label}*\n"
            f"Risk Guard executed perfectly — protected capital with profit secured.\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 https://bullsandbears.binaryunit.tech"
        )
        return msg

    def format_breakeven_locked(self, sig: Dict[str, Any], current_price: float, gain_pct: float) -> str:
        sym = sig.get("symbol", "BTC/USDT")
        horizon = self._format_horizon_display(sig)
        grade = sig.get("quality_grade") or sig.get("grade") or "Grade A"
        raw_prob = sig.get("meta_win_prob_pct") or sig.get("win_probability_pct") or sig.get("p_tp1") or sig.get("meta_win_prob")
        prob_str = ""
        if raw_prob is not None:
            try:
                f_prob = float(raw_prob)
                f_prob = f_prob * 100.0 if 0.0 < f_prob <= 1.0 else f_prob
                prob_str = f"🧠 P(TP1): *{f_prob:.1f}%* | "
            except Exception:
                pass

        decision = (
            sig.get("decision")
            or sig.get("strategy_archetype")
            or (sig.get("grade") if isinstance(sig.get("grade"), str) and "(" in sig.get("grade") else "")
            or ""
        )
        setup_line = f"🎯 Setup: *{decision}*\n" if decision else ""
        entry_val = sig.get("entry_price") or sig.get("entry_price_initial") or current_price
        entry_p = self._format_price(entry_val)
        curr_p = self._format_price(current_price)

        if (gain_pct is None or gain_pct == 0.0) and float(entry_val or 0) > 0 and current_price > 0:
            dirn = str(sig.get("dominant_direction") or sig.get("direction") or "LONG").upper()
            gain_pct = ((current_price - float(entry_val)) / float(entry_val) * 100.0) if dirn in ["LONG", "BUY"] else ((float(entry_val) - current_price) / float(entry_val) * 100.0)

        msg = (
            f"🛡️ *RISK-FREE PROFIT LOCK / BREAK-EVEN MOVED* 🛡️\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Coin: *{sym}* ({horizon})\n"
            f"{setup_line}"
            f"💎 Grade: *{grade}*\n"
            f"{prob_str}Current Price: *{curr_p}* ({gain_pct:+.2f}%)\n"
            f"Stop Loss Adjusted to Entry: *{entry_p}*\n"
            f"Risk Exposure: *0.00% (Guaranteed Risk-Free Trade)*\n"
            f"Capital protected. Position is running towards profit targets with zero downside.\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 https://bullsandbears.binaryunit.tech"
        )
        return msg

    def format_expired(self, sig: Dict[str, Any], exit_price: float, ret_pct: float, label: str) -> str:
        sym = sig.get("symbol", "BTC/USDT")
        horizon = self._format_horizon_display(sig)
        grade = sig.get("quality_grade") or sig.get("grade") or "Grade A"
        prob = sig.get("meta_win_prob_pct")
        prob_str = f"🧠 Probability Score: *{float(prob):.1f}%*\n" if prob is not None else ""
        decision = sig.get("decision") or sig.get("strategy_archetype") or ""
        setup_line = f"🎯 Setup: *{decision}*\n" if decision else ""
        f_price = self._format_price(exit_price)
        emoji = "🟢" if ret_pct > 0 else ("🔴" if ret_pct < -0.1 else "⚪")
        msg = (
            f"{emoji} *TIME HORIZON EXPIRED / TRADE RESOLVED* ⏳\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Coin: *{sym}* ({horizon})\n"
            f"{setup_line}"
            f"💎 Grade: *{grade}*\n"
            f"{prob_str}Closing Price: *{f_price}* ({ret_pct:+.2f}%)\n"
            f"Result: *{label}*\n"
            f"Prediction cycle completed for this trading horizon.\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 https://bullsandbears.binaryunit.tech"
        )
        return msg

    def format_limit_cancelled(self, sig: Dict[str, Any], exit_price: float, reason: str, detail: str = "") -> str:
        sym = sig.get("symbol", "BTC/USDT")
        horizon = self._format_horizon_display(sig)
        grade = sig.get("quality_grade") or sig.get("grade") or "Grade A"
        prob = sig.get("meta_win_prob_pct")
        prob_str = f"🧠 Probability Score: *{float(prob):.1f}%*\n" if prob is not None else ""
        decision = sig.get("decision") or sig.get("strategy_archetype") or ""
        setup_line = f"🎯 Setup: *{decision}*\n" if decision else ""
        f_price = self._format_price(exit_price)
        detail_line = f"Context: *{detail}*\n" if detail else ""
        msg = (
            f"⏱️ *RESTING LIMIT ORDER CANCELLED / EXPIRED* 🛑\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Coin: *{sym}* ({horizon})\n"
            f"{setup_line}"
            f"💎 Grade: *{grade}*\n"
            f"{prob_str}Reference Price: *{f_price}*\n"
            f"Reason: *{reason}*\n"
            f"{detail_line}"
            f"Anti-Chase & Capital Protection: resting order stood down safely.\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 https://bullsandbears.binaryunit.tech"
        )
        return msg

    def format_regime_shift(self, shield_data: Dict[str, Any]) -> str:
        regime = shield_data.get("status_code") or shield_data.get("regime") or "CONSOLIDATION"
        reason = shield_data.get("reason", "Dynamic Market Shift")
        cons_prob = shield_data.get("cons_prob", 50.0)
        posture = shield_data.get("posture", "NORMAL")
        timeframe = shield_data.get("timeframe", "Multi-Timeframe (15M / 1H / 4H)")
        btc_p = shield_data.get("btc_price")
        bbw_val = shield_data.get("bbw_15m")

        if regime in ["CONSOLIDATION", "RANGE_SQUEEZE", "NO_TRADE_ZONE"] or "NO_TRADE_ZONE" in posture:
            btc_line = f"📉 Benchmark (BTC): *${btc_p:,.0f}*" if btc_p else ""
            bbw_line = f" | Squeeze BBW: *{bbw_val:.2f}%*" if bbw_val is not None else ""
            market_line = f"{btc_line}{bbw_line}\n" if (btc_line or bbw_line) else ""
            msg = (
                f"🛑 *MARKET REGIME ALERT: CONSOLIDATION / NO TRADE ZONE* 🛑\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 Market State: *CONSOLIDATION RANGE & LOW VOLUME*\n"
                f"⏱️ Timeframe Scope: *{timeframe}*\n"
                f"{market_line}"
                f"💤 Consolidation Prob: *{cons_prob:.1f}%*\n"
                f"📉 Context: {reason}\n"
                f"🛡️ Posture: *CAPITAL PRESERVATION (NTZ ACTIVE)*\n"
                f"\n"
                f"⚠️ *Institutional Execution Policy*:\n"
                f"• Signals: *PAUSED on Compressed Timeframes*\n"
                f"• Paper Trading: *LOCKED (0 New Entries)*\n"
                f"• Capital: *Held in Reserve to Avoid Chop Drag*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🔗 https://bullsandbears.binaryunit.tech"
            )
            return msg

        msg = (
            f"🛡️ *INSTITUTIONAL BTC MARKET SHIELD ALERT* 🛡️\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Status: *{regime}*\n"
            f"Context: {reason}\n"
            f"Consolidation Prob: *{cons_prob:.1f}%*\n"
            f"Trading Posture: *{posture}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 https://bullsandbears.binaryunit.tech"
        )
        return msg

    def format_macro_ntz_start(self, reason: str, btc_shield: Dict[str, Any]) -> str:
        regime = btc_shield.get("status_code") or btc_shield.get("regime") or "RANGE_SQUEEZE"
        btc_p = btc_shield.get("btc_price") or btc_shield.get("current_price") or 0.0
        btc_str = self._format_price(btc_p) if btc_p > 0 else "N/A"
        adx_val = btc_shield.get("adx") or btc_shield.get("metrics", {}).get("adx", 20.0)
        timeframe = btc_shield.get("timeframe", "Multi-Timeframe (15M / 1H / 4H)")

        msg = (
            f"🛑 *QUANT EDGE V16 — NO TRADE ZONE (NTZ) ACTIVATED* 🛑\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ *Trading Posture*: *CAPITAL PRESERVATION (LOCK ACTIVE)*\n"
            f"📉 *Trigger*: {reason}\n"
            f"📊 *Market Regime*: *{regime}*\n"
            f"💵 *BTC Benchmark*: *{btc_str}* | ADX: *{float(adx_val):.1f}*\n"
            f"⏱️ *Timeframe Scope*: *{timeframe}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ *Automated Institutional Execution Safeguards*:\n"
            f"• ⛔ *New Trade Signals*: *HALTED* across all horizons (15M, 1H, 24H)\n"
            f"• 🔒 *Paper Trading Bot*: *ADMISSIONS LOCKED* (0 new entries permitted)\n"
            f"• 🛡️ *Running Positions*: *100% PROTECTED* (Active TP/SL & Trailing guards remain active 24/7)\n"
            f"• 💼 *Capital Allocation*: Risk multiplier reduced to *0.0x* to prevent chop bleed\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 Live Terminal: https://bullsandbears.binaryunit.tech"
        )
        return msg

    def format_macro_ntz_end(self, btc_shield: Dict[str, Any]) -> str:
        regime = btc_shield.get("status_code") or btc_shield.get("regime") or "NORMAL"
        btc_p = btc_shield.get("btc_price") or btc_shield.get("current_price") or 0.0
        btc_str = self._format_price(btc_p) if btc_p > 0 else "N/A"
        adx_val = btc_shield.get("adx") or btc_shield.get("metrics", {}).get("adx", 25.0)

        msg = (
            f"🟢 *QUANT EDGE V16 — NO TRADE ZONE (NTZ) LIFTED* 🟢\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ *Trading Posture*: *NORMAL TRADING OPERATIONS RESUMED*\n"
            f"📈 *Market Assessment*: Macro volatility stabilized & directional clarity restored\n"
            f"📊 *Market Regime*: *{regime}*\n"
            f"💵 *BTC Benchmark*: *{btc_str}* | ADX: *{float(adx_val):.1f}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ *Operational Directives*:\n"
            f"• 🟢 *New Trade Admissions*: *UNLOCKED* for Grade A/A+ institutional setups\n"
            f"• 🤖 *Paper Trading Bot*: *SCANNING RESUMED* with sub-diffusive volatility scaling\n"
            f"• 🎯 *Target Matrices*: Fully refreshed across 15M, 1H, and 24H horizons\n"
            f"• 💼 *Capital Allocation*: Restored to standard institutional sizing\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 Live Terminal: https://bullsandbears.binaryunit.tech"
        )
        return msg

    # =========================================================================
    # DISPATCH QUEUE & WORKER
    # =========================================================================
    def _enqueue_message(self, target_jid: str, text: str, priority: int = 10, dedup_key: Optional[str] = None):
        if not self.enabled or not target_jid:
            return
        msg_id = str(uuid.uuid4())
        item = {
            "id": msg_id,
            "target": target_jid,
            "text": text,
            "ts": time.time(),
            "priority": priority,
            "retries": 0,
            "next_retry_ts": 0.0,
            "dedup_key": dedup_key
        }
        with self._lock:
            # Enforce max spool size (200) to protect memory and disk
            if len(self._spool) >= 200:
                oldest_k = min(self._spool.keys(), key=lambda k: self._spool[k].get("ts", 0))
                del self._spool[oldest_k]
            self._spool[msg_id] = item
        self._save_spool_to_disk()

        try:
            self._queue.put_nowait(item)
            logger.info(f"[WHATSAPP 📤] Queued message to {target_jid[:15]}... (Queue size: {self._queue.qsize()})")
        except queue.Full:
            logger.error("[WHATSAPP ❌] Outbound queue full! Retaining in disk spool for subsequent retry.")

    def _process_queue(self):
        """Worker loop that sends messages with anti-ban pacing, exponential retry, and session health checks."""
        while self._running:
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                # Periodic health check during idle queue periods (every 60s)
                now = time.time()
                if now - self._last_health_check_ts > 60.0:
                    try:
                        self.check_gateway_health()
                    except Exception:
                        pass
                continue

            try:
                now = time.time()
                # Gateway Circuit Breaker: Wait out active gateway cooldown
                if now < self._gateway_circuit_breaker_until:
                    sleep_time = min(5.0, max(0.5, self._gateway_circuit_breaker_until - now))
                    time.sleep(sleep_time)

                # Retry Timing Check
                if item.get("next_retry_ts", 0.0) > now:
                    time.sleep(min(1.0, max(0.1, item["next_retry_ts"] - now)))
                    self._queue.put(item)
                    continue

                # Anti-ban Pacing delay: Ensure at least rate_limit_seconds between messages
                now = time.time()
                elapsed = now - self._last_dispatch_ts
                required_delay = max(1.5, self.rate_limit_seconds)
                if elapsed < required_delay:
                    time.sleep(required_delay - elapsed)

                success = self._send_http(item["target"], item["text"])
                self._last_dispatch_ts = time.time()

                if success:
                    msg_id = item.get("id")
                    with self._lock:
                        if msg_id in self._spool:
                            del self._spool[msg_id]
                    self._save_spool_to_disk()
                    self._gateway_connected = True
                else:
                    # Gateway dispatch failed: Engage bounded exponential backoff
                    retries = item.get("retries", 0) + 1
                    item["retries"] = retries
                    if retries <= self._max_retries:
                        backoff = min(120.0, 5.0 * (2 ** (retries - 1)))
                        item["next_retry_ts"] = time.time() + backoff
                        logger.warning(f"[WHATSAPP 🔄] Gateway dispatch failed for {item['target'][:15]}... Retrying #{retries} in {backoff:.1f}s.")
                        # Trip a 10s gateway circuit breaker to prevent rapid hammering on a broken/restarting gateway
                        self._gateway_circuit_breaker_until = time.time() + 10.0
                        with self._lock:
                            if item.get("id") in self._spool:
                                self._spool[item["id"]] = item
                        self._save_spool_to_disk()
                        self._queue.put(item)
                    else:
                        # Max retries exceeded: Archive to dead-letter storage
                        logger.error(f"[WHATSAPP ❌] Max retries ({self._max_retries}) exceeded for {item['target']}. Moving to dead-letter.")
                        self._archive_dead_letter(item, reason=f"Max retries ({self._max_retries}) exceeded")
                        msg_id = item.get("id")
                        with self._lock:
                            if msg_id in self._spool:
                                del self._spool[msg_id]
                        self._save_spool_to_disk()

            except Exception as e:
                logger.error(f"[WHATSAPP ❌] Error sending queued message: {e}")
            finally:
                self._queue.task_done()

    def check_gateway_health(self) -> Dict[str, Any]:
        """
        Actively checks gateway connection status.
        For Evolution API / Baileys: Inspects instance connectionState.
        If instance is disconnected or session closed, triggers automatic reconnection.
        """
        self._last_health_check_ts = time.time()
        if not self.enabled:
            return {"status": "disabled", "healthy": True}

        gateway_type = self.gateway_type
        base_api_url = self.api_url
        api_key = self.api_key
        instance = self.instance_name

        urls_to_try = [base_api_url]
        if "://whatsapp:" in base_api_url or "://whatsapp/" in base_api_url or base_api_url.endswith("://whatsapp"):
            urls_to_try.append(base_api_url.replace("://whatsapp", "://127.0.0.1"))

        for api_url in urls_to_try:
            try:
                if gateway_type == "evolution_api":
                    headers = {"apikey": api_key}
                    endpoint = f"{api_url}/instance/connectionState/{instance}"
                    resp = requests.get(endpoint, headers=headers, timeout=4.0)
                    if resp.status_code == 200:
                        data = resp.json()
                        state = data.get("instance", {}).get("state", "unknown")
                        is_open = (state == "open")
                        self._gateway_connected = is_open
                        if not is_open:
                            logger.warning(f"[WHATSAPP ⚠️] Evolution API instance '{instance}' state is '{state}'. Triggering auto-reconnect...")
                            reconnect_endpoint = f"{api_url}/instance/connect/{instance}"
                            try:
                                requests.get(reconnect_endpoint, headers=headers, timeout=4.0)
                            except Exception:
                                pass
                        return {
                            "healthy": is_open,
                            "state": state,
                            "gateway_type": gateway_type,
                            "instance": instance,
                            "pending_spool_count": len(self._spool)
                        }
                    elif resp.status_code == 404:
                        logger.warning(f"[WHATSAPP ⚠️] Evolution API instance '{instance}' not found. Initializing...")
                        create_endpoint = f"{api_url}/instance/create"
                        try:
                            requests.post(create_endpoint, json={"instanceName": instance, "qrcode": True}, headers=headers, timeout=5.0)
                        except Exception:
                            pass
                        return {"healthy": False, "state": "initializing", "gateway_type": gateway_type}
            except Exception:
                pass

        self._gateway_connected = False
        return {
            "healthy": False,
            "state": "unreachable",
            "gateway_type": gateway_type,
            "pending_spool_count": len(self._spool)
        }

    def _send_http(self, target_jid: str, text: str) -> bool:
        """Sends payload to configured WhatsApp gateway.
        
        IMPORTANT: WhatsApp Channel/Newsletter JIDs (ending in @newsletter) require
        a DIFFERENT API endpoint than groups/DMs. This method auto-detects and routes
        to the correct endpoint. Automatically falls back to localhost if running outside Docker.
        """
        if not self.enabled:
            logger.debug(f"[WHATSAPP MOCK] (Disabled) Would send to {target_jid}:\n{text[:60]}...")
            return True

        gateway_type = self.gateway_type
        base_api_url = self.api_url
        api_key = self.api_key
        instance = self.instance_name
        is_newsletter = "@newsletter" in target_jid

        urls_to_try = [base_api_url]
        if "://whatsapp:" in base_api_url or "://whatsapp/" in base_api_url or base_api_url.endswith("://whatsapp"):
            urls_to_try.append(base_api_url.replace("://whatsapp", "://127.0.0.1"))

        last_error = None
        for api_url in urls_to_try:
            try:
                if gateway_type == "evolution_api":
                    headers = {
                        "apikey": api_key,
                        "Content-Type": "application/json"
                    }

                    if is_newsletter:
                        # -------------------------------------------------------
                        # WhatsApp CHANNELS / NEWSLETTERS require a separate endpoint
                        # Evolution API v2: POST /newsletter/send/{instance}
                        # -------------------------------------------------------
                        endpoint = f"{api_url}/newsletter/send/{instance}"
                        payload = {
                            "number": target_jid,
                            "message": {"text": text}
                        }
                        resp = requests.post(endpoint, json=payload, headers=headers, timeout=12.0)
                        if resp.status_code in [200, 201]:
                            logger.info(f"[WHATSAPP ✅] Channel message dispatched to {target_jid}")
                            return True
                        else:
                            # Fallback: some Evolution API versions use sendText for all targets
                            logger.warning(f"[WHATSAPP ⚠️] Newsletter endpoint HTTP {resp.status_code}: {resp.text[:200]}. Trying sendText fallback...")
                            endpoint_fb = f"{api_url}/message/sendText/{instance}"
                            payload_fb = {"number": target_jid, "text": text, "delay": 1200}
                            resp_fb = requests.post(endpoint_fb, json=payload_fb, headers=headers, timeout=12.0)
                            if resp_fb.status_code in [200, 201]:
                                logger.info(f"[WHATSAPP ✅] Channel message dispatched via sendText fallback to {target_jid}")
                                return True
                            logger.error(f"[WHATSAPP ❌] Both channel endpoints failed. Last HTTP {resp_fb.status_code}: {resp_fb.text[:200]}")
                            return False
                    else:
                        # Standard Group / DM message
                        endpoint = f"{api_url}/message/sendText/{instance}"
                        payload = {
                            "number": target_jid,
                            "text": text,
                            "delay": 1200
                        }
                        resp = requests.post(endpoint, json=payload, headers=headers, timeout=8.0)
                        if resp.status_code in [200, 201]:
                            logger.info(f"[WHATSAPP ✅] Successfully dispatched message to {target_jid}")
                            print(f"[WHATSAPP ✅] Successfully dispatched message to {target_jid}", flush=True)
                            return True
                        else:
                            logger.warning(f"[WHATSAPP ⚠️] Gateway returned HTTP {resp.status_code}: {resp.text[:200]}")
                            print(f"[WHATSAPP ⚠️] Gateway returned HTTP {resp.status_code}: {resp.text[:200]}", flush=True)
                            return False

                elif gateway_type == "whapi":
                    endpoint = f"{api_url}/messages/text"
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    }
                    payload = {
                        "to": target_jid,
                        "body": text
                    }
                    resp = requests.post(endpoint, json=payload, headers=headers, timeout=8.0)
                    return resp.status_code in [200, 201]

                elif gateway_type == "webhook":
                    headers = {"Content-Type": "application/json"}
                    if api_key:
                        headers["Authorization"] = f"Bearer {api_key}"
                    payload = {"target": target_jid, "text": text}
                    resp = requests.post(api_url, json=payload, headers=headers, timeout=8.0)
                    return resp.status_code in [200, 201]

                else:
                    logger.error(f"[WHATSAPP ❌] Unknown gateway type: {gateway_type}")
                    return False

            except requests.exceptions.ConnectionError as ce:
                last_error = ce
                continue
            except Exception as e:
                logger.error(f"[WHATSAPP ❌] HTTP exception to gateway (target={target_jid}): {e}")
                return False

        if last_error:
            logger.error(f"[WHATSAPP ❌] HTTP connection exception to gateway (target={target_jid}): {last_error}")
        return False

    # =========================================================================
    # PUBLIC HIGH-LEVEL AUTOMATION HOOKS
    # =========================================================================
    def emit_signal_created(self, sig: Dict[str, Any]):
        """
        Called when a new signal is admitted into SignalAuditTracker.
        Automatically broadcasts to WhatsApp Group and/or Channel.
        """
        horizon_desc = sig.get("horizon_name") or sig.get("horizon_tag") or sig.get("horizon_key") or sig.get("horizon") or "1H"
        sig_id = sig.get("signal_id") or f"{sig.get('symbol')}_{horizon_desc}"
        dedup_key = f"{sig_id}:SIGNAL_CREATED"

        if self.is_already_sent(dedup_key):
            return

        # Check Quality Gate for Group
        group_jid = self.group_id
        is_dispatched = False
        if group_jid and self.passes_quality_gate(sig, is_channel=False):
            text = self.format_new_signal(sig)
            self._enqueue_message(group_jid, text, priority=1)
            is_dispatched = True

        # Check Quality Gate for Channel (higher hurdle)
        channel_jid = self.channel_id
        if channel_jid and self.passes_quality_gate(sig, is_channel=True):
            text = self.format_new_signal(sig)
            self._enqueue_message(channel_jid, text, priority=1)
            is_dispatched = True

        if is_dispatched:
            self._broadcasted_signals.add(sig_id)

    def sync_v16_terminal_signals(self) -> int:
        """
        Reconciles active signals from the Quant Edge V16 Institutional Terminal store
        (v16_immutable_signals.json & v16_dynamic_states.json) and ensures active trades
        are broadcast to the WhatsApp group with deduplication.
        Returns the number of new signals dispatched.
        """
        if not self.enabled or not self.group_id:
            return 0

        try:
            from app.routers.v16_router import _get_v16_store
            immut_data, dyn_data = _get_v16_store()
        except Exception as e:
            logger.warning(f"[WHATSAPP ⚠️] Failed to load V16 store for sync: {e}")
            return 0

        dispatched = 0
        for sid, imm in immut_data.items():
            dyn = dyn_data.get(sid, {})
            status = str(dyn.get("status") or imm.get("status") or "").upper()
            outcome_lbl = str(dyn.get("outcome_label") or "").upper()

            is_active = (
                status in ["ACTIVE", "PENDING_EVALUATION", "ACTIVE_TRADE", "PENDING_LIMIT", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL"]
                or "RUNNING" in outcome_lbl
                or "ACTIVE" in outcome_lbl
                or "PENDING" in outcome_lbl
            )
            if not is_active:
                continue

            merged = {**imm, **dyn}
            if not self.passes_quality_gate(merged, is_channel=False):
                continue

            dedup_key = f"V16_SYNC_CREATED:{sid}"
            if self.is_already_sent(dedup_key, ttl_seconds=86400 * 3):
                continue

            text = self.format_new_signal(merged)
            self._enqueue_message(self.group_id, text, priority=1)
            if self.channel_id and self.passes_quality_gate(merged, is_channel=True):
                self._enqueue_message(self.channel_id, text, priority=1)
            dispatched += 1
            logger.info(f"[WHATSAPP 🚀] Synced active V16 Terminal signal to WhatsApp: {merged.get('symbol')} ({merged.get('horizon')})")

        return dispatched

    def emit_signal_outcome(self, sig: Dict[str, Any], event_type: str, current_price: float, gain_pct: float):
        """
        Called on heartbeat evaluation when a TP, SL, or Breakeven is touched.
        event_type in: TP1_HIT, TP2_HIT, TP3_HIT, SL_HIT, BE_LOCKED, BE_HIT, BREAKEVEN_GUARD, TRAIL_SL_HIT, EXPIRED
        """
        horizon_desc = sig.get("horizon_name") or sig.get("horizon_tag") or sig.get("horizon_key") or sig.get("horizon") or "1H"
        sig_id = sig.get("signal_id") or sig.get("trade_id") or f"{sig.get('symbol')}_{horizon_desc}"

        # 1. Quality Gate Check: Suppress outcome updates for Grade C / sub-hurdle setups
        if not self.passes_quality_gate(sig, is_channel=False):
            logger.info(f"[WHATSAPP 🛡️] Suppressed {event_type} for {sig.get('symbol')}: fails quality gate ({sig.get('grade')}).")
            return

        dedup_key = f"{sig_id}:{event_type}"

        if self.is_already_sent(dedup_key):
            return

        group_jid = self.group_id
        channel_jid = self.channel_id

        if event_type in ["TP1_HIT", "TP2_HIT", "TP3_HIT"]:
            if not self.send_tp_updates:
                return
            level = "TP1" if event_type == "TP1_HIT" else ("TP2" if event_type == "TP2_HIT" else "TP3")
            text = self.format_tp_hit(sig, level, current_price, gain_pct)

            # Send TP1, TP2, TP3 to VIP Group
            if group_jid:
                self._enqueue_message(group_jid, text, priority=2)

            # Send TP1 and TP3 Won to Public Channel
            if channel_jid and level in ["TP1", "TP3"]:
                self._enqueue_message(channel_jid, text, priority=2)

        elif event_type in ["BE_LOCKED", "BE_RATCHET"]:
            text = self.format_breakeven_locked(sig, current_price, gain_pct)
            if group_jid:
                self._enqueue_message(group_jid, text, priority=2)
            if channel_jid:
                self._enqueue_message(channel_jid, text, priority=2)

        elif event_type == "SL_HIT":
            if not self.send_sl_updates:
                return
            text = self.format_sl_hit(sig, current_price, gain_pct)
            # Invalidation sent to Group
            if group_jid:
                self._enqueue_message(group_jid, text, priority=3)

        elif event_type in ["BE_HIT", "BREAKEVEN_GUARD", "TRAIL_SL_HIT"]:
            label = sig.get("outcome_label", "Break-Even Exit")
            text = self.format_trail_or_be_hit(sig, current_price, gain_pct, label)
            if group_jid:
                self._enqueue_message(group_jid, text, priority=2)
            if channel_jid:
                self._enqueue_message(channel_jid, text, priority=2)

        elif event_type in ["EXPIRED", "CANCELLED", "CANCELLED_CHASE_EXCEEDED", "LIMIT_CANCELLED"]:
            if event_type in ["CANCELLED", "CANCELLED_CHASE_EXCEEDED", "LIMIT_CANCELLED"]:
                sym_canc_key = f"LIMIT_CANC:{sig.get('symbol')}:{horizon_desc}"
                if self.is_already_sent(sym_canc_key, ttl_seconds=1800):
                    logger.info(f"[WHATSAPP 🛡️] Suppressed duplicate limit cancellation for {sig.get('symbol')} ({horizon_desc}) within 30m window.")
                    return
                reason = sig.get("cancellation_reason") or "Resting Limit Expired / Chase Exceeded"
                detail = sig.get("cancellation_detail") or ""
                text = self.format_limit_cancelled(sig, current_price, reason, detail)
            else:
                label = sig.get("outcome_label", "Horizon Expired")
                text = self.format_expired(sig, current_price, gain_pct, label)
            if group_jid:
                self._enqueue_message(group_jid, text, priority=3)

    def emit_regime_alert(self, shield_data: Dict[str, Any]):
        """
        Called when BTC switches regime or trips a circuit breaker.
        Enforces a global regime shift lock to prevent rapid back-and-forth oscillations
        (e.g., flipping between BEAR_TREND and CONSOLIDATION within minutes).
        """
        if not self.send_regime_alerts:
            return

        regime = shield_data.get("status_code") or shield_data.get("regime") or "NORMAL"
        # Only notify on significant market regime shifts
        if regime in ["NORMAL"]:
            return

        is_emergency_dump = regime in ["ALERT_DUMP", "FLASH_DUMP"] or "CRASH" in str(shield_data.get("reason", "")).upper()

        # 1. Exact regime repeat deduplication: Don't repeat the exact same regime within 15m
        repeat_ttl = 900 if regime in ["CONSOLIDATION", "RANGE_SQUEEZE", "NO_TRADE_ZONE"] else 600
        same_regime_key = f"REGIME_REPEAT:{regime}"
        if self.is_already_sent(same_regime_key, ttl_seconds=repeat_ttl):
            return

        # 2. Global regime cooldown: Prevent rapid alternating oscillations between ANY regimes
        global_lock_key = "GLOBAL_REGIME_ALERT_LOCK"
        if not is_emergency_dump:
            if self.is_already_sent(global_lock_key, ttl_seconds=600):
                return
        else:
            # For emergency crash dumps, establish shorter 5m lock
            self.is_already_sent(global_lock_key, ttl_seconds=300)

        if not self.enabled:
            return

        text = self.format_regime_shift(shield_data)
        if self.group_id:
            self._enqueue_message(self.group_id, text, priority=1)
        if self.channel_id:
            self._enqueue_message(self.channel_id, text, priority=1)

    def emit_macro_ntz_start(self, reason: str, btc_shield: Dict[str, Any]):
        """
        Called on edge transition when engine enters Macro No Trade Zone.
        Dispatches high-priority alert to Group and Channel.
        """
        if not self.send_regime_alerts:
            return

        dedup_key = f"MACRO_NTZ_START:{int(time.time() // 300)}"
        if self.is_already_sent(dedup_key, ttl_seconds=600):
            return

        text = self.format_macro_ntz_start(reason, btc_shield)
        if self.group_id:
            self._enqueue_message(self.group_id, text, priority=1)
        if self.channel_id:
            self._enqueue_message(self.channel_id, text, priority=1)
        logger.info(f"[WHATSAPP 🛑] Dispatched Macro NTZ START alert to queue (reason: {reason})")

    def emit_macro_ntz_end(self, btc_shield: Dict[str, Any]):
        """
        Called on edge transition when engine exits Macro No Trade Zone.
        Dispatches high-priority alert to Group and Channel.
        """
        if not self.send_regime_alerts:
            return

        dedup_key = f"MACRO_NTZ_END:{int(time.time() // 300)}"
        if self.is_already_sent(dedup_key, ttl_seconds=600):
            return

        text = self.format_macro_ntz_end(btc_shield)
        if self.group_id:
            self._enqueue_message(self.group_id, text, priority=1)
        if self.channel_id:
            self._enqueue_message(self.channel_id, text, priority=1)
        logger.info("[WHATSAPP 🟢] Dispatched Macro NTZ END alert to queue")

    # =========================================================================
    # MANAGEMENT & DIAGNOSTIC ENDPOINTS
    # =========================================================================
    def get_status(self) -> Dict[str, Any]:
        """Returns diagnostic health of the WhatsApp dispatcher."""
        return {
            "enabled": self.enabled,
            "gateway_type": self.gateway_type,
            "api_url": self.api_url,
            "instance_name": self.instance_name,
            "group_configured": bool(self.group_id),
            "group_id": self.group_id,
            "channel_configured": bool(self.channel_id),
            "channel_id": self.channel_id,
            "min_grade": self.min_grade,
            "min_win_prob": self.min_win_prob,
            "queue_size": self._queue.qsize(),
            "has_redis_dedup": HAS_REDIS,
            "in_memory_keys_count": len(self._in_memory_dedup)
        }

# Global singleton
whatsapp_service = WhatsAppService()
