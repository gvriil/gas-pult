"""Telegram бота: отправка (куски, пауза 429), каналы доставки владельцам, реакции, маршруты ответов (reply → окно).

Часть класса ``bot.Pult`` (модульный монолит, docs/MONOLITH-PLAN.md п.3.3): методы перенесены как есть, ``self`` —
тот же ``Pult``. ``MENU`` (клавиатура бота) живёт здесь; ``bot.MENU`` — то же имя.
"""

from __future__ import annotations

import re
import threading
import time

from gas_pult import brand, emailcode, harness, injection_guard, notifyroute, spaces, tglinks, tgroutes, webpush
from gas_pult.telegram import TelegramError

MENU = {"keyboard": [[{"text": "🆕 Новая"}, {"text": "🔀 Переключить"}, {"text": "📊 Сводка"}],
                     [{"text": "⚡ Команды"}, {"text": "📋 Окна"}, {"text": "⚙️ Настройки"}]],
        "resize_keyboard": True, "is_persistent": True}


class TelegramPart:
    """Отправка в Telegram и доставка владельцам (примесь к ``Pult``)."""

    pause_until = 0.0          # Telegram ответил 429 — до этого времени не шлём (повторы только продлевают запрет)
    skipped = 0                # сколько сообщений не отправили за паузу — сказать одним сообщением после неё

    # ---------- Telegram ----------
    def send(self, chat: int, text: str, wid: str | None = None, **kw) -> dict:
        """``wid`` — окно, о котором сообщение: ответ (reply) на любой его кусок уйдёт в это окно (``tgroutes``)."""
        if (left := self.pause_until - time.time()) > 0:
            self.skipped += 1
            raise TelegramError("sendMessage", f"лимит Telegram — пауза ещё {left:.0f} с")
        parts = [text[i:i + 4000] for i in range(0, max(len(text), 1), 4000)] or ["—"]   # лимит — 4096
        r = {}
        try:
            for i, c in enumerate(parts):  # кнопки — под последним куском
                r = self.api("sendMessage", chat_id=chat, text=c or "—", **(kw if i == len(parts) - 1 else {}))
                if wid:
                    self.bind(chat, r, wid)
        except TelegramError as e:
            if e.retry_after:
                self.pause_until = time.time() + e.retry_after
                self.skipped += 1
            raise
        return r or {}

    def bind(self, chat, r, wid: str):
        """Запомнить окно сообщения бота (заготовки ``Pult.__new__`` в тестах — без карты)."""
        routes = getattr(self, "routes", None)
        if routes and isinstance(r, dict):
            routes.bind(chat, r.get("message_id"), wid)

    def send_answer(self, chat: int, head: str, text: str, wid: str | None = None, **kw) -> dict:
        """Ответ Claude — HTML (tglinks): адреса нажимаемые и в `коде`, и без схемы; под блоком кода — «Ссылки: …».
        Куски по 4000 с целыми тегами, кнопки — под последним. Telegram не разобрал разметку — тот же ответ текстом."""
        if spaces.split(wid)[0]:                         # пространство клиента: ПДн в ответе — маской (GAS-16)
            text = injection_guard.mask_pii(text)[0]
        chunks, r = tglinks.messages(text, head), {}
        try:
            for i, c in enumerate(chunks):
                r = self.send(chat, c, parse_mode="HTML", wid=wid, **(kw if i == len(chunks) - 1 else {}))
        except TelegramError as e:
            if e.retry_after or "parse" not in e.description.lower() or i:
                raise
            return self.send(chat, f"{head}\n{text}", wid=wid, **kw)
        return r

    def after_pause(self):
        """Пауза 429 кончилась — одно сообщение вместо пропущенных."""
        if self.skipped and time.time() >= self.pause_until:
            n, self.skipped = self.skipped, 0
            self.broadcast(f"⏸ Telegram на время ограничил частоту сообщений — {n} уведомл. не отправлено. "
                           "Ответы Claude — в панели.")

    def broadcast(self, text: str, kind: str = "error", **kw):
        """Одна точка доставки владельцам (notifyroute.py): Telegram, телефон и почта — что выбрал каждый.
        ``kind`` — вид события (answer, dialog, error, brief, people); кнопки решения — всегда и в Telegram."""
        for chat in self.cfg.owners:
            ch = self.channels(chat, kind, action="reply_markup" in kw)
            if "telegram" in ch:
                try:
                    self.send(chat, text, **kw)
                except TelegramError as e:
                    print("send:", e, flush=True)
            if "push" in ch:
                self.push_one(chat, text)
            if "email" in ch:
                self.mail_one(chat, text)

    def _hub(self):
        return self.__dict__.setdefault("_push", webpush.Hub(self.cfg.data / "push"))

    def channels(self, uid: int, kind: str, action: bool = False) -> set[str]:
        """Каналы владельца ``uid`` для события ``kind``. Бот без данных (заготовка в тестах) — только Telegram."""
        cfg = getattr(self, "cfg", None)
        if cfg is None or not getattr(cfg, "data", None):
            return {"telegram"}
        try:
            push = bool(self._hub().devices(uid))
        except (OSError, ValueError):
            push = False
        mail, email = getattr(self, "mail", None), False
        try:
            rec = mail.people.email(uid) if mail is not None and mail.enabled else {}
            email = bool(rec.get("notify") and rec.get("address"))
        except (AttributeError, OSError, ValueError):
            email = False
        rec = notifyroute.Store(cfg.data / "notify_channels.json").get(uid)
        return notifyroute.route(rec, kind, push=push, email=email, action=action)

    def push_one(self, uid: int, text: str, w: str = "", title: str = brand.NAME_RU):
        try:
            self._hub().notify(uid, title, self.PUSH_PLAIN.sub("", str(text or "")).strip(), w)
        except (OSError, ValueError) as e:
            print("push:", e, flush=True)

    def mail_one(self, uid: int, text: str, subject: str = ""):
        """Письмо в фоне: SMTP не задерживает монитор."""
        body = self.PUSH_PLAIN.sub("", str(text or "")).strip()
        subject = subject or body.split("\n", 1)[0][:80] or brand.NAME_RU
        threading.Thread(target=emailcode.notify_email, args=(self.mail, uid, subject, body), daemon=True).start()

    PUSH_PLAIN = re.compile(r"^[^\w«\[(]+")                       # значок-эмодзи в начале — не в заголовок пуша

    def push_owners(self, text: str, w: str = "", title: str = brand.NAME_RU, kind: str = "dialog"):
        """На телефон (Web Push, webpush.py) тем владельцам, у кого есть устройства и выбран этот вид событий."""
        cfg = getattr(self, "cfg", None)
        if cfg is None or not getattr(cfg, "data", None):
            return
        for uid in cfg.owners:
            if "push" in self.channels(uid, kind):
                self.push_one(uid, text, w, title)

    def to(self, chat: int):
        return lambda text, **kw: self.send(chat, text, **kw)

    def react(self, m: dict, emoji: str):
        try:
            self.api("setMessageReaction", chat_id=m["chat"]["id"], message_id=m["message_id"],
                     reaction=[{"type": "emoji", "emoji": emoji}])
        except TelegramError:
            pass

    def reply_target(self, chat: int, m: dict):
        """Окно, на сообщение которого человек ответил (reply) в Telegram; None — не ответ на сообщение окна
        (пишем в активное); False — окно найдено, но его уже нет или Claude там остановлен: сказали человеку.
        Порядок: карта ``tg_routes.json`` → кнопки исходного сообщения → «[имя]», если такое окно одно."""
        rt = m.get("reply_to_message") or {}
        if not rt or not (rt.get("from") or {}).get("is_bot"):
            return None
        routes = getattr(self, "routes", None)
        wid = (routes.get(chat, rt.get("message_id")) if routes else None) or tgroutes.markup_wid(rt)
        ws = self.tmux.windows() if not wid else []
        if not wid and (name := tgroutes.head_name(rt)):
            same = [x for x in ws if x["name"] == name] or [x for x in ws if self.label(x) == name]   # 20.11
            wid = same[0]["id"] if len(same) == 1 else None
        if not wid:
            return None
        w = self.tmux.window(wid)
        if w and harness.is_agent(w):
            return w
        self.send(chat, ("Сессии этого сообщения уже нет" if not w else f"В «{self.label(w)}» Claude остановлен")
                  + " — текст не отправил. Ответьте на сообщение живой сессии или выберите окно в 🔀 Переключить.",
                  reply_markup=MENU)
        return False
