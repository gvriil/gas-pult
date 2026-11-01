"""Пульт: Telegram ⇄ окна Claude Code в tmux.

Меню: 🆕 Новая · 🔀 Переключить · 📊 Сводка · ⚡ Команды · 📋 Окна · ⚙️ Настройки.
- Текст, голосовое, фото и файлы уходят в активное окно (голос — через faster-whisper).
- Монитор: любой законченный ход Claude и любой диалог на экране (разрешения, /model, /mcp) приходят сами,
  с кнопками 🔊 ✅ ✏️ и 1/2/3/↑/↓.
- Номер задачи (GAS-123) — новая сессия по задаче. Команды из ответа — отдельными сообщениями с ▶️.
Пускает только владельцев из ``owners``; от остальных принимает лишь вход в панель «через Telegram»
(``/start login_…`` и кнопки «Войти / Это не я») — остальное молча игнорирует.
До согласия с условиями использования (``terms.py``) на любое действие бот отвечает текстом условий и кнопкой
«Принимаю»; вход в панель через Telegram это не задерживает — условия человек примет в самой панели.
После условий — страна (``country.py``): выбор кнопками или кодом, затем «Поделиться номером» (берём код страны,
номер — только хешем). Участники и наблюдатели пишут боту только это (и вход в панель); остальное — как раньше.
Новая сессия и текст в окно — только если поставщик окна разрешён для стран человека; иначе — ``country.DENY``.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from gas_pult import country, digest, fallback, models, people, setup, terms, transcripts, voice
from gas_pult.commands import TAIL, Commands, Journal, fail_key, triage_text
from gas_pult.config import Config
from gas_pult.people import TITLES, People, allowed
from gas_pult.telegram import Api, TelegramError, kb
from gas_pult.tmux import Tmux
from gas_pult.voice import catalog
from gas_pult.webauth import TgLogins

# Меню и вопросы Claude Code узнаём по подсказке внизу («Enter to confirm/select», «Esc to …»). Нумерованная строка
# сама по себе — не признак: Claude Code показывает ваши прошлые сообщения с «❯», и «❯ 1. Сделай…» — это вы, не меню.
HINT = r"(?:[^·\n]{1,40}·\s*)*"          # подсказки внизу меню могут идти после других: «↑/↓ to navigate · Enter to …»
DIALOG = re.compile(r"^\s*(Do you (want|trust)|Select model)|^\s*" + HINT +
                    r"(Enter to (confirm|select)|Esc to (cancel|close|go back))", re.M)
BUSY = re.compile(r"esc to interrupt", re.I)
# Готовность окна к тексту. Вопрос Claude (разрешение, выбор пункта): Esc там значит «нет» — за человека не отвечаем.
# Меню и панели (/status, /model, /config, /usage…): Esc безопасен — закрываем, иначе текст уйдёт в меню и пропадёт.
QUESTION = re.compile(r"^\s*Do you (want|trust)|^\s*" + HINT + r"Enter to (confirm|select)", re.M)
PANEL = re.compile(r"^\s*" + HINT + r"Esc to (cancel|close|exit|go back)|Settings\s+Status\s+Config", re.I | re.M)
PROMPT = re.compile(r"^\s*❯(?!\s*\d\.)", re.M)


# Строка статуса и таймеры меняются каждые секунды — в отпечаток меню их не берём, иначе «изменение» без конца.
NOISE = re.compile(r"🤖|ctx used|⏵⏵|esc to interrupt|^\s*[✻✶✳✢·*]\s", re.I)


def dialog_hash(scr: str) -> str:
    return hashlib.md5("\n".join(x for x in scr.splitlines() if not NOISE.search(x)).encode()).hexdigest()


def public(u: dict) -> bool:
    """Что принимаем и от незнакомых: начало входа в панель и кнопки подтверждения входа."""
    if m := u.get("message"):
        return (m.get("text") or "").startswith("/start login_")
    return (u.get("callback_query") or {}).get("data", "").startswith("lg:")


class NotReady(RuntimeError):
    """Окно не готово принять текст — сообщение не вставляем вслепую, а говорим человеку почему."""


class Denied(RuntimeError):
    """Поставщик окна не разрешён для стран человека — отвечаем ровно ``country.DENY``."""


PHONE_KB = {"keyboard": [[{"text": "📱 Поделиться номером", "request_contact": True}], [{"text": "Позже"}]],
            "resize_keyboard": True, "one_time_keyboard": True}
MENU = {"keyboard": [[{"text": "🆕 Новая"}, {"text": "🔀 Переключить"}, {"text": "📊 Сводка"}],
                     [{"text": "⚡ Команды"}, {"text": "📋 Окна"}, {"text": "⚙️ Настройки"}]],
        "resize_keyboard": True, "is_persistent": True}
MENU_PREFIXES = ("🆕", "🔀", "📊", "⚡", "📋", "⚙️")
KEYS = [("1", "1"), ("2", "2"), ("3", "3"), ("↑", "Up"), ("↓", "Down"), ("⏎", "Enter"), ("Esc", "Escape")]
COMMANDS = [("🧠 Модель", "models"), ("🔌 MCP", "/mcp"), ("📏 Контекст", "/context"),
            ("🗜 Сжать", "/compact"), ("🧹 Очистить", "/clear"), ("ℹ️ Статус", "/status"),
            ("🔐 Разрешения", "/permissions"), ("💰 Расход", "/cost"), ("📖 HANDOFF", "handoff")]
PROMPTS = {"handoff": "Прочитай HANDOFF.md (или README) этого проекта и кратко доложи: состояние, блокеры, "
                      "следующий шаг."}
NAME_OK = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
NOTIFY = {"all": "все окна", "active": "только активное", "off": "выкл"}
DEFAULTS = {"notify": "all", "voice_always": False}


TRIAGE_NOTE = {"sent": "🔎 Отправил на разбор в [{to}] — Claude предложит исправление",
               "dup": "🔎 Эта ошибка уже отправлялась на разбор в [{to}]",
               "closed": "Сессии этой папки уже нет — на разбор не отправил",
               "busy": "Claude в [{to}] ждёт ответа на вопрос — на разбор не отправил; выполните ещё раз позже"}


class Pult:
    pause_until = 0.0          # Telegram ответил 429 — до этого времени не шлём (повторы только продлевают запрет)
    skipped = 0                # сколько сообщений не отправили за паузу — сказать одним сообщением после неё
    BURST = 3                  # больше ответов окна за один обход монитора — шлём последний и счётчик
    actor = threading.local()  # кто сейчас действует (Telegram ID; у каждого потока свой) — для проверки страны

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
        self.requests: dict[int, dict] = {}                # кто просит доступ: Telegram ID → имя, @username
        self.hint_wait: dict[str, dict] = {}               # окно → ответ, к которому ждём подсказку Claude (90 с)
        self.hints: dict[int, tuple[str, str]] = {}        # n → (окно, текст подсказки) для кнопки 💡
        self.digest = digest.Digest(cfg.data / "digest.json")
        # поставщик модели не отвечает — окно само уходит на запасной (fallback.py), владельцам — одна строка
        # запасные — по странам человека, чьё окно (@gas_pult_by), иначе первого владельца
        self.fallback = fallback.Switcher(self.tmux, self.state, cfg.claude, cfg.region,
                                          say=lambda line: self.broadcast("🔁 " + line), log=self.fallback_logged,
                                          countries=self.window_countries)
        # вход в Claude Code из пульта (setup.py); config_dir/env — когда у каждого человека будет своя папка Claude
        self.login = setup.Login(cfg.session, cfg.claude, home=self.home)

    # ---------- Telegram ----------
    def send(self, chat: int, text: str, **kw) -> dict:
        if (left := self.pause_until - time.time()) > 0:
            self.skipped += 1
            raise TelegramError("sendMessage", f"лимит Telegram — пауза ещё {left:.0f} с")
        parts = [text[i:i + 4000] for i in range(0, max(len(text), 1), 4000)] or ["—"]   # лимит — 4096
        r = {}
        try:
            for i, c in enumerate(parts):  # кнопки — под последним куском
                r = self.api("sendMessage", chat_id=chat, text=c or "—", **(kw if i == len(parts) - 1 else {}))
        except TelegramError as e:
            if e.retry_after:
                self.pause_until = time.time() + e.retry_after
                self.skipped += 1
            raise
        return r or {}

    def after_pause(self):
        """Пауза 429 кончилась — одно сообщение вместо пропущенных."""
        if self.skipped and time.time() >= self.pause_until:
            n, self.skipped = self.skipped, 0
            self.broadcast(f"⏸ Telegram на время ограничил частоту сообщений — {n} уведомл. не отправлено. "
                           "Ответы Claude — в панели.")

    def show_dialog(self, w: dict, scr: str, shown: dict):
        """Открытое меню/вопрос = одно сообщение каждому владельцу; изменилось — правим его, без новых уведомлений."""
        h, ep, now = dialog_hash(scr), shown.get(w["id"]), time.time()
        if ep and (ep["hash"] == h or now - ep["t"] < 4):
            return
        text, kw = self.screen_msg(w, "Claude ждёт выбора:")
        msgs = ep["msgs"] if ep else {}
        for chat in self.cfg.owners:
            try:
                if chat in msgs:
                    try:
                        self.api("editMessageText", chat_id=chat, message_id=msgs[chat], text=text[:4000], **kw)
                        continue
                    except TelegramError as e:
                        if "not modified" in e.description:
                            continue                     # то же самое — ничего не делаем; иначе (удалили) — заново
                msgs[chat] = self.send(chat, text, **kw).get("message_id")
            except TelegramError as e:
                print("send:", e, flush=True)
        shown[w["id"]] = {"msgs": msgs, "hash": h, "t": now}

    def broadcast(self, text: str, **kw):
        for chat in self.cfg.owners:
            try:
                self.send(chat, text, **kw)
            except TelegramError as e:
                print("send:", e, flush=True)

    def to(self, chat: int):
        return lambda text, **kw: self.send(chat, text, **kw)

    # ---------- состояние ----------
    def state(self) -> dict:
        try:
            return {**DEFAULTS, "voice": self.cfg.voice, **json.loads(self.state_file.read_text())}
        except (OSError, ValueError):
            return {**DEFAULTS, "voice": self.cfg.voice}

    def set_state(self, **kw):
        with self.lock:
            s = {**self.state(), **kw}
            self.state_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.state_file.write_text(json.dumps(s))

    def fallback_logged(self, entry: dict):
        """Переключение на запасной — в state.json (последние 20): панель показывает его строкой."""
        log = list(self.state().get("fallback_log") or [])[-19:]
        self.set_state(fallback_log=[*log, entry])

    # ---------- окна ----------
    def projects(self) -> list[str]:
        dirs = [self.home]
        for root in self.cfg.roots():
            dirs += sorted(str(p) for p in root.glob("*/") if p.is_dir())
        return dirs

    def short(self, path: str) -> str:
        return "домашняя (~)" if path == self.home else os.path.basename(path)

    def active(self) -> dict | None:
        w = self.tmux.window(self.state().get("active") or "")
        return w if w and w["cmd"] == "claude" else None

    def need_active(self, chat: int) -> dict | None:
        w = self.active()
        if not w:
            self.send(chat, "Активного окна с Claude нет — выбери в 🔀 Переключить или 🆕 Новая.", reply_markup=MENU)
        return w

    def wait_ready(self, wid: str, limit: int = 40) -> bool:
        """Свежий Claude грузится несколько секунд — ждём строку ввода."""
        for _ in range(limit):
            scr = "\n".join(self.tmux.screen(wid))
            if "❯" in scr or DIALOG.search(scr):
                return True
            time.sleep(1)
        return False

    def ready_for_text(self, wid: str, limit: int = 40):
        """Довести окно до строки ввода: меню закрыть (Esc), на вопрос — не отвечать, свежий Claude — дождаться."""
        w = self.tmux.window(wid)
        if w and w.get("cmd") != "claude" and w.get("mark"):     # Claude завершился — в окне оболочка, не печатаем
            raise NotReady("Claude в этом окне остановлен — текст в командную строку не отправляю. Перезапустите "
                           "сессию: в панели «Перезапустить» или 🆕 в той же папке")
        escapes = 0
        for _ in range(limit):
            scr = "\n".join(self.tmux.screen(wid, 15))
            if QUESTION.search(scr):
                raise NotReady("Claude ждёт ответа на вопрос в этом окне — ответьте на экране (1 2 3 или Esc), "
                               "потом пишите")
            if PANEL.search(scr) and not BUSY.search(scr):
                if escapes >= 3:
                    raise NotReady("в окне открыто меню Claude и не закрывается — откройте «Экран» и нажмите Esc")
                self.tmux.keys(wid, "Escape")
                escapes += 1
                time.sleep(0.8)
                continue
            if PROMPT.search(scr):
                return
            time.sleep(1)
        raise NotReady("окно не готово к вводу 40 секунд — посмотрите «Экран»")

    @contextmanager
    def hold(self, wid: str):
        """В окно пишет кто-то один. Бот и панель — разные процессы, поэтому замок — файл (flock), а не threading.Lock;
        снимается сам, когда файл закрыт, — даже если процесс упал. Не вкладывать: второй hold того же окна ждёт."""
        self.locks.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(self.locks / (re.sub(r"[^\w@-]", "_", wid) + ".lock"), "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            yield

    def to_claude(self, w: dict, text: str):
        uid = getattr(self.actor, "uid", None)             # из бота — человек; из панели и монитора — проверено там
        if uid is not None and not models.allowed(w.get("profile") or "claude", self.countries(uid)):
            raise Denied(country.DENY)
        with self.hold(w["id"]):
            self.ready_for_text(w["id"])
            self.tmux.paste(w["id"], text)

    def run_slash(self, wid: str, cmd: str) -> list[str]:
        """Слэш-команда как с клавиатуры — одна для бота и панели; через 2,5 с — экран (меню или ответ)."""
        with self.hold(wid):
            self.ready_for_text(wid)                   # открытое меню закрыть, на вопрос Claude — не печатать
            self.tmux.type(wid, cmd)
            time.sleep(0.3)
            self.tmux.keys(wid, "Enter")
        time.sleep(2.5)
        return self.tmux.screen(wid, 40)

    def slash(self, chat: int, w: dict, cmd: str):
        """Меню (/model, /mcp) монитор пришлёт сам, остальное — экраном."""
        if not DIALOG.search("\n".join(self.run_slash(w["id"], cmd)[-25:])):
            self.send_screen(chat, w, cmd)

    def screen_msg(self, w: dict, title: str) -> tuple[str, dict]:
        return (f"[{w['name']}] {title}\n\n" + "\n".join(self.tmux.screen(w["id"])),
                {"reply_markup": kb([[(t, f"key:{w['id']}|{k}") for t, k in KEYS]])})

    def send_screen(self, chat: int, w: dict, title: str):
        text, kw = self.screen_msg(w, title)
        self.send(chat, text, **kw)

    def project_window(self, path: str) -> dict | None:
        """Окно Claude, уже работающее в этой папке (правило: одно окно на проект)."""
        real = os.path.realpath(path)
        return next((w for w in self.tmux.windows()
                     if w["cmd"] == "claude" and os.path.realpath(w["path"]) == real), None)

    def claude_dir(self, uid) -> Path | None:
        """Папка Claude Code человека для новых окон; владелец — None (``~/.claude``)."""
        return people.claude_dir(self.cfg.data, uid, self.cfg.owners)

    def home_of(self, w: dict) -> Path | None:
        """Папка Claude Code окна: того, кто его открыл (``@gas_pult_by``), а не того, кто сейчас нажал."""
        return people.home_of(w, self.cfg.data)

    def open_session(self, chat: int, name: str, path: str, first: str | None = None):
        if not setup.installed(self.cfg.claude):
            return self.show_setup(chat)
        if w := self.project_window(path):
            self.set_state(active=w["id"])
            self.send(chat, f"↪️ В {self.short(path)} уже работает «{w['name']}» — пишу туда (одно окно на проект).")
            if first:
                self.to_claude(w, first)
            return
        uid = getattr(self.actor, "uid", None)
        if uid is not None and not models.allowed("claude", self.countries(uid)):
            return self.send(chat, country.DENY)
        try:
            home = self.claude_dir(chat)                # чат с ботом — личный: chat = Telegram ID того, кто открыл
            wid = self.tmux.new_window(name, path, models.with_home(self.cfg.claude, home),
                                       by=str(chat) if home else "")
            if uid is not None and not home:            # окно владельца — тоже с меткой: запасные по его странам
                self.tmux.run("set-option", "-w", "-t", wid, "@gas_pult_by", str(uid))
        except (RuntimeError, OSError) as e:
            return self.send(chat, f"Не вышло: {e}")
        self.set_state(active=wid)
        self.send(chat, f"✅ Окно «{name}» с Claude в {self.short(path)} — активно. Пиши сюда, ответы придут сами.")
        if first:
            time.sleep(3)
            if w := self.tmux.window(wid):
                self.to_claude(w, first)

    def quit(self, w: dict) -> str:
        """Выйти из Claude штатно (/exit — переписка сохранится) и закрыть окно — одно для бота и панели.
        «closed» — закрыто; «background» — у сессии фоновые задачи, не закрываем; «busy» — Claude не вышел."""
        with self.hold(w["id"]):
            self.tmux.keys(w["id"], "C-c")
            self.tmux.type(w["id"], "/exit")
            self.tmux.keys(w["id"], "Enter")
            time.sleep(4)
            if "Enter to confirm" in "\n".join(self.tmux.screen(w["id"])):
                self.tmux.keys(w["id"], "Escape")
                return "background"
            if (self.tmux.window(w["id"]) or w)["cmd"] == "claude":
                return "busy"
            self.tmux.kill(w["id"])
            return "closed"

    def close(self, chat: int, w: dict):
        if w["cmd"] != "claude":
            self.tmux.kill(w["id"])
        elif (done := self.quit(w)) == "background":
            return self.send(chat, f"«{w['name']}» не завершена: у сессии есть фоновые задачи, они бы "
                                   "остановились. Реши в самом окне.")
        elif done == "busy":
            return self.send(chat, f"«{w['name']}»: Claude не вышел (возможно, занят). Посмотри 📺 Экран.")
        self.send(chat, f"«{w['name']}» завершена.")

    # ---------- голос ----------
    def say(self, chat: int, text: str):
        clean = transcripts.clean(text)[:3500]      # ~3–4 минуты речи; код и таблицы пропущены
        if not clean:
            return
        v = self.state()["voice"]
        if v not in catalog.installed(self.cfg.personal_voices):      # бот — только владельцам
            return self.send(chat, f"Голос «{catalog.label(v)}» не установлен: gas-pult voices install {v}")
        base = self.cfg.data / f"out-{uuid.uuid4().hex}"
        try:
            if not self.state().get("audio_only"):
                try:
                    voice.synth(v, clean, base.with_suffix(".ogg"))
                    data = base.with_suffix(".ogg").read_bytes()
                    return self.api("sendVoice", chat_id=chat, files={"voice": ("answer.ogg", data)})
                except TelegramError as e:  # приватность Telegram запрещает голосовые → аудиофайл
                    if "VOICE_MESSAGES_FORBIDDEN" not in e.description:
                        raise
                    self.set_state(audio_only=True)
            voice.synth(v, clean, base.with_suffix(".mp3"))
            self.api("sendAudio", chat_id=chat, title="Ответ Claude", performer="gas-pult",
                     files={"audio": ("answer.mp3", base.with_suffix(".mp3").read_bytes())})
        finally:
            for ext in (".ogg", ".mp3"):
                base.with_suffix(ext).unlink(missing_ok=True)

    def remember(self, w: dict, text: str) -> int:
        with self.lock:
            self.counter += 1
            self.answers[self.counter] = (w["id"], text)
            for old in [k for k in self.answers if k <= self.counter - 100]:
                del self.answers[old]
            return self.counter

    # ---------- монитор: ответы и диалоги всех окон ----------
    def deliver(self, w: dict, text: str):
        n = self.remember(w, text)
        rows, msgs = [[("🔊", f"say:{n}"), ("✅ Да", f"yes:{w['id']}"), ("✏️ Ответить", f"act:{w['id']}")]], {}
        for chat in self.cfg.owners:
            try:
                msgs[chat] = self.send(chat, f"[{w['name']}]\n{text}", reply_markup=kb(rows)).get("message_id")
            except TelegramError as e:
                print("send:", e, flush=True)
        self.hint_wait[w["id"]] = {"t": time.time(), "msgs": msgs, "rows": rows}
        self.cmds.offer(w, text, self.broadcast, kb)
        if self.state()["voice_always"]:
            for chat in self.cfg.owners:
                threading.Thread(target=self.say, args=(chat, text), daemon=True).start()

    def offer_hints(self):
        """Подсказка Claude появляется через секунды после ответа — дописываем к ответу кнопку «💡 …» (ждём 90 с)."""
        for wid, x in list(self.hint_wait.items()):
            if time.time() - x["t"] > 90:
                self.hint_wait.pop(wid, None)
                continue
            if not (h := self.tmux.hint(wid)):
                continue
            self.hint_wait.pop(wid, None)
            with self.lock:
                self.counter += 1
                n = self.counter
                self.hints[n] = (wid, h)
                for old in [k for k in self.hints if k <= n - 100]:
                    del self.hints[old]
            label = "💡 " + (h if len(h) <= 40 else h[:39].rstrip() + "…")
            for chat, mid in x["msgs"].items():
                try:
                    self.api("editMessageReplyMarkup", chat_id=chat, message_id=mid,
                             reply_markup=kb([*x["rows"], [(label, f"hint:{n}")]]))
                except TelegramError as e:
                    print("hint:", e, flush=True)

    def monitor(self):
        tail, turns, shown = transcripts.Tail(time.time()), {}, {}
        while True:
            try:
                self.after_pause()
                st = self.state()
                ws = [w for w in self.tmux.windows() if w["cmd"] == "claude" and not w["channel"]]
                by_path: dict[tuple, list[dict]] = {}   # окна в одной папке пишут в общий каталог транскриптов
                for w in ws:                            # (у человека со своей папкой Claude — свой каталог)
                    by_path.setdefault((w["path"], self.home_of(w)), []).append(w)
                for (path, home), group in by_path.items():
                    w = next((x for x in group if x["id"] == st.get("active")), group[0])
                    quiet = st["notify"] == "off" or (st["notify"] == "active" and w["id"] != st.get("active"))
                    files, texts = transcripts.transcripts(path, home), []
                    tail.watch(f"{home}|{path}" if home else path, files)    # старое не пересылаем
                    for f in files:
                        for e in tail.read(f):
                            self.fallback.seen(w["id"], e)      # ошибка API поставщика — ждём остановки окна
                            if text := turns.setdefault(f, transcripts.Turns()).feed(e):
                                texts.append(text)
                    if texts and not quiet:
                        if len(texts) > self.BURST:            # пачка за 3 с — сбой, а не переписка
                            self.broadcast(f"[{w['name']}] пропущено ответов: {len(texts) - 1} — они в панели. "
                                           "Последний:")
                        for text in texts[-1:] if len(texts) > self.BURST else texts:
                            self.deliver(w, text)
                for w in ws:
                    quiet = st["notify"] == "off" or (st["notify"] == "active" and w["id"] != st.get("active"))
                    lines = self.tmux.screen(w["id"])
                    scr = "\n".join(lines)
                    if w["id"] in self.fallback.pending:        # сессия стоит на ошибке, человек не набирает
                        idle = not BUSY.search(scr) and not DIALOG.search(scr)
                        self.fallback.step(w, idle and not fallback.typing(lines, self.tmux.hint(w["id"])))
                    if not DIALOG.search(scr):
                        shown.pop(w["id"], None)
                    elif not quiet:
                        self.show_dialog(w, scr, shown)
                self.offer_hints()
            except Exception as e:
                print("monitor:", self.api.redact(e), flush=True)
            time.sleep(3)

    # ---------- утренняя сводка «ждёт владельца» ----------
    def digest_items(self) -> list[dict]:
        items = []
        if self.cfg.digest_github:
            try:
                items += digest.prs(self.cfg.digest_github, time.time())
            except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as e:
                print("digest:", e, flush=True)
        for w in self.tmux.windows():
            if w["cmd"] == "claude" and DIALOG.search("\n".join(self.tmux.screen(w["id"]))):
                items.append({"kind": "win", "key": digest.key("win", w["id"]), "id": w["id"], "name": w["name"]})
        return items + digest.handoffs(self.cfg.roots())

    def send_digest(self, chat: int | None = None):
        """Сводка сейчас: в чат (команда /digest) или всем владельцам (по расписанию; пусто — молчим)."""
        items = self.digest.fresh(self.digest_items(), time.time())
        if not items:
            return chat and self.send(chat, "☀️ Ничего не ждёт вашего решения.")
        text, kbd = digest.render(items)
        return self.send(chat, text, reply_markup=kbd) if chat else self.broadcast(text, reply_markup=kbd)

    def digest_loop(self):
        while True:
            try:
                now = datetime.now()
                if self.digest.due(self.cfg.digest_at, now):
                    self.digest.mark_sent(now.strftime("%Y-%m-%d"))      # сначала отметка — не слать дважды
                    self.send_digest()
            except Exception as e:
                print("digest:", self.api.redact(e), flush=True)
            time.sleep(60)

    def on_digest(self, chat: int, arg: str):
        """dg:y — «да» (PR и «да» штабу — с подтверждением dg:Y), dg:c — закрыть, dg:l — позже."""
        act, _, k = arg.partition(":")
        x, send = self.digest.item(k), self.to(chat)
        if not x:
            return send("Этот пункт уже не в сводке — пришлите /digest.")
        if act == "c":
            self.digest.snooze(k, digest.GONE)
            return send("Убрал из сводок на месяц.")
        if act == "l":
            self.digest.snooze(k, digest.LATER)
            return send("Напомню в следующей сводке.")
        if x["kind"] == "win":
            w = self.tmux.window(x["id"])
            return self.send_screen(chat, w, "Claude ждёт ответа:") if w else send("Этого окна уже нет.")
        if act == "y":
            ask = (f"Слить {x['repo']}#{x['n']} «{x['title']}»?" if x["kind"] == "pr"
                   else f"Передать «да» в окно {x['project']}: {x['text']}?")
            return send(ask,
                        reply_markup=kb([[("✅ Да", f"dg:Y:{k}"), ("Нет", "noop")]]))
        if x["kind"] == "pr":
            send(digest.merge(x["repo"], x["n"]))
        elif w := self.project_window(x["path"]):
            self.to_claude(w, f"Владелец отвечает «да» на пункт из HANDOFF.md: {x['text']}")
            send(f"Передал «да» в «{w['name']}».")
        else:
            return send(f"Окна с Claude в {x['project']} нет — откройте сессию (🆕 Новая) и повторите.")
        self.digest.snooze(k, digest.GONE)

    # ---------- экраны пульта ----------
    def show_windows(self, chat: int):
        ws = self.tmux.windows()
        if not ws:
            return self.send(chat, "Окон нет. Нажми 🆕 Новая.")
        rows = [[(f"{w['idx']}: {w['name']} · {self.short(w['path'])}" + (" 🤖" if w["cmd"] == "claude" else ""),
                  f"w:{w['id']}")] for w in ws]
        self.send(chat, "Окна tmux (🤖 — работает Claude):", reply_markup=kb(rows))

    def show_switch(self, chat: int):
        ws = [w for w in self.tmux.windows() if w["cmd"] == "claude"]
        act = self.state().get("active")
        if not ws:
            return self.send(chat, "Окон с Claude нет. Нажми 🆕 Новая.")
        self.send(chat, "Куда писать? (📡 — у окна свой Telegram-бот)", reply_markup=kb([[(
            ("✅ " if w["id"] == act else "") + f"{w['name']} · {self.short(w['path'])}"
            + (" 📡" if w["channel"] else ""), f"act:{w['id']}")] for w in ws]))

    def show_summary(self, chat: int):
        act, lines = self.state().get("active"), []
        for w in self.tmux.windows():
            if w["cmd"] != "claude":
                lines.append(f"{w['idx']}. {w['name']} — терминал")
                continue
            scr = "\n".join(self.tmux.screen(w["id"], 40))
            status = "⏸ ждёт выбора" if DIALOG.search(scr) else "⚙️ работает" if BUSY.search(scr) else "✅ свободен"
            ctx = re.search(r"left [\d.]+k? \((\d+)%\)", scr)
            lines.append(f"{w['idx']}. {'▶️ ' if w['id'] == act else ''}{w['name']} · {self.short(w['path'])} — "
                         f"{status}" + (f" · контекст свободен {ctx.group(1)}%" if ctx else "")
                         + (" · 📡" if w["channel"] else ""))
        self.send(chat, "📊 Сводка\n" + "\n".join(lines or ["окон нет"]))

    def command_list(self) -> list[tuple[str, str]]:
        return COMMANDS + [(t, c) for t, c in self.cfg.commands]

    def show_commands(self, chat: int):
        if w := self.need_active(chat):
            cmds = list(enumerate(self.command_list()))
            rows = [cmds[i:i + 3] for i in range(0, len(cmds), 3)]
            self.send(chat, f"⚡ Команды для «{w['name']}»:",
                      reply_markup=kb([[(t, f"cmd:{i}") for i, (t, _) in r] for r in rows]))

    def show_settings(self, chat: int):
        s, voices = self.state(), catalog.installed(self.cfg.personal_voices)
        rows = [[("🔔 Все", "set:notify=all"), ("🔕 Только активная", "set:notify=active"),
                 ("🚫 Выкл", "set:notify=off")],
                [("🔊 Голосом: вкл/выкл", "set:voice_always"), ("🩺 Проверка", "su:check")], [("👥 Люди", "ppl:")]]
        rows += [[(("✅ " if v == s["voice"] else "🗣 ") + catalog.label(v), f"set:voice={v}") for v in voices[i:i + 3]]
                 for i in range(0, len(voices), 3)]
        self.send(chat, f"⚙️ Уведомления: {NOTIFY.get(s['notify'], s['notify'])}\n"
                        f"🔊 Всегда голосом: {'да' if s['voice_always'] else 'нет'}\n"
                        f"🗣 Голос: {catalog.label(s['voice'])}"
                        + ("" if voices else "\n(голоса не установлены: gas-pult voices install irina)"),
                  reply_markup=kb(rows))

    def before_run(self, cmd: str, path: str):
        """▶️ в боте — во вкладке «Команды» панели сразу «выполняется»."""
        wins = [w for w in self.tmux.windows() if w["cmd"] == "claude" and w["path"] == path]
        self.journal.collect(wins, self.cmds.kind)
        self.journal.flag_cmd(path, cmd, running=time.strftime("%Y-%m-%d %H:%M", time.gmtime()))

    def after_run(self, cmd: str, path: str, code, secs: float, out: str) -> str:
        """▶️ в боте: отметка «выполнено» во вкладке «Команды» панели; упала — на разбор в сессию. Строка для итога."""
        wins = [w for w in self.tmux.windows() if w["cmd"] == "claude" and w["path"] == path]
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
        wins = [w for w in self.tmux.windows() if w["cmd"] == "claude" and w["path"] == path]
        w = next((x for x in wins if x["id"] == wid), None) or (wins[0] if wins else None)
        key = fail_key(path, cmd, code, out)
        if not w:
            return "closed", ""
        if not self.journal.triage_once(key):
            return "dup", w["name"]
        try:
            (paste or self.to_claude)(w, triage_text(cmd, code, out))
        except NotReady:
            self.journal.forget_triage(key)                  # следующий запуск попробует снова
            return "busy", w["name"]
        return "sent", w["name"]

    def rename(self, chat: int, wid: str, name: str):
        if not self.tmux.window(wid):
            return self.send(chat, "Этого окна уже нет.")
        try:
            self.send(chat, f"✏️ Теперь сессия называется «{self.tmux.rename(wid, name)}».")
        except (ValueError, RuntimeError) as e:
            self.send(chat, f"Не переименовал: {e}. Нажмите ✏️ ещё раз.")

    def new_folder(self, chat: int, name: str):
        root = self.cfg.roots()[0] if self.cfg.project_roots else Path(self.home) / "projects"
        path = root / name
        if not NAME_OK.match(name):
            return self.send(chat, "Имя: латиница в нижнем регистре, цифры, дефис (2–41 знак). Нажми 📁 ещё раз.")
        if path.exists():
            return self.send(chat, f"Папка {name} уже есть — выбери её в 🆕 Новая.")
        path.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(path)], capture_output=True)
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
        self.send(chat, "Спасибо, условия приняты. Пульт сессий Claude Code: текст, голос и файлы уходят в "
                        "активное окно. Кнопки внизу.", reply_markup=self.menu_of(uid))

    # ---------- страна человека (country.py) ----------
    def countries(self, uid) -> set[str]:
        return country.check_set(self.people.country(uid), self.cfg.region)

    def has_country(self, uid) -> bool:
        return bool(country.norm(self.people.country(uid).get("chosen")))

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
        self.broadcast(country.notice(who, uid, rec))

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
                 + f" — {TITLES[p['role']]}" + (", условия приняты" if self.people.accepted(p["id"]) else "")
                 + self.country_line(p.get("country")) for p in rest]
        self.send(chat, "👥 Люди пульта:\n" + "\n".join(lines) + "\n\nОтключить — доступ прекращается сразу, "
                        "любой вход человека перестаёт работать.", reply_markup=kb(rows))

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
        self.send(chat, f"Готово: {who} отключён(а) — вход больше не работает.")

    # ---------- обработчики ----------
    def on_callback(self, q: dict):
        chat = q["message"]["chat"]["id"] if q.get("message") else q["from"]["id"]
        self.api("answerCallbackQuery", callback_query_id=q["id"])
        kind, _, arg = q.get("data", "").partition(":")
        send = self.to(chat)
        if kind == "noop":
            return
        if kind == "lg":                                   # человек подтверждает вход в панель из своего Telegram
            verdict, _, nonce = arg.partition(":")
            uid = q["from"]["id"]
            if verdict == "ok" and not self.people.role(uid):
                return send("Доступа к пульту нет.")
            if not self.logins.decide(nonce, uid, verdict == "ok"):
                return send("Ссылка входа устарела — нажмите «Войти через Telegram» в браузере ещё раз.")
            return send("✅ Вход подтверждён — вернитесь в браузер." if verdict == "ok" else "Вход отклонён.")
        if q["from"]["id"] not in self.cfg.owners and kind not in ("tm", "cc"):
            return                                         # участникам кнопки бота — только условия и страна
        if kind == "pp":                                   # владелец решает, пускать ли человека
            return self.grant(chat, arg)
        if kind == "tm":                                   # «Принимаю» под условиями использования
            return self.on_terms(chat, q["from"]["id"], arg)
        if kind == "cc":                                   # выбор страны
            return self.on_country(chat, q["from"]["id"], arg)
        if kind == "ppl":
            return self.show_people(chat)
        if kind == "off":                                  # «Отключить человека» (только владелец — как всё, кроме lg:)
            return self.switch_off(chat, arg)
        if kind == "hint":                                 # 💡 под ответом — отправить подсказку Claude
            wid, h = self.hints.get(int(arg), ("", "")) if arg.isdigit() else ("", "")
            w = self.tmux.window(wid) if wid else None
            if not w:
                return send("Подсказка устарела или окна уже нет.")
            self.to_claude(w, h)
            return send(f"→ [{w['name']}]: {h}")
        if kind == "dg":
            return self.on_digest(chat, arg)
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
                  or (key == "voice" and val in catalog.installed(self.cfg.personal_voices))):
                self.set_state(**{key: val})
            return self.show_settings(chat)
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
                return send(f"Модель для «{w['name']}»:", reply_markup=kb([
                    [(m, f"cmd:/model {m}") for m in self.cfg.models], [("Открыть меню /model", "cmd:/model")]]))
            if cmd in PROMPTS:
                return self.to_claude(w, PROMPTS[cmd])
            return self.slash(chat, w, cmd) if cmd.startswith("/") else self.to_claude(w, cmd)
        if kind in ("run", "runok"):        # ▶️ Выполнить (runok — после подтверждения опасной)
            return self.cmds.run(arg, kind == "runok", send, kb, send_file=lambda name, data: self.api(
                "sendDocument", chat_id=chat, caption="Весь вывод команды", files={"document": (name, data)}))
        if kind == "key":                   # кнопки 1/2/3/↑/↓/⏎/Esc под экраном диалога
            wid, _, key = arg.partition("|")
            if key not in {k for _, k in KEYS}:
                return
            if not self.tmux.window(wid):
                return send("Этого окна уже нет.")
            return self.tmux.keys(wid, key)
        w = self.tmux.window(arg)
        if not w:
            return send("Этого окна уже нет.")
        if kind == "act":
            self.set_state(active=w["id"])
            send(f"✅ Пишу в «{w['name']}» ({self.short(w['path'])})."
                 + ("\n⚠️ У окна свой Telegram-бот — ответы придут туда, а не сюда." if w["channel"] else ""))
        elif kind == "yes":
            self.to_claude(w, "да")
        elif kind == "w":
            send(f"«{w['name']}» · {w['path']}", reply_markup=kb([
                [("🔀 Сделать активной", f"act:{w['id']}")],
                [("📺 Экран", f"scr:{w['id']}"), ("💬 Последний ответ", f"last:{w['id']}")],
                [("✏️ Переименовать", f"ren:{w['id']}"), ("⛔ Завершить", f"ask:{w['id']}")]]))
        elif kind == "ren":
            self.waiting[chat] = f"ren:{w['id']}"
            send(f"Новое имя для «{w['name']}» (до 40 знаков, без «:» и «.»):", reply_markup={"force_reply": True})
        elif kind == "scr":
            self.send_screen(chat, w, "экран:")
        elif kind == "last":
            text = transcripts.last_answer(w["path"], self.home_of(w))
            if not text:
                return send("Ответов Claude в этой папке не нашёл.")
            send(text, reply_markup=kb([[("🔊", f"say:{self.remember(w, text)}")]]))
        elif kind == "ask":
            send(f"Завершить «{w['name']}»? Claude выйдет штатно, переписка сохранится.",
                 reply_markup=kb([[("Да, завершить", f"close:{w['id']}"), ("Нет", "noop:")]]))
        elif kind == "close":
            self.close(chat, w)

    def react(self, m: dict, emoji: str):
        try:
            self.api("setMessageReaction", chat_id=m["chat"]["id"], message_id=m["message_id"],
                     reaction=[{"type": "emoji", "emoji": emoji}])
        except TelegramError:
            pass

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
            return send(f"{what} подключаются в панели: «Интеграции». Панель запускается командой "
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
        role = self.people.role(u["id"])
        if role:
            return send(f"Войти в панель пульта ({TITLES[role]})?\n\nБраузер: {info['ua'] or '—'}\n"
                        f"Адрес: {info['ip'] or '—'}\n\nЕсли входите не вы — нажмите «Это не я».",
                        reply_markup=kb([[("✅ Войти", f"lg:ok:{nonce}"), ("✖️ Это не я", f"lg:no:{nonce}")]]))
        name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or str(u["id"])
        self.requests[u["id"]] = {"name": name, "username": u.get("username", "")}
        send("У вас пока нет доступа к пульту. Я спросил владельца — когда он ответит, нажмите «Войти через Telegram» "
             "в браузере ещё раз.")
        self.broadcast(f"🔐 {name} (@{u.get('username') or '—'}, ID {u['id']}) просит доступ к панели пульта.",
                       reply_markup=kb([[("👤 Участник", f"pp:member:{u['id']}"),
                                         ("👁 Наблюдатель", f"pp:viewer:{u['id']}")],
                                        [("✖️ Отказать", f"pp:no:{u['id']}")]]))

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
        if t.startswith("/start login_"):
            return self.login_request(m, t.removeprefix("/start login_").strip())
        uid = (m.get("from") or {}).get("id")
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
        if wait == "code" and m.get("text") and not t.startswith(MENU_PREFIXES) and not t.startswith("/"):
            return self.setup_code(chat, t)
        if t.startswith("🆕"):
            rows = [[("📁 Новая папка…", "mk:")]]
            rows += [[(self.short(p), f"new:{i}")] for i, p in enumerate(self.projects())]
            return send("В какой папке открыть новую сессию? (или пришли номер задачи, например GAS-123)",
                        reply_markup=kb(rows))
        for prefix, fn in (("🔀", self.show_switch), ("📊", self.show_summary), ("⚡", self.show_commands),
                           ("📋", self.show_windows), ("⚙️", self.show_settings)):
            if t.startswith(prefix):
                return fn(chat)
        if t == "/digest":
            return self.send_digest(chat)
        if t in ("/start", "/menu", "/help"):
            send("Пульт сессий Claude Code. Текст, голос и файлы уходят в активное окно. Кнопки внизу.",
                 reply_markup=MENU)
            if t == "/start" and not (st := self.setup_status())["ready"]:
                self.show_setup(chat, st)
            return None
        if t == "/setup":
            return self.show_setup(chat)
        task = self.task.match(t) if m.get("text") else None
        if task:
            tid = task.group(1).upper()
            rows = [[(self.short(p), f"tnew:{i}|{tid}")] for i, p in enumerate(self.projects())]
            return send(f"Задача {tid}: в какой папке открыть сессию?", reply_markup=kb(rows))
        if not (w := self.need_active(chat)):
            return
        if v := (m.get("voice") or m.get("audio")):
            self.react(m, "✍")
            try:
                text = voice.transcribe(self.api.download(v["file_id"], self.cfg.data / "inbox", "voice.ogg"),
                                        self.cfg.whisper_model)
            except (RuntimeError, OSError) as e:
                return send(f"Не разобрал голосовое: {e}")
            if not text:
                return send("Не разобрал голосовое — попробуй ещё раз.")
            send(f"🎙 → [{w['name']}]: {text}")
            return self.to_claude(w, text)
        f = (m.get("photo") or [None])[-1] or m.get("document") or m.get("video")
        if f:
            path = self.api.download(f["file_id"], self.cfg.data / "inbox", f.get("file_name") or "photo.jpg")
            t = f"{t or 'Посмотри файл.'}\n\nФайл из Telegram: {path}"
        if not t:
            return send("Пришли текст, голосовое или файл.")
        self.to_claude(w, t)
        self.react(m, "👀")

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
        offset = None
        while True:
            try:
                for u in self.api("getUpdates", timeout=60, **({"offset": offset} if offset else {})):
                    offset = u["update_id"] + 1
                    src = u.get("message") or u.get("callback_query") or {}
                    uid = src.get("from", {}).get("id")
                    if uid not in self.cfg.owners and not public(u) and not (
                            self.people.role(uid) and self.country_update(u)):   # чужих — молча; людям — страна
                        continue
                    threading.Thread(target=self.handle, args=(u,), daemon=True).start()
            except Exception as e:
                print("poll:", self.api.redact(e), flush=True)
                time.sleep(5)
