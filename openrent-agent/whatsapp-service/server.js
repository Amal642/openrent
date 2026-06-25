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
const fs = require("fs");

const FASTAPI_URL = "http://localhost:8000/api/whatsapp/incoming";
const PORT = 3001;
const CONTACTS_CACHE = "./contacts_cache.json";

const logger = pino({ level: "warn" });

let sock = null;

// Persistent contact maps — survive restarts
const lidToPhone = {};
const nameToPhone = {};

// Load persisted maps from previous sessions
try {
  if (fs.existsSync(CONTACTS_CACHE)) {
    var cached = JSON.parse(fs.readFileSync(CONTACTS_CACHE, "utf8"));
    Object.assign(lidToPhone, cached.lidToPhone || {});
    Object.assign(nameToPhone, cached.nameToPhone || {});
    console.log("[whatsapp-service] Loaded cache: " + Object.keys(lidToPhone).length + " lid→phone, " + Object.keys(nameToPhone).length + " name→phone mappings");
  }
} catch(e) {
  console.log("[whatsapp-service] Could not load contacts cache: " + e.message);
}

function saveCache() {
  try {
    fs.writeFileSync(CONTACTS_CACHE, JSON.stringify({lidToPhone: lidToPhone, nameToPhone: nameToPhone}));
  } catch(e) {}
}

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

  // Pending @lid live messages waiting for contacts.upsert to fire
  const pendingLids = {};

  // Levenshtein-based similarity — handles "Mohammed" vs "Mohamed" (edit dist = 1)
  function editDist(a, b) {
    var m = a.length, n = b.length;
    if (!m) return n;
    if (!n) return m;
    var prev = [], curr = [];
    for (var j = 0; j <= n; j++) prev[j] = j;
    for (var i = 1; i <= m; i++) {
      curr[0] = i;
      for (var j = 1; j <= n; j++) {
        curr[j] = a[i-1] === b[j-1] ? prev[j-1] : 1 + Math.min(prev[j], curr[j-1], prev[j-1]);
      }
      prev = curr.slice();
    }
    return prev[n];
  }

  function namesSimilar(a, b) {
    if (!a || !b) return false;
    if (a === b) return true;
    if (a.includes(b) || b.includes(a)) return true;
    var maxLen = Math.max(a.length, b.length);
    return maxLen > 0 && (1 - editDist(a, b) / maxLen) >= 0.80;
  }

  function findPhoneByName(name) {
    if (!name) return null;
    var key = name.toLowerCase().replace(/\s+/g, "");
    if (nameToPhone[key]) return nameToPhone[key];
    for (var stored in nameToPhone) {
      if (namesSimilar(stored, key)) return nameToPhone[stored];
    }
    return null;
  }

  function processContactList(contacts) {
    for (var i = 0; i < contacts.length; i++) {
      var contact = contacts[i];
      console.log("[DBG contact] id=" + contact.id + " lid=" + contact.lid + " name=" + contact.name + " notify=" + contact.notify);
      if (!contact.id || !contact.id.endsWith("@s.whatsapp.net")) continue;
      var realPhone = contact.id.replace("@s.whatsapp.net", "");

      // Try all name fields the contact might use
      var names = [contact.name, contact.notify, contact.verifiedName].filter(Boolean);
      for (var ni = 0; ni < names.length; ni++) {
        nameToPhone[names[ni].toLowerCase().replace(/\s+/g, "")] = realPhone;
      }
      console.log("[DBG contact] stored phone=" + realPhone + " under names=" + JSON.stringify(names));

      if (contact.lid) {
        lidToPhone[contact.lid.replace("@lid", "")] = realPhone;
      }

      saveCache();

      var contactName = (contact.name || contact.notify || "").toLowerCase().replace(/\s+/g, "");
      for (var pendingLid in pendingLids) {
        var pending = pendingLids[pendingLid];
        var pendingName = (pending.pushName || "").toLowerCase().replace(/\s+/g, "");
        var nameMatch = namesSimilar(contactName, pendingName);
        var onlyOne = Object.keys(pendingLids).length === 1;
        console.log("[DBG pending] lid=" + pendingLid + " contactName=" + contactName + " pendingName=" + pendingName + " nameMatch=" + nameMatch + " onlyOne=" + onlyOne);
        if (nameMatch || onlyOne) {
          lidToPhone[pendingLid] = realPhone;
          console.log("[whatsapp-service] lid resolved: " + pendingLid + " → " + realPhone);
          pending.resolve(realPhone);
          delete pendingLids[pendingLid];
          break;
        }
      }
    }
  }

  sock.ev.on("contacts.upsert", function(c) { console.log("[DBG] contacts.upsert count=" + c.length); processContactList(c); });
  sock.ev.on("contacts.update", function(c) { console.log("[DBG] contacts.update count=" + c.length); processContactList(c); });
  sock.ev.on("messaging-history.set", function(data) {
    var c = data.contacts || [];
    console.log("[DBG] messaging-history.set contacts=" + c.length);
    processContactList(c);
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
        var pushNameRaw = msg.pushName || null;

        console.log("[DBG @lid] lid=" + lidKey + " pushName=" + pushNameRaw + " nameToPhone keys=" + JSON.stringify(Object.keys(nameToPhone)));

        if (lidToPhone[lidKey]) {
          phone = lidToPhone[lidKey];
          console.log("[DBG @lid] resolved from lidToPhone cache: " + phone);
        } else if (pushNameRaw) {
          var resolvedByName = findPhoneByName(pushNameRaw);
          console.log("[DBG @lid] findPhoneByName(" + pushNameRaw + ") = " + resolvedByName);
          if (resolvedByName) {
            phone = resolvedByName;
            lidToPhone[lidKey] = phone;
            console.log("[whatsapp-service] @lid resolved via name: " + lidKey + " → " + phone);
          }
        }

        if (!phone) {
          console.log("[DBG @lid] entering 3s wait, pendingLids=" + JSON.stringify(Object.keys(pendingLids)));
          phone = await new Promise(function(resolve) {
            pendingLids[lidKey] = {pushName: pushNameRaw, resolve: resolve};
            setTimeout(function() {
              if (pendingLids[lidKey]) {
                delete pendingLids[lidKey];
                resolve(null);
              }
            }, 3000);
          });
          console.log("[DBG @lid] after 3s wait result=" + phone);
        }

        if (!phone) {
          console.log("[whatsapp-service] @lid could not resolve real phone, skipping: " + jid);
          continue;
        }
        console.log("[whatsapp-service] @lid final phone: " + phone);
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
