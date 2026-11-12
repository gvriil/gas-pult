// ---------- фокус (задача 41): одна сессия на любом устройстве по ссылке ----------
// Владелец: меню сессии → «Фокус-ссылка» (или «Новая сессия» → «В фокусе») — ссылка, QR, «Отправить себе в Telegram».
// На устройстве по ссылке — только чат этой сессии и её настройки (модель, усилия, файлы, интеграции); ни списка
// сессий, ни создания, ни общих настроек. «Завершить» закрывает сессию и гасит ссылку. Список и «Отозвать» —
// «Настройки» → «Фокус-ссылки».
let focusNext = false, focusWant = false;
function focusAfterNew(id) { if (focusWant) { focusWant = false; focusLink(id); } }
async function focusLink(id, proj, mode) {           // proj — ссылка на весь проект (меню проекта); mode "demo" — демо-ссылка
  const body = { ...(proj ? { proj } : { w: id }), base: location.origin, ...(mode ? { mode } : {}) };
  let d; try { d = await api("/api/focus/new", body); } catch (e) { return toast("Не вышло: " + e.message, 5000); }
  const demo = d.mode === "demo";
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.focus");
  if (demo) bg.setAttribute("data-help", hv("sheet.focus-demo"));   // демо-ссылка — своя справка
  const till = new Date(d.exp * 1000).toLocaleString("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
  bg.innerHTML = `<div class="sheet" role="dialog"><h3>${demo ? "Демо-ссылка" : "Фокус-ссылка"}${proj && !demo ? " на проект" : ""}: ${esc(d.name)}</h3>
    <p class="note" style="margin:0 16px">${demo ? `Для показа: открывается на нескольких устройствах (до ${d.max || 20}). Гости видят сессии ${proj ? "этого проекта" : "этой сессии"} и могут только выбирать варианты в вопросах Claude — писать, загружать файлы и менять настройки нельзя. Ссылка действует до ${esc(till)}; «Отозвать» отключает все устройства сразу.`
      : proj ? `Откройте на нужном устройстве — там будут все сессии этого проекта, новая сессия в нём и завершённые чаты; другие проекты не видны. Первое открытие привязывает устройство. Ссылка действует до ${esc(till)}.`
      : `Откройте на нужном устройстве — там будет только чат этой сессии с её настройками. Первое открытие привязывает устройство. Ссылка гаснет, когда сессию завершат, и не позже ${esc(till)}.`}</p>
    <img class="focus-qr" id="focusQr" alt="QR-код ссылки"><div class="focus-url" id="focusUrl"></div>
    <button data-fa="tg">${ic("send")}<span>Отправить себе в Telegram<small>бот пришлёт ссылку в ваш чат с ним</small></span></button>
    <button data-fa="copy">${ic("copy")}<span>Скопировать ссылку</span></button>
    <button data-fa="revoke" class="danger">${ic("x")}<span>Отозвать эту ссылку</span></button>
    <button class="cancel" data-close>Готово</button></div>`;
  bg.querySelector("#focusUrl").textContent = d.url;
  document.body.append(bg);
  const qrImg = bg.querySelector("#focusQr");      // QR — POST: адрес с токеном не попадает в журнал прокси
  api("/api/focus/qr", { url: d.url }).then((b) => { if (b instanceof Blob) qrImg.src = URL.createObjectURL(b); else qrImg.remove(); }).catch(() => qrImg.remove());
  bg.addEventListener("click", async (e) => {
    if (e.target === bg || e.target.closest("[data-close]")) return bg.remove();
    const b = e.target.closest("[data-fa]"); if (!b) return;
    if (b.dataset.fa === "copy") return copyText(d.url, "Ссылка скопирована");
    if (b.dataset.fa === "tg") return busy(b, "Отправляю…", async () => { try { await api("/api/focus/send", { url: d.url }); toast("Ссылка — в вашем чате с ботом"); } catch (err) { toast(err.message, 5000); } });
    if (b.dataset.fa === "revoke") { try { await api("/api/focus/revoke", { id: d.id }); bg.remove(); toast(demo ? "Демо-ссылка отозвана — все устройства отключены" : "Ссылка отозвана"); } catch (err) { toast(err.message, 5000); } }
  });
}
async function focusList() {
  let d; try { d = await api("/api/focus/list"); } catch (e) { return toast(e.message, 5000); }
  const when = (t) => new Date(t * 1000).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  helpSheet("settings.focus");
  sheet("Фокус-ссылки", d.links.length ? [
    { info: true, icon: "qr", label: "Действующие ссылки", sub: "нажмите, чтобы отозвать: устройство сразу потеряет доступ" },
    ...d.links.map((x) => ({ label: (x.mode === "demo" ? "Демо · " : "") + (x.proj ? "Проект «" + x.name + "»" : x.name) + (x.space ? " · " + x.space : ""), icon: x.mode === "demo" ? "eye" : x.proj ? "folder" : "qr",
      sub: (x.mode === "demo" ? (x.devices ? `${x.devices} ${plural(x.devices, ["устройство", "устройства", "устройств"])} · последнее ${when(x.opened)}` : "ещё не открыта")
        : x.opened ? `открыта ${when(x.opened)} · ${x.device || "устройство"}` : "ещё не открыта") + ` · до ${when(x.exp)}`,
      run: () => confirmDanger(x.mode === "demo" ? `Отозвать демо-ссылку на «${x.name}»? Все устройства сразу потеряют доступ, сессии продолжат работать.`
        : `Отозвать фокус-ссылку на «${x.name}»? Устройство сразу потеряет доступ, сессия продолжит работать.`,
        async () => { try { await api("/api/focus/revoke", { id: x.id }); toast("Ссылка отозвана"); focusList(); } catch (e) { toast(e.message, 5000); } }) }))]
    : [{ info: true, icon: "qr", label: "Фокус-ссылок нет", sub: "выпустить — меню сессии → «Фокус-ссылка»" }]);
}
// ---------- репозитории GitHub в сессии (задача 43, repos.py) ----------
// Клон (или pull, если папка уже есть) на сервере и /add-dir в живую сессию; при перезапуске — --add-dir.
// «Отключить» убирает только из сессии: папка с репозиторием остаётся.
const canRepos = (s) => !!s && meta?.role !== "viewer" && (meta?.role === "owner" || !!s.space);
function reposLine(s) {
  if (!s.repos?.length) return "";
  const off = canRepos(s);
  return `<div class="repos">${ic("folder")}${s.repos.map((r) => `<span class="rp" title="${esc(r.path)}">${esc(r.name)}${off ? `<button type="button" data-roff-s="${esc(s.id)}" data-roff="${esc(r.path)}" aria-label="Отключить ${esc(r.name)}">Отключить</button>` : ""}</span>`).join("")}</div>`;
}
async function repoOff(id, path, btn) {
  const go = async () => {
    try { await api("/api/repos/remove", { w: id, path }); toast("Отключено. Папка осталась на сервере; Claude перестанет её видеть после перезапуска сессии", 5000); await refresh(); }
    catch (e) { toast(e.message, 5000); }
  };
  return btn ? busy(btn, "…", go) : go();
}
async function repoSheet(id) {
  const s = sessions.find((x) => x.id === id); if (!s) return;
  const bg = sSheet(hv("sheet.repos"), "Репозитории сессии", `<div data-rp-added></div>
    <div class="field"><label for="rpQ">Добавить репозиторий</label><input id="rpQ" type="search" autocomplete="off" spellcheck="false" placeholder="Поиск или ссылка: github.com/владелец/имя"></div>
    <div data-rp-note><p class="note">${ic("wait", "s16")} Загружаю список репозиториев…</p></div><div class="rp-list" data-rp-list></div>`, (b) => {
    if (b.dataset.rpAdd) return repoAdd(id, b.dataset.rpAdd, b, bg);
    if (b.dataset.rpOff) return repoOff(id, b.dataset.rpOff, b).then(() => paintAdded());
    if (b.dataset.rpUrl) return openUrl(b.dataset.rpUrl);
  });
  let list = [];
  const paintAdded = () => {
    const a = sessions.find((x) => x.id === id)?.repos || [];
    bg.querySelector("[data-rp-added]").innerHTML = a.length ? `<p class="note">Подключены к этой сессии — Claude видит их папки:</p>` + a.map((r) => `<div class="ss-row"><b>${esc(r.name)}</b><small>${esc(r.path)}</small>
      <div class="scn-opts">${sChip(false, `data-rp-off="${esc(r.path)}"`, "Отключить", ic("x"))}</div></div>`).join("") + `<p class="note">«Отключить» убирает репозиторий только из сессии, папка остаётся.</p>` : "";
  };
  const paintList = () => {
    const q = bg.querySelector("#rpQ").value.trim(), ql = q.toLowerCase(), have = new Set((sessions.find((x) => x.id === id)?.repos || []).map((r) => r.name.toLowerCase()));
    const rows = list.filter((r) => !ql || r.full.toLowerCase().includes(ql) || (r.about || "").toLowerCase().includes(ql)).slice(0, 60);
    const link = /github\.com[/:][^/\s]+\/[^/\s]+|^[\w.-]+\/[\w.-]+$/.test(q) && !rows.some((r) => r.full.toLowerCase() === ql);
    bg.querySelector("[data-rp-list]").innerHTML = (link ? `<button class="rp-pick" type="button" data-rp-add="${esc(q)}"><b>${ic("plus", "s16")} Добавить по ссылке</b><small>${esc(q)}</small></button>` : "")
      + rows.map((r) => `<button class="rp-pick" type="button" data-rp-add="${esc(r.full)}"${have.has(r.full.split("/")[1].toLowerCase()) ? " disabled" : ""}><b>${esc(r.full)}${r.private ? " · закрытый" : ""}</b>${r.about ? `<small>${esc(r.about)}</small>` : ""}</button>`).join("")
      + (!rows.length && !link && list.length ? `<p class="note">Ничего не нашлось — вставьте ссылку на репозиторий.</p>` : "");
  };
  paintAdded();
  bg.querySelector("#rpQ").addEventListener("input", paintList);
  let d; try { d = await api("/api/repos?w=" + encodeURIComponent(id)); } catch (e) { d = { repos: [], error: e.message }; }
  if (!bg.isConnected) return;
  list = d.repos || [];
  const h = d.hint;
  bg.querySelector("[data-rp-note]").innerHTML = h ? `<div class="result bad">${ic("key")}<span><b>${esc(h.text)}</b></span></div><ol class="s-notes">${h.steps.map((x) => `<li>${esc(x)}</li>`).join("")}</ol>
      <div class="scn-opts">${sChip(false, `data-rp-url="${esc(h.url)}"`, "Создать токен на GitHub", ic("ext"))}</div>`
    : d.error ? `<p class="note">${esc(d.error)}</p>` : `<p class="note">${list.length ? "Выберите из списка или вставьте ссылку. Папка уже есть — вместо клона будет pull." : "Список пуст — вставьте ссылку на репозиторий."}</p>`;
  paintList();
}
async function repoAdd(id, repo, btn, bg) {
  await busy(btn, "Клонирую…", async () => {
    try {
      const d = await api("/api/repos/add", { w: id, repo });
      bg.remove();
      toast(`${d.full}: ${d.action === "pull" ? "папка уже была — обновлена (pull)" : "склонирован"}. ${d.sent ? "Claude получил /add-dir — папка уже в сессии" : "Подключится при перезапуске сессии"}`, 6000);
      await refresh();
      if (d.dialog && current === id) { toast("Claude спрашивает подтверждение — ответьте на экране", 5000); setTab("screen"); }
    } catch (e) { toast(e.message, 6000); }
  });
}
async function focusMcp() {                         // интеграции сессии: что подключено у Claude Code на сервере
  let d; try { d = await api("/api/mcp"); } catch (e) { return toast(e.message, 5000); }
  helpSheet("focus.mcp");
  sheet("Интеграции этой сессии", [
    { info: true, icon: "puzzle", label: "Подключено у Claude Code", sub: "работают в этой сессии; добавить или убрать — в полном пульте («Интеграции»)" },
    ...d.servers.map((x) => ({ info: true, label: x.name, dot: x.ok ? "s-idle" : "s-approval", sub: x.ok ? "работает" : x.state || "не подключено" })),
    ...(d.servers.length ? [] : [{ info: true, icon: "puzzle", label: "Интеграций нет" }])]);
}
// Фокус на проект (меню проекта → «Фокус-ссылка на проект»): все его сессии, «Новая сессия в проекте», завершённые
// чаты — и ничего вне проекта (сервер отвечает 403). Под шапкой — имя проекта (шторка сессий) и срок входа.
const FOCUS_PROJ = () => FOCUS && !!meta?.focus?.proj;
const FOCUS_DEMO = () => FOCUS && meta?.focus?.mode === "demo";   // демо-ссылка: только просмотр и выбор вариантов
function focusExp() {                               // «вход действует до ДД.ММ (через N дн.)»; за 2 дня — заметно
  const el = $("focusExp"), f = meta?.focus;
  if (!FOCUS || !f?.exp) { if (!el.hidden) el.hidden = true; return; }
  const left = f.exp * 1000 - Date.now(), days = Math.max(0, Math.ceil(left / 864e5)), d = new Date(f.exp * 1000);
  const date = String(d.getDate()).padStart(2, "0") + "." + String(d.getMonth() + 1).padStart(2, "0");
  const soon = left <= 2 * 864e5, n = days + " " + plural(days, ["день", "дня", "дней"]);
  const text = FOCUS_DEMO() ? (days < 1 ? "Демо до сегодня" : `Демо до ${date}`)
    : !soon ? `Вход действует до ${date} (через ${days} дн.)` : days < 1 ? `Вход истекает сегодня — попросите новую ссылку` : `Перезайти через ${n} — вход до ${date}`;
  const h = (FOCUS_PROJ() ? `<button type="button" data-fproj aria-label="Сессии проекта «${esc(f.name)}»">${ic("folder", "s16")}<b>${esc(f.name)}</b>${ic("chev", "s16")}</button>` : "")
    + `<span title="Ссылка действует до ${esc(new Date(f.exp * 1000).toLocaleString("ru-RU"))}">${ic(soon ? "warn" : "lock", "s16")}${esc(text)}</span>`;
  const cls = "focus-exp" + (soon ? " soon" : "");
  if (el.className !== cls) el.className = cls;
  if (el.dataset.h !== h) { el.dataset.h = h; el.innerHTML = h; }
  if (el.hidden) el.hidden = false;
}
$("focusExp").addEventListener("click", (e) => { if (e.target.closest("[data-fproj]")) focusProjSheet(); });
const byLast = (a, b) => lastMsg(b) - lastMsg(a);
function focusProjSheet() {
  const f = meta.focus, list = [...sessions].sort(byLast);
  helpSheet("sheet.focus-proj");
  sheet(`Проект «${f.name}»`, [
    ...list.map((x) => ({ label: x.title && x.title !== x.name ? `${x.name} · ${x.title}` : x.name, dot: (ST[x.status] || ST.idle).cls, on: x.id === current,
      sub: (ST[x.status] || ST.idle).label + (isNew(x) ? " · новый ответ" : "") + (lastMsg(x) ? " · " + agoText(lastMsg(x)) : ""), run: () => openSession(x.id) })),
    ...(list.length ? [] : [{ info: true, icon: "chat", label: "Открытых сессий нет", sub: FOCUS_DEMO() ? "демо — только просмотр" : "начните новую или продолжите завершённую" }]),
    ...(FOCUS_DEMO() ? [] : [{ label: "Новая сессия в проекте", icon: "plus", sub: "ещё одно окно Claude в папке проекта", run: () => focusProjNew() },
      { label: "Завершённые чаты", icon: "file", sub: "продолжить разговор, который закрыли", run: () => focusProjDone() }])]);
}
async function focusProjNew(btn) {
  const go = async () => { try { const d = await api("/api/project/session", { id: meta.focus.proj }); await refresh(); await openSession(d.id); } catch (e) { toast("Не вышло: " + e.message, 4500); } };
  return btn ? busy(btn, "Запускаю…", go) : go();
}
async function focusProjDone() {
  let d; try { d = await api("/api/project/sessions?id=" + encodeURIComponent(meta.focus.proj)); } catch (e) { return toast(e.message, 4500); }
  helpSheet("sheet.focus-proj");
  sheet("Завершённые чаты", d.chats.length ? d.chats.map((c) => ({ label: c.title || "Без названия", icon: "chat", sub: `${c.msgs} ${plural(c.msgs, ["сообщение", "сообщения", "сообщений"])}${c.last || c.mtime ? " · " + agoText(c.last || c.mtime) : ""} · продолжить`,
    run: async () => { try { const r = await api("/api/project/resume", { id: meta.focus.proj, sid: c.sid }); await refresh(); openSession(r.id); } catch (e) { toast("Не вышло: " + e.message, 4500); } } }))
    : [{ info: true, icon: "chat", label: "Завершённых чатов нет" }]);
}
function focusGone() {                              // сессию завершили: ссылка на сессию гаснет, на проект — живёт
  if (!FOCUS_PROJ()) return focusEnd("Сессия завершена.");
  current = null; return refresh().then(() => { const n = [...sessions].sort(byLast)[0]; return n ? openSession(n.id) : focusEmpty(); });
}
function focusEmpty() {                             // в проекте нет открытых сессий: новая или завершённая
  current = null; document.body.classList.add("focus-empty"); show("session");
  setText($("title"), meta.focus.name); setSub("<span>проект · открытых сессий нет</span>");
  const h = FOCUS_DEMO() ? `<div class="panel focus-proj-empty" data-key="fempty">${ic("folder")}<h2 class="serif">Проект «${esc(meta.focus.name)}»</h2><p class="note">Открытых сессий сейчас нет — страница обновится сама.</p></div>`
    : `<div class="panel focus-proj-empty" data-key="fempty">${ic("folder")}<h2 class="serif">Проект «${esc(meta.focus.name)}»</h2><p class="note">Открытых сессий нет — начните новую или продолжите завершённую.</p>
    <button class="btn" type="button" data-fnew>${ic("plus", "s16")}Новая сессия в проекте</button><button class="btn ghost" type="button" data-fdone>${ic("file", "s16")}Завершённые чаты</button></div>`;
  if (!$("content").querySelector("[data-key=fempty]")) $("content").innerHTML = h;
}
$("content").addEventListener("click", (e) => { const b = e.target.closest("[data-fnew], [data-fdone]"); if (!b || !FOCUS_PROJ() || FOCUS_DEMO()) return; b.dataset.fnew != null ? focusProjNew(b) : focusProjDone(); });
function focusEnd(text) {
  if ($("focusEnd")) return;
  start.poll = null;
  document.querySelectorAll(".sheet-bg").forEach((b) => b.remove());
  const done = !text || /^Сессия завершена/.test(text);
  const d = document.createElement("div"); d.id = "focusEnd"; d.className = "focus-end"; d.setAttribute("role", "alert");
  d.innerHTML = `<div>${ic(done ? "power" : "lock")}<h2 class="serif">${done ? "Сессия завершена" : "Ссылка не действует"}</h2>${done ? "" : `<p>${esc(text)}</p>`}<p class="note">Эту страницу можно закрыть.</p></div>`;
  document.body.append(d);
}
async function focusStart() {
  document.body.classList.add("focus");             // экран сессии — openSession, когда известна сессия
  try {
    if (FOCUS_TOKEN) await api("/api/focus/open", { token: FOCUS_TOKEN });   // первое открытие — привязка устройства
    meta = await api("/api/meta"); BUILD = meta.build;
  } catch (e) { return focusEnd(e.message); }
  document.body.dataset.role = FOCUS_DEMO() ? "demo" : "owner";   // демо: сервер — «наблюдатель», кнопки вопроса — есть
  document.body.classList.toggle("focus-demo", FOCUS_DEMO());
  if (FOCUS_DEMO()) $("demoNote").innerHTML = ic("eye", "s16") + "<span>Демо — только просмотр и выбор вариантов</span>";
  $("keys").innerHTML = meta.keys.map((k) => `<button data-key="${esc(k.key)}"${k.key === "C-c" ? ' class="ctrlc" aria-label="Прервать команду: Ctrl+C"' : ""}>${esc(k.label)}</button>`).join("");
  if (!meta.voices.length) document.querySelectorAll("#menu [data-act^=say]").forEach((b) => (b.hidden = true));
  document.body.classList.toggle("focus-proj", FOCUS_PROJ()); focusExp();
  await refresh();
  if (FOCUS_PROJ()) { const n = [...sessions].sort(byLast)[0]; if (n) await openSession(n.id); else focusEmpty(); }
  else if (!sessions.length) return focusEnd("Сессия завершена.");
  else await openSession(sessions[0].id);
  start.done = true; afterPaint(mdLoad);
  start.poll ||= refresh;                            // опрос — общий секундный тик (tick, pollDue)
  keepAwake(); restoreDraft();
}
$("backBtn").onclick = back;
$("target").onclick = () => { haptic("selectionChanged"); openSwitcher(); };   // «куда уйдёт» у поля ввода — сменить сессию
