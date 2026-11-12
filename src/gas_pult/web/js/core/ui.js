// ---------- иконки (линейные SVG, цвет — currentColor) ----------
const P = {
  back: '<path d="M15 18l-6-6 6-6"/>', search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.6-3.6"/>', swap: '<path d="M7 4v16M3 8l4-4 4 4M17 20V4M13 16l4 4 4-4"/>',
  settings: '<path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h11M19 17h1"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="17" r="2"/>',
  menu: '<rect x="4" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.3a2.5 2.5 0 0 1 4.8.9c0 1.7-2.4 2.1-2.4 3.6M12 17.2v.1"/>',
  plus: '<path d="M12 5v14M5 12h14"/>', x: '<path d="M6 6l12 12M18 6L6 18"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>',
  send: '<path d="M12 19V5M5.5 11.5L12 5l6.5 6.5"/>',
  play: '<path d="M8 5.5v13l10.5-6.5z"/>', stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/>', pause: '<path d="M9 5.5v13M15 5.5v13"/>',
  chev: '<path d="M7 10l5 5 5-5"/>',
  trash: '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13M10 11v5.5M14 11v5.5"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
  bulb: '<path d="M9.5 18h5M10.5 21h3"/><path d="M12 3a6 6 0 0 0-3.4 10.9c.6.4.9 1 .9 1.7V16h5v-.4c0-.7.3-1.3.9-1.7A6 6 0 0 0 12 3z"/>',
  vol: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M16 9.5a3.5 3.5 0 0 1 0 5"/>',
  volfull: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M16 9.5a3.5 3.5 0 0 1 0 5M18.5 7a7 7 0 0 1 0 10"/>',
  share: '<circle cx="18" cy="5.5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="18.5" r="2.5"/><path d="M8.2 10.8l7.6-4.1M8.2 13.2l7.6 4.1"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5.5 15V6a2 2 0 0 1 2-2H15"/>',
  bolt: '<path d="M13 3L5 13.5h6L10 21l8-10.5h-6z"/>', chip: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9.5 2.5v3.5M14.5 2.5v3.5M9.5 18v3.5M14.5 18v3.5M2.5 9.5H6M2.5 14.5H6M18 9.5h3.5M18 14.5h3.5"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>', refresh: '<path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20 4.5v4.5h-4.5"/>',
  top: '<path d="M12 20V9M6.5 14.5L12 9l5.5 5.5M5 4.5h14"/>', power: '<path d="M12 3.5v8"/><path d="M6.6 6.6a7.5 7.5 0 1 0 10.8 0"/>',
  camera: '<path d="M4 8.5h3.2L9 6h6l1.8 2.5H20V19H4z"/><circle cx="12" cy="13.2" r="3.3"/>',
  image: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><circle cx="9" cy="10" r="1.8"/><path d="M20.5 15.5l-5-5-9 9"/>',
  file: '<path d="M7 3.5h7l4.5 4.5v12.5H7z"/><path d="M14 3.5V8h4.5"/>',
  key: '<circle cx="8" cy="15.5" r="3.5"/><path d="M10.5 13l8.5-8.5M15.5 8l2.5 2.5M17.5 6l2 2"/>',
  term: '<rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M7 9.5l3 2.5-3 2.5M12.5 15H17"/>',
  chat: '<path d="M4.5 5.5h15v10.5H10l-4.5 3.5v-3.5h-1z"/>', play: '<path d="M8 5.5v13l10.5-6.5z"/>',
  more: '<circle cx="5.5" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="18.5" cy="12" r="1.3" fill="currentColor"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
  ext: '<path d="M14 4h6v6M20 4l-9 9M18.5 14v5.5h-14v-14H10"/>', warn: '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17.2v.3"/>',
  lock: '<rect x="5" y="11" width="14" height="9.5" rx="2"/><path d="M8.5 11V8a3.5 3.5 0 0 1 7 0v3"/>', monitor: '<rect x="3" y="4.5" width="18" height="12" rx="2"/><path d="M8.5 20h7M12 16.5V20"/>',
  wait: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>', place: '<path d="M12 21s6.5-6 6.5-11a6.5 6.5 0 0 0-13 0c0 5 6.5 11 6.5 11z"/><circle cx="12" cy="10" r="2.3"/>',
  pin: '<path d="M9 3.5h6M10 3.5v5.5l-3.5 4.5h11L14 9V3.5M12 13.5V21"/>',
  attach: '<path d="M19.5 11.5l-7.8 7.8a5 5 0 0 1-7-7l8.3-8.3a3.3 3.3 0 0 1 4.7 4.7l-8.3 8.3a1.7 1.7 0 0 1-2.4-2.4l7.6-7.6"/>',
  newsess: '<path d="M12 6v12M6 12h12"/>', burger: '<path d="M4 7h16M4 12h16M4 17h16"/>', compose: '<path d="M11 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5"/><path d="M17.6 3.6a2 2 0 0 1 2.8 2.8L12 14.8 8.5 15.5l.7-3.5z"/>', grid: '<path d="M4 6h16M4 12h16M4 18h10"/>',
  mail: '<rect x="3.5" y="5.5" width="17" height="13" rx="2"/><path d="M4 7l8 6 8-6"/>',
  cal: '<rect x="4" y="5.5" width="16" height="14.5" rx="2"/><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4"/>',
  folder: '<path d="M3.5 6.5a1.5 1.5 0 0 1 1.5-1.5h4.5l2 2.5H19a1.5 1.5 0 0 1 1.5 1.5v8.5A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z"/>',
  hash: '<path d="M9.5 4l-2 16M16.5 4l-2 16M4.5 9h16M3.5 15h16"/>', home: '<path d="M4 11l8-6.5 8 6.5M6 9.5V20h12V9.5"/><path d="M10 20v-5h4v5"/>',
  book: '<path d="M5 4.5h11a2 2 0 0 1 2 2v13H7a2 2 0 0 1-2-2z"/><path d="M5 17.5a2 2 0 0 1 2-2h11"/>', pen: '<path d="M4 20l4-1 11-11-3-3L5 16z"/><path d="M14 7l3 3"/>',
  code: '<path d="M8.5 7.5L4 12l4.5 4.5M15.5 7.5L20 12l-4.5 4.5"/>', server: '<rect x="4" y="4.5" width="16" height="6" rx="1.5"/><rect x="4" y="13.5" width="16" height="6" rx="1.5"/><path d="M7.5 7.5h.5M7.5 16.5h.5"/>',
  down: '<path d="M12 5v14M5.5 12.5L12 19l6.5-6.5"/>', up: '<path d="M12 19V5M5.5 11.5L12 5l6.5 6.5"/>', chevron: '<path d="M9 6l6 6-6 6"/>',
  spark: '<path d="M12 2.5c.6 4.9 4.6 8.9 9.5 9.5-4.9.6-8.9 4.6-9.5 9.5-.6-4.9-4.6-8.9-9.5-9.5 4.9-.6 8.9-4.6 9.5-9.5z" fill="url(#gsp)" stroke="none"/><defs><linearGradient id="gsp" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4285F4"/><stop offset=".5" stop-color="#9B72CB"/><stop offset="1" stop-color="#D96570"/></linearGradient></defs>',
  bell: '<path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2H4.5z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
  sidebar: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M9.5 4.5v15"/>',
  sideopen: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M9.5 4.5v15M13.5 10l2 2-2 2"/>',
  tasks: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 12.5l2.5 2.5L16 9.5"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.4 2.5 3.5 5.3 3.5 8.5s-1.1 6-3.5 8.5c-2.4-2.5-3.5-5.3-3.5-8.5s1.1-6 3.5-8.5z"/>',
  phone: '<rect x="7" y="3" width="10" height="18" rx="2"/><path d="M11 17.5h2"/>',
  qr: '<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><path d="M14 14h2v2h-2zM18 18h2v2h-2zM14 18h2M18 14h2"/>',
  puzzle: '<path d="M12 3.2l7.8 4.4v8.8L12 20.8l-7.8-4.4V7.6z"/><path d="M4.4 7.7L12 12l7.6-4.3M12 12v8.6"/>',
  coin: '<circle cx="12" cy="12" r="8.5"/><path d="M14.6 9.3c-.5-.8-1.4-1.3-2.6-1.3-1.5 0-2.6.8-2.6 2s1.1 1.6 2.6 2 2.6.8 2.6 2-1.1 2-2.6 2c-1.2 0-2.1-.5-2.6-1.3M12 6.5V8M12 16v1.5"/>',
  pause: '<path d="M9 6.5v11M15 6.5v11"/>',
  flask: '<path d="M9.5 3.5h5M10.5 3.5v6L5 18.5a1.5 1.5 0 0 0 1.3 2.2h11.4a1.5 1.5 0 0 0 1.3-2.2L13.5 9.5v-6"/><path d="M7.5 15h9"/>',
  rew15: '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 3.8v3.5H8"/><text x="12.3" y="15.2" font-size="7.6" font-weight="700" text-anchor="middle" fill="currentColor" stroke="none">15</text>',
  fwd15: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 3.8v3.5H16"/><text x="11.7" y="15.2" font-size="7.6" font-weight="700" text-anchor="middle" fill="currentColor" stroke="none">15</text>',
};
const ic = (n, cls = "") => `<svg class="i ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[n] || ""}</svg>`;
function paintIcons() {
  $("hintBtn").innerHTML = ic("bulb"); $("backBtn").innerHTML = ic("back"); $("switchBtn").innerHTML = ic("swap"); $("settingsBtn").innerHTML = ic("settings");
  $("menuBtn").innerHTML = ic("menu"); $("plus").innerHTML = ic("attach"); $("mic").innerHTML = ic("mic"); $("send").innerHTML = ic("send");
  $("netIcon").innerHTML = ic("warn"); $("updateBar").insertAdjacentHTML("afterbegin", ic("refresh", "s16")); $("ptr").innerHTML = ic("refresh"); $("netRetry").innerHTML = ic("refresh", "s16") + "Переподключить";
  $("pickIcon").innerHTML = ic("chat"); $("toBottom").innerHTML = ic("down"); $("helpBtn").innerHTML = ic("help") + "<span>Подсказать</span>";
  $("newBtn").innerHTML = ic("newsess") + "Новая сессия";
  $("navBtn").innerHTML = ic("burger"); $("composeBtn").innerHTML = ic("compose"); $("navSearchBtn").innerHTML = ic("search");
  $("navMoreBtn").innerHTML = ic("more"); $("navCloseBtn").innerHTML = ic("x"); $("navNew").innerHTML = ic("compose") + "<span>Новый чат</span>";
  document.querySelector('[data-tab="chat"]').innerHTML = ic("chat", "s16") + "Переписка";
  document.querySelector('[data-tab="screen"]').innerHTML = ic("term", "s16") + "Экран";
  // Две строки по четыре; «Завершить» — в верхнем левом углу, дальше всего от большого пальца, и с подтверждением.
  $("menu").innerHTML = `<button data-act="close" class="danger" data-owner>${ic("power")}Завершить</button>` + [["say", "vol", "Прослушать"],
    ["commands", "bolt", "Команды"], ["models", "chip", "Модель"], ["active", "place", "Активная"], ["refresh", "refresh", "Обновить"], ["switch", "swap", "Сессии"]]
    .map(([a, i, t]) => `<button data-act="${a}">${ic(i)}${t}</button>`).join("")
    + `<button data-act="sos" class="tester-only">${ic("bell")}Позвать на помощь</button>`      // тестировщик пространства
    + `<button data-act="mcp" class="focus-only">${ic("puzzle")}Интеграции</button>`            // фокус: интеграции сессии
    + `<button data-act="repos" class="focus-only">${ic("folder")}Репозитории</button>`;        // фокус: репозитории сессии (задача 43)
}

// ---------- тема ----------
function applyTheme() {
  const mode = params.get("theme") || store("theme") || "auto";
  const dark = mode === "dark" || (mode === "auto" && (tg?.colorScheme ? tg.colorScheme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches));
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  const bg = getComputedStyle(document.documentElement).getPropertyValue("--bg-canvas").trim();
  try { tg?.setHeaderColor?.(bg); tg?.setBackgroundColor?.(bg); tg?.setBottomBarColor?.(bg); } catch (e) {}
}
// Копировать: navigator.clipboard, а где его нет или он отказал (старый iOS, WebView Telegram) — выделение текста
// в скрытом поле и execCommand("copy"); не вышло и так — шторка с выделенным текстом, скопировать рукой.
// quiet — без всплывашки: кнопка сама покажет «Скопировано» (copyBtn). → true, если текст в буфере.
async function copyText(text, what = "Скопировано", quiet = false) {
  const done = () => { if (!quiet) toast(what); return true; };
  try { await navigator.clipboard.writeText(text); return done(); } catch (e) {}
  const t = document.createElement("textarea");
  t.value = text; t.readOnly = true; t.style.cssText = "position:fixed;top:0;left:0;width:1px;height:1px;opacity:0";
  document.body.append(t); t.focus(); t.select(); t.setSelectionRange(0, text.length);
  let ok = false; try { ok = document.execCommand("copy"); } catch (e) {}
  t.remove();
  if (ok) return done();
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.copy");
  bg.innerHTML = `<div class="sheet" role="dialog"><h3>Скопируйте вручную</h3><div class="field"><textarea rows="8" readonly></textarea></div>
    <div class="row2"><button class="btn">Готово</button></div></div>`;
  const ta = bg.querySelector("textarea"); ta.value = text;
  bg.onclick = (e) => { if (e.target === bg || e.target.closest("button")) bg.remove(); };
  document.body.append(bg); ta.focus(); ta.setSelectionRange(0, text.length);
  return false;
}
// Кнопки «Копировать» в переписке (полный и простой режим, переписка завершённого чата). Разметка — строкой, чтобы
// morph сравнивал её как есть; блоки кода получают кнопку дообработкой новых узлов (codeCopy) — как ссылки (linkify).
const copyLbl = () => LT("link.copy", "Копировать");
const mCopyBtn = () => `<button type="button" class="mcopy" data-mcopy="1" aria-label="${esc(LT("copy.msg", "Копировать сообщение"))}" title="${esc(copyLbl())}">${ic("copy", "s16")}</button>`;
const cCopyBtn = () => `<button type="button" class="ccopy" data-cpcode="1" aria-label="${esc(LT("copy.code", "Копировать код"))}" title="${esc(LT("copy.code", "Копировать код"))}">${ic("copy", "s16")}</button>`;
function codeCopy(root) {                            // pre в разметке ответа → обёртка с кнопкой справа сверху
  root.querySelectorAll(".md pre").forEach((pre) => {
    if (pre.closest(".log, .codebox")) return;
    const w = document.createElement("div"); w.className = "codebox";
    pre.replaceWith(w); w.append(pre); w.insertAdjacentHTML("beforeend", cCopyBtn());
  });
}
function copiedFlash(b) {                            // «Скопировано» на 1,5 с: значок — галочка, у кнопки с подписью — и текст
  clearTimeout(b.__ct); if (b.__html == null) b.__html = b.innerHTML;
  b.innerHTML = ic("check", "s16") + `<span>${esc(LT("copy.done", "Скопировано"))}</span>`; b.classList.add("done");
  b.__ct = setTimeout(() => { b.innerHTML = b.__html; b.__html = null; b.classList.remove("done"); }, 1500);
}
function msgText(el) {                               // исходный текст сообщения (markdown как есть, без разметки)
  const k = el.dataset.key || "", src = el.closest("#sFeed") ? SIM.hist : el.closest(".chatv-list")?.__items || hist;
  if (k.startsWith("p:")) return pending.find((p) => "p:" + p.id === k)?.text;
  if (k.startsWith("sp:")) return SIM.pending[+k.slice(3)]?.text;
  if (el.dataset.n != null) return src[+el.dataset.n]?.text;
  return src.find((m) => m.i === +el.dataset.i)?.text ?? el.querySelector(".bubble")?.innerText;
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-mcopy], [data-cpcode]"); if (!b) return;
  e.preventDefault();                                // кнопка в заголовке свёрнутого блока — не раскрывать его
  let text = "";
  if (b.dataset.mcopy) { const m = b.closest(".msg"); text = (m && msgText(m)) || ""; }
  else text = (b.closest(".codebox, .log")?.querySelector("pre")?.textContent || "").replace(/\n$/, "");
  if (!text) return;
  if (await copyText(text, LT("copy.done", "Скопировано"), true)) { copiedFlash(b); haptic("notificationOccurred", "success"); }
});
// link:start — ссылки в переписке (задача 33). Только http(s); элементы — через DOM (textContent/href), сырого
// HTML нет. Хвост «.», «,», «!», «?»… и лишняя «)» — не адрес. Адрес без схемы (pult.example.su/x, claude.ai/…) —
// домен с известной зоной, ссылка на https://; file.py, 1.2.3, v2.0 и почта — не адреса (зоны py/md/sh/rs нет в списке,
// перед доменом не «@», «.», «/»). Ссылки — и внутри `кода` и блоков кода: текст кода тот же (textContent не меняется),
// «Копировать» блока даёт чистый текст. Регулярка без просмотра назад — старый Safari её не знает; часть домена —
// до 63 знаков (как в DNS): длинное «слово» без точек не разбирается квадратично.
const LINK_TLD = "ru|su|com|net|org|io|ai|dev|app|me|co|рф|info|biz|xyz|tech|pro|site|online|cloud|page|tv|eu|de|uk|us|kz|by|ua|uz|gg|fm|club|shop|store|space|link|news|blog|team|tools|chat";
const LINK_RE = new RegExp("\\bhttps?:\\/\\/[^\\s<>\"'`]+|(?:[\\p{L}\\p{N}][\\p{L}\\p{N}-]{0,62}\\.)+(?:" + LINK_TLD
  + ")(?![\\p{L}\\p{N}_-]|\\.[\\p{L}\\p{N}])(?::\\d{1,5})?(?:[/?#][^\\s<>\"'`]*)?", "giu");
const LINK_BEFORE = /[\p{L}\p{N}_@.\/\\-]/u;          // «a@mail.ru», «x/site.com», «a.b.site.com» с середины — не адрес
function safeUrl(u) {                                // адрес для href или "" — javascript:, data:, mailto: и прочее не проходят
  try { const x = new URL(String(u)); return (x.protocol === "http:" || x.protocol === "https:") && x.hostname ? x.href : ""; }
  catch (e) { return ""; }
}
function trimUrl(u) {
  for (;;) {
    const c = u.slice(-1), n = (ch) => u.split(ch).length - 1;
    if (/[.,;:!?…»”’]/.test(c)) u = u.slice(0, -1);
    else if ((c === ")" && n(")") > n("(")) || (c === "]" && n("]") > n("[")) || (c === "}" && n("}") > n("{"))) u = u.slice(0, -1);
    else return u;
  }
}
// code — текст из кода: там «self.app», «req.me» — не адреса; адрес без схемы — только с путём, портом или поддоменом
function linkParts(text, code) {                     // "см. https://a.b/c." → ["см. ", { url: "https://a.b/c", href }, "."]
  const s = String(text ?? ""), out = []; let last = 0;
  for (const m of s.matchAll(LINK_RE)) {
    const bare = !/^https?:/i.test(m[0]);
    if (bare && m.index && LINK_BEFORE.test(s[m.index - 1])) continue;
    const u = trimUrl(m[0]), href = safeUrl(bare ? "https://" + u : u);
    if (bare && code && !/[/:]|\..*\./.test(u)) continue;
    if (!href) continue;
    if (m.index > last) out.push(s.slice(last, m.index));
    out.push({ url: u, href }); last = m.index + u.length;
  }
  if (last < s.length) out.push(s.slice(last));
  return out;
}
function linkEl(a, href) { a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer"; a.className = "clink"; return a; }
function linkify(root) {
  root.querySelectorAll("a").forEach((a) => {         // ссылки из markdown: http(s) — наши, остальное — простой текст
    const href = a.closest("pre, code") ? "" : safeUrl(a.getAttribute("href") || "");
    if (href) linkEl(a, href); else a.replaceWith(...a.childNodes);
  });
  const skip = (n) => n.parentElement?.closest("a, summary, button, textarea");   // код и логи — тоже со ссылками
  const nodes = [], walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (walk.nextNode()) if (!skip(walk.currentNode) && walk.currentNode.data.includes(".")) nodes.push(walk.currentNode);
  for (const t of nodes) {
    const parts = linkParts(t.data, !!t.parentElement?.closest("pre, code")); if (!parts.some((p) => typeof p !== "string")) continue;
    const frag = document.createDocumentFragment();
    for (const p of parts) {
      if (typeof p === "string") { frag.append(document.createTextNode(p)); continue; }
      const a = linkEl(document.createElement("a"), p.href); a.textContent = p.url; frag.append(a);
    }
    t.replaceWith(frag);
  }
  return root;
}
// link:end
const LT = (k, ru) => (DICT[k] ? T(k) : ru);         // строки ссылок — из словаря (ru/en), пока он грузится — по-русски
function openLink(href) {                             // в Telegram — его методом (браузер телефона); иначе false — обычный переход
  if (tg?.initData && typeof tg.openLink === "function") { tg.openLink(href); return true; }
  return false;
}
async function shareLink(href) {
  if (navigator.share) {
    try { await navigator.share({ url: href }); return; } catch (e) { if (e?.name === "AbortError") return; }
  }
  copyText(href, LT("link.share.copied", "Поделиться отсюда нельзя — ссылка скопирована"));
}
let linkMenuAt = 0;
function linkMenu(a) {
  if (Date.now() - linkMenuAt < 800) return;           // долгое нажатие и contextmenu одного касания — одно меню
  linkMenuAt = Date.now(); haptic("impactOccurred", "medium");
  const href = a.href;
  helpSheet("sheet.link");
  sheet(LT("link.title", "Ссылка"), [
    { label: LT("link.open", "Открыть"), icon: "ext", run: () => openLink(href) || window.open(href, "_blank", "noopener,noreferrer") },
    { label: LT("link.copy", "Копировать"), sub: href, icon: "copy", run: () => copyText(href, LT("link.copied", "Ссылка скопирована")) },
    { label: LT("link.share", "Поделиться"), icon: "share", run: () => shareLink(href) },
  ], LT("link.close", "Закрыть"));
  [...document.querySelectorAll(".sheet-bg")].pop()?.querySelector("button[data-i='1'] small")?.classList.add("url");
}
let linkHold = null, linkHeld = false, linkTouch = false;
document.addEventListener("pointerdown", (e) => {
  linkHeld = false; linkTouch = e.pointerType !== "mouse";
  const a = e.target.closest?.("a.clink"); if (!a || e.button > 0) return;
  linkHold = { x: e.clientX, y: e.clientY, t: setTimeout(() => { linkHold = null; linkHeld = true; linkMenu(a); }, 500) };
});
const linkUnhold = () => { if (linkHold) clearTimeout(linkHold.t); linkHold = null; };
document.addEventListener("pointerup", linkUnhold); document.addEventListener("pointercancel", linkUnhold);
document.addEventListener("pointermove", (e) => { if (linkHold && Math.hypot(e.clientX - linkHold.x, e.clientY - linkHold.y) > 10) linkUnhold(); });
document.addEventListener("contextmenu", (e) => {     // долгое нажатие пальцем (Android) — наше меню; правая кнопка мыши — меню браузера
  const a = e.target.closest?.("a.clink"); if (!a || !linkTouch) return;
  e.preventDefault(); linkUnhold(); linkHeld = true; linkMenu(a);
});
document.addEventListener("click", (e) => {
  const a = e.target.closest?.("a.clink"); if (!a) return;
  if (linkHeld) { linkHeld = false; e.preventDefault(); return; }   // долгое нажатие уже открыло меню
  if (openLink(a.href)) e.preventDefault();
});
// Время в журналах — UTC «ГГГГ-ММ-ДД ЧЧ:ММ» (как в транскрипте Claude Code). Показываем в часовом поясе зрителя
// (телефона или компьютера) — как строка статуса и как в ChatGPT/Claude: сегодня — «ЧЧ:ММ», вчера — «вчера ЧЧ:ММ»,
// раньше — «ДД.ММ ЧЧ:ММ». Раньше было время сервера: у сообщения «16:47», а у статуса рядом «18:47» — путало.
const localTs = (t) => {
  const d = new Date(String(t).replace(" ", "T") + ":00Z"); if (isNaN(d)) return t;
  const hm = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  const day = (x) => x.toLocaleDateString("sv-SE"), now = new Date(), y = new Date(now - 864e5);
  if (day(d) === day(now)) return hm;
  if (day(d) === day(y)) return "вчера " + hm;
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", ...(d.getFullYear() !== now.getFullYear() ? { year: "numeric" } : {}) }) + " " + hm;
};
function toast(text, ms = 2600) {
  document.querySelectorAll(".toast").forEach((t) => t.remove());
  const t = document.createElement("div"); t.className = "toast"; t.textContent = text;
  notice(t); setTimeout(() => t.remove(), ms);
}
async function busy(btn, text, fn) {              // кнопка показывает, что работает, и не нажимается дважды
  const old = btn.innerHTML; btn.disabled = true; btn.textContent = text;
  try { return await fn(); } finally { if (btn.isConnected) { btn.disabled = false; btn.innerHTML = old; } }
}
// Шторка, открытая пунктом другой шторки (Настройки → Люди → человек, папка → модель → усилия), — с «‹ Назад» к той,
// из которой пришли. Нажатие вне шторок — уже новый путь: отметку сбрасываем.
let sheetFrom = null;
document.addEventListener("pointerdown", (e) => { if (!e.target.closest(".sheet-bg")) sheetFrom = null; }, true);
function sheet(title, items, closeLabel = "Закрыть") {                     // [{label, sub, icon | dot | vis, run, hold, danger, on, info} | {head}]; hold — долгое нажатие
  const bg = document.createElement("div"); bg.className = "sheet-bg";
  const help = helpNext; helpNext = ""; if (help) bg.dataset.help = help;    // экран помощника: helpSheet("…") перед sheet()
  const parent = sheetFrom && Date.now() - sheetFrom.t < 15000 ? sheetFrom : null; sheetFrom = null;
  bg.innerHTML = `<div class="sheet" role="dialog">${parent ? `<button class="sback" data-back="1">${ic("back", "s16")}Назад</button>` : ""}<h3>${esc(title)}</h3>${items.map((it, i) => it.head ? `<h3 class="sub">${esc(it.head)}</h3>` :
    `<button data-i="${i}" class="${it.danger ? "danger" : ""} ${it.on ? "on" : ""} ${it.info ? "info" : ""}">${it.vis ? `<span class="vis">${it.vis}</span>` : it.dot ? `<i class="sdot ${it.dot}"></i>` : it.icon ? ic(it.icon) : ""}<span>${esc(clean(it.label))}${it.sub ? `<small>${esc(it.sub)}</small>` : ""}</span>${it.on ? ic("check") : ""}</button>`).join("")}
    <button class="cancel" data-close>${esc(closeLabel)}</button></div>`;
  let hold = null, held = false;
  bg.addEventListener("pointerdown", (e) => {
    const b = e.target.closest("button[data-i]"), it = b && items[+b.dataset.i];
    if (!it?.hold) return;
    hold = { x: e.clientX, y: e.clientY, t: setTimeout(() => { held = true; haptic("impactOccurred", "medium"); bg.remove(); it.hold(); }, 500) };
  });
  const unhold = () => { if (hold) clearTimeout(hold.t); hold = null; };
  bg.addEventListener("pointerup", unhold); bg.addEventListener("pointercancel", unhold);
  bg.addEventListener("pointermove", (e) => { if (hold && Math.hypot(e.clientX - hold.x, e.clientY - hold.y) > 10) unhold(); });
  bg.addEventListener("contextmenu", (e) => e.preventDefault());
  bg.addEventListener("click", (e) => {
    if (held) { held = false; return; }               // долгое нажатие уже открыло своё меню
    const b = e.target.closest("button");
    if (b?.dataset.i && items[+b.dataset.i].info) return;     // строка-пояснение: шторка остаётся
    if (e.target === bg || b) bg.remove();
    if (b?.dataset.back) return parent.open();
    if (b && b.dataset.i) { sheetFrom = { t: Date.now(), open: () => { sheetFrom = parent && { ...parent, t: Date.now() }; helpNext = help; sheet(title, items, closeLabel); } }; items[+b.dataset.i].run(); }
  });
  document.body.append(bg);
}
// В Telegram — его окно подтверждения; в браузере скрипт Telegram тоже загружен, но showConfirm там бросает
// WebAppMethodUnsupported — поэтому смотрим, открыта ли панель из Telegram на самом деле (initData).
function confirmDanger(text, go) {
  if (tg?.initData && tg.showConfirm) {
    try { return tg.showConfirm(text, (ok) => ok && go()); } catch (e) {}
  }
  if (confirm(text)) go();
}
