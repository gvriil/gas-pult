// «Интеграции» → «Календари» (владелец): секрет вставляют в поле — сервер кладёт его в файл 0600 коннектора
// календаря и сразу проверяет (calkeys.py). Значение обратно не приходит: только «подключено» и что проверено.
// Google — «Секретный адрес в формате iCal» (только чтение). iCloud — пресет «Календарь iCloud» выше (одно место).

const HOW = {
  google: "Google Календарь на компьютере → ⚙ Настройки → слева ваш календарь → «Интеграция календаря» → «Секретный адрес в формате iCal» → скопировать.",
};

export async function calendarsSection() {
  let d; try { d = await api("/api/calendars/keys"); } catch (e) { return ""; }
  return `<div class="section">Календари</div><p class="note">Для утреннего брифинга и агентов. iCloud — сервис «Календарь iCloud» выше. Секрет хранится на сервере в закрытом файле и больше нигде не показывается.</p>
    <div class="tiles">${d.calendars.map((c) => `<button class="tile${c.on ? " on" : ""}" data-calkey="${esc(c.kind)}"><span class="mono">${ic("cal")}</span><span>${esc(c.title)}</span><small>${c.on ? "подключено" : "не подключено"}</small></button>`).join("")}</div>`;
}

export function calendarSheet(kind, on, done) {
  const fields = `<div class="field"><label for="ckUrl">Секретный адрес в формате iCal</label><input id="ckUrl" type="password" autocomplete="off" spellcheck="false" placeholder="https://calendar.google.com/…/basic.ics"></div>`;
  const bg = sSheet(hv("int.calendar"), "Google Календарь", `<p class="note">${esc(HOW[kind])}</p>${fields}
    <button class="btn wide" type="button" data-cksave="1">${ic("check")}${on ? "Заменить и проверить" : "Подключить и проверить"}</button>
    ${on ? `<button class="btn ghost wide" type="button" data-ckdel="1" style="margin-top:8px">${ic("trash")}Отключить</button>` : ""}
    <div id="ckOut"></div>
    <p class="note">Только чтение: пульт видит события, но не меняет их. Данные календаря получают только модели, которые на них не учатся.</p>`,
    async (b) => {
      const out = $("ckOut");
      if (b.dataset.ckdel) {
        try { await api("/api/calendars/key/remove", { kind }); bg.remove(); toast("Календарь отключён"); done?.(); } catch (e) { toast(e.message, 4000); }
        return;
      }
      if (!b.dataset.cksave) return;
      const body = { kind, url: $("ckUrl").value };
      b.disabled = true; out.innerHTML = `<div class="result wait">${ic("wait")}<span>Проверяю подключение…</span></div>`;
      try {
        const r = await api("/api/calendars/key", body);
        bg.querySelectorAll("input").forEach((x) => { x.value = ""; });           // секрет не держим в странице
        out.innerHTML = `<div class="result ok">${ic("check")}<span>Подключено — ${esc(r.checked)}.</span></div>`;
        haptic("notificationOccurred", "success"); done?.();
      } catch (e) { b.disabled = false; out.innerHTML = `<div class="result bad">${ic("warn")}<span>${esc(e.message)}</span></div>`; }
    });
  setTimeout(() => bg.querySelector("input")?.focus(), 60);
}
