"""Лёгкий вход без Telegram (задача 34): ссылка, QR и короткий код одного приглашения → «Как вас зовут?» → панель.

Проверяем: код без похожих знаков, одноразовость (ссылка и код сгорают вместе), перебор (6-я неверная попытка с одного
IP — 429), отзыв (сессии гаснут сразу), ссылка для входа на другое устройство, «Привязать Telegram» (перенос записи),
гость не получает сообщений в Telegram, в журнале нет кодов, QR — структура и сверка с qrencode/zbarimg, если есть.
"""

import json
import re
import shutil
import struct
import subprocess
import threading
import urllib.error
import urllib.request
import zlib
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import bot, cli, invites, people, qr, tenants, webapp, webauth
from gas_pult.config import Config

OWNER, TG = 7301, 7302


@pytest.fixture(autouse=True)
def dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    root = tmp_path / "tenants"
    monkeypatch.setenv("GAS_PULT_TENANTS_ROOT", str(root))
    for slug, title in (("demo", "Планета"), ("cafe", "Демо для кафе"), ("solo", "Обои")):
        (root / slug).mkdir(parents=True)
        (root / slug / tenants.META).write_text(json.dumps({"title": title}))
    (root / tenants.MARKER).write_text("{}")
    return tmp_path


class FakeApi:
    def __init__(self):
        self.calls = []

    def __call__(self, method, files=None, **params):
        self.calls.append((method, params, files))
        return {"type": "web_app", "web_app": {"url": "https://panel.example:8443/"}} \
            if method == "getChatMenuButton" else {}

    def redact(self, text):
        return str(text)

    def texts(self, chat=None):
        return [x.get("text", "") for m, x, _ in self.calls
                if m == "sendMessage" and (chat is None or x["chat_id"] == chat)]


@pytest.fixture
def web():
    p = webapp.Panel(Config(token="1:T", owners=[OWNER], region="NL"))
    p.people.accept(OWNER)
    p.people.set_country(OWNER, chosen="NL")
    p.bot_username = lambda: "test_bot"
    p.pult.api = FakeApi()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield p, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def req(base, path, body=None, token="", ip="198.51.100.7"):
    h = {"X-Forwarded-For": ip}                     # запрос с 127.0.0.1 — адрес клиента из заголовка прокси
    if token:
        h["Cookie"] = f"{webauth.COOKIE}={token}"
    r = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None, h)
    try:
        x = urllib.request.urlopen(r)
    except urllib.error.HTTPError as e:
        x = e
    raw = x.read()
    code = x.status if hasattr(x, "status") else x.code
    return code, x.headers, json.loads(raw) if raw[:1] in (b"{", b"[") else raw


def cookie(h) -> str:
    m = re.search(rf"{webauth.COOKIE}=([^;]+)", h.get("Set-Cookie", ""))
    return m.group(1) if m else ""


def guest_ready(p, uid):
    p.people.accept(uid)
    p.people.set_country(uid, chosen="NL")


# ---------- короткий код ----------
def test_short_code_has_no_lookalikes():
    for _ in range(300):
        c = invites.short_code("cafe")
        assert not set(c) & set("0O1I"), c
        assert re.fullmatch(r"[A-Z]{3,10}-[2-9]{6}", c)
    assert invites.word_of("demo") == "PLANETA"                       # «Планета» латиницей
    assert invites.word_of("cafe") == "CAFE"                         # «Демо» — есть O → имя пространства
    assert invites.word_of("solo") in invites.WORDS                  # и в имени O → нейтральное слово
    assert all(not set(w) & set("OI") for w in invites.WORDS)
    inv = invites.new("demo")
    assert inv["short"].startswith("PLANETA-")
    raw = invites.store().read_text()
    assert inv["short"] not in raw and invites.norm_short(inv["short"]) not in raw and inv["code"] not in raw
    assert invites.check(inv["short"].lower().replace("-", " "))      # регистр, пробелы и дефисы — не важны


# ---------- одноразовость ----------
def test_link_and_code_burn_together(web):
    p, base = web
    inv = invites.new("demo")
    info = req(base, f"/api/invite?code={inv['code']}")[2]
    assert info["ok"] and info["guest"] and info["kind"] == "invite" and info["title"] == "Планета"
    assert req(base, "/api/invite/enter", {"code": inv["code"], "name": "  "})[0] == 400   # без имени — нельзя
    st, h, d = req(base, "/api/invite/enter", {"code": inv["code"], "name": "Анна"})
    assert st == 200 and d["state"] == "ok"
    tok = cookie(h)
    assert "Max-Age=2592000" in h["Set-Cookie"] and "HttpOnly" in h["Set-Cookie"]   # 30 дней
    uid = p.auth.uid(tok)
    assert people.is_guest(uid) and not people.has_telegram(uid)
    rec = next(x for x in p.people.list() if x["id"] == uid)
    assert rec["kind"] == "guest" and rec["name"] == "Анна" and rec["tenant"] == "demo" and rec["role"] == "member"
    assert rec["last"]["device"] and rec["last"]["at"]
    guest_ready(p, uid)
    m = req(base, "/api/meta", token=tok)[2]
    assert m["space"]["slug"] == "demo" and m["uid"] == uid
    # второй раз — ни ссылкой, ни коротким кодом
    assert req(base, "/api/invite/enter", {"code": inv["code"], "name": "Борис"})[0] == 400
    assert req(base, "/api/invite/enter", {"code": inv["short"], "name": "Борис"})[0] == 400
    assert req(base, f"/api/invite?code={inv['code']}")[2] == {"ok": False}
    # и наоборот: вошли коротким кодом — сгорела и ссылка
    inv2 = invites.new("demo", "viewer")
    st, h, _ = req(base, "/api/invite/enter", {"code": inv2["short"], "name": "Вера"}, ip="198.51.100.8")
    assert st == 200 and p.people.role(p.auth.uid(cookie(h))) == "viewer"
    assert req(base, "/api/invite/enter", {"code": inv2["code"], "name": "Галя"}, ip="198.51.100.8")[0] == 400
    assert any("без Telegram" in t and "Анна" in t for t in p.pult.api.texts(OWNER))   # владельцу — кто и откуда


# ---------- перебор ----------
def test_bruteforce_sixth_wrong_attempt_is_429(web, capfd):
    _p, base = web
    inv = invites.new("demo")
    for i in range(5):
        st, _, d = req(base, "/api/invite/check", {"code": f"PLANETA-22222{i + 2}"})
        assert st == 400, d
    st, _, d = req(base, "/api/invite/check", {"code": "PLANETA-999999"})
    assert st == 429 and d["retry"] > 0
    # и правильный код с этого адреса — тоже подождать; с другого адреса — работает
    assert req(base, "/api/invite/enter", {"code": inv["short"], "name": "Анна"})[0] == 429
    st, _, d = req(base, "/api/invite/check", {"code": inv["short"]}, ip="203.0.113.5")
    assert st == 200 and d["ok"] and d["title"] == "Планета"
    # в журнале — ни кода приглашения, ни введённых кодов целиком
    err = capfd.readouterr().err
    assert "invite_failed" in err
    assert inv["code"] not in err and "222222" not in err and "999999" not in err


def test_global_limit_across_ips():
    m = invites.Misses(per_ip=5, window=600, total=30)
    for i in range(30):
        m.miss(f"10.0.0.{i}")
    assert m.blocked("10.9.9.9") > 0                         # с разных адресов вместе — тоже не больше 30


def test_disabled_spaces_hide_easy_login(web, dirs):
    _p, base = web
    inv = invites.new("demo")
    (dirs / "tenants" / tenants.MARKER).unlink()
    st, _, d = req(base, "/api/invite/enter", {"code": inv["code"], "name": "Анна"})
    assert st == 400 and "выключен" in d["error"]
    assert invites.check(inv["code"])                        # приглашение не сгорело


def test_short_code_only_where_attempts_are_limited(web):
    """Короткий код угадать проще ссылки: где нет лимита попыток (GET /api/invite, Telegram, QR), он не работает."""
    _p, base = web
    inv = invites.new("demo")
    assert req(base, f"/api/invite?code={inv['short']}")[2] == {"ok": False}
    assert req(base, "/api/login/tg", {"invite": inv["short"]})[0] == 400
    assert req(base, "/api/login/tg", {"invite": inv["code"]})[0] == 200
    assert invites.check(inv["short"], short=False) is None and invites.check(inv["short"])


# ---------- отзыв ----------
def test_revoke_kills_sessions_at_once(web):
    p, base = web
    inv = invites.new("demo")
    _, h, _ = req(base, "/api/invite/enter", {"code": inv["code"], "name": "Анна"})
    tok = cookie(h)
    uid = p.auth.uid(tok)
    guest_ready(p, uid)
    tok2 = p.auth.issue(uid)                                 # второе устройство
    dev = invites.new("demo", uid=uid)                       # и невыданная ссылка для входа
    assert req(base, "/api/meta", token=tok)[0] == 200
    owner = p.auth.issue(OWNER)
    ppl = req(base, "/api/people", token=owner)[2]["people"]
    g = next(x for x in ppl if x["id"] == uid)
    assert g["kind"] == "guest" and g["last"]["device"]      # владелец видит: имя, устройство, время
    assert req(base, "/api/people/remove", {"id": uid}, owner)[0] == 200
    assert req(base, "/api/meta", token=tok)[0] == 401
    assert req(base, "/api/meta", token=tok2)[0] == 401
    assert p.auth.uid(tok) is None and p.auth.uid(tok2) is None
    assert invites.check(dev["code"]) is None


# ---------- другое устройство ----------
def test_device_link(web):
    p, base = web
    inv = invites.new("demo")
    _, h, _ = req(base, "/api/invite/enter", {"code": inv["code"], "name": "Анна"})
    tok = cookie(h)
    uid = p.auth.uid(tok)
    guest_ready(p, uid)
    st, _, d = req(base, "/api/invite/device", {}, tok)
    assert st == 200 and d["path"].startswith("/invite/") and re.fullmatch(r"[A-Z]+-[2-9]{6}", d["code"])
    link = d["path"].split("/")[-1]
    assert req(base, f"/api/invite?code={link}")[2]["kind"] == "device"
    assert req(base, f"/api/invite?code={link}")[2]["name"] == "Анна"
    # QR своей ссылки — можно; чужой (приглашения владельца) — нет
    st, h, png = req(base, f"/api/invite/qr?u=https://panel.example{d['path']}", token=tok)
    assert st == 200 and h["Content-Type"] == "image/png" and png[:8] == b"\x89PNG\r\n\x1a\n"
    assert req(base, f"/api/invite/qr?u=https://panel.example/invite/{inv['code']}", token=tok)[0] == 404
    st, h, _ = req(base, "/api/invite/enter", {"code": d["code"]}, ip="203.0.113.9")   # имя не спрашиваем
    assert st == 200 and p.auth.uid(cookie(h)) == uid
    assert req(base, "/api/invite/enter", {"code": link}, ip="203.0.113.9")[0] == 400   # один раз
    # владелец выпускает ссылку для человека; без входа — нельзя
    owner = p.auth.issue(OWNER)
    assert req(base, "/api/invite/device", {"id": uid}, owner)[0] == 200
    assert req(base, "/api/invite/device", {"id": uid})[0] == 401
    assert req(base, "/api/invite/device", {"id": OWNER}, owner)[0] == 400


def test_owner_invite_gives_link_code_and_qr(web):
    p, base = web
    owner = p.auth.issue(OWNER)
    st, _, d = req(base, "/api/invite/new", {"space": "demo"}, owner)
    assert st == 200 and d["code"].startswith("PLANETA-") and invites.check(d["code"])
    st, _h, png = req(base, f"/api/invite/qr?u=https://panel.example{d['path']}", token=owner)
    assert st == 200 and png[:8] == b"\x89PNG\r\n\x1a\n"
    assert req(base, f"/api/invite/qr?u=https://panel.example{d['path']}")[0] == 401
    assert req(base, "/api/invite/qr?u=javascript:alert(1)", token=owner)[0] == 404


# ---------- Telegram: привязка и рассылки ----------
def test_link_telegram_moves_record():
    pult = bot.Pult(Config(token="t", owners=[1], session="test"))
    pult.api = FakeApi()
    inv = invites.new("demo")
    g = pult.people.add_guest("Анна", "member", "demo")
    assert invites.redeem(inv["code"], g)
    pult.people.accept(g)
    pult.people.set_country(g, chosen="NL")
    pult.people.set_prefs(g, simple=True)
    pult.web_sessions().issue(g)
    rid, nonce = pult.logins.start("1.2.3.4", "Safari", link=g)
    u = {"id": TG, "first_name": "Анна", "username": "anna"}
    pult.login_request({"from": u, "chat": {"id": TG}}, nonce)
    assert any("Привязать этот Telegram" in t for t in pult.api.texts(TG))
    assert pult.people.role(TG) is None                       # пока человек не нажал — ничего
    pult.on_callback({"id": "q", "from": u, "message": {"chat": {"id": TG}}, "data": f"lk:ok:{nonce}"})
    assert pult.people.role(TG) == "member" and pult.people.tenant(TG) == "demo"
    assert pult.people.accepted(TG) and pult.people.country(TG)["chosen"] == "NL" and pult.people.prefs(TG)["simple"]
    assert pult.people.role(g) is None                        # гость исчез, его сессии погашены
    assert pult.logins.poll(rid) == ("ok", TG)                # браузер получает сессию уже по Telegram
    assert any(m == "setChatMenuButton" and x["chat_id"] == TG for m, x, _ in pult.api.calls)
    # Telegram, который уже в пульте, к гостю не привязать
    g2 = pult.people.add_guest("Борис", "member", "demo")
    _, n2 = pult.logins.start("1.2.3.4", "Safari", link=g2)
    pult.login_request({"from": u, "chat": {"id": TG}}, n2)
    assert any("уже есть в пульте" in t for t in pult.api.texts(TG))


def test_guest_gets_no_telegram_messages():
    pult = bot.Pult(Config(token="t", owners=[1], session="test"))
    g = pult.people.add_guest("Анна", "member", "demo")
    with pytest.raises(ValueError):
        pult.ask_notify_done("@1", g)
    assert people.GUEST_FLOOR < 0 and g <= people.GUEST_FLOOR and g != webauth.LEGACY
    assert not people.has_telegram(g) and people.has_telegram(TG) and not people.has_telegram(webauth.LEGACY)


def test_bot_invite_sends_qr_photo():
    pult = bot.Pult(Config(token="t", owners=[1], session="test"))
    pult.api = FakeApi()
    pult.send_invite(1, "demo")
    _m, x, files = next(c for c in pult.api.calls if c[0] == "sendPhoto")
    assert files["photo"][1][:8] == b"\x89PNG\r\n\x1a\n"
    assert "https://panel.example:8443/invite/" in x["caption"] and "PLANETA-" in x["caption"]


def test_cli_prints_link_code_and_qr(capsys):
    cli.main(["invite", "create", "demo", "--url", "https://panel.example"])
    out = capsys.readouterr().out
    link = re.search(r"https://panel\.example/invite/(\S+)", out).group(1)
    short = re.search(r"Код:\s+(\S+)", out).group(1)
    path = re.search(r"QR:\s+(\S+\.png)", out).group(1)
    assert invites.check(link) and invites.check(short) and short.startswith("PLANETA-")
    from pathlib import Path
    f = Path(path)
    assert f.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and f.stat().st_mode & 0o777 == 0o600
    assert f.parent.stat().st_mode & 0o777 == 0o700


# ---------- QR ----------
def unpng(data: bytes) -> tuple[int, list[bytes]]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    w, h, depth, color = struct.unpack(">IIBB", data[16:26])
    assert w == h and depth == 8 and color == 0
    at, idat = 8, b""
    while at < len(data):
        n = struct.unpack(">I", data[at:at + 4])[0]
        kind, body = data[at + 4:at + 8], data[at + 8:at + 8 + n]
        assert zlib.crc32(kind + body) & 0xFFFFFFFF == struct.unpack(">I", data[at + 8 + n:at + 12 + n])[0]
        idat += body if kind == b"IDAT" else b""
        at += 12 + n
    raw = zlib.decompress(idat)
    return w, [raw[i * (w + 1) + 1:(i + 1) * (w + 1)] for i in range(h)]


def finder_ok(m, x0, y0) -> bool:
    for dy in range(7):
        for dx in range(7):
            ring = max(abs(dx - 3), abs(dy - 3))
            if m[y0 + dy][x0 + dx] != (ring != 2):
                return False
    return True


def read_format(m) -> tuple[int, int]:
    """Уровень коррекции и маска из 15 бит формата у левого верхнего узора."""
    bits = [m[i][8] for i in range(6)] + [m[7][8], m[8][8], m[8][7]] + [m[8][14 - i] for i in range(9, 15)]
    v = sum(int(b) << i for i, b in enumerate(bits)) ^ 0x5412
    return v >> 13, (v >> 10) & 7


@pytest.mark.parametrize("n", [20, 60, 120, 213])
def test_qr_structure(n):
    text = ("https://panel.example:8443/invite/" + "AbC-_9" * 40)[:n]
    m = qr.encode(text)
    size = len(m)
    assert (size - 17) % 4 == 0 and 1 <= (size - 17) // 4 <= 10
    for x0, y0 in ((0, 0), (size - 7, 0), (0, size - 7)):
        assert finder_ok(m, x0, y0)
    assert [m[6][i] for i in range(8, size - 8)] == [i % 2 == 0 for i in range(8, size - 8)]   # синхронизация
    ec, mask = read_format(m)
    assert ec == qr.EC_M and 0 <= mask < 8
    assert m[size - 8][8] is True                                                          # тёмный модуль
    w, rows = unpng(qr.png(m, scale=4))
    assert w == (size + 8) * 4
    assert rows[0] == b"\xff" * w                                                          # тихая зона
    assert rows[16][16] == 0                                                               # угол поискового узора
    with pytest.raises(ValueError):
        qr.encode("x" * 300)


@pytest.mark.skipif(not shutil.which("qrencode"), reason="нет qrencode — сверка с эталоном пропущена")
@pytest.mark.parametrize("n", [14, 60, 150, 213])
def test_qr_matches_qrencode(n):
    """Та же матрица, что у libqrencode (с какой-то из 8 масок: выбор маски у них свой)."""
    text = ("https://panel.example:8443/invite/" + "AbC-_9" * 40)[:n]
    out = subprocess.run(["qrencode", "-8", "-l", "M", "-m", "0", "-t", "ASCII", text],
                         capture_output=True, text=True, check=True).stdout
    ref = [[row[i] == "#" for i in range(0, len(row), 2)] for row in out.splitlines() if row]
    assert any(qr.encode(text, k) == ref for k in range(8))


@pytest.mark.skipif(not shutil.which("zbarimg"), reason="нет zbarimg — декодирование PNG пропущено")
def test_qr_decodes_with_zbar(tmp_path):
    link = "https://panel.example:8443/invite/" + invites.create("demo")
    f = tmp_path / "q.png"
    f.write_bytes(qr.png_of(link))
    out = subprocess.run(["zbarimg", "--raw", "-q", str(f)], capture_output=True, text=True).stdout.strip()
    assert out == link
