"use strict";

const fs = require("fs");
const path = require("path");

const baileys = require("@whiskeysockets/baileys");
const makeWASocket = baileys.default || baileys.makeWASocket || baileys;
const {
  Browsers,
  DisconnectReason,
  fetchLatestBaileysVersion,
  makeInMemoryStore,
  useMultiFileAuthState,
} = baileys;
const pino = require("pino");

const AUTH_DIR = process.env.WHATSAPP_AUTH_DIR || "auth_info_baileys";
const OUT_FILE = process.env.WHATSAPP_HISTORY_OUT || "whatsapp-history-export.json";
const WAIT_MS = Number(process.env.WHATSAPP_HISTORY_WAIT_MS || "90000");
const MIN_WAIT_MS = Number(process.env.WHATSAPP_HISTORY_MIN_WAIT_MS || String(WAIT_MS));
const SINCE_ISO = process.env.WHATSAPP_HISTORY_SINCE || "2026-06-25T00:00:00Z";
const SINCE_TS = Math.floor(new Date(SINCE_ISO).getTime() / 1000);

const logger = pino({ level: process.env.WHATSAPP_HISTORY_LOG_LEVEL || "silent" });
const store = makeInMemoryStore({ logger });

const records = new Map();
let lastActivity = Date.now();

function timestampSeconds(value) {
  if (!value) return null;
  if (typeof value === "number") return value;
  if (typeof value === "string") return Number(value);
  if (typeof value.toNumber === "function") return value.toNumber();
  if (typeof value.low === "number") return value.low;
  return null;
}

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

function textFromMessage(message) {
  if (!message) return "";
  if (message.conversation) return message.conversation;
  if (message.extendedTextMessage && message.extendedTextMessage.text) {
    return message.extendedTextMessage.text;
  }
  if (message.imageMessage && message.imageMessage.caption) {
    return message.imageMessage.caption;
  }
  if (message.videoMessage && message.videoMessage.caption) {
    return message.videoMessage.caption;
  }
  return "";
}

function displayNameFor(jid, msg) {
  const contact = store.contacts && store.contacts[jid];
  return (
    msg.pushName ||
    (contact && (contact.name || contact.notify || contact.verifiedName)) ||
    null
  );
}

function considerMessage(msg, source) {
  if (!msg || !msg.key || msg.key.fromMe) return;

  const jid = msg.key.remoteJid;
  if (!jid || jid.endsWith("@g.us") || jid === "status@broadcast") return;

  const phone = phoneFromJid(jid);
  if (!phone) return;

  const text = textFromMessage(msg.message);
  if (!text) return;

  const ts = timestampSeconds(msg.messageTimestamp);
  if (!ts || ts < SINCE_TS) return;

  const messageId = msg.key.id || `${jid}:${ts}:${text.slice(0, 24)}`;
  const key = `${jid}:${messageId}`;
  if (records.has(key)) return;

  records.set(key, {
    jid,
    phone,
    sender_name: displayNameFor(jid, msg),
    message: text,
    timestamp: ts,
    timestamp_iso: new Date(ts * 1000).toISOString(),
    message_id: messageId,
    source,
  });
  lastActivity = Date.now();
}

async function main() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();

  const sock = makeWASocket({
    version,
    auth: state,
    logger,
    browser: Browsers.macOS("Desktop"),
    printQRInTerminal: false,
    syncFullHistory: true,
  });

  store.bind(sock.ev);
  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", (update) => {
    const status = update.connection || (update.qr ? "qr" : "update");
    console.error(`[history] connection=${status}`);
    if (update.connection === "open") {
      lastActivity = Date.now();
    }
  });

  sock.ev.on("messaging-history.set", ({ messages }) => {
    for (const msg of messages || []) {
      considerMessage(msg, "messaging-history.set");
    }
    console.error(`[history] batch messages=${(messages || []).length} captured=${records.size}`);
  });

  sock.ev.on("messages.upsert", ({ messages, type }) => {
    for (const msg of messages || []) {
      considerMessage(msg, `messages.upsert:${type}`);
    }
  });

  await new Promise((resolve) => {
    const startedAt = Date.now();
    const interval = setInterval(() => {
      const elapsed = Date.now() - startedAt;
      const idle = Date.now() - lastActivity;
      if (elapsed >= WAIT_MS || (elapsed > MIN_WAIT_MS && idle > 10000)) {
        clearInterval(interval);
        resolve();
      }
    }, 1000);
  });

  try {
    sock.end(undefined);
  } catch (_err) {
    // Best-effort shutdown; exporter is a one-off process.
  }

  const messages = Array.from(records.values()).sort((a, b) => a.timestamp - b.timestamp);
  const payload = {
    exported_at: new Date().toISOString(),
    since: SINCE_ISO,
    message_count: messages.length,
    messages,
  };

  fs.writeFileSync(path.resolve(OUT_FILE), JSON.stringify(payload, null, 2));
  console.log(JSON.stringify({
    output: path.resolve(OUT_FILE),
    since: SINCE_ISO,
    message_count: messages.length,
    unique_contacts: new Set(messages.map((m) => m.phone)).size,
  }));

  const code = DisconnectReason.loggedOut ? 0 : 0;
  process.exit(code);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
