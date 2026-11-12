// ---------- вход ----------
function showLogin() { simpleHide(); show("login"); paintLoginLang(); loginMethods(); oidcReturn(); inviteCheck(); }
// Приглашение (/invite/<код> → /?invite=<код>): пометка над «Войти через Telegram»; после входа доступ — сразу.
// Лёгкий вход (задача 34): если на пульте есть демо-пространства (guest) — сразу экран «Как вас зовут?» → панель,
// без Telegram; ссылка для входа на другое устройство (kind=device) — одна кнопка «Войти», имя не спрашиваем.
const INVITE = params.get("invite") || "";
let invCode = "";
async function inviteCheck() {
  if (!INVITE) return;
  let r = { ok: false }; try { r = await api("/api/invite?code=" + encodeURIComponent(INVITE)); } catch (e) { /* покажем, что не вышло */ }
  if (r.ok && r.guest) return inviteShow(INVITE, r);
  $("inviteNote").hidden = false; $("inviteNote").className = "result " + (r.ok ? "ok" : "bad");
  $("inviteNote").innerHTML = ic(r.ok ? "check" : "warn") + `<span>${esc(r.ok ? LL("login.invite", "Приглашение в «{t}». Войдите через Telegram — доступ откроется сразу.").replace("{t}", r.title) : LL("login.invite.bad", "Приглашение недействительно: истёк срок, оно уже использовано или отозвано. Попросите новое."))}</span>`;
}
let invInfo = null;
async function inviteShow(code, r) {              // экран «Как вас зовут?» (или «Вход для …» — другое устройство)
  await dictReady;                                // заголовок — на языке экрана входа
  invCode = code; invInfo = r; loginPane("loginName"); invTitle();
  const dev = r.kind === "device";
  $("invNameBox").hidden = dev; $("invTg").hidden = dev || code !== INVITE;      // Telegram — только по ссылке
  if (!dev) setTimeout(() => $("invName").focus(), 50);
}
function invTitle() {                             // и после смены языка (paintLoginLang)
  if (!invInfo) return;
  $("invTitle").textContent = invInfo.kind === "device" ? LL("login.inv.device", "Вход для «{n}»").replace("{n}", invInfo.name || "")
    : LL("login.inv.title", "Вас пригласили в «{t}»").replace("{t}", invInfo.title);
}
$("invCodeBtn").onclick = () => { loginPane("loginInvCode"); setTimeout(() => $("invCode").focus(), 50); };
$("invCodeGo").onclick = (e) => busy(e.currentTarget, LL("login.inv.checking", "Проверяю…"), async () => {
  const code = $("invCode").value.trim();
  if (!code) return loginMsg(false, LL("login.inv.empty", "Введите код — слово и цифры."));
  try { inviteShow(code, await api("/api/invite/check", { code })); }
  catch (err) { loginMsg(false, err.message); }
});
$("invCode").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); $("invCodeGo").click(); } };
$("invName").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); $("invEnter").click(); } };
$("invEnter").onclick = (e) => busy(e.currentTarget, LL("login.inv.entering", "Вхожу…"), async () => {
  const name = $("invName").value.trim();
  if (!$("invNameBox").hidden && !name) { $("invName").focus(); return loginMsg(false, LL("login.inv.noname", "Напишите, как вас зовут.")); }
  try {
    await api("/api/invite/enter", { code: invCode, name });
    haptic("notificationOccurred", "success");
    if (INVITE) history.replaceState(null, "", location.pathname + location.search.replace(/([?&])invite=[^&]*&?/, "$1").replace(/[?&]$/, ""));
    if (DEMO) return loginMsg(true, LL("login.inv.demo", "В демо вход не выполняется: здесь откроется панель пространства."));
    await start();
  } catch (err) { loginMsg(false, err.message); }
});
$("invTg").onclick = () => { loginPane("loginStep1"); $("tgLogin").click(); };
// Способы входа, которые включены на этом пульте (почта — если владелец настроил SMTP).
async function loginMethods() {
  try {
    const m = await api("/api/login/methods"); $("emailLogin").hidden = !m.email; $("pkLogin").hidden = !(m.passkey && passkeyOk());
    $("invCodeBtn").hidden = !m.invite;
    $("googleLogin").hidden = !m.google; $("yandexLogin").hidden = !m.yandex; $("oidcNote").hidden = !(tg?.initData && (m.google || m.yandex));
  } catch (e) { for (const x of ["emailLogin", "pkLogin", "googleLogin", "yandexLogin", "oidcNote", "invCodeBtn"]) $(x).hidden = true; }
}
function loginPane(id) {                          // один шаг входа на экране: способы, код владельцу, почта, второй фактор
  for (const x of ["loginStep1", "loginStep2", "loginEmail", "login2fa", "loginInvCode", "loginName"]) $(x).hidden = x !== id;
  document.querySelector('#login [data-l="login.note"]').hidden = id === "loginInvCode" || id === "loginName";   // «подтвердите в Telegram» — не про приглашение
  $("loginResult").innerHTML = "";
}
const loginMsg = (ok, text) => { $("loginResult").innerHTML = `<div class="result ${ok ? "ok" : "bad"}">${ic(ok ? "check" : "warn")}<span>${esc(text)}</span></div>`; };
// Условия использования: при первом входе и после смены версии. До «Принимаю» панель не показывает остальное.
async function showTerms() {
  if (view === "terms") return;
  start.poll = null;                 // фоновые запросы — после согласия
  show("terms"); $("title").textContent = "Пульт"; setSub("<span>условия использования</span>");
  let d; try { d = await api("/api/terms"); } catch (e) { $("termsBox").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`; return; }
  $("termsBox").innerHTML = `<h2 class="serif">${esc(d.title)}</h2><p class="ver">Версия от ${esc(d.version.split("-").reverse().join("."))} · прочитайте перед началом работы</p>
    <ol>${d.points.map((p) => `<li>${esc(p)}</li>`).join("")}</ol>
    <a class="full" href="${esc(d.url)}" target="_blank" rel="noopener">${ic("book", "s16")}Полный текст условий</a>
    <button class="btn" id="termsOk">${ic("check")}Принимаю</button>
    ${meta?.via === "browser" ? '<button class="btn ghost" id="termsOut">Не принимаю — выйти</button>' : ""}
    <div id="termsResult"></div>`;
  $("termsOk").onclick = (e) => busy(e.currentTarget, "Сохраняю…", async () => {
    try { await api("/api/terms/accept", { version: d.version }); haptic("notificationOccurred", "success"); await start(); }
    catch (err) { $("termsResult").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(err.message)}</span></div>`; }
  });
  if ($("termsOut")) $("termsOut").onclick = async () => { try { await api("/api/logout", {}); } catch (e) {} showLogin(); };
}
// Страна человека: после условий (и в «Настройках» — поменять). Доступно то, что поставщики разрешают для страны;
// номер подтверждается в боте («Поделиться номером»), страна по IP — локальной базой (IP Geolocation by DB-IP).
const DENY = "Этот сервис недоступен в вашей стране по условиям поставщика";
const ccDate = (t) => t ? new Date(t * 1000).toLocaleDateString("ru-RU") : "";
function ipMark(c) {                              // отметка страны по IP — с атрибуцией базы (CC BY 4.0)
  const by = `<a href="${esc(c.attribution_url || "https://db-ip.com")}" target="_blank" rel="noopener">${esc(c.attribution || "IP Geolocation by DB-IP")}</a>`;
  return !c.geoip ? "нет данных — база стран по IP не загружена" : c.ip_cc ? `${esc(c.ip_cc)}${c.ip_at ? " · " + ccDate(c.ip_at) : ""} · ${by}` : `нет данных · ${by}`;
}
async function showCountry(change) {
  if (view === "country" && !change) return;
  start.poll = null;
  show("country"); $("title").textContent = "Пульт"; setSub("<span>ваша страна</span>");
  let d; try { d = await api("/api/country"); } catch (e) { $("countryBox").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`; return; }
  const bot = d.bot ? `https://t.me/${encodeURIComponent(d.bot)}?start=phone` : "";
  $("countryBox").innerHTML = `<h2 class="serif">Из какой страны вы работаете?</h2>
    <p class="ver">Модели доступны по спискам стран их поставщиков: пульт покажет то, что разрешено для вашей страны.</p>
    <div class="cc-grid" role="group" aria-label="Страна">${d.options.map((o) => `<button data-cc="${esc(o.code)}" class="${o.code === d.chosen ? "on" : ""}" aria-pressed="${o.code === d.chosen}">${esc(o.name)}<span class="code">${esc(o.code)}</span></button>`).join("")}</div>
    <div class="field"><label for="ccCode">Другая страна <span class="opt">— код из двух букв (ISO 3166-1)</span></label>
      <div class="inp"><input id="ccCode" maxlength="2" autocomplete="off" autocapitalize="characters" placeholder="например, CH" value="${d.chosen && !d.options.some((o) => o.code === d.chosen) ? esc(d.chosen) : ""}"><button class="btn sm" id="ccGo" style="width:auto">Выбрать</button></div></div>
    <div class="cc-sig">${ic("phone")}<div><b>Номер телефона:</b> ${d.phone ? `подтверждён · код страны ${esc(d.phone_cc || "не определён")}` : "не подтверждён"}
      <div class="hint">Подтвердите номер в боте: «Поделиться номером» — хранится только код страны и хеш номера.${bot ? ` <a href="${bot}" target="_blank" rel="noopener">Открыть бота</a>` : ""}</div></div></div>
    <div class="cc-sig">${ic("globe")}<div><b>Страна по IP:</b> ${ipMark(d)}<div class="hint">Сверяется при каждом входе; адрес не сохраняется — только код страны.</div></div></div>
    ${d.mismatch ? `<div class="result wait">${ic("warn")}<span>Признаки страны не совпадают — доступны только сервисы, разрешённые для всех: ${esc(d.effective.join(", "))}.</span></div>` : ""}
    <div id="ccResult"></div>`;
  const choose = async (code, btn) => busy(btn, "Сохраняю…", async () => {
    try { await api("/api/country", { code }); haptic("notificationOccurred", "success"); if (change) toast("Страна: " + code.toUpperCase()); await start(); }
    catch (err) { $("ccResult").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(err.message)}</span></div>`; }
  });
  $("countryBox").querySelectorAll("[data-cc]").forEach((b) => (b.onclick = () => choose(b.dataset.cc, b)));
  $("ccGo").onclick = (e) => choose($("ccCode").value.trim(), e.currentTarget);
  $("ccCode").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); $("ccGo").click(); } };
}
$("getCode").onclick = (e) => requestCode(e.target);
$("tryDemo").onclick = () => { location.href = "/?demo"; };
// Вход «через Telegram»: ссылка на бота → человек жмёт «Start» и «Войти» у себя → браузер сам замечает и входит.
let tgTimer = null;
$("tgLogin").onclick = (e) => busy(e.currentTarget, LL("login.preparing", "Готовлю вход…"), async () => {
  try {
    const d = await api("/api/login/tg", INVITE ? { invite: INVITE } : {});
    tg?.initData ? tg.openTelegramLink(d.link) : window.open(d.link, "_blank");   // в браузере — новой вкладкой, не уходя со страницы
    $("tgWait").hidden = false;
    $("tgWait").innerHTML = `<div class="result wait">${ic("wait")}<span>${esc(LL("login.wait", "В Telegram нажмите «Запустить» (Start), затем «Войти». Жду подтверждения…"))}</span></div>
      <p class="note" style="margin:6px 2px">${esc(LL("login.wait.note", "Не открылся Telegram или нет кнопки? Внизу чата с ботом нажмите «Запустить» (Start) — даже если бот уже запущен."))}</p>
      <a class="btn ghost" href="${esc(d.link)}" target="_blank" rel="noopener">${ic("ext")}${esc(LL("login.again", "Открыть Telegram ещё раз"))}</a>`;
    clearInterval(tgTimer); const t0 = Date.now();
    tgTimer = setInterval(async () => {
      if (Date.now() - t0 > d.ttl * 1000) { clearInterval(tgTimer); $("tgWait").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(LL("login.expired", "Ссылка устарела — нажмите «Войти через Telegram» ещё раз."))}</span></div>`; return; }
      try {
        const r = await api("/api/login/tg?id=" + encodeURIComponent(d.id));
        if (r.state === "ok") { clearInterval(tgTimer); $("tgWait").hidden = true; haptic("notificationOccurred", "success"); await start(); }
        else if (r.state === "2fa") { clearInterval(tgTimer); $("tgWait").hidden = true; askSecond(r); }
        else if (r.state !== "wait") { clearInterval(tgTimer); $("tgWait").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(r.state === "no" ? LL("login.rejected", "Вход отклонён в Telegram.") : LL("login.restart", "Ссылка устарела — начните заново."))}</span></div>`; }
      } catch (err) { /* сеть моргнула — следующая попытка через 2 с */ }
    }, 2000);
  } catch (err) { $("loginResult").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(err.message)}</span></div>`; }
});
$("resend").onclick = (e) => requestCode(e.target);
async function requestCode(btn) {
  await busy(btn, "Отправляю…", async () => {
    try {
      loginId = (await api("/api/login/start", {})).id;
      $("loginStep1").hidden = true; $("loginStep2").hidden = false; $("code").value = ""; $("code").focus();
      $("loginResult").innerHTML = `<div class="result ok">${ic("check")}<span>Код отправлен в Telegram.</span></div>`;
    } catch (e) { $("loginResult").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`; }
  });
}
// Ключ входа (passkey, WebAuthn): JSON-опции сервера → navigator.credentials и обратно. Вручную, без
// parseCreationOptionsFromJSON/toJSON — их нет в старых Safari и Chrome. В Telegram Mini App ключи не работают
// (на iPhone WebAuthn во встроенном окне недоступен) — там кнопку прячем и просим открыть панель в браузере.
const b64uToBuf = (v) => Uint8Array.from(atob(v.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(v.length / 4) * 4, "=")), (c) => c.charCodeAt(0)).buffer;
function bufToB64u(buf) {
  if (!buf) return "";
  let bin = ""; for (const b of new Uint8Array(buf)) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
const passkeyHere = () => typeof window.PublicKeyCredential === "function" && !!navigator.credentials;
const passkeyOk = () => passkeyHere() && !tg?.initData;
const pkList = (xs) => (xs || []).map((c) => ({ ...c, id: b64uToBuf(c.id) }));
const pkCreation = (j) => ({ ...j, challenge: b64uToBuf(j.challenge), user: { ...j.user, id: b64uToBuf(j.user.id) }, excludeCredentials: pkList(j.excludeCredentials) });
const pkRequest = (j) => ({ ...j, challenge: b64uToBuf(j.challenge), allowCredentials: pkList(j.allowCredentials) });
function pkJson(cred) {                           // ответ устройства → JSON, который понимает сервер (py_webauthn)
  if (!cred) return {};
  const r = cred.response, out = { id: cred.id, rawId: bufToB64u(cred.rawId), type: cred.type,
    clientExtensionResults: cred.getClientExtensionResults?.() ?? {}, authenticatorAttachment: cred.authenticatorAttachment ?? undefined,
    response: { clientDataJSON: bufToB64u(r.clientDataJSON) } };
  if (r.attestationObject) { out.response.attestationObject = bufToB64u(r.attestationObject); out.response.transports = typeof r.getTransports === "function" ? r.getTransports() : []; }
  if (r.authenticatorData) { out.response.authenticatorData = bufToB64u(r.authenticatorData); out.response.signature = bufToB64u(r.signature); out.response.userHandle = r.userHandle ? bufToB64u(r.userHandle) : null; }
  return out;
}
const pkCall = (kind, publicKey) => DEMO ? Promise.resolve(null) : navigator.credentials[kind]({ publicKey });   // демо: без устройства
function pkError(e) {
  if (e?.name === "NotAllowedError" || e?.name === "AbortError") return "Отменено или время вышло — попробуйте ещё раз.";
  if (e?.name === "InvalidStateError") return "Этот ключ уже сохранён на этом устройстве.";
  if (e?.name === "SecurityError") return "Адрес панели не совпадает с настройкой ключей на сервере (rp_id).";
  if (e?.name === "NotSupportedError") return "Это устройство не умеет ключи входа — войдите через Telegram.";
  return e?.message || "Не получилось";
}
$("pkLogin").onclick = (e) => busy(e.currentTarget, "Жду ключ…", async () => {
  try {
    const r = await api("/api/login/passkey/options", {});
    const cred = await pkCall("get", pkRequest(r.options));
    const d = await api("/api/login/passkey/verify", { id: r.id, credential: pkJson(cred) });
    if (d.state === "2fa") return askSecond(d);
    haptic("notificationOccurred", "success"); await start();
  } catch (err) { loginMsg(false, pkError(err)); }
});
// Вход через Google и Яндекс ID (oidc.py): переход на сайт провайдера и обратно. В Telegram — во внешнем браузере
// (Google не пускает во встроенные окна): вход и панель продолжаются там. Второй фактор с почты возвращается во фрагменте.
function oidcGo(p) {
  const url = `/api/login/oidc/${p}/start`, name = p === "google" ? "Google" : LL("login.yandex.name", "Яндекс ID");
  if (DEMO) return loginMsg(true, LL("login.oidc.demo", "В демо вход не выполняется: на пульте здесь откроется сайт {name}.").replace("{name}", name));
  if (tg?.initData) { tg.openLink(location.origin + url); return loginMsg(true, LL("login.oidc.opened", "Открыли браузер: войдите там через {name} — панель откроется в браузере.").replace("{name}", name)); }
  location.href = url;
}
$("googleLogin").onclick = () => oidcGo("google");
$("yandexLogin").onclick = () => oidcGo("yandex");
function oidcReturn() {
  const h = new URLSearchParams(location.hash.slice(1));
  if (!h.get("2fa")) return;
  history.replaceState(null, "", location.pathname + location.search);
  askSecond({ id: h.get("2fa"), to: h.get("to") || "вашу почту" });
}
// Вход по коду на почту: адрес → код из письма. Ответ одинаковый, привязан адрес или нет.
let emTimer = null;
$("emailLogin").onclick = () => { loginPane("loginEmail"); $("emCodeBox").hidden = true; $("emAddr").focus(); };
document.querySelectorAll("[data-login-back]").forEach((b) => (b.onclick = () => loginPane("loginStep1")));
function emCountdown(sec) {                       // «Прислать новый код» — не раньше чем через минуту
  clearInterval(emTimer); const b = $("emResend"), until = Date.now() + sec * 1000;
  const tick = () => { const left = Math.ceil((until - Date.now()) / 1000); b.disabled = left > 0; b.textContent = left > 0 ? `Прислать новый код — через ${left} с` : "Прислать новый код"; if (left <= 0) clearInterval(emTimer); };
  tick(); emTimer = setInterval(tick, 1000);
}
async function emailSend(btn) {
  const email = $("emAddr").value.trim();
  if (!email) return $("emAddr").focus();
  await busy(btn, "Отправляю…", async () => {
    try {
      const d = await api("/api/login/email/start", { email });
      $("emCodeBox").hidden = false; $("emCode").value = ""; $("emCode").focus();
      loginMsg(true, d.message); emCountdown(d.resend_in || 60);
    } catch (e) { loginMsg(false, e.message); }
  });
}
$("emSend").onclick = (e) => emailSend(e.currentTarget);
$("emResend").onclick = (e) => emailSend(e.currentTarget);
$("emAddr").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); $("emSend").click(); } };
$("emCode").addEventListener("input", () => { $("emCode").value = $("emCode").value.replace(/\D/g, "").slice(0, 6); if ($("emCode").value.length === 6) $("emEnter").click(); });
$("emEnter").onclick = (e) => busy(e.currentTarget, "Проверяю…", async () => {
  try { await api("/api/login/email/verify", { email: $("emAddr").value.trim(), code: $("emCode").value }); clearInterval(emTimer); loginPane("loginStep1"); await start(); }
  catch (err) { loginMsg(false, err.message); }
});
// Второй фактор: вход через Telegram подтверждён, но человек включил «код с почты после входа».
let tfId = "";
function askSecond(r) {
  tfId = r.id; loginPane("login2fa"); $("tfCode").value = "";
  $("tfHint").textContent = `Для вашего входа включён второй фактор: код отправлен на ${r.to}. Он действует 10 минут.`;
  $("tfCode").focus();
}
$("tfCode").addEventListener("input", () => { $("tfCode").value = $("tfCode").value.replace(/\D/g, "").slice(0, 6); if ($("tfCode").value.length === 6) $("tfEnter").click(); });
$("tfEnter").onclick = (e) => busy(e.currentTarget, "Проверяю…", async () => {
  try { await api("/api/login/2fa", { id: tfId, code: $("tfCode").value }); loginPane("loginStep1"); await start(); }
  catch (err) { loginMsg(false, err.message); }
});
$("code").addEventListener("input", () => { $("code").value = $("code").value.replace(/\D/g, "").slice(0, 6); if ($("code").value.length === 6) $("enter").click(); });
$("enter").onclick = (e) => busy(e.target, "Проверяю…", async () => {
  try { await api("/api/login/verify", { id: loginId, code: $("code").value }); $("loginResult").innerHTML = ""; await start(); }
  catch (err) { $("loginResult").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(err.message)}</span></div>`; }
});
