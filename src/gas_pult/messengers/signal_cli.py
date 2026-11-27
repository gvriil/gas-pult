"""Signal — signal-cli как связанное устройство (как Signal Desktop). Неофициальный способ: см. экран выбора.

signal-cli ставит человек сам (``messengers.need_install``); данные signal-cli — ``data/`` в папке моста (0700).
Привязка: ``signal-cli link`` печатает ссылку ``sgnl://linkdevice…`` → панель рисует QR → человек сканирует телефоном
(Signal → Настройки → Связанные устройства). Пока не отсканировал — привязки нет, ничего не меняется.
Каждая команда signal-cli — короткий процесс; сам мост спит по простою (``host.py``).
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

from gas_pult import messengers as M

NUM = re.compile(r"\+\d{6,16}")


class Signal:
    OPS = ("status", "link", "chats", "messages", "inbox")

    def __init__(self, d: Path, cli: str):
        self.d, self.cli = d, cli
        self.data = d / "data"
        self.data.mkdir(exist_ok=True, mode=0o700)
        self.proc, self.uri, self.linking = None, "", None

    def _number(self) -> str:
        acc = M.read_json(self.d / "account.json") or {}
        return str(acc.get("number") or "")

    async def _run(self, *args: str, timeout: float = 60) -> str:
        p = await asyncio.create_subprocess_exec(self.cli, "--config", str(self.data), *args,
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(p.communicate(), timeout)
        except TimeoutError:
            p.kill()
            raise RuntimeError("signal-cli не ответил вовремя") from None
        if p.returncode:
            raise RuntimeError("signal-cli: " + (err.decode("utf-8", "replace").strip().splitlines() or ["ошибка"])[-1])
        return out.decode("utf-8", "replace")

    async def start(self):
        pass

    async def stop(self):
        if self.proc and self.proc.returncode is None:
            self.proc.kill()

    async def status(self) -> dict:
        return {"linked": bool(self._number()), "linking": bool(self.proc and self.proc.returncode is None)}

    async def link(self) -> dict:
        """Ссылка для QR. Процесс ``link`` ждёт скана (несколько минут); отсканировали — номер в account.json."""
        if self._number():
            return {"linked": True}
        if self.proc and self.proc.returncode is None and self.uri:
            return {"uri": self.uri}
        self.proc = await asyncio.create_subprocess_exec(
            self.cli, "--config", str(self.data), "link", "-n", "gas-pult",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        self.uri = ""
        until = time.monotonic() + 40
        while time.monotonic() < until:
            line = await asyncio.wait_for(self.proc.stdout.readline(), max(0.1, until - time.monotonic()))
            if not line:
                break
            text = line.decode("utf-8", "replace").strip()
            if text.startswith("sgnl://"):
                self.uri = text
                self.linking = asyncio.ensure_future(self._wait_link())
                return {"uri": text}
        raise RuntimeError("signal-cli не выдал ссылку для QR")

    async def _wait_link(self):
        rest = (await self.proc.stdout.read()).decode("utf-8", "replace")
        await self.proc.wait()
        m = NUM.search(rest)
        if self.proc.returncode == 0 and m:
            M.write_private(self.d / "account.json",
                            json.dumps({"connected": True, "who": M.mask(m.group(0)), "number": m.group(0)}))
        self.uri = ""

    async def _receive(self):
        num = self._number()
        if not num:
            raise ValueError("Signal не привязан — отсканируйте QR")
        out = await self._run("-a", num, "-o", "json", "receive", "-t", "2", "--ignore-attachments", timeout=60)
        items = []
        for line in out.splitlines():
            try:
                env = json.loads(line).get("envelope") or {}
            except ValueError:
                continue
            dm = env.get("dataMessage") or {}
            if not dm.get("message"):
                continue
            group = ((dm.get("groupInfo") or {}).get("groupId")) or ""
            items.append({"chat": ("g:" + group) if group else str(env.get("sourceNumber") or env.get("sourceUuid")),
                          "name": env.get("sourceName") or "", "from": env.get("sourceName") or "",
                          "ts": float(env.get("timestamp") or 0) / 1000, "text": str(dm["message"])[:2000]})
        M.inbox_append(self.d, items)

    async def inbox(self, since: float = 0) -> dict:
        await self._receive()
        return {"items": M.inbox_read(self.d, float(since))}

    async def chats(self, limit: int = 40) -> dict:
        await self._receive()
        seen: dict[str, dict] = {}
        for x in M.inbox_read(self.d):
            seen[x["chat"]] = {"id": x["chat"], "name": x.get("name") or x["chat"], "last": x.get("ts")}
        return {"chats": sorted(seen.values(), key=lambda c: -(c["last"] or 0))[:int(limit)]}

    async def messages(self, chat: str = "", limit: int = 30) -> dict:
        await self._receive()
        return {"messages": M.inbox_read(self.d, chat=str(chat))[-int(limit):]}

    async def send(self, params: dict) -> dict:
        to = str(params["chat"])
        target = ["-g", to[2:]] if to.startswith("g:") else [to]
        await self._run("-a", self._number(), "send", "-m", str(params["text"]), *target)
        return {"ok": True, "sent": True}
