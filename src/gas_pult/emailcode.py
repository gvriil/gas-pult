"""Вход по коду на почту, второй фактор и письма-оповещения — только стандартная библиотека.

**Правила** (как во входе по почте у других проектов GASTECH): код — 6 цифр (``secrets.randbelow``), живёт 10 минут,
5 попыток; на диске — только HMAC-SHA256 кода (ключ — ``email_hmac`` в ``secrets.json`` 0600, создаётся сам), адрес в
файле кодов тоже не хранится — только его HMAC. Новый код на адрес — не чаще раза в минуту и не больше 5 в час;
с одного IP — не больше 20 запросов в час.

**Не раскрываем, есть ли адрес.** Запрос кода для входа отвечает одинаково для привязанного и чужого адреса, письмо
уходит в фоне (ответ не ждёт SMTP — время ответа одинаковое). Для чужого адреса заводится «пустышка» с тем же
счётчиком попыток: проверка кода отвечает так же («не подошёл, осталось N»), но войти по ней нельзя.

**Где адрес.** Человек сам привязывает почту в «Настройках» (код на этот адрес) — адрес ложится в ``people.json``
(поле ``email``; у владельцев — рядом, ``emails.json``). Войти по почте можно только с адресом, привязанным
к человеку с ролью; убрали роль — вход по почте перестаёт работать вместе с остальными.

**SMTP** — ``[email]`` в ``config.toml`` (вне репозитория), пароль приложения — ``smtp`` в ``secrets.json`` 0600
(``gas-pult email password``). ``smtplib.SMTP_SSL`` (порт 465) с проверкой сертификата. Нет настроек — функция
выключена: кнопки нет, API отвечает «выключено». Подробно — docs/AUTH.md.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import smtplib
import ssl
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

from gas_pult import providers
from gas_pult.config import write_private

CODE_TTL = 600
MAX_TRIES = 5
RESEND_AFTER = 60
PER_HOUR = 5
IP_PER_HOUR = 20
TIMEOUT = 20
SAME_ANSWER = "Если адрес привязан к пульту, мы отправили на него код. Он действует 10 минут."
# Подсказка в docs/AUTH.md и config.example.toml: Яндекс — для РФ, Gmail или другой — для остальных.
PRESETS = {"yandex": ("smtp.yandex.ru", 465), "gmail": ("smtp.gmail.com", 465), "mailru": ("smtp.mail.ru", 465)}
HMAC_KEY = "email_hmac"                      # ключ HMAC в secrets.json — создаётся при первом коде
PASSWORD_KEY = "smtp"                        # пароль приложения SMTP в secrets.json
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class LimitError(ValueError):
    """Слишком часто: ответ 429, ``retry`` — через сколько секунд можно снова."""

    def __init__(self, text: str, retry: int):
        super().__init__(text)
        self.retry = retry


def _wait(sec: float) -> int:
    return max(1, math.ceil(sec))


def normalize(raw) -> str | None:
    """Адрес в нижнем регистре или None, если это не адрес."""
    addr = str(raw or "").strip().lower()
    if len(addr) > 254 or not EMAIL_RE.fullmatch(addr):
        return None
    return addr


def mask(addr: str) -> str:
    """i***@example.com — для журнала и подсказки «код отправлен на …»."""
    local, _, domain = (addr or "").partition("@")
    return f"{local[:1]}***@{domain}" if domain else ""


def log(event: str, **kw):
    """Журнал входов — строкой в journalctl службы панели. Ни кодов, ни адресов целиком."""
    tail = " ".join(f"{k}={v}" for k, v in kw.items() if v not in (None, ""))
    print(f"auth: {event} {tail}".rstrip(), file=sys.stderr, flush=True)


# ---------- SMTP ----------
@dataclass
class Smtp:
    host: str
    port: int
    user: str
    sender: str
    name: str
    password: str
    timeout: float = TIMEOUT


def smtp_settings(section: dict | None, keys: dict | None = None) -> Smtp | None:
    """Настройки из ``[email]`` и пароль из secrets.json. Чего-то не хватает — None (функция выключена)."""
    s = dict(section or {})
    host, port = PRESETS.get(str(s.get("provider", "")).lower(), ("", 465))
    host = str(s.get("host") or host)
    user = str(s.get("user") or "")
    password = str(s.get("password") or (providers.load_keys() if keys is None else keys).get(PASSWORD_KEY) or "")
    if not (host and user and password):
        return None
    try:
        port, timeout = int(s.get("port") or port), float(s.get("timeout") or TIMEOUT)
    except (TypeError, ValueError):
        return None
    return Smtp(host, port, user, str(s.get("from") or user), str(s.get("name") or "gas-pult"), password, timeout)


def message(smtp: Smtp, to: str, subject: str, text: str) -> EmailMessage:
    """Простое письмо по-русски: From, To, Subject, Date, Message-ID — как положено."""
    msg = EmailMessage()
    msg["From"] = formataddr((smtp.name, smtp.sender))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=smtp.sender.rpartition("@")[2] or None)
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(text)
    return msg


def send(smtp: Smtp, msg: EmailMessage):
    """SMTP_SSL (порт 465) с проверкой сертификата сервера и таймаутом."""
    with smtplib.SMTP_SSL(smtp.host, smtp.port, context=ssl.create_default_context(), timeout=smtp.timeout) as s:
        s.login(smtp.user, smtp.password)
        s.send_message(msg)


def code_text(code: str, why: str) -> tuple[str, str]:
    """Тема и текст письма с кодом. Без ссылок для входа и без слов о том, есть ли аккаунт."""
    return (f"{code} — код для пульта gas-pult",
            f"Код {why}: {code}\n\n"
            "Он действует 10 минут. Никому его не сообщайте.\n"
            "Если вы не запрашивали код, просто удалите письмо — без кода войти нельзя.\n")


# ---------- коды ----------
class Codes:
    """Коды и счётчики отправок — в файле 0600 (атомарная запись), просроченное выбрасывается при каждом чтении.

    Ячейка кода (``slot``) — строка вида ``login:<адрес>``; в файле — только её HMAC, HMAC кода, срок, попытки и
    свои данные (uid). Счётчики отправок — по HMAC адреса и HMAC IP."""

    def __init__(self, store: Path, key: bytes | Callable[[], bytes], clock: Callable[[], float] = time.time):
        self.store, self._key, self.clock, self.lock = store, key, clock, threading.Lock()

    def key(self) -> bytes:
        return self._key() if callable(self._key) else self._key

    def mac(self, text: str) -> str:
        return hmac.new(self.key(), text.encode(), hashlib.sha256).hexdigest()

    def _load(self) -> dict:
        try:
            d = json.loads(self.store.read_text())
        except (OSError, ValueError):
            d = {}
        now = self.clock()
        return {"codes": {k: v for k, v in (d.get("codes") or {}).items() if v.get("exp", 0) > now},
                "sends": {k: [t for t in v if now - t < 3600] for k, v in (d.get("sends") or {}).items()},
                "ips": {k: [t for t in v if now - t < 3600] for k, v in (d.get("ips") or {}).items()}}

    def _save(self, d: dict):
        d["sends"] = {k: v for k, v in d["sends"].items() if v}
        d["ips"] = {k: v for k, v in d["ips"].items() if v}
        write_private(self.store, json.dumps(d))

    def issue(self, slot: str, addr: str, ip: str = "", cooldown: bool = True, decoy: bool = False,
              **data) -> str | None:
        """Новый код в ячейку ``slot`` (прежний гасится). Лимиты — по адресу и по IP, одинаковые для своих и чужих
        адресов. ``decoy`` — пустышка: код не выдаётся (None), проверка отвечает как обычно, но не проходит."""
        now = self.clock()
        with self.lock:
            d = self._load()
            sent = d["sends"].setdefault(self.mac("a:" + addr), [])
            by_ip = d["ips"].setdefault(self.mac("ip:" + ip), [])
            if cooldown and sent and now - sent[-1] < RESEND_AFTER:
                raise LimitError("Код уже отправлен — новый можно запросить через минуту.",
                                 _wait(RESEND_AFTER - (now - sent[-1])))
            if len(sent) >= PER_HOUR:
                raise LimitError("Слишком много кодов на этот адрес — попробуйте через час.",
                                 _wait(3600 - (now - sent[0])))
            if ip and len(by_ip) >= IP_PER_HOUR:
                raise LimitError("Слишком много запросов — попробуйте через час.", _wait(3600 - (now - by_ip[0])))
            sent.append(now)
            if ip:
                by_ip.append(now)
            code = None if decoy else f"{secrets.randbelow(10**6):06d}"
            secret = code if code else secrets.token_hex(16)             # пустышку угадать нельзя
            d["codes"][self.mac("s:" + slot)] = {"hash": self.mac(f"c:{slot}:{secret}"), "exp": now + CODE_TTL,
                                                  "tries": 0, **data}
            self._save(d)
        return code

    def forget(self, slot: str, addr: str):
        """Письмо не ушло: код гасится, а отправка не считается — можно сразу попробовать снова."""
        with self.lock:
            d = self._load()
            d["codes"].pop(self.mac("s:" + slot), None)
            sent = d["sends"].get(self.mac("a:" + addr)) or []
            if sent:
                sent.pop()
            self._save(d)

    def check(self, slot: str, code) -> dict:
        """Верный код → данные ячейки (код гасится). Иначе ValueError: «не подошёл, осталось N» или «устарел»."""
        code = "".join(ch for ch in str(code or "") if ch.isdigit())
        if len(code) != 6:
            raise ValueError("Введите 6 цифр из письма.")
        sid = self.mac("s:" + slot)
        with self.lock:
            d = self._load()
            c = d["codes"].get(sid)
            if not c:
                raise ValueError("Код устарел — запросите новый.")
            c["tries"] += 1
            if not hmac.compare_digest(c["hash"], self.mac(f"c:{slot}:{code}")):
                left = MAX_TRIES - c["tries"]
                if left <= 0:
                    d["codes"].pop(sid)
                self._save(d)
                raise ValueError(f"Код не подошёл. Осталось попыток: {left}." if left > 0 else
                                 "Код не подошёл — попытки кончились, запросите новый.")
            d["codes"].pop(sid)
            self._save(d)
        return {k: v for k, v in c.items() if k not in ("hash", "exp", "tries")}


def hmac_key() -> bytes:
    """Ключ HMAC кодов из secrets.json; нет — создаётся (32 байта) и сохраняется туда же (0600)."""
    k = providers.load_keys().get(HMAC_KEY)
    if not k:
        k = secrets.token_hex(32)
        providers.save_key(HMAC_KEY, k)
    return bytes.fromhex(k)


# ---------- служба: вход, привязка, второй фактор, оповещения ----------
class Service:
    """Всё, что панель и бот делают с почтой. ``people`` — ``people.People``; ``deliver`` — подменяется в тестах."""

    def __init__(self, section: dict | None, people, store: Path, key: bytes | Callable[[], bytes] = hmac_key,
                 clock: Callable[[], float] = time.time, background: bool = True):
        self.section, self.people, self.background = dict(section or {}), people, background
        self.codes = Codes(store, key, clock)
        self.sender: Callable[[Smtp, EmailMessage], None] = send

    def smtp(self) -> Smtp | None:
        return smtp_settings(self.section)

    @property
    def enabled(self) -> bool:
        return self.smtp() is not None

    def need(self) -> Smtp:
        if not (s := self.smtp()):
            raise RuntimeError("почта не настроена — владелец пульта может включить её в config.toml ([email])")
        return s

    def deliver(self, to: str, subject: str, text: str, wait: bool = False, on_fail: Callable[[], None] | None = None):
        """Письмо — в фоне (ответ не ждёт SMTP), ``wait`` — сразу, с ошибкой наверх (привязка из настроек)."""
        smtp = self.need()
        msg = message(smtp, to, subject, text)

        def go():
            try:
                self.sender(smtp, msg)
                return True
            except (OSError, smtplib.SMTPException) as e:
                log("email_send_failed", to=mask(to), error=type(e).__name__)
                if on_fail:
                    on_fail()
                if wait:
                    raise RuntimeError(f"не получилось отправить письмо: {type(e).__name__}") from None
                return False

        if wait or not self.background:
            return go()
        threading.Thread(target=go, daemon=True).start()
        return True

    # --- вход по почте ---
    def login_start(self, raw, ip: str = "") -> dict:
        """Одинаковый ответ для привязанного и чужого адреса; письмо — только привязанному человеку с ролью."""
        self.need()
        addr = normalize(raw)
        if not addr:
            raise ValueError("Укажите адрес почты целиком, например name@example.com")
        uid = self.people.by_email(addr)
        slot = f"login:{addr}"
        code = self.codes.issue(slot, addr, ip, decoy=uid is None, uid=uid)
        if code:
            subject, text = code_text(code, "для входа в пульт")
            self.deliver(addr, subject, text, on_fail=lambda: self.codes.forget(slot, addr))
        log("email_code_requested", to=mask(addr), ip=ip)        # свой ли адрес — не пишем даже в журнал
        return {"sent": True, "message": SAME_ANSWER, "resend_in": RESEND_AFTER, "ttl": CODE_TTL}

    def login_verify(self, raw, code, ip: str = "") -> int:
        self.need()
        addr = normalize(raw)
        if not addr:
            raise ValueError("Укажите адрес почты целиком, например name@example.com")
        try:
            data = self.codes.check(f"login:{addr}", code)
        except ValueError:
            log("email_login_failed", to=mask(addr), ip=ip)
            raise
        uid = data.get("uid")
        if uid is None or self.people.by_email(addr) != uid:          # пустышка или адрес за это время отвязали
            log("email_login_failed", to=mask(addr), ip=ip)
            raise ValueError("Код устарел — запросите новый.")
        log("email_login_ok", uid=uid, ip=ip)
        return int(uid)

    # --- привязка адреса из настроек ---
    def info(self, uid) -> dict:
        rec = self.people.email(uid)
        return {"enabled": self.enabled, "address": rec.get("address", ""), "at": rec.get("at"),
                "second_factor": bool(rec.get("second_factor")), "notify": bool(rec.get("notify")),
                "resend_in": RESEND_AFTER, "ttl": CODE_TTL}

    def bind_start(self, uid, raw, ip: str = "") -> dict:
        self.need()
        addr = normalize(raw)
        if not addr:
            raise ValueError("Укажите адрес почты целиком, например name@example.com")
        other = self.people.by_email(addr)
        if other is not None and other != int(uid):
            raise ValueError("Этот адрес уже привязан к другому человеку пульта.")
        slot = f"bind:{int(uid)}:{addr}"
        code = self.codes.issue(slot, addr, ip, uid=int(uid))
        subject, text = code_text(code, "для привязки почты к пульту")
        try:
            self.deliver(addr, subject, text, wait=True)
        except RuntimeError:
            self.codes.forget(slot, addr)
            raise
        log("email_bind_code", uid=uid, to=mask(addr))
        return {"sent": True, "to": addr, "resend_in": RESEND_AFTER, "ttl": CODE_TTL}

    def bind_confirm(self, uid, raw, code) -> dict:
        self.need()
        addr = normalize(raw)
        if not addr:
            raise ValueError("Укажите адрес почты целиком, например name@example.com")
        self.codes.check(f"bind:{int(uid)}:{addr}", code)
        other = self.people.by_email(addr)
        if other is not None and other != int(uid):
            raise ValueError("Этот адрес уже привязан к другому человеку пульта.")
        self.people.set_email(uid, address=addr, at=int(time.time()))
        log("email_bound", uid=uid, to=mask(addr))
        return self.info(uid)

    def unbind(self, uid) -> dict:
        self.people.set_email(uid, address=None)
        log("email_unbound", uid=uid)
        return self.info(uid)

    def options(self, uid, second_factor=None, notify=None) -> dict:
        if not self.people.email(uid).get("address"):
            raise ValueError("Сначала привяжите почту.")
        upd = {}
        if second_factor is not None:
            if second_factor:
                self.need()
            upd["second_factor"] = bool(second_factor)
        if notify is not None:
            upd["notify"] = bool(notify)
        self.people.set_email(uid, **upd)
        log("email_options", uid=uid, **{k: int(v) for k, v in upd.items()})
        return self.info(uid)

    # --- второй фактор: после входа через Telegram (и ключом) ---
    def wants_second(self, uid) -> bool:
        rec = self.people.email(uid)
        return bool(rec.get("second_factor") and rec.get("address")) and self.enabled

    def second_start(self, uid, ip: str = "") -> dict:
        """Код на почту человека; браузер получает номер ожидания (вход ещё не выдан)."""
        addr = self.people.email(uid)["address"]
        pid = secrets.token_urlsafe(24)
        slot = f"2fa:{pid}"
        code = self.codes.issue(slot, addr, ip, cooldown=False, uid=int(uid))
        subject, text = code_text(code, "подтверждения входа в пульт")
        self.deliver(addr, subject, text, on_fail=lambda: self.codes.forget(slot, addr))
        log("second_factor_sent", uid=uid, ip=ip)
        return {"state": "2fa", "id": pid, "to": mask(addr), "ttl": CODE_TTL}

    def second_verify(self, pid: str, code, ip: str = "") -> int:
        try:
            data = self.codes.check(f"2fa:{str(pid)[:64]}", code)
        except ValueError:
            log("second_factor_failed", ip=ip)
            raise
        uid = int(data["uid"])
        if not self.people.role(uid):
            raise ValueError("Доступа к пульту больше нет.")
        log("second_factor_ok", uid=uid, ip=ip)
        return uid

    # --- оповещения ---
    def notify(self, uid, subject: str, text: str) -> bool:
        """Письмо-оповещение человеку, если почта включена, адрес привязан и он сам включил оповещения."""
        rec = self.people.email(uid)
        if not (self.enabled and rec.get("notify") and rec.get("address")):
            return False
        self.deliver(rec["address"], subject, text + "\n\n— gas-pult. Отключить письма: панель → «Настройки» → "
                     "«Почта для входа и оповещений».\n")
        log("email_notify", uid=uid)
        return True


def notify_email(service: Service, uid, subject: str, text: str) -> bool:
    """Канал оповещений по почте (для бота и будущих событий): молча False, если у человека выключено."""
    try:
        return service.notify(uid, subject, text)
    except (RuntimeError, OSError, ValueError) as e:
        log("email_notify_failed", uid=uid, error=type(e).__name__)
        return False
