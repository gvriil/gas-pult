"""Сообщения команды в чат и «Сообщить об ошибке» (владелец 22.11: тестировщики и фокус-ссылки).

**Сообщения команды** — ``<данные>/team_msgs.json`` (0600, список; запись — ``store.update`` под файловым замком: пишут
панель, CLI штаба и закрытие задачи из любого процесса). Сообщение: ``id``, ``at`` (секунды), ``from`` («Команда»),
``text``, ``kind`` (info — от команды · ack — «Приняли» · fixed — «Исправлено»), ``ref`` (id задачи) и адрес — окно
(``w`` и разговор ``sid``: окно перезапустили с тем же разговором — сообщения на месте) или проект (``proj``: видно во
всех его окнах), у окон пространства — ``space``. В чате — отдельной карточкой «Команда Ладеи» по времени, в Claude
не уходят и вводом человека не считаются: в tmux ничего не пишется. Отдача — полем ``team`` ответа ``/api/history``
(``for_window``: только окно запроса и его проект — фокус-ссылка чужих не видит). Событие ``team_msg`` в журнале
чата — без текста.

**Отчёт об ошибке** — ``bug_save``: ``<данные>/bugs/<время>-<случайное>.json`` (0600): текст, устройство и браузер,
состояние экрана, которое прислала панель (``ctx``: адрес экрана, размер окна, тема, последние ошибки и сообщения
интерфейса; это не картинка) и картинка, если человек приложил её сам. ``bug_task`` — задача владельцу (тип check,
ссылка на файл, ``team_to`` — куда ответить). Задачу закрыли (``tasks.Tasks.update`` → done) — ``on_done`` пишет в
тот же чат «Исправлено: …».
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

from gas_pult import chatlog
from gas_pult import store as jstore

FILE = "team_msgs.json"
BUGS = "bugs"
FROM = "Команда"
KINDS = ("info", "fixed", "ack")
MAX_TEXT = 2000
KEEP = 2000                       # всего сообщений; больше — самые старые уходят
SHOW = 30                         # в ответе истории — последние для окна
ACK = "Приняли, сообщим, когда исправим."
FIXED = "Исправлено: {title}. Проверьте, пожалуйста."
WID = re.compile(r"^@\d{1,6}$")
PID = re.compile(r"^(p[0-9a-f]{10}|s:[a-z0-9-]{1,40}:[A-Za-z0-9._-]{1,80})$")


def utc_ts(at: float) -> str:
    """Время как у сообщений переписки (``ts`` журнала): UTC «ГГГГ-ММ-ДД ЧЧ:ММ» — панель переводит в местное."""
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(at))


def target(w: str = "", sid: str = "", proj: str = "", space: str = "") -> dict:
    """Адрес сообщения: окно (и его разговор) или проект. Проверка формата — без tmux."""
    w, proj, sid = str(w or ""), str(proj or ""), str(sid or "")[:40]
    if bool(w) == bool(proj):
        raise ValueError("кому: окно (@N) или проект (pXXX)")
    if w and not WID.match(w):
        raise ValueError("окно — @N")
    if proj and not PID.match(proj):
        raise ValueError("проект — pXXXXXXXXXX")
    out = {"w": w, "sid": sid} if w else {"proj": proj}
    if space:
        out["space"] = str(space)[:40]
    return out


def to_key(t: dict) -> str:
    """Адрес строкой — для поля задачи ``team_to`` (tasks.LIMITS)."""
    return json.dumps({k: v for k, v in t.items() if v}, ensure_ascii=False, separators=(",", ":"))


def from_key(s: str) -> dict | None:
    try:
        d = json.loads(s or "")
        return target(d.get("w", ""), d.get("sid", ""), d.get("proj", ""), d.get("space", ""))
    except (ValueError, TypeError, AttributeError):
        return None


class TeamMsgs:
    def __init__(self, path: Path, clock=time.time):
        self.path, self.clock = Path(path), clock

    def say(self, to: dict, text: str, kind: str = "info", ref: str = "") -> dict:
        text = str(text or "").strip()[:MAX_TEXT]
        if not text:
            raise ValueError("текст пустой")
        if kind not in KINDS:
            raise ValueError("вид: " + ", ".join(KINDS))
        to = target(to.get("w", ""), to.get("sid", ""), to.get("proj", ""), to.get("space", ""))
        m = {"id": secrets.token_hex(5), "at": round(self.clock(), 3), "from": FROM, "text": text, "kind": kind,
             **({"ref": str(ref)[:20]} if ref else {}), **to}

        def add(items):                                  # на месте: store.update пишет тот же список
            items[:] = [*[x for x in items if isinstance(x, dict)][-(KEEP - 1):], m]
        jstore.update(self.path, add, list, ensure_ascii=False)
        chatlog.Log(self.path.parent / "chat-events.jsonl").event(   # событие — без текста
            "team_msg", m["id"], kind=kind, to="proj" if to.get("proj") else "w", w=to.get("w"),
            space=to.get("space"), n=len(text))
        return m

    def all(self) -> list[dict]:
        return [x for x in jstore.load(self.path, list) if isinstance(x, dict) and x.get("id")]

    def for_window(self, w: dict, proj: str = "", limit: int = SHOW) -> list[dict]:
        """Сообщения окна ``w`` (по id окна или его разговору) и его проекта ``proj`` — того же пространства."""
        space, wid, sid = str(w.get("space") or ""), w.get("id") or "", w.get("sid") or ""
        def mine(m):
            if str(m.get("space") or "") != space:
                return False
            if m.get("w"):
                same_sid = not m.get("sid") or not sid or m["sid"] == sid
                return (m["w"] == wid and same_sid) or bool(sid and m.get("sid") == sid)
            return bool(proj) and m.get("proj") == proj
        out = [m for m in self.all() if mine(m)]
        return [public(m) for m in out[-limit:]]


def public(m: dict) -> dict:
    return {"id": m["id"], "at": m["at"], "ts": utc_ts(m["at"]), "from": m.get("from") or FROM,
            "text": m["text"], "kind": m.get("kind") or "info", **({"ref": m["ref"]} if m.get("ref") else {})}


def on_done(data_dir: Path, task: dict):
    """Задачу из отчёта закрыли — человеку в его чат «Исправлено: …» (``tasks.Tasks.update``)."""
    to = from_key(task.get("team_to") or "")
    if not to:
        return None
    title = re.sub(r"^Ошибка:\s*", "", str(task.get("title") or "")).strip() or "ваше сообщение об ошибке"
    return TeamMsgs(Path(data_dir) / FILE).say(to, FIXED.format(title=title.rstrip(".")), "fixed", task.get("id", ""))


# ---------- «Сообщить об ошибке» ----------
class Rate:
    """Не чаще ``n`` за ``per`` секунд с одного ключа (устройство человека) — в памяти процесса панели."""

    def __init__(self, n: int = 3, per: float = 60.0, clock=time.time):
        self.n, self.per, self.clock, self.seen, self.lock = n, per, clock, {}, threading.Lock()

    def hit(self, key: str) -> bool:
        now = self.clock()
        with self.lock:
            xs = [t for t in self.seen.get(key, []) if now - t < self.per]
            if len(xs) >= self.n:
                self.seen[key] = xs
                return False
            self.seen[key] = [*xs, now]
            if len(self.seen) > 5000:                     # старые ключи — прочь
                self.seen = {k: v for k, v in self.seen.items() if v and now - v[-1] < self.per}
            return True


def _ctx(ctx) -> dict:
    """Состояние экрана от панели — только известные поля, короткими строками (это не картинка)."""
    if not isinstance(ctx, dict):
        return {}
    s = lambda v, n=200: " ".join(str(v or "").split())[:n]   # noqa: E731
    out = {"screen": s(ctx.get("screen"), 80), "url": s(ctx.get("url"), 300), "size": s(ctx.get("size"), 40),
           "theme": s(ctx.get("theme"), 20), "lang": s(ctx.get("lang"), 20), "build": s(ctx.get("build"), 40),
           "shot_note": s(ctx.get("shot_note"), 200),     # «снимок не получился: …» — честная строка от панели
           "errors": [s(x, 300) for x in (ctx.get("errors") or [])[:10] if isinstance(x, str)],
           "ui": [s(x, 300) for x in (ctx.get("ui") or [])[:10] if isinstance(x, str)]}
    return {k: v for k, v in out.items() if v}


def _write(path: Path, data: bytes):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def bug_save(data_dir: Path, text: str, *, device: str, browser: str, who: str, to: dict, proj: str = "",
             chat_title: str = "", ctx=None, shot: str = "") -> dict:
    """Отчёт — файл 0600 в ``<данные>/bugs/``; картинка, если приложили, — рядом (``feedback.shot_bytes``)."""
    from gas_pult import feedback

    text = str(text or "").strip()
    if not text:
        raise ValueError("напишите, что не так")
    if len(text) > MAX_TEXT:
        raise ValueError(f"текст — до {MAX_TEXT} символов")
    d = Path(data_dir) / BUGS
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    base = time.strftime("%Y-%m-%d-%H%M%S") + "-" + secrets.token_hex(3)
    rec = {"at": int(time.time()), "who": str(who or "")[:80], "text": text, "device": device, "browser": browser,
           "proj": proj, "chat": to.get("w", ""), "chat_title": str(chat_title or "")[:80],
           "space": to.get("space", ""), "ctx": _ctx(ctx), "shot": ""}
    if shot:
        ext, data = feedback.shot_bytes(shot)
        rec["shot"] = f"{base}.{ext}"
        _write(d / rec["shot"], data)
    rec["shot_file"] = str(d / rec["shot"]) if rec["shot"] else ""
    rec["file"] = str(d / f"{base}.json")
    _write(d / f"{base}.json", json.dumps(rec, ensure_ascii=False, indent=1).encode())
    return rec


def bug_task(rec: dict, to: dict) -> dict:
    """Задача владельцу и штабу по отчёту: тип check, ссылка — файл отчёта, ``team_to`` — куда ответить."""
    head = " ".join(rec["text"].split())[:120]
    where = f"чат «{rec['chat_title']}»" if rec.get("chat_title") else f"чат {rec.get('chat') or '—'}"
    shot = "снимок экрана приложен" if rec.get("shot") else "без снимка экрана"
    return {"title": f"Ошибка: {head}", "kind": "check", "status": "todo", "link": rec["file"],
            "shot": rec.get("shot_file") or "",
            "next": f"Проверить отчёт ({rec['who'] or 'без имени'}; {where}; {rec['device'] or '—'}, "
                    f"{rec['browser'] or '—'}; {shot}) и исправить; закроете — человеку придёт «Исправлено»",
            "chat": rec.get("chat") or "", "sid": to.get("sid", ""), "chat_title": rec.get("chat_title") or "",
            "proj": rec.get("proj") or "", "device": rec["device"], "browser": rec["browser"], "text": rec["text"],
            "team_to": to_key(to)}
