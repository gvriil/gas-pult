"""Владелец 20.11: «логотип у каждой интеграции — узнать сервис по картинке». Знаки Simple Icons (CC0) — локально
в js/logos.js, без запросов наружу; нет знака — нейтральная буква (mono в ядре)."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
JS = (WEB / "js/logos.js").read_text(encoding="utf-8")


def test_local_cc0_no_network():
    assert "Simple Icons 16.36.0 (CC0 1.0" in JS
    assert not re.search(r"https?://(?!simpleicons\.org)", JS)          # ничего не грузится снаружи
    for slug in ("notion", "gmail", "googlecalendar", "googledrive", "linear", "jira", "confluence", "figma", "github",
                 "homeassistant", "icloud", "claude"):
        assert re.search(rf'^  {slug}: \["(#[0-9A-F]{{6}})?", "[Mm]', JS, re.M), slug
    for dark in ("notion", "github", "confluence"):                       # тёмный фирменный — цветом текста темы
        assert re.search(rf'^  {dark}: \["", ', JS, re.M), dark
    assert "slack" not in JS.split("const NAMES")[0]                      # Slack нет в Simple Icons — буква
    assert "Simple Icons" in (WEB.parents[2] / "NOTICE.md").read_text(encoding="utf-8")


def test_wired_everywhere_people_choose():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    assert "LOGOS?.byId(id) ||" in page and 'LOGOS || part("logos")' in page     # «Подключения»
    assert "LOGOS?.byName(s.name)" in (WEB / "js/connections.js").read_text(encoding="utf-8")   # «Подключено» (23.11)
    nc = (WEB / "js/newchat.js").read_text(encoding="utf-8")
    assert nc.count("vis: LG?.byName(x.name)") == 2                       # «Новый чат» и «Интеграции чата»


def test_by_name_in_node(tmp_path):
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("нет node")
    (tmp_path / "logos.mjs").write_text(JS, encoding="utf-8")
    out = subprocess.run([node, "--input-type=module", "-e",
                          f"import * as L from '{tmp_path / 'logos.mjs'}';"
                          "for (const n of ['claude.ai Google Drive', 'claude.ai Gmail', 'linear', 'github-mcp',"
                          " 'claude.ai Claude Docs', 'context7', 'slack']) {"
                          " const h = L.byName(n);"
                          " console.log(n + '=' + (h.match(/color:#\\w+/)?.[0] || (h ? 'mono' : ''))); }"
                          "console.log('id=' + !!L.byId('gcal') + !!L.byId('slack'));"],
                         capture_output=True, text=True, timeout=20)
    got = dict(x.split("=", 1) for x in out.stdout.splitlines())
    assert got["claude.ai Google Drive"] == "color:#4285F4" and got["claude.ai Gmail"] == "color:#EA4335"
    assert got["linear"].startswith("color:") and got["github-mcp"] == "mono"
    assert got["claude.ai Claude Docs"] == "color:#D97757"
    assert got["context7"] == "" and got["slack"] == "" and got["id"] == "truefalse"
