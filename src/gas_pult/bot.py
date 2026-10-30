"""Пульт: Telegram ⇄ окна Claude Code в tmux.

Меню: 🆕 Новая · 🔀 Переключить · 📊 Сводка · ⚡ Команды · 📋 Окна · ⚙️ Настройки.
- Текст, голосовое, фото и файлы уходят в активное окно (голос — через faster-whisper).
- Монитор: любой законченный ход Claude и любой диалог на экране (разрешения, /model, /mcp) приходят сами,
  с кнопками 🔊 ✅ ✏️ и 1/2/3/↑/↓.
- Номер задачи (GAS-123) — новая сессия по задаче. Команды из ответа — отдельными сообщениями с ▶️.
Пускает только владельцев из ``owners``; от остальных принимает лишь вход в панель «через Telegram»
(``/start login_…`` и кнопки «Войти / Это не я») — остальное молча игнорирует.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

from gas_pult import transcripts, voice
from gas_pult.commands import Commands
from gas_pult.config import Config
from gas_pult.people import TITLES, People
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


class Pult:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.api = Api(cfg.token)
        self.tmux = Tmux(cfg.session)
        self.cmds = Commands(cfg.host, cfg.data / "cmds.json", cfg.sudo_allow, cfg.foreign)
        self.task = re.compile(rf"^(?:/task\s+)?({cfg.task_pattern})$", re.I)
        self.state_file = cfg.data / "state.json"
        self.lock = threading.Lock()
        self.answers: dict[int, tuple[str, str]] = {}     # n → (окно, текст) для 🔊; последние 100
        self.counter = 0
        self.waiting: dict[int, str] = {}                 # чат → чего ждём следующим сообщением
        self.home = os.path.expanduser("~")
        self.people = People(cfg.data / "people.json", cfg.owners)
        self.logins = TgLogins(cfg.data / "tg_logins.json")
        self.requests: dict[int, dict] = {}                # кто просит доступ: Telegram ID → имя, @username

    # ---------- Telegram ----------
    def send(self, chat: int, text: str, **kw) -> dict:
        parts = [text[i:i + 4000] for i in range(0, max(len(text), 1), 4000)] or ["—"]   # лимит — 4096
        r = {}
        for i, c in enumerate(parts):  # кнопки — под последним куском
            r = self.api("sendMessage", chat_id=chat, text=c or "—", **(kw if i == len(parts) - 1 else {}))
        return r or {}

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

    def to_claude(self, w: dict, text: str):
        self.ready_for_text(w["id"])
        self.tmux.paste(w["id"], text)

    def slash(self, chat: int, w: dict, cmd: str):
        """Слэш-команда: печатаем как с клавиатуры; меню (/model, /mcp) монитор пришлёт сам, остальное — экраном."""
        self.ready_for_text(w["id"])
        self.tmux.type(w["id"], cmd)
        time.sleep(0.3)
        self.tmux.keys(w["id"], "Enter")
        time.sleep(2.5)
        if not DIALOG.search("\n".join(self.tmux.screen(w["id"]))):
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

    def open_session(self, chat: int, name: str, path: str, first: str | None = None):
        if w := self.project_window(path):
            self.set_state(active=w["id"])
            self.send(chat, f"↪️ В {self.short(path)} уже работает «{w['name']}» — пишу туда (одно окно на проект).")
            if first:
                self.to_claude(w, first)
            return
        try:
            wid = self.tmux.new_window(name, path, self.cfg.claude)
        except (RuntimeError, OSError) as e:
            return self.send(chat, f"Не вышло: {e}")
        self.set_state(active=wid)
        self.send(chat, f"✅ Окно «{name}» с Claude в {self.short(path)} — активно. Пиши сюда, ответы придут сами.")
        if first:
            time.sleep(3)
            if w := self.tmux.window(wid):
                self.to_claude(w, first)

    def close(self, chat: int, w: dict):
        if w["cmd"] == "claude":            # выходим штатно, чтобы переписка сохранилась
            self.tmux.keys(w["id"], "C-c")
            self.tmux.type(w["id"], "/exit")
            self.tmux.keys(w["id"], "Enter")
            time.sleep(4)
            if "Enter to confirm" in "\n".join(self.tmux.screen(w["id"])):
                self.tmux.keys(w["id"], "Escape")
                return self.send(chat, f"«{w['name']}» не закрыл: у сессии есть фоновые задачи, они бы "
                                       "остановились. Реши в самом окне.")
            w = self.tmux.window(w["id"]) or w
            if w["cmd"] == "claude":
                return self.send(chat, f"«{w['name']}»: Claude не вышел (возможно, занят). Посмотри 📺 Экран.")
        self.tmux.kill(w["id"])
        self.send(chat, f"«{w['name']}» закрыто.")

    # ---------- голос ----------
    def say(self, chat: int, text: str):
        clean = transcripts.clean(text)[:3500]      # ~3–4 минуты речи; код и таблицы пропущены
        if not clean:
            return
        v = self.state()["voice"]
        if v not in catalog.installed():
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
        self.broadcast(f"[{w['name']}]\n{text}", reply_markup=kb([[
            ("🔊", f"say:{n}"), ("✅ Да", f"yes:{w['id']}"), ("✏️ Ответить", f"act:{w['id']}")]]))
        self.cmds.offer(w, text, self.broadcast, kb)
        if self.state()["voice_always"]:
            for chat in self.cfg.owners:
                threading.Thread(target=self.say, args=(chat, text), daemon=True).start()

    def monitor(self):
        tail, turns, shown, started = transcripts.Tail(), {}, {}, time.time()
        while True:
            try:
                st = self.state()
                ws = [w for w in self.tmux.windows() if w["cmd"] == "claude" and not w["channel"]]
                by_path: dict[str, list[dict]] = {}     # окна в одной папке пишут в общий каталог транскриптов
                for w in ws:
                    by_path.setdefault(w["path"], []).append(w)
                for path, group in by_path.items():
                    w = next((x for x in group if x["id"] == st.get("active")), group[0])
                    quiet = st["notify"] == "off" or (st["notify"] == "active" and w["id"] != st.get("active"))
                    for f in transcripts.transcripts(path):
                        tail.track(f, from_start=f.stat().st_ctime > started)   # старое не пересылаем
                        for e in tail.read(f):
                            text = turns.setdefault(f, transcripts.Turns()).feed(e)
                            if text and not quiet:
                                self.deliver(w, text)
                for w in ws:
                    quiet = st["notify"] == "off" or (st["notify"] == "active" and w["id"] != st.get("active"))
                    scr = "\n".join(self.tmux.screen(w["id"]))
                    if not DIALOG.search(scr):
                        shown.pop(w["id"], None)
                    elif not quiet:
                        self.show_dialog(w, scr, shown)
            except Exception as e:
                print("monitor:", self.api.redact(e), flush=True)
            time.sleep(3)

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
        s, voices = self.state(), catalog.installed()
        rows = [[("🔔 Все", "set:notify=all"), ("🔕 Активное", "set:notify=active"), ("🚫 Выкл", "set:notify=off")],
                [("🔊 Голосом: вкл/выкл", "set:voice_always")]]
        rows += [[(("✅ " if v == s["voice"] else "🗣 ") + catalog.label(v), f"set:voice={v}") for v in voices[i:i + 3]]
                 for i in range(0, len(voices), 3)]
        self.send(chat, f"⚙️ Уведомления: {NOTIFY.get(s['notify'], s['notify'])}\n"
                        f"🔊 Всегда голосом: {'да' if s['voice_always'] else 'нет'}\n"
                        f"🗣 Голос: {catalog.label(s['voice'])}"
                        + ("" if voices else "\n(голоса не установлены: gas-pult voices install irina)"),
                  reply_markup=kb(rows))

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
        if kind == "pp":                                   # владелец решает, пускать ли человека
            return self.grant(chat, arg)
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
            elif (key == "notify" and val in NOTIFY) or (key == "voice" and val in catalog.installed()):
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
                    [(m, f"cmd:/model {m}") for m in self.cfg.models], [("Меню выбора", "cmd:/model")]]))
            if cmd in PROMPTS:
                return self.to_claude(w, PROMPTS[cmd])
            return self.slash(chat, w, cmd) if cmd.startswith("/") else self.to_claude(w, cmd)
        if kind in ("run", "runok"):        # ▶️ Выполнить (runok — после подтверждения опасной)
            return self.cmds.run(arg, kind == "runok", send, kb)
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
                [("🔀 Сделать активным", f"act:{w['id']}")],
                [("📺 Экран", f"scr:{w['id']}"), ("💬 Последний ответ", f"last:{w['id']}")],
                [("⛔ Закрыть", f"ask:{w['id']}")]]))
        elif kind == "scr":
            self.send_screen(chat, w, "экран:")
        elif kind == "last":
            text = transcripts.last_answer(w["path"])
            if not text:
                return send("Ответов Claude в этой папке не нашёл.")
            send(text, reply_markup=kb([[("🔊", f"say:{self.remember(w, text)}")]]))
        elif kind == "ask":
            send(f"Закрыть «{w['name']}»?", reply_markup=kb([[("Да, закрыть", f"close:{w['id']}"), ("Нет", "noop:")]]))
        elif kind == "close":
            self.close(chat, w)

    def react(self, m: dict, emoji: str):
        try:
            self.api("setMessageReaction", chat_id=m["chat"]["id"], message_id=m["message_id"],
                     reaction=[{"type": "emoji", "emoji": emoji}])
        except TelegramError:
            pass

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
        self.send(chat, f"Готово: {who} — {TITLES[role]}. Убрать или поменять роль — «Настройки» → «Люди» в панели.")
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
        if self.waiting.pop(chat, None) == "name" and m.get("text") and not t.startswith(MENU_PREFIXES):
            return self.new_folder(chat, t.lower())
        if t.startswith("🆕"):
            rows = [[("📁 Новая папка…", "mk:")]]
            rows += [[(self.short(p), f"new:{i}")] for i, p in enumerate(self.projects())]
            return send("В какой папке открыть новую сессию? (или пришли номер задачи, например GAS-123)",
                        reply_markup=kb(rows))
        for prefix, fn in (("🔀", self.show_switch), ("📊", self.show_summary), ("⚡", self.show_commands),
                           ("📋", self.show_windows), ("⚙️", self.show_settings)):
            if t.startswith(prefix):
                return fn(chat)
        if t in ("/start", "/menu", "/help"):
            return send("Пульт сессий Claude Code. Текст, голос и файлы уходят в активное окно. Кнопки внизу.",
                        reply_markup=MENU)
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
            if "callback_query" in u:
                self.on_callback(u["callback_query"])
            else:
                self.on_message(u["message"])
        except Exception as e:
            if chat:
                self.send(chat, f"Ошибка: {self.api.redact(e)}")

    def run(self):
        me = self.api("getMe")
        print(f"gas-pult: @{me['username']} · сессия tmux «{self.cfg.session}» · владельцев: {len(self.cfg.owners)}",
              flush=True)
        threading.Thread(target=self.monitor, daemon=True).start()
        offset = None
        while True:
            try:
                for u in self.api("getUpdates", timeout=60, **({"offset": offset} if offset else {})):
                    offset = u["update_id"] + 1
                    src = u.get("message") or u.get("callback_query") or {}
                    if src.get("from", {}).get("id") not in self.cfg.owners and not public(u):   # чужих — молча
                        continue
                    threading.Thread(target=self.handle, args=(u,), daemon=True).start()
            except Exception as e:
                print("poll:", self.api.redact(e), flush=True)
                time.sleep(5)
