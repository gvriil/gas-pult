// Экран входа «Ладея» (владелец 25.11 через штаб: «уровня лучших студий», «магия, но сдержанно»; основа — эталон Gemini,
// фон — пять монолитов знака за матовым стеклом). Только экран входа: класс body.lg-look живёт, пока #login виден.
// Палитра знака: графит #111111, тёплый белый #F4F4F2, акцент #E8421C (на тёмном #FF5A2D); синего нет.
// Движение — только transform: красный монолит один раз «встаёт на место», дальше едва заметный дрейф 36 с;
// prefers-reduced-motion — без движения. Зерно и виньетка — статичные. Часть по требованию (#191): ядро не растёт.
const MARK = `<svg viewBox="0 0 120 100" aria-hidden="true"><g fill="currentColor"><rect x="4" y="10" width="18" height="80"/>`
  + `<rect x="26" y="10" width="18" height="80"/><rect x="48" y="10" width="18" height="80"/><rect x="70" y="10" width="18" height="80"/></g>`
  + `<rect x="92" y="34" width="18" height="56" fill="var(--lg-accent)"/></svg>`;
const SUN = '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>';
const MOON = '<path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401"/>';
// зерно: шум SVG один раз в картинку фона — не анимируется, не пересчитывается
const GRAIN = "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160">'
  + '<filter id="n"><feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" stitchTiles="stitch"/>'
  + '<feColorMatrix values="0 0 0 0 .5  0 0 0 0 .5  0 0 0 0 .5  0 0 0 .55 0"/></filter><rect width="160" height="160" filter="url(#n)"/></svg>');

const CSS = `
body.lg-look { --lg-bg: #F4F4F2; --lg-glass: rgba(255,255,255,.72); --lg-text: #111111; --lg-text2: #55544E;
  --lg-border: rgba(17,17,17,.12); --lg-accent: #E8421C; --lg-accent-h: #D13714; --lg-accent-a: #B82D0E;
  --lg-mono: #111111; --lg-mono-o: .9; --lg-shine: rgba(255,255,255,.9); --lg-field: rgba(255,255,255,.6);
  --lg-font: "Golos Ladeya", system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--lg-bg); color: var(--lg-text); }
:root[data-theme="dark"] body.lg-look { --lg-bg: #0C0C0B; --lg-glass: rgba(20,20,18,.66); --lg-text: #F4F4F2;
  --lg-text2: #A3A29B; --lg-border: rgba(244,244,242,.12); --lg-accent: #FF5A2D; --lg-accent-h: #FF7048;
  --lg-accent-a: #E04820; --lg-mono: #2A2A27; --lg-mono-o: 1; --lg-shine: rgba(255,255,255,.07); --lg-field: rgba(0,0,0,.25); }
body.lg-look header#top { display: none; }
body.lg-look main { background: transparent; }
.lg-bg { position: fixed; inset: 0; z-index: 0; overflow: hidden; pointer-events: none; display: none; }
body.lg-look .lg-bg { display: block; }
.lg-mono { position: absolute; right: max(-4vw, calc(50vw - 600px)); bottom: -6vh; width: min(140vw, 1200px);
  height: min(112vh, 1000px); display: flex; gap: 3.3%; align-items: flex-end;
  animation: lg-drift 36s steps(36) infinite alternate; will-change: transform; }   /* шаг раз в секунду: стекло
  пересчитывает размытие раз в секунду, а не 60 раз (замер 25.11: плавный дрейф — 41–77 % ядра, шагами — см. PR) */
.lg-mono i { flex: 1; height: 80%; background: var(--lg-mono); opacity: var(--lg-mono-o); }
.lg-mono i.r { height: 56%; background: var(--lg-accent); opacity: 1; transform-origin: 50% 100%;
  animation: lg-rise 2.6s cubic-bezier(.2,.7,.1,1) .2s both; }
.lg-grain { position: absolute; inset: 0; background: url("${GRAIN}"); opacity: .06; mix-blend-mode: multiply; }
:root[data-theme="dark"] .lg-grain { opacity: .09; mix-blend-mode: screen; }
.lg-vig { position: absolute; inset: 0; background: radial-gradient(ellipse at 50% 42%, transparent 55%, rgba(0,0,0,.10) 100%); }
:root[data-theme="dark"] .lg-vig { background: radial-gradient(ellipse at 50% 42%, transparent 50%, rgba(0,0,0,.55) 100%); }
@keyframes lg-rise { from { transform: translate3d(0, 104%, 0); } to { transform: none; } }
@keyframes lg-drift { from { transform: translate3d(-1.2%, 0, 0); } to { transform: translate3d(1.2%, -1.5%, 0); } }
@media (prefers-reduced-motion: reduce) { .lg-mono, .lg-mono i.r { animation: none; } }

body.lg-look #login { position: relative; z-index: 1; min-height: 100dvh; display: grid; place-items: center; padding: 20px 16px;
  font-family: var(--lg-font); }
body.lg-look #login .panel { width: 100%; max-width: 400px; margin: 0; padding: 24px 24px 20px; background: var(--lg-glass);
  border: 1px solid var(--lg-border); border-radius: 16px; color: var(--lg-text);
  -webkit-backdrop-filter: blur(24px) saturate(1.1); backdrop-filter: blur(24px) saturate(1.1);
  box-shadow: inset 0 1px 0 var(--lg-shine), 0 24px 48px rgba(0,0,0,.16); }
body.lg-look #login .lmark { display: none; }
.lg-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 0 0 28px; }
.lg-brand { display: flex; align-items: center; gap: 10px; font: 600 17px/1 var(--lg-font); letter-spacing: -.01em; }
.lg-brand svg { width: 29px; height: 24px; color: var(--lg-text); }
.lg-ctrl { display: flex; align-items: center; gap: 8px; }
body.lg-look #login .lg-ctrl .scn-opts { margin: 0; gap: 4px; }
body.lg-look #login .lg-ctrl .scn-opts button { min-height: 36px; min-width: 40px; padding: 0 9px; border-radius: 8px;
  font: 500 0/1 var(--lg-font); background: transparent; color: var(--lg-text2); border: 1px solid var(--lg-border); }
body.lg-look #login .lg-ctrl .scn-opts button::after { content: attr(data-lang); font-size: 13px; text-transform: uppercase;
  letter-spacing: .04em; }   /* «RU» / «EN»: полное название остаётся текстом кнопки для чтения с экрана */
body.lg-look #login .lg-ctrl .scn-opts button[aria-pressed="true"], body.lg-look #login .lg-ctrl .scn-opts button.on {
  color: var(--lg-text); border-color: var(--lg-text2); background: transparent; }
.lg-theme { width: 36px; height: 36px; display: grid; place-items: center; border-radius: 8px; border: 1px solid var(--lg-border);
  background: transparent; color: var(--lg-text2); cursor: pointer; padding: 0; }
.lg-theme:hover { color: var(--lg-text); border-color: var(--lg-text2); }
.lg-theme svg { width: 18px; height: 18px; }
body.lg-look #login h2 { font: 600 28px/1.15 var(--lg-font); letter-spacing: -.025em; margin: 0 0 8px !important; color: var(--lg-text); }
body.lg-look #login .note, body.lg-look #login .hint, body.lg-look #login label { color: var(--lg-text2); }
body.lg-look #login h2 + .note { font-size: 15px; line-height: 1.45; margin: 0 0 24px !important; }
body.lg-look #login .btn { width: 100%; min-height: 52px; border-radius: 10px; font: 600 15px/1.2 var(--lg-font); margin: 0 0 10px;
  background: var(--lg-accent); color: #111111; border: 0; box-shadow: none; transition: background .15s, transform .1s; }
body.lg-look #login .btn:hover { background: var(--lg-accent-h); }
body.lg-look #login .btn:active { background: var(--lg-accent-a); transform: scale(.985); }
body.lg-look #login .btn.ghost { background: transparent; color: var(--lg-text); border: 1px solid var(--lg-border); }
body.lg-look #login .btn.ghost:hover { background: rgba(128,128,128,.08); }
body.lg-look #login .btn:focus-visible, body.lg-look #login .linkbtn:focus-visible, .lg-theme:focus-visible,
body.lg-look #login .lg-ctrl button:focus-visible { outline: 2px solid var(--lg-accent); outline-offset: 2px; }
body.lg-look #login input { min-height: 48px; border-radius: 10px; border: 1px solid var(--lg-border); background: var(--lg-field);
  color: var(--lg-text); font-family: inherit; }
body.lg-look #login input:focus { outline: 2px solid var(--lg-accent); outline-offset: 0; border-color: transparent; }
body.lg-look #login .login-links { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px 12px; margin: 14px 0 0;
  padding: 16px 0 0; border-top: 1px solid var(--lg-border); }
body.lg-look #login .linkbtn { font: 500 13px/1.3 var(--lg-font); color: var(--lg-text2); text-decoration: none; padding: 4px 0; }
body.lg-look #login .linkbtn:hover { color: var(--lg-text); }
`;

const dark = () => document.documentElement.dataset.theme === "dark";

function paintTheme(b) {
  const d = dark(), t = d ? LT("theme.to.light", "Светлая тема") : LT("theme.to.dark", "Тёмная тема");
  b.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d ? SUN : MOON}</svg>`;
  b.setAttribute("aria-label", t); b.title = t;
}

function build() {
  const panel = document.querySelector("#login > .panel");
  if (!panel || panel.querySelector(".lg-top")) return;
  const top = document.createElement("div"); top.className = "lg-top";
  top.innerHTML = `<div class="lg-brand">${MARK}<span>${esc(brandName())}</span></div><div class="lg-ctrl"></div>`;
  const ctrl = top.querySelector(".lg-ctrl"), lang = $("loginLang");
  if (lang) ctrl.append(lang);                              // тот же переключатель языка — переносим, обработчики на месте
  const tb = document.createElement("button"); tb.type = "button"; tb.className = "lg-theme";
  tb.onclick = () => { store("theme", dark() ? "light" : "dark"); applyTheme(); };
  ctrl.append(tb); paintTheme(tb);
  new MutationObserver(() => paintTheme(tb)).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  panel.prepend(top);
  const bg = document.createElement("div"); bg.className = "lg-bg"; bg.setAttribute("aria-hidden", "true");
  bg.innerHTML = `<div class="lg-mono"><i></i><i></i><i></i><i></i><i class="r"></i></div><div class="lg-grain"></div><div class="lg-vig"></div>`;
  document.body.prepend(bg);
}

export function init() {
  if (!document.getElementById("lgLook")) {
    const s = document.createElement("style"); s.id = "lgLook"; s.textContent = CSS; document.head.append(s);
  }
  part("golosfont").then((m) => m.init()).catch(() => {});      // нет сети — системный шрифт, вход работает
  build();
  const login = $("login"), on = () => document.body.classList.toggle("lg-look", !!login && !login.hidden);
  on();
  if (login && !login.dataset.lgWatch) {
    login.dataset.lgWatch = "1";
    new MutationObserver(on).observe(login, { attributes: true, attributeFilter: ["hidden"] });
  }
}
