"""Модули-агенты: формат module.toml, общие блоки, создание пространства, расписание, панель и /modules в боте."""

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import bot, modules, webapp, webauth
from gas_pult.config import Config

BUILTIN = ("night-shift", "morning-numbers", "client-alerts")


@pytest.fixture(autouse=True)
def own_config(monkeypatch, tmp_path):
    """Свои модули владельца — во временной папке, не в ~/.config."""
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))


def write_module(base: Path, mid: str, toml: str, claude: str = "# Роль\n") -> Path:
    d = base / mid
    d.mkdir(parents=True)
    (d / "module.toml").write_text(toml, encoding="utf-8")
    (d / "CLAUDE.md").write_text(claude, encoding="utf-8")
    return d


GOOD = 'title = "Тест"\nindustry = "Пробная"\nabout = "для проверки"\n'


def test_builtin_modules_parse():
    errors = []
    by = {m["id"]: m for m in modules.catalog(errors)}
    assert errors == [] and set(BUILTIN) <= set(by)
    ns = by["night-shift"]
    assert ns["settings"]["iterations"] == 20 and len(ns["decisions"]) == 3
    assert all(d["options"] == ["Да", "Нет"] for d in ns["decisions"])
    assert {"night-review", "night-report"} <= set(ns["skills"]) and "20 итераций" in ns["description"]
    mn = by["morning-numbers"]
    assert mn["schedule"][0]["at"] == "08:00" and mn["schedule"][0]["days"] == [1, 2, 3, 4, 5, 6, 7]
    assert {s["kind"] for s in mn["data_sources"]} == {"official_api", "client_export"}
    assert {x["kind"] for x in mn["integrations"]} == {"connector", "manual"}
    ca = by["client-alerts"]
    assert [u["id"] for u in ca["uses"]] == ["reminders"] and "reminder-batch" in ca["skills"]
    assert ca["decisions"][0]["options"] == ["Да", "Нет"] and ca["schedule"][0]["days"] == [1, 2, 3, 4, 5]
    assert not any(m["id"].startswith("_") for m in by.values())          # общие блоки — не модули
    assert set(modules.blocks()) == {"reminders", "reviews", "receivables", "documents"}
    for m in by.values():                                                  # в публичном виде нет путей на диске
        assert "path" not in modules.public(m)


def test_broken_toml_and_missing_fields(tmp_path):
    base = tmp_path / "cfg" / "modules"
    write_module(base, "bad-toml", "title = \n")
    write_module(base, "no-title", 'industry = "x"\nabout = "y"\n')
    write_module(base, "bad-time", GOOD + '[[schedule]]\nat = "8:00"\nprompt = "p"\n')
    write_module(base, "bad-use", GOOD + 'uses = ["nope"]\n')
    write_module(base, "bad-source", GOOD + '[[data_sources]]\ntitle = "сайт"\nkind = "scraping"\n')
    write_module(base, "bad-decision", GOOD + '[[decisions]]\nquestion = "?"\noptions = ["Да"]\n')
    errors = []
    ids = {m["id"] for m in modules.catalog(errors)}
    assert not ids & {"bad-toml", "no-title", "bad-time", "bad-use", "bad-source", "bad-decision"}
    text = "\n".join(errors)
    assert "bad-toml: ошибка в module.toml" in text and "поле «title» — обязательная строка" in text
    assert "ЧЧ:ММ" in text and "нет такого общего блока «nope»" in text
    assert "official_api" in text and "от 2 до 4" in text
    with pytest.raises(modules.ModuleError, match=r"нет CLAUDE\.md"):
        (base / "bad-toml" / "CLAUDE.md").unlink()
        (base / "bad-toml" / "module.toml").write_text(GOOD)
        modules.parse(base / "bad-toml")


def test_own_module_one_folder_with_common_block(tmp_path):
    base = tmp_path / "cfg" / "modules"
    d = write_module(base, "shop", GOOD + 'uses = ["reviews"]\n[settings]\nlimit = 7\n'
                     '[[data_sources]]\ntitle = "Заказы"\nkind = "official_api"\n',
                     "# Магазин\nЛимит {{limit}}.\n")
    (d / "skills" / "orders").mkdir(parents=True)
    (d / "skills" / "orders" / "SKILL.md").write_text("---\nname: orders\ndescription: x\n---\n")
    m = modules.get("shop")                                   # модуль одной папкой — без правки кода
    assert m["skills"] == ["orders", "review-reply"]
    root = tmp_path / "projects"
    p = modules.create("shop", root)
    text = (p / "CLAUDE.md").read_text()
    assert "Лимит 7." in text and "## Общий блок: Отзывы и NPS" in text and "Заказы — официальный API" in text
    assert (p / ".claude" / "skills" / "orders" / "SKILL.md").is_file()
    assert (p / ".claude" / "skills" / "review-reply" / "SKILL.md").is_file()


def test_create_workspace(tmp_path):
    root = tmp_path / "projects"
    p = modules.create("night-shift", root, by=5)
    assert p == root / "night-shift"
    assert "Лимит итераций: 20" in (p / "CLAUDE.md").read_text() and "{{" not in (p / "CLAUDE.md").read_text()
    assert (p / "PLAN.md").is_file() and not (p / "module.toml").exists()
    assert (p / ".claude" / "skills" / "night-review" / "SKILL.md").is_file()
    assert json.loads((p / ".claude" / "settings.json").read_text())["permissions"]["ask"]
    mark = modules.mark_of(p)
    assert mark["id"] == "night-shift" and mark["version"] == "1.0" and mark["by"] == 5
    q = modules.create("morning-numbers", root)
    assert (q / "data" / "plan.csv").is_file() and (q / "data" / "fact.csv").is_file()
    assert modules.free_name(root, "night-shift") == "night-shift-2"
    assert [f.name for f, _ in modules.workspaces([root])] == ["morning-numbers", "night-shift"]


def test_create_refuses_taken_and_bad_names(tmp_path):
    root = tmp_path / "projects"
    (root / "mine").mkdir(parents=True)
    (root / "mine" / "keep.txt").write_text("моё")
    with pytest.raises(modules.ModuleError, match="уже есть"):
        modules.create("night-shift", root, "mine")
    assert sorted(x.name for x in (root / "mine").iterdir()) == ["keep.txt"]       # ничего не тронуто
    for bad in ("..", "../evil", "a/b", "/tmp/x", "Имя", "x"):
        with pytest.raises(modules.ModuleError, match="имя папки"):
            modules.create("night-shift", root, bad)
    assert not (tmp_path / "evil").exists()
    with pytest.raises(LookupError):
        modules.create("no-such-module", root)


def test_schedule_due_once_and_not_for_new_workspace(tmp_path):
    root = tmp_path / "projects"
    p = modules.create("morning-numbers", root)
    mark = json.loads((p / modules.MARK).read_text())
    mark["created"] = int(datetime(2026, 11, 1, 12, 0).timestamp())
    (p / modules.MARK).write_text(json.dumps(mark))
    sch = modules.Schedule(tmp_path / "modules.json")
    assert sch.due([root], datetime(2026, 11, 2, 7, 59)) == []
    due = sch.due([root], datetime(2026, 11, 2, 8, 0))
    assert [(f.name, item["at"]) for f, _, item in due] == [("morning-numbers", "08:00")]
    assert "утренние цифры" in due[0][2]["prompt"] and "{{" not in due[0][2]["prompt"]
    assert sch.due([root], datetime(2026, 11, 2, 9, 0)) == []                    # сегодня уже было
    assert sch.due([root], datetime(2026, 11, 3, 12, 30)) == []                  # пульт спал дольше 3 ч — не догоняем
    q = modules.create("client-alerts", root)                                   # создано сейчас — сегодня не шлём
    assert all(f != q for f, _, _ in sch.due([root], datetime.now().replace(hour=23, minute=59)))


# ---------- панель ----------
@pytest.fixture
def panel(monkeypatch, tmp_path):
    p = webapp.Panel(Config(token="1:T", owners=[1], project_roots=[str(tmp_path / "projects")]))
    p.people.add(2, "member")
    p.people.add(3, "viewer")
    for uid in (1, 2, 3):
        p.people.accept(uid)
        p.people.set_country(uid, chosen="NL")
    monkeypatch.setattr(webapp.setup, "installed", lambda claude="claude": "/usr/bin/claude")   # в CI Claude Code нет
    opened, later = [], []
    monkeypatch.setattr(p.pult, "project_window", lambda path: None)
    monkeypatch.setattr(p.tmux, "new_window", lambda name, path, cmd, **kw: opened.append((name, path, kw)) or "@9")
    monkeypatch.setattr(p.tmux, "run", lambda *a, **kw: "")
    monkeypatch.setattr(p.pult, "send_later", lambda wid, text: later.append((wid, text)))
    p.opened, p.later = opened, later
    return p


def call(base, path, body=None, token=""):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={token}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


@pytest.fixture
def server(panel):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield panel, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_panel_modules_api(server, tmp_path):
    panel, base = server
    owner, member, viewer = (panel.auth.issue(u) for u in (1, 2, 3))
    code, d = call(base, "/api/modules", None, viewer)                       # смотреть может и наблюдатель
    assert code == 200 and set(BUILTIN) <= {m["id"] for m in d["modules"]} and d["root"] == "projects"
    night = next(m for m in d["modules"] if m["id"] == "night-shift")
    assert night["folder"] == "night-shift" and "path" not in night
    assert call(base, "/api/modules/create", {"id": "night-shift"}, viewer)[0] == 403   # создавать — нет
    code, d = call(base, "/api/modules/create", {"id": "night-shift"}, owner)
    assert code == 200 and d == {"id": "@9", "path": "night-shift", "folder": "night-shift"}
    assert panel.opened[-1][1] == str(tmp_path / "projects" / "night-shift")
    assert panel.later[-1][0] == "@9" and "PLAN.md" in panel.later[-1][1]       # первое задание модуля
    code, d = call(base, "/api/modules/create", {"id": "night-shift", "name": "night-shift"}, member)
    assert code == 400 and "уже есть" in d["error"]
    code, d = call(base, "/api/modules/create", {"id": "night-shift", "name": "../x"}, member)
    assert code == 400 and "имя папки" in d["error"]
    code, d = call(base, "/api/modules/create", {"id": "client-alerts", "name": "alerts"}, member)
    assert code == 200 and d["folder"] == "alerts"
    assert panel.opened[-1][2]["by"] == "2"                                    # окно участника — его папкой Claude
    assert modules.mark_of(tmp_path / "projects" / "alerts")["by"] == 2
    assert call(base, "/api/modules", None, owner)[1]["modules"][0]["folder"] != ""


def test_panel_create_checks_before_folder(panel, monkeypatch, tmp_path):
    monkeypatch.setattr(webapp.setup, "installed", lambda claude="claude": None)
    with pytest.raises(ValueError, match="не установлен"):
        panel.module_create("night-shift", "", uid=1)
    assert not (tmp_path / "projects" / "night-shift").exists()               # пустых папок не оставляем


# ---------- бот ----------
@pytest.fixture
def pult(tmp_path, monkeypatch):
    p = bot.Pult(Config(token="1:T", owners=[1], project_roots=[str(tmp_path / "projects")]))
    p.sent, p.opened, p.later = [], [], []
    p.send = lambda chat, text, **kw: p.sent.append((text, kw))
    p.broadcast = lambda text, **kw: p.sent.append((text, kw))
    p.api = lambda method, **kw: {}
    p.open_session = lambda chat, name, path, first=None: p.opened.append((name, path))
    p.project_window = lambda path: {"id": "@5", "path": path} if p.opened else None
    p.send_later = lambda wid, text: p.later.append((wid, text))
    monkeypatch.setattr(bot.setup, "installed", lambda claude="claude": "/usr/bin/claude")
    return p


def buttons(kw) -> list[str]:
    return [b["callback_data"] for row in kw["reply_markup"]["inline_keyboard"] for b in row]


def cb(p, data):
    p.on_callback({"id": "q", "from": {"id": 1}, "message": {"chat": {"id": 1}, "message_id": 3}, "data": data})


def test_bot_modules_list_view_create(pult, tmp_path):
    p = pult
    p.on_message({"chat": {"id": 1}, "from": {"id": 1}, "text": "/modules"})
    text, kw = p.sent[-1]
    assert "Ночная смена" in text and "md:v:night-shift" in buttons(kw)
    cb(p, "md:v:morning-numbers")
    text, kw = p.sent[-1]
    assert "08:00 каждый день" in text and "Google Таблицы" in text and "md:new:morning-numbers" in buttons(kw)
    assert "Создать «morning-numbers»" in json.dumps(kw, ensure_ascii=False)
    cb(p, "md:new:morning-numbers")
    folder = tmp_path / "projects" / "morning-numbers"
    assert (folder / "data" / "fact.csv").is_file() and p.opened[-1][1] == str(folder)
    assert p.later[-1][0] == "@5" and "откуда брать цифры" in p.later[-1][1]
    cb(p, "md:v:morning-numbers")
    assert "Создать «morning-numbers-2»" in json.dumps(p.sent[-1][1], ensure_ascii=False)   # имя занято — суффикс
    cb(p, "md:name:night-shift")
    p.on_message({"chat": {"id": 1}, "from": {"id": 1}, "text": "../evil"})
    assert "имя папки" in p.sent[-1][0] and not (tmp_path / "evil").exists()
    cb(p, "md:name:night-shift")
    p.on_message({"chat": {"id": 1}, "from": {"id": 1}, "text": "Nightly"})
    assert (tmp_path / "projects" / "nightly" / "PLAN.md").is_file()


def test_bot_new_menu_has_modules(pult):
    p = pult
    p.projects = lambda: []
    p.on_message({"chat": {"id": 1}, "from": {"id": 1}, "text": "🆕 Новая"})
    assert "md:list:" in buttons(p.sent[-1][1])


def test_bot_schedule_sends_prompt_or_opens_window(pult, tmp_path, monkeypatch):
    p = pult
    root = tmp_path / "projects"
    folder = modules.create("morning-numbers", root)
    mark = json.loads((folder / modules.MARK).read_text())
    mark["created"] = 0
    (folder / modules.MARK).write_text(json.dumps(mark))
    pasted, opened = [], []
    p.to_claude = lambda w, text: pasted.append((w["id"], text))
    p.project_window = lambda path: {"id": "@7"}
    p.module_tick(datetime(2026, 11, 2, 8, 1))
    assert pasted and pasted[0][0] == "@7" and "утренние цифры" in pasted[0][1]
    p.module_tick(datetime(2026, 11, 2, 8, 2))
    assert len(pasted) == 1                                                    # раз в день
    p.project_window = lambda path: None                                       # окна нет — открываем
    p.people.set_country(1, chosen="NL")
    monkeypatch.setattr(p.tmux, "new_window", lambda name, path, cmd, **kw: opened.append((name, path)) or "@8")
    monkeypatch.setattr(p.tmux, "run", lambda *a, **kw: "")
    p.module_tick(datetime(2026, 11, 3, 8, 0))
    assert opened == [("morning-numbers-0800", str(folder))] and p.later[-1][0] == "@8"
    assert "открыл сессию по расписанию" in p.sent[-1][0]
