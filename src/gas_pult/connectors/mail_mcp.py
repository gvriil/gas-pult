"""Почта для пульта (IMAP/SMTP): папки, письма, поиск — чтение; черновик и отправка — только после «Да» человека.

Ящики — по файлу на ящик ``~/.config/gastech-mcp/mail-<ящик>.json`` (0600), каталог меняется ``GAS_MAIL_KEY_DIR``:
``{"host": "imap.yandex.ru", "user": "box@yandex.ru", "app_password": "<пароль приложения>"}``; необязательно —
``imap_port`` (993), ``smtp_host`` (по ``host``), ``smtp_port`` (465), ``tls`` (true; false — только для 127.0.0.1).
Яндекс, Gmail, Yahoo, Mail.ru — пароли приложений. Контракт — docs/CONNECTORS.md, описание — docs/connectors/mail.md.

Чтение не меняет ящик: папка открывается EXAMINE (только чтение), письма — BODY.PEEK (не становятся прочитанными).
Запись: ``mail_propose_draft`` / ``mail_propose_send`` — черновик в пульте; ``mail_apply`` — после подтверждения
человека и при ``GAS_MAIL_WRITE=1``: черновик кладётся в папку «Черновики» ящика (IMAP APPEND) или письмо уходит
по SMTP. Удаление, перемещение, пометки, пересылка с вложениями, массовые рассылки — не реализованы.
"""

from __future__ import annotations

import base64
import email
import email.policy
import email.utils
import html
import imaplib
import json
import os
import re
import socket
import ssl
import sys
import time
from contextlib import contextmanager
from datetime import date
from email.message import EmailMessage
from pathlib import Path

if __package__:
    from . import _core
else:                                                  # запуск файлом: python3 mail_mcp.py
    import _core

SVC = "mail"
TIMEOUT = 25
# Имя для EHLO — без socket.getfqdn(): smtplib по умолчанию спрашивает DNS, на macOS это бывает дольше минуты
# (гипотеза по падениям CI macOS 20.11: test_mail_mcp — TimeoutExpired на отправке; проверка — CI main на macOS).
EHLO = socket.gethostname() or "localhost"
MAX_FETCH = 3_000_000                                  # больше — письмо читается не целиком (вложения)
MAX_RCPT = 10                                          # не рассылка: до 10 адресатов на письмо
MAX_BODY = 20_000
_BOX = re.compile(r"^[a-z0-9_-]{1,32}$")
_UID = re.compile(r"^\d{1,10}$")
_ADDR = re.compile(r"^[^@\s<>,;\"]+@[^@\s<>,;\"]+\.[^@\s<>,;\"]+$")
_LOCAL = {"127.0.0.1", "localhost", "::1"}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# Адреса серверов, если в файле только ``host`` (IMAP): SMTP того же почтового сервиса.
_SMTP = {"imap.yandex.ru": "smtp.yandex.ru", "imap.yandex.com": "smtp.yandex.com", "imap.gmail.com": "smtp.gmail.com",
         "imap.mail.yahoo.com": "smtp.mail.yahoo.com", "imap.mail.ru": "smtp.mail.ru"}
ROLES = {"\\inbox": "входящие", "\\sent": "отправленные", "\\drafts": "черновики", "\\junk": "спам",
         "\\trash": "корзина", "\\archive": "архив", "\\all": "вся почта", "\\flagged": "помеченные",
         "\\templates": "шаблоны"}                     # \Templates — не RFC 6154, отдаёт Яндекс (проверено 17.11)
_DRAFT_NAMES = ("Drafts", "Черновики", "[Gmail]/Drafts", "[Gmail]/Черновики", "Draft")


# ---------- ящики и пароли ----------
def _key_dir() -> Path:
    return Path(os.environ.get("GAS_MAIL_KEY_DIR") or _core.SECRETS_DIR).expanduser()


def boxes() -> list[str]:
    return sorted(p.name[5:-5] for p in _key_dir().glob("mail-*.json") if _BOX.match(p.name[5:-5]))


def _box(name: str | None) -> tuple[str, dict]:
    """Настройки ящика. Без имени — единственный ящик; ящиков несколько — просим указать."""
    have = boxes()
    if not name:
        if len(have) == 1:
            name = have[0]
        elif not have:
            raise _core.ToolError(f"нет файла ящика mail-<ящик>.json — положите его в {_key_dir()} (права 0600), "
                                  "см. docs/connectors/mail.md")
        else:
            raise _core.ToolError(f"ящиков несколько — укажите box: {', '.join(have)}")
    name = str(name).strip().lower()
    if not _BOX.match(name):
        raise _core.ToolError("неверное имя ящика (латиница, цифры, - и _)")
    p = _key_dir() / f"mail-{name}.json"
    try:
        raw = p.read_text(encoding="utf-8").strip()
    except OSError:
        raise _core.ToolError(f"нет ящика «{name}» (файла {p.name}); есть: {', '.join(have) or 'ни одного'}") from None
    try:
        cfg = json.loads(raw)
    except ValueError:
        cfg = None
    if not (isinstance(cfg, dict) and cfg.get("user") and cfg.get("app_password")
            and (cfg.get("host") or cfg.get("imap_host"))):
        raise _core.ToolError(f"файл {p.name}: нужен JSON с host, user, app_password")
    cfg["imap_host"] = str(cfg.get("imap_host") or cfg["host"])
    cfg["smtp_host"] = str(cfg.get("smtp_host") or _SMTP.get(cfg["imap_host"])
                           or re.sub(r"^imap\.", "smtp.", cfg["imap_host"]))
    cfg["tls"] = cfg.get("tls", True) is not False
    if not cfg["tls"] and (cfg["imap_host"] not in _LOCAL or cfg["smtp_host"] not in _LOCAL):
        raise _core.ToolError(f"файл {p.name}: без шифрования (tls: false) — только для проверки на 127.0.0.1")
    return name, cfg


def _secrets(cfg: dict | None = None) -> list[str]:
    """Что прятать в ответах: пароли приложений (и файлы ящиков целиком). Адреса и серверы не прячем."""
    out = [str(cfg.get("app_password", ""))] if cfg else []
    for p in _key_dir().glob("mail-*.json"):
        try:
            raw = p.read_text(encoding="utf-8").strip()
            out += [raw, str(json.loads(raw).get("app_password", ""))]
        except (OSError, ValueError, AttributeError):
            continue
    return [s for s in out if s]


def _err(e: BaseException, cfg: dict) -> str:
    text = e.args[0] if isinstance(e, imaplib.IMAP4.error) and e.args else e
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    return _core.hide(str(text)[:300], *_secrets(cfg))


# ---------- IMAP ----------
def utf7_encode(s: str) -> str:
    """Имя папки → «модифицированный UTF-7» IMAP (RFC 3501 §5.1.3): «Обращения» → «&BB4EMQRABDAESQQ1BD0EOARP-»."""
    out, buf = [], []

    def flush():
        if buf:
            b = base64.b64encode("".join(buf).encode("utf-16-be")).decode().rstrip("=").replace("/", ",")
            out.append(f"&{b}-")
            buf.clear()

    for ch in s:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)


def utf7_decode(s: str) -> str:
    def dec(m: re.Match) -> str:
        b = m.group(1)
        if not b:
            return "&"
        b = b.replace(",", "/")
        return base64.b64decode(b + "=" * (-len(b) % 4)).decode("utf-16-be", "replace")

    return re.sub(r"&([A-Za-z0-9+,]*)-", dec, s)


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


@contextmanager
def _imap(box: str | None):
    name, cfg = _box(box)
    host, port = cfg["imap_host"], int(cfg.get("imap_port") or 993)
    try:
        if cfg["tls"]:
            m = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=TIMEOUT)
        else:
            m = imaplib.IMAP4(host, port, timeout=TIMEOUT)
    except (OSError, imaplib.IMAP4.error) as e:
        raise _core.ToolError(f"почтовый сервер {host} недоступен: {_err(e, cfg)}") from None
    try:
        try:
            m.login(cfg["user"], cfg["app_password"])
        except imaplib.IMAP4.error as e:
            raise _core.ToolError(f"ящик «{name}»: вход не удался — проверьте пароль приложения и что IMAP включён "
                                  f"в настройках почты ({_err(e, cfg)})") from None
        yield m, name, cfg
    except (imaplib.IMAP4.error, OSError) as e:
        raise _core.ToolError(f"ящик «{name}»: сервер ответил ошибкой: {_err(e, cfg)}") from None
    finally:
        try:
            m.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def _ok(typ: str, data, what: str):
    if typ != "OK":
        detail = b" ".join(x for x in data if isinstance(x, bytes)).decode("utf-8", "replace")[:200]
        raise _core.ToolError(f"{what}: {detail or typ}")
    return data


def _folders(m) -> list[dict]:
    data = _ok(*m.list('""', "*"), "не удалось получить список папок")
    out = []
    for item in data:
        if item is None:
            continue
        if isinstance(item, tuple):                    # имя пришло литералом
            head, name = item[0].decode("utf-8", "replace"), item[1].decode("utf-8", "replace")
        else:
            head, name = item.decode("utf-8", "replace"), None
        mt = re.match(r'\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s*(?P<name>.*)$', head)
        if not mt:
            continue
        raw = name if name is not None else mt["name"].strip()
        if raw.startswith('"') and raw.endswith('"'):
            raw = re.sub(r"\\(.)", r"\1", raw[1:-1])
        flags = mt["flags"].lower().split()
        if "\\noselect" in flags or "\\nonexistent" in flags:
            continue
        role = next((ROLES[f] for f in flags if f in ROLES), "входящие" if raw.upper() == "INBOX" else "")
        out.append({"name": utf7_decode(raw), "role": role, "_raw": raw})
    return out


def _examine(m, folder: str) -> int:
    typ, data = m.select(_q(utf7_encode(folder or "INBOX")), readonly=True)
    if typ != "OK":
        raise _core.ToolError(f"нет папки «{folder}» — список папок: mail_list_folders")
    try:
        return int(data[0] or 0)
    except (ValueError, TypeError, IndexError):
        return 0


def _fetch(m, uids: list[str], items: str) -> list[dict]:
    """UID FETCH → [{uid, flags, size, data}] (данные — байты письма или заголовков)."""
    data = _ok(*m.uid("FETCH", ",".join(uids), items), "не удалось прочитать письма")
    out, cur = [], None
    for item in data:
        meta = item[0] if isinstance(item, tuple) else item
        meta = meta.decode("utf-8", "replace") if isinstance(meta, bytes) else ""
        if isinstance(item, tuple):
            cur = {"uid": None, "flags": [], "size": None, "data": item[1]}
            out.append(cur)
        if cur is None:
            continue
        if (u := re.search(r"\bUID (\d+)", meta)) and not cur["uid"]:
            cur["uid"] = u.group(1)
        if f := re.search(r"\bFLAGS \(([^)]*)\)", meta):
            cur["flags"] = f.group(1).split()
        if s := re.search(r"\bRFC822\.SIZE (\d+)", meta):
            cur["size"] = int(s.group(1))
    return [x for x in out if x["uid"]]


def _imap_date(s: str) -> str:
    try:
        d = date.fromisoformat(str(s).strip())
    except ValueError:
        raise _core.ToolError("дата — в виде ГГГГ-ММ-ДД, например 2026-11-01") from None
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year}"


def _iso(value) -> str:
    try:
        return email.utils.parsedate_to_datetime(str(value)).isoformat()
    except (TypeError, ValueError, IndexError):
        return str(value or "")


def _hdr(msg, name: str) -> str:
    try:
        return " ".join(str(msg.get(name, "") or "").split())
    except (ValueError, TypeError, IndexError):
        return ""


def _limit(a: dict) -> int:
    return max(1, min(int(a.get("limit", 20)), 100))


def _text_of(msg) -> tuple[str, str]:
    """Текст письма: text/plain, иначе HTML без тегов."""
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return "", ""
    try:
        text = part.get_content()
    except (LookupError, ValueError, AssertionError):
        text = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
    if part.get_content_subtype() == "html":
        text = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", text)
        text = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", text)
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip(), part.get_content_subtype()


# ---------- инструменты: чтение ----------
def list_boxes(a: dict):
    rows = []
    for b in boxes():
        try:
            _, cfg = _box(b)
            rows.append({"box": b, "user": cfg["user"], "imap": cfg["imap_host"], "smtp": cfg["smtp_host"]})
        except _core.ToolError as e:
            rows.append({"box": b, "error": str(e)})
    if not rows:
        _box(None)                                     # понятная ошибка «нет файла ящика»
    return {"boxes": rows}


def list_folders(a: dict):
    with _imap(a.get("box")) as (m, name, _):
        return {"box": name, "folders": [{k: v for k, v in f.items() if k != "_raw"} for f in _folders(m)]}


def list_messages(a: dict):
    limit = _limit(a)
    crit, lit = [], None
    if a.get("unseen"):
        crit.append("UNSEEN")
    if a.get("since"):
        crit += ["SINCE", _imap_date(a["since"])]
    for key, arg in (("FROM", "from"), ("SUBJECT", "subject"), ("TEXT", "text")):
        val = " ".join(str(a.get(arg) or "").split())
        if not val:
            continue
        if val.isascii():
            crit += [key, _q(val)]
        elif lit is None:
            lit = (key, val)
        else:
            raise _core.ToolError("не латиницей — только один фильтр из from / subject / text за раз")
    folder = str(a.get("folder") or "INBOX")
    with _imap(a.get("box")) as (m, name, _):
        _examine(m, folder)
        if lit:                                        # кириллица — литералом в UTF-8, последним условием
            found = set()
            # Яндекс ищет буквально: «счёт» не находит «счет» (проверено 17.11) — ищем оба написания
            for val in dict.fromkeys((lit[1], lit[1].replace("ё", "е").replace("Ё", "Е"))):
                m.literal = val.encode()
                typ, data = m.uid("SEARCH", "CHARSET", "UTF-8", *crit, lit[0])
                found.update((_ok(typ, data, "поиск не удался")[0] or b"").split())
            found = sorted(found, key=int)
        else:
            typ, data = m.uid("SEARCH", *(crit or ["ALL"]))
            found = (_ok(typ, data, "поиск не удался")[0] or b"").split()
        uids = [u.decode() for u in found][-limit:]
        rows = []
        if uids:
            got = _fetch(m, uids,
                         "(UID FLAGS RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID)])")
            for r in got:
                msg = email.message_from_bytes(r["data"] or b"", policy=email.policy.default)
                rows.append({"uid": r["uid"], "date": _iso(msg.get("Date")), "from": _hdr(msg, "From"),
                             "to": _hdr(msg, "To"), "subject": _hdr(msg, "Subject"),
                             "seen": "\\Seen" in r["flags"], "size": r["size"],
                             # для брифинга (GAS-18): копия, Message-ID (ссылка на письмо), «отвечено»
                             "cc": _hdr(msg, "Cc"), "message_id": _hdr(msg, "Message-ID"),
                             "answered": "\\Answered" in r["flags"]})
        rows.sort(key=lambda r: int(r["uid"]), reverse=True)
    out = {"box": name, "folder": folder, "total": len(found), "rows": rows}
    if len(found) > len(rows):
        out["more"] = f"показаны последние {len(rows)} из {len(found)}; сузьте фильтр (since, from, subject)"
    return out


def get_message(a: dict):
    uid = str(a.get("uid", "")).strip()
    if not _UID.match(uid):
        raise _core.ToolError("uid — число из mail_list_messages")
    folder = str(a.get("folder") or "INBOX")
    max_chars = max(200, min(int(a.get("max_chars", 4000)), 20000))
    with _imap(a.get("box")) as (m, name, _):
        _examine(m, folder)
        got = _fetch(m, [uid], f"(UID FLAGS RFC822.SIZE BODY.PEEK[]<0.{MAX_FETCH}>)")
        r = next((x for x in got if x["uid"] == uid), None)
        if r is None:
            raise _core.ToolError(f"письма uid {uid} нет в папке «{folder}»")
    msg = email.message_from_bytes(r["data"] or b"", policy=email.policy.default)
    text, kind = _text_of(msg)
    atts = []
    for part in msg.iter_attachments():
        payload = part.get_payload(decode=True) or b""
        atts.append({"name": part.get_filename() or "", "type": part.get_content_type(), "bytes": len(payload)})
    out = {"box": name, "folder": folder, "uid": uid, "date": _iso(msg.get("Date")), "from": _hdr(msg, "From"),
           "to": _hdr(msg, "To"), "cc": _hdr(msg, "Cc"), "subject": _hdr(msg, "Subject"),
           "message_id": _hdr(msg, "Message-ID"), "seen": "\\Seen" in r["flags"], "text": text[:max_chars],
           "text_from": kind, "attachments": atts}
    if len(text) > max_chars:
        out["text_cut"] = f"показано {max_chars} из {len(text)} знаков; больше — max_chars (до 20000)"
    if (r["size"] or 0) > MAX_FETCH:
        out["note"] = f"письмо больше {MAX_FETCH // 1_000_000} МБ — прочитано начало, список вложений неполный"
    return out


# ---------- запись: черновик → «Да» человека → apply ----------
def _addrs(v) -> list[str]:
    items = v if isinstance(v, list) else re.split(r"[,;]", str(v or ""))
    out = [str(x).strip() for x in items if str(x).strip()]
    if not out:
        raise _core.ToolError("укажите адресата: to")
    if len(out) > MAX_RCPT:
        raise _core.ToolError(f"не больше {MAX_RCPT} адресатов — это не рассылка")
    bad = [x for x in out if not _ADDR.match(email.utils.parseaddr(x)[1] or "-") or "\n" in x or "\r" in x]
    if bad:
        raise _core.ToolError(f"неверный адрес: {', '.join(bad)}")
    return out


def _letter(a: dict, action: str) -> dict:
    name, cfg = _box(a.get("box"))
    subject = " ".join(str(a.get("subject") or "").split())
    text = str(a.get("body") or "").strip()
    if not text:
        raise _core.ToolError("пустой текст письма: body")
    if len(text) > MAX_BODY:
        raise _core.ToolError(f"текст длиннее {MAX_BODY} знаков")
    p = {"box": name, "from": cfg["user"], "to": _addrs(a.get("to")), "subject": subject, "body": text}
    if a.get("reply_to_uid"):                          # ответ в ту же цепочку: читаем заголовки исходного письма
        orig = get_message({"box": name, "folder": a.get("folder") or "INBOX", "uid": a["reply_to_uid"],
                            "max_chars": 200})
        mid = orig["message_id"]
        if mid:
            p["in_reply_to"] = mid
            p["references"] = mid
        if not subject:
            p["subject"] = orig["subject"] if orig["subject"].lower().startswith("re:") else f"Re: {orig['subject']}"
    if not p["subject"]:
        raise _core.ToolError("укажите тему: subject")
    what = "положить черновик в «Черновики» ящика" if action == "draft" else "ОТПРАВИТЬ письмо"
    summary = (f"{what} «{name}»: кому {', '.join(p['to'])}; тема «{p['subject']}»; "
               f"текст ({len(text)} зн.): {text[:300]}{'…' if len(text) > 300 else ''}")
    return _core.propose(SVC, action, p, summary)


def propose_draft(a: dict):
    return _letter(a, "draft")


def propose_send(a: dict):
    return _letter(a, "send")


def _build(p: dict) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = p["from"], ", ".join(p["to"]), p["subject"]
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=p["from"].rsplit("@", 1)[-1])
    if p.get("in_reply_to"):
        msg["In-Reply-To"], msg["References"] = p["in_reply_to"], p["references"]
    msg.set_content(p["body"], cte="quoted-printable")      # 7 бит: проходит любой SMTP
    return msg


def _drafts_folder(m) -> str:
    fl = _folders(m)
    hit = next((f for f in fl if f["role"] == "черновики"), None) \
        or next((f for f in fl if f["name"] in _DRAFT_NAMES), None)
    if not hit:
        raise _core.ToolError("в ящике не нашлась папка «Черновики»")
    return hit["_raw"]


def apply(a: dict):
    rec = _core.take_confirmed(SVC, str(a.get("id", "")))
    p = rec["params"]
    msg = _build(p)
    if rec["action"] == "draft":
        with _imap(p["box"]) as (m, _, _cfg):
            folder = _drafts_folder(m)
            _ok(*m.append(_q(folder), "(\\Draft \\Seen)", imaplib.Time2Internaldate(time.time()),
                          msg.as_bytes(policy=email.policy.SMTP)), "черновик не сохранился")
        return {"done": rec["summary"], "folder": utf7_decode(folder)}
    if rec["action"] == "send":
        _send(p["box"], msg)
        return {"done": rec["summary"], "message_id": msg["Message-ID"],
                "note": "копию в «Отправленных» сервер кладёт сам (Яндекс, Gmail) — проверить в ящике"}
    raise _core.ToolError("неизвестное действие черновика")


def _send(box: str, msg: EmailMessage) -> None:
    import smtplib

    name, cfg = _box(box)
    host, port = cfg["smtp_host"], int(cfg.get("smtp_port") or 465)
    try:
        if cfg["tls"]:
            s = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT, context=ssl.create_default_context(), local_hostname=EHLO)
        else:
            s = smtplib.SMTP(host, port, timeout=TIMEOUT, local_hostname=EHLO)
        with s:
            s.login(cfg["user"], cfg["app_password"])
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise _core.ToolError(f"ящик «{name}»: SMTP не принял пароль приложения ({_err(e, cfg)})") from None
    except (smtplib.SMTPException, OSError) as e:
        raise _core.ToolError(f"ящик «{name}»: письмо не ушло: {_err(e, cfg)}") from None


# ---------- MCP ----------
_BOXP = {"box": {"type": "string", "description": "ящик (имя из mail_list_boxes); один ящик — можно не указывать"}}
_FOLDER = {"folder": {"type": "string", "default": "INBOX", "description": "папка, как в mail_list_folders"}}
_LETTER = {"type": "object", "properties": {
    **_BOXP, "to": {"type": "array", "items": {"type": "string"}, "description": f"адресаты, до {MAX_RCPT}"},
    "subject": {"type": "string", "description": "тема; при ответе можно не указывать — «Re: …»"},
    "body": {"type": "string", "description": "текст письма (обычный текст)"},
    "reply_to_uid": {"type": "string", "description": "uid письма, на которое отвечаем (та же цепочка)"},
    **_FOLDER}, "required": ["to", "body"]}

SERVER = {
    "name": f"gas-pult-{SVC}",
    "instructions": "Почта (IMAP/SMTP): папки, письма, поиск — только чтение, письма не становятся прочитанными. "
                    "Черновик и отправка — только черновиком в пульте и после «Да» человека.",
    "keys": lambda: _secrets(),
    "tools": [
        {"name": "mail_list_boxes", "description": "Подключённые ящики: имя, адрес, серверы. Пароли не показывает.",
         "inputSchema": {"type": "object", "properties": {}}, "fn": list_boxes},
        {"name": "mail_list_folders", "description": "Папки ящика и их роль (входящие, черновики, спам…). "
                                                     "Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {**_BOXP}}, "fn": list_folders},
        {"name": "mail_list_messages",
         "description": "Письма папки — новые сверху: uid, дата, от кого, тема, прочитано ли. Фильтры: непрочитанные, "
                        "с даты, от кого, тема, текст. Ничего не меняет и не отмечает прочитанным.",
         "inputSchema": {"type": "object", "properties": {
             **_BOXP, **_FOLDER, "limit": {"type": "integer", "default": 20, "maximum": 100},
             "unseen": {"type": "boolean", "description": "только непрочитанные"},
             "since": {"type": "string", "description": "с даты ГГГГ-ММ-ДД"},
             "from": {"type": "string"}, "subject": {"type": "string"}, "text": {"type": "string"}}},
         "fn": list_messages},
        {"name": "mail_get_message",
         "description": "Одно письмо по uid: заголовки, текст (HTML — без разметки), список вложений "
                        "(без содержимого). Не отмечает прочитанным.",
         "inputSchema": {"type": "object", "properties": {
             **_BOXP, **_FOLDER, "uid": {"type": "string"},
             "max_chars": {"type": "integer", "default": 4000, "maximum": 20000}}, "required": ["uid"]},
         "fn": get_message},
        {"name": "mail_propose_draft",
         "description": "Черновик письма для «Черновиков» ящика. Сам ничего не пишет: человек подтверждает в пульте, "
                        "затем mail_apply.", "inputSchema": _LETTER, "fn": propose_draft},
        {"name": "mail_propose_send",
         "description": "Письмо к отправке. Само НЕ отправляет: показать владельцу, после его «Да» в пульте — "
                        "mail_apply. Не рассылка: до 10 адресатов, без вложений.",
         "inputSchema": _LETTER, "fn": propose_send},
        {"name": "mail_apply", "description": "Выполнить черновик (положить в «Черновики» или отправить), "
                                              "подтверждённый человеком. Без подтверждения — ошибка.",
         "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
         "fn": apply}],
}

if __name__ == "__main__":
    sys.exit(_core.main(SERVER, SVC))
