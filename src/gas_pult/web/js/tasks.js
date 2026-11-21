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
const chatName = (t) => { const s = sessions.find((x) => x.id === t.chat_now); return (s && (s.title || s.name)) || t.chat_title || t.chat_name || ""; };
async function tasksOpen() {
  try { await tasksLoad(); } catch (e) { return toast("Задачи: " + e.message, 4500); }
  tasksSheet();
}

// Группы (владелец 21.11, ориентир — Things, Todoist, Linear): «Срочно», «Сегодня», «Позже», «Сделано» (свёрнуто).
// Группу считает сервер (tasks.group, поле group); здесь — то же правило на случай старого ответа и для демо.
const GROUPS = [["urgent", "Срочно"], ["today", "Сегодня"], ["later", "Позже"], ["done", "Сделано"]];
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
function taskGroup(t) {
  if (t.group) return t.group;
  if (t.status === "done") return "done";
  if (t.overdue || t.urgent === true || t.status === "waiting") return "urgent";
  return t.due === today() || t.status === "doing" ? "today" : "later";
}
// Тон карточки — полоса слева: просрочено и срочно — красный, ждёт вас — оранжевый, в работе — жёлтый, сделано — зелёный
const tone = (t) => (t.status === "done" ? "g" : t.overdue ? "over" : taskGroup(t) === "urgent" ? (t.status === "waiting" ? "o" : "r")
  : t.status === "doing" ? "y" : taskGroup(t) === "today" ? "a" : "");
const dueText = (t) => {
  if (!t.due) return "";
  if (t.overdue) return "просрочено: " + dayName(t.due);
  return t.due === today() ? "сегодня" : "до " + dayName(t.due);
};
const dayName = (d) => { const x = new Date(d + "T12:00:00"); return isNaN(x) ? d : x.toLocaleDateString("ru-RU", { day: "numeric", month: "short" }); };
// Свёрнутые группы запоминаются в браузере (владелец 19.11: «таски удобно сворачивать по группировкам»);
// «Сделано» свёрнуто по умолчанию — флаг для него означает «развернули».
const FOLD_KEY = "gp.tasks.groups";
function folds() { try { return JSON.parse(localStorage.getItem(FOLD_KEY) || "{}") || {}; } catch (e) { return {}; } }
const folded = (k, f = folds()) => (k === "done" ? !f[k] : !!f[k]);
function fold(k) {
  const f = folds(); f[k] ? delete f[k] : (f[k] = 1);
  try { localStorage.setItem(FOLD_KEY, JSON.stringify(f)); } catch (e) { /* без памяти — свернётся на этот раз */ }
  const sh = document.querySelector(".sheet[data-tasks]"); if (sh) Y = sh.scrollTop;
  document.querySelectorAll(".sheet-bg").forEach((x) => x.remove());
  tasksSheet(true);
}
// Gemini №14: задачи «Выполнить команду» — разработчику; на ПК окно задач — правой шторкой 400 px
const mine = (t) => dev() || t.kind !== "command";
const SIDE_CSS = `.sheet-bg.side { justify-content: flex-end; align-items: stretch; padding: 0; }
.sheet-bg.side .sheet { width: 400px; max-width: 100vw; height: 100%; max-height: none; border-radius: 0; }`;
// Карточки (владелец 21.11): рамка 1 px, радиус 12, полоса тона слева; заголовок 15/600, ниже «что дальше» и мета
// приглушённо; справа — «Готово» (круг с галочкой) и ⋯. Нажатие на карточку — чат задачи и её действия.
const CARD_CSS = `.sheet.tsk { padding-bottom: calc(10px + env(safe-area-inset-bottom)); }
.tsk-add { display: flex; gap: 8px; align-items: center; margin: 2px 16px 10px; padding: 4px 4px 4px 12px; border: 1px solid var(--field-border); border-radius: 12px; background: var(--bg-surface); }
.tsk-add:focus-within { border-color: var(--border-focus); box-shadow: 0 0 0 1px var(--border-focus); }
.tsk-add .i { color: var(--text-secondary); flex: none; }
.tsk-add input { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; color: var(--text-primary); font: inherit; font-size: calc(16px * var(--fz, 1)); padding: 8px 0; }
.tsk-add input::placeholder { color: var(--field-ph); }
.tsk-add input[type=date] { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.tsk-add { position: relative; }
.sheet .tsk-add .tsk-due { width: auto; min-width: 40px; background: transparent; gap: 4px; padding: 0 8px; font-size: calc(13px * var(--fz, 1)); color: var(--text-secondary); }
.sheet .tsk-add .tsk-due .i { color: var(--text-secondary); } .sheet .tsk-add .tsk-due:hover { background: var(--bg-subtle); }
.sheet .tsk-add .tsk-due span:empty { display: none; }
.sheet .tsk-add button[type=submit] { width: 40px; min-height: 40px; padding: 0; justify-content: center; border-radius: 9px; background: var(--accent-primary); flex: none; }
.sheet .tsk-add button[type=submit] .i { color: var(--on-accent); }
.sheet .tsk-g { min-height: 40px; padding: 8px 16px; gap: 8px; font-size: calc(13px * var(--fz, 1)); font-weight: 600; color: var(--text-secondary); }
.sheet .tsk-g span { flex: 0 1 auto; } .sheet .tsk-g em { font-style: normal; font-weight: 500; color: var(--text-muted); }
.sheet .tsk-g .i { width: 16px; height: 16px; transition: transform .15s; } .sheet .tsk-g.off .i { transform: rotate(-90deg); }
.sheet .tsk-g.r span { color: var(--tq-red); }
.tsk-list { display: flex; flex-direction: column; gap: 8px; padding: 0 16px 6px; }
.tsk-c { position: relative; border: 1px solid var(--border-subtle); border-radius: 12px; background: var(--bg-surface); overflow: hidden; }
.tsk-c::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: transparent; }
.tsk-c.t-r::before, .tsk-c.t-over::before { background: var(--tq-red); } .tsk-c.t-o::before { background: var(--tq-orange); }
.tsk-c.t-y::before { background: var(--tq-yellow); } .tsk-c.t-g::before { background: var(--tq-green); } .tsk-c.t-a::before { background: var(--accent-primary); }
.tsk-c.t-over { border-color: var(--tq-red); }
.tsk-c.just { box-shadow: 0 0 0 2px var(--border-focus); }
.sheet .tsk-c button { min-height: 0; padding: 0; font-size: inherit; }
.tsk-row { display: flex; align-items: flex-start; gap: 4px; }
.sheet .tsk-c .tsk-b { flex: 1; min-width: 0; display: block; padding: 12px 4px 12px 16px; }
.tsk-c:has(.tsk-m) .tsk-b { padding-bottom: 4px; }
.tsk-t { display: block; font-size: calc(15px * var(--fz, 1)); font-weight: 600; line-height: 1.35; color: var(--text-primary); overflow-wrap: anywhere; }
.tsk-c.t-g .tsk-t { color: var(--text-secondary); text-decoration: line-through; text-decoration-color: var(--text-muted); font-weight: 500; }
.tsk-n { display: block; margin-top: 3px; font-size: calc(14px * var(--fz, 1)); color: var(--text-secondary); line-height: 1.35; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tsk-m { display: flex; flex-wrap: wrap; align-items: center; gap: 2px 10px; padding: 0 12px 10px 16px; font-size: calc(12.5px * var(--fz, 1)); color: var(--text-muted); }
.tsk-m .over { color: var(--tq-red); font-weight: 600; } .tsk-m .wait { color: var(--tq-orange); font-weight: 600; }
.sheet .tsk-c .tsk-chat { display: inline-flex; align-items: center; gap: 4px; width: auto; color: var(--accent-primary); font-size: inherit; min-height: 24px; max-width: 100%; }
.sheet .tsk-c .tsk-chat .i { width: 14px; height: 14px; color: inherit; }
.tsk-chat span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tsk-acts { display: flex; flex: none; align-items: center; padding: 6px 6px 0 0; }
.sheet .tsk-acts button { width: 40px; height: 40px; justify-content: center; border-radius: 10px; }
.sheet .tsk-acts button:hover { background: var(--bg-subtle); }
.tsk-ok { display: grid; place-items: center; width: 22px; height: 22px; border-radius: 50%; border: 1.8px solid var(--text-muted); }
.tsk-ok .i { width: 14px; height: 14px; opacity: 0; }
.sheet .tsk-acts button:hover .tsk-ok .i { opacity: .6; }
.tsk-c.t-g .tsk-ok { background: var(--tq-green); border-color: var(--tq-green); } .tsk-c.t-g .tsk-ok .i { opacity: 1; color: var(--bg-surface); }
.tsk-empty { margin: 8px 16px 12px; padding: 18px 16px; border: 1px dashed var(--border-subtle); border-radius: 12px; color: var(--text-secondary); text-align: center; font-size: calc(14px * var(--fz, 1)); }`;
function styles() {
  if (!document.getElementById("tasksSideCss")) document.head.insertAdjacentHTML("beforeend", `<style id="tasksSideCss">${SIDE_CSS}\n${CARD_CSS}</style>`);
}
function card(t) {
  const g = taskGroup(t), ch = chatName(t), due = dueText(t);
  const meta = [due && `<span class="${t.overdue ? "over" : ""}">${esc(due)}</span>`,
    t.status === "waiting" && '<span class="wait">ждёт вас</span>', t.status === "doing" && "<span>в работе</span>",
    t.kind !== "other" && `<span>${esc(KIND_T[t.kind] || "")}</span>`,
    t.status === "done" && t.done_at && `<span>сделано ${esc(when(t.done_at))}</span>`,
    ch && (t.chat_now ? `<button type="button" class="tsk-chat" data-chat="${esc(t.id)}" aria-label="Открыть чат «${esc(ch)}»">${ic("chat")}<span>из чата «${esc(ch)}»</span></button>`
      : `<span>из чата «${esc(ch)}»</span>`)].filter(Boolean);
  return `<div class="tsk-c t-${tone(t)}" data-id="${esc(t.id)}" data-g="${g}"><div class="tsk-row">
    <button type="button" class="tsk-b" data-go="${esc(t.id)}"><span class="tsk-t">${esc(t.title)}</span>${t.next && t.status !== "done" ? `<span class="tsk-n">${esc(t.next)}</span>` : ""}</button>
    <span class="tsk-acts"><button type="button" data-done="${esc(t.id)}" aria-label="${t.status === "done" ? "Вернуть в работу" : "Готово"}" title="${t.status === "done" ? "Вернуть в работу" : "Готово"}"><i class="tsk-ok">${ic("check")}</i></button><button type="button" data-more="${esc(t.id)}" aria-label="Действия с задачей">${ic("more")}</button></span></div>${meta.length ? `<div class="tsk-m">${meta.join("")}</div>` : ""}</div>`;
}
function tasksSheet(keep) {
  const all = TASKS.filter(mine), open = all.filter((t) => t.status !== "done");
  const f = folds(), by = Object.fromEntries(GROUPS.map(([k]) => [k, []]));
  for (const t of all) (by[taskGroup(t)] || by.later).push(t);
  let body = "";
  for (const [k, title] of GROUPS) {
    const list = k === "done" ? by[k].slice(0, 30) : by[k];
    if (!by[k].length) continue;
    const off = folded(k, f);
    body += `<button type="button" class="tsk-g${off ? " off" : ""}${k === "urgent" ? " r" : ""}" data-fold="${k}" aria-expanded="${!off}">${ic("chev")}<span>${title}</span><em>${by[k].length}</em></button>`;
    if (!off) body += `<div class="tsk-list">${list.map(card).join("")}</div>`;
  }
  styles();
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.tasks");
  bg.innerHTML = `<div class="sheet tsk" role="dialog" aria-label="Задачи" data-tasks="1"><h3>Задачи${open.length ? " · не решено " + open.length : ""}</h3>
    <form class="tsk-add" autocomplete="off">${ic("plus")}<input id="tskNew" maxlength="200" placeholder="Добавить задачу" aria-label="Новая задача — Enter, чтобы добавить" enterkeyhint="done"><button type="button" class="tsk-due" data-due aria-label="Срок — по желанию" title="Срок — по желанию">${ic("cal")}<span></span></button><input id="tskDue" type="date" tabindex="-1" aria-hidden="true"><button type="submit" aria-label="Добавить">${ic("plus")}</button></form>
    ${open.length ? "" : `<p class="tsk-empty">Всё решено. Скажите агенту в чате «добавь задачу …» — она появится здесь.</p>`}
    ${body}<button class="cancel" data-close>Закрыть</button></div>`;
  document.body.append(bg);
  const sh = bg.firstElementChild, byId = (id) => TASKS.find((x) => x.id === id);
  bg.addEventListener("click", (e) => {
    if (e.target === bg || e.target.closest("[data-close]")) return bg.remove();
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.fold) return fold(b.dataset.fold);
    if (b.dataset.due != null) { const d = bg.querySelector("#tskDue"); try { d.showPicker(); } catch (er) { d.focus(); } return; }
    if (b.dataset.chat) { const t = byId(b.dataset.chat); Y = sh.scrollTop; bg.remove(); return t && openSession(t.chat_now); }
    if (b.dataset.done) { const t = byId(b.dataset.done); Y = sh.scrollTop;
      return t && taskSet(t, { status: t.status === "done" ? "todo" : "done" }, t.status === "done" ? "Задача снова в работе" : "Готово"); }
    if (b.dataset.more) { const t = byId(b.dataset.more); Y = sh.scrollTop; bg.remove(); sheetFrom = null; return t && taskSheet(t); }
    if (b.dataset.go) { const t = byId(b.dataset.go); return t && taskGo(t); }
  });
  bg.querySelector("#tskDue").addEventListener("change", (e) => { bg.querySelector(".tsk-due span").textContent = e.target.value ? "до " + dayName(e.target.value) : ""; });
  bg.querySelector(".tsk-add").addEventListener("submit", (e) => { e.preventDefault(); taskQuick(bg); });
  if (split()) bg.classList.add("side");
  if (keep) sh.scrollTop = Y;
  sh.addEventListener("scroll", () => { Y = sh.scrollTop; }, { passive: true });
  if (JUST) {                                          // только что изменённая задача — подсветка на месте
    const c = [...sh.querySelectorAll(".tsk-c")].find((x) => x.querySelector(".tsk-t")?.textContent === JUST);
    JUST = "";
    if (c) { c.classList.add("just"); setTimeout(() => c.classList.remove("just"), 2400);
      if (c.offsetTop < sh.scrollTop || c.offsetTop > sh.scrollTop + sh.clientHeight - 40) c.scrollIntoView({ block: "center" }); }
  } else if (!keep && !matchMedia("(pointer: coarse)").matches) sh.querySelector("#tskNew").focus();
}
// «Добавить задачу» сверху: одна строка + Enter, срок — по желанию. Открыт чат — задача привязана к нему.
async function taskQuick(bg) {
  const inp = bg.querySelector("#tskNew"), due = bg.querySelector("#tskDue").value, title = inp.value.trim();
  if (!title) return inp.focus();
  const inChat = current && view === "session";
  try {
    await api("/api/tasks/add", { title, kind: "other", next: inChat ? "продолжить в чате" : "решить, с чего начать", ...(due ? { due } : {}),
      ...(inChat ? { chat: current, sid: cur()?.sid || "", chat_title: (cur()?.title || cur()?.name || "").slice(0, 80) } : {}) });
    haptic("notificationOccurred", "success");
    JUST = title; await tasksLoad(); tasksCount(); back();
    document.getElementById("tskNew")?.focus();
  } catch (e) { toast("Не добавлено: " + e.message, 4500); }
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
  if (t.chat_now) a.push({ label: "Открыть чат «" + chatName(t) + "»", icon: "chat", sub: "откуда пришла задача", run: () => t.chat_now !== current && openSession(t.chat_now) });
  if (!t.chat_now) a.push({ label: "Продолжить в чате", icon: "chat", sub: "новый чат — задача уже в поле ввода", run: () => {   // чата нет — новый
    document.querySelectorAll(".sheet-bg").forEach((x) => x.remove());
    chatWith(["Задача: " + t.title, t.next && "Дальше: " + t.next, t.due && "Срок: " + t.due, t.link && "Источник: " + t.link].filter(Boolean).join("\n") + "\n");
  } });
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

function taskNew() {                                   // «Добавить задачу» — поле сверху списка
  tasksOpen().then(() => document.getElementById("tskNew")?.focus());
}

Object.assign(window, { tasksOpen, taskSheet, tasksLoad, taskNew });
