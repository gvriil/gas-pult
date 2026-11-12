// ---------- уведомления ----------
// В Telegram уведомления присылает бот. В браузере — системные, когда вкладка скрыта: «готово» и «ждёт ответа».
const canNotify = () => !tg?.initData && "Notification" in window;
let lastSeen = {};
async function askNotify() {
  if (!canNotify()) return toast("Здесь уведомления присылает бот в Telegram");
  const r = await Notification.requestPermission();
  store("notifyAsked", "1"); toast(r === "granted" ? "Уведомления включены" : "Уведомления не разрешены — включите в настройках браузера", 4000);
  document.getElementById("notifyCard")?.remove();
}
function notifyCard() {                              // спрашиваем один раз, ненавязчиво — карточкой над сессиями
  if (!canNotify() || Notification.permission !== "default" || store("notifyAsked") || DEMO) return "";
  return `<div class="notice" id="notifyCard">${ic("bell")}<span>Сообщать, когда Claude ответит или задаст вопрос?</span><button data-notify="yes">Включить</button><button data-notify="no" style="color:var(--text-secondary)">Не сейчас</button></div>`;
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-notify]"); if (!b) return;
  if (b.dataset.notify === "yes") askNotify(); else { store("notifyAsked", "1"); document.getElementById("notifyCard")?.remove(); }
});
function watchSessions(list) {                       // переходы статусов → уведомление, если вкладка не на виду
  for (const s of list) {
    const was = lastSeen[s.id];
    if (was && was !== s.status && document.hidden && canNotify() && Notification.permission === "granted") {
      const text = s.status === "dialog" ? "ждёт вашего ответа" : was === "busy" && s.status === "idle" ? "ответил" : "";
      if (text) {
        const show = (reg) => (reg ? reg.showNotification(`${s.name}: ${text}`, { body: s.preview || "", tag: s.id, data: { id: s.id } })
          : new Notification(`${s.name}: ${text}`, { body: s.preview || "", tag: s.id }));
        navigator.serviceWorker?.getRegistration().then(show).catch(() => show(null));
      }
    }
    lastSeen[s.id] = s.status;
  }
}
if (canNotify() && "serviceWorker" in navigator && !DEMO) navigator.serviceWorker.register("/sw.js").catch(() => {});
navigator.serviceWorker?.addEventListener?.("message", (e) => { if (e.data?.open) openSession(e.data.open); });

// ---------- люди (только владелец) ----------
const ROLE = { owner: "владелец", member: "участник", viewer: "наблюдатель" };
// Страна в «Людях»: выбор · код номера · страна по IP; расхождение — пометкой (номер и IP не показываются — их нет)
function countryLine(c, geoip) {
  if (!c?.chosen) return " · страна не выбрана";
  const ip = !geoip ? "нет базы" : c.ip_cc || "нет данных";
  return ` · страна ${c.chosen}, номер ${c.phone ? c.phone_cc || "?" : "не подтверждён"}, IP ${ip}` + (c.mismatch ? " — признаки расходятся" : "");
}
async function peopleSheet() {
  let d; try { d = await api("/api/people"); } catch (e) { return toast(e.message, 4000); }
  helpSheet("settings.people");
  sheet("Люди", [...(d.geoip === false ? [{ info: true, icon: "warn", label: "Страна по IP: нет данных", sub: "база стран по IP не загружена — на сервере: gas-pult geoip update" }] : []),
    ...d.people.map((p) => ({
    label: p.name || (p.username ? "@" + p.username : "ID " + p.id), icon: p.country?.mismatch ? "warn" : "place",
    sub: ROLE[p.role] + (p.kind === "guest" ? " · без Telegram" : "") + (p.tenant ? " · пространство " + p.tenant : "") + (p.last?.at ? " · вошёл " + new Date(p.last.at * 1000).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) + ", " + p.last.device : "") + (p.username ? " · @" + p.username : "") + (p.terms && p.terms.version === meta?.terms?.version ? " · условия приняты " + new Date(p.terms.at * 1000).toLocaleDateString("ru-RU") : " · условия не приняты") + countryLine(p.country, d.geoip) + (p.role === "owner" ? "" : " — нажмите, чтобы изменить или отключить"),
    run: () => p.role !== "owner" && personSheet(p) })),
    { info: true, label: "Как добавить человека", icon: "plus", sub: "пусть откроет панель и нажмёт «Войти через Telegram» — бот спросит вас, кем его пустить" },
    ...(d.geoip ? [{ info: true, icon: "globe", label: "Страна по IP", sub: (d.attribution || "IP Geolocation by DB-IP") + " · db-ip.com, CC BY 4.0" }] : [])]);
}
// ---------- «Команда» (только владельцу): потолок возможностей и разделы сотрудников (personas.Team, /api/team) ----------
// Общая политика — для всех участников; поправка — для одного человека поверх неё. Это права: сервер не отдаёт
// сотруднику API возможностей вне потолка. Наблюдателей здесь нет — у них свой постоянный потолок.
async function teamSheet(uid) {
  let d; try { d = await api("/api/team"); } catch (e) { return toast(e.message, 4000); }
  const p = uid == null ? null : d.people.find((x) => x.id === uid);
  const caps = p ? (p.own_caps ?? p.ceiling) : (d.staff_caps ?? d.catalog.caps.map((c) => c.id));
  const secs = p ? (p.own_sections ?? p.sections) : d.sections;
  const name = (x) => x.name || (x.username ? "@" + x.username : "ID " + x.id);
  const save = (body) => api("/api/team", body).then(() => { toast("Сохранено"); teamSheet(uid); }).catch((e) => toast(e.message, 4000));
  const flip = (list, id) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  const who = p ? { id: uid } : {};
  helpSheet("settings.team");
  sheet(p ? "Команда: " + name(p) : "Команда", [
    { info: true, icon: "lock", label: p ? (p.own_caps ? "Свои настройки — поверх общих" : "Как у всех сотрудников") : "Для всех сотрудников",
      sub: p ? "что видит этот человек; права проверяет сервер" : d.staff_caps == null ? "пока не задано — сотрудники видят всё, как раньше" : "что видят участники пульта; права проверяет сервер" },
    { head: "Разделы над чатом" },
    ...d.catalog.sections.map((x) => ({ label: x.title, on: secs.includes(x.id), run: () => save({ ...who, sections: flip(secs, x.id) }) })),
    { head: "Возможности" },
    ...d.catalog.caps.map((c) => ({ label: c.title, on: caps.includes(c.id), sub: c.ready ? (c.dev ? "инженерное" : "") : "готовится", run: () => save({ ...who, caps: flip(caps, c.id) }) })),
    ...(p ? [{ label: "Как у всех сотрудников", icon: "refresh", sub: "убрать свои настройки этого человека", run: () => save({ id: uid, reset: true }) }]
      : [{ head: "Сотрудники" }, ...d.people.map((x) => ({ label: name(x), icon: "place", sub: x.own_caps ? "свои настройки" : "как у всех", run: () => teamSheet(x.id) })),
         ...(d.people.length ? [] : [{ info: true, icon: "plus", label: "Сотрудников пока нет", sub: "участники появятся здесь — «Настройки» → «Люди»" }])]),
  ]);
}
function personSheet(p) {
  const set = (role) => api("/api/people/role", { id: p.id, role }).then(() => toast("Роль: " + ROLE[role])).catch((e) => toast(e.message, 4000));
  helpSheet("settings.person");
  sheet(p.name || "ID " + p.id, [
    ...(p.role === "member" ? [{ label: "Что видит в пульте", icon: "tasks", sub: "разделы и возможности — экран «Команда»", run: () => teamSheet(p.id) }] : []),
    ...(p.tenant ? [{ label: "Ссылка для входа на другое устройство", icon: "phone", sub: "одноразовая, 24 часа: QR, ссылка и код", run: () => personDevice(p) }] : []),
    { label: "Участник", icon: "chat", on: p.role === "member", sub: "писать в сессии, отвечать, новые сессии — без «Выполнить» и ключей", run: () => set("member") },
    { label: "Наблюдатель", icon: "eye", on: p.role === "viewer", sub: "только смотреть", run: () => set("viewer") },
    { label: "Отключить", icon: "power", danger: true, sub: "доступ прекратится сразу: вход перестанет работать на всех устройствах", run: () => confirmDanger(`Отключить ${p.name || "ID " + p.id}? Доступ к пульту прекратится сразу.`, () => api("/api/people/remove", { id: p.id }).then(() => toast("Отключён: " + (p.name || "ID " + p.id))).catch((e) => toast(e.message, 4000))) },
  ]);
}

// ---------- ключи входа (passkeys.py) ----------
function deviceName() {                           // название ключа по устройству — человек видит его в списке
  const ua = navigator.userAgent;
  return /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) ? "iPad" : /Android/.test(ua) ? "Android" : /Mac/.test(ua) ? "Mac" : /Windows/.test(ua) ? "Windows" : /Linux/.test(ua) ? "Linux" : "Устройство";
}
async function keysSheet() {
  let d; try { d = await api("/api/passkeys"); } catch (e) { return toast(e.message, 4000); }
  const day = (t) => t ? new Date(t * 1000).toLocaleDateString("ru-RU") : "";
  const add = async () => {
    try {
      const r = await api("/api/passkeys/options", {});
      const cred = await pkCall("create", pkCreation(r.options));
      await api("/api/passkeys/add", { id: r.id, credential: pkJson(cred), name: deviceName() });
      haptic("notificationOccurred", "success"); toast("Ключ добавлен"); keysSheet();
    } catch (e) { toast(pkError(e), 5000); }
  };
  const drop = (k) => confirmDanger(`Удалить ключ «${k.name}»? Войти с ним больше не получится.`, () => api("/api/passkeys/remove", { id: k.id }).then(() => { toast("Ключ удалён"); keysSheet(); }).catch((e) => toast(e.message, 4000)));
  helpSheet("settings.keys");
  sheet("Ключи входа", [
    ...(!d.enabled ? [{ info: true, icon: "warn", label: "Не настроено на этом пульте", sub: "владелец включает ключи в config.toml ([passkeys]) — инструкция в docs/AUTH.md" }]
      : !passkeyHere() ? [{ info: true, icon: "warn", label: "Этот браузер не умеет ключи входа", sub: "откройте панель в Safari, Chrome или Edge" }]
      : tg?.initData ? [{ info: true, icon: "ext", label: "Откройте панель в браузере", sub: "в Telegram ключи входа не работают — добавьте ключ из Safari или Chrome по адресу панели" }]
      : [{ label: "Добавить ключ этого устройства", icon: "plus", sub: "Face ID, отпечаток или PIN — закрытый ключ остаётся в устройстве", run: add }]),
    ...d.keys.map((k) => ({ label: k.name, icon: "key", sub: `добавлен ${day(k.created)}` + (k.last_used ? ` · вход ${day(k.last_used)}` : " · ещё не входили") + " — нажмите, чтобы удалить", run: () => drop(k) })),
    ...(d.keys.length ? [] : [{ info: true, icon: "lock", label: "Ключей пока нет", sub: "с ключом можно войти в панель без Telegram" }]),
  ]);
}

// ---------- способы входа: Google и Яндекс ID (oidc.py) ----------
// Привязка — переходом на сайт провайдера по одноразовой ссылке (5 минут); из Telegram — во внешнем браузере.
async function oidcSheet() {
  let d; try { d = await api("/api/oidc"); } catch (e) { return toast(e.message, 4000); }
  const day = (t) => t ? new Date(t * 1000).toLocaleDateString("ru-RU") : "";
  const link = async (p) => {
    try {
      const r = await api("/api/oidc/link", { provider: p });
      if (DEMO) return toast("В демо привязка не выполняется", 4000);
      if (tg?.initData) { tg.openLink(location.origin + r.url); toast("Открыли браузер — закончите привязку там", 5000); }
      else location.href = r.url;
    } catch (e) { toast(e.message, 4000); }
  };
  const unlink = (p, x) => confirmDanger(`Отвязать ${x.title}? Войти через него больше не получится.`, () => api("/api/oidc/unlink", { provider: p }).then(() => { toast("Отвязано"); oidcSheet(); }).catch((e) => toast(e.message, 4000)));
  const rows = Object.entries(d).map(([p, x]) => !x.enabled ? { info: true, icon: "warn", label: x.title + ": не настроено на этом пульте", sub: `владелец включает вход в config.toml ([${p}]) — инструкция в docs/AUTH.md` }
    : x.linked ? { label: x.title + ": привязан", icon: "check", sub: (x.email ? x.email + " · " : "") + `с ${day(x.at)} — нажмите, чтобы отвязать`, run: () => unlink(p, x) }
    : { label: "Привязать " + x.title, icon: "ext", sub: "откроется сайт " + x.title + ": войдите в свой аккаунт — после этого им можно входить в пульт", run: () => link(p) });
  helpSheet("settings.oidc");
  sheet("Способы входа", [
    ...rows,
    { info: true, icon: "lock", label: "Только вход", sub: "пульт получает лишь адрес и номер аккаунта — без писем, файлов и диска. Совпал подтверждённый адрес с почтой в пульте — вход работает и без привязки" },
  ]);
}

// ---------- почта для входа и оповещений (emailcode.py) ----------
// Адрес подтверждается кодом из письма; по нему можно войти, включить второй фактор и письма-оповещения.
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
function legend() {
  const chip = (cls, t) => `<span class="chip ${cls}" style="font-size:11px;padding:1px 6px">${t}</span>`;
  helpSheet("settings.legend");
  sheet("Обозначения", [
    { head: "Точка статуса сессии" },
    { info: true, dot: "s-running", label: "Зелёная, мигает — работает", sub: "Claude выполняет задачу; можно писать — сообщение встанет в очередь" },
    { info: true, dot: "s-approval", label: "Жёлтая — ждёт вашего ответа", sub: "Claude задал вопрос или просит разрешения — ответьте кнопками на экране" },
    { info: true, dot: "s-idle", label: "Серая — свободна", sub: "готова к новому сообщению" },
    { info: true, dot: "s-stopped", label: "Красная — остановлена", sub: "Claude в окне не запущен (нет процесса) — «Перезапустить» или новая сессия" },
    { head: "Метки" },
    { info: true, vis: '<i class="sdot s-approval"></i>', label: "Точка у имени сессии ▾", sub: "в другой сессии вопрос или новый ответ — нажмите имя, чтобы перейти" },
    { info: true, vis: chip("new", "новый"), label: "Новый ответ", sub: "ответ, который вы ещё не открывали" },
    { info: true, vis: chip("s-approval", "ждут"), label: "Ждут ответа", sub: "сколько сессий ждут вас — на главной" },
    { info: true, vis: '<span class="ctx warn"><span class="bar"><i style="width:80%"></i></span></span>', label: "Контекст: N%", sub: "сколько памяти разговора занято; жёлтая — больше 70%, пора «Сжать» (/compact)" },
    { info: true, vis: chip("cost", "$0.42"), label: "Расход сессии", sub: "деньги по ценам API и токены из журнала Claude Code; «из $N» — лимит; жёлтая — больше 80% лимита. Видит только хозяин учётки" },
    { info: true, vis: chip("s-approval", "пауза"), label: "На паузе по расходу", sub: "сессия превысила лимит: Claude остановлен, сообщения не уходят, пока владелец не решит" },
    { info: true, vis: '<span class="live stale"><i></i></span>', label: "«Нет связи · N с» у поля ввода", sub: "связь прервалась, данные могут быть старыми; пока связь есть, индикатора нет" },
    { head: "Вкладка «Команды»" },
    { info: true, vis: chip("s-running", "идёт"), label: "Выполняется", sub: "команду запустили через пульт — ждём итог" },
    { info: true, vis: chip("ok", "код 0"), label: "Код 0 — успешно", sub: "выполнена через пульт без ошибок" },
    { info: true, vis: chip("bad", "код N"), label: "Код N — ошибка", sub: "вывод под командой; «на разборе» — ушла в свою сессию, Claude предложит исправление" },
    { info: true, vis: '<span class="chip"><i class="sdot hollow"></i></span>', label: "Не запускалась", sub: "через пульт её ещё не выполняли" },
    { info: true, vis: chip("accent", "вручную"), label: "Сделано вручную", sub: "вы отметили, что выполнили сами — команда остаётся в списке" },
    { head: "Кнопки" },
    { info: true, icon: "menu", label: "Меню действий", sub: "озвучить, команды Claude, модель, активная сессия, обновить, завершить" },
    { info: true, icon: "vol", label: "Прослушать", sub: "озвучить ответ голосом; скорость 1×–2× — кнопкой в плеере" },
    { info: true, icon: "bolt", label: "Команды Claude", sub: "/compact, /clear, /status и другие — кнопками" },
    { info: true, icon: "chip", label: "Модель", sub: "в какой модели работает сессия" },
    { info: true, icon: "place", label: "Активная", sub: "ответы в чате бота — от этой сессии" },
    { info: true, icon: "term", label: "Экран", sub: "терминал сессии как есть; вариант ответа — кнопкой" },
    { info: true, icon: "attach", label: "Прикрепить", sub: "фото или файл — Claude получит путь к нему" },
    { info: true, icon: "mic", label: "Голосом", sub: "надиктовать сообщение — панель распознает текст" },
    { info: true, icon: "play", label: "Выполнить", sub: "команду из ответа — на сервере пульта" },
    { info: true, icon: "warn", label: "Опасная команда", sub: "меняет или удаляет данные — спросим подтверждение" },
    { info: true, icon: "monitor", label: "Для другой машины", sub: "скопируйте и выполните там (Mac, гипервизор)" },
    { info: true, icon: "key", label: "Нужен ввод (пароль)", sub: "keepassxc-cli, sudo, ssh — «Открыть в терминале» вместо «Выполнить»" },
    { info: true, icon: "lock", label: "sudo -n вне списка", sub: "только вручную в терминале" },
    { info: true, icon: "copy", label: "Копировать", sub: "текст ответа или команды — в буфер обмена" },
  ]);
}
$("settingsBtn").onclick = () => {
  const mode = store("theme") || "auto";
  helpSheet("settings");
  sheet("Настройки", [
    { label: "Тема: как в системе", on: mode === "auto", run: () => { store("theme", "auto"); applyTheme(); } },
    { label: "Тема: светлая", on: mode === "light", run: () => { store("theme", "light"); applyTheme(); } },
    { label: "Тема: тёмная", on: mode === "dark", run: () => { store("theme", "dark"); applyTheme(); } },
    { label: "Ключи входа — Face ID", icon: "key", sub: "вход без Telegram: Face ID, отпечаток или PIN устройства", run: keysSheet },
    ...(meta?.space && meta?.role !== "owner" ? [{ label: T("dev.title"), icon: "phone", sub: T("dev.sub"), run: deviceSheet }] : []),
    { label: "Способы входа — Google, Яндекс ID", icon: "lock", sub: "войти своим аккаунтом Google или Яндекса вместо Telegram", run: oidcSheet },
    { label: "Почта для входа и оповещений", icon: "mail", sub: "вход по коду из письма, второй фактор, письма о паузе по расходу", run: emailSheet },
    { label: "Страна", icon: "globe", sub: meta?.country?.chosen ? meta.country.chosen + (meta.country.mismatch ? " · признаки расходятся" : "") + " — поменять или подтвердить номер" : "не выбрана", run: () => showCountry(true) },
    ...(canNotify() ? [{ label: "Уведомления", icon: "bell", sub: Notification.permission === "granted" ? "включены — о готово и «ждёт ответа»" : "выключены — нажмите, чтобы включить", run: askNotify }] : []),
    ...(meta?.role === "owner" ? [{ label: "Проверка", icon: "check", sub: "Claude Code установлен, вход выполнен, ключи", run: setupSheet }] : []),
    ...(meta?.role === "owner" ? [{ label: T("st.title"), icon: "chip", sub: T("st.sub"), run: providersView }] : []),
    ...(meta?.role === "owner" ? [{ label: "Люди", icon: "place", sub: "кто ещё может входить в пульт и с какими правами", run: peopleSheet }] : []),
    ...(meta?.role === "owner" && UI?.can_team ? [{ label: "Команда", icon: "tasks", sub: "какие разделы и возможности видят сотрудники", run: teamSheet }] : []),
    ...(meta?.role === "owner" ? [{ label: "Корзина чатов", icon: "trash", sub: "удалённые сессии и чаты — вернуть; скрытые — показать снова", run: chatTrash }] : []),
    ...(meta?.role === "owner" ? [{ label: "Фокус-ссылки", icon: "qr", sub: "какие сессии открыты по фокус-ссылке; отозвать", run: focusList }] : []),
    ...(meta?.role === "owner" ? [{ label: "Модель по умолчанию", icon: "chip", sub: "для всех новых сессий Claude; модель одного чата — в самом чате", run: defaultModelSheet }] : []),
    ...(meta?.role !== "viewer" ? [{ label: "Расход и лимиты", icon: "coin", sub: meta?.role === "owner" ? "токены и деньги за день, лимит на сессию и на день" : "токены и деньги за день по вашей учётке", run: costSheet }] : []),
    ...(UI ? [{ label: T("caps.title"), icon: "settings", sub: T("caps.entry.sub", { role: personaTitle(UI.persona) }), run: capsSheet }] : []),
    { label: "Язык: " + (LANG === "en" ? "English" : "русский"), icon: "globe", sub: "простого режима и экрана входа — нажмите, чтобы сменить", run: () => setLang(LANG === "en" ? "ru" : "en") },
    { label: "Обозначения", icon: "help", sub: "что значат точки, цвета и значки", run: legend },
    ...[tourKind(), ...TOUR_KINDS.filter((k) => k !== tourKind())].map((k) => ({ label: "Пройти тур: " + TOURS[k].title, icon: "spark", sub: k === "dev" ? "сессии, экран, команды, модели, интеграции, расход" : "простыми словами: агенты, «Из модуля», «Примерить на себя», расход", run: () => { store("tourKind", k); startTour(k); } })),
    { label: "Перезагрузить панель", icon: "refresh", sub: "если что-то выглядит старым или зависло", run: reloadPanel },
    ...(meta?.via === "browser" ? [{ label: "Выйти на этом устройстве", icon: "power", danger: true, run: async () => { await api("/api/logout", {}); showLogin(); } }] : []),
  ]);
};
