"""Ключи календарей из панели («Интеграции» → «Календари»): владелец вставляет секрет в поле — пульт кладёт его в файл
коннектора 0600 (``~/.config/gastech-mcp/calendar-<имя>.json``, его читает ``connectors/calendar_mcp.py``) и сразу
проверяет подключение. Владелец секреты в чат не шлёт и файлы руками не кладёт (штаб 18.11).

- Google Календарь — «Секретный адрес в формате iCal» (только чтение) → ``calendar-google.json`` ``{kind: ics}``;
- iCloud (Apple) — Apple ID и пароль приложения (appleid.apple.com → «Пароли приложений») →
  ``calendar-icloud.json`` ``{kind: caldav, url: https://caldav.icloud.com}``.

Значение секрета наружу не уходит: ни в ответ API, ни в журнал, ни в текст ошибки — только «подключено» и что
проверено (число календарей). Не прошла проверка — файл не остаётся.
"""

from __future__ import annotations

import json
import re
import urllib.parse

from gas_pult.config import write_private
from gas_pult.connectors import _core
from gas_pult.connectors import calendar_mcp as cal

KINDS = {"google": "Google Календарь", "icloud": "iCloud (Apple)"}
ICLOUD = "https://caldav.icloud.com"
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$")
_APP_PW = re.compile(r"^[a-z]{4}-?[a-z]{4}-?[a-z]{4}-?[a-z]{4}$")


def path(kind: str):
    return cal._key_dir() / f"calendar-{kind}.json"


def status() -> list[dict]:
    """Что подключено — без значений: {kind, title, on, user?} (Apple ID — с маской)."""
    out = []
    for k, title in KINDS.items():
        row = {"kind": k, "title": title, "on": path(k).is_file()}
        if row["on"] and k == "icloud":
            try:
                u = json.loads(path(k).read_text(encoding="utf-8")).get("user", "")
                row["user"] = u[:2] + "…@" + u.split("@")[-1] if "@" in u else ""
            except (OSError, ValueError):
                pass
        out.append(row)
    return out


def _google(url: str) -> dict:
    url = re.sub(r"^webcal://", "https://", str(url or "").strip(), flags=re.I)
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or (u.hostname or "").lower() != "calendar.google.com" or not u.path.endswith(".ics"):
        raise ValueError("нужен «Секретный адрес в формате iCal»: https://calendar.google.com/…/basic.ics")
    if "/private-" not in u.path:
        raise ValueError("это открытый адрес календаря — нужен именно секретный (в пути есть «private-»)")
    return {"kind": "ics", "url": url, "google": True}


def _icloud(user: str, password: str) -> dict:
    user, pw = str(user or "").strip(), re.sub(r"\s", "", str(password or "")).lower()
    if not _EMAIL.match(user):
        raise ValueError("Apple ID — адрес почты, с которым вы входите в iCloud")
    if not _APP_PW.match(pw):
        raise ValueError("нужен пароль приложения (16 букв, вида abcd-efgh-ijkl-mnop), а не пароль Apple ID")
    if "-" not in pw:
        pw = "-".join(pw[i:i + 4] for i in range(0, 16, 4))
    return {"kind": "caldav", "url": ICLOUD, "user": user, "app_password": pw}


def _check(kind: str) -> str:
    """Проверить подключение по записанному файлу: что видно — словами (без значений)."""
    _, cfg = cal._cal(kind)
    if kind == "icloud":
        n = len(cal._collections(cfg))
        return f"календарей в iCloud: {n}"
    n = len(cal.parse_ics(cal._ics(cfg)))
    return f"событий в календаре: {n}"


def save(kind: str, b: dict) -> dict:
    """Записать ключ (0600) и проверить; не вышло — файл убрать, ошибку — без значения секрета."""
    if kind not in KINDS:
        raise ValueError("календарь: google или icloud")
    rec = _google(b.get("url")) if kind == "google" else _icloud(b.get("user"), b.get("password"))
    d = cal._key_dir()
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    p = path(kind)
    write_private(p, json.dumps(rec, ensure_ascii=False))
    try:
        what = _check(kind)
    except Exception as e:                       # сеть, адрес, пароль — файл не оставляем
        p.unlink(missing_ok=True)
        msg = str(e) if isinstance(e, (_core.ToolError, ValueError)) else "сервер календаря недоступен"
        for s in (rec.get("url", "") if kind == "google" else "", rec.get("app_password", ""), rec.get("user", "")):
            if s:
                msg = msg.replace(s, "[скрыто]")
        raise ValueError(f"не подключилось: {msg}") from None
    return {"ok": True, "kind": kind, "checked": what, "calendars": status()}


def remove(kind: str) -> dict:
    if kind not in KINDS:
        raise ValueError("календарь: google или icloud")
    path(kind).unlink(missing_ok=True)
    return {"ok": True, "calendars": status()}
