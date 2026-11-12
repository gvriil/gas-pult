const tg = window.Telegram?.WebApp;
const params = new URLSearchParams(location.search);
const DEMO = params.has("demo");
// Фокус (задача 41): ссылка «…/#focus=<токен>» — только чат одной сессии. Токен — после «#»: на сервер и в журналы он
// не уходит; страница отдаёт его один раз (POST /api/focus/open) и убирает из адреса.
const FOCUS_TOKEN = (/(?:^#|&)focus=([A-Za-z0-9_-]{24,64})/.exec(location.hash) || [])[1] || "";
const FOCUS = !!FOCUS_TOKEN || params.has("focus");
if (FOCUS_TOKEN) history.replaceState(null, "", location.pathname + (params.has("focus") ? location.search : (location.search ? location.search + "&" : "?") + "focus"));
// Статусы: свободна — спокойный серый, работает — синий, ждёт ответа — янтарный (зелёный — только «готов результат»).
const ST = { idle: { label: "свободна", cls: "s-idle" }, busy: { label: "работает", cls: "s-running" }, dialog: { label: "ждёт ответа", cls: "s-approval" },
             stopped: { label: "остановлена", cls: "s-stopped" } };      // Claude завершился, в окне — командная строка
const ORDER = { dialog: 0, busy: 1, idle: 2, stopped: 3 };
let lastY = 0, autoUntil = 0, barsShown = true, barsDir = 0, barsRun = 0, barsHidDir = 0;   // прячущиеся панели
let drag = null;                                    // перемотка пальцем: { id, bar, t }
let voice = null;                                   // озвучка: { w, name, msg, full, state: "prep" | "play" | "pause", at? }
let hint = "";                                       // подсказка Claude Code для пустого поля ввода
let histRev = "", BUILD = null, pending = [], sessions = [], meta = null, current = null, tab = "chat", files = [], hist = [], histMore = false,
    lastStatus = null, rec = null, view = "home", homeView = "sessions", loginId = null, mcpData = null, termAll = false,
    termWrap = false, lastOk = Date.now(), openLogs = new Set(),
    lastTouch = Date.now(), lastPoll = 0;      // зритель: последнее касание и последний опрос (pollDue)
const wideMQ = matchMedia("(min-width: 1024px)");
const split = () => !FOCUS && wideMQ.matches && view !== "login";          // десктоп: список слева, сессия справа

const $ = (id) => document.getElementById(id);
// Внешняя ссылка: в Telegram — его методом, в браузере — новой вкладкой (страница панели остаётся на месте).
const openUrl = (url) => (tg?.initData ? tg.openLink(url) : window.open(url, "_blank", "noopener"));
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const clean = (s) => String(s ?? "").replace(/[\p{Extended_Pictographic}️‍]/gu, "").replace(/\s+/g, " ").trim();   // без системных эмодзи
const folder = (p) => p.split("/").filter(Boolean).pop() || "~";
const cur = () => sessions.find((x) => x.id === current);
const haptic = (kind, v) => { try { tg?.HapticFeedback?.[kind]?.(v); } catch (e) {} };
function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
