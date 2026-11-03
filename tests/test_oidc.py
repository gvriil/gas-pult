"""Вход через Google и Яндекс ID (oidc.py): то, что легко сломать.

Подпись RS256 проверяется по-настоящему (ключ RSA собран здесь же на стандартной библиотеке), state одноразовый
и привязан к браузеру, PKCE S256, nonce, только openid email profile, вход только человеку с ролью и только
при подтверждённом адресе или явной привязке, одинаковый ответ, лимит по IP, выключено без настроек, права
эндпоинтов. Сеть к Google и Яндексу подменена — настоящих запросов тесты не делают.
"""

import base64
import hashlib
import http.client
import json
import random
import threading
import time
import urllib.parse
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import config, oidc, providers, webapp, webauth
from gas_pult.config import Config
from gas_pult.people import People

GOOGLE = {"client_id": "cid-g.apps.example", "client_secret": "sec-g",
          "redirect_uri": "https://pult.example.test:8443/api/login/oidc/google/back"}
YANDEX = {"client_id": "cid-y", "client_secret": "sec-y",
          "redirect_uri": "https://pult.example.test:8443/api/login/oidc/yandex/back"}


# ---------- RSA на стандартной библиотеке: только для тестов ----------
def _prime(bits: int, rnd: random.Random) -> int:
    small = [p for p in range(3, 2000, 2) if all(p % q for q in range(3, int(p ** 0.5) + 1, 2))]
    while True:
        n = rnd.getrandbits(bits) | (1 << (bits - 1)) | (1 << (bits - 2)) | 1
        if any(n % p == 0 for p in small):
            continue
        d, r = n - 1, 0
        while d % 2 == 0:
            d, r = d // 2, r + 1
        for _ in range(20):
            x = pow(rnd.randrange(2, n - 2), d, n)
            if x in (1, n - 1):
                continue
            for _ in range(r - 1):
                x = pow(x, 2, n)
                if x == n - 1:
                    break
            else:
                break
        else:
            return n


class Rsa:
    def __init__(self, seed: int, bits: int = 2048):
        rnd = random.Random(seed)
        while True:
            p, q = _prime(bits // 2, rnd), _prime(bits // 2, rnd)
            n, phi = p * q, (p - 1) * (q - 1)
            if p != q and n.bit_length() == bits and phi % 65537:
                break
        self.n, self.e, self.d = n, 65537, pow(65537, -1, phi)

    def sign(self, msg: bytes) -> bytes:
        k = (self.n.bit_length() + 7) // 8
        t = oidc.SHA256_PREFIX + hashlib.sha256(msg).digest()
        em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
        return pow(int.from_bytes(em, "big"), self.d, self.n).to_bytes(k, "big")

    def jwk(self, kid: str) -> dict:
        b = lambda i: oidc.b64url(i.to_bytes((i.bit_length() + 7) // 8, "big"))   # noqa: E731
        return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid, "n": b(self.n), "e": b(self.e)}


@pytest.fixture(scope="module")
def keys():
    return Rsa(1), Rsa(2)


def jwt(key: Rsa, claims: dict, kid: str = "k1", alg: str = "RS256") -> str:
    h = oidc.b64url(json.dumps({"alg": alg, "kid": kid, "typ": "JWT"}).encode())
    c = oidc.b64url(json.dumps(claims).encode())
    return f"{h}.{c}.{oidc.b64url(key.sign(f'{h}.{c}'.encode()))}"


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


def claims(nonce: str, now: float, **kw) -> dict:
    return {"iss": "https://accounts.google.com", "aud": GOOGLE["client_id"], "azp": GOOGLE["client_id"],
            "sub": "g-100", "email": "Ivan@Example.test", "email_verified": True, "iat": int(now),
            "exp": int(now) + 3600, "nonce": nonce, **kw}


class Fake:
    """Google и Яндекс понарошку: токен, JWKS, login.yandex.ru/info. ``who`` — что вернёт провайдер."""

    def __init__(self, key: Rsa, clock: Clock):
        self.key, self.clock, self.calls = key, clock, []
        self.who: dict = {}
        self.extra: dict = {}
        self.yandex: dict = {"id": "y-7", "default_email": "ivan@yandex.ru", "client_id": YANDEX["client_id"]}
        self.nonce = ""

    def __call__(self, url, data=None, headers=None):
        self.calls.append((url, data, headers))
        if url == oidc.PROVIDERS["google"]["jwks"]:
            return {"keys": [self.key.jwk("k1"), {"kty": "EC", "kid": "ec"}]}
        if url == oidc.PROVIDERS["google"]["token"]:
            return {"access_token": "at", "id_token": jwt(self.key, {**claims(self.nonce, self.clock()), **self.who},
                                                          **self.extra)}
        if url == oidc.PROVIDERS["yandex"]["token"]:
            return {"access_token": "y-at"}
        if url == oidc.PROVIDERS["yandex"]["info"]:
            assert headers == {"Authorization": "OAuth y-at"}
            return self.yandex
        raise AssertionError(url)


@pytest.fixture(autouse=True)
def dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture
def svc(tmp_path, keys):
    people = People(tmp_path / "people.json", [1])
    people.add(2, "member", "Иван")
    people.add(3, "viewer", "Пётр")
    people.set_email(2, address="ivan@example.test", at=1)
    clock = Clock()
    fake = Fake(keys[0], clock)
    s = oidc.Oidc({"google": dict(GOOGLE), "yandex": dict(YANDEX)}, people, tmp_path / "oidc.json", clock=clock,
                  fetch=fake)
    s.fake, s.people_ = fake, people
    return s


def query(url: str) -> dict:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))


def go(s, p="google", ip="198.51.100.1", link="", **who) -> tuple[dict, str, dict]:
    """Начать вход, «сходить» к провайдеру и вернуться: (параметры адреса провайдера, cookie браузера, итог)."""
    url, browser = s.start(p, ip, link)
    q = query(url)
    s.fake.nonce, s.fake.who = q.get("nonce", ""), who
    return q, browser, s.finish(p, {"code": "c-1", "state": q["state"]}, browser, ip)


# ---------- подпись RS256 ----------
def test_rsa_verify_pkcs1_sha256(keys):
    k, other = keys
    sig = k.sign(b"hello")
    assert oidc.rsa_verify(k.n, k.e, b"hello", sig)
    assert not oidc.rsa_verify(k.n, k.e, b"hellO", sig)                    # другое сообщение
    assert not oidc.rsa_verify(other.n, other.e, b"hello", sig)            # другой ключ
    assert not oidc.rsa_verify(k.n, k.e, b"hello", sig[:-1])               # не та длина
    assert not oidc.rsa_verify(k.n, k.e, b"hello", (k.n + 1).to_bytes(256, "big"))   # s ≥ n
    bad = bytearray(sig)
    bad[10] ^= 1
    assert not oidc.rsa_verify(k.n, k.e, b"hello", bytes(bad))
    assert not oidc.rsa_verify(k.n, 3, b"hello", sig) and not oidc.rsa_verify(k.n, 4, b"hello", sig)


def test_rsa_short_keys_refused():
    small = Rsa(3, bits=1024)
    assert not oidc.rsa_verify(small.n, small.e, b"x", small.sign(b"x"))   # меньше 2048 бит — не доверяем


def test_id_token_checks(keys):
    k, other = keys
    now, nonce = 1_800_000_000.0, "n-1"
    get = {"k1": (k.n, k.e)}.get
    ok = lambda c, key=k, **kw: oidc.verify_id_token(jwt(key, c, **kw), get, GOOGLE["client_id"], nonce,   # noqa: E731
                                                     oidc.PROVIDERS["google"]["issuers"], now)
    assert ok(claims(nonce, now))["sub"] == "g-100"
    assert ok(claims(nonce, now, iss="accounts.google.com", aud=[GOOGLE["client_id"]]))["sub"] == "g-100"
    for bad, why in [((claims(nonce, now), other), "подпись"),
                     ((claims(nonce, now, iss="https://evil.example"),), "iss"),
                     ((claims(nonce, now, aud="other"),), "aud"),
                     ((claims(nonce, now, aud=[GOOGLE["client_id"], "x"], azp="x"),), "azp"),
                     ((claims(nonce, now, azp="other"),), "azp"),
                     ((claims(nonce, now, exp=now - 600),), "просрочен"),
                     ((claims(nonce, now, iat=now + 3600),), "просрочен"),
                     ((claims("n-2", now),), "nonce"),
                     ((claims(nonce, now, sub=""),), "sub")]:
        with pytest.raises(ValueError, match=why):
            ok(*bad)
    with pytest.raises(ValueError, match="подпись"):                          # неизвестный kid
        ok(claims(nonce, now), kid="k9")
    for alg in ("none", "HS256", "RS512"):
        with pytest.raises(ValueError, match="RS256"):
            ok(claims(nonce, now), alg=alg)
    h = oidc.b64url(b'{"alg":"none"}')
    c = oidc.b64url(json.dumps(claims(nonce, now)).encode())
    with pytest.raises(ValueError):
        oidc.verify_id_token(f"{h}.{c}.", get, GOOGLE["client_id"], nonce, ("https://accounts.google.com",), now)
    with pytest.raises(ValueError, match="JWT"):
        oidc.verify_id_token("abc", get, GOOGLE["client_id"], nonce, ("https://accounts.google.com",), now)


def test_parse_jwks_only_rsa_sig(keys):
    k = keys[0]
    got = oidc.parse_jwks({"keys": [k.jwk("a"), {**k.jwk("b"), "use": "enc"}, {"kty": "EC", "kid": "c"},
                                    {**k.jwk("d"), "alg": "RS512"}, {"kty": "RSA", "kid": "e"}]})
    assert got == {"a": (k.n, k.e)}
    assert oidc.parse_jwks(None) == {} and oidc.parse_jwks([]) == {}


# ---------- настройки ----------
def test_disabled_without_settings(tmp_path):
    s = oidc.Oidc({}, None, tmp_path / "o.json")
    assert s.methods() == {"google": False, "yandex": False}
    with pytest.raises(RuntimeError, match="не настроен"):
        s.start("google")
    s = oidc.Oidc({"google": {"client_id": "x"}}, None, tmp_path / "o.json", base=lambda: "https://p.example.test")
    assert not s.enabled("google")                                            # нет секрета
    providers.save_key(oidc.secret_key("google"), "from-secrets")
    assert s.settings("google") == {"client_id": "x", "secret": "from-secrets",
                                    "redirect_uri": "https://p.example.test/api/login/oidc/google/back"}
    s.base = lambda: ""
    assert not s.enabled("google")                                            # нет адреса панели — выключено
    s.base = lambda: "http://pult.example.test"
    assert not s.enabled("google")                                            # только https (или localhost)
    with pytest.raises(LookupError):
        s.need("facebook")


def test_internal_secrets_hidden_from_keys():
    providers.save_key(oidc.secret_key("google"), "s1")
    providers.save_key(oidc.secret_key("yandex"), "s2")
    assert providers.key_info() == {}


def test_config_sections(tmp_path):
    d = tmp_path / "cfg"
    d.mkdir(exist_ok=True)
    (d / "token").write_text("1:T")
    (d / "config.toml").write_text('owners = [1]\n\n[google]\nclient_id = "g"\n\n[yandex]\nclient_id = "y"\n')
    cfg = config.load()
    assert cfg.google == {"client_id": "g"} and cfg.yandex == {"client_id": "y"}
    (d / "config.toml").write_text('owners = [1]\n[google]\nscope = "https://www.googleapis.com/auth/drive"\n')
    with pytest.raises(config.ConfigError, match="Неизвестные ключи в \\[google\\]"):   # права не настраиваются
        config.load()


def test_cli_status_and_secret(tmp_path, monkeypatch, capsys):
    from gas_pult import cli

    d = tmp_path / "cfg"
    d.mkdir(exist_ok=True)
    (d / "token").write_text("1:T")
    (d / "config.toml").write_text('owners = [1]\n\n[google]\nclient_id = "abc-123456"\n')
    cli.main(["oidc", "status"])
    out = capsys.readouterr().out
    assert "Google: выключен" in out and "gas-pult oidc secret google" in out and "Яндекс ID: выключен" in out
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "  s3cret  ")
    cli.main(["oidc", "secret", "google"])
    assert providers.load_keys()[oidc.secret_key("google")] == "s3cret"
    cli.main(["oidc", "status", "--url", "https://p.example.test:8443"])
    out = capsys.readouterr().out
    assert "Google: включён" in out and "https://p.example.test:8443/api/login/oidc/google/back" in out
    assert "s3cret" not in out
    with pytest.raises(SystemExit):
        cli.main(["oidc", "secret", "facebook"])


def test_provider_garbage_is_a_clean_error(svc):
    url, browser = svc.start("yandex")
    svc.fake.yandex = {"id": None}
    with pytest.raises(ValueError, match="Не удалось проверить"):
        svc.finish("yandex", {"code": "c", "state": query(url)["state"]}, browser)


# ---------- начало входа ----------
def test_start_url_scope_pkce_state(svc, tmp_path):
    url, browser = svc.start("google", "198.51.100.1")
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    q = query(url)
    assert q["scope"] == "openid email profile"                               # ни Gmail, ни Drive
    assert q["response_type"] == "code" and q["code_challenge_method"] == "S256"
    assert q["redirect_uri"] == GOOGLE["redirect_uri"] and q["client_id"] == GOOGLE["client_id"]
    assert len(q["state"]) >= 32 and len(q["nonce"]) >= 24 and len(browser) >= 32
    raw = (tmp_path / "oidc.json").read_text()
    assert q["state"] not in raw and browser not in raw                       # на диске — только SHA-256
    assert (tmp_path / "oidc.json").stat().st_mode & 0o777 == 0o600
    st = json.loads(raw)["states"][hashlib.sha256(q["state"].encode()).hexdigest()]
    want = base64.urlsafe_b64encode(hashlib.sha256(st["verifier"].encode()).digest()).rstrip(b"=").decode()
    assert q["code_challenge"] == want and st["nonce"] == q["nonce"]
    y = query(svc.start("yandex")[0])
    assert y["scope"] == "login:email" and y["code_challenge_method"] == "S256" and "nonce" not in y


def test_start_rate_limit_by_ip(svc):
    for _ in range(oidc.START_LIMIT[0]):
        svc.start("google", "203.0.113.5")
    with pytest.raises(oidc.LimitError) as e:
        svc.start("yandex", "203.0.113.5")
    assert e.value.retry > 0
    svc.start("google", "203.0.113.6")                                        # другой IP — можно
    svc.clock.t += oidc.START_LIMIT[1] + 1
    svc.start("google", "203.0.113.5")


# ---------- возврат: Google ----------
def test_google_login_by_verified_email(svc):
    r = go(svc)[2]
    assert r == {"mode": "login", "uid": 2, "provider": "google"}
    url, data, _ = svc.fake.calls[0]
    assert url == oidc.PROVIDERS["google"]["token"]
    assert data["code_verifier"] and data["redirect_uri"] == GOOGLE["redirect_uri"] and data["code"] == "c-1"
    assert data["client_secret"] == "sec-g"


def test_same_answer_for_unknown_unverified_and_no_role(svc):
    with pytest.raises(ValueError) as a:
        go(svc, email="nobody@example.test")
    with pytest.raises(ValueError) as b:
        go(svc, email_verified=False)                                         # адрес есть в пульте, но не подтверждён
    with pytest.raises(ValueError) as c:
        go(svc, email_verified="false")
    svc.people_.remove(2)
    with pytest.raises(ValueError) as d:
        go(svc)
    assert str(a.value) == str(b.value) == str(c.value) == str(d.value) == oidc.SAME_ANSWER
    svc.people_.add(2, "member")
    svc.people_.set_email(2, address="ivan@example.test", at=1)
    assert go(svc, email="ivan@example.test", email_verified="true")[2]["uid"] == 2    # «true» строкой — тоже да


def test_state_is_one_time_and_bound_to_browser(svc):
    url, browser = svc.start("google")
    q = query(url)
    svc.fake.nonce = q["nonce"]
    with pytest.raises(ValueError, match="истекло"):
        svc.finish("google", {"code": "c", "state": q["state"]}, "чужой-браузер")
    with pytest.raises(ValueError, match="истекло"):                          # state сгорел и после неудачи
        svc.finish("google", {"code": "c", "state": q["state"]}, browser)
    url, browser = svc.start("google")
    q = query(url)
    svc.fake.nonce = q["nonce"]
    assert svc.finish("google", {"code": "c", "state": q["state"]}, browser)["uid"] == 2
    with pytest.raises(ValueError, match="истекло"):                          # повтор того же возврата
        svc.finish("google", {"code": "c", "state": q["state"]}, browser)
    url, browser = svc.start("google")
    with pytest.raises(ValueError, match="истекло"):                          # state Google — не для Яндекса
        svc.finish("yandex", {"code": "c", "state": query(url)["state"]}, browser)


def test_state_expires_and_redirect_uri_checked(svc):
    url, browser = svc.start("google")
    svc.clock.t += oidc.STATE_TTL + 1
    with pytest.raises(ValueError, match="истекло"):
        svc.finish("google", {"code": "c", "state": query(url)["state"]}, browser)
    url, browser = svc.start("google")
    svc.sections["google"]["redirect_uri"] = "https://other.example.test/api/login/oidc/google/back"
    with pytest.raises(ValueError, match="истекло"):
        svc.finish("google", {"code": "c", "state": query(url)["state"]}, browser)


def test_cancel_and_bad_token(svc):
    url, browser = svc.start("google")
    with pytest.raises(ValueError, match="отменён"):
        svc.finish("google", {"error": "access_denied", "state": query(url)["state"]}, browser)
    url, browser = svc.start("google")                                        # nonce не тот — подмена токена
    svc.fake.nonce = "чужой"
    with pytest.raises(ValueError, match="Не удалось проверить вход у Google"):
        svc.finish("google", {"code": "c", "state": query(url)["state"]}, browser)


def test_jwks_cached_and_refreshed(svc):
    go(svc)
    go(svc)
    jw = [c for c in svc.fake.calls if c[0] == oidc.PROVIDERS["google"]["jwks"]]
    assert len(jw) == 1                                                       # ключи — из памяти
    svc.clock.t += oidc.JWKS_TTL + 1
    go(svc)
    assert len([c for c in svc.fake.calls if c[0] == oidc.PROVIDERS["google"]["jwks"]]) == 2


# ---------- привязка из «Настроек» ----------
def test_link_then_login_without_email(svc, tmp_path):
    t = svc.ticket(3, "google", "198.51.100.1")
    _, _, r = go(svc, link=t, sub="g-300", email="petr@gmail.example", email_verified=False)
    assert r == {"mode": "link", "uid": 3, "provider": "google"}
    with pytest.raises(ValueError, match="устарела"):                          # билет одноразовый
        svc.start("google", link=t)
    assert go(svc, sub="g-300", email="", email_verified=False)[2]["uid"] == 3   # вход по привязке
    info = svc.info(3)["google"]
    assert info["linked"] and info["email"] == "p***@gmail.example" and not svc.info(3)["yandex"]["linked"]
    assert "petr@gmail.example" not in (tmp_path / "oidc.json").read_text()  # адрес — только маской
    svc.unlink(3, "google")
    with pytest.raises(ValueError, match="не привязан"):
        go(svc, sub="g-300", email="", email_verified=False)


def test_link_taken_by_other_and_ticket_rules(svc):
    go(svc, link=svc.ticket(3, "google"), sub="g-1")
    with pytest.raises(ValueError, match="другому человеку"):
        go(svc, link=svc.ticket(2, "google"), sub="g-1")
    t = svc.ticket(2, "google")
    with pytest.raises(ValueError, match="устарела"):                          # билет Google — не для Яндекса
        svc.start("yandex", link=t)
    t = svc.ticket(2, "google")
    svc.clock.t += oidc.TICKET_TTL + 1
    with pytest.raises(ValueError, match="устарела"):
        svc.start("google", link=t)
    with pytest.raises(ValueError, match="Доступа"):
        svc.ticket(99, "google")
    go(svc, link=svc.ticket(3, "google"), sub="g-2")                           # новая привязка заменяет старую
    assert sum(1 for v in svc._load()["links"].values() if v["uid"] == 3) == 1


def test_linked_person_without_role_cannot_login(svc):
    go(svc, link=svc.ticket(3, "google"), sub="g-3")
    svc.people_.remove(3)
    with pytest.raises(ValueError) as e:
        go(svc, sub="g-3", email="")
    assert str(e.value) == oidc.SAME_ANSWER


# ---------- Яндекс ID ----------
def test_yandex_login_by_yandex_address_and_info_call(svc):
    svc.people_.set_email(3, address="petr@yandex.ru", at=1)
    svc.fake.yandex["default_email"] = "Petr@Yandex.ru"
    assert go(svc, "yandex")[2]["uid"] == 3
    data = next(c[1] for c in svc.fake.calls if c[0] == oidc.PROVIDERS["yandex"]["token"])
    assert data["code_verifier"] and data["client_id"] == YANDEX["client_id"]


def test_yandex_external_address_needs_link(svc):
    svc.fake.yandex["default_email"] = "ivan@example.test"                    # адрес в пульте есть, но не на Яндексе
    with pytest.raises(ValueError) as e:
        go(svc, "yandex")
    assert str(e.value) == oidc.SAME_ANSWER
    go(svc, "yandex", link=svc.ticket(2, "yandex"))
    assert go(svc, "yandex")[2]["uid"] == 2


def test_yandex_token_of_other_app_refused(svc):
    svc.fake.yandex["client_id"] = "чужое-приложение"
    with pytest.raises(ValueError, match="Не удалось проверить вход у Яндекс ID"):
        go(svc, "yandex", link=svc.ticket(2, "yandex"))


# ---------- панель: переходы браузера и права ----------
@pytest.fixture
def server(tmp_path, keys):
    panel = webapp.Panel(Config(token="1:T", owners=[1], google=dict(GOOGLE), yandex=dict(YANDEX)))
    panel.people.add(2, "member")
    panel.people.add(3, "viewer")
    for uid in (1, 2, 3):
        panel.people.accept(uid)
        panel.people.set_country(uid, chosen="NL")
    panel.people.set_email(2, address="ivan@example.test", at=1)
    panel.oidc.clock = Clock()
    panel.oidc.clock.t = time.time()
    panel.oidc.fetch = Fake(keys[0], panel.oidc.clock)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield panel, srv.server_address[1]
    srv.shutdown()


def req(port, path, method="GET", body=None, cookie=""):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, json.dumps(body) if body is not None else None,
              {"Cookie": cookie, "Content-Type": "application/json"})
    r = c.getresponse()
    data = r.read()
    out = (r.status, dict(r.getheaders()), r.headers.get_all("Set-Cookie") or [], data)
    c.close()
    return out


def jar(set_cookies: list[str]) -> dict:
    return dict(x.split(";")[0].split("=", 1) for x in set_cookies)


def browser_login(panel, port, p="google", path=None):
    st, h, ck, _ = req(port, path or f"/api/login/oidc/{p}/start")
    assert st == 302
    q = query(h["Location"])
    panel.oidc.fetch.nonce = q.get("nonce", "")
    flow = jar(ck)[oidc.COOKIE]
    assert any("SameSite=Lax" in c and "HttpOnly" in c and "Secure" in c for c in ck)
    return req(port, f"/api/login/oidc/{p}/back?code=c-1&state={q['state']}", cookie=f"{oidc.COOKIE}={flow}")


def test_http_login_flow(server):
    panel, port = server
    st, h, _, body = req(port, "/api/login/methods")
    assert json.loads(body)["google"] is True and json.loads(body)["yandex"] is True
    st, h, ck, _ = browser_login(panel, port)
    assert st == 303 and h["Location"] == "/"
    j = jar(ck)
    assert panel.auth.uid(j[webauth.COOKIE]) == 2 and j[oidc.COOKIE] == ""    # сессия выдана, cookie входа стёрта
    st, h, ck, body = req(port, "/api/login/oidc/google/back?code=x&state=nope", cookie=f"{oidc.COOKIE}=x")
    assert st == 400 and "истекло" in body.decode() and webauth.COOKIE not in jar(ck)
    st, *_ = req(port, "/api/login/oidc/github/start")                    # чужого провайдера нет: обычное «нужен вход»
    assert st == 401


def test_http_second_factor_goes_to_fragment(server):
    panel, port = server
    panel.email.section = {"provider": "yandex", "user": "p@example.test", "password": "x"}
    panel.email.background, panel.email.sender = False, lambda smtp, msg: None
    panel.people.set_email(2, second_factor=True)
    st, h, ck, _ = browser_login(panel, port)
    assert st == 303 and h["Location"].startswith("/#2fa=") and webauth.COOKIE not in jar(ck)


def test_http_link_from_settings(server):
    panel, port = server
    viewer = f"{webauth.COOKIE}={panel.auth.issue(3)}"
    assert req(port, "/api/oidc")[0] == 401                                  # без входа — нельзя
    st, _, _, body = req(port, "/api/oidc", cookie=viewer)                   # наблюдатель — свои привязки можно
    assert st == 200 and json.loads(body)["google"] == {"enabled": True, "title": "Google", "linked": False,
                                                        "email": "", "at": None}
    st, _, _, body = req(port, "/api/oidc/link", "POST", {"provider": "google"}, viewer)
    url = json.loads(body)["url"]
    assert st == 200 and url.startswith("/api/login/oidc/google/start?link=")
    panel.oidc.fetch.who = {"sub": "g-77", "email": "", "email_verified": False}
    st, _, _, body = browser_login(panel, port, path=url)
    assert st == 200 and "Google привязан" in body.decode()
    assert json.loads(req(port, "/api/oidc", cookie=viewer)[3])["google"]["linked"] is True
    st, _, ck, _ = browser_login(panel, port)
    assert st == 303 and panel.auth.uid(jar(ck)[webauth.COOKIE]) == 3
    st, _, _, body = req(port, "/api/oidc/unlink", "POST", {"provider": "google"}, viewer)
    assert st == 200 and json.loads(body)["google"]["linked"] is False
    st, _, _, body = req(port, "/api/oidc/link", "POST", {"provider": "github"}, viewer)
    assert st == 404


def test_http_off_without_settings(server):
    panel, port = server
    panel.oidc.sections = {"google": {}, "yandex": {}}
    assert json.loads(req(port, "/api/login/methods")[3]) | {} == {
        "telegram": True, "owner_code": True, "email": False, "passkey": panel.keys.enabled,
        "google": False, "yandex": False}
    st, _, ck, body = req(port, "/api/login/oidc/google/start")
    assert st == 503 and "выключен" in body.decode() and not ck
    assert req(port, "/api/login/oidc/yandex/back?code=x&state=y")[0] == 503
    st, _, _, body = req(port, "/api/oidc/link", "POST", {"provider": "google"},
                         f"{webauth.COOKIE}={panel.auth.issue(2)}")
    assert st == 400 and "не настроен" in json.loads(body)["error"]
