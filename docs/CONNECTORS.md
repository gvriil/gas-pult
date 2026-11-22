# Коннекторы к сервисам бизнеса РФ — шаблон и контракт

Зачем: пульт должен быстро подключаться к тому, чем уже пользуется клиент (МойСклад, Битрикс24, Wildberries, Ozon,
1С…). Каталог, приоритет и ночной конвейер — `portfolio-hq/products/integrations-market.md`; очередь —
`portfolio-hq/automation/connector-night/QUEUE.md`. Здесь — как устроен один коннектор, чтобы любой агент (и ночной
конвейер) делал их одинаково.

## Где что лежит

| Что | Путь |
|---|---|
| Ядро (общий код) | `src/gas_pult/connectors/_core.py` — `read_secret`, `hide`, `http`, `Throttle`, `propose`/`take_confirmed`/`confirm`, `serve`/`main` |
| Коннектор | `src/gas_pult/connectors/<svc>_mcp.py` — один файл, только stdlib |
| Записанные ответы | `tests/fixtures/<svc>/*.json` — обезличенные |
| Тесты | `tests/test_<svc>_mcp.py` — без сети |
| Описание для людей | `docs/connectors/<svc>.md` — что умеет, как получить ключ, лимиты, чего не умеет |
| Пример сценария | `docs/connectors/<svc>.md`, раздел «Сценарий» — связка с модулем из `templates/modules/` |
| Подключение в harness | `portfolio-hq/integrations/servers.json` (`auth.kind: "file"`) → `bootstrap/mcp-install.sh` |

`<svc>` — короткое латинское имя: `moysklad`, `bitrix24`, `wildberries`, `ozon`, `max`, `metrika`, `amocrm`, `onec`,
`yclients`, `tbank`.

## Контракт инструментов

- Протокол — MCP по stdio, JSON-RPC 2.0 построчно (как `base_mcp.py`): `initialize`, `tools/list`, `tools/call`,
  `ping`. Запуск: `python3 src/gas_pult/connectors/<svc>_mcp.py`.
- Имена: `<svc>_list_*` (список с `limit`, по умолчанию 20, максимум 100; фильтры — явные параметры),
  `<svc>_get_*` (одна запись по id), `<svc>_propose_*` (черновик записи), `<svc>_apply` (выполнить подтверждённый).
- **Чтение по умолчанию.** Набор первой версии — то, что нужно модулям пульта: остатки, заказы, клиенты/контрагенты,
  долги, отзывы, цены, выписки.
- Ответ — короткий JSON с нужными полями (не сырой ответ API целиком): id, название, суммы в рублях, даты ISO,
  ссылка на запись в веб-интерфейсе сервиса, если есть. Больше ~50 строк — урезать и сказать, как получить остальное.
- Описание инструмента (`description`) — по-русски, что делает и чего **не** делает.
- Ошибки — `ToolError` с понятным текстом («ключ не подходит», «лимит запросов, подождите N с»), без стека и без ключа.

## Запись: propose → человек → apply

1. `<svc>_propose_<действие>(...)` **ничего не пишет в сервис**: проверяет параметры, при необходимости читает
   текущее состояние и вызывает `_core.propose(svc, action, params, summary)` — черновик ложится в
   `~/.local/state/gas-pult/confirm/<svc>/<id>.json` (0600), модель получает id и человекочитаемое `summary`.
2. Человек подтверждает кнопкой «Да» в панели («Ждут вашего «Да»»): «Да» с отпечатком ровно этих параметров
   хранится только в памяти службы панели (`approvals.py`). Команды `confirm` и отметки `.ok` на диске — не действуют
   (штаб 22.11: агент от того же пользователя Linux мог поставить их сам).
3. `<svc>_apply(id)` → `_core.take_confirmed(svc, id)`: выполняется, только если `GAS_<SVC>_WRITE=1` (по умолчанию
   0) **и** панель подтверждает «Да» с совпадающим хешем (`POST /api/drafts/check`). Одноразово: черновик становится `.done`.
- **Не реализуем вовсе:** платежи и переводы денег, удаление, массовые изменения, смену прав/пользователей.
- Защита рассчитана на ошибку модели, а не на злой умысел агента с доступом к shell — от этого песочница сессии.

## Секреты

- Файл `~/.config/gastech-mcp/<svc>.token` (права 0600), путь меняется `GAS_<SVC>_KEY_FILE`. Простой токен — одной
  строкой; несколько значений (Ozon: Client-Id + Api-Key; amoCRM: OAuth) — JSON-объект в том же файле.
  Оригинал — в KeePassXC `gastech.kdbx`, группа `mcp/<svc>`.
- В `servers.json` — только путь (`auth.kind: "file"`), ключ в конфиг harness не копируется.
- Ключ читается на каждый вызов (`read_secret`), не держится в глобальных переменных и не пишется никуда.
- Сервер отдаёт `"keys": lambda: _core.secret_values(_core.read_secret(SVC))` — ядро вычищает их из любого ответа;
  ошибки HTTP — через `hide`.
- Регистрации в сервисах, OAuth-приложения, запрос партнёрских токенов — только владелец (внешнее действие).

## Адрес, лимиты, песочница

- `BASE = _core.base_url(SVC, "<боевой адрес>")` — `GAS_<SVC>_BASE` подменяет на песочницу или локальный сервер в
  тестах. Песочница по умолчанию, если у вендора она отдельным адресом (WB: `*-api-sandbox.wildberries.ru`).
- Лимиты — `Throttle(n, per)` по документации вендора (МойСклад 45 за 3 с, Т-Банк 20 RPS); 429 — понятная ошибка
  с `Retry-After`.

## Тесты (обязательный минимум)

Без сети; сервис подменяется локальным `HTTPServer` (как в `tests/test_base_mcp.py`), отвечающим файлами из
`tests/fixtures/<svc>/`. Проверить:
1. `initialize` → `tools/list` → `tools/call` для каждого `list/get` — настоящим процессом `python3 <svc>_mcp.py`.
2. Запрос уходит с правильной авторизацией (заголовок/параметр) и на правильный путь.
3. **Ключ не утекает:** нет в stdout и stderr ни при успехе, ни при 401/500 (фейковый сервис эхом возвращает ключ).
4. **Без подтверждения записи нет:** `propose` не делает ни одного запроса на запись (фейковый сервис считает
   POST/PUT/PATCH/DELETE); `apply` без `confirm` и при `GAS_<SVC>_WRITE=0` — ошибка; после подтверждения — ровно один
   запрос.
5. Нет файла ключа — понятная ошибка, процесс не падает.
6. `ruff check` и `pytest -q` зелёные.

Ответы в fixtures: записаны с песочницы (обезличить: ИНН, телефоны, имена, суммы — на выдуманные) или, пока ключа нет,
собраны по примерам из документации — тогда в шапке теста и в PR пометка **«не проверено на песочнице»**.

## Каркас коннектора

```python
"""<Сервис> для пульта: <что читает>. Ключ — ~/.config/gastech-mcp/<svc>.token. Контракт — docs/CONNECTORS.md."""
from __future__ import annotations
import sys

if __package__:
    from . import _core
else:                                                  # запуск файлом: python3 <svc>_mcp.py
    import _core

SVC = "<svc>"
THROTTLE = _core.Throttle(45, 3.0)


def _api(method: str, path: str, **kw):
    key = _core.read_secret(SVC)
    return _core.http(method, _core.base_url(SVC, "https://api.example.ru/v1") + path,
                      headers={"Authorization": f"Bearer {key}"}, keys=_core.secret_values(key),
                      throttle=THROTTLE, service="<Сервис>", **kw)


def list_items(a: dict):
    limit = max(1, min(int(a.get("limit", 20)), 100))
    rows = _api("GET", "/items", query={"limit": limit}).get("rows", [])
    return [{"id": r["id"], "name": r.get("name", ""), "qty": r.get("stock", 0)} for r in rows]


def propose_price(a: dict):
    return _core.propose(SVC, "set_price", {"id": str(a["id"]), "price": float(a["price"])},
                         f"цена товара {a['id']} → {a['price']} ₽")


def apply(a: dict):
    rec = _core.take_confirmed(SVC, a["id"])
    p = rec["params"]
    _api("PUT", f"/items/{p['id']}", body={"price": p["price"]})
    return {"done": rec["summary"]}


SERVER = {
    "name": f"gas-pult-{SVC}", "instructions": "<Сервис>: чтение; запись — только черновик и подтверждение человека.",
    "keys": lambda: _core.secret_values(_core.read_secret(SVC)),
    "tools": [
        {"name": f"{SVC}_list_items", "description": "Товары и остатки. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 20}}},
         "fn": list_items},
        {"name": f"{SVC}_propose_price", "description": "Черновик смены цены. Сам ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "price": {"type": "number"}},
                         "required": ["id", "price"]}, "fn": propose_price},
        {"name": f"{SVC}_apply", "description": "Выполнить черновик, подтверждённый человеком.",
         "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
         "fn": apply}],
}

if __name__ == "__main__":
    sys.exit(_core.main(SERVER, SVC))
```

## Запись в `servers.json` (portfolio-hq)

```json
"moysklad": {
  "type": "stdio", "command": "python3",
  "args": ["{gas_pult}/src/gas_pult/connectors/moysklad_mcp.py"],
  "env": {"GAS_MOYSKLAD_KEY_FILE": "{secrets}/moysklad.token"},
  "auth": {"kind": "file", "file": "moysklad.token", "keepass": "mcp/moysklad",
           "get_key": "МойСклад → Настройки → Пользователи → Токены (демо-аккаунт)"},
  "purpose": "МойСклад: остатки, заказы, долги контрагентов — чтение; запись — через подтверждение (gas-pult PR #N)"
}
```
Нет файла ключа — `mcp-install.sh` сервер пропускает и пишет, где взять ключ.

## Чек-лист «коннектор готов» (статус «подключено» на сайте — только после всех пунктов)

1. Песочница/демо-аккаунт указаны; доступ проверен одним вызовом — вывод (без ключа) в PR.
2. Тесты на записанных ответах в `tests/fixtures/<svc>/`, без сети, зелёные в CI.
3. Тест «ключ не утекает» и тест «без подтверждения записи нет» — есть и зелёные.
4. `docs/connectors/<svc>.md`: что умеет, как получить ключ (шаги в ЛК), лимиты, чего **не** умеет.
5. Пример сценария с модулем из `templates/modules/` (напр. `horeca-reorder` + МойСклад) и замер «минут до/после».
6. Запись в `portfolio-hq/integrations/servers.json`; PR с меткой `[продукт]`, сливает владелец после ревью.

Каркас без ключа (пункт 1 не выполнен) — PR с пометкой «не проверено на песочнице», статус в очереди «PR открыт
(каркас)»; после появления ключа ночной конвейер перезаписывает fixtures настоящими ответами в той же ветке.

## Автовход: сторож входа коннекторов

Решение владельца 22.11: коннектор (MCP-сервер, плагин) потерял вход — система входит заново сама; от владельца —
самое большее одно окно с уже заполненными полями. Код — `src/gas_pult/connwatch.py`, тесты — `tests/test_connwatch.py`.

### Фазы

| Фаза | Что | Статус |
|---|---|---|
| 1 | Обнаружение, квитанции, задачи владельцу, заготовка базы паролей | сделано |
| 2 | Нажать «Разрешить» в Chrome агента (CDP) — только для уже разрешённых прав | сделано (`relogin.py`) |
| 3 | Подставить логин и пароль из базы `connectors.kdbx` | код есть; список сервисов пуст — ни один не проверен |

Точка расширения — `connwatch.relogin(conn, approved) -> Result`; работу делает `relogin.run`. **По умолчанию
выключен**: `claude mcp login` перед входом стирает старые токены коннектора, поэтому автовход включается
(`relogin = true` в `~/.config/gas-pult/connwatch.toml`) только после живой проверки на сервере. Выключен — сторож
работает как в фазе 1: квитанция и задача «Ждут вас».

### Что проверяется

| Harness | Как | Состояния |
|---|---|---|
| Claude Code и FCC | `claude mcp list` (FCC — тот же `claude` и та же папка) | `✔ Connected` → ok · `! Needs authentication` → needs_auth · `✘ Failed …` → failed · `- Not configured` → unknown |
| Pi | `pi mcp list --json` | connected → ok · needs-auth → needs_auth · failed → failed · disabled, connecting → unknown |
| OpenCode | `opencode mcp list` (машиночитаемого вывода нет; строки сверены с программой) | connected → ok · needs authentication, needs client registration → needs_auth · failed → failed |
| Hermes | не проверяется | `hermes mcp list` показывает только «✓ enabled» (настройка), а не связь: отказавший сервер там тоже «✓ enabled» |

Unknown прошлое состояние не меняет. Программа не ответила — строка «не проверено» с причиной, остальные harness
проверяются дальше.

**Исключения** (не проверяются): `plugin:design:*`, `plugin:gitlab:*`, `browser-local` (мост к компьютеру — выключенный компьютер не потеря входа) и `plugin:telegram:*` (канал бота есть только в сессиях, запущенных с ним). Свои — в `~/.config/gas-pult/connwatch.toml`:

```toml
exclude = ["browser-local", "plugin:telegram:*", "pi/linear"]   # шаблоны fnmatch; «harness/имя» — для одного harness
```

### Что происходит при сбое

1. Коннектор перешёл в needs_auth или failed → событие `connector_down` в `<данные>/chat-events.jsonl` (только
   harness, имя и состояние — без текстов ошибок).
2. `relogin` — автовход (фаза 2, ниже). Вошёл — задачи нет. Не вышел — дальше по шагам. Событие
   `connector_relogin`: harness, имя, итог (`clicked` · `needs_owner` · `failed`), причина — без query в адресах.
3. Задача «Войти заново: <имя> (<harness>)» со статусом «ждёт вас» и строкой «что нажать». Одна на коннектор:
   повторная проверка её не дублирует.
4. Бот (цикл `monitor`, раз в 5 минут) читает новые события и шлёт владельцу одну квитанцию на переход
   (`broadcast`, как сводка сбоев — docs/ALERTS.md).
5. Коннектор снова ok → событие `connector_up`, задача закрыта, квитанция «снова на связи — вошёл заново».

Состояние — `<данные>/connwatch_state.json`. `gas-pult connectors watch --dry-run` показывает статус и что было бы
сделано, но ничего не пишет и автовход не запускает.

### Фаза 2: «Разрешить» в Chrome агента

Код — `src/gas_pult/relogin.py`, тесты — `tests/test_relogin.py`. Только для состояния needs_auth (failed — это не
вход).

1. Chrome агента (DevTools `127.0.0.1:9222`, «Браузер» на столе) не отвечает → `failed`, задача владельцу. Программа
   входа не запускается.
2. Программа входа harness запускается отдельно от сторожа, в своём терминале (pty), до часа (`relogin.HOLD`): она
   ждёт возврата браузера на свой адрес `localhost`. Вывод — `<данные>/relogin/<harness>_<имя>.out` (0600). Свой
   браузер она не открывает (`xdg-open` подменён пустым).
3. Адрес входа открывается новой вкладкой в Chrome агента. Страница:
   - **согласие** (кнопка Allow, Authorize, Approve, Accept, Grant, «Разрешить», «Принять»…) — отпечаток: домен +
     `scope` из адреса входа и страницы + хэш видимого списка прав. `client_id` и `state` в отпечаток не входят.
     Нет разрешённого отпечатка (первый раз) или он другой (новые права) → не нажимаем, `needs_owner`. Совпал и
     кнопка «Разрешить» одна → настоящий щелчок мышью, ждём конца программы входа, проверяем `mcp list`: ok →
     `clicked`, иначе `failed`;
   - **пароль** — только домен из `relogin.PASSWORD_SERVICES` (домен → адрес условий сервиса; пока пусто) и запись
     `<harness>/<имя>` в `connectors.kdbx`. Логин и пароль вводятся через DevTools `Input.insertText`, значение
     никуда не пишется. Google, Gmail, YouTube, Telegram (`relogin.NEVER_PASSWORD`) — никогда;
   - **2FA, капча, неизвестная страница** → `needs_owner`.
4. `needs_owner`: вкладка остаётся открытой (с тем, что уже заполнено), задача «Ждут вас» начинается словами «В Chrome
   агента уже открыта страница входа». Владелец нажимает «Разрешить» сам → программа входа заканчивает вход →
   следующая проверка видит ok → отпечаток из `pending` переходит в `approved`.

Отпечатки — в `<данные>/connwatch_state.json`: `approved` (разрешённые владельцем) и `pending` (показаны владельцу,
ждут ручного успеха), ключ — `harness:имя`; хранятся домен, список `scope` и хэши — без текста страницы. Сбросить:
`gas-pult connectors forget claude:linear` (один) или `gas-pult connectors forget` (все). После сброса следующий вход
снова решает владелец.

#### Как получить адрес входа без сессии (проверено 22.11, программы не запускались для входа)

| Harness | Как получить адрес | Как заканчивается вход | Где токены (только путь) |
|---|---|---|---|
| Claude Code 2.1.330 и FCC | `claude mcp login <имя> --no-browser` печатает адрес. Без терминала (stdin не TTY) программа сразу сдаётся — поэтому pty. Перед входом стирает старые токены сервера. | Возврат браузера на `http://localhost:<порт>/callback` (у плагина design:slack порт 3118 — `claude mcp get`) или вставка адреса возврата в ту же программу | `~/.claude/.credentials.json` (0600) |
| Claude Code, коннекторы `claude.ai …` | та же команда печатает ссылку claude.ai и сразу заканчивается | на claude.ai; в Claude Code — со следующего запуска | на claude.ai |
| Claude Code, плагины `plugin:…` | тип http с OAuth (`claude mcp get plugin:design:slack`: `Type: http`, `OAuth: client_id configured, callback_port 3118`) — значит, та же ветка `mcp login`; инструменты `authenticate` / `complete_authentication` есть только внутри сессии | как у Claude Code | как у Claude Code |
| Pi | `pi mcp login <имя> [--timeout с]` печатает «Sign in to MCP server … in your browser:» и адрес, открывает `xdg-open` | возврат на `http://127.0.0.1/callback` (свой порт); без терминала ждёт только его | `~/.pi/agent/mcp-auth.json` |
| OpenCode 1.19.5 | `opencode mcp auth <имя>` печатает «Authorize in your browser:» и адрес | возврат на `http://127.0.0.1:19876/mcp/oauth/callback` | `~/.local/share/opencode/mcp-auth.json` |
| Hermes | нет: `hermes mcp list` не показывает связь | — | — |

### Таймер

`gas-pult connectors watch --install` ставит `~/.config/systemd/user/gas-pult-connwatch.{service,timer}`: служба
`Type=oneshot` (постоянного процесса нет), таймер — через 10 минут после загрузки и затем раз в 30 минут.
Убрать — `--uninstall`. Проверить — `systemctl --user list-timers gas-pult-connwatch.timer`. Посмотреть шаги, ничего
не ставя, — `--install --dry-run`. В службе `KillMode=process`: программа входа живёт после конца проверки и ждёт
владельца до часа.

### База паролей коннекторов

Отдельная от основной базы владельца база: `~/.local/share/gas-pult/connectors.kdbx`, ключ-файл
`~/.config/gas-pult/connectors.key` (0600), мастер-пароля нет — её читает служба без человека. Агентам оба файла
закрыты: в Claude Code — `secrets_guard` (Read, Grep, Bash), в Pi, OpenCode и Hermes — `injection_guard` через адаптер
ловушек.

Как владельцу положить логин (в терминале, не кнопкой «Выполнить»):

1. Создайте базу (уже есть — команда ничего не делает): `gas-pult connectors vault init`.
2. Добавьте запись; пароль программа спросит сама, в историю команд он не попадёт:
   `keepassxc-cli add --no-password -k ~/.config/gas-pult/connectors.key -u <логин> --url <адрес входа> -p ~/.local/share/gas-pult/connectors.kdbx <harness>/<имя коннектора>`
3. Проверьте, что запись есть (без пароля): `keepassxc-cli ls --no-password -k ~/.config/gas-pult/connectors.key ~/.local/share/gas-pult/connectors.kdbx`.

Пульт читает пароль функцией `connwatch.vault_get("<harness>/<имя>")`. Значение не пишется в журнал, события и задачи.

### Чего сторож не делает никогда

- Не обходит двухфакторную проверку и капчу.
- Не вводит пароль Google и Telegram: вход в них — только живая сессия человека.
- Не нажимает «Разрешить» для нового коннектора или для других прав: это решает владелец.
- Не пишет пароль и адреса с кодами в журнал, события, задачи, чат и git.
