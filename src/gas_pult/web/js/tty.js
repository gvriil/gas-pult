// Живой терминал (задача 50) — часть по требованию (#191, 17.11): перенесён из ядра, плюс эмулятор xterm.js.
// Владелец 17.11: «терминал — полноценная терминальная сессия». Причина «видно только сверху»: окно tmux без клиента
// держит default-size 80x24 — экран 24 строки по 80 знаков занимал только верх области, а панель размер окна не меняла.
// Теперь: xterm.js (цвета, курсор, ввод как в терминале), окно tmux — под размер области и шрифта (/api/tty/size),
// прокрутка до начала подгружает историю страницами. Поиск и «Журнал сессии» — прежним текстом (<pre>); эмулятор не
// загрузился (нет сети) — тоже текстом. xterm.js 6.0.0 — cdnjs, точная версия и SRI (как marked и driver.js).

const XTERM = { js: ["https://cdnjs.cloudflare.com/ajax/libs/xterm/6.0.0/xterm.js",
  "sha512-uizNIcrofW9tvPxCDN2zy3RKGesFPi8nwV0SEE480G+qUpyDaWEI9ia9lnwTitiU1DbW4wLQcA/vFrVzjgVkdw=="],
  css: ["https://cdnjs.cloudflare.com/ajax/libs/xterm/6.0.0/xterm.min.css",
  "sha512-xos4zaD4xiLA4Y3REtnCRqZx2icS1XdZdLBjXUmgqhflDB7tUtnOwKNMHuVIxnBnDUsbuJhlMIuV+exytqZYTA=="] };
let xLoading = null;
function xLoad() {
  if (window.Terminal) return Promise.resolve();
  return xLoading ||= new Promise((ok, no) => {
    const l = document.createElement("link"); l.rel = "stylesheet"; l.href = XTERM.css[0]; l.integrity = XTERM.css[1]; l.crossOrigin = "anonymous";
    const sc = document.createElement("script"); sc.src = XTERM.js[0]; sc.integrity = XTERM.js[1]; sc.crossOrigin = "anonymous";
    sc.onload = () => (window.Terminal ? ok() : no(new Error("нет Terminal"))); sc.onerror = () => { xLoading = null; no(new Error("xterm.js не загрузился")); };
    document.head.append(l, sc);
  });
}

const xcss = document.createElement("style");
xcss.textContent = `.tty .tbox .txterm { display: none; flex: 1; min-height: 0; padding: 4px 0 0 6px; background: #1E1F20; border-radius: var(--radius-md); }
.tty .tbox.xt .txterm { display: block; } .tty .tbox.xt pre { display: none; }
.tty .txterm .xterm { height: 100%; } .tty .txterm .xterm-viewport { overscroll-behavior: contain; }`;
document.head.append(xcss);

function ttyOpenX(wid) {
  if (!ttyOk()) return toast("Живой терминал — только в режиме разработчика", 4000);
  document.querySelector(".sheet-bg.ttybg")?.remove();
  const fine = matchMedia("(pointer: fine)").matches;
  const keys = [["Esc", "Escape"], ["Tab", "Tab"], ["Ctrl", "ctrl"], ["↑", "Up"], ["↓", "Down"], ["←", "Left"], ["→", "Right"], ["↵", "Enter"],
    ["PgUp", "PPage"], ["PgDn", "NPage"], ["Home", "Home"], ["End", "End"], ["⌫", "BSpace"], ["^C", "C-c"], ["^D", "C-d"], ["^R", "C-r"], ["^L", "C-l"]];
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.classList.add("ttybg"); bg.dataset.help = hv("sheet.tty");
  bg.innerHTML = `<div class="sheet tty" role="dialog" aria-label="Живой терминал">
    <div class="th"><div class="tt"><b id="ttyName">Терминал</b><small id="ttySub">загружаю…</small></div>
      <button type="button" id="ttyFind" aria-label="Поиск по истории" title="Поиск по истории (Ctrl+F)">${ic("search")}</button>
      <button type="button" id="ttyWrap" aria-label="Перенос строк" title="Перенос строк">${ic("menu")}</button>
      <button type="button" data-close aria-label="Закрыть" title="Закрыть">${ic("x")}</button></div>
    <div class="seg tmode" id="ttyMode" hidden><button type="button" data-m="tmux" class="on">История окна</button><button type="button" data-m="log">Журнал сессии</button></div>
    <div class="tf" id="ttyFindRow" hidden><input id="ttyQ" type="search" placeholder="Найти в истории" autocomplete="off" spellcheck="false" aria-label="Найти в истории">
      <span class="cnt" id="ttyCnt"></span><button type="button" id="ttyPrev" aria-label="Предыдущее совпадение">${ic("up")}</button><button type="button" id="ttyNext" aria-label="Следующее совпадение">${ic("down")}</button></div>
    <div class="term tbox" id="ttyBox" tabindex="0" aria-label="Экран терминала: щёлкните и печатайте"><div class="ttop" id="ttyTop"></div><div class="txterm" id="ttyX"></div><pre id="ttyPre"></pre></div>
    <p class="thint" id="ttyHint"></p>
    <div class="tk" id="ttyKeys">${keys.map(([l, k]) => `<button type="button" data-k="${k}"${k === "C-c" ? ' class="cc"' : ""}${k === "ctrl" ? ' aria-pressed="false"' : ""}>${esc(l)}</button>`).join("")}</div>
    <div class="tin"><input id="ttyIn" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" enterkeyhint="send" aria-label="Текст в окно" placeholder="Текст в окно — Enter отправит">
      <button type="button" id="ttySend" aria-label="Отправить и нажать Enter">${ic("send")}</button></div></div>`;
  document.body.append(bg);
  const $$ = (id) => bg.querySelector("#" + id), pre = $$("ttyPre"), box = $$("ttyBox"), inp = $$("ttyIn");
  const st = { mode: "tmux", old: [], tail: [], lo: 0, tailStart: 0, floor: 0, alive: true, kind: "", deep: false, busy: false, loading: false,
    q: "", hits: 0, hit: -1, ctrl: false, chain: Promise.resolve(), buf: "", bufT: 0, timer: 0, soonT: 0, log: null, logFirst: null, logMore: false, shown: "",
    xt: null, xl: [], xlo: 0, xshown: "", xsize: "", xfz: 0, xhold: false };
  bg.__tty = st;                                          // для тестов: состояние и эмулятор (st.xt)
  const wrapOn = () => (store("ttyWrap") || (fine ? "0" : "1")) === "1";
  box.classList.toggle("wrap", wrapOn()); $$("ttyWrap").classList.toggle("on", wrapOn());
  const lines = () => (st.mode === "log" ? st.log || [] : [...st.old, ...st.tail]);
  const atBottom = () => pre.scrollHeight - pre.scrollTop - pre.clientHeight < 40;
  const hint = (m, bad) => { const h = $$("ttyHint"); h.textContent = m || ""; h.classList.toggle("bad", !!bad); };
  const baseHint = () => hint(fine ? "Щёлкните по экрану и печатайте: клавиши уходят прямо в окно. Ctrl+F — поиск по истории." : "Текст — в строке внизу, Enter отправит; спецклавиши — над ней. Ctrl — нажмите, затем букву.");
  function top() {                                         // что выше загруженного: ещё страницы, начало истории, журнал
    const t = $$("ttyTop"), canLog = st.kind === "session" || st.kind === "stopped";
    const logBtn = canLog && st.mode === "tmux" ? `<button type="button" data-tlog>Раньше — журнал сессии</button>` : "";
    if (st.mode === "log") t.innerHTML = st.logMore ? `<button type="button" data-tmore>Показать раньше</button>` : "Начало журнала сессии.";
    else if (!st.alive) t.innerHTML = `Окна больше нет — истории tmux нет.${logBtn}`;
    else if (st.lo > st.floor) t.innerHTML = `Выше ещё ${st.lo - st.floor} строк <button type="button" data-tmore>Показать</button>`;
    else t.innerHTML = (st.floor > 0 ? "Глубже 20 000 строк история окна не показывается." : "Начало истории окна: раньше tmux не помнит.") + logBtn;
  }
  function render(how = {}) {                               // how: {stick: вниз, prepend: сохранить место}
    const L = lines(), q = st.q.toLowerCase();
    let html, n = 0;
    if (!q) html = esc(L.join("\n"));
    else html = L.map((ln) => {
      const low = ln.toLowerCase(); let out = "", p = 0, j;
      while ((j = low.indexOf(q, p)) !== -1) { out += esc(ln.slice(p, j)) + `<mark data-h="${n++}">${esc(ln.slice(j, j + q.length))}</mark>`; p = j + q.length; }
      return out + esc(ln.slice(p));
    }).join("\n");
    st.hits = n; top();
    if (html === st.shown && !how.force) return;
    const stick = how.stick ?? atBottom(), h0 = pre.scrollHeight, t0 = pre.scrollTop;
    pre.innerHTML = html || (st.mode === "log" ? "Журнал пуст." : ""); st.shown = html;
    if (how.prepend) pre.scrollTop = t0 + (pre.scrollHeight - h0);
    else if (stick) pre.scrollTop = pre.scrollHeight;
    count(false);
  }
  function count(go) {                                      // «3 из 12» и подсветка текущего совпадения
    if (st.hit >= st.hits) st.hit = st.hits - 1;
    $$("ttyCnt").textContent = !st.q ? "" : st.hits ? `${st.hit + 1} из ${st.hits}` : "нет";
    pre.querySelector("mark.cur")?.classList.remove("cur");
    const m = st.hit >= 0 && pre.querySelector(`mark[data-h="${st.hit}"]`);
    if (m) { m.classList.add("cur"); if (go) m.scrollIntoView({ block: "center", inline: "nearest" }); }
  }
  const get = (extra = "") => api(`/api/tty?w=${encodeURIComponent(wid)}${extra}`);
  function head(d) {
    st.kind = d.kind || st.kind; $$("ttyName").textContent = d.name || wid;
    const rows = d.total ? `строк в истории: ${d.history ?? 0}` : "";
    $$("ttySub").textContent = [TTY_KIND[st.kind] || "окно", rows].filter(Boolean).join(" · ");
    $$("ttyMode").hidden = !(st.kind === "session" || st.kind === "stopped");
  }
  function take(d, fresh) {                                  // строки выше экрана (cut) — копим, экран — заменяем
    st.alive = d.alive !== false; st.floor = d.floor || 0;
    if (!st.alive) { st.tail = []; return; }
    if (fresh) { st.old = d.lines.slice(0, d.cut); st.lo = d.start; } else st.old.push(...d.lines.slice(0, d.cut));
    st.tail = d.lines.slice(d.cut); st.tailStart = Math.max(d.start, d.history || 0);
    if (st.old.length > 30000) { st.old = st.old.slice(-20000); st.lo = st.tailStart - 20000; st.deep = true; }
  }
  async function poll(first) {
    if (!bg.isConnected) return clearInterval(st.timer);
    if (st.mode !== "tmux" || st.busy || st.loading || document.hidden) return;
    if (xOn()) return xPoll();
    st.busy = true;
    try {
      const fresh = first || (atBottom() && !st.q && !st.deep);   // внизу — свежий хвост; прокрутили вверх — дописываем
      const d = await get(fresh ? "" : "&start=" + st.tailStart);
      head(d); take(d, fresh); render(first ? { stick: true } : {}); loginNotice(d.login, wid);
    } catch (e) { hint(e.message, true); } finally { st.busy = false; }
  }
  const soon = () => { clearTimeout(st.soonT); st.soonT = setTimeout(() => poll(), 250); };
  async function older(all) {                               // страница выше (all — всё выше, для поиска)
    if (st.mode !== "tmux" || st.loading || st.lo <= st.floor) return;
    st.loading = true;
    try {
      const d = await get(`&end=${st.lo}${all ? "&all=1" : ""}`);
      st.old = [...d.lines, ...st.old]; st.lo = d.start; st.floor = d.floor || 0; st.deep = true;
      render({ prepend: true, force: true });
    } catch (e) { hint(e.message, true); } finally { st.loading = false; }
  }
  async function logLoad(more) {                            // журнал сессии: переписка из транскрипта Claude Code
    if (st.loading) return;
    st.loading = true;
    try {
      const h = await api(`/api/history?w=${encodeURIComponent(wid)}${more && st.logFirst != null ? "&before=" + st.logFirst : ""}`);
      const L = (h.items || []).flatMap((it) => [`── ${it.ts || ""} · ${it.role === "user" ? "вы" : "Claude"} ──`, ...String(it.text || "").split("\n"), ""]);
      st.log = more ? [...L, ...(st.log || [])] : L; st.logFirst = h.items?.[0]?.i ?? st.logFirst; st.logMore = !!h.more;
      render(more ? { prepend: true, force: true } : { stick: true, force: true });
    } catch (e) { st.log = st.log || []; st.logMore = false; hint(e.message, true); render({ force: true }); } finally { st.loading = false; }
  }
  function mode(m) {
    st.mode = m; st.shown = ""; xView();
    $$("ttyMode").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.m === m));
    if (m === "log" && !st.log) return logLoad(false);
    render({ stick: true, force: true }); if (m === "tmux") poll();
  }
  // ввод: по порядку — текст копится 40 мс и уходит одним запросом, клавиша — после текста
  const send = (path, body) => { st.chain = st.chain.then(() => api(path, { w: wid, ...body })).then(() => { if ($$("ttyHint").classList.contains("bad")) baseHint(); soon(); }, (e) => hint(e.message, true)); };
  const flush = () => { clearTimeout(st.bufT); if (st.buf) { send("/api/tty/type", { text: st.buf }); st.buf = ""; } };
  const typeCh = (ch) => { st.buf += ch; clearTimeout(st.bufT); st.bufT = setTimeout(flush, 40); };
  const key = (k) => { flush(); haptic("impactOccurred", "light"); send("/api/tty/key", { key: k }); };
  const ctrl = (on) => { st.ctrl = on; const b = bg.querySelector('[data-k="ctrl"]'); b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); };
  const ctrlKey = (ch) => { ctrl(false); const c = ch.toLowerCase(); if (TTY_CTRL.includes(c)) key("C-" + c); else hint(`Ctrl+${ch} в окно не отправляется`, true); };
  box.addEventListener("keydown", (e) => {
    if (e.isComposing || st.mode !== "tmux") return;
    if (e.target.closest?.(".txterm")) {                     // в эмуляторе: Ctrl+F — поиск, остальное — его onData
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") { e.preventDefault(); find(true); }
      return;
    }
    const k = e.key, low = k.length === 1 ? k.toLowerCase() : "";
    if ((e.ctrlKey || e.metaKey) && low === "f") { e.preventDefault(); return find(true); }
    if (e.metaKey || e.altKey) return;                       // Cmd+C / Cmd+V и прочее — браузеру
    if (e.ctrlKey && low === "c" && String(getSelection())) return;   // выделили текст — Ctrl+C копирует
    if (e.ctrlKey && low === "v") return;                    // вставка — событием paste
    if (e.ctrlKey && low) { e.preventDefault(); return ctrlKey(low); }
    if (TTY_MAP[k]) { e.preventDefault(); e.stopPropagation(); ctrl(false); return key(k === "Tab" && e.shiftKey ? "BTab" : TTY_MAP[k]); }
    if (k.length === 1 && !e.ctrlKey) { e.preventDefault(); if (st.ctrl) return ctrlKey(k); typeCh(k); }
  });
  box.addEventListener("paste", (e) => { const t = e.clipboardData?.getData("text"); if (t && st.mode === "tmux") { e.preventDefault(); flush(); send("/api/tty/type", { text: t }); } });
  box.addEventListener("focus", () => box.classList.add("live")); box.addEventListener("blur", () => box.classList.remove("live"));
  inp.addEventListener("input", () => { if (st.ctrl && inp.value) { const ch = inp.value.slice(-1); inp.value = inp.value.slice(0, -1); ctrlKey(ch); } });
  const submit = () => { const t = inp.value; inp.value = ""; if (t) send("/api/tty/type", { text: t }); key("Enter"); };
  inp.addEventListener("keydown", (e) => {
    if (e.isComposing) return;
    if (e.key === "Enter") { e.preventDefault(); return submit(); }
    if (!inp.value && TTY_MAP[e.key]) { e.preventDefault(); e.stopPropagation(); key(e.key === "Tab" && e.shiftKey ? "BTab" : TTY_MAP[e.key]); }   // пустая строка — стрелки, Esc, Tab, ⌫ — в окно
  });
  $$("ttySend").onclick = submit;
  const tk = $$("ttyKeys");
  tk.addEventListener("pointerdown", (e) => { if (e.target.closest("button")) e.preventDefault(); });   // клавиатура телефона не закрывается
  tk.addEventListener("click", (e) => {
    const b = e.target.closest("[data-k]"); if (!b) return;
    if (b.dataset.k === "ctrl") return ctrl(!st.ctrl);
    ctrl(false); key(b.dataset.k);
  });
  // поиск по истории: сначала догружаем всё, что выше (до 20 тысяч строк), потом подсвечиваем
  let qT = 0;
  function find(open) {
    const row = $$("ttyFindRow"); row.hidden = open === undefined ? !row.hidden : !open;
    $$("ttyFind").classList.toggle("on", !row.hidden);
    xView();                                               // поиск — по тексту истории; закрыли — снова эмулятор
    if (!row.hidden) return $$("ttyQ").focus();
    st.q = ""; $$("ttyQ").value = ""; st.hit = -1; render({ force: true });
  }
  $$("ttyFind").onclick = () => find();
  $$("ttyQ").addEventListener("input", () => { clearTimeout(qT); qT = setTimeout(async () => {
    st.q = $$("ttyQ").value.trim();
    if (st.q && st.mode === "tmux" && st.lo > st.floor) await older(true);
    for (let i = 0; st.q && st.mode === "log" && st.logMore && i < 30; i++) await logLoad(true);
    render({ force: true }); st.hit = st.hits - 1; count(true);           // ближайшее к концу — первым
  }, 250); });
  const step = (d) => { if (!st.hits) return; st.hit = (st.hit + d + st.hits) % st.hits; count(true); };
  $$("ttyPrev").onclick = () => step(-1); $$("ttyNext").onclick = () => step(1);
  $$("ttyQ").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); step(e.shiftKey ? 1 : -1); } if (e.key === "Escape") { e.stopPropagation(); find(false); box.focus(); } });
  $$("ttyWrap").onclick = () => { const on = !wrapOn(); store("ttyWrap", on ? "1" : "0"); box.classList.toggle("wrap", on); $$("ttyWrap").classList.toggle("on", on); };
  $$("ttyMode").addEventListener("click", (e) => { const b = e.target.closest("[data-m]"); if (b && b.dataset.m !== st.mode) mode(b.dataset.m); });
  pre.addEventListener("scroll", () => { if (pre.scrollTop < 60) { if (st.mode === "tmux") older(false); else if (st.logMore) logLoad(true); } });
  bg.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) {
      clearInterval(st.timer); st.ro?.disconnect(); st.xt?.dispose();
      if (st.xsize) api("/api/tty/size", { w: wid, reset: true }).catch(() => {});   // окно — снова по клиентам tmux
      return bg.remove();
    }
    if (e.target.closest("[data-tlog]")) return mode("log");
    if (e.target.closest("[data-tmore]")) return xOn() ? xOlder() : st.mode === "tmux" ? older(false) : logLoad(true);
    if (e.target.closest("#ttyBox") && fine && !String(getSelection())) box.focus({ preventScroll: true });
  });
  // ---------- эмулятор (xterm.js, 17.11): цвета, курсор, ввод как в терминале; размер окна — под область ----------
  const xOn = () => !!st.xt && st.mode === "tmux" && $$("ttyFindRow").hidden;
  function xView() { box.classList.toggle("xt", xOn()); if (xOn()) { st.xshown = ""; xFit(); xPoll(); } else { render({ force: true, stick: true }); if (st.mode === "tmux") poll(); } }
  const xFz = () => Math.round(13 * (parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--fz")) || 1));
  function xFit() {                                       // колонки и строки — по размеру знака; окно tmux — под них
    const t = st.xt, el = $$("ttyX"); if (!t || !el.clientWidth) return;
    if (st.xfz !== xFz()) {                                // другой масштаб (A+/A−): размер знака — после отрисовки
      st.xfz = xFz(); t.options.fontSize = st.xfz; return requestAnimationFrame(() => setTimeout(xFit, 30));
    }
    const c = t._core?._renderService?.dimensions?.css?.cell, cw = c?.width || st.xfz * 0.6, ch = c?.height || st.xfz * 1.2;
    const cols = Math.max(20, Math.floor((el.clientWidth - 4) / cw)), rows = Math.max(5, Math.floor((el.clientHeight - 2) / ch));
    if (cols !== t.cols || rows !== t.rows) t.resize(cols, rows);
    const k = cols + "x" + rows; if (k === st.xsize) return;
    st.xsize = k; clearTimeout(st.xsT);
    st.xsT = setTimeout(() => api("/api/tty/size", { w: wid, cols, rows }).then(() => { st.xshown = ""; xPoll(); }, (e) => hint(e.message, true)), 300);
  }
  const xAtEnd = () => { const b = st.xt.buffer.active; return b.viewportY >= b.baseY; };
  function xPaint(cx, cy, height, cursor) {               // весь текст заново (история + экран), курсор — на место
    const t = st.xt, text = st.xl.join("\r\n"); if (text === st.xshown && !cursor?.force) return;
    st.xshown = text; st.xpaint = true; t.reset();          // своя перерисовка — не «прокрутили до верха»
    const row = t.rows - Math.min(height || t.rows, t.rows) + cy + 1;
    t.write(text + `\x1b[${Math.max(1, row)};${cx + 1}H` + (cursor === false ? "\x1b[?25l" : "\x1b[?25h"),
      () => { t.scrollToBottom(); st.xpaint = false; });
  }
  async function xPoll() {                                 // внизу — свежий экран; прокрутили вверх — не мешаем
    if (!xOn() || st.busy || st.loading || st.xhold || !bg.isConnected) return;
    if (st.xfz !== xFz()) xFit();
    if (st.xl.length && !xAtEnd()) return;
    st.busy = true;
    try {
      const d = await get("&color=1"); head(d); st.alive = d.alive !== false; st.floor = d.floor || 0;
      if (!st.alive) { st.xl = []; st.xt.reset(); st.xt.write("Окна больше нет."); return; }
      st.xl = d.lines; st.xlo = d.start; st.lo = d.start; top(); xPaint(d.cx || 0, d.cy || 0, d.height, d.cursor);
      loginNotice(d.login, wid);
    } catch (e) { hint(e.message, true); } finally { st.busy = false; }
  }
  async function xOlder() {                                // прокрутили до верха — страница выше, место не прыгает
    if (!xOn() || st.loading || st.xlo <= st.floor) return;
    st.loading = st.xhold = true;
    try {
      const d = await get(`&end=${st.xlo}&color=1`), n = d.lines.length; if (!n) return;
      st.xl = [...d.lines, ...st.xl]; st.xlo = st.lo = d.start; st.xshown = ""; top();
      st.xpaint = true; st.xt.reset();
      st.xt.write(st.xl.join("\r\n"), () => { st.xt.scrollToLine(n); st.xpaint = false; }); st.xshown = st.xl.join("\r\n");
    } catch (e) { hint(e.message, true); } finally { st.loading = false; }
  }
  const XMAP = { "\r": "Enter", "\x7f": "BSpace", "\b": "BSpace", "\t": "Tab", "\x1b": "Escape", "\x1b[A": "Up", "\x1b[B": "Down",
    "\x1b[C": "Right", "\x1b[D": "Left", "\x1bOA": "Up", "\x1bOB": "Down", "\x1bOC": "Right", "\x1bOD": "Left", "\x1b[H": "Home",
    "\x1b[F": "End", "\x1bOH": "Home", "\x1bOF": "End", "\x1b[5~": "PPage", "\x1b[6~": "NPage", "\x1b[3~": "DC", "\x1b[Z": "BTab" };
  function xInput(data) {                                  // нажатия эмулятора → те же /api/tty/type и /api/tty/key
    if (XMAP[data]) return key(XMAP[data]);
    if (data.length === 1 && data.charCodeAt(0) < 27) return ctrlKey(String.fromCharCode(96 + data.charCodeAt(0)));
    if (/^\x1b/.test(data)) return;                        // прочие последовательности — не шлём вслепую
    for (const ch of data.replace(/\r\n?/g, "\n")) ch === "\n" ? key("Enter") : typeCh(ch);
  }
  function xStart() {
    if (!window.Terminal || st.xt) return;
    const t = st.xt = new Terminal({ fontSize: xFz(), fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", scrollback: 25000,
      convertEol: false, cursorBlink: true, theme: { background: "#1E1F20", foreground: "#E8EAED", cursor: "#E8EAED" } });
    t.open($$("ttyX")); st.xfz = xFz();
    t.onData(xInput);
    t.onScroll(() => {                                    // только прокрутка человеком: до верха — страница выше
      if (st.xpaint) return;
      const b = t.buffer.active;
      if (b.viewportY === 0 && b.baseY > 0) xOlder();
      if (xAtEnd() && st.xhold) { st.xhold = false; st.xshown = ""; xPoll(); }
    });
    st.ro = new ResizeObserver(() => xFit()); st.ro.observe($$("ttyX"));
    xView(); if (fine) setTimeout(() => t.focus(), 50);
  }
  baseHint(); poll(true); st.timer = setInterval(() => poll(), 1500);
  if (!params.has("ttytext")) xLoad().then(xStart, () => hint("Эмулятор не загрузился — показываю текстом", false));
  if (fine) setTimeout(() => box.focus({ preventScroll: true }), 50);
}

Object.assign(window, { ttyOpenX });
