// ---------- озвучка ----------
// Плеер один на всю панель: играет при переходах по меню и между сессиями, останавливается только кнопкой ✕.
// Состояние — на том сообщении, где нажали «Прослушать»; на других экранах — мини-плеер (тап — к сообщению).
const player = () => $("player");
// Скорость: 1× → 1,25× → 1,5× → 2× по кругу; выбор — в настройках человека на сервере, localStorage — кэш.
const RATES = [1, 1.25, 1.5, 2];
const rateLabel = (r) => String(r).replace(".", ",") + "×";
function voiceRate() { const r = +((FOCUS || DEMO ? store("voiceRate") : meta?.prefs?.rate) || store("voiceRate") || 1); return RATES.includes(r) ? r : 1; }
function setVoiceRate(r) {
  store("voiceRate", String(r)); if (meta?.prefs) meta.prefs.rate = r;
  player().playbackRate = r; voiceUi(); mediaPos();
  if (meta && !FOCUS && !DEMO) api("/api/prefs", { rate: r }).catch(() => {});   // не вышло — останется в кэше браузера
}
// seek:start — чистые функции перемотки (их же считает тест): −15 с у начала — 0:00, +15 с у конца — конец.
const SEEK = 15;
const mmss = (t) => (isFinite(t) ? `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}` : "");
function seekPos(t, d, dur) { const x = (+t || 0) + d; return Math.max(0, isFinite(dur) && dur > 0 ? Math.min(dur, x) : x); }
function clock(t, dur) { return isFinite(dur) && dur > 0 ? `${mmss(Math.min(t, dur))} / ${mmss(dur)}` : mmss(t); }
// seek:end
function voiceRow(m) {
  if (!voice || voice.w !== current || voice.msg !== m.i) return "";
  return `<div class="voice ${voice.state}" data-voice>${voiceInner(false)}</div>`;
}
function voiceInner(mini) {
  const prep = voice.state === "prep", p = player(), dur = p.duration, t = drag ? drag.t : (voice.at ?? p.currentTime);
  const pct = dur ? (100 * t / dur).toFixed(1) : 0;
  return (mini ? `<button class="name" data-vgo>${esc(voice.name)}</button>` : "")
    + (prep ? `${ic("wait", "s16")}<span>Готовлю…</span><span class="bar"><i></i></span>`
      : `<button class="vb" data-vseek="-${SEEK}" aria-label="Назад на ${SEEK} секунд">${ic("rew15")}</button>
         <button class="vb play" data-vtoggle aria-label="${voice.state === "play" ? "Пауза" : "Играть"}">${ic(voice.state === "play" ? "pause" : "play")}</button>
         <button class="vb" data-vseek="${SEEK}" aria-label="Вперёд на ${SEEK} секунд">${ic("fwd15")}</button>
         <button class="vb rate" data-vrate aria-label="Скорость ${rateLabel(voiceRate())}, нажмите — быстрее">${rateLabel(voiceRate())}</button>
         <span class="t">${clock(t, dur)}</span>
         <span class="bar" role="slider" tabindex="0" aria-label="Перемотка" aria-valuemin="0" aria-valuemax="${Math.round(dur || 0)}" aria-valuenow="${Math.round(t || 0)}" aria-valuetext="${clock(t, dur)}"><i style="width:${pct}%"></i><b style="left:${pct}%"></b></span>`)
    + `<button class="vb" data-vstop aria-label="Остановить">${ic("x", "s16")}</button>`;
}
function voiceUi() {                                // перерисовать состояние везде, где оно видно
  document.querySelectorAll("[data-voice]").forEach((el) => voice ? (el.className = "voice " + voice.state, el.innerHTML = voiceInner(false)) : el.remove());
  const onMsg = voice && document.querySelector("[data-voice]")?.isConnected && view === "session" && current === voice.w;
  $("mini").hidden = !voice || onMsg;
  if (!$("mini").hidden) { $("mini").className = "voice mini " + voice.state; $("mini").innerHTML = voiceInner(true); placeMini(); }
}
function voiceTick() {                              // прогресс — без перерисовки, каждые ~250 мс
  const p = player(), dur = p.duration, t = drag ? drag.t : (voice?.at ?? p.currentTime), w = dur ? (100 * t / dur).toFixed(1) + "%" : "0";
  document.querySelectorAll(".voice:not(.prep) .bar i").forEach((i) => { i.style.width = w; });
  document.querySelectorAll(".voice:not(.prep) .bar b").forEach((i) => { i.style.left = w; });
  document.querySelectorAll(".voice:not(.prep) .bar").forEach((b) => { b.setAttribute("aria-valuenow", Math.round(t || 0)); b.setAttribute("aria-valuetext", clock(t, dur)); });
  document.querySelectorAll(".voice .t").forEach((x) => { x.textContent = clock(t, dur); });
  if (!drag) voicePos();
}
function placeMini() {                              // над нижней панелью или кнопкой «Новая сессия»
  const h = !$("dock").hidden ? ($("dock").classList.contains("hide") ? 0 : $("dock").offsetHeight) : !$("homeBar").hidden ? $("homeBar").offsetHeight : 0;
  document.documentElement.style.setProperty("--mini-b", (h + 12) + "px");
}
// Позиция переживает сворачивание и перезагрузку панели: где остановились — оттуда и продолжим (тот же ответ, тот же вид).
const VPOS = "voicePos", VPOS_TTL = 12 * 3600e3;
let vposAt = 0;
function voicePos(force) {
  const p = player(); if (!voice || voice.state === "prep" || !p.duration) return;
  if (!force && Date.now() - vposAt < 2000) return; vposAt = Date.now();
  try { localStorage.setItem(VPOS, JSON.stringify({ w: voice.w, msg: voice.msg, full: voice.full, name: voice.name, t: p.currentTime, ts: Date.now() })); } catch (e) {}
}
function voiceSaved(w, msg, full) {
  try {
    const r = JSON.parse(localStorage.getItem(VPOS) || "null");
    if (r && Date.now() - r.ts < VPOS_TTL && (w == null || (r.w === w && r.msg === msg && r.full === full))) return r;
  } catch (e) {}
  return null;
}
function voiceForget() { try { localStorage.removeItem(VPOS); } catch (e) {} }
function seekBy(d) {                                // кнопки ±15 с, наушники, экран блокировки
  const p = player(); if (!voice || voice.state === "prep") return;
  if (voice.at != null && !p.src) { voice.at = seekPos(voice.at, d, NaN); return voiceTick(); }   // ещё не загрузили заново
  if (!p.duration) return;
  p.currentTime = seekPos(p.currentTime, d, p.duration); voiceTick(); voicePos(true); mediaPos();
}
function mediaPos() {                               // полоса на экране блокировки
  const p = player();
  if (!("mediaSession" in navigator) || !navigator.mediaSession.setPositionState || !isFinite(p.duration) || !p.duration) return;
  try { navigator.mediaSession.setPositionState({ duration: p.duration, playbackRate: p.playbackRate || 1, position: Math.min(p.currentTime, p.duration) }); } catch (e) {}
}
function mediaSession(title, name) {               // previoustrack/nexttrack не трогаем: «следующего ответа» нет
  if (!("mediaSession" in navigator)) return;
  const ms = navigator.mediaSession, on = (a, f) => { try { ms.setActionHandler(a, f); } catch (e) {} };
  ms.metadata = new MediaMetadata({ title, artist: name, album: "Пульт" });
  on("play", () => player().play()); on("pause", () => player().pause()); on("stop", stopPlayer);
  on("seekbackward", (d) => seekBy(-(d?.seekOffset || SEEK)));
  on("seekforward", (d) => seekBy(d?.seekOffset || SEEK));
  on("seekto", (d) => { const p = player(); if (!p.duration || d?.seekTime == null) return;
    if (d.fastSeek && p.fastSeek) p.fastSeek(d.seekTime); else p.currentTime = seekPos(d.seekTime, 0, p.duration); voiceTick(); mediaPos(); });
}
async function say(full, btn, msg) {
  const w = current, name = cur()?.name || "сессия";
  if (msg == null) msg = hist.findLast?.((m) => m.role === "assistant")?.i ?? null;   // из меню — последний ответ
  full = !!full;
  if (voice && voice.w === w && voice.msg === msg && voice.full === full && voice.state !== "prep" && player().src) {
    return player().paused ? player().play() : player().pause();     // тот же ответ уже загружен — пауза/продолжить
  }
  const saved = voiceSaved(w, msg, full);
  stopPlayer(true); voice = { w, name, msg, full, state: "prep" }; renderChat(false); voiceUi();
  try {
    const blob = DEMO ? demoTone() : await api(`/api/tts?w=${encodeURIComponent(w)}&full=${full ? 1 : 0}${msg == null ? "" : "&msg=" + msg}`);
    if (!voice || voice.w !== w || voice.msg !== msg || voice.full !== full) return;   // пока готовили — остановили, начали другое или сменили режим
    await voiceLoad(blob, full, name, saved?.t);
  } catch (e) { voice = null; voiceUi(); toast("Озвучка: " + e.message, 4500); }
}
async function voiceLoad(blob, full, name, from) {
  const p = player(); if (p.src) URL.revokeObjectURL(p.src);
  p.src = URL.createObjectURL(blob);
  p.playbackRate = p.defaultPlaybackRate = voiceRate();
  mediaSession(full ? "Ответ Claude" : "Ответ Claude кратко", name);
  if (from > 1) {                                   // в прошлый раз остановились здесь — продолжаем
    await new Promise((r) => { if (p.readyState >= 1) r(); else p.addEventListener("loadedmetadata", r, { once: true }); });
    if (from < p.duration - 1) { p.currentTime = from; toast("Продолжаю с " + mmss(from)); }
  }
  await p.play().catch(() => { if (voice) { voice.state = "pause"; voiceUi(); } toast("Нажмите ▶, чтобы слушать"); });
}
function stopPlayer(keep) {                         // keep — сменили ответ, а не нажали ✕: место в старом не забываем
  const p = player(); p.pause(); if (p.src) { URL.revokeObjectURL(p.src); p.removeAttribute("src"); p.load(); }
  if ("mediaSession" in navigator) navigator.mediaSession.metadata = null;
  if (keep !== true) voiceForget();
  voice = null; drag = null; voiceUi();
}
player().addEventListener("play", () => { if (voice) { voice.state = "play"; voiceUi(); mediaPos(); } });
player().addEventListener("pause", () => { if (voice && voice.state !== "prep" && !player().ended) { voice.state = "pause"; voiceUi(); voicePos(true); } });
player().addEventListener("ended", () => stopPlayer());
player().addEventListener("timeupdate", voiceTick);
player().addEventListener("loadedmetadata", () => { voiceTick(); mediaPos(); });
player().addEventListener("seeked", mediaPos);
addEventListener("pagehide", () => voicePos(true));
document.addEventListener("visibilitychange", () => { if (document.hidden) voicePos(true); });
// Полоса: тянуть пальцем (или мышью) — время меняется сразу, звук перескакивает, когда отпустили.
function dragAt(e, bar) {
  const r = bar.getBoundingClientRect(), dur = player().duration;
  return dur * Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
}
document.addEventListener("pointerdown", (e) => {
  const bar = voice && e.target.closest(".voice:not(.prep) .bar"); if (!bar || !player().duration) return;
  e.preventDefault(); try { bar.setPointerCapture(e.pointerId); } catch (x) {}
  drag = { id: e.pointerId, bar, t: dragAt(e, bar) }; bar.classList.add("drag"); voiceTick();
});
document.addEventListener("pointermove", (e) => { if (drag && e.pointerId === drag.id) { drag.t = dragAt(e, drag.bar); voiceTick(); } });
function dragEnd(e, apply) {
  if (!drag || e.pointerId !== drag.id) return;
  const t = drag.t; drag.bar.classList.remove("drag"); drag = null;
  if (apply && player().duration) { player().currentTime = seekPos(t, 0, player().duration); voicePos(true); mediaPos(); }
  voiceTick();
}
document.addEventListener("pointerup", (e) => dragEnd(e, true));
document.addEventListener("pointercancel", (e) => dragEnd(e, false));
document.addEventListener("keydown", (e) => {     // полоса с клавиатуры: стрелки — ±15 с
  if (!e.target.closest?.(".voice .bar")) return;
  if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); seekBy(e.key === "ArrowLeft" ? -SEEK : SEEK); }
});
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-vtoggle], [data-vstop], [data-vgo], [data-vseek], [data-vrate]"); if (!b || !voice) return;
  if (b.dataset.vstop != null) return stopPlayer();
  if (b.dataset.vseek != null) { haptic("selectionChanged"); return seekBy(+b.dataset.vseek); }
  if (b.dataset.vrate != null) { haptic("selectionChanged"); return setVoiceRate(RATES[(RATES.indexOf(voiceRate()) + 1) % RATES.length]); }
  if (b.dataset.vtoggle != null) {
    if (voice.at != null && !player().src) return voiceResume();      // после перезагрузки: озвучку готовим заново
    return player().paused ? player().play() : player().pause();
  }
  const v = voice;                                  // мини-плеер: вернуться к сообщению
  (current === v.w && view === "session" ? Promise.resolve() : openSession(v.w)).then?.(() => setTimeout(() => {
    if (tab !== "chat") setTab("chat");
    document.querySelector("[data-voice]")?.scrollIntoView({ block: "center", behavior: "smooth" }); voiceUi();
  }, 600));
});
// Панель перезагрузилась (свернули, обновилась версия) — мини-плеер на паузе с тем же местом; ▶ — продолжить.
function voiceRestore() {
  const r = voiceSaved(); if (!r || voice || !sessions.some((x) => x.id === r.w)) return;
  voice = { w: r.w, name: r.name || "сессия", msg: r.msg, full: !!r.full, state: "pause", at: r.t }; voiceUi();
}
async function voiceResume() {
  const v = voice, from = v.at; v.state = "prep"; delete v.at; voiceUi();
  try {
    const blob = DEMO ? demoTone() : await api(`/api/tts?w=${encodeURIComponent(v.w)}&full=${v.full ? 1 : 0}${v.msg == null ? "" : "&msg=" + v.msg}`);
    if (voice !== v) return;
    await voiceLoad(blob, v.full, v.name, from);
  } catch (e) { voice = null; voiceForget(); voiceUi(); toast("Озвучка: " + e.message, 4500); }
}
function demoTone(sec = 40) {                       // демо: 40 с тихого тона вместо настоящей озвучки
  const rate = 8000, n = rate * sec, b = new DataView(new ArrayBuffer(44 + n * 2));
  const str = (o, t) => [...t].forEach((c, i) => b.setUint8(o + i, c.charCodeAt(0)));
  str(0, "RIFF"); b.setUint32(4, 36 + n * 2, true); str(8, "WAVEfmt "); b.setUint32(16, 16, true); b.setUint16(20, 1, true); b.setUint16(22, 1, true);
  b.setUint32(24, rate, true); b.setUint32(28, rate * 2, true); b.setUint16(32, 2, true); b.setUint16(34, 16, true); str(36, "data"); b.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) b.setInt16(44 + i * 2, Math.sin(i / rate * 2 * Math.PI * 440) * 600, true);
  return new Blob([b], { type: "audio/wav" });
}
function padDock() { requestAnimationFrame(() => { const h = $("dock").offsetHeight, shown = $("dock").classList.contains("hide") ? 0 : h;
  const pb = (h + 16) + "px"; if ($("session").style.paddingBottom !== pb) $("session").style.paddingBottom = pb;
  document.documentElement.style.setProperty("--tb", shown + "px"); placeMini(); }); }
function closeMenu() { $("menu").hidden = true; $("menuBtn").classList.remove("on"); $("menuBtn").innerHTML = ic("menu"); padDock(); }
$("menuBtn").onclick = () => { const o = $("menu").hidden; $("menu").hidden = !o; $("menuBtn").classList.toggle("on", o); $("menuBtn").innerHTML = ic(o ? "x" : "menu"); padDock(); };

const ACTIONS = {
  sos: () => callHelp(current),
  say: (b) => say(true, b),
  commands: () => helpSheet("sheet.commands") || sheet("Команды Claude", meta.commands.map((label, i) => ({
    label: clean(label), icon: "bolt", run: async () => { const d = await act("/api/command", { i }); if (d?.models) ACTIONS.models(); else if (d?.sent) { toast("Отправлено"); lastStatus = "busy"; setTab("screen"); } },
  }))),
  models: () => {                                   // модель и поставщик — только этого чата (задача 37)
    const s = cur(), p = profileOf(s?.profile || "claude"), own = p && p.needs_key;
    const pick = (alias, name) => setModel(s, alias, name);
    const items = own
      ? [[p.main || p.default_main, "основная", "opus"], [p.fast || p.default_fast, "быстрая — рутина и субагенты", "haiku"]]
          .map(([name, sub, alias]) => ({ label: name, icon: "chip", sub, on: s?.model_own === alias, run: () => pick(alias, name) }))
      : meta.models.map((m) => ({ label: m, icon: "chip", on: s?.model_own === m, sub: { opus: "самая сильная", sonnet: "баланс скорости и качества", haiku: "самая быстрая" }[m],
          run: () => pick(m, m) }));
    helpSheet("sheet.model");
    sheet(`Модель этого чата · ${p?.title || "Claude"}`, [
      { info: true, icon: "help", label: "Только для этого чата", sub: "сессия перезапустится с выбранной моделью, разговор продолжится; другие сессии и чаты не меняются" + (meta.role === "owner" ? ". Для всех новых сессий — «Настройки» → «Модель по умолчанию»" : "") },
      ...items,
      ...(meta.role === "owner" ? [{ label: "Сменить поставщика этого чата…", icon: "swap", sub: "Claude, OpenRouter, GLM, DeepSeek — только эта сессия, она перезапустится", run: () => switchProfile(s) }] : [])]);
  },
  effort: () => effortSheet(),
  mcp: () => focusMcp(),
  repos: () => repoSheet(current),
  switch: () => $("switchBtn").onclick(),
  active: () => act("/api/active", {}, "Теперь ответы в чате бота — от этой сессии").then(refresh),
  refresh: () => { hist = []; loadContent(); toast("Обновлено"); },
  top: () => { $("top").classList.remove("hide"); scrollToY(0, true); },
  close: () => confirmClose(current),
};
$("menu").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; closeMenu(); useMark("act:" + b.dataset.act); ACTIONS[b.dataset.act](b); };
// Смена поставщика перезапускает окно. По умолчанию разговор продолжается (claude --continue) — контекст не теряется.
function switchProfile(s) {
  pickProfile((pid) => {
    const title = profileOf(pid)?.title || pid;
    const go = async (keep) => {
      toast("Перезапускаю…", 6000);
      try { const d = await api("/api/restart", { w: s.id, profile: pid, keep }); await refresh(); openSession(d.id); toast(`Готово: ${title}${keep ? " — разговор продолжается" : ""}`); }
      catch (err) { toast("Не вышло: " + err.message, 5000); }
    };
    helpSheet("sheet.switch-provider");
    sheet(`Перезапустить «${s.name}» с ${title}`, [
      { label: "Продолжить этот разговор", icon: "chat", sub: `${title} получит всю переписку — контекст сохранится`, run: () => go(true) },
      { label: "Начать заново", icon: "refresh", sub: "чистый контекст: быстрее и дешевле; старый разговор останется в истории", run: () => go(false) },
    ]);
  }, s.profile || "claude");
}
// После смены модели — сразу уровень усилий (как глубоко думать): одно касание вместо второго меню.
function effortSheet() {
  helpSheet("sheet.effort");
  sheet("Уровень усилий", [["auto", "Авто", "Claude сам решает"], ["low", "Низкий", "быстро и дёшево"], ["medium", "Средний", "обычные задачи"],
    ["high", "Высокий", "сложные задачи"], ["xhigh", "Очень высокий", "архитектура, сложный разбор"], ["max", "Максимальный", "дольше и дороже всего"]]
    .map(([v, label, sub]) => ({ label, sub, icon: "bolt", run: () => act("/api/effort", { level: v }, "Усилия: " + label) })));
}
async function closeSession(id = current, schedule = "") {
  try {
    const d = await api("/api/close", { w: id, ...(schedule ? { schedule } : {}) }); toast(d.result === "закрыто" ? "Сессия завершена" : "Не завершена: " + d.result, 4500);
    if (d.result === "закрыто") { if (FOCUS) return focusGone(); if (id === current) back(); else refresh(); }
    if (d.draft) draftSheet(d.draft);                 // неотправленный текст из поля ввода — не теряем молча
  } catch (e) { toast("Не вышло: " + e.message, 4500); }
}
function draftSheet(text) {
  helpSheet("session.menu");
  sheet("Черновик", [
    { info: true, icon: "edit", label: "Черновик: " + (text.length > 300 ? text.slice(0, 300) + "…" : text), sub: "был в поле ввода и не отправлен — при завершении Claude его стёр" },
    { label: "Скопировать черновик", icon: "copy", run: () => copyText(text, "Черновик скопирован") },
  ]);
}
// Шторка сессий: статус точкой, текущая отмечена; долгое нажатие — действия с сессией; ниже — «Новая» и «Все сессии».
function openSwitcher() {
  if (FOCUS) return FOCUS_PROJ() ? focusProjSheet() : undefined;   // фокус на сессию — только она; на проект — его сессии
  helpSheet("sheet.switcher");
  sheet("Сессии", [...pinFirst([...sessions].sort(byChange)).map((s) => ({
    label: s.name, sub: `${s.pinned ? "закреплена · " : ""}${ST[s.status].label}${isNew(s) ? " · новый ответ" : ""}${s.changed ? " · " + agoText(s.changed) : ""} · ${folder(s.path)}`, dot: ST[s.status].cls, on: s.id === current,
    run: () => openSession(s.id), hold: () => sessionActions(s) })),
    ...(meta?.role !== "viewer" ? [{ label: "Новая сессия", icon: "plus", run: () => newSession() }] : []),
    { label: "Команды из всех сессий", icon: "term", run: () => { back(); setHome("commands"); } },
    { label: "Все сессии и интеграции", icon: "menu", run: back },
    { label: "Обозначения", icon: "help", sub: "что значат цвета точек", run: legend }]);
}
const sessionActions = (s) => sessionSheet(s.id);          // долгое нажатие в шторке — то же, что «⋯» на карточке
// Переименовать: своё поле ввода (prompt() в Telegram на iPhone ненадёжен). Имя — как в tmux: без «:» и «.».
function renameSession(s) {
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.rename");
  bg.innerHTML = `<div class="sheet" role="dialog"><h3>Переименовать сессию</h3>
    <div class="field" style="margin:4px 16px 0"><input id="renName" maxlength="40" autocomplete="off" value="${esc(s.name)}"></div>
    <p class="note" id="renErr" style="margin:6px 16px 0">До 40 знаков, без «:» и «.»</p>
    <div class="row2"><button class="btn ghost" data-close>Отмена</button><button class="btn" id="renOk">Сохранить</button></div></div>`;
  document.body.append(bg);
  const inp = $("renName"); inp.focus(); inp.select();
  const save = async () => {
    const name = inp.value.trim().replace(/\s+/g, " ");
    if (!name || /[:.]/.test(name)) { $("renErr").style.color = "var(--status-danger)"; return; }
    try { await api("/api/rename", { w: s.id, name }); bg.remove(); toast("Теперь: " + name); haptic("notificationOccurred", "success"); await refresh(); if (s.id === current) paintSession(cur()); }
    catch (e) { $("renErr").textContent = e.message; $("renErr").style.color = "var(--status-danger)"; }
  };
  $("renOk").onclick = save;
  inp.onkeydown = (e) => { if (e.key === "Enter") save(); if (e.key === "Escape") bg.remove(); };
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) bg.remove(); });
}
$("switchBtn").onclick = openSwitcher;
$("title").onclick = () => { if (view === "session" && !split()) openSwitcher(); };
$("screenBtn").onclick = () => setTab(tab === "chat" ? "screen" : "chat");
// Жесты (телефон, в сессии): по шапке влево-вправо — соседняя сессия. От левого края — назад (backDrag); панель чатов — ☰.
let swipe = null;
addEventListener("touchstart", (e) => {
  swipe = null;
  if (view !== "session" || split() || e.touches.length !== 1 || document.querySelector(".sheet-bg")) return;
  const t = e.touches[0], head = t.clientX >= 24 && !!e.target.closest?.("#top") && !e.target.closest("button");
  if (head) swipe = { x: t.clientX, y: t.clientY };
}, { passive: true });
addEventListener("touchend", (e) => {
  const s = swipe; swipe = null;
  if (!s) return;
  const t = e.changedTouches[0], dx = t.clientX - s.x, dy = t.clientY - s.y;
  if (Math.abs(dx) < 60 || Math.abs(dy) > 40) return;
  const i = sessions.findIndex((x) => x.id === current), next = sessions[i + (dx < 0 ? 1 : -1)];
  if (next) { haptic("selectionChanged"); openSession(next.id); }
}, { passive: true });
