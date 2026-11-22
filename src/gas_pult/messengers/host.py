"""Процесс одного моста: ``python -m gas_pult.messengers.host <svc>``.

Слушает unix-сокет ``host.sock`` (0600) в папке моста: один запрос — одна строка JSON, ответ — одна строка JSON.
Выключается сам, когда ``IDLE`` секунд никто не спрашивал (замер памяти — docs/MESSENGERS.md).

Операции: ``ping``, ``stop``, ``status`` и операции моста (``OPS`` у бэкенда: вход, QR, чаты, сообщения, входящие).
Отправки текста нет: только ``apply`` — выполнить черновик, который человек подтвердил «Да» в панели
(``_core.take_confirmed``: отпечаток ``.ok`` должен совпасть ровно с этим черновиком, выполняется один раз).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from gas_pult import messengers as M
from gas_pult.connectors import _core


class Host:
    def __init__(self, svc: str, d: Path, backend, idle: float = M.IDLE, tick: float = 5.0):
        self.svc, self.d, self.backend, self.idle, self.tick = svc, d, backend, idle, tick
        self.last = time.monotonic()
        self.done = asyncio.Event()

    async def handle(self, req: dict) -> dict:
        op = str(req.get("op") or "")
        args = {k: v for k, v in req.items() if k != "op"}
        if op == "ping":
            return {"ok": True, "pid": os.getpid()}
        if op == "stop":
            self.done.set()
            return {"ok": True}
        if op == "apply":                              # только подтверждённый человеком черновик
            rec = _core.take_confirmed(self.svc, str(args.get("id") or ""), need_flag=False)
            if rec.get("action") != "send":
                raise ValueError("мост умеет выполнить только черновик отправки")
            return await self.backend.send(rec["params"])
        if op not in getattr(self.backend, "OPS", ()):
            raise ValueError(f"нет такой операции: {op}")
        return await getattr(self.backend, op)(**args)

    async def client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            line = await reader.readline()
            busy = True
            try:
                req = json.loads(line or b"{}")
                req = req if isinstance(req, dict) else {}
                busy = req.get("op") != "ping"            # «жив?» из панели — не работа: мост всё равно уснёт
                if busy:
                    self.last = time.monotonic()
                res = await self.handle(req)
            except _core.ToolError as e:
                res = {"error": str(e)}
            except Exception as e:                    # ошибка моста — текстом, процесс живёт дальше
                res = {"error": f"{type(e).__name__}: {e}"[:400]}
            if busy:
                self.last = time.monotonic()
            writer.write((json.dumps(res, ensure_ascii=False, default=str) + "\n").encode())
            await writer.drain()
        finally:
            writer.close()

    async def run(self):
        sock = self.d / "host.sock"
        sock.unlink(missing_ok=True)
        old = os.umask(0o077)                          # сокет — только владельцу папки
        try:
            server = await asyncio.start_unix_server(self.client, path=str(sock))
        finally:
            os.umask(old)
        sock.chmod(0o600)
        try:
            await self.backend.start()
            while not self.done.is_set():
                try:
                    await asyncio.wait_for(self.done.wait(), self.tick)
                except TimeoutError:
                    pass
                if time.monotonic() - self.last > self.idle:
                    break                              # сон по простою: выходим, следующий запрос запустит снова
        finally:
            server.close()
            sock.unlink(missing_ok=True)
            try:
                await asyncio.wait_for(self.backend.stop(), 10)
            except Exception:
                pass


def backend_for(svc: str, d: Path):
    if svc == "telegram":
        from gas_pult.messengers.tg import Telegram
        return Telegram(d)
    if svc == "signal":
        from gas_pult.messengers.signal_cli import Signal
        return Signal(d, M.signal_bin())
    if svc == "whatsapp":
        from gas_pult.messengers.wa import WhatsApp
        return WhatsApp(d, M.node(), M.baileys_dir())
    raise ValueError("нет такого мессенджера")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] not in M.SERVICES:
        print("использование: python -m gas_pult.messengers.host telegram|signal|whatsapp", file=sys.stderr)
        return 2
    svc = argv[0]
    if not M.consented(svc):                           # второй замок: без выбора человека мост не стартует
        print("нет выбора человека (consent.json) — мост не запускается", file=sys.stderr)
        return 3
    d = M.svc_dir(svc)
    asyncio.run(Host(svc, d, backend_for(svc, d), idle=float(os.environ.get("GAS_MSG_IDLE") or M.IDLE)).run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
