// ---------- секреты в поле ввода (secrets_guard.py) ----------
// Ключ, токен или пароль в сообщении — спросить до отправки: модель не должна его видеть. Правила — #secretRules,
// те же, что у хука Claude Code; тест прогоняет набор образцов через обе стороны.
// secrets:begin
const SECRET_RULES = JSON.parse(document.getElementById("secretRules").textContent)
  .map((r) => ({ ...r, rx: new RegExp(r.re, "g" + r.flags) }));
function redactSecrets(text) {
  const found = [];
  for (const r of SECRET_RULES) {
    const mask = `[скрыт: ${r.label}]`;
    const out = text.replace(r.rx, (...m) => r.g ? m[1] + mask + (m[3] || "") : mask);
    if (out !== text) { if (!found.includes(r.label)) found.push(r.label); text = out; }
  }
  return { text, found };
}
// secrets:end
let secretPass = null;                               // «Отправить как есть» — для этого текста больше не спрашивать
function secretSheet(typed, s) {
  helpSheet("sheet.secret");
  sheet("Похоже на ключ: " + s.found.join(", "), [
    { info: true, icon: "lock", label: "Модель не должна видеть ключи", sub: "Уберите его из сообщения, а сам ключ положите в «Интеграции» — там он хранится на сервере и модели не показывается." },
    { label: "Убрать и отправить", icon: "check", sub: "вместо ключа уйдёт «[скрыт: …]»", run: () => { $("input").value = s.text; secretPass = null; sendText(); } },
    { label: "Отправить как есть", icon: "warn", sub: "если это не ключ; в сессии с защитой пульта сообщение с ключом модель не получит", run: () => { secretPass = typed; sendText(); } },
  ], "Отмена");
}

// ---------- ввод ----------
async function sendText() {
  if (DRAFT) return draftSend();                    // новый чат: окно — при первой отправке
  if (cur()?.status === "stopped") return toast("Сессия остановлена — сначала «Перезапустить»", 4000);
  if (files.some((f) => !f.path)) return toast("Подождите — файл ещё загружается");
  const typed = $("input").value.trim();
  if (!typed && !files.length) return toast("Напишите, надиктуйте или прикрепите файл");
  if (typed && secretPass !== typed) { const s = redactSecrets(typed); if (s.found.length) return secretSheet(typed, s); }
  secretPass = null;
  const text = (typed || "Посмотри файл.") + (files.length ? "\n\n" + files.map((f) => "Файл из панели: " + f.path).join("\n") : "");
  const p = { text, state: "sending", id: msgId(), w: current }; pending.push(p);
  $("input").value = ""; const sent = files; files = []; renderFiles(); grow();
  if (tab === "chat") renderChat(true); else toast("Отправлено в «" + (cur()?.name || "сессию") + "»");
  await deliver(p, () => { if (!$("input").value.trim()) { $("input").value = typed; files = sent; renderFiles(); grow(); } });
}
const msgId = () => crypto.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2);
// Обрыв связи — не «не отправлено»: текст мог уже дойти. Повторяем с тем же id (сервер второй раз не вставит), а
// переписку сверяем — дошедшее сообщение уходит из «ожидающих» само. Отказ сервера — честная ошибка, текст — в поле.
async function deliver(p, restore) {
  for (const pause of [0, 1500, 4000, 8000]) {
    if (pause) { p.state = "unsure"; renderChat(true); await new Promise((r) => setTimeout(r, pause)); }
    if (!pending.includes(p)) return;               // уже видно в переписке — дошло
    try {
      actLocal = { phase: "sent", text: "Отправлено", since: Date.now() / 1000 + actSkew, w: p.w }; paintAct();
      await api("/api/send", { w: p.w, text: p.text, id: p.id });
      actLocal = null; liveAct = { phase: "delivered", text: "Доставлено в сессию", since: Date.now() / 1000 + actSkew, w: p.w };
      paintAct(); setTimeout(() => pollAct(true), 300);                // дальше — сервер: ход, инструменты, «Готово»
      p.state = "sent"; haptic("notificationOccurred", "success");
      if (cur()?.status !== "busy") lastStatus = "busy";
      setTimeout(() => { if (tab === "chat") hist = []; loadContent(); }, tab === "chat" ? 2000 : 1200);
      return renderChat(true);
    } catch (e) {
      actLocal = null;
      if (!e.net) { p.state = "fail"; p.err = e.message; restore?.(); haptic("notificationOccurred", "error"); return renderChat(true); }
    }
  }
  p.state = "lost"; haptic("notificationOccurred", "warning"); renderChat(true);
}
$("content").addEventListener("click", (e) => {
  const b = e.target.closest("[data-resend]"), p = b && pending.find((x) => x.id === b.dataset.resend);
  if (p) deliver(p);                                // тот же id — даже если первое дошло, второй раз не вставится
});
$("plus").onclick = () => helpSheet("sheet.attach") || sheet("Прикрепить", [
  { label: "Сфотографировать", icon: "camera", run: () => $("fCam").click() },
  { label: "Фото или видео из галереи", icon: "image", run: () => $("fPhoto").click() },
  { label: "Файл с устройства", icon: "file", sub: "документ, таблица, архив — до 50 МБ", run: () => $("fFile").click() },
]);
for (const id of ["fCam", "fPhoto", "fFile"]) $(id).onchange = (e) => { [...e.target.files].forEach(upload); e.target.value = ""; };
async function upload(f) {
  if (f.size > 50 * 1024 * 1024) return toast(`«${f.name}» больше 50 МБ`, 4000);
  const item = { name: f.name || "photo.jpg", path: null }; files.push(item); renderFiles();
  try {
    item.path = cur()?.space                         // сессия пространства: файл — в её папку (sfPut), агенту — имя
      ? (await sfPut(current, f, item.name)).name
      : (await api("/api/upload", f, f.type || "application/octet-stream", { "X-File-Name": encodeURIComponent(item.name) })).path;
  }
  catch (e) { files = files.filter((x) => x !== item); toast(`«${item.name}» не загрузился: ${e.message}`, 4500); }
  renderFiles();
}
function renderFiles() {
  $("attach").hidden = !files.length;
  $("attach").innerHTML = files.map((f, i) => `<span>${ic(f.path ? "file" : "wait", "s16")}<em>${esc(f.name)}</em><button data-rmf="${i}" aria-label="Убрать">${ic("x", "s16")}</button></span>`).join("");
  sync(); padDock();
}
$("attach").onclick = (e) => { const b = e.target.closest("[data-rmf]"); if (b) { files.splice(+b.dataset.rmf, 1); renderFiles(); } };
// Микрофон всегда на месте (предсказуемо); «Отправить» появляется рядом, когда есть что отправить.
function sync() { const has = !!$("input").value.trim() || files.length > 0; $("send").hidden = !has; $("hintBtn").hidden = !hint || has; }
// Подсказка Claude Code (бледный текст в его строке ввода): в пустом поле — вместо «Сообщение для …»;
// «вставить» (или Tab на компьютере) — текст в поле, отправляете сами.
function setHint(h) {
  if (h === hint) return;
  hint = h; sync();
  const s = cur(); if (s) $("input").placeholder = hint || "Сообщение для " + s.name + "…";
}
async function loadHint(s) {
  if (s.status !== "idle" || tab !== "chat" || meta?.role === "viewer") return setHint("");
  try { const d = await api("/api/hint?w=" + encodeURIComponent(s.id)); if (s.id === current) setHint(d.hint || ""); } catch (e) {}
}
function takeHint() { if (!hint) return; $("input").value = hint; grow(); sync(); $("input").focus(); }
$("hintBtn").onclick = takeHint;
$("input").addEventListener("keydown", (e) => { if (e.key === "Tab" && hint && !$("input").value) { e.preventDefault(); takeHint(); } });
// enter:start — что делает Enter в поле ввода (то же в простом режиме; считает и тест).
// Компьютер (есть мышь/тачпад — any-pointer: fine): Enter — отправить, Shift/Alt+Enter — новая строка.
// Телефон и планшет без мыши: Enter экранной клавиатуры — новая строка, отправка — кнопкой-стрелкой.
// Ctrl/Cmd+Enter отправляет всегда (внешняя клавиатура к планшету). Во время набора (IME, isComposing) — не трогаем.
function enterAction(e, touch) {                   // "send" | "newline" | null (пусть браузер сам)
  if (e.key !== "Enter" || e.isComposing || e.keyCode === 229) return null;
  if (e.ctrlKey || e.metaKey) return "send";
  if (touch) return null;                          // экранная клавиатура: обычный перенос строки
  return e.shiftKey || e.altKey ? "newline" : "send";
}
// enter:end
const touchInput = () => !matchMedia("(any-pointer: fine)").matches && (matchMedia("(pointer: coarse)").matches || navigator.maxTouchPoints > 0);
function onEnter(t, send, grown) {
  t.addEventListener("keydown", (e) => {
    const a = enterAction(e, touchInput()); if (!a) return;
    e.preventDefault();
    if (a === "send") return send();
    t.setRangeText("\n", t.selectionStart, t.selectionEnd, "end"); grown();
  });
}
// Поле растёт со строками до ~6, дальше — прокрутка внутри.
const MAX_LINES = 6;
// Измерение — раз в кадр (requestAnimationFrame): ввод, вставка и диктовка не перестраивают раскладку на каждое событие.
function fitLines(t) {
  if (t.__fit) return;
  t.__fit = requestAnimationFrame(() => {
    t.__fit = 0;
    const cs = getComputedStyle(t), lh = parseFloat(cs.lineHeight) || 22;
    const max = Math.round(lh * MAX_LINES + parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom));
    t.style.height = "auto"; const h = t.scrollHeight;
    t.style.height = Math.min(h, max) + "px"; t.style.overflowY = h > max ? "auto" : "hidden";
    if (t.__end) { t.__end = false; t.scrollTop = t.scrollHeight; }
  });
}
onEnter($("input"), () => sendText(), () => grow());
// ---------- микрофон: запись → «Распознаю…» → текст в поле ----------
// Поток микрофона держим, пока панель открыта: разрешение не спрашивается перед каждой записью. Между записями
// дорожки выключены (track.enabled = false); через 2 минуты простоя или когда панель скрыта — поток освобождается
// полностью. Между перезапусками Mini App разрешение помнит сам Telegram/система — на это панель не влияет.
const MIC_IDLE = 120000, STT_TIMEOUT = DEMO && params.get("stt") === "slow" ? 5000 : 90000;   // ?demo&stt=slow — таймаут за 5 с
let micStream = null, micIdle = 0, micBar = null, micHidden = [];   // micBar — строка записи/распознавания вместо поля ввода
function micRelease() {
  clearTimeout(micIdle); micIdle = 0;
  if (micStream && !rec && !vs) { micStream.getTracks().forEach((t) => t.stop()); micStream = null; }
}
async function micGet() {
  clearTimeout(micIdle);
  if (micStream?.getAudioTracks().some((t) => t.readyState === "live")) { micStream.getTracks().forEach((t) => (t.enabled = true)); return micStream; }
  micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  return micStream;
}
function micPark() {                                // запись закончилась — дорожки выключены, поток ждёт следующей
  if (!micStream) return;
  if (document.hidden) return micRelease();
  micStream.getTracks().forEach((t) => (t.enabled = false));
  clearTimeout(micIdle); micIdle = setTimeout(micRelease, MIC_IDLE);
}
document.addEventListener("visibilitychange", () => { if (document.hidden && !rec && !vs) micRelease(); });
// Поле и кнопки прячем: пока идёт запись или распознавание, ввода нет. ``live`` — диктовка потоком: поле остаётся
// на месте (в нём растёт текст), прячутся только кнопки. ``where`` — полный режим (MIC_FULL) или простой (MIC_SIMPLE).
function micBarOpen(where = MIC_FULL, live = false) {
  const hide = live ? where.liveHide : where.hide;
  if (micBar && micBar.dataset.k !== hide.join()) micBarClose();
  if (!micBar) {
    micBar = document.createElement("div"); micBar.dataset.k = hide.join(); micHidden = hide;
    for (const id of hide) $(id).hidden = true; $(live ? where.liveAfter : where.after).after(micBar);
  }
  return micBar;
}
function micBarClose() {
  if (!micBar) return;
  micBar.remove(); micBar = null;
  for (const id of micHidden) $(id).hidden = false; sync(); padDock();
}
async function toggleMic() {
  if (rec) return rec.stop();                       // нажатие во время записи — как «Стоп»: текст в поле
  if (micBar) return;                               // идёт распознавание — ждём ответа
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)
    return toast("Этот Telegram не даёт панели микрофон — диктуйте кнопкой микрофона на клавиатуре", 5000);
  let stream;
  try { stream = await micGet(); }
  catch (e) { return toast("Нет доступа к микрофону: " + e.message, 5000); }
  const type = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg"].find((t) => MediaRecorder.isTypeSupported(t)) || "";
  const chunks = []; let cancelled = false, sendNow = false, raf = 0;
  rec = new MediaRecorder(stream, type ? { mimeType: type } : {});
  setBars(true);                                     // идёт запись — панель с записью не прячем
  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  const bar = micBarOpen(); bar.className = "recbar";
  bar.innerHTML = `<span class="dotrec"></span><canvas title="Остановить и вставить текст"></canvas><span class="t">0:00</span>
    <button class="no" aria-label="Отменить запись" title="Отменить">${ic("x", "s16")}</button>
    <button class="txt" aria-label="Стоп: распознать и вставить текст в поле" title="Остановить запись, текст — в поле">${ic("stop", "s16")}Стоп</button>
    <button class="ok" aria-label="Стоп и отправить сразу" title="Остановить и отправить сразу">${ic("send", "s16")}</button>`;
  const cv = bar.querySelector("canvas"), g = cv.getContext("2d"), t0 = Date.now();
  const ac = new (window.AudioContext || window.webkitAudioContext)(), an = ac.createAnalyser();
  an.fftSize = 256; ac.createMediaStreamSource(stream).connect(an);
  const lv = new Uint8Array(an.frequencyBinCount), levels = [];
  const color = getComputedStyle(document.documentElement).getPropertyValue("--status-danger").trim();
  (function draw() {
    an.getByteTimeDomainData(lv);
    let peak = 0; for (const v of lv) peak = Math.max(peak, Math.abs(v - 128));
    levels.push(Math.min(1, peak / 64)); const w = cv.width = cv.clientWidth * 2, h = cv.height = 56, n = Math.floor(w / 8);
    g.fillStyle = color; levels.slice(-n).forEach((v, i) => { const bh = Math.max(4, v * h); g.fillRect(i * 8, (h - bh) / 2, 5, bh); });
    bar.querySelector(".t").textContent = mmss((Date.now() - t0) / 1000);
    raf = requestAnimationFrame(draw);
  })();
  bar.querySelector(".no").onclick = () => { cancelled = true; rec.stop(); };
  bar.querySelector(".txt").onclick = cv.onclick = () => rec.stop();
  bar.querySelector(".ok").onclick = () => { sendNow = true; rec.stop(); };
  rec.onstop = () => {
    cancelAnimationFrame(raf); ac.close(); rec = null; micPark();
    if (cancelled) { micBarClose(); return toast("Запись отменена"); }
    const blob = new Blob(chunks, { type: (type || "audio/webm").split(";")[0] });
    if (!blob.size) return sttFail("Запись пустая — проверьте микрофон и попробуйте ещё раз", null);
    sttRun(blob, sendNow);
  };
  rec.start(); haptic("impactOccurred", "medium"); padDock();
}
// Распознавание: строка остаётся на месте с «Распознаю…» и секундами, пока сервер не ответит (до 90 с).
async function sttRun(blob, sendNow, where = MIC_FULL) {
  const bar = micBarOpen(where), ctl = new AbortController(), t0 = Date.now(), inp = $(where.inp);
  bar.className = "recbar stt";
  bar.innerHTML = `<span class="spin"></span><span class="msg" role="status">Распознаю…</span><span class="t">0:00</span>
    <button class="no" aria-label="Отменить распознавание" title="Отменить">${ic("x", "s16")}</button>`;
  const tick = setInterval(() => {
    const ms = Date.now() - t0; bar.querySelector(".t").textContent = mmss(ms / 1000);
    if (ms > 15000) bar.querySelector(".msg").textContent = "Распознаю… ещё немного";
  }, 500);
  const timer = setTimeout(() => ctl.abort("timeout"), STT_TIMEOUT);
  let gone = false;
  bar.querySelector(".no").onclick = () => { gone = true; ctl.abort("cancel"); };
  try {
    const stop = new Promise((_, no) => ctl.signal.addEventListener("abort", () => no(new Error("прервано"))));
    const d = await Promise.race([api("/api/stt", blob, blob.type, null, ctl.signal), stop]);
    const text = (d.text || "").trim();
    if (!text) throw Object.assign(new Error("Ничего не расслышал — попробуйте ещё раз"), { empty: true });
    micBarClose();
    if (d.fallback) toast("ElevenLabs не ответил — распознал локально", 3500);
    inp.value = (inp.value + " " + text).trim(); where === MIC_SIMPLE ? sGrow() : grow();
    if (sendNow) return where.send();
    inp.focus(); toast(LT("mic.check", "Проверьте текст и отправьте"), 3500);
  } catch (e) {
    if (gone) { micBarClose(); return toast("Распознавание отменено"); }
    if (ctl.signal.aborted) return sttFail("Сервер не распознал за " + STT_TIMEOUT / 1000 + " секунд — попробуйте ещё раз или наберите текстом", blob, sendNow, where);
    if (e.empty || /расслышал/.test(e.message)) return sttFail("Ничего не расслышал — попробуйте ещё раз", null, false, where);
    sttFail("Не распознал: " + e.message, blob, sendNow, where);
  } finally { clearInterval(tick); clearTimeout(timer); }
}
// Ошибка — в той же строке, пока не нажмут: «Повторить» (та же запись) или «Записать снова»; ✕ — вернуть поле.
function sttFail(text, blob, sendNow, where = MIC_FULL) {
  const bar = micBarOpen(where); bar.className = "recbar err"; haptic("notificationOccurred", "error");
  bar.innerHTML = `${ic("warn", "s16")}<span class="msg" role="alert">${esc(text)}</span>
    <button class="txt again">${ic(blob ? "refresh" : "mic", "s16")}${blob ? "Повторить" : "Записать"}</button>
    <button class="no" aria-label="Закрыть" title="Закрыть">${ic("x", "s16")}</button>`;
  bar.querySelector(".no").onclick = micBarClose;
  bar.querySelector(".again").onclick = () => { if (blob) return sttRun(blob, sendNow, where); micBarClose(); micTap(where); };
}
// ---------- голос потоком (задача 46): удержание микрофона → текст в поле, пока говорите ----------
// Звук: AudioWorklet (нет — ScriptProcessor) → PCM 16 кГц моно, кусками по 100 мс → WebSocket /api/stt/stream → служба
// T-one на сервере → частичный текст в поле. Отпустили — итог за доли секунды. Удержание короче HOLD_MS — нажатие:
// запись идёт до «Стоп», как раньше. Службы нет или поток оборвался — та же запись уходит WAV-файлом в /api/stt.
const HOLD_MS = 350, STT_RATE = 16000, FINAL_WAIT = 4000;
const MIC_FULL = { inp: "input", hide: ["input", "ctools"], after: "input", liveHide: ["ctools"], liveAfter: "ctools", send: () => sendText() };
const MIC_SIMPLE = { inp: "sInput", hide: ["sComp"], after: "sComp", liveHide: ["sMic", "sSend"], liveAfter: "sComp", send: () => sSend() };
// Понижение частоты: среднее по окну (простой фильтр) → Int16, по 1600 отсчётов (100 мс). Тот же класс — в AudioWorklet.
class Down {
  constructor(rate, post, to = 16000) { this.r = rate / to; this.post = post; this.acc = 0; this.cnt = 0; this.pos = 0; this.out = new Int16Array(1600); this.n = 0; }
  push(ch) {
    for (let i = 0; i < ch.length; i++) {
      this.acc += ch[i]; this.cnt++; this.pos += 1;
      if (this.pos < this.r) continue;
      this.pos -= this.r; const v = Math.max(-1, Math.min(1, this.acc / this.cnt)); this.acc = 0; this.cnt = 0;
      this.out[this.n++] = v < 0 ? v * 32768 : v * 32767;
      if (this.n === this.out.length) { this.post(this.out); this.out = new Int16Array(1600); this.n = 0; }
    }
  }
  flush() { if (this.n) { this.post(this.out.slice(0, this.n)); this.n = 0; } }
}
const PCM_WORKLET = `const Down = ${Down.toString()};
registerProcessor("gp-pcm16", class extends AudioWorkletProcessor {
  constructor() { super(); this.d = new Down(sampleRate, (a) => this.port.postMessage(a, [a.buffer]), ${STT_RATE}); this.port.onmessage = () => { this.d.flush(); this.port.postMessage("flushed"); }; }
  process(inputs) { const ch = inputs[0] && inputs[0][0]; if (ch) this.d.push(ch); return true; } });`;
let vs = null, micPress = null;                     // vs — идущая диктовка потоком; micPress — палец на кнопке
const canStream = () => !!(window.AudioContext || window.webkitAudioContext) && !!navigator.mediaDevices?.getUserMedia;
// Звук микрофона → куски Int16 (onpcm). AudioWorklet — из Blob: панель — один файл, отдельного .js нет.
// ``ac`` создаётся прямо в нажатии (до ожидания микрофона): иначе iOS оставляет его на паузе — звука не будет.
async function pcmCapture(ac, stream, onpcm) {
  const src = ac.createMediaStreamSource(stream), an = ac.createAnalyser();
  an.fftSize = 256; src.connect(an);
  let flush;
  if (ac.audioWorklet && window.AudioWorkletNode) {
    const url = URL.createObjectURL(new Blob([PCM_WORKLET], { type: "text/javascript" }));
    try { await ac.audioWorklet.addModule(url); } finally { URL.revokeObjectURL(url); }
    const node = new AudioWorkletNode(ac, "gp-pcm16", { numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1, channelCountMode: "explicit" });
    let done = null;
    node.port.onmessage = (e) => (e.data === "flushed" ? done?.() : onpcm(new Int16Array(e.data.buffer || e.data)));
    src.connect(node); node.connect(ac.destination);  // выход молчит (нули), но без подключения узел может не работать
    flush = () => new Promise((ok) => { done = ok; node.port.postMessage("flush"); setTimeout(ok, 300); });
  } else {                                           // старые WebView: ScriptProcessor в основном потоке
    const sp = ac.createScriptProcessor(2048, 1, 1), d = new Down(ac.sampleRate, onpcm, STT_RATE);
    sp.onaudioprocess = (e) => d.push(e.inputBuffer.getChannelData(0));
    src.connect(sp); sp.connect(ac.destination);
    flush = async () => d.flush();
  }
  if (ac.state === "suspended") await ac.resume().catch(() => {});
  return { an, flush, close: () => ac.close().catch(() => {}) };
}
function wavBlob(chunks, rate) {                     // запасной путь: та же запись файлом WAV для /api/stt
  const n = chunks.reduce((a, c) => a + c.length, 0), b = new DataView(new ArrayBuffer(44 + n * 2));
  const w = (o, s) => { for (let i = 0; i < s.length; i++) b.setUint8(o + i, s.charCodeAt(i)); };
  w(0, "RIFF"); b.setUint32(4, 36 + n * 2, true); w(8, "WAVE"); w(12, "fmt "); b.setUint32(16, 16, true); b.setUint16(20, 1, true); b.setUint16(22, 1, true);
  b.setUint32(24, rate, true); b.setUint32(28, rate * 2, true); b.setUint16(32, 2, true); b.setUint16(34, 16, true); w(36, "data"); b.setUint32(40, n * 2, true);
  let o = 44; for (const c of chunks) for (let i = 0; i < c.length; i++, o += 2) b.setInt16(o, c[i], true);
  return new Blob([b.buffer], { type: "audio/wav" });
}
function sttSocket() {                               // демо — подмена распознавания (demoStt), иначе настоящий WebSocket
  if (DEMO) return new DemoStt();
  const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/api/stt/stream");
  ws.binaryType = "arraybuffer"; return ws;
}
// Нажатие на микрофон: палец держат — диктовка до отпускания; коротко — запись до «Стоп». Нет потока в браузере — как раньше.
function micTap(where) {
  if (vs || micBar) return;
  if (!canStream()) return where === MIC_FULL ? toggleMic() : toast(LT("mic.none", "Этот Telegram не даёт панели микрофон — диктуйте кнопкой микрофона на клавиатуре"), 5000);
  voiceStart(where);
}
function micDown(e, where) {
  if (e.button > 0 || vs || micBar) return;
  e.preventDefault(); micPress = { t: Date.now(), where };
  micTap(where);
}
function micUp() {
  const p = micPress; micPress = null;
  if (!p || !vs || vs.ending) return;
  if (Date.now() - p.t >= HOLD_MS) { vs.hold = true; voiceStop(false); }   // держали — отпустили: итог в поле
}
document.addEventListener("pointerup", micUp); document.addEventListener("pointercancel", micUp);
async function voiceStart(where) {
  const inp = $(where.inp);
  const s = vs = { where, inp, base: inp.value.trim(), pcm: [], queue: [], ws: null, ready: false, ending: false, stopping: false, done: false,
                   partial: "", sendNow: false, hold: false, t0: Date.now(), raf: 0, cap: null, timer: 0 };
  const ac = new (window.AudioContext || window.webkitAudioContext)(); ac.resume?.().catch(() => {});
  let stream;
  try { stream = await micGet(); }
  catch (e) { ac.close().catch(() => {}); vs = null; return toast(LT("mic.denied", "Нет доступа к микрофону: {e}").replace("{e}", e.message), 5000); }
  if (vs !== s) return ac.close().catch(() => {});
  try {
    s.cap = await pcmCapture(ac, stream, (a) => {
      if (s.done || s.stopping) return;
      s.pcm.push(a);
      if (s.ready && s.ws?.readyState === 1) s.ws.send(a.buffer); else s.queue.push(a);
    });
  } catch (e) { ac.close().catch(() => {}); vs = null; micPark(); return where === MIC_FULL ? toggleMic() : toast(LT("mic.none", "Этот Telegram не даёт панели микрофон — диктуйте кнопкой микрофона на клавиатуре"), 5000); }
  if (vs !== s) { s.cap.close(); return; }
  setBars(true); voiceBar(s); haptic("impactOccurred", "medium");
  try { s.ws = sttSocket(); } catch (e) { s.ws = null; }
  if (!s.ws) return;
  s.ws.onopen = () => s.ws.send(JSON.stringify({ init: tg?.initData || "", focus: FOCUS, rate: STT_RATE }));
  s.ws.onmessage = (e) => {
    if (typeof e.data !== "string" || s.done) return;
    let m; try { m = JSON.parse(e.data); } catch (_) { return; }
    if (m.ready) { s.ready = true; for (const a of s.queue.splice(0)) s.ws.send(a.buffer); if (s.stopping) s.ws.send('{"end": true}'); return; }
    if (m.partial != null) { s.partial = m.partial; return voiceShow(s); }
    if (m.final != null) return voiceDone(s, m.final);
    if (m.error) { s.ws.onclose = null; s.ws.close(); s.ws = null; if (s.stopping) voiceFallback(s); }   // дальше — запись целиком
  };
  s.ws.onclose = () => { s.ws = null; if (s.stopping && !s.done) voiceFallback(s); };
}
function voiceShow(s) {
  s.inp.value = [s.base, s.partial].filter(Boolean).join(" ");
  s.inp.__end = true; fitLines(s.inp); sync();   // «Отправить» — по тексту в поле (без опроса раз в 0,7 с)
}
// Строка записи под полем: поле видно — в нём растёт текст; ✕ — отменить, «Стоп» — текст в поле, ➤ — отправить.
function voiceBar(s) {
  const bar = micBarOpen(s.where, true); bar.className = "recbar live";
  s.inp.readOnly = true; s.inp.classList.add("dictating");
  bar.innerHTML = `<span class="dotrec"></span><canvas aria-hidden="true"></canvas><span class="t">0:00</span>
    <button class="no" aria-label="${esc(LT("mic.cancel", "Отменить запись"))}" title="${esc(LT("mic.cancel", "Отменить запись"))}">${ic("x", "s16")}</button>
    <button class="txt" aria-label="${esc(LT("mic.stop.title", "Остановить запись, текст — в поле"))}">${ic("stop", "s16")}${esc(LT("mic.stop", "Стоп"))}</button>
    <button class="ok" aria-label="${esc(LT("mic.send", "Остановить и отправить сразу"))}" title="${esc(LT("mic.send", "Остановить и отправить сразу"))}">${ic("send", "s16")}</button>`;
  const cv = bar.querySelector("canvas"), g = cv.getContext("2d"), lv = new Uint8Array(s.cap.an.frequencyBinCount), levels = [];
  const color = getComputedStyle(document.documentElement).getPropertyValue("--status-danger").trim();
  (function draw() {
    s.cap.an.getByteTimeDomainData(lv);
    let peak = 0; for (const v of lv) peak = Math.max(peak, Math.abs(v - 128));
    levels.push(Math.min(1, peak / 64)); const w = cv.width = cv.clientWidth * 2, h = cv.height = 56, n = Math.floor(w / 8);
    g.fillStyle = color; levels.slice(-n).forEach((v, i) => { const bh = Math.max(4, v * h); g.fillRect(i * 8, (h - bh) / 2, 5, bh); });
    bar.querySelector(".t").textContent = mmss((Date.now() - s.t0) / 1000);
    s.raf = requestAnimationFrame(draw);
  })();
  bar.querySelector(".no").onclick = () => voiceCancel(s);
  bar.querySelector(".txt").onclick = () => voiceStop(false);
  bar.querySelector(".ok").onclick = () => voiceStop(true);
}
function voiceEnd(s) {                              // микрофон и строка — на место; поле снова можно править
  cancelAnimationFrame(s.raf); s.cap?.close(); clearTimeout(s.timer);
  s.inp.readOnly = false; s.inp.classList.remove("dictating");
  if (vs === s) vs = null; micPark();
}
async function voiceStop(sendNow) {
  const s = vs; if (!s || s.ending) return;
  s.ending = true; s.sendNow = sendNow;
  cancelAnimationFrame(s.raf);
  const bar = micBar; if (bar) { bar.className = "recbar live stt"; bar.querySelector(".dotrec")?.replaceWith(Object.assign(document.createElement("span"), { className: "spin" })); }
  await s.cap.flush();                               // последний неполный кусок — тоже в поток
  if (s.done) return;
  s.stopping = true; s.cap.close(); micPark();       // микрофон гаснет сразу, не дожидаясь итога
  if (!s.ws) return voiceFallback(s);                // потока нет — запись целиком прежним путём
  if (s.ready) { for (const a of s.queue.splice(0)) s.ws.send(a.buffer); s.ws.send('{"end": true}'); }
  s.timer = setTimeout(() => voiceFallback(s), FINAL_WAIT);   // итог не пришёл — не ждём дольше
}
function voiceDone(s, text) {
  if (s.done) return; s.done = true;
  try { s.ws?.close(); } catch (_) {}
  voiceEnd(s); micBarClose();
  s.partial = (text || "").trim(); voiceShow(s); s.where === MIC_SIMPLE ? sGrow() : grow();
  if (!s.partial) { s.inp.value = s.base; return toast(LT("mic.empty", "Ничего не расслышал — попробуйте ещё раз"), 3500); }
  haptic("notificationOccurred", "success");
  if (s.sendNow) return s.where.send();
  if (!s.hold) { s.inp.focus(); toast(LT("mic.check", "Проверьте текст и отправьте"), 3500); }
}
function voiceFallback(s) {
  if (s.done) return; s.done = true;
  if (s.ws) { s.ws.onclose = null; try { s.ws.close(); } catch (_) {} }
  voiceEnd(s); s.inp.value = s.base; micBarClose(); sync();
  if (!s.pcm.length) return toast(LT("mic.empty", "Ничего не расслышал — попробуйте ещё раз"), 3500);
  sttRun(wavBlob(s.pcm, STT_RATE), s.sendNow, s.where);
}
function voiceCancel(s) {
  if (s.done) return; s.done = true;
  if (s.ws) { s.ws.onclose = null; try { if (s.ready) s.ws.send('{"cancel": true}'); s.ws.close(); } catch (_) {} }
  voiceEnd(s); s.inp.value = s.base; micBarClose(); fitLines(s.inp); sync();
  toast(LT("mic.cancelled", "Запись отменена"));
}
// Демо (?demo): подмена службы распознавания — те же сообщения, что у /api/stt/stream: слово на каждые 0,4 с звука.
// ?asr=off — службы нет (панель уходит на /api/stt), ?asr=slow — итог не приходит (запасной путь через 4 с).
const DEMO_STT = ["Покажи,", "что", "изменилось", "за", "сегодня"];
class DemoStt {
  constructor() { this.readyState = 0; this.bytes = 0; this.words = 0; setTimeout(() => { this.readyState = 1; this.onopen?.(); }, 60); }
  emit(m) { setTimeout(() => this.readyState === 1 && this.onmessage?.({ data: JSON.stringify(m) }), 30); }
  send(d) {
    if (typeof d !== "string") {
      this.bytes += d.byteLength; const k = Math.min(DEMO_STT.length, Math.floor(this.bytes / 12800));
      if (k !== this.words) { this.words = k; this.emit({ partial: DEMO_STT.slice(0, k).join(" ") }); }
      return;
    }
    const m = JSON.parse(d), mode = params.get("asr");
    if ("rate" in m) {
      if (mode !== "off") return this.emit({ ready: true });
      this.emit({ error: "служба распознавания не запущена", code: "asr_off" }); return setTimeout(() => this.close(), 60);
    }
    if (m.end && mode !== "slow") this.emit({ final: this.words ? DEMO_STT.join(" ") : "" });
  }
  close() { if (this.readyState === 3) return; this.readyState = 3; setTimeout(() => this.onclose?.(), 0); }
}
function grow() { fitLines($("input")); sync(); padDock(); }
$("send").onclick = sendText; $("input").oninput = grow;
// Микрофон: держать — диктовка, пока держите; коснуться — запись до «Стоп». С клавиатуры (Enter, пробел) — касание.
for (const [id, where] of [["mic", MIC_FULL], ["sMic", MIC_SIMPLE]]) {
  $(id).onpointerdown = (e) => micDown(e, where);
  $(id).onclick = (e) => { if (e.detail === 0) micTap(where); };
  $(id).oncontextmenu = (e) => e.preventDefault();   // долгое нажатие — не меню браузера
}
for (const ev of ["keyup", "change", "paste", "compositionend", "focus", "blur"]) $("input").addEventListener(ev, () => setTimeout(grow, 0));
