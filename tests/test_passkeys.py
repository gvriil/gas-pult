"""Вход по ключу доступа (passkeys.py): церемонии по-настоящему, с программным аутентификатором.

Ответы устройства собираются в тесте (ключ P-256 из cryptography, CBOR из cbor2 — оба приходят с пакетом webauthn),
подписи проверяет сама библиотека — ничего не подменено. Тесты с пакетом пропускаются без него (``importorskip``);
для них в CI — отдельная задача с ``.[passkeys]``. Тесты «без пакета» и «без rp_id» идут всегда.
"""

import base64
import hashlib
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import passkeys, webapp, webauth
from gas_pult.config import Config
from gas_pult.people import People

RP = "pult.example.test"
ORIGIN = "https://pult.example.test"
SECTION = {"rp_id": RP, "origin": ORIGIN}


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class Clock:
    def __init__(self):
        self.t = 2_000_000.0

    def __call__(self):
        return self.t


class Authenticator:
    """Устройство с одним ключом: create — ответ на регистрацию (fmt none), get — подпись входа."""

    def __init__(self):
        from cryptography.hazmat.primitives.asymmetric import ec

        self.ec = ec
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(16)
        self.count = 0
        self.handle = None

    def cose(self) -> bytes:
        import cbor2

        n = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})

    def create(self, options: dict, origin: str = ORIGIN, rp: str = RP, uv: bool = True) -> dict:
        import cbor2

        self.handle = options["user"]["id"]
        cdj = json.dumps({"type": "webauthn.create", "challenge": options["challenge"], "origin": origin,
                          "crossOrigin": False}).encode()
        flags = 0x01 | 0x40 | (0x04 if uv else 0)
        auth = (hashlib.sha256(rp.encode()).digest() + bytes([flags]) + self.count.to_bytes(4, "big") + b"\0" * 16
                + len(self.cred_id).to_bytes(2, "big") + self.cred_id + self.cose())
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
        return {"id": b64(self.cred_id), "rawId": b64(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64(cdj), "attestationObject": b64(att), "transports": ["internal"]},
                "clientExtensionResults": {}}

    def get(self, options: dict, origin: str = ORIGIN, rp: str = RP, step: int = 1, handle=None) -> dict:
        from cryptography.hazmat.primitives import hashes

        self.count += step
        cdj = json.dumps({"type": "webauthn.get", "challenge": options["challenge"], "origin": origin,
                          "crossOrigin": False}).encode()
        auth = hashlib.sha256(rp.encode()).digest() + bytes([0x05]) + self.count.to_bytes(4, "big")
        sig = self.key.sign(auth + hashlib.sha256(cdj).digest(), self.ec.ECDSA(hashes.SHA256()))
        return {"id": b64(self.cred_id), "rawId": b64(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64(cdj), "authenticatorData": b64(auth), "signature": b64(sig),
                             "userHandle": handle if handle is not None else self.handle},
                "clientExtensionResults": {}}


@pytest.fixture
def wa():
    return pytest.importorskip("webauthn")


@pytest.fixture
def pk(tmp_path, wa):
    people = People(tmp_path / "people.json", [1])
    people.add(2, "member", "Иван")
    k = passkeys.Passkeys(SECTION, people, tmp_path / "passkeys.json", clock=Clock())
    return k


def register(pk, uid=2, dev=None, name="iPhone"):
    dev = dev or Authenticator()
    r = pk.register_options(uid, "Пульт · Иван", "198.51.100.1")
    pk.register_verify(uid, r["id"], dev.create(r["options"]), name)
    return dev


def login(pk, dev, **kw):
    r = pk.login_options("198.51.100.1")
    return pk.login_verify(r["id"], dev.get(r["options"], **kw))


# ---------- регистрация ----------
def test_registration_options(pk):
    o = pk.register_options(2, "Пульт · Иван")["options"]
    assert o["rp"]["id"] == RP
    assert o["authenticatorSelection"]["residentKey"] == "required"
    assert o["authenticatorSelection"]["userVerification"] == "required"
    assert o["attestation"] == "none"
    handle = base64.urlsafe_b64decode(o["user"]["id"] + "==")
    assert len(handle) >= 32 and handle != b"2" and "2" not in o["user"]["name"]   # случайный, не uid


def test_register_and_login_for_real(pk, tmp_path):
    dev = register(pk)
    raw = json.loads((tmp_path / "passkeys.json").read_text())
    assert (tmp_path / "passkeys.json").stat().st_mode & 0o777 == 0o600
    c = raw["creds"][b64(dev.cred_id)]
    assert c["uid"] == 2 and c["name"] == "iPhone" and c["transports"] == ["internal"]
    assert c["user_handle"] == dev.handle
    assert raw["challenges"] == {}                                     # вызов снят после регистрации
    assert login(pk, dev) == 2
    assert json.loads((tmp_path / "passkeys.json").read_text())["creds"][b64(dev.cred_id)]["sign_count"] == 1
    o = pk.login_options()["options"]
    assert o["userVerification"] == "required" and o["rpId"] == RP


def test_challenge_single_use_and_ttl(pk):
    dev = Authenticator()
    r = pk.register_options(2)
    cred = dev.create(r["options"])
    pk.register_verify(2, r["id"], cred)
    with pytest.raises(ValueError, match="истекло"):                  # повтор того же ответа
        pk.register_verify(2, r["id"], cred)
    r = pk.login_options()
    a = dev.get(r["options"])
    assert pk.login_verify(r["id"], a) == 2
    with pytest.raises(ValueError, match="истекло"):
        pk.login_verify(r["id"], a)
    r = pk.login_options()
    pk.clock.t += passkeys.CHALLENGE_TTL + 1
    with pytest.raises(ValueError, match="истекло"):
        pk.login_verify(r["id"], dev.get(r["options"]))
    r = pk.register_options(2)                                         # вызов регистрации не годится для входа
    with pytest.raises(ValueError, match="истекло"):
        pk.login_verify(r["id"], dev.get(r["options"]))


def test_wrong_origin_and_rp_id(pk):
    for kw in ({"origin": "https://evil.example.test"}, {"rp": "evil.example.test"}):
        dev = Authenticator()
        r = pk.register_options(2)
        with pytest.raises(ValueError, match="Не удалось сохранить"):
            pk.register_verify(2, r["id"], dev.create(r["options"], **kw))
    dev = register(pk)
    for kw in ({"origin": "https://evil.example.test"}, {"rp": "evil.example.test"}):
        with pytest.raises(ValueError, match="Не удалось войти"):
            login(pk, dev, **kw)


def test_user_verification_required(pk):
    dev = Authenticator()
    r = pk.register_options(2)
    with pytest.raises(ValueError):
        pk.register_verify(2, r["id"], dev.create(r["options"], uv=False))


def test_sign_count_rollback_rejected(pk):
    dev = register(pk)
    login(pk, dev, step=5)
    dev.count = 1                                                      # клон ключа со старым счётчиком
    with pytest.raises(ValueError, match="Не удалось войти"):
        login(pk, dev, step=1)


def test_user_handle_mismatch_and_unknown_key(pk):
    dev = register(pk)
    with pytest.raises(ValueError, match="Не удалось войти"):
        login(pk, dev, handle=b64(b"x" * 32))
    with pytest.raises(ValueError, match="неизвестен"):
        login(pk, Authenticator())


def test_several_keys_names_and_removal(pk):
    a = register(pk, name="iPhone")
    b = register(pk, name="MacBook")
    keys = pk.list(2)
    assert [k["name"] for k in keys] == ["iPhone", "MacBook"]
    creds = json.loads(pk.store.read_text())["creds"]
    assert len({creds[k["id"]]["user_handle"] for k in keys}) == 1    # один user_handle на человека
    with pytest.raises(LookupError):                                   # чужой ключ не удалить
        pk.remove(1, keys[0]["id"])
    assert [k["name"] for k in pk.remove(2, keys[0]["id"])] == ["MacBook"]
    with pytest.raises(ValueError, match="неизвестен"):
        login(pk, a)
    assert login(pk, b) == 2
    r = pk.register_options(2)                                         # уже сохранённый ключ — в exclude
    assert {c["id"] for c in r["options"]["excludeCredentials"]} == {b64(b.cred_id)}


def test_person_without_role_cannot_log_in(pk):
    dev = register(pk)
    pk.people.remove(2)
    with pytest.raises(ValueError, match="Доступа"):
        login(pk, dev)


def test_rate_limit(pk):
    for _ in range(passkeys.START_LIMIT[0]):
        pk.login_options("203.0.113.9")
    with pytest.raises(passkeys.LimitError):
        pk.login_options("203.0.113.9")
    with pytest.raises(passkeys.LimitError):
        pk.register_options(2, ip="203.0.113.9")
    pk.login_options("203.0.113.10")
    pk.clock.t += passkeys.START_LIMIT[1] + 1
    pk.login_options("203.0.113.9")


# ---------- выключено: без rp_id и без пакета (идут и без webauthn) ----------
def test_disabled_without_rp_id(tmp_path):
    people = People(tmp_path / "p.json", [1])
    for section in ({}, {"rp_id": RP}, {"origin": ORIGIN}):
        k = passkeys.Passkeys(section, people, tmp_path / "k.json")
        assert not k.enabled
        with pytest.raises(RuntimeError, match="не настроен"):
            k.login_options()


def test_disabled_without_package(tmp_path, monkeypatch):
    monkeypatch.setattr(passkeys.importlib.util, "find_spec", lambda name: None)
    k = passkeys.Passkeys(SECTION, People(tmp_path / "p.json", [1]), tmp_path / "k.json")
    assert not k.enabled
    with pytest.raises(RuntimeError, match="нет пакета"):
        k.register_options(1)


# ---------- панель: эндпоинты и права ----------
def serve(tmp_path, monkeypatch, section):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    panel = webapp.Panel(Config(token="1:T", owners=[1], passkeys=section))
    panel.people.add(2, "member")
    panel.people.add(3, "viewer")
    for uid in (1, 2, 3):
        panel.people.accept(uid)
        panel.people.set_country(uid, chosen="NL")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return panel, srv, f"http://127.0.0.1:{srv.server_address[1]}"


def call(base, path, body=None, token=""):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={token}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r), r.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as e:
        return e.code, json.load(e), ""


def test_endpoints_off_without_settings(tmp_path, monkeypatch):
    panel, srv, base = serve(tmp_path, monkeypatch, {})
    try:
        assert call(base, "/api/login/methods")[1]["passkey"] is False
        st, d, _ = call(base, "/api/login/passkey/options", {})
        assert st == 503 and d["code"] == "off"
        st, d, _ = call(base, "/api/passkeys", token=panel.auth.issue(2))
        assert st == 200 and d == {"enabled": False, "keys": []}
        st, d, _ = call(base, "/api/passkeys/options", {}, panel.auth.issue(2))
        assert st == 400 and "не настроен" in d["error"]
    finally:
        srv.shutdown()


def test_endpoints_flow_and_rights(tmp_path, monkeypatch, wa):
    panel, srv, base = serve(tmp_path, monkeypatch, SECTION)
    try:
        assert call(base, "/api/login/methods")[1]["passkey"] is True
        assert call(base, "/api/passkeys")[0] == 401                   # без входа — нельзя
        assert call(base, "/api/passkeys/options", {})[0] == 401
        viewer, dev = panel.auth.issue(3), Authenticator()
        st, r, _ = call(base, "/api/passkeys/options", {}, viewer)     # наблюдатель — свой ключ можно
        assert st == 200 and "3" not in r["options"]["user"]["name"] + r["options"]["user"]["displayName"]
        st, d, _ = call(base, "/api/passkeys/add", {"id": r["id"], "credential": dev.create(r["options"]),
                                                    "name": "Телефон"}, viewer)
        assert st == 200 and [k["name"] for k in d["keys"]] == ["Телефон"]
        st, r, _ = call(base, "/api/login/passkey/options", {})
        st, d, ck = call(base, "/api/login/passkey/verify", {"id": r["id"], "credential": dev.get(r["options"])})
        assert st == 200 and d["state"] == "ok" and panel.auth.uid(ck.split(";")[0].split("=", 1)[1]) == 3
        other = panel.auth.issue(2)                                    # чужой ключ не видно и не удалить
        assert call(base, "/api/passkeys", token=other)[1]["keys"] == []
        assert call(base, "/api/passkeys/remove", {"id": b64(dev.cred_id)}, other)[0] == 404
        assert call(base, "/api/passkeys/remove", {"id": b64(dev.cred_id)}, viewer)[1]["keys"] == []
    finally:
        srv.shutdown()


def test_second_factor_after_passkey(tmp_path, monkeypatch, wa):
    panel, srv, base = serve(tmp_path, monkeypatch, SECTION)
    try:
        dev = register(panel.keys, uid=2)
        panel.email.section = {"provider": "yandex", "user": "p@example.test", "password": "x"}
        panel.email.background, sent = False, []
        panel.email.sender = lambda smtp, msg: sent.append(msg)
        panel.people.set_email(2, address="ivan@example.test", second_factor=True)
        st, r, _ = call(base, "/api/login/passkey/options", {})
        st, d, ck = call(base, "/api/login/passkey/verify", {"id": r["id"], "credential": dev.get(r["options"])})
        assert st == 200 and d["state"] == "2fa" and not ck and len(sent) == 1
    finally:
        srv.shutdown()
