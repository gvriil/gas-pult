"""Файлы владельца — на Google Диск в папку проекта (#217): панель, бот, перенос старого inbox. Диск — tmp."""

import io
import json
import re
import threading
from pathlib import Path

import pytest

from gas_pult import bot, cli, drive_inbox, tgroutes, webapp
from gas_pult.config import Config


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Корни проектов и «Диск» во временной папке: проект alpha с папкой на Диске, beta — без."""
    projects, drive, data = tmp_path / "projects", tmp_path / "drive", tmp_path / "data"
    for d in (projects / "alpha", projects / "beta", drive / "alpha", drive / "gas-pult", data):
        d.mkdir(parents=True)
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(data))
    monkeypatch.setenv("GAS_PULT_DRIVE_ROOT", str(drive))
    cfg = Config(token="1:T", owners=[1], project_roots=[str(projects)])
    return {"projects": projects, "drive": drive, "data": data, "cfg": cfg}


def test_project_of_and_dir(env):
    roots = env["cfg"].roots()
    assert drive_inbox.project_of(str(env["projects"] / "alpha" / ".claude" / "worktrees" / "x"), roots) == "alpha"
    assert drive_inbox.project_of("/elsewhere/alpha", roots) is None
    assert env["cfg"].drive_folder(str(env["projects"] / "alpha")) == env["drive"] / "alpha"
    assert env["cfg"].drive_folder(str(env["projects"] / "beta")) is None     # папки на Диске нет — inbox


def test_save_no_overwrite_and_streams(env, monkeypatch):
    folder = env["drive"] / "alpha"
    reads = []

    class Src(io.BytesIO):
        def read(self, n=-1):
            reads.append(n)
            return super().read(n)

    monkeypatch.setattr(drive_inbox, "CHUNK", 4)
    a = drive_inbox.save(Src(b"0123456789"), "фото.jpg", folder=folder, inbox=env["data"] / "inbox",
                         inbox_name="x", size=10, day="2026-11-15")
    b = drive_inbox.save(io.BytesIO(b"2"), "фото.jpg", folder=folder, inbox=env["data"] / "inbox",
                         inbox_name="y", day="2026-11-15")
    assert a == folder / "Входящие" / "2026-11-15-фото.jpg" and a.read_bytes() == b"0123456789"
    assert b == folder / "Входящие" / "2026-11-15-фото-2.jpg"                  # без перезаписи — суффикс
    assert max(n for n in reads if n is not None) <= 4                         # кусками, не целиком


def test_save_write_error_falls_back_to_inbox(env, monkeypatch):
    real = drive_inbox._create

    def broken(path):
        f = real(path)

        class W:
            name = f.name

            def write(self, b):
                raise OSError("Диск отвалился")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                f.close()

        return W()

    monkeypatch.setattr(drive_inbox, "_create", broken)

    class Pipe:                                     # тело HTTP: не перематывается
        def __init__(self):
            self.b = io.BytesIO(b"abcdef")

        def read(self, n=-1):
            return self.b.read(n)

    p = drive_inbox.save(Pipe(), "a.txt", folder=env["drive"] / "alpha", inbox=env["data"] / "inbox",
                         inbox_name="a.txt", size=6)
    assert p == env["data"] / "inbox" / "a.txt" and p.read_bytes() == b"abcdef"
    assert list((env["drive"] / "alpha" / "Входящие").iterdir()) == []         # обрывок на Диске убран


@pytest.fixture
def panel(env, monkeypatch):
    p = webapp.Panel(env["cfg"])
    wins = {"@1": {"id": "@1", "path": str(env["projects"] / "alpha")},
            "@2": {"id": "@2", "path": str(env["projects"] / "beta")}}
    monkeypatch.setattr(p.tmux, "window", lambda wid: wins.get(wid))
    return p


def test_panel_upload_to_project_drive(panel, env):
    path = Path(panel.upload("%D1%84%D0%BE%D1%82%D0%BE.jpg", io.BytesIO(b"jpeg"), size=4, w="@1"))
    assert path.parent == env["drive"] / "alpha" / "Входящие"
    assert re.fullmatch(r"\d{4}-\d\d-\d\d-фото\.jpg", path.name) and path.read_bytes() == b"jpeg"
    assert not (env["data"] / "inbox").exists()                               # сервер не держит копию


def test_panel_upload_without_drive_folder_goes_to_inbox(panel, env, capsys):
    assert Path(panel.upload("a.txt", b"x", w="@2")).parent == env["data"] / "inbox"   # у beta нет папки
    assert Path(panel.upload("a.txt", b"x")).parent == env["data"] / "inbox"           # окно не указано
    (env["drive"] / "alpha").rmdir()                                                   # Диск не смонтирован
    assert Path(panel.upload("a.txt", b"x", w="@1")).parent == env["data"] / "inbox"


class Api:
    def __init__(self, src: Path):
        self.src = src

    def __call__(self, method, **kw):
        return {}

    def download(self, file_id, dst_dir, name=None):
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / f"20261115-101500-{name}"
        dst.write_bytes(self.src.read_bytes())
        return dst


@pytest.fixture
def pult(env, tmp_path, monkeypatch):
    x = bot.Pult.__new__(bot.Pult)
    x.cfg = env["cfg"]
    alpha = {"id": "@1", "idx": "1", "name": "alpha", "cmd": "claude", "path": str(env["projects"] / "alpha"),
             "sid": "", "channel": False, "mark": "claude", "by": ""}
    x.tmux = type("T", (), {"window": lambda s, wid: dict(alpha) if wid == "@1" else None,
                            "windows": lambda s: [dict(alpha)]})()
    x.routes = tgroutes.Routes(tmp_path / "r.json")
    x.waiting, x.task = {}, re.compile(r"^(GAS-\d+)$")
    x.home = str(env["projects"])
    x.lock, x.counter, x.answers, x.hints, x.hint_wait = threading.Lock(), 0, {}, {}, {}
    st = {"active": "@1", "notify": "all"}
    x.state = lambda: dict(st)
    x.set_state = lambda **kw: st.update(kw)
    x.sent, x.got = [], []
    x.send = lambda chat, text, **kw: x.sent.append(text) or {"message_id": 1}
    x.to = lambda chat: lambda text, **kw: x.sent.append(text) or {"message_id": 1}
    x.to_claude_live = lambda chat, w, text: x.got.append((w["id"], text))
    x.react = lambda m, e: None
    src = tmp_path / "src.jpg"
    src.write_bytes(b"photo")
    x.api = Api(src)
    return x


def test_bot_attachment_to_project_drive(pult, env):
    pult.on_message({"message_id": 3, "chat": {"id": 1}, "from": {"id": 1}, "caption": "",
                     "document": {"file_id": "f", "file_name": "счёт.pdf"}})
    wid, text = pult.got[-1]
    path = Path(text.split("Файл из Telegram: ")[1])
    assert wid == "@1" and path.parent == env["drive"] / "alpha" / "Входящие" and path.name.endswith("-счёт.pdf")
    assert path.read_bytes() == b"photo" and not list((env["data"] / "inbox").iterdir())   # локальная — удалена


def test_migrate(env, tmp_path, monkeypatch, capsys):
    cfgdir = tmp_path / "cfg"                       # настройки пульта: корни проектов — временные
    cfgdir.mkdir()
    (cfgdir / "token").write_text("1:T")
    (cfgdir / "config.toml").write_text(f'owners = [1]\nproject_roots = ["{env["projects"]}"]\n')
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(cfgdir))
    inbox = env["data"] / "inbox"
    inbox.mkdir()
    (inbox / "20261101-090000-ab12cd-план.pdf").write_bytes(b"plan")         # упомянут в сессии alpha
    (inbox / "20261102-090000-чек.jpg").write_bytes(b"check")                # проект неизвестен — в архив
    (inbox / "ревью-2026-11-14-2100.md").write_text("отчёт")                 # #ревью — остаётся для штаба
    cl = tmp_path / "claude" / "projects" / "-alpha"
    cl.mkdir(parents=True)
    rec = {"cwd": str(env["projects"] / "alpha"),
           "message": {"content": f"Файл из панели: {inbox}/20261101-090000-ab12cd-план.pdf"}}
    (cl / "s.jsonl").write_text(json.dumps(rec, ensure_ascii=False) + "\n")

    cli.main(["inbox", "migrate", "--dry-run", "--claude-dir", str(tmp_path / "claude")])
    assert "проверка" in capsys.readouterr().out and len(list(inbox.iterdir())) == 3   # ничего не тронуто

    cli.main(["inbox", "migrate", "--claude-dir", str(tmp_path / "claude")])
    assert (env["drive"] / "alpha" / "Входящие" / "2026-11-01-план.pdf").read_bytes() == b"plan"
    assert (env["drive"] / "gas-pult" / "Входящие-архив" / "2026-11-02-чек.jpg").read_bytes() == b"check"
    assert [p.name for p in inbox.iterdir()] == ["ревью-2026-11-14-2100.md"]


def test_migrate_keeps_local_when_size_differs(env, monkeypatch):
    inbox = env["data"] / "inbox"
    inbox.mkdir()
    (inbox / "a.bin").write_bytes(b"12345")
    monkeypatch.setattr(drive_inbox, "copy_stream", lambda r, w, size=None: w.write(r.read()[:2]))   # обрыв
    rows = drive_inbox.migrate(inbox, env["drive"], env["cfg"].roots())
    assert not rows[0]["ok"] and "размер" in rows[0]["error"] and (inbox / "a.bin").exists()
    assert list((env["drive"] / "gas-pult" / "Входящие-архив").iterdir()) == []


def test_http_upload_streams_to_project_drive(panel, env, monkeypatch):
    """/api/upload?w=… по HTTP: тело — потоком в файл на Диске (без ``self.body()`` целиком), путь — в ответе."""
    import urllib.request
    from http.server import ThreadingHTTPServer

    from gas_pult import webauth

    panel.people.accept(1)
    panel.people.set_country(1, chosen="NL")
    monkeypatch.setattr(drive_inbox, "CHUNK", 1024)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        body = bytes(range(256)) * 100                           # 25 600 Б — несколько кусков
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/api/upload?w=%401", body,
                                     {"Content-Type": "application/octet-stream", "X-File-Name": "data.bin",
                                      "Cookie": f"{webauth.COOKIE}={panel.auth.issue(1)}"})
        with urllib.request.urlopen(req) as r:
            path = Path(json.loads(r.read())["path"])
    finally:
        srv.shutdown()
    assert path.parent == env["drive"] / "alpha" / "Входящие" and path.read_bytes() == body
