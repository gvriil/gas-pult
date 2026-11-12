// ---------- старт ----------
async function start() {
  try { meta = await api("/api/meta"); BUILD = meta.build; } catch (e) { if (view !== "login") setSub(`<span>нет связи: ${esc(e.message)}</span>`); return; }
  loadSpaces().then(() => { if (spacesInfo?.tenants?.length && view === "home") refresh(); });   // группа «Пространства»
  if (meta.terms && !meta.terms.accepted) return showTerms();     // сначала условия использования
  if (meta.country?.need) return showCountry();                   // потом — страна
  UI = meta.ui || null; applyCaps();
  document.body.classList.toggle("tester", !!meta.space);         // тестировщик демо-пространства (задача 31)
  if (UI && !UI.onboarded && !UI.own_space && meta.role !== "owner" && (!DEMO || params.has("persona"))) return showPersona();   // роль — один раз, не владельцу
  paintSpaces();
  if (simplePrefs(meta).simple) return simpleStart();              // простой режим — свой экран, полный не запускаем
  $("helpBtn").innerHTML = ic("help") + "<span>Подсказать</span>";  // после первого экрана на английском
  document.body.dataset.role = meta.role || "owner";             // роль: владелец / участник / наблюдатель
  if (meta.role === "viewer" && !$("viewOnly")) $("composer").insertAdjacentHTML("afterend", '<div class="viewonly" id="viewOnly">Доступ только на просмотр</div>');
  $("keys").innerHTML = meta.keys.map((k) => `<button data-key="${esc(k.key)}"${k.key === "C-c" ? ' class="ctrlc" aria-label="Прервать команду: Ctrl+C"' : ""}>${esc(k.label)}</button>`).join("");
  if (!meta.voices.length) document.querySelectorAll("#menu [data-act^=say]").forEach((b) => (b.hidden = true));
  if (meta.role === "owner") await loadSetup();
  show("home"); setHome(params.get("view") === "integrations" ? "integrations" : "sessions");
  const wn = meta.whatsnew?.[0];
  if (wn && store("whatsnew") !== wn.id && !DEMO) {
    store("whatsnew", wn.id);
    if (store("seenAny")) { helpSheet("whatsnew"); sheet(wn.title, wn.items.map((t) => ({ info: true, label: t, icon: "check" })), "Понятно"); }
  }
  store("seenAny", "1");
  start.poll ||= () => tourOn || refresh();          // общий секундный тик (tick, pollDue); во время тура экран не перерисовываем
  start.done = true; afterPaint(mdLoad);
  setTimeout(tourOffer, 1200);
  keepAwake();
  let resume = null;
  try { resume = JSON.parse(sessionStorage.getItem("resume") || "null"); sessionStorage.removeItem("resume"); } catch (e) {}
  if (resume?.id && !DEMO) { await refresh(); if (sessions.some((x) => x.id === resume.id)) await openSession(resume.id, resume.tab); }
  // Чат прежде всего: на телефоне панель сразу открывает последнюю сессию (открытую здесь, иначе активную в чате бота).
  if (view !== "session" && !split() && !params.has("open") && !params.has("home") && !params.has("prof") && !params.has("cmds")
      && !params.has("view") && !params.has("modules") && !(setupData && !setupData.ready)) {
    if (!sessions.length) await refresh();
    const live = sessions.filter((x) => x.status !== "stopped");
    const pick = sessions.find((x) => x.id === store("last")) || live.find((x) => x.active)
      || [...live].sort((a, b) => ORDER[a.status] - ORDER[b.status])[0];
    if (pick) await openSession(pick.id);
  }
  if (params.has("cmds")) setHome("commands");            // ?cmds — сразу вкладка «Команды»
  if (DEMO && params.get("project") && projOn()) {        // ?demo&home&proj&project=p-books&ptab=done&pchat=<id> — «Проекты»
    await refresh(); await openProject(params.get("project"), params.get("ptab") || "active");
    if (params.get("pchat")) { await loadDone(); chatView(params.get("pchat") === "1" ? projDone?.chats[0]?.sid : params.get("pchat")); }
  }
  if (DEMO && params.get("open")) {
    await refresh(); await openSession(params.get("open"));
    if (params.get("menu")) $("menuBtn").click();
    if (params.get("pending")) { pending = [{ text: "Проверь, что сообщение видно сразу", state: "sent" }]; renderChat(false); }
    if (params.get("files")) { files = [{ name: "фото-стенда.jpg", path: "/x" }, { name: "отчёт-П8.xlsx", path: null }]; renderFiles(); }
    if (params.get("model")) ACTIONS.models();
    if (params.get("expand")) setTimeout(() => document.querySelectorAll("details.log").forEach((d) => (d.open = true)), 1500);
    if (params.get("mic")) {                        // для скриншота: вместо микрофона — синтетический звук
      navigator.mediaDevices.getUserMedia = async () => { const c = new AudioContext(), o = c.createOscillator(), d = c.createMediaStreamDestination(); o.connect(d); o.start(); return d.stream; };
      toggleMic();
      if (params.get("mic") === "stop") setTimeout(() => rec?.stop(), 1500);   // ?mic=stop — сразу «Распознаю…» (и &stt=…)
    }
  }
  if (DEMO && ["prof", "pick", "prov", "gaps", "conn"].some((k) => params.has(k))) await dictReady;   // что недоступно — из словаря
  if (DEMO && params.get("prof")) { profileForm(profileOf(params.get("prof")), params.has("connected")); if (params.get("cat")) openCatalog($("profMain")); }
  if (DEMO && params.get("pick")) pickProfile(() => {});
  if (DEMO && params.has("prov")) providersView();
  if (DEMO && params.get("gaps")) gapsView(profileOf(params.get("gaps")));
  if (params.get("view") === "scenarios") {          // из бота «📱 Примерить в панели» (?view=scenarios&role=…); в демо — &step=N
    await scenariosView(params.get("role") || null);
    if (scn && params.get("step")) { scn.step = Math.min(+params.get("step") || 0, scn.r.timeline_steps.length + 1); scnRender(); }
  }
  if (params.get("term") && meta?.role === "owner") termSheet(params.get("term"));
  if (params.get("tty") && ttyOk()) ttyOpen(params.get("tty"));   // ?tty=@1 — живой терминал окна сразу (задача 50)   // из бота: «⌨️ Терминал в браузере»
  if (DEMO && params.has("modules")) { await modulesView(); if (params.get("modules")) moduleView(modData.modules.find((m) => m.id === params.get("modules"))); }
  if (DEMO && params.has("repos")) { if (!sessions.length) await refresh(); repoSheet(params.get("repos") || "@3"); }   // ?repos[=@1|t:demo:@1&spaces] — репозитории сессии
  if (DEMO && params.get("conn")) { mcpData = await api("/api/mcp"); connectorView(mcpData.connectors.find((c) => c.id === params.get("conn"))); }
  if (DEMO && params.get("form")) { mcpData = await api("/api/mcp"); mcpForm(mcpData.presets.find((p) => p.id === params.get("form"))); }
  restoreDraft();                                     // черновик — после того, как открылась сессия
  voiceRestore();                                     // слушали ответ до перезагрузки — мини-плеер на том же месте
  goFromLink();
}

// ---------- роли интерфейса (personas.py, docs/MINI_APP.md#роли): вид панели отдельно от прав ----------
// Сервер присылает вид в /api/meta (ui): роль, возможности cap.* (уже с потолком по правам), справочник. Панель только
// показывает или прячет части (body.nocap-…) и выбирает экран: без «Сессий» (cap.dev_sessions) — простой режим (чат).
let UI = null;
const PERSONA_ICON = { business_owner: "coin", point_admin: "place", project_manager: "tasks", student: "book", developer: "term" };
const cap = (c) => !UI || UI.caps.includes("cap." + c);
function applyCaps() {
  for (const c of UI?.catalog?.caps || []) document.body.classList.toggle("no" + c.id.replace(".", "-"), !UI.caps.includes(c.id));
}
const personaTitle = (id) => UI?.catalog?.personas.find((p) => p.id === id)?.title || id;
async function showPersona(change) {                  // первый вход — 5 карточек; из настроек — «Сменить роль целиком»
  await dictReady;
  if (SIM.on) simpleHide();
  start.poll = null;
  show("persona"); $("title").textContent = T("login.brand"); setSub(`<span>${esc(T("persona.sub.short"))}</span>`);
  const list = UI?.catalog?.personas || [];
  $("personaBox").innerHTML = `<h2 class="serif">${esc(T("persona.title"))}</h2><p class="ver">${esc(T(change ? "persona.change.sub" : "persona.sub"))}</p>
    <div class="pcards" role="group" aria-label="${esc(T("persona.title"))}">${list.map((p) => `<button class="pcard${change && p.id === UI.persona ? " on" : ""}" data-persona="${esc(p.id)}" aria-pressed="${!!change && p.id === UI.persona}">${ic(PERSONA_ICON[p.id] || "spark")}<span><b>${esc(p.title)}</b><small>${esc(p.sub)}</small></span></button>`).join("")}</div>
    ${change ? `<button class="btn ghost" id="personaBack">${esc(T("s.close"))}</button>` : ""}<div id="personaResult"></div>`;
  $("personaBox").querySelectorAll("[data-persona]").forEach((b) => (b.onclick = () => pickPersona(b.dataset.persona, b)));
  $("personaBack")?.addEventListener("click", () => location.reload());
}
async function pickPersona(id, btn) {
  if (UI?.own_space) return previewAs(id);  // владелец: только временный просмотр, в его настройки не пишем
  await busy(btn, T("persona.saving"), async () => {
    try { UI = await api("/api/persona", { persona: id }); haptic("notificationOccurred", "success"); }
    catch (e) { $("personaResult").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`; return; }
    if (DEMO) { const u = new URL(location.href); u.searchParams.delete("persona"); UI.simple ? u.searchParams.set("simple", "1") : u.searchParams.delete("simple"); u.searchParams.set("ui", id); u.searchParams.set("lang", LANG); return location.replace(u); }
    location.reload();                                // вид сменился целиком — панель заново, данные те же
  });
}
function capsSheet() {                                // «Возможности панели»: тумблеры по-человечески и смена роли
  if (!UI) return;
  if (UI.preview) return sSheet(hv("settings.caps"), T("caps.title"), `<p>Это временный просмотр — возможности меняются в «Моём пространстве».</p>
    <div class="scn-opts">${sChip(true, 'data-mine="1"', "Вернуться в моё пространство", ic("back"))}</div>`, () => location.reload());
  const ceil = new Set(UI.ceiling), mine = UI.own_space, rows = UI.catalog.caps.map((c, i, all) => {
    const on = UI.caps.includes(c.id), fixed = (UI.fixed || []).includes(c.id), locked = !ceil.has(c.id) || fixed, soon = !c.ready;
    const note = fixed ? "в вашем пространстве всегда" : locked ? T("caps.locked") : soon ? T("caps.soon") : "";
    const head = c.dev && !all[i - 1]?.dev ? `<p class="s-lbl">${esc(T("caps.dev"))}</p>` : "";
    return `${head}<div class="scn-opts">${sChip(on, `data-cap="${esc(c.id)}"${locked || soon ? " disabled" : on ? "" : ' aria-pressed="false"'}`, c.title, on ? ic("check") : "")}${note ? `<span class="note">${esc(note)}</span>` : ""}</div>`;
  }).join("");
  const html = `<p class="note">${esc(T("caps.sub"))}</p>${rows}
    <p class="s-lbl">${esc(T("caps.role", { role: personaTitle(UI.persona) }))}</p>
    <div class="scn-opts">${sChip(false, 'data-role="1"', mine ? "Посмотреть как другая роль" : T("caps.change"), ic("refresh"))}</div><p class="note">${esc(mine ? "Временно, только в этой вкладке: ваши настройки не меняются, перезагрузка вернёт в ваше пространство." : T("caps.change.sub"))}</p>`;
  sSheet(hv("settings.caps"), T("caps.title"), html, async (b, bg) => {
    if (b.dataset.role) { bg.remove(); return showPersona(true); }
    if (!b.dataset.cap) return;
    const was = UI.simple, on = !UI.caps.includes(b.dataset.cap);
    try { UI = await api("/api/persona", { add: { [b.dataset.cap]: on } }); haptic("selectionChanged"); }
    catch (e) { return toast(e.message, 4000); }
    if (UI.simple !== was) return DEMO ? location.replace(demoUrl()) : location.reload();   // сменился экран целиком
    applyCaps(); bg.remove(); capsSheet();
  });
}
function demoUrl() { const u = new URL(location.href); UI.simple ? u.searchParams.set("simple", "1") : u.searchParams.delete("simple"); u.searchParams.set("ui", UI.persona); return u; }

// «Моё пространство» и «Демо и тесты» (только владельцу): его пульт неприкосновенен. Просмотр другой роли — на вкладку,
// в памяти страницы: на сервер не пишется, перезагрузка возвращает в своё пространство; сверху — яркая полоса.
function paintSpaces() {
  const on = !!UI?.own_space && (!DEMO || params.has("space")) && !SIM.on;   // демо: ?demo&space=1
  $("spaces").hidden = !on; if (!on) return;
  $("spaces").querySelector(".sp-mine").innerHTML = ic("folder") + "Моё пространство";
  $("spaces").querySelector(".sp-demo").innerHTML = ic("spark") + "Демо и тесты";
}
$("spaces").addEventListener("click", (e) => { if (e.target.closest("[data-space=demo]")) demoSheet(); });
function demoSheet() {
  helpSheet("spaces.demo");
  sheet("Демо и тесты", [
    { head: "Посмотреть как — ваши настоящие сессии, без сохранения" },
    ...(UI?.catalog?.personas || []).filter((p) => p.id !== "developer").map((p) => ({ label: p.title, icon: PERSONA_ICON[p.id] || "spark", sub: p.sub, run: () => previewAs(p.id) })),
    { head: "На примерах" },
    { label: "Примерочная", icon: "spark", sub: "сценарии и калькулятор — выдуманные цифры", run: () => scenariosView() },
    { label: "Демо панели", icon: "ext", sub: "вся панель на примерах — в новой вкладке, ничего никуда не уходит", run: () => window.open("/?demo", "_blank", "noopener") },
    { info: true, icon: "lock", label: "Демо-пространства", sub: "отдельные пространства с демо-данными — готовятся" },
  ]);
}
async function previewAs(id) {
  const p = UI?.catalog?.personas.find((x) => x.id === id); if (!p) return;
  const caps = p.caps.filter((c) => UI.ceiling.includes(c)).sort();
  UI = { ...UI, persona: id, caps, simple: p.simple || !caps.some((c) => UI.fixed?.includes(c)), preview: true };   // только в памяти вкладки
  applyCaps();
  document.querySelectorAll(".sheet-bg").forEach((x) => x.remove());
  $("previewBar").innerHTML = `<span>ПРОСМОТР · вид «${esc(p.title)}» · ваши настоящие сессии</span><button type="button" id="previewBack">Вернуться в моё пространство</button>`;
  $("previewBar").hidden = false; document.body.classList.add("previewing");
  const fit = () => document.body.style.setProperty("--pv", $("previewBar").offsetHeight + "px");   // полоса — не поверх шапки
  fit(); addEventListener("resize", fit);
  $("previewBack").onclick = () => location.reload();
  $("spaces").hidden = true;
  if (UI.simple) { start.poll = null; await simpleStart(); }
}
