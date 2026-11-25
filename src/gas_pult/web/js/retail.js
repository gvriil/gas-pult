// Сценарий для ритейла: /?demo=retail (framewatcher и владелец 25.11, QR в колоде). Дизайн — ТЗ v1.1 25.11 (Linear ×
// Stripe × Shopify + дополнения Gemini): нейтральные поверхности, глубина оттенками и микро-тенью, полупрозрачные границы,
// один акцент для действий, статусы — точкой и словом, Inter, заголовки −0.02em, цифры tabular-nums, кнопки ≥ 52 px,
// касания ≥ 44 px, значки Lucide (штрих 1,75). Один поток за ~5 секунд: вопрос покупателя → агент проверяет (свёрнутый лог)
// → ваше «Да» (белая карточка, янтарная полоса слева) → личная полка покупателя. На ПК — сплит 55/45: слева поток, справа
// макет телефона с полкой, он обновляется после решения. Без кода, английского, моделей, денег и лимитов; ПДн — маской;
// внешних действий нет. Название компании — только параметром ссылки (&to=…), в репозитории его нет.
// Часть по требованию (#191): ядро её не качает; шрифт — своя часть retailfont.js; стили и токены — здесь, под #rt.
const CSS = `
#rt { --bg:#F7F8FA; --surface:#FFFFFF; --surface-2:#F0F3F7; --text:#151922; --text-2:#505A6B; --text-3:#626D7D;
  --line:rgba(21,25,34,.08); --line-2:rgba(21,25,34,.14); --control:#7C8797; --accent:#2454D6; --accent-hover:#1D43B1;
  --accent-soft:#EEF3FF; --on-accent:#FFFFFF; --pending:#B45309; --pending-text:#854D0E; --working:#2454D6; --success:#15803D;
  --success-text:#166534; --neutral:#626D7D; --shadow:0 1px 2px rgba(0,0,0,.04);
  --shadow-md:0 8px 24px rgba(15,23,42,.08); --dur:180ms; --ease:cubic-bezier(.2,.8,.2,1); color-scheme: light; }
#rt[data-t="dark"] { --bg:#10141C; --surface:#171C25; --surface-2:#202632; --text:#F2F4F8; --text-2:#B3BDCC; --text-3:#98A5B8;
  --line:rgba(255,255,255,.08); --line-2:rgba(255,255,255,.14); --control:#77869C; --accent:#8CA9FF; --accent-hover:#A5BAFF;
  --accent-soft:#202E4C; --on-accent:#101828; --pending:#F5C46B; --pending-text:#F5C46B; --working:#A9BFFF; --success:#83D7A4;
  --success-text:#83D7A4; --neutral:#98A5B8; --shadow:0 1px 2px rgba(0,0,0,.2); --shadow-md:0 8px 24px rgba(0,0,0,.32); color-scheme: dark; }
@media (prefers-reduced-motion: reduce) { #rt { --dur: 0ms; } }
#rt { position: fixed; inset: 0; z-index: 70; overflow-y: auto; background: var(--bg); color: var(--text);
  font: 400 16px/24px "Inter RT", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; -webkit-font-smoothing: antialiased; }
#rt *, #rt *::before, #rt *::after { box-sizing: border-box; }
#rt p { margin: 0; }
#rt .rt-num { font-variant-numeric: tabular-nums; }
#rt svg.rt-i { width: 20px; height: 20px; flex: none; fill: none; stroke: currentColor; stroke-width: 1.75; stroke-linecap: round; stroke-linejoin: round; }
#rt svg.rt-i.rt-s { width: 16px; height: 16px; }
/* шапка: логотип, тонкий индикатор шагов, одна строка маркировки */
#rt .rt-top { position: sticky; top: 0; z-index: 3; background: var(--surface); box-shadow: 0 1px 0 var(--line); }
#rt .rt-top-in { height: 56px; display: flex; align-items: center; gap: 10px; padding: 0 20px; max-width: 1200px; margin: 0 auto; }
#rt .rt-logo { display: flex; align-items: baseline; gap: 6px; font-weight: 700; font-size: 18px; letter-spacing: -.02em; }
#rt .rt-e { color: #E8421C; } :root[data-theme="dark"] #rt .rt-e { color: #FF5A2D; }
#rt .rt-by { font-size: 12px; font-weight: 500; color: var(--text-3); letter-spacing: 0; }
#rt .rt-mark { width: 28px; height: 28px; border-radius: 8px; background: var(--text); color: var(--surface); display: grid; place-items: center; font-weight: 700; font-size: 15px; }
#rt .rt-tag { color: var(--text-3); font-size: 14px; }
#rt .rt-count { margin-left: auto; color: var(--text-2); font-size: 14px; font-weight: 500; }
#rt .rt-bar { height: 3px; background: var(--line); }
#rt .rt-bar i { display: block; height: 3px; background: var(--accent); width: 25%; transition: width var(--dur) var(--ease); }
#rt .rt-note { display: flex; gap: 6px; align-items: center; justify-content: center; font-size: 12px; line-height: 16px; color: var(--text-3); padding: 8px 20px 0; text-align: center; }
#rt .rt-note svg.rt-i { width: 14px; height: 14px; }
/* раскладка: телефон — один столбец; ПК — сплит 55/45 */
#rt .rt-grid { max-width: 1200px; margin: 0 auto; padding: 16px 20px 40px; display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; }
#rt .rt-grid > * { min-width: 0; }
#rt h1 { font-size: 28px; line-height: 36px; font-weight: 700; letter-spacing: -.02em; margin: 4px 0 4px; }
#rt h2 { font-size: 20px; line-height: 28px; font-weight: 600; letter-spacing: -.02em; margin: 0; }
#rt h3 { font-size: 16px; line-height: 24px; font-weight: 600; margin: 0 0 8px; }
#rt .rt-lead { color: var(--text-2); }
#rt .rt-card { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 16px; box-shadow: var(--shadow); animation: rtIn var(--dur) var(--ease) both; }
#rt .rt-flow { display: grid; gap: 12px; }
/* вопрос покупателя — как в мессенджере */
#rt .rt-chat-h { display: flex; align-items: center; gap: 10px; }
#rt .rt-ava { width: 36px; height: 36px; border-radius: 50%; background: var(--surface-2); color: var(--text-2); display: grid; place-items: center; font-weight: 600; flex: none; }
#rt .rt-name { font-weight: 600; }
#rt .rt-meta { color: var(--text-3); font-size: 12px; line-height: 16px; }
#rt .rt-in { margin-top: 12px; display: inline-block; max-width: 92%; background: var(--surface-2); border-radius: 16px 16px 16px 4px; padding: 10px 14px; }
#rt .rt-srcs { margin-top: 12px; color: var(--text-3); font-size: 12px; line-height: 16px; display: flex; flex-wrap: wrap; gap: 4px 12px; }
#rt .rt-srcs span { display: inline-flex; gap: 4px; align-items: center; }
#rt .rt-srcs svg.rt-i { width: 14px; height: 14px; }
/* работа агента — приглушённый лог */
#rt .rt-log { border: 1px dashed var(--line-2); border-radius: 12px; padding: 12px 14px; color: var(--text-2); font-size: 13px; line-height: 20px; animation: rtIn var(--dur) var(--ease) both; }
#rt .rt-log-h { display: flex; align-items: center; gap: 8px; min-height: 24px; }
#rt .rt-log b { font-weight: 500; color: var(--text-2); }
#rt .rt-log summary { list-style: none; cursor: pointer; display: flex; align-items: center; gap: 8px; min-height: 44px; margin: -10px 0; }
#rt .rt-log summary::-webkit-details-marker { display: none; }
#rt .rt-log summary .rt-more { margin-left: auto; color: var(--accent); font-weight: 500; }
#rt .rt-log summary b { white-space: nowrap; }
#rt .rt-log summary .rt-st { display: none; }
#rt .rt-note svg.rt-i { display: none; }
#rt .rt-log ul { list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 6px; }
#rt .rt-log li { display: flex; gap: 8px; align-items: flex-start; }
#rt .rt-log li svg.rt-i { width: 16px; height: 16px; margin-top: 2px; color: var(--text-3); }
#rt .rt-log ol { margin: 6px 0 0; padding-left: 20px; }
#rt .rt-log .rt-sub { margin-top: 10px; font-weight: 500; color: var(--text-2); }
#rt .rt-spin { width: 16px; height: 16px; border-radius: 50%; border: 2px solid var(--line-2); border-top-color: var(--working); animation: rtSpin .8s linear infinite; flex: none; }
#rt .rt-ok { color: var(--success); }
/* статус: точка + слово */
#rt .rt-st { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; line-height: 16px; font-weight: 500; color: var(--text-2); white-space: nowrap; }
#rt .rt-st::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--neutral); }
#rt .rt-st.rt-pending { color: var(--pending-text); } #rt .rt-st.rt-pending::before { background: var(--pending); }
#rt .rt-st.rt-working { color: var(--working); } #rt .rt-st.rt-working::before { background: var(--working); }
#rt .rt-st.rt-success { color: var(--success-text); } #rt .rt-st.rt-success::before { background: var(--success); }
/* карточка «Да»: белая, янтарная полоса слева */
#rt .rt-ask { position: relative; padding-left: 19px; scroll-margin-top: 72px; }
#rt .rt-ask::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; border-radius: 12px 0 0 12px; background: var(--pending); }
#rt .rt-ask.rt-yes::before { background: var(--success); } #rt .rt-ask.rt-no::before { background: var(--neutral); }
#rt .rt-ask h2 { margin: 8px 0 4px; }
#rt .rt-to { display: flex; gap: 6px; align-items: center; color: var(--text-2); font-size: 14px; line-height: 20px; }
#rt .rt-out { margin: 14px 0 0 auto; max-width: 94%; width: fit-content; background: var(--accent-soft); color: var(--text); border-radius: 16px 16px 4px 16px; padding: 12px 14px; }
#rt .rt-safe { display: flex; gap: 6px; align-items: center; color: var(--text-3); font-size: 12px; line-height: 16px; margin-top: 12px; }
#rt .rt-safe svg.rt-i { width: 14px; height: 14px; }
#rt button.rt-b { font: inherit; font-weight: 600; font-size: 16px; line-height: 24px; border-radius: 8px; cursor: pointer; width: 100%;
  display: inline-flex; align-items: center; justify-content: center; gap: 8px; padding: 0 20px; transition: background var(--dur) var(--ease); }
#rt button.rt-p { min-height: 52px; background: var(--accent); color: var(--on-accent); border: 0; }
#rt button.rt-p:hover { background: var(--accent-hover); }
#rt button.rt-sec-b { min-height: 48px; background: var(--surface); color: var(--text); border: 1px solid var(--control); }
#rt button.rt-sec-b:hover { background: var(--surface-2); }
#rt button.rt-b:disabled { opacity: .55; cursor: default; }
#rt button:focus { outline: none; }
#rt button:focus-visible, #rt summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
#rt .rt-dock { position: sticky; bottom: 0; z-index: 2; display: grid; gap: 8px; margin: 16px -16px -16px -16px; padding: 12px 16px calc(12px + env(safe-area-inset-bottom)); border-radius: 0 0 12px 0;
  background: var(--surface); box-shadow: 0 -1px 0 var(--line), 0 -8px 24px rgba(15,23,42,.06); }
#rt .rt-done { display: flex; gap: 8px; align-items: flex-start; margin-top: 14px; font-size: 14px; line-height: 20px; color: var(--text-2); }
#rt .rt-done svg.rt-i { margin-top: 2px; }
/* полка покупателя — витрина */
#rt .rt-phone-wrap.rt-wait { display: none; }
#rt .rt-phone-wrap { scroll-margin-top: 72px; }
#rt .rt-cap { color: var(--text-3); font-size: 12px; line-height: 16px; margin: 0 0 8px; }
#rt .rt-shelf { background: var(--surface); border: 1px solid var(--line); border-radius: 20px; overflow: hidden; box-shadow: var(--shadow-md); }
#rt .rt-shelf-top { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; box-shadow: 0 1px 0 var(--line); }
#rt .rt-shelf-top b { font-weight: 600; letter-spacing: -.01em; }
#rt .rt-shelf-top span { color: var(--text-3); font-size: 12px; }
#rt .rt-prod { display: flex; gap: 14px; align-items: center; padding: 16px; }
#rt .rt-art { width: 88px; height: 88px; border-radius: 16px; background: var(--surface-2); display: grid; place-items: center; color: var(--text-2); flex: none; }
#rt .rt-art svg { width: 60px; height: 60px; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
#rt .rt-prod .rt-meta { margin-top: 2px; font-size: 13px; }
#rt .rt-prod .rt-st { margin-top: 8px; }
#rt .rt-news { margin: 0 16px; background: var(--surface-2); border-radius: 12px; padding: 12px 14px; }
#rt .rt-news .rt-meta { margin-bottom: 4px; }
#rt .rt-news p.rt-txt { font-size: 14px; line-height: 20px; }
#rt .rt-shelf .rt-acts { padding: 12px 16px 4px; }
#rt .rt-links { padding: 4px 16px 8px; }
#rt .rt-link { display: flex; align-items: center; gap: 10px; min-height: 48px; color: var(--text); font-size: 14px; line-height: 20px; }
#rt .rt-link + .rt-link { box-shadow: 0 -1px 0 var(--line); }
#rt .rt-link svg.rt-i { color: var(--text-3); }
#rt .rt-link span.rt-d { color: var(--text-3); margin-left: auto; text-align: right; }
#rt .rt-foot { color: var(--text-3); font-size: 11px; line-height: 16px; text-align: center; padding: 8px 16px 12px; }
/* итог пилота */
#rt .rt-final { display: grid; gap: 8px; }
#rt ol.rt-measure { margin: 0; padding-left: 20px; }
#rt ol.rt-measure li + li { margin-top: 6px; }
#rt ol.rt-measure span { color: var(--text-2); }
#rt .rt-final-b { display: grid; gap: 8px; margin-top: 8px; }
#rt .rt-hide { display: none !important; }
@keyframes rtIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
@keyframes rtSpin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { #rt .rt-spin { animation: none; } }
@media (min-width: 1024px) {
  #rt .rt-top-in { padding: 0 32px; }
  #rt .rt-note { padding-top: 10px; }
  #rt .rt-note svg.rt-i { display: block; }
  #rt .rt-log summary .rt-st { display: inline-flex; }
  #rt .rt-grid { grid-template-columns: minmax(0, 55fr) minmax(0, 45fr); gap: 48px; padding: 24px 32px 64px; align-items: start; }
  #rt .rt-main { grid-column: 1; }
  #rt .rt-phone-wrap, #rt .rt-phone-wrap.rt-wait { display: block; grid-column: 2; grid-row: 1 / span 2; position: sticky; top: 96px; }
  #rt .rt-final { grid-column: 1; }
  #rt .rt-phone { width: 360px; margin: 0 auto; padding: 10px; border-radius: 36px; background: var(--surface-2); box-shadow: inset 0 0 0 1px var(--line), var(--shadow-md); }
  #rt .rt-phone .rt-shelf { border-radius: 28px; box-shadow: none; }
  #rt .rt-cap { text-align: center; }
  #rt .rt-dock { position: static; margin: 16px 0 0; padding: 0; box-shadow: none; background: none; grid-template-columns: 1fr auto; }
  #rt .rt-final-b { grid-template-columns: auto auto auto; justify-content: start; }
  #rt .rt-final-b button.rt-b { width: auto; }
}`;

// Значки Lucide (ISC): контуры 24×24
const P = {
  check: '<path d="M20 6 9 17l-5-5"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  lock: '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  pkg: '<path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z"/><path d="M12 22V12"/><path d="m3.3 7 8.7 5 8.7-5"/>',
  qr: '<rect width="5" height="5" x="3" y="3" rx="1"/><rect width="5" height="5" x="16" y="3" rx="1"/><rect width="5" height="5" x="3" y="16" rx="1"/><path d="M21 16h-3a2 2 0 0 0-2 2v3"/><path d="M21 21v.01"/><path d="M12 7v3a2 2 0 0 1-2 2H7"/><path d="M3 12h.01"/><path d="M12 3h.01"/><path d="M12 16v.01"/><path d="M16 12h1"/><path d="M21 12v.01"/><path d="M12 21v-1"/>',
  chat: '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>',
  shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
  book: '<path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>',
  rules: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="m9 15 2 2 4-4"/>',
  cal: '<path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>',
  drop: '<path d="M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5C6 11.1 5 13 5 15a7 7 0 0 0 7 7z"/>',
  send: '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/><path d="m21.854 2.147-10.94 10.939"/>',
  again: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
  user: '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
};
const rtIc = (n, cls = "rt-i") => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${P[n]}</svg>`;
const h = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const motion = !matchMedia("(prefers-reduced-motion: reduce)").matches;
const wait = (ms) => new Promise((r) => setTimeout(r, motion ? ms : 0));
// Кофемашина без конкретной модели: корпус, бак, носик, чашка
const ART = '<svg viewBox="0 0 96 96" aria-hidden="true"><rect x="22" y="10" width="52" height="76" rx="8"/><path d="M22 30h52"/>' +
  '<rect x="34" y="16" width="28" height="8" rx="2"/><path d="M42 30v10h12V30"/><path d="M48 40v6"/><path d="M38 62h20v8a6 6 0 0 1-6 6h-8a6 6 0 0 1-6-6z"/>' +
  '<path d="M58 64h3a3 3 0 0 1 0 6h-3"/><path d="M22 80h52"/></svg>';

const STEPS = ["Данные", "Агенты", "Ваше «Да»", "Результат"];
const st = (k, text) => `<span class="rt-st rt-${k}">${h(text)}</span>`;   // статусы: Требует решения / В работе / Выполнено
const AGENTS = [["shield", "Заказ и гарантия: покупка 12 дней назад, гарантия действует"],
  ["book", "Инструкция: раздел «Очистка от накипи»"],
  ["rules", "Правила компании: советы по уходу — можно; скидки и возвраты — только с вашего «Да»"]];
const RULES = ["Отвечать покупателю на «вы», коротко и по шагам.", "Советы по уходу и инструкции — можно.",
  "Скидки, возвраты и обмен — только после подтверждения сотрудника.", "Телефон и адрес покупателя в ответ не писать."];
const REPLY = "Здравствуйте! Чтобы удалить накипь: налейте в бак средство для очистки с водой, запустите программу «Очистка» " +
  "и через 20 минут промойте чистой водой. Подробно — в инструкции на вашей личной полке. О следующей очистке напомним через 2 месяца.";
// полка после решения: «Да» — свежий ответ; «Не отправлять» — вопрос ждёт сотрудника
const SHELF = { wait: ["Вопрос о товаре", "Ответ готовится — его проверяет сотрудник."], yes: ["Ответ получен", REPLY],
  no: ["Ждёт ответа сотрудника", "Ваш вопрос передан в поддержку. Ответим в чате."] };

let S = { step: 0, run: 0 }, root = null, NOTE = "";
const $r = (sel) => root.querySelector(sel);

function progress(step) {
  S.step = step;
  $r("#rtCount").textContent = `${step + 1} из 4`;
  $r("#rtBar i").style.width = `${(step + 1) * 25}%`;
  $r("#rtBar").setAttribute("aria-label", `Шаг ${step + 1} из 4: ${STEPS[step]}`);
}

function shelf(state) {                               // витрина покупателя: товар, гарантия, свежий ответ, инструкция
  const [title, text] = SHELF[state];
  return `<div class="rt-shelf" aria-label="Личная полка покупателя">
<div class="rt-shelf-top"><b>Моя техника</b><span>Личная полка</span></div>
<div class="rt-prod"><div class="rt-art">${ART}</div><div><h2>Кофемашина</h2><p class="rt-meta rt-num">Заказ № 10482 · куплена 12 дней назад</p>${st("success", "Гарантия действует")}</div></div>
<div class="rt-news"><p class="rt-meta">${state === "yes" ? "Только что · " : ""}${h(title)}</p><p class="rt-txt">${h(text)}</p></div>
<div class="rt-acts"><button class="rt-b rt-sec-b" type="button" tabindex="-1">${rtIc("book")}Открыть инструкцию</button></div>
<div class="rt-links"><div class="rt-link">${rtIc("cal")}Обслуживание<span class="rt-d">${state === "yes" ? "напомним через 2 месяца" : "не назначено"}</span></div>
<div class="rt-link">${rtIc("drop")}Расходники<span class="rt-d">средство и фильтры</span></div></div>
<p class="rt-foot">Функции пилота · учебные данные</p></div>`;
}

async function play() {
  const me = ++S.run, alive = () => me === S.run;
  const flow = $r("#rtFlow");
  progress(0);
  $r("#rtPhone").classList.add("rt-wait"); $r("#rtShelf").innerHTML = shelf("wait"); $r("#rtFinal").classList.add("rt-hide");
  flow.innerHTML = `<div><h1>После покупки</h1><p class="rt-lead">Покупатель спросил о кофемашине. Агент готовит ответ — отправляете вы.</p></div>
<section class="rt-card" aria-label="Вопрос покупателя"><div class="rt-chat-h"><div class="rt-ava">А</div><div><p class="rt-name">А••• К•••</p>
<p class="rt-meta rt-num">Чат покупателя · +7 ••• •••-••-41</p></div></div>
<p class="rt-in">Как удалить накипь? В инструкции не нашла.</p>
<p class="rt-srcs"><span>${rtIc("pkg")}Заказ</span><span>${rtIc("qr")}Личная полка (QR)</span><span>${rtIc("chat")}Чат покупателя</span></p></section>`;
  await wait(600); if (!alive()) return;
  progress(1);
  flow.insertAdjacentHTML("beforeend", `<div class="rt-log" id="rtLog"><div class="rt-log-h"><span class="rt-spin" aria-hidden="true"></span>
<b class="rt-num">Агент проверяет заказ № 10482 и инструкцию…</b><span style="margin-left:auto">${st("working", "В работе")}</span></div><ul id="rtSteps"></ul></div>`);
  for (const [i, t] of AGENTS) {
    await wait(500); if (!alive()) return;
    $r("#rtSteps").insertAdjacentHTML("beforeend", `<li>${rtIc(i)}<span>${h(t)}</span></li>`);
  }
  await wait(400); if (!alive()) return;
  $r("#rtLog").outerHTML = `<details class="rt-log" id="rtLog"><summary>${rtIc("check", "rt-i rt-s rt-ok")}<b>Агент проверил 3 источника</b>
${st("success", "Выполнено")}<span class="rt-more">Подробнее</span></summary><ul>${AGENTS.map(([i, t]) => `<li>${rtIc(i)}<span>${h(t)}</span></li>`).join("")}</ul>
<p class="rt-sub">Инструкция компании</p><ol>${RULES.map((r) => `<li>${h(r)}</li>`).join("")}</ol></details>`;
  progress(2);
  flow.insertAdjacentHTML("beforeend", `<section class="rt-card rt-ask" id="rtAsk" aria-label="Нужно ваше решение">${st("pending", "Требует решения")}
<h2>Отправить ответ покупателю?</h2><p class="rt-to">${rtIc("user", "rt-i rt-s")}Кому: А••• К••• · чат покупателя</p>
<p class="rt-out">${h(REPLY)}</p>
<p class="rt-safe">${rtIc("lock")}Без вашего подтверждения ничего не уйдёт</p>
<div class="rt-dock" id="rtDock"><button class="rt-b rt-p" type="button" data-yes>${rtIc("send")}Да, отправить покупателю</button>
<button class="rt-b rt-sec-b" type="button" data-no>Не отправлять</button></div></section>`);
  if (!matchMedia("(min-width: 1024px)").matches) $r("#rtAsk").scrollIntoView({ behavior: motion ? "smooth" : "auto", block: "start" });
  const once = (yes) => () => { root.querySelectorAll("#rtDock button").forEach((b) => { b.disabled = true; }); decide(yes, me); };
  $r("[data-yes]").onclick = once(true); $r("[data-no]").onclick = once(false);
}

function decide(yes, me) {
  if (me !== S.run) return;
  progress(3);
  const ask = $r("#rtAsk");
  ask.classList.add(yes ? "rt-yes" : "rt-no");
  ask.querySelector(".rt-st").outerHTML = yes ? st("success", "Выполнено · отправлено") : st("neutral", "Не отправлено");
  $r("#rtDock").outerHTML = `<p class="rt-done">${rtIc(yes ? "check" : "info", "rt-i rt-s" + (yes ? " rt-ok" : ""))}${yes
    ? "Ответ у покупателя в чате и на личной полке. Записано в журнал."
    : "Ответ не ушёл. Вопрос вернулся сотруднику поддержки. Записано в журнал."}</p>`;
  $r("#rtShelf").innerHTML = shelf(yes ? "yes" : "no");
  const wrap = $r("#rtPhone"); wrap.classList.remove("rt-wait");
  $r("#rtFinal").classList.remove("rt-hide");
  if (!matchMedia("(min-width: 1024px)").matches) wrap.scrollIntoView({ behavior: motion ? "smooth" : "auto", block: "start" });
}

export async function init() {
  if (!document.getElementById("rtCss")) { const s = document.createElement("style"); s.id = "rtCss"; s.textContent = CSS; document.head.append(s); }
  part("retailfont").then((m) => m.init()).catch(() => {});        // Inter — своя часть; нет сети — системный шрифт
  const q = new URLSearchParams(location.search), to = (q.get("to") || "").trim().slice(0, 40);
  NOTE = `Концепция пилота · учебные данные · подключения к ${to || "вашим системам"} нет`;
  root = document.createElement("div");
  root.id = "rt"; root.dataset.t = q.get("theme") === "dark" ? "dark" : "light";   // для QR — светлая (ТЗ v1)
  root.innerHTML = `<header class="rt-top"><div class="rt-top-in"><div class="rt-logo"><span>Лад<span class="rt-e">э</span>я</span><span class="rt-by">by Botsmith</span></div>
<span class="rt-tag">Демо · 1 мин</span><span class="rt-count rt-num" id="rtCount"></span></div>
<div class="rt-bar" id="rtBar" role="img"><i></i></div></header>
<p class="rt-note">${rtIc("info")}${h(NOTE)}</p>
<div class="rt-grid"><main class="rt-main"><div class="rt-flow" id="rtFlow" aria-live="polite"></div></main>
<aside class="rt-phone-wrap rt-wait" id="rtPhone"><p class="rt-cap">Так видит покупатель</p><div class="rt-phone"><div id="rtShelf"></div></div></aside>
<section class="rt-card rt-final rt-hide" id="rtFinal"><h3>Что измерим в пилоте</h3>
<ol class="rt-measure"><li>Активация личной полки <span>— сколько покупателей открыли её по QR</span></li>
<li>Повторные покупки <span>— аксессуары и обслуживание после покупки</span></li>
<li>Нагрузка на поддержку <span>— сколько вопросов закрыто без звонка</span></li></ol>
<div class="rt-final-b"><button class="rt-b rt-p" type="button" data-again>${rtIc("again")}Пройти ещё раз</button>
<button class="rt-b rt-sec-b" type="button" data-try>Примерить на себя</button><button class="rt-b rt-sec-b" type="button" data-full>Полное демо</button></div></section></div>`;
  document.body.append(root);
  document.body.style.overflow = "hidden";
  document.title = "Ладэя";
  $r("[data-again]").onclick = () => { root.scrollTop = 0; play(); };
  $r("[data-try]").onclick = () => { location.href = "/?demo&simple=0"; };
  $r("[data-full]").onclick = () => { location.href = "/?demo"; };
  play();
}
