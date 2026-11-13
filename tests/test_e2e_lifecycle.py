"""Сквозные сценарии жизненного цикла (задание штаба 13.11, пункт 5): настоящий tmux, настоящий HTTP-сервер панели,
«Claude» — скрипт, который выходит по ``/exit``. «Перезапуск службы» — новый объект ``Panel`` на тех же данных.

- закрыл — не вернулась после перезагрузки панели;
- удалил — нет после перезапуска службы (журнал в корзине, «Вернуть» — на месте);
- две сессии одного проекта — сообщения из панели не путаются."""

import json
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import transcripts, webapp, webauth
from gas_pult.config import Config

pytestmark = pytest.mark.skipif(not shutil.which("tmux"), reason="нужен tmux")

FAKE = """#!/usr/bin/env bash
while true; do printf '❯ '; read -r line || exit 0; [ "$line" = "/exit" ] && exit 0; echo "got: $line"; done
"""


def wait(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


@pytest.fixture
def env(tmp_path, monkeypatch):
    d = tempfile.mkdtemp(prefix="gp-", dir="/tmp")
    monkeypatch.setenv("GAS_PULT_TMUX_SOCKET", d + "/s")
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(transcripts, "CLAUDE_PROJECTS", tmp_path / "cp")
    fake = tmp_path / "bin" / "claude"
    fake.parent.mkdir()
    fake.write_text(FAKE)
    fake.chmod(0o755)
    proj = tmp_path / "shtap"
    proj.mkdir()
    monkeypatch.setattr(webapp.models, "command", lambda base, profile, st, **kw: str(fake))
    servers = []

    def start():
        p = webapp.Panel(Config(token="1:T", owners=[1], session="t", claude=str(fake)))
        p.people.accept(1)
        p.people.set_country(1, chosen="NL")
        p.need_claude = lambda: None
        p.pult.QUIT_WAIT = 5
        srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return p, f"http://127.0.0.1:{srv.server_address[1]}"

    yield start, proj
    for s in servers:
        s.shutdown()
    subprocess.run(["tmux", "-S", d + "/s", "kill-server"], capture_output=True)
    shutil.rmtree(d, ignore_errors=True)


def call(base, path, body=None, tok=""):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={tok}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def ids(base, tok):
    return {s["id"] for s in call(base, "/api/sessions", tok=tok)[1]["sessions"]}


def journal(proj, sid, text="привет"):
    d = transcripts.project_dir(str(proj))
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{sid}.jsonl"
    f.write_text(json.dumps({"type": "user", "message": {"content": text}}) + "\n")
    return f


def test_closed_does_not_come_back_after_reload_or_restart(env):
    start, proj = env
    p, base = start()
    tok = p.auth.issue(1)
    w = p.open_in(str(proj))
    assert wait(lambda: w["id"] in ids(base, tok))
    code, d = call(base, "/api/close", {"w": w["id"]}, tok)
    assert code == 200 and d["result"] == "закрыто", d
    assert wait(lambda: w["id"] not in ids(base, tok))
    for _ in range(3):                                                 # панель перезагрузили — опрос раз в 3 с
        assert w["id"] not in ids(base, tok)
    p2, base2 = start()                                                # и служба перезапущена
    assert w["id"] not in ids(base2, p2.auth.issue(1))


def test_deleted_is_gone_after_service_restart_and_can_be_restored(env):
    start, proj = env
    p, base = start()
    tok = p.auth.issue(1)
    w = p.open_in(str(proj))
    f = journal(proj, w["sid"])
    assert wait(lambda: w["id"] in ids(base, tok))
    code, d = call(base, "/api/chat/delete", {"w": w["id"]}, tok)
    assert code == 200 and d["trash"] and not f.exists(), d
    p2, base2 = start()                                                # перезапуск службы
    tok2 = p2.auth.issue(1)
    assert w["id"] not in ids(base2, tok2)
    trash = call(base2, "/api/chat/trash", tok=tok2)[1]["trash"]
    assert [x["sid"] for x in trash] == [w["sid"]]
    assert call(base2, "/api/chat/restore", {"id": trash[0]["id"]}, tok2)[0] == 200   # «Отменить»
    assert f.exists()


def test_two_sessions_of_one_project_from_panel(env):
    start, proj = env
    p, base = start()
    tok = p.auth.issue(1)
    a, b = p.open_in(str(proj), name="штаб"), p.open_in(str(proj), name="штаб2")
    assert wait(lambda: {a["id"], b["id"]} <= ids(base, tok))
    assert p.pult.state().get("active") in (None, "")                  # панель активное окно бота не трогала
    for w, text in ((a, "в первое"), (b, "во второе"), (a, "снова в первое")):
        assert wait(lambda w=w: "❯" in "\n".join(p.tmux.screen(w["id"])))
        code, d = call(base, "/api/send", {"w": w["id"], "text": text}, tok)
        assert code == 200, d
    assert wait(lambda: "got: снова в первое" in "\n".join(p.tmux.screen(a["id"])))
    sa, sb = "\n".join(p.tmux.screen(a["id"], 60)), "\n".join(p.tmux.screen(b["id"], 60))
    assert "got: в первое" in sa and "во второе" not in sa
    assert "got: во второе" in sb and "первое" not in sb
