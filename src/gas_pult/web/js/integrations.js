// ---------- интеграции ----------
let prov = null;
const GLYPH = { gmail: "mail", gcal: "cal", gdrive: "folder", slack: "hash", linear: "tasks", atlassian: "tasks", figma: "pen",
                github: "code", homeassistant: "home", context7: "book", http: "server", stdio: "term" };
const mono = (t, id) => `<span class="mono">${GLYPH[id] ? ic(GLYPH[id]) : esc(clean(t).slice(0, 1).toUpperCase())}</span>`;
async function loadMcp(fresh) {
  await dictReady;                                     // разделы «Для любой модели» / «Через сайт Claude» — из словаря
  const owner = meta?.role === "owner";                // участнику — только его сервисы; модели, ключи и голос — владельцу
  if (view === "home") setSub(owner ? "<span>голос, ключи API и сервисы</span>" : "<span>ваши сервисы</span>");
  $("integrationsView").innerHTML = '<div id="mcpBox" data-tour="integrations"><div class="empty">Проверяю, что уже подключено… (до 30 секунд)</div></div>' + (owner ? '<div id="modelsBox" data-tour="models"></div><div id="fbBox" data-owner></div><div id="voiceBox"></div>' : "");
  if (!owner) {
    try { mcpData = await api("/api/mcp" + (fresh ? "?fresh=1" : "")); renderMcp(); }
    catch (e) { $("mcpBox").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`; }
    return;
  }
  renderModels(); loadFallback();
  Promise.all([api("/api/providers"), api("/api/voice/cards")]).then(([d, c]) => { prov = d; vcards = c; renderVoice(); }).catch((e) => { $("voiceBox").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`; });
  try { mcpData = await api("/api/mcp" + (fresh ? "?fresh=1" : "")); renderMcp(); }
  catch (e) { $("mcpBox").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`; }
}
function renderModels() {
  const list = (meta?.profiles || []).filter((p) => p.needs_key);
  $("modelsBox").innerHTML = `<div class="section">Модели</div>
    <p class="note">Кроме Claude сессия может работать на моделях других поставщиков — по их ключу. Поставщик выбирается при «Новой сессии».</p>
    ${list.map((p) => `<button class="card" data-prof="${p.id}"><div class="row">${mono(p.title, p.id)}<div class="ctext"><div class="name">${esc(p.title)}</div>
      <div class="meta">${esc(p.allowed === false ? p.denied || DENY : p.key ? (p.main || "модели Claude") : p.about)}</div></div><span class="chip ${p.key && !p.not_ready ? "ok" : ""}">${p.key ? (p.not_ready ? "нет адреса шлюза" : "ключ " + esc(p.key.tail)) : "нет ключа"}</span></div></button>`).join("")}`;
}
$("integrationsView").addEventListener("click", (e) => { const b = e.target.closest("[data-prof]"); if (b) profileForm(profileOf(b.dataset.prof)); });

// «Запасные»: поставщик не ответил (ключ, лимит, сбой, нет связи) — сессия сама продолжает разговор у следующего
let fb = null;
async function loadFallback() {
  try { fb = await api("/api/fallback"); renderFallback(); }
  catch (e) { $("fbBox").innerHTML = `<div class="section">Запасные</div><div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`; }
}
function renderFallback() {
  const opt = Object.fromEntries(fb.options.map((o) => [o.id, o])), title = (id) => opt[id]?.title || id;
  const rest = fb.options.filter((o) => !fb.chain.includes(o.id) && !(o.denied ?? /стран|регион/.test(o.why)));
  const voice = (k) => fb.voice[k].map(esc).join(" → ");
  $("fbBox").innerHTML = `<div class="section">Запасные</div>
    <p class="note">Поставщик не ответил (ключ, лимит, сбой, нет связи) — сессия сама продолжит разговор у первого подходящего по списку, и вы получите одну строку в Telegram.${fb.countries?.length ? ` Страны проверки — ${esc(fb.countries.join(", "))} (ваша и сервера): поставщики не для этих стран не выбираются.` : fb.region ? ` Страна сервера — ${esc(fb.region)}: поставщики не для этой страны не выбираются.` : ""}</p>
    <div class="panel">
      ${fb.chain.length ? fb.chain.map((id, i) => `<div class="fb-row"><span class="fb-n">${i + 1}</span>
        <div class="ctext"><div class="name">${esc(title(id))}</div>${opt[id]?.why ? `<div class="meta fb-why">${esc(opt[id].why)} — пропускается</div>` : ""}</div>
        <button class="icon" data-fb-up="${i}" aria-label="Выше" ${i ? "" : "disabled"}>${ic("up")}</button>
        <button class="icon" data-fb-down="${i}" aria-label="Ниже" ${i < fb.chain.length - 1 ? "" : "disabled"}>${ic("down")}</button>
        <button class="icon" data-fb-rm="${i}" aria-label="Убрать">${ic("x")}</button></div>`).join("")
        : '<p class="note" style="margin:0">Список пуст — пульт не переключает сессии сам.</p>'}
      ${rest.length ? `<div class="fb-add"><select id="fbAdd" aria-label="Добавить запасного">${rest.map((o) => `<option value="${esc(o.id)}">${esc(o.title)}${o.why ? " · " + esc(o.why) : ""}</option>`).join("")}</select>
        <button class="btn ghost sm" id="fbAddBtn">${ic("plus")}Добавить</button></div>` : ""}
      ${fb.log.length ? `<div class="section" style="margin:16px 0 4px">Последние переключения</div>
        <ul class="fb-log">${fb.log.slice(-3).reverse().map((x) => `<li><time>${esc(x.t || "")}</time>${esc(x.text || "")}</li>`).join("")}</ul>` : ""}
    </div>
    <div class="panel" style="margin-top:8px">
      <div class="name">Голос — переключается сам</div>
      <div class="hint">Озвучка: ${voice("tts")}<br>Распознавание: ${voice("stt")}</div>
      ${fb.voice_note ? `<div class="result wait">${ic("warn")}<span>${esc(fb.voice_note)}</span></div>` : ""}
    </div>`;
}
async function saveChain(chain, msg) {
  try { fb = await api("/api/fallback", { chain }); renderFallback(); toast(msg); }
  catch (e) { toast(e.message, 4500); }
}
$("integrationsView").addEventListener("click", (e) => {
  const b = e.target.closest("[data-fb-up],[data-fb-down],[data-fb-rm],#fbAddBtn"); if (!b || !fb) return;
  const c = [...fb.chain];
  if (b.id === "fbAddBtn") return saveChain([...c, $("fbAdd").value], "Запасной добавлен");
  const i = +(b.dataset.fbUp ?? b.dataset.fbDown ?? b.dataset.fbRm);
  if (b.dataset.fbRm != null) { c.splice(i, 1); return saveChain(c, "Убран из запасных"); }
  const j = b.dataset.fbUp != null ? i - 1 : i + 1; [c[i], c[j]] = [c[j], c[i]];
  saveChain(c, "Порядок сохранён");
});
async function reloadProfiles() { try { meta.profiles = (await api("/api/meta")).profiles; } catch (e) { /* покажем старое */ } }
let orLink = null, orTimer = null;
function profileForm(p, connected) {
  show("mcpForm"); formHelp = hv("form.provider"); helpModule = ""; $("title").textContent = p.title; setSub("<span>модели поставщика</span>");
  clearInterval(orTimer);
  $("mcpForm").innerHTML = `<div class="panel">
    <div class="hero">${mono(p.title, p.id)}<h2 class="serif">${esc(p.title)}</h2><p>${esc(p.about)}</p></div>
    ${connected ? `<div class="result ok">${ic("check")}<span>${esc(p.title)} подключён — ключ сохранён на сервере.</span></div>
      <button class="btn" id="profStart0">${ic("newsess")}Новая сессия с ${esc(p.title)}</button>` : ""}
    <div class="result wait">${ic("warn")}<span>${p.gateway ? `Код и переписка сессий уходят на ваш шлюз и дальше — ${esc(p.short)}; оплата — по тарифу поставщика. Только для России: шлюз и сервер пульта — в России.`
      : `Код и переписка сессий с ${esc(p.title)} уходят ${esc(p.title)}; оплата — по их тарифу.`}</span></div>
    ${gapsHtml(p)}
    ${p.gateway ? `<div class="section">Шлюз</div>
      <p class="note">У ${esc(p.short)} нет API, совместимого с Anthropic, а Claude Code говорит только на нём. Нужен ваш шлюз-переводчик (gpt2giga, LiteLLM) со своим ключом поставщика — как его поднять, в инструкции.</p>
      <button class="btn ghost" id="profGuide">${ic("ext")}Инструкция: шлюз и что работает</button>
      <div class="field"><label for="profUrl">Адрес шлюза</label><input id="profUrl" type="url" autocapitalize="off" spellcheck="false" value="${esc(p.base_url || "")}" placeholder="https://шлюз.пример:8090">
        <div class="hint">${p.base_url ? "Задан — действует для новых сессий." : `Пока не задан — сессии с ${esc(p.short)} не запускаются.`} Шлюз — ваш и в России; ключ шлюза — ниже.</div></div>
      <button class="btn quiet" id="profUrlSave">Сохранить адрес</button>` : ""}
    <div class="section">${p.oauth ? "Аккаунт" : p.gateway ? "Ключ шлюза" : "Ключ API"}</div>
    ${p.oauth ? `${p.key ? `<div class="panel" id="orAcct" style="box-shadow:none"><span class="note">Проверяю аккаунт…</span></div>` : ""}
      <button class="btn${p.key ? " quiet" : ""}" id="orLogin">${ic("ext")}${p.key ? "Войти заново" : "Войти через " + esc(p.title)}</button>
      <div class="hint" style="margin:0 2px 8px">Откроется ${esc(p.title)}: войдите (Google, GitHub или почта) и нажмите «Authorize». Ключ сам вернётся на сервер — копировать ничего не нужно.</div>
      <div id="orWait" hidden></div>
      <details class="manual"><summary class="note" style="display:inline">Или вставить ключ вручную</summary>` : ""}
    ${p.key_url && !p.gateway ? `<button class="btn ghost" id="profKeyPage">${ic("ext")}Где взять ключ</button>` : ""}
    <div class="field"><label for="profKey">${p.key ? "Заменить ключ (сейчас " + esc(p.key.tail) + ")" : "Ключ"}</label>
      <div class="inp"><input id="profKey" type="password" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="вставьте ключ">
      <button class="icon" type="button" data-eye="profKey" aria-label="Показать">${ic("eye")}</button></div>
      <div class="hint">Хранится только на сервере (права 600) и в панель больше не возвращается — копию держите в менеджере паролей.</div></div>
    <button class="btn" id="profSave">Сохранить ключ</button>
    ${p.oauth ? "</details>" : ""}
    ${p.key ? '<button class="btn danger" id="profDel">Удалить ключ</button>' : ""}
    <div id="profResult"></div>
    <div class="section">Модели</div>
    <div class="field"><label for="profMain">Основная</label><input id="profMain" autocapitalize="off" spellcheck="false" value="${esc(p.main)}" placeholder="${esc(p.default_main || "пусто — по умолчанию поставщика")}">
      <div class="hint">Для opus и sonnet. ${esc(p.hint || "")}</div>
      ${p.oauth ? `<button class="btn quiet sm" style="margin-top:8px" data-cat="profMain">${ic("grid", "s16")}Выбрать из каталога</button>` : ""}</div>
    <div class="field"><label for="profFast">Быстрая</label><input id="profFast" autocapitalize="off" spellcheck="false" value="${esc(p.fast)}" placeholder="${esc(p.default_fast || "пусто — по умолчанию поставщика")}">
      <div class="hint">Для haiku, фоновых задач и субагентов.</div>
      ${p.oauth ? `<button class="btn quiet sm" style="margin-top:8px" data-cat="profFast">${ic("grid", "s16")}Выбрать из каталога</button>` : ""}</div>
    <button class="btn quiet" id="profModels">Сохранить модели</button>
    <button class="btn ghost" id="profDefaults">Вернуть по умолчанию</button>
    <p class="note">Изменения моделей и ключа действуют для новых сессий и после «Сменить поставщика».</p></div>`;
  $("mcpForm").querySelectorAll("[data-eye]").forEach((b) => b.onclick = () => { const i = $(b.dataset.eye); i.type = i.type === "password" ? "text" : "password"; });
  $("profKeyPage")?.addEventListener("click", () => { openUrl(p.key_url); });
  $("profGuide")?.addEventListener("click", () => { openUrl(p.guide); });
  $("profUrlSave")?.addEventListener("click", () => api("/api/models", { profile: p.id, main: p.main, fast: p.fast, base_url: $("profUrl").value.trim() })
    .then((d) => { meta.profiles = d.profiles; toast($("profUrl").value.trim() ? "Адрес шлюза сохранён" : "Адрес шлюза убран"); profileForm(profileOf(p.id)); }).catch((err) => toast(err.message, 4500)));
  $("profSave").onclick = (e) => busy(e.currentTarget, "Проверяю ключ…", async () => {
    try {
      const d = await api("/api/keys", { provider: p.id, key: $("profKey").value });
      await reloadProfiles(); haptic("notificationOccurred", "success");
      $("profResult").innerHTML = `<div class="result ok">${ic("check")}<span>${d.checked ? "Ключ работает" : "Ключ сохранён — проверится при первом запуске сессии"}.</span></div>
        <button class="btn" id="profStart">${ic("newsess")}Новая сессия с ${esc(p.title)}</button>`;
      $("profStart").onclick = () => newSession(p.id); $("profKey").value = "";
    } catch (err) { $("profResult").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(err.message)}</span></div>`; haptic("notificationOccurred", "error"); }
  });
  $("profDel")?.addEventListener("click", () => confirmDanger(`Удалить ключ ${p.title}? Уже открытые сессии доработают, новые с ним не запустятся.`, async () => {
    await api("/api/keys/remove", { provider: p.id }); await reloadProfiles(); toast("Ключ удалён"); profileForm(profileOf(p.id));
  }));
  const saveModels = (main, fast) => api("/api/models", { profile: p.id, main, fast }).then((d) => { meta.profiles = d.profiles; toast("Модели сохранены"); profileForm(profileOf(p.id)); }).catch((err) => toast(err.message, 4500));
  $("profModels").onclick = () => saveModels($("profMain").value.trim(), $("profFast").value.trim());
  $("profDefaults").onclick = () => saveModels(p.default_main, p.default_fast);
  $("profStart0")?.addEventListener("click", () => newSession(p.id));
  $("mcpForm").querySelectorAll("[data-cat]").forEach((b) => b.onclick = () => openCatalog($(b.dataset.cat)));
  if (p.oauth) oauthWire(p);
}
// Вход в OpenRouter: ссылку готовим заранее, чтобы открыть её прямо в нажатии (браузеры не любят окна после ожидания).
function oauthWire(p) {
  const fetchLink = () => api("/api/openrouter/start", {}).then((d) => (orLink = { url: d.url, t: Date.now() }));
  if (!orLink || Date.now() - orLink.t > 8 * 60000) fetchLink().catch(() => {});
  if (p.key) api("/api/openrouter/info").then((a) => {
    const usd = (v) => v == null ? "—" : "$" + (+v).toFixed(2);
    document.getElementById("orAcct").innerHTML = `<div class="row"><span class="name" style="flex:1">${esc(a.label || "ключ " + p.key.tail)}</span>
      <span class="chip ok">${a.is_free_tier ? "бесплатный тариф" : "подключён"}</span></div>
      <p class="note" style="margin:8px 0 0">Потрачено всего ${usd(a.usage)}, за месяц ${usd(a.usage_monthly)} · ${a.limit == null ? "без лимита на ключ" : "лимит " + usd(a.limit) + ", осталось " + usd(a.limit_remaining)}</p>`;
  }).catch((e) => { document.getElementById("orAcct").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`; });
  $("orLogin").onclick = async () => {
    let url = orLink && Date.now() - orLink.t < 9 * 60000 ? orLink.url : null;
    orLink = null;
    if (!url) { toast("Готовлю вход…"); try { url = (await fetchLink()).url; orLink = null; } catch (e) { return toast(e.message, 4500); } }
    openUrl(url);
    const before = p.key?.tail || "", t0 = Date.now();
    $("orWait").hidden = false;
    $("orWait").innerHTML = `<div class="result wait">${ic("wait")}<span>Жду ключ от ${esc(p.title)} — войдите и нажмите «Authorize». Проверяю каждые 3 секунды…</span></div>`;
    clearInterval(orTimer);
    orTimer = setInterval(async () => {
      if (view !== "mcpForm" || Date.now() - t0 > 10 * 60000) return clearInterval(orTimer);
      await reloadProfiles();
      const np = profileOf(p.id);
      if (np?.key && np.key.tail !== before) { clearInterval(orTimer); haptic("notificationOccurred", "success"); profileForm(np, true); }
    }, 3000);
    fetchLink().catch(() => {});                       // на случай «попробовать ещё раз»
  };
}
// Каталог моделей OpenRouter: поиск по названию и id; модели Anthropic — первыми (с ними Claude Code надёжен).
function openCatalog(input) {
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.catalog");
  bg.innerHTML = `<div class="sheet picker" role="dialog"><h3>Модели OpenRouter</h3>
    <div class="search"><input id="catQ" type="search" autocapitalize="off" spellcheck="false" placeholder="поиск: claude, glm, deepseek, gemini…"></div>
    <div id="catList"><div class="empty">Загружаю каталог…</div></div><button class="cancel" data-close>Отмена</button></div>`;
  document.body.append(bg);
  let all = [];
  const fmt = (m) => [m.ctx ? Math.round(m.ctx / 1000) + "K контекста" : "", m.in == null ? "" : `$${m.in} / $${m.out} за 1 млн`].filter(Boolean).join(" · ");
  const draw = () => {
    const q = bg.querySelector("#catQ").value.trim().toLowerCase();
    const hits = all.filter((m) => !q || m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q))
      .sort((a, b) => (b.id.startsWith("anthropic/") - a.id.startsWith("anthropic/")) || a.name.localeCompare(b.name)).slice(0, 60);
    bg.querySelector("#catList").innerHTML = hits.length ? hits.map((m) => `<button data-id="${esc(m.id)}">${ic("chip")}<span>${esc(m.name)}
      <small><span class="mid">${esc(m.id)}</span>${fmt(m) ? " · " + esc(fmt(m)) : ""}${m.id.startsWith("anthropic/") ? " · надёжно с Claude Code" : ""}</small></span></button>`).join("")
      : '<div class="empty">Ничего не нашлось</div>';
  };
  bg.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (e.target === bg || b?.hasAttribute("data-close")) return bg.remove();
    if (b?.dataset.id) { input.value = b.dataset.id; bg.remove(); toast("Выбрано — нажмите «Сохранить модели»", 3500); }
  });
  bg.querySelector("#catQ").addEventListener("input", draw);
  api("/api/openrouter/models").then((d) => { all = d.models; draw(); })
    .catch((e) => { bg.querySelector("#catList").innerHTML = `<div class="result bad" style="margin:0 16px">${ic("warn")}<span>${esc(e.message)}</span></div>`; });
}
// ---------- голос: карточки (экран «Голос», шторка по долгому нажатию у ответа) ----------
let vcards = null, vPlaying = null, vWait = null;   // /api/voice/cards: { cards, current, can_choose }; что сейчас слушаем
const vAudio = new Audio();                         // «Послушать» — свой плеер: озвучку ответа не трогает
function voiceGrid() {
  if (!vcards) return '<div class="empty">Загружаю голоса…</div>';
  // Голос без карточки (Piper — выбран раньше или запасной) продолжает читать: пишем об этом строкой под карточками.
  const fb = vcards.fallback ? `<div class="hint vfb">Сейчас ответы читает запасной голос сервера — ${esc(vcards.fallback)}.${vcards.can_choose && vcards.cards.some((c) => c.ok) ? " Выберите голос выше." : ""}</div>` : "";
  if (!vcards.cards.length) return fb || '<div class="empty">Голоса не установлены: gas-pult voices install irina</div>';
  return `<div class="vgrid">${vcards.cards.map((c) => {
    const on = c.ok && c.id === vcards.current, sub = (c.ok ? c.kind : c.why + (c.install ? " · нажмите — команда" : "")) + (c.demo ? " · демо" : "");
    return `<div class="vcard ${on ? "on" : ""} ${c.ok ? "" : "off"}">
      <button class="vpick" data-vpick="${esc(c.id)}" aria-pressed="${on}"><span><b>${esc(c.name)}</b><small>${esc(sub)}</small></span>${on ? ic("check") : ""}</button>
      ${c.ok ? `<button class="vplay ${vWait === c.id ? "wait" : ""}" data-vplay="${esc(c.id)}" aria-label="Послушать: ${esc(c.name)}">${ic(vPlaying === c.id && vWait !== c.id ? "pause" : "play", "s16")}</button>` : ""}
    </div>`; }).join("")}</div>${fb}`;
}
function paintVoiceGrids() { document.querySelectorAll("[data-vgrid]").forEach((el) => { el.innerHTML = voiceGrid(); }); }
function stopPreview() { vAudio.pause(); vPlaying = vWait = null; paintVoiceGrids(); }
vAudio.addEventListener("ended", stopPreview);
async function previewVoice(id) {
  if (vPlaying === id) return stopPreview();
  vAudio.pause(); if (!player().paused) player().pause();
  vPlaying = vWait = id; paintVoiceGrids();
  try {
    const blob = DEMO ? demoTone(1.5) : await api("/api/voice/preview?id=" + encodeURIComponent(id));
    if (vPlaying !== id) return;                    // пока готовили — нажали другой
    if (vAudio.src) URL.revokeObjectURL(vAudio.src);
    vAudio.src = URL.createObjectURL(blob); vWait = null; paintVoiceGrids();
    await vAudio.play();
  } catch (e) { if (vPlaying === id) stopPreview(); if (e.name !== "AbortError") toast("Послушать: " + e.message, 4500); }
}
async function voiceGridClick(e) {
  const play = e.target.closest("[data-vplay]"), pick = e.target.closest("[data-vpick]");
  if (play) return previewVoice(play.dataset.vplay);
  const c = pick && vcards?.cards.find((x) => x.id === pick.dataset.vpick); if (!c) return;
  if (!c.ok) {
    if (c.install) return copyText(c.install, "Команда скопирована — выполните её на сервере");
    const k = $("elKey");
    if (k?.isConnected && !k.closest(".sheet-bg")) { k.scrollIntoView({ block: "center", behavior: "smooth" }); return k.focus({ preventScroll: true }); }
    return toast("Нужен ключ ElevenLabs: Интеграции → Голос → Ключи API", 4000);
  }
  if (!vcards.can_choose) return toast("Голос выбирает владелец пульта — здесь можно послушать", 3500);
  if (c.id === vcards.current) return c.id === "elevenlabs" ? elVoiceSheet() : undefined;
  try {
    vcards = await api("/api/voice/choose", { id: c.id }); haptic("selectionChanged"); paintVoiceGrids(); toast("Голос: " + c.name);
    if (prov && $("voiceBox")?.isConnected) renderVoice();
  } catch (err) { toast(err.message, 4500); }
}
function elVoiceSheet() {                           // голос внутри ElevenLabs — шторкой, без выпадающего списка
  if (!prov?.el_voices?.length) return;
  helpSheet("sheet.el-voice");
  sheet("Голос ElevenLabs", prov.el_voices.map((v) => ({ label: v.name, icon: "vol", on: v.id === prov.el_voice, run: async () => {
    try { await api("/api/providers", { el_voice: v.id }); prov.el_voice = v.id; vcards = await api("/api/voice/cards"); paintVoiceGrids(); toast("Голос: " + v.name); }
    catch (err) { toast(err.message, 4500); } } })));
}
async function openVoiceSheet() {                   // долгое нажатие на «Прослушать»: те же карточки шторкой
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.voice");
  bg.innerHTML = `<div class="sheet" role="dialog"><h3>Голос озвучки</h3><div data-vgrid>${voiceGrid()}</div><p class="note vnote"></p><button class="cancel" data-close>Закрыть</button></div>`;
  const close = () => { bg.remove(); if (vPlaying) stopPreview(); };
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) return close(); voiceGridClick(e); });
  bg.addEventListener("contextmenu", (e) => e.preventDefault());
  document.body.append(bg);
  try { vcards = await api("/api/voice/cards"); paintVoiceGrids(); }
  catch (err) { bg.querySelector("[data-vgrid]").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(err.message)}</span></div>`; return; }
  bg.querySelector(".vnote").textContent = vcards.can_choose ? "Нажмите на голос — он сразу станет голосом озвучки; круглая кнопка справа — послушать." : "Голос выбирает владелец пульта — здесь можно послушать.";
}
function renderVoice() {
  const el = prov.keys.elevenlabs, seg = (name, val, opts) => `<div class="seg" data-prov="${name}">${opts.map(([v, label]) =>
    `<button data-val="${v}" class="${val === v ? "on" : ""}" ${v === "elevenlabs" && !el ? "disabled" : ""}>${esc(label)}</button>`).join("")}</div>`;
  $("voiceBox").innerHTML = `
    <div class="section">Голос</div>
    <div class="panel">
      <div class="field"><label>Озвучка ответов</label>
        <div data-vgrid>${voiceGrid()}</div>
        ${vcards?.current === "elevenlabs" && prov.el_voices.length > 1 ? `<button class="btn ghost" id="elOther">${ic("vol", "s16")}Другой голос ElevenLabs</button>` : ""}
        <div class="hint">Нажмите на голос — он сразу станет голосом озвучки; круглая кнопка справа — послушать. На сервере — бесплатно и приватно. ElevenLabs — живее, платно; текст ответа уходит в ElevenLabs.${vcards?.cards.some((c) => c.demo) ? " «Демо» — голоса с некоммерческой лицензией, только для показа." : ""} Быстрый путь — долгое нажатие на «Прослушать» у ответа.</div></div>
      <div class="field" style="margin:0"><label>Распознавание голосовых</label>${seg("stt", prov.stt, [["local", "На сервере · whisper"], ["elevenlabs", "ElevenLabs Scribe"]])}
        <div class="hint">ElevenLabs точнее на терминах и именах; запись голоса уходит в ElevenLabs.</div></div>
    </div>
    <div class="section">Ключи API</div>
    <div class="panel">
      <div class="row"><span class="name" style="flex:1">ElevenLabs</span><span class="chip ${el ? "ok" : ""}">${el ? "ключ " + esc(el.tail) : "нет ключа"}</span></div>
      <div class="field" style="margin:12px 0 0"><label for="elKey">${el ? "Заменить ключ" : "Ключ API"}</label>
        <div class="inp"><input id="elKey" type="password" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="sk_…">
        <button class="icon" type="button" data-eye="elKey" aria-label="Показать">${ic("eye")}</button></div>
        <div class="hint">elevenlabs.io → профиль → API Keys → Create. Ключ хранится только на сервере (права 600) и сюда больше не возвращается — сохраните копию в менеджере паролей.</div></div>
      <button class="btn" id="elSave">Сохранить и проверить</button>
      ${el ? '<button class="btn danger" id="elDel">Удалить ключ</button>' : ""}
      <div id="elResult"></div>
    </div>`;
}
$("integrationsView").addEventListener("click", async (e) => {
  if (e.target.closest("[data-vgrid]")) return voiceGridClick(e);
  if (e.target.closest("#elOther")) return elVoiceSheet();
  const segBtn = e.target.closest("[data-prov] button");
  if (segBtn && !segBtn.disabled) {
    try { await api("/api/providers", { [segBtn.parentElement.dataset.prov]: segBtn.dataset.val }); prov = await api("/api/providers"); renderVoice(); toast("Сохранено"); }
    catch (err) { toast(err.message, 4500); }
  }
  const eye = e.target.closest("[data-eye]"); if (eye) { const i = $(eye.dataset.eye); i.type = i.type === "password" ? "text" : "password"; }
  if (e.target.id === "elSave") busy(e.target, "Проверяю ключ…", async () => {
    try { const d = await api("/api/keys", { provider: "elevenlabs", key: $("elKey").value });
          [prov, vcards] = await Promise.all([api("/api/providers"), api("/api/voice/cards")]); renderVoice();
          $("elResult").innerHTML = `<div class="result ok">${ic("check")}<span>Ключ работает, голосов в аккаунте: ${d.voices.length}. Нажмите карточку ElevenLabs выше.</span></div>`; haptic("notificationOccurred", "success"); }
    catch (err) { $("elResult").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(err.message)}</span></div>`; haptic("notificationOccurred", "error"); }
  });
  if (e.target.id === "elDel") confirmDanger("Удалить ключ ElevenLabs?", async () => { await api("/api/keys/remove", { provider: "elevenlabs" }); [prov, vcards] = await Promise.all([api("/api/providers"), api("/api/voice/cards")]); renderVoice(); toast("Ключ удалён, голос — снова на сервере"); });
});
const isOn = (c) => mcpData.servers.some((s) => s.ok && s.name.startsWith("claude.ai ") && s.name.toLowerCase().includes(c.match.toLowerCase()));
const pname = (s) => s.name.replace(/^claude\.ai /, "").replace(/^plugin:[^:]+:/, "");
function renderMcp() {
  const srv = mcpData.servers, ok = srv.filter((s) => s.ok), bad = srv.filter((s) => !s.ok && s.removable);
  const anyTiles = mcpData.presets.filter((p) => p.providers === "all" && !["http", "stdio"].includes(p.id));   // задача 38
  $("mcpBox").innerHTML = `
    <p class="note">${mcpData.personal ? "Интеграции у каждого свои: здесь — ваши, они работают в сессиях, которые открыли вы. В первой своей сессии войдите в Claude на «Экране» — без входа коннекторы claude.ai не появятся."
      : "Интеграции у каждого человека пульта свои — здесь ваши."}</p>
    <div class="section">Подключено</div>
    ${ok.length ? `<div class="conn">${ok.map((s) => `<span class="chip ok">${ic("check", "s16")}${esc(pname(s))}</span>`).join("")}</div>` : '<p class="note">Пока ничего. Выберите сервис ниже.</p>'}
    ${bad.map((s) => `<div class="card" style="margin-top:8px;cursor:default"><div class="row"><span class="name" style="flex:1">${esc(pname(s))}</span><span class="chip bad">${/auth/i.test(s.state) ? "нужен вход" : "не работает"}</span></div>
      <button class="btn danger sm" data-rm="${srv.indexOf(s)}" style="margin-top:10px">Убрать</button></div>`).join("")}
    <div class="section">${esc(T("int.any.title"))}</div>
    <p class="note">${esc(T("int.any.note"))} Нажмите на сервис — дальше всё по шагам.</p>
    <div class="tiles">
      ${anyTiles.map((p) => `<button class="tile" data-p="${mcpData.presets.indexOf(p)}">${mono(p.title, p.id)}<span>${esc(p.title)}</span><small>${esc(p.about.split(":")[0].split(" — ")[0])}</small><small class="chip ok">${esc(T("int.any.chip"))}</small></button>`).join("")}
    </div>
    <div class="section">${esc(T("int.claude.title"))}</div>
    <p class="note">${esc(T("int.claude.note"))}</p>
    <div class="tiles">
      ${mcpData.connectors.map((c, i) => `<button class="tile ${isOn(c) ? "on" : ""}" data-c="${i}">${mono(c.title, c.id)}<span>${esc(c.title)}</span><small>${isOn(c) ? "подключено" : esc(c.about)}</small><small class="chip space">${esc(T("int.claude.chip"))}</small></button>`).join("")}
      <button class="tile" data-more="1"><span class="mono">${ic("plus")}</span><span>Другой сервис</span><small>каталог claude.ai или вручную</small></button>
    </div>
    <button class="btn ghost" id="mcpRefresh" style="margin-top:12px">${ic("refresh")}Обновить список</button>`;
}
$("integrationsView").addEventListener("click", (e) => {
  const rm = e.target.closest("[data-rm]"), p = e.target.closest("[data-p]"), c = e.target.closest("[data-c]"), more = e.target.closest("[data-more]");
  const rf = e.target.closest("#mcpRefresh"); if (rf) return busy(rf, "Проверяю…", () => loadMcp(true));
  if (rm) {
    const s = mcpData.servers[+rm.dataset.rm];
    return confirmDanger(`Убрать «${pname(s)}»?`, () => busy(rm, "Убираю…", async () => { try { await api("/api/mcp/remove", { name: s.name }); toast("«" + pname(s) + "» убран"); loadMcp(true); } catch (err) { toast(err.message, 4500); } }));
  }
  if (c) return connectorView(mcpData.connectors[+c.dataset.c]);
  if (p) return mcpForm(mcpData.presets[+p.dataset.p]);
  if (more) return moreView();
});
let connTimer = null;
function connectorView(c) {
  show("mcpForm"); formHelp = hv("form.connector"); $("title").textContent = c.title; setSub("<span>подключение сервиса</span>");
  const on = isOn(c);
  $("mcpForm").innerHTML = `<div class="panel">
    <div class="hero">${mono(c.title, c.id)}<h2 class="serif">${esc(c.title)}</h2><p>${esc(c.about)}</p></div>
    ${on ? "" : `<ol class="steps">
      <li><button class="btn sm" id="openClaude">${ic("ext")}Открыть claude.ai</button>
        <div class="hint">Откроется страница «Коннекторы». Если попросит войти — тем же аккаунтом Claude, ${mcpData.personal ? "которым вы вошли в своей сессии пульта" : "что и на сервере"}.</div></li>
      <li>Найдите <b>${esc(c.title)}</b> и нажмите <b>«Подключить»</b> (Connect). Войдите в ${esc(c.title)} как обычно.</li>
      <li>Вернитесь сюда. Отметка появится сама.</li></ol>`}
    ${connAlt(c)}
    <div id="connStatus" class="result ${on ? "ok" : "wait"}">${on ? `${ic("check")}<span>${esc(c.title)} подключён</span>` : `${ic("wait")}<span>Жду подключения — проверяю каждые 10 секунд…</span>`}</div>
    <div id="connNext">${on ? tryButton(c) : '<button class="btn ghost" id="connCheck">Проверить сейчас</button>'}</div>
    <details style="margin-top:10px"><summary class="note" style="display:inline">Не получается?</summary>
      <p class="note">Отметка не появляется 2–3 минуты — нажмите «Проверить сейчас». В claude.ai нет ${esc(c.title)} — «Другой сервис» → «Для продвинутых». Открытые сессии увидят сервис после перезапуска, новые — сразу.</p></details></div>`;
  $("openClaude")?.addEventListener("click", () => { openUrl(mcpData.connectors_url); });
  $("connCheck")?.addEventListener("click", (e) => busy(e.target, "Проверяю…", () => checkConn(c)));
  clearInterval(connTimer);
  if (!on) connTimer = setInterval(() => { if (view !== "mcpForm") return clearInterval(connTimer); checkConn(c); }, 10000);
}
function connAlt(c) {                                // задача 38: коннектор — только Claude; замена через сервер
  const p = c.alt && mcpData.presets.find((x) => x.id === c.alt);
  return p ? `<div class="result wait">${ic("warn")}<span>${esc(T("int.alt", { title: p.title }))}</span></div>
    <button class="btn ghost" data-p-alt="${esc(p.id)}">${ic("puzzle")}${esc(T("int.alt.btn", { title: p.title }))}</button>` : "";
}
async function checkConn(c) {
  try {
    const d = await api("/api/mcp/connected?id=" + c.id);
    if (!d.ok) { if (d.found) $("connStatus").innerHTML = `${ic("wait")}<span>Claude видит ${esc(c.title)}, но вход не завершён — закончите вход в claude.ai</span>`; return; }
    clearInterval(connTimer); haptic("notificationOccurred", "success");
    $("connStatus").className = "result ok"; $("connStatus").innerHTML = `${ic("check")}<span>${esc(c.title)} подключён</span>`;
    $("connNext").innerHTML = tryButton(c); mcpData = await api("/api/mcp");
  } catch (e) { /* сеть моргнула — следующая проверка через 10 с */ }
}
function tryButton(c) { return `<p class="note" style="margin:10px 0 4px">Попробуйте — панель отправит это в сессию Claude:</p><button class="btn" data-try="${esc(c.example)}">«${esc(c.example)}»</button>`; }
$("mcpForm").addEventListener("click", async (e) => {
  const t = e.target.closest("[data-try]");
  if (t) {
    const s = sessions.find((x) => x.active && x.status !== "busy") || sessions.find((x) => x.status === "idle") || sessions[0];
    if (!s) return toast("Нет открытых сессий — откройте новую", 4500);
    return busy(t, "Отправляю…", async () => {
      try { await api("/api/send", { w: s.id, text: t.dataset.try }); toast("Отправлено в «" + s.name + "»"); clearInterval(connTimer); openSession(s.id); }
      catch (err) { toast("Не отправлено: " + err.message, 4500); }
    });
  }
  const p = e.target.closest("[data-p2]"); if (p) return mcpForm(mcpData.presets[+p.dataset.p2]);
  const lg = e.target.closest("[data-login]"); if (lg) return startLogin(lg.dataset.login, lg);
});
function moreView() {
  show("mcpForm"); formHelp = hv("form.more"); $("title").textContent = "Другой сервис"; setSub("<span>каталог и ручное подключение</span>");
  $("mcpForm").innerHTML = `<div class="panel">
    <p style="margin-top:0">Сотни сервисов подключаются так же — через каталог claude.ai: найдите свой и нажмите «Подключить».</p>
    <button class="btn" id="openCatalog">${ic("ext")}Открыть каталог claude.ai</button>
    <p class="note">После подключения сервис появится в «Подключено» («Обновить список»).</p>
    <div class="section">Для продвинутых</div>
    ${mcpData.presets.map((p, i) => `<button class="card" data-p2="${i}"><div class="row">${mono(p.title, p.id)}<div class="ctext"><div class="name">${esc(p.title)}</div><div class="meta" style="white-space:normal">${esc(p.about)}</div></div></div></button>`).join("")}
    ${mcpData.servers.filter((s) => !s.ok && /auth/i.test(s.state) && s.removable).map((s) => `<button class="btn ghost" data-login="${esc(s.name)}">${ic("key")}Войти в ${esc(s.name)} через сервер</button>`).join("")}</div>`;
  $("openCatalog").onclick = () => { openUrl(mcpData.connectors_url); };
}
async function startLogin(name, btn) {
  await busy(btn, "Готовлю вход… (до 20 секунд)", async () => {
    try {
      const a = await api("/api/mcp/login", { name });
      const box = document.createElement("div"); box.innerHTML = authCard(a, name, a.w) + `<p class="note">Вход идёт через сессию «${esc(a.session)}». Ссылка действует несколько минут.</p>`;
      btn.replaceWith(box); box.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) { toast(e.message, 5000); }
  });
}
function mcpForm(p) {
  show("mcpForm"); formHelp = hv("form.preset"); $("title").textContent = p.title; setSub("<span>подключение</span>");
  const fields = p.fields.map((f) => `<div class="field"><label for="f_${f.key}">${esc(f.label)}${f.optional ? ' <span class="opt">— необязательно</span>' : ""}</label>
      <div class="inp">${f.options ? `<select id="f_${f.key}">${f.options.map((o) => `<option value="${esc(o.v)}">${esc(o.t)}</option>`).join("")}</select>` : f.multiline ? `<textarea id="f_${f.key}" rows="3" placeholder="${esc(f.placeholder || "")}"></textarea>`
        : `<input id="f_${f.key}" type="${f.secret ? "password" : "text"}" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="${esc(f.placeholder || "")}">`}
      ${f.secret && !f.multiline ? `<button class="icon" type="button" data-eye="f_${f.key}" aria-label="Показать">${ic("eye")}</button>` : ""}</div>
      ${f.hint ? `<div class="hint">${esc(f.hint)}</div>` : ""}</div>`).join("");
  $("mcpForm").innerHTML = `<div class="panel">
      <div class="hero">${mono(p.title, p.id)}<h2 class="serif">${esc(p.title)}</h2><p>${esc(p.about)}</p></div>
      ${p.id === "http" || p.id === "stdio" ? `<div class="field"><label for="f__name">Короткое название (латиницей)</label><input id="f__name" placeholder="например: crm" autocapitalize="off" spellcheck="false">
        <div class="hint">Как инструмент будет называться у Claude. Это не логин — логин и пароль здесь не нужны.</div></div>` : `<input id="f__name" type="hidden" value="${esc(p.id)}">`}
      ${!p.fields.length ? `<div class="result ok">${ic("check")}<span>Ключ не нужен. Нажмите «Подключить», затем «Войти».</span></div>` : ""}
      ${p.key_url || p.fields.some((f) => f.options?.some((o) => o.key_url)) ? `<button class="btn ghost" id="keyPage" type="button">${ic("ext")}Открыть страницу, где взять ключ</button>` : ""}
      ${fields}
      ${p.after ? `<div class="result wait"><span>После подключения: ${esc(clean(p.after))}</span></div>` : ""}
      <button class="btn" id="mcpAdd">Подключить</button>
      <div id="mcpResult"></div>
      <p class="note">Ключи сохраняются только на вашем сервере и в панели больше не показываются.</p></div>`;
  $("mcpForm").querySelectorAll("[data-eye]").forEach((b) => b.onclick = () => { const i = $(b.dataset.eye); i.type = i.type === "password" ? "text" : "password"; });
  $("keyPage")?.addEventListener("click", () => {
    const opt = p.fields.filter((f) => f.options).map((f) => f.options.find((o) => o.v === $("f_" + f.key).value)).find((o) => o?.key_url);
    if (opt) return openUrl(opt.key_url);                // ключ выбранного сервиса (веб-поиск: Яндекс, Brave…)
    const base = ($("f_base")?.value || "").trim().replace(/\/$/, "");
    if (p.key_url.includes("{base}") && !base) return toast("Сначала впишите адрес " + p.title + " — поле ниже", 4000);
    const url = p.key_url.replace("{base}", base);
    openUrl(url);
  });
  $("mcpAdd").onclick = (e) => busy(e.target, "Подключаю и проверяю…", async () => {
    const values = Object.fromEntries(p.fields.map((f) => [f.key, $("f_" + f.key).value]));
    try {
      const d = await api("/api/mcp/add", { preset: p.id, name: $("f__name").value.trim(), values });
      const needLogin = /не отвечает|вход/i.test(d.result);
      $("mcpResult").innerHTML = `<div class="result ok">${ic("check")}<span>${esc(clean(d.result.split(". Если")[0].split(". Вход")[0]))}</span></div>` +
        (needLogin ? `<button class="btn" data-login="${esc($("f__name").value.trim())}">${ic("key")}Войти в ${esc(p.title)}</button>` : "") +
        `<button class="btn ghost" id="mcpDone">Готово — к списку</button>`;
      $("mcpDone").onclick = back; haptic("notificationOccurred", "success");
    } catch (err) { $("mcpResult").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(err.message)}</span></div>`; haptic("notificationOccurred", "error"); }
  });
}

// ---------- модули-агенты: «Новая сессия» → «Из модуля» ----------
// Каталог модулей (/api/modules) → экран модуля: интеграции с состоянием и «Подключить» (тот же мастер, что в
// «Интеграциях»), источники данных, расписание, решения кнопками → имя папки → «Создать» → открывается сессия.
let formBack = null, modData = null;               // formBack — куда «‹ Назад» с экрана формы (модуль → подключение)
const goSessions = () => { show("home"); setHome("sessions"); };
async function modulesView() {
  show("mcpForm"); formBack = goSessions; formHelp = hv("modules"); helpModule = ""; $("title").textContent = "Из модуля"; setSub("<span>готовые агенты под задачу</span>");
  $("mcpForm").innerHTML = '<div class="empty">Загружаю модули…</div>';
  await dictReady;                                   // «изменено N назад» — из словаря
  try { modData = await api("/api/modules"); } catch (e) { $("mcpForm").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`; return; }
  await scnLoad().catch(() => null);               // сценарии — для «Как это выглядит в работе» у отрасли; нет — без ссылок
  const groups = [...new Set(modData.modules.map((m) => m.industry))];
  const scnLink = (g) => scnData?.scenarios.some((x) => x.industries.includes(g)) ? `<button class="scn-link" data-scn-ind="${esc(g)}">Как это выглядит в работе${ic("chevron")}</button>` : "";
  $("mcpForm").innerHTML = `<div class="mods">
    <p class="note">Модуль — готовое пространство: агент с ролью и правилами, навыки, пример данных, расписание и решения кнопками. Создаётся новой папкой в «${esc(modData.root)}» — ваши папки не трогаются.</p>
    ${scnData ? `<button class="scn-entry" data-scn-entry>${ic("eye")}<span class="ctext"><b>Примерить на себя</b> — день с агентом по ролям: до создания пространства</span>${ic("chevron")}</button>` : ""}
    ${groups.map((g) => `<div class="section">${esc(g)}</div>${scnLink(g)}` + modData.modules.filter((m) => m.industry === g).map((m) =>
      `<button class="card" data-mod="${esc(m.id)}"><div class="row"><span class="mono">${ic("puzzle")}</span><div class="ctext"><div class="name">${esc(m.title)}</div>
        <div class="meta">${esc(m.about)}</div>${m.schedule.length ? `<span class="chip">${ic("wait", "s16")}${esc(m.schedule.map((x) => x.when || x.at).join(", "))}</span>` : ""}</div>${ic("chevron")}</div></button>`).join("")).join("")}
    ${modData.errors?.length && meta?.role === "owner" ? `<div class="result bad">${ic("warn")}<span>Не загружены: ${esc(modData.errors.join("; "))}</span></div>` : ""}</div>`;
}
$("mcpForm").addEventListener("click", (e) => {
  const c = e.target.closest("[data-mod]"); if (c) return moduleView(modData.modules.find((m) => m.id === c.dataset.mod));
  const k = e.target.closest("[data-mconn]"); if (k) return moduleConnect(k.dataset.mconn);
  if (e.target.closest("#modCreate")) return moduleCreate(e.target.closest("#modCreate"));
  const o = e.target.closest("[data-mopen]"); if (o) return openFolder(o.dataset.mopen === "" ? null : +o.dataset.mopen, o.dataset.mw, o);
});
// Открыть уже существующую папку (пространство модуля, занятое имя «Новой папки»): окно открыто — в него, нет —
// новая сессия в этой папке (/api/new: одно окно на проект, сервер сам вернёт работающее).
async function openFolder(i, wid, btn) {
  if (wid) { await refresh(); return openSession(wid); }
  if (i == null) return toast("Папка не в списке проектов — обновите панель", 4000);
  pickProfile((profile) => busy(btn, "Открываю…", async () => {
    try { const d = await api("/api/new", { i, profile }); await refresh(); openSession(d.id); }
    catch (err) { toast("Не вышло: " + err.message, 5000); }
  }));
}
const integrOn = (x) => !mcpData ? null : x.kind === "connector" ? isOn(x) : x.kind === "preset" ? mcpData.servers.some((s) => s.ok && s.name === x.id) : null;
function moduleIntegr(m) {
  if (!m.integrations.length) return '<p class="note">Не нужны — всё работает в папке пространства.</p>';
  return m.integrations.map((x) => {
    const on = integrOn(x), wait = mcpData === null && x.kind !== "manual" && meta?.role !== "viewer";
    const state = x.kind === "manual" ? '<span class="chip">вручную</span>' : wait ? '<span class="chip">проверяю…</span>'
      : on ? `<span class="chip ok">${ic("check", "s16")}подключено</span>` : `<span class="chip ${x.optional ? "" : "bad"}">не подключено</span>`;
    const btn = x.kind !== "manual" && on === false && meta?.role !== "viewer" ? `<button class="btn ghost sm" data-mconn="${esc(x.id)}">Подключить</button>` : "";
    return `<div class="mrow">${mono(x.title, x.id)}<div class="ctext"><b>${esc(x.title)}</b>
      <small>${esc(x.why)}</small>${x.how ? `<small>${esc(x.how)}</small>` : ""}<div class="opts">${state}${x.optional ? '<span class="chip">по желанию</span>' : '<span class="chip accent">нужно</span>'}</div>${btn}</div></div>`;
  }).join("");
}
function daysText(d) { return d.length === 7 ? "каждый день" : d.join() === "1,2,3,4,5" ? "по будням" : d.map((x) => "пн вт ср чт пт сб вс".split(" ")[x - 1]).join(", "); }
function moduleView(m) {
  if (!m) return;
  show("mcpForm"); formBack = modulesView; formHelp = hv("module"); helpModule = m.id; $("title").textContent = m.title; setSub(`<span>модуль · ${esc(m.industry)}</span>`);
  const can = meta?.role !== "viewer";
  $("mcpForm").innerHTML = `<div class="mod">
    <div class="hero"><span class="mono">${ic("puzzle")}</span><h2 class="serif">${esc(m.title)}</h2><p>${esc(m.about)}</p></div>
    ${m.description ? `<div class="panel"><p style="margin:0">${esc(m.description)}</p></div>` : ""}
    <div class="section">Интеграции</div><div class="panel" id="modIntegr">${moduleIntegr(m)}</div>
    ${m.data_sources?.length ? `<div class="section">Откуда данные</div><div class="panel">${m.data_sources.map((x) => `<div class="mrow">${ic("file")}<div class="ctext"><b>${esc(x.title)}</b><small>${esc(x.kind_title)}${x.about ? " · " + esc(x.about) : ""}</small></div></div>`).join("")}
      <p class="note" style="margin:8px 0 0">Только официальные API и выгрузки клиента.</p></div>` : ""}
    <div class="section">Расписание</div><div class="panel">${m.schedule.length ? m.schedule.map((x) => `<div class="mrow">${ic("wait")}<div class="ctext"><b>${esc(x.when || x.at)} · ${esc(daysText(x.days))}</b><small>${esc(x.title)}</small></div></div>`).join("")
      + '<p class="note" style="margin:8px 0 0">В это время пульт отправит задание в сессию пространства; окна нет — откроет его и сообщит в боте.</p>' : '<p class="note" style="margin:0">Без расписания — работает, когда вы пишете.</p>'}</div>
    ${m.decisions.length ? `<div class="section">Решения кнопками</div><div class="panel">${m.decisions.map((x) => `<div class="mrow">${ic("help")}<div class="ctext"><b>${esc(x.question)}</b>${x.when ? `<small>${esc(x.when)}</small>` : ""}
      <div class="opts">${x.options.map((o) => `<span class="chip accent">${esc(o)}</span>`).join("")}</div></div></div>`).join("")}
      <p class="note" style="margin:8px 0 0">Агент спрашивает вариантами — кнопки приходят в Telegram и появляются в панели.</p></div>` : ""}
    <div class="section">Что будет в папке</div><div class="panel"><div class="conn">${[...m.files, ...(m.skills.length ? [".claude/skills/"] : []), ...(m.agents?.length ? [".claude/agents/"] : [])].map((f) => `<span class="chip">${esc(f)}</span>`).join("")}</div>
      ${m.skills.length ? `<p class="note" style="margin:8px 0 0">Навыки: ${esc(m.skills.join(", "))}${m.uses?.length ? " · общие блоки: " + esc(m.uses.map((u) => u.title).join(", ")) : ""}</p>` : ""}
      ${m.agents?.length ? `<p class="note" style="margin:8px 0 0">Проверяющие: ${m.agents.map((a) => `<b>${esc(a.title)}</b> — ${esc(a.about)}`).join(" ")} Позовите словами: «отдай на слепую проверку».</p>` : ""}</div>
    ${can && m.existing?.length ? `<div class="section">Уже есть</div><div class="panel">${m.existing.map((x) => `<button class="btn" data-mopen="${x.i ?? ""}" data-mw="${esc(x.open || "")}">${ic("folder")}Открыть «${esc(x.folder)}»</button>
      <p class="note" style="margin:-2px 0 10px">${esc(x.path)}${x.changed && agoText(x.changed) ? " · изменено " + esc(agoText(x.changed, nowSec(), true)) : ""}${x.open ? " · сессия открыта" : ""}${x.schedule ? " · расписание: " + esc(x.schedule.text) + " — " + esc(schedLabel(x.schedule)) : ""}</p>`).join("")}</div>` : ""}
    ${can ? `<div class="section">${m.existing?.length ? "Создать ещё одно" : "Создать пространство"}</div><div class="panel">
      <div class="field"><label for="modName">Имя папки</label><input id="modName" value="${esc(m.folder)}" autocapitalize="off" spellcheck="false" autocomplete="off">
        <div class="hint">Латиница, цифры, дефис. Папка появится в «${esc(modData?.root || "projects")}»; существующие не перезаписываются.</div></div>
      <button class="btn${m.existing?.length ? " ghost" : ""}" id="modCreate" data-id="${esc(m.id)}">${ic("plus")}${m.existing?.length ? "Создать ещё одно пространство" : "Создать и открыть сессию"}</button></div>` : '<p class="viewonly">У вас доступ только на просмотр.</p>'}</div>`;
  if (can && mcpData === null && m.integrations.some((x) => x.kind !== "manual")) api("/api/mcp").then((d) => { mcpData = d; if (view === "mcpForm" && $("modIntegr")) $("modIntegr").innerHTML = moduleIntegr(m); })
    .catch(() => { mcpData = { servers: [], connectors: [], presets: [] }; if ($("modIntegr")) $("modIntegr").innerHTML = moduleIntegr(m); });
}
function moduleConnect(id) {
  const m = modData.modules.find((x) => x.integrations.some((i) => i.id === id) && $("modCreate")?.dataset.id === x.id) || modData.modules.find((x) => x.integrations.some((i) => i.id === id));
  const c = mcpData?.connectors.find((x) => x.id === id), p = mcpData?.presets.find((x) => x.id === id);
  if (!c && !p) return toast("Этот сервис подключается в «Интеграциях»", 4000);
  c ? connectorView(c) : mcpForm(p); formBack = () => moduleView(m);
}
function moduleCreate(btn) {
  const m = modData.modules.find((x) => x.id === btn.dataset.id), name = $("modName").value.trim().toLowerCase();
  if (!/^[a-z0-9][a-z0-9-]{1,40}$/.test(name)) return toast("Имя папки: латиница в нижнем регистре, цифры, дефис (2–41 знак)", 4500);
  const again = !!m.existing?.length;                  // уже есть — ещё одно только после подтверждения
  if (again && !btn.dataset.sure) return confirmDanger(`Создать ещё одно пространство «${name}»? Этот модуль уже есть в «${m.existing[0].folder}» — его можно просто открыть.`,
    () => { btn.dataset.sure = "1"; moduleCreate(btn); });
  pickProfile((profile) => busy(btn, "Создаю пространство…", async () => {
    try {
      const d = await api("/api/modules/create", { id: m.id, name, profile, again }); haptic("notificationOccurred", "success");
      toast(`Пространство «${d.folder}» создано — агент получит первое задание, когда Claude будет готов`, 4500);
      modData = null; await refresh(); openSession(d.id);
    } catch (err) { toast("Не вышло: " + err.message, 5000); haptic("notificationOccurred", "error"); }
  }));
}
// ---------- «Примерочная» («Примерить на себя»): понял → примерил → подключил (scenarios.py, docs/SCENARIOS.md) ----------
// Данные — /api/scenarios (в демо — тот же JSON, вшитый ниже). Кнопки-решения — как в модулях; нажатие показывает
// outcome_toast — что произошло бы, ничего не выполняя. Калькулятор — по формулам из toml (benefitCalc — как в Python).
/* benefit:start — тот же расчёт, что scenarios.benefit() в Python; тест сверяет */
function benefitCalc(s, vals) {
  const c = s.calculator;
  const num = (x, d) => { if (typeof x === "boolean" || x == null) return d; const v0 = typeof x === "string" ? x.trim().replace(",", ".") : x;
    if (v0 === "") return d; const v = Number(v0); return Number.isFinite(v) ? v : d; };
  const inp = {};
  for (const x of c.inputs) inp[x.id] = Math.min(x.max, Math.max(x.min, num(vals?.[x.id], x.default)));
  const rnd = (v, r) => Math.floor(v / r + 0.5) * r;
  const fmt = (v) => { const t = Math.floor(v * 10 + 0.5), w = Math.floor(t / 10), f = t % 10; return String(w).replace(/\B(?=(\d{3})+(?!\d))/g, " ") + (f ? "," + f : ""); };
  const lines = c.formulas.map((l) => {
    let base = 1; for (const k of l.of) base *= inp[k];
    const low = rnd(base * l.low, l.round), high = rnd(base * l.high, l.round);
    return { title: l.title, caption: l.caption, unit: l.unit, low, high, text: (low === high ? "≈ " + fmt(low) : fmt(low) + "–" + fmt(high)) + " " + l.unit, about: l.about };
  });
  return { inputs: inp, lines, disclaimer: c.assumptions_disclaimer };
}
/* benefit:end */
let scnData = null, scn = null;                    // scn — открытая роль: { r, step, picked: {шаг: кнопка}, vals, back, list, connect }
async function scnLoad() { if (!scnData) scnData = await api("/api/scenarios"); return scnData; }
const scnWord = (n) => n === 1 ? "модуль" : n < 5 ? "модуля" : "модулей";
async function scenariosView(roleId, from) {
  const back = from || goSessions;
  show("mcpForm"); formBack = back; formHelp = hv("scenarios"); helpModule = ""; $("title").textContent = "Примерить на себя"; setSub("<span>день с агентом в вашей роли · пример</span>");
  $("mcpForm").innerHTML = '<div class="empty">Загружаю роли…</div>';
  try { await scnLoad(); } catch (e) { $("mcpForm").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`; return; }
  const r = roleId && scnData.scenarios.find((x) => x.id === roleId);
  if (r) return scnOpen(r, 0, () => scenariosView(null, back), back);
  const groups = [...new Set(scnData.scenarios.map((x) => x.industries[0]))];
  $("mcpForm").innerHTML = `<div class="mods">
    <p class="note">Выберите роль — покажем день с агентом: сообщения со временем и кнопки-решения, как в модулях, а в конце — калькулятор пользы с допущениями, которые можно поправить. Всё — выдуманный пример, ничего не отправляется.</p>
    ${groups.map((g) => `<div class="section">${esc(g)}</div>` + scnData.scenarios.filter((x) => x.industries[0] === g).map((x) =>
      `<button class="card" data-scn="${esc(x.id)}"><div class="row"><span class="mono">${ic("eye")}</span><div class="ctext"><div class="name">${esc(x.title)}</div>
        <div class="meta">${esc(x.short)}</div><span class="chip">${ic("puzzle", "s16")}${x.modules.length} ${scnWord(x.modules.length)}</span></div>${ic("chevron")}</div></button>`).join("")).join("")}
    <p class="note">Другие отрасли каталога появятся здесь следующим шагом.</p>
    ${scnData.errors?.length && meta?.role === "owner" ? `<div class="result bad">${ic("warn")}<span>Не загружены: ${esc(scnData.errors.join("; "))}</span></div>` : ""}</div>`;
}
function scnOpen(r, step, back, list) { scn = { r, step, picked: {}, vals: {}, back, list: list || back, connect: false }; formBack = back; scnRender(); }
function scnRender() {
  const { r, step } = scn, steps = r.timeline_steps, n = steps.length, last = n + 1;
  show("mcpForm"); formBack = scn.back; formHelp = hv("scenarios"); $("title").textContent = r.title; setSub(`<span>примерить на себя · ${step === 0 ? "кто вы" : step <= n ? `шаг ${step} из ${n}` : "ваша польза"}</span>`);
  const bar = `<div class="scn-steps">${Array.from({ length: last + 1 }, (_, i) => `<i class="${i <= step ? "on" : ""}"></i>`).join("")}</div>`;
  const nav = (prev, next, nextLabel = "Дальше") => `<div class="scn-nav">${prev ? `<button class="btn ghost" data-scn-go="${step - 1}">${ic("back")}Назад</button>` : ""}${next ? `<button class="btn" data-scn-go="${step + 1}">${esc(nextLabel)}${ic("chevron")}</button>` : ""}</div>`;
  let body = "";
  if (step === 0) {
    body = `<div class="hero"><span class="mono">${ic("eye")}</span><h2 class="serif">${esc(r.title)}</h2><p>${esc(r.short)}</p></div>
      <div class="panel"><div class="section" style="margin-top:0">Кто вы и что болит</div><p style="margin:0">${esc(r.who)}</p></div>
      <div class="section">Модули</div><div class="panel"><div class="conn">${r.modules.map((m) => `<span class="chip accent">${ic("puzzle", "s16")}${esc(m.title)}</span>`).join("")}</div>
        <p class="note" style="margin:8px 0 0">Дальше — день с агентом: ${n} шагов. Нажимайте кнопки — покажем, что произошло бы. Имена, адреса и цифры — пример.</p></div>
      ${nav(false, true, "Начать день")}`;
  } else if (step <= n) {
    const st = steps[step - 1], j = scn.picked[step], d = j == null ? null : st.decisions[j];
    body = `<div class="panel">
      <div class="scn-when"><span class="t">${esc(st.at)}</span>${st.day ? `<span class="chip">${esc(st.day)}</span>` : ""}${st.module_title ? `<span class="chip accent">${ic("puzzle", "s16")}${esc(st.module_title)}</span>` : ""}<span class="chip s-approval">пример</span></div>
      <div class="scn-msg">${esc(st.text)}</div>
      ${st.decisions.length ? `<div class="scn-opts">${st.decisions.map((x, i) => `<button class="scn-opt ${i === j ? "on" : ""}" data-scn-opt="${i}">${esc(x.label)}</button>`).join("")}</div>` : ""}
      ${d ? `<div class="scn-res">${ic("chevron")}<span><b>Что произошло бы:</b> ${esc(d.outcome_toast)} <span class="chip s-approval">ничего не выполнено</span></span></div>` : ""}</div>
      ${nav(true, true, step === n ? "Итог: ваша польза" : "Дальше")}`;
  } else {
    const can = meta?.role !== "viewer", c = r.calculator;
    const field = (x) => { const v = scn.vals[x.id] ?? x.default, id = esc(x.id);   // ползунок пальцем + число рядом, пересчёт сразу
      return `<div class="field scn-field"><label for="scnR_${id}">${esc(x.title)}</label>
      <div class="scn-slide"><input id="scnR_${id}" data-scn-range="${id}" type="range" min="${x.min}" max="${x.max}" step="${x.step}" value="${esc(v)}" aria-describedby="scnH_${id}">
        <input data-scn-in="${id}" type="number" inputmode="decimal" min="${x.min}" max="${x.max}" step="${x.step}" value="${esc(v)}" aria-label="${esc(x.title)}"><span class="u">${esc(x.unit)}</span></div>
      <div class="hint" id="scnH_${id}">${esc(x.about)}</div></div>`; };
    body = `<div class="section" style="margin-top:0">Без агента</div><div class="panel"><p style="margin:0">${esc(r.without)}</p></div>
      <div class="section">Ваша польза — оценка</div><div class="panel">
        <div class="scn-gain" id="scnGain"></div>
        <p class="note" style="margin:10px 0 0">${esc(c.assumptions_disclaimer)}</p>
        <div class="section" style="margin:12px 0 6px">Ваши цифры</div><div class="scn-in">${c.inputs.filter((x) => !x.assumption).map(field).join("")}</div>
        <div class="section" style="margin:4px 0 6px">Допущения — поправьте</div><div class="scn-in">${c.inputs.filter((x) => x.assumption).map(field).join("")}</div></div>
      <div class="section">Что нужно от вас</div><div class="panel"><ul class="scn-list">${r.needs.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
      <div class="section">Первый шаг</div><div class="panel"><p style="margin:0">${esc(r.first_step)}</p></div>
      ${can ? (scn.connect ? `<div class="section">Подключить</div><div class="panel"><p class="note" style="margin:0 0 8px">Пространство создаётся из одного модуля — начните с первого, остальные добавите так же. Данные клиента (выгрузки, доступы) — после создания, по списку выше.</p>
        ${r.modules.map((m) => `<div class="mrow">${ic("puzzle")}<div class="ctext"><b>${esc(m.title)}</b><button class="btn ghost sm" data-scn-mod="${esc(m.id)}">${ic("plus")}Создать пространство</button></div></div>`).join("")}</div>`
        : `<button class="btn" data-scn-connect>${ic("check")}Подключить</button>`)
        : '<p class="viewonly">У вас доступ только на просмотр — подключить может владелец пульта или участник.</p>'}
      ${nav(true, false)}<div class="scn-nav"><button class="btn quiet" data-scn-all>Другие роли</button></div>`;
  }
  $("mcpForm").innerHTML = `<div class="mod">${bar}${body}</div>`;
  if (step > n) scnGain();
}
function scnGain() {                                 // результат и рядом — допущения, из которых он посчитан
  const res = benefitCalc(scn.r, scn.vals), byId = Object.fromEntries(scn.r.calculator.inputs.map((x) => [x.id, x]));
  const fmtv = (v) => String(v).replace(".", ",");
  $("scnGain").innerHTML = res.lines.map((x, i) => {
    const f = scn.r.calculator.formulas[i], used = f.of.filter((k) => byId[k].assumption).map((k) => `${byId[k].title.toLowerCase()} — ${fmtv(res.inputs[k])} ${byId[k].unit}`);
    return `<div class="scn-line"><div>${esc(x.title)}${x.caption ? ` <span class="chip s-approval">${esc(x.caption)}</span>` : ""}</div><div class="v">${esc(x.text)}</div>
      ${used.length ? `<small>Допущение: ${esc(used.join("; "))}</small>` : ""}<small>${esc(x.about)}</small></div>`;
  }).join("");
}
$("mcpForm").addEventListener("click", (e) => {
  const c = e.target.closest("[data-scn]"); if (c) return scenariosView(c.dataset.scn, formBack);
  const i = e.target.closest("[data-scn-ind]"); if (i) { const r = scnData?.scenarios.find((x) => x.industries.includes(i.dataset.scnInd)); return r && scnOpen(r, 0, modulesView); }
  const a = e.target.closest("[data-scn-entry]"); if (a) return scenariosView(null, modulesView);
  if (!scn) return;
  const g = e.target.closest("[data-scn-go]"); if (g) { scn.step = Math.max(0, Math.min(scn.r.timeline_steps.length + 1, +g.dataset.scnGo)); return scnRender(); }
  const o = e.target.closest("[data-scn-opt]"); if (o) {
    scn.picked[scn.step] = +o.dataset.scnOpt; haptic("selectionChanged");
    toast(scn.r.timeline_steps[scn.step - 1].decisions[+o.dataset.scnOpt].outcome_toast, 5000); return scnRender();
  }
  if (e.target.closest("[data-scn-connect]")) { scn.connect = true; scnRender(); return $("mcpForm").querySelector("[data-scn-mod]")?.scrollIntoView({ behavior: "smooth", block: "center" }); }
  if (e.target.closest("[data-scn-all]")) return scenariosView(null, scn.list);
  const m = e.target.closest("[data-scn-mod]"); if (m) return scnModule(m.dataset.scnMod);
});
$("mcpForm").addEventListener("input", (e) => {
  const x = e.target.closest("[data-scn-in], [data-scn-range]"); if (!x || !scn) return;
  const id = x.dataset.scnIn || x.dataset.scnRange, d = scn.r.calculator.inputs.find((y) => y.id === id), v = Number(String(x.value).replace(",", "."));
  const ok = x.value.trim() !== "" && Number.isFinite(v) && v >= d.min && v <= d.max, box = x.closest(".scn-field");
  if (x.dataset.scnRange) box.querySelector("[data-scn-in]").value = x.value;           // ползунок → число
  else if (ok) box.querySelector("[data-scn-range]").value = x.value;                    // число → ползунок
  box.querySelector("[data-scn-in]").classList.toggle("bad", !ok);
  box.querySelector(".hint").textContent = ok ? d.about : `Число от ${String(d.min).replace(".", ",")} до ${String(d.max).replace(".", ",")} — считаю по ближайшей границе.`;
  scn.vals[d.id] = x.value; scnGain();
});
async function scnModule(id) {                       // «Создать пространство» — экран модуля из «Из модуля» (имя папки → «Создать»)
  const r = scn, back = () => { scn = r; scnRender(); };
  try { if (!modData) modData = await api("/api/modules"); } catch (e) { return toast("Не загрузил модули: " + e.message, 4000); }
  const m = modData.modules.find((x) => x.id === id);
  if (!m) return toast(DEMO ? "Демо: в панели здесь откроется экран модуля — имя папки и «Создать»" : "Этого модуля нет в каталоге — обновите список модулей", 4000);
  moduleView(m); formBack = back;
}
function scnEntry() {                                // ненавязчивый вход под списком сессий
  return `<button class="scn-entry" data-scn-home data-tour="try">${ic("eye")}<span class="ctext"><b>Примерить на себя</b> — день с агентом в вашей роли и польза в цифрах</span>${ic("chevron")}</button>`;
}
