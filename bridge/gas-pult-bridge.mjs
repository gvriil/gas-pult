#!/usr/bin/env node
// Мост пульта к браузеру пользователя (Mac, Windows, Linux) — один файл, Node 22+, без зависимостей.
//
//   node gas-pult-bridge.mjs pair https://<адрес панели> <КОД>   — привязать компьютер (код — панель → Настройки → Компьютеры)
//   node gas-pult-bridge.mjs                                      — работать: держит связь с пультом
//   node gas-pult-bridge.mjs allow <домен>                        — разрешить сайт из запретного списка (банк, госуслуги)
//   node gas-pult-bridge.mjs status                               — что настроено
//
// Мост сам подключается к пульту (исходящий WebSocket, wss) и локально запускает Playwright MCP в режиме
// --extension (Microsoft, Apache-2.0): управление уже открытым Chrome/Edge, где вы вошли в свои сервисы. Нужно
// расширение «Playwright Extension» в браузере. Команды агентов пульта приходят сюда, ответы уходят обратно.
// «Сохранить на компьютер» — файл в папку Загрузки (save_to_computer). Банки и госуслуги — выключены, пока вы сами их
// не разрешите командой allow (прочитав правила сервиса: автоматизация там может быть запрещена).
// Настройки — ~/.gas-pult-bridge.json (только для вас: 0600).

import { spawn, execFile } from "node:child_process";
import { createInterface } from "node:readline";
import { existsSync, mkdirSync, readFileSync, writeFileSync, chmodSync, readdirSync, statSync, rmSync, realpathSync } from "node:fs";
import { homedir, hostname, platform, tmpdir } from "node:os";
import { join, basename } from "node:path";

const PW_MCP = "@playwright/mcp@0.0.85";                 // выпуск 09.11.2026 (старше 14 дней — правило портфеля)
const CONF = join(homedir(), ".gas-pult-bridge.json");
const BLOCKED = ["gosuslugi.ru", "nalog.gov.ru", "nalog.ru", "pfr.gov.ru", "sfr.gov.ru", "mos.ru", "sberbank.ru", "sber.ru",
  "tbank.ru", "tinkoff.ru", "vtb.ru", "alfabank.ru", "raiffeisen.ru", "gazprombank.ru", "psbank.ru", "open.ru", "rshb.ru",
  "pochtabank.ru", "sovcombank.ru", "mkb.ru", "paypal.com", "revolut.com", "wise.com", "bunq.com", "n26.com"];
const SAVE_TOOL = {
  name: "save_to_computer",
  description: "Сохранить файл на компьютер пользователя в папку Загрузки (или подпапку). Текст — content, двоичное — " +
    "content_base64. Существующий файл не перезаписывается — к имени добавляется номер.",
  inputSchema: { type: "object", properties: { name: { type: "string" }, content: { type: "string" },
    content_base64: { type: "string" }, folder: { type: "string", description: "подпапка в Загрузках" } }, required: ["name"] },
};

// Уровень 1 «руки на компьютере» (владелец 17.11): белый список, без свободной командной строки. Каждое действие —
// в журнал устройства на сервере пульта (как и всё, что идёт через мост).
const MAC_TOOLS = [
  { name: "list_dir", description: "Список файлов и папок в папке пользователя (внутри домашней папки). Скрытые — нет.",
    inputSchema: { type: "object", properties: { path: { type: "string", description: "путь от домашней папки, например Documents" } } } },
  { name: "open_app", description: "Открыть программу на Маке по имени (из /Applications или /System/Applications), например Safari, Notes.",
    inputSchema: { type: "object", properties: { name: { type: "string" } }, required: ["name"] } },
  { name: "screenshot", description: "Снимок экрана компьютера (JPEG, длинная сторона до 1600 px). На macOS нужно разрешение «Запись экрана» для Терминала.",
    inputSchema: { type: "object", properties: {} } },
];
const exec = (cmd, args) => new Promise((ok, no) => execFile(cmd, args, { timeout: 20000 }, (e, out) => (e ? no(e) : ok(out))));

export function listDir(args, home = homedir()) {
  const want = String(args.path || "").replace(/^~\/?/, "");
  const real = realpathSync(join(home, want)), base = realpathSync(home);
  if (real !== base && !real.startsWith(base + "/")) throw new Error("только папки внутри домашней");
  const items = readdirSync(real).filter((n) => !n.startsWith(".")).slice(0, 300).map((n) => {
    let st; try { st = statSync(join(real, n)); } catch { return null; }
    return st.isDirectory() ? `${n}/` : `${n} (${st.size} байт)`;
  }).filter(Boolean);
  return `${want || "~"}:\n` + (items.join("\n") || "(пусто)");
}

export async function openApp(args, os = platform()) {
  if (os !== "darwin") throw new Error("открыть программу — пока только на macOS");
  const name = String(args.name || "").replace(/\.app$/i, "");
  if (!/^[\p{L}\p{N} ._-]{1,60}$/u.test(name)) throw new Error("имя программы — буквы, цифры, пробел, точка, дефис");
  const app = ["/Applications", "/System/Applications", "/System/Applications/Utilities", "/Applications/Utilities"]
    .map((d) => `${d}/${name}.app`).find((p) => existsSync(p));
  if (!app) throw new Error(`программы «${name}» нет в /Applications`);
  await exec("open", ["-a", app]);
  return `Открыто: ${name}`;
}

export async function screenshot(os = platform()) {
  if (os !== "darwin") throw new Error("снимок экрана — пока только на macOS");
  const f = join(tmpdir(), `gp-shot-${Date.now()}.jpg`);
  try {
    await exec("screencapture", ["-x", "-t", "jpg", f]);
    await exec("sips", ["-Z", "1600", f]);
    return readFileSync(f).toString("base64");
  } finally { try { rmSync(f); } catch {} }
}

const load = () => { try { return JSON.parse(readFileSync(CONF, "utf8")); } catch { return {}; } };
const save = (c) => { writeFileSync(CONF, JSON.stringify(c, null, 1)); try { chmodSync(CONF, 0o600); } catch {} };
const log = (...a) => console.error(new Date().toISOString().slice(11, 19), ...a);

export function blockedHost(url, allowed = []) {
  const m = /^[a-z][a-z0-9+.-]*:\/\/([^/:?#]+)/.exec(String(url || "").trim().toLowerCase());
  const host = m ? m[1] : "";
  return BLOCKED.find((d) => (host === d || host.endsWith("." + d)) && !allowed.includes(d)) || "";
}

export function saveToComputer(args, root = join(homedir(), "Downloads")) {
  const sub = String(args.folder || "").replace(/[\\/]+/g, "_").replace(/^\.+/, "");
  const dir = sub ? join(root, sub) : root;
  mkdirSync(dir, { recursive: true });
  let name = basename(String(args.name || "файл")).replace(/^\.+/, "_") || "файл";
  const [stem, ext] = /^(.*?)(\.[^.]*)?$/.exec(name).slice(1);
  for (let k = 2; existsSync(join(dir, name)); k++) name = `${stem}-${k}${ext || ""}`;
  const data = args.content_base64 ? Buffer.from(args.content_base64, "base64") : Buffer.from(String(args.content ?? ""), "utf8");
  writeFileSync(join(dir, name), data);
  return join(dir, name);
}

async function pair(url, code) {
  const r = await fetch(url.replace(/\/$/, "") + "/api/bridge/claim", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, name: hostname(), os: platform() }) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || "ошибка " + r.status);
  save({ ...load(), url: url.replace(/\/$/, ""), token: d.token, id: d.id });
  console.log(`Готово: компьютер «${hostname()}» привязан к пульту. Запустите: node ${basename(process.argv[1])}`);
}

function run() {
  const conf = load();
  if (!conf.token) { console.error("Сначала привяжите компьютер: node gas-pult-bridge.mjs pair <адрес панели> <КОД>"); process.exit(2); }
  const allowed = conf.allowed || [];
  let mcp = null, ws = null, pause = 1000;
  const startMcp = () => {                              // Playwright MCP — дочерний процесс, stdio JSON-RPC построчно
    const cmd = process.env.GAS_PULT_BRIDGE_MCP || `npx -y ${PW_MCP} --extension`;
    mcp = spawn(cmd, { shell: true, stdio: ["pipe", "pipe", "inherit"] });
    createInterface({ input: mcp.stdout }).on("line", (line) => {
      let m; try { m = JSON.parse(line); } catch { return; }
      if (m?.result?.tools && Array.isArray(m.result.tools)) m.result.tools.push(SAVE_TOOL, ...MAC_TOOLS);   // ответ на tools/list
      if (ws?.readyState === 1) ws.send(JSON.stringify(m));
    });
    mcp.on("exit", (c) => { log("Playwright MCP завершился:", c); mcp = null; });
  };
  const reply = (id, result, error) => ws?.readyState === 1 && ws.send(JSON.stringify({ jsonrpc: "2.0", id, ...(error ? { error } : { result }) }));
  const connect = () => {
    const url = conf.url.replace(/^http/, "ws") + "/api/bridge/ws";
    ws = new WebSocket(url, ["gpb-" + conf.token]);
    ws.onopen = () => { pause = 1000; log("связь с пультом есть"); ws.send(JSON.stringify({ bridge: { allowed, os: platform() } })); };
    ws.onmessage = (e) => {
      let m; try { m = JSON.parse(String(e.data)); } catch { return; }
      const p = m.params || {};
      if (m.method === "tools/call" && p.name === "save_to_computer") {
        try { return reply(m.id, { content: [{ type: "text", text: "Сохранено: " + saveToComputer(p.arguments || {}) }] }); }
        catch (err) { return reply(m.id, null, { code: -32010, message: "не сохранил: " + err.message }); }
      }
      if (m.method === "tools/call" && MAC_TOOLS.some((t) => t.name === p.name)) {
        const a = p.arguments || {}, fail = (err) => reply(m.id, null, { code: -32011, message: err.message });
        if (p.name === "list_dir") { try { return reply(m.id, { content: [{ type: "text", text: listDir(a) }] }); } catch (err) { return fail(err); } }
        if (p.name === "open_app") return openApp(a).then((t) => reply(m.id, { content: [{ type: "text", text: t }] }), fail);
        return screenshot().then((b64) => reply(m.id, { content: [{ type: "image", data: b64, mimeType: "image/jpeg" }] }), fail);
      }
      if (m.method === "tools/call" && String(p.name || "").endsWith("navigate")) {
        const d = blockedHost((p.arguments || {}).url, allowed);
        if (d) return reply(m.id, null, { code: -32001, message: `сайт ${d} выключен на этом компьютере (банк или госуслуги)` });
      }
      if (!mcp) startMcp();
      mcp.stdin.write(JSON.stringify(m) + "\n");
    };
    ws.onclose = (e) => {
      if (e.code === 1008 || e.code === 4001) { log("пульт отклонил устройство — привяжите заново"); process.exit(3); }
      log(`нет связи (${e.code}) — повтор через ${pause / 1000} с`);
      setTimeout(connect, pause); pause = Math.min(60000, pause * 2);
    };
    ws.onerror = () => {};
  };
  startMcp();
  connect();
}

const [cmd, a1, a2] = process.argv.slice(2);
if (cmd === "pair") pair(a1, a2).catch((e) => { console.error("Не привязал:", e.message); process.exit(1); });
else if (cmd === "allow") {
  const c = load(), d = String(a1 || "").toLowerCase();
  if (!BLOCKED.includes(d)) { console.error("Этого сайта нет в запретном списке — разрешать не нужно."); process.exit(0); }
  console.log(`Внимание: правила ${d} могут запрещать автоматизацию. Прочитайте условия сервиса. Разрешаю ${d}.`);
  save({ ...c, allowed: [...new Set([...(c.allowed || []), d])] });
} else if (cmd === "status") {
  const c = load(); console.log({ url: c.url, id: c.id, allowed: c.allowed || [], token: c.token ? "есть" : "нет" });
} else if (!cmd) run();
else { console.error("Команды: pair <адрес> <КОД> | allow <домен> | status | без аргументов — работать"); process.exit(2); }
