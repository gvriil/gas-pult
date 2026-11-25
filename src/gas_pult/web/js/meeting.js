// Протокол встречи (владелец 22.11: «уровня Plaud») — часть по требованию (#191): список протоколов, протокол с
// оглавлением (нажатие на главу — запись с этого места), «Что сделать» с кнопкой «→ в задачи», карточка-превью
// картинкой (SVG с сервера → PNG через canvas), ссылка на один протокол (вид по ссылке — publicView).
// Данные — /api/meetings, /api/meeting (владелец) и /api/mt (по ссылке: id протокола сервер берёт из ссылки).
// Рассылки здесь нет: письма участникам — черновиком в чате «Встречи» и только после «Да» (meetings.prompt).

const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
const day = (t) => { if (!t) return ""; const d = new Date(t * 1000); return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`; };
const mins = (s) => (s ? Math.max(1, Math.round(s / 60)) + " мин" : "");
const clock = (s) => { s = Math.max(0, Math.floor(s || 0)); const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, x = String(s % 60).padStart(2, "0"); return h ? `${h}:${String(m).padStart(2, "0")}:${x}` : `${m}:${x}`; };
const sub = (v) => [day(v.started), mins(v.dur), v.chapters?.length ? `глав: ${v.chapters.length}` : ""].filter(Boolean).join(" · ");
const KEY = (id) => "mt:tasks:" + id;
const added = (id) => { try { return JSON.parse(localStorage.getItem(KEY(id)) || "[]"); } catch (e) { return []; } };
const mark = (id, i) => { try { localStorage.setItem(KEY(id), JSON.stringify([...new Set([...added(id), i])])); } catch (e) { /* только удобство */ } };

// «Что сделать» уже в протоколе разделом — показываем один раз, списком с кнопками, в конце
const noActions = (t) => t.replace(/\n#{1,3}\s*Что сделать[^\n]*\n[\s\S]*?(?=\n#{1,3}\s|$)/i, "\n");
const noTitle = (t) => t.replace(/^\s*#\s[^\n]*\n/, "");      // тема — уже в шапке протокола

let PUB = false, CUR = null, AU = null;

// Список протоколов (владелец): новые сверху; нажатие — протокол
export async function open(id) {
  if (id) return show(id);
  let d; try { d = await api("/api/meetings"); } catch (e) { return toast("Протоколы: " + e.message, 4500); }
  const xs = d.meetings || [];
  sheet("Протоколы встреч", xs.length ? xs.map((x) => ({ label: x.gist || x.title, icon: x.ready ? "file" : "wait",
    sub: [sub(x), x.ready ? "" : "протокол ещё готовится"].filter(Boolean).join(" · "), run: () => show(x.id) }))
    : [{ info: true, icon: "mic", label: "Протоколов пока нет", sub: "в боте: «Протокол встречи» → запись или файл → «Готово»" }]);
}

async function show(id) {
  let v; try { v = await api("/api/meeting?id=" + encodeURIComponent(id)); } catch (e) { return toast("Протокол: " + e.message, 4500); }
  await mdLoad();                                    // текст протокола — разметкой (marked и DOMPurify ядра)
  document.querySelector(".mt-bg")?.remove();
  const bg = document.createElement("div"); bg.className = "sheet-bg mt-bg";
  bg.innerHTML = `<div class="sheet mt-sheet" role="dialog" aria-label="Протокол встречи"><h3>Протокол встречи</h3>${body(v)}<button class="cancel" data-close>Закрыть</button></div>`;
  document.body.append(bg);
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) { stop(); bg.remove(); } });
  wire(bg, v);
}

// Вид по ссылке на протокол: вся страница — только этот протокол (без пульта, без входа)
export async function publicView() {
  PUB = true;
  document.body.classList.add("mt-public-on");
  const page = document.createElement("main"); page.className = "mt-page"; page.setAttribute("aria-label", "Протокол встречи");
  page.innerHTML = `<div class="result wait">${ic("wait")}<span>Открываю протокол…</span></div>`;
  document.body.append(page);
  let v; try { v = await api("/api/mt"); await mdLoad(); }
  catch (e) { page.innerHTML = `<div class="mt-gone">${ic("lock")}<h2 class="serif">Ссылка не действует</h2><p>${esc(e.message)}</p></div>`; return; }
  document.getElementById("focusEnd")?.remove();
  document.title = v.title + " — протокол";
  page.innerHTML = `<div class="mt-wrap"><header class="mt-brand"><img src="brand/ladeya-mark.svg" alt="" width="29" height="24"><span>Протокол встречи</span>${v.exp ? `<small>ссылка действует до ${esc(day(v.exp))}</small>` : ""}</header>${body(v)}</div>`;
  wire(page, v);
}

function body(v) {
  CUR = v;
  const done = added(v.id);
  const text = v.md ? md(noTitle(v.actions?.length ? noActions(v.md) : v.md)) : v.transcript ? `<p class="note">Протокол ещё готовится — пока видна расшифровка.</p><pre class="mt-tr">${esc(v.transcript)}</pre>` : `<p class="note">Протокол ещё готовится.</p>`;
  return `<header class="mt-head"><h2 class="serif">${esc(v.title)}</h2><p class="mt-sub">${esc(sub(v))}</p>${v.gist && v.gist !== v.title ? `<p class="mt-gist">${esc(v.gist)}</p>` : ""}</header>
    ${PUB ? "" : `<div class="mt-tools"><button class="btn ghost" type="button" data-card>${ic("image", "s16")}Карточка</button><button class="btn ghost" type="button" data-share>${ic("qr", "s16")}Ссылка на протокол</button></div>`}
    ${v.audio ? `<section class="mt-player" aria-label="Запись"><button class="btn" type="button" data-listen>${ic("play", "s16")}<span>Слушать запись</span></button><audio controls preload="metadata" hidden></audio></section>` : ""}
    ${v.chapters?.length ? `<section class="mt-sec"><h3>Оглавление</h3><ol class="mt-ch">${v.chapters.map((c, i) => `<li><button type="button" data-ch="${i}"${v.audio ? "" : " disabled"}><time>${esc(clock(c.start))}</time><span>${esc(c.topic)}</span>${c.end ? `<small>${esc(mins(c.end - c.start))}</small>` : ""}</button></li>`).join("")}</ol>${v.audio ? "" : `<p class="note">Записи нет — только текст.</p>`}</section>` : ""}
    <section class="mt-sec mt-md md">${text}</section>
    ${v.actions?.length ? `<section class="mt-sec"><h3>Что сделать</h3><ul class="mt-act">${v.actions.map((a, i) => `<li><div><b>${esc(a.what)}</b><small>${esc([a.who && "Отвечает: " + a.who, a.due ? "Срок: " + new Date(a.due + "T12:00").toLocaleDateString("ru-RU", { day: "numeric", month: "long" }) : a.when ? "Срок: " + a.when : ""].filter(Boolean).join(" · "))}</small></div>${PUB ? "" : done.includes(i) ? `<span class="mt-added">${ic("check", "s16")}В задачах</span>` : `<button class="btn ghost" type="button" data-task="${i}" aria-label="В задачи: ${esc(a.what)}">→ в задачи</button>`}</li>`).join("")}</ul></section>` : ""}`;
}

function stop() { if (AU) { AU.pause(); URL.revokeObjectURL(AU.src); } AU = null; }

// Запись — целиком через api (заголовки входа и ссылки работают и в Mini App), потом обычный <audio>
async function load(root, v) {
  const a = root.querySelector(".mt-player audio"), b = root.querySelector("[data-listen]");
  if (a.src) return a;
  b.disabled = true; b.querySelector("span").textContent = "Загружаю запись…";
  try {
    const blob = await api(PUB ? "/api/mt/audio" : "/api/meeting/audio?id=" + encodeURIComponent(v.id));
    a.src = URL.createObjectURL(blob); AU = a;
  } catch (e) { b.disabled = false; b.querySelector("span").textContent = "Слушать запись"; toast("Запись: " + e.message, 4500); return null; }
  b.hidden = true; a.hidden = false;
  a.addEventListener("timeupdate", () => {
    const t = a.currentTime;
    root.querySelectorAll("[data-ch]").forEach((x) => { const c = v.chapters[+x.dataset.ch]; x.classList.toggle("on", t >= c.start && t < (c.end ?? Infinity)); });
  });
  return a;
}

function wire(root, v) {
  root.addEventListener("click", async (e) => {
    const t = e.target.closest("button"); if (!t) return;
    if (t.dataset.listen != null) { const a = await load(root, v); a?.play().catch(() => {}); }
    else if (t.dataset.ch != null) {
      const a = await load(root, v); if (!a) return;
      const go = () => { a.currentTime = v.chapters[+t.dataset.ch].start; a.play().catch(() => {}); };
      a.readyState >= 1 ? go() : a.addEventListener("loadedmetadata", go, { once: true });
    }
    else if (t.dataset.task != null) toTask(t, v, +t.dataset.task);
    else if (t.dataset.card != null) card(v);
    else if (t.dataset.share != null) shareLink(v);
  });
}

// «→ в задачи» — одним нажатием; в задаче — ссылка обратно на протокол (поле link)
async function toTask(btn, v, i) {
  const a = v.actions[i];
  btn.disabled = true;
  try {
    await api("/api/tasks/add", { title: a.what, kind: "other", status: "todo", next: a.who ? "Отвечает: " + a.who : "Сделать по протоколу «" + v.title + "»",
      ...(a.due ? { due: a.due } : {}), link: location.origin + location.pathname + "?meeting=" + encodeURIComponent(v.id) });
  } catch (e) { btn.disabled = false; return toast("Задача: " + e.message, 4500); }
  mark(v.id, i);
  btn.outerHTML = `<span class="mt-added">${ic("check", "s16")}В задачах</span>`;
  toast("Добавлено в задачи");
}

// Карточка-превью: SVG с сервера → картинка; «Сохранить» и «Поделиться» — PNG (canvas), без новых зависимостей
async function card(v) {
  let url; try { url = URL.createObjectURL(await api("/api/meeting/card?id=" + encodeURIComponent(v.id))); } catch (e) { return toast("Карточка: " + e.message, 4500); }
  const bg = document.createElement("div"); bg.className = "sheet-bg mt-card-bg";
  bg.innerHTML = `<div class="sheet" role="dialog" aria-label="Карточка встречи"><h3>Карточка для пересылки</h3><img class="mt-card" src="${url}" alt="Карточка: ${esc(v.gist || v.title)}">
    <div class="mt-tools"><button class="btn" type="button" data-png>${ic("down", "s16")}Сохранить картинку</button>${navigator.canShare ? `<button class="btn ghost" type="button" data-send>${ic("share", "s16")}Поделиться</button>` : ""}</div>
    <p class="note">Картинку отправляете вы сами — пульт никому ничего не рассылает.</p><button class="cancel" data-close>Закрыть</button></div>`;
  document.body.append(bg);
  const png = () => new Promise((ok, no) => { const im = new Image(); im.onload = () => { const c = document.createElement("canvas"); c.width = 1200; c.height = 630; c.getContext("2d").drawImage(im, 0, 0, 1200, 630); c.toBlob((b) => b ? ok(b) : no(new Error("не получилось")), "image/png"); }; im.onerror = () => no(new Error("картинка не загрузилась")); im.src = url; });
  const name = "встреча-" + v.id + ".png";
  bg.addEventListener("click", async (e) => {
    if (e.target === bg || e.target.closest("[data-close]")) { bg.remove(); URL.revokeObjectURL(url); return; }
    try {
      if (e.target.closest("[data-png]")) { const b = await png(), a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 4000); }
      if (e.target.closest("[data-send]")) { const f = new File([await png()], name, { type: "image/png" }); if (navigator.canShare({ files: [f] })) await navigator.share({ files: [f], title: v.title }); else toast("Это устройство не умеет делиться картинкой — сохраните её"); }
    } catch (er) { if (er.name !== "AbortError") toast(er.message, 4500); }
  });
}

// Ссылка на протокол: только этот протокол, 30 дней, отозвать — «Настройки» → «Фокус-ссылки»
async function shareLink(v) {
  let d; try { d = await api("/api/meeting/share", { id: v.id, base: location.origin }); } catch (e) { return toast("Ссылка: " + e.message, 5000); }
  const till = new Date(d.exp * 1000).toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
  sheet("Ссылка на протокол", [
    { info: true, icon: "lock", label: "По ссылке — только этот протокол", sub: `запись, оглавление, текст и «Что сделать»; до ${till}; отозвать — «Настройки» → «Фокус-ссылки»` },
    { label: "Скопировать ссылку", icon: "copy", run: () => copyText(d.url, "Ссылка скопирована") },
    ...(navigator.share ? [{ label: "Поделиться…", icon: "share", sub: "кому отправить — выбираете вы", run: () => navigator.share({ title: v.title, url: d.url }).catch(() => {}) }] : []),
  ]);
}

document.head.insertAdjacentHTML("beforeend", `<style>
  .mt-sheet { max-height: 94%; } .mt-sheet > .mt-head, .mt-sheet > section, .mt-sheet > .mt-tools { margin-left: 16px; margin-right: 16px; }
  .mt-head h2 { margin: 4px 0 2px; font-size: calc(22px * var(--fz, 1)); color: var(--text-primary); } .mt-sub { margin: 0; color: var(--text-secondary); font-size: calc(13px * var(--fz, 1)); }
  .mt-gist { margin: 10px 0 0; padding: 10px 12px; border-left: 3px solid var(--accent-primary); background: var(--accent-soft); color: var(--text-primary); border-radius: 0 8px 8px 0; }
  .mt-tools { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; } .mt-tools .btn { min-height: 44px; width: auto; flex: 1 1 0; margin: 0; justify-content: center; gap: 8px; padding: 8px 12px; font-size: calc(15px * var(--fz, 1)); }
  .sheet .mt-tools button.btn, .sheet .mt-act button.btn, .sheet .mt-player button.btn { width: auto; border: 1px solid var(--border-subtle); border-radius: 10px; }
  .mt-bg .btn:not(.ghost), .mt-card-bg .btn:not(.ghost), .mt-page .btn:not(.ghost) { background: var(--accent-primary); color: var(--on-accent); border-color: var(--accent-primary); }
  .mt-player { margin: 12px 0; } .mt-player audio { width: 100%; } .mt-player .btn { min-height: 44px; }
  .mt-sec { margin: 16px 0; } .mt-sec h3 { margin: 0 0 8px; font-size: calc(15px * var(--fz, 1)); color: var(--text-primary); }
  .mt-ch { list-style: none; margin: 0; padding: 0; border: 1px solid var(--border-subtle); border-radius: 10px; overflow: hidden; }
  .mt-ch li + li { border-top: 1px solid var(--border-subtle); }
  .mt-ch button { all: unset; box-sizing: border-box; width: 100%; display: flex; gap: 12px; align-items: baseline; padding: 10px 12px; min-height: 44px; cursor: pointer; color: var(--text-primary); }
  .mt-ch button[disabled] { cursor: default; } .mt-ch time { font-variant-numeric: tabular-nums; color: var(--accent-primary); min-width: 3.2em; font-weight: 600; }
  .mt-ch span { flex: 1; min-width: 0; } .mt-ch small { color: var(--text-muted); white-space: nowrap; }
  .mt-ch button.on { background: var(--accent-soft); } .mt-ch button:focus-visible { outline: 2px solid var(--border-focus); outline-offset: -2px; }
  @media (hover: hover) { .mt-ch button:not([disabled]):hover { background: var(--bg-subtle); } }
  .mt-md { color: var(--text-primary); overflow-wrap: anywhere; } .mt-tr { white-space: pre-wrap; font-size: calc(13px * var(--fz, 1)); color: var(--text-secondary); }
  .mt-act { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
  .mt-act li { display: flex; flex-wrap: wrap; gap: 8px 10px; align-items: center; justify-content: space-between; padding: 10px 12px; border: 1px solid var(--border-subtle); border-radius: 10px; background: var(--bg-surface); }
  .mt-act li > div { min-width: 0; flex: 1 1 220px; display: grid; gap: 2px; } .mt-act b { color: var(--text-primary); font-weight: 600; } .mt-act small { color: var(--text-secondary); }
  .mt-act .btn { min-height: 40px; white-space: nowrap; flex: 0 0 auto; width: auto; margin: 0 0 0 auto; padding: 0 14px; font-size: calc(14px * var(--fz, 1)); } .mt-added { display: inline-flex; gap: 4px; align-items: center; color: var(--status-success, var(--accent-primary)); white-space: nowrap; flex: 0 0 auto; margin-left: auto; }
  .mt-card { display: block; width: calc(100% - 32px); margin: 8px 16px; border: 1px solid var(--border-subtle); border-radius: 10px; }
  .mt-card-bg .mt-tools, .mt-card-bg .note { margin-left: 16px; margin-right: 16px; }
  body.mt-public-on { overflow: hidden; } .mt-page { position: fixed; inset: 0; z-index: 60; overflow: auto; background: var(--bg-canvas); color: var(--text-primary); }
  .mt-wrap { max-width: 760px; margin: 0 auto; padding: 16px 16px 48px; }
  .mt-brand { display: flex; gap: 10px; align-items: center; color: var(--text-secondary); font-weight: 600; flex-wrap: wrap; } .mt-brand img { height: 32px; width: auto; }
  .mt-brand small { margin-left: auto; font-weight: 400; color: var(--text-muted); }
  .mt-gone { text-align: center; padding: 64px 16px; color: var(--text-secondary); } .mt-page > .result { margin: 32px 16px; }
  @media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) .mt-brand img { filter: invert(1); } }
  :root[data-theme="dark"] .mt-brand img { filter: invert(1); }
</style>`);
