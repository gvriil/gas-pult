// Согласие на обработку персональных данных по фокус-ссылке (аудит 24.11). Точка — первое открытие ссылки
// (POST /api/focus/open): сервер не привязывает устройство и не принимает ни сообщений, ни голоса, ни файлов, пока
// человек не отметил отдельную галочку. Без галочки «Продолжить» неактивна; сервер тоже отказывает (409 code=privacy).
// Документы — в новой вкладке: страница ссылки остаётся на месте. ask(token) → ответ /api/focus/open (как без согласия).

document.head.insertAdjacentHTML("beforeend", `<style>
  .pv-box { max-width: 440px; width: 100%; text-align: left; }
  .pv-box > .i { display: block; margin: 0 auto; }
  .pv-box h2 { text-align: center; }
  .pv-box p { margin: 0 0 12px; color: var(--text-secondary); }
  .pv-agree { display: flex; align-items: flex-start; gap: 12px; margin: 8px 0 12px; padding: 14px; cursor: pointer;
    border: 1px solid var(--border-subtle); border-radius: 8px; background: var(--bg-subtle); color: var(--text-primary); }
  .pv-agree input { flex: none; width: 22px; height: 22px; margin: 1px 0 0; accent-color: var(--accent-primary); cursor: pointer; }
  .pv-box a { color: var(--accent-primary); }
  .pv-box .btn { width: 100%; margin: 4px 0 0; }
  .pv-box .err { color: var(--status-danger); margin: 8px 0 0; }
</style>`);

export function ask(token) {
  return new Promise((resolve, reject) => {
    const d = document.createElement("div");
    d.id = "focusPriv"; d.className = "focus-end";                 // не #focusEnd: api() считает его «чат завершён»
    d.setAttribute("role", "dialog"); d.setAttribute("aria-modal", "true"); d.setAttribute("aria-labelledby", "pvTitle");
    d.innerHTML = `<div class="pv-box">${ic("lock")}<h2 class="serif" id="pvTitle">Перед началом</h2>
      <p>В этом чате вы будете писать сообщения, а при желании — отправлять голос и файлы. Чтобы мы могли их обработать, нужно ваше согласие.</p>
      <label class="pv-agree"><input type="checkbox" id="pvAgree"><span>Согласен(на) на обработку персональных данных по <a href="/privacy" target="_blank" rel="noopener">Политике</a></span></label>
      <p class="note">Документы откроются в новой вкладке: <a href="/privacy" target="_blank" rel="noopener">Политика обработки персональных данных</a> · <a href="/terms" target="_blank" rel="noopener">Условия использования</a></p>
      <button class="btn" type="button" id="pvGo" disabled>Продолжить</button><p class="err" id="pvErr" role="alert" hidden></p></div>`;
    document.body.append(d);
    const box = d.querySelector("#pvAgree"), go = d.querySelector("#pvGo"), err = d.querySelector("#pvErr");
    box.addEventListener("change", () => { go.disabled = !box.checked; err.hidden = true; });
    go.addEventListener("click", async () => {
      if (!box.checked) return;
      go.disabled = true;
      try { const o = await api("/api/focus/open", { token, privacy: true }); d.remove(); resolve(o); }
      catch (e) {
        if (e.code === "focus_gone" || /Чат завершён/.test(e.message)) { d.remove(); return reject(e); }
        err.textContent = e.message; err.hidden = false; go.disabled = false;
      }
    });
    box.focus();
  });
}
