// ---------- «Проекты» (задача 49, docs/PROJECTS.md): главная — проекты, внутри — их чаты ----------
// Проект — папка со своими инструкциями (CLAUDE.md) и файлами; внутри — много чатов: активные (окна) и завершённые
// (журналы Claude Code без окна, «Продолжить» — --resume). Плоский список окон — вкладка «Сессии», как раньше.
let homeMode = store("homeMode") || (DEMO && !params.has("proj") ? "sessions" : "projects");
let projData = null, proj = null, projInfo = null, projTab = "active", projQ = "", projListQ = "", projFilter = "all";
let projDone = null, projDoneQ = null;                // завершённые чаты открытого проекта и поиск, по которому загружены
const projOn = () => !!meta?.projects_ui && !meta?.space && !FOCUS;
const projMode = () => projOn() && homeMode === "projects";
const projOf = (id) => projData?.projects?.find((p) => p.id === id);
function setMode(m) { homeMode = m; store("homeMode", m); if (m !== "projects") proj = null; }
const chatWord = (n) => { const f = agoPlural(n); return n + " " + (f === "one" ? "чат" : f === "few" ? "чата" : "чатов"); };
const msgWord = (n) => { const f = agoPlural(n); return n + " " + (f === "one" ? "сообщение" : f === "few" ? "сообщения" : "сообщений"); };
const agoAt = (ts) => ts ? `<span class="ago" data-ago="${esc(ts)}">${esc(agoLabel({ ago: ts }, nowSec()))}</span>` : "";
function projCard(p) {
  const wait = p.waiting ? `<span class="chip s-approval"><span class="sdot s-approval"></span>${p.waiting} ждут ответа</span>` : "";
  const busy = p.busy ? `<span class="chip s-running">${p.busy} работают</span>` : "";
  return `<div class="card projc${p.waiting ? " s-approval" : ""}" data-proj="${esc(p.id)}" role="button" tabindex="0" aria-label="${esc(p.name)}">
    <div class="row">${ic(p.origin?.startsWith("module:") ? "puzzle" : "folder")}<div class="ctext"><div class="name">${pinMark(p)}${esc(p.name)}</div>
      <div class="meta">${p.last_window ? esc(p.last_window) + (p.last_title ? " · «" + esc(p.last_title) + "»" : "") : p.last_title ? "«" + esc(p.last_title) + "»" : "нет чатов"}</div></div>${agoAt(p.last)}
      <button class="kebab" data-proj-more="${esc(p.id)}" aria-label="Действия с проектом">${ic("more")}</button></div>
    <div class="cfoot">${wait}${busy}<span class="chip">${esc(chatWord(p.chats))}</span>${p.windows ? `<span class="chip">окон: ${p.windows}</span>` : ""}
      <span class="chip space" title="папка проекта">${ic("folder")}${esc(p.folder)}${p.paths?.length ? " +" + p.paths.length : ""}</span></div></div>`;
}
function projMatch(p, q) {
  if (!q) return true;
  const ss = sessions.filter((s) => s.project === p.id);
  return [p.name, p.folder, p.last_title, p.last_window, ...ss.map((s) => s.title), ...ss.map((s) => s.name)].some((x) => String(x || "").toLowerCase().includes(q));
}
function renderProjects() {                           // список проектов или открытый проект — в #projectsView
  const box = $("projectsView");
  if (proj && !projOf(proj) && projData) proj = null;  // проект пропал (папку удалили) — к списку
  if (proj) return renderProject();
  if (box.dataset.mode !== "list") {                   // поиск и фильтр — один раз: перерисовка раз в 3 с не сбивает ввод
    box.dataset.mode = "list";
    box.innerHTML = `<div class="field psearch"><input id="projQ" type="search" placeholder="Поиск по проектам и чатам" autocomplete="off" value="${esc(projListQ)}"></div>
      <div class="summary" id="projChips"></div><div id="projList"></div>`;
    $("projQ").oninput = (e) => { projListQ = e.target.value; renderProjects(); };
  }
  const all = projData?.projects || [], q = projListQ.trim().toLowerCase();
  const waiting = all.filter((p) => p.waiting).length;
  setHTML($("projChips"), `<button class="chip${projFilter === "all" ? " accent" : ""}" data-pf="all">Все <b>${all.length}</b></button>`
    + `<button class="chip${projFilter === "wait" ? " accent" : " s-approval"}" data-pf="wait">Ждут ответа <b>${waiting}</b></button>${costSummary()}`);
  const list = all.filter((p) => (projFilter !== "wait" || p.waiting) && projMatch(p, q));
  const mine = (x) => meta?.role === "owner" && x.space;
  morph($("projList"), notifyCard() + (list.length ? pinGroups(list, projCard)
    : `<div class="empty">${all.length ? "Ничего не нашлось" : "Проектов пока нет — нажмите «Новая сессия»: папка станет проектом."}</div>`)
    + spacesGroup([...sessions].sort(byChange).filter(mine)));
}
async function openProject(id, t) {
  proj = id; projTab = t || "active"; projQ = ""; projDone = null; projDoneQ = null; projInfo = null;
  $("projectsView").dataset.mode = "";
  setHome("sessions"); scrollToY(0);
  try { projInfo = await api("/api/project?id=" + encodeURIComponent(id)); if (proj === id) renderProject(); } catch (e) { toast(e.message, 4000); }
  if (projTab === "done") loadDone();
}
function closeProject() { proj = null; $("projectsView").dataset.mode = ""; setHome("sessions"); scrollToY(0); }
function renderProject() {
  const box = $("projectsView"), p = projOf(proj); if (!p) return;
  if (box.dataset.mode !== "proj:" + proj) {
    box.dataset.mode = "proj:" + proj;
    box.innerHTML = `<div class="phead"><button class="chip" data-pback>${ic("back")}Все проекты</button></div>
      <h2 class="serif ptitle" id="projName"></h2><div class="note pinfo" id="projInfo"></div>
      <div class="field psearch"><input id="projSearch" type="search" placeholder="Поиск в чатах проекта" autocomplete="off"></div>
      <div class="seg" id="projSeg"><button data-pt="active"></button><button data-pt="done"></button></div>
      <div id="projChats"></div>`;
    $("projSearch").oninput = (e) => { projQ = e.target.value; if (projTab === "done") { clearTimeout(renderProject.t); renderProject.t = setTimeout(loadDone, 400); } renderProject(); };
  }
  $("projName").textContent = p.name;
  if (view === "home" && !split()) $("title").textContent = p.name;
  const inf = projInfo && projInfo.id === proj ? projInfo : null;
  const first = inf?.instructions?.split("\n").map((x) => x.replace(/^[#>*\-\s]+/, "").trim()).find(Boolean) || "";
  setHTML($("projInfo"), inf ? `<span>${first ? "Инструкции: «" + esc(first.slice(0, 80)) + "»" : "Инструкций нет (CLAUDE.md)"}</span> · <span>Файлы: ${inf.files.length}</span> · <span class="ppath">${esc(p.path)}</span>` : "");
  const act = sessions.filter((s) => s.project === proj).sort(byChange), q = projQ.trim().toLowerCase();
  const doneN = projDone && projDoneQ === "" ? projDone.chats.length + (projDone.more ? "+" : "") : p.chats - act.filter((s) => s.sid).length;
  setHTML($("projSeg"), `<button data-pt="active" class="${projTab === "active" ? "on" : ""}">Активные ${act.length}</button><button data-pt="done" class="${projTab === "done" ? "on" : ""}">Завершённые ${Math.max(0, +doneN || 0) || doneN || 0}</button>`);
  if (projTab === "active") {
    const shown = act.filter((s) => !q || [s.title, s.name, s.preview].some((x) => String(x || "").toLowerCase().includes(q)));
    morph($("projChats"), shown.length ? pinGroups(shown, (s) => card(s, true))
      : `<div class="empty">${act.length ? "Ничего не нашлось" : "Активных чатов нет — «Новая сессия в проекте» внизу или «Завершённые»."}</div>`);
    return;
  }
  const d = projDone;
  if (!d) { morph($("projChats"), skelCards(2)); return; }
  const note = `<div class="note">Чаты старше ${d.keep_days} дней Claude Code удаляет сам — в списке их не будет.${d.cut ? " Поиск по тексту — не по всем чатам: уточните запрос." : ""}</div>`;
  morph($("projChats"), (d.chats.length ? pinGroups(d.chats, (c) => `<div class="card dchat" data-chat="${esc(c.sid)}" role="button" tabindex="0" aria-label="${esc(c.title)}">
      <div class="row">${ic("chat")}<div class="ctext"><div class="name">${pinMark(c)}${esc(c.title)}</div><div class="meta">${esc(msgWord(c.msgs))}${c.mine ? "" : " · другая учётка"}</div></div>${agoAt(c.last || c.mtime)}
        <button class="kebab" data-chat-more="${esc(c.sid)}" aria-label="Действия с чатом">${ic("more")}</button></div>
      ${c.mine && meta?.role !== "viewer" ? `<button class="btn quiet sm reply" data-resume="${esc(c.sid)}">${ic("play", "s16")}Продолжить</button>` : ""}</div>`)
    : `<div class="empty">${projQ ? "Ничего не нашлось" : "Завершённых чатов нет."}</div>`)
    + (d.more ? '<button class="btn quiet" data-done-more>Показать ещё</button>' : "") + note
    + (meta?.role === "owner" ? `<button class="btn quiet" data-chat-trash>${ic("trash", "s16")}Корзина и скрытые чаты</button>` : ""));
}
async function loadDone(more) {
  const id = proj, q = projQ.trim();
  try {
    const d = await api(`/api/project/sessions?id=${encodeURIComponent(id)}&q=${encodeURIComponent(q)}${more && projDone?.before ? "&before=" + projDone.before : ""}`);
    if (proj !== id || projQ.trim() !== q) return;
    projDone = more && projDone ? { ...d, chats: [...projDone.chats, ...d.chats] } : d; projDoneQ = q;
    renderProject();
  } catch (e) { toast(e.message, 4000); }
}
async function projectNew() {
  const p = projOf(proj); if (!p) return;
  toast("Запускаю новый чат в «" + p.name + "»…", 3000);
  try { const d = await api("/api/project/session", { id: p.id }); await refresh(); openSession(d.id); focusAfterNew(d.id); }
  catch (e) { toast("Не вышло: " + e.message, 4500); }
}
async function projectResume(sid, btn) {
  const p = projOf(proj); if (!p) return;
  document.querySelectorAll(".sheet-bg").forEach((x) => x.remove());
  if (btn) btn.disabled = true;
  toast("Продолжаю чат…", 3000);
  try { const d = await api("/api/project/resume", { id: p.id, sid }); projDone = null; await refresh(); openSession(d.id); if (projTab === "done") loadDone(); }
  catch (e) { toast("Не вышло: " + e.message, 5000); }
  finally { if (btn) btn.disabled = false; }
}
async function chatView(sid) {                         // переписка завершённого чата — без окна, внизу «Продолжить»
  const p = projOf(proj), c = projDone?.chats.find((x) => x.sid === sid); if (!p) return;
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.project-chat");
  bg.innerHTML = `<div class="sheet chatv" role="dialog"><h3></h3><div class="chatv-list chat">${skelMsgs()}</div>
    <div class="row2">${c?.mine && meta?.role !== "viewer" ? `<button class="btn ghost" data-close>Закрыть</button><button class="btn" data-go-resume>Продолжить этот чат</button>` : '<button class="btn ghost" data-close>Закрыть</button>'}</div></div>`;
  bg.querySelector("h3").textContent = c?.title || "Чат";
  document.body.append(bg);
  bg.addEventListener("click", (e) => {
    if (e.target === bg || e.target.closest("[data-close]")) bg.remove();
    if (e.target.closest("[data-go-resume]")) projectResume(sid, e.target.closest("[data-go-resume]"));
  });
  try {
    const d = await api(`/api/project/history?id=${encodeURIComponent(p.id)}&sid=${encodeURIComponent(sid)}`);
    const list = bg.querySelector(".chatv-list");
    list.__items = d.items;                            // для «Копировать» — исходный текст по номеру (data-n)
    list.innerHTML = (d.more ? '<div class="note">Показаны последние сообщения.</div>' : "") + (d.items.length ? d.items.map((m, n) => m.role === "user"
      ? `<div class="msg me" data-n="${n}"><div class="bubble">${esc(m.text)}</div><div class="macts">${mCopyBtn()}</div></div>`
      : m.human ? `<div class="msg ai"><div class="s-err">${ic("warn")}<span>${esc(m.human[LANG] || m.human.ru)}</span></div></div>`
      : `<div class="msg ai" data-n="${n}"><div class="bubble md">${md(m.text)}</div><div class="macts">${mCopyBtn()}</div></div>`).join("") : '<div class="empty">Сообщений нет.</div>');
    list.querySelectorAll(".bubble").forEach(linkify);   // ссылки — и в завершённом чате
    codeCopy(list);
    list.scrollTop = list.scrollHeight;
  } catch (e) { bg.querySelector(".chatv-list").innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}
function chatSheet(sid) {
  const p = projOf(proj), c = projDone?.chats.find((x) => x.sid === sid); if (!p || !c) return;
  const set = async (b, ok) => { try { await api("/api/project/chat", { id: p.id, sid, ...b }); toast(ok); loadDone(); } catch (e) { toast(e.message, 4000); } };
  helpSheet("sheet.project-chat-menu");
  sheet(c.title, [
    { label: "Открыть переписку", icon: "chat", run: () => chatView(sid) },
    ...(c.mine && meta?.role !== "viewer" ? [{ label: "Продолжить", sub: "новое окно с этим разговором", icon: "play", run: () => projectResume(sid) }] : []),
    ...(meta?.role !== "viewer" ? [pinItem(c, { id: p.id, sid }, c.title),
      { label: "Переименовать", icon: "edit", run: () => chatRename(c, (t) => set({ title: t }, "Теперь: " + t)) },
      { label: "Скрыть", sub: "из списка; журнал Claude Code остаётся", icon: "x", run: () => set({ hidden: true }, "Чат скрыт") }] : []),
    ...(meta?.role === "owner" ? [{ label: "Удалить", icon: "trash", danger: true, sub: "переписка — в корзину пульта; можно вернуть", run: () => chatDelete({ id: p.id, sid }, c.title) }] : []),
  ]);
}
// «Удалить» сессию (окно) или завершённый чат — плашкой «Отменить» вместо окна «Вы уверены?» (план UX, пункт 9):
// строка уходит сразу, на сервер — через 5 с, если не отменили. Окно закрывается, журнал Claude Code — в корзину
// пульта (вернуть — «Настройки» → «Корзина чатов»); ошибка — текстом сервера, не молча.
function chatDelete(body, name) {
  const label = name || "чат", done = () => proj && projTab === "done" && loadDone();
  if (body.w) { NAV.gone.add(body.w); sessions = sessions.filter((x) => x.id !== body.w); }
  else if (projDone?.chats) { projDone = { ...projDone, chats: projDone.chats.filter((c) => c.sid !== body.sid) }; renderProject(); }
  if (body.w && body.w === current && view === "session") back(); else { renderNav(); refresh(); }
  undoBar(`Удалено: «${label}»`, () => { if (body.w) NAV.gone.delete(body.w); projDone = null; refresh(); done(); toast("Вернул «" + label + "»"); }, async () => {
    try {
      const d = await api("/api/chat/delete", body);
      if (d.draft) toast("В поле ввода был неотправленный текст — он в корзине вместе с перепиской", 4500);
    } catch (e) { toast("Не удалено: " + e.message, 5000); }
    finally { if (body.w) NAV.gone.delete(body.w); projDone = null; await refresh(); done(); }
  });
}
async function chatRestore(id) {
  try { const r = await api("/api/chat/restore", { id }); toast("Вернул: «" + (r.title || "чат") + "» — в «Завершённых»", 4000); projDone = null; await refresh(); if (proj && projTab === "done") loadDone(); }
  catch (e) { toast("Не вернул: " + e.message, 5000); }
}
async function chatTrash() {                         // «Корзина чатов»: удалённые (вернуть) и скрытые (показать снова)
  let d; try { d = await api("/api/chat/trash"); } catch (e) { return toast(e.message, 4000); }
  const when = (ts) => ts ? new Date(ts * 1000).toLocaleString(LANG === "en" ? "en-GB" : "ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
  helpSheet("sheet.chat-trash");
  sheet("Корзина чатов", [
    { info: true, icon: "help", label: "Удалённые чаты лежат в корзине пульта", sub: `через ${d.keep_days || 30} дней удаляются окончательно; «Вернуть» — переписка снова в проекте` },
    ...(d.trash.length ? [{ head: "Удалённые" }, ...d.trash.map((x) => ({ label: x.title || "Без названия", icon: x.warn ? "warn" : "chat", danger: !!x.warn,
      sub: [x.warn ? (x.days_left > 0 ? `удалится через ${x.days_left} дн.` : "удалится сегодня") : "", x.project_name, "удалён " + when(x.at), x.warn ? "нажмите — «Вернуть»" : "нажмите — вернуть"].filter(Boolean).join(" · "), run: () => chatRestore(x.id) }))] : [{ info: true, icon: "trash", label: "Удалённых нет" }]),
    ...(d.hidden.length ? [{ head: "Скрытые" }, ...d.hidden.map((x) => ({ label: x.title || "Без названия", icon: "chat", sub: [x.project_name, "нажмите — показать в списке"].filter(Boolean).join(" · "),
      run: () => api("/api/project/chat", { id: x.project, sid: x.sid, hidden: false }).then(() => { toast("Чат снова в списке"); projDone = null; if (proj && projTab === "done") loadDone(); }, (e) => toast(e.message, 4000)) }))] : []),
  ]);
}
function chatRename(c, done) {                        // своё поле: prompt() в Telegram на iPhone ненадёжен
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.rename");
  bg.innerHTML = `<div class="sheet" role="dialog"><h3>Переименовать чат</h3>
    <div class="field" style="margin:4px 16px 0"><input id="chatName" maxlength="60" autocomplete="off" value="${esc(c.title)}"></div>
    <p class="note" style="margin:6px 16px 0">До 60 знаков. Журнал Claude Code не меняется — название хранит пульт.</p>
    <div class="row2"><button class="btn ghost" data-close>Отмена</button><button class="btn" id="chatOk">Сохранить</button></div></div>`;
  document.body.append(bg);
  const inp = $("chatName"); inp.focus(); inp.select();
  const save = () => { const t = inp.value.trim().replace(/\s+/g, " "); if (!t) return; bg.remove(); done(t); };
  $("chatOk").onclick = save;
  inp.onkeydown = (e) => { if (e.key === "Enter") save(); if (e.key === "Escape") bg.remove(); };
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) bg.remove(); });
}
$("projectsView").addEventListener("click", (e) => {
  if (e.target.closest("[data-pback]")) return closeProject();
  const pf = e.target.closest("[data-pf]"); if (pf) { projFilter = pf.dataset.pf; return renderProjects(); }
  const pm = e.target.closest("[data-proj-more]"); if (pm) return projSheet(pm.dataset.projMore);
  const pc = e.target.closest(".card[data-proj]"); if (pc) return openProject(pc.dataset.proj);
  const pt = e.target.closest("[data-pt]"); if (pt) { projTab = pt.dataset.pt; if (projTab === "done" && (!projDone || projDoneQ !== projQ.trim())) loadDone(); return renderProject(); }
  if (e.target.closest("[data-done-more]")) return loadDone(true);
  if (e.target.closest("[data-chat-trash]")) return chatTrash();
  const rs = e.target.closest("[data-resume]"); if (rs) return projectResume(rs.dataset.resume, rs);
  const cm = e.target.closest("[data-chat-more]"); if (cm) return chatSheet(cm.dataset.chatMore);
  const ch = e.target.closest(".card[data-chat]"); if (ch) return chatView(ch.dataset.chat);
  sessionsClick(e);                                    // карточки окон и группа «Пространства» — как на «Сессиях»
});
function newSession(profile) {
  const f = focusNext; focusNext = false; focusWant = false;   // «В фокусе» — только для этой новой сессии
  if (meta?.space) return sheet(T("ss.menu"), [    // тестировщик: новая сессия (своя папка в пространстве) или закрытые
    { label: T("ss.new.title"), sub: T("ss.new.sub"), icon: "plus", run: () => ssNew() },
    { label: T("ss.list.title"), sub: T("ss.list.sub"), icon: "folder", run: () => ssClosed() }]);
  helpSheet("sheet.new-session");
  sheet(f ? "Новая сессия в фокусе — в какой папке?" : "Новая сессия — в какой папке?", [
    ...(meta?.role === "owner" && !f ? [{ label: "В фокусе", sub: "сразу фокус-ссылка: только эта сессия на другом устройстве", icon: "qr", run: () => { focusNext = true; newSession(profile); } }] : []),
    { label: "Новая папка", sub: "пустой проект (git init) и сессия в нём", icon: "plus", run: () => { focusWant = f; newFolder(profile); } },
    ...(profile || f ? [] : [{ label: "Из модуля", sub: "готовый агент под задачу: новая папка с правилами и навыками", icon: "puzzle", run: () => modulesView() }]),
    ...meta.projects.map((label, i) => ({
      label, icon: "file", run: () => { focusWant = f; profile ? startSession(i, profile) : pickProfile((pid) => startSession(i, pid)); },
    }))]);
}
// «Новая папка» — своё поле ввода (prompt() в Telegram на iPhone ненадёжен); имя — как у 📁 в боте.
function newFolder(profile) {
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.new-folder");
  bg.innerHTML = `<div class="sheet" role="dialog"><h3>Новая папка</h3>
    <div class="field" style="margin:4px 16px 0"><input id="nfName" maxlength="41" autocapitalize="off" spellcheck="false" autocomplete="off" placeholder="например, shop-bot"></div>
    <p class="note" id="nfErr" style="margin:6px 16px 0">Латиница в нижнем регистре, цифры, дефис. Папка — в первом корне проектов, сразу с git.</p>
    <button class="btn" id="nfOpen" hidden style="margin:8px 16px 0;width:calc(100% - 32px)"></button>
    <div class="row2"><button class="btn ghost" data-close>Отмена</button><button class="btn" id="nfOk">Создать и открыть</button></div></div>`;
  document.body.append(bg);
  const inp = $("nfName"); inp.focus();
  const bad = (t) => { $("nfErr").textContent = t; $("nfErr").style.color = "var(--status-danger)"; $("nfOpen").hidden = true; };
  const taken = (name, i, wid) => {                 // имя занято — не ошибка: открыть существующую папку
    bad(`Папка «${name}» уже есть — откройте её или введите другое имя.`); const b = $("nfOpen");
    b.hidden = false; b.innerHTML = ic("folder") + `Открыть «${esc(name)}»`; b.onclick = () => { bg.remove(); openFolder(i < 0 ? null : i, wid, b); };
  };
  const go = async (pid) => {
    toast("Создаю папку и запускаю Claude…", 3000);
    try {
      const d = await api("/api/folder", { name: inp.value.trim().toLowerCase(), profile: pid });
      if (d.exists) return taken(d.folder, d.i, d.open);
      bg.remove(); haptic("notificationOccurred", "success"); await refresh(); openSession(d.id); toast("Папка " + d.folder + " создана"); focusAfterNew(d.id);
    } catch (e) { bad(e.message); }
  };
  const save = () => {
    const name = inp.value.trim().toLowerCase();
    if (!/^[a-z0-9][a-z0-9-]{1,40}$/.test(name)) return bad("Имя: латиница в нижнем регистре, цифры, дефис (2–41 знак)");
    if (meta.projects.includes(name)) return taken(name, meta.projects.indexOf(name), sessions.find((x) => x.path?.split("/").pop() === name && x.status !== "stopped")?.id);
    profile ? go(profile) : pickProfile(go);
  };
  $("nfOk").onclick = save;
  inp.onkeydown = (e) => { if (e.key === "Enter") save(); if (e.key === "Escape") bg.remove(); };
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) bg.remove(); });
}
// «Новый проект» (панель чатов → «Проекты» → «+»): название (кириллица можно) → имя папки латиницей, как у «Новой
// папки»; папка — в первом корне проектов, с git; инструкции — в CLAUDE.md; модель по умолчанию — для чатов проекта.
// Окно не запускаем: сразу пустой «Новый чат» в этом проекте, сессия — при первой отправке (newChat).
const NP_LAT = Object.fromEntries([..."абвгдеёжзийклмнопрстуфхцчшщъыьэюя"].map((c, i) => [c, ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
  "u", "f", "kh", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"][i]]));
const npFolder = (name) => {                          // как projects.folder_of на сервере
  const x = [...(name || "").trim().toLowerCase()].map((c) => NP_LAT[c] ?? c).join("").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 41).replace(/-+$/, "");
  return /^[a-z0-9][a-z0-9-]{1,40}$/.test(x) ? x : "";
};
function newProject() {
  closePop(); navOpen(false);
  if (meta?.role === "viewer") return;
  const root = projData?.new_root || "~/projects", models = meta?.models || [];
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.new-project");
  bg.innerHTML = `<div class="sheet" role="dialog" aria-labelledby="npTitle"><h3 id="npTitle">Новый проект</h3><div style="padding:4px 16px 0">
    <div class="field"><label for="npName">Название</label><input id="npName" maxlength="80" autocomplete="off" placeholder="например, Магазин книг"></div>
    <div class="field"><label for="npFolder">Папка <span class="opt">· в ${esc(root)}</span></label><input id="npFolder" maxlength="41" autocapitalize="off" spellcheck="false" autocomplete="off" placeholder="из названия">
      <p class="note" style="margin:4px 2px 0">Латиница в нижнем регистре, цифры, дефис. Сразу с git.</p></div>
    <div class="field"><label for="npInstr">Инструкции <span class="opt">· необязательно, в CLAUDE.md</span></label><textarea id="npInstr" rows="3" placeholder="Как работать в этом проекте: тон, правила, что важно"></textarea></div>
    ${models.length ? `<div class="field"><label>Модель по умолчанию</label><div class="np-models" role="group" aria-label="Модель по умолчанию">${["", ...models].map((m) => `<button type="button" data-npm="${esc(m)}" aria-pressed="${m === "" ? "true" : "false"}">${esc(m || "Как у пульта")}</button>`).join("")}</div></div>` : ""}
    <p class="note" id="npErr" role="alert" style="margin:0 2px;color:var(--status-danger)" hidden></p></div>
    <div class="row2"><button class="btn ghost" data-close>Отмена</button><button class="btn" id="npOk">Создать</button></div></div>`;
  document.body.append(bg);
  const name = $("npName"), folder = $("npFolder"); let own = false, model = "";
  name.focus();
  name.oninput = () => { if (!own) folder.value = npFolder(name.value); };
  folder.oninput = () => { own = !!folder.value.trim(); };
  const bad = (t) => { $("npErr").textContent = t; $("npErr").hidden = false; };
  const save = () => busy($("npOk"), "Создаю…", async () => {
    const n = name.value.trim(), f = folder.value.trim().toLowerCase() || npFolder(n);
    if (!n) { name.focus(); return bad("Назовите проект."); }
    if (!/^[a-z0-9][a-z0-9-]{1,40}$/.test(f)) { folder.focus(); return bad("Имя папки: латиница в нижнем регистре, цифры, дефис (2–41 знак)."); }
    try {
      const d = await api("/api/project/new", { name: n, folder: f, instructions: $("npInstr").value, model });
      bg.remove(); haptic("notificationOccurred", "success");
      projData = await api("/api/projects").catch(() => projData);
      if (!projOf(d.id)) (projData ||= { projects: [] }).projects = [...(projData.projects || []), { id: d.id, name: d.name, folder: d.folder, path: d.path, origin: "new", chats: 0 }];
      NAV.exp.add(d.id); store("lastProj", d.id);
      newChat(d.id); toast(`Проект «${d.name}» создан — напишите первое сообщение`, 3500);
    } catch (e) { bad(e.message); }
  });
  $("npOk").onclick = save;
  bg.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT") { e.preventDefault(); save(); } if (e.key === "Escape") bg.remove(); });
  bg.addEventListener("click", (e) => {
    const m = e.target.closest("[data-npm]");
    if (m) { model = m.dataset.npm; bg.querySelectorAll("[data-npm]").forEach((x) => x.setAttribute("aria-pressed", String(x === m))); return; }
    if (e.target === bg || e.target.closest("[data-close]")) bg.remove();
  });
}
// Модель этого чата: окно перезапускается с --model у того же поставщика (разговор продолжается); другие не трогаем.
async function setModel(s, alias, name) {
  if (!s) return;
  toast("Перезапускаю этот чат с " + name + "…", 6000);
  try { const d = await api("/api/model", { w: s.id, name: alias }); await refresh(); openSession(d.id); toast(`Модель «${name}» — только для этого чата`, 4500); }
  catch (e) { toast("Не вышло: " + e.message, 5000); }
}
// Модель Claude по умолчанию для новых сессий — отдельной явной настройкой владельца (не из чата).
async function defaultModelSheet() {
  let d; try { d = await api("/api/model/default"); } catch (e) { return toast(e.message, 4500); }
  const set = async (m) => { try { await api("/api/model/default", { model: m }); toast(m ? "Новые сессии Claude — с " + m : "Модель по умолчанию снята — решает Claude Code"); } catch (e) { toast(e.message, 4500); } };
  helpSheet("settings.default-model");
  sheet("Модель по умолчанию для новых сессий", [
    { info: true, icon: "help", label: d.model ? "Сейчас: " + d.model : "Сейчас не задана — решает Claude Code", sub: "действует на все новые сессии Claude (общая настройка Claude Code). Модель одного чата — в самом чате: «Модель»" },
    ...d.models.map((m) => ({ label: m, icon: "chip", on: d.model === m, run: () => set(m) })),
    ...(d.model ? [{ label: "Не задавать", icon: "x", sub: "убрать — модель выберет Claude Code", run: () => set("") }] : []),
  ]);
}
// У поставщика кончились деньги (balance.py) — баннер в чате: пополнить, переключить этот чат, «Я пополнил».
function moneyBar(s) {
  const el = $("money"); if (!el) return;
  const p = profileOf(s?.profile || "claude");
  const was = el.hidden;
  setHidden(el, !s?.no_balance);
  if (was !== el.hidden) padDock();                  // баннер в нижней панели — лента не уходит под него
  if (el.hidden) return;
  setHTML(el, `<p style="margin:0 0 8px"><b>У поставщика ${esc(p?.title || "")} закончились деньги</b> — пополните или переключите этот чат на другого.</p>
    <div class="money-act">${meta?.role === "owner" ? `<button class="btn" data-money="switch">${ic("swap")}Переключить этот чат</button>` : ""}
    ${p?.billing_url ? `<button class="btn ghost" data-money="pay">${ic("ext")}Пополнить</button>` : ""}
    ${meta?.role === "owner" ? `<button class="btn ghost" data-money="paid">${ic("check")}Я пополнил</button>` : ""}</div>`);
  el.onclick = async (e) => {
    const b = e.target.closest("[data-money]"); if (!b) return;
    if (b.dataset.money === "switch") return switchProfile(s);
    if (b.dataset.money === "pay") return openUrl(p.billing_url);
    try { await api("/api/balance/clear", { profile: p.id }); toast("Снова предлагаю " + p.title + " — проверьте, что ответ пришёл", 4500); } catch (err) { toast(err.message, 4500); }
  };
}
// Выбор модели — только если есть ключ хоть одного поставщика кроме Claude; иначе сразу Claude (ноль лишних шагов).
// Недоступный для страны человека — в списке с пометкой; нажатие — отказ тем же текстом, что у сервера.
function pickProfile(go, exclude) {
  const ready = (meta.profiles || []).filter((p) => p.id !== exclude && (!p.needs_key || p.key) && !p.not_ready && !p.no_balance);
  if (!exclude && ready.length < 2 && profileOf("claude")?.allowed !== false) return go("claude");
  helpSheet("sheet.pick-model");
  sheet(exclude ? "Перезапустить с поставщиком" : "В какой модели работать?", [
    ...ready.map((p) => p.allowed === false ? { label: p.title, icon: "lock", sub: p.denied || DENY, run: () => toast(p.denied || DENY, 4500) }
      : { label: p.title, icon: "chip", sub: p.needs_key ? [p.main, p.about, gapPick(p)].filter(Boolean).join(" · ") : p.about, run: () => go(p.id) }),
    ...(meta.profiles || []).filter((p) => p.needs_key && (!p.key || p.not_ready) && p.allowed !== false).map((p) => ({ label: p.title, icon: "key", sub: p.key ? "нет адреса шлюза — настроить" : "нет ключа — добавить", run: () => profileForm(p) })),
    ...(meta.profiles || []).filter((p) => p.no_balance && p.key && p.id !== exclude).map((p) => ({ label: p.title, icon: "coin", sub: "у поставщика закончились деньги — пополните; снова предложу через час", run: () => p.billing_url ? openUrl(p.billing_url) : toast("Пополните счёт у поставщика", 4000) })),
  ]);
}
async function startSession(i, profile) {
  toast(profile && profile !== "claude" ? `Запускаю Claude Code с ${profileOf(profile)?.title || profile}…` : "Запускаю Claude…", 3000);
  try {
    const d = await api("/api/new", { i, profile }); await refresh(); openSession(d.id); focusAfterNew(d.id);
    if (d.existing) toast(`В этой папке уже работает «${d.existing}» — открыл её (одно окно на проект)`, 4500);
  } catch (err) { toast("Не вышло: " + err.message, 4500); }
}
function sessionSheet(id) {
  const s = sessions.find((x) => x.id === id); if (!s) return;
  helpSheet("sheet.session");
  sheet(s.name, [
    { label: "Открыть", icon: "chat", run: () => openSession(id) },
    ...(s.space && meta?.role === "owner" ? [{ label: "Подключиться", sub: "читать и писать в сессию тестировщика; он увидит «Владелец подключился»", icon: "flask", run: () => spaceConnect(id) }] : []),
    ...(s.space ? [] : [{ label: "Сделать активной", sub: "ответы в чате бота будут от этой сессии", icon: "place", run: () => api("/api/active", { w: id }).then(() => { toast("Теперь активная: " + s.name); refresh(); }) }]),
    ...(meta?.role !== "viewer" && !FOCUS && !s.space ? [pinItem(s, { w: id }, s.title || s.name)] : []),
    ...(meta?.role !== "viewer" && !FOCUS ? [{ label: "Переименовать", icon: "edit", run: () => renameSession(s) }] : []),
    ...(meta?.role === "owner" && !FOCUS ? [{ label: "Создать фокус-ссылку", icon: "qr", sub: "только эта сессия на другом устройстве — ссылка и QR, без входа в пульт", run: () => focusLink(id) }] : []),
    ...(canRepos(s) ? [{ label: "Подключить репозитории", icon: "folder", sub: s.repos?.length ? "подключено: " + s.repos.map((r) => r.name).join(", ") : "подключить репозиторий GitHub к этой сессии — без перезапуска", run: () => repoSheet(id) }] : []),
    ...(s.schedule && meta?.role !== "viewer" ? [{ label: "Настроить расписание", icon: "cal", sub: s.schedule.text + " · " + schedLabel(s.schedule), run: () => scheduleSheet(s) }] : []),
    ...(meta?.role === "owner" && !s.space ? [{ label: "Завершить сессию", sub: "Claude выйдет штатно, переписка сохранится", icon: "power", danger: true, run: () => confirmClose(id) }] : []),
    ...(meta?.role === "owner" && s.schedule ? [{ label: "Удалить", icon: "x", danger: true, sub: "расписание выключится навсегда, папка — в корзину", run: () => moduleDelete(s) }] : []),
    ...(meta?.role === "owner" && !s.space && !s.schedule && !FOCUS ? [{ label: "Удалить", icon: "trash", danger: true, sub: "окно закроется, переписка — в корзину пульта; можно вернуть", run: () => chatDelete({ w: id }, s.title || s.name) }] : []),
    ...(s.space && meta?.role !== "viewer" ? [
      { label: T("ss.close.item"), sub: T("ss.close.sub"), icon: "power", run: () => ssClose(s) },
      { label: T("ss.del.item"), sub: T("ss.del.sub"), icon: "trash", danger: true, run: () => ssClose(s, (f) => ssDelete(s.space, f)) },
      { label: T("ss.list.title"), sub: T("ss.list.sub"), icon: "folder", run: () => ssClosed(s.space) },
      { label: T("sf.title"), sub: T("sf.sub"), icon: "file", run: () => sfFiles(s.id) }] : []),
  ]);
}
function confirmClose(id) {
  const s = sessions.find((x) => x.id === id);
  if (s?.schedule?.state === "on") {                // агент из модуля с расписанием: что с ним после закрытия
    helpSheet("sheet.schedule");
    return sheet(`Завершить «${s.name}»?`, [
      { info: true, icon: "cal", label: `Расписание этого агента: ${s.schedule.text}`, sub: "сессия закроется, переписка сохранится. Что с расписанием?" },
      { label: "Оставить", icon: "play", sub: schedLabel(s.schedule) + " — агент снова откроется сам", run: () => closeSession(id, "on") },
      { label: "Приостановить", icon: "pause", sub: "не запускать, пока не включу", run: () => closeSession(id, "paused") },
      { label: "Выключить", icon: "x", sub: "сам больше не запускается", run: () => closeSession(id, "off") },
    ]);
  }
  confirmDanger(`Завершить «${s?.name || "сессию"}»? Claude выйдет штатно, переписка сохранится.`, () => closeSession(id));
}
