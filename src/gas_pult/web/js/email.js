// «Почта для входа и оповещений» (настройки) — часть по требованию (#191): вынесена из ядра, открывается редко.

async function emailSheet() {
  let d; try { d = await api("/api/email"); } catch (e) { return toast(e.message, 4000); }
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("settings.email");
  let step = d.address ? "view" : "addr", addr = "", timer = null;
  const err = (t) => { const n = bg.querySelector("#emsErr"); if (n) { n.textContent = t; n.style.color = "var(--status-danger)"; } };
  const tog = (k, icon, label, sub) => `<button data-em="${k}" class="${d[k] ? "on" : ""}" aria-pressed="${!!d[k]}">${ic(icon)}<span>${esc(label)}<small>${esc(sub)}</small></span>${d[k] ? ic("check") : ""}</button>`;
  const paint = () => {
    const body = !d.enabled ? `<p class="note" style="margin:4px 16px 8px">Почта на этом пульте не настроена. Владелец включает её в config.toml (секция [email]) — инструкция в docs/AUTH.md.</p>`
      : step === "view" ? `<p class="note" style="margin:4px 16px 4px">Привязана: <b>${esc(d.address)}</b>${d.at ? " · " + ccDate(d.at) : ""}. По ней можно войти в пульт кодом из письма.</p>
          ${tog("second_factor", "lock", "Код с почты после входа через Telegram", "второй фактор: без кода из письма вход не завершится")}
          ${tog("notify", "bell", "Оповещения на почту", "письмо, когда сессия встала на паузу по расходу")}
          <button data-em="change">${ic("edit")}<span>Сменить адрес</span></button>
          <button data-em="remove" class="danger">${ic("power")}<span>Отвязать почту<small>вход по почте и письма перестанут работать</small></span></button>`
      : `<div class="field" style="margin:4px 16px 10px"><label for="emsAddr">Адрес почты</label><input id="emsAddr" type="email" inputmode="email" autocomplete="email" autocapitalize="off" spellcheck="false" maxlength="254" placeholder="name@example.com" value="${esc(addr)}"></div>
         ${step === "code" ? `<div class="field" style="margin:0 16px 0"><label for="emsCode">Код из письма</label><input id="emsCode" class="code-input" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="••••••"></div>` : ""}
         <p class="note" id="emsErr" style="margin:8px 16px 0">${step === "code" ? "Код отправлен на " + esc(addr) + ". Он действует 10 минут." : "Пришлём код, чтобы убедиться, что адрес ваш."}</p>
         <div class="row2"><button class="btn ghost" data-close>Отмена</button><button class="btn" id="emsGo">${step === "code" ? "Подтвердить" : "Прислать код"}</button></div>`;
    bg.innerHTML = `<div class="sheet" role="dialog"><h3>Почта для входа и оповещений</h3>${body}${d.enabled && step === "view" || !d.enabled ? '<button class="cancel" data-close>Закрыть</button>' : ""}</div>`;
    const go = bg.querySelector("#emsGo");
    if (go) go.onclick = () => busy(go, "Минуту…", async () => {
      try {
        if (step === "addr") { addr = bg.querySelector("#emsAddr").value.trim(); await api("/api/email/bind", { email: addr }); step = "code"; paint(); bg.querySelector("#emsCode").focus(); }
        else { d = await api("/api/email/confirm", { email: bg.querySelector("#emsAddr").value.trim(), code: bg.querySelector("#emsCode").value }); step = "view"; paint(); toast("Почта привязана"); haptic("notificationOccurred", "success"); }
      } catch (e) { err(e.message); }
    });
    const inp = bg.querySelector("#emsCode") || bg.querySelector("#emsAddr");
    if (inp) inp.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); go.click(); } };
  };
  bg.addEventListener("click", async (e) => {
    if (e.target === bg || e.target.closest("[data-close]")) { clearInterval(timer); return bg.remove(); }
    const b = e.target.closest("[data-em]"); if (!b) return;
    const k = b.dataset.em;
    try {
      if (k === "change") { step = "addr"; addr = ""; return paint(); }
      if (k === "remove") return confirmDanger("Отвязать почту? Вход по почте и письма перестанут работать.", async () => { try { d = await api("/api/email/remove", {}); step = "addr"; paint(); toast("Почта отвязана"); } catch (x) { toast(x.message, 4000); } });
      d = await api("/api/email/options", { [k]: !d[k] }); paint();
    } catch (x) { toast(x.message, 4000); }
  });
  paint(); document.body.append(bg);
}

// ---------- настройки ----------
// «Обозначения»: что значат точки, цвета и значки панели — одним экраном (в настройках и в шторке сессий).

Object.assign(window, { emailSheet });
