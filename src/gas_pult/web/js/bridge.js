// «Компьютеры — ваш браузер» (настройки) — часть по требованию (#191). Решение владельца 16.11: пульт управляет
// браузером пользователя на его компьютере через мост (docs/BRIDGE.md). Здесь: список компьютеров (на связи или нет),
// «Отозвать», «Подключить компьютер» — одноразовый код (10 мин), готовая команда, ссылка на файл моста. QR не нужен:
// команду вводят на том же компьютере, камерой его не сканируют.

const BRIDGE_FILE = "https://raw.githubusercontent.com/gvriil/gas-pult/main/bridge/gas-pult-bridge.mjs";
const ago = (t) => (t ? new Date(t * 1000).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");

async function bridgeSheet() {
  let d;
  try { d = await api("/api/bridge/devices"); } catch (e) { return toast("Компьютеры: " + e.message, 4500); }
  const devs = d.devices || [];
  helpSheet("settings.bridge");
  sheet("Компьютеры — ваш браузер", [
    { info: true, icon: "monitor", label: "Пульт управляет браузером на вашем компьютере",
      sub: "Chrome или Edge, где вы уже вошли в сервисы. Банки и госуслуги выключены — включаете только вы, на компьютере" },
    ...devs.map((x) => ({ label: `${x.name || "компьютер"} · ${x.online ? "на связи" : "не на связи"}`, icon: x.online ? "check" : "monitor",
      sub: `${x.os || ""} · подключён ${ago(x.created)} · был на связи ${ago(x.seen)} — нажмите, чтобы отозвать`,
      run: () => confirmDanger(`Отозвать «${x.name}»? Мост на этом компьютере перестанет работать, подключать — заново.`, async () => {
        try { await api("/api/bridge/revoke", { id: x.id }); toast("Отозвано"); bridgeSheet(); } catch (e) { toast(e.message, 4000); }
      }) })),
    { label: "Подключить компьютер", icon: "plus", sub: "код на 10 минут и команда для компьютера", run: () => bridgePair() },
  ]);
}

async function bridgePair() {
  let c;
  try { c = await api("/api/bridge/pair", {}); } catch (e) { return toast(e.message, 4500); }
  const url = location.origin, cmd = `node gas-pult-bridge.mjs pair ${url} ${c.code}`;
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("settings.bridge");
  bg.innerHTML = `<div class="sheet" role="dialog"><h3>Подключить компьютер</h3>
    <ol style="margin:4px 16px 0;padding-left:20px;line-height:1.5">
      <li>Node.js 22 или новее (Mac: <code>brew install node</code>)</li>
      <li>В Chrome или Edge — расширение «Playwright Extension»</li>
      <li>Файл моста: <a href="${BRIDGE_FILE}" target="_blank" rel="noopener">gas-pult-bridge.mjs</a></li>
      <li>В терминале компьютера, в папке с файлом:</li></ol>
    <div class="field" style="margin:6px 16px 0"><code id="bpCmd" style="display:block;word-break:break-all;padding:8px">${esc(cmd)}</code></div>
    <p class="note" style="margin:6px 16px 0">Код <b>${esc(c.code)}</b> — 10 минут, один раз. Потом: <code>node gas-pult-bridge.mjs</code></p>
    <div class="row2"><button class="btn ghost" data-close>Закрыть</button><button class="btn" id="bpCopy">Скопировать команду</button></div></div>`;
  document.body.append(bg);
  bg.addEventListener("click", (e) => {
    if (e.target === bg || e.target.closest("[data-close]")) { bg.remove(); bridgeSheet(); }
    if (e.target.closest("#bpCopy")) copyText(cmd, "Команда скопирована");
  });
}

Object.assign(window, { bridgeSheet });
