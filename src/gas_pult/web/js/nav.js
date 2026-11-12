// ---------- широкий экран: ширина и свёртка списка слева, размер шрифта ----------
// Только при двух колонках (split): на телефоне ни ручки, ни полосы значков, клавиши браузера не перехватываем.
const SIDE = { min: 200, max: 480, def: 280 }, FONT = { min: 12, max: 20, def: 15 };
const clampN = (v, a, b, d) => (Number.isFinite(v) ? Math.min(b, Math.max(a, Math.round(v))) : d);
let sideW = clampN(parseInt(store("sideW"), 10), SIDE.min, SIDE.max, SIDE.def);
let sideMini = store("sideMini") === "1";
let fontPx = clampN(parseInt(store("fontPx"), 10), FONT.min, FONT.max, FONT.def);
function applyWide() {
  const two = split(), root = document.documentElement.style;
  root.setProperty("--side-w", sideW + "px");
  document.body.classList.toggle("side-mini", two && sideMini);
  if (two && fontPx !== FONT.def) root.setProperty("--fz", String(fontPx / FONT.def)); else root.removeProperty("--fz");
  const g = $("sideGrip"); g.setAttribute("aria-valuenow", sideW); g.setAttribute("aria-valuetext", sideW + " пикселей");
  const b = $("sideBtn"), t = sideMini ? "Развернуть список" : "Свернуть список";
  b.innerHTML = ic(sideMini ? "sideopen" : "sidebar"); b.setAttribute("aria-label", t); b.title = t; b.setAttribute("aria-expanded", String(!sideMini));
}
function setSideW(w, save = true) {
  sideW = clampN(w, SIDE.min, SIDE.max, SIDE.def); applyWide();
  if (save) store("sideW", sideW === SIDE.def ? "" : String(sideW));
}
function setMini(on) { sideMini = on; store("sideMini", on ? "1" : ""); applyWide(); renderRail(); renderNav(); }
function setFont(px) {
  const v = clampN(px, FONT.min, FONT.max, FONT.def);
  if (v === fontPx) return toast(v === FONT.def ? "Шрифт по умолчанию" : v === FONT.max ? "Крупнее нельзя" : "Мельче нельзя", 1400);
  fontPx = v; store("fontPx", v === FONT.def ? "" : String(v)); applyWide();
  toast(`Шрифт панели: ${v} px${v === FONT.def ? " (по умолчанию)" : ""}`, 1400);
}
// Узкая полоса (свёрнутая панель чатов на ПК, решение владельца — проекты): ⇥ раскрыть, ✎ новый чат, ⌕ поиск, затем
// проекты квадратами — инициалы, цвет (--pjN), цифра — активные чаты, точка — «ждёт ответа» (жёлтая) или «новое»;
// нажатие — список чатов проекта у самого значка; текущий — обводка; закреплённые — сверху. Внизу ⚙. Проектов нет
// (пространство, проекты выключены) — сессии кружками, как раньше. Телефон и фокус — без полосы (navOn, split).
const initial = (n) => (String(n).match(/[\p{L}\p{N}]/u)?.[0] || "?").toUpperCase();
function initials(n) {                                // «gas-pult» → «GP», «Книги» → «КН»
  const w = String(n).split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  return (w.length > 1 ? w[0][0] + w[1][0] : (w[0] || "?").slice(0, 2)).toUpperCase();
}
function pjColor(id) { let h = 0; for (const c of String(id)) h = (h * 31 + c.codePointAt(0)) >>> 0; return 1 + (h % 6); }
function railProjects() {
  const ps = (projData?.projects || []).filter((p) => !p.archived);
  return [...ps.filter((p) => p.pinned).sort((a, b) => (b.pinned_at || 0) - (a.pinned_at || 0)), ...ps.filter((p) => !p.pinned)];
}
const railTool = (id, icon, tip, extra = "") => `<button class="rb rt" type="button" id="${id}" title="${esc(tip)}" aria-label="${esc(tip)}"${extra}>${ic(icon)}</button>`;
function renderRail() {
  if (!split() || !sideMini || !navOn()) return;
  const rw = meta?.role !== "viewer", cur = sessions.find((x) => x.id === current);
  const head = railTool("railOpen", "sideopen", "Развернуть панель чатов", ' aria-expanded="false"')
    + (rw ? railTool("railNew", "compose", "Новый чат") : "") + railTool("railSearch", "search", "Поиск (Ctrl+K)") + "<hr>";
  let body;
  if (projOn() && projData) {
    body = railProjects().map((p) => {
      const list = sessions.filter((x) => x.project === p.id), wait = list.filter((x) => x.status === "dialog").length || p.waiting || 0;
      const nw = !wait && list.some(isNew), on = !!cur && cur.project === p.id && view === "session";
      const tip = `${p.name}${p.pinned ? " · закреплён" : ""} — ${list.length ? "активных чатов: " + list.length : "нет активных чатов"}${wait ? " · ждёт ответа" : nw ? " · новый ответ" : ""}`;
      return `<button class="rb pj c${pjColor(p.id)}${on ? " on" : ""}" type="button" data-rp="${esc(p.id)}" title="${esc(tip)}" aria-label="${esc(tip)}" aria-haspopup="menu" aria-expanded="false"${on ? ' aria-current="true"' : ""}>`
        + `${esc(initials(p.name))}${list.length ? `<span class="cnt" aria-hidden="true">${list.length}</span>` : ""}${wait || nw ? `<i class="pdot${wait ? " wait" : ""}" aria-hidden="true"></i>` : ""}</button>`;
    }).join("");
  } else {
    body = pinFirst([...sessions].sort(byChange)).map((s) => {
      const st = ST[s.status] || ST.idle, prov = provName(s), nw = isNew(s);
      const tip = `${s.name} — ${st.label}${prov ? " · " + prov : ""}${nw ? " · новый ответ" : ""}`;
      return `<button class="rb ${st.cls}${s.id === current ? " on" : ""}${nw ? " new" : ""}" type="button" data-id="${esc(s.id)}" title="${esc(tip)}" aria-label="${esc(tip)}"${s.id === current ? ' aria-current="true"' : ""}>${esc(initial(s.name))}<i class="sdot"></i></button>`;
    }).join("");
  }
  const f = $("rail").contains(document.activeElement) ? document.activeElement : null;   // опрос перерисовал — фокус на месте
  const key = f && (f.id ? "#" + f.id : f.dataset.rp ? `[data-rp="${CSS.escape(f.dataset.rp)}"]` : f.dataset.id ? `[data-id="${CSS.escape(f.dataset.id)}"]` : "");
  if (setHTML($("rail"), head + body + `<span class="rgap"></span>` + railTool("railSettings", "settings", "Настройки")) !== false && key) $("rail").querySelector(key)?.focus();
}
function railProject(btn) {                           // чаты проекта — меню у значка, справа от полосы
  const p = projOf(btn.dataset.rp); if (!p) return;
  const list = sessions.filter((x) => x.project === p.id).sort((a, b) => lastMsg(b) - lastMsg(a));
  popMenu(btn, [
    ...list.map((x) => ({ label: (x.title || x.name) + (x.status === "dialog" ? " · ждёт ответа" : isNew(x) ? " · новое" : ""), icon: "chat", on: x.id === current, run: () => openSession(x.id) })),
    ...(list.length ? [{ sep: true }] : []),
    ...(meta?.role !== "viewer" ? [{ label: "Начать чат в проекте", icon: "compose", run: () => newChat(p.id) }] : []),
    { label: p.chats ? `Все чаты проекта · ${p.chats}` : "Открыть проект", icon: "folder", run: () => navProject(p.id) },
  ], { right: true });
}
$("rail").addEventListener("click", (e) => {
  const t = e.target.closest("button"); if (!t) return;
  if (t.id === "railOpen") return setMini(false);
  if (t.id === "railNew") return newChat();
  if (t.id === "railSearch") return navSearch(true);
  if (t.id === "railSettings") return go("go:settings");
  if (t.dataset.rp) return railProject(t);
  if (t.dataset.id) openSession(t.dataset.id);
});
$("rail").addEventListener("keydown", (e) => {          // стрелки — по значкам полосы, Home/End — к краям
  const bs = [...$("rail").querySelectorAll("button")], k = bs.indexOf(document.activeElement);
  if (k < 0) return;
  const to = { ArrowDown: k + 1, ArrowUp: k - 1, Home: 0, End: bs.length - 1 }[e.key];
  if (to === undefined) return;
  e.preventDefault(); bs[(to + bs.length) % bs.length].focus();
});
$("sideBtn").onclick = () => setMini(!sideMini);
// ---------- панель чатов (как в ChatGPT / Claude.ai) ----------
// Сверху «Пульт», ✎ «Новый чат» (окно — при первой отправке, см. newChat), поиск (Ctrl+K / ⌘K) и «⋯» (новая папка,
// из модуля, в фокусе). Ниже — «Закреплённые» (закрепление своё у каждого человека, /api/pin), «Проекты» свёрнутыми
// группами и «Недавние» — по времени последнего сообщения (ваше или агента), не по изменению файла. У строки «⋯» при
// наведении (компьютер) или долгом нажатии (телефон) — меню у самой строки: «Закрепить», «Переименовать», «Удалить»
// (плашка «Отменить» 5 с — до неё на сервере ничего не удаляется). Телефон: панель выезжает слева (☰ или свайп).
const NAV = { open: false, q: "", html: "", gone: new Set(), held: false, exp: new Set((() => { try { return JSON.parse(store("navExp") || "[]"); } catch (e) { return []; } })()) };
let DRAFT = null;                                     // новый чат до первой отправки: { proj, profile }
const navOn = () => !FOCUS && !SIM.on && !!meta && !["login", "terms", "country", "persona"].includes(view);
const lastMsg = (s) => Math.max(+s.said || 0, +s.asked || 0) || +s.changed || 0;
const canPin = (s) => meta?.role !== "viewer" && !FOCUS && !s?.space;
function navTime(ts) {                                 // сегодня — время, вчера — «вчера», раньше — дата
  if (!ts) return "";
  const d = new Date(ts * 1000), now = new Date(), p = (x) => String(x).padStart(2, "0");
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime(), diff = Math.round((day(now) - day(d)) / 864e5);
  return diff <= 0 ? `${p(d.getHours())}:${p(d.getMinutes())}` : diff === 1 ? "вчера" : `${p(d.getDate())}.${p(d.getMonth() + 1)}`;
}
const navBtns = (x, pinOk) => (pinOk ? `<button class="nb npin" type="button" data-npin aria-label="${x.pinned ? "Открепить" : "Закрепить"}" title="${x.pinned ? "Открепить" : "Закрепить"}">${ic("pin")}</button>` : "")
  + `<button class="nb nmore" type="button" data-nmore aria-label="Действия" title="Действия" aria-haspopup="menu">${ic("more")}</button>`;
function navRow(s, sub) {
  const st = ST[s.status] || ST.idle, name = s.name, tip = name + (s.title && s.title !== name ? " — «" + s.title + "»" : "") + " — " + st.label;
  return `<div class="nrow${s.id === current && view === "session" ? " on" : ""}${s.pinned ? " pinned" : ""}${sub ? " sub" : ""}${isNew(s) ? " new" : ""}" data-nw="${esc(s.id)}" role="listitem" tabindex="0" title="${esc(tip)}">`
    + `<span class="sdot ${st.cls}"></span><span class="nm">${esc(name)}</span><span class="tm">${esc(navTime(lastMsg(s)))}</span>${navBtns(s, canPin(s))}</div>`;
}
function navProj(p, list, open) {
  const n = p.waiting ? p.waiting + " ждут" : String(list.length || p.chats || "");
  return `<div class="nrow proj${p.pinned ? " pinned" : ""}" data-np="${esc(p.id)}" role="listitem" tabindex="0" aria-expanded="${open}" title="${esc(p.name)}">${ic("chevron", "nchev")}<span class="nm">${esc(p.name)}</span><span class="tm">${esc(n)}</span>${navBtns(p, canPin())}</div>`
    + (open ? list.map((s) => navRow(s, true)).join("") + `<div class="nrow sub all" data-nall="${esc(p.id)}" role="listitem" tabindex="0"><span class="nm">Все чаты проекта${p.chats ? " · " + p.chats : ""}</span></div>` : "");
}
function renderNav() {
  const on = navOn();
  document.body.classList.toggle("has-nav", on);
  const two = split();
  setHidden($("navBtn"), !on || two || (view !== "home" && view !== "session"));          // на ПК — ⇥ и ✎ в полосе
  setHidden($("composeBtn"), !on || meta?.role === "viewer" || two || view !== "home");
  setHidden($("navCloseBtn"), two); syncBack(); $("nav").inert = !on || (!two && !NAV.open) || (two && sideMini);
  if (!on) { if (NAV.open) navOpen(false); return; }
  const q = NAV.q.trim().toLowerCase(), hit = (t) => !q || String(t || "").toLowerCase().includes(q);
  const ss = sessions.filter((x) => !NAV.gone.has(x.id)), nm = (x) => x.name + " " + (x.title || "");
  const projs = projOn() ? projData?.projects || [] : [];
  const ofProj = (p) => ss.filter((x) => x.project === p.id).sort((a, b) => lastMsg(b) - lastMsg(a));
  const pv = (p) => { const l = ofProj(p).filter((x) => !q || hit(nm(x)) || hit(p.name)); return (hit(p.name) || l.length) ? navProj(p, l, !!q || NAV.exp.has(p.id)) : ""; };
  const sec = (t) => `<div class="nav-sec" role="presentation">${t}</div>`;
  const pins = projs.filter((p) => p.pinned).map(pv).join("") + ss.filter((x) => x.pinned && hit(nm(x))).sort((a, b) => lastMsg(b) - lastMsg(a)).map((x) => navRow(x)).join("");
  const groups = projs.filter((p) => !p.pinned).map(pv).join("");
  const recent = ss.filter((x) => !x.pinned && hit(nm(x))).sort((a, b) => lastMsg(b) - lastMsg(a));
  const cmds = q ? palCmds().filter((c) => hit(c.label + " " + (c.kw || ""))) : [];   // палитра: при поиске — и команды
  const canNewP = projOn() && meta?.role !== "viewer" && !q;           // «+» — «Новый проект» (и когда проектов ещё нет)
  const secP = `<div class="nav-sec has-add" role="presentation"><span>Проекты</span><button type="button" class="nav-add" data-nnewp aria-label="Новый проект" title="Новый проект">${ic("plus")}</button></div>`;
  const h = (pins ? sec("Закреплённые") + pins : "") + (groups ? (canNewP ? secP : sec("Проекты")) + groups : canNewP ? secP : "")
    + (recent.length || !cmds.length ? sec("Недавние") : "")
    + (recent.length ? recent.map((x) => navRow(x)).join("") : cmds.length ? "" : `<p class="nav-empty">${q ? "Ничего не нашлось" : "Чатов пока нет — «Новый чат» вверху"}</p>`)
    + (cmds.length ? sec("Команды") + cmds.map((c) => `<div class="nrow cmd" data-ncmd="${c.id}" role="listitem" tabindex="0">${ic(c.icon, "ncmd")}<span class="nm">${esc(c.label)}</span></div>`).join("") : "");
  if (NAV.html !== h) { NAV.html = h; $("navList").innerHTML = h; }   // опрос раз в 3–10 с — DOM только при изменении
  renderRail();
}
// Палитра команд (план UX, пункт 5): Ctrl+K / ⌘K — тот же поиск панели чатов (#149), только в выдаче, кроме чатов и
// проектов, — действия. Переходы — через HELP_GO (те же, что у «Перейти» в справке), без отдельного окна.
function palCmds() {
  const rw = meta?.role !== "viewer", own = meta?.role === "owner";
  return [
    rw && { id: "new", label: "Начать новый чат", icon: "compose", kw: "сессия создать", run: () => newChat() },
    rw && { id: "folder", label: "Создать папку", icon: "plus", kw: "проект новая", run: () => go("go:new-folder") },
    rw && !meta?.space && { id: "modules", label: "Создать из модуля", icon: "puzzle", kw: "агент модули", run: () => go("go:modules") },
    { id: "home", label: "Открыть главную: сессии", icon: "chat", kw: "список", run: () => go("go:sessions") },
    { id: "commands", label: "Открыть команды из ответов", icon: "term", kw: "код блоки", run: () => go("go:commands") },
    rw && { id: "integrations", label: "Открыть интеграции", icon: "puzzle", kw: "модели голос подключения mcp", run: () => go("go:integrations") },
    view === "session" && current && { id: "screen", label: "Показать экран терминала", icon: "monitor", kw: "tmux", run: () => go("go:session.screen") },
    view === "session" && current && { id: "chat", label: "Показать переписку", icon: "chat", run: () => go("go:session.chat") },
    { id: "settings", label: "Открыть настройки", icon: "settings", kw: "тема шрифт язык", run: () => go("go:settings") },
    own && { id: "cost", label: "Показать расход", icon: "coin", kw: "деньги бюджет лимит", run: () => go("go:settings.cost") },
    own && { id: "trash", label: "Открыть корзину чатов", icon: "trash", kw: "удалённые вернуть", run: () => chatTrash() },
    { id: "legend", label: "Показать обозначения", icon: "eye", kw: "значки цвета", run: () => go("go:settings.legend") },
    { id: "help", label: "Открыть подсказки", icon: "help", kw: "справка помощь", run: () => $("helpBtn").click() },
  ].filter(Boolean);
}
function navOpen(on) {
  if (split() || !document.body.classList.contains("has-nav")) on = false;
  if (NAV.open === on && document.body.classList.contains("nav-open") === on) return;
  NAV.open = on; document.body.classList.toggle("nav-open", on);
  $("nav").inert = !on && !split();
  if (on) { renderNav(); haptic("impactOccurred", "light"); } else closePop();
}
function navSearch(on = true) {
  if (split() && sideMini) setMini(false);
  if (!split()) navOpen(true);
  $("navQBox").hidden = !on; $("navSearchBtn").setAttribute("aria-expanded", String(on));
  if (on) setTimeout(() => $("navQ").focus(), split() ? 0 : 220);
  else if (NAV.q) { NAV.q = ""; $("navQ").value = ""; renderNav(); }
}
$("navQ").oninput = (e) => { NAV.q = e.target.value; renderNav(); };
$("navQ").onkeydown = (e) => {
  if (e.key === "Escape") { e.preventDefault(); navSearch(false); }
  if (e.key === "Enter") { e.preventDefault(); ($("navList").querySelector("[data-nw]") || $("navList").querySelector("[data-ncmd]"))?.click(); }
  if (e.key === "ArrowDown") { e.preventDefault(); $("navList").querySelector(".nrow")?.focus(); }
};
$("navSearchBtn").onclick = () => navSearch($("navQBox").hidden);
$("navBtn").onclick = () => (split() ? setMini(false) : navOpen(true));
$("navCloseBtn").onclick = () => navOpen(false);
$("navBg").onclick = () => navOpen(false);
$("navNew").onclick = () => newChat();
$("navHome").onclick = () => { navOpen(false); current = null; show("home"); setHome("sessions"); };
$("composeBtn").onclick = () => newChat();
$("navMoreBtn").onclick = (e) => popMenu(e.currentTarget, [
  // В меню «⋯» — глаголы (план UX, пункт 9): что произойдёт, а не куда попадёте
  ...(meta?.role !== "viewer" ? [{ label: "Начать новый чат", icon: "compose", run: () => newChat() },
    { label: "Создать папку", icon: "plus", run: () => newFolder() }] : []),
  ...(meta?.role !== "viewer" && !meta?.space ? [{ label: "Создать из модуля", icon: "puzzle", run: () => modulesView() }] : []),
  ...(meta?.role === "owner" ? [{ label: "Начать сессию в фокусе", icon: "qr", run: () => { focusNext = true; newSession(); } }] : []),
  { sep: true }, { label: "Открыть главную", icon: "home", run: () => { current = null; show("home"); setHome("sessions"); } },
]);
// Меню у строки (поповер): закрыть — щелчок мимо, Esc, прокрутка
function closePop() { document.querySelectorAll(".pop").forEach((x) => { x.anchor?.classList.remove("menu-on"); x.btn?.setAttribute("aria-expanded", "false"); x.remove(); }); }
function popMenu(anchor, items, opt = {}) {
  const had = [...document.querySelectorAll(".pop")].some((x) => x.btn === anchor || x.anchor === anchor);
  closePop(); if (had) return;
  const box = document.createElement("div"); box.className = "pop"; box.setAttribute("role", "menu"); box.anchor = anchor;
  box.innerHTML = items.map((x, i) => x.sep ? "<hr>" : `<button type="button" role="menuitem" data-i="${i}" class="${x.danger ? "danger" : ""}${x.on ? " on" : ""}">${ic(x.icon || "chevron")}<span>${esc(x.label)}</span></button>`).join("");
  document.body.append(box);
  const row = anchor.closest(".nrow") || anchor; row.classList.add("menu-on"); box.anchor = row;
  if (anchor.hasAttribute("aria-haspopup")) { anchor.setAttribute("aria-expanded", "true"); box.btn = anchor; }
  const r = anchor.getBoundingClientRect(), w = box.offsetWidth, h = box.offsetHeight;
  const left = opt.right ? Math.min(innerWidth - w - 8, r.right + 14)
    : Math.max(8, Math.min(innerWidth - w - 8, r.right - w + (anchor.classList.contains("nrow") ? 0 : 4)));
  const top = opt.right ? Math.max(8, Math.min(innerHeight - h - 8, r.top))
    : r.bottom + 4 + h <= innerHeight - 8 ? r.bottom + 4 : Math.max(8, r.top - h - 4);
  box.style.left = left + "px"; box.style.top = top + "px";
  box.onclick = (e) => { const b = e.target.closest("button[data-i]"); if (!b) return; closePop(); items[+b.dataset.i].run(); };
  box.onkeydown = (e) => {
    const bs = [...box.querySelectorAll("button")], k = bs.indexOf(document.activeElement);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); bs[(k + (e.key === "ArrowDown" ? 1 : bs.length - 1)) % bs.length]?.focus(); }
    if (e.key === "Escape" || e.key === "Tab") { e.preventDefault(); closePop(); anchor.focus?.(); }
  };
  if (matchMedia("(pointer: fine)").matches || anchor.matches(":focus-visible")) box.querySelector("button")?.focus();
}
addEventListener("pointerdown", (e) => { if (!e.target.closest(".pop, [data-nmore], [data-rp], #navMoreBtn, [data-dfold], [data-dmodel]")) closePop(); }, true);
$("navList").addEventListener("scroll", closePop, { passive: true });
addEventListener("resize", closePop);
function navItems(row) {
  if (row.dataset.np) {
    const p = projOf(row.dataset.np); if (!p) return [];
    return [...(canPin() ? [{ label: p.pinned ? "Открепить" : "Закрепить", icon: "pin", on: !!p.pinned, run: () => pinSet({ project: p.id }, !p.pinned, p.name) }] : []),
      ...(meta?.role !== "viewer" ? [{ label: "Начать чат в проекте", icon: "compose", run: () => newChat(p.id) }] : []),
      { label: "Открыть проект", icon: "folder", run: () => navProject(p.id) },
      ...(meta?.role === "owner" && !FOCUS ? [{ label: "Создать фокус-ссылку на проект", icon: "qr", run: () => focusLink(null, p.id) },
        { label: "Создать демо-ссылку", icon: "eye", sub: "несколько устройств, только просмотр и выбор вариантов", run: () => focusLink(null, p.id, "demo") }] : [])];
  }
  const s = sessions.find((x) => x.id === row.dataset.nw); if (!s) return [];
  const name = s.title || s.name;
  return [...(canPin(s) ? [{ label: s.pinned ? "Открепить" : "Закрепить", icon: "pin", on: !!s.pinned, run: () => pinSet({ w: s.id }, !s.pinned, name) }] : []),
    ...(meta?.role !== "viewer" && !FOCUS ? [{ label: "Переименовать", icon: "edit", run: () => renameSession(s) }] : []),
    ...(meta?.role === "owner" && !s.space && !s.schedule ? [{ label: "Удалить", icon: "trash", danger: true, run: () => navDelete(s) }] : []),
    { sep: true }, { label: "Показать все действия…", icon: "more", run: () => sessionSheet(s.id) }];
}
function navProject(id) {                             // «Все чаты проекта» — страница проекта на главной
  navOpen(false); current = null; show("home"); setMode("projects"); setHome("sessions"); openProject(id);
}
// «Удалить» в меню строки — та же плашка «Отменить» (chatDelete).
function navDelete(s) { chatDelete({ w: s.id }, s.title || s.name); }
function undoBar(text, undo, commit, ms = 5000) {
  document.querySelectorAll(".toast").forEach((t) => t.remove());
  const t = document.createElement("div"); t.className = "toast undo"; t.setAttribute("role", "status");
  t.innerHTML = `<span>${esc(text)}</span><button type="button">Отменить</button>`;
  let done = false;
  const fin = (f) => { if (done) return; done = true; clearTimeout(tm); t.remove(); f(); };
  const tm = setTimeout(() => fin(commit), ms);
  t.querySelector("button").onclick = () => fin(undo);
  notice(t); return t;
}
$("navList").addEventListener("click", (e) => {
  if (NAV.held) { NAV.held = false; return; }          // долгое нажатие уже открыло меню
  if (e.target.closest("[data-nnewp]")) return newProject();
  const row = e.target.closest(".nrow"); if (!row) return;
  if (e.target.closest("[data-nmore]")) return popMenu(e.target.closest("[data-nmore]"), navItems(row));
  if (e.target.closest("[data-npin]")) {
    const p = row.dataset.np && projOf(row.dataset.np), s = sessions.find((x) => x.id === row.dataset.nw);
    return p ? pinSet({ project: p.id }, !p.pinned, p.name) : s && pinSet({ w: s.id }, !s.pinned, s.title || s.name);
  }
  if (row.dataset.ncmd) { const c = palCmds().find((x) => x.id === row.dataset.ncmd); navSearch(false); navOpen(false); return c?.run(); }
  if (row.dataset.nall) return navProject(row.dataset.nall);
  if (row.dataset.np) {
    const id = row.dataset.np; NAV.exp.has(id) ? NAV.exp.delete(id) : NAV.exp.add(id);
    store("navExp", JSON.stringify([...NAV.exp])); renderNav(); return;
  }
  if (row.dataset.nw) { navOpen(false); if (row.dataset.nw !== current || view !== "session") openSession(row.dataset.nw); }
});
$("navList").addEventListener("keydown", (e) => {
  const row = e.target.closest(".nrow"); if (!row || e.target !== row) return;
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); row.click(); }
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault(); const rs = [...$("navList").querySelectorAll(".nrow")], k = rs.indexOf(row);
    rs[k + (e.key === "ArrowDown" ? 1 : -1)]?.focus();
  }
  if ((e.key === "F10" && e.shiftKey) || e.key === "ContextMenu") { e.preventDefault(); popMenu(row, navItems(row)); }
});
$("navList").addEventListener("contextmenu", (e) => {   // правая кнопка — то же меню
  const row = e.target.closest(".nrow[data-nw], .nrow[data-np]"); if (!row) return;
  e.preventDefault(); popMenu(row, navItems(row));
});
{ // долгое нажатие (телефон) — меню у строки
  let lp = null;
  $("navList").addEventListener("pointerdown", (e) => {
    const row = e.target.closest(".nrow[data-nw], .nrow[data-np]");
    if (!row || e.pointerType === "mouse" || e.target.closest(".nb")) return;
    const key = row.dataset.nw ? `[data-nw="${CSS.escape(row.dataset.nw)}"]` : `[data-np="${CSS.escape(row.dataset.np)}"]`;
    lp = { x: e.clientX, y: e.clientY, t: setTimeout(() => {                 // строку могли перерисовать — берём живую
      lp = null; const r = row.isConnected ? row : $("navList").querySelector(".nrow" + key); if (!r) return;
      NAV.held = true; haptic("impactOccurred", "medium"); popMenu(r, navItems(r));
    }, 480) };
  });
  const stop = () => { if (lp) clearTimeout(lp.t); lp = null; };
  $("navList").addEventListener("pointermove", (e) => { if (lp && Math.hypot(e.clientX - lp.x, e.clientY - lp.y) > 10) stop(); });
  $("navList").addEventListener("pointerup", stop); $("navList").addEventListener("pointercancel", stop);
}
// Свайп от левого края (телефон): панель идёт за пальцем; отпустили дальше трети или быстро — открыта. Закрыть — свайп
// влево по панели или затемнению. Только transform и opacity, кадр — через requestAnimationFrame.
let navDrag = null;
function navMove(e) {
  const d = navDrag; if (!d) return;
  const t = e.touches[0], dx = t.clientX - d.x, dy = t.clientY - d.y;
  if (!d.live) {
    if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
    if (Math.abs(dy) > Math.abs(dx) || (d.open ? dx > 0 : dx < 0)) return navEnd();
    d.live = true; document.body.classList.add("nav-drag"); swipe = null; $("nav").inert = false;
  }
  e.preventDefault(); d.dx = dx; d.v = (dx - d.px) / Math.max(1, e.timeStamp - d.pt); d.px = dx; d.pt = e.timeStamp;
  if (!d.raf) d.raf = requestAnimationFrame(() => {
    d.raf = 0; const x = Math.max(-d.w, Math.min(0, (d.open ? 0 : -d.w) + d.dx));
    $("nav").style.transform = `translateX(${x}px)`; $("navBg").style.opacity = String(1 + x / d.w);
  });
}
function navEnd() {
  const d = navDrag; navDrag = null;
  removeEventListener("touchmove", navMove); removeEventListener("touchend", navEnd); removeEventListener("touchcancel", navEnd);
  if (!d?.live) return;
  cancelAnimationFrame(d.raf); document.body.classList.remove("nav-drag");
  $("nav").style.transform = ""; $("navBg").style.opacity = "";
  const open = d.open ? !(d.dx < -d.w / 3 || d.v < -0.4) : d.dx > d.w / 3 || d.v > 0.4;
  NAV.open = !open; navOpen(open);
}
addEventListener("touchstart", (e) => {
  if (navDrag || !document.body.classList.contains("has-nav") || split() || e.touches.length !== 1 || document.querySelector(".sheet-bg, .pop")) return;
  const t = e.touches[0];
  // в сессии край экрана — «назад» (backDrag); панель там — по ☰
  if (NAV.open ? !e.target.closest?.("#nav, #navBg") : t.clientX > 24 || view === "session") return;
  navDrag = { x: t.clientX, y: t.clientY, w: $("nav").offsetWidth || 300, live: false, open: NAV.open, dx: 0, px: 0, pt: e.timeStamp, v: 0, raf: 0 };
  addEventListener("touchmove", navMove, { passive: false }); addEventListener("touchend", navEnd); addEventListener("touchcancel", navEnd);
}, { passive: true });
// Ctrl+K / ⌘K — палитра: поиск по чатам, проектам и командам (palCmds); Esc — закрыть меню и панель
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.code === "KeyK" || e.key.toLowerCase() === "k") && document.body.classList.contains("has-nav")) { e.preventDefault(); navSearch(true); }
  else if (e.key === "Escape" && document.querySelector(".pop")) closePop();
  else if (e.key === "Escape" && NAV.open) navOpen(false);
});
// ---------- новый чат ----------
// ✎ — сразу пустое поле ввода; папка — текущего чата или последняя, модель — по умолчанию проекта; над полем их можно
// сменить. Окно Claude запускается при ПЕРВОЙ отправке (/api/project/session), без шторки «В какой папке?».
function newChat(pid) {
  closePop(); navOpen(false);
  if (meta?.role === "viewer") return;
  const ps = projOn() ? projData?.projects || [] : [];
  const want = pid || cur()?.project || store("lastProj"), p = ps.find((x) => x.id === want) || ps[0];
  if (!p) return newSession();                       // без проектов (пространство, старый сервер) — прежний выбор папки
  current = null; closeMenu(); hint = ""; DRAFT = { proj: p.id, profile: "" };
  show("session");
  $("tabsBar").hidden = true; $("screenBtn").hidden = true; $("keys").hidden = true; setAsk("");
  $("content").className = "";
  $("content").innerHTML = `<div class="draft">${ic("compose")}<h2 class="serif">Новый чат</h2><p id="draftNote"></p></div>`;
  paintDraft(); renderNav(); padDock(); sync();
  setTimeout(() => $("input").focus(), 60);
}
const readyProfiles = () => (meta?.profiles || []).filter((x) => (!x.needs_key || x.key) && !x.not_ready && !x.no_balance && x.allowed !== false);
function paintDraft() {
  const on = !!DRAFT; document.body.classList.toggle("drafting", on);
  $("draftBar").hidden = !on;
  if (!on) return;
  const p = projOf(DRAFT.proj), prof = profileOf(DRAFT.profile || p?.profile || "claude");
  $("title").textContent = "Новый чат"; $("title").classList.remove("sw");
  setSub(`<span>${esc(p?.name || "")}${prof?.title ? " · " + esc(prof.title) : ""}</span>`);
  if ($("draftNote")) $("draftNote").textContent = `Напишите первое сообщение — чат запустится в папке «${p?.name || ""}». Папку${readyProfiles().length > 1 ? " и модель" : ""} можно сменить над полем ввода.`;
  $("draftBar").innerHTML = `<button class="dchip" type="button" data-dfold aria-haspopup="menu" title="Папка нового чата">${ic("folder")}<span>${esc(p?.name || "Папка")}</span>${ic("chev", "s16")}</button>`
    + (readyProfiles().length > 1 ? `<button class="dchip" type="button" data-dmodel title="Модель нового чата">${ic("chip")}<span>${esc(prof?.title || "Claude")}</span>${ic("chev", "s16")}</button>` : "");
  $("input").placeholder = "Сообщение — новый чат в «" + (p?.name || "") + "»…";
}
$("draftBar").onclick = (e) => {
  if (!DRAFT) return;
  const f = e.target.closest("[data-dfold]"), m = e.target.closest("[data-dmodel]");
  if (f) return popMenu(f, [...(projData?.projects || []).map((p) => ({ label: p.name, icon: "folder", on: p.id === DRAFT.proj, run: () => { DRAFT.proj = p.id; paintDraft(); $("input").focus(); } })),
    { sep: true }, { label: "Новая папка…", icon: "plus", run: () => newFolder() }]);
  if (m) return pickProfile((pid) => { if (DRAFT) { DRAFT.profile = pid; paintDraft(); } });
};
async function draftSend() {
  const text = $("input").value.trim();
  if (!text && !files.length) return toast("Напишите первое сообщение");
  if (files.some((f) => !f.path)) return toast("Подождите — файл ещё загружается");
  const dr = DRAFT, p = projOf(dr.proj), keep = files;
  $("send").disabled = true;
  toast("Запускаю новый чат в «" + (p?.name || "папке") + "»…", 4000);
  try {
    const d = await api("/api/project/session", { id: dr.proj, profile: dr.profile });
    store("lastProj", dr.proj);
    await openSession(d.id);                          // черновик гаснет в show()
    $("input").value = text; files = keep; renderFiles(); grow();
    await sendText();
  } catch (e) { toast("Не вышло: " + e.message, 5000); }
  finally { $("send").disabled = false; }
}
{
  const g = $("sideGrip"); let drag = null;
  g.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault(); g.setPointerCapture(e.pointerId); drag = { x: e.clientX, w: sideW };
    document.body.classList.add("resizing");
  });
  g.addEventListener("pointermove", (e) => { if (drag) setSideW(drag.w + e.clientX - drag.x, false); });
  const end = (e) => {
    if (!drag) return; drag = null; document.body.classList.remove("resizing");
    try { g.releasePointerCapture(e.pointerId); } catch (err) {}
    setSideW(sideW);
  };
  g.addEventListener("pointerup", end); g.addEventListener("pointercancel", end);
  g.addEventListener("dblclick", () => setSideW(SIDE.def));
  g.addEventListener("keydown", (e) => {
    const step = e.shiftKey ? 48 : 16;
    const w = { ArrowLeft: sideW - step, ArrowRight: sideW + step, Home: SIDE.min, End: SIDE.max }[e.key];
    if (w !== undefined) { e.preventDefault(); setSideW(w); }
    else if (e.key === "Enter") { e.preventDefault(); setSideW(SIDE.def); }
  });
}
// Cmd/Ctrl + «+»/«−»/«0» — шрифт панели вместо зума страницы. e.code — та же клавиша в любой раскладке, e.key — запасной путь.
document.addEventListener("keydown", (e) => {
  if (!split() || !(e.metaKey || e.ctrlKey) || e.altKey) return;
  const k = e.key, c = e.code;
  const d = c === "Equal" || c === "NumpadAdd" || k === "=" || k === "+" ? 1
    : c === "Minus" || c === "NumpadSubtract" || k === "-" || k === "_" ? -1
    : c === "Digit0" || c === "Numpad0" || k === "0" ? 0 : null;
  if (d === null) return;
  e.preventDefault();
  setFont(d === 0 ? FONT.def : fontPx + d);
});
