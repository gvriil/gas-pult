// ---------- что работает у поставщика и автотест поставщиков (задача 38, ADR-0002) ----------
// Поля профиля (models.py): limits — не работает, unsure — под вопросом, works — работает ([{id, names}]), alt — какие
// интеграции «Для любой модели» заменяют недоступное. Тексты — словари gap.* / work.*, названия (claude.ai, WebSearch) —
// с сервера. Плашка в сессии — над полем ввода, одной строкой, скрывается для поставщика (localStorage «gaps:<id>»).
const gapText = (g, short) => T((short ? "gap.s." : "gap.") + g.id, { names: g.names || "" });
const workText = (g) => T("work." + g.id, { names: g.names || "" });
const gapShort = (p) => (p?.limits || []).map((g) => gapText(g, true)).join(", ");
const gapPick = (p) => p?.limits?.length ? T("gap.pick", { list: gapShort(p) }) : "";
function gapsHtml(p) {
  if (!p?.limits?.length && !p?.unsure?.length) return "";
  const li = (xs, f, cls) => `<ul class="gaps-l ${cls}">${xs.map((g) => `<li>${ic(cls === "ok" ? "check" : cls === "bad" ? "x" : "warn", "s16")}<span>${esc(f(g))}</span></li>`).join("")}</ul>`;
  return `<div class="gaps">
    ${p.limits.length ? `<div class="name">${esc(T("gap.title"))}</div>${li(p.limits, gapText, "bad")}` : ""}
    ${p.unsure?.length ? `<div class="name">${esc(T("gap.maybe"))}</div>${li(p.unsure, gapText, "maybe")}` : ""}
    ${p.works?.length ? `<div class="name">${esc(T("gap.works"))}</div>${li(p.works, workText, "ok")}` : ""}
    ${p.alt_names ? `<p class="note">${esc(T("gap.alt", { names: p.alt_names }))}</p>
      <button class="btn ghost sm" data-gap-int>${ic("puzzle", "s16")}${esc(T("gap.alt.go"))}</button>` : ""}</div>`;
}
function paintGaps(s) {
  let el = $("gapBar");
  const p = s?.profile && s.profile !== "claude" ? profileOf(s.profile) : null;
  if (!p?.limits?.length || store("gaps:" + p.id) === "hide" || !DICT["gap.short"]) { el?.remove(); return; }
  if (!el) { el = document.createElement("div"); el.id = "gapBar"; el.className = "gapbar"; $("dock").insertBefore(el, $("costPause")); }   // над полем ввода — видно всегда
  const k = p.id + ":" + LANG; if (el.dataset.k === k) return; el.dataset.k = k; el.dataset.p = p.id;
  el.innerHTML = `<button class="gapline" data-gap-more>${ic("warn", "s16")}<span>${esc(T("gap.short", { name: p.short, list: gapShort(p) }))}</span>${ic("chevron", "s16")}</button>
    <button class="icon" data-gap-hide aria-label="${esc(T("gap.hide", { name: p.short }))}" title="${esc(T("gap.hide", { name: p.short }))}">${ic("x", "s16")}</button>`;
}
$("dock").addEventListener("click", (e) => {
  const bar = e.target.closest("#gapBar"); if (!bar) return;
  const p = profileOf(bar.dataset.p); if (!p) return;
  if (e.target.closest("[data-gap-hide]")) { store("gaps:" + p.id, "hide"); bar.remove(); return toast(T("gap.hidden", { name: p.short }), 4500); }
  if (e.target.closest("[data-gap-more]")) gapsView(p, current);
});
function gapsView(p, from) {                          // «что работает и что нет» — из плашки сессии
  show("mcpForm"); formHelp = hv("form.providers"); helpModule = ""; if (from) formBack = () => openSession(from);
  $("title").textContent = p.title; setSub(`<span>${esc(T("gap.more"))}</span>`);
  $("mcpForm").innerHTML = `<div class="panel"><div class="hero">${mono(p.title, p.id)}<h2 class="serif">${esc(p.title)}</h2><p>${esc(p.about || "")}</p></div>${gapsHtml(p)}</div>`;
}
const toIntegrations = () => { show("home"); setHome("integrations"); };
$("mcpForm").addEventListener("click", (e) => {
  if (e.target.closest("[data-gap-int]")) return toIntegrations();
  const a = e.target.closest("[data-p-alt]"); if (a) { const p = mcpData?.presets.find((x) => x.id === a.dataset.pAlt); if (p) mcpForm(p); return; }
  if (e.target.closest("#stRun")) return stRun(e.target.closest("#stRun"));
});
// «Настройки» → «Поставщики»: по каждому — итог суточной проверки (selftest.py) и что работает; «Проверить сейчас».
let stData = null, stTimer = null;
async function providersView() {
  show("mcpForm"); formHelp = hv("form.providers"); helpModule = ""; $("title").textContent = T("st.title"); setSub(`<span>${esc(T("st.sub"))}</span>`);
  $("mcpForm").innerHTML = '<div class="empty">…</div>';
  await dictReady; $("title").textContent = T("st.title"); setSub(`<span>${esc(T("st.sub"))}</span>`);
  try { stData = await api("/api/selftest"); } catch (e) { $("mcpForm").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`; return; }
  renderProviders();
}
function stCard(p) {
  const r = stData.profiles.find((x) => x.id === p.id), chk = r?.checks || {};
  const st = p.id === "claude" ? T("st.claude") : !r ? T("st.nokey") : !r.t ? T("st.never")
    : T("st.when", { when: agoText(r.t) }) + (r.cost != null ? " · " + T("st.cost", { usd: "$" + (+r.cost).toFixed(3) }) : "");
  const chip = r?.t && r.ok ? `<span class="chip ok">${ic("check", "s16")}${esc(T("st.allok"))}</span>` : "";
  return `<div class="card stcard"><div class="row">${mono(p.title, p.id)}<div class="ctext"><div class="name">${esc(p.title)}</div><div class="meta">${esc(st)}</div></div>${chip}</div>
    ${r?.t ? `<div class="conn">${stData.checks.map((c) => `<span class="chip ${chk[c] ? "ok" : "bad"}">${ic(chk[c] ? "check" : "x", "s16")}${esc(T("st.check." + c))}</span>`).join("")}</div>` : ""}
    ${r?.error ? `<div class="result bad">${ic("warn")}<span>${esc(T("st.err", { text: r.error }))}</span></div>` : ""}
    ${p.limits?.length || p.unsure?.length ? `<details class="gaps-d"><summary class="note">${esc(T("gap.more"))}${p.limits?.length ? " · " + esc(gapPick(p)) : ""}</summary>${gapsHtml(p)}</details>`
      : p.works?.length ? `<p class="note gaps-ok">${esc(T("gap.works"))}: ${esc(p.works.map((g) => workText(g)).join(", "))}</p>` : ""}</div>`;
}
function renderProviders() {
  const list = (meta?.profiles || []).filter((p) => p.id === "claude" || p.key);
  const rest = (meta?.profiles || []).filter((p) => p.id !== "claude" && !p.key);
  $("mcpForm").innerHTML = `<div class="panel"><p class="note" style="margin-top:0">${esc(T("st.note"))}</p>
      <button class="btn${stData.running ? " quiet" : ""}" id="stRun" ${stData.running ? "disabled" : ""}>${ic(stData.running ? "wait" : "refresh")}${esc(T(stData.running ? "st.running" : "st.run"))}</button></div>
    ${list.map(stCard).join("")}${rest.map(stCard).join("")}`;
  clearTimeout(stTimer);
  if (stData.running) stTimer = setTimeout(async () => {
    if (view !== "mcpForm" || !$("stRun")) return;
    try { stData = await api("/api/selftest"); renderProviders(); } catch (e) { /* следующая попытка — при новом открытии */ }
  }, 3000);
}
async function stRun(btn) {
  await busy(btn, T("st.running"), async () => {
    try { stData = await api("/api/selftest", {}); toast(T("st.started")); renderProviders(); } catch (e) { toast(e.message, 4500); }
  });
}

// ---------- мастер: Claude Code не установлен или вход не выполнен (setup.py) ----------
let setupData = null, setupMsg = "";
async function loadSetup(fresh) {
  try { setupData = await api("/api/setup/status" + (fresh ? "?fresh=1" : "")); } catch (e) { setupData = null; }
  renderSetup();
}
function renderSetup() {
  const box = $("setupView"), d = setupData;
  box.hidden = !(d && !d.ready && homeView === "sessions");
  if (box.hidden) return;
  const lg = d.login, inst = d.claude?.installed;
  box.innerHTML = `<div class="card setup"><div class="name">Claude не готов</div>
    <div class="meta">${inst ? "Claude Code установлен, но вход не выполнен. Бот и панель работают — войдите, чтобы открывать сессии." : "Claude Code на сервере не установлен. Установите его и нажмите «Проверка»."}</div>
    ${(d.checks || []).map((c) => `<div class="chk ${c.ok ? "" : "bad"}">${ic(c.ok ? "check" : "warn", "s16")}<span>${esc(c.name)}${c.hint ? `<small>${esc(c.hint)}</small>` : ""}</span></div>`).join("")}
    ${lg?.url ? `<div class="section">Вход в Claude</div>
      <p class="note">1. Откройте страницу входа и войдите в аккаунт Claude. 2. Скопируйте код со страницы и вставьте сюда.</p>
      <button class="btn quiet" data-su="open">${ic("ext", "s16")}Открыть страницу входа</button>
      <div class="field" style="margin-top:10px"><div class="inp"><input id="suCode" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="код со страницы входа">
        <button class="btn sm" style="width:auto" data-su="code">Отправить</button></div></div>` : ""}
    <div id="suResult">${setupMsg}</div>
    <div class="acts">
      ${inst ? `<button class="btn sm" data-su="login">${ic("key", "s16")}${lg?.url ? "Начать заново" : "Войти в Claude"}</button>` : ""}
      <button class="btn quiet sm" data-su="int">${ic("plus", "s16")}Интеграции</button>
      <button class="btn quiet sm" data-su="keys">${ic("key", "s16")}Ключ провайдера</button>
      <button class="btn quiet sm" data-su="check">${ic("refresh", "s16")}Проверка</button>
      <button class="btn ghost sm" data-su="doc">${ic("book", "s16")}Инструкция</button></div></div>`;
}
function setupSheet() {
  const d = setupData;
  helpSheet("settings.setup");
  sheet(d?.ready ? "Claude Code готов" : "Claude не готов", [
    ...(d?.checks || []).map((c) => ({ info: true, icon: c.ok ? "check" : "warn", label: c.name, sub: c.hint })),
    ...(d && !d.ready && d.claude?.installed ? [{ label: "Войти в Claude", icon: "key", run: () => { show("home"); setHome("sessions"); setupAct("login"); } }] : []),
    { label: "Проверить ещё раз", icon: "refresh", run: async () => { await loadSetup(true); setupSheet(); } },
    { label: "Инструкция: если вход через пульт невозможен", icon: "book", run: () => openUrl(d?.doc || "https://github.com/gvriil/gas-pult/blob/main/docs/SETUP-CLAUDE.md") },
  ]);
}
const suNote = (cls, text) => `<div class="result ${cls}">${ic(cls === "ok" ? "check" : cls === "bad" ? "warn" : "wait")}<span>${esc(text)}</span></div>`;
async function setupAct(act, btn) {
  const say = (cls, text) => { setupMsg = suNote(cls, text); renderSetup(); };
  if (act === "open") return openUrl(setupData.login.url);
  if (act === "doc") return openUrl(setupData.doc);
  if (act === "int" || act === "keys") { setHome("integrations"); if (act === "keys") setTimeout(() => $("modelsBox")?.scrollIntoView({ behavior: "smooth" }), 300); return; }
  if (act === "check") { setupMsg = ""; return busy(btn, "Проверяю…", () => loadSetup(true)); }
  if (act === "login") {
    say("wait", "Запускаю вход в отдельном окне tmux — до 20 секунд…");
    try {
      const r = await api("/api/setup/login", {});
      setupData = { ...setupData, login: r };
      setupMsg = r.url ? "" : suNote("bad", "Claude Code не показал ссылку входа. " + (r.lines || []).slice(-3).join(" · "));
    } catch (e) { setupMsg = suNote("bad", e.message); }
    return renderSetup();
  }
  if (act === "code") {
    const code = $("suCode").value.trim(); if (!code) return $("suCode").focus();
    return busy(btn, "Проверяю…", async () => {
      try {
        const r = await api("/api/setup/code", { code });
        if (r.ok) { setupMsg = ""; toast("Вход в Claude выполнен"); await loadSetup(true); return; }
        say("bad", "Вход не подтвердился" + (r.error ? ": " + r.error : "") + ". Проверьте код и отправьте ещё раз.");
      } catch (e) { say("bad", e.message); }
    });
  }
}
$("setupView").addEventListener("click", (e) => { const b = e.target.closest("[data-su]"); if (b) setupAct(b.dataset.su, b); });
$("setupView").addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.id === "suCode") { e.preventDefault(); setupAct("code", e.target.nextElementSibling); } });

// ---------- дежурный помощник «? Подсказать» (helper.py, docs/HELPER.md) ----------
// Экран для помощника: вид (helpViewId), открытый лист (data-help у .sheet-bg, ставит helpSheet("…") перед sheet() или
// hv("…") у своих листов), форма (formHelp), выбранный модуль. Ответ — из карты экранов, без модели, с кнопками
// «Перейти: …»: только id из карты, их открывает go(id). Демо (?demo) отвечает из help-map.json — той же карты.
let helpNext = "", formHelp = "", helpModule = "";
const hv = (id) => id;
// Демо «Нужен вход»: ?login=claude|gh|mcp на окне @1 (заведомо поддельные ссылки и коды)
const DEMO_LOGIN = {
  claude: { kind: "claude", service: "Claude", url: "https://claude.ai/oauth/authorize?code=true&client_id=demo&state=demo", code: "", wants: "code" },
  gh: { kind: "gh", service: "GitHub", url: "https://github.com/login/device", code: "AB12-CD34", wants: "" },
  mcp: { kind: "mcp", service: "notion", url: "https://mcp.example.invalid/authorize?client_id=demo", code: "", wants: "url" },
};                                 // id экрана помощника (тест сверяет их с картой)
function helpSheet(id) { helpNext = id; }
function helpViewId() {
  if (SIM.on) return hv("simple.chat");
  if (view === "login") return hv("login");
  if (view === "terms") return hv("terms");
  if (view === "country") return hv("country");
  if (view === "persona") return hv("persona");
  if (view === "mcpForm") return formHelp || hv("modules");
  if (view === "session") return !$("menu").hidden ? hv("session.menu") : tab === "screen" ? hv("session.screen") : hv("session.chat");
  if (homeView === "sessions" && setupData && !setupData.ready) return hv("setup");
  if (homeView === "sessions" && projMode()) return proj ? hv("home.project") : hv("home.projects");
  return { commands: hv("home.commands"), integrations: hv("home.integrations") }[homeView] || hv("home.sessions");
}
const helpVisible = (b) => b.offsetParent !== null && !b.closest("[hidden]");
function helpContext() {                               // всё, что помощнику нужно знать об экране, — одной функцией
  const top = [...document.querySelectorAll(".sheet-bg:not(.help-bg)")].at(-1);
  const box = top || (SIM.on ? $("simple") : $(view === "session" ? "session" : view)) || document.body;
  const title = (top ? top.querySelector("h3")?.textContent : SIM.on ? $("sWho").textContent : $("title").textContent) || "";
  const buttons = [...box.querySelectorAll("button")].filter(helpVisible).map((b) => clean(b.textContent).slice(0, 40)).filter(Boolean).slice(0, 12);
  return { screen: top?.dataset.help || helpViewId(), step: view === "session" ? tab : "", module: helpModule, title: clean(title).slice(0, 80), buttons };
}
const goHome = (v) => { show("home"); setHome(v); };
function goSession(t) {
  const id = (current && sessions.some((x) => x.id === current) && current) || sessions.find((x) => x.id === store("last"))?.id
    || sessions.find((x) => x.active)?.id || sessions[0]?.id;
  if (!id) { toast("Сессий пока нет — откройте новую", 3500); return Promise.resolve(false); }
  if (view === "session" && current === id) { if (tab !== t) setTab(t); return Promise.resolve(true); }
  return openSession(id, t).then(() => true);
}
const HELP_GO = {                                      // действие карты → экран панели (все id — из screens.toml)
  "go:sessions": () => { if (projOn()) setMode("sessions"); goHome("sessions"); },
  "go:new-session": () => { goHome("sessions"); newSession(); },
  "go:new-folder": () => newFolder(),
  "go:modules": () => modulesView(),
  "go:scenarios": () => scenariosView(),
  "go:commands": () => goHome("commands"),
  "go:integrations": () => goHome("integrations"),
  "go:models": () => { goHome("integrations"); setTimeout(() => $("modelsBox")?.scrollIntoView({ behavior: "smooth" }), 400); },
  "go:voice": () => { goHome("integrations"); setTimeout(() => $("voiceBox")?.scrollIntoView({ behavior: "smooth" }), 600); },
  "go:switch": () => (sessions.length ? openSwitcher() : goHome("sessions")),
  "go:session.chat": () => goSession("chat"),
  "go:session.screen": () => goSession("screen"),
  "go:session.menu": () => goSession("chat").then((ok) => { if (ok && $("menu").hidden) $("menuBtn").click(); }),
  "go:session.model": () => goSession("chat").then((ok) => ok && ACTIONS.models()),
  "go:settings": () => $("settingsBtn").onclick(),
  "go:settings.country": () => showCountry(true),
  "go:settings.cost": () => costSheet(),
  "go:settings.limits": () => limitsForm(),
  "go:settings.people": () => peopleSheet(),
  "go:settings.setup": () => (setupData ? setupSheet() : loadSetup(true).then(setupSheet)),
  "go:settings.legend": () => legend(),
  "go:login": () => { showLogin(); $("tgLogin").focus(); },
  "go:demo": () => { location.href = "/?demo"; },
  "go:simple.chat": () => simpleGo(),
  "go:simple.agents": () => simpleGo().then(sAgents),
  "go:simple.new-agent": () => simpleGo().then(sNewAgent),
  "go:simple.settings": () => simpleGo().then(sSettings),
  "go:settings.caps": () => capsSheet(),
  "go:persona": () => showPersona(true),
  "go:settings.team": () => teamSheet(),
};
function go(id) {
  const f = HELP_GO[id];
  if (!f) return toast(L("s.fail", "Этот переход недоступен"));
  document.querySelectorAll(".sheet-bg").forEach((x) => x.remove());   // «Перейти» — новый путь: листы закрываем
  closeMenu(); f();
}
function helpAnswer(r) {
  const box = document.createElement("div"); box.className = "ha"; box.dataset.id = r.id;
  box.innerHTML = `<p>${esc(r.text)}</p>
    ${r.actions.length ? `<div class="hgo">${r.actions.map((a) => `<button data-go="${esc(a.id)}"${a.enable ? ` data-enable="${esc(a.enable)}"` : ""}>${ic(a.enable ? "bolt" : "chevron", "s16")}${esc((a.enable ? L("help.enable", "Включить и перейти: {t}") : L("help.go", "Перейти: {t}")).replace("{t}", a.title))}</button>`).join("")}</div>` : ""}
    <div class="hfoot"><span class="hmark">${esc(L("help.mark", "Подсказка из карты"))}</span>
      <button class="hfb" data-fb="1" aria-label="${esc(L("help.useful", "Помогло"))}">${ic("check")}</button><button class="hfb" data-fb="0" aria-label="${esc(L("help.useless", "Не помогло"))}">${ic("x")}</button></div>`;
  return box;
}
async function helpAsk(bg, body, label) {
  const msgs = bg.querySelector(".hmsgs"), ctx = bg.ctx;
  if (label) msgs.insertAdjacentHTML("beforeend", `<div class="hq">${esc(label)}</div>`);
  const wait = document.createElement("div"); wait.className = "ha wait"; wait.textContent = L("help.thinking", "Думаю…"); msgs.append(wait);
  msgs.scrollTop = msgs.scrollHeight;
  try {
    const r = await api("/api/help/ask", { ctx, ...body, ...(SIM.on || view === "login" ? { lang: LANG } : {}) });
    wait.replaceWith(helpAnswer(r));
    bg.querySelector(".hwhere").textContent = L("help.where", "Экран: {t}").replace("{t}", r.title);
    bg.querySelector(".hchips").innerHTML = r.chips.filter((c) => c.id !== body.chip).map((c) => `<button data-chip="${esc(c.id)}">${esc(c.label)}</button>`).join("");
  } catch (e) { wait.className = "ha"; wait.innerHTML = `<p class="hnote">${esc(e.message)}</p>`; }
  msgs.scrollTop = msgs.scrollHeight;
}
function openHelp() {
  if (document.querySelector(".help-bg")) return;
  const bg = document.createElement("div"); bg.className = "sheet-bg help-bg"; bg.ctx = helpContext();
  bg.innerHTML = `<div class="sheet help" role="dialog" aria-label="${esc(L("help.title", "Помощник"))}"><h3>${ic("help", "s16")}${esc(L("help.title", "Помощник"))}</h3><div class="hwhere"></div>
    <div class="hmsgs" aria-live="polite"></div><div class="hchips"></div>${view === "login" || SIM.on ? "" : `<button class="htour" data-tour-here>${ic("spark", "s16")}Показать тур по этому экрану</button>`}
    <form class="hrow"><input name="q" maxlength="500" autocomplete="off" enterkeyhint="send" placeholder="${esc(L("help.ask", "Спросите, что непонятно…"))}" aria-label="${esc(L("help.ask.aria", "Вопрос помощнику"))}">
      <button class="hsend" type="submit" aria-label="${esc(L("help.send", "Спросить"))}">${ic("send")}</button></form>
    <button class="cancel" data-close>${esc(L("help.close", "Закрыть"))}</button></div>`;
  bg.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (e.target === bg || b?.hasAttribute("data-close")) return bg.remove();   // лист под ним остаётся
    if (!b) return;
    if (b.hasAttribute("data-tour-here")) { bg.remove(); return startTour(tourKind(), true); }
    const id = b.closest(".ha")?.dataset.id;
    if (b.dataset.chip) return helpAsk(bg, { chip: b.dataset.chip }, b.textContent);
    if (b.dataset.fb) {
      b.parentElement.querySelectorAll(".hfb").forEach((x) => x.classList.toggle("on", x === b));
      api("/api/help/feedback", { id, useful: b.dataset.fb === "1" }).catch(() => {});
      return toast(b.dataset.fb === "1" ? L("help.thanks", "Спасибо!") : L("help.thanks.bad", "Спасибо — поправим подсказку"));
    }
    if (b.dataset.go) {
      api("/api/help/feedback", { id, action: b.dataset.go }).catch(() => {}); haptic("selectionChanged");
      return b.dataset.enable ? enableAndGo(b.dataset.enable, b.dataset.go) : go(b.dataset.go);
    }
  });
  bg.querySelector("form").addEventListener("submit", (e) => {
    e.preventDefault(); const inp = e.target.q, q = inp.value.trim(); if (!q) return inp.focus();
    inp.value = ""; helpAsk(bg, { q }, q);
  });
  document.body.append(bg);
  helpAsk(bg, { chip: "what" });
}
$("helpBtn").onclick = () => { haptic("selectionChanged"); openHelp(); };
// Пилюля «? Подсказать» — и в каждом листе: шторка помощника откроется поверх него и вернёт к нему.
new MutationObserver(() => {
  document.querySelectorAll(".sheet-bg:not(.help-bg) > .sheet:not(.hp)").forEach((sh) => {
    sh.classList.add("hp");
    const b = document.createElement("button"); b.className = "hpill insheet"; b.type = "button";
    b.setAttribute("aria-label", L("help.sheet", "Подсказать: что делать в этом листе")); b.innerHTML = ic("help") + `<span>${esc(L("s.help", "Подсказать"))}</span>`;
    b.addEventListener("click", (e) => { e.stopPropagation(); openHelp(); });
    sh.prepend(b);
  });
}).observe(document.body, { childList: true });
// Демо: ответы помощника из той же карты (help-map.json), как на сервере.
async function demoHelp(b) {
  demoHelp.map ||= await fetch("help-map.json").then((r) => r.json());
  const m = demoHelp.map, role = view === "login" ? "anon" : params.get("role") || "owner";
  const own = (id) => m.screens[id] && m.screens[id].roles.includes(role);
  const sid = own(b.ctx?.screen) ? b.ctx.screen : role === "anon" ? "login" : "home.sessions", s0 = m.screens[sid];
  const en = b.lang === "en" && !!s0.title_en, loc = (x) => (en && x ? { ...x, title: x.title_en || x.title, purpose: x.purpose_en, steps: x.steps_en, q: x.q_en, a: x.a_en } : x);
  const s = { ...loc(s0), faq: s0.faq.map(loc) };              // английский — только у экранов простого режима и входа
  const faq = [...s.faq.filter((f) => !f.roles.length || f.roles.includes(role))];
  if (!s0.title_en) m.faq.forEach((f) => { if (f.roles.includes(role) && !faq.some((x) => x.id === f.id)) faq.push(f); });
  const mine = (m.personas?.[UI?.persona]?.faq || []).map(loc);                  // вопросы роли — первыми чипами
  faq.push(...mine.filter((f) => !faq.some((x) => x.id === f.id)));
  const acts = (ids) => [...new Set(ids)].filter((a) => m.actions[a]?.roles.includes(role))
    .map((a) => ({ id: a, title: en ? m.actions[a].title_en || m.actions[a].title : m.actions[a].title, cap: m.actions[a].cap }))
    .filter((a) => !UI || !a.cap || UI.caps.includes(a.cap) || UI.ceiling.includes(a.cap))
    .map(({ cap: c, ...a }) => (UI && c && !UI.caps.includes(c) ? { ...a, enable: c } : a)).slice(0, 3);
  const chips = [{ id: "what", label: en ? "What can I do here?" : "Что здесь делать?" }, ...mine.map((f) => ({ id: f.id, label: f.q })),
    ...s.chips.map((c) => faq.find((f) => f.id === c)).filter(Boolean).map((f) => ({ id: f.id, label: f.q }))];
  const out = { id: "demo" + Date.now(), screen: sid, title: s.title, chips, mode: "offline" };
  const f = b.chip && faq.find((x) => x.id === b.chip);
  if (b.chip === "explain") return { ...out, text: (en ? "In plain words: " : "Если совсем просто: ") + s.purpose + " " + s.steps.map((x, i) => `${i + 1}) ${x}`).join(" "), actions: acts(s.next) };
  if (f) return { ...out, text: f.a, actions: acts(f.actions.length ? f.actions : s.next) };
  if (b.q) {                                        // простое ранжирование слов, как на сервере
    const w = (t) => new Set(String(t).toLowerCase().replace(/ё/g, "е").match(/[а-яa-z0-9]{3,}/g)?.map((x) => x.slice(0, 5)) || []);
    const q = w(b.q), best = faq.map((x) => [[...w(x.q + " " + x.a)].filter((y) => q.has(y)).length, x]).sort((a, c) => c[0] - a[0])[0];
    if (best && best[0]) return { ...out, text: best[1].a, actions: acts(best[1].actions.length ? best[1].actions : s.next) };
    return { ...out, text: (en ? "No exact answer in the tips. On this screen: " : "Точного ответа в подсказках нет. На этом экране: ") + s.purpose, actions: acts(s.next) };
  }
  return { ...out, text: s.purpose + " " + s.steps.map((x, i) => `${i + 1}) ${x}`).join(" "), actions: acts(s.next) };
}
// «Включить и перейти»: помощник предложил экран, которого нет в виде человека, — сервер включает возможность (только
// если права позволяют), потом переход. Сменился режим целиком (простой ⇄ полный) — панель заново, сразу на экран.
async function enableAndGo(c, id) {
  const was = UI?.simple;
  try { UI = await api("/api/persona", { add: { [c]: true } }); } catch (e) { return toast(e.message, 4000); }
  applyCaps();
  if (UI.simple !== was) { if (DEMO) { const u = demoUrl(); u.hash = "go=" + id; location.replace(u); return; } location.hash = "go=" + id; return location.reload(); }
  go(id);
}
function goFromLink() {                                // #go=<id> из бота («📱 Открыть в панели») — сразу на нужный экран
  const id = new URLSearchParams(location.hash.slice(1)).get("go") || params.get("go");
  if (id && /^go:[a-z0-9.\-]+$/.test(id)) setTimeout(() => go(id), 300);
  const sid = params.get("session");                  // «📱 Открыть сессию» из бота (зов тестировщика на помощь)
  if (sid && !DEMO && !SIM.on) setTimeout(async () => { await refresh(); if (sessions.some((x) => x.id === sid)) openSession(sid); }, 300);
}

// ---------- короткий тур (docs/MINI_APP.md#тур) ----------
// Шаги {target, title, text} — по data-tour="…" (данные — #tourData); шага, чьего элемента нет на экране (скрыт
// ролью, шириной или ещё не открыт), нет. Предложение «Пройти короткий тур?» — один раз; дальше — «Настройки» →
// «Пройти тур» и «? Подсказать» → «Показать тур по этому экрану». Отметки done/dismissed — на сервере (/api/tour),
// у каждого свои; localStorage — только кэш. driver.js грузится с cdnjs только при старте тура (точная версия + SRI).
const DRIVER = {
  js: "https://cdnjs.cloudflare.com/ajax/libs/driver.js/1.8.0/driver.js.iife.min.js",
  jsSri: "sha512-RhwyYBNqTj+hAVmH3cyZhZ+1ExPTW3lYtpiCQrC//Oiugjd/oTHIQRVP1IhEvqcccyP4+rcSuf/1nudX3pOXxQ==",
  css: "https://cdnjs.cloudflare.com/ajax/libs/driver.js/1.8.0/driver.min.css",
  cssSri: "sha512-dBiCVIs5ayOv4qwu3u8yf+CvdLI2kFdXijpYiU5nM6mO61QRXzExoENn5nJiF3n8uBW/yEO+FoLLuYbkj8/frg==",
};
const TOURS = JSON.parse($("tourData").textContent), TOUR_KINDS = ["dev", "business"];
let tourOn = false;
const tourKind = () => TOURS[store("tourKind")] ? store("tourKind") : meta?.role === "viewer" ? "business" : "dev";
const tourKey = () => "tour:" + (meta?.uid ?? "");
const tourEl = (t) => [...document.querySelectorAll(`[data-tour="${t}"]`)].find((el) => el.getClientRects().length && !el.closest("[hidden]"));
function tourCache(v) {
  if (v) return store(tourKey(), JSON.stringify(v));
  try { return JSON.parse(store(tourKey()) || "null"); } catch (e) { return null; }
}
function saveTour(kind, state) {                       // сразу в кэш, потом на сервер; сервер недоступен — останется кэш
  tourCache({ ...(tourCache() || {}), [kind]: state });
  api("/api/tour", { tour: kind, state }).catch(() => {});
}
function loadDriver() {                                // driver.js 1.8.0 — только когда тур запускают
  if (window.driver?.js?.driver) return Promise.resolve(window.driver.js.driver);
  return (loadDriver.p ||= new Promise((ok, no) => {
    const css = Object.assign(document.createElement("link"), { rel: "stylesheet", href: DRIVER.css, integrity: DRIVER.cssSri, crossOrigin: "anonymous" });
    const js = Object.assign(document.createElement("script"), { src: DRIVER.js, integrity: DRIVER.jsSri, crossOrigin: "anonymous" });
    const fail = () => { clearTimeout(t); css.remove(); js.remove(); loadDriver.p = null; no(new Error("нет связи")); };
    const t = setTimeout(fail, 12000);
    js.onload = () => { clearTimeout(t); window.driver?.js?.driver ? ok(window.driver.js.driver) : fail(); };
    js.onerror = fail;
    document.head.append(css, js);
  }));
}
async function tourWait(targets, ms = 1500) {         // экран дорисовывается после перехода — ждём шаги, не дольше ms
  const t0 = Date.now();
  while (Date.now() - t0 < ms && !targets.every((t) => tourEl(t))) await new Promise((r) => setTimeout(r, 100));
}
async function tourGo(screen) {                        // перейти на экран шагов; false — экран недоступен
  if (screen === "home") { if (view !== "home" || homeView !== "sessions") goHome("sessions"); await refresh(); return true; }
  if (screen === "session") return sessions.length ? goSession("chat") : false;
  if (screen === "integrations") { if (meta?.role === "viewer") return false; if (view !== "home" || homeView !== "integrations") goHome("integrations"); return true; }
  return true;
}
function tourRun(drv, steps, label, more) {           // один экран тура; "next" — дальше, "close" — закрыли (Esc, ×)
  return new Promise((done) => {
    let how = "close";
    const d = drv({
      showProgress: true, progressText: `${label} · {{current}} из {{total}}`, nextBtnText: "Далее", prevBtnText: "Назад",
      doneBtnText: more ? "Дальше" : "Готово", popoverClass: "gp-tour", overlayColor: "#000", overlayOpacity: 0.5,
      stagePadding: 6, stageRadius: 12, smoothScroll: false, allowKeyboardControl: true,
      steps: steps.map((s) => ({ element: () => tourEl(s.target), popover: { title: esc(s.title), description: esc(s.text) } })),
      onPopoverRender: (p) => p.closeButton.setAttribute("aria-label", "Закрыть тур"),
      onDoneClick: () => { how = "next"; d.destroy(); },
      onDestroyed: () => done(how),
    });
    d.drive();
  });
}
async function startTour(kind = tourKind(), here = false) {
  if (tourOn || !TOURS[kind]) return;
  const from = document.activeElement;
  hideTourOffer();
  document.querySelectorAll(".sheet-bg").forEach((x) => x.remove()); closeMenu();
  let drv;
  try { drv = await loadDriver(); } catch (e) { return toast("Тур недоступен — нет связи", 3500); }
  saveTour(kind, "done");
  const all = TOURS[kind].steps, segs = [];
  if (here) segs.push({ screen: "here", steps: all.filter((s) => tourEl(s.target)) });   // только то, что на экране сейчас
  else all.forEach((s) => (segs.at(-1)?.screen === s.screen ? segs.at(-1).steps.push(s) : segs.push({ screen: s.screen, steps: [s] })));
  const reach = (g) => g.screen !== "session" || sessions.length;
  const NAMES = { home: "Главная", session: "Сессия", integrations: "Интеграции", any: "Везде", here: "Этот экран" };
  tourOn = true;
  let shown = 0, how = "close";
  try {
    for (let i = 0; i < segs.length; i++) {
      const g = segs[i];
      if (!here && !(await tourGo(g.screen))) continue;
      await tourWait(g.steps.map((s) => s.target));
      const steps = g.steps.filter((s) => tourEl(s.target));
      if (!steps.length) continue;
      shown += steps.length;
      how = await tourRun(drv, steps, NAMES[g.screen] + " · " + TOURS[kind].title, segs.slice(i + 1).some(reach));
      if (how !== "next") break;
    }
  } finally { tourOn = false; }
  if (!shown) toast("На этом экране тура нет — «Настройки» → «Пройти тур»", 3500);
  else if (how === "next") toast("Тур пройден. Повторить — «Настройки» → «Пройти тур»", 3500);
  const back = from?.isConnected && from !== document.body ? from : $("helpBtn");   // фокус — туда, откуда начали
  if (!document.querySelector(".sheet-bg")) back.focus?.();
}
function hideTourOffer() { document.getElementById("tourOffer")?.remove(); }
function showTourOffer() {
  if (document.getElementById("tourOffer")) return;
  let kind = tourKind();
  const box = document.createElement("div"); box.className = "tour-offer"; box.id = "tourOffer";
  box.setAttribute("role", "dialog"); box.setAttribute("aria-label", "Предложение пройти тур");
  box.innerHTML = `<div class="row">${ic("spark")}<div class="ctext"><b>Пройти короткий тур?</b>
      <div class="meta">Минута — главное о панели. Потом — «Настройки» → «Пройти тур» или «? Подсказать».</div></div>
      <button class="icon" data-tno aria-label="Не сейчас">${ic("x", "s16")}</button></div>
    <div class="seg" role="group" aria-label="Для кого тур">${TOUR_KINDS.map((k) => `<button data-tkind="${k}" class="${k === kind ? "on" : ""}" aria-pressed="${k === kind}">${k === "dev" ? "Разработчику" : "Бизнесу"}</button>`).join("")}</div>
    <div class="acts"><button class="btn quiet sm" data-tno>Не сейчас</button><button class="btn sm" data-tgo>Пройти</button></div>`;
  const no = () => { hideTourOffer(); saveTour(kind, "dismissed"); };
  box.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.tkind) { kind = b.dataset.tkind; box.querySelectorAll("[data-tkind]").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-pressed", x === b); }); return; }
    if (b.hasAttribute("data-tno")) return no();
    if (b.hasAttribute("data-tgo")) { store("tourKind", kind); startTour(kind); }
  });
  box.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); no(); } });
  notice(box);
}
async function tourOffer() {                           // один раз: сервер говорит, что тур не пройден и не отклонён
  if (tourOffer.asked || (DEMO && !params.get("tour")) || !meta) return;
  if ((meta.role === "owner" || UI?.own_space) && !(DEMO && params.get("tour"))) return;   // владельцу — только по его кнопке
  tourOffer.asked = true;
  const has = (r) => !!(r && (r.business || r.dev)), local = tourCache();
  let remote;
  try { remote = await api("/api/tour"); } catch (e) { remote = undefined; }
  if (remote === undefined) { if (!has(local)) showTourOffer(); return; }   // сервер не ответил — решаем по кэшу
  if (has(remote)) return void tourCache(remote);                            // отметка на сервере — в кэш
  if (has(local)) return TOUR_KINDS.forEach((k) => local[k] && api("/api/tour", { tour: k, state: local[k] }).catch(() => {}));   // только в кэше — на сервер
  showTourOffer();
}
