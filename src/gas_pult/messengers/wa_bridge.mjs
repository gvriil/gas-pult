// WhatsApp — связанное устройство через Baileys (неофициальный способ, см. экран выбора в панели).
// Запускает мост пульта (wa.py): node wa_bridge.mjs <папка входа>. Обмен — строки JSON:
//   stdout: {"ev":"qr","qr":…} | {"ev":"open","who":…} | {"ev":"msg",…} | {"ev":"sent","rid":…} | {"ev":"close",…}
//   stdin:  {"op":"send","to":…,"text":…,"rid":…} — только из подтверждённого черновика (проверяет мост на Python).
// Файлы входа — 0600 (umask), в папке данных человека; в stdout ключей нет.
import { createInterface } from "node:readline";
process.umask(0o077);
const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, Browsers } = await import("@whiskeysockets/baileys");
const { default: pino } = await import("pino");

const dir = process.argv[2];
const out = (x) => process.stdout.write(JSON.stringify(x) + "\n");
const text = (m) => m?.conversation || m?.extendedTextMessage?.text || m?.imageMessage?.caption || m?.videoMessage?.caption || "";
let sock = null;

async function connect() {
  const { state, saveCreds } = await useMultiFileAuthState(dir);
  sock = makeWASocket({ auth: state, logger: pino({ level: "silent" }), browser: Browsers.ubuntu("gas-pult"),
    markOnlineOnConnect: false, syncFullHistory: false, shouldSyncHistoryMessage: () => false });
  sock.ev.on("creds.update", saveCreds);
  sock.ev.on("connection.update", (u) => {
    if (u.qr) out({ ev: "qr", qr: u.qr });
    if (u.connection === "open") out({ ev: "open", who: String(sock.user?.id || "").split(":")[0].split("@")[0] });
    if (u.connection === "close") {
      const code = u.lastDisconnect?.error?.output?.statusCode;
      if (code === DisconnectReason.loggedOut) { out({ ev: "close", reason: "logged_out" }); process.exit(0); }
      if (code === DisconnectReason.restartRequired) return setTimeout(connect, 0);   // после скана — переподключиться
      out({ ev: "close", reason: String(code || "") });
      if (!state.creds.me) process.exit(0);           // QR так и не отсканировали — не крутить новые QR без человека
      setTimeout(connect, 3000);
    }
  });
  sock.ev.on("messages.upsert", ({ messages, type }) => {
    if (type !== "notify") return;
    for (const m of messages) {
      const t = text(m.message);
      if (m.key.fromMe || !t || m.key.remoteJid === "status@broadcast") continue;
      out({ ev: "msg", chat: m.key.remoteJid, name: m.pushName || "", from: m.pushName || "", ts: Number(m.messageTimestamp) || Date.now() / 1000, text: t.slice(0, 2000) });
    }
  });
}

createInterface({ input: process.stdin }).on("line", async (line) => {
  let r; try { r = JSON.parse(line); } catch { return; }
  if (r.op !== "send") return;
  try { await sock.sendMessage(r.to, { text: String(r.text) }); out({ ev: "sent", rid: r.rid }); }
  catch (e) { out({ ev: "sent", rid: r.rid, error: String(e?.message || e).slice(0, 300) }); }
}).on("close", () => process.exit(0));                // мост на Python закрылся — выходим и мы
await connect();
