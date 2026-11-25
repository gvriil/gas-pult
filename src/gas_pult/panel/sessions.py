"""Окна сессий: список, открыть, перезапустить, оживить, закрыть; модель и усилие; пропуск по памяти; интеграции чата;
вход в MCP-сервисы; файлы из панели.

Часть класса ``webapp.Panel`` (модульный монолит, docs/MONOLITH-PLAN.md п.3.1): методы перенесены как есть, ``self`` —
тот же ``Panel``. ``effort_ok``, ``CONTEXT``, ``MODEL_LINE``, ``AUTH_WITH``, ``URL_TAIL``, ``find_auth`` переехали
сюда же — ``webapp`` их реэкспортирует; ``BUSY`` — из ``bot.py`` в ``humanize.py`` (``bot.BUSY`` жив).
"""

from __future__ import annotations

import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import BinaryIO, ClassVar

from gas_pult import (
    ago,
    balance,
    chatmcp,
    claude_trust,
    ctxsnap,
    drive_inbox,
    harness,
    logins,
    models,
    notifylevel,
    pi_journal,
    projects,
    providers,
    repos,
    setup,
    space_sessions,
    spaces,
    tenants,
    termwin,
    tmux,
    transcripts,
)
from gas_pult.humanize import BUSY, DIALOG
from gas_pult.panel.projects import EFFORTS, effort_flag
from gas_pult.people import has_telegram
from gas_pult.telegram import TelegramError
from gas_pult.tmux import trust_keys


def effort_ok(profile: str | None, model: str | None = "") -> bool:
    """Усилие — только у Claude Code со своей подпиской или ключом Anthropic, в том числе у Haiku (20.11: проверено —
    ``claude -p --model haiku --effort low`` отвечает без ошибки, строка статуса Haiku показывает уровень);
    другим программам (Pi, OpenCode) и поставщикам с чужим ключом флаг не передаём. ``model`` — для совместимости."""
    del model
    return (profile or "claude") == "claude"


CONTEXT = re.compile(r"left [\d.]+k? \((\d+)%\)")
MODEL_LINE = re.compile(r"🤖 ([^·│\n]{2,40}?)\s*·")     # строка статуса: «🤖 Opus 5.5 · effort …»


AUTH_WITH = re.compile(r"Authenticating with (.+?)[….]*\s*$")
URL_TAIL = re.compile(r"^\s+([A-Za-z0-9%&=_.~:/?#+\-]+)\s*$")


def find_auth(lines: list[str]) -> dict | None:
    """Вход в MCP-сервис на экране Claude Code: название и полная ссылка (продолжение ссылки — следующими строками)."""
    service = next((m.group(1).strip() for line in lines if (m := AUTH_WITH.search(line))), None)
    for i, line in enumerate(lines):
        if m := re.search(r"https://\S*(authorize|oauth)\S*", line):
            url = m.group(0)
            for nxt in lines[i + 1:]:
                if not (t := URL_TAIL.match(nxt)):
                    break
                url += t.group(1)
            return {"service": service or "сервис", "url": url,
                    "paste": any("paste the URL" in x or "URL >" in x for x in lines)}
    return None


class SessionsPart:
    """Окна сессий: открыть, перезапустить, оживить, закрыть; модель и усилие; пропуск по памяти (примесь к Panel)."""

    BRANCH_TTL = 10                                     # с: ветка git окна — не на каждый опрос списка

    def branch_of(self, path: str) -> str:
        """Ветка git папки окна; запоминается на 10 с (список сессий опрашивается раз в 3 с на каждое окно)."""
        now, cache = time.monotonic(), self.__dict__.setdefault("_branches", {})
        if (hit := cache.get(path)) and now - hit[0] < self.BRANCH_TTL:
            return hit[1]
        b = subprocess.run(["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"],
                           capture_output=True, text=True).stdout.strip()
        cache[path] = (now, b)
        return b

    def sessions(self, pool: str | None = "owner", who: str | None = "owner") -> list[dict]:
        """``pool`` — чей расход показывать на карточках (``cost``): «owner» или ID участника; None — ничей.
        ``who`` — чьи закрепления (``pinned``): «owner» или Telegram ID человека (``H.pinner``)."""
        self.balance_watch()
        st = self.pult.state()
        act, out, paused = st.get("active"), [], st.get("cost_paused") or {}
        wins = self.tmux.windows()
        pd = self.project_data(wins)
        for w in wins:
            def branch(path=w["path"]) -> str:
                return self.branch_of(path)
            if w.get("stopped"):                     # Claude завершился, в окне оболочка — «остановлена»
                out.append({"id": w["id"], "name": w["name"], "path": w["path"], "branch": branch(),
                            "status": "stopped", "context": None, "model": "", "active": w["id"] == act,
                            "channel": False, "profile": w["mark"] if w["mark"] in models.BY_ID else "claude",
                            "rev": "", "preview": "", "cost_paused": False, "cost": None,
                            "project": self.project_of(pd, w),
                            "sid": w.get("sid") or "",
                            "pinned": self.pinned_of(pd, w, w.get("sid") or "", who),   # закреплена: время (добавлено)
                            "repos": repos.public(repos.of(st, w["path"])),
                            **ago.stamps(self.pult.acts.status(w["path"], self.pult.home_of(w), w.get("sid") or "",
                                                               harness.of(w)))})
                continue
            if not harness.is_agent(w):
                continue
            # окно без метки открыл не пульт (вручную в tmux): не метим — иначе после выхода Claude оно навсегда
            # оставалось «остановленной» сессией (#179 P1.6); такое окно просто пропадает из списка, как терминал
            lines = self.tmux.screen(w["id"], 40)
            scr = "\n".join(lines)
            home = self.pult.home_of(w)                       # папка Claude того, кто открыл окно
            sid = self.follow_sid(w, wins, home)              # свой журнал окна (--session-id); "" — старое окно
            # когда менялась (ago.py): последний ход в журнале или смена экрана; ответ агента, ваше сообщение
            when = ago.stamps(self.pult.acts.status(w["path"], home, sid, harness.of(w)),
                              self.pult.changes.look(w["id"], lines))
            ctx, mdl = CONTEXT.search(scr), MODEL_LINE.search(scr)
            snap = ctxsnap.read(sid)                          # строка статуса Claude Code: модель, усилие, контекст
            rev = harness.of(w).revision(w["path"], home, sid)
            pi = self.pi_row(w, sid) if harness.of(w).name in harness.JOURNAL_ONLY else None   # Pi, OpenCode, Hermes
            out.append({"id": w["id"], "name": w["name"], "path": w["path"], "branch": branch(),
                        "status": "sleep" if w.get("sleep") else pi["status"] if pi else
                        "dialog" if DIALOG.search(scr) else "busy" if BUSY.search(scr) else "idle",
                        "sleep": bool(w.get("sleep")),                   # 💤 claude-sleep: первое сообщение разбудит
                        # свободно % контекста: снимок строки статуса, иначе — текст экрана (старый способ)
                        "context": pi["context"] if pi else 100 - snap["used"] if snap and snap["used"] is not None
                        else int(ctx.group(1)) if ctx else None,
                        # на чём работает сессия: снимок строки статуса, «🤖 …» на экране, иначе — модель из журнала
                        "model": pi["model"] if pi else (snap or {}).get("model") or (
                            mdl.group(1).strip() if mdl else self.model_of(w["path"], rev, home, sid, harness.of(w))),
                        "harness": harness.of(w).name if harness.is_agent(w) else "",     # какой агент (добавлено)
                        "usage": pi["usage"] if pi else None,     # окно Pi: ↑↓ токены, $, контекст (добавлено)
                        # уровень усилий: выбранный в пульте (и «авто») важнее того, что Claude Code показал в строке
                        "effort": (st.get("window_efforts") or {}).get(w["id"]) or (snap or {}).get("effort", ""),
                        "effort_guess": bool((snap or {}).get("effort_guess")),
                        "ctx_at": (snap or {}).get("at"),                # когда строка статуса обновлялась
                        "active": w["id"] == act, "channel": w["channel"], "profile": w.get("profile") or "claude",
                        "rev": rev,                                       # изменился журнал → «новый ответ»
                        "preview": self.preview(w["path"], rev, home, sid, harness.of(w)),
                        "sid": sid,                                       # id сессии Claude Code окна (добавлено)
                        "twin": ((o := self.sid_owner(sid, w["id"], wins, running=True)) and o["name"]) or "",
                        "notify": notifylevel.level(st, w["id"]),        # уровень уведомлений окна (добавлено)
                        # один повтор после лимита подписки — когда (limitretry.py); нет — None
                        "retry_at": ((st.get("limit_retries") or {}).get(w["id"]) or {}).get("at"),
                        "notify_own": bool(notifylevel.own(st, w["id"])),
                        "title": (ttl := self.chat_title(pd, w["path"], home, sid, harness.of(w))),   # название чата
                        "title_status": projects.is_status(ttl),          # название-статус, смысла ещё нет
                        "mcp_off": chatmcp.get(self.CHAT_MCP, sid),        # интеграции, выключенные в этом чате
                        "title_own": bool(sid and ((pd.get("sessions") or {}).get(sid) or {}).get("title")),
                        "cost_paused": w["id"] in paused,                 # на паузе по расходу — видно всем
                        "cost": self.cost_of(w, pool, st),                # расход — только хозяину учётки
                        "agent": self.agent_of(w["path"]),                # простой режим: имя агента модуля
                        "sections": self.sections_of(w["path"]),          # разделы чата бизнес-ролей; [] — во всех
                        "schedule": self.schedule_of(w["path"]),          # расписание модуля: on/paused/off, следующий
                        **self.space_fields(w),                           # окно демо-пространства (spaces.py)
                        **self.money_of(w, lines),                        # у поставщика нет денег (balance.py)
                        "model_own": (st.get("window_models") or {}).get(w["id"], ""),   # модель — только этого чата
                        "project": self.project_of(pd, w),                # проект окна (projects.py); "" — нет
                        "repos": repos.public(repos.of(st, w["path"])),     # подключённые репозитории (задача 43)
                        "pinned": self.pinned_of(pd, w, sid, who),             # закреплена: время закрепления, 0 — нет
                        **when})                                          # когда менялась (ago.py)
        return out

    def follow_sid(self, w: dict, wins: list[dict], home) -> str:
        """Метка окна ``@gas_pult_sid`` с поправкой на ``/clear`` (новый журнал — новый id): окно — единственное в
        папке, появился более новый ничей журнал — метка переезжает на него (``transcripts.follow``)."""
        sid = transcripts.valid_sid(w.get("sid"))
        if not sid:
            return ""
        if w.get("live"):                               # id взят у самого процесса Claude — догадки не нужны
            if w.get("tag") != sid and not w.get("space"):
                self.tmux.set_sid(w["id"], sid)         # метка — вслед за процессом: переживёт его завершение
            return sid
        real = os.path.realpath(w["path"])
        mates = [x for x in wins if x["id"] != w["id"] and harness.is_agent(x) and not x.get("space")
                 and os.path.realpath(x.get("path", "")) == real and self.pult.home_of(x) == home]
        if any(not transcripts.valid_sid(x.get("sid")) for x in mates):
            return sid                                  # рядом старое окно без метки — его журнал не забираем
        taken = {x.get("sid") for x in wins if x["id"] != w["id"] and transcripts.valid_sid(x.get("sid"))}
        if nxt := transcripts.follow(w["path"], home, sid, taken):   # журнал любого другого окна — не наш
            self.tmux.set_sid(w["id"], nxt)
            w["sid"] = sid = nxt
        return sid

    def model_of(self, path: str, rev: str, home=None, sid: str = "", h: harness.Harness | None = None) -> str:
        """Модель последнего ответа из журнала — когда строка статуса её не показывает; кэш по ревизии журнала.
        Журнал — у адаптера агента окна (R13); красивое имя (``model_title``) — у моделей Claude Code."""
        h = h or harness.of(None)
        key = (path, str(home or ""), sid, h.name)
        if self.model_cache.get(key, (None,))[0] != rev:      # (None,) — у нового окна журнала ещё нет (rev "")
            m = h.last_model(path, home=home, sid=sid)
            self.model_cache[key] = (rev, transcripts.model_title(m) if h.name == harness.DEFAULT else m)
        return self.model_cache[key][1]

    def preview(self, path: str, rev: str, home=None, sid: str = "", h: harness.Harness | None = None) -> str:
        """Строка о последнем шаге сессии; пересчитывается, только когда журнал изменился. Журнал — у агента окна."""
        h = h or harness.of(None)
        key = (f"{home}|{path}" if home else path) + (f"|{sid}" if sid else "")
        key += f"|{h.name}" if h.name != harness.DEFAULT else ""
        if self.previews.get(key, (None,))[0] != rev:
            self.previews[key] = (rev, h.preview(path, home=home, sid=sid))
        return self.previews[key][1]

    # ---------- действия ----------
    def send(self, w: dict, text: str, mid: str = "") -> bool:
        """mid — id сообщения от браузера. Связь телефона рвётся, пока текст вставляется, и браузер повторяет запрос:
        с тем же id второй раз не вставляем (ответ True — «уже было»). Повтор, пришедший во время первой вставки, ждёт
        её исхода; не удалась — пробует сам."""
        if mid:
            with self.pult.lock:
                now = time.time()
                for k in [k for k, (_, t) in self.sent.items() if now - t > 900]:
                    del self.sent[k]
                ev, first = self.sent.get(mid, (None, 0))[0], mid not in self.sent
                if first:
                    ev = threading.Event()
                    self.sent[mid] = (ev, now)
            if not first:
                ev.wait(120)
                return True if mid in self.sent else self.send(w, text, mid)
        try:
            self.pult.to_claude(w, text)               # под замком окна — общим с ботом (flock)
        except Exception:
            with self.pult.lock:
                self.sent.pop(mid, None)
            raise
        finally:
            if mid:
                ev.set()
        return False

    def activity(self, wid: str) -> dict:
        """Живая строка статуса окна (activity.py): опрос раз в 1,5 с из открытого чата — поэтому список окон
        кэшируется на 3 с (в нём ``ps`` по каждому окну), экран читается не чаще раза в 2 с, журнал — с хвоста."""
        self.tmux.target(wid)                        # окно не своего пространства — «окна нет» (кэш общий)
        now = time.time()
        if wid not in self.wins[1] or now - self.wins[0] > 3:
            self.wins = (now, {w["id"]: w for w in self.tmux.windows() if harness.is_agent(w)})
        if not (w := self.wins[1].get(wid)):
            raise LookupError("окна уже нет")
        scr = self.screens.get(wid)
        if not scr or now - scr[0] >= 2:
            scr = self.screens[wid] = (now, self.pult.screen_state(wid))
        home = self.pult.home_of(w)
        return {**self.pult.activity(w, scr[1]), "rev": harness.of(w).revision(w["path"], home, w.get("sid") or "")}

    def slash(self, w: dict, cmd: str) -> list[str]:
        return self.pult.run_slash(w["id"], cmd)

    def effort(self, w: dict, level: str) -> list[str]:
        if level not in EFFORTS:
            raise ValueError("такого уровня усилий нет")
        st = self.pult.state()                          # запомнить у чата: перезапуск и «Продолжить» — с ним же
        ef = {k: v for k, v in (st.get("window_efforts") or {}).items() if k != w["id"]}
        self.pult.set_state(window_efforts={**ef, w["id"]: level})      # и «авто»: панель покажет выбор человека
        return self.slash(w, f"/effort {level}")

    def keep_model(self, w: dict, name: str) -> dict:
        """Окно выбора: реальная модель чата (строка статуса) расходится с сохранённой — «Оставить» запоминает
        реальную для следующего перезапуска (``window_models``), окно не перезапускается (вариант A, владелец 20.11)."""
        if name not in self.cfg.models:
            raise ValueError("такой модели нет в настройках (models)")
        st = self.pult.state()
        self.pult.set_state(window_models={**(st.get("window_models") or {}), w["id"]: name})
        return {"ok": True, "model_own": name}

    def model(self, w: dict, name: str, uid=None, effort: str | None = None) -> dict:
        """Модель — только для этого чата (задача 37): окно перезапускается с ``--model`` у того же поставщика, разговор
        продолжается. ``/model`` Claude Code не шлём: он сохраняет выбор в общие настройки (``~/.claude/settings.json``)
        — модель менялась во всех сессиях. Модель по умолчанию для новых — отдельно: ``default_model``."""
        if name not in self.cfg.models:
            raise ValueError("такой модели нет в настройках (models)")
        if w.get("space"):
            raise ValueError("в сессии пространства модель задаёт его профиль")
        if effort is not None and effort not in EFFORTS:
            raise ValueError("такого уровня усилий нет")
        return self.restart(w, w.get("profile") or (w.get("mark") if w.get("mark") in models.BY_ID else "claude"),
                            keep=True, uid=uid, model=name, effort=effort)

    def money_of(self, w: dict, lines: list[str]) -> dict:
        """Поставщик окна ответил «нет денег» (Z.ai 1113, DeepSeek 402) — в карточку и отметку на час (balance.py)."""
        prof = w.get("profile") or "claude"
        if prof == "claude" or not balance.seen("\n".join(lines[-15:])):
            return {}
        if (new := balance.mark(self.pult.state(), prof)) is not None:
            self.pult.set_state(no_balance=new)
        return {"no_balance": True}

    def balance_watch(self):
        """Раз в час — баланс поставщиков, у которых есть бесплатная проверка (DeepSeek): нет денег — отметка, есть —
        снять. В фоне: список сессий не ждёт сеть."""
        if time.time() - self.balance_at < balance.TTL:
            return
        self.balance_at = time.time()

        def run():
            keys = providers.load_keys()
            for prov in balance.BALANCE_URL:
                ok = balance.check(prov, keys.get(prov, ""))
                st = self.pult.state()
                if ok is False and (new := balance.mark(st, prov)) is not None:
                    self.pult.set_state(no_balance=new)
                elif ok is True and prov in balance.marked(st):
                    self.pult.set_state(no_balance=balance.clear(st, prov))
        threading.Thread(target=run, daemon=True).start()

    def default_model(self, name: str | None = None) -> dict:
        """Модель Claude по умолчанию для новых сессий (``model`` в ``~/.claude/settings.json`` владельца) — только
        явной настройкой владельца. ``name``: None — прочитать, «» — убрать (как решит Claude Code)."""
        f = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            d = {}
        if name is not None:
            if name and name not in self.cfg.models:
                raise ValueError("такой модели нет в настройках (models)")
            if name:
                d["model"] = name
            else:
                d.pop("model", None)
            tmp = f.with_name(f".{f.name}.gas-pult")
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
            os.replace(tmp, f)
        return {"model": d.get("model") or "", "models": list(self.cfg.models)}

    def tty_window(self, wid: str, owner: bool, write: bool, space: str | None = None) -> dict:
        """Окно для живого терминала (задача 50). Владельцу — любое окно его tmux, окно gp-term и окна пространств
        (через их tmux). Тестировщику пространства — только окна своего пространства: командная строка там —
        песочница пространства (свой пользователь Linux, GAS-38). Участнику — только окна сессий пульта; писать —
        только пока в окне работает Claude (остановленная сессия — командная строка сервера, она только владельцу)."""
        w = self.tmux.window(str(wid or ""))
        if not w:
            raise LookupError("окна уже нет")
        if space:
            if w.get("space") != space:
                raise LookupError("окна уже нет")         # чужое окно — как несуществующее
            return w
        if owner:
            return w
        if w.get("space") or w.get("name") == termwin.WINDOW:
            raise ValueError("это окно — только владельцу пульта")
        if not (harness.is_agent(w) or w.get("mark")):
            raise ValueError("это не окно сессии пульта")
        if write and (not harness.is_agent(w) or w.get("stopped")):
            raise ValueError("Claude в этой сессии остановлен — в командную строку сервера вводит только владелец")
        return w

    @staticmethod
    def tty_kind(w: dict) -> str:
        """Что за окно — для подписи в панели: сессия, окно терминала gp-term, остановленная сессия, своё окно."""
        if w.get("name") == termwin.WINDOW:
            return "term"
        if w.get("stopped"):
            return "stopped"
        return "session" if harness.is_agent(w) or w.get("mark") else "shell"

    def login_window(self, home=None) -> dict:
        """Окно для входа в MCP: активная сессия, если свободна, иначе любая свободная — только того же человека
        (``home`` — его папка Claude Code; вход сохранится у него, а не у хозяина чужого окна)."""
        mine = {w["id"] for w in self.tmux.windows() if self.pult.home_of(w) == home}
        sess = [s for s in self.sessions() if s["status"] == "idle" and s["id"] in mine]
        pick = next((s for s in sess if s["active"]), None) or (sess[0] if sess else None)
        if not pick:
            raise ValueError("нет свободной сессии Claude — откройте новую («Сессии» → ＋) и повторите"
                             if not home else "нет вашей свободной сессии Claude — откройте свою («Сессии» → ＋) "
                             "и повторите: вход сохранится в ваших интеграциях")
        return self.window(pick["id"])

    def mcp_login(self, name: str, home=None) -> dict:
        """Запуск входа в MCP-сервис из панели: /mcp → сервер → Authenticate → ссылка входа с экрана."""
        w = self.login_window(home)
        self.slash(w, "/mcp")
        self.select(w, name)
        self.select(w, "Authenticate")
        for _ in range(15):
            lines = self.tmux.screen(w["id"], 60)
            if auth := find_auth(lines):
                return {"w": w["id"], "session": w["name"], **auth}
            time.sleep(1)
        self.tmux.keys(w["id"], "Escape")
        raise ValueError("Claude Code не показал ссылку входа — откройте сессию и проверьте «Экран»")

    def login_check(self, w: dict, kind: str, home=None) -> dict:
        """«Готово — проверить» в шторке «Нужен вход»: claude — ``claude auth status``, gh — ``gh auth status``,
        mcp — ``claude mcp list`` (сервис с ✔); всё — и экран окна: запрос входа с него ушёл."""
        login = logins.detect(self.tmux.screen(w["id"], 60))
        if kind == "claude":
            au = setup.auth(setup.installed(self.cfg.claude) or setup.executable(self.cfg.claude))
            ok = au["logged_in"] is True
            text = "вход в Claude выполнен" if ok else "вход в Claude ещё не выполнен"
        elif kind == "gh":
            exe = shutil.which("gh")
            if not exe:
                return {"ok": False, "text": "GitHub CLI (gh) на сервере не найден", "login": login}
            try:
                r = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=15)
                ok = r.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                ok = False
            text = "вход в GitHub выполнен" if ok else "gh auth status: вход не выполнен"
        elif kind == "mcp":
            svc = (login or {}).get("service", "")
            bad = [x for x in self.mcp.list(fresh=True, home=home) if not x["ok"]]
            ok = not login and not any(svc and x["name"] == svc for x in bad)
            text = "вход в сервис выполнен" if ok else "сервис ещё ждёт входа — откройте ссылку и завершите вход"
        else:
            ok = not login
            text = "запроса входа на экране больше нет" if ok else "окно всё ещё просит войти"
        return {"ok": ok, "text": text, "login": None if ok else login}

    def mcp_finish(self, w: dict, url: str, name: str, home=None) -> str:
        """Адрес страницы после входа (http://localhost…/callback?code=…) → в поле «URL >» Claude Code."""
        if self.pult.home_of(w) != home:
            raise ValueError("это сессия другого человека — вход начните заново из своих «Подключений»")
        u = urllib.parse.urlparse(url.strip())
        if u.scheme != "http" or u.hostname not in ("localhost", "127.0.0.1") or "code=" not in u.query:
            raise ValueError("нужен адрес страницы после входа: начинается с http://localhost и содержит code=")
        self.send(w, url.strip())
        time.sleep(4)
        self.tmux.keys(w["id"], "Escape")              # закрыть меню /mcp, вернуться к вводу
        time.sleep(1)
        self.tmux.keys(w["id"], "Escape")
        status = next((s for s in self.mcp.list(fresh=True, home=home) if s["name"] == name), None)
        if status and status["ok"]:
            return f"✔ {name} подключён"
        return f"вход не подтвердился: {status['state'] if status else 'сервер не найден'} — попробуйте ещё раз"

    def select(self, w: dict, target: str, n: str = "", go: bool = True) -> list[str]:
        """Пункт меню: двигаем ❯ стрелками до строки с этим текстом (или номером n) и жмём Enter; go=False — только
        выделить. Цифрой не выбираем — не всякое меню Claude её принимает. Выше меню бывают прошлые сообщения с «❯»
        и «1. …» — номер ищем снизу (меню внизу экрана), а выделение — ближайшее к пункту."""
        target = target.strip()[:200]
        with self.pult.hold(w["id"]):
            for _ in range(30):
                lines = self.tmux.screen(w["id"], 60)
                if n.isdigit():
                    num = re.compile(rf"^\s*(❯\s*)?{int(n)}\.\s")
                    tgt = next((i for i in reversed(range(len(lines))) if num.match(lines[i])), None)
                    sel = next((i for i in reversed(range(len(lines))) if re.match(r"^\s*❯\s*\d+\.\s", lines[i])), None)
                else:
                    tgt = next((i for i, x in enumerate(lines) if target and target in x), None)
                    if tgt is None and target:                # узкое окно перенесло пункт на две строки
                        tgt = next((i for i, x in enumerate(lines) if len(c := x.replace("❯", "").strip()) >= 6
                                    and target.startswith(c)), None)
                    marks = [i for i, x in enumerate(lines) if "❯" in x]
                    sel = min(marks, key=lambda i: abs(i - tgt)) if marks and tgt is not None else None
                if (sel is None or tgt is None) and re.match(r"Yes, I trust", target, re.I) and \
                        (keys := trust_keys("\n".join(lines))):   # «Да, доверяю» — как автоответ (25.11)
                    for k in keys:
                        self.tmux.keys(w["id"], k)
                        time.sleep(0.1)
                    time.sleep(1.5)
                    return self.tmux.screen(w["id"], 40)
                if sel is None or tgt is None:
                    raise ValueError("пункт не найден на экране — обновите экран")
                if sel == tgt:
                    if not go:
                        return lines[-40:]
                    self.tmux.keys(w["id"], "Enter")
                    time.sleep(1.5)
                    return self.tmux.screen(w["id"], 40)
                self.tmux.keys(w["id"], "Down" if tgt > sel else "Up")
                time.sleep(0.25)
        raise ValueError("не получилось выбрать этот пункт — выберите стрелками ↑ ↓ и ⏎")

    def new(self, i: int, profile: str = "", person: int | None = None, uid=None) -> dict:
        """``person`` — Telegram ID участника: окно с его папкой Claude Code (вход, MCP); None — владелец.
        ``uid`` — кто нажал: по его странам проверяется поставщик и ставится метка окна для запасных."""
        if slug := self.tmux.scoped:                     # тестировщик: окно — только в его пространстве
            return self.new_in_space(slug)
        if uid is not None:
            self.check(profile, uid)                     # поставщик не для страны — отказ сразу
        dirs = self.pult.projects()
        if not 0 <= i < len(dirs):
            raise ValueError("список папок изменился — обновите панель")
        path = dirs[i]
        if w := self.pult.project_window(path):             # одно окно на проект: открываем уже работающее
            return {"id": w["id"], "existing": w["name"]}   # активное окно бота — только явным выбором (#179)
        return {"id": self.open_in(path, profile, person, uid)["id"]}

    # ---------- пропуск новой сессии по памяти (GAS-25 п.1; зависание сервера 18.11, GAS-22) ----------
    # Свободной памяти меньше ``tmux.LOW_MB`` и после усыпления простаивающих (``tmux.make_room``) — новое окно не
    # открываем: запрос встаёт в очередь, человеку — понятный ответ; освободится память — окно откроется само и
    # придёт сообщение в Telegram. Ждём не дольше ``MEM_WAIT`` с, потом — «не дождался».
    MEM_WAIT = 30 * 60

    def mem_gate(self, start, label: str, uid=None):
        free = tmux.free_mb()
        if free is None or free >= tmux.LOW_MB:
            return start()
        tmux.make_room()
        time.sleep(3)                                     # усыпление освобождает память за секунды
        free = tmux.free_mb()
        if free is None or free >= tmux.LOW_MB:
            return start()
        with self.lock_q:
            self.start_q.append({"start": start, "label": label, "uid": uid, "at": time.time()})
            pos = len(self.start_q)
            if not self.q_thread or not self.q_thread.is_alive():
                self.q_thread = threading.Thread(target=self._start_queue, daemon=True, name="mem-queue")
                self.q_thread.start()
        print(f"память: свободно {free} МБ < {tmux.LOW_MB} — «{label}» в очереди ({pos})", file=sys.stderr, flush=True)
        raise ValueError(f"На сервере мало памяти (свободно {free / 1024:.1f} ГБ). Сессия «{label}» в очереди"
                         f"{f' — {pos}-я' if pos > 1 else ''}: откроется сама, когда память освободится, и придёт "
                         "сообщение. Освободить сейчас — закройте или усыпите ненужные сессии.")

    def _start_queue(self):
        while True:
            time.sleep(20)
            with self.lock_q:
                if not self.start_q:
                    return
                job = self.start_q[0]
                if time.time() - job["at"] > self.MEM_WAIT:
                    self.start_q.pop(0)
                    self._q_tell(job, f"⏳ Сессия «{job['label']}» не открылась: памяти на сервере так и не хватило "
                                      f"за {self.MEM_WAIT // 60} минут. Закройте ненужные сессии и откройте снова.")
                    continue
                free = tmux.free_mb()
                if free is not None and free < tmux.LOW_MB:
                    continue
                self.start_q.pop(0)
            try:
                job["start"]()
                self._q_tell(job, f"✅ Память освободилась — сессия «{job['label']}» открыта. Она в списке сессий.")
            except Exception as e:
                self._q_tell(job, f"Сессия «{job['label']}» не открылась: {e}")

    def _q_tell(self, job: dict, text: str):
        chats = [job["uid"]] if has_telegram(job.get("uid")) else list(self.cfg.owners)
        for chat in chats:
            try:
                self.pult.api("sendMessage", chat_id=chat, text=text)
            except (TelegramError, OSError) as e:
                print(f"память: сообщение {chat}: {e}", file=sys.stderr, flush=True)

    def open_in(self, path: str, profile: str = "", person: int | None = None, uid=None, resume: str = "",
                model: str = "", name: str = "", mcp_off: list | None = None, effort: str = "") -> dict:
        label = name or (os.path.basename(path) if path != self.pult.home else "home")
        return self.mem_gate(lambda: self._open_in(path, profile, person, uid, resume, model, name, mcp_off, effort),
                             label, uid)

    def _open_in(self, path: str, profile: str = "", person: int | None = None, uid=None, resume: str = "",
                 model: str = "", name: str = "", mcp_off: list | None = None, effort: str = "") -> dict:
        """Новое окно с Claude в папке — без правила «одно окно на папку»: у окна свой журнал (``--session-id`` и
        метка ``@gas_pult_sid``) или продолжение выбранного (``resume`` — ``--resume <id>``). ``model`` — модель только
        этого чата (``window_models``), как у «Модель» в меню."""
        base = name or (os.path.basename(path) if path != self.pult.home else "home")
        if profile in harness.JOURNAL_ONLY:              # Pi, OpenCode, Hermes: своя команда, свой журнал, метка
            h = harness.HARNESSES[profile]
            sid = (pi_journal.valid_sid(resume) or str(uuid.uuid4())) if profile == "pi" else resume   # у OC/Hermes id
            cmd = h.launch(sid, resume=bool(resume), path=path)             # + автопамять проекта папки
            wid = self.tmux.new_window(self.free_wname(base), path, cmd,
                                       mark=profile, sid=sid)       # сессии создаёт сама программа — по папке окна
            self.mark_by(wid, uid)
            return {"id": wid, "sid": sid}
        self.need_claude()
        home = self.pult.claude_dir(person) if person is not None else None
        st = self.pult.state()
        cmd = models.command(self.cfg.claude, profile, st, home=home, path=path)
        if model:
            cmd += f" --model {shlex.quote(model)}"
        if not effort_ok(profile, model):
            effort = ""
        cmd += effort_flag(effort)                                   # усилие нового чата — сразу при запуске
        cmd += repos.flags(st, path)                                 # подключённые к папке репозитории (задача 43)
        sid = transcripts.valid_sid(resume) or str(uuid.uuid4())     # свой журнал окна: --session-id или --resume
        if mcp_off is not None:                                      # интеграции, выключенные для этого чата
            chatmcp.put(self.CHAT_MCP, sid, mcp_off)
        cmd += chatmcp.flags(chatmcp.get(self.CHAT_MCP, sid))
        cmd += f" --resume {sid}" if resume else f" --session-id {sid}"
        claude_trust.ensure(path, self.cfg.roots(), home)            # папка пульта — без вопроса «доверять?» (25.11)
        wid = self.tmux.new_window(self.free_wname(base), path, cmd,
                                   mark=profile or "claude", by=str(person) if home else "", sid=sid)
        if not home:
            self.mark_by(wid, uid)
        if model:                                   # активное окно бота не трогаем — только явным выбором (#179)
            self.pult.set_state(window_models={**(st.get("window_models") or {}), wid: model})
        if effort_flag(effort):
            self.pult.set_state(window_efforts={**(self.pult.state().get("window_efforts") or {}), wid: effort})
        return {"id": wid, "sid": sid}

    CLAUDE_MISSING = ("В пространстве ещё не установлен Claude Code — сессия не запустится. Владелец пульта уже "
                      "знает; попробуйте через несколько минут.")

    def new_in_space(self, slug: str, name: str = "", effort: str = "") -> dict:
        """Новая сессия в демо-пространстве: своя папка ``home/projects/<имя>`` (``space_sessions.create``) и окно
        ``tenants.new_window`` в ней — от пользователя пространства, с его CLAUDE_CONFIG_DIR и моделью. Функция
        выключена (нет настройки) — понятный отказ."""
        if not tenants.enabled():
            raise ValueError("демо-пространство ещё не готово — владелец пульта включит его")
        name = space_sessions.folder_name(name) if str(name or "").strip() else f"Сессия {time.strftime('%d.%m %H-%M')}"
        path = space_sessions.create(slug, name)
        raw = tenants.new_window(slug, path.name, str(path), args=effort_flag(effort).strip())
        self.space_claude_check(slug, raw)
        return {"id": spaces.wid_of(slug, raw), "name": path.name, "folder": path.name}

    def space_claude_check(self, slug: str, raw: str, wait: float = 2.0):
        """Claude Code в пространстве не установлен — окно с «command not found»: закрыть и сказать понятно
        (диагноз lexx 19.11: сессии «создавались», а в окне была пустая оболочка)."""
        time.sleep(wait)
        try:
            tm = tenants.tmux_of(slug)
            text = "\n".join(tm.screen(raw, 10))
        except (RuntimeError, OSError):
            return
        if "claude: command not found" in text or "claude: not found" in text:
            try:
                tm.run("kill-window", "-t", raw)
            except (RuntimeError, OSError):
                pass
            print(f"пространство {slug}: claude не установлен (docs/TENANTS.md, шаг 4)", file=sys.stderr, flush=True)
            raise ValueError(self.CLAUDE_MISSING)

    # ---------- окна сессий: новая папка, оживить, интеграции чата, перезапуск, закрыть, файлы ----------
    def new_folder(self, name: str, profile: str = "", person: int | None = None, uid=None) -> dict:
        """«Новая папка» в панели — как 📁 в боте: папка в первом корне проектов, ``git init``, сессия в ней.
        Проверки страны/поставщика и Claude — до создания папки, чтобы не оставлять пустых."""
        if uid is not None:
            self.check(profile, uid)
        self.need_claude()
        try:
            path = self.pult.make_folder(name.strip().lower())
        except FileExistsError:                         # занято — не ошибка: предложим открыть существующую
            p = str(self.pult.module_root() / name.strip().lower())
            dirs, w = self.pult.projects(), self.pult.project_window(p)
            return {"exists": True, "folder": name.strip().lower(), "path": self.pult.short(p),
                    "i": dirs.index(p) if p in dirs else None, "open": w["id"] if w else None}
        out = self.new(self.pult.projects().index(str(path)), profile, person, uid)
        return {**out, "path": self.pult.short(str(path)), "folder": path.name}

    def revive(self, wid: str, uid=None) -> dict:
        """Остановленная сессия: Claude заново в том же окне, у того же поставщика, с продолжением разговора.
        Спящая (claude-sleep) — просто будим: человек её открыл, этого достаточно (владелец 18.11)."""
        w = self.tmux.window(wid)
        if w and w.get("sleep"):
            self.tmux.wake_open(wid)
            return {"id": wid, "woke": True}
        if not w or not w.get("stopped"):
            raise ValueError("сессия не остановлена — перезапускать нечего")
        if w.get("space"):                              # окно пространства — его команда: свой PATH, профиль, ключ
            t = tenants.load(w["space"])
            if not t:
                raise ValueError("пространства уже нет")
            profile, cmd = w["mark"] or "claude", tenants.command(t) + repos.flags(self.pult.state(), w["path"])
            self.tmux.respawn(wid, w["path"], cmd + " --continue", mark=profile)
            return {"id": wid}
        if w.get("mark") in harness.JOURNAL_ONLY:        # окно Pi/OpenCode/Hermes — снова оно, тот же разговор
            if uid is not None:
                self.check(w["mark"], uid)
            cmd = harness.HARNESSES[w["mark"]].launch(w.get("sid") or "", resume=True, path=w["path"])
            self.tmux.respawn(wid, w["path"], cmd, mark=w["mark"])
            return {"id": wid}
        profile = w["mark"] if w["mark"] in models.BY_ID else "claude"
        if uid is not None:
            self.check(profile, uid)
        self.need_claude()
        st = self.pult.state()
        cmd = models.command(self.cfg.claude, profile, st, home=self.pult.home_of(w), path=w["path"])  # нет ключа
        cmd += repos.flags(st, w["path"])                                    # подключённые репозитории (задача 43)
        cmd += chatmcp.flags(chatmcp.get(self.CHAT_MCP, w.get("sid") or ""))   # выключенные интеграции чата
        if own := (st.get("window_models") or {}).get(wid):                  # модель этого чата — та же
            cmd += f" --model {shlex.quote(own)}"
        if effort_ok(profile, own):
            cmd += effort_flag((st.get("window_efforts") or {}).get(wid))   # и усилие
        self.busy_sid(w.get("sid"), wid)                                     # тот же разговор уже идёт рядом
        # @gas_pult_by и @gas_pult_sid окна остаются: свой журнал — тот же разговор (--resume), иначе --continue
        self.tmux.respawn(wid, w["path"], cmd + harness.of(w).resume_args(w.get("sid")), mark=profile)
        return {"id": wid}

    @property
    def CHAT_MCP(self) -> Path:
        return self.cfg.data / "chat-mcp.json"

    def chat_mcp(self, w: dict, off, uid=None) -> dict:
        """Сменить набор интеграций посреди чата: только Claude Code; разговор продолжается (--resume)."""
        if harness.of(w).name != "claude":
            raise ValueError("интеграции на чат — только у Claude Code; у этого агента — в его настройках")
        if not transcripts.valid_sid(w.get("sid")):
            raise ValueError("у чата ещё нет разговора — напишите первое сообщение")
        chatmcp.put(self.CHAT_MCP, w["sid"], off)
        return {**self.restart(w, w.get("profile") or w.get("mark") or "claude", True, uid), "off": chatmcp.get(
            self.CHAT_MCP, w["sid"])}

    def free_wname(self, base: str) -> str:
        """Имя нового окна ``<папка>-ЧЧММ``; занято (два окна за минуту) — ``-2``, ``-3``…: штаб и люди зовут окна
        по имени (``tmux send-keys -t main:<имя>``), два одинаковых имени — письмо уходит не туда (22.11)."""
        name = f"{base}-{time.strftime('%H%M')}"
        try:
            taken = {w.get("name") for w in self.tmux.windows()}
        except (OSError, AttributeError):                  # нет tmux; у подделок в тестах нет windows()
            return name
        n, out = 2, name
        while out in taken:
            out, n = f"{name}-{n}", n + 1
        return out

    def restart(self, w: dict, profile: str, keep: bool = True, uid=None, model: str | None = None,
                effort: str | None = None, path: str = "", wname: str = "", closed=None) -> dict:
        """Сменить поставщика: штатно закрыть окно и открыть в той же папке с другим профилем.

        ``keep`` — продолжить тот же разговор (``claude --continue``: новый поставщик получает всю переписку, контекст
        не теряется); иначе — чистый лист. Одно окно на проект, поэтому «последний разговор папки» — именно этот.
        ``path`` и ``wname`` — открыть в другой папке под другим именем окна («Перенести в проект…», chat_move.py);
        ``closed()`` — вызывается после закрытия окна и до запуска нового (перенос журнала: Claude уже вышел).
        """
        name = w.get("mark") if w.get("mark") in harness.JOURNAL_ONLY else harness.of(w).name
        if name in harness.JOURNAL_ONLY:               # Pi/OpenCode/Hermes: перезапуск — снова оно, тот же разговор
            h = harness.HARNESSES[name]
            if profile not in ("", name, "claude") and profile != (w.get("profile") or ""):
                raise ValueError(f"в окне {h.title} модель меняется в самой программе: /model")
            if uid is not None:
                self.check(name, uid)
            sid = (w.get("sid") or "") if keep else (str(uuid.uuid4()) if name == "pi" else "")
            cmd = h.launch(sid, resume=keep, path=w["path"])
            if (result := self.close(w)) != "закрыто":
                raise ValueError(result)
            wid = self.tmux.new_window(w["name"], w["path"], cmd, mark=name, sid=sid)
            self.mark_by(wid, w.get("by") or uid)
            self.focus.move(w["id"], wid)
            if routes := getattr(self.pult, "routes", None):
                routes.moved(w["id"], wid)
            return {"id": wid}
        if uid is not None:
            self.check(profile, uid)                                          # не для страны — до закрытия
        path = path or w["path"]
        home = self.pult.home_of(w)                    # папка того, кто открыл окно, а не того, кто нажал
        st = self.pult.state()
        cmd = models.command(self.cfg.claude, profile, st, home=home, path=path)   # нет ключа — ошибка до закрытия
        own = dict(st.get("window_models") or {})
        efforts = dict(st.get("window_efforts") or {})
        same = profile == (w.get("profile") or w.get("mark") or "claude")
        if effort is None:                              # усилие этого чата — прежнее (у того же поставщика)
            effort = efforts.get(w["id"], "") if same else ""
        if model is None:                               # смена поставщика: модель этого чата — его по умолчанию;
            model = own.get(w["id"], "") if same else ""   # тот же поставщик (перезапуск) — прежняя модель чата
        cmd += repos.flags(st, path)                     # подключённые репозитории — снова в сессии (задача 43)
        cmd += f" --model {shlex.quote(model)}" if model else ""
        if not effort_ok(profile, model):               # Haiku и чужие поставщики — без усилия, и не запоминаем
            effort = ""
        cmd += effort_flag(effort)
        sid = transcripts.valid_sid(w.get("sid"))
        off = chatmcp.get(self.CHAT_MCP, w.get("sid") or "")   # выключенные интеграции чата — и после перезапуска
        cmd += chatmcp.flags(off)
        if keep:                                        # свой журнал окна — тот же разговор (--resume), иначе последний
            self.busy_sid(w.get("sid"), w["id"])        # метка окна могла указывать на чужой живой разговор
            cmd += harness.of(w).resume_args(w.get("sid"))
        else:                                           # чистый лист — новый журнал со своей меткой
            sid = str(uuid.uuid4())
            chatmcp.put(self.CHAT_MCP, sid, off)
            cmd += f" --session-id {sid}"
        result = self.close(w)
        if result != "закрыто":
            raise ValueError(result)
        failed = ""
        if closed:
            try:
                closed()
            except (OSError, ValueError, LookupError) as e:   # перенос не удался — чат снова там, где был
                if fl := repos.flags(st, path):
                    cmd = cmd.replace(fl, repos.flags(st, w["path"]))
                failed, path, wname = str(e) or "не вышло", w["path"], ""
        wid = self.tmux.new_window(wname or w["name"], path, cmd, mark=profile or "claude",
                                   by=w.get("by", "") if home else "", sid=sid)
        if not home:                                    # окно владельца: метка прежняя, иначе — кто нажал
            self.mark_by(wid, w.get("by") or uid)
        own.pop(w["id"], None)
        self.focus.move(w["id"], wid)                   # фокус-ссылка — за той же сессией в новом окне
        if routes := getattr(self.pult, "routes", None):    # ответы в Telegram на старые сообщения — в новое окно
            routes.moved(w["id"], wid)
        if model:
            own[wid] = model                            # выбор — только этого чата: «Продолжить» и перезапуск — с ним
        efforts.pop(w["id"], None)
        if effort_flag(effort):
            efforts[wid] = effort
        upd = {"window_models": own, "window_efforts": efforts, "notify_levels": notifylevel.moved(st, w["id"], wid)}
        if st.get("active") == w["id"]:                 # активная в боте — та же сессия, но чужую не делаем активной
            upd["active"] = wid
        self.pult.set_state(**upd)
        return {"id": wid, **({"model": model} if model else {}), **({"failed": failed} if failed else {})}

    def close(self, w: dict) -> str:
        return self.close_ex(w)["result"]

    def close_ex(self, w: dict, force: bool = False) -> dict:
        """Завершить сессию: текст итога и неотправленный черновик из поля ввода (если был) — панель его покажет.
        ``code`` — «background» (фоновые задачи) или «busy» (Claude не вышел): панель предложит «Закрыть
        принудительно» (``force``) — окно закрывается, фоновые задачи останавливаются, переписка остаётся в журнале."""
        if w.get("stopped"):                            # остановленная: Claude уже вышел — окно с оболочкой закрыть
            self.tmux.kill(w["id"])
            self.forget_window(w["id"])
            return {"result": "закрыто", "draft": ""}
        r = self.pult.quit_ex(w)
        if r["result"] in ("background", "busy") and force:
            if self.tmux.window(w["id"]):
                self.tmux.kill(w["id"])
            self.forget_window(w["id"])
            return {"result": "закрыто", "draft": r["draft"], "forced": True}
        if r["result"] not in ("background", "busy"):
            self.forget_window(w["id"])
        text = {"background": "не закрыл: у сессии есть фоновые задачи — их можно остановить, закрыв принудительно",
                "busy": "Claude не вышел за 20 с (возможно, занят) — можно закрыть принудительно"}.get(r["result"],
                                                                                                    "закрыто")
        return {"result": text, "draft": r["draft"], **({"code": r["result"]} if text != "закрыто" else {})}

    def forget_window(self, wid: str):
        """Окно закрыто — его модель и усилие из состояния прочь: id окон tmux после перезапуска сервера начинаются
        заново, и новое окно не должно подхватить чужой выбор (слепая проверка #323)."""
        st = self.pult.state()
        upd = {k: {i: v for i, v in (st.get(k) or {}).items() if i != wid}
               for k in ("window_models", "window_efforts") if wid in (st.get(k) or {})}
        if upd:
            self.pult.set_state(**upd)

    def clear_stopped(self) -> dict:
        """«Убрать все остановленные»: закрыть окна сессий пульта, где Claude уже вышел (осталась оболочка).
        Журналы не трогаем — разговоры остаются в «Завершённых» проекта. Окна пространств — не наши."""
        gone = []
        for w in self.tmux.windows():
            if w.get("stopped") and not w.get("space"):
                self.tmux.kill(w["id"])
                self.focus.end_window(w["id"])
                self.forget_window(w["id"])
                gone.append(w["name"])
        return {"closed": len(gone), "names": gone}

    MEDIA: ClassVar[dict] = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
                             ".gif": "image/gif", ".heic": "image/heic"}

    MEDIA_MAX = 25 * 1024 * 1024

    def focus_roots(self, rec: dict) -> list[str]:
        """Откуда фокус-ссылке можно брать картинки ленты: папка её чата или проекта и папка этого проекта на Google
        Диске (``<проект>/Входящие``, #217). inbox пульта и Диск целиком — нет: там файлы других чатов владельца."""
        roots = []
        paths = [rec.get("path") or ""]
        if kids := self.focus_spawned(rec):              # окна, открытые агентом из чата ссылки, — и их папки
            paths += [w.get("path") or "" for w in self.tmux.windows() if w["id"] in kids]
        for p in dict.fromkeys(x for x in paths if x):
            roots.append(os.path.realpath(os.path.expanduser(p)))
            if (d := self.cfg.drive_folder(p)) is not None:
                roots.append(os.path.realpath(d))
        return roots

    def media(self, path: str, roots: list[str] | None = None) -> tuple:
        """Картинка для ленты: только из inbox пульта и папок Google Диска (``drive_root``) — туда кладутся файлы
        владельца (#217); ничего другого с сервера не отдаём (путь проверяем после realpath — без «..» и ссылок)."""
        if roots is None:
            roots = [os.path.realpath(self.cfg.data / "inbox")]
            if (d := drive_inbox.drive_root(self.cfg.drive_root)) is not None:
                roots.append(os.path.realpath(d))
        real = os.path.realpath(os.path.expanduser(path or ""))
        if not path or not any(real == r or real.startswith(r + os.sep) for r in roots):
            raise LookupError("файл не найден")
        ctype = self.MEDIA.get(os.path.splitext(real)[1].lower())
        if not ctype:
            raise ValueError("это не картинка")
        try:
            st = os.stat(real)
            if st.st_size > self.MEDIA_MAX:
                raise ValueError("картинка больше 25 МБ")
            data = Path(real).read_bytes()
        except OSError:
            raise LookupError("файл не найден") from None
        return (ctype, data, {"Cache-Control": "private, max-age=3600"})

    def upload(self, name: str, data: bytes | BinaryIO, size: int | None = None, w: str = "") -> str:
        """Файл из панели → папка проекта сессии ``w`` на Google Диске (``<проект>/Входящие``, #217); нет Диска или
        папки проекта — inbox пульта, как раньше. Claude получает путь (как файлы из чата бота). Поток — кусками."""
        safe = re.sub(r"[^\w.\-]+", "_", os.path.basename(urllib.parse.unquote(name)))[-80:].lstrip(".") or "file"
        win = self.tmux.window(w) if w else None
        folder = self.cfg.drive_folder(win.get("path", "")) if win and not win.get("space") else None
        src = io.BytesIO(data) if isinstance(data, bytes | bytearray) else data
        return str(drive_inbox.save(src, safe, folder=folder, inbox=self.cfg.data / "inbox",
                                    inbox_name=f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}-{safe}",
                                    size=size))
