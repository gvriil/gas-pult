"""Простой режим: английские экраны Claude Code → русские (и английские) чипы с правильными нажатиями (humanize.py).

Образцы — вид экранов Claude Code 2.x (рамки │ и без них), как их отдаёт tmux: разрешения на правку, создание,
команду, веб-доступ, MCP, доверие к папке, план, вопросы агента со служебными пунктами, «Press Enter to continue»,
ошибки и неизвестное. Неизвестное — общая фраза и три чипа, без сырого текста."""

import re

import pytest

from gas_pult import humanize as h

LATIN = re.compile(r"[A-Za-z]")
CYR = re.compile(r"[А-Яа-яЁё]")

BASH = """● Bash(npm test)
  ⎿  24 passed

╭──────────────────────────────────────────────────────────────╮
│ Bash command                                                 │
│                                                              │
│   rm -rf dist && npm run build                               │
│   Remove dist and rebuild                                    │
│                                                              │
│ Do you want to proceed?                                      │
│ ❯ 1. Yes                                                     │
│   2. Yes, and don't ask again for rm commands in /home/u/p   │
│   3. No, and tell Claude what to do differently (esc)        │
╰──────────────────────────────────────────────────────────────╯"""

EDIT = """ Edit file
 ╭────────────────────────────╮
 │ report.md                  │
 │  12 - Выручка: 120         │
 │  12 + Выручка: 128         │
 ╰────────────────────────────╯
 Do you want to make this edit to report.md?
 ❯ 1. Yes
   2. Yes, allow all edits during this session (shift+tab)
   3. No, and tell Claude what to do differently (esc)"""

CREATE = """ Create file
 notes/plan.md
 # План на неделю
 Do you want to create plan.md?
 ❯ 1. Yes
   2. Yes, allow all edits during this session (shift+tab)
   3. No, and tell Claude what to do differently (esc)"""

FETCH = """ Fetch

   https://example.com/prices
   Claude wants to fetch content from example.com

 Do you want to allow Claude to fetch this content?
 ❯ 1. Yes
   2. Yes, and don't ask again for example.com
   3. No, and tell Claude what to do differently (esc)"""

SEARCH = """ Web Search

   "цены на шиномонтаж 2026"

 Do you want to proceed?
 ❯ 1. Yes
   2. No, and tell Claude what to do differently (esc)"""

MCP = """ Tool use

   notion - notion-search(query: "отчёты") (MCP)
   Search the workspace

 Do you want to proceed?
 ❯ 1. Yes
   2. Yes, and don't ask again for notion - notion-search commands in /home/u/p
   3. No, and tell Claude what to do differently (esc)"""

READ = """ Read file

   Read(/etc/hosts)

 Do you want to proceed?
 ❯ 1. Yes
   2. Yes, allow reading from etc/ during this session
   3. No, and tell Claude what to do differently (esc)"""

TRUST = """ Do you trust the files in this folder?

 /home/u/projects/shop

 Claude Code may read, write, or execute files contained in this directory. This can pose security risks, so only
 use files from trusted sources.

 Learn more

 ❯ 1. Yes, proceed
   2. No, exit

 Enter to confirm · Esc to exit"""

TRUST_NEW = """ Accessing workspace:

 /home/u/projects/shop

 Quick safety check: Is this a project you created or one you trust? (Like your own code, a well-known open source
 project, or work from your team). If not, take a moment to review what's in this folder first.

 ❯ 1. Yes, I trust this folder
   2. No, exit

 Enter to confirm · Esc to cancel"""

PLAN = """ Here is Claude's plan:
 ╭──────────────────────────╮
 │ 1. Собрать выгрузку       │
 │ 2. Посчитать выручку      │
 ╰──────────────────────────╯

 Would you like to proceed?

 ❯ 1. Yes, and auto-accept edits
   2. Yes, and manually approve edits
   3. No, keep planning"""

QUESTION = """←  ☐ Отчёт  ☐ Срок  ✔ Submit  →

Какой отчёт прислать утром?

❯ 1. Короткий — три цифры
     Выручка, машины, средний чек
  2. Подробный — по каждой мойке
     Таблица по филиалам
  3. Type something.

Enter to select · Tab/Arrow keys to navigate · Esc to cancel"""

QUESTION_MULTI = """☐ Каналы

Где отвечать на отзывы?

❯ 1. [ ] Яндекс Карты
  2. [ ] 2ГИС
  3. [ ] Other
  4. Chat about this

Enter to select · ↑/↓ to navigate · Esc to cancel"""

SUBMIT = """Review your answers

 ● Какой отчёт прислать утром?
   → Короткий — три цифры

Ready to submit your answers?

❯ 1. Submit answers
  2. Cancel"""

PRESS = """ Login successful. Press Enter to continue…"""

UNKNOWN = """ Something brand new

 Allow the experimental thing?
 ❯ 1. Sure
   2. Nope

 Enter to confirm · Esc to cancel"""

PLAIN = """ Do you trust the files in this folder?

 /home/u/projects/shop

 ❯ Yes, proceed
   No, exit

 Enter to confirm · Esc to exit"""

NOT_A_DIALOG = """> Сделай отчёт по пунктам:
❯ 1. Выручка
  2. Машины
  3. Средний чек

● Готово: отчёт в report.md

❯ """


def keys(r):
    return [o["key"] for o in r["options"]]


def chip(r, key):
    return next(o for o in r["options"] if o["key"] == key)


@pytest.mark.parametrize("screen,kind,title", [
    (BASH, "bash", "Агент хочет выполнить действие на компьютере"),
    (EDIT, "edit", "Агент хочет изменить документ"),
    (CREATE, "create", "Агент хочет создать новый документ"),
    (FETCH, "fetch", "Агент хочет открыть страницу в интернете"),
    (SEARCH, "search", "Агент хочет поискать в интернете"),
    (MCP, "mcp", "Агент хочет воспользоваться подключённым сервисом"),
    (READ, "read", "Агент хочет прочитать документ вне своей папки"),
    (TRUST, "trust", "Можно ли агенту работать с файлами этой папки?"),
    (TRUST_NEW, "trust", "Можно ли агенту работать с файлами этой папки?"),
    (PLAN, "plan", "Агент составил план. Начинать?"),
    (SUBMIT, "submit", "Отправить ваши ответы агенту?"),
    (PRESS, "continue", "Агент ждёт, чтобы вы продолжили"),
    (UNKNOWN, "unknown", "Агент спрашивает разрешение"),
    (PLAIN, "trust", "Можно ли агенту работать с файлами этой папки?"),
])
def test_known_screens_are_human(screen, kind, title):
    r = h.parse(screen)
    assert r and r["kind"] == kind and r["title_ru"] == title, r
    assert r["title_en"] and not CYR.search(r["title_en"] + r["detail_en"])
    assert not LATIN.search(r["title_ru"] + r["detail_ru"])
    for o in r["options"]:                                   # подписи — без чужих букв, у каждого — что нажать
        assert o["label_ru"] and not LATIN.search(o["label_ru"]) and not CYR.search(o["label_en"]), o
        assert set(o["send"]) <= {"n", "text", "key", "show", "compose"} and o["send"], o
        assert not LATIN.search(o["note_ru"]) and not CYR.search(o["note_en"]), o


def test_bash_permission_chips():
    r = h.parse(BASH)
    assert keys(r) == ["yes", "yes-always", "no-tell", "details"]
    assert chip(r, "yes")["send"] == {"n": "1"} and chip(r, "yes")["label_ru"] == "Да"
    assert chip(r, "no-tell")["send"] == {"n": "3"} and chip(r, "no-tell")["label_en"] == "No"
    danger = chip(r, "yes-always")                           # «больше не спрашивать» — второй уровень, с пояснением
    assert danger["level"] == 2 and danger["send"] == {"n": "2"} and "уверены" in danger["note_ru"]
    assert chip(r, "details")["send"] == {"show": "details"}
    assert [o["level"] for o in r["options"] if o["key"] != "yes-always"] == [1, 1, 1]


def test_edit_create_allow_all_is_second_level():
    for screen in (EDIT, CREATE):
        r = h.parse(screen)
        assert chip(r, "yes-all-edits")["level"] == 2 and chip(r, "yes-all-edits")["send"] == {"n": "2"}
        assert "report.md" not in str(r) and "plan.md" not in str(r)       # имён файлов в простом режиме нет


def test_fetch_and_mcp_wider_permissions():
    assert chip(h.parse(FETCH), "yes-always")["level"] == 2
    m = h.parse(MCP)
    assert keys(m) == ["yes", "yes-always", "no-tell", "details"] and "notion" not in str(m).lower()
    assert chip(h.parse(READ), "yes-read-dir")["level"] == 2


def test_trust_and_plan():
    t = h.parse(TRUST)
    assert keys(t) == ["yes-proceed", "no-exit", "details"] and chip(t, "no-exit")["send"] == {"n": "2"}
    assert keys(h.parse(TRUST_NEW))[:2] == ["trust-yes", "no-exit"]
    p = h.parse(PLAN)
    assert keys(p) == ["plan-auto", "plan-manual", "plan-keep", "details"]
    assert chip(p, "plan-auto")["level"] == 2 and chip(p, "plan-manual")["level"] == 1
    plain = h.parse(PLAIN)                                   # меню без номеров — выбираем пункт по тексту
    assert chip(plain, "yes-proceed")["send"] == {"text": "Yes, proceed"}


def test_agent_question_keeps_model_text_and_translates_service_items():
    r = h.parse(QUESTION)
    assert r["kind"] == "question" and r["title_ru"] == "Какой отчёт прислать утром?"
    assert [o["label_ru"] for o in r["options"]] == ["Короткий — три цифры", "Подробный — по каждой мойке",
                                                     "Свой вариант"]
    assert r["options"][0]["send"] == {"n": "1"} and r["options"][1]["send"] == {"n": "2"}
    own = chip(r, "type")                                    # «Type something» — ответить своими словами
    assert own["send"] == {"key": "Escape", "compose": True} and own["label_en"] == "Your own answer"
    assert "details" not in keys(r)
    m = h.parse(QUESTION_MULTI)
    assert [o["label_ru"] for o in m["options"]] == ["Яндекс Карты", "2ГИС", "Другое", "Обсудить с агентом"]
    s = h.parse(SUBMIT)
    assert keys(s) == ["submit", "cancel"] and chip(s, "submit")["send"] == {"n": "1"}
    assert chip(s, "submit")["label_ru"] == "Отправить ответы" and chip(s, "cancel")["label_en"] == "Cancel"


def test_press_enter_and_unknown():
    p = h.parse(PRESS)
    assert keys(p) == ["continue"] and p["options"][0]["send"] == {"key": "Enter"}
    u = h.parse(UNKNOWN)
    assert u["known"] is False and u["title_en"] == "The agent is asking for permission"
    assert [o["label_ru"] for o in u["options"]] == ["Разрешить", "Не разрешать", "Показать подробности"]
    assert [o["send"] for o in u["options"]] == [{"n": "1"}, {"key": "Escape"}, {"show": "details"}]
    assert "experimental" not in str(u) and "Sure" not in str(u)          # сырого текста нет


def test_unknown_permission_options_never_raw():
    screen = BASH.replace("Yes, and don't ask again for rm commands in /home/u/p", "Yes, and something new")
    r = h.parse(screen)
    assert chip(r, "yes-other")["level"] == 2 and "something" not in str(r)
    odd = BASH.replace("3. No, and tell Claude what to do differently (esc)", "3. Maybe later")
    assert "Maybe" not in str(h.parse(odd))


def test_no_dialog_no_question():
    assert h.parse(NOT_A_DIALOG) is None                     # ваши нумерованные сообщения — не меню
    assert h.parse("") is None and h.parse(["● Готово", "", "❯ "]) is None


@pytest.mark.parametrize("text,key", [
    ('API Error: 529 {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}', "overloaded"),
    ("API Error: 500 Internal server error", "overloaded"),
    ("API Error: 429 rate_limit_error: Number of request tokens has exceeded your per-minute rate limit", "limit"),
    ("Claude AI usage limit reached|1793660400", "limit"),
    ("5-hour limit reached ∙ resets 3pm", "limit"),
    ("Credit balance is too low", "credit"),
    ("Invalid API key · Please run /login", "auth"),
    ("OAuth token has expired. Please obtain a new token or refresh your existing token.", "auth"),
    ("API Error: Connection error.", "network"),
    ("API Error: Request timed out.", "network"),
    ("Prompt is too long", "context"),
    ("Context low (8% remaining) · Run /compact to compact & continue", "context"),
    ("[Request interrupted by user]", "interrupted"),
    ("Interrupted by user", "interrupted"),
    ("API Error: 400 invalid_request_error", "api"),
])
def test_errors_human(text, key):
    e = h.error(text)
    assert e and e["key"] == key and not LATIN.search(e["ru"]) and not CYR.search(e["en"]), (text, e)


def test_plain_text_is_not_an_error():
    assert h.error("Готово: отчёт за неделю в таблице") is None
    assert h.error("Выручка выросла на 7 %") is None
    # в переписке — только служебные строки Claude Code, не ответ агента, где встретилось «rate limit»
    assert h.error("Проверил: у API есть rate limit 60 запросов в минуту.", strict=True) is None
    assert h.error("API Error: 529 Overloaded", strict=True)["key"] == "overloaded"
    assert h.error("[Request interrupted by user]", strict=True)["key"] == "interrupted"


def test_status_keys_generalize_tools():
    assert h.status_key("working", "Read") == "status.reads"
    assert h.status_key("working", "Bash") == "status.acts"
    assert h.status_key("working", "mcp__claude_ai_Notion__notion-search") == "status.service"
    assert h.status_key("working", "Unknown") == "status.works"
    assert h.status_key("thinking") == "status.thinking" and h.status_key("weird") == "status.idle"
    for k in {*h.TOOLS.values(), "service", "works", *h.PHASES} - {"working"}:
        assert h.text("status." + k)["ru"]


def test_template_count():
    c = h.templates_count()
    assert c["dialogs"] >= 15 and c["options"] >= 20 and c["errors"] >= 8
