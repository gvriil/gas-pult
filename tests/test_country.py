"""Страна человека: allowlist поставщиков, телефон, хеш с солью, GeoIP, адрес за прокси, расхождение признаков."""

import gzip
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import bot, country, fallback, models, webapp, webauth
from gas_pult.config import Config
from gas_pult.people import People

PHONE = "+31 6 00000000"                    # выдуманный номер
# Маленькая база db-ip lite: документационные адреса, страны — для проверок
CSV = """ip_start,ip_end,country
192.0.2.0,192.0.2.255,NL
198.51.100.0,198.51.100.127,RU
198.51.100.128,198.51.100.255,ZZ
203.0.113.0,203.0.113.255,DE
2001:db8::,2001:db8:0:ffff:ffff:ffff:ffff:ffff,NL
2001:db8:1::,2001:db8:1:ffff:ffff:ffff:ffff:ffff,CN
"""


def geo_dir(tmp_path: Path, gz: bool = False) -> Path:
    d = tmp_path / "geoip"
    d.mkdir(parents=True, exist_ok=True)
    if gz:
        with gzip.open(d / "dbip-country-lite.csv.gz", "wt") as fh:
            fh.write(CSV)
    else:
        (d / "dbip-country-lite.csv").write_text(CSV)
    return d


# ---------- списки поставщиков ----------
def test_allowlist_needs_every_country():
    assert len(models.ANTHROPIC_LISTED) == 185                     # вся страница Anthropic, сверено 01.11.2026
    assert models.allowed("claude", {"NL", "DE"}) and models.allowed("openrouter", "US")
    assert not models.allowed("claude", {"NL", "RU"})               # одна страна не в списке — нельзя
    assert not models.allowed("claude", {"NL", "CN"}) and not models.allowed("openrouter", "HK")
    assert models.allowed("claude", "PR")                           # территория США — тоже
    assert not models.allowed("claude", "AQ")                       # не в списке — не поддерживается
    assert models.allowed("zai", {"NL", "CN"}) and not models.allowed("zai", {"NL", "IR"})
    assert not models.allowed("deepseek", {"DE", "RU"})
    assert not models.allowed("claude", set()) and not models.allowed("claude", "")   # страна неизвестна
    assert models.allowed("claude", "US/CA")


def test_public_profiles_mark_denied(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path))
    pub = {p["id"]: p for p in models.public({}, {"NL", "CN"})}
    assert not pub["claude"]["allowed"] and pub["claude"]["denied"] == models.DENY
    assert pub["zai"]["allowed"] and pub["zai"]["denied"] == ""
    assert "allowed" not in models.public({})[0]                     # без стран — как раньше


# ---------- телефон ----------
@pytest.mark.parametrize("num, cc", [
    (PHONE, "NL"), ("+7 900 000-00-00", "RU"), ("+7 700 000 0000", "KZ"), ("+7 600 000 0000", "KZ"),
    ("+1 555 000 0000", "US/CA"), ("0049 30 000000", "DE"), ("+44 7700 900000", "GB"), ("+375 00 0000000", "BY"),
    ("+380 00 000 0000", "UA"), ("+995 500 000000", "GE"), ("", ""), ("+999 0", ""),
])
def test_phone_country(num, cc):
    assert country.phone_country(num) == cc


def test_phone_hash_with_install_salt(tmp_path):
    rec = country.phone_record(PHONE, tmp_path)
    salt = tmp_path / "country_salt"
    assert salt.stat().st_mode & 0o777 == 0o600 and len(salt.read_text().strip()) == 64
    assert set(rec) == {"phone_hash", "phone_cc", "phone_at"} and rec["phone_cc"] == "NL"
    assert "00000000" not in json.dumps(rec) and len(rec["phone_hash"]) == 64
    assert country.phone_record("0031600000000", tmp_path)["phone_hash"] == rec["phone_hash"]   # тот же номер
    other = tmp_path / "other"
    assert country.phone_record(PHONE, other)["phone_hash"] != rec["phone_hash"]   # другая установка — другой хеш


# ---------- GeoIP ----------
@pytest.mark.parametrize("gz", [False, True])
def test_geoip_v4_v6(tmp_path, gz):
    g = country.GeoIP(geo_dir(tmp_path, gz))
    assert g.available() and g.info()["attribution"] == "IP Geolocation by DB-IP"
    assert g.lookup("192.0.2.10") == "NL" and g.lookup("198.51.100.5") == "RU" and g.lookup("203.0.113.255") == "DE"
    assert g.lookup("198.51.100.200") is None                       # ZZ — нет данных
    assert g.lookup("2001:db8::1") == "NL" and g.lookup("2001:db8:1::abcd") == "CN"
    assert g.lookup("::ffff:192.0.2.7") == "NL"                     # IPv4 внутри IPv6
    assert g.lookup("2001:db8:2::1") is None and g.lookup("8.8.8.8") is None   # нет в базе
    assert g.lookup("127.0.0.1") is None and g.lookup("10.1.2.3") is None and g.lookup("bad") is None


def test_geoip_without_base(tmp_path):
    g = country.GeoIP(tmp_path / "nope")
    assert not g.available() and g.lookup("192.0.2.1") is None and g.info()["geoip"] is False


# ---------- признаки и расхождение ----------
def test_mismatch_gives_intersection_and_notice(tmp_path):
    p = People(tmp_path / "people.json", [1])
    p.add(2, "member", "Иван")
    rec, tell = p.set_country(2, chosen="NL")
    assert not tell and not rec["mismatch"] and country.check_set(rec, "NL") == {"NL"}
    rec, tell = p.set_country(2, **country.phone_record("+7 900 000 0000", tmp_path))
    assert tell and rec["mismatch"]                                  # выбрал NL, номер +7 — пометка владельцу
    rec, tell = p.set_country(2, ip_cc="DE", ip_at=1)
    assert tell and country.effective(rec) == {"NL", "RU", "DE"}     # набор поменялся — сказать снова
    rec, tell = p.set_country(2, ip_cc="DE", ip_at=2)
    assert not tell                                                  # то же расхождение — без повтора
    cs = country.check_set(rec, "NL")
    assert not models.allowed("claude", cs) and not models.allowed("zai", cs)   # только то, что разрешено для всех
    line = country.notice("Иван", 2, rec)
    assert "Иван" in line and "NL" in line and "RU" in line and "900" not in line
    stored = (tmp_path / "people.json").read_text()
    assert "900" not in stored and "phone_hash" in stored            # номер — только хешем
    p.add(2, "viewer", "Иван")
    assert p.country(2)["chosen"] == "NL"                            # смена роли страну не сбрасывает
    assert country.check_set({}, "NL") == set()                      # не выбрал — ничего
    assert country.check_set({"chosen": "CA", "phone_cc": "US/CA"}, "") == {"CA", "US"}   # строгая трактовка
    assert not country.is_mismatch({"chosen": "CA", "phone_cc": "US/CA", "ip_cc": "CA"})


def test_owner_country_in_side_file(tmp_path):
    p = People(tmp_path / "people.json", [1])
    p.set_country(1, chosen="DE")
    assert p.country(1)["chosen"] == "DE" and not (tmp_path / "people.json").exists()
    assert (tmp_path / "countries.json").stat().st_mode & 0o777 == 0o600
    assert p.list()[0]["country"]["chosen"] == "DE"
    p.add(2, "member")
    p.set_country(2, chosen="NL")
    p.remove(2)
    assert p.country(2) == {}


def test_no_vpn_hints_in_interface():
    src = Path(__file__).parent.parent / "src" / "gas_pult"
    for f in ("web/index.html", "bot.py", "country.py", "terms.py"):
        text = (src / f).read_text(encoding="utf-8")
        assert "VPN" not in text and "смените регион" not in text.lower(), f
    assert country.DENY == models.DENY == "Этот сервис недоступен в вашей стране по условиям поставщика"


# ---------- запасные — по странам человека ----------
class FakeTmux:
    def __init__(self):
        self.calls = []

    def respawn(self, wid, path, cmd, mark="claude"):
        self.calls.append((wid, cmd, mark))


def test_fallback_uses_person_countries(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path))
    from gas_pult import providers
    providers.save_key("deepseek", "k2")
    state = {"fallback_chain": ["claude", "deepseek"]}
    said = []
    s = fallback.Switcher(FakeTmux(), lambda: state, "claude", "NL", say=said.append,
                          countries=lambda w: {"NL", "CN"})
    line = s.act({"id": "@1", "name": "shop", "path": "/p", "profile": "openrouter"}, "rate", 429)
    assert line.endswith("переключена на DeepSeek")                  # Claude не для CN — пропущен
    s.countries = lambda w: set()                                    # страна неизвестна — никуда
    line = s.act({"id": "@2", "name": "b", "path": "/p", "profile": "openrouter"}, "rate", 429)
    assert "запасных нет" in line
    with pytest.raises(ValueError, match=models.DENY):
        fallback.validate(["claude"], {"NL", "RU"})


def test_bot_window_countries_by_opener(tmp_path):
    p = bot.Pult.__new__(bot.Pult)
    p.cfg = type("C", (), {"owners": [1], "region": "NL", "data": tmp_path})()
    p.people = People(tmp_path / "people.json", [1])
    p.people.add(2, "member")
    p.people.set_country(1, chosen="NL")
    p.people.set_country(2, chosen="CN")
    by = {"@1": "2", "@2": ""}
    p.tmux = type("T", (), {"run": lambda self, *a: by[a[3]] + "\n"})()
    assert p.window_countries({"id": "@1"}) == {"CN", "NL"}          # открыл человек 2
    assert p.window_countries({"id": "@2"}) == {"NL"}                # метки нет — владелец


# ---------- бот ----------
@pytest.fixture
def pult(tmp_path):
    p = bot.Pult.__new__(bot.Pult)
    p.cfg = type("C", (), {"owners": [1], "data": tmp_path, "region": "NL"})()
    p.people, p.waiting, p.sent = People(tmp_path / "people.json", [1]), {}, []
    p.people.add(2, "member", "Иван")
    p.send = lambda chat, text, **kw: p.sent.append((chat, text, kw)) or {}
    p.to = lambda chat: (lambda text, **kw: p.sent.append((chat, text, kw)))
    p.api = lambda method, **kw: {}
    return p


def test_bot_contact_only_own(pult):
    p = pult
    p.on_message({"chat": {"id": 2}, "from": {"id": 2}, "contact": {"phone_number": PHONE, "user_id": 3}})
    assert "не ваш номер" in p.sent[-1][1] and not p.people.country(2)        # чужой контакт — не принимаем
    p.on_message({"chat": {"id": 2}, "from": {"id": 2}, "contact": {"phone_number": PHONE}})
    assert not p.people.country(2)                                             # без user_id — тоже
    p.on_message({"chat": {"id": 2}, "from": {"id": 2}, "contact": {"phone_number": PHONE, "user_id": 2}})
    rec = p.people.country(2)
    assert rec["phone_cc"] == "NL" and rec["phone_hash"] and "NL" in p.sent[-1][1]
    assert p.sent[-1][2]["reply_markup"] == {"remove_keyboard": True}          # участнику меню бота не нужно
    assert "00000000" not in (p.cfg.data / "people.json").read_text()


def test_bot_country_flow_and_people_mark(pult):
    p = pult
    p.show_country(1)
    assert "cc:NL" in json.dumps(p.sent[-1][2]) and p.waiting[1] == "cc"
    p.on_message({"chat": {"id": 1}, "from": {"id": 1}, "text": "zz"})
    assert "Не знаю такой страны" in p.sent[-1][1] and not p.people.country(1)
    p.on_message({"chat": {"id": 1}, "from": {"id": 1}, "text": "de"})
    assert p.people.country(1)["chosen"] == "DE" and p.sent[-1][2]["reply_markup"] == bot.PHONE_KB
    kb = p.sent[-1][2]["reply_markup"]
    assert kb["keyboard"][0][0]["request_contact"] is True and kb["one_time_keyboard"] is True
    p.people.set_country(2, chosen="NL", ip_cc="RU")
    p.show_people(1)
    assert "страна NL" in p.sent[-1][1] and "расходятся" in p.sent[-1][1]
    # участник: только страна; остальные кнопки бота — нет
    assert p.country_update({"callback_query": {"data": "cc:NL"}})
    assert not p.country_update({"message": {"chat": {"id": 5}, "text": "🆕 Новая"}})


def test_bot_refuses_session_for_country(pult, monkeypatch):
    p = pult
    p.people.set_country(1, chosen="RU")
    p.actor.uid = 1
    try:
        with pytest.raises(bot.Denied, match=country.DENY):
            p.to_claude({"id": "@1", "profile": "claude"}, "привет")
        monkeypatch.setattr(bot.setup, "installed", lambda c: True)
        p.cfg.claude = "claude"
        p.tmux = type("T", (), {"windows": lambda self: []})()
        p.open_session(1, "x", "/tmp")
        assert p.sent[-1][1] == country.DENY
    finally:
        p.actor.uid = None


# ---------- панель ----------
@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    panel = webapp.Panel(Config(token="1:T", owners=[1], region="NL"))
    panel.geo = country.GeoIP(geo_dir(tmp_path))
    panel.people.add(2, "member", "Иван")
    for uid in (1, 2):
        panel.people.accept(uid)
    told = []
    monkeypatch.setattr(panel.pult, "api", lambda method, **kw: told.append(kw.get("text")) or {})
    monkeypatch.setattr(panel, "window", lambda wid: {"id": wid, "path": "/tmp", "name": "w", "profile": "claude"})
    monkeypatch.setattr(panel, "send", lambda w, text, mid="": False)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield panel, f"http://127.0.0.1:{srv.server_address[1]}", told
    srv.shutdown()


def call(base, path, body=None, token="", ip="192.0.2.9"):
    hdr = {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={token}"}
    if ip:
        hdr["X-Forwarded-For"] = ip
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None, hdr)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def test_panel_country_gate_choice_and_ip(server):
    panel, base, told = server
    member = panel.auth.issue(2)
    code, d = call(base, "/api/sessions", None, member, "192.0.2.9")
    assert code == 403 and d["code"] == "country"                    # без страны — только выбор
    code, meta = call(base, "/api/meta", None, member, "192.0.2.9")
    assert code == 200 and meta["country"]["need"] and meta["country"]["ip_cc"] == "NL"   # IP сверили сразу
    code, c = call(base, "/api/country", None, member)
    assert code == 200 and c["geoip"] and c["attribution"] == "IP Geolocation by DB-IP"
    assert {"code": "NL", "name": "Нидерланды"} in c["options"]
    assert call(base, "/api/country", {"code": "XX"}, member)[0] == 400
    code, c = call(base, "/api/country", {"code": "nl"}, member)
    assert code == 200 and c["chosen"] == "NL" and not c["need"] and c["check"] == ["NL"]
    assert call(base, "/api/send", {"w": "@1", "text": "x"}, member)[0] == 200
    assert "192.0.2" not in (Path(panel.cfg.data) / "people.json").read_text()   # IP не храним
    # человек поменял выбор на RU — Claude ему недоступен, отказ ровно этим текстом
    call(base, "/api/country", {"code": "RU"}, member)
    code, d = call(base, "/api/send", {"w": "@1", "text": "x"}, member)
    assert code == 400 and d["error"] == country.DENY
    code, d = call(base, "/api/new", {"i": 0, "profile": "claude"}, member)
    assert code == 400 and d["error"] == country.DENY
    assert told and "Иван" in told[-1] and "RU" in told[-1] and "192.0.2" not in told[-1]   # пометка владельцу
    code, meta = call(base, "/api/meta", None, member)
    assert {p["id"]: p["allowed"] for p in meta["profiles"]}["claude"] is False


def test_panel_ip_rechecked_on_request_and_people_mark(server, monkeypatch):
    panel, base, told = server
    owner = panel.auth.issue(1)
    panel.people.set_country(1, chosen="NL")
    panel.people.set_country(2, chosen="NL")
    call(base, "/api/sessions", None, owner, "192.0.2.9")
    assert panel.people.country(1)["ip_cc"] == "NL" and not told
    panel.ip_seen.clear()                                            # прошло IP_EVERY
    call(base, "/api/sessions", None, owner, "203.0.113.4")
    assert panel.people.country(1)["ip_cc"] == "DE" and panel.people.country(1)["mismatch"] and told
    code, d = call(base, "/api/people", None, owner, "203.0.113.4")
    assert code == 200 and d["geoip"] and d["attribution"] == "IP Geolocation by DB-IP"
    me = next(p for p in d["people"] if p["id"] == 1)
    assert me["country"]["mismatch"] and me["country"]["ip_cc"] == "DE" and "phone_hash" not in json.dumps(d)
    panel.ip_seen.clear()
    call(base, "/api/sessions", None, owner, "198.51.100.200")      # нет данных — не блокируем
    assert panel.people.country(1)["ip_cc"] == "" and call(base, "/api/sessions", None, owner)[0] == 200


def test_client_ip_trusts_proxy_headers_only_from_loopback(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    H = webapp.handler(webapp.Panel(Config(token="1:T", owners=[1])))
    h = H.__new__(H)
    h.client_address, h.headers = ("192.0.2.5", 1), {"X-Forwarded-For": "198.51.100.7"}
    assert h.client_ip() == "192.0.2.5"                              # не с прокси — заголовку не верим
    h.client_address = ("127.0.0.1", 1)
    assert h.client_ip() == "198.51.100.7"
    h.headers = {"X-Forwarded-For": "203.0.113.1, 198.51.100.7"}
    assert h.client_ip() == "198.51.100.7"                           # первый адрес прислал клиент — берём последний
    h.client_address, h.headers = ("::1", 1), {"X-Real-IP": "2001:db8::5"}
    assert h.client_ip() == "2001:db8::5"
    h.headers = {}
    assert h.client_ip() == "::1"
