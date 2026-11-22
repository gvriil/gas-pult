"""Автовход коннекторов, фаза 2 (relogin.py): поддельный DevTools (подмена транспорта ``Browser.http`` / ``connect``)
и поддельная программа входа. Настоящий Chrome и настоящие claude, pi, opencode не трогаются."""

import json
import os
import sys
from pathlib import Path

import pytest

from gas_pult import cli, connwatch, relogin

SECRET = "Zq9-very-secret-Pass"
AUTH = "https://auth.example.org/authorize?client_id=c1&scope=read%20write&state=S1&code_challenge=X"
CONSENT = {"url": "https://auth.example.org/consent?scope=read+write", "ready": "complete",
           "btns": ["Cancel", "Allow"], "perms": ["Read your files", "Write your files"], "text": "App wants access"}
CALLBACK = {"url": "http://localhost:3118/callback?code=SECRETCODE&state=S1", "ready": "complete", "btns": []}
LOGIN_PAGE = {"url": "https://auth.example.org/login", "ready": "complete", "btns": ["Sign in"], "pw": True,
              "user": True, "text": "Sign in"}


class FakeConn:
    """Вкладка: страница — словарь снимка; щелчок по «Allow» и Enter на странице пароля ведут дальше."""

    def __init__(self, pages):
        self.pages, self.calls = list(pages), []

    @property
    def page(self):
        return self.pages[0]

    def call(self, method, **p):
        self.calls.append((method, p))
        if method == "Runtime.evaluate":
            e = p["expression"]
            if e == relogin.SNAP_JS:
                return {"result": {"value": json.dumps(self.page)}}
            if "scrollIntoView" in e:
                return {"result": {"value": [10, 20]}}
            if "e.focus()" in e:
                return {"result": {"value": True}}
        if method == "Input.dispatchMouseEvent" and p["type"] == "mouseReleased" and len(self.pages) > 1:
            self.pages.pop(0)
        if method == "Input.dispatchKeyEvent" and p["type"] == "keyUp" and len(self.pages) > 1:
            self.pages.pop(0)
        return {}

    def close(self):
        self.calls.append(("close", {}))

    def methods(self):
        return [m for m, _ in self.calls]


class FakeBrowser(relogin.Browser):
    def __init__(self, *pages):
        self.conn = FakeConn(pages)
        self.opened = []
        super().__init__(cdp="http://127.0.0.1:9", http=self.fake_http, connect=lambda ws: self.conn)

    def fake_http(self, path, method="GET"):
        if path.startswith("/json/new?"):
            self.opened.append(path)
            return {"id": "T1", "webSocketDebuggerUrl": "ws://127.0.0.1:9/devtools/page/T1"}
        return {}


class FakeLogin:
    def __init__(self, c, auth=AUTH, code=0):
        self.auth, self.code, self.clicked = auth, code, False

    def url(self):
        return self.auth

    def exit_code(self):
        return None

    def wait(self, timeout):
        return self.code


def ticks():
    t = [0.0]

    def clock():
        t[0] += 0.5
        return t[0]
    return clock


def go(page_list, approved=None, auth=AUTH, verify_state="ok", vault=None, harness="claude"):
    b = FakeBrowser(*page_list)
    c = {"harness": harness, "name": "linear", "state": "needs_auth", "detail": ""}
    r = relogin.run(c, approved, browser=b, start=lambda c: FakeLogin(c, auth),
                    verify=lambda h: [{"harness": h, "name": "linear", "state": verify_state}],
                    vault=vault or (lambda *a, **k: pytest.fail("пароль не нужен")), clock=ticks(),
                    sleep=lambda s: None)
    return r, b


def approved_fp(auth=AUTH):
    return relogin.fingerprint(CONSENT["url"], auth, CONSENT["perms"])


# ---------- согласие ----------
def test_first_time_does_not_click():
    r, b = go([CONSENT, CALLBACK])
    assert r.outcome == "needs_owner" and not r.done and "первый вход" in r.why
    assert "Input.dispatchMouseEvent" not in b.conn.methods()
    assert r.fp["host"] == "auth.example.org" and r.fp["scope"] == ["read", "write"]
    assert "уже открыта страница входа" in r.hint and b.opened                   # вкладка открыта и оставлена
    assert ("close", {}) in b.conn.calls and not any("/json/close" in p for p in b.opened)


def test_same_fingerprint_clicks_allow():
    r, b = go([CONSENT, CALLBACK], approved=approved_fp())
    assert r.outcome == "clicked" and r.done
    clicks = [p for m, p in b.conn.calls if m == "Input.dispatchMouseEvent"]
    assert [p["type"] for p in clicks] == ["mousePressed", "mouseReleased"]
    assert any('"Allow"' in p.get("expression", "") for m, p in b.conn.calls if m == "Runtime.evaluate")


def test_clicked_but_still_not_ok_is_failed():
    r, _ = go([CONSENT, CALLBACK], approved=approved_fp(), verify_state="needs_auth")
    assert r.outcome == "failed" and not r.done and "коннектор needs_auth" in r.why


def test_scope_changed_does_not_click():
    old = relogin.fingerprint(CONSENT["url"].replace("read+write", "read"), AUTH.replace("read%20write", "read"),
                              CONSENT["perms"])                       # раньше разрешали только read
    r, b = go([CONSENT, CALLBACK], approved=old)
    assert r.outcome == "needs_owner" and "права изменились" in r.why
    assert "Input.dispatchMouseEvent" not in b.conn.methods()
    assert r.fp["fp"] != old["fp"]


def test_perms_text_changed_does_not_click():
    page = {**CONSENT, "perms": ["Read your files", "Delete your files"]}
    r, b = go([page, CALLBACK], approved=approved_fp())
    assert r.outcome == "needs_owner" and "Input.dispatchMouseEvent" not in b.conn.methods()


def test_fingerprint_ignores_client_id_and_state():
    a = relogin.fingerprint(CONSENT["url"], AUTH, CONSENT["perms"])
    b = relogin.fingerprint(CONSENT["url"], AUTH.replace("c1", "c2").replace("S1", "S2"), CONSENT["perms"][::-1])
    assert a == b


@pytest.mark.parametrize("page,word", [
    ({**CONSENT, "captcha": True}, "капча"),
    ({**CONSENT, "btns": ["Verify"], "otp": True}, "двухфакторная"),
    ({**CONSENT, "btns": ["Next"], "text": "Enter the verification code we sent"}, "двухфакторная"),
])
def test_captcha_and_2fa_go_to_owner(page, word):
    r, b = go([page], approved=approved_fp())
    assert r.outcome == "needs_owner" and word in r.why
    assert "Input.dispatchMouseEvent" not in b.conn.methods()


def test_unknown_page_goes_to_owner():
    r, _ = go([{"url": "https://x.example/weird?token=abc", "ready": "complete", "btns": ["Next"]}])
    assert r.outcome == "needs_owner" and "не распознана" in r.why and "token=abc" not in r.why


def test_no_browser_is_failed_without_starting_login():
    b = relogin.Browser(cdp="http://127.0.0.1:9", http=lambda *a, **k: (_ for _ in ()).throw(relogin.Fail("нет")))
    c = {"harness": "claude", "name": "linear", "state": "needs_auth"}
    r = relogin.run(c, browser=b, start=lambda c: pytest.fail("программу входа не запускать"))
    assert r.outcome == "failed" and "браузер агента" in r.why


def test_failed_server_and_hermes_are_not_tried():
    r = relogin.run({"harness": "claude", "name": "x", "state": "failed"}, browser=object())
    assert r.outcome == "needs_owner"
    r = relogin.run({"harness": "hermes", "name": "x", "state": "needs_auth"}, browser=object())
    assert r.outcome == "needs_owner" and "hermes" in r.why


# ---------- пароль ----------
def vault_of(calls):
    def vault(entry, attr="password"):
        calls.append((entry, attr))
        return SECRET if attr == "password" else "owner@example.org"
    return vault


def test_google_domain_never_gets_password(monkeypatch):
    monkeypatch.setattr(relogin, "PASSWORD_SERVICES", {"google.com": "https://policies.google.com/terms"})
    page = {**LOGIN_PAGE, "url": "https://accounts.google.com/v3/signin?continue=x"}
    calls = []
    r, b = go([page], vault=vault_of(calls))
    assert r.outcome == "needs_owner" and "Google и Telegram" in r.why
    assert calls == [] and "Input.insertText" not in b.conn.methods()


def test_telegram_domain_never_gets_password(monkeypatch):
    monkeypatch.setattr(relogin, "PASSWORD_SERVICES", {"telegram.org": "https://telegram.org/tos"})
    r, b = go([{**LOGIN_PAGE, "url": "https://oauth.telegram.org/auth"}], vault=vault_of([]))
    assert r.outcome == "needs_owner" and "Input.insertText" not in b.conn.methods()


def test_password_service_not_listed_goes_to_owner():
    assert relogin.PASSWORD_SERVICES == {}                          # по умолчанию ни один сервис не проверен
    calls = []
    r, _ = go([LOGIN_PAGE], vault=vault_of(calls))
    assert r.outcome == "needs_owner" and "не в списке" in r.why and calls == []


def test_password_never_leaks(tmp_path, monkeypatch, capsys, caplog):
    """Пароль разрешённого сервиса: вводится только в DevTools; ни в события, ни в задачи, ни в состояние, ни в
    вывод, ни в журнал — проверка по всем записанным строкам."""
    monkeypatch.setattr(relogin, "PASSWORD_SERVICES", {"example.org": "https://example.org/terms"})
    caplog.set_level("DEBUG")
    calls, browsers = [], []

    def fn(c, approved=None):
        b = FakeBrowser(LOGIN_PAGE, CONSENT, CALLBACK)
        browsers.append(b)
        return relogin.run(c, approved, browser=b, start=lambda c: FakeLogin(c),
                           verify=lambda h: [{"harness": h, "name": "linear", "state": "ok"}],
                           vault=vault_of(calls), clock=ticks(), sleep=lambda s: None)

    w = connwatch.Watch(tmp_path, relogin_fn=fn)
    conn = {"harness": "claude", "name": "linear", "state": "needs_auth", "detail": ""}
    out = w.run([conn])                                    # первый раз: пароль введён, «Разрешить» — владельцу
    typed = [p["text"] for m, p in browsers[0].conn.calls if m == "Input.insertText"]
    assert typed == ["owner@example.org", SECRET] and ("claude/linear", "password") in calls
    w.run([{**conn, "state": "ok"}])                       # владелец разрешил — отпечаток запомнен
    out += w.run([conn])                                   # второй раз: пароль и «Разрешить» — сами
    assert "Input.dispatchMouseEvent" in browsers[1].conn.methods()
    assert any("вошёл автоматически" in x for x in out)
    printed = capsys.readouterr()
    everything = [printed.out, printed.err, caplog.text, *out]
    for p in Path(tmp_path).rglob("*"):
        if p.is_file():
            everything.append(p.read_text(encoding="utf-8", errors="replace"))
    assert everything and not any(SECRET in s for s in everything)
    assert not any("SECRETCODE" in s for s in everything)


# ---------- сторож: отпечаток после ручного успеха, событие ----------
def test_watch_remembers_after_manual_success_then_clicks(tmp_path):
    seen = []

    def fn(c, approved=None):
        seen.append(approved)
        return go([CONSENT, CALLBACK], approved=approved)[0]

    w = connwatch.Watch(tmp_path, relogin_fn=fn)
    conn = {"harness": "claude", "name": "linear", "state": "needs_auth", "detail": ""}
    w.run([conn])
    st = json.loads((tmp_path / "connwatch_state.json").read_text())
    assert "linear" in json.dumps(st["pending"]) and not st.get("approved")
    w.run([{**conn, "state": "ok"}])
    st = json.loads((tmp_path / "connwatch_state.json").read_text())
    assert st["approved"]["claude:linear"]["scope"] == ["read", "write"] and not st["pending"]
    acts = w.run([conn])
    assert seen[0] is None and seen[1]["fp"] == st["approved"]["claude:linear"]["fp"]
    assert "вошёл автоматически" in acts[0]
    evs = [json.loads(x) for x in (tmp_path / "chat-events.jsonl").read_text().splitlines()]
    rel = [e for e in evs if e["ev"] == "connector_relogin"]
    assert [e["result"] for e in rel] == ["needs_owner", "clicked"]
    assert set(rel[0]) == {"ts", "ev", "harness", "name", "result", "reason"}
    assert connwatch.forget(tmp_path, "claude:linear") == ["approved: claude:linear"]
    assert not json.loads((tmp_path / "connwatch_state.json").read_text())["approved"]


def test_event_reason_has_no_query(tmp_path):
    def fn(c, approved=None):
        return connwatch.Result(False, "ушёл на https://x.example/cb?code=SECRETCODE&state=1", "h",
                                outcome="failed")

    connwatch.Watch(tmp_path, relogin_fn=fn).run([{"harness": "pi", "name": "a", "state": "needs_auth"}])
    text = (tmp_path / "chat-events.jsonl").read_text()
    assert "SECRETCODE" not in text and "https://x.example/cb" in text


def test_disabled_in_config(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path))
    (tmp_path / "connwatch.toml").write_text("relogin = false\n")
    r = connwatch.relogin({"harness": "claude", "name": "x", "state": "needs_auth"})
    assert not r.done and r.outcome == "" and "выключен" in r.why


# ---------- программа входа в своём терминале (настоящий pty, безобидная команда) ----------
def test_login_hold_reads_url_from_pty(tmp_path, monkeypatch):
    monkeypatch.setitem(relogin.LOGIN, "claude", ["sh", "-c", "test -t 0 && echo 'Open: " + AUTH + "' && sleep 0.3"])
    lg = relogin.Login({"harness": "claude", "name": "x"}, data=tmp_path)
    assert lg.url(timeout=10) == AUTH                                  # stdin — терминал (иначе claude сдаётся)
    assert lg.wait(10) == 0
    assert oct(lg.out.stat().st_mode & 0o777) == "0o600"
    assert (tmp_path / "relogin" / "bin" / "xdg-open").exists()


def test_scrub_and_domains():
    assert relogin.scrub("go https://a.example/cb?code=1#x now") == "go https://a.example/cb now"
    assert relogin.domain_in("accounts.google.com", relogin.NEVER_PASSWORD)
    assert not relogin.domain_in("notgoogle.com", relogin.NEVER_PASSWORD)
    assert relogin.kind(CALLBACK) == "callback" and relogin.kind(CONSENT) == "consent"
    assert relogin.allow_buttons({"btns": ["Allow", "Don't allow", "Разрешить", "Continue"]}) == ["Allow", "Разрешить"]


# ---------- dry-run таймера ----------
def test_install_dry_run_changes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(connwatch, "RUN", lambda *a, **k: pytest.fail("в --dry-run ничего не запускать"))
    cli.main(["connectors", "watch", "--install", "--dry-run"])
    out = capsys.readouterr().out
    assert "было бы" in out and "enable --now gas-pult-connwatch.timer" in out and "записать" in out
    assert not (tmp_path / ".config").exists()
    cli.main(["connectors", "watch", "--uninstall", "--dry-run"])
    assert "disable --now" in capsys.readouterr().out


def test_unit_keeps_login_alive():
    assert "KillMode=process" in connwatch.units(python=sys.executable, path_env="/usr/bin", src="")[
        "gas-pult-connwatch.service"]
    assert os.path.basename(relogin.__file__) == "relogin.py"
