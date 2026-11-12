// ---------- главная: статус всех сессий за 3 секунды ----------
function setHome(v) {
  if (v === "projects") { setMode("projects"); v = "sessions"; }   // «Проекты» — главная (docs/PROJECTS.md, вопрос 8)
  homeView = v;
  const pm = v === "sessions" && projMode(), inProj = pm && !!proj;
  $("projSegBtn").hidden = !projOn();
  document.querySelectorAll("#homeSeg button").forEach((b) => b.classList.toggle("on", b.dataset.v === (pm ? "projects" : v)));
  $("sessionsView").hidden = v !== "sessions" || pm; $("projectsView").hidden = !pm; $("integrationsView").hidden = v !== "integrations";
  $("newBtn").innerHTML = ic("newsess") + (inProj ? "Новая сессия в проекте" : "Новая сессия");
  renderSetup();
  $("commandsView").hidden = v !== "commands";
  $("homeBar").hidden = !(view === "home" && v === "sessions");
  const two = split();
  if (view === "home") {                               // вложенный экран — его имя в шапке, «Пульт» — на главной
    const sub = (v !== "sessions" || inProj) && !two;
    $("title").textContent = sub ? (inProj ? projOf(proj)?.name || "Проект" : { commands: "Команды", integrations: "Интеграции" }[v]) : "Пульт";
    $("title").classList.toggle("brand-text", !sub); noDup();
    $("homeSeg").hidden = sub;                         // на вложенном экране — «‹ Назад», а не вкладки
  }
  syncBack();
  if (v === "integrations") loadMcp(); else if (v === "commands") loadCommands(); else refresh();
}
$("homeSeg").onclick = (e) => {
  const b = e.target.closest("button"); if (!b) return;
  if (b.dataset.v === "sessions" && projOn()) setMode("sessions");   // «Сессии» — плоский список окон, как раньше
  setHome(b.dataset.v);
};

const seenKey = (s) => "seen:" + s.id + ":" + s.path;
function isNew(s) {                                   // журнал изменился с тех пор, как вы последний раз открывали сессию
  const seen = store(seenKey(s));
  if (seen == null) { if (s.rev) store(seenKey(s), s.rev); return false; }
  return s.status === "idle" && s.rev && s.rev !== seen;
}
// Поставщик модели сессии (models.py): у обычных сессий Claude метки нет — не шумим.
const profileOf = (id) => meta?.profiles?.find((p) => p.id === id);
const provName = (s) => s.profile && s.profile !== "claude" ? (profileOf(s.profile)?.short || s.profile) : "";
const provChip = (s) => provName(s) ? `<span class="chip prov">${esc(provName(s))}</span>` : "";
const ctxUsed = (s) => s.context == null ? null : 100 - s.context;       // сервер отдаёт «свободно %»
function ctxMeter(s) {
  const u = ctxUsed(s);
  return u == null ? "" : `<span class="ctx ${u > 70 ? "warn" : ""}" title="${u > 70 ? "Контекст почти заполнен — пора /compact" : "Заполнение контекста"}">Контекст: ${u}%<span class="bar"><i style="width:${u}%"></i></span></span>`;
}
// ---------- «изменена N назад» (ago.py — те же правила и словари ago.*; тест сверяет обе реализации) ----------
// Шкала: до 5 с — «только что», дальше секунды, минуты, часы, «вчера» (до двух суток), дни, недели, месяцы, дата.
// Текст обновляется на месте (agoTick из общего секундного тика): раз в секунду, пока что-то изменилось меньше минуты
// назад, иначе раз в 30 с.
const AGO_STEPS = [[5, "now"], [60, "s"], [3600, "min"], [86400, "h"], [172800, "yesterday"], [604800, "d"], [2592000, "w"], [31536000, "mo"]];
const AGO_UNIT = {"s": 1, "min": 60, "h": 3600, "d": 86400, "w": 604800, "mo": 2592000};
const AGO_STALE = 604800;
let agoSkew = 0;                                      // часы сервера − часы браузера (из /api/sessions)
const nowSec = () => Date.now() / 1000 + agoSkew;
function agoPlural(n) {                               // ru: 1 минуту · 2 минуты · 5 минут; en: 1 minute · 2 minutes
  n = Math.abs(Math.trunc(n));
  if (LANG !== "ru") return n === 1 ? "one" : "many";
  return n % 10 === 1 && n % 100 !== 11 ? "one" : n % 10 >= 2 && n % 10 <= 4 && !(n % 100 >= 12 && n % 100 <= 14) ? "few" : "many";
}
function agoParts(ts) {                               // местный часовой пояс браузера
  const d = new Date(ts * 1000), p = (x) => String(x).padStart(2, "0");
  return { d: p(d.getDate()), m: p(d.getMonth() + 1), y: String(d.getFullYear()), t: `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}` };
}
function agoText(ts, now = nowSec(), full = false) {
  if (!ts || !DICT["ago.now"]) return "";
  const sec = Math.max(0, Math.trunc(now - ts));
  for (const [lim, u] of AGO_STEPS) {
    if (sec >= lim) continue;
    if (u === "now" || u === "yesterday") return T("ago." + u);
    const n = Math.floor(sec / AGO_UNIT[u]);
    return T(full ? `ago.${u}.${agoPlural(n)}` : "ago." + u, { n });
  }
  return T("ago.date", agoParts(ts));
}
function agoExact(ts, now = nowSec()) {
  if (!ts || !DICT["ago.now"]) return "";
  return T(new Date(ts * 1000).getFullYear() === new Date(now * 1000).getFullYear() ? "ago.exact" : "ago.exact.year", agoParts(ts));
}
const isStale = (s) => !!s.changed && s.status !== "dialog" && nowSec() - s.changed > AGO_STALE;
// Ждущие ответа (и пауза по расходу) — сверху, дальше — по последнему изменению; без времени — в конце.
const byChange = (a, b) => (a.status === "dialog" || a.cost_paused ? 0 : 1) - (b.status === "dialog" || b.cost_paused ? 0 : 1)
  || (b.changed || 0) - (a.changed || 0) || (b.active - a.active);
// Ответ агента и ваше сообщение — отдельно, если по шкале они не совпадают с последним изменением.
function agoLabel(x, now) {
  if (!x.full) return agoText(+x.ago, now);
  const main = agoText(+x.ago, now, true), out = [T("ago.changed", { ago: main })];
  for (const k of x.more ? ["said", "asked"] : []) if (+x[k] && agoText(+x[k], now, true) !== main) out.push(T("ago." + k, { ago: agoText(+x[k], now, true) }));
  return main ? out.join(" · ") : "";
}
function agoTip(x) {                                  // подсказка и тап: точное время всех трёх отметок
  return [["changed", x.ago], ["said", x.said], ["asked", x.asked]].filter(([, t]) => +t).map(([k, t]) => T("ago.tip." + k, { at: agoExact(+t) })).join("\n");
}
function agoSpan(s, head = false) {                    // шапка на широком экране — полные слова, ответ и сообщение
  if (!s.changed) return "";
  queueMicrotask(agoTick);
  const full = head && split();                       // на телефоне шапка узкая — короткая форма, подробности по тапу
  const x = { ago: s.changed, said: s.said || 0, asked: s.asked || 0, full: full ? "1" : "", more: full ? "1" : "" };
  const d = Object.entries(x).filter(([, v]) => v !== "").map(([k, v]) => ` data-${k}="${esc(v)}"`).join("");
  return `<span class="ago"${d} title="${esc(agoTip(x))}">${esc(agoLabel(x, nowSec()))}</span>`;
}
function agoTick() {
  agoTick.at = Date.now();
  const now = nowSec(); let fast = false;
  for (const el of document.querySelectorAll(".ago[data-ago]")) {
    if (el.closest("[hidden]")) continue;              // скрытый экран (главная под сессией на телефоне) — не трогаем
    if (now - +el.dataset.ago < 60) fast = true;
    const tx = agoLabel(el.dataset, now), tip = agoTip(el.dataset);
    if (el.textContent !== tx) el.textContent = tx;     // только текст: без перерисовки карточки и мигания
    if (el.title !== tip) el.title = tip;
  }
  for (const el of document.querySelectorAll(".chip.stale")) {     // карточка могла нарисоваться до словаря
    if (el.textContent !== T("ago.stale")) { el.textContent = T("ago.stale"); el.title = T("ago.stale.tip"); }
  }
  agoTick.fast = fast;
}
// Тап (на телефоне подсказки нет) — точное время всплывающим сообщением; карточку при этом не открываем.
document.addEventListener("click", (e) => {
  const a = e.target.closest?.(".ago[data-ago]");
  if (!a || !a.title) return;
  e.stopPropagation(); e.preventDefault(); toast(a.title, 4000);
}, true);
// «Закрепить» (проект, сессия, чат): закреплённые — своей группой наверху, последний закреплённый первым; хранится на
// сервере (projects.json) — одинаково на телефоне и в браузере. Меню — «⋯» на карточке или долгое нажатие.
const pinTs = (x) => +(x.pinned_at || x.pinned || 0);  // проект: pinned_at; сессия и чат: pinned — время закрепления
const pinMark = (x) => x.pinned ? `<span class="pinmark" title="Закреплено">${ic("pin")}</span>` : "";
const pinFirst = (list) => [...list.filter((x) => x.pinned).sort((a, b) => pinTs(b) - pinTs(a)), ...list.filter((x) => !x.pinned)];
function pinGroups(list, draw) {
  const top = list.filter((x) => x.pinned).sort((a, b) => pinTs(b) - pinTs(a)), rest = list.filter((x) => !x.pinned);
  if (!top.length) return rest.map(draw).join("");
  return `<div class="pin-h">${ic("pin")}<span>Закреплённые</span></div>` + top.map(draw).join("")
    + (rest.length ? `<div class="pin-h"><span>Остальные</span></div>` + rest.map(draw).join("") : "");
}
const pinItem = (x, body, name) => ({ label: x.pinned ? "Открепить" : "Закрепить", icon: "pin", sub: x.pinned ? "убрать из закреплённых" : "наверху вашего списка — на телефоне и в браузере", run: () => pinSet(body, !x.pinned, name) });
async function pinSet(body, on, name) {
  try {
    await api("/api/pin", { ...body, on }); toast((on ? "Закреплено: " : "Откреплено: ") + (name || ""), 2500);
    await refresh(); if (proj && projTab === "done") loadDone();
  } catch (e) { toast("Не вышло: " + e.message, 4500); }
}
function projSheet(id) {                              // «⋯» и долгое нажатие на проекте
  const p = projOf(id); if (!p) return;
  helpSheet("sheet.project");
  sheet(p.name, [
    { label: "Открыть", icon: "folder", run: () => openProject(id) },
    ...(meta?.role !== "viewer" ? [pinItem(p, { project: id }, p.name)] : []),
    ...(meta?.role === "owner" && !FOCUS ? [{ label: "Создать фокус-ссылку на проект", icon: "qr", sub: "одно устройство: все сессии проекта, без входа в пульт", run: () => focusLink(null, id) },
      { label: "Создать демо-ссылку", icon: "eye", sub: "несколько устройств, только просмотр и выбор вариантов", run: () => focusLink(null, id, "demo") }] : []),
  ]);
}
// Долгое нажатие на карточке (телефон) и правая кнопка мыши — меню этой карточки, как «⋯».
let cardHold = null, cardHeldAt = 0, cardSwallow = false;
function cardMenu(el) {
  if (Date.now() - cardHeldAt < 800) return true;      // долгое нажатие и contextmenu одного касания — одно меню
  const c = el.closest(".card[data-id], .card[data-proj], .card[data-chat]"); if (!c) return false;
  cardHeldAt = Date.now(); cardSwallow = true; haptic("impactOccurred", "medium");
  if (c.dataset.id) sessionSheet(c.dataset.id); else if (c.dataset.proj) projSheet(c.dataset.proj); else chatSheet(c.dataset.chat);
  return true;
}
$("home").addEventListener("pointerdown", (e) => {
  cardSwallow = false;                                 // новое касание — прежнее меню уже не в счёт
  if (e.pointerType === "mouse" || !e.target.closest(".card[data-id], .card[data-proj], .card[data-chat]") || e.target.closest("button")) return;
  const t = e.target; cardHold = { x: e.clientX, y: e.clientY, t: setTimeout(() => { cardHold = null; cardMenu(t); }, 550) };
});
const cardUnhold = () => { if (cardHold) clearTimeout(cardHold.t); cardHold = null; };
for (const ev of ["pointerup", "pointercancel"]) $("home").addEventListener(ev, cardUnhold);
$("home").addEventListener("pointermove", (e) => { if (cardHold && Math.hypot(e.clientX - cardHold.x, e.clientY - cardHold.y) > 10) cardUnhold(); });
$("home").addEventListener("contextmenu", (e) => { if (e.target.closest(".card[data-id], .card[data-proj], .card[data-chat]") && !e.target.closest("a")) { e.preventDefault(); cardUnhold(); cardMenu(e.target); } });
$("home").addEventListener("click", (e) => { if (cardSwallow && e.target.closest(".card")) { cardSwallow = false; e.stopPropagation(); e.preventDefault(); } }, true);   // отпустили после меню — карточку не открываем
function card(s, chat) {                              // chat — в проекте: второй строкой название чата
  const st = ST[s.status], old = isStale(s), sub = chat && s.title && s.title !== s.name ? `<div class="meta ctitle">«${esc(s.title)}»</div>` : "";
  return `<div class="card ${st.cls}${s.active ? " active" : ""}${old ? " stale" : ""}${split() && s.id === current ? " current" : ""}" data-id="${esc(s.id)}" role="button" tabindex="0" aria-label="${esc(s.name)}, ${st.label}">
    <div class="row"><span class="sdot"></span>
      <div class="ctext"><div class="name">${pinMark(s)}${esc(s.name)}</div>${sub}<div class="meta">${esc(folder(s.path))}${s.branch && s.branch !== "HEAD" ? " · " + esc(s.branch) : ""}${s.model ? " · " + esc(s.model) : ""}</div></div>
      ${agoSpan(s)}<button class="kebab" data-more-s="${esc(s.id)}" aria-label="Действия с сессией">${ic("more")}</button></div>
    ${s.preview ? `<div class="preview">${esc(s.preview)}</div>` : ""}
    <div class="cfoot"><span class="chip ${st.cls}">${st.label}</span>${provChip(s)}${isNew(s) ? '<span class="chip new">новый ответ</span>' : ""}${s.active ? '<span class="chip accent">активная в чате</span>' : ""}${spaceChips(s)}${schedChip(s)}${old ? `<button class="chip stale" data-more-s="${esc(s.id)}" title="${esc(T("ago.stale.tip"))}">${esc(T("ago.stale"))}</button>` : ""}${costChip(s)}
      ${ctxMeter(s)}</div>
    ${costBar(s)}${reposLine(s)}
    ${s.status === "dialog" ? `<button class="btn approval sm reply" data-reply="${esc(s.id)}">Ответить</button>` : ""}
    ${s.status === "stopped" && meta?.role !== "viewer" ? `<button class="btn quiet sm reply" data-revive="${esc(s.id)}">${ic("refresh", "s16")}Перезапустить — продолжить разговор</button>` : ""}</div>`;
}
// ---------- демо-пространства (задача 31, docs/TENANTS.md) ----------
// Владелец видит окна пространств отдельной группой «Пространства»: читает, пишет, отвечает («Подключиться» —
// тестировщик увидит «Владелец подключился»), ставит задачу новой сессией. Тестировщик видит только своё.
let spacesInfo = null;                                // /api/spaces (владельцу): включено ли и какие есть
// Расписание пространства из модуля (задача 39): «🗓 по будням 10:00, 17:00 · следующий: завтра 10:00» — переключатель.
function schedWhen(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000), now = new Date(), day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(d) - day(now)) / 86400000), hm = d.toTimeString().slice(0, 5);
  return (diff === 0 ? "сегодня" : diff === 1 ? "завтра" : d.toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "short" })) + " " + hm;
}
function schedLabel(sc) {
  return sc.state === "on" ? (sc.next ? "следующий запуск: " + schedWhen(sc.next) : "по расписанию") : sc.state === "paused" ? "приостановлено" : "выключено";
}
function schedChip(s) {
  const sc = s.schedule; if (!sc) return "";
  return `<button class="chip sched${sc.state === "on" ? "" : " off"}" data-sched="${esc(s.id)}" title="${esc("Расписание: " + sc.text)}">${ic("cal")}${esc(schedLabel(sc))}</button>`;
}
function scheduleSheet(s, after) {
  const sc = s.schedule; if (!sc) return;
  const set = async (state) => {
    try { const r = await api("/api/module/schedule", { w: s.id, state }); s.schedule = r; toast(state === "on" ? "Расписание включено: " + schedLabel(r) : state === "paused" ? "Расписание приостановлено — включите, когда нужно" : "Расписание выключено", 4500); refresh(); after?.(); }
    catch (e) { toast(e.message, 5000); }
  };
  helpSheet("sheet.schedule");
  sheet(`Расписание «${s.name}»`, [
    { info: true, icon: "cal", label: sc.text, sub: sc.state === "on" ? schedLabel(sc) : sc.state === "paused" ? "приостановлено: агент не запускается, пока не включите" : "выключено: агент сам не запускается" },
    { label: "Включено", icon: "play", on: sc.state === "on", sub: "агент запускается сам в это время", run: () => set("on") },
    { label: "Приостановить", icon: "pause", on: sc.state === "paused", sub: "не запускать, пока не включу", run: () => set("paused") },
    { label: "Выключить", icon: "x", on: sc.state === "off", sub: "сам больше не запускается; включить можно здесь же", run: () => set("off") },
  ]);
}
// «Удалить» сессию модуля: расписание выключается навсегда, папка — в корзину пульта; второе подтверждение — именем папки.
function moduleDelete(s) {
  const name = (s.path || "").split("/").pop();
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.module-delete");
  bg.innerHTML = `<div class="sheet" role="dialog"><h3>Удалить «${esc(name)}»?</h3>
    <p class="note" style="margin:4px 16px 8px">Сессия закроется, расписание агента выключится навсегда, папка с файлами уйдёт в корзину пульта (вернуть — перенести обратно). Чтобы удалить, введите имя папки: <b>${esc(name)}</b></p>
    <div class="field" style="margin:0 16px"><input id="mdName" autocomplete="off" autocapitalize="off" spellcheck="false"></div>
    <div class="row2"><button class="btn ghost" data-close>Отмена</button><button class="btn danger" id="mdOk" disabled>Удалить</button></div></div>`;
  document.body.append(bg);
  const inp = $("mdName"), ok = $("mdOk"); inp.focus();
  inp.oninput = () => { ok.disabled = inp.value.trim() !== name; };
  ok.onclick = () => busy(ok, "Удаляю…", async () => {
    try { const r = await api("/api/module/delete", { w: s.id, confirm: inp.value.trim() }); bg.remove(); toast("Удалено, расписание выключено. Папка — в " + r.trash, 6000); if (s.id === current) back(); else refresh(); }
    catch (e) { toast(e.message, 5000); }
  });
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) bg.remove(); });
}
function spaceChips(s) {
  if (!s.space) return "";
  return (meta?.role === "owner" ? `<span class="chip space" title="Сессия демо-пространства">${ic("flask")}${esc(s.space_title || s.space)}</span>` : "")
    + (s.owner_here && meta?.role !== "owner" ? '<span class="chip accent">Владелец подключился</span>' : "");
}
function spacesGroup(list) {                          // группа под своими сессиями — только владельцу
  if (meta?.role !== "owner" || (!list.length && !spacesInfo?.tenants?.length)) return "";
  return `<div class="sec-h space-h">${ic("flask")}<span>Пространства</span>${spacesInfo?.tenants?.length ? '<button class="chip" data-space-invite>' + ic("mail") + "Пригласить</button>" + '<button class="chip" data-space-task>' + ic("plus") + "Поставить задачу</button>" + '<button class="chip" data-space-closed>' + ic("folder") + "Закрытые</button>" : ""}</div>`
    + (spacesInfo?.tenants || []).filter((x) => x.budget).map((x) => `<div class="note space-bud${x.budget.pct >= 0.8 ? " warn" : ""}"><b>${esc(x.title || x.slug)}</b> — ${esc(x.budget.text)} <button class="chip" data-space-add="${esc(x.slug)}">${ic("plus")}${esc(T("bud.add"))}</button></div>`).join("")
    + (list.length ? list.map(card).join("") : '<div class="empty">В пространствах сессий пока нет.</div>');
}
async function loadSpaces() {
  if (meta?.role !== "owner") return;
  try { spacesInfo = await api("/api/spaces"); } catch (e) { spacesInfo = null; }
}
async function callHelp(id) {                        // тестировщик: владельцу — сессия и последний вопрос агента
  if (!id) return toast(T("s.sos.none"), 3500);
  try { await api("/api/help/call", { w: id }); toast(T("s.sos.sent"), 4500); haptic("notificationOccurred", "success"); }
  catch (e) { toast(e.message, 4500); }
}
async function spaceConnect(id) {
  try { await api("/api/space/connect", { w: id }); toast("Подключились — тестировщик видит «Владелец подключился»"); openSession(id); refresh(); }
  catch (e) { toast("Не вышло: " + e.message, 4000); }
}
function spaceInvite() {                              // ссылка на 24 часа: вход через Telegram — сразу тестировщик
  const list = (spacesInfo?.tenants || []).filter((t) => t.ready !== false);
  if (!list.length) return toast("Нет готовых пространств — docs/TENANTS.md", 4000);
  helpSheet("sheet.space-invite");
  sheet("Пригласить тестировщика — в какое пространство?", list.map((t) => ({ label: t.title, icon: "flask", run: async () => {
    try {
      inviteReady(await api("/api/invite/new", { space: t.slug }), t.title);
    } catch (e) { toast("Не вышло: " + e.message, 4000); }
  } })));
}
// ---------- лёгкий вход (задача 34): ссылка, QR и короткий код одного приглашения ----------
// QR — картинка с сервера (/api/invite/qr, PNG; владельцу — любого приглашения, человеку — своей ссылки входа).
function invQr(link) {
  return DEMO ? `<div class="inv-qr" role="img" aria-label="QR">${ic("qr")}</div>`
    : `<img class="inv-qr" alt="QR" src="/api/invite/qr?u=${encodeURIComponent(link)}">`;
}
function inviteReady(r, title, who) {             // владелец: приглашение (или ссылка входа человека) готово
  const link = location.origin + r.path, hint = r.hint || r.path.split("/").pop().slice(0, 6);
  copyText(link, "Ссылка скопирована");
  sSheet(hv("sheet.invite-ready"), who ? "Вход на другом устройстве: " + who : "Приглашение в «" + title + "»",
    `<p class="note">${who ? "Отправьте человеку ссылку или покажите QR — он откроет её на новом устройстве и сразу войдёт."
      : "Отправьте человеку ссылку или покажите QR — пусть наведёт камеру телефона. Можно продиктовать код: экран входа → «Есть код приглашения?». Telegram не нужен."}</p>
    ${invQr(link)}<div class="inv-codebig">${esc(r.code || "")}</div><div class="inv-url">${esc(link)}</div>
    <div class="scn-opts">${sChip(false, 'data-cp="link"', "Скопировать ссылку", ic("copy"))}${sChip(false, 'data-cp="code"', "Скопировать код", ic("copy"))}</div>
    <p class="note">24 часа, один вход: после него ссылка и код сгорают. Отозвать — gas-pult invite revoke ${esc(hint)}</p>`,
    (b) => { if (b.dataset.cp) copyText(b.dataset.cp === "code" ? r.code : link, b.dataset.cp === "code" ? "Код скопирован" : "Ссылка скопирована"); });
}
async function personDevice(p) {                  // владелец: ссылка для входа человека на другом устройстве
  try { inviteReady(await api("/api/invite/device", { id: p.id }), "", p.name || "ID " + p.id); }
  catch (e) { toast("Не вышло: " + e.message, 4000); }
}
// Человек в пространстве: «Вход с другого устройства» — Face ID на этом устройстве, ссылка для другого, а гость без
// Telegram — ещё и «Привязать Telegram». Открывается и из простого режима, поэтому строки — T().
const isGuest = () => meta?.uid != null && meta.uid <= -1e15;
async function deviceSheet() {
  let pk = false; try { pk = (await api("/api/login/methods")).passkey && passkeyOk(); } catch (e) { /* без ключей */ }
  const bg = sSheet(hv("settings.device"), T("dev.title"), `<p class="note">${esc(T("dev.note"))}</p>
    <div class="scn-opts">${pk ? sChip(false, 'data-pk="1"', T("dev.passkey"), ic("key")) : ""}${sChip(false, 'data-link="1"', T("dev.link"), ic("phone"))}${isGuest() ? sChip(false, 'data-tg="1"', T("dev.tg"), ic("send")) : ""}</div>
    ${isGuest() ? `<p class="note">${esc(T("dev.tg.note"))}</p>` : ""}<div id="devOut"></div>`, async (b) => {
    const out = $("devOut");
    if (b.dataset.cp) return copyText(b.dataset.cp, T("dev.copied"));
    if (b.dataset.pk) {
      try {
        const r = await api("/api/passkeys/options", {});
        const cred = await pkCall("create", pkCreation(r.options));
        await api("/api/passkeys/add", { id: r.id, credential: pkJson(cred), name: deviceName() });
        haptic("notificationOccurred", "success"); out.innerHTML = `<div class="result ok">${ic("check")}<span>${esc(T("dev.pk.done"))}</span></div>`;
      } catch (e) { out.innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(pkError(e))}</span></div>`; }
    }
    if (b.dataset.link) {
      try {
        const r = await api("/api/invite/device", {}), link = location.origin + r.path;
        out.innerHTML = `<p class="note">${esc(T("dev.link.ready"))}</p>${invQr(link)}<p class="note">${esc(T("dev.link.code"))}</p>
          <div class="inv-codebig">${esc(r.code)}</div><div class="inv-url">${esc(link)}</div><div class="scn-opts">${sChip(false, `data-cp="${esc(link)}"`, T("dev.copy"), ic("copy"))}</div>`;
      } catch (e) { out.innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`; }
    }
    if (b.dataset.tg) return linkTelegram(out, bg);
  });
}
async function linkTelegram(out, bg) {            // гость: тот же вход через бота (TgLogins), бот переносит запись
  try {
    const d = await api("/api/link/tg", {});
    tg?.initData ? tg.openTelegramLink(d.link) : window.open(d.link, "_blank");
    out.innerHTML = `<div class="result wait">${ic("wait")}<span>${esc(T("dev.tg.wait"))}</span></div>
      <a class="btn ghost" href="${esc(d.link)}" target="_blank" rel="noopener">${ic("ext")}${esc(T("dev.tg.again"))}</a>`;
    if (DEMO) return;
    const t0 = Date.now(), timer = setInterval(async () => {
      if (!bg.isConnected || Date.now() - t0 > d.ttl * 1000) return clearInterval(timer);
      try {
        const r = await api("/api/login/tg?id=" + encodeURIComponent(d.id));
        if (r.state === "wait") return;
        clearInterval(timer);
        if (r.state === "ok") { toast(T("dev.tg.done"), 3000); setTimeout(() => location.reload(), 800); }
        else out.innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(T("dev.tg.no"))}</span></div>`;
      } catch (e) { /* сеть моргнула — следующая попытка через 2 с */ }
    }, 2000);
  } catch (e) { out.innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`; }
}
function spaceTaskForm() {
  const list = (spacesInfo?.tenants || []).filter((t) => t.ready !== false);
  if (!list.length) return toast("Нет готовых пространств — docs/TENANTS.md", 4000);
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.space-task");
  bg.innerHTML = `<div class="sheet" role="dialog"><h3>Поставить задачу в пространстве</h3>
    <div class="field" style="margin:4px 16px 10px"><label for="stSpace">Пространство</label><select id="stSpace">${list.map((t) => `<option value="${esc(t.slug)}">${esc(t.title)}</option>`).join("")}</select></div>
    <div class="field" style="margin:0 16px 10px"><label for="stName">Название сессии — так её увидит тестировщик</label><input id="stName" maxlength="60" autocomplete="off" placeholder="Сверка счетов за октябрь"></div>
    <div class="field" style="margin:0 16px 0"><label for="stTask">Задание — первое сообщение агенту</label><textarea id="stTask" rows="4" placeholder="Разбери выгрузку в папке inbox и составь реестр"></textarea></div>
    <p class="note" id="stErr" style="margin:8px 16px 0">Сессия откроется в пространстве; задание уйдёт, как только агент будет готов.</p>
    <div class="row2"><button class="btn ghost" data-close>Отмена</button><button class="btn" id="stOk">Поставить</button></div></div>`;
  document.body.append(bg);
  $("stOk").onclick = () => busy($("stOk"), "Открываю…", async () => {
    try { const r = await api("/api/space/task", { space: $("stSpace").value, name: $("stName").value, task: $("stTask").value });
          bg.remove(); toast("Сессия «" + r.name + "» открыта в пространстве"); await refresh(); openSession(r.id); }
    catch (e) { $("stErr").textContent = e.message; $("stErr").style.color = "var(--status-danger)"; }
  });
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) bg.remove(); });
}
// «+ добавить» к запасу пространства (задача 35): неделя нормы, две недели, $10.
function budgetAdd(slug) {
  const t = (spacesInfo?.tenants || []).find((x) => x.slug === slug), d = t?.budget?.daily || 0;
  if (!t?.budget) return toast(T("bud.none"), 4000);
  sheet(T("bud.add.title", { n: t.title || slug }), [[7 * d, T("bud.add.week")], [14 * d, T("bud.add.2w")], [10, "$10"]].map(([v, label]) => ({
    label: label + (label.startsWith("$") ? "" : " — " + usd(v)), icon: "plus",
    run: async () => { try { const b = await api("/api/space/budget/add", { space: slug, usd: Math.round(v * 100) / 100 }); toast(T("bud.add.done", { l: usd(b.left) }), 4000); await loadSpaces(); refresh(); } catch (e) { toast(e.message, 5000); } },
  })));
}
