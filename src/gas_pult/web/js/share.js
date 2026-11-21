// «Поделиться» в Гаврилу — часть по требованию (#191). Владелец 21.11: «Хочу поделиться фото, ссылкой, файлом —
// Гаврила должен быть в списке «Поделиться»». Сервер: share.py.
// - Android: Гаврила с экрана «Домой» есть в системном «Поделиться» (share_target) → POST /share → /?share=<id>.
// - iPhone: Safari так не умеет — «Быстрая команда» шлёт POST /api/share с токеном устройства (страница iphoneGuide).
// Шторка «Поделились»: превью (текст, ссылка, миниатюры) и «Куда отправить»: новый чат, один из последних чатов,
// «Сохранить во Входящие». Ничего не уходит само — текст встаёт в поле ввода, отправляет человек.
// ?share=<id> — открыть запись; ?share=iphone — страница iPhone; ?share=login|denied|big|error — почему не вышло.

const CSS = `.shr .shr-prev { margin: 2px 16px 8px; padding: 12px; border-radius: var(--radius-md); background: var(--bg-subtle);
  display: grid; gap: 6px; overflow-wrap: anywhere; }
.shr .shr-prev b { font-size: calc(15px * var(--fz, 1)); }
.shr .shr-prev p { margin: 0; white-space: pre-wrap; max-height: 9em; overflow: auto; color: var(--text-primary); }
.shr .shr-prev a { color: var(--accent-primary); word-break: break-all; }
.shr .shr-imgs { display: flex; flex-wrap: wrap; gap: 6px; }
.shr .shr-imgs img { width: 72px; height: 72px; object-fit: cover; border-radius: var(--radius-sm); background: var(--bg-surface); }
.shr .shr-file { display: flex; align-items: center; gap: 8px; color: var(--text-secondary); font-size: calc(13px * var(--fz, 1)); }
.shr .note { margin: 8px 16px 4px; }
.shr ol.shr-steps { margin: 4px 16px 0; padding-left: 22px; line-height: 1.5; }
.shr ol.shr-steps li { margin: 6px 0; }
.shr ol.shr-steps code, .shr .shr-code { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: calc(13px * var(--fz, 1));
  background: var(--bg-subtle); border-radius: 5px; padding: 1px 5px; overflow-wrap: anywhere; }
.shr .shr-code { word-break: break-all; }
.shr .shr-code { display: block; margin: 6px 16px 0; padding: 8px 10px; }
.shr .shr-scheme { display: block; width: calc(100% - 32px); max-width: 520px; margin: 4px 16px 8px; color: var(--text-primary); }
.shr .shr-scheme rect { fill: var(--bg-subtle); stroke: var(--border-subtle); }
.shr .shr-scheme rect.on { fill: var(--accent-primary); stroke: none; }
.shr .shr-scheme text { fill: currentColor; font: 12px system-ui, sans-serif; }
.shr .shr-scheme text.on { fill: var(--bg-surface); font-weight: 600; }
.shr .shr-scheme path { stroke: var(--text-secondary); fill: none; stroke-width: 1.5; }
.shr .row2 { margin-top: 10px; }
@media (min-width: 900px) { .sheet.shr { max-width: 560px; } }`;
const css = () => { if (!document.getElementById("shrCss")) document.head.insertAdjacentHTML("beforeend", `<style id="shrCss">${CSS}</style>`); };

const WHY = {
  login: ["Войдите и поделитесь снова", "Без входа Гаврила не знает, чьё это. Войдите и снова нажмите «Поделиться» — запись появится здесь."],
  denied: ["Нет прав на запись", "У вас доступ только на просмотр — поделиться в Гаврилу может участник или владелец пульта."],
  big: ["Больше 50 МБ", "Гаврила принимает до 50 МБ за раз. Отправьте файлы частями."],
  error: ["Не получилось", "Запись не дошла целиком. Поделитесь ещё раз — если повторится, отправьте файл через скрепку в чате."],
};

// демо (?demo&share=demo): пример записи без сервера
const DEMO_ITEMS = [{ id: "demo", at: Date.now() / 1000 - 40, via: "android", title: "Счёт за ноябрь",
  text: "Посмотри, пожалуйста, всё ли сходится с договором", url: "https://example.org/invoice/1124",
  files: [{ name: "счёт-ноябрь.jpg", path: "/home/u/.local/share/gas-pult/inbox/20261121-101500-a1b2c3-schet.jpg", size: 412000, image: true },
    { name: "фото-стенда.jpg", path: "/home/u/.local/share/gas-pult/inbox/20261121-101500-d4e5f6-stend.jpg", size: 280000, image: true },
    { name: "договор.pdf", path: "/home/u/.local/share/gas-pult/inbox/20261121-101500-0a1b2c-dogovor.pdf", size: 1250000, image: false }] }];
let demoDone = false, demoDevs = [{ id: "d1", name: "iPhone Гаврилы", created: Date.now() / 1000 - 86400 * 3, seen: Date.now() / 1000 - 3600 }];

const size = (n) => n >= 1 << 20 ? (n / (1 << 20)).toFixed(1).replace(".", ",") + " МБ" : Math.max(1, Math.round(n / 1024)) + " КБ";
const when = (t) => (t ? new Date(t * 1000).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");
const dropParam = () => { if (!params.has("share")) return; const u = new URL(location.href); u.searchParams.delete("share"); history.replaceState(null, "", u); };

async function items() {
  if (DEMO) return demoDone ? [] : DEMO_ITEMS;
  return (await api("/api/share/list")).items || [];
}

async function thumb(rec, i) {                         // <img> не несёт вход Mini App — грузим fetch → blob
  if (DEMO) {
    const c = Object.assign(document.createElement("canvas"), { width: 144, height: 144 }), g = c.getContext("2d");
    g.fillStyle = ["#7FA7D9", "#D9A77F"][i % 2]; g.fillRect(0, 0, 144, 144);
    g.fillStyle = "#fff"; g.font = "bold 22px sans-serif"; g.fillText(rec.files[i].name.slice(0, 9), 12, 80);
    return c.toDataURL("image/png");
  }
  const b = await api(`/api/share/file?id=${encodeURIComponent(rec.id)}&i=${i}`);
  return URL.createObjectURL(b);
}

// Текст для поля ввода: заголовок, текст, ссылка (без повторов — Android кладёт ссылку и в text) и пути файлов.
function compose(rec) {
  const parts = [];
  for (const s of [rec.title, rec.text, rec.url]) if (s && !parts.some((p) => p.includes(s))) parts.push(s);
  const files = rec.files.map((f) => "Файл из панели: " + f.path);
  return [parts.join("\n"), files.join("\n")].filter(Boolean).join("\n\n");
}

function recent() {                                    // 3–5 последних чатов, куда можно вставить текст
  return (typeof sessions !== "undefined" ? sessions : []).filter((s) => s.status !== "stopped" && !s.space)
    .sort((a, b) => (b.changed || 0) - (a.changed || 0)).slice(0, 3);
}

function intoChat(id, text) {                          // в поле ввода выбранного чата; отправит человек
  openSession(id).then(() => setTimeout(() => { const el = $("input"); el.value = (el.value ? el.value + "\n\n" : "") + text; grow(); el.focus(); }, 120));
}

async function markDone(rec) {
  if (DEMO) { demoDone = true; return; }
  try { await api("/api/share/done", { id: rec.id }); } catch (e) { toast(e.message, 4000); }
}

function frame(html) {
  css();
  const bg = document.createElement("div"); bg.className = "sheet-bg";
  bg.innerHTML = `<div class="sheet shr" role="dialog">${html}</div>`;
  document.body.append(bg);
  return bg;
}

function why(code) {
  const [t, s] = WHY[code];
  const bg = frame(`<h3>${esc(t)}</h3><p class="note">${esc(s)}</p><button class="cancel" data-close>Понятно</button>`);
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) bg.remove(); });
}

function showRec(rec, left) {
  const text = compose(rec), imgs = rec.files.map((f, i) => [f, i]).filter(([f]) => f.image), other = rec.files.filter((f) => !f.image);
  const chats = recent();
  const head = rec.title || (rec.url ? "ссылка" : rec.files.length ? rec.files.length + " " + plural(rec.files.length, ["файл", "файла", "файлов"]) : "текст");
  const bg = frame(`<h3>Поделились: ${esc(head.length > 48 ? head.slice(0, 47) + "…" : head)}</h3>
    <div class="shr-prev">${rec.title ? `<b>${esc(rec.title)}</b>` : ""}${rec.text ? `<p>${esc(rec.text)}</p>` : ""}
      ${rec.url ? `<a href="${esc(rec.url)}" target="_blank" rel="noopener noreferrer">${esc(rec.url)}</a>` : ""}
      ${imgs.length ? `<div class="shr-imgs">${imgs.map(([f, i]) => `<img alt="${esc(f.name)}" data-i="${i}">`).join("")}</div>` : ""}
      ${other.map((f) => `<div class="shr-file">${ic("file", "s16")}<span>${esc(f.name)} · ${size(f.size)}</span></div>`).join("")}
      <small class="note" style="margin:0">${esc(when(rec.at))}${rec.via === "iphone" ? " · с iPhone" : ""}${rec.files.length ? " · файлы — во «Входящих»" : ""}</small></div>
    <h3 class="sub">Куда отправить</h3>
    <button data-k="new">${ic("plus")}<span>Новый чат<small>текст и файлы встанут в поле ввода</small></span></button>
    ${chats.map((s) => `<button data-k="w" data-w="${esc(s.id)}">${ic("chat")}<span>В чат «${esc(s.title || s.name)}»<small>${s.changed ? "был " + esc(agoText(s.changed)) : "открытый чат"}</small></span></button>`).join("")}
    <button data-k="inbox">${ic("folder")}<span>Сохранить во Входящие<small>${rec.files.length ? "файлы уже там; запись уйдёт из этого списка" : "запись уйдёт из этого списка"}</small></span></button>
    <p class="note">Ничего не отправится само: текст встанет в поле ввода, отправите вы.${left > 1 ? ` Ещё ${left - 1} — откроются следом.` : ""}</p>
    <button class="cancel" data-close>Позже</button>`);
  imgs.forEach(([, i]) => thumb(rec, i).then((u) => { const im = bg.querySelector(`img[data-i="${i}"]`); if (im) im.src = u; }, () => bg.querySelector(`img[data-i="${i}"]`)?.remove()));
  bg.addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    if (e.target === bg || b?.dataset.close) return bg.remove();
    if (!b?.dataset.k) return;
    bg.remove();
    await markDone(rec);
    if (b.dataset.k === "new") chatWith(text);
    else if (b.dataset.k === "w") intoChat(b.dataset.w, text);
    else { toast("Сохранено во Входящих"); if (left > 1) setTimeout(() => open(), 400); }
  });
}

// Открыть: запись по id (или первую неразобранную); коды — почему не вышло; iphone — страница настройки.
export async function open(id) {
  id = id || params.get("share") || "";
  dropParam();
  if (WHY[id]) return why(id);
  if (id === "iphone") return iphoneGuide();
  if (id === "devices") return devicesSheet();
  let list;
  try { list = await items(); } catch (e) { return toast("Поделились: " + e.message, 4000); }
  if (!list.length) return id && id !== "demo" ? toast("Эта запись уже разобрана") : undefined;
  if (typeof sessions !== "undefined" && !sessions.length && !DEMO) await refreshShared().catch(() => {});
  showRec(list.find((x) => x.id === id) || list[0], list.length);
}

// ---------- «Устройства для «Поделиться»» (настройки → Аккаунт и вход) ----------
async function devices() {
  if (DEMO) return demoDevs;
  return (await api("/api/share/devices")).devices || [];
}

export async function devicesSheet() {
  let devs;
  try { devs = await devices(); } catch (e) { return toast(e.message, 4000); }
  sheet("Устройства для «Поделиться»", [
    { info: true, icon: "share", label: "Android: установите Гаврилу на экран «Домой»", sub: "Chrome → ⋮ → «Добавить на гл. экран». После этого Гаврила есть в «Поделиться» сам — токен не нужен" },
    { info: true, icon: "phone", label: "iPhone: «Быстрая команда» с токеном", sub: "Safari не даёт сайтам место в «Поделиться» — поэтому команда. Токен — свой у каждого устройства" },
    ...devs.map((d) => ({ label: d.name || "iPhone", icon: "phone", sub: `добавлен ${when(d.created)} · ${d.seen ? "был " + when(d.seen) : "ещё не присылал"} · нажмите, чтобы отозвать`,
      run: () => confirmDanger(`Отозвать «${d.name}»? Быстрая команда на нём перестанет работать.`, async () => {
        try { if (DEMO) demoDevs = demoDevs.filter((x) => x.id !== d.id); else await api("/api/share/devices/revoke", { id: d.id }); toast("Отозвано"); devicesSheet(); } catch (e) { toast(e.message, 4000); }
      }) })),
    { label: "Добавить iPhone", icon: "plus", sub: "пошаговая настройка и токен", run: () => iphoneGuide() },
  ]);
}

// Схема без скриншотов iOS (рисуем сами): что происходит при «Поделиться».
const SCHEME = `<svg class="shr-scheme" viewBox="0 0 520 70" role="img" aria-label="Фото или ссылка, Поделиться, команда «В Гаврилу», Гаврила">
  <rect x="2" y="16" width="104" height="38" rx="9"/><text x="54" y="40" text-anchor="middle">Фото, ссылка</text>
  <path d="M108 35h22m-6-5l6 5-6 5"/>
  <rect x="134" y="16" width="104" height="38" rx="9"/><text x="186" y="40" text-anchor="middle">«Поделиться»</text>
  <path d="M240 35h22m-6-5l6 5-6 5"/>
  <rect x="266" y="16" width="118" height="38" rx="9"/><text x="325" y="40" text-anchor="middle">«В Гаврилу»</text>
  <path d="M386 35h22m-6-5l6 5-6 5"/>
  <rect class="on" x="412" y="16" width="106" height="38" rx="9"/><text class="on" x="465" y="40" text-anchor="middle">Гаврила</text></svg>`;

const demoTok = () => ["gps", "demo", "0".repeat(28)].join("_");   // демо: не настоящий токен

export function iphoneGuide() {
  const url = location.origin + "/api/share";
  let token = "";
  const bg = frame(`<h3>Гаврила в «Поделиться» на iPhone</h3>${SCHEME}
    <p class="note">Safari не даёт сайтам место в меню «Поделиться». Поэтому — «Быстрая команда»: один раз настроить, дальше — как у приложения.</p>
    <ol class="shr-steps">
      <li>Нажмите «Создать токен и скопировать» ниже. Токен покажется один раз.</li>
      <li>Откройте «Команды» (Shortcuts) → «+». Назовите команду «В Гаврилу».</li>
      <li>Нажмите ⓘ (Сведения) → включите «Показывать в меню «Поделиться»».</li>
      <li>Добавьте действие «Получить содержимое URL». Адрес: <code>${esc(url)}</code></li>
      <li>Метод — <code>POST</code>. Заголовки → добавить: ключ <code>Authorization</code>, значение <code>Bearer</code>, пробел и токен.</li>
      <li>Тело запроса — «Форма». Поле <code>files</code>, тип «Файл», значение — «Ввод быстрой команды». Для текста и ссылок — второе поле <code>text</code>, тип «Текст», то же значение.</li>
      <li>Готово: в фото или Safari нажмите «Поделиться» → «В Гаврилу». Придёт сообщение бота, запись — в Гавриле.</li>
    </ol>
    <code class="shr-code" id="shrTok">токен ещё не создан</code>
    <p class="note">Готовый файл команды не даём: новые iOS открывают только файлы, подписанные через Apple. Отозвать токен — «Настройки» → «Аккаунт и вход» → «Устройства для «Поделиться»».</p>
    <div class="row2"><button class="btn ghost" data-close>Закрыть</button><button class="btn" id="shrMake">Создать токен и скопировать</button></div>`);
  bg.addEventListener("click", async (e) => {
    if (e.target === bg || e.target.closest("[data-close]")) return bg.remove();
    if (!e.target.closest("#shrMake")) return;
    if (token) return copyText(token, "Токен скопирован");
    try {
      const d = DEMO ? { token: demoTok(), id: "d" + Date.now(), name: "iPhone" } : await api("/api/share/devices/new", { name: "iPhone" });
      if (DEMO) demoDevs.push({ id: d.id, name: d.name, created: Date.now() / 1000, seen: null });
      token = d.token;
      bg.querySelector("#shrTok").textContent = token;
      bg.querySelector("#shrMake").textContent = "Скопировать токен";
      copyText(token, "Токен скопирован — вставьте в заголовок Authorization после «Bearer »");
    } catch (er) { toast(er.message, 4000); }
  });
}

Object.assign(window, { shareOpen: open, shareDevices: devicesSheet, shareIphone: iphoneGuide });
