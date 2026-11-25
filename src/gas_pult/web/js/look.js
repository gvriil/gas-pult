// Фирменный вид «Ладэи» (штаб 25.11, шаг 2). Фон: пять монолитов знака — едва заметно (3–5 % контраста к фону), только там,
// где нет текста для чтения: главная (список) и «Новый чат». В ленте сообщений фона нет. Красный монолит один раз за
// загрузку «встаёт на место» (transform, 2,4 с), дальше слой неподвижен — без нагрузки; prefers-reduced-motion — сразу
// на месте. Слой — первый ребёнок body (z-index −1: над фоном body, под содержимым).
// Акцент — только главное действие: в вопросе Claude первый вариант («Да, …») — заливка акцентом, остальные нейтральные.
// Часть по требованию (#191): ядро не растёт.
const CSS = `
.bb-bg { position: absolute; inset: 0; z-index: -1; pointer-events: none; overflow: hidden; opacity: 0; transition: opacity .24s ease;
  --bb-mono: #EFEEEA; --bb-red: #F8ECE6; }   /* к фону 1,05:1 — 5 % */
:root[data-theme="dark"] .bb-bg { --bb-mono: #131312; --bb-red: #1C100B; }
body.bb-on .bb-bg { opacity: 1; }
.bb-bg svg { position: absolute; right: max(-6vw, calc(50vw - 640px)); bottom: -4vh; height: min(86vh, 820px); width: auto; }
.bb-bg .m { fill: var(--bb-mono); }
.bb-bg .r { fill: var(--bb-red); transform-box: fill-box; transform-origin: 50% 100%; }
body.bb-on:not(.bb-done) .bb-bg .r { animation: bb-rise 2.4s cubic-bezier(.2,.7,.1,1) .15s both; }
@keyframes bb-rise { from { transform: translate3d(0, 100%, 0); } to { transform: none; } }
@media (prefers-reduced-motion: reduce) { .bb-bg .r { animation: none !important; } .bb-bg { transition: none; } }
.ask .q + button.opt:not([data-esc]) { background: var(--accent-primary); border-color: var(--accent-primary); color: var(--on-accent); font-weight: 600; }
.ask .q + button.opt:not([data-esc]) b { color: inherit; opacity: .8; }
.ask .q + button.opt:not([data-esc]):hover { filter: brightness(.94); }
.act button { color: var(--text-primary); }
/* карточки главной — один раз при загрузке: подъём на 6 px и проявление, 220 мс, лесенкой по 40 мс; потом без движения */
body.lk-intro #home .card { animation: lk-in .22s cubic-bezier(.2,.7,.2,1) both; }
body.lk-intro #home .card:nth-of-type(2) { animation-delay: 40ms; } body.lk-intro #home .card:nth-of-type(3) { animation-delay: 80ms; }
body.lk-intro #home .card:nth-of-type(4) { animation-delay: 120ms; } body.lk-intro #home .card:nth-of-type(n+5) { animation-delay: 160ms; }
/* знак-название «Ладэя»: «э» красная (владелец 25.11) — в шапке, боковой панели и заголовке главной; в обычном тексте нет */
.brand-text .e { -webkit-text-fill-color: #E8421C; color: #E8421C; }
:root[data-theme="dark"] .brand-text .e { -webkit-text-fill-color: #FF5A2D; color: #FF5A2D; }
@keyframes lk-in { from { opacity: 0; transform: translate3d(0, 6px, 0); } to { opacity: 1; transform: none; } }   /* «Ответить» в строке состояния — путь к вопросу, не главное действие */
`;
const SVG = `<svg viewBox="0 0 120 100" preserveAspectRatio="xMaxYMax meet" aria-hidden="true">`
  + `<rect class="m" x="4" y="10" width="18" height="90"/><rect class="m" x="26" y="10" width="18" height="90"/>`
  + `<rect class="m" x="48" y="10" width="18" height="90"/><rect class="m" x="70" y="10" width="18" height="90"/>`
  + `<rect class="r" x="92" y="34" width="18" height="66"/></svg>`;

const want = () => view === "home" || document.body.classList.contains("drafting");

function sync() {
  const on = want(), b = document.body;
  if (on === b.classList.contains("bb-on")) return;
  b.classList.toggle("bb-on", on);
  if (on && !b.dataset.bbRose) {                      // «встаёт» один раз за загрузку страницы
    b.dataset.bbRose = "1";
    setTimeout(() => b.classList.add("bb-done"), 2800);
  }
}

// Знак-название: в элементах .brand-text слово «Ладэя» → «Лад<span class="e">э</span>я». Текст ставит ядро
// (textContent), поэтому следим за изменениями и оборачиваем снова; другой текст (название проекта) не трогаем.
function markWord() {
  for (const el of document.querySelectorAll(".brand-text")) {
    const host = el.querySelector("button") || el;
    if (host.childElementCount === 0 && host.textContent.trim() === "Ладэя") host.innerHTML = 'Лад<span class="e">э</span>я';
  }
}

export function init() {
  if (document.getElementById("bbStyle")) return sync();
  markWord();
  let queued = false;                                 // не чаще раза за кадр: лента чата меняется часто
  new MutationObserver(() => { if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; markWord(); }); } }).observe(document.body, { subtree: true, childList: true, characterData: true,
    attributes: true, attributeFilter: ["class"] });
  if (!document.querySelector("#home .card")) {     // карточек ещё нет — появятся с движением; уже нарисованы — не дёргаем
    document.body.classList.add("lk-intro"); setTimeout(() => document.body.classList.remove("lk-intro"), 1500);
  }
  const s = document.createElement("style"); s.id = "bbStyle"; s.textContent = CSS; document.head.append(s);
  const bg = document.createElement("div"); bg.className = "bb-bg"; bg.innerHTML = SVG;
  document.body.prepend(bg);
  sync();
  // вид меняет show() (атрибут hidden у #home) и черновик (класс drafting у body)
  const mo = new MutationObserver(sync);
  const home = $("home");
  if (home) mo.observe(home, { attributes: true, attributeFilter: ["hidden"] });
  mo.observe(document.body, { attributes: true, attributeFilter: ["class"] });
}
