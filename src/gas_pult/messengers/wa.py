"""WhatsApp — связанное устройство через Baileys на Node (неофициальный способ: см. экран выбора).

Почему Baileys, а не whatsmeow: на сервере пульта есть Node, а Go нет; Baileys ставится одной командой npm в папку
данных (без сборки), версия зафиксирована (``messengers.BAILEYS``). Node-процесс ``wa_bridge.mjs`` живёт, пока живёт
мост (``host.py``), и выходит вместе с ним — по простою.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import shutil
import time
from pathlib import Path

from gas_pult import messengers as M

SCRIPT = Path(__file__).with_name("wa_bridge.mjs")


class WhatsApp:
    OPS = ("status", "link", "chats", "messages", "inbox")

    def __init__(self, d: Path, node: str, mods: Path):
        self.d, self.node, self.mods = d, node, mods
        self.auth = d / "auth"
        self.proc, self.reader, self.qr, self.open = None, None, "", False
        self.started, self.waits = 0.0, {}

    def _linked(self) -> bool:
        return bool(M.account("whatsapp")) and (self.auth / "creds.json").is_file()

    async def _spawn(self):
        if self.proc and self.proc.returncode is None:
            return
        self.auth.mkdir(exist_ok=True, mode=0o700)
        script = self.mods / SCRIPT.name                # рядом с node_modules: так Node найдёт Baileys
        if not script.is_file() or script.read_bytes() != SCRIPT.read_bytes():
            shutil.copyfile(SCRIPT, script)
        self.proc = await asyncio.create_subprocess_exec(
            self.node, str(script), str(self.auth), cwd=str(self.mods), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=1 << 20)
        self.started, self.qr, self.open = time.monotonic(), "", False
        self.reader = asyncio.ensure_future(self._read())

    async def _read(self):
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            kind = ev.get("ev")
            if kind == "qr":
                self.qr = str(ev.get("qr") or "")
            elif kind == "open":
                self.open, self.qr = True, ""
                M.write_private(self.d / "account.json",
                                json.dumps({"connected": True, "who": M.mask(str(ev.get("who") or ""))}))
            elif kind == "msg":
                M.inbox_append(self.d, [{k: ev.get(k) for k in ("chat", "name", "from", "ts", "text")}])
            elif kind == "sent" and (fut := self.waits.pop(str(ev.get("rid")), None)) and not fut.done():
                fut.set_result(ev)
            elif kind == "close" and ev.get("reason") == "logged_out":   # телефон отвязал устройство
                (self.d / "account.json").unlink(missing_ok=True)
                shutil.rmtree(self.auth, ignore_errors=True)
                self.open = False

    async def start(self):
        if self._linked():                              # привязан — сразу на связь: входящие придут сами
            await self._spawn()

    async def stop(self):
        if self.proc and self.proc.returncode is None:
            self.proc.stdin.close()
            try:
                await asyncio.wait_for(self.proc.wait(), 5)
            except TimeoutError:
                self.proc.kill()

    async def status(self) -> dict:
        return {"linked": self._linked(), "open": self.open, "qr": bool(self.qr)}

    async def link(self) -> dict:
        """QR для привязки: строка Baileys (панель рисует картинку). Привязан — ``linked``."""
        if self._linked() and self.open:
            return {"linked": True}
        await self._spawn()
        until = time.monotonic() + 25
        while time.monotonic() < until:
            if self.open:
                return {"linked": True}
            if self.qr:
                return {"uri": self.qr}
            if self.proc.returncode is not None:
                raise RuntimeError("мост WhatsApp завершился — проверьте установку Baileys")
            await asyncio.sleep(0.2)
        raise RuntimeError("WhatsApp не выдал QR за 25 секунд — попробуйте ещё раз")

    async def _fresh(self):
        """Только что запустились — дать WhatsApp пару секунд дослать то, что пришло, пока мост спал."""
        await self._spawn()
        wait = 4 - (time.monotonic() - self.started)
        if wait > 0:
            await asyncio.sleep(wait)

    async def inbox(self, since: float = 0) -> dict:
        if self._linked():
            await self._fresh()
        return {"items": M.inbox_read(self.d, float(since))}

    async def chats(self, limit: int = 40) -> dict:
        await self.inbox()
        seen: dict[str, dict] = {}
        for x in M.inbox_read(self.d):
            seen[x["chat"]] = {"id": x["chat"], "name": x.get("name") or x["chat"], "last": x.get("ts")}
        return {"chats": sorted(seen.values(), key=lambda c: -(c["last"] or 0))[:int(limit)]}

    async def messages(self, chat: str = "", limit: int = 30) -> dict:
        await self.inbox()
        return {"messages": M.inbox_read(self.d, chat=str(chat))[-int(limit):]}

    async def send(self, params: dict) -> dict:
        await self._fresh()
        if not self.open:
            raise RuntimeError("WhatsApp не на связи — попробуйте через минуту")
        rid = secrets.token_hex(4)
        fut = asyncio.get_running_loop().create_future()
        self.waits[rid] = fut
        self.proc.stdin.write((json.dumps({"op": "send", "to": str(params["chat"]), "text": str(params["text"]),
                                           "rid": rid}, ensure_ascii=False) + "\n").encode())
        await self.proc.stdin.drain()
        ev = await asyncio.wait_for(fut, 30)
        if ev.get("error"):
            raise RuntimeError("WhatsApp: " + str(ev["error"]))
        return {"ok": True, "sent": True}
