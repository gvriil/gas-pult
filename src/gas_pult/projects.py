"""«Проекты» (задача 49, docs/PROJECTS.md): папка со своими инструкциями (``CLAUDE.md``), файлами, интеграциями и
моделью по умолчанию; внутри — много сессий (чатов).

Метаданные — ``<data>/projects.json`` (0600). Источник правды о сессиях — журналы Claude Code, а не этот файл: в нём
только имена, настройки и переименования. Файла нет — пульт строит его сам из папок, окон и ``add_dirs``
(миграция, раздел 2.5): идемпотентно (id — от ``realpath`` папки), ничего на диске не переносит и не удаляет.
Откат — удалить ``projects.json``.

Рабочие копии git worktree (``~/worktrees/*``) — не отдельные проекты, а доп. папки (``paths``) проекта основного
репозитория (вопрос 1 раздела 7 — по рекомендации документа).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from gas_pult import modules, transcripts
from gas_pult.config import write_private

VERSION = 1
FILE = "projects.json"
HOME_NAME = "Домашняя"
TITLE_MAX = 60
_lock = threading.Lock()


def pid_of(real: str) -> str:
    """Детерминированный id проекта по ``realpath`` папки: повторная миграция даёт те же id."""
    return "p" + hashlib.sha1(real.encode("utf-8", "surrogatepass")).hexdigest()[:10]


def tilde(path: str, home: str) -> str:
    """Путь с ``~`` вместо домашней папки: в файле и ответах API — без личных путей."""
    home = home.rstrip("/")
    return "~" + path[len(home):] if path == home or path.startswith(home + "/") else path


def untilde(path: str, home: str) -> str:
    return home.rstrip("/") + path[1:] if path == "~" or path.startswith("~/") else path


def main_repo(folder: str) -> str:
    """Рабочая копия git worktree → папка основного репозитория (по файлу ``.git``: ``gitdir: …/.git/worktrees/x``);
    обычная папка — ""."""
    try:
        text = (Path(folder) / ".git").read_text(encoding="utf-8", errors="replace").strip()
    except (OSError, IsADirectoryError):
        return ""
    m = re.match(r"gitdir:\s*(.+?)/\.git/worktrees/[^/]+/?$", text)
    return os.path.realpath(m.group(1)) if m else ""


def empty() -> dict:
    return {"v": VERSION, "projects": {}, "sessions": {}}


def pins_of(d: dict, who: str | None) -> tuple[dict, dict]:
    """Закрепления человека: (проекты ``{pid: время}``, сессии и чаты ``{ключ: время}``). ``who`` None — пусто."""
    mine = ((d.get("pins") or {}).get(str(who)) or {}) if who else {}
    return mine.get("projects") or {}, mine.get("chats") or {}


def _migrate_pins(d: dict):
    """Прежние общие закрепления (``pinned`` у проекта, плоские ``pins`` ``{ключ: время}``) — в закрепления владельца.
    Идемпотентно; на диск попадает со следующей записью."""
    pins = d.get("pins") if isinstance(d.get("pins"), dict) else {}
    flat = {k: v for k, v in pins.items() if not isinstance(v, dict)}
    olds = {pid: p["pinned"] for pid, p in d["projects"].items() if isinstance(p, dict) and p.get("pinned")}
    if not flat and not olds:
        return
    pins = {k: v for k, v in pins.items() if isinstance(v, dict)}
    owner = pins.setdefault("owner", {})
    for k, v in flat.items():
        if isinstance(v, int) and v > 0:
            owner.setdefault("chats", {}).setdefault(k, v)
    for pid, v in olds.items():
        owner.setdefault("projects", {}).setdefault(pid, v if isinstance(v, int) and v > 1 else 1)
        d["projects"][pid]["pinned"] = False
    d["pins"] = pins


class Store:
    """``projects.json`` под замком. ``home`` — домашняя папка сервера (для ``~``), путь проекта хранится с ``~``."""

    def __init__(self, file: Path, home: str):
        self.file, self.home = file, home.rstrip("/") or "/"

    def read(self) -> dict:
        try:
            d = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return empty()
        if not isinstance(d, dict) or not isinstance(d.get("projects"), dict):
            return empty()
        d.setdefault("sessions", {})
        _migrate_pins(d)
        return d

    def write(self, d: dict):
        write_private(self.file, json.dumps(d, ensure_ascii=False, indent=1) + "\n")

    def real(self, p: dict) -> str:
        return os.path.realpath(untilde(p["path"], self.home))

    def exists(self) -> bool:
        return self.file.exists()

    # ---------- миграция и досоздание ----------
    def sync(self, folders: list[str], windows: list[dict], add_dirs: dict | None = None) -> dict:
        """Каждая папка из ``folders`` (домашняя и подпапки корней) и каждое окно Claude вне проектов → авто-проект;
        рабочая копия worktree → доп. папка проекта основного репозитория; ``add_dirs`` (#123) → ``repos``.
        Существующие проекты не меняются (имя, архив, настройки — как оставил человек). Пишем, только если что-то
        добавилось. Возвращает данные."""
        with _lock:
            d = self.read()
            before = json.dumps(d, sort_keys=True)
            home_real = os.path.realpath(self.home)
            later: list[str] = []
            for f in folders:
                if not os.path.isdir(f):
                    continue
                if main_repo(f):
                    later.append(f)                     # worktree — после основных: основной может идти позже
                else:
                    self._add(d, f, home_real)
            for w in windows:
                if w.get("space") or not (w.get("cmd") == "claude" or w.get("mark")) or not w.get("path"):
                    continue
                if self.of_path(d, w["path"]) is None and os.path.isdir(w["path"]):
                    if main_repo(w["path"]):
                        later.append(w["path"])
                    else:
                        self._add(d, w["path"], home_real)
            for f in later:
                self._attach(d, f, home_real)
            for key, dirs in (add_dirs or {}).items():
                pid = self.of_path(d, key)
                if pid and isinstance(dirs, list):
                    p = d["projects"][pid]
                    have = list(p.get("repos") or [])
                    for x in dirs:
                        if isinstance(x, str) and (t := tilde(x, self.home)) not in have:
                            have.append(t)
                    p["repos"] = have
            d["v"] = VERSION
            if json.dumps(d, sort_keys=True) != before or not self.file.exists():
                self.write(d)
            return d

    def _add(self, d: dict, folder: str, home_real: str) -> str:
        real = os.path.realpath(folder)
        pid = pid_of(real)
        if pid in d["projects"]:
            return pid
        mk = modules.mark_of(Path(real)) or {}
        name = HOME_NAME if real == home_real else (str(mk.get("title") or "") or os.path.basename(real))
        d["projects"][pid] = {
            "id": pid, "name": name[:80], "path": tilde(real, self.home), "paths": [],
            "owner": {"kind": "person", "uid": None}, "share": [],
            "origin": f"module:{mk['id']}" if mk.get("id") else "auto",
            "created": int(time.time()), "by": None, "profile": "", "model": "", "effort": "",
            "integrations": [], "files": "files", "repos": [], "pinned": False, "archived": False}
        return pid

    def _attach(self, d: dict, folder: str, home_real: str):
        """Рабочая копия → ``paths`` проекта основного репозитория; основного нет среди проектов — свой проект."""
        real = os.path.realpath(folder)
        main = main_repo(real)
        owner = next((pid for pid, p in d["projects"].items() if self.real(p) == main), None)
        if owner is None:
            self._add(d, real, home_real)
            return
        mine = d["projects"].get(pid_of(real))
        if mine and mine.get("origin") == "auto" and pid_of(real) != owner:
            return                                       # уже отдельный проект (прошлая миграция) — не трогаем
        p = d["projects"][owner]
        t = tilde(real, self.home)
        if t not in p.setdefault("paths", []):
            p["paths"].append(t)

    # ---------- окно → проект ----------
    def of_path(self, d: dict, path: str) -> str | None:
        """Проект папки: ``realpath`` внутри ``path`` или ``paths`` проекта — самое длинное совпадение. Домашняя папка —
        только точное совпадение (иначе в неё попало бы всё)."""
        if not path:
            return None
        real = os.path.realpath(path)
        home_real = os.path.realpath(self.home)
        best, n = None, -1
        for pid, p in d["projects"].items():
            for x in [p["path"], *(p.get("paths") or [])]:
                r = os.path.realpath(untilde(x, self.home))
                inside = real == r or (r != home_real and real.startswith(r.rstrip("/") + "/"))
                if inside and len(r) > n:
                    best, n = pid, len(r)
        return best

    def set_chat(self, sid: str, pid: str, title=None, hidden=None) -> dict:
        """Своё название и «скрыт» у чата (``sessions``) — единственное, что пульт хранит о сессии сверх журнала."""
        with _lock:
            d = self.read()
            rec = dict(d["sessions"].get(sid) or {})
            rec["project"] = pid
            if title is not None:
                rec["title"] = title
                if not title:
                    rec.pop("title")
            if hidden is not None:
                rec["hidden"] = hidden
            d["sessions"][sid] = rec
            self.write(d)
            return rec

    def set_pin(self, who: str, on: bool, pid: str = "", key: str = "") -> int:
        """«Закрепить» / «Открепить» — свои у каждого человека (``who``: «owner» или Telegram ID участника):
        ``pins[who]["projects"][pid]`` или ``pins[who]["chats"][key]`` (``sid:<id сессии>`` или ``path:<папка с ~>``
        у старого окна без метки). Значение — время закрепления: порядок в группе «Закреплённые». Возвращает его
        или 0."""
        ts = int(time.time()) if on else 0
        with _lock:
            d = self.read()
            if pid and pid not in d["projects"]:
                raise LookupError("проекта нет — обновите список")
            mine = d.setdefault("pins", {}).setdefault(str(who), {})
            box = mine.setdefault("projects" if pid else "chats", {})
            if ts:
                box[pid or key] = ts
            else:
                box.pop(pid or key, None)
            self.write(d)
            return ts

    def folders_of(self, p: dict) -> list[str]:
        """Все папки проекта (главная и рабочие копии) — полными путями."""
        return [untilde(x, self.home) for x in [p["path"], *(p.get("paths") or [])]]


# ---------- сессии проекта из журналов Claude Code ----------
_titles: dict[str, tuple[int, int, str]] = {}       # файл журнала → (mtime_ns, размер, название)


def session_files(folders: list[str], homes: list) -> list[Path]:
    """Журналы всех папок проекта во всех папках Claude Code (владелец — None, участники — свои). Запуски
    ``claude -p`` (плановые задания, ``entrypoint`` = ``sdk-cli``) — не чаты проекта: их не показываем."""
    out: list[Path] = []
    seen: set[Path] = set()
    for f in folders:
        for h in homes:
            for x in transcripts.transcripts(f, h):
                if x not in seen and not transcripts.is_batch(x):
                    seen.add(x)
                    out.append(x)
    return out


def said(e: dict) -> bool:
    """Настоящее сообщение переписки: запрос человека или ответ Claude с текстом — не служебная запись
    (``ai-title``, ``mode``, ``queue-operation``…), не субагент, не ответ-заглушка Claude Code (``<synthetic>``)."""
    if e.get("isSidechain"):
        return False
    if e.get("type") == "user":
        return transcripts.is_real_prompt(e)
    if e.get("type") == "assistant":
        msg = e.get("message") or {}
        return bool(transcripts.text_of(msg.get("content")).strip()) and not str(msg.get("model") or "").startswith("<")
    return False


def epoch(ts) -> int:
    """``2026-11-09T16:06:00.123Z`` → секунды; не разобрать — 0."""
    try:
        return int(datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


_tails: dict[str, tuple[int, int, dict]] = {}       # файл → (mtime_ns, размер, {last, ai})


def tail_info(f: Path, step: int = 262144, limit: int = 8 * 1024 * 1024, enough: int = 1024 * 1024) -> dict:
    """С конца журнала: когда было последнее настоящее сообщение (``last``, секунды) и последнее название, которое
    дал чату Claude Code (запись ``ai-title``, ``ai``). Время изменения файла для порядка не годится: «Продолжить»,
    смена режима или закрытие окна дописывают служебные записи — и старый чат прыгал наверх «только что».
    Читается не больше ``limit`` байт с конца; не нашли сообщения в них — время изменения файла (``cut``); сообщение
    нашлось, а названия нет и в ``enough`` байт — дальше не ищем (название — из начала файла).
    Кэш — по времени изменения и размеру."""
    try:
        st = f.stat()
    except OSError:
        return {"last": 0, "ai": "", "cut": False}
    key = str(f)
    old = _tails.get(key)
    if old and old[0] == st.st_mtime_ns and old[1] == st.st_size:
        return old[2]
    last, ai, pos, buf, read = 0, "", st.st_size, b"", 0
    try:
        with open(f, "rb") as fh:
            while pos > 0 and read < limit and not (last and (ai or read >= enough)):
                start = max(0, pos - step)
                fh.seek(start)
                buf = fh.read(pos - start) + buf
                read += pos - start
                pos = start
                lines = buf.split(b"\n")
                buf, lines = (lines[0], lines[1:]) if pos > 0 else (b"", lines)   # первая строка куска — обрывок
                for raw in reversed(lines):
                    if not ai and b'"ai-title"' in raw:
                        with contextlib.suppress(ValueError):
                            e = json.loads(raw)
                            if e.get("type") == "ai-title":
                                ai = " ".join(str(e.get("aiTitle") or "").split())
                    elif not last and (b'"user"' in raw or b'"assistant"' in raw):
                        try:
                            e = json.loads(raw)
                        except ValueError:
                            continue
                        if said(e):
                            last = epoch(e.get("timestamp"))
                    if last and ai:
                        break
    except OSError:
        return {"last": 0, "ai": "", "cut": False}
    cut = not last and pos > 0
    out = {"last": last or (int(st.st_mtime) if cut else 0), "ai": ai, "cut": cut}
    if len(_tails) > 5000:
        _tails.clear()
    _tails[key] = (st.st_mtime_ns, st.st_size, out)
    return out


def last_said(f: Path) -> int:
    """Когда в чате было последнее настоящее сообщение (секунды); сообщений нет — 0."""
    return tail_info(f)["last"]


def title_of(f: Path, head: int = 262144) -> str:
    """Название чата: последнее название от Claude Code (``ai-title``, как в его списке ``/resume``) → запись
    ``summary`` → первое настоящее сообщение человека (до 60 знаков). Начало файла кэшируется по размеру: журнал
    только дописывается; название Claude Code — с конца (``tail_info``)."""
    try:
        st = f.stat()
    except OSError:
        return ""
    t = tail_info(f)["ai"] or _head_title(f, st, head)
    return t[:TITLE_MAX - 1].rstrip() + "…" if len(t) > TITLE_MAX else t


def _head_title(f: Path, st, head: int) -> str:
    key = str(f)
    old = _titles.get(key)
    if old and (old[0] == st.st_mtime_ns or (old[2] and st.st_size >= old[1])):
        return old[2]                               # журнал только дописывается — начало, а с ним название, то же
    summary, first, ai = "", "", ""
    try:
        with open(f, "rb") as fh:
            chunk = fh.read(head).decode("utf-8", "replace")
    except OSError:
        return ""
    for line in chunk.splitlines():
        if '"summary"' not in line and '"user"' not in line and '"ai-title"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "ai-title" and e.get("aiTitle"):
            ai = str(e["aiTitle"])
        elif e.get("type") == "summary" and e.get("summary"):
            summary = str(e["summary"])
        elif not first and e.get("type") == "user" and not e.get("isSidechain") and transcripts.is_real_prompt(e):
            first = transcripts.PASTED.sub("", transcripts.text_of(e["message"]["content"]))
    t = " ".join((ai or summary or first).split())
    if len(_titles) > 5000:
        _titles.clear()
    _titles[key] = (st.st_mtime_ns, st.st_size, t)
    return t


_prompts: dict[str, tuple[int, int]] = {}            # файл → (mtime_ns, сколько сообщений человека)


def prompts(f: Path) -> int:
    """Сколько настоящих сообщений человека в журнале (кэш по времени изменения)."""
    try:
        st = f.stat()
    except OSError:
        return 0
    key = str(f)
    if key in _prompts and _prompts[key][0] == st.st_mtime_ns:
        return _prompts[key][1]
    n = 0
    with contextlib.suppress(OSError), open(f, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"user"' not in line or '"isSidechain":true' in line.replace(" ", ""):
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            n += e.get("type") == "user" and transcripts.is_real_prompt(e)
    if len(_prompts) > 5000:
        _prompts.clear()
    _prompts[key] = (st.st_mtime_ns, n)
    return n


def contains(f: Path, q: str, limit: int = 32 * 1024 * 1024) -> bool:
    """Есть ли ``q`` (уже в нижнем регистре) в тексте журнала — грубо, по строкам JSON; большие файлы — до ``limit``."""
    q = q.lower()
    try:
        with open(f, "rb") as fh:
            data = fh.read(limit)
    except OSError:
        return False
    text = data.decode("utf-8", "replace").lower()
    if q in text:
        return True
    esc = json.dumps(q, ensure_ascii=True)[1:-1]     # кириллица в журнале бывает экранирована (\u0441…)
    return esc != q and esc in text


def stats(files: list[Path]) -> dict:
    """Сколько чатов у проекта, когда в последнем было настоящее сообщение (не время изменения файла) и его журнал.
    Равное время — у кого файл новее."""
    best, lf = (0, 0), None
    for f in files:
        try:
            m = f.stat().st_mtime
        except OSError:
            continue
        k = (last_said(f), m)
        if k[0] and k > best:
            best, lf = k, f
    return {"total": len(files), "last": best[0] or None, "last_file": lf}
