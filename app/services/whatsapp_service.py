import os
import time
import json
import logging
import threading
import queue
import requests
from typing import Dict, Any, Optional, List, Union
from datetime import datetime, timezone

from app.config import settings

logger = logging.getLogger("whatsapp_service")
logger.setLevel(logging.INFO)

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
        
        # Start async consumer worker
        self._start_worker()

    def _start_worker(self):
        """Starts background worker thread to process outbound messages with pacing."""
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._worker_thread = threading.Thread(
                target=self._process_queue,
                name="whatsapp_dispatcher_worker",
                daemon=True
            )
            self._worker_thread.start()

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
        - Group: Grade A or Grade A+, ML Win Prob >= settings.WHATSAPP_MIN_WIN_PROB
        - Channel: Grade A+ only, or Meta-Win Prob >= 75%
        """
        grade = str(sig.get("quality_grade") or sig.get("grade") or "").upper()
        grade_tier = sig.get("grade_tier", 3)
        win_prob = float(sig.get("meta_win_prob_pct") or (float(sig.get("meta_win_prob", 0.5)) * 100.0 if float(sig.get("meta_win_prob", 0.5)) <= 1.0 else sig.get("meta_win_prob", 50.0)))
        conviction = float(sig.get("conviction_pct") or sig.get("conviction") or 50.0)

        # Baseline: Grade must be A or A+
        is_grade_a = ("GRADE A" in grade) or (grade_tier <= 2)
        if not is_grade_a and "GRADE A+" not in grade:
            return False

        # Channel requires higher hurdle (Grade A+ or >= 75% win probability)
        if is_channel:
            if "GRADE A+" not in grade and win_prob < 75.0 and conviction < 75.0:
                return False

        # ML Win Probability gate
        min_prob = settings.WHATSAPP_MIN_WIN_PROB * 100.0 if settings.WHATSAPP_MIN_WIN_PROB <= 1.0 else settings.WHATSAPP_MIN_WIN_PROB
        if win_prob < min_prob and conviction < min_prob:
            return False

        return True

    # =========================================================================
    # MESSAGE FORMATTERS (WHATSAPP NATIVE MARKDOWN)
    # =========================================================================
    @staticmethod
    def _format_price(val: Any) -> str:
        try:
            f = float(val)
            if f >= 1000:
                return f"${f:,.2f}"
            elif f >= 1:
                return f"${f:.4f}"
            elif f >= 0.001:
                return f"${f:.6f}"
            else:
                return f"${f:.8f}"
        except Exception:
            return f"${val}"

    def format_new_signal(self, sig: Dict[str, Any]) -> str:
        sym = sig.get("symbol", "BTC/USDT")
        direction = str(sig.get("direction", "LONG")).upper()
        is_long = direction in ["LONG", "BULLISH", "BUY"]
        dir_emoji = "🟢 *LONG BUY*" if is_long else "🔴 *SHORT SELL*"
        horizon = sig.get("horizon", "1H Swing")
        grade = sig.get("quality_grade") or sig.get("grade") or "Grade A+"
        
        conviction = float(sig.get("conviction_pct") or sig.get("conviction") or 75.0)
        win_prob = float(sig.get("meta_win_prob_pct") or (float(sig.get("meta_win_prob", 0.75)) * 100.0 if float(sig.get("meta_win_prob", 0.75)) <= 1.0 else sig.get("meta_win_prob", 75.0)))
        
        entry = self._format_price(sig.get("entry_price", 0.0))
        tp1 = self._format_price(sig.get("tp1_price", 0.0))
        tp2 = self._format_price(sig.get("tp2_price", 0.0))
        tp3 = self._format_price(sig.get("tp3_price", 0.0))
        sl = self._format_price(sig.get("sl_price", 0.0))
        
        rr = sig.get("risk_reward_ratio", "1:2.0")
        exp_ret = float(sig.get("expected_return_pct") or (float(sig.get("exp_return", 0.035)) * 100.0 if float(sig.get("exp_return", 0.035)) <= 1.0 else sig.get("exp_return", 3.5)))
        
        market_shield = sig.get("market_shield", "CONSOLIDATION")

        msg = (
            f"⚡ *QUANT EDGE AI • NEW INSTITUTIONAL SIGNAL* ⚡\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Pair:* #{sym.replace('/', '_')} ({horizon})\n"
            f"📊 *Direction:* {dir_emoji}\n"
            f"💎 *Grade:* {grade} ({conviction:.1f}% AI Conviction)\n"
            f"🧠 *ML Win Probability:* {win_prob:.1f}%\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 *Entry Zone:* {entry}\n"
            f"🎯 *Target 1 (TP1):* {tp1}\n"
            f"🎯 *Target 2 (TP2):* {tp2}\n"
            f"🎯 *Target 3 (TP3):* {tp3}\n"
            f"🛑 *Invalidation (SL):* {sl}\n"
            f"⚖️ *Risk:Reward:* {rr} | *Exp. Gain:* +{abs(exp_ret):.2f}%\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ *BTC Shield:* {market_shield}\n"
            f"🔗 *Live Terminal:* https://bullsandbears.binaryunit.tech"
        )
        return msg

    def format_tp_hit(self, sig: Dict[str, Any], level: str, current_price: float, gain_pct: float) -> str:
        sym = sig.get("symbol", "BTC/USDT")
        horizon = sig.get("horizon", "1H Swing")
        f_price = self._format_price(current_price)

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

        msg = (
            f"{title}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Coin: *{sym}* ({horizon})\n"
            f"Current Price: *{f_price}*\n"
            f"{action_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 Track live: https://bullsandbears.binaryunit.tech"
        )
        return msg

    def format_sl_hit(self, sig: Dict[str, Any], exit_price: float, loss_pct: float) -> str:
        sym = sig.get("symbol", "BTC/USDT")
        horizon = sig.get("horizon", "1H Swing")
        f_price = self._format_price(exit_price)
        msg = (
            f"🛑 *TRADE INVALIDATION / STOP-LOSS ALERT* ⚠️\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Coin: *{sym}* ({horizon})\n"
            f"Exit Price: *{f_price}* (-{abs(loss_pct):.2f}%)\n"
            f"Status: *Closed under strict risk control*\n"
            f"Capital preservation rule executed. Waiting for next high-probability setup.\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 https://bullsandbears.binaryunit.tech"
        )
        return msg

    def format_regime_shift(self, shield_data: Dict[str, Any]) -> str:
        regime = shield_data.get("status_code") or shield_data.get("regime") or "CONSOLIDATION"
        reason = shield_data.get("reason", "Dynamic Market Shift")
        cons_prob = shield_data.get("cons_prob", 50.0)
        posture = shield_data.get("posture", "NORMAL")

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

    # =========================================================================
    # DISPATCH QUEUE & WORKER
    # =========================================================================
    def _enqueue_message(self, target_jid: str, text: str, priority: int = 10):
        if not target_jid:
            return
        item = {
            "target": target_jid,
            "text": text,
            "ts": time.time(),
            "priority": priority
        }
        try:
            self._queue.put_nowait(item)
            logger.info(f"[WHATSAPP 📤] Queued message to {target_jid[:15]}... (Queue size: {self._queue.qsize()})")
        except queue.Full:
            logger.error("[WHATSAPP ❌] Outbound queue full! Dropping message.")

    def _process_queue(self):
        """Worker loop that sends messages with anti-ban delay."""
        while self._running:
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                # Anti-ban Pacing delay: Ensure at least WHATSAPP_RATE_LIMIT_SECONDS between messages
                now = time.time()
                elapsed = now - self._last_dispatch_ts
                required_delay = max(1.5, float(settings.WHATSAPP_RATE_LIMIT_SECONDS))
                if elapsed < required_delay:
                    time.sleep(required_delay - elapsed)

                self._send_http(item["target"], item["text"])
                self._last_dispatch_ts = time.time()
            except Exception as e:
                logger.error(f"[WHATSAPP ❌] Error sending queued message: {e}")
            finally:
                self._queue.task_done()

    def _send_http(self, target_jid: str, text: str) -> bool:
        """Sends payload to configured WhatsApp gateway.
        
        IMPORTANT: WhatsApp Channel/Newsletter JIDs (ending in @newsletter) require
        a DIFFERENT API endpoint than groups/DMs. This method auto-detects and routes
        to the correct endpoint.
        """
        if not settings.WHATSAPP_ENABLED:
            logger.debug(f"[WHATSAPP MOCK] (Disabled) Would send to {target_jid}:\n{text[:60]}...")
            return True

        gateway_type = settings.WHATSAPP_GATEWAY_TYPE.lower()
        api_url = settings.WHATSAPP_API_URL.rstrip('/')
        api_key = settings.WHATSAPP_API_KEY
        instance = settings.WHATSAPP_INSTANCE_NAME
        is_newsletter = "@newsletter" in target_jid

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
                        return True
                    else:
                        logger.warning(f"[WHATSAPP ⚠️] Gateway returned HTTP {resp.status_code}: {resp.text[:200]}")
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

        except Exception as e:
            logger.error(f"[WHATSAPP ❌] HTTP exception to gateway (target={target_jid}): {e}")
            return False

    # =========================================================================
    # PUBLIC HIGH-LEVEL AUTOMATION HOOKS
    # =========================================================================
    def emit_signal_created(self, sig: Dict[str, Any]):
        """
        Called when a new signal is admitted into SignalAuditTracker.
        Automatically broadcasts to WhatsApp Group and/or Channel.
        """
        sig_id = sig.get("signal_id") or f"{sig.get('symbol')}_{sig.get('horizon')}"
        dedup_key = f"{sig_id}:SIGNAL_CREATED"

        if self.is_already_sent(dedup_key):
            return

        # Check Quality Gate for Group
        group_jid = settings.WHATSAPP_GROUP_ID
        if group_jid and self.passes_quality_gate(sig, is_channel=False):
            text = self.format_new_signal(sig)
            self._enqueue_message(group_jid, text, priority=1)

        # Check Quality Gate for Channel (higher hurdle)
        channel_jid = settings.WHATSAPP_CHANNEL_ID
        if channel_jid and self.passes_quality_gate(sig, is_channel=True):
            text = self.format_new_signal(sig)
            self._enqueue_message(channel_jid, text, priority=1)

    def emit_signal_outcome(self, sig: Dict[str, Any], event_type: str, current_price: float, gain_pct: float):
        """
        Called on heartbeat evaluation when a TP or SL is touched.
        event_type in: TP1_HIT, TP2_HIT, TP3_HIT, SL_HIT
        """
        sig_id = sig.get("signal_id") or f"{sig.get('symbol')}_{sig.get('horizon')}"
        dedup_key = f"{sig_id}:{event_type}"

        if self.is_already_sent(dedup_key):
            return

        group_jid = settings.WHATSAPP_GROUP_ID
        channel_jid = settings.WHATSAPP_CHANNEL_ID

        if event_type in ["TP1_HIT", "TP2_HIT", "TP3_HIT"]:
            if not settings.WHATSAPP_SEND_TP_UPDATES:
                return
            level = "TP1" if event_type == "TP1_HIT" else ("TP2" if event_type == "TP2_HIT" else "TP3")
            text = self.format_tp_hit(sig, level, current_price, gain_pct)

            # Send TP1, TP2, TP3 to VIP Group
            if group_jid:
                self._enqueue_message(group_jid, text, priority=2)

            # Send TP1 and TP3 Won to Public Channel
            if channel_jid and level in ["TP1", "TP3"]:
                self._enqueue_message(channel_jid, text, priority=2)

        elif event_type == "SL_HIT":
            if not settings.WHATSAPP_SEND_SL_UPDATES:
                return
            text = self.format_sl_hit(sig, current_price, gain_pct)
            # Invalidation sent to Group
            if group_jid:
                self._enqueue_message(group_jid, text, priority=3)

    def emit_regime_alert(self, shield_data: Dict[str, Any]):
        """
        Called when BTC switches regime or trips a circuit breaker.
        """
        if not settings.WHATSAPP_SEND_REGIME_ALERTS:
            return

        regime = shield_data.get("status_code") or shield_data.get("regime") or "NORMAL"
        # Only notify on significant market regime shifts
        if regime in ["NORMAL"]:
            return

        # Deduplicate: Only 1 regime alert per 30 minutes
        bucket_30m = int(time.time() // 1800)
        dedup_key = f"REGIME_SHIFT:{regime}:{bucket_30m}"
        if self.is_already_sent(dedup_key, ttl_seconds=1800):
            return

        text = self.format_regime_shift(shield_data)
        if settings.WHATSAPP_GROUP_ID:
            self._enqueue_message(settings.WHATSAPP_GROUP_ID, text, priority=1)
        if settings.WHATSAPP_CHANNEL_ID:
            self._enqueue_message(settings.WHATSAPP_CHANNEL_ID, text, priority=1)

    # =========================================================================
    # MANAGEMENT & DIAGNOSTIC ENDPOINTS
    # =========================================================================
    def get_status(self) -> Dict[str, Any]:
        """Returns diagnostic health of the WhatsApp dispatcher."""
        return {
            "enabled": settings.WHATSAPP_ENABLED,
            "gateway_type": settings.WHATSAPP_GATEWAY_TYPE,
            "api_url": settings.WHATSAPP_API_URL,
            "instance_name": settings.WHATSAPP_INSTANCE_NAME,
            "group_configured": bool(settings.WHATSAPP_GROUP_ID),
            "group_id": settings.WHATSAPP_GROUP_ID,
            "channel_configured": bool(settings.WHATSAPP_CHANNEL_ID),
            "channel_id": settings.WHATSAPP_CHANNEL_ID,
            "queue_size": self._queue.qsize(),
            "has_redis_dedup": HAS_REDIS,
            "in_memory_keys_count": len(self._in_memory_dedup)
        }

# Global singleton
whatsapp_service = WhatsAppService()
