"""Задачи владельца (#203): чек-лист «что решено, что нет» — с действием и привязкой к чату.

Владелец 14.11: «чтобы я понимал, какие задачи не решены и какие решены … сразу нажать, провалиться туда и
продолжить работу … это для меня супер важно, чтобы не теряться»."""

import json
import multiprocessing
import urllib.request

import pytest
from test_project_chats import call
from test_project_chats import server as server

from gas_pult import bot, cli, tasks, webapp, webauth
from gas_pult.config import Config


@pytest.fixture
def t(tmp_path):
    return tasks.Tasks(tmp_path / "tasks.json")


def test_add_check_order_and_done(t):
    a = t.add({"title": "Перезапустить панель", "kind": "command", "cmd": "systemctl --user restart x",
               "next": "нажать «Выполнить»"})
    b = t.add({"title": "Ответить Ивану", "kind": "write", "to": "@ivan", "draft": "Привет", "next": "отправить",
               "status": "waiting"})
    c = t.add({"title": "Сделано", "kind": "other", "status": "done"})
    assert [x["id"] for x in t.list()] == [b["id"], a["id"], c["id"]]        # ждут вас — первыми, выполненные — в конце
    assert t.open_count() == {"open": 2, "waiting": 1, "q1": 0}
    x = t.update(a["id"], {"status": "done"})
    assert x["done_at"] and t.open_count()["open"] == 1
    x = t.update(a["id"], {"status": "todo"})
    assert "done_at" not in x
    for bad in ({"kind": "other", "next": "x"}, {"title": "x"}, {"title": "x", "kind": "command", "next": "y"},
                {"title": "x", "kind": "decision", "question": "?", "options": ["один"], "next": "y"},
                {"title": "x", "kind": "звонок", "next": "y"}):
        with pytest.raises(ValueError):
            t.add(bad)
    assert t.remove(c["id"]) and not t.remove(c["id"])
    with pytest.raises(LookupError):
        t.update("нет", {"status": "done"})
    assert oct((t.path).stat().st_mode & 0o777) == "0o600"


def test_etag_changes_with_content(t):
    e0 = t.etag()
    t.add({"title": "a", "next": "b"})
    e1 = t.etag()
    assert e0 != e1 and e1 == t.etag()


def _add_many(path, n):
    x = tasks.Tasks(path)
    for i in range(n):
        x.add({"title": f"t{i}", "next": "n"})


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_concurrent_writers_do_not_lose_tasks(tmp_path):
    ctx = multiprocessing.get_context("fork")
    ps = [ctx.Process(target=_add_many, args=(tmp_path / "tasks.json", 20)) for _ in range(3)]
    for p in ps:
        p.start()
    for p in ps:
        p.join(30)
    assert len(tasks.Tasks(tmp_path / "tasks.json").list()) == 60


def test_cli_add_list_done(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "own_window", lambda: ("@4", "штаб"))
    monkeypatch.setattr(cli, "_sid_of", lambda wid: "11111111-1111-4111-8111-111111111111")
    cli.main(["task", "add", "--title", "Выбрать цену пилота", "--type", "decision", "--question", "Сколько?",
              "--option", "50 тыс.", "--option", "80 тыс.", "--next", "выбрать вариант", "--status", "waiting"])
    out = capsys.readouterr().out
    tid = out.split()[1].rstrip(":")
    x = tasks.Tasks(tmp_path / "tasks.json").get(tid)
    assert x["chat"] == "@4" and x["sid"].startswith("1111") and x["by"] == "агент · штаб"
    assert x["options"] == ["50 тыс.", "80 тыс."]
    cli.main(["task", "list"])
    assert "ждёт вас" in capsys.readouterr().out
    cli.main(["task", "done", tid])
    assert tasks.Tasks(tmp_path / "tasks.json").get(tid)["status"] == "done"
    with pytest.raises(SystemExit, match="не записал"):
        cli.main(["task", "add", "--title", "без дальше", "--chat", "none"])


def test_api_owner_only_etag_and_run(server, monkeypatch):
    p, base, *_ = server
    tok, member = p.auth.issue(1), p.auth.issue(2)
    code, x = call(base, "/api/tasks/add", {"title": "Посмотреть логи", "kind": "command", "cmd": "echo привет",
                                            "next": "выполнить", "chat": "@1"}, tok)
    assert code == 200 and x["id"]
    assert call(base, "/api/tasks", tok=member)[0] == 403                    # участнику — нет
    req = urllib.request.Request(base + "/api/tasks", headers={"Cookie": f"{webauth.COOKIE}={tok}"})
    with urllib.request.urlopen(req) as r:
        etag, d = r.headers["ETag"], json.loads(r.read())
    assert d["tasks"][0]["chat_now"] == "@1"                                 # окно задачи живо — куда «провалиться»
    req.add_header("If-None-Match", etag)
    try:
        urllib.request.urlopen(req)
        raise AssertionError("ждали 304")
    except urllib.error.HTTPError as e:
        assert e.code == 304
    code, d = call(base, "/api/sessions", tok=tok)
    assert d["tasks"] == {"open": 1, "waiting": 0, "q1": 0}
    monkeypatch.setattr(p.auth, "needs_confirm", lambda token, fresh=None: False)
    ran = []
    monkeypatch.setattr(webapp, "execute", lambda cmd, path: ran.append((cmd, path)) or (0, 0.1, "привет\n"))
    code, r = call(base, "/api/tasks/run", {"id": x["id"]}, tok)
    assert code == 200 and r["code"] == 0 and "привет" in r["out"]
    assert p.tasks.get(x["id"])["result"]["code"] == 0 and ran[0][0] == "echo привет"
    code, y = call(base, "/api/tasks/add", {"title": "Удалить", "kind": "command", "cmd": "rm -rf /tmp/x",
                                            "next": "x"}, tok)
    assert call(base, "/api/tasks/run", {"id": y["id"]}, tok)[1] == {"confirm": True}   # опасное — ещё раз
    code, z = call(base, "/api/tasks/update", {"id": x["id"], "status": "done"}, tok)
    assert z["status"] == "done"


def test_run_needs_confirm_code_for_fresh_session(server):
    p, base, *_ = server
    tok = p.auth.issue(1)
    _, x = call(base, "/api/tasks/add", {"title": "ls", "kind": "command", "cmd": "ls", "next": "x"}, tok)
    code, e = call(base, "/api/tasks/run", {"id": x["id"]}, tok)
    assert code == 403 and e.get("confirm") == "code"        # новый вход — сперва код, как у «Выполнить»


def test_bot_tasks(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    p = bot.Pult.__new__(bot.Pult)
    p.cfg = Config(token="t", owners=[1])
    p.tasks = tasks.Tasks(tmp_path / "tasks.json")
    p.tmux = type("T", (), {"window": lambda self, wid: {"id": wid} if wid == "@1" else None})()
    sent = []
    p.send = lambda chat, text, **kw: sent.append((text, kw))
    p.to = lambda chat: lambda text, **kw: sent.append((text, kw))
    p.api = lambda *a, **k: {}
    p.show_tasks(1)
    assert "Невыполненных задач нет" in sent[-1][0]
    x = p.tasks.add({"title": "Позвонить бухгалтеру", "kind": "call", "phone": "+7 900 000-00-00",
                     "next": "уточнить акт", "chat": "@1"})
    p.show_tasks(1)
    text, kw = sent[-1]
    assert "Позвонить бухгалтеру" in text and "+7 900" in text and "уточнить акт" in text
    assert "Не разобрано" in text                                            # бот — тоже по квадрантам
    assert f"tk:done:{x['id']}" in json.dumps(kw) and "act:@1" in json.dumps(kw)
    p.on_callback({"id": "c", "from": {"id": 1}, "message": {"chat": {"id": 1}}, "data": f"tk:done:{x['id']}"})
    assert p.tasks.get(x["id"])["status"] == "done" and "выполнено" in sent[-2][0]


def test_ui_static():
    from pathlib import Path
    web = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
    index = (web / "index.html").read_text(encoding="utf-8")
    part = (web / "js" / "tasks.js").read_text(encoding="utf-8")
    assert 'data-space="tasks"' in index and 'data-space="demo"' not in index      # «Демо и тесты» — не наверху
    assert "data-demo-here" in index and "return demoSheet();" in index            # а в «Подсказать»
    assert 'part("tasks").then(() => tasksOpen()' in index and '"/api/tasks/run"' in index
    assert "function taskSheet(t)" in part and "tasksOpen" not in index.split("function tasksCount")[0][-2000:]


def test_e2e_tasks_demo():
    import importlib.util
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from pathlib import Path

    pytest.importorskip("playwright.sync_api")
    web = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(web)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    e2e = Path(__file__).resolve().parent / "e2e" / "tasks_demo.py"
    spec = importlib.util.spec_from_file_location("tasks_demo", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo")
    finally:
        srv.shutdown()


def test_cli_update_chat_by_name_index_or_id(tmp_path, monkeypatch, capsys):
    """Штаб 14.11: «task update --chat @12» молча ничего не менял; люди называют окно номером или именем."""
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    wins = [{"id": "@14", "idx": "2", "name": "штаб", "sid": "22222222-2222-4222-8222-222222222222"},
            {"id": "@12", "idx": "13", "name": "gastech-site", "sid": "33333333-3333-4333-8333-333333333333"}]
    monkeypatch.setattr(cli, "_windows", lambda: [dict(w) for w in wins])
    monkeypatch.setattr(cli, "own_window", lambda: ("", ""))
    t = tasks.Tasks(tmp_path / "tasks.json")
    x = t.add({"title": "DNS гастех.рф", "next": "проверить", "chat": "@14"})
    for ref in ("gastech-site", "13", "@12"):
        cli.main(["task", "update", x["id"], "--chat", ref])
        y = t.get(x["id"])
        assert y["chat"] == "@12" and y["sid"].startswith("3333"), ref
        t.update(x["id"], {"chat": "@14"})
    with pytest.raises(SystemExit, match=r"не найдено.*13:gastech-site"):
        cli.main(["task", "update", x["id"], "--chat", "нет-такого"])
    with pytest.raises(SystemExit, match="нечего менять"):
        cli.main(["task", "update", x["id"]])
    cli.main(["task", "update", x["id"], "--chat", "none"])
    assert t.get(x["id"])["chat"] == ""
    cli.main(["task", "add", "--title", "сайт", "--next", "x", "--chat", "gastech-site"])
    capsys.readouterr()
    cli.main(["task", "list"])
    assert "чат 13:gastech-site" in capsys.readouterr().out                 # в списке — номер и имя окна


def test_eisenhower_quadrants(t):
    """Решение владельца 14.11: «по срочности и важности» — квадранты 1–4; 1 сверху, не разобрано — после него."""
    q = {n: t.add({"title": f"q{n}", "next": "x", **({"q": n} if n else {})}) for n in (4, 3, 2, 1, 0)}
    assert [x["title"] for x in t.list()] == ["q1", "q0", "q2", "q3", "q4"]
    assert [x["q"] for x in t.list()] == [1, 0, 2, 3, 4]
    assert q[3]["urgent"] is True and q[3]["important"] is False
    assert t.open_count()["q1"] == 1
    late = t.add({"title": "просрочено", "next": "x", "important": "да", "urgent": "нет", "due": "2020-01-01"})
    x = next(x for x in t.list() if x["id"] == late["id"])
    assert x["q"] == 1 and x["overdue"] is True                                  # срок прошёл → срочно
    assert t.update(late["id"], {"status": "done"}) and t.open_count()["q1"] == 1  # выполненное — не просрочено
    t.update(q[0]["id"], {"urgent": "no", "important": "yes"})
    assert next(x for x in t.list() if x["id"] == q[0]["id"])["q"] == 2
    for bad in ({"q": 5}, {"urgent": "может"}, {"due": "завтра"}):
        with pytest.raises(ValueError):
            t.add({"title": "x", "next": "y", **bad})


def test_cli_quadrants(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "_windows", lambda: [])
    monkeypatch.setattr(cli, "own_window", lambda: ("", ""))
    cli.main(["task", "add", "--title", "Ключ гипервизора", "--next", "сменить",
              "--urgent", "yes", "--important", "yes"])
    cli.main(["task", "add", "--title", "Digest", "--next", "потом", "--q", "4"])
    cli.main(["task", "add", "--title", "Без оценки", "--next", "x"])
    t = tasks.Tasks(tmp_path / "tasks.json")
    d = next(x for x in t.list() if x["title"] == "Digest")
    cli.main(["task", "update", d["id"], "--q", "2", "--due", "2099-01-01"])
    assert next(x for x in t.list() if x["id"] == d["id"])["q"] == 2
    capsys.readouterr()
    cli.main(["task", "list"])
    out = capsys.readouterr().out
    assert out.index("== Q1 · Срочно и важно") < out.index("== Не разобрано") < out.index("== Q2 · Важно")
    assert "срок 2099-01-01" in out
