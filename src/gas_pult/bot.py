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
import html  # noqa: F401 — bot.html: в botparts/screens.py, имя живо
import json  # noqa: F401 — bot.json: в botparts/windows.py, имя живо
import os
import re
import subprocess  # noqa: F401 — bot.subprocess: в botparts/windows.py и botparts/screens.py, имя живо
import threading
import time
import urllib.parse  # noqa: F401 — bot.urllib: в botparts/screens.py, имя живо
import uuid  # noqa: F401 — bot.uuid: в botparts/windows.py и botparts/screens.py, имя живо
from contextlib import contextmanager, suppress  # noqa: F401 — bot.contextmanager: в botparts/windows.py, имя живо
from datetime import date, datetime  # noqa: F401 — bot.date, bot.datetime: в botparts/screens.py, имя живо
from functools import cached_property
from pathlib import Path  # noqa: F401 — bot.Path: в botparts/windows.py и botparts/screens.py, имя живо
from typing import ClassVar  # noqa: F401 — bot.ClassVar: в botparts/screens.py, имя живо

from gas_pult import (
    activity,
    ago,
    alerts,  # noqa: F401 — bot.alerts: монитор в botparts/monitor.py, имя живо
    brand,
    brief,
    chainfuse,  # noqa: F401 — bot.chainfuse: монитор в botparts/monitor.py, имя живо
    chatlog,
    country,  # noqa: F401 — bot.country: в botparts/windows.py и botparts/screens.py, имя живо
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
    invites,  # noqa: F401 — bot.invites: в botparts/screens.py, имя живо
    limitretry,
    meetings,
    models,  # noqa: F401 — bot.models: в botparts/windows.py и botparts/screens.py, имя живо
    modules,
    notifylevel,
    notifyroute,  # noqa: F401 — bot.notifyroute: Telegram в botparts/telegram.py, имя живо
    offers,
    people,  # noqa: F401 — bot.people: в botparts/windows.py, имя живо
    projects,  # noqa: F401 — bot.projects: в botparts/windows.py и botparts/screens.py, имя живо
    providers,  # noqa: F401 — bot.providers: выбор голоса в botparts/voice.py, имя живо
    qr,  # noqa: F401 — bot.qr: в botparts/screens.py, имя живо
    review_inbox,
    secrets_guard,  # noqa: F401 — bot.secrets_guard: в botparts/windows.py, имя живо
    selftest,  # noqa: F401 — bot.selftest: монитор в botparts/monitor.py, имя живо
    setup,
    space_budget,  # noqa: F401 — bot.space_budget: в botparts/screens.py, имя живо
    spaces,  # noqa: F401 — bot.spaces: Telegram в botparts/telegram.py, имя живо
    speech,  # noqa: F401 — bot.speech: озвучка в botparts/voice.py, имя живо
    store,  # noqa: F401 — bot.store: в botparts/screens.py, имя живо
    tasks,
    tenants,  # noqa: F401 — bot.tenants: в botparts/screens.py, имя живо
    terms,  # noqa: F401 — bot.terms: в botparts/screens.py, имя живо
    termwin,  # noqa: F401 — bot.termwin: в botparts/screens.py, имя живо
    testers,  # noqa: F401 — bot.testers: в botparts/screens.py, имя живо
    tglinks,  # noqa: F401 — bot.tglinks: Telegram в botparts/telegram.py, имя живо
    tgroutes,
    transcripts,  # noqa: F401 — bot.transcripts: в botparts/windows.py и botparts/screens.py, имя живо
    uploads,
    usage,
    voice,
    webpush,  # noqa: F401 — bot.webpush: Telegram в botparts/telegram.py, имя живо
)
from gas_pult import tmux as tmux_mod  # noqa: F401 — bot.tmux_mod: монитор в botparts/monitor.py, имя живо
from gas_pult.botparts.base import HINT, QUESTION, AwaitsChoice, Denied, NotReady  # noqa: F401 — окна и экраны в botparts/; bot.<имя> живы
from gas_pult.botparts.meetings import MeetingsPart
from gas_pult.botparts.monitor import NOISE, MonitorPart, dialog_hash  # noqa: F401 — bot.NOISE, bot.dialog_hash живы
from gas_pult.botparts.screens import (  # noqa: F401 — bot.<имя>: экраны в botparts/screens.py, имена живы
    COMMANDS,
    DEMO_GONE,
    DEMO_RATE,
    NAME_OK,
    NOTIFY,
    PHONE_KB,
    TESTER_HELLO,
    TRIAGE_NOTE,
    ScreensPart,
    _clip,
    public,
)
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
from gas_pult.commands import DANGER, SPACE_RUN, TAIL, Commands, Journal, fail_key, in_space, triage_text  # noqa: F401 — окна и экраны в botparts/; bot.<имя> живы
from gas_pult.config import Config
from gas_pult.humanize import BUSY, DIALOG  # noqa: F401 — признаки экрана в humanize.py; bot.BUSY, bot.DIALOG живы
from gas_pult.people import TITLES, People, allowed, has_telegram, is_guest  # noqa: F401 — окна и экраны в botparts/; bot.<имя> живы
from gas_pult.telegram import Api, TelegramError, kb
from gas_pult.tmux import Tmux, prompt_draft  # noqa: F401 — bot.prompt_draft: в botparts/windows.py, имя живо
from gas_pult.tmux import is_ours as tmux_is_ours  # noqa: F401 — bot.tmux_is_ours: в botparts/windows.py, имя живо
from gas_pult.voice import catalog
from gas_pult.webauth import Auth, TgConfirm, TgLogins


def tester_start(u: dict, ppl) -> bool:
    """/start и /menu от тестировщика демо-пространства — бот отвечает инструкцией (остальное ему не работает)."""
    m = u.get("message") or {}
    uid = (m.get("from") or {}).get("id")
    return (m.get("text") or "").strip() in ("/start", "/menu", "/help") and bool(ppl.tenant(uid))


MENU_PREFIXES = ("🆕", "🔀", "📊", "⚡", "📋", "⚙️")
PROMPTS = {"handoff": "Прочитай HANDOFF.md (или README) этого проекта и кратко доложи: состояние, блокеры, "
                      "следующий шаг."}


class Pult(TelegramPart, WindowsPart, ScreensPart, MonitorPart, MeetingsPart, VoicePart):
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
            t = uploads.mark_bare(f"{t or uploads.DEFAULT}\n\nФайл из Telegram: {path}")   # без подписи — пометка
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
        getattr(self.tmux, "spawn_hook", lambda: None)()   # окно из окна — видно по фокус-ссылке (spawned.py)
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
