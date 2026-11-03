"""Enter в поле ввода (задача 30): компьютер — Enter отправляет, телефон — новая строка, Ctrl/Cmd+Enter — всегда
отправить, во время IME-набора — ничего; поле растёт до ~6 строк.

Решение «что делает Enter» — чистая функция enterAction (блок «enter:start … enter:end» в index.html): есть node —
считает сам JS; нет — Python-двойник и сверка текста. В браузере — tests/e2e/enter_demo.py (нет Chrome — пропуск).
"""

import importlib.util
import json
import shutil
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
PAGE = (WEB / "index.html").read_text(encoding="utf-8")
SCRIPT = PAGE[PAGE.index("<script>\n"):]
BLOCK = SCRIPT[SCRIPT.index("// enter:start"):SCRIPT.index("// enter:end")]


def enter_action(e: dict, touch: bool):
    """Python-двойник enterAction."""
    if e.get("key") != "Enter" or e.get("isComposing") or e.get("keyCode") == 229:
        return None
    if e.get("ctrlKey") or e.get("metaKey"):
        return "send"
    if touch:
        return None
    return "newline" if e.get("shiftKey") or e.get("altKey") else "send"


E = {"key": "Enter"}
CASES = [
    (E, False, "send"), ({**E, "shiftKey": True}, False, "newline"), ({**E, "altKey": True}, False, "newline"),
    ({**E, "ctrlKey": True}, False, "send"), ({**E, "metaKey": True}, False, "send"),
    (E, True, None), ({**E, "shiftKey": True}, True, None),                      # телефон: перенос — сам браузер
    ({**E, "ctrlKey": True}, True, "send"), ({**E, "metaKey": True}, True, "send"),   # внешняя клавиатура
    ({**E, "isComposing": True}, False, None), ({**E, "keyCode": 229}, False, None),
    ({**E, "isComposing": True, "ctrlKey": True}, True, None), ({"key": "a"}, False, None),
]


def test_rules():
    for e, touch, want in CASES:
        assert enter_action(e, touch) == want, (e, touch)


def test_js_matches_python():
    for piece in ('e.key !== "Enter" || e.isComposing || e.keyCode === 229',
                  'if (e.ctrlKey || e.metaKey) return "send"', "if (touch) return null",
                  'e.shiftKey || e.altKey ? "newline" : "send"'):
        assert piece in BLOCK, piece
    node = shutil.which("node")
    if not node:
        return
    script = BLOCK + "\nconst C = " + json.dumps([[e, t] for e, t, _ in CASES]) + ";\n" + \
        "console.log(JSON.stringify(C.map(([e, t]) => enterAction(e, t))));"
    run = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(run.stdout) == [w for _, _, w in CASES]


def test_both_fields_use_the_same_rules():
    assert 'onEnter($("input"), () => sendText(), () => grow());' in SCRIPT
    assert 'onEnter($("sInput"), () => sSend(), sGrow);' in SCRIPT
    assert SCRIPT.count("enterAction(e, touchInput())") == 1          # одно место решения
    touch = SCRIPT[SCRIPT.index("const touchInput"):].split("\n")[0]
    assert "(any-pointer: fine)" in touch and "(pointer: coarse)" in touch and "maxTouchPoints" in touch
    assert 'id="input" rows="1" enterkeyhint="enter"' in PAGE and 'id="sInput" rows="1" enterkeyhint="enter"' in PAGE


def test_grow_up_to_six_lines():
    assert "const MAX_LINES = 6;" in SCRIPT
    assert 'function grow() { fitLines($("input"));' in SCRIPT
    assert 'function sGrow() { fitLines($("sInput")); }' in SCRIPT
    fit = SCRIPT[SCRIPT.index("function fitLines"):SCRIPT.index("\n}\n", SCRIPT.index("function fitLines"))]
    assert "lh * MAX_LINES" in fit and 'overflowY = h > max ? "auto" : "hidden"' in fit


def test_e2e_enter_in_browser():
    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    e2e = Path(__file__).resolve().parent / "e2e" / "enter_demo.py"
    spec = importlib.util.spec_from_file_location("enter_demo", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
