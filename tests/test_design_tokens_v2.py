"""Дизайн-токены v2 (разбор стиля Gemini 21.11): текст на каждом фоне — WCAG AA (≥ 4,5:1) в светлой и тёмной теме.
Токены читаются прямо из CSS панели — поменяли цвет и сломали контраст, тест скажет, какую пару."""
import re
from pathlib import Path

PAGE = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/index.html").read_text(encoding="utf-8")
TEXT = ("--text-primary", "--text-secondary", "--text-muted", "--accent-primary", "--status-danger",
        "--status-approval", "--status-success", "--status-running", "--status-idle")
BG = ("--bg-canvas", "--bg-surface", "--bg-subtle")


def tokens(selector: str) -> dict:
    block = PAGE[PAGE.index(selector):]
    block = block[:block.index("\n  }")]
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9A-Fa-f]{6})", block))


def lum(h: str) -> float:
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def ratio(a: str, b: str) -> float:
    x, y = sorted((lum(a), lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def check(t: dict) -> list[str]:
    bad = [f"{f} на {b}: {ratio(t[f], t[b]):.2f}" for f in TEXT for b in BG if ratio(t[f], t[b]) < 4.5]
    for f, b in (("--on-accent", "--accent-primary"), ("--on-approval", "--status-approval"),
                 ("--status-approval", "--status-approval-bg")):
        if ratio(t[f], t[b]) < 4.5:
            bad.append(f"{f} на {b}: {ratio(t[f], t[b]):.2f}")
    return bad


def test_light_aa():
    assert check(tokens(':root, :root[data-theme="light"] {')) == []


def test_dark_aa():
    light = tokens(':root, :root[data-theme="light"] {')
    dark = {**light, **tokens(':root[data-theme="dark"] {')}
    assert check(dark) == []


def test_v3_values_from_mark():
    """Палитра знака «Лад» (владелец 25.11): графит, тёплый белый, акцент — красный знака; синего нет нигде."""
    light, dark = tokens(':root, :root[data-theme="light"] {'), tokens(':root[data-theme="dark"] {')
    assert light["--accent-primary"] == "#C2361A" and light["--text-primary"] == "#111111"
    assert light["--bg-canvas"] == "#F4F4F2" and dark["--accent-primary"] == "#FF5A2D"
    assert dark["--bg-canvas"] == "#0C0C0B" and dark["--text-primary"] == "#F4F4F2"


def test_no_blue_in_tokens():
    """Синий (оттенок 190°–260°, насыщенный) — ни в одном токене обеих тем."""
    import colorsys
    for sel in (':root, :root[data-theme="light"] {', ':root[data-theme="dark"] {'):
        for k, v in tokens(sel).items():
            h, lt, sat = colorsys.rgb_to_hls(*(int(v[i:i + 2], 16) / 255 for i in (1, 3, 5)))
            assert not (190 <= h * 360 <= 260 and sat > .35 and .15 < lt < .9), (sel, k, v)
