"""Календарь для пульта (CalDAV и ссылка iCal): календари, события за период, одно событие — чтение; новое событие —
только черновиком и после «Да» человека.

Календари — по файлу на календарь ``~/.config/gastech-mcp/calendar-<имя>.json`` (0600), каталог меняется
``GAS_CAL_KEY_DIR``:
- ``{"kind": "caldav", "url": "https://caldav.yandex.ru/", "user": "...", "app_password": "..."}`` — CalDAV (Яндекс
  Календарь, Nextcloud, iCloud — пароли приложений); ``url`` — корень сервера или адрес одного календаря;
- ``{"kind": "ics", "url": "https://calendar.google.com/calendar/ical/.../basic.ics"}`` — секретная ссылка iCal
  (Google и другие), только чтение. Ссылка — секрет: в ответах не показывается.
Необязательно: ``tz`` — часовой пояс ответов (иначе ``GAS_CAL_TZ``, иначе пояс сервера). Без HTTPS — только 127.0.0.1.
Контракт — docs/CONNECTORS.md, описание — docs/connectors/calendar.md.

Повторяющиеся события (RRULE) разворачиваются сами: FREQ=DAILY/WEEKLY/MONTHLY/YEARLY с INTERVAL, COUNT, UNTIL,
BYDAY, BYMONTHDAY, EXDATE и изменёнными повторами (RECURRENCE-ID). Другое правило — событие помечается
«повторяется, правило: …» и показывается один раз.

Запись: ``calendar_propose_event`` — черновик нового события (только CalDAV); ``calendar_apply`` — после
подтверждения человека и при ``GAS_CAL_WRITE=1``: PUT нового файла с ``If-None-Match: *`` — существующее событие
перезаписать нельзя. Изменение и удаление событий — не реализованы.

Google API Limited Use: данные календарей Google (ссылка на calendar.google.com) не отдаются моделям, которые учатся
на данных (``:free``, DeepSeek напрямую, NVIDIA trial) — по ``GAS_PULT_MODEL`` / ``OPENROUTER_MODEL`` /
``ANTHROPIC_MODEL``. ``GAS_CAL_GOOGLE_OK=1`` — пульт сам проверил поставщика окна (кроме ``:free`` — никогда).
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if __package__:
    from . import _core
else:                                                  # запуск файлом: python3 calendar_mcp.py
    import _core

SVC = "cal"                                            # GAS_CAL_WRITE, папка подтверждений confirm/cal
TIMEOUT = 25
MAX_BYTES = 5_000_000                                  # ICS больше — не читаем целиком
MAX_DAYS = 366
MAX_STEPS = 20_000                                     # шагов разворота одного RRULE
_NAME = re.compile(r"^[a-z0-9_-]{1,32}$")
_LOCAL = {"127.0.0.1", "localhost", "::1"}
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav"}
_DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
# Windows-имена поясов (Outlook, Exchange) → IANA: самые частые
_WIN_TZ = {"Russian Standard Time": "Europe/Moscow", "UTC": "UTC", "GMT Standard Time": "Europe/London",
           "W. Europe Standard Time": "Europe/Berlin", "Romance Standard Time": "Europe/Paris",
           "Central European Standard Time": "Europe/Warsaw", "E. Europe Standard Time": "Europe/Chisinau",
           "FLE Standard Time": "Europe/Kiev", "Ekaterinburg Standard Time": "Asia/Yekaterinburg",
           "N. Central Asia Standard Time": "Asia/Novosibirsk", "Eastern Standard Time": "America/New_York",
           "Pacific Standard Time": "America/Los_Angeles", "Central Standard Time": "America/Chicago"}
_GOOGLE_HOSTS = ("calendar.google.com", "www.google.com")


# ---------- календари и пароли ----------
def _key_dir() -> Path:
    return Path(os.environ.get("GAS_CAL_KEY_DIR") or _core.SECRETS_DIR).expanduser()


def calendars() -> list[str]:
    return sorted(p.name[9:-5] for p in _key_dir().glob("calendar-*.json") if _NAME.match(p.name[9:-5]))


def _cal(name: str | None) -> tuple[str, dict]:
    have = calendars()
    if not name:
        if len(have) == 1:
            name = have[0]
        elif not have:
            raise _core.ToolError(f"нет файла календаря calendar-<имя>.json — положите его в {_key_dir()} "
                                  "(права 0600), см. docs/connectors/calendar.md")
        else:
            raise _core.ToolError(f"календарей несколько — укажите calendar: {', '.join(have)}")
    name = str(name).strip().lower()
    if not _NAME.match(name):
        raise _core.ToolError("неверное имя календаря (латиница, цифры, - и _)")
    p = _key_dir() / f"calendar-{name}.json"
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except OSError:
        raise _core.ToolError(f"нет календаря «{name}» (файла {p.name}); есть: {', '.join(have) or 'ни одного'}") \
            from None
    except ValueError:
        cfg = None
    if not isinstance(cfg, dict) or cfg.get("kind") not in ("caldav", "ics") or not cfg.get("url"):
        raise _core.ToolError(f"файл {p.name}: нужен JSON с kind (caldav или ics) и url")
    if cfg["kind"] == "caldav" and not (cfg.get("user") and cfg.get("app_password")):
        raise _core.ToolError(f"файл {p.name}: для caldav нужны user и app_password")
    url = re.sub(r"^webcal://", "https://", str(cfg["url"]).strip(), flags=re.I)
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("https", "http") or not u.hostname:
        raise _core.ToolError(f"файл {p.name}: url — адрес https://…")
    if u.scheme == "http" and u.hostname not in _LOCAL:
        raise _core.ToolError(f"файл {p.name}: без шифрования (http) — только для проверки на 127.0.0.1")
    cfg["url"], cfg["name"] = url, name
    cfg["google"] = cfg.get("google") is True or (u.hostname or "").lower() in _GOOGLE_HOSTS
    return name, cfg


def _secrets(cfg: dict | None = None) -> list[str]:
    """Что прятать: пароли приложений, секретные ссылки iCal (и их путь), файлы календарей целиком."""
    found = [cfg] if cfg else []
    out = []
    for p in _key_dir().glob("calendar-*.json"):
        try:
            raw = p.read_text(encoding="utf-8").strip()
            out.append(raw)
            found.append(json.loads(raw))
        except (OSError, ValueError):
            continue
    for c in found:
        if not isinstance(c, dict):
            continue
        out.append(str(c.get("app_password") or ""))
        if c.get("kind") == "ics" and c.get("url"):
            url = str(c["url"])
            path = urllib.parse.urlsplit(url).path
            out += [url, re.sub(r"^https?://", "", url), path, urllib.parse.unquote(path)]
    return [s for s in out if s and len(s) >= 6]


def _tz(a: dict, cfg: dict | None = None) -> tzinfo:
    name = a.get("tz") or (cfg or {}).get("tz") or os.environ.get("GAS_CAL_TZ")
    if not name:
        return datetime.now().astimezone().tzinfo or UTC
    try:
        return ZoneInfo(str(name))
    except (ZoneInfoNotFoundError, ValueError):
        raise _core.ToolError(f"неизвестный часовой пояс «{name}» — например Europe/Moscow") from None


def _tzname(tz: tzinfo) -> str:
    return getattr(tz, "key", None) or str(tz)


# ---------- Google API Limited Use ----------
def google_block_reason() -> str | None:
    """Почему данные Google нельзя отдать модели этого окна; None — можно."""
    models = [os.environ.get(k, "") for k in ("GAS_PULT_MODEL", "OPENROUTER_MODEL", "ANTHROPIC_MODEL")]
    models = [m.strip().lower() for m in models if m and m.strip()]
    if any(":free" in m for m in models):
        bad = next(m for m in models if ":free" in m)
    elif os.environ.get("GAS_CAL_GOOGLE_OK") == "1":
        return None
    else:
        bad = next((m for m in models if "deepseek" in m or "nvidia" in m), None)
    if not bad:
        return None
    return (f"данные Google нельзя этой модели (Limited Use): «{bad}» может учиться на данных. Нужна модель без "
            "обучения на данных (Claude; OpenRouter — только с data_collection=deny и zdr); пульт подтверждает "
            "это переменной GAS_CAL_GOOGLE_OK=1")


def _check_google(cfg: dict) -> None:
    if cfg.get("google") and (why := google_block_reason()):
        raise _core.ToolError(f"календарь «{cfg['name']}»: {why}")


# ---------- HTTP ----------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):              # переадресацию разбираем сами: пароль — только на тот же хост
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _same_host(a: str, b: str) -> bool:
    x, y = urllib.parse.urlsplit(a), urllib.parse.urlsplit(b)
    dp = {"https": 443, "http": 80}
    return (x.scheme, x.hostname, x.port or dp.get(x.scheme)) == (y.scheme, y.hostname, y.port or dp.get(y.scheme))


# Сервисы, где календари лежат на другом узле того же домена: iCloud отвечает с caldav.icloud.com, а
# calendar-home-set указывает на узел pNN-caldav.icloud.com (у каждого аккаунта свой; адрес не постоянный).
_SITES = ("icloud.com",)


def _same_site(a: str, b: str) -> bool:
    """Тот же сервер — или узел того же сервиса из ``_SITES`` по https (пароль уходит только туда)."""
    if _same_host(a, b):
        return True
    x, y = urllib.parse.urlsplit(a), urllib.parse.urlsplit(b)
    if x.scheme != "https" or y.scheme != "https" or (x.port or 443) != 443 or (y.port or 443) != 443:
        return False
    hx, hy = (x.hostname or "").lower(), (y.hostname or "").lower()
    return any((hx == s or hx.endswith("." + s)) and (hy == s or hy.endswith("." + s)) for s in _SITES)


def _req(cfg: dict, method: str, url: str, body: str | None = None, headers: dict | None = None,
         ok: tuple = (200, 207)) -> tuple[int, bytes, str]:
    """Запрос к серверу календаря → (код, тело, итоговый адрес). Переадресация — до 3 раз, только на тот же хост."""
    h = {"User-Agent": "gas-pult-connector/1", **(headers or {})}
    if cfg["kind"] == "caldav":
        tok = base64.b64encode(f"{cfg['user']}:{cfg['app_password']}".encode()).decode()
        h["Authorization"] = f"Basic {tok}"
    if body is not None:
        h.setdefault("Content-Type", "application/xml; charset=utf-8")
    keys = _secrets(cfg)
    what = f"календарь «{cfg['name']}»"
    for _ in range(4):
        req = urllib.request.Request(url, data=body.encode() if body is not None else None, method=method, headers=h)
        try:
            with _OPENER.open(req, timeout=TIMEOUT) as r:
                raw = r.read(MAX_BYTES + 1)
                code = r.status
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location") if e.code in (301, 302, 303, 307, 308) else None
            if loc:
                nxt = urllib.parse.urljoin(url, loc)
                if not _same_site(nxt, url) and cfg["kind"] == "caldav":
                    raise _core.ToolError(f"{what}: сервер переадресует на другой адрес — укажите в файле url "
                                          f"{_core.hide(nxt, *keys)}") from None
                url = nxt
                continue
            code, raw = e.code, e.read(300)
            if code in ok:
                return code, raw, url
            hint = {401: " — вход не удался: проверьте user и пароль приложения", 403: " — нет доступа",
                    404: " — не найдено (проверьте url)", 412: " — такое событие уже есть",
                    429: " — лимит запросов, подождите"}.get(code, "")
            detail = raw.decode("utf-8", "replace")
            raise _core.ToolError(_core.hide(f"{what}: сервер ответил {code}{hint}: {detail[:200]}", *keys)) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise _core.ToolError(_core.hide(f"{what}: сервер недоступен: {getattr(e, 'reason', e)}", *keys)) \
                from None
        if len(raw) > MAX_BYTES:
            raise _core.ToolError(f"{what}: ответ больше {MAX_BYTES // 1_000_000} МБ — сузьте период")
        if code not in ok:
            raise _core.ToolError(f"{what}: неожиданный ответ {code}")
        return code, raw, url
    raise _core.ToolError(f"{what}: слишком много переадресаций")


# ---------- CalDAV ----------
def _xml(raw: bytes) -> ET.Element:
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        raise _core.ToolError("сервер календаря вернул не XML (это точно адрес CalDAV?)") from None


def _propfind(cfg: dict, url: str, props: str, depth: str) -> tuple[ET.Element, str]:
    body = f'<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:" ' \
           f'xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop>{props}</d:prop></d:propfind>'
    _, raw, final = _req(cfg, "PROPFIND", url, body, {"Depth": depth})
    return _xml(raw), final


def _href_in(root: ET.Element, prop: str, base: str) -> str | None:
    el = root.find(f".//d:{prop}/d:href", NS)
    return urllib.parse.urljoin(base, el.text.strip()) if el is not None and el.text else None


def _collections(cfg: dict) -> list[dict]:
    """Календари аккаунта CalDAV (RFC 4791 §6.2, RFC 5397): [{href, url, name}] — только с событиями (VEVENT)."""
    props = "<d:resourcetype/><d:displayname/><d:current-user-principal/><c:calendar-home-set/>" \
            "<c:supported-calendar-component-set/>"
    root, url = _propfind(cfg, cfg["url"], props, "0")
    cols = _parse_cols(root, url)
    if cols:                                           # в файле — адрес одного календаря
        return cols
    home = _href_in(root, "prop/c:calendar-home-set", url)
    if not home:
        principal = _href_in(root, "prop/d:current-user-principal", url)
        if not principal:
            raise _core.ToolError(f"календарь «{cfg['name']}»: сервер не назвал владельца (current-user-principal)"
                                  " — проверьте url")
        root, purl = _propfind(cfg, principal, "<c:calendar-home-set/>", "0")
        home = _href_in(root, "prop/c:calendar-home-set", purl)
        if not home:
            raise _core.ToolError(f"календарь «{cfg['name']}»: нет calendar-home-set — это сервер CalDAV?")
    if not _same_site(home, cfg["url"]):
        raise _core.ToolError(f"календарь «{cfg['name']}»: календари на другом сервере — укажите его в url")
    root, hurl = _propfind(cfg, home, "<d:resourcetype/><d:displayname/><c:supported-calendar-component-set/>",
                           "1")
    return _parse_cols(root, hurl)


def _parse_cols(root: ET.Element, base: str) -> list[dict]:
    out = []
    for resp in root.findall("d:response", NS):
        href = resp.findtext("d:href", "", NS).strip()
        prop = resp.find("d:propstat/d:prop", NS)
        if not href or prop is None or prop.find("d:resourcetype/c:calendar", NS) is None:
            continue
        comps = [c.get("name", "").upper() for c in prop.findall("c:supported-calendar-component-set/c:comp", NS)]
        if comps and "VEVENT" not in comps:
            continue                                   # только задачи (VTODO) — не события
        url = urllib.parse.urljoin(base, href)
        name = (prop.findtext("d:displayname", "", NS) or "").strip() or urllib.parse.unquote(
            urllib.parse.urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1])
        out.append({"href": urllib.parse.urlsplit(url).path, "url": url, "name": name})
    return out


def _pick(cols: list[dict], want: str | None) -> list[dict]:
    if not want:
        return cols
    w = str(want).strip()
    hit = [c for c in cols if w in (c["href"], c["name"]) or w.lower() == c["name"].lower()]
    if not hit:
        raise _core.ToolError(f"нет календаря «{w}»; есть: {', '.join(c['name'] for c in cols) or 'ни одного'}")
    return hit


def _utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _report(cfg: dict, col: dict, start: datetime, end: datetime) -> list[tuple[str, str]]:
    """REPORT calendar-query (RFC 4791 §7.8): [(href, iCalendar)] событий, пересекающих период."""
    body = ('<?xml version="1.0" encoding="utf-8"?><c:calendar-query xmlns:d="DAV:" '
            'xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag/><c:calendar-data/></d:prop>'
            '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
            f'<c:time-range start="{_utc(start)}" end="{_utc(end)}"/>'
            '</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>')
    _, raw, url = _req(cfg, "REPORT", col["url"], body, {"Depth": "1"})
    out = []
    for resp in _xml(raw).findall("d:response", NS):
        href = resp.findtext("d:href", "", NS).strip()
        data = resp.find(".//c:calendar-data", NS)
        if href and data is not None and data.text:
            out.append((urllib.parse.urlsplit(urllib.parse.urljoin(url, href)).path, data.text))
    return out


# ---------- iCalendar (RFC 5545): свой простой разбор ----------
def _unfold(text: str) -> list[str]:
    out: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        elif line.strip():
            out.append(line)
    return out


def _prop(line: str) -> tuple[str, dict, str]:
    """«DTSTART;TZID="Europe/Moscow":20261118T100000» → ("DTSTART", {"TZID": "Europe/Moscow"}, "20261118T100000")."""
    q, i = False, -1
    for n, ch in enumerate(line):
        if ch == '"':
            q = not q
        elif ch == ":" and not q:
            i = n
            break
    if i < 0:
        return line.upper(), {}, ""
    head, value = line[:i], line[i + 1:]
    parts = re.findall(r'(?:[^;"]|"[^"]*")+', head)
    params = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.strip().upper()] = v.strip().strip('"')
    return parts[0].strip().upper() if parts else "", params, value


def _text(v: str) -> str:
    return re.sub(r"\\([\\;,nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), v)


def parse_ics(text: str) -> list[dict]:
    """VEVENT → {props: {ИМЯ: [(params, value)]}}; вложенные VALARM пропускаются."""
    events, stack, cur = [], [], None
    for line in _unfold(text):
        name, params, value = _prop(line)
        if name == "BEGIN":
            stack.append(value.upper())
            if stack[-1] == "VEVENT":
                cur = {}
            continue
        if name == "END":
            if stack and stack[-1] == "VEVENT" and cur is not None:
                events.append(cur)
                cur = None
            if stack:
                stack.pop()
            continue
        if cur is not None and stack and stack[-1] == "VEVENT":
            cur.setdefault(name, []).append((params, value))
    return events


def _first(ev: dict, name: str) -> tuple[dict, str]:
    return (ev.get(name) or [({}, "")])[0]


def _zone(tzid: str | None, local: tzinfo) -> tuple[tzinfo, bool]:
    """Пояс по TZID → (пояс, узнан ли). Неизвестный — пояс ответа."""
    if not tzid:
        return local, True
    tzid = tzid.strip()
    for cand in (tzid, _WIN_TZ.get(tzid), "/".join(tzid.strip("/").split("/")[-2:])):   # /mozilla.org/…/Europe/Moscow
        if not cand:
            continue
        try:
            return ZoneInfo(cand), True
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return local, False


def _dt(params: dict, value: str, local: tzinfo) -> tuple[date | datetime, bool]:
    """Значение даты-времени → (дата для DATE, иначе datetime с поясом; узнан ли пояс)."""
    v = value.strip()
    if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", v):
        return datetime.strptime(v[:8], "%Y%m%d").date(), True
    m = re.fullmatch(r"(\d{8}T\d{4,6})(Z?)", v)
    if not m:
        raise ValueError(f"дата {v!r}")
    naive = datetime.strptime(m.group(1).ljust(15, "0"), "%Y%m%dT%H%M%S")
    if m.group(2):
        return naive.replace(tzinfo=UTC), True
    tz, known = _zone(params.get("TZID"), local)
    return naive.replace(tzinfo=tz), known


def _duration(v: str) -> timedelta:
    m = re.fullmatch(r"([+-]?)P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", v.strip())
    if not m:
        return timedelta(0)
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    td = timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)
    return -td if m.group(1) == "-" else td


def _rrule(v: str) -> dict:
    return {k.upper(): val for k, _, val in (p.partition("=") for p in v.split(";") if p)}


_SUPPORTED = {"FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "BYMONTHDAY", "WKST"}


def _rule_ok(r: dict) -> bool:
    if set(r) - _SUPPORTED or r.get("FREQ") not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        return False
    if r.get("WKST", "MO") != "MO":
        return False
    days = [d for d in r.get("BYDAY", "").split(",") if d]
    if days and r["FREQ"] in ("DAILY", "YEARLY"):
        return False
    if days and r["FREQ"] == "WEEKLY" and any(d not in _DAYS for d in days):
        return False
    if days and r["FREQ"] == "MONTHLY" and (r.get("BYMONTHDAY") or any(
            not re.fullmatch(r"[+-]?[1-5]?(MO|TU|WE|TH|FR|SA|SU)", d) for d in days)):
        return False
    if r.get("BYMONTHDAY") and (r["FREQ"] != "MONTHLY"
                                or not re.fullmatch(r"-?\d{1,2}(,-?\d{1,2})*", r["BYMONTHDAY"])):
        return False
    try:
        return int(r.get("INTERVAL", 1)) >= 1 and int(r.get("COUNT", 1)) >= 1
    except ValueError:
        return False


def _month_days(y: int, m: int) -> int:
    return ((date(y + m // 12, m % 12 + 1, 1)) - date(y, m, 1)).days


def _period_dates(r: dict, start: date, n: int) -> list[date]:
    """Даты n-го периода правила (по возрастанию), без учёта COUNT/UNTIL."""
    step = int(r.get("INTERVAL", 1)) * n
    freq = r["FREQ"]
    days = [d for d in r.get("BYDAY", "").split(",") if d]
    if freq == "DAILY":
        return [start + timedelta(days=step)]
    if freq == "WEEKLY":
        week = start - timedelta(days=start.weekday()) + timedelta(weeks=step)
        wd = sorted(_DAYS.index(d) for d in days) if days else [start.weekday()]
        return [week + timedelta(days=i) for i in wd]
    if freq == "YEARLY":
        try:
            return [start.replace(year=start.year + step)]
        except ValueError:                             # 29 февраля
            return []
    mi = start.month - 1 + step
    y, m = start.year + mi // 12, mi % 12 + 1
    last = _month_days(y, m)
    out = []
    if days:
        for d in days:
            mt = re.fullmatch(r"([+-]?\d?)(\w\w)", d)
            nth, wd = int(mt.group(1) or 0), _DAYS.index(mt.group(2))
            all_wd = [x for x in range(1, last + 1) if date(y, m, x).weekday() == wd]
            picked = all_wd if nth == 0 else ([all_wd[nth - 1]] if 0 < nth <= len(all_wd) else
                                               [all_wd[nth]] if -len(all_wd) <= nth < 0 else [])
            out += [date(y, m, x) for x in picked]
    else:
        for x in (r.get("BYMONTHDAY") or str(start.day)).split(","):
            k = int(x)
            k = last + k + 1 if k < 0 else k
            if 1 <= k <= last:
                out.append(date(y, m, k))
    return sorted(set(out))


def _expand(start, r: dict, until_end, exdates: set) -> list:
    """Начала повторов (date или datetime с поясом события) от start до until_end (не включая)."""
    count = int(r["COUNT"]) if "COUNT" in r else None
    until = None
    if "UNTIL" in r:
        u, _ = _dt({}, r["UNTIL"], UTC)
        until = u
    is_dt = isinstance(start, datetime)
    d0 = start.date() if is_dt else start
    out, seen, n = [], 0, 0
    while n < MAX_STEPS:
        dates = _period_dates(r, d0, n)
        n += 1
        if not dates and r["FREQ"] in ("DAILY", "WEEKLY"):
            break
        stop = False
        for d in dates:
            if d < d0:
                continue
            occ = datetime.combine(d, start.timetz()).replace(tzinfo=start.tzinfo) if is_dt else d
            if until is not None:
                if isinstance(until, datetime):
                    if (occ if is_dt else datetime.combine(occ, datetime.min.time(), UTC)) > until:
                        stop = True
                        break
                elif (occ.date() if is_dt else occ) > until:
                    stop = True
                    break
            if count is not None and seen >= count:
                stop = True
                break
            seen += 1
            if occ >= until_end:
                stop = True
                break
            if _key(occ) not in exdates:
                out.append(occ)
        if stop:
            break
    return out


def _key(v) -> str:
    """Ключ повтора для EXDATE и RECURRENCE-ID: момент в UTC (или дата для целого дня)."""
    if isinstance(v, datetime):
        return v.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return v.strftime("%Y%m%d")


def _fmt(v, tz: tzinfo) -> str:
    return v.astimezone(tz).isoformat() if isinstance(v, datetime) else v.isoformat()


def _as_dt(v, tz: tzinfo) -> datetime:
    return v if isinstance(v, datetime) else datetime.combine(v, datetime.min.time(), tz)


def events_in(ics_events: list[dict], start: datetime, end: datetime, tz: tzinfo, full: bool = False) -> list[dict]:
    """События (с развёрнутыми повторами), пересекающие [start, end)."""
    overrides: dict[tuple[str, str], dict] = {}
    for ev in ics_events:
        if ev.get("RECURRENCE-ID"):
            p, v = _first(ev, "RECURRENCE-ID")
            try:
                overrides[(_first(ev, "UID")[1], _key(_dt(p, v, tz)[0]))] = ev
            except ValueError:
                continue
    out = []
    for ev in ics_events:
        try:
            out += _occurrences(ev, overrides, start, end, tz, full)
        except (ValueError, KeyError, IndexError):
            continue                                   # битое событие — пропускаем, не роняем весь список
    out.sort(key=lambda e: (e["_sort"], e["summary"]))
    return out


def _occurrences(ev, overrides, start, end, tz, full) -> list[dict]:
    if _first(ev, "STATUS")[1].upper() == "CANCELLED" and not ev.get("RECURRENCE-ID"):
        return []
    p, v = _first(ev, "DTSTART")
    if not v:
        return []
    s0, known = _dt(p, v, tz)
    if ev.get("DTEND"):
        e0 = _dt(*_first(ev, "DTEND"), tz)[0]
        dur = _as_dt(e0, tz) - _as_dt(s0, tz)
    elif ev.get("DURATION"):
        dur = _duration(_first(ev, "DURATION")[1])
    else:
        dur = timedelta(days=1) if not isinstance(s0, datetime) else timedelta(0)
    uid = _first(ev, "UID")[1]
    rule_raw = _first(ev, "RRULE")[1]
    base = {"uid": uid, "summary": _text(_first(ev, "SUMMARY")[1]) or "(без названия)",
            "location": _text(_first(ev, "LOCATION")[1]), "all_day": not isinstance(s0, datetime)}
    desc = _text(_first(ev, "DESCRIPTION")[1])
    base["description"] = desc if full or len(desc) <= 200 else desc[:200] + "…"
    if not known:
        base["note"] = f"неизвестный пояс «{p.get('TZID')}» — время показано в поясе {_tzname(tz)}"
    if _first(ev, "STATUS")[1].upper() == "CANCELLED":
        base["status"] = "отменено"
    starts = [s0]
    if rule_raw and not ev.get("RECURRENCE-ID"):
        rule = _rrule(rule_raw)
        base["recurrence"] = f"повторяется, правило: {rule_raw}"
        if _rule_ok(rule):
            ex = set()
            for ep, evv in ev.get("EXDATE", []):
                for x in evv.split(","):
                    try:
                        ex.add(_key(_dt(ep, x, tz)[0]))
                    except ValueError:
                        continue
            ex |= {k for (u, k) in overrides if u == uid}
            limit = end if isinstance(s0, datetime) else end.astimezone(tz).date() + timedelta(days=1)
            starts = _expand(s0, rule, limit, ex)
        else:
            base["recurrence"] += " (разворот не поддерживается — показано первое событие)"
            sd0 = _as_dt(s0, tz)
            if sd0 < start and not full:               # первое — раньше периода: повторы в периоде не знаем
                return [{**base, "start": _fmt(s0, tz), "unexpanded": True, "_sort": sd0.astimezone(UTC).isoformat()}]
    out = []
    for s in starts:
        e = s + dur
        sd, ed = _as_dt(s, tz), _as_dt(e, tz)
        if not (sd < end and (ed > start or (sd == ed and sd >= start))):
            continue
        row = {**base, "start": _fmt(s, tz), "_sort": sd.astimezone(UTC).isoformat()}
        if isinstance(s, datetime):
            row["end"] = _fmt(e, tz)
        else:
            row["end"] = (e - timedelta(days=1) if e > s else s).isoformat()     # DTEND даты — не включительно
        if rule_raw and not ev.get("RECURRENCE-ID"):
            row["occurrence"] = _key(s)
        out.append(row)
    return out


# ---------- инструменты: чтение ----------
def _period(a: dict, tz: tzinfo) -> tuple[date, date]:
    try:
        d1 = date.fromisoformat(str(a["from"]).strip()) if a.get("from") else datetime.now(tz).date()
        d2 = date.fromisoformat(str(a["to"]).strip()) if a.get("to") else d1 + timedelta(days=6)
    except ValueError:
        raise _core.ToolError("дата — в виде ГГГГ-ММ-ДД, например 2026-11-20") from None
    if d2 < d1:
        raise _core.ToolError("to раньше from")
    if (d2 - d1).days >= MAX_DAYS:
        raise _core.ToolError(f"период не больше {MAX_DAYS} дней")
    return d1, d2


def _ics(cfg: dict) -> str:
    _, raw, _ = _req(cfg, "GET", cfg["url"], headers={"Accept": "text/calendar"})
    text = raw.decode("utf-8", "replace")
    if "BEGIN:VCALENDAR" not in text[:2000].upper():
        raise _core.ToolError(f"календарь «{cfg['name']}»: по ссылке не iCalendar — проверьте ссылку")
    return text


def list_calendars(a: dict):
    rows = []
    for n in calendars():
        try:
            _, cfg = _cal(n)
        except _core.ToolError as e:
            rows.append({"calendar": n, "error": str(e)})
            continue
        host = urllib.parse.urlsplit(cfg["url"]).hostname
        row = {"calendar": n, "kind": cfg["kind"], "host": host,
               "write": "через черновик и «Да»" if cfg["kind"] == "caldav" else "нет (ссылка iCal — только чтение)"}
        if cfg["google"]:
            row["google"] = "данные Google: только моделям без обучения на данных (Limited Use)"
        if cfg["kind"] == "caldav":
            row["user"] = cfg["user"]
            try:
                row["collections"] = [{"name": c["name"], "href": c["href"]} for c in _collections(cfg)]
            except _core.ToolError as e:
                row["error"] = str(e)
        rows.append(row)
    if not rows:
        _cal(None)                                     # понятная ошибка «нет файла календаря»
    return {"calendars": rows}


def _sources(a: dict) -> list[str]:
    return [a["calendar"]] if a.get("calendar") else calendars() or [None]


def list_events(a: dict):
    limit = max(1, min(int(a.get("limit", 50)), 100))
    names = _sources(a)
    _, first = _cal(names[0])
    tz = _tz(a, first if len(names) == 1 else None)
    d1, d2 = _period(a, tz)
    start = datetime.combine(d1, datetime.min.time(), tz)
    end = datetime.combine(d2 + timedelta(days=1), datetime.min.time(), tz)
    rows, skipped = [], []
    for n in names:
        name, cfg = _cal(n)
        if cfg["google"] and (why := google_block_reason()):
            if a.get("calendar"):
                raise _core.ToolError(f"календарь «{name}»: {why}")
            skipped.append({"calendar": name, "why": why})
            continue
        if cfg["kind"] == "ics":
            for e in events_in(parse_ics(_ics(cfg)), start, end, tz):
                rows.append({"calendar": name, "id": e["uid"], **e})
            continue
        cols = _pick(_collections(cfg), a.get("collection"))
        for col in cols:
            for href, data in _report(cfg, col, start, end):
                for e in events_in(parse_ics(data), start, end, tz):
                    rows.append({"calendar": name, "collection": col["name"], "id": href, **e})
    keep = ("calendar", "id", "summary", "start", "recurrence")
    unexp = [{k: r[k] for k in keep} for r in rows if r.get("unexpanded")]
    rows = [r for r in rows if not r.get("unexpanded")]
    rows.sort(key=lambda e: (e["_sort"], e["summary"]))
    total = len(rows)
    rows = [{k: v for k, v in r.items() if k != "_sort" and v not in ("", None)} for r in rows[:limit]]
    out = {"period": {"from": d1.isoformat(), "to": d2.isoformat(), "tz": _tzname(tz)}, "total": total,
           "events": rows}
    if total > limit:
        out["more"] = f"показаны первые {limit} из {total}; сузьте период (from, to) или увеличьте limit (до 100)"
    if unexp:
        out["recurring_unexpanded"] = unexp
        out["recurring_note"] = ("у этих событий сложное правило повтора — попадают ли они в период, коннектор не "
                                 "знает; проверьте в приложении календаря")
    if skipped:
        out["skipped"] = skipped
    return out


def get_event(a: dict):
    name, cfg = _cal(a.get("calendar"))
    _check_google(cfg)
    tz = _tz(a, cfg)
    eid = str(a.get("id") or "").strip()
    if not eid:
        raise _core.ToolError("id — из calendar_list_events")
    if cfg["kind"] == "ics":
        evs = [e for e in parse_ics(_ics(cfg)) if _first(e, "UID")[1] == eid]
        href = None
    else:
        if not eid.startswith("/") or ".." in eid or "?" in eid or "#" in eid:
            raise _core.ToolError("id события CalDAV — путь из calendar_list_events")
        col = next((c for c in _collections(cfg) if eid.startswith(c["href"])), None)
        if not col:
            raise _core.ToolError("событие не из календарей этого аккаунта")
        _, raw, _ = _req(cfg, "GET", urllib.parse.urljoin(col["url"], eid), headers={"Accept": "text/calendar"})
        evs, href = parse_ics(raw.decode("utf-8", "replace")), eid
    if not evs:
        raise _core.ToolError(f"нет события «{eid}» в календаре «{name}»")
    master = next((e for e in evs if not e.get("RECURRENCE-ID")), evs[0])
    p, v = _first(master, "DTSTART")
    s0, _ = _dt(p, v, tz)
    wide_start = _as_dt(s0, tz) - timedelta(days=1)
    now = datetime.now(tz)
    ahead = max(now, wide_start) + timedelta(days=MAX_DAYS)
    occ = events_in(evs, wide_start, ahead, tz, full=True)
    first = occ[0] if occ else {"summary": _text(_first(master, "SUMMARY")[1]), "start": _fmt(s0, tz)}
    out = {"calendar": name, "id": href or eid, **{k: v for k, v in first.items() if k not in ("_sort", "occurrence")}}
    if master.get("RRULE"):
        nxt = [e["start"] for e in occ if e["_sort"] >= now.astimezone(UTC).isoformat()][:5]
        out["next"] = nxt
    for k in ("ORGANIZER", "URL"):
        if master.get(k):
            out[k.lower()] = re.sub(r"^mailto:", "", _first(master, k)[1], flags=re.I)
    att = [re.sub(r"^mailto:", "", v, flags=re.I) for _, v in master.get("ATTENDEE", [])]
    if att:
        out["attendees"] = att[:30]
    return out


# ---------- запись: черновик → «Да» человека → apply ----------
def _when(v, tz: tzinfo, what: str) -> date | datetime:
    s = str(v or "").strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return date.fromisoformat(s)
        d = datetime.fromisoformat(s)
    except ValueError:
        raise _core.ToolError(f"{what} — ГГГГ-ММ-ДД (весь день) или ГГГГ-ММ-ДДTЧЧ:ММ, например 2026-11-20T10:00") \
            from None
    return d if d.tzinfo else d.replace(tzinfo=tz)


def propose_event(a: dict):
    name, cfg = _cal(a.get("calendar"))
    if cfg["kind"] != "caldav":
        raise _core.ToolError(f"календарь «{name}» — ссылка iCal, только чтение; записывать можно в CalDAV")
    tz = _tz(a, cfg)
    title = " ".join(str(a.get("summary") or "").split())
    if not title:
        raise _core.ToolError("укажите название: summary")
    if len(title) > 300:
        raise _core.ToolError("название длиннее 300 знаков")
    start = _when(a.get("start"), tz, "start")
    if a.get("end"):
        end = _when(a["end"], tz, "end")
    elif isinstance(start, datetime):
        end = start + timedelta(minutes=max(5, min(int(a.get("duration_minutes") or 60), 24 * 60)))
    else:
        end = start
    if isinstance(start, datetime) != isinstance(end, datetime):
        raise _core.ToolError("start и end — оба с временем или оба датами (весь день)")
    if end < start or (isinstance(start, datetime) and end == start):
        raise _core.ToolError("end раньше start")
    desc = str(a.get("description") or "").strip()
    if len(desc) > 5000:
        raise _core.ToolError("описание длиннее 5000 знаков")
    col = _pick(_collections(cfg), a.get("collection"))
    if len(col) != 1:
        raise _core.ToolError(f"укажите collection: {', '.join(c['name'] for c in col)}")
    col = col[0]
    uid = f"{secrets.token_hex(12)}@gas-pult"
    allday = not isinstance(start, datetime)
    p = {"calendar": name, "collection": col["name"], "href": col["href"].rstrip("/") + f"/{uid}.ics",
         "url": col["url"].split("?")[0].rstrip("/") + f"/{uid}.ics", "uid": uid,
         "summary": title, "location": " ".join(str(a.get("location") or "").split()), "description": desc,
         "all_day": allday}
    if allday:
        p["start"], p["end"] = start.isoformat(), end.isoformat()
        when = start.strftime("%d.%m.%Y") + ("" if end == start else f"–{end.strftime('%d.%m.%Y')}") + ", весь день"
    else:
        p["start"], p["end"] = _utc(start), _utc(end)
        ls, le = start.astimezone(tz), end.astimezone(tz)
        tail = le.strftime("%H:%M" if ls.date() == le.date() else "%d.%m.%Y %H:%M")
        when = f"{ls.strftime('%d.%m.%Y %H:%M')}–{tail} ({_tzname(tz)})"
    summary = f"СОЗДАТЬ событие «{title}» в календаре «{name}/{col['name']}»: {when}" + \
              (f"; место: {p['location']}" if p["location"] else "") + \
              (f"; описание ({len(desc)} зн.): {desc[:200]}{'…' if len(desc) > 200 else ''}" if desc else "")
    return _core.propose(SVC, "create", p, summary)


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\n").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Строки iCalendar — не длиннее 75 байт (RFC 5545 §3.1), перенос — CRLF и пробел."""
    out, cur = [], b""
    for ch in line:
        b = ch.encode()
        if len(cur) + len(b) > (75 if not out else 74):
            out.append(cur.decode())
            cur = b""
        cur += b
    out.append(cur.decode())
    return "\r\n ".join(out)


def build_ics(p: dict) -> str:
    if p["all_day"]:
        s = date.fromisoformat(p["start"])
        e = date.fromisoformat(p["end"]) + timedelta(days=1)
        times = [f"DTSTART;VALUE=DATE:{s:%Y%m%d}", f"DTEND;VALUE=DATE:{e:%Y%m%d}"]
    else:
        times = [f"DTSTART:{p['start']}", f"DTEND:{p['end']}"]
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//gas-pult//calendar connector//RU", "CALSCALE:GREGORIAN",
             "BEGIN:VEVENT", f"UID:{p['uid']}", f"DTSTAMP:{_utc(datetime.now(UTC))}", *times,
             f"SUMMARY:{_esc(p['summary'])}"]
    if p.get("location"):
        lines.append(f"LOCATION:{_esc(p['location'])}")
    if p.get("description"):
        lines.append(f"DESCRIPTION:{_esc(p['description'])}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"


def apply(a: dict):
    rec = _core.take_confirmed(SVC, str(a.get("id", "")))
    p = rec["params"]
    if rec["action"] != "create":
        raise _core.ToolError("неизвестное действие черновика")
    _, cfg = _cal(p["calendar"])
    url = p.get("url") or urllib.parse.urljoin(cfg["url"], p["href"])
    if not _same_site(url, cfg["url"]) or urllib.parse.urlsplit(url).path != p["href"]:
        raise _core.ToolError("адрес события не на сервере календаря")
    _req(cfg, "PUT", url, build_ics(p), {"Content-Type": "text/calendar; charset=utf-8", "If-None-Match": "*"},
         ok=(200, 201, 204))
    return {"done": rec["summary"], "id": p["href"], "uid": p["uid"]}


# ---------- MCP ----------
_CAL = {"calendar": {"type": "string", "description": "календарь (имя из calendar_list_calendars); один — можно "
                                                      "не указывать"}}
_COL = {"collection": {"type": "string", "description": "календарь внутри аккаунта CalDAV (name из "
                                                         "calendar_list_calendars); не указан — все"}}
_TZ = {"tz": {"type": "string", "description": "часовой пояс ответа, например Europe/Moscow"}}
_GOOGLE = (" Данные календарей Google — только моделям, которые на них не учатся (Google API Limited Use): "
           "не :free, не DeepSeek напрямую, не NVIDIA trial.")

SERVER = {
    "name": "gas-pult-calendar",
    "instructions": "Календари (CalDAV: Яндекс, Nextcloud, iCloud; ссылка iCal: Google) — чтение событий за период. "
                    "Новое событие — только черновиком в пульте и после «Да» человека; изменение и удаление — нет."
                    + _GOOGLE,
    "keys": lambda: _secrets(),
    "tools": [
        {"name": "calendar_list_calendars",
         "description": "Подключённые календари: вид (caldav / ics), сервер, календари внутри аккаунта CalDAV. "
                        "Пароли и секретные ссылки не показывает. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {}}, "fn": list_calendars},
        {"name": "calendar_list_events",
         "description": "События за период по всем календарям (или одному): начало, конец, название, место, повтор. "
                        "По умолчанию — сегодня и 6 дней вперёд. Повторы (RRULE) развёрнуты. Ничего не меняет."
                        + _GOOGLE,
         "inputSchema": {"type": "object", "properties": {
             **_CAL, **_COL, **_TZ, "from": {"type": "string", "description": "с даты ГГГГ-ММ-ДД (включительно)"},
             "to": {"type": "string", "description": "по дату ГГГГ-ММ-ДД (включительно)"},
             "limit": {"type": "integer", "default": 50, "maximum": 100}}},
         "fn": list_events},
        {"name": "calendar_get_event",
         "description": "Одно событие по id из calendar_list_events: полное описание, участники, правило повтора и "
                        "ближайшие 5 повторов. Ничего не меняет." + _GOOGLE,
         "inputSchema": {"type": "object", "properties": {**_CAL, **_TZ, "id": {"type": "string"}},
                         "required": ["id"]},
         "fn": get_event},
        {"name": "calendar_propose_event",
         "description": "Черновик НОВОГО события в календаре CalDAV. Сам ничего не пишет: показать владельцу, после "
                        "его «Да» в пульте — calendar_apply. Изменить или удалить событие нельзя.",
         "inputSchema": {"type": "object", "properties": {
             **_CAL, **_COL, **_TZ, "summary": {"type": "string", "description": "название"},
             "start": {"type": "string", "description": "ГГГГ-ММ-ДДTЧЧ:ММ или ГГГГ-ММ-ДД (весь день)"},
             "end": {"type": "string", "description": "конец, так же; для дня — последний день включительно"},
             "duration_minutes": {"type": "integer", "default": 60, "description": "если нет end"},
             "location": {"type": "string"}, "description": {"type": "string"}},
             "required": ["summary", "start"]},
         "fn": propose_event},
        {"name": "calendar_apply",
         "description": "Создать событие по черновику, подтверждённому человеком. Без подтверждения — ошибка.",
         "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
         "fn": apply}],
}

if __name__ == "__main__":
    sys.exit(_core.main(SERVER, SVC))
