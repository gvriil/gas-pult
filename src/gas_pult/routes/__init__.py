"""Маршруты API панели — таблицами по областям (MONOLITH-PLAN §3.2, шаг 7).

Область — модуль ``routes/<область>.py`` со словарями «путь → функция». Функция — бывшая ветка ``if path == …`` из
``webapp.H.get``/``H.post``, тело как есть: ``self`` — обработчик запроса (``webapp.H``: ``self.panel``, ``who()``,
``space()``, ``body()``…). Подпись — по тому, что ветке было доступно в цепочке:

- ``GET``      — ``fn(self, q)``: параметры запроса;
- ``GET_W``    — ``fn(self, q, w)``: и окно сессии ``w = self.win(q["w"])`` (ветки после общего ``self.win`` в ``get``;
  окна нет — 404 «окна уже нет», как раньше);
- ``POST_RAW`` — ``fn(self)``: тело читает сама (запись голоса, файл) — до разбора JSON;
- ``POST``     — ``fn(self, b)``: тело — JSON (``json.loads(self.body() or b"{}")``, как в цепочке);
- ``POST_W``   — ``fn(self, b, w)``: и окно сессии ``w = self.win(b.get("w"))`` (ветки после общего ``self.win`` в
  ``post``; окна нет — 404 «окна уже нет»); ищется после ``POST_P`` — там, где ``post`` разобрал JSON;
- ``GET_P``, ``POST_P`` — развилка: одна функция на несколько путей, ``fn(self, path, q)`` / ``fn(self, path, b)``;
  ключ — кортеж путей (ветка ``if path in ТАБЛИЦА`` цепочки: ответ собирает модуль области по ``path``, например
  ``billing.api``). Ищутся после ``GET``/``GET_W`` и ``POST`` — как ветки, что шли ниже.

``H.get``/``H.post`` сначала ищут путь в ``TABLES``, потом — старая цепочка. Права здесь не проверяются: ``get`` и
``post`` вызываются только после ``H.permit`` (вход, условия, пространство ``SPACE_OK``, роль, потолок, код
подтверждения), ``H.focus_call`` (фокус- и демо-ссылка: ``FOCUS_*``/``DEMO_*`` и окно ссылки) или ``H.v1_call``
(токен: белый список ``V1_*``, затем ``permit``) — таблицы прав в ``access.py``, одна точка проверки на запрос.

Новая область: модуль с теми же именами словарей и строка в ``AREAS``. Путь объявлен в одном месте — в таблице или
в цепочке (``tests/test_routes.py``); опись API (``api_spec``) читает и таблицы. Модули областей не импортируют ни
``bot``, ни ``webapp`` (``tests/test_module_boundaries.py``).
"""

SENT = object()  # обработчик сам отправил ответ (``self.reply``): ``H.dispatch`` ничего не дописывает; ``webapp.SENT``

from gas_pult.routes import (  # noqa: E402 — SENT выше: его берут модули областей (routes/tasks.py)
    api_tokens,
    billing,
    bridge,
    focus,
    forms,
    integrations,
    meetings,
    messengers,
    model_keys,
    notify,
    projects,
    share,
    spaces,
    tasks,
    voice,
)

AREAS = (voice, messengers, billing, meetings, tasks, share, notify, forms, api_tokens, model_keys, integrations,
         projects, spaces, bridge, focus)
KINDS = ("GET", "GET_W", "GET_P", "POST_RAW", "POST", "POST_P", "POST_W")


def _merge(kind: str) -> dict:
    out: dict = {}
    for area in AREAS:
        for key, fn in getattr(area, kind, {}).items():
            for path in key if isinstance(key, tuple) else (key,):   # GET_P/POST_P: кортеж путей → одна функция
                if path in out:
                    raise ValueError(f"{kind} {path}: путь объявлен в двух областях")
                out[path] = fn
    return out


TABLES = {k: _merge(k) for k in KINDS}
GET, GET_W, GET_P, POST_RAW, POST, POST_P, POST_W = (TABLES[k] for k in KINDS)
