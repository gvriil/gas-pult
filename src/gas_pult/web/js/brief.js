// Утренний брифинг первого лица (GAS-18) — часть интерфейса по требованию (#191): ядро держит кнопку «Брифинг»,
// пункт в «⋯» и в «Настройках»; этот код грузится при первом нажатии.
// Владелец 18.11: один экран телефона, у каждой строки — источник-ссылка. Первый вход — выбор источников и времени
// («что хотят подключить — всегда должна быть такая возможность»), потом — короткий тур (как в админке и сканере TGI).
// Владелец 21.11: «понятно с первого взгляда» (ориентиры — Things 3 «Today», Linear Inbox, «Напоминания»): сверху
// итог одной строкой, затем группы «Ждут вашего Да» → «Сегодня» → «Сделано» (свёрнуто) и «Не выполнено»;
// пустая группа не показывается, кроме «Ждут вашего Да»; длинное — «…», раскрывается нажатием.

const KIND_IC = { mail: "mail", calendar: "cal", github: "code", linear: "tasks", pult: "home", handoff: "book" };
const DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const EVERY_T = { workdays: "Рабочие дни", daily: "Каждый день", custom: "Выбрать дни" };
const BLOCKS = [["done", "Сделано", "check"], ["failed", "Не выполнено", "warn"]];   // идут после «Ждут вашего Да» и «Сегодня»
const TIME = /^((?:\d{1,2}:\d{2}(?:–\d{1,2}:\d{2})?)|весь день) · /;   // «10:00–10:30 · Планёрка» → время слева
let D = null;                                         // ответ /api/brief: {brief, sel, schedule, avail, tour}

const css = document.createElement("style");
css.textContent = `
body:has(.brief-bg) .notices { z-index: 61; }   /* сообщения («Сохранено») — поверх брифинга (Gemini 20.11) */
.brief-bg { position: fixed; inset: 0; z-index: 60; background: var(--bg-canvas); overflow-y: auto; overscroll-behavior: contain; }
.brief { max-width: 780px; margin: 0 auto; padding: 8px 16px calc(32px + env(safe-area-inset-bottom)); color: var(--text-primary); }   /* как абзацы ленты */
.brief .bh { display: flex; align-items: center; gap: 6px; }
.brief .bh h2 { flex: 1; margin: 0; font-size: 20px; }
.brief .bh small { color: var(--text-muted); font-weight: 400; font-size: 13px; margin-left: 6px; }
.brief .bl { margin: 10px 0 6px; font-size: 18px; font-weight: 600; line-height: 1.35; }   /* итог — крупно, без плашки */
.brief .bl small { display: block; margin-top: 2px; font-size: 13px; font-weight: 400; color: var(--text-muted); }
.brief .grp { margin-top: 22px; }
.brief h3 { display: flex; align-items: center; gap: 8px; margin: 0 0 6px; font-size: 15px; font-weight: 600; line-height: 22px; color: var(--text-primary); }
.brief h3 .i { width: 18px; height: 18px; color: var(--text-secondary); }
.brief h3 .n { font-weight: 400; color: var(--text-muted); }
.brief .grp.warn h3, .brief .grp.warn h3 .i { color: var(--status-approval); }
.brief ul { list-style: none; margin: 0; padding: 0; }
.brief li { display: flex; align-items: center; gap: 10px; min-height: 44px; padding: 4px 0; border-bottom: 1px solid var(--border-subtle); font-size: 15px; line-height: 22px; }
.brief li:last-child { border-bottom: 0; }
.brief .tm { flex: none; width: 52px; font-variant-numeric: tabular-nums; font-weight: 600; }
.brief .tm small { display: block; font-size: 13px; font-weight: 400; line-height: 16px; color: var(--text-muted); }
.brief .tx { flex: 1; min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; cursor: pointer; }
.brief .tx.open { white-space: normal; }
.brief .why { color: var(--status-approval); }
.brief .src { flex: none; display: inline-flex; align-items: center; gap: 4px; max-width: 40%; font-size: 13px; color: var(--text-muted); text-decoration: none; }
.brief .src .lb { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.brief .src .i { width: 14px; height: 14px; flex: none; }
.brief a.src:hover { color: var(--accent-primary); }
.brief .tochat { flex: none; display: grid; place-items: center; width: 36px; height: 36px; border: 0; border-radius: var(--radius-sm); background: none; color: var(--text-muted); cursor: pointer; }
.brief .tochat:hover { color: var(--accent-primary); background: var(--bg-subtle); }
.brief .dec { border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 12px 14px 10px; margin-top: 8px; background: var(--bg-surface); }
.brief .dec.hot { border-color: color-mix(in srgb, var(--status-approval) 45%, var(--border-subtle)); }   /* Gemini №14: без грязной заливки */
.brief .dt { font-size: 15px; line-height: 22px; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; cursor: pointer; }
.brief .dec.open .dt { display: block; } .brief .dec.open .yes { white-space: normal; }
.brief .tag { display: inline-block; margin-right: 6px; padding: 0 6px; border-radius: 6px; font-size: 12px; line-height: 20px; font-weight: 600; vertical-align: 1px;
  color: var(--status-approval); background: var(--status-approval-bg); }
.brief .meta { display: flex; align-items: center; gap: 4px; margin-top: 4px; font-size: 13px; color: var(--text-muted); min-width: 0; }
.brief .meta .src { max-width: none; }
.brief .meta .yes { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.brief .acts { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }
.brief .acts .btn { flex: none; width: auto; min-height: 36px; padding: 6px 14px; }
.brief .dec .acts .btn.quiet { background: transparent; color: var(--text-secondary); font-weight: 500; }   /* «Нет / Позже / В чат» — тихие */
.brief .dec .acts .btn.quiet:hover { background: var(--bg-subtle); color: var(--text-primary); }
.brief .dec .acts [data-a=yes] { min-width: 72px; }
.brief .calm { display: flex; align-items: center; gap: 8px; min-height: 44px; color: var(--text-secondary); font-size: 15px; }
.brief .calm .i { width: 18px; height: 18px; color: var(--status-success); }
.brief details.fold > summary { list-style: none; cursor: pointer; }
.brief details.fold > summary::-webkit-details-marker { display: none; }
.brief details.fold > summary h3 { min-height: 44px; margin: 0; }
.brief details.fold > summary .chev { margin-left: auto; transition: transform .15s; }
.brief details.fold[open] > summary .chev { transform: rotate(180deg); }
.brief .more { font-size: 13px; color: var(--text-muted); margin-top: 6px; }
.brief .off { margin-top: 24px; font-size: 13px; color: var(--text-muted); overflow: hidden; white-space: nowrap; text-overflow: ellipsis; cursor: pointer; }
.brief .off.open { white-space: normal; }
@media (max-width: 600px) {                          /* телефон: цели нажатия 44 px, источник — значком */
  .brief .acts .btn { min-height: 44px; }
  .brief .tochat { width: 44px; height: 44px; margin-right: -8px; }
  .brief li .src .lb { display: none; }
  .brief li .src { min-width: 28px; min-height: 44px; justify-content: center; }
}
.brief.bpick label { display: flex; align-items: center; gap: 10px; padding: 9px 0; border-bottom: 1px solid var(--border-subtle); font-size: 15px; }
.brief.bpick label small { display: block; color: var(--text-muted); font-size: 12px; }
.brief.bpick label.dis { color: var(--text-muted); }
.brief.bpick input[type=checkbox] { width: 20px; height: 20px; accent-color: var(--accent-primary); }
.brief.bpick .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 8px 0; }
.brief.bpick input[type=time] { font: inherit; padding: 8px 10px; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle); background: var(--bg-surface); color: var(--text-primary); }
.brief .seg button { flex: 1; }
.brief .days button { min-width: 40px; }
.brief .empty { color: var(--text-muted); font-size: 14px; padding: 6px 0; }
`;
document.head.append(css);

const srcHtml = (s) => {
  const inner = ic(KIND_IC[s.kind] || "ext") + `<span class="lb">${esc(s.label)}</span>`, t = ` title="${esc(s.label)}"`;
  return s.url ? `<a class="src" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer"${t} aria-label="Источник: ${esc(s.label)}">${inner}</a>` : `<span class="src"${t}>${inner}</span>`;
};
// Строки разработки (PR GitHub, HANDOFF.md) — разработчику (Gemini №14 [У]); у остальных — письма, встречи, задачи
const devOnly = (r) => !dev() && ["github", "handoff"].includes(r.source?.kind);
// Каждый пункт — «В чат»: новый чат, пункт и источник уже в поле ввода (владелец 21.11: «сразу вход в чат»)
let ROWS = [];
// строка группы — одна строка: [время] текст (длинное — «…», нажатие раскрывает) · источник · «В чат»
const rowHtml = (r, timed) => {
  const m = timed && String(r.text).match(TIME), [a, z] = m ? m[1].split("–") : [];
  const tx = m ? r.text.slice(m[0].length) : r.text;
  return `<li>${m ? `<span class="tm">${esc(a)}${z ? `<small>${esc(z)}</small>` : ""}</span>` : ""}<span class="tx" data-more>${esc(tx)}${r.why ? `<span class="why"> · ${esc(r.why)}</span>` : ""}</span>${srcHtml(r.source)}<button class="tochat" data-chat="${ROWS.push(r) - 1}" title="Продолжить в чате" aria-label="Продолжить в чате">${ic("chat", "s16")}</button></li>`;
};
// решение — карточка: метка категории («[деньги] …») — плашкой, текст ≤ 2 строк, источник и что сделает «Да» — мелко
const decHtml = (r, n) => {
  const m = String(r.text).match(/^\[([^\]]{1,20})\]\s*/), tx = m ? r.text.slice(m[0].length) : r.text;
  return `<div class="dec${r.cat ? " hot" : ""}" data-n="${n}" data-more><div class="dt">${m ? `<span class="tag">${esc(m[1])}</span>` : ""}${esc(tx)}</div>
    <div class="meta">${srcHtml(r.source)}${r.yes ? `<span class="yes" title="${esc(r.yes)}">· Да — ${esc(r.yes)}</span>` : ""}</div>
    <div class="acts">${r.act ? `<button class="btn sm" data-a="yes">Да</button>` : ""}<button class="btn quiet sm" data-a="no">Нет</button><button class="btn quiet sm" data-a="later">Позже</button><button class="btn quiet sm" data-a="chat">В чат</button></div></div>`;
};
const count = (b, k) => (b[k]?.length || 0) + (b.more?.[k] || 0);
const moreHtml = (b, k) => (b.more?.[k] ? `<div class="more">…и ещё ${b.more[k]}</div>` : "");
const chatText = (r) => [r.text, "Источник: " + (r.source?.label || "") + (r.source?.url ? " " + r.source.url : ""), r.why].filter(Boolean).join("\n") + "\n";

function frame() {
  document.querySelector(".brief-bg")?.remove();
  const bg = document.createElement("div"); bg.className = "brief-bg"; bg.setAttribute("role", "dialog"); bg.setAttribute("aria-label", "Сегодня");
  bg.addEventListener("keydown", (e) => { if (e.key === "Escape" && !document.querySelector(".driver-popover")) close(); });
  document.body.append(bg);
  return bg;
}
function close() { document.querySelector(".brief-bg")?.remove(); }
const head = (title, sub, btns = "") => `<div class="bh"><h2>${esc(title)}${sub ? `<small>${esc(sub)}</small>` : ""}</h2>${btns}
  <button class="icon" data-bx aria-label="Закрыть «Сегодня»">${ic("x")}</button></div>`;

// «Сегодня» открывается сразу (владелец 21.11: «без ожидания — заранее загружен, потом обновляется»): панель
// заранее забирает брифинг (prefetch, ядро — через несколько секунд после загрузки); открыли — показываем готовый
// и тихо спрашиваем свежий: сервер отдаёт готовый сразу, а свежий собирает в фоне (webapp.brief_get).
let ready = null;                                     // идущий запрос prefetch
export function prefetch() {
  if (D || ready) return ready;
  return ready = api("/api/brief").then((d) => { D = d; }, () => {}).finally(() => { ready = null; });
}

export async function briefOpen(mode) {
  const bg = frame();
  if (ready && !D && mode !== "fresh") await ready;
  if (D?.sel?.chosen && D.brief && mode !== "fresh" && mode !== "prefs") {
    briefView(bg);
    return later(bg, 0);
  }
  bg.innerHTML = `<div class="brief">${head("Сегодня", "собираю…")}<div class="empty">Читаю почту, календарь и задачи — несколько секунд.</div></div>`;
  bg.querySelector("[data-bx]").onclick = close;
  try { D = await api("/api/brief" + (mode === "fresh" ? "?fresh=1" : "")); } catch (e) { close(); return toast("Сегодня: " + e.message, 4500); }
  if (mode === "prefs" || !D.sel?.chosen) return pickView(bg, !D.sel?.chosen);
  briefView(bg);
  if (D.stale) later(bg, 1);
}

// тихое обновление открытого экрана: перерисовываем, только если что-то изменилось и человек не в туре и не в
// настройке; сервер собирает свежий в фоне — второй вопрос через несколько секунд
function later(bg, n) {
  setTimeout(() => api("/api/brief").then((d) => {
    if (!bg.isConnected || !bg.querySelector(".bl")) return;
    const changed = JSON.stringify(d.brief) !== JSON.stringify(D.brief);
    D = d;
    if (changed && !document.querySelector(".driver-popover")) briefView(bg);
    if (d.stale && n < 3) later(bg, n + 1);
  }, () => {}), n ? 6000 : 300);
}

function briefView(bg) {
  const b = { ...D.brief }, at = (b.at || "").slice(11, 16); ROWS = [];
  for (const [k] of BLOCKS) if (b[k]) b[k] = b[k].filter((r) => !devOnly(r));
  b.decisions = (b.decisions || []).filter((r) => !devOnly(r)); if (b.today) b.today = b.today.filter((r) => !devOnly(r));
  const nd = b.decisions.length;                     // заголовок сервера считает и скрытые строки — число по видимым
  if (nd !== (D.brief.decisions || []).length) b.headline = String(b.headline || "").replace(/(\d+)\s+решени[а-я]*/, nd + " " + plural(nd, ["решение", "решения", "решений"]));
  const nt = count(b, "today"), ndone = count(b, "done"), nf = count(b, "failed");
  // итог: первое предложение — крупно, остальное — мелко; «Решений от вас не ждут» уже сказано в группе — не повторяем
  let [h1, ...h2] = String(b.headline || "").split(/(?<=\.)\s+/);
  if (!nd && /^(Решений от вас не ждут|Ждут вас 0 )/.test(h1) && h2.length) h1 = h2.shift();
  const off = (b.sources || []).filter((s) => s.state === "error" || s.state === "none");
  bg.innerHTML = `<div class="brief">${head("Сегодня", at && "на " + at,
      `<button class="icon" data-btour aria-label="Тур по брифингу">${ic("help")}</button><button class="icon" data-bprefs aria-label="Источники и время" data-tour="brief-prefs">${ic("settings")}</button><button class="icon" data-bfresh aria-label="Обновить">${ic("refresh")}</button>`)}
    <div class="bl" data-tour="brief-head">${esc(h1)}${h2.length ? `<small>${esc(h2.join(" "))}</small>` : ""}</div>
    <section class="grp" data-group="decisions" data-tour="brief-decisions">${nd
      ? `<h3>${ic("help")}Ждут вашего Да <span class="n">${nd}</span></h3>${b.decisions.map(decHtml).join("")}`
      : `<div class="calm">${ic("check")}Решений от вас не ждут</div>`}</section>
    ${nt ? `<section class="grp" data-group="today" data-tour="brief-today"><h3>${ic("cal")}Сегодня <span class="n">${nt}</span></h3><ul>${b.today.map((r) => rowHtml(r, true)).join("")}</ul>${moreHtml(b, "today")}</section>` : ""}
    ${ndone ? `<section class="grp" data-group="done"><details class="fold" data-tour="brief-done"><summary><h3>${ic("check")}Сделано <span class="n">${ndone}</span>${ic("chev", "chev")}</h3></summary>
      <ul>${b.done.map((r) => rowHtml(r)).join("")}</ul>${moreHtml(b, "done")}</details></section>` : ""}
    ${nf ? `<section class="grp warn" data-group="failed" data-tour="brief-failed"><h3>${ic("warn")}Не выполнено <span class="n">${nf}</span></h3><ul>${b.failed.map((r) => rowHtml(r)).join("")}</ul>${moreHtml(b, "failed")}</section>` : ""}
    ${off.length ? `<div class="off" data-more>Не подключено: ${off.map((s) => esc(s.label + (s.note ? " — " + s.note : ""))).join("; ")}</div>` : ""}
  </div>`;
  bg.querySelector("[data-bx]").onclick = close;
  bg.querySelector("[data-bprefs]").onclick = () => pickView(bg, false);
  bg.querySelector("[data-bfresh]").onclick = () => briefOpen("fresh");
  bg.querySelector("[data-btour]").onclick = () => briefTour();
  bg.querySelectorAll(".dec [data-a]").forEach((x) => { x.onclick = () => (x.dataset.a === "chat" ? (close(), chatWith(chatText(b.decisions[+x.closest(".dec").dataset.n])))
    : act(bg, b.decisions[+x.closest(".dec").dataset.n], x.dataset.a)); });
  bg.querySelectorAll("[data-chat]").forEach((x) => { x.onclick = () => { close(); chatWith(chatText(ROWS[+x.dataset.chat])); }; });
  bg.querySelectorAll("[data-more]").forEach((x) => { x.onclick = (e) => { if (!e.target.closest("a, button")) x.classList.toggle("open"); }; });
  if (!D.tour) briefTour();                            // первый брифинг — тур сам, дальше — по «?»
}

async function act(bg, r, a, sure = false) {
  try {
    const out = await api("/api/brief/act", { key: r.key, act: a, confirm: sure });
    if (out.ask) return confirmDanger(out.ask, () => act(bg, r, a, true));      // «Да» с действием — только после подтверждения
    if (out.url) open(out.url, "_blank", "noopener");
    if (out.window) { close(); await openSession(out.window); }
    if (out.done) toast(out.done, 3000);
    D.brief.decisions = D.brief.decisions.filter((x) => x.key !== r.key);
    D.brief.headline = out.headline || D.brief.headline;
    if (document.body.contains(bg)) briefView(bg);
  } catch (e) { toast("Не вышло: " + e.message, 4500); }
}

// ---------- выбор источников и времени: первый вход и «Настройки» → «Брифинг» ----------
function pickView(bg, first) {
  const av = D.avail || {}, sel = D.sel || {}, sch = D.schedule || { time: "07:30", every: "workdays", days: [0, 1, 2, 3, 4] };
  const on = (s) => (sel.sources || []).includes(s), chk = (c) => (c ? " checked" : "");
  const box = (b) => `<label><input type="checkbox" data-box="${esc(b.id)}"${chk((sel.boxes || []).includes(b.id))}><span>${b.gmail ? "Gmail" : "Почта"} · ${esc(b.id)}</span></label>`;
  const cal = (c) => `<label><input type="checkbox" data-cal="${esc(c)}"${chk((sel.calendars || []).includes(c))}><span>Календарь · ${esc(c)}</span></label>`;
  const opt = (id, t, sub, ok) => `<label class="${ok ? "" : "dis"}"><input type="checkbox" data-src="${id}"${chk(ok && on(id))}${ok ? "" : " disabled"}><span>${t}<small>${sub}</small></span></label>`;
  let every = sch.every || "workdays", days = [...(sch.days || [0, 1, 2, 3, 4])];
  bg.innerHTML = `<div class="brief bpick">${head(first ? "Что показывать в «Сегодня»?" : "«Сегодня»: что, во сколько, откуда")}
    <p class="more">${first ? "Выберите, что подключить. Поменять можно всегда: «Настройки» → «Брифинг». " : ""}Письма и события читает код, а не модель; ничего не отправляется без вашего «Да».</p>
    <h3>${ic("mail")}Почта</h3>${(av.boxes || []).map(box).join("") || '<div class="empty">Ящик не подключён — «Подключения» → «Почта».</div>'}
    <h3>${ic("cal")}Календарь</h3>${(av.calendars || []).map(cal).join("") || '<div class="empty">Календарь не подключён — «Подключения» → «Календари»${(av.calkeys || []).length ? ": " + av.calkeys.filter((k) => !k.on).map((k) => esc(k.title)).join(", ") : ""}.</div>'}
    <h3>${ic("tasks")}Задачи и работа</h3>
    ${opt("pult", "Пульт", "окна, где Claude ждёт ответа, задачи, «Ждут «да»» из HANDOFF", true)}
    ${opt("linear", "Задачи Linear", av.linear ? "закрытые вчера и просроченные" : "нет ключа Linear", av.linear)}
    ${opt("github", "GitHub", av.github ? "слитые PR, красный CI, PR ждут решения" : "не задан digest_github в настройках", av.github)}
    ${opt("apple", "Apple: почта и календарь iCloud", "скоро", false)}
    <h3>${ic("wait")}Когда присылать</h3>
    <div class="row"><input type="time" data-time value="${esc(sch.time || "07:30")}" aria-label="Время брифинга"><span class="more">ваш пояс: ${esc(tzName())}</span></div>
    <div class="row seg" role="group" aria-label="Периодичность">${Object.entries(EVERY_T).map(([k, t]) => `<button class="btn quiet sm" data-every="${k}">${t}</button>`).join("")}</div>
    <div class="row days" role="group" aria-label="Дни недели">${DAYS.map((d, i) => `<button class="btn quiet sm" data-day="${i}">${d}</button>`).join("")}</div>
    <div class="acts"><button class="btn" data-bsave>${first ? "Готово — показать брифинг" : "Сохранить"}</button></div></div>`;
  const paint = () => {
    bg.querySelectorAll("[data-every]").forEach((x) => { const o = x.dataset.every === every; x.classList.toggle("on", o); x.setAttribute("aria-pressed", o); });
    bg.querySelector(".days").hidden = every !== "custom";
    bg.querySelectorAll("[data-day]").forEach((x) => { const o = days.includes(+x.dataset.day); x.classList.toggle("on", o); x.setAttribute("aria-pressed", o); });
  };
  paint();
  bg.querySelector("[data-bx]").onclick = close;
  bg.querySelectorAll("[data-every]").forEach((x) => { x.onclick = () => { every = x.dataset.every; paint(); }; });
  bg.querySelectorAll("[data-day]").forEach((x) => { x.onclick = () => { const d = +x.dataset.day; days = days.includes(d) ? days.filter((y) => y !== d) : [...days, d].sort(); paint(); }; });
  bg.querySelector("[data-bsave]").onclick = async () => {
    const pick = (a) => [...bg.querySelectorAll(`[data-${a}]:checked`)].map((x) => x.dataset[a]);
    const boxes = pick("box"), calendars = pick("cal");
    const sources = [...pick("src"), ...(boxes.length ? ["mail"] : []), ...(calendars.length ? ["calendar"] : [])];
    if (every === "custom" && !days.length) return toast("Выберите хотя бы один день", 3000);
    try {
      await api("/api/brief/prefs", { sources, boxes, calendars, time: bg.querySelector("[data-time]").value || "07:30", every, days, tz: tzName() });
    } catch (e) { return toast("Не сохранилось: " + e.message, 4500); }
    toast("Сохранено", 2000);
    briefOpen("fresh");
  };
}
const tzName = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (e) { return ""; } };

// ---------- тур по брифингу: механизм тура пульта (driver.js, отметка на сервере — /api/tour, вид «brief») ----------
const STEPS = [
  { target: "brief-head", title: "Главное — одной строкой", text: "Сколько решений ждут вас и было ли ночью срочное. Ночью бот будит только по деньгам, безопасности и срокам." },
  { target: "brief-decisions", title: "Ждут вашего Да", text: "«Да» — сделать (что именно — написано под пунктом; слияние и «да» проекту — после второго подтверждения). «Нет» — убрать на месяц, «Позже» — вернётся в следующем брифинге." },
  { target: "brief-today", title: "Сегодня", text: "Встречи и дела дня: время слева. Длинная строка раскрывается нажатием." },
  { target: "brief-done", title: "Сделано и не выполнено", text: "«Сделано» свёрнуто — нажмите, чтобы раскрыть. У каждой строки — источник: письмо, событие, PR, задача; нажмите его — откроется оригинал." },
  { target: "brief-prefs", title: "Источники и время", text: "Что подключить, во сколько и по каким дням присылать — меняйте здесь в любой момент или в «Настройки» → «Брифинг»." },
];
async function briefTour() {
  D && (D.tour = "done");
  let drv;
  try { drv = await loadDriver(); } catch (e) { return toast("Тур недоступен — нет связи", 3500); }
  saveTour("brief", "done");
  const steps = STEPS.map((s) => (s.target === "brief-done" && !tourEl("brief-done") ? { ...s, target: "brief-failed" } : s)).filter((s) => tourEl(s.target));
  if (steps.length) await tourRun(drv, steps, "Брифинг", false);
}
