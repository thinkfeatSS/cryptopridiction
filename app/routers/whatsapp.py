from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any, Tuple
import json
import os
import html

from app.services.whatsapp_service import whatsapp_service
from app.config import settings

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

class BroadcastRequest(BaseModel):
    text: str
    target: Optional[str] = "both"  # "group" | "channel" | "both"

class TestSignalRequest(BaseModel):
    symbol: Optional[str] = "BTC/USDT"
    target: Optional[str] = "both"  # "group" | "channel" | "both"
    custom_target: Optional[str] = None  # Override JID directly (e.g. "120363xxx@g.us" or "120363xxx@newsletter")

@router.get("/status")
def get_whatsapp_status():
    """Returns the operational status and configuration of the WhatsApp dispatcher."""
    return whatsapp_service.get_status()

@router.post("/sync-terminal")
def sync_terminal_signals():
    """Forces synchronization between active V16 Terminal signals and WhatsApp."""
    count = whatsapp_service.sync_v16_terminal_signals()
    return {
        "status": "SUCCESS",
        "synced_count": count,
        "message": f"Successfully evaluated and synced {count} active V16 terminal signal(s) to WhatsApp queue."
    }

@router.post("/test")
def send_test_signal(req: TestSignalRequest):
    """Dispatches a test institutional signal to verify WhatsApp Group and Channel connectivity."""
    test_sig = {
        "signal_id": f"TEST_{req.symbol.replace('/', '_')}_SWING",
        "symbol": req.symbol,
        "direction": "LONG",
        "decision": "🎯 INSTITUTIONAL ORDER-BLOCK RETEST (LONG)",
        "horizon": "1H Day Trade",
        "quality_grade": "Grade A+ (HIGH CONVICTION)",
        "grade_tier": 1,
        "conviction_pct": 88.5,
        "meta_win_prob_pct": 81.2,
        "p_tp1": 81.2,
        "p_tp2": 52.8,
        "p_tp3": 29.0,
        "p_sl": 18.8,
        "entry_price": 84500.0,
        "tp1_price": 86100.0,
        "tp2_price": 87500.0,
        "tp3_price": 88900.0,
        "sl_price": 83100.0,
        "risk_reward_ratio": "1:2.4",
        "expected_return_pct": 4.15,
        "market_shield": "CONSOLIDATION (Mean Reversion Active)"
    }
    
    msg = whatsapp_service.format_new_signal(test_sig)
    
    queued_to = []

    # If a custom_target JID is directly specified, use it exclusively
    if req.custom_target:
        jid = req.custom_target.strip()
        whatsapp_service._enqueue_message(jid, msg)
        queued_to.append(jid)
    else:
        if req.target in ["group", "both"] and settings.WHATSAPP_GROUP_ID:
            whatsapp_service._enqueue_message(settings.WHATSAPP_GROUP_ID, msg)
            queued_to.append(settings.WHATSAPP_GROUP_ID)
            
        if req.target in ["channel", "both"] and settings.WHATSAPP_CHANNEL_ID:
            whatsapp_service._enqueue_message(settings.WHATSAPP_CHANNEL_ID, msg)
            queued_to.append(settings.WHATSAPP_CHANNEL_ID)

    return {
        "status": "QUEUED",
        "targets": queued_to,
        "message_preview": msg
    }

@router.post("/broadcast")
def broadcast_custom_message(req: BroadcastRequest):
    """Manually broadcasts a formatted text announcement to WhatsApp Group / Channel."""
    queued_to = []
    if req.target in ["group", "both"] and settings.WHATSAPP_GROUP_ID:
        whatsapp_service._enqueue_message(settings.WHATSAPP_GROUP_ID, req.text)
        queued_to.append(settings.WHATSAPP_GROUP_ID)
        
    if req.target in ["channel", "both"] and settings.WHATSAPP_CHANNEL_ID:
        whatsapp_service._enqueue_message(settings.WHATSAPP_CHANNEL_ID, req.text)
        queued_to.append(settings.WHATSAPP_CHANNEL_ID)

    return {
        "status": "QUEUED",
        "targets": queued_to,
        "text": req.text
    }

class SetTargetsRequest(BaseModel):
    group_id: Optional[str] = None
    group_invite_link: Optional[str] = None
    channel_id: Optional[str] = None
    send_test_message: Optional[bool] = True

@router.post("/set-targets")
def configure_targets(req: SetTargetsRequest):
    """
    Configures the WhatsApp Group and/or Channel targets for automated signal broadcasting.
    Accepts direct JIDs (e.g. 120363xxx@g.us or @newsletter) or group invite links (chat.whatsapp.com/...).
    """
    import re
    import requests

    resolved_group = req.group_id
    resolved_channel = req.channel_id
    info_notes = []

    # 1. Resolve Group from invite link if provided
    if req.group_invite_link and not resolved_group:
        m = re.search(r"(?:chat\.whatsapp\.com/|invite/)([a-zA-Z0-9]{22})", req.group_invite_link)
        if m:
            invite_code = m.group(1)
            api_url = settings.WHATSAPP_API_URL.rstrip('/')
            api_key = settings.WHATSAPP_API_KEY
            instance = settings.WHATSAPP_INSTANCE_NAME
            headers = {"apikey": api_key, "Content-Type": "application/json"}
            try:
                resp = requests.get(f"{api_url}/group/inviteInfo/{instance}?inviteCode={invite_code}", headers=headers, timeout=6.0)
                if resp.status_code == 200:
                    data = resp.json()
                    resolved_group = data.get("id")
                    info_notes.append(f"Resolved group '{data.get('subject')}' -> {resolved_group}")
                else:
                    info_notes.append(f"Failed to resolve invite link: {resp.text}")
            except Exception as e:
                info_notes.append(f"Error resolving invite link: {e}")
        else:
            info_notes.append("Group invite link did not match standard format (chat.whatsapp.com/<22-chars>).")

    # Update active settings
    # Resolve Channel from link if provided (detect whatsapp.com/channel/ format)
    if req.channel_id and re.search(r"https?://(?:www\.)?whatsapp\.com/channel/", req.channel_id):
        ch_code = req.channel_id.rstrip('/')
        ch_code = ch_code.split('/')[-1]
        api_url = settings.WHATSAPP_API_URL.rstrip('/')
        api_key = settings.WHATSAPP_API_KEY
        instance = settings.WHATSAPP_INSTANCE_NAME
        headers = {"apikey": api_key, "Content-Type": "application/json"}
        try:
            resp = requests.get(f"{api_url}/channel/inviteInfo/{instance}?inviteCode={ch_code}", headers=headers, timeout=6.0)
            if resp.status_code == 200:
                data = resp.json()
                resolved_channel = data.get("id")
                info_notes.append(f"Resolved channel '{data.get('subject')}' -> {resolved_channel}")
            else:
                info_notes.append(f"Failed to resolve channel link: {resp.text}")
        except Exception as e:
            info_notes.append(f"Error resolving channel link: {e}")
    if resolved_group:
        settings.WHATSAPP_GROUP_ID = resolved_group
        settings.WHATSAPP_ENABLED = True
    if resolved_channel:
        settings.WHATSAPP_CHANNEL_ID = resolved_channel
        settings.WHATSAPP_ENABLED = True

    # Persist to .env on disk if accessible
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    try:
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            if resolved_group:
                if "WHATSAPP_GROUP_ID=" in content:
                    content = re.sub(r'WHATSAPP_GROUP_ID=.*', f'WHATSAPP_GROUP_ID="{resolved_group}"', content)
                else:
                    content += f'\nWHATSAPP_GROUP_ID="{resolved_group}"'
            
            if resolved_channel:
                if "WHATSAPP_CHANNEL_ID=" in content:
                    content = re.sub(r'WHATSAPP_CHANNEL_ID=.*', f'WHATSAPP_CHANNEL_ID="{resolved_channel}"', content)
                else:
                    content += f'\nWHATSAPP_CHANNEL_ID="{resolved_channel}"'
            
            content = re.sub(r'WHATSAPP_ENABLED=.*', 'WHATSAPP_ENABLED=true', content)
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(content)
            info_notes.append("Saved targets to .env configuration.")
    except Exception as e:
        info_notes.append(f"Could not write to local .env: {e}")

    # Optional test message
    test_sent_to = []
    if req.send_test_message:
        init_msg = (
            "🚀 *Quant Prediction Engine • Activated!*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ *Broadcasting Initialized Successfully*\n"
            "📡 *Target:* Institutional Crypto Alpha Signals\n"
            "🛡️ *Quality Gate:* Grade A / A+ (Win Probability >= 70%)\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚡ Live continuous multi-horizon scanning active."
        )
        if resolved_group:
            whatsapp_service._enqueue_message(resolved_group, init_msg)
            test_sent_to.append(resolved_group)
        if resolved_channel:
            whatsapp_service._enqueue_message(resolved_channel, init_msg)
            test_sent_to.append(resolved_channel)

    return {
        "status": "CONFIGURED",
        "whatsapp_enabled": settings.WHATSAPP_ENABLED,
        "group_id": settings.WHATSAPP_GROUP_ID,
        "channel_id": settings.WHATSAPP_CHANNEL_ID,
        "test_messages_dispatched": test_sent_to,
        "notes": info_notes
    }

@router.get("/connect")
def connect_whatsapp_qr():
    """
    Renders an interactive QR Code scan page to link your WhatsApp phone directly
    via WhatsApp Web / Baileys multi-device.
    """
    from fastapi.responses import HTMLResponse
    import requests

    api_url = settings.WHATSAPP_API_URL.rstrip('/')
    api_key = settings.WHATSAPP_API_KEY
    instance = settings.WHATSAPP_INSTANCE_NAME

    headers = {"apikey": api_key, "Content-Type": "application/json"}

    # 1. Try to create instance if not exists
    try:
        requests.post(
            f"{api_url}/instance/create",
            json={"instanceName": instance, "qrcode": True, "integration": "WHATSAPP-BAILEYS"},
            headers=headers,
            timeout=5.0
        )
    except Exception:
        pass

    # 2. Fetch QR code or connection state
    qr_base64 = None
    state = "DISCONNECTED"
    try:
        state_resp = requests.get(f"{api_url}/instance/connectionState/{instance}", headers=headers, timeout=5.0)
        if state_resp.status_code == 200:
            state = state_resp.json().get("instance", {}).get("state", "DISCONNECTED")

        if state != "open":
            connect_resp = requests.get(f"{api_url}/instance/connect/{instance}", headers=headers, timeout=8.0)
            if connect_resp.status_code in [200, 201]:
                data = connect_resp.json()
                qr_base64 = data.get("base64")
    except Exception as e:
        state = f"GATEWAY_OFFLINE: {e}"

    if state == "open":
        body_content = f"""
        <div style="background:#064e3b; color:#a7f3d0; padding:28px; border-radius:16px; border:1px solid #059669; max-width:480px; margin:auto; text-align:center;">
            <div style="font-size:48px; margin-bottom:12px;">✅</div>
            <h2 style="margin:0 0 10px 0; color:#34d399;">WhatsApp Connected & Ready!</h2>
            <p style="color:#d1fae5; font-size:14px; margin-bottom:20px;">Your WhatsApp account is active and linked to the Quant Prediction Engine.</p>
            <div style="display:flex; flex-direction:column; gap:10px;">
                <a href="/api/whatsapp/groups" style="background:#047857; color:#fff; padding:10px 16px; border-radius:8px; text-decoration:none; font-weight:600;">👥 View WhatsApp Group IDs</a>
                <a href="/api/whatsapp/channels" style="background:#047857; color:#fff; padding:10px 16px; border-radius:8px; text-decoration:none; font-weight:600;">📢 View WhatsApp Channel IDs</a>
            </div>
        </div>
        """
    elif qr_base64:
        img_src = qr_base64 if qr_base64.startswith("data:image") else f"data:image/png;base64,{qr_base64}"
        body_content = f"""
        <div style="background:#111827; color:#f3f4f6; padding:24px; border-radius:16px; border:1px solid #374151; max-width:440px; margin:auto; text-align:center;">
            <h2 style="margin:0 0 8px 0; color:#38bdf8;">📱 Link WhatsApp to Quant Engine</h2>
            <p style="color:#9ca3af; font-size:13px; margin-bottom:16px;">
                1. Open WhatsApp on your phone.<br>
                2. Tap <b>Settings</b> or <b>⋮</b> &rarr; <b>Linked Devices</b>.<br>
                3. Tap <b>Link a Device</b> and point camera at the QR code below:
            </p>
            <div style="background:#ffffff; padding:12px; border-radius:12px; display:inline-block; margin-bottom:14px;">
                <img src="{img_src}" alt="WhatsApp QR Code" style="width:260px; height:260px; display:block;" />
            </div>
            <p style="color:#6b7280; font-size:12px; margin-bottom:12px;">This QR refreshes automatically. Page auto-reloads every 15 seconds.</p>
            <button onclick="location.reload()" style="background:#2563eb; color:#fff; border:none; padding:8px 16px; border-radius:8px; font-weight:bold; cursor:pointer;">🔄 Refresh QR Code</button>
        </div>
        <script>setTimeout(function(){{ location.reload(); }}, 15000);</script>
        """
    else:
        body_content = f"""
        <div style="background:#1f2937; color:#f87171; padding:24px; border-radius:16px; border:1px solid #dc2626; max-width:440px; margin:auto; text-align:center;">
            <h3 style="margin:0 0 10px 0;">⏳ Initializing WhatsApp Gateway...</h3>
            <p style="color:#e5e7eb;">Status: <b>{state}</b></p>
            <p style="color:#9ca3af; font-size:13px; margin-bottom:16px;">Generating connection session and QR code. Please wait a moment.</p>
            <button onclick="location.reload()" style="background:#3b82f6; color:#fff; padding:10px 20px; border:none; border-radius:8px; cursor:pointer; font-weight:bold;">Refresh Page</button>
        </div>
        <script>setTimeout(function(){{ location.reload(); }}, 5000);</script>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>WhatsApp Connection • Quant Engine</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background:#030712; color:#fff; display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; padding:16px; }}
        </style>
    </head>
    <body>
        {body_content}
    </body>
    </html>
    """
    return HTMLResponse(content=html)

def _fetch_groups_from_storage_or_api() -> Tuple[List[Dict[str, Any]], str]:
    """Fetches groups with sub-millisecond latency from Redis DB 2 cache, falling back to Baileys API."""
    groups = []
    
    # 1. Primary: Direct Redis DB 2 Cache (Evolution API cache)
    try:
        import redis
        for host in ["crypto_redis", "127.0.0.1", "localhost"]:
            try:
                r = redis.Redis(host=host, port=6379, db=2, decode_responses=True, socket_timeout=1.5)
                keys = r.keys("evolution:groups:*")
                if keys:
                    for k in keys:
                        val = r.get(k)
                        if not val:
                            continue
                        try:
                            obj = json.loads(val)
                            data = obj.get("data", obj)
                            gid = data.get("id") or k.replace("evolution:groups:", "")
                            sub = data.get("subject") or "WhatsApp Group"
                            cnt = data.get("size") or len(data.get("participants", []))
                            groups.append({
                                "group_id": gid,
                                "group_name": sub,
                                "members_count": cnt,
                                "creation": data.get("creation")
                            })
                        except Exception:
                            gid = k.replace("evolution:groups:", "")
                            groups.append({
                                "group_id": gid,
                                "group_name": "WhatsApp Group",
                                "members_count": 0,
                                "creation": None
                            })
                    break
            except Exception:
                continue
    except Exception:
        pass

    if groups:
        groups.sort(key=lambda x: (x.get("group_name") or "").lower())
        return groups, "redis_cache"

    # 2. Secondary: Fallback to Evolution API query with short 4s timeout
    import requests
    api_url = settings.WHATSAPP_API_URL.rstrip('/')
    api_key = settings.WHATSAPP_API_KEY
    instance = settings.WHATSAPP_INSTANCE_NAME
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    try:
        resp = requests.get(f"{api_url}/group/fetchAllGroups/{instance}?getParticipants=false", headers=headers, timeout=4.0)
        if resp.status_code == 200:
            groups_data = resp.json()
            for g in (groups_data if isinstance(groups_data, list) else []):
                groups.append({
                    "group_id": g.get("id"),
                    "group_name": g.get("subject") or "WhatsApp Group",
                    "members_count": g.get("size", 0),
                    "creation": g.get("creation")
                })
            if groups:
                groups.sort(key=lambda x: (x.get("group_name") or "").lower())
                return groups, "evolution_api"
    except Exception:
        pass

    return groups, "empty"


def _fetch_channels_from_storage() -> List[Dict[str, Any]]:
    """Detects and returns active WhatsApp Channels / Newsletters."""
    channels = []
    seen = set()

    # Primary: use the configured channel from settings (most reliable)
    if settings.WHATSAPP_CHANNEL_ID and "@newsletter" in settings.WHATSAPP_CHANNEL_ID:
        channels.append({
            "channel_id": settings.WHATSAPP_CHANNEL_ID,
            "channel_name": "Configured Channel (Active)",
            "source": "settings"
        })
        seen.add(settings.WHATSAPP_CHANNEL_ID)

    # Secondary: Scan Redis for any additional detected newsletter JIDs
    try:
        import redis
        for host in ["crypto_redis", "127.0.0.1", "localhost"]:
            try:
                r = redis.Redis(host=host, port=6379, db=2, decode_responses=True, socket_timeout=1.5)
                n_keys = r.keys("*newsletter*")
                for k in n_keys:
                    jid = k.split(":")[-1] if ":" in k else k
                    if "@newsletter" in jid and jid not in seen:
                        channels.append({
                            "channel_id": jid,
                            "channel_name": "WhatsApp Channel (Detected)",
                            "source": "redis_cache"
                        })
                        seen.add(jid)
                break
            except Exception:
                continue
    except Exception:
        pass

    # Tertiary: Try Evolution API newsletter/fetchAll
    if not channels:
        try:
            import requests as req_lib
            api_url = settings.WHATSAPP_API_URL.rstrip('/')
            headers = {"apikey": settings.WHATSAPP_API_KEY, "Content-Type": "application/json"}
            instance = settings.WHATSAPP_INSTANCE_NAME
            resp = req_lib.get(f"{api_url}/newsletter/fetchAll/{instance}", headers=headers, timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                newsletters = data if isinstance(data, list) else (data.get("newsletters") or [])
                for n in newsletters:
                    jid = n.get("id") or n.get("newsletterJid") or ""
                    name = n.get("name") or n.get("subject") or "WhatsApp Channel"
                    if jid and jid not in seen:
                        channels.append({
                            "channel_id": jid,
                            "channel_name": name,
                            "source": "evolution_api"
                        })
                        seen.add(jid)
        except Exception:
            pass

    return channels


@router.get("/groups")
def list_whatsapp_groups(request: Request, format: Optional[str] = None):
    """
    Fetches all WhatsApp Groups joined by the connected WhatsApp bot account.
    Returns an interactive, dark-mode dashboard when opened in a browser, or JSON via API.
    """
    import requests
    api_url = settings.WHATSAPP_API_URL.rstrip('/')
    api_key = settings.WHATSAPP_API_KEY
    instance = settings.WHATSAPP_INSTANCE_NAME
    headers = {"apikey": api_key, "Content-Type": "application/json"}

    # Pre-flight connection check with short timeout
    state = "open"
    try:
        state_resp = requests.get(f"{api_url}/instance/connectionState/{instance}", headers=headers, timeout=3.0)
        if state_resp.status_code == 200:
            state = state_resp.json().get("instance", {}).get("state", "DISCONNECTED")
    except Exception:
        pass

    # Determine if user is visiting via browser
    accept_hdr = request.headers.get("accept", "")
    is_browser = "text/html" in accept_hdr and format != "json"

    if state != "open":
        if is_browser:
            return HTMLResponse(content=f"""
            <!DOCTYPE html><html><head><title>WhatsApp Not Linked</title><meta name="viewport" content="width=device-width, initial-scale=1">
            <style>body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background:#030712; color:#fff; display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; padding:16px; }}</style>
            </head><body>
            <div style="background:#1f2937; color:#f87171; padding:28px; border-radius:16px; border:1px solid #dc2626; max-width:480px; text-align:center;">
                <div style="font-size:44px; margin-bottom:12px;">⚠️</div>
                <h3 style="margin:0 0 10px 0; color:#fca5a5;">WhatsApp Not Linked</h3>
                <p style="color:#d1d5db; font-size:14px; margin-bottom:20px;">Your WhatsApp instance <b>{instance}</b> is in state: <code>{state}</code>.<br>Please scan the QR code to link your phone.</p>
                <a href="/api/whatsapp/connect" style="background:#2563eb; color:#fff; padding:10px 20px; border-radius:8px; text-decoration:none; font-weight:bold;">📱 Scan QR Code</a>
            </div></body></html>
            """, status_code=200)
        return {
            "status": "NOT_CONNECTED",
            "connection_state": state,
            "message": f"WhatsApp instance '{instance}' is in state '{state}'. Please link your phone first.",
            "connect_url": "https://bullsandbears.binaryunit.tech/api/whatsapp/connect"
        }

    # Fetch groups
    groups, source = _fetch_groups_from_storage_or_api()

    # If requested as JSON
    if not is_browser:
        return {
            "status": "SUCCESS",
            "total_groups": len(groups),
            "source": source,
            "groups": groups
        }

    # Render High-End Dark Interactive UI for browser
    cards_html = ""
    for g in groups:
        gid = g.get("group_id", "")
        name = html.escape(str(g.get("group_name", "WhatsApp Group")))
        members = g.get("members_count", 0)
        cards_html += f"""
        <div class="group-card" data-name="{name.lower()}" data-id="{gid.lower()}" style="background:#111827; border:1px solid #1f2937; border-radius:12px; padding:16px; display:flex; justify-content:space-between; align-items:center; gap:16px; transition:border-color 0.2s, transform 0.2s;">
            <div style="flex:1; min-width:0;">
                <div style="font-size:16px; font-weight:700; color:#f9fafb; margin-bottom:6px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">{name}</div>
                <div style="display:flex; flex-wrap:wrap; align-items:center; gap:8px;">
                    <span style="background:#064e3b; color:#6ee7b7; font-size:12px; font-weight:600; padding:3px 8px; border-radius:6px;">👥 {members} members</span>
                    <code style="background:#030712; color:#38bdf8; font-size:12px; padding:3px 8px; border-radius:6px; font-family:monospace; border:1px solid #1e293b;">{gid}</code>
                </div>
            </div>
            <button onclick="copyId('{gid}', this)" style="background:#1e293b; color:#e2e8f0; border:1px solid #334155; padding:8px 14px; border-radius:8px; font-size:13px; font-weight:600; cursor:pointer; white-space:nowrap; transition:all 0.2s;">📋 Copy ID</button>
        </div>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>WhatsApp Groups Directory • Quant Prediction Engine</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * {{ box-sizing: border-box; }}
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background:#030712; color:#f3f4f6; margin:0; padding:24px 16px; }}
            .container {{ max-width:860px; margin:auto; }}
            .group-card:hover {{ border-color:#38bdf8 !important; transform:translateY(-1px); }}
            .btn-nav {{ background:#1e293b; color:#e2e8f0; padding:8px 14px; border-radius:8px; text-decoration:none; font-size:13px; font-weight:600; border:1px solid #334155; display:inline-flex; align-items:center; gap:6px; }}
            .btn-nav:hover {{ background:#334155; color:#fff; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-bottom:20px;">
                <div>
                    <h2 style="margin:0 0 6px 0; color:#10b981; font-size:24px; display:flex; align-items:center; gap:10px;">
                        <span>👥 Linked WhatsApp Groups</span>
                        <span style="background:#064e3b; color:#34d399; font-size:13px; font-weight:700; padding:4px 10px; border-radius:20px;">{len(groups)} Active</span>
                    </h2>
                    <p style="margin:0; color:#9ca3af; font-size:14px;">Select any Group ID below to configure automated trade signal broadcasting.</p>
                </div>
                <div style="display:flex; gap:8px;">
                    <a href="/api/whatsapp/channels" class="btn-nav">📢 View Channels</a>
                    <a href="/api/whatsapp/connect" class="btn-nav">📱 Gateway QR</a>
                </div>
            </div>

            <!-- Search and Action Bar -->
            <div style="background:#111827; border:1px solid #1f2937; border-radius:12px; padding:12px 16px; margin-bottom:20px; display:flex; gap:12px; align-items:center;">
                <input type="text" id="searchInput" oninput="filterCards()" placeholder="🔍 Filter groups by name or ID..." style="flex:1; background:#030712; border:1px solid #374151; color:#fff; padding:10px 14px; border-radius:8px; font-size:14px; outline:none;" />
                <span id="counter" style="color:#9ca3af; font-size:13px; font-weight:600; white-space:nowrap;">{len(groups)} visible</span>
            </div>

            <!-- Cards Container -->
            <div id="cardsList" style="display:flex; flex-direction:column; gap:10px;">
                {cards_html}
            </div>

            <div style="margin-top:28px; text-align:center; padding:16px; background:#0f172a; border-radius:12px; border:1px solid #1e293b; color:#94a3b8; font-size:13px;">
                💡 <b>How to start broadcasting:</b> Copy the Group ID above and paste it as <code>WHATSAPP_GROUP_ID</code> in your <code>.env</code> file. The Quant Prediction Engine will automatically send verified high-conviction signals directly to the group.
            </div>
        </div>

        <script>
            function filterCards() {{
                const q = document.getElementById('searchInput').value.toLowerCase().trim();
                const cards = document.querySelectorAll('.group-card');
                let visible = 0;
                cards.forEach(c => {{
                    const n = c.getAttribute('data-name');
                    const id = c.getAttribute('data-id');
                    if (!q || n.includes(q) || id.includes(q)) {{
                        c.style.display = 'flex';
                        visible++;
                    }} else {{
                        c.style.display = 'none';
                    }}
                }});
                document.getElementById('counter').innerText = visible + ' visible';
            }}

            function copyId(id, btn) {{
                navigator.clipboard.writeText(id).then(() => {{
                    const orig = btn.innerText;
                    btn.innerText = '✅ Copied!';
                    btn.style.background = '#059669';
                    btn.style.color = '#fff';
                    btn.style.borderColor = '#10b981';
                    setTimeout(() => {{
                        btn.innerText = orig;
                        btn.style.background = '#1e293b';
                        btn.style.color = '#e2e8f0';
                        btn.style.borderColor = '#334155';
                    }}, 2000);
                }});
            }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@router.get("/channels")
def list_whatsapp_channels(request: Request, format: Optional[str] = None):
    """
    Fetches all WhatsApp Channels (Newsletters) associated with the bot account.
    Returns an interactive dashboard when opened in a browser, or JSON via API.
    """
    import requests
    api_url = settings.WHATSAPP_API_URL.rstrip('/')
    api_key = settings.WHATSAPP_API_KEY
    instance = settings.WHATSAPP_INSTANCE_NAME
    headers = {"apikey": api_key, "Content-Type": "application/json"}

    # Pre-flight connection check with short timeout
    state = "open"
    try:
        state_resp = requests.get(f"{api_url}/instance/connectionState/{instance}", headers=headers, timeout=3.0)
        if state_resp.status_code == 200:
            state = state_resp.json().get("instance", {}).get("state", "DISCONNECTED")
    except Exception:
        pass

    accept_hdr = request.headers.get("accept", "")
    is_browser = "text/html" in accept_hdr and format != "json"

    if state != "open":
        if is_browser:
            return HTMLResponse(content=f"""
            <!DOCTYPE html><html><head><title>WhatsApp Not Linked</title><meta name="viewport" content="width=device-width, initial-scale=1">
            <style>body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background:#030712; color:#fff; display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; padding:16px; }}</style>
            </head><body>
            <div style="background:#1f2937; color:#f87171; padding:28px; border-radius:16px; border:1px solid #dc2626; max-width:480px; text-align:center;">
                <div style="font-size:44px; margin-bottom:12px;">⚠️</div>
                <h3 style="margin:0 0 10px 0; color:#fca5a5;">WhatsApp Not Linked</h3>
                <p style="color:#d1d5db; font-size:14px; margin-bottom:20px;">Your WhatsApp instance <b>{instance}</b> is in state: <code>{state}</code>.<br>Please scan the QR code to link your phone.</p>
                <a href="/api/whatsapp/connect" style="background:#2563eb; color:#fff; padding:10px 20px; border-radius:8px; text-decoration:none; font-weight:bold;">📱 Scan QR Code</a>
            </div></body></html>
            """, status_code=200)
        return {
            "status": "NOT_CONNECTED",
            "connection_state": state,
            "message": f"WhatsApp instance '{instance}' is in state '{state}'. Please link your phone first.",
            "connect_url": "https://bullsandbears.binaryunit.tech/api/whatsapp/connect"
        }

    channels = _fetch_channels_from_storage()

    if not is_browser:
        return {
            "status": "SUCCESS",
            "total_channels": len(channels),
            "channels": channels,
            "channel_id_help": "Channel JID format is typically '120363xxxxxxxxx@newsletter'. You can find it from the WhatsApp Channel link or WhatsApp Web."
        }

    cards_html = ""
    for ch in channels:
        cid = ch.get("channel_id", "")
        name = html.escape(str(ch.get("channel_name", "WhatsApp Channel")))
        src = ch.get("source", "active")
        cards_html += f"""
        <div style="background:#111827; border:1px solid #1f2937; border-radius:12px; padding:16px; display:flex; justify-content:space-between; align-items:center; gap:16px;">
            <div style="flex:1; min-width:0;">
                <div style="font-size:16px; font-weight:700; color:#f9fafb; margin-bottom:6px;">{name}</div>
                <div style="display:flex; align-items:center; gap:8px;">
                    <span style="background:#064e3b; color:#34d399; font-size:12px; font-weight:600; padding:3px 8px; border-radius:6px;">📢 Channel</span>
                    <code style="background:#030712; color:#38bdf8; font-size:12px; padding:3px 8px; border-radius:6px; font-family:monospace; border:1px solid #1e293b;">{cid}</code>
                </div>
            </div>
            <button onclick="copyId('{cid}', this)" style="background:#1e293b; color:#e2e8f0; border:1px solid #334155; padding:8px 14px; border-radius:8px; font-size:13px; font-weight:600; cursor:pointer; white-space:nowrap; transition:all 0.2s;">📋 Copy Channel ID</button>
        </div>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>WhatsApp Channels • Quant Prediction Engine</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * {{ box-sizing: border-box; }}
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background:#030712; color:#f3f4f6; margin:0; padding:24px 16px; }}
            .container {{ max-width:860px; margin:auto; }}
            .btn-nav {{ background:#1e293b; color:#e2e8f0; padding:8px 14px; border-radius:8px; text-decoration:none; font-size:13px; font-weight:600; border:1px solid #334155; display:inline-flex; align-items:center; gap:6px; }}
            .btn-nav:hover {{ background:#334155; color:#fff; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-bottom:20px;">
                <div>
                    <h2 style="margin:0 0 6px 0; color:#38bdf8; font-size:24px; display:flex; align-items:center; gap:10px;">
                        <span>📢 Linked WhatsApp Channels</span>
                        <span style="background:#0c4a6e; color:#7dd3fc; font-size:13px; font-weight:700; padding:4px 10px; border-radius:20px;">{len(channels)} Available</span>
                    </h2>
                    <p style="margin:0; color:#9ca3af; font-size:14px;">Broadcast institutional signals to public or private WhatsApp announcement channels.</p>
                </div>
                <div style="display:flex; gap:8px;">
                    <a href="/api/whatsapp/groups" class="btn-nav">👥 View Groups</a>
                    <a href="/api/whatsapp/connect" class="btn-nav">📱 Gateway QR</a>
                </div>
            </div>

            <div style="display:flex; flex-direction:column; gap:10px; margin-bottom:24px;">
                {cards_html}
            </div>

            <div style="background:#111827; border:1px solid #1f2937; border-radius:12px; padding:20px; color:#d1d5db; font-size:14px;">
                <h4 style="margin:0 0 10px 0; color:#f3f4f6; font-size:16px;">💡 How to use a WhatsApp Channel for Signal Alerts:</h4>
                <ol style="margin:0 0 14px 0; padding-left:20px; line-height:1.7;">
                    <li>Copy the <b>Channel ID</b> above (format: <code>120363xxxxxxxxx@newsletter</code>).</li>
                    <li>Paste it in your VPS configuration as <code>WHATSAPP_CHANNEL_ID="120363xxxxxxxxx@newsletter"</code>.</li>
                    <li>If you create a new Channel, send or forward any message from it in WhatsApp. The gateway automatically indexes the newsletter JID.</li>
                </ol>
            </div>
        </div>

        <script>
            function copyId(id, btn) {{
                navigator.clipboard.writeText(id).then(() => {{
                    const orig = btn.innerText;
                    btn.innerText = '✅ Copied!';
                    btn.style.background = '#059669';
                    btn.style.color = '#fff';
                    btn.style.borderColor = '#10b981';
                    setTimeout(() => {{
                        btn.innerText = orig;
                        btn.style.background = '#1e293b';
                        btn.style.color = '#e2e8f0';
                        btn.style.borderColor = '#334155';
                    }}, 2000);
                }});
            }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
