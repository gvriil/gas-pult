"""«Проекты» (задача 49, этап 2, docs/PROJECTS.md): данные и API. Без живого tmux и Claude: окна подменены,
домашняя папка и журналы Claude Code — во временной папке."""

import contextlib
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import modules, projects, transcripts, webapp, webauth
from gas_pult.config import Config


def jsonl(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}, "timestamp": "2026-11-07T10:00:00Z"}


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    for d in ("projects/shop", "projects/books", "projects/agent", "worktrees/shop-fix", "worktrees/lonely",
              "other/tool"):
        (h / d).mkdir(parents=True)
    (h / "projects/shop/.git").mkdir()
    (h / "worktrees/shop-fix/.git").write_text(f"gitdir: {h}/projects/shop/.git/worktrees/shop-fix\n")
    (h / "worktrees/lonely/.git").write_text(f"gitdir: {h}/gone/.git/worktrees/lonely\n")
    (h / "projects/agent" / modules.MARK).write_text(json.dumps({"id": "uk-start", "title": "УК-старт"}))
    return h


def folders(h):
    return [str(h), *sorted(str(p) for root in ("projects", "worktrees") for p in (h / root).iterdir())]


def test_migration_idempotent_and_nothing_moves(home, tmp_path):
    st = projects.Store(tmp_path / "data" / "projects.json", str(home))
    before = sorted(str(p) for p in home.rglob("*"))
    win = [{"id": "@1", "cmd": "claude", "mark": "claude", "path": str(home / "other/tool")},
           {"id": "@2", "cmd": "claude", "path": str(home / "projects/shop/src")},
           {"id": "@3", "cmd": "bash", "mark": "", "path": str(home / "other")},          # не сессия — не проект
           {"id": "t:x:@1", "cmd": "claude", "mark": "claude", "path": "/srv/x", "space": "x"}]
    (home / "projects/shop/src").mkdir()
    d = st.sync(folders(home), win, {str(home / "projects/books"): ["/r/a", "/r/a"]})
    assert oct(os.stat(st.file).st_mode & 0o777) == "0o600"
    ps = d["projects"]
    by_path = {p["path"]: p for p in ps.values()}
    assert set(by_path) == {"~", "~/projects/shop", "~/projects/books", "~/projects/agent", "~/worktrees/lonely",
                            "~/other/tool"}                                   # worktree shop-fix — не отдельный
    assert by_path["~"]["name"] == "Домашняя"
    assert by_path["~/projects/shop"]["paths"] == ["~/worktrees/shop-fix"]      # доп. папка основного репозитория
    assert by_path["~/projects/agent"]["origin"] == "module:uk-start" and by_path["~/projects/agent"]["name"] == \
        "УК-старт"
    assert by_path["~/projects/books"]["repos"] == ["/r/a"]                     # add_dirs (#123) → repos проекта
    assert all(p["id"] == projects.pid_of(os.path.realpath(projects.untilde(p["path"], str(home))))
               for p in ps.values())
    assert str(home) not in st.file.read_text()                                  # без личных путей — только ~
    # повтор — те же данные, файл не переписан; правки человека не затираются
    d["projects"][by_path["~/projects/shop"]["id"]]["name"] = "Магазин"
    st.write(d)
    mtime = st.file.stat().st_mtime_ns
    d2 = st.sync(folders(home), win, {str(home / "projects/books"): ["/r/a"]})
    assert d2 == d and st.file.stat().st_mtime_ns == mtime
    assert sorted(str(p) for p in home.rglob("*")) == sorted([*before, str(home / "projects/shop/src")])  # на месте
    # окно → проект: самое длинное совпадение; домашняя — только точно
    shop = by_path["~/projects/shop"]["id"]
    assert st.of_path(d2, str(home / "projects/shop/src")) == shop
    assert st.of_path(d2, str(home / "worktrees/shop-fix")) == shop
    assert st.of_path(d2, str(home)) == by_path["~"]["id"]
    assert st.of_path(d2, str(home / "elsewhere")) is None
    # откат: удалить файл — пульт строит заново те же id
    st.file.unlink()
    assert set(st.sync(folders(home), win)["projects"]) == set(ps)


def test_worktree_before_main_stays_own(home, tmp_path):
    st = projects.Store(tmp_path / "p.json", str(home))
    d = st.sync([str(home / "worktrees/shop-fix")], [])              # основного ещё нет среди папок
    wid = projects.pid_of(os.path.realpath(home / "worktrees/shop-fix"))
    assert set(d["projects"]) == {wid}
    d = st.sync(folders(home), [])                                     # появился — отдельный проект не ломаем
    assert wid in d["projects"] and d["projects"][projects.pid_of(str(home / "projects/shop"))]["paths"] == []


def test_broken_file_is_rebuilt(home, tmp_path):
    f = tmp_path / "p.json"
    f.write_text("{oops")
    d = projects.Store(f, str(home)).sync([str(home)], [])
    assert len(d["projects"]) == 1 and json.loads(f.read_text())["v"] == projects.VERSION


def test_title_summary_then_first_prompt(tmp_path):
    f = tmp_path / "a.jsonl"
    jsonl(f, [{"type": "user", "isMeta": True, "message": {"content": "служебное"}},
              user("<command-name>/clear</command-name>"),
              user("Посчитай скидки на зиму для всех товаров магазина, кроме тех, что уже со скидкой больше 20 %"),
              {"type": "assistant", "message": {"content": [{"type": "text", "text": "ок"}]}}])
    t = projects.title_of(f)
    assert t.startswith("Посчитай скидки на зиму") and len(t) == projects.TITLE_MAX and t.endswith("…")
    jsonl(f, [{"type": "summary", "summary": "Скидки на зиму"}, user("привет")])
    assert projects.title_of(f) == "Скидки на зиму"
    assert projects.title_of(tmp_path / "нет.jsonl") == ""


def test_title_ai_title_last_wins_and_tail(tmp_path):
    """Название от Claude Code (``ai-title``) важнее первого сообщения и summary; берётся последнее — с конца файла,
    даже если начало журнала не влезает в чтение головы."""
    f = tmp_path / "b.jsonl"
    filler = [{"type": "assistant", "message": {"content": [{"type": "text", "text": "x" * 1000}]}}] * 400
    jsonl(f, [user("Да"), {"type": "ai-title", "aiTitle": "Первое название"}, *filler,
              {"type": "ai-title", "aiTitle": "Keep  alive в tmux"}, {"type": "mode", "mode": "default"}])
    assert projects.title_of(f, head=4096) == "Keep alive в tmux"
    assert projects.tail_info(f, step=4096, limit=8192)["ai"] == "Keep alive в tmux"


def test_last_said_skips_service_records(tmp_path):
    f = tmp_path / "c.jsonl"
    jsonl(f, [{**user("вопрос"), "timestamp": "2026-11-08T16:00:00.000Z"},
              {"type": "assistant", "timestamp": "2026-11-08T16:00:30.000Z",
               "message": {"content": [{"type": "text", "text": "ответ"}]}},
              {"type": "assistant", "timestamp": "2026-11-09T15:00:00.000Z",
               "message": {"model": "<synthetic>", "content": [{"type": "text", "text": "No response requested."}]}},
              {**user("<task-notification>агент закончил</task-notification>"), "timestamp": "2026-11-09T16:00:00Z"},
              {"type": "user", "timestamp": "2026-11-09T16:01:00Z",
               "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
              {"type": "permission-mode", "timestamp": "2026-11-09T16:25:00Z"},
              {"type": "ai-title", "aiTitle": "Разбор"}])
    assert projects.last_said(f) == projects.epoch("2026-11-08T16:00:30Z")
    g = tmp_path / "d.jsonl"
    jsonl(g, [{"type": "mode"}])
    assert projects.last_said(g) == 0


def test_batch_runs_are_not_chats(tmp_path):
    base = tmp_path / ".claude"
    folder = str(tmp_path / "w")
    d = transcripts.project_dir(folder, base)
    d.mkdir(parents=True)
    jsonl(d / "a.jsonl", [{"type": "queue-operation", "operation": "enqueue", "content": "задача"},
                          {**user("задача"), "entrypoint": "sdk-cli"}])
    jsonl(d / "b.jsonl", [{**user("привет"), "entrypoint": "cli"}])
    jsonl(d / "c.jsonl", [{"type": "mode"}])                    # ещё пустой — пока не запуск
    assert [x.name for x in projects.session_files([folder], [base])] == ["b.jsonl", "c.jsonl"]


# ---------- API ----------
class Wins:
    session = "main"

    def __init__(self, wins):
        self.wins = wins

    def windows(self):
        return list(self.wins)

    def window(self, wid):
        return next((w for w in self.wins if w["id"] == wid), None)

    def screen(self, wid, n=25):
        return ["Do you want to proceed?", "❯ 1. Yes"] if wid == "@2" else ["esc to interrupt"]

    def run(self, *a, **k):
        return ""

    @contextlib.contextmanager
    def scope(self, slug):
        yield

    all_spaces = contextlib.nullcontext
    scoped = None


@pytest.fixture
def server(monkeypatch, home, tmp_path):
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(transcripts, "CLAUDE_PROJECTS", home / ".claude" / "projects")
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    p.people.add(2, "member", "Иван")
    p.people.add(3, "viewer", "Анна")
    for uid in (1, 2, 3):
        p.people.accept(uid)
        p.people.set_country(uid, chosen="NL")
    wins = Wins([{"id": "@1", "name": "shop-1", "cmd": "claude", "mark": "claude", "path": str(home / "projects/shop"),
                  "channel": False, "profile": "claude", "by": ""},
                 {"id": "@2", "name": "shop-2", "cmd": "claude", "mark": "claude",
                  "path": str(home / "worktrees/shop-fix"), "channel": False, "profile": "claude", "by": ""},
                 {"id": "t:demo:@1", "name": "сверка", "cmd": "claude", "mark": "claude", "path": "/srv/d",
                  "space": "demo", "channel": False, "profile": "claude", "by": ""}])
    monkeypatch.setattr(p, "tmux", wins)
    monkeypatch.setattr(p.pult, "tmux", wins)
    monkeypatch.setattr(p, "space_fields", lambda w: {"space": w["space"]} if w.get("space") else {})
    monkeypatch.setattr(webapp.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "main\n"})())
    shop = home / "projects/shop"
    (shop / "CLAUDE.md").write_text("Отвечай коротко. Цены — в рублях.\n")
    (shop / "files").mkdir()
    (shop / "files/прайс.csv").write_text("a;b\n")
    (shop / "files/.скрытый").write_text("x")
    jsonl(transcripts.project_dir(str(shop), None) / "s1.jsonl", [{"type": "summary", "summary": "Скидки на зиму"}])
    jsonl(transcripts.project_dir(str(home / "worktrees/shop-fix"), None) / "s2.jsonl", [user("Поправь кнопку")])
    jsonl(transcripts.project_dir(str(home / "projects/books"), p.cfg.data / "people/2/claude") / "s3.jsonl",
          [user("Книги участника")])
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield p, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def call(base, path, tok=""):
    req = urllib.request.Request(base + path, None, {"Cookie": f"{webauth.COOKIE}={tok}" if tok else ""})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_api_projects_and_sessions_field(server, home):
    p, base = server
    tok = p.auth.issue(1)
    code, d = call(base, "/api/projects", tok)
    assert code == 200
    shop = next(x for x in d["projects"] if x["path"] == "~/projects/shop")
    assert d["projects"][0]["id"] == shop["id"]                   # ждущий ответа — сверху
    assert (shop["windows"], shop["waiting"], shop["busy"], shop["chats"]) == (2, 1, 1, 2)
    assert shop["paths"] == ["~/worktrees/shop-fix"] and shop["folder"] == "shop" and shop["last"]
    assert set(shop["sessions"]) == {"@1", "@2"}
    books = next(x for x in d["projects"] if x["path"] == "~/projects/books")
    assert books["chats"] == 1 and books["last_title"] == "Книги участника"   # журналы участника — тоже
    assert str(home) not in json.dumps(d["projects"])
    ss = {x["id"]: x for x in call(base, "/api/sessions", tok)[1]["sessions"]}
    assert ss["@1"]["project"] == ss["@2"]["project"] == shop["id"]         # новое поле — добавлением
    assert ss["t:demo:@1"]["project"] == ""                                  # пространство — пока без проектов
    assert [x["name"] for x in call(base, "/api/projects?q=%D0%B4%D0%BE%D0%BC", tok)[1]["projects"]] == \
        ["Домашняя"]                                                         # поиск по имени («дом»)
    assert call(base, "/api/projects?q=shop-2", tok)[1]["projects"][0]["id"] == shop["id"]   # и по окну
    code, one = call(base, f"/api/project?id={shop['id']}", tok)
    assert code == 200 and one["instructions"].startswith("Отвечай коротко") and not one["instructions_cut"]
    assert [f["name"] for f in one["files"]] == ["прайс.csv"] and sorted(one["windows"]) == ["@1", "@2"]
    assert call(base, "/api/project?id=pnone", tok)[0] == 404


def test_api_projects_who(server):
    p, base = server
    for uid in (2, 3):                                              # участник и наблюдатель — как сейчас, все
        code, d = call(base, "/api/projects", p.auth.issue(uid))
        assert code == 200 and len(d["projects"]) >= 5
    assert call(base, "/api/projects")[0] == 401
    p.people.add(5, "member", "Тест")
    p.people.accept(5)
    p.people.set_country(5, chosen="NL")
    import gas_pult.people as people_mod
    orig = people_mod.People.tenant
    people_mod.People.tenant = lambda self, uid: "demo" if uid == 5 else orig(self, uid)
    try:
        assert call(base, "/api/projects", p.auth.issue(5))[1].get("code") == "space"   # тестировщик — позже
    finally:
        people_mod.People.tenant = orig
