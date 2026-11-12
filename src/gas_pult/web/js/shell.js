// ---------- навигация ----------
function show(v) {
  const was = view;
  view = v; if (v !== "mcpForm") formBack = null;
  for (const id of ["login", "terms", "country", "persona", "home", "session", "mcpForm"]) $(id).hidden = id !== v;
  const gate = ["login", "terms", "country", "persona"].includes(v);   // вход, условия, страна, роль — без списка и меню
  const two = split() && !["terms", "country", "persona"].includes(v);  // одной колонкой, без списка сессий
  document.body.classList.toggle("split", two);
  if (DRAFT && (v !== "session" || current)) { DRAFT = null; paintDraft(); }   // ушли из нового чата
  applyWide(); renderRail(); queueMicrotask(agoTick);   // «N назад» на открывшемся экране — сразу свежие
  $("pick").hidden = true;                           // компьютер: без открытой сессии — главная в основной колонке
  $("dock").hidden = v !== "session";
  $("homeBar").hidden = !(v === "home" && !gate && homeView === "sessions");
  closePop(); navOpen(false); renderNav();
  placeNotices();
  syncBack();
  $("switchBtn").hidden = true;                       // переключатель — само имя сессии с ▾ (телефон) или список слева
  $("screenBtn").hidden = v !== "session" || two;
  $("title").classList.toggle("sw", v === "session" && !two);
  $("settingsBtn").hidden = gate;
  $("title").classList.toggle("brand-text", v === "home" || gate);   // «Пульт» — фирменным градиентом
  noDup();
  $("toBottom").hidden = true; voiceUi();           // ушли с сообщения — мини-плеер, вернулись — состояние в сообщении
  $("tabsBar").hidden = v !== "session" || !two;     // на компьютере — вкладки; на телефоне — кнопка «Экран» в шапке
  setBars(true); scrollToY(0);
  // телефон: сессия въезжает справа — когда её открыл человек (не при запуске панели сразу в последнюю сессию)
  if (v === "session" && was && was !== "session" && !two && !backDrag && navigator.userActivation?.hasBeenActive !== false) slideIn();
}
function slideIn() {
  for (const el of [$("session"), $("dock")]) {
    el.classList.remove("slide-in"); void el.offsetWidth; el.classList.add("slide-in");
    el.addEventListener("animationend", () => el.classList.remove("slide-in"), { once: true });
  }
}
// Свайп от левого края в сессии (телефон) — «назад»: экран идёт за пальцем, под ним главная; отпустили дальше трети
// или быстро — уезжает вправо и открывается главная, иначе возвращается. Панель чатов в сессии — по ☰ (navDrag
// от края работает на главной). Кадр — requestAnimationFrame, только transform.
let backDrag = null;
const backEls = () => [$("session"), $("dock")];
function backMove(e) {
  const d = backDrag; if (!d) return;
  const t = e.touches[0], dx = t.clientX - d.x, dy = t.clientY - d.y;
  if (!d.live) {
    if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
    if (Math.abs(dy) > Math.abs(dx) || dx < 0) return backEnd();
    d.live = true; swipe = null;
    document.documentElement.style.setProperty("--under-top", Math.max(0, $("top").getBoundingClientRect().bottom) + "px");
    document.body.classList.add("back-drag");
  }
  e.preventDefault(); d.dx = Math.max(0, dx); d.v = (dx - d.px) / Math.max(1, e.timeStamp - d.pt); d.px = dx; d.pt = e.timeStamp;
  if (!d.raf) d.raf = requestAnimationFrame(() => { d.raf = 0; backEls().forEach((el) => (el.style.transform = `translateX(${d.dx}px)`)); });
}
function backEnd() {
  const d = backDrag; backDrag = null;
  removeEventListener("touchmove", backMove); removeEventListener("touchend", backEnd); removeEventListener("touchcancel", backEnd);
  if (!d?.live) return;
  cancelAnimationFrame(d.raf);
  const go = d.dx > d.w / 3 || d.v > 0.4, b = document.body.classList;
  b.add("back-anim"); backEls().forEach((el) => (el.style.transform = go ? `translateX(${d.w}px)` : ""));
  const done = () => {
    b.remove("back-anim", "back-drag"); backEls().forEach((el) => (el.style.transform = ""));
    if (go && view === "session") { haptic("selectionChanged"); back(); }
  };
  matchMedia("(prefers-reduced-motion: reduce)").matches ? done() : setTimeout(done, 210);
}
addEventListener("touchstart", (e) => {
  if (backDrag || navDrag || view !== "session" || split() || FOCUS || e.touches.length !== 1 || NAV.open || document.querySelector(".sheet-bg, .pop")) return;
  const t = e.touches[0]; if (t.clientX > 24) return;
  backDrag = { x: t.clientX, y: t.clientY, w: innerWidth, live: false, dx: 0, px: 0, pt: e.timeStamp, v: 0, raf: 0 };
  addEventListener("touchmove", backMove, { passive: false }); addEventListener("touchend", backEnd); addEventListener("touchcancel", backEnd);
}, { passive: true });
// «‹ Назад» слева в шапке — на любом вложенном экране: сессия (телефон), форма подключения, вкладки главной
// «Команды» и «Интеграции» (телефон). Шапка прячется при прокрутке — кнопка вместе с ней; Telegram — своя кнопка.
// Атрибут hidden — только если меняется: опрос не трогает шапку (MutationObserver, перерисовка стилей).
function setHidden(el, on) { if (el.hidden !== on) el.hidden = on; }
// Компьютер, главная: «Пульт» уже в шапке панели чатов — заголовок «Пульт / хост» справа не дублируем (пункт 9).
function noDup() { document.body.classList.toggle("no-dup", view === "home" && split() && homeView !== "integrations"); }
function syncBack() {
  const two = split();
  const canBack = !FOCUS && view === "mcpForm" || (view === "session" && !two) || (view === "home" && !two && (homeView !== "sessions" || (projMode() && !!proj)));
  // телефон, сессия: слева ☰ — панель чатов (в ней и главная); Telegram сохраняет свою «Назад»
  setHidden($("backBtn"), !canBack || (view === "session" && !two && document.body.classList.contains("has-nav")));
  if (tg) canBack ? tg.BackButton.show() : tg.BackButton.hide();
}
function back() {
  if (FOCUS) return refresh();                      // в фокусе уходить некуда; сессию завершили — сервер ответит 410
  if (view === "home" && homeView === "sessions" && projMode() && proj) return closeProject();   // проект → все проекты
  if (view === "home" && homeView !== "sessions") { setHome("sessions"); return scrollToY(0); }
  if (view === "mcpForm") { clearInterval(connTimer); const f = formBack; formBack = null; if (f) return f(); show("home"); return setHome("integrations"); }
  current = null; closeMenu(); files = []; renderFiles(); show("home"); setHome("sessions");
}
// Шапка и поле ввода прячутся, как в Safari и Telegram на iOS:
// - листаете ленту в любую сторону дальше 30 px — обе уходят, экран целиком под переписку;
// - лёгкое обратное движение (10 px) или одиночный тап по ленте — обе возвращаются;
// - в самом верху и в самом низу ленты (последние сообщения) панели видны всегда;
// - не прячем, пока открыта клавиатура, в поле текст или вложения, идёт запись голоса, открыто меню или вопрос Claude;
// - «резинку» iOS у границ (scrollTop за пределами ленты) и прокрутку самой панели (к новому сообщению) не считаем.
const BARS_HIDE = 30, BARS_SHOW = 10, EDGE_TOP = 8, EDGE_END = 24;
function barsLocked() {
  return document.documentElement.classList.contains("kb") || document.activeElement === $("input") || !!$("input").value.trim()
    || files.length > 0 || !!rec || !!micBar || !$("menu").hidden || !$("keys").hidden || $("ask").childElementCount > 0;
}
function setBars(show) {
  if (!show && barsLocked()) show = true;
  barsShown = show; barsRun = 0;
  if (!show) document.documentElement.style.setProperty("--top-h", $("top").offsetHeight + "px");   // для «Назад»
  $("top").classList.toggle("hide", !show);
  hideDock(!show); placeNotices(); setTimeout(placeNotices, 250);    // шапка уезжает .2 с — зона следом
}
function hideDock(on) {
  const d = $("dock");
  if (on && d.hidden) on = false;
  if (d.classList.contains("hide") === on) return;
  d.classList.toggle("hide", on);
  const h = on ? 0 : d.offsetHeight;                   // кнопка «к последнему» и мини-плеер — следом за панелью
  const root = document.documentElement.style; root.setProperty("--tb", h + "px"); root.setProperty("--mini-b", (h + 12) + "px");
  placeNotices();
}
const SC = $("scroller");                            // прокручивается только лента; документ стоит на месте
const atEnd = (gap) => SC.scrollHeight - (SC.clientHeight + SC.scrollTop) <= gap;
function scrollToY(y, smooth) { autoUntil = Date.now() + (smooth ? 900 : 300); SC.scrollTo({ top: y, behavior: smooth ? "smooth" : "auto" }); }
SC.addEventListener("scroll", () => {
  const max = SC.scrollHeight - SC.clientHeight, y = SC.scrollTop;
  const far = !atEnd(200);                           // пролистали вверх — кнопка «к последнему»
  $("toBottom").hidden = !(view === "session" && far);
  if (!far) $("toBottom").classList.remove("new");
  $("top").classList.toggle("edge", y > 4);
  if (y < 0 || y > max) return;                      // «резинка» iOS за границей ленты — не жест
  const dy = y - lastY; lastY = y;
  if (y <= EDGE_TOP || max - y <= EDGE_END) { if (!barsShown) setBars(true); barsDir = 0; barsRun = 0; return; }
  if (Date.now() < autoUntil || !dy) return;
  const dir = Math.sign(dy);
  if (dir !== barsDir) { barsDir = dir; barsRun = 0; }
  barsRun += Math.abs(dy);
  if (barsShown && barsRun >= BARS_HIDE) { barsHidDir = dir; setBars(false); }
  else if (!barsShown && dir !== barsHidDir && barsRun >= BARS_SHOW) setBars(true);
}, { passive: true });
// Одиночный тап по ленте (не жест прокрутки) — панели возвращаются.
let tapAt = null;
SC.addEventListener("pointerdown", (e) => { tapAt = { x: e.clientX, y: e.clientY, t: Date.now() }; }, { passive: true });
SC.addEventListener("pointerup", (e) => {
  if (tapAt && !barsShown && Date.now() - tapAt.t < 350 && Math.hypot(e.clientX - tapAt.x, e.clientY - tapAt.y) < 8) setBars(true);
  tapAt = null;
}, { passive: true });
SC.addEventListener("pointercancel", () => { tapAt = null; }, { passive: true });
$("input").addEventListener("focus", () => setBars(true));

// Каркас — ровно в видимой части экрана. iOS не сжимает страницу под клавиатуру, а сдвигает её, и поле ввода «ездит»
// вместе с лентой; Android и Telegram сжимают сами. Высота и верх — из visualViewport, класс .kb — клавиатура открыта.
let fullH = 0, fullW = 0;
function fitViewport() {
  const v = window.visualViewport, h = v ? v.height : innerHeight, root = document.documentElement;
  if (innerWidth !== fullW) { fullW = innerWidth; fullH = 0; }          // повернули экран — меряем заново
  fullH = Math.max(fullH, h);
  root.style.setProperty("--app-h", h + "px");
  root.style.setProperty("--app-top", (v ? v.offsetTop : 0) + "px");
  const kb = fullH - h > 150;
  root.classList.toggle("kb", kb);
  if (kb && !barsShown) setBars(true);               // клавиатура открылась — поле ввода на виду
  if (!kb && window.scrollY) scrollTo(0, 0);           // iOS иногда оставляет страницу сдвинутой после клавиатуры
  placeNotices();
}

// Потяните ленту вниз в самом верху — панель обновится, как в мобильных приложениях. Свайпы Telegram, которые
// сворачивают Mini App, отключены (disableVerticalSwipes), так что жест наш. Вбок и вверх — обычная прокрутка.
const PULL = 64;                                     // насколько вытянуть кружок, чтобы обновить
let pull = null;
const pullBox = (t) => (t.closest("#scroller") ? SC : null);
function onPullStart(e) {
  const box = e.touches.length === 1 && view !== "login" && !document.querySelector(".sheet-bg") && pullBox(e.target);
  if (!box || box.scrollTop > 0 || $("ptr").classList.contains("spin")) return;
  const t = e.touches[0], r = (box === SC ? $("top") : box).getBoundingClientRect(), b = document.body.getBoundingClientRect();
  pull = { box, x: t.clientX, y: t.clientY, d: 0, on: false, ready: false, top: (box === SC ? r.bottom : r.top) - b.top, mid: r.left + r.width / 2 - b.left };
}
function onPullMove(e) {
  if (!pull) return;
  const t = e.touches[0], dx = t.clientX - pull.x, dy = t.clientY - pull.y;
  if (!pull.on) {
    if (dy < 0 || Math.abs(dx) > Math.abs(dy) || pull.box.scrollTop > 0) { pull = null; return; }
    if (dy < 10) return;
    pull.on = true; pull.y = t.clientY;
  }
  e.preventDefault();                                // ленту не растягиваем — тянется только кружок
  const d = Math.min(PULL * 1.6, Math.max(0, t.clientY - pull.y) * 0.5), ready = d >= PULL, el = $("ptr");   // кружок вдвое «вязче» пальца
  if (ready && !pull.ready) haptic("impactOccurred", "light");
  pull.d = d; pull.ready = ready;
  el.classList.remove("back"); el.classList.toggle("ready", ready);
  Object.assign(el.style, { left: pull.mid + "px", top: pull.top + "px", opacity: Math.min(1, d / PULL), transform: `translateY(${d}px) rotate(${d * 4}deg)` });
}
function onPullEnd() {
  const p = pull; pull = null;
  if (p?.on) p.ready ? pullRefresh() : hidePull();
}
function hidePull() {
  const el = $("ptr"); el.classList.add("back"); el.classList.remove("ready", "spin");
  Object.assign(el.style, { opacity: 0, transform: "translateY(0) scale(.6)" });
}
async function pullRefresh() {
  const el = $("ptr"), t0 = Date.now();
  el.classList.add("back", "spin"); el.style.transform = `translateY(${PULL * 0.8}px)`;
  await refresh();
  if (UPD.found) return reloadPanel();               // вышла новая версия панели — сами просили обновить: загружаем
  if (view === "session") await loadContent();
  else if (view === "home" && homeView === "integrations") await loadMcp(true);
  else if (view === "home" && homeView === "commands") await loadCommands();
  await new Promise((r) => setTimeout(r, Math.max(0, 500 - (Date.now() - t0))));   // кружок не мигает
  hidePull();
  if (lastOk < t0) toast("Нет связи с сервером — проверьте интернет", 3500);
}
SC.addEventListener("touchstart", onPullStart, { passive: true });     // список слева (split) тоже внутри ленты
SC.addEventListener("touchmove", onPullMove, { passive: false });
SC.addEventListener("touchend", onPullEnd); SC.addEventListener("touchcancel", onPullEnd);
// Перезагрузка возвращает туда же: открытая сессия и вкладка переживают обновление страницы.
function reloadPanel() {
  try { sessionStorage.setItem("resume", JSON.stringify({ id: view === "session" ? current : null, tab })); } catch (e) {}
  saveDraft(); location.reload();
}

// ---------- зона уведомлений (задача 26) ----------
// Всё всплывающее — тосты, баннеры, подсказки — живёт в #notices: под шапкой и не ниже верха нижней панели, с учётом
// клавиатуры (body — ровно видимая область, fitViewport). Поле ввода, микрофон и кнопки ничто не закрывает.
// Новый всплывающий элемент — сюда в реестр и через notice(el); tests/test_notices.py сверяет реестр со стилями,
// tests/e2e/notices_demo.py — с геометрией в браузере (390×844, клавиатура открыта).
const NOTICES = ["#updateBar", "#net", ".toast", ".tour-offer"];
// Над нижней панелью: кнопки — высота дока + 12 px (hideDock, padDock, placeMini), шторка помощника — --nz-dock.
const ABOVE_DOCK = [".tobottom", ".mini", ".help-bg"];
// position: fixed, но не всплывающее: сам каркас, нижние панели, листы-шторки (свой фон на весь экран), служебное;
// .pvbar — полоса просмотра роли в самом верху, место под неё отведено (body.previewing), поле ввода не трогает.
// body.back-drag #home — главная под сессией только на время свайпа «назад» (план UX, пункт 7).
const FIXED_OK = ["body", ".ptr", ".homebar", ".dock", ".sheet-bg", ".nav", ".nav-bg", "body.split.side-mini.has-nav .rail", ".pop", "body.split:not(.side-mini) .grip", "#simple", ".notices", ".pvbar", ".focus-end", "body.back-drag #home[hidden]"];
function notice(el) { $("notices").append(el); placeNotices(); return el; }
function placeNotices() {
  const root = document.documentElement.style, H = document.body.clientHeight;
  const head = SIM.on ? document.querySelector(".s-top") : view === "login" || $("top").classList.contains("hide") ? null : $("top");
  const r = head?.getBoundingClientRect(), top = r && r.height ? Math.max(0, r.bottom - document.body.getBoundingClientRect().top) : 0;
  const dock = SIM.on ? document.querySelector(".s-dock") : !$("dock").hidden ? ($("dock").classList.contains("hide") ? null : $("dock"))
    : !$("homeBar").hidden ? $("homeBar") : null;
  const bottom = H - (dock ? dock.offsetHeight : 0);    // нижние панели прижаты к низу видимой области
  root.setProperty("--nz-top", Math.round(top + 8) + "px"); root.setProperty("--nz-dock", Math.round(H - bottom) + "px");
  root.setProperty("--nz-max", Math.max(0, Math.round(bottom - Math.max(top + 8, 8) - 8)) + "px");
}
if (window.ResizeObserver) {                          // шапка, док и поле ввода меняют высоту — зона следом
  const ro = new ResizeObserver(() => placeNotices());
  for (const el of [$("top"), $("dock"), $("homeBar"), document.querySelector(".s-top"), document.querySelector(".s-dock")]) if (el) ro.observe(el);
}

// ---------- новая версия панели ----------
// /api/sessions отдаёт build; не совпал с тем, с которым панель загрузилась, — вышла новая. Тонкая строка под шапкой
// «Есть новая версия · Обновить · Позже»; «Позже» прячет её до следующего открытия панели. Сама панель
// перезагружается, только когда это никому не мешает (updSafe): вернулись в неё из фона или открыли заново.
const UPD = { found: false, later: false };
function updateFound() {
  if (UPD.found) return;
  UPD.found = true;
  $("updText").textContent = L("upd.text", "Есть новая версия"); $("updGo").textContent = L("upd.go", "Обновить");
  $("updLater").textContent = L("upd.later", "Позже");
  $("updateBar").hidden = UPD.later; placeNotices();
  if (document.hidden) updAuto();                      // нашли, пока панель в фоне, — можно сразу
}
function checkBuild(d) { if (BUILD && d?.build && d.build !== BUILD) updateFound(); }
// Безопасно: поле ввода пустое (и в простом режиме), ничего не прикреплено и не грузится, не идёт запись голоса,
// не открыт лист, помощник, тур или мастер (форма подключения, вход, условия, страна, роль).
function updSafe() {
  if ($("input").value.trim() || $("sInput").value.trim() || files.length || rec || micBar) return false;
  if (document.querySelector(".sheet-bg, .tour-offer, .driver-popover") || tourOn) return false;
  if (voice && voice.state !== "pause") return false;     // слушают ответ — не прерываем (место всё равно запомнено)
  return SIM.on || view === "home" || view === "session";
}
function updAuto() { if (UPD.found && updSafe()) reloadPanel(); }
$("updGo").onclick = reloadPanel;
$("updLater").onclick = () => { UPD.later = true; $("updateBar").hidden = true; placeNotices(); };
document.addEventListener("visibilitychange", () => { if (!document.hidden) updAuto(); });
tg?.onEvent?.("activated", updAuto);                    // Telegram: Mini App снова на экране

// Черновик переживает перезагрузку (новая версия, «Перезагрузить панель», потянуть ленту): поле ввода полного
// и простого режима и уже загруженные файлы — в sessionStorage этой вкладки, после запуска возвращаются на место.
function saveDraft() {
  const d = { input: $("input").value, sInput: $("sInput").value, files: files.filter((f) => f.path) };
  try { if (d.input.trim() || d.sInput.trim() || d.files.length) sessionStorage.setItem("draft", JSON.stringify(d)); else sessionStorage.removeItem("draft"); } catch (e) {}
}
addEventListener("pagehide", saveDraft);
function restoreDraft() {
  let d = null;
  try { d = JSON.parse(sessionStorage.getItem("draft") || "null"); sessionStorage.removeItem("draft"); } catch (e) {}
  if (!d) return;
  if (d.input && !$("input").value.trim()) { $("input").value = d.input; grow(); }
  if (d.files?.length && !files.length) { files = d.files; renderFiles(); }
  if (d.sInput && !$("sInput").value.trim()) { $("sInput").value = d.sInput; sGrow(); }
}
// ---------- точечное обновление (план UX, пункт 1) ----------
// Опрос раз в 3–10 с не перерисовывает то, что не изменилось. setHTML: та же разметка — DOM не трогаем. morph: список
// и лента по ключам (data-id, data-i, data-proj, data-key, id) — изменившийся элемент заменяется, новые вставляются,
// пропавшие удаляются, остальное стоит на месте (прокрутка, раскрытые логи, фокус). Анимация появления — только у новых;
// заменённые — с классом .mupd (без анимации). Текст «изменена N назад» в сравнение не входит — его ведёт agoTick.
const AGO_TXT = /(<span class="ago"[^>]*>)[^<]*/g;
function setHTML(el, html) {
  const key = html.replace(AGO_TXT, "$1");
  if (el.__h === key && el.firstChild === el.__f) return false;
  el.innerHTML = html; el.__h = key; el.__f = el.firstChild;
  return true;
}
function setText(el, t) { if (el.textContent !== t) el.textContent = t; }
function setHidden(el, on) { if (el.hidden !== on) el.hidden = on; }
function morph(box, html) {                           // → новые узлы (вставленные и заменённые) — для дообработки
  const t = document.createElement("template"); t.innerHTML = html;
  const old = new Map(), fresh = [], seen = {};
  for (const n of box.children) if (n.__k) old.set(n.__k, n);
  const next = [...t.content.children].map((n) => {
    const d = n.dataset, base = d.id ?? d.i ?? d.proj ?? d.chat ?? d.key ?? (n.id ? "#" + n.id : n.tagName + "." + n.className);
    const k = base + "~" + (seen[base] = (seen[base] || 0) + 1), src = n.outerHTML.replace(AGO_TXT, "$1"), was = old.get(k);
    if (was && was.__s === src) return was;
    n.__k = k; n.__s = src; fresh.push(n);
    if (was) n.classList.add("mupd");
    return n;
  });
  const keep = new Set(next);
  for (const n of [...box.childNodes]) if (!keep.has(n)) n.remove();
  next.forEach((n, i) => { if (box.children[i] !== n) box.insertBefore(n, box.children[i] || null); });
  return fresh;
}
// Скелетоны (план UX, пункт 3): заглушки в размер карточки и сообщения; ключ data-key — morph заменит их данными.
function skelCards(n = 3) {
  return Array.from({ length: n }, (_, i) => `<div class="card skel" data-key="skel:${i}" aria-hidden="true"><div class="row"><span class="sdot"></span>
    <div class="ctext"><i class="sk-name"></i><i class="sk-meta"></i></div></div><div class="cfoot"><i class="sk-chip"></i></div></div>`).join("")
    + '<span class="sr-only" data-key="skel:sr" role="status">Загружаю…</span>';
}
function skelMsgs() {
  const ai = (w) => `<div class="msg ai skel" data-key="skel:a${w}" aria-hidden="true">${w.map((x) => `<i style="width:${x}%"></i>`).join("")}</div>`;
  return `<div class="msg me skel" data-key="skel:u1" aria-hidden="true"><div class="bubble"></div></div>${ai([92, 84, 60])}`
    + `<div class="msg me skel" data-key="skel:u2" aria-hidden="true"><div class="bubble" style="width:40%"></div></div>${ai([88, 70])}`
    + '<span class="sr-only" data-key="skel:sr" role="status">Загружаю…</span>';
}
// ---------- разметка ответов (план UX, пункт 10) ----------
// marked и DOMPurify (~60 КБ) больше не держат первый показ: грузятся после него (mdLoad), а до загрузки ответ виден
// простым текстом с переносами строк. Пришли — лента и простой режим перерисовываются (точечно: меняются только ответы).
const MD_LIBS = ["https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js", "https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.1.6/purify.min.js"];
const mdReady = () => !!(window.marked && window.DOMPurify);
function md(t) {
  if (mdReady()) return DOMPurify.sanitize(marked.parse(t || ""));
  mdLoad();
  return (t || "").split(/\n{2,}/).map((p) => `<p>${esc(p).replace(/\n/g, "<br>")}</p>`).join("");
}
const afterPaint = (f) => (window.requestIdleCallback ? requestIdleCallback(f, { timeout: 2500 }) : setTimeout(f, 400));
function mdLoad() {
  return mdLoad.p ||= Promise.all(MD_LIBS.map((src) => new Promise((ok, no) => {
    const el = document.createElement("script"); el.src = src; el.async = false; el.onload = ok; el.onerror = no; document.head.append(el);
  }))).then(() => {
    if (view === "session" && tab === "chat" && hist.length) renderChat(false);
    if (SIM.on && SIM.hist.length) sRender();
  }, () => { mdLoad.p = null; });                   // нет сети к CDN — попробуем при следующем ответе
}
function setSub(html) { setHTML($("subtitle"), html); }
