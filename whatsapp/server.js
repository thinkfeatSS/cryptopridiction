const express = require("express");
const {
  default: makeWASocket,
  DisconnectReason,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  Browsers,
} = require("@whiskeysockets/baileys");
const QRCode = require("qrcode");
const pino = require("pino");
const path = require("path");
const fs = require("fs");

const app = express();
app.use(express.json());

const PORT = process.env.PORT || 8080;
const AUTH_DIR = path.join(__dirname, "auth_info_baileys");

if (!fs.existsSync(AUTH_DIR)) {
  fs.mkdirSync(AUTH_DIR, { recursive: true });
}

let sock = null;
let currentQrBase64 = null;
let connectionState = "connecting";
let reconnectAttempts = 0;

const logger = pino({ level: "warn" });

async function initBaileys() {
  try {
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
    const { version } = await fetchLatestBaileysVersion();

    sock = makeWASocket({
      version,
      auth: state,
      logger,
      printQRInTerminal: true,
      browser: Browsers.macOS("Chrome"),
      defaultQueryTimeoutMs: 60000,
      generateHighQualityLinkPreview: true,
      syncFullHistory: false,
    });

    sock.ev.on("creds.update", saveCreds);

    sock.ev.on("connection.update", async (update) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        try {
          currentQrBase64 = await QRCode.toDataURL(qr, { margin: 2, scale: 8 });
          connectionState = "connecting";
          console.log("[BAILEYS 📱] New QR Code generated ready for scanning.");
        } catch (err) {
          console.error("[BAILEYS ❌] Failed to generate QR base64:", err);
        }
      }

      if (connection === "close") {
        currentQrBase64 = null;
        connectionState = "close";
        const statusCode = lastDisconnect?.error?.output?.statusCode;
        const shouldReconnect = statusCode !== DisconnectReason.loggedOut;

        console.log(`[BAILEYS 🔌] Connection closed. Reason code: ${statusCode}. Reconnecting: ${shouldReconnect}`);

        if (shouldReconnect) {
          reconnectAttempts++;
          const delay = Math.min(reconnectAttempts * 3000, 15000);
          setTimeout(initBaileys, delay);
        } else {
          console.log("[BAILEYS ⚠️] Session logged out. Please restart container to re-pair.");
        }
      } else if (connection === "open") {
        reconnectAttempts = 0;
        currentQrBase64 = null;
        connectionState = "open";
        console.log("[BAILEYS ✅] WhatsApp Connected successfully!");
      }
    });
  } catch (err) {
    console.error("[BAILEYS ❌] Initialization error:", err);
    setTimeout(initBaileys, 5000);
  }
}

// ============================================================================
// REST API ENDPOINTS
// ============================================================================

// 1. Connection State
app.get("/instance/connectionState/:instance?", (req, res) => {
  res.json({
    instance: {
      instanceName: req.params.instance || "crypto_bot",
      state: connectionState === "open" ? "open" : "connecting",
    },
  });
});

// 2. Fetch QR Code or Status
app.get("/instance/connect/:instance?", (req, res) => {
  if (connectionState === "open") {
    return res.json({ state: "open", message: "Already connected" });
  }
  if (!currentQrBase64) {
    return res.json({ state: "connecting", message: "QR generating, please refresh in 3s" });
  }
  res.json({
    state: "connecting",
    base64: currentQrBase64,
  });
});

// 3. Send Text Message (Group, Channel/Newsletter @newsletter, or 1-to-1)
// Baileys v6+ natively supports @newsletter JIDs via sock.sendMessage()
app.post("/message/sendText/:instance?", async (req, res) => {
  const { number, text } = req.body;

  if (!sock || connectionState !== "open") {
    return res.status(503).json({ error: "WhatsApp socket is not connected yet" });
  }

  if (!number || !text) {
    return res.status(400).json({ error: "Missing 'number' or 'text' in body" });
  }

  let jid = number.trim();

  // Normalize JID: pass through valid JIDs as-is, convert phone numbers
  if (!jid.includes("@")) {
    const cleanNum = jid.replace(/\D/g, "");
    jid = `${cleanNum}@s.whatsapp.net`;
  }

  const isChannel = jid.includes("@newsletter");

  try {
    const result = await sock.sendMessage(jid, { text });
    console.log(`[BAILEYS ${isChannel ? "📢 CHANNEL" : "📤"}] Dispatched to ${jid}`);
    return res.status(200).json({ status: "SUCCESS", messageId: result?.key?.id, jid });
  } catch (err) {
    console.error(`[BAILEYS ❌] Failed to send to ${jid}:`, err.message || err);
    return res.status(500).json({
      error: err.message,
      jid,
      hint: isChannel
        ? "Ensure the WhatsApp account owns/follows the channel. JID must be in 120363xxx@newsletter format."
        : undefined,
    });
  }
});

// 4. Dedicated Newsletter/Channel send endpoint (alias for sendText but with message.text body)
app.post("/newsletter/send/:instance?", async (req, res) => {
  const { number, message } = req.body;
  const text = (message && (message.text || message.body)) || req.body.text || "";

  if (!sock || connectionState !== "open") {
    return res.status(503).json({ error: "WhatsApp socket is not connected yet" });
  }

  if (!number || !text) {
    return res.status(400).json({ error: "Missing 'number' or 'message.text' in body" });
  }

  let jid = number.trim();
  if (!jid.includes("@newsletter")) {
    // Strip any existing domain and force @newsletter
    jid = jid.replace(/@[^@]*$/, "") + "@newsletter";
  }

  try {
    const result = await sock.sendMessage(jid, { text });
    console.log(`[BAILEYS 📢] Channel message dispatched to ${jid}`);
    return res.status(200).json({ status: "SUCCESS", messageId: result?.key?.id, jid });
  } catch (err) {
    console.error(`[BAILEYS ❌] Failed to send channel msg to ${jid}:`, err.message || err);
    return res.status(500).json({ error: err.message, jid });
  }
});

// 5. Fetch All Groups Joined
app.get("/group/fetchAllGroups/:instance?", async (req, res) => {
  if (!sock || connectionState !== "open") {
    return res.status(503).json({ error: "WhatsApp socket not connected" });
  }
  try {
    const groups = await sock.groupFetchAllParticipating();
    const groupList = Object.values(groups).map((g) => ({
      id: g.id,
      subject: g.subject,
      creation: g.creation,
      owner: g.owner,
      participantsCount: g.participants ? g.participants.length : 0,
    }));
    res.json(groupList);
  } catch (err) {
    console.error("[BAILEYS ❌] Error fetching groups:", err);
    res.status(500).json({ error: err.message });
  }
});

// 6. Find Chats
app.get("/chat/findChats/:instance?", async (req, res) => {
  if (!sock || connectionState !== "open") {
    return res.status(503).json({ error: "WhatsApp socket not connected" });
  }
  try {
    const groups = await sock.groupFetchAllParticipating();
    const chats = Object.values(groups).map((g) => ({
      id: g.id,
      name: g.subject,
      isGroup: true,
    }));
    res.json(chats);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// 7. Fetch Newsletters/Channels the account is following or owns
app.get("/newsletter/fetchAll/:instance?", async (req, res) => {
  if (!sock || connectionState !== "open") {
    return res.status(503).json({ error: "WhatsApp socket not connected" });
  }
  try {
    let newsletters = [];
    // Try different Baileys APIs for newsletter listing
    if (typeof sock.getNewsletterList === "function") {
      newsletters = await sock.getNewsletterList();
    }
    return res.json({ newsletters, count: newsletters.length });
  } catch (err) {
    console.error("[BAILEYS ❌] Error fetching newsletters:", err.message);
    return res.status(200).json({ newsletters: [], count: 0, error: err.message });
  }
});

// 8. Get Newsletter Metadata by Invite Code (resolves invite link -> full JID)
app.get("/newsletter/metadata/:instance?", async (req, res) => {
  if (!sock || connectionState !== "open") {
    return res.status(503).json({ error: "WhatsApp socket not connected" });
  }
  const { inviteCode, jid } = req.query;
  if (!inviteCode && !jid) {
    return res.status(400).json({ error: "Provide inviteCode or jid query parameter. Example: ?inviteCode=0029Vb9L75a8F2pLtsMuAn1p" });
  }
  try {
    let metadata;
    if (inviteCode && typeof sock.getNewsletterInfo === "function") {
      metadata = await sock.getNewsletterInfo(inviteCode);
    } else if (jid && typeof sock.getNewsletterMetadata === "function") {
      metadata = await sock.getNewsletterMetadata("invite", jid);
    } else {
      return res.status(500).json({ error: "getNewsletterInfo not available in this Baileys version" });
    }
    return res.json({ status: "SUCCESS", metadata });
  } catch (err) {
    console.error("[BAILEYS ❌] Newsletter metadata error:", err.message);
    return res.status(500).json({ error: err.message });
  }
});

app.listen(PORT, "0.0.0.0", () => {
  console.log(`[BAILEYS 🚀] Ultra-Lightweight WhatsApp Gateway running on port ${PORT}`);
  initBaileys();
});
