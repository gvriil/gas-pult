// Команде нужен ввод (задача 47): окно терминала панели вместо «Выполнить» вслепую. Вынесено из ядра 21.11 (место ядра).
export async function termOpen(btn, path, body, cmd) {
  const go = (confirmed) => busy(btn, "Открываю…", async () => {
    try {
      const r = await api(path, { ...body, confirmed });
      if (r.confirm) return confirmDanger("Команда меняет или удаляет данные:\n\n" + cmd.slice(0, 600) + "\n\nОткрыть в терминале и выполнить?", () => go(true));
      termSheet(r.id);
    } catch (e) { toast(e.message, 5000); }
  });
  return go(false);
}
export function termSheet(id) {
  document.querySelector(".sheet-bg.termsheet")?.remove();
  const inTg = !!tg?.initData;
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.classList.add("termsheet"); bg.dataset.help = hv("cmd.terminal");
  bg.innerHTML = `<div class="sheet" role="dialog"><h3>Терминал</h3>
    <p class="note" style="margin:4px 16px 8px">Команда запущена в окне «gp-term» на сервере. ${inTg ? "Пароль в Telegram не вводим — откройте панель в браузере или терминал (Termius)." : "Спросит пароль — введите его ниже: он уйдёт прямо в окно и нигде не сохранится."}</p>
    <div class="term" style="margin:0 16px"><pre id="twScreen">…</pre></div>
    ${inTg ? `<div class="row2"><button class="btn ghost" data-close>Закрыть</button><button class="btn" id="twBrowser">${ic("ext")}Открыть в браузере</button></div>`
      : `<div class="field" style="margin:10px 16px 0"><input id="twIn" type="password" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="пароль или ответ — Enter отправит"></div>
    <label class="note" style="margin:6px 16px 0;display:flex;gap:6px;align-items:center"><input type="checkbox" id="twShow">показывать, что ввожу</label>
    <p class="note" id="twErr" style="margin:6px 16px 0"></p>
    <div class="row2"><button class="btn ghost" id="twCc">Ctrl+C</button><button class="btn" id="twSend">${ic("key")}Отправить</button></div>`}
    ${ttyOk() ? `<div class="row2"><button class="btn ghost" id="twLive">${ic("term")}Живой терминал: клавиши и вся история</button></div>` : ""}
    <div class="row2"><button class="btn ghost danger" id="twKill">Закрыть окно на сервере</button><button class="btn ghost" data-close>Свернуть</button></div></div>`;
  document.body.append(bg);
  let timer = null, alive = true;
  const stop = () => { clearInterval(timer); const i = $("twIn"); if (i) i.value = ""; bg.remove(); };
  const err = (m) => { const e = $("twErr"); if (e) { e.textContent = m; e.style.color = "var(--status-danger)"; } else toast(m, 4000); };
  const poll = async () => {
    if (!bg.isConnected) return clearInterval(timer);
    try {
      const d = await api("/api/term?id=" + encodeURIComponent(id)); alive = d.alive;
      $("twScreen").textContent = d.alive ? (d.lines || []).slice(-30).join("\n") || "…" : "Окно закрыто — команда завершилась.";
      if (!d.alive) { clearInterval(timer); bg.querySelectorAll("#twIn, #twSend, #twCc, #twKill").forEach((x) => { x.disabled = true; }); }
    } catch (e) { $("twScreen").textContent = e.message; }
  };
  poll(); timer = setInterval(poll, 1500);
  const inp = $("twIn");
  if (inp) {
    inp.focus();
    $("twShow").onchange = (e) => { inp.type = e.target.checked ? "text" : "password"; };
    const send = () => busy($("twSend"), "Отправляю…", async () => {
      try { await api("/api/term/type", { id, text: inp.value }); inp.value = ""; $("twErr").textContent = ""; setTimeout(poll, 600); } catch (e) { err(e.message); }
    });
    $("twSend").onclick = send;
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); send(); } });
    $("twCc").onclick = async () => { try { await api("/api/term/key", { id, key: "C-c" }); setTimeout(poll, 600); } catch (e) { err(e.message); } };
  }
  $("twLive")?.addEventListener("click", () => { stop(); ttyOpen(id); });
  $("twBrowser")?.addEventListener("click", () => openUrl(location.origin + location.pathname + "?term=" + encodeURIComponent(id)));
  $("twKill").onclick = async () => { if (alive) { try { await api("/api/term/close", { id }); } catch (e) { /* окна уже нет */ } } stop(); };
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) stop(); });
}
