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
import time
from datetime import datetime
from pathlib import Path

from gas_pult import harness, modules, transcripts
from gas_pult import store as jstore
from gas_pult.config import write_private

VERSION = 1
FILE = "projects.json"
HOME_NAME = "Домашняя"
TITLE_MAX = 60


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


# «Новый проект»: имя человека (латиница или кириллица) → имя папки по правилу «Новой папки» (``bot.NAME_OK``):
# латиница в нижнем регистре, цифры, дефис, 2–41 знак; «/», «..» и прочее — дефисами, по краям — без них.
FOLDER_OK = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
NAME_MAX = 80
_LAT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                 "u", "f", "kh", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"], strict=True))


def folder_of(name: str) -> str:
    """Имя папки для проекта «name»: «Магазин книг» → ``magazin-knig``, «../x» → ``x``. Не вышло 2 знаков — ""."""
    s = "".join(_LAT.get(ch, ch) for ch in (name or "").strip().lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:41].strip("-")
    return s if FOLDER_OK.match(s) else ""


def empty() -> dict:
    return {"v": VERSION, "projects": {}, "sessions": {}}


def order_of(d: dict, who: str | None) -> dict:
    """Свой порядок групп панели человека: {группа: [id…]} (``Store.set_order``)."""
    return dict((d.get("order") or {}).get(str(who)) or {}) if who else {}


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
        with jstore.locked(self.file):
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
                if w.get("space") or not (harness.is_agent(w) or w.get("mark")) or not w.get("path"):
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

    def create(self, folder: str, name: str, by: int | None = None, profile: str = "", model: str = "") -> str:
        """«Новый проект»: запись для только что созданной папки — имя человека, кто создал, поставщик и модель по
        умолчанию (пусто — как у пульта). Проект с этой папкой уже есть — его id, запись не трогаем."""
        with jstore.locked(self.file):
            d = self.read()
            real = os.path.realpath(folder)
            pid = pid_of(real)
            if pid not in d["projects"]:
                self._add(d, real, os.path.realpath(self.home))
                d["projects"][pid].update({"name": (name.strip() or os.path.basename(real))[:NAME_MAX],
                                           "origin": "new", "by": by, "profile": profile, "model": model})
                d["v"] = VERSION
                self.write(d)
            return pid

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
        with jstore.locked(self.file):
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

    def set_project(self, pid: str, name=None, archived=None) -> dict:
        """Название и архив проекта — только в ``projects.json``: папку на диске и журналы Claude Code не трогаем."""
        with jstore.locked(self.file):
            d = self.read()
            p = d["projects"].get(pid)
            if p is None:
                raise LookupError("проекта нет — обновите список")
            if name is not None:
                p["name"] = name
            if archived is not None:
                p["archived"] = bool(archived)
            self.write(d)
            return p

    ORDER_GROUP = re.compile(r"^(pins|proj|chats|p:[A-Za-z0-9_.-]{1,64})$")

    def set_order(self, who: str, grp: str, ids: list) -> list[str]:
        """Свой порядок в группе панели (владелец 20.11: «двигать между собой, ставить приоритет»): ``pins`` —
        закреплённые, ``proj`` — проекты, ``chats`` — чаты, ``p:<id проекта>`` — чаты проекта. Свой у каждого
        человека (``who``), на сервере — одинаков на всех устройствах. Пустой список — вернуть порядок по умолчанию."""
        if not self.ORDER_GROUP.match(str(grp or "")):
            raise ValueError("неизвестная группа")
        clean = [str(x)[:200] for x in (ids or []) if str(x).strip()][:500]
        with jstore.locked(self.file):
            d = self.read()
            mine = d.setdefault("order", {}).setdefault(str(who), {})
            if clean:
                mine[grp] = clean
            else:
                mine.pop(grp, None)
            self.write(d)
        return clean

    def set_pin(self, who: str, on: bool, pid: str = "", key: str = "") -> int:
        """«Закрепить» / «Открепить» — свои у каждого человека (``who``: «owner» или Telegram ID участника):
        ``pins[who]["projects"][pid]`` или ``pins[who]["chats"][key]`` (``sid:<id сессии>`` или ``path:<папка с ~>``
        у старого окна без метки). Значение — время закрепления: порядок в группе «Закреплённые». Возвращает его
        или 0."""
        ts = int(time.time()) if on else 0
        with jstore.locked(self.file):
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
                if x not in seen and transcripts.inside(x, h) and not transcripts.is_batch(x):   # ссылка наружу — нет
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
    ai = tail_info(f)["ai"]
    if ai and not is_status(ai):
        t = ai
    else:                       # название-статус («Ожидание формулировки задачи») — не название (владелец 19.11)
        h = _head_title(f, st, head)
        good = next((x for x in (h["ai"], h["summary"]) if x and not is_status(x)), "")
        status = ai or h["ai"]                      # Claude Code назвал чат статусом — смысл из сообщений человека
        t = good or ((first_words(h["meaning"]) or status) if status else h["summary"] or h["first"])
    t = " ".join(t.split())
    return t[:TITLE_MAX - 1].rstrip() + "…" if len(t) > TITLE_MAX else t


# Название по смыслу, а не состояние (владелец 19.11: «никаких непонятных автонаименований — по общему смыслу
# присваивать название»; пользователь фокус-ссылки: «Ожидание формулировки задачи» — это не название чата).
# Claude Code сам называет чат (``ai-title``) и переименовывает по ходу — пока задачи нет, получается статус.
STATUS = re.compile(r"^\W*(ожидани|ожида[ею]т|жд[её]т|приветстви|знакомств|начало (разговора|работы|сессии)|"
                    r"нов(ый|ая) (чат|разговор|сессия)|без (темы|названия)|пустой|greeting|waiting|awaiting|"
                    r"new (chat|conversation|session)|untitled|hello|introduction)", re.I)


def is_status(t: str) -> bool:
    return bool(STATUS.match(str(t or "")))


SMALL = frozenset({"и", "в", "во", "на", "с", "со", "к", "ко", "о", "об", "от", "для", "по", "за", "из", "у", "а",
                   "но", "или", "что", "как", "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with"})


def first_words(t: str, n: int = 5) -> str:
    """Первое сообщение человека — 3–5 слов, если в нём есть смысл (3 слова и больше): «привет» — не название.
    Предлог или союз в конце обрезаем («…кухни для» → «…кухни»)."""
    w = str(t or "").split()
    if len(w) < 3:
        return ""
    cut = w[:n]
    while len(cut) > 2 and cut[-1].lower().strip(".,:;!?") in SMALL:
        cut.pop()
    out = " ".join(cut).rstrip(".,:;!?")
    return out[:1].upper() + out[1:] + ("…" if len(w) > n else "")


def _head_title(f: Path, st, head: int) -> dict:
    key = str(f)
    old = _titles.get(key)
    if old and (old[0] == st.st_mtime_ns or (old[2] and st.st_size >= old[1])):
        return old[2]                               # журнал только дописывается — начало, а с ним название, то же
    summary, first, ai, meaning = "", "", "", ""
    try:
        with open(f, "rb") as fh:
            chunk = fh.read(head).decode("utf-8", "replace")
    except OSError:
        return {"ai": "", "summary": "", "first": ""}
    for line in chunk.splitlines():
        if '"summary"' not in line and '"user"' not in line and '"ai-title"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "ai-title" and e.get("aiTitle"):
            if not ai or not is_status(e["aiTitle"]):  # последнее название по смыслу; статус — только если другого нет
                ai = str(e["aiTitle"])
        elif e.get("type") == "summary" and e.get("summary"):
            summary = str(e["summary"])
        elif not meaning and e.get("type") == "user" and not e.get("isSidechain") and transcripts.is_real_prompt(e):
            text = transcripts.PASTED.sub("", transcripts.text_of(e["message"]["content"]))
            first = first or text
            meaning = text if len(text.split()) >= 3 else ""     # первое сообщение со смыслом («привет» — нет)
    t = {k: " ".join(v.split()) for k, v in (("ai", ai), ("summary", summary), ("first", first), ("meaning", meaning))}
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
