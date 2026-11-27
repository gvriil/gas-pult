// Вход через Telegram: ссылка на бота → человек жмёт «Запустить» (Start) и «Войти» → браузер замечает и входит.
// Штаб 22.11: тестировщик на Mac нажал «Войти через Telegram» — ссылка t.me не открыла Telegram (или START не нажали),
// страница 5 минут молча ждала. Теперь: через WARN секунд — «Telegram не ответил» и запасные пути (ещё раз, приложение
// tg://, QR для телефона, новый код); через срок входа (ttl, webauth.LOGIN_TTL) — «Время вышло» и опрос стоп.
// Человек с фокус-ссылкой (отметка в localStorage) видит над кнопкой, что вход ему не нужен (focusdev.loginNote).

const WARN = 60;                                    // с: столько ждём подтверждения до подсказки
let timer = null, run = 0;

const box = () => $("tgWait");
const stop = () => { clearInterval(timer); timer = null; };

function paint(d, state) {
  const slow = state === "slow";
  box().hidden = false;
  box().innerHTML = state === "expired"
    ? `<div class="result bad">${ic("warn")}<span>${esc(LL("login.timeout", "Время вышло. Вход не подтвердили в Telegram."))}</span></div>
      <button class="btn" type="button" data-tg="again">${ic("refresh", "s16")}${esc(LL("login.restart.btn", "Начать заново"))}</button>`
    : `<div class="result ${slow ? "bad" : "wait"}">${ic(slow ? "warn" : "wait")}<span>${esc(slow
      ? LL("login.slow", "Telegram не ответил. Проверьте, что открылся чат с ботом и нажата кнопка «Запустить».")
      : LL("login.wait", "В Telegram нажмите «Запустить» (Start), затем «Войти». Жду подтверждения…"))}</span></div>
      <p class="note" style="margin:6px 2px">${esc(slow ? LL("login.slow.note", "Не открывается? Попробуйте другой способ:") : LL("login.wait.note", "Не открылся Telegram или нет кнопки? Внизу чата с ботом нажмите «Запустить» (Start) — даже если бот уже запущен."))}</p>
      <a class="btn ghost" href="${esc(d.link)}" target="_blank" rel="noopener">${ic("ext")}${esc(LL("login.again", "Открыть Telegram ещё раз"))}</a>
      ${d.app ? `<a class="btn ghost" href="${esc(d.app)}">${ic("phone")}${esc(LL("login.app", "Открыть приложение Telegram"))}</a>` : ""}
      ${d.qr ? `<button class="btn ghost" type="button" data-tg="qr">${ic("qr")}${esc(LL("login.qr", "Показать код для телефона — наведите камеру"))}</button><img class="focus-qr" data-tg-qr hidden alt="QR-код входа через Telegram" src="${esc(d.qr)}">` : ""}
      ${slow ? `<button class="btn ghost" type="button" data-tg="again">${ic("refresh", "s16")}${esc(LL("login.resend.tg", "Отправить ещё раз (новый код)"))}</button>` : ""}`;
  box().onclick = (e) => {
    const b = e.target.closest("[data-tg]"); if (!b) return;
    if (b.dataset.tg === "qr") { const q = box().querySelector("[data-tg-qr]"); q.hidden = !q.hidden; return; }
    if (b.dataset.tg === "again") return busy(b, LL("login.preparing", "Готовлю вход…"), start);
  };
}

export async function start() {
  stop();
  const me = ++run;
  let d;
  try { d = await api("/api/login/tg", INVITE ? { invite: INVITE } : {}); }
  catch (err) { $("loginResult").innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(err.message)}</span></div>`; return; }
  if (me !== run) return;
  tg?.initData ? tg.openTelegramLink(d.link) : window.open(d.link, "_blank");   // в браузере — новой вкладкой
  const t0 = Date.now(), ttl = (d.ttl || 300) * 1000;
  let shown = "wait";
  paint(d, shown);
  const tick = async () => {
    const left = Date.now() - t0;
    if (left > ttl) { stop(); return paint(d, "expired"); }      // вкладка в фоне: таймер редкий — срок по часам
    if (left > WARN * 1000 && shown === "wait") paint(d, (shown = "slow"));
    if (DEMO && !params.has("tgok")) return;                       // демо: подтверждения нет — видно подсказки
    try {
      const r = await api("/api/login/tg?id=" + encodeURIComponent(d.id));
      if (me !== run) return;
      if (r.state === "ok") { stop(); box().hidden = true; haptic("notificationOccurred", "success"); await window.start(); }
      else if (r.state === "2fa") { stop(); box().hidden = true; askSecond(r); }
      else if (r.state !== "wait") { stop(); box().innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(r.state === "no" ? LL("login.rejected", "Вход отклонён в Telegram.") : LL("login.restart", "Ссылка устарела — начните заново."))}</span></div>`; }
    } catch (err) { /* сеть моргнула — следующая попытка через 2 с */ }
  };
  timer = setInterval(tick, 2000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden && timer && me === run) tick(); }, { once: true });
}
// для проверки в демо: ?demo&view=login&tgwait=slow|expired — сразу нужное состояние (снимки без ожидания)
export function demoState(state) {
  const d = { link: "https://t.me/demo_bot?start=login_demo", app: "tg://resolve?domain=demo_bot&start=login_demo", qr: "", ttl: 300 };
  paint(d, state);
}
