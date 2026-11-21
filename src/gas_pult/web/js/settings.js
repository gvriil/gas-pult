// Настройки — 5 разделов (владелец 20.11: «по Gemini, чтобы не перегружать и функции не дублировались»): вместо плоского
// списка из 29 пунктов — разделы, у каждого свой экран; «Назад» возвращает к разделам. Пункты и их условия — прежние
// (перенос из index.html), плюс «Подключения» (раньше — только вкладка главной); тема — один пункт по кругу. Пустой
// для этой роли раздел не показывается. «Подключения» в пространстве — нет: интеграции там пока владельца (GAS-38).

// Состояние уведомлений этого устройства — сразу в подписи (владелец 20.11: «опять только Telegram»; подписок не было:
// «Включить» ни разу не нажимали). Подписку проверяет экран «Уведомления»; здесь — то, что видно без запроса.
function pushState() {
  if (tg?.initData) return "здесь, в Telegram, — присылает бот; на телефон — откройте Гаврилу в браузере";
  if (!("PushManager" in window) || !("Notification" in window)) return /iPhone|iPad/.test(navigator.userAgent) ? "на iPhone — откройте Гаврилу значком с экрана «Домой»" : "этот браузер не умеет уведомления";
  return Notification.permission === "granted" ? "на этом устройстве включены · проверить, устройства" : "на этом устройстве выключены — включить";
}

function groups() {
  const mode = store("theme") || "auto", THEME = { auto: "как в системе", light: "светлая", dark: "тёмная" };
  return [
    { title: "Внешний вид и язык", icon: "eye", items: [
    { label: "Тема", icon: "eye", seg: [["auto", "Система"], ["light", "Светлая"], ["dark", "Тёмная"]], cur: mode,   // Gemini №11
      run: (v) => { if (!v || v === mode) return open(0); store("theme", v); applyTheme(); open(0); } },
    ...(tgBig() ? [{ label: "Во весь экран на планшете: " + (store("tgFull") === "0" ? "нет" : "да"), icon: "expand", run: () => {
      const on = store("tgFull") === "0"; store("tgFull", on ? "1" : "0"); try { on ? tg.requestFullscreen() : tg.exitFullscreen(); } catch (e) {} } }] : []),
    { label: `Размер текста: ${Math.round(fontPx / FONT.def * 100)} %`, icon: "edit", sub: "A− / A+", run: () => part("zoom").then(() => fontSheet()) },
    { label: "Язык: " + (LANG === "en" ? "English" : "русский"), icon: "globe", sub: "простого режима и экрана входа — нажмите, чтобы сменить", run: () => setLang(LANG === "en" ? "ru" : "en") },
    ] },
    { title: "Аккаунт и вход", icon: "lock", items: [
    { label: "Ключи входа — Face ID", icon: "key", sub: "вход без Telegram: Face ID, отпечаток или PIN устройства", run: keysSheet },
    ...(meta?.space && meta?.role !== "owner" ? [{ label: T("dev.title"), icon: "phone", sub: T("dev.sub"), run: deviceSheet }] : []),
    { label: "Способы входа — Google, Яндекс ID", icon: "lock", sub: "войти своим аккаунтом Google или Яндекса вместо Telegram", run: oidcSheet },
    { label: "Почта для входа и оповещений", icon: "mail", sub: "вход по коду из письма, второй фактор, письма о важном", run: () => part("email").then(() => emailSheet()) },
    { label: "Уведомления", icon: "bell", sub: pushState(), run: () => part("push").then((m) => m.open()) },
    ...(meta?.role !== "viewer" && !meta?.space && !FOCUS ? [{ label: "Устройства для «Поделиться»", icon: "share", sub: "фото, ссылки и файлы из других приложений — в Гаврилу; iPhone и Android", run: () => part("share").then((m) => m.devicesSheet()) }] : []),
    ] },
    { title: "ИИ, интеграции и бюджет", icon: "chip", items: [
    ...(meta?.role !== "viewer" && !meta?.space ? [{ label: "Подключения", icon: "puzzle", sub: "почта, календарь, документы, ВкусВилл, MCP — подключить и отключить", run: () => go("go:integrations") }] : []),
    ...(meta?.role === "owner" ? [{ label: "Модель по умолчанию", icon: "chip", sub: "для всех новых сессий Claude; модель одного чата — в самом чате", run: defaultModelSheet }] : []),
    ...(meta?.role !== "viewer" ? [{ label: "Расход и лимиты", icon: "coin", sub: meta?.role === "owner" ? "токены и деньги за день, лимит на сессию и на день" : "токены и деньги за день по вашей учётке", run: costSheet }] : []),
    ...(meta?.role === "owner" ? [{ label: "Брифинг: источники и время", icon: "spark", run: () => briefGo("prefs") }] : []),
    ...(meta?.role === "owner" ? [{ label: "Компьютеры — ваш браузер", icon: "monitor", sub: "пульт управляет Chrome на вашем компьютере", run: () => part("bridge").then(() => bridgeSheet()) }] : []),
    ...(deskLinks() ? [{ label: "Ссылки: где открывать", icon: "globe", sub: "запомненные сайты — в Браузере или здесь", run: () => part("links").then(() => linkPrefsSheet()) }] : []),
    ] },
    { title: "Команда и клиенты", icon: "place", items: [
    ...(isBoss() ? [{ label: "Пригласить человека", icon: "mail", sub: "ссылка-приглашение в пульт", run: spaceInvite }] : []),   // из «⋯» панели (Gemini №8)
    // «Люди» и «Команда» — один пункт (Gemini №12): список людей, внутри — «Что видят сотрудники»
    ...(isBoss() ? [{ label: "Команда и права", icon: "place", sub: "кто входит в пульт, роли и что видят сотрудники", run: peopleSheet }] : []),
    ...(UI ? [{ label: T("caps.title"), icon: "settings", sub: T("caps.entry.sub", { role: personaTitle(UI.persona) }), run: capsSheet }] : []),
    ...(meta?.role === "owner" ? [{ label: "Фокус-ссылки", icon: "qr", sub: "какие сессии открыты по фокус-ссылке; отозвать", run: focusList }] : []),
    ...(meta?.role === "owner" && !FOCUS ? [{ label: "Анкеты клиентов", icon: "file", sub: "ссылка клиенту — ответы сюда и в бот", run: () => part("forms").then((m) => m.open()) }] : []),
    ] },
    { title: "Система и справка", icon: "help", items: [
    { label: "Отзыв", icon: "chat", sub: "что не так или что улучшить — текстом или голосом, со снимком экрана", run: () => part("feedback").then((m) => m.open()) },
    ...(meta?.role === "owner" && dev("dev_models_mcp") ? [{ label: T("st.title"), icon: "chip", sub: T("st.sub"), run: providersView }] : []),   // инженерный экран [У] (Gemini №13)
    ...(meta?.role === "owner" ? [{ label: "Проверка", icon: "check", sub: "Claude Code установлен, вход выполнен, ключи", run: setupSheet }] : []),
    ...(meta?.role === "owner" ? [{ label: "Корзина чатов", icon: "trash", sub: "удалённые сессии и чаты — вернуть; скрытые — показать снова", run: chatTrash }] : []),
    { label: "Обозначения", icon: "help", sub: "что значат точки, цвета и значки", run: legend },
    ...[tourKind(), ...TOUR_KINDS.filter((k) => k !== tourKind())].map((k) => ({ label: "Пройти тур: " + TOURS[k].title, icon: "spark", sub: k === "dev" ? "сессии, экран, команды, модели, интеграции, расход" : "простыми словами: агенты, «Из модуля», «Примерить на себя», расход", run: () => { store("tourKind", k); startTour(k); } })),
    { label: "Перезагрузить панель", icon: "refresh", sub: "если что-то выглядит старым или зависло", run: reloadPanel },
    ] },
  ].map((g) => ({ ...g, items: g.items.filter(Boolean) })).filter((g) => g.items.some((x) => !x.head));
}

// подпись группы: начала пунктов без пояснений («Ключи входа — Face ID» → «ключи входа»), без повторов, до 4
const brief = (items) => [...new Set(items.filter((x) => !x.head && !x.danger)
  .map((x) => x.label.split(/ — |:/)[0].trim()).map((t) => /^[А-ЯЁ][а-яё]/.test(t) ? t[0].toLowerCase() + t.slice(1) : t))].slice(0, 4).join(", ");

// ПК (Gemini №6, приём 2): одно окно 720×560 — слева разделы, справа пункты; без «‹ Назад», × справа вверху.
// Строится из обычной шторки раздела (те же пункты и обработчики); вложенные окна «‹ Назад» возвращают сюда же.
const WIDE_CSS = `.sheet.setwide { width: min(720px, calc(100vw - 32px)); max-width: 720px; height: min(560px, calc(100vh - 48px));
  display: flex; padding: 0; overflow: hidden; }
.setwide .setnav { flex: none; width: 248px; padding: 12px 8px; border-right: 1px solid var(--border-subtle);
  background: var(--bg-subtle); display: flex; flex-direction: column; gap: 2px; overflow-y: auto; }
.setwide .setnav button { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 36px; padding: 6px 10px;
  border: 0; border-radius: var(--radius-sm); background: none; color: var(--text-secondary); text-align: left;
  font-size: calc(14px * var(--fz, 1)); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.setwide .setnav button span { overflow: hidden; text-overflow: ellipsis; }
.setwide .hpill.insheet { right: 52px; }
.setwide .setnav button.on { background: var(--bg-surface); color: var(--text-primary); font-weight: 600; }
.setwide .setpane { flex: 1; min-width: 0; overflow-y: auto; padding: 8px 4px 12px; position: relative; }
.setwide .cancel, .setwide .sback { display: none; }
.setwide .setx { position: absolute; top: 8px; right: 8px; width: 32px; height: 32px; min-height: 0; padding: 0;
  border: 0; border-radius: var(--radius-sm); background: none; color: var(--text-secondary); display: grid; place-items: center; }`;
const wide = () => split() && innerWidth >= 900;
function openWide(at, gs) {
  if (!document.getElementById("setwideCss")) document.head.insertAdjacentHTML("beforeend", `<style id="setwideCss">${WIDE_CSS}</style>`);
  const g = gs[at];
  const back = (run) => (v) => { if (sheetFrom) sheetFrom.open = () => open(at); return run(v); };   // «‹ Назад» — в это окно
  helpSheet("settings");
  sheet(g.title, g.items.map((x) => (x.run ? { ...x, run: back(x.run) } : x)));
  const s = [...document.querySelectorAll(".sheet-bg .sheet")].at(-1); if (!s) return;
  const pane = document.createElement("div"); pane.className = "setpane";
  pane.append(...[...s.childNodes]);
  pane.insertAdjacentHTML("afterbegin", `<button class="setx" data-close aria-label="Закрыть">${ic("x")}</button>`);
  const nav = document.createElement("nav"); nav.className = "setnav"; nav.setAttribute("aria-label", "Разделы настроек");
  nav.innerHTML = gs.map((x, i) => `<button type="button" data-sec="${i}" class="${i === at ? "on" : ""}">${ic(x.icon)}<span>${esc(x.title)}</span></button>`).join("")
    + (meta?.via === "browser" ? `<button type="button" data-out class="danger" style="margin-top:auto">${ic("power")}<span>Выйти</span></button>` : "");
  nav.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.out) return void api("/api/logout", {}).then(showLogin);
    open(+b.dataset.sec);                             // старое окно уберёт сама шторка (нажата кнопка)
  });
  s.classList.add("setwide"); s.append(nav, pane);
}

export function open(at) {                            // at — номер раздела: открыть его сразу (тема переключилась)
  const gs = groups();
  if (wide()) return openWide(gs[at] ? at : 0, gs);
  if (at != null && gs[at]) { helpSheet("settings"); return sheet(gs[at].title, gs[at].items); }
  helpSheet("settings");
  sheet("Настройки", [
    ...gs.map((g) => ({ label: g.title, icon: g.icon, sub: brief(g.items),
      run: () => { helpSheet("settings"); sheet(g.title, g.items); } })),
    ...(meta?.via === "browser" ? [{ label: "Выйти на этом устройстве", icon: "power", danger: true, run: async () => { await api("/api/logout", {}); showLogin(); } }] : []),
  ]);
}

export function legend() {
  const chip = (cls, t) => `<span class="chip ${cls}" style="font-size:11px;padding:1px 6px">${t}</span>`;
  helpSheet("settings.legend");
  sheet("Обозначения", [
    { head: "Точка статуса сессии" },
    { info: true, dot: "s-running", label: "Зелёная, мигает — работает", sub: "Claude выполняет задачу; можно писать — сообщение встанет в очередь" },
    { info: true, dot: "s-approval", label: "Жёлтая — ждёт вашего ответа", sub: "Claude задал вопрос или просит разрешения — ответьте кнопками на экране" },
    { info: true, dot: "s-idle", label: "Серая — свободна", sub: "готова к новому сообщению" },
    { info: true, dot: "s-sleep", label: "Пустая серая — спит", sub: "чат отдыхает; напишите — проснётся сам и продолжит разговор" },
    { head: "Метки" },
    { info: true, vis: '<i class="sdot s-approval"></i>', label: "Точка у имени сессии ▾", sub: "в другой сессии вопрос или новый ответ — нажмите имя, чтобы перейти" },
    { info: true, vis: chip("new", "новый"), label: "Новый ответ", sub: "ответ, который вы ещё не открывали" },
    { info: true, vis: chip("s-approval", "ждут"), label: "Ждут ответа", sub: "сколько сессий ждут вас — на главной" },
    { info: true, vis: '<span class="ctx warn"><span class="bar"><i style="width:80%"></i></span></span>', label: "Контекст: N%", sub: "сколько памяти разговора занято; жёлтая — больше 70%, пора «Сжать» (/compact)" },
    { info: true, vis: chip("cost", "$0.42"), label: "Расход чата", sub: "деньги по ценам API и токены из журнала Claude Code; «из $N» — лимит; жёлтая — больше 80% лимита. Видит только хозяин учётки" },
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
