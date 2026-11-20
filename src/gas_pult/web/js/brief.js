// Утренний брифинг первого лица (GAS-18) — часть интерфейса по требованию (#191): ядро держит кнопку «Брифинг»,
// пункт в «⋯» и в «Настройках»; этот код грузится при первом нажатии.
// Владелец 18.11: один экран телефона — вывод одной строкой, «Выполнено», «Не выполнено — и почему», «Ваши решения»
// с «Да / Нет / Позже»; у каждой строки — источник-ссылка. Первый вход — выбор источников и времени («что хотят
// подключить — всегда должна быть такая возможность»), потом — короткий тур (как в админке и сканере TGI).

const KIND_IC = { mail: "mail", calendar: "cal", github: "code", linear: "tasks", pult: "home", handoff: "book" };
const DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const EVERY_T = { workdays: "Рабочие дни", daily: "Каждый день", custom: "Выбрать дни" };
const BLOCKS = [["done", "Выполнено", "check"], ["failed", "Не выполнено — и почему", "warn"]];   // как в макете; «Сегодня» — после решений
let D = null;                                         // ответ /api/brief: {brief, sel, schedule, avail, tour}

const css = document.createElement("style");
css.textContent = `
body:has(.brief-bg) .notices { z-index: 61; }   /* сообщения («Сохранено») — поверх брифинга (Gemini 20.11) */
.brief-bg { position: fixed; inset: 0; z-index: 60; background: var(--bg-canvas); overflow-y: auto; overscroll-behavior: contain; }
.brief { max-width: 640px; margin: 0 auto; padding: 8px 16px calc(24px + env(safe-area-inset-bottom)); color: var(--text-primary); }
.brief .bh { display: flex; align-items: center; gap: 6px; }
.brief .bh h2 { flex: 1; margin: 0; font-size: 20px; }
.brief .bh small { color: var(--text-muted); font-weight: 400; font-size: 13px; margin-left: 6px; }
.brief .bl { margin: 6px 0 4px; padding: 9px 12px; border-radius: var(--radius-md); background: var(--accent-soft); font-weight: 600; line-height: 1.35; }
.brief h3 { display: flex; align-items: center; gap: 6px; margin: 10px 0 2px; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-secondary); }
.brief h3 .i { width: 15px; height: 15px; }
.brief ul { list-style: none; margin: 0; padding: 0; }
.brief li { padding: 5px 0; border-bottom: 1px solid var(--border-subtle); line-height: 1.3; font-size: 14px; }
.brief li:last-child { border-bottom: 0; }
.brief .why { color: var(--status-danger); font-size: 13px; }
.brief .src { display: inline-flex; align-items: center; gap: 3px; font-size: 12px; vertical-align: 1px; color: var(--text-muted); }
.brief .src .i { width: 13px; height: 13px; }
.brief a.src { color: var(--accent-primary); text-decoration: none; }
.brief .dec { border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 7px 10px; margin-top: 6px; font-size: 14px; line-height: 1.3; background: var(--bg-surface); }
.brief .dec.hot { border-color: var(--status-approval); background: var(--status-approval-bg); }
.brief .yes { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
.brief .acts { display: flex; gap: 6px; margin-top: 6px; }
.brief .acts .btn { flex: 1; min-height: 34px; padding-block: 4px; }
.brief .more, .brief .off { font-size: 13px; color: var(--text-muted); margin-top: 6px; }
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
  const inner = ic(KIND_IC[s.kind] || "ext") + esc(s.label);
  return s.url ? `<a class="src" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${inner}</a>` : `<span class="src">${inner}</span>`;
};
const rowHtml = (r) => `<li>${esc(r.text)} · ${srcHtml(r.source)}${r.why ? `<div class="why">${esc(r.why)}</div>` : ""}</li>`;

function frame() {
  document.querySelector(".brief-bg")?.remove();
  const bg = document.createElement("div"); bg.className = "brief-bg"; bg.setAttribute("role", "dialog"); bg.setAttribute("aria-label", "Брифинг");
  bg.addEventListener("keydown", (e) => { if (e.key === "Escape" && !document.querySelector(".driver-popover")) close(); });
  document.body.append(bg);
  return bg;
}
function close() { document.querySelector(".brief-bg")?.remove(); }
const head = (title, sub, btns = "") => `<div class="bh"><h2>${esc(title)}${sub ? `<small>${esc(sub)}</small>` : ""}</h2>${btns}
  <button class="icon" data-bx aria-label="Закрыть брифинг">${ic("x")}</button></div>`;

export async function briefOpen(mode) {
  const bg = frame();
  bg.innerHTML = `<div class="brief">${head("Брифинг", "собираю…")}<div class="empty">Читаю почту, календарь и задачи — несколько секунд.</div></div>`;
  bg.querySelector("[data-bx]").onclick = close;
  try { D = await api("/api/brief" + (mode === "fresh" ? "?fresh=1" : "")); } catch (e) { close(); return toast("Брифинг: " + e.message, 4500); }
  if (mode === "prefs" || !D.sel?.chosen) return pickView(bg, !D.sel?.chosen);
  briefView(bg);
}

function briefView(bg) {
  const b = D.brief, at = (b.at || "").slice(11, 16);
  const blocks = BLOCKS.map(([k, t, i]) => b[k]?.length ? `<section data-tour="brief-${k}"><h3>${ic(i)}${t}</h3><ul>${b[k].map(rowHtml).join("")}</ul>${b.more?.[k] ? `<div class="more">…и ещё ${b.more[k]}</div>` : ""}</section>` : "").join("");
  const decs = b.decisions.map((r, n) => `<div class="dec${r.cat ? " hot" : ""}" data-n="${n}"><div>${esc(r.text)}</div>
      <div class="yes">${srcHtml(r.source)}${r.yes ? ` · «Да» — ${esc(r.yes)}` : ""}</div>
      <div class="acts">${r.act ? `<button class="btn sm" data-a="yes">Да</button>` : ""}<button class="btn quiet sm" data-a="no">Нет</button><button class="btn quiet sm" data-a="later">Позже</button></div></div>`).join("");
  const off = (b.sources || []).filter((s) => s.state === "error" || s.state === "none");
  bg.innerHTML = `<div class="brief">${head("Брифинг", at && "на " + at,
      `<button class="icon" data-btour aria-label="Тур по брифингу">${ic("help")}</button><button class="icon" data-bprefs aria-label="Источники и время" data-tour="brief-prefs">${ic("settings")}</button><button class="icon" data-bfresh aria-label="Обновить">${ic("refresh")}</button>`)}
    <div class="bl" data-tour="brief-head">${esc(b.headline)}</div>
    ${blocks}
    <section data-tour="brief-decisions"><h3>${ic("help")}Ваши решения · ${b.decisions.length}</h3>${decs || '<div class="empty">Решений от вас не ждут.</div>'}</section>
    ${b.today?.length ? `<section data-tour="brief-today"><h3>${ic("cal")}Сегодня</h3><ul>${b.today.map(rowHtml).join("")}</ul></section>` : ""}
    ${off.length ? `<div class="off">Не подключено: ${off.map((s) => esc(s.label + (s.note ? " — " + s.note : ""))).join("; ")}</div>` : ""}
  </div>`;
  bg.querySelector("[data-bx]").onclick = close;
  bg.querySelector("[data-bprefs]").onclick = () => pickView(bg, false);
  bg.querySelector("[data-bfresh]").onclick = () => briefOpen("fresh");
  bg.querySelector("[data-btour]").onclick = () => briefTour();
  bg.querySelectorAll(".dec [data-a]").forEach((x) => { x.onclick = () => act(bg, b.decisions[+x.closest(".dec").dataset.n], x.dataset.a); });
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
  bg.innerHTML = `<div class="brief bpick">${head(first ? "Что включить в брифинг?" : "Брифинг: источники и время")}
    <p class="more">${first ? "Выберите, что подключить. Поменять можно всегда: «Настройки» → «Брифинг». " : ""}Письма и события читает код, а не модель; ничего не отправляется без вашего «Да».</p>
    <h3>${ic("mail")}Почта</h3>${(av.boxes || []).map(box).join("") || '<div class="empty">Ящик не подключён — «Интеграции» → «Почта».</div>'}
    <h3>${ic("cal")}Календарь</h3>${(av.calendars || []).map(cal).join("") || '<div class="empty">Календарь не подключён — «Интеграции» → «Календари»${(av.calkeys || []).length ? ": " + av.calkeys.filter((k) => !k.on).map((k) => esc(k.title)).join(", ") : ""}.</div>'}
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
  { target: "brief-decisions", title: "Ваши решения", text: "«Да» — сделать (что именно — написано под пунктом; слияние и «да» проекту — после второго подтверждения). «Нет» — убрать на месяц, «Позже» — вернётся в следующем брифинге." },
  { target: "brief-done", title: "Выполнено и не выполнено", text: "У каждой строки — источник: письмо, событие, PR, задача. Нажмите источник — откроется оригинал. Строк без источника здесь нет." },
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
