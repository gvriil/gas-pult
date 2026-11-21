"""Утренний брифинг первого лица (GAS-18): один экран телефона — что выполнено, что нет и почему, что ждёт решения.

Решение владельца 18.11: брифинг в 07:30; источники первой версии — Gmail и Google Календарь; данные Google — только
моделям без обучения на данных (Google API Limited Use). Поэтому брифинг собирает **код, без модели**: письма и
события не уходят ни одной модели — только в Telegram владельцу и в его панель.

Блоки: «Выполнено» (слитые PR, закрытые задачи Linear и пульта), «Не выполнено — и почему» (красный CI, срок прошёл),
«Сегодня» (календарь), «Ваши решения» (пункты утренней сводки ``digest.py`` и письма без ответа). Каждая строка —
``{text, source: {kind, label, url?}}``; строка без источника не показывается.

Источники человек выбирает сам (экран выбора в панели, ``Prefs``); пока не выбрал — подключённое по умолчанию:
ящики Gmail, все календари, GitHub (если задан ``digest_github``), Linear (если есть ключ), пульт.

Правило тишины: вне утра бот будит только по деньгам, безопасности и срыву срока (``urgent``, ``notifylevel.wakes``);
остальное ждёт брифинга. Что срочного прислали ночью — строка вывода «Ночью срочного не было» или «Ночью — N срочных».
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

from gas_pult import digest

# id → подпись; «скоро» — видно на экране выбора, но не подключается
SOURCES = {"mail": "Почта", "calendar": "Календарь", "linear": "Задачи Linear", "github": "GitHub",
           "pult": "Пульт: окна, задачи, «Ждут «да»»", "apple": "Apple: почта и календарь iCloud"}
SOON = {"apple"}
MAX_ROWS = 6                                     # строк на блок: один экран телефона
MAIL_MAX = 5
URGENT_EVERY = 30 * 60                           # как часто вне утра проверять срочное
NIGHT_FROM = "22:00"
# автоматические письма (уведомления сервисов): ответа не ждут; в брифинг — только срочные, строкой «Проверить»
AUTO = re.compile(r"(?:^|[<\s\"])(?:no-?reply|do-?not-?reply|notifications?|notify|alerts?|admin|security|"
                  r"mailer-daemon|postmaster|bounces?|news(?:letter)?|digest|marketing|promo|info|support|billing|"
                  r"accounts?|robot|bot)[@+.-]|@(?:[\w-]+\.)*(?:notify|mg|updates|bounce|email|mailer|news)\.", re.I)
CATS = {
    "money": re.compile(r"сч[её]т\b|сч[её]та\b|оплат|платеж|платёж|долг|задолжен|штраф|возврат средств|invoice|"
                        r"payment|overdue|refund|chargeback|списан", re.I),
    "security": re.compile(r"безопасн|подозрит|взлом|парол|выполнен вход|вход в аккаунт|новый вход|код подтвержд|"
                           r"токен|ключ api|security|suspicious|sign-?in|password|breach|2fa|verification code|"
                           r"access token|api key", re.I),
    "deadline": re.compile(r"срок|дедлайн|просроч|последний день|сегодня до|deadline|due (?:today|date)|expires?",
                           re.I),
}
CAT_TITLES = {"money": "деньги", "security": "безопасность", "deadline": "срок"}
_GH_MERGED = ("query($q:String!){search(query:$q,type:ISSUE,first:30){nodes{... on PullRequest{number title url "
              "mergedAt repository{nameWithOwner}}}}}")


def urgent(text: str) -> str | None:
    """Категория срочного по тексту (тема письма, задача): money / security / deadline; иначе None."""
    return next((c for c, rx in CATS.items() if rx.search(text or "")), None)


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def row(text: str, source: dict | None, **extra) -> dict | None:
    """Строка брифинга; без источника (kind и label) — None: такую строку не показываем."""
    if not (text and source and source.get("kind") and source.get("label")):
        return None
    src = {k: v for k, v in source.items() if k in ("kind", "label", "url") and v}
    return {"text": text, "source": src, **{k: v for k, v in extra.items() if v not in (None, "")}}


def rows(items) -> list[dict]:
    return [x for x in items if x]


# ---------- выбор источников: у каждого свой ----------
# ---------- расписание: время, дни недели, часовой пояс — у каждого свои ----------
# Владелец 18.11: «руководитель сам выбирает время и периодичность; по умолчанию — 07:30». По умолчанию — рабочие дни.
DEFAULT_TIME = "07:30"
WORKDAYS = [0, 1, 2, 3, 4]                       # пн–пт (datetime.weekday)
EVERY = {"daily": list(range(7)), "workdays": WORKDAYS}
_HHMM = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _zone(name: str | None):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        return ZoneInfo(str(name)) if name else datetime.now().astimezone().tzinfo
    except (ZoneInfoNotFoundError, ValueError):
        return None


def schedule(rec: dict, default_time: str = DEFAULT_TIME) -> dict:
    """Расписание человека: {time, days, tz, every}; чего нет — 07:30 по рабочим дням в поясе сервера."""
    t = rec.get("time") if _HHMM.match(str(rec.get("time") or "")) else default_time or DEFAULT_TIME
    days = sorted({d for d in rec.get("days") or [] if isinstance(d, int) and 0 <= d <= 6}) or WORKDAYS
    tz = rec.get("tz") if rec.get("tz") and _zone(rec.get("tz")) else ""
    every = next((k for k, v in EVERY.items() if v == days), "custom")
    return {"time": t, "days": days, "tz": tz, "every": every}


def due(sched: dict, now: datetime, last: str) -> str:
    """Пора слать брифинг: вернёт местную дату человека (её запомнить), иначе "". ``now`` — с поясом или местное."""
    tz = _zone(sched.get("tz")) or datetime.now().astimezone().tzinfo
    local = (now if now.tzinfo else now.astimezone()).astimezone(tz)
    day = local.date().isoformat()
    if local.weekday() in sched["days"] and local.strftime("%H:%M") >= sched["time"] and last != day:
        return day
    return ""


class Prefs:
    """``brief_prefs.json`` (0600): uid → {sources, boxes, calendars, chosen, time, days, tz, sent, saved}."""

    def __init__(self, path: Path):
        self.path = path

    def _all(self) -> dict:
        try:
            d = json.loads(self.path.read_text())
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, uid) -> dict:
        rec = self._all().get(str(uid))
        return rec if isinstance(rec, dict) else {}

    def _put(self, uid, **fields) -> dict:
        d = self._all()
        rec = {**(d.get(str(uid)) if isinstance(d.get(str(uid)), dict) else {}), **fields, "saved": int(time.time())}
        d[str(uid)] = rec
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False))
        tmp.chmod(0o600)
        tmp.replace(self.path)
        return rec

    def set(self, uid, sources: list, boxes: list | None = None, calendars: list | None = None) -> dict:
        bad = [s for s in sources if s not in SOURCES]
        if bad:
            raise ValueError("неизвестный источник: " + ", ".join(map(str, bad)))
        return self._put(uid, sources=[s for s in SOURCES if s in sources and s not in SOON], chosen=True,
                         boxes=[str(b) for b in boxes or []], calendars=[str(c) for c in calendars or []])

    def set_schedule(self, uid, time_: str, every: str = "workdays", days: list | None = None,
                     tz: str = "") -> dict:
        """Время ЧЧ:ММ, периодичность (daily / workdays / custom + days 0–6, пн = 0) и пояс человека."""
        if not _HHMM.match(str(time_ or "")):
            raise ValueError("время — ЧЧ:ММ, например 07:30")
        if every in EVERY:
            days = EVERY[every]
        elif every == "custom":
            days = sorted({int(d) for d in days or [] if str(d).isdigit() and 0 <= int(d) <= 6})
            if not days:
                raise ValueError("выберите хотя бы один день недели")
        else:
            raise ValueError("периодичность: daily, workdays или custom")
        if tz and not _zone(tz):
            raise ValueError(f"неизвестный часовой пояс «{tz}»")
        return self._put(uid, time=time_, days=days, tz=tz or "")

    def mark_sent(self, uid, day: str):
        self._put(uid, sent=day)


def available(cfg) -> dict:
    """Что можно подключить на этом сервере: ящики, календари, есть ли ключ Linear и GitHub."""
    from gas_pult.connectors import _core, calendar_mcp, mail_mcp
    boxes = []
    for b in mail_mcp.boxes():
        try:
            host = mail_mcp._box(b)[1]["imap_host"]
        except Exception:                        # файл ящика испорчен — покажем, но без «Gmail»
            host = ""
        boxes.append({"id": b, "gmail": host == "imap.gmail.com"})
    try:                                        # «Подключения» → «Календари» (calkeys.py): что подключено, без значений
        from gas_pult import calkeys
        keys = calkeys.status()
    except Exception:
        keys = []
    return {"boxes": boxes, "calendars": calendar_mcp.calendars(), "calkeys": keys,
            "linear": (_core.SECRETS_DIR / "linear.token").is_file(), "github": bool(getattr(cfg, "digest_github", ""))}


def chosen(prefs: dict, avail: dict) -> dict:
    """Итоговый выбор: сохранённый или «по умолчанию» (ящики Gmail, все календари, GitHub, Linear, пульт)."""
    if prefs.get("chosen"):
        return {"sources": list(prefs.get("sources") or []), "boxes": list(prefs.get("boxes") or []),
                "calendars": list(prefs.get("calendars") or []), "chosen": True}
    src = {"mail", "calendar", "pult"} | {k for k in ("github", "linear") if avail.get(k)}
    return {"sources": [s for s in SOURCES if s in src], "chosen": False,
            "boxes": [b["id"] for b in avail.get("boxes", []) if b["gmail"]],
            "calendars": list(avail.get("calendars", []))}


# ---------- почта: письма без ответа ----------
def gmail_url(user: str, message_id: str) -> str:
    q = urllib.parse.quote("rfc822msgid:" + message_id.strip("<> "), safe="")
    return f"https://mail.google.com/mail/?authuser={urllib.parse.quote(user)}#search/{q}"


def _addr(v: str) -> str:
    m = re.search(r"[^\s<>\"',;]+@[^\s<>\"',;]+", v or "")
    return m.group(0).lower() if m else ""


def _name(v: str) -> str:
    n = re.sub(r"<[^>]*>", "", v or "").strip().strip('"')
    return n or _addr(v)


def _subj(s: str) -> str:
    return re.sub(r"^(?:\s*(?:re|fwd?|ответ|отв)\s*(?:\[\d+\])?\s*:\s*)+", "", s or "", flags=re.I).strip().lower()


def unanswered(inbox: list[dict], sent: list[dict], user: str) -> list[dict]:
    """Входящие владельцу без ответа: адресат — он сам, не рассылка, нет флага «отвечено» и ответа в «Отправленных»."""
    me = user.lower()
    replied = {_subj(m.get("subject", "")) for m in sent}
    out = []
    for m in inbox:
        frm = m.get("from", "")
        if _addr(frm) == me or me not in (m.get("to", "") + " " + m.get("cc", "")).lower():
            continue
        if m.get("answered") or _subj(m.get("subject", "")) in replied:
            continue
        out.append({**m, "auto": bool(AUTO.search(frm))})
    return out


def mail_items(boxes: list[str], since: str) -> tuple[list[dict], list[dict]]:
    """Решения «ответить на письмо» по ящикам и состояние источника (по ящику)."""
    from gas_pult.connectors import mail_mcp
    items, status = [], []
    for b in boxes:
        try:
            _, cfg = mail_mcp._box(b)
            inbox = mail_mcp.list_messages({"box": b, "since": since, "limit": 50})["rows"]
            sent = []
            folders = mail_mcp.list_folders({"box": b})["folders"]
            folder = next((f["name"] for f in folders if f.get("role") == "отправленные"), "")
            if folder:
                sent = mail_mcp.list_messages({"box": b, "since": since, "limit": 100, "folder": folder})["rows"]
        except Exception as e:                   # ящик недоступен — строка «не подключён», без падения брифинга
            status.append({"id": "mail:" + b, "label": "Почта · " + b, "state": "error", "note": str(e)[:200]})
            continue
        gmail = cfg["imap_host"] == "imap.gmail.com"
        status.append({"id": "mail:" + b, "label": ("Gmail · " if gmail else "Почта · ") + b, "state": "ok"})
        letters = [m for m in unanswered(inbox, sent, cfg["user"]) if not m["auto"] or urgent(m.get("subject", ""))]
        for m in letters[:MAIL_MAX]:
            mid = m.get("message_id") or m["uid"]
            items.append({"kind": "mail", "key": digest.key("mail", b, mid), "box": b, "uid": m["uid"],
                          "from": _name(m.get("from", "")), "subject": m.get("subject") or "(без темы)",
                          "date": m.get("date", ""), "gmail": gmail,
                          "url": gmail_url(cfg["user"], mid) if gmail and m.get("message_id") else "",
                          "cat": urgent(m.get("subject", "")), "auto": m["auto"]})
    return items, status


# ---------- календарь: сегодня ----------
def calendar_rows(names: list[str], day: str) -> tuple[list[dict], list[dict]]:
    from gas_pult.connectors import calendar_mcp
    out, status = [], []
    for n in names:
        try:
            got = calendar_mcp.list_events({"calendar": n, "from": day, "to": day, "limit": 30})
        except Exception as e:
            status.append({"id": "calendar:" + n, "label": "Календарь · " + n, "state": "error", "note": str(e)[:200]})
            continue
        status.append({"id": "calendar:" + n, "label": "Календарь · " + n, "state": "ok"})
        try:
            google = calendar_mcp._cal(n)[1]["google"]
        except Exception:
            google = False
        y, mth, d = day.split("-")
        for e in got.get("events", []):
            t = e.get("start", "")
            hm = t[11:16] if len(t) > 10 else ""
            end = e.get("end", "")[11:16] if len(e.get("end", "")) > 10 else ""
            when = f"{hm}–{end}" if hm and end else hm or "весь день"
            day_url = f"https://calendar.google.com/calendar/r/day/{y}/{int(mth)}/{int(d)}"
            url = e.get("url") or (day_url if google else "")
            out.append(row(f"{when} · {e.get('summary', '')}" + (f" · {e['location']}" if e.get("location") else ""),
                           {"kind": "calendar", "label": "Календарь · " + n, "url": url}, at=hm))
    return rows(out), status


# ---------- GitHub: слитые PR ----------
def merged(owner: str, since: str) -> list[dict]:
    r = subprocess.run(["gh", "api", "graphql", "-f", f"q=is:pr is:merged author:{owner} merged:>={since}",
                        "-f", f"query={_GH_MERGED}"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError((r.stderr.strip() or "gh не ответил")[:200])
    out = []
    for n in json.loads(r.stdout)["data"]["search"]["nodes"]:
        if n:
            repo = n["repository"]["nameWithOwner"]
            out.append(row(f"Слит PR {repo}#{n['number']} — {digest.cut(n['title'], 80)}",
                           {"kind": "github", "label": f"GitHub · {repo}#{n['number']}", "url": n["url"]}))
    return rows(out)


# ---------- Linear: закрыто и просрочено ----------
LINEAR_URL = "https://api.linear.app/graphql"


def linear(since: str, today: str, http=None) -> tuple[list[dict], list[dict]]:
    """(выполнено, не выполнено) — задачи на владельце: закрытые с ``since`` и со сроком раньше ``today``."""
    from gas_pult.connectors import _core
    token = (_core.SECRETS_DIR / "linear.token").read_text().strip()
    q = ('{done: viewer {assignedIssues(first: 20, filter: {completedAt: {gte: "SINCET00:00:00Z"}}) '
         '{nodes {identifier title url}}} late: viewer {assignedIssues(first: 20, filter: {dueDate: {lt: "TODAY"}, '
         'state: {type: {nin: ["completed", "canceled"]}}}) {nodes {identifier title url dueDate state {name}}}}}'
         ).replace("SINCE", since).replace("TODAY", today)
    http = http or _core.http
    got = http("POST", LINEAR_URL, headers={"Authorization": token}, body={"query": q}, keys=[token], service="Linear")
    data = (got if isinstance(got, dict) else {}).get("data") or {}
    nodes = lambda k: ((data.get(k) or {}).get("assignedIssues") or {}).get("nodes") or []   # noqa: E731
    done = [row(f"{n['identifier']} — {digest.cut(n['title'], 90)}",
                {"kind": "linear", "label": "Linear · " + n["identifier"], "url": n.get("url")}) for n in nodes("done")]
    late = [row(f"{n['identifier']} — {digest.cut(n['title'], 90)}",
                {"kind": "linear", "label": "Linear · " + n["identifier"], "url": n.get("url")},
                why=f"срок {n['dueDate']} прошёл, статус «{(n.get('state') or {}).get('name', '?')}»", cat="deadline")
            for n in nodes("late")]
    return rows(done), rows(late)


# ---------- задачи пульта ----------
def pult_tasks(items: list[dict], since_ts: float, today: str) -> tuple[list[dict], list[dict]]:
    from gas_pult import tasks
    src = lambda t: {"kind": "pult", "label": "Задачи пульта", "url": t.get("link")}   # noqa: E731
    done = [row(t["title"], src(t)) for t in items if t.get("status") == "done" and (t.get("done_at") or 0) >= since_ts]
    late = [row(t["title"], src(t), why=f"срок {t['due']} прошёл; дальше: {t.get('next') or '—'}", cat="deadline")
            for t in items if tasks.overdue(t, today)]
    return rows(done), rows(late)


# ---------- решения: пункты сводки и письма ----------
def decision(x: dict) -> dict | None:
    """Пункт сводки (digest) или письмо → строка «Ваши решения» с тем, что сделает «Да»."""
    k = x.get("key")
    if x["kind"] == "pr":
        red = x.get("ci") in ("FAILURE", "ERROR")
        why = "CI красный" if red else f"открыт {x['age']} дн."
        yes = "сольёт PR (после подтверждения)" if x.get("ok") else "откроет PR на GitHub"
        return row(f"PR {x['repo']}#{x['n']} — {digest.cut(x['title'], 70)} ({why})",
                   {"kind": "github", "label": f"GitHub · {x['repo']}#{x['n']}", "url": x.get("url")}, key=k, yes=yes,
                   act="confirm" if x.get("ok") else "open")
    if x["kind"] == "win":
        return row(f"Окно «{x['name']}» — Claude ждёт ответа", {"kind": "pult", "label": "Пульт · окно " + x["name"]},
                   key=k, yes="покажет экран окна", act="window", id=x.get("id"))
    if x["kind"] == "yes":
        return row(digest.cut(x["text"], 160), {"kind": "handoff", "label": f"HANDOFF.md · {x['project']}"}, key=k,
                   yes="передаст «да» в окно проекта (после подтверждения)", act="confirm")
    if x["kind"] == "mail":
        mark = f"[{CAT_TITLES[x['cat']]}] " if x.get("cat") else ""
        label = ("Gmail · " if x.get("gmail") else "Почта · ") + x["box"]
        what = f"Проверить: «{digest.cut(x['subject'], 80)}» — {x['from']}" if x.get("auto") else \
            f"Ответить {x['from']}: «{digest.cut(x['subject'], 80)}»"
        return row(mark + what,
                   {"kind": "mail", "label": label, "url": x.get("url")}, key=k, cat=x.get("cat"),
                   yes="откроет письмо в Gmail" if x.get("url") else "", act="open" if x.get("url") else "")
    return None


# ---------- сборка ----------
def headline(n: int, night: int) -> str:
    first = f"Ждут вас {n} {plural(n, 'решение', 'решения', 'решений')}." if n else "Решений от вас не ждут."
    tail = ("Ночью срочного не было." if not night
            else f"Ночью — {night} {plural(night, 'срочное', 'срочных', 'срочных')}, уже присылал.")
    return f"{first} {tail}"


def assemble(*, now: datetime, done=(), failed=(), today=(), decisions=(), status=(), night: int = 0,
             sel: dict | None = None) -> dict:
    """Готовый брифинг: строки без источника уже отброшены (``row``), блоки — не длиннее ``MAX_ROWS``."""
    dec = rows(decisions)
    dec.sort(key=lambda r: 0 if r.get("cat") else 1)              # срочное — первым
    cut = lambda xs: rows(xs)[:MAX_ROWS]                           # noqa: E731
    more = {k: max(0, len(rows(v)) - MAX_ROWS) for k, v in (("done", done), ("failed", failed), ("today", today))}
    return {"at": now.isoformat(timespec="minutes"), "headline": headline(len(dec), night),
            "done": cut(done), "failed": cut(failed), "today": sorted(cut(today), key=lambda r: r.get("at") or ""),
            "decisions": dec, "more": {k: v for k, v in more.items() if v}, "sources": list(status),
            "sel": sel or {}}


def collect(cfg, *, sel: dict, digest_items: list[dict], tasks_list: list[dict], now: datetime, night: int = 0,
            fresh=None) -> dict:
    """Собрать брифинг из выбранных источников. ``digest_items`` — пункты сводки (бот или панель собрали сами);
    ``fresh`` — фильтр отложенных/закрытых (``Digest.fresh``), он же запоминает пункты для кнопок."""
    src = set(sel.get("sources") or [])
    since_d = (now - timedelta(days=1)).date().isoformat()
    day = now.date().isoformat()
    done, failed, today, dec_items, status = [], [], [], [], []

    def off(sid: str):
        status.append({"id": sid, "label": SOURCES[sid], "state": "off"})

    if "mail" in src and sel.get("boxes"):
        items, st = mail_items(sel["boxes"], since_d)
        dec_items += items
        status += st
    elif "mail" in src:
        status.append({"id": "mail", "label": SOURCES["mail"], "state": "none", "note": "ящик не подключён"})
    if "calendar" in src and sel.get("calendars"):
        r, st = calendar_rows(sel["calendars"], day)
        today += r
        status += st
    elif "calendar" in src:
        status.append({"id": "calendar", "label": SOURCES["calendar"], "state": "none",
                       "note": "календарь не подключён — «Подключения» → «Календари»"})
    pr_items = [x for x in digest_items if x["kind"] == "pr"]
    if "github" in src:
        owner = getattr(cfg, "digest_github", "")
        try:
            if not owner:
                raise RuntimeError("не задан digest_github в настройках")
            done += merged(owner, since_d)
            status.append({"id": "github", "label": SOURCES["github"], "state": "ok"})
        except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as e:
            status.append({"id": "github", "label": SOURCES["github"], "state": "error", "note": str(e)[:200]})
        for x in pr_items:                                             # красный CI — «не выполнено», а не решение
            if x.get("ci") in ("FAILURE", "ERROR"):
                failed.append(row(f"PR {x['repo']}#{x['n']} — {digest.cut(x['title'], 70)}",
                                  {"kind": "github", "label": f"GitHub · {x['repo']}#{x['n']}", "url": x["url"]},
                                  why="CI красный — проверки не прошли"))
            else:
                dec_items.append(x)
    else:
        off("github")
    if "linear" in src:
        try:
            d, f = linear(since_d, day)
            done += d
            failed += f
            status.append({"id": "linear", "label": SOURCES["linear"], "state": "ok"})
        except Exception as e:                   # нет ключа, нет сети — брифинг без Linear
            status.append({"id": "linear", "label": SOURCES["linear"], "state": "error", "note": str(e)[:200]})
    else:
        off("linear")
    if "pult" in src:
        d, f = pult_tasks(tasks_list, (now - timedelta(days=1)).timestamp(), day)
        done += d
        failed += f
        dec_items += [x for x in digest_items if x["kind"] != "pr"]
        status.append({"id": "pult", "label": SOURCES["pult"], "state": "ok"})
    else:
        off("pult")
    if fresh:
        dec_items = fresh(dec_items)
    return assemble(now=now, done=done, failed=failed, today=today, decisions=[decision(x) for x in dec_items],
                    status=status, night=night, sel=sel)


# ---------- Telegram ----------
def _h(s: str) -> str:
    import html
    return html.escape(str(s), quote=True)


def _src(r: dict) -> str:
    s = r["source"]
    return f'<a href="{_h(s["url"])}">{_h(s["label"])}</a>' if s.get("url") else _h(s["label"])


def telegram(b: dict) -> str:
    """Брифинг текстом (HTML): вывод, блоки с источником у каждой строки; решения идут отдельными сообщениями."""
    out = [f"☀️ <b>{_h(b['headline'])}</b>"]
    for k, title in (("today", "📅 Сегодня"), ("done", "✅ Выполнено"), ("failed", "⚠️ Не выполнено — и почему")):
        if b.get(k):
            out.append(f"\n<b>{title}</b>")
            for r in b[k]:
                why = f" — {_h(r['why'])}" if r.get("why") else ""
                out.append(f"• {_h(r['text'])}{why} · {_src(r)}")
            if b.get("more", {}).get(k):
                out.append(f"  …и ещё {b['more'][k]} — в пульте")
    gone = [s for s in b.get("sources", []) if s["state"] in ("error", "none")]
    if gone:
        out.append("\n<i>Не подключено: " + _h("; ".join(f"{s['label']} — {s.get('note', '')}" for s in gone)) + "</i>")
    if b.get("decisions"):
        out.append(f"\n<b>🗳 Ваши решения — {len(b['decisions'])}</b>, ниже по одному.")
    return "\n".join(out)


def decision_msg(i: int, r: dict, panel: str = "") -> tuple[str, dict]:
    """Одно решение: текст с источником и что сделает «Да»; кнопки «Да / Нет / Позже» и «📱 Открыть в пульте»."""
    text = f"{i}. {_h(r['text'])}\nИсточник: {_src(r)}"
    if r.get("yes"):
        text += f"\n«Да» — {_h(r['yes'])}."
    k = r["key"]
    if r.get("act") == "open" and r["source"].get("url"):
        yes = {"text": "✅ Да", "url": r["source"]["url"]}
    else:
        yes = {"text": "✅ Да", "callback_data": f"dg:y:{k}"}
    kb = [[yes, {"text": "✖️ Нет", "callback_data": f"dg:c:{k}"}, {"text": "⏰ Позже", "callback_data": f"dg:l:{k}"}]]
    if panel:
        kb.append([{"text": "📱 Открыть в пульте", "web_app": {"url": panel}}])
    return text, {"inline_keyboard": kb}


# ---------- срочное вне утра ----------
class Alerts:
    """``brief_alerts.json``: срочное, которое владелец уже видел (ключ → [время, будили ли]) — не будить дважды.
    Показанное в брифинге записывается без «будили»; ночью разбуженное считает строка «Ночью — N срочных»."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict:
        try:
            d = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        return {k: v for k, v in d.items() if isinstance(v, list) and len(v) == 2} if isinstance(d, dict) else {}

    def new(self, keys: list[str], now: float, woke: bool = True) -> list[str]:
        """Каких ключей ещё не было; записывает их. Первый запуск (файла нет) — всё молча: не будить старым."""
        first = not self.path.exists()
        d = {k: v for k, v in self.load().items() if now - v[0] < 7 * 86400}
        fresh = [k for k in dict.fromkeys(keys) if k not in d]
        d.update({k: [now, woke and not first] for k in fresh})
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d))
        tmp.chmod(0o600)
        tmp.replace(self.path)
        return [] if first else fresh

    def night(self, now: datetime) -> int:
        """Сколько раз будили срочным с 22:00 вчера до сейчас."""
        h, m = map(int, NIGHT_FROM.split(":"))
        start = (now - timedelta(days=1)).replace(hour=h, minute=m, second=0, microsecond=0).timestamp()
        return sum(1 for t, woke in self.load().values() if woke and t >= start)


def hot(b: dict) -> list[dict]:
    """Срочные решения брифинга (деньги, безопасность, срок) — по ним можно будить вне утра."""
    from gas_pult import notifylevel
    return [r for r in b.get("decisions", []) if notifylevel.wakes(r.get("cat"))]


# ---------- решения из панели: «Да» — только после подтверждения; всё — в журнал ----------
def log(data: Path, uid, key: str, act: str, kind: str, result: str):
    """``brief_log.jsonl`` (0600): кто, что и с каким итогом решил в брифинге — без текста писем."""
    path = data / "brief_log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    new = not path.exists()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": int(time.time()), "uid": uid, "key": key, "act": act, "kind": kind,
                            "result": result[:200]}, ensure_ascii=False) + "\n")
    if new:
        path.chmod(0o600)


def act(pult, uid, key: str, what: str, sure: bool = False) -> dict:
    """«Да» / «Нет» / «Позже» по пункту брифинга. ``pult`` — бот (digest, project_window, to_claude).
    Ответ: {done} — сделано; {ask} — спросить подтверждение и прислать снова с ``sure``; {url} / {window} — открыть."""
    x = pult.digest.item(key)
    if not x:
        raise ValueError("этого пункта уже нет в брифинге — обновите")
    data = pult.cfg.data
    if what in ("no", "later"):
        pult.digest.snooze(key, digest.GONE if what == "no" else digest.LATER)
        log(data, uid, key, what, x["kind"], "убрано на месяц" if what == "no" else "до следующего брифинга")
        return {"done": "Убрал на месяц" if what == "no" else "Вернётся в следующем брифинге"}
    if what != "yes":
        raise ValueError("действие: yes, no или later")
    if x["kind"] == "mail" or (x["kind"] == "pr" and not x.get("ok")):
        if not x.get("url"):
            raise ValueError("ссылки нет — откройте письмо в почте")
        log(data, uid, key, "open", x["kind"], "открыто")
        return {"url": x["url"]}
    if x["kind"] == "win":
        log(data, uid, key, "open", "win", "открыт экран")
        return {"window": x["id"]}
    if not sure:
        return {"ask": f"Слить {x['repo']}#{x['n']} «{x['title']}»?" if x["kind"] == "pr"
                else f"Передать «да» в окно {x['project']}: {x['text']}?"}
    if x["kind"] == "pr":
        done = digest.merge(x["repo"], x["n"])
    elif w := pult.project_window(x["path"]):
        pult.to_claude(w, f"Владелец отвечает «да» на пункт из HANDOFF.md: {x['text']}")
        done = f"Передал «да» в «{w['name']}»"
    else:
        raise ValueError(f"окна с Claude в {x['project']} нет — откройте сессию и повторите")
    pult.digest.snooze(key, digest.GONE)
    log(data, uid, key, "yes", x["kind"], done)
    return {"done": done}
