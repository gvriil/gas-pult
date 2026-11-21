"""«Сегодня» открывается сразу (владелец 21.11): сервер отдаёт готовый брифинг и собирает свежий в фоне; панель
забирает его заранее (prefetch) и показывает без ожидания, потом тихо обновляет."""
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from gas_pult import webapp

WEB = Path(webapp.__file__).parent / "web"


def panel(monkeypatch, built):
    p = webapp.Panel.__new__(webapp.Panel)
    n = {"built": 0}
    gate = threading.Event()

    def now(uid=None):
        n["built"] += 1
        if n["built"] > 1:
            gate.wait(5)
        return {"headline": f"сбор {n['built']}"}
    p.cfg = SimpleNamespace(brief_at="07:30")
    p.pult = SimpleNamespace(brief_prefs=SimpleNamespace(get=lambda uid: {}), brief_now=now)
    p.people = SimpleNamespace(tour=lambda uid: {})
    monkeypatch.setattr(webapp.morning_brief, "available", lambda cfg: {})
    monkeypatch.setattr(webapp.morning_brief, "chosen", lambda rec, avail: {"chosen": True})
    monkeypatch.setattr(webapp.morning_brief, "schedule", lambda rec, at: {})
    return p, n, gate


def test_old_brief_returned_at_once_fresh_built_in_background(monkeypatch):
    p, n, gate = panel(monkeypatch, 0)
    d = p.brief_get(1)                                            # первый раз — собираем (кэша нет)
    assert d["brief"]["headline"] == "сбор 1" and "stale" not in d
    p.brief_cache[1] = (time.time() - 400, p.brief_cache[1][1])   # прошло больше 5 минут
    t = time.time()
    d = p.brief_get(1)
    assert time.time() - t < 1 and d["stale"] is True and d["brief"]["headline"] == "сбор 1"   # сразу, старый
    p.brief_get(1)                                                # второй запрос — второй сбор не запускаем
    gate.set()
    for _ in range(50):
        if not p.brief_busy:
            break
        time.sleep(0.05)
    assert n["built"] == 2 and p.brief_get(1)["brief"]["headline"] == "сбор 2"


def test_panel_prefetches_and_opens_from_memory():
    js = (WEB / "js/brief.js").read_text(encoding="utf-8")
    assert "export function prefetch()" in js and "return later(bg, 0);" in js
    assert 'head("Сегодня"' in js and "Что показывать в «Сегодня»?" in js
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'part("brief").then((x) => x.prefetch?.()' in html and 'meta?.role === "owner"' in html
