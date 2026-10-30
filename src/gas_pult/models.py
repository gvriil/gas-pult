"""Профили моделей: у какого поставщика работает сессия Claude Code.

Claude Code говорит с любым Anthropic-совместимым API: адрес — ``ANTHROPIC_BASE_URL``, ключ —
``ANTHROPIC_AUTH_TOKEN``, модели ролей — ``ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL`` (устаревший
``ANTHROPIC_SMALL_FAST_MODEL`` заменён на ``…HAIKU…``). Профиль — такой набор переменных.

Сессия профиля запускается ``claude --settings <config>/profiles/<id>.json``: ключ лежит в файле 0600 на сервере,
в командной строке и в tmux его нет. Профиль окна виден по аргументам процесса (``profile_of``), отдельно
не хранится. «Claude» — обычный запуск, как раньше (подписка или ключ сервера), без ``--settings``.

Значения по умолчанию — из документации поставщиков (октябрь 2026); названия моделей меняются, поэтому основную
и быструю модель можно поменять в панели (хранятся в ``state.json`` пульта, ключи — в ``secrets.json``).
"""

from __future__ import annotations

import json
import re
import shlex
from itertools import pairwise
from pathlib import Path

from gas_pult import providers
from gas_pult.config import config_dir

PROFILES = [
    {"id": "claude", "title": "Claude", "short": "Claude",
     "about": "Anthropic — как сейчас: подписка или ключ сервера. Работают коннекторы claude.ai"},
    {"id": "openrouter", "title": "OpenRouter", "short": "OpenRouter", "key": "openrouter",
     "base_url": "https://openrouter.ai/api", "main": "", "fast": "",
     "key_url": "https://openrouter.ai/settings/keys", "oauth": True,     # вход в одно касание (openrouter.py)
     "about": "Один ключ — сотни моделей, оплата по факту. Пустые поля моделей — Claude через OpenRouter",
     "hint": "id модели из каталога openrouter.ai/models. Надёжно работают только модели Anthropic — "
             "с другими Claude Code может ошибаться",
     "env": {"CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1"}},
    {"id": "zai", "title": "GLM (Z.ai)", "short": "GLM", "key": "zai",
     "base_url": "https://api.z.ai/api/anthropic", "main": "glm-5.3[1m]", "fast": "glm-5.3-flash[1m]",
     "key_url": "https://z.ai/manage-apikey/apikey-list",
     "about": "GLM от Z.ai: длинный контекст, недорого. Картинки не понимает",
     "env": {"API_TIMEOUT_MS": "3000000", "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "1000000",
             "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}},
    {"id": "deepseek", "title": "DeepSeek", "short": "DeepSeek", "key": "deepseek",
     "base_url": "https://api.deepseek.com/anthropic", "main": "deepseek-v4-pro[1m]", "fast": "deepseek-flash",
     "key_url": "https://platform.deepseek.com/api_keys",
     "about": "DeepSeek V4: быстро и очень дёшево. Основная — V4 Pro, быстрая — Flash",
     "hint": "в документации DeepSeek основная по умолчанию — deepseek-flash[1m] (быстрее и дешевле)",
     "env": {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "786432"}},
]
BY_ID = {p["id"]: p for p in PROFILES}
SETTINGS = re.compile(r"/profiles/([a-z0-9-]+)\.json$")
MODEL = re.compile(r"^[\w./:@~\[\]-]{1,120}$")


def profiles_dir() -> Path:
    return config_dir() / "profiles"


def models_of(p: dict, state: dict) -> tuple[str, str]:
    """Основная и быстрая модель профиля: ваш выбор из панели или значение по умолчанию."""
    own = (state.get("model_profiles") or {}).get(p["id"]) or {}
    return own.get("main", p.get("main", "")), own.get("fast", p.get("fast", ""))


def env_of(p: dict, key: str, state: dict) -> dict:
    main, fast = models_of(p, state)
    env = {"ANTHROPIC_BASE_URL": p["base_url"], "ANTHROPIC_AUTH_TOKEN": key, "ANTHROPIC_API_KEY": ""}
    if main:
        env.update(ANTHROPIC_MODEL=main, ANTHROPIC_DEFAULT_OPUS_MODEL=main, ANTHROPIC_DEFAULT_SONNET_MODEL=main)
    if fast:
        env.update(ANTHROPIC_DEFAULT_HAIKU_MODEL=fast, CLAUDE_CODE_SUBAGENT_MODEL=fast)
    return {**env, **p.get("env", {})}


def command(base: str, profile: str, state: dict) -> str:
    """Команда запуска Claude Code в профиле. Для «claude» — как раньше; иначе файл настроек с ключом (0600)."""
    if profile in ("", "claude"):
        return base
    p = BY_ID.get(profile)
    if not p:
        raise ValueError("нет такого профиля")
    key = providers.load_keys().get(p["key"])
    if not key:
        raise ValueError(f"нет ключа {p['title']} — добавьте его в «Интеграции» → «Модели»")
    d = profiles_dir()
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    f = d / f"{profile}.json"
    f.touch(mode=0o600, exist_ok=True)
    f.chmod(0o600)
    f.write_text(json.dumps({"env": env_of(p, key, state)}, ensure_ascii=False))
    return f"{base} --settings {shlex.quote(str(f))}"


def profile_of(argv: list[str]) -> str:
    """Профиль запущенного claude — по пути файла настроек в его аргументах; без него — «claude»."""
    for a, b in pairwise(argv):
        if a == "--settings" and (m := SETTINGS.search(b)) and m.group(1) in BY_ID:
            return m.group(1)
    return "claude"


def public(state: dict) -> list[dict]:
    """Профили для панели: без ключей — только «ключ есть», хвост и модели."""
    keys = providers.key_info()
    out = []
    for p in PROFILES:
        main, fast = models_of(p, state) if p.get("key") else ("", "")
        out.append({k: p[k] for k in ("id", "title", "short", "about") if k in p}
                   | {"needs_key": bool(p.get("key")), "key": keys.get(p.get("key", "")),
                      "key_url": p.get("key_url", ""), "hint": p.get("hint", ""), "oauth": bool(p.get("oauth")),
                      "main": main, "fast": fast, "default_main": p.get("main", ""),
                      "default_fast": p.get("fast", "")})
    return out


def set_models(state: dict, profile: str, main: str, fast: str) -> dict:
    """Новые основная/быстрая модели профиля → обновлённое ``model_profiles`` для state.json."""
    if profile not in BY_ID or profile == "claude":
        raise ValueError("нет такого профиля")
    for m in (main, fast):
        if m and not MODEL.match(m):
            raise ValueError(f"странное имя модели: {m[:40]}")
    allp = dict(state.get("model_profiles") or {})
    allp[profile] = {"main": main.strip(), "fast": fast.strip()}
    return allp
