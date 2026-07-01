"use strict";

/**
 * Baileys WhatsApp bridge for OpenRent phone acquisition.
 *
 * Only processes messages from people who text this number.
 * No contact list syncing. Some WhatsApp accounts arrive as @lid
 * identifiers instead of @s.whatsapp.net phone JIDs (WhatsApp's phone-hiding
 * Linked-ID system). On Baileys v7 we recover the real phone number from the
 * message key (remoteJidAlt) and the on-device lidMapping store; only when
 * that fails do we fall back to forwarding lid:<id> so the CRM still records
 * the lead.
 *
 * Baileys v7 is ESM-only (package.json "type": "module"), so it is loaded via
 * a dynamic import() from this CommonJS module.
 */

// Baileys exports resolved at startup by loadBaileys().
let makeWASocket = null;
let useMultiFileAuthState = null;
let DisconnectReason = null;
let fetchLatestBaileysVersion = null;

async function loadBaileys() {
  // v7 ESM namespace: named exports sit on the namespace; default is makeWASocket.
  const baileys = await import("@whiskeysockets/baileys");
  makeWASocket = baileys.makeWASocket || baileys.default;
  useMultiFileAuthState = baileys.useMultiFileAuthState;
  DisconnectReason = baileys.DisconnectReason;
  fetchLatestBaileysVersion = baileys.fetchLatestBaileysVersion;
}

const qrcode = require("qrcode-terminal");
const axios = require("axios");
const express = require("express");
const pino = require("pino");

const FASTAPI_URL = "http://localhost:8000/api/whatsapp/incoming";
const RESOLVE_URL = "http://localhost:8000/api/whatsapp/resolve";
const LOG_URL = "http://localhost:8000/api/whatsapp/log";
const PORT = 3001;

function logToBackend(level, message) {
  axios.post(LOG_URL, { level: level, message: message }, { timeout: 5000 }).catch(function() {});
}

const logger = pino({ level: "warn" });

let sock = null;

function phoneFromJid(jid) {
  if (!jid) return null;
  if (jid.endsWith("@s.whatsapp.net")) {
    return jid.replace("@s.whatsapp.net", "");
  }
  if (jid.endsWith("@lid")) {
    return "lid:" + jid.replace("@lid", "");
  }
  return null;
}

function lidFromJid(jid) {
  if (!jid) return null;
  if (jid.endsWith("@lid")) {
    return jid.replace("@lid", "");
  }
  return null;
}

function jidFromPhone(phone) {
  if (phone.includes("@")) {
    return phone;
  }
  if (phone.startsWith("lid:")) {
    return phone.slice(4) + "@lid";
  }
  return phone + "@s.whatsapp.net";
}

function normalizeResolvedPhone(jidOrPhone) {
  if (!jidOrPhone) return null;
  if (jidOrPhone.endsWith && jidOrPhone.endsWith("@s.whatsapp.net")) {
    return jidOrPhone.replace("@s.whatsapp.net", "");
  }
  var digits = String(jidOrPhone).replace(/\D/g, "");
  return digits || null;
}

// Return bare phone digits from a phone JID (...@s.whatsapp.net) or raw PN, else null.
function digitsFromPn(jidOrPn) {
  if (!jidOrPn) return null;
  var value = String(jidOrPn);
  if (value.endsWith("@lid") || value.endsWith("@g.us")) return null;
  if (value.endsWith("@s.whatsapp.net")) {
    value = value.replace("@s.whatsapp.net", "");
  }
  var digits = value.replace(/\D/g, "");
  return digits || null;
}

// Best-effort recovery of the real phone number behind an @lid sender.
// 1. The PN often rides on the message key itself (remoteJidAlt for DMs).
// 2. Otherwise consult Baileys' on-device PN<->LID store.
// Returns bare phone digits or null when WhatsApp has not exposed the number.
async function resolvePhoneForLid(socket, lidJid, msgKey) {
  msgKey = msgKey || {};
  var fromKey = digitsFromPn(msgKey.remoteJidAlt) || digitsFromPn(msgKey.senderPn);
  if (fromKey) return fromKey;

  try {
    var store = socket && socket.signalRepository && socket.signalRepository.lidMapping;
    if (store && typeof store.getPNForLID === "function") {
      var pn = await store.getPNForLID(lidJid);
      var digits = digitsFromPn(pn);
      if (digits) return digits;
    }
  } catch (err) {
    console.error("[whatsapp-service] lidMapping.getPNForLID failed: " + err.message);
  }

  return null;
}

async function postLidResolution(lid, phone, jid) {
  var cleanLid = lid ? String(lid).replace("@lid", "").replace("lid:", "") : null;
  var cleanPhone = normalizeResolvedPhone(phone || jid);
  if (!cleanLid || !cleanPhone) return;

  try {
    await axios.post(
      RESOLVE_URL,
      { lid: cleanLid, phone: cleanPhone, jid: jid || null },
      { timeout: 10000 }
    );
    console.log("[whatsapp-service] Resolved lid:" + cleanLid + " -> +" + cleanPhone);
  } catch (err) {
    console.error("[whatsapp-service] Failed to resolve LID in FastAPI: " + err.message);
  }
}

async function connectToWhatsApp() {
  if (!makeWASocket) {
    await loadBaileys();
  }

  const { state, saveCreds } = await useMultiFileAuthState("auth_info_baileys");
  const { version } = await fetchLatestBaileysVersion();

  console.log("[whatsapp-service] Connecting using Baileys v" + version.join("."));

  sock = makeWASocket({
    version,
    auth: state,
    logger,
    browser: ["Land Royal", "Chrome", "1.0.0"],
  });

  sock.ev.on("connection.update", async function(update) {
    var connection = update.connection;
    var lastDisconnect = update.lastDisconnect;
    var qr = update.qr;

    if (qr) {
      console.log("\n[whatsapp-service] Scan this QR code with WhatsApp:\n");
      qrcode.generate(qr, { small: true });
      logToBackend("warn", "QR code generated — waiting for WhatsApp scan");
    }

    if (connection === "close") {
      var statusCode;
      if (lastDisconnect && lastDisconnect.error && lastDisconnect.error.output) {
        statusCode = lastDisconnect.error.output.statusCode;
      }
      var shouldReconnect = statusCode !== DisconnectReason.loggedOut;
      console.log("[whatsapp-service] Connection closed (" + statusCode + "). Reconnecting: " + shouldReconnect);
      if (shouldReconnect) {
        logToBackend("warn", "WhatsApp connection closed (code=" + statusCode + ") — reconnecting");
        setTimeout(connectToWhatsApp, 3000);
      } else {
        console.log("[whatsapp-service] Logged out. Delete auth_info_baileys/ and restart.");
        logToBackend("error", "WhatsApp logged out (401 device_removed) — delete auth_info_baileys/ and restart");
      }
    }

    if (connection === "open") {
      console.log("[whatsapp-service] WhatsApp connected successfully.");
      logToBackend("info", "WhatsApp connected successfully");
    }
  });

  sock.ev.on("creds.update", saveCreds);

  // v7: WhatsApp discovers a PN<->LID mapping after the fact. Payload shape is
  // still WIP upstream, so read every plausible field defensively.
  sock.ev.on("lid-mapping.update", async function(event) {
    var items = Array.isArray(event) ? event : [event];
    for (var i = 0; i < items.length; i++) {
      var item = items[i] || {};
      var lid = item.lid || item.lidJid || item.lidUser;
      var pn = item.pn || item.phoneNumber || item.jid || item.pnJid;
      await postLidResolution(lid, pn, pn);
    }
  });

  sock.ev.on("chats.phoneNumberShare", async function(event) {
    var items = Array.isArray(event) ? event : [event];
    for (var i = 0; i < items.length; i++) {
      var item = items[i] || {};
      await postLidResolution(item.lid || item.lidJid, item.jid || item.phoneNumber, item.jid);
    }
  });

  sock.ev.on("contacts.upsert", async function(contacts) {
    contacts = Array.isArray(contacts) ? contacts : [contacts];
    for (var i = 0; i < contacts.length; i++) {
      var contact = contacts[i] || {};
      if (contact.lid && contact.id && String(contact.id).endsWith("@s.whatsapp.net")) {
        await postLidResolution(contact.lid, contact.id, contact.id);
      }
    }
  });

  sock.ev.on("contacts.update", async function(contacts) {
    contacts = Array.isArray(contacts) ? contacts : [contacts];
    for (var i = 0; i < contacts.length; i++) {
      var contact = contacts[i] || {};
      if (contact.lid && contact.id && String(contact.id).endsWith("@s.whatsapp.net")) {
        await postLidResolution(contact.lid, contact.id, contact.id);
      }
    }
  });

  sock.ev.on("messages.upsert", async function(event) {
    var messages = event.messages;
    var type = event.type;

    // Only handle live incoming messages — ignore history replay
    if (type !== "notify") return;

    for (var i = 0; i < messages.length; i++) {
      var msg = messages[i];

      if (msg.key.fromMe) continue;

      var jid = msg.key.remoteJid;
      if (!jid) continue;

      // Skip groups
      if (jid.endsWith("@g.us")) continue;

      var phone = phoneFromJid(jid);
      if (!phone) {
        console.log("[whatsapp-service] Skipping non-phone JID: " + jid);
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

      var senderName = msg.pushName || null;
      var lid = lidFromJid(jid);
      var messageId = msg.key.id || null;

      // Phone-hidden @lid sender: try to recover the real number (key alt field
      // or the lidMapping store). On success, forward the real phone and merge
      // any earlier lid:<id> row via the /resolve endpoint.
      var resolvedPhone = null;
      if (lid) {
        resolvedPhone = await resolvePhoneForLid(sock, jid, msg.key);
        if (resolvedPhone) {
          phone = resolvedPhone;
        }
      }

      var displayPhone = phone.startsWith("lid:") ? phone : "+" + phone;
      var incomingDesc = "Incoming from " + displayPhone + (senderName ? " (" + senderName + ")" : "") + ": " + text.substring(0, 80);
      console.log("[whatsapp-service] " + incomingDesc);
      logToBackend("info", incomingDesc);

      if (lid && resolvedPhone) {
        postLidResolution(lid, resolvedPhone, jid);
      }

      try {
        await axios.post(
          FASTAPI_URL,
          {
            phone: phone,
            message: text,
            timestamp: timestamp,
            sender_name: senderName,
            jid: jid,
            lid: lid,
            message_id: messageId
          },
          { timeout: 10000 }
        );
      } catch (err) {
        console.error("[whatsapp-service] Failed to forward to FastAPI: " + err.message);
        logToBackend("error", "Failed to forward message to backend: " + err.message);
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
    var jid = jidFromPhone(phone);
    await sock.sendMessage(jid, { text: message });
    var sentDesc = "Sent to +" + phone + ": " + message.substring(0, 80);
    console.log("[whatsapp-service] " + sentDesc);
    logToBackend("info", sentDesc);
    return res.json({ status: "sent" });
  } catch (err) {
    console.error("[whatsapp-service] Send failed: " + err.message);
    logToBackend("error", "Send failed to +" + phone + ": " + err.message);
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

connectToWhatsApp().catch(function(err) {
  console.error("[whatsapp-service] Fatal error:", err);
  process.exit(1);
});
