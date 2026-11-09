"""Нагрузка опроса: список окон — один ``ps`` на все окна, общий кэш на короткий срок (панель), без зрителя — без
опроса (браузер; сценарий tests/e2e/viewer_poll.py с подменой часов)."""

import subprocess

import pytest

from gas_pult import tmux as tmux_mod
from gas_pult.tmux import Tmux

LIST = ("@1\t0\tone\tbash\t/p/one\t/dev/pts/1\tclaude\t\t\n"
        "@2\t1\ttwo\tbash\t/p/two\t/dev/pts/2\t\t\t\n"
        "@3\t2\tthree\tbash\t/p/three\t/dev/pts/3\tclaude\t\t\n")
PS = ("pts/1    11 bash\n"
      "pts/1    12 /usr/local/bin/claude --settings /x/profiles/zai.json\n"
      "pts/2    21 bash\n"
      "pts/3    31 bash\n")


class Fake:
    """Подмена subprocess.run: считает вызовы tmux и ps, отдаёт заготовленный вывод."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, cmd, *a, **kw):
        self.calls.append(list(cmd))
        out = ""
        if "list-windows" in cmd:
            out = LIST
        elif cmd[0] == "ps":
            out = PS
        elif "new-window" in cmd:
            out = "@9\n"
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    def count(self, what: str) -> int:
        return sum(1 for c in self.calls if (c[0] == "ps" if what == "ps" else what in c))


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    monkeypatch.setattr(tmux_mod.subprocess, "run", f)
    monkeypatch.setattr(Tmux, "_WINS", {})
    monkeypatch.setattr(Tmux, "_FORGOT", {})
    return f


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(tmux_mod.time, "monotonic", lambda: now[0])
    return now


def test_one_ps_for_all_windows(fake):
    ws = Tmux("main", socket="/nonexistent/sock").windows()
    assert fake.count("ps") == 1                          # было: по ps на окно
    ps = next(c for c in fake.calls if c[0] == "ps")
    assert ps[ps.index("-t") + 1] == "pts/1,pts/2,pts/3"
    one, two, three = ws
    assert one["cmd"] == "claude" and one["profile"] == "zai" and not one["stopped"]
    assert two["cmd"] == "bash" and not two["stopped"]     # не сессия пульта: метки нет
    assert three["cmd"] == "bash" and three["stopped"]      # метка есть, Claude нет — «остановлена»


def test_no_cache_by_default(fake, clock):
    t = Tmux("main", socket="/nonexistent/sock")
    t.windows()
    t.windows()
    assert fake.count("list-windows") == 2                # бот и проверки — как раньше, всегда свежий список


def test_ttl_cache_shared_and_expires(fake, clock, monkeypatch):
    monkeypatch.setattr(Tmux, "ttl", 2.0)
    a, b = Tmux("main", socket="/nonexistent/sock"), Tmux("main", socket="/nonexistent/sock")
    a.windows()
    clock[0] += 1.5
    ws = b.windows()                                       # другой объект того же сервера — из памяти
    assert fake.count("list-windows") == 1 and fake.count("ps") == 1
    ws[0]["name"] = "испорчено"                            # копия: правка ответа не портит запомненное
    assert a.windows()[0]["name"] == "one"
    clock[0] += 1.0
    a.windows()
    assert fake.count("list-windows") == 2                 # срок вышел — читаем заново


def test_mutation_forgets(fake, clock, monkeypatch):
    monkeypatch.setattr(Tmux, "ttl", 2.0)
    t = Tmux("main", socket="/nonexistent/sock")
    t.windows()
    t.screen("@1")                                         # чтение экрана — список не сбрасывает
    t.windows()
    assert fake.count("list-windows") == 1
    t.rename("@1", "новое")
    t.windows()
    assert fake.count("list-windows") == 2
    t.run("set-option", "-w", "-t", "@1", "@gas_pult", "claude")
    t.windows()
    assert fake.count("list-windows") == 3
    t.new_window("x", "/p", "true", mark="claude")
    t.windows()
    assert fake.count("list-windows") == 4


def test_other_server_not_shared(fake, clock, monkeypatch):
    monkeypatch.setattr(Tmux, "ttl", 2.0)
    Tmux("main", socket="/nonexistent/a").windows()
    Tmux("main", socket="/nonexistent/b").windows()
    assert fake.count("list-windows") == 2


def test_stale_read_during_mutation_not_cached(fake, clock, monkeypatch):
    """Список читали, а в это время соседний запрос открыл окно — такой список не запоминаем."""
    monkeypatch.setattr(Tmux, "ttl", 2.0)
    t = Tmux("main", socket="/nonexistent/sock")
    real = t._windows

    def slow():
        ws = real()
        clock[0] += 0.1
        t.forget()                                         # «соседний» new-window посреди чтения
        return ws
    monkeypatch.setattr(t, "_windows", slow)
    t.windows()
    monkeypatch.setattr(t, "_windows", real)
    t.windows()
    assert fake.count("list-windows") == 2


def test_serve_sets_ttl():
    from gas_pult import webapp
    assert webapp.WINDOWS_TTL and webapp.WINDOWS_TTL < 3      # меньше шага опроса браузера (3 с)
    assert Tmux.ttl == 0.0                                    # без serve() (тесты, бот) — без кэша


def test_branch_cached(monkeypatch):
    from gas_pult import webapp
    calls = []
    monkeypatch.setattr(webapp.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "main\n", ""))
    now = [50.0]
    monkeypatch.setattr(webapp.time, "monotonic", lambda: now[0])
    p = object.__new__(webapp.Panel)
    assert p.branch_of("/p") == "main" and p.branch_of("/p") == "main"
    assert len(calls) == 1
    now[0] += webapp.Panel.BRANCH_TTL + 1
    p.branch_of("/p")
    assert len(calls) == 2


def test_e2e_no_viewer_no_poll():
    """Браузер с подменой часов: скрыта — ноль опросов, 10 мин без касаний — раз в 30 с (tests/e2e/viewer_poll.py)."""
    import importlib.util
    import shutil
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from pathlib import Path

    from gas_pult import webapp

    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    web = Path(webapp.__file__).resolve().parent / "web"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(web)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    e2e = Path(__file__).resolve().parent / "e2e" / "viewer_poll.py"
    spec = importlib.util.spec_from_file_location("viewer_poll", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
