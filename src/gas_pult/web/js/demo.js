// Демо панели (?demo): ответы API на примерах, без сервера. Часть интерфейса по требованию (#191, образец bb —
// docs/ui-code-splitting.md, уровень «intent»): обычный вход эти ~110 КБ не качает; ядро грузит часть через part("demo")
// перед первым запросом демо. Код — классический по смыслу, но выполняется модулем (строгий режим); общие функции и
// переменные ядра видны отсюда как глобальные, а свои — отдаём ядру через window.
// Демо ролей (?demo&persona=1 — экран выбора, &ui=<роль>): тот же справочник, что personas.catalog() — тест сверяет.
const DEMO_PERSONAS = {"ru":{"caps":[{"id":"cap.four_tabs","title":"4 раздела бизнеса: Поиск, Цифры, Бумаги, Общение","ready":true,"dev":false},{"id":"cap.approvals_yes_no","title":"Карточки «Ждут вашего Да» наверху","ready":true,"dev":false},{"id":"cap.scenarios_try","title":"Примерочная: сценарии и калькулятор","ready":true,"dev":false},{"id":"cap.assistant_guide","title":"Помощник «Подсказать» на каждом экране","ready":true,"dev":false},{"id":"cap.pm_tasks_deadlines","title":"Доска задач, сроков и отчётов","ready":false,"dev":false},{"id":"cap.audit_journal","title":"Журнал действий и откат","ready":false,"dev":false},{"id":"cap.sandbox_safe","title":"Учебная песочница с уроками","ready":false,"dev":false},{"id":"cap.dev_sessions","title":"Сессии, папки и ветки","ready":true,"dev":true},{"id":"cap.dev_terminal","title":"Экран терминала и клавиши","ready":true,"dev":true},{"id":"cap.dev_models_mcp","title":"Модели, ключи и подключения (MCP)","ready":true,"dev":true},{"id":"cap.dev_cost_tokens","title":"Подробный расход: токены и стоимость","ready":true,"dev":true}],"personas":[{"id":"business_owner","title":"Владелец или директор бизнеса","sub":"Выручка, документы и клиенты; решения — кнопкой «Да», без сложных настроек.","caps":["cap.four_tabs","cap.approvals_yes_no","cap.scenarios_try","cap.assistant_guide"],"simple":true},{"id":"point_admin","title":"Сотрудник или администратор точки","sub":"Заявки, расписание, клиенты и документы на точке.","caps":["cap.four_tabs","cap.approvals_yes_no","cap.assistant_guide"],"simple":true},{"id":"project_manager","title":"Руковожу проектами и задачами","sub":"Сроки, поручения помощникам, отчёты и журнал.","caps":["cap.approvals_yes_no","cap.assistant_guide","cap.pm_tasks_deadlines","cap.audit_journal"],"simple":false},{"id":"student","title":"Учусь или хочу примерить","sub":"Безопасно попробовать на готовых примерах.","caps":["cap.four_tabs","cap.approvals_yes_no","cap.scenarios_try","cap.assistant_guide","cap.sandbox_safe"],"simple":true},{"id":"developer","title":"Разработчик или инженер","sub":"Сессии, терминал, модели, подключения и расход — как сейчас.","caps":["cap.approvals_yes_no","cap.assistant_guide","cap.audit_journal","cap.dev_sessions","cap.dev_terminal","cap.dev_models_mcp","cap.dev_cost_tokens"],"simple":false}],"sections":[{"id":"search","title":"Поиск"},{"id":"analytics","title":"Цифры"},{"id":"docs","title":"Бумаги"},{"id":"comms","title":"Общение"}]},"en":{"caps":[{"id":"cap.four_tabs","title":"4 business sections: Search, Numbers, Papers, Messages","ready":true,"dev":false},{"id":"cap.approvals_yes_no","title":"“Waiting for your Yes” cards on top","ready":true,"dev":false},{"id":"cap.scenarios_try","title":"Try-on: scenarios and calculator","ready":true,"dev":false},{"id":"cap.assistant_guide","title":"“Help me” assistant on every screen","ready":true,"dev":false},{"id":"cap.pm_tasks_deadlines","title":"Tasks, deadlines and reports board","ready":false,"dev":false},{"id":"cap.audit_journal","title":"Action log and undo","ready":false,"dev":false},{"id":"cap.sandbox_safe","title":"Practice sandbox with lessons","ready":false,"dev":false},{"id":"cap.dev_sessions","title":"Sessions, folders and branches","ready":true,"dev":true},{"id":"cap.dev_terminal","title":"Terminal screen and keys","ready":true,"dev":true},{"id":"cap.dev_models_mcp","title":"Models, keys and connections (MCP)","ready":true,"dev":true},{"id":"cap.dev_cost_tokens","title":"Detailed usage: tokens and cost","ready":true,"dev":true}],"personas":[{"id":"business_owner","title":"Business owner or director","sub":"Revenue, documents and clients; decisions with one “Yes”, no complex settings.","caps":["cap.four_tabs","cap.approvals_yes_no","cap.scenarios_try","cap.assistant_guide"],"simple":true},{"id":"point_admin","title":"Staff member or site administrator","sub":"Requests, schedule, clients and documents on site.","caps":["cap.four_tabs","cap.approvals_yes_no","cap.assistant_guide"],"simple":true},{"id":"project_manager","title":"I manage projects and tasks","sub":"Deadlines, assignments to assistants, reports and the log.","caps":["cap.approvals_yes_no","cap.assistant_guide","cap.pm_tasks_deadlines","cap.audit_journal"],"simple":false},{"id":"student","title":"I'm learning or want to try","sub":"Try safely on ready-made examples.","caps":["cap.four_tabs","cap.approvals_yes_no","cap.scenarios_try","cap.assistant_guide","cap.sandbox_safe"],"simple":true},{"id":"developer","title":"Developer or engineer","sub":"Sessions, terminal, models, connections and usage — as now.","caps":["cap.approvals_yes_no","cap.assistant_guide","cap.audit_journal","cap.dev_sessions","cap.dev_terminal","cap.dev_models_mcp","cap.dev_cost_tokens"],"simple":false}],"sections":[{"id":"search","title":"Search"},{"id":"analytics","title":"Numbers"},{"id":"docs","title":"Papers"},{"id":"comms","title":"Messages"}]}};
// Демо: ответы помощника (перенесено из ядра 21.11) из той же карты (help-map.json), как на сервере.
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
// «Семейная история» (владелец 22.11): id, название, начало задания — как в help/starters.toml
const DEMO_FAMILY = [["grave-search", "Найти место захоронения", "найти, где похоронен мой родственник. К каждой находке дай ссылку на источник. Не нашёл — так и скажи прямо"],
  ["archive-request", "Запрос в архив", "подготовить черновик запроса в архив или ЗАГС: кому писать, что приложить и сам текст. Ничего не отправляй сам"],
  ["family-photos", "Разобрать семейные фото", "разложить копии фото по годам и по людям и подписать, кто на снимке. Оригиналы не трогай"],
  ["family-story", "Записать рассказ близкого", "записать рассказ близкого человека и оформить его главой семейной книги"]];

// Бизнес-демо (framewatcher и владелец 25.11, QR в колоде для ритейла): /?demo — простой режим, бизнес-сценарий «вход →
// работа → выход», у чатов — источник данных (МойСклад, Битрикс24, Telegram, почта), расход и лимиты скрыты.
// &dev — прежнее демо разработчика (на нём автотесты); &simple=0 — сразу полный режим.
const BIZ = !params.has("dev");
const BIZ_S = {   // окно: название ru/en, источник, строка-превью ru/en, папка
  "@1": ["Заказы и остатки", "Orders and stock", "МойСклад", "Сверяю остатки по 214 товарам: 8 заказов ждут сборки", "Checking stock for 214 items: 8 orders wait for picking", "sklad"],
  "@2": ["Утро руководителя магазина", "Store manager's morning", "Telegram", "Отправить персональное предложение 12 покупателям?", "Send a personal offer to 12 customers?", "magazin"],
  "@3": ["Ответы покупателям", "Replies to customers", "Битрикс24", "Готово: 17 ответов на вопросы покупателей", "Done: 17 replies to customer questions", "pokupateli"],
  "@4": ["Протокол планёрки", "Meeting minutes", "Почта", "Протокол разослан: 5 поручений со сроками", "Minutes sent: 5 tasks with deadlines", "planerki"],
  "@5": ["Бот магазина", "Store bot", "Telegram", "", "", "bot"] };
const BIZ_P = { "p-icon": ["Магазин", "Store"], "p-tgi": ["Склад и заказы", "Stock and orders"], "p-gas-pult": ["Покупатели", "Customers"],
  "p-gastech-digest": ["Планёрки", "Meetings"], "p-shop-bot": ["Бот магазина", "Store bot"] };
const BIZ_SRC_EN = { "МойСклад": "MoySklad", "Битрикс24": "Bitrix24", "Telegram": "Telegram", "Почта": "Email" };
function bizHist() {
  const en = LANG === "en";
  return en ? [
    { i: 1, role: "user", text: "Send me the morning numbers for the store", ts: "2026-11-25 07:58" },
    { i: 2, role: "assistant", ts: "2026-11-25 08:00", text: "Good morning! Yesterday: revenue 1,240,000 — 97% of plan. 386 receipts, average 3,210.\n\n| Category | Revenue | Plan |\n|---|---|---|\n| Smartphones | 512,000 | 104% |\n| Laptops | 318,000 | 91% |\n| Home appliances | 314,000 | 99% |\n| Accessories | 96,000 | 78% |\n\nSource: MoySklad. Accessories are behind: 12 customers bought a smartphone this week without a case or a screen protector. I prepared a personal offer for them in Telegram: 10% off until Sunday." },
    { i: 3, role: "user", text: "Good, show me the text and send it", ts: "2026-11-25 08:02" }] : [
    { i: 1, role: "user", text: "Пришли утренние цифры по магазину", ts: "2026-11-25 07:58" },
    { i: 2, role: "assistant", ts: "2026-11-25 08:00", text: "Доброе утро! Вчера выручка 1 240 000 ₽ — 97 % плана. Чеков 386, средний чек 3 210 ₽.\n\n| Категория | Выручка | План |\n|---|---|---|\n| Смартфоны | 512 000 ₽ | 104 % |\n| Ноутбуки | 318 000 ₽ | 91 % |\n| Бытовая техника | 314 000 ₽ | 99 % |\n| Аксессуары | 96 000 ₽ | 78 % |\n\nИсточник: МойСклад. Аксессуары отстают: 12 покупателей за неделю купили смартфон без чехла и стекла. Подготовил им персональное предложение в Telegram — скидка 10 % до воскресенья." },
    { i: 3, role: "user", text: "Хорошо, покажи текст и отправь", ts: "2026-11-25 08:02" }];
}
const BIZ_ASK = { kind: "question", known: true, sig: "biz-offer",
  title_ru: "Отправить персональное предложение 12 покупателям?", title_en: "Send a personal offer to 12 customers?",
  detail_ru: "«Здравствуйте! Для вашего нового смартфона — чехол и защитное стекло со скидкой 10 % до воскресенья.» Список — из МойСклад, отправка — в Telegram.",
  detail_en: "“Hello! A case and a screen protector for your new smartphone — 10% off until Sunday.” List from MoySklad, sent via Telegram.",
  options: [{ key: "q1", label_ru: "Да, отправить", label_en: "Yes, send", send: { n: "1" }, level: 1, note_ru: "", note_en: "" },
    { key: "q2", label_ru: "Нет", label_en: "No", send: { n: "2" }, level: 1, note_ru: "", note_en: "" },
    { key: "q3", label_ru: "Изменить текст", label_en: "Edit the text", send: { n: "3" }, level: 1, note_ru: "", note_en: "" }] };
const BIZ_SCREEN = ["● МойСклад: 12 покупателей без аксессуаров за неделю", "", "☐ Предложение", "", "Отправить персональное предложение 12 покупателям?", "",
  "❯ 1. Да", "     Скидка 10 % на чехол и стекло до воскресенья — в Telegram", "  2. Нет", "  3. Изменить текст", "", "Enter to select · ↑/↓ to navigate · Esc to cancel"];
// Простой режим бизнес-демо — токены дизайн-ТЗ v1.1 (framewatcher 25.11): белая карточка «Да» с янтарной полосой, основная
// кнопка во всю ширину, разделы — текстом, заголовок без обрезки, цифры tabular-nums. Только в бизнес-демо (body.biz-demo):
// настоящий простой режим клиентов и панель владельца не меняются.
const BIZ_CSS = `
body.biz-demo #simple { --bz-line: rgba(17,17,17,.09); --bz-control: #85827A; --bz-accent: #C2361A; --bz-accent-h: #A82E14;
  --bz-on: #FFFFFF; --bz-pending: #B45309; --bz-pending-t: #854D0E; --bz-surface: #FFFFFF; --bz-surface-2: #EFEEEA; --bz-text-3: #5C5A54;
  font-family: "Inter RT", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
:root[data-theme="dark"] body.biz-demo #simple { --bz-line: rgba(255,255,255,.08); --bz-control: #8E8C85; --bz-accent: #FF5A2D;
  --bz-accent-h: #FF7048; --bz-on: #111111; --bz-pending: #F5C46B; --bz-pending-t: #F5C46B; --bz-surface: #181816; --bz-surface-2: #22221F; --bz-text-3: #9A988F; }
body.biz-demo #simple .s-who b { white-space: normal; overflow: visible; text-overflow: clip; font-size: 16px; line-height: 20px; letter-spacing: -.02em; }
@media (max-width: 480px) { body.biz-demo #simple #sHelp span { display: none; } body.biz-demo #simple #sHelp { min-width: 44px; min-height: 44px; padding: 0; justify-content: center; } }
body.biz-demo #simple .s-who small { white-space: nowrap; font-size: 12px; }
body.biz-demo #simple #sWho { pointer-events: none; } body.biz-demo #simple #sWho > .i.s16 { display: none; }   /* демо — один чат, без списка (владелец 25.11) */
body.biz-demo #simple #sVid, body.biz-demo #simple #sTourBtn { margin-right: 6px; }
body.biz-demo .hgo button[data-go="go:simple.agents"] { display: none; }   /* и из «?» — без перехода к списку чатов */
body.biz-demo #simple .s-demo { color: var(--bz-text-3); }
body.biz-demo #simple .s-vid { display: inline-flex; align-items: center; gap: 6px; margin: 0 0 8px; min-height: 36px; padding: 0 12px;
  border: 1px solid var(--bz-line); border-radius: 8px; background: var(--bz-surface); color: var(--text-primary); font: inherit; font-size: 14px; font-weight: 500; cursor: pointer; }
body.biz-demo #simple .s-secs { gap: 2px; padding: 0; box-shadow: inset 0 -1px 0 var(--bz-line); }
body.biz-demo #simple .s-secs .scn-opt { border: 0; background: none; border-radius: 0; min-height: 44px; padding: 0 12px; font-size: 15px;
  font-weight: 500; color: var(--text-secondary); box-shadow: none; }
body.biz-demo #simple .s-secs .scn-opt.on, body.biz-demo #simple .s-secs .scn-opt[aria-pressed="true"] { color: var(--text-primary); box-shadow: inset 0 -2px 0 var(--bz-accent); }
body.biz-demo #simple .s-ask { position: relative; background: var(--bz-surface); border: 1px solid var(--bz-line); border-radius: 12px;
  box-shadow: 0 1px 2px rgba(0,0,0,.04); padding: 16px 16px 16px 19px; }
body.biz-demo #simple .s-ask::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; border-radius: 12px 0 0 12px; background: var(--bz-pending); }
body.biz-demo #simple .s-ask .q { flex-direction: column; gap: 6px; font-size: 18px; line-height: 26px; letter-spacing: -.02em; }
body.biz-demo #simple .s-ask .q .i { display: none; }
body.biz-demo #simple .s-ask .q::before { content: "Требует решения"; display: inline-flex; align-items: center; gap: 6px; font-size: 12px; line-height: 16px;
  font-weight: 500; letter-spacing: 0; color: var(--bz-pending-t); }
body.biz-demo #simple .s-ask .scn-opts { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 14px; }
body.biz-demo #simple .s-ask .scn-opt { width: 100%; min-height: 48px; border-radius: 8px; border: 1px solid var(--bz-control); background: var(--bz-surface);
  color: var(--text-primary); font-size: 16px; font-weight: 600; box-shadow: none; }
body.biz-demo #simple .s-ask .scn-opt[data-sopt="0"] { grid-column: 1 / -1; min-height: 52px; border: 0; background: var(--bz-accent); color: var(--bz-on); }
body.biz-demo #simple .s-ask .scn-opt[data-sopt="0"]:hover { background: var(--bz-accent-h); }
body.biz-demo #simple .md table { font-variant-numeric: tabular-nums; border-collapse: separate; border-spacing: 0; border: 1px solid var(--bz-line); border-radius: 12px; overflow: hidden; }
body.biz-demo #simple .md th, body.biz-demo #simple .md td { border: 0; box-shadow: inset 0 -1px 0 var(--bz-line); padding: 10px 12px; }
body.biz-demo #simple .md tr:last-child td { box-shadow: none; }
body.biz-demo #simple .md th { background: var(--bz-surface-2); font-size: 13px; font-weight: 600; color: var(--text-secondary); }
body.biz-demo #simple .md td:not(:first-child), body.biz-demo #simple .md th:not(:first-child) { text-align: right; }`;
function bizStyle() {                                  // один раз: стили бизнес-демо и шрифт Inter (часть retailfont, если есть)
  if (document.getElementById("bizCss")) return;
  const st = document.createElement("style"); st.id = "bizCss"; st.textContent = BIZ_CSS; document.head.append(st);
  document.body.classList.add("biz-demo");
  part("retailfont").then((m) => m.init()).catch(() => {});
  setTimeout(bizVideo, 1500);
}
// «Смотреть, 1 мин» и в простом режиме (framewatcher 25.11): тихая вторичная кнопка под шапкой; ролик — тот же, что в
// полосе демо (js/demovideo.js); ролика на сервере нет — кнопки нет.
function bizVideo() {
  const src = $("dvBtn"), at = $("sDemo");
  if (!src || !at || !SIM.on || $("sVid")) return;
  const b = document.createElement("button");
  b.type = "button"; b.id = "sVid"; b.className = "s-vid"; b.innerHTML = ic("play", "s16") + "<span>" + (LANG === "en" ? "Watch, 1 min" : "Смотреть, 1 мин") + "</span>";
  b.onclick = () => src.click();
  at.after(b);
  // «Показать тур» — одно нажатие (владелец 25.11): 4–5 шагов и «На экран «Домой»» (js/ladtour.js)
  const tb = document.createElement("button");
  tb.type = "button"; tb.id = "sTourBtn"; tb.className = "s-vid"; tb.innerHTML = ic("spark", "s16") + "<span>" + (LANG === "en" ? "Show the tour" : "Показать тур") + "</span>";
  tb.onclick = () => part("ladtour").then((m) => m.start()).catch(() => toast(LANG === "en" ? "Tour unavailable — no connection" : "Тур недоступен — нет связи", 3500));
  b.after(tb);
}
// Chrome на Android предлагает установку событием до тура — держим его для кнопки «Установить» в шаге «Домой»
addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); window.__ladeyaInstall = e; });
function demoBiz(R) {                                  // данные бизнес-демо поверх общих: окна, источник, без расхода
  const s = R["/api/sessions"], en = LANG === "en";
  s.cost = null; s.limits = null;
  Object.assign(R["/api/meta"], { desktop: false, tty: false });   // бизнес-демо: без «Экрана», «Браузера» и «Терминала» (владелец 25.11)
  bizStyle();
  for (const x of s.sessions) {
    const b = BIZ_S[x.id]; if (!b) continue;
    const src = en ? BIZ_SRC_EN[b[2]] : b[2], text = en ? b[4] : b[3];
    Object.assign(x, { active: x.id === "@2", name: en ? b[1] : b[0], path: "/home/u/projects/" + b[5], branch: "", source: src, cost: null,
      preview: text ? `${src} · ${text}` : "", ...(x.title_own ? {} : { title: en ? b[1] : b[0] }) });
  }
}
function demoTeam(body) {                            // «Команда» в демо: как personas.Team, в памяти страницы
  const t = demoApi.team ||= { staff_caps: null, sections: ["search", "analytics", "docs", "comms"], people: { 2: {} } }, c = DEMO_PERSONAS.ru;
  if (body) { const r = body.id != null ? (t.people[body.id] ||= {}) : t;
    if (body.reset) t.people[body.id] = {};
    else { if (body.caps) r[body.id != null ? "caps" : "staff_caps"] = [...body.caps].sort(); if (body.sections) r.sections = c.sections.map((x) => x.id).filter((x) => body.sections.includes(x)); } }
  const all = c.caps.map((x) => x.id);
  return { staff_caps: t.staff_caps, sections: t.sections, catalog: c,
    people: Object.entries(t.people).map(([id, r]) => ({ id: +id, name: "Иван", username: "", own_caps: r.caps || null, own_sections: r.sections || null,
      ceiling: r.caps || t.staff_caps || all, sections: r.sections || t.sections })) };
}
function demoUi(body) {
  const role = params.get("role") || "owner", c = DEMO_PERSONAS[LANG] || DEMO_PERSONAS.ru;
  const all = c.caps.map((x) => x.id), ceil = role === "viewer" ? all.filter((x) => x !== "cap.dev_models_mcp") : all;
  const st = demoApi.ui ||= { persona: params.get("ui") || (params.get("simple") === "1" || (BIZ && params.get("simple") !== "0") ? "business_owner" : "developer"), added: [], hidden: BIZ ? ["cap.dev_terminal"] : [], onboarded: !params.has("persona") };
  if (body?.persona) Object.assign(st, { persona: body.persona, added: [], hidden: BIZ ? ["cap.dev_terminal"] : [], onboarded: true });
  for (const [k, on] of Object.entries(body?.add || {})) {
    if (on && !ceil.includes(k)) throw new Error("эту возможность вам не разрешил владелец пульта");
    st.added = st.added.filter((x) => x !== k); st.hidden = st.hidden.filter((x) => x !== k); (on ? st.added : st.hidden).push(k);
  }
  const base = c.personas.find((p) => p.id === st.persona)?.caps || [];
  const caps = [...new Set([...base, ...st.added])].filter((x) => !st.hidden.includes(x) && ceil.includes(x)).sort();
  return { ...st, chosen: true, access: { owner: "owner", member: "staff", viewer: "guest" }[role], ceiling: [...ceil].sort(), caps,
           simple: !caps.includes("cap.dev_sessions"), sections: c.sections.map((x) => x.id), can_team: role === "owner", catalog: c,
           own_space: role === "owner" && params.has("space"), fixed: role === "owner" && params.has("space") ? ["cap.dev_sessions"] : [] };
}

// ---------- демо-данные (?demo): только для показа и скриншотов, сервер не трогается ----------
// живой терминал в демо (задача 50): история окна в 1500 строк, экран — 20 нижних; ввод дописывается в строку ❯
function demoTty(key, path, body) {
  const t = demoApi.tty ||= { buf: "", rows: Array.from({ length: 1480 }, (_, k) => k % 97 === 0 ? `❯ прогон тестов, круг ${k / 97 + 1}`
    : k % 13 === 0 ? `● Bash(npm test -- --grep rooms) · ${k} мс` : k === 700 ? "  токен из .env: [скрыт: токен GitHub]" : `  PASS  tests/rooms/case-${k}.test.ts (${(k * 7) % 900 + 40} мс)`) };
  if (key === "/api/tty/type") { if (body.w === "@9" && tg?.initData) return Promise.reject(new Error("в окно с паролем из Telegram не вводим — откройте панель в браузере")); t.buf += body.text; return Promise.resolve({ ok: true }); }
  if (key === "/api/tty/key") {
    if (body.key === "Enter") { t.rows.push("❯ " + t.buf, t.buf ? `● (демо) получено: ${t.buf}` : ""); t.buf = ""; }
    else if (body.key === "BSpace") t.buf = t.buf.slice(0, -1);
    else if (body.key === "C-c") { t.rows.push("❯ " + t.buf + "^C"); t.buf = ""; }
    else if (body.key === "C-l") t.rows.push(...Array(20).fill(""));
    return Promise.resolve({ ok: true });
  }
  const q = new URLSearchParams(path.split("?")[1]), all = [...t.rows, "", "❯ " + t.buf], H = 20, total = all.length, hs = total - H;
  const s = q.get("start"), e = q.get("end");
  let lo = Math.max(0, total - 500), hi = total;
  if (e != null) { hi = Math.min(+e, total); lo = q.get("all") ? 0 : Math.max(0, hi - 500); } else if (q.get("all")) lo = 0; else if (s != null) lo = Math.min(+s, total);
  const w = q.get("w");
  return Promise.resolve({ alive: true, lines: all.slice(lo, hi), cut: Math.max(0, Math.min(hi, hs) - lo), start: lo, end: hi, total, floor: 0, history: hs,
    limit: 50000, height: H, since: 0, w, cx: 2 + t.buf.length, cy: H - 1, width: 80, cursor: true, name: w === "@9" ? "gp-term" : (demoApi.names?.[w] || { "@1": "tgi-0904", "@2": "icon-1146", "@3": "gas-pult", "@4": "digest-0716", "@5": "shop-bot" }[w] || w),
    kind: w === "@9" ? "term" : w === "@5" ? "stopped" : "session", path: "/home/u/projects/demo" });
}
// Демо «Проектов»: проекты — папки сессий демо и ещё два без окон; завершённые чаты — с поиском и «Продолжить».
function demoTitle(id) {                              // простой режим на английском — без русских слов и в демо-данных
  if (demoApi.titles?.[id]) return demoApi.titles[id];  // своё название чата (/api/title)
  if (BIZ && BIZ_S[id]) return BIZ_S[id][LANG === "en" ? 1 : 0];
  return (LANG === "en" ? { "@1": "Room tests and report check", "@2": "Icons for the storefront", "@3": "Panel: dark theme", "@4": "Weekly digest" }
    : { "@1": "Тесты комнат и сверка П8", "@2": "Иконки для витрины", "@3": "Панель: тёмная тема", "@4": "Дайджест за неделю" })[id] || "";
}
function demoProjects(key, path, body, ses) {
  const q = new URLSearchParams(path.split("?")[1] || ""), t0 = demoApi.t0 || Math.floor(Date.now() / 1000), D = 86400;
  demoApi.pj ||= { hidden: {}, titles: {} };
  const en = LANG === "en", L2 = (ru, eng) => (en ? eng : ru);
  const P = [["p-tgi", "tgi", L2("Ассистент ТГИ", "Assistant"), "auto"], ["p-icon", "icon", L2("Иконки магазина", "Shop icons"), "module:wb-reviews"], ["p-gas-pult", "gas-pult", L2("Пульт", "Panel"), "auto"],
    ["p-shop-bot", "shop-bot", L2("Магазин-бот", "Shop bot"), "auto"], ["p-gastech-digest", "gastech-digest", L2("Дайджест", "Digest"), "auto"], ["p-books", "books", L2("Бухгалтерия", "Accounting"), "module:acc-start"], ["p-home", "~", L2("Домашняя", "Home"), "auto"]];
  if (BIZ) P.forEach((x) => { if (BIZ_P[x[0]]) x[2] = L2(...BIZ_P[x[0]]); });
  const DONE = { "p-tgi": [[L2("Отчёт П8 за октябрь", "October report"), 2 * 3600, 14], [L2("Комнаты: миграция базы", "Rooms: database move"), D + 5000, 31], [L2("Сверка по банку", "Bank reconciliation"), 9 * D, 6]],
    "p-books": [[L2("Акт сверки за октябрь", "October reconciliation"), D, 18], [L2("Описание платёжки", "Payment description"), 4 * D, 4]], "p-icon": [[L2("Цены конкурентов", "Competitor prices"), 3 * D, 12]] };
  if (BIZ) DONE["p-tgi"] = [[L2("Инвентаризация за октябрь", "October stocktake"), 2 * 3600, 14], [L2("Перенос остатков со склада", "Stock transfer"), D + 5000, 31], [L2("Сверка по банку", "Bank reconciliation"), 9 * D, 6]];
  const SP = params.has("tester") || params.has("slink");                   // тестировщик (GAS-38): проекты — папки его пространства
  if (SP) { P.length = 0; P.push(...[[L2("Сверка счетов", "Invoice check")], [L2("Меню на зиму", "Winter menu")], [L2("Отчёт для собственника", "Owner report")]].map(([f]) => ["s:demo:" + f, f, f, "space"]));
    DONE["s:demo:" + P[0][1]] = [[L2("Акт сверки с поставщиком", "Supplier reconciliation"), D, 9]]; DONE["s:demo:" + P[1][1]] = [[L2("Цены на супы", "Soup prices"), 3 * D, 5]]; }
  P.push(...(demoApi.pj.newp || []));                // «Новый проект» в демо — в памяти страницы
  if (key === "/api/project/new" && SP) {            // в пространстве: папка — из названия, кириллица можно
    const f = String(body?.name || "").trim().replace(/[\/]+/g, " ").slice(0, 60);
    if (!f) return Promise.reject(new Error("назовите проект"));
    (demoApi.pj.newp ||= []).push(["s:demo:" + f, f, f, "space"]);
    return Promise.resolve({ id: "s:demo:" + f, name: f, folder: f, path: "projects/" + f });
  }
  if (key === "/api/project/new") {
    const f = String(body?.folder || "").trim().toLowerCase() || npFolder(body?.name);
    if (!String(body?.name || "").trim()) return Promise.reject(new Error("назовите проект"));
    if (!/^[a-z0-9][a-z0-9-]{1,40}$/.test(f)) return Promise.reject(new Error("имя папки: латиница в нижнем регистре, цифры, дефис (2–41 знак), без «/» и «..»"));
    if (P.some((x) => x[1] === f)) return Promise.reject(new Error(`папка «${f}» уже есть в ~/projects — выберите другое название или имя папки`));
    const id = "p-new-" + f; (demoApi.pj.newp ||= []).push([id, f, body.name.trim(), "new"]);
    return Promise.resolve({ id, name: body.name.trim(), folder: f, path: "~/projects/" + f });
  }
  const chats = (id) => (DONE[id] || []).map(([title, age, msgs], i) => ({ sid: `00000000-0000-4000-8000-${id.length}${String(i).padStart(11, "0")}`, title, mtime: t0 - age, msgs, mine: i !== 2 }))
    .concat(demoApi.pj.extra?.[id] || []).map((c) => ({ ...c, title: demoApi.pj.titles[c.sid] || c.title, pinned: demoApi.pins?.["c:" + c.sid] || 0 })).filter((c) => !demoApi.pj.hidden[c.sid])
    .sort((a, b) => (b.pinned || 0) - (a.pinned || 0));
  const list = P.map(([id, f, name, origin]) => {
    const mine = ses.sessions.filter((x) => x.project === id), ch = chats(id);
    const last = Math.max(0, ...mine.map((x) => x.changed || 0), ...ch.map((c) => c.mtime)) || null;
    return { id, name, folder: f, path: SP ? "projects/" + f : f === "~" ? "~" : "~/projects/" + f, ...(SP ? { space: "demo", space_title: "Демо для бухгалтерии" } : {}), paths: id === "p-gas-pult" ? ["~/worktrees/gas-pult-fix"] : [], origin, pinned: !!demoApi.pins?.["p:" + id], pinned_at: demoApi.pins?.["p:" + id] || 0, archived: false,
      windows: mine.length, waiting: mine.filter((x) => x.status === "dialog").length, busy: mine.filter((x) => x.status === "busy").length,
      chats: ch.length + mine.length, last, last_title: mine.sort((a, b) => (b.changed || 0) - (a.changed || 0))[0]?.title || ch[0]?.title || "", sessions: mine.map((x) => x.id) };
  }).sort((a, b) => b.pinned_at - a.pinned_at || (b.waiting ? 1 : 0) - (a.waiting ? 1 : 0) || (b.last || 0) - (a.last || 0));
  if (key === "/api/projects") return Promise.resolve({ ...ses, projects: list, new_root: "~/projects", order: demoApi.order || {} });
  const id = q.get("id") || body?.id, p = list.find((x) => x.id === id);
  if (!p) return Promise.reject(new Error("проекта нет — обновите список"));
  if (key === "/api/project") return Promise.resolve({ ...p, instructions: id === "p-books" ? "# Бухгалтерия\nОтвечай коротко. Суммы — в рублях, даты — ДД.ММ.ГГГГ." : "", files: id === "p-books" ? [{ name: "выписка-октябрь.xlsx", size: 48213, mtime: t0 - D }] : [], windows: p.sessions });
  if (key === "/api/project/sessions") {
    const s = (q.get("q") || "").toLowerCase(), all = chats(id).filter((c) => !s || c.title.toLowerCase().includes(s));
    return Promise.resolve({ chats: all, more: false, before: null, cut: false, keep_days: 30, active: p.windows });
  }
  if (key === "/api/project/history") return Promise.resolve({ sid: q.get("sid"), title: chats(id).find((c) => c.sid === q.get("sid"))?.title || "", more: false, items: [
    { i: 0, role: "user", text: L2("Собери акт сверки за октябрь по выписке из папки файлов", "Prepare the October reconciliation from the statement in the files folder"), ts: "2026-11-06 10:02" },
    { i: 1, role: "assistant", text: L2("Готово: **акт сверки** — расхождений два.\n\n| Дата | Сумма | Что |\n|---|---|---|\n| 12.10 | 14 200 ₽ | нет первички |\n| 27.10 | 3 150 ₽ | двойная оплата |",
      "Done: **reconciliation** — two differences.\n\n| Date | Amount | What |\n|---|---|---|\n| 12.10 | 14,200 | no source document |\n| 27.10 | 3,150 | paid twice |"), ts: "2026-11-06 10:05" }] });
  if (key === "/api/project/chat") { if (body.hidden) demoApi.pj.hidden[body.sid] = 1; else if (body.hidden === false) delete demoApi.pj.hidden[body.sid]; if (body.title) demoApi.pj.titles[body.sid] = body.title; return Promise.resolve({ project: id }); }
  if (key === "/api/project/session" || key === "/api/project/resume") return Promise.resolve({ id: p.sessions[0] || (SP ? "t:demo:@1" : "@3"), sid: body.sid || "", project: id });
  return Promise.reject(new Error("демо: нет такого запроса"));
}
// «Удалить» и «Корзина чатов» в демо: окно пропадает из списка, чат — из «Завершённых»; «Вернуть» — в «Завершённые».
async function demoChat(key, body, ses) {
  const pj = demoApi.pj ||= { hidden: {}, titles: {} }, tr = demoApi.trash ||= [], now = Math.floor(Date.now() / 1000);
  const name = (pid) => ({ "p-tgi": "Ассистент ТГИ", "p-icon": "Иконки магазина", "p-gas-pult": "Пульт", "p-shop-bot": "Магазин-бот", "p-gastech-digest": "Дайджест", "p-books": "Бухгалтерия", ...(BIZ ? Object.fromEntries(Object.entries(BIZ_P).map(([k, v]) => [k, v[0]])) : {}) })[pid] || "";
  if (key === "/api/chat/move") {                     // «Перенести в проект…»: занятый — «перенесу после хода»
    const s = ses.sessions.find((x) => x.id === body.w); if (!s) throw new Error("окна уже нет");
    if (body.cancel) return { cancelled: true };
    if (body.project === s.project) throw new Error("чат уже в этом проекте");
    if (s.status === "busy") return { pending: true, id: s.id, project: body.project, project_name: name(body.project), text: "Перенесу, как только закончит" };
    s.project = body.project;
    return { id: s.id, sid: "", project: body.project, project_name: name(body.project), moved: true, trash: null };
  }
  if (key === "/api/chat/delete") {
    let rec;
    if (body.w) {
      const s = ses.sessions.find((x) => x.id === body.w); if (!s) throw new Error("окна уже нет");
      (demoApi.gone ||= {})[body.w] = 1;
      rec = { sid: "00000000-0000-4000-9000-" + String(tr.length + 1).padStart(12, "0"), title: s.title || s.name, project: s.project, w: body.w };
    } else {
      const c = (await demoProjects("/api/project/sessions", "/api/project/sessions?id=" + body.id, body, ses)).chats.find((x) => x.sid === body.sid);
      if (!c) throw new Error("чата нет — Claude Code мог удалить старый журнал");
      pj.hidden[body.sid] = 1; rec = { sid: body.sid, title: c.title, project: body.id, chat: c };
    }
    const t = { id: "t" + (tr.length + 1), at: now, ...rec }; tr.unshift(t);
    return { result: "удалено", closed: !!body.w, draft: "", trash: { id: t.id, sid: t.sid, title: t.title, project: t.project, at: now } };
  }
  if (key === "/api/chat/restore") {
    const i = tr.findIndex((x) => x.id === body.id); if (i < 0) throw new Error("в корзине такого чата нет");
    const [t] = tr.splice(i, 1);
    if (t.w && demoApi.gone) delete demoApi.gone[t.w];   // демо: «Отменить» сразу после «Удалить» — окно на месте
    if (t.chat) delete pj.hidden[t.sid];
    else ((pj.extra ||= {})[t.project] ||= []).unshift({ sid: t.sid, title: t.title, mtime: now - 60, msgs: 5, mine: true });
    return { id: t.id, sid: t.sid, title: t.title, project: t.project, at: t.at };
  }
  const hidden = Object.keys(pj.hidden).filter((sid) => !tr.some((x) => x.sid === sid)).map((sid) => ({ sid, project: "p-tgi", project_name: name("p-tgi"), title: "Скрытый чат" }));
  const left = (x) => Math.max(0, Math.ceil((x.at + 30 * 86400 - now) / 86400));   // как chat_trash.public: 30 дней, предупреждение за 3
  if (!tr.demoOld && params.has("trash")) { tr.demoOld = 1; tr.push({ id: "t-old", sid: "00000000-0000-4000-9000-000000000099", title: "Сверка за сентябрь", project: "p-books", at: now - 28 * 86400 }); }   // ?trash — запись, которой осталось 2 дня
  return { trash: tr.map((x) => ({ id: x.id, sid: x.sid, title: x.title, project: x.project, project_name: name(x.project), at: x.at, purge_at: x.at + 30 * 86400, days_left: left(x), warn: left(x) <= 3 })), hidden, keep_days: 30, warn_days: 3 };
}
function demoRepos(key, path, body) {             // задача 43: список, «добавить» (клон / pull), «отключить»
  const rp = demoApi.rp ||= { "@3": [{ path: "/home/u/projects/gas-pult-docs", name: "gas-pult-docs" }] }, w = body?.w || decodeURIComponent(path.split("w=")[1] || "");
  if (key === "/api/repos/remove") { rp[w] = (rp[w] || []).filter((r) => r.path !== body.path); return Promise.resolve({ added: rp[w] }); }
  if (key === "/api/repos/add") {
    const m = String(body.repo).match(/([\w.-]+)\/([\w.-]+?)(?:\.git)?\/?$/);
    if (!m) return Promise.reject(new Error("нужна ссылка на репозиторий GitHub (https://github.com/владелец/имя) или «владелец/имя»"));
    const r = { path: (w.startsWith("t:") ? "/srv/pult/tenants/demo/home/projects/" : "/home/u/projects/") + m[2], name: m[2] };
    rp[w] = [...(rp[w] || []).filter((x) => x.path !== r.path), r];
    return new Promise((ok) => setTimeout(() => ok({ full: m[1] + "/" + m[2], path: r.path, action: m[2] === "gas-pult" ? "pull" : "clone", sent: true, dialog: false, added: rp[w] }), 900));
  }
  if (w.startsWith("t:")) return Promise.resolve({ added: rp[w] || [], repos: [], error: "", space: "demo", hint: { text: "У этого пространства нет токена GitHub — клонировать закрытые репозитории и показать их список нечем.",
    steps: ["Создайте fine-grained токен на GitHub: доступ — только к нужным репозиториям, права Contents: Read (для пуша — Read and write), Metadata: Read.",
      "Владелец пульта кладёт его в подключения пространства: pult-tenant key demo github (токен — со стандартного ввода, ляжет в secrets.json пространства), — или подключает GitHub в Claude Code этого пространства.",
      "Открытый репозиторий можно добавить и без токена — вставьте ссылку."], url: "https://github.com/settings/personal-access-tokens/new" } });
  return new Promise((ok) => setTimeout(() => ok({ added: rp[w] || [], hint: null, error: "", space: "", repos: [
    { full: "gvriil/gas-pult", private: false, about: "Telegram-пульт и панель для сессий Claude Code" }, { full: "gvriil/gas-pult-docs", private: false, about: "Документация" },
    { full: "gvriil/shop-bot", private: true, about: "Бот магазина" }, { full: "gvriil/gastech-digest", private: true, about: "" }] }), 400));
}
// Расход владельца за сегодня (usage.py) — одно число в меню, на главной, в листе «Расход» и на экране расхода (22.11)
const DEMO_TODAY = { tokens: { in: 4500, out: 214000, cw: 640000, cr: 12650000 }, total: 13508500, usd: 8.36, unknown: false, cost_source: "estimate", estimate: true, pending: 0 };
// Расход по ценам API (/api/spend, js/spend.js): часы — до прошлого полного (сводка раз в час), их сумма не больше
// DEMO_TODAY; проекты — доли итога; 7 дней — по дням; live — итог дня, как в /api/sessions
function demoSpend(path) {
  const p = new URLSearchParams(path.split("?")[1] || "").get("period") || "today", now = new Date(), iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const W = [0, 0, 0, 0, 0, 0, 0, 0, 0.11, 0.53, 0.87, 0.73, 0.34, 0.62, 1.34, 1.09, 0.76, 0.42, 0.25, 0.39, 0.59, 0.22, 0.08, 0];
  const last = p === "today" ? Math.max(now.getHours() - 1, 16) : 23, k = p === "yesterday" ? 0.8 : 1;
  const hours = W.map((v, h) => ({ h, usd: h <= last ? Math.round(v * k * 100) / 100 : 0 }));
  const dd = (i) => { const d = new Date(now); d.setDate(d.getDate() - i); return d; };
  const days = [8.7, 5.2, 7.5, 3.4, 2.7, 6.8, 0].map((v, i) => ({ date: iso(dd(6 - i)), usd: i === 6 ? Math.round(hours.reduce((a, x) => a + x.usd, 0) * 100) / 100 : v }));
  const total = Math.round((p === "7d" ? days : hours).reduce((a, x) => a + x.usd, 0) * 100) / 100;
  const SH = [["shtab", 0.41], ["gas-pult", 0.27], ["shop", 0.14], ["books", 0.09], ["news", 0.06], ["прочее", 0.03]];
  const from = p === "7d" ? dd(6) : p === "yesterday" ? dd(1) : now;
  return Promise.resolve({ period: p, total, updated: Math.floor(now.setMinutes(1, 0, 0) / 1000), from: iso(from), to: iso(p === "yesterday" ? dd(1) : new Date()),
    projects: total ? SH.map(([name, f]) => ({ name, usd: Math.round(total * f * 100) / 100 })) : [], ...(p === "7d" ? { days } : { hours }),
    ...(p === "today" ? { live: DEMO_TODAY } : {}) });
}
function demoApi(path, body) {
  // когда менялись: шкала «N назад» видна целиком — секунды, минуты, часы, «вчера», давняя (>7 дн) остановленная
  const t0 = demoApi.t0 ||= Math.floor(Date.now() / 1000) - 8, H = 3600, D = 86400;
  const AT = { "@1": [t0, t0, t0 - 87], "@2": [t0 - 232, t0 - 232, t0 - 1492], "@3": [t0 - 3 * H - 600, t0 - 3 * H - 600, t0 - 3 * H - 900],
               "@4": [t0 - 26 * H, t0 - 26 * H, t0 - 27 * H], "@5": [t0 - 12 * D, t0 - 12 * D - 40, t0 - 12 * D - 300],
               "t:demo:@1": [t0 - 600, t0 - 600, t0 - 900] };
  const S = [
    { id: "@1", name: "tgi-0904", path: "/home/u/projects/tgi", branch: "chore/claude-files-unify", status: "busy", context: 22, model: "Opus 5.5", active: true, channel: false, rev: "a", preview: "Команда: прогон тестов комнат и сверка П8", agent: "Утренние цифры против плана", sections: ["analytics"] },
    { id: "@2", name: "icon-1146", path: "/home/u/projects/icon", branch: "main", status: "dialog", context: 82, active: false, channel: false, rev: "b", preview: "Удалить dist и пересобрать проект?", agent: "Отзывы и вопросы WB и Ozon", sections: ["comms"] },
    { id: "@3", name: "gas-pult", path: "/home/u/projects/gas-pult", branch: "feature/mini-app", status: "idle", context: 63, active: false, channel: false, rev: "c2", preview: "Готово: панель переписана, тесты зелёные" },
    { id: "@5", name: "shop-bot", path: "/home/u/projects/shop-bot", branch: "main", status: "stopped", context: null, model: "", active: false, channel: false, rev: "", preview: "", profile: "zai" },
    { id: "@4", name: "digest-0716", path: "/home/u/projects/gastech-digest", branch: "main", status: "idle", context: 86, model: "DeepSeek V4 Pro", active: false, channel: false, rev: "d", preview: "Вы: собери дайджест за неделю", profile: "deepseek" },
  ];
  if (path === "/api/close" && body?.w && !FOCUS) (demoApi.gone ||= {})[body.w] = 1;      // «Завершить» в демо — окна нет
  for (let i = S.length - 1; i >= 0; i--) if (demoApi.gone?.[S[i].id]) S.splice(i, 1);   // «Удалить» в демо
  // расход (usage.py): владелец видит свой пул, участник — свою учётку, наблюдатель — ничего; ?cost=pause — сессия на паузе
  const role = params.get("role") || "owner", own = role === "owner";
  demoApi.pins ||= params.has("pins") ? { "w:@3": 2, "p:p-books": 2, "p:p-gas-pult": 1 } : {};   // ?pins — уже закреплены
  if (path === "/api/order") { demoApi.order = { ...(demoApi.order || {}), [body.grp]: body.ids }; return Promise.resolve({ ok: true, ids: body.ids }); }   // свой порядок (20.11)
  if (path === "/api/pin") { const k = body.project ? "p:" + body.project : body.w ? "w:" + body.w : "c:" + body.sid;
    if (body.on === false) delete demoApi.pins[k]; else demoApi.pins[k] = Math.floor(Date.now() / 1000); }
  S.forEach((x) => { x.pinned = demoApi.pins["w:" + x.id] || 0; });
  if (params.has("spaces") && own && !S.some((x) => x.space))   // ?spaces — сессия демо-пространства (группа «Пространства»)
    S.push({ id: "t:demo:@1", name: "Сверка счетов", path: "/home/u/demo", branch: "", status: "idle", context: 12, model: "", active: false, channel: false,
             rev: "s", preview: "Реестр готов: 14 документов, у двух нет первички", profile: "openrouter", space: "demo", space_title: "Демо для бухгалтерии", owner_here: null });
  if (params.has("money")) S.forEach((x) => { if (x.id === "@4") x.no_balance = true; });   // ?money — у поставщика нет денег
  demoApi.sch ||= { state: "on" };                    // расписание агента из модуля (@3 — «Ночная смена»)
  if (path === "/api/module/schedule" && body?.state) demoApi.sch.state = body.state;
  { const x = S.find((y) => y.id === "@3"); const tm = new Date(); tm.setDate(tm.getDate() + 1); tm.setHours(10, 0, 0, 0);
    if (x) x.schedule = { state: demoApi.sch.state, text: "по будням 10:00, 17:00", next: demoApi.sch.state === "on" ? Math.floor(tm / 1000) : null }; }
  demoApi.lim ||= { session: 10, day: 25 };
  if (demoApi.pz === undefined) demoApi.pz = params.get("cost") === "pause" ? "ask" : "";
  if (path === "/api/cost/limits" && body) demoApi.lim = { session: +String(body.session).replace(",", ".") || null, day: +String(body.day).replace(",", ".") || null };
  if (path === "/api/cost/decide") demoApi.pz = body.act === "stop" ? "stopped" : "";
  const cst = (usdv, inp, out, cw, cr, extra = {}) => ({ tokens: { in: inp, out, cw, cr }, total: inp + out + cw + cr, usd: usdv, unknown: usdv == null, cost_source: usdv == null ? null : "anthropic", pending: 0, limit: demoApi.lim.session, ...extra });
  const pz = demoApi.pz && { kind: "session", spent: 10.42, limit: 10, state: demoApi.pz, name: "gas-pult", sid: "c3d4" };
  const COST = own ? { "@1": cst(4.31, 1200, 84000, 310000, 5200000), "@2": cst(0.87, 300, 21000, 90000, 1100000, { by: { id: 2, name: "Иван" } }),
                       "@3": cst(pz ? 10.42 : 3.18, 900, 61000, 240000, 4100000, { paused: pz || null }),
                       "@4": cst(0.31, 2100, 48000, 0, 2250000, { cost_source: "estimate" }) } : role === "member" ? { "@2": cst(0.87, 300, 21000, 90000, 1100000, { limit: null }) } : {};
  if (!demoApi.seeded) { demoApi.seeded = 1; try { localStorage.setItem("seen:@3:/home/u/projects/gas-pult", "c1"); } catch (e) {} }
  // ?ask=question — вопрос агента с вариантами (вид экрана Claude Code 2.1, как в tests/fixtures/cc_question.txt)
  const screen = demoApi.scr ||= BIZ && !params.get("ask") ? [...BIZ_SCREEN] : params.get("ask") === "question" ? ["☐ Отчёт", "", "Какой отчёт прислать утром?", "", "❯ 1. Короткий — три цифры",
    "     Выручка, машины, средний чек", "  2. Подробный — по каждой мойке", "  3. Type something.", "", "Enter to select · ↑/↓ to navigate · Esc to cancel"] : ["● Bash(npm test)", "  ⎿  24 passed", "", " Bash command", "   rm -rf dist && npm run build", "",
    " Do you want to proceed?", " ❯ 1. Yes", "   2. Yes, and don't ask again for rm commands in this project", "   3. No, and tell Claude what to do differently (esc)"];
  const answer = "Готово: панель переписана.\n\n## Что изменилось\n\n| Что | Было | Стало |\n|---|---|---|\n| Тема | только светлая | светлая и тёмная |\n| Экран | текст | варианты — кнопками |\n\n- Поле ввода закреплено внизу\n- Шапка с вкладками закреплена сверху\n\n```bash\ngas-pult webapp --url https://pult.example.com\n```\n\nКак пользоваться панелью — https://github.com/gvriil/gas-pult/blob/main/docs/MINI_APP.md.";
  const TT = demoApi.titles ||= {};                   // «Название чата» (/api/title) — живёт до перезагрузки
  for (const x of S) if (x.id in TT) { x.title = TT[x.id] || x.title; x.title_own = !!TT[x.id]; }
  if (path.split("?")[0] === "/api/spend") return demoSpend(path);
  if (path.split("?")[0] === "/api/chat/mcp") return Promise.resolve({ id: body.w, off: body.off || [] });
  if (path.split("?")[0] === "/api/steps") { const t0 = Date.now() / 1000; const all = [
    { at: t0 - 600, dur: 74, prompt: "Проверь сборку и запусти тесты", answer: "Тесты прошли: 58 из 58. Сборку можно запускать командой ниже.", steps: [
      { at: t0 - 598, tool: "Bash", what: "Выполняет команду: npm run build", ok: true, out: "built in 4.2s", dur: 5 },
      { at: t0 - 590, tool: "Read", what: "Читает файл rooms.test.ts", ok: true, out: "describe('rooms', …", dur: 0.1 },
      { at: t0 - 580, tool: "Bash", what: "Выполняет команду: npm test", ok: true, out: "PASS 58 tests", dur: 52 }] },
    { at: t0 - 300, dur: 21, prompt: "И добавь кнопку обновления", answer: "Добавил кнопку «Обновить» в шапку.", steps: [
      { at: t0 - 298, tool: "Edit", what: "Правит файл Header.tsx", ok: true, out: "", dur: 0.3 },
      { at: t0 - 290, tool: "Bash", what: "Выполняет команду: npm run lint", ok: false, out: "1 error: unused variable 'x'", dur: 6 },
      { at: t0 - 280, tool: "Edit", what: "Правит файл Header.tsx", ok: true, out: "", dur: 0.2 }] }];
    const q = (new URLSearchParams(path.split("?")[1] || "").get("q") || "").toLowerCase();
    return Promise.resolve({ turns: all.filter((t) => !q || JSON.stringify(t).toLowerCase().includes(q)).reverse() }); }
  if (path.split("?")[0] === "/api/q/list") return Promise.resolve({ forms: [{ id: "example", title: "Пример анкеты: настройка учёта" }],
    links: [{ id: "d1", client: "Лавка «Пример»", form: "example", created: Date.now() / 1000 - 86400, exp: Date.now() / 1000 + 13 * 86400, sent: null, answered: 6 }] });
  if (path.split("?")[0] === "/api/q/answers") return Promise.resolve({ client: "Лавка «Пример»", form: "example", sent: null, rows: [{ q: "Сколько предметов учитываем?", a: "1–5 тысяч" }], profile: null });
  if (path.split("?")[0] === "/api/title") { TT[body.w] = body.title || ""; return Promise.resolve({ title: body.title || "", own: !!body.title }); }
  const R = {
    "/api/meta": { desktop: true, agents: [{ id: "pi", title: "Pi", model: "deepseek/deepseek-v4-pro" }], ui: demoUi(), host: "ubuntu", tz: "Europe/Amsterdam", via: "telegram", commands: ["🧠 Модель", "🔌 MCP", "📏 Контекст", "🗜 Сжать", "🧹 Очистить", "ℹ️ Статус"], models: ["opus", "sonnet", "haiku"],
                   keys: [["1","1"],["2","2"],["3","3"],["↑","Up"],["↓","Down"],["⏎","Enter"],["Esc","Escape"],["Ctrl+C","C-c"]].map(([label, key]) => ({ label, key })),
                   projects: ["домашняя (~)", "tgi", "icon", "gas-pult"], voices: [{ id: "irina", label: "Ирина" }], voice: "irina", role: params.get("role") || "owner", tty: params.get("role") !== "viewer" && !params.has("tester"), terms: { version: "2026-11-02", accepted: !params.has("terms") || !!demoApi.terms },
                   country: { chosen: demoApi.cc || (params.has("country") ? "" : "NL"), need: params.has("country") && !demoApi.cc, mismatch: false, phone: !params.has("country"), ip_cc: "NL", check: ["NL"] },
                   profiles: [{ id: "claude", title: "Claude", short: "Claude", about: "Anthropic — как сейчас: подписка или ключ сервера", needs_key: false, main: "", fast: "" },
                     { id: "openrouter", title: "OpenRouter", short: "OpenRouter", about: "Один ключ — сотни моделей, оплата по факту", needs_key: true, oauth: true, key: params.get("orkey") ? { set: true, tail: "…b7e2" } : null, key_url: "https://openrouter.ai/settings/keys", main: "", fast: "", default_main: "", default_fast: "", hint: "id модели из каталога openrouter.ai/models" },
                     { id: "zai", title: "GLM (Z.ai)", short: "GLM", about: "GLM от Z.ai: длинный контекст, недорого. Картинки не понимает", needs_key: true, key: { set: true, tail: "…k3Qa" }, key_url: "https://z.ai/manage-apikey/apikey-list", main: "glm-5.3[1m]", fast: "glm-5.3-flash[1m]", default_main: "glm-5.3[1m]", default_fast: "glm-5.3-flash[1m]", hint: "" },
                     { id: "deepseek", title: "DeepSeek", short: "DeepSeek", about: "DeepSeek V4: быстро и очень дёшево", needs_key: true, key: { set: true, tail: "…7a1c" }, key_url: "https://platform.deepseek.com/api_keys", main: "deepseek-v4-pro[1m]", fast: "deepseek-flash", default_main: "deepseek-v4-pro[1m]", default_fast: "deepseek-flash", hint: "" },
                     { id: "gigachat", title: "GigaChat (через шлюз)", short: "GigaChat", about: "Сбер, для России. Только через ваш шлюз, совместимый с Anthropic (gpt2giga или LiteLLM), в России", needs_key: true, gateway: true, key: demoApi.gw ? { set: true, tail: "…9f2d" } : null, key_url: "https://github.com/gvriil/gas-pult/blob/main/docs/RU-MODELS.md", guide: "https://github.com/gvriil/gas-pult/blob/main/docs/RU-MODELS.md", base_url: demoApi.gw || "", not_ready: demoApi.gw ? "" : "не задан адрес шлюза GigaChat — «Подключения» → «Модели» → GigaChat (через шлюз)", regions: ["RU"], main: "GigaChat-2-Max", fast: "GigaChat-2-Lite", default_main: "GigaChat-2-Max", default_fast: "GigaChat-2-Lite", hint: "имя модели — как его знает ваш шлюз", allowed: false, denied: "Этот сервис недоступен в вашей стране по условиям поставщика" }] },
    "/api/sessions": { host: "ubuntu", now: Date.now() / 1000, tasks: demoTaskCount(), limits: { limits: { five_hour: { used: 21, resets_at: Date.now() / 1000 + 3 * 3600 }, seven_day: { used: 91, resets_at: Date.now() / 1000 + 2 * 86400 } }, at: Date.now() / 1000 }, sessions: S.map((x) => ({ ...x, effort: x.status === "stopped" ? "" : x.id === "@2" ? "medium" : "high", notify: x.status === "stopped" ? "" : (demoApi.nl?.[x.id] && demoApi.nl[x.id] !== "inherit" ? demoApi.nl[x.id] : "all"), notify_own: !!demoApi.nl?.[x.id] && demoApi.nl[x.id] !== "inherit", repos: (demoApi.rp ||= { "@3": [{ path: "/home/u/projects/gas-pult-docs", name: "gas-pult-docs" }] })[x.id] || [], changed: AT[x.id][0], said: AT[x.id][1], asked: AT[x.id][2], name: demoApi.names?.[x.id] || x.name, cost: COST[x.id] || null, cost_paused: x.id === "@3" && !!demoApi.pz, ...(x.id === "@2" && demoApi.answered ? { status: "busy" } : {}) })),
      cost: role === "viewer" ? null : { pool: own ? "owner" : "own", today: own ? DEMO_TODAY
        : { tokens: { in: 300, out: 21000, cw: 90000, cr: 1100000 }, total: 1211300, usd: 0.87, unknown: false, cost_source: "anthropic", pending: 0 }, prices_checked: "2026-11-02", provider_prices_checked: "2026-11-07",
        ...(own ? { limits: demoApi.lim, paused: demoApi.pz ? 1 : 0 } : {}) } },
    "/api/cost/limits": { limits: demoApi.lim, paused: {}, prices_checked: "2026-11-02" },
    "/api/cost/decide": { result: demoApi.pz === "stopped" ? "⏹ «gas-pult» остаётся на паузе по расходу." : "▶️ «gas-pult»: пауза снята, лимит увеличен. Claude продолжает.", limits: demoApi.lim },
    "/api/people": { geoip: true, attribution: "IP Geolocation by DB-IP", attribution_url: "https://db-ip.com", people: [
      { id: 1, role: "owner", name: "", username: "", terms: { version: "2026-11-02", at: 1793491200 }, country: { chosen: "NL", phone: true, phone_cc: "NL", ip_cc: "NL", mismatch: false } },
      { id: 2, role: "member", name: "Иван", username: "ivan", terms: { version: "2026-11-02", at: 1793491200 }, country: { chosen: "NL", phone: true, phone_cc: "RU", ip_cc: "RU", mismatch: true } },
      { id: 3, role: "viewer", name: "Анна", username: "", country: { chosen: "" } }] },
    "/api/country": { chosen: demoApi.cc || (params.has("country") ? "" : "NL"), phone: !params.has("country"), phone_cc: params.has("country") ? "" : "NL", ip_cc: "NL", ip_at: 1793491200, mismatch: false, effective: ["NL"],
      need: params.has("country") && !demoApi.cc, server: "NL", check: ["NL"], geoip: true, geoip_at: 1793491200, attribution: "IP Geolocation by DB-IP", attribution_url: "https://db-ip.com", bot: "pult_demo_bot",
      options: [["NL", "Нидерланды"], ["DE", "Германия"], ["GB", "Великобритания"], ["FR", "Франция"], ["ES", "Испания"], ["PT", "Португалия"], ["PL", "Польша"], ["CY", "Кипр"], ["RS", "Сербия"],
        ["TR", "Турция"], ["GE", "Грузия"], ["AM", "Армения"], ["KZ", "Казахстан"], ["AE", "ОАЭ"], ["IL", "Израиль"], ["US", "США"], ["RU", "Россия"], ["BY", "Беларусь"]].map(([code, name]) => ({ code, name })) },
    "/api/terms": { version: "2026-11-02", title: "Условия использования пульта", url: "https://github.com/gvriil/gas-pult/blob/main/docs/TERMS.md", accepted: false, at: null, points: [
      "Пульт — инструмент: он передаёт ваши сообщения в сессии Claude Code и другие модели. Модели предоставляют их поставщики (Anthropic, OpenRouter и другие) по своим условиям.",
      "Вы сами отвечаете за соблюдение условий поставщиков моделей и законов: у вас свой аккаунт или ключ, вы не делитесь подпиской и не перепродаёте её, работаете только из поддерживаемых поставщиком стран.",
      "Модели доступны только в странах, которые поддерживает поставщик. Страну пульт определяет по вашему выбору, коду страны номера телефона (если вы поделились им в боте) и стране IP-адреса при входе в панель. Храним только коды стран и хеш номера — сам номер и IP-адрес не сохраняются.",
      "При нарушении этих условий или правил поставщика владелец пульта вправе в любой момент и без предупреждения прекратить ваш доступ.",
      "Нажимая «Принимаю», вы подтверждаете, что прочитали условия. Дата согласия сохраняется на сервере пульта."] },
    "/api/login/tg": { id: "demo", link: "https://t.me/rc_cld_bot?start=login_demo", ttl: 300, state: "wait" },
    "/api/mcp": { servers: [{ name: "claude.ai Claude Docs", target: "https://api.anthropic.com/v1/pages/mcp", ok: true, state: "Connected", removable: false },
                            { name: "github", target: "https://api.githubcopilot.com/mcp/ (HTTP)", ok: false, state: "Failed to connect", removable: true }],
                  connectors_url: "https://claude.ai/customize/connectors",
                  connectors: [{ id: "notion", title: "Notion", match: "Notion", about: "Заметки, страницы и базы", example: "Найди в Notion мои заметки за неделю" },
                               { id: "gmail", title: "Gmail", match: "Gmail", about: "Почта: найти, прочитать, ответить", example: "Что важного в почте?" },
                               { id: "gcal", title: "Google Календарь", match: "Calendar", about: "Встречи и планы", example: "Что у меня завтра?" },
                               { id: "gdrive", title: "Google Диск", match: "Drive", about: "Документы и таблицы", example: "Найди договор" }],
                  presets: [{ id: "github", key_url: "https://github.com/settings/personal-access-tokens/new", title: "GitHub", about: "Репозитории, issues, PR — читать, комментировать, создавать", fields: [{ key: "token", label: "Токен GitHub", secret: true, placeholder: "github_pat_…", hint: "github.com → Settings → Developer settings → Personal access tokens → Fine-grained." }], after: "" },
                            { id: "notion", title: "Notion", about: "Страницы и базы Notion — читать и обновлять", fields: [], after: "" },
                            { id: "homeassistant", title: "Home Assistant", about: "Умный дом: состояние устройств, свет, сценарии", fields: [], after: "" }] },
  };
  R["/api/providers"] = { tts: "elevenlabs", stt: "local", el_voice: "v2", local_voice: "Ирина", keys: { elevenlabs: { set: true, tail: "…9fQx" } },
                          el_voices: [{ id: "v1", name: "Rachel" }, { id: "v2", name: "Ксения (клон)" }] };
  R["/api/restart"] = { id: "@4" };
  // окно терминала (задача 47): команде нужен ввод — ?demo&term=@9 открывает его сразу
  if (path === "/api/term/type") demoApi.typed = true;
  if (path === "/api/term/close") demoApi.termGone = true;
  R["/api/run/term"] = R["/api/commands/term"] = { id: "@9", name: "gp-term" };
  R["/api/term"] = { alive: !demoApi.termGone, lines: ["$ keepassxc-cli show -s ~/vault/demo.kdbx Сервисы/почта",
    "Введите пароль для разблокировки demo.kdbx:", ...(demoApi.typed ? ["Title: почта", "UserName: robot", "Password: ••••••••", "", "— готово, код 0. Enter — закрыть окно."] : [])] };
  R["/api/term/type"] = R["/api/term/key"] = R["/api/term/close"] = { ok: true };
  // фокус (задача 41): ?demo&focus — устройство по ссылке (одна сессия @1); &focus=gone — ссылка погасла
  const FURL = location.origin + "/#focus=demo-token-demo-token-demo-token";
  R["/api/focus/new"] = { url: FURL, id: "f1", exp: Math.floor(Date.now() / 1000) + 7 * 86400, name: S.find((y) => y.id === (body?.w || "@1"))?.name || "сессия" };
  if (body?.space) R["/api/focus/new"] = { url: FURL, id: "f9", exp: Math.floor(Date.now() / 1000) + ({ "1h": 1 / 24, "1d": 1, "30d": 30, none: 36500 }[body.ttl] || 7) * 86400, name: body.name || "Демо для бухгалтерии",   // GAS-38
    space: body.space, space_title: "Демо для бухгалтерии", mode: "space", max: body.max, rights: body.rights, forever: body.ttl === "none" };
  R["/api/focus/send"] = { ok: true }; R["/api/focus/revoke"] = { ok: true, links: [] }; R["/api/focus/open"] = { ok: true, name: "gas-pult" };
  R["/api/focus/list"] = { links: [{ id: "f3", name: "Ассистент ТГИ", proj: "p-tgi", space: null, created: Date.now() / 1000 - 300, exp: Date.now() / 1000 + 7 * 86400, opened: null, device: "" },
    { id: "f1", w: "@1", name: "gas-pult", space: null, created: Date.now() / 1000 - 3600, exp: Date.now() / 1000 + 6 * 86400, opened: Date.now() / 1000 - 3000, device: "iPhone · Safari" },
    { id: "f2", name: "Сверка счетов", space: "buh-demo", created: Date.now() / 1000 - 600, exp: Date.now() / 1000 + 7 * 86400, opened: null, device: "" },
    ...(params.has("spaces") ? [{ id: "f4", name: "Кафе — показ партнёру", w: "", space: "demo", mode: "space", devices: 2, max: 3, rights: "full", forever: false, created: Date.now() / 1000 - 900, exp: Date.now() / 1000 + 7 * 86400, opened: Date.now() / 1000 - 600, device: "iPhone · Safari" },
      { id: "f5", name: "Демо для бухгалтерии", w: "", space: "demo", mode: "space", devices: 0, max: 0, rights: "read", forever: true, created: Date.now() / 1000 - 1900, exp: Date.now() / 1000 + 36500 * 86400, opened: null, device: "" }] : [])] };
  // «Открыть на другом устройстве» и «Просят доступ» (22.11): ?demo&focusask=a1 — владелец открыл кнопку из сообщения
  R["/api/focus/device"] = { url: location.origin + "/#focus=demo-extra-demo-extra-demo-extra", exp: Math.floor(Date.now() / 1000) + 900, used: 1, max: 3, qr: demoQr() };
  R["/api/focus/ask"] = { ok: true };
  R["/api/focus/asks"] = { id: "a1", rid: "f1", name: "gas-pult", why: "nodevice", note: "Ольга, ноутбук в офисе", device: "Mac · Chrome", at: Math.floor(Date.now() / 1000) - 120,
    link: { id: "f1", name: "gas-pult", w: "@1", proj: null, mode: "", used: 1, max: 3, live: true, why: "" } };
  if (FOCUS) {
    if (params.get("focus") === "gone") { focusEnd("Чат завершён."); return Promise.reject(new Error("Чат завершён.")); }
    // &focus=nodevice | limit | expired | revoked | bad — ссылка не открылась: свой экран и «Попросить доступ» (22.11)
    const FWHY = { nodevice: "Фокус-ссылка не открыта на этом устройстве.", limit: "Ссылку уже открыли на 3 устройствах.", expired: "Срок фокус-ссылки вышел.", revoked: "Владелец отозвал эту фокус-ссылку.", bad: "Ссылка неверна или устарела." };
    if (FWHY[params.get("focus")] && path !== "/api/focus/ask") { focusEnd(FWHY[params.get("focus")], params.get("focus")); return Promise.reject(new Error(FWHY[params.get("focus")])); }
    // &focus=proj — ссылка на проект сессии @1 (все его окна); &fexp=1 — до конца срока сутки (предупреждение)
    const fp = params.get("focus") === "proj", pw = "p-" + folder(R["/api/sessions"].sessions.find((x) => x.id === "@1")?.path || "");
    const fexp = Math.floor(Date.now() / 1000) + (params.has("fexp") ? +params.get("fexp") || 1 : 7) * 86400 - 600;
    R["/api/meta"] = { ...R["/api/meta"], focus: { id: "f1", name: fp ? pw.slice(2) : "gas-pult", w: fp ? "" : "@1", exp: fexp, proj: fp ? pw : null }, via: "focus", role: "owner", projects: [] };
    if (fp && path === "/api/close") (demoApi.gone ||= {})[body.w] = 1;
    R["/api/sessions"] = { ...R["/api/sessions"], sessions: R["/api/sessions"].sessions.filter((x) => fp ? "p-" + folder(x.path) === pw && !demoApi.gone?.[x.id] : x.id === "@1"), focus: true };
    if (!fp && path === "/api/close") setTimeout(() => focusEnd("Чат завершён."), 0);
  }
  R["/api/close"] = { result: "закрыто", draft: "" };
  if (path.startsWith("/api/bridge/")) return demoBridge(path, body);   // «Компьютеры» (мост, 21.11)
  if (path.startsWith("/api/meeting") || path.startsWith("/api/mt")) return demoMeeting(path, body);   // протоколы встреч (22.11)
  if (path.startsWith("/api/tasks")) return demoTasks(path, body);
  if (path.startsWith("/api/brief")) return demoBrief(path, body);
  if (path.startsWith("/api/desktop/tabs")) return demoTabs(path, body);   // вкладки Chrome стола на телефоне (22.11)
  if (path === "/api/desktop/open") return Promise.resolve({ url: "", demo: true });   // рабочий стол (#206): заглушка     // задачи владельца (#203)
  if (path === "/api/notify/level") { (demoApi.nl ||= {})[body.w] = body.level; R["/api/notify/level"] = { notify: body.level === "inherit" ? "all" : body.level }; }
  if (path === "/api/stopped/clear") { const st = (R["/api/sessions"]?.sessions || []).filter((x) => x.status === "stopped"); st.forEach((x) => { (demoApi.gone ||= {})[x.id] = 1; }); R["/api/stopped/clear"] = { closed: st.length, names: st.map((x) => x.name) }; }
  R["/api/module/schedule"] = S.find((y) => y.id === "@3")?.schedule || {};
  R["/api/module/delete"] = { result: "удалено", trash: "~/.local/share/gas-pult/trash/modules/20261105-101500__gas-pult" };
  R["/api/model"] = { id: body?.w || "@1", model: body?.name || "" };
  R["/api/model/default"] = { model: body?.model ?? "haiku", models: ["opus", "sonnet", "haiku"] };
  // задача 38: что работает у поставщика (models.py CAPS) и автотест (selftest.py)
  { const C = "claude.ai (Google Drive, Notion, Gmail, Claude Docs…)", RM = "PushNotification, RemoteTrigger, DesignSync";
    const g = (ids) => ids.map((id) => ({ id, names: { connectors: C, remote: RM, claude_md: "CLAUDE.md", webfetch: "WebFetch", websearch: "WebSearch" }[id] || "" }));
    const W = ["claude_md", "files", "mcp", "webfetch"], ALT = "Notion, Google Диск (rclone), Веб-поиск";
    const CAPS = { claude: [[], [], [...W, "websearch", "connectors", "images"], ""], openrouter: [["connectors", "remote"], ["websearch"], [...W, "images"], ALT],
      zai: [["connectors", "remote", "websearch", "images"], [], W, ALT], deepseek: [["connectors", "remote", "images"], [], [...W, "websearch"], "Notion, Google Диск (rclone)"],
      gigachat: [["connectors", "remote", "websearch"], ["images", "tools"], W, ALT], yandexgpt: [["connectors", "remote", "websearch"], ["images", "tools"], W, ALT] };
    for (const p of R["/api/meta"].profiles) { const c = CAPS[p.id]; if (c) Object.assign(p, { limits: g(c[0]), unsure: g(c[1]), works: g(c[2]), alt_names: c[3] }); }
    const m = R["/api/mcp"];
    for (const p of m.presets) p.providers = "all";
    m.presets.push({ id: "atlassian", title: "Jira и Confluence", about: "Задачи Jira и страницы Confluence — официальный сервер Atlassian", fields: [], after: "", providers: "all" },
      { id: "gdrive", title: "Google Диск", about: "Найти, прочитать, создать файлы на Диске — официальный сервер Google (превью)", key_url: "https://console.cloud.google.com/auth/clients", providers: "all", after: "",
        fields: [{ key: "client_id", label: "ID клиента OAuth", placeholder: "123….apps.googleusercontent.com", hint: "Google Cloud → Google Auth Platform → Clients → тип «Desktop app»." },
                 { key: "client_secret", label: "Секрет клиента", secret: true, placeholder: "GOCSPX-…", hint: "Там же, в созданном клиенте." }] },
      { id: "websearch", title: "Веб-поиск", about: "Поиск в интернете для любой модели — свой сервер пульта: Яндекс, Brave, Tavily или Exa по вашему ключу", providers: "all", after: "",
        fields: [{ key: "engine", label: "Сервис поиска", options: [{ v: "yandex", t: "Яндекс — лучше по-русски, оплата в рублях", key_url: "https://console.yandex.cloud/folders" },
          { v: "brave", t: "Brave — весь мир, дешевле всех", key_url: "https://api-dashboard.search.brave.com/" }], hint: "Для русского — Яндекс; для мира — Brave." },
          { key: "token", label: "API-ключ", secret: true, placeholder: "ключ сервиса" }, { key: "folder", label: "ID каталога Yandex Cloud", optional: true, placeholder: "b1g…" }] },
      { id: "drive", title: "Google Диск (rclone)", about: "Список, скачать в папку сессии, загрузить из неё — через rclone на сервере, без коннекторов claude.ai", key_url: "https://rclone.org/remote_setup/", providers: "all", after: "",
        fields: [{ key: "token", label: "Ответ rclone authorize", secret: true, multiline: true, placeholder: "{\"access_token\":\"…\"}", hint: "На компьютере с браузером: rclone authorize \"drive\"." }] });
    const ALTC = { notion: "notion", gdrive: "drive" };
    for (const c of m.connectors) Object.assign(c, { providers: "claude", alt: ALTC[c.id] || "" });
    // каталог по разделам (владелец 23.11): разделы, раздел у каждого пункта, Elicit, карточки «официальный путь»
    const CAT = { notion: "docs", gmail: "mail", gdrive: "docs", drive: "docs", websearch: "research", elicit: "research", gcal: "other" };
    m.presets.push({ id: "elicit", title: "Elicit", about: "Научные статьи: поиск, отчёты, систематические обзоры, исследовательский агент — официальный сервер Elicit. Только на тарифах Elicit Pro, Scale и Enterprise",
      key_url: "https://support.elicit.com/en/articles/14757404-use-elicit-via-mcp-server", fields: [], providers: "all", after: "Вход через Elicit (OAuth 2.0): «Войти» ниже или в сессии /mcp → elicit → Authenticate." });
    for (const x of [...m.presets, ...m.connectors]) x.cat = CAT[x.id] || "other";
    m.cats = [["ai", "ИИ-модели и агенты"], ["messengers", "Мессенджеры"], ["mail", "Почта"], ["docs", "Документы и диски"], ["research", "Исследования"], ["other", "Прочее"]].map(([id, title]) => ({ id, title }));
    m.cards = [{ id: "claude", cat: "ai", title: "Claude Code", state: "info", about: "Ваш аккаунт Claude: вход на «Экране» сессии (/login) или ключ API Anthropic. Подписку не передавайте другим людям" },
      { id: "openai", cat: "ai", title: "ChatGPT и OpenAI", state: "info", about: "Только официально: ключ API OpenAI (platform.openai.com) или официальный вход в Codex. Логин и пароль ChatGPT пульт не принимает" },
      { id: "telegram", cat: "messengers", title: "Telegram (как пользователь)", state: "info", owner: true, about: "Только официальный API Telegram: свои api_id и api_hash с my.telegram.org, вход по номеру и коду" },
      { id: "whatsapp", cat: "messengers", title: "WhatsApp (личный)", state: "off", about: "Не поддерживается: запрещено правилами WhatsApp — личный аккаунт через неофициальные клиенты" },
      { id: "whatsapp-business", cat: "messengers", title: "WhatsApp Business Platform", state: "info", about: "Официальный путь для компаний — Cloud API от Meta: номер компании и бизнес-аккаунт. В пульте пока не подключается кнопкой — через «Свой сервер (адрес)», если у вас есть MCP-сервер к Cloud API" },
      { id: "max", cat: "messengers", title: "MAX", state: "off", about: "Нет официального пути для личного аккаунта: вход пользователем запрещён соглашением MAX. Для организации — бот (Bot API MAX)" },
      { id: "mail", cat: "mail", title: "Почта по паролю приложения", state: "info", owner: true, about: "Яндекс, Mail.ru, Gmail, Yahoo — по IMAP с паролем приложения; черновик и отправка — после вашего «Да». Ящик подключает владелец сервера" }];
    const ok = { memory: true, tools: true, tool: true, webfetch: true };
    demoApi.st ||= { running: false };
    if (path === "/api/selftest" && body) demoApi.st = { running: true, at: Date.now() };
    if (demoApi.st.running && Date.now() - demoApi.st.at > 6000) demoApi.st = { running: false, done: true };
    R["/api/selftest"] = { t: t0 - 5 * H, running: demoApi.st.running, checks: ["memory", "tools", "tool", "webfetch"], every: 86400, profiles: [
      { id: "zai", title: "GLM (Z.ai)", t: demoApi.st.done ? t0 : t0 - 5 * H, checks: ok, ok: true, error: "", cost: 0.004, secs: 41, websearch_tool: true },
      { id: "deepseek", title: "DeepSeek", t: t0 - 5 * H, checks: { ...ok, webfetch: !!demoApi.st.done }, ok: !!demoApi.st.done, error: demoApi.st.done ? "" : "WebFetch: превышено время ожидания", cost: 0.002, secs: 63, websearch_tool: true }] }; }
  // модули — те же три, что в templates/modules (без промптов и путей); создание — открывает свободную сессию
  R["/api/modules"] = { root: "projects", errors: [], modules: [{"id":"night-shift","version":"1.0","title":"Ночная смена","industry":"Общие","about":"Ночью агент идёт по плану: код → проверка → ревью безопасности. Будит только по трём причинам.","description":"Вечером вы пишете задачи в PLAN.md, ночью агент выполняет их по одной: пишет код, прогоняет тесты и линтер, проверяет изменения на уязвимости и утечки, коммитит в рабочую ветку. Будит человека только когда без него нельзя: нужно необратимое или внешнее действие, работа заблокирована, найден риск для безопасности или данных — вопросом с кнопками «Да» / «Нет» в Telegram и в панели. Не больше 20 итераций за смену. Утром — отчёт в REPORT.md: что сделано, что нет и почему, что ждёт решения.","integrations":[{"id":"github","title":"GitHub","why":"Задачи из issues и пулл-реквест утром. Без GitHub работа остаётся в локальной ветке — тоже можно.","optional":true,"kind":"preset"},{"id":"linear","title":"Linear","why":"Взять задачи смены из трекера и отметить сделанное.","optional":true,"kind":"connector","match":"Linear"}],"schedule":[{"at":"07:30","days":[1,2,3,4,5,6,7],"title":"Утренний отчёт","when":"07:30"}],"decisions":[{"question":"Нужно необратимое или внешнее действие — разрешаете?","options":["Да","Нет"],"when":"push, деплой, миграция живой базы, удаление данных, письмо или платёж, установка в систему"},{"question":"Работа заблокирована — пропустить задачу и идти дальше?","options":["Да","Нет"],"when":"нет доступа или ключа, противоречие в плане, проверка падает не по задаче после трёх попыток"},{"question":"Найден риск безопасности или данных — исправлять сейчас?","options":["Да","Нет"],"when":"уязвимость, секрет в коде или истории, утечка персональных данных"}],"data_sources":[],"uses":[],"skills":["night-report","night-review"],"files":["CLAUDE.md","PLAN.md"],"folder":"night-shift"},{"id":"client-alerts","version":"1.0","title":"Оповещения клиентов","industry":"Общие","about":"Напоминания и рассылки по шаблонам: агент готовит пачку, человек одобряет кнопкой. Без одобрения — ни одного письма.","description":"Шаблоны напоминаний (запись, оплата, продление) и рассылок — в templates/, клиенты — в data/clients.csv. Агент отбирает получателей по согласию, заполняет шаблоны и показывает пачку: «Отправить пачку из N?» — «Да» / «Нет». Отправляет только после «Да» и только ту пачку, которую показал. Пока канал отправки (почта, Telegram) не подключён — только черновики в outbox/. Пачка — не больше 50 сообщений, тихие часы — с 21:00 до 09:00.","integrations":[{"id":"gmail","title":"Gmail","why":"Канал отправки писем. Без него — только черновики в outbox/, отправляете сами.","optional":true,"kind":"connector","match":"Gmail"},{"id":"telegram-sender","title":"Telegram-бот для рассылок","why":"Канал отправки в Telegram — отдельный бот компании (MCP-сервер). Без него — черновики в outbox/.","optional":true,"kind":"manual","how":"Панель → Подключения → «Другой сервис» → «Свой сервер (адрес)»: MCP-сервер вашего бота рассылок."}],"schedule":[{"at":"10:00","days":[1,2,3,4,5],"title":"Пачка напоминаний на сегодня","when":"10:00"}],"decisions":[{"question":"Отправить пачку из N? (шаблон, число получателей, первые три имени)","options":["Да","Нет"],"when":"каждый раз перед отправкой; «Нет» — пачка остаётся черновиком"}],"data_sources":[{"title":"Клиенты и согласия: data/clients.csv","kind":"client_export","kind_title":"выгрузка клиента","about":"выгрузка из CRM или учётной системы клиента"}],"uses":[{"id":"reminders","title":"Подтверждения и напоминания","about":"Напоминания о записи, оплате, сроках и подтверждения от клиента — пачкой, только после одобрения человека"}],"skills":["alert-batch","alert-send","reminder-batch"],"files":["CLAUDE.md","data/","outbox/","templates/"],"folder":"client-alerts"},{"id":"morning-numbers","version":"1.0","title":"Утренние цифры против плана","industry":"Общие","about":"В 8:00 — план, факт и отклонения за вчера и с начала месяца, топ-3 отклонения и вопрос «что делаем».","description":"Источник — CSV, Google Таблицы или выгрузка из 1С (CSV/XLSX в папке data/). Каждое утро в 8:00 агент берёт свежие данные, считает план, факт и отклонение по каждому показателю за вчера и с начала месяца, выбирает три самых заметных отклонения (порог — 5 %) и спрашивает «Что делаем?» с 2–4 вариантами кнопками. Полная сводка — в SUMMARY.md, история — в history/.","integrations":[{"id":"gdrive","title":"Google Таблицы (через Google Диск)","why":"Если план и факт ведёте в Google Таблицах — агент читает их сам. Не нужен, если данные лежат в data/.","optional":true,"kind":"connector","match":"Drive"},{"id":"onec","title":"Выгрузка из 1С","why":"Отчёт 1С (продажи, план продаж) сохраняется в CSV или XLSX в папку data/ этого пространства.","optional":true,"kind":"manual","how":"В 1С — регламентная выгрузка отчёта в файл в общую папку или на почту; файл кладётся в data/ к 7:50."}],"schedule":[{"at":"08:00","days":[1,2,3,4,5,6,7],"title":"Сводка план/факт","when":"08:00"}],"decisions":[{"question":"Что делаем? (сводка план/факт и топ-3 отклонения в тексте вопроса)","options":["Разобрать главное отклонение","Подробно по показателю","Всё в порядке","Позже"],"when":"каждое утро после сводки; варианты агент подбирает под цифры дня"}],"data_sources":[{"title":"План и факт: CSV или выгрузка из 1С в data/","kind":"client_export","kind_title":"выгрузка клиента","about":""},{"title":"Google Таблицы","kind":"official_api","kind_title":"официальный API","about":"через коннектор Google Диска claude.ai"}],"uses":[],"skills":["data-sources","plan-fact"],"files":["CLAUDE.md","SOURCE.md","data/"],"folder":"morning-numbers"},{"id":"carwash-tire-season","version":"1.0","title":"Сезон шин: запись на переобувку","industry":"Автомойки и шиномонтаж (сеть)","about":"За 3–4 недели до переобувки — клиентам с хранением шин и прошлым клиентам: свободный слот, пик — поровну по филиалам.","description":"Дату старта сезона (зима: 2026-11-23, регион «Средняя полоса (пример)») задаёт человек: обязательные сроки — по ТР ТС\n018/2011 (зимние шины в декабре–феврале, шипы запрещены в июне–августе; регион может сроки увеличить), ориентир —\nсреднесуточная +5…+7 °C. За 3 недели до старта агент собирает две пачки: клиентам с хранением шин у вас\n(сервисное сообщение по договору хранения) и прошлым клиентам шиномонтажа (это реклама — только с согласием на\nрассылку, ст. 18 ФЗ «О рекламе»). Каждому — свободный слот из data/slots.csv; пик распределяется по филиалам с учётом\nпостов и того, где лежат шины клиента, при перегрузе — соседний филиал (скрипт peak_spread.py). Пачка уходит только\nпосле «Отправить пачку из N?» — «Да»; без «Да» — черновики в outbox/. Персональные данные клиентов (телефоны,\nгосномера) — 152-ФЗ: для клиентов в РФ сессия только на российской модели (GigaChat или YandexGPT, docs/RU-MODELS.md),\nхранение в РФ.","integrations":[{"id":"booking-api","title":"Система записи / CRM автомойки (официальный API)","why":"Свободные слоты и клиенты из системы записи напрямую. Без неё — выгрузки в data/slots.csv и data/clients.csv.","optional":true,"kind":"manual","how":"Если у вашей системы записи есть официальный API (например, YCLIENTS REST API) — MCP-сервер с ключом сети: панель → Подключения → «Свой сервер (адрес)». Ключ хранит сервер, не модуль. Запись слота — только после «Да» клиента и человека."},{"id":"telegram-sender","title":"Бот или SMS-шлюз сети для сообщений клиентам","why":"Отправить одобренную пачку. Без него — черновики в outbox/, отправляете сами.","optional":true,"kind":"manual","how":"Панель → Подключения → «Другой сервис» → «Свой сервер (адрес)»: MCP-сервер бота или SMS-шлюза сети."}],"schedule":[{"at":"10:00","days":[1,3,5],"title":"Сезон шин: пачка записи","when":"10:00"}],"decisions":[{"question":"Отправить пачку из N? (сегмент, филиалы, первые три имени, загрузка пика по филиалам)","options":["Да","Нет"],"when":"в дни кампании, по пачке на сегмент"},{"question":"Филиал перегружен — предложить клиентам соседний филиал?","options":["Да, соседний","Добавить слоты","Сдвинуть на неделю"],"when":"загрузка постов филиала выше порога, а свободных слотов в окне нет"},{"question":"Дата старта сезона не задана или прошла — какую ставим?","options":["Предложенную агентом","Через неделю","Задам сам"],"when":"season_start пустая или раньше сегодняшней"}],"data_sources":[{"title":"Клиенты, хранение шин, согласия: data/clients.csv","kind":"client_export","kind_title":"выгрузка клиента","about":"выгрузка CRM или системы записи сети; согласия на уведомления и на рекламу — из неё же"},{"title":"Свободные слоты и посты филиалов: data/slots.csv, data/branches.csv","kind":"client_export","kind_title":"выгрузка клиента","about":"выгрузка расписания постов шиномонтажа"},{"title":"Система записи / CRM сети","kind":"official_api","kind_title":"официальный API","about":"только официальный API с ключом сети (например, YCLIENTS REST API), если подключён"}],"uses":[{"id":"reminders","title":"Подтверждения и напоминания","about":"Напоминания о записи, оплате, сроках и подтверждения от клиента — пачкой, только после одобрения человека; спорные переносы решает человек"}],"skills":["peak-spread","reminder-batch","reminder-replies","reminder-send","tire-season"],"files":["CLAUDE.md","data/","outbox/","templates/"],"folder":"carwash-tire-season"},{"id":"fitness-renewals","version":"1.0","title":"Продления клубных карт","industry":"Фитнес-клубы (семейные)","about":"Точки 60/30/7 дней до конца карты, семейное продление; утром — «под риском».","description":"Каждое утро агент смотрит карты участников (data/members.csv) и посещения (data/visits.csv). Менеджеру в\n9:00 — список «под риском»: посещаемость упала, карта скоро кончится или уже кончилась, на сообщения не\nотвечают (оценка — скрипт renewal_risk.py). Участникам — точки касания за 60, 30 и 7 дней до конца карты (настройка points):\nнапоминание о сроке (сервисное, по согласию на уведомления) и персональное предложение по истории посещений и типу\nкарты (только с согласием на рекламу, ст. 18 ФЗ «О рекламе»). Если у семьи (общий family_id) карты кончаются рядом —\nодно семейное продление плательщику. Скидки и спецусловия — только разрешённые в настройках, иначе вопрос человеку.\nПачка уходит только после «Отправить пачку из N?» — «Да»; без «Да» — черновики в outbox/. Для клиентов в РФ сессия\nтолько на российской модели (GigaChat или YandexGPT, docs/RU-MODELS.md), хранение в РФ (152-ФЗ).","start":"Прочитай CLAUDE.md и data/ (пример выдуманный). Запусти renewal_risk.py на 2026-11-02 (навык renewal-risk) и покажи список «под риском» и кому написали бы сегодня, — ничего не отправляй.","integrations":[{"id":"club-crm","title":"Учётная система клуба / CRM (официальный API)","why":"Карты, посещения и согласия напрямую. Без неё — выгрузки в data/members.csv и data/visits.csv.","optional":true,"kind":"manual","how":"Если у вашей системы учёта клуба есть официальный API — MCP-сервер с ключом клуба: панель → Подключения → «Свой сервер (адрес)». Иначе — ежедневная выгрузка CSV или XLSX в data/."},{"id":"club-sender","title":"Бот или SMS-шлюз клуба для сообщений участникам","why":"Отправить одобренную пачку. Без него — черновики в outbox/.","optional":true,"kind":"manual","how":"Панель → Подключения → «Другой сервис» → «Свой сервер (адрес)»: MCP-сервер бота или SMS-шлюза клуба."}],"schedule":[{"at":"09:00","days":[1,2,3,4,5,6,7],"title":"Под риском — менеджеру","prompt":"Список «под риском» на сегодня (навык renewal-risk): у кого падает посещаемость, кончается или кончилась карта, нет ответа. RISK.md и вопрос менеджеру «Что делаем с N под риском?»; нет таких — одна строка.","when":"09:00"},{"at":"11:00","days":[1,2,3,4,5,6],"title":"Точки касания до конца карты","prompt":"Точки касания за 60,30,7 дней до конца карты (навык renewal-risk), семейные — одним сообщением плательщику. Собери пачки (reminder-batch) и спроси «Отправить пачку из N?» о каждой. Без «Да» не отправляй.","when":"11:00"}],"decisions":[{"question":"Под риском N участников — что делаем? (первые три имени, причины)","options":["Позвонить","Персональное предложение","Подробно","Позже"],"when":"каждое утро, если есть участники с риском «высокий» или «средний»"},{"question":"Отправить пачку из N? (точка 60/30/7, семейные, первые три имени)","options":["Да","Нет"],"when":"каждый день, если есть кому писать"},{"question":"Нужна скидка или спецусловие, которых нет в настройках, — что предлагаем?","options":["Без скидки","Разрешаю один раз","Позвоню сам"],"when":"когда участник просит условие вне прайса и разрешённого в [settings]"}],"data_sources":[{"title":"Карты и согласия: data/members.csv","kind":"client_export","kind_title":"выгрузка клиента","about":"выгрузка учётной системы клуба: тип карты, дата окончания, family_id, согласия — отдельными полями"},{"title":"Посещения: data/visits.csv","kind":"client_export","kind_title":"выгрузка клиента","about":"выгрузка турникета или учётной системы: дата, участник, филиал"},{"title":"Учётная система клуба","kind":"official_api","kind_title":"официальный API","about":"только официальный API с ключом клуба, если подключён"}],"uses":[{"id":"reminders","title":"Подтверждения и напоминания","about":"Напоминания о записи, оплате, сроках и подтверждения от клиента — пачкой, только после одобрения человека; спорные переносы решает человек"}],"settings":{"members":"data/members.csv","visits":"data/visits.csv","points":"60,30,7","family_window":30,"allowed_discount":"нет","family_offer":"нет","risk_at":"9:00","batch_max":50},"skills":["reminder-batch","reminder-replies","reminder-send","renewal-risk"],"files":["CLAUDE.md","data/","outbox/","templates/"],"folder":"fitness-renewals"},{"id":"acc-deadlines","version":"1.0","title":"Сроки отчётности клиентов","industry":"Бухгалтеры и юристы на аутсорсе","about":"Что и кому сдать и уплатить в ближайшие дни по каждому клиенту, что не готово — и напоминания клиентам по вашему «Да».","description":"Для бухгалтерской фирмы на аутсорсе: календарь сроков (data/tax-calendar.csv — уведомления, ЕНП, НДС, УСН, 6-НДФЛ,\nРСВ, персонифицированные сведения) накладывается на профиль каждого клиента (data/clients.csv: режим, работодатель)\nи статус работ (data/status.csv). По будням в 9:00 — что сдать и уплатить за 5 рабочих дней, что не\nготово и чьих документов не хватает. Напоминания клиентам — пачкой после «Да». Сроки — с датой сверки по\nnalog.gov.ru; календарь обновлять ежегодно, сверять с КонсультантПлюс. Для клиентов в РФ — российская модель\n(профили GigaChat или YandexGPT, docs/RU-MODELS.md).","integrations":[{"id":"onec","title":"1С: статус отчётности и данные клиентов","why":"Что уже сдано и уплачено — из базы 1С клиента (выгрузка или OData только на чтение). Без него — data/status.csv.","optional":true,"kind":"manual","how":"В 1С — регламентная выгрузка отчёта «Отчётность» в CSV в data/ или публикация стандартного интерфейса OData (its.1c.ru) с правами только на чтение."},{"id":"gmail","title":"Gmail","why":"Канал напоминаний клиентам по почте. Без него — черновики в outbox/.","optional":true,"kind":"connector","match":"Gmail"}],"schedule":[{"at":"09:00","days":[1,2,3,4,5],"title":"Сроки на ближайшие дни","when":"09:00"}],"decisions":[{"question":"До срока <что> осталось N раб. дн., не готово у K клиентов. Напомнить им?","options":["Да","Нет","Показать список"],"when":"каждое утро, если есть несданное или нет документов"},{"question":"ПРОСРОЧЕНО: <что> у <клиент> — что делаем?","options":["Сдать сегодня","Позвонить клиенту","Отметить сданным"],"when":"срок прошёл, а статус не «сдано»"}],"data_sources":[{"title":"Календарь сроков: data/tax-calendar.csv","kind":"client_export","kind_title":"выгрузка клиента","about":"сроки по НК РФ, сверены с nalog.gov.ru 02.11.2026; обновлять ежегодно"},{"title":"Клиенты и статус работ: data/clients.csv, data/status.csv","kind":"client_export","kind_title":"выгрузка клиента","about":"выгрузка из учётной системы бухгалтерской фирмы или 1С"},{"title":"1С клиента","kind":"official_api","kind_title":"официальный API","about":"стандартный интерфейс OData платформы 1С:Предприятие — только чтение, с согласия клиента"}],"uses":[{"id":"deadlines","title":"Сроки и рабочие дни РФ","about":"Сроки в рабочих днях по производственному календарю РФ (выходные, праздники, переносы) и сигнал заранее — для сроков по закону и отчётности"},{"id":"reminders","title":"Подтверждения и напоминания","about":"Напоминания о записи, оплате, сроках и подтверждения от клиента — пачкой, только после одобрения человека; спорные переносы решает человек"}],"skills":["deadline-plan","reminder-batch","reminder-replies","reminder-send","workdays"],"files":["CLAUDE.md","data/","outbox/","templates/"],"folder":"acc-deadlines"},{"id":"horeca-orders","version":"1.0","title":"Заказ из мессенджера","industry":"Поставщики HoReCa","about":"Сообщение шефа «на завтра базилик 2 кг, руккола 3…» → позиции по прайсу; подтвердить или предложить замену — кнопкой.","description":"Для поставщика свежей продукции ресторанам: шеф пишет заказ как привык — в мессенджер, на почту, голосом\n(расшифровка) — сообщение попадает в inbox/ или в сессию. Агент находит позиции в прайсе data/price.csv (с учётом\nсинонимов и единиц), считает сумму, проверяет наличие (data/stock.csv), минимальную партию и стоп-лист должников, и\nспрашивает: «Подтвердить», «Предложить замену», «Изменить», «Отклонить». Ответ шефу и счёт — черновиком, уходят\nпосле «Да». В 18:00 — лист сборки на завтра.","integrations":[{"id":"telegram-sender","title":"Бот приёма заказов (Telegram)","why":"Заказы шефов из бота компании — сразу в inbox/, ответы шефам после «Да». Без него — пересылаете сообщение в сессию сами.","optional":true,"kind":"manual","how":"Панель → Подключения → «Другой сервис» → «Свой сервер (адрес)»: MCP-сервер бота компании."},{"id":"gmail","title":"Gmail","why":"Заказы, присланные письмом, и отправка счёта. Без него — inbox/ и outbox/.","optional":true,"kind":"connector","match":"Gmail"}],"schedule":[{"at":"18:00","days":[1,2,3,4,5,6,7],"title":"Лист сборки на завтра","when":"18:00"}],"decisions":[{"question":"Заказ <ресторан> на <дата>: N позиций, <сумма> ₽. <чего нет — замена?>","options":["Подтвердить","Предложить замену","Изменить","Отклонить"],"when":"на каждый новый заказ"},{"question":"<ресторан> в стоп-листе по долгу — принять заказ?","options":["Принять","Принять по предоплате","Отказать вежливо"],"when":"заказ от ресторана из стоп-листа"}],"data_sources":[{"title":"Прайс, остатки, рестораны: data/price.csv, data/stock.csv, data/customers.csv","kind":"client_export","kind_title":"выгрузка клиента","about":"из учёта поставщика (1С, таблица)"},{"title":"Сообщения с заказами: inbox/","kind":"client_export","kind_title":"выгрузка клиента","about":"что шефы прислали поставщику — бот компании, почта или пересылка"}],"uses":[{"id":"reminders","title":"Подтверждения и напоминания","about":"Напоминания о записи, оплате, сроках и подтверждения от клиента — пачкой, только после одобрения человека; спорные переносы решает человек"},{"id":"documents","title":"Документы","about":"Счёт, акт, УПД, договор, претензия, письмо — черновик по шаблону, проверка реквизитов и сумм; подписывает и отправляет человек"}],"skills":["claim-draft","document-draft","order-parse","reminder-batch","reminder-replies","reminder-send","requisites-check"],"files":["CLAUDE.md","data/","inbox/","orders/","outbox/","templates/"],"folder":"horeca-orders"},{"id":"wb-ozon-reviews","version":"1.0","title":"Отзывы и вопросы WB и Ozon","industry":"Селлеры WB и Ozon","about":"Черновики ответов на отзывы и вопросы покупателей; негатив — сразу вам; публикуется только после «Да».","description":"Дважды в день агент берёт новые отзывы и вопросы покупателей — через официальный API Wildberries и Ozon Seller API\n(ключ продавца) или из выгрузки в data/reviews.csv — и готовит ответы по фактам о товаре из data/facts.md.\nНегатив (1–3 звезды, «брак», «подделка», «верните деньги») — сразу отдельным вопросом. Остальное — пачкой:\n«Опубликовать N ответов?». Без «Да» — только черновики в outbox/. Отзывы от имени покупателей агент не пишет.","integrations":[{"id":"wb-api","title":"Wildberries API — «Вопросы и отзывы»","why":"Читать новые отзывы и вопросы и публиковать одобренные ответы. Без него — выгрузка в data/reviews.csv, публикуете в кабинете сами.","optional":true,"kind":"manual","how":"Кабинет продавца WB → доступ к API → токен с категорией «Вопросы и отзывы» (только она). MCP-сервер для WB API — панель → Подключения → «Свой сервер (адрес)»; токен хранит сервер, не модуль."},{"id":"ozon-seller-api","title":"Ozon Seller API — отзывы","why":"То же для Ozon. Методы отзывов (ReviewAPI) доступны продавцам с подпиской Premium Plus — проверьте в кабинете.","optional":true,"kind":"manual","how":"Кабинет продавца Ozon → настройки → Seller API: Client-Id и API-ключ с правами на отзывы; MCP-сервер — «Свой сервер (адрес)»."}],"schedule":[{"at":"10:00","days":[1,2,3,4,5,6,7],"title":"Новые отзывы — утро","when":"10:00"},{"at":"17:00","days":[1,2,3,4,5,6,7],"title":"Новые отзывы — вечер","when":"17:00"}],"decisions":[{"question":"Опубликовать N ответов? (позитив, вопросы, первый ответ)","options":["Опубликовать все","По одному","Нет"],"when":"дважды в день после черновиков"},{"question":"Негативный отзыв ★1–3 — опубликовать ответ?","options":["Опубликовать","Изменить","Не отвечать"],"when":"сразу, как пришёл негатив"}],"data_sources":[{"title":"Отзывы и вопросы Wildberries","kind":"official_api","kind_title":"официальный API","about":"API «Вопросы и отзывы», dev.wildberries.ru/openapi/user-communication — ключ продавца"},{"title":"Отзывы Ozon","kind":"official_api","kind_title":"официальный API","about":"Ozon Seller API, ReviewAPI (docs.ozon.ru/api/seller) — Client-Id и API-ключ продавца"},{"title":"Отзывы и факты о товарах: data/reviews.csv, data/facts.md","kind":"client_export","kind_title":"выгрузка клиента","about":"выгрузка отзывов из кабинета продавца и описание товаров от продавца"}],"uses":[{"id":"reviews","title":"Отзывы и NPS","about":"Черновики ответов на отзывы, негатив — сразу руководителю, NPS по периоду; публикует ответ только человек или пульт после «Да»"}],"skills":["marketplace-reviews","nps","review-publish","review-reply"],"files":["CLAUDE.md","data/","outbox/"],"folder":"wb-ozon-reviews"},{"id":"uk-emergency","version":"1.0","title":"Аварийная диспетчерская","industry":"Управляющие компании — «УК-старт»","about":"Таймеры аварийных заявок по п. 13 Правил № 416: нет отметки о локализации за 30 минут — сигнал кнопками.","description":"Диспетчер пишет заявку в сессию («Дом 1, кв. 5, течь ГВС в подвале») или в журнал data/emergency.csv (выгрузка\nсистемы АДС). Агент ставит время регистрации и вид, а каждые 10 минут проверяет таймеры по п. 13 Правил № 416:\nлокализация аварии — 30 минут с регистрации, информирование заявителя о сроках — 30 минут, засор — 2 часа,\nустранение — 3 суток. За 10 минут до срока — предупреждение, срок прошёл без отметки — сигнал вопросом с кнопками в\nTelegram и панели. Бригады агент не вызывает — это делает диспетчер. Проверка раз в 10 минут — это\nсообщения в сессию круглые сутки: учитывайте расход. Сессия — только на российской модели (GigaChat или YandexGPT,\ndocs/RU-MODELS.md); адреса и телефоны жителей — 152-ФЗ, хранение в РФ. Сроки сверены 02.11.2026.","integrations":[{"id":"ads-export","title":"Журнал АДС (выгрузка)","why":"Если заявки ведёт система АДС — её выгрузка в data/emergency.csv. Без неё — диспетчер пишет заявки в сессию.","optional":true,"kind":"manual","how":"Экспорт журнала аварийных заявок системы АДС в CSV в data/ (раз в 5–10 минут) или ввод заявок в сессию."}],"schedule":[{"at":"00:00","days":[1,2,3,4,5,6,7],"title":"Таймеры аварийных заявок","when":"каждые 10 мин","every":10,"until":"23:59"}],"decisions":[{"question":"АВАРИЯ: заявка № <n> (дом, система) — <m> мин без отметки о локализации. Что сделать?","options":["Локализовано — отметить","Бригада на месте","Передать руководителю"],"when":"30 минут с регистрации без отметки о локализации"},{"question":"Заявителю по № <n> не сообщили срок исполнения (30 мин) — отметить?","options":["Сообщили — отметить","Сообщить сейчас","Передать руководителю"],"when":"30 минут с регистрации без отметки об информировании"}],"data_sources":[{"title":"Журнал аварийных заявок: data/emergency.csv","kind":"client_export","kind_title":"выгрузка клиента","about":"журнал АДС самой УК или ввод диспетчера"}],"uses":[],"skills":["emergency-register","emergency-watch"],"files":["CLAUDE.md","data/"],"folder":"uk-emergency"}] };
  R["/api/scenarios"] = {"scenarios":[{"id":"carwash-owner","title":"Владелец сети автомоек","short":"Несколько моек в городе: цифры по филиалам утром, сезон шин, возврат клиентов, ответы на отзывы.","who":"У вас сеть моек в городе — 3 шт. Утром не видно, как сработал каждый филиал: управляющие присылают цифры к обеду, каждый в своём формате. Клиенты моются два-три раза и пропадают, а отзывы на картах висят без ответа по неделе.","industries":["Автомойки и шиномонтаж (сеть)"],"modules":[{"id":"carwash-morning","title":"Утренние цифры по филиалам"},{"id":"carwash-tire-season","title":"Сезон шин: запись на переобувку"},{"id":"carwash-return","title":"Возврат клиентов и допродажа детейлинга"},{"id":"carwash-reviews","title":"Отзывы во всех карточках филиалов"}],"without":"Цифры по филиалам сводите вечером из сообщений управляющих — отклонение видно на день позже. «Ждём вас снова» администратор пишет, когда есть минутка, то есть почти никогда. Ответы на отзывы — раз в неделю, пачкой; запись на сезон шин — по звонкам.","needs":["Выгрузка смен и кассы по филиалам (CSV или XLSX из CRM, кассы или 1С) — раз в день","Клиенты, визиты и согласия на рассылку — выгрузка или официальный API системы записи (если есть)","Отзывы: Google — Business Profile API; Яндекс Карты и 2ГИС — выгрузка, ответ публикуете вы в кабинете","Канал для сообщений клиентам — бот сети в Telegram или почта; нет канала — агент кладёт черновики в outbox/"],"first_step":"Пришлите выгрузку смен за прошлый месяц по всем филиалам — утренние цифры начнут приходить в 8:00. Сезон шин, возврат клиентов и отзывы подключаем по одному.","demo":{"business":"Сеть автомоек «Пример»","point":"Центр"},"timeline_steps":[{"at":"08:00","day":"","module":"carwash-morning","text":"Утренние цифры сети · Сеть автомоек «Пример» (пример)\nВчера: выручка 182 400 ₽ при плане 196 000 ₽ (−7 %), загрузка постов 68 %, средний чек 1 400 ₽.\nГлавное отклонение: «Центр» — −18 % к плану, загрузка 49 % (вечерняя смена).\n\nЧто делаем?","decisions":[{"label":"Разобрать главное отклонение","outcome_toast":"Агент пришлёт разбор по «Центр»: какие часы и посты простаивали, сравнение с прошлой неделей и 2–3 варианта действий. Ничего не меняет сам."},{"label":"Подробно по филиалу","outcome_toast":"Агент покажет таблицу по каждому филиалу: выручка, загрузка, чек, допродажи против плана."},{"label":"Всё в порядке","outcome_toast":"Агент запишет, что отклонение принято, и не будет поднимать его до завтрашней сводки."},{"label":"Позже","outcome_toast":"Агент напомнит после обеда — с теми же цифрами."}],"module_title":"Утренние цифры по филиалам"},{"at":"10:00","day":"","module":"carwash-tire-season","text":"Сезон шин: до старта переобувки 3 недели (дату сезона задаёте вы; погоду агент учтёт, если подключить источник прогноза — нужно подключение).\nПачка 1 — клиенты с хранением шин и согласием на сообщения: 120 человек (пример), слоты поровну по филиалам.\nТекст: «Анна, добрый день! Ваши шины хранятся у нас. Записаться на переобувку — по ссылке» (пример).\n\nОтправить пачку из 120?","decisions":[{"label":"Да","outcome_toast":"Сообщения ушли бы 120 клиентам с хранением шин — сервисные, по договору хранения, через бот сети или почту. Сейчас ничего не отправлено."},{"label":"Нет","outcome_toast":"Пачка останется черновиком в outbox/; агент спросит снова завтра в 10:00."}],"module_title":"Сезон шин: запись на переобувку"},{"at":"11:00","day":"","module":"carwash-return","text":"Не были 30–45 дней и дали согласие на рекламные сообщения: 46 клиентов (пример).\nТекст: «Олег, добрый день! Давно не видели вас в «Центр». Будем рады снова — ответьте, когда удобно. Не хотите таких сообщений — ответьте «стоп»» (пример).\n\nОтправить пачку из 46?","decisions":[{"label":"Отправить","outcome_toast":"Сообщения ушли бы 46 клиентам — только с согласием на рекламу (ст. 18 ФЗ «О рекламе»), с отпиской, одному клиенту не чаще раза в 14 дней. Сейчас ничего не отправлено."},{"label":"Показать первых трёх","outcome_toast":"Агент покажет: Олег — 38 дней, Анна — 41 день, Павел — 44 дня (пример) — и спросит снова."},{"label":"Не сейчас","outcome_toast":"Агент ничего не отправит и спросит завтра."}],"module_title":"Возврат клиентов и допродажа детейлинга"},{"at":"17:00","day":"","module":"carwash-reviews","text":"Готовы ответы на 12 отзывов по филиалам (пример): Google — 7, Яндекс Карты — 4, 2ГИС — 1.\nПервый: «Спасибо, Ирина! Рады, что химчистка салона понравилась — ждём вас снова в «Центр»».\n\nОпубликовать 12 ответов?","decisions":[{"label":"Опубликовать все","outcome_toast":"7 ответов в Google ушли бы через Business Profile API. Ответ скопирован — опубликуйте в кабинете Яндекс Карт и 2ГИС: публичного API ответов у них нет."},{"label":"По одному","outcome_toast":"Агент пришлёт ответы по одному — каждый на «Да» или правку."},{"label":"Нет","outcome_toast":"Ответы останутся черновиками; агент спросит вечером снова."}],"module_title":"Отзывы во всех карточках филиалов"}],"calculator":{"inputs":[{"id":"points","title":"Филиалов","unit":"шт.","default":3,"min":1,"max":50,"step":1,"about":"Сколько моек в сети.","assumption":false},{"id":"clients","title":"Клиентов в месяц по сети","unit":"чел.","default":1500,"min":50,"max":100000,"step":50,"about":"Разных клиентов за месяц по всем филиалам (из кассы или CRM).","assumption":false},{"id":"avg_check","title":"Средний чек","unit":"₽","default":1400,"min":100,"max":50000,"step":50,"about":"Средний чек мойки по сети.","assumption":false},{"id":"return_share","title":"Доля вернувшихся после напоминания","unit":"%","default":2,"min":0.1,"max":20,"step":0.1,"about":"Допущение: какая часть месячного числа клиентов вернётся после «ждём вас». Общая оценка для услуг с регулярными визитами — 1–3 %.","assumption":true},{"id":"minutes","title":"Минут в день на сводку по филиалу","unit":"мин","default":20,"min":1,"max":120,"step":1,"about":"Допущение: сколько сейчас уходит у управляющего и у вас на сбор и сверку цифр одного филиала.","assumption":true}],"formulas":[{"title":"Время на утренние цифры","caption":"","unit":"ч в неделю","of":["points","minutes"],"low":0.08,"high":0.12,"round":0.5,"about":"Филиалы × минуты × 6 дней ÷ 60; агент собирает сводку сам, вы читаете её за минуту."},{"title":"Вернувшиеся клиенты","caption":"","unit":"чел. в месяц","of":["clients","return_share"],"low":0.008,"high":0.012,"round":1,"about":"Клиенты в месяц × доля вернувшихся. Сообщения — только тем, кто дал согласие."},{"title":"Оборот от вернувшихся","caption":"оборот, не прибыль","unit":"₽ в месяц","of":["clients","return_share","avg_check"],"low":0.008,"high":0.012,"round":1000,"about":"Вернувшиеся × средний чек, по одному визиту. Это выручка, не прибыль: себестоимость мойки не вычтена."}],"assumptions_disclaimer":"Оценка, не обещание. Доли и минуты — допущения: поправьте их под себя, результат пересчитается. Диапазон — ±20 % вокруг допущения. Точные цифры покажет пилот на ваших данных за 4 недели."}},{"id":"uk-director","title":"Директор управляющей компании","short":"Сводка утром, раскрытие в ГИС ЖКХ, предписания жилинспекции, долги, сроки ответов жителям.","who":"У вас в управлении несколько десятков многоквартирных домов. Жилинспекция штрафует за просроченные ответы жителям и неисполненные предписания, долги растут, а раскрытие в ГИС ЖКХ кто-то «вроде размещал». О проблемах вы узнаёте из жалоб, а не заранее.","industries":["Управляющие компании — «УК-старт»"],"modules":[{"id":"uk-morning","title":"Утренняя сводка директора УК"},{"id":"uk-gis-disclosure","title":"Сверка раскрытия в ГИС ЖКХ"},{"id":"uk-inspections","title":"Проверки жилинспекции"},{"id":"uk-debts","title":"Долги и суды"},{"id":"uk-requests","title":"Сроки обращений жителей"}],"without":"Сроки ответов жителям считают в календарных днях вместо рабочих — и ошибаются. Пункт предписания вспоминают за день до проверки. Должник, которому полгода назад надо было отправить претензию, всё ещё на ступени «напомнить». Что не размещено в ГИС ЖКХ, выясняется из акта проверки.","needs":["Реестр обращений жителей и журнал аварийной службы — выгрузка (CSV, XLSX) из вашей системы или таблицы","Начисления, оплаты и список должников — выгрузка из биллинга; статусы дел вносит человек (открытого API нет)","Предписания жилинспекции (PDF, скан, текст) и фото или акты по пунктам — в папку пространства","Выгрузка размещённого в ГИС ЖКХ — ваша выгрузка, агент в кабинет не входит","Канал ответов жителям — Telegram или почта УК; SMS-канала в пульте нет, без канала — черновики в outbox/"],"first_step":"Пришлите реестр обращений за последний месяц — сроки по Правилам № 416 и № 354 в рабочих днях появятся в сводке в 8:00, с сигналом за день до срока. Долги, предписания и ГИС ЖКХ — по одному модулю дальше.","demo":{"business":"УК «Пример»","point":"Примерная, 1"},"timeline_steps":[{"at":"08:00","day":"","module":"uk-morning","text":"Сводка директора · УК «Пример» (пример)\nОбращения: просрочено 1, срок сегодня 3, новых за сутки 17.\nАварии за сутки: 2, дольше 30 минут без отметки о локализации — 1 (дом «Примерная, 1», ХВС).\nПлановые работы: отключение ГВС, Тестовая, 12, 10:00–16:00.\n\nЧто делаем?","decisions":[{"label":"Разобрать просроченные","outcome_toast":"Агент пришлёт просроченное обращение с историей, сроком по правилам и черновиком ответа жителю."},{"label":"Подробно по авариям","outcome_toast":"Агент покажет обе аварии по журналу: время звонка, отметка о локализации, где не уложились в 30 минут."},{"label":"Всё в порядке","outcome_toast":"Агент запишет, что сводка просмотрена, и не будет беспокоить до сигнала по сроку."},{"label":"Позже","outcome_toast":"Агент напомнит через час."}],"module_title":"Утренняя сводка директора УК"},{"at":"09:00","day":"1-й рабочий день месяца","module":"uk-gis-disclosure","text":"Сверка раскрытия в ГИС ЖКХ по чек-листу и вашей выгрузке (пример): не размещено 4 — первое: отчёт об исполнении договора управления, дом «Примерная, 1», срок был 31.03; с опозданием — 2.\n\nПоручить?","decisions":[{"label":"Поручить всё ответственному","outcome_toast":"Агент поставит ответственному задачу со списком из 4 пунктов и сроками. Размещает в ГИС ЖКХ человек."},{"label":"Поручить по пунктам","outcome_toast":"Агент спросит по каждому пункту, кому поручить."},{"label":"Уже размещено — обновлю выгрузку","outcome_toast":"Агент дождётся новой выгрузки и сверит снова."},{"label":"Позже","outcome_toast":"Агент напомнит завтра."}],"module_title":"Сверка раскрытия в ГИС ЖКХ"},{"at":"09:10","day":"","module":"uk-inspections","text":"Пункт 3 предписания № 41-П (пример): ремонт отмостки, дом «Примерная, 1». До срока 2 рабочих дня, фото и актов в папке пункта нет.\n\nПросить продление?","decisions":[{"label":"Просить продление","outcome_toast":"Агент подготовит черновик ходатайства об отсрочке с обоснованием; подписываете и отправляете вы."},{"label":"Успеем — напомнить исполнителю","outcome_toast":"Агент напомнит исполнителю о сроке и о том, какие фото и акты нужны для отчёта."},{"label":"Позже","outcome_toast":"Агент спросит снова завтра — до срока останется 1 рабочий день."}],"module_title":"Проверки жилинспекции"},{"at":"09:30","day":"","module":"uk-debts","text":"ЛС-000-01 (пример): долг 38 400 ₽ за 7 месяцев, пени 2 160 ₽ (расчёт по ч. 14 ст. 155 ЖК РФ). Напоминания были дважды, оплат нет.\n\nПеревести на «претензию»?","decisions":[{"label":"Да","outcome_toast":"Агент подготовит черновик претензии с расчётом пеней; подписывает юрист, отправляете вы."},{"label":"Нет","outcome_toast":"Должник останется на ступени «напоминание»."},{"label":"Отложить на 14 дней","outcome_toast":"Агент вернётся к должнику через 14 дней с новым расчётом."},{"label":"Рассрочка","outcome_toast":"Агент подготовит черновик соглашения о рассрочке — условия задаёте вы."}],"module_title":"Долги и суды"},{"at":"14:00","day":"","module":"uk-requests","text":"Готовы черновики ответов жителям, срок которых истекает завтра: 5 (пример).\nПервый: «Добрый день! По вашему обращению № 418 о перерасчёте: перерасчёт за октябрь будет в квитанции за ноябрь».\n\nОтправить пачку из 5?","decisions":[{"label":"Отправить","outcome_toast":"Ответы ушли бы 5 жителям — в Telegram или на почту УК; у кого нет канала — черновик в outbox/ для печати. Сейчас ничего не отправлено."},{"label":"Показать черновики","outcome_toast":"Агент покажет черновики по одному — каждый на «Да» или правку."},{"label":"Не сейчас","outcome_toast":"Агент напомнит перед концом дня: срок — завтра."}],"module_title":"Сроки обращений жителей"}],"calculator":{"inputs":[{"id":"requests","title":"Обращений жителей в месяц","unit":"шт.","default":400,"min":1,"max":50000,"step":10,"about":"Все обращения в реестре.","assumption":false},{"id":"late_share","title":"Доля ответов, уходящих с опозданием","unit":"%","default":3,"min":0.1,"max":50,"step":0.1,"about":"Допущение: какая часть ответов сейчас опаздывает из-за подсчёта сроков вручную.","assumption":true},{"id":"debt","title":"Просроченный долг жителей","unit":"₽","default":3000000,"min":10000,"max":1000000000,"step":10000,"about":"Сумма долгов дольше трёх месяцев по всем лицевым счетам.","assumption":false},{"id":"speed_share","title":"Доля долга, собранная раньше за месяц","unit":"%","default":2,"min":0.1,"max":30,"step":0.1,"about":"Допущение: какую часть долга ступени без пропусков (напоминание → претензия → приказ) собирают раньше обычного.","assumption":true}],"formulas":[{"title":"Ответы жителям, ушедшие в срок","caption":"","unit":"ответов в месяц","of":["requests","late_share"],"low":0.008,"high":0.012,"round":1,"about":"Обращения × доля опаздывающих: агент считает сроки по правилам в рабочих днях и предупреждает за день."},{"title":"Ускорение сбора долгов","caption":"ускорение сбора, не доп. доход","unit":"₽ в месяц","of":["debt","speed_share"],"low":0.008,"high":0.012,"round":1000,"about":"Долг × доля, собранная раньше. Эти деньги вам и так должны — агент помогает получить их раньше."}],"assumptions_disclaimer":"Оценка, не обещание. Доли и минуты — допущения: поправьте их под себя, результат пересчитается. Диапазон — ±20 % вокруг допущения. Деньги по долгам — ускорение сбора того, что вам и так должны, а не дополнительный доход. Точные цифры покажет пилот на ваших данных."}}]};
  // слепые проверяющие — в каждом пространстве модуля (reviewers.public, задача 45)
  for (const m of R["/api/modules"].modules) m.agents = [{"id": "slepaya-proverka", "title": "Слепая проверка", "about": "Смотрит на готовую работу глазами заказчика: видит только требование и результат, отвечает «принято» или «не принято» и адресом у каждой находки."}, {"id": "slepaya-proverka-dokumentov", "title": "Проверка документов как налоговая или банк", "about": "Документы бухгалтера или юриста глазами инспектора ФНС или банка по 115-ФЗ — до отправки."}];
  // уже созданное пространство модуля — «Открыть» первым, «Создать ещё одно» — с подтверждением (задача 27)
  for (const m of R["/api/modules"].modules) m.existing = m.id === "night-shift" ? [{ folder: "ночная-смена", path: "ночная-смена", changed: Date.now() / 1000 - 3 * 3600 | 0, i: 3, open: null }] : [];
  R["/api/folder"] = body?.name === "gas-pult" ? { exists: true, folder: "gas-pult", path: "gas-pult", i: 3, open: "@3" }
    : { id: "@3", path: (body && body.name) || "new-project", folder: (body && body.name) || "new-project" };
  R["/api/modules/create"] = { id: "@3", path: "night-shift", folder: (body && body.name) || "night-shift" };
  if (path.startsWith("/api/voice/choose")) demoApi.vcur = body.id;       // демо: голоса — Ксения выбрана, Ксения-2 не установлена
  { const own = (params.get("role") || "owner") === "owner", K = { xenia: ["Ксения", "женский"], baya: ["Бая", "женский"], aidar: ["Айдар", "мужской"], eugene: ["Евгений", "мужской"],
      kseniya: ["Ксения-2", "женский"] };            // Piper в выборе нет — только запасной синтез
    const loc = own ? Object.entries(K).map(([id, [name, kind]]) => { const ok = id !== "kseniya";
      return { id, name, kind, ok, demo: true, why: ok ? "" : "не установлен", install: ok ? "" : "gas-pult voices install " + id }; }) : [];
    R["/api/voice/cards"] = R["/api/voice/choose"] = { can_choose: own, current: own ? (demoApi.vcur || "xenia") : "irina", fallback: own ? "" : "Ирина",
      cards: [{ id: "elevenlabs", name: "Ксения (клон)", kind: "облачный", ok: true, why: "", install: "" }, ...loc] }; }
  demoApi.fb ||= ["openrouter", "claude"];
  if (path === "/api/fallback" && body) demoApi.fb = body.chain;
  // сессии пространства (space-sessions): закрытые и корзина; закрыть — сначала «агент работает», потом закрыто
  R["/api/space/sessions"] = { keep_days: 14, closed: [{ folder: "Сверка актов за октябрь", changed: t0 - 5 * H, history: true, draft: true },
                                                      { folder: "Пустая проба", changed: t0 - 2 * D, history: false, draft: false }],
                               trash: [{ id: "20261101-101500__Черновик реестра", folder: "Черновик реестра", deleted: t0 - D, until: t0 + 13 * D }] };
  if (path === "/api/space/close") return body.force || params.get("ss") !== "busy" ? { result: "closed", folder: "Сверка счетов", draft: "" } : { result: "busy", folder: "Сверка счетов" };
  R["/api/space/resume"] = { id: "t:demo:@1", continued: true, draft: "А что со счётом №14?" };
  R["/api/space/delete"] = { id: "x", until: t0 + 14 * D, keep_days: 14 };
  R["/api/space/restore"] = { folder: "Черновик реестра" };
  R["/api/space/files"] = { free: 1600 * 1024 * 1024, files: [{ name: "Реестр входящих.xlsx", size: 48213, changed: t0 - 300 },
    { name: "Акт сверки №14.pdf", size: 1288490, changed: t0 - 2 * H }, { name: "data/выгрузка 1С.xml", size: 913, changed: t0 - D }] };
  R["/api/space/upload"] = { name: "Счёт.pdf" };
  // свои интеграции пространства (GAS-38 (в)): список без ключей, подключить и отключить — в памяти демо
  const smcp = (demoApi.smcp ||= [{ name: "github", type: "http", target: "https://api.githubcopilot.com", removable: true },
                                    { name: "browser-local", type: "stdio", target: "python3", removable: false }]);
  R["/api/space/mcp"] = { space: "demo", servers: smcp, presets: [...R["/api/mcp"].presets.filter((x) => !["websearch", "drive", "gdrive", "stdio", "docs", "icloud"].includes(x.id)),
    { id: "websearch", title: "Веб-поиск", about: "Поиск в интернете для любой модели: Яндекс, Brave, Tavily или Exa по вашему ключу",
      fields: [{ key: "engine", label: "Сервис поиска", options: [{ v: "yandex", t: "Яндекс" }, { v: "brave", t: "Brave" }] }, { key: "token", label: "API-ключ", secret: true }], after: "" }] };
  if (path === "/api/space/mcp/add") { if (!smcp.some((x) => x.name === body.name)) smcp.push({ name: body.name, type: "http", target: "https://" + body.preset + ".example", removable: true }); return Promise.resolve({ result: "подключено. Перезапустите открытые сессии.", servers: smcp }); }
  if (path === "/api/space/mcp/remove") { demoApi.smcp = smcp.filter((x) => x.name !== body.name); return Promise.resolve({ result: "отключено", servers: demoApi.smcp }); }
  // черновики действий коннекторов (drafts.py): «Да / Изменить / Нет» — в памяти демо
  const drf = (demoApi.drf ||= [{ id: "a1b2c3d4e5f6", svc: "moysklad", action: "set_order_state", summary: "Заказ №1043 «Кафе у моря» → статус «Отгружен»", created: "", w: "@1" },
                                 { id: "0f1e2d3c4b5a", svc: "wildberries", action: "feedback_answer", summary: "Ответ на отзыв о кофемолке: «Спасибо! Замену отправили сегодня»", created: "", w: null }]);
  R["/api/drafts"] = { drafts: params.has("drafts") ? drf : [] };   // только ?demo&drafts: не мешают остальным снимкам и проверкам
  if (path === "/api/drafts/yes" || path === "/api/drafts/no") { demoApi.drf = drf.filter((x) => x.id !== body.id); return Promise.resolve({ ok: true }); }
  if (path.startsWith("/api/space/download")) return Promise.resolve(new Blob(["демо"], { type: "text/plain" }));
  const demoBud = { daily: 4, period_days: 30, reserve: 120, spent: 97.4, today: 9.2, left: 22.6, pct: 0.81, over: false, reason: "", day_cap: null, estimate: true,
    text: "сегодня $9.20 · в запасе $22.60 до 01.12 · норма $4.00/день; при нынешнем темпе хватит до 21.11 (оценка по ценам за токены — работает на подписке)" };
  R["/api/spaces"] = params.has("spaces") ? { enabled: true, tenants: [{ slug: "demo", title: "Демо для бухгалтерии", ready: true, budget: demoBud }] } : { enabled: false, tenants: [] };
  R["/api/fallback"] = { chain: demoApi.fb, region: "NL", voice_note: "",
    options: [{ id: "claude", title: "Claude", why: "" }, { id: "openrouter", title: "OpenRouter", why: params.get("orkey") ? "" : "нет ключа" },
              { id: "zai", title: "GLM (Z.ai)", why: "" }, { id: "deepseek", title: "DeepSeek", why: "" }],
    log: [{ t: "2026-11-01 14:20", text: "Поставщик DeepSeek не отвечает (429) — сессия «digest-0716» переключена на OpenRouter" },
          { t: "2026-11-01 16:05", text: "Поставщик OpenRouter не отвечает (529) — сессия «digest-0716» переключена на Claude" }],
    voice: { tts: ["ElevenLabs", "На сервере · Piper"], stt: ["ElevenLabs Scribe", "На сервере · whisper"] } };
  // ?setup=login — вход не выполнен, ?setup=none — Claude Code не установлен; без параметра — всё готово
  const su = params.get("setup"), inst = su !== "none";
  R["/api/setup/status"] = { ready: !su, claude: { installed: inst, path: inst ? "/usr/local/bin/claude" : "", version: inst ? "2.1.316 (Claude Code)" : "" },
    auth: { logged_in: !su, method: su ? "" : "claude.ai" }, keys: ["zai"], doc: "https://github.com/gvriil/gas-pult/blob/main/docs/SETUP-CLAUDE.md", login: demoApi.login || null,
    checks: [{ name: "tmux", ok: true, hint: "" }, { name: inst ? "Claude Code 2.1.316 (Claude Code)" : "Claude Code", ok: inst, hint: inst ? "" : "установите: https://docs.claude.com/en/docs/claude-code/setup" },
      ...(inst ? [{ name: su ? "вход не выполнен" : "вход выполнен (claude.ai)", ok: !su, hint: su ? "«Войти в Claude» в боте или панели" : "" }] : []), { name: "ключи поставщиков: Z.ai", ok: true, hint: "" }] };
  if (path === "/api/setup/login") return Promise.resolve(demoApi.login = { active: true, w: "@9", url: "https://claude.ai/oauth/authorize?code=true&client_id=demo", code: true, done: false, error: "", lines: [] });
  if (path === "/api/setup/code") return Promise.resolve({ ok: false, error: "демо: код никуда не уходит", lines: [] });
  R["/api/openrouter/start"] = { url: "https://openrouter.ai/auth?demo" };
  R["/api/openrouter/info"] = { key: true, label: "gas-pult", usage: 4.27, usage_monthly: 1.9, limit: 20, limit_remaining: 15.73, is_free_tier: false };
  R["/api/openrouter/models"] = { models: [
    { id: "anthropic/claude-opus-5.5", name: "Anthropic: Claude Opus 5.5", ctx: 1000000, in: 5, out: 25 },
    { id: "anthropic/claude-sonnet-5.5", name: "Anthropic: Claude Sonnet 5.5", ctx: 1000000, in: 3, out: 15 },
    { id: "z-ai/glm-5.3-flash", name: "Z.ai: GLM 5.3 Flash", ctx: 200000, in: 0.1, out: 0.4 },
    { id: "deepseek/deepseek-v4.1-flash", name: "DeepSeek: V4.1 Flash", ctx: 786432, in: 0.07, out: 0.28 },
    { id: "openrouter/auto", name: "Auto Router", ctx: 2000000, in: null, out: null }] };
  if (params.has("upd")) { R["/api/meta"].build = "demo-1"; R["/api/sessions"].build = "demo-2"; }   // ?upd — вышла новая версия
  if (params.has("tester") || params.has("slink")) {   // ?tester — тестировщик демо-пространства; ?slink — вход по ссылке на него (GAS-38)
    R["/api/meta"].space = { slug: "demo", title: "Демо для бухгалтерии", ready: true }; R["/api/meta"].role = "member"; R["/api/meta"].projects = [];
    if (params.has("slink")) Object.assign(R["/api/meta"], { via: "slink", uid: null, tty: false, slink: { name: "Кафе — показ партнёру", exp: Math.floor(Date.now() / 1000) + 7 * 86400, forever: false, rights: "full", terms_line: true } });
    R["/api/sessions"].cost = { pool: "own", today: { tokens: { in: 0, out: 0, cw: 0, cr: 0 }, total: 0, usd: 9.2 }, budget: demoBud };
    R["/api/sessions"].sessions = [{ id: "t:demo:@1", name: "Сверка счетов", path: "/home/u/demo", branch: "", status: "idle", context: 12, model: "", active: false,
      channel: false, rev: "s", preview: "Реестр готов: 14 документов, у двух нет первички", profile: "openrouter", space: "demo", owner_here: null,
      project: "s:demo:Сверка счетов", title: "Реестр документов за октябрь" }];
  }
  R["/api/cmds"] = { host: "ubuntu", cmds: [{ i: 0, cmd: "npm test", kind: "local", danger: false, sha: "a" },
    { i: 1, cmd: "rm -rf dist && npm run build", kind: "local", danger: true, sha: "b" }, { i: 2, cmd: "brew install jq", kind: "foreign", danger: false, sha: "c" },
    { i: 3, cmd: "keepassxc-cli show -s ~/vault/demo.kdbx Сервисы/почта", kind: "tty", danger: false, sha: "d" }] };
  const key = path.split("?")[0];
  // согласие на подключение (consents.py): в демо — в памяти страницы
  if (key === "/api/consent") {
    demoApi.cons ||= [];
    if (body) { if (body.accepted !== true) return Promise.reject(new Error("отметьте «Понимаю: аккаунт мой, ответственность моя»")); if (!demoApi.cons.includes(body.what)) demoApi.cons.push(body.what); return Promise.resolve({ ok: true, v: "2026-11-24" }); }
    return Promise.resolve({ v: "2026-11-24", title: "Подключение вашего аккаунта", check: "Понимаю: аккаунт мой, ответственность моя", given: [...demoApi.cons], log: [], points: [
      "Вы подключаете свой аккаунт или свой ключ. Пульт не создаёт аккаунты и не делится ими.",
      "Агент в ваших сессиях сможет читать и делать в сервисе то, что разрешает подключение. Отправка людям и платежи — только после вашего «Да» в панели, если сервис это поддерживает.",
      "Аккаунт, ключ и соблюдение правил сервиса — на вас: условия поставщика, законы вашей страны, согласие людей, чью переписку видит агент.",
      "Отключить можно в любой момент в «Подключениях». Дата и версия этого текста сохраняются на сервере пульта."] });
  }
  if (key === "/api/mcp" && /[?&]catalog=1/.test(path)) return Promise.resolve({ ...R["/api/mcp"], servers: null });
  if (key === "/api/mcp" && params.get("mcpslow")) return new Promise((r) => setTimeout(() => r(R["/api/mcp"]), +params.get("mcpslow") || 0));   // демо: статусы — как на сервере, позже
  R["/api/meta"].projects_ui = true;                  // «Проекты» (задача 49): и у тестировщика пространства (GAS-38)
  R["/api/sessions"].sessions.forEach((x) => { if (!x.space) { x.project = "p-" + folder(x.path); x.title = demoTitle(x.id); } });
  if (BIZ) demoBiz(R);
  if (key === "/api/projects" || key.startsWith("/api/project/") || key === "/api/project") return demoProjects(key, path, body, R["/api/sessions"]);
  if (key.startsWith("/api/chat/")) return demoChat(key, body, R["/api/sessions"]);
  if (key === "/api/help/ask") return demoHelp(body);
  if (key.startsWith("/api/repos")) return demoRepos(key, path, body);
  if (key === "/api/ask") return Promise.resolve({ ask: decodeURIComponent(path).includes("@2") && !demoApi.answered && !params.has("first") ? (BIZ && !params.get("ask") ? BIZ_ASK : SIMPLE_DEMO[params.get("ask") || "bash"]) || null : null });
  if (key === "/api/key" && SIM.on) demoApi.answered = Date.now() / 1000;
  if (key === "/api/key" && body?.key === "Escape" && params.get("ask") === "question" && !SIM.on) {   // «Отмена» — вопрос закрыт
    demoApi.toolDone = true; demoApi.scr?.splice(0, demoApi.scr.length, "● Вопрос закрыт", "", "❯ ");
    return Promise.resolve({ lines: demoApi.scr });
  }
  // rev — как у сервера: меняется и когда растёт последний ответ (ход Claude дописывается в журнал по блоку)
  const demoRev = () => "demo0000-" + demoApi.h.length + "-" + (demoApi.h.at(-1)?.text.length || 0);
  if (!demoApi.h) demoApi.h = params.has("first") ? [] : BIZ ? bizHist() : params.get("simple") === "1" ? simpleDemoHist() : [
    { i: 7, role: "user", text: "Сделай панель удобнее: тёмная тема и кнопки диалога", ts: "2026-10-29 09:12" },
    { i: 8, role: "assistant", text: answer, ts: "2026-10-29 09:14" },
    { i: 9, role: "user", text: "Проверь сборку и запусти тесты. Вот что было на сервере:\nLast login: Thu Oct 29 09:18:02 2026 from 203.0.113.11\nWARNING: connection is not using a post-quantum key exchange algorithm.\n$ lsof -i :8443\nCOMMAND   PID    USER   FD   TYPE DEVICE SIZE/OFF NODE NAME\ncaddy   1834 user       7u  IPv6  31337      0t0  TCP *:8443 (LISTEN)\n$ ssh hv uptime\n 09:18:40 up 12 days,  3:02,  1 user,  load average: 0.08, 0.05, 0.01", ts: "2026-10-29 09:20" },
    { i: 10, role: "assistant", text: "Тесты прошли: **58 из 58**. Сборку можно запускать командой ниже.\n\n```bash\nnpm test\n```\n\nПолный отчёт:\n\n```\n" + Array.from({ length: 24 }, (_, k) => `PASS  tests/rooms/case-${String(k + 1).padStart(2, "0")}.test.ts  (${(0.2 + k / 37).toFixed(2)} s)`).join("\n") + "\n```", ts: "2026-10-29 09:21" },
    { i: 11, role: "user", text: "И добавь кнопку обновления", ts: "2026-10-29 09:22", queued: "read" }];
  // &nq=1 — последний ответ с фразами «Можно спросить» и образцом текста (отзыв 22.11, js/nextq.js); &nq=file — ещё
  // ваш снимок без подписи и документ с подписью (строки «Снимок получен» / «Файл получен»)
  if (params.get("nq") && !demoApi.nqAdded) {
    demoApi.nqAdded = true;
    const H = demoApi.h, n = (H.at(-1)?.i || 0) + 1;
    if (params.get("nq") === "file") H.push({ i: n, role: "user", text: "Посмотри файл.\n\nФайл из панели: /home/u/drive/demo/Входящие/таблица-клиентов.png", ts: "2026-10-29 09:23" },
      { i: n + 1, role: "user", text: "Сверь с прошлым месяцем\n\nФайл из панели: /home/u/drive/demo/Входящие/клиенты-октябрь.xlsx", ts: "2026-10-29 09:23" });
    H.push({ i: n + 2, role: "assistant", ts: "2026-10-29 09:24", text: "Нашёл **12 дублей** в таблице клиентов: одинаковые телефоны у разных карточек.\n\nОбразец письма клиенту:\n\n> Здравствуйте! Мы объединили ваши записи — теперь все бонусы на одной карте.\n\nМожно спросить дальше:\n\n- «Сколько дублей нашлось по телефону?»\n- «Покажи дубли списком»\n- «Объедини дубли, но сначала покажи, что изменится»" });
  }
  if (key === "/api/send") {                         // демо: вставка ~0,7 с, потом фазы строки статуса и ответ (&act=stuck — реакции нет)
    const now = new Date().toLocaleString("sv-SE").slice(0, 16), n = demoApi.h.length + 20, stuck = params.get("act") === "stuck" || params.get("act") === "unsent";
    demoApi.run = { w: body.w, t: Date.now() + 700, stuck, unsent: params.get("act") === "unsent" };
    setTimeout(() => demoApi.h.push({ i: n, role: "user", text: body.text, ts: now }), stuck ? 1e9 : 2200);
    if (!stuck) setTimeout(() => demoApi.h.push({ i: n + 1, role: "assistant", ts: now, text: SIM.on ? simpleDemoText().answer : "Это **демо-ответ**. В настоящей панели здесь будет ответ Claude из вашей сессии — с таблицами, кодом и озвучкой." }), 10700);
    return new Promise((ok) => setTimeout(() => ok({ ok: true }), 700));
  }
  if (key === "/api/resend") {                       // демо (&act=unsent): «Отправить» — текст ушёл
    if (demoApi.run) demoApi.run = { ...demoApi.run, unsent: false, stuck: false, t: Date.now() };
    return Promise.resolve({ result: "Отправлено." });
  }
  if (key === "/api/activity") {                     // демо: фазы по времени после отправки; без отправки — по сессии
    const w = new URLSearchParams(path.split("?")[1]).get("w"), now = Date.now() / 1000, r = demoApi.run, base = { now, rev: demoRev(), spinner: "", action: "", tool: "" };
    if (r && r.w === w) {
      const t = (Date.now() - r.t) / 1000, at = r.t / 1000;
      const P = r.unsent ? [[0, "delivered", "Доставлено в чат"], [3, "unsent", "Не отправлено — текст в поле ввода", { action: "enter" }]]
        : r.stuck ? [[0, "delivered", "Доставлено в чат"], [4, "stuck", "Не видно реакции — показать экран?", { action: "screen" }]]
        : [[0, "delivered", "Доставлено в чат"], [1.5, "started", "Взял в работу"], [3, "working", "Читает файл index.html", { tool: "Read", spinner: "Reading… · 1s" }],
           [6, "working", "Выполняет команду: npm test", { tool: "Bash", spinner: "Running… · 2s" }], [10, "done", "Готово"]];
      const [s0, phase, text, extra] = P.filter((x) => x[0] <= t).at(-1);
      return Promise.resolve({ ...base, phase, text, since: at + s0, ...(extra || {}) });
    }
    const t0 = demoApi.t0 ||= now;
    const A = { "@1": { phase: "working", text: "Выполняет команду: npm run test:rooms", tool: "Bash", since: t0 - 42, spinner: "Running…" },
                "@2": demoApi.answered ? { phase: "working", text: "Выполняет команду", tool: "Bash", since: demoApi.answered } : { phase: "waiting", text: "Ждёт вашего ответа", action: "answer", since: t0 - 95 },
                "@3": { phase: "done", text: "Готово", since: t0 - 1500 }, "@4": { phase: "done", text: "Готово", since: t0 - 7200 } };
    return Promise.resolve({ ...base, phase: "idle", text: "", since: 0, ...(A[w] || {}) });
  }
  // сообщения команды (teammsg.py) в чате @1: «Команда» пишет тестировщику — карточкой, не в Claude
  const demoTeamMsgs = (p, t = Date.now() / 1000 - 240) => new URLSearchParams(p.split("?")[1]).get("w") !== "@1" ? [] : demoApi.teamMsgs ||= [
    { id: "dt1", at: t, ts: new Date(t * 1000).toISOString().slice(0, 16).replace("T", " "), from: "Команда", kind: "fixed",
      text: "Исправлено: фото с телефона не уходило в чат. Проверьте, пожалуйста." }];
  if (key === "/api/history" && new URLSearchParams(path.split("?")[1]).get("before")) {   // раньше — по номеру сообщения
    const xs = demoApi.h.filter((m) => m.i < +new URLSearchParams(path.split("?")[1]).get("before"));
    return Promise.resolve({ more: xs.length > 30, rev: demoRev(), items: xs.slice(-30) });
  }
  if (key.startsWith("/api/tty")) return demoTty(key, path, body);
  if (key === "/api/history") return Promise.resolve({ more: demoApi.h.length > 0, rev: demoRev(), items: demoApi.h.slice(-30), team: demoTeamMsgs(path),
    ...(new URLSearchParams(path.split("?")[1]).get("rev") === demoRev() ? { same: true } : {}) });
  if (key === "/api/select" && body.n) {             // демо: ❯ переезжает на пункт; выбор — меню закрывается
    if (body.go && SIM.on) demoApi.answered = Date.now() / 1000;
    if (body.go) demoApi.toolDone = true;            // карточка инструмента (#258) — вопрос закрыт
    if (body.go) return Promise.resolve({ lines: screen.splice(0, screen.length, "● Bash(npm run build)", "  ⎿  готово", "", "❯ ") && screen });
    screen.forEach((l, i) => { const m = l.match(/^ (?:❯|\s) (\d+)\. (.*)$/); if (m) screen[i] = ` ${m[1] === body.n ? "❯" : " "} ${m[1]}. ${m[2]}`; });
    return Promise.resolve({ lines: screen });
  }
  if (key === "/api/confirm/start") return Promise.resolve({ id: "demo", via: "telegram", to: "Telegram", ttl: 600, at: Math.floor(Date.now() / 1000), chat: "Пульт", bot: "example_bot" });
  if (key === "/api/confirm/verify") {               // демо (&confirm): верный код — 123456
    if (body.code !== "123456") return Promise.reject(new Error("неверный код, осталось попыток: 4"));
    demoApi.confirmed = true; return Promise.resolve({ ok: true });
  }
  if (key === "/api/run") {                          // демо: «npm test» — длинный вывод, сборка падает и уходит на разбор
    if (body.i === 1) return Promise.resolve({ code: 1, seconds: 14, cut: false, out: "> build\nsrc/rooms.ts(42,7): error TS2322: Type 'string' is not assignable to type 'number'.", triage: "sent", triage_to: "tgi-0904" });
    const full = Array.from({ length: 400 }, (_, k) => `PASS  tests/case-${k + 1}.test.ts`).join("\n");
    return Promise.resolve({ code: 0, seconds: 3, cut: true, out: full.slice(-600), full, triage: "", triage_to: "" });
  }
  if (key.startsWith("/api/commands")) {            // демо: команды трёх сессий, одна уже выполнена
    demoApi.cl ||= [
      { id: "k0", win: "shop-bot", ts: "2026-11-01 09:30", about: "Собрать образ и выложить", cmd: "docker compose build && docker compose up -d", kind: "local", danger: false, done: null,
        running: new Date(Date.now() - 90000).toISOString().slice(0, 16).replace("T", " ") },
      { id: "k6", win: "gas-pult", ts: "2026-11-01 09:25", about: "Достать пароль почты из KeePassXC", cmd: "keepassxc-cli show -s ~/vault/demo.kdbx Сервисы/почта", kind: "tty", danger: false, done: null },
      { id: "k1", win: "tgi-0904", ts: "2026-11-01 09:21", about: "Прогнать тесты комнат перед сборкой", cmd: "npm test", kind: "local", danger: false, done: null },
      { id: "k2", win: "icon-1146", ts: "2026-11-01 09:05", about: "Пересобрать проект с нуля", cmd: "rm -rf dist && npm run build", kind: "local", danger: true, done: null },
      { id: "k3", win: "gas-pult", ts: "2026-11-01 08:40", about: "перезапуск панели после обновления", cmd: "# перезапуск панели после обновления\nsystemctl --user restart gas-pult-webapp", kind: "local", danger: false,
        done: { code: 0, seconds: 1, at: "2026-11-01 08:42", by: "panel", out: "" } },
      { id: "k4", win: "gas-pult", ts: "2026-11-01 08:31", about: "Проверить правила DNAT на гипервизоре", cmd: "ssh hv 'iptables -t nat -S PREROUTING'", kind: "foreign", danger: false, done: null, manual: { at: "2026-11-01 08:36" } },
      { id: "k5", win: "digest-0716", ts: "2026-10-31 22:10", about: "", cmd: "git status --short", kind: "local", danger: false,
        done: { code: 128, seconds: 0, at: "2026-10-31 22:11", by: "panel", out: "…\nfatal: not a git repository (or any of the parent directories): .git", cut: true, triage: "sent", triage_to: "digest-0716" } }];
    if (path.includes("/output")) return Promise.resolve({ out: Array.from({ length: 300 }, (_, k) => `строка вывода ${k + 1}`).join("\n") + "\nfatal: not a git repository (or any of the parent directories): .git" });
    if (path.includes("/run")) {                    // демо: опасная сборка падает и уходит на разбор, остальное — успех
      const c = demoApi.cl.find((x) => x.id === body.id), bad = c.id === "k2", at = new Date().toISOString().slice(0, 16).replace("T", " ");
      c.running = null; c.done = bad ? { code: 1, seconds: 14, at, by: "panel", out: "> build\nsrc/rooms.ts(42,7): error TS2322: Type 'string' is not assignable to type 'number'.", cut: false, triage: "sent", triage_to: c.win }
        : { code: 0, seconds: 2, at, by: "panel", out: "PASS  58 из 58", cut: false };
      return Promise.resolve({ item: c });
    }
    if (path.includes("/mark")) { const c = demoApi.cl.find((x) => x.id === body.id); c.manual = body.done ? { at: new Date().toISOString().slice(0, 16).replace("T", " ") } : null; return Promise.resolve({ item: c }); }
    return Promise.resolve({ host: "ubuntu", items: demoApi.cl });
  }
  if (key === "/api/hint") return Promise.resolve({ hint: decodeURIComponent(path).includes("@3") ? "Запусти тесты и закоммить" : "" });
  if (key === "/api/models" && body?.base_url !== undefined) { demoApi.gw = body.base_url; return demoApi("/api/meta").then((m) => ({ profiles: m.profiles })); }
  if (key === "/api/tour") {                        // ?demo&tour=1 — предложение тура; отметки — в памяти
    demoApi.tour ||= { business: null, dev: null, at: null };
    if (body) Object.assign(demoApi.tour, { [body.tour]: body.state, at: Date.now() / 1000 | 0 });
    return Promise.resolve({ ...demoApi.tour });
  }
  if (key === "/api/bug") {                         // «Сообщить об ошибке»: никуда не уходит; что пришло — demoApi.bugs (e2e)
    (demoApi.bugs ||= []).push(body);
    const ack = { id: "demo-ack-" + Date.now(), ts: new Date().toISOString().slice(0, 16).replace("T", " "), at: Date.now() / 1000, from: "Команда", kind: "ack", text: "Приняли, сообщим, когда исправим." };
    if (body.w === "@1") demoApi.teamMsgs?.push(ack);   // опрос демо отдаёт его же
    return Promise.resolve({ ok: true, task: "demo-bug", ack });
  }
  if (key === "/api/rename") { (demoApi.names ||= {})[body.w] = body.name; return Promise.resolve({ name: body.name }); }
  if (key === "/api/country" && body) { if (!/^[a-z]{2}$/i.test(body.code || "")) return Promise.reject(new Error("нет такой страны — нужен код из двух букв, например NL")); demoApi.cc = body.code.toUpperCase(); return Promise.resolve({ ...R["/api/country"], chosen: demoApi.cc, need: false }); }
  if (key === "/api/persona") return Promise.resolve(demoUi(body));
  if (key === "/api/team") return Promise.resolve(demoTeam(body));
  if (key === "/api/terms/accept") { demoApi.terms = 1; return Promise.resolve({ ...R["/api/terms"], accepted: true, at: Date.now() / 1000 | 0 }); }
  if (key === "/api/rec/chunk") { demoApi.recN = (demoApi.recN || 0) + 1; return Promise.resolve({ ok: true, have: demoApi.recN }); }   // запись по кускам (22.11)
  if (key === "/api/rec/finish") { demoApi.sttAt = Date.now(); return Promise.resolve({ job: "demo", segs: 2 }); }
  if (key === "/api/rec/drop") return Promise.resolve({ ok: true });
  if (key === "/api/rec/status") return Promise.resolve({ have: 0, bytes: 0, segs: [], missing: [] });
  if (key === "/api/stt" && path.includes("job=1")) { demoApi.sttAt = Date.now(); return Promise.resolve({ job: "demo" }); }   // GAS-34
  if (key === "/api/stt/job") {
    const m = params.get("stt"), done = Date.now() - (demoApi.sttAt || 0) > 2500;
    if (!done || m === "slow") return Promise.resolve({ state: "work" });
    if (m === "fail" || m === "empty") return Promise.resolve({ state: "fail", error: m === "empty" ? "Ничего не расслышал — попробуйте ещё раз" : "распознавание не удалось", kept: true });
    return Promise.resolve({ state: "done", text: "Покажи, что изменилось за сегодня" });
  }
  if (key === "/api/stt") {                          // как на сервере: распознавание занимает секунды; ?stt=empty|slow|fail — ошибки
    const m = params.get("stt"), text = m === "empty" ? "" : "Покажи, что изменилось за сегодня";
    if (m === "slow") return new Promise(() => {});  // ответа нет — сработает таймаут 90 с
    return new Promise((ok, no) => setTimeout(() => m === "fail" ? no(new Error("распознавание не удалось")) : ok({ text }), 2500));
  }
  const askW = (FOCUS || params.has("tester")) && params.get("ask") === "question" ? "@1" : "@2";   // фокус и пространство — их сессия @1
  if (key === "/api/screen") return Promise.resolve({ lines: decodeURIComponent(path).includes(askW) ? screen : ["● Готово", "", "❯ "],
    auth: params.get("auth") ? { service: "notion", url: "https://mcp.notion.com/authorize?…", paste: true } : null,
    login: decodeURIComponent(path).includes("@1") ? DEMO_LOGIN[params.get("login")] || null : null,
    // ?tool=bash — карточка инструмента (#258): разбор как с сервера и команда в target
    ask: !decodeURIComponent(path).includes(askW) || demoApi.toolDone ? null : BIZ && !params.get("ask") && !params.get("tool") ? BIZ_ASK : SIMPLE_DEMO[params.get("tool")]
      ? { ...SIMPLE_DEMO[params.get("tool")], target: "rm -rf build && npm run build\nClean and rebuild the project" } : params.get("ask") === "question" ? SIMPLE_DEMO.question : null });
  if (key === "/api/login/code") { demoApi.loginCode = body?.code || ""; return Promise.resolve({ ok: true }); }
  if (key === "/api/login/check") return Promise.resolve(demoApi.loginCode ? { ok: true, text: "вход выполнен", login: null } : { ok: false, text: "окно всё ещё просит войти" });
  if (key === "/api/login/methods") return Promise.resolve({ telegram: true, owner_code: true, email: true, passkey: true, google: true, yandex: true, invite: true });
  if (key === "/api/invite") return Promise.resolve(params.get("invite") === "bad" ? { ok: false } : { ok: true, guest: true, title: "Планета", kind: params.get("invite") === "device" ? "device" : "invite", name: "Анна",
    ...(params.get("invite") === "named" ? { welcome: true, name: "Алексей", title: "Демо" } : {}) });
  if (key === "/api/invite/check") return /^\s*planeta[\s-]*482157\s*$/i.test(body?.code || "") ? Promise.resolve({ ok: true, guest: true, title: "Планета", kind: "invite" })
    : Promise.reject(new Error("Код не подошёл: проверьте буквы и цифры. Код работает один раз и 24 часа — если он уже использован, попросите новый."));
  if (key === "/api/invite/new" || key === "/api/invite/device") return Promise.resolve({ path: "/invite/demo-AbCdEfGhIjKlMnOpQr", code: "PLANETA-482157", hint: "demo-A", ttl: { "7d": 604800, "30d": 2592000, "90d": 7776000, "365d": 31536000 }[body?.ttl] || 86400,
    ...(key === "/api/invite/new" && body?.uses !== undefined ? { uses: body.uses, access: body.access } : {}) });
  if (key === "/api/route") return Promise.resolve({ route: /сайт|браузер|форм/i.test(body?.text || "") ? { type: "browser", title: "рутина в браузере", profile: "claude", model: "haiku", name: "Haiku 5.5", why: "80/80 и 16/16, ≈ $0.04 за 8 задач" } : null });
  if (key === "/api/messengers" || key.startsWith("/api/messengers/")) return Promise.resolve(demoMsg(key, body || {}));
  if (key === "/api/calendars/keys") return Promise.resolve({ calendars: [{ kind: "google", title: "Google Календарь", on: false }] });
  if (key === "/api/calendars/key") return Promise.resolve({ ok: true, checked: "событий в календаре: 12" });
  if (key === "/api/tts/about") {                     // «Что здесь умеет» → «Прослушать»: в демо — секунда тишины (WAV)
    const n = 8000, b = new DataView(new ArrayBuffer(44 + n)), w = (o, t) => [...t].forEach((c, i) => b.setUint8(o + i, c.charCodeAt(0)));
    w(0, "RIFF"); b.setUint32(4, 36 + n, true); w(8, "WAVEfmt "); b.setUint32(16, 16, true); b.setUint16(20, 1, true); b.setUint16(22, 1, true);
    b.setUint32(24, 8000, true); b.setUint32(28, 8000, true); b.setUint16(32, 1, true); b.setUint16(34, 8, true); w(36, "data"); b.setUint32(40, n, true);
    for (let i = 0; i < n; i++) b.setUint8(44 + i, 128);
    return Promise.resolve(new Blob([b.buffer], { type: "audio/wav" }));
  }
  if (key === "/api/starters") {                       // «Чем вы занимаетесь?» → 3–4 сценария под ответ (19.11)
    const occ = new URLSearchParams(path.split("?")[1] || "").get("occ") || "";
    const all = { "": [["day-plan", "План на день"], ["meeting", "Назначить встречу"], ["mail", "Разобрать почту"], ["client-reply", "Ответить клиенту"],
      ["business-plan", "Бизнес-план"], ["find-doc", "Найти документ"], ["reminder", "Напомнить о деле"]],
      biz: [["money-leaks", "Где утекают деньги"], ["partners-summary", "Сводка для партнёров"], ["mail", "Разобрать почту"], ["week-priorities", "Приоритеты на неделю"]],
      personal: [["official-letter", "Письмо в организацию"], ["trip-plan", "План поездки"], ["contract-check", "Разобраться с договором"], ["reminder", "Напомнить о деле"]],
      family: DEMO_FAMILY };
    const list = all[occ] || all[""];
    return Promise.resolve({ starters: list.map(([id, title]) => ({ id, title })), occ: all[occ] ? occ : "",
      occupations: [["biz", "Руковожу бизнесом"], ["sales", "Продажи и клиенты"], ["accounting", "Бухгалтерия и документы"], ["it", "Разработка и IT"],
        ["study", "Учусь"], ["personal", "Для себя и семьи"], ["family", "Семейная история"]].map(([id, title]) => ({ id, title })) });
  }
  if (key === "/api/starter") {                        // семейная история (22.11) — своим текстом, остальное — «План на день»
    const f = DEMO_FAMILY.find(([id]) => id === body?.id);
    return Promise.resolve({ prompt: f ? `«${f[1]}». Помоги ${f[2]}. Сначала расспроси меня — по одному вопросу за раз…`
      : "«План на день». Помоги составить мне план на сегодня. Сначала расспроси меня — по одному вопросу за раз…" });
  }
  if (key === "/api/link/tg") return Promise.resolve({ id: "demo", link: "https://t.me/", ttl: 300 });
  if (key === "/api/oidc/link") return Promise.resolve({ url: "/api/login/oidc/" + body.provider + "/start?link=demo" });
  if (key.startsWith("/api/oidc")) {                // демо: Google привязан, Яндекс — нет
    demoApi.oidc ||= { google: { enabled: true, title: "Google", linked: true, email: "i***@example.com", at: Date.now() / 1000 - 86400 * 2 | 0 }, yandex: { enabled: true, title: "Яндекс ID", linked: false, email: "", at: null } };
    if (key === "/api/oidc/unlink") Object.assign(demoApi.oidc[body.provider], { linked: false, email: "", at: null });
    return Promise.resolve(demoApi.oidc);
  }
  if (key === "/api/login/passkey/options" || key === "/api/passkeys/options") return Promise.resolve({ id: "demo", options: { challenge: "AAAA", rpId: "localhost", user: { id: "AAAA", name: "demo", displayName: "demo" } } });
  if (key.startsWith("/api/passkeys")) {             // демо: ключ «добавляется» без устройства
    demoApi.pk ||= [{ id: "k1", name: "iPhone", created: Date.now() / 1000 - 86400 * 3 | 0, last_used: Date.now() / 1000 - 3600 | 0 }];
    if (key === "/api/passkeys/add") demoApi.pk.push({ id: "k" + Date.now(), name: body.name, created: Date.now() / 1000 | 0, last_used: null });
    if (key === "/api/passkeys/remove") demoApi.pk = demoApi.pk.filter((k) => k.id !== body.id);
    return Promise.resolve({ enabled: true, keys: demoApi.pk });
  }
  if (key === "/api/login/email/start") return /.+@.+\..+/.test(body?.email || "") ? Promise.resolve({ sent: true, message: "Если адрес привязан к пульту, мы отправили на него код. Он действует 10 минут.", resend_in: 60, ttl: 600 }) : Promise.reject(new Error("Укажите адрес почты целиком, например name@example.com"));
  if (key.startsWith("/api/login/")) return Promise.resolve({ state: "ok" });
  if (key.startsWith("/api/email")) {               // демо: почта привязывается любым кодом из 6 цифр
    demoApi.em ||= { enabled: true, address: "", at: null, second_factor: false, notify: false, resend_in: 60, ttl: 600 };
    const e = demoApi.em;
    if (key === "/api/email/bind" && !/.+@.+\..+/.test(body?.email || "")) return Promise.reject(new Error("Укажите адрес почты целиком, например name@example.com"));
    if (key === "/api/email/confirm") { if (!/^\d{6}$/.test(body?.code || "")) return Promise.reject(new Error("Введите 6 цифр из письма.")); Object.assign(e, { address: body.email.toLowerCase(), at: Date.now() / 1000 | 0 }); }
    if (key === "/api/email/remove") Object.assign(e, { address: "", at: null, second_factor: false, notify: false });
    if (key === "/api/email/options") Object.assign(e, body);
    return Promise.resolve(key === "/api/email/bind" ? { sent: true, to: body.email, resend_in: 60, ttl: 600 } : { ...e });
  }
  return Promise.resolve(R[key] || { ok: true });
}

// Задачи владельца (#203) в демо: примеры всех типов действий, всё — в памяти страницы.
function demoTaskList() {
  return demoApi.tasks ||= [
    { id: "t1", title: "Выбрать цену пилота для клиента", kind: "decision", status: "waiting", urgent: true, important: true, question: "Цена пилота на 4 недели?",
      options: ["50 тыс. ₽", "80 тыс. ₽", "Обсудить на созвоне"], next: "выбрать вариант — ответ уйдёт в чат", chat: "@1", chat_now: "@1", chat_name: "tgi-0904", by: "агент · штаб", created: Date.now() / 1000 - 3600 },
    { id: "t2", title: "Перезапустить панель после выкладки", kind: "command", status: "todo", urgent: true, important: false, cmd: "systemctl --user restart gas-pult-webapp",
      next: "нажать «Выполнить»", chat: "@2", chat_now: "@2", chat_name: "icon-1146", by: "агент · gas-pult", created: Date.now() / 1000 - 7200 },
    { id: "t3", title: "Позвонить бухгалтеру про акт сверки", kind: "call", status: "todo", urgent: false, important: true, due: "2026-01-15", phone: "+7 900 000-00-00", next: "уточнить дату акта", by: "owner", created: Date.now() / 1000 - 9000 },
    { id: "t4", title: "Написать Ивану про доступ", kind: "write", status: "doing", to: "@ivan_example", draft: "Иван, добрый день! Доступ к пульту открыт — войдите через Telegram.", next: "отправить черновик", by: "агент · штаб", created: Date.now() / 1000 - 600 },
    { id: "t5", title: "Проверить PR с задачами", kind: "check", status: "done", link: "https://github.com/gvriil/gas-pult/pulls", next: "", by: "агент · gas-pult", created: Date.now() / 1000 - 86400, done_at: Date.now() / 1000 - 3000 },
  ];
}
// Квадрант — как на сервере (tasks.quadrant): срок прошёл — срочно; не оценено — 0
function demoQ(t) {
  const today = new Date().toISOString().slice(0, 10), over = !!t.due && t.status !== "done" && t.due < today;
  const u = over ? true : t.urgent, i = t.important;
  if (u == null && i == null) return { q: 0, overdue: over };
  return { q: u && i ? 1 : i ? 2 : u ? 3 : 4, overdue: over };
}
function demoTaskCount() {
  const l = demoTaskList().filter((t) => t.status !== "done");
  return { open: l.length, waiting: l.filter((t) => t.status === "waiting").length, q1: l.filter((t) => demoQ(t).q === 1).length,
    doing: l.filter((t) => t.status === "doing").length,
    urgent: l.filter((t) => demoQ(t).overdue || t.urgent === true || t.status === "waiting").length };
}
// «Компьютеры» в демо: Мак на связи с «Личными данными», Windows не на связи, одно действие ждёт «Да»
function demoBridge(path, body) {
  const now = Date.now() / 1000, st = demoApi.br ||= { devs: [
    { id: "d1", name: "MacBook мамы", os: "darwin", online: true, created: now - 9 * 86400, seen: now - 30, private: true },
    { id: "d2", name: "Рабочий ПК", os: "win32", online: false, created: now - 30 * 86400, seen: now - 2 * 86400 - 3600, private: false }],
    drafts: [{ id: "a1b2c3d4e5f6", summary: "НАЖАТЬ «Отправить» (button) — страница «Новое письмо» https://mail.example.com/compose",
      device: "d1", device_name: "MacBook мамы", created: now - 40, confirmed: false, tool: "browser_click" }] };
  const key = path.split("?")[0];
  if (key === "/api/bridge/devices") return Promise.resolve({ devices: st.devs });
  if (key === "/api/bridge/drafts") return Promise.resolve({ drafts: st.drafts });
  if (key === "/api/bridge/pair") return Promise.resolve({ code: "K7MP4QXR", expires: Math.floor(now + 600) });
  if (key === "/api/bridge/private") { const x = st.devs.find((y) => y.id === body.id); if (x) x.private = body.on !== false; }
  if (key === "/api/bridge/confirm") st.drafts.forEach((x) => { if (x.id === body.id) x.confirmed = true; });
  if (key === "/api/bridge/reject") st.drafts = st.drafts.filter((x) => x.id !== body.id);
  if (key === "/api/bridge/revoke") st.devs = st.devs.filter((x) => x.id !== body.id);
  if (key === "/api/bridge/log") return Promise.resolve({ log: [{ t: now - 120, tool: "browser_navigate", url: "https://mail.example.com/", ok: true }] });
  return Promise.resolve({ ok: true });
}

function demoTasks(path, body) {
  const l = demoTaskList(), t = l.find((x) => x.id === body?.id);
  const QO = { 1: 0, 0: 1, 2: 2, 3: 3, 4: 4 }, SO = { waiting: 0, doing: 1, todo: 2, done: 3 };
  const key = (x) => (x.status === "done" ? 90 : QO[demoQ(x).q] * 10) + SO[x.status];
  if (path === "/api/tasks") return Promise.resolve({ tasks: l.map((x) => ({ ...x, ...demoQ(x) })).sort((a, b) => key(a) - key(b)) });
  if (path === "/api/tasks/add") { const x = { id: "t" + Date.now(), kind: "other", status: "todo", by: "owner", created: Date.now() / 1000, ...body }; l.unshift(x); return Promise.resolve(x); }
  if (path === "/api/tasks/remove") { demoApi.tasks = l.filter((x) => x !== t); return Promise.resolve({ ok: !!t }); }
  if (!t) return Promise.reject(new Error("задачи уже нет"));
  if (path === "/api/tasks/update") {
    if (body.q) Object.assign(body, { urgent: [1, 3].includes(body.q), important: [1, 2].includes(body.q) });
    Object.assign(t, body); if (body.status === "done") t.done_at = Date.now() / 1000; return Promise.resolve(t); }
  if (path === "/api/tasks/run") { t.result = { code: 0, at: Date.now() / 1000 }; return Promise.resolve({ code: 0, seconds: 1, out: "(демо) команда выполнена\n" }); }
  return Promise.resolve({ ok: true });
}

// Вкладки Chrome стола (desktabs.py, 22.11): вымышленные сайты; агент ищет билеты во второй вкладке
const DEMO_SITES = [
  ["T1", "Погода на неделю — Северный Город", "https://weather.example/north", "#2B6CB0"],
  ["T2", "Билеты на поезд: Северный Город — Озёрск", "https://rail.example/search?from=north&to=ozersk", "#C05621", true],
  ["T3", "Сырники: простой рецепт на завтрак", "https://cook.example/syrniki", "#2F855A"],
  ["T4", "Аптека у дома — каталог", "https://apteka.example/catalog", "#6B46C1"],
  ["T5", "Входящие — почта", "https://mail.example/inbox", "#B83280"],
  ["T6", "Расписание автобусов", "https://bus.example/lines/12", "#2C7A7B"]];
const svgEsc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
// Картинка «сайта» (миниатюра вкладки) и, с chrome, — весь стол: полоса вкладок и адресная строка Chrome сверху
function demoSiteSvg(t, w, h, chrome = null) {
  const top = chrome ? 81 : 0, host = (t.url.split("/")[2] || "").replace(/^www\./, ""), blank = t.url === "about:blank";
  let g = `<rect width="${w}" height="${h}" fill="#fff"/>`;
  if (chrome) {
    const n = chrome.length, tw = Math.max(18, (w - 40) / n);
    g += `<rect width="${w}" height="41" fill="#DEE1E6"/><rect y="41" width="${w}" height="40" fill="#fff"/><rect y="80" width="${w}" height="1" fill="#C4C7CC"/>`;
    chrome.forEach((x, i) => { g += `<rect x="${8 + i * tw}" y="${i === 0 ? 6 : 10}" width="${tw - 4}" height="${i === 0 ? 35 : 24}" rx="7" fill="${i === 0 ? "#fff" : "#E8EAED"}"/><circle cx="${8 + i * tw + 10}" cy="24" r="5" fill="${x.c || "#9AA0A6"}"/>`; });
    g += `<rect x="${w - 30}" y="12" width="20" height="20" rx="4" fill="#C4C7CC"/><rect x="70" y="47" width="${w - 110}" height="28" rx="14" fill="#F1F3F4"/>`
      + `<text x="88" y="66" font-family="sans-serif" font-size="13" fill="#3C4043">${svgEsc(t.url.slice(0, Math.floor((w - 140) / 7)))}</text>`
      + `<path d="M18 61h14M18 61l6-6M18 61l6 6" stroke="#5F6368" stroke-width="2" fill="none"/><path d="M50 61h-14M50 61l-6-6M50 61l-6 6" stroke="#BDC1C6" stroke-width="2" fill="none"/>`;
  }
  if (!blank) {
    g += `<rect y="${top}" width="${w}" height="70" fill="${t.c}"/><text x="20" y="${top + 44}" font-family="sans-serif" font-size="22" font-weight="700" fill="#fff">${svgEsc(host)}</text>`
      + `<text x="20" y="${top + 112}" font-family="sans-serif" font-size="24" font-weight="700" fill="#1F2937">${svgEsc(t.title.slice(0, Math.floor(w / 15)))}</text>`;
    for (let y = top + 140, i = 0; y < h - 30; y += 30, i++) {
      g += i % 5 === 3 ? `<rect x="20" y="${y}" width="${w - 40}" height="90" rx="10" fill="${t.c}" opacity=".14"/>` : `<rect x="20" y="${y}" width="${(w - 40) * (0.55 + ((i * 37) % 40) / 100)}" height="12" rx="6" fill="#D1D5DB"/>`;
      if (i % 5 === 3) y += 70;
    }
  }
  return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${g}</svg>`);
}
function demoTabs(path, body) {
  const st = demoApi.dt ||= { n: 6, back: true, fwd: false, tabs: DEMO_SITES.map(([id, title, url, c, agent]) => ({ id, title, url, c, agent: !!agent })) };
  const cur = st.tabs[0], hostOf = (u) => (u.split("/")[2] || "").replace(/^www\./, "");
  if (path === "/api/desktop/tabs") return Promise.resolve({ tabs: st.tabs.map((t, i) => ({ id: t.id, title: t.title, url: t.url, host: hostOf(t.url),
    icon: "", active: i === 0, agent: t.agent })), active: cur?.id || "", back: st.back, fwd: st.fwd, top: params.has("tabs") ? 81 : 0 });
  const t = st.tabs.find((x) => x.id === body?.id) || cur;
  if (path === "/api/desktop/tabs/shot") return Promise.resolve({ id: t.id, img: demoSiteSvg(t, 360, 576), w: 390, h: 624 });
  const op = body?.op;
  if (op === "new") { const x = { id: "T" + ++st.n, title: "Новая вкладка", url: "about:blank", c: "#9AA0A6" }; st.tabs.unshift(x); st.back = st.fwd = false; return Promise.resolve({ ok: true, id: x.id }); }
  if (op === "open") { st.tabs = [t, ...st.tabs.filter((x) => x !== t)]; st.back = t.id !== "T5"; st.fwd = false; }
  if (op === "close") { st.tabs = st.tabs.filter((x) => x !== t); if (!st.tabs.length) st.tabs.push({ id: "T" + ++st.n, title: "Новая вкладка", url: "about:blank", c: "#9AA0A6" }); }
  if (op === "go") {
    let u = String(body.url || "").trim();
    if (!/^https?:\/\//i.test(u)) { if (/^[a-z][a-z0-9+.-]*:/i.test(u) && !/^[\w.-]+:\d+/.test(u)) return Promise.reject(new Error("открыть можно только адрес http:// или https://")); u = "https://" + u; }
    Object.assign(t, { url: u, title: hostOf(u), c: "#4A5568" }); st.back = true; st.fwd = false;
  }
  if (op === "back" || op === "forward") { st.back = op === "forward"; st.fwd = op === "back"; }
  return Promise.resolve({ ok: true, id: t.id });
}

Object.assign(window, { demoBridge, demoTasks, demoTabs, demoSiteSvg, demoTaskCount, DEMO_PERSONAS, demoTeam, demoUi, demoTty, demoTitle, demoProjects, demoChat, demoRepos, demoApi });

// Брифинг (GAS-18): ?demo&brief=first — первый вход с выбором источников; иначе — готовый брифинг на сегодня
function demoBrief(path, body) {
  const g = (demoApi.brief ||= {
    chosen: params.get("brief") !== "first", sources: ["mail", "calendar", "github", "pult"], boxes: ["gmail"], calendars: ["work"],
    schedule: { time: "07:30", days: [0, 1, 2, 3, 4], tz: "", every: "workdays" }, tour: params.get("brief") === "tour" ? null : "done",
    decisions: [
      { text: "[деньги] Ответить ООО «Ромашка»: «Счёт на оплату №118 — срок пятница»", source: { kind: "mail", label: "Gmail · gmail", url: "https://mail.google.com/" }, key: "d1", cat: "money", yes: "откроет письмо в Gmail", act: "open" },
      { text: "PR shop/site#42 — Витрина: новые цены (открыт 3 дн.)", source: { kind: "github", label: "GitHub · shop/site#42", url: "https://github.com/" }, key: "d2", yes: "сольёт PR (после подтверждения)", act: "confirm" },
      { text: "Ждут «да»: выкатить рассылку клиентам в четверг", source: { kind: "handoff", label: "HANDOFF.md · shop" }, key: "d3", yes: "передаст «да» в окно проекта (после подтверждения)", act: "confirm" },
    ],
  });
  if (path === "/api/brief/prefs") { Object.assign(g, { chosen: true, sources: body.sources, boxes: body.boxes, calendars: body.calendars, schedule: { time: body.time, days: body.every === "custom" ? body.days : body.every === "daily" ? [0, 1, 2, 3, 4, 5, 6] : [0, 1, 2, 3, 4], tz: body.tz, every: body.every } }); return Promise.resolve({}); }
  if (path === "/api/brief/act") {
    const d = g.decisions.find((x) => x.key === body.key);
    if (body.act === "yes" && d?.act === "confirm" && !body.confirm) return Promise.resolve({ ask: "(демо) " + d.text + "?" });
    g.decisions = g.decisions.filter((x) => x.key !== body.key);
    return Promise.resolve({ done: body.act === "yes" ? "(демо) сделано" : body.act === "no" ? "Убрал на месяц" : "Вернётся в следующем брифинге", headline: `Ждут вас ${g.decisions.length} реш. Ночью срочного не было.` });
  }
  const n = g.decisions.length;
  return Promise.resolve({
    sel: { sources: g.sources, boxes: g.boxes, calendars: g.calendars, chosen: g.chosen }, schedule: g.schedule, tour: g.tour,
    avail: { boxes: [{ id: "gmail", gmail: true }, { id: "yandex", gmail: false }], calendars: ["work"], linear: true, github: true },
    brief: { at: new Date().toISOString().slice(0, 11) + "07:30", headline: `Ждут вас ${n} ${n === 1 ? "решение" : n < 5 && n ? "решения" : "решений"}. Ночью срочного не было.`,
      today: [{ text: "10:00–10:30 · Планёрка с командой", source: { kind: "calendar", label: "Календарь · work", url: "https://calendar.google.com/" } },
        { text: "15:00–16:00 · Встреча с поставщиком · офис", source: { kind: "calendar", label: "Календарь · work" } }],
      done: [{ text: "Слит PR shop/site#40 — Оплата картой", source: { kind: "github", label: "GitHub · shop/site#40", url: "https://github.com/" } },
        { text: "GAS-12 — Прайс-лист на сайте", source: { kind: "linear", label: "Linear · GAS-12", url: "https://linear.app/" } }],
      failed: [{ text: "PR shop/site#41 — Корзина", why: "CI красный — проверки не прошли", source: { kind: "github", label: "GitHub · shop/site#41", url: "https://github.com/" } }],
      decisions: g.decisions, more: {}, sources: [{ id: "linear", label: "Задачи Linear", state: "none", note: "нет ключа" }] },
  });
}

// Протоколы встреч (владелец 22.11): ?demo&meeting=1 — протокол с оглавлением; ?demo&focus=meeting — вид по ссылке.
// Люди и компания — вымышленные; запись — тишина, собранная в браузере (WAV), чтобы работали плеер и главы.
const DEMO_MT = (() => {
  const t0 = Math.floor(new Date(2026, 10, 22, 10, 30) / 1000), dur = 14 * 60;
  const m1 = { id: "20261122-1030", title: "Открытие второй точки кафе «Ромашка»", started: t0, dur, ready: true, audio: true,
    gist: "Вторую точку открываем 15 декабря, если до 1 декабря подпишем аренду",
    chapters: [{ start: 0, end: 95, topic: "Знакомство и цель встречи" }, { start: 95, end: 310, topic: "Помещение и аренда" },
      { start: 310, end: 520, topic: "Смета ремонта и оборудования" }, { start: 520, end: 700, topic: "Персонал и график найма" },
      { start: 700, end: dur, topic: "Сроки и итоги" }],
    actions: [{ what: "Согласовать с арендодателем договор и каникулы на ремонт", who: "Анна", due: "2026-12-01" },
      { what: "Собрать смету ремонта и оборудования", who: "Борис", due: "2026-11-27" },
      { what: "Разместить вакансии бариста и повара", who: "Вера", due: "", when: "после аренды" }],
    md: "# Открытие второй точки кафе «Ромашка»\n\n**Дата:** 22 ноября 2026 · **Участники:** Анна, Борис, Вера\n\n## Решения\n- [01:40] Помещение на Садовой — основной вариант, запасной — у вокзала.\n- [05:20] Бюджет ремонта — не больше 1,2 млн ₽.\n- [11:50] Открытие — 15 декабря, если аренда подписана до 1 декабря.\n\n## Открытые вопросы\n- Нужна ли летняя веранда в первый сезон?\n\n## Что сделать\n- Анна — договор аренды, до 1 декабря.\n- Борис — смета, до 27 ноября.\n- Вера — вакансии после аренды." };
  const m2 = { id: "20261121-1600", title: "Созвон с поставщиком кофе", started: t0 - 86400, dur: 21 * 60, ready: true, audio: true,
    gist: "Поставщик держит цену до марта при заказе от 40 кг в месяц", chapters: [], actions: [] };
  const m3 = { id: "20261120-0915", title: "Планёрка", started: t0 - 2 * 86400, dur: null, ready: false, audio: false, gist: "", chapters: [], actions: [] };
  return { list: [m1, m2, m3], by: { [m1.id]: m1, [m2.id]: m2, [m3.id]: { ...m3, transcript: "[00:00] (текст) Обсудили график смен на следующую неделю…" } } };
})();
function demoWav(sec) {                                  // тишина 8 кГц, 8 бит: плеер и переходы по главам
  const n = 8000 * sec, b = new ArrayBuffer(44 + n), v = new DataView(b), w = (o, x) => [...x].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF"); v.setUint32(4, 36 + n, true); w(8, "WAVEfmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, 8000, true); v.setUint32(28, 8000, true); v.setUint16(32, 1, true); v.setUint16(34, 8, true); w(36, "data"); v.setUint32(40, n, true);
  new Uint8Array(b, 44).fill(128);
  return new Blob([b], { type: "audio/wav" });
}
async function demoCard(v) {                             // та же раскладка, что meetings.card_svg на сервере
  const e = (x) => esc(x), mark = await fetch("brand/ladeya-mark.svg").then((r) => r.text()).catch(() => "");
  const m = /<svg[^>]*viewBox="([^"]+)"[^>]*>([\s\S]*)<\/svg>/.exec(mark);
  const words = (v.gist || v.title).split(/\s+/), lines = []; let cur = "";
  for (const x of words) { if ((cur + " " + x).trim().length <= 30) cur = (cur + " " + x).trim(); else { lines.push(cur); cur = x; } }
  if (cur) lines.push(cur);
  const big = lines.slice(0, 4), y0 = 250 - (big.length - 1) * 30, f = 'font-family="system-ui, -apple-system, Segoe UI, Roboto, sans-serif"';
  const d = new Date(v.started * 1000), meta = [`${d.getDate()} ${["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"][d.getMonth()]} ${d.getFullYear()}`, v.dur ? Math.round(v.dur / 60) + " мин" : "", v.chapters.length ? "глав: " + v.chapters.length : ""].filter(Boolean).join(" · ");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630"><rect width="1200" height="630" fill="#FFFFFF"/><rect width="16" height="630" fill="#2563EB"/>`
    + `<text x="80" y="100" ${f} font-size="28" font-weight="600" fill="#2563EB">Протокол встречи</text><text ${f} font-size="54" font-weight="700" fill="#111827">${big.map((s, i) => `<tspan x="80" y="${y0 + i * 66}">${e(s)}</tspan>`).join("")}</text>`
    + `<text x="80" y="500" ${f} font-size="30" fill="#4B5563">${e(v.title)}</text><text x="80" y="560" ${f} font-size="28" fill="#5F6672">${e(meta)}</text>`
    + (m ? `<svg x="1000" y="64" width="120" height="100" viewBox="${e(m[1])}">${m[2]}</svg>` : "")
    + `<text x="1120" y="580" text-anchor="end" ${f} font-size="24" font-weight="600" fill="#111827">Лад<tspan fill="#E8421C">э</tspan>я</text></svg>`;   // знак-название: «э» красная
  return new Blob([svg], { type: "image/svg+xml" });
}
function demoMeeting(path, body) {
  const id = new URLSearchParams(path.split("?")[1] || "").get("id") || DEMO_MT.list[0].id, v = DEMO_MT.by[id] || DEMO_MT.list[0];
  const p = path.split("?")[0];
  if (p === "/api/meetings") return Promise.resolve({ meetings: DEMO_MT.list.map(({ md, ...x }) => x) });
  if (p === "/api/meeting") return Promise.resolve({ ...v, links: [] });
  if (p === "/api/mt") return Promise.resolve({ ...DEMO_MT.list[0], exp: Math.floor(Date.now() / 1000) + 30 * 86400 });
  if (p.endsWith("/audio")) return Promise.resolve(demoWav(p === "/api/mt/audio" ? DEMO_MT.list[0].dur : v.dur));
  if (p.endsWith("/card")) return demoCard(p === "/api/mt/card" ? DEMO_MT.list[0] : v);
  if (p === "/api/meeting/share") return Promise.resolve({ url: location.origin + "/#focus=demo-meeting-demo-meeting-demo", id: "f8", exp: Math.floor(Date.now() / 1000) + 30 * 86400, name: v.title, mode: "meeting", max: 50 });
  return Promise.reject(new Error("нет такого метода"));
}
// «Мессенджеры» в демо (js/messengers.js): выбор, вход и QR — на примерах; QR — нарисованный образец, не настоящий
function demoMsg(key, b) {
  const m = demoApi.msg ||= { telegram: { c: false, on: false }, signal: { c: false, on: false }, whatsapp: { c: false, on: false } };
  const txt = { telegram: "Модель будет читать переписку в чатах, которые вы откроете ей. По условиям Telegram для ИИ (п. 1.5 Telegram API Terms) нужно явное согласие собеседников этого чата — спросите их. Отправить сообщение модель может только черновиком и только после вашего «Да» в панели.",
    signal: "Неофициальный способ. Нарушает условия Signal. Номер могут заблокировать. Лучше отдельный номер. Решаете вы.",
    whatsapp: "Неофициальный способ. Нарушает условия WhatsApp. Номер могут заблокировать. Лучше отдельный номер. Решаете вы." };
  const T = { telegram: "Telegram", signal: "Signal", whatsapp: "WhatsApp" };
  if (key === "/api/messengers") return { idle: 600, catalog: [
    { id: "telegram", title: "Telegram", about: "Ваш аккаунт: читать чаты, отвечать — после вашего «Да»", kind: "consent" },
    { id: "signal", title: "Signal", about: "Связанное устройство: читать, отвечать — после вашего «Да»", kind: "risk" },
    { id: "whatsapp", title: "WhatsApp (личный)", about: "Не поддерживается: запрещено правилами WhatsApp", kind: "off" },
    { id: "max", title: "MAX", about: "Только бот организации", kind: "off" }],
    services: Object.keys(T).map((id) => ({ id, title: T[id], consented: m[id].c, connected: m[id].on, who: m[id].on ? "*** 4567" : "", running: false, install: null, text: txt[id], api: m[id].on, allowed: 0 })) };
  const what = key.slice("/api/messengers/".length), svc = what.startsWith("tg/") ? "telegram" : b.svc;
  if (what === "consent") { m[svc].c = b.accepted === true; return { ok: true, consented: m[svc].c }; }
  if (what === "off") { m[svc] = { c: false, on: false }; return { ok: true }; }
  if (what === "tg/login") return { sent: "app" };
  if (what === "tg/code" || what === "tg/password") { m.telegram.on = true; return { ok: true, who: "*** 4567" }; }
  if (what === "link") return { qr: demoQr() };
  if (what === "chats") return { allowed: ["1"], chats: [{ id: "1", name: "Анна (согласна)", kind: "user", unread: 2 }, { id: "2", name: "Семья", kind: "group", unread: 0 }, { id: "3", name: "Новости района", kind: "channel", unread: 5 }] };
  if (what === "allow") return { allowed: b.chats || [] };
  return { ok: true };
}
function demoQr() {                                   // образец «ДЕМО»: узоры по углам и случайные клетки — камера его не прочтёт
  const n = 33, cell = (x, y) => { const f = (a, b) => x >= a && x < a + 7 && y >= b && y < b + 7;
    for (const [a, b] of [[0, 0], [n - 7, 0], [0, n - 7]]) if (f(a, b)) { const dx = x - a, dy = y - b; return dx === 0 || dx === 6 || dy === 0 || dy === 6 || (dx > 1 && dx < 5 && dy > 1 && dy < 5); }
    if ((x < 8 && (y < 8 || y > n - 9)) || (x > n - 9 && y < 8)) return false;
    return ((x * 7 + y * 13 + x * y) % 5) < 2; };
  let r = "";
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) if (cell(x, y)) r += `<rect x="${x}" y="${y}" width="1" height="1"/>`;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="-2 -2 ${n + 4} ${n + 4}" shape-rendering="crispEdges"><rect x="-2" y="-2" width="${n + 4}" height="${n + 4}" fill="#fff"/><g fill="#111">${r}</g><rect x="9" y="13" width="15" height="7" fill="#fff"/><text x="16.5" y="18.4" font-size="5" font-family="sans-serif" font-weight="700" text-anchor="middle" fill="#c00">ДЕМО</text></svg>`;
  return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
}
