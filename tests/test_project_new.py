"""«Новый проект» (панель чатов → «Проекты» → «+»): POST /api/project/new и имя папки из названия."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import projects, webapp, webauth
from gas_pult.config import Config

INDEX = (Path(__file__).parent.parent / "src" / "gas_pult" / "web" / "index.html").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def own_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture
def server(monkeypatch, tmp_path):
    p = webapp.Panel(Config(token="1:T", owners=[1], project_roots=[str(tmp_path / "projects"), str(tmp_path / "b")]))
    for uid, role in ((2, "member"), (3, "viewer")):
        p.people.add(uid, role)
    for uid in (1, 2, 3):
        p.people.accept(uid)
        p.people.set_country(uid, chosen="NL")
    opened = []
    monkeypatch.setattr(p.tmux, "new_window", lambda *a, **kw: opened.append(a) or "@9")
    monkeypatch.setattr(p.tmux, "windows", lambda: [])
    p.opened = opened
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield p, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def call(base, path, body=None, token=""):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={token}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


@pytest.mark.parametrize("name,folder", [
    ("Магазин книг", "magazin-knig"), ("Shop Bot", "shop-bot"), ("../evil", "evil"), ("a/../../b", "a-b"),
    ("Щука и ёж", "schuka-i-ezh"), ("  ---  ", ""), ("Я", "ya"), ("x", ""), ("Отчёт 2026!", "otchet-2026"),
    ("ы" * 60, "y" * 41),
])
def test_folder_of(name, folder):
    assert projects.folder_of(name) == folder
    assert not folder or projects.FOLDER_OK.match(folder)


def test_project_new_creates_folder_record_and_no_window(server, tmp_path):
    panel, base = server
    owner = panel.auth.issue(1)
    code, d = call(base, "/api/project/new", {"name": "Магазин книг", "instructions": "# Магазин\nОтвечай коротко.",
                                              "model": "sonnet"}, owner)
    assert code == 200, d
    dst = tmp_path / "projects" / "magazin-knig"                       # первый из project_roots
    assert d["folder"] == "magazin-knig" and d["name"] == "Магазин книг" and d["id"] == projects.pid_of(str(dst))
    assert (dst / ".git").is_dir()                                     # git init — как у «Новой папки»
    assert (dst / "CLAUDE.md").read_text(encoding="utf-8") == "# Магазин\nОтвечай коротко.\n"
    assert panel.opened == []                                          # окно — только при первой отправке
    rec = json.loads((tmp_path / "data" / "projects.json").read_text(encoding="utf-8"))["projects"][d["id"]]
    assert rec["name"] == "Магазин книг" and rec["origin"] == "new" and rec["model"] == "sonnet" and rec["by"] is None
    code, lst = call(base, "/api/projects", None, owner)               # сразу в списке, с именем человека
    assert code == 200 and any(p["id"] == d["id"] and p["name"] == "Магазин книг" for p in lst["projects"])


def test_project_new_existing_folder_is_not_touched(server, tmp_path):
    panel, base = server
    owner = panel.auth.issue(1)
    dst = tmp_path / "projects" / "shop"
    dst.mkdir(parents=True)
    (dst / "CLAUDE.md").write_text("моё", encoding="utf-8")
    code, d = call(base, "/api/project/new", {"name": "Shop", "instructions": "чужое"}, owner)
    assert code == 400 and "уже есть" in d["error"] and "shop" in d["error"]
    assert (dst / "CLAUDE.md").read_text(encoding="utf-8") == "моё" and not (dst / ".git").exists()
    code, d = call(base, "/api/project/new", {"name": "Shop", "folder": "shop-2"}, owner)   # своё имя папки
    assert code == 200 and d["folder"] == "shop-2" and not (tmp_path / "projects" / "shop-2" / "CLAUDE.md").exists()


@pytest.mark.parametrize("body,err", [
    ({"name": ""}, "назовите"), ({"name": "!!"}, "латиница"), ({"name": "x", "folder": "../evil"}, "латиница"),
    ({"name": "x", "folder": "a/b"}, "латиница"), ({"name": "Ок", "folder": ".git"}, "латиница"),
    ({"name": "Ок", "model": "gpt-9"}, "модели"), ({"name": "Ок", "profile": "nope"}, "поставщика"),
])
def test_project_new_rejects(server, tmp_path, body, err):
    panel, base = server
    code, d = call(base, "/api/project/new", body, panel.auth.issue(1))
    assert code == 400 and err in d["error"], d
    assert not (tmp_path / "evil").exists() and not (tmp_path / "projects" / "a").exists()


def test_project_new_roles(server, tmp_path):
    panel, base = server
    member, viewer = panel.auth.issue(2), panel.auth.issue(3)
    assert call(base, "/api/project/new", {"name": "Чужой"}, viewer)[0] == 403        # наблюдателю — нет
    assert call(base, "/api/project/new", {"name": "Без входа"})[0] in (401, 403)
    assert not (tmp_path / "projects" / "chuzhoy").exists()
    code, d = call(base, "/api/project/new", {"name": "Свой"}, member)              # участнику — да, как «Новая папка»
    assert code == 200 and d["folder"] == "svoy"
    rec = json.loads((tmp_path / "data" / "projects.json").read_text(encoding="utf-8"))["projects"][d["id"]]
    assert rec["by"] == 2


def test_panel_has_new_project_button():
    nav = INDEX[INDEX.index("function renderNav("):INDEX.index("function navOpen(")]
    assert "data-nnewp" in nav                                       # «+» у заголовка «Проекты»
    assert 'api("/api/project/new"' in INDEX and 'hv("sheet.new-project")' in INDEX
    sheet = INDEX[INDEX.index("function newProject("):INDEX.index("// Модель этого чата")]
    assert "newChat(d.id)" in sheet and "/api/project/session" not in sheet     # окно — при первой отправке


def test_e2e_newproj_demo():
    import importlib.util
    import shutil
    from functools import partial
    from http.server import SimpleHTTPRequestHandler

    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    web = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(web)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    spec = importlib.util.spec_from_file_location("newproj_demo",
                                                  Path(__file__).resolve().parent / "e2e" / "newproj_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
