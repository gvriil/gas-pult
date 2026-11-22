// «Подключения» → «Мессенджеры» (владелец 22.11, вариант А: «человек решает сам»). Часть по требованию (#191).
// Telegram — свой аккаунт (вход по номеру и коду) после экрана согласия по п. 1.5 условий Telegram API.
// Signal и WhatsApp — связанное устройство по QR после экрана «Неофициальный способ… Решаете вы».
// MAX — только строка: вход пользователем запрещён соглашением MAX. Секреты в браузер не возвращаются:
// после ввода поля очищаются, QR приходит картинкой. Сервер — messengers/panel.py.

let D = null, BOX = null;
const css = document.createElement("style");
css.textContent = `
.msg-risk { border-left: 3px solid var(--status-danger); }
.msg-qr { display: block; width: min(260px, 100%); aspect-ratio: 1; margin: 10px auto; border-radius: 12px; background: #fff; padding: 6px; image-rendering: pixelated; }
.msg-cmd { white-space: pre-wrap; word-break: break-all; font-size: 13px; background: var(--bg-subtle); border-radius: 10px; padding: 10px 12px; margin: 8px 0; }
.msg-chats label { display: flex; align-items: center; gap: 10px; min-height: 44px; border-bottom: 1px solid var(--border-subtle); }
.msg-chats label small { color: var(--text-muted); margin-left: auto; }
.s-body .msg-acts { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
.tile small.chip.msg-un { align-self: flex-start; }
.tile[aria-disabled] { cursor: default; box-shadow: none; background: var(--bg-subtle); }
`;
document.head.append(css);

const st = (id) => D.services.find((s) => s.id === id) || {};
const res = (kind, icon, text) => `<div class="result ${kind}">${ic(icon)}<span>${text}</span></div>`;

export async function section(box) {
  BOX = box;
  try { D = await api("/api/messengers"); } catch (e) { box.innerHTML = ""; return; }
  box.innerHTML = `<div class="section">Мессенджеры</div>
    <p class="note">Ваш аккаунт. Модель читает чаты; отправить может только черновиком — после вашего «Да». Входящие видны в «Сегодня».</p>
    <div class="tiles">${D.catalog.map((c) => {
      if (c.kind === "off") return `<div class="tile" aria-disabled="true">${mono(c.title, c.id)}<span>${esc(c.title)}</span><small>${esc(c.about)}</small></div>`;
      const s = st(c.id);
      return `<button class="tile${s.connected ? " on" : ""}" data-msg="${esc(c.id)}">${mono(c.title, c.id)}<span>${esc(c.title)}</span>
        <small>${s.connected ? "подключено · " + esc(s.who) : esc(c.about)}</small>${c.kind === "risk" ? '<small class="chip bad msg-un">неофициально</small>' : ""}</button>`;
    }).join("")}</div>`;
  box.onclick = (e) => { const t = e.target.closest("[data-msg]"); if (t) open(t.dataset.msg); };
  const want = DEMO && params.get("msg");             // демо: ?view=integrations&msg=whatsapp|whatsapp-qr|telegram|telegram-code|telegram-chats
  if (want && !section.once) { section.once = 1; open(want.split("-")[0], want.split("-")[1]); }
}
const refresh = () => BOX && section(BOX);

function open(svc, step) {
  const s = st(svc);
  if (step === "qr") return qrSheet(svc);
  if (step === "code") return loginSheet(svc, "code");
  if (step === "chats" || (s.connected && svc === "telegram")) return manageSheet(svc);
  if (s.connected) return manageSheet(svc);
  if (!s.consented) return consentSheet(svc);
  next(svc);
}
function next(svc) {
  const s = st(svc);
  if (s.install) return installSheet(svc);
  return svc === "telegram" ? loginSheet(svc) : qrSheet(svc);
}

// ---------- выбор человека: без него мост не стартует ----------
function consentSheet(svc) {
  const s = st(svc), tg = svc === "telegram";
  const body = tg
    ? `<p>${esc(s.text)}</p>
       <ul class="note"><li>Вход — вашим номером и кодом из Telegram; api_id и api_hash — ваши, с my.telegram.org.</li>
       <li>Модели открываете только выбранные чаты — после согласия собеседников.</li>
       <li>Сессия хранится на сервере в закрытом файле; «Отключить» её стирает.</li></ul>`
    : `<div class="result bad msg-risk">${ic("warn")}<span><b>${esc(s.text)}</b></span></div>
       <ul class="note"><li>Пульт подключается как ещё одно устройство — как ${svc === "whatsapp" ? "WhatsApp Web" : "Signal Desktop"}.</li>
       <li>Модель читает чаты; отправить может только после вашего «Да».</li>
       <li>«Отключить» стирает вход с сервера; на телефоне уберите устройство в «Связанных устройствах».</li></ul>`;
  sSheet(hv("int.messengers"), "Подключить " + s.title, `${body}
    <button class="btn wide" type="button" data-ok>${ic("check")}${tg ? "Понимаю, подключить" : "Подключить"}</button>`,
    async (b, bg) => {
      if (!b.hasAttribute("data-ok")) return;
      try { await api("/api/messengers/consent", { svc, accepted: true }); D = await api("/api/messengers"); bg.remove(); next(svc); }
      catch (e) { toast(e.message, 4500); }
    }, "Отмена");
}

function installSheet(svc) {
  const s = st(svc);
  sSheet(hv("int.messengers"), s.title + ": нужна программа", `<p>Для ${esc(s.title)} на сервере нужна программа <b>${esc(s.install.what)}</b>. Пульт не ставит её сам — поставьте одной командой в терминале сервера:</p>
    <div class="msg-cmd">${esc(s.install.cmd)}</div>
    <div class="msg-acts"><button class="btn ghost" type="button" data-copy>${ic("copy")}Скопировать</button>
    <button class="btn" type="button" data-again>${ic("refresh")}Проверить снова</button></div>`,
    async (b, bg) => {
      if (b.hasAttribute("data-copy")) return copyText(s.install.cmd);
      if (!b.hasAttribute("data-again")) return;
      D = await api("/api/messengers");
      if (st(svc).install) return toast("Пока не вижу программу на сервере", 3500);
      bg.remove(); next(svc);
    });
}

// ---------- Telegram: api_id/api_hash → номер → код → облачный пароль ----------
function loginSheet(svc, start) {
  const s = st(svc);
  const inp = (id, label, type, ph, hint) => `<div class="field"><label for="${id}">${label}</label><div class="inp"><input id="${id}" type="${type}" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="${ph}"></div>${hint ? `<div class="hint">${hint}</div>` : ""}</div>`;
  const keys = s.api ? "" : inp("tgId", "api_id", "text", "1234567", "")
    + inp("tgHash", "api_hash", "password", "32 знака", "Откройте my.telegram.org → войдите своим номером → «API development tools» → создайте приложение (название любое). Там api_id и api_hash — они ваши. Хранятся на сервере в закрытом файле и сюда не возвращаются.");
  const bg = sSheet(hv("int.messengers"), "Вход в Telegram", `
    <div data-st="phone"${start === "code" ? " hidden" : ""}>${keys}${inp("tgPhone", "Номер телефона", "tel", "+7 999 123-45-67", "Номер с кодом страны. Не сохраняется: на сервере — только последние 4 цифры.")}
      <button class="btn wide" type="button" data-send>${ic("send")}Получить код</button></div>
    <div data-st="code"${start === "code" ? "" : " hidden"}>${inp("tgCode", "Код из Telegram", "text", "12345", "Код придёт в приложение Telegram (чат «Telegram») или по SMS. Никому его не пересылайте.")}
      <button class="btn wide" type="button" data-code>${ic("check")}Войти</button></div>
    <div data-st="pw" hidden>${inp("tgPw", "Облачный пароль Telegram", "password", "", "Включена двухэтапная проверка — нужен её пароль.")}
      <button class="btn wide" type="button" data-pw>${ic("check")}Войти</button></div>
    <div data-out></div>`,
    async (b) => {
      const out = bg.querySelector("[data-out]"), step = (x) => bg.querySelectorAll("[data-st]").forEach((d) => { d.hidden = d.dataset.st !== x; });
      const val = (id) => bg.querySelector("#" + id)?.value || "";
      const run = async (path, body, ok) => {
        b.disabled = true; out.innerHTML = res("wait", "wait", "Связываюсь с Telegram…");
        try { const r = await api(path, body); bg.querySelectorAll("input").forEach((x) => { x.value = ""; }); out.innerHTML = ""; ok(r); }
        catch (e) { out.innerHTML = res("bad", "warn", esc(e.message)); }
        b.disabled = false;
      };
      if (b.hasAttribute("data-send")) return run("/api/messengers/tg/login", { api_id: val("tgId"), api_hash: val("tgHash"), phone: val("tgPhone") },
        (r) => { step("code"); out.innerHTML = res("ok", "check", r.sent === "sms" ? "Код отправлен по SMS." : "Код отправлен в приложение Telegram."); bg.querySelector("#tgCode")?.focus(); });
      const done = (r) => { if (r.need === "password") { step("pw"); return bg.querySelector("#tgPw")?.focus(); } bg.remove(); haptic("notificationOccurred", "success"); toast("Telegram подключён"); refresh(); manageSheet(svc, true); };
      if (b.hasAttribute("data-code")) return run("/api/messengers/tg/code", { code: val("tgCode") }, done);
      if (b.hasAttribute("data-pw")) return run("/api/messengers/tg/password", { password: val("tgPw") }, done);
    }, "Отмена");
  setTimeout(() => bg.querySelector("input:not([hidden])")?.focus(), 60);
}

// ---------- Signal и WhatsApp: QR, обновляется сам ----------
function qrSheet(svc) {
  const s = st(svc), wa = svc === "whatsapp";
  const how = wa ? "Телефон → WhatsApp → Настройки → «Связанные устройства» → «Привязка устройства» → наведите камеру на код."
    : "Телефон → Signal → Настройки → «Связанные устройства» → «+» → наведите камеру на код.";
  const bg = sSheet(hv("int.messengers"), "Привязать " + s.title, `<p class="note">${esc(how)}</p>
    <div data-qr>${res("wait", "wait", "Готовлю код — до 20 секунд…")}</div>
    <p class="note">Код обновляется сам. Пока вы не отсканировали его, ничего не привязано.</p>`, null, "Отмена");
  let alive = true;
  const tick = async () => {
    if (!alive || !bg.isConnected) return;
    try {
      const r = await api("/api/messengers/link", { svc });
      if (r.linked) { alive = false; bg.remove(); haptic("notificationOccurred", "success"); toast(s.title + " подключён"); return refresh(); }
      bg.querySelector("[data-qr]").innerHTML = `<img class="msg-qr" alt="QR-код для привязки ${esc(s.title)}" src="${r.qr}">`;
    } catch (e) { bg.querySelector("[data-qr]").innerHTML = res("bad", "warn", esc(e.message)); }
    if (!DEMO) setTimeout(tick, 5000);
  };
  tick();
}

// ---------- подключено: чаты для модели (Telegram) и «Отключить» ----------
async function manageSheet(svc, fresh) {
  const s = st(svc), tg = svc === "telegram";
  const bg = sSheet(hv("int.messengers"), s.title, `${res("ok", "check", "Подключено" + (s.who ? " · " + esc(s.who) : ""))}
    ${tg ? `<div class="section">Чаты для модели</div><p class="note">По условиям Telegram модель может читать чат, только если собеседники согласны. Отметьте такие чаты — остальные модель не увидит.</p><div class="msg-chats" data-chats>${res("wait", "wait", "Загружаю чаты…")}</div>
      <button class="btn wide" type="button" data-allow>${ic("check")}Сохранить</button>` : ""}
    <button class="btn danger wide" type="button" data-off style="margin-top:8px">${ic("trash")}Отключить</button>`,
    async (b) => {
      if (b.hasAttribute("data-allow")) {
        const chats = [...bg.querySelectorAll("[data-chat]:checked")].map((x) => x.dataset.chat);
        try { await api("/api/messengers/allow", { svc, chats }); toast(chats.length ? `Модели открыто чатов: ${chats.length}` : "Модели не открыт ни один чат"); bg.remove(); refresh(); }
        catch (e) { toast(e.message, 4500); }
      }
      if (b.hasAttribute("data-off")) confirmDanger(`Отключить ${s.title}? Вход и входящие сотрутся с сервера.`, async () => {
        await api("/api/messengers/off", { svc }); bg.remove(); toast(s.title + " отключён"); refresh();
      });
    });
  if (!tg) return;
  try {
    const r = await api("/api/messengers/chats", { svc }), on = new Set(r.allowed);
    bg.querySelector("[data-chats]").innerHTML = r.chats.map((c) => `<label><input type="checkbox" data-chat="${esc(c.id)}"${on.has(c.id) ? " checked" : ""}><span>${esc(c.name || c.id)}</span><small>${c.kind === "user" ? "личный" : c.kind === "group" ? "группа" : "канал"}</small></label>`).join("") || '<p class="note">Чатов нет.</p>';
  } catch (e) { bg.querySelector("[data-chats]").innerHTML = res("bad", "warn", esc(e.message)); }
  if (fresh) bg.querySelector("[data-chats]")?.scrollIntoView({ block: "nearest" });
}
