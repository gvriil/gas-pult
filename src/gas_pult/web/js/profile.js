// Форма поставщика моделей (ключ, адрес шлюза, модели, вход в OpenRouter, каталог моделей) — часть по требованию:
// ядро держит только вызов (бюджет ядра index.html, test_ui_parts).
let orLink = null, orTimer = null;
export function profileForm(p, connected) {
  show("mcpForm"); formHelp = hv("form.provider"); helpModule = ""; $("title").textContent = p.title; setSub("<span>модели поставщика</span>");
  clearInterval(orTimer);
  $("mcpForm").innerHTML = `<div class="panel">
    <div class="hero">${mono(p.title, p.id)}<h2 class="serif">${esc(p.title)}</h2><p>${esc(p.about)}</p></div>
    ${connected ? `<div class="result ok">${ic("check")}<span>${esc(p.title)} подключён — ключ сохранён на сервере.</span></div>
      <button class="btn" id="profStart0">${ic("newsess")}Новый чат с ${esc(p.title)}</button>` : ""}
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
        <button class="btn" id="profStart">${ic("newsess")}Новый чат с ${esc(p.title)}</button>`;
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
export function openCatalog(input) {
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
