// Увеличение ленты жестом — часть по требованию (#191). Владелец 16.11: «нужен зум, как будто мы картинку приближаем,
// а не размер шрифта через плюс/минус». Щипок (телефон) и Ctrl + колесо / щипок трекпада (компьютер) увеличивают ленту
// как картинку — с центром в точке жеста; по увеличенной ленте двигаются пальцем (обычная прокрутка по обеим осям);
// двойной тап (двойной клик) — снова 100 %. Шапка и поле ввода не масштабируются: увеличивается только содержимое
// ленты (#content, свойство CSS zoom — оно меняет раскладку, поэтому прокрутка доходит до краёв увеличенного).
// Страницу целиком не масштабируем (maximum-scale=1): каркас с полем ввода и клавиатурой iOS остаётся на месте.
// Жесты: iOS (Safari, Telegram) — gesturestart/change/end, остальные — два пальца. Экран Ubuntu (.desk) — свой зум.
// Размер шрифта (A+ / A−, Ctrl +/−/0) — отдельно, в настройках.

const Z_MIN = 1, Z_MAX = 4;
let fz = 1, base = 0, t0 = 0, mid = null, lastTap = 0, tapXY = null, quietT = 0;
const sc = () => $("scroller"), feed = () => $("content");
const inFeed = (e) => !!e.target?.closest?.("#scroller") && !e.target.closest(".desk");
const dist = (e) => Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
const center = (e) => ({ x: (e.touches[0].clientX + e.touches[1].clientX) / 2, y: (e.touches[0].clientY + e.touches[1].clientY) / 2 });
const note = () => { clearTimeout(quietT); quietT = setTimeout(() => fz > 1 && toast(`Лента: ${Math.round(fz * 100)} % — двойной тап: 100 %`, 1500), 300); };

function zoomFeed(z, cx, cy) {                       // масштаб вокруг точки (cx, cy) экрана; 1 — как было
  const s = sc(), c = feed();
  if (!s || !c) return;
  z = Math.max(Z_MIN, Math.min(Z_MAX, z));
  if (Math.abs(z - 1) < 0.04) z = 1;
  const r = s.getBoundingClientRect();
  cx ??= r.left + r.width / 2; cy ??= r.top + r.height / 2;
  const x = cx - r.left, y = cy - r.top, k = z / fz;
  const left = (s.scrollLeft + x) * k - x, top = (s.scrollTop + y) * k - y;
  if (fz === 1 && z !== 1) c.style.width = c.getBoundingClientRect().width + "px";   // как картинка: без перестройки
  fz = z;
  c.style.zoom = z === 1 ? "" : String(z);
  if (z === 1) c.style.width = "";
  s.style.overflowX = z === 1 ? "" : "auto";          // увеличенную ленту двигаем и вбок
  s.classList.toggle("feed-zoomed", z !== 1);
  s.scrollLeft = z === 1 ? 0 : left; s.scrollTop = top;
  pin();
}
// шапка (#top) и полоса демо — внутри прокрутки ленты: при сдвиге увеличенной ленты вбок держим их на месте
// (свойство translate, а не transform — им шапка прячется при прокрутке вниз)
function pin() {
  const x = fz === 1 ? "" : sc().scrollLeft + "px 0";
  for (const id of ["top", "demoBar"]) { const el = $(id); if (el) el.style.translate = x; }
}
addEventListener("scroll", (e) => { if (fz !== 1 && e.target?.id === "scroller") pin(); }, { capture: true, passive: true });

addEventListener("gesturestart", (e) => { if (!inFeed(e)) return; e.preventDefault(); base = fz; }, { passive: false });
addEventListener("gesturechange", (e) => {
  if (!base) return; e.preventDefault(); zoomFeed(base * e.scale, e.clientX, e.clientY);
}, { passive: false });
addEventListener("gestureend", (e) => { if (!base) return; e.preventDefault(); base = 0; note(); }, { passive: false });

addEventListener("touchstart", (e) => {
  if (!inFeed(e)) return;
  if (e.touches.length === 2 && !window.GestureEvent) { t0 = dist(e); base = fz; mid = center(e); return; }
  if (e.touches.length === 1) {                        // двойной тап по увеличенной ленте — 100 %
    const now = Date.now(), p = { x: e.touches[0].clientX, y: e.touches[0].clientY };
    if (fz > 1 && now - lastTap < 320 && tapXY && Math.hypot(p.x - tapXY.x, p.y - tapXY.y) < 30) {
      lastTap = 0; zoomFeed(1, p.x, p.y); return;
    }
    lastTap = now; tapXY = p;
  }
}, { passive: true });
addEventListener("touchmove", (e) => {
  if (!t0 || e.touches.length !== 2) return;
  e.preventDefault(); mid = center(e); zoomFeed(base * dist(e) / t0, mid.x, mid.y);
}, { passive: false });
addEventListener("touchend", () => { if (t0) { t0 = 0; base = 0; note(); } });

addEventListener("wheel", (e) => {                   // Ctrl + колесо; щипок трекпада приходит так же (ctrlKey)
  if (!e.ctrlKey || !inFeed(e)) return;
  e.preventDefault();
  zoomFeed(fz * Math.exp(-e.deltaY / 200), e.clientX, e.clientY); note();
}, { passive: false });
addEventListener("dblclick", (e) => { if (fz > 1 && inFeed(e)) { e.preventDefault(); zoomFeed(1, e.clientX, e.clientY); } });

function fontSheet() {                               // настройки → «Размер текста»: A− / A+ / по умолчанию
  const pct = () => Math.round(fontPx / FONT.def * 100);
  sheet(`Размер текста: ${pct()} %`, [
    { label: "A+  Крупнее", icon: "plus", run: () => { setFont(fontPx + 1); fontSheet(); } },
    { label: "A−  Мельче", icon: "x", run: () => { setFont(fontPx - 1); fontSheet(); } },
    { label: "По умолчанию (100 %)", icon: "refresh", run: () => { setFont(FONT.def); fontSheet(); } },
    { info: true, icon: "help", label: "Увеличить ленту как картинку", sub: "щипком двумя пальцами или Ctrl + колесо; двойной тап — 100 %" },
  ]);
}

Object.assign(window, { fontSheet, zoomFeed, feedZoom: () => fz });
