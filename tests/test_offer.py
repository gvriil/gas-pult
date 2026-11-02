"""Предложения GASTECH: код и файл, страница без входа (404, noindex, перебор), загрузка выгрузки (CSV/XLSX, защита,
ПДн, TTL), мастер «Подключить», запрос владельцу, демо в Telegram (изоляция), CLI."""

import io
import json
import os
import threading
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import bot, cli, modules, offer_report, offers, terms, webapp, webauth
from gas_pult.config import Config


@pytest.fixture(autouse=True)
def dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()


def make(name="", expires="", text=None) -> str:
    return offers.create(text or offers.example_text(), name, expires)[0]


# ---------- код и файл ----------
def test_code_unguessable_file_private(tmp_path):
    a, b = make(), make()
    assert a != b and offers.CODE.match(a) and len(a) >= 24 and not a.startswith("-")
    p = tmp_path / "cfg" / "offers" / f"{a}.toml"
    assert p.is_file() and p.stat().st_mode & 0o777 == 0o600
    assert offers.load(a)["business"] == "Автомойка «Пример»"
    for bad in ("", "short", "../" + a, a + "/x", "a" * 65, a.replace(a[0], "!", 1)):
        assert offers.load(bad) is None
    with pytest.raises(offers.OfferError, match="нет таких модулей"):
        make(text=offers.example_text().replace('"carwash-reviews"', '"no-such"'))


def test_expired_and_revoked(tmp_path):
    c = make(expires="2026-01-01")
    assert offers.load(c, today=date(2026, 1, 1)) and offers.load(c, today=date(2026, 1, 2)) is None
    c2 = make()
    offers.revoke(c2)
    assert offers.load(c2) is None and (tmp_path / "cfg" / "offers" / "revoked" / f"{c2}.toml").is_file()


# ---------- сервер ----------
@pytest.fixture
def server(monkeypatch):
    panel = webapp.Panel(Config(token="1:T", owners=[1], region="NL"))
    monkeypatch.setattr(panel, "bot_username", lambda: "test_bot")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield panel, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


class Client:
    def __init__(self, base):
        self.base, self.cookies = base, {}

    def req(self, path, body=None, raw=None, headers=None):
        h = {"Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items()), **(headers or {})}
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        r = urllib.request.Request(self.base + path, data, h)
        try:
            resp = urllib.request.urlopen(r)
            code = resp.status
        except urllib.error.HTTPError as e:
            resp, code = e, e.code
        body = resp.read()
        for c in resp.headers.get_all("Set-Cookie") or []:
            k, _, v = c.split(";")[0].partition("=")
            self.cookies[k] = v
        return code, body, resp.headers

    def json(self, path, body=None, **kw):
        code, b, h = self.req(path, body, **kw)
        return code, json.loads(b or b"{}"), h


def test_404_same_for_unknown_revoked_expired(server):
    _, base = server
    c = Client(base)
    gone, old = make(), make(expires="2020-01-01")
    offers.revoke(gone)
    pages = {c.req(f"/offer/{x}")[:2] for x in (gone, old, "A" * 24, "nope")}
    apis = {c.req(f"/api/offer/{x}")[:2] for x in (gone, old, "A" * 24, "nope")}
    assert len(pages) == 1 and next(iter(pages))[0] == 404
    assert len(apis) == 1 and next(iter(apis))[0] == 404


def test_page_headers_noindex_csp(server):
    _, base = server
    code = make()
    st, body, h = Client(base).req(f"/offer/{code}")
    assert st == 200 and b'name="robots" content="noindex' in body
    assert h["X-Robots-Tag"] == "noindex, nofollow, noarchive" and h["Referrer-Policy"] == "no-referrer"
    assert h["Cache-Control"] == "no-store" and "script-src 'sha256-" in h["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
    st, body, h = Client(base).req(f"/api/offer/{code}")
    assert st == 200 and h["X-Robots-Tag"].startswith("noindex") and h["Cache-Control"] == "no-store"
    st, body, _ = Client(base).req("/robots.txt")
    assert st == 200 and b"Disallow: /offer/" in body


def test_business_name_is_text_only(server):
    _, base = server
    evil = '<img src=x onerror=alert(1)>'
    code = make(name=evil)
    _, body, _ = Client(base).req(f"/offer/{code}")
    assert evil.encode() not in body and b"esc(d.business)" in body          # имя выводится только через esc()
    _st, d, h = Client(base).json(f"/api/offer/{code}")
    assert d["business"] == evil and h["Content-Type"].startswith("application/json")
    assert h["X-Content-Type-Options"] == "nosniff"


def test_offer_data_has_no_internal_fields(server):
    _, base = server
    code = make()
    _, d, _ = Client(base).json(f"/api/offer/{code}")
    blob = json.dumps(d, ensure_ascii=False)
    assert code not in blob and "note" not in d and "/" + "home" not in blob and "path" not in blob
    assert [m["id"] for m in d["modules"]] == ["carwash-morning", "carwash-return", "carwash-reviews"]
    assert d["modules"][0]["demo"]["summary"]["rows"] and d["modules"][1]["demo"]["reminder"]["n"] > 0
    q = d["modules"][0]["demo"]["question"]
    assert len(q["options"]) >= 2 and all(o["next"] for o in q["options"])
    _, d2, _ = Client(base).json(f"/api/offer/{code}")
    assert d2["modules"][0]["demo"] == d["modules"][0]["demo"]                      # детерминированно


def test_offer_gives_no_panel_access(server):
    _panel, base = server
    c = Client(base)
    code = make()
    c.json(f"/api/offer/{code}")
    for step in ({"step": "terms", "version": terms.VERSION}, {"step": "country", "code": "DE"},
                 {"step": "module", "id": "carwash-return"}):
        assert c.json(f"/api/offer/{code}/wizard", step)[0] == 200
    assert c.json(f"/api/offer/{code}/login", {})[0] == 200
    assert offers.COOKIE in c.cookies and webauth.COOKIE not in c.cookies
    for path in ("/api/sessions", "/api/meta", "/api/people", "/api/providers", "/api/commands"):
        assert c.json(path)[0] == 401
    assert c.json("/api/send", {"w": "@1", "text": "x"})[0] == 401
    assert c.json(f"/api/offer/{code}/sessions")[0] == 404
    assert c.json(f"/api/offer/{code}/../../api/sessions")[0] in (401, 404)
    c.cookies[webauth.COOKIE] = c.cookies[offers.COOKIE]                          # демо-cookie — не вход в панель
    assert c.json("/api/sessions")[0] == 401


def test_bruteforce_limited_per_ip(server):
    _, base = server
    c = Client(base)
    code = make()
    for i in range(offers.MISS_LIMIT[0]):
        assert c.req(f"/api/offer/{'Z' * 23}{i % 10}")[0] == 404
    assert c.req(f"/api/offer/{code}")[0] == 429 and c.req(f"/offer/{code}")[0] == 429


# ---------- выгрузки ----------
SALES = ("Дата;Филиал;Услуга;Сумма\n" + "".join(
    f"2026-10-{d:02d};Север;Комплекс;{1500 + d}\n2026-10-{d:02d};Юг;Мойка кузова;900\n" for d in range(1, 29)))
CLIENTS = ("ФИО,Телефон,Последний визит,Визитов\n"
           "Петров Иван Иванович,+7 900 111-22-33,2026-08-01,7\n"
           "Анна Смирнова,+7 900 111-22-34,2026-10-30,2\n"
           "Олег,+7 900 111-22-35,2026-09-10,1\n")
DEBT = ("Контрагент,ИНН,Документ,Сумма,Оплачено,Срок оплаты\n"
        "ИП Сидоров Пётр,772211223344,УПД 1,10000,0,2026-09-01\n"
        "ООО «Ромашка»,7722112233,УПД 2,5000,1000,2026-12-31\n"
        "Мария Кузнецова,,УПД 3,3000,3000,2026-10-01\n")


def xlsx(rows, extra=None, doctype=False) -> bytes:
    strings, idx = [], {}

    def s(v):
        if v not in idx:
            idx[v] = len(strings)
            strings.append(v)
        return idx[v]
    cells = []
    for r, row in enumerate(rows, 1):
        cs = "".join(f'<c r="{chr(65 + c)}{r}"' + (f'><v>{v}</v></c>' if isinstance(v, int | float)
                                                   else f' t="s"><v>{s(v)}</v></c>') for c, v in enumerate(row))
        cells.append(f'<row r="{r}">{cs}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    dt = '<!DOCTYPE x [<!ENTITY a "aaaa">]>' if doctype else ""
    sheet = f'<?xml version="1.0"?>{dt}<worksheet {ns}><sheetData>{"".join(cells)}</sheetData></worksheet>'
    sst = f'<sst {ns}>' + "".join(f"<si><t>{v}</t></si>" for v in strings) + "</sst>"
    wb = (f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          '<sheets><sheet name="Лист1" sheetId="1" r:id="rId1"/></sheets></workbook>')
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr("xl/sharedStrings.xml", sst)
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    return buf.getvalue()


def rows_of(text: str):
    out = []
    for line in text.strip().splitlines():
        cells = line.split(";") if ";" in line else line.split(",")
        out.append([float(x) if x.replace(".", "").isdigit() and len(x) < 7 else x for x in cells])
    return out


@pytest.mark.parametrize("kind,text", [("sales", SALES), ("clients", CLIENTS), ("debtors", DEBT)])
@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_reports_three_kinds(kind, text, fmt):
    data = text.encode("utf-8") if fmt == "csv" else xlsx(rows_of(text))
    r = offer_report.build(data, today=date(2026, 11, 2))
    assert r["kind"] == kind and r["cards"] and r["tables"] and "error" not in r
    blob = json.dumps(r, ensure_ascii=False)
    for secret in ("900 111", "772211223344", "Смирнова", "Петров Иван", "Кузнецова"):
        assert secret not in blob
    if kind == "sales":
        assert "Выручка" in blob and "Север" in blob and "Динамика" in blob and "Топ позиций" in blob
    if kind == "clients":
        assert "Иван П." in blob and r["batch"] == 2 and "Телефон" in r["private"]
    if kind == "debtors":
        assert "ИП Сидоров П." in blob and "Пётр" not in blob and "ООО «Ромашка»" in blob and "Больше 30 дней" in blob
        assert r["cards"][0]["value"].startswith("14 000")                  # 10 000 + 4 000 (3 000 оплачено)


def test_cp1251_and_manual_mapping():
    data = "дата;точка;итог\n01.10.2026;А;100\n02.10.2026;Б;200\n".encode("cp1251")
    r = offer_report.build(data)
    assert r["kind"] == "sales" and r["cards"][0]["value"].startswith("300")
    with pytest.raises(offer_report.ReportError, match="Не понял"):
        offer_report.build(b"a,b\nx,5\ny,7\n")
    r = offer_report.build(b"who,when\nIvan Petrov,2026-10-01\n", kind="clients")
    assert "error" in r and r["columns"] == ["who", "when"]
    two = b"who,when\nIvan Petrov,2026-08-01\nAnna Lee,2026-10-30\n"
    r = offer_report.build(two, kind="clients", mapping={"client": 0, "date": 1})
    assert "Ivan P." in json.dumps(r)


def test_mask():
    m = offer_report.mask
    assert m("Иван Петров", 1) == "Иван П." and m("Петров Иван Иванович", 1) == "Иван П."
    assert m("+7 900 000-00-00", 3) == "Клиент №3" and m("a@b.ru", 4) == "Клиент №4"
    assert m("ООО «Ромашка»", 1) == "ООО «Ромашка»" and m("Олег", 1) == "Олег"


def test_bad_files_clear_errors():
    E = offer_report.ReportError
    with pytest.raises(E, match="пустой"):
        offer_report.build(b"")
    with pytest.raises(E, match="5 МБ"):
        offer_report.build(b"a" * (offer_report.MAX_BYTES + 1))
    with pytest.raises(E, match="повреждён"):
        offer_report.build(b"PK\x03\x04" + b"\x00" * 100)
    with pytest.raises(E, match="DOCTYPE"):
        offer_report.build(xlsx([["Сумма"], [1]], doctype=True))
    bomb = xlsx([["Сумма"], [1]], extra={"xl/media/big.bin": b"\x00" * (offer_report.XLSX_MAX_TOTAL + 1)})
    assert len(bomb) < 200_000
    with pytest.raises(E, match="после распаковки"):
        offer_report.build(bomb)
    many = xlsx([["Сумма"], [1]], extra={f"x/{i}.xml": "" for i in range(offer_report.XLSX_MAX_FILES)})
    with pytest.raises(E, match="много файлов"):
        offer_report.build(many)
    with pytest.raises(E, match="xls"):
        offer_report.build(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 50)
    with pytest.raises(E, match="CSV или XLSX"):
        offer_report.build(b"\x89PNG\r\n\x1a\n\x00\x00\x00")
    with pytest.raises(E, match="строк"):
        offer_report.build(("Сумма\n" + "1\n" * (offer_report.MAX_ROWS + 1)).encode())


def snapshot(root):
    return {(p, os.stat(os.path.join(p, f)).st_mtime_ns, f) for p, _, fs in os.walk(root) for f in fs}


def test_upload_in_memory_ttl_and_forget(server, tmp_path, monkeypatch):
    panel, base = server
    c = Client(base)
    code = make()
    c.json(f"/api/offer/{code}")
    before = snapshot(tmp_path)
    for kind, text in (("sales", SALES), ("clients", CLIENTS)):
        st, r, _ = c.json(f"/api/offer/{code}/upload", raw=text.encode(), headers={"X-Offer-Kind": kind})
        assert st == 200 and r["kind"] == kind and r["exp"] - r["at"] == offers.DEMO_TTL
    st, r, _ = c.json(f"/api/offer/{code}/upload", raw=xlsx(rows_of(DEBT)))
    assert st == 200 and r["kind"] == "debtors"
    st, r, _ = c.json(f"/api/offer/{code}/upload", raw=b"PK\x03\x04broken")
    assert st == 400 and "повреждён" in r["error"]
    assert snapshot(tmp_path) == before                                           # на диск — ничего
    _, d, _ = c.json(f"/api/offer/{code}")
    assert {x["kind"] for x in d["session"]["reports"]} == {"sales", "clients", "debtors"}
    other = Client(base)
    _, d2, _ = other.json(f"/api/offer/{code}")
    assert d2["session"]["reports"] == []                                         # чужая сессия не видит
    real = time.time
    monkeypatch.setattr(offers.time, "time", lambda: real() + offers.DEMO_TTL + 5)
    panel.offer_demos.sweep()
    assert panel.offer_demos.items == {}                                          # истекло — удалено
    monkeypatch.setattr(offers.time, "time", real)
    c.json(f"/api/offer/{code}")
    c.json(f"/api/offer/{code}/upload", raw=SALES.encode())
    st, r, h = c.json(f"/api/offer/{code}/forget", {})
    assert st == 200 and "Max-Age=0" in h["Set-Cookie"] and panel.offer_demos.items == {}


def test_upload_too_big_rejected_before_reading(server):
    _, base = server
    c = Client(base)
    code = make()
    st, r, _ = c.json(f"/api/offer/{code}/upload", raw=b"x" * (offer_report.MAX_BYTES + 10))
    assert st == 400 and "5 МБ" in r["error"]


# ---------- мастер и запрос владельцу ----------
def test_wizard_order_and_deny(server):
    panel, base = server
    c = Client(base)
    code = make()
    c.json(f"/api/offer/{code}")
    assert "условия" in c.json(f"/api/offer/{code}/login", {})[1]["error"]
    assert c.json(f"/api/offer/{code}/wizard", {"step": "terms", "version": "old"})[0] == 400
    c.json(f"/api/offer/{code}/wizard", {"step": "terms", "version": terms.VERSION})
    st, r, _ = c.json(f"/api/offer/{code}/wizard", {"step": "country", "code": "RU"})   # сервер в NL
    assert st == 400 and r["error"] == "Этот сервис недоступен в вашей стране по условиям поставщика"
    assert c.json(f"/api/offer/{code}/wizard", {"step": "module", "id": "night-shift"})[0] == 400
    c.json(f"/api/offer/{code}/wizard", {"step": "country", "code": "nl"})
    c.json(f"/api/offer/{code}/wizard", {"step": "module", "id": "carwash-morning"})
    st, r, _ = c.json(f"/api/offer/{code}/login", {})
    assert st == 200 and r["link"].startswith("https://t.me/test_bot?start=login_")
    nonce = r["link"].rsplit("login_", 1)[1]
    off = panel.logins.info(nonce)["offer"]
    assert off == {"business": "Автомойка «Пример»", "hint": code[:4] + "…", "module": "carwash-morning",
                   "module_title": modules.get("carwash-morning")["title"], "country": "NL", "terms": terms.VERSION}
    assert c.json(f"/api/login/tg?id={r['id']}")[1]["state"] == "wait"


@pytest.fixture
def pult(tmp_path, monkeypatch):
    p = bot.Pult(Config(token="1:T", owners=[1], project_roots=[str(tmp_path / "projects")]))
    p.sent = []
    p.send = lambda chat, text, **kw: p.sent.append((chat, text, kw))
    p.broadcast = lambda text, **kw: p.sent.append(("owners", text, kw))
    p.api = lambda method, **kw: {}

    class NoTmux:
        def __getattr__(self, name):
            raise AssertionError(f"tmux.{name} в демо/запросе — нельзя")
    p.tmux = NoTmux()
    p.open_session = lambda *a, **k: (_ for _ in ()).throw(AssertionError("сессия до одобрения"))
    return p


def cbs(kw) -> list[str]:
    return [b.get("callback_data", "") for row in kw.get("reply_markup", {}).get("inline_keyboard", []) for b in row]


def test_owner_request_marks_offer_and_grant_applies(pult, tmp_path):
    p = pult
    code = make()
    _rid, nonce = p.logins.start("1.2.3.4", "UA", offer={
        "business": "Автомойка «Пример»", "hint": offers.hint(code), "module": "carwash-return",
        "module_title": "Возврат", "country": "DE", "terms": terms.VERSION})
    p.on_message({"chat": {"id": 55}, "from": {"id": 55, "first_name": "Алексей"}, "text": f"/start login_{nonce}"})
    _, text, kw = next(x for x in p.sent if x[0] == "owners")
    assert "Автомойка «Пример»" in text and code[:4] + "…" in text and code not in text
    assert "«Возврат»" in text and "DE" in text and "pp:member:55" in cbs(kw)
    p.on_callback({"id": "q", "from": {"id": 1}, "message": {"chat": {"id": 1}}, "data": "pp:member:55"})
    assert p.people.role(55) == "member" and p.people.accepted(55) and p.people.country(55)["chosen"] == "DE"
    offer_msg = next(x for x in p.sent if x[0] == 1 and "of:55:carwash-return" in cbs(x[2]))
    assert "модель не потратится" in offer_msg[1]
    assert any("Поделиться номером" in json.dumps(x[2], ensure_ascii=False) for x in p.sent if x[0] == 55)
    p.on_callback({"id": "q", "from": {"id": 1}, "message": {"chat": {"id": 1}}, "data": "of:55:carwash-return"})
    folder = tmp_path / "projects" / "carwash-return"
    assert folder.is_dir() and modules.mark_of(folder)["by"] == 55
    p.on_callback({"id": "q", "from": {"id": 77}, "message": {"chat": {"id": 77}}, "data": "of:77:carwash-return"})
    assert not (tmp_path / "projects" / "carwash-return-2").exists()               # не владелец — ничего


# ---------- демо в Telegram ----------
def test_tg_token_ttl_and_starts(tmp_path, monkeypatch):
    t = offers.TgDemos(tmp_path / "tg.json")
    code = make()
    tok = t.issue(code, "carwash-return", "https://x/offer/" + code)
    assert offers.TOKEN.match(tok) and tok != code and code not in tok
    assert (tmp_path / "tg.json").stat().st_mode & 0o777 == 0o600
    assert len(f"/start demo_{tok}".split(" ", 1)[1]) <= 64
    for _ in range(offers.TG_STARTS):
        assert t.start(tok)
    assert t.start(tok) is None and t.get(tok)
    tok2 = t.issue(code, "carwash-return")
    real = time.time
    monkeypatch.setattr(offers.time, "time", lambda: real() + offers.TG_TTL + 1)
    assert t.get(tok2) is None and t.start(tok2) is None


def test_panel_issues_telegram_link(server):
    panel, base = server
    c = Client(base)
    code = make()
    st, r, _ = c.json(f"/api/offer/{code}/telegram", {"module": "carwash-return"})
    tok = r["link"].rsplit("demo_", 1)[1]
    assert st == 200 and r["link"].startswith("https://t.me/test_bot?start=demo_") and code not in r["link"]
    assert panel.offer_tg.get(tok)["code"] == code
    assert c.json(f"/api/offer/{code}/telegram", {"module": "night-shift"})[0] == 400


def test_scenario_default_and_from_section():
    o = {**offers.parse(json.loads(json.dumps({"business": "Мойка Тест", "industry": "carwash", "pains": ["x"],
                                               "modules": ["carwash-morning"]})), check_modules=False), "code": "c"}
    own = offers.scenario(o, modules.get("carwash-return"))
    assert len(own) == 4 and "Мойка Тест" in own[0]["text"] and "{{" not in json.dumps(own, ensure_ascii=False)
    assert "Отправить пачку из" in own[1]["text"]
    dflt = offers.scenario(o, modules.get("carwash-morning"))                        # секции нет — по умолчанию
    assert 3 <= len(dflt) <= 4 and "заявка" in dflt[0]["text"] and "пачку из" in dflt[1]["text"]
    assert "Утренние цифры" in dflt[2]["text"] and dflt[3]["buttons"]


def test_demo_isolated_buttons_and_connect(pult, tmp_path):
    p = pult
    code = make()
    tok = p.offer_tg.issue(code, "carwash-return", "https://pult.example/offer/" + code)
    stranger = {"id": 777, "first_name": "Гость"}
    start = {"update_id": 1, "message": {"chat": {"id": 777}, "from": stranger, "text": f"/start demo_{tok}"}}
    assert p.admitted(start)
    p.handle(start)
    texts = [t for c, t, _ in p.sent if c == 777]
    assert "Демо GASTECH" in texts[0] and "Заявка" in texts[1]
    first = next(kw for c, t, kw in p.sent if c == 777 and kw.get("reply_markup"))
    datas = cbs(first)
    assert all(len(d.encode()) <= 64 for d in datas) and all(d.startswith(f"dm:{tok}:0:") for d in datas)
    step = 0
    while True:                                                               # проходим сценарий кнопками
        p.sent.clear()
        p.handle({"update_id": 2, "callback_query": {"id": "q", "from": stranger, "message": {"chat": {"id": 777}},
                                                     "data": f"dm:{tok}:{step}:0"}})
        last = p.sent[-1][2]
        if "dm:" + tok + ":f:c" in cbs(last):
            break
        step += 1
        assert step < 6
    assert any(b.get("url", "").endswith(code) for row in last["reply_markup"]["inline_keyboard"] for b in row)
    assert all(len(d.encode()) <= 64 for d in cbs(last))
    assert not any(c == "owners" for c, *_ in p.sent)                          # владельцу — ничего без «Подключить»
    assert p.people.role(777) is None
    for upd in ({"text": "/menu"}, {"text": "/modules"}, {"text": "привет"}, {"voice": {"file_id": "v"}},
                {"text": "/start"}):
        u = {"update_id": 3, "message": {"chat": {"id": 777}, "from": stranger, **upd}}
        assert not p.admitted(u)                                              # дальше — обычный незнакомец
    assert not p.admitted({"update_id": 4, "callback_query": {"id": "q", "from": stranger, "data": "md:list:"}})
    p.sent.clear()
    p.handle({"update_id": 5, "callback_query": {"id": "q", "from": stranger, "message": {"chat": {"id": 777}},
                                                 "data": f"dm:{tok}:f:c"}})
    _, text, kw = next(x for x in p.sent if x[0] == "owners")
    assert "Мойка" in text or "Пример" in text
    assert code[:4] + "…" in text and code not in text and "pp:member:777" in cbs(kw)
    p.handle({"update_id": 6, "callback_query": {"id": "q", "from": stranger, "message": {"chat": {"id": 777}},
                                                 "data": f"dm:{tok}:f:c"}})
    assert sum(1 for x in p.sent if x[0] == "owners") == 1                      # второй раз — не дублируем
    p.sent.clear()
    p.handle({"update_id": 7, "callback_query": {"id": "q", "from": stranger, "message": {"chat": {"id": 777}},
                                                 "data": "dm:" + "x" * 24 + ":0:0"}})
    assert p.sent[-1][1] == bot.DEMO_GONE
    offers.revoke(code)
    p.handle({"update_id": 8, "callback_query": {"id": "q", "from": stranger, "message": {"chat": {"id": 777}},
                                                 "data": f"dm:{tok}:0:0"}})
    assert p.sent[-1][1] == bot.DEMO_GONE


def test_demo_rate_limit_per_person(pult):
    p = pult
    code = make()
    tok = p.offer_tg.issue(code, "carwash-return")
    for _i in range(bot.DEMO_RATE[0] + 1):
        p.on_message({"chat": {"id": 9}, "from": {"id": 9}, "text": f"/start demo_{tok}"})
    assert "не чаще" in p.sent[-1][1]


# ---------- CLI ----------
def test_cli_new_list_revoke(tmp_path, capsys):
    cli.main(["offer", "new", "--name", "Фитнес «Тест»", "--url", "https://pult.example:8443/", "--expires",
              "2030-01-01"])
    out = capsys.readouterr().out
    code = out.split("/offer/", 1)[1].split()[0]
    assert offers.CODE.match(code) and "https://pult.example:8443/offer/" + code in out
    cli.main(["offer", "list"])
    out = capsys.readouterr().out
    assert code in out and "Фитнес «Тест»" in out and "2030-01-01" in out
    tpl = tmp_path / "t.toml"
    cli.main(["offer", "example"])
    tpl.write_text(capsys.readouterr().out.replace("carwash-reviews", "carwash-fleet"), encoding="utf-8")
    cli.main(["offer", "new", str(tpl)])
    assert "Путь: /offer/" in capsys.readouterr().out
    cli.main(["offer", "revoke", code])
    assert offers.load(code) is None
    with pytest.raises(SystemExit, match="нет такого"):
        cli.main(["offer", "revoke", code])
    with pytest.raises(SystemExit, match="ГГГГ-ММ-ДД"):
        cli.main(["offer", "new", "--name", "x", "--expires", "завтра"])
