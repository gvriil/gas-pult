// Задачи владельца (#203) — часть интерфейса по требованию (#191): ядро держит только кнопку «Задачи (N)» наверху,
// этот код грузится при первом нажатии (и заранее, в простое после первого показа).
// Владелец 14.11: «чтобы я понимал, какие задачи не решены и какие решены … сразу нажать, провалиться туда и
// продолжить работу». Нажал задачу — открывается её чат и карточка с действием: команда — «Выполнить» (тот же путь,
// что ▶ у ответа: код подтверждения для нового входа), позвонить — tel:, написать — черновик и Telegram (отправляет
// сам владелец), встреча — черновик события, решение — варианты: ответ уходит в чат задачи дословно.

const KIND_T = { command: "Выполнить команду", call: "Позвонить", write: "Написать", meeting: "Встреча",
  decision: "Решение", check: "Проверить", other: "Другое" };
const KIND_IC = { command: "term", call: "phone", write: "mail", meeting: "cal", decision: "help", check: "eye", other: "tasks" };
const ST_T = { todo: "не начато", doing: "в работе", waiting: "ждёт вас", done: "выполнено" };
// Матрица Эйзенхауэра (решение владельца 14.11: «по срочности и важности»): квадрант считает сервер (поле q, 0 — не оценено)
const Q_T = { 1: "Срочно и важно — сделать сейчас", 0: "Не разобрано — оцените срочность и важность",
  2: "Важно, не срочно — запланировать", 3: "Срочно, не важно — быстро или делегировать", 4: "Не срочно и не важно — потом или убрать" };
const Q_SHORT = { 1: "срочно и важно", 2: "важно", 3: "срочно", 4: "ни то ни другое", 0: "не разобрано" };
let TASKS = [];
// Остаёмся на месте (владелец 19.11: «если я там нажал что-то — они не должны закрываться, главное — вернуться туда же,
// где я был»): прокрутка списка запоминается, после действия список открывается на той же позиции, задача — с
// подсветкой, 5 секунд можно «Отменить».
let Y = 0, JUST = "";

async function tasksLoad() {
  TASKS = (await api("/api/tasks")).tasks || [];
  return TASKS;
}

// Название чата задачи — по смыслу (как в панели), не служебное имя окна tmux («tgi-0904»): сервер отдаёт имя окна
const chatName = (t) => { const s = sessions.find((x) => x.id === t.chat_now); return (s && (s.title || s.name)) || t.chat_name || ""; };
async function tasksOpen() {
  try { await tasksLoad(); } catch (e) { return toast("Задачи: " + e.message, 4500); }
  tasksSheet();
}

// Цвет задачи (владелец 17.11): красный — срочно и важно, оранжевый — ждёт вас, жёлтый — в работе, зелёный — готово
const tqDot = (t, q) => (t.status === "done" ? "tq-g" : q === 1 ? "tq-r" : t.status === "waiting" ? "tq-o" : t.status === "doing" ? "tq-y" : "");
// Группы сворачиваются по нажатию на заголовок (владелец 19.11: «таски удобно сворачивать по группировкам срочно-важно»);
// состояние запоминается в браузере. «Ждут вас» — всегда первой группой; по умолчанию все открыты («как было»).
const FOLD_KEY = "tq:fold";
function folds() { try { return JSON.parse(localStorage.getItem(FOLD_KEY) || "{}") || {}; } catch (e) { return {}; } }
function fold(k) {
  const f = folds(); f[k] ? delete f[k] : (f[k] = 1);
  try { localStorage.setItem(FOLD_KEY, JSON.stringify(f)); } catch (e) { /* без памяти — свернётся на этот раз */ }
  document.querySelectorAll(".sheet-bg").forEach((x) => x.remove());
  tasksSheet(true);
}
const taskRow = (t, q) => ({ label: t.title, dot: tqDot(t, q), icon: KIND_IC[t.kind] || "tasks", /* срочность — точкой, не красным текстом (UI-обзор 20.11) */
  sub: [ST_T[t.status], KIND_T[t.kind], t.due ? (t.overdue ? "просрочено: " : "срок ") + t.due : "", "дальше: " + (t.next || "—"),
    chatName(t) ? "чат «" + chatName(t) + "»" : ""].filter(Boolean).join(" · "),
  run: () => taskGo(t) });
// Gemini №14: задачи «Выполнить команду» — разработчику; на ПК окно задач — правой шторкой 400 px
const mine = (t) => dev() || t.kind !== "command";
const SIDE_CSS = `.sheet-bg.side { justify-content: flex-end; align-items: stretch; padding: 0; }
.sheet-bg.side .sheet { width: 400px; max-width: 100vw; height: 100%; max-height: none; border-radius: 0; }`;
function tasksSheet(keep) {
  const all = TASKS.filter(mine);
  const open = all.filter((t) => t.status !== "done"), done = all.filter((t) => t.status === "done");
  const f = folds(), rows = [];
  const group = (k, title, list, q) => {
    if (!list.length) return;
    rows.push({ label: `${title} · ${list.length}`, icon: f[k] ? "plus" : "chev", sub: f[k] ? "свёрнуто — нажмите, чтобы открыть" : "",
      fold: 1, run: () => fold(k) });
    if (!f[k]) rows.push(...list.map((t) => taskRow(t, q ?? (t.q || 0))));
  };
  const waiting = open.filter((t) => t.status === "waiting");
  group("w", "Ждут вас", waiting);
  for (const q of [1, 0, 2, 3, 4]) group(q, Q_T[q], open.filter((t) => (t.q || 0) === q && t.status !== "waiting"), q);
  helpSheet("sheet.tasks");
  sheet(`Задачи · не решено ${open.length}`, [
    ...(open.length ? [] : [{ info: true, icon: "check", label: "Всё решено", sub: "агенты ставят задачи командой gas-pult task add" }]),
    ...rows,
    { label: "Добавить задачу", icon: "plus", run: () => taskNew() },
    ...(done.length ? [{ head: `Выполнено · ${done.length}` },
      ...done.slice(0, 15).map((t) => ({ label: t.title, dot: "tq-g", sub: "выполнено" + (t.done_at ? " · " + when(t.done_at) : ""), run: () => taskGo(t) }))] : []),
  ]);
  const sh = [...document.querySelectorAll(".sheet-bg .sheet")].pop();
  if (!sh) return;
  sh.dataset.tasks = "1";
  if (split()) {
    if (!document.getElementById("tasksSideCss")) document.head.insertAdjacentHTML("beforeend", `<style id="tasksSideCss">${SIDE_CSS}</style>`);
    sh.parentElement.classList.add("side");
  }
  if (keep) sh.scrollTop = Y;
  sh.addEventListener("scroll", () => { Y = sh.scrollTop; }, { passive: true });
  if (JUST) {                                          // только что изменённая задача — подсветка на месте
    const b = [...sh.querySelectorAll("button[data-i]")].find((x) => x.querySelector("span")?.firstChild?.textContent === JUST);
    JUST = "";
    if (b) { b.classList.add("just"); if (b.offsetTop < sh.scrollTop || b.offsetTop > sh.scrollTop + sh.clientHeight - 40) b.scrollIntoView({ block: "center" }); }
  }
}
const back = () => { document.querySelectorAll(".sheet-bg").forEach((x) => x.remove()); tasksSheet(true); };

const when = (ts) => new Date(ts * 1000).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

async function taskGo(t) {                            // «провалиться»: чат задачи и карточка поверх него
  const sh = document.querySelector(".sheet[data-tasks]"); if (sh) Y = sh.scrollTop;
  document.querySelectorAll(".sheet-bg").forEach((x) => x.remove());
  if (t.chat_now && t.chat_now !== current) await openSession(t.chat_now);
  sheetFrom = null;                                    // своя кнопка «К списку задач» — на то же место, без второй «Назад»
  taskSheet(t);
}

function taskSheet(t) {
  const a = [];
  if (t.kind === "command") a.push({ label: "Выполнить", icon: "play", sub: t.cmd, run: () => taskRun(t) },
    { label: "Скопировать команду", icon: "copy", run: () => copyText(t.cmd, "Команда скопирована") });
  if (t.kind === "call") a.push({ label: "Позвонить: " + t.phone, icon: "phone", run: () => { location.href = "tel:" + String(t.phone).replace(/[^+\d]/g, ""); } });
  if (t.kind === "write") {
    if (t.draft) a.push({ label: "Скопировать черновик", icon: "copy", sub: t.draft.slice(0, 160), run: () => copyText(t.draft, "Черновик скопирован") });
    if (/^@\w{3,}$/.test(t.to || "")) a.push({ label: "Открыть " + t.to + " в Telegram", icon: "ext", sub: "отправляете вы сами", run: () => openUrl("https://t.me/" + t.to.slice(1)) });
    else if (t.to) a.push({ info: true, icon: "mail", label: "Кому: " + t.to });
  }
  if (t.kind === "meeting") a.push({ label: "Скопировать черновик встречи", icon: "cal", sub: [t.with, t.when].filter(Boolean).join(" · "),
    run: () => copyText(`Встреча: ${t.title}\nС кем: ${t.with || "—"}\nКогда: ${t.when || "—"}`, "Черновик встречи скопирован — приглашения не отправлены") });
  if (t.kind === "decision") {
    a.push({ info: true, icon: "help", label: t.question });
    for (const o of t.options || []) a.push({ label: o, icon: "check", sub: t.chat_now ? "ответ уйдёт в чат «" + chatName(t) + "» дословно" : "чата задачи нет — только отметить", run: () => taskDecide(t, o) });
  }
  if (t.link) a.push({ label: "Открыть источник", icon: "ext", sub: t.link, run: () => openUrl(t.link) });
  if (t.chat_now && t.chat_now !== current) a.push({ label: "Открыть чат «" + chatName(t) + "»", icon: "chat", run: () => openSession(t.chat_now) });
  a.push(t.status === "done" ? { label: "Вернуть в работу", icon: "refresh", run: () => taskSet(t, { status: "todo" }, "Задача снова в работе") }
    : { label: "Отметить выполненным", icon: "check", run: () => taskSet(t, { status: "done" }, "Выполнено") });
  if (t.status !== "done") a.push({ label: "Срочность и важность…", icon: "bolt", sub: Q_SHORT[t.q || 0], run: () => taskQ(t) },
    { label: "Что сделать дальше…", icon: "edit", sub: t.next, run: () => taskNext(t) },
    ...(t.status !== "waiting" ? [{ label: "Ждёт меня", icon: "wait", run: () => taskSet(t, { status: "waiting" }, "Поставил первой в списке") }] : []));
  a.push({ label: "Удалить задачу", icon: "trash", danger: true, run: () => confirmDanger("Удалить задачу «" + t.title + "»?", () => taskSet(t, null, "Задача удалена")) });
  helpSheet("sheet.tasks");
  sheet(t.title, [{ label: "К списку задач", icon: "back", sub: "на то же место", run: back }, { info: true, icon: KIND_IC[t.kind] || "tasks", label: "Дальше: " + (t.next || "—"),
    sub: [Q_SHORT[t.q || 0], ST_T[t.status], KIND_T[t.kind], t.due ? "срок " + t.due : "", t.by ? "поставил: " + t.by : "", t.result ? "последний запуск: код " + t.result.code : ""].filter(Boolean).join(" · ") }, ...a]);
}

function taskQ(t) {                                     // квадрант руками: 1–4
  helpSheet("sheet.tasks");
  sheet("Срочность и важность", [1, 2, 3, 4].map((q) => ({ label: Q_T[q], icon: q === (t.q || 0) ? "check" : "bolt",
    run: () => taskSet(t, { q }, "Записал: " + Q_SHORT[q]) })));
}

async function taskSet(t, upd, ok, quiet) {
  try {
    if (upd) await api("/api/tasks/update", { id: t.id, ...upd }); else await api("/api/tasks/remove", { id: t.id });
    haptic("notificationOccurred", "success");
    await tasksLoad(); tasksCount(); refreshShared();
    if (quiet) return;
    // обратно в список, на то же место; «Отменить» — 5 с (кроме удаления: его подтверждаем заранее)
    const was = Object.fromEntries(Object.keys(upd || {}).map((k) => [k, t[k] ?? (k === "q" ? 0 : "")]));
    if (upd) JUST = t.title;
    back();
    undoToast(ok, upd && ok !== "Отменено" ? () => taskSet(t, was, "Отменено") : null);
  } catch (e) { toast("Не вышло: " + e.message, 4500); }
}

function undoToast(text, undo) {
  document.querySelectorAll(".toast").forEach((x) => x.remove());
  const el = document.createElement("div"); el.className = "toast"; el.textContent = text;
  if (undo) {
    const b = document.createElement("button"); b.type = "button"; b.className = "toast-undo"; b.textContent = "Отменить";
    b.onclick = () => { el.remove(); undo(); }; el.append(" ", b);
  }
  notice(el); setTimeout(() => el.remove(), undo ? 5000 : 2600);
}

async function taskRun(t, confirmed) {
  try {
    const d = await api("/api/tasks/run", { id: t.id, ...(confirmed ? { confirmed: true } : {}) });
    if (d.confirm) return confirmDanger("Команда опасная:\n" + t.cmd + "\n\nВыполнить?", () => taskRun(t, true));
    sheet(d.code === 0 ? "Команда выполнена" : "Команда завершилась с кодом " + d.code, [
      { info: true, icon: d.code === 0 ? "check" : "warn", label: t.cmd, sub: (d.out || "").slice(-600) || "вывода нет" },
      ...(d.code === 0 && t.status !== "done" ? [{ label: "Отметить задачу выполненной", icon: "check", run: () => taskSet(t, { status: "done" }, "Выполнено") }] : []),
      { label: "Скопировать вывод", icon: "copy", run: () => copyText(d.full || d.out || "", "Вывод скопирован") }]);
  } catch (e) { toast("Не выполнено: " + e.message, 5000); }
}

async function taskDecide(t, option) {
  try {
    if (t.chat_now) await api("/api/send", { w: t.chat_now, text: option });
    await taskSet(t, { status: "done" }, t.chat_now ? "Ответ ушёл в чат, задача выполнена" : "Отмечено выполненным");
  } catch (e) { toast("Не отправлено: " + e.message, 5000); }
}

function textSheet(title, value, hint, save) {          // одно поле: «что дальше», заголовок новой задачи
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.tasks");
  bg.innerHTML = `<div class="sheet" role="dialog"><h3>${esc(title)}</h3>
    <div class="field" style="margin:4px 16px 0"><input id="taskText" maxlength="300" autocomplete="off" value="${esc(value || "")}"></div>
    <p class="note" style="margin:6px 16px 0">${esc(hint)}</p>
    <div class="row2"><button class="btn ghost" data-close>Отмена</button><button class="btn" id="taskOk">Сохранить</button></div></div>`;
  document.body.append(bg);
  const inp = bg.querySelector("#taskText"); inp.focus();
  const ok = () => { const v = inp.value.trim(); if (!v) return inp.focus(); bg.remove(); save(v); };
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) bg.remove(); if (e.target.closest("#taskOk")) ok(); });
  inp.addEventListener("keydown", (e) => { if (e.key === "Enter") ok(); });
}

function taskNext(t) {
  textSheet("Что сделать дальше", t.next, "Одна строка: следующий шаг по задаче", (v) => taskSet(t, { next: v }, "Записал"));
}

function taskNew() {
  textSheet("Новая задача", "", "Что нужно не забыть — коротко", (title) =>
    textSheet("Что сделать дальше", "", "Первый шаг", async (next) => {
      try {
        await api("/api/tasks/add", { title, next, kind: "other", ...(current && view === "session" ? { chat: current, sid: cur()?.sid || "" } : {}) });
        JUST = title; toast("Задача добавлена"); await tasksLoad(); tasksCount(); back();
      } catch (e) { toast("Не добавлено: " + e.message, 4500); }
    }));
}

Object.assign(window, { tasksOpen, taskSheet, tasksLoad });
