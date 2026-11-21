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
// «Сохранить на компьютер» — файл в папку Загрузки (save_to_computer). Заметки, Напоминания, Календарь Мака — через
// osascript; новая заметка или напоминание — только после «Да» человека в пульте. Банки и госуслуги — выключены, пока вы сами их
// не разрешите командой allow (прочитав правила сервиса: автоматизация там может быть запрещена).
// Настройки — ~/.gas-pult-bridge.json (только для вас: 0600).

import { spawn, execFile } from "node:child_process";
import { createInterface } from "node:readline";
import { existsSync, mkdirSync, readFileSync, writeFileSync, chmodSync, readdirSync, statSync, rmSync, realpathSync } from "node:fs";
import { homedir, hostname, platform, tmpdir } from "node:os";
import { join, basename, dirname, delimiter, sep } from "node:path";

// Установщик с панели (install.sh / install.ps1) кладёт свой Node в папку пользователя и запускает мост без Терминала
// (LaunchAgent, «Автозагрузка»): npx берём рядом с этим node, а не из PATH системы.
process.env.PATH = dirname(process.execPath) + delimiter + (process.env.PATH || "");

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
  { name: "screenshot", description: "Снимок экрана компьютера (JPEG, длинная сторона до 1600 px). На macOS нужно разрешение «Запись экрана» для Терминала. Несколько мониторов (расширенный рабочий стол) — display: 1 основной, 2, 3…",
    inputSchema: { type: "object", properties: { display: { type: "integer", minimum: 1, maximum: 9, description: "номер дисплея; нет — основной" } } } },
];
// Терминал на компьютере (владелец 21.11): только команды из белого списка, каждая — после «Да» человека в пульте.
// Сервер проверяет строку и делает черновик; сюда приходит готовый список аргументов с отметкой _confirmed — мост
// проверяет его ещё раз сам. Без оболочки: execFile, ни конвейеров, ни подстановок.
export const RUN_TOOL = { name: "run_allowed",
  description: "Команда на компьютере пользователя — только из белого списка: ls [-l|-a|-la|-lh] [папка в доме]; df -h; " +
    "du -sh <папка в доме>; open <файл или папка в доме> (документы, картинки, музыка, видео — не программы; macOS); " +
    "ping -c 3 <адрес сайта>; brew list (macOS); sw_vers (macOS); uptime. Без ; | & $( ) кавычек и «..». " +
    "Каждая — только после «Да» человека: первый вызов вернёт черновик; после подтверждения вызовите снова с draft. " +
    "На Windows — пока только ping.",
  inputSchema: { type: "object", properties: { command: { type: "string", description: "например: df -h" },
    draft: { type: "string", description: "id черновика — только после «Да» человека; первый вызов — без него" } }, required: ["command"] } };
const DOC_EXT = new Set(("pdf txt rtf md csv doc docx xls xlsx ppt pptx odt ods odp pages numbers key jpg jpeg png gif heic " +
  "webp bmp tif tiff mp3 m4a wav aac flac mp4 mov m4v avi mkv epub").split(" "));
const BAD = /[;|&$`<>(){}[\]*?!\\"'\n\r\t#%^=]/;

export function checkArgv(argv, home = homedir(), os = platform()) {
  const no = (t) => { throw new Error(t || "команды нет в белом списке"); };
  if (!Array.isArray(argv) || !argv.length || argv.some((x) => typeof x !== "string" || BAD.test(x) || x.split(/[\\/]/).includes(".."))) no();
  const [p, ...a] = argv, key = argv.join(" ");
  const inHome = (x) => {
    if (!x || x.startsWith("-") || x.startsWith("/") || /^[a-z]:/i.test(x)) no("только путь внутри домашней папки");
    const real = realpathSync(join(home, x.replace(/^~[\\/]?/, ""))), base = realpathSync(home);
    if (real !== base && !real.startsWith(base + sep)) no("только путь внутри домашней папки");
    return real;
  };
  if (os === "win32" && p !== "ping") no("на Windows — пока только ping");
  if (p === "ls") {
    const flags = a.filter((x) => x.startsWith("-")), rest = a.filter((x) => !x.startsWith("-"));
    if (flags.length > 1 || (flags.length && !["-l", "-a", "-la", "-al", "-lh"].includes(flags[0])) || rest.length > 1) no("ls: -l, -a, -la, -lh и одна папка");
    return ["ls", ...flags, ...(rest.length ? [inHome(rest[0])] : [])];
  }
  if (p === "df") { if (key !== "df -h") no("df: только df -h"); return ["df", "-h"]; }
  if (p === "du") { if (a.length !== 2 || a[0] !== "-sh") no("du: только du -sh <папка>"); return ["du", "-sh", inHome(a[1])]; }
  if (p === "open") {
    if (os !== "darwin") no("open — только на macOS");
    if (a.length !== 1) no("open: один файл или папка");
    const real = inHome(a[0]), last = basename(real), ext = last.includes(".") && !/^\.[^.]*$/.test(last) ? last.split(".").pop().toLowerCase() : "";
    if (ext && !DOC_EXT.has(ext)) no(`open: файлы .${ext} не открываю — только документы, картинки, музыку, видео и папки`);
    if (!ext && !statSync(real).isDirectory()) no("open: файл без расширения не открываю");
    return ["open", real];
  }
  if (p === "ping") {
    const host = String(a[2] || "").toLowerCase();
    if (a.length !== 3 || a[0] !== "-c" || a[1] !== "3" || !/^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?)*$/.test(host)) no("ping: только ping -c 3 <адрес сайта>");
    return os === "win32" ? ["ping", "-n", "3", host] : ["ping", "-c", "3", host];
  }
  if (p === "brew") { if (os !== "darwin" || key !== "brew list") no("brew: только brew list на macOS"); return ["brew", "list"]; }
  if (p === "sw_vers" || p === "uptime") { if (a.length || (p === "sw_vers" && os !== "darwin")) no(); return [p]; }
  return no();
}

export async function runAllowed(args = {}, run = execFile, home = homedir(), os = platform()) {
  if (!args._confirmed) throw new Error("команда — только после «Да» человека в пульте: сначала черновик");
  const [cmd, ...rest] = checkArgv(args.argv, home, os);
  const env = { ...process.env, PATH: `${process.env.PATH}${delimiter}/opt/homebrew/bin${delimiter}/usr/local/bin` };
  return new Promise((ok) => run(cmd, rest, { timeout: 60000, maxBuffer: 2 << 20, cwd: home, env, shell: false },
    (e, out, err) => {
      const text = `${out || ""}${err ? "\n" + err : ""}`.trim().slice(0, 20000);
      ok(e && !text ? `не выполнилось: ${e.message}` : text || "(пусто)");
    }));
}

const exec = (cmd, args) => new Promise((ok, no) => execFile(cmd, args, { timeout: 20000 }, (e, out) => (e ? no(e) : ok(out))));

// Заметки, Напоминания, Календарь на Маке (GAS-15, владелец 18.11) — через osascript (JXA), без чужих программ.
// Аргументы уходят в скрипт строкой JSON (argv), в текст скрипта ничего не подставляется. Запись (notes_create,
// reminders_create) мост выполняет только с отметкой пульта _confirmed: её ставит сервер после «Да» человека.
// Права macOS «Автоматизация» спрашиваются по одной программе при первом обращении к ней.
export const APPLE_JS = {
  notes_list: `function run(argv){const a=JSON.parse(argv[0]);const N=Application("Notes");const q=(a.query||"").toLowerCase();
const folders=[],rows=[];N.folders().forEach(f=>{const fn=f.name();folders.push(fn);if(a.folder&&fn!==a.folder)return;
const ids=f.notes.id(),names=f.notes.name(),mods=f.notes.modificationDate();const txt=q?f.notes.plaintext():null;
for(let i=0;i<ids.length;i++){if(q&&names[i].toLowerCase().indexOf(q)<0&&String(txt[i]||"").toLowerCase().indexOf(q)<0)continue;
rows.push({id:ids[i],name:names[i],folder:fn,modified:mods[i].toISOString()});}});
rows.sort((x,y)=>y.modified<x.modified?-1:1);return JSON.stringify({folders:folders,total:rows.length,notes:rows.slice(0,a.limit)});}`,
  notes_get: `function run(argv){const a=JSON.parse(argv[0]);const n=Application("Notes").notes.byId(a.id);
let folder="";try{folder=n.container().name();}catch(e){}
return JSON.stringify({id:n.id(),name:n.name(),folder:folder,modified:n.modificationDate().toISOString(),text:String(n.plaintext()).slice(0,a.max)});}`,
  notes_create: `function run(argv){const a=JSON.parse(argv[0]);const N=Application("Notes");
const esc=s=>String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const body="<div><b>"+esc(a.title)+"</b></div>"+String(a.body||"").split("\\n").map(l=>"<div>"+(esc(l)||"<br>")+"</div>").join("");
const f=a.folder?N.folders.byName(a.folder):N.defaultAccount().defaultFolder();const n=N.Note({body:body});f.notes.push(n);
return JSON.stringify({id:n.id(),name:n.name(),folder:f.name()});}`,
  reminders_lists: `function run(argv){const R=Application("Reminders");
return JSON.stringify({lists:R.lists().map(l=>({name:l.name(),open:l.reminders.completed().filter(c=>!c).length}))});}`,
  reminders_list: `function run(argv){const a=JSON.parse(argv[0]);const R=Application("Reminders");const q=(a.query||"").toLowerCase();const rows=[];
R.lists().forEach(l=>{const ln=l.name();if(a.list&&ln!==a.list)return;const r=l.reminders;
const ids=r.id(),names=r.name(),done=r.completed(),due=r.dueDate(),body=r.body();
for(let i=0;i<ids.length;i++){if(done[i]&&!a.include_completed)continue;
if(q&&names[i].toLowerCase().indexOf(q)<0&&String(body[i]||"").toLowerCase().indexOf(q)<0)continue;
rows.push({id:ids[i],name:names[i],list:ln,done:!!done[i],due:due[i]?due[i].toISOString():null,notes:String(body[i]||"").slice(0,200)});}});
return JSON.stringify({total:rows.length,reminders:rows.slice(0,a.limit)});}`,
  reminders_create: `function run(argv){const a=JSON.parse(argv[0]);const R=Application("Reminders");
const l=a.list?R.lists.byName(a.list):R.defaultList();const p={name:a.title};if(a.notes)p.body=a.notes;if(a.due)p.dueDate=new Date(a.due);
const r=R.Reminder(p);l.reminders.push(r);return JSON.stringify({id:r.id(),name:r.name(),list:l.name()});}`,
  mac_calendar_events: `function run(argv){const a=JSON.parse(argv[0]);const C=Application("Calendar");const s=new Date(a.from),e=new Date(a.to);const rows=[];
C.calendars().forEach(c=>{const cn=c.name();if(a.calendar&&cn!==a.calendar)return;
const ev=c.events.whose({_and:[{startDate:{_lessThan:e}},{endDate:{_greaterThan:s}}]});
const t=ev.summary(),st=ev.startDate(),en=ev.endDate(),loc=ev.location(),ad=ev.alldayEvent();
for(let i=0;i<t.length;i++)rows.push({calendar:cn,summary:t[i],start:st[i].toISOString(),end:en[i].toISOString(),all_day:!!ad[i],location:loc[i]||""});});
rows.sort((x,y)=>x.start<y.start?-1:1);return JSON.stringify({total:rows.length,events:rows.slice(0,a.limit),
note:"повторяющиеся события — по первому событию серии (ограничение AppleScript)"});}`,
};

const LIM = { type: "integer", minimum: 1, maximum: 200, description: "сколько показать, по умолчанию 50" };
const DRAFT = { type: "string", description: "id черновика — только после «Да» человека; первый вызов — без него" };
export const APPLE_TOOLS = [
  { name: "notes_list", description: "Заметки на Маке (приложение «Заметки», в т. ч. iCloud): папки и заметки — название, папка, когда изменена; поиск query — по названию и тексту. Ничего не меняет. При первом вызове macOS спросит разрешение «Терминал → Заметки».",
    inputSchema: { type: "object", properties: { folder: { type: "string" }, query: { type: "string" }, limit: LIM } } },
  { name: "notes_get", description: "Текст одной заметки по id из notes_list (до 20000 знаков). Ничего не меняет.",
    inputSchema: { type: "object", properties: { id: { type: "string" } }, required: ["id"] } },
  { name: "notes_create", description: "Новая заметка на Маке. Только после «Да» человека: первый вызов вернёт черновик (на Маке ничего не пишется) — покажите его человеку; после его подтверждения вызовите снова с draft. Изменять и удалять заметки нельзя.",
    inputSchema: { type: "object", properties: { title: { type: "string" }, body: { type: "string" }, folder: { type: "string", description: "папка; нет — по умолчанию" }, draft: DRAFT }, required: ["title"] } },
  { name: "reminders_lists", description: "Списки «Напоминаний» на Маке и сколько в каждом невыполненных. Ничего не меняет. При первом вызове macOS спросит разрешение «Терминал → Напоминания».",
    inputSchema: { type: "object", properties: {} } },
  { name: "reminders_list", description: "Напоминания: невыполненные (include_completed — и выполненные), поиск query по названию и заметке, срок. Ничего не меняет.",
    inputSchema: { type: "object", properties: { list: { type: "string" }, query: { type: "string" }, include_completed: { type: "boolean" }, limit: LIM } } },
  { name: "reminders_create", description: "Новое напоминание на Маке (через iCloud появится и на iPhone). Только после «Да» человека: первый вызов вернёт черновик — покажите его человеку; после подтверждения вызовите снова с draft. due — ГГГГ-ММ-ДД или ГГГГ-ММ-ДДTЧЧ:ММ по часам Мака (дата без времени — 09:00).",
    inputSchema: { type: "object", properties: { title: { type: "string" }, list: { type: "string" }, due: { type: "string" }, notes: { type: "string" }, draft: DRAFT }, required: ["title"] } },
  { name: "mac_calendar_events", description: "События приложения «Календарь» на Маке (все его календари, в т. ч. iCloud) за период: from–to ГГГГ-ММ-ДД включительно, по умолчанию сегодня и 6 дней; до 62 дней. Повторяющиеся — по первому событию серии. Ничего не меняет. При первом вызове macOS спросит «Терминал → Календарь».",
    inputSchema: { type: "object", properties: { from: { type: "string" }, to: { type: "string" }, calendar: { type: "string" }, limit: LIM } } },
];
export const APPLE_WRITE = ["notes_create", "reminders_create"];
const APP_RU = (name) => (name.startsWith("notes") ? "Заметки" : name.startsWith("reminders") ? "Напоминания" : "Календарь");
export const automationHint = (app) => `macOS не дал пульту доступ к программе «${app}». На Маке: меню Apple → Системные ` +
  `настройки → Защита и безопасность → Конфиденциальность → «Автоматизация» → «Терминал» → включить «${app}». ` +
  `Окна с вопросом не было или нажали «Не разрешать» — включите там же и повторите.`;

const day = (s, what) => {
  if (!s) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s));
  if (!m) throw new Error(`${what} — дата ГГГГ-ММ-ДД`);
  return new Date(+m[1], +m[2] - 1, +m[3]);
};

// Аргументы скрипта: только известные поля, пределы — здесь (скрипт JXA им доверяет).
export function appleArgs(name, a = {}) {
  const lim = Math.min(200, Math.max(1, parseInt(a.limit, 10) || 50)), str = (v, n) => String(v ?? "").slice(0, n);
  if (name === "notes_list") return { folder: str(a.folder, 100), query: str(a.query, 200), limit: lim };
  if (name === "notes_get") { if (!a.id) throw new Error("id — из notes_list"); return { id: str(a.id, 300), max: 20000 }; }
  if (name === "notes_create") return { title: str(a.title, 200), body: str(a.body, 20000), folder: str(a.folder, 100) };
  if (name === "reminders_lists") return {};
  if (name === "reminders_list") return { list: str(a.list, 100), query: str(a.query, 200), include_completed: !!a.include_completed, limit: lim };
  if (name === "reminders_create") {
    let due = str(a.due, 16);
    if (due && !/^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?$/.test(due)) throw new Error("due — ГГГГ-ММ-ДД или ГГГГ-ММ-ДДTЧЧ:ММ");
    if (/^\d{4}-\d{2}-\d{2}$/.test(due)) due += "T09:00";
    return { title: str(a.title, 200), list: str(a.list, 100), due, notes: str(a.notes, 5000) };
  }
  if (name === "mac_calendar_events") {
    const now = new Date(), from = day(a.from, "from") || new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const last = day(a.to, "to") || new Date(from.getFullYear(), from.getMonth(), from.getDate() + 6);
    const to = new Date(last.getFullYear(), last.getMonth(), last.getDate() + 1);
    if (to <= from) throw new Error("to раньше from");
    if ((to - from) / 86400000 > 62) throw new Error("период не больше 62 дней");
    return { from: from.toISOString(), to: to.toISOString(), calendar: str(a.calendar, 100), limit: lim };
  }
  throw new Error("нет такого инструмента");
}

const execLong = (cmd, args) => new Promise((ok, no) => execFile(cmd, args, { timeout: 90000, maxBuffer: 20 << 20 },
  (e, out, err) => (e ? no(Object.assign(e, { stderr: String(err || "") })) : ok(out))));

// Вызов инструмента Мака: запись — только с отметкой пульта _confirmed (сервер ставит её после «Да» человека).
export async function appleTool(name, args = {}, run = execLong) {
  if (!APPLE_JS[name]) throw new Error("нет такого инструмента");
  if (APPLE_WRITE.includes(name) && !args._confirmed) throw new Error("запись — только после «Да» человека в пульте: сначала черновик");
  const a = appleArgs(name, args);
  if (APPLE_WRITE.includes(name) && !a.title.trim()) throw new Error("укажите title");
  try {
    return String(await run("osascript", ["-l", "JavaScript", "-e", APPLE_JS[name], JSON.stringify(a)])).trim();
  } catch (e) {
    const m = `${e?.message || e}\n${e?.stderr || ""}`;
    if (e?.code === "ENOENT") throw new Error("Заметки, Напоминания и Календарь — только на Маке (нет osascript)");
    if (/-1743|not authori[sz]ed to send apple events/i.test(m)) throw new Error(automationHint(APP_RU(name)));
    if (/-1728|can.t get|не удается получить/i.test(m)) throw new Error(`${APP_RU(name)}: не найдено (проверьте id, папку или список)`);
    if (e?.killed) throw new Error(`${APP_RU(name)}: не ответили за 90 с — сузьте папку, список или период`);
    throw new Error(`${APP_RU(name)}: ${m.trim().split("\n").slice(-1)[0].slice(0, 300)}`);
  }
}

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

export const SCREEN_HINT = "macOS не дал снять экран: нет разрешения «Запись экрана». На Маке: меню  → Системные " +
  "настройки → Защита и безопасность → Конфиденциальность → «Запись экрана» → замок → включить «Терминал»; затем " +
  "закрыть Терминал (Cmd+Q), открыть снова и запустить мост.";

export async function screenshot(os = platform(), run = exec, display = 1) {
  if (os !== "darwin") throw new Error("снимок экрана — пока только на macOS");
  const f = join(tmpdir(), `gp-shot-${Date.now()}.jpg`);
  try {
    const d = Math.min(9, Math.max(1, parseInt(display, 10) || 1));      // screencapture -D: номер дисплея, 1 — основной
    // основной — как раньше (проверено на Big Sur 17.11); -D — только для 2, 3… (расширенный рабочий стол)
    try { await run("screencapture", ["-x", ...(d > 1 ? ["-D", String(d)] : []), "-t", "jpg", f]); }
    catch (e) {
      const m = String(e?.message || e);
      if (/could not create image/i.test(m)) throw new Error(SCREEN_HINT);
      if (/display|invalid/i.test(m)) throw new Error(`дисплея ${d} нет — у этого Мака меньше мониторов (1 — основной)`);
      throw e;
    }
    await run("sips", ["-Z", "1600", f]);
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
    body: JSON.stringify({ code, name: hostname(), os: platform(), old: load().token || "" }) });   // повторная установка — та же запись
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
      if (m?.result?.tools && Array.isArray(m.result.tools)) m.result.tools.push(SAVE_TOOL, ...MAC_TOOLS, ...APPLE_TOOLS, RUN_TOOL);   // ответ на tools/list
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
        return screenshot(platform(), exec, a.display).then((b64) => reply(m.id, { content: [{ type: "image", data: b64, mimeType: "image/jpeg" }] }), fail);
      }
      if (m.method === "tools/call" && APPLE_TOOLS.some((t) => t.name === p.name)) {
        return appleTool(p.name, p.arguments || {}).then((t) => reply(m.id, { content: [{ type: "text", text: t }] }),
          (err) => reply(m.id, null, { code: -32013, message: err.message }));
      }
      if (m.method === "tools/call" && p.name === RUN_TOOL.name) {
        return runAllowed(p.arguments || {}).then((t) => reply(m.id, { content: [{ type: "text", text: t }] }),
          (err) => reply(m.id, null, { code: -32014, message: err.message }));
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
const MAIN = process.argv[1] && realpathSync(process.argv[1]) === realpathSync(new URL(import.meta.url).pathname);   // импорт в тестах — без запуска
if (!MAIN) { /* модуль импортирован — команды не выполняем */ }
else if (cmd === "pair") pair(a1, a2).catch((e) => { console.error("Не привязал:", e.message); process.exit(1); });
else if (cmd === "allow") {
  const c = load(), d = String(a1 || "").toLowerCase();
  if (!BLOCKED.includes(d)) { console.error("Этого сайта нет в запретном списке — разрешать не нужно."); process.exit(0); }
  console.log(`Внимание: правила ${d} могут запрещать автоматизацию. Прочитайте условия сервиса. Разрешаю ${d}.`);
  save({ ...c, allowed: [...new Set([...(c.allowed || []), d])] });
} else if (cmd === "status") {
  const c = load(); console.log({ url: c.url, id: c.id, allowed: c.allowed || [], token: c.token ? "есть" : "нет" });
} else if (!cmd) run();
else { console.error("Команды: pair <адрес> <КОД> | allow <домен> | status | без аргументов — работать"); process.exit(2); }
