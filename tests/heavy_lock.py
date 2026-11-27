"""Один тяжёлый прогон на сервер (штаб 23.11: в 21:00 панель и браузер агента убил OOM — два полных pytest шли сразу).

Замок — flock на общий файл в ``$XDG_RUNTIME_DIR`` (или /tmp): второй прогон ждёт, пока закончится первый, и пишет,
кого ждёт. Замок держится до выхода процесса — ядро снимает flock само, даже после kill -9.
Дочерние процессы (``GAS_PULT_HEAVY_LOCK_HELD``) замок родителя не ждут.

- ``pytest``  — полный прогон (от ``BIG`` тестов; берёт tests/conftest.py, точечные прогоны идут без очереди);
- ``browser`` — e2e с браузером (``import _onebrowser`` в tests/e2e/*.py).

В CI (``CI=true``) и при ``GAS_PULT_TEST_LOCK=0`` замка нет. Ожидание — до ``GAS_PULT_TEST_LOCK_WAIT`` секунд
(по умолчанию 3600), потом ошибка.
"""

from __future__ import annotations

import fcntl
import os
import sys
import time

BIG = 300          # столько тестов и больше — «полный прогон»
_held: dict[str, int] = {}


def path(kind: str) -> str:
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return os.path.join(base, f"gas-pult-{kind}.lock")


def off() -> bool:
    return os.environ.get("CI") == "true" or os.environ.get("GAS_PULT_TEST_LOCK") == "0"


def hold(kind: str, what: str = "") -> bool:
    """Взять замок ``kind`` на время жизни процесса. False — замок выключен."""
    if off():
        return False
    held = os.environ.get("GAS_PULT_HEAVY_LOCK_HELD", "").split(",")
    if kind in _held or kind in held:   # замок у родителя (e2e запускает панель дочерним процессом) — не ждать себя
        return True
    fd = os.open(path(kind), os.O_RDWR | os.O_CREAT, 0o600)
    limit = float(os.environ.get("GAS_PULT_TEST_LOCK_WAIT", "3600"))
    start = time.monotonic()
    said = False
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if not said:
                who = os.pread(fd, 200, 0).decode(errors="replace").strip() or "?"
                print(f"[gas-pult] жду: идёт другой тяжёлый прогон ({kind}: {who}) — по одному, чтобы не кончилась "
                      "память; без очереди — GAS_PULT_TEST_LOCK=0", file=sys.stderr, flush=True)
                said = True
            if time.monotonic() - start > limit:
                os.close(fd)
                raise TimeoutError(f"замок {path(kind)} не освободился за {limit:.0f} с") from None
            time.sleep(2)
    os.ftruncate(fd, 0)
    os.pwrite(fd, f"pid {os.getpid()} {what}".strip().encode(), 0)
    _held[kind] = fd   # не закрываем: замок живёт до выхода процесса
    os.environ["GAS_PULT_HEAVY_LOCK_HELD"] = ",".join(filter(None, [*held, kind]))   # детям — «замок уже наш»
    return True
