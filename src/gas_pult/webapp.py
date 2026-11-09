"""Mini App: пульт внутри Telegram — те же возможности, что у бота, на одном экране.

Сессии и их статусы, последний ответ и экран, поле ввода (текст и диктовка клавиатуры), голосовое
(распознаётся и встаёт в поле — проверить перед отправкой), озвучка ответа, команды ⚡, выбор модели,
клавиши диалога 1/2/3/↑/↓/⏎/Esc, новая сессия и закрытие.

Сервер — стандартная библиотека. Запрос к ``/api`` пускается, если он подписан Telegram (``initData``) владельцем
из ``owners`` или пришёл из браузера с сессией, открытой одноразовым кодом из Telegram (``webauth``).
MCP-серверы Claude Code (``mcp``), ключи API и поставщики голоса (``providers``), «▶️ Выполнить» для команд
из последнего ответа: команду берёт сервер из ответа Claude (браузер присылает только её номер и отпечаток).

    gas-pult webapp [--port 8765] [--tunnel | --url https://…]

``--tunnel`` поднимает временный HTTPS-адрес Cloudflare (нужен ``cloudflared``), ``--url`` — постоянный адрес
перед этим сервером. В обоих случаях в меню бота у владельцев появляется кнопка «📱 Панель».
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
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
from datetime import date, datetime, timedelta
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from gas_pult import (
    ago,
    asr,
    balance,
    chat_trash,
    country,
    emailcode,
    fallback,
    focus,
    helper,
    humanize,
    invites,
    models,
    modules,
    offer_report,
    offers,
    oidc,
    passkeys,
    personas,
    projects,
    providers,
    qr,
    repos,
    scenarios,
    selftest,
    setup,
    space_budget,
    space_files,
    space_sessions,
    spaces,
    tenants,
    terms,
    termwin,
    testers,
    transcripts,
    usage,
    voice,
    webauth,
    wsock,
)
from gas_pult.bot import BUSY, DIALOG, KEYS, PROMPTS, Pult
from gas_pult.commands import DANGER, FULL, SPACE_RUN, TAIL, execute, extract, in_space
from gas_pult.config import Config
from gas_pult.mcp import CONNECTORS, CONNECTORS_URL, PRESETS, Mcp
from gas_pult.openrouter import CALLBACK, OpenRouter
from gas_pult.people import TITLES, People, allowed, has_telegram, is_guest
from gas_pult.telegram import Api, TelegramError
from gas_pult.tmux import Tmux
from gas_pult.voice import catalog

MAX_AGE = 24 * 3600                     # initData старше суток не принимаем
MAX_BODY = 50 << 20                     # голосовое и файлы — до 50 МБ
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
EFFORTS = ("auto", "low", "medium", "high", "xhigh", "max")   # /effort <уровень> — Claude Code принимает аргументом
PANEL_KEYS = [("Ctrl+C", "C-c")]                     # прервать зависшую команду (в боте этой клавиши нет)
CONTEXT = re.compile(r"left [\d.]+k? \((\d+)%\)")
MODEL_LINE = re.compile(r"🤖 ([^·│\n]{2,40}?)\s*·")     # строка статуса: «🤖 Opus 5.5 · effort …»
AUDIO_EXT = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav"}
STT_TIMEOUT = 85                                          # с; панель ждёт ответа 90 с
STT_EMPTY = "Ничего не расслышал — попробуйте ещё раз"   # распознавание вернуло пустой текст
EL_PAUSE = 600                                            # ElevenLabs отказал — столько секунд к нему не ходим
STT_STREAM = "/api/stt/stream"                            # голос потоком: WebSocket → служба T-one (задача 46)
STREAM_IDLE = 30                                          # с; панель молчит дольше (ни звука, ни «конец») — закрыть
STREAM_MAX_S = 300                                        # одна диктовка — не длиннее 5 минут


def verify(init_data: str, token: str, now: float | None = None) -> dict | None:
    """Проверка подписи Telegram Mini App: возвращает пользователя или None."""
    pairs = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    got = pairs.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    want = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not got or not hmac.compare_digest(got, want):
        return None
    if (now or time.time()) - int(pairs.get("auth_date", 0)) > MAX_AGE:
        return None
    try:
        return json.loads(pairs.get("user", ""))
    except ValueError:
        return None


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


def brief(text: str, limit: int = 700) -> str:
    """«Кратко» для озвучки: первые абзацы до ~700 знаков — в наших ответах там вывод.

    Сюда приходит текст после ``transcripts.clean``: пустые строки там уже схлопнуты в один перенос, поэтому делим
    по любому переносу. Раньше делили по пустой строке — весь ответ был одним «абзацем», и «кратко» звучало целиком.
    Первый абзац длиннее лимита режем по концу предложения (нет его — по пробелу)."""
    out = ""
    for para in re.split(r"\n+", text.strip()):
        if not (para := para.strip()):
            continue
        if out and len(out) + len(para) + 1 > limit:
            break
        if len(para) > limit:                        # сюда попадаем только с пустым out
            end = max(para.rfind(c, 0, limit) for c in ".!?…")
            if end < limit // 3:
                sp = para.rfind(" ", 0, limit)
                end = (sp if sp > 0 else limit) - 1
            out = para[:end + 1]
            break
        out += para + "\n"
    return out.strip()


class Panel:
    """Действия панели поверх того же tmux и state.json, что у бота (окна, активное, голос)."""

    def __init__(self, cfg: Config):
        self.cfg, self.pult = cfg, Pult(cfg)
        # окна владельца и демо-пространств (spaces.py): запрос тестировщика ограничен его пространством (scope)
        self.pult.tmux = spaces.Routed(self.pult.tmux)
        self.tmux = self.pult.tmux
        self.auth = webauth.Auth(cfg.data / "web_sessions.json")
        self.mcp = Mcp()
        self.openrouter = OpenRouter()
        self.people = People(cfg.data / "people.json", cfg.owners)
        self.team = personas.Team(cfg.data / "team.json")      # потолок возможностей сотрудников (экран «Команда»)
        self.logins = webauth.TgLogins(cfg.data / "tg_logins.json")
        self.email = emailcode.Service(cfg.email, self.people, cfg.data / "email_codes.json")   # вход по почте
        self.keys = passkeys.Passkeys(cfg.passkeys, self.people, cfg.data / "passkeys.json")    # Face ID / ключ
        self.oidc = oidc.Oidc({"google": cfg.google, "yandex": cfg.yandex}, self.people, cfg.data / "oidc.json",
                              base=lambda: self.public_url)                                # Google, Яндекс ID
        self._bot = ""
        self.public_url = ""                                 # адрес панели снаружи — для возврата после входа
        self.previews: dict[str, tuple[str, str]] = {}  # папка → (ревизия журнала, строка превью)
        self.model_cache: dict[tuple, tuple[str, str]] = {}  # (папка, папка Claude) → (ревизия, модель ответа)
        self.mod_sections: tuple[float, dict] = (0.0, {})    # модуль → разделы чата (sections_of)
        self.mod_sched: tuple[float, dict] = (0.0, {})       # модуль → описание (schedule_of)
        self.sent: dict[str, tuple[threading.Event, float]] = {}     # id сообщения → (вставка, когда): без повторов
        self.wins: tuple[float, dict] = (0.0, {})                   # окна Claude для строки статуса (кэш 3 с)
        self.screens: dict[str, tuple[float, dict]] = {}             # окно → (когда, экран): не чаще раза в 2 с
        self.journal = self.pult.journal                             # вкладка «Команды»: все команды всех сессий
        self.login = self.pult.login                                 # вход в Claude Code (setup.py) — общий с ботом
        self._setup: tuple[float, dict] = (0, {})
        self.geo = country.GeoIP(cfg.data / "geoip")                 # страна по IP — локальная база db-ip lite
        self.ip_seen: dict[int, tuple[float, str]] = {}              # кого и когда сверяли по IP (только в памяти)
        self.offer_demos = offers.Demos()                            # демо-сессии страниц предложений (в памяти)
        self.offer_misses = offers.Misses()                          # перебор кодов предложений — по IP
        self.offer_tg = offers.TgDemos(cfg.data / "offer_tg.json")   # «Попробовать в Telegram» — токены для бота
        # дежурный помощник «? Подсказать» (helper.py): карта экранов, ответы без модели
        self.helper = helper.Helper(cfg.data)
        self.help_anon = helper.Rate(30, 600)                        # помощник на экране входа — по IP
        self._mod_ids: tuple[float, frozenset] = (0.0, frozenset())
        self.owner_seen: dict[str, float] = {}                       # окно пространства → когда владелец подключился
        self.help_calls: dict[str, float] = {}                       # окно → когда тестировщик звал на помощь
        self.balance_at = 0.0                                        # когда последний раз спрашивали баланс (раз в час)
        self.budget_told: dict[str, str] = {}                        # пространство → день, когда сказали владельцу
        self.budget_cache: dict[str, tuple[float, dict]] = {}       # пространство → (когда, запас)
        self.invite_misses = invites.Misses()                        # перебор кодов приглашений — по IP
        self.focus = focus.Focus(cfg.data / "focus.json")            # фокус-ссылки: одна сессия на устройстве
        self.projects = projects.Store(cfg.data / projects.FILE, self.pult.home)   # «Проекты» (docs/PROJECTS.md)
        self._proj: tuple[float, dict] = (0.0, {})                  # (когда сверяли с папками, данные) — раз в 30 с
        self.focus_gap: dict[str, float] = {}   # ссылка → с какого времени окна её сессии нет (перезапуск)

    def setup_status(self, fresh: bool = False) -> dict:
        """Готов ли Claude Code (для мастера на главной); ``claude auth status`` — не чаще раза в 20 с."""
        if fresh or time.time() - self._setup[0] > 20:
            self._setup = (time.time(), setup.status(self.cfg.claude))
        login = self.login.read()
        return {**self._setup[1], "login": login if login.get("w") else None}

    def need_claude(self):
        if not setup.installed(self.cfg.claude):
            raise ValueError("Claude Code на сервере не установлен — главная → «Claude не готов» → «Инструкция»")

    def window(self, wid: str) -> dict | None:
        w = self.tmux.window(wid)
        return w if w and w["cmd"] == "claude" else None

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

    def sessions(self, pool: str | None = "owner") -> list[dict]:
        """``pool`` — чей расход показывать на карточках (``cost``): «owner» или ID участника; None — ничей."""
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
                            "repos": repos.public(repos.of(st, w["path"])),
                            **ago.stamps(self.pult.acts.status(w["path"], self.pult.home_of(w), w.get("sid") or ""))})
                continue
            if w["cmd"] != "claude":
                continue
            if not w.get("mark"):                    # окна до метки: помечаем, чтобы и они потом стали «остановлена»
                self.tmux.run("set-option", "-w", "-t", w["id"], "@gas_pult", w.get("profile") or "claude")
            lines = self.tmux.screen(w["id"], 40)
            scr = "\n".join(lines)
            home = self.pult.home_of(w)                       # папка Claude того, кто открыл окно
            sid = self.follow_sid(w, wins, home)              # свой журнал окна (--session-id); "" — старое окно
            # когда менялась (ago.py): последний ход в журнале или смена экрана; ответ агента, ваше сообщение
            when = ago.stamps(self.pult.acts.status(w["path"], home, sid), self.pult.changes.look(w["id"], lines))
            ctx, mdl = CONTEXT.search(scr), MODEL_LINE.search(scr)
            rev = transcripts.revision(w["path"], home, sid)
            out.append({"id": w["id"], "name": w["name"], "path": w["path"], "branch": branch(),
                        "status": "dialog" if DIALOG.search(scr) else "busy" if BUSY.search(scr) else "idle",
                        "context": int(ctx.group(1)) if ctx else None,
                        # на чём работает сессия: строка статуса «🤖 …», иначе — модель последнего ответа в журнале
                        "model": mdl.group(1).strip() if mdl else self.model_of(w["path"], rev, home, sid),
                        "active": w["id"] == act, "channel": w["channel"], "profile": w.get("profile") or "claude",
                        "rev": rev,                                       # изменился журнал → «новый ответ»
                        "preview": self.preview(w["path"], rev, home, sid),
                        "sid": sid,                                       # id сессии Claude Code окна (добавлено)
                        "title": self.chat_title(pd, w["path"], home, sid),   # название чата («Проекты»)
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
                        **when})                                          # когда менялась (ago.py)
        return out

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

    def chat_title(self, d: dict, path: str, home, sid: str) -> str:
        """Название чата окна: своё (``projects.json``) → ``summary`` журнала → первое сообщение человека."""
        if (own := ((d.get("sessions") or {}).get(sid) or {}).get("title")) if sid else None:
            return str(own)
        f = transcripts.current(path, home, sid)
        return projects.title_of(f) if f else ""

    def project_of(self, d: dict, w: dict) -> str:
        """Проект окна: окно пространства — "" (проекты пространств — отдельным шагом)."""
        return "" if w.get("space") else (self.projects.of_path(d, w.get("path", "")) or "")

    def claude_homes(self) -> list:
        """Папки Claude Code, где могут лежать журналы сессий проекта: владельца (None) и участников."""
        out: list = [None]
        base = self.cfg.data / "people"
        with contextlib.suppress(OSError):
            out += sorted(x / "claude" for x in base.iterdir() if (x / "claude" / "projects").is_dir())
        return out

    def project_public(self, p: dict) -> dict:
        """Поля проекта для API (без личных путей: путь — с ``~``)."""
        keys = ("id", "name", "path", "paths", "origin", "created", "profile", "model", "effort", "integrations",
                "repos", "pinned", "archived", "share")
        return {**{k: p.get(k) for k in keys}, "folder": os.path.basename(p["path"].rstrip("/")) or "~"}

    def projects_list(self, ss: list[dict], q: str = "", archived: bool = False) -> list[dict]:
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
            item = {**self.project_public(p),
                    "windows": len(mine),
                    "waiting": sum(x["status"] == "dialog" for x in mine),
                    "busy": sum(x["status"] == "busy" for x in mine),
                    "chats": st["total"], "last": last,
                    "last_title": projects.title_of(st["last_file"]) if st["last_file"] else "",
                    "sessions": [x["id"] for x in mine]}
            if q and not any(q in str(v).lower() for v in (item["name"], item["folder"], item["last_title"],
                                                            *[x.get("name", "") for x in mine])):
                continue
            out.append(item)
        out.sort(key=lambda x: (not x["pinned"], not x["waiting"], -(x["last"] or 0), x["name"].lower()))
        return out

    def project(self, pid: str) -> dict:
        p = self.project_data()["projects"].get(str(pid or ""))
        if not p:
            raise LookupError("проекта нет — обновите список")
        return p

    def project_session(self, pid: str, profile: str = "", person: int | None = None, uid=None) -> dict:
        """«Новая сессия в проекте»: ещё одно окно в главной папке проекта, даже если там уже работает чат — у каждого
        свой журнал (``--session-id``). Поставщик и модель — по умолчанию проекта, если не выбраны."""
        p = self.project(pid)
        path = projects.untilde(p["path"], self.pult.home)
        if not os.path.isdir(path):
            raise ValueError("папки проекта нет на сервере")
        profile = profile or p.get("profile") or ""
        if uid is not None:
            self.check(profile, uid)
        out = self.open_in(path, profile, person, uid, model=p.get("model") or "")
        return {**out, "project": p["id"]}

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
            if w.get("space") or not (w.get("cmd") == "claude" or w.get("mark")):
                continue
            if self.projects.of_path(d, w.get("path", "")) != p["id"]:
                continue
            if sid := transcripts.valid_sid(w.get("sid")):
                by_sid[sid] = w
            elif f := transcripts.current(w["path"], self.pult.home_of(w)):
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
        ``q`` — по названию, затем по тексту журналов (с лимитом файлов и времени)."""
        p = self.project(pid)
        meta = self.project_data().get("sessions") or {}
        by_sid, legacy = self.open_sids(p)
        mine = self.my_claude(person)
        files = []
        for f in self.project_files(p):
            with contextlib.suppress(OSError):
                files.append((f.stat().st_mtime, f))
        files.sort(key=lambda x: -x[0])
        q = " ".join(str(q or "").lower().split())
        out, scanned, t0, cut = [], 0, time.time(), False
        for mt, f in files:
            if before is not None and mt >= before:
                continue
            if f.stem in by_sid or str(f) in legacy or (meta.get(f.stem) or {}).get("hidden"):
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
            out.append({"sid": f.stem, "title": title, "mtime": int(mt), "msgs": projects.prompts(f), "mine": own})
            if len(out) >= self.CHATS_PAGE:
                break
        more = bool(out) and len(out) >= self.CHATS_PAGE
        return {"chats": out, "more": more, "before": out[-1]["mtime"] if more else None, "cut": cut,
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
        if w := by_sid.get(f.stem):
            self.pult.set_state(active=w["id"])
            return {"id": w["id"], "existing": True, "sid": f.stem}
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

    def project_chat(self, pid: str, sid: str, title=None, hidden=None) -> dict:
        """Переименовать или скрыть чат проекта — только в ``projects.json``; журнал Claude Code не меняется."""
        p = self.project(pid)
        f = self.chat_file(p, sid)
        if title is not None:
            title = " ".join(str(title).split())[:projects.TITLE_MAX]
        rec = self.projects.set_chat(f.stem, p["id"], title=title, hidden=None if hidden is None else bool(hidden))
        self._proj = (0.0, {})
        return rec

    # ---------- «Удалить» сессию или чат: окно закрыто, журнал — в корзину пульта (chat_trash.py) ----------
    def session_window(self, wid: str) -> dict:
        """Окно сессии пульта для «Завершить»/«Удалить»: с Claude или остановленное (Claude вышел, осталась
        оболочка). Остальные окна tmux владельца (просто терминалы) не трогаем."""
        w = self.tmux.window(str(wid or ""))
        if not w or not (w.get("cmd") == "claude" or w.get("stopped")):
            raise LookupError("окна уже нет")
        return w

    def window_journal(self, w: dict) -> Path | None:
        """Журнал окна: по метке ``@gas_pult_sid``; старое окно без метки — последний журнал папки, но только если
        других окон Claude в этой папке нет (иначе можно унести чужой разговор)."""
        home = self.pult.home_of(w)
        if sid := transcripts.valid_sid(w.get("sid")):
            return transcripts.current(w["path"], home, sid)
        real = os.path.realpath(w["path"])
        if any(x["id"] != w["id"] and (x.get("cmd") == "claude" or x.get("stopped"))
               and os.path.realpath(x.get("path", "")) == real for x in self.tmux.windows()):
            return None
        return transcripts.current(w["path"], home)

    def chat_delete(self, wid: str = "", pid: str = "", sid: str = "") -> dict:
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
            if w.get("cmd") == "claude":
                r = self.pult.quit_ex(w)
                draft = r["draft"]
                if r["result"] == "background":
                    raise ValueError("не удалил: у сессии есть фоновые задачи — решите в самом окне")
                if r["result"] == "busy" and self.tmux.window(w["id"]):
                    self.tmux.kill(w["id"])
            else:
                self.tmux.kill(w["id"])
            self.focus.end_window(w["id"])                  # фокус-ссылки этой сессии гаснут
        out = {"result": "удалено", "closed": bool(w), "draft": draft, "trash": None}
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
        return {"trash": [{**x, "project_name": names.get(x["project"], "")} for x in items], "hidden": hidden}

    def chat_restore(self, tid: str) -> dict:
        """«Вернуть» из корзины: журнал — на место, чат снова в «Завершённых» своего проекта."""
        rec = chat_trash.restore(self.cfg.data, tid)
        self.projects.set_chat(rec["sid"], rec["project"], hidden=False)
        self._proj = (0.0, {})
        return rec

    INSTR_MAX = 20000                                   # знаков CLAUDE.md в ответе: больше — обрезаем с пометкой
    FILES_MAX = 200

    def project_info(self, pid: str) -> dict:
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
        wins = [w["id"] for w in self.tmux.windows() if not w.get("space") and (w.get("cmd") == "claude" or
                                                                               w.get("mark"))
                and self.projects.of_path(d, w.get("path", "")) == p["id"]]
        return {**self.project_public(p), "instructions": text, "instructions_cut": cut,
                "has_instructions": bool(text), "files": files, "files_dir": p.get("files") or "files",
                "chats": st["total"], "last": st["last"], "windows": wins}

    OWNER_HERE = 15 * 60                                 # с: «Владелец подключился» видно тестировщику 15 минут

    def space_fields(self, w: dict) -> dict:
        """Окно пространства: имя и название пространства, был ли владелец (``owner_here`` — когда, иначе None)."""
        slug = w.get("space")
        if not slug:
            return {}
        t = tenants.load(slug) or {}
        seen = self.owner_seen.get(w["id"])
        return {"space": slug, "space_title": t.get("title") or slug,
                "owner_here": seen if seen and time.time() - seen < self.OWNER_HERE else None}

    def invite_info(self, code: str, short: bool = False) -> dict:
        """Экран входа по приглашению: действует ли и в какое пространство (название — без путей и ролей).
        ``guest`` — можно войти без Telegram (только именем); ``kind=device`` — ссылка для входа на другое устройство
        уже существующего человека (имя не спрашиваем)."""
        rec = invites.check(code, short)            # короткий код — только из invite_check (с лимитом попыток)
        if not rec:
            return {"ok": False}
        t = tenants.load(rec["tenant"]) if tenants.enabled() else None
        out = {"ok": True, "title": (t or {}).get("title") or rec["tenant"], "guest": tenants.enabled(),
               "kind": "device" if "uid" in rec else "invite"}
        if "uid" in rec:
            p = next((x for x in self.people.list() if x["id"] == rec["uid"]), {})
            out["name"] = p.get("name") or ""
        return out

    def invite_check(self, code: str, ip: str) -> dict:
        """Короткий код с экрана входа («Есть код приглашения?»): не больше 5 промахов с IP за 10 минут."""
        self.invite_guard(ip)
        info = self.invite_info(code, short=True)
        if not info["ok"] or not info["guest"]:
            self.invite_miss(code, ip)
        return info

    def invite_guard(self, ip: str):
        if not tenants.enabled():
            raise ValueError("вход по приглашению на этом пульте выключен")
        if wait := self.invite_misses.blocked(ip):
            raise emailcode.LimitError(f"слишком много неверных кодов — попробуйте через {max(1, wait // 60)} мин.",
                                       wait)

    def invite_miss(self, code: str, ip: str):
        self.invite_misses.miss(ip)
        emailcode.log("invite_failed", ip=ip, hint=invites.norm_short(code)[:3] + "…" if code else "")
        raise ValueError("Код не подошёл: проверьте буквы и цифры. Код работает один раз и 24 часа — если он уже "
                         "использован, попросите новый.")

    def invite_enter(self, code: str, name: str, ip: str, ua: str) -> int:
        """Вход по ссылке или короткому коду без Telegram. Приглашение — новый гость (имя → сразу панель);
        ссылка для входа на другое устройство — сессия того, кому её выпустили. Код сгорает."""
        self.invite_guard(ip)
        rec = invites.check(code)
        if not rec:
            self.invite_miss(code, ip)
        dev = webauth.device(ua)
        if "uid" in rec:                                      # ссылка для входа на другое устройство
            uid = int(rec["uid"])
            if not self.people.role(uid) or not invites.redeem(code, uid):
                self.invite_miss(code, ip)
            how = "по ссылке для входа на другое устройство"
        else:
            name = " ".join(str(name or "").split())[:60]
            if not name:
                raise ValueError("Напишите, как вас зовут — так вас увидит владелец пульта")
            uid = self.people.add_guest(name, rec["role"], rec["tenant"])
            if not invites.redeem(code, uid):                 # кто-то успел раньше — гостя не оставляем
                self.people.remove(uid)
                self.invite_miss(code, ip)
            how = "по приглашению, без Telegram"
        self.people.seen(uid, dev)
        p = next((x for x in self.people.list() if x["id"] == uid), {})
        emailcode.log("invite_ok", uid=uid, ip=ip, hint=rec.get("hint", ""), kind="device" if "uid" in rec else "guest")
        t = tenants.load(rec["tenant"]) or {}
        text = (f"🎟 {p.get('name') or 'Гость'} вошёл {how} — пространство «{t.get('title') or rec['tenant']}», "
                f"{TITLES.get(p.get('role'), '')}.\nУстройство: {dev} · {time.strftime('%d.%m %H:%M')}.\n"
                "Убрать — «Настройки» → «Люди» → «Отключить»: все его входы гаснут сразу.")
        for chat in self.cfg.owners:
            try:
                self.pult.api("sendMessage", chat_id=chat, text=text)
            except (TelegramError, OSError) as e:
                print("invite:", e, file=sys.stderr, flush=True)
        return uid

    def device_link(self, uid: int, by) -> dict:
        """Ссылка для входа на другое устройство: одноразовая, 24 часа; выпускает сам человек или владелец."""
        role = self.people.role(uid)
        if not role or role == "owner":
            raise ValueError("ссылку для входа можно выпустить только человеку из «Людей»")
        slug = self.people.tenant(uid)
        if not slug or not tenants.enabled():
            raise ValueError("ссылка для входа — для тестировщиков демо-пространства")
        inv = invites.new(slug, role, by=by, uid=int(uid))
        return {"path": f"/invite/{inv['code']}", "code": inv["short"], "ttl": invites.TTL}

    def invite_qr(self, url: str, owner: bool, uid) -> bytes:
        """PNG с QR ссылки ``…/invite/<код>``: только для действующего приглашения; не владельцу — только своей ссылки
        для входа на другое устройство."""
        m = re.match(r"^https?://[A-Za-z0-9.:\[\]-]{1,200}/invite/([A-Za-z0-9_-]{16,64})$", url)
        rec = invites.check(m.group(1), short=False) if m else None
        if not rec or (not owner and rec.get("uid") != uid):
            raise LookupError("приглашения нет: истёк срок, оно использовано или отозвано")
        return qr.png_of(url)

    FOCUS_BASE = re.compile(r"^https?://[A-Za-z0-9.:\[\]-]{1,200}$")

    def focus_new(self, wid: str, by, base: str) -> dict:
        """«Фокус-ссылка» из меню сессии (владелец): ссылка ``…/#focus=<токен>`` — токен показывается один раз."""
        with self.tmux.all_spaces():
            w = self.tmux.window(str(wid or ""))
        if not w:
            raise LookupError("окна уже нет")
        base = (self.public_url or base or "").rstrip("/")
        if not self.FOCUS_BASE.match(base):
            raise ValueError("не знаю адрес панели снаружи — откройте панель по её адресу и повторите")
        f = self.focus.new(w, by)
        return {"url": f"{base}/#focus={f['token']}", "id": f["id"], "exp": f["exp"], "name": w["name"]}

    def focus_token(self, url: str) -> dict:
        """Действующая ссылка по адресу ``…/#focus=<токен>`` (для QR и «Отправить себе»)."""
        m = re.match(r"^https?://[A-Za-z0-9.:\[\]-]{1,200}/#focus=([A-Za-z0-9_-]{24,64})$", str(url or ""))
        rec = self.focus.check_token(m.group(1)) if m else None
        if not rec:
            raise LookupError("фокус-ссылка не действует: сессия завершена, ссылку отозвали или вышел срок")
        return rec

    def focus_send(self, url: str, chat) -> dict:
        """«Отправить себе в Telegram»: ссылка — сообщением в чат владельца с ботом (как в «Избранное»)."""
        rec = self.focus_token(url)
        if not chat or int(chat) < 0:
            raise ValueError("не знаю ваш чат с ботом — войдите в панель через Telegram")
        till = time.strftime("%d.%m %H:%M", time.localtime(rec["exp"]))
        text = (f"🎯 Фокус-ссылка на сессию «{rec['name']}»\n\nОткройте на нужном устройстве — там будет только чат "
                f"этой сессии, без остального пульта. Первое открытие привязывает устройство. Ссылка гаснет, когда "
                f"сессию завершат, и не позже {till}. Отозвать — «Настройки» → «Фокус-ссылки».\n\n{url}")
        self.pult.api("sendMessage", chat_id=int(chat), text=text, link_preview_options={"is_disabled": True},
                      reply_markup={"inline_keyboard": [[{"text": "Открыть в браузере", "url": url}],
                                                        [{"text": "Открыть в Telegram", "web_app": {"url": url}}]]})
        return {"ok": True}

    def focus_rec(self, cookie: str) -> dict:
        """Запрос из фокуса: действующая ссылка этого устройства и живое окно её сессии; иначе ``focus.Gone``.
        Окна нет (сессию завершили из панели или бота) — ссылка гаснет сразу."""
        rec = self.focus.by_cookie(cookie)
        with self.tmux.scope(rec.get("space")):
            w = self.tmux.window(rec["w"])
            if not w or w.get("path") != rec.get("path"):   # перезапустили из бота — то же окно папки (одно на проект)
                w = next((x for x in self.tmux.windows() if x.get("path") == rec.get("path")
                          and (x["cmd"] == "claude" or x.get("stopped"))), None)
                if w:
                    self.focus.move(rec["w"], w["id"])
                    rec = {**rec, "w": w["id"]}
        if not w:
            # перезапуск (модель, поставщик — из фокуса, из панели или из бота) закрывает окно раньше, чем открывает
            # новое: между ними окна нет. Гасим ссылку, только если окна нет дольше ``focus.GRACE``; «Завершить»
            # гасит её сразу (``end_window``)
            first = self.focus_gap.setdefault(rec["id"], time.time())
            if time.time() - first < focus.GRACE:
                raise focus.Wait("сессия перезапускается — подождите несколько секунд")
            self.focus_gap.pop(rec["id"], None)
            self.focus.end(rec["id"])
            raise focus.Gone("Сессия завершена.")
        self.focus_gap.pop(rec["id"], None)
        return rec

    def focus_meta(self, rec: dict) -> dict:
        """«meta» для фокуса: только то, что нужно одной сессии и её настройкам — без папок и имени сервера."""
        voices = catalog.installed(self.personal(rec.get("by")))
        return {"host": rec.get("name", ""), "tz": server_tz(), "projects": [],
                "commands": [t for t, _ in self.pult.command_list()],                  # команды Claude этой сессии
                "models": [] if rec.get("space") else self.cfg.models,                 # модель и поставщик этого чата
                "profiles": [] if rec.get("space") else models.public(self.pult.state(), self.countries(rec.get("by"))),
                "keys": [{"label": t, "key": k} for t, k in KEYS + PANEL_KEYS],
                "voices": [{"id": v, "label": catalog.label(v)} for v in voices], "voice": self.voice(voices),
                "focus": {"id": rec["id"], "name": rec.get("name", ""), "w": rec["w"], "space": rec.get("space"),
                          "exp": rec.get("exp")}}

    def forget_person(self, uid: int):
        """Отключить человека: роль, сессии браузера и его ссылки для входа — сразу."""
        self.people.remove(uid)
        self.team.forget(uid)
        self.auth.drop(uid)
        invites.drop_for(uid)

    def call_help(self, uid, w: dict) -> dict:
        """«Позвать на помощь» из сессии пространства: владельцам — кто, сессия, последний вопрос агента и кнопка
        «Открыть сессию». Из одной сессии — не чаще раза в 5 минут."""
        slug = self.people.tenant(uid)
        if not slug or w.get("space") != slug:
            raise ValueError("позвать на помощь можно из сессии своего демо-пространства")
        if time.time() - self.help_calls.get(w["id"], 0) < testers.HELP_EVERY:
            raise ValueError("владелец уже получил сообщение — подождите несколько минут")
        self.help_calls[w["id"]] = time.time()
        person = next((p for p in self.people.list() if p["id"] == int(uid)), {"id": uid})
        text, kb = testers.help_message(person, slug, w, self.pult.panel_url())
        for chat in self.cfg.owners:
            try:
                self.pult.api("sendMessage", chat_id=chat, text=text, **({"reply_markup": kb} if kb else {}))
            except (TelegramError, OSError) as e:
                print("help:", e, file=sys.stderr, flush=True)
        return {"ok": True}

    def space_budget(self, slug: str, fresh: bool = False) -> dict | None:
        """Запас пространства на период (space_budget.py): норма × дни + пополнения, расход по дням (журналы, цены
        API; на подписке — оценка). Бюджета нет — None. Кэш 10 с: список сессий спрашивает часто."""
        hit = self.budget_cache.get(slug)
        if hit and not fresh and time.time() - hit[0] < 10:
            return hit[1]
        t = tenants.load(slug) or {}
        cfg = t.get("budget")
        if not cfg:
            return None
        today = date.today()
        first, _ = space_budget.period(cfg, today)
        home = tenants.paths(slug)["claude"]
        accs = self.pult.meter.days(home, first.isoformat(), detail=True) if home.is_dir() else {}
        seen = {d: round(x["usd"], 4) for d, x in accs.items()}
        spent = space_budget.remember(slug, seen, first)     # максимум записанного: прошлые дни не уменьшаются
        b = space_budget.state(cfg, spent, today, space_budget.extra(slug, first),
                               estimate=(t.get("profile") or "") == "claude",
                               source=usage.source(usage.merge(*accs.values())))
        b["text"] = space_budget.text(b)
        self.budget_cache[slug] = (time.time(), b)
        return b

    def budget_watch(self, slug: str, b: dict):
        """Владельцу — на 80% и 100% запаса (раз за период; после пополнения — заново) и при потолке дня (раз в день);
        с кнопкой «+ добавить»."""
        t = tenants.load(slug) or {}
        title = t.get("title") or slug
        end = date.fromisoformat(b["end"]).strftime("%d.%m")
        msgs = []
        if (x := space_budget.warn_due(slug, b)) is not None:
            if x >= 1:
                msgs.append(f"💸 Запас пространства «{title}» исчерпан: ${b['spent']:.2f} из ${b['reserve']:.2f} "
                            f"(период до {end}). Тестировщик не может писать агенту до нового периода или пополнения.")
            else:
                msgs.append(f"⚠️ Пространство «{title}» потратило {round(b['pct'] * 100)}% запаса: ${b['spent']:.2f} "
                            f"из ${b['reserve']:.2f} (период до {end}). {b['text'][0].upper() + b['text'][1:]}.")
        today = time.strftime("%Y-%m-%d")
        if b["reason"] == "day" and self.budget_told.get(slug) != today:
            self.budget_told[slug] = today
            msgs.append(f"⏸ Пространство «{title}» дошло до потолка дня: ${b['today']:.2f} из ${b['day_cap']:.2f}. "
                        "Тестировщик продолжит завтра — или пополните запас.")
        kb = {"inline_keyboard": [[{"text": "➕ Добавить", "callback_data": f"bt:{slug}"}]]}
        for text in msgs:
            for chat in self.cfg.owners:
                try:
                    self.pult.api("sendMessage", chat_id=chat, text=text, reply_markup=kb)
                except (TelegramError, OSError) as e:
                    print("budget:", e, file=sys.stderr, flush=True)

    def check_budget(self, slug: str):
        """Тестировщик пишет, отвечает или открывает сессию: запас периода исчерпан (или потолок дня) — отказ
        (ValueError) с понятным текстом; владельцу — сообщения (budget_watch)."""
        b = self.space_budget(slug, fresh=True)
        if not b:
            return
        self.budget_watch(slug, b)
        if not b["over"]:
            return
        if b["reason"] == "day":
            raise ValueError(f"На сегодня потрачен потолок дня (${b['today']:.2f} из ${b['day_cap']:.2f}). Завтра "
                             "можно продолжить — владелец получил сообщение.")
        nxt = (date.fromisoformat(b["end"]) + timedelta(days=1)).strftime("%d.%m")
        raise ValueError(f"Запас пространства на период исчерпан (${b['spent']:.2f} из ${b['reserve']:.2f}). Владелец "
                         f"получил сообщение и может пополнить запас; новый период — с {nxt}.")

    def budget_add(self, slug: str, usd: float, by: int | None = None) -> dict:
        """«+ добавить» из панели владельца: пополнить запас текущего периода."""
        t = tenants.load(slug) or {}
        if not t.get("budget"):
            raise ValueError("у пространства нет бюджета — sudo bin/pult-tenant create <slug> --budget <USD>")
        first, _ = space_budget.period(t["budget"], date.today())
        space_budget.top_up(slug, usd, first, by)
        return self.space_budget(slug, fresh=True)

    def owner_join(self, w: dict) -> dict:
        """Владелец подключился к окну пространства (сам — «Подключиться» — или написал, ответил на вопрос)."""
        if not w.get("space"):
            raise ValueError("это не сессия демо-пространства")
        self.owner_seen[w["id"]] = time.time()
        return {"ok": True, "space": w["space"]}

    def space_task(self, slug: str, name: str, task: str) -> dict:
        """«Поставить задачу» владельцем: новая сессия в пространстве с понятным именем; первое сообщение —
        задание (уходит, когда Claude в окне готов принять текст). Тестировщик видит её у себя этой сессией."""
        slug, name, task = tenants.check_slug(slug), name.strip()[:60], task.strip()
        if not tenants.enabled() or not tenants.load(slug):
            raise ValueError("нет такого пространства")
        if not name:
            raise ValueError("назовите сессию — так её увидит тестировщик")
        wid = self.new_in_space(slug, name)["id"]       # своя папка, как у сессий тестировщика
        self.owner_seen[wid] = time.time()
        if task:
            threading.Thread(target=self.first_message, args=(wid, task), daemon=True).start()
        return {"id": wid, "name": name}

    def first_message(self, wid: str, text: str, timeout: float = 90):
        """Дождаться Claude в новом окне и отправить первое сообщение (то же, что «Отправить» в панели)."""
        end, why = time.time() + timeout, "Claude не запустился"
        while time.time() < end:
            if w := self.window(wid):
                try:
                    self.pult.to_claude(w, text)
                    return True
                except Exception as e:                    # не готов ещё — пробуем, пока не выйдет время
                    why = str(e)
            time.sleep(2)
        print(f"задание в {wid} не отправлено: {why}", flush=True)
        return False

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
        if w.get("cmd") == "claude":
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

    # ---------- расход (usage.py) ----------
    def cost_of(self, w: dict, pool: str | None, st: dict) -> dict | None:
        """Расход текущей сессии окна — если окно в пуле того, кто смотрит (чужие учётки не показываем)."""
        own_space = pool == "owner" and w.get("space")      # владелец видит расход пространств
        if pool is None or (self.pult.pool_of(w) != pool and not own_space):
            return None
        s = self.pult.meter.session(w["path"], self.pult.home_of(w), sid=w.get("sid") or "")
        if not s:
            return None
        lim = usage.limits(st)["session"] if pool == "owner" and not own_space else None
        by = self.pult.opened_by(w)
        name = next((p.get("name") or (f"@{p['username']}" if p.get("username") else "")
                     for p in self.people.list() if p["id"] == by), "") if by else ""
        return {**usage.public(s["total"]), "today": usage.public(s["today"]), "session": s["id"][:8],
                "limit": None if lim is None else round(lim + (st.get("cost_extra") or {}).get(s["id"], 0.0), 2),
                "paused": (st.get("cost_paused") or {}).get(w["id"]) if pool == "owner" and not own_space else None,
                **({"by": {"id": by, "name": name}} if by else {})}

    def pool_home(self, pool: str):
        """Папка Claude Code пула: владелец — None (~/.claude); участник — его папка (не создаём, если её нет)."""
        if pool == "owner":
            return None
        if pool.startswith("space:"):                    # тестировщик: расход его пространства
            d = tenants.paths(pool.removeprefix("space:"))["claude"]
            return d if d.is_dir() else False
        d = self.cfg.data / "people" / pool / "claude"
        return d if d.is_dir() else False

    def cost_summary(self, pool: str | None) -> dict | None:
        """Итог пула за сегодня (по местному дню сервера) и, владельцу, лимиты и паузы."""
        if pool is None:
            return None
        home = self.pool_home(pool)
        day = usage.empty() if home is False else self.pult.meter.day(home)
        out = {"pool": "owner" if pool == "owner" else "own", "today": usage.public(day),
               "prices_checked": usage.PRICES_CHECKED, "prices_url": usage.PRICES_URL,
               "provider_prices_checked": models.PROVIDER_PRICES_CHECKED}
        if pool.startswith("space:"):                    # тестировщик: дневной бюджет его пространства
            out["budget"] = self.space_budget(pool.removeprefix("space:"))
        if pool == "owner":
            st = self.pult.state()
            out |= {"limits": usage.limits(st), "paused": len(st.get("cost_paused") or {})}
        return out

    def cost_limits(self) -> dict:
        st = self.pult.state()
        return {"limits": usage.limits(st), "paused": st.get("cost_paused") or {},
                "prices_checked": usage.PRICES_CHECKED, "prices_url": usage.PRICES_URL}

    def set_cost_limits(self, b: dict) -> dict:
        """Лимиты из «Настроек»; сразу сверяем — снятые/поднятые лимиты снимают паузы, новые — ставят."""
        self.pult.set_state(cost_limits=usage.check_limits(b))
        self.pult.cost_watch(self.pult.state(), force=True)
        return self.cost_limits()

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
        mates = [x for x in wins if x["id"] != w["id"] and x.get("cmd") == "claude" and not x.get("space")
                 and os.path.realpath(x.get("path", "")) == real and self.pult.home_of(x) == home]
        if any(not transcripts.valid_sid(x.get("sid")) for x in mates):
            return sid                                  # рядом старое окно без метки — его журнал не забираем
        if nxt := transcripts.follow(w["path"], home, sid, {x["sid"] for x in mates}):
            self.tmux.set_sid(w["id"], nxt)
            w["sid"] = sid = nxt
        return sid

    def model_of(self, path: str, rev: str, home=None, sid: str = "") -> str:
        """Модель последнего ответа из журнала — когда строка статуса её не показывает; кэш по ревизии журнала."""
        key = (path, str(home or ""), sid)
        if self.model_cache.get(key, (None,))[0] != rev:      # (None,) — у нового окна журнала ещё нет (rev "")
            self.model_cache[key] = (rev, transcripts.model_title(transcripts.last_model(path, home=home, sid=sid)))
        return self.model_cache[key][1]

    def preview(self, path: str, rev: str, home=None, sid: str = "") -> str:
        """Строка о последнем шаге сессии; пересчитывается, только когда журнал изменился."""
        key = (f"{home}|{path}" if home else path) + (f"|{sid}" if sid else "")
        if self.previews.get(key, (None,))[0] != rev:
            self.previews[key] = (rev, transcripts.preview(path, home=home, sid=sid))
        return self.previews[key][1]

    # ---------- страна человека (country.py) ----------
    def countries(self, uid) -> set[str]:
        """Страны, по которым проверяем поставщика для этого человека: признаки и страна сервера; не выбрана — пусто."""
        return country.check_set(self.people.country(uid), self.cfg.region)

    def check(self, profile: str, uid):
        """Поставщик не разрешён для какой-то из стран человека — отказ ровно этим текстом."""
        if not models.allowed(profile or "claude", self.countries(uid)):
            raise ValueError(country.DENY)

    def mark_by(self, wid: str, uid):
        """Чьё окно — для запасных (``fallback.Switcher``): по странам этого человека."""
        if uid is not None:
            self.tmux.run("set-option", "-w", "-t", wid, "@gas_pult_by", str(uid))

    def seen_ip(self, uid, ip: str, force: bool = False):
        """Страна по IP — при входе (``force``) и не чаще ``IP_EVERY`` на запросах. IP не храним — код и время."""
        if uid is None:
            return
        now, last = time.time(), self.ip_seen.get(uid)
        if not force and last and last[1] == ip and now - last[0] < country.IP_EVERY:
            return
        self.ip_seen[uid] = (now, ip)
        rec, tell = self.people.set_country(uid, ip_cc=self.geo.lookup(ip) or "", ip_at=int(now))
        if tell:
            self.tell_owners(uid, rec)

    def set_country(self, uid, code: str) -> dict:
        c = country.norm(code)
        if not c:
            raise ValueError("нет такой страны — нужен код из двух букв, например NL")
        rec, tell = self.people.set_country(uid, chosen=c)
        if tell:
            self.tell_owners(uid, rec)
        return self.country_info(uid)

    def tell_owners(self, uid, rec: dict):
        """Признаки страны разошлись — одна строка владельцам (имя/ID и коды стран, без номера и IP)."""
        p = next((x for x in self.people.list() if x["id"] == uid), {})
        line = country.notice(p.get("name") or (f"@{p['username']}" if p.get("username") else "человек"), uid, rec)
        for chat in self.cfg.owners:
            try:
                self.pult.api("sendMessage", chat_id=chat, text=line)
            except (TelegramError, OSError) as e:
                print("country:", e, file=sys.stderr, flush=True)

    def country_info(self, uid) -> dict:
        rec = self.people.country(uid)
        return {**country.public(rec), **self.geo.info(), "need": not country.norm(rec.get("chosen")),
                "server": (self.cfg.region or "").upper(), "check": sorted(self.countries(uid)),
                "options": [{"code": c, "name": country.name(c)} for c in country.COMMON], "bot": self._bot}

    def is_owner(self, uid) -> bool:
        try:
            return int(uid) in self.cfg.owners
        except (TypeError, ValueError):
            return False

    def ui(self, uid, role: str | None) -> dict:
        """Вид панели человека (``personas.view``): роль интерфейса, возможности, потолок, справочник.

        Владелец пульта — всегда «Моё пространство» с видом разработчика: экран выбора роли ему сам не показывается
        (``onboarded``), другой вид — только временный просмотр в панели («Демо и тесты»), на сервере не хранится."""
        rec = self.people.ui(uid)
        if self.is_owner(uid):
            rec = {**rec, "persona": personas.DEFAULT, "onboarded": True}
        if sp := self.space_info(uid):                 # тестировщик: вид — тот, что задан пространству
            rec = {**rec, "persona": sp["persona"], "onboarded": True}
        out = personas.view(rec, personas.access(role), self.team, uid, self.people.prefs(uid)["lang"])
        own = self.is_owner(uid)                       # fixed — что владелец у себя не прячет (иначе ушёл бы в чат)
        return {**out, "own_space": own, "fixed": sorted(personas.SPACE_FIXED) if own else [],
                **({"space": sp} if sp else {})}

    def space_info(self, uid) -> dict | None:
        """Пространство тестировщика для панели: имя, название, вид. Не тестировщик — None."""
        slug = self.people.tenant(uid)
        if not slug:
            return None
        t = tenants.load(slug) if tenants.enabled() else None
        return {"slug": slug, "title": (t or {}).get("title") or slug, "ready": t is not None,
                "persona": (t or {}).get("persona") or tenants.DEFAULT_PERSONA}

    def set_ui(self, uid, role: str | None, b: dict) -> dict:
        """Выбор человека: ``persona`` (сменить роль целиком), ``add`` ({cap: true|false}) — тумблеры. Простой режим
        (#80) следует за видом: бизнес-роли — чат, разработчик — прежний интерфейс."""
        add, persona = b.get("add"), None if b.get("persona") is None else str(b["persona"])
        owner = self.is_owner(uid)
        if self.people.tenant(uid):
            raise ValueError("вид панели в демо-пространстве задаёт владелец пульта")
        if owner and persona not in (None, personas.DEFAULT):
            raise ValueError("ваше пространство — всегда вид разработчика; посмотреть как бизнес — «Демо и тесты», "
                             "без сохранения")
        rec = personas.change(self.people.ui(uid), personas.access(role), self.team, uid, persona,
                              add if isinstance(add, dict) else None)
        if owner and personas.simple(personas.effective(personas.DEFAULT, rec.get("added"), rec.get("hidden"),
                                                         personas.ALL)):
            raise ValueError("в вашем пространстве сессии не прячутся — посмотреть без них можно в «Демо и тестах»")
        self.people.set_ui(uid, rec)
        out = self.ui(uid, role)
        if not owner:                                  # простой режим следует за выбором человека — не владельца
            self.people.set_prefs(uid, simple=out["simple"])
        return out

    def prefs(self, uid, role: str | None) -> dict:
        """Настройки панели; ``simple`` — по виду, если человек выбрал роль или владелец закрыл ему инженерное."""
        p, v = self.people.prefs(uid), self.ui(uid, role)
        if self.is_owner(uid):
            return {**p, "simple": False}              # владелец — всегда полный пульт в своём пространстве
        return {**p, "simple": v["simple"] if v["chosen"] or "cap.dev_sessions" not in v["ceiling"]
                else p["simple"]}

    def owner_space_fix(self):
        """Один раз при старте: у владельца вид не разработчика или простой режим — это не его выбор (так было после
        #82: экран выбора роли показывался и владельцу). Сбросить, прежние файлы — рядом с отметкой времени."""
        for o in self.cfg.owners:
            if self.people.ui(o).get("persona") in (None, personas.DEFAULT) and not self.people.prefs(o)["simple"]:
                continue
            stamp = time.strftime("%Y%m%d-%H%M%S")
            for f in (self.people.ui_store, self.people.prefs_store):
                if f.is_file():
                    bak = f.with_name(f"{f.name}.bak-{stamp}")
                    bak.write_bytes(f.read_bytes())
                    bak.chmod(0o600)
            self.people.set_ui(o, {**self.people.ui(o), "persona": personas.DEFAULT, "onboarded": True})
            self.people.set_prefs(o, simple=False)
            print(f"владелец: вид разработчика и полный режим восстановлены (бэкап *.bak-{stamp})", flush=True)

    def team_info(self) -> dict:
        """Экран «Команда»: общая политика для сотрудников и поправки по людям (только участники — staff)."""
        people = [{"id": p["id"], "name": p.get("name") or "", "username": p.get("username") or "",
                   **{f"own_{k}": v for k, v in self.team.person(p["id"]).items()},
                   "ceiling": sorted(self.team.ceiling(p["id"])), "sections": self.team.sections(p["id"])}
                  for p in self.people.list() if p.get("role") == "member"]
        return {**self.team.policy(), "people": people, "catalog": personas.catalog()}

    def people_list(self) -> list[dict]:
        """Люди для панели: страна — кодами и временем, без хеша номера."""
        return [{**p, "country": country.public(p.get("country"))} for p in self.people.list()]

    def personal(self, uid) -> bool:
        """Некоммерческие голоса (Silero) — только владельцу и только при ``personal_voices = true``."""
        try:
            return self.cfg.personal_voices and int(uid) in self.cfg.owners
        except (TypeError, ValueError):
            return False

    def meta(self, uid=None) -> dict:
        voices = catalog.installed(self.personal(uid))
        if sp := self.space_info(uid):                 # тестировщик: ни папок, ни имени сервера владельца
            return {"host": sp["title"], "tz": server_tz(), "commands": [t for t, _ in self.pult.command_list()],
                    "models": [], "keys": [{"label": t, "key": k} for t, k in KEYS + PANEL_KEYS], "profiles": [],
                    "projects": [], "voices": [{"id": v, "label": catalog.label(v)} for v in voices],
                    "voice": self.voice(voices), "space": sp}
        return {"host": self.cfg.host, "tz": server_tz(),
                "commands": [t for t, _ in self.pult.command_list()],
                "models": self.cfg.models,
                "keys": [{"label": t, "key": k} for t, k in KEYS + PANEL_KEYS],
                "profiles": models.public(self.pult.state(), None if uid is None else self.countries(uid)),
                "projects": [self.pult.short(p) for p in self.pult.projects()],
                "voices": [{"id": v, "label": catalog.label(v)} for v in voices],
                "voice": self.voice(voices)}

    def voice(self, voices: list[str] | None = None, personal: bool = False) -> str | None:
        """Голос из настроек, если он доступен этому человеку; иначе — первый доступный (Silero → Piper)."""
        voices = catalog.installed(personal) if voices is None else voices
        v = self.pult.state().get("voice")
        return v if v in voices else (voices[0] if voices else None)

    def login_methods(self) -> dict:
        """Способы входа для экрана входа (без входа): только «включено ли», без настроек."""
        return {"telegram": True, "owner_code": True, "email": self.email.enabled, "passkey": self.keys.enabled,
                "invite": tenants.enabled(),                                         # «Есть код приглашения?»
                **self.oidc.methods()}                                              # google, yandex

    def key_label(self, uid) -> str:
        """Подпись ключа в менеджере паролей устройства: имя человека, без Telegram ID."""
        p = next((x for x in self.people.list() if x["id"] == uid), {})
        who = p.get("name") or (f"@{p['username']}" if p.get("username") else "") or TITLES.get(p.get("role"), "")
        return f"Пульт {self.cfg.host} · {who}"

    def login_start(self, ip: str, ua: str) -> str:
        rid, code = self.auth.start()
        text = (f"🔐 Вход в панель gas-pult из браузера\n\nКод: {code}\n\nДействует 5 минут. "
                f"Откуда: {ip or '?'} · {ua[:80] or 'браузер'}.\nЕсли входите не вы — просто не вводите код.")
        for chat in self.cfg.owners:
            self.pult.api("sendMessage", chat_id=chat, text=text)
        return rid

    # ---------- предложения (offers.py): страница /offer/<код> без входа ----------
    def offer_country_ok(self, cc: str) -> bool:
        """Есть ли для страны хоть один поставщик моделей (с учётом страны сервера) — как при выборе страны."""
        cs = country.check_set({"chosen": cc}, self.cfg.region)
        return any(models.allowed(p["id"], cs) for p in models.PROFILES)

    def offer_wizard(self, o: dict, s: dict, b: dict) -> dict:
        """Шаги мастера «Подключить» до входа: условия, страна, модуль. В демо-сессии — только версия условий,
        код страны и id модуля (без ПДн); к владельцу уходят вместе с запросом доступа."""
        w, step = s["wizard"], str(b.get("step", ""))
        if step == "terms":
            if str(b.get("version", "")) != terms.VERSION:
                raise ValueError("условия обновились — обновите страницу")
            w["terms"] = terms.VERSION
        elif step == "country":
            cc = country.norm(b.get("code"))
            if not cc:
                raise ValueError("нет такой страны — нужен код из двух букв, например NL")
            if not self.offer_country_ok(cc):
                w.pop("country", None)
                raise ValueError(country.DENY)
            w["country"] = cc
        elif step == "module":
            mid = str(b.get("id", ""))
            if mid not in o["modules"]:
                raise ValueError("этого модуля нет в предложении")
            w["module"] = mid
        else:
            raise ValueError("нет такого шага")
        return {"wizard": w}

    def offer_login(self, o: dict, s: dict, ip: str, ua: str) -> dict:
        """Шаг «Войти через Telegram»: обычный вход (TgLogins) с пометкой предложения — владелец увидит, откуда
        человек и что он выбрал. Сессий не создаёт и модель не тратит: всё — после решения владельца."""
        w = s["wizard"]
        if w.get("terms") != terms.VERSION:
            raise ValueError("сначала примите условия использования")
        if not w.get("country"):
            raise ValueError("сначала выберите страну")
        if w.get("module") not in o["modules"]:
            raise ValueError("сначала выберите модуль")
        m = next((x for x in modules.catalog() if x["id"] == w["module"]), {"title": w["module"]})
        bot = self.offer_bot()
        rid, nonce = self.logins.start(ip, ua, offer={
            "business": o["business"], "hint": offers.hint(o["code"]), "module": w["module"],
            "module_title": m["title"], "country": w["country"], "terms": w["terms"]})
        return {"id": rid, "link": f"https://t.me/{bot}?start=login_{nonce}", "ttl": webauth.LOGIN_TTL}

    def offer_bot(self) -> str:
        """Имя бота для ссылок со страницы предложения; Telegram недоступен — понятная ошибка, без подробностей."""
        try:
            return self.bot_username()
        except (TelegramError, OSError, KeyError):
            raise ValueError("бот пульта сейчас недоступен — попробуйте через несколько минут") from None

    def offer_telegram(self, o: dict, mid: str, back: str) -> dict:
        """«Попробовать в Telegram»: короткоживущий токен (не код предложения) → ссылка на бота с ?start=demo_…"""
        if mid not in o["modules"]:
            raise ValueError("этого модуля нет в предложении")
        bot = self.offer_bot()
        tok = self.offer_tg.issue(o["code"], mid, back)
        return {"link": f"https://t.me/{bot}?start=demo_{tok}", "ttl": offers.TG_TTL}

    # ---------- помощник «?» (helper.py) ----------
    def module_ids(self) -> frozenset:
        """id модулей каталога — чтобы принимать от клиента только известные (кэш минуту)."""
        if time.time() - self._mod_ids[0] > 60:
            self._mod_ids = (time.time(), frozenset(m["id"] for m in modules.catalog()))
        return self._mod_ids[1]

    def help_ask(self, role: str, uid, b: dict) -> dict:
        """Вопрос вошедшего: роль — с сервера; от клиента — только экран, шаг, модуль и сам вопрос."""
        v = self.ui(uid, role)                         # вид — с сервера: чипы роли и переходы по возможностям
        return self.helper.ask(role, b.get("ctx"), str(b.get("q", "")), str(b.get("chip", "")),
                               who=[self.helper.who_key("u", uid)], extra={"module_ids": self.module_ids()},
                               lang=str(b.get("lang", "ru")),
                               ui={k: v[k] for k in ("persona", "caps", "ceiling")})

    def help_guest(self, o: dict, sid: str, ip: str, b: dict) -> dict:
        """Вопрос гостя предложения: только экраны страницы и мастера и публичное о модулях ЕГО предложения;
        частота — по cookie демо и по IP (хешами)."""
        cat = {m["id"]: m for m in modules.catalog()}
        mods = [{"id": x, "title": cat[x]["title"], "about": cat[x]["about"]} for x in o["modules"] if x in cat]
        return self.helper.ask("guest", b.get("ctx"), str(b.get("q", "")), str(b.get("chip", "")),
                               who=[self.helper.who_key("g", sid), self.helper.who_key("ip", ip)],
                               extra={"modules": mods})

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
            self.wins = (now, {w["id"]: w for w in self.tmux.windows() if w["cmd"] == "claude"})
        if not (w := self.wins[1].get(wid)):
            raise LookupError("окна уже нет")
        scr = self.screens.get(wid)
        if not scr or now - scr[0] >= 2:
            scr = self.screens[wid] = (now, self.pult.screen_state(wid))
        home = self.pult.home_of(w)
        return {**self.pult.activity(w, scr[1]), "rev": transcripts.revision(w["path"], home, w.get("sid") or "")}

    def slash(self, w: dict, cmd: str) -> list[str]:
        return self.pult.run_slash(w["id"], cmd)

    def command(self, w: dict, i: int) -> dict:
        cmds = self.pult.command_list()
        if not 0 <= i < len(cmds):
            raise ValueError("команда устарела — обновите панель")
        cmd = cmds[i][1]
        if cmd == "models":
            return {"models": self.cfg.models}
        if cmd in PROMPTS:
            self.send(w, PROMPTS[cmd])
            return {"sent": True}
        if cmd.startswith("/"):
            return {"lines": self.slash(w, cmd)}
        self.send(w, cmd)
        return {"sent": True}

    def effort(self, w: dict, level: str) -> list[str]:
        if level not in EFFORTS:
            raise ValueError("такого уровня усилий нет")
        return self.slash(w, f"/effort {level}")

    def model(self, w: dict, name: str, uid=None) -> dict:
        """Модель — только для этого чата (задача 37): окно перезапускается с ``--model`` у того же поставщика, разговор
        продолжается. ``/model`` Claude Code не шлём: он сохраняет выбор в общие настройки (``~/.claude/settings.json``)
        — модель менялась во всех сессиях. Модель по умолчанию для новых — отдельно: ``default_model``."""
        if name not in self.cfg.models:
            raise ValueError("такой модели нет в настройках (models)")
        if w.get("space"):
            raise ValueError("в сессии пространства модель задаёт его профиль")
        return self.restart(w, w.get("profile") or (w.get("mark") if w.get("mark") in models.BY_ID else "claude"),
                            keep=True, uid=uid, model=name)

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

    def tty_window(self, wid: str, owner: bool, write: bool) -> dict:
        """Окно для живого терминала (задача 50). Владельцу — любое окно его tmux, окно gp-term и окна пространств
        (через их tmux). Участнику — только окна сессий пульта; писать — только пока в окне работает Claude
        (остановленная сессия — командная строка сервера, она только владельцу)."""
        w = self.tmux.window(str(wid or ""))
        if not w:
            raise LookupError("окна уже нет")
        if owner:
            return w
        if w.get("space") or w.get("name") == termwin.WINDOW:
            raise ValueError("это окно — только владельцу пульта")
        if not (w.get("cmd") == "claude" or w.get("mark")):
            raise ValueError("это не окно сессии пульта")
        if write and (w.get("cmd") != "claude" or w.get("stopped")):
            raise ValueError("Claude в этой сессии остановлен — в командную строку сервера вводит только владелец")
        return w

    @staticmethod
    def tty_kind(w: dict) -> str:
        """Что за окно — для подписи в панели: сессия, окно терминала gp-term, остановленная сессия, своё окно."""
        if w.get("name") == termwin.WINDOW:
            return "term"
        if w.get("stopped"):
            return "stopped"
        return "session" if w.get("cmd") == "claude" or w.get("mark") else "shell"

    def key(self, w: dict, key: str) -> list[str]:
        if key not in {k for _, k in KEYS + PANEL_KEYS} and not re.fullmatch(r"[1-9]", key):   # цифры — пункты
            raise ValueError("неизвестная клавиша")
        self.tmux.keys(w["id"], key)
        time.sleep(1)
        return self.tmux.screen(w["id"], 40)

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

    def mcp_finish(self, w: dict, url: str, name: str, home=None) -> str:
        """Адрес страницы после входа (http://localhost…/callback?code=…) → в поле «URL >» Claude Code."""
        if self.pult.home_of(w) != home:
            raise ValueError("это сессия другого человека — вход начните заново из своих «Интеграций»")
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
                    marks = [i for i, x in enumerate(lines) if "❯" in x]
                    sel = min(marks, key=lambda i: abs(i - tgt)) if marks and tgt is not None else None
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
            self.pult.set_state(active=w["id"])
            return {"id": w["id"], "existing": w["name"]}
        return {"id": self.open_in(path, profile, person, uid)["id"]}

    def open_in(self, path: str, profile: str = "", person: int | None = None, uid=None, resume: str = "",
                model: str = "", name: str = "") -> dict:
        """Новое окно с Claude в папке — без правила «одно окно на папку»: у окна свой журнал (``--session-id`` и
        метка ``@gas_pult_sid``) или продолжение выбранного (``resume`` — ``--resume <id>``). ``model`` — модель только
        этого чата (``window_models``), как у «Модель» в меню."""
        self.need_claude()
        base = name or (os.path.basename(path) if path != self.pult.home else "home")
        home = self.pult.claude_dir(person) if person is not None else None
        st = self.pult.state()
        cmd = models.command(self.cfg.claude, profile, st, home=home)
        if model:
            cmd += f" --model {shlex.quote(model)}"
        cmd += repos.flags(st, path)                                 # подключённые к папке репозитории (задача 43)
        sid = transcripts.valid_sid(resume) or str(uuid.uuid4())     # свой журнал окна: --session-id или --resume
        cmd += f" --resume {sid}" if resume else f" --session-id {sid}"
        wid = self.tmux.new_window(f"{base}-{time.strftime('%H%M')}", path, cmd,
                                   mark=profile or "claude", by=str(person) if home else "", sid=sid)
        if not home:
            self.mark_by(wid, uid)
        upd: dict = {"active": wid}
        if model:
            upd["window_models"] = {**(st.get("window_models") or {}), wid: model}
        self.pult.set_state(**upd)
        return {"id": wid, "sid": sid}

    def new_in_space(self, slug: str, name: str = "") -> dict:
        """Новая сессия в демо-пространстве: своя папка ``home/projects/<имя>`` (``space_sessions.create``) и окно
        ``tenants.new_window`` в ней — от пользователя пространства, с его CLAUDE_CONFIG_DIR и моделью. Функция
        выключена (нет настройки) — понятный отказ."""
        if not tenants.enabled():
            raise ValueError("демо-пространство ещё не готово — владелец пульта включит его")
        name = space_sessions.folder_name(name) if str(name or "").strip() else f"Сессия {time.strftime('%d.%m %H-%M')}"
        path = space_sessions.create(slug, name)
        raw = tenants.new_window(slug, path.name, str(path))
        return {"id": spaces.wid_of(slug, raw), "name": path.name, "folder": path.name}

    # ---------- сессии пространства: закрыть, продолжить, удалить в корзину (space_sessions.py) ----------
    def space_windows(self, slug: str) -> list[dict]:
        return [w for w in self.tmux.windows() if w.get("space") == slug]

    def space_list(self, slug: str) -> dict:
        """Закрытые сессии (папки без окна) и корзина — для «Закрытые» в панели тестировщика."""
        open_paths = {w.get("path", "") for w in self.space_windows(slug)} | space_sessions.open_paths(slug)
        drafts = self.space_drafts().get(slug, {})
        closed = [{**x, "draft": bool(drafts.get(x["folder"]))} for x in space_sessions.closed(slug, open_paths)]
        return {"closed": [{k: v for k, v in x.items() if k != "path"} for x in closed],
                "trash": space_sessions.trash_list(slug), "keep_days": space_sessions.KEEP_DAYS}

    def space_drafts(self) -> dict:
        try:
            return json.loads((self.cfg.data / "space-drafts.json").read_text())
        except (OSError, ValueError):
            return {}

    def space_draft_set(self, slug: str, folder: str, text: str):
        d = self.space_drafts()
        if text:
            d.setdefault(slug, {})[folder] = text[:20000]
        else:
            d.get(slug, {}).pop(folder, None)
        webauth.write_private(self.cfg.data / "space-drafts.json", json.dumps(d, ensure_ascii=False))

    def space_close(self, slug: str, wid: str, force: bool = False) -> dict:
        """«Закрыть»: агент выходит штатно, окно закрывается; папка, файлы и разговор остаются. Агент работает —
        без ``force`` не закрываем (``busy``: панель спросит «прервать работу?»). Черновик из поля — сохраняем."""
        w = self.tmux.window(wid)
        if not w or w.get("space") != slug:
            raise LookupError("окна уже нет")
        folder = os.path.basename(w.get("path", ""))
        if w["cmd"] != "claude":                          # Claude уже вышел — окно с оболочкой просто закрыть
            self.tmux.kill(wid)
            return {"result": "closed", "folder": folder, "draft": ""}
        if not force and BUSY.search("\n".join(self.tmux.screen(wid, 40))):
            return {"result": "busy", "folder": folder}
        r = self.pult.quit_ex(w)
        if r["result"] == "busy" and force:               # не вышел за 20 с — закрываем окно (разговор в журнале)
            self.tmux.kill(wid)
            r["result"] = "closed"
        if r.get("draft"):
            self.space_draft_set(slug, folder, r["draft"])
        return {"result": r["result"], "folder": folder, "draft": r.get("draft", "")}

    def space_resume(self, slug: str, folder: str) -> dict:
        """«Продолжить»: окно в папке сессии — ``claude --continue`` (тот же разговор); черновик — обратно в поле."""
        path = space_sessions.check_folder(slug, folder)
        if any(w.get("path") == str(path) for w in self.space_windows(slug)) or space_sessions.is_open(slug, path):
            raise ValueError("эта сессия уже открыта")
        if folder not in {x["folder"] for x in space_sessions.listing(slug)}:
            raise LookupError("нет такой сессии")
        args = "--continue" if space_sessions.has_history(slug, path) else ""
        args = (repos.flags(self.pult.state(), str(path)) + " " + args).strip()   # подключённые репозитории
        raw = tenants.new_window(slug, folder, str(path), args=args)
        draft = self.space_drafts().get(slug, {}).get(folder, "")
        if draft:
            self.space_draft_set(slug, folder, "")
        return {"id": spaces.wid_of(slug, raw), "draft": draft, "continued": bool(args)}

    def space_delete(self, slug: str, folder: str, confirm: str) -> dict:
        """«Удалить»: только закрытую сессию и только с именем во втором подтверждении — в корзину на KEEP_DAYS."""
        path = space_sessions.check_folder(slug, folder)
        if confirm != folder:
            raise ValueError("для удаления введите имя сессии точно")
        if any(w.get("path") == str(path) for w in self.space_windows(slug)) or space_sessions.is_open(slug, path):
            raise ValueError("сессия открыта — сначала закройте её")
        out = space_sessions.trash(slug, folder)
        self.space_draft_set(slug, folder, "")
        return {**out, "keep_days": space_sessions.KEEP_DAYS}

    def space_restore(self, slug: str, tid: str) -> dict:
        return {"folder": space_sessions.restore(slug, tid)}

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
        """Остановленная сессия: Claude заново в том же окне, у того же поставщика, с продолжением разговора."""
        w = self.tmux.window(wid)
        if not w or not w.get("stopped"):
            raise ValueError("сессия не остановлена — перезапускать нечего")
        if w.get("space"):                              # окно пространства — его команда: свой PATH, профиль, ключ
            t = tenants.load(w["space"])
            if not t:
                raise ValueError("пространства уже нет")
            profile, cmd = w["mark"] or "claude", tenants.command(t) + repos.flags(self.pult.state(), w["path"])
            self.tmux.respawn(wid, w["path"], cmd + " --continue", mark=profile)
            return {"id": wid}
        profile = w["mark"] if w["mark"] in models.BY_ID else "claude"
        if uid is not None:
            self.check(profile, uid)
        self.need_claude()
        st = self.pult.state()
        cmd = models.command(self.cfg.claude, profile, st, home=self.pult.home_of(w))  # нет ключа — тут
        cmd += repos.flags(st, w["path"])                                    # подключённые репозитории (задача 43)
        if own := (st.get("window_models") or {}).get(wid):                  # модель этого чата — та же
            cmd += f" --model {shlex.quote(own)}"
        # @gas_pult_by и @gas_pult_sid окна остаются: свой журнал — тот же разговор (--resume), иначе --continue
        self.tmux.respawn(wid, w["path"], cmd + transcripts.resume_args(w.get("sid")), mark=profile)
        return {"id": wid}

    def restart(self, w: dict, profile: str, keep: bool = True, uid=None, model: str | None = None) -> dict:
        """Сменить поставщика: штатно закрыть окно и открыть в той же папке с другим профилем.

        ``keep`` — продолжить тот же разговор (``claude --continue``: новый поставщик получает всю переписку, контекст
        не теряется); иначе — чистый лист. Одно окно на проект, поэтому «последний разговор папки» — именно этот.
        """
        if uid is not None:
            self.check(profile, uid)                                          # не для страны — до закрытия
        home = self.pult.home_of(w)                    # папка того, кто открыл окно, а не того, кто нажал
        st = self.pult.state()
        cmd = models.command(self.cfg.claude, profile, st, home=home)   # нет ключа — ошибка до закрытия
        own = dict(st.get("window_models") or {})
        same = profile == (w.get("profile") or w.get("mark") or "claude")
        if model is None:                               # смена поставщика: модель этого чата — его по умолчанию;
            model = own.get(w["id"], "") if same else ""   # тот же поставщик (перезапуск) — прежняя модель чата
        cmd += repos.flags(st, w["path"])                # подключённые репозитории — снова в сессии (задача 43)
        cmd += f" --model {shlex.quote(model)}" if model else ""
        sid = transcripts.valid_sid(w.get("sid"))
        if keep:                                        # свой журнал окна — тот же разговор (--resume), иначе последний
            cmd += transcripts.resume_args(w.get("sid"))
        else:                                           # чистый лист — новый журнал со своей меткой
            sid = str(uuid.uuid4())
            cmd += f" --session-id {sid}"
        result = self.close(w)
        if result != "закрыто":
            raise ValueError(result)
        wid = self.tmux.new_window(w["name"], w["path"], cmd, mark=profile or "claude",
                                   by=w.get("by", "") if home else "", sid=sid)
        if not home:                                    # окно владельца: метка прежняя, иначе — кто нажал
            self.mark_by(wid, w.get("by") or uid)
        own.pop(w["id"], None)
        self.focus.move(w["id"], wid)                   # фокус-ссылка — за той же сессией в новом окне
        if model:
            own[wid] = model                            # выбор — только этого чата: «Продолжить» и перезапуск — с ним
        upd = {"window_models": own}
        if st.get("active") == w["id"]:                 # активная в боте — та же сессия, но чужую не делаем активной
            upd["active"] = wid
        self.pult.set_state(**upd)
        return {"id": wid, **({"model": model} if model else {})}

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

    def close(self, w: dict) -> str:
        return self.close_ex(w)["result"]

    def close_ex(self, w: dict) -> dict:
        """Завершить сессию: текст итога и неотправленный черновик из поля ввода (если был) — панель его покажет."""
        if w.get("stopped"):                            # остановленная: Claude уже вышел — окно с оболочкой закрыть
            self.tmux.kill(w["id"])
            return {"result": "закрыто", "draft": ""}
        r = self.pult.quit_ex(w)
        text = {"background": "не закрыл: у сессии есть фоновые задачи — решите в самом окне",
                "busy": "Claude не вышел за 20 с (возможно, занят) — посмотрите экран"}.get(r["result"], "закрыто")
        return {"result": text, "draft": r["draft"]}

    def upload(self, name: str, data: bytes) -> str:
        """Файл из панели → inbox пульта; Claude получает путь (как файлы из чата бота)."""
        safe = re.sub(r"[^\w.\-]+", "_", os.path.basename(urllib.parse.unquote(name)))[-80:].lstrip(".") or "file"
        d = self.cfg.data / "inbox"
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = d / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}-{safe}"
        path.write_bytes(data)
        path.chmod(0o600)
        return str(path)

    # ---------- голос: локально или ElevenLabs ----------
    def voice_settings(self) -> dict:
        st, keys = self.pult.state(), providers.key_info()
        el, own = "elevenlabs" in keys, self.cfg.personal_voices        # настройки голоса — только владельцу
        return {"tts": st.get("tts_provider", "local") if el else "local",
                "stt": st.get("stt_provider", "local") if el else "local",
                "el_voice": st.get("el_voice"), "keys": keys,
                "local_voice": catalog.label(self.voice(personal=own) or ""),
                "fallback": self.fallback_note(), "voice": self.voice(personal=own),
                "local_voices": [{"id": v, "name": catalog.label(v)} for v in catalog.installed(own)]}

    def el_voices(self) -> list[dict]:
        key = providers.load_keys().get("elevenlabs")
        return providers.el_voices(key) if key else []

    def el_voice_name(self, vid: str | None) -> str:
        """Имя голоса ElevenLabs для карточки (список аккаунта — не чаще раза в 10 минут)."""
        t, voices = getattr(self, "_el_names", (0.0, []))
        if time.time() - t > 600:
            try:
                voices = self.el_voices()
            except providers.ProviderError:
                voices = []
            self._el_names = (time.time(), voices)
        return next((v["name"] for v in voices if v["id"] == vid), "")

    # ---------- карточки голосов: экран «Голос», шторка у ответа, /voice в боте ----------
    def voice_cards(self, owner: bool, cloud: bool = True) -> dict:
        """Голоса, доступные этому человеку: ElevenLabs первой, затем локальные (``catalog.ORDER``). Silero — только
        владельцу при ``personal_voices``; не установленные — только владельцу. Выбирает — владелец.
        ``cloud=False`` — тестировщик пространства: только локальные (ключ ElevenLabs — владельца)."""
        personal = owner and self.cfg.personal_voices
        st, key = self.pult.state(), cloud and "elevenlabs" in providers.key_info()
        out = []
        if cloud and (key or owner):
            vid = st.get("el_voice") if key else None
            out.append({"id": "elevenlabs", "name": (self.el_voice_name(vid) if vid else "") or "ElevenLabs",
                        "kind": "облачный", "ok": key, "why": "" if key else "нужен ключ ElevenLabs", "install": ""})
        out += catalog.cards(personal, owner)
        cur = "elevenlabs" if key and st.get("tts_provider") == "elevenlabs" else self.voice(personal=personal)
        # Голос без карточки (Piper: выбран раньше или запасной) — читает дальше; панель пишет, что это запасной.
        fb = catalog.label(cur) if cur and cur in catalog.FALLBACK else ""
        return {"cards": out, "current": cur, "can_choose": owner, "fallback": fb}

    def choose_voice(self, vid: str):
        self.pult.choose_voice(vid)                          # общее с ботом (/voice)

    def voice_preview(self, vid: str, owner: bool) -> bytes:
        return self.pult.voice_preview(vid, owner and self.cfg.personal_voices)[0]

    def set_key(self, provider: str, key: str) -> dict:
        key = key.strip()
        if provider in {p.get("key") for p in models.PROFILES} - {None}:
            if len(key) < 16 or any(c.isspace() for c in key):
                raise ValueError(f"это не похоже на ключ {providers.NAMES[provider]} — скопируйте его целиком")
            checked = providers.check_model_key(provider, key)   # неверный ключ сюда не дойдёт
            providers.save_key(provider, key)
            return {"checked": checked}
        if provider != "elevenlabs":
            raise ValueError("такого поставщика нет")
        if len(key) < 20:
            raise ValueError("это не похоже на ключ ElevenLabs — скопируйте его целиком")
        voices = providers.el_voices(key)                 # проверка: неверный ключ сюда не дойдёт
        providers.save_key(provider, key)
        if voices and not self.pult.state().get("el_voice"):
            self.pult.set_state(el_voice=voices[0]["id"])
        return {"voices": voices}

    def remove_key(self, provider: str):
        providers.save_key(provider, None)
        if provider == "elevenlabs":                         # голос возвращается на сервер; модели не трогаем
            self.pult.set_state(tts_provider="local", stt_provider="local")

    def bot_username(self) -> str:
        if not self._bot:
            self._bot = self.pult.api("getMe")["username"]
        return self._bot

    def set_role(self, uid: int, role: str):
        p = next((x for x in self.people.list() if x["id"] == uid), None)
        if not p or p["role"] == "owner":
            raise ValueError("такого человека нет в списке")
        self.people.add(uid, role, p.get("name", ""), p.get("username", ""))

    def openrouter_done(self, code: str, state: str):
        """Возврат из OpenRouter после «Authorize»: код → ключ → secrets.json (как ключ, вставленный вручную)."""
        providers.save_key("openrouter", self.openrouter.finish(code, state))

    def openrouter_info(self) -> dict:
        key = providers.load_keys().get("openrouter")
        return {"key": False} if not key else {"key": True, **self.openrouter.info(key)}

    def set_models(self, profile: str, main: str, fast: str, base_url: str | None = None):
        """``base_url`` — адрес шлюза клиента (GigaChat, YandexGPT); ``None`` — не менять."""
        self.pult.set_state(model_profiles=models.set_models(self.pult.state(), profile, main, fast, base_url))

    def set_providers(self, b: dict):
        el = "elevenlabs" in providers.key_info()
        upd = {}
        for k in ("tts", "stt"):
            if k in b:
                if b[k] not in ("local", "elevenlabs") or (b[k] == "elevenlabs" and not el):
                    raise ValueError("сначала сохраните ключ ElevenLabs")
                upd[f"{k}_provider"] = b[k]
        if b.get("el_voice"):
            upd["el_voice"] = str(b["el_voice"])
        if b.get("voice"):
            if b["voice"] not in catalog.selectable(self.cfg.personal_voices):  # настройки голоса — владельцу
                raise ValueError("этот голос не установлен: gas-pult voices install <имя>")
            upd["voice"] = str(b["voice"])
        self.pult.set_state(**upd)

    def voice_fallback(self, what: str, e: Exception):
        """ElevenLabs отказал — работаем локально и сообщаем: журнал службы и ``fallback`` в /api/providers.
        Отказ сервиса (лимит, ключ, сеть) запоминаем на ``EL_PAUSE`` с: каждая следующая запись не ждёт ответа
        ElevenLabs (до ``providers.TIMEOUT`` = 2 мин при зависшей сети), а сразу идёт локально."""
        note = f"ElevenLabs недоступен ({what}): {e} — переключился на локальный голос"
        print(note, file=sys.stderr, flush=True)
        self.last_fallback = (time.time(), note)
        if isinstance(e, providers.ProviderError):
            self.el_pause_until = time.time() + EL_PAUSE

    def el_ok(self) -> bool:
        """ElevenLabs не отказывал последние ``EL_PAUSE`` с (см. ``voice_fallback``)."""
        return time.time() >= getattr(self, "el_pause_until", 0.0)

    def fallback_info(self, uid=None) -> dict:
        """Запасные для панели: цепочка поставщиков, страны, кто годится, последние переключения, голос (#53)."""
        cs = None if uid is None else self.countries(uid)
        return {**fallback.public(self.pult.state(), self.cfg.region, countries=cs), "voice_note": self.fallback_note()}

    def set_fallback(self, chain, uid=None) -> dict:
        cs = self.cfg.region if uid is None else self.countries(uid)
        self.pult.set_state(fallback_chain=fallback.validate(chain, cs))
        return self.fallback_info(uid)

    def fallback_note(self) -> str:
        t, note = getattr(self, "last_fallback", (0, ""))
        return note if time.time() - t < 3600 else ""

    def stt(self, data: bytes, ctype: str, cloud: bool = True) -> str:
        """Голос из панели → текст. Пустая запись или пустой результат — понятная ошибка (400), не пустая строка."""
        if not data:
            raise ValueError(STT_EMPTY)
        ext = AUDIO_EXT.get(ctype.split(";")[0], "webm")
        if cloud and self.voice_settings()["stt"] == "elevenlabs" and self.el_ok():
            try:
                text = (providers.el_stt(providers.load_keys()["elevenlabs"], data, f"voice.{ext}") or "").strip()
                if not text:
                    raise ValueError(STT_EMPTY)
                return text
            except (providers.ProviderError, KeyError) as e:     # запасной путь — локальный whisper, молча не падаем
                self.voice_fallback("распознавание", e)
        path = self.cfg.data / "inbox" / f"web-{uuid.uuid4().hex}.{ext}"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(data)
        try:                                             # служба T-one, нет её — whisper (voice.transcribe_any)
            text = (voice.transcribe_any(path, self.cfg.whisper_model, STT_TIMEOUT, self.cfg.data) or "").strip()
        except subprocess.TimeoutExpired:            # панель ждёт 90 с — сервер сдаётся чуть раньше и говорит почему
            raise RuntimeError(f"распознавание не уложилось в {STT_TIMEOUT} с — длинная запись или сервер занят") \
                from None
        finally:
            path.unlink(missing_ok=True)                 # голос не храним
        if not text:
            raise ValueError(STT_EMPTY)
        return text

    def stt_stream(self, rate: int) -> asr.Stream:
        """Поток в службу распознавания; её нет или занята — ``asr.Unavailable`` (панель уйдёт на ``/api/stt``)."""
        return asr.Stream(rate, partials=True, path=asr.socket_path(self.cfg.data))

    def message(self, w: dict, i: int | None) -> str:
        home, sid = self.pult.home_of(w), w.get("sid") or ""
        if i is None:
            return transcripts.last_answer(w["path"], home, sid)
        items, _ = transcripts.history(w["path"], limit=1, before=i + 1, home=home, sid=sid)
        if not items or items[0]["i"] != i:
            raise ValueError("сообщение не найдено — обновите переписку")
        return items[0]["text"]

    def tts(self, w: dict, full: bool, msg: int | None = None, personal: bool = False, cloud: bool = True) -> bytes:
        text = transcripts.clean(self.message(w, msg))
        text = (text if full else brief(text))[:3500]
        if not text:
            raise ValueError("нечего озвучивать")
        vs = self.voice_settings()
        if cloud and vs["tts"] == "elevenlabs" and self.el_ok():
            voice_id = vs["el_voice"] or next(iter(self.el_voices()), {}).get("id")
            if not voice_id:
                raise ValueError("в аккаунте ElevenLabs нет голосов")
            try:
                return providers.el_tts(providers.load_keys()["elevenlabs"], voice_id, text)
            except (providers.ProviderError, KeyError) as e:     # запасной путь — локальный голос
                self.voice_fallback("озвучка", e)
        v = self.voice(personal=personal)                # Silero — только владельцу лично, остальным — Piper
        if not v:
            raise ValueError("голоса не установлены: gas-pult voices install irina")
        out = self.cfg.data / f"web-{uuid.uuid4().hex}.mp3"
        try:
            voice.synth(v, text, out)
            return out.read_bytes()
        finally:
            out.unlink(missing_ok=True)


    # ---------- ▶️ команды из последнего ответа ----------
    def commands(self, w: dict) -> list[dict]:
        out = []
        for i, cmd in enumerate(extract(transcripts.last_answer(w["path"], self.pult.home_of(w), w.get("sid") or ""))):
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
        wins = [w for w in self.tmux.windows() if w["cmd"] == "claude"]
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


def server_tz() -> str:
    """Часовой пояс сервера (Europe/Amsterdam): панель показывает время в нём, где бы ни был телефон. Время в журналах
    Claude Code и пульта — UTC. Не нашли имя пояса — "" (панель покажет время телефона)."""
    if os.environ.get("TZ", "").count("/"):
        return os.environ["TZ"].lstrip(":")
    try:                                            # как timedatectl: системный пояс — ссылка /etc/localtime
        link = os.readlink("/etc/localtime")
        if "zoneinfo/" in link:
            return link.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    try:                                            # /etc/timezone бывает устаревшим — только запасной путь
        return Path("/etc/timezone").read_text().strip()
    except OSError:
        return ""


def utc_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime())


# Сервис-воркер: только клик по уведомлению — открыть панель на нужной сессии. Ни кэша, ни фоновых запросов.
SW_JS = """self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const id = e.notification.data && e.notification.data.id;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((cs) => {
    if (cs[0]) { cs[0].focus(); cs[0].postMessage({ open: id }); return null; }
    return self.clients.openWindow("/");
  }));
});
"""

# Только владельцу: выполнение команд, закрытие сессий, ключи, модели, люди.
TERM = ("/api/term", "/api/run/term", "/api/commands/term", "/api/term/type", "/api/term/key", "/api/term/close")
OWNER_ONLY = {"/api/run", "/api/commands/run", "/api/commands/mark", "/api/commands/output", "/api/close",
              "/api/restart", "/api/keys", "/api/keys/remove", "/api/providers", "/api/voice/choose",
              "/api/models", "/api/openrouter/start", "/api/openrouter/info", "/api/openrouter/models",
              "/api/people", "/api/people/role", "/api/people/remove", "/api/fallback", "/api/team",
              "/api/cost/limits", "/api/cost/decide",
              "/api/model/default", "/api/balance/clear", "/api/module/delete", *TERM,
              "/api/chat/delete", "/api/chat/restore", "/api/chat/trash",
              "/api/focus/new", "/api/focus/send", "/api/focus/qr", "/api/focus/list", "/api/focus/revoke",
              "/api/spaces", "/api/invite/new", "/api/space/task", "/api/space/connect", "/api/space/budget/add",
              "/api/setup/status", "/api/setup/login", "/api/setup/code", "/api/setup/cancel"}
# Участнику и владельцу, в том числе чтение: интеграции — у каждого свои (его папка Claude Code), наблюдателю — нет.
MEMBER_ONLY = {"/api/mcp", "/api/mcp/connected"}
# Живой терминал (задача 50): клавиши и текст прямо в окно, вся история tmux. Только в режиме разработчика (владелец
# и участник с «Экраном терминала» не в простом режиме — ``H.dev_tty``); наблюдателю, пространству и фокусу — нет.
TTY = ("/api/tty", "/api/tty/type", "/api/tty/key")
MEMBER_ONLY |= set(TTY)
OWNER_PRESETS = {"stdio"}               # своя программа на сервере — только владельцу
SELFTEST = "/api/selftest"               # автотест поставщиков (selftest.py): итог и «Проверить сейчас» — владельцу
OWNER_ONLY |= {SELFTEST}

# Вид панели (роль интерфейса и тумблеры возможностей) — своя настройка человека; потолок задаёт владелец.
PERSONA = "/api/persona"
# До согласия с условиями использования (terms.py) — только это; остальное API отвечает 403 с code="terms".
TERMS_FREE = {"/api/meta", "/api/terms", "/api/terms/accept", "/api/logout", "/api/help/ask", "/api/help/feedback",
              "/api/prefs", PERSONA}
# Помощник «? Подсказать» — любому вошедшему (и наблюдателю), а на экране входа — и до входа.
HELP_OPEN = ("/api/help/ask", "/api/help/feedback")
# Почта для входа и оповещений (emailcode.py) — своя у каждого вошедшего, в том числе у наблюдателя.
EMAIL_OWN = ("/api/email", "/api/email/bind", "/api/email/confirm", "/api/email/remove", "/api/email/options")
# Вход по почте и второй фактор — до входа (свои лимиты по адресу и IP).
EMAIL_LOGIN = ("/api/login/email/start", "/api/login/email/verify", "/api/login/2fa")
# Ключи входа (passkeys.py): свои у каждого вошедшего; вход по ключу — до входа (лимит по IP).
PASSKEY_OWN = ("/api/passkeys", "/api/passkeys/options", "/api/passkeys/add", "/api/passkeys/remove")
PASSKEY_LOGIN = ("/api/login/passkey/options", "/api/login/passkey/verify")
# Вход через Google и Яндекс ID (oidc.py): привязки — свои у каждого вошедшего; сам вход — переходами браузера.
OIDC_OWN = ("/api/oidc", "/api/oidc/link", "/api/oidc/unlink")
OIDC_PATH = re.compile(r"^/api/login/oidc/(google|yandex)/(start|back)$")
# «Сообщить по готовности» из строки статуса — и наблюдателю: только уведомление ему же в бот.
NOTIFY_DONE = "/api/notify-done"
# Отметки короткого тура (пройден / «Не сейчас») — настройка самого человека: менять может и наблюдатель.
TOUR = "/api/tour"
# До выбора страны (country.py) — ещё и выбор страны; остальное — 403 с code="country".
COUNTRY_FREE = TERMS_FREE | {"/api/country"}
# Репозитории GitHub в сессии (задача 43, repos.py): к своей сессии — владелец и тестировщик пространства.
REPOS = ("/api/repos", "/api/repos/add", "/api/repos/remove")
# Тестировщик демо-пространства (задача 31): только это — и только с окнами своего пространства (spaces.Routed.scope).
# Остальное (папки и модули владельца, файлы, интеграции, ключи, люди, модели, расход владельца) — 403 code=space.
SPACE_OK = TERMS_FREE | {
    "/api/sessions", "/api/country", "/api/prefs", TOUR, "/api/activity", "/api/last", "/api/screen", "/api/ask",
    "/api/hint", "/api/history", "/api/tts", "/api/stt", "/api/voice/cards", "/api/scenarios", "/api/new",
    "/api/send", "/api/key", "/api/select", "/api/command", "/api/rename", "/api/help/call",
    "/api/space/sessions", "/api/space/close", "/api/space/resume", "/api/space/delete", "/api/space/restore",
    "/api/space/files", "/api/space/upload", "/api/space/download", STT_STREAM, *REPOS,
    "/api/invite/device", "/api/invite/qr", "/api/link/tg", *("/api/passkeys", "/api/passkeys/options",
                                                            "/api/passkeys/add", "/api/passkeys/remove"),
}
# Что тратит деньги: тестировщику — только пока дневной бюджет пространства не исчерпан (клавиши, Esc — можно).
BUDGET_PATHS = {"/api/send", "/api/new", "/api/command", "/api/select", "/api/space/resume"}
# Лёгкий вход (задача 34): ссылка для входа на другое устройство, её QR и «Привязать Telegram» — свои у каждого.
INVITE_OWN = ("/api/invite/device", "/api/invite/qr", "/api/link/tg")
# Фокус (задача 41, focus.py): с cookie фокуса — только чат одной сессии; окно ``w`` в запросе — только её.
# Настройки самой сессии — тоже здесь: модель, поставщик, усилия, файлы, интеграции (список и вход из её экрана).
# Нет: другие сессии, их создание и переключение, общие настройки пульта (ключи, люди, добавление интеграций).
FOCUS_GET = {"/api/meta", "/api/sessions", "/api/history", "/api/screen", "/api/ask", "/api/hint", "/api/cmds",
             "/api/tts", "/api/last", "/api/activity", "/api/space/files", "/api/space/download", "/api/mcp",
             "/api/mcp/connected", "/api/repos"}
FOCUS_POST = {"/api/send", "/api/key", "/api/select", "/api/command", "/api/run", "/api/revive", "/api/upload",
              "/api/stt", "/api/space/upload", "/api/close", "/api/space/close", "/api/logout", "/api/model",
              "/api/effort", "/api/restart", "/api/mcp/finish", "/api/repos/add", "/api/repos/remove"}
FOCUS_NO_W = {"/api/meta", "/api/sessions", "/api/upload", "/api/stt", "/api/logout", "/api/mcp",
              "/api/mcp/connected"}   # без окна в запросе
# Адрес клиента из заголовков прокси — только если запрос пришёл с этой машины (Caddy, cloudflared).
LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

# Страница предложения (offers.py): без входа, не индексируется, не кэшируется, ссылка не уходит в Referer.
NOINDEX = {"X-Robots-Tag": "noindex, nofollow, noarchive", "Referrer-Policy": "no-referrer",
           "X-Frame-Options": "DENY"}
INVITE_PATH = re.compile(r"^/invite/([A-Za-z0-9_-]{16,64})/?$")
OFFER_PATH = re.compile(r"^/(api/)?offer/([^/]{1,80})(?:/([a-z]{1,20}))?/?$")
ROBOTS = "User-agent: *\nDisallow: /offer/\nDisallow: /api/\n"
OFFER_404 = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             '<meta name="robots" content="noindex, nofollow, noarchive"><title>Страница не найдена</title>'
             '<body style="margin:0;padding:48px 24px;font:16px/1.5 system-ui,sans-serif;text-align:center">'
             '<h1 style="font-size:22px">Страница не найдена</h1><p>Ссылка неверна, устарела или отозвана.</p></body>')

# Страница после входа в OpenRouter: открывается во внешнем браузере, поэтому самодостаточная.
# Страница входа через Google и Яндекс ID: открывается во внешнем браузере, поэтому самодостаточная.
OIDC_PAGE = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             '<title>gas-pult · вход</title><body style="margin:0;padding:48px 24px;font:16px/1.5 system-ui,'
             'sans-serif;background:#F6F5F0;color:#181816;text-align:center"><h1 style="font:600 22px Georgia,serif">'
             '{title}</h1><p style="color:#6E6C65">{text}</p><p><a href="/" style="color:#181816">Открыть панель</a>'
             '</p></body>')
DONE_PAGE = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             '<title>gas-pult · OpenRouter</title><body style="margin:0;padding:48px 24px;font:16px/1.5 system-ui,'
             'sans-serif;background:#F6F5F0;color:#181816;text-align:center"><h1 style="font:600 22px Georgia,serif">'
             '{title}</h1><p style="color:#6E6C65">{text}</p></body>')


def handler(panel: Panel):
    page = resources.files("gas_pult").joinpath("web/index.html").read_bytes()
    build = hashlib.sha256(page).hexdigest()[:12]      # версия страницы: изменилась — панель предложит обновиться
    whatsnew = json.loads(resources.files("gas_pult").joinpath("web/whatsnew.json").read_text(encoding="utf-8"))
    offer_page = resources.files("gas_pult").joinpath("web/offer.html").read_bytes()
    help_map = resources.files("gas_pult").joinpath("web/help-map.json").read_bytes()   # карта для демо панели
    i18n = {f"/i18n/{x}.json": resources.files("gas_pult").joinpath(f"web/i18n/{x}.json").read_bytes()
            for x in ("ru", "en")}                       # словари простого режима и первого экрана — и до входа
    scripts = re.findall(rb"<script>(.*?)</script>", offer_page, re.S)
    hashes = " ".join("'sha256-" + base64.b64encode(hashlib.sha256(x).digest()).decode() + "'" for x in scripts)
    offer_csp = (f"default-src 'none'; script-src {hashes}; style-src 'unsafe-inline'; img-src 'self' data:; "
                 "connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'")

    class H(BaseHTTPRequestHandler):
        focused: dict | None = None             # запрос из фокуса: ссылка (focus.py), уже проверенная
        raw: bytes | None = None                # тело, прочитанное проверкой фокуса

        def log_message(self, fmt, *args):     # без логов запросов: в них initData
            pass

        def reply(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8", cookie: str = "",
                  headers: dict | None = None):
            self.send_response(code)
            if cookie:
                self.send_header("Set-Cookie", cookie)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def json(self, data, code: int = 200):
            self.reply(code, json.dumps(data, ensure_ascii=False).encode())

        def who(self) -> tuple[str, str | None, int | None]:
            """(откуда: «telegram» / «browser» / "", роль, Telegram ID). Роль — на каждый запрос, из people.json.
            Запрос из фокуса — права того, кто выпустил ссылку, но только в пределах ``FOCUS_*`` и одного окна."""
            if self.focused is not None:
                return "focus", "owner", self.focused.get("by")
            user = verify(self.headers.get("X-Telegram-Init-Data", ""), panel.cfg.token)
            if user and (role := panel.people.role(user.get("id"))):
                return "telegram", role, int(user["id"])
            uid = panel.auth.uid(self.session())
            if uid is None:
                return "", None, None
            role = "owner" if uid == webauth.LEGACY else panel.people.role(uid)
            return ("browser", role, uid) if role else ("", None, None)

        def via(self) -> str:
            return self.who()[0]

        def person(self) -> int | None:
            """Telegram ID вошедшего, если это не владелец: его окна и интеграции — в его папке Claude Code."""
            _, role, uid = self.who()
            return None if role == "owner" or uid is None else uid

        def pool(self) -> str | None:
            """Чей расход видит вошедший: владелец — «owner», участник — свой ID, наблюдатель — ничей,
            тестировщик — его пространство."""
            _, role, uid = self.who()
            if slug := self.space():
                return f"space:{slug}"
            return "owner" if role == "owner" else str(uid) if role == "member" and uid is not None else None

        def home(self):
            """Папка Claude Code вошедшего (``people.claude_dir``); владелец — None (``~/.claude``)."""
            uid = self.person()
            return panel.pult.claude_dir(uid) if uid is not None else None

        def session(self) -> str:
            return webauth.cookie_value(self.headers.get("Cookie", ""))

        def space(self) -> str | None:
            """Демо-пространство тестировщика (``people.tenant``); владелец и обычные люди — None."""
            _, role, uid = self.who()
            return None if role == "owner" or uid is None else panel.people.tenant(uid)

        def space_of(self, b: dict) -> str:
            """Чьё пространство: тестировщика — его; владельцу — из запроса (``space``); остальным — отказ."""
            if slug := self.space():
                return slug
            if self.who()[1] == "owner" and b.get("space"):
                return tenants.check_slug(str(b["space"]))
            raise ValueError("это действие — для сессий демо-пространства")

        def space_win(self, q: dict) -> tuple[str, dict]:
            """Окно пространства из запроса (``w``): тестировщику — только своё; владельцу — любое пространство."""
            w = panel.tmux.window(str(q.get("w") or ""))
            slug = self.space()
            if not slug and self.who()[1] == "owner":
                slug = (w or {}).get("space")
            if not w or not slug or w.get("space") != slug:
                raise LookupError("окна уже нет")
            return slug, w

        def terms_uid(self) -> int | None:
            """Чьё согласие с условиями проверять. Вход кодом владельцу (LEGACY) — первого владельца."""
            uid = self.who()[2]
            return (panel.cfg.owners or [None])[0] if uid == webauth.LEGACY else uid

        def permit(self, path: str, method: str) -> bool:
            """Не вошёл — 401 (панель покажет вход); не принял условия — 403 code=terms; не хватает роли — 403."""
            role = self.who()[1]
            if not role and self.focus_cookie():          # с фокус-ссылкой — только её сессия, остальное закрыто
                self.json({"error": "по фокус-ссылке доступна только её сессия", "code": "focus_scope"}, 403)
                return False
            if not role:
                self.json({"error": "нужен вход"}, 401)
                return False
            uid = self.terms_uid()
            panel.seen_ip(uid, self.client_ip())                   # страна по IP — не чаще раза в IP_EVERY
            if path not in TERMS_FREE and not panel.people.accepted(uid):
                self.json({"error": "сначала примите условия использования пульта", "code": "terms"}, 403)
                return False
            if path not in COUNTRY_FREE and not country.norm(panel.people.country(uid).get("chosen")):
                self.json({"error": "сначала выберите страну, из которой работаете", "code": "country"}, 403)
                return False
            if self.space() and path not in SPACE_OK:     # тестировщик — только своё пространство
                self.json({"error": "в демо-пространстве этого нет", "code": "space"}, 403)
                return False
            if method == "POST" and path in BUDGET_PATHS and (slug := self.space()):
                try:
                    panel.check_budget(slug)              # дневной бюджет пространства исчерпан — не писать агенту
                except ValueError as e:
                    self.json({"error": str(e), "code": "budget"}, 403)
                    return False
            free = ("/api/logout", "/api/terms/accept", "/api/country", "/api/prefs", NOTIFY_DONE, TOUR, PERSONA,
                    *HELP_OPEN, *EMAIL_OWN, *PASSKEY_OWN, *OIDC_OWN, *INVITE_OWN)   # и наблюдателю
            need = ("owner" if path in OWNER_ONLY else
                    "member" if (method == "POST" and path not in free) or path in MEMBER_ONLY else "viewer")
            if not allowed(role, need):
                why = "это может только владелец" if need == "owner" else "у вас доступ только на просмотр"
                self.json({"error": why}, 403)
                return False
            cap = personas.PATH_CAP.get(path)               # потолок возможностей — это права, не только вид
            if cap and cap not in personas.ceiling(personas.access(role), panel.team, uid):
                self.json({"error": "этот раздел вам не открыл владелец пульта", "code": "cap", "cap": cap}, 403)
                return False
            if path in TTY and not self.dev_tty():
                self.json({"error": "живой терминал — только в режиме разработчика", "code": "dev"}, 403)
                return False
            return True

        def dev_tty(self) -> bool:
            """Живой терминал: владелец или участник, у которого в виде есть «Экран терминала» и не простой режим.
            Фокус-ссылка сюда не доходит (``FOCUS_*``), тестировщик пространства — тоже (``SPACE_OK``)."""
            if self.focused is not None or self.space():
                return False
            role = self.who()[1]
            if role not in ("owner", "member"):
                return False
            tu = self.terms_uid()
            v = panel.ui(tu, role)
            return "cap.dev_terminal" in v["caps"] and not v["simple"] and not panel.prefs(tu, role)["simple"]

        def client_ip(self) -> str:
            """Адрес клиента. За обратным прокси на этой машине — из ``X-Forwarded-For`` (последний адрес: его дописал
            наш прокси, начало строки присылает сам клиент) или ``X-Real-IP``; с других адресов заголовкам не верим."""
            peer = self.client_address[0]
            if peer in LOOPBACK:
                xff = [x.strip() for x in self.headers.get("X-Forwarded-For", "").split(",") if x.strip()]
                if xff:
                    return xff[-1]
                if real := self.headers.get("X-Real-IP", "").strip():
                    return real
            return peer

        def client(self) -> tuple[str, str]:
            return self.client_ip(), self.headers.get("User-Agent", "")

        def body(self) -> bytes:
            if self.raw is not None:
                return self.raw
            n = int(self.headers.get("Content-Length", 0))
            if n > MAX_BODY:
                raise ValueError("слишком большой запрос")
            return self.rfile.read(n)

        def repo_win(self, q: dict) -> dict:
            """Окно для репозиториев: остановленное — тоже (подключить к перезапуску). Сессии владельца — только ему:
            клон идёт на сервер пульта; тестировщик — только в своём пространстве (``tmux.scope``)."""
            w = panel.tmux.window(str(q.get("w") or ""))
            if not w:
                raise LookupError("окна уже нет")
            if not w.get("space") and self.who()[1] != "owner":
                raise ValueError("подключать репозитории к этой сессии может только владелец пульта")
            return w

        def win(self, wid) -> dict:
            if not (w := panel.window(str(wid or ""))):
                t = panel.tmux.window(str(wid or ""))
                raise LookupError("Claude в этой сессии остановлен — текст в командную строку не отправляю. "
                                  "Нажмите «Перезапустить»" if t and t.get("stopped") else "окна уже нет")
            return w

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path in ("/", "/index.html"):
                return self.reply(200, page, "text/html; charset=utf-8")
            if url.path == "/sw.js":                    # служебный файл уведомлений браузера (должен лежать в корне)
                return self.reply(200, SW_JS.encode(), "text/javascript; charset=utf-8")
            if url.path == CALLBACK:                    # возврат из OpenRouter: без входа, по одноразовому state
                return self.openrouter_back(dict(urllib.parse.parse_qsl(url.query)))
            if url.path == "/help-map.json":            # демо панели (?demo) отвечает подсказками из карты сам
                return self.reply(200, help_map)
            if url.path in i18n:
                return self.reply(200, i18n[url.path])
            if url.path == "/robots.txt":
                return self.reply(200, ROBOTS.encode(), "text/plain; charset=utf-8")
            if m := INVITE_PATH.match(url.path):         # приглашение: на экран входа с кодом
                return self.reply(302, b"", "text/plain", headers={**NOINDEX, "Location": f"/?invite={m.group(1)}"})
            if url.path == "/api/invite":                # экран входа: «приглашение в …» — только для действующего
                return self.json(panel.invite_info(dict(urllib.parse.parse_qsl(url.query)).get("code", "")))
            if url.path.startswith(("/offer/", "/api/offer/")):     # предложение: без входа, только по коду
                return self.offer("GET", url.path)
            if not url.path.startswith("/api/"):
                return self.json({"error": "нет такой страницы"}, 404)
            q = dict(urllib.parse.parse_qsl(url.query))
            if url.path == STT_STREAM:                   # WebSocket: вход — первым сообщением, не заголовком
                return self.stt_stream()
            if url.path == "/api/login/tg":              # браузер ждёт подтверждения из Telegram (по своему rid)
                return self.dispatch(lambda: self.tg_poll(q))
            if url.path == "/api/login/methods":         # экран входа: какие способы включены на этом пульте
                return self.json(panel.login_methods())
            if m := OIDC_PATH.match(url.path):           # вход через Google / Яндекс ID: переходы браузера
                return self.oidc_step(m.group(1), m.group(2), q)
            if self.headers.get(focus.HEADER):           # страница в режиме фокуса — только cookie фокуса
                return self.focus_call("GET", url.path, q)
            if not self.permit(url.path, "GET"):
                return None
            with panel.tmux.scope(self.space()):
                self.dispatch(lambda: self.get(url.path, q))

        def get(self, path: str, q: dict):
            if path == "/api/sessions":
                pool = self.pool()
                if self.space():                          # тестировщик: без имени сервера и событий владельца
                    sp = panel.space_info(self.terms_uid()) or {}
                    return {"sessions": panel.sessions(pool), "host": sp.get("title", ""), "build": build,
                            "now": time.time(), "cost": panel.cost_summary(pool), "fallback": [], "space": sp}
                with panel.tmux.all_spaces() if self.who()[1] == "owner" else contextlib.nullcontext():
                    ss = panel.sessions(pool)                 # владелец: и окна пространств (группа «Пространства»)
                return {"sessions": ss, "host": panel.cfg.host, "build": build,
                        "now": time.time(),                                   # часы сервера: «N назад» без сдвига
                        "cost": panel.cost_summary(pool),
                        "fallback": [{k: x.get(k) for k in ("ts", "w", "text")}
                                     for x in fallback.recent(panel.pult.state())]}
            if path == "/api/projects":                  # «Проекты» (docs/PROJECTS.md): список для главной
                pool = self.pool()
                with panel.tmux.all_spaces() if self.who()[1] == "owner" else contextlib.nullcontext():
                    ss = panel.sessions(pool)
                # всё, что отдаёт /api/sessions, — чтобы главной «Проекты» хватало одного запроса раз в 3 с
                return {"projects": panel.projects_list(ss, q.get("q", ""), q.get("archived") == "1"),
                        "sessions": ss, "now": time.time(), "host": panel.cfg.host, "build": build,
                        "cost": panel.cost_summary(pool),
                        "fallback": [{k: x.get(k) for k in ("ts", "w", "text")}
                                     for x in fallback.recent(panel.pult.state())]}
            if path == "/api/project":
                return panel.project_info(q.get("id", ""))
            if path == "/api/project/sessions":          # завершённые чаты проекта (журналы без окна)
                before = float(q["before"]) if re.fullmatch(r"\d+(\.\d+)?", q.get("before", "")) else None
                return panel.project_chats(q.get("id", ""), q.get("q", ""), before, self.person())
            if path == "/api/chat/trash":                # корзина чатов и скрытые чаты
                return panel.chat_trash_list()
            if path == "/api/project/history":           # переписка завершённого чата — без окна
                before = int(q["before"]) if q.get("before", "").isdigit() else None
                return panel.project_history(q.get("id", ""), q.get("sid", ""), before)
            if path == "/api/meta":
                kind, role, uid = self.who()
                tu = self.terms_uid()
                cinfo = panel.country_info(tu)
                return {**panel.meta(tu), "via": kind, "role": role, "uid": uid, "build": build,
                        "whatsnew": whatsnew[:1], "prefs": panel.prefs(tu, role), "ui": panel.ui(tu, role),
                        "terms": {"version": terms.VERSION, "accepted": panel.people.accepted(tu)},
                        "tty": bool(role) and self.dev_tty(),         # живой терминал (задача 50) — кнопка в панели
                        "projects_ui": not self.space(),              # «Проекты» (docs/PROJECTS.md): экран включён
                        "country": {k: cinfo[k] for k in ("chosen", "need", "mismatch", "phone", "ip_cc", "check")}}
            if path == "/api/terms":
                return self.terms_info()
            if path == "/api/prefs":
                return panel.prefs(self.terms_uid(), self.who()[1])
            if path == PERSONA:
                return panel.ui(self.terms_uid(), self.who()[1])
            if path == "/api/team":
                return panel.team_info()
            if path == TOUR:                             # тур: пройден / «Не сейчас» — у каждого свой
                return panel.people.tour(self.terms_uid())
            if path == "/api/country":
                return panel.country_info(self.terms_uid())
            if path == "/api/email":
                return panel.email.info(self.terms_uid())
            if path == "/api/passkeys":
                return panel.keys.info(self.terms_uid())
            if path == "/api/oidc":
                return panel.oidc.info(self.terms_uid())
            if path == "/api/people":
                return {"people": panel.people_list(), **panel.geo.info()}
            if path == "/api/setup/status":
                return panel.setup_status(q.get("fresh") == "1")
            if path == "/api/mcp":
                home = self.home()
                return {"servers": panel.mcp.list(q.get("fresh") == "1", home=home),
                        "presets": [p for p in PRESETS if not home or p["id"] not in OWNER_PRESETS],
                        "connectors": CONNECTORS, "connectors_url": CONNECTORS_URL,
                        "personal": home is not None}          # список — свой у человека, не общий с владельцем
            if path == "/api/modules":
                return panel.modules_list()
            if path == "/api/scenarios":                 # «Примерить на себя»: роли, день с агентом, польза
                errors: list[str] = []
                d = scenarios.api_data(errors)
                return {**d, "errors": errors if self.who()[1] == "owner" else []}
            if path == "/api/mcp/connected":
                c = next((x for x in CONNECTORS if x["id"] == q.get("id")), None)
                if not c:
                    raise LookupError("нет такого сервиса")
                s = panel.mcp.connected(c["match"], self.home())
                return {"found": bool(s), "ok": bool(s and s["ok"]), "state": s["state"] if s else ""}
            if path == "/api/openrouter/info":
                return panel.openrouter_info()
            if path == "/api/openrouter/models":
                return {"models": panel.openrouter.models()}
            if path == "/api/fallback":
                return panel.fallback_info(self.terms_uid())
            if path == SELFTEST:
                return selftest.public(panel.cfg.data, panel.pult.state())
            if path == "/api/cost/limits":
                return panel.cost_limits()
            if path == "/api/providers":
                vs = panel.voice_settings()
                return {**vs, "el_voices": panel.el_voices() if "elevenlabs" in vs["keys"] else []}
            if path == "/api/commands":
                return panel.command_log(self.who()[1] == "owner")
            if path == "/api/commands/output":
                out = panel.journal.output(q.get("id", ""))
                if out is None:
                    raise LookupError("вывода этой команды уже нет")
                return {"out": out}
            if path == "/api/voice/cards":
                return panel.voice_cards(self.who()[1] == "owner", cloud=not self.space())
            if path == "/api/voice/preview":
                return ("audio/mpeg", panel.voice_preview(q.get("id", ""), self.who()[1] == "owner"))
            if path == "/api/invite/qr":                 # QR ссылки приглашения: владельцу — любой, человеку — своей
                return ("image/png", panel.invite_qr(str(q.get("u") or ""), self.who()[1] == "owner",
                                                     self.terms_uid()))
            if path == "/api/focus/list":                 # «Настройки» → «Фокус-ссылки»: действующие, без токенов
                return {"links": panel.focus.listing()}
            if path == "/api/model/default":             # владелец: модель Claude по умолчанию для новых сессий
                return panel.default_model()
            if path == "/api/term":                       # окно терминала панели: что на экране, живо ли
                return termwin.screen(panel.tmux, q.get("id", ""))
            if path == "/api/tty":                        # живой терминал: история окна страницами (задача 50)
                w = panel.tty_window(str(q.get("w") or ""), self.who()[1] == "owner", write=False)
                d = termwin.history(panel.tmux, w["id"], q.get("start"), q.get("end"), q.get("all") == "1")
                return {**d, "w": w["id"], "name": w.get("name", ""), "kind": panel.tty_kind(w),
                        "path": w.get("path", "")}
            if path == "/api/spaces":                    # владелец: пространства для «Поставить задачу»
                st = tenants.status(check=True)
                for x in st.get("tenants", []):            # и запас каждого на период (задача 35)
                    x["budget"] = panel.space_budget(x["slug"])
                return st
            if path == "/api/space/sessions":            # закрытые сессии пространства и корзина
                return panel.space_list(self.space_of(q))
            if path in ("/api/space/files", "/api/space/download"):   # файлы папки сессии пространства
                slug, w = self.space_win(q)
                folder = space_files.folder_of(slug, w)
                if path == "/api/space/files":
                    return space_files.listing(slug, folder)
                name, data = space_files.get(slug, folder, q.get("f", ""))
                disp = "attachment; filename*=UTF-8''" + urllib.parse.quote(name)
                return ("application/octet-stream", data, {"Content-Disposition": disp})
            if path == "/api/activity":                  # строка статуса чата: что агент делает сейчас
                return panel.activity(str(q.get("w") or ""))
            if path == "/api/repos":                     # подключённые и что можно добавить (задача 43)
                return panel.repo_list(self.repo_win(q))
            w = self.win(q.get("w"))
            if path == "/api/last":
                return {"text": transcripts.last_answer(w["path"], panel.pult.home_of(w), w.get("sid") or "")}
            if path == "/api/screen":
                lines = panel.tmux.screen(w["id"], 60)
                return {"lines": lines[-40:], "auth": find_auth(lines)}
            if path == "/api/ask":                        # простой режим: вопрос Claude простыми словами и чипы
                return {"ask": humanize.parse(panel.tmux.screen(w["id"], 60))}
            if path == "/api/hint":
                return {"hint": panel.tmux.hint(w["id"])}
            if path == "/api/cmds":
                return {"cmds": panel.commands(w), "host": panel.cfg.host}
            if path == "/api/tts":
                msg = int(q["msg"]) if q.get("msg", "").isdigit() else None
                return ("audio/mpeg", panel.tts(w, q.get("full") == "1", msg,
                                                 panel.cfg.personal_voices and self.who()[1] == "owner",
                                                 cloud=not self.space()))
            if path == "/api/history":
                before = int(q["before"]) if q.get("before", "").isdigit() else None
                sid = w.get("sid") or ""                   # окно со своим журналом — его переписка
                rev = transcripts.revision(w["path"], home := panel.pult.home_of(w), sid)
                if before is None and q.get("rev") and q["rev"] == rev:
                    return {"same": True, "rev": rev}          # журнал не менялся — переписку не пересчитываем
                items, more = transcripts.history(w["path"], 30, before, home=home, sid=sid)
                for it in items:                           # ошибка Claude Code — ещё и простыми словами (простой режим)
                    if it.get("role") == "assistant" and (h := humanize.error(it.get("text") or "", strict=True)):
                        it["human"] = h
                return {"items": items, "more": more, "rev": rev}
            raise KeyError

        def openrouter_back(self, q: dict):
            try:
                panel.openrouter_done(q.get("code", ""), q.get("state", ""))
                title, text = "Ключ OpenRouter сохранён", "Вернитесь в панель — ключ на месте. Вкладку можно закрыть."
            except ValueError as e:
                title, text = "Не получилось", str(e)
            done = DONE_PAGE.format(title=escape(title), text=escape(text))
            self.reply(200, done.encode(), "text/html; charset=utf-8")

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/api/login/start":
                return self.dispatch(lambda: {"id": panel.login_start(*self.client())})
            if path == "/api/login/verify":
                return self.dispatch(self.login)
            if path == "/api/login/tg":
                return self.dispatch(self.tg_start)
            if path in PASSKEY_LOGIN:
                if not panel.keys.enabled:
                    return self.json({"error": "вход по ключу выключен на этом пульте", "code": "off"}, 503)
                return self.dispatch(lambda: self.passkey_login(path))
            if path in EMAIL_LOGIN:
                if not panel.email.enabled:
                    return self.json({"error": "вход по почте выключен на этом пульте", "code": "off"}, 503)
                return self.dispatch(lambda: self.email_login(path))
            if path.startswith("/api/offer/"):
                return self.offer("POST", path)
            if path in ("/api/invite/check", "/api/invite/enter"):   # лёгкий вход: код или ссылка, без Telegram
                return self.dispatch(lambda: self.invite_login(path))
            if path == "/api/focus/open":                  # фокус-ссылка: первое открытие привязывает устройство
                return self.dispatch(self.focus_open)
            if self.headers.get(focus.HEADER):
                q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
                return self.focus_call("POST", path, q)
            if path in HELP_OPEN and not self.who()[1]:   # экран входа: подсказки только по нему
                return self.dispatch(lambda: self.help_anon(path))
            if not path.startswith("/api/") or not self.permit(path, "POST"):
                return None if path.startswith("/api/") else self.json({"error": "нет такой страницы"}, 404)
            with panel.tmux.scope(self.space()):
                self.dispatch(lambda: self.post(path))

        def stt_stream(self):
            """Голос потоком (задача 46): звук PCM 16 бит из панели → служба T-one → частичный текст обратно.
            Браузер не умеет слать заголовки в WebSocket, поэтому вход — первым сообщением:
            ``{"init": initData Telegram | "", "focus": true | false, "rate": 16000}``; cookie входа и фокуса приходят
            сами. Права — как у ``/api/stt``. Дальше: двоичные кадры — звук, ``{"end": true}`` — итог,
            ``{"cancel": true}`` — отмена. Ответы: ``{"ready"}``, ``{"partial"}``, ``{"final"}``, ``{"error", "code"}``.
            Службы нет — ``code="asr_off"``: панель распознаёт ту же запись прежним ``/api/stt``."""
            key = wsock.accept(self.headers)
            if not key:
                return self.json({"error": "нужен WebSocket"}, 400)
            origin = self.headers.get("Origin", "")
            if origin and urllib.parse.urlparse(origin).netloc != self.headers.get("Host", ""):
                return self.json({"error": "запрос не со страницы пульта"}, 403)    # чужой сайт с нашей cookie
            self.close_connection = True
            self.wfile.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                              f"Sec-WebSocket-Accept: {key}\r\n\r\n").encode())
            self.connection.settimeout(STREAM_IDLE)
            ws, st = wsock.Conn(self.rfile, self.wfile), None
            try:
                st = self.stt_stream_open(ws)
                if st:
                    self.stt_stream_pump(ws, st)
            except wsock.ProtocolError as e:
                ws.close(e.code, "ошибка протокола")
            except (wsock.Closed, OSError, ValueError):
                pass                                   # панель ушла или служба оборвалась — панель повторит /api/stt
            finally:
                if st:
                    st.close()
                ws.close()
                self.focused = None

        def stt_stream_open(self, ws: wsock.Conn) -> asr.Stream | None:
            """Первое сообщение: вход и права; затем поток в службу. Отказ — сообщение с ``code`` и закрытие."""
            op, msg = ws.recv()
            b = json.loads(msg) if op == wsock.TEXT else None
            if not isinstance(b, dict):
                raise wsock.ProtocolError("первым — объект JSON")

            def fail(error: str, code: str, close: int):
                ws.send_text(json.dumps({"error": error, "code": code}, ensure_ascii=False))
                ws.close(close, code)

            if b.get("focus"):                             # фокус-ссылка: только её cookie, как у /api/stt в фокусе
                try:
                    self.focused = panel.focus_rec(self.focus_cookie())
                except focus.Gone as e:
                    return fail(str(e), "focus_gone", 4410)
            else:
                del self.headers["X-Telegram-Init-Data"]
                if b.get("init"):
                    self.headers["X-Telegram-Init-Data"] = str(b["init"])[:8192]
                errs: list = []
                self.json = lambda data, code=200: errs.append((code, data))   # отказ permit — не ответ HTTP
                try:
                    ok = self.permit(STT_STREAM, "POST")
                finally:
                    del self.json
                if not ok:
                    code, data = errs[0] if errs else (403, {})
                    return fail(data.get("error") or "нет доступа", data.get("code") or str(code), 4000 + code)
            try:
                return panel.stt_stream(int(b.get("rate") or 16000))
            except asr.Unavailable as e:
                return fail(str(e), "asr_off", 4503)

        def stt_stream_pump(self, ws: wsock.Conn, st: asr.Stream):
            """Звук панели → служба; ответы службы → панели (свой поток). Итог — и соединение закрывается."""
            ws.send_text('{"ready": true}')
            done = threading.Event()

            def back():
                final = False
                try:
                    for ev in st.events(STREAM_MAX_S * 2):
                        final = final or "final" in ev
                        if "error" in ev:                  # любой отказ службы — панель распознает запись по-старому
                            ev = {"error": ev["error"], "code": ev.get("code") or "asr_off"}
                        ws.send_text(json.dumps(ev, ensure_ascii=False))
                except (asr.Unavailable, OSError, ValueError, wsock.Closed):
                    if not final:
                        with contextlib.suppress(OSError, wsock.Closed):
                            ws.send_text(json.dumps({"error": "служба распознавания оборвала поток", "code": "asr_off"},
                                                    ensure_ascii=False))
                finally:
                    done.set()

            threading.Thread(target=back, daemon=True, name="stt-stream").start()
            got, cap = 0, STREAM_MAX_S * 16000 * 2
            while not done.is_set():
                op, msg = ws.recv()
                if op == wsock.BINARY:
                    got += len(msg)
                    if got <= cap:
                        st.audio(msg)
                    continue
                b = json.loads(msg)
                if not isinstance(b, dict) or b.get("cancel"):
                    break
                if b.get("end"):
                    st.end()
                    done.wait(15)
                    break
            ws.close(1000)

        def focus_cookie(self) -> str:
            for part in self.headers.get("Cookie", "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == focus.COOKIE:
                    return v
            return ""

        def focus_open(self):
            """Страница прочитала токен из «#focus=…» и отдала сюда: cookie устройства (первое открытие — привязка).
            Ссылка не действует — ``focus.Gone``: ответ 410 даёт ``dispatch`` (один ответ на запрос)."""
            b = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 4096)) or b"{}")
            value, rec = panel.focus.open(str((b if isinstance(b, dict) else {}).get("token") or ""),
                                          self.focus_cookie(), webauth.device(self.client()[1]))
            age = max(60, int(rec["exp"] - time.time()))
            cookie = f"{focus.COOKIE}={value}; Path=/; Max-Age={age}; HttpOnly; Secure; SameSite=Strict"
            return ("cookie", cookie, {"ok": True, "name": rec.get("name", "")})

        def focus_call(self, method: str, path: str, q: dict):
            """Запрос страницы в режиме фокуса: действующая ссылка этого устройства, путь из ``FOCUS_*``, окно — только
            её. Ссылка погасла — 410 (страница покажет «Сессия завершена»), чужое — 403."""
            try:
                rec = panel.focus_rec(self.focus_cookie())
            except focus.Gone as e:
                return self.json({"error": str(e), "code": "focus_gone"}, 410)
            except focus.Wait as e:                      # сессию перезапускают — ссылка жива, страница повторит
                return self.json({"error": str(e), "code": "focus_wait"}, 503)
            if path not in (FOCUS_GET if method == "GET" else FOCUS_POST):
                return self.json({"error": "по фокус-ссылке доступна только её сессия", "code": "focus_scope"}, 403)
            b: dict = {}
            if method == "POST" and path not in ("/api/upload", "/api/stt", "/api/space/upload"):
                try:
                    self.raw = self.body()
                    b = json.loads(self.raw or b"{}")
                except ValueError as e:
                    return self.json({"error": str(e) or "неверный запрос"}, 400)
                if not isinstance(b, dict):
                    return self.json({"error": "ожидался объект"}, 400)
            w = (q if method == "GET" or path == "/api/space/upload" else b).get("w")
            if path not in FOCUS_NO_W and str(w or "") != rec["w"]:
                return self.json({"error": "по фокус-ссылке доступна только её сессия", "code": "focus_scope"}, 403)
            self.focused = rec
            try:
                with panel.tmux.scope(rec.get("space")):
                    return self.dispatch(lambda: self.focus_do(method, path, q, b, rec))
            finally:                                      # соединение может жить дольше запроса — права не переносим
                self.focused, self.raw = None, None

        def focus_do(self, method: str, path: str, q: dict, b: dict, rec: dict):
            if path == "/api/meta":
                return {**panel.focus_meta(rec), "via": "focus", "role": "owner", "uid": None, "build": build}
            if path == "/api/sessions":
                ss = [s for s in panel.sessions(None) if s["id"] == rec["w"]]
                return {"sessions": ss, "host": rec.get("name", ""), "build": build, "now": time.time(), "cost": None,
                        "fallback": [], "focus": True}
            if path == "/api/logout":                      # «Выйти» на устройстве: cookie фокуса стираем, ссылка живёт
                gone = f"{focus.COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict"
                return ("cookie", gone, {"ok": True})
            if path == "/api/close":                       # «Завершить» в фокусе: сессия закрывается, ссылка гаснет
                w = panel.session_window(rec["w"])
                if b.get("schedule"):                      # агент модуля: оставить / приостановить / выключить
                    panel.set_schedule(w["path"], str(b["schedule"]), self.terms_uid())
                r = panel.close_ex(w)
                if r["result"] == "закрыто":
                    panel.focus.end_window(rec["w"])
                return r
            if path == "/api/space/close":
                r = panel.space_close(rec["space"], rec["w"], b.get("force") is True)
                if r.get("result") == "closed":
                    panel.focus.end_window(rec["w"])
                return r
            return self.get(path, q) if method == "GET" else self.post(path)

        def help_anon(self, path: str):
            if not panel.help_anon.ok(self.client_ip()):
                raise ValueError("слишком много вопросов — подождите несколько минут")
            b = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 4096)) or b"{}")
            if path.endswith("/feedback"):
                return panel.helper.feedback(str(b.get("id", "")), b.get("useful"), str(b.get("action", "")), "anon")
            return panel.helper.ask("anon", b.get("ctx"), str(b.get("q", "")), str(b.get("chip", "")),
                                    who=[panel.helper.who_key("ip", self.client_ip())])

        def tg_start(self):
            b = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 4096)) or b"{}")
            code = str((b if isinstance(b, dict) else {}).get("invite") or "")
            if code and not invites.check(code, short=False):    # через Telegram — только ссылкой (без перебора)
                raise ValueError("приглашение недействительно: истёк срок, уже использовано или отозвано")
            rid, nonce = panel.logins.start(*self.client(), invite=code)
            return {"id": rid, "link": f"https://t.me/{panel.bot_username()}?start=login_{nonce}",
                    "ttl": webauth.LOGIN_TTL}

        def invite_login(self, path: str):
            """«Есть код приглашения?» → проверка кода; «Как вас зовут?» → гость и cookie-сессия на 30 дней."""
            b = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 4096)) or b"{}")
            if not isinstance(b, dict):
                raise ValueError("ожидался объект")
            ip, ua = self.client()
            if path == "/api/invite/check":
                return panel.invite_check(str(b.get("code") or ""), ip)
            uid = panel.invite_enter(str(b.get("code") or ""), str(b.get("name") or ""), ip, ua)
            panel.seen_ip(uid, ip, force=True)
            return ("cookie", webauth.set_cookie(panel.auth.issue(uid, ua)), {"state": "ok"})

        def tg_poll(self, q: dict):
            state, uid = panel.logins.poll(q.get("id", ""))
            if state == "ok":
                if panel.email.wants_second(uid):                           # второй фактор: код ещё и на почту
                    return panel.email.second_start(uid, self.client_ip())
                panel.seen_ip(uid, self.client_ip(), force=True)            # вход — сверяем страну по IP
                panel.people.seen(uid, webauth.device(self.client()[1]))   # «вошёл: устройство, время»
                return ("cookie", webauth.set_cookie(panel.auth.issue(uid, self.client()[1])), {"state": "ok"})
            return {"state": state}

        def passkey_login(self, path: str):
            """Вход по ключу: опции (одноразовый вызов) → ответ устройства → сессия (или второй фактор с почты)."""
            b = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 65536)) or b"{}")
            if not isinstance(b, dict):
                raise ValueError("ожидался объект")
            ip, ua = self.client()
            if path == "/api/login/passkey/options":
                return panel.keys.login_options(ip)
            uid = panel.keys.login_verify(str(b.get("id", "")), b.get("credential"), ip)
            if panel.email.wants_second(uid):
                return panel.email.second_start(uid, ip)
            panel.seen_ip(uid, ip, force=True)
            panel.people.seen(uid, webauth.device(ua))
            return ("cookie", webauth.set_cookie(panel.auth.issue(uid, ua)), {"state": "ok"})

        def email_login(self, path: str):
            """Вход по коду на почту и второй фактор. Тело — не больше 4 КБ: адрес и код."""
            b = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 4096)) or b"{}")
            if not isinstance(b, dict):
                raise ValueError("ожидался объект")
            ip, ua = self.client()
            if path == "/api/login/email/start":
                return panel.email.login_start(b.get("email"), ip)
            if path == "/api/login/email/verify":
                uid = panel.email.login_verify(b.get("email"), b.get("code"), ip)
            else:
                uid = panel.email.second_verify(str(b.get("id", "")), b.get("code"), ip)
            panel.seen_ip(uid, ip, force=True)
            return ("cookie", webauth.set_cookie(panel.auth.issue(uid, ua)), {"state": "ok"})

        def oidc_page(self, code: int, title: str, text: str, cookies: tuple[str, ...] = ()):
            self.send_response(code)
            for c in cookies:
                self.send_header("Set-Cookie", c)
            body = OIDC_PAGE.format(title=escape(title), text=escape(text)).encode()
            for k, v in {**NOINDEX, "Content-Type": "text/html; charset=utf-8", "Content-Length": str(len(body)),
                         "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def go(self, location: str, cookies: tuple[str, ...] = ()):
            self.send_response(303 if location.startswith("/") else 302)
            for c in cookies:
                self.send_header("Set-Cookie", c)
            for k, v in {**NOINDEX, "Location": location, "Content-Length": "0", "Cache-Control": "no-store"}.items():
                self.send_header(k, v)
            self.end_headers()

        def oidc_step(self, p: str, step: str, q: dict):
            """Вход через Google / Яндекс ID: start → сайт провайдера → back → сессия (или второй фактор, или привязка).
            Это переходы браузера, поэтому ответы — переадресации и короткие страницы, а не JSON."""
            title = oidc.PROVIDERS[p]["title"]
            if not panel.oidc.enabled(p):
                return self.oidc_page(503, "Вход выключен", f"Вход через {title} на этом пульте выключен.")
            ip, ua = self.client()
            drop = oidc.set_cookie("", 0)
            try:
                if step == "start":
                    url, browser = panel.oidc.start(p, ip, str(q.get("link", ""))[:64])
                    return self.go(url, (oidc.set_cookie(browser),))
                r = panel.oidc.finish(p, q, oidc.cookie_value(self.headers.get("Cookie", "")), ip)
            except emailcode.LimitError as e:
                return self.oidc_page(429, "Слишком часто", str(e))
            except (ValueError, RuntimeError) as e:
                return self.oidc_page(400, "Не получилось", str(e), (drop,))
            if r["mode"] == "link":
                return self.oidc_page(200, f"{title} привязан",
                                      f"Теперь на экране входа можно нажать «Войти через {title}». "
                                      "Эту вкладку можно закрыть.", (drop,))
            uid = r["uid"]
            if panel.email.wants_second(uid):                       # второй фактор: код ещё и на почту
                d = panel.email.second_start(uid, ip)
                frag = urllib.parse.urlencode({"2fa": d["id"], "to": d["to"]})
                return self.go(f"/#{frag}", (drop,))                 # номер — во фрагменте: на сервер он не уходит
            panel.seen_ip(uid, ip, force=True)
            return self.go("/", (drop, webauth.set_cookie(panel.auth.issue(uid, ua))))

        def login(self):
            b = json.loads(self.body() or b"{}")
            token = panel.auth.verify(str(b.get("id", "")), str(b.get("code", "")), self.client()[1])
            panel.seen_ip((panel.cfg.owners or [None])[0], self.client_ip(), force=True)   # вход кодом — владелец
            return ("cookie", webauth.set_cookie(token), {"ok": True})

        # ---------- страница предложения: без входа, ничего из панели ----------
        def offer_reply(self, code: int, data, page: bool = False, cookie: str = "", csp: str = ""):
            h = dict(NOINDEX, **({"Content-Security-Policy": csp} if csp else {}))
            if page:
                return self.reply(code, data, "text/html; charset=utf-8", cookie, h)
            return self.reply(code, json.dumps(data, ensure_ascii=False).encode(), cookie=cookie, headers=h)

        def offer_cookie(self, sid: str, age: int = offers.DEMO_TTL) -> str:
            host = self.headers.get("Host", "").split(":")[0]
            secure = (self.client_address[0] in LOOPBACK and self.headers.get("X-Forwarded-Proto") == "https") or \
                host not in ("127.0.0.1", "localhost", "::1", "")
            flags = "; HttpOnly; SameSite=Lax" + ("; Secure" if secure else "")
            return f"{offers.COOKIE}={sid}; Path=/; Max-Age={age}" + flags

        def offer_sid(self) -> str:
            for part in self.headers.get("Cookie", "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == offers.COOKIE:
                    return v
            return ""

        def offer(self, method: str, path: str):
            """``/offer/<код>`` — страница; ``/api/offer/<код>[/действие]`` — её данные. Неизвестный, отозванный и
            просроченный код — один и тот же 404; перебор кодов с одного IP — 429 на любые коды."""
            m, ip = OFFER_PATH.match(path), self.client_ip()
            api = path.startswith("/api/")
            if panel.offer_misses.blocked(ip):
                body = {"error": "слишком много запросов — подождите 10 минут"}
                return self.offer_reply(429, OFFER_404.encode() if not api else body, page=not api)
            o = offers.load(m.group(2)) if m and bool(m.group(1)) == api else None
            if not o or (not api and (method != "GET" or m.group(3))):
                if not o:
                    panel.offer_misses.miss(ip)
                return self.offer_reply(404, OFFER_404.encode() if not api else {"error": "нет такой страницы"},
                                        page=not api)
            if not api:
                return self.offer_reply(200, offer_page, page=True, csp=offer_csp)
            sid, cookie = self.offer_sid(), ""
            s = panel.offer_demos.get(sid, o["code"])
            if not s:
                sid = panel.offer_demos.new(o["code"])
                s, cookie = panel.offer_demos.get(sid, o["code"]), self.offer_cookie(sid)
            act = m.group(3) or ""
            try:
                out = self.offer_act(method, act, o, s, sid)
            except KeyError:
                return self.offer_reply(404, {"error": "нет такого метода"}, cookie=cookie)
            except (ValueError, TelegramError, OSError) as e:
                return self.offer_reply(400, {"error": str(e) or "ошибка"}, cookie=cookie)
            if act == "forget":
                cookie = self.offer_cookie("", 0)
            return self.offer_reply(200, out, cookie=cookie)

        def offer_act(self, method: str, act: str, o: dict, s: dict, sid: str):
            if method == "GET" and act == "":
                bot = bool(panel._bot) or bool(panel.cfg.token)
                return {**offers.page(o), "bot": bot,
                        "session": {"reports": list(s["reports"].values()), "wizard": s["wizard"],
                                    "ttl": max(0, int(s["exp"] - time.time()))}}
            if method != "POST":
                raise KeyError
            if act == "upload":
                n = int(self.headers.get("Content-Length", 0) or 0)
                if n > offer_report.MAX_BYTES:
                    left = min(n, 4 * offer_report.MAX_BYTES)             # дочитать (не храня), чтобы ответ дошёл
                    while left > 0 and (chunk := self.rfile.read(min(left, 1 << 16))):
                        left -= len(chunk)
                    self.close_connection = True
                    raise ValueError(f"Файл больше {offer_report.MAX_BYTES >> 20} МБ — выгрузите период покороче.")
                if not panel.offer_demos.upload_ok(s):
                    raise ValueError("слишком много загрузок — подождите 10 минут")
                data = self.rfile.read(n)
                try:
                    mapping = json.loads(self.headers.get("X-Offer-Map", "")[:2000] or "null")
                except ValueError:
                    mapping = None
                rep = offer_report.build(data, self.headers.get("X-Offer-Kind", ""),
                                         mapping if isinstance(mapping, dict) else None)
                del data                                                  # байты файла дальше не нужны
                return rep if rep.get("error") else panel.offer_demos.put_report(s, rep)
            b = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 4096)) or b"{}")
            if not isinstance(b, dict):
                raise ValueError("ожидался объект")
            if act == "forget":                                           # «Удалить мои данные»
                panel.offer_demos.drop(sid)
                return {"ok": True}
            if act == "wizard":
                return panel.offer_wizard(o, s, b)
            if act == "login":
                return panel.offer_login(o, s, *self.client())
            if act == "help":                                             # помощник гостя: только его страница
                return panel.help_guest(o, sid, self.client_ip(), b)
            if act == "helpfb":
                return panel.helper.feedback(str(b.get("id", "")), b.get("useful"), str(b.get("action", "")), "guest")
            if act == "telegram":
                base = panel.public_url or ""
                return panel.offer_telegram(o, str(b.get("module", "")), f"{base}/offer/{o['code']}" if base else "")
            raise KeyError

        def terms_info(self) -> dict:
            rec = panel.people.terms(self.terms_uid()) or {}
            return {"version": terms.VERSION, "title": terms.TITLE, "points": list(terms.POINTS), "url": terms.URL,
                    "accepted": rec.get("version") == terms.VERSION, "at": rec.get("at")}

        def post(self, path: str):
            if path == "/api/space/upload":              # файл — в папку сессии пространства (от его пользователя)
                slug, w = self.space_win(dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query)))
                name = urllib.parse.unquote(self.headers.get("X-File-Name", "file"))
                return {"name": space_files.put(slug, space_files.folder_of(slug, w), name, self.body())}
            if path == "/api/upload":
                return {"path": panel.upload(self.headers.get("X-File-Name", "file"), self.body())}
            if path == "/api/stt":
                before = panel.fallback_note()
                text = panel.stt(self.body(), self.headers.get("Content-Type", ""), cloud=not self.space())
                now = panel.fallback_note()
                return {"text": text, "fallback": now if now and now != before else ""}
            b = json.loads(self.body() or b"{}")
            if path == "/api/prefs":                       # простой режим и язык — у каждого свои
                lang, uid, role = b.get("lang"), self.terms_uid(), self.who()[1]
                if b.get("simple") is True and panel.is_owner(uid):
                    raise ValueError("ваше пространство — всегда полный пульт; простой режим — в «Демо и тестах»")
                if b.get("simple") is not None and not panel.is_owner(uid):   # прежний переключатель — смена роли
                    cur = panel.ui(uid, role)["persona"]
                    want = b.get("simple") is True
                    if want != (cur in personas.SIMPLE):
                        panel.set_ui(uid, role, {"persona": "business_owner" if want else "developer"})
                p = panel.people.set_prefs(uid, None if b.get("simple") is None else b.get("simple") is True,
                                           None if lang is None else str(lang))
                return {**p, "simple": panel.prefs(uid, role)["simple"]}
            if path == PERSONA:
                return panel.set_ui(self.terms_uid(), self.who()[1], b if isinstance(b, dict) else {})
            if path == "/api/team":
                uid = b.get("id")
                caps, secs = b.get("caps"), b.get("sections")
                if uid is not None and int(uid) not in [p["id"] for p in panel.team_info()["people"]]:
                    raise ValueError("это не сотрудник пульта")
                panel.team.set(caps if isinstance(caps, list) else None, secs if isinstance(secs, list) else None,
                               None if uid is None else int(uid), b.get("reset") is True)
                return panel.team_info()
            if path == "/api/terms/accept":
                if str(b.get("version", "")) != terms.VERSION:
                    raise ValueError("условия обновились — прочитайте новую версию")
                panel.people.accept(self.terms_uid(), terms.VERSION)
                return self.terms_info()
            if path == "/api/country":
                return panel.set_country(self.terms_uid(), str(b.get("code", "")))
            if path == TOUR:
                return panel.people.set_tour(self.terms_uid(), str(b.get("tour", "")), str(b.get("state", "")))
            if path == "/api/passkeys/options":
                uid = self.terms_uid()
                return panel.keys.register_options(uid, panel.key_label(uid), self.client_ip())
            if path == "/api/passkeys/add":
                return {"keys": panel.keys.register_verify(self.terms_uid(), str(b.get("id", "")), b.get("credential"),
                                                           str(b.get("name", "")), self.client_ip())}
            if path == "/api/passkeys/remove":
                return {"keys": panel.keys.remove(self.terms_uid(), str(b.get("id", "")))}
            if path == "/api/oidc/link":                   # ссылка на привязку — открыть в браузере (и из Telegram)
                p = str(b.get("provider", ""))
                ticket = panel.oidc.ticket(self.terms_uid(), p, self.client_ip())
                return {"url": f"/api/login/oidc/{p}/start?link={ticket}"}
            if path == "/api/oidc/unlink":
                return panel.oidc.unlink(self.terms_uid(), str(b.get("provider", "")))
            if path == "/api/email/bind":
                return panel.email.bind_start(self.terms_uid(), b.get("email"), self.client_ip())
            if path == "/api/email/confirm":
                return panel.email.bind_confirm(self.terms_uid(), b.get("email"), b.get("code"))
            if path == "/api/email/remove":
                return panel.email.unbind(self.terms_uid())
            if path == "/api/email/options":
                return panel.email.options(self.terms_uid(), b.get("second_factor"), b.get("notify"))
            if path == "/api/help/ask":                    # роль — с сервера, не от клиента
                return panel.help_ask(self.who()[1], self.terms_uid(), b if isinstance(b, dict) else {})
            if path == "/api/help/feedback":
                return panel.helper.feedback(str(b.get("id", "")), b.get("useful"), str(b.get("action", "")),
                                             self.who()[1])
            if path == "/api/commands/run":
                return panel.command_run(str(b.get("id", "")), bool(b.get("confirmed")))
            if path == "/api/commands/mark":
                return panel.command_mark(str(b.get("id", "")), b.get("done", True) is not False)
            if path == "/api/people/role":
                panel.set_role(int(b.get("id", 0)), str(b.get("role", "")))
                return {"people": panel.people_list(), **panel.geo.info()}
            if path == "/api/people/remove":
                panel.forget_person(int(b.get("id", 0)))
                return {"people": panel.people_list(), **panel.geo.info()}
            if path == "/api/logout":
                panel.auth.logout(self.session())
                return ("cookie", webauth.set_cookie("", 0), {"ok": True})
            if path == "/api/mcp/add":
                home, preset = self.home(), str(b.get("preset", ""))
                if home and preset in OWNER_PRESETS:
                    raise ValueError("свою программу на сервере подключает только владелец")
                return {"result": panel.mcp.add(preset, str(b.get("name", "")), b.get("values") or {}, home=home)}
            if path == "/api/mcp/remove":
                return {"result": panel.mcp.remove(str(b.get("name", "")), home=self.home())}
            if path == "/api/keys":
                return panel.set_key(str(b.get("provider", "")), str(b.get("key", "")))
            if path == "/api/keys/remove":
                panel.remove_key(str(b.get("provider", "")))
                return {"ok": True}
            if path == "/api/providers":
                panel.set_providers(b)
                return {"ok": True}
            if path == "/api/voice/choose":
                panel.choose_voice(str(b.get("id", "")))
                return panel.voice_cards(True)
            if path == "/api/mcp/login":
                return panel.mcp_login(str(b.get("name", "")), self.home())
            if path == "/api/setup/login":                  # окно входа и ссылка с экрана (до 20 с)
                return panel.login.start()
            if path == "/api/setup/code":
                r = panel.login.send_code(str(b.get("code", "")))
                panel._setup = (0, {})
                return r
            if path == "/api/setup/cancel":
                panel.login.cancel()
                return {"ok": True}
            if path == "/api/new" and (slug := self.space()):
                return panel.new_in_space(slug, str(b.get("name", "")))
            if path == "/api/model/default":             # только явной настройкой — не из чата
                return panel.default_model(str(b.get("model") or ""))
            if path == "/api/commands/term":             # вкладка «Команды»: нужен ввод — в окне терминала
                return panel.command_term(str(b.get("id", "")), bool(b.get("confirmed")))
            if path == "/api/term/type":                 # строка (пароль) — в окно gp-term; из Mini App — нет
                if self.headers.get("X-Telegram-Init-Data"):
                    raise ValueError("пароль в Telegram не вводим — откройте панель в браузере или Termius")
                termwin.type_line(panel.tmux, str(b.get("id", "")), str(b.get("text", "")))
                return {"ok": True}
            if path == "/api/term/key":                  # Ctrl+C, Ctrl+D, Enter
                termwin.key(panel.tmux, str(b.get("id", "")), str(b.get("key", "")))
                return {"ok": True}
            if path == "/api/term/close":
                termwin.close(panel.tmux, str(b.get("id", "")))
                return {"ok": True}
            if path in ("/api/tty/type", "/api/tty/key"):   # живой терминал: текст и клавиши прямо в окно
                owner = self.who()[1] == "owner"
                w = panel.tty_window(str(b.get("w") or ""), owner, write=True)
                if path == "/api/tty/key":
                    termwin.tty_key(panel.tmux, w["id"], str(b.get("key", "")), owner)
                    return {"ok": True}
                if w.get("name") == termwin.WINDOW and self.headers.get("X-Telegram-Init-Data"):
                    raise ValueError("в окно с паролем из Telegram не вводим — откройте панель в браузере")
                termwin.tty_type(panel.tmux, w["id"], str(b.get("text", "")))
                return {"ok": True}
            if path == "/api/balance/clear":             # «Я пополнил» — снова предлагать поставщика
                st = panel.pult.state()
                panel.pult.set_state(no_balance=balance.clear(st, str(b.get("profile", ""))))
                return {"ok": True}
            if path == "/api/space/budget/add":         # владелец: «+ добавить» к запасу пространства
                return panel.budget_add(tenants.check_slug(str(b.get("space", ""))), float(b.get("usd") or 0),
                                        self.terms_uid())
            if path == "/api/space/close":
                r = panel.space_close(self.space_of(b), str(b.get("w", "")), b.get("force") is True)
                if r.get("result") == "closed":
                    panel.focus.end_window(str(b.get("w", "")))
                return r
            if path == "/api/space/resume":
                return panel.space_resume(self.space_of(b), str(b.get("folder", "")))
            if path == "/api/space/delete":
                return panel.space_delete(self.space_of(b), str(b.get("folder", "")), str(b.get("confirm", "")))
            if path == "/api/space/restore":
                return panel.space_restore(self.space_of(b), str(b.get("id", "")))
            if path == "/api/new":
                return panel.new(int(b.get("i", -1)), str(b.get("profile", "")), self.person(), self.terms_uid())
            if path == "/api/project/session":           # «Новая сессия в проекте» — ещё одно окно, свой журнал
                return panel.project_session(str(b.get("id", "")), str(b.get("profile", "")), self.person(),
                                             self.terms_uid())
            if path == "/api/project/resume":            # «Продолжить» завершённый чат (--resume)
                return panel.project_resume(str(b.get("id", "")), str(b.get("sid", "")), self.person(),
                                            self.terms_uid())
            if path == "/api/project/chat":              # переименовать / скрыть чат проекта
                return panel.project_chat(str(b.get("id", "")), str(b.get("sid", "")), b.get("title"),
                                          b.get("hidden"))
            if path == "/api/chat/delete":                # «Удалить» сессию или чат: окно закрыто, журнал — в корзину
                return panel.chat_delete(str(b.get("w") or ""), str(b.get("id") or ""), str(b.get("sid") or ""))
            if path == "/api/chat/restore":               # «Вернуть» из корзины
                return panel.chat_restore(str(b.get("id") or ""))
            if path == "/api/folder":                     # «Новая папка» → сессия в ней (как 📁 в боте)
                return panel.new_folder(str(b.get("name", "")), str(b.get("profile", "")), self.person(),
                                        self.terms_uid())
            if path == "/api/modules/create":
                return panel.module_create(str(b.get("id", "")), str(b.get("name", "")), str(b.get("profile", "")),
                                           self.person(), self.terms_uid(), str(b.get("lang", "")),
                                           b.get("again") is True)
            if path == "/api/openrouter/start":
                base = panel.public_url or f"https://{self.headers.get('Host', '')}"
                return {"url": panel.openrouter.start(base)}
            if path == "/api/fallback":
                return panel.set_fallback(b.get("chain"), self.terms_uid())
            if path == SELFTEST:                          # «Проверить сейчас» — в фоне, итог — GET
                started = selftest.start(panel.cfg.data, panel.pult.state())
                return {"started": started, **selftest.public(panel.cfg.data, panel.pult.state())}
            if path == "/api/cost/limits":
                return panel.set_cost_limits(b)
            if path == "/api/cost/decide":                  # пауза по расходу: «go» — продолжить, «stop» — оставить
                return {"result": panel.pult.cost_decide(str(b.get("w", "")), str(b.get("act", ""))),
                        **panel.cost_limits()}
            if path == "/api/models":
                url = b.get("base_url")
                panel.set_models(str(b.get("profile", "")), str(b.get("main", "")), str(b.get("fast", "")),
                                 None if url is None else str(url))
                return {"profiles": models.public(panel.pult.state(), panel.countries(self.terms_uid()))}
            if path == "/api/revive":
                return panel.revive(str(b.get("w", "")), self.terms_uid())
            if path == "/api/focus/new":                   # «Фокус-ссылка» из меню сессии
                return panel.focus_new(str(b.get("w", "")), self.terms_uid(), str(b.get("base", "")))
            if path == "/api/focus/send":                  # «Отправить себе в Telegram»
                return panel.focus_send(str(b.get("url", "")), self.terms_uid())
            if path == "/api/focus/qr":                    # QR — POST: адрес с токеном не попадает в журнал прокси
                panel.focus_token(str(b.get("url", "")))
                return ("image/png", qr.png_of(str(b["url"])))
            if path == "/api/focus/revoke":
                return {"ok": panel.focus.revoke(str(b.get("id", ""))), "links": panel.focus.listing()}
            if path == "/api/invite/new":                  # владелец: ссылка, короткий код и QR — одно приглашение
                inv = invites.new(str(b.get("space", "")), str(b.get("role") or "member"), by=self.terms_uid())
                return {"path": f"/invite/{inv['code']}", "code": inv["short"], "hint": inv["hint"], "ttl": invites.TTL}
            if path == "/api/invite/device":               # ссылка для входа на другое устройство: себе или владелец
                owner = self.who()[1] == "owner"
                target = int(b["id"]) if owner and b.get("id") is not None else self.terms_uid()
                return panel.device_link(target, self.terms_uid())
            if path == "/api/link/tg":                     # гость: «Привязать Telegram» — ссылка на бота
                uid = self.terms_uid()
                if not is_guest(uid):
                    raise ValueError("Telegram у вас уже привязан")
                rid, nonce = panel.logins.start(*self.client(), link=uid)
                return {"id": rid, "link": f"https://t.me/{panel.bot_username()}?start=login_{nonce}",
                        "ttl": webauth.LOGIN_TTL}
            if path == "/api/space/task":
                return panel.space_task(str(b.get("space", "")), str(b.get("name", "")), str(b.get("task", "")))
            if path in ("/api/module/schedule", "/api/module/delete"):   # пространство из модуля (задача 39)
                w = panel.tmux.window(str(b.get("w") or ""))
                if not w:
                    raise LookupError("окна уже нет")
                if path == "/api/module/schedule":
                    return panel.set_schedule(w["path"], str(b.get("state", "")), self.terms_uid())
                return panel.module_delete(w, str(b.get("confirm", "")))
            if path in ("/api/repos/add", "/api/repos/remove"):   # задача 43: клон и /add-dir; «Отключить»
                w = self.repo_win(b)
                if path == "/api/repos/add":
                    return panel.repo_add(w, str(b.get("repo", "")))
                return panel.repo_remove(w, str(b.get("path", "")))
            if path == "/api/close":                       # и остановленную: окно с оболочкой просто закрыть
                w = panel.session_window(b.get("w"))
                if b.get("schedule"):                      # сессия модуля: оставить / приостановить / выключить
                    panel.set_schedule(w["path"], str(b["schedule"]), self.terms_uid())
                r = panel.close_ex(w)                      # {result, draft}: черновик не теряется молча
                if r["result"] == "закрыто":
                    panel.focus.end_window(w["id"])        # фокус-ссылки этой сессии гаснут сразу
                return r
            w = self.win(b.get("w"))
            if path == "/api/space/connect":
                return panel.owner_join(w)
            if path == "/api/help/call":                    # тестировщик: «Позвать на помощь» — владельцу в бот
                return panel.call_help(self.terms_uid(), w)
            if w.get("space") and self.who()[1] == "owner" and path in ("/api/send", "/api/select", "/api/key"):
                panel.owner_seen[w["id"]] = time.time()      # владелец пишет или отвечает — тестировщик увидит
            if path == NOTIFY_DONE:                       # одно сообщение в бот, когда ход закончится (бот следит)
                return {"result": panel.pult.ask_notify_done(w["id"], self.terms_uid())}
            if path in ("/api/send", "/api/command", "/api/select", "/api/key", "/api/model"):
                panel.check(w.get("profile") or "claude", self.terms_uid())   # сессия этого поставщика — для страны?
            if path == "/api/send":
                text = str(b.get("text", "")).strip()
                if not text:
                    raise ValueError("пустое сообщение")
                return {"ok": True, "dup": panel.send(w, text, str(b.get("id", ""))[:64])}
            if path == "/api/rename":
                return {"name": panel.tmux.rename(w["id"], str(b.get("name", "")))}
            if path == "/api/active" and w.get("space"):
                raise ValueError("сессия демо-пространства не бывает активной в чате бота — откройте её в панели")
            if path == "/api/active":
                panel.pult.set_state(active=w["id"])
                return {"ok": True}
            if path == "/api/command":
                return panel.command(w, int(b.get("i", -1)))
            if path == "/api/model":                     # модель — только этого чата (перезапуск с --model)
                return panel.model(w, str(b.get("name", "")), self.terms_uid())
            if path == "/api/effort":
                return {"lines": panel.effort(w, str(b.get("level", "")))}
            if path == "/api/key":
                return {"lines": panel.key(w, str(b.get("key", "")))}
            if path == "/api/select":
                go = b.get("go", True) is not False            # go: false — только выделить пункт
                return {"lines": panel.select(w, str(b.get("text", "")), str(b.get("n", "")), go)}
            if path == "/api/mcp/finish":
                return {"result": panel.mcp_finish(w, str(b.get("url", "")), str(b.get("name", "")), self.home())}
            if path == "/api/restart":
                return panel.restart(w, str(b.get("profile", "")), b.get("keep", True) is not False, self.terms_uid())
            if path == "/api/run":
                return panel.run(w, int(b.get("i", -1)), str(b.get("sha", "")), bool(b.get("confirmed")))
            if path == "/api/run/term":                  # из ответа: нужен ввод — в окне терминала, не вслепую
                return panel.term_run(w, int(b.get("i", -1)), str(b.get("sha", "")), bool(b.get("confirmed")))
            raise KeyError

        def dispatch(self, fn):
            try:
                out = fn()
            except KeyError:
                return self.json({"error": "нет такого метода"}, 404)
            except focus.Gone as e:                      # фокус-ссылка не действует: страница покажет почему
                return self.json({"error": str(e), "code": "focus_gone"}, 410)
            except LookupError as e:
                return self.json({"error": str(e)}, 404)
            except emailcode.LimitError as e:
                return self.json({"error": str(e), "retry": e.retry}, 429)
            except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired, providers.ProviderError) as e:
                return self.json({"error": str(e) or "ошибка"}, 400)
            if isinstance(out, tuple) and out[0] == "cookie":
                return self.reply(200, json.dumps(out[2], ensure_ascii=False).encode(), cookie=out[1])
            if isinstance(out, tuple):                   # (тип, байты[, заголовки]) — файл, звук
                return self.reply(200, out[1], out[0], headers=out[2] if len(out) > 2 else None)
            return self.json(out)

    return H


def tunnel(port: int) -> tuple[subprocess.Popen, str]:
    """Временный HTTPS-адрес Cloudflare (без аккаунта); адрес меняется при каждом запуске."""
    p = subprocess.Popen(["cloudflared", "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    deadline = time.time() + 60
    for line in p.stderr:
        if m := TUNNEL_URL.search(line):
            threading.Thread(target=lambda: [None for _ in p.stderr], daemon=True).start()   # читаем дальше
            return p, m.group(0)
        if time.time() > deadline:
            break
    p.kill()
    raise RuntimeError("cloudflared не выдал адрес за минуту")


def set_menu(api: Api, owners: list[int], url: str):
    """Кнопка «📱 Панель» каждому. Ошибка у одного (например, «user not found» — человек не открывал бота)
    не мешает остальным: печатаем и идём дальше."""
    for chat in owners:
        try:
            api("setChatMenuButton", chat_id=chat,
                menu_button={"type": "web_app", "text": "📱 Панель", "web_app": {"url": url}})
        except TelegramError as e:
            print(f"menu: {chat}: {e}", flush=True)


WINDOWS_TTL = 2.0                                   # с: см. Tmux.ttl


def serve(cfg: Config, port: int = 8765, use_tunnel: bool = False, url: str | None = None):
    Tmux.ttl = WINDOWS_TTL                          # список окон — общий на цикл опроса браузера (tmux.py)
    panel = Panel(cfg)
    panel.owner_space_fix()                         # вид владельца — его выбор, не чужой (см. owner_space_fix)
    menu_for = cfg.owners + [p["id"] for p in panel.people.list()               # кнопка «📱 Панель»; гостям без
                             if p["role"] != "owner" and has_telegram(p["id"])]   # Telegram — некуда
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler(panel))

    def learn_bot():                                       # имя бота — для ссылки «подтвердите номер в боте»
        panel.geo.lookup("192.0.2.1")                      # и база GeoIP — в память заранее, не на первом входе
        try:
            panel.bot_username()
        except (TelegramError, OSError, KeyError) as e:
            print("bot:", e, flush=True)
    threading.Thread(target=learn_bot, daemon=True).start()

    def sweep():                                           # отчёты демо-страниц — удалить точно в срок
        while True:
            time.sleep(60)
            panel.offer_demos.sweep()
    threading.Thread(target=sweep, daemon=True).start()
    proc = None
    if use_tunnel:
        proc, url = tunnel(port)
    if url:
        panel.public_url = url
        try:
            set_menu(Api(cfg.token), menu_for, url)
        except TelegramError as e:
            print("menu:", e, flush=True)
    print(f"gas-pult webapp: http://127.0.0.1:{port}" + (f" → {url} · кнопка «📱 Панель» в меню бота" if url else ""),
          flush=True)
    try:
        srv.serve_forever()
    finally:
        if proc:
            proc.terminate()
