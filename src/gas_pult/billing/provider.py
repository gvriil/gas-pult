"""Поставщик платежей: общий интерфейс, проверка подписи вебхука и заглушка ``none``.

Поставщика пока нет — он ждёт юрлица в ЕС (решение владельца 22.11). Заглушка честно отвечает «не подключён».
Подключить поставщика — docs/BILLING.md: наследник ``ProviderBase`` с ``create_payment`` и ``parse_event``;
подпись, время и повтор проверяет общий ``verify_signature``.

Формат подписи (общий для HMAC-поставщиков): заголовок ``t=<unix-время>,v1=<hex HMAC-SHA256>``; подписывается
строка ``<t>.<тело запроса>``. Несколько ``v1`` — смена секрета без простоя.
"""

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

TOLERANCE = 300                      # секунд: старше или из будущего дальше — отказ
WAITING = "поставщик не подключён — ждёт юрлица"


class WebhookError(ValueError):
    """Вебхук отклонён; ``code`` — почему (для журнала и ответа 400 без подробностей)."""

    code = "webhook"


class BadSignature(WebhookError):
    code = "signature"


class Expired(WebhookError):
    code = "expired"


class Replayed(WebhookError):
    code = "replay"


class NotConnected(RuntimeError):
    """Поставщик не подключён: платёж онлайн невозможен, счета — вручную."""


@dataclass(frozen=True)
class Event:
    """Событие поставщика после проверки: ``id`` — для идемпотентности (ключ журнала ``evt:<id>``)."""

    id: str
    type: str
    invoice: str = ""
    amount: int = 0
    currency: str = ""
    raw: dict = field(default_factory=dict)


def sign(secret: bytes, body: bytes, ts: int) -> str:
    """Подпись для заголовка (тесты и исходящие вебхуки)."""
    mac = hmac.new(secret, f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def verify_signature(secrets: list[bytes], body: bytes, header: str, *, now: float | None = None,
                     tolerance: int = TOLERANCE, seen: Callable[[str], bool] | None = None) -> int:
    """Проверить подпись, время и повтор. Возвращает время подписи; иначе ``BadSignature``/``Expired``/``Replayed``.

    ``seen(sig) -> bool`` — True, если подпись видим впервые (``store.remember_webhook``); без него повтор не ловится,
    поэтому у поставщика он обязателен."""
    if not secrets or not all(isinstance(s, bytes) and len(s) >= 16 for s in secrets):
        raise BadSignature("нет секрета вебхука")
    parts: dict[str, list[str]] = {}
    for kv in str(header or "").split(","):
        k, _, v = kv.strip().partition("=")
        parts.setdefault(k, []).append(v)
    try:
        ts = int(parts.get("t", [""])[0])
    except ValueError:
        raise BadSignature("нет времени в подписи") from None
    sigs = [s for s in parts.get("v1", []) if s]
    if not sigs:
        raise BadSignature("нет подписи")
    good = None
    for secret in secrets:                                   # сравнение — за постоянное время
        want = hmac.new(secret, f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
        for s in sigs:
            if hmac.compare_digest(want, s):
                good = s
    if good is None:
        raise BadSignature("подпись не совпала")
    if abs((time.time() if now is None else now) - ts) > tolerance:
        raise Expired("подпись просрочена")
    if seen is None:
        raise Replayed("нет защиты от повтора")
    if not seen(hashlib.sha256(f"{ts}.{good}".encode()).hexdigest()):
        raise Replayed("повтор вебхука")
    return ts


class ProviderBase:
    """Интерфейс поставщика. Наследник задаёт ``name``, ``secrets()``, ``create_payment`` и ``parse_event``."""

    name = "base"
    header = "X-Signature"

    def status(self) -> dict:
        return {"name": self.name, "connected": True, "note": ""}

    def secrets(self) -> list[bytes]:
        raise NotImplementedError

    def create_payment(self, invoice: dict, key: str) -> dict:
        """Платёж по счёту у поставщика: {"url": куда отправить клиента, "id": номер у поставщика}."""
        raise NotImplementedError

    def parse_event(self, body: bytes) -> Event:
        raise NotImplementedError

    def verify_webhook(self, headers: dict, body: bytes, *, seen: Callable[[str], bool],
                       now: float | None = None) -> Event:
        """Подпись HMAC, время, повтор — общим кодом; затем разбор тела поставщиком."""
        h = {str(k).lower(): v for k, v in (headers or {}).items()}
        verify_signature(self.secrets(), body, h.get(self.header.lower(), ""), now=now, seen=seen)
        return self.parse_event(body)


class NoneProvider(ProviderBase):
    """Заглушка: поставщика нет. Ничего не принимает и не обещает."""

    name = "none"

    def status(self) -> dict:
        return {"name": self.name, "connected": False, "note": WAITING}

    def secrets(self) -> list[bytes]:
        return []

    def create_payment(self, invoice: dict, key: str) -> dict:
        raise NotConnected(WAITING)

    def parse_event(self, body: bytes) -> Event:
        raise NotConnected(WAITING)

    def verify_webhook(self, headers: dict, body: bytes, *, seen=None, now=None) -> Event:
        raise NotConnected(WAITING)


class JsonHmacProvider(ProviderBase):
    """Образец для тестов и для подключения: тело — JSON {"id", "type", "invoice", "amount", "currency"}."""

    name = "json-hmac"

    def __init__(self, secrets: list[bytes]):
        self._secrets = list(secrets)

    def secrets(self) -> list[bytes]:
        return self._secrets

    def create_payment(self, invoice: dict, key: str) -> dict:
        raise NotConnected(WAITING)

    def parse_event(self, body: bytes) -> Event:
        d = json.loads(body)
        amount = d.get("amount", 0)
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise WebhookError("сумма события — целые центы")
        if not d.get("id") or not d.get("type"):
            raise WebhookError("в событии нет id или type")
        return Event(str(d["id"]), str(d["type"]), str(d.get("invoice") or ""), amount, str(d.get("currency") or ""),
                     d)


PROVIDERS = {"none": NoneProvider}


def get(name: str = "none") -> ProviderBase:
    """Поставщик по имени; пока есть только ``none``."""
    return PROVIDERS.get(name, NoneProvider)()
