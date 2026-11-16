"""Служба бота Telegram Business (``gas-pult tgbiz run``, юнит ``gas-pult-tgbiz``): одна точка чтения апдейтов.

Решение владельца 16.11 («1 да»): апдейты бота читает только эта служба (``getUpdates`` со своим offset) и кладёт их в
локальный журнал ``~/.local/state/gas-pult/tgbiz/updates.jsonl`` (0600, 7 дней). Коннектор ``tgbiz_mcp`` читает этот
журнал, а не Telegram, — второй читатель не забирает апдейты у первого, ничего не теряется.

Владелец пишет боту в личный чат:
- ``/заметка <текст>`` (``/note``) — заметка сразу (команда владельца и есть подтверждение): Notion, если настроен,
  иначе локальный файл (``tgbiz_mcp._save_note``);
- голосовое — текст на этом сервере (локальный ASR, ``voice.transcribe_any``); в чужие сервисы голос не уходит;
- остальное — подсказка. Режим «журналист» — следующим шагом (окно Claude в пульте со скиллом zhurnalist).
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


class Bot:
    def __init__(self, api, owners: list[int], save_note=None, stt=None):
        self.api, self.owners = api, set(owners)
        self.save_note, self.stt = save_note, stt
        self.offset = 0

    def poll(self, timeout: int = 25) -> int:
        """Один длинный опрос: апдейты — в журнал, сообщения владельца — обработать. → сколько апдейтов."""
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
                p = {"title": body.splitlines()[0][:120], "text": body, "source": "команда владельца в боте",
                     "tags": []}
                out = self.save_note(p)
                where = "в Notion" if out.get("saved") == "notion" else "в файл на сервере"
                msg = f"Сохранил заметку {where}: «{p['title']}»"
                if out.get("remind"):
                    msg += "\n\nЧтобы заметки шли в Notion: " + out["remind"]
                return self.reply(chat, msg)
        if m.get("voice") or m.get("audio"):
            v = m.get("voice") or m.get("audio")
            text = self.stt(v["file_id"])
            if not text:
                return self.reply(chat, "Не расслышал — запишите ещё раз")
            return self.reply(chat, "Распознал:\n\n" + text + "\n\nСохранить — /заметка и этот текст")
        if text in ("/start", "/help") or text:
            return self.reply(chat, HELP)


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

    bot = Bot(api, owners, save_note=tgbiz_mcp._save_note, stt=stt)
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
