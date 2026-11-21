// Шторка «Подтвердите кодом»: код уходит сразу (бот в Telegram или почта), 6 цифр — проверка. Одна на все запросы,
// что ждут подтверждения; «Отмена» — ошибка у кнопки, которая его запросила.
export function open() {
  return new Promise((ok, no) => {
    const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("sheet.confirm");
    bg.innerHTML = `<div class="sheet confirm-code" role="dialog" aria-labelledby="cfTitle"><h3 id="cfTitle">Подтвердите кодом</h3>
      <p class="note" style="margin:4px 16px 10px">Это новый вход в панель. Команды на сервере и ввод в терминал — после кода: так чужой вход ничего не запустит. Подтверждение действует до конца этого входа.</p>
      <div class="field" style="margin:0 16px 0"><label for="cfCode">Код</label><input id="cfCode" class="code-input" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="••••••"></div>
      <p class="note" id="cfMsg" role="status" style="margin:8px 16px 0">Отправляю код…</p>
      <div class="row2"><button class="btn ghost" data-close>Отмена</button><button class="btn" id="cfGo">Подтвердить</button></div>
      <button class="btn ghost wide" id="cfBot" hidden style="margin:8px 16px 0;width:calc(100% - 32px)">Открыть чат с ботом</button>
      <button class="btn ghost wide" id="cfAgain" style="margin:8px 16px 0;width:calc(100% - 32px)">Прислать новый код</button></div>`;
    document.body.append(bg);
    const inp = bg.querySelector("#cfCode"), go = bg.querySelector("#cfGo");
    const msg = (t, bad) => { const n = bg.querySelector("#cfMsg"); n.textContent = t; n.style.color = bad ? "var(--status-danger)" : ""; };
    let rid = "";
    let poll = 0;                                     // «✅ Подтвердить вход» в боте — экран закрывается сам
    const done = (err) => { clearInterval(poll); bg.remove(); err ? no(new Error(err)) : ok(); };
    poll = setInterval(() => { if (DEMO || !bg.isConnected) return; api("/api/confirm/check", {}).then((d) => { if (d.ok && bg.isConnected) { toast("Подтверждено в Telegram"); done(); } }, () => {}); }, 2000);
    const send = async () => {
      msg("Отправляю код…");
      try {
        const r = await api("/api/confirm/start", {}); rid = r.id;
        const min = Math.round((r.ttl || 600) / 60);
        const at = r.at ? new Date(r.at * 1000).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) : "";
        msg(r.via === "email" ? `Код отправлен на ${r.to}. Он действует ${min} минут.`
          : `Код отправлен${at ? " в " + at : ""} в Telegram, в чат ${r.chat ? "«" + r.chat + "»" : "с ботом"} — он закреплён сверху. Нажмите там «✅ Подтвердить вход» или введите код. Действует ${min} минут.`);
        const tgb = bg.querySelector("#cfBot");               // не пришёл — открыть чат с ботом (21.11)
        if (r.via !== "email" && r.bot) { tgb.hidden = false; tgb.onclick = () => { const u = "https://t.me/" + r.bot; try { tg?.openTelegramLink ? tg.openTelegramLink(u) : window.open(u, "_blank"); } catch (e) { window.open(u, "_blank"); } }; }
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
