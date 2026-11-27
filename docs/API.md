# API панели — опись путей

<!-- Файл собран генератором: python -m gas_pult.api_spec. Руками не править — правьте src/gas_pult/api_spec.py (описания) или webapp.py (маршруты) и перезапустите генератор. -->

Путей: **301**, пар «путь + метод»: **315**. Машиночитаемо — [`openapi.json`](openapi.json) (OpenAPI 3.1).

Все пути — под адресом панели, ответы — JSON (кроме отмеченных). Ошибка — `{"error": "…", "code": …}` с кодом HTTP: 401 — нужен вход, 403 — не хватает прав (`code`: `terms`, `space`, `focus_scope`, `confirm`, `cap`, `dev`, `budget`), 404 — нет метода, 409/410 — конфликт или ссылка погасла, 429 — лимит.

## Кто может

Роль — по формуле `Handler.permit` и таблицам `src/gas_pult/access.py`:

| Роль | Значит |
|---|---|
| владелец | `OWNER_ONLY` |
| владелец и админ | `OWNER_ONLY` и `ADMIN_OK` |
| участник и выше | POST (кроме личных настроек) и `MEMBER_ONLY`; наблюдателю — нет |
| любой вошедший | чтение и личные настройки — и наблюдателю |
| без входа | обрабатывается до проверки входа: свой код, токен или подпись (вход, приглашение, мост, анкета) |
| только по фокус-ссылке | путь есть только в режиме фокуса (`focus_do`); обычной панели — 404 |
| по токену | `/api/v1/…`: Bearer-токен из «Токены для 1С и CRM», путь — из белого списка `access.V1_*` |

Метки:

| Метка | Значит |
|---|---|
| `и до входа` | на экране входа — и без входа (свой лимит по IP) |
| `CONFIRM` | новая сессия браузера (моложе суток) — после кода подтверждения (403 code=confirm) |
| `TTY` | только в режиме разработчика (живой терминал) |
| `TERMS_FREE` | доступно до принятия условий использования |
| `SPACE_OK` | доступно тестировщику демо-пространства (только своё пространство) |
| `BUDGET` | тестировщику — пока не исчерпан дневной бюджет пространства |
| `SLINK_NO` | не по ссылке на пространство |
| `FOCUS` | по фокус-ссылке (только её сессия) |
| `FOCUS_PROJ` | по фокус-ссылке на проект (только её проект) |
| `DEMO` | по демо-ссылке (просмотр и выбор вариантов) |
| `MEETING` | по ссылке на протокол встречи (только её протокол) |
| `cap:…` | потолок возможностей человека (personas.PATH_CAP) |
| `V1` | псевдоним `/api/<путь>` для 1С и CRM: `Authorization: Bearer`, права выпустившего; запись — у токена с «запись» (docs/API-V1.md) |
| `v1:…` | группа прав токена (`access.V1_GET` / `access.V1_POST`) |

## Сессии и чат

| Путь | Метод | Кто | Метки | Что делает | Вход | Выход |
|---|---|---|---|---|---|---|
| `/api/active` | POST | участник и выше | — | Сделать сессию активной в чате бота | `w` | `ok` |
| `/api/activity` | GET | любой вошедший | `SPACE_OK`, `FOCUS`, `DEMO` | Строка статуса чата: что агент делает сейчас | `w` | — |
| `/api/ask` | GET | любой вошедший | `SPACE_OK`, `FOCUS`, `DEMO` | Простой режим: вопрос Claude простыми словами и варианты-чипы | `w` | `ask` |
| `/api/close` | POST | владелец | `FOCUS` | «Завершить» сессию; модулю — расписание (оставить, приостановить, выключить) | `w`, `schedule`, `force` | — |
| `/api/cmds` | GET | любой вошедший | `FOCUS`, `cap:cap.dev_sessions` | Команды из ответов агента, которые можно выполнить кнопкой | `w` | `cmds`, `host` |
| `/api/command` | POST | участник и выше | `SPACE_OK`, `BUDGET`, `FOCUS`, `cap:cap.dev_sessions` | Выполнить команду из списка `/api/cmds` по номеру | `w`, `i` | — |
| `/api/effort` | POST | участник и выше | `FOCUS`, `cap:cap.dev_models_mcp` | Уровень усилий модели (/effort) в сессии | `w`, `level` | `lines` |
| `/api/folder` | POST | участник и выше | `cap:cap.dev_sessions` | «Новая папка» и сессия в ней (как папка в боте) | `name`, `profile` | — |
| `/api/hint` | GET | любой вошедший | `SPACE_OK`, `FOCUS`, `DEMO`, `cap:cap.dev_terminal` | Подсказка ввода из строки окна (что предлагает Claude Code) | `w` | `hint` |
| `/api/history` | GET | любой вошедший | `SPACE_OK`, `FOCUS`, `DEMO` | Переписка сессии страницами (новые сверху, `before` — раньше); `team` — сообщения команды | `w`, `before`, `rev` | `team`, `same`, `rev`, `items`, `more` |
| `/api/key` | POST | участник и выше | `SPACE_OK`, `FOCUS`, `DEMO` | Клавиша в окно (Enter, Esc, стрелки, Ctrl+C); по демо-ссылке — только выбор варианта | `key`, `w` | `lines` |
| `/api/last` | GET | любой вошедший | `SPACE_OK`, `FOCUS`, `DEMO` | Последний ответ агента текстом (для «Скопировать» и озвучки) | `w` | `text` |
| `/api/media` | GET | владелец | `FOCUS` | Картинка из ленты: inbox и Диск (по фокус-ссылке — только её папки) | `p` | — |
| `/api/model` | POST | участник и выше | `FOCUS`, `cap:cap.dev_models_mcp` | Сменить модель сессии; `keep` — только запомнить для перезапуска | `w`, `keep`, `name`, `effort` | — |
| `/api/model/default` | GET | владелец | — | Модель Claude по умолчанию для новых сессий | `model` | — |
| `/api/model/default` | POST | владелец | — | Модель Claude по умолчанию для новых сессий | `model` | — |
| `/api/new` | POST | участник и выше | `SPACE_OK`, `BUDGET` | Новая сессия (окно) в папке; тестировщику — в его пространстве | `name`, `effort`, `i`, `profile` | — |
| `/api/notify-done` | POST | любой вошедший | `SLINK_NO` | «Сообщить по готовности»: одно сообщение в бот, когда ход закончится | `w` | `result` |
| `/api/notify/level` | POST | владелец | — | Уровень уведомлений этой сессии (notifylevel.py) | `w`, `level` | `notify` |
| `/api/order` | POST | участник и выше | — | Свой порядок закреплённых, проектов и чатов | `ids`, `grp` | `ok`, `ids` |
| `/api/pin` | POST | участник и выше | — | «Закрепить» / «Открепить» проект, сессию или чат | `on`, `project`, `w`, `id`, `sid` | — |
| `/api/rename` | POST | участник и выше | `SPACE_OK`, `FOCUS`, `cap:cap.dev_sessions` | Переименовать окно сессии | `w`, `name` | `name` |
| `/api/resend` | POST | участник и выше | `SPACE_OK`, `FOCUS` | «Отправить» у строки «Не отправлено» — Enter после проверки | `w`, `sha` | `result` |
| `/api/restart` | POST | владелец и админ | `FOCUS` | Перезапустить сессию с профилем модели; `keep` — продолжить разговор | `w`, `profile`, `keep` | — |
| `/api/revive` | POST | участник и выше | `FOCUS` | Оживить сессию, окно которой пропало (продолжить по журналу) | `w` | — |
| `/api/route` | POST | участник и выше | — | Подсказка модели по первому сообщению (router.py) | `text` | — |
| `/api/scenarios` | GET | любой вошедший | `SPACE_OK` | «Примерить на себя»: роли, день с агентом, польза | — | `errors` |
| `/api/screen` | GET | любой вошедший | `SPACE_OK`, `FOCUS`, `DEMO`, `cap:cap.dev_terminal` | Последние строки экрана окна; вход в сервис и вопрос, если на экране | `w` | `lines`, `auth`, `login`, `ask` |
| `/api/select` | POST | участник и выше | `SPACE_OK`, `BUDGET`, `FOCUS`, `DEMO` | Выбрать вариант в вопросе Claude (номер или текст) | `go`, `w`, `n`, `text` | `lines` |
| `/api/send` | POST | участник и выше | `SPACE_OK`, `BUDGET`, `FOCUS` | Отправить текст в сессию; повтор того же текста — `dup` | `text`, `w`, `id` | `ok`, `dup` |
| `/api/sessions` | GET | любой вошедший | `SPACE_OK`, `FOCUS`, `DEMO` | Список сессий (окна tmux) для главной: статус, расход, лимиты (владельцу), задачи | — | `sessions`, `host`, `build`, `now`, `cost`, `fallback`, `focus`, `space`, `limits`, `tasks` |
| `/api/starter` | POST | участник и выше | `SPACE_OK`, `FOCUS` | Нажали бейджик: текст для агента и замер (без текста) | `id`, `w` | `prompt` |
| `/api/starters` | GET | любой вошедший | `SPACE_OK`, `FOCUS` | Бейджики-сценарии первого разговора (GAS-37) | `occ` | — |
| `/api/steps` | GET | любой вошедший | `SPACE_OK` | «Шаги»: сообщение → инструменты → ответ (GAS-16) | `w`, `q` | `turns`, `note` |
| `/api/stopped/clear` | POST | владелец | — | «Убрать все остановленные» — окна закрыты, журналы остаются | — | — |
| `/api/title` | POST | участник и выше | `SPACE_OK`, `FOCUS` | Название чата (вторая часть), не имя окна; пусто — авто | `w`, `title` | — |
| `/api/upload` | POST | участник и выше | `FOCUS` | Файл в сессию (поток в файл); `w` — папка проекта, иначе inbox | `тело — байты файла, X-File-Name; w (query)` | `path` |

## Голос

| Путь | Метод | Кто | Метки | Что делает | Вход | Выход |
|---|---|---|---|---|---|---|
| `/api/providers` | GET | владелец | — | Голосовые поставщики: настройки и голоса ElevenLabs; POST — сохранить | — | `el_voices`, `ok` |
| `/api/providers` | POST | владелец | — | Голосовые поставщики: настройки и голоса ElevenLabs; POST — сохранить | — | `el_voices`, `ok` |
| `/api/rec/chunk` | POST | участник и выше | `SPACE_OK`, `FOCUS` | Кусок записи (~10 с) на сервер: не теряется при блокировке телефона | `id, seg, seq (query); тело — звук` | — |
| `/api/rec/drop` | POST | участник и выше | `SPACE_OK`, `FOCUS` | «Отменить запись»: куски удалить | `id` | `ok` |
| `/api/rec/finish` | POST | участник и выше | `SPACE_OK`, `FOCUS` | «Стоп»: куски с сервера — в распознавание | `id` | — |
| `/api/rec/status` | GET | любой вошедший | `SPACE_OK`, `FOCUS` | Какие куски записи уже на сервере (после обрыва) | `id` | — |
| `/api/stt` | POST | участник и выше | `SPACE_OK`, `FOCUS` | Распознать голос; `?job=1` — фоново (GAS-34) | `тело — звук, Content-Type` | `text`, `fallback` |
| `/api/stt/job` | GET | любой вошедший | `SPACE_OK`, `FOCUS` | Фоновое распознавание: состояние и текст | `id` | — |
| `/api/stt/retry` | POST | участник и выше | `SPACE_OK`, `FOCUS` | Повторить нераспознанную запись (она хранится на сервере) | `id` | — |
| `/api/stt/stream` | GET | без входа | `SPACE_OK` | Голос потоком: WebSocket к службе T-one; вход — первым сообщением | `WebSocket` | — |
| `/api/tts` | GET | любой вошедший | `SPACE_OK`, `FOCUS`, `DEMO` | Озвучить ответ: звук (audio/mpeg) | `w`, `msg`, `full`, `head` | `audio/mpeg` |
| `/api/tts/about` | GET | любой вошедший | `SPACE_OK`, `FOCUS` | «Что здесь умеет» — голосом (текст из карты помощника) | `screen` | — |
| `/api/tts/warm` | GET | любой вошедший | `SPACE_OK`, `FOCUS`, `DEMO` | Прогреть синтез речи, когда открыли сессию (#190) | `w` | — |
| `/api/voice/cards` | GET | любой вошедший | `SPACE_OK` | Карточки голосов для выбора | — | — |
| `/api/voice/choose` | POST | владелец | — | Выбрать голос озвучки | `id` | — |
| `/api/voice/preview` | GET | любой вошедший | — | Образец голоса (audio/mpeg) | `id` | `audio/mpeg` |

## Проекты и чаты

| Путь | Метод | Кто | Метки | Что делает | Вход | Выход |
|---|---|---|---|---|---|---|
| `/api/chat/delete` | POST | владелец | — | «Удалить» сессию или чат: окно закрыто, журнал — в корзину | `force`, `w`, `id`, `sid` | — |
| `/api/chat/mcp` | POST | владелец и админ | — | Интеграции посреди чата: запомнить и перезапустить с --resume | `w`, `off` | — |
| `/api/chat/move` | POST | владелец | — | «Перенести в проект…»: журнал и окно (--resume) — в папку проекта; идёт ход — после | — | — |
| `/api/chat/restore` | POST | владелец | — | «Вернуть» чат из корзины | `id` | — |
| `/api/chat/trash` | GET | владелец | — | Корзина чатов и скрытые чаты | — | — |
| `/api/project` | GET | любой вошедший | `SPACE_OK`, `FOCUS_PROJ` | Карточка проекта: папка, сессии, инструкции | `id` | — |
| `/api/project/chat` | POST | участник и выше | — | Переименовать или скрыть чат проекта | `title`, `hidden`, `id`, `sid` | — |
| `/api/project/history` | GET | любой вошедший | `SPACE_OK`, `FOCUS_PROJ` | Переписка завершённого чата — без окна | `before`, `id`, `sid` | — |
| `/api/project/new` | POST | участник и выше | `SPACE_OK`, `cap:cap.dev_sessions` | «Новый проект»: папка, инструкции, первая сессия | `name`, `instructions`, `folder`, `profile`, `model` | — |
| `/api/project/resume` | POST | участник и выше | `SPACE_OK`, `BUDGET`, `FOCUS_PROJ` | «Продолжить» завершённый чат проекта | `id`, `sid` | — |
| `/api/project/session` | POST | участник и выше | `SPACE_OK`, `BUDGET`, `FOCUS_PROJ` | «Новая сессия в проекте» — ещё одно окно со своим журналом | `id`, `effort`, `profile`, `mcp_off`, `model` | — |
| `/api/project/sessions` | GET | любой вошедший | `SPACE_OK`, `FOCUS_PROJ` | Завершённые чаты проекта (журналы без окна), страницами | `before`, `id`, `q` | — |
| `/api/project/update` | POST | владелец | — | Меню проекта: название и архив | `name`, `archived`, `id` | — |
| `/api/projects` | GET | любой вошедший | `SPACE_OK` | «Проекты» для главной: проекты, порядок, сессии, лимиты — одним запросом | `archived`, `q` | `projects`, `order`, `sessions`, `now`, `host`, `build`, `limits`, `tasks`, `new_root`, `cost`, `fallback`, `space`, `space_projects` |

## Команды на сервере и терминал

| Путь | Метод | Кто | Метки | Что делает | Вход | Выход |
|---|---|---|---|---|---|---|
| `/api/commands` | GET | любой вошедший | — | Журнал выполненных команд | — | — |
| `/api/commands/mark` | POST | владелец | — | Отметить команду сделанной | `id`, `done` | — |
| `/api/commands/output` | GET | владелец | — | Вывод команды из журнала | `id` | `out` |
| `/api/commands/run` | POST | владелец | `CONFIRM` | Выполнить команду из журнала ещё раз | `id`, `confirmed` | — |
| `/api/commands/term` | POST | владелец | `CONFIRM` | Команда из журнала — в окне терминала | `id`, `confirmed` | — |
| `/api/desktop/mobile` | POST | владелец | `CONFIRM` | Мобильный вид сайтов, пока стол смотрят с телефона | `on`, `w`, `h`, `dpr` | — |
| `/api/desktop/open` | POST | владелец | `CONFIRM` | Открыть «Рабочий стол» (noVNC): одноразовая ссылка | — | — |
| `/api/desktop/tabs` | POST | владелец | `CONFIRM` | Вкладки Chrome рабочего стола (для телефона) | `idle`, `id`, `op`, `url` | — |
| `/api/desktop/tabs/act` | POST | владелец | `CONFIRM` | Действие с вкладкой: open, new, close, go, back, forward | `op`, `id`, `url`, `idle` | — |
| `/api/desktop/tabs/shot` | POST | владелец | `CONFIRM` | Снимок вкладки рабочего стола | `id`, `idle`, `op`, `url` | — |
| `/api/desktop/url` | POST | владелец | `CONFIRM` | Открыть ссылку вкладкой в Chrome рабочего стола | `url` | — |
| `/api/gate/desktop` | GET | без входа | — | Проверка входа для Caddy (forward_auth) рабочего стола: только владелец | — | — |
| `/api/links/prefs` | GET | владелец | — | Где открывать ссылки сайтов: на рабочем столе или здесь | `open`, `host` | `sites` |
| `/api/links/prefs` | POST | владелец | — | Где открывать ссылки сайтов: на рабочем столе или здесь | `open`, `host` | `sites` |
| `/api/run` | POST | владелец | `CONFIRM` | «Выполнить» команду из ответа на сервере пульта | `w`, `i`, `sha`, `confirmed` | — |
| `/api/run/term` | POST | владелец | `CONFIRM` | Команда из ответа в окне терминала (нужен ввод) | `w`, `i`, `sha`, `confirmed` | — |
| `/api/shell/open` | POST | владелец | `CONFIRM` | «Терминал» рядом с «Ubuntu»: окно ubuntu-shell | — | `id`, `name` |
| `/api/term` | GET | владелец | — | Окно терминала панели: экран и живо ли | `id` | — |
| `/api/term/close` | POST | владелец | — | Закрыть окно терминала | `id` | `ok` |
| `/api/term/key` | POST | владелец | `CONFIRM` | Клавиша в окно терминала (Ctrl+C, Ctrl+D, Enter) | `id`, `key` | `ok` |
| `/api/term/type` | POST | владелец | `CONFIRM` | Строка (в том числе пароль) в окно терминала; из Mini App — нет | `id`, `text` | `ok` |
| `/api/tty` | GET | участник и выше | `TTY`, `SPACE_OK`, `cap:cap.dev_terminal` | Живой терминал: история окна страницами (задача 50) | `w`, `start`, `end`, `all`, `color` | `w`, `name`, `kind`, `path`, `login` |
| `/api/tty/key` | POST | участник и выше | `CONFIRM`, `TTY`, `SPACE_OK`, `cap:cap.dev_terminal` | Живой терминал: клавиша | `w`, `cols`, `rows`, `reset`, `key`, `text` | `ok` |
| `/api/tty/size` | POST | участник и выше | `TTY`, `SPACE_OK` | Живой терминал: размер окна | `w`, `cols`, `rows`, `reset`, `key`, `text` | `ok` |
| `/api/tty/type` | POST | участник и выше | `CONFIRM`, `TTY`, `SPACE_OK`, `cap:cap.dev_terminal` | Живой терминал: текст в окно | `w`, `cols`, `rows`, `reset`, `key`, `text` | `ok` |

## Задачи и брифинг

| Путь | Метод | Кто | Метки | Что делает | Вход | Выход |
|---|---|---|---|---|---|---|
| `/api/brief` | GET | владелец | — | Брифинг первого лица (GAS-18): почта и календарь, собирает код | `fresh` | — |
| `/api/brief/act` | POST | владелец | — | Ответ на пункт брифинга: «Да / Нет / Позже» | `act` | — |
| `/api/brief/prefs` | POST | владелец | — | Настройки брифинга: источники, время, дни, пояс | — | — |
| `/api/tasks` | GET | владелец | — | Задачи владельца (#203); не менялись — 304 без тела | — | — |
| `/api/tasks/add` | POST | владелец | — | Добавить задачу руками | — | — |
| `/api/tasks/remove` | POST | владелец | — | Удалить задачу | `id` | `ok` |
| `/api/tasks/run` | POST | владелец | `CONFIRM` | «Выполнить» команду задачи | `confirmed`, `id` | — |
| `/api/tasks/update` | POST | владелец | — | Статус, «что дальше» и поля задачи | `id` | — |

## Модели, ключи, расход

| Путь | Метод | Кто | Метки | Что делает | Вход | Выход |
|---|---|---|---|---|---|---|
| `/api/balance/clear` | POST | владелец | — | «Я пополнил» — снова предлагать поставщика | `profile` | `ok` |
| `/api/cost/decide` | POST | владелец | — | Пауза по расходу: продолжить или остановить | `w`, `act` | `result` |
| `/api/cost/limits` | GET | владелец | — | Пороги расхода; POST — сохранить | — | — |
| `/api/cost/limits` | POST | владелец | — | Пороги расхода; POST — сохранить | — | — |
| `/api/fallback` | GET | владелец | — | Запасная цепочка поставщиков при лимите; POST — сохранить | `chain` | — |
| `/api/fallback` | POST | владелец | — | Запасная цепочка поставщиков при лимите; POST — сохранить | `chain` | — |
| `/api/funnel` | GET | владелец | — | Воронка продукта: вход → первый ответ → «Да» (funnel.py); арендатору — нет | `days`, `space` | — |
| `/api/keys` | POST | владелец | — | Сохранить ключ поставщика модели | `provider`, `key` | — |
| `/api/keys/remove` | POST | владелец | — | Удалить ключ поставщика | `provider` | `ok` |
| `/api/login/check` | POST | владелец | — | Шторка «Нужен вход»: проверить, вошла ли сессия | `w`, `kind` | — |
| `/api/login/code` | POST | владелец | — | Шторка «Нужен вход»: код или адрес — в окно сессии | `w`, `code` | `ok` |
| `/api/models` | POST | владелец | — | Профили моделей: адрес, основная и быстрая модель | `base_url`, `profile`, `main`, `fast` | `profiles` |
| `/api/openrouter/info` | GET | владелец | — | OpenRouter: подключён ли, баланс | — | — |
| `/api/openrouter/models` | GET | владелец | — | Список моделей OpenRouter | — | `models` |
| `/api/openrouter/start` | POST | владелец | — | Вход в OpenRouter: ссылка на авторизацию (PKCE) | — | `url` |
| `/api/selftest` | GET | владелец | — | Автотест поставщиков: итог; POST — «Проверить сейчас» в фоне | — | `started` |
| `/api/selftest` | POST | владелец | — | Автотест поставщиков: итог; POST — «Проверить сейчас» в фоне | — | `started` |
| `/api/setup/cancel` | POST | владелец | — | Мастер: отменить вход | — | `ok` |
| `/api/setup/code` | POST | владелец | — | Мастер: код входа — в окно | `code` | — |
| `/api/setup/login` | POST | владелец | — | Мастер: окно входа Claude Code и ссылка с экрана | — | — |
| `/api/setup/status` | GET | владелец | — | Мастер: вошёл ли Claude Code на сервере | `fresh` | — |
| `/api/spend` | GET | владелец | — | Расход по ценам API за период (spend.py) | `period` | — |

## Платежи

| Путь | Метод | Кто | Метки | Что делает | Вход | Выход |
|---|---|---|---|---|---|---|
| `/api/billing/invoice` | GET | владелец | — | Платежи: один счёт с суммами строкой | `id` | — |
| `/api/billing/invoice/issue` | POST | владелец | `CONFIRM` | Платежи: выставить счёт | `key`, `id` | — |
| `/api/billing/invoice/new` | POST | владелец | `CONFIRM` | Платежи: новый счёт | `key`, `client`, `currency`, `lines`, `space`, `due_days` | — |
| `/api/billing/invoice/pay` | POST | владелец | `CONFIRM` | Платежи: отметить оплату | `key`, `id`, `reason`, `ref` | — |
| `/api/billing/invoice/void` | POST | владелец | `CONFIRM` | Платежи: аннулировать счёт | `key`, `id`, `reason` | — |
| `/api/billing/invoices` | GET | владелец | — | Платежи: счета | — | — |
| `/api/billing/plan` | POST | владелец | `CONFIRM` | Платежи: новый тариф; `key` — повтор не дублирует | `key`, `code`, `title`, `price`, `amount`, `currency`, `period` | — |
| `/api/billing/plans` | GET | владелец | — | Платежи: тарифы | — | — |

## Интеграции, репозитории, модули

| Путь | Метод | Кто | Метки | Что делает | Вход | Выход |
|---|---|---|---|---|---|---|
| `/api/calendars/key` | POST | владелец | — | Секрет календаря: в файл 0600 и проверка | `kind` | — |
| `/api/calendars/key/remove` | POST | владелец | — | Удалить секрет календаря | `kind` | — |
| `/api/calendars/keys` | GET | владелец | — | Подключённые календари — без значений секретов | — | `calendars` |
| `/api/consent` | GET | участник и выше | `SPACE_OK`, `FOCUS` | Согласие на подключение: GET — текст экрана, версия `v` и подтверждённое `given`; POST — записать «аккаунт мой, ответственность моя» на подключение `what` (только добавлением). Без согласия подключение отвечает 409 `code=consent` | `what`, `title`, `accepted` | `v`, `given`, `consent`, `ok` |
| `/api/consent` | POST | участник и выше | `SPACE_OK`, `FOCUS` | Согласие на подключение: GET — текст экрана, версия `v` и подтверждённое `given`; POST — записать «аккаунт мой, ответственность моя» на подключение `what` (только добавлением). Без согласия подключение отвечает 409 `code=consent` | `what`, `title`, `accepted` | `v`, `given`, `consent`, `ok` |
| `/api/drafts` | GET | любой вошедший | `SPACE_OK` | Черновики действий коннекторов: «Ждут вашего Да» | — | `drafts` |
| `/api/drafts/check` | POST | без входа | — | Коннектор перед выполнением: нажал ли человек «Да» ровно на этот черновик (одноразово); секрет — заголовок X-GP-Local или X-GP-Space-Token | `svc`, `id`, `digest` | — |
| `/api/drafts/no` | POST | участник и выше | `SPACE_OK` | «Нет» черновику | `svc`, `id` | — |
| `/api/drafts/yes` | POST | участник и выше | `CONFIRM`, `SPACE_OK` | «Да» черновику — выполнить ровно его | `svc`, `id` | — |
| `/api/mcp` | GET | участник и выше | `FOCUS`, `cap:cap.dev_models_mcp` | Интеграции: подключённые, готовые наборы, коннекторы, разделы `cats` и карточки `cards`; `catalog=1` — только каталог, без опроса серверов (`servers: null`) | `catalog`, `fresh` | `servers`, `presets`, `connectors`, `connectors_url`, `personal`, `cats`, `cards` |
| `/api/mcp/add` | POST | участник и выше | `cap:cap.dev_models_mcp` | Подключить интеграцию из набора | `preset`, `name`, `values` | `result` |
| `/api/mcp/connected` | GET | участник и выше | `FOCUS`, `cap:cap.dev_models_mcp` | Подключилась ли интеграция после входа | `id` | `found`, `ok`, `state` |
| `/api/mcp/finish` | POST | участник и выше | `FOCUS`, `cap:cap.dev_models_mcp` | Завершить вход в интеграцию по адресу возврата | `w`, `url`, `name` | `result` |
| `/api/mcp/login` | POST | участник и выше | `cap:cap.dev_models_mcp` | Вход в интеграцию (OAuth): ссылка | `name` | — |
| `/api/mcp/remove` | POST | участник и выше | `cap:cap.dev_models_mcp` | Отключить интеграцию | `name` | `result` |
| `/api/module/delete` | POST | владелец | — | Удалить модуль | `w`, `state`, `confirm` | — |
| `/api/module/schedule` | POST | участник и выше | — | Расписание модуля: оставить, приостановить, выключить | `w`, `state`, `confirm` | — |
| `/api/modules` | GET | любой вошедший | — | Модули-агенты и их расписание | — | — |
| `/api/modules/create` | POST | участник и выше | — | Создать модуль-агента | `id`, `name`, `profile`, `lang`, `again` | — |
| `/api/repos` | GET | любой вошедший | `SPACE_OK`, `FOCUS` | Репозитории GitHub сессии: подключённые и доступные | — | — |
| `/api/repos/add` | POST | участник и выше | `SPACE_OK`, `FOCUS` | Подключить репозиторий: клон и /add-dir | `repo`, `path` | — |
| `/api/repos/remove` | POST | участник и выше | `SPACE_OK`, `FOCUS` | Отключить репозиторий | `repo`, `path` | — |

## Мост к браузеру

| Путь | Метод | Кто | Метки | Что делает | Вход | Выход |
|---|---|---|---|---|---|---|
| `/api/bridge/bridge.mjs` | GET | без входа | — | Файл моста для установщика | — | `text/javascript` |
| `/api/bridge/claim` | POST | без входа | — | Мост: одноразовый код → токен устройства | `code`, `name`, `os`, `old` | — |
| `/api/bridge/code` | POST | без входа | — | Код пары из командной строки сервера (тот же секрет) | — | — |
| `/api/bridge/confirm` | POST | владелец | — | «Да» действию моста | `id` | `ok` |
| `/api/bridge/devices` | GET | владелец | — | Компьютеры с мостом к браузеру | — | `devices` |
| `/api/bridge/drafts` | GET | владелец | — | Что ждёт «Да» человека на мосту | — | `drafts` |
| `/api/bridge/install.ps1` | GET | без входа | — | Установщик моста (Windows) — по коду пары `c`; `do=remove` — удаление | `c`, `do` | `text/plain` |
| `/api/bridge/install.sh` | GET | без входа | — | Установщик моста (macOS, Linux) одной командой — по коду пары `c`; `do=remove` — удаление | `c`, `do` | `text/plain` |
| `/api/bridge/log` | GET | владелец | — | Журнал действий моста по устройству | `id` | `log` |
| `/api/bridge/pair` | POST | владелец | — | Одноразовый код пары (10 мин) для моста | — | — |
| `/api/bridge/private` | POST | владелец | — | «Личные данные не уходят модели» для устройства | `on`, `id` | `ok` |
| `/api/bridge/reject` | POST | владелец | — | «Нет» действию моста | `id` | `ok` |
| `/api/bridge/revoke` | POST | владелец | — | Отключить компьютер | `id` | `ok` |
| `/api/bridge/rpc` | POST | без входа | — | Агент (gas-pult bridge-mcp) → мост; секрет — файл 0600 на сервере | — | — |
| `/api/bridge/ws` | GET | без входа | — | Мост: WebSocket с компьютера; токен — в подпротоколе | `WebSocket` | — |

## Мессенджеры

| Путь | Метод | Кто | Метки | Что делает | Вход | Выход |
|---|---|---|---|---|---|---|
| `/api/messengers` | GET | владелец | — | Мессенджеры: состояние подключений без секретов | — | — |
| `/api/messengers/allow` | POST | владелец | — | Мессенджеры: какие чаты видит модель | `svc`, `chats`, `accepted` | `allowed` |
| `/api/messengers/chats` | POST | владелец | — | Мессенджеры: чаты для «Чаты для модели» | `svc`, `accepted` | `chats` |
| `/api/messengers/consent` | POST | владелец | — | Мессенджеры: согласие «Понимаю, подключить» или отмена | `svc`, `accepted` | — |
| `/api/messengers/link` | POST | владелец | — | Signal / WhatsApp: привязка — QR картинкой | `svc`, `accepted` | `linked`, `qr` |
| `/api/messengers/off` | POST | владелец | — | Мессенджеры: отключить | `svc`, `accepted` | — |
| `/api/messengers/tg/code` | POST | владелец | — | Telegram: код входа | `svc`, `code`, `accepted` | — |
| `/api/messengers/tg/login` | POST | владелец | — | Telegram: api_id/api_hash в файл 0600, номер → код в Telegram | `svc`, `api_id`, `api_hash`, `phone`, `accepted` | — |
| `/api/messengers/tg/password` | POST | владелец | — | Telegram: пароль двухэтапной проверки | `svc`, `password`, `accepted` | — |

## Фокус-ссылки

| Путь | Метод | Кто | Метки | Что делает | Вход | Выход |
|---|---|---|---|---|---|---|
| `/api/focus/ask` | POST | без входа | — | «Попросить доступ»: ссылка не открылась — запрос владельцам (до входа, 3 за 10 минут с адреса) | `token`, `id`, `why`, `note` | `ok` |
| `/api/focus/asks` | GET | владелец | — | Запрос доступа по фокус-ссылке и его ссылка — для владельца | `id` | `id`, `rid`, `name`, `why`, `note`, `device`, `at`, `link` |
| `/api/focus/auto` | POST | владелец | — | Ссылка на проект: новые окна владельца в папке видны человеку (вкл/выкл) | `id`, `on` | `ok` |
| `/api/focus/bridge` | GET | только по фокус-ссылке | `FOCUS` | Фокус-ссылка: свой компьютер с мостом | — | — |
| `/api/focus/bridge/pair` | POST | только по фокус-ссылке | `FOCUS` | Фокус-ссылка: код пары своего компьютера | — | — |
| `/api/focus/bridge/private` | POST | только по фокус-ссылке | `FOCUS` | Фокус-ссылка: «Личные данные не уходят модели» | `id`, `on` | `ok` |
| `/api/focus/bridge/revoke` | POST | только по фокус-ссылке | `FOCUS` | Фокус-ссылка: отключить свой компьютер | `id` | `ok` |
| `/api/focus/browser` | POST | владелец | — | Разрешить фокус-ссылке подключить свой браузер | `id`, `on` | `ok` |
| `/api/focus/device` | POST | владелец | `FOCUS` | «Открыть на другом устройстве»: одноразовая ссылка той же записи на 15 минут и QR; с фокус-ссылки — своя запись, у владельца — id | `id`, `base` | `url`, `exp`, `used`, `max`, `qr` |
| `/api/focus/list` | GET | владелец | — | Действующие фокус-ссылки — без токенов | — | `links` |
| `/api/focus/new` | POST | владелец | — | Новая фокус-ссылка: сессия, проект или пространство; права и срок | `space`, `base`, `ttl`, `max`, `rights`, `name`, `audience`, `w`, `proj`, `mode` | — |
| `/api/focus/open` | POST | без входа | — | Первое открытие фокус-ссылки: привязать устройство (cookie). Без согласия с политикой ПДн и условиями — 409 code=privacy, docs; повтор с privacy: true — согласие в журнал | `token`, `privacy` | `ok, name, id, mode; cookie` |
| `/api/focus/qr` | POST | владелец | — | QR ссылки (POST — адрес с токеном не попадает в журнал прокси) | `url` | — |
| `/api/focus/revoke` | POST | владелец | — | Погасить фокус-ссылку | `id` | `ok`, `links` |
| `/api/focus/send` | POST | владелец | — | Отправить ссылку себе в Telegram | `url` | — |

## Люди, вход, приглашения

| Путь | Метод | Кто | Метки | Что делает | Вход | Выход |
|---|---|---|---|---|---|---|
| `/api/clientlog` | POST | любой вошедший | `SPACE_OK` | Ошибка JS в браузере: тип, экран, место | `mid`, `kind`, `msg`, `at`, `screen` | `ok` |
| `/api/confirm/check` | POST | участник и выше | — | Подтвердили ли вход кнопкой в боте | `id`, `code` | `ok` |
| `/api/confirm/start` | POST | участник и выше | — | Код подтверждения новой сессии браузера: отправить | `id`, `code` | `ok` |
| `/api/confirm/verify` | POST | участник и выше | — | Код подтверждения: проверить | `id`, `code` | `ok` |
| `/api/country` | GET | любой вошедший | `SPACE_OK` | Страна человека; POST — выбрать | `code` | — |
| `/api/country` | POST | любой вошедший | `SPACE_OK` | Страна человека; POST — выбрать | `code` | — |
| `/api/email` | GET | любой вошедший | — | Своя почта для входа и оповещений | — | — |
| `/api/email/bind` | POST | любой вошедший | — | Привязать почту: отправить код | `email` | — |
| `/api/email/confirm` | POST | любой вошедший | — | Подтвердить почту кодом | `email`, `code` | — |
| `/api/email/options` | POST | любой вошедший | — | Почта: второй фактор и оповещения | `second_factor`, `notify` | — |
| `/api/email/remove` | POST | любой вошедший | — | Отвязать почту | — | — |
| `/api/feedback` | POST | любой вошедший | `SPACE_OK` | «Отзыв» | — | — |
| `/api/help/ask` | POST | любой вошедший | `и до входа`, `TERMS_FREE`, `SPACE_OK` | Помощник «? Подсказать»: ответ по карте помощи | `q`, `chip`, `ctx` | — |
| `/api/help/call` | POST | участник и выше | `SPACE_OK` | Тестировщик: «Позвать на помощь» — владельцу в бот | `w` | — |
| `/api/help/feedback` | POST | любой вошедший | `и до входа`, `TERMS_FREE`, `SPACE_OK` | Помощник: полезен ли ответ | `id`, `useful`, `action` | — |
| `/api/invite` | GET | без входа | — | Экран входа: «приглашение в …» — только для действующего кода | `code (query)` | — |
| `/api/invite/check` | POST | без входа | — | Лёгкий вход: проверить код приглашения | `code` | — |
| `/api/invite/device` | POST | любой вошедший | `SPACE_OK`, `SLINK_NO` | Ссылка для входа на другое устройство | `id` | — |
| `/api/invite/enter` | POST | без входа | — | Лёгкий вход: войти по коду приглашения | `code`, `name` | `state; cookie` |
| `/api/invite/new` | POST | владелец и админ | — | Приглашение: ссылка, короткий код и QR | `ttl`, `space`, `role`, `uses`, `access`, `plan`, `name` | `path`, `code`, `hint`, `ttl`, `uses`, `access` |
| `/api/invite/qr` | GET | любой вошедший | `SPACE_OK`, `SLINK_NO` | QR ссылки приглашения (картинка) | `u` | `image/svg+xml` |
| `/api/link/tg` | POST | любой вошедший | `SPACE_OK`, `SLINK_NO` | «Привязать Telegram»: ссылка на бота | — | `id`, `link`, `ttl` |
| `/api/login/2fa` | POST | без входа | — | Второй фактор: код с почты | `id`, `code` | `state; cookie` |
| `/api/login/email/start` | POST | без входа | — | Вход по почте: отправить код | `email` | — |
| `/api/login/email/verify` | POST | без входа | — | Вход по почте: проверить код | `email`, `code` | `state; cookie` |
| `/api/login/methods` | GET | без входа | — | Экран входа: какие способы входа включены | — | — |
| `/api/login/oidc/{provider}/{step}` | GET | без входа | — | Вход через Google или Яндекс ID: start — переход, back — возврат | `provider: google\|yandex, step: start\|back; code, state` | `302` |
| `/api/login/passkey/options` | POST | без входа | — | Вход по ключу (passkey): параметры WebAuthn | — | — |
| `/api/login/passkey/verify` | POST | без входа | — | Вход по ключу: проверить подпись | `id`, `credential` | `state; cookie` |
| `/api/login/start` | POST | без входа | — | Вход кодом из бота: начать | — | `id` |
| `/api/login/tg` | GET | без входа | — | Вход через Telegram: POST — начать (ссылка на бота), GET — ждать подтверждения | `POST: invite; GET: id (query)` | `POST: id, link, app, qr, ttl; GET: state (+cookie)` |
| `/api/login/tg` | POST | без входа | — | Вход через Telegram: POST — начать (ссылка на бота), GET — ждать подтверждения | `POST: invite; GET: id (query)` | `POST: id, link, app, qr, ttl; GET: state (+cookie)` |
| `/api/login/verify` | POST | без входа | — | Вход кодом из бота: проверить код | `id`, `code` | `ok; cookie` |
| `/api/logout` | POST | любой вошедший | `TERMS_FREE`, `SPACE_OK`, `FOCUS`, `DEMO`, `MEETING` | Выйти на этом устройстве | — | — |
| `/api/meta` | GET | любой вошедший | `TERMS_FREE`, `SPACE_OK`, `FOCUS`, `DEMO` | Кто я и что видно: роль, сборка, новое, настройки | — | `via`, `role`, `uid`, `build`, `whatsnew`, `prefs`, `ui`, `terms`, `tty`, `desktop`, `projects_ui`, `shares`, `country` |
| `/api/oidc` | GET | любой вошедший | — | Привязки Google и Яндекс ID | — | — |
| `/api/oidc/link` | POST | любой вошедший | — | Ссылка на привязку Google или Яндекс ID | `provider` | `url` |
| `/api/oidc/unlink` | POST | любой вошедший | — | Отвязать Google или Яндекс ID | `provider` | — |
| `/api/passkeys` | GET | любой вошедший | `SPACE_OK`, `SLINK_NO` | Свои ключи входа | — | — |
| `/api/passkeys/add` | POST | любой вошедший | `SPACE_OK`, `SLINK_NO` | Сохранить новый ключ входа | `credential`, `id`, `name` | `keys` |
| `/api/passkeys/options` | POST | любой вошедший | `SPACE_OK`, `SLINK_NO` | Новый ключ входа: параметры WebAuthn | — | — |
| `/api/passkeys/remove` | POST | любой вошедший | `SPACE_OK`, `SLINK_NO` | Удалить ключ входа | `id` | `keys` |
| `/api/people` | GET | владелец и админ | — | Люди и роли | — | `people` |
| `/api/people/access` | POST | владелец и админ | — | Продлить доступ на N дней (0 — бессрочно) | `id`, `days` | `people` |
| `/api/people/remove` | POST | владелец и админ | — | Убрать человека | `id` | `people` |
| `/api/people/role` | POST | владелец и админ | — | Назначить роль | `id`, `role` | `people` |
| `/api/persona` | GET | любой вошедший | `TERMS_FREE`, `SPACE_OK` | Вид панели и тумблеры возможностей — свои; потолок задаёт владелец | — | — |
| `/api/persona` | POST | любой вошедший | `TERMS_FREE`, `SPACE_OK` | Вид панели и тумблеры возможностей — свои; потолок задаёт владелец | — | — |
| `/api/prefs` | GET | любой вошедший | `TERMS_FREE`, `SPACE_OK` | Свои настройки: простой режим, язык, скорость речи | `lang`, `simple`, `rate` | `simple` |
| `/api/prefs` | POST | любой вошедший | `TERMS_FREE`, `SPACE_OK` | Свои настройки: простой режим, язык, скорость речи | `lang`, `simple`, `rate` | `simple` |
| `/api/team` | GET | владелец | — | Возможности людей (потолок разделов); POST — сохранить | `id`, `caps`, `sections`, `reset` | — |
| `/api/team` | POST | владелец | — | Возможности людей (потолок разделов); POST — сохранить | `id`, `caps`, `sections`, `reset` | — |
| `/api/team/say` | POST | владелец | — | Сообщение команды в чат окна или проекта (карточка «Команда»; в Claude не уходит) | `w`, `proj`, `text`, `kind` | `ok`, `msg` |
| `/api/terms` | GET | любой вошедший | `TERMS_FREE`, `SPACE_OK` | Условия использования: версия и пункты | — | — |
| `/api/terms/accept` | POST | любой вошедший | `TERMS_FREE`, `SPACE_OK` | Принять условия использования | `version` | — |
| `/api/tour` | GET | любой вошедший | `SPACE_OK` | Отметки короткого тура: пройден, «Не сейчас» | `tour`, `state` | — |
| `/api/tour` | POST | любой вошедший | `SPACE_OK` | Отметки короткого тура: пройден, «Не сейчас» | `tour`, `state` | — |
| `/api/uses` | POST | любой вошедший | `SPACE_OK`, `FOCUS` | Какие экраны открыты (только id, для замера) | `ids` | `n` |

## Уведомления

| Путь | Метод | Кто | Метки | Что делает | Вход | Выход |
|---|---|---|---|---|---|---|
| `/api/notify/prefs` | GET | любой вошедший | `SPACE_OK`, `SLINK_NO` | Куда и о чём сообщать (notifyroute.py); менять — владелец | — | — |
| `/api/notify/prefs` | POST | любой вошедший | `SPACE_OK`, `SLINK_NO` | Куда и о чём сообщать (notifyroute.py); менять — владелец | — | — |
| `/api/push/devices` | GET | любой вошедший | `SPACE_OK`, `SLINK_NO` | Уведомления: свои устройства | `dev` | `key`, `devices`, `items` |
| `/api/push/key` | GET | любой вошедший | `SPACE_OK`, `SLINK_NO` | Уведомления на телефон: ключ VAPID | `dev` | `key`, `devices`, `items` |
| `/api/push/last` | GET | любой вошедший | `SPACE_OK`, `SLINK_NO` | Уведомления: последнее (текст по сигналу без содержимого) | `dev` | `key`, `devices`, `items` |
| `/api/push/subscribe` | POST | любой вошедший | `SPACE_OK`, `SLINK_NO` | Уведомления: подписать устройство | `sub`, `label`, `id` | `ok`, `devices`, `list` |
| `/api/push/test` | POST | любой вошедший | `SPACE_OK`, `SLINK_NO` | Уведомления: пробное | `sub`, `label`, `id` | `ok`, `devices`, `list` |
| `/api/push/unsubscribe` | POST | любой вошедший | `SPACE_OK`, `SLINK_NO` | Уведомления: отписать устройство | `sub`, `label`, `id` | `ok`, `devices`, `list` |

## «Поделиться»

| Путь | Метод | Кто | Метки | Что делает | Вход | Выход |
|---|---|---|---|---|---|---|
| `/api/share` | POST | без входа | — | «Поделиться» с iPhone: токен устройства, не кука | `Authorization, Content-Type; тело` | — |
| `/api/share/devices` | GET | любой вошедший | — | Устройства «Поделиться» (iPhone) | — | `devices` |
| `/api/share/devices/new` | POST | участник и выше | — | Токен «Быстрой команды» — показывается один раз | `name` | — |
| `/api/share/devices/revoke` | POST | участник и выше | — | Отозвать токен устройства | `id` | — |
| `/api/share/done` | POST | участник и выше | — | Запись разобрана: сохранили во «Входящие» или отправили | `id` | — |
| `/api/share/file` | GET | любой вошедший | — | Миниатюра картинки своей записи | `id`, `i` | — |
| `/api/share/list` | GET | любой вошедший | — | «Поделились» — свои неразобранные записи | — | — |

## Пространства

| Путь | Метод | Кто | Метки | Что делает | Вход | Выход |
|---|---|---|---|---|---|---|
| `/api/space/budget/add` | POST | владелец | — | «+ добавить» к бюджету пространства | `space`, `usd` | — |
| `/api/space/close` | POST | участник и выше | `SPACE_OK`, `FOCUS` | Завершить сессию пространства | `force`, `w` | — |
| `/api/space/connect` | POST | владелец и админ | — | Владелец подключается к окну пространства | `w` | — |
| `/api/space/delete` | POST | участник и выше | `SPACE_OK` | Удалить сессию пространства (в корзину) | `folder`, `confirm` | — |
| `/api/space/download` | GET | любой вошедший | `SPACE_OK`, `FOCUS` | Скачать файл из папки сессии пространства | `f` | `файл` |
| `/api/space/files` | GET | любой вошедший | `SPACE_OK`, `FOCUS` | Файлы папки сессии пространства | `f` | — |
| `/api/space/mcp` | GET | любой вошедший | `SPACE_OK` | Свои интеграции пространства — без ключей | — | `servers`, `space`, `presets` |
| `/api/space/mcp/add` | POST | участник и выше | `SPACE_OK` | Подключить интеграцию в своём пространстве | `preset`, `name`, `values` | — |
| `/api/space/mcp/remove` | POST | участник и выше | `SPACE_OK` | Отключить интеграцию в своём пространстве | `preset`, `name`, `values` | — |
| `/api/space/restore` | POST | участник и выше | `SPACE_OK` | Вернуть сессию пространства из корзины | `id` | — |
| `/api/space/resume` | POST | участник и выше | `SPACE_OK`, `BUDGET` | Продолжить закрытую сессию пространства | `folder` | — |
| `/api/space/sessions` | GET | любой вошедший | `SPACE_OK` | Закрытые сессии пространства и корзина | — | — |
| `/api/space/task` | POST | владелец | — | Поставить задачу в пространство | `space`, `name`, `task` | — |
| `/api/space/upload` | POST | участник и выше | `SPACE_OK`, `FOCUS` | Файл в папку сессии пространства | `тело — байты файла, X-File-Name; w (query)` | `name` |
| `/api/spaces` | GET | владелец и админ | — | Пространства и их бюджет | — | — |

## Протоколы встреч

| Путь | Метод | Кто | Метки | Что делает | Вход | Выход |
|---|---|---|---|---|---|---|
| `/api/meeting` | GET | владелец | — | Протокол встречи: оглавление, «Что сделать», текст, ссылки на него | `id` | — |
| `/api/meeting/audio` | GET | владелец | — | Запись встречи (звук) | `id` | `аудио` |
| `/api/meeting/card` | GET | владелец | — | Карточка-превью протокола (SVG 1200×630) | `id` | `image/svg+xml` |
| `/api/meeting/share` | POST | владелец | — | «Ссылка на протокол»: фокус-ссылка на один протокол, 30 дней, до 50 устройств | `base`, `id` | — |
| `/api/meetings` | GET | владелец | — | Протоколы встреч: список | — | — |
| `/api/mt` | GET | только по фокус-ссылке | `MEETING` | По ссылке на протокол: протокол без черновика и ссылок (id — из записи ссылки) | — | `exp` |
| `/api/mt/audio` | GET | только по фокус-ссылке | `MEETING` | По ссылке на протокол: запись встречи | — | `аудио` |
| `/api/mt/card` | GET | только по фокус-ссылке | `MEETING` | По ссылке на протокол: карточка-превью | — | `image/svg+xml` |

## Анкеты и предложения клиентам

| Путь | Метод | Кто | Метки | Что делает | Вход | Выход |
|---|---|---|---|---|---|---|
| `/api/offer/{code}` | GET | без входа | — | Предложение клиенту по коду: страница данных и демо-сессия | — | `session`, `bot` |
| `/api/offer/{code}/{act}` | POST | без входа | — | Действие на странице предложения: upload, forget, wizard, login, help, helpfb, telegram | `act` | — |
| `/api/q/answers` | GET | владелец | — | Ответы клиента на анкету | `id` | — |
| `/api/q/list` | GET | владелец | — | «Анкеты клиентов»: ссылки без кодов и формы | — | `links`, `forms` |
| `/api/q/new` | POST | владелец | — | Новая личная ссылка на анкету клиента | `form`, `client`, `days` | — |
| `/api/q/{code}` | GET | без входа | — | Анкета по личному коду: форма (с glossary — пояснениями терминов, если есть) и черновик | — | `form`, `draft`, `sent` |
| `/api/q/{code}/save` | POST | без входа | — | Анкета: сохранить черновик | `answers` | `ok` |
| `/api/q/{code}/submit` | POST | без входа | — | Анкета: отправить; без privacy: true (галочка согласия с политикой ПДн) — 409 code=privacy, docs | `answers`, `privacy` | — |

## API v1 для 1С и CRM

| Путь | Метод | Кто | Метки | Что делает | Вход | Выход |
|---|---|---|---|---|---|---|
| `/api/apitokens` | GET | любой вошедший | `SPACE_OK`, `SLINK_NO` | Свои токены для 1С и CRM (без значений), условия и группы прав | — | `tokens`, `terms`, `groups` |
| `/api/apitokens/new` | POST | участник и выше | `SPACE_OK`, `SLINK_NO` | Новый токен: показывается один раз; группы прав, «запись», срок | `name`, `write`, `days`, `groups` | — |
| `/api/apitokens/revoke` | POST | участник и выше | `SPACE_OK`, `SLINK_NO` | Отозвать свой токен | `id` | — |
| `/api/v1/activity` | GET | по токену | `V1`, `v1:sessions` | По токену: `/api/activity` — Строка статуса чата: что агент делает сейчас (белый список `access.V1_*`, docs/API-V1.md) | `w` | — |
| `/api/v1/drafts` | GET | по токену | `V1`, `v1:drafts` | По токену: `/api/drafts` — Черновики действий коннекторов: «Ждут вашего Да» (белый список `access.V1_*`, docs/API-V1.md) | — | `drafts` |
| `/api/v1/history` | GET | по токену | `V1`, `v1:sessions` | По токену: `/api/history` — Переписка сессии страницами (новые сверху, `before` — раньше); `team` — сообщения команды (белый список `access.V1_*`, docs/API-V1.md) | `w`, `before`, `rev` | `team`, `same`, `rev`, `items`, `more` |
| `/api/v1/last` | GET | по токену | `V1`, `v1:sessions` | По токену: `/api/last` — Последний ответ агента текстом (для «Скопировать» и озвучки) (белый список `access.V1_*`, docs/API-V1.md) | `w` | `text` |
| `/api/v1/project` | GET | по токену | `V1`, `v1:sessions` | По токену: `/api/project` — Карточка проекта: папка, сессии, инструкции (белый список `access.V1_*`, docs/API-V1.md) | `id` | — |
| `/api/v1/project/history` | GET | по токену | `V1`, `v1:sessions` | По токену: `/api/project/history` — Переписка завершённого чата — без окна (белый список `access.V1_*`, docs/API-V1.md) | `before`, `id`, `sid` | — |
| `/api/v1/project/sessions` | GET | по токену | `V1`, `v1:sessions` | По токену: `/api/project/sessions` — Завершённые чаты проекта (журналы без окна), страницами (белый список `access.V1_*`, docs/API-V1.md) | `before`, `id`, `q` | — |
| `/api/v1/projects` | GET | по токену | `V1`, `v1:sessions` | По токену: `/api/projects` — «Проекты» для главной: проекты, порядок, сессии, лимиты — одним запросом (белый список `access.V1_*`, docs/API-V1.md) | `archived`, `q` | `projects`, `order`, `sessions`, `now`, `host`, `build`, `limits`, `tasks`, `new_root`, `cost`, `fallback`, `space`, `space_projects` |
| `/api/v1/send` | POST | по токену | `V1`, `v1:send` | По токену: `/api/send` — Отправить текст в сессию; повтор того же текста — `dup` (белый список `access.V1_*`, docs/API-V1.md) | `text`, `w`, `id` | `ok`, `dup` |
| `/api/v1/sessions` | GET | по токену | `V1`, `v1:sessions` | По токену: `/api/sessions` — Список сессий (окна tmux) для главной: статус, расход, лимиты (владельцу), задачи (белый список `access.V1_*`, docs/API-V1.md) | — | `sessions`, `host`, `build`, `now`, `cost`, `fallback`, `focus`, `space`, `limits`, `tasks` |
| `/api/v1/tasks` | GET | по токену | `V1`, `v1:tasks` | По токену: `/api/tasks` — Задачи владельца (#203); не менялись — 304 без тела (белый список `access.V1_*`, docs/API-V1.md) | — | — |
| `/api/v1/tasks/add` | POST | по токену | `V1`, `v1:tasks` | По токену: `/api/tasks/add` — Добавить задачу руками (белый список `access.V1_*`, docs/API-V1.md) | — | — |
| `/api/v1/tasks/update` | POST | по токену | `V1`, `v1:tasks` | По токену: `/api/tasks/update` — Статус, «что дальше» и поля задачи (белый список `access.V1_*`, docs/API-V1.md) | `id` | — |

## Прочее

| Путь | Метод | Кто | Метки | Что делает | Вход | Выход |
|---|---|---|---|---|---|---|
| `/api/bug` | POST | любой вошедший | `SPACE_OK`, `FOCUS` | «Сообщить об ошибке» из чата: задача владельцу и штабу, уведомление, в чат — «Приняли» | `w`, `text`, `ctx`, `shot` | `ok`, `task`, `ack` |
| `/api/deadlines` | GET | владелец | — | «Подписки и балансы»: сроки из реестров, неделя Claude, расход за сутки — только чтение | — | — |
| `/api/demo/info` | GET | без входа | — | Демо без входа: есть ли ролик «Смотреть, 1 мин» (/media/demo.mp4) | — | — |
| `/api/tracks` | GET | владелец | — | «Поручения»: что отправлено, кому и в каком состоянии — файл команды track, только чтение | — | — |
