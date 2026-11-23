"""Владелец 23.11: агент в чате фокус-ссылки вынес задачу в новое окно в другой папке — человек по ссылке его не нашёл.
Окно, открытое из окна ссылки (``@gas_pult_from``, spawned.py), видно по той же ссылке; чужое новое окно — нет.
И файл без подписи: агенту — пометка «посмотри и свяжи с последним вопросом» (uploads.mark_bare)."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_focus import FX, call, open_link, proj_link, proj_server, server  # noqa: F401 — server: фикстура

from gas_pult import spawned, transcripts, uploads
from gas_pult.tmux import Tmux

SRC = str(Path(spawned.__file__).resolve().parent.parent)


# ---------- признак «порождено из окна» ----------
def fake_proc(root: Path, pid: int, argv: list[str], env: dict):
    d = root / str(pid)
    d.mkdir(parents=True)
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    (d / "environ").write_bytes(b"\0".join(f"{k}={v}".encode() for k, v in env.items()) + b"\0")


def test_name_of_and_parent_pane(tmp_path):
    assert spawned.name_of(["tmux", "new-window", "-d", "-t", "main:", "-n", "dom-1200", "-c", "/x", "claude"]) \
        == "dom-1200"
    assert spawned.name_of(["tmux", "neww", "-nkid"]) == "kid"
    assert spawned.name_of(["tmux", "new-window", "claude"]) is None
    assert spawned.name_of(["tmux", "send-keys", "-n", "x"]) is None
    sock = str(tmp_path / "s")
    fake_proc(tmp_path / "proc", 101, ["tmux", "-S", sock, "new-window", "-n", "kid"], {"TMUX": f"{sock},1,0",
                                                                                         "TMUX_PANE": "%4"})
    # другой сервер tmux, запуск не из окна (нет TMUX_PANE), не new-window — не в счёт
    fake_proc(tmp_path / "proc", 102, ["tmux", "new-window", "-n", "kid"], {"TMUX": "/other,1,0", "TMUX_PANE": "%9"})
    fake_proc(tmp_path / "proc", 103, ["tmux", "-S", sock, "new-window", "-n", "kid"], {"TMUX": f"{sock},1,0"})
    fake_proc(tmp_path / "proc", 104, ["tmux", "-S", sock, "send-keys", "x"], {"TMUX": f"{sock},1,0",
                                                                                 "TMUX_PANE": "%7"})
    assert spawned.parent_pane(sock, "kid", tmp_path / "proc") == "%4"
    assert spawned.parent_pane(sock, "other", tmp_path / "proc") == ""            # имя не совпало — родителя нет
    # два окна с одним именем в одно мгновение из разных окон — неясно, чей: родителя нет
    fake_proc(tmp_path / "proc", 105, ["tmux", "-S", sock, "new-window", "-n", "kid"], {"TMUX": f"{sock},1,0",
                                                                                         "TMUX_PANE": "%5"})
    assert spawned.parent_pane(sock, "kid", tmp_path / "proc") == ""


def test_hook_command_quotes_and_silence():
    cmd = spawned.hook_command("/usr/bin/python3", "/opt/gp/src")
    assert cmd.startswith('run-shell "PYTHONPATH=/opt/gp/src timeout -k 1 2 /usr/bin/python3 -m gas_pult.spawned ')
    # хук держит сервер tmux — потолок времени, чтобы зависший Python не заморозил окна
    assert "'#{window_id}' '#{socket_path}'" in cmd and ">/dev/null 2>&1; true" in cmd   # вывод не поверх окна
    assert spawned.hook_command("/usr/bin/py thon", "/opt") == ""                         # странный путь — не ставим


@pytest.mark.skipif(not shutil.which("tmux") or not spawned.hook_command(), reason="нет tmux или необычный путь")
def test_real_tmux_hook_marks_parent(tmp_path):
    """Настоящий tmux на своём сокете: агент в окне @0 делает ``tmux new-window`` — у нового окна родитель @0;
    окно, открытое не из окна (без TMUX_PANE: пульт, бот, cron), — без родителя."""
    import tempfile
    d = tempfile.mkdtemp(prefix="gp-sp-", dir="/tmp")
    sock = os.path.join(d, "s")
    tm = Tmux("main", socket=sock)
    try:
        subprocess.run(["tmux", "-S", sock, "new-session", "-d", "-s", "main", "-n", "parent", "sleep 60"], check=True)
        assert spawned.install(tm.run)
        assert spawned.HOOK.split("[")[0] in tm.run("show-hooks", "-g")
        parent = tm.run("display-message", "-p", "-t", "main:parent", "#{window_id}").strip()
        pane = tm.run("display-message", "-p", "-t", "main:parent", "#{pane_id}").strip()
        env = {**os.environ, "TMUX": f"{sock},1,0", "TMUX_PANE": pane}
        subprocess.run(["tmux", "-S", sock, "new-window", "-d", "-t", "main:", "-n", "kid", "-c", d, "sleep 60"],
                       env=env, check=True)
        env.pop("TMUX_PANE")
        subprocess.run(["tmux", "-S", sock, "new-window", "-d", "-t", "main:", "-n", "lone", "sleep 60"], env=env,
                       check=True)
        for _ in range(50):
            got = {w["name"]: w.get("from", "") for w in tm.windows()}
            if got.get("kid"):
                break
            time.sleep(0.1)
        assert got == {"parent": "", "kid": parent, "lone": ""}, got
    finally:
        subprocess.run(["tmux", "-S", sock, "kill-server"], capture_output=True)
        shutil.rmtree(d, ignore_errors=True)


def test_spawn_hook_only_on_owner_tmux():
    assert Tmux("main", socket="/tmp/none").spawn_hook() is False            # тесты и отдельный сокет — нет
    assert Tmux("main", socket="/tmp/none", user="pult_t_a").spawn_hook() is False   # пространство — нет


# ---------- видимость по ссылке ----------
def test_single_link_sees_spawned_window_not_foreign(server):  # noqa: F811
    s = server
    _, _, cookie = open_link(s)
    s["wins"].w["@3"] = {"id": "@3", "name": "dom", "path": "/srv/dom", "cmd": "claude", "from": "@1"}   # из ссылки
    s["wins"].w["@4"] = {"id": "@4", "name": "deep", "path": "/srv/deep", "cmd": "claude", "from": "@3"}  # из него
    s["wins"].w["@5"] = {"id": "@5", "name": "mine", "path": "/srv/mine", "cmd": "claude", "from": "@2"}  # чужое
    s["wins"].w["@6"] = {"id": "@6", "name": "new", "path": "/srv/new", "cmd": "claude"}                 # без родителя
    code, d, _ = call(s["base"], "/api/sessions", None, cookie, FX)
    assert code == 200 and sorted(x["id"] for x in d["sessions"]) == ["@1", "@3", "@4"]
    assert call(s["base"], "/api/send", {"w": "@3", "text": "привет"}, cookie, FX)[0] == 200
    for wid in ("@2", "@5", "@6"):
        code, r, _ = call(s["base"], "/api/send", {"w": wid, "text": "x"}, cookie, FX)
        assert code == 403 and r["code"] == "focus_scope", wid
    assert s["sent"] == [("@3", "привет")]


def test_project_link_sees_window_spawned_into_other_folder(server, monkeypatch):  # noqa: F811
    s = server
    proj_server(s, monkeypatch)
    _, cookie = proj_link(s)
    s["wins"].w["@3"] = {"id": "@3", "name": "dom", "path": "/srv/dom", "cmd": "claude", "from": "@1"}
    s["wins"].w["@4"] = {"id": "@4", "name": "x", "path": "/srv/x", "cmd": "claude", "from": "@2"}   # из чужого
    code, d, _ = call(s["base"], "/api/sessions", None, cookie, FX)
    assert code == 200 and sorted(x["id"] for x in d["sessions"]) == ["@1", "@3"]
    assert call(s["base"], "/api/send", {"w": "@3", "text": "ок"}, cookie, FX)[0] == 200
    assert call(s["base"], "/api/send", {"w": "@4", "text": "x"}, cookie, FX)[0] == 403
    assert call(s["base"], "/api/send", {"w": "@2", "text": "x"}, cookie, FX)[0] == 403


def test_spawned_cycle_and_space_links_stay_closed(server):  # noqa: F811
    p = server["p"]
    server["wins"].w["@1"]["from"] = "@3"
    server["wins"].w["@3"] = {"id": "@3", "name": "a", "path": "/a", "cmd": "claude", "from": "@1"}      # цикл опций
    assert p.focus_spawned({"w": "@1"}) == {"@3"}
    assert p.focus_spawned({"w": "@1", "space": "acme"}) == set()             # окно пространства — без потомков
    assert p.focus_spawned({"w": "", "mode": "space", "space": "acme"}) == set()
    server["wins"].w["@7"] = {"id": "@7", "name": "s", "path": "/s", "cmd": "claude", "from": "@1", "space": "acme"}
    assert "@7" not in p.focus_spawned({"w": "@1"})                           # окно пространства не видно никогда


def test_focus_page_has_switcher_for_spawned_chats():
    page = (Path(SRC) / "gas_pult/web/index.html").read_text(encoding="utf-8")
    assert "const FOCUS_MULTI = () => FOCUS && !FOCUS_PROJ() && sessions.length > 1;" in page
    assert "body.focus.focus-multi #menu [data-act=switch] { display: flex !important; }" in page
    assert "if (FOCUS) focusNew();" in page and "Агент открыл новый чат" in page


# ---------- файл без подписи ----------
def test_bare_file_gets_note_caption_does_not():
    t = uploads.mark_bare("Посмотри файл.\n\nФайл из панели: /in/a.png")
    assert t.startswith("Человек прислал снимок без подписи. Посмотри его и свяжи с последним вопросом. Если неясно — "
                        "спроси, что с ним сделать. Не продолжай другую тему, пока не ответил на снимок.")
    assert t.endswith("\n\nФайл из панели: /in/a.png")
    assert uploads.mark_bare("Файл из Telegram: /in/doc.pdf").startswith("Человек прислал файл без подписи.")
    many = uploads.mark_bare("Посмотри файл.\n\nФайл из панели: /a.jpg\nФайл из панели: /b.webp")
    assert many.startswith("Человек прислал снимки без подписи. Посмотри их") and many.count("Файл из панели") == 2
    for same in ("Что тут не так?\n\nФайл из панели: /in/a.png", "привет", ""):
        assert uploads.mark_bare(same) == same
    assert uploads.shown(t) == "Посмотри файл.\n\nФайл из панели: /in/a.png"       # в ленте — как писал человек
    assert uploads.shown(many).startswith("Посмотри файл.\n\nФайл из панели: /a.jpg")


def test_send_route_marks_bare_file(server):  # noqa: F811
    s = server
    _, _, cookie = open_link(s)
    assert call(s["base"], "/api/send", {"w": "@1", "text": "Посмотри файл.\n\nФайл из панели: /in/x.png"},
                cookie, FX)[0] == 200
    assert call(s["base"], "/api/send", {"w": "@1", "text": "Это ошибка?\n\nФайл из панели: /in/y.png"},
                cookie, FX)[0] == 200
    (_, a), (_, b) = s["sent"]
    assert a.startswith("Человек прислал снимок без подписи.") and a.endswith("Файл из панели: /in/x.png")
    assert b == "Это ошибка?\n\nФайл из панели: /in/y.png"


def test_bot_photo_without_caption_gets_note():
    src = (Path(SRC) / "gas_pult/bot.py").read_text(encoding="utf-8")
    assert 'uploads.mark_bare(f"{t or uploads.DEFAULT}\\n\\nФайл из Telegram: {path}")' in src


def test_feed_shows_plain_text_not_note():
    marked = uploads.mark_bare("Посмотри файл.\n\nФайл из панели: /in/x.png")
    feed = transcripts._Feed()
    feed.line(json.dumps({"type": "user", "timestamp": "2026-11-23T10:00:00Z",
                          "message": {"role": "user", "content": marked}}).encode())
    assert feed.items[-1]["text"] == "Посмотри файл.\n\nФайл из панели: /in/x.png"   # пометку человек не писал


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
