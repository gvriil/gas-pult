"""Настройки пульта.

Конфиг — ``~/.config/gas-pult/config.toml``, токен бота — ``~/.config/gas-pult/token`` (права 0600)
или переменная ``GAS_PULT_TOKEN``. Каталоги переопределяются ``GAS_PULT_CONFIG_DIR`` / ``GAS_PULT_DATA_DIR``.
"""

from __future__ import annotations

import os
import re
import socket
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


def config_dir() -> Path:
    return Path(os.environ.get("GAS_PULT_CONFIG_DIR") or Path.home() / ".config" / "gas-pult")


def data_dir() -> Path:
    return Path(os.environ.get("GAS_PULT_DATA_DIR") or Path.home() / ".local" / "share" / "gas-pult")


# sudo без пароля, которое пульт готов выполнить по кнопке (остальное sudo — только вручную)
SUDO_ALLOW = [
    r"apt(-get)?\s+(install|update|upgrade)\b",
    r"systemctl\s+(restart|reload|start|stop|status|enable|disable|daemon-reload)\b",
]


class ConfigError(Exception):
    pass


@dataclass
class Config:
    token: str
    owners: list[int]
    session: str = "main"                                   # сессия tmux, окна которой видит пульт
    host: str = field(default_factory=lambda: socket.gethostname().split(".")[0])
    claude: str = "claude"                                  # команда запуска Claude Code в новом окне
    project_roots: list[str] = field(default_factory=lambda: ["~/projects", "~/worktrees"])
    voice: str = "irina"                                    # голос по умолчанию (дальше — из ⚙️ Настроек)
    whisper_model: str = "small"                            # tiny / base / small / medium — точность vs скорость
    models: list[str] = field(default_factory=lambda: ["opus", "sonnet", "haiku"])
    sudo_allow: list[str] = field(default_factory=lambda: list(SUDO_ALLOW))
    foreign: list[str] = field(default_factory=list)        # доп. шаблоны «команда для другой машины»
    task_pattern: str = r"[A-Z]{2,10}-\d+"                  # номер задачи трекера: GAS-123, PROJ-7
    task_prompt: str = "Возьми задачу {task} из трекера: прочитай описание и комментарии, составь план и приступай."
    commands: list[list[str]] = field(default_factory=list)  # свои кнопки ⚡: [["▶️ Старт", "/shtab start"]]

    @property
    def data(self) -> Path:
        return data_dir()

    def roots(self) -> list[Path]:
        return [Path(os.path.expanduser(r)) for r in self.project_roots]


def read_token() -> str:
    if tok := os.environ.get("GAS_PULT_TOKEN", "").strip():
        return tok
    path = config_dir() / "token"
    try:
        return path.read_text().strip()
    except OSError:
        raise ConfigError(f"Нет токена бота: {path}. Запустите `gas-pult init`.") from None


def load() -> Config:
    path = config_dir() / "config.toml"
    try:
        raw = tomllib.loads(path.read_text())
    except OSError:
        raise ConfigError(f"Нет настроек: {path}. Запустите `gas-pult init`.") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Ошибка в {path}: {e}") from None
    known = {f.name for f in fields(Config)} - {"token"}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"Неизвестные ключи в {path}: {', '.join(sorted(unknown))}")
    owners = raw.get("owners") or []
    if not owners or not all(isinstance(o, int) for o in owners):
        raise ConfigError(f"В {path} нужен owners = [<ваш Telegram ID>] — `gas-pult init` узнает его сам.")
    try:
        re.compile(raw.get("task_pattern", Config.task_pattern))
        for p in raw.get("sudo_allow", []) + raw.get("foreign", []):
            re.compile(p)
    except re.error as e:
        raise ConfigError(f"Неверное регулярное выражение в {path}: {e}") from None
    return Config(token=read_token(), **raw)


def _toml(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return "[" + ", ".join(_toml(x) for x in v) + "]"


def save(owners: list[int], token: str | None = None, **extra) -> Path:
    """Пишет config.toml (и токен с правами 0600). Существующие ключи, кроме переданных, сохраняются."""
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = d / "config.toml"
    raw = {}
    if path.exists():
        raw = tomllib.loads(path.read_text())
    raw.update(extra, owners=owners)
    body = "# gas-pult — настройки. Все ключи: config.example.toml в репозитории.\n"
    body += "".join(f"{k} = {_toml(v)}\n" for k, v in raw.items())
    path.write_text(body)
    if token:
        tp = d / "token"
        tp.touch(mode=0o600, exist_ok=True)
        tp.chmod(0o600)
        tp.write_text(token + "\n")
    return path
