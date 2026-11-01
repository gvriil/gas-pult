from pathlib import Path

import pytest

from gas_pult import webapp
from gas_pult.config import Config


@pytest.fixture
def panel(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    p.people.accept(1)                     # условия использования приняты
    p.people.set_country(1, chosen="NL")   # и страна выбрана
    cmds = [{"i": 0, "cmd": "ls", "kind": "local", "danger": False, "sha": "aaa"},
            {"i": 1, "cmd": "rm -rf build", "kind": "local", "danger": True, "sha": "bbb"},
            {"i": 2, "cmd": "brew install x", "kind": "foreign", "danger": False, "sha": "ccc"}]
    monkeypatch.setattr(p, "commands", lambda w: cmds)
    monkeypatch.setattr(webapp, "execute", lambda cmd, cwd: (0, 0.1, f"ran {cmd}"))
    monkeypatch.setattr(webapp.setup, "installed", lambda claude="claude": "/usr/bin/claude")   # в CI Claude Code нет
    return p


W = {"id": "@1", "path": "/tmp"}


def test_run_ok(panel):
    assert panel.run(W, 0, "aaa", False) == {"code": 0, "seconds": 0, "out": "ran ls", "cut": False,
                                             "triage": "", "triage_to": ""}


def test_run_rejects_changed_answer(panel):
    with pytest.raises(ValueError, match="изменился"):
        panel.run(W, 0, "zzz", False)          # отпечаток не совпал — браузер не подсунет свою команду


def test_run_danger_needs_confirm(panel):
    assert panel.run(W, 1, "bbb", False) == {"confirm": True}
    assert panel.run(W, 1, "bbb", True)["out"] == "ran rm -rf build"


def test_run_foreign_refused(panel):
    with pytest.raises(ValueError, match="вручную"):
        panel.run(W, 2, "ccc", True)


def test_upload_sanitizes_name(panel, tmp_path):
    p = panel.upload("..%2F..%2Fetc%2Fpasswd фото.jpg", b"x")
    assert p.startswith(str(tmp_path / "inbox")) and "/etc/" not in p.split("inbox")[1]
    assert Path(p).read_bytes() == b"x"


def test_find_auth_joins_wrapped_url():
    from gas_pult.webapp import find_auth
    lines = ["   Authenticating with notion…",
             "   If your browser doesn't open automatically, copy this URL manually (c to copy)",
             "   https://mcp.notion.com/authorize?response_type=code&client_id=x&code_challe",
             "   nge_method=S256&redirect_uri=http%3A%2F%2Flocalhost%3A49442%2Fcallback&state=abc",
             "   If the redirect page shows a connection error, paste the URL from your browser's address bar:",
             "   URL >"]
    a = find_auth(lines)
    assert a["service"] == "notion" and a["paste"]
    assert a["url"].endswith("callback&state=abc") and "code_challenge_method=S256" in a["url"]
    assert find_auth(["❯ ", "просто экран"]) is None


def test_key_allows_ctrl_c_only_from_list(panel, monkeypatch):
    sent = []
    monkeypatch.setattr(panel.tmux, "keys", lambda wid, k: sent.append(k))
    monkeypatch.setattr(panel.tmux, "screen", lambda wid, n: ["ok"])
    monkeypatch.setattr(webapp.time, "sleep", lambda s: None)
    assert panel.key(W, "C-c") == ["ok"] and sent == ["C-c"]
    with pytest.raises(ValueError):
        panel.key(W, "C-d")


def test_preview_cached_by_revision(panel, monkeypatch):
    calls = []
    monkeypatch.setattr(webapp.transcripts, "preview", lambda path: calls.append(path) or "строка")
    assert panel.preview("/p", "r1") == "строка" and panel.preview("/p", "r1") == "строка"
    panel.preview("/p", "r2")
    assert calls == ["/p", "/p"]


def test_new_reuses_window_in_same_folder(panel, monkeypatch):
    monkeypatch.setattr(panel.pult, "projects", lambda: ["/p/a", "/p/b"])
    monkeypatch.setattr(panel.pult, "project_window",
                        lambda path: {"id": "@7", "name": "a-0900"} if path == "/p/a" else None)
    monkeypatch.setattr(panel.tmux, "new_window", lambda name, path, cmd, **kw: "@9")
    monkeypatch.setattr(panel.pult, "set_state", lambda **kw: None)
    assert panel.new(0) == {"id": "@7", "existing": "a-0900"}
    assert panel.new(1) == {"id": "@9"}


def test_new_session_in_profile_and_restart(panel, monkeypatch):
    opened = []
    monkeypatch.setattr(panel.pult, "projects", lambda: ["/p/a"])
    monkeypatch.setattr(panel.pult, "project_window", lambda path: None)
    monkeypatch.setattr(panel.pult, "set_state", lambda **kw: None)
    monkeypatch.setattr(panel.tmux, "new_window",
                        lambda name, path, cmd, **kw: opened.append((name, path, cmd)) or "@9")
    monkeypatch.setattr(webapp.models, "command", lambda base, profile, st: f"{base} [{profile or 'claude'}]")
    assert panel.new(0, "zai") == {"id": "@9"} and opened[-1][2] == "claude [zai]"
    monkeypatch.setattr(panel, "close", lambda w: "Claude не вышел (возможно, занят) — посмотрите экран")
    with pytest.raises(ValueError, match="не вышел"):
        panel.restart({"id": "@1", "name": "a-0900", "path": "/p/a"}, "deepseek")
    monkeypatch.setattr(panel, "close", lambda w: "закрыто")
    assert panel.restart({"id": "@1", "name": "a-0900", "path": "/p/a"}, "deepseek") == {"id": "@9"}
    assert opened[-1] == ("a-0900", "/p/a", "claude [deepseek] --continue")      # по умолчанию разговор продолжается
    panel.restart({"id": "@1", "name": "a-0900", "path": "/p/a"}, "zai", keep=False)
    assert opened[-1][2] == "claude [zai]"


def test_model_key_saved_without_voice_reset(panel, monkeypatch):
    saved, state = {}, {}
    monkeypatch.setattr(webapp.providers, "check_model_key", lambda p, k: True)
    monkeypatch.setattr(webapp.providers, "save_key", lambda p, k: saved.__setitem__(p, k))
    monkeypatch.setattr(panel.pult, "set_state", lambda **kw: state.update(kw))
    assert panel.set_key("deepseek", " sk-0123456789abcdef ") == {"checked": True}
    assert saved == {"deepseek": "sk-0123456789abcdef"}
    with pytest.raises(ValueError, match="не похоже"):
        panel.set_key("zai", "short")
    panel.remove_key("deepseek")
    assert "tts_provider" not in state                     # голос не сбрасывается из-за ключа модели


def test_effort_only_known_levels(panel, monkeypatch):
    sent = []
    monkeypatch.setattr(panel, "slash", lambda w, cmd: sent.append(cmd) or ["ok"])
    assert panel.effort(W, "xhigh") == ["ok"] and sent == ["/effort xhigh"]
    with pytest.raises(ValueError):
        panel.effort(W, "xhigh; rm -rf /")


def test_service_worker_served_from_root(panel):
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/sw.js")
        assert r.headers["Content-Type"].startswith("text/javascript") and b"notificationclick" in r.read()
    finally:
        srv.shutdown()


def test_stopped_session_listed_and_revived(panel, monkeypatch):
    stopped = {"id": "@3", "name": "shop", "path": "/tmp", "cmd": "zsh", "mark": "zai", "stopped": True,
               "channel": False, "profile": ""}
    monkeypatch.setattr(panel.tmux, "windows", lambda: [stopped])
    monkeypatch.setattr(panel.tmux, "window", lambda wid: stopped if wid == "@3" else None)
    s = panel.sessions()
    assert s[0]["status"] == "stopped" and s[0]["profile"] == "zai"
    calls = []
    monkeypatch.setattr(webapp.models, "command", lambda base, profile, st: f"claude [{profile}]")
    monkeypatch.setattr(panel.tmux, "respawn", lambda wid, path, cmd, mark: calls.append((wid, cmd, mark)))
    monkeypatch.setattr(panel.pult, "set_state", lambda **kw: None)
    assert panel.revive("@3") == {"id": "@3"}
    assert calls == [("@3", "claude [zai] --continue", "zai")]     # тот же поставщик, разговор продолжается
    with pytest.raises(ValueError):
        panel.revive("@9")


class Menu:
    """Меню Claude на экране: стрелки двигают ❯, Enter выбирает; цифры меню не принимает. Выше — ваше прошлое
    сообщение с «❯ 1. …», как Claude Code показывает историю."""
    def __init__(self, sel=1):
        self.sel, self.keys_sent, self.chosen = sel, [], None

    def screen(self, wid, n=25):
        opts = [f" {'❯' if i == self.sel else ' '} {i}. Вариант {i}" for i in (1, 2, 3)]
        return ["❯ 1. Мой пункт из прошлого сообщения", "● ответ", " Какой вариант?", *opts,
                " Enter to select · ↑/↓ to navigate · Esc to cancel"]

    def keys(self, wid, *keys):
        self.keys_sent += keys
        for k in keys:
            self.sel = max(1, self.sel - 1) if k == "Up" else min(3, self.sel + 1) if k == "Down" else self.sel
            if k == "Enter":
                self.chosen = self.sel


@pytest.fixture
def menu(panel, monkeypatch):
    m = Menu()
    panel.tmux = m
    monkeypatch.setattr(webapp.time, "sleep", lambda s: None)
    return m


def test_tap_highlights_without_choosing(panel, menu):
    lines = panel.select(W, "", "3", go=False)
    assert menu.sel == 3 and menu.chosen is None and "Enter" not in menu.keys_sent
    assert any(x.startswith(" ❯ 3.") for x in lines)


def test_second_tap_chooses_by_arrows_not_digit(panel, menu):
    panel.select(W, "", "2")
    assert menu.chosen == 2 and menu.keys_sent == ["Down", "Enter"]       # цифру «2» не шлём


def test_old_message_with_number_is_not_the_menu(panel, menu):
    menu.sel = 3
    panel.select(W, "", "1")                       # «❯ 1. …» выше — ваше сообщение, не пункт меню
    assert menu.chosen == 1 and menu.keys_sent == ["Up", "Up", "Enter"]
def test_same_message_id_is_pasted_once(panel, monkeypatch):
    pasted = []
    monkeypatch.setattr(panel.pult, "to_claude", lambda w, text: pasted.append(text))
    assert panel.send(W, "привет", "m1") is False
    assert panel.send(W, "привет", "m1") is True            # браузер повторил после обрыва — не вставляем
    panel.send(W, "привет", "m2")
    panel.send(W, "привет")                                  # без id — как раньше
    assert pasted == ["привет", "привет", "привет"]


def test_retry_during_slow_paste_waits_for_first(panel, monkeypatch):
    import threading
    import time as t
    pasted, go = [], threading.Event()
    monkeypatch.setattr(panel.pult, "to_claude", lambda w, text: go.wait(2) and pasted.append(text))
    first = threading.Thread(target=panel.send, args=(W, "привет", "m1"))
    first.start()
    t.sleep(0.1)
    res = []
    retry = threading.Thread(target=lambda: res.append(panel.send(W, "привет", "m1")))
    retry.start()
    t.sleep(0.1)
    go.set()
    first.join(2)
    retry.join(2)
    assert pasted == ["привет"] and res == [True]


def test_failed_paste_can_be_retried(panel, monkeypatch):
    calls = []

    def flaky(w, text):
        calls.append(text)
        if len(calls) == 1:
            raise ValueError("окно не готово")

    monkeypatch.setattr(panel.pult, "to_claude", flaky)
    with pytest.raises(ValueError):
        panel.send(W, "привет", "m1")
    assert panel.send(W, "привет", "m1") is False and calls == ["привет", "привет"]   # не дошло — повтор вставляет


def test_window_name_rules():
    from gas_pult.tmux import window_name
    assert window_name("  магазин   бот ") == "магазин бот"
    for bad in ("", "   ", "a:b", "v1.2", "x" * 41):
        with pytest.raises(ValueError):
            window_name(bad)


def test_rename_runs_tmux_on_own_server(panel, monkeypatch):
    calls = []
    import gas_pult.tmux as tm
    ok = tm.subprocess.CompletedProcess
    monkeypatch.setattr(tm.subprocess, "run", lambda args, **kw: calls.append(args) or ok(args, 0, "", ""))
    assert panel.tmux.rename("@3", "shop") == "shop"
    assert calls[-1][-4:] == ["rename-window", "-t", "@3", "shop"] and "-S" in calls[-1]    # тесты — на своём сокете


@pytest.fixture
def logged(panel, monkeypatch, tmp_path):
    items = {"c1": {"id": "c1", "cmd": "ls", "kind": "local", "danger": False, "path": "/tmp", "ts": "1", "n": 0,
                    "done": None},
             "c2": {"id": "c2", "cmd": "rm -rf build", "kind": "local", "danger": True, "path": "/tmp", "ts": "2",
                    "n": 0, "done": None},
             "c3": {"id": "c3", "cmd": "brew up", "kind": "foreign", "danger": False, "path": "/tmp", "ts": "3",
                    "n": 0, "done": None}}
    panel.journal.save({"items": items, "revs": {}})
    monkeypatch.setattr(panel.tmux, "windows", lambda: [])
    return panel


def test_command_run_marks_done_with_exit_code(logged):
    r = logged.command_run("c1", False)["item"]
    assert r["done"]["code"] == 0 and r["done"]["out"] == "ran ls"
    assert logged.journal.get("c1")["done"]["code"] == 0


def test_command_run_danger_and_foreign(logged):
    assert logged.command_run("c2", False) == {"confirm": True}
    assert logged.journal.get("c2")["done"] is None
    with pytest.raises(ValueError, match="вручную"):
        logged.command_run("c3", True)


def test_command_mark_by_hand_is_separate_and_undo(logged):
    item = logged.command_mark("c3", True)["item"]
    assert item["manual"]["at"] and item["done"] is None                 # ручная отметка — не «запуск»
    assert logged.command_mark("c3", False)["item"]["manual"] is None
    logged.command_run("c1", False)
    item = logged.command_mark("c1", True)["item"]
    assert item["done"]["code"] == 0 and item["manual"]                  # итог запуска не стирается


def test_command_shows_running_while_executing(logged, monkeypatch):
    from gas_pult import webapp as wa
    seen = []
    monkeypatch.setattr(wa, "execute", lambda cmd, cwd: seen.append(logged.journal.get("c1")["running"]) or (0, 1, ""))
    item = logged.command_run("c1", False)["item"]
    assert seen[0] and item["running"] is None and item["done"]["code"] == 0


def test_old_hand_mark_becomes_manual(logged):
    d = logged.journal.load()
    d["items"]["c2"]["done"] = {"code": None, "by": "hand", "at": "2026-11-01 10:00"}
    logged.journal.save(d)
    c = logged.journal.get("c2")
    assert c["done"] is None and c["manual"] == {"at": "2026-11-01 10:00"}


def test_command_log_hides_paths_from_non_owner(logged):
    assert all("path" in c for c in logged.command_log(True)["items"])
    assert not any("path" in c for c in logged.command_log(False)["items"])


def test_prompt_hint_parsing():
    from gas_pult.tmux import prompt_hint
    box = "\x1b[38;5;246m────────\x1b[39m"
    real = ["● Готово.", box, "\x1b[39m❯ \x1b[2mзапусти тесты и закоммить\x1b[22m", box, "  ⏵⏵ auto mode on"]
    assert prompt_hint(real) == "запусти тесты и закоммить"
    stub = "\x1b[39m❯\u00a0 \x1b[2mTry \"fix typecheck errors\""
    assert prompt_hint(["● x", box, stub, box]) == ""                                # общая заглушка
    assert prompt_hint(["● x", box, "\x1b[39m❯\u00a0мой текст", box]) == ""        # набранное — не подсказка
    assert prompt_hint(["\x1b[2m❯ 1. Да\x1b[22m", "  2. Нет"]) == ""               # меню — не строка ввода


def test_failed_command_in_tab_is_triaged_and_full_output_kept(logged, monkeypatch):
    from gas_pult import webapp as wa
    big = "\n".join(f"line {i}" for i in range(2000))
    monkeypatch.setattr(wa, "execute", lambda cmd, cwd: (2, 0.1, big))
    monkeypatch.setattr(logged.pult, "triage", lambda path, wid, cmd, code, out, paste=None: ("sent", "alpha"))
    item = logged.command_run("c1", False)["item"]
    assert item["done"]["code"] == 2 and item["done"]["triage"] == "sent" and item["done"]["triage_to"] == "alpha"
    assert item["done"]["cut"] and logged.journal.output("c1") == big       # весь вывод — для «Копировать»
    assert logged.journal.output("../../etc/passwd") is None


def test_chat_block_run_returns_full_output_when_cut(panel, monkeypatch):
    big = "y" * 5000
    monkeypatch.setattr(webapp, "execute", lambda cmd, cwd: (0, 0.1, big))
    monkeypatch.setattr(panel.tmux, "windows", lambda: [])
    r = panel.run(W, 0, "aaa", False)
    assert r["cut"] and r["full"] == big and len(r["out"]) < len(big)
