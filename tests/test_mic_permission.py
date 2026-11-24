"""Владелец 24.11: «Permission not allowed» на микрофоне. Нет доступа — лист с шагами под браузер (js/micperm.js) и
«Попробовать снова», а не голая ошибка браузера; обе точки запроса микрофона (запись и диктовка) ведут туда."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
PART = (WEB / "js/micperm.js").read_text(encoding="utf-8")


def test_both_mic_paths_use_help():
    assert INDEX.count("return micHelp(e, ") == 2 and 'part("micperm")' in INDEX
    assert '"Нет доступа к микрофону: " + e.message' not in INDEX


def test_steps_for_owner_browsers():
    for k in ("ios-safari", "mac-safari", "mac-chrome", "tg-ios", "tg-mac", "other"):
        assert re.search(rf'"?{k}"?: \[', PART), k
    assert "Попробовать снова" in PART and "export async function help" in PART


@pytest.mark.skipif(not shutil.which("node"), reason="нет node")
def test_part_parses():
    r = subprocess.run(["node", "--check", "--input-type=module"], input=PART, text=True, capture_output=True)
    assert r.returncode == 0, r.stderr
