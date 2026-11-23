// «Подключения»: каталог по разделам, поиск и экран согласия (владелец 23.11: «пусть пользователь сам решает»).
// Часть по требованию (#191). Окно открывается сразу: каталог — из кэша браузера (последний ответ /api/mcp), статусы
// подключений догружаются вторым запросом — до тех пор у плитки «проверяю…». Поиск — по названию и назначению, на
// клиенте, без задержки. Согласие — перед каждым подключением: без галочки «Подключить» неактивна; сервер тоже
// проверяет (409 code=consent, consents.py). Логотипы — только официальные знаки (js/logos.js) или нейтральная буква.

const css = typeof document === "undefined" ? null : document.createElement("style");   // node (тесты) — без стилей
const CSS = `
.cn-search { position: sticky; top: 0; z-index: 2; background: var(--bg-app); padding: 4px 0 8px; }
.cn-search .inp { display: flex; align-items: center; gap: 8px; }
.cn-search input { flex: 1; min-width: 0; }
.cn-cat { margin-top: 4px; }
.cn-cat[hidden], .tile[hidden], .cn-conn .chip[hidden] { display: none !important; }
.tile .cn-st { align-self: flex-start; margin-top: auto; }
.tile.cn-err { border-color: color-mix(in srgb, var(--status-danger) 45%, var(--border-subtle)); }
.tile.cn-off { background: var(--bg-subtle); box-shadow: none; }
.tile.cn-off .mono { opacity: .7; }
.cn-empty { text-align: center; padding: 18px 8px; color: var(--text-secondary); }
.cn-empty .btn { width: auto; margin-top: 10px; }
.tile.skel { min-height: 112px; }
.tile.skel i { width: 36px; height: 36px; border-radius: 10px; } .tile.skel i + i { width: 70%; height: 12px; } .tile.skel i + i + i { width: 50%; }
.cn-consent .cn-what { margin: 0 0 10px; }
.cn-consent ul { margin: 8px 0 12px; padding-left: 20px; }
.cn-consent ul li { margin: 0 0 6px; }
.cn-consent .cn-mine { font-weight: 600; }
.cn-check { display: flex; gap: 10px; align-items: flex-start; min-height: 44px; padding: 10px 12px; border: 1px solid var(--border-subtle); border-radius: var(--radius-md); margin: 10px 0; cursor: pointer; }
.cn-check input { width: 20px; height: 20px; margin: 1px 0 0; flex: none; accent-color: var(--accent-primary); }
.cn-ver { color: var(--text-muted); font-size: calc(12px * var(--fz, 1)); margin-top: 8px; }
`;
if (css) { css.textContent = CSS; document.head.append(css); }

// ---------- кэш каталога: окно «Подключения» — сразу, без ожидания `claude mcp list` ----------
const KEY = () => "gp.conn.catalog.v1:" + (meta?.role || "") + ":" + (meta?.uid ?? "") + (FOCUS ? ":focus" : "");
export function cached() {
  try { const d = JSON.parse(localStorage.getItem(KEY()) || "null"); return d && Array.isArray(d.presets) ? { ...d, servers: null } : null; }
  catch (e) { return null; }
}
export function remember(d) {
  try {
    const { presets, connectors, connectors_url, personal, cats, cards, focus } = d;
    localStorage.setItem(KEY(), JSON.stringify({ presets, connectors, connectors_url, personal, cats, cards, focus }));
  } catch (e) { /* приватное окно — без кэша */ }
}

// ---------- каталог ----------
const CATS = [["ai", "ИИ-модели и агенты"], ["messengers", "Мессенджеры"], ["mail", "Почта"], ["docs", "Документы и диски"],
  ["research", "Исследования"], ["other", "Прочее"]];
const low = (s) => String(s || "").toLowerCase().replace(/ё/g, "е");
// Поиск без задержки: все слова запроса — в названии, назначении (описании), id или названии раздела.
export const hay = (x, catTitle = "") => low([x.title, x.about, x.id, catTitle].join(" "));
export const words = (q) => low(q).trim().split(/\s+/).filter(Boolean);
export const hit = (ws, s) => ws.every((w) => s.includes(w));
export const pick = (list, q, catTitle = () => "") => { const ws = words(q); return list.filter((x) => hit(ws, hay(x, catTitle(x.cat)))); };
const pname = (s) => s.name.replace(/^claude\.ai /, "").replace(/^plugin:[^:]+:/, "");
const chip = (st) => ({
  on: `<small class="chip ok cn-st">${ic("check", "s16")}подключено</small>`,
  err: '<small class="chip bad cn-st">ошибка</small>',
  off: '<small class="chip cn-st">не подключено</small>',
  wait: '<small class="chip cn-st">проверяю…</small>',
  info: '<small class="chip cn-st">официальный путь</small>',
  no: '<small class="chip bad cn-st">не поддерживается</small>',
}[st]);

function items(d) {
  const srv = d.servers, out = [];
  const presetSt = (p) => !srv ? "wait" : (() => { const s = srv.find((x) => x.name === p.id); return !s ? "off" : s.ok ? "on" : "err"; })();
  const connSt = (c) => {
    if (!srv) return "wait";
    const s = srv.filter((x) => x.name.startsWith("claude.ai ") && low(x.name).includes(low(c.match)));
    return s.some((x) => x.ok) ? "on" : s.length ? "err" : "off";
  };
  if (meta?.role === "owner" && !FOCUS) for (const p of (meta?.profiles || []).filter((x) => x.needs_key)) {
    const no = p.allowed === false;                    // недоступен в стране по условиям поставщика
    out.push({ cat: "ai", attr: `data-prof="${esc(p.id)}"`, id: p.id, title: p.title, about: no ? p.denied || DENY : p.about || "", st: no ? "no" : p.key ? (p.not_ready ? "err" : "on") : "off" });
  }
  d.presets.forEach((p, i) => { if (p.id !== "stdio" && p.id !== "http") out.push({ cat: p.cat || "other", attr: `data-p="${i}"`, id: p.id, title: p.title, about: p.about, st: presetSt(p) }); });
  d.connectors.forEach((c, i) => out.push({ cat: c.cat || "other", attr: `data-c="${i}"`, id: c.id, title: c.title, about: c.about, st: connSt(c), claude: true }));
  const msgSection = meta?.role === "owner" && !FOCUS;   // у владельца Telegram, WhatsApp и MAX — в «Мессенджерах» (js/messengers.js)
  for (const c of d.cards || []) if (!(msgSection && ["telegram", "whatsapp", "max"].includes(c.id))) out.push({ cat: c.cat || "other", attr: `data-card="${esc(c.id)}"`, id: c.id, title: c.title, about: c.about, st: c.state === "off" ? "no" : "info" });
  return out;
}
const short = (s) => String(s || "").split(":")[0].split(" — ")[0];
function tile(x) {
  const cls = x.st === "on" ? "on" : x.st === "err" ? "cn-err" : x.st === "no" ? "cn-off" : "";
  return `<button class="tile ${cls}" ${x.attr} data-s="${esc(hay(x))}">${mono(x.title, x.id)}<span>${esc(x.title)}</span>
    <small>${esc(short(x.about))}</small>${x.claude && dev() ? `<small class="chip space">${esc(T("int.claude.chip"))}</small>` : ""}${chip(x.st)}</button>`;
}
export function skeleton() {
  const sk = '<div class="tile skel"><i></i><i></i><i></i></div>';
  return `<div class="cn-search"><div class="inp"><input type="search" placeholder="Найти сервис" disabled aria-label="Найти сервис"></div></div>
    <div class="section">Подключено</div><div class="card skel"><i class="sk-name"></i><i class="sk-meta"></i></div>
    <div class="section">${CATS[0][1]}</div><div class="tiles">${sk.repeat(4)}</div>`;
}

export function render(box, d, keep) {
  const q = keep ? box.querySelector("#connQ")?.value || "" : "";
  const srv = d.servers || [], ok = srv.filter((s) => s.ok), bad = srv.filter((s) => !s.ok && s.removable);
  const all = items(d), cats = (d.cats?.length ? d.cats.map((c) => [c.id, c.title]) : CATS);
  const note = d.focus ? (d.space ? "Здесь — подключения вашего пространства. Ресурсы владельца пульта по этой ссылке не видны."
      : "По этой ссылке видны только ваши подключения. Своё пространство с подключениями выдаёт владелец пульта.")
    : d.personal ? "Подключения у каждого свои: здесь — ваши, они работают в сессиях, которые открыли вы. Аккаунт и правила сервиса — на вас."
    : "Подключения у каждого человека пульта свои — здесь ваши. Аккаунт и правила сервиса — на вас.";
  const connected = !d.servers ? '<p class="note">Проверяю, что подключено…</p>'
    : ok.length ? `<div class="conn cn-conn">${ok.map((s) => `<span class="chip ok" data-s="${esc(low(s.name))}">${LOGOS?.byName(s.name) || ic("check", "s16")}${esc(pname(s))}</span>`).join("")}</div>`
    : '<p class="note">Пока ничего. Выберите сервис ниже.</p>';
  box.innerHTML = `<div class="cn-search"><div class="inp">${ic("search")}<input id="connQ" type="search" placeholder="Найти сервис: название или для чего" aria-label="Найти сервис" autocomplete="off" value="${esc(q)}"></div></div>
    <p class="note">${note}</p>
    <div class="section">Подключено</div>
    ${connected}
    ${bad.map((s) => `<div class="card cn-bad" data-s="${esc(low(s.name))}" style="margin-top:8px;cursor:default"><div class="row">${LOGOS?.byName(s.name) || ""}<span class="name" style="flex:1">${esc(pname(s))}</span><span class="chip bad">${/auth/i.test(s.state) ? "нужен вход" : "ошибка"}</span>
      <button class="btn danger sm rm-inline" data-rm="${srv.indexOf(s)}">Отключить</button></div></div>`).join("")}
    ${cats.map(([id, title]) => {
      const mine = all.filter((x) => x.cat === id);
      const extra = id === "messengers" ? '<div id="msgKeys" class="cn-sub"></div>' : id === "other" ? '<div id="calKeys" class="cn-sub"></div>' : "";
      const more = id === "other" && !d.focus ? `<button class="tile" data-more="1" data-s="другой сервис каталог вручную адрес программа mcp"><span class="mono">${ic("plus")}</span><span>Другой сервис</span><small>каталог claude.ai или вручную</small></button>` : "";
      if (!mine.length && !extra && !more) return "";
      const models = id === "ai" && meta?.role === "owner" && !FOCUS;   // ключи моделей — здесь (бывший блок «Модели»)
      return `<section class="cn-cat" data-cat="${esc(id)}" data-t="${esc(low(title))}"${models ? ' id="modelsBox" data-tour="models"' : ""}><div class="section">${esc(title)}</div>
        ${models ? '<p class="note">Кроме Claude сессия может работать на моделях других поставщиков — по их ключу. Поставщик выбирается при «Новой сессии».</p>' : ""}
        ${mine.length || more ? `<div class="tiles">${mine.map(tile).join("")}${more}</div>` : ""}${extra}</section>`;
    }).join("")}
    <div class="cn-empty" id="connNone" hidden>Ничего не нашлось<br><button class="btn ghost sm" id="connReset">${ic("x")}Сбросить поиск</button></div>
    ${d.focus ? "" : `<button class="btn ghost" id="mcpRefresh" style="margin-top:12px">${ic("refresh")}Обновить список</button>`}`;
  const inp = box.querySelector("#connQ");
  inp.oninput = () => filter(box);
  box.querySelector("#connReset").onclick = () => { inp.value = ""; filter(box); inp.focus(); };
  if (q) filter(box);
}

// Поиск: по названию, назначению и разделу; подразделы (мессенджеры, календари) — по их тексту.
export function filter(box) {
  const ws = words(box.querySelector("#connQ")?.value || ""), ok = (s) => hit(ws, s);
  let any = false;
  box.querySelectorAll(".cn-cat").forEach((sec) => {
    const inCat = ws.length && ok(sec.dataset.t);
    let n = 0;
    sec.querySelectorAll(".tile[data-s]").forEach((t) => { const on = !ws.length || inCat || ok(t.dataset.s); t.hidden = !on; n += on; });
    sec.querySelectorAll(".cn-sub").forEach((x) => { const on = !ws.length || inCat || ok(low(x.textContent)); x.hidden = !on; n += on && !!x.textContent.trim(); });
    sec.hidden = ws.length > 0 && !n; any ||= n > 0;
  });
  box.querySelectorAll(".cn-conn .chip[data-s], .cn-bad").forEach((c) => { c.hidden = ws.length > 0 && !ok(c.dataset.s); });
  box.querySelector("#connNone").hidden = !ws.length || any;
}

// Карточка без кнопки «Подключить»: официальный путь или «не поддерживается» — и почему.
export function card(d, id) {
  const c = (d.cards || []).find((x) => x.id === id); if (!c) return;
  sSheet("int.card", c.title, `<div class="hero">${mono(c.title, c.id)}<h2 class="serif">${esc(c.title)}</h2></div>
    <div class="result ${c.state === "off" ? "bad" : "wait"}">${ic(c.state === "off" ? "warn" : "info")}<span>${esc(c.about)}</span></div>
    <p class="note">Пульт подключает сервисы только официальными способами — по правилам самого сервиса.</p>`);
}

// ---------- согласие перед подключением ----------
let C = null;
export function reset() { C = null; }
export async function given(what) { try { C ||= await api("/api/consent"); return C.given.includes(what); } catch (e) { return false; } }
export async function ask(it) {
  try { C ||= await api("/api/consent"); } catch (e) { toast(e.message, 4500); return false; }
  if (C.given.includes(it.what)) return true;
  return new Promise((res) => {
    let done = false;
    const html = `<div class="cn-consent">${it.id ? `<div class="hero">${mono(it.title, it.id)}<h2 class="serif">${esc(it.title)}</h2></div>` : ""}
      <p class="cn-what"><b>Что подключается:</b> ${esc(it.title)}${it.kind ? " — " + esc(it.kind) : ""}.</p>
      <p class="cn-what"><b>Что сможет агент:</b> ${esc(it.can || it.about || "читать и делать в сервисе то, что разрешает подключение")}.</p>
      <ul class="note">${C.points.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>
      <p class="cn-mine">Аккаунт и соблюдение правил сервиса — на вас.</p>
      <label class="cn-check"><input type="checkbox" data-agree><span>${esc(C.check)}</span></label>
      <button class="btn wide" type="button" data-ok disabled>${ic("check")}Подключить</button>
      <div class="cn-ver">Версия текста ${esc(C.v)} — дата и версия сохранятся на сервере пульта.</div></div>`;
    const bg = sSheet("int.consent", "Подключение: " + it.title, html, async (b) => {
      if (!b.hasAttribute("data-ok")) return;
      b.disabled = true;
      try {
        await api("/api/consent", { what: it.what, title: it.title, accepted: true });
        C.given.push(it.what); done = true; bg.remove(); res(true);
      } catch (e) { toast(e.message, 4500); b.disabled = false; }
    }, "Отмена");
    const box = bg.querySelector("[data-agree]"), ok = bg.querySelector("[data-ok]");
    box.onchange = () => { ok.disabled = !box.checked; };
    new MutationObserver((_, o) => { if (!bg.isConnected) { o.disconnect(); if (!done) res(false); } }).observe(document.body, { childList: true });
  });
}
