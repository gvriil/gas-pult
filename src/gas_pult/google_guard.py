"""Данные Google — только моделям, которые на них не учатся (правило владельца 17.11, Google API Limited Use).

Окно профиля, которому правило запрещает данные Google (``base_mcp.learns_on_data``: FCC «:free», DeepSeek напрямую,
NVIDIA, OpenRouter без подтверждённых deny и zdr), запускается так (``models.command``):

1. ``--strict-mcp-config --mcp-config <файл>`` — Claude Code берёт серверы MCP только из файла пульта. Файл — копия
   серверов из ``.claude.json`` (как их сливает Claude Code: пользователь → одобренные ``.mcp.json`` папки → локальные
   серверы папки; отключённые в папке — нет) **без серверов Google** (``google_reason``). Коннекторы claude.ai и
   серверы плагинов в таком окне не грузятся. Файл 0600 в данных пульта (в нём могут быть заголовки с ключами),
   пишется заново при каждом запуске окна.
2. Хук ``PreToolUse`` в настройках профиля (``--settings``, не общий ``~/.claude/settings.json``):
   ``secrets_guard.py drive-hook`` — отказ любому инструменту с путём в ``~/drive`` или в точке монтирования rclone.

Claude на подписке (профиль «claude») — без изменений.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sys
from pathlib import Path
from urllib.parse import urlsplit

from gas_pult import secrets_guard
from gas_pult.config import data_dir, write_private

# Почему сервер — Google (список и обоснование — docs/CONNECTORS.md, «Данные Google»):
# имя сервера — Google-сервис (gdrive, google-drive, gmail, gcal, google-*);
NAME = re.compile(r"google|gdrive|g-drive|gmail|gcal|gdocs|gsheets?|gslides|youtube", re.I)
# адрес HTTP/SSE — домены Google (официальный сервер Диска drivemcp.googleapis.com и любые *.googleapis.com);
HOSTS = ("googleapis.com", "google.com", "googleusercontent.com", "gstatic.com")
# команда stdio — Диск через rclone (наш base_mcp.py drive, сам rclone) или переменные rclone/Диска пульта.
DRIVE_ENV = ("RCLONE_CONFIG", "GAS_DRIVE_REMOTE", "GAS_DRIVE_RCLONE", "GAS_DRIVE_DIR")


def claude_json(home: Path | None) -> Path:
    """Настройки Claude Code, откуда берутся серверы: у человека — его папка (``CLAUDE_CONFIG_DIR``), у владельца —
    ``~/.claude.json`` (``GAS_PULT_CLAUDE_JSON`` — тесты)."""
    if home:
        return Path(home) / ".claude.json"
    if f := os.environ.get("GAS_PULT_CLAUDE_JSON"):
        return Path(f)
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home()) / ".claude.json"


def _load(f: Path) -> dict:
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def google_reason(name: str, cfg: dict, roots=()) -> str | None:
    """Почему сервер MCP отдаёт данные Google (или None)."""
    if NAME.search(name or ""):
        return "имя — сервис Google"
    cfg = cfg if isinstance(cfg, dict) else {}
    host = (urlsplit(str(cfg.get("url") or "")).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in HOSTS):
        return f"адрес Google ({host})"
    args = [str(a) for a in cfg.get("args") or []]
    words = [str(cfg.get("command") or ""), *args]
    if any(os.path.basename(w) in ("rclone", "rclone.exe") for w in words):
        return "rclone"
    if any(w.endswith("base_mcp.py") for w in words) and "drive" in args:
        return "Диск пульта через rclone (base_mcp.py drive)"
    env = cfg.get("env") if isinstance(cfg.get("env"), dict) else {}
    if any(k in env for k in DRIVE_ENV):
        return "переменные rclone"
    text = json.dumps(cfg, ensure_ascii=False)
    if NAME.search(" ".join(words)) or "googleapis.com" in text:
        return "команда Google"
    if any(r in text for r in roots):
        return "работает с папкой Google Диска"            # например, «Документы» по ~/drive/…
    return None


def servers(home: Path | None, path: str = "") -> dict:
    """Серверы MCP окна, как их видит Claude Code в папке ``path``: пользователь, одобренные .mcp.json, локальные."""
    d = _load(claude_json(home))
    out = dict(d.get("mcpServers") or {})
    proj = ((d.get("projects") or {}).get(str(path)) or {}) if path else {}
    if path:
        settings = _load(Path(home) / "settings.json" if home else Path.home() / ".claude" / "settings.json")
        allow_all = proj.get("enableAllProjectMcpServers") or settings.get("enableAllProjectMcpServers")
        enabled = set(proj.get("enabledMcpjsonServers") or []) | set(settings.get("enabledMcpjsonServers") or [])
        off = set(proj.get("disabledMcpjsonServers") or []) | set(settings.get("disabledMcpjsonServers") or [])
        shared = _load(Path(path) / ".mcp.json").get("mcpServers") or {}
        out.update({n: c for n, c in shared.items() if (allow_all or n in enabled) and n not in off})
        out.update(proj.get("mcpServers") or {})
        for n in proj.get("disabledMcpServers") or []:
            out.pop(n, None)
    return {n: c for n, c in out.items() if isinstance(c, dict)}


def safe_servers(home: Path | None, path: str = "") -> tuple[dict, dict]:
    """(разрешённые серверы, {убранный: почему})."""
    roots = secrets_guard.drive_roots()
    keep, cut = {}, {}
    for n, c in servers(home, path).items():
        if why := google_reason(n, c, roots):
            cut[n] = why
        else:
            keep[n] = c
    return keep, cut


def config_file(profile: str, home: Path | None, path: str) -> Path:
    tag = hashlib.sha256(f"{home or ''}\0{path}".encode()).hexdigest()[:12]
    return data_dir() / "mcp-no-google" / f"{profile}-{tag}.json"


def flags(profile: str, home: Path | None = None, path: str = "") -> str:
    """Добавка к команде claude: только серверы без Google. Файл пишется заново при каждом запуске окна."""
    keep, _ = safe_servers(home, path)
    f = config_file(profile, home, path)
    write_private(f, json.dumps({"mcpServers": keep}, ensure_ascii=False, indent=1))
    return f" --strict-mcp-config --mcp-config {shlex.quote(str(f))}"


def hooks() -> dict:
    """Хук для настроек профиля: отказ инструментам с путём в папке Google Диска (правило — secrets_guard)."""
    cmd = (f"{shlex.quote(sys.executable)} {shlex.quote(secrets_guard.__file__)} drive-hook "
           + " ".join(shlex.quote(r) for r in secrets_guard.drive_roots()))
    return {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": cmd.strip(), "timeout": 20}]}]}
