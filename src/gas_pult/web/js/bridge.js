// «Компьютеры» — часть по требованию (#191). Решение владельца 16.11: пульт управляет браузером пользователя на его
// компьютере через мост (docs/BRIDGE.md). Владелец 21.11 («в одну кнопку и понятно»): крупный статус каждого
// компьютера; «Подключить компьютер» → Mac или Windows → одна команда, «Скопировать» и три шага картинками;
// переключатель «Личные данные не уходят модели» (новые — включён); «Ждут вашего «Да»» — что агент хочет нажать или
// выполнить на компьютере, человек отвечает «Да» или «Нет» здесь же.
// Фокус-ссылка с «Браузер» (владелец 17.11): та же форма на фокус-странице, но свои пути /api/focus/bridge* — только
// устройства этой ссылки, без журнала и без «Да» (подтверждает владелец пульта).

const ago = (t) => (t ? new Date(t * 1000).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");
const B = FOCUS ? { list: "/api/focus/bridge", pair: "/api/focus/bridge/pair", revoke: "/api/focus/bridge/revoke", private: "/api/focus/bridge/private" }
  : { list: "/api/bridge/devices", pair: "/api/bridge/pair", revoke: "/api/bridge/revoke", private: "/api/bridge/private" };
const OS = { darwin: "Mac", win32: "Windows", linux: "Linux" };
const PRIVATE_SUB = "Модели уходят только кнопки, ссылки и заголовки страниц. Текст писем и введённое в поля — нет; " +
  "почта, телефоны и номера карт скрыты; снимков экрана нет";
const cmds = (code) => {
  const o = location.origin, q = code ? `?c=${code}` : "";
  return { mac: `curl -fsSL '${o}/api/bridge/install.sh${q}' | bash`, win: `irm '${o}/api/bridge/install.ps1${q}' | iex`,
    mac_remove: `curl -fsSL '${o}/api/bridge/install.sh?do=remove' | bash`, win_remove: `irm '${o}/api/bridge/install.ps1?do=remove' | iex` };
};

const css = document.createElement("style");
css.textContent = `
  .br .br-lead { color: var(--text-secondary); margin: 0 16px 12px; line-height: 1.45; }
  .sheet.br .br-seg, .sheet.br .br-step, .sheet.br .br-wait, .sheet.br .br-live { margin-left: 12px; margin-right: 12px; }
  .br h4 { margin: 14px 16px 8px; font-size: calc(15px * var(--fz, 1)); }
  .sheet.br .br-dev { display: flex; gap: 12px; align-items: center; text-align: left; border: 1px solid var(--border-subtle); border-radius: var(--radius-md);
    background: var(--bg-surface); color: var(--text-primary); padding: 14px; margin: 0 12px 8px; width: calc(100% - 24px); font: inherit; cursor: pointer; }
  .br-dot { flex: none; width: 14px; height: 14px; border-radius: 50%; background: var(--status-idle); }
  .br-dev.on .br-dot { background: var(--status-running); box-shadow: 0 0 0 4px color-mix(in srgb, var(--status-running) 22%, transparent); }
  .br-live .br-dot { background: var(--status-approval); box-shadow: 0 0 0 4px color-mix(in srgb, var(--status-approval) 22%, transparent); animation: pulse 1.4s infinite; }
  .br-dev b { display: block; font-size: calc(18px * var(--fz, 1)); }
  .br-dev.on b { color: var(--status-running); }
  .br-dev .br-name { display: block; margin-top: 2px; } .br-dev small { display: block; color: var(--text-secondary); margin-top: 2px; }
  .br-tag { display: inline-flex; align-items: center; gap: 4px; margin-top: 6px; padding: 2px 8px; border-radius: var(--radius-pill);
    background: var(--accent-soft); color: var(--text-primary); font-size: calc(12px * var(--fz, 1)); }
  .br-tag svg { width: 14px; height: 14px; }
  .sheet.br .btn { justify-content: center; text-align: center; border-radius: var(--radius-pill); background: var(--accent-primary); color: var(--on-accent); font-weight: 600; }
  .sheet.br .btn.ghost { background: transparent; color: var(--accent-primary); border: 1px solid var(--border-subtle); }
  .sheet.br .btn svg { width: 20px; height: 20px; } .sheet.br .btn .i { color: inherit; }
  .sheet.br .br-big { font-size: calc(17px * var(--fz, 1)); padding: 16px 18px; margin: 8px 0 4px; }
  .sheet.br > .br-big { margin: 8px 12px 4px; width: calc(100% - 24px); }
  .br-wait { border: 1px solid var(--status-approval); background: var(--status-approval-bg); border-radius: var(--radius-md); padding: 12px; margin: 0 0 8px; }
  .br-wait p { margin: 0 0 4px; line-height: 1.4; word-break: break-word; } .br-wait small { color: var(--text-secondary); }
  .br-wait .row2 { margin: 10px 0 0; padding: 0; }
  .br-empty { text-align: center; color: var(--text-secondary); padding: 8px 0 4px; }
  .br-seg { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 0 0 12px; }
  .sheet.br .br-seg button { justify-content: center; border: 2px solid var(--border-subtle); background: var(--bg-surface); color: var(--text-primary); border-radius: var(--radius-md);
    padding: 12px; font: inherit; font-size: calc(17px * var(--fz, 1)); font-weight: 600; cursor: pointer; }
  .sheet.br .br-seg button.on { border-color: var(--accent-primary); background: var(--accent-soft); }
  .br-step { display: grid; grid-template-columns: 34px 1fr; gap: 4px 10px; border: 1px solid var(--border-subtle); border-radius: var(--radius-md);
    padding: 12px; margin: 0 0 10px; background: var(--bg-surface); }
  .br-num { width: 30px; height: 30px; border-radius: 50%; background: var(--accent-primary); color: var(--on-accent); display: grid; place-items: center; font-weight: 700; }
  .br-step p { margin: 4px 0 0; line-height: 1.45; font-size: calc(16px * var(--fz, 1)); }
  .br-step > svg { grid-column: 1 / -1; width: 100%; max-width: 420px; height: auto; margin: 8px auto 0; display: block; }
  .br-cmd { grid-column: 1 / -1; font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 13px; background: var(--bg-terminal); color: #E8EAED;
    border-radius: var(--radius-sm); padding: 10px; word-break: break-all; margin-top: 8px; user-select: all; }
  .br-step .btn { grid-column: 1 / -1; }
  .br-live { display: flex; gap: 10px; align-items: center; border-radius: var(--radius-md); padding: 12px; background: var(--bg-subtle); margin: 0 0 10px; }
  .br-live.ok { background: color-mix(in srgb, var(--status-running) 14%, var(--bg-surface)); }
  .br-live.ok b { color: var(--status-running); }
  .br a { color: var(--accent-primary); }
  .br details { margin: 4px 16px 10px; color: var(--text-secondary); } .br summary { cursor: pointer; padding: 6px 0; }
  .br details code { display: block; word-break: break-all; padding: 8px; background: var(--bg-subtle); border-radius: var(--radius-sm); margin: 6px 0; }
  .br-ill .k { fill: var(--bg-subtle); stroke: var(--field-border); } .br-ill .s { fill: var(--bg-canvas); stroke: var(--border-subtle); }
  .br-ill .a { fill: var(--accent-primary); } .br-ill .as { fill: var(--accent-soft); stroke: var(--accent-primary); }
  .br-ill .t { fill: var(--text-primary); font: 600 13px system-ui, sans-serif; } .br-ill .m { fill: var(--text-secondary); font: 12px system-ui, sans-serif; }
  .br-ill .term { fill: var(--bg-terminal); } .br-ill .tt { fill: #8AB4F8; font: 12px ui-monospace, Menlo, monospace; } .br-ill .tw { fill: #E8EAED; font: 12px ui-monospace, Menlo, monospace; }
  .br-ill .ok { fill: var(--status-running); } .br-ill .on-a { fill: var(--on-accent); font: 700 13px system-ui, sans-serif; }
  .br-ill .ln { stroke: var(--text-secondary); stroke-width: 2; fill: none; }
`;
document.head.append(css);

// Схемы шагов — свои рисунки, не снимки экрана систем
const KEY = (x, y, w, label) => `<rect class="k" x="${x}" y="${y}" width="${w}" height="34" rx="7"/><text class="t" x="${x + w / 2}" y="${y + 22}" text-anchor="middle">${label}</text>`;
const PLUS = (x) => `<text class="m" x="${x}" y="110" text-anchor="middle">+</text>`;
const ILL = {
  mac1: `<svg class="br-ill" viewBox="0 0 320 130" aria-hidden="true"><rect class="s" x="1" y="1" width="318" height="70" rx="10"/>
    <rect class="as" x="40" y="18" width="240" height="34" rx="9"/><circle class="ln" cx="60" cy="35" r="7"/><path class="ln" d="M65 40l6 6"/>
    <text class="t" x="80" y="40">Терминал</text><rect class="a" x="216" y="24" width="56" height="22" rx="5"/><text class="on-a" x="244" y="39" text-anchor="middle">Enter</text>
    ${KEY(70, 88, 52, "⌘")}${PLUS(140)}${KEY(156, 88, 96, "Пробел")}</svg>`,
  win1: `<svg class="br-ill" viewBox="0 0 320 130" aria-hidden="true"><rect class="s" x="1" y="1" width="318" height="128" rx="10"/>
    <rect class="k" x="1" y="100" width="318" height="29"/><rect class="as" x="14" y="104" width="22" height="22" rx="4"/>
    <path class="a" d="M18 108h6v6h-6zM26 108h6v6h-6zM18 116h6v6h-6zM26 116h6v6h-6z"/>
    <rect class="s" x="14" y="14" width="190" height="80" rx="8"/><text class="m" x="28" y="38">Диспетчер задач</text>
    <rect class="as" x="20" y="48" width="178" height="26" rx="5"/><text class="t" x="28" y="66">Терминал (PowerShell)</text>
    <text class="m" x="28" y="88">Параметры</text><text class="m" x="48" y="119">← правая кнопка мыши</text></svg>`,
  paste: (win) => `<svg class="br-ill" viewBox="0 0 320 130" aria-hidden="true"><rect class="term" x="1" y="1" width="318" height="74" rx="10"/>
    <circle cx="16" cy="14" r="4" fill="#FF5F57"/><circle cx="30" cy="14" r="4" fill="#FEBC2E"/><circle cx="44" cy="14" r="4" fill="#28C840"/>
    <text class="tt" x="14" y="46">${win ? "PS&gt;" : "$"}</text><text class="tw" x="${win ? 46 : 28}" y="46">${win ? "irm '…/install.ps1?c=…' | iex" : "curl -fsSL '…/install.sh?c=…' | bash"}</text>
    ${win ? `${KEY(80, 88, 66, "Ctrl")}${PLUS(162)}${KEY(176, 88, 52, "V")}` : `${KEY(96, 88, 52, "⌘")}${PLUS(162)}${KEY(176, 88, 52, "V")}`}</svg>`,
  enter: `<svg class="br-ill" viewBox="0 0 320 130" aria-hidden="true"><rect class="a" x="30" y="30" width="110" height="60" rx="10"/>
    <text class="on-a" x="85" y="66" text-anchor="middle">Enter ⏎</text><path class="ln" d="M155 60h30m-8-8l8 8-8 8"/>
    <circle class="ok" cx="220" cy="60" r="20"/><path d="M211 60l6 6 13-13" stroke="#fff" stroke-width="4" fill="none"/>
    <text class="t" x="248" y="65">Готово!</text><text class="m" x="160" y="114" text-anchor="middle">1–3 минуты</text></svg>`,
};

function dialog(html, onClick) {                     // своя шторка: крупные карточки, кнопки и картинки
  const bg = document.createElement("div"); bg.className = "sheet-bg"; bg.dataset.help = hv("settings.bridge");
  bg.innerHTML = `<div class="sheet br" role="dialog">${html}<button class="cancel" data-close>Закрыть</button></div>`;
  document.body.append(bg);
  const close = () => { bg.remove(); bg.dispatchEvent(new Event("gone")); };
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) close(); else onClick?.(e, close); });
  return bg;
}

async function bridgeSheet() {
  let d, w = { drafts: [] };
  try { [d, w] = await Promise.all([api(B.list), FOCUS ? w : api("/api/bridge/drafts").catch(() => w)]); }
  catch (e) { return toast("Компьютеры: " + e.message, 4500); }
  const devs = d.devices || [], drafts = w.drafts || [];
  const card = (x, i) => `<button class="br-dev${x.online ? " on" : ""}" data-dev="${i}"><i class="br-dot"></i><span style="flex:1;min-width:0">
      <b>${x.online ? "На связи" : "Не на связи"}</b>
      <span class="br-name">${esc(x.name || "компьютер")}${x.os ? " · " + esc(OS[x.os] || x.os) : ""}</span>
      <small>${x.online ? "можно давать задания" : "последний раз " + esc(ago(x.seen)) + " — включите компьютер и войдите в него"}${x.focus_name ? " · фокус: " + esc(x.focus_name) : ""}</small>
      ${x.private ? `<span class="br-tag">${ic("lock")}Личные данные не уходят модели</span>` : ""}</span>${ic("chev")}</button>`;
  const wait = (x, i) => `<div class="br-wait"><p><b>${esc(x.summary)}</b></p><small>${esc(x.device_name)} · ${esc(ago(x.created))}${x.confirmed ? " · вы уже сказали «Да» — агент выполнит один раз" : ""}</small>
      ${x.confirmed ? "" : `<div class="row2"><button class="btn ghost" data-no="${i}">Нет</button><button class="btn" data-yes="${i}">Да, выполнить</button></div>`}</div>`;
  dialog(`<h3>${FOCUS ? "Ваш браузер" : "Компьютеры"}</h3>
    <p class="br-lead">${FOCUS ? "Пульт будет работать в Chrome или Edge на вашем компьютере — только в этой сессии. " : "Пульт работает в Chrome или Edge на вашем компьютере — там, где вы уже вошли в почту и сервисы. "}Банки и госуслуги выключены.</p>
    ${drafts.length ? `<h4>Ждут вашего «Да»</h4>${drafts.map(wait).join("")}` : ""}
    ${devs.length ? devs.map(card).join("") : `<p class="br-empty">Компьютеров пока нет</p>`}
    <button class="btn br-big" data-pair>${ic("plus")}Подключить компьютер</button>`, async (e, close) => {
    const dv = e.target.closest("[data-dev]"), yes = e.target.closest("[data-yes]"), no = e.target.closest("[data-no]");
    if (dv) { close(); return deviceSheet(devs[+dv.dataset.dev]); }
    if (e.target.closest("[data-pair]")) { close(); return bridgePair(); }
    if (yes || no) {
      const x = drafts[+(yes ? yes.dataset.yes : no.dataset.no)];
      try { await api(yes ? "/api/bridge/confirm" : "/api/bridge/reject", { id: x.id }); toast(yes ? "Подтверждено — агент выполнит это один раз" : "Отменено — агент это не выполнит", 3500); }
      catch (err) { toast(err.message, 4000); }
      close(); bridgeSheet();
    }
  });
}

function deviceSheet(x) {
  const revoke = () => confirmDanger(`Отозвать «${x.name}»? Мост на этом компьютере перестанет работать, подключать — заново.`, async () => {
    try { await api(B.revoke, { id: x.id }); toast("Отозвано"); bridgeSheet(); } catch (e) { toast(e.message, 4000); }
  });
  const priv = async () => {
    try { await api(B.private, { id: x.id, on: !x.private }); x.private = !x.private; toast(x.private ? "Личные данные не уходят модели" : "Модель видит страницы целиком", 3500); }
    catch (e) { return toast(e.message, 4000); }
    deviceSheet(x);
  };
  const rm = x.os === "win32" ? cmds().win_remove : cmds().mac_remove;
  helpSheet("settings.bridge");
  sheet(x.name || "компьютер", [
    { info: true, dot: x.online ? "s-running" : "hollow", label: x.online ? "На связи" : "Не на связи", sub: x.online ? "можно давать задания" : "последний раз " + ago(x.seen) },
    { label: "Личные данные не уходят модели", icon: "lock", toggle: !!x.private,
      sub: x.private ? PRIVATE_SUB : "Выключено: модель видит страницы целиком, со снимками экрана", run: priv },
    ...(FOCUS ? [] : [{ label: "Журнал действий", icon: "eye", sub: "что агенты делали на этом компьютере: время, действие, адрес", run: () => deviceLog(x) }]),
    { label: "Удалить мост с компьютера", icon: "trash", sub: "скопировать команду для Терминала или PowerShell", run: () => copyText(rm, "Команда удаления скопирована") },
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
  let c, before;
  try { [c, before] = await Promise.all([api(B.pair, {}), api(B.list)]); } catch (e) { return toast(e.message, 4500); }
  const known = new Set((before.devices || []).map((x) => x.id));
  let os = /Windows/i.test(navigator.userAgent) ? "win" : "mac", timer = null;
  const phone = matchMedia("(pointer: coarse)").matches && innerWidth < 700;
  const body = () => {
    const k = cmds(c.code), win = os === "win";
    return `<h3>Подключить компьютер</h3>
      ${phone ? `<p class="br-lead">Это делается на компьютере: откройте пульт на нём и нажмите «Подключить компьютер» там.</p>` : ""}
      <div class="br-seg" role="radiogroup" aria-label="Какой компьютер">
        <button role="radio" aria-checked="${!win}" class="${win ? "" : "on"}" data-os="mac">Mac</button>
        <button role="radio" aria-checked="${win}" class="${win ? "on" : ""}" data-os="win">Windows</button></div>
      <div class="br-step"><span class="br-num">1</span><p>${win ? "Нажмите <b>правой кнопкой</b> на «Пуск» и выберите <b>«Терминал»</b> (или «Windows PowerShell»)."
        : "Откройте <b>Терминал</b>: нажмите <b>⌘ и Пробел</b>, напишите «Терминал», нажмите <b>Enter</b>."}</p>${win ? ILL.win1 : ILL.mac1}</div>
      <div class="br-step"><span class="br-num">2</span><p>Скопируйте команду и вставьте её в окно: ${win ? "<b>Ctrl и V</b> (или правая кнопка мыши)" : "<b>⌘ и V</b>"}.</p>
        <div class="br-cmd">${esc(win ? k.win : k.mac)}</div>
        <button class="btn br-big" data-copy>${ic("copy")}Скопировать команду</button>${ILL.paste(win)}</div>
      <div class="br-step"><span class="br-num">3</span><p>Нажмите <b>Enter</b> и подождите 1–3 минуты, пока не появится «Готово!». Пароль не нужен.</p>${ILL.enter}</div>
      <p class="br-lead">Потом в ${win ? "Chrome или Edge" : "Chrome"} откроется страница расширения «Playwright Extension» — нажмите <b>«Установить»</b>. Больше ничего делать не нужно: мост будет запускаться сам.</p>
      <div class="br-live" id="brLive"><i class="br-dot"></i><span>Жду компьютер… Команда действует 10 минут и один раз.</span></div>
      <details><summary>Как удалить мост потом</summary><code>${esc(win ? k.win_remove : k.mac_remove)}</code></details>
      <p class="note" style="margin:0 16px 8px">Подключая компьютер, вы принимаете <a href="/terms" target="_blank" rel="noopener">пользовательское соглашение</a>.</p>`;
  };
  const bg = dialog(body(), (e) => {
    const b = e.target.closest("[data-os]");
    if (b && b.dataset.os !== os) { os = b.dataset.os; bg.querySelector(".sheet").innerHTML = body() + `<button class="cancel" data-close>Закрыть</button>`; }
    if (e.target.closest("[data-copy]")) copyText(os === "win" ? cmds(c.code).win : cmds(c.code).mac, "Команда скопирована — вставьте её в окно");
  });
  const poll = async () => {                          // новый компьютер на связи — сразу «Подключён»
    if (!bg.isConnected) return;
    try {
      const d = await api(B.list), got = (d.devices || []).find((x) => !known.has(x.id));
      const live = bg.querySelector("#brLive");
      if (got && live) {
        live.className = "br-live ok";
        live.innerHTML = `${ic("check")}<span><b>${got.online ? "Компьютер подключён" : "Компьютер привязан"}</b> — «${esc(got.name)}». Осталось «Установить» расширение в Chrome.</span>`;
        return;
      }
    } catch (e) {}
    timer = setTimeout(poll, 3000);
  };
  bg.addEventListener("gone", () => { clearTimeout(timer); bridgeSheet(); });
  if (!DEMO) timer = setTimeout(poll, 3000);
}

Object.assign(window, { bridgeSheet });
