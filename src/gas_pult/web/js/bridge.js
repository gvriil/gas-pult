// «Компьютеры — ваш браузер» (настройки) — часть по требованию (#191). Решение владельца 16.11: пульт управляет
// браузером пользователя на его компьютере через мост (docs/BRIDGE.md). Здесь: список компьютеров (на связи или нет),
// «Отозвать», «Подключить компьютер» — одноразовый код (10 мин), готовая команда, ссылка на файл моста. QR не нужен:
// команду вводят на том же компьютере, камерой его не сканируют.
// Фокус-ссылка с «Браузер» (владелец 17.11): та же форма на фокус-странице, но свои пути /api/focus/bridge* — только
// устройства этой ссылки. Владелец видит устройства фокус-пользователей с пометкой «фокус: …» и их журнал.

const BRIDGE_FILE = "https://raw.githubusercontent.com/gvriil/gas-pult/main/bridge/gas-pult-bridge.mjs";
const ago = (t) => (t ? new Date(t * 1000).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");
const B = FOCUS ? { list: "/api/focus/bridge", pair: "/api/focus/bridge/pair", revoke: "/api/focus/bridge/revoke" }
  : { list: "/api/bridge/devices", pair: "/api/bridge/pair", revoke: "/api/bridge/revoke" };

async function bridgeSheet() {
  let d;
  try { d = await api(B.list); } catch (e) { return toast("Компьютеры: " + e.message, 4500); }
  const devs = d.devices || [];
  helpSheet("settings.bridge");
  sheet(FOCUS ? "Ваш браузер" : "Компьютеры — ваш браузер", [
    { info: true, icon: "monitor", label: FOCUS ? "Пульт будет работать в браузере на вашем компьютере" : "Пульт управляет браузером на вашем компьютере",
      sub: (FOCUS ? "Только в этой сессии; другие сессии и владелец пульта ваш браузер не видят. " : "")
        + "Chrome или Edge, где вы уже вошли в сервисы. Банки и госуслуги выключены — включаете только вы, на компьютере" },
    ...devs.map((x) => ({ label: `${x.name || "компьютер"} · ${x.online ? "на связи" : "не на связи"}`, icon: x.online ? "check" : "monitor",
      sub: (x.focus_name ? `фокус: ${x.focus_name} · ` : "") + `${x.os || ""} · подключён ${ago(x.created)} · был на связи ${ago(x.seen)}`,
      run: () => deviceSheet(x) })),
    { label: "Подключить компьютер", icon: "plus", sub: "код на 10 минут и команда для компьютера", run: () => bridgePair() },
  ]);
}

function deviceSheet(x) {
  const revoke = () => confirmDanger(`Отозвать «${x.name}»? Мост на этом компьютере перестанет работать, подключать — заново.`, async () => {
    try { await api(B.revoke, { id: x.id }); toast("Отозвано"); bridgeSheet(); } catch (e) { toast(e.message, 4000); }
  });
  if (FOCUS) return revoke();                           // фокус-пользователю журнал не нужен — сразу отзыв
  sheet(x.name || "компьютер", [
    { label: "Журнал действий", icon: "eye", sub: "что агенты делали в этом браузере: время, действие, адрес", run: () => deviceLog(x) },
    { label: "Отозвать", icon: "x", danger: true, run: revoke },
  ]);
}

async function deviceLog(x) {
  let d;
  try { d = await api("/api/bridge/log?id=" + encodeURIComponent(x.id)); } catch (e) { return toast(e.message, 4500); }
  helpSheet("settings.bridge");
  sheet("Журнал · " + (x.name || "компьютер"), d.log.length ? d.log.map((r) => ({ info: true, icon: r.ok ? "check" : "warn",
    label: `${ago(r.t)} · ${r.tool}`, sub: [r.url, r.err].filter(Boolean).join(" · ") || (r.ok ? "выполнено" : "ошибка") }))
    : [{ info: true, icon: "eye", label: "Действий пока не было" }]);
}

async function bridgePair() {
  let c;
  try { c = await api(B.pair, {}); } catch (e) { return toast(e.message, 4500); }
  const url = location.origin, cmd = `node gas-pult-bridge.mjs pair ${url} ${c.code}`;
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("settings.bridge");
  bg.innerHTML = `<div class="sheet" role="dialog"><h3>Подключить компьютер</h3>
    <ol style="margin:4px 16px 0;padding-left:20px;line-height:1.5">
      <li>Node.js 22 или новее (Mac: <code>brew install node</code>)</li>
      <li>В Chrome или Edge — расширение «Playwright Extension»</li>
      <li>Файл моста: <a href="${BRIDGE_FILE}" target="_blank" rel="noopener">gas-pult-bridge.mjs</a></li>
      <li>В терминале компьютера, в папке с файлом:</li></ol>
    <div class="field" style="margin:6px 16px 0"><code id="bpCmd" style="display:block;word-break:break-all;padding:8px">${esc(cmd)}</code></div>
    <p class="note" style="margin:6px 16px 0">Подключая компьютер, вы принимаете <a href="/terms" target="_blank" rel="noopener">пользовательское соглашение</a>.</p>
    <p class="note" style="margin:6px 16px 0">Код <b>${esc(c.code)}</b> — 10 минут, один раз. Потом: <code>node gas-pult-bridge.mjs</code></p>
    <div class="row2"><button class="btn ghost" data-close>Закрыть</button><button class="btn" id="bpCopy">Скопировать команду</button></div></div>`;
  document.body.append(bg);
  bg.addEventListener("click", (e) => {
    if (e.target === bg || e.target.closest("[data-close]")) { bg.remove(); bridgeSheet(); }
    if (e.target.closest("#bpCopy")) copyText(cmd, "Команда скопирована");
  });
}

Object.assign(window, { bridgeSheet });
