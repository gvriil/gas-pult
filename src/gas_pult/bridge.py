"""Мост к браузеру пользователя (решение владельца 16.11, продукт «пульт управляет браузером пользователя»).

На компьютере пользователя (Mac, Windows) работает лёгкий мост ``bridge/gas-pult-bridge.mjs``: он сам подключается к
пульту исходящим защищённым соединением (WebSocket ``/api/bridge/ws``) и локально запускает Playwright MCP в режиме
``--extension`` — управление уже открытым Chrome/Edge пользователя, где он вошёл в свои сервисы. Агенты в окнах
пульта видят этот браузер как MCP-сервер ``gas-pult bridge-mcp`` («browser-local») — с телефона и с компьютера.

- Пара: владелец в панели получает одноразовый код (10 мин) → мост меняет его на токен устройства (в файле — только
  хэш, 0600). Устройства — список в настройках, любое можно отозвать.
- Токен моста — в подпротоколе WebSocket (``gpb-<токен>``): своих заголовков WebSocket не умеет.
- ``/api/bridge/rpc`` — только локальным процессам пульта: секрет из файла 0600 (снаружи запросы тоже приходят с
  127.0.0.1 через Caddy, поэтому адрес — не проверка).
- Фокус-ссылка с разрешением «Браузер» (владелец 17.11): код пары выпускается для ссылки — устройство помечено её
  id (``focus``). Его видит только агент окна этой ссылки; агенты остальных окон — только устройства владельца.
  Ссылка отозвана, истекла, сессия завершена — устройство не работает (проверка при подключении и каждом вызове).
- Журнал по устройству — ``bridge_log.jsonl`` (0600, 30 дней): время, инструмент, адрес, итог; без содержимого страниц.
- Заметки, Напоминания, Календарь Мака (GAS-15) — чтение мостом сразу; запись (``APPLE_WRITE``) — только черновиком:
  первый вызов возвращает черновик, человек нажимает «Да» в панели (``approvals.py``: «Да» — только в памяти
  службы панели, команды подтверждения нет), второй вызов с ``draft`` уходит на мост с отметкой ``_confirmed``.
- «Личные данные не уходят модели» (владелец 21.11, по умолчанию включено для новых устройств): ответы моста — без
  текста писем и введённого в поля, с маской почты, телефонов, карт; снимки экрана запрещены (``private_reply``).
- «Да» на сервере перед «Отправить / Оплатить / Удалить» в браузере и перед командой терминала из белого списка
  (``run_allowed``) — тот же черновик, что у записи на Маке (``Hub.plan``).
- Установщик одной командой — ``bridge_install.py``.
- Банки и госуслуги — запрет по умолчанию (``BLOCKED``), разрешает пользователь у себя в мосте; сервер тоже не
  пропускает переход на них, пока устройство не сообщило, что пользователь их разрешил.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from pathlib import Path

from gas_pult.connectors import _core

PAIR_TTL = 600
LOG_KEEP = 30 * 86400
RPC_TIMEOUT = 120.0
BLOCKED = ("gosuslugi.ru", "nalog.gov.ru", "nalog.ru", "pfr.gov.ru", "sfr.gov.ru", "mos.ru", "sberbank.ru",
           "sber.ru", "tbank.ru", "tinkoff.ru", "vtb.ru", "alfabank.ru", "raiffeisen.ru", "gazprombank.ru",
           "psbank.ru", "open.ru", "rshb.ru", "pochtabank.ru", "sovcombank.ru", "mkb.ru", "paypal.com",
           "revolut.com", "wise.com", "bunq.com", "n26.com")
_CODE = re.compile(r"^[A-Z0-9]{8}$")


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def blocked_host(url: str, allowed: list[str] | tuple = ()) -> str:
    """Домен из запретного списка (банк, госуслуги), если пользователь его не разрешил; иначе ""."""
    m = re.match(r"^[a-z][a-z0-9+.-]*://([^/:?#]+)", str(url or "").strip().lower())
    host = m.group(1) if m else ""
    for d in BLOCKED:
        if (host == d or host.endswith("." + d)) and d not in allowed:
            return d
    return ""


# ---------- запись на Маке: черновик → «Да» человека в пульте → выполнение (GAS-15) ----------
CONFIRM_SVC = "mac"                                    # папка подтверждений confirm/mac (как у коннекторов)
APPLE_WRITE = {"notes_create": "заметку", "reminders_create": "напоминание"}
_DUE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?$")


def _one(v, n: int, what: str, need: bool = False) -> str:
    s = " ".join(str(v or "").split())
    if need and not s:
        raise ValueError(f"укажите {what}")
    if len(s) > n:
        raise ValueError(f"{what} длиннее {n} знаков")
    return s


def write_draft(tool: str, args: dict) -> tuple[dict, str]:
    """Проверенные аргументы записи и строка для человека. Ошибка — ValueError с понятным текстом."""
    title = _one(args.get("title"), 200, "title (название)", need=True)
    if tool == "notes_create":
        body = str(args.get("body") or "").replace("\r\n", "\n").strip()
        if len(body) > 20000:
            raise ValueError("body длиннее 20000 знаков")
        folder = _one(args.get("folder"), 100, "folder")
        clean = {"title": title, "body": body, **({"folder": folder} if folder else {})}
        text = f"СОЗДАТЬ заметку «{title}» в папке «{folder or 'по умолчанию'}»" + \
               (f"; текст ({len(body)} зн.): {body[:200]}{'…' if len(body) > 200 else ''}" if body else "")
        return clean, text
    lst, due = _one(args.get("list"), 100, "list"), str(args.get("due") or "").strip()
    if due and not _DUE.match(due):
        raise ValueError("due — ГГГГ-ММ-ДД или ГГГГ-ММ-ДДTЧЧ:ММ (время Мака)")
    notes = str(args.get("notes") or "").strip()
    if len(notes) > 5000:
        raise ValueError("notes длиннее 5000 знаков")
    clean = {"title": title, **({"list": lst} if lst else {}), **({"due": due} if due else {}),
             **({"notes": notes} if notes else {})}
    text = f"СОЗДАТЬ напоминание «{title}» в списке «{lst or 'по умолчанию'}»" + \
           (f", срок {due.replace('T', ' ')}" if due else "") + (f"; заметка: {notes[:200]}" if notes else "")
    return clean, text


# ---------- «Личные данные не уходят модели» (владелец 21.11): на сервере, в ответах моста ----------
# Включено — агент видит структуру страницы (кнопки, ссылки, заголовки, подписи полей), а не текст писем, абзацев,
# ячеек и не то, что введено в поля. Почта, телефоны, номера карт маскируются в любом тексте ответа. Снимки экрана и
# инструменты, которые читают страницу в обход снимка (код на странице, сетевые запросы), — запрещены.
PRIVATE_DENY = re.compile(r"screenshot|evaluate|run_code|network_request|pdf_save")
_STRUCT = {"button", "link", "heading", "tab", "menuitem", "menuitemcheckbox", "menuitemradio", "checkbox", "radio",
           "switch", "option", "columnheader", "rowheader", "img", "dialog", "alertdialog", "navigation", "region",
           "form", "tabpanel", "toolbar", "menu", "menubar", "tablist", "search", "banner", "main", "contentinfo",
           "complementary", "figure", "group", "list", "table", "grid", "tree", "treeitem", "progressbar", "slider",
           "separator", "/url", "/placeholder"}
_INPUT = {"textbox", "searchbox", "combobox", "spinbutton"}
_ARIA = re.compile(r'^(?P<ind>\s*)- (?P<role>/?[\w-]+)(?P<name> "(?:[^"\\]|\\.)*")?(?P<attrs>(?: \[[^\]]*\])*)'
                   r'(?P<colon>:)?(?P<val>.*)$')
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_CARD = re.compile(r"(?<![\w/=])(?:\d[ -]?){12,18}\d(?![\w])")
_PHONE = re.compile(r"(?<![\w/=.:-])\+?\(?\d[\d ().-]{7,18}\d(?![\w])")
HIDDEN, TEXT_HIDDEN = '"[скрыто]"', '"[текст]"'


def _luhn(digits: str) -> bool:
    s = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch) * (2 if i % 2 else 1)
        s += d - 9 if d > 9 else d
    return s % 10 == 0


def mask_pii(text: str) -> str:
    """Почта → [почта], номер карты (13–19 цифр, проверка Луна) → [карта], телефон (10–15 цифр) → [телефон]."""
    def card(m):
        d = re.sub(r"\D", "", m.group(0))
        return "[карта]" if 13 <= len(d) <= 19 and _luhn(d) else m.group(0)

    def phone(m):
        s = m.group(0)
        if re.match(r"^\d{4}-\d{2}-\d{2}", s) or re.match(r"^\d{1,2}[./]\d{1,2}[./]\d{2,4}", s):
            return s                                         # дата, а не телефон
        return "[телефон]" if 10 <= len(re.sub(r"\D", "", s)) <= 15 else s
    return _PHONE.sub(phone, _EMAIL.sub("[почта]", _CARD.sub(card, str(text))))


def _short(name: str, n: int = 80) -> str:
    inner = mask_pii(name[2:-1] if name.startswith(' "') else name)
    return ' "' + (inner[:n] + "…" if len(inner) > n else inner) + '"'


def _aria_line(line: str) -> str:
    m = _ARIA.match(line)
    if not m:
        return mask_pii(line)
    role, name, val = m.group("role"), m.group("name") or "", m.group("val") or ""
    if role in _STRUCT:                                      # структура: названия кнопок, ссылок, заголовков
        name = _short(name) if name else ""
        val = (" " + mask_pii(val.strip())[:300]) if role in ("/url", "/placeholder") and val.strip() else \
              (" " + TEXT_HIDDEN if val.strip() else "")
    elif role in _INPUT:                                     # поле: подпись — да, введённое — нет
        name = _short(name) if name else ""
        val = " " + HIDDEN if val.strip() else ""
    else:                                                    # абзацы, текст, ячейки, письма — без содержимого
        name = " " + TEXT_HIDDEN if name else ""
        val = " " + TEXT_HIDDEN if val.strip() else ""
    return f"{m.group('ind')}- {role}{name}{m.group('attrs') or ''}{m.group('colon') or ''}{val}"


def strip_snapshot(text: str) -> str:
    """Снимок страницы Playwright MCP (YAML в ```yaml … ```): только структура; остальной текст — с маской."""
    out, inside = [], False
    for line in str(text).split("\n"):
        if line.strip().startswith("```"):
            inside = line.strip().startswith("```yaml") if not inside else False
            out.append(line)
            continue
        out.append(_aria_line(line) if inside else mask_pii(line))
    return "\n".join(out)


def private_reply(out: dict) -> dict:
    """Ответ моста в режиме «личные данные не уходят модели»: текст — без содержимого и с маской, картинок нет."""
    if not isinstance(out, dict):
        return out
    if isinstance(out.get("error"), dict):
        out = {**out, "error": {**out["error"], "message": mask_pii(out["error"].get("message", ""))}}
    res = out.get("result")
    if isinstance(res, dict) and isinstance(res.get("content"), list):
        items = []
        for c in res["content"]:
            if isinstance(c, dict) and c.get("type") == "text":
                items.append({**c, "text": strip_snapshot(c.get("text", ""))})
            else:
                items.append({"type": "text", "text": "[картинка или файл скрыты: личные данные не уходят модели]"})
        out = {**out, "result": {**res, "content": items}}
    return out


# ---------- «Да» на сервере перед «Отправить / Оплатить / Удалить» в браузере (владелец 21.11) ----------
RISKY = re.compile(r"(?<!\w)(отправ|оплат|удал|купи|покупк|подтверд|заказ|оформ|перевест|перевод|опубликов|подпис|"
                   r"send|pay|delete|remove|buy|purchase|submit|confirm|order|checkout|transfer|publish|"
                   r"post\b|sign\b)", re.I)
_REF = re.compile(r"^(?:f\d+)?e\d+$")
_SNAP_REF = re.compile(r'^\s*- (?P<role>[\w-]+)(?: "(?P<name>(?:[^"\\]|\\.)*)")?.*?\[ref=(?P<ref>\w+)\]')
_SEARCH = re.compile(r"поиск|найти|search|find", re.I)
CODE_TOOLS = ("browser_evaluate", "browser_run_code", "browser_run_code_unsafe")
GATED = {"browser_click", "browser_type", "browser_press_key", "browser_file_upload", "browser_drop",
         "browser_handle_dialog", *CODE_TOOLS}
GATED_NOTE = (" Кнопки и действия, после которых что-то уходит, оплачивается или удаляется («Отправить», «Оплатить», "
              "«Удалить», «Купить», Enter в форме, код на странице), — только после «Да» человека: первый вызов вернёт "
              "черновик; после подтверждения вызовите снова с draft.")


class NeedSnapshot(LookupError):
    """Элемента нет в последнем снимке страницы: агенту — сначала browser_snapshot."""


# ---------- терминал на компьютере: белый список, каждая команда — после «Да» (владелец 21.11) ----------
RUN_TOOL = "run_allowed"
RUN_LIST = {                                              # команда → что разрешено (та же проверка — на мосту)
    "ls": "ls [-l|-a|-la|-lh] [папка в доме]",
    "df": "df -h",
    "du": "du -sh <папка в доме>",
    "open": "open <файл или папка в доме> (документы, картинки, музыка, видео; не программы)",
    "ping": "ping -c 3 <адрес сайта>",
    "brew": "brew list",
    "sw_vers": "sw_vers (версия macOS)",
    "uptime": "uptime",
}
DOC_EXT = {"pdf", "txt", "rtf", "md", "csv", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "pages",
           "numbers", "key", "jpg", "jpeg", "png", "gif", "heic", "webp", "bmp", "tif", "tiff", "mp3", "m4a", "wav",
           "aac", "flac", "mp4", "mov", "m4v", "avi", "mkv", "epub"}
_BAD = re.compile(r"[;|&$`<>(){}\[\]*?!\\\"'\n\r\t#%^=]")
_HOME_PATH = re.compile(r"^(~(/[^/]+)*/?|[^/~-][^/]*(/[^/]+)*/?)$")
_HOST = re.compile(r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?)*$")


def _home_path(p: str, what: str) -> str:
    if not _HOME_PATH.match(p or "") or ".." in p.split("/"):
        raise ValueError(f"{what}: только путь внутри домашней папки, например ~/Documents")
    return p


def check_command(cmd: str) -> list[str]:
    """Строка команды → список аргументов из белого списка; иначе ValueError. Ни оболочки, ни конвейеров, ни
    подстановок: такие знаки отклоняются сразу; пути — только внутри домашней папки, без «..»."""
    s = str(cmd or "").strip()
    if not s or len(s) > 300:
        raise ValueError("пустая или слишком длинная команда")
    if _BAD.search(s) or ".." in s:
        raise ValueError("нельзя: ; | & $( ) ` < > кавычки, звёздочки и «..» — только простая команда из списка")
    prog, *args = s.split()
    if prog not in RUN_LIST:
        raise ValueError(f"команды «{prog}» нет в белом списке: " + "; ".join(RUN_LIST.values()))
    if prog == "ls":
        flags = [a for a in args if a.startswith("-")]
        rest = [a for a in args if not a.startswith("-")]
        if len(flags) > 1 or (flags and flags[0] not in ("-l", "-a", "-la", "-al", "-lh")) or len(rest) > 1:
            raise ValueError("ls: можно -l, -a, -la, -lh и одну папку")
        return ["ls", *flags, *([_home_path(rest[0], "ls")] if rest else [])]
    if prog == "df":
        if args != ["-h"]:
            raise ValueError("df: только df -h")
        return ["df", "-h"]
    if prog == "du":
        if len(args) != 2 or args[0] != "-sh":
            raise ValueError("du: только du -sh <папка в доме>")
        return ["du", "-sh", _home_path(args[1], "du")]
    if prog == "open":
        if len(args) != 1:
            raise ValueError("open: один файл или папка в доме")
        p = _home_path(args[0], "open")
        last = p.rstrip("/").rsplit("/", 1)[-1]
        ext = last.rsplit(".", 1)[1].lower() if "." in last.lstrip(".") else ""
        if ext and ext not in DOC_EXT:
            raise ValueError(f"open: файлы .{ext} не открываю — только документы, картинки, музыку, видео и папки")
        return ["open", p]
    if prog == "ping":
        if len(args) != 3 or args[:2] != ["-c", "3"] or not _HOST.match(args[2].lower()):
            raise ValueError("ping: только ping -c 3 <адрес сайта>, например ping -c 3 ya.ru")
        return ["ping", "-c", "3", args[2].lower()]
    if prog == "brew":
        if args != ["list"]:
            raise ValueError("brew: только brew list")
        return ["brew", "list"]
    if args:
        raise ValueError(f"{prog}: без аргументов")
    return [prog]


DRAFT_TTL = 86400


def drafts(confirmed=None) -> list[dict]:
    """Черновики, которые ждут «Да» человека (панель → «Компьютеры»): свежее сутки, новые — сверху.
    ``confirmed(id)`` — «Да» уже нажато (в памяти службы панели, approvals.py)."""
    d, now, out = _core._dir(CONFIRM_SVC), time.time(), []
    for f in sorted(d.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:50]:
        if now - f.stat().st_mtime > DRAFT_TTL:
            continue
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"id": rec.get("id"), "summary": rec.get("summary", ""), "created": int(f.stat().st_mtime),
                    "tool": rec.get("action", ""), "device": (rec.get("params") or {}).get("device", ""),
                    "confirmed": bool(confirmed and confirmed(str(rec.get("id"))))})
    return out


def reject(pid: str) -> None:
    """«Нет» человека: черновик убирается, выполнить его уже нельзя."""
    _core._load(CONFIRM_SVC, pid)                      # неверный id или нет черновика — ToolError
    d = _core._dir(CONFIRM_SVC)
    (d / f"{pid}.json").rename(d / f"{pid}.no")


class Devices:
    """Устройства с мостом и одноразовые коды пары. Файл ``bridge_devices.json`` (0600): id, имя, ОС, хэш токена."""

    def __init__(self, path: Path, clock=time.time):
        self.path, self.clock, self.lock = Path(path), clock, threading.Lock()
        self.codes: dict[str, tuple[float, str]] = {}      # код → (срок, id фокус-ссылки или "")

    def _load(self) -> list[dict]:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return [x for x in d if isinstance(x, dict) and x.get("id")] if isinstance(d, list) else []
        except (OSError, ValueError):
            return []

    def _save(self, items: list[dict]):
        from gas_pult.config import write_private
        write_private(self.path, json.dumps(items, ensure_ascii=False))

    def pair_code(self, focus: str = "") -> dict:
        """Одноразовый код пары; ``focus`` — id фокус-ссылки: устройство будет только её."""
        now = self.clock()
        with self.lock:
            self.codes = {c: v for c, v in self.codes.items() if v[0] > now}
            code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
            self.codes[code] = (now + PAIR_TTL, str(focus or ""))
        return {"code": code, "expires": int(now + PAIR_TTL)}

    def peek(self, code: str) -> bool:
        """Код действует (не тратит его): установщик с панели проверяет код до скачивания Node."""
        code = str(code or "").strip().upper()
        with self.lock:
            return bool(_CODE.match(code)) and self.codes.get(code, (0, ""))[0] >= self.clock()

    def claim(self, code: str, name: str, os_name: str, old: str = "") -> dict:
        """Код → токен устройства. ``old`` — прежний токен этого же компьютера (повторная установка): прежняя запись
        заменяется новой, а не копится. Новое устройство — с «Личные данные не уходят модели» (владелец 21.11)."""
        code = str(code or "").strip().upper()
        now = self.clock()
        with self.lock:
            exp, focus = self.codes.pop(code, (0, "")) if _CODE.match(code) else (0, "")
            if exp < now:
                raise PermissionError("код неверный или устарел — получите новый в панели")
            token = secrets.token_urlsafe(32)
            dev = {"id": secrets.token_hex(4), "name": " ".join(str(name or "компьютер").split())[:60],
                   "os": str(os_name or "")[:20], "token": _h(token), "created": now, "seen": now, "private": True,
                   **({"focus": focus} if focus else {})}
            items = self._load()
            if old:
                h = _h(str(old))
                items = [d for d in items if not secrets.compare_digest(d.get("token", ""), h)
                         or d.get("focus", "") != focus]
            items.append(dev)
            self._save(items)
        return {"id": dev["id"], "token": token, **({"focus": focus} if focus else {})}

    def check(self, token: str) -> dict | None:
        if not token:
            return None
        h = _h(token)
        return next((d for d in self._load() if secrets.compare_digest(d.get("token", ""), h)), None)

    def seen(self, did: str):
        with self.lock:
            items = self._load()
            for d in items:
                if d["id"] == did:
                    d["seen"] = self.clock()
            self._save(items)

    def listing(self) -> list[dict]:
        return [{**{k: d.get(k) for k in ("id", "name", "os", "created", "seen", "focus")},
                 "private": bool(d.get("private"))} for d in self._load()]

    def private(self, did: str) -> bool:
        return bool((self.get(did) or {}).get("private"))

    def set_private(self, did: str, on: bool) -> bool:
        with self.lock:
            items = self._load()
            hit = [d for d in items if d["id"] == did]
            for d in hit:
                d["private"] = bool(on)
            if hit:
                self._save(items)
        return bool(hit)

    def get(self, did: str) -> dict | None:
        return next((d for d in self._load() if d["id"] == did), None)

    def revoke(self, did: str) -> bool:
        with self.lock:
            items = self._load()
            keep = [d for d in items if d["id"] != did]
            if len(keep) == len(items):
                return False
            self._save(keep)
        return True


class Hub:
    """Подключённые мосты и их ответы: запрос агента (JSON-RPC) → мост → ответ, с подменой id (несколько агентов)."""

    def __init__(self, log: Path | None = None, clock=time.time):
        self.approve = None                       # «Да» человека: служба панели ставит approvals.take (approvals.py)
        self.lock, self.log, self.clock = threading.Lock(), Path(log) if log else None, clock
        self.conns: dict[str, dict] = {}              # id устройства → {"ws", "allowed": [домены]}
        self.wait: dict[str, tuple[threading.Event, list]] = {}
        self.pages: dict[str, dict] = {}              # id устройства → адрес, заголовок, элементы последнего снимка
        self.private = lambda did: False              # «Личные данные не уходят модели»: Panel даёт Devices.private

    def attach(self, did: str, ws) -> None:
        with self.lock:
            old = self.conns.get(did)
            self.conns[did] = {"ws": ws, "allowed": []}
        if old:
            try:
                old["ws"].close(4000, "заменено новым подключением")
            except Exception:
                pass

    def detach(self, did: str, ws) -> None:
        with self.lock:
            if self.conns.get(did, {}).get("ws") is ws:
                del self.conns[did]

    def online(self) -> list[str]:
        with self.lock:
            return list(self.conns)

    def on_message(self, did: str, text: str) -> None:
        """Сообщение от моста: ответ на запрос (по нашему id) или служебное (``{"allowed": [...]}``)."""
        try:
            m = json.loads(text)
        except ValueError:
            return
        if isinstance(m, dict) and "bridge" in m:     # мост сообщает настройки пользователя
            with self.lock:
                if did in self.conns:
                    self.conns[did]["allowed"] = [str(x) for x in (m["bridge"].get("allowed") or [])][:50]
            return
        rid = str(m.get("id")) if isinstance(m, dict) else ""
        with self.lock:
            w = self.wait.get(rid)
        if w:
            w[1].append(m)
            w[0].set()

    def journal(self, did: str, msg: dict, out: dict | None):
        """Строка журнала устройства: время, метод, инструмент, адрес перехода, итог. Без содержимого страниц."""
        if not self.log or msg.get("method") != "tools/call":
            return
        p = msg.get("params") or {}
        url = str((p.get("arguments") or {}).get("url") or "")[:300]
        err = (out or {}).get("error") or ((out or {}).get("result") or {}).get("isError")
        row = {"t": int(self.clock()), "dev": did, "tool": str(p.get("name") or "")[:60],
               **({"url": url} if url else {}), "ok": not err}
        if isinstance(err, dict):
            row["err"] = str(err.get("message", ""))[:160]
        from gas_pult.config import write_private
        with self.lock:
            try:
                rows = self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []
            except OSError:
                rows = []
            keep = [r for r in rows if r and json.loads(r).get("t", 0) > self.clock() - LOG_KEEP]
            write_private(self.log, "\n".join([*keep, json.dumps(row, ensure_ascii=False)]) + "\n")

    def history(self, did: str, n: int = 50) -> list[dict]:
        try:
            rows = [json.loads(r) for r in self.log.read_text(encoding="utf-8").splitlines() if r] if self.log else []
        except (OSError, ValueError):
            rows = []
        return [r for r in rows if r.get("dev") == did][-n:][::-1]

    # ---------- что на странице: адрес, заголовок, элементы последнего снимка (для «Да» перед кнопками) ----------
    def remember(self, did: str, out: dict | None) -> None:
        res = (out or {}).get("result") if isinstance(out, dict) else None
        if not isinstance(res, dict):
            return
        text = "\n".join(c.get("text", "") for c in res.get("content") or []
                         if isinstance(c, dict) and c.get("type") == "text")
        if not text:
            return
        with self.lock:
            pg = self.pages.setdefault(did, {"url": "", "title": "", "refs": {}, "typed": None})
            if m := re.search(r"Page URL: (\S+)", text):
                pg["url"] = m.group(1)[:300]
            if m := re.search(r"Page Title: ?(.*)", text):
                pg["title"] = m.group(1).strip()[:120]
            if "```yaml" in text:
                for line in text.split("\n"):
                    if m := _SNAP_REF.match(line):
                        pg["refs"][m.group("ref")] = (m.group("role"), m.group("name") or "")
                if len(pg["refs"]) > 20000:
                    pg["refs"] = dict(list(pg["refs"].items())[-10000:])

    def _target(self, did: str, a: dict) -> tuple[str | None, str]:
        """Элемент из аргументов агента → (роль, название) по последнему снимку. Селектор — (None, "")."""
        t = str(a.get("target") or a.get("ref") or "").strip()
        if not _REF.match(t):
            return None, ""
        with self.lock:
            got = (self.pages.get(did) or {}).get("refs", {}).get(t)
        if not got:
            raise NeedSnapshot(f"элемента {t} нет в последнем снимке страницы — сначала вызовите browser_snapshot")
        return got

    def risky(self, did: str, tool: str, a: dict) -> str | None:
        """Действие, после которого что-то уходит, оплачивается или удаляется, — текст для человека; иначе None."""
        pg = self.pages.get(did) or {}
        where = f" — страница «{pg.get('title') or '—'}» {pg.get('url') or ''}".rstrip()
        desc = str(a.get("element") or "")[:120]
        if tool in CODE_TOOLS:
            return f"ВЫПОЛНИТЬ КОД на странице{where}: {str(a.get('function') or a.get('code') or '')[:300]}"
        if "mouse_click" in tool or "mouse_down" in tool:
            return f"НАЖАТЬ мышью в точку {a.get('x')}, {a.get('y')}{where}"
        if tool in ("browser_file_upload", "browser_drop") and (a.get("paths") or a.get("data")):
            files = ", ".join(str(x) for x in (a.get("paths") or []))[:300]
            return f"ЗАГРУЗИТЬ НА САЙТ {('файлы ' + files) if files else 'данные'}{where}"
        if tool == "browser_handle_dialog" and a.get("accept"):
            return f"НАЖАТЬ «ОК» в окне сайта{where}"
        if tool == "browser_click":
            role, name = self._target(did, a)
            if role is None:
                return f"НАЖАТЬ «{desc or a.get('target')}» (элемент по селектору){where}"
            if RISKY.search(name) or RISKY.search(desc):
                return f"НАЖАТЬ «{name or desc}» ({role}){where}"
            return None
        searchy = lambda r, n: r in ("searchbox", "combobox") or bool(_SEARCH.search(n))   # noqa: E731
        if tool == "browser_type":
            role, name = self._target(did, a)
            with self.lock:
                self.pages.setdefault(did, {"url": "", "title": "", "refs": {}, "typed": None})["typed"] = \
                    (role or "", name or desc)
            if a.get("submit") and not searchy(role or "", f"{name} {desc}"):
                return f"ВВЕСТИ текст и нажать Enter (отправить форму) в поле «{name or desc}»{where}"
            return None
        if tool == "browser_press_key" and "enter" in str(a.get("key") or "").lower():
            typed = pg.get("typed")
            if "+" in str(a.get("key")) or not (typed and searchy(*typed)):
                return f"НАЖАТЬ клавишу {a.get('key')} (может отправить форму){where}"
        return None

    def plan(self, did: str, tool: str, args: dict) -> tuple[dict, str] | None:
        """Нужен ли черновик: (аргументы, текст для человека) или None — выполнить сразу. Ошибка — ValueError."""
        if tool in APPLE_WRITE:
            return write_draft(tool, args)
        if tool == RUN_TOOL:
            argv = check_command(args.get("command"))
            return {"argv": argv}, "ВЫПОЛНИТЬ на компьютере команду: " + " ".join(argv)
        text = self.risky(did, tool, args)
        return (args, text) if text else None

    def _gate(self, did: str, msg: dict) -> tuple[dict | None, dict]:
        """«Да» на сервере: без ``draft`` — черновик (мост не вызывается); с ``draft`` — только подтверждённый человеком
        черновик этого инструмента и этого устройства, аргументы — из черновика, не от агента. Запись на Маке и
        терминал получают отметку ``_confirmed`` — мост без неё их не выполняет."""
        p = msg.get("params") or {}
        tool, args = str(p.get("name")), dict(p.get("arguments") or {})

        def fail(text: str) -> tuple[dict, dict]:
            return {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32012, "message": text}}, msg

        if "_confirmed" in args:
            return fail("отметку _confirmed ставит только пульт после «Да» человека")
        draft = str(args.pop("draft", "") or "").strip()
        if not draft:
            try:
                got = self.plan(did, tool, args)
            except (ValueError, LookupError) as e:     # LookupError — NeedSnapshot: сначала browser_snapshot
                return fail(str(e))
            if got is None:
                return None, {**msg, "params": {**p, "arguments": args}}
            clean, text = got
            if self.private(did):                      # заголовок страницы может нести почту или телефон
                text = mask_pii(text)
            d = _core.propose(CONFIRM_SVC, tool, {"device": did, "args": clean}, text)
            return {"jsonrpc": "2.0", "id": msg.get("id"), "result": {"content": [{"type": "text", "text": (
                f"Черновик {d['id']}: {text}. На компьютере ничего не сделано. Покажите это человеку дословно. Если "
                f"он скажет «Да» — он нажимает «Да» в панели Гаврилы («Ждут вашего «Да»»); команды подтверждения "
                f"нет — сами не подтверждайте. "
                f"Затем вызовите {tool} с draft=\"{d['id']}\". Без его «Да» действие не выполнится.")}]}}, msg
        try:
            rec = _core.take_confirmed(CONFIRM_SVC, draft, need_flag=False, approve=self.approve)
        except _core.ToolError as e:
            return fail(str(e))
        if rec.get("action") != tool or (rec.get("params") or {}).get("device") != did:
            return fail("черновик для другого действия или другого компьютера — сделайте новый")
        args = {**rec["params"]["args"], **({"_confirmed": draft} if tool in APPLE_WRITE or tool == RUN_TOOL else {})}
        return None, {**msg, "params": {**p, "arguments": args}}

    @staticmethod
    def _tools_list(out: dict, private: bool) -> dict:
        """Ответ на tools/list: у «опасных» инструментов — поле ``draft`` и пояснение; в режиме «личные данные» —
        без снимков экрана и чтения страницы в обход снимка."""
        res = (out or {}).get("result")
        if not isinstance(res, dict) or not isinstance(res.get("tools"), list):
            return out
        tools = []
        for t in res["tools"]:
            name = str((t or {}).get("name") or "")
            if private and PRIVATE_DENY.search(name):
                continue
            if name in GATED or "mouse_click" in name or "mouse_down" in name:
                sch = dict(t.get("inputSchema") or {"type": "object"})
                sch["properties"] = {**(sch.get("properties") or {}), "draft": {
                    "type": "string", "description": "id черновика — только после «Да» человека"}}
                t = {**t, "inputSchema": sch, "description": str(t.get("description") or "") + GATED_NOTE}
            tools.append(t)
        return {**out, "result": {**res, "tools": tools}}

    def call(self, msg: dict, did: str = "", timeout: float = RPC_TIMEOUT, allowed: set | None = None) -> dict | None:
        """JSON-RPC от агента → мост; запрос — ждём ответ, уведомление — None. ``allowed`` — устройства, доступные
        этому агенту (None — любые); ``did`` не из них — как будто не подключено."""
        with self.lock:
            ok = [d for d in self.conns if allowed is None or d in allowed]
            did = did if did in ok else ("" if did else next(iter(ok), ""))
            c = self.conns.get(did)
        if not c:
            self.journal(did or "-", msg, {"error": {"message": "не подключён"}})
            if "id" in msg:
                return {"jsonrpc": "2.0", "id": msg["id"], "error": {
                    "code": -32000, "message": "браузер пользователя не подключён: запустите мост на компьютере "
                                               "(панель → Настройки → Компьютеры)"}}
            return None
        p = msg.get("params") or {}
        tool = str(p.get("name") or "") if msg.get("method") == "tools/call" else ""
        private = self.private(did)
        if tool.endswith("navigate") and (d := blocked_host((p.get("arguments") or {}).get("url", ""), c["allowed"])):
            self.journal(did, msg, {"error": {"message": f"запрещён сайт {d}"}})
            return {"jsonrpc": "2.0", "id": msg.get("id"), "error": {
                "code": -32001, "message": f"сайт {d} (банк или госуслуги) выключен: включить его может только "
                                           f"пользователь в мосте на своём компьютере, прочитав правила сервиса"}}
        if tool and private and PRIVATE_DENY.search(tool):
            out = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32015, "message": (
                f"{tool} выключен: на этом компьютере включено «Личные данные не уходят модели» — снимки экрана и "
                f"чтение страницы в обход снимка запрещены. Пользуйтесь browser_snapshot (кнопки, ссылки, заголовки). "
                f"Выключить может владелец компьютера: панель → «Компьютеры» → компьютер.")}}
            self.journal(did, msg, out)
            return out
        if tool in APPLE_WRITE or tool == RUN_TOOL or tool in GATED or "mouse_click" in tool or "mouse_down" in tool:
            out, msg = self._gate(did, msg)
            if out is not None:
                self.journal(did, msg, out)
                return out
        if "id" not in msg:
            c["ws"].send_text(json.dumps(msg, ensure_ascii=False))
            return None
        rid = "gp-" + secrets.token_hex(6)
        ev, box = threading.Event(), []
        with self.lock:
            self.wait[rid] = (ev, box)
        try:
            c["ws"].send_text(json.dumps({**msg, "id": rid}, ensure_ascii=False))
            if not ev.wait(timeout):
                out = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32002, "message": "мост не ответил"}}
            else:
                out = {**box[0], "id": msg["id"]}
            self.journal(did, msg, out)
            if tool:
                self.remember(did, out)
            if msg.get("method") == "tools/list":
                out = self._tools_list(out, private)
            elif private:
                out = private_reply(out)
            return out
        finally:
            with self.lock:
                self.wait.pop(rid, None)
