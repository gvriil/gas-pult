"""Опись API панели: каждый путь ``/api/…`` — метод, кто может, что делает, основные поля входа и выхода.

Пути и поля собираются из кода ``webapp.py`` разбором ``ast`` (без запуска): ветки ``if path == …``,
``if path in (…)``, ``path.startswith(…)`` и регулярки маршрутов. Права — из таблиц ``access.py`` по той же формуле,
что ``Handler.permit``. Описания — вручную, коротко, в ``DESCR`` (поля, которых разбор не видит, — там же).

Обновить документы после правки маршрутов или описаний::

    python -m gas_pult.api_spec          # пишет docs/API.md и docs/openapi.json
    python -m gas_pult.api_spec --check  # только сверка (как в CI), код 1 при расхождении

Тест ``tests/test_api_spec.py``: каждый путь из кода есть в ``DESCR`` и наоборот, документы совпадают с генератором.
Только стандартная библиотека; OpenAPI 3.1 — собран словарём.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

from gas_pult import access, personas

SRC = Path(__file__).with_name("webapp.py")
DOCS = Path(__file__).resolve().parents[2] / "docs"

GET_FN = {"do_GET", "get"}                   # ветки GET; do_GET — до проверки входа (свои правила)
POST_FN = {"do_POST", "post", "focus_bridge"}  # ветки POST; do_POST — до проверки входа
OPEN_FN = {"do_GET", "do_POST"}              # путь здесь — обработка до ``permit`` (вход, коды, токены)
# Фокус-ссылки: функция → (пути GET, пути POST) — метод по таблицам access.py. focus_do — ссылка на сессию, проект и
# демо; meeting_public — ссылка на протокол встречи (focus.MEETING, ветка в focus_call)
FOCUS_TABLES = {"focus_do": (access.FOCUS_GET | access.DEMO_GET, access.FOCUS_POST | access.DEMO_POST),
                "meeting_public": (access.MEETING_GET, access.MEETING_POST)}
FOCUS_FN = set(FOCUS_TABLES)
FOCUS_ONLY_FN = FOCUS_FN | {"focus_bridge"}   # путь только здесь — его нет вне фокус-ссылки
PATH_VARS = {"path", "url.path"}
# Пути по префиксу (``path.startswith``) — разбор внутри обработчика: префикс → (путь, метод)
PREFIX_ROUTES = {
    "/api/q/": (("/api/q/{code}", "GET"), ("/api/q/{code}/save", "POST"), ("/api/q/{code}/submit", "POST")),
    "/api/offer/": (("/api/offer/{code}", "GET"), ("/api/offer/{code}/{act}", "POST")),
}
# Регулярки маршрутов (``X.match(url.path)``) — путь с параметрами
REGEX_ROUTES = {"OIDC_PATH": (("/api/login/oidc/{provider}/{step}", "GET"),)}


# ---------------------------------------------------------------------------------------------------- разбор кода
def _env(tree: ast.Module) -> dict[str, list[str]]:
    """Имена путей: таблицы ``access.py`` (как есть, с ``|=``) и простые константы ``webapp.py``."""
    env: dict[str, list[str]] = {}
    for k, v in vars(access).items():
        if isinstance(v, str):
            env[k] = [v]
        elif isinstance(v, (tuple, set, frozenset)) and all(isinstance(x, str) for x in v):
            env[k] = sorted(v)
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            got = _lit(node.value, env)
            if got is not None:
                env[node.targets[0].id] = got
    return env


def _lit(n: ast.AST, env: dict[str, list[str]]) -> list[str] | None:
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return [n.value]
    if isinstance(n, ast.Name):
        return env.get(n.id)
    if isinstance(n, (ast.Tuple, ast.Set, ast.List)):
        out: list[str] = []
        for e in n.elts:
            got = _lit(e.value if isinstance(e, ast.Starred) else e, env)
            if got is None:
                return None
            out += got
        return out
    return None


def _regexes(tree: ast.Module) -> dict[str, str]:
    """Регулярки маршрутов: ``ИМЯ = re.compile("…")`` в ``access.py`` и ``webapp.py`` → шаблон."""
    out = {k: v.pattern for k, v in vars(access).items() if isinstance(v, re.Pattern)}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and \
                isinstance(node.value, ast.Call) and ast.unparse(node.value.func) == "re.compile" and \
                isinstance(node.value.args[0], ast.Constant):
            out[node.targets[0].id] = node.value.args[0].value
    return out


class _Walk(ast.NodeVisitor):
    def __init__(self, env: dict[str, list[str]]):
        self.env = env
        self.fn: list[str] = []
        self.found: list[tuple[str, str, str, ast.AST | None]] = []   # (функция, вид, путь, ветка If)
        self.branch: list[ast.If] = []
        self.with_w: set[int] = set()            # ветки после ``w = self.win(…)``: окно сессии — поле ``w``

    def visit_FunctionDef(self, n):
        seen = False
        for st in n.body:                         # get/post: общее «w = self.win(q/b.get("w"))» перед ветками
            if isinstance(st, ast.Assign) and ast.unparse(st.targets[0]) == "w" and \
                    ast.unparse(st.value).startswith("self.win("):
                seen = True
            elif seen and isinstance(st, ast.If):
                self.with_w.update(id(x) for x in ast.walk(st) if isinstance(x, ast.If))
        self.fn.append(n.name)
        self.generic_visit(n)
        self.fn.pop()

    def visit_If(self, n: ast.If):
        self.branch.append(n)
        self.visit(n.test)
        self.branch.pop()
        for x in n.body + n.orelse:
            self.visit(x)

    def _add(self, kind: str, path: str):
        if self.fn:
            self.found.append((self.fn[-1], kind, path, self.branch[-1] if self.branch else None))

    def visit_Compare(self, n: ast.Compare):
        if ast.unparse(n.left) in PATH_VARS:
            for op, c in zip(n.ops, n.comparators, strict=True):
                if isinstance(op, (ast.Eq, ast.In)):
                    for p in _lit(c, self.env) or ():
                        if p.startswith("/api/"):
                            self._add("eq", p)
        self.generic_visit(n)

    def visit_Call(self, n: ast.Call):
        f = n.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.attr in ("match", "fullmatch") and \
                n.args and ast.unparse(n.args[0]) in PATH_VARS:
            self._add("re", f.value.id)
        if isinstance(f, ast.Attribute) and f.attr == "startswith" and ast.unparse(f.value) in PATH_VARS and n.args:
            for p in _lit(n.args[0], self.env) or ():
                if p.startswith("/api/") and p != "/api/":
                    self._add("prefix", p)
        self.generic_visit(n)


def _fields(branch: ast.AST | None, with_w: set[int]) -> tuple[list[str], list[str], list[str]]:
    """Ветка ``if`` → (поля входа ``q``/``b``, ключи словаря ответа, вызванные методы ``panel.*``)."""
    if branch is None:
        return [], [], []
    ins: list[str] = ["w"] if id(branch) in with_w else []
    outs: list[str] = []
    calls: list[str] = []
    for st in branch.body:
        for n in ast.walk(st):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and \
                    isinstance(n.func.value, ast.Name) and n.func.value.id in ("q", "b") and n.args and \
                    isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                ins.append(n.args[0].value)
            elif isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id in ("q", "b") and \
                    isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str):
                ins.append(n.slice.value)
            elif isinstance(n, ast.Return) and isinstance(n.value, ast.Dict):
                outs += [k.value for k in n.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and \
                    isinstance(n.func.value, ast.Name) and n.func.value.id == "panel":
                calls.append(f"Panel.{n.func.attr}")
    uniq = lambda xs: list(dict.fromkeys(xs))      # noqa: E731 — порядок появления, без повторов
    return uniq(ins), uniq(outs), uniq(calls)


def _free(tree: ast.Module, env: dict[str, list[str]]) -> set[str]:
    """Локальный кортеж ``free`` из ``permit``: POST без роли «участник» (и наблюдателю)."""
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == "permit":
            for n in ast.walk(fn):
                if isinstance(n, ast.Assign) and [ast.unparse(t) for t in n.targets] == ["free"]:
                    return set(_lit(n.value, env) or ())
    raise LookupError("permit: нет free — разбор устарел, поправьте api_spec._free")


def scan(src: str | None = None) -> dict[str, dict]:
    """Маршруты из кода: путь → {methods, open, focus_only, in, out, calls}."""
    src = SRC.read_text(encoding="utf-8") if src is None else src
    tree = ast.parse(src)
    env = _env(tree)
    regexes = _regexes(tree)
    w = _Walk(env)
    w.visit(tree)
    out: dict[str, dict] = {}

    def put(path: str, method: str, fn: str, branch: ast.AST | None):
        r = out.setdefault(path, {"methods": set(), "open": set(), "src": set(), "in": [], "out": [], "calls": []})
        r["methods"].add(method)
        r["src"].add(fn)
        if fn in OPEN_FN:
            r["open"].add(method)
        ins, outs, calls = _fields(branch, w.with_w)
        for k, v in (("in", ins), ("out", outs), ("calls", calls)):
            r[k] = list(dict.fromkeys(r[k] + v))

    for fn, kind, p, br in w.found:
        if kind == "re":
            if p not in REGEX_ROUTES and "/api/" in regexes.get(p, ""):   # новый путь-регулярка API — в опись
                raise LookupError(f"маршрут-регулярка {p} ({regexes[p]}) — добавьте в REGEX_ROUTES")
            for path, m in REGEX_ROUTES.get(p, ()):
                put(path, m, fn, None)
        elif kind == "prefix":
            if fn in FOCUS_FN:                            # /api/focus/bridge — сам путь, подпути — в focus_bridge
                for m in ("GET", "POST"):
                    if p in (access.FOCUS_GET if m == "GET" else access.FOCUS_POST):
                        put(p, m, fn, br)
            elif p.endswith("/"):
                if p not in PREFIX_ROUTES:
                    raise LookupError(f"маршрут-префикс {p} — добавьте в PREFIX_ROUTES")
                for path, m in PREFIX_ROUTES[p]:
                    put(path, m, fn, None)
        elif fn in GET_FN:
            put(p, "GET", fn, br)
        elif fn in POST_FN:
            put(p, "POST", fn, br)
        elif fn in FOCUS_FN:
            for m, ok in zip(("GET", "POST"), FOCUS_TABLES[fn], strict=True):
                if p in ok:
                    put(p, m, fn, br)
    for r in out.values():
        r["methods"] = sorted(r["methods"])
        r["open"] = sorted(r["open"])
        r["focus_only"] = r.pop("src") <= FOCUS_ONLY_FN      # обычной панели такого пути нет (404)
    return dict(sorted(out.items()))


# -------------------------------------------------------------------------------------------------------- права
ROLE_RU = {"owner": "владелец", "admin": "владелец и админ", "member": "участник и выше", "viewer": "любой вошедший",
           "open": "без входа", "focus": "только по фокус-ссылке"}


def who(path: str, method: str, r: dict, free: set[str]) -> dict:
    """Кто может: та же формула, что ``Handler.permit`` (роль) + особые таблицы (метки)."""
    a = access
    if method in r["open"] and path not in a.HELP_OPEN:   # до permit: вход, коды, токены устройства
        role = "open"
    elif r["focus_only"]:                                   # только cookie фокус-ссылки (focus_call)
        role = "focus"
    elif path in a.OWNER_ONLY:
        role = "admin" if path in a.ADMIN_OK else "owner"
    elif (method == "POST" and path not in free) or path in a.MEMBER_ONLY:
        role = "member"
    else:
        role = "viewer"
    tags = []
    if path in a.HELP_OPEN:
        tags.append("и до входа")
    if method == "POST" and path in a.CONFIRM:
        tags.append("CONFIRM")
    if path in a.TTY:
        tags.append("TTY")
    if path in a.TERMS_FREE:
        tags.append("TERMS_FREE")
    if path in a.SPACE_OK:
        tags.append("SPACE_OK")
    if method == "POST" and path in a.BUDGET_PATHS:
        tags.append("BUDGET")
    if path in a.SLINK_NO:
        tags.append("SLINK_NO")
    if path in (a.FOCUS_GET if method == "GET" else a.FOCUS_POST):
        tags.append("FOCUS")
    if path in (a.FOCUS_PROJ_GET if method == "GET" else a.FOCUS_PROJ_POST):
        tags.append("FOCUS_PROJ")
    if path in (a.DEMO_GET if method == "GET" else a.DEMO_POST):
        tags.append("DEMO")
    if path in (a.MEETING_GET if method == "GET" else a.MEETING_POST):
        tags.append("MEETING")
    if cap := personas.PATH_CAP.get(path):
        tags.append(f"cap:{cap}")
    return {"role": role, "tags": tags}


TAGS_RU = {
    "и до входа": "на экране входа — и без входа (свой лимит по IP)",
    "CONFIRM": "новая сессия браузера (моложе суток) — после кода подтверждения (403 code=confirm)",
    "TTY": "только в режиме разработчика (живой терминал)",
    "TERMS_FREE": "доступно до принятия условий использования",
    "SPACE_OK": "доступно тестировщику демо-пространства (только своё пространство)",
    "BUDGET": "тестировщику — пока не исчерпан дневной бюджет пространства",
    "SLINK_NO": "не по ссылке на пространство",
    "FOCUS": "по фокус-ссылке (только её сессия)",
    "FOCUS_PROJ": "по фокус-ссылке на проект (только её проект)",
    "DEMO": "по демо-ссылке (просмотр и выбор вариантов)",
    "MEETING": "по ссылке на протокол встречи (только её протокол)",
    "cap:": "потолок возможностей человека (personas.PATH_CAP)",
}


# ----------------------------------------------------------------------------------------------- описания вручную
# Путь → «что делает» или («что делает», «вход: поля», «выход: поля») — поля сверх тех, что видит разбор.
# Новый путь в webapp.py без строки здесь — тест упадёт; строка без пути — тоже.
DESCR: dict[str, str | tuple[str, str, str]] = {
    # --- сессии и чат
    "/api/sessions": "Список сессий (окна tmux) для главной: статус, расход, лимиты (владельцу), задачи",
    "/api/activity": "Строка статуса чата: что агент делает сейчас",
    "/api/ask": "Простой режим: вопрос Claude простыми словами и варианты-чипы",
    "/api/hint": "Подсказка ввода из строки окна (что предлагает Claude Code)",
    "/api/history": "Переписка сессии страницами (новые сверху, `before` — раньше)",
    "/api/screen": "Последние строки экрана окна; вход в сервис и вопрос, если на экране",
    "/api/last": "Последний ответ агента текстом (для «Скопировать» и озвучки)",
    "/api/cmds": "Команды из ответов агента, которые можно выполнить кнопкой",
    "/api/send": ("Отправить текст в сессию; повтор того же текста — `dup`", "text", ""),
    "/api/resend": "«Отправить» у строки «Не отправлено» — Enter после проверки",
    "/api/key": "Клавиша в окно (Enter, Esc, стрелки, Ctrl+C); по демо-ссылке — только выбор варианта",
    "/api/select": "Выбрать вариант в вопросе Claude (номер или текст)",
    "/api/command": "Выполнить команду из списка `/api/cmds` по номеру",
    "/api/active": "Сделать сессию активной в чате бота",
    "/api/new": "Новая сессия (окно) в папке; тестировщику — в его пространстве",
    "/api/folder": "«Новая папка» и сессия в ней (как папка в боте)",
    "/api/rename": "Переименовать окно сессии",
    "/api/title": "Название чата (вторая часть), не имя окна; пусто — авто",
    "/api/close": "«Завершить» сессию; модулю — расписание (оставить, приостановить, выключить)",
    "/api/restart": "Перезапустить сессию с профилем модели; `keep` — продолжить разговор",
    "/api/revive": "Оживить сессию, окно которой пропало (продолжить по журналу)",
    "/api/model": "Сменить модель сессии; `keep` — только запомнить для перезапуска",
    "/api/effort": "Уровень усилий модели (/effort) в сессии",
    "/api/route": "Подсказка модели по первому сообщению (router.py)",
    "/api/pin": "«Закрепить» / «Открепить» проект, сессию или чат",
    "/api/order": "Свой порядок закреплённых, проектов и чатов",
    "/api/upload": ("Файл в сессию (поток в файл); `w` — папка проекта, иначе inbox",
                    "тело — байты файла, X-File-Name; w (query)", "path"),
    "/api/media": "Картинка из ленты: inbox и Диск (по фокус-ссылке — только её папки)",
    "/api/steps": "«Шаги»: сообщение → инструменты → ответ (GAS-16)",
    "/api/starters": "Бейджики-сценарии первого разговора (GAS-37)",
    "/api/starter": "Нажали бейджик: текст для агента и замер (без текста)",
    "/api/scenarios": "«Примерить на себя»: роли, день с агентом, польза",
    "/api/stopped/clear": "«Убрать все остановленные» — окна закрыты, журналы остаются",
    "/api/notify-done": "«Сообщить по готовности»: одно сообщение в бот, когда ход закончится",
    "/api/notify/level": "Уровень уведомлений этой сессии (notifylevel.py)",
    # --- голос
    "/api/stt": ("Распознать голос; `?job=1` — фоново (GAS-34)", "тело — звук, Content-Type", ""),
    "/api/stt/job": "Фоновое распознавание: состояние и текст",
    "/api/stt/retry": "Повторить нераспознанную запись (она хранится на сервере)",
    "/api/stt/stream": ("Голос потоком: WebSocket к службе T-one; вход — первым сообщением", "WebSocket", ""),
    "/api/tts": ("Озвучить ответ: звук (audio/mpeg)", "", "audio/mpeg"),
    "/api/tts/warm": "Прогреть синтез речи, когда открыли сессию (#190)",
    "/api/tts/about": "«Что здесь умеет» — голосом (текст из карты помощника)",
    "/api/voice/cards": "Карточки голосов для выбора",
    "/api/voice/choose": "Выбрать голос озвучки",
    "/api/voice/preview": ("Образец голоса (audio/mpeg)", "", "audio/mpeg"),
    "/api/providers": "Голосовые поставщики: настройки и голоса ElevenLabs; POST — сохранить",
    # --- проекты и чаты
    "/api/projects": "«Проекты» для главной: проекты, порядок, сессии, лимиты — одним запросом",
    "/api/project": "Карточка проекта: папка, сессии, инструкции",
    "/api/project/sessions": "Завершённые чаты проекта (журналы без окна), страницами",
    "/api/project/history": "Переписка завершённого чата — без окна",
    "/api/project/session": "«Новая сессия в проекте» — ещё одно окно со своим журналом",
    "/api/project/resume": "«Продолжить» завершённый чат проекта",
    "/api/project/new": "«Новый проект»: папка, инструкции, первая сессия",
    "/api/project/update": "Меню проекта: название и архив",
    "/api/project/chat": "Переименовать или скрыть чат проекта",
    "/api/chat/delete": "«Удалить» сессию или чат: окно закрыто, журнал — в корзину",
    "/api/chat/restore": "«Вернуть» чат из корзины",
    "/api/chat/trash": "Корзина чатов и скрытые чаты",
    "/api/chat/mcp": "Интеграции посреди чата: запомнить и перезапустить с --resume",
    # --- команды на сервере и терминал
    "/api/run": "«Выполнить» команду из ответа на сервере пульта",
    "/api/run/term": "Команда из ответа в окне терминала (нужен ввод)",
    "/api/commands": "Журнал выполненных команд",
    "/api/commands/output": "Вывод команды из журнала",
    "/api/commands/run": "Выполнить команду из журнала ещё раз",
    "/api/commands/term": "Команда из журнала — в окне терминала",
    "/api/commands/mark": "Отметить команду сделанной",
    "/api/term": "Окно терминала панели: экран и живо ли",
    "/api/term/type": "Строка (в том числе пароль) в окно терминала; из Mini App — нет",
    "/api/term/key": "Клавиша в окно терминала (Ctrl+C, Ctrl+D, Enter)",
    "/api/term/close": "Закрыть окно терминала",
    "/api/tty": "Живой терминал: история окна страницами (задача 50)",
    "/api/tty/type": "Живой терминал: текст в окно",
    "/api/tty/key": "Живой терминал: клавиша",
    "/api/tty/size": "Живой терминал: размер окна",
    "/api/shell/open": "«Терминал» рядом с «Ubuntu»: окно ubuntu-shell",
    "/api/desktop/open": "Открыть «Рабочий стол» (noVNC): одноразовая ссылка",
    "/api/desktop/url": "Открыть ссылку вкладкой в Chrome рабочего стола",
    "/api/desktop/mobile": "Мобильный вид сайтов, пока стол смотрят с телефона",
    "/api/links/prefs": "Где открывать ссылки сайтов: на рабочем столе или здесь",
    "/api/gate/desktop": "Проверка входа для Caddy (forward_auth) рабочего стола: только владелец",
    # --- задачи и брифинг
    "/api/tasks": "Задачи владельца (#203); не менялись — 304 без тела",
    "/api/tasks/add": "Добавить задачу руками",
    "/api/tasks/update": "Статус, «что дальше» и поля задачи",
    "/api/tasks/remove": "Удалить задачу",
    "/api/tasks/run": "«Выполнить» команду задачи",
    "/api/brief": "Брифинг первого лица (GAS-18): почта и календарь, собирает код",
    "/api/brief/prefs": "Настройки брифинга: источники, время, дни, пояс",
    "/api/brief/act": "Ответ на пункт брифинга: «Да / Нет / Позже»",
    # --- модели, ключи, расход
    "/api/keys": "Сохранить ключ поставщика модели",
    "/api/keys/remove": "Удалить ключ поставщика",
    "/api/models": "Профили моделей: адрес, основная и быстрая модель",
    "/api/model/default": "Модель Claude по умолчанию для новых сессий",
    "/api/openrouter/start": "Вход в OpenRouter: ссылка на авторизацию (PKCE)",
    "/api/openrouter/info": "OpenRouter: подключён ли, баланс",
    "/api/openrouter/models": "Список моделей OpenRouter",
    "/api/fallback": "Запасная цепочка поставщиков при лимите; POST — сохранить",
    "/api/balance/clear": "«Я пополнил» — снова предлагать поставщика",
    "/api/cost/limits": "Пороги расхода; POST — сохранить",
    "/api/cost/decide": "Пауза по расходу: продолжить или остановить",
    "/api/selftest": "Автотест поставщиков: итог; POST — «Проверить сейчас» в фоне",
    "/api/setup/status": "Мастер: вошёл ли Claude Code на сервере",
    "/api/setup/login": "Мастер: окно входа Claude Code и ссылка с экрана",
    "/api/setup/code": "Мастер: код входа — в окно",
    "/api/setup/cancel": "Мастер: отменить вход",
    "/api/login/code": "Шторка «Нужен вход»: код или адрес — в окно сессии",
    "/api/login/check": "Шторка «Нужен вход»: проверить, вошла ли сессия",
    # --- интеграции (MCP), репозитории, модули
    "/api/mcp": "Интеграции: подключённые, готовые наборы, коннекторы",
    "/api/mcp/add": "Подключить интеграцию из набора",
    "/api/mcp/remove": "Отключить интеграцию",
    "/api/mcp/login": "Вход в интеграцию (OAuth): ссылка",
    "/api/mcp/finish": "Завершить вход в интеграцию по адресу возврата",
    "/api/mcp/connected": "Подключилась ли интеграция после входа",
    "/api/repos": "Репозитории GitHub сессии: подключённые и доступные",
    "/api/repos/add": "Подключить репозиторий: клон и /add-dir",
    "/api/repos/remove": "Отключить репозиторий",
    "/api/modules": "Модули-агенты и их расписание",
    "/api/modules/create": "Создать модуль-агента",
    "/api/module/schedule": "Расписание модуля: оставить, приостановить, выключить",
    "/api/module/delete": "Удалить модуль",
    "/api/drafts": "Черновики действий коннекторов: «Ждут вашего Да»",
    "/api/drafts/yes": "«Да» черновику — выполнить ровно его",
    "/api/drafts/no": "«Нет» черновику",
    "/api/calendars/keys": "Подключённые календари — без значений секретов",
    "/api/calendars/key": "Секрет календаря: в файл 0600 и проверка",
    "/api/calendars/key/remove": "Удалить секрет календаря",
    # --- мост к браузеру пользователя
    "/api/bridge/devices": "Компьютеры с мостом к браузеру",
    "/api/bridge/pair": "Одноразовый код пары (10 мин) для моста",
    "/api/bridge/revoke": "Отключить компьютер",
    "/api/bridge/log": "Журнал действий моста по устройству",
    "/api/bridge/drafts": "Что ждёт «Да» человека на мосту",
    "/api/bridge/confirm": "«Да» действию моста",
    "/api/bridge/reject": "«Нет» действию моста",
    "/api/bridge/private": "«Личные данные не уходят модели» для устройства",
    "/api/bridge/claim": ("Мост: одноразовый код → токен устройства", "code, name, os, old", ""),
    "/api/bridge/rpc": "Агент (gas-pult bridge-mcp) → мост; секрет — файл 0600 на сервере",
    "/api/bridge/code": "Код пары из командной строки сервера (тот же секрет)",
    "/api/bridge/ws": ("Мост: WebSocket с компьютера; токен — в подпротоколе", "WebSocket", ""),
    "/api/bridge/install.sh": ("Установщик моста (macOS, Linux) одной командой — по коду пары `c`; `do=remove` — "
                               "удаление", "c, do", "text/plain"),
    "/api/bridge/install.ps1": ("Установщик моста (Windows) — по коду пары `c`; `do=remove` — удаление", "c, do",
                                "text/plain"),
    "/api/bridge/bridge.mjs": ("Файл моста для установщика", "", "text/javascript"),
    # --- фокус-ссылки
    "/api/focus/new": "Новая фокус-ссылка: сессия, проект или пространство; права и срок",
    "/api/focus/list": "Действующие фокус-ссылки — без токенов",
    "/api/focus/revoke": "Погасить фокус-ссылку",
    "/api/focus/send": "Отправить ссылку себе в Telegram",
    "/api/focus/qr": "QR ссылки (POST — адрес с токеном не попадает в журнал прокси)",
    "/api/focus/browser": "Разрешить фокус-ссылке подключить свой браузер",
    "/api/focus/open": ("Первое открытие фокус-ссылки: привязать устройство (cookie)", "token",
                        "ok, name, mode; cookie"),
    "/api/focus/bridge": "Фокус-ссылка: свой компьютер с мостом",
    "/api/focus/bridge/pair": "Фокус-ссылка: код пары своего компьютера",
    "/api/focus/bridge/revoke": "Фокус-ссылка: отключить свой компьютер",
    "/api/focus/bridge/private": "Фокус-ссылка: «Личные данные не уходят модели»",
    # --- люди, вход, приглашения
    "/api/meta": "Кто я и что видно: роль, сборка, новое, настройки",
    "/api/prefs": "Свои настройки: простой режим, язык, скорость речи",
    "/api/persona": "Вид панели и тумблеры возможностей — свои; потолок задаёт владелец",
    "/api/tour": "Отметки короткого тура: пройден, «Не сейчас»",
    "/api/uses": "Какие экраны открыты (только id, для замера)",
    "/api/clientlog": "Ошибка JS в браузере: тип, экран, место",
    "/api/feedback": "«Отзыв»",
    "/api/terms": "Условия использования: версия и пункты",
    "/api/terms/accept": "Принять условия использования",
    "/api/country": "Страна человека; POST — выбрать",
    "/api/logout": "Выйти на этом устройстве",
    "/api/people": "Люди и роли",
    "/api/people/role": "Назначить роль",
    "/api/people/remove": "Убрать человека",
    "/api/people/access": "Продлить доступ на N дней (0 — бессрочно)",
    "/api/team": "Возможности людей (потолок разделов); POST — сохранить",
    "/api/invite": ("Экран входа: «приглашение в …» — только для действующего кода", "code (query)", ""),
    "/api/invite/new": "Приглашение: ссылка, короткий код и QR",
    "/api/invite/check": ("Лёгкий вход: проверить код приглашения", "code", ""),
    "/api/invite/enter": ("Лёгкий вход: войти по коду приглашения", "code, name", "state; cookie"),
    "/api/invite/device": "Ссылка для входа на другое устройство",
    "/api/invite/qr": ("QR ссылки приглашения (картинка)", "", "image/svg+xml"),
    "/api/link/tg": "«Привязать Telegram»: ссылка на бота",
    "/api/login/methods": "Экран входа: какие способы входа включены",
    "/api/login/start": ("Вход кодом из бота: начать", "", "id"),
    "/api/login/verify": ("Вход кодом из бота: проверить код", "id, code", "ok; cookie"),
    "/api/login/tg": ("Вход через Telegram: POST — начать (ссылка на бота), GET — ждать подтверждения",
                     "POST: invite; GET: id (query)", "POST: id, link, ttl; GET: state (+cookie)"),
    "/api/login/email/start": ("Вход по почте: отправить код", "email", ""),
    "/api/login/email/verify": ("Вход по почте: проверить код", "email, code", "state; cookie"),
    "/api/login/2fa": ("Второй фактор: код с почты", "id, code", "state; cookie"),
    "/api/login/passkey/options": "Вход по ключу (passkey): параметры WebAuthn",
    "/api/login/passkey/verify": ("Вход по ключу: проверить подпись", "id, credential", "state; cookie"),
    "/api/login/oidc/{provider}/{step}": ("Вход через Google или Яндекс ID: start — переход, back — возврат",
                                          "provider: google|yandex, step: start|back; code, state", "302"),
    "/api/email": "Своя почта для входа и оповещений",
    "/api/email/bind": "Привязать почту: отправить код",
    "/api/email/confirm": "Подтвердить почту кодом",
    "/api/email/remove": "Отвязать почту",
    "/api/email/options": "Почта: второй фактор и оповещения",
    "/api/passkeys": "Свои ключи входа",
    "/api/passkeys/options": "Новый ключ входа: параметры WebAuthn",
    "/api/passkeys/add": "Сохранить новый ключ входа",
    "/api/passkeys/remove": "Удалить ключ входа",
    "/api/oidc": "Привязки Google и Яндекс ID",
    "/api/oidc/link": "Ссылка на привязку Google или Яндекс ID",
    "/api/oidc/unlink": "Отвязать Google или Яндекс ID",
    "/api/confirm/start": "Код подтверждения новой сессии браузера: отправить",
    "/api/confirm/verify": "Код подтверждения: проверить",
    "/api/confirm/check": "Подтвердили ли вход кнопкой в боте",
    "/api/help/ask": ("Помощник «? Подсказать»: ответ по карте помощи", "q, chip, ctx", ""),
    "/api/help/feedback": ("Помощник: полезен ли ответ", "id, useful, action", ""),
    "/api/help/call": "Тестировщик: «Позвать на помощь» — владельцу в бот",
    # --- протоколы встреч (meetings.py)
    "/api/meetings": "Протоколы встреч: список",
    "/api/meeting": "Протокол встречи: оглавление, «Что сделать», текст, ссылки на него",
    "/api/meeting/audio": ("Запись встречи (звук)", "id", "аудио"),
    "/api/meeting/card": ("Карточка-превью протокола (SVG 1200×630)", "id", "image/svg+xml"),
    "/api/meeting/share": "«Ссылка на протокол»: фокус-ссылка на один протокол, 30 дней, до 50 устройств",
    "/api/mt": "По ссылке на протокол: протокол без черновика и ссылок (id — из записи ссылки)",
    "/api/mt/audio": ("По ссылке на протокол: запись встречи", "", "аудио"),
    "/api/mt/card": ("По ссылке на протокол: карточка-превью", "", "image/svg+xml"),
    # --- уведомления
    "/api/push/key": "Уведомления на телефон: ключ VAPID",
    "/api/push/devices": "Уведомления: свои устройства",
    "/api/push/last": "Уведомления: последнее (текст по сигналу без содержимого)",
    "/api/push/subscribe": "Уведомления: подписать устройство",
    "/api/push/unsubscribe": "Уведомления: отписать устройство",
    "/api/push/test": "Уведомления: пробное",
    "/api/notify/prefs": "Куда и о чём сообщать (notifyroute.py); менять — владелец",
    # --- «Поделиться»
    "/api/share": ("«Поделиться» с iPhone: токен устройства, не кука", "Authorization, Content-Type; тело", ""),
    "/api/share/list": "«Поделились» — свои неразобранные записи",
    "/api/share/file": "Миниатюра картинки своей записи",
    "/api/share/done": "Запись разобрана: сохранили во «Входящие» или отправили",
    "/api/share/devices": "Устройства «Поделиться» (iPhone)",
    "/api/share/devices/new": "Токен «Быстрой команды» — показывается один раз",
    "/api/share/devices/revoke": "Отозвать токен устройства",
    # --- пространства (демо для тестировщиков)
    "/api/spaces": "Пространства и их бюджет",
    "/api/space/task": "Поставить задачу в пространство",
    "/api/space/connect": "Владелец подключается к окну пространства",
    "/api/space/budget/add": "«+ добавить» к бюджету пространства",
    "/api/space/sessions": "Закрытые сессии пространства и корзина",
    "/api/space/close": "Завершить сессию пространства",
    "/api/space/resume": "Продолжить закрытую сессию пространства",
    "/api/space/delete": "Удалить сессию пространства (в корзину)",
    "/api/space/restore": "Вернуть сессию пространства из корзины",
    "/api/space/files": "Файлы папки сессии пространства",
    "/api/space/download": ("Скачать файл из папки сессии пространства", "", "файл"),
    "/api/space/upload": ("Файл в папку сессии пространства", "тело — байты файла, X-File-Name; w (query)", "name"),
    "/api/space/mcp": "Свои интеграции пространства — без ключей",
    "/api/space/mcp/add": "Подключить интеграцию в своём пространстве",
    "/api/space/mcp/remove": "Отключить интеграцию в своём пространстве",
    # --- анкеты и предложения клиентам (0010)
    "/api/q/new": "Новая личная ссылка на анкету клиента",
    "/api/q/list": "«Анкеты клиентов»: ссылки без кодов и формы",
    "/api/q/answers": "Ответы клиента на анкету",
    "/api/q/{code}": ("Анкета по личному коду: форма и черновик", "", "form, draft, sent"),
    "/api/q/{code}/save": ("Анкета: сохранить черновик", "answers", "ok"),
    "/api/q/{code}/submit": ("Анкета: отправить", "answers", ""),
    "/api/offer/{code}": ("Предложение клиенту по коду: страница данных и демо-сессия", "", "session, bot"),
    "/api/offer/{code}/{act}": ("Действие на странице предложения: upload, forget, wizard, login, help, helpfb, "
                                "telegram", "act", ""),
}


# ------------------------------------------------------------------------------------------------------ сборка
GROUPS = (   # раздел документа → первые части пути (по порядку: первое совпадение)
    ("Сессии и чат", ("sessions", "activity", "ask", "hint", "history", "screen", "last", "cmds", "send", "resend",
                      "key", "select", "command", "active", "new", "folder", "rename", "title", "close", "restart",
                      "revive", "model", "effort", "route", "pin", "order", "upload", "media", "steps", "starters",
                      "starter", "scenarios", "stopped", "notify-done", "notify/level")),
    ("Голос", ("stt", "tts", "voice", "providers")),
    ("Проекты и чаты", ("projects", "project", "chat")),
    ("Команды на сервере и терминал", ("run", "commands", "term", "tty", "shell", "desktop", "links", "gate")),
    ("Задачи и брифинг", ("tasks", "brief")),
    ("Модели, ключи, расход", ("keys", "models", "model/default", "openrouter", "fallback", "balance", "cost",
                               "selftest", "setup", "login/code", "login/check")),
    ("Интеграции, репозитории, модули", ("mcp", "repos", "modules", "module", "drafts", "calendars")),
    ("Мост к браузеру", ("bridge",)),
    ("Фокус-ссылки", ("focus",)),
    ("Люди, вход, приглашения", ("meta", "prefs", "persona", "tour", "uses", "clientlog", "feedback", "terms",
                                 "country", "logout", "people", "team", "invite", "link", "login", "email",
                                 "passkeys", "oidc", "confirm", "help")),
    ("Уведомления", ("push", "notify")),
    ("«Поделиться»", ("share",)),
    ("Пространства", ("spaces", "space")),
    ("Протоколы встреч", ("meetings", "meeting", "mt")),
    ("Анкеты и предложения клиентам", ("q", "offer")),
)


def group(path: str) -> str:
    rest = path.removeprefix("/api/")
    for name, keys in GROUPS:
        if any(rest == k or rest.startswith(k + "/") for k in keys):
            return name
    return "Прочее"


def _split(text: str) -> list[str]:
    """«a, b» → [a, b]; фраза («тело — байты файла; w (query)») остаётся одним полем."""
    parts = [x.strip() for x in text.split(",") if x.strip()]
    return parts if all(re.fullmatch(r"[\w-]+", x) for x in parts) else [text] if text else []


def entries() -> list[dict]:
    """Опись: по строке на путь и метод — всё, из чего собираются оба документа."""
    src = SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    free = _free(tree, _env(tree))
    out = []
    for path, r in scan(src).items():
        d = DESCR.get(path, "")
        text, more_in, more_out = (d, "", "") if isinstance(d, str) else d
        for m in r["methods"]:
            ins, outs = _split(more_in), _split(more_out)
            ins += [x for x in r["in"] if x not in ins]
            outs += [x for x in r["out"] if x not in outs]
            out.append({"path": path, "method": m, "group": group(path), "summary": text, "in": ins, "out": outs,
                        "calls": r["calls"], **who(path, m, r, free)})
    return out


def _cell(xs: list[str]) -> str:
    return ", ".join(f"`{x}`" for x in xs).replace("|", "\\|") or "—"


def markdown() -> str:
    es = entries()
    lines = [
        "# API панели — опись путей",
        "",
        "<!-- Файл собран генератором: python -m gas_pult.api_spec. Руками не править — правьте "
        "src/gas_pult/api_spec.py (описания) или webapp.py (маршруты) и перезапустите генератор. -->",
        "",
        f"Путей: **{len({e['path'] for e in es})}**, пар «путь + метод»: **{len(es)}**. Машиночитаемо — "
        "[`openapi.json`](openapi.json) (OpenAPI 3.1).",
        "",
        "Все пути — под адресом панели, ответы — JSON (кроме отмеченных). Ошибка — `{\"error\": \"…\", \"code\": …}` "
        "с кодом HTTP: 401 — нужен вход, 403 — не хватает прав (`code`: `terms`, `space`, `focus_scope`, `confirm`, "
        "`cap`, `dev`, `budget`), 404 — нет метода, 409/410 — конфликт или ссылка погасла, 429 — лимит.",
        "",
        "## Кто может",
        "",
        "Роль — по формуле `Handler.permit` и таблицам `src/gas_pult/access.py`:",
        "",
        "| Роль | Значит |",
        "|---|---|",
        "| владелец | `OWNER_ONLY` |",
        "| владелец и админ | `OWNER_ONLY` и `ADMIN_OK` |",
        "| участник и выше | POST (кроме личных настроек) и `MEMBER_ONLY`; наблюдателю — нет |",
        "| любой вошедший | чтение и личные настройки — и наблюдателю |",
        "| без входа | обрабатывается до проверки входа: свой код, токен или подпись "
        "(вход, приглашение, мост, анкета) |",
        "| только по фокус-ссылке | путь есть только в режиме фокуса (`focus_do`); обычной панели — 404 |",
        "",
        "Метки:",
        "",
        "| Метка | Значит |",
        "|---|---|",
        *(f"| `{k}…` | {v} |" if k.endswith(":") else f"| `{k}` | {v} |" for k, v in TAGS_RU.items()),
        "",
    ]
    for name in [g for g, _ in GROUPS] + ["Прочее"]:
        rows = [e for e in es if e["group"] == name]
        if not rows:
            continue
        lines += [f"## {name}", "", "| Путь | Метод | Кто | Метки | Что делает | Вход | Выход |",
                  "|---|---|---|---|---|---|---|"]
        for e in rows:
            lines.append(f"| `{e['path']}` | {e['method']} | {ROLE_RU[e['role']]} | {_cell(e['tags'])} | "
                         f"{e['summary'].replace('|', '/')} | {_cell(e['in'])} | {_cell(e['out'])} |")
        lines.append("")
    return "\n".join(lines)


def openapi() -> dict:
    paths: dict[str, dict] = {}
    for e in entries():
        op: dict = {"summary": e["summary"], "tags": [e["group"]],
                    "operationId": (e["method"].lower() + "_" + re.sub(r"[^a-z0-9]+", "_", e["path"][5:])).strip("_"),
                    "x-access": {"role": e["role"], "tags": e["tags"]}}
        if e["role"] != "open":                    # фокус-ссылка — своя cookie, тоже сессия устройства
            op["security"] = [{"session": []}]
        params = [{"name": x, "in": "path", "required": True, "schema": {"type": "string"}}
                  for x in re.findall(r"{(\w+)}", e["path"])]
        names = [x for x in e["in"] if re.fullmatch(r"[a-z_]+", x)]
        if e["method"] == "GET":
            params += [{"name": x, "in": "query", "schema": {"type": "string"}} for x in names]
        elif names:
            op["requestBody"] = {"content": {"application/json": {"schema": {
                "type": "object", "properties": {x: {} for x in names}}}}}
        if params:
            op["parameters"] = params
        outs = [x for x in e["out"] if re.fullmatch(r"[a-z_]+", x)]
        schema: dict = {"type": "object"}
        if outs:
            schema["properties"] = {x: {} for x in outs}
        op["responses"] = {"200": {"description": "успех", "content": {"application/json": {"schema": schema}}},
                           "default": {"$ref": "#/components/responses/Error"}}
        paths.setdefault(e["path"], {})[e["method"].lower()] = op
    return {
        "openapi": "3.1.0",
        "info": {"title": "gas-pult — API панели", "version": "1",
                 "description": "Собрано генератором python -m gas_pult.api_spec из webapp.py и access.py. "
                                "Права — x-access (роль и метки, см. docs/API.md)."},
        "components": {
            "securitySchemes": {"session": {"type": "apiKey", "in": "cookie", "name": "gp_session",
                                            "description": "Сессия браузера; в Mini App — подпись Telegram"}},
            "responses": {"Error": {"description": "ошибка", "content": {"application/json": {"schema": {
                "type": "object", "properties": {"error": {"type": "string"}, "code": {"type": "string"}}}}}}},
        },
        "paths": paths,
    }


def openapi_json() -> str:
    return json.dumps(openapi(), ensure_ascii=False, indent=1) + "\n"


def outputs() -> dict[Path, str]:
    return {DOCS / "API.md": markdown(), DOCS / "openapi.json": openapi_json()}


def main(argv: list[str] | None = None) -> int:
    check = "--check" in (sys.argv[1:] if argv is None else argv)
    stale = []
    for path, text in outputs().items():
        if path.exists() and path.read_text(encoding="utf-8") == text:
            continue
        stale.append(path.name)
        if not check:
            path.write_text(text, encoding="utf-8")
    if stale:
        print(("устарели: " if check else "обновлены: ") + ", ".join(stale))
    return 1 if check and stale else 0


if __name__ == "__main__":                       # python -m gas_pult.api_spec — обновить docs/API.md и openapi.json
    raise SystemExit(main())
