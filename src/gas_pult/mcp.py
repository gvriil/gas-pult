"""MCP-серверы Claude Code из панели: список со статусом, добавление по шаблону или вручную, удаление.

Всё через ``claude mcp`` (уровень user — видно во всех проектах). Новые сессии видят сервер сразу,
открытые — после перезапуска. Ключи сохраняются в настройках Claude Code (``~/.claude.json``) на сервере.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import time

NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{1,40}$")
LINE = re.compile(r"^(?P<name>.+?): (?P<target>.+) - (?P<mark>[✔✘⚠!])\s*(?P<state>.*)$")
TIMEOUT = 90

# Шаблоны: что это, куда подключаемся и какие поля спросить у человека (с подсказкой, где взять значение).
PRESETS = [
    {"id": "context7", "title": "Context7", "about": "Свежая документация библиотек и фреймворков — Claude меньше "
     "ошибается в API", "type": "http", "url": "https://mcp.context7.com/mcp", "fields": [], "after": ""},
    {"id": "github", "title": "GitHub", "about": "Репозитории, issues, PR — читать, комментировать, создавать",
     "type": "http", "url": "https://api.githubcopilot.com/mcp/",
     "fields": [{"key": "token", "label": "Токен GitHub", "secret": True, "header": "Authorization",
                 "format": "Bearer {}", "placeholder": "github_pat_…",
                 "hint": "github.com → Settings → Developer settings → Personal access tokens → Fine-grained: "
                         "выберите нужные репозитории и права (Contents, Issues, Pull requests)."}], "after": ""},
    {"id": "linear", "title": "Linear", "about": "Задачи и проекты Linear — брать задачу, менять статус, "
     "комментировать", "type": "http", "url": "https://mcp.linear.app/mcp",
     "fields": [{"key": "token", "label": "API-ключ Linear", "secret": True, "optional": True,
                 "header": "Authorization", "format": "Bearer {}", "placeholder": "lin_api_…",
                 "hint": "Linear → Settings → Security & access → Personal API keys → New key. Только чтение — "
                         "выберите право Read. Без ключа — вход через браузер (см. ниже)."}],
     "after": "Если ключ не вводили — вход через Linear: сессия → ☰ → ⚡ Команды → /mcp → linear → Authenticate."},
    {"id": "notion", "title": "Notion", "about": "Страницы и базы Notion — читать и обновлять", "type": "http",
     "url": "https://mcp.notion.com/mcp", "fields": [],
     "after": "Вход через Notion: сессия → ☰ → ⚡ Команды → /mcp → notion → Authenticate — с компьютера."},
    {"id": "homeassistant", "title": "Home Assistant", "about": "Умный дом: состояние устройств, свет, "
     "сценарии", "type": "http", "url": "{base}/api/mcp",
     "fields": [{"key": "base", "label": "Адрес Home Assistant", "placeholder": "https://home.example.com:8123",
                 "hint": "Тот адрес, по которому открываете Home Assistant в браузере. В самом HA включите "
                         "интеграцию «Model Context Protocol Server»."},
                {"key": "token", "label": "Долгосрочный токен", "secret": True, "header": "Authorization",
                 "format": "Bearer {}", "placeholder": "eyJ…",
                 "hint": "Home Assistant → профиль (внизу слева) → Безопасность → Долгосрочные токены → Создать."}],
     "after": ""},
    {"id": "http", "title": "Свой сервер (адрес)", "about": "Любой MCP-сервер по адресу HTTPS", "type": "http",
     "url": "{url}",
     "fields": [{"key": "url", "label": "Адрес сервера", "placeholder": "https://mcp.example.com/mcp",
                 "hint": "Берётся из документации сервиса, обычно оканчивается на /mcp."},
                {"key": "token", "label": "Ключ (если нужен)", "secret": True, "optional": True,
                 "header": "Authorization", "format": "Bearer {}",
                 "hint": "Если сервис выдаёт API-ключ — вставьте его; если вход через браузер — оставьте пустым "
                         "и потом /mcp → Authenticate."}], "after": ""},
    {"id": "stdio", "title": "Своя программа (команда)", "about": "MCP-сервер, который запускается командой "
     "на этом сервере (npx, uvx, docker…)", "type": "stdio",
     "fields": [{"key": "command", "label": "Команда запуска", "placeholder": "npx -y @modelcontextprotocol/server-x",
                 "hint": "Как в документации сервера. Нужная программа (node, uv, docker) должна быть установлена."},
                {"key": "env", "label": "Переменные окружения", "secret": True, "optional": True, "multiline": True,
                 "placeholder": "API_KEY=…", "hint": "По одной на строку: ИМЯ=значение. Ключи — здесь."}],
     "after": ""},
]


def _claude(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["claude", "mcp", *args], capture_output=True, text=True, timeout=TIMEOUT)


class Mcp:
    def __init__(self):
        self.cache: tuple[float, list[dict]] = (0, [])

    def list(self, fresh: bool = False) -> list[dict]:
        if not fresh and time.time() - self.cache[0] < 30:
            return self.cache[1]
        out = []
        for line in _claude("list").stdout.splitlines():
            if m := LINE.match(line.strip()):
                name = m["name"]
                out.append({"name": name, "target": m["target"], "ok": m["mark"] == "✔", "state": m["state"],
                            "removable": not name.startswith(("claude.ai ", "plugin:"))})
        self.cache = (time.time(), out)
        return out

    def add(self, preset_id: str, name: str, values: dict) -> str:
        p = next((x for x in PRESETS if x["id"] == preset_id), None)
        if not p:
            raise ValueError("нет такого шаблона")
        if not NAME.match(name):
            raise ValueError("имя: латиница в нижнем регистре, цифры, - или _ (2–41 знак)")
        vals = {f["key"]: str(values.get(f["key"], "")).strip() for f in p["fields"]}
        for f in p["fields"]:
            if not vals[f["key"]] and not f.get("optional"):
                raise ValueError(f"заполните поле «{f['label']}»")
        if p["type"] == "http":
            url = p["url"].format(**{k: v.rstrip("/") for k, v in vals.items()})
            if not url.startswith("https://") and not re.match(r"^http://(localhost|127\.|192\.168\.|10\.)", url):
                raise ValueError("адрес должен начинаться с https://")
            cfg = {"type": "http", "url": url}
            headers = {f["header"]: f["format"].format(vals[f["key"]]) for f in p["fields"]
                       if f.get("header") and vals[f["key"]]}
            if headers:
                cfg["headers"] = headers
        else:
            cmd = shlex.split(vals["command"])
            env = dict(line.split("=", 1) for line in vals.get("env", "").splitlines() if "=" in line)
            cfg = {"type": "stdio", "command": cmd[0], "args": cmd[1:], "env": {k.strip(): v.strip()
                                                                                 for k, v in env.items()}}
        r = _claude("add-json", name, json.dumps(cfg), "-s", "user")
        if r.returncode != 0:
            raise ValueError((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip()
                             else "claude mcp add-json не сработал")
        self.cache = (0, [])
        status = next((s for s in self.list(fresh=True) if s["name"] == name), None)
        return (("✔ подключён" if status["ok"] else f"добавлен, но пока не отвечает: {status['state']}")
                if status else "добавлен") + (f". {p['after']}" if p["after"] else "")

    def remove(self, name: str) -> str:
        if not NAME.match(name):
            raise ValueError("этот сервер удаляется не отсюда")
        r = _claude("remove", name, "-s", "user")
        self.cache = (0, [])
        if r.returncode != 0:
            raise ValueError((r.stderr or r.stdout).strip() or "не удалось удалить")
        return "удалён"
