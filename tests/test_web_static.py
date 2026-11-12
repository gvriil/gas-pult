"""Файлы интерфейса рядом с index.html (разбиение пульта на модули, шаг 1): /js/… и /css/… с версией и кэшем,
сборка исходника для тестов (tests/websrc.py)."""

import hashlib
import re
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from websrc import WEB, web_source

from gas_pult import webapp
from gas_pult.config import Config

PAGE = ('<!doctype html><html><head><link rel="stylesheet" href="/css/tokens.css">\n<link rel="stylesheet" '
        'href="/css/base.css"></head><body><p>x</p>\n'
        '<script defer src="/js/core/store.js"></script>\n<script>\nconst inline = 1;\n</script></body></html>')


@pytest.fixture
def web(tmp_path):
    w = tmp_path / "web"
    (w / "js" / "core").mkdir(parents=True)
    (w / "css").mkdir()
    (w / "index.html").write_text(PAGE, encoding="utf-8")
    (w / "css" / "tokens.css").write_text(":root { --a: 1px; }\n", encoding="utf-8")
    (w / "css" / "base.css").write_text("p { margin: 0; }\n", encoding="utf-8")
    (w / "js" / "core" / "store.js").write_text("const store = 1;\n", encoding="utf-8")
    (w / "js" / "extra.js").write_text("const extra = 2;\n", encoding="utf-8")
    (w / "js" / "notes.txt").write_text("не интерфейс", encoding="utf-8")
    return w


def ver(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:10]


def test_assets_found_with_version(web):
    a = webapp.web_assets(web)
    assert sorted(a) == ["/css/base.css", "/css/tokens.css", "/js/core/store.js", "/js/extra.js"]
    assert a["/js/core/store.js"] == (b"const store = 1;\n", ver(web / "js" / "core" / "store.js"))
    page = webapp.link_assets(PAGE.encode(), a).decode()
    assert f'href="/css/tokens.css?v={ver(web / "css" / "tokens.css")}"' in page
    assert f'src="/js/core/store.js?v={ver(web / "js" / "core" / "store.js")}"' in page
    assert re.sub(r"\?v=[0-9a-f]{10}", "", page) == PAGE                  # других подстановок нет
    assert webapp.link_assets(b'<script src="/js/gone.js"></script>', a) == b'<script src="/js/gone.js"></script>'


def test_build_covers_page_and_files(web):
    page = (web / "index.html").read_bytes()
    a = webapp.web_assets(web)
    assert webapp.web_build(page, {}) == hashlib.sha256(page).hexdigest()[:12]      # без файлов — как раньше
    b1 = webapp.web_build(page, a)
    (web / "js" / "extra.js").write_text("const extra = 3;\n", encoding="utf-8")
    assert webapp.web_build(page, webapp.web_assets(web)) != b1      # поменялся только файл — версия другая


def get(base: str, path: str):
    try:
        r = urllib.request.urlopen(base + path)
    except urllib.error.HTTPError as e:
        r = e
    return r.status if hasattr(r, "status") else r.code, r.read(), r.headers


def test_server_serves_files_with_cache(web):
    panel = webapp.Panel(Config(token="1:T", owners=[1]))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel, web))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        v = ver(web / "js" / "core" / "store.js")
        st, body, h = get(base, "/")
        assert st == 200 and f'src="/js/core/store.js?v={v}"'.encode() in body
        assert h["Cache-Control"] == "no-store"                              # страница — как раньше
        st, body, h = get(base, f"/js/core/store.js?v={v}")
        assert st == 200 and body == b"const store = 1;\n"
        assert h["Content-Type"] == "text/javascript; charset=utf-8" and h["X-Content-Type-Options"] == "nosniff"
        assert h["Cache-Control"] == "public, max-age=31536000, immutable"
        assert h.get_all("Cache-Control") == ["public, max-age=31536000, immutable"]   # без второго no-store
        st, _, h = get(base, "/css/tokens.css")                              # без версии — каждый раз сверяться
        assert st == 200 and h["Content-Type"] == "text/css; charset=utf-8" and h["Cache-Control"] == "no-cache"
        assert get(base, "/js/core/store.js?v=0000000000")[2]["Cache-Control"] == "no-cache"
        for bad in ("/js/notes.txt", "/js/../index.html", "/js/missing.js", "/css/x.css/../../index.html"):
            st, body, h = get(base, bad)                                     # только известные файлы, без «..»
            assert b"const store" not in body and h.get("Cache-Control") != "public, max-age=31536000, immutable", bad
    finally:
        srv.shutdown()


def test_web_source_inlines_files_in_order(web):
    src = web_source(web)
    assert '<style>\n:root { --a: 1px; }\np { margin: 0; }\n</style>' in src      # подряд — один блок, как было
    assert "<script>\nconst store = 1;\n</script>\n<script>\nconst inline" in src   # свой встроенный — не сливается
    assert src.index("--a: 1px") < src.index("const store") < src.index("const inline")
    assert src.rstrip().endswith("const extra = 2;")                     # не подключён — всё равно виден тестам
    assert "notes.txt" not in src


def test_page_links_only_existing_files():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    for ref in re.findall(r'<(?:script|link)\b[^>]*\b(?:src|href)="/((?:js|css)/[^"?]+)"', page):
        assert (WEB / ref).is_file(), f"index.html подключает {ref}, а файла нет"
    assert "?v=" not in page                     # версию дописывает сервер при отдаче, в исходнике её нет


def test_every_file_is_linked_in_cascade_order():
    """Каждый web/css/*.css подключён в <head> ровно один раз; tokens.css — первым (на токенах стоит всё остальное)."""
    page = (WEB / "index.html").read_text(encoding="utf-8")
    head = page[:page.index("</head>")]
    linked = re.findall(r'<link rel="stylesheet" href="/(css/[\w/.-]+\.css)">', head)
    files = sorted(p.relative_to(WEB).as_posix() for p in WEB.glob("css/**/*.css"))
    assert sorted(linked) == files and len(set(linked)) == len(linked)
    if linked:
        assert linked[0] == "css/tokens.css"
    assert "<style>" not in page                  # стили — только в файлах (кэшируются), не в странице
    scripts = re.findall(r'<script\b[^>]*\bsrc="/(js/[\w/.-]+\.js)"', page)
    assert sorted(scripts) == sorted(p.relative_to(WEB).as_posix() for p in WEB.glob("js/**/*.js"))
    assert len(set(scripts)) == len(scripts)


def test_demo_data_before_main_script_and_only_functions():
    """demoApi зовётся уже из start() при загрузке — demo.js обычным (не defer) скриптом перед основным; в нём
    только объявления функций: порядок выполнения не важен, переменных основного скрипта он не трогает."""
    page = (WEB / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<script src="/js/demo\.js"></script>\n(<script src="/js/[\w/.-]+"></script>\n)*<script>\n', page)
    demo = (WEB / "js" / "demo.js").read_text(encoding="utf-8")
    top = [x for x in demo.split("\n") if x and not x.startswith((" ", "}", "//"))]
    assert top and all(re.match(r"(async )?function \w+\(", x) for x in top), top[:3]
    assert "function demoApi(" in demo and "function demoApi(" not in page


# Порядок файлов = порядок выполнения (обычные <script> перед основным встроенным): переносятся непрерывные куски
# основного скрипта сверху вниз, так что порядок кода — прежний. Новый файл — сюда, на своё место.
SCRIPTS = [
    "demo", "core/store", "core/i18n", "core/ui", "core/api",
    "nav",
    "shell",
    "login",
    "home",
    "terminal",
    "usage",
    "projects",
    "chat",
    "activity",
    "commands",
    "voice",
    "input",
    "integrations",
    "settings",
]


def test_scripts_before_main_in_order():
    """Ядро (шаг 4): store (общее состояние и store()), i18n (словарь), ui (значки, тема, ссылки, шторки, toast),
    api (сеть); дальше — разделы основного скрипта (шаг 5) в прежнем порядке."""
    page = (WEB / "index.html").read_text(encoding="utf-8")
    assert re.findall(r'<script src="/js/([\w/.-]+)\.js"></script>', page) == SCRIPTS
    assert not re.search(r"<script[^>]*\b(defer|async)\b[^>]*src=\"/js/", page)   # пока основной встроен — без defer
    assert f'<script src="/js/{SCRIPTS[-1]}.js"></script>\n<script>\n' in page        # сразу за ними — основной


def test_load_order_no_forward_calls():
    """Верхний уровень каждого файла при загрузке не вызывает функций из более поздних файлов (tests/jsorder.py)."""
    from jsorder import check
    assert check(WEB) == []


JSORDER_CASES = {                                   # код файла перед основным → есть ли вызов «вперёд»
    "const v = late();": True, "[1].forEach(() => late());": True, "(() => { late(); })();": True,
    "Promise.resolve().then(() => late());": True,     # продолжение обещания — сразу после файла
    "setInterval(late, 1000);": True, '$("x").onclick = late;': True, 'document.addEventListener("click", late);': True,
    "let t = `${late()}`;": True, "function g() { late(); }\ng();": True, "const h = () => late();\nh();": True,
    "const X = { a: () => late() };": False, 'document.addEventListener("click", () => late());': False,
    "const f = () => late();": False, "function g() { late(); }": False, 'const s = "late()"; // late()': False,
    "function g2() {\n  return () => late();\n}\ng2();": False,
}


@pytest.mark.parametrize("code", JSORDER_CASES)
def test_jsorder_catches_forward_call(tmp_path, code):
    from jsorder import check
    (tmp_path / "js").mkdir()
    (tmp_path / "index.html").write_text('<script src="/js/a.js"></script>\n<script>\nfunction late() {}\n</script>',
                                         encoding="utf-8")
    (tmp_path / "js" / "a.js").write_text(code + "\n", encoding="utf-8")
    assert bool(check(tmp_path)) is JSORDER_CASES[code]
