"""Вход по коду на почту (emailcode.py): то, что легко сломать.

Код не лежит на диске в открытом виде и одноразовый, 5 попыток, срок 10 минут, лимиты 1 в минуту и 5 в час,
одинаковый ответ для своего и чужого адреса, выключено без настроек, письмо собрано правильно, второй фактор,
права эндпоинтов. SMTP подменён — настоящих писем тесты не отправляют.
"""

import json
import re
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import config, emailcode, providers, webapp, webauth
from gas_pult.config import Config
from gas_pult.people import People

SMTP = {"provider": "yandex", "user": "pult@example.test", "password": "app-password-1"}
KEY = b"k" * 32


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture
def svc(tmp_path):
    people = People(tmp_path / "people.json", [1])
    people.add(2, "member", "Иван")
    clock = Clock()
    s = emailcode.Service(SMTP, people, tmp_path / "codes.json", key=KEY, clock=clock, background=False)
    s.outbox = []
    s.sender = lambda smtp, msg: s.outbox.append(msg)
    s.clock = clock
    return s


def code_of(msg) -> str:
    return re.search(r"\b(\d{6})\b", msg.get_content()).group(1)


def bind(s, uid=2, addr="ivan@example.test"):
    s.bind_start(uid, addr)
    s.clock.t += 61                                   # следующий код на этот адрес — не раньше чем через минуту
    return s.bind_confirm(uid, addr, code_of(s.outbox[-1]))


# ---------- код ----------
def test_code_format_and_only_hmac_on_disk(svc, tmp_path):
    bind(svc)
    svc.login_start("Ivan@Example.test")
    msg = svc.outbox[-1]
    code = code_of(msg)
    assert re.fullmatch(r"\d{6}", code) and code in msg["Subject"]
    raw = (tmp_path / "codes.json").read_text()
    assert code not in raw and "ivan@example.test" not in raw          # ни кода, ни адреса — только HMAC
    assert (tmp_path / "codes.json").stat().st_mode & 0o777 == 0o600
    assert svc.login_verify("ivan@example.test", f"{code[:3]} {code[3:]}") == 2      # пробел внутри — не беда
    with pytest.raises(ValueError, match="устарел"):                  # одноразовый
        svc.login_verify("ivan@example.test", code)


def test_codes_are_random(tmp_path):
    c = emailcode.Codes(tmp_path / "c.json", KEY, Clock())
    codes = set()
    for i in range(30):
        codes.add(c.issue(f"s{i}", f"a{i}@example.test"))
    assert len(codes) > 20 and all(re.fullmatch(r"\d{6}", x) for x in codes)


def test_code_expires_after_ten_minutes(svc):
    bind(svc)
    svc.login_start("ivan@example.test")
    code = code_of(svc.outbox[-1])
    svc.clock.t += emailcode.CODE_TTL + 1
    with pytest.raises(ValueError, match="устарел"):
        svc.login_verify("ivan@example.test", code)


def test_five_wrong_attempts_burn_the_code(svc):
    bind(svc)
    svc.login_start("ivan@example.test")
    code = code_of(svc.outbox[-1])
    wrong = "000000" if code != "000000" else "111111"
    for left in (4, 3, 2, 1):
        with pytest.raises(ValueError, match=f"Осталось попыток: {left}"):
            svc.login_verify("ivan@example.test", wrong)
    with pytest.raises(ValueError, match="попытки кончились"):
        svc.login_verify("ivan@example.test", wrong)
    with pytest.raises(ValueError, match="устарел"):
        svc.login_verify("ivan@example.test", code)               # верный код после пяти промахов уже не работает


def test_resend_limits_minute_and_hour(svc):
    bind(svc)
    svc.login_start("ivan@example.test")
    with pytest.raises(emailcode.LimitError, match="через минуту") as e:
        svc.login_start("ivan@example.test")
    assert 0 < e.value.retry <= 60
    for _ in range(3):                                # привязка (1) + вход (1) + ещё 3 = 5 за час
        svc.clock.t += 61
        svc.login_start("ivan@example.test")
    svc.clock.t += 61
    with pytest.raises(emailcode.LimitError, match="через час"):
        svc.login_start("ivan@example.test")
    svc.clock.t += 3600
    svc.login_start("ivan@example.test")


def test_ip_limit(svc):
    for i in range(emailcode.IP_PER_HOUR):
        svc.login_start(f"x{i}@example.test", "203.0.113.5")
    with pytest.raises(emailcode.LimitError):
        svc.login_start("y@example.test", "203.0.113.5")
    svc.login_start("y@example.test", "203.0.113.6")          # другой адрес клиента — свой счёт


def test_same_answer_for_known_and_unknown(svc):
    bind(svc)
    n = len(svc.outbox)
    known = svc.login_start("ivan@example.test")
    unknown = svc.login_start("stranger@example.test")
    assert known == unknown and "Если адрес привязан" in known["message"]
    assert len(svc.outbox) == n + 1 and svc.outbox[-1]["To"] == "ivan@example.test"   # чужому письмо не ушло
    errs = []
    for addr in ("ivan@example.test", "stranger@example.test"):        # и проверка кода отвечает одинаково
        with pytest.raises(ValueError) as e:
            svc.login_verify(addr, "000000" if code_of(svc.outbox[-1]) != "000000" else "111111")
        errs.append(str(e.value))
    assert errs[0] == errs[1]
    svc.clock.t += 61                                                  # и лимиты у чужого адреса те же
    svc.login_start("stranger@example.test")
    with pytest.raises(emailcode.LimitError):
        svc.login_start("stranger@example.test")


def test_bad_address(svc):
    for bad in ("", "no-at", "a@b", "a b@example.test", "a@@example.test"):
        with pytest.raises(ValueError):
            svc.login_start(bad)


def test_address_of_person_without_role_does_not_log_in(svc):
    bind(svc)
    svc.people.remove(2)
    n = len(svc.outbox)
    svc.clock.t += 61
    svc.login_start("ivan@example.test")
    assert len(svc.outbox) == n                                       # роли нет — письма нет


def test_smtp_failure_allows_retry(svc):
    bind(svc)

    def boom(smtp, msg):
        raise OSError("smtp down")

    svc.sender = boom
    svc.clock.t += 61
    svc.login_start("ivan@example.test")                              # ответ тот же — письмо в фоне
    svc.sender = lambda smtp, msg: svc.outbox.append(msg)
    svc.login_start("ivan@example.test")                              # неудачная отправка не держит минуту
    assert svc.login_verify("ivan@example.test", code_of(svc.outbox[-1])) == 2


def test_disabled_without_settings(tmp_path):
    people = People(tmp_path / "p.json", [1])
    for section in ({}, {"provider": "gmail", "user": "a@example.test"}, {"host": "smtp.example.test"}):
        s = emailcode.Service(section, people, tmp_path / "c.json", key=KEY)
        assert not s.enabled
        with pytest.raises(RuntimeError, match="не настроена"):
            s.login_start("a@example.test")
    providers.save_key(emailcode.PASSWORD_KEY, "from-secrets")       # пароль из secrets.json — тоже годится
    s = emailcode.Service({"provider": "gmail", "user": "a@example.test"}, people, tmp_path / "c.json", key=KEY)
    assert s.enabled and s.smtp().host == "smtp.gmail.com" and s.smtp().port == 465


def test_message_headers(svc):
    smtp = svc.smtp()
    msg = emailcode.message(smtp, "ivan@example.test", *emailcode.code_text("123456", "для входа в пульт"))
    assert msg["From"] == "gas-pult <pult@example.test>" and msg["To"] == "ivan@example.test"
    assert msg["Date"] and msg["Message-ID"].endswith("@example.test>") and "123456" in msg["Subject"]
    body = msg.get_content()
    assert "http" not in body and "123456" in body                    # без ссылок для входа — только код


def test_smtp_ssl_with_verified_context(monkeypatch, svc):
    seen = {}

    class Fake:
        def __init__(self, host, port, context=None, timeout=None):
            seen.update(host=host, port=port, ctx=context, timeout=timeout)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, u, p):
            seen["login"] = (u, p)

        def send_message(self, msg):
            seen["msg"] = msg

    monkeypatch.setattr(emailcode.smtplib, "SMTP_SSL", Fake)
    smtp = svc.smtp()
    emailcode.send(smtp, emailcode.message(smtp, "a@example.test", "s", "t"))
    assert seen["host"] == "smtp.yandex.ru" and seen["port"] == 465 and seen["timeout"] == emailcode.TIMEOUT
    assert seen["ctx"].verify_mode.name == "CERT_REQUIRED" and seen["ctx"].check_hostname
    assert seen["login"] == ("pult@example.test", "app-password-1")


# ---------- привязка, второй фактор, оповещения ----------
def test_bind_requires_code_and_stores_in_people(svc, tmp_path):
    svc.bind_start(2, "ivan@example.test")
    with pytest.raises(ValueError):
        svc.bind_confirm(2, "ivan@example.test", "000000" if code_of(svc.outbox[-1]) != "000000" else "111111")
    assert svc.people.by_email("ivan@example.test") is None
    svc.bind_confirm(2, "ivan@example.test", code_of(svc.outbox[-1]))
    assert json.loads((tmp_path / "people.json").read_text())["2"]["email"]["address"] == "ivan@example.test"
    svc.people.add(2, "viewer")                                       # смена роли почту не сбрасывает
    assert svc.people.by_email("ivan@example.test") == 2
    with pytest.raises(ValueError, match="другому"):                  # чужой адрес не привязать
        svc.bind_start(1, "ivan@example.test")
    bind(svc, 1, "owner@example.test")                                # владелец — в emails.json рядом
    assert svc.people.by_email("owner@example.test") == 1 and (tmp_path / "emails.json").exists()
    svc.unbind(2)
    assert svc.people.by_email("ivan@example.test") is None


def test_second_factor(svc):
    bind(svc)
    assert not svc.wants_second(2)                                    # по умолчанию выключено
    svc.options(2, second_factor=True)
    assert svc.wants_second(2)
    r = svc.second_start(2)
    assert r["state"] == "2fa" and r["to"] == "i***@example.test"
    with pytest.raises(ValueError):
        svc.second_verify("чужой", code_of(svc.outbox[-1]))
    assert svc.second_verify(r["id"], code_of(svc.outbox[-1])) == 2
    with pytest.raises(ValueError):
        svc.second_verify(r["id"], code_of(svc.outbox[-1]))           # одноразовый


def test_notify_only_when_enabled(svc):
    assert not emailcode.notify_email(svc, 2, "Тема", "Текст")       # адреса нет
    bind(svc)
    n = len(svc.outbox)
    assert not emailcode.notify_email(svc, 2, "Тема", "Текст")       # оповещения не включены
    svc.options(2, notify=True)
    assert emailcode.notify_email(svc, 2, "Тема", "Текст") and len(svc.outbox) == n + 1
    assert svc.outbox[-1]["Subject"] == "Тема"


# ---------- конфиг ----------
def test_config_email_section(monkeypatch, tmp_path):
    d = tmp_path / "cfg"
    d.mkdir(exist_ok=True)
    (d / "token").write_text("1:T")
    (d / "config.toml").write_text('owners = [1]\n\n[email]\nprovider = "yandex"\nuser = "a@example.test"\n')
    assert config.load().email == {"provider": "yandex", "user": "a@example.test"}
    config.save([1], voice="irina")                                   # пересохранение не ломает секцию
    assert config.load().email["provider"] == "yandex" and config.load().voice == "irina"
    (d / "config.toml").write_text('owners = [1]\n[email]\nhots = "x"\n')
    with pytest.raises(config.ConfigError, match="Неизвестные ключи в \\[email\\]"):
        config.load()
    (d / "config.toml").write_text('owners = [1]\nemail = "x"\n')
    with pytest.raises(config.ConfigError, match="секция"):
        config.load()


def test_internal_secrets_hidden_from_keys():
    providers.save_key("smtp", "secret-pass")
    emailcode.hmac_key()
    assert providers.key_info() == {}


# ---------- панель: эндпоинты и права ----------
@pytest.fixture
def server(tmp_path):
    panel = webapp.Panel(Config(token="1:T", owners=[1], email=dict(SMTP)))
    panel.people.add(2, "member")
    panel.people.add(3, "viewer")
    for uid in (1, 2, 3):
        panel.people.accept(uid)
        panel.people.set_country(uid, chosen="NL")
    outbox = []
    panel.email.background = False
    panel.email.sender = lambda smtp, msg: outbox.append(msg)
    panel.email.codes.clock = panel.clock = Clock()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield panel, f"http://127.0.0.1:{srv.server_address[1]}", outbox
    srv.shutdown()


def call(base, path, body=None, token=""):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={token}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r), r.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as e:
        return e.code, json.load(e), ""


def cookie(set_cookie: str) -> str:
    return set_cookie.split(";")[0].split("=", 1)[1]


def test_endpoints_flow_and_rights(server):
    panel, base, outbox = server
    assert call(base, "/api/login/methods")[1]["email"] is True
    assert call(base, "/api/email")[0] == 401                         # без входа — нельзя
    viewer = panel.auth.issue(3)
    st, d, _ = call(base, "/api/email", token=viewer)                 # наблюдатель — свою почту можно
    assert st == 200 and d["enabled"] and d["address"] == ""
    assert call(base, "/api/email/bind", {"email": "v@example.test"}, viewer)[0] == 200
    st, d, _ = call(base, "/api/email/confirm", {"email": "v@example.test", "code": code_of(outbox[-1])}, viewer)
    assert st == 200 and d["address"] == "v@example.test"
    panel.clock.t += 61
    # вход по почте
    st, d, _ = call(base, "/api/login/email/start", {"email": "v@example.test"})
    st2, d2, _ = call(base, "/api/login/email/start", {"email": "nobody@example.test"})
    assert st == st2 == 200 and d == d2
    assert call(base, "/api/login/email/start", {"email": "v@example.test"})[0] == 429
    st, d, ck = call(base, "/api/login/email/verify", {"email": "v@example.test", "code": code_of(outbox[-1])})
    assert st == 200 and d["state"] == "ok" and panel.auth.uid(cookie(ck)) == 3
    # второй фактор после входа через Telegram
    call(base, "/api/email/options", {"second_factor": True}, viewer)
    rid, nonce = panel.logins.start()
    panel.logins.decide(nonce, 3, True)
    st, d, ck = call(base, f"/api/login/tg?id={rid}")
    assert st == 200 and d["state"] == "2fa" and not ck               # сессии ещё нет
    assert call(base, "/api/login/2fa", {"id": d["id"], "code": "000000" if code_of(outbox[-1]) != "000000"
                                         else "111111"})[0] == 400
    st, d2, ck = call(base, "/api/login/2fa", {"id": d["id"], "code": code_of(outbox[-1])})
    assert st == 200 and panel.auth.uid(cookie(ck)) == 3


def test_endpoints_off_without_smtp(server):
    panel, base, _ = server
    panel.email.section = {}
    assert call(base, "/api/login/methods")[1]["email"] is False
    st, d, _ = call(base, "/api/login/email/start", {"email": "a@example.test"})
    assert st == 503 and d["code"] == "off"
    st, d, _ = call(base, "/api/email/bind", {"email": "a@example.test"}, panel.auth.issue(2))
    assert st == 400 and "не настроена" in d["error"]
