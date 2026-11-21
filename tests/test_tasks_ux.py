"""Задачи удобнее (владелец 21.11): кнопка «Задачи» справа сверху; «добавь задачу …» из чата — агент ставит задачу
командой ``gas-pult task add "…"``, в задаче видно, из какого чата она пришла, и есть переход в этот чат; карточки
с рамкой и тоном по срочности, группы «Срочно», «Сегодня», «Позже», «Сделано»."""

import time
from pathlib import Path

import pytest
from test_project_chats import OPEN, call
from test_project_chats import server as server

from gas_pult import cli, projects, starters, tasks

SID = "22222222-2222-4222-8222-222222222222"
WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"


@pytest.fixture
def agent(tmp_path, monkeypatch):
    """Окружение агента в чате пульта: разговор — CLAUDE_CODE_SESSION_ID, окна tmux — подменены."""
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SID)
    monkeypatch.setattr(cli, "_windows", lambda: [{"id": "@7", "idx": 7, "name": "shop-7", "sid": SID}])
    return tmp_path


def test_cli_add_from_chat_fills_sid_chat_and_title(agent, monkeypatch, capsys):
    monkeypatch.setattr(cli, "own_window", lambda: ("", ""))                # окна по TMUX_PANE нет — ищем по разговору
    projects.Store(agent / projects.FILE, str(agent)).set_chat(SID, "", title="Долг: ООО Ромашка — 46 000 ₽")
    cli.main(["task", "add", "Позвонить бухгалтеру", "--due", "2026-12-01"])
    x = tasks.Tasks(agent / "tasks.json").list()[0]
    assert x["title"] == "Позвонить бухгалтеру" and x["due"] == "2026-12-01"
    assert x["sid"] == SID and x["chat"] == "@7"
    assert x["chat_title"] == "Долг: ООО Ромашка — 46 000 ₽"                  # «из чата «…»» — по смыслу
    assert x["next"] == "продолжить в чате"                                     # одной фразой: «добавь задачу …»
    assert "чат @7" in capsys.readouterr().out


def test_cli_env_sid_wins_over_window_label(agent, monkeypatch):
    monkeypatch.setattr(cli, "own_window", lambda: ("@7", "shop-7"))
    monkeypatch.setattr(cli, "_sid_of", lambda wid: "33333333-3333-4333-8333-333333333333")
    cli.main(["task", "add", "--title", "Сверить акт", "--next", "открыть акт"])
    x = tasks.Tasks(agent / "tasks.json").list()[0]
    assert x["sid"] == SID and x["chat"] == "@7" and x["chat_title"] == "shop-7"   # названия нет — имя окна
    assert x["by"] == "агент · shop-7"


def test_cli_outside_chat_needs_next(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr(cli, "own_window", lambda: ("", ""))
    with pytest.raises(SystemExit, match="не записал"):                         # вне чата — «что дальше» обязательно
        cli.main(["task", "add", "Без чата"])


def test_api_gives_task_chat(server):
    p, base, *_ = server
    tok = p.auth.issue(1)
    code, _ = call(base, "/api/tasks/add", {"title": "Ответить клиенту", "next": "продолжить в чате", "sid": OPEN,
                                            "chat_title": "Открытый чат"}, tok)
    assert code == 200
    t = call(base, "/api/tasks", tok=tok)[1]["tasks"][0]
    assert t["chat_now"] == "@1" and t["chat_name"] == "shop-1"                 # окно нашлось по разговору
    assert t["chat_title"] == "Открытый чат" and t["group"] == "later"
    assert call(base, "/api/sessions", tok=tok)[1]["tasks"]["urgent"] == 0
    assert call(base, "/api/tasks", tok=p.auth.issue(2))[0] == 403            # задачи — только владельцу


def test_starter_hint_only_for_owner(server):
    p, base, *_ = server
    d = call(base, "/api/starter", {"id": "day-plan", "w": "@1"}, p.auth.issue(1))[1]
    assert "gas-pult task add" in d["prompt"]
    d = call(base, "/api/starter", {"id": "day-plan", "w": "@1"}, p.auth.issue(2))[1]
    assert "gas-pult task add" not in d["prompt"]                               # участник: задачи владельца — не его
    assert starters.TASK_HINT not in starters.prompt("day-plan")


def test_groups_and_counter(tmp_path):
    t = tasks.Tasks(tmp_path / "tasks.json")
    today = time.strftime("%Y-%m-%d")
    mk = lambda title, **kw: t.add({"title": title, "next": "x", **kw})       # noqa: E731
    mk("Просрочено", due="2020-01-01")
    mk("Срочно", urgent=True)
    mk("Ждёт вас", status="waiting")
    mk("Сегодня срок", due=today)
    mk("В работе", status="doing")
    mk("Потом")
    mk("Сделано", status="done")
    g = {x["title"]: x["group"] for x in t.list()}
    assert g == {"Просрочено": "urgent", "Срочно": "urgent", "Ждёт вас": "urgent", "Сегодня срок": "today",
                 "В работе": "today", "Потом": "later", "Сделано": "done"}
    assert t.open_count()["urgent"] == 3


def test_header_button_in_core():
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert len(index.encode()) < 770_000
    top = index[index.index('<header class="top" id="top">'):index.index("</header>")]
    assert top.index('id="tasksTop"') < top.index('id="chatMoreBtn"')          # справа, рядом с ⋯
    assert "function tasksTop()" in index and 'b.hidden = meta?.role !== "owner"' in index
    assert '$("tasksTop").onclick = () => part("tasks").then(() => tasksOpen()' in index
    assert "body.focus #tasksTop { display: none !important; }" in index


def test_cards_tone_and_quick_add():
    js = (WEB / "js" / "tasks.js").read_text(encoding="utf-8")
    assert "border: 1px solid var(--border-subtle); border-radius: 12px;" in js        # карточка: рамка 1 px, радиус 12
    assert ".tsk-c.t-over { border-color: var(--tq-red); }" in js                     # просроченные — заметно
    assert "font-size: calc(15px * var(--fz, 1)); font-weight: 600;" in js            # заголовок 15/600
    assert 'const tone = (t) => (t.status === "done" ? "g" : t.overdue ? "over"' in js
    assert 'data-done="${esc(t.id)}"' in js and 'data-more="${esc(t.id)}"' in js       # «Готово» и ⋯
    assert "из чата «${esc(ch)}»" in js and 'class="tsk-chat" data-chat=' in js
    assert '<form class="tsk-add"' in js and 'id="tskDue" type="date"' in js           # одна строка + срок по желанию
    assert not [c for c in js if ord(c) >= 0x1F300]                                    # без эмодзи
