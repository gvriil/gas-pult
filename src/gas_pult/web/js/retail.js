// Сценарий для ритейла: /?demo=retail (framewatcher и владелец 25.11, QR в колоде). Один учебный заказ за 60 секунд:
// данные входят → агенты работают → человек решает «Да» → результат и личная полка покупателя. Без кода, английского,
// моделей, денег и лимитов; ПДн — маской; внешних действий нет. Название компании — только параметром ссылки (&to=…),
// в репозитории его нет. Часть по требованию (#191): ядро её не качает, стили — здесь.
const CSS = `
#rt { position: fixed; inset: 0; z-index: 70; overflow-y: auto; background: var(--bg-subtle); color: var(--text-primary); }
#rt .rt-bar { position: sticky; top: 0; z-index: 2; background: var(--accent-soft); color: var(--text-primary); text-align: center;
  font-size: 14px; line-height: 1.35; padding: 8px 16px; border-bottom: 1px solid var(--border-subtle); }
#rt .rt-wrap { max-width: 760px; margin: 0 auto; padding: 20px 16px 48px; }
#rt h1 { font-size: 24px; line-height: 1.25; margin: 4px 0 4px; }
#rt .rt-lead { color: var(--text-secondary); margin: 0 0 16px; font-size: 16px; line-height: 1.45; }
#rt .rt-steps { display: flex; gap: 6px; flex-wrap: wrap; margin: 0 0 16px; padding: 0; list-style: none; }
#rt .rt-steps li { font-size: 13px; padding: 5px 10px; border-radius: var(--radius-pill); background: var(--bg-surface);
  color: var(--text-muted); border: 1px solid var(--border-subtle); }
#rt .rt-steps li.on { color: var(--text-primary); border-color: var(--accent-primary); font-weight: 600; }
#rt .rt-card { background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-md);
  padding: 16px; margin: 0 0 14px; box-shadow: var(--shadow-sm); animation: rtIn .35s ease both; }
#rt .rt-card.ask { border-color: var(--status-approval); background: var(--status-approval-bg); }
#rt .rt-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin: 0 0 10px; }
#rt .rt-head h2 { font-size: 18px; margin: 0; line-height: 1.3; }
#rt .rt-n { color: var(--text-muted); font-size: 13px; font-weight: 600; margin: 0 0 4px; }
#rt .rt-st { flex: none; font-size: 13px; font-weight: 600; padding: 4px 10px; border-radius: var(--radius-pill); }
#rt .rt-st.work { color: var(--status-running); background: var(--bg-subtle); }
#rt .rt-st.ask { color: var(--on-approval); background: var(--status-approval); }
#rt .rt-st.done { color: var(--status-success); background: var(--bg-subtle); }
#rt .rt-badges { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 10px; }
#rt .rt-badge { font-size: 13px; padding: 4px 10px; border-radius: var(--radius-pill); background: var(--accent-soft); color: var(--text-primary); }
#rt .rt-msg { background: var(--bg-subtle); border-radius: var(--radius-sm); padding: 10px 12px; margin: 8px 0 0; line-height: 1.45; }
#rt .rt-muted { color: var(--text-secondary); font-size: 14px; line-height: 1.45; margin: 6px 0 0; }
#rt ul.rt-checks { list-style: none; margin: 0; padding: 0; }
#rt ul.rt-checks li { display: flex; gap: 10px; align-items: flex-start; padding: 6px 0; line-height: 1.45; animation: rtIn .3s ease both; }
#rt ul.rt-checks svg { flex: none; width: 22px; height: 22px; stroke: var(--status-success); fill: none; stroke-width: 2.2; margin-top: 1px; }
#rt details { margin: 8px 0 0; }
#rt summary { cursor: pointer; color: var(--accent-primary); font-weight: 600; min-height: 32px; display: flex; align-items: center; }
#rt details ol { margin: 6px 0 0; padding-left: 20px; line-height: 1.5; color: var(--text-secondary); }
#rt .rt-quote { background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 12px; margin: 10px 0; line-height: 1.5; }
#rt .rt-safe { display: flex; gap: 8px; align-items: center; font-weight: 600; margin: 4px 0 12px; }
#rt .rt-safe svg { width: 20px; height: 20px; stroke: currentColor; fill: none; stroke-width: 2; flex: none; }
#rt .rt-btns { display: flex; flex-wrap: wrap; gap: 10px; }
#rt button { font: inherit; font-size: 16px; font-weight: 600; min-height: 48px; padding: 0 18px; border-radius: var(--radius-sm); cursor: pointer;
  border: 1px solid var(--border-subtle); background: var(--bg-surface); color: var(--text-primary); }
#rt button.main { background: var(--accent-primary); color: var(--on-accent); border-color: var(--accent-primary); }
#rt button:focus-visible, #rt summary:focus-visible, #rt a:focus-visible { outline: 3px solid var(--border-focus); outline-offset: 2px; }
#rt .rt-shelf { display: grid; gap: 8px; margin: 10px 0 0; }
#rt .rt-item { display: flex; justify-content: space-between; gap: 10px; align-items: center; padding: 10px 12px; border-radius: var(--radius-sm); background: var(--bg-subtle); }
#rt .rt-item b { font-weight: 600; }
#rt .rt-pilot { font-size: 12px; color: var(--text-muted); white-space: nowrap; }
#rt ol.rt-measure { margin: 6px 0 14px; padding-left: 22px; line-height: 1.6; }
@keyframes rtIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) { #rt .rt-card, #rt ul.rt-checks li { animation: none; } }
@media (min-width: 900px) { #rt .rt-wrap { padding-top: 32px; } #rt h1 { font-size: 30px; } }`;

const ICON = { check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>', lock: '<rect x="5" y="11" width="14" height="9.5" rx="2"/><path d="M8.5 11V8a3.5 3.5 0 0 1 7 0v3"/>' };
const svg = (n) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[n]}</svg>`;
const h = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const slow = !matchMedia("(prefers-reduced-motion: reduce)").matches;
const wait = (ms) => new Promise((r) => setTimeout(r, slow ? ms : 0));

const STEPS = ["Данные входят", "Агенты работают", "Вы решаете", "Результат"];
const CHECKS = ["Проверил заказ и гарантию: покупка 12 дней назад, гарантия действует",
  "Нашёл ответ в инструкции: раздел «Очистка от накипи»",
  "Сверил правило компании: советы по уходу — можно, скидки и возвраты — только с вашего «Да»"];
const RULES = ["Отвечать покупателю на «вы», коротко и по шагам.", "Советы по уходу и инструкции — можно.",
  "Скидки, возвраты и обмен — только после подтверждения сотрудника.", "Телефон и адрес покупателя в ответ не писать."];
const REPLY = "Здравствуйте! Чтобы удалить накипь: налейте в бак средство для очистки с водой, запустите программу «Очистка» " +
  "и через 20 минут промойте чистой водой. Подробно — в инструкции на вашей личной полке. О следующей очистке напомним через 2 месяца.";

let run = 0;
function stepBar(i) { return `<ol class="rt-steps" aria-label="Шаги сценария">${STEPS.map((s, k) => `<li class="${k === i ? "on" : ""}"${k === i ? ' aria-current="step"' : ""}>${k + 1}. ${s}</li>`).join("")}</ol>`; }
function card(n, title, st, body, cls = "") {
  const lab = { work: "В работе", ask: "Требует решения", done: "Выполнено" }[st];
  return `<section class="rt-card ${cls}" data-step="${n}"><p class="rt-n">Шаг ${n} из 4</p><div class="rt-head"><h2>${title}</h2><span class="rt-st ${st}">${lab}</span></div>${body}</section>`;
}
const order = `<p style="margin:0;font-weight:600">Заказ № 10482 · Кофемашина</p>
<div class="rt-badges"><span class="rt-badge">Заказ</span><span class="rt-badge">Личная полка (QR)</span><span class="rt-badge">Чат покупателя</span></div>
<p class="rt-muted">Покупатель: А••• К•••, +7 ••• •••-••-41 · учебный заказ</p>
<div class="rt-msg">«Как удалить накипь? В инструкции не нашла.»</div>`;

async function play(root, me) {
  const box = root.querySelector("#rtFlow"), bar = root.querySelector("#rtBar");
  const alive = () => me === run;
  box.innerHTML = card(1, "Пришёл вопрос покупателя", "done", order);
  await wait(900); if (!alive()) return;
  bar.innerHTML = stepBar(1);
  box.insertAdjacentHTML("beforeend", card(2, "Агенты готовят ответ", "work", `<ul class="rt-checks" id="rtChecks"></ul>
<details><summary>Показать инструкцию компании</summary><ol>${RULES.map((r) => `<li>${h(r)}</li>`).join("")}</ol></details>`));
  for (const c of CHECKS) {
    await wait(800); if (!alive()) return;
    root.querySelector("#rtChecks").insertAdjacentHTML("beforeend", `<li>${svg("check")}<span>${h(c)}</span></li>`);
  }
  const s2 = box.querySelector('[data-step="2"] .rt-st'); s2.className = "rt-st done"; s2.textContent = "Выполнено";
  await wait(700); if (!alive()) return;
  bar.innerHTML = stepBar(2);
  box.insertAdjacentHTML("beforeend", card(3, "Нужно ваше «Да» перед отправкой покупателю", "ask", `<p class="rt-muted" style="margin:0">Кому: А••• К••• · чат покупателя</p>
<div class="rt-quote">${h(REPLY)}</div>
<p class="rt-safe">${svg("lock")}Без вашего подтверждения ничего не уйдёт</p>
<div class="rt-btns"><button class="main" type="button" data-yes>Да, отправить</button><button type="button" data-no>Не отправлять</button></div>`, "ask"));
  const ask = box.querySelector('[data-step="3"]');
  ask.scrollIntoView({ behavior: slow ? "smooth" : "auto", block: "center" });
  ask.onclick = (e) => { const b = e.target.closest("button"); if (b) finish(root, b.hasAttribute("data-yes"), me); };
}

function finish(root, yes, me) {
  if (me !== run) return;
  const box = root.querySelector("#rtFlow"), ask = box.querySelector('[data-step="3"]');
  ask.classList.remove("ask"); ask.querySelector(".rt-btns").remove();
  const st = ask.querySelector(".rt-st"); st.className = "rt-st done"; st.textContent = yes ? "Одобрено" : "Отклонено";
  root.querySelector("#rtBar").innerHTML = stepBar(3);
  const shelf = `<p style="margin:14px 0 0;font-weight:600">Личная полка покупателя · Моя техника</p>
<div class="rt-shelf">
<div class="rt-item"><span><b>Кофемашина</b> · гарантия действует</span><span class="rt-pilot">функции пилота</span></div>
<div class="rt-item"><span><b>Инструкция</b> · раздел «Очистка от накипи»</span><span class="rt-pilot">функции пилота</span></div>
<div class="rt-item"><span><b>Вопрос о товаре</b> · ${yes ? "ответ получен" : "ждёт ответа сотрудника"}</span><span class="rt-pilot">функции пилота</span></div>
<div class="rt-item"><span><b>Обслуживание</b> · ${yes ? "напомним об очистке через 2 месяца" : "напоминание не назначено"}</span><span class="rt-pilot">функции пилота</span></div>
</div>`;
  const text = yes ? "Ответ отправлен покупателю в чат и записан в журнал. Покупатель видит его на своей личной полке."
    : "Ответ не отправлен и записан в журнал как отклонённый. Вопрос вернулся сотруднику поддержки — покупатель пока ждёт.";
  box.insertAdjacentHTML("beforeend", card(4, yes ? "Готово: покупатель получил ответ" : "Остановлено: ответ не ушёл", "done",
    `<p style="margin:0;line-height:1.5">${h(text)}</p><p class="rt-muted">Выполнено · записано в журнал</p>${shelf}`));
  box.insertAdjacentHTML("beforeend", `<section class="rt-card" data-step="end"><h2 style="font-size:18px;margin:0 0 4px">Что измерим в пилоте</h2>
<ol class="rt-measure"><li>Активация личной полки: сколько покупателей открыли её по QR.</li><li>Повторные покупки: аксессуары и обслуживание после покупки.</li>
<li>Нагрузка на поддержку: сколько вопросов закрыто без звонка.</li></ol>
<div class="rt-btns"><button class="main" type="button" data-again>Пройти ещё раз</button><button type="button" data-try>Примерить на себя</button><button type="button" data-full>Полное демо</button></div></section>`);
  const end = box.querySelector('[data-step="4"]');
  end.scrollIntoView({ behavior: slow ? "smooth" : "auto", block: "start" });
  const fin = box.querySelector('[data-step="end"]');
  fin.onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.hasAttribute("data-again")) { root.scrollTop = 0; start(root); }
    else location.href = "/?demo" + (b.hasAttribute("data-try") ? "&simple=0" : "");
  };
}

function start(root) {
  const me = ++run;
  root.querySelector("#rtBar").innerHTML = stepBar(0);
  play(root, me);
}

export function init() {
  if (!document.getElementById("rtCss")) { const st = document.createElement("style"); st.id = "rtCss"; st.textContent = CSS; document.head.append(st); }
  const to = (new URLSearchParams(location.search).get("to") || "").trim().slice(0, 40);
  const root = document.createElement("div");
  root.id = "rt"; root.setAttribute("role", "main");
  root.innerHTML = `<div class="rt-bar">Концепция пилота · учебные данные · подключения к ${to ? h(to) : "вашим системам"} нет</div>
<div class="rt-wrap"><h1>Покупатель купил кофемашину</h1>
<p class="rt-lead">Как агенты помогают после покупки: отвечают на вопрос по инструкции, а отправляет человек — одной кнопкой.</p>
<div id="rtBar"></div><div id="rtFlow" aria-live="polite"></div></div>`;
  document.body.append(root);
  document.title = "Сценарий: после покупки";
  start(root);
}
