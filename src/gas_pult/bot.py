"""Пульт: Telegram ⇄ окна Claude Code в tmux.

Меню: 🆕 Новая · 🔀 Переключить · 📊 Сводка · ⚡ Команды · 📋 Окна · ⚙️ Настройки.
- Текст, голосовое, фото и файлы уходят в активное окно (голос — через faster-whisper).
- Монитор: любой законченный ход Claude и любой диалог на экране (разрешения, /model, /mcp) приходят сами,
  с кнопками 🔊 ✅ ✏️ и 1/2/3/↑/↓.
- Номер задачи (GAS-123) — новая сессия по задаче. Команды из ответа — отдельными сообщениями с ▶️.
- «#ревью» в начале сообщения владельца — отчёт ревью файлом в inbox для разбора, не в окно (``review_inbox.py``).
Пускает только владельцев из ``owners``; от остальных принимает лишь вход в панель «через Telegram»
(``/start login_…`` и кнопки «Войти / Это не я») — остальное молча игнорирует.
До согласия с условиями использования (``terms.py``) на любое действие бот отвечает текстом условий и кнопкой
«Принимаю»; вход в панель через Telegram это не задерживает — условия человек примет в самой панели.
После условий — страна (``country.py``): выбор кнопками или кодом, затем «Поделиться номером» (берём код страны,
номер — только хешем). Участники и наблюдатели пишут боту только это (и вход в панель); остальное — как раньше.
Новая сессия и текст в окно — только если поставщик окна разрешён для стран человека; иначе — ``country.DENY``.
"""

from __future__ import annotations

import fcntl  # noqa: F401 — bot.fcntl: в botparts/windows.py, имя живо
import hashlib  # noqa: F401 — bot.hashlib: отпечаток меню в botparts/monitor.py, имя живо
import html
import json  # noqa: F401 — bot.json: в botparts/windows.py, имя живо
import os
import re
import subprocess
import threading
import time
import urllib.parse
import uuid
from contextlib import contextmanager, suppress  # noqa: F401 — bot.contextmanager: в botparts/windows.py, имя живо
from datetime import date, datetime
from functools import cached_property
from pathlib import Path
from typing import ClassVar

from gas_pult import (
    activity,
    ago,
    alerts,  # noqa: F401 — bot.alerts: монитор в botparts/monitor.py, имя живо
    brand,
    brief,
    chainfuse,  # noqa: F401 — bot.chainfuse: монитор в botparts/monitor.py, имя живо
    chatlog,
    country,
    ctxsnap,  # noqa: F401 — bot.ctxsnap: монитор в botparts/monitor.py, имя живо
    deliveries,
    digest,
    drive_inbox,
    emailcode,
    fallback,
    features,  # noqa: F401 — bot.features: монитор в botparts/monitor.py, имя живо
    focus,
    funnel,
    harness,
    humanize,  # noqa: F401 — bot.humanize: в botparts/windows.py, имя живо
    injection_guard,  # noqa: F401 — bot.injection_guard: Telegram в botparts/telegram.py, имя живо
    invites,
    limitretry,
    meetings,
    models,
    modules,
    notifylevel,
    notifyroute,  # noqa: F401 — bot.notifyroute: Telegram в botparts/telegram.py, имя живо
    offers,
    people,  # noqa: F401 — bot.people: в botparts/windows.py, имя живо
    projects,
    providers,  # noqa: F401 — bot.providers: выбор голоса в botparts/voice.py, имя живо
    qr,
    review_inbox,
    secrets_guard,  # noqa: F401 — bot.secrets_guard: в botparts/windows.py, имя живо
    selftest,  # noqa: F401 — bot.selftest: монитор в botparts/monitor.py, имя живо
    setup,
    space_budget,
    spaces,  # noqa: F401 — bot.spaces: Telegram в botparts/telegram.py, имя живо
    speech,  # noqa: F401 — bot.speech: озвучка в botparts/voice.py, имя живо
    store,
    tasks,
    tenants,
    terms,
    termwin,
    testers,
    tglinks,  # noqa: F401 — bot.tglinks: Telegram в botparts/telegram.py, имя живо
    tgroutes,
    transcripts,
    usage,
    voice,
    webpush,  # noqa: F401 — bot.webpush: Telegram в botparts/telegram.py, имя живо
)
from gas_pult import tmux as tmux_mod  # noqa: F401 — bot.tmux_mod: монитор в botparts/monitor.py, имя живо
from gas_pult.botparts.base import HINT, QUESTION, AwaitsChoice, Denied, NotReady  # noqa: F401 — окна в botparts/windows.py; bot.<имя> живы
from gas_pult.botparts.meetings import MeetingsPart
from gas_pult.botparts.monitor import NOISE, MonitorPart, dialog_hash  # noqa: F401 — bot.NOISE, bot.dialog_hash живы
from gas_pult.botparts.telegram import MENU, TelegramPart
from gas_pult.botparts.voice import VoicePart
from gas_pult.botparts.windows import (  # noqa: F401 — bot.<имя>: окна в botparts/windows.py, имена живы
    DEFAULTS,
    KEYS,
    PANEL,
    PROMPT,
    WindowsPart,
    escalate_rows,
    free,
)
from gas_pult.commands import DANGER, SPACE_RUN, TAIL, Commands, Journal, fail_key, in_space, triage_text
from gas_pult.config import Config
from gas_pult.humanize import BUSY, DIALOG  # переехали в humanize.py (признаки экрана); bot.BUSY, bot.DIALOG живы
from gas_pult.people import TITLES, People, allowed, has_telegram, is_guest  # noqa: F401 — окна в botparts/windows.py; bot.<имя> живы
from gas_pult.telegram import Api, TelegramError, kb
from gas_pult.tmux import Tmux, prompt_draft  # noqa: F401 — bot.prompt_draft: в botparts/windows.py, имя живо
from gas_pult.tmux import is_ours as tmux_is_ours  # noqa: F401 — bot.tmux_is_ours: в botparts/windows.py, имя живо
from gas_pult.voice import catalog
from gas_pult.webauth import Auth, TgConfirm, TgLogins

TESTER_HELLO = ("🧪 Вы — тестировщик демо-пространства пульта.\n\n"
                "1. Нажмите кнопку «📱 Панель» внизу чата — откроется ваше пространство.\n"
                "2. «Новая сессия» — агент запустится только в нём: ни чужих окон, ни файлов сервера.\n"
                "3. Пишите агенту задания так, как написали бы сотруднику.\n\n"
                "Если что-то непонятно или агент застрял — «Позвать на помощь» в панели или /help здесь: "
                "владелец получит вашу сессию и подключится.")


def tester_start(u: dict, ppl) -> bool:
    """/start и /menu от тестировщика демо-пространства — бот отвечает инструкцией (остальное ему не работает)."""
    m = u.get("message") or {}
    uid = (m.get("from") or {}).get("id")
    return (m.get("text") or "").strip() in ("/start", "/menu", "/help") and bool(ppl.tenant(uid))


def public(u: dict) -> bool:
    """Что принимаем и от незнакомых: начало входа в панель и кнопки подтверждения входа; демо предложения
    (``/start demo_<токен>`` и его кнопки ``dm:``) — изолированно, без роли и без доступа к пульту; ``lk:`` — гость
    привязывает свой Telegram (у этого Telegram роли ещё нет)."""
    if m := u.get("message"):
        return (m.get("text") or "").startswith(("/start login_", "/start demo_"))
    return (u.get("callback_query") or {}).get("data", "").startswith(("lg:", "lk:", "dm:"))


DEMO_GONE = "Демо закончилось — откройте ссылку на странице предложения снова."
DEMO_RATE = (5, 3600)          # сценарий демо — не чаще 5 раз в час на человека (счётчик только в памяти)


def _clip(text: str, limit: int = 4000) -> str:
    """Одно сообщение Telegram (лимит 4096): лишние строки срезаем целиком, в конце — «…»."""
    if len(text) <= limit:
        return text
    return text[:text.rfind("\n", 0, limit - 2)] + "\n…"


PHONE_KB = {"keyboard": [[{"text": "📱 Поделиться номером", "request_contact": True}], [{"text": "Позже"}]],
            "resize_keyboard": True, "one_time_keyboard": True}
MENU_PREFIXES = ("🆕", "🔀", "📊", "⚡", "📋", "⚙️")
COMMANDS = [("🧠 Модель", "models"), ("🔌 MCP", "/mcp"), ("📏 Контекст", "/context"),
            ("🗜 Сжать", "/compact"), ("🧹 Очистить", "/clear"), ("ℹ️ Статус", "/status"),
            ("🔐 Разрешения", "/permissions"), ("💰 Расход", "/cost"), ("📖 HANDOFF", "handoff")]
PROMPTS = {"handoff": "Прочитай HANDOFF.md (или README) этого проекта и кратко доложи: состояние, блокеры, "
                      "следующий шаг."}
NAME_OK = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
NOTIFY = {"all": "все окна", "active": "только активное", "off": "выкл"}


TRIAGE_NOTE = {"sent": "🔎 Отправил на разбор в [{to}] — Claude предложит исправление",
               "dup": "🔎 Эта ошибка уже отправлялась на разбор в [{to}]",
               "closed": "Сессии этой папки уже нет — на разбор не отправил",
               "busy": "Claude в [{to}] ждёт ответа на вопрос — на разбор не отправил; выполните ещё раз позже"}


class Pult(TelegramPart, WindowsPart, MonitorPart, MeetingsPart, VoicePart):
    BURST = 3                  # больше ответов окна за один обход монитора — шлём последний и счётчик
    actor = threading.local()  # кто сейчас действует (Telegram ID; у каждого потока свой) — для проверки страны

    @cached_property
    def focus(self) -> focus.Focus:
        """Фокус-ссылки — один экземпляр на бот (как People); бот и панель пишут focus.json под store.locked."""
        return focus.Focus(self.cfg.data / "focus.json")

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.api = Api(cfg.token)
        self.tmux = Tmux(cfg.session)
        self.cmds = Commands(cfg.host, cfg.data / "cmds.json", cfg.sudo_allow, cfg.foreign, on_done=self.after_run,
                             on_start=self.before_run)
        self.journal = Journal(cfg.data / "commands-log.json")         # вкладка «Команды» панели
        self.task = re.compile(rf"^(?:/task\s+)?({cfg.task_pattern})$", re.I)
        self.state_file = cfg.data / "state.json"
        self.locks = cfg.data / "locks"                     # замки окон — общие для бота и панели
        self.lock = threading.Lock()
        self.answers: dict[int, tuple[str, str]] = {}     # n → (окно, текст) для 🔊; последние 100
        self.counter = 0
        self.waiting: dict[int, str] = {}                 # чат → чего ждём следующим сообщением
        self.home = os.path.expanduser("~")
        self.people = People(cfg.data / "people.json", cfg.owners)
        self.logins = TgLogins(cfg.data / "tg_logins.json")
        self.mail = emailcode.Service(cfg.email, self.people, cfg.data / "email_codes.json")   # письма-оповещения
        self.requests: dict[int, dict] = {}                # кто просит доступ: Telegram ID → имя, @username
        self.help_calls: dict[int, float] = {}             # тестировщик → когда звал на помощь (/help)
        self.hint_wait: dict[str, dict] = {}               # окно → ответ, к которому ждём подсказку Claude (90 с)
        self.hints: dict[int, tuple[str, str]] = {}        # n → (окно, текст подсказки) для кнопки 💡
        self.digest = digest.Digest(cfg.data / "digest.json")
        self.brief_prefs = brief.Prefs(cfg.data / "brief_prefs.json")   # брифинг (GAS-18): источники — у каждого свои
        self.alerts = brief.Alerts(cfg.data / "brief_alerts.json")      # срочное вне утра: что уже присылали
        self.urgent_at = 0.0
        self.schedule = modules.Schedule(cfg.data / "modules.json")   # расписание пространств из модулей
        self.offer_tg = offers.TgDemos(cfg.data / "offer_tg.json")     # демо предложений: токены от панели
        self.demo_seen: dict[int, list[float]] = {}                    # кто запускал демо — только в памяти, час
        self.reviews = review_inbox.Collector(cfg.data / "inbox")      # «#ревью» владельца — файлом для разбора
        # поставщик модели не отвечает — окно само уходит на запасной (fallback.py), владельцам — одна строка
        # запасные — по странам человека, чьё окно (@gas_pult_by), иначе первого владельца
        self.fallback = fallback.Switcher(self.tmux, self.state, cfg.claude, cfg.region,
                                          say=lambda line: self.broadcast("🔁 " + line), log=self.fallback_logged,
                                          countries=self.window_countries, on_rate=self.limit_wait)
        # вход в Claude Code из пульта (setup.py); config_dir/env — когда у каждого человека будет своя папка Claude
        self.login = setup.Login(cfg.session, cfg.claude, home=self.home)
        self.meter = usage.Meter()                         # расход сессий по журналам (usage.py)
        self.sends = activity.Sends()                      # что и когда отправили в окно — фазы до хода (activity.py)
        self.deliv = deliveries.Log(cfg.data / "sends.jsonl")   # журнал доставок без текста (deliveries.py)
        self.events = chatlog.Log(cfg.data / "chat-events.jsonl")  # путь сообщения по id (GAS-31)
        self.funnel = funnel.Funnel(cfg.data, cfg.events_keep_days)   # события продукта для воронки (funnel.py)
        self.drafts: dict[str, tuple[str, float]] = {}     # сторож черновиков: окно → (отпечаток, с какого времени)
        self.acts = activity.Journal()                     # разбор хвоста журнала для строки статуса (кэш)
        self.changes = ago.Screens()                       # когда менялся экран окна — «изменена N назад» (ago.py)
        self.following: dict[tuple, tuple] = {}            # (чат, окно) → (метка, id служебного сообщения статуса)
        self.routes = tgroutes.Routes(cfg.data / "tg_routes.json")   # сообщение бота → окно: reply идёт туда
        self.tasks = tasks.Tasks(cfg.data / "tasks.json")           # задачи владельца (#203): /tasks
        self.meetings = meetings.Store(cfg.data / "meetings.json")   # протоколы встреч (GAS-36)
        self.mt_wait: dict[int, dict] = {}                           # кусок ждёт «продолжение / новая встреча»
        self.cost_at = 0.0                                 # когда монитор последний раз сверял лимиты

    # ---------- задачи владельца (tasks.py, #203) ----------
    TASK_ICON: ClassVar[dict] = {"waiting": "⏳", "doing": "🔄", "todo": "⬜", "done": "✅"}
    Q_ICON: ClassVar[dict] = {1: "🔴", 0: "⚪", 2: "🟡", 3: "🟠", 4: "⚫"}

    def show_tasks(self, chat: int):
        """/tasks: невыполненные (ждут вас — первыми), у каждой — что дальше; кнопки «✅ Выполнено» и «💬 В чат»."""
        open_ = [x for x in self.tasks.list() if x["status"] != "done"][:10]
        if not open_:
            return self.send(chat, "✅ Невыполненных задач нет. Агенты ставят их командой gas-pult task add.")
        lines, rows, group = ["📋 Задачи — что не решено (по срочности и важности):"], [], None
        for i, x in enumerate(open_, 1):
            if x.get("q", 0) != group:
                group = x.get("q", 0)
                lines.append(f"\n{self.Q_ICON[group]} {tasks.QUADRANTS[group]}")
            what = {"command": x.get("cmd"), "call": x.get("phone"), "write": x.get("to"),
                    "meeting": " · ".join(v for v in (x.get("with"), x.get("when")) if v),
                    "decision": x.get("question"), "check": x.get("link")}.get(x["kind"]) or ""
            lines.append(f"{i}. {self.TASK_ICON.get(x['status'], '•')} {tasks.TITLES[x['kind']]}: {x['title']}"
                         + (f"\n   {what}" if what else "") + f"\n   → {x['next']}")
            row = [(f"✅ {i}", f"tk:done:{x['id']}")]
            if x.get("chat") and self.tmux.window(x["chat"]):
                row.append((f"💬 {i} — в чат", f"act:{x['chat']}"))
            rows.append(row)
        self.send(chat, "\n".join(lines), reply_markup=kb(rows))

    # ---------- модули-агенты (modules.py) ----------
    def module_root(self) -> Path:
        """Куда создавать пространства из модулей — первый корень проектов (как 📁 Новая папка)."""
        return self.cfg.roots()[0] if self.cfg.project_roots else Path(self.home) / "projects"

    def send_later(self, wid: str, text: str, wait: int = 180):
        """Первое задание в свежее окно — в фоне, когда Claude готов. Свежая папка начинается с вопроса «доверяете
        этой папке?»: ждём, пока человек ответит (до ``wait`` секунд), потом вставляем; не вышло — пишем владельцам."""
        def run():
            end, why = time.time() + wait, ""
            time.sleep(3)
            while time.time() < end:
                w = self.tmux.window(wid)
                if not w:
                    return
                try:
                    with self.via("scheduler"):
                        return self.to_claude(w, text)
                except NotReady as e:
                    why = str(e)
                    time.sleep(5)
            self.broadcast(f"Задание модуля не отправлено в окно {wid}: {why or 'окно не готово'}. "
                           "Откройте сессию и напишите «начинай».")
        threading.Thread(target=run, daemon=True).start()

    def show_modules(self, chat: int):
        """Каталог в два шага (одно сообщение Telegram — до 4096 знаков): «Общие» модули сразу, отрасли — кнопками,
        по нажатию (md:g:<n>) — модули отрасли."""
        ms = modules.catalog()
        if not ms:
            return self.send(chat, "Модулей нет.")
        groups = list(dict.fromkeys(m["industry"] for m in ms))     # в порядке каталога, «Общие» — первыми
        common = [m for m in ms if m["industry"] == "Общие"]
        lines = ["🧩 Модули — готовые агенты под задачу. Выберите модуль или отрасль:"]
        if common:
            lines += ["", "▪️ Общие"] + [f"• {m['title']} — {m['about']}" for m in common]
        inds = [(i, g) for i, g in enumerate(groups) if g != "Общие"]
        if inds:
            lines += ["", "Отрасли:"] + [f"▪️ {g} — {sum(m['industry'] == g for m in ms)}" for _, g in inds]
        rows = [[(m["title"], f"md:v:{m['id']}")] for m in common] + [[(f"▪️ {g}", f"md:g:{i}")] for i, g in inds]
        self.send(chat, _clip("\n".join(lines)), reply_markup=kb(rows))

    def show_industry(self, chat: int, n: str):
        """md:g:<n> — модули одной отрасли (n — номер группы в порядке каталога)."""
        ms = modules.catalog()
        groups = list(dict.fromkeys(m["industry"] for m in ms))
        if not n.isdigit() or int(n) >= len(groups):
            return self.show_modules(chat)                      # каталог поменялся — показываем заново
        g = groups[int(n)]
        own = [m for m in ms if m["industry"] == g]
        lines = [f"🧩 {g} — модулей: {len(own)}. Выберите, чтобы посмотреть и создать пространство:", ""]
        lines += [f"• {m['title']} — {m['about']}" for m in own]
        rows = [[(m["title"], f"md:v:{m['id']}")] for m in own] + [[("‹ Все отрасли", "md:list:")]]
        self.send(chat, _clip("\n".join(lines)), reply_markup=kb(rows))

    def module_text(self, m: dict) -> str:
        out = [f"🧩 {m['title']} · {m['industry']}", "", m["description"] or m["about"]]
        if m["integrations"]:
            out += ["", "Подключения (в панели):"]
            out += [f"• {x['title']}{' — по желанию' if x['optional'] else ''}: {x['why']}" for x in m["integrations"]]
        if m["schedule"]:
            out += ["", "Расписание:"]
            out += [f"• {x.get('when') or x['at']}" + ("" if x.get("workday") else f" {modules.days_text(x['days'])}")
                    + f" — {x['title']}" for x in m["schedule"]]       # раз в месяц — без дней недели
        if m["decisions"]:
            out += ["", "Решения кнопками:"]
            out += [f"• {x['question']} ({' / '.join(x['options'])})" for x in m["decisions"]]
        return "\n".join(out)

    def open_rows(self, mid: str) -> list:
        """Кнопки «📂 Открыть «папка» · изменено …» для пространств модуля, которые уже есть (свежие первыми)."""
        dirs = self.projects()
        return [[(f"📂 Открыть «{x['folder']}» · {ago.ago(x['changed'])}", f"new:{dirs.index(str(x['path']))}")]
                for x in modules.existing(self.module_root(), mid)[:3] if str(x["path"]) in dirs]

    def on_module(self, chat: int, arg: str):
        """md:v:<id> — описание; md:new:<id> — создать с именем по умолчанию; md:name:<id> — спросить имя; md:list —
        каталог; md:g:<n> — модули отрасли. Пространство модуля уже есть — первым «Открыть», «Создать ещё одно» —
        вторым и с подтверждением (md:again → md:new2), чтобы не плодить <id>-2, <id>-3."""
        act, _, mid = arg.partition(":")
        if act == "list":
            return self.show_modules(chat)
        if act == "g":
            return self.show_industry(chat, mid)
        try:
            m = modules.get(mid)
        except LookupError as e:
            return self.send(chat, f"Не нашёл модуль: {e}")
        folder = modules.free_name(self.module_root(), m["id"])
        have = self.open_rows(m["id"])
        if act == "v" or (act == "new" and have):         # старая кнопка «Создать» при уже созданном — снова выбор
            if have:
                return self.send(chat, self.module_text(m) + "\n\nЭтот модуль уже есть — откройте его.",
                                 reply_markup=kb([*have, [("➕ Создать ещё одно…", f"md:again:{m['id']}")],
                                                  [("‹ Все модули", "md:list:")]]))
            return self.send(chat, self.module_text(m), reply_markup=kb([
                [(f"✅ Создать «{folder}»", f"md:new:{m['id']}")], [("✏️ Другое имя папки", f"md:name:{m['id']}")],
                [("‹ Все модули", "md:list:")]]))
        if act == "again":
            return self.send(chat, f"Пространство «{m['title']}» уже есть. Точно создать ещё одно — «{folder}»?",
                             reply_markup=kb([[(f"✅ Да, создать «{folder}»", f"md:new2:{m['id']}")],
                                              [("✏️ Другое имя папки", f"md:name:{m['id']}")], *have]))
        if act == "new2":
            return self.module_create(chat, m["id"], folder)
        if act == "name":
            self.waiting[chat] = f"md:{m['id']}"
            return self.send(chat, f"Имя папки для «{m['title']}» (латиница, цифры, дефис), например {folder}:",
                             reply_markup={"force_reply": True})
        if act == "new":
            return self.module_create(chat, m["id"], folder)
        return None

    def module_create(self, chat: int, mid: str, name: str):
        if not setup.installed(self.cfg.claude):
            return self.show_setup(chat)
        uid = getattr(self.actor, "uid", None)
        if uid is not None and not models.allowed("claude", self.countries(uid)):
            return self.send(chat, country.DENY)
        try:
            path = modules.create(mid, self.module_root(), name, by=None if chat in self.cfg.owners else chat)
        except (ValueError, LookupError, OSError) as e:
            return self.send(chat, f"Не создал: {e}")
        m = modules.get(mid)
        self.send(chat, f"📁 Пространство «{m['title']}» — {path}. Открываю сессию…")
        self.open_session(chat, f"{path.name}-{time.strftime('%H%M')}", str(path))
        if w := self.project_window(str(path)):
            self.send_later(w["id"], m["start"])
        return None

    def modules_loop(self):
        while True:
            try:
                self.module_tick(datetime.now())
            except Exception as e:
                print("modules:", self.api.redact(e), flush=True)
            time.sleep(60)

    def module_tick(self, now: datetime):
        """Расписание пространств: в назначенное время — промпт модуля в окно этой папки. Окна нет — открываем
        (папкой Claude того, кто создал пространство) и шлём промпт первым сообщением; владельцам — одна строка."""
        for folder, m, item in self.schedule.due(self.cfg.roots(), now):
            name = f"«{m['title']}» ({folder.name})"
            try:
                if w := self.project_window(str(folder)):
                    with self.via("scheduler"):
                        self.to_claude(w, item["prompt"])
                    continue
                if w := self.folder_window(str(folder)):   # окно папки есть, Claude в нём остановлен — в нём же
                    by = modules.mark_of(folder).get("by")
                    home = self.claude_dir(by) if by is not None else None
                    sid = str(uuid.uuid4())             # новый разговор — новый журнал со своей меткой
                    self.tmux.respawn(w["id"], str(folder), models.with_home(self.cfg.claude, home) +
                                      f" --session-id {sid}", mark=w.get("mark") or "claude")
                    self.tmux.set_sid(w["id"], sid)
                    self.send_later(w["id"], item["prompt"])
                    self.broadcast(f"🗓 {name}: запустил по расписанию в окне «{self.label(w)}» ({item['title']}).",
                                   kind="brief")
                    continue
                if not setup.installed(self.cfg.claude):
                    self.broadcast(f"🗓 {name}: {item['at']} — Claude Code не установлен, задание не отправлено.",
                                   kind="brief")
                    continue
                by = modules.mark_of(folder).get("by")
                if not models.allowed("claude", self.countries(by if by is not None else self.cfg.owners[0])):
                    self.broadcast(f"🗓 {name}: {item['at']} — {country.DENY}", kind="brief")
                    continue
                home = self.claude_dir(by) if by is not None else None
                sid = str(uuid.uuid4())
                wid = self.tmux.new_window(folder.name, str(folder),             # имя — папка, без «-ЧЧММ»
                                           models.with_home(self.cfg.claude, home) + f" --session-id {sid}",
                                           by=str(by) if home else "", sid=sid)
                if not home:
                    self.tmux.run("set-option", "-w", "-t", wid, "@gas_pult_by", str(self.cfg.owners[0]))
                self.send_later(wid, item["prompt"])
                self.broadcast(f"🗓 {name}: открыл сессию по расписанию ({item['title']}).", kind="brief")
            except (NotReady, Denied) as e:
                if not item.get("every"):                # «каждые N минут» — следующий круг скоро: не дёргаем
                    self.broadcast(f"🗓 {name}: {item['at']} — задание не отправлено: {e}", kind="brief")
            except (RuntimeError, OSError) as e:
                self.broadcast(f"🗓 {name}: {item['at']} — не вышло: {e}", kind="brief")

    # ---------- экраны пульта ----------
    def show_windows(self, chat: int):
        ws = self.tmux.windows()
        if not ws:
            return self.send(chat, "Окон нет. Нажми 🆕 Новая.")
        now, info = time.time(), {}
        for w in ws:                                       # ждущие ответа — сверху, дальше — по последнему изменению
            if harness.is_agent(w):
                lines = self.tmux.screen(w["id"])
                self.changes.look(w["id"], lines)
                info[w["id"]] = (bool(DIALOG.search("\n".join(lines))), self.stamps(w)["changed"] or 0.0)
        ws = sorted(ws, key=lambda w: (not info.get(w["id"], (0, 0))[0], -info.get(w["id"], (0, 0))[1]))

        def label(w: dict) -> str:
            wait, ch = info.get(w["id"], (False, 0.0))
            when = (" · " + ago.ago(ch, now) + (" · " + ago.tr("ru", "ago.stale") if ago.stale(ch, now) else "")
                    if ch else "")
            return (f"{w['idx']}: {'⏸ ' if wait else ''}{self.label(w)} · {self.short(w['path'])}{when}"
                    + (" 🤖" if harness.is_agent(w) and harness.of(w).name == "claude" else ""))
        rows = [[(label(w), f"w:{w['id']}")] for w in ws]
        self.send(chat, "Окна tmux (🤖 — работает Claude, ⏸ — ждёт ответа; сверху — ждущие и недавние):",
                  reply_markup=kb(rows))

    def show_switch(self, chat: int):
        ws = [w for w in self.tmux.windows() if harness.is_agent(w)]
        act = self.state().get("active")
        if not ws:
            return self.send(chat, "Окон с Claude нет. Нажми 🆕 Новая.")
        self.send(chat, "Куда писать? (📡 — у окна свой Telegram-бот)", reply_markup=kb([[(
            ("✅ " if w["id"] == act else "") + f"{self.label(w)} · {self.short(w['path'])}"
            + (" 📡" if w["channel"] else ""), f"act:{w['id']}")] for w in ws]))

    def show_summary(self, chat: int):
        act, lines = self.state().get("active"), []
        for w in self.tmux.windows():
            if not harness.is_agent(w):
                lines.append(f"{w['idx']}. {self.label(w)} — терминал")
                continue
            scr = "\n".join(self.tmux.screen(w["id"], 40))
            status = "⏸ ждёт выбора" if DIALOG.search(scr) else "⚙️ работает" if BUSY.search(scr) else "✅ свободен"
            ch = self.stamps(w)["changed"]                 # экран отмечает монитор — по своим 25 строкам
            ctx = re.search(r"left [\d.]+k? \((\d+)%\)", scr)
            lines.append(f"{w['idx']}. {'▶️ ' if w['id'] == act else ''}{self.label(w)} · {self.short(w['path'])} — "
                         f"{status}" + (f" · {ago.tr('ru', 'ago.changed', ago=ago.ago(ch))}" if ch else "")
                         + (f" · контекст свободен {ctx.group(1)}%" if ctx else "")
                         + (" · 📡" if w["channel"] else ""))
        self.send(chat, "📊 Сводка\n" + "\n".join(lines or ["окон нет"]))

    def command_list(self) -> list[tuple[str, str]]:
        return COMMANDS + [(t, c) for t, c in self.cfg.commands]

    def show_commands(self, chat: int):
        if w := self.need_active(chat):
            cmds = list(enumerate(self.command_list()))
            rows = [cmds[i:i + 3] for i in range(0, len(cmds), 3)]
            self.send(chat, f"⚡ Команды для «{self.label(w)}»:",
                      reply_markup=kb([[(t, f"cmd:{i}") for i, (t, _) in r] for r in rows]))

    def show_settings(self, chat: int):
        s, voices = self.state(), catalog.installed(self.cfg.personal_voices)
        rows = [[("🔔 Все", "set:notify=all"), ("🔕 Только активная", "set:notify=active"),
                 ("🚫 Выкл", "set:notify=off")],
                [("🔊 Голосом: вкл/выкл", "set:voice_always"), ("🩺 Проверка", "su:check")], [("👥 Люди", "ppl:")]]
        rows += self.voice_rows()                          # та же сетка, что /voice: ▶ — послушать, имя — выбрать
        self.send(chat, f"⚙️ Уведомления: {NOTIFY.get(s['notify'], s['notify'])}\n"
                        f"🔊 Всегда голосом: {'да' if s['voice_always'] else 'нет'}\n" + self.voice_text()
                        + ("" if voices else "\n(голоса не установлены: gas-pult voices install irina)"),
                  reply_markup=kb(rows))

    def before_run(self, cmd: str, path: str):
        """▶️ в боте — во вкладке «Команды» панели сразу «выполняется»."""
        wins = [w for w in self.tmux.windows() if harness.is_agent(w) and w["path"] == path]
        self.journal.collect(wins, self.cmds.kind)
        self.journal.flag_cmd(path, cmd, running=time.strftime("%Y-%m-%d %H:%M", time.gmtime()))

    def after_run(self, cmd: str, path: str, code, secs: float, out: str) -> str:
        """▶️ в боте: отметка «выполнено» во вкладке «Команды» панели; упала — на разбор в сессию. Строка для итога."""
        wins = [w for w in self.tmux.windows() if harness.is_agent(w) and w["path"] == path]
        self.journal.collect(wins, self.cmds.kind)            # панель могла ещё не видеть этот ответ
        tri, to = self.triage(path, "", cmd, code, out)
        self.journal.mark_cmd(path, cmd, {"code": code, "seconds": round(secs), "by": "bot", "out": out[-TAIL:],
                                          "cut": len(out) > TAIL, "at": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
                                          "triage": tri, "triage_to": to}, out)
        return TRIAGE_NOTE.get(tri, "").format(to=to)

    def triage(self, path: str, wid: str, cmd: str, code, out: str, paste=None) -> tuple[str, str]:
        """Упала (код ≠ 0) — отправить команду, код и хвост вывода в сессию, откуда она пришла; одну ошибку — один раз.
        (состояние, имя окна): sent — отправлено, dup — уже отправляли, closed — окна нет, busy — Claude ждёт ответа."""
        if code == 0:
            return "", ""
        wins = [w for w in self.tmux.windows() if harness.is_agent(w) and w["path"] == path]
        w = next((x for x in wins if x["id"] == wid), None) or (wins[0] if wins else None)
        key = fail_key(path, cmd, code, out)
        if not w:
            return "closed", ""
        if not self.journal.triage_once(key):
            return "dup", self.label(w)
        try:
            (paste or self.to_claude)(w, triage_text(cmd, code, out))
        except NotReady:
            self.journal.forget_triage(key)                  # следующий запуск попробует снова
            return "busy", self.label(w)
        return "sent", self.label(w)

    def rename(self, chat: int, wid: str, name: str):
        """Своё название чата (projects.json по id разговора, как «Переименовать» в панели); имя окна не меняется."""
        w = self.tmux.window(wid)
        if not w:
            return self.send(chat, "Этого окна уже нет.")
        sid = transcripts.valid_sid(w.get("sid") or "")
        title = " ".join(str(name or "").split())[:projects.TITLE_MAX]
        if not sid or not title:
            return self.send(chat, "У этого чата ещё нет разговора — напишите первое сообщение, потом переименуйте."
                             if not sid else "Пустое название — нажмите ✏️ ещё раз.")
        try:
            st = projects.Store(self.cfg.data / projects.FILE, self.home)
            pid = "" if w.get("space") else (st.of_path(st.read(), w.get("path", "")) or "")
            st.set_chat(sid, pid, title=title)
        except (OSError, ValueError) as e:
            return self.send(chat, f"Не переименовал: {e}. Нажмите ✏️ ещё раз.")
        self.__dict__.get("_labels", {}).pop(wid, None)
        self.send(chat, f"✏️ Теперь чат называется «{title}».")

    def make_folder(self, name: str) -> Path:
        """Новая папка проекта в первом корне (как у модулей) + ``git init``. Общая для бота и панели."""
        path = self.module_root() / name
        if not NAME_OK.match(name):
            raise ValueError("имя: латиница в нижнем регистре, цифры, дефис (2–41 знак)")
        if path.exists():
            raise FileExistsError(f"папка {name} уже есть")
        path.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(path)], capture_output=True)
        return path

    def new_folder(self, chat: int, name: str):
        try:
            path = self.make_folder(name)
        except FileExistsError:                         # занято — предложить открыть существующую
            p, dirs = str(self.module_root() / name), self.projects()
            more = {"reply_markup": kb([[(f"📂 Открыть «{name}»", f"new:{dirs.index(p)}")]])} if p in dirs else {}
            return self.send(chat, f"Папка {name} уже есть — откройте её или нажмите 📁 и введите другое имя.", **more)
        except ValueError:
            return self.send(chat, "Имя: латиница в нижнем регистре, цифры, дефис (2–41 знак). Нажми 📁 ещё раз.")
        self.send(chat, f"📁 Создал {path} (git init).")
        self.open_session(chat, f"{name}-{time.strftime('%H%M')}", str(path))

    # ---------- условия использования ----------
    def show_terms(self, chat: int, note: str = ""):
        self.send(chat, (note + "\n\n" if note else "") + terms.bot_text(),
                  reply_markup=kb([[("✅ Принимаю", f"tm:{terms.VERSION}")]]),
                  link_preview_options={"is_disabled": True})

    def need_terms(self, u: dict) -> bool:
        """Условия ещё не приняты — показать их вместо действия. Вход в панель (``public``) не задерживаем."""
        if public(u):
            return False
        q = u.get("callback_query") or {}
        src = u.get("message") or q
        uid = (src.get("from") or {}).get("id")
        if uid is None or self.people.accepted(uid) or q.get("data", "").startswith("tm:"):
            return False
        chat = (src.get("chat") or (q.get("message") or {}).get("chat") or {}).get("id") or uid
        self.show_terms(chat)
        return True

    def on_terms(self, chat: int, uid: int, version: str):
        if version != terms.VERSION:
            return self.show_terms(chat, "Условия обновились — прочитайте новую версию.")
        self.people.accept(uid, version)
        if not self.has_country(uid):
            return self.show_country(chat, "Спасибо, условия приняты.")
        self.send(chat, f"Спасибо, условия приняты. {brand.NAME_RU}: текст, голос и файлы уходят в "
                        "активное окно. Кнопки внизу.", reply_markup=self.menu_of(uid))

    # ---------- страна человека (country.py) ----------
    def countries(self, uid) -> set[str]:
        return country.check_set(self.people.country(uid), self.cfg.region)

    def has_country(self, uid) -> bool:
        """Решение владельца 20.11: страну не спрашиваем — по умолчанию регион сервера (country.check_set); вопроса
        «ваша страна» в боте нет, как и в панели. Вернуться при платных клиентах."""
        return True

    def window_countries(self, w: dict) -> set[str]:
        """Чьё окно: метка ``@gas_pult_by`` (кто открыл), иначе первый владелец — его страны для запасных."""
        by = ""
        try:
            by = self.tmux.run("show-options", "-wqv", "-t", w["id"], "@gas_pult_by").strip()
        except (OSError, AttributeError):
            pass
        uid = int(by) if by.lstrip("-").isdigit() else (self.cfg.owners or [None])[0]
        return self.countries(uid)

    def menu_of(self, uid) -> dict:
        """Владельцу — постоянное меню; остальным бот нужен только для входа и страны — клавиатуру убираем."""
        return MENU if uid in self.cfg.owners else {"remove_keyboard": True}

    def show_country(self, chat: int, note: str = ""):
        codes = list(country.COMMON)
        rows = [[(country.name(c), f"cc:{c}") for c in codes[i:i + 3]] for i in range(0, len(codes), 3)]
        rows.append([("Другая — ввести код", "cc:other")])
        self.waiting[chat] = "cc"
        self.send(chat, (note + "\n\n" if note else "") + "🌍 Из какой страны вы работаете? Выберите кнопкой или "
                  "пришлите код страны из двух букв (например, NL). Доступно будет то, что поставщики моделей "
                  "разрешают для вашей страны.", reply_markup=kb(rows))

    def on_country(self, chat: int, uid: int, code: str):
        if code == "other":
            self.waiting[chat] = "cc"
            return self.send(chat, "Пришлите код страны из двух букв (ISO 3166-1), например NL или DE.",
                             reply_markup={"force_reply": True})
        c = country.norm(code)
        if not c:
            self.waiting[chat] = "cc"
            return self.send(chat, "Не знаю такой страны — пришлите код из двух букв, например NL.")
        self.waiting.pop(chat, None)
        rec, tell = self.people.set_country(uid, chosen=c)
        self.tell_country(uid, rec, tell)
        self.ask_phone(chat, f"Страна: {country.name(c)} ({c}).")

    def ask_phone(self, chat: int, note: str = ""):
        self.send(chat, (note + "\n\n" if note else "") + "Подтвердите страну номером телефона: нажмите «📱 Поделиться "
                  "номером» внизу. Храним только код страны номера и его хеш — сам номер не сохраняется.",
                  reply_markup=PHONE_KB)

    def on_contact(self, m: dict):
        """Контакт из «Поделиться номером»: только свой (``contact.user_id`` — тот, кто прислал)."""
        chat, uid, c = m["chat"]["id"], m["from"]["id"], m.get("contact") or {}
        if c.get("user_id") != uid:
            return self.send(chat, "Это не ваш номер. Нажмите «📱 Поделиться номером», чтобы отправить свой.",
                             reply_markup=PHONE_KB)
        rec, tell = self.people.set_country(uid, **country.phone_record(c.get("phone_number", ""), self.cfg.data))
        self.tell_country(uid, rec, tell)
        cc = rec.get("phone_cc") or "не определён"
        done = "Номер подтверждён: код страны " + cc + "."
        if uid not in self.cfg.owners:
            done += " Вернитесь в панель."
        self.send(chat, done, reply_markup=self.menu_of(uid))

    def tell_country(self, uid: int, rec: dict, tell: bool):
        if not tell:
            return
        p = next((x for x in self.people.list() if x["id"] == uid), {})
        who = p.get("name") or (f"@{p['username']}" if p.get("username") else "человек")
        self.broadcast(country.notice(who, uid, rec), kind="people")

    def country_update(self, u: dict) -> bool:
        """От участников и наблюдателей бот принимает только страну: кнопки, код, контакт, «Позже», /start phone."""
        if q := u.get("callback_query"):
            return q.get("data", "").startswith(("cc:", "tm:"))
        m = u.get("message") or {}
        t = (m.get("text") or "").strip()
        waiting = self.waiting.get((m.get("chat") or {}).get("id")) == "cc" and t and not t.startswith("/")
        return bool(m.get("contact") or t in ("/start phone", "Позже") or waiting)

    def need_country(self, u: dict) -> bool:
        """Условия приняты, а страны нет — сначала страна (как условия). Вход в панель и сама страна — без задержки."""
        if public(u) or self.country_update(u):
            return False
        src = u.get("message") or u.get("callback_query") or {}
        uid = (src.get("from") or {}).get("id")
        if uid is None or self.has_country(uid):
            return False
        chat = (src.get("chat") or (src.get("message") or {}).get("chat") or {}).get("id") or uid
        self.show_country(chat)
        return True

    # ---------- люди ----------
    def show_people(self, chat: int):
        rest = [p for p in self.people.list() if p["role"] != "owner"]
        if not rest:
            return self.send(chat, "Кроме владельца, доступа к пульту ни у кого нет. Добавить человека: пусть откроет "
                                   "панель и нажмёт «Войти через Telegram» — я спрошу вас.")
        rows = [[(f"⛔ Отключить: {p.get('name') or p.get('username') or p['id']}", f"off:{p['id']}")] for p in rest]
        lines = [f"• {p.get('name') or '—'}" + (f" @{p['username']}" if p.get("username") else "")
                 + (" (без Telegram)" if is_guest(p["id"]) else "") + f" — {TITLES[p['role']]}"
                 + self.last_line(p.get("last")) + (", условия приняты" if self.people.accepted(p["id"]) else "")
                 + self.country_line(p.get("country")) for p in rest]
        self.send(chat, "👥 Люди пульта:\n" + "\n".join(lines) + "\n\nОтключить — доступ прекращается сразу, "
                        "любой вход человека перестаёт работать.", reply_markup=kb(rows))

    @staticmethod
    def last_line(rec: dict | None) -> str:
        """«вошёл 04.11 12:30 · iPhone · Safari» — последний вход в панель (без IP)."""
        if not (rec or {}).get("at"):
            return ""
        return f", вошёл {time.strftime('%d.%m %H:%M', time.localtime(rec['at']))} · {rec.get('device') or 'браузер'}"

    @staticmethod
    def country_line(rec: dict | None) -> str:
        """Страна в «Людях»: коды признаков; расхождение — пометкой. Номер и IP не показываем."""
        rec = rec or {}
        if not rec.get("chosen"):
            return ", страна не выбрана"
        out = (f", страна {rec['chosen']} · номер {rec.get('phone_cc') or 'не подтверждён'}"
               f" · IP {rec.get('ip_cc') or 'нет данных'}")
        return out + (" — ⚠️ признаки расходятся" if rec.get("mismatch") else "")

    def switch_off(self, chat: int, arg: str):
        """off:<id> — спросить; off:yes:<id> — отключить (роль и согласие удаляются)."""
        yes, _, uid = arg.rpartition(":")
        if not uid.lstrip("-").isdigit():
            return
        p = next((x for x in self.people.list() if x["id"] == int(uid) and x["role"] != "owner"), None)
        if not p:
            return self.send(chat, "Этого человека уже нет в списке.")
        who = p.get("name") or p.get("username") or uid
        if yes != "yes":
            return self.send(chat, f"Отключить {who}? Доступ к пульту прекратится сразу.",
                             reply_markup=kb([[("Да, отключить", f"off:yes:{uid}"), ("Нет", "noop:")]]))
        self.people.remove(int(uid))
        self.web_sessions().drop(int(uid))                 # сессии браузера и ссылки для входа — сразу
        invites.drop_for(int(uid))
        self.send(chat, f"Готово: {who} отключён(а) — вход больше не работает.")

    # ---------- обработчики ----------
    def on_callback(self, q: dict):
        chat = q["message"]["chat"]["id"] if q.get("message") else q["from"]["id"]
        self.api("answerCallbackQuery", callback_query_id=q["id"])
        kind, _, arg = q.get("data", "").partition(":")
        send = self.to(chat)
        if kind == "noop":
            return
        if kind == "mt":                                   # протокол встречи: предупредил, готово, продолжение…
            return self.meeting_button(chat, arg)
        if kind == "lg":                                   # человек подтверждает вход в панель из своего Telegram
            verdict, _, nonce = arg.partition(":")
            uid = q["from"]["id"]
            if verdict == "ok" and not self.people.role(uid):
                return send("Доступа к пульту нет.")
            if not self.logins.decide(nonce, uid, verdict == "ok"):
                return send("Ссылка входа устарела — нажмите «Войти через Telegram» в браузере ещё раз.")
            return send("✅ Вход подтверждён — вернитесь в браузер." if verdict == "ok" else "Вход отклонён.")
        if kind == "cf":                                   # «✅ Подтвердить вход» под кодом подтверждения (21.11)
            ok = TgConfirm(Auth(self.cfg.data / "web_sessions.json")).approve(
                arg, q["from"]["id"], self.cfg.owners)
            if ok and q.get("message"):                    # код в чате больше не нужен — убираем его из сообщения
                with suppress(TelegramError):
                    self.api("editMessageText", chat_id=chat, message_id=q["message"]["message_id"],
                             text="✅ Вход подтверждён — вернитесь в панель.")
                return None
            return send("✅ Вход подтверждён — вернитесь в панель." if ok else
                        "Подтверждение устарело — в панели нажмите «Прислать новый код».")
        if kind == "lk":                                   # гость привязывает свой Telegram (из панели)
            verdict, _, nonce = arg.partition(":")
            return self.link_done(chat, q["from"], verdict, nonce)
        if kind == "dm":                                   # демо предложения — изолированно, кому угодно
            return self.on_demo(q, arg)
        if q["from"]["id"] not in self.cfg.owners and kind not in ("tm", "cc"):
            return                                         # участникам кнопки бота — только условия и страна
        if kind == "pp":                                   # владелец решает, пускать ли человека
            return self.grant(chat, arg)
        if kind == "bt":                                   # «➕ Добавить» к запасу пространства — на сколько
            return self.budget_offer(chat, arg)
        if kind == "ba":                                   # … пополнить на выбранную сумму
            return self.budget_add(chat, arg, q["from"]["id"])
        if kind == "pt":                                   # … тестировщиком в демо-пространстве: какое
            return self.pick_space(chat, arg)
        if kind == "ps":
            return self.grant_space(chat, arg)
        if kind == "tm":                                   # «Принимаю» под условиями использования
            return self.on_terms(chat, q["from"]["id"], arg)
        if kind == "cc":                                   # выбор страны
            return self.on_country(chat, q["from"]["id"], arg)
        if kind == "ppl":
            return self.show_people(chat)
        if kind == "off":                                  # «Отключить человека» (только владелец — как всё, кроме lg:)
            return self.switch_off(chat, arg)
        if kind == "rs":                                   # «Отправить»: наш текст висит в поле ввода — Enter
            wid, _, h = arg.rpartition(":")
            return send(self.push_enter(wid, h))
        if kind == "hint":                                 # 💡 под ответом — отправить подсказку Claude
            wid, h = self.hints.get(int(arg), ("", "")) if arg.isdigit() else ("", "")
            w = self.tmux.window(wid) if wid else None
            if not w:
                return send("Подсказка устарела или окна уже нет.")
            self.to_claude(w, h)
            return send(f"→ [{self.label(w)}]: {h}", wid=w["id"])
        if kind == "dg":
            return self.on_digest(chat, arg)
        if kind == "md":                                   # модули-агенты: описание, создание пространства
            return self.on_module(chat, arg)
        if kind == "of":                                   # пространство для человека с предложения (владелец)
            return self.offer_space(chat, arg)
        if kind == "cost":                                 # пауза по расходу: продолжить или остановить (владелец)
            act, _, wid = arg.partition(":")
            try:
                return send(self.cost_decide(wid, act))
            except LookupError as e:
                return send(f"Уже решено: {e}.")
        if kind == "su":                                   # мастер: вход в Claude, проверка — только владельцу
            if not allowed(self.people.role(q["from"]["id"]), "owner"):
                return send("Это может только владелец.")
            return self.on_setup(chat, arg)
        if kind == "mk":
            self.waiting[chat] = "name"
            return send("Имя новой папки (латиница, дефис), например: shop-bot", reply_markup={"force_reply": True})
        if kind in ("new", "tnew"):         # tnew: «<idx>|GAS-123» — сессия по задаче
            idx, _, task = arg.partition("|")
            dirs = self.projects()
            if not idx.isdigit() or int(idx) >= len(dirs):
                return send("Список папок изменился — открой 🆕 Новая ещё раз.")
            path = dirs[int(idx)]
            base = task.lower() if task else (os.path.basename(path) if path != self.home else "home")
            return self.open_session(chat, f"{base}-{time.strftime('%H%M')}", path,
                                     self.cfg.task_prompt.format(task=task) if task else None)
        if kind == "set":
            key, _, val = arg.partition("=")
            if key == "voice_always":
                self.set_state(voice_always=not self.state()["voice_always"])
            elif ((key == "notify" and val in NOTIFY)
                  or (key == "voice" and val in catalog.selectable(self.cfg.personal_voices))):
                self.set_state(**{key: val})
            return self.show_settings(chat)
        if kind in ("vp", "vs", "vi"):                     # голос: послушать / выбрать / как установить
            return self.on_voice(chat, kind, arg, q)
        if kind == "say":
            a = self.answers.get(int(arg)) if arg.isdigit() else None
            return self.say(chat, a[1]) if a else send("Этот ответ уже забыт — открой 💬 Последний ответ.")
        if kind == "cmd":
            if not (w := self.need_active(chat)):
                return
            if arg.startswith("/model"):
                return self.slash(chat, w, arg)
            cmds = self.command_list()
            if not arg.isdigit() or int(arg) >= len(cmds):
                return send("Команда устарела — открой ⚡ Команды ещё раз.")
            cmd = cmds[int(arg)][1]
            if cmd == "models":
                return send(f"Модель для «{self.label(w)}»:", reply_markup=kb([
                    [(m, f"cmd:/model {m}") for m in self.cfg.models], [("Открыть меню /model", "cmd:/model")]]))
            if cmd in PROMPTS:
                return self.to_claude(w, PROMPTS[cmd])
            return self.slash(chat, w, cmd) if cmd.startswith("/") else self.to_claude(w, cmd)
        if kind in ("tw", "twok"):          # ⌨️ Открыть в терминале: команде нужен ввод (twok — после подтверждения)
            return self.term_open(chat, arg, kind == "twok")
        if kind in ("run", "runok"):        # ▶️ Выполнить (runok — после подтверждения опасной)
            return self.cmds.run(arg, kind == "runok", send, kb, send_file=lambda name, data: self.api(
                "sendDocument", chat_id=chat, caption="Весь вывод команды", files={"document": (name, data)}))
        if kind == "key":                   # кнопки 1/2/3/↑/↓/⏎/Esc под экраном диалога
            wid, _, key = arg.partition("|")
            if key not in {k for _, k in KEYS}:
                return
            if not self.tmux.window(wid):
                return send("Этого окна уже нет.")
            self.product_pick(q["from"]["id"], wid, n=key if key.isdigit() else "", key="" if key.isdigit() else key)
            return self.tmux.keys(wid, key)
        if kind == "tk":                                   # задачи владельца: tk:done:<id> / tk:undo:<id>
            act, _, tid = arg.partition(":")
            try:
                x = self.tasks.update(tid, {"status": "done" if act == "done" else "todo"})
            except (LookupError, ValueError) as e:
                return send(f"Не вышло: {e}.")
            send(f"{'✅' if x['status'] == 'done' else '↩️'} «{x['title']}» — {tasks.STATUS_TITLES[x['status']]}.")
            return self.show_tasks(chat)
        if kind == "rc":                                   # «Не продолжать» после лимита подписки
            self.set_state(limit_retries=limitretry.cancel(self.state(), arg))
            return send("Хорошо, сама не продолжу.")
        if kind == "nd":                                   # «Сообщить по готовности» из строки статуса
            return send(self.ask_notify_done(arg, chat))
        if kind == "nl":                                   # уровень уведомлений окна (notifylevel.py)
            wid, _, lv = arg.partition("|")
            if not self.tmux.window(wid):
                return send("Этого окна уже нет.")
            try:
                self.set_state(notify_levels=notifylevel.updated(self.state(), wid, lv))
            except ValueError as e:
                return send(str(e))
            return send(f"🔔 Уведомления этой сессии: {notifylevel.TITLES.get(lv, 'как в настройках')}.")
        w = self.tmux.window(arg)
        if not w:
            return send("Этого окна уже нет.")
        if kind == "stop":                                 # «Остановить» — Esc в окно, только после «Да»
            return send(f"Остановить текущий ход в «{self.label(w)}»? Claude получит Esc — как кнопка Esc под экраном.",
                        reply_markup=kb([[("Да, остановить", f"key:{w['id']}|Escape"), ("Нет", "noop:")]]))
        if kind == "act":
            self.set_state(active=w["id"])
            send(f"✅ Пишу в «{self.label(w)}» ({self.short(w['path'])})."
                 + ("\n⚠️ У окна свой Telegram-бот — ответы придут туда, а не сюда." if w["channel"] else ""))
        elif kind == "yes":
            self.to_claude(w, "да")
            self.product("yes", q["from"]["id"], via="bot")
        elif kind == "w":
            lv = notifylevel.level(self.state(), w["id"])
            send(f"«{self.label(w)}» · {w['path']}\n🔔 Уведомления: {notifylevel.TITLES[lv]}", reply_markup=kb([
                [("🔀 Сделать активной", f"act:{w['id']}")],
                [(("✅ " if lv == x else "") + t, f"nl:{w['id']}|{x}")
                 for x, t in (("all", "🔔 Все"), ("input", "❓ Вопросы"), ("muted", "🔕 Тихо"))],
                [("📺 Экран", f"scr:{w['id']}"), ("💬 Последний ответ", f"last:{w['id']}")],
                [("✏️ Переименовать", f"ren:{w['id']}"), ("⛔ Завершить", f"ask:{w['id']}")]]))
        elif kind == "ren":
            self.waiting[chat] = f"ren:{w['id']}"
            send(f"Новое название для «{self.label(w)}»:", reply_markup={"force_reply": True})
        elif kind == "scr":
            self.send_screen(chat, w, "экран:")
        elif kind == "last":
            text = harness.of(w).last_answer(w["path"], self.home_of(w), w.get("sid") or "")
            if not text:
                return send("Ответов Claude в этой папке не нашёл.")
            send(text, wid=w["id"], reply_markup=kb([[("🔊", f"say:{self.remember(w, text)}")]]))
        elif kind == "ask":
            send(f"Завершить «{self.label(w)}»? Claude выйдет штатно, переписка сохранится.",
                 reply_markup=kb([[("Да, завершить", f"close:{w['id']}"), ("Нет", "noop:")]]))
        elif kind == "close":
            self.close(chat, w)
        elif kind == "fclose":                             # «Закрыть принудительно»: фоновые задачи остановятся
            self.tmux.kill(w["id"])
            self.focus.end_window(w["id"])
            send(f"«{self.label(w)}» закрыта принудительно. Переписка — в журнале, «Продолжить» в панели её поднимет.")

    # ---------- мастер: Claude Code без оператора (setup.py) ----------
    def setup_status(self) -> dict:
        try:
            return setup.status(self.cfg.claude)
        except Exception as e:                             # проверка не должна ронять бота
            print("setup:", e, flush=True)
            return {"ready": True, "claude": {"installed": True}, "checks": [], "doc": setup.DOC_URL}

    def panel_url(self, view: str = "") -> str:
        """Адрес панели — из кнопки «📱 Панель» владельца (его ставит ``gas-pult webapp --url``); нет — пусто."""
        try:
            mb = self.api("getChatMenuButton", chat_id=self.cfg.owners[0])
        except TelegramError:
            return ""
        url = (mb.get("web_app") or {}).get("url", "") if mb.get("type") == "web_app" else ""
        return url + (("&" if "?" in url else "?") + f"view={view}" if url and view else "")

    def setup_kb(self, st: dict) -> dict:
        """Кнопки мастера. Интеграции и ключи — экраны панели (кнопка Mini App); панели нет — подсказка текстом."""
        panel = self.panel_url("integrations")
        rows = []
        if st["claude"].get("installed"):
            rows.append([{"text": "🔑 Войти в Claude", "callback_data": "su:login"}])
        rows.append([{"text": "🔌 Подключить интеграции", "web_app": {"url": panel}} if panel else
                     {"text": "🔌 Подключить интеграции", "callback_data": "su:int"}])
        rows.append([{"text": "🗝 Ключ провайдера", "web_app": {"url": panel}} if panel else
                     {"text": "🗝 Ключ провайдера", "callback_data": "su:keys"}])
        rows.append([{"text": "🩺 Проверка", "callback_data": "su:check"},
                     {"text": "📖 Инструкция", "url": st.get("doc") or setup.DOC_URL}])
        return {"inline_keyboard": rows}

    def show_setup(self, chat: int, st: dict | None = None):
        st = st or self.setup_status()
        if not st["claude"].get("installed"):
            head = (f"🧩 Claude Code на сервере не установлен. Установите его ({setup.INSTALL_URL}) и нажмите "
                    "«Проверка». Сессии на моделях других поставщиков тоже идут через Claude Code.")
        elif st["ready"]:
            head = "✅ Claude Code готов: установлен, вход выполнен."
        else:
            head = ("🧩 Claude Code установлен, но вход не выполнен. «Войти в Claude» — пульт откроет вход, пришлёт "
                    "ссылку и попросит код со страницы. Не получается — «Инструкция».")
        self.send(chat, head + "\n\n" + setup.text(st), reply_markup=self.setup_kb(st))

    def on_setup(self, chat: int, arg: str):
        send = self.to(chat)
        if arg == "login":
            return self.setup_login(chat)
        if arg == "cancel":
            self.waiting.pop(chat, None)
            self.login.cancel()
            return send("Вход отменён, окно входа закрыто.")
        if arg == "check":
            return self.show_setup(chat)
        if arg in ("int", "keys"):
            what = ("Интеграции (Notion, GitHub, почта…)" if arg == "int" else
                    "Ключи поставщиков моделей (OpenRouter, GLM, DeepSeek)")
            return send(f"{what} подключаются в панели: «Подключения». Панель запускается командой "
                        "gas-pult webapp --url https://<ваш адрес> (или --tunnel) — после этого у бота появится "
                        "кнопка «📱 Панель». Подробно — docs/MINI_APP.md в репозитории."
                        + ("\n\nПоставщик — только тот, что поддерживает страну, откуда идёт работа. Для российских "
                           "каналов (MAX, VK) — не Claude: Россия не входит в список стран Anthropic. Правила — "
                           "docs/COMPLIANCE.md." if arg == "keys" else ""))
        return None

    def setup_login(self, chat: int):
        send = self.to(chat)
        send("⏳ Запускаю вход в Claude Code (claude auth login) в отдельном окне tmux — до 20 секунд…")
        try:
            st = self.login.start()
        except (RuntimeError, OSError, ValueError) as e:
            return send(f"Не вышло: {e}\nВойти вручную — {setup.DOC_URL}")
        if st.get("done"):
            return self.setup_result(chat, self.login.finish(st))
        if not st["url"]:
            return send("Claude Code не показал ссылку входа. Экран окна:\n\n" + "\n".join(st.get("lines") or ["—"])
                        + f"\n\nПопробуйте ещё раз или войдите вручную — {setup.DOC_URL}",
                        reply_markup=self.setup_kb(self.setup_status()))
        self.waiting[chat] = "code"
        send(f"1. Откройте ссылку и войдите в аккаунт Claude:\n{st['url']}\n\n2. Скопируйте код со страницы "
             "и пришлите его сюда одним сообщением.",
             reply_markup={"inline_keyboard": [[{"text": "🌐 Открыть страницу входа", "url": st["url"]}],
                                               [{"text": "✖️ Отменить вход", "callback_data": "su:cancel"}]]})

    def setup_code(self, chat: int, code: str):
        send = self.to(chat)
        try:
            r = self.login.send_code(code)
        except ValueError as e:
            self.waiting[chat] = "code"
            return send(f"{e}. Пришлите код ещё раз.")
        except LookupError as e:
            return send(f"{e}.", reply_markup=self.setup_kb(self.setup_status()))
        return self.setup_result(chat, r)

    def setup_result(self, chat: int, r: dict):
        if r["ok"]:
            return self.send(chat, "✅ Вход в Claude выполнен. Открывайте сессию: 🆕 Новая.", reply_markup=MENU)
        self.waiting[chat] = "code"
        why = f": {r['error']}" if r.get("error") else ""
        self.send(chat, f"❌ Вход не подтвердился{why}.\n\nЭкран окна:\n" + "\n".join(r.get("lines") or ["—"])
                  + f"\n\nПришлите код ещё раз или войдите вручную — {setup.DOC_URL}",
                  reply_markup={"inline_keyboard": [[{"text": "🔑 Начать вход заново", "callback_data": "su:login"}],
                                                    [{"text": "📖 Инструкция", "url": setup.DOC_URL}]]})

    # ---------- вход в панель «через Telegram» и люди ----------
    def login_request(self, m: dict, nonce: str):
        u, send = m["from"], self.to(m["chat"]["id"])
        info = self.logins.info(nonce)
        if not info:
            return send("Ссылка входа устарела — нажмите «Войти через Telegram» в браузере ещё раз.")
        if info.get("link") is not None:                   # гость без Telegram привязывает этот Telegram
            return self.link_request(m, nonce, info)
        role = self.people.role(u["id"])
        if not role and info.get("invite") and (inv := invites.redeem(info["invite"], u["id"])):
            role = self.invited(u, inv)                    # приглашение: доступ сразу, владельцу — уведомление
        if role:
            return send(f"Войти в панель пульта ({TITLES[role]})?\n\nБраузер: {info['ua'] or '—'}\n"
                        f"Адрес: {info['ip'] or '—'}\n\nЕсли входите не вы — нажмите «Это не я».",
                        reply_markup=kb([[("✅ Войти", f"lg:ok:{nonce}"), ("✖️ Это не я", f"lg:no:{nonce}")]]))
        send("У вас пока нет доступа к пульту. Я спросил владельца — когда он ответит, нажмите «Войти через Telegram» "
             "в браузере ещё раз.")
        self.ask_owner(u, info.get("offer"))

    def link_request(self, m: dict, nonce: str, info: dict):
        """«Привязать Telegram» из панели гостя: спросить человека, затем перенести запись (``People.adopt``)."""
        u, send = m["from"], self.to(m["chat"]["id"])
        p = next((x for x in self.people.list() if x["id"] == info["link"]), None)
        if not p:
            return send("Вход, к которому вы привязываете Telegram, уже отключён.")
        if self.people.role(u["id"]):
            return send("Этот Telegram уже есть в пульте — войдите через него («Войти через Telegram»).")
        send(f"Привязать этот Telegram к вашему входу «{p.get('name') or 'гость'}»? Потом входить можно будет и через "
             f"Telegram, а в этом чате появится кнопка «📱 Панель».\n\nБраузер: {info['ua'] or '—'}\n\n"
             "Если это не вы — нажмите «Это не я».",
             reply_markup=kb([[("✅ Привязать", f"lk:ok:{nonce}"), ("✖️ Это не я", f"lk:no:{nonce}")]]))

    def link_done(self, chat: int, u: dict, verdict: str, nonce: str):
        """lk:ok|no:<nonce> — перенос записи гостя под Telegram ID; его прежние сессии браузера гаснут, браузер,
        который ждёт по ``rid``, получает новую."""
        send = self.to(chat)
        info = self.logins.info(nonce)
        if not info or info.get("link") is None:
            return send("Ссылка устарела — нажмите «Привязать Telegram» в панели ещё раз.")
        if verdict != "ok":
            self.logins.decide(nonce, u["id"], False)
            return send("Хорошо, не привязываю.")
        name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x)
        try:
            rec = self.people.adopt(int(info["link"]), u["id"], name, u.get("username", ""))
        except ValueError as e:
            self.logins.decide(nonce, u["id"], False)
            return send(f"Не получилось: {e}.")
        self.web_sessions().drop(int(info["link"]))
        self.rebind_keys(int(info["link"]), u["id"])
        self.logins.decide(nonce, u["id"], True)
        self.menu_for(u["id"])
        send("✅ Telegram привязан — вернитесь в браузер. Панель теперь открывается и кнопкой «📱 Панель» внизу чата.")
        self.broadcast(f"🔗 {rec.get('name') or name} привязал(а) Telegram (@{u.get('username') or '—'}, "
                       f"ID {u['id']}) — тестировщик в пространстве «{rec.get('tenant') or '—'}».", kind="people")

    def web_sessions(self) -> Auth:
        return Auth(self.cfg.data / "web_sessions.json")

    def rebind_keys(self, old: int, new: int):
        """Ключи входа (passkeys.json) гостя — под его Telegram ID: Face ID продолжает работать."""
        f = self.cfg.data / "passkeys.json"
        with store.locked(f):                       # панель пишет тот же файл (passkeys.Passkeys) — один замок
            d = store.load(f)
            changed = False
            for c in (d.get("creds") or {}).values():
                if c.get("uid") == old:
                    c["uid"], changed = new, True
            if str(old) in (d.get("handles") or {}):
                d["handles"][str(new)] = d["handles"].pop(str(old))
                changed = True
            if changed:
                store.save(f, d)

    def invited(self, u: dict, inv: dict) -> str:
        """Вход по приглашению (invites.py): роль и пространство из него, без ожидания владельца."""
        name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or str(u["id"])
        self.people.add(u["id"], inv["role"], name, u.get("username", ""), tenant=inv["tenant"],
                        until=invites.until_of(inv), plan=inv.get("plan", ""))
        self.menu_for(u["id"])
        self.broadcast(f"🎟 {name} (@{u.get('username') or '—'}, ID {u['id']}) вошёл по приглашению — "
                       f"{TITLES[inv['role']]}, тестировщик в пространстве «{inv['tenant']}». Убрать — «Настройки» → "
                       "«Люди».", kind="people")
        return inv["role"]

    def ask_owner(self, u: dict, offer: dict | None = None):
        """Запрос доступа владельцам: кто и, если человек пришёл со страницы предложения, — с какого и что выбрал."""
        name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or str(u["id"])
        self.requests[u["id"]] = {"name": name, "username": u.get("username", ""),
                                  **({"offer": offer} if offer else {})}
        text = f"🔐 {name} (@{u.get('username') or '—'}, ID {u['id']}) просит доступ к панели пульта."
        if offer:
            text += f"\n\n🧾 С предложения GASTECH для «{offer.get('business', '?')}» (код {offer.get('hint', '…')})."
            if offer.get("module_title"):
                text += f"\nВыбрал(а) модуль: «{offer['module_title']}»."
            if offer.get("country"):
                text += f"\nСтрана: {country.name(offer['country'])} ({offer['country']})."
            if offer.get("terms"):
                text += f"\nУсловия приняты на странице (версия {offer['terms']})."
            text += "\nСессии и модель — только после вашего решения."
        rows = [[("👤 Участник", f"pp:member:{u['id']}"), ("👁 Наблюдатель", f"pp:viewer:{u['id']}")]]
        if self.spaces():                                  # демо-пространства включены — можно пустить только туда
            rows.append([("🧪 Тестировщик в пространстве…", f"pt:{u['id']}")])
        self.broadcast(text, kind="people", reply_markup=kb([*rows, [("✖️ Отказать", f"pp:no:{u['id']}")]]))

    # ---------- тестировщики демо-пространств (задача 31, docs/TENANTS.md) ----------
    def spaces(self) -> list[dict]:
        """Пространства для выбора: функция включена и описание читается. Выключено — [] (кнопки нет)."""
        if not tenants.enabled():
            return []
        return [t for s in tenants.slugs() if (t := tenants.load(s))]

    # ---------- команде нужен ввод — окно терминала панели (termwin.py, задача 47) ----------
    def term_open(self, chat: int, cid: str, confirmed: bool):
        """«⌨️ Открыть в терминале»: окно ``gp-term`` с командой; пароль — в панели в браузере или в Termius."""
        c = self.cmds.get(cid)
        if not c:
            return self.send(chat, "Эта команда уже забыта — попроси Claude прислать её снова.")
        if in_space(c):
            return self.send(chat, "🔒 " + SPACE_RUN[0].upper() + SPACE_RUN[1:] + ".")
        if DANGER.search(c["cmd"]) and not confirmed:
            return self.send(chat, "⚠️ Команда меняет или удаляет данные:\n<pre>"
                             + html.escape(c["cmd"][:1500]) + "</pre>", parse_mode="HTML",
                             reply_markup=kb([[("⚠️ Да, открыть в терминале", f"twok:{cid}"), ("Отмена", "noop:")]]))
        try:
            wid = termwin.open_window(self.tmux, c["cmd"], c.get("cwd"))
        except (ValueError, RuntimeError, OSError) as e:
            return self.send(chat, f"Не вышло: {e}")
        url = self.panel_url()
        link = (url + ("&" if "?" in url else "?") + "term=" + urllib.parse.quote(wid)) if url else ""
        self.send(chat, f"⌨️ Команда запущена в окне «{termwin.WINDOW}» ({wid}) на сервере и ждёт ввода. Пароль "
                        "вводите там: в панели в браузере (кнопка ниже) или в Termius — tmux select-window -t "
                        f"{wid}. В Telegram пароль не присылайте.",
                  **({"reply_markup": {"inline_keyboard": [[{"text": "⌨️ Терминал в браузере", "url": link}]]}}
                     if link else {}))

    def budget_offer(self, chat: int, slug: str):
        """Сколько добавить к запасу пространства: неделя нормы, две недели, $10."""
        t = tenants.load(slug) if tenants.SLUG.match(slug or "") else None
        if not t or not t.get("budget"):
            return self.send(chat, "У пространства нет бюджета — sudo bin/pult-tenant create <slug> --budget <USD>.")
        d = t["budget"]["daily"]
        opts = [(f"+ неделя (${7 * d:g})", 7 * d), (f"+ 2 недели (${14 * d:g})", 14 * d), ("+ $10", 10.0)]
        self.send(chat, f"Сколько добавить к запасу «{t.get('title') or slug}» на этот период?",
                  reply_markup=kb([[(label, f"ba:{slug}:{usd:g}")] for label, usd in opts]))

    def budget_add(self, chat: int, arg: str, by: int):
        slug, _, usd = arg.rpartition(":")
        t = tenants.load(slug) if tenants.SLUG.match(slug or "") else None
        if not t or not t.get("budget"):
            return self.send(chat, "У пространства нет бюджета.")
        try:
            first, _ = space_budget.period(t["budget"], date.today())
            extra = space_budget.top_up(slug, float(usd), first, by)
        except ValueError as e:
            return self.send(chat, f"Не вышло: {e}")
        self.send(chat, f"✅ Запас «{t.get('title') or slug}» пополнен на ${float(usd):g} — всего пополнений в этом "
                        f"периоде ${extra:g}. Тестировщик может продолжать.")

    def pick_space(self, chat: int, uid: str):
        """pt:<uid> — выбрать пространство для тестировщика."""
        sp = self.spaces()
        if not sp:
            return self.send(chat, "Демо-пространств нет — создайте его: docs/TENANTS.md, шаг 3.")
        who = (self.requests.get(int(uid)) or {}).get("name") or uid
        rows = [[(f"🧪 {t.get('title') or t['slug']}", f"ps:{uid}:{t['slug']}")] for t in sp]
        self.send(chat, f"В каком пространстве {who} будет тестировщиком? Он увидит только его сессии — ни ваших окон, "
                        "ни папок сервера.", reply_markup=kb([*rows, [("✖️ Отказать", f"pp:no:{uid}")]]))

    def grant_space(self, chat: int, arg: str):
        """ps:<uid>:<slug> — участник, привязанный к пространству (people.json, поле tenant)."""
        uid, _, slug = arg.partition(":")
        if not uid.isdigit() or slug not in [t["slug"] for t in self.spaces()]:
            return self.send(chat, "Пространства уже нет — выберите заново.")
        req = self.requests.pop(int(uid), {})
        who = req.get("name") or uid
        self.people.add(int(uid), "member", req.get("name", ""), req.get("username", ""), tenant=slug)
        self.menu_for(int(uid))
        self.send(chat, f"Готово: {who} — тестировщик в пространстве «{slug}». Убрать — «Настройки» → «Люди».")
        self.notify(int(uid), TESTER_HELLO)

    def tester_help(self, chat: int, uid: int):
        """/help тестировщика: владельцам — кто, сессия (где ждут ответа или самая свежая), последний вопрос агента."""
        slug = self.people.tenant(uid)
        now = time.time()
        if now - self.help_calls.get(uid, 0) < testers.HELP_EVERY:
            return self.send(chat, "Владелец уже получил сообщение — он подключится. Подождите несколько минут.")
        self.help_calls[uid] = now
        person = next((p for p in self.people.list() if p["id"] == uid), {"id": uid})
        text, kbd = testers.help_message(person, slug, testers.pick(testers.windows(slug)), self.panel_url())
        self.broadcast(text, kind="people", **({"reply_markup": kbd} if kbd else {}))
        self.send(chat, "🆘 Позвал владельца пульта — он получил сообщение с вашей сессией и подключится.")

    def send_testers(self, chat: int | None = None):
        """Сводка по тестировщикам: по расписанию — владельцам (пусто — молчим), /testers — в чат."""
        text = testers.report(self.people, self.meter)
        if chat:
            return self.send(chat, text or "Тестировщиков нет.")
        return text and self.broadcast(text, kind="people")

    def send_invite(self, chat: int, slug: str):
        """/invite <пространство> [срок 1d|7d|30d|90d|365d] [входов N, 0 — без лимита] [доступ дней] (владелец):
        приглашение — QR картинкой, ссылка и короткий код в подписи. По умолчанию — 24 часа, один вход, бессрочно."""
        slug, *opt = (slug or "").split() or [""]
        ttl = next((invites.TTLS[x] for x in opt if x in invites.TTLS), invites.TTL)
        nums = [int(x) for x in opt if x.isdigit()]
        uses, access = (*nums, 0)[:2] if nums else (1, 0)          # «5» — пять входов, доступ бессрочно
        sp = self.spaces()
        if not sp:
            return self.send(chat, "Демо-пространств нет — создайте его: docs/TENANTS.md, шаг 3.")
        if slug not in [t["slug"] for t in sp]:
            return self.send(chat, "Для кого приглашение? /invite <пространство>: "
                                   + ", ".join(t["slug"] for t in sp))
        base = urllib.parse.urlsplit(self.panel_url())
        if not base.netloc:
            return self.send(chat, "Не знаю адрес панели: запустите её с --url (кнопка «📱 Панель»).")
        try:
            inv = invites.new(slug, by=chat, ttl=ttl, uses=uses, access=access)
        except ValueError as e:
            return self.send(chat, f"Приглашение: {e}. Пример: /invite {slug} 7d 0 30")
        link = f"{base.scheme}://{base.netloc}/invite/{inv['code']}"
        title = next((t.get("title") or slug for t in sp if t["slug"] == slug), slug)
        days = {v: k for k, v in invites.TTLS.items()}.get(ttl, "1d")
        cap = (f"🎟 Приглашение в «{title}» — ссылка {days}, "
               f"{'входов без лимита' if uses == 0 else 'один вход' if uses == 1 else f'до {uses} входов'}, "
               f"доступ {f'{access} дн.' if access else 'бессрочно'}; Telegram не нужен.\n\n"
               f"Наведите камеру телефона на QR или откройте ссылку:\n{link}\n\n"
               f"Или код на экране входа («Есть код приглашения?»): {inv['short']}\n\n"
               f"Отозвать: gas-pult invite revoke {inv['hint']}")
        self.api("sendPhoto", chat_id=chat, caption=cap, files={"photo": ("invite.png", qr.png_of(link))})

    def tester_start(self, chat: int, uid: int):
        """/start тестировщика: коротко, что можно, и кнопка «📱 Панель» (команды пульта ему не работают)."""
        self.menu_for(uid)
        self.send(chat, TESTER_HELLO, reply_markup={"remove_keyboard": True})

    def grant(self, chat: int, arg: str):
        role, _, uid = arg.partition(":")
        uid = int(uid)
        req = self.requests.pop(uid, {})
        who = req.get("name") or str(uid)
        if role not in ("member", "viewer"):
            self.send(chat, f"Отказано: {who}.")
            return self.notify(uid, "Владелец не дал доступ к пульту.")
        self.people.add(uid, role, req.get("name", ""), req.get("username", ""))
        self.menu_for(uid)
        self.send(chat, f"Готово: {who} — {TITLES[role]}. Отключить или поменять роль — «Настройки» → «Люди» "
                        "в панели или ⚙️ Настройки → 👥 Люди здесь.")
        self.notify(uid, f"Владелец дал доступ к пульту ({TITLES[role]}). Нажмите «Войти через Telegram» в браузере "
                         "ещё раз — или кнопку «📱 Панель» внизу этого чата.")
        if off := req.get("offer"):
            self.offer_granted(chat, uid, role, who, off)

    # ---------- предложения (offers.py): после одобрения и демо в Telegram ----------
    def offer_granted(self, chat: int, uid: int, role: str, who: str, off: dict):
        """Человек пришёл с предложения: условия и страна из мастера — его записью; номер — как обычно, в боте;
        пространство из выбранного модуля — одной кнопкой владельцу (без сессии и без модели)."""
        if off.get("terms") == terms.VERSION:
            self.people.accept(uid, terms.VERSION)
        if country.norm(off.get("country")):
            self.people.set_country(uid, chosen=country.norm(off["country"]))
            try:
                self.ask_phone(uid)
            except TelegramError as e:
                print("notify:", e, flush=True)
        mid = off.get("module", "")
        if role != "member" or not modules.ID.match(mid or ""):
            return
        try:
            m = modules.get(mid)
        except LookupError:
            return
        folder = modules.free_name(self.module_root(), m["id"])
        self.send(chat, f"🧩 {who} выбрал(а) на странице предложения модуль «{m['title']}». Создать пространство "
                        f"«{folder}»? Сессия не откроется и модель не потратится — человек откроет её сам в панели и "
                        "загрузит туда выгрузку.",
                  reply_markup=kb([[(f"✅ Создать «{folder}»", f"of:{uid}:{m['id']}")], [("Не сейчас", "noop:")]]))

    def offer_space(self, chat: int, arg: str):
        """of:<uid>:<модуль> — владелец создаёт пространство для человека с предложения (папка, без сессии)."""
        uid, _, mid = arg.partition(":")
        if not uid.isdigit() or not self.people.role(int(uid)):
            return self.send(chat, "У этого человека нет доступа — пространство не создаю.")
        try:
            path = modules.create(mid, self.module_root(), modules.free_name(self.module_root(), mid), by=int(uid))
        except (ValueError, LookupError, OSError) as e:
            return self.send(chat, f"Не создал: {e}")
        self.send(chat, f"📁 Пространство {self.short(str(path))} создано. Сессию человек откроет сам: панель → "
                        f"«Новая сессия» → папка «{path.name}»; выгрузку — туда же, кнопкой 📎.")
        self.notify(int(uid), f"📁 Для вас создано пространство «{path.name}». Откройте панель → «Новая сессия» → "
                              f"«{path.name}» и загрузите туда выгрузку (📎).")

    def demo_rate(self, uid: int) -> bool:
        now = time.time()
        self.demo_seen = {k: [t for t in v if now - t < DEMO_RATE[1]] for k, v in self.demo_seen.items()
                          if any(now - t < DEMO_RATE[1] for t in v)}
        hits = self.demo_seen.setdefault(uid, [])
        if len(hits) >= DEMO_RATE[0]:
            return False
        hits.append(now)
        return True

    def demo_of(self, tok: str) -> tuple[dict, dict, dict] | None:
        """(запись токена, предложение, модуль) — или None: токен истёк, предложение отозвано, модуля нет."""
        rec = self.offer_tg.get(tok)
        o = offers.load(rec["code"]) if rec else None
        if not o:
            return None
        try:
            return rec, o, modules.get(rec["module"])
        except LookupError:
            return None

    def offer_demo(self, m: dict, tok: str):
        """/start demo_<токен>: сценарий модуля на выдуманных данных. Ни роли, ни меню, ни сессий — только сообщения."""
        chat, uid = m["chat"]["id"], m["from"]["id"]
        if not self.demo_rate(uid):
            return self.send(chat, "Демо можно запускать не чаще 5 раз в час — попробуйте позже.")
        if not self.offer_tg.start(tok) or not (got := self.demo_of(tok)):
            return self.send(chat, DEMO_GONE)
        _, o, mod = got
        self.send(chat, f"🧪 Демо GASTECH для «{o['business']}» — модуль «{mod['title']}».\n\nДанные выдуманы для "
                        "демонстрации: ничего не отправляется, модель не вызывается. Нажимайте кнопки — покажу, что "
                        "произошло бы.")
        self.demo_step(chat, tok, o, mod, 0)

    def demo_step(self, chat: int, tok: str, o: dict, mod: dict, i: int, back: str = ""):
        steps = offers.scenario(o, mod)
        if i < len(steps):
            st = steps[i]
            rows = [[(b, f"dm:{tok}:{i}:{j}")] for j, (b, _) in enumerate(st["buttons"])]
            rows.append([("Дальше ›", f"dm:{tok}:{i}:n")])
            return self.send(chat, st["text"], reply_markup=kb(rows))
        markup = kb([[("✅ Подключить", f"dm:{tok}:f:c")], [("🔁 Посмотреть ещё раз", f"dm:{tok}:f:r")]])
        if back.startswith("https://"):
            markup["inline_keyboard"].append([{"text": "Открыть предложение", "url": back}])
        return self.send(chat, f"Так агент работал бы для «{o['business']}» каждый день — в вашем Telegram, решения "
                               "кнопками, без отправки без вашего «Да».\n\nПодключить? Владелец пульта получит запрос "
                               "и свяжется с вами.", reply_markup=markup)

    def on_demo(self, q: dict, arg: str):
        """dm:<токен>:<шаг>:<кнопка> — кнопки демо. Токен проверяется на каждое нажатие; устарел — «закончилось»."""
        chat, u = (q.get("message") or {}).get("chat", {}).get("id") or q["from"]["id"], q["from"]
        tok, _, rest = arg.partition(":")
        step, _, btn = rest.partition(":")
        got = self.demo_of(tok)
        if not got:
            return self.send(chat, DEMO_GONE)
        rec, o, mod = got
        if step == "f" and btn == "c":
            return self.demo_connect(chat, u, o, mod)
        if step == "f" and btn == "r":
            if not self.demo_rate(u["id"]) or not self.offer_tg.start(tok):
                return self.send(chat, "Демо можно запускать не чаще 5 раз в час — попробуйте позже.")
            return self.demo_step(chat, tok, o, mod, 0)
        if not step.isdigit():
            return None
        i, steps = int(step), offers.scenario(o, mod)
        if i >= len(steps):
            return self.send(chat, DEMO_GONE)
        if btn.isdigit() and int(btn) < len(steps[i]["buttons"]):
            self.send(chat, "↪️ " + steps[i]["buttons"][int(btn)][1])
        return self.demo_step(chat, tok, o, mod, i + 1, rec.get("back", ""))

    def demo_connect(self, chat: int, u: dict, o: dict, mod: dict):
        """«Подключить» из демо: обычный запрос доступа владельцу с пометкой предложения (один раз)."""
        if self.people.role(u["id"]):
            return self.send(chat, "У вас уже есть доступ к пульту — откройте панель кнопкой «📱 Панель».")
        if u["id"] in self.requests:
            return self.send(chat, "Запрос уже у владельца — когда он ответит, я напишу сюда.")
        self.ask_owner(u, {"business": o["business"], "hint": offers.hint(o["code"]), "module": mod["id"],
                           "module_title": mod["title"]})
        self.send(chat, "Запрос отправлен владельцу пульта. Когда он ответит, я напишу сюда — дальше условия, страна "
                        "и номер прямо в этом чате.")

    def notify(self, uid: int, text: str):
        try:
            self.send(uid, text)
        except TelegramError as e:
            print("notify:", e, flush=True)

    def menu_for(self, uid: int):
        """Кнопка «📱 Панель» — как у владельца (адрес панели знает только она)."""
        try:
            mb = self.api("getChatMenuButton", chat_id=self.cfg.owners[0])
            if mb.get("type") == "web_app":
                self.api("setChatMenuButton", chat_id=uid, menu_button=mb)
        except TelegramError as e:
            print("menu:", e, flush=True)

    def on_message(self, m: dict):
        chat = m["chat"]["id"]
        send = self.to(chat)
        t = (m.get("text") or m.get("caption") or "").strip()
        if t.startswith("/start demo_"):                   # демо предложения: до любых проверок доступа
            return self.offer_demo(m, t.removeprefix("/start demo_").strip())
        if t.startswith("/start login_"):
            return self.login_request(m, t.removeprefix("/start login_").strip())
        uid = (m.get("from") or {}).get("id")
        # заготовки Pult.__new__ в тестах — без reviews
        if getattr(self, "reviews", None) and uid in self.cfg.owners and self.on_review(m, t):
            return None
        if t in ("/start", "/menu") and uid not in self.cfg.owners and self.people.tenant(uid):
            return self.tester_start(chat, uid)
        if t == "/help" and uid not in self.cfg.owners and self.people.tenant(uid):
            return self.tester_help(chat, uid)
        if m.get("contact"):
            return self.on_contact(m)
        if t == "/start phone":                            # из панели: «подтвердите номер в боте»
            return self.ask_phone(chat) if self.has_country(uid) else self.show_country(chat)
        if t == "Позже":
            return send("Хорошо, номер можно подтвердить позже: /start phone.", reply_markup=self.menu_of(uid))
        if self.waiting.get(chat) == "cc" and m.get("text") and not t.startswith((*MENU_PREFIXES, "/")):
            self.waiting.pop(chat, None)
            return self.on_country(chat, uid, t)
        wait = self.waiting.pop(chat, None) or ""
        if wait == "name" and m.get("text") and not t.startswith(MENU_PREFIXES):
            return self.new_folder(chat, t.lower())
        if wait.startswith("ren:") and m.get("text") and not t.startswith(MENU_PREFIXES):
            return self.rename(chat, wait[4:], t)
        if wait.startswith("md:") and m.get("text") and not t.startswith(MENU_PREFIXES):
            return self.module_create(chat, wait[3:], t.lower())
        if wait == "code" and m.get("text") and not t.startswith(MENU_PREFIXES) and not t.startswith("/"):
            return self.setup_code(chat, t)
        if t.startswith("🆕"):
            rows = [[("📁 Новая папка…", "mk:")], [("🧩 Из модуля…", "md:list:")]]
            rows += [[(self.short(p), f"new:{i}")] for i, p in enumerate(self.projects())]
            return send("В какой папке открыть новую сессию? (или пришли номер задачи, например GAS-123)",
                        reply_markup=kb(rows))
        for prefix, fn in (("🔀", self.show_switch), ("📊", self.show_summary), ("⚡", self.show_commands),
                           ("📋", self.show_windows), ("⚙️", self.show_settings)):
            if t.startswith(prefix):
                return fn(chat)
        if t == "/digest":
            return self.send_digest(chat)
        if t == "/brief":
            self.send_brief(chat)
            return None
        if t == "/testers":
            return self.send_testers(chat)
        if t == "/selftest":
            return self.on_selftest(chat)
        if t == "/invite" or t.startswith("/invite "):
            return self.send_invite(chat, t.removeprefix("/invite").strip())
        if t == "/modules":
            return self.show_modules(chat)
        if t == "/tasks":
            return self.show_tasks(chat)
        if t in ("/start", "/menu", "/help"):
            send(f"{brand.NAME_RU}. Текст, голос и файлы уходят в активное окно. Кнопки внизу; голос — /voice, "
                 "готовые агенты — /modules.",
                 reply_markup=MENU)
            if t == "/start" and not (st := self.setup_status())["ready"]:
                self.show_setup(chat, st)
            return None
        if t == "/setup":
            return self.show_setup(chat)
        if t == "/voice":
            return self.show_voice(chat)
        task = self.task.match(t) if m.get("text") else None
        if task:
            tid = task.group(1).upper()
            rows = [[(self.short(p), f"tnew:{i}|{tid}")] for i, p in enumerate(self.projects())]
            return send(f"Задача {tid}: в какой папке открыть сессию?", reply_markup=kb(rows))
        if t in ("/meeting", "/протокол") or t.lower() in ("протокол встречи", "📝 протокол встречи"):
            return self.meeting_start(chat)
        mts = getattr(self, "meetings", None)              # бот без хранилища (собран в тесте) — встреч нет
        if mts and mts.current(chat) and not t.startswith("/"):       # идёт встреча — кусок к ней, не в сессию
            return self.meeting_piece(chat, m)
        w = self.reply_target(chat, m)
        if w is False:                                     # ответ на сообщение окна, которого нет — не подменяем
            return
        if not w and not (w := self.need_active(chat)):
            return
        if v := (m.get("voice") or m.get("audio")):
            self.react(m, "✍")
            try:
                text = voice.transcribe_any(self.api.download(v["file_id"], self.cfg.data / "inbox", "voice.ogg"),
                                            self.cfg.whisper_model, data=self.cfg.data)   # T-one, нет — whisper
            except (RuntimeError, OSError) as e:
                return send(f"Не разобрал голосовое: {e}")
            if not text:
                return send("Не разобрал голосовое — попробуй ещё раз.")
            send(f"🎙 → [{self.label(w)}]: {text}", wid=w["id"])
            return self.to_claude_live(chat, w, text)
        f = (m.get("photo") or [None])[-1] or m.get("document") or m.get("video")
        if f:
            path = self.api.download(f["file_id"], self.cfg.data / "inbox", f.get("file_name") or "photo.jpg")
            # проект с папкой на Google Диске — файл туда (<проект>/Входящие, #217); нет — остаётся в inbox
            path = drive_inbox.place(path, folder=None if w.get("space") else self.cfg.drive_folder(w.get("path", "")))
            t = f"{t or 'Посмотри файл.'}\n\nФайл из Telegram: {path}"
        if not t:
            return send("Пришли текст, голосовое или файл.")
        self.to_claude_live(chat, w, t)
        self.react(m, "👀")

    def on_review(self, m: dict, t: str) -> bool:
        """«#ревью» владельца (и продолжение длинной посылки) — файлом в inbox, не в сессию (review_inbox.py).
        True — сообщение забрано. Текст отчёта в журнал службы не пишется."""
        chat = m["chat"]["id"]
        body = review_inbox.labeled(t)
        if body is None:
            if t.startswith(MENU_PREFIXES) or not self.reviews.wants(chat, m, t):
                return False
            body, file = self.review_attachment(m, t)
            self.reviews.add(chat, m, body, file)
            self.react(m, "✍")
            return True
        body, file = self.review_attachment(m, body)
        self.reviews.start(chat, m, body, file)
        self.send(chat, review_inbox.reply(self.reviews.now()))
        return True

    def review_attachment(self, m: dict, text: str) -> tuple[str, str]:
        """Файл при «#ревью» (подпись документа или фото): скачать в inbox/review-att; текстовый (.md, .txt,
        до 1 МБ) — дописать к тексту отчёта целиком. → (текст, путь вложения или «»)."""
        f = (m.get("photo") or [None])[-1] or m.get("document")
        if not f:
            return text, ""
        att = self.reviews.inbox / review_inbox.ATT_DIR
        path = self.api.download(f["file_id"], att, f.get("file_name") or "photo.jpg")
        os.chmod(path, 0o600)
        mime = f.get("mime_type") or ""
        if (mime.startswith("text/") or path.suffix.lower() in (".md", ".txt")) and path.stat().st_size <= 1 << 20:
            try:
                return "\n\n".join(x for x in (text, path.read_text(encoding="utf-8").strip()) if x), str(path)
            except (OSError, UnicodeDecodeError):
                pass
        return text, str(path)

    def handle(self, u: dict):
        chat = (u.get("message") or u.get("callback_query", {}).get("message") or {}).get("chat", {}).get("id")
        try:
            src = u.get("message") or u.get("callback_query") or {}
            self.actor.uid = (src.get("from") or {}).get("id")
            if self.need_terms(u) or self.need_country(u):
                if "callback_query" in u:
                    self.api("answerCallbackQuery", callback_query_id=u["callback_query"]["id"])
                return
            if "callback_query" in u:
                self.on_callback(u["callback_query"])
            else:
                self.on_message(u["message"])
        except Denied as e:
            if chat:
                self.send(chat, str(e))
        except Exception as e:
            if chat:
                self.send(chat, f"Ошибка: {self.api.redact(e)}")

    def admitted(self, u: dict) -> bool:
        """Что бот вообще обрабатывает: владельцы — всё; незнакомые — вход в панель и демо предложения (``public``);
        люди с ролью — ещё и страну."""
        src = u.get("message") or u.get("callback_query") or {}
        uid = src.get("from", {}).get("id")
        return uid in self.cfg.owners or public(u) or bool(self.people.role(uid) and self.country_update(u)) or \
            tester_start(u, self.people)

    def run(self):
        me = self.api("getMe")
        print(f"gas-pult: @{me['username']} · сессия tmux «{self.cfg.session}» · владельцев: {len(self.cfg.owners)}",
              flush=True)
        st = self.setup_status()
        if not st["ready"]:                                # не падаем: бот работает, /start покажет мастер
            why = "не установлен" if not st["claude"]["installed"] else "— вход не выполнен"
            print(f"gas-pult: Claude Code {why} · /start в боте — мастер входа", flush=True)
        threading.Thread(target=self.monitor, daemon=True).start()
        threading.Thread(target=self.digest_loop, daemon=True).start()
        threading.Thread(target=self.selftest_loop, daemon=True).start()
        threading.Thread(target=self.modules_loop, daemon=True).start()
        offset = None
        while True:
            try:
                for u in self.api("getUpdates", timeout=60, **({"offset": offset} if offset else {})):
                    offset = u["update_id"] + 1
                    if not self.admitted(u):               # чужих — молча; людям — страна
                        continue
                    threading.Thread(target=self.handle, args=(u,), daemon=True).start()
            except Exception as e:
                print("poll:", self.api.redact(e), flush=True)
                time.sleep(5)
