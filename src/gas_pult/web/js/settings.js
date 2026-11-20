// Настройки — 5 разделов (владелец 20.11: «по Gemini, чтобы не перегружать и функции не дублировались»): вместо плоского
// списка из 29 пунктов — разделы, у каждого свой экран; «Назад» возвращает к разделам. Пункты и их условия — прежние
// (перенос из index.html), плюс «Подключения» (раньше — только вкладка главной); тема — один пункт по кругу. Пустой
// для этой роли раздел не показывается. «Подключения» в пространстве — нет: интеграции там пока владельца (GAS-38).

function groups() {
  const mode = store("theme") || "auto", THEME = { auto: "как в системе", light: "светлая", dark: "тёмная" };
  return [
    { title: "Внешний вид и язык", icon: "eye", items: [
    { label: "Тема: " + THEME[mode], icon: "eye", sub: "нажмите — следующая: как в системе → светлая → тёмная",
      run: () => { store("theme", { auto: "light", light: "dark", dark: "auto" }[mode]); applyTheme(); open(0); } },
    ...(tgBig() ? [{ label: "Во весь экран на планшете: " + (store("tgFull") === "0" ? "нет" : "да"), icon: "expand", run: () => {
      const on = store("tgFull") === "0"; store("tgFull", on ? "1" : "0"); try { on ? tg.requestFullscreen() : tg.exitFullscreen(); } catch (e) {} } }] : []),
    { label: `Размер текста: ${Math.round(fontPx / FONT.def * 100)} %`, icon: "edit", sub: "A− / A+", run: () => part("zoom").then(() => fontSheet()) },
    { label: "Язык: " + (LANG === "en" ? "English" : "русский"), icon: "globe", sub: "простого режима и экрана входа — нажмите, чтобы сменить", run: () => setLang(LANG === "en" ? "ru" : "en") },
    ] },
    { title: "Аккаунт и вход", icon: "lock", items: [
    { label: "Ключи входа — Face ID", icon: "key", sub: "вход без Telegram: Face ID, отпечаток или PIN устройства", run: keysSheet },
    ...(meta?.space && meta?.role !== "owner" ? [{ label: T("dev.title"), icon: "phone", sub: T("dev.sub"), run: deviceSheet }] : []),
    { label: "Способы входа — Google, Яндекс ID", icon: "lock", sub: "войти своим аккаунтом Google или Яндекса вместо Telegram", run: oidcSheet },
    { label: "Почта для входа и оповещений", icon: "mail", sub: "вход по коду из письма, второй фактор, письма о паузе по расходу", run: () => part("email").then(() => emailSheet()) },
    { label: "Уведомления", icon: "bell", sub: "на телефон и компьютер — даже когда панель закрыта; проверить, устройства", run: () => part("push").then((m) => m.open()) },
    ] },
    { title: "ИИ, интеграции и бюджет", icon: "chip", items: [
    ...(meta?.role !== "viewer" && !meta?.space ? [{ label: "Подключения", icon: "puzzle", sub: "почта, календарь, документы, ВкусВилл, MCP — подключить и отключить", run: () => go("go:integrations") }] : []),
    ...(meta?.role === "owner" ? [{ label: "Модель по умолчанию", icon: "chip", sub: "для всех новых сессий Claude; модель одного чата — в самом чате", run: defaultModelSheet }] : []),
    ...(meta?.role !== "viewer" ? [{ label: "Расход и лимиты", icon: "coin", sub: meta?.role === "owner" ? "токены и деньги за день, лимит на сессию и на день" : "токены и деньги за день по вашей учётке", run: costSheet }] : []),
    ...(meta?.role === "owner" ? [{ label: "Брифинг: источники и время", icon: "spark", run: () => briefGo("prefs") }] : []),
    ...(meta?.role === "owner" ? [{ label: "Компьютеры — ваш браузер", icon: "monitor", sub: "пульт управляет Chrome на вашем компьютере", run: () => part("bridge").then(() => bridgeSheet()) }] : []),
    ...(deskLinks() ? [{ label: "Ссылки: где открывать", icon: "globe", sub: "запомненные сайты — в Ubuntu или здесь", run: () => part("links").then(() => linkPrefsSheet()) }] : []),
    ] },
    { title: "Команда и клиенты", icon: "place", items: [
    ...(isBoss() ? [{ label: "Люди", icon: "place", sub: "кто ещё может входить в пульт и с какими правами", run: peopleSheet }] : []),
    ...(meta?.role === "owner" && UI?.can_team ? [{ label: "Команда", icon: "tasks", sub: "какие разделы и возможности видят сотрудники", run: teamSheet }] : []),
    ...(UI ? [{ label: T("caps.title"), icon: "settings", sub: T("caps.entry.sub", { role: personaTitle(UI.persona) }), run: capsSheet }] : []),
    ...(meta?.role === "owner" ? [{ label: "Фокус-ссылки", icon: "qr", sub: "какие сессии открыты по фокус-ссылке; отозвать", run: focusList }] : []),
    ...(meta?.role === "owner" && !FOCUS ? [{ label: "Анкеты клиентов", icon: "file", sub: "ссылка клиенту — ответы сюда и в бот", run: () => part("forms").then((m) => m.open()) }] : []),
    ] },
    { title: "Система и справка", icon: "help", items: [
    ...(meta?.role === "owner" ? [{ label: T("st.title"), icon: "chip", sub: T("st.sub"), run: providersView }] : []),
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

export function open(at) {                            // at — номер раздела: открыть его сразу (тема переключилась)
  const gs = groups();
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
