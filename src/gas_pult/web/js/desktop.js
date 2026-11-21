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

let deskEl = null, deskScr = null, deskOff = [];
const Z_MIN = 0.25, Z_MAX = 4, Z_STEP = 1.25;
const KEYS = { Enter: [0xff0d, "Enter"], Escape: [0xff1b, "Escape"], Tab: [0xff09, "Tab"], Backspace: [0xff08, "Backspace"],
  Left: [0xff51, "ArrowLeft"], Up: [0xff52, "ArrowUp"], Right: [0xff53, "ArrowRight"], Down: [0xff54, "ArrowDown"],
  Delete: [0xffff, "Delete"], Home: [0xff50, "Home"], End: [0xff57, "End"] };
const MODS = { Ctrl: [0xffe3, "ControlLeft"], Alt: [0xffe9, "AltLeft"], Shift: [0xffe1, "ShiftLeft"] };
// Ряд клавиш (владелец 15.11: «команды, Enter, Ctrl+C, если мы в терминале оказались, и чтобы это было понятно»)
const KEYROW = [["Enter", "Enter ⏎", "Ввод (Enter)"], ["Escape", "Esc", "Escape"], ["Tab", "Tab", "Tab"],
  ["Backspace", "⌫", "Стереть (Backspace)"], ["Left", "←", "Влево"], ["Up", "↑", "Вверх"], ["Down", "↓", "Вниз"],
  ["Right", "→", "Вправо"], ["mod:Ctrl", "Ctrl", "Ctrl — нажмите, затем клавишу"], ["mod:Alt", "Alt", "Alt — нажмите, затем клавишу"],
  ["mod:Shift", "Shift", "Shift — нажмите, затем клавишу"], ["c", "Ctrl+C", "Прервать команду (Ctrl+C)"],
  ["v", "Ctrl+V", "Вставить (Ctrl+V)"], ["l", "Ctrl+L", "Очистить экран терминала (Ctrl+L)"],
  ["d", "Ctrl+D", "Конец ввода / выйти (Ctrl+D)"], ["z", "Ctrl+Z", "Приостановить (Ctrl+Z)"]];
// Стили стола — здесь, а не в ядре (ядро < 770 КБ, tests/test_ui_parts.py): часть грузится только при открытии стола.
// В ядре остались только правила с position: fixed (.desk, .desk-fab, .desk-kbd) — их учитывает реестр FIXED_OK
const DESK_CSS = `
  /* одна строка плоских кнопок (владелец 15.11: «округлённые кнопки смотрятся дурацки … не больше чем в одну строку») */
  .desk-bar, .desk-keys { display: flex; align-items: center; gap: 2px; padding: 2px 4px; background: var(--bg-canvas); flex: none;
    overflow-x: auto; scrollbar-width: none; white-space: nowrap; border-bottom: 1px solid var(--border-subtle); }
  .desk-bar::-webkit-scrollbar, .desk-keys::-webkit-scrollbar { display: none; }
  .desk-name { display: inline-flex; align-items: center; gap: 4px; padding: 0 6px 0 4px; flex: none; color: var(--text-secondary); }
  .desk-st { font-size: 12px; max-width: 120px; overflow: hidden; text-overflow: ellipsis; }
  .desk-b { flex: none; min-width: 36px; height: 34px; padding: 0 9px; border: 0; border-radius: var(--radius-sm); background: transparent;
    color: var(--text-primary); font: inherit; font-size: 13px; display: inline-flex; align-items: center; justify-content: center; gap: 4px; cursor: pointer; }
  .desk-b:hover { background: var(--bg-subtle); } .desk-b:active { background: var(--accent-soft); }
  .desk-b[aria-pressed="true"], .desk-b[aria-expanded="true"] { background: var(--accent-soft); color: var(--accent-primary); }
  .desk-b .i { width: 18px; height: 18px; }
  .desk-keys { background: var(--bg-subtle); } .desk-keys .desk-b { font-variant-numeric: tabular-nums; }
  .desk-z { min-width: 50px; text-align: center; font-size: 12px; color: var(--text-secondary); font-variant-numeric: tabular-nums; flex: none; }
  .desk.desk-hidden .desk-bar, .desk.desk-hidden .desk-keys, .desk.desk-hidden .desk-clip { display: none; }
  .desk-term { margin: 0; padding: 16px; font: 14px/1.4 ui-monospace, monospace; color: var(--text-primary); white-space: pre-wrap; text-align: left; width: 100%; height: 100%; box-sizing: border-box; }
  .desk-clip { display: flex; flex-direction: column; gap: 6px; padding: 6px 8px; background: var(--bg-canvas); border-bottom: 1px solid var(--border-subtle); flex: none; }
  .desk-clip-in { width: 100%; box-sizing: border-box; font: inherit; font-size: 16px; padding: 6px 8px; border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); background: var(--bg-surface); color: var(--text-primary); resize: vertical; }
  .desk-clip-row, .desk-clip-out { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .desk-clip-out span { font-size: 13px; color: var(--text-secondary); } .desk-clip-text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
  .desk-t.on { background: var(--accent-primary); border-color: var(--accent-primary); color: var(--on-accent); }
  .desk-stage { position: relative; flex: 1; min-height: 0; padding-bottom: env(safe-area-inset-bottom); }
  .desk-view { position: absolute; inset: 0; overflow: auto; display: flex; } .desk-view > * { margin: auto; flex: none; }   /* margin: auto — центр без обрезки при зуме */
  .desk-pan { position: absolute; inset: 0; z-index: 1; touch-action: none; cursor: grab; }
  .desk-demo { display: flex; align-items: flex-start; background: var(--bg-surface); color: var(--text-secondary); text-align: center; font-size: 15px; outline: 1px solid var(--border-subtle); }
  body.desk-on { overflow: hidden; }
  /* Телефон (владелец 21.11: «как у Safari или DuckDuckGo … не засорять поле»): стол на весь экран, кнопки панели —
     в меню ≡, ряд клавиш — по кнопке с клавиатурой. Обе кнопки — в правом нижнем углу (сверху — вкладки и меню Chrome) */
  .desk-dock { position: absolute; right: calc(8px + env(safe-area-inset-right)); bottom: calc(8px + env(safe-area-inset-bottom)); z-index: 3;
    display: none; flex-direction: column; gap: 6px; touch-action: none; }
  .desk-dock .desk-b { width: 44px; height: 44px; padding: 0; border-radius: var(--radius-md); border: 1px solid var(--border-subtle);
    background: var(--bg-canvas); box-shadow: 0 2px 10px rgb(0 0 0 / .3); opacity: .88; }
  .desk-dock .desk-b .i { width: 22px; height: 22px; }
  .desk.desk-compact .desk-dock { display: flex; }
  .desk.desk-compact .desk-fab, .desk.desk-compact [data-desk=hide] { display: none; }
  .desk.desk-compact .desk-bar { position: absolute; z-index: 4; right: calc(60px + env(safe-area-inset-right)); bottom: calc(8px + env(safe-area-inset-bottom));
    display: none; flex-wrap: wrap; gap: 4px; width: min(300px, calc(100% - 76px)); max-height: calc(100% - 16px); overflow-y: auto;
    padding: 6px; border: 1px solid var(--border-subtle); border-radius: var(--radius-md); box-shadow: 0 6px 24px rgb(0 0 0 / .35); white-space: normal; }
  .desk.desk-compact.desk-menu .desk-bar { display: flex; }
  .desk.desk-compact .desk-bar .desk-name { flex: 1 0 100%; padding: 4px 6px; }
  .desk.desk-compact .desk-bar .desk-b { height: 40px; }
  .desk.desk-compact .desk-keys { position: absolute; z-index: 3; left: env(safe-area-inset-left); right: calc(60px + env(safe-area-inset-right));
    bottom: calc(8px + env(safe-area-inset-bottom)); margin-left: 8px; border: 1px solid var(--border-subtle); border-radius: var(--radius-md);
    box-shadow: 0 2px 10px rgb(0 0 0 / .3); padding: 3px; }
  .desk.desk-compact .desk-keys[hidden] { display: none; }
  .desk.desk-compact .desk-keys .desk-b { height: 38px; }
  .desk.desk-compact .desk-stage { padding-bottom: 0; }
`;
if (!document.getElementById("desk-css")) {
  const s = document.createElement("style"); s.id = "desk-css"; s.textContent = DESK_CSS; document.head.append(s);
}
// Телефон и альбом телефона: компактная панель (меню ≡, клавиши по кнопке) и мобильный вид сайтов (deskmobile.py)
const NARROW = "(max-width: 700px), (max-height: 500px)";
const MIN_W = 500;                                     // уже окно Chrome не бывает — стол не уже, показываем уменьшенным
const BEAT = 20000;                                    // сердцебиение мобильного вида; сервер ждёт 60 с
const DESK_UI = "gp.desk.ui";                          // свёрнута ли панель, показан ли ряд клавиш — на этом устройстве
const uiGet = () => { try { return JSON.parse(localStorage.getItem(DESK_UI) || "{}"); } catch (_) { return {}; } };
const uiSet = (v) => { try { localStorage.setItem(DESK_UI, JSON.stringify({ ...uiGet(), ...v })); } catch (_) {} };

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
  // 21.11: стол на Xvnc (TigerVNC) меняет размер под окно — «вписать» = стол того же размера, что экран устройства;
  // буфер UTF-8 (расширенный буфер noVNC) — русский текст в обе стороны без набора клавишами
  rfb.scaleViewport = false; rfb.resizeSession = true; rfb.background = "transparent";
  if (typeof DEMO !== "undefined" && DEMO) window.__deskRfb = rfb;     // проверка на живом столе (только ?demo)
  // 21.11: окно Chrome не уже ~500 px — на телефоне (390) правый край обрезался. Узкий экран: просим стол шириной
  // MIN_W (высота — в той же пропорции) и показываем его уменьшенным (scaleViewport: noVNC сам пересчитает мышь)
  const box = () => { const r = rfb._screen.getBoundingClientRect(); return { w: r.width, h: r.height }; };
  const narrow = () => { const b = box(); return b.w > 0 && b.w < MIN_W; };
  const want = () => { const b = box(); return narrow() ? { w: MIN_W, h: Math.round(b.h * MIN_W / b.w) } : b; };
  const ask = rfb._requestRemoteResize.bind(rfb);
  rfb._requestRemoteResize = function () { this._screenSize = want; try { ask(); } finally { delete this._screenSize; } };
  const scr = {
    get w() { return rfb._display?.width || 0; }, get h() { return rfb._display?.height || 0; },
    scroller: rfb._screen || view,                     // noVNC прокручивает свой блок внутри контейнера
    // noVNC 1.6: свой масштаб — через display.scale (сам он умеет только «вписать»); координаты мыши он делит на него же
    scale(z) { rfb.resizeSession = false; rfb.scaleViewport = false; rfb.clipViewport = false; if (rfb._display) rfb._display.scale = z; },
    fit() { rfb.clipViewport = false; rfb.scaleViewport = narrow(); rfb.resizeSession = true; },   // стол — под размер окна
    get utf8() { return !!rfb._clipboardServerCapabilitiesFormats?.[1]; },   // сервер принял расширенный буфер (UTF-8)
    // «Рука» перехватывает касания своим слоем; viewOnly у noVNC не ставим — он глушит и клавиатуру (пароль, Enter)
    view() {},
    press(sym, code, mods = []) {                      // клавиша с модификаторами: нажать модификаторы, клавишу, отпустить
      for (const m of mods) rfb.sendKey(MODS[m][0], MODS[m][1], true);
      rfb.sendKey(sym, code);
      for (const m of [...mods].reverse()) rfb.sendKey(MODS[m][0], MODS[m][1], false);
    },
    type(text, mods = []) {                            // посимвольно; \n — Enter; кириллица — keysym по Unicode
      for (const ch of text) ch === "\n" ? scr.press(0xff0d, "Enter", mods) : scr.press(keysyms.lookup(ch.codePointAt(0)), null, mods);
    },
    paste(text) {                                      // в буфер стола и Ctrl+V — в поле, где стоит курсор
      rfb.clipboardPasteFrom(text);
      rfb.sendKey(0xffe3, "ControlLeft", true); rfb.sendKey(0x76, "KeyV"); rfb.sendKey(0xffe3, "ControlLeft", false);
    },
    key(name, mods = []) { scr.press(KEYS[name][0], KEYS[name][1], mods); },
    close() { try { rfb.disconnect(); } catch (_) {} },
  };
  rfb.addEventListener("connect", () => { st.textContent = "на связи"; scr.onready?.(); });
  rfb.addEventListener("clipboard", (e) => scr.onclip?.(String(e.detail?.text || "")));   // копия на столе → сюда
  rfb.addEventListener("disconnect", (e) => { st.textContent = e.detail?.clean ? "отключено" : "связь потеряна — «Переподключить»"; });
  rfb.addEventListener("securityfailure", () => { st.textContent = "нет доступа — откройте заново"; });
  return scr;
}

function demoScreen(view, st) {                        // демо: «стол» 1600×900 с терминалом-заглушкой (для тестов)
  const box = document.createElement("div"); box.className = "desk-demo";
  box.innerHTML = `<pre class="desk-term" aria-label="Терминал на столе (демо)">Демо: терминал в Браузере агентов\n$ </pre>`;
  view.append(box);
  const pre = box.querySelector("pre"), size = (z) => { box.style.width = 1600 * z + "px"; box.style.height = 900 * z + "px"; };
  let line = "", busy = false;
  const out = (t) => { pre.textContent += t; };
  const enter = () => {                                // «выполнить» строку: echo — вывод, sleep — занят до Ctrl+C
    out("\n"); const [cmd, ...a] = line.trim().split(/\s+/); line = "";
    if (cmd === "echo") out(a.join(" ") + "\n$ "); else if (cmd === "sleep") busy = true; else out((cmd ? cmd + ": демо\n" : "") + "$ ");
  };
  const scr = {
    w: 1600, h: 900, typed: [], z: 1, fitted: true, scroller: view, get term() { return pre.textContent; },
    scale(z) { scr.fitted = false; scr.z = z; size(z); },
    fit() { scr.fitted = true; scr.z = Math.min(view.clientWidth / 1600, view.clientHeight / 900); size(scr.z); },
    view() {}, close() {},
    type(t, mods = []) {
      scr.typed.push(mods.length ? mods.join("+") + "+" + t : t);
      for (const ch of t) {
        if (mods.includes("Ctrl") && ch.toLowerCase() === "c") { if (busy) busy = false; out("^C\n$ "); line = ""; continue; }
        if (ch === "\n") enter(); else if (!busy) { line += ch; out(ch); }
      }
    },
    key(k, mods = []) {
      scr.typed.push("<" + (mods.length ? mods.join("+") + "+" : "") + k + ">");
      if (k === "Enter" && !busy) enter();
      if (k === "Backspace" && line) { line = line.slice(0, -1); pre.textContent = pre.textContent.slice(0, -1); }
    },
    paste(t) { scr.typed.push("[вставка]" + t); }, copy(t) { scr.onclip?.(t); },   // copy — «скопировали на столе» (тест)
  };
  setTimeout(() => { st.textContent = "демо"; scr.onready?.(); }, 30);
  window.__deskDemo = scr;
  return scr;
}

function deskShow(d) {
  deskClose();
  const touch = matchMedia("(pointer: coarse)").matches;   // палец: по умолчанию «Рука» (смотреть и двигать)
  const el = deskEl = document.createElement("div");
  el.className = "desk"; el.setAttribute("role", "dialog"); el.setAttribute("aria-label", "Браузер агентов");
  const ui = uiGet(), keysOn = ui.keys ?? touch;
  const b = (k, icon, label, extra = "") => `<button class="desk-b" data-desk="${k}" aria-label="${label}" title="${label}"${extra}>${icon}</button>`;
  // одна строка плоских кнопок; не влезает — прокрутка вбок; «Скрыть» — панель в значок в углу (перетаскивается)
  el.innerHTML = `<div class="desk-bar" role="toolbar" aria-label="Управление столом">
      <span class="desk-name">${ic("monitor", "s16")}<span class="desk-st" role="status">подключаю…</span></span>
      ${b("out", "−", "Уменьшить")}<span class="desk-z" aria-live="polite">вписан</span>${b("in", "+", "Увеличить")}
      ${b("fit", "Вписать", "Вписать весь стол в экран")}${b("one", "1:1", "100 %")}
      ${b("hand", "Рука", "Рука: двигать и масштабировать картинку пальцами (клавиатура работает всегда)", ` aria-pressed="${touch}"`)}
      ${b("kbd", "Клавиатура", "Экранная клавиатура")}${b("keys", "Клавиши", "Ряд клавиш: Enter, Esc, Ctrl+C…", ` aria-pressed="${keysOn}"`)}
      ${b("clip", "Буфер", "Буфер обмена: вставить на стол, скопировать со стола", ' aria-expanded="false"')}
      ${b("full", ic("expand"), "Во весь экран")}${b("reload", ic("refresh"), "Переподключить")}
      ${d.demo ? "" : b("tab", ic("ext"), "Открыть в браузере")}${b("hide", ic("down"), "Скрыть панель")}${b("close", ic("x"), "Закрыть")}</div>
    <div class="desk-keys" role="toolbar" aria-label="Клавиши"${keysOn ? "" : " hidden"}>${KEYROW.map(([k, t, l]) =>
      `<button class="desk-b" data-key="${k}" title="${l}" aria-label="${l}"${k.startsWith("mod:") ? ' aria-pressed="false"' : ""}>${t}</button>`).join("")}</div>
    <div class="desk-clip" hidden>
      <textarea class="desk-clip-in" rows="2" placeholder="Вставьте сюда текст (пароль, ссылку) — он уйдёт на стол" autocomplete="off" autocapitalize="off" spellcheck="false"></textarea>
      <div class="desk-clip-row"><button class="desk-t" data-desk="clip-read">Взять из буфера телефона</button>
        <button class="desk-t on" data-desk="clip-paste">Вставить на стол</button>
        <button class="desk-t" data-desk="clip-type" title="Если вставка не сработала: набрать текст посимвольно">Напечатать</button></div>
      <div class="desk-clip-out" hidden><span>Скопировано на столе:</span><code class="desk-clip-text"></code>
        <button class="desk-t on" data-desk="clip-copy">Скопировать</button></div></div>
    <div class="desk-stage"><div class="desk-view"></div><div class="desk-pan"${touch ? "" : " hidden"}></div></div>
    <textarea class="desk-kbd" aria-label="Ввод на рабочий стол" autocapitalize="off" autocomplete="off" autocorrect="off" spellcheck="false" enterkeyhint="enter"></textarea>
    <button class="desk-fab" data-desk="show" aria-label="Показать панель стола" title="Показать панель (можно перетащить)" hidden>${ic("monitor")}</button>
    <div class="desk-dock" role="toolbar" aria-label="Кнопки стола">
      ${b("keys", ic("keyboard"), "Клавиши: Enter, Esc, стрелки, Ctrl", ' aria-pressed="false"')}
      ${b("menu", ic("lines"), "Меню стола", ' aria-haspopup="true" aria-expanded="false"')}</div>`;
  const st = el.querySelector(".desk-st"), view = el.querySelector(".desk-view"), pan = el.querySelector(".desk-pan");
  const zl = el.querySelector(".desk-z"), kbd = el.querySelector(".desk-kbd");
  const later = () => setTimeout(() => relayout(), 80);
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
  function relayout() { if (!deskEl) return; if (fitted) fit(); else zoom(z); }   // без переподключения
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

  // клавиши: залипающие Ctrl/Alt/Shift — подсвечены, действуют на следующую клавишу или букву, потом гаснут
  const sticky = new Set();
  const modsOnce = () => { const m = [...sticky]; sticky.clear(); el.querySelectorAll(".desk-keys [aria-pressed]").forEach((x) => x.setAttribute("aria-pressed", "false")); return m; };
  const send = (name) => { if (!deskScr) return toast("Стол ещё не подключён", 2500); deskScr.key(name, modsOnce()); };
  const sendText = (t) => { if (!deskScr) return; deskScr.type(t, modsOnce()); };
  // экранная клавиатура: скрытое поле; буквы — на стол; Enter/⌫/Tab/Esc/стрелки — клавишами. iOS шлёт Enter как
  // beforeinput insertLineBreak/insertParagraph (keydown не всегда) — ловим оба; ⌫ в пустом поле — только keydown
  const named = { Enter: "Enter", Backspace: "Backspace", Tab: "Tab", Escape: "Escape", ArrowLeft: "Left", ArrowRight: "Right",
    ArrowUp: "Up", ArrowDown: "Down", Delete: "Delete", Home: "Home", End: "End" };
  kbd.addEventListener("keydown", (e) => {
    if (e.isComposing) return;
    if (named[e.key]) { e.preventDefault(); return send(named[e.key]); }
    if ((e.ctrlKey || e.altKey) && e.key.length === 1) {            // компьютер: Ctrl+C и т.п. с настоящей клавиатуры
      e.preventDefault(); deskScr?.type(e.key, [e.ctrlKey && "Ctrl", e.altKey && "Alt"].filter(Boolean));
    }
  });
  kbd.addEventListener("beforeinput", (e) => {
    if (e.inputType === "insertLineBreak" || e.inputType === "insertParagraph") {
      e.preventDefault(); send("Enter");           // keydown Enter уже отменён — тогда beforeinput не приходит: без двойных
    } else if (e.inputType === "deleteContentBackward" && !kbd.value) { e.preventDefault(); send("Backspace"); }
  });
  kbd.addEventListener("input", () => { if (kbd.value) { const v = kbd.value; kbd.value = ""; sendText(v); } });

  // панель скрыта — плавающий значок (перетаскивается, место запоминается)
  const fab = el.querySelector(".desk-fab");
  const hideBar = (on) => { el.classList.toggle("desk-hidden", on); fab.hidden = !on; uiSet({ hidden: on }); later(); };
  if (ui.fab) Object.assign(fab.style, { left: ui.fab[0] + "px", top: ui.fab[1] + "px", right: "auto", bottom: "auto" });
  let drag = null;
  fab.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, l: fab.offsetLeft, t: fab.offsetTop, moved: false }; try { fab.setPointerCapture(e.pointerId); } catch (_) {} });
  fab.addEventListener("pointermove", (e) => {
    if (!drag) return; const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 6) drag.moved = true;
    if (drag.moved) Object.assign(fab.style, { left: Math.max(0, Math.min(innerWidth - 48, drag.l + dx)) + "px",
      top: Math.max(0, Math.min(innerHeight - 48, drag.t + dy)) + "px", right: "auto", bottom: "auto" });
  });
  fab.addEventListener("pointerup", () => { if (drag?.moved) { uiSet({ fab: [fab.offsetLeft, fab.offsetTop] }); fab.dataset.dragged = "1"; } drag = null; });
  if (ui.hidden) hideBar(true);

  // Телефон (владелец 21.11): кнопки панели — в меню ≡, ряд клавиш — по кнопке, сайты — в мобильном виде
  const mq = matchMedia(NARROW), keysBox = el.querySelector(".desk-keys"), menuB = el.querySelector("[data-desk=menu]");
  const keysShow = (on) => { keysBox.hidden = !on; el.querySelectorAll("[data-desk=keys]").forEach((x) => x.setAttribute("aria-pressed", String(on))); };
  const menu = (on) => { el.classList.toggle("desk-menu", on); menuB.setAttribute("aria-expanded", String(on)); };
  let beat = 0, mob = false, mobT = 0;
  const mobSend = () => api("/api/desktop/mobile", mob ? { on: true, w: Math.round(innerWidth), h: Math.round(innerHeight),
    dpr: devicePixelRatio || 1 } : { on: false }).catch(() => {});       // сбой — не мешает столу; сервер ждёт 60 с
  const mobile = (on) => {                             // мобильный вид — только пока стол открыт и виден на телефоне
    on = on && !document.hidden; el.dataset.mobile = on ? "1" : "";
    if (on === mob && on) return;
    const was = mob; mob = on; clearInterval(beat); beat = 0;
    if (d.demo) return;
    if (on) { mobSend(); beat = setInterval(mobSend, BEAT); } else if (was) mobSend();
  };
  const compact = () => {
    const on = mq.matches; el.classList.toggle("desk-compact", on); menu(false);
    if (on) { el.classList.remove("desk-hidden"); fab.hidden = true; keysShow(!!uiGet().keysC); }
    else { keysShow(uiGet().keys ?? touch); if (uiGet().hidden) hideBar(true); }
    mobile(on); later();
  };
  const turn = () => { clearTimeout(mobT); mobT = setTimeout(() => { if (mob) mobSend(); }, 400); };   // поворот — новый размер
  const vis = () => mobile(mq.matches);
  mq.addEventListener("change", compact); addEventListener("resize", turn); document.addEventListener("visibilitychange", vis);
  deskOff.push(() => { mq.removeEventListener("change", compact); removeEventListener("resize", turn);
    document.removeEventListener("visibilitychange", vis); clearTimeout(mobT); mobile(false); });
  el.querySelector(".desk-stage").addEventListener("pointerdown", () => menu(false), true);   // касание стола — меню закрыть
  el.addEventListener("keydown", (e) => { if (e.key === "Escape" && el.classList.contains("desk-menu")) { e.stopPropagation(); menu(false); } });
  compact();
  el.addEventListener("click", (e) => {
    const kk = e.target.closest("[data-key]");
    if (kk) {
      const k = kk.dataset.key;
      if (k.startsWith("mod:")) { const m = k.slice(4), on = !sticky.has(m); on ? sticky.add(m) : sticky.delete(m); kk.setAttribute("aria-pressed", String(on)); return; }
      if (k.length === 1) { modsOnce(); return deskScr?.type(k, ["Ctrl"]); }   // готовые сочетания Ctrl+…
      return send(k);
    }
    const t = e.target.closest("[data-desk]"); if (!t) return;
    const k = t.dataset.desk;
    if (k === "menu") return menu(!el.classList.contains("desk-menu"));
    if (el.classList.contains("desk-menu") && t.closest(".desk-bar") && !["in", "out"].includes(k)) menu(false);   // выбрали — закрыть
    if (k === "close") return deskClose();
    if (k === "tab") return deskTab();
    if (k === "reload") { st.textContent = "подключаю…"; return deskOpen(); }
    if (k === "in") return zoom((z || fitZ()) * Z_STEP);
    if (k === "out") return zoom((z || fitZ()) / Z_STEP);
    if (k === "fit") return fit();
    if (k === "one") return zoom(1);
    if (k === "hand") return hand(pan.hidden);
    if (k === "kbd") return kbd.focus({ preventScroll: true });
    if (k === "keys") { const on = keysBox.hidden; keysShow(on); uiSet(el.classList.contains("desk-compact") ? { keysC: on } : { keys: on }); return later(); }
    if (k === "hide") return hideBar(true);
    if (k === "show") { if (t.dataset.dragged) { delete t.dataset.dragged; return; } return hideBar(false); }
    if (k.startsWith("clip")) return deskClip(el, k, t, later);
    if (k === "full") return deskFull(el);
  });

  (d.demo ? Promise.resolve(demoScreen(view, st)) : rfbScreen(view, st)).then((scr) => {
    if (deskEl !== el) return scr.close();
    deskScr = scr;
    scr.onclip = (text) => {                             // копия на столе: показать с «Скопировать» (только в памяти)
      if (!text || deskEl !== el) return;
      el.querySelector(".desk-clip-text").textContent = text.length > 300 ? text.slice(0, 300) + "…" : text;
      el.querySelector(".desk-clip-out").hidden = false; el.dataset.clip = "1"; deskClipText = text;
      if (el.querySelector(".desk-clip").hidden) toast("На столе скопирован текст — «Буфер» → «Скопировать»", 3500);
    };
    scr.onready = () => { hand(!pan.hidden); fit(); };
  }, (e) => { st.textContent = "не подключился: " + e.message; });
  haptic("impactOccurred", "light");
}

// Буфер обмена (владелец 15.11: «копия не проходит … пароль неудобно вписывать»). Текст — только в памяти страницы:
// не пишется в журналы и хранилище, поле очищается после отправки.
let deskClipText = "";
async function deskClip(el, k, t, later) {
  const box = el.querySelector(".desk-clip"), inp = el.querySelector(".desk-clip-in");
  if (k === "clip") {
    box.hidden = !box.hidden; t.setAttribute("aria-expanded", String(!box.hidden));
    if (!box.hidden) inp.focus({ preventScroll: true });
    return later();
  }
  if (k === "clip-read") {                             // Clipboard API — по нажатию (iOS иначе не даёт)
    try { inp.value = await navigator.clipboard.readText(); inp.focus(); }
    catch (_) { toast("Телефон не дал прочитать буфер — вставьте в поле долгим нажатием", 4500); inp.focus(); }
    return;
  }
  if (k === "clip-copy") {
    const ok = await navigator.clipboard?.writeText(deskClipText).then(() => true, () => false);
    if (!ok) {                                         // запасной путь: выделить и «копировать»
      const ta = Object.assign(document.createElement("textarea"), { value: deskClipText });
      ta.style.cssText = "position:fixed;left:-9999px"; document.body.append(ta); ta.select();
      try { document.execCommand("copy"); } catch (_) {} ta.remove();
    }
    return toast("Скопировано в буфер телефона", 2500);
  }
  const text = inp.value;
  if (!text) { inp.focus(); return toast("Сначала вставьте текст в поле", 3000); }
  if (!deskScr) return toast("Стол ещё не подключён", 3000);
  // буфер UTF-8 (Xvnc) — вставляем как есть; старый сервер (Latin-1) — кириллицу и эмодзи набираем клавишами
  const wide = /[^\u0000-\u00ff]/.test(text) && !deskScr.utf8, typed = k === "clip-type" || wide;
  if (typed) deskScr.type(text); else deskScr.paste(text);
  inp.value = "";
  toast(!typed ? "Вставлено на стол (Ctrl+V). Не вставилось — «Напечатать»"
    : wide && k === "clip-paste" ? "В тексте не только латиница — набрал его на столе клавишами" : "Напечатано на столе", 3500);
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
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  deskEl.remove(); deskEl = null; deskClipText = ""; document.body.classList.remove("desk-on");
  try { tg?.BackButton?.offClick(deskClose); if (typeof view !== "undefined" && view === "home") tg?.BackButton?.hide(); } catch (_) {}
}

Object.assign(window, { deskOpen, deskClose, deskTab, deskShow });
