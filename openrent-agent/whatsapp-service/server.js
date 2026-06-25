"use strict";

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

const baileys = require("@whiskeysockets/baileys");
const makeWASocket = baileys.default || baileys.makeWASocket || baileys;
const { useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion } = baileys;

const qrcode = require("qrcode-terminal");
const axios = require("axios");
const express = require("express");
const pino = require("pino");

const FASTAPI_URL = "http://localhost:8000/api/whatsapp/incoming";
const PORT = 3001;

const logger = pino({ level: "warn" });

let sock = null;

// Maps @lid identifier → real phone number, populated via contacts.upsert
const lidToPhone = {};

async function connectToWhatsApp() {
  const { state, saveCreds } = await useMultiFileAuthState("auth_info_baileys");
  const { version } = await fetchLatestBaileysVersion();

  console.log("[whatsapp-service] Connecting using Baileys v" + version.join("."));
  console.log("[whatsapp-service] makeWASocket type:", typeof makeWASocket);

  sock = makeWASocket({
    version,
    auth: state,
    logger,
    printQRInTerminal: false,
    browser: ["Land Royal", "Chrome", "1.0.0"],
  });

  sock.ev.on("connection.update", async function(update) {
    var connection = update.connection;
    var lastDisconnect = update.lastDisconnect;
    var qr = update.qr;

    if (qr) {
      console.log("\n[whatsapp-service] Scan this QR code with WhatsApp:\n");
      qrcode.generate(qr, { small: true });
    }

    if (connection === "close") {
      var statusCode;
      if (lastDisconnect && lastDisconnect.error && lastDisconnect.error.output) {
        statusCode = lastDisconnect.error.output.statusCode;
      }
      var shouldReconnect = statusCode !== DisconnectReason.loggedOut;
      console.log("[whatsapp-service] Connection closed (" + statusCode + "). Reconnecting: " + shouldReconnect);
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

  sock.ev.on("creds.update", saveCreds);

  // Pending @lid messages waiting for contacts.upsert to fire with the real phone.
  // Key: lid string, Value: {pushName, resolve}
  const pendingLids = {};

  // When contacts.upsert fires, resolve any waiting @lid messages by name + timing.
  sock.ev.on("contacts.upsert", function(contacts) {
    for (var i = 0; i < contacts.length; i++) {
      var contact = contacts[i];
      if (!contact.id || !contact.id.endsWith("@s.whatsapp.net")) continue;
      var realPhone = contact.id.replace("@s.whatsapp.net", "");
      var contactName = (contact.name || "").toLowerCase().replace(/\s+/g, "");

      // Try to match against any pending @lid
      for (var pendingLid in pendingLids) {
        var pending = pendingLids[pendingLid];
        var pendingName = (pending.pushName || "").toLowerCase().replace(/\s+/g, "");
        // Match if names are similar OR if only one lid is pending (timing-based)
        var nameMatch = pendingName && contactName && (
          contactName === pendingName ||
          contactName.includes(pendingName) ||
          pendingName.includes(contactName)
        );
        var onlyOnePending = Object.keys(pendingLids).length === 1;

        if (nameMatch || onlyOnePending) {
          lidToPhone[pendingLid] = realPhone;
          console.log("[whatsapp-service] resolved lid→phone: " + pendingLid + " → " + realPhone);
          pending.resolve(realPhone);
          delete pendingLids[pendingLid];
          break;
        }
      }
    }
  });

  sock.ev.on("messaging-history.set", function(data) {
    var contacts = data.contacts || [];
    for (var i = 0; i < contacts.length; i++) {
      var contact = contacts[i];
      if (contact.lid && contact.id && contact.id.endsWith("@s.whatsapp.net")) {
        var lid = contact.lid.replace("@lid", "");
        lidToPhone[lid] = contact.id.replace("@s.whatsapp.net", "");
      }
    }
  });

  sock.ev.on("messages.upsert", async function(event) {
    var messages = event.messages;
    var type = event.type;

    // "notify" = live messages, "append" = history sync on connect
    if (type !== "notify" && type !== "append") return;

    for (var i = 0; i < messages.length; i++) {
      var msg = messages[i];

      if (msg.key.fromMe) continue;

      var jid = msg.key.remoteJid;
      if (!jid) continue;

      if (jid.endsWith("@g.us")) continue;

      var phone;
      if (jid.endsWith("@s.whatsapp.net")) {
        phone = jid.replace("@s.whatsapp.net", "");
      } else if (jid.endsWith("@lid")) {
        var lidKey = jid.replace("@lid", "");
        if (lidToPhone[lidKey]) {
          phone = lidToPhone[lidKey];
        } else {
          // Wait up to 3s for contacts.upsert to fire with the real phone
          var senderNameForLid = msg.pushName || null;
          phone = await new Promise(function(resolve) {
            pendingLids[lidKey] = {pushName: senderNameForLid, resolve: resolve};
            setTimeout(function() {
              if (pendingLids[lidKey]) {
                delete pendingLids[lidKey];
                resolve(null); // could not resolve
              }
            }, 3000);
          });
          if (!phone) {
            console.log("[whatsapp-service] @lid could not resolve real phone, skipping: " + jid);
            continue;
          }
          console.log("[whatsapp-service] @lid resolved to real phone: " + phone);
        }
      } else {
        continue;
      }

      var text = "";
      if (msg.message) {
        if (msg.message.conversation) {
          text = msg.message.conversation;
        } else if (msg.message.extendedTextMessage && msg.message.extendedTextMessage.text) {
          text = msg.message.extendedTextMessage.text;
        } else if (msg.message.imageMessage && msg.message.imageMessage.caption) {
          text = msg.message.imageMessage.caption;
        }
      }

      if (!text) continue;

      var timestamp = msg.messageTimestamp
        ? Number(msg.messageTimestamp)
        : Math.floor(Date.now() / 1000);

      // pushName is the sender's WhatsApp display name — use it directly
      var senderName = msg.pushName || null;

      console.log("[whatsapp-service] Incoming from " + phone + (senderName ? " (" + senderName + ")" : "") + ": " + text.substring(0, 80));

      try {
        await axios.post(
          FASTAPI_URL,
          { phone: phone, message: text, timestamp: timestamp, sender_name: senderName },
          { timeout: 10000 }
        );
      } catch (err) {
        console.error("[whatsapp-service] Failed to forward to FastAPI: " + err.message);
      }
    }
  });
}

// ── Express HTTP server ───────────────────────────────────────────────────────

const app = express();
app.use(express.json());

app.post("/send", async function(req, res) {
  var phone = req.body.phone;
  var message = req.body.message;

  if (!phone || !message) {
    return res.status(400).json({ error: "phone and message are required" });
  }

  if (!sock) {
    return res.status(503).json({ error: "WhatsApp not connected" });
  }

  try {
    var jid = phone.includes("@") ? phone : phone + "@s.whatsapp.net";
    await sock.sendMessage(jid, { text: message });
    console.log("[whatsapp-service] Sent to " + phone + ": " + message.substring(0, 80));
    return res.json({ status: "sent" });
  } catch (err) {
    console.error("[whatsapp-service] Send failed: " + err.message);
    return res.status(500).json({ error: err.message });
  }
});

app.get("/health", function(_req, res) {
  res.json({
    status: sock ? "connected" : "disconnected",
    timestamp: new Date().toISOString(),
  });
});

app.listen(PORT, function() {
  console.log("[whatsapp-service] HTTP server listening on port " + PORT);
});

// ── Start ─────────────────────────────────────────────────────────────────────
connectToWhatsApp().catch(function(err) {
  console.error("[whatsapp-service] Fatal error:", err);
  process.exit(1);
});
