# Мессенджеры «как пользователь»: Telegram, Signal, WhatsApp

Решение владельца 22.11 — **вариант А: человек решает сам**, зная условия сервисов. Панель → «Подключения» →
«Мессенджеры». Модель читает чаты; отправить людям может только черновиком — после «Да» человека в панели.
Входящие видны в «Сегодня» (брифинг собирает код, не модель).

| Мессенджер | Способ | Экран перед подключением | Что ставить на сервер |
|---|---|---|---|
| Telegram | свой аккаунт, MTProto (Telethon), свои api_id/api_hash с my.telegram.org | согласие по п. 1.5 Telegram API Terms | Telethon 1.45.0 (Python) |
| Signal | signal-cli как связанное устройство, QR | «Неофициальный способ… Решаете вы» | signal-cli 0.14.10 (native) |
| WhatsApp | не подключается с 23.11: личный аккаунт через неофициальный клиент запрещён правилами WhatsApp | — | уже подключённый — только «Отключить»; для компаний — WhatsApp Business Platform (Cloud API) |
| MAX | — | — | не делаем: вход пользователем запрещён соглашением MAX (п. 4.3.7, 4.4); только бот организации |

Условия сервисов (проверены 22.11): https://core.telegram.org/api/terms , https://telegram.org/tos/content-licensing ,
https://www.whatsapp.com/legal/terms-of-service , https://signal.org/legal/ , https://legal.max.ru/ps . Коротко:
- **Telegram.** Клиент на своём api_id разрешён (п. 2.1–2.2). Для ИИ п. 1.5 требует явного согласия **каждого
  участника конкретного чата**. Поэтому модель видит только чаты, которые человек отметил в «Чаты для модели».
- **Signal, WhatsApp.** Неофициальные клиенты нарушают условия сервисов; номер могут заблокировать. Экран выбора
  говорит это прямо и советует отдельный номер.

## Как устроено

```
панель (webapp.py) ─┐                         ┌─ Telethon (в том же процессе, свой Python)
MCP модели ─────────┼─ unix-сокет host.sock ─→ host.py ─┼─ signal-cli (короткие процессы; link — пока ждёт скан)
«Сегодня» (brief) ──┘   (0600, папка 0700)              └─ node wa_bridge.mjs (Baileys, строки JSON по stdio)
```

- `src/gas_pult/messengers/__init__.py` — каталог, папки, выбор человека (`consent.json`), запуск моста (`spawn`,
  `call`), состояние без секретов, входящие (`inbox.jsonl`), `recent()` для «Сегодня».
- `host.py` — процесс моста `python -m gas_pult.messengers.host <svc>`: сокет, операции, **сон по простою**.
- `tg.py`, `signal_cli.py`, `wa.py` + `wa_bridge.mjs` — по мосту на мессенджер.
- `mcp_server.py` — инструменты модели: `<svc>_chats`, `<svc>_read`, `<svc>_draft`, `<svc>_apply`.
  При подключении панель добавляет сервер `msg-<svc>` в настройки Claude Code владельца (`claude mcp add-json`).
- `panel.py` — API панели `/api/messengers…` (только владелец); интерфейс — `web/js/messengers.js`.

### Правила
- **Без выбора человека мост не стартует.** Два замка: `spawn()` и сам `host.py` проверяют `consent.json`
  (время, кто, версия текста экрана). «Отмена» запись снимает. Поменяли текст экрана — версия другая, человек решает
  заново.
- **Отправка — только черновиком.** У моста нет операции «отправить текст». Модель вызывает `<svc>_draft` →
  `connectors/_core.propose` → черновик в «Ждут вашего «Да»» (`drafts.py`). После «Да» модель вызывает
  `<svc>_apply <id>` → мост берёт черновик через `_core.take_confirmed` (отпечаток `.ok` ровно этого черновика,
  один раз) и только тогда отправляет.
- **Секреты.** api_id/api_hash — `telegram/api.json`, сессия Telegram — `telegram/tg.session`, вход WhatsApp —
  `whatsapp/auth/`, данные Signal — `signal/data/`, входящие — `<svc>/inbox.jsonl`. Всё в папке данных человека
  (`<данные пульта>/messengers`, у владельца `~/.local/share/gas-pult/messengers`; переопределить — `GAS_MSG_DIR`):
  папки 0700, файлы 0600. В ответы API, журнал, git они не попадают: номер — только последние 4 цифры, ссылка
  привязки — только картинкой QR.
- **«Отключить»** останавливает мост, стирает вход, ключи, входящие и выбор, убирает MCP-сервер. На телефоне
  связанное устройство человек убирает сам («Связанные устройства»).
- **Пространства** (люди пространств) — пока нет: пути `/api/messengers…` только у владельца.

### Сон по простою
Мост запускается по первому запросу (панель, модель, «Сегодня») и выходит сам через `IDLE` = 600 с (10 минут) без
запросов; вместе с ним выходят signal-cli и Node. Опрос «жив?» (`ping`) работой не считается. Для проверки —
`GAS_MSG_IDLE=15`.

## Установка программ (человек ставит сам; пульт показывает команду на экране «нужна программа»)

Пути ниже — для владельца; панель показывает точную команду со своей папкой данных.

- **Telegram:** `python3 -m venv ~/.local/share/gas-pult/messengers/telegram/venv &&
  ~/.local/share/gas-pult/messengers/telegram/venv/bin/pip install telethon==1.45.0`.
  Уже есть Python с Telethon — укажите его: `GAS_MSG_TELETHON_PY=/путь/к/python` в окружении панели.
- **Signal:** `mkdir -p ~/.local/share/gas-pult/messengers/signal/bin && curl -fsSL
  https://github.com/AsamK/signal-cli/releases/download/v0.14.10/signal-cli-0.14.10-Linux-native.tar.gz | tar xz -C
  ~/.local/share/gas-pult/messengers/signal/bin` (native-сборка: Java не нужна, ~390 МБ на диске). Обновлять раз в
  ~3 месяца: устаревший клиент Signal перестаёт работать. Свой signal-cli — `GAS_MSG_SIGNAL_CLI`.
- **WhatsApp:** Node 20+ (`GAS_MSG_NODE` — свой путь), затем
  `mkdir -p ~/.local/share/gas-pult/messengers/whatsapp/node && cd ~/.local/share/gas-pult/messengers/whatsapp/node &&
  echo '{"private":true,"type":"module"}' > package.json && npm install --no-audit --no-fund --omit=dev
  --ignore-scripts @whiskeysockets/baileys@7.0.0-rc14` (~50 МБ, 70 пакетов). В репозиторий ничего не ставится.
  Почему Baileys, а не whatsmeow: на сервере есть Node, нет Go; Baileys ставится одной командой без сборки.

## Замер ресурсов (22.11, ВМ ubuntu, `ps -o rss,pcpu`)

| Процесс | RSS | CPU |
|---|---|---|
| мост `host.py` (Python, без Telethon) | ~27 МБ | ~0,5 % в покое |
| Telegram: мост с Telethon, вход есть, 20 чатов + непрочитанные за сутки | ~60 МБ | только во время запроса (~1 с) |
| WhatsApp: `node wa_bridge.mjs` (Baileys), ждёт скан QR | ~119 МБ | 25 % при старте, ~1 % в покое |
| Signal: `signal-cli link` (native), ждёт скан QR | ~267 МБ | 13 % при старте, ~1 % в покое |

Signal тяжелее всех, но живёт только пока идёт привязка; приём и отправка — короткие процессы signal-cli. Все мосты
выключаются через 10 минут без запросов. Замер Signal и WhatsApp после привязки (приём сообщений) — не делался:
нужен скан QR владельцем.

## Проверка

- `tests/test_messengers.py` — на подделках, без сети: выбор обязателен, отправка только через черновик, секреты
  0600 и не в ответах, сон по простою, QR WhatsApp помещается (QR панели — до версии 15, 412 байт).
- Демо: `/?demo&view=integrations&msg=whatsapp` (экран выбора), `msg=whatsapp-qr` (QR-образец «ДЕМО»),
  `msg=telegram`, `msg=telegram-code`, `msg=telegram-chats`; тёмная тема — `&theme=dark`.
