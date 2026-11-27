// Фокус-ссылка на нескольких устройствах (владелец 22.11). На телефоне ссылка открылась; на компьютере открыли адрес
// «/?focus» — без токена (страница убирает его из адреса) — и видели глухое «Ссылка не действует». Теперь:
//  • gone(text, why) — свой экран для каждой причины (сервер: focus.Gone.why): что случилось и что сделать; кнопка
//    «Попросить доступ» → /api/focus/ask (до входа; 3 запроса за 10 минут с адреса);
//  • device() — «Открыть на другом устройстве»: одноразовая ссылка той же записи на 15 минут, QR и «Скопировать»;
//  • ask(id, act) — владелец открыл кнопку из сообщения «Просят доступ»: «Добавить устройство» или «Новая ссылка»;
//  • loginNote(el) — экран входа на устройстве, где раньше открывали фокус-ссылку: «Вам не нужен вход».
// Что возможно без токена (честно): на новом устройстве страница не знает, какая это ссылка. Знает, только если ссылку
// уже открывали в этом браузере (id записи в localStorage, не токен) или токен ещё в памяти страницы. Иначе владельцу
// уходит текст человека и вид устройства — ссылку он выбирает сам.

const MARK = "gp.focus";                            // {id, name}: id записи ссылки (не токен) — для «Попросить доступ»
export const mark = () => { try { return JSON.parse(localStorage.getItem(MARK) || "null"); } catch (e) { return null; } };

document.head.insertAdjacentHTML("beforeend", `<style>
  .fd-end { max-width: 420px; width: 100%; text-align: left; }
  .fd-end > .i { display: block; margin: 0 auto; }
  .fd-end h2 { text-align: center; }
  .fd-end p { margin: 0 0 10px; color: var(--text-secondary); }
  .fd-steps { margin: 0 0 14px; padding: 0 0 0 22px; color: var(--text-primary); }
  .fd-steps li { margin: 0 0 8px; line-height: 1.4; }
  .fd-end .btn { width: 100%; margin: 6px 0 0; }
  .fd-end .btn .i, .fd-end .result .i { width: 18px; height: 18px; color: inherit; }
  .fd-end .field { margin: 8px 0 0; }
  .fd-end .note { text-align: center; }
  .fd-dev { display: flex; flex-direction: column; gap: 2px; }
  .fd-dev .row-note { margin: 0 16px; }
  .fd-ask dl { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; margin: 4px 16px 10px; font-size: 14px; }
  .fd-ask dt { color: var(--text-secondary); }
  .fd-ask dd { margin: 0; overflow-wrap: anywhere; }
  .login-focus { margin: 0 0 12px; }
  .login-focus .btn { margin-top: 8px; }
</style>`);

// ---------- экраны «ссылка не открылась» ----------
const SCREENS = {
  nodevice: { icon: "lock", title: "Нужна полная ссылка", ask: "Попросить доступ",
    text: "Вы открыли адрес без ключа доступа. Ключ есть только в полной ссылке, которую вам прислали.",
    steps: ["Откройте ссылку из сообщения ещё раз — целиком, а не адрес из строки браузера.",
      "Или возьмите устройство, где чат уже открыт. Нажмите ⋯ → «Открыть на другом устройстве» и отсканируйте QR.",
      "Ссылки нет? Нажмите «Попросить доступ» — владелец получит сообщение."] },
  limit: { icon: "lock", title: "Все места для устройств заняты", ask: "Попросить доступ",
    text: "Эту ссылку уже открыли на всех разрешённых устройствах. На новом устройстве она не откроется.",
    steps: ["Продолжайте на устройстве, где чат уже открыт.", "Нужно это устройство? Нажмите «Попросить доступ» — владелец добавит его или пришлёт новую ссылку."] },
  expired: { icon: "wait", title: "Срок ссылки вышел", ask: "Попросить новую ссылку",
    text: "Ссылка больше не работает.", steps: ["Нажмите «Попросить новую ссылку» — владелец получит сообщение."] },
  revoked: { icon: "lock", title: "Владелец отозвал ссылку", ask: "Попросить доступ",
    text: "Ссылка больше не работает.", steps: ["Нужен доступ снова? Нажмите «Попросить доступ»."] },
  bad: { icon: "warn", title: "Ссылка не найдена", ask: "Попросить доступ",
    text: "Возможно, ссылку скопировали не целиком или она устарела.",
    steps: ["Откройте ссылку из сообщения ещё раз — целиком.", "Не помогло? Нажмите «Попросить доступ»."] },
};
export const known = (why) => !!SCREENS[why];

export function gone(text, why) {
  const s = SCREENS[why], d = $("focusEnd"); if (!s || !d) return;
  d.dataset.why = why;
  d.innerHTML = `<div class="fd-end">${ic(s.icon)}<h2 class="serif">${esc(s.title)}</h2><p>${esc(s.text)}</p>
    <p><b>Что сделать</b></p><ol class="fd-steps">${s.steps.map((x) => `<li>${esc(x)}</li>`).join("")}</ol>
    <div data-fd-ask><button class="btn" type="button" data-fd-open>${ic("send", "s16")}${esc(s.ask)}</button></div></div>`;
  d.querySelector("[data-fd-open]").onclick = () => askForm(d.querySelector("[data-fd-ask]"), why);
}

// форма «Попросить доступ»: кто вы — владельцу; ссылка — по токену в памяти или id из localStorage
export function askForm(box, why) {
  const id = mark()?.id || "", knownLink = !!(FOCUS_TOKEN || id);
  box.innerHTML = `<div class="field"><label for="fdNote">Кто вы и о какой ссылке речь</label>
    <input id="fdNote" maxlength="120" autocomplete="name" placeholder="Например: Анна, ноутбук для отчётов"></div>
    <p class="note" style="text-align:left;margin:6px 0 0">${knownLink ? "Владелец увидит, о какой ссылке речь." : "Это устройство не знает, какая у вас ссылка. Напишите, кто вы, — владелец поймёт, кому ответить."}</p>
    <button class="btn" type="button" data-fd-send>${ic("send", "s16")}Отправить владельцу</button><div data-fd-res></div>`;
  const inp = box.querySelector("#fdNote"), res = box.querySelector("[data-fd-res]");
  inp.focus();
  box.querySelector("[data-fd-send]").onclick = (e) => busy(e.currentTarget, "Отправляю…", async () => {
    const note = inp.value.trim();
    if (!note && !knownLink) { res.innerHTML = `<p class="note" style="color:var(--status-danger)">Напишите, кто вы.</p>`; return inp.focus(); }
    const body = { why: why || "", note, ...(FOCUS_TOKEN ? { token: FOCUS_TOKEN } : {}), ...(id ? { id } : {}) };
    try {
      if (DEMO) await demoApi("/api/focus/ask", body);
      else {
        const r = await fetch("/api/focus/ask", { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify(body) });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || "ошибка " + r.status);
      }
      box.innerHTML = `<div class="result ok">${ic("check")}<span>Запрос отправлен владельцу.</span></div>
        <p class="note" style="text-align:left;margin:8px 0 0">Владелец пришлёт новую ссылку сам — в мессенджере или по почте. Эту страницу можно закрыть.</p>`;
    } catch (err) { res.innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(err.message)}</span></div>`; }
  });
  inp.onkeydown = (e) => { if (e.key === "Enter") box.querySelector("[data-fd-send]").click(); };
}

// ---------- «Открыть на другом устройстве» ----------
function qrSheet(d, title, extra = "") {
  const till = new Date(d.exp * 1000).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.focus");
  bg.innerHTML = `<div class="sheet fd-dev" role="dialog" aria-label="${esc(title)}"><h3>${esc(title)}</h3>
    <p class="note row-note">Отсканируйте QR камерой телефона или откройте ссылку на компьютере. Чат откроется там без входа.</p>
    <img class="focus-qr" alt="QR-код ссылки для другого устройства" src="${esc(d.qr || "")}"><div class="focus-url" id="fdUrl"></div>
    <p class="note row-note">Ссылка работает до ${esc(till)} и только один раз.${d.max ? ` Устройств: ${d.used} из ${d.max}.` : ""}</p>
    <button data-fd="copy">${ic("copy")}<span>Скопировать ссылку</span></button>${extra}
    <button class="cancel" data-close>Готово</button></div>`;
  bg.querySelector("#fdUrl").textContent = d.url;
  document.body.append(bg);
  bg.addEventListener("click", async (e) => {
    if (e.target === bg || e.target.closest("[data-close]")) return bg.remove();
    const b = e.target.closest("[data-fd]"); if (!b) return;
    if (b.dataset.fd === "copy") return copyText(d.url, "Ссылка скопирована");
    if (b.dataset.fd === "tg") return busy(b, "Отправляю…", async () => { try { await api("/api/focus/send", { url: d.url }); toast("Ссылка — в вашем чате с ботом"); } catch (err) { toast(err.message, 5000); } });
  });
  return bg;
}
function fullSheet(msg) {
  helpSheet("sheet.focus");
  sheet("Все места заняты", [{ info: true, icon: "lock", label: msg }]);
}

export async function device(id) {                   // id — запись (у владельца); на устройстве по ссылке — своя
  let d; try { d = await api("/api/focus/device", { base: location.origin, ...(id ? { id } : {}) }); }
  catch (e) { return e.code === "full" ? fullSheet(e.message) : toast("Не вышло: " + e.message, 5000); }
  return qrSheet(d, id ? "Ссылка для нового устройства" : "Открыть на другом устройстве",
    id ? `<button data-fd="tg">${ic("send")}<span>Отправить себе в Telegram<small>перешлите её человеку</small></span></button>` : "");
}

// ---------- владелец: «Просят доступ» ----------
const WHY_T = { nodevice: "открыли адрес без полной ссылки", limit: "все места для устройств заняты", expired: "срок ссылки вышел",
  revoked: "ссылку отозвали", bad: "ссылка не найдена", closed: "чат завершён" };
export async function ask(aid, act) {
  let a; try { a = await api("/api/focus/asks?id=" + encodeURIComponent(aid)); } catch (e) { return toast(e.message, 5000); }
  const l = a.link, chat = l && (l.w || l.proj), when = new Date(a.at * 1000).toLocaleString("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
  const add = () => device(l.id), fresh = () => focusLink(l.proj ? null : l.w, l.proj || null, l.mode === "demo" ? "demo" : undefined);
  if (act === "add" && l?.live) return add();
  if (act === "new" && chat) return fresh();
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.focus");
  bg.innerHTML = `<div class="sheet fd-ask" role="dialog" aria-label="Просят доступ"><h3>Просят доступ</h3><dl>
      ${a.note ? `<dt>Пишет</dt><dd>«${esc(a.note)}»</dd>` : ""}
      <dt>Почему</dt><dd>${esc(WHY_T[a.why] || "ссылка не открылась")}</dd>
      ${a.device ? `<dt>Устройство</dt><dd>${esc(a.device)}</dd>` : ""}<dt>Когда</dt><dd>${esc(when)}</dd>
      <dt>Ссылка</dt><dd>${l ? `${esc(l.name || "—")} · ${l.live ? (l.max ? `устройств ${l.used} из ${l.max}` : "действует") : esc(l.why || "не действует")}` : "не определена: человек открыл адрес на новом устройстве"}</dd></dl>
    ${l?.live ? `<button data-fd="add">${ic("plus")}<span>Добавить устройство<small>ссылка и QR на 15 минут — для одного устройства</small></span></button>` : ""}
    ${chat ? `<button data-fd="new">${ic("qr")}<span>Новая ссылка<small>на тот же чат; старую можно отозвать в «Фокус-ссылках»</small></span></button>`
      : `<button data-fd="list">${ic("qr")}<span>Фокус-ссылки<small>выберите ссылку или создайте новую</small></span></button>`}
    <p class="note" style="margin:8px 16px 0">Ссылку человеку пересылаете вы: у пульта нет его контакта.</p>
    <button class="cancel" data-close>Закрыть</button></div>`;
  document.body.append(bg);
  bg.addEventListener("click", (e) => {
    if (e.target === bg || e.target.closest("[data-close]")) return bg.remove();
    const b = e.target.closest("[data-fd]"); if (!b) return;
    bg.remove();
    return { add, new: fresh, list: focusList }[b.dataset.fd]?.();
  });
}

// ---------- экран входа: устройство, где раньше открывали фокус-ссылку ----------
export function loginNote(el) {
  if (!el || !mark()) return;
  el.hidden = false; el.className = "login-focus";
  el.innerHTML = `<div class="result ok">${ic("lock")}<span>Вам не нужен вход. Откройте ссылку из сообщения — чат откроется сам. Ссылки нет — нажмите «Попросить доступ».</span></div>
    <div data-fd-ask><button class="btn ghost" type="button" data-fd-open>${ic("send", "s16")}Попросить доступ</button></div>`;
  el.querySelector("[data-fd-open]").onclick = () => askForm(el.querySelector("[data-fd-ask]"), "nodevice");
}
