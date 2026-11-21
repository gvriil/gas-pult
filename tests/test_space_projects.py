"""«Проекты» в демо-пространстве (GAS-38 п.1): у тестировщика тот же экран, что у владельца — проекты (папки
``home/projects/<имя>``), чаты проекта, переписка завершённого, «Новый чат в проекте», «Продолжить», «Новый проект».

Изоляция: тестировщик пространства demo не видит проекты, чаты и переписку пространства other и проекты владельца;
id с «..», абсолютным путём, чужим пространством — 404; журнал-ссылка наружу не читается; наблюдатель чат не создаёт.

Настоящие серверы tmux по коротким сокетам (как tests/test_tenant_testers.py): пространства без sudo —
``tenants.tmux_of`` подменён на tmux по сокету, команда запуска — поддельный «claude».
"""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import space_projects, spaces, tenants, transcripts, webapp, webauth
from gas_pult.config import Config
from gas_pult.tmux import Tmux

pytestmark = pytest.mark.skipif(not shutil.which("tmux"), reason="нужен tmux")
OWNER, TESTER, OTHER_T, MEMBER, VIEWER = 7201, 7202, 7203, 7204, 7205
OLD, FOREIGN, OWN_SID, LINK = (str(uuid.UUID(int=i)) for i in (21, 22, 23, 24))
SV, REP = "Сверка счетов", "Отчёт"


def wait(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


def journal(home, folder: str, sid: str, text: str):
    d = transcripts.project_dir(str(folder), home)
    d.mkdir(parents=True, exist_ok=True)
    rows = [{"type": "user", "message": {"role": "user", "content": text}, "timestamp": "2026-11-20T10:00:00Z"},
            {"type": "assistant", "message": {"stop_reason": "end_turn", "content": [{"type": "text",
                                                                                     "text": "Готово: " + text}]},
             "timestamp": "2026-11-20T10:00:05Z"}]
    f = d / f"{sid}.jsonl"
    f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return f


@pytest.fixture
def world(tmp_path, monkeypatch):
    d = tempfile.mkdtemp(prefix="gp-", dir="/tmp")
    socks = {k: os.path.join(d, k[:2]) for k in ("owner", "demo", "other")}
    monkeypatch.setenv("GAS_PULT_TMUX_SOCKET", socks["owner"])
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    root = tmp_path / "tenants"
    monkeypatch.setenv("GAS_PULT_TENANTS_ROOT", str(root))
    root.mkdir()
    (root / tenants.MARKER).write_text("{}")
    for slug, title in (("demo", "Демо для кафе"), ("other", "Чужое")):
        (root / slug / "home" / "projects").mkdir(parents=True)
        (root / slug / "config/claude/projects").mkdir(parents=True)
        (root / slug / tenants.META).write_text(json.dumps({"title": title, "persona": "point_admin"}))
    fake = tmp_path / "bin" / "claude"
    fake.parent.mkdir()
    fake.write_text("#!/usr/bin/env bash\nwhile true; do printf '❯ '; read -r line; echo \"got: $line\"; done\n")
    fake.chmod(0o755)
    monkeypatch.setattr(tenants, "tmux_of", lambda slug, session="main", base_root=None:
                        Tmux("main", socket=socks[slug], home=str(root / slug / "home")))
    monkeypatch.setattr(tenants, "ready", lambda slug, base_root=None, runner=None, now=None: True)
    monkeypatch.setattr(tenants, "command", lambda t, base="claude", base_root=None: str(fake))
    monkeypatch.setattr(webapp.Panel, "space_claude_check", lambda self, slug, raw, wait=2.0: None)
    space_projects._cache.clear()
    # проекты: у demo — две папки и журнал завершённого чата; у other — своя папка и журнал; у владельца — своя
    demo_home, other_home = root / "demo/config/claude", root / "other/config/claude"
    for slug, name in (("demo", SV), ("demo", REP), ("other", "Секрет")):
        (root / slug / "home/projects" / name).mkdir()
    journal(demo_home, root / "demo/home/projects" / SV, OLD, "Сверь счета за октябрь")
    journal(other_home, root / "other/home/projects/Секрет", FOREIGN, "Чужая тайна other")
    (tmp_path / "projects" / "secret").mkdir(parents=True)
    owner_f = journal(tmp_path / "ownclaude", tmp_path / "projects" / "secret", OWN_SID,
                      "Тайна владельца")
    p = webapp.Panel(Config(token="1:T", owners=[OWNER], region="NL", claude=str(fake), session="test",
                            project_roots=[str(tmp_path / "projects")]))
    p.people.add(TESTER, "member", "Тестировщик", tenant="demo")
    p.people.add(OTHER_T, "member", "Чужой", tenant="other")
    p.people.add(MEMBER, "member", "Сотрудник")
    p.people.add(VIEWER, "viewer", "Наблюдатель", tenant="demo")
    for uid in (OWNER, TESTER, OTHER_T, MEMBER, VIEWER):
        p.people.accept(uid)
        p.people.set_country(uid, chosen="NL")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield {"p": p, "base": base, "root": root, "socks": socks, "owner_f": owner_f,
           "tok": {u: p.auth.issue(u) for u in (OWNER, TESTER, OTHER_T, MEMBER, VIEWER)}}
    srv.shutdown()
    for s in socks.values():
        subprocess.run(["tmux", "-S", s, "kill-server"], capture_output=True)
    shutil.rmtree(d, ignore_errors=True)
    space_projects._cache.clear()


def call(w, path, body=None, who=TESTER):
    req = urllib.request.Request(w["base"] + path, json.dumps(body).encode() if body is not None else None,
                                 {"Cookie": f"{webauth.COOKIE}={w['tok'][who]}"})
    try:
        r = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        r = e
    raw = r.read()
    code = r.status if hasattr(r, "status") else r.code
    try:
        return code, json.loads(raw or b"{}")
    except ValueError:
        return code, {"raw": len(raw)}


def q(s):
    return urllib.parse.quote(s, safe="")


def pid(slug, folder):
    return space_projects.pid_of(slug, folder)


def space_windows(slug):
    return [w for w in tenants.tmux_of(slug).windows() if w["cmd"] == "claude" or w.get("mark")]


def test_tester_sees_projects_of_own_space(world):
    w = world
    assert call(w, "/api/meta")[1]["projects_ui"] is True          # «Проекты» включены и у тестировщика
    code, d = call(w, "/api/projects")
    assert code == 200, d
    ids = {x["id"] for x in d["projects"]}
    assert ids == {pid("demo", SV), pid("demo", REP)}               # ни other, ни проектов владельца
    sv = next(x for x in d["projects"] if x["id"] == pid("demo", SV))
    assert sv["chats"] == 1 and sv["last_title"] and sv["path"] == "projects/" + SV
    assert str(w["root"]) not in json.dumps(d, ensure_ascii=False)  # путей сервера в ответе нет
    assert d["host"] == "Демо для кафе" and "space_projects" not in d


def test_tester_chats_history_new_and_resume(world):
    w = world
    code, d = call(w, f"/api/project?id={q(pid('demo', SV))}")
    assert code == 200 and d["name"] == SV and d["chats"] == 1, d
    code, d = call(w, f"/api/project/sessions?id={q(pid('demo', SV))}")
    assert code == 200 and [c["sid"] for c in d["chats"]] == [OLD], d
    code, d = call(w, f"/api/project/history?id={q(pid('demo', SV))}&sid={OLD}")
    assert code == 200 and any("октябрь" in it["text"] for it in d["items"]), d
    # «Новый чат в проекте» — окно пространства demo именно в этой папке, со своим id разговора
    code, d = call(w, "/api/project/session", {"id": pid("demo", SV)})
    assert code == 200 and d["id"].startswith("t:demo:@") and d["project"] == pid("demo", SV), d
    raw = spaces.split(d["id"])[1]
    win = next(x for x in tenants.tmux_of("demo").windows() if x["id"] == raw)
    assert win["path"] == str(w["root"] / "demo/home/projects" / SV) and win["sid"] == d["sid"]
    assert not space_windows("other")
    assert wait(lambda: any(s["id"] == d["id"] and s["project"] == pid("demo", SV)
                            for s in call(w, "/api/projects")[1]["sessions"]))
    # «Продолжить» завершённый — окно с --resume и меткой этого разговора; повтор — то же окно
    code, r = call(w, "/api/project/resume", {"id": pid("demo", SV), "sid": OLD})
    assert code == 200 and r["sid"] == OLD, r
    raw = spaces.split(r["id"])[1]
    assert next(x for x in tenants.tmux_of("demo").windows() if x["id"] == raw)["sid"] == OLD
    code, r2 = call(w, "/api/project/resume", {"id": pid("demo", SV), "sid": OLD})
    assert code == 200 and r2["id"] == r["id"] and r2["existing"], r2
    # завершённых больше нет: OLD открыт
    assert call(w, f"/api/project/sessions?id={q(pid('demo', SV))}")[1]["chats"] == []


def test_tester_new_project(world):
    w = world
    code, d = call(w, "/api/project/new", {"name": "Меню на зиму", "instructions": "Отвечай коротко; 'кавычки' $x"})
    assert code == 200 and d["id"] == pid("demo", "Меню на зиму"), d
    f = w["root"] / "demo/home/projects/Меню на зиму/CLAUDE.md"
    assert f.read_text(encoding="utf-8") == "Отвечай коротко; 'кавычки' $x\n"
    assert pid("demo", "Меню на зиму") in {x["id"] for x in call(w, "/api/projects")[1]["projects"]}
    assert "кавычки" in call(w, f"/api/project?id={q(d['id'])}")[1]["instructions"]
    assert not space_windows("demo")                                # окно — только при первой отправке
    assert not (w["root"] / "other/home/projects/Меню на зиму").exists()


BAD_IDS = [pid("other", "Секрет"), "s:other:Секрет", "s:demo:..", "s:demo:../../other/home/projects/Секрет",
           "s:demo:/etc", "s:demo:", "s:demo", "s:Demo:" + SV, "s:../other:Секрет", "/etc/passwd", "~/projects/secret",
           "s:demo:.hidden", "s:demo:" + SV + "/..", "s:demo:Нет такой"]


@pytest.mark.parametrize("bad", BAD_IDS)
def test_tester_cannot_reach_foreign_or_bad_ids(world, bad):
    w = world
    for path in (f"/api/project?id={q(bad)}", f"/api/project/sessions?id={q(bad)}",
                 f"/api/project/history?id={q(bad)}&sid={FOREIGN}", f"/api/project/history?id={q(bad)}&sid={OWN_SID}"):
        code, d = call(w, path)
        assert code in (403, 404), (path, code, d)
        assert "тайна" not in json.dumps(d, ensure_ascii=False).lower()
    for path, body in (("/api/project/session", {"id": bad}), ("/api/project/resume", {"id": bad, "sid": FOREIGN})):
        code, d = call(w, path, body)
        assert code in (403, 404), (path, code, d)
    assert not space_windows("other") and not space_windows("demo")


def test_tester_cannot_reach_owner_projects(world):
    w = world
    owner_ids = [x["id"] for x in call(w, "/api/projects", who=OWNER)[1]["projects"]]
    assert owner_ids                                                # у владельца проект «secret» есть
    for oid in owner_ids:
        for path in (f"/api/project?id={q(oid)}", f"/api/project/sessions?id={q(oid)}",
                     f"/api/project/history?id={q(oid)}&sid={OWN_SID}"):
            code, d = call(w, path)
            assert code in (403, 404) and "Тайна" not in json.dumps(d, ensure_ascii=False), (path, code, d)
        assert call(w, "/api/project/session", {"id": oid})[0] in (403, 404)
        assert call(w, "/api/project/resume", {"id": oid, "sid": OWN_SID})[0] in (403, 404)
    for path, body in (("/api/project/update", {"id": owner_ids[0], "name": "взлом"}), ("/api/pin", {"project": "x"}),
                       ("/api/project/chat", {"id": owner_ids[0], "sid": OWN_SID, "hidden": True})):
        assert call(w, path, body)[0] == 403, path                 # меню проекта и закрепления — не в пространстве


@pytest.mark.parametrize("sid", ["../" + FOREIGN, FOREIGN, OWN_SID, "/etc/passwd", "*", OLD.upper() + "x"])
def test_bad_sid_in_own_project(world, sid):
    w = world
    code, d = call(w, f"/api/project/history?id={q(pid('demo', SV))}&sid={q(sid)}")
    assert code == 404, (sid, code, d)
    code, d = call(w, "/api/project/resume", {"id": pid("demo", SV), "sid": sid})
    assert code == 404, (sid, code, d)
    assert not space_windows("demo")


def test_symlinked_journal_is_not_read(world):
    """Агент клиента сделал журнал-ссылку на чужой файл — пульт его не показывает и не продолжает."""
    w = world
    d = transcripts.project_dir(str(w["root"] / "demo/home/projects" / REP), w["root"] / "demo/config/claude")
    d.mkdir(parents=True)
    (d / f"{LINK}.jsonl").symlink_to(w["owner_f"])
    assert call(w, f"/api/project/sessions?id={q(pid('demo', REP))}")[1]["chats"] == []
    assert call(w, f"/api/project/history?id={q(pid('demo', REP))}&sid={LINK}")[0] == 404
    assert call(w, "/api/project/resume", {"id": pid("demo", REP), "sid": LINK})[0] == 404
    assert next(x for x in call(w, "/api/projects")[1]["projects"] if x["id"] == pid("demo", REP))["chats"] == 0


def test_other_tester_and_member_isolated(world):
    w = world
    ids = {x["id"] for x in call(w, "/api/projects", who=OTHER_T)[1]["projects"]}
    assert ids == {pid("other", "Секрет")}
    for who in (OTHER_T, MEMBER):
        for path in (f"/api/project?id={q(pid('demo', SV))}", f"/api/project/sessions?id={q(pid('demo', SV))}",
                     f"/api/project/history?id={q(pid('demo', SV))}&sid={OLD}"):
            code, d = call(w, path, who=who)
            assert code in (403, 404) and "октябрь" not in json.dumps(d, ensure_ascii=False), (who, path, code, d)
        assert call(w, "/api/project/session", {"id": pid("demo", SV)}, who=who)[0] in (403, 404)
        assert call(w, "/api/project/resume", {"id": pid("demo", SV), "sid": OLD}, who=who)[0] in (403, 404)
    # обычный участник проектов пространств не видит ни в списке, ни в группе
    d = call(w, "/api/projects", who=MEMBER)[1]
    assert not d.get("space_projects") and not any(x["id"].startswith("s:") for x in d["projects"])
    assert not space_windows("demo")


def test_viewer_reads_but_does_not_create(world):
    w = world
    assert {x["id"] for x in call(w, "/api/projects", who=VIEWER)[1]["projects"]} == {pid("demo", SV), pid("demo", REP)}
    assert call(w, f"/api/project/sessions?id={q(pid('demo', SV))}", who=VIEWER)[0] == 200
    assert call(w, "/api/project/session", {"id": pid("demo", SV)}, who=VIEWER)[0] == 403
    assert call(w, "/api/project/resume", {"id": pid("demo", SV), "sid": OLD}, who=VIEWER)[0] == 403
    assert call(w, "/api/project/new", {"name": "Взлом"}, who=VIEWER)[0] == 403
    assert not space_windows("demo") and not (w["root"] / "demo/home/projects/Взлом").exists()


def test_owner_sees_space_projects_in_group(world):
    w = world
    d = call(w, "/api/projects", who=OWNER)[1]
    assert not any(x["id"].startswith("s:") for x in d["projects"])          # свои проекты — как раньше
    assert {x["id"] for x in d["space_projects"]} == {pid("demo", SV), pid("demo", REP), pid("other", "Секрет")}
    assert {x["space_title"] for x in d["space_projects"]} == {"Демо для кафе", "Чужое"}
    code, r = call(w, f"/api/project/sessions?id={q(pid('other', 'Секрет'))}", who=OWNER)
    assert code == 200 and [c["sid"] for c in r["chats"]] == [FOREIGN]
    code, r = call(w, "/api/project/session", {"id": pid("other", "Секрет")}, who=OWNER)
    assert code == 200 and r["id"].startswith("t:other:@"), r
    assert call(w, "/api/project/history?id=s:other:..&sid=" + FOREIGN, who=OWNER)[0] == 404


def test_space_projects_off_without_setup(world):
    w = world
    (w["root"] / tenants.MARKER).unlink()
    space_projects._cache.clear()
    assert call(w, "/api/projects")[1]["projects"] == []
    assert call(w, "/api/project/session", {"id": pid("demo", SV)})[0] in (400, 404)
