// Рабочий стол Ubuntu агентов (#206) — часть интерфейса по требованию (#191). Владелец 14.11: «чтобы внутри пульта
// была кнопочка … открыть Ubuntu сразу, минуя браузер». Владелец 15.11: «открывать окно с адаптивным дизайном под размер
// экрана, с горизонтальной и вертикальной ориентацией и возможностью зума».
//
// Вход: «Ubuntu» → /api/desktop/open (свежему входу — код подтверждения) → cookie-пропуск на /desktop/ → Caddy пускает
// только владельца (forward_auth /api/gate/desktop). Экран — своё окно на ядре noVNC (core/rfb.js с того же /desktop/),
// а не vnc.html во фрейме: у vnc.html только «вписать» или «обрезать», произвольного зума нет.
//
// Масштаб: «вписать» (по умолчанию: весь стол виден, пропорции сохранены) или зум 25–400 % — кнопки − / + / 100 % /
// «Вписать», щипок двумя пальцами, двойной тап «вписать ↔ 100 %». Режимы касаний: «Рука» — смотреть и двигать картинку
// (щипок, перетаскивание, двойной тап), без неё касания и мышь уходят на стол. Поворот телефона и смена размера окна —
// пересчёт без переподключения. Полный экран (Fullscreen API; в Mini App — свой полноэкранный режим), безопасные зоны
// iPhone, экранная клавиатура, панель кнопок сворачивается.

let deskEl = null, deskScr = null, deskOff = [], deskSize = "";
// Размер стола под устройство: портрет — «высокий» 1080×1920, альбом и компьютер — 1600×900 (как у агентов).
// Стол общий для агентов: по закрытию просмотра — обратно 1600×900. Сервер пускает только эти размеры.
const DESK_BASE = "1600x900", deskWant = () => (innerHeight > innerWidth * 1.2 ? "1080x1920" : DESK_BASE);
function deskResize(want) {
  if (want === deskSize) return Promise.resolve(false);
  const [w, h] = want.split("x").map(Number);
  return api("/api/desktop/size", { w, h }).then(() => { deskSize = want; return true; }, () => false);
}
const Z_MIN = 0.25, Z_MAX = 4, Z_STEP = 1.25;

async function deskOpen() {
  let d;
  try { d = await api("/api/desktop/open", {}); }
  catch (e) { return toast("Рабочий стол: " + e.message, 5000); }
  deskShow(d);
}

// «Экран»: настоящий (noVNC) или заглушка демо 1600×900 — одно устройство для зума и тестов.
// {w, h — размер стола; scale(z) — показать в z раз; fit() — вписать; view(on) — только смотреть; type/key — ввод}
async function rfbScreen(view, st) {
  const { default: RFB } = await import("/desktop/core/rfb.js");
  const { default: keysyms } = await import("/desktop/core/input/keysymdef.js");
  const url = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/desktop/websockify";
  const rfb = new RFB(view, url, { shared: true });
  rfb.scaleViewport = true; rfb.resizeSession = false; rfb.background = "transparent";
  const scr = {
    get w() { return rfb._display?.width || 0; }, get h() { return rfb._display?.height || 0; },
    scroller: rfb._screen || view,                     // noVNC прокручивает свой блок внутри контейнера
    // noVNC 1.6: свой масштаб — через display.scale (сам он умеет только «вписать»); координаты мыши он делит на него же
    scale(z) { rfb.scaleViewport = false; rfb.clipViewport = false; if (rfb._display) rfb._display.scale = z; },
    fit() { rfb.clipViewport = false; rfb.scaleViewport = true; },
    view(only) { rfb.viewOnly = only; },
    type(text) { for (const ch of text) rfb.sendKey(keysyms.lookup(ch.codePointAt(0)), null); },
    key(name) { rfb.sendKey({ Enter: 0xff0d, Backspace: 0xff08, Tab: 0xff09, Escape: 0xff1b }[name], name); },
    close() { try { rfb.disconnect(); } catch (_) {} },
  };
  rfb.addEventListener("connect", () => { st.textContent = "на связи"; scr.onready?.(); });
  rfb.addEventListener("disconnect", (e) => { st.textContent = e.detail?.clean ? "отключено" : "связь потеряна — «Переподключить»"; });
  rfb.addEventListener("securityfailure", () => { st.textContent = "нет доступа — откройте заново"; });
  return scr;
}

function demoScreen(view, st) {                        // демо: «стол» 1600×900 без сети, ввод — в журнал (для тестов)
  const box = document.createElement("div"); box.className = "desk-demo";
  box.innerHTML = `<div>Демо: рабочий стол Ubuntu 1600×900<br>с браузером агента (noVNC)</div>`;
  view.append(box);
  const size = (z) => { box.style.width = 1600 * z + "px"; box.style.height = 900 * z + "px"; };
  const scr = {
    w: 1600, h: 900, typed: [], z: 1, fitted: true, viewOnly: false, scroller: view,
    scale(z) { scr.fitted = false; scr.z = z; size(z); },
    fit() { scr.fitted = true; scr.z = Math.min(view.clientWidth / 1600, view.clientHeight / 900); size(scr.z); },
    view(only) { scr.viewOnly = only; }, type(t) { scr.typed.push(t); }, key(k) { scr.typed.push("<" + k + ">"); }, close() {},
  };
  setTimeout(() => { st.textContent = "демо"; scr.onready?.(); }, 30);
  window.__deskDemo = scr;
  return scr;
}

function deskShow(d) {
  deskClose();
  const touch = matchMedia("(pointer: coarse)").matches;   // палец: по умолчанию «Рука» (смотреть и двигать)
  const el = deskEl = document.createElement("div");
  el.className = "desk"; el.setAttribute("role", "dialog"); el.setAttribute("aria-label", "Рабочий стол Ubuntu");
  const b = (k, icon, label, extra = "") => `<button class="icon" data-desk="${k}" aria-label="${label}" title="${label}"${extra}>${icon}</button>`;
  el.innerHTML = `<div class="desk-bar"><b>${ic("monitor", "s16")}<span>Ubuntu</span></b><span class="desk-st" role="status">подключаю…</span>
      ${b("tools", ic("settings"), "Кнопки масштаба", ' aria-expanded="true"')}
      ${b("full", ic("expand"), "Во весь экран")}
      ${b("reload", ic("refresh"), "Переподключить")}
      ${d.demo ? "" : b("tab", ic("ext"), "Открыть в браузере")}
      ${b("close", ic("x"), "Закрыть")}</div>
    <div class="desk-tools">
      ${b("out", "−", "Уменьшить")}<span class="desk-z" aria-live="polite">вписан</span>${b("in", "+", "Увеличить")}
      <button class="desk-t" data-desk="fit">Вписать</button><button class="desk-t" data-desk="one">100 %</button>
      <button class="desk-t" data-desk="hand" aria-pressed="${touch}" title="Рука: смотреть и двигать; выкл — управлять столом">Рука</button>
      <button class="desk-t" data-desk="kbd">Клавиатура</button></div>
    <div class="desk-stage"><div class="desk-view"></div><div class="desk-pan"${touch ? "" : " hidden"}></div></div>
    <textarea class="desk-kbd" aria-label="Ввод на рабочий стол" autocapitalize="off" autocomplete="off" spellcheck="false"></textarea>`;
  const st = el.querySelector(".desk-st"), view = el.querySelector(".desk-view"), pan = el.querySelector(".desk-pan");
  const zl = el.querySelector(".desk-z"), kbd = el.querySelector(".desk-kbd");
  document.body.append(el); document.body.classList.add("desk-on");
  try { tg?.BackButton?.show(); tg?.BackButton?.onClick(deskClose); tg?.expand?.(); } catch (_) {}

  let z = 0, fitted = true;                            // z — текущий масштаб; fitted — режим «вписать»
  const sc = () => deskScr?.scroller || view;
  const fitZ = () => (deskScr?.w ? Math.min(view.clientWidth / deskScr.w, view.clientHeight / deskScr.h) : 1);
  const show = () => { zl.textContent = fitted ? "вписан" : Math.round(z * 100) + " %"; };
  const fit = () => { if (!deskScr) return; fitted = true; z = fitZ(); deskScr.fit(); show(); };
  const zoom = (nz, cx, cy) => {                       // масштаб вокруг точки (cx, cy) окна; меньше «вписать» — вписать
    if (!deskScr) return;
    const f = fitZ(); nz = Math.max(Z_MIN, Math.min(Z_MAX, nz));
    if (nz <= f * 1.01) return fit();
    const r = view.getBoundingClientRect(); cx ??= r.width / 2; cy ??= r.height / 2;
    const k = nz / (z || f), sx = (sc().scrollLeft + cx) * k - cx, sy = (sc().scrollTop + cy) * k - cy;
    fitted = false; z = nz; deskScr.scale(z); sc().scrollLeft = sx; sc().scrollTop = sy; show();
  };
  const relayout = () => { if (!deskEl) return; if (fitted) fit(); else zoom(z); };   // без переподключения
  let sizeT = 0;
  const later = () => {
    setTimeout(relayout, 80);
    if (!d.demo) { clearTimeout(sizeT); sizeT = setTimeout(() => deskResize(deskWant()).then((ch) => ch && setTimeout(relayout, 700)), 700); }
  };
  for (const [t, ev] of [[window, "resize"], [window, "orientationchange"], [window.visualViewport, "resize"]])
    if (t) { t.addEventListener(ev, later); deskOff.push(() => t.removeEventListener(ev, later)); }
  try { if (tg?.onEvent) { tg.onEvent("viewportChanged", later); deskOff.push(() => tg.offEvent?.("viewportChanged", later)); } } catch (_) {}

  // «Рука»: перетаскивание — прокрутка, щипок — зум, двойной тап — «вписать ↔ 100 %». Выключена — касания уходят на стол.
  const hand = (on) => { pan.hidden = !on; el.querySelector("[data-desk=hand]").setAttribute("aria-pressed", String(on)); deskScr?.view(on); };
  const pts = new Map(); let pinch = null, lastTap = 0, moved = 0;
  pan.addEventListener("pointerdown", (e) => { try { pan.setPointerCapture(e.pointerId); } catch (_) {} pts.set(e.pointerId, { x: e.clientX, y: e.clientY }); pinch = null; moved = 0; });
  pan.addEventListener("pointermove", (e) => {
    const p = pts.get(e.pointerId); if (!p) return;
    if (pts.size === 1) { sc().scrollLeft -= e.clientX - p.x; sc().scrollTop -= e.clientY - p.y; moved += Math.abs(e.clientX - p.x) + Math.abs(e.clientY - p.y); }
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 2) {
      const [a, c] = [...pts.values()], dist = Math.hypot(a.x - c.x, a.y - c.y), r = view.getBoundingClientRect();
      if (!pinch) pinch = { dist, z: z || fitZ() };
      else if (pinch.dist) zoom(pinch.z * dist / pinch.dist, (a.x + c.x) / 2 - r.left, (a.y + c.y) / 2 - r.top);
    }
  });
  const up = (e) => {
    const was = pts.size; pts.delete(e.pointerId);
    if (was === 1 && !pinch && moved < 10) {
      const now = Date.now(), r = view.getBoundingClientRect();
      if (now - lastTap < 350) { lastTap = 0; if (fitted) zoom(1, e.clientX - r.left, e.clientY - r.top); else fit(); return; }
      lastTap = now;
    }
    if (!pts.size) pinch = null;
  };
  pan.addEventListener("pointerup", up); pan.addEventListener("pointercancel", up);
  view.addEventListener("wheel", (e) => {              // компьютер: Ctrl + колесо (и щипок тачпада) — зум
    if (!e.ctrlKey) return; e.preventDefault(); const r = view.getBoundingClientRect();
    zoom((z || fitZ()) * (e.deltaY < 0 ? 1.1 : 1 / 1.1), e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });

  // экранная клавиатура: скрытое поле; набранное — на стол, Enter / ⌫ / Tab / Esc — клавишами
  kbd.addEventListener("input", () => { if (kbd.value) { deskScr?.type(kbd.value); kbd.value = ""; } });
  kbd.addEventListener("keydown", (e) => { if (["Enter", "Backspace", "Tab", "Escape"].includes(e.key)) { e.preventDefault(); deskScr?.key(e.key); } });

  el.addEventListener("click", (e) => {
    const t = e.target.closest("[data-desk]"); if (!t) return;
    const k = t.dataset.desk;
    if (k === "close") return deskClose();
    if (k === "tab") return deskTab();
    if (k === "reload") { st.textContent = "подключаю…"; return deskOpen(); }
    if (k === "in") return zoom((z || fitZ()) * Z_STEP);
    if (k === "out") return zoom((z || fitZ()) / Z_STEP);
    if (k === "fit") return fit();
    if (k === "one") return zoom(1);
    if (k === "hand") return hand(pan.hidden);
    if (k === "kbd") return kbd.focus({ preventScroll: true });
    if (k === "tools") { const off = el.classList.toggle("desk-min"); t.setAttribute("aria-expanded", String(!off)); return later(); }
    if (k === "full") return deskFull(el);
  });

  (d.demo ? Promise.resolve(demoScreen(view, st)) : rfbScreen(view, st)).then((scr) => {
    if (deskEl !== el) return scr.close();
    deskScr = scr; scr.onready = () => {
      hand(!pan.hidden); fit();
      if (!d.demo) deskResize(deskWant()).then((ch) => ch && setTimeout(relayout, 700));   // стол — под экран
    };
  }, (e) => { st.textContent = "не подключился: " + e.message; });
  haptic("impactOccurred", "light");
}

function deskFull(el) {                                // во весь экран: Mini App — свой режим, браузер — Fullscreen API
  try {
    if (tg?.requestFullscreen && tg?.isVersionAtLeast?.("8.0")) return tg.isFullscreen ? tg.exitFullscreen() : tg.requestFullscreen();
    if (document.fullscreenElement) return document.exitFullscreen();
    const p = (el.requestFullscreen || el.webkitRequestFullscreen)?.call(el);
    if (!p && !el.requestFullscreen && !el.webkitRequestFullscreen) toast("Этот браузер не даёт полный экран", 3500);
    p?.catch?.(() => toast("Этот браузер не даёт полный экран", 3500));
  } catch (_) { toast("Этот браузер не даёт полный экран", 3500); }
}

// Отдельная вкладка (владелец 14.11: «чтобы окно убунту открывалось во вкладке»): свежая одноразовая ссылка —
// из Mini App вкладка открывается во внешнем браузере, где нет ни входа панели, ни пропуска.
async function deskTab() {
  try { const d = await api("/api/desktop/open", {}); openUrl(location.origin + (d.tab || d.url)); }
  catch (e) { toast("Рабочий стол: " + e.message, 5000); }
}

function deskClose() {
  if (!deskEl) return;
  deskScr?.close(); deskScr = null; deskOff.forEach((f) => f()); deskOff = [];
  if (deskSize && deskSize !== DESK_BASE) deskResize(DESK_BASE);   // стол общий — вернуть агентам обычный размер
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  deskEl.remove(); deskEl = null; document.body.classList.remove("desk-on");
  try { tg?.BackButton?.offClick(deskClose); if (typeof view !== "undefined" && view === "home") tg?.BackButton?.hide(); } catch (_) {}
}

Object.assign(window, { deskOpen, deskClose, deskTab, deskShow });
