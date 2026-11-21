"""Служба бота Telegram Business (``gas-pult tgbiz run``, юнит ``gas-pult-tgbiz``): одна точка чтения апдейтов.

Решение владельца 16.11 («1 да»): апдейты бота читает только эта служба (``getUpdates`` со своим offset) и кладёт их в
локальный журнал ``~/.local/state/gas-pult/tgbiz/updates.jsonl`` (0600, 7 дней). Коннектор ``tgbiz_mcp`` читает этот
журнал, а не Telegram, — второй читатель не забирает апдейты у первого, ничего не теряется.

Владелец пишет боту в личный чат:
- ``/заметка <текст>`` (``/note``) — заметка сразу (команда владельца и есть подтверждение): Notion, если настроен,
  иначе локальный файл (``tgbiz_mcp._save_note``);
- голосовое — текст на этом сервере (локальный ASR, ``voice.transcribe_any``); в чужие сервисы голос не уходит;
- ``/журналист [тема]`` — режим «журналист» (решение владельца 16.11: «2 Claude»): окно Claude в пульте со скиллом
  zhurnalist; сообщения и голосовые владельца уходят в окно, законченные ответы Claude (вопросы, черновик) — в бот;
  черновик — на Диск владельца ``~/drive/Статьи/черновики/ГГГГ-ММ-ДД-<тема>.md``; публикация — только после «да»;
  ``/стоп`` — выйти из режима;
- остальное — подсказка.
Чужим людям бот в личке не отвечает. Ответы клиентам — только через черновик и подтверждение (коннектор).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("GAS_TGBIZ_STATE") or Path.home() / ".local/state/gas-pult/tgbiz")
KEEP = 7 * 86400                                       # сколько дней храним журнал апдейтов
ALLOWED = ["message", "business_connection", "business_message", "edited_business_message",
           "deleted_business_messages"]
HELP = ("Я бот GASTECH Business.\n"
        "• /заметка <текст> — сохранить заметку (Notion или файл на сервере)\n"
        "• /журналист [тема] — статья из вашего опыта: задам вопросы и напишу черновик; /стоп — выйти\n"
        "• голосовое — распознаю на сервере и пришлю текст\n"
        "Ответы клиентам — только после вашего подтверждения в пульте.")


def journal() -> Path:
    return ROOT / "updates.jsonl"


def heartbeat() -> Path:
    return ROOT / "alive"


def append(updates: list[dict], now: float | None = None) -> None:
    """Апдейты — в журнал (0600) с временем получения."""
    if not updates:
        return
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    f = journal()
    with open(f, "a", encoding="utf-8") as fh:
        for u in updates:
            fh.write(json.dumps({"at": now or time.time(), "update": u}, ensure_ascii=False) + "\n")
    f.chmod(0o600)


def read(since: float = 0.0, now: float | None = None) -> list[dict]:
    """Апдейты из журнала не старше 7 дней (и не раньше ``since``) — по порядку."""
    now = now or time.time()
    out = []
    try:
        lines = journal().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and now - float(r.get("at") or 0) <= KEEP and float(r.get("at") or 0) >= since:
            out.append(r["update"])
    return out


def prune(now: float | None = None) -> int:
    """Убрать из журнала записи старше 7 дней; → сколько убрано."""
    now = now or time.time()
    f = journal()
    try:
        lines = f.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    keep = []
    for ln in lines:
        try:
            if now - float(json.loads(ln).get("at") or 0) <= KEEP:
                keep.append(ln)
        except (ValueError, AttributeError):
            continue
    if len(keep) != len(lines):
        tmp = f.with_suffix(".tmp")
        tmp.write_text("".join(x + "\n" for x in keep), encoding="utf-8")
        tmp.chmod(0o600)
        tmp.replace(f)
    return len(lines) - len(keep)


def alive(max_age: float = 120) -> bool:
    """Служба работает (отметка свежее ``max_age`` с) — коннектор читает журнал, а не Telegram."""
    try:
        return time.time() - heartbeat().stat().st_mtime < max_age
    except OSError:
        return False


DRAFTS = Path(os.environ.get("GAS_TGBIZ_DRAFTS") or Path.home() / "drive/Статьи/черновики")
WORK = Path(os.environ.get("GAS_TGBIZ_WORK") or Path.home() / ".local/share/gas-pult/journalist")


def brief(topic: str, drafts: Path) -> str:
    """Первое сообщение окну Claude: что делать и как отвечать (его ответы пересылаются владельцу в Telegram)."""
    return (f"Используй скилл zhurnalist. Владелец пишет тебе из Telegram-бота: твои законченные ответы приходят ему "
            f"как есть — коротко, без таблиц. Задай 5–8 вопросов одним сообщением, по номерам; после ответов напиши "
            f"черновик и сохрани его в {drafts}/{time.strftime('%Y-%m-%d')}-<тема латиницей или кириллицей>.md "
            f"(папка — Google Диск владельца). В ответе — ссылка на файл на Google Диске (не путь на сервере). "
            f"Публикация и отправка людям — только после «да» владельца."
            + (f" Тема: {topic}." if topic else " Тему владелец пришлёт следующим сообщением."))


class Journalist:
    """Режим «журналист»: одно окно Claude на владельца. Состояние — ``journalist.json`` рядом с журналом апдейтов."""

    def __init__(self, open_window, paste, answer, alive):
        # open_window(name, path) → (wid, sid); paste(wid, text) → bool; answer(path, sid) → (готов?, текст, отпечаток);
        # alive(wid) → окно есть
        self.open_window, self.paste, self.answer, self.alive = open_window, paste, answer, alive

    def _f(self) -> Path:
        return ROOT / "journalist.json"

    def state(self) -> dict:
        try:
            return json.loads(self._f().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save(self, st: dict):
        ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        if st:
            self._f().write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
            self._f().chmod(0o600)
        else:
            self._f().unlink(missing_ok=True)

    def active(self) -> bool:
        st = self.state()
        return bool(st) and self.alive(st["wid"])

    def start(self, chat: int, topic: str) -> str:
        DRAFTS.mkdir(parents=True, exist_ok=True)
        WORK.mkdir(parents=True, exist_ok=True, mode=0o700)
        wid, sid = self.open_window("журналист", str(WORK))
        self.save({"wid": wid, "sid": sid, "chat": chat, "seen": ""})
        if not self.paste(wid, brief(topic, DRAFTS)):
            return "Окно журналиста открыл, но Claude не принял задание — откройте пульт, окно «журналист»."
        return ("Режим «журналист»: задам вопросы и напишу черновик. Отвечайте текстом или голосом. /стоп — выйти."
                + ("" if topic else "\nО чём статья?"))

    def forward(self, text: str) -> str:
        st = self.state()
        if not self.paste(st["wid"], text):
            return "Не передал — окно журналиста занято или закрыто. Попробуйте ещё раз или /стоп."
        return ""

    def stop(self) -> str:
        self.save({})
        return "Вышел из режима «журналист». Окно с черновиком осталось в пульте."

    def relay(self) -> tuple[int, str] | None:
        """Законченный новый ответ Claude → (чат владельца, текст); иначе None."""
        st = self.state()
        if not st:
            return None
        if not self.alive(st["wid"]):
            self.save({})
            return st["chat"], "Окно журналиста закрыто — режим выключен."
        ready, text, mark = self.answer(str(WORK), st["sid"])
        if not ready or not text or mark == st.get("seen"):
            return None
        self.save({**st, "seen": mark})
        return st["chat"], text


class Bot:
    def __init__(self, api, owners: list[int], save_note=None, stt=None, journalist: Journalist | None = None):
        self.api, self.owners = api, set(owners)
        self.save_note, self.stt, self.journalist = save_note, stt, journalist
        self.offset = 0

    def poll(self, timeout: int = 25) -> int:
        """Один длинный опрос: апдейты — в журнал, сообщения владельца — обработать. → сколько апдейтов."""
        if self.journalist and self.journalist.state():   # ждём ответа Claude — опрос короче, ответ приходит быстрее
            timeout = min(timeout, 3)
        ups = self.api("getUpdates", offset=self.offset, timeout=timeout, allowed_updates=ALLOWED) or []
        append(ups)
        for u in ups:
            self.offset = max(self.offset, int(u.get("update_id", 0)) + 1)
            m = u.get("message")
            if m and (m.get("chat") or {}).get("type") == "private":
                try:
                    self.on_message(m)
                except Exception as e:                    # одно сообщение не роняет службу
                    print("tgbiz: сообщение:", e, file=sys.stderr, flush=True)
        if self.journalist and (r := self.journalist.relay()):
            chat, text = r
            for i in range(0, len(text), 3900):           # длинный черновик — несколькими сообщениями
                self.reply(chat, text[i:i + 3900])
        ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        heartbeat().touch()
        return len(ups)

    def reply(self, chat: int, text: str):
        self.api("sendMessage", chat_id=chat, text=text[:4000])

    def on_message(self, m: dict):
        chat, uid = m["chat"]["id"], (m.get("from") or {}).get("id")
        if uid not in self.owners:                        # чужим в личке не отвечаем
            return
        text = (m.get("text") or "").strip()
        low = text.lower()
        for cmd in ("/заметка", "/note"):
            if low == cmd or low.startswith(cmd + " ") or low.startswith(cmd + "\n"):
                body = text[len(cmd):].strip()
                if not body:
                    return self.reply(chat, "Напишите текст после /заметка, например: /заметка Пётр платит в пт")
                tags = [w[1:].lower() for w in body.split() if w.startswith("#")]        # #задача, #идея — в «Метки»
                p = {"title": body.splitlines()[0][:120], "text": body, "source": "команда владельца в боте",
                     "tags": tags, "origin": "Личка бота"}
                out = self.save_note(p)
                where = "в Notion" if out.get("saved") == "notion" else "в файл на сервере"
                msg = f"Сохранил заметку {where}: «{p['title']}»"
                if out.get("remind"):
                    msg += "\n\nЧтобы заметки шли в Notion: " + out["remind"]
                return self.reply(chat, msg)
        j = self.journalist
        if j and (low.startswith("/журналист") or low.startswith("/journalist")):
            topic = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
            return self.reply(chat, j.start(chat, topic))
        if j and low in ("/стоп", "/stop") and j.state():
            return self.reply(chat, j.stop())
        if m.get("voice") or m.get("audio"):
            v = m.get("voice") or m.get("audio")
            text = self.stt(v["file_id"])
            if not text:
                return self.reply(chat, "Не расслышал — запишите ещё раз")
            if j and j.active():                          # в режиме журналиста голос — ответ Claude
                return self.reply(chat, j.forward(text) or "Распознал и передал журналисту:\n\n" + text)
            return self.reply(chat, "Распознал:\n\n" + text + "\n\nСохранить — /заметка и этот текст")
        if j and text and not text.startswith("/") and j.active():
            if err := j.forward(text):
                return self.reply(chat, err)
            return None
        if text in ("/start", "/help") or text:
            return self.reply(chat, HELP)


def _journalist() -> Journalist:
    """Окно Claude в tmux пульта (сессия ``main``) со своим журналом (``--session-id``); вставка — как у пульта
    (``paste_ex``: Enter и проверка, что текст ушёл); ответ — законченный ход Claude из его журнала."""
    import re
    import uuid

    from gas_pult import activity, config, harness, models
    from gas_pult.tmux import Tmux
    cfg = config.load()
    tm = Tmux(cfg.session)
    acts = activity.Journal()
    prompt = re.compile(r"^\s*❯(?!\s*\d\.)", re.M)

    def open_window(name: str, path: str) -> tuple[str, str]:
        sid = str(uuid.uuid4())
        cmd = models.command(cfg.claude, "claude", {}) + f" --session-id {sid}"
        return tm.new_window(name, path, cmd, mark="claude", sid=sid), sid

    def paste(wid: str, text: str) -> bool:
        for _ in range(40):                               # свежий Claude — дождаться строки ввода «❯»
            if prompt.search("\n".join(tm.screen(wid, 15))):
                break
            time.sleep(1)
        return bool(tm.paste_ex(wid, text).get("ok"))

    def answer(path: str, sid: str) -> tuple[bool, str, str]:
        h = harness.of({"harness": "claude"})             # окно журналиста — всегда Claude Code (open_window); R13
        st = acts.status(path, None, sid, h)
        done = st.get("phase") == "done"
        return done, h.last_answer(path, None, sid), h.revision(path, None, sid)

    return Journalist(open_window, paste, answer, lambda wid: tm.window(wid) is not None)


def run(token: str, owners: list[int]) -> None:
    """Служба: длинный опрос без конца; сбой сети — пауза с ростом до минуты; раз в час — чистка журнала."""
    from gas_pult import telegram, voice
    from gas_pult.connectors import tgbiz_mcp
    api = telegram.Api(token)
    tmp = ROOT / "voice"

    def stt(file_id: str) -> str:
        f = api.download(file_id, tmp)
        try:
            return voice.transcribe_any(f).strip()
        finally:
            f.unlink(missing_ok=True)                     # голос не храним

    bot = Bot(api, owners, save_note=tgbiz_mcp._save_note, stt=stt, journalist=_journalist())
    pause, cleaned = 1.0, 0.0
    print(f"gas-pult-tgbiz: читаю апдейты, журнал {journal()}", flush=True)
    while True:
        try:
            bot.poll()
            pause = 1.0
            if time.time() - cleaned > 3600:
                prune()
                cleaned = time.time()
        except Exception as e:
            print("tgbiz:", api.redact(str(e)) if hasattr(api, "redact") else e, file=sys.stderr, flush=True)
            time.sleep(pause)
            pause = min(60.0, pause * 2)
