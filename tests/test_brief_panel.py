"""Брифинг в панели (GAS-18): «Да / Нет / Позже» из панели, подтверждение, журнал, тур «brief», часть js/brief.js."""

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from gas_pult import brief, digest, webapp
from gas_pult.people import People

WEB = Path(webapp.__file__).parent / "web"


def fake_pult(tmp_path, items):
    p = SimpleNamespace(cfg=SimpleNamespace(data=tmp_path), digest=digest.Digest(tmp_path / "digest.json"), pasted=[])
    p.project_window = lambda path: {"id": "@3", "name": "shop-1"} if path == "/p/shop" else None
    p.to_claude = lambda w, text: p.pasted.append((w["id"], text))
    p.digest.fresh(items, time.time())
    return p


def journal(tmp_path):
    return [json.loads(x) for x in (tmp_path / "brief_log.jsonl").read_text().splitlines()]


def test_yes_needs_confirmation_then_logged(tmp_path, monkeypatch):
    pr = {"kind": "pr", "key": "p1", "repo": "me/r", "n": 7, "title": "T", "url": "u", "age": 3, "ci": "SUCCESS",
          "ok": True}
    p = fake_pult(tmp_path, [pr])
    merged = []
    monkeypatch.setattr(digest, "merge", lambda repo, n: merged.append((repo, n)) or "✅ Слито: me/r#7")
    assert brief.act(p, 1, "p1", "yes") == {"ask": "Слить me/r#7 «T»?"} and merged == []
    assert brief.act(p, 1, "p1", "yes", sure=True) == {"done": "✅ Слито: me/r#7"} and merged == [("me/r", 7)]
    assert p.digest.fresh([pr], time.time()) == []
    (rec,) = journal(tmp_path)
    assert rec["act"] == "yes" and rec["kind"] == "pr" and rec["uid"] == 1
    assert (tmp_path / "brief_log.jsonl").stat().st_mode & 0o777 == 0o600


def test_yes_to_project_window_and_missing_window(tmp_path):
    ok = {"kind": "yes", "key": "h1", "project": "shop", "path": "/p/shop", "text": "Ждут «да»: #5"}
    gone = {"kind": "yes", "key": "h2", "project": "cafe", "path": "/p/cafe", "text": "Ждут «да»: #6"}
    p = fake_pult(tmp_path, [ok, gone])
    assert brief.act(p, 1, "h1", "yes", sure=True)["done"] == "Передал «да» в «shop-1»"
    assert p.pasted == [("@3", "Владелец отвечает «да» на пункт из HANDOFF.md: Ждут «да»: #5")]
    with pytest.raises(ValueError, match="окна с Claude в cafe нет"):
        brief.act(p, 1, "h2", "yes", sure=True)


def test_open_no_later_and_unknown(tmp_path):
    mail = {"kind": "mail", "key": "m1", "box": "gmail", "subject": "Договор", "url": "https://m/1"}
    win = {"kind": "win", "key": "w1", "id": "@2", "name": "shop-1"}
    p = fake_pult(tmp_path, [mail, win])
    assert brief.act(p, 1, "m1", "yes") == {"url": "https://m/1"}                 # открыть — без подтверждения
    assert brief.act(p, 1, "w1", "yes") == {"window": "@2"}
    assert brief.act(p, 1, "m1", "later")["done"].startswith("Вернётся")
    assert brief.act(p, 1, "w1", "no")["done"] == "Убрал на месяц"
    assert p.digest.fresh([mail, win], time.time()) == []
    assert [r["act"] for r in journal(tmp_path)] == ["open", "open", "later", "no"]
    assert "Договор" not in (tmp_path / "brief_log.jsonl").read_text()             # текста писем в журнале нет
    with pytest.raises(ValueError):
        brief.act(p, 1, "nope", "yes")


def test_tour_brief_is_kept_per_person(tmp_path):
    ppl = People(tmp_path / "people.json", [1])
    assert ppl.tour(1)["brief"] is None
    ppl.set_tour(1, "brief", "done")
    assert ppl.tour(1)["brief"] == "done" and ppl.tour(1)["dev"] is None


def test_brief_part_and_core_entry_points():
    js = (WEB / "js" / "brief.js").read_text()
    assert "export async function briefOpen" in js and "/api/brief/act" in js and 'saveTour("brief"' in js
    core = (WEB / "index.html").read_text()
    assert 'data-space="brief"' in core and 'part("brief")' in core and 'params.get("view") === "brief"' in core
    assert set(brief.SOURCES) >= {"mail", "calendar", "linear", "github", "pult", "apple"} and "apple" in brief.SOON
    assert {"/api/brief", "/api/brief/prefs", "/api/brief/act"} <= webapp.OWNER_ONLY
