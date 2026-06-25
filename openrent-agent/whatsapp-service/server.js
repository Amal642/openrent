/**
 * Baileys WhatsApp bridge for OpenRent phone acquisition.
 *
 * - Connects to WhatsApp via Baileys (multi-device)
 * - Saves auth state in ./auth_info_baileys/
 * - Prints QR code to terminal on first run
 * - Forwards all incoming messages to FastAPI at http://localhost:8000/api/whatsapp/incoming
 * - Exposes POST /send for FastAPI to trigger outbound messages
 *
 * Usage:
 *   npm install
 *   node server.js
 */

import makeWASocket, {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} from "@whiskeysockets/baileys";
import qrcode from "qrcode-terminal";
import axios from "axios";
import express from "express";
import pino from "pino";

const FASTAPI_URL = "http://localhost:8000/api/whatsapp/incoming";
const PORT = 3001;

// Suppress verbose Baileys logs — only show warn+ from baileys internals
const logger = pino({ level: "warn" });

let sock = null;

async function connectToWhatsApp() {
  const { state, saveCreds } = await useMultiFileAuthState("auth_info_baileys");
  const { version } = await fetchLatestBaileysVersion();

  console.log(`[whatsapp-service] Connecting using Baileys v${version.join(".")}`);

  sock = makeWASocket({
    version,
    auth: state,
    logger,
    printQRInTerminal: false, // We handle QR manually below
    browser: ["Land Royal", "Chrome", "1.0.0"],
  });

  // QR code — only shown when not yet authenticated
  sock.ev.on("connection.update", async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      console.log("\n[whatsapp-service] Scan this QR code with WhatsApp:\n");
      qrcode.generate(qr, { small: true });
    }

    if (connection === "close") {
      const statusCode = lastDisconnect?.error?.output?.statusCode;
      const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
      console.log(
        `[whatsapp-service] Connection closed (${statusCode}). Reconnecting: ${shouldReconnect}`
      );
      if (shouldReconnect) {
        setTimeout(connectToWhatsApp, 3000);
      } else {
        console.log("[whatsapp-service] Logged out. Delete auth_info_baileys/ and restart.");
      }
    }

    if (connection === "open") {
      console.log("[whatsapp-service] WhatsApp connected successfully.");
    }
  });

  // Save credentials whenever they update
  sock.ev.on("creds.update", saveCreds);

  // Forward incoming messages to FastAPI
  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify") return;

    for (const msg of messages) {
      // Skip messages we sent
      if (msg.key.fromMe) continue;

      const jid = msg.key.remoteJid;
      if (!jid) continue;

      // Skip group messages — only handle 1:1
      if (jid.endsWith("@g.us")) continue;

      // Extract phone number: strip @s.whatsapp.net suffix
      const phone = jid.replace("@s.whatsapp.net", "");

      // Extract message text
      const text =
        msg.message?.conversation ||
        msg.message?.extendedTextMessage?.text ||
        msg.message?.imageMessage?.caption ||
        "";

      if (!text) continue;

      const timestamp = msg.messageTimestamp
        ? Number(msg.messageTimestamp)
        : Math.floor(Date.now() / 1000);

      console.log(`[whatsapp-service] Incoming from ${phone}: ${text.substring(0, 80)}`);

      try {
        await axios.post(
          FASTAPI_URL,
          { phone, message: text, timestamp },
          { timeout: 10000 }
        );
      } catch (err) {
        console.error(
          `[whatsapp-service] Failed to forward message to FastAPI: ${err.message}`
        );
      }
    }
  });
}

// ── Express HTTP server for outbound sends ────────────────────────────────────

const app = express();
app.use(express.json());

app.post("/send", async (req, res) => {
  const { phone, message } = req.body;

  if (!phone || !message) {
    return res.status(400).json({ error: "phone and message are required" });
  }

  if (!sock) {
    return res.status(503).json({ error: "WhatsApp not connected" });
  }

  try {
    const jid = phone.includes("@") ? phone : `${phone}@s.whatsapp.net`;
    await sock.sendMessage(jid, { text: message });
    console.log(`[whatsapp-service] Sent to ${phone}: ${message.substring(0, 80)}`);
    return res.json({ status: "sent" });
  } catch (err) {
    console.error(`[whatsapp-service] Send failed: ${err.message}`);
    return res.status(500).json({ error: err.message });
  }
});

app.get("/health", (_req, res) => {
  res.json({
    status: sock ? "connected" : "disconnected",
    timestamp: new Date().toISOString(),
  });
});

app.listen(PORT, () => {
  console.log(`[whatsapp-service] HTTP server listening on port ${PORT}`);
});

// ── Start ─────────────────────────────────────────────────────────────────────
connectToWhatsApp().catch((err) => {
  console.error("[whatsapp-service] Fatal error:", err);
  process.exit(1);
});
