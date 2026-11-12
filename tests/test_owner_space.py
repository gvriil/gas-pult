"""Пространство владельца неприкосновенно (P0, 03.11): после #82 экран выбора роли показался и владельцу, нажатие
карточки записало ему «владельца бизнеса» и простой режим. Теперь: владелец — всегда вид разработчика, экран роли и тур
ему сами не показываются, другой вид — только временный просмотр в панели (на сервер не пишется); старое — сбрасывается
один раз при старте с бэкапом."""

import json
import re
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from websrc import web_source

from gas_pult import webapp, webauth
from gas_pult.config import Config

INDEX = web_source()
OWNER, MEMBER = 7001, 7002


@pytest.fixture(autouse=True)
def dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()


def panel():
    p = webapp.Panel(Config(token="1:T", owners=[OWNER], region="NL"))
    p.people.add(MEMBER, "member", "Иван")
    for uid in (OWNER, MEMBER):
        p.people.accept(uid)
        p.people.set_country(uid, chosen="NL")
    return p


def serve(p):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def call(base, path, body=None, token=""):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Cookie": f"{webauth.COOKIE}={token}"})
    try:
        r = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        r = e
    return (r.status if hasattr(r, "status") else r.code), json.loads(r.read() or b"{}")


def test_restart_and_new_login_keeps_owner_space():
    """Перезапуск службы и новый вход владельца → вид разработчика, полный пульт; попытки сменить вид — отказ."""
    p1 = panel()
    srv, base = serve(p1)
    tok = p1.auth.issue(OWNER)
    assert call(base, "/api/persona", {"persona": "business_owner"}, tok)[0] == 400
    assert call(base, "/api/prefs", {"simple": True}, tok)[0] == 400
    assert call(base, "/api/persona", {"add": {"cap.dev_sessions": False}}, tok)[0] == 400   # сессии не прячутся
    assert call(base, "/api/persona", {"add": {"cap.dev_terminal": False}}, tok)[0] == 200   # своё скрыть — можно
    assert call(base, "/api/prefs", {"lang": "en"}, tok)[0] == 200                           # язык — его выбор
    srv.shutdown()
    p2 = panel()                                                    # «перезапуск»: новый процесс, те же файлы
    p2.owner_space_fix()
    srv, base = serve(p2)
    m = call(base, "/api/meta", token=p2.auth.issue(OWNER))[1]
    srv.shutdown()
    assert m["ui"]["persona"] == "developer" and m["ui"]["onboarded"] is True and m["ui"]["own_space"] is True
    assert m["prefs"]["simple"] is False and m["prefs"]["lang"] == "en"
    assert "cap.dev_terminal" not in m["ui"]["caps"] and "cap.dev_sessions" in m["ui"]["caps"]


def test_member_choice_still_saved():
    p = panel()
    srv, base = serve(p)
    tok = p.auth.issue(MEMBER)
    assert call(base, "/api/persona", {"persona": "business_owner"}, tok)[1]["simple"] is True
    m = call(base, "/api/meta", token=tok)[1]
    srv.shutdown()
    assert m["ui"]["persona"] == "business_owner" and m["prefs"]["simple"] is True and m["ui"]["own_space"] is False


def test_migration_resets_once_with_backup(tmp_path, capsys):
    p = panel()
    p.people.set_ui(OWNER, {"persona": "business_owner", "onboarded": True})     # как было после #82
    p.people.set_prefs(OWNER, simple=True, lang="ru")
    p.people.set_ui(MEMBER, {"persona": "student", "onboarded": True})           # выбор участника — не трогаем
    p.owner_space_fix()
    assert p.people.ui(OWNER)["persona"] == "developer" and p.people.prefs(OWNER)["simple"] is False
    assert p.people.ui(MEMBER)["persona"] == "student"
    baks = sorted(x.name for x in (tmp_path / "data").glob("*.bak-*"))
    assert len(baks) == 2 and all((tmp_path / "data" / b).stat().st_mode & 0o777 == 0o600 for b in baks)
    assert json.loads((tmp_path / "data" / baks[1]).read_text())[str(OWNER)]["persona"] == "business_owner"
    p.owner_space_fix()                                             # второй раз — ничего
    assert len(list((tmp_path / "data").glob("*.bak-*"))) == 2
    assert "восстановлены" in capsys.readouterr().out


def test_panel_never_writes_owner_view():
    """Панель: экран роли и тур владельцу сами не показываются; просмотр другой роли — без запросов к серверу."""
    start = INDEX[INDEX.index("async function start()"):INDEX.index("async function start()") + 1500]
    assert re.search(r"!UI\.onboarded && !UI\.own_space && meta\.role !== \"owner\"", start)
    tour = INDEX[INDEX.index("async function tourOffer()"):INDEX.index("async function tourOffer()") + 400]
    assert 'meta.role === "owner"' in tour
    end = INDEX.index("// ---------- простой режим (docs/SIMPLE-MODE.md)")
    pv = INDEX[INDEX.index("async function previewAs("):end]
    assert "api(" not in pv and "store(" not in pv and "localStorage" not in pv and "sessionStorage" not in pv
    assert "location.reload()" in pv                                # «Вернуться» — снова своё пространство
    pick = INDEX[INDEX.index("async function pickPersona("):INDEX.index("async function pickPersona(") + 200]
    assert "previewAs(id)" in pick
    simple = INDEX[INDEX.index("function simplePrefs("):INDEX.index("async function setLang(")]
    assert 'm?.role !== "owner"' in simple                          # язык с первого экрана — не владельцу
