"""Хранилище паролей pass (GPG) на сервере пульта (задача 40): заблокировано или нет, и как разблокировать.

Ключ GPG держит ``gpg-agent`` (кэш — ``max-cache-ttl`` в ``~/.gnupg/gpg-agent.conf``, на сервере владельца — 30 дней,
до перезагрузки). Разблокирует ``~/.local/bin/pass-unlock``: один раз спрашивает пароль ключа (символы не видны,
loopback-pinentry). Пульт пароль не спрашивает и не хранит: он только

- проверяет заранее — ``gpg --batch --pinentry-mode error -d`` любого файла хранилища (тот же способ, что у
  ``pass-unlock``): расшифровалось — разблокировано; ``needs`` — команда «Выполнить» с ``pass``/``gpg``;
- открывает окно tmux с ``pass-unlock`` — пароль вводят в нём: в терминале (Termius) или в панели в браузере.
  В Telegram (бот, Mini App) пароль не вводится.

Когда разблокировали — пульт замечает сам (``status``) и пишет в ``state.json`` (``pass_at``, ``pass_boot``):
«разблокирован до» = тогда + ``max-cache-ttl``. Перезагрузка (другой ``boot_id``) — отметка сбрасывается.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path

NEEDS = re.compile(r"(?:^|[\s;&|(`$])(?:pass|gpg2?)(?=\s|$)")
WINDOW = "pass-unlock"
CACHE = 60                                   # с: проверка — не чаще раза в минуту (кроме fresh)
DEFAULT_TTL = 7200                           # gpg-agent по умолчанию: max-cache-ttl 2 ч
_cache: dict[str, tuple[float, bool | None]] = {}


def store() -> Path:
    return Path(os.environ.get("PASSWORD_STORE_DIR") or Path.home() / ".password-store")


def sample() -> Path | None:
    """Любой файл хранилища — на нём и проверяем."""
    try:
        return next(store().rglob("*.gpg"), None)
    except OSError:
        return None


def script() -> str | None:
    """Команда разблокировки: ``pass-unlock`` в PATH или в ``~/.local/bin``."""
    p = shutil.which("pass-unlock") or str(Path.home() / ".local/bin/pass-unlock")
    return p if os.access(p, os.X_OK) else None


def needs(cmd: str) -> bool:
    """Команде нужен pass/gpg (``pass show …``, ``… | gpg -d``)."""
    return bool(NEEDS.search(str(cmd or "")))


def unlocked(fresh: bool = False, runner=subprocess.run) -> bool | None:
    """True — ключ в кэше gpg-agent; False — заблокировано; None — хранилища или gpg нет (проверять нечего)."""
    hit = _cache.get("s")
    if hit and not fresh and time.time() - hit[0] < CACHE:
        return hit[1]
    f = sample()
    if f is None or not shutil.which("gpg"):
        res = None
    else:
        try:
            r = runner(["gpg", "--batch", "--pinentry-mode", "error", "-q", "-d", str(f)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=15)
            res = r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            res = False
    _cache["s"] = (time.time(), res)
    return res


def ttl(conf: Path | None = None) -> int:
    """``max-cache-ttl`` из ``gpg-agent.conf`` (с: сколько ключ держится после ввода пароля)."""
    conf = conf or Path(os.environ.get("GNUPGHOME") or Path.home() / ".gnupg") / "gpg-agent.conf"
    try:
        for line in conf.read_text().splitlines():
            parts = line.split("#", 1)[0].split()
            if len(parts) == 2 and parts[0] == "max-cache-ttl" and parts[1].isdigit():
                return int(parts[1])
    except OSError:
        pass
    return DEFAULT_TTL


def boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return ""


def status(state: dict, set_state=None, fresh: bool = False, runner=subprocess.run, now: float | None = None) -> dict:
    """{state: unlocked/locked/absent, until, script} для «Настройки → Сервер». Заметили разблокировку — запомнили
    время (``set_state``), чтобы показать «до <дата>»; заблокировано или перезагрузка — отметку сбросили."""
    now = time.time() if now is None else now
    ok = unlocked(fresh, runner)
    if ok is None:
        return {"state": "absent", "until": None, "script": bool(script())}
    boot = boot_id()
    at = state.get("pass_at") if state.get("pass_boot") == boot else None
    if ok and not at:
        at = now
        if set_state:
            set_state(pass_at=at, pass_boot=boot)
    elif not ok and state.get("pass_at") and set_state:
        set_state(pass_at=None, pass_boot=None)
    return {"state": "unlocked" if ok else "locked", "until": int(at + ttl()) if ok and at else None,
            "script": bool(script())}


def open_window(tmux) -> str:
    """Окно tmux с ``pass-unlock`` (уже открыто — то же). Окно закроется само через несколько секунд после ввода."""
    sc = script()
    if not sc:
        raise ValueError("нет ~/.local/bin/pass-unlock — разблокируйте вручную: gpg -d любого файла ~/.password-store")
    for w in tmux.windows():
        if w.get("name") == WINDOW:
            return w["id"]
    out = tmux.run("new-window", "-P", "-F", "#{window_id}", "-t", f"{tmux.session}:", "-n", WINDOW,
                   "-c", str(Path.home()), f"{sc}; sleep 8")
    return out.split()[0]


def type_password(tmux, wid: str, text: str):
    """Пароль — в окно ``pass-unlock`` (и только в него) через буфер tmux, который сразу удаляется, и Enter.
    Нигде не сохраняется и не попадает в аргументы процессов."""
    w = tmux.window(wid)
    if not w or w.get("name") != WINDOW:
        raise LookupError("окна разблокировки уже нет — нажмите «Разблокировать» ещё раз")
    if "\n" in text or "\r" in text or not text:
        raise ValueError("пароль — одной строкой")
    buf = "gp-pass-" + secrets.token_hex(6)             # не в аргументах команды (их видно в /proc) — через stdin
    try:
        tmux.run("load-buffer", "-b", buf, "-", input=text)
        tmux.run("paste-buffer", "-d", "-b", buf, "-t", wid)  # -d: буфер удаляется сразу после вставки
    finally:
        try:
            tmux.run("delete-buffer", "-b", buf)
        except (RuntimeError, OSError, subprocess.SubprocessError):
            pass                                          # уже удалён paste-buffer -d
    tmux.run("send-keys", "-t", wid, "Enter")
    _cache.clear()
