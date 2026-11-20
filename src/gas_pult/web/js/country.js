// Страна человека — экран выбора (решение владельца 20.11: по умолчанию — регион сервера, человека не спрашиваем;
// экран остаётся для правки из «Настроек» и для старых ответов сервера 403 code=country). Вынесено из ядра.
const ccDate = (t) => t ? new Date(t * 1000).toLocaleDateString("ru-RU") : "";
function ipMark(c) {                              // отметка страны по IP — с атрибуцией базы (CC BY 4.0)
  const by = `<a href="${esc(c.attribution_url || "https://db-ip.com")}" target="_blank" rel="noopener">${esc(c.attribution || "IP Geolocation by DB-IP")}</a>`;
  return !c.geoip ? "нет данных — база стран по IP не загружена" : c.ip_cc ? `${esc(c.ip_cc)}${c.ip_at ? " · " + ccDate(c.ip_at) : ""} · ${by}` : `нет данных · ${by}`;
}
export async function open(change) {
  if (view === "country" && !change) return;
  start.poll = null;
  show("country"); $("title").textContent = brandName(); setSub("<span>ваша страна</span>");
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
