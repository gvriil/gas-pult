"""Ссылки в переписке (задача 33): http(s) и адреса без схемы — нажимаемые, и в коде; без сырого HTML.

Разбор текста на куски — чистая функция linkParts (блок «link:start … link:end» в index.html): есть node — считает
сам JS (с крошечной заменой URL из node); нет — Python-двойник и сверка текста. DOM, XSS, ширина 390/1366, темы, меню
и Telegram.WebApp.openLink — tests/e2e/links_demo.py (Playwright; нет Chrome — пропуск).
"""

import importlib.util
import json
import re
import shutil
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from websrc import web_source

from gas_pult import tglinks

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
PAGE = web_source()
SCRIPT = PAGE[PAGE.index("<script>\n"):]
BLOCK = SCRIPT[SCRIPT.index("// link:start"):SCRIPT.index("// link:end")]
RU = json.loads((WEB / "i18n" / "ru.json").read_text(encoding="utf-8"))
EN = json.loads((WEB / "i18n" / "en.json").read_text(encoding="utf-8"))

def parts(text: str, code: bool = False) -> list:
    """Python-двойник linkParts — тот же, что режет ответы для Telegram (gas_pult.tglinks); href — без нормализации
    (её делает URL в браузере), поэтому сравниваем только куски текста и адреса."""
    return [p if isinstance(p, str) else {"url": p["url"]} for p in tglinks.parts(text, code)]


LONG = "https://example.com/" + "x" * 3000
CASES = [
    ("javascript:alert(1)", ["javascript:alert(1)"]),
    ("data:text/html,<script>alert(1)</script>", ["data:text/html,<script>alert(1)</script>"]),
    ("JAVASCRIPT:alert('https://ok.example')", ["JAVASCRIPT:alert('", {"url": "https://ok.example"}, "')"]),
    ('<script>https://a.example/</script>', ["<script>", {"url": "https://a.example/"}, "</script>"]),
    ('https://x.example/"onmouseover=alert(1)', [{"url": "https://x.example/"}, '"onmouseover=alert(1)']),
    ("https://x.example/'onmouseover=alert(1)", [{"url": "https://x.example/"}, "'onmouseover=alert(1)"]),
    ("&lt;https://e.example/?a=1&amp;b=2&gt;", ["&lt;", {"url": "https://e.example/?a=1&amp;b=2&gt"}, ";"]),
    ("см. https://dot.example/path.", ["см. ", {"url": "https://dot.example/path"}, "."]),
    ("(см. https://p.example/x)", ["(см. ", {"url": "https://p.example/x"}, ")"]),
    ("https://w.example/A_(b), и", [{"url": "https://w.example/A_(b)"}, ", и"]),
    ("«https://q.example/»!", ["«", {"url": "https://q.example/"}, "»!"]),
    ("https://", ["https://"]),                                  # без адреса — не ссылка
    ("xhttps://glued.example", ["xhttps://glued.example"]),      # приклеено к слову — не ссылка
    ("ftp://f.example и mailto:a@b.example", ["ftp://f.example и mailto:a@b.example"]),
    ("http://a.example https://b.example", [{"url": "http://a.example"}, " ", {"url": "https://b.example"}]),
    (LONG, [{"url": LONG}]),
    # адрес без схемы — домен с известной зоной; хвостовая пунктуация — не адрес
    ("см. pult.example.su/x.", ["см. ", {"url": "pult.example.su/x"}, "."]),
    ("claude.ai/code/abc?x=1, и всё", [{"url": "claude.ai/code/abc?x=1"}, ", и всё"]),
    ("(github.com/gvriil/gas-pult)", ["(", {"url": "github.com/gvriil/gas-pult"}, ")"]),
    ("«example.com»;", ["«", {"url": "example.com"}, "»;"]),
    ("pult.example.su:8443 открыт", [{"url": "pult.example.su:8443"}, " открыт"]),
    ("пульт.рф/а", [{"url": "пульт.рф/а"}]),
    # не адреса: файлы, версии, почта, «a.b», середина пути, неизвестная зона
    ("file.py и 1.2.3 и v2.0 и a.b", ["file.py и 1.2.3 и v2.0 и a.b"]),
    ("README.md main.rs install.sh node.js package.json", ["README.md main.rs install.sh node.js package.json"]),
    ("a@mail.ru и x/site.com", ["a@mail.ru и x/site.com"]),
    ("example.community и e.g. т.е.", ["example.community и e.g. т.е."]),
]
# В коде адрес без схемы — только с путём, портом или поддоменом: «self.app» и «req.me» — атрибуты, не сайты.
CODE_CASES = [
    ("self.app.run() и req.me", ["self.app.run() и req.me"]),
    ("curl pult.example.su:8443/api", ["curl ", {"url": "pult.example.su:8443/api"}]),
    ("open claude.ai/code", ["open ", {"url": "claude.ai/code"}]),
    ("git clone https://github.com/x/y.git", ["git clone ", {"url": "https://github.com/x/y.git"}]),
]


def test_rules():
    for text, want in CASES:
        assert parts(text) == want, text
        assert "".join(p if isinstance(p, str) else p["url"] for p in parts(text)) == text   # текст не теряется
    for text, want in CODE_CASES:
        assert parts(text, True) == want, text
    assert tglinks.parts("pult.example.su/x")[0]["href"] == "https://pult.example.su/x"   # без схемы → https://


def test_js_matches_python():
    assert "const LINK_TLD = \"" + tglinks.TLD + "\";" in BLOCK                      # зоны — те же, что у бота
    assert r"""("\\bhttps?:\\/\\/[^\\s<>\"'`]+|""" in BLOCK and '"giu")' in BLOCK
    assert 'safeUrl(bare ? "https://" + u : u)' in BLOCK
    assert '(x.protocol === "http:" || x.protocol === "https:") && x.hostname' in BLOCK
    assert "/[.,;:!?…»”’]/.test(c)" in BLOCK
    assert '(c === ")" && n(")") > n("("))' in BLOCK and '(c === "]" && n("]") > n("["))' in BLOCK
    node = shutil.which("node")
    if not node:
        return
    fn = BLOCK[BLOCK.index("const LINK_TLD"):BLOCK.index("function linkEl")]
    cases = [(t, w, False) for t, w in CASES] + [(t, w, True) for t, w in CODE_CASES]
    script = fn + "\nconst C = " + json.dumps([[t, c] for t, _, c in cases]) + ";\n" + \
        "const plain = (p) => (typeof p === 'string' ? p : { url: p.url });\n" + \
        "console.log(JSON.stringify(C.map(([t, c]) => linkParts(t, c).map(plain))));"
    run = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(run.stdout) == [w for _, w, _ in cases]


def test_built_with_dom_not_html():
    link = BLOCK[BLOCK.index("function linkEl"):]
    assert "innerHTML" not in link and "insertAdjacentHTML" not in link and "outerHTML" not in link
    assert "a.textContent = p.url" in link and "document.createTextNode(p)" in link
    assert 'a.target = "_blank"; a.rel = "noopener noreferrer"' in link
    assert "a.href = href" in link and "safeUrl(" in link                   # href — только проверенный адрес
    assert 'a.replaceWith(...a.childNodes)' in link                         # [x](javascript:…) — просто текст
    assert 'closest("a, summary, button, textarea")' in link                # готовые ссылки и кнопки — как есть
    assert 'linkParts(t.data, !!t.parentElement?.closest("pre, code"))' in link   # в коде — строже


def test_both_modes_linkify_bubbles():
    full = SCRIPT[SCRIPT.index("function renderChat("):SCRIPT.index("\n}\n", SCRIPT.index("function renderChat("))]
    simple = SCRIPT[SCRIPT.index("function sRender("):SCRIPT.index("\n}\n", SCRIPT.index("function sRender("))]
    for body in (full, simple):
        # точечное обновление (план UX, пункт 1): ссылки — у новых и изменившихся сообщений, после morph
        assert 'querySelectorAll(".bubble, .log pre").forEach(linkify)' in body   # и в коде, и в «Терминал»
        assert body.index("forEach(linkify)") > body.index("morph(box")


def test_finished_chats_linkify():
    for fn in ("async function chatView(", "async function sPast("):
        body = SCRIPT[SCRIPT.index(fn):SCRIPT.index("\n}\n", SCRIPT.index(fn))]
        assert '.querySelectorAll(".bubble").forEach(linkify)' in body, fn


def test_telegram_open_and_menu():
    assert 'tg?.initData && typeof tg.openLink === "function"' in SCRIPT
    assert "navigator.share({ url: href })" in SCRIPT
    menu = SCRIPT[SCRIPT.index("function linkMenu("):SCRIPT.index("\n}\n", SCRIPT.index("function linkMenu("))]
    assert 'helpSheet("sheet.link")' in menu
    for icon in ('icon: "ext"', 'icon: "copy"', 'icon: "share"'):
        assert icon in menu
    assert "  share: '<circle" in SCRIPT                                     # значок — в наборе ic()
    assert not re.search(r"[\U0001F300-\U0001FAFF]", menu)                   # без системных эмодзи


def test_texts_in_both_dictionaries():
    used = set(re.findall(r'LT\("(link\.[a-z.]+)"', SCRIPT))
    assert used == {k for k in RU if k.startswith("link.")}
    assert used <= EN.keys() and all(EN[k] and RU[k] for k in used)


def test_css_long_links_wrap():
    css = PAGE[PAGE.index("<style>"):PAGE.index("</style>")]
    rule = re.search(r"\.chat \.bubble a\.clink \{([^}]*)\}", css).group(1)
    for piece in ("overflow-wrap: anywhere", "var(--accent-primary)", "-webkit-touch-callout: none"):
        assert piece in rule, piece
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", rule)                       # цвет — токеном


def test_e2e_links_in_browser():
    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    e2e = Path(__file__).resolve().parent / "e2e" / "links_demo.py"
    spec = importlib.util.spec_from_file_location("links_demo", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
