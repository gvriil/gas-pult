"""Telegram — свой аккаунт человека через MTProto (Telethon, официальный клиентский API со своим api_id).

Работает внутри процесса моста (``host.py``), запущенного Python с Telethon (``messengers.telethon_python``).
Вход: номер → код (приходит в приложение Telegram или SMS) → облачный пароль, если включён. Номер не хранится
(в ``account.json`` — только последние 4 цифры); сессия — ``tg.session`` (0600), api_id/api_hash — ``api.json`` (0600).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from gas_pult import messengers as M


class Telegram:
    OPS = ("status", "login", "code", "password", "chats", "messages", "inbox")

    def __init__(self, d: Path, session: str | None = None, api: dict | None = None):
        self.d, self.session = d, session or str(d / "tg")
        self.api, self.client, self.phone, self.hash = api, None, "", ""

    def _api(self) -> dict:
        api = self.api or M.read_json(self.d / "api.json")
        if not isinstance(api, dict) or not api.get("api_id") or not api.get("api_hash"):
            raise ValueError("нет api_id и api_hash — введите их на экране подключения")
        return api

    async def _client(self):
        if self.client is None:
            from telethon import TelegramClient  # только в процессе моста (внешний пакет)
            api = self._api()
            old = os.umask(0o077)                          # файл сессии — 0600 с рождения
            try:
                self.client = TelegramClient(self.session, int(api["api_id"]), str(api["api_hash"]),
                                             device_model="gas-pult", app_version="gas-pult")
                await self.client.connect()
            finally:
                os.umask(old)
        return self.client

    def _secure(self):
        f = Path(self.session + ".session")
        if f.exists():
            f.chmod(0o600)

    async def start(self):
        if (self.d / "api.json").is_file() or self.api:
            try:
                await self._client()
            except Exception:                              # нет сети — подключимся при первом запросе
                self.client = None

    async def stop(self):
        if self.client is not None:
            await self.client.disconnect()
            self.client = None

    async def status(self) -> dict:
        c = await self._client()
        return {"authorized": bool(await c.is_user_authorized())}

    async def login(self, phone: str = "") -> dict:
        phone = "+" + re.sub(r"\D", "", str(phone))
        if not 8 <= len(phone) <= 16:
            raise ValueError("номер — с кодом страны, например +7 999 123-45-67")
        c = await self._client()
        sent = await c.send_code_request(phone)
        self.phone, self.hash = phone, sent.phone_code_hash
        where = {"SentCodeTypeApp": "app", "SentCodeTypeSms": "sms"}.get(type(sent.type).__name__, "other")
        return {"sent": where}

    async def _done(self) -> dict:
        me = await self.client.get_me()
        who = M.mask(getattr(me, "phone", "") or self.phone)
        M.write_private(self.d / "account.json", json.dumps({"connected": True, "who": who}))
        self._secure()
        self.phone = self.hash = ""
        return {"ok": True, "who": who}

    async def code(self, code: str = "") -> dict:
        from telethon.errors import SessionPasswordNeededError
        if not self.hash:
            raise ValueError("сначала запросите код")
        try:
            await self.client.sign_in(phone=self.phone, code=re.sub(r"\D", "", str(code)),
                                      phone_code_hash=self.hash)
        except SessionPasswordNeededError:
            return {"need": "password"}
        return await self._done()

    async def password(self, password: str = "") -> dict:
        await self.client.sign_in(password=str(password))
        return await self._done()

    async def chats(self, limit: int = 40) -> dict:
        c = await self._client()
        out = []
        async for d in c.iter_dialogs(limit=min(int(limit), 200)):
            kind = "user" if d.is_user else "group" if d.is_group else "channel"
            out.append({"id": str(d.id), "name": d.name or "", "unread": d.unread_count, "kind": kind})
        return {"chats": out}

    async def messages(self, chat: str = "", limit: int = 30) -> dict:
        c = await self._client()
        out = []
        async for m in c.iter_messages(int(chat), limit=min(int(limit), 200)):
            s = m.sender
            name = " ".join(x for x in (getattr(s, "first_name", "") or "", getattr(s, "last_name", "") or "") if x)
            out.append({"id": m.id, "ts": m.date.timestamp() if m.date else 0, "out": bool(m.out),
                        "from": name or getattr(s, "title", "") or "", "text": m.text or ("[файл]" if m.file else "")})
        out.reverse()
        return {"messages": out}

    async def inbox(self, since: float = 0, limit: int = 20) -> dict:
        """Непрочитанные входящие (до 3 последних на чат) новее ``since`` — для «Сегодня». Отметку «прочитано» не
        ставит: человек прочитает сам."""
        c = await self._client()
        out = []
        async for d in c.iter_dialogs(limit=60):
            if not d.unread_count or d.archived:
                continue
            async for m in c.iter_messages(d.entity, limit=min(d.unread_count, 3)):
                ts = m.date.timestamp() if m.date else 0
                if m.out or ts < float(since):
                    continue
                s = m.sender
                who = getattr(s, "first_name", "") or getattr(s, "title", "") or ""
                out.append({"chat": str(d.id), "name": d.name or "", "from": who, "ts": ts,
                            "text": (m.text or ("[файл]" if m.file else ""))[:300]})
            if len(out) >= int(limit):
                break
        return {"items": out}

    async def send(self, params: dict) -> dict:
        c = await self._client()
        await c.send_message(int(params["chat"]), str(params["text"]))
        return {"ok": True, "sent": True}
