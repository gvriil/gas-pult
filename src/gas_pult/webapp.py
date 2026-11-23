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
import gzip
import hashlib
import hmac
import io  # noqa: F401 — webapp.* жив (panel/sessions.py)
import json
import os
import re
import secrets
import shlex  # noqa: F401 — webapp.* жив (panel/sessions.py)
import shutil  # noqa: F401 — webapp.* жив (panel/sessions.py)
import socket  # noqa: F401 — webapp.* жив (desktop.py)
import stat
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid  # noqa: F401 — webapp.* жив (panel/sessions.py)
from datetime import date, datetime, timedelta  # noqa: F401 — webapp.datetime жив (panel/work.py)
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import BinaryIO, ClassVar  # noqa: F401 — webapp.* жив (panel/sessions.py)

from gas_pult import (
    ago,  # noqa: F401 — webapp.* жив (panel/sessions.py)
    alerts,
    apitokens,
    approvals,
    asr,
    balance,  # noqa: F401 — webapp.* жив (routes/model_keys.py, routes/integrations.py)
    brand,
    bridge,
    bridge_install,
    calkeys,  # noqa: F401 — webapp.* жив (routes/model_keys.py, routes/integrations.py)
    chat_trash,  # noqa: F401 — корзина чатов в panel/projects.py; имя webapp.chat_trash живо
    chatlog,
    chatmcp,  # noqa: F401 — webapp.* жив (panel/sessions.py)
    country,
    ctxsnap,  # noqa: F401 — webapp.* жив (routes/sessions.py)
    deskmobile,  # noqa: F401 — webapp.* жив (routes/desktop.py)
    desktabs,  # noqa: F401 — webapp.* жив (routes/desktop.py)
    drafts,
    drive_inbox,
    emailcode,
    fallback,
    features,
    feedback,
    focus,
    funnel,
    harness,
    helper,
    humanize,
    invites,
    logins,
    meetings,
    models,
    modules,
    notifylevel,  # noqa: F401 — webapp.* жив (routes/sessions.py)
    notifyroute,
    offer_report,
    offers,
    oidc,
    onboarding,
    passkeys,
    personas,
    pi_journal,  # noqa: F401 — webapp.* жив (panel/sessions.py)
    projects,
    providers,
    qr,
    recparts,
    repos,  # noqa: F401 — webapp.* жив (panel/spaces.py)
    router,
    routes,
    scenarios,  # noqa: F401 — webapp.* жив (routes/sessions.py)
    selftest,  # noqa: F401 — webapp.* жив (routes/model_keys.py, routes/integrations.py)
    setup,
    share,
    space_budget,  # noqa: F401 — webapp.* жив (panel/spaces.py)
    space_files,  # noqa: F401 — webapp.* жив (routes/)
    space_mcp,  # noqa: F401 — webapp.* жив (routes/)
    space_projects,
    space_sessions,  # noqa: F401 — webapp.* жив (panel/spaces.py)
    spaces,
    speech,  # noqa: F401 — webapp.speech: голос в panel/voice.py, имя живо
    spend,  # noqa: F401 — webapp.* жив (routes/model_keys.py, routes/integrations.py)
    starters,  # noqa: F401 — webapp.* жив (routes/sessions.py)
    steps,  # noqa: F401 — webapp.* жив (routes/sessions.py)
    tasks,
    teammsg,
    tenants,
    terms,
    termwin,  # noqa: F401 — webapp.* жив (routes/)
    testers,  # noqa: F401 — webapp.* жив (panel/spaces.py)
    tmux,  # noqa: F401 — webapp.* жив (panel/sessions.py)
    transcripts,  # noqa: F401 — webapp.* жив (routes/sessions.py)
    usage,
    voice,  # noqa: F401 — webapp.voice (тесты подменяют voice.synth): голос в panel/voice.py
    webauth,
    webpush,
    wsock,
)
from gas_pult import brief as morning_brief  # noqa: F401 — «brief» ниже — «Кратко» для озвучки; webapp.morning_brief жив
from gas_pult.access import (  # noqa: F401 — таблица прав переехала в access.py; старые имена webapp.* живы
    ADMIN_OK,
    BRIEF,
    BUDGET_PATHS,
    BUG,
    CONFIRM,
    CONFIRM_API,
    COUNTRY_FREE,
    DEMO_GET,
    DEMO_POST,
    EMAIL_LOGIN,
    EMAIL_OWN,
    FEEDBACK,
    FOCUS_GET,
    FOCUS_NO_W,
    FOCUS_POST,
    FOCUS_PROJ_GET,
    FOCUS_PROJ_POST,
    HELP_OPEN,
    INVITE_OWN,
    MEETING_GET,
    MEETING_POST,
    MEMBER_ONLY,
    NOTIFY_DONE,
    OIDC_OWN,
    OIDC_PATH,
    OWNER_ONLY,
    OWNER_PRESETS,
    PASSKEY_LOGIN,
    PASSKEY_OWN,
    PERSONA,
    PUSH_OWN,
    REPOS,
    SELFTEST,
    SLINK,
    SLINK_HEADER,
    SLINK_NO,
    SPACE_OK,
    STT_JOB,
    STT_STREAM,
    TERM,
    TERMS_FREE,
    TOUR,
    TTY,
    USES,
    V1_GET,
    V1_NEVER,
    V1_POST,
    V1_PREFIX,
)
from gas_pult.billing import api as billing_api  # noqa: F401 — платежи: маршруты в routes/billing.py; имя живо
from gas_pult.bot import BUSY, DIALOG, KEYS, PROMPTS, AwaitsChoice, Pult  # noqa: F401 — webapp.BUSY жив (panel/spaces.py)
from gas_pult.commands import DANGER, FULL, SPACE_RUN, TAIL, execute, extract, in_space  # noqa: F401 — реэкспорт
from gas_pult.config import Config
from gas_pult.desktop import (  # noqa: F401 — рабочий стол, ссылки сайтов, «Терминал» — в desktop.py; webapp.* живы
    CDP,
    DESK_COOKIE,
    DESK_PASSES,
    DESK_TICKETS,
    DESK_TTL,
    DESKTOP_PORT,
    DESKTOP_URL,
    LINK_OPEN,
    SHELL_WINDOW,
    TICKET_TTL,
    desk_cookie,
    desk_pass,
    desk_ticket,
    desktop_tab,
    desktop_up,
    link_pref_set,
    link_prefs,
    shell_window,
)
from gas_pult.mcp import CONNECTORS, CONNECTORS_URL, PRESETS, Mcp  # noqa: F401 — webapp.* живы (routes/)
from gas_pult.messengers import panel as messengers_panel  # noqa: F401 — маршруты в routes/messengers.py
from gas_pult.openrouter import CALLBACK, OpenRouter
from gas_pult.panel.clients import ClientsPart
from gas_pult.panel.focus import FocusPart
from gas_pult.panel.people import PeoplePart
from gas_pult.panel.projects import (  # noqa: F401 — «Проекты» переехали в panel/projects.py; старые имена webapp.* живы
    EFFORTS,
    NeedForce,
    ProjectsPart,
    effort_flag,
)
from gas_pult.panel.sessions import (  # noqa: F401 — окна сессий переехали в panel/sessions.py; webapp.* живы
    AUTH_WITH,
    CONTEXT,
    MODEL_LINE,
    URL_TAIL,
    SessionsPart,
    effort_ok,
    find_auth,
)
from gas_pult.panel.spaces import SpacesPart
from gas_pult.panel.voice import (  # noqa: F401 — голос переехал в panel/voice.py; старые имена webapp.* живы
    AUDIO_EXT,
    EL_PAUSE,
    HEAD_CHARS,
    STT_EMPTY,
    STT_JOB_TIMEOUT,
    STT_KEEP_DAYS,
    STT_TIMEOUT,
    VoicePart,
    brief,
    head_of,
)
from gas_pult.panel.work import WorkPart, utc_now  # noqa: F401 — задачи, команды, модули — в panel/work.py
from gas_pult.people import STAFF_ROLES, TITLES, People, allowed, has_telegram, is_guest  # noqa: F401 — webapp.* живы
from gas_pult.telegram import Api, TelegramError
from gas_pult.tmux import Tmux
from gas_pult.uploads import MAX_BODY, upload_log  # noqa: F401 — загрузка файлов — в uploads.py; webapp.* живы
from gas_pult.voice import catalog

PART_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")   # имя части интерфейса: web/js/<имя>.js
PART_PATH = re.compile(r"/js/([a-z0-9][a-z0-9-]{0,40})\.js")
BRIDGE_MAX = 16 << 20                      # сообщение моста: base64 снимка экрана или страницы


def bridge_local_token(data: Path) -> str:
    """Секрет для ``/api/bridge/rpc``: файл ``bridge-local.token`` (0600) в папке данных — его читают только процессы
    пульта (``gas-pult bridge-mcp``); нет — создаём."""
    f = Path(data) / "bridge-local.token"
    try:
        t = f.read_text(encoding="utf-8").strip()
        if t:
            return t
    except OSError:
        pass
    from gas_pult.config import write_private
    t = secrets.token_urlsafe(32)
    write_private(f, t)
    return t


SENT = routes.SENT                       # обработчик сам отправил ответ (dispatch ничего не дописывает)
GZIP_LEVEL = 5                          # ответы API — быстро и в разы меньше; страница — заранее с уровнем 9
GZIP_MIN = 1024                         # меньше — сжимать не стоит
GZIP_TYPES = ("text/", "application/json", "application/javascript", "image/svg+xml")


def gzips(accept: str, ctype: str, body: bytes) -> bool:
    """Сжимать ли ответ: клиент принимает gzip, тип текстовый, тело не меньше ``GZIP_MIN``."""
    return (len(body) >= GZIP_MIN and ctype.startswith(GZIP_TYPES)
            and any(p.split(";")[0].strip() == "gzip" for p in accept.lower().split(",")))


MAX_AGE = 24 * 3600                     # initData старше суток не принимаем
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


PANEL_KEYS = [("Ctrl+C", "C-c")]                     # прервать зависшую команду (в боте этой клавиши нет)
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


TEMP_SKIP = {"inbox"}                                      # входящие файлы — своя очистка (#217)


def sweep_temp(data: Path, now: float, age: float) -> list[Path]:
    """Остатки оборванной озвучки (``*.tmp.wav``, пустые ``*.mp3``) старше ``age`` с в ``data`` и её подпапках первого
    уровня (кроме ``TEMP_SKIP``) — удалить. → что удалено."""
    dirs = [data] + [d for d in sorted(data.iterdir()) if d.is_dir() and not d.is_symlink()
                     and d.name not in TEMP_SKIP] if data.is_dir() else []
    gone = []
    for d in dirs:
        for f in [*d.glob("*.tmp.wav"), *d.glob("*.mp3")]:
            try:
                st = f.lstat()
                if not stat.S_ISREG(st.st_mode) or now - st.st_mtime < age:
                    continue
                if f.name.endswith(".mp3") and st.st_size:
                    continue                               # озвучка с содержимым — кеш голосов, не мусор
                f.unlink()
                gone.append(f)
            except OSError:
                pass
    return gone


class Panel(ProjectsPart, SessionsPart, WorkPart, ClientsPart, VoicePart, SpacesPart, PeoplePart, FocusPart):
    """Действия панели поверх того же tmux и state.json, что у бота (окна, активное, голос)."""

    def __init__(self, cfg: Config):
        self.cfg, self.pult = cfg, Pult(cfg)
        # окна владельца и демо-пространств (spaces.py): запрос тестировщика ограничен его пространством (scope)
        self.pult.tmux = spaces.Routed(self.pult.tmux)
        self.tmux = self.pult.tmux
        self.auth = webauth.Auth(cfg.data / "web_sessions.json")
        self.tg_confirm = webauth.TgConfirm(self.auth)      # «✅ Подтвердить вход» в сообщении бота с кодом
        self.mcp = Mcp()
        self.openrouter = OpenRouter()
        self.people = People(cfg.data / "people.json", cfg.owners)
        self.team = personas.Team(cfg.data / "team.json")      # потолок возможностей сотрудников (экран «Команда»)
        self.logins = webauth.TgLogins(cfg.data / "tg_logins.json")
        self.email = emailcode.Service(cfg.email, self.people, cfg.data / "email_codes.json")   # вход по почте
        self.push = webpush.Hub(cfg.data / "push")              # уведомления на телефон (Web Push)
        self.keys = passkeys.Passkeys(cfg.passkeys, self.people, cfg.data / "passkeys.json")    # Face ID / ключ
        self.oidc = oidc.Oidc({"google": cfg.google, "yandex": cfg.yandex}, self.people, cfg.data / "oidc.json",
                              base=lambda: self.public_url)                                # Google, Яндекс ID
        self._bot = ""
        self._bot_name = ""
        self.confirm_pins: dict[str, list] = {}           # код подтверждения → закреплённые сообщения (снимаем)
        self.public_url = ""                                 # адрес панели снаружи — для возврата после входа
        self.previews: dict[str, tuple[str, str]] = {}  # папка → (ревизия журнала, строка превью)
        self.model_cache: dict[tuple, tuple[str, str]] = {}  # (папка, папка Claude) → (ревизия, модель ответа)
        self.mod_sections: tuple[float, dict] = (0.0, {})    # модуль → разделы чата (sections_of)
        self.mod_sched: tuple[float, dict] = (0.0, {})       # модуль → описание (schedule_of)
        self.sent: dict[str, tuple[threading.Event, float]] = {}     # id сообщения → (вставка, когда): без повторов
        self.stt_jobs: dict[str, dict] = {}              # фоновое распознавание (GAS-34): id → состояние
        self.recparts = recparts.Parts(cfg.data / "rec-parts")   # запись по кускам: не теряется при блокировке
        self.repeat = router.Repeat()
        self.start_q: list[dict] = []                    # новые сессии, ждущие памяти (mem_gate)
        self.lock_q, self.q_thread = threading.Lock(), None
        self.events = chatlog.Log(cfg.data / "chat-events.jsonl")   # путь сообщения по id (GAS-31, отладка)
        self.funnel = funnel.Funnel(cfg.data, cfg.events_keep_days)  # события продукта для воронки (funnel.py)
        self.wins: tuple[float, dict] = (0.0, {})                   # окна Claude для строки статуса (кэш 3 с)
        self.screens: dict[str, tuple[float, dict]] = {}             # окно → (когда, экран): не чаще раза в 2 с
        self.journal = self.pult.journal                             # вкладка «Команды»: все команды всех сессий
        self.login = self.pult.login                                 # вход в Claude Code (setup.py) — общий с ботом
        self._setup: tuple[float, dict] = (0, {})
        self.geo = country.GeoIP(cfg.data / "geoip")                 # страна по IP — локальная база db-ip lite
        self.ip_seen: dict[int, tuple[float, str]] = {}              # кого и когда сверяли по IP (только в памяти)
        self.offer_demos = offers.Demos()                            # демо-сессии страниц предложений (в памяти)
        self.offer_misses = offers.Misses()                          # перебор кодов предложений — по IP
        self.forms_links = onboarding.Links(cfg.data)                # анкеты клиентов по ссылке (решение 0010)
        self.q_misses = offers.Misses()                              # перебор кодов анкет — по IP
        self.ask_guard = apitokens.Guard()                           # «Попросить доступ» по фокус-ссылке — по IP
        self.ask_guard.LIMIT, self.ask_guard.WINDOW = 3, 600
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
        self.people.virtual = self.focus.person      # ссылка на пространство — «тестировщик» на срок ссылки (GAS-38)
        self.tasks = tasks.Tasks(cfg.data / "tasks.json")            # задачи владельца (#203)
        self.team_msgs = teammsg.TeamMsgs(cfg.data / teammsg.FILE)    # сообщения команды в чат (teammsg.py)
        self.bug_rate = teammsg.Rate(3, 60)                          # «Сообщить об ошибке»: 3 в минуту с устройства
        self.devices = bridge.Devices(cfg.data / "bridge_devices.json")   # мосты к браузеру пользователя
        self.hub = bridge.Hub(cfg.data / "bridge_log.jsonl")
        self.approvals = approvals.Approvals()                 # «Да» человека — только здесь, в памяти (штаб 22.11)
        self.hub.approve = lambda svc, pid, dg: self.approvals.take("", svc, pid, dg)   # мост — в этом процессе
        self.hub.private = self.devices.private          # «Личные данные не уходят модели» — флаг устройства
        self.shares = share.Store(cfg.data / "shares.json")                # «Поделиться» в Гаврилу (share.py)
        self.share_tokens = share.Tokens(cfg.data / "share_tokens.json")  # iPhone: токены «Быстрой команды»
        self.api_tokens = apitokens.Tokens(cfg.data / "api_tokens.json")   # 1С и CRM: /api/v1 (apitokens.py)
        self.api_log = apitokens.Log(cfg.data / "api-tokens-log.jsonl")     # журнал вызовов /api/v1
        self.api_guard = apitokens.Guard()                                  # подбор токена — 429
        self.uses = features.Uses(cfg.data / "features.json")        # какими функциями панели пользуются (отчёт)
        self.projects = projects.Store(cfg.data / projects.FILE, self.pult.home)   # «Проекты» (docs/PROJECTS.md)
        self._proj: tuple[float, dict] = (0.0, {})                  # (когда сверяли с папками, данные) — раз в 30 с
        self._trash_at = 0.0                                          # когда фоновый цикл чистил корзину чатов
        self._temp_at = 0.0                                           # когда фоновый цикл убирал остатки озвучки
        self.focus_gap: dict[str, float] = {}   # ссылка → с какого времени окна её сессии нет (перезапуск)
        self.demo_locks: dict[str, threading.Lock] = {}   # окно → замок ответа гостей демо-ссылки (первый проходит)
        self.demo_done: dict[str, float] = {}             # окно → когда гость демо-ссылки ответил на вопрос

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
        return w if w and harness.is_agent(w) else None

    TEMP_AGE = 3600                                     # с: остаток озвучки старше — мусор (озвучка идёт секунды)

    def temp_tick(self, now: float | None = None) -> list[Path]:
        """Из фонового цикла панели, не чаще раза в час: удалить остатки оборванной озвучки — ``*.tmp.wav`` и пустые
        ``*.mp3`` старше ``TEMP_AGE`` в папке данных и её подпапках первого уровня. ``inbox`` не трогаем (#217)."""
        now = time.time() if now is None else now
        if now - self._temp_at < self.TRASH_EVERY:
            return []
        self._temp_at = now
        gone = sweep_temp(self.cfg.data, now, self.TEMP_AGE)
        if gone:
            print(f"остатки озвучки: удалено {len(gone)} (старше {self.TEMP_AGE // 60} мин)", flush=True)
        return gone

    # ---------- протоколы встреч в панели (meetings.py, владелец 22.11) ----------
    def meeting_dir(self, mid: str) -> Path:
        return meetings.find(str(mid or ""), drive_inbox.drive_root(self.cfg.drive_root), self.cfg.data)

    def meeting_list(self) -> dict:
        return {"meetings": meetings.listing(drive_inbox.drive_root(self.cfg.drive_root), self.cfg.data)}

    def meeting_view(self, mid: str, public: bool = False) -> dict:
        """Протокол: оглавление, «Что сделать», текст. По публичной ссылке — без транскрипта черновика и ссылок."""
        v = meetings.view(self.meeting_dir(mid))
        if public:
            v.pop("transcript", None)
            return v
        v["links"] = [x for x in self.focus.listing() if x.get("mode") == focus.MEETING and x.get("mt") == mid]
        return v

    def meeting_card(self, mid: str) -> tuple:
        """Карточка-превью (SVG 1200×630): главная мысль, дата, длительность, знак Гаврилы."""
        try:
            mark = resources.files("gas_pult").joinpath("web/brand/gavrila-mark.svg").read_text(encoding="utf-8")
        except OSError:
            mark = ""
        v = meetings.view(self.meeting_dir(mid), full=False)
        return ("image/svg+xml; charset=utf-8", meetings.card_svg(v, mark).encode(), {"Cache-Control": "no-store"})

    def meeting_audio(self, mid: str) -> tuple:
        ctype, data = meetings.audio(self.meeting_dir(mid))
        return (ctype, data, {"Cache-Control": "private, max-age=3600"})

    def meeting_share(self, mid: str, by, base: str) -> dict:
        """«Ссылка на протокол» (владелец): ``…/#focus=<токен>`` — только этот протокол, 30 дней, отзыв — в
        «Фокус-ссылках». Токен показывается один раз."""
        v = meetings.view(self.meeting_dir(mid), full=False)
        base = (self.public_url or base or "").rstrip("/")
        if not self.FOCUS_BASE.match(base):
            raise ValueError("не знаю адрес панели снаружи — откройте панель по её адресу и повторите")
        f = self.focus.new({"id": "", "path": "", "name": v["title"]}, by, ttl=focus.MEETING_TTL, mode=focus.MEETING,
                           mt=v["id"])
        return {"url": f"{base}/#focus={f['token']}", "id": f["id"], "exp": f["exp"], "name": v["title"],
                "mode": focus.MEETING, "max": focus.MEETING_MAX}

    def meeting_public(self, rec: dict, path: str) -> dict | tuple:
        """Запрос по ссылке на протокол: протокол — только из записи ссылки (``mt``), путь — из ``MEETING_GET``."""
        mid = str(rec.get("mt") or "")
        if path == "/api/mt":
            return {**self.meeting_view(mid, public=True), "exp": rec.get("exp")}
        if path == "/api/mt/audio":
            return self.meeting_audio(mid)
        if path == "/api/mt/card":
            return self.meeting_card(mid)
        raise focus.Denied("по ссылке на протокол — только этот протокол")

    def focus_meta(self, rec: dict) -> dict:
        """«meta» для фокуса: только то, что нужно одной сессии и её настройкам — без папок и имени сервера.
        Демо-ссылка: без команд, моделей, поставщиков и клавиш — только смотреть и выбирать вариант."""
        voices = catalog.installed(self.personal(rec.get("by")))
        if focus.Focus.is_demo(rec):
            return {"host": rec.get("name", ""), "tz": server_tz(), "projects": [], "commands": [], "models": [],
                    "profiles": [], "keys": [], "voices": [{"id": v, "label": catalog.label(v)} for v in voices],
                    "voice": self.voice(voices),
                    "focus": {"id": rec["id"], "name": rec.get("name", ""), "w": rec["w"], "space": rec.get("space"),
                              "exp": rec.get("exp"), "proj": rec.get("proj"), "mode": focus.DEMO}}
        return {"host": rec.get("name", ""), "tz": server_tz(), "projects": [],
                "commands": [t for t, _ in self.pult.command_list()],                  # команды Claude этой сессии
                "models": [] if rec.get("space") else self.cfg.models,                 # модель и поставщик этого чата
                "profiles": [] if rec.get("space") else models.public(self.pult.state(), self.countries(rec.get("by"))),
                "keys": [{"label": t, "key": k} for t, k in KEYS + PANEL_KEYS],
                "voices": [{"id": v, "label": catalog.label(v)} for v in voices], "voice": self.voice(voices),
                "focus": {"id": rec["id"], "name": rec.get("name", ""), "w": rec["w"], "space": rec.get("space"),
                          "exp": rec.get("exp"), "proj": rec.get("proj"),     # proj — ссылка на проект (добавлено)
                          "browser": bool(rec.get("browser"))}}            # можно подключить свой браузер

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

    def notify_info(self, uid) -> dict:
        """Уведомления, часть B (notifyroute.py): каналы и события человека. Каналы и события — у владельцев: бот
        шлёт уведомления им; остальным — только устройства (Web Push)."""
        rec = notifyroute.Store(self.cfg.data / "notify_channels.json").get(uid)
        mail = self.people.email(uid)
        return {"owner": self.is_owner(uid), "push": rec["push"], "telegram": rec["telegram"],
                "devices": len(self.push.devices(uid)),
                "email": {"can": self.email.enabled, "addr": bool(mail.get("address")),
                          "on": bool(mail.get("notify") and mail.get("address"))},
                "events": [{"id": k, "label": v, "on": rec["events"][k], "email": k not in notifyroute.NO_EMAIL}
                           for k, v in notifyroute.EVENTS.items()]}

    def notify_set(self, uid, b: dict) -> dict:
        if not self.is_owner(uid):
            raise focus.Denied("каналы и события — у владельца пульта", "owner")   # 403
        patch = {k: b[k] for k in ("push", "telegram", "events") if k in b}
        if patch:
            notifyroute.Store(self.cfg.data / "notify_channels.json").set(uid, patch)
        if "email" in b:
            if not isinstance(b["email"], bool):
                raise ValueError("email: да или нет")
            self.email.options(uid, None, b["email"])
        return self.notify_info(uid)
    def feedback_add(self, who: tuple, b: dict) -> dict:
        """Отзыв из панели: файл в ``feedback/``, задача владельцу (её видит штаб), сообщение бота владельцам."""
        via, _, uid = who
        if via == "focus":
            raise ValueError("отзыв — после входа в панель")
        p = next((x for x in self.people.list() if x["id"] == uid), {}) if uid is not None else {}
        own = self.is_owner(uid) or uid == webauth.LEGACY
        name = "владелец" if own else p.get("name") or f"@{p.get('username', '')}"
        rec = feedback.save(self.cfg.data, uid, name, str(b.get("text") or ""), str(b.get("screen") or ""),
                            str(b.get("shot") or ""))
        t = self.tasks.add(feedback.task(rec), by="feedback")
        if not own:                                       # свой отзыв владельцу не пересылаем
            with contextlib.suppress(Exception):
                self.pult.broadcast(f"💬 Отзыв ({name}, экран {rec['screen'] or '—'}): {rec['text'][:600]}"
                                    + (" · есть снимок" if rec["shot"] else ""))
        return {"ok": True, "task": t.get("id")}

    def team_for(self, w: dict) -> list[dict]:
        """Сообщения команды для чата окна ``w`` — его и его проекта (``teammsg.for_window``); сбой — пусто."""
        try:
            proj = self.project_of(self.project_data(), w)
        except Exception:
            proj = ""
        try:
            return self.team_msgs.for_window(w, proj)
        except (OSError, ValueError):
            return []

    def team_say(self, b: dict) -> dict:
        """«Команда» пишет в чат окна или проекта (владелец; штаб — ``gas-pult chat say``). В tmux ничего не уходит."""
        wid, proj = str(b.get("w") or ""), str(b.get("proj") or "")
        kind = str(b.get("kind") or "info")
        if wid:
            w = self.tmux.window(wid)
            if not w:
                raise LookupError("окна уже нет")
            to = teammsg.target(w=wid, sid=w.get("sid") or "")
        else:
            if proj not in self.project_data()["projects"]:
                raise LookupError("проекта нет")
            to = teammsg.target(proj=proj)
        return {"ok": True, "msg": teammsg.public(self.team_msgs.say(to, str(b.get("text") or ""), kind))}

    def bug_report(self, who: tuple, w: dict, b: dict, ua: str, focus_rec: dict | None = None) -> dict:
        """«Сообщить об ошибке» из чата: отчёт в ``bugs/``, задача владельцу и штабу, уведомление владельцу, человеку
        в его чат — «Приняли». Не чаще ``bug_rate`` с устройства; окно уже проверено (своё, пространства, ссылки)."""
        via, _, uid = who
        dev, br = webauth.device_parts(ua)
        key = f"f:{focus_rec['id']}" if focus_rec else f"u:{uid}"
        if not self.bug_rate.hit(f"{key}:{hashlib.sha256((ua or '').encode()).hexdigest()[:12]}"):
            raise ValueError("слишком часто — подождите минуту и отправьте ещё раз")
        if focus_rec:
            name = f"фокус-ссылка «{focus_rec.get('name') or ''}»"
        else:
            p = next((x for x in self.people.list() if x["id"] == uid), {}) if uid is not None else {}
            own = self.is_owner(uid) or uid == webauth.LEGACY
            name = "владелец" if own else p.get("name") or f"@{p.get('username', '')}"
        space = w.get("space") or ""
        to = teammsg.target(w=w["id"], sid=w.get("sid") or "", space=space)
        try:
            proj = self.project_of(self.project_data(), w)
        except Exception:
            proj = ""
        title = ""
        with contextlib.suppress(Exception):
            title = self.chat_title(self.project_data(), w["path"], self.pult.home_of(w), w.get("sid") or "",
                                    harness.of(w)) or w.get("name", "")
        rec = teammsg.bug_save(self.cfg.data, str(b.get("text") or ""), device=dev, browser=br, who=name, to=to,
                               proj=proj, chat_title=title or w.get("name", ""), ctx=b.get("ctx"),
                               shot=str(b.get("shot") or ""))
        t = teammsg.bug_task(rec, to)
        if space:                                          # окно пространства — не окно владельца: без перехода в чат
            t.update(chat="", sid="")
        t = self.tasks.add(t, by="bug")
        with contextlib.suppress(Exception):
            self.pult.broadcast(f"Сообщили об ошибке ({name}; {dev or '—'}, {br or '—'}; чат «{rec['chat_title']}»"
                                f"{', пространство ' + space if space else ''}): {rec['text'][:600]}")
        ack = self.team_msgs.say(to, teammsg.ACK, "ack", t["id"])
        self.events.event("bug", t["id"], w=w["id"], space=space, dev=f"{dev} · {br}".strip(" ·"), via=via,
                          n=len(rec["text"]))
        return {"ok": True, "task": t["id"], "ack": teammsg.public(ack)}

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
                "agents": harness.available(),           # другие агенты для нового окна (R13): Pi
                "projects": [self.pult.short(p) for p in self.pult.projects()],
                "voices": [{"id": v, "label": catalog.label(v)} for v in voices],
                "voice": self.voice(voices)}

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
        role = "member" if role == "admin" else role     # у помощника экраны админа — как у участника
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

    def key(self, w: dict, key: str) -> list[str]:
        if key not in {k for _, k in KEYS + PANEL_KEYS} and not re.fullmatch(r"[1-9]", key):   # цифры — пункты
            raise ValueError("неизвестная клавиша")
        self.tmux.keys(w["id"], key)
        time.sleep(1)
        return self.tmux.screen(w["id"], 40)

    # ---------- «Поделиться» в Гаврилу (share.py) ----------
    def share_receive(self, uid: int, f: BinaryIO, ctype: str, n: int, via: str) -> dict:
        """Тело «поделились» → запись человека ``uid``. multipart — файлы потоком в inbox (``upload``), поля —
        title/text/url; JSON и urlencoded — только текст и ссылка (iPhone «Быстрая команда»)."""
        if n > MAX_BODY:
            raise ValueError("больше 50 МБ")
        kind = (ctype or "").split(";")[0].strip().lower()
        if kind != "multipart/form-data":
            raw = f.read(min(n, share.MAX_FIELD * 4)) if n else b""
            if kind == "application/json":
                b = json.loads(raw or b"{}")
                b = b if isinstance(b, dict) else {}
            else:                                         # application/x-www-form-urlencoded и прочее текстовое
                b = dict(urllib.parse.parse_qsl(raw.decode("utf-8", "replace")))
            return self.shares.add(uid, b.get("title", ""), b.get("text", ""), b.get("url", ""), via=via)
        saved: list[dict] = []

        def on_file(_field, name, typ, body):
            p = Path(self.upload(name, body))
            size = p.stat().st_size
            if not size:
                p.unlink(missing_ok=True)
                return None
            shown = re.sub(r"[\x00-\x1f/\\]+", "_", os.path.basename(name.replace("\\", "/")))[-80:] or p.name
            rec = {"name": shown, "path": str(p), "size": size, "type": typ.split(";")[0].strip()[:80]}
            saved.append(rec)
            return rec
        try:
            fields, files = share.Multipart(f, ctype, n).parse(on_file)
            return self.shares.add(uid, fields.get("title", ""), fields.get("text", ""), fields.get("url", ""),
                                   files, via=via)
        except Exception:
            for x in saved:                               # запись не создана — недописанные файлы не копим
                Path(x["path"]).unlink(missing_ok=True)
            raise

    def share_notify(self, uid: int, rec: dict):
        """iPhone: «Поделились: … — откройте Гаврилу» в бот самому человеку (не другим). Сбой Telegram — не ошибка."""
        what = rec.get("title") or rec.get("url") or rec.get("text") or ", ".join(x["name"] for x in rec["files"])
        what = " ".join(str(what).split())[:120]
        base = (self.public_url or "").rstrip("/")
        text = f"Поделились: {what} — откройте Гаврилу" + (f"\n{base}/?share={rec['id']}" if base else "")

        def go():
            try:
                self.pult.api("sendMessage", chat_id=int(uid), text=text,
                              link_preview_options={"is_disabled": True})
            except (TelegramError, OSError, ValueError) as e:
                print("share:", e, file=sys.stderr, flush=True)
        threading.Thread(target=go, daemon=True).start()

    def share_list(self, uid) -> dict:
        out = []
        for r in self.shares.mine(uid):
            out.append({**{k: r[k] for k in ("id", "at", "title", "text", "url", "via")},
                        "files": [{"name": x["name"], "path": x["path"], "size": x["size"],
                                   "image": x.get("type", "").startswith("image/")} for x in r["files"]]})
        return {"items": out}

    def share_file(self, uid, sid: str, i: str) -> tuple:
        """Миниатюра своей записи: только картинка из её файлов, до 25 МБ."""
        rec = self.shares.get(uid, sid)
        try:
            x = rec["files"][int(i)]
        except (ValueError, IndexError):
            raise LookupError("файл не найден") from None
        ctype = x.get("type", "")
        if not re.fullmatch(r"image/(jpeg|png|gif|webp|heic|heif)", ctype):
            raise ValueError("это не картинка")
        try:
            if os.stat(x["path"]).st_size > self.MEDIA_MAX:
                raise ValueError("картинка больше 25 МБ")
            data = Path(x["path"]).read_bytes()
        except OSError:
            raise LookupError("файл не найден") from None
        return (ctype, data, {"Cache-Control": "private, max-age=3600"})

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

    def openrouter_done(self, code: str, state: str):
        """Возврат из OpenRouter после «Authorize»: код → ключ → secrets.json (как ключ, вставленный вручную)."""
        providers.save_key("openrouter", self.openrouter.finish(code, state))

    def openrouter_info(self) -> dict:
        key = providers.load_keys().get("openrouter")
        return {"key": False} if not key else {"key": True, **self.openrouter.info(key)}

    def set_models(self, profile: str, main: str, fast: str, base_url: str | None = None):
        """``base_url`` — адрес шлюза клиента (GigaChat, YandexGPT); ``None`` — не менять."""
        self.pult.set_state(model_profiles=models.set_models(self.pult.state(), profile, main, fast, base_url))

    def fallback_info(self, uid=None) -> dict:
        """Запасные для панели: цепочка поставщиков, страны, кто годится, последние переключения, голос (#53)."""
        cs = None if uid is None else self.countries(uid)
        return {**fallback.public(self.pult.state(), self.cfg.region, countries=cs), "voice_note": self.fallback_note()}

    def set_fallback(self, chain, uid=None) -> dict:
        cs = self.cfg.region if uid is None else self.countries(uid)
        self.pult.set_state(fallback_chain=fallback.validate(chain, cs))
        return self.fallback_info(uid)


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


# Сервис-воркер: только клик по уведомлению — открыть панель на нужной сессии. Ни кэша, ни фоновых запросов.
SW_JS = """self.addEventListener("push", (e) => {   // сигнал без содержимого — текст забираем с сервера по куке
  e.waitUntil(self.registration.pushManager.getSubscription().then(async (sub) => {
    const ep = sub ? sub.endpoint : "", h = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(ep));
    const dev = [...new Uint8Array(h)].slice(0, 8).map((b) => b.toString(16).padStart(2, "0")).join("");
    const r = await fetch("/api/push/last?dev=" + dev, { credentials: "include" });
    const items = r.ok ? (await r.json()).items || [] : [];
    if (!items.length) return self.registration.showNotification("Гаврила", { body: "Есть новое — откройте" });
    for (const x of items) {
      await self.registration.showNotification(x.title, { body: x.body, tag: x.w || x.id, data: { id: x.w } });
    }
  }));
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const id = e.notification.data && e.notification.data.id;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((cs) => {
    if (cs[0]) { cs[0].focus(); cs[0].postMessage({ open: id }); return null; }
    return self.clients.openWindow("/");
  }));
});
// «Поделиться» (Android, share_target): форму пересылаем сами — запрос со страницы своего адреса несёт куку входа
// (SameSite=Strict); остальные запросы service worker не трогает
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "POST" || u.origin !== self.location.origin || u.pathname !== "/share") return;
  e.respondWith((async () => {
    try {
      const r = await fetch("/share", { method: "POST", credentials: "same-origin", body: await e.request.blob(),
        headers: { "Content-Type": e.request.headers.get("Content-Type") || "", "X-GP-SW": "1" } });
      return Response.redirect((await r.json()).go || "/?share=error", 303);
    } catch (_) { return Response.redirect("/?share=error", 303); }
  })());
});
"""

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


ORIGIN_OK = re.compile(r"[A-Za-z0-9.-]{1,100}(:\d{1,5})?")      # адрес панели для og:image (page_for)


def handler(panel: Panel):
    page = resources.files("gas_pult").joinpath("web/index.html").read_bytes()
    if brand.NAME_RU != brand.DEFAULT:                      # название продукта — одно место: brand.py
        page = page.replace(brand.DEFAULT.encode(), brand.NAME_RU.encode())
    # превью ссылки и экраны запуска (brand.head_tags) — вставляются в <head> при старте; полный адрес — из запроса
    tags = brand.head_tags().replace(brand.DEFAULT, brand.NAME_RU).encode()
    page = page.replace(b'<link rel="manifest"', tags + b'\n<link rel="manifest"', 1)
    manifest = json.dumps(brand.manifest(), ensure_ascii=False).encode()
    manifest_focus = json.dumps(brand.manifest(focus=True), ensure_ascii=False).encode()
    # части интерфейса по требованию (#191): web/js/<имя>.js — нативные ES-модули без сборки; читаются и сжимаются
    # один раз при старте, отдаются с ETag (после выкладки браузер получит новую версию, иначе — 304 без тела)
    parts = {}
    js_dir = resources.files("gas_pult").joinpath("web/js")
    for f in (js_dir.iterdir() if js_dir.is_dir() else []):
        if f.name.endswith(".js") and PART_NAME.fullmatch(f.name[:-3]):
            body = f.read_bytes()
            parts[f.name[:-3]] = (body, gzip.compress(body, 9), '"' + hashlib.sha256(body).hexdigest()[:12] + '"')
    # версия страницы вместе с частями: изменилось что-то одно — панель предложит обновиться
    build = hashlib.sha256(page + b"".join(parts[k][0] for k in sorted(parts))).hexdigest()[:12]
    origin_pages: dict[str, tuple[bytes, bytes]] = {}   # адрес панели → страница с полным адресом превью (og:image)
    page_plain = page.replace(b"__ORIGIN__", b"")        # неизвестный адрес — ссылки от корня
    page_gz = gzip.compress(page_plain, 9)               # страница сжимается один раз при старте (887 → ~200 КБ)

    def page_for(host: str) -> tuple[bytes, bytes]:
        """Страница для адреса из запроса: ``og:image`` — полным адресом (так просят Telegram и iMessage). Адрес —
        только буквы, цифры, точки, дефисы и порт; адресов немного (кэш до 8), остальные — без полного адреса."""
        if not ORIGIN_OK.fullmatch(host or ""):
            return page_plain, page_gz
        if host not in origin_pages and len(origin_pages) < 8:
            body = page.replace(b"__ORIGIN__", f"https://{host}".encode())
            origin_pages[host] = (body, gzip.compress(body, 9))
        return origin_pages.get(host) or (page_plain, page_gz)
    whatsnew = json.loads(resources.files("gas_pult").joinpath("web/whatsnew.json").read_text(encoding="utf-8"))
    offer_page = resources.files("gas_pult").joinpath("web/offer.html").read_bytes()
    q_page = resources.files("gas_pult").joinpath("web/q.html").read_bytes()     # анкета клиента (0010)
    terms_page = resources.files("gas_pult").joinpath("web/terms.html").read_bytes()   # /terms — без входа (17.11)
    help_map = resources.files("gas_pult").joinpath("web/help-map.json").read_bytes()   # карта для демо панели
    icons = {u: (resources.files("gas_pult").joinpath(brand.FILES_DIR + f).read_bytes(), t)   # знак K3 (20.11)
             for u, (f, t) in brand.ICONS.items()}
    i18n = {f"/i18n/{x}.json": resources.files("gas_pult").joinpath(f"web/i18n/{x}.json").read_bytes()
            for x in ("ru", "en")}                       # словари простого режима и первого экрана — и до входа
    scripts = re.findall(rb"<script>(.*?)</script>", offer_page, re.S)
    hashes = " ".join("'sha256-" + base64.b64encode(hashlib.sha256(x).digest()).decode() + "'" for x in scripts)
    offer_csp = (f"default-src 'none'; script-src {hashes}; style-src 'unsafe-inline'; img-src 'self' data:; "
                 "connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'")
    q_hashes = " ".join("'sha256-" + base64.b64encode(hashlib.sha256(x).digest()).decode() + "'"
                        for x in re.findall(rb"<script>(.*?)</script>", q_page, re.S))
    q_csp = offer_csp.replace(f"script-src {hashes}", f"script-src {q_hashes}")

    class H(BaseHTTPRequestHandler):
        focused: dict | None = None             # запрос из фокуса: ссылка (focus.py), уже проверенная
        raw: bytes | None = None                # тело, прочитанное проверкой фокуса

        renew = ""                              # Set-Cookie продлённой или новой сессии — уйдёт с ответом
        sl: tuple | None = None                 # (запись ссылки на пространство | None, почему погасла) — на запрос
        apitok: dict | None = None              # запрос /api/v1 по токену (apitokens.py): {"uid", "role"}, проверен
        sent_code = 0                           # код последнего ответа — для журнала /api/v1

        def log_message(self, fmt, *args):     # без логов запросов: в них initData
            pass

        def parse_request(self) -> bool:
            self.renew = ""                     # соединение keep-alive: у каждого запроса своё
            self.sl = None                      # ссылка на пространство — проверяется заново на каждый запрос
            self.apitok = None                  # токен /api/v1 — тоже на каждый запрос
            self.sent_code = 0                  # ответа ещё нет: упадёт обработчик — можно ответить 500 (crash)
            return super().parse_request()

        def handle_one_request(self):
            try:
                super().handle_one_request()
            except (ConnectionError, TimeoutError):      # человек ушёл, не дождавшись ответа — не сбой
                raise
            except Exception as e:                       # упало мимо dispatch: 500 JSON, а не обрыв (502 у Caddy)
                self.crash(e)
                self.close_connection = True

        def crash(self, e: Exception):
            """Необработанное исключение: трассировка — в журнал службы, событие ``server_error`` (путь без query,
            класс, id) — сводкой владельцу (alerts.py), человеку — 500 JSON с тем же id."""
            eid = secrets.token_hex(4)
            path = urllib.parse.urlparse(getattr(self, "path", "") or "").path
            print(f"server_error {eid} {path}:", file=sys.stderr, flush=True)
            traceback.print_exception(e, file=sys.stderr)
            panel.events.event("server_error", path=path[:120], exc=type(e).__name__, id=eid)
            if not self.sent_code:                       # заголовки ещё не ушли — ответ ещё можно дать
                try:
                    self.json({"error": "внутренняя ошибка", "code": "server_error", "id": eid}, 500)
                except OSError:
                    pass

        def send_response(self, code, message=None):
            self.sent_code = code               # журнал /api/v1 пишет код ответа
            super().send_response(code, message)

        def reply(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8", cookie: str = "",
                  headers: dict | None = None, packed: bytes | None = None, etag: str = ""):
            """``packed`` — уже сжатое тело (страница сжимается один раз); ``etag`` — версия: совпала — 304 без тела."""
            if etag and code == 200 and self.headers.get("If-None-Match", "") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                return
            gz = gzips(self.headers.get("Accept-Encoding", ""), ctype, body)
            if gz:                                       # #191: страница 887 КБ и опрос раз в 3 с — сжатием в 4–7 раз
                body = packed or gzip.compress(body, GZIP_LEVEL)
            self.send_response(code)
            if code < 500:                               # отметка жизни панели — не чаще раза в минуту
                alerts.beat(panel.cfg.data, "web")
            if cookie or self.renew:
                self.send_header("Set-Cookie", cookie or self.renew)
            self.renew = ""
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            if gz:
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Vary", "Accept-Encoding")
            if etag:                                     # страница: проверять версию, тело — только если сменилась
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "no-cache")
            else:
                self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def json(self, data, code: int = 200):
            self.reply(code, json.dumps(data, ensure_ascii=False).encode())

        def push_uid(self) -> int:
            """Чьи подписки: Telegram ID вошедшего; фокус-ссылке и входу без ID уведомлений нет."""
            via, _, uid = self.who()
            if via in ("focus", SLINK) or uid is None:
                raise ValueError("уведомления на телефон — после входа через Telegram, Google, Яндекс или ключ")
            return uid

        def who(self) -> tuple[str, str | None, int | None]:
            """(откуда: «telegram» / «browser» / "", роль, Telegram ID). Роль — на каждый запрос, из people.json.
            Запрос из фокуса — права того, кто выпустил ссылку, но только в пределах ``FOCUS_*`` и одного окна."""
            if self.apitok is not None:                   # /api/v1: права выпустившего токен, проверены v1_call
                return "apitoken", self.apitok["role"], self.apitok["uid"]
            if self.focused is not None:
                return "focus", "owner", self.focused.get("by")
            if self.headers.get(SLINK_HEADER):            # страница ссылки на пространство — только её cookie
                return self.slink_who()
            got = self.login_who()
            return got if got[1] else self.slink_who()

        def slink(self) -> tuple[dict | None, str]:
            """Ссылка на пространство этого устройства (focus.SPACE): (запись | None, почему не действует)."""
            if self.sl is None:
                try:
                    self.sl = (panel.focus.space_by_cookie(self.focus_cookie()), "")
                except focus.Gone as e:
                    self.sl = (None, str(e))
            return self.sl

        def slink_who(self) -> tuple[str, str | None, int | None]:
            """Вход по ссылке на пространство: «человек» ссылки (focus.vuid), роль и пространство — People.virtual."""
            rec = self.slink()[0]
            if not rec:
                return "", None, None
            uid = focus.vuid(rec["id"])
            role = panel.people.role(uid)
            return (SLINK, role, uid) if role else ("", None, None)

        def login_who(self) -> tuple[str, str | None, int | None]:
            user = verify(self.headers.get("X-Telegram-Init-Data", ""), panel.cfg.token)
            if user and (role := panel.people.role(user.get("id"))):
                self.tg_cookie(int(user["id"]))
                return "telegram", role, int(user["id"])
            uid = panel.auth.uid(self.session())
            if uid is None:
                return "", None, None
            if panel.auth.touch(self.session()):          # скользящий срок: заходит — вход не кончается
                self.renew = webauth.set_cookie(self.session())
            role = "owner" if uid == webauth.LEGACY else panel.people.role(uid)
            return ("browser", role, uid) if role else ("", None, None)

        def desktop_gate(self):
            """Рабочий стол агентов (noVNC за Caddy, #206) — полное управление браузером со входами: пускаем только
            владельца — по cookie входа панели или по пропуску из кнопки «Рабочий стол» (``DESK_COOKIE``). Фокус-ссылки,
            пространства, участники, наблюдатели, демо — нет. Свежему входу — сперва код подтверждения, как для команд
            на сервере (``CONFIRM``). 204 — можно; 401 — нет входа; 403 — не владелец или нужен код."""
            tok = self.session()
            uid = panel.auth.uid(tok)
            fresh = True
            got = next((v for k, _, v in (c.strip().partition("=") for c in self.headers.get("Cookie", "").split(";"))
                        if k == DESK_COOKIE), "")
            ps = DESK_PASSES.get(got) if got else None
            if ps and ps[1] > time.time():                # пропуск из «Рабочий стол» (код уже подтверждён)
                uid, fresh = ps[0], False
            if uid is None:
                return self.json({"error": "нужен вход"}, 401)
            role = "owner" if uid == webauth.LEGACY else panel.people.role(uid)
            if role != "owner" or panel.people.tenant(uid):
                return self.json({"error": "рабочий стол — только владельцу"}, 403)
            if fresh and panel.auth.needs_confirm(tok):
                return self.json({"error": "новый вход: подтвердите кодом в панели", "code": "confirm"}, 403)
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return None

        def via(self) -> str:
            return self.who()[0]

        def tg_cookie(self, uid: int):
            """Mini App: подпись Telegram (``initData``) действует сутки (``MAX_AGE``), а окно Mini App живёт дольше —
            и через сутки панель просила войти. При загрузке (``/api/meta``) с верной подписью выдаём и cookie той же
            сессии на 30 дней: подпись устареет — запросы пройдут по cookie. Cookie уже есть — только продлеваем."""
            tok = self.session()
            if panel.auth.uid(tok) == uid:
                if panel.auth.touch(tok):
                    self.renew = webauth.set_cookie(tok)
                return
            if urllib.parse.urlsplit(self.path).path != "/api/meta" or self.renew:
                return
            seen = panel.__dict__.setdefault("_tg_issued", {})     # cookie не вернулся (iframe web.telegram.org) —
            now = time.time()                                       # не плодим сессии: одна на человека за 10 минут
            if now - seen.get(uid, 0) < 600:
                return
            seen[uid] = now
            self.renew = webauth.set_cookie(panel.auth.issue(uid, self.client()[1]))
            self.product("login", uid, "miniapp")

        def person(self) -> int | None:
            """Telegram ID вошедшего, если это не владелец: его окна и интеграции — в его папке Claude Code."""
            _, role, uid = self.who()
            return None if role == "owner" or uid is None else uid

        def pinner(self) -> str:
            """Чьи закрепления: владелец (и фокус-ссылка — права выпустившего её владельца) — «owner», остальные —
            свой Telegram ID."""
            uid = self.person()
            return "owner" if uid is None else str(uid)

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

        def same_origin(self) -> None:
            """«Да» — только со страницы панели: чужой сайт с нашей cookie не пройдёт (cookie и так SameSite=Strict)."""
            origin = self.headers.get("Origin", "")
            if origin and urllib.parse.urlparse(origin).netloc != self.headers.get("Host", ""):
                raise ValueError("запрос не со страницы панели")

        def drafts_check(self):
            """Коннектор спрашивает перед выполнением: человек нажал «Да» ровно на этот черновик? Одноразово.
            Кто спрашивает — по секрету: владелец — ``bridge-local.token``, пространство — токен его моста.
            Этот путь «Да» не даёт — только забирает данное человеком в панели."""
            space = panel.bridge_space(self.headers.get("X-GP-Space-Token", ""))
            if not space and not secrets.compare_digest(self.headers.get("X-GP-Local", ""),
                                                        bridge_local_token(panel.cfg.data)):
                self.json({"error": "нет доступа"}, 403)
                return SENT
            b = json.loads(self.body() or b"{}")
            svc, pid, dg = str(b.get("svc", "")), str(b.get("id", "")), str(b.get("digest", ""))
            ok = drafts.SVC.match(svc) and drafts.ID.match(pid) and panel.approvals.take(space or "", svc, pid, dg)
            panel.events.event("draft_check", "", svc=svc[:24], ok=bool(ok))
            return {"ok": bool(ok)}

        def drafts_scope(self) -> str | None:
            """Чьи черновики коннекторов: человека пространства — его пространства; владельца — его; остальным — нет."""
            if slug := self.space():
                return slug
            if self.who()[1] != "owner":
                raise ValueError("черновики действий подтверждает тот, чей это коннектор")
            return None

        def space_of(self, b: dict) -> str:
            """Чьё пространство: тестировщика — его; владельцу — из запроса (``space``); остальным — отказ."""
            if slug := self.space():
                return slug
            if self.who()[1] in ("owner", "admin") and b.get("space"):     # админ — помогает в пространствах
                return tenants.check_slug(str(b["space"]))
            raise ValueError("это действие — для сессий демо-пространства")

        def sp(self, pid) -> tuple[bool, str | None]:
            """Проект пространства (GAS-38)? → (да/нет, чьё пространство можно). Тестировщику — любой id идёт в его
            пространство (проект владельца и чужое пространство — «проекта нет»); владельцу и админу — любое
            пространство (None); остальным id пространства — «проекта нет»."""
            if slug := self.space():
                return True, slug
            if space_projects.is_space(pid):
                if self.who()[1] in ("owner", "admin"):
                    return True, None
                raise LookupError(space_projects.NOT_FOUND)
            return False, None

        def space_win(self, q: dict) -> tuple[str, dict]:
            """Окно пространства из запроса (``w``): тестировщику — только своё; владельцу — любое пространство."""
            w = panel.tmux.window(str(q.get("w") or ""))
            slug = self.space()
            if not slug and self.who()[1] in ("owner", "admin"):
                slug = (w or {}).get("space")
            if not w or not slug or w.get("space") != slug:
                raise LookupError("окна уже нет")
            return slug, w

        def product(self, ev: str, uid=None, via: str = "", sp: str | None = None):
            """Событие продукта (funnel.py): login / send / first_reply / yes / no. Человек — вошедший
            (вход кодом владельцу — первый владелец), пространство — его. Ошибка аналитики запрос не ломает."""
            try:
                if uid is None and self.focused is not None:   # фокус-ссылка: человек не известен (права — автора)
                    return
                uid = self.terms_uid() if uid is None else uid
                if uid == webauth.LEGACY:
                    uid = (panel.cfg.owners or [None])[0]
                if uid is None:
                    return
                sp = (panel.people.tenant(uid) or "") if sp is None else sp
                if ev == "send":
                    panel.funnel.send(uid, sp, via)
                elif ev == "first_reply":
                    panel.funnel.replied(uid, sp, via)
                else:
                    panel.funnel.event(ev, uid, sp, via)
            except Exception as e:  # аналитика не ломает работу панели
                print("funnel:", e, flush=True)

        def product_seen(self, items: list[dict]):
            """Переписка показана человеку: первый ответ агента после его сообщения — ``first_reply`` (один раз)."""
            try:
                uid = None if self.focused is not None else self.terms_uid()
                if uid is not None and panel.funnel.sent_at(uid) is not None:
                    panel.funnel.answered(uid, items, panel.people.tenant(uid) or "")
            except Exception as e:
                print("funnel:", e, flush=True)

        def product_pick(self, w: dict, n: str = "", key: str = ""):
            """Ответ на вопрос агента в чате (пункт меню или клавиша): «Да» / «Нет» — событием продукта. Экран читаем
            до нажатия, ошибка — без события. Стрелки и «выделить» — не ответ: экран не читаем."""
            if not n and key not in ("Enter", "Escape"):
                return
            try:
                yn = funnel.choice(humanize.parse(panel.tmux.screen(w["id"], 60)), n=n, key=key)
            except Exception:
                return
            if yn:
                self.product(yn, via="chat")

        def terms_uid(self) -> int | None:
            """Чьё согласие с условиями проверять. Вход кодом владельцу (LEGACY) — первого владельца."""
            uid = self.who()[2]
            return (panel.cfg.owners or [None])[0] if uid == webauth.LEGACY else uid

        def permit(self, path: str, method: str) -> bool:
            """Не вошёл — 401 (панель покажет вход); не принял условия — 403 code=terms; не хватает роли — 403."""
            role = self.who()[1]
            if not role and (self.headers.get(SLINK_HEADER) or self.focus_cookie()):
                why = self.slink()[1]                    # ссылка на пространство погасла — экран «Ссылка не действует»
                if why or self.headers.get(SLINK_HEADER):
                    self.json({"error": why or "Ссылка не открыта на этом устройстве. Откройте ссылку ещё раз.",
                               "code": "focus_gone"}, 410)
                    return False
            if not role and self.focus_cookie():          # с фокус-ссылкой — только её сессия, остальное закрыто
                self.json({"error": "по фокус-ссылке доступна только её сессия", "code": "focus_scope"}, 403)
                return False
            if not role:
                self.json({"error": "нужен вход"}, 401)
                return False
            uid = self.terms_uid()
            if self.via() == SLINK and path in SLINK_NO:  # вход на другое устройство, ключи, уведомления — не по ссылке
                self.json({"error": "по ссылке на пространство этого нет", "code": "focus_scope"}, 403)
                return False
            if self.via() != SLINK:                       # у ссылки нет страны человека
                panel.seen_ip(uid, self.client_ip())       # страна по IP — не чаще раза в IP_EVERY
            if path not in TERMS_FREE and not panel.people.accepted(uid) and not self.terms_line(method, uid):
                self.json({"error": "сначала примите условия использования пульта", "code": "terms"}, 403)
                return False
            # выбор страны не спрашиваем (решение владельца 20.11, country.check_set) — без шага «страна»
            if self.space() and path not in SPACE_OK:     # тестировщик — только своё пространство
                self.json({"error": "в демо-пространстве этого нет", "code": "space"}, 403)
                return False
            if method == "POST" and path in BUDGET_PATHS and (slug := self.space()):
                try:
                    panel.check_budget(slug)              # дневной бюджет пространства исчерпан — не писать агенту
                except ValueError as e:
                    self.json({"error": str(e), "code": "budget"}, 403)
                    return False
            free = ("/api/logout", "/api/terms/accept", "/api/country", "/api/prefs", NOTIFY_DONE, TOUR, PERSONA, USES,
                    FEEDBACK, "/api/clientlog", BUG,
                    *HELP_OPEN, *EMAIL_OWN, *PASSKEY_OWN, *OIDC_OWN, *INVITE_OWN, *PUSH_OWN)   # и наблюдателю
            need = (("admin" if path in ADMIN_OK else "owner") if path in OWNER_ONLY else
                    "member" if (method == "POST" and path not in free) or path in MEMBER_ONLY else "viewer")
            if not allowed(role, need):
                why = ("это может только владелец" if need == "owner" else "это могут владелец и админ"
                       if need == "admin" else "у вас доступ только на просмотр")
                self.json({"error": why}, 403)
                return False
            cap = personas.PATH_CAP.get(path)               # потолок возможностей — это права, не только вид
            if cap and cap not in personas.ceiling(personas.access(role), panel.team, uid):
                self.json({"error": "этот раздел вам не открыл владелец пульта", "code": "cap", "cap": cap}, 403)
                return False
            if path in TTY and not self.dev_tty():
                self.json({"error": "живой терминал — только в режиме разработчика", "code": "dev"}, 403)
                return False
            if method == "POST" and path in CONFIRM and self.via() == "browser" and \
                    panel.auth.needs_confirm(self.session()):
                self.json({"error": "новый вход: подтвердите кодом, что команды выполняете вы", "code": "confirm",
                           "confirm": "code"}, 403)
                return False
            return True

        def terms_line(self, method: str, uid) -> bool:
            """Ссылка на пространство «для клиента» (штаб 21.11): вместо экрана условий — строка «Продолжая, вы
            принимаете условия» в панели. Смотреть можно сразу; первое действие (POST) — согласие человека ссылки,
            записывается за ним с датой (``people.accept``)."""
            rec = self.slink()[0] if self.via() == SLINK else None
            if not rec or rec.get("aud") == "self":
                return False
            if method == "POST":
                panel.people.accept(uid)
            return True

        def dev_tty(self) -> bool:
            """Живой терминал: владелец или участник, у которого в виде есть «Экран терминала» и не простой режим.
            Фокус-ссылка сюда не доходит (``FOCUS_*``). Тестировщик пространства — как владелец, за «режимом
            разработчика», и только окна своего пространства (``tty_window``; решение владельца 20.11, GAS-38)."""
            if self.focused is not None:
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

        def rec_owner(self) -> str:
            """Чей сеанс записи: человек, пространство и фокус-ссылка — чужой сеанс не виден и не дописывается."""
            return f"{self.terms_uid()}:{self.space() or ''}:{(self.focused or {}).get('id', '')}"

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

        def login_of(self, w: dict, lines: list[str]) -> dict | None:
            """«Нужен вход» на экране окна (logins.py) — только владельцу: не фокус, не пространство, не участник."""
            if self.focused is not None or self.who()[1] != "owner" or in_space(w):
                return None
            return logins.detect(lines)

        def win(self, wid) -> dict:
            if not (w := panel.window(str(wid or ""))):
                t = panel.tmux.window(str(wid or ""))
                raise LookupError("Claude в этой сессии остановлен — текст в командную строку не отправляю. "
                                  "Нажмите «Перезапустить»" if t and t.get("stopped") else "окна уже нет")
            return w

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path.startswith(V1_PREFIX):           # 1С и CRM: токен, белый список access.V1_* (apitokens.py)
                return self.v1_call("GET")
            if url.path == "/api/gate/desktop":         # Caddy forward_auth рабочего стола (#206): только владелец
                return self.desktop_gate()
            if url.path == "/desktop-enter":             # одноразовая ссылка вкладки: пропуск и переход на noVNC
                t = urllib.parse.parse_qs(url.query).get("t", [""])[0]
                got = DESK_TICKETS.pop(t, None) if t else None
                if not got or got[1] < time.time():
                    return self.oidc_page(403, "Ссылка устарела", "Откройте рабочий стол заново кнопкой в пульте.")
                return self.go(DESKTOP_URL, (desk_cookie(desk_pass(got[0]), tab=True),))
            if url.path in ("/", "/index.html"):
                body, packed = page_for(self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "")
                return self.reply(200, body, "text/html; charset=utf-8", packed=packed, etag=f'"{build}"')
            if url.path == "/terms":                    # соглашение простым языком, RU и EN — без входа (17.11)
                return self.reply(200, terms_page, "text/html; charset=utf-8")
            if (m := PART_PATH.fullmatch(url.path)) and m.group(1) in parts:   # часть интерфейса (#191)
                body, gz, etag = parts[m.group(1)]
                return self.reply(200, body, "text/javascript; charset=utf-8", packed=gz, etag=etag)
            if url.path in icons:                        # значок вкладки и экрана «Домой» — без входа, кэш на сутки
                body, ctype = icons[url.path]
                return self.reply(200, body, ctype, headers={"Cache-Control": "public, max-age=86400"})
            if url.path == "/manifest.webmanifest":     # экран «Домой» и пуш на iPhone (brand.py) — без входа
                body = manifest_focus if url.query == "focus" else manifest     # фокус: значок открывает фокус
                return self.reply(200, body, "application/manifest+json; charset=utf-8")
            if url.path == "/sw.js":                    # служебный файл уведомлений браузера (должен лежать в корне)
                sw = SW_JS.replace(brand.DEFAULT, brand.NAME_RU).encode()
                return self.reply(200, sw, "text/javascript; charset=utf-8")
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
            if url.path.startswith(("/q/", "/api/q/")) and not url.path.startswith(("/api/q/list", "/api/q/answers")):
                return self.anketa_http("GET", url.path)   # анкета клиента: без входа, только по личному коду
            if url.path.startswith(("/offer/", "/api/offer/")):     # предложение: без входа, только по коду
                return self.offer("GET", url.path)
            if not url.path.startswith("/api/"):
                return self.json({"error": "нет такой страницы"}, 404)
            q = dict(urllib.parse.parse_qsl(url.query))
            if url.path in ("/api/bridge/install.sh", "/api/bridge/install.ps1"):   # установка одной командой: без
                return self.bridge_installer(url.path.rsplit(".", 1)[1], q)          # входа, по коду пары (21.11)
            if url.path == "/api/bridge/bridge.mjs":     # файл моста для установщика — тот же, что в репозитории
                return self.bridge_file()
            if url.path == STT_STREAM:                   # WebSocket: вход — первым сообщением, не заголовком
                return self.stt_stream()
            if url.path == "/api/bridge/ws":             # мост к браузеру пользователя: токен — в подпротоколе
                return self.bridge_ws()
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
            if fn := routes.GET.get(path):              # таблицы областей (routes/): права уже проверены (permit,
                return fn(self, q)                       # focus_call, v1_call) — как у веток ниже
            if fn := routes.GET_W.get(path):            # ветки после «w = self.win(…)»: окно сессии — до вызова
                return fn(self, q, self.win(q.get("w")))
            if fn := routes.GET_P.get(path):            # развилка: несколько путей — одна функция (платежи)
                return fn(self, path, q)
            self.win(q.get("w"))   # путь не из таблиц — как раньше: окна нет — 404 «окна уже нет», иначе «нет метода»
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
            if path.startswith(V1_PREFIX):               # 1С и CRM: токен, белый список access.V1_* (apitokens.py)
                return self.v1_call("POST")
            if path == "/api/bridge/claim":             # мост: одноразовый код из панели → токен устройства
                return self.dispatch(self.bridge_claim)
            if path == "/api/bridge/rpc":               # агент (gas-pult bridge-mcp) → мост; секрет — файл 0600
                return self.dispatch(self.bridge_rpc)
            if path == "/api/drafts/check":             # коннектор: есть ли «Да» человека (approvals.py); секрет — файл
                return self.dispatch(self.drafts_check)
            if path == "/api/bridge/code":              # код пары из командной строки сервера (тот же секрет)
                return self.dispatch(self.bridge_code)
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
            if path.startswith("/api/q/") and path != "/api/q/new":
                return self.anketa_http("POST", path)
            if path.startswith("/api/offer/"):
                return self.offer("POST", path)
            if path in ("/api/invite/check", "/api/invite/enter"):   # лёгкий вход: код или ссылка, без Telegram
                return self.dispatch(lambda: self.invite_login(path))
            if path == "/api/focus/open":                  # фокус-ссылка: первое открытие привязывает устройство
                return self.dispatch(self.focus_open)
            if path == "/api/focus/ask":                   # «Попросить доступ»: ссылка не открылась (до входа)
                return self.dispatch(self.focus_ask)
            if path == "/share":                           # «Поделиться» Android (share_target): форма, кука входа
                return self.share_post()
            if path == "/api/share":                       # «Поделиться» iPhone: токен устройства, не кука
                return self.share_api()
            if self.headers.get(focus.HEADER):
                q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
                return self.focus_call("POST", path, q)
            if path in HELP_OPEN and not self.who()[1]:   # экран входа: подсказки только по нему
                return self.dispatch(lambda: self.help_anon(path))
            if not path.startswith("/api/") or not self.permit(path, "POST"):
                return None if path.startswith("/api/") else self.json({"error": "нет такой страницы"}, 404)
            with panel.tmux.scope(self.space()):
                self.dispatch(lambda: self.post(path))

        def share_len(self) -> int:
            try:
                return max(0, int(self.headers.get("Content-Length") or 0))
            except ValueError:
                return -1

        def share_post(self):
            """POST /share из системного «Поделиться» (Android): запись человека → 303 на ``/?share=<id>``. Без входа,
            без прав, больше 50 МБ — тоже 303, панель скажет почему («войдите и поделитесь снова»). Service worker
            пересылает форму с ``X-GP-SW: 1`` — ему JSON ``{"go": …}`` (браузер переходит сам)."""
            sw = self.headers.get("X-GP-SW") == "1"
            n, role = self.share_len(), self.who()[1]
            why = ("login" if not role else "denied" if not allowed(role, "member") or self.space() else
                   "big" if n > MAX_BODY else "error" if n <= 0 else "")
            rec = None
            if not why:
                try:
                    rec = panel.share_receive(self.terms_uid(), self.rfile, self.headers.get("Content-Type", ""), n,
                                              "android")
                except (ValueError, OSError) as e:
                    print("share:", e, file=sys.stderr, flush=True)
                    why = "error"
            if why:
                self.close_connection = True               # тело не дочитано — соединение не переиспользуем
            go = f"/?share={rec['id'] if rec else why}"
            return self.json({"go": go}) if sw else self.go(go)

        def v1_call(self, method: str):
            """``/api/v1/<путь>`` — псевдоним ``/api/<путь>`` для 1С и CRM. ``Authorization: Bearer <токен>``:
            неизвестный, отозванный, просроченный или выпустивший без прежних прав — 401; путь не из белого списка
            ``access.V1_*`` (или запись токеном «только чтение») — 403. Дальше — обычные ``permit`` и обработчик с
            правами и пространством выпустившего. Каждый вызов — строка в журнале (без тел и параметров)."""
            url = urllib.parse.urlparse(self.path)
            ext, ip, rec = url.path, self.client_ip(), None
            self.close_connection = True                 # токен — на каждый запрос заново, без keep-alive
            try:
                if panel.api_guard.blocked(ip):
                    return self.json({"error": "слишком много неверных токенов — подождите минуту"}, 429)
                rec = panel.api_tokens.check(apitokens.bearer(self.headers.get("Authorization", "")))
                role = panel.people.role(rec["by"]) if rec else None
                if rec and role and (panel.people.tenant(rec["by"]) or "") != rec["space"]:
                    role = None                          # человека перевели в другое пространство — токен не его
                if not role or (not rec["space"] and role != "owner"):
                    if not rec:
                        panel.api_guard.fail(ip)
                    return self.json({"error": "нужен действующий токен: Настройки → Токены для 1С и CRM",
                                      "code": "token"}, 401)
                path = "/api/" + ext[len(V1_PREFIX):]
                table = V1_GET if method == "GET" else V1_POST
                ok = path not in V1_NEVER and any(path in table[g] for g in rec["groups"] if g in table)
                if not ok or (method == "POST" and not rec["write"]):
                    why = "токен только для чтения" if ok else "этот путь через токен закрыт"
                    return self.json({"error": why, "code": "v1_scope"}, 403)
                if method == "POST" and path in ("/api/tasks/add", "/api/tasks/update"):
                    try:
                        b = json.loads(self.body() or b"{}")
                    except ValueError:
                        return self.json({"error": "тело — JSON"}, 400)
                    self.raw = json.dumps(b).encode()        # обработчик прочитает то же тело (H.body)
                    if not isinstance(b, dict) or b.get("kind") == "command" or "cmd" in b:
                        return self.json({"error": "задачи с командой сервера через токен не создаются",
                                          "code": "v1_scope"}, 403)
                self.apitok, self.focused = {"uid": rec["by"], "role": role}, None
                self.path = path + (f"?{url.query}" if url.query else "")
                if not self.permit(path, method):
                    return None
                q = dict(urllib.parse.parse_qsl(url.query))
                with panel.tmux.scope(self.space()):
                    self.dispatch(lambda: self.get(path, q) if method == "GET" else self.post(path))
                return None
            finally:
                panel.api_log.write((rec or {}).get("id", ""), method, ext, self.sent_code or 500)

        def api_owner(self) -> tuple[int, str]:
            """Чьи токены /api/v1: владелец пульта — свои (пространство ""); человек пространства (не наблюдатель) —
            свои в своём пространстве. Админу, участнику без пространства, наблюдателю — нет."""
            role, uid = self.who()[1], self.terms_uid()
            if self.focused is not None or self.apitok is not None or uid is None:
                raise ValueError("токены выпускает владелец пульта или пространства")
            if slug := self.space():
                if not allowed(role, "member"):
                    raise ValueError("наблюдателю токены не выдаются")
                return uid, slug
            if role != "owner":
                raise ValueError("токены выпускает владелец пульта или пространства")
            return uid, ""

        def share_api(self):
            """POST /api/share (iPhone «Быстрая команда»): ``Authorization: Bearer <токен устройства>``; multipart,
            JSON или форма. Нет токена, чужой, отозван, человек без роли — 401; больше 50 МБ — 413."""
            rec = panel.share_tokens.check(share.bearer(self.headers.get("Authorization", "")))
            role = panel.people.role(rec["uid"]) if rec else None
            if not role or not allowed(role, "member") or panel.people.tenant(rec["uid"]):
                self.close_connection = True
                return self.json({"error": "нужен токен устройства: Гаврила → Настройки → Аккаунт и вход → "
                                           "Устройства для «Поделиться»", "code": "token"}, 401)
            n = self.share_len()
            if n > MAX_BODY or n < 0:
                self.close_connection = True
                return self.json({"error": "больше 50 МБ — отправьте частями"}, 413)

            def save():
                got = panel.share_receive(rec["uid"], self.rfile, self.headers.get("Content-Type", ""), n, "iphone")
                panel.share_notify(rec["uid"], got)
                base = (panel.public_url or "").rstrip("/")
                return {"ok": True, "id": got["id"], "open": f"{base}/?share={got['id']}"}
            return self.dispatch(save)

        def bridge_claim(self):
            b = json.loads(self.body() or b"{}")
            return panel.devices.claim(b.get("code", ""), b.get("name", ""), b.get("os", ""), str(b.get("old") or ""))

        def bridge_installer(self, kind: str, q: dict):
            """``install.sh`` / ``install.ps1`` с адресом панели и кодом пары; код не тратится (тратит пара)."""
            host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "").split(",")[0].strip()
            proto = (self.headers.get("X-Forwarded-Proto") or
                     ("https" if self.headers.get("X-Forwarded-Host") else "http")).split(",")[0].strip()
            remove, code = q.get("do") == "remove", str(q.get("c") or "")
            try:
                text = bridge_install.script(kind, f"{proto}://{host}", code, remove=remove,
                                             valid=remove or panel.devices.peek(code))
            except ValueError as e:
                return self.json({"error": str(e)}, 400)
            return self.reply(200, text.encode(), "text/plain; charset=utf-8",
                              headers={**NOINDEX, "Cache-Control": "no-store"})

        def bridge_file(self):
            f = Path(__file__).resolve().parents[2] / "bridge" / "gas-pult-bridge.mjs"
            try:
                body = f.read_bytes()
            except OSError:
                return self.json({"error": "на сервере нет файла моста"}, 404)
            return self.reply(200, body, "text/javascript; charset=utf-8", headers={"Cache-Control": "no-store"})

        def bridge_rpc(self):
            space = panel.bridge_space(self.headers.get("X-GP-Space-Token", ""))
            if not space and not secrets.compare_digest(self.headers.get("X-GP-Local", ""),
                                                        bridge_local_token(panel.cfg.data)):
                self.json({"error": "нет доступа"}, 403)
                return SENT
            b = json.loads(self.body() or b"{}")
            allowed = {d for d in (panel.bridge_space_allowed(space) if space else
                                   panel.bridge_allowed(str(b.get("window") or "")))
                       if panel.bridge_dev_ok(panel.devices.get(d))}
            return panel.hub.call(b.get("msg") or {}, str(b.get("device") or ""), allowed=allowed) or {"ok": True}

        def bridge_code(self):
            if not secrets.compare_digest(self.headers.get("X-GP-Local", ""), bridge_local_token(panel.cfg.data)):
                self.json({"error": "нет доступа"}, 403)
                return SENT
            return panel.devices.pair_code()

        def bridge_ws(self):
            """Мост держит соединение: запросы агентов (JSON-RPC MCP) идут ему, ответы — обратно (``bridge.Hub``)."""
            key = wsock.accept(self.headers)
            if not key:
                return self.json({"error": "нужен WebSocket"}, 400)
            protos = [x.strip() for x in self.headers.get("Sec-WebSocket-Protocol", "").split(",")]
            tok = next((x[4:] for x in protos if x.startswith("gpb-")), "")
            dev = panel.devices.check(tok)
            if not panel.bridge_dev_ok(dev):
                return self.json({"error": "устройство не подключено или отозвано"}, 401)
            self.close_connection = True
            self.wfile.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                              f"Sec-WebSocket-Accept: {key}\r\nSec-WebSocket-Protocol: gpb-{tok}\r\n\r\n").encode())
            self.connection.settimeout(120)
            ws = wsock.Conn(self.rfile, self.wfile, limit=BRIDGE_MAX)   # снимки экрана и страниц — больше 1 МБ
            panel.hub.attach(dev["id"], ws)
            panel.devices.seen(dev["id"])
            try:
                while True:
                    op, data = ws.recv()
                    if op == wsock.TEXT:
                        panel.hub.on_message(dev["id"], data)
            except (wsock.Closed, wsock.ProtocolError, OSError, ValueError):
                pass
            finally:
                panel.hub.detach(dev["id"], ws)
                ws.close()

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
                if focus.Focus.is_demo(self.focused):      # демо-ссылка: голоса нет — только смотреть и выбирать
                    self.focused = None
                    return fail("по демо-ссылке голос недоступен", "focus_scope", 4403)
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
            token = str((b if isinstance(b, dict) else {}).get("token") or "")
            # владелец 21.11: «по фокус-ссылке должны быть все инструменты такие же, как и без неё». Ссылку открыл
            # сам владелец на устройстве, где он вошёл, — открываем обычную панель на этом чате (все инструменты);
            # устройство к ссылке не привязываем (слоты устройств — для того, кому ссылку отправили)
            ouid = panel.auth.uid(self.session()) if self.session() else None
            if ouid is not None and (ouid == webauth.LEGACY or panel.is_owner(ouid)):
                r0 = panel.focus.check_token(token)
                if r0 and r0.get("mode") not in (focus.SPACE, focus.MEETING) and not focus.Focus.is_demo(r0):
                    return {"ok": True, "owner_here": True, "w": r0.get("w") or "", "proj": r0.get("proj") or ""}
            value, rec = panel.focus.open(token, self.focus_cookie(), webauth.device(self.client()[1]))
            age = max(60, int(rec["exp"] - time.time()))
            if rec.get("mode") == focus.SPACE and rec.get("space") and not panel.people.accepted(focus.vuid(rec["id"])):
                # владелец 19.11: «попал по ссылке — значит проверен; не спрашивать ни про страну, ни про что» —
                # страна — пространства, первая сессия; условия: «для себя» — отмечены выпуском ссылки, «для
                # клиента» — человек соглашается сам строкой «Продолжая, вы принимаете условия» (штаб 21.11)
                with contextlib.suppress(Exception):
                    panel.space_welcome(focus.vuid(rec["id"]), rec["space"], accept=rec.get("aud") == "self")
            cookie = f"{focus.COOKIE}={value}; Path=/; Max-Age={age}; HttpOnly; Secure; SameSite=Strict"
            return ("cookie", cookie, {"ok": True, "name": rec.get("name", ""), "id": rec["id"],
                                       **({"mode": rec["mode"]} if rec.get("mode") in (focus.SPACE, focus.MEETING)
                                          else {})})

        def focus_ask(self):
            """«Попросить доступ» со страницы, где ссылка не открылась: ``{token?, id?, why, note}`` — владельцам.
            Защита от перебора и спама: не больше ``ask_guard.LIMIT`` запросов с адреса за ``WINDOW`` (429)."""
            ip = self.client_ip()
            if panel.ask_guard.blocked(ip):
                self.json({"error": "Запрос уже отправлен. Подождите 10 минут.", "code": "ask_limit"}, 429)
                return SENT
            panel.ask_guard.fail(ip)
            b = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 4096)) or b"{}")
            b = b if isinstance(b, dict) else {}
            return panel.focus_ask(str(b.get("token") or "")[:64], str(b.get("id") or "")[:12],
                                   str(b.get("why") or ""), str(b.get("note") or ""),
                                   webauth.device(self.client()[1]))

        def focus_call(self, method: str, path: str, q: dict):
            """Запрос страницы в режиме фокуса: действующая ссылка этого устройства, путь из ``FOCUS_*``, окно — только
            её. Ссылка погасла — 410 (страница покажет «Чат завершён»), чужое — 403."""
            try:
                rec = panel.focus_rec(self.focus_cookie())
            except focus.Gone as e:
                return self.json({"error": str(e), "code": "focus_gone", "why": e.why}, 410)
            except focus.Wait as e:                      # сессию перезапускают — ссылка жива, страница повторит
                return self.json({"error": str(e), "code": "focus_wait"}, 503)
            if focus.Focus.is_meeting(rec):              # ссылка на протокол: только он, ни сессий, ни прав владельца
                if path not in (MEETING_GET if method == "GET" else MEETING_POST):
                    return self.json({"error": "по ссылке доступен только этот протокол", "code": "focus_scope"}, 403)
                if path == "/api/logout":
                    gone = f"{focus.COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict"
                    return self.reply(200, b'{"ok": true}', cookie=gone)
                return self.dispatch(lambda: panel.meeting_public(rec, path))
            proj_path = path in (FOCUS_PROJ_GET if method == "GET" else FOCUS_PROJ_POST)
            allowed = bool(rec.get("proj")) if proj_path else path in (FOCUS_GET if method == "GET" else FOCUS_POST)
            if focus.Focus.is_demo(rec):                 # демо-ссылка: только смотреть и выбирать вариант
                proj_path, allowed = False, path in (DEMO_GET if method == "GET" else DEMO_POST)
                if not allowed:
                    return self.json({"error": "по демо-ссылке — только просмотр и выбор вариантов",
                                      "code": "focus_scope"}, 403)
            if not allowed:
                return self.json({"error": "по фокус-ссылке доступна только её сессия", "code": "focus_scope"}, 403)
            b: dict = {}
            if method == "POST" and path not in ("/api/upload", "/api/stt", "/api/space/upload", "/api/rec/chunk"):
                try:
                    self.raw = self.body()
                    b = json.loads(self.raw or b"{}")
                except ValueError as e:
                    return self.json({"error": str(e) or "неверный запрос"}, 400)
                if not isinstance(b, dict):
                    return self.json({"error": "ожидался объект"}, 400)
            src = q if method == "GET" or path == "/api/space/upload" else b
            if proj_path:
                if str(src.get("id") or "") != rec["proj"]:
                    return self.json({"error": "по фокус-ссылке доступен только её проект", "code": "focus_scope"},
                                     403)
            elif path not in FOCUS_NO_W and not panel.focus_owns(rec, str(src.get("w") or "")):
                return self.json({"error": "по фокус-ссылке доступна только её сессия", "code": "focus_scope"}, 403)
            self.focused = rec
            try:
                with panel.tmux.scope(rec.get("space")):
                    return self.dispatch(lambda: self.focus_do(method, path, q, b, rec))
            finally:                                      # соединение может жить дольше запроса — права не переносим
                self.focused, self.raw = None, None

        def focus_do(self, method: str, path: str, q: dict, b: dict, rec: dict):
            demo = focus.Focus.is_demo(rec)
            if path == "/api/media":                       # картинки ленты — только из папок этой ссылки (19.11)
                return panel.media(str(q.get("p") or ""), roots=panel.focus_roots(rec))
            if path == "/api/meta":                        # демо — роль «наблюдатель»: интерфейс прячет действия
                return {**panel.focus_meta(rec), "via": "focus", "role": "viewer" if demo else "owner", "uid": None,
                        "build": build}
            if demo and path == "/api/key":
                key = str(b.get("key", ""))
                if key not in panel.DEMO_KEYS:
                    raise focus.Denied("по демо-ссылке — только выбор варианта в вопросе Claude")
                return panel.demo_answer(str(b.get("w") or ""), key == "Enter", lambda: self.post(path))
            if demo and path == "/api/select":
                return panel.demo_answer(str(b.get("w") or ""), b.get("go", True) is not False, lambda: self.post(path))
            if path.startswith("/api/focus/bridge"):
                return panel.focus_bridge(rec, path, b)
            if path == "/api/focus/device":                # «Открыть на другом устройстве»: только своя запись
                return panel.focus_device(rec["id"], str(b.get("base") or ""))
            if path == "/api/sessions":
                ss = panel.focus_sessions(rec)
                return {"sessions": ss, "host": rec.get("name", ""), "build": build, "now": time.time(), "cost": None,
                        "fallback": [], "focus": True}
            if path == "/api/logout":                      # «Выйти» на устройстве: cookie фокуса стираем, ссылка живёт
                gone = f"{focus.COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict"
                return ("cookie", gone, {"ok": True})
            if path == "/api/close":                       # «Завершить» в фокусе: сессия закрывается, ссылка гаснет
                wid = str(b.get("w") or "") if rec.get("proj") else rec["w"]   # у проекта — окно из запроса (проверено)
                w = panel.session_window(wid)
                if b.get("schedule"):                      # агент модуля: оставить / приостановить / выключить
                    panel.set_schedule(w["path"], str(b["schedule"]), self.terms_uid())
                r = panel.close_ex(w)
                if r["result"] == "закрыто":
                    panel.focus.end_window(wid)            # ссылку на проект это не гасит (focus.end_window)
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
            bot = panel.bot_username()
            link = f"https://t.me/{bot}?start=login_{nonce}"
            # запасные пути (штаб 22.11: на Mac ссылка t.me не открыла Telegram): tg:// — приложение напрямую, QR — с
            # телефона; поле добавлено, старые поля — как были
            return {"id": rid, "link": link, "ttl": webauth.LOGIN_TTL,
                    "app": f"tg://resolve?domain={bot}&start=login_{nonce}",
                    "qr": "data:image/png;base64," + base64.b64encode(qr.png_of(link, 6)).decode()}

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
            self.product("login", uid, "invite")
            return ("cookie", webauth.set_cookie(panel.auth.issue(uid, ua)), {"state": "ok"})

        def tg_poll(self, q: dict):
            state, uid = panel.logins.poll(q.get("id", ""))
            if state == "ok":
                if panel.email.wants_second(uid):                           # второй фактор: код ещё и на почту
                    return panel.email.second_start(uid, self.client_ip())
                panel.seen_ip(uid, self.client_ip(), force=True)            # вход — сверяем страну по IP
                panel.people.seen(uid, webauth.device(self.client()[1]))   # «вошёл: устройство, время»
                self.product("login", uid, "telegram")
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
            self.product("login", uid, "passkey")
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
            self.product("login", uid, "email" if path == "/api/login/email/verify" else "2fa")
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
            self.product("login", uid, p)
            return self.go("/", (drop, webauth.set_cookie(panel.auth.issue(uid, ua))))

        def login(self):
            b = json.loads(self.body() or b"{}")
            token = panel.auth.verify(str(b.get("id", "")), str(b.get("code", "")), self.client()[1])
            panel.seen_ip((panel.cfg.owners or [None])[0], self.client_ip(), force=True)   # вход кодом — владелец
            self.product("login", webauth.LEGACY, "code")
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

        def anketa_http(self, method: str, path: str):
            """``/q/<код>`` — страница анкеты; ``/api/q/<код>`` — анкета и черновик; ``…/save`` — черновик;
            ``…/submit`` — отправить. Неизвестный и просроченный код — один и тот же 404; перебор с IP — 429."""
            m = re.match(r"^/(api/)?q/([A-Za-z0-9_-]{16,64})(?:/(save|submit))?/?$", path)
            ip, api = self.client_ip(), path.startswith("/api/")
            if panel.q_misses.blocked(ip):
                return self.offer_reply(429, {"error": "слишком много запросов — подождите 10 минут"}, page=False)
            try:
                rec, form = panel.anketa(m.group(2)) if m and bool(m.group(1)) == api else (None, None)
            except LookupError:
                rec = form = None
            if not rec:
                panel.q_misses.miss(ip)
                body = OFFER_404.encode() if not api else {"error": "ссылка не найдена или устарела"}
                return self.offer_reply(404, body, page=not api)
            if not api:
                return self.offer_reply(200, q_page, page=True, csp=q_csp)
            act = m.group(3) or ""
            if method == "GET" and not act:
                return self.offer_reply(200, {"form": onboarding.public(form), "draft": rec.get("draft") or {},
                                              "sent": bool(rec.get("sent"))})
            if method != "POST" or not act:
                return self.offer_reply(404, {"error": "нет такого метода"})
            try:
                b = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 262144)) or b"{}")
                answers = b.get("answers") if isinstance(b, dict) else None
                if act == "save":
                    panel.forms_links.draft(m.group(2), onboarding.clean(form, answers))
                    return self.offer_reply(200, {"ok": True})
                return self.offer_reply(200, panel.anketa_submit(m.group(2), answers))
            except (ValueError, LookupError) as e:
                return self.offer_reply(400, {"error": str(e) or "ошибка"})

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
            if fn := routes.POST_RAW.get(path):         # таблицы областей (routes/): тело читает сама
                return fn(self)
            if fn := routes.POST.get(path):             # тело — JSON, как «b = json.loads(…)» ниже
                return fn(self, json.loads(self.body() or b"{}"))
            b = json.loads(self.body() or b"{}")
            if fn := routes.POST_P.get(path):           # развилка: несколько путей — одна функция (платежи и др.)
                return fn(self, path, b)
            if fn := routes.POST_W.get(path):           # ветки после «w = self.win(b.get("w"))»: окно — до вызова
                return fn(self, b, self.win(b.get("w")))
            self.win(b.get("w"))   # путь не из таблиц — как раньше: окна нет — 404 «окна уже нет», иначе «нет метода»
            raise KeyError

        def dispatch(self, fn):
            try:
                out = fn()
            except KeyError:
                return self.json({"error": "нет такого метода"}, 404)
            except focus.Gone as e:                      # фокус-ссылка не действует: страница покажет почему
                return self.json({"error": str(e), "code": "focus_gone", "why": e.why}, 410)
            except focus.Denied as e:                    # демо-ссылке нельзя (403) или уже ответили (409)
                return self.json({"error": str(e), "code": e.code}, e.status)
            except LookupError as e:
                return self.json({"error": str(e)}, 404)
            except NeedForce as e:
                return self.json({"error": str(e), "code": "force"}, 409)
            except emailcode.LimitError as e:
                return self.json({"error": str(e), "retry": e.retry}, 429)
            except AwaitsChoice as e:                    # Claude ждёт выбора: панель подсветит варианты, текст — в поле
                return self.json({"error": str(e), "code": e.code}, 400)
            except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired, providers.ProviderError) as e:
                return self.json({"error": str(e) or "ошибка"}, 400)
            except Exception as e:                       # прочее — 500 JSON и событие, а не обрыв (502 у Caddy)
                return self.crash(e)
            if out is SENT:                              # ответ уже отправлен (свой заголовок: ETag)
                return None
            if isinstance(out, tuple) and out[0] == "cookie":
                return self.reply(200, json.dumps(out[2], ensure_ascii=False).encode(), cookie=out[1])
            if isinstance(out, tuple):                   # (тип, байты[, заголовки]) — файл, звук
                return self.reply(200, out[1], out[0], headers=out[2] if len(out) > 2 else None)
            return self.json(out)

    H.panel = panel                             # для таблиц маршрутов (routes/): их функции получают обработчик
    H.build = build                             # версия страницы — для таблиц маршрутов («/api/projects»)
    H.whatsnew = whatsnew                       # «Что нового» — для таблиц маршрутов («/api/meta»)
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
        except (TelegramError, OSError) as e:        # и таймаут сети: панель запускается без кнопки (18.11)
            print(f"menu: {chat}: {e if isinstance(e, TelegramError) else f'{type(e).__name__}: {e}'}", flush=True)


WINDOWS_TTL = 2.0                                   # с: см. Tmux.ttl


def serve(cfg: Config, port: int = 8765, use_tunnel: bool = False, url: str | None = None):
    Tmux.ttl = WINDOWS_TTL                          # список окон — общий на цикл опроса браузера (tmux.py)
    panel = Panel(cfg)
    panel.owner_space_fix()                         # вид владельца — его выбор, не чужой (см. owner_space_fix)
    getattr(panel.tmux, "spawn_hook", lambda: None)()   # окно из окна — видно по фокус-ссылке (spawned.py)
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
            try:
                panel.trash_tick()                         # корзина чатов: старше 30 дней — раз в час окончательно
            except Exception as e:                         # цикл не падает из-за корзины
                print("корзина чатов:", e, flush=True)
            try:
                panel.move_tick()                          # отложенные переносы чатов: окно освободилось — переносим
            except Exception as e:
                print("перенос чатов:", e, flush=True)
            try:
                panel.temp_tick()                          # остатки озвучки (*.tmp.wav, пустые .mp3) — раз в час
            except Exception as e:
                print("остатки озвучки:", e, flush=True)
    threading.Thread(target=sweep, daemon=True).start()

    def alive():                                           # отметка heartbeat-web и без посетителей: запрос к себе
        while True:                                        # же — сервер отвечает, значит панель жива (#438)
            time.sleep(alerts.BEAT_EVERY)
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/alive", timeout=10).close()
            except urllib.error.HTTPError:
                pass                                       # ответ есть (401) — отметка уже записана
            except OSError as e:
                print("проверка жизни панели:", e, flush=True)
    threading.Thread(target=alive, daemon=True).start()
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
