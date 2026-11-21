"""Первый разговор (GAS-37): бейджики-сценарии из help/starters.toml по подключённому и роли; нажатие — текст
интервью агенту и замер в журнале событий без текста."""

import json
from pathlib import Path

import pytest
from test_people_login import call, server  # noqa: F401

from gas_pult import starters


def test_listing_by_connected_and_role():
    all_ = [x["id"] for x in starters.listing({"mail", "calendar"}, "owner")]
    assert all_[:3] == ["day-plan", "meeting", "mail"] and "connect-mail" not in all_ and len(all_) <= starters.MAX
    none = [x["id"] for x in starters.listing(set(), "member")]
    assert "connect-calendar" in none and "mail" not in none and none.count("connect-mail") == 1
    assert starters.listing({"mail"}, "viewer") == [] and starters.listing({"mail"}, None) == []
    space = [x["id"] for x in starters.listing(set(), "member", space=True)]   # пространство: подключения — его
    assert "mail" not in space and "connect-mail" not in space and "day-plan" in space
    assert all(1 <= len(x["title"].split()) <= 4 for x in starters.load())   # коротко: до 4 слов («Бизнес-план»)


def test_prompt_interview_one_by_one_with_options():
    p = starters.prompt("meeting")
    assert p.startswith("«Назначить встречу».") and "по одному вопросу" in p and "(варианты: сегодня, завтра" in p
    assert "«Да / Нет / Позже»" in p
    with pytest.raises(LookupError):
        starters.prompt("нет")


def test_api_and_event_without_text(server, monkeypatch):  # noqa: F811
    panel, base = server
    from gas_pult.connectors import calendar_mcp, mail_mcp
    monkeypatch.setattr(mail_mcp, "boxes", lambda: [])
    monkeypatch.setattr(calendar_mcp, "calendars", lambda: [])
    owner = panel.auth.issue(1)
    ids = [x["id"] for x in call(base, "/api/starters", None, owner)[1]["starters"]]
    assert "connect-mail" in ids and "mail" not in ids
    st, d = call(base, "/api/starter", {"id": "day-plan", "w": "@1"}, owner)[:2]
    assert st == 200 and d["prompt"].startswith("«План на день»")
    ev = [json.loads(x) for x in panel.events.path.read_text().splitlines()]
    assert ev[-1]["ev"] == "starter" and ev[-1]["starter"] == "day-plan" and "prompt" not in ev[-1]
    assert call(base, "/api/starters", None, panel.auth.issue(3))[1]["starters"] == []   # наблюдателю — нет


def test_hooks_in_page():
    page = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/index.html").read_text(encoding="utf-8")
    assert page.count('<div id="starters"></div>') == 2 and 'part("starters")' in page


def test_docs_badge_by_connection():
    ids = [x["id"] for x in starters.listing({"docs"}, "owner")]
    assert "docs" in ids and "connect-docs" not in ids
    ids = [x["id"] for x in starters.listing(set(), "owner")]
    assert "connect-docs" in ids and "docs" not in ids
    assert "find_in_docs" in starters.prompt("docs")


def test_occupations_and_tailored_scenarios():
    """Владелец 19.11: «спросить, чем человек занимается, и предложить 3–4 небанальных сценария под ответ»."""
    occ = starters.occupations()
    assert {o["id"] for o in occ} >= {"biz", "sales", "accounting", "it", "study", "personal"}
    biz = [x["id"] for x in starters.for_occupation("biz", set(), "owner")]
    assert biz[:2] == ["money-leaks", "partners-summary"]
    assert "connect-mail" in biz and len(biz) <= 4
    assert "mail" in [x["id"] for x in starters.for_occupation("biz", {"mail"}, "owner")]
    assert starters.for_occupation("biz", set(), "viewer") == []
    assert starters.for_occupation("нет", set(), "owner") == []
    space = [x["id"] for x in starters.for_occupation("accounting", set(), "member", space=True)]
    assert "docs" not in space and "connect-docs" not in space and len(space) == 3
    general = [x["id"] for x in starters.listing(set(), "owner")]
    assert "money-leaks" not in general                                  # под занятие — не в общем ряду
    for o in starters.occupations():                                     # у каждого занятия сценарии есть
        assert len(starters.for_occupation(o["id"], {"mail", "calendar", "docs"}, "owner")) >= 3
    assert "по одному вопросу" in starters.prompt("money-leaks")


def test_groceries_by_vkusvill():
    ids = [x["id"] for x in starters.for_occupation("personal", {"vkusvill"}, "owner")]
    assert ids[0] == "groceries" and len(ids) == 4
    ids = [x["id"] for x in starters.for_occupation("personal", set(), "owner")]
    assert ids[0] == "connect-vkusvill" and "groceries" not in ids
    assert "корзину" in starters.prompt("groceries") and "«Да / Нет / Позже»" in starters.prompt("groceries")


def test_family_history():
    """Владелец 22.11: «Семейная история» для людей 50+ — 4 сценария, источники, только черновик, только копии."""
    assert {"id": "family", "title": "Семейная история"} in starters.occupations()
    ids = [x["id"] for x in starters.for_occupation("family", set(), "member", space=True)]
    assert ids == ["grave-search", "archive-request", "family-photos", "family-story"]
    general = [x["id"] for x in starters.listing(set(), "owner")]
    assert not set(ids) & set(general)                                   # под занятие — не в общем ряду
    assert "ссылку на источник" in starters.prompt("grave-search") and "Не нашёл" in starters.prompt("grave-search")
    p = starters.prompt("archive-request")
    assert "черновик" in p and "Ничего не отправляй" in p and "после моего «Да»" in p
    assert "ничего не удаляй" in starters.prompt("family-photos") and "копиями" in starters.prompt("family-photos")
    assert "микрофона" in starters.prompt("family-story") and "семейной книги" in starters.prompt("family-story")
    for sid in ids:                                                      # без английских слов и техники
        assert not any("a" <= c.lower() <= "z" for c in starters.prompt(sid).split("gas-pult")[0])
    demo = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/js/demo.js").read_text(encoding="utf-8")
    by = {s["id"]: s["title"] for s in starters.load()}
    for sid in ids:                                                      # демо — те же id и названия, что в TOML
        assert f'["{sid}", "{by[sid]}"' in demo
