"""Фокус-ссылка на пространство (GAS-38, владелец 21.11): ссылка открывает полную панель одного пространства — как у
его тестировщика, со сроком, числом устройств и правами («полные» / «только чтение»).

Проверяем: выпускает только владелец; ссылка пространства demo не видит окна владельца, пространство other и проекты
владельца; «только чтение» не пишет; отозванная, истёкшая и сверх числа устройств — 410 focus_gone; режим фокуса
(одна сессия) по такой ссылке не открывается и её не гасит; вход владельца в том же браузере ссылку не расширяет.
Мир (tmux по сокетам, пространства demo и other) — из tests/test_tenant_testers.py.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest
from test_tenant_testers import MEMBER, OWNER, TESTER, call, q, wait, world  # noqa: F401 — world: фикстура

from gas_pult import focus, space_projects, terms, webauth
from gas_pult.access import SLINK_HEADER

VIEWER = 7104
BASE = "https://pult.example"


def raw(w, path, body=None, cookie="", headers=None):
    """Запрос без входа в пульт: только cookie ссылки (и заголовки страницы)."""
    h = {**({"Cookie": cookie} if cookie else {}), **(headers or {})}
    req = urllib.request.Request(w["base"] + path, json.dumps(body).encode() if body is not None else None, h)
    try:
        r = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        r = e
    data = r.read()
    try:
        out = json.loads(data or b"{}")
    except ValueError:
        out = {"raw": len(data)}
    return r.code if hasattr(r, "code") else r.status, out, r.headers.get("Set-Cookie", "")


def issue(w, **kw) -> dict:
    code, d = call(w, "/api/focus/new", {"space": "demo", "base": BASE, **kw}, who=OWNER)
    assert code == 200, d
    assert d["url"].startswith(BASE + "/#focus=") and d["mode"] == "space" and d["space"] == "demo"
    return d


def open_link(w, d: dict, cookie: str = "") -> tuple[int, dict, str]:
    """Открыть ссылку на устройстве: (код, ответ, cookie устройства «gp_focus=…»)."""
    token = d["url"].split("#focus=", 1)[1]
    code, out, sc = raw(w, "/api/focus/open", {"token": token}, cookie)
    return code, out, sc.split(";", 1)[0] if sc else ""


def device(w, **kw) -> tuple[dict, str]:
    """Новая ссылка, открытая на устройстве, условия приняты: (ссылка, cookie)."""
    d = issue(w, **kw)
    code, out, ck = open_link(w, d)
    assert code == 200 and out["mode"] == "space" and ck.startswith(focus.COOKIE + "="), out
    assert raw(w, "/api/terms/accept", {"version": terms.VERSION}, ck)[0] == 200
    return d, ck


def sl(w, path, body=None, ck="", header=True):
    code, out, _ = raw(w, path, body, ck, {SLINK_HEADER: "1"} if header else None)
    return code, out


def test_only_owner_issues_space_links(world):  # noqa: F811
    w = world
    w["p"].people.add(VIEWER, "viewer", "Наблюдатель")
    w["p"].people.accept(VIEWER)
    w["tok"][VIEWER] = w["p"].auth.issue(VIEWER)
    for who in (TESTER, MEMBER, VIEWER):
        code, d = call(w, "/api/focus/new", {"space": "demo", "base": BASE}, who=who)
        assert code == 403, (who, code, d)
    assert call(w, "/api/focus/new", {"space": "nope", "base": BASE}, who=OWNER)[0] == 404
    for bad in ({"ttl": "2y"}, {"max": 5}, {"rights": "root"}):
        assert call(w, "/api/focus/new", {"space": "demo", "base": BASE, **bad}, who=OWNER)[0] == 400, bad
    # по самой ссылке новую не выпустить
    _, ck = device(w)
    assert sl(w, "/api/focus/new", {"space": "demo", "base": BASE}, ck)[0] == 403
    assert sl(w, "/api/focus/new", {"space": "other", "base": BASE}, ck)[0] == 403


def test_link_opens_full_space_panel_and_isolates(world):  # noqa: F811
    w = world
    _, ck = device(w, ttl="1d", max=3, rights="full", name="Кафе — показ")
    m = sl(w, "/api/meta", ck=ck)[1]
    assert m["role"] == "member" and m["via"] == "slink" and m["space"]["slug"] == "demo"
    assert m["slink"]["name"] == "Кафе — показ" and m["slink"]["rights"] == "full"
    assert m["ui"]["persona"] == "developer" and m["prefs"]["simple"] is False   # как у тестировщика
    code, d = sl(w, "/api/new", {"i": 0}, ck)
    assert code == 200 and d["id"].startswith("t:demo:@"), d
    wid = d["id"]
    # первая сессия «Мой проект» открыта при первом входе (space_welcome) — плюс новая; всё — пространства demo
    assert wait(lambda: wid in [s["id"] for s in sl(w, "/api/sessions", ck=ck)[1]["sessions"]])
    assert all(s["id"].startswith("t:demo:@") for s in sl(w, "/api/sessions", ck=ck)[1]["sessions"])
    assert sl(w, "/api/send", {"w": wid, "text": "привет"}, ck)[0] == 200
    sent = []
    w["p"].pult.api = lambda method, **kw: sent.append(kw.get("text", "")) or {}
    assert sl(w, "/api/help/call", {"w": wid}, ck)[0] == 200     # «Позвать на помощь» — владельцу, с названием ссылки
    assert any("Гость по ссылке «Кафе — показ»" in t for t in sent), sent
    # окна владельца и чужого пространства — «окна нет»
    for target in (w["owner_w"], w["other_w"]):
        for path in ("/api/screen", "/api/history", "/api/last"):
            assert sl(w, f"{path}?w={q(target)}", ck=ck)[0] == 404, (path, target)
        assert sl(w, "/api/send", {"w": target, "text": "rm -rf ~"}, ck)[0] == 404
    # проекты владельца — нет
    owner_ids = [x["id"] for x in call(w, "/api/projects", who=OWNER)[1]["projects"]
                 if not space_projects.is_space(x["id"])]
    assert owner_ids
    for oid in owner_ids:
        assert sl(w, f"/api/project?id={q(oid)}", ck=ck)[0] in (403, 404)
        assert sl(w, "/api/project/session", {"id": oid}, ck)[0] in (403, 404)
    assert all(space_projects.is_space(x["id"]) for x in sl(w, "/api/projects", ck=ck)[1]["projects"])
    # люди, ключи, интеграции владельца, вход на другое устройство, ключи входа, уведомления — нет
    for path, body in (("/api/people", None), ("/api/keys", {"provider": "x", "key": "x"}), ("/api/mcp", None),
                       ("/api/focus/list", None), ("/api/spaces", None), ("/api/invite/device", {}),
                       ("/api/passkeys/options", {}), ("/api/push/subscribe", {}), ("/api/link/tg", {})):
        assert sl(w, path, body, ck)[0] == 403, path
    # и без заголовка страницы (адрес открыли закладкой) — то же пространство
    assert raw(w, "/api/sessions", cookie=ck)[1]["space"]["slug"] == "demo"


def test_read_only_link_does_not_write(world):  # noqa: F811
    w = world
    _, ck = device(w, rights="read")
    m = sl(w, "/api/meta", ck=ck)[1]
    assert m["role"] == "viewer" and m["space"]["slug"] == "demo"
    assert sl(w, "/api/sessions", ck=ck)[0] == 200
    for path, body in (("/api/new", {"i": 0}), ("/api/send", {"w": w["other_w"], "text": "x"}),
                       ("/api/project/new", {"name": "x"}), ("/api/space/close", {"w": "@1"})):
        assert sl(w, path, body, ck)[0] == 403, path


def test_revoked_expired_and_over_limit_are_gone(world):  # noqa: F811
    w = world
    p = w["p"]
    d, ck = device(w, max=1)
    # второе устройство сверх лимита — 410, первое работает
    code, out, _ = open_link(w, d)
    assert code == 410 and out["code"] == "focus_gone" and "1 устройстве" in out["error"]
    assert sl(w, "/api/sessions", ck=ck)[0] == 200
    # тем же устройством — снова можно
    assert open_link(w, d, ck)[0] == 200
    # отозвали — 410 и с заголовком, и без
    assert call(w, "/api/focus/revoke", {"id": d["id"]}, who=OWNER)[1]["ok"] is True
    code, out = sl(w, "/api/sessions", ck=ck)
    assert code == 410 and out["code"] == "focus_gone" and "отозвал" in out["error"]
    assert raw(w, "/api/meta", cookie=ck)[0] == 410
    assert open_link(w, d)[0] == 410
    # срок вышел
    d2, ck2 = device(w, ttl="1h")
    rec = p.focus._load()
    rec[d2["id"]]["exp"] = int(time.time()) - 1
    p.focus._save(rec)
    code, out = sl(w, "/api/sessions", ck=ck2)
    assert code == 410 and "Срок" in out["error"]
    # «человек» ссылки больше не тестировщик
    assert p.people.role(focus.vuid(d2["id"])) is None and p.people.tenant(focus.vuid(d2["id"])) is None
    # без cookie, но страница ссылки — 410 (экран «Ссылка не действует»), а не вход
    assert sl(w, "/api/sessions")[0] == 410


def test_unlimited_and_forever(world):  # noqa: F811
    w = world
    d = issue(w, ttl="none", max=0)
    assert d["forever"] is True and d["exp"] - time.time() > 50 * 365 * 86400
    cks = [open_link(w, d)[2] for _ in range(5)]
    assert all(cks) and len(set(cks)) == 5
    x = next(x for x in call(w, "/api/focus/list", who=OWNER)[1]["links"] if x["id"] == d["id"])
    assert x["mode"] == "space" and x["devices"] == 5 and x["max"] == 0 and x["forever"] is True
    assert x["space"] == "demo" and x["rights"] == "full"


def test_focus_mode_with_space_cookie_does_not_kill_link(world):  # noqa: F811
    w = world
    d, ck = device(w)
    code, out, _ = raw(w, "/api/sessions", cookie=ck, headers={focus.HEADER: "1"})
    assert code == 410 and out["code"] == "focus_gone"
    assert focus.Focus.live(w["p"].focus._load()[d["id"]])         # ссылка жива
    assert sl(w, "/api/sessions", ck=ck)[0] == 200


def test_owner_login_does_not_widen_link(world):  # noqa: F811
    """Страница ссылки (заголовок) в браузере, где вошёл владелец: только пространство ссылки."""
    w = world
    _, ck = device(w)
    both = f"{ck}; {webauth.COOKIE}={w['tok'][OWNER]}"
    code, out, _ = raw(w, "/api/sessions", cookie=both, headers={SLINK_HEADER: "1"})
    assert code == 200 and out["space"]["slug"] == "demo"
    assert w["owner_w"] not in [s["id"] for s in out["sessions"]]
    assert raw(w, "/api/people", cookie=both, headers={SLINK_HEADER: "1"})[0] == 403
    # без заголовка — обычный вход владельца, как раньше
    assert raw(w, "/api/people", cookie=both)[0] == 200


def test_logout_clears_device_cookie_link_lives(world):  # noqa: F811
    w = world
    d, ck = device(w)
    code, _, sc = raw(w, "/api/logout", {}, ck, {SLINK_HEADER: "1"})
    assert code == 200 and sc.startswith(focus.COOKIE + "=;")
    assert focus.Focus.live(w["p"].focus._load()[d["id"]])


@pytest.mark.parametrize("uid", [0, 1, -1, 123456789, "x", None])
def test_vuid_never_matches_people(uid):
    assert focus.rid_of(uid) is None
    rid = "00ab12cd34ef"
    assert focus.rid_of(focus.vuid(rid)) == rid and focus.vuid(rid) < -(2 ** 50) + 1


def test_listing_has_no_secrets(world):  # noqa: F811
    w = world
    d, _ = device(w)
    links = call(w, "/api/focus/list", who=OWNER)[1]["links"]
    s = json.dumps(links)
    assert d["url"].split("#focus=")[1] not in s and urllib.parse.quote(d["url"]) not in s
    assert "devs" not in s and '"h"' not in s


def test_link_for_self_is_welcomed_without_questions(world):  # noqa: F811
    """Ссылка «для себя или тестировщика»: условия отмечены выпуском ссылки, страна — пространства (как приглашение)."""
    w = world
    d = issue(w, audience="self")
    code, _out, ck = open_link(w, d)
    assert code == 200 and d["audience"] == "self"
    uid = focus.vuid(d["id"])
    assert w["p"].people.accepted(uid) and w["p"].people.country(uid).get("chosen")
    m = sl(w, "/api/meta", ck=ck)[1]
    assert m["terms"]["accepted"] is True and m["slink"]["terms_line"] is False


def test_link_for_client_agrees_by_line_on_first_action(world):  # noqa: F811
    """Ссылка «для клиента» (по умолчанию, штаб 21.11): без отдельного экрана — строка «Продолжая, вы принимаете
    условия»; смотреть можно сразу, первое действие — согласие самого человека, с датой."""
    w = world
    d = issue(w)
    code, _out, ck = open_link(w, d)
    assert code == 200 and d["audience"] == "client"
    uid = focus.vuid(d["id"])
    assert not w["p"].people.accepted(uid) and w["p"].people.country(uid).get("chosen")
    m = sl(w, "/api/meta", ck=ck)[1]
    assert m["terms"]["accepted"] is False and m["slink"]["terms_line"] is True
    assert sl(w, "/api/sessions", ck=ck)[0] == 200                         # смотреть — сразу
    assert not w["p"].people.accepted(uid)
    code, out = sl(w, "/api/new", {"i": 0}, ck)                             # первое действие — согласие
    assert code == 200, out
    assert w["p"].people.accepted(uid) and sl(w, "/api/meta", ck=ck)[1]["slink"]["terms_line"] is False
    assert call(w, "/api/focus/new", {"space": "demo", "base": BASE, "audience": "всем"}, who=OWNER)[0] == 400
