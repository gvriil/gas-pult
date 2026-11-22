"""«Да» человека на черновик действия — только в памяти службы панели (штаб 22.11: обход «Да» агентом).

Раньше «Да» было файлом ``<id>.ok`` рядом с черновиком (``connectors/_core.confirm``, ``gas-pult bridge-confirm``).
Агент работает от того же пользователя Linux, что и пульт: он мог сам создать этот файл или вызвать команду —
и выполнить действие без человека. Теперь отметки на диске ничего не значат. «Да» живёт только здесь, в памяти
процесса панели (``webapp``): его кладёт кнопка «Да» в панели — запрос с сессией человека (cookie ``SameSite=Strict``
и проверка ``Origin``), для пространства — только его человек. Коннектор перед выполнением спрашивает панель
(``POST /api/drafts/check``) и получает «да» один раз. Память чужого процесса агенту не прочитать
(``kernel.yama.ptrace_scope=1``: отлаживать можно только своих потомков).

Что остаётся открытым без отдельного пользователя Linux — docs/BRIDGE.md, «Граница «Да»».

Ключ — (пространство или "" для владельца, сервис, id черновика); значение — отпечаток черновика (``_core._digest``)
и срок. Отпечаток сверяется: подменили параметры после «Да» — не выполнится. Одноразово, срок ``TTL``.
"""

from __future__ import annotations

import threading
import time

TTL = 30 * 60                     # «Да» действует 30 минут: агент выполняет сразу, долгий запас не нужен


class Approvals:
    def __init__(self, ttl: int = TTL, now=time.monotonic):
        self.ttl, self.now = ttl, now
        self._d: dict[tuple[str, str, str], tuple[str, float]] = {}
        self._lock = threading.Lock()

    def _gc(self) -> None:
        t = self.now()
        for k in [k for k, (_, exp) in self._d.items() if exp <= t]:
            del self._d[k]

    def grant(self, scope: str, svc: str, pid: str, digest: str) -> None:
        """Человек нажал «Да» в панели. Вызывает только обработчик запроса с сессией человека."""
        with self._lock:
            self._gc()
            self._d[(scope or "", svc, pid)] = (str(digest), self.now() + self.ttl)

    def pending(self, scope: str, svc: str, pid: str) -> bool:
        """«Да» уже есть, ещё не выполнено (панель не показывает такой черновик снова)."""
        with self._lock:
            self._gc()
            return (scope or "", svc, pid) in self._d

    def take(self, scope: str, svc: str, pid: str, digest: str) -> bool:
        """Коннектор спрашивает перед выполнением: «Да» есть и отпечаток тот же — да, один раз."""
        with self._lock:
            self._gc()
            v = self._d.get((scope or "", svc, pid))
            if not v or v[0] != str(digest):
                return False
            del self._d[(scope or "", svc, pid)]
            return True
