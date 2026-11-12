// ---------- сессия ----------
// Не «open»: функция верхнего уровня стала бы window.open и ломала внешние ссылки в браузере.
async function openSession(id, startTab) {
  document.body.classList.remove("focus-empty");
  current = id; termAll = false; store("last", id); hint = ""; show("session"); liveAct = null; actTick = 0;
  if (!cur()) await refresh();
  lastStatus = cur()?.status;
  if (cur()) paintSession(cur());
  $("content").className = "chat"; $("content").innerHTML = skelMsgs(); setAsk("");
  hist = []; setTab(startTab || "chat"); refresh(); haptic("selectionChanged"); padDock();
  if (matchMedia("(pointer: fine)").matches) setTimeout(() => $("input").focus(), 300);   // на компьютере — сразу печатать
}
function setTab(t) {
  tab = t;
  $("screenBtn").innerHTML = ic(t === "chat" ? "term" : "chat"); $("screenBtn").setAttribute("aria-label", t === "chat" ? "Экран терминала" : "Переписка");
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === t));
  $("live").hidden = t !== "chat";
  loadContent();
}
$("tabs").onclick = (e) => { const b = e.target.closest("button"); if (b) setTab(b.dataset.tab); };

// Остановленная сессия: Claude в окне завершился. Текст туда не шлём — предлагаем перезапустить с продолжением разговора.
async function revive(id, btn) {
  const go = async () => { try { await api("/api/revive", { w: id }); toast("Claude запускается — разговор продолжится", 3500); await refresh(); openSession(id); } catch (err) { toast(err.message, 5000); } };
  return btn ? busy(btn, "Запускаю…", go) : go();
}
async function loadContent() {
  if (!current) return;
  if (cur()?.status === "stopped") {
    $("content").className = ""; setAsk("");
    $("content").innerHTML = `<div class="panel"><p style="margin-top:0"><b>Claude в этой сессии остановлен.</b> В окне осталась командная строка — сообщения туда не отправляются, чтобы не выполнить их как команды.</p>
      ${meta?.role !== "viewer" ? `<button class="btn" data-revive="${esc(current)}">${ic("refresh")}Перезапустить — продолжить разговор</button>` : ""}</div>`;
    return;
  }
  try {
    const [h, scr] = await Promise.all([tab === "chat" ? api("/api/history?w=" + encodeURIComponent(current)) : null, api("/api/screen?w=" + encodeURIComponent(current))]);
    renderAsk(scr.lines, scr.auth); loginNotice(scr.login, current);
    $("keys").hidden = tab !== "screen";                    // клавиши — на «Экране»; в переписке вопрос — карточкой
    if (tab === "chat") {
      const grew = !hist.length || h.items.at(-1)?.i !== hist.at(-1)?.i || h.items.at(-1)?.text.length !== hist.at(-1)?.text.length;
      const opened = !hist.length || $("content").className !== "chat" || journalOf(histRev) !== journalOf(h.rev);
      histRev = h.rev || ""; markFresh();
      if (opened) { hist = h.items; histMore = h.more; renderChat(true); }   // открыли (или вернулись с «Экрана») — с конца
      else if (grew) mergeChat(h);   // переписка уже на экране: дорисовать, ранние сообщения и место чтения — не трогать
    } else renderTerm(scr.lines);
    padDock();
  } catch (e) {
    if (e.net && $("content").firstElementChild && !$("content").querySelector(".empty, .skel")) return;   // при обрыве — оставляем то, что видно
    $("content").className = ""; $("content").innerHTML = `<div class="panel"><div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div></div>`; }
}
// Экран — контрастный терминал: последние строки, остальное по кнопке.
function renderTerm(lines) {
  const box = $("content"); box.className = "";
  const shown = termAll ? lines : lines.slice(-18);
  box.innerHTML = `<div class="term${termWrap ? " wrap" : ""}"><div class="termbar"><button id="termWrap" class="${termWrap ? "on" : ""}">Перенос строк: ${termWrap ? "вкл" : "выкл"}</button>${ttyOk() ? `<button id="termLive" class="on">Живой терминал</button>` : ""}</div><pre>${esc(shown.join("\n"))}</pre>${lines.length > 18 ? `<button class="more" id="termMore">${termAll ? "Свернуть" : "Показать весь экран · " + lines.length + " строк"}</button>` : ""}</div>`;
  $("termMore")?.addEventListener("click", () => { termAll = !termAll; renderTerm(lines); });
  $("termLive")?.addEventListener("click", () => ttyOpen(current));
  $("termWrap").addEventListener("click", () => { termWrap = !termWrap; store("termWrap", termWrap ? "1" : ""); renderTerm(lines); });
}

async function liveChat() {                         // каждые 3 с: менялся ли журнал; изменился — дорисовываем, не сбивая прокрутку
  if (!current || tab !== "chat" || cur()?.status === "stopped") return;
  try {
    const h = await api(`/api/history?w=${encodeURIComponent(current)}&rev=${encodeURIComponent(histRev)}`);
    markFresh();
    if (h.same) return;
    if (journalOf(histRev) !== journalOf(h.rev)) { histRev = h.rev || ""; hist = h.items; histMore = h.more; return renderChat(true); }
    histRev = h.rev || "";
    mergeChat(h);
  } catch (e) { /* связь показывает индикатор: нет ответа сервера 15 с — янтарная плашка */ }
}
// rev журнала — «<8 знаков id сессии>-<размер>-<время>» (transcripts.revision): другой id — другой разговор (окно
// сменило журнал: /clear, /resume, или раньше панель брала «последний журнал папки»). Склеивать два разговора по
// номерам сообщений нельзя — переписка заново, с конца.
const journalOf = (rev) => String(rev || "").split("-")[0];
function mergeChat(h) {   // свежий хвост переписки — к тому, что уже на экране; читатель остаётся на своём месте
  const atBottom = atEnd(220), first = h.items[0]?.i ?? Infinity;
  // якорь — сообщение, которое сейчас читают (первое видимое), и его отступ от верха экрана; после перерисовки — туда же
  const ms = [...$("content").querySelectorAll(".msg")], top = SC.getBoundingClientRect?.().top || 0;
  const k = ms.findIndex((el) => el.getBoundingClientRect().bottom > top + 1), anchor = k >= 0 ? hist[k]?.i : null;
  const off = k >= 0 ? ms[k].getBoundingClientRect().top : 0;
  hist = [...hist.filter((m) => m.i < first), ...h.items];
  if (!hist.some((m) => m.i < first)) histMore = h.more;
  renderChat(atBottom);
  if (atBottom) return;
  const j = hist.findIndex((m) => m.i === anchor), el = j >= 0 ? $("content").querySelectorAll(".msg")[j] : null;
  if (el) SC.scrollTop += el.getBoundingClientRect().top - off;
  autoUntil = Date.now() + 300;
  $("toBottom").classList.add("new");
}
// «Прилипнуть к низу»: после открытия лента ещё растёт — команды под ответом (renderCmds), строка статуса, поле ввода
// (padDock), таблицы, шрифты. Одна прокрутка в rAF попадала не в конец. Пока человек сам не тронул ленту (палец,
// колесо, клавиши) — 4 с держим низ при каждом изменении размера.
let stick = 0;
const stickRO = typeof ResizeObserver === "function" ? new ResizeObserver(() => { if (Date.now() < stick) SC.scrollTop = SC.scrollHeight; }) : null;
function stickBottom() {
  stick = Date.now() + 4000; SC.scrollTop = SC.scrollHeight;
  requestAnimationFrame(() => { if (Date.now() < stick) SC.scrollTop = SC.scrollHeight; });
  if (stickRO) { stickRO.disconnect(); stickRO.observe($("content")); $("dock") && stickRO.observe($("dock")); }
}
["wheel", "touchmove", "keydown"].forEach((ev) => addEventListener(ev, (e) => { if (ev !== "keydown" || /^(Arrow|Page|Home|End)/.test(e.key)) stick = 0; }, { passive: true, capture: true }));
// Связь есть — индикатор у поля скрыт (план UX, пункт 9); виден только «нет связи · N с» (netTick).
function markFresh() { const sp = $("live").querySelector("span"); if (!$("live").classList.contains("stale") && sp.textContent) sp.textContent = ""; }
document.addEventListener("visibilitychange", () => { if (!document.hidden) { lastOk = Math.max(lastOk, Date.now() - 5000); refresh(); keepAwake(); } });
// Опрос — только для зрителя. Вкладка скрыта — не опрашиваем совсем (каждый опрос — список окон tmux на сервере,
// у демо-пространств ещё и sudo). Панель открыта, но 10 минут никто её не касался — раз в 30 с, а не раз в 3 с.
// Касание, клавиша, прокрутка — сразу свежие данные и обычный темп.
// Темп: идёт работа (какая-то сессия работает, ваше сообщение ещё в пути) — раз в 3 с; всё стоит — раз в 10 с.
const IDLE_MS = 10 * 60 * 1000, IDLE_POLL_MS = 30000, WORK_POLL_MS = 3000, CALM_POLL_MS = 10000;
const idle = () => Date.now() - lastTouch > IDLE_MS;
const working = () => pending.length > 0 || sessions.some((s) => s.status === "busy");
const pollGap = () => idle() ? IDLE_POLL_MS : working() ? WORK_POLL_MS : CALM_POLL_MS;
function pollDue() { return !document.hidden && Date.now() - lastPoll >= pollGap() - 250; }
["pointerdown", "keydown", "wheel", "touchstart", "scroll"].forEach((ev) => addEventListener(ev, () => {
  const woke = idle(); lastTouch = Date.now();
  if (woke && start.done && !document.hidden) { lastOk = Math.max(lastOk, Date.now() - 5000); refresh(); }
}, { passive: true, capture: true }));
// Честный индикатор: 15 секунд без ответа сервера — янтарная плашка с «Переподключить». Без работы опрос раз в 10 с,
// поэтому порог — два пропущенных опроса, но не меньше 15 с.
function netTick() {
  if (view === "login" || idle()) return;            // без зрителя опрос редкий — это не обрыв связи
  const sec = Math.round((Date.now() - lastOk) / 1000), bad = sec >= Math.max(15, pollGap() * 2 / 1000 + 2);
  if ($("net").hidden !== !bad) $("net").hidden = !bad;
  $("live").classList.toggle("stale", bad);
  if (bad) {
    const t = `Нет связи с сервером · ${sec} с`, l = `нет связи · ${sec} с`, sp = $("live").querySelector("span");
    if ($("netText").textContent !== t) $("netText").textContent = t;
    if (sp.textContent !== l) sp.textContent = l;
  }
}
// Один секундный тик на всю панель (вместо пяти таймеров): опрос списка по темпу (pollDue), связь, таймер хода,
// «изменена N назад», строка статуса простого режима. Скрытая вкладка — ничего не делает.
function tick() {
  if (document.hidden) return;
  if (start.poll && pollDue()) start.poll();
  netTick();
  if (view === "session") paintActTimer();
  if (SIM.on) sAct();
  if (agoTick.fast || Date.now() - (agoTick.at || 0) >= 30000) agoTick();
  useTick();
}
setInterval(tick, 1000);
// Какими функциями пользуются (features.py, отчёт владельцу раз в месяц): id открытого экрана или листа и действий
// меню — пачкой раз в минуту. Только id (как у помощника), без текста и данных; в демо — ничего не шлём.
const USE = { cur: "", ids: new Set(), at: Date.now() };
function useMark(id) { if (id && !DEMO && meta) USE.ids.add(id); }
function useTick() {
  const top = [...document.querySelectorAll(".sheet-bg:not(.help-bg)")].at(-1), id = top?.dataset.help || (meta ? helpViewId() : "");
  if (id !== USE.cur) { USE.cur = id; useMark(id); }
  if (USE.ids.size && Date.now() - USE.at >= 60000) useFlush();
}
function useFlush() {
  if (!USE.ids.size) return;
  const ids = [...USE.ids].slice(0, 20); USE.ids.clear(); USE.at = Date.now();
  api("/api/uses", { ids }).catch(() => {});
}
addEventListener("pagehide", useFlush);
$("netRetry").onclick = (e) => busy(e.currentTarget, "Подключаюсь…", async () => {
  await refresh(); if (view === "session") await loadContent();
  if (Date.now() - lastOk < 3000) { $("net").hidden = true; $("live").classList.remove("stale"); markFresh(); toast("Связь есть"); }
  else toast("Сервер пока не отвечает — проверьте интернет", 3500);
});
$("toBottom").onclick = () => { $("toBottom").classList.remove("new"); scrollToY(SC.scrollHeight, true); };
let wake = null;
async function keepAwake() { try { if (navigator.wakeLock && !document.hidden && (!wake || wake.released)) wake = await navigator.wakeLock.request("screen"); } catch (e) {} }

// Строки, по которым видно вывод терминала: приглашение, ssh/lsof, предупреждения, листинги, трассировки.
const TECH = /^\s*(\$ |# |❯ |Last login|WARNING:|\*\* |COMMAND\s+PID|(tcp|udp)\s|LISTEN|Connection (to|closed)|ssh[: ]|lsof|sudo |\[sudo\]|total \d+|[dl-][rwx-]{9}|Traceback|File "|npm (ERR|WARN)|error:|E: |fatal:|[\w.-]+@[\w.-]+[:~]|[─━═]{6,}|\s*\d+\s+\d+\s+\d+)/;
const plural = (n, f) => f[n % 10 === 1 && n % 100 !== 11 ? 0 : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20) ? 1 : 2];
function logBlock(key, label, text, hint) {
  const n = text.split("\n").length;
  return `<details class="log" data-log="${key}"${openLogs.has(key) ? " open" : ""}><summary>${ic("chevron", "s16")}<b>${label}</b><em>${n} ${plural(n, ["строка", "строки", "строк"])}${hint ? " · " + esc(hint) : ""}</em>${cCopyBtn()}</summary><pre>${esc(text)}</pre></details>`;
}
function userMsg(m) {                               // вставленный вывод терминала — свёрнут, ваш текст — открыт
  const lines = m.text.split("\n"), k = lines.findIndex((l) => TECH.test(l));
  const body = k < 0 ? [] : lines.slice(k);
  if (body.length < 4 || body.filter((l) => TECH.test(l)).length < 2) return `<div class="bubble">${esc(m.text)}</div>`;
  const head = lines.slice(0, k).join("\n").trim();
  const first = body.find((l) => l.trim())?.trim().slice(0, 60);
  return (head ? `<div class="bubble">${esc(head)}</div>` : "") + logBlock(m.i + ":u", "Терминал", body.join("\n"), first);
}
