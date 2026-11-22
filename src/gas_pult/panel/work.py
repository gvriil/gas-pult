"""Задачи, брифинг, команды из ответов, окно терминала, модули-агенты, репозитории GitHub в сессии.

Часть класса ``webapp.Panel`` (модульный монолит, docs/MONOLITH-PLAN.md п.3.1): методы перенесены как есть, ``self`` —
тот же ``Panel``. ``utc_now`` переехала сюда же — ``webapp`` её реэкспортирует.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from gas_pult import brief as morning_brief  # «brief» в webapp — «Кратко» для озвучки
from gas_pult import harness, modules, repos, termwin, transcripts
from gas_pult.commands import DANGER, FULL, SPACE_RUN, TAIL, execute, extract, in_space
from gas_pult.humanize import DIALOG


def utc_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime())


class WorkPart:
    """Задачи, брифинг, команды из ответов, окно терминала, модули-агенты, репозитории (примесь к ``Panel``)."""

    # ---------- модули-агенты (modules.py) ----------
    def modules_list(self) -> dict:
        """Каталог модулей для «Новое пространство → Из модуля»: имя папки по умолчанию — свободное."""
        root, errors = self.pult.module_root(), []
        items = [{**modules.public(m), "folder": modules.free_name(root, m["id"]),
                  "existing": self.module_spaces(m["id"])} for m in modules.catalog(errors)]
        return {"modules": items, "root": self.pult.short(str(root)), "errors": errors}

    def module_spaces(self, mid: str) -> list[dict]:
        """Пространства модуля, которые уже есть: папка, последнее изменение, номер в списке папок (для /api/new),
        открытое окно — если есть."""
        dirs = self.pult.projects()
        out = []
        for x in modules.existing(self.pult.module_root(), mid):
            p = str(x["path"])
            w = self.pult.project_window(p)
            out.append({"folder": x["folder"], "path": self.pult.short(p), "changed": x["changed"],
                        "i": dirs.index(p) if p in dirs else None, "open": w["id"] if w else None,
                        "schedule": self.schedule_of(p)})
        return out

    def module_create(self, mid: str, name: str, profile: str = "", person: int | None = None, uid=None,
                      lang: str = "", again: bool = False) -> dict:
        """Пространство из модуля: папка в первом корне проектов → сессия в ней (как «Новая сессия») → первое
        задание модуля, когда Claude будет готов. Проверки — до создания папки, чтобы не оставлять пустых.
        ``lang`` (ru, en) — из простого режима: язык ответов агента в настройках Claude Code пространства.
        Пространство этого модуля уже есть — без ``again`` (человек подтвердил «Создать ещё одно») не создаём."""
        if name:
            modules.check_name(name)                   # неверное имя — сразу, до вопроса «уже есть»
        if not again and (have := modules.existing(self.pult.module_root(), mid)):
            raise ValueError(f"пространство «{have[0]['folder']}» этого модуля уже есть — откройте его или "
                             "подтвердите «Создать ещё одно»")
        if uid is not None:
            self.check(profile, uid)
        self.need_claude()
        path = modules.create(mid, self.pult.module_root(), name, by=person, lang=lang)
        out = self.new(self.pult.projects().index(str(path)), profile, person, uid)
        self.pult.send_later(out["id"], modules.get(mid)["start"])
        return {**out, "path": self.pult.short(str(path)), "folder": path.name}

    def sections_of(self, path: str) -> list[str]:
        """Разделы (Поиск, Цифры, Бумаги, Общение) модуля пространства — по каталогу, раз в минуту."""
        mk = modules.mark_of(Path(path))
        if not mk:
            return []
        if time.time() - self.mod_sections[0] > 60:
            self.mod_sections = (time.time(), {m["id"]: m["sections"] for m in modules.catalog()})
        return list(self.mod_sections[1].get(str(mk.get("id")), []))

    def schedule_of(self, path: str, now: datetime | None = None) -> dict | None:
        """Расписание пространства из модуля (задача 39): состояние on/paused/off, «по будням 10:00, 17:00» и
        следующий запуск. Папка не из модуля или у модуля нет расписания — None."""
        mk = modules.mark_of(Path(path))
        if not mk:
            return None
        if time.time() - self.mod_sched[0] > 60:
            self.mod_sched = (time.time(), {m["id"]: m for m in modules.catalog()})
        m = self.mod_sched[1].get(str(mk.get("id")))
        if not m or not m.get("schedule"):
            return None
        nxt = modules.next_run(m, now or datetime.now()) if mk["schedule"] == "on" else None
        return {"state": mk["schedule"], "text": modules.schedule_text(m),
                "next": int(nxt.timestamp()) if nxt else None}

    def set_schedule(self, path: str, state: str, uid=None) -> dict:
        """Переключатель «Расписание»: on / paused / off — владельцу и тому, кто создал пространство."""
        mk = modules.mark_of(Path(path))
        if not mk:
            raise ValueError("эта папка — не пространство из модуля")
        if uid is not None and not self.is_owner(uid) and str(mk.get("by")) != str(uid):
            raise PermissionError("расписание меняет владелец или тот, кто создал пространство")
        modules.set_schedule(Path(path), state)
        return self.schedule_of(path) or {"state": state}

    def module_delete(self, w: dict, confirm: str) -> dict:
        """«Удалить» сессию модуля: расписание — выключено навсегда, окно закрыто, папка — в корзину пульта
        (``<данные>/trash/modules/<время>__<папка>``; вернуть — перенести обратно)."""
        folder = Path(w["path"])
        if not modules.mark_of(folder):
            raise ValueError("это не пространство из модуля — «Завершить сессию»")
        if confirm != folder.name:
            raise ValueError("для удаления введите имя папки точно")
        modules.set_schedule(folder, "off")             # даже если папку вернут — само не запустится
        if harness.is_agent(w):
            r = self.close_ex(w)
            if r["result"] != "закрыто":
                raise ValueError(r["result"])
        elif self.tmux.window(w["id"]):
            self.tmux.kill(w["id"])
        trash = self.cfg.data / "trash" / "modules"
        trash.mkdir(parents=True, exist_ok=True, mode=0o700)
        dst = trash / f"{time.strftime('%Y%m%d-%H%M%S')}__{folder.name}"
        shutil.move(str(folder), str(dst))
        return {"result": "удалено", "trash": self.pult.short(str(dst))}

    def agent_of(self, path: str) -> str:
        """Название модуля, из которого создано пространство (простой режим зовёт агента так), иначе ""."""
        mk = modules.mark_of(Path(path))
        return str((mk or {}).get("title") or "")[:60]

    # ---------- репозитории GitHub в сессии (задача 43, repos.py) ----------
    def repo_list(self, w: dict) -> dict:
        """Подключённые к сессии и что можно добавить: владельцу — его репозитории (gh), пространству — по его
        токену. Нет токена у пространства — ``hint``: где взять и куда положить."""
        out = {"added": repos.public(repos.of(self.pult.state(), w["path"])), "repos": [], "hint": None,
               "error": "", "space": w.get("space") or ""}
        try:
            out["repos"] = repos.space_list(w["space"]) if w.get("space") else repos.owner_list()
        except repos.NoToken as e:
            out["hint"] = e.hint
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            out["error"] = str(e)
        return out

    def repo_add(self, w: dict, src: str) -> dict:
        """Клон (или ``pull --ff-only``, если папка уже есть) и ``/add-dir`` в живую сессию; путь — в список сессии,
        чтобы перезапуск и «Продолжить» передали его как ``--add-dir``."""
        full, _ = repos.parse(src)
        if w.get("space"):
            path, act = repos.space_fetch(w["space"], full)
        else:
            path, act = repos.owner_fetch(full, self.pult.module_root())
        if os.path.normpath(path) == os.path.normpath(w["path"]):
            raise ValueError("это папка самой сессии — она и так в ней")
        self.pult.set_state(**{repos.STATE: repos.added(self.pult.state(), w["path"], path)})
        live = not w.get("stopped") and w.get("cmd", "claude") == "claude"
        lines = self.slash(w, f"/add-dir {path}") if live else []
        return {"full": full, "path": path, "action": act, "sent": live,
                "dialog": bool(DIALOG.search("\n".join(lines))),
                "added": repos.public(repos.of(self.pult.state(), w["path"]))}

    def repo_remove(self, w: dict, path: str) -> dict:
        """«Отключить»: только из списка сессии — при следующем перезапуске ``--add-dir`` его не будет.
        Папку с репозиторием не трогаем."""
        st = self.pult.state()
        if path not in repos.of(st, w["path"]):
            raise LookupError("этот репозиторий к сессии не подключён")
        self.pult.set_state(**{repos.STATE: repos.removed(st, w["path"], path)})
        return {"added": repos.public(repos.of(self.pult.state(), w["path"]))}

    # ---------- ▶️ команды из последнего ответа ----------
    def commands(self, w: dict) -> list[dict]:
        out = []
        answer = harness.of(w).last_answer(w["path"], self.pult.home_of(w), w.get("sid") or "")
        for i, cmd in enumerate(extract(answer)):
            kind = self.pult.cmds.kind(cmd)
            out.append({"i": i, "cmd": cmd, "kind": kind, "danger": bool(DANGER.search(cmd)),
                        "sha": hashlib.sha256(cmd.encode()).hexdigest()[:12]})
        return out

    def run(self, w: dict, i: int, sha: str, confirmed: bool) -> dict:
        if in_space(w):
            raise PermissionError(SPACE_RUN)
        c = next((x for x in self.commands(w) if x["i"] == i and x["sha"] == sha), None)
        if not c:
            raise ValueError("ответ Claude изменился — обновите вкладку «Ответ»")
        if c["kind"] != "local":
            raise ValueError("эту команду выполняйте вручную: " + {"sudo": "sudo вне разрешённого списка",
                             "tty": "ей нужен ввод (пароль) — откройте её в терминале"}.get(c["kind"],
                                                                                      "она для другой машины"))
        if c["danger"] and not confirmed:
            return {"confirm": True}
        code, secs, out = execute(c["cmd"], w["path"])
        tri, to = self.triage(w["path"], w["id"], c["cmd"], code, out)
        self.journal.collect([w], self.pult.cmds.kind)               # та же отметка — во вкладке «Команды»
        self.journal.mark_cmd(w["path"], c["cmd"], self.done(code, secs, out, "panel", tri, to), out)
        return {"code": code, "seconds": round(secs), "out": out[-TAIL:], "cut": len(out) > TAIL,
                **({"full": out[-FULL:]} if len(out) > TAIL else {}), "triage": tri, "triage_to": to}

    # ---------- задачи владельца (tasks.py, #203) ----------
    def task_chat(self, t: dict) -> dict | None:
        """Окно задачи: сначала по разговору (окно могло смениться при перезапуске), потом по номеру окна."""
        wins = [w for w in self.tmux.windows() if harness.is_agent(w) or w.get("stopped") or w.get("sleep")]
        sid = transcripts.valid_sid(t.get("sid"))
        return next((w for w in wins if sid and w.get("sid") == sid), None) or \
            next((w for w in wins if t.get("chat") and w["id"] == t["chat"]), None)

    # ---------- брифинг первого лица (brief.py, GAS-18) ----------
    def brief_get(self, uid, fresh: bool = False) -> dict:
        """Выбор источников и расписание человека; сам брифинг — только после выбора (первый вход — экран выбора).
        Сборка — несколько секунд (почта): 5 минут держим готовый, ``fresh`` — собрать заново."""
        rec = self.pult.brief_prefs.get(uid)
        avail = morning_brief.available(self.cfg)
        sel = morning_brief.chosen(rec, avail)
        out = {"sel": sel, "schedule": morning_brief.schedule(rec, self.cfg.brief_at), "avail": avail,
               "tour": self.people.tour(uid).get("brief")}
        if sel["chosen"]:
            cache = self.__dict__.setdefault("brief_cache", {})
            got = cache.get(uid)
            if fresh or not got:
                got = cache[uid] = (time.time(), self.pult.brief_now(uid=uid))
            elif time.time() - got[0] > 300:     # «Сегодня» сразу (владелец 21.11): отдаём готовый, свежий — в фоне,
                self.brief_refresh(uid)          # панель заберёт его следующим запросом
                out["stale"] = True
            out["brief"], out["built"] = got[1], int(got[0])
        return out

    def brief_refresh(self, uid):
        """Собрать брифинг в фоне (один сбор на человека за раз)."""
        busy = self.__dict__.setdefault("brief_busy", set())
        if uid in busy:
            return

        def run():
            try:
                self.brief_cache[uid] = (time.time(), self.pult.brief_now(uid=uid))
            except Exception as e:                        # сбой сбора — остаётся прежний, панель не падает
                print("brief:", type(e).__name__, e, flush=True)
            finally:
                busy.discard(uid)
        busy.add(uid)
        threading.Thread(target=run, daemon=True).start()

    def brief_set(self, uid, b: dict) -> dict:
        prefs = self.pult.brief_prefs
        prefs.set(uid, list(b.get("sources") or []), b.get("boxes"), b.get("calendars"))
        if b.get("time"):
            prefs.set_schedule(uid, str(b["time"]), str(b.get("every") or "workdays"), b.get("days"),
                               str(b.get("tz") or ""))
        self.__dict__.get("brief_cache", {}).pop(uid, None)
        rec = prefs.get(uid)
        return {"sel": morning_brief.chosen(rec, morning_brief.available(self.cfg)),
                "schedule": morning_brief.schedule(rec, self.cfg.brief_at)}

    def brief_act(self, uid, b: dict) -> dict:
        out = morning_brief.act(self.pult, uid, str(b.get("key") or ""), str(b.get("act") or ""),
                                b.get("confirm") is True)
        if "ask" not in out:
            self.__dict__.get("brief_cache", {}).pop(uid, None)
        return out

    def task_list(self) -> list[dict]:
        """Задачи с живым окном (``chat_now`` — куда «провалиться», ``chat_name``); окна нет — без него."""
        out = []
        for t in self.tasks.list():
            w = self.task_chat(t) if (t.get("chat") or t.get("sid")) else None
            out.append({**t, "chat_now": (w or {}).get("id", ""), "chat_name": (w or {}).get("name", "")})
        return out

    def task_run(self, tid: str, confirmed: bool) -> dict:
        """«Выполнить» команду задачи: как ▶ у ответа Claude — те же правила (sudo, ввод пароля, другая машина —
        вручную; опасное — второе подтверждение), в папке чата задачи; итог — в задачу (код и время, без вывода)."""
        t = self.tasks.get(tid)
        if not t:
            raise LookupError("задачи уже нет")
        if t.get("kind") != "command" or not t.get("cmd"):
            raise ValueError("у этой задачи нет команды")
        w = self.task_chat(t)
        if w and in_space(w):
            raise PermissionError(SPACE_RUN)
        kind = self.pult.cmds.kind(t["cmd"])
        if kind != "local":
            raise ValueError("эту команду выполняйте вручную: " + {"sudo": "sudo вне разрешённого списка",
                             "tty": "ей нужен ввод (пароль) — откройте её в терминале"}.get(kind,
                                                                                      "она для другой машины"))
        if DANGER.search(t["cmd"]) and not confirmed:
            return {"confirm": True}
        code, secs, out = execute(t["cmd"], (w or {}).get("path") or self.pult.home)
        self.tasks.update(tid, {"result": {"code": code, "at": time.time()}})
        return {"code": code, "seconds": round(secs), "out": out[-TAIL:], "cut": len(out) > TAIL,
                **({"full": out[-FULL:]} if len(out) > TAIL else {})}

    # ---------- команде нужен ввод — окно терминала панели (termwin.py, задача 47) ----------
    def term_open(self, cmd: str, kind: str, danger: bool, path: str, confirmed: bool) -> dict:
        """Команда — в новом окне ``gp-term`` (пароль вводят там). Для другой машины — нет."""
        if kind == "foreign":
            raise ValueError("команда для другой машины — скопируйте и выполните там")
        if danger and not confirmed:
            return {"confirm": True}
        return {"id": termwin.open_window(self.tmux, cmd, path), "name": termwin.WINDOW}

    def term_run(self, w: dict, i: int, sha: str, confirmed: bool) -> dict:
        if in_space(w):
            raise PermissionError(SPACE_RUN)
        c = next((x for x in self.commands(w) if x["i"] == i and x["sha"] == sha), None)
        if not c:
            raise ValueError("ответ Claude изменился — обновите вкладку «Ответ»")
        return self.term_open(c["cmd"], c["kind"], c["danger"], w["path"], confirmed)

    def command_term(self, cid: str, confirmed: bool) -> dict:
        c = self.journal.get(cid)
        if not c:
            raise LookupError("команды уже нет в списке")
        if in_space(c):
            raise PermissionError(SPACE_RUN)
        return self.term_open(c["cmd"], c["kind"], c["danger"], c["path"], confirmed)

    def triage(self, path: str, wid: str, cmd: str, code, out: str) -> tuple[str, str]:
        """Упала — в сессию на разбор (одну ошибку — один раз); вставка — под замком окна, как обычное сообщение."""
        try:
            return self.pult.triage(path, wid, cmd, code, out, paste=lambda w, text: self.send(w, text))
        except Exception as e:                                      # разбор — не повод потерять итог выполнения
            print(f"gas-pult webapp: не отправил ошибку на разбор: {e}", flush=True)
            return "error", ""

    @staticmethod
    def done(code, secs: float, out: str, by: str, tri: str = "", to: str = "") -> dict:
        return {"code": code, "seconds": round(secs), "at": utc_now(), "by": by, "out": out[-TAIL:],
                "cut": len(out) > TAIL, "triage": tri, "triage_to": to}

    # ---------- вкладка «Команды»: все команды из ответов всех сессий (время — UTC, как в транскрипте) ----------
    def command_log(self, can_run: bool) -> dict:
        wins = [w for w in self.tmux.windows() if harness.is_agent(w)]
        self.journal.collect(wins, self.pult.cmds.kind)
        items = self.journal.items()
        if not can_run:
            items = [{k: v for k, v in c.items() if k != "path"} for c in items]   # папки сервера — только владельцу
        return {"items": items, "host": self.cfg.host}

    def command_run(self, cid: str, confirmed: bool) -> dict:
        c = self.journal.get(cid)
        if not c:
            raise LookupError("команды уже нет в списке")
        if in_space(c):
            raise PermissionError(SPACE_RUN)
        if c["kind"] != "local":
            raise ValueError("эту команду выполняйте вручную: " + {"sudo": "sudo вне разрешённого списка",
                             "tty": "ей нужен ввод (пароль) — откройте её в терминале"}.get(c["kind"],
                                                                                      "она для другой машины"))
        if c["danger"] and not confirmed:
            return {"confirm": True}
        self.journal.update(cid, running=utc_now())                  # другим устройствам — «выполняется»
        try:
            code, secs, out = execute(c["cmd"], c["path"])
        except Exception:
            self.journal.update(cid, running=None)
            raise
        tri, to = self.triage(c["path"], c.get("wid", ""), c["cmd"], code, out)
        item = self.journal.update(cid, running=None, done=self.done(code, secs, out, "panel", tri, to))
        self.journal.save_output(cid, out)
        return {"item": item}

    def command_mark(self, cid: str, done: bool) -> dict:
        """«Отметить: сделано вручную» — отдельная пометка; итог настоящего запуска (done) не трогаем."""
        return {"item": self.journal.update(cid, manual={"at": utc_now()} if done else None)}
