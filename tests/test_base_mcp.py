"""Свои MCP-серверы пульта (задача 48): веб-поиск и Google Диск через rclone — по протоколу, без сети.

Сервер запускается настоящим процессом (``python3 base_mcp.py …``), сервис поиска подменяется локальным HTTP-сервером,
rclone — маленьким скриптом. Проверяем: initialize → tools/list → tools/call, заголовок с ключом у каждого сервиса,
ключ не попадает ни в ответ, ни в stderr, пути Диска не выходят из папки сессии.
"""

import base64
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from gas_pult import base_mcp, mcp

SERVER = Path(base_mcp.__file__)
KEY = "test" + "-key-" + "0123456789abcdef"                 # заведомо не настоящий, склейкой — не для сканера


def rpc(kind: str, calls: list[tuple[str, dict]], env: dict, cwd: Path | None = None) -> tuple[list[dict], str]:
    """Один процесс сервера: initialize, затем вызовы по порядку. Возвращает ответы (без initialize) и stderr."""
    msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"}]
    msgs += [{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls, 1)]
    full = {k: v for k, v in os.environ.items() if not k.startswith(("GAS_", "RCLONE"))} | env
    p = subprocess.run([sys.executable, str(SERVER), kind], input="".join(json.dumps(m) + "\n" for m in msgs),
                       capture_output=True, text=True, timeout=60, env=full, cwd=str(cwd) if cwd else None)
    out = [json.loads(x) for x in p.stdout.splitlines()]
    assert out[0]["id"] == 0 and out[0]["result"]["protocolVersion"] == "2025-06-18"
    assert len(out) == len(calls) + 1                       # на уведомление ответа нет
    return out[1:], p.stderr


def call(name: str, args: dict) -> tuple[str, dict]:
    return "tools/call", {"name": name, "arguments": args}


def text(resp: dict) -> str:
    return resp["result"]["content"][0]["text"]


# ---------- поиск ----------
class Fake(BaseHTTPRequestHandler):
    seen: ClassVar[list] = []
    status = 200

    def log_message(self, *a):
        pass

    def _answer(self, body: bytes):
        n = int(self.headers.get("Content-Length") or 0)
        Fake.seen.append({"path": self.path, "headers": dict(self.headers),
                          "body": json.loads(self.rfile.read(n)) if n else None})
        self.send_response(Fake.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._answer(json.dumps({"web": {"results": [
            {"title": "Погода в Москве", "url": "https://example.ru/w", "description": "Сегодня +5",
             "extra_snippets": ["ветер 3 м/с"]}]}}).encode())

    def do_POST(self):
        if Fake.status != 200:                              # плохой ключ: сервис повторяет его в ответе
            return self._answer(json.dumps({"error": f"invalid key {KEY}"}).encode())
        if self.path.startswith("/v2/web/search"):
            xml = ('<?xml version="1.0" encoding="utf-8"?><yandexsearch><response><results><grouping><group><doc>'
                   '<url>https://ya.example/a</url><title>Курс <hlword>рубля</hlword></title>'
                   '<passages><passage>Курс на сегодня</passage></passages></doc></group></grouping></results>'
                   '</response></yandexsearch>')
            return self._answer(json.dumps({"rawData": base64.b64encode(xml.encode()).decode()}).encode())
        if self.path == "/search" and "x-api-key" in {k.lower() for k in self.headers}:
            return self._answer(json.dumps({"results": [{"title": "Exa", "url": "https://exa.example/",
                                                          "highlights": ["смысл"]}]}).encode())
        self._answer(json.dumps({"results": [{"title": "Tavily", "url": "https://t.example/",
                                              "content": "найдено"}]}).encode())


@pytest.fixture
def api(tmp_path):
    Fake.seen, Fake.status = [], 200
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    keyfile = tmp_path / "search.key"
    keyfile.write_text(KEY + "\n")
    keyfile.chmod(0o600)
    yield {"GAS_SEARCH_BASE": f"http://127.0.0.1:{srv.server_port}", "GAS_SEARCH_KEY_FILE": str(keyfile)}
    srv.shutdown()


def test_search_tools_list(api):
    (lst,), _ = rpc("search", [("tools/list", {})], api)
    tools = lst["result"]["tools"]
    assert [t["name"] for t in tools] == ["web_search"] and tools[0]["inputSchema"]["required"] == ["query"]
    assert "fn" not in tools[0]


@pytest.mark.parametrize("engine, header, value, expect", [
    ("brave", "X-Subscription-Token", KEY, "Погода в Москве"),
    ("tavily", "Authorization", f"Bearer {KEY}", "Tavily"),
    ("exa", "X-Api-Key", KEY, "смысл"),
    ("yandex", "Authorization", f"Api-Key {KEY}", "Курс рубля"),
])
def test_search_each_engine(api, engine, header, value, expect):
    env = api | {"GAS_SEARCH_ENGINE": engine, "GAS_SEARCH_FOLDER": "b1gtestfolder"}
    (r,), err = rpc("search", [call("web_search", {"query": "курс рубля", "max_results": 3, "region": "ru"})], env)
    assert not r["result"]["isError"], text(r)
    assert expect in text(r) and "https://" in text(r)
    got = {k.lower(): v for k, v in Fake.seen[0]["headers"].items()}
    assert got[header.lower()] == value
    assert KEY not in text(r) and KEY not in err
    if engine == "yandex":
        b = Fake.seen[0]["body"]
        assert b["folderId"] == "b1gtestfolder" and b["query"]["searchType"] == "SEARCH_TYPE_RU"
        assert b["groupSpec"]["groupsOnPage"] == "3" and b["region"] == "225"
    if engine == "brave":
        assert "search_lang=ru" in Fake.seen[0]["path"] and "count=3" in Fake.seen[0]["path"]
    if engine == "tavily":
        assert Fake.seen[0]["body"]["country"] == "russia" and Fake.seen[0]["body"]["max_results"] == 3


def test_search_key_hidden_in_errors(api):
    Fake.status = 401
    (r,), err = rpc("search", [call("web_search", {"query": "x"})], api | {"GAS_SEARCH_ENGINE": "tavily"})
    assert r["result"]["isError"] and "401" in text(r) and "проверьте ключ" in text(r)
    assert KEY not in text(r) and KEY not in err and "***" in text(r)


def test_search_without_key_or_folder(api, tmp_path):
    (r,), _ = rpc("search", [call("web_search", {"query": "x"})],
                  {"GAS_SEARCH_KEY_FILE": str(tmp_path / "нет.key"), "GAS_SEARCH_ENGINE": "brave"})
    assert r["result"]["isError"] and "Интеграциях" in text(r)
    (r,), _ = rpc("search", [call("web_search", {"query": "x"})], api | {"GAS_SEARCH_ENGINE": "yandex"})
    assert r["result"]["isError"] and "каталога" in text(r) and Fake.seen == []


def test_unknown_method_and_tool(api):
    (a, b), _ = rpc("search", [("resources/list", {}), call("nope", {})], api)
    assert a["error"]["code"] == -32601 and b["error"]["code"] == -32602


# ---------- Google Диск через rclone ----------
FAKE_RCLONE = r'''#!/usr/bin/env python3
import json, os, shutil, sys
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
a = sys.argv[1:]
drive = os.environ["FAKE_DRIVE"]
def loc(x):
    return os.path.join(drive, x.split(":", 1)[1]) if x.startswith("gdrive:") else x
if a[0] == "lsjson":
    d = loc(a[1])
    out = [{"Path": n, "Name": n, "Size": os.path.getsize(os.path.join(d, n)),
            "ModTime": "2026-11-0%dT10:00:00Z" % (i + 1), "IsDir": os.path.isdir(os.path.join(d, n))}
           for i, n in enumerate(sorted(os.listdir(d)))]
    print(json.dumps(out))
elif a[0] == "copyto":
    src, dst = loc(a[1]), loc(a[2])
    if not os.path.exists(src):
        print("ERROR : object not found refresh_token=" + "abc123secret", file=sys.stderr); sys.exit(3)
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    shutil.copyfile(src, dst)
'''


@pytest.fixture
def drive(tmp_path):
    exe = tmp_path / "rclone"
    exe.write_text(FAKE_RCLONE)
    exe.chmod(0o755)
    remote, work, outside = tmp_path / "remote", tmp_path / "work", tmp_path / "outside"
    for d in (remote, work, outside):
        d.mkdir()
    for i, n in enumerate(["a.txt", "b.txt", "c.txt", "d.txt"]):
        (remote / n).write_text(f"файл {i}")
    (outside / "secret.txt").write_text("чужое")
    (work / "ссылка").symlink_to(outside)
    log = tmp_path / "log.jsonl"
    log.write_text("")
    env = {"GAS_DRIVE_RCLONE": str(exe), "FAKE_DRIVE": str(remote), "FAKE_LOG": str(log),
           "RCLONE_CONFIG": str(tmp_path / "rclone.conf")}
    return {"env": env, "work": work, "remote": remote, "log": log}


def rclone_calls(d) -> list[list[str]]:
    return [json.loads(x) for x in d["log"].read_text().splitlines()]


def test_drive_tools_list(drive):
    (lst,), _ = rpc("drive", [("tools/list", {})], drive["env"], drive["work"])
    assert [t["name"] for t in lst["result"]["tools"]] == ["drive_list", "drive_download", "drive_upload"]


def test_drive_recent_download_upload(drive):
    (ls, dl, up), _ = rpc("drive", [
        call("drive_list", {"limit": 3}),
        call("drive_download", {"path": "c.txt", "to": "inbox/c.txt"}),
        call("drive_upload", {"path": "inbox/c.txt", "folder": "Отчёты"})], drive["env"], drive["work"])
    lines = text(ls).splitlines()[1:]
    assert [x.split(" ·")[0] for x in lines[:3]] == ["d.txt", "c.txt", "b.txt"] and "ещё 1" in text(ls)
    assert not dl["result"]["isError"], text(dl)
    assert (drive["work"] / "inbox" / "c.txt").read_text() == "файл 2"
    assert not up["result"]["isError"] and (drive["remote"] / "Отчёты" / "c.txt").read_text() == "файл 2"
    calls = rclone_calls(drive)
    assert calls[0][:2] == ["lsjson", "gdrive:"]
    assert calls[1] == ["copyto", "gdrive:c.txt", str(drive["work"].resolve() / "inbox" / "c.txt")]
    assert calls[2] == ["copyto", str(drive["work"].resolve() / "inbox" / "c.txt"), "gdrive:Отчёты/c.txt"]


@pytest.mark.parametrize("tool, args", [
    ("drive_download", {"path": "a.txt", "to": "../a.txt"}),
    ("drive_download", {"path": "a.txt", "to": "/tmp/a.txt"}),
    ("drive_download", {"path": "a.txt", "to": "~/a.txt"}),
    ("drive_download", {"path": "a.txt", "to": "ссылка/a.txt"}),     # ссылка ведёт из папки наружу
    ("drive_upload", {"path": "ссылка/secret.txt"}),
    ("drive_upload", {"path": "../outside/secret.txt"}),
    ("drive_upload", {"path": "нет-такого.txt"}),
    ("drive_download", {"path": "../a.txt"}),
])
def test_drive_paths_stay_inside(drive, tool, args):
    (r,), _ = rpc("drive", [call(tool, args)], drive["env"], drive["work"])
    assert r["result"]["isError"], text(r)
    assert rclone_calls(drive) == []                         # rclone даже не запускался
    assert not (drive["work"].parent / "a.txt").exists() and not (drive["remote"] / "secret.txt").exists()


def test_drive_rclone_error_hides_token(drive):
    (r,), err = rpc("drive", [call("drive_download", {"path": "нет.txt"})], drive["env"], drive["work"])
    assert r["result"]["isError"] and "rclone" in text(r)
    assert "abc123secret" not in text(r) and "abc123secret" not in err


def test_drive_dir_from_env(drive, tmp_path):
    other = tmp_path / "space"
    other.mkdir()
    (r,), _ = rpc("drive", [call("drive_download", {"path": "a.txt"})], drive["env"] | {"GAS_DRIVE_DIR": str(other)},
                  drive["work"])
    assert not r["result"]["isError"] and (other / "a.txt").exists() and not (drive["work"] / "a.txt").exists()


# ---------- подключение из «Интеграций» ----------
class Claude:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, home=None, env=None):
        self.calls.append(args)
        out = "websearch: python3 base_mcp.py search - ✔ Connected\n"
        return subprocess.CompletedProcess(args, 0, out if args[0] == "list" else "", "")


@pytest.fixture
def claude(monkeypatch, tmp_path):
    c = Claude()
    monkeypatch.setattr(mcp, "_claude", c)
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    return c


def test_add_websearch_key_in_file_not_config(claude, tmp_path):
    res = mcp.Mcp().add("websearch", "websearch", {"engine": "brave", "token": KEY})
    args = claude.calls[0]
    cfg = json.loads(args[2])
    assert args[:2] == ("add-json", "websearch") and KEY not in " ".join(args)
    assert cfg["type"] == "stdio" and cfg["args"] == [str(SERVER), "search"]
    f = Path(cfg["env"]["GAS_SEARCH_KEY_FILE"])
    assert f == tmp_path / "cfg" / "integrations" / "websearch.key" and f.read_text().strip() == KEY
    assert f.stat().st_mode & 0o777 == 0o600 and f.parent.stat().st_mode & 0o777 == 0o700
    assert cfg["env"]["GAS_SEARCH_ENGINE"] == "brave" and "подключён" in res
    mcp.Mcp().remove("websearch")
    assert not f.exists()                                    # «Убрать» уносит и ключ


def test_add_websearch_validates(claude):
    with pytest.raises(ValueError, match="каталога"):
        mcp.Mcp().add("websearch", "websearch", {"engine": "yandex", "token": KEY})
    with pytest.raises(ValueError, match="сервис"):
        mcp.Mcp().add("websearch", "websearch", {"engine": "google", "token": KEY})
    with pytest.raises(ValueError, match="одна строка"):
        mcp.Mcp().add("websearch", "websearch", {"engine": "brave", "token": "a b"})
    assert claude.calls == []
    mcp.Mcp().add("websearch", "websearch", {"token": KEY, "folder": "b1gabcdef12"})   # по умолчанию — Яндекс
    assert json.loads(claude.calls[0][2])["env"]["GAS_SEARCH_FOLDER"] == "b1gabcdef12"


def test_person_keys_in_own_folder(claude, tmp_path):
    home = tmp_path / "data" / "people" / "42" / "claude"
    home.mkdir(parents=True)
    mcp.Mcp().add("websearch", "websearch", {"engine": "exa", "token": KEY}, home=home)
    f = Path(json.loads(claude.calls[0][2])["env"]["GAS_SEARCH_KEY_FILE"])
    assert f.parent == home.parent / "integrations" and not (tmp_path / "cfg").exists()


TOKEN = {"access_token": "ya29." + "fake", "token_type": "Bearer", "refresh_token": "1//" + "fake",
         "expiry": "2026-11-07T21:00:00Z"}


@pytest.mark.parametrize("pasted", [
    json.dumps(TOKEN),
    "Paste the following into your remote machine --->\n" + json.dumps(TOKEN) + "\n<---End paste",
    base64.b64encode(json.dumps({"token": json.dumps(TOKEN)}).encode()).decode(),
])
def test_rclone_token_forms(pasted):
    assert json.loads(mcp.rclone_token(pasted)) == TOKEN


def test_rclone_token_rejects_junk():
    with pytest.raises(ValueError, match="rclone authorize"):
        mcp.rclone_token("привет")


def test_add_drive_writes_own_rclone_conf(claude, tmp_path, monkeypatch):
    monkeypatch.setattr(mcp, "rclone_bin", lambda: "/opt/rclone")
    mcp.Mcp().add("drive", "drive", {"token": json.dumps(TOKEN)})
    args = claude.calls[0]
    cfg = json.loads(args[2])
    assert "refresh_token" not in args[2] and cfg["args"][1] == "drive"
    conf = Path(cfg["env"]["RCLONE_CONFIG"])
    assert conf.stat().st_mode & 0o777 == 0o600 and "[gdrive]\ntype = drive" in conf.read_text()
    assert cfg["env"]["GAS_DRIVE_RCLONE"] == "/opt/rclone"
    monkeypatch.setattr(mcp, "rclone_bin", lambda: "")
    with pytest.raises(ValueError, match="нет rclone"):
        mcp.Mcp().add("drive", "drive", {"token": json.dumps(TOKEN)})
