// ---------- живая строка статуса (activity.py): что агент делает сейчас ----------
// Отправлено → Доставлено в сессию → Взял в работу → «Читает файл X · 12 с» → Готово; «Ждёт вашего ответа» — с кнопкой.
// Опрос /api/activity раз в 1,5 с, пока идёт ход (иначе — раз в 4,5 с); текст меняется только при смене фазы.
const busySince = {};
const ACT_CLS = { sent: "run", delivered: "run", started: "run", working: "run", thinking: "run", queued: "wait", waiting: "wait", stuck: "bad", unsent: "bad", done: "done" };
let liveAct = null, actLocal = null, actSkew = 0, actBusy = false, actTick = 0;
// Анти-мигание: фаза держится на экране не меньше ACT_DWELL; меняется только textContent. Эскалация — по времени без
// нового хода и без смены фазы (ACT_ESC, с): «Проверить статус» → «Сообщить по готовности» → «Остановить».
const ACT_DWELL = 900, ACT_ESC = [12, 20, 60], ACT_RUN = ["sent", "delivered", "started", "working", "thinking", "queued", "stuck"];
let actShow = null, actProg = { key: "", at: 0, w: "" }, actDwellT = null;
const actKey = (st) => st ? [st.phase, st.text || "", st.action || ""].join("|") : "";
function actView(now = Date.now()) {                 // что показать сейчас: новое — не раньше, чем через ACT_DWELL
  const st = actState(), key = actKey(st);
  if (actProg.w !== current || actProg.key !== key) actProg = { key, at: now, w: current };
  if (!actShow || actShow.w !== current) actShow = { key, at: now, st, w: current };
  else if (key !== actShow.key) {
    const left = ACT_DWELL - (now - actShow.at);
    if (left <= 0) actShow = { key, at: now, st, w: current };
    else if (!actDwellT) actDwellT = setTimeout(() => { actDwellT = null; paintAct(); }, left + 5);
  } else actShow.st = st;
  return actShow.st;
}
function actLevel(now = Date.now()) {                // 0 — всё идёт; 1, 2, 3 — прошло 12, 20, 60 с без изменений
  const st = actShow?.w === current ? actShow.st : null;
  if (!st || !ACT_RUN.includes(st.phase)) return 0;
  const sec = (now - actProg.at) / 1000;
  return ACT_ESC.filter((x) => sec >= x).length;
}
function paintEsc() {
  const box = $("actx"); if (!box) return;
  const lv = actLevel(); if (String(lv) === box.dataset.lv) return;
  box.dataset.lv = String(lv); box.hidden = !lv;
  box.innerHTML = !lv ? "" : `<button data-actx="check">${ic("refresh", "s16")}Проверить статус</button>`
    + (lv >= 2 ? `<button data-actx="notify">${ic("bell", "s16")}Сообщить по готовности</button>` : "")
    + (lv >= 3 && meta?.role !== "viewer" ? `<button class="stop" data-actx="stop">${ic("stop", "s16")}Остановить</button>` : "");
}
function actElapsed(sec) {
  sec = Math.max(0, Math.floor(sec));
  if (sec < 60) return sec + " с";
  if (sec < 3600) return Math.floor(sec / 60) + " мин" + (sec % 60 ? " " + (sec % 60) + " с" : "");
  return Math.floor(sec / 3600) + " ч " + Math.floor(sec % 3600 / 60) + " мин";
}
function actState() {                                // что показывать: своё «Отправлено», ответ сервера или запасной вариант
  if (actLocal && actLocal.w === current) return actLocal;
  if (liveAct && liveAct.w === current) return liveAct;
  const s = cur();                                  // сервер без /api/activity — как раньше: «работает» и превью шага
  if (s?.status === "busy") { busySince[s.id] ??= Date.now() / 1000; return { phase: "working", text: s.preview || "Работает", since: busySince[s.id] }; }
  if (s) delete busySince[s.id];
  return s?.status === "dialog" ? { phase: "waiting", text: "Ждёт вашего ответа", action: "answer" } : null;
}
function paintWorking() { paintAct(); }
function paintAct() {
  const row = $("act"); if (!row) return;
  const st = actView(), now = Date.now() / 1000 + actSkew;
  const fresh = st && st.phase !== "idle" && !(st.phase === "done" && now - (st.since || 0) > 12 * 3600);
  const cls = "act " + (fresh ? ACT_CLS[st.phase] || "" : "off");
  if (row.className !== cls) row.className = cls;
  let text = "";
  if (fresh) text = st.phase === "done" ? "Готово" + (st.since ? " · " + new Date(st.since * 1000).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) : "")
    : st.action === "screen" ? "Не видно реакции" : st.text + (st.spinner ? ` (${st.spinner.split(" · ")[0]})` : "");   // кнопка рядом
  const t = row.querySelector(".t");
  if (t.textContent !== text) { t.textContent = text; row.title = text; }   // без мигания: только при смене фазы
  const btn = fresh && ["screen", "answer", "enter"].includes(st.action) ? st.action : "";
  if ((row.dataset.btn || "") !== btn) {
    row.dataset.btn = btn; row.querySelector("button")?.remove();
    if (btn) row.insertAdjacentHTML("beforeend", btn === "screen" ? `<button data-actbtn="screen">${ic("term", "s16")}Показать экран</button>`
      : btn === "enter" ? `<button data-actbtn="enter">${ic("send", "s16")}Отправить</button>` : `<button data-actbtn="answer">${ic("chat", "s16")}Ответить</button>`);
  }
  paintActTimer();
}
function paintActTimer() {                           // раз в секунду меняется только таймер
  const row = $("act"), st = actShow?.w === current ? actShow.st : null; if (!row) return;
  const live = st && ACT_CLS[st.phase] && st.phase !== "done" && st.phase !== "waiting" && st.since;
  const v = live ? actElapsed(Date.now() / 1000 + actSkew - st.since) : "";
  const tm = row.querySelector(".tm"); if (tm.textContent !== v) tm.textContent = v;
  paintEsc();
}
async function pollAct(force) {
  if (!current || view !== "session" || tab !== "chat" || document.hidden || idle() || actBusy || cur()?.status === "stopped") return;
  const st = actState(), hot = !st || ["sent", "delivered", "started", "working", "thinking", "queued"].includes(st.phase) || pending.length;
  if (!force && !hot && actTick++ % 3) return;                        // ничего не идёт — реже
  actBusy = true;
  const w = current;
  try {
    const d = await api("/api/activity?w=" + encodeURIComponent(w));
    if (w !== current) return;
    actSkew = d.now ? d.now - Date.now() / 1000 : 0;
    liveAct = { ...d, w };
    paintAct();
    if (d.rev && histRev && d.rev !== histRev && tab === "chat") liveChat();   // журнал изменился — переписку сразу
  } catch (e) { /* связь показывает индикатор; старый сервер без /api/activity — запасной вариант в actState */ }
  finally { actBusy = false; }
}
setInterval(pollAct, 1500);
$("content").addEventListener("click", async (e) => {
  const x = e.target.closest("[data-actx]");
  if (x) {
    const w = current;
    if (x.dataset.actx === "check") {                 // обновить сейчас; всё так же — показать экран
      const before = actProg.key; await pollAct(true);
      if (actProg.key === before) setTab("screen"); else toast("Статус обновлён");
      return;
    }
    if (x.dataset.actx === "notify") {
      try { const r = await api("/api/notify-done", { w }); toast(r.result || "Пришлю сообщение в бот, когда ход закончится", 3500); x.disabled = true; }
      catch (err) { toast(err.message, 4000); }
      return;
    }
    return confirmDanger("Остановить текущий ход? Claude получит Esc — как кнопка Esc на «Экране».", async () => {
      try { await api("/api/key", { w, key: "Escape" }); toast("Остановлено (Esc)"); pollAct(true); } catch (err) { toast(err.message, 4000); }
    });
  }
  const b = e.target.closest("[data-actbtn]"); if (!b) return;
  if (b.dataset.actbtn === "screen") return setTab("screen");
  if (b.dataset.actbtn === "enter") {               // текст висит в поле ввода сессии — Enter (сервер проверит, что текст наш)
    b.disabled = true;
    return api("/api/resend", { w: current }).then((d) => { toast(d.result || "Готово"); pollAct(true); })
      .catch((err) => toast(err.message, 4000)).finally(() => { b.disabled = false; });
  }
  const q = $("ask").querySelector("button");                        // вопрос уже карточкой над полем ввода — к нему
  if (q) { $("ask").scrollIntoView({ block: "nearest", behavior: "smooth" }); q.focus({ preventScroll: true }); haptic("selectionChanged"); }
  else setTab("screen");
});
function renderChat(toBottom) {
  const box = $("content"); if (box.className !== "chat") box.className = "chat";
  if (!hist.length && !pending.length) { morph(box, `<div class="panel"><div class="empty">${FOCUS_DEMO() ? "Сообщений пока нет — переписка появится здесь." : "Сообщений пока нет — напишите Claude внизу."}</div></div>`); return; }
  const norm = (t) => t.replace(/\s+/g, " ").trim();
  pending = pending.filter((p) => !hist.some((m) => m.role === "user" && norm(m.text) === norm(p.text)));
  const QS = { wait: ["wait", "в очереди — Claude занят и прочитает по ходу работы"], read: ["ok", "прочитано по ходу работы"] };
  const canSay = meta?.voices?.length || prov?.keys?.elevenlabs || DEMO;
  const lastAi = hist.at(-1)?.role === "assistant" ? hist.at(-1).i : null;
  const had = !!box.querySelector(".msg[data-i]"), wasPending = !!box.querySelector(".msg[data-key^='p:']");
  box.querySelectorAll(".msg.enter").forEach((el) => el.classList.remove("enter"));   // прошлые уже появились — при перестановке не повторять
  const fresh = morph(box, (histMore ? '<button class="btn ghost" id="older">Показать ранее</button>' : "") + hist.map((m) => m.role === "user"
    ? `<div class="msg me" data-i="${m.i}">${userMsg(m)}${m.queued ? `<div class="state ${QS[m.queued][0]}">${QS[m.queued][1]}</div>` : ""}<div class="macts"><span class="when">${esc(localTs(m.ts))}</span>${mCopyBtn()}</div></div>`
    : `<div class="msg ai" data-i="${m.i}"><div class="bubble md">${md(m.text)}</div>
        <div class="acts">${canSay ? `<button data-say="${m.i}">${ic("vol", "s16")}Прослушать</button>` : ""}<span class="when" style="margin-left:auto">${esc(localTs(m.ts))}</span><button type="button" data-mcopy="1">${ic("copy", "s16")}${esc(copyLbl())}</button></div>${voiceRow(m)}</div>`).join("")
    + pending.map((p) => `<div class="msg me" data-key="p:${esc(p.id)}"><div class="bubble">${esc(p.text)}</div><div class="state ${p.state === "sent" ? "ok" : /fail|lost/.test(p.state) ? "bad" : "wait"}">${
      { sending: "отправляется…", unsure: "связь прервалась — проверяю, дошло ли…",
        sent: cur()?.status === "busy" ? "доставлено · Claude занят и прочитает по ходу работы" : "доставлено в " + esc(cur()?.name || "сессию"),
        fail: "не отправлено — " + esc(p.err || ""),
        lost: `нет связи — не знаю, дошло ли <button class="link" data-resend="${esc(p.id)}">Повторить</button>` }[p.state]}</div><div class="macts">${mCopyBtn()}</div></div>`).join("")
    + (lastAi == null ? "" : `<div class="cmds" data-key="cmds:${lastAi}"></div>`)       // команды из последнего ответа (renderCmds)
    + '<div class="act off" id="act" data-tour="status" role="status" aria-live="polite"><span class="dot"></span><span class="t"></span><span class="tm"></span></div><div class="actx" id="actx" hidden></div>');
  voiceUi();
  const msgs = fresh.filter((el) => el.classList.contains("msg"));   // дообработка — только новых и изменившихся
  if (had) msgs.forEach((el) => !el.classList.contains("mupd") && !(wasPending && el.classList.contains("me") && el.dataset.i) && el.classList.add("enter"));
  msgs.forEach((el) => el.querySelectorAll("table").forEach((t) => { const w = document.createElement("div"); w.className = "tbl"; t.replaceWith(w); w.append(t); }));
  msgs.filter((el) => el.classList.contains("ai")).forEach((el) => el.querySelectorAll(".md pre").forEach((pre, j) => {   // длинный код в ответе — свёрнут
    const text = pre.textContent.replace(/\n$/, ""), n = text.split("\n").length;
    if (n <= 15) return;
    const key = el.dataset.i + ":p" + j, t = document.createElement("div");
    t.innerHTML = logBlock(key, "Код", text, text.split("\n")[0].trim().slice(0, 50)); pre.replaceWith(t.firstElementChild);
  }));
  msgs.forEach((el) => el.querySelectorAll(".bubble, .log pre").forEach(linkify));   // и в свёрнутом коде, и в «Терминал»
  msgs.forEach(codeCopy);                                  // короткие блоки кода — с кнопкой «Копировать» справа сверху
  if (fresh.some((el) => el.classList.contains("cmds"))) renderCmds();
  paintAct();
  if (toBottom && !params.has("noscroll")) stickBottom();   // с конца, как в ChatGPT/Claude
}
$("content").addEventListener("click", (e) => { const v = e.target.closest("[data-revive]"); if (v) revive(v.dataset.revive, v); });
$("content").addEventListener("toggle", (e) => {        // раскрытый лог остаётся раскрытым при живом обновлении
  const k = e.target.dataset?.log; if (k) e.target.open ? openLogs.add(k) : openLogs.delete(k);
}, true);
// Долгое нажатие (~0,5 с) на «Прослушать» — шторка выбора голоса; сдвиг пальца отменяет; обычное — озвучка.
let sayHold = null, sayHeld = false;
$("content").addEventListener("pointerdown", (e) => {
  sayHeld = false; const b = e.target.closest("[data-say]"); if (!b) return;
  sayHold = { x: e.clientX, y: e.clientY, t: setTimeout(() => { sayHold = null; sayHeld = true; haptic("impactOccurred", "medium"); openVoiceSheet(); }, 500) };
});
const sayUnhold = () => { if (sayHold) clearTimeout(sayHold.t); sayHold = null; };
$("content").addEventListener("pointerup", sayUnhold); $("content").addEventListener("pointercancel", sayUnhold);
$("content").addEventListener("pointermove", (e) => { if (sayHold && Math.hypot(e.clientX - sayHold.x, e.clientY - sayHold.y) > 10) sayUnhold(); });
$("content").addEventListener("contextmenu", (e) => { if (e.target.closest("[data-say]")) e.preventDefault(); });
$("content").addEventListener("click", async (e) => {
  const b = e.target.closest("button"); if (!b) return;
  if (b.dataset.say && sayHeld) { sayHeld = false; return; }   // долгое нажатие уже открыло шторку
  if (b.id === "older") return busy(b, "Загружаю…", async () => {
    const h = await api(`/api/history?w=${encodeURIComponent(current)}&before=${hist[0].i}`);
    const y = SC.scrollHeight - SC.scrollTop; hist = [...h.items, ...hist]; histMore = h.more; renderChat(false);
    scrollToY(SC.scrollHeight - y);
  });
  if (b.dataset.say) return say(true, b, +b.dataset.say);              // один режим — ответ целиком
});
