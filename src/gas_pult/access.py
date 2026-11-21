"""Права на пути API панели (план модульного монолита, docs/MONOLITH-PLAN.md, шаг 1): кто куда может — одной
таблицей рядом с маршрутами. Перенесено из ``webapp.py`` без изменений; ``webapp`` реэкспортирует все имена.

Таблицы: ``OWNER_ONLY`` (только владелец), ``ADMIN_OK`` (что из владельческого можно админу), ``MEMBER_ONLY``,
``CONFIRM`` (команды на сервере — через подтверждение кодом), ``TERMS_FREE`` / ``COUNTRY_FREE`` (до условий и страны),
``SPACE_OK`` (тестировщику пространства), ``FOCUS_GET`` / ``FOCUS_POST`` / ``FOCUS_NO_W`` (фокус-ссылка),
``DEMO_GET`` / ``DEMO_POST`` (демо-ссылка), ``FOCUS_PROJ_*`` (фокус-ссылка на проект), ``BUDGET_PATHS`` (расход
пространства).
"""

import re

STT_STREAM = "/api/stt/stream"                            # голос потоком: WebSocket → служба T-one (задача 46)

# Только владельцу: выполнение команд, закрытие сессий, ключи, модели, люди.
TERM = ("/api/term", "/api/run/term", "/api/commands/term", "/api/term/type", "/api/term/key", "/api/term/close")
OWNER_ONLY = {"/api/bridge/devices", "/api/bridge/pair", "/api/bridge/revoke", "/api/bridge/log",
              "/api/focus/browser",
              "/api/media", "/api/run", "/api/commands/run", "/api/commands/mark", "/api/commands/output", "/api/close",
              "/api/restart", "/api/keys", "/api/keys/remove", "/api/providers", "/api/voice/choose",
              "/api/models", "/api/openrouter/start", "/api/openrouter/info", "/api/openrouter/models",
              "/api/people", "/api/people/role", "/api/people/remove", "/api/fallback", "/api/team",
              "/api/cost/limits", "/api/cost/decide",
              "/api/model/default", "/api/balance/clear", "/api/module/delete", *TERM,
              "/api/chat/delete", "/api/chat/restore", "/api/chat/trash", "/api/stopped/clear", "/api/notify/level",
              "/api/desktop/open",
              "/api/tasks", "/api/tasks/add", "/api/tasks/update", "/api/tasks/remove", "/api/tasks/run",
              "/api/focus/new", "/api/focus/send", "/api/focus/qr", "/api/focus/list", "/api/focus/revoke",
              "/api/spaces", "/api/invite/new", "/api/space/task", "/api/space/connect", "/api/space/budget/add",
              "/api/setup/status", "/api/setup/login", "/api/setup/code", "/api/setup/cancel",
              "/api/login/code", "/api/login/check"}          # шторка «Нужен вход» (logins.py) — только владельцу
# Админ (people.py, владелец 17.11): из владельческого — только люди, приглашения, пространства (смотреть и
# подключаться) и перезапуск сессий без смены модели. Ключи, деньги, команды на сервере, пространства — нет.
ADMIN_OK = {"/api/people", "/api/people/role", "/api/people/remove", "/api/people/access", "/api/spaces",
            "/api/invite/new", "/api/space/connect", "/api/restart"}
OWNER_ONLY |= {"/api/people/access"}
OWNER_ONLY |= {"/api/q/new", "/api/q/list", "/api/q/answers"}   # анкеты клиентов (0010) — только владелец
# Интеграции на чат посреди чата — перезапуск окна, как /api/restart: владелец и админ (включить выключенное = доступ)
OWNER_ONLY |= {"/api/chat/mcp"}
ADMIN_OK |= {"/api/chat/mcp"}
# Подтверждение кодом (аудит 09.11): сессия браузера моложе суток (``webauth.CONFIRM_FRESH``) выполняет команды на
# сервере и пишет в терминал только после кода — ответ 403 ``{"code": "confirm", "confirm": "code"}``, панель покажет
# «Подтвердите кодом» и повторит запрос. Mini App в Telegram — доверенное устройство (код ушёл бы в тот же Telegram);
# фокус-ссылка — права и окно задал владелец, код ей прийти некуда.
CONFIRM = {"/api/run", "/api/run/term", "/api/tasks/run", "/api/desktop/open", "/api/commands/run",
           "/api/commands/term", "/api/term/type",
           "/api/term/key",
           "/api/tty/type", "/api/tty/key"}
CONFIRM_API = ("/api/confirm/start", "/api/confirm/verify", "/api/confirm/check")
# Участнику и владельцу, в том числе чтение: интеграции — у каждого свои (его папка Claude Code), наблюдателю — нет.
MEMBER_ONLY = {"/api/mcp", "/api/mcp/connected"}
# Живой терминал (задача 50): клавиши и текст прямо в окно, вся история tmux. Только в режиме разработчика (владелец
# и участник с «Экраном терминала» не в простом режиме — ``H.dev_tty``); наблюдателю, пространству и фокусу — нет.
TTY = ("/api/tty", "/api/tty/type", "/api/tty/key", "/api/tty/size")
MEMBER_ONLY |= set(TTY)
OWNER_PRESETS = {"stdio"}               # своя программа на сервере — только владельцу
SELFTEST = "/api/selftest"               # автотест поставщиков (selftest.py): итог и «Проверить сейчас» — владельцу
OWNER_ONLY |= {SELFTEST}
# Ссылки и терминал (владелец 17.11): вкладка в Chrome рабочего стола, выбор «где открыть» по сайту, окно ubuntu-shell
OWNER_ONLY |= {"/api/desktop/url", "/api/links/prefs", "/api/shell/open"}
OWNER_ONLY |= {"/api/calendars/keys", "/api/calendars/key", "/api/calendars/key/remove"}   # секреты календарей
OWNER_ONLY |= {"/api/project/update"}               # название и архив проекта — владельцу (GAS-24)
# Брифинг первого лица (GAS-18, brief.py): почта и календарь владельца — только ему
BRIEF = ("/api/brief", "/api/brief/prefs", "/api/brief/act")
OWNER_ONLY |= set(BRIEF)
CONFIRM |= {"/api/desktop/url", "/api/shell/open"}
# Мобильный вид сайтов в «Браузере» (deskmobile.py, 21.11): как сам стол — только владельцу и после кода
OWNER_ONLY |= {"/api/desktop/mobile"}
CONFIRM |= {"/api/desktop/mobile"}

# Вид панели (роль интерфейса и тумблеры возможностей) — своя настройка человека; потолок задаёт владелец.
PERSONA = "/api/persona"
# До согласия с условиями использования (terms.py) — только это; остальное API отвечает 403 с code="terms".
TERMS_FREE = {"/api/meta", "/api/terms", "/api/terms/accept", "/api/logout", "/api/help/ask", "/api/help/feedback",
              "/api/prefs", PERSONA}
# Помощник «? Подсказать» — любому вошедшему (и наблюдателю), а на экране входа — и до входа.
HELP_OPEN = ("/api/help/ask", "/api/help/feedback")
# Почта для входа и оповещений (emailcode.py) — своя у каждого вошедшего, в том числе у наблюдателя.
EMAIL_OWN = ("/api/email", "/api/email/bind", "/api/email/confirm", "/api/email/remove", "/api/email/options")
# Вход по почте и второй фактор — до входа (свои лимиты по адресу и IP).
EMAIL_LOGIN = ("/api/login/email/start", "/api/login/email/verify", "/api/login/2fa")
# Ключи входа (passkeys.py): свои у каждого вошедшего; вход по ключу — до входа (лимит по IP).
PASSKEY_OWN = ("/api/passkeys", "/api/passkeys/options", "/api/passkeys/add", "/api/passkeys/remove")
PASSKEY_LOGIN = ("/api/login/passkey/options", "/api/login/passkey/verify")
# Вход через Google и Яндекс ID (oidc.py): привязки — свои у каждого вошедшего; сам вход — переходами браузера.
OIDC_OWN = ("/api/oidc", "/api/oidc/link", "/api/oidc/unlink")
OIDC_PATH = re.compile(r"^/api/login/oidc/(google|yandex)/(start|back)$")
# Уведомления на телефон (webpush.py): подписки и «ящик» — свои у каждого вошедшего, в том числе у наблюдателя.
PUSH_OWN = ("/api/push/key", "/api/push/subscribe", "/api/push/unsubscribe", "/api/push/devices", "/api/push/test",
            "/api/push/last", "/api/notify/prefs")   # и каналы/события (notifyroute.py): менять — владелец
# «Сообщить по готовности» из строки статуса — и наблюдателю: только уведомление ему же в бот.
NOTIFY_DONE = "/api/notify-done"
# «Отзыв» (feedback.py): написать может каждый вошедший, в том числе наблюдатель и пространство.
FEEDBACK = "/api/feedback"
# Отметки короткого тура (пройден / «Не сейчас») — настройка самого человека: менять может и наблюдатель.
TOUR = "/api/tour"
# До выбора страны (country.py) — ещё и выбор страны; остальное — 403 с code="country".
COUNTRY_FREE = TERMS_FREE | {"/api/country"}
# Репозитории GitHub в сессии (задача 43, repos.py): к своей сессии — владелец и тестировщик пространства.
REPOS = ("/api/repos", "/api/repos/add", "/api/repos/remove")
# Тестировщик демо-пространства (задача 31): только это — и только с окнами своего пространства (spaces.Routed.scope).
# Остальное (папки и модули владельца, файлы, интеграции, ключи, люди, модели, расход владельца) — 403 code=space.
USES = "/api/uses"                      # панель отмечает открытые экраны и листы (features.py): только id, без людей
SPACE_OK = TERMS_FREE | set(PUSH_OWN) | set(TTY) | {USES, FEEDBACK,
    "/api/sessions", "/api/country", "/api/prefs", TOUR, "/api/activity", "/api/last", "/api/screen", "/api/ask",
    "/api/hint", "/api/history", "/api/tts", "/api/tts/warm", "/api/stt", "/api/voice/cards", "/api/scenarios",
    "/api/new",
    "/api/send", "/api/resend", "/api/key", "/api/select", "/api/command", "/api/rename", "/api/help/call",
    "/api/space/sessions", "/api/space/close", "/api/space/resume", "/api/space/delete", "/api/space/restore",
    "/api/space/files", "/api/space/upload", "/api/space/download", STT_STREAM, *REPOS,
    "/api/invite/device", "/api/invite/qr", "/api/link/tg", *("/api/passkeys", "/api/passkeys/options",
                                                            "/api/passkeys/add", "/api/passkeys/remove"),
}
# «Проекты» пространства (GAS-38): папки home/projects/<имя>, их чаты, «Новый чат в проекте», «Продолжить», «Новый
# проект» — только в своём пространстве (Handler.sp, space_projects.parse). Меню проекта, закрепления — нет.
SPACE_PROJ = ("/api/projects", "/api/project", "/api/project/sessions", "/api/project/history", "/api/project/session",
              "/api/project/resume", "/api/project/new")
SPACE_OK |= set(SPACE_PROJ)
# Что тратит деньги: тестировщику — только пока дневной бюджет пространства не исчерпан (клавиши, Esc — можно).
BUDGET_PATHS = {"/api/send", "/api/new", "/api/command", "/api/select", "/api/space/resume", "/api/project/session",
                "/api/project/resume"}
# Лёгкий вход (задача 34): ссылка для входа на другое устройство, её QR и «Привязать Telegram» — свои у каждого.
INVITE_OWN = ("/api/invite/device", "/api/invite/qr", "/api/link/tg")
# Фокус (задача 41, focus.py): с cookie фокуса — только чат одной сессии; окно ``w`` в запросе — только её.
# Настройки самой сессии — тоже здесь: модель, поставщик, усилия, файлы, интеграции (список и вход из её экрана).
# Нет: другие сессии, их создание и переключение, общие настройки пульта (ключи, люди, добавление интеграций).
# Нет и команд на сервере пульта (решение владельца 10.11): ни «Выполнить» (/api/run), ни терминала — только копировать.
FOCUS_GET = {"/api/meta", "/api/sessions", "/api/history", "/api/screen", "/api/ask", "/api/hint", "/api/cmds",
             "/api/tts", "/api/tts/warm", "/api/last", "/api/activity", "/api/space/files", "/api/space/download",
             "/api/mcp", "/api/mcp/connected", "/api/repos"}
FOCUS_POST = {"/api/send", "/api/resend", "/api/key", "/api/select", "/api/command", "/api/revive", "/api/upload",
              "/api/stt", "/api/space/upload", "/api/close", "/api/space/close", "/api/logout", "/api/model",
              "/api/effort", "/api/restart", "/api/mcp/finish", "/api/repos/add", "/api/repos/remove", "/api/uses"}
STT_JOB = ("/api/stt/job", "/api/stt/retry")       # фоновое распознавание (GAS-34): там же, где /api/stt
SPACE_OK |= set(STT_JOB) | {"/api/tts/about", "/api/clientlog", "/api/starters", "/api/starter", "/api/title",
                            "/api/steps"}
FOCUS_GET |= {"/api/tts/about", "/api/starters"}
# Фокус-ссылка — удобства своей сессии (владелец 19.11: «переименования, тёмный/светлый и все остальные»; GAS-13 п.4)
FOCUS_POST |= {"/api/rename", "/api/starter", "/api/title"}
FOCUS_GET |= {"/api/stt/job"}
FOCUS_POST |= {"/api/stt/retry"}
FOCUS_GET |= {"/api/focus/bridge"}                  # фокус-ссылка с «Браузер»: свой компьютер (владелец 17.11)
FOCUS_POST |= {"/api/focus/bridge/pair", "/api/focus/bridge/revoke"}
FOCUS_NO_W = {"/api/meta", "/api/sessions", "/api/upload", "/api/stt", "/api/logout", "/api/mcp",
              "/api/focus/bridge", "/api/focus/bridge/pair", "/api/focus/bridge/revoke",
              "/api/mcp/connected", "/api/uses"}   # без окна в запросе
FOCUS_NO_W |= set(STT_JOB) | {"/api/tts/about", "/api/starters", "/api/media"}
FOCUS_GET |= {"/api/media"}           # картинки в переписке по фокус-ссылке (papasan 19.11): только папки ссылки
# Демо-ссылка (``mode: "demo"``, focus.py): показ клиенту на нескольких устройствах — смотреть сессии (переписка,
# экран, статус, «Прослушать») и отвечать на вопрос Claude кнопками (/api/select, /api/key — стрелки и Enter, только
# когда на экране вопрос: ``Panel.demo_answer``). Нет: текста, файлов, голоса, модели, усилий, перезапуска,
# завершения, новых сессий, интеграций, репозиториев, команд — 403 focus_scope.
DEMO_GET = {"/api/meta", "/api/sessions", "/api/history", "/api/screen", "/api/activity", "/api/hint", "/api/tts",
            "/api/tts/warm", "/api/ask", "/api/last"}
DEMO_POST = {"/api/select", "/api/key", "/api/logout"}
# Фокус на проект (ссылка с ``proj``): весь проект — его окна, «Новая сессия в проекте», завершённые чаты; ``id``
# проекта в запросе — только её. Ссылке на одну сессию эти пути закрыты (403), как раньше.
FOCUS_PROJ_GET = {"/api/project", "/api/project/sessions", "/api/project/history"}
FOCUS_PROJ_POST = {"/api/project/session", "/api/project/resume"}
# Адрес клиента из заголовков прокси — только если запрос пришёл с этой машины (Caddy, cloudflared).
# Ссылка на пространство (GAS-38, focus.SPACE): права тестировщика этого пространства (SPACE_OK, та же изоляция), но
# без того, что привязывает устройство или человека мимо ссылки: вход на другом устройстве, ключи входа, уведомления.
SLINK = "slink"                                     # who()[0] для входа по ссылке на пространство
SLINK_HEADER = "X-Gp-Slink"                         # страница ссылки: проверяется только её cookie (не вход владельца)
SLINK_NO = set(INVITE_OWN) | set(PASSKEY_OWN) | set(PUSH_OWN) | {NOTIFY_DONE}
