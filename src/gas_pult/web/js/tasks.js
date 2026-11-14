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

async function tasksLoad() {
  TASKS = (await api("/api/tasks")).tasks || [];
  return TASKS;
}

async function tasksOpen() {
  try { await tasksLoad(); } catch (e) { return toast("Задачи: " + e.message, 4500); }
  tasksSheet();
}

function tasksSheet() {
  const open = TASKS.filter((t) => t.status !== "done"), done = TASKS.filter((t) => t.status === "done");
  helpSheet("sheet.tasks");
  const rows = [];
  for (const q of [1, 0, 2, 3, 4]) {                    // сервер уже отсортировал: внутри квадранта — «ждёт вас» первыми
    const g = open.filter((t) => (t.q || 0) === q);
    if (!g.length) continue;
    rows.push({ head: `${Q_T[q]} · ${g.length}` });
    rows.push(...g.map((t) => ({ label: t.title, icon: KIND_IC[t.kind] || "tasks", danger: q === 1,
      sub: [ST_T[t.status], KIND_T[t.kind], t.due ? (t.overdue ? "просрочено: " : "срок ") + t.due : "", "дальше: " + (t.next || "—"),
        t.chat_name ? "чат «" + t.chat_name + "»" : ""].filter(Boolean).join(" · "),
      run: () => taskGo(t) })));
  }
  sheet(`Задачи · не решено ${open.length}`, [
    ...(open.length ? [] : [{ info: true, icon: "check", label: "Всё решено", sub: "агенты ставят задачи командой gas-pult task add" }]),
    ...rows,
    { label: "Добавить задачу", icon: "plus", run: () => taskNew() },
    ...(done.length ? [{ head: `Выполнено · ${done.length}` },
      ...done.slice(0, 15).map((t) => ({ label: t.title, icon: "check", sub: "выполнено" + (t.done_at ? " · " + when(t.done_at) : ""), run: () => taskSheet(t) }))] : []),
  ]);
}

const when = (ts) => new Date(ts * 1000).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

async function taskGo(t) {                            // «провалиться»: чат задачи и карточка поверх него
  document.querySelectorAll(".sheet-bg").forEach((x) => x.remove());
  if (t.chat_now && t.chat_now !== current) await openSession(t.chat_now);
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
    for (const o of t.options || []) a.push({ label: o, icon: "check", sub: t.chat_now ? "ответ уйдёт в чат «" + t.chat_name + "» дословно" : "чата задачи нет — только отметить", run: () => taskDecide(t, o) });
  }
  if (t.link) a.push({ label: "Открыть источник", icon: "ext", sub: t.link, run: () => openUrl(t.link) });
  if (t.chat_now && t.chat_now !== current) a.push({ label: "Открыть чат «" + t.chat_name + "»", icon: "chat", run: () => openSession(t.chat_now) });
  a.push(t.status === "done" ? { label: "Вернуть в работу", icon: "refresh", run: () => taskSet(t, { status: "todo" }, "Задача снова в работе") }
    : { label: "Отметить выполненным", icon: "check", run: () => taskSet(t, { status: "done" }, "Выполнено") });
  if (t.status !== "done") a.push({ label: "Срочность и важность…", icon: "bolt", sub: Q_SHORT[t.q || 0], run: () => taskQ(t) },
    { label: "Что сделать дальше…", icon: "edit", sub: t.next, run: () => taskNext(t) },
    ...(t.status !== "waiting" ? [{ label: "Ждёт меня", icon: "wait", run: () => taskSet(t, { status: "waiting" }, "Поставил первой в списке") }] : []));
  a.push({ label: "Удалить задачу", icon: "trash", danger: true, run: () => taskSet(t, null, "Задача удалена") });
  helpSheet("sheet.tasks");
  sheet(t.title, [{ info: true, icon: KIND_IC[t.kind] || "tasks", label: "Дальше: " + (t.next || "—"),
    sub: [Q_SHORT[t.q || 0], ST_T[t.status], KIND_T[t.kind], t.due ? "срок " + t.due : "", t.by ? "поставил: " + t.by : "", t.result ? "последний запуск: код " + t.result.code : ""].filter(Boolean).join(" · ") }, ...a]);
}

function taskQ(t) {                                     // квадрант руками: 1–4
  sheet("Срочность и важность", [1, 2, 3, 4].map((q) => ({ label: Q_T[q], icon: q === (t.q || 0) ? "check" : "bolt",
    run: () => taskSet(t, { q }, "Записал: " + Q_SHORT[q]).then(() => tasksSheet()) })));
}

async function taskSet(t, upd, ok) {
  try {
    if (upd) await api("/api/tasks/update", { id: t.id, ...upd }); else await api("/api/tasks/remove", { id: t.id });
    toast(ok); haptic("notificationOccurred", "success");
    await tasksLoad(); tasksCount(); refreshShared();
  } catch (e) { toast("Не вышло: " + e.message, 4500); }
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
        toast("Задача добавлена"); await tasksLoad(); tasksCount(); tasksSheet();
      } catch (e) { toast("Не добавлено: " + e.message, 4500); }
    }));
}

Object.assign(window, { tasksOpen, taskSheet, tasksLoad });
