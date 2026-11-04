"""Простой режим панели: английские экраны Claude Code → человеческий русский (и английский) с кнопками-чипами.

Словарь известных шаблонов (docs/SIMPLE-MODE.md): вопросы разрешений («Do you want to proceed?», правка, создание,
команда, веб-доступ, MCP), доверие к папке, план, вопросы агента (AskUserQuestion — тексты пишет сама модель, их
оставляем, а служебные пункты «Type something», «Other», «Submit», «Cancel» переводим), «Press Enter to continue»,
ошибки и фразы строки статуса. Тексты — не здесь, а в словарях панели ``web/i18n/ru.json`` и ``en.json`` (ключи
``ask.*``, ``opt.*``, ``err.*``, ``status.*``): один источник для панели и тестов.

Разбор экрана ``parse(lines)`` → ``{kind, known, title_ru, title_en, detail_ru, detail_en, options, sig}``; у пункта
``{key, label_ru, label_en, send, level, note_ru, note_en}``. ``send`` — что нажать через существующие ``/api/select``
и ``/api/key``: ``{"n": "1"}`` (пункт по номеру), ``{"text": …}`` (пункт без номера), ``{"key": "Enter"|"Escape"}``,
``{"show": "details"}`` (подсказка на экране, в окно ничего не уходит); ``compose: true`` — после нажатия поставить
курсор в поле ввода (ответить своими словами). ``level: 2`` — опасные пункты («больше не спрашивать», «разрешить все
правки»): панель прячет их во второй уровень с пояснением. Неизвестное — общая фраза «Агент спрашивает разрешение» и
чипы «Разрешить» / «Не разрешать» / «Показать подробности», без сырого текста.

Только стандартная библиотека.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
from importlib import resources

# Имена собственные, которые можно писать латиницей и в русском простом режиме (и самоназвание языка в
# переключателе). Тест «нет латиницы на экране» берёт белый список отсюда — одно место.
LATIN_OK = ("Claude", "Telegram", "Google", "Ozon", "WB", "Wildberries", "GigaChat", "YandexGPT", "ElevenLabs",
            "GASTECH", "iPhone", "Android", "OpenRouter", "DeepSeek", "GLM", "Notion", "Gmail", "Excel", "PDF",
            "HoReCa", "Face ID", "Яндекс ID", "English")
# В английском — ни одной кириллической буквы, кроме самоназвания языка в переключателе.
CYRILLIC_OK = ("Русский",)

# ---------- признаки диалога ----------
BOX = re.compile(r"^[\s│┃|╭╮╰╯─━┌┐└┘]+|[\s│┃|╭╮╰╯─━┌┐└┘]+$")
HINT = r"(?:[^·\n]{1,40}·\s*)*"
FOOT = re.compile(r"^\s*" + HINT + r"(Enter to (confirm|select)|Esc to (cancel|close|exit|go back)|"
                  r"↑/↓ to navigate)", re.I)
OPT = re.compile(r"^(❯\s*)?(\d{1,2})\.\s+(?:\[[ ✔✓x×]\]\s*)?(.+?)$")
PLAIN_SEL = re.compile(r"^❯\s*(?!\d+\.)(\S.*)$")
QUESTION = re.compile(r"\?\s*$")
CONTINUE = re.compile(r"Press Enter to continue", re.I)
ASKS = re.compile(r"^(Do you (want|trust)|Would you like to proceed|Ready to submit)", re.I)   # без подсказки
TABS = re.compile(r"[☐☒✔✓]\s+\S")                       # шапка вопросов агента: «☐ Формат  ☐ Срок  ✔ Submit»


# ---------- словарь шаблонов ----------
# Вопрос диалога: (kind, где искать: "q" — строка-вопрос, "ctx" — блок над пунктами, регулярка). Порядок важен.
DIALOGS: list[tuple[str, str, re.Pattern]] = [
    ("trust", "ctx", re.compile(r"Do you trust the files in this folder\?|Is this a project you (created|trust)|"
                                r"Quick safety check|Yes, I trust this folder", re.I)),
    ("plan", "ctx", re.compile(r"Would you like to proceed\?.*|keep planning|auto-accept edits", re.I)),
    ("submit", "ctx", re.compile(r"Ready to submit your answers\?|Review your answers|Submit answers", re.I)),
    ("edit", "q", re.compile(r"^Do you want to make this edit to .+\?$", re.I)),
    ("create", "q", re.compile(r"^Do you want to create .+\?$", re.I)),
    ("overwrite", "q", re.compile(r"^Do you want to (overwrite|write to) .+\?$", re.I)),
    ("fetch", "ctx", re.compile(r"Do you want to allow Claude to fetch this content\?|^Fetch$|"
                                r"Claude wants to fetch content", re.I | re.M)),
    ("search", "ctx", re.compile(r"^Web ?Search$", re.I | re.M)),
    ("mcp", "ctx", re.compile(r"\(MCP\)|^Tool use$|mcp__", re.I | re.M)),
    ("bash", "ctx", re.compile(r"^(Bash|Shell|PowerShell) command$", re.I | re.M)),
    ("read", "ctx", re.compile(r"^Read (file|files)$|allow reading from", re.I | re.M)),
    ("notebook", "ctx", re.compile(r"^Edit notebook$|Do you want to make this edit to .+\.ipynb", re.I | re.M)),
    ("proceed", "q", re.compile(r"^Do you want to proceed\?$", re.I)),
]

# Пункты: (key, регулярка по тексту пункта, уровень). Ключ → подписи opt.<key>.label / .note в словарях.
OPTIONS: list[tuple[str, re.Pattern, int]] = [
    ("yes", re.compile(r"^Yes\.?$", re.I), 1),
    ("yes-proceed", re.compile(r"^Yes, (proceed|continue)\.?$", re.I), 1),
    ("trust-yes", re.compile(r"^Yes, I trust (this|the) folder", re.I), 1),
    ("yes-session", re.compile(r"^Yes, and don'?t ask again (for )?this session", re.I), 2),
    ("yes-always", re.compile(r"^Yes, and don'?t ask again", re.I), 2),
    ("yes-domain", re.compile(r"^Yes, and always allow", re.I), 2),
    ("yes-all-edits", re.compile(r"^Yes, allow all edits", re.I), 2),
    ("yes-read-dir", re.compile(r"^Yes, allow reading from", re.I), 2),
    ("plan-bypass", re.compile(r"^Yes, and bypass permissions", re.I), 2),
    ("plan-auto", re.compile(r"^Yes, and auto-accept edits", re.I), 2),
    ("plan-manual", re.compile(r"^Yes, (and )?manually approve edits", re.I), 1),
    ("plan-keep", re.compile(r"^No, keep planning", re.I), 1),
    ("plan-change", re.compile(r"^Type here to tell Claude what to change", re.I), 1),
    ("no-tell", re.compile(r"^No, and tell Claude what to do differently", re.I), 1),
    ("no-exit", re.compile(r"^No, exit", re.I), 1),
    ("no", re.compile(r"^No\.?$", re.I), 1),
    ("submit", re.compile(r"^Submit( answers)?$", re.I), 1),
    ("cancel", re.compile(r"^Cancel$", re.I), 1),
    ("type", re.compile(r"^Type something\.?$", re.I), 1),
    ("other", re.compile(r"^Other$", re.I), 1),
    ("chat", re.compile(r"^Chat about this$", re.I), 1),
]
# Служебные пункты вопроса агента, которые значат «ответить своими словами»: Esc закрывает вопрос, курсор — в поле
# ввода (иначе пульт не примет текст, пока на экране вопрос).
COMPOSE = {"type", "other", "chat", "plan-change"}

# Ошибки и служебные строки Claude Code (журнал и экран) → err.<key>.
ERRORS: list[tuple[str, re.Pattern]] = [
    ("credit", re.compile(r"Credit balance is too low", re.I)),
    # у поставщика закончились деньги: Z.ai — 429 с кодом 1113, DeepSeek — 402 (balance.py); раньше «limit» (429)
    ("balance", re.compile(r'"code"\s*:\s*"?1113\b|insufficient[ _](account[ _])?balance|API Error:\s*402\b|'
                           r"Payment Required", re.I)),
    ("limit", re.compile(r"usage limit reached|limit reached\b|hit your (usage )?limit|rate[_ ]limit|"
                         r"API Error:\s*429|Too many requests", re.I)),
    ("overloaded", re.compile(r"Overloaded|API Error:\s*5\d\d|overloaded_error|internal server error", re.I)),
    ("auth", re.compile(r"Invalid API key|Please run /login|OAuth token (has )?expired|API Error:\s*40[13]|"
                        r"authentication_error|Not logged in", re.I)),
    ("network", re.compile(r"Connection error|Request timed out|ECONNRESET|ETIMEDOUT|fetch failed|"
                           r"socket hang up", re.I)),
    ("context", re.compile(r"Prompt is too long|Context low|Context left until auto-compact|"
                           r"context (window|length) exceeded", re.I)),
    ("interrupted", re.compile(r"Interrupted by user|Request interrupted|^\s*Interrupted\b", re.I | re.M)),
    ("api", re.compile(r"^\s*API Error\b", re.I | re.M)),
]

# Строка статуса: инструмент Claude Code → обобщённое действие (status.<key>): имена файлов и команды в простом
# режиме не показываем. Тот же список — в index.html (SIMPLE_TOOL), тест сверяет.
TOOLS = {"Read": "reads", "Grep": "reads", "Glob": "reads", "LS": "reads",
         "Edit": "edits", "MultiEdit": "edits", "Write": "writes", "NotebookEdit": "edits",
         "Bash": "acts", "PowerShell": "acts", "BashOutput": "acts", "KillShell": "acts", "Skill": "acts",
         "WebSearch": "web", "WebFetch": "web", "Task": "helper", "Agent": "helper",
         "TodoWrite": "plans", "TaskCreate": "plans", "TaskUpdate": "plans",
         "AskUserQuestion": "waiting", "ExitPlanMode": "waiting"}
PHASES = ("sent", "delivered", "started", "working", "thinking", "waiting", "done", "queued", "stuck", "idle")


@functools.cache
def dictionary(lang: str) -> dict:
    """Словарь панели ``web/i18n/<lang>.json`` (ru или en)."""
    if lang not in ("ru", "en"):
        raise ValueError("язык — ru или en")
    return json.loads(resources.files("gas_pult").joinpath(f"web/i18n/{lang}.json").read_text(encoding="utf-8"))


def text(key: str) -> dict:
    """{ru, en} по ключу словаря (нет ключа — KeyError: тест ловит пропуски)."""
    return {"ru": dictionary("ru")[key], "en": dictionary("en")[key]}


def tidy(line: str) -> str:
    return BOX.sub("", line.replace(" ", " ")).strip()


def _options(lines: list[str]) -> tuple[list[dict], int]:
    """Нумерованные пункты внизу экрана: последний блок 1…N (между пунктами — их пояснения, до 3 строк).
    Возвращает (пункты, индекс строки первого пункта) или ([], -1)."""
    last = next((i for i in range(len(lines) - 1, -1, -1) if OPT.match(lines[i])), -1)
    if last < 0:
        return [], -1
    m = OPT.match(lines[last])
    found = [{"n": int(m.group(2)), "text": m.group(3).strip(), "sel": bool(m.group(1))}]
    first, gap = last, 0
    for i in range(last - 1, -1, -1):
        if found[0]["n"] == 1:
            break
        m = OPT.match(lines[i])
        if m and int(m.group(2)) == found[0]["n"] - 1:
            found.insert(0, {"n": int(m.group(2)), "text": m.group(3).strip(), "sel": bool(m.group(1))})
            first, gap = i, 0
            continue
        gap += 1
        if m or gap > 3 or QUESTION.search(lines[i]):
            return [], -1
    if found[0]["n"] != 1 or len(found) < 2:
        return [], -1
    return found, first


def _plain(lines: list[str], foot: int) -> tuple[list[dict], int]:
    """Меню без номеров (старый вид доверия к папке): строка с ❯ и соседние строки того же отступа."""
    sel = next((i for i in range(foot - 1, -1, -1) if PLAIN_SEL.match(lines[i])), -1)
    if sel < 0:
        return [], -1
    a = z = sel
    while a > 0 and lines[a - 1] and not QUESTION.search(lines[a - 1]) and len(lines[a - 1]) < 60:
        a -= 1
    while z < foot - 1 and lines[z + 1]:
        z += 1
    opts = [{"n": 0, "text": x.removeprefix("❯").strip(), "sel": x.startswith("❯")} for x in lines[a:z + 1]]
    opts = [o for o in opts if o["text"]]
    return (opts, a) if len(opts) >= 2 else ([], -1)


def _option(o: dict, kind: str) -> dict | None:
    """Пункт меню → чип. Вопрос агента: незнакомый пункт — текст модели как есть; разрешение: незнакомый пункт
    «Yes…»/«No…» — общие слова, остальное не показываем (сырого английского в простом режиме нет)."""
    key, level = None, 1
    for k, rx, lv in OPTIONS:
        if rx.search(o["text"]):
            key, level = k, lv
            break
    send: dict = {"n": str(o["n"])} if o["n"] else {"text": o["text"]}
    if key in COMPOSE:
        send = {"key": "Escape", "compose": True}
    if key:
        lab, note = text(f"opt.{key}.label"), text(f"opt.{key}.note")
        return {"key": key, "label_ru": lab["ru"], "label_en": lab["en"], "send": send, "level": level,
                "note_ru": note["ru"], "note_en": note["en"]}
    if kind == "question":
        return {"key": f"q{o['n']}", "label_ru": o["text"], "label_en": o["text"], "send": send, "level": 1,
                "note_ru": "", "note_en": "", "raw": True}
    if re.match(r"^Yes\b", o["text"], re.I):
        lab, note = text("opt.yes-other.label"), text("opt.yes-other.note")
        return {"key": "yes-other", "label_ru": lab["ru"], "label_en": lab["en"], "send": send, "level": 2,
                "note_ru": note["ru"], "note_en": note["en"]}
    if re.match(r"^No\b", o["text"], re.I):
        lab = text("opt.no.label")
        return {"key": "no-other", "label_ru": lab["ru"], "label_en": lab["en"], "send": send, "level": 1,
                "note_ru": "", "note_en": ""}
    return None


def _details_chip() -> dict:
    lab = text("opt.details.label")
    return {"key": "details", "label_ru": lab["ru"], "label_en": lab["en"], "send": {"show": "details"}, "level": 1,
            "note_ru": "", "note_en": ""}


def _result(kind: str, options: list[dict], known: bool = True, title: str | None = None) -> dict:
    t = text(f"ask.{kind}.title") if title is None else {"ru": title, "en": title}
    d = text(f"ask.{kind}.detail")
    if kind not in ("question", "submit", "continue") and not any(o["key"] == "details" for o in options):
        options = [*options, _details_chip()]
    sig = hashlib.md5(json.dumps([kind, t["ru"], [(o["key"], o["send"]) for o in options]],
                                 ensure_ascii=False).encode()).hexdigest()[:12]
    return {"kind": kind, "known": known, "title_ru": t["ru"], "title_en": t["en"], "detail_ru": d["ru"],
            "detail_en": d["en"], "options": options, "sig": sig}


def unknown(opts: list[dict] | None = None) -> dict:
    """Незнакомый диалог: «Агент спрашивает разрешение» и три чипа. «Разрешить» — первый пункт (обычно «Yes»),
    без пунктов — Enter; «Не разрешать» — Esc (в вопросах Claude Code это «нет»)."""
    allow = {"n": "1"} if opts and opts[0]["n"] == 1 else {"key": "Enter"}
    a, n = text("opt.allow.label"), text("opt.deny.label")
    return _result("unknown", [
        {"key": "allow", "label_ru": a["ru"], "label_en": a["en"], "send": allow, "level": 1, "note_ru": "",
         "note_en": ""},
        {"key": "deny", "label_ru": n["ru"], "label_en": n["en"], "send": {"key": "Escape"}, "level": 1,
         "note_ru": "", "note_en": ""},
        _details_chip()], known=False)


def parse(lines: list[str] | str) -> dict | None:
    """Экран окна Claude Code → вопрос простыми словами или None (вопроса на экране нет)."""
    raw = lines.splitlines() if isinstance(lines, str) else list(lines)
    tail = [tidy(x) for x in raw[-45:]]
    while tail and not tail[-1]:
        tail.pop()
    if not tail:
        return None
    if any(CONTINUE.search(x) for x in tail[-4:]):
        lab = text("opt.continue.label")
        return _result("continue", [{"key": "continue", "label_ru": lab["ru"], "label_en": lab["en"],
                                     "send": {"key": "Enter"}, "level": 1, "note_ru": "", "note_en": ""}])
    foot = next((i for i in range(len(tail) - 1, max(-1, len(tail) - 8), -1) if FOOT.search(tail[i])), -1)
    opts, first = _options(tail)
    has_q = any(ASKS.match(x) for x in tail[-25:])
    if not opts and foot >= 0:
        opts, first = _plain(tail, foot)
    if not opts or not (foot >= 0 or has_q):
        return None                                    # нумерованные строки без меню — это ваши сообщения
    above = tail[max(0, first - 25):first]
    q = next((x for x in reversed(above) if QUESTION.search(x)), "")
    ctx = "\n".join(above)
    kind = next((k for k, where, rx in DIALOGS if rx.search(q if where == "q" else ctx)), None)
    if kind == "plan" and not re.search(r"keep planning|auto-accept|manually approve|bypass", "\n".join(
            o["text"] for o in opts), re.I):
        kind = None
    if kind is None and (TABS.search(ctx) or any(re.match(r"^(Type something|Other|Chat about this)\b", o["text"],
                                                          re.I) for o in opts)):
        kind = "question"
    if kind is None:
        return unknown(opts)
    chips = [c for c in (_option(o, kind) for o in opts) if c]
    if kind != "question" and not any(c["level"] == 1 and not c["send"].get("show") for c in chips):
        return unknown(opts)
    if kind == "question" and q:
        return _result("question", chips, title=q)       # вопрос написала модель — оставляем как есть
    return _result(kind, chips)


# Ответ в журнале — это служебная строка Claude Code, а не текст агента, если начинается так (для переписки: обычный
# ответ агента про «rate limit» ошибкой не считаем).
ERROR_LINE = re.compile(r"^\s*(API Error|Credit balance|Claude AI usage limit|\d+-hour limit|You'?ve hit your|"
                        r"Invalid API key|OAuth token|\[?Request interrupted|Interrupted by user|Prompt is too long|"
                        r"Context low|Please run /login|Not logged in)", re.I)


def error(message: str, strict: bool = False) -> dict | None:
    """Ошибка или служебная строка Claude Code → {key, ru, en}; не похоже на ошибку — None. ``strict`` — только
    короткая строка, которая начинается как служебная (ответы агента в переписке)."""
    s = str(message or "")[:600]
    if strict and (len(s) > 400 or not ERROR_LINE.match(s)):
        return None
    for key, rx in ERRORS:
        if rx.search(s):
            t = text(f"err.{key}")
            return {"key": key, "ru": t["ru"], "en": t["en"]}
    return None


def status_key(phase: str, tool: str = "") -> str:
    """Фаза строки статуса и инструмент → ключ ``status.*`` словаря (без имён файлов и команд)."""
    if phase == "working":
        if tool.startswith("mcp__"):
            return "status.service"
        return "status." + TOOLS.get(tool, "works")
    return "status." + (phase if phase in PHASES else "idle")


def templates_count() -> dict:
    """Сколько шаблонов в словаре (для документации и PR): диалоги — DIALOGS и ещё «вопрос агента», «нажмите
    Enter», «неизвестное»; пункты — OPTIONS и общие «Да (другой)», «Нет (другой)», «Разрешить», «Не разрешать»,
    «Показать подробности», «Продолжить»."""
    return {"dialogs": len(DIALOGS) + 3, "options": len(OPTIONS) + 6, "errors": len(ERRORS),
            "tools": len(TOOLS)}


# ---------- демо панели (?demo&simple=1): готовый разбор тех же экранов ----------
DEMO_SCREENS = {
    "bash": ["● Bash(npm test)", "  ⎿  24 passed", "", " Bash command", "   rm -rf dist && npm run build",
             "   Remove dist and rebuild", "", " Do you want to proceed?", " ❯ 1. Yes",
             "   2. Yes, and don't ask again for rm commands in /home/u/projects/icon",
             "   3. No, and tell Claude what to do differently (esc)"],
    "edit": [" Edit file", " report.md", "  12 - Выручка: 120", "  12 + Выручка: 128", "",
             " Do you want to make this edit to report.md?", " ❯ 1. Yes",
             "   2. Yes, allow all edits during this session (shift+tab)",
             "   3. No, and tell Claude what to do differently (esc)"],
    "question": ["←  ☐ Отчёт  ✔ Submit  →", "", "Какой отчёт прислать утром?", "", "❯ 1. Короткий — три цифры",
                 "     Выручка, машины, средний чек", "  2. Подробный — по каждой мойке", "  3. Type something.",
                 "", "Enter to select · Tab/Arrow keys to navigate · Esc to cancel"],
    "unknown": [" Something new", "", " Allow the experimental thing?", " ❯ 1. Sure", "   2. Nope", "",
                " Enter to confirm · Esc to cancel"],
}


def demo_json() -> str:
    """Одна строка для index.html: ``const SIMPLE_DEMO = {…};`` — разбор демо-экранов (тест сверяет)."""
    return json.dumps({k: parse(v) for k, v in DEMO_SCREENS.items()}, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":       # python -m gas_pult.humanize — обновить демо-разбор в index.html после правки словаря
    from pathlib import Path
    page = Path(__file__).with_name("web") / "index.html"
    src = page.read_text(encoding="utf-8")
    new, n = re.subn(r"^const SIMPLE_DEMO = .*;$", lambda _: f"const SIMPLE_DEMO = {demo_json()};", src, flags=re.M)
    if n != 1:
        raise SystemExit("в index.html нет строки const SIMPLE_DEMO = …;")
    page.write_text(new, encoding="utf-8")
    print(f"демо простого режима обновлено: {', '.join(DEMO_SCREENS)} → {page}")
