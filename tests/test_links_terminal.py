"""Ссылки и терминал (владелец 17.11): «Где открыть?» — в Ubuntu (вкладка Chrome рабочего стола по CDP) или здесь,
выбор запоминается по сайту; «Терминал» рядом с «Ubuntu» — окно ubuntu-shell. Только владельцу; адрес — только http(s);
открытие вкладки и окна — с кодом подтверждения (CONFIRM)."""

import json
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from test_project_chats import call
from test_project_chats import server as server

from gas_pult import webapp

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"


def fake_cdp():
    """Подделка Chrome DevTools: PUT /json/new?<адрес> → {id, url}; помнит, что открыли."""
    got = []

    class H(BaseHTTPRequestHandler):
        def do_PUT(self):
            got.append(self.path)
            body = json.dumps({"id": "T1", "url": self.path.split("?", 1)[1]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, got


def test_desktop_tab_only_http_and_cdp_call():
    srv, got = fake_cdp()
    try:
        cdp = f"http://127.0.0.1:{srv.server_address[1]}"
        d = webapp.desktop_tab("https://example.com/a?b=1&c=д", cdp)
        assert d["ok"] and got == ["/json/new?https://example.com/a?b=1&c=%D0%B4"]
        for bad in ("javascript:alert(1)", "file:///etc/passwd", "chrome://settings", "https://x.y/a b", "ftp://x"):
            with pytest.raises(ValueError):
                webapp.desktop_tab(bad, cdp)
        assert len(got) == 1
    finally:
        srv.shutdown()
    with pytest.raises(ValueError, match="9222"):
        webapp.desktop_tab("https://example.com", "http://127.0.0.1:9")    # Chrome не запущен — понятная ошибка


def test_link_prefs_per_site(tmp_path):
    assert webapp.link_prefs(tmp_path) == {}
    assert webapp.link_pref_set(tmp_path, "GitHub.com", "desk") == {"github.com": "desk"}
    webapp.link_pref_set(tmp_path, "pult.example.su:8443", "here")
    assert webapp.link_prefs(tmp_path) == {"github.com": "desk", "pult.example.su:8443": "here"}
    assert oct((tmp_path / "link_open.json").stat().st_mode)[-3:] == "600"
    assert webapp.link_pref_set(tmp_path, "github.com", None) == {"pult.example.su:8443": "here"}    # «Забыть»
    for host, where in (("bad host", "desk"), ("a.ru", "everywhere")):
        with pytest.raises(ValueError):
            webapp.link_pref_set(tmp_path, host, where)


class Tm:
    session = "main"

    def __init__(self):
        self.wins, self.ran = [{"id": "@1", "name": "gp-term"}], []

    def windows(self):
        return list(self.wins)

    def run(self, *a):
        self.ran.append(a)
        self.wins.append({"id": "@7", "name": a[a.index("-n") + 1]})
        return "@7\n"


def test_shell_window_created_once_and_gp_term_untouched():
    t = Tm()
    assert webapp.shell_window(t) == "@7" and webapp.shell_window(t) == "@7"
    assert len(t.ran) == 1 and "-d" in t.ran[0] and t.ran[0][-1] == "bash -l" and "ubuntu-shell" in t.ran[0]
    assert t.wins[0] == {"id": "@1", "name": "gp-term"}                       # окно «Выполнить» не тронуто


def test_routes_owner_only_and_confirm(server):
    p, base, *_ = server
    member = p.auth.issue(2)
    for path, body in (("/api/desktop/url", {"url": "https://example.com"}), ("/api/shell/open", {}),
                       ("/api/links/prefs", {"host": "a.ru", "open": "desk"})):
        assert call(base, path, body, member)[0] == 403, path
    assert call(base, "/api/links/prefs", tok=member)[0] == 403
    assert {"/api/desktop/url", "/api/shell/open"} <= webapp.CONFIRM                 # с кодом подтверждения
    owner = p.auth.issue(1)
    code, d = call(base, "/api/links/prefs", {"host": "a.ru", "open": "here"}, owner)[:2]
    assert code == 200 and d["sites"] == {"a.ru": "here"}
    assert call(base, "/api/links/prefs", tok=owner)[1]["sites"] == {"a.ru": "here"}


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def test_e2e_link_sheet_remembers_site():
    sync_api = pytest.importorskip("playwright.sync_api")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_api.sync_playwright() as p:
            br = p.chromium.launch()
            pg = br.new_page(viewport={"width": 390, "height": 844})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&dev&open=@1&noscroll")
            pg.wait_for_selector("#content .msg")
            # демо — без шторки (как сейчас); включаем «владельца с рабочим столом» вручную и подменяем сеть
            pg.evaluate("""() => { meta.role = 'owner'; meta.desktop = true; window.__calls = [];
              window.deskLinks = () => true;
              window.api = async (path, body) => { __calls.push([path, body || null]);
                if (path === '/api/links/prefs')
                  return { sites: body ? (body.open ? { [body.host]: body.open } : {}) : {} };
                return { ok: true }; };
              window.open = (u) => __calls.push(['open', u]); }""")
            pg.evaluate("part('links').then(() => linkChoose('https://example.com/x'))")
            pg.wait_for_selector("[data-lw=here]")
            assert pg.is_checked("#lwMem")                                     # «Запомнить» — по умолчанию да
            pg.click("[data-lw=here]")
            pg.wait_for_function("__calls.some((c) => c[0] === 'open')")
            calls = pg.evaluate("__calls")
            assert ["/api/links/prefs", {"host": "example.com", "open": "here"}] in calls
            # второй раз тот же сайт — без вопроса
            pg.evaluate("__calls = []; linkChoose('https://example.com/y')")
            pg.wait_for_function("__calls.some((c) => c[0] === 'open')")
            assert pg.locator("[data-lw]").count() == 0
            assert not errs, errs
            br.close()
    finally:
        srv.shutdown()
