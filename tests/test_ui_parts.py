"""Части интерфейса по требованию (#191, образец bb — docs/ui-code-splitting.md): нативные ES-модули без сборщика.

Шаг 1: демо (~130 КБ) — в ``web/js/demo.js``; обычный вход его не качает, ``?demo`` грузит через ``part("demo")``.
Сервер отдаёт части с gzip и ETag; версия страницы (``build``) учитывает и части."""

import gzip
import urllib.request
from pathlib import Path

from test_project_chats import server as server

from gas_pult import webapp

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
DEMO = (WEB / "js" / "demo.js").read_text(encoding="utf-8")


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_demo_is_a_part_not_in_core():
    assert "function demoApi(" not in INDEX and "function demoApi(" in DEMO
    assert "Object.assign(window, { DEMO_PERSONAS" in DEMO                # ядро видит функции демо через window
    assert 'if (DEMO) part("demo");' in INDEX and 'if (DEMO && !window.demoApi) await part("demo");' in INDEX
    assert "import(`/js/${name}.js`)" in INDEX and "[500, 1500]" in INDEX # загрузка с двумя повторами, как у bb
    assert len(INDEX.encode()) < 760_000                                   # ядро меньше прежних 866 КБ


def test_part_served_with_gzip_and_etag(server):
    _p, base, *_ = server
    st, h, body = get(base + "/js/demo.js")
    assert st == 200 and h["Content-Type"].startswith("text/javascript") and body == DEMO.encode()
    st, h, gz = get(base + "/js/demo.js", {"Accept-Encoding": "gzip"})
    assert h["Content-Encoding"] == "gzip" and gzip.decompress(gz) == DEMO.encode()
    assert get(base + "/js/demo.js", {"If-None-Match": h["ETag"]})[0] == 304
    for bad in ("/js/../webapp.py", "/js/nope.js", "/js/Demo.js", "/js/demo.js.map"):
        assert get(base + bad)[0] == 404, bad


def test_part_names():
    assert webapp.PART_PATH.fullmatch("/js/demo.js") and not webapp.PART_PATH.fullmatch("/js/../x.js")
    assert not webapp.PART_NAME.fullmatch("../x") and webapp.PART_NAME.fullmatch("voice-player")
