"""«Что здесь умеет» в меню сессии (владелец 19.11: «у каждой сессии возможность посмотреть тур или сразу прослушать
и узнать о функционале»): текст — только из карты помощника, до ~60 с речи; голосом — /api/tts/about."""

from pathlib import Path

import pytest
from test_people_login import server  # noqa: F401

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"


def test_text_from_map_and_short(server):  # noqa: F811
    panel, _ = server
    t = panel.about_text("session.chat")
    assert t.startswith("Сессия: переписка.") and "1. " in t and len(t) <= panel.ABOUT_MAX
    with pytest.raises(LookupError):
        panel.about_text("нет-такого")


def test_endpoint_speaks_map_text_only(server, monkeypatch):  # noqa: F811
    panel, base = server
    said = []
    monkeypatch.setattr(panel, "tts_text", lambda text, personal=False, cloud=True: said.append(text) or b"ID3mp3")
    import urllib.request

    from gas_pult import webauth
    req = urllib.request.Request(base + "/api/tts/about?screen=session.chat",
                                 headers={"Cookie": f"{webauth.COOKIE}={panel.auth.issue(3)}"})   # и наблюдателю
    with urllib.request.urlopen(req) as r:
        assert r.status == 200 and r.headers["Content-Type"] == "audio/mpeg" and r.read() == b"ID3mp3"
    assert said == [panel.about_text("session.chat")]


def test_menu_item_and_part():
    ease = (WEB / "js/ease.js").read_text(encoding="utf-8")         # 20.11: из «⋯» — в «Удобства»
    assert 'label: "Что здесь умеет"' in ease and "aboutSession(" in ease
    js = (WEB / "js/about.js").read_text(encoding="utf-8")
    assert "/api/tts/about?screen=" in js and "startTour(tourKind(), true)" in js
