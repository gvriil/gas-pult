// «Сообщить об ошибке» (владелец 22.11, тестировщики и фокус-ссылки): кнопка-жук у поля ввода → лист «Что не так?».
// Снимок экрана (задача владельца 23.11 — «настоящий снимок», библиотека с CDN только с SRI, как driver.js и xterm.js)
// делается сам при открытии листа: modern-screenshot 4.7.0 (MIT) с jsDelivr, точная версия и SRI, грузится только
// здесь и не попадает в репозиторий. Он рисует страницу средствами браузера (SVG foreignObject), поэтому видит всё
// оформление панели (color-mix, переменные). На снимке нет листа отчёта, тостов и тура; поля паролей и кодов и всё
// с атрибутом data-no-shot закрыты плашкой. Снимок — JPEG шириной до 1280 px и до 400 КБ; миниатюра в листе и
// «Убрать снимок». Не вышло (нет сети, CDN закрыт, ошибка) — отчёт уходит с описанием и строкой «снимок не получился».
// Описание экрана текстом — как раньше: экран, адрес (без #ссылки), размер окна, тема, язык, версия, последние 10
// ошибок JS и 10 сообщений панели. Устройство и браузер сервер узнаёт сам (по User-Agent).
// Сервер (/api/bug, teammsg.py): отчёт и снимок — файлы 0600 в bugs/, задача владельцу и штабу со ссылкой на снимок,
// уведомление владельцу, в этот чат — «Приняли». В демо отвечает js/demo.js — никуда не уходит.

const MAX = 2000;
export const SHOT_LIB = {
  src: "https://cdn.jsdelivr.net/npm/modern-screenshot@4.7.0/dist/index.js",
  sri: "sha512-iRizB3H0kZuwJ8rbggCO5iNu26GP5nm85QlpsxLzorb00pja9ujNs3UKzu4Jq4imdLA410POKduZLEy7exLX/g==",
};
const SHOT_W = 1280, SHOT_BYTES = 400 * 1024;
const NOT_IN_SHOT = ".sheet-bg, .toast, #notices, .driver-popover, .driver-overlay";
const MASK = 'input[type=password], input[autocomplete=one-time-code], input[autocomplete^="cc-"], [data-no-shot]';

function state() {
  const dark = document.documentElement.dataset.theme === "dark"
    || (document.documentElement.dataset.theme !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
  return {
    screen: [typeof view !== "undefined" ? view : "", typeof tab !== "undefined" ? tab : "", (typeof USE !== "undefined" && USE.cur) || ""].filter(Boolean).join(" · "),
    url: location.pathname + location.search,         // без #: в нём токен фокус-ссылки
    size: `${innerWidth}×${innerHeight} · ${devicePixelRatio || 1}x`,
    theme: dark ? "тёмная" : "светлая", lang: typeof LANG !== "undefined" ? LANG : "", build: String(typeof BUILD !== "undefined" ? BUILD || "" : ""),
    errors: typeof ERRS !== "undefined" ? [...ERRS] : [], ui: typeof UIMSG !== "undefined" ? [...UIMSG] : [],
  };
}

function loadLib() {                                   // один раз; не вышло — новая попытка при следующем открытии
  if (window.modernScreenshot?.domToCanvas) return Promise.resolve(window.modernScreenshot);
  return (loadLib.p ||= new Promise((ok, no) => {
    const js = Object.assign(document.createElement("script"), { src: SHOT_LIB.src, integrity: SHOT_LIB.sri, crossOrigin: "anonymous" });
    js.dataset.lib = "shot";
    const fail = () => { clearTimeout(t); js.remove(); loadLib.p = null; no(new Error("нет связи с CDN")); };
    const t = setTimeout(fail, 10000);
    js.onload = () => { clearTimeout(t); window.modernScreenshot?.domToCanvas ? ok(window.modernScreenshot) : fail(); };
    js.onerror = fail;
    document.head.append(js);
  }));
}

function smaller(c, k) {
  const d = Object.assign(document.createElement("canvas"), { width: Math.max(1, Math.round(c.width * k)), height: Math.max(1, Math.round(c.height * k)) });
  d.getContext("2d").drawImage(c, 0, 0, d.width, d.height);
  return d;
}
export function compress(c) {                          // JPEG до SHOT_BYTES: сначала качество, потом размер
  if (c.width > SHOT_W) c = smaller(c, SHOT_W / c.width);
  for (let i = 0; i < 5; i++, c = smaller(c, 0.75))
    for (const q of [0.82, 0.68, 0.55]) { const u = c.toDataURL("image/jpeg", q); if ((u.length - 23) * 0.75 <= SHOT_BYTES) return u; }
  throw new Error("снимок слишком большой");
}

async function snap() {
  const lib = await loadLib(), b = document.body, css = getComputedStyle(document.documentElement);
  const fill = css.getPropertyValue("--text-muted").trim() || "gray", bg = css.getPropertyValue("--bg-canvas").trim() || "white";
  const canvas = await lib.domToCanvas(b, {
    width: b.clientWidth, height: b.clientHeight, scale: Math.min(SHOT_W / Math.max(1, b.clientWidth), Math.min(2, devicePixelRatio || 1)),
    backgroundColor: bg, font: false, timeout: 8000, style: { margin: "0", left: "0", top: "0" },
    filter: (n) => !(n instanceof Element && n.matches(NOT_IN_SHOT)) && !n.parentElement?.closest("[data-no-shot]"),   // внутри data-no-shot — ничего
    onCloneEachNode: (c) => {                          // пароли и коды — плашкой, без текста
      if (!(c instanceof Element) || !c.matches(MASK)) return;
      if ("value" in c) { c.value = ""; c.setAttribute("value", ""); c.removeAttribute("placeholder"); }
      for (const [k, v] of [["background", fill], ["color", "transparent"], ["-webkit-text-fill-color", "transparent"]]) c.style.setProperty(k, v, "important");
    },
  });
  return compress(canvas);
}

export function open(w) {
  if (!w) return toast("Откройте чат — сообщение уйдёт из него");
  const ctx = state();
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = "sheet.bug";
  bg.innerHTML = `<div class="sheet" role="dialog" aria-labelledby="bugTitle"><h3 id="bugTitle">Сообщить об ошибке</h3>
    <p class="note" style="margin:4px 16px 10px">Сообщение уйдёт команде, не в чат с ИИ. Ответим здесь, в этом чате.</p>
    <div class="field" style="margin:0 16px"><label for="bugText">Что не так?</label><textarea id="bugText" rows="4" maxlength="${MAX}" placeholder="Например: нажал «Отправить», а фото не ушло"></textarea>
${matchMedia("(pointer: fine)").matches ? `
      <p class="note" style="margin:4px 0 0">Картинку можно вставить из буфера (Ctrl+V). Отправить — Ctrl+Enter.</p>` : ""}</div>
    <div style="margin:10px 16px 0;display:flex;align-items:center;gap:10px">
      <img id="bugPrev" alt="Снимок экрана" hidden style="width:64px;height:64px;flex:none;object-fit:cover;object-position:top;border-radius:var(--radius-sm);border:1px solid var(--border-subtle);background:var(--bg-subtle)">
      <div style="flex:1;min-width:0"><p class="note" id="bugShotNote" role="status" style="margin:0"></p>
        <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px"><button class="btn ghost sm" id="bugDrop" type="button" hidden>${ic("x")} Убрать снимок</button>
        <button class="btn ghost sm" id="bugPick" type="button">${ic("image")} Своя картинка</button>
        <button class="btn ghost sm" id="bugMic" type="button" aria-pressed="false">${ic("mic")} <span>Надиктовать</span></button></div></div>
      <input type="file" id="bugFile" accept="image/*" hidden></div>
    <details style="margin:10px 16px 0"><summary class="note">Что приложим автоматически</summary>
      <ul class="note" style="margin:6px 0 0;padding-left:18px">
        <li>Снимок экрана без этого листа. Поля паролей и кодов на снимке закрыты</li>
        <li>Экран: ${esc(ctx.screen || "—")}; размер окна ${esc(ctx.size)}; тема ${esc(ctx.theme)}</li>
        <li>Устройство и браузер — по данным браузера</li>
        <li>Последние ошибки страницы: ${ctx.errors.length}; последние сообщения панели: ${ctx.ui.length}</li></ul></details>
    <p class="note" id="bugMsg" role="status" style="margin:8px 16px 0"></p>
    <div class="row2"><button class="btn ghost" data-close type="button">Отмена</button><button class="btn" id="bugGo" type="button">Отправить</button></div></div>`;
  const $f = (s) => bg.querySelector(s), text = $f("#bugText"), file = $f("#bugFile"), msg = $f("#bugMsg");
  const prev = $f("#bugPrev"), note = $f("#bugShotNote"), drop = $f("#bugDrop");
  let shot = "", how = "wait";                         // wait → auto | failed; человек: own | removed
  const show = (u, h) => {
    shot = u; how = h; prev.hidden = !u; drop.hidden = !u; if (u) prev.src = u; else prev.removeAttribute("src");
    note.textContent = { wait: "Делаю снимок экрана…", removed: "Снимок убран — отправим только описание экрана.",
      failed: "Снимок не получился — отправим описание экрана. Можно приложить свою картинку.",
      own: "Приложим вашу картинку — её можно убрать." }[h] || "Снимок экрана приложится сам — его можно убрать.";
  };
  show("", "wait");
  const auto = snap().then((u) => { if (how === "wait") show(u, "auto"); },
    (e) => { ctx.shot_note = "снимок не получился: " + e.message; if (how === "wait") show("", "failed"); });
  document.body.append(bg);
  const close = () => { if (rec) rec.stop(); bg.remove(); document.removeEventListener("keydown", esc_); };
  const esc_ = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", esc_);
  // Щелчок по фону закрывает, только если и нажали, и отпустили на фоне, а текста нет (papasan 24.11: растянул поле
  // за уголок, отпустил мышь вне листа — лист закрылся вместе с текстом)
  let downBg = false;
  bg.addEventListener("pointerdown", (e) => { downBg = e.target === bg; });
  bg.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) return close();
    if (e.target === bg && downBg && !text.value.trim()) close();
  });
  text.addEventListener("keydown", (e) => {                 // Ctrl+Enter / ⌘+Enter — отправить (владелец 23.11)
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); $f("#bugGo").click(); }
  });
  bg.addEventListener("paste", async (e) => {               // картинка из буфера (владелец 23.11)
    const f = [...(e.clipboardData?.files || [])].find((x) => x.type.startsWith("image/"));
    if (!f) return;
    e.preventDefault();
    try { show(await (await part("feedback")).shrink(f), "own"); msg.textContent = ""; }
    catch (er) { msg.textContent = er.message; }
  });
  const micB = $f("#bugMic");                                // голосом (владелец 24.11): запись → текст в поле
  let rec = null;
  micB.onclick = async () => {
    if (rec) return rec.stop();
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { msg.textContent = "Этот браузер не даёт микрофон — диктуйте кнопкой на клавиатуре"; return; }
    let stream;
    try { stream = await micGet(); } catch (er) { return micHelp(er, () => micB.click()); }
    const type = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg"].find((t) => MediaRecorder.isTypeSupported(t)) || "";
    const chunks = [];
    rec = new MediaRecorder(stream, type ? { mimeType: type } : {});
    rec.ondataavailable = (ev) => ev.data.size && chunks.push(ev.data);
    rec.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop()); rec = null;
      micB.setAttribute("aria-pressed", "false"); micB.querySelector("span").textContent = "Распознаю…"; micB.disabled = true;
      try {
        const d = await (await part("voicejob")).sttJob(new Blob(chunks, { type: type || "audio/webm" }), new AbortController().signal);
        const t = (d.text || "").trim();
        if (t) { text.value = (text.value + " " + t).trim(); text.focus(); } else msg.textContent = "Ничего не расслышал — попробуйте ещё раз";
      } catch (er) { msg.textContent = "Не распознал: " + er.message; }
      micB.disabled = false; micB.querySelector("span").textContent = "Надиктовать";
    };
    rec.start(); micB.setAttribute("aria-pressed", "true"); micB.querySelector("span").textContent = "Стоп";
  };
  drop.onclick = () => show("", "removed");
  $f("#bugPick").onclick = () => file.click();
  file.onchange = async () => {
    const f = file.files?.[0]; if (!f) return;
    try { show(await (await part("feedback")).shrink(f), "own"); msg.textContent = ""; }
    catch (e) { msg.textContent = e.message; }
  };
  $f("#bugGo").onclick = () => busy($f("#bugGo"), "Отправляю…", async () => {
    const t = text.value.trim();
    if (!t) { msg.textContent = "Напишите в двух словах, что не так"; return text.focus(); }
    if (how === "wait") await Promise.race([auto, new Promise((r) => setTimeout(r, 4000))]);   // снимок почти готов — подождём
    if (how === "removed") ctx.shot_note = "снимок убрал человек";
    else if (how === "wait") ctx.shot_note = "снимок не успел";
    try {
      const r = await api("/api/bug", { w, text: t, ctx, shot });
      close(); toast(DEMO ? "В демо сообщение никуда не уходит" : "Отправлено — команда ответит в этом чате", 3500);
      if (w === current && r?.ack) teamAdd(r.ack);
    } catch (e) { msg.textContent = e.message; }
  });
  setTimeout(() => text.focus(), 50);
}
