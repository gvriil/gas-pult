// ---------- команде нужен ввод (задача 47): не «Выполнить» вслепую, а окно терминала панели ----------
// keepassxc-cli, sudo с паролем, ssh, passwd, read -s … — сервер открывает окно tmux «gp-term» и запускает команду там.
// Пароль вводится здесь, в браузере: строка уходит прямо в окно (буфер tmux удаляется сразу) и нигде не хранится.
// В Telegram (Mini App) пароль не вводим — только смотрим экран; ввод — в браузере или в терминале (Termius).
async function termOpen(btn, path, body, cmd) {
  const go = (confirmed) => busy(btn, "Открываю…", async () => {
    try {
      const r = await api(path, { ...body, confirmed });
      if (r.confirm) return confirmDanger("Команда меняет или удаляет данные:\n\n" + cmd.slice(0, 600) + "\n\nОткрыть в терминале и выполнить?", () => go(true));
      termSheet(r.id);
    } catch (e) { toast(e.message, 5000); }
  });
  return go(false);
}
function termSheet(id) {
  document.querySelector(".sheet-bg.termsheet")?.remove();
  const inTg = !!tg?.initData;
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.classList.add("termsheet"); bg.dataset.help = hv("cmd.terminal");
  bg.innerHTML = `<div class="sheet" role="dialog"><h3>Терминал</h3>
    <p class="note" style="margin:4px 16px 8px">Команда запущена в окне «gp-term» на сервере. ${inTg ? "Пароль в Telegram не вводим — откройте панель в браузере или терминал (Termius)." : "Спросит пароль — введите его ниже: он уйдёт прямо в окно и нигде не сохранится."}</p>
    <div class="term" style="margin:0 16px"><pre id="twScreen">…</pre></div>
    ${inTg ? `<div class="row2"><button class="btn ghost" data-close>Закрыть</button><button class="btn" id="twBrowser">${ic("ext")}Открыть в браузере</button></div>`
      : `<div class="field" style="margin:10px 16px 0"><input id="twIn" type="password" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="пароль или ответ — Enter отправит"></div>
    <label class="note" style="margin:6px 16px 0;display:flex;gap:6px;align-items:center"><input type="checkbox" id="twShow">показывать, что ввожу</label>
    <p class="note" id="twErr" style="margin:6px 16px 0"></p>
    <div class="row2"><button class="btn ghost" id="twCc">Ctrl+C</button><button class="btn" id="twSend">${ic("key")}Отправить</button></div>`}
    ${ttyOk() ? `<div class="row2"><button class="btn ghost" id="twLive">${ic("term")}Живой терминал: клавиши и вся история</button></div>` : ""}
    <div class="row2"><button class="btn ghost danger" id="twKill">Закрыть окно на сервере</button><button class="btn ghost" data-close>Свернуть</button></div></div>`;
  document.body.append(bg);
  let timer = null, alive = true;
  const stop = () => { clearInterval(timer); const i = $("twIn"); if (i) i.value = ""; bg.remove(); };
  const err = (m) => { const e = $("twErr"); if (e) { e.textContent = m; e.style.color = "var(--status-danger)"; } else toast(m, 4000); };
  const poll = async () => {
    if (!bg.isConnected) return clearInterval(timer);
    try {
      const d = await api("/api/term?id=" + encodeURIComponent(id)); alive = d.alive;
      $("twScreen").textContent = d.alive ? (d.lines || []).slice(-30).join("\n") || "…" : "Окно закрыто — команда завершилась.";
      if (!d.alive) { clearInterval(timer); bg.querySelectorAll("#twIn, #twSend, #twCc, #twKill").forEach((x) => { x.disabled = true; }); }
    } catch (e) { $("twScreen").textContent = e.message; }
  };
  poll(); timer = setInterval(poll, 1500);
  const inp = $("twIn");
  if (inp) {
    inp.focus();
    $("twShow").onchange = (e) => { inp.type = e.target.checked ? "text" : "password"; };
    const send = () => busy($("twSend"), "Отправляю…", async () => {
      try { await api("/api/term/type", { id, text: inp.value }); inp.value = ""; $("twErr").textContent = ""; setTimeout(poll, 600); } catch (e) { err(e.message); }
    });
    $("twSend").onclick = send;
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); send(); } });
    $("twCc").onclick = async () => { try { await api("/api/term/key", { id, key: "C-c" }); setTimeout(poll, 600); } catch (e) { err(e.message); } };
  }
  $("twLive")?.addEventListener("click", () => { stop(); ttyOpen(id); });
  $("twBrowser")?.addEventListener("click", () => openUrl(location.origin + location.pathname + "?term=" + encodeURIComponent(id)));
  $("twKill").onclick = async () => { if (alive) { try { await api("/api/term/close", { id }); } catch (e) { /* окна уже нет */ } } stop(); };
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) stop(); });
}
// ---------- живой терминал (задача 50): клавиши и текст прямо в окно, вся история, поиск ----------
// Один лист для окна сессии и для окна gp-term. История tmux — страницами вверх (до 20 тысяч строк, секреты скрыты
// сервером), поиск с подсветкой; «Журнал сессии» — переписка из транскрипта, если окно пересоздано и истории tmux
// нет. Компьютер: щёлкните по экрану и печатайте — клавиши уходят в окно. Телефон: строка ввода и спецклавиши,
// Ctrl — липкий (нажали Ctrl, затем букву). Только режим разработчика (meta.tty): не в простом режиме и не в фокусе.
const TTY_MAP = { ArrowUp: "Up", ArrowDown: "Down", ArrowLeft: "Left", ArrowRight: "Right", Escape: "Escape", Tab: "Tab",
  Enter: "Enter", Backspace: "BSpace", Delete: "DC", Home: "Home", End: "End", PageUp: "PPage", PageDown: "NPage" };
const TTY_CTRL = "cdzlraeukwpnotbfgy";                  // Ctrl+буква — как в белом списке сервера (termwin.TTY_KEYS)
const TTY_KIND = { session: "сессия", stopped: "сессия остановлена — командная строка", term: "окно ввода gp-term", shell: "окно tmux" };
const ttyOk = () => !!meta?.tty && !FOCUS && !UI?.simple && !SIM.on;
function ttyOpen(wid) {
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
    <div class="term tbox" id="ttyBox" tabindex="0" aria-label="Экран терминала: щёлкните и печатайте"><div class="ttop" id="ttyTop"></div><pre id="ttyPre"></pre></div>
    <p class="thint" id="ttyHint"></p>
    <div class="tk" id="ttyKeys">${keys.map(([l, k]) => `<button type="button" data-k="${k}"${k === "C-c" ? ' class="cc"' : ""}${k === "ctrl" ? ' aria-pressed="false"' : ""}>${esc(l)}</button>`).join("")}</div>
    <div class="tin"><input id="ttyIn" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" enterkeyhint="send" aria-label="Текст в окно" placeholder="Текст в окно — Enter отправит">
      <button type="button" id="ttySend" aria-label="Отправить и нажать Enter">${ic("send")}</button></div></div>`;
  document.body.append(bg);
  const $$ = (id) => bg.querySelector("#" + id), pre = $$("ttyPre"), box = $$("ttyBox"), inp = $$("ttyIn");
  const st = { mode: "tmux", old: [], tail: [], lo: 0, tailStart: 0, floor: 0, alive: true, kind: "", deep: false, busy: false, loading: false,
    q: "", hits: 0, hit: -1, ctrl: false, chain: Promise.resolve(), buf: "", bufT: 0, timer: 0, soonT: 0, log: null, logFirst: null, logMore: false, shown: "" };
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
    st.mode = m; st.shown = "";
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
    if (e.target.closest("[data-close]")) { clearInterval(st.timer); return bg.remove(); }
    if (e.target.closest("[data-tlog]")) return mode("log");
    if (e.target.closest("[data-tmore]")) return st.mode === "tmux" ? older(false) : logLoad(true);
    if (e.target.closest("#ttyBox") && fine && !String(getSelection())) box.focus({ preventScroll: true });
  });
  baseHint(); poll(true); st.timer = setInterval(() => poll(), 1500);
  if (fine) setTimeout(() => box.focus({ preventScroll: true }), 50);
}
// space-sessions:start — сессии демо-пространства (задача 32): своя папка; «Закрыть» — агент выходит, папка и разговор
// остаются; «Продолжить» — тот же разговор; «Удалить» — в корзину пространства на N дней. Тексты — T(): и простой режим.
const ssBody = (slug, b = {}) => (meta?.role === "owner" && slug ? { ...b, space: slug } : b);
const ssDate = (x) => new Date(x * 1000).toLocaleDateString(LANG === "en" ? "en-GB" : "ru-RU", { day: "numeric", month: "long" });
function ssErr(bg, e) { const er = bg.querySelector(".ss-err"); if (er) { er.textContent = e.message; er.style.color = "var(--status-danger)"; } else toast(e.message, 5000); }
function ssNew(after) {                                  // имя → своя папка → сессия
  const bg = sSheet(hv("sheet.space-new"), T("ss.new.title"), `<p>${esc(T("ss.new.text"))}</p>
    <div class="field"><input id="ssName" maxlength="60" autocomplete="off" placeholder="${esc(T("ss.new.ph"))}"></div><p class="note ss-err"></p>
    <button class="btn wide" type="button" data-ssgo="1">${ic("plus")}${esc(T("ss.new.go"))}</button>`, (b) => b.dataset.ssgo && go(b));
  const inp = bg.querySelector("#ssName"); setTimeout(() => inp.focus(), 50);
  inp.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); go(bg.querySelector("[data-ssgo]")); } });
  function go(b) {
    return busy(b, T("s.new.wait"), async () => {
      try { const r = await api("/api/new", { i: 0, name: inp.value.trim() }); bg.remove(); toast(T("ss.new.done", { n: r.name }), 3500); after ? after(r.id) : (await refresh(), openSession(r.id)); }
      catch (e) { ssErr(bg, e); }
    });
  }
}
function ssClose(s, done) {                              // s: {id, name, space}; done — после закрытия (например, «Удалить»)
  sSheet(hv("sheet.space-close"), T("ss.close.title", { n: s.name }), `<ul class="s-notes"><li>${esc(T("ss.close.what"))}</li>
    <li>${esc(T("ss.close.keep"))}</li><li>${esc(T("ss.close.lost"))}</li></ul>
    <button class="btn wide" type="button" data-ssok="1">${ic("power")}${esc(T("ss.close.go"))}</button>`, (b, bg) => b.dataset.ssok && run(b, bg, false));
  function run(b, bg, force) {
    return busy(b, T("ss.close.wait"), async () => {
      try {
        const d = await api("/api/space/close", ssBody(s.space, { w: s.id, force }));
        bg.remove();
        if (d.result === "busy" && !force) {          // агент работает — спросить «прервать работу?»
          return sSheet(hv("sheet.space-close"), T("ss.busy.title"), `<p>${esc(T("ss.busy.text"))}</p>
            <button class="btn danger wide" type="button" data-ssforce="1">${ic("stop")}${esc(T("ss.busy.go"))}</button>`, (b2, bg2) => b2.dataset.ssforce && run(b2, bg2, true), T("ss.busy.no"));
        }
        if (d.result !== "closed") return toast(T("ss.close.not"), 5000);
        toast(d.draft ? T("ss.close.draft") : T("ss.close.done"), 5000);
        if (FOCUS) return focusGone();
        if (s.id === current) back(); else refresh();
        if (meta?.space) sLoad?.();
        done && done(d.folder);
      } catch (e) { toast(e.message, 5000); }
    });
  }
}
function ssDelete(slug, folder, keep) {                  // два шага: что произойдёт → ввести имя
  sSheet(hv("sheet.space-delete"), T("ss.del.title", { n: folder }), `<ul class="s-notes"><li>${esc(T("ss.del.what", { d: keep || 14 }))}</li>
    <li>${esc(T("ss.del.after"))}</li><li>${esc(T("ss.del.lost"))}</li></ul>
    <button class="btn danger wide" type="button" data-ssnext="1">${ic("trash")}${esc(T("ss.del.next"))}</button>`, (b, bg) => { if (b.dataset.ssnext) { bg.remove(); step2(); } });
  function step2() {
    const bg = sSheet(hv("sheet.space-delete"), T("ss.del.confirm"), `<p>${esc(T("ss.del.type", { n: folder }))}</p>
      <div class="field"><input id="ssConfirm" maxlength="60" autocomplete="off" autocapitalize="off" spellcheck="false"></div><p class="note ss-err"></p>
      <button class="btn danger wide" type="button" data-ssdel="1" disabled>${ic("trash")}${esc(T("ss.del.go"))}</button>`, (b) => b.dataset.ssdel && go(b));
    const inp = bg.querySelector("#ssConfirm"), btn = bg.querySelector("[data-ssdel]");
    inp.addEventListener("input", () => { btn.disabled = inp.value.trim() !== folder; });
    setTimeout(() => inp.focus(), 50);
    function go(b) {
      return busy(b, T("ss.del.wait"), async () => {
        try { const d = await api("/api/space/delete", ssBody(slug, { folder, confirm: inp.value.trim() })); bg.remove();
              toast(T("ss.del.done", { d: ssDate(d.until) }), 5000); refresh(); }
        catch (e) { ssErr(bg, e); }
      });
    }
  }
}
async function ssResume(slug, folder, b) {
  const go = async () => {
    try {
      const d = await api("/api/space/resume", ssBody(slug, { folder }));
      document.querySelectorAll(".sheet-bg").forEach((x) => x.remove());
      if (meta?.space && SIM.on) { await sLoad(); sPick(d.id); } else { await refresh(); openSession(d.id); }
      toast(d.continued ? T("ss.res.done") : T("ss.res.fresh"), 4000);
      if (d.draft) setTimeout(() => {                   // черновик, сохранённый при «Закрыть», — обратно в поле
        for (const id of ["sInput", "input"]) { const el = $(id); if (el && !el.value) { el.value = d.draft; fitLines(el); } }
        toast(T("ss.res.draft"), 4000);
      }, 400);
    } catch (e) { toast(e.message, 5000); }
  };
  return b ? busy(b, T("ss.res.wait"), go) : go();
}
async function ssClosed(slug) {                          // «Закрытые и корзина»
  let d; try { d = await api("/api/space/sessions" + (meta?.role === "owner" && slug ? "?space=" + encodeURIComponent(slug) : "")); } catch (e) { return toast(e.message, 5000); }
  const now = nowSec();
  const closed = (d.closed || []).map((x) => `<div class="ss-row"><b>${esc(x.folder)}</b><small>${esc(T("ss.list.when", { t: agoText(x.changed, now, true) }))}${x.draft ? " · " + esc(T("ss.list.draft")) : ""}</small>
      <div class="scn-opts">${sChip(true, `data-ssres="${esc(x.folder)}"`, T(x.history ? "ss.res.go" : "ss.res.open"), ic("refresh"))}${sChip(false, `data-ssdel="${esc(x.folder)}"`, T("ss.del.short"), ic("trash"))}</div></div>`).join("");
  const trash = (d.trash || []).map((x) => `<div class="ss-row"><b>${esc(x.folder)}</b><small>${esc(T("ss.trash.until", { d: ssDate(x.until) }))}</small>
      <div class="scn-opts">${sChip(false, `data-ssrest="${esc(x.id)}"`, T("ss.trash.restore"), ic("refresh"))}</div></div>`).join("");
  sSheet(hv("sheet.space-closed"), T("ss.list.title"), `<p class="note">${esc(T("ss.list.hint"))}</p>${closed || `<p class="note">${esc(T("ss.list.empty"))}</p>`}
    ${trash ? `<p class="s-lbl">${esc(T("ss.trash.title", { d: d.keep_days }))}</p>${trash}` : ""}`, async (b, bg) => {
    if (b.dataset.ssres) return ssResume(slug, b.dataset.ssres, b);
    if (b.dataset.ssdel) { bg.remove(); return ssDelete(slug, b.dataset.ssdel, d.keep_days); }
    if (b.dataset.ssrest) return busy(b, T("ss.res.wait"), async () => {
      try { const r = await api("/api/space/restore", ssBody(slug, { id: b.dataset.ssrest })); bg.remove(); toast(T("ss.trash.done", { n: r.folder }), 4000); ssClosed(slug); }
      catch (e) { toast(e.message, 5000); }
    });
  });
}
function ssPickSpace(fn) {                               // владелец: из какого пространства
  const list = spacesInfo?.tenants || [];
  if (list.length === 1) return fn(list[0].slug);
  sheet(T("ss.pick"), list.map((x) => ({ label: x.title || x.slug, icon: "flask", run: () => fn(x.slug) })));
}
// space-sessions:end
// space-files:start — файлы сессии демо-пространства (задача 32, п. 4): в папку сессии и обратно, через сервер пульта.
// Скачивание — fetch с подписью (в Mini App куки нет) → файл; имена — с кириллицей. Тексты — T().
const sfSize = (n) => n >= 1 << 20 ? (n / (1 << 20)).toFixed(1) + " MB" : n >= 1024 ? Math.round(n / 1024) + " KB" : n + " B";
function sfPut(w, f, name) {
  if (f.size > 50 * 1024 * 1024) return Promise.reject(new Error(T("sf.too_big", { n: name || f.name })));
  return api("/api/space/upload?w=" + encodeURIComponent(w), f, f.type || "application/octet-stream", { "X-File-Name": encodeURIComponent(name || f.name || "file") });
}
async function sfGet(w, name, b) {
  const go = async () => {
    try {
      const blob = await api("/api/space/download?w=" + encodeURIComponent(w) + "&f=" + encodeURIComponent(name));
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name.split("/").pop();
      document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 30000);
      toast(T("sf.get.done", { n: a.download }), 3500);
    } catch (e) { toast(e.message, 5000); }
  };
  return b ? busy(b, T("sf.get.wait"), go) : go();
}
async function sfFiles(w) {
  if (!w) return;
  let d; try { d = await api("/api/space/files?w=" + encodeURIComponent(w)); } catch (e) { return toast(e.message, 5000); }
  const now = nowSec();
  const rows = (d.files || []).map((x) => `<div class="ss-row"><b>${esc(x.name)}</b><small>${esc(sfSize(x.size))} · ${esc(agoText(x.changed, now, true))}</small>
      <div class="scn-opts">${sChip(false, `data-sfget="${esc(x.name)}"`, T("sf.get"), ic("down"))}</div></div>`).join("");
  const bg = sSheet(hv("sheet.space-files"), T("sf.title"), `<p class="note">${esc(T("sf.hint"))}${d.free != null ? " " + esc(T("sf.free", { n: sfSize(d.free) })) : ""}</p>
    <button class="btn wide" type="button" data-sfup="1">${ic("attach")}${esc(T("sf.up"))}</button><input type="file" multiple hidden data-sfin>
    ${rows || `<p class="note">${esc(T("sf.empty"))}</p>`}`, (b) => {
    if (b.dataset.sfget) return sfGet(w, b.dataset.sfget, b);
    if (b.dataset.sfup) bg.querySelector("[data-sfin]").click();
  });
  bg.querySelector("[data-sfin]").onchange = async (e) => {
    const list = [...e.target.files]; e.target.value = "";
    const b = bg.querySelector("[data-sfup]"), done = [];
    await busy(b, T("sf.up.wait"), async () => {
      for (const f of list) { try { done.push((await sfPut(w, f)).name); } catch (err) { toast(T("sf.up.fail", { n: f.name, e: err.message }), 6000); } }
    });
    if (!done.length) return;
    bg.remove(); toast(T("sf.up.done", { n: done.join(", ") }), 4000);
    const inp = meta?.space && SIM.on ? $("sInput") : $("input");          // сказать агенту — одним касанием «Отправить»
    if (inp) { inp.value = (inp.value ? inp.value + "\n" : "") + T("sf.msg", { n: done.join(", ") }); fitLines(inp); sync(); inp.focus(); }
  };
}
// space-files:end
