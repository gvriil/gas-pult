"""Короткий тур по панели (docs/MINI_APP.md#тур): шаги ссылаются на настоящие data-tour в index.html, два тура
(для бизнеса и для разработчика), driver.js — с cdnjs точной версией 1.8.0 и SRI, грузится только при старте;
отметки done/dismissed — на сервере на человека (/api/tour), права и хранение."""

import json
import re
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import helper, people, webapp, webauth
from gas_pult.config import Config

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "src" / "gas_pult" / "web" / "index.html").read_text(encoding="utf-8")
TOURS = json.loads(re.search(r'<script type="application/json" id="tourData">(.*?)</script>', INDEX, re.S).group(1))
SCREENS = {"home", "session", "integrations", "any"}


@pytest.fixture(autouse=True)
def dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()


# ---------- шаги и тексты ----------
def test_two_tours_with_texts():
    assert set(TOURS) == set(people.TOURS) == {"business", "dev"}
    for kind, t in TOURS.items():
        assert t["title"] and len(t["steps"]) >= 5, kind
        for s in t["steps"]:
            assert set(s) == {"target", "screen", "title", "text"}, s
            assert s["screen"] in SCREENS and s["title"].strip() and 20 <= len(s["text"]) <= 220, s
        targets = [s["target"] for s in t["steps"]]
        assert len(targets) == len(set(targets)), kind                   # без повторов в одном туре
        assert t["steps"][-1]["target"] == "settings"                     # в конце — где пройти тур снова


def test_every_target_is_real_data_tour():
    marked = set(re.findall(r'data-tour="([a-z][a-z0-9\-]*)"', INDEX))
    used = {s["target"] for t in TOURS.values() for s in t["steps"]}
    assert used <= marked, used - marked
    assert marked == used, marked - used                                    # и нет отметок без шага


def test_business_tour_speaks_simple_words():
    biz = " ".join(s["title"] + " " + s["text"] for s in TOURS["business"]["steps"])
    for need in ("Из модуля", "Примерить на себя", "Подсказать", "Расход", "агент"):
        assert need in biz, need
    for jargon in ("tmux", "MCP", "git", "Ctrl"):
        assert jargon not in biz, jargon
    dev = " ".join(s["title"] + " " + s["text"] for s in TOURS["dev"]["steps"])
    for need in ("Сессии", "Экран", "Команды", "Модели", "Интеграции", "Расход", "лимит", "Новая папка",
                 "Строка статуса"):
        assert need in dev, need


def test_driver_from_cdnjs_exact_version_with_sri_and_lazy():
    for f in ("driver.js.iife.min.js", "driver.min.css"):
        assert f"https://cdnjs.cloudflare.com/ajax/libs/driver.js/1.8.0/{f}" in INDEX, f
    for k in ("jsSri", "cssSri"):
        assert re.search(k + r': "sha512-[A-Za-z0-9+/]{86}=="', INDEX), k
    assert 'crossOrigin: "anonymous"' in INDEX
    assert not re.search(r"<(script|link)[^>]+driver", INDEX)                # не в <head>: только при старте тура
    assert "Тур недоступен — нет связи" in INDEX


def test_tour_reachable_from_menu_and_helper():
    assert "Пройти тур: " in INDEX and "Показать тур по этому экрану" in INDEX and "Пройти короткий тур?" in INDEX
    assert 'params.get("tour")' in INDEX                                     # в демо предложение — только с &tour=1
    f = next(x for x in helper.the_map()["faq"] if x["id"] == "tour")
    assert "Показать тур по этому экрану" in f["a"] and "Пройти тур" in f["a"]


# ---------- хранение на человека ----------
def test_people_store_tour_per_person(tmp_path):
    p = people.People(tmp_path / "people.json", [1])
    p.add(2, "member", "Иван")
    assert p.tour(1) == {"business": None, "dev": None, "at": None} == p.tour("мусор")
    p.set_tour(1, "dev", "dismissed")
    p.set_tour(2, "business", "done")
    assert p.tour(1)["dev"] == "dismissed" and p.tour(1)["business"] is None and p.tour(1)["at"]
    assert p.tour(2)["business"] == "done" and p.tour(2)["dev"] is None
    side = tmp_path / "tours.json"                                         # владелец — рядом, 0600
    assert side.stat().st_mode & 0o777 == 0o600 and "2" not in json.loads(side.read_text())
    assert json.loads((tmp_path / "people.json").read_text())["2"]["tour"]["business"] == "done"
    p.add(2, "viewer", "Иван")                                              # смена роли тур не сбрасывает
    assert p.tour(2)["business"] == "done"
    for bad in (("dev", "maybe"), ("ops", "done")):
        with pytest.raises(ValueError):
            p.set_tour(1, *bad)
    p.remove(2)
    assert p.tour(2)["business"] is None


# ---------- /api/tour: права ----------
@pytest.fixture
def server():
    panel = webapp.Panel(Config(token="1:T", owners=[1], region="NL"))
    panel.people.add(2, "member", "Иван")
    panel.people.add(3, "viewer", "Анна")
    for uid in (1, 2, 3):
        panel.people.accept(uid)
        panel.people.set_country(uid, chosen="NL")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield panel, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def call(base, path, body=None, token=""):
    h = {"Cookie": f"{webauth.COOKIE}={token}" if token else ""}
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None, h)
    try:
        r = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        r = e
    return r.status if hasattr(r, "status") else r.code, json.loads(r.read() or b"{}")


def test_api_tour_rights_and_per_person(server):
    panel, base = server
    assert call(base, "/api/tour")[0] == 401
    assert call(base, "/api/tour", {"tour": "dev", "state": "done"})[0] == 401
    toks = {uid: panel.auth.issue(uid) for uid in (1, 2, 3)}
    for uid, tok in toks.items():
        st, d = call(base, "/api/tour", token=tok)
        assert st == 200 and d == {"business": None, "dev": None, "at": None}, uid
    st, d = call(base, "/api/tour", {"tour": "dev", "state": "done"}, toks[1])
    assert st == 200 and d["dev"] == "done" and d["at"]
    st, d = call(base, "/api/tour", {"tour": "business", "state": "dismissed"}, toks[3])   # наблюдатель — тоже
    assert st == 200 and d["business"] == "dismissed"
    assert call(base, "/api/tour", {"tour": "dev", "state": "done"}, toks[2])[0] == 200
    assert call(base, "/api/tour", token=toks[1])[1]["business"] is None                   # у каждого своё
    assert call(base, "/api/tour", token=toks[3])[1] == {**call(base, "/api/tour", token=toks[3])[1],
                                                         "business": "dismissed", "dev": None}
    assert call(base, "/api/tour", token=toks[2])[1]["dev"] == "done"
    assert call(base, "/api/tour", {"tour": "dev", "state": "reset"}, toks[2])[0] == 400
    assert call(base, "/api/tour", {"tour": "x", "state": "done"}, toks[2])[0] == 400


def test_api_tour_needs_terms(server):
    panel, base = server
    panel.people.add(4, "member", "Новый")
    st, d = call(base, "/api/tour", token=panel.auth.issue(4))
    assert st == 403 and d["code"] == "terms"
