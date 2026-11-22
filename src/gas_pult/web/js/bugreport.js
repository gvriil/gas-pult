// «Сообщить об ошибке» (владелец 22.11, тестировщики и фокус-ссылки): кнопка-жук у поля ввода → лист «Что не так?».
// Картинку экрана браузер без сторонних библиотек сделать не может (html2canvas нельзя — без новых зависимостей),
// поэтому прикладываем состояние экрана текстом: какой экран открыт, адрес страницы (без #ссылки), размер окна,
// тема, язык, версия панели, последние 10 ошибок JS и последние 10 всплывающих сообщений интерфейса. Устройство и
// браузер сервер узнаёт сам (по User-Agent, как во «Вошёл: устройство»). Картинку человек может приложить сам.
// Сервер (/api/bug, teammsg.py): задача владельцу и штабу, уведомление владельцу, в этот чат — «Приняли».

const MAX = 2000;

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

export function open(w) {
  if (!w) return toast("Откройте чат — сообщение уйдёт из него");
  const ctx = state();
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = "sheet.bug";
  bg.innerHTML = `<div class="sheet" role="dialog" aria-labelledby="bugTitle"><h3 id="bugTitle">Сообщить об ошибке</h3>
    <p class="note" style="margin:4px 16px 10px">Сообщение уйдёт команде, не в чат с ИИ. Ответим здесь, в этом чате.</p>
    <div class="field" style="margin:0 16px"><label for="bugText">Что не так?</label><textarea id="bugText" rows="4" maxlength="${MAX}" placeholder="Например: нажал «Отправить», а фото не ушло"></textarea></div>
    <details style="margin:10px 16px 0"><summary class="note">Что приложим автоматически</summary>
      <ul class="note" style="margin:6px 0 0;padding-left:18px">
        <li>Экран: ${esc(ctx.screen || "—")}; размер окна ${esc(ctx.size)}; тема ${esc(ctx.theme)}</li>
        <li>Устройство и браузер — по данным браузера</li>
        <li>Последние ошибки страницы: ${ctx.errors.length}; последние сообщения панели: ${ctx.ui.length}</li>
        <li>Это описание, а не картинка экрана. Картинку можно приложить ниже</li></ul></details>
    <div style="margin:10px 16px 0;display:flex;align-items:center;gap:10px"><button class="btn ghost sm" id="bugPick" type="button">${ic("image")} Приложить снимок экрана</button>
      <img id="bugPrev" alt="" hidden style="width:44px;height:44px;object-fit:cover;border-radius:var(--radius-sm);border:1px solid var(--border-subtle)">
      <input type="file" id="bugFile" accept="image/*" hidden></div>
    <p class="note" id="bugMsg" role="status" style="margin:8px 16px 0"></p>
    <div class="row2"><button class="btn ghost" data-close type="button">Отмена</button><button class="btn" id="bugGo" type="button">Отправить</button></div></div>`;
  document.body.append(bg);
  const $f = (s) => bg.querySelector(s), text = $f("#bugText"), file = $f("#bugFile"), msg = $f("#bugMsg");
  let shot = "";
  const close = () => { bg.remove(); document.removeEventListener("keydown", esc_); };
  const esc_ = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", esc_);
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) close(); });
  $f("#bugPick").onclick = () => file.click();
  file.onchange = async () => {
    const f = file.files?.[0]; if (!f) return;
    try { shot = await (await part("feedback")).shrink(f); const p = $f("#bugPrev"); p.src = shot; p.hidden = false; msg.textContent = ""; }
    catch (e) { shot = ""; msg.textContent = e.message; }
  };
  $f("#bugGo").onclick = () => busy($f("#bugGo"), "Отправляю…", async () => {
    const t = text.value.trim();
    if (!t) { msg.textContent = "Напишите в двух словах, что не так"; return text.focus(); }
    if (DEMO) {                                       // демо: никуда не уходит — показываем, как ответит команда
      close(); toast("В демо сообщение никуда не уходит", 3500);
      const now = new Date().toISOString().slice(0, 16).replace("T", " ");
      const ack = { id: "demo-ack-" + Date.now(), ts: now, at: Date.now() / 1000, from: "Команда", kind: "ack", text: "Приняли, сообщим, когда исправим." };
      if (w === "@1") window.demoApi?.teamMsgs?.push(ack);   // опрос демо отдаёт его же (js/demo.js)
      return teamAdd(ack);
    }
    try {
      const r = await api("/api/bug", { w, text: t, ctx, shot });
      close(); toast("Отправлено — команда ответит в этом чате", 3500);
      if (w === current) teamAdd(r.ack);
    } catch (e) { msg.textContent = e.message; }
  });
  setTimeout(() => text.focus(), 50);
}
