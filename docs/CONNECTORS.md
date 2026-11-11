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
2. Человек подтверждает: кнопка в пульте (Telegram/MAX) или `python3 <svc>_mcp.py confirm <id>` в терминале —
   пишется `<id>.ok` с хешем ровно этих параметров.
3. `<svc>_apply(id)` → `_core.take_confirmed(svc, id)`: выполняется, только если `GAS_<SVC>_WRITE=1` (по умолчанию
   0) **и** есть подтверждение с совпадающим хешем. Одноразово: черновик становится `.done`.
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
