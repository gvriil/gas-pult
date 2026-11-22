"""«Проекты», закрепление, корзина чатов, название чата; «Проекты» пространства.

Часть класса ``webapp.Panel`` (модульный монолит, docs/MONOLITH-PLAN.md п.3.1): методы перенесены как есть, ``self`` —
тот же ``Panel``. ``NeedForce``, ``EFFORTS``, ``effort_flag`` переехали сюда же — ``webapp`` их реэкспортирует.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
import uuid
from pathlib import Path

from gas_pult import (
    chat_trash,
    chatmcp,
    harness,
    humanize,
    models,
    modules,
    projects,
    repos,
    router,
    space_projects,
    space_sessions,
    spaces,
    tenants,
    transcripts,
)


class NeedForce(ValueError):
    """Действие можно сделать только принудительно (фоновые задачи сессии): панель спросит и повторит с ``force``."""


EFFORTS = ("auto", "low", "medium", "high", "xhigh", "max")   # /effort <уровень> — Claude Code принимает аргументом


def effort_flag(level: str | None) -> str:
    """Усилие чата — флагом запуска ``--effort`` (Claude Code 2.1.328: low, medium, high, xhigh, max). «auto» и пусто —
    без флага: решает Claude Code. Флаг, а не ``/effort`` после запуска: команда в только что запущенное окно
    терялась (владелец 19.11: «усилия не выбираются»)."""
    return f" --effort {level}" if level in EFFORTS and level != "auto" else ""


class ProjectsPart:
    """«Проекты», закрепление, корзина чатов, название чата (примесь к ``Panel``)."""

    # ---------- «Проекты» (projects.py, docs/PROJECTS.md) ----------
    PROJECT_SYNC = 30                                   # с: как часто сверять проекты с папками и окнами

    def project_data(self, wins: list[dict] | None = None, fresh: bool = False) -> dict:
        """Проекты владельца и участников; сверка с папками и окнами (миграция, досоздание) — не чаще раза в 30 с."""
        if fresh or time.time() - self._proj[0] > self.PROJECT_SYNC or not self._proj[1]:
            if wins is None:
                wins = self.tmux.windows()
            d = self.projects.sync(self.pult.projects(), wins, self.pult.state().get("add_dirs"))
            self._proj = (time.time(), d)
        return self._proj[1]

    def pi_row(self, w: dict, sid: str) -> dict:
        """Окно Pi: статус хода, модель «поставщик/модель», свободный контекст и расход — из журнала Pi (не из строки
        статуса Claude Code и не лимиты подписки Claude)."""
        h = harness.of(w)
        f = h.journal(w["path"], sid=sid)
        st, u = h.status(f), h.usage(f)
        busy = st["phase"] in ("started", "working", "thinking")
        return {"status": "busy" if busy else "idle", "usage": u,
                "model": f"{u['provider']}/{u['model']}".strip("/") if u["model"] else getattr(h, "MODEL", ""),
                "context": None if u["used"] is None else max(0, round(100 - u["used"]))}

    def chat_title(self, d: dict, path: str, home, sid: str, h: harness.Harness | None = None) -> str:
        """Название чата окна: своё (``projects.json``) → ``summary`` журнала → первое сообщение человека.
        Журнал — через адаптер агента окна (R13): у Claude Code — ``title_of``, у Pi/OpenCode/Hermes — первое сообщение
        человека из их ленты."""
        if (own := ((d.get("sessions") or {}).get(sid) or {}).get("title")) if sid else None:
            return str(own)
        h = h or harness.of(None)
        f = h.journal(path, home, sid)
        if not f:
            return ""
        if h.name == harness.DEFAULT:
            return projects.title_of(f)
        first = next((m["text"] for m in h.history(path, 200, home=home, sid=sid)[0] if m.get("role") == "user"), "")
        return " ".join(str(first).split())[:projects.TITLE_MAX]

    def project_of(self, d: dict, w: dict) -> str:
        """Проект окна: окно пространства — его папка ``home/projects/<имя>`` (``s:<пространство>:<имя>``, GAS-38)."""
        if slug := w.get("space"):
            f = space_projects.folder_of(slug, w.get("path", ""))
            return space_projects.pid_of(slug, f) if f else ""
        return self.projects.of_path(d, w.get("path", "")) or ""

    def claude_homes(self) -> list:
        """Папки Claude Code, где могут лежать журналы сессий проекта: владельца (None) и участников."""
        out: list = [None]
        base = self.cfg.data / "people"
        with contextlib.suppress(OSError):
            out += sorted(x / "claude" for x in base.iterdir() if (x / "claude" / "projects").is_dir())
        return out

    def project_public(self, p: dict, who: str | None = "owner") -> dict:
        """Поля проекта для API (без личных путей: путь — с ``~``). ``pinned`` — закреплён ли у ``who``."""
        at = int(projects.pins_of(self.project_data(), who)[0].get(p["id"]) or 0)
        keys = ("id", "name", "path", "paths", "origin", "created", "profile", "model", "effort", "integrations",
                "repos", "pinned", "archived", "share")
        return {**{k: p.get(k) for k in keys}, "folder": os.path.basename(p["path"].rstrip("/")) or "~",
                "pinned": bool(at), "pinned_at": at}           # закреплён этим человеком и когда (добавлено)

    def projects_list(self, ss: list[dict], q: str = "", archived: bool = False,
                      who: str | None = "owner") -> list[dict]:
        """Список проектов для главной: счётчики окон (ждут ответа / работают / всего), чатов в журналах, последняя
        активность и название последнего чата. ``ss`` — готовые сессии: статусы не считаем заново."""
        d = self.project_data()
        meta = d.get("sessions") or {}
        homes = self.claude_homes()
        by: dict[str, list[dict]] = {}
        for x in ss:
            if x.get("project"):
                by.setdefault(x["project"], []).append(x)
        q = " ".join(str(q or "").lower().split())
        out = []
        for pid, p in d["projects"].items():
            mine = by.get(pid, [])
            folders = self.projects.folders_of(p)
            if not mine and not any(os.path.isdir(f) for f in folders):
                continue                                  # папку удалили — проект не показываем (запись остаётся)
            if bool(p.get("archived")) != archived:
                continue
            st = projects.stats([f for f in projects.session_files(folders, homes)     # скрытые и удалённые — не в счёт
                                 if not (meta.get(f.stem) or {}).get("hidden")])
            last = max([st["last"] or 0, *[int(x.get("changed") or 0) for x in mine]]) or None
            lf = st["last_file"]
            win = next((x for x in mine if lf and x.get("sid") == lf.stem), None)
            item = {**self.project_public(p, who),
                    "windows": len(mine),
                    "waiting": sum(x["status"] == "dialog" for x in mine),
                    "busy": sum(x["status"] == "busy" for x in mine),
                    "chats": st["total"], "last": last,
                    "last_title": (str((meta.get(lf.stem) or {}).get("title") or "") or projects.title_of(lf))
                    if lf else "",
                    "last_window": (win or {}).get("name", ""),   # последний чат открыт в окне — его имя (добавлено)
                    "sessions": [x["id"] for x in mine]}
            if q and not any(q in str(v).lower() for v in (item["name"], item["folder"], item["last_title"],
                                                            *[x.get("name", "") for x in mine])):
                continue
            out.append(item)
        # закреплённые — сверху, последний закреплённый первым; остальные — как раньше
        out.sort(key=lambda x: (not x["pinned"], -x["pinned_at"], not x["waiting"], -(x["last"] or 0),
                                x["name"].lower()))
        return out

    def project(self, pid: str) -> dict:
        p = self.project_data()["projects"].get(str(pid or ""))
        if not p:
            raise LookupError("проекта нет — обновите список")
        return p

    def route(self, text: str, uid=None) -> dict:
        """Подсказка модели для первого сообщения нового чата (router.py): только среди готовых профилей."""
        ready = {p["id"] for p in models.public(self.pult.state(), None if uid is None else self.countries(uid))
                 if (not p.get("needs_key") or p.get("key")) and not p.get("not_ready") and not p.get("no_balance")
                 and p.get("allowed") is not False}
        return {"route": router.route(text, ready)}

    def project_session(self, pid: str, profile: str = "", person: int | None = None, uid=None,
                        model: str = "", mcp_off: list | None = None, effort: str = "") -> dict:
        """«Новая сессия в проекте»: ещё одно окно в главной папке проекта, даже если там уже работает чат — у каждого
        свой журнал (``--session-id``). Поставщик и модель — по умолчанию проекта, если не выбраны."""
        p = self.project(pid)
        path = projects.untilde(p["path"], self.pult.home)
        if not os.path.isdir(path):
            raise ValueError("папки проекта нет на сервере")
        profile = profile or p.get("profile") or ""
        if uid is not None:
            self.check(profile, uid)
        out = self.open_in(path, profile, person, uid, model=router.valid_model(model) or p.get("model") or "",
                           mcp_off=chatmcp.norm(mcp_off) if mcp_off else None,
                           effort=effort if effort in EFFORTS else "")
        return {**out, "project": p["id"]}

    INSTR_MAX = 20000

    def project_new(self, name: str, folder: str = "", instructions: str = "", profile: str = "", model: str = "",
                    person: int | None = None) -> dict:
        """«Новый проект» (панель чатов → «Проекты» → «+»): папка в первом корне проектов с ``git init`` — как «Новая
        папка» (``Pult.make_folder``), ``CLAUDE.md`` из инструкций, запись в ``projects.json`` с поставщиком и моделью
        по умолчанию. Окно не открываем: чат запустится при первой отправке (``/api/project/session``). Папка уже
        есть — отказ, на диске ничего не трогаем."""
        name = " ".join(str(name or "").split())[:projects.NAME_MAX]
        if not name:
            raise ValueError("назовите проект")
        folder = str(folder or "").strip().lower() or projects.folder_of(name)
        if not projects.FOLDER_OK.match(folder):
            raise ValueError("имя папки: латиница в нижнем регистре, цифры, дефис (2–41 знак), без «/» и «..»")
        if profile and profile not in models.BY_ID:
            raise ValueError("такого поставщика нет")
        if model and model not in self.cfg.models:
            raise ValueError("такой модели нет в настройках (models)")
        instructions = str(instructions or "").strip()
        if len(instructions) > self.INSTR_MAX:
            raise ValueError(f"инструкции длиннее {self.INSTR_MAX} знаков — сократите")
        root = self.pult.module_root()
        try:
            path = self.pult.make_folder(folder)
        except FileExistsError:
            raise ValueError(f"папка «{folder}» уже есть в {projects.tilde(str(root), self.pult.home)} — выберите "
                             "другое название или имя папки") from None
        if instructions:
            (path / "CLAUDE.md").write_text(instructions + "\n", encoding="utf-8")
        pid = self.projects.create(str(path), name, by=person, profile=profile, model=model)
        self._proj = (0.0, {})
        return {"id": pid, "name": name, "folder": path.name, "path": projects.tilde(str(path), self.pult.home)}

    def project_update(self, pid: str, name=None, archived=None) -> dict:
        """Меню проекта «⋯» (GAS-24, перенесено из папки фокуса): название и архив — только в ``projects.json``."""
        p = self.project(pid)
        if name is not None:
            name = " ".join(str(name).split())[:projects.TITLE_MAX]
            if not name:
                raise ValueError("название пустое")
        rec = self.projects.set_project(p["id"], name=name, archived=None if archived is None else bool(archived))
        self._proj = (0.0, {})
        return {"id": p["id"], "name": rec.get("name"), "archived": bool(rec.get("archived"))}

    # ---------- «Закрепить» проект, сессию и чат — свои у каждого человека (projects.json → pins[кто]) ----------
    def pin_key(self, w: dict, sid: str = "") -> str:
        """Ключ закрепления окна: id сессии Claude Code (переживает перезапуск с продолжением и «Продолжить»);
        старое окно без метки — его папка."""
        if sid := transcripts.valid_sid(sid or w.get("sid")):
            return "sid:" + sid
        return "path:" + projects.tilde(os.path.realpath(w.get("path") or ""), self.pult.home)

    def pinned_of(self, d: dict, w: dict, sid: str = "", who: str | None = "owner") -> int:
        return int(projects.pins_of(d, who)[1].get(self.pin_key(w, sid)) or 0)

    def pin(self, who: str, on: bool, project: str = "", wid: str = "", pid: str = "", sid: str = "") -> dict:
        """«Закрепить» / «Открепить»: проект (``project``), окно сессии (``wid``) или завершённый чат (``pid`` +
        ``sid``). Свои у каждого человека (``who``); хранится на сервере — одинаково на телефоне и в браузере."""
        if project:
            self.project(project)
            ts = self.projects.set_pin(who, on, pid=project)
        elif wid:
            w = self.tmux.window(wid)
            if not w or w.get("space") or not (harness.is_agent(w) or w.get("stopped")):
                raise LookupError("окна уже нет")
            ts = self.projects.set_pin(who, on, key=self.pin_key(w))
        else:
            f = self.chat_file(self.project(pid), sid)
            ts = self.projects.set_pin(who, on, key="sid:" + f.stem)
        self._proj = (0.0, {})
        return {"pinned": ts}

    def project_files(self, p: dict) -> list[Path]:
        return projects.session_files(self.projects.folders_of(p), self.claude_homes())

    def chat_file(self, p: dict, sid: str) -> Path:
        """Журнал чата проекта по id — только среди журналов этого проекта (id — uuid, путь не подставить)."""
        sid = transcripts.valid_sid(sid)
        f = next((f for f in self.project_files(p) if sid and f.stem == sid), None)
        if not f:
            raise LookupError("чата нет — Claude Code мог удалить старый журнал")
        return f

    def open_sids(self, p: dict) -> tuple[dict, set]:
        """Окна проекта: id сессии → окно; журналы окон без метки (последний журнал их папки) — тоже заняты."""
        d = self.project_data()
        by_sid, legacy = {}, set()
        for w in self.tmux.windows():
            if w.get("space") or not (harness.is_agent(w) or w.get("mark")):
                continue
            if self.projects.of_path(d, w.get("path", "")) != p["id"]:
                continue
            if sid := transcripts.valid_sid(w.get("sid")):
                by_sid[sid] = w
            elif f := harness.of(w).journal(w["path"], self.pult.home_of(w)):     # R13: журнал — у агента окна
                legacy.add(str(f))
        return by_sid, legacy

    def keep_days(self) -> int:
        """Сколько дней Claude Code хранит журналы (``cleanupPeriodDays`` владельца, по умолчанию 30). Только читаем."""
        with contextlib.suppress(OSError, ValueError, TypeError):
            v = json.loads((Path.home() / ".claude" / "settings.json").read_text()).get("cleanupPeriodDays")
            if isinstance(v, int) and v > 0:
                return v
        return 30

    def my_claude(self, person: int | None) -> Path:
        """Папка Claude Code того, кто спрашивает (не создаётся): владелец — ``~/.claude``."""
        if person is None:
            return transcripts.CLAUDE_PROJECTS.parent
        return self.cfg.data / "people" / str(person) / "claude"

    CHATS_PAGE = 20
    SEARCH_FILES, SEARCH_SECS = 300, 2.0                 # поиск по тексту журналов — не дольше и не больше этого

    def project_chats(self, pid: str, q: str = "", before: float | None = None, person: int | None = None) -> dict:
        """Завершённые чаты проекта (журналы без окна): название, когда, сколько сообщений; новые сверху, страницами.
        ``q`` — по названию, затем по тексту журналов (с лимитом файлов и времени). Закрепления — свои у ``person``
        (None — владельца)."""
        p = self.project(pid)
        who = "owner" if person is None else str(person)
        meta = self.project_data().get("sessions") or {}
        by_sid, legacy = self.open_sids(p)
        mine = self.my_claude(person)
        files = []                                       # (когда последнее сообщение, время файла, журнал)
        for f in self.project_files(p):
            with contextlib.suppress(OSError):
                files.append((projects.last_said(f), f.stat().st_mtime, f))
        files.sort(key=lambda x: (-x[0], -x[1]))         # по последнему сообщению: служебные записи — не «только что»
        q = " ".join(str(q or "").lower().split())
        pins = projects.pins_of(self.project_data(), who)[1]
        files = [(at, mt, f) for at, mt, f in files
                 if not (f.stem in by_sid or str(f) in legacy or (meta.get(f.stem) or {}).get("hidden"))]
        top = []                                          # закреплённые — сверху первой страницы, не по времени
        for at, mt, f in files if before is None else []:
            if pin := int(pins.get("sid:" + f.stem) or 0):
                title = str((meta.get(f.stem) or {}).get("title") or "") or projects.title_of(f)
                if title and (not q or q in title.lower()):
                    top.append({"sid": f.stem, "title": title, "mtime": int(mt), "last": at or int(mt),
                                "msgs": projects.prompts(f), "mine": f.parent.parent.parent == mine, "pinned": pin})
        out, scanned, t0, cut = [], 0, time.time(), False
        for at, mt, f in files:
            if pins.get("sid:" + f.stem) or (before is not None and (at or int(mt)) >= before):
                continue
            title = str((meta.get(f.stem) or {}).get("title") or "") or projects.title_of(f)
            if not title:
                continue                                  # журнал без единого сообщения человека — не чат
            if q and q not in title.lower():
                if scanned >= self.SEARCH_FILES or time.time() - t0 > self.SEARCH_SECS:
                    cut = True
                    continue
                scanned += 1
                if not projects.contains(f, q):
                    continue
            own = f.parent.parent.parent == mine
            out.append({"sid": f.stem, "title": title, "mtime": int(mt), "msgs": projects.prompts(f), "mine": own,
                        "pinned": 0, "last": at or int(mt)})    # last — время последнего сообщения (добавлено)
            if len(out) >= self.CHATS_PAGE:
                break
        more = bool(out) and len(out) >= self.CHATS_PAGE
        top.sort(key=lambda x: -x["pinned"])
        return {"chats": top + out, "more": more, "before": out[-1]["last"] if more else None, "cut": cut,
                "keep_days": self.keep_days(), "active": len(by_sid) + len(legacy)}

    def project_history(self, pid: str, sid: str, before: int | None = None) -> dict:
        """Переписка завершённого чата без окна — окно открывается только по «Продолжить»."""
        p = self.project(pid)
        f = self.chat_file(p, sid)
        items, more = transcripts.history("", 30, before, file=f)
        for it in items:
            if it.get("role") == "assistant" and (h := humanize.error(it.get("text") or "", strict=True)):
                it["human"] = h
        meta = (self.project_data().get("sessions") or {}).get(f.stem) or {}
        return {"items": items, "more": more, "title": meta.get("title") or projects.title_of(f), "sid": f.stem}

    def project_resume(self, pid: str, sid: str, person: int | None = None, uid=None) -> dict:
        """«Продолжить»: новое окно в папке чата с ``--resume <id>``; чат уже открыт — его окно. Продолжить можно
        только свой чат (журнал в своей папке Claude Code): чужая учётка — не наша."""
        p = self.project(pid)
        f = self.chat_file(p, sid)
        by_sid, _ = self.open_sids(p)
        if w := by_sid.get(f.stem) or self.sid_owner(f.stem, running=True):   # чат уже идёт — его окно
            return {"id": w["id"], "existing": True, "sid": f.stem}     # активное окно бота не меняем (#179)
        mine = self.my_claude(person)
        if f.parent.parent.parent != mine:
            raise ValueError("этот чат вёлся на другой учётке Claude — продолжить его может только её хозяин")
        folder = next((x for x in self.projects.folders_of(p)
                       if transcripts.project_dir(x, None if person is None else mine).name == f.parent.name),
                      projects.untilde(p["path"], self.pult.home))
        profile = p.get("profile") or ""
        if uid is not None:
            self.check(profile, uid)
        return {**self.open_in(folder, profile, person, uid, resume=f.stem, model=p.get("model") or ""),
                "project": p["id"]}

    def set_title(self, w: dict, title) -> dict:
        """Своё название чата окна (GAS-13 п.3; фокус-пользователь 19.11: «мне нужно переименовать вторую часть»):
        хранится в ``projects.json`` по id разговора, автоматика его не перетирает; пустое — снова авто (summary
        журнала). Имя окна tmux не меняется."""
        sid = transcripts.valid_sid(self.follow_sid(w, self.tmux.windows(), self.pult.home_of(w)))
        if not sid:
            raise ValueError("у этой сессии ещё нет разговора — напишите первое сообщение, потом переименуйте")
        title = " ".join(str(title or "").split())[:projects.TITLE_MAX]
        pd = self.project_data()
        self.projects.set_chat(sid, self.project_of(pd, w), title=title)
        self._proj = (0.0, {})
        return {"title": title or self.chat_title(self.project_data(fresh=True), w["path"], self.pult.home_of(w), sid,
                                                  harness.of(w)),
                "own": bool(title)}

    def project_chat(self, pid: str, sid: str, title=None, hidden=None) -> dict:
        """Переименовать или скрыть чат проекта — только в ``projects.json``; журнал Claude Code не меняется."""
        p = self.project(pid)
        f = self.chat_file(p, sid)
        if title is not None:
            title = " ".join(str(title).split())[:projects.TITLE_MAX]
        rec = self.projects.set_chat(f.stem, p["id"], title=title, hidden=None if hidden is None else bool(hidden))
        self._proj = (0.0, {})
        return rec

    def sid_owner(self, sid, skip: str = "", wins: list[dict] | None = None, running: bool = False) -> dict | None:
        """Другое окно (не ``skip``), где этот разговор: id у живого процесса Claude или метка остановленного окна.
        ``running`` — только окна, где Claude сейчас работает. Два процесса на один журнал пишут вперемешку: ответы
        одного окна видны в другом (#178) — поэтому второй раз один разговор не запускаем и журнал не уносим."""
        sid = transcripts.valid_sid(sid)
        if not sid:
            return None
        for x in self.tmux.windows() if wins is None else wins:
            if x["id"] == skip or x.get("space") or transcripts.valid_sid(x.get("sid")) != sid:
                continue
            if harness.is_agent(x) or (x.get("stopped") and not running):
                return x
        return None

    def busy_sid(self, sid, skip: str = ""):
        """Разговор уже идёт в другом окне — понятный отказ вместо второго процесса на тот же журнал."""
        if o := self.sid_owner(sid, skip, running=True):
            raise ValueError(f"этот разговор уже открыт в окне «{o['name']}» — откройте его там; второй запуск "
                             "смешал бы ответы двух окон")

    # ---------- «Удалить» сессию или чат: окно закрыто, журнал — в корзину пульта (chat_trash.py) ----------
    def session_window(self, wid: str) -> dict:
        """Окно сессии пульта для «Завершить»/«Удалить»: с Claude или остановленное (Claude вышел, осталась
        оболочка). Остальные окна tmux владельца (просто терминалы) не трогаем."""
        w = self.tmux.window(str(wid or ""))
        if not w or not (harness.is_agent(w) or w.get("stopped")):
            raise LookupError("окна уже нет")
        return w

    def window_journal(self, w: dict) -> Path | None:
        """Журнал окна: по метке ``@gas_pult_sid``; старое окно без метки — последний журнал папки, но только если
        других окон Claude в этой папке нет (иначе можно унести чужой разговор)."""
        home, h = self.pult.home_of(w), harness.of(w)          # R13: журнал — у агента окна (Pi, OpenCode, Hermes)
        if sid := transcripts.valid_sid(w.get("sid")):
            return h.journal(w["path"], home, sid)
        real = os.path.realpath(w["path"])
        if any(x["id"] != w["id"] and (harness.is_agent(x) or x.get("stopped"))
               and os.path.realpath(x.get("path", "")) == real for x in self.tmux.windows()):
            return None
        return h.journal(w["path"], home)

    def chat_delete(self, wid: str = "", pid: str = "", sid: str = "", force: bool = False) -> dict:
        """«Удалить»: окно сессии (``wid``) или завершённый чат проекта (``pid`` + ``sid``). Окно закрывается (Claude
        выходит штатно; не вышел за 20 с — окно закрываем, разговор уже в журнале), журнал — в корзину пульта, чат
        помечается скрытым в ``projects.json``: после обновления и перезапуска не возвращается. «Вернуть» —
        ``chat_restore``. Фоновые задачи в окне — не удаляем: решить в самом окне."""
        d = self.project_data(fresh=True)
        f: Path | None = None
        w = self.session_window(wid) if wid else None
        if w is None:
            p = self.project(pid)
            f = self.chat_file(p, sid)
            w = self.open_sids(p)[0].get(f.stem)            # чат ещё открыт в окне — закрыть и его
        else:
            f = self.window_journal(w)
        draft = ""
        if w:
            if harness.is_agent(w):
                r = self.pult.quit_ex(w)
                draft = r["draft"]
                if r["result"] == "background" and not force:
                    raise NeedForce("не удалил: у сессии есть фоновые задачи — «Удалить принудительно» остановит их")
                if r["result"] in ("busy", "background") and self.tmux.window(w["id"]):
                    self.tmux.kill(w["id"])
            else:
                self.tmux.kill(w["id"])
            self.focus.end_window(w["id"])                  # фокус-ссылки этой сессии гаснут
            if (sch := self.schedule_of(w["path"])) and sch.get("state") == "on":
                modules.set_schedule(Path(w["path"]), "paused")   # иначе расписание снова откроет удалённую сессию
        out = {"result": "удалено", "closed": bool(w), "draft": draft, "trash": None,
               **({"schedule": "paused"} if w and (self.schedule_of(w["path"]) or {}).get("state") == "paused" else {})}
        if f and (o := self.sid_owner(f.stem, (w or {}).get("id", ""))):
            out["kept"] = o["name"]                          # журнал открыт в другом окне — его разговор не уносим
            return out
        if f and f.is_file():
            pid = (w and self.project_of(d, w)) or pid
            meta = (d.get("sessions") or {}).get(f.stem) or {}
            title = str(meta.get("title") or "") or projects.title_of(f) or (w or {}).get("name", "")
            out["trash"] = chat_trash.put(self.cfg.data, f, title, pid)
            self.projects.set_chat(f.stem, pid, hidden=True)
            self._proj = (0.0, {})
        return out

    def chat_trash_list(self) -> dict:
        """Корзина чатов и скрытые чаты (их журнал на месте) — для «Корзина» в панели."""
        d = self.project_data()
        chat_trash.purge(self.cfg.data)                 # старше 30 дней — в списке не показываем, стираем сразу
        items = chat_trash.listing(self.cfg.data)
        gone = {x["sid"] for x in items}
        hidden = []
        for sid, rec in (d.get("sessions") or {}).items():
            if rec.get("hidden") and sid not in gone and rec.get("project") in d["projects"]:
                p = d["projects"][rec["project"]]
                with contextlib.suppress(LookupError):
                    f = self.chat_file(p, sid)
                    hidden.append({"sid": sid, "project": p["id"], "project_name": p["name"],
                                   "title": str(rec.get("title") or "") or projects.title_of(f)})
        names = {pid: p["name"] for pid, p in d["projects"].items()}
        return {"trash": [{**x, "project_name": names.get(x["project"], "")} for x in items], "hidden": hidden,
                "keep_days": chat_trash.KEEP_DAYS, "warn_days": chat_trash.WARN_DAYS}   # добавлено

    TRASH_EVERY = 3600                                  # с: как часто фоновый цикл чистит корзину чатов

    def trash_tick(self, now: float | None = None) -> list[str]:
        """Из фонового цикла панели (раз в минуту): не чаще раза в час — окончательно удалить из корзины чатов
        записи старше ``chat_trash.KEEP_DAYS``. Первый вызов после запуска — сразу."""
        now = time.time() if now is None else now
        if now - self._trash_at < self.TRASH_EVERY:
            return []
        self._trash_at = now
        gone = chat_trash.purge(self.cfg.data, now)
        if gone:
            print(f"корзина чатов: удалено окончательно {len(gone)} (старше {chat_trash.KEEP_DAYS} дн.)", flush=True)
        return gone

    def chat_restore(self, tid: str) -> dict:
        """«Вернуть» из корзины: журнал — на место, чат снова в «Завершённых» своего проекта."""
        rec = chat_trash.restore(self.cfg.data, tid)
        self.projects.set_chat(rec["sid"], rec["project"], hidden=False)
        self._proj = (0.0, {})
        return rec

    INSTR_MAX = 20000                                   # знаков CLAUDE.md в ответе: больше — обрезаем с пометкой
    FILES_MAX = 200

    def project_info(self, pid: str, who: str | None = "owner") -> dict:
        """Проект: настройки, инструкции (``CLAUDE.md`` главной папки), файлы проекта, окна."""
        d = self.project_data()
        p = d["projects"].get(str(pid or ""))
        if not p:
            raise LookupError("проекта нет — обновите список")
        root = Path(projects.untilde(p["path"], self.pult.home))
        text, cut = "", False
        with contextlib.suppress(OSError):
            raw = (root / "CLAUDE.md").read_text(encoding="utf-8", errors="replace")
            text, cut = raw[:self.INSTR_MAX], len(raw) > self.INSTR_MAX
        files = []
        fdir = root / (p.get("files") or "files")
        with contextlib.suppress(OSError):
            for f in sorted(fdir.iterdir(), key=lambda x: x.name.lower()):
                if f.is_file() and not f.name.startswith("."):
                    st = f.stat()
                    files.append({"name": f.name, "size": st.st_size, "mtime": int(st.st_mtime)})
                if len(files) >= self.FILES_MAX:
                    break
        homes = self.claude_homes()
        st = projects.stats(projects.session_files(self.projects.folders_of(p), homes))
        wins = [w["id"] for w in self.tmux.windows() if not w.get("space") and (harness.is_agent(w) or
                                                                               w.get("mark"))
                and self.projects.of_path(d, w.get("path", "")) == p["id"]]
        return {**self.project_public(p, who), "instructions": text, "instructions_cut": cut,
                "has_instructions": bool(text), "files": files, "files_dir": p.get("files") or "files",
                "chats": st["total"], "last": st["last"], "windows": wins}

    # ---------- «Проекты» пространства (GAS-38 п.1, space_projects.py): папки home/projects/<имя> ----------
    def sp_windows(self, slug: str) -> list[dict]:
        """Окна пространства — и владельцу, и тестировщику (без ограничения запроса)."""
        return self.tmux.space(slug).windows()

    def space_projects_list(self, slug: str, ss: list[dict], q: str = "") -> list[dict]:
        """Проекты пространства для главной — в тех же полях, что ``projects_list`` у владельца. ``ss`` — готовые
        сессии (свои окна пространства уже с полем ``project``)."""
        if not tenants.enabled():
            return []
        title = (tenants.load(slug) or {}).get("title") or slug
        root = space_sessions.projects(slug)
        q = " ".join(str(q or "").lower().split())
        out = []
        for row in space_projects.listing(slug):
            pid = space_projects.pid_of(slug, row["folder"])
            mine = [x for x in ss if x.get("project") == pid]
            st = space_projects.stats(slug, root / row["folder"])
            lf = st["last_file"]
            win = next((x for x in mine if lf and x.get("sid") == lf.stem), None)
            item = {**space_projects.public(slug, row["folder"], title),
                    "windows": len(mine), "waiting": sum(x["status"] == "dialog" for x in mine),
                    "busy": sum(x["status"] == "busy" for x in mine), "chats": st["total"],
                    "last": max([st["last"] or 0, row["changed"], *[int(x.get("changed") or 0) for x in mine]]) or None,
                    "last_title": projects.title_of(lf) if lf else "", "last_window": (win or {}).get("name", ""),
                    "sessions": [x["id"] for x in mine]}
            if q and not any(q in str(v).lower() for v in (item["name"], item["last_title"],
                                                            *[x.get("name", "") for x in mine])):
                continue
            out.append(item)
        out.sort(key=lambda x: (not x["waiting"], -(x["last"] or 0), x["name"].lower()))
        return out

    def owner_space_projects(self, ss: list[dict]) -> list[dict]:
        """Владельцу и админу — проекты всех готовых пространств (группа «Пространства»). Сбой одного пространства
        (tmux, диск) не мешает остальным."""
        out, slugs = [], getattr(self.tmux, "_slugs", None)      # готовые пространства (spaces.Routed)
        for slug in slugs() if slugs else []:
            try:
                out += [{**x, "name": f"{x['space_title']} · {x['name']}"}   # чьё пространство — в названии
                        for x in self.space_projects_list(slug, ss)]
            except (RuntimeError, OSError, ValueError) as e:
                print(f"пространство {slug}: проекты не прочитались: {e}", file=sys.stderr, flush=True)
        return out

    def space_project_info(self, pid: str, allowed: str | None) -> dict:
        slug, folder, path = space_projects.parse(pid, allowed)
        if folder not in {x["folder"] for x in space_projects.listing(slug)}:
            raise LookupError(space_projects.NOT_FOUND)
        text = space_projects.instructions(slug, path)
        st = space_projects.stats(slug, path)
        wins = [w["id"] for w in self.sp_windows(slug) if space_projects.folder_of(slug, w.get("path", "")) == folder
                and (harness.is_agent(w) or w.get("mark"))]
        title = (tenants.load(slug) or {}).get("title") or slug
        return {**space_projects.public(slug, folder, title), "instructions": text[:self.INSTR_MAX],
                "instructions_cut": len(text) > self.INSTR_MAX, "has_instructions": bool(text), "files": [],
                "files_dir": "", "chats": st["total"], "last": st["last"], "windows": wins}

    def space_project_chats(self, pid: str, allowed: str | None, q: str = "", before: float | None = None) -> dict:
        """Завершённые чаты проекта пространства — как ``project_chats``: журналы без окна, новые сверху, страницами."""
        slug, folder, path = space_projects.parse(pid, allowed)
        if folder not in {x["folder"] for x in space_projects.listing(slug)}:
            raise LookupError(space_projects.NOT_FOUND)
        by_sid, legacy = space_projects.open_sids(slug, path, self.sp_windows(slug))
        files = []
        for f in space_projects.chat_files(slug, path):
            with contextlib.suppress(OSError):
                if f.stem not in by_sid and str(f) not in legacy:
                    files.append((projects.last_said(f), f.stat().st_mtime, f))
        files.sort(key=lambda x: (-x[0], -x[1]))
        q = " ".join(str(q or "").lower().split())
        out, scanned, t0, cut = [], 0, time.time(), False
        for at, mt, f in files:
            if before is not None and (at or int(mt)) >= before:
                continue
            title = projects.title_of(f)
            if not title:
                continue
            if q and q not in title.lower():
                if scanned >= self.SEARCH_FILES or time.time() - t0 > self.SEARCH_SECS:
                    cut = True
                    continue
                scanned += 1
                if not projects.contains(f, q):
                    continue
            out.append({"sid": f.stem, "title": title, "mtime": int(mt), "msgs": projects.prompts(f), "mine": True,
                        "pinned": 0, "last": at or int(mt)})
            if len(out) >= self.CHATS_PAGE:
                break
        more = bool(out) and len(out) >= self.CHATS_PAGE
        return {"chats": out, "more": more, "before": out[-1]["last"] if more else None, "cut": cut,
                "keep_days": self.keep_days(), "active": len(by_sid) + len(legacy)}

    def space_project_history(self, pid: str, allowed: str | None, sid: str, before: int | None = None) -> dict:
        slug, _folder, path = space_projects.parse(pid, allowed)
        f = space_projects.chat_file(slug, path, sid)
        items, more = transcripts.history("", 30, before, file=f)
        for it in items:
            if it.get("role") == "assistant" and (h := humanize.error(it.get("text") or "", strict=True)):
                it["human"] = h
        return {"items": items, "more": more, "title": projects.title_of(f), "sid": f.stem}

    def space_project_open(self, slug: str, folder: str, path: Path, args: str, sid: str) -> str:
        """Окно пространства в папке проекта; метка разговора — чтобы чат знал свой журнал."""
        if folder not in {x["folder"] for x in space_projects.listing(slug, fresh=True)}:
            raise LookupError(space_projects.NOT_FOUND)
        args = (repos.flags(self.pult.state(), str(path)) + " " + args).strip()   # подключённые репозитории
        raw = tenants.new_window(slug, folder, str(path), args=args)
        with contextlib.suppress(RuntimeError, OSError):
            tenants.tmux_of(slug).set_sid(raw, sid)
        self.space_claude_check(slug, raw)
        return raw

    def space_project_session(self, pid: str, allowed: str | None, effort: str = "") -> dict:
        """«Новый чат в проекте»: ещё одно окно пространства в ЭТОЙ папке, свой журнал (``--session-id``)."""
        if not tenants.enabled():
            raise ValueError("демо-пространство ещё не готово — владелец пульта включит его")
        slug, folder, path = space_projects.parse(pid, allowed)
        sid = str(uuid.uuid4())
        raw = self.space_project_open(slug, folder, path, f"--session-id {sid}{effort_flag(effort)}", sid)
        return {"id": spaces.wid_of(slug, raw), "sid": sid, "project": pid}

    def space_project_resume(self, pid: str, allowed: str | None, sid: str) -> dict:
        """«Продолжить» завершённый чат проекта пространства (``--resume``); уже открыт — его окно."""
        slug, folder, path = space_projects.parse(pid, allowed)
        f = space_projects.chat_file(slug, path, sid)
        by_sid, legacy = space_projects.open_sids(slug, path, self.sp_windows(slug))
        if w := by_sid.get(f.stem):
            return {"id": w["id"], "existing": True, "sid": f.stem}
        if str(f) in legacy:
            raise ValueError("этот чат уже открыт — откройте его в списке активных")
        raw = self.space_project_open(slug, folder, path, f"--resume {f.stem}", f.stem)
        return {"id": spaces.wid_of(slug, raw), "sid": f.stem, "project": pid}

    def space_project_new(self, slug: str, name: str, instructions: str = "") -> dict:
        """«Новый проект» тестировщика: папка ``home/projects/<название>``; чат — при первой отправке."""
        if not tenants.enabled():
            raise ValueError("демо-пространство ещё не готово — владелец пульта включит его")
        name = " ".join(str(name or "").split())
        if not name:
            raise ValueError("назовите проект")
        path = space_projects.create(slug, name, instructions)
        return {"id": space_projects.pid_of(slug, path.name), "name": path.name, "folder": path.name,
                "path": "projects/" + path.name}
