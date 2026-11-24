"""Согласие человека перед подключением своего аккаунта (владелец 23.11: «пусть пользователь сам решает»).

Перед каждым подключением — MCP-сервер, коннектор claude.ai, мессенджер, ключ модели, календарь — панель показывает
экран согласия: что подключается, что агент сможет читать и отправлять и что аккаунт и соблюдение правил сервиса — на
человеке. Кнопка «Подключить» неактивна без галочки «Понимаю: аккаунт мой, ответственность моя».

Сервер проверяет тоже: путь подключения зовёт ``require`` — без записи согласия на это подключение и текущую версию
текста (``CONSENT_V``) — исключение ``Needed`` (панель отвечает 409 ``code=consent``). Поменяли смысл текста — поднимите
``CONSENT_V``: согласие спросят заново.

Хранение — ``consents.json`` в папке данных пульта через общий слой ``store`` (замок, атомарная запись, 0600).
Только добавление: запись не меняется и не удаляется — это журнал «кто, что, когда, какая версия текста».
Кто: ``uid:<Telegram ID>`` (вошедший человек) или ``space:<пространство>`` / ``focus:<id ссылки>`` (фокус-ссылка),
``form:<id ссылки>`` (анкета клиента /q/).

Согласие с документом (владелец 24.11: политика обработки персональных данных и условия) — записи ``what=doc:<имя>``:
документ (``privacy``, ``terms``), его версия ``v`` и SHA-256 отданного текста той версии (``sha256``) — ``record_doc``.
Анкета /q/ — перед отправкой, фокус-ссылка — перед первым открытием (``DocNeeded`` → 409 ``code=privacy``).
Только стандартная библиотека; нижний слой — не импортирует ни бот, ни панель.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from gas_pult import store

CONSENT_V = "2026-11-24"                # поменяли смысл текста — новая дата: согласие спросят заново
FILE = "consents.json"
TITLE = "Подключение вашего аккаунта"
CHECK = "Понимаю: аккаунт мой, ответственность моя"
POINTS = (
    "Вы подключаете свой аккаунт или свой ключ. Пульт не создаёт аккаунты и не делится ими.",
    "Агент в ваших сессиях сможет читать и делать в сервисе то, что разрешает подключение. Отправка людям и "
    "платежи — только после вашего «Да» в панели, если сервис это поддерживает.",
    "Аккаунт, ключ и соблюдение правил сервиса — на вас: условия поставщика, законы вашей страны, согласие людей, "
    "чью переписку видит агент.",
    "Отключить можно в любой момент в «Подключениях». Дата и версия этого текста сохраняются на сервере пульта.",
)
KINDS = ("mcp", "connector", "messenger", "key", "calendar")
WHAT = re.compile(r"^(?:" + "|".join(KINDS) + r"):[a-z0-9][a-z0-9_.-]{0,47}$")
WHO = re.compile(r"^(?:uid:-?\d{1,20}|space:[a-z0-9][a-z0-9_-]{0,40}|(?:focus|form):[A-Za-z0-9_-]{1,64})$")
DOCS = ("privacy", "terms")             # документы, согласие с которыми пишем: политика ПДн и условия
DOC_CHECK = "Согласен(на) на обработку персональных данных по Политике"
SHA = re.compile(r"^[0-9a-f]{64}$")
PER_WHO = 2000                          # предохранитель: столько записей на одного человека (каталог × версии ≪ этого)


class DocNeeded(Exception):
    """Нет согласия с политикой (и условиями) на их текущие версии: панель отвечает 409 ``code=privacy``."""

    def __init__(self, docs: dict):
        super().__init__("Отметьте «" + DOC_CHECK + "» — без согласия продолжить нельзя.")
        self.docs = docs                # {"privacy": версия, "terms": версия} — что подтвердить


class Needed(Exception):
    """Нет согласия на это подключение (или оно на старый текст): панель отвечает 409 ``code=consent``."""

    def __init__(self, what: str):
        super().__init__("Сначала подтвердите: аккаунт ваш и ответственность за него — ваша. Откройте подключение "
                         "заново и отметьте «" + CHECK + "».")
        self.what = what


def path_of(data: Path) -> Path:
    return Path(data) / FILE


def check_what(what: str) -> str:
    what = str(what or "").strip().lower()
    if not WHAT.match(what):
        raise ValueError("неизвестное подключение")
    return what


def check_who(who: str) -> str:
    who = str(who or "")
    if not WHO.match(who):
        raise ValueError("не знаю, чьё согласие записать")
    return who


def has(path: Path, who: str, what: str) -> dict | None:
    """Запись согласия ``who`` на ``what`` на текущую версию текста или None."""
    recs = store.load(path).get(str(who)) or []
    return next((r for r in reversed(recs) if isinstance(r, dict) and r.get("what") == what
                 and r.get("v") == CONSENT_V), None)


def require(path: Path, who: str, what: str) -> None:
    """Подключение без согласия на текущий текст — ``Needed`` (409)."""
    if not has(path, who, what):
        raise Needed(what)


def record(path: Path, who: str, what: str, title: str = "", clock=time.time) -> dict:
    """Записать согласие (только добавлением). Уже есть на эту версию — вернуть его, второй раз не пишем."""
    who, what = check_who(who), check_what(what)
    title = re.sub(r"\s+", " ", str(title or ""))[:80]

    def add(d: dict) -> dict:
        recs = d.setdefault(who, [])
        old = next((r for r in recs if r.get("what") == what and r.get("v") == CONSENT_V), None)
        if old:
            return old
        if len(recs) >= PER_WHO:
            raise ValueError("слишком много записей согласия — напишите владельцу пульта")
        rec = {"what": what, "title": title, "v": CONSENT_V, "at": int(clock())}
        recs.append(rec)
        return rec

    return dict(store.update(path, add))


def listing(path: Path, who: str) -> list[dict]:
    """Согласия ``who`` — все версии, по порядку записи."""
    return [dict(r) for r in store.load(path).get(str(who)) or [] if isinstance(r, dict)]


def public(path: Path, who: str) -> dict:
    """Для панели: текст экрана, версия и что уже подтверждено на текущую версию."""
    recs = listing(path, who)
    return {"v": CONSENT_V, "title": TITLE, "check": CHECK, "points": list(POINTS),
            "given": sorted({r["what"] for r in recs if r.get("v") == CONSENT_V and r.get("what")
                             and not str(r["what"]).startswith("doc:")}),
            "log": recs[-50:]}


# ---------- согласие с документом: политика ПДн, условия ----------
def has_doc(path: Path, who: str, doc: str, v: str) -> dict | None:
    """Запись согласия ``who`` с документом ``doc`` версии ``v`` или None."""
    recs = store.load(path).get(str(who)) or []
    return next((r for r in reversed(recs) if isinstance(r, dict) and r.get("what") == f"doc:{doc}"
                 and r.get("v") == v), None)


def record_doc(path: Path, who: str, doc: str, v: str, sha: str, clock=time.time) -> dict:
    """Записать согласие с документом ``doc`` версии ``v`` (``sha`` — SHA-256 отданного текста). Только добавлением;
    уже есть на эту версию и этот текст — вернуть его. Текст той же версии поменялся (поправили оператора) — новая
    запись с новым хешем: журнал хранит, с каким именно текстом согласились."""
    who = check_who(who)
    if doc not in DOCS:
        raise ValueError("неизвестный документ")
    v, sha = str(v or "")[:32], str(sha or "").lower()
    if not v or not SHA.match(sha):
        raise ValueError("нет версии или хеша документа")

    def add(d: dict) -> dict:
        recs = d.setdefault(who, [])
        old = next((r for r in recs if r.get("what") == f"doc:{doc}" and r.get("v") == v
                    and r.get("sha256") == sha), None)
        if old:
            return old
        if len(recs) >= PER_WHO:
            raise ValueError("слишком много записей согласия — напишите владельцу пульта")
        rec = {"what": f"doc:{doc}", "doc": doc, "v": v, "sha256": sha, "at": int(clock())}
        recs.append(rec)
        return rec

    return dict(store.update(path, add))
