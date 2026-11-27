"""Фокус-ссылка на нескольких устройствах (владелец 22.11): «Открыть на другом устройстве» — одноразовый токен той же
записи на 15 минут, не сверх лимита; ответ «не действует» с причиной (``why``) для своего экрана; «Попросить доступ»
до входа — владельцам, с защитой от частых запросов."""

import time

import pytest
from test_focus import FX, W1, call, owner, server  # noqa: F401 — server: фикстура

from gas_pult import focus


def test_extra_token_one_time_and_within_limit(tmp_path):
    f = focus.Focus(tmp_path / "focus.json")
    link = f.new(W1, by=1)
    c1, rec = f.open(link["token"], "", "iPhone · Safari")
    x = f.add_device(rec["id"])
    assert x["used"] == 1 and x["max"] == focus.FOCUS_MAX and x["exp"] - time.time() <= focus.EXTRA_TTL
    assert x["token"] not in (tmp_path / "focus.json").read_text()          # на сервере — только хэш
    c2, _ = f.open(x["token"], "", "Mac · Chrome")
    assert f.by_cookie(c2)["id"] == rec["id"] and f.by_cookie(c1)["id"] == rec["id"]   # старое устройство живёт
    with pytest.raises(focus.Gone) as e:
        f.open(x["token"], "")                                               # одноразовый
    assert e.value.why == "bad"
    assert f.open(link["token"], "")[0]                                      # основная ссылка — как раньше (3-е место)
    with pytest.raises(focus.Denied) as d:
        f.add_device(rec["id"])                                              # мест нет — новый токен не выдаём
    assert d.value.status == 409 and d.value.code == "full"


def test_extra_token_expires_and_cannot_overfill(tmp_path):
    f = focus.Focus(tmp_path / "focus.json")
    link = f.new(W1, by=1)
    _, rec = f.open(link["token"], "")
    a, b, c = (f.add_device(rec["id"]) for _ in range(3))                   # три токена при двух свободных местах
    f.open(a["token"], "")
    f.open(b["token"], "")
    with pytest.raises(focus.Gone) as e:
        f.open(c["token"], "")
    assert e.value.why == "limit" and e.value.rid == rec["id"]
    link2 = f.new(W1, by=1)
    _, r2 = f.open(link2["token"], "")
    old = f.add_device(r2["id"])
    d = f._load()
    d[r2["id"]]["extra"] = {k: time.time() - 1 for k in d[r2["id"]]["extra"]}
    f._save(d)
    with pytest.raises(focus.Gone):
        f.open(old["token"], "")


def test_gone_reasons(tmp_path):
    f = focus.Focus(tmp_path / "focus.json")
    with pytest.raises(focus.Gone) as e:
        f.by_cookie("")
    assert e.value.why == "nodevice"
    link = f.new(W1, by=1)
    c, rec = f.open(link["token"], "")
    f.revoke(rec["id"])
    with pytest.raises(focus.Gone) as e:
        f.by_cookie(c)
    assert e.value.why == "revoked"
    with pytest.raises(focus.Gone) as e:
        f.open(link["token"], "")
    assert e.value.why == "revoked" and f.rid_by_token(link["token"]) == rec["id"]
    old = f.new(W1, 1, ttl=-1)
    with pytest.raises(focus.Gone) as e:
        f.open(old["token"], "")
    assert e.value.why == "expired"


def test_http_device_from_focus_and_owner(server):  # noqa: F811
    s = server
    st, d, _ = call(s["base"], "/api/focus/new", {"w": "@1", "base": "https://pult.example"}, cookie=owner(s))
    tok = d["url"].split("#focus=")[1]
    st, d, ck = call(s["base"], "/api/focus/open", {"token": tok, "privacy": True})
    assert st == 200 and d["id"]
    rid, fc = d["id"], ck.split(";")[0]
    st, x, _ = call(s["base"], "/api/focus/device", {"base": "https://pult.example", "id": "чужое"}, cookie=fc,
                    headers=FX)
    assert st == 200 and x["url"].startswith("https://pult.example/#focus=") and x["qr"].startswith("data:image/png")
    assert x["used"] == 1 and x["max"] == 3
    st, d2, ck2 = call(s["base"], "/api/focus/open", {"token": x["url"].split("#focus=")[1], "privacy": True})
    assert st == 200 and d2["id"] == rid
    st, m, _ = call(s["base"], "/api/meta", cookie=ck2.split(";")[0], headers=FX)
    assert st == 200 and m["focus"]["id"] == rid
    st, _, _ = call(s["base"], "/api/focus/device", {"id": rid, "base": "https://pult.example"})
    assert st == 401                                                          # без входа — нет
    st, y, _ = call(s["base"], "/api/focus/device", {"id": rid, "base": "https://pult.example"}, cookie=owner(s))
    assert st == 200 and y["used"] == 2


def test_http_gone_has_reason(server):  # noqa: F811
    s = server
    st, d, _ = call(s["base"], "/api/meta", cookie="", headers=FX)
    assert st == 410 and d["why"] == "nodevice"
    st, d, _ = call(s["base"], "/api/focus/open", {"token": "x" * 40, "privacy": True})
    assert st == 410 and d["why"] == "bad"


def test_http_ask_notifies_owner_and_is_rate_limited(server, monkeypatch):  # noqa: F811
    s = server
    sent = []
    monkeypatch.setattr(s["p"].pult, "broadcast", lambda text, kind="error", **kw: sent.append((text, kw)))
    s["p"].public_url = "https://pult.example"
    st, d, _ = call(s["base"], "/api/focus/new", {"w": "@1", "base": "https://pult.example"}, cookie=owner(s))
    tok = d["url"].split("#focus=")[1]
    st, d, _ = call(s["base"], "/api/focus/ask", {"why": "nodevice"})
    assert st == 400                                                          # ни ссылки, ни текста — не шлём
    st, d, _ = call(s["base"], "/api/focus/ask", {"token": tok, "why": "limit", "note": "Ольга, ноутбук"})
    assert st == 200 and d == {"ok": True}
    text, kw = sent[-1]
    assert "Ольга, ноутбук" in text and "shop" in text and tok not in text
    btn = kw["reply_markup"]["inline_keyboard"][0]
    assert [b["text"] for b in btn] == ["Добавить устройство", "Новая ссылка"]
    aid = btn[0]["web_app"]["url"].split("focusask=")[1].split("&")[0]
    st, a, _ = call(s["base"], f"/api/focus/asks?id={aid}", cookie=owner(s))
    assert st == 200 and a["link"]["w"] == "@1" and a["link"]["used"] == 0 and a["note"] == "Ольга, ноутбук"
    st, _, _ = call(s["base"], f"/api/focus/asks?id={aid}")
    assert st == 401
    st, d, _ = call(s["base"], "/api/focus/ask", {"id": "000000000000", "note": "кто-то"})
    assert st == 200 and "Ссылка не определена" in sent[-1][0]                 # чужой id — тот же ответ
    st, d, _ = call(s["base"], "/api/focus/ask", {"id": "000000000000", "note": "кто-то"})
    assert st == 429 and d["code"] == "ask_limit"                            # 3 запроса с адреса за 10 минут


@pytest.mark.parametrize("engine", ["chromium", "firefox", "webkit"])   # Edge и Chrome — chromium; Safari — webkit
def test_e2e_focus_devices_live(engine):
    """Сценарий вживую (tests/e2e/focus_devices_live.py) на трёх движках: два устройства по ссылке, «/?focus» без
    токена, сверх лимита, «Открыть на другом устройстве». Без tmux или движка — пропуск (в CI движки ставятся)."""
    import importlib.util
    import shutil
    from pathlib import Path

    pytest.importorskip("playwright.sync_api")
    if not shutil.which("tmux"):
        pytest.skip("нет tmux для проверки вживую")
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            getattr(p, engine).launch().close()
    except Exception as e:
        pytest.skip(f"нет браузера {engine} для Playwright: {str(e).splitlines()[0][:80]}")
    e2e = Path(__file__).resolve().parent / "e2e" / "focus_devices_live.py"
    spec = importlib.util.spec_from_file_location("focus_devices_live", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert len(mod.run(engine)) == 5
