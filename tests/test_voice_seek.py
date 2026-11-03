"""Перемотка озвучки (задача 29): −15 / +15 с, полоса с перемоткой пальцем, «0:42 / 3:10», Media Session, место.

Чистые функции плеера (блок «seek:start … seek:end» в index.html) — здесь: есть node — считает JS; нет — Python-двойник
и сверка, что в JS те же границы. Поведение в браузере — tests/e2e/voice_demo.py (Playwright; нет Chrome — пропуск).
"""

import importlib.util
import json
import math
import re
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
BLOCK = SCRIPT[SCRIPT.index("// seek:start"):SCRIPT.index("// seek:end")]


def body(name: str) -> str:
    i = SCRIPT.index(f"function {name}(")
    return SCRIPT[i:SCRIPT.index("\n}\n", i)]


# Python-двойник seekPos / clock — так и должно считаться.
def seek_pos(t, d, dur):
    x = (t or 0) + d
    return max(0, min(dur, x) if dur and math.isfinite(dur) and dur > 0 else x)


def mmss(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def clock(t, dur):
    return f"{mmss(min(t, dur))} / {mmss(dur)}" if dur and math.isfinite(dur) and dur > 0 else mmss(t)


CASES = [(10, -15, 190), (0, -15, 190), (187, 15, 190), (190, 15, 190), (42, 15, 190), (42, -15, 190), (5, 15, 0)]


def test_seek_bounds():
    assert seek_pos(10, -15, 190) == 0                       # −15 на 0:10 — 0:00
    assert seek_pos(185, 15, 190) == 190                     # +15 у конца — конец
    assert seek_pos(42, 15, 190) == 57 and seek_pos(42, -15, 190) == 27
    assert clock(42, 190) == "0:42 / 3:10" and clock(0, 190) == "0:00 / 3:10"


def test_js_matches_python():
    assert "const SEEK = 15;" in BLOCK
    assert "Math.max(0, isFinite(dur) && dur > 0 ? Math.min(dur, x) : x)" in BLOCK      # те же границы, что в двойнике
    assert "`${mmss(Math.min(t, dur))} / ${mmss(dur)}`" in BLOCK
    node = shutil.which("node")
    if not node:
        return
    script = BLOCK + "\nconst C = " + json.dumps(CASES) + ";\n" + \
        "console.log(JSON.stringify(C.map(([t, d, dur]) => [seekPos(t, d, dur), clock(seekPos(t, d, dur), dur)])));"
    run = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True, timeout=30)
    out = json.loads(run.stdout)
    assert out == [[seek_pos(t, d, dur), clock(seek_pos(t, d, dur), dur)] for t, d, dur in CASES]


def test_player_controls():
    inner = body("voiceInner")
    assert 'data-vseek="-${SEEK}"' in inner and 'data-vseek="${SEEK}"' in inner and "data-vtoggle" in inner
    assert "${clock(t, dur)}" in inner and 'role="slider"' in inner
    css = PAGE[PAGE.index("<style>"):PAGE.index("</style>")]
    vb = re.search(r"\.voice \.vb \{([^}]*)\}", css).group(1)
    assert "min-width: 44px" in vb and "min-height: 44px" in vb
    bar = re.search(r"\.voice \.bar \{([^}]*)\}", css).group(1)
    assert "touch-action: none" in bar and "padding: 20px 0" in bar and "box-sizing: content-box" in bar   # 4 + 40 px
    # Перемотка пальцем: тянем — время меняется, отпустили — перескочили.
    for ev in ('"pointerdown"', '"pointermove"', '"pointerup"', '"pointercancel"'):
        assert f"document.addEventListener({ev}" in SCRIPT, ev


def test_media_session():
    ms = body("mediaSession")
    for a in ("seekbackward", "seekforward", "seekto", "play", "pause", "stop"):
        assert f'on("{a}"' in ms, a
    for a in ("previoustrack", "nexttrack"):                     # переключение треков не трогаем
        assert f'on("{a}"' not in SCRIPT and f'setActionHandler("{a}"' not in SCRIPT, a
    assert "seekOffset || SEEK" in ms
    assert "setPositionState" in body("mediaPos")


def test_position_survives_hide_and_reload():
    assert 'addEventListener("pagehide", () => voicePos(true))' in SCRIPT
    assert "if (document.hidden) voicePos(true)" in SCRIPT
    assert "voiceRestore();" in SCRIPT
    assert "voiceForget()" in body("stopPlayer")                 # ✕ и конец — место забыто
    say = body("say")
    assert "voiceSaved(w, msg, full)" in say and "saved?.t" in say
    # Пока слушают, обновление панели само не перезагружает её.
    assert 'voice.state !== "pause"' in body("updSafe")


def test_e2e_voice_in_browser():
    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    e2e = Path(__file__).resolve().parent / "e2e" / "voice_demo.py"
    spec = importlib.util.spec_from_file_location("voice_demo", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
