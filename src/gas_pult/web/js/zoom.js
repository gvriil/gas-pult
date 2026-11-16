// Масштаб текста панели жестом — часть по требованию (#191). Владелец 16.11: «масштаб двумя пальцами … как в ChatGPT:
// иногда шрифт мелкий». Страницу целиком не масштабируем (maximum-scale=1): каркас с полем ввода и клавиатурой iOS
// остаётся на месте, растёт текст — общий множитель --fz (размер шрифта панели, 80–200 %, хранится на устройстве).
// Щипок: iOS (Safari, Telegram) — gesturestart/change/end, остальные — два пальца; компьютер — Ctrl + колесо и щипок
// трекпада. Экран Ubuntu (.desk) — свой зум, его не трогаем.

let base = 0, t0 = 0, acc = 0, quietT = 0;
const desk = (e) => e.target?.closest?.(".desk");
const at = (k) => setFont(base * k, true);
const done = () => { clearTimeout(quietT); quietT = setTimeout(() => toast(`Размер текста: ${Math.round(fontPx / FONT.def * 100)} %`, 1200), 250); };
const dist = (e) => Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);

addEventListener("gesturestart", (e) => { if (desk(e)) return; e.preventDefault(); base = fontPx; }, { passive: false });
addEventListener("gesturechange", (e) => { if (desk(e) || !base) return; e.preventDefault(); at(e.scale); }, { passive: false });
addEventListener("gestureend", (e) => { if (!base) return; e.preventDefault(); base = 0; done(); }, { passive: false });

addEventListener("touchstart", (e) => {             // без событий жестов WebKit (Android, Chrome): два пальца
  if (window.GestureEvent || e.touches.length !== 2 || desk(e)) return;
  t0 = dist(e); base = fontPx;
}, { passive: true });
addEventListener("touchmove", (e) => {
  if (!t0 || e.touches.length !== 2) return;
  e.preventDefault(); at(dist(e) / t0);
}, { passive: false });
addEventListener("touchend", () => { if (t0) { t0 = 0; base = 0; done(); } });

addEventListener("wheel", (e) => {                   // Ctrl + колесо; щипок трекпада приходит так же (ctrlKey)
  if (!e.ctrlKey || desk(e)) return;
  e.preventDefault();
  acc -= e.deltaY;
  if (Math.abs(acc) >= 30) { setFont(fontPx + Math.sign(acc), true); acc = 0; done(); }
}, { passive: false });

function fontSheet() {                               // настройки → «Размер текста»: A− / A+ / по умолчанию
  const pct = () => Math.round(fontPx / FONT.def * 100);
  sheet(`Размер текста: ${pct()} %`, [
    { label: "A+  Крупнее", icon: "plus", run: () => { setFont(fontPx + 1); fontSheet(); } },
    { label: "A−  Мельче", icon: "x", run: () => { setFont(fontPx - 1); fontSheet(); } },
    { label: "По умолчанию (100 %)", icon: "refresh", run: () => { setFont(FONT.def); fontSheet(); } },
    { info: true, icon: "help", label: "Щипком двумя пальцами", sub: "на телефоне; на компьютере — Ctrl + колесо или щипок трекпада, Ctrl +/−/0" },
  ]);
}

Object.assign(window, { fontSheet });
