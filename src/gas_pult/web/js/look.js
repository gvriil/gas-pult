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
/* «э» в «Ладэя» (любой падеж) — красная везде (владелец 25.11): мелкий текст на светлом — #C2361A (AA), знак-название
   крупно — #E8421C, на тёмном — #FF5A2D. Обёртку ставит сервер (brand.paint_html) и paintText ниже — для нового текста */
.e { color: #C2361A; }
.brand-text .e, .lg-brand .e { -webkit-text-fill-color: #E8421C; color: #E8421C; }
:root[data-theme="dark"] .e, :root[data-theme="dark"] .brand-text .e { -webkit-text-fill-color: #FF5A2D; color: #FF5A2D; }
/* английский знак-название (вариант B): «ladeya» строчными, «e» красная и зеркальная; в тексте — «Ladeya» (копирование) */
.wm-en { text-transform: lowercase; }
.wm-en .em { display: inline-block; transform: scaleX(-1); -webkit-text-fill-color: #E8421C; color: #E8421C; }
:root[data-theme="dark"] .wm-en .em { -webkit-text-fill-color: #FF5A2D; color: #FF5A2D; }
/* телефон (обзор 25.11): в верхней шапке тесно — знак остаётся в боковой панели и на входе, название — целиком */
@media (max-width: 420px) { .top .tmark { display: none !important; } #title.brand-text { overflow: visible; text-overflow: clip; } }
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

// «э» в «Ладэя» — красная везде (владелец 25.11): любой текст страницы — словари, чат, тур, подсказки, демо — в любом
// падеже. Узел текста режем на месте (splitText): прежний узел остаётся первым ребёнком — ядро (setHTML) не считает
// элемент изменённым и не перерисовывает. Поля ввода, скрипты, стили и уже обёрнутое не трогаем.
const WORD = /(?<![А-Яа-яЁё])Лад(?=э(?:я|и|е|ю|ей)(?![А-Яа-яЁё]))/g;
const SKIP = "script,style,textarea,input,title,.e,[contenteditable]";
function paintText(root) {
  if (!root || root.nodeType === 3 && !(root = root.parentElement)) return;
  if (root.nodeType !== 1 || root.closest?.(SKIP)) return;
  const tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, { acceptNode: (n) => n.data.includes("Ладэ")
    && !n.parentElement.closest(SKIP) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT });
  const hits = []; while (tw.nextNode()) hits.push(tw.currentNode);
  for (let n of hits) {
    WORD.lastIndex = 0;
    let m;
    while ((m = WORD.exec(n.data))) {
      const e = n.splitText(m.index + 3), rest = e.splitText(1), span = document.createElement("span");
      span.className = "e"; e.replaceWith(span); span.append(e);
      n = rest; WORD.lastIndex = 0;
    }
  }
}
const WM_EN = '<span class="wm-en" aria-label="Ladeya">Lad<span class="em">e</span>ya</span>';   // = brand.WORDMARK_EN
function markEn() {                                 // знак-название на английском — только в .brand-text, не в тексте
  const en = LANG === "en";                          // боковая панель пишет название по-русски и в английском — знак по языку
  for (const el of document.querySelectorAll(".brand-text")) {
    const host = el.querySelector("button") || el, t = host.textContent.trim();
    if (host.querySelector(".wm-en") || !(t === "Ladeya" || (en && t === "Ладэя"))) continue;
    host.innerHTML = WM_EN;
  }
}
const markWord = () => { markEn(); paintText(document.body); };   // всё — один раз при загрузке

export function init() {
  if (document.getElementById("bbStyle")) return sync();
  markWord();
  let queued = new Set();                             // только изменённые места, не чаще раза за кадр: лента меняется часто
  new MutationObserver((list) => {
    const first = !queued.size;
    for (const r of list) {
      if (r.type === "characterData") queued.add(r.target);
      else for (const x of r.addedNodes) queued.add(x);
    }
    if (first && queued.size) requestAnimationFrame(() => { const q = [...queued]; queued = new Set(); q.forEach(paintText); markEn(); });
  }).observe(document.body, { subtree: true, childList: true, characterData: true });
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
