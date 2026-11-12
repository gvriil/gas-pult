// ---------- сеть ----------
// Команды на сервере и ввод в терминал (webapp.CONFIRM): новый вход в браузере — только после кода. Сервер отвечает
// 403 {confirm: "code"} — шторка «Подтвердите кодом», после кода тот же запрос повторяется. Демо: &confirm, код 123456.
const CONFIRM_PATHS = new Set(["/api/run", "/api/run/term", "/api/commands/run", "/api/commands/term", "/api/term/type",
  "/api/term/key", "/api/tty/type", "/api/tty/key"]);
async function api(path, body, raw, extra, signal) {
  if (DEMO && params.has("offline") && start.done) throw Object.assign(new Error("нет сети"), { net: true });
  if (DEMO && params.has("confirm") && !demoApi.confirmed && CONFIRM_PATHS.has(path)) { await confirmCode(); return api(path, body, raw, extra, signal); }
  if (DEMO && params.get("slow") && (!start.done || path.startsWith("/api/history"))) await new Promise((ok) => setTimeout(ok, +params.get("slow")));   // ?demo&slow=1500 — медленная сеть: загрузка и переписка (скелетоны)
  if (DEMO) { lastOk = Date.now(); return demoApi(path, body); }
  if (FOCUS && $("focusEnd")) throw new Error("Сессия завершена");   // ссылка погасла — опросы больше не шлём
  const headers = FOCUS ? { "X-Gp-Focus": "1", ...(extra || {}) } : { "X-Telegram-Init-Data": tg?.initData || "", ...(extra || {}) };
  if (body && !raw) headers["Content-Type"] = "application/json";
  if (raw) headers["Content-Type"] = raw;
  let r;
  try { r = await fetch(path, { method: body ? "POST" : "GET", headers, credentials: "same-origin", body: body ? (raw ? body : JSON.stringify(body)) : undefined, signal }); }
  catch (e) { if (signal?.aborted) throw e; throw Object.assign(new Error("нет связи с сервером"), { net: true }); }   // сеть, а не ошибка сервера
  if (FOCUS && r.status === 410) { const err = await r.json().catch(() => ({})); focusEnd(err.error); throw new Error(err.error || "Сессия завершена"); }
  if (r.status === 401 && !path.startsWith("/api/login")) { showLogin(); throw new Error("нужен вход"); }   // 403 — не хватает прав: просто ошибка
  lastOk = Date.now();                              // сервер ответил — связь есть, даже если ответ «ошибка»
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    if (r.status === 403 && err.code === "terms") showTerms();      // условия ещё не приняты (или обновились)
    if (r.status === 403 && err.code === "country") showCountry();  // страна ещё не выбрана
    if (r.status === 403 && err.confirm === "code") { await confirmCode(); return api(path, body, raw, extra, signal); }
    throw new Error(err.error || "ошибка " + r.status);
  }
  return (r.headers.get("Content-Type") || "").startsWith("application/json") ? r.json() : r.blob();
}
// Шторка «Подтвердите кодом»: код уходит сразу (бот в Telegram или почта), 6 цифр — проверка. Одна на все запросы,
// что ждут подтверждения; «Отмена» — ошибка у кнопки, которая его запросила.
let confirmWait = null;
function confirmCode() {
  return confirmWait ||= new Promise((ok, no) => {
    const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.confirm");
    bg.innerHTML = `<div class="sheet confirm-code" role="dialog" aria-labelledby="cfTitle"><h3 id="cfTitle">Подтвердите кодом</h3>
      <p class="note" style="margin:4px 16px 10px">Это новый вход в панель. Команды на сервере и ввод в терминал — после кода: так чужой вход ничего не запустит. Подтверждение действует до конца этого входа.</p>
      <div class="field" style="margin:0 16px 0"><label for="cfCode">Код</label><input id="cfCode" class="code-input" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="••••••"></div>
      <p class="note" id="cfMsg" role="status" style="margin:8px 16px 0">Отправляю код…</p>
      <div class="row2"><button class="btn ghost" data-close>Отмена</button><button class="btn" id="cfGo">Подтвердить</button></div>
      <button class="btn ghost wide" id="cfAgain" style="margin:8px 16px 0;width:calc(100% - 32px)">Прислать новый код</button></div>`;
    document.body.append(bg);
    const inp = bg.querySelector("#cfCode"), go = bg.querySelector("#cfGo");
    const msg = (t, bad) => { const n = bg.querySelector("#cfMsg"); n.textContent = t; n.style.color = bad ? "var(--status-danger)" : ""; };
    let rid = "";
    const done = (err) => { bg.remove(); confirmWait = null; err ? no(new Error(err)) : ok(); };
    const send = async () => {
      msg("Отправляю код…");
      try {
        const r = await api("/api/confirm/start", {}); rid = r.id;
        const min = Math.round((r.ttl || 600) / 60);
        msg(r.via === "email" ? `Код отправлен на ${r.to}. Он действует ${min} минут.` : `Код прислал бот в Telegram. Он действует ${min} минут.`);
        inp.focus();
      } catch (e) { msg(e.message, true); }
    };
    go.onclick = () => busy(go, "Проверяю…", async () => {
      try { await api("/api/confirm/verify", { id: rid, code: inp.value }); haptic("notificationOccurred", "success"); toast("Подтверждено"); done(); }
      catch (e) { msg(e.message, true); inp.select(); }
    });
    inp.addEventListener("input", () => { inp.value = inp.value.replace(/\D/g, "").slice(0, 6); if (inp.value.length === 6) go.click(); });
    inp.onkeydown = (e) => { if (e.key === "Enter") go.click(); };
    bg.querySelector("#cfAgain").onclick = send;
    bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) done("Не выполнено: нужен код подтверждения"); });
    send();
  });
}
