"""Профили моделей: у какого поставщика работает сессия Claude Code.

Claude Code говорит с любым Anthropic-совместимым API: адрес — ``ANTHROPIC_BASE_URL``, ключ —
``ANTHROPIC_AUTH_TOKEN``, модели ролей — ``ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL`` (устаревший
``ANTHROPIC_SMALL_FAST_MODEL`` заменён на ``…HAIKU…``). Профиль — такой набор переменных.

Сессия профиля запускается ``claude --settings <config>/profiles/<id>.json``: ключ лежит в файле 0600 на сервере,
в командной строке и в tmux его нет. Профиль окна виден по аргументам процесса (``profile_of``), отдельно
не хранится. «Claude» — обычный запуск, как раньше (подписка или ключ сервера), без ``--settings``.

Значения по умолчанию — из документации поставщиков (октябрь 2026); названия моделей меняются, поэтому основную
и быструю модель можно поменять в панели (хранятся в ``state.json`` пульта, ключи — в ``secrets.json``).

Регионы: у профиля ``blocked`` — страны (ISO 3166-1, две буквы), откуда трафика к этому поставщику быть не должно,
и, если нужно, ``regions`` — явный список разрешённых. ``allowed(profile, region)`` — можно ли; регион по умолчанию —
``region`` из config.toml (страна сервера). Регион не задан — разрешено всё, что явно не запрещено. Списки — по
условиям поставщиков на октябрь 2026; уточняются отдельно (соблюдение условий поставщиков).
"""

from __future__ import annotations

import json
import re
import shlex
from itertools import pairwise
from pathlib import Path

from gas_pult import providers
from gas_pult.config import config_dir, write_private

# Страны, где модели поставщиков не поддерживаются (санкции, условия поставщиков). Россия — для всех.
UNSUPPORTED = ("RU", "BY", "KP", "IR", "SY", "CU")
NOT_FOR_ANTHROPIC = (*UNSUPPORTED, "CN", "HK", "MO")      # Anthropic: Китая в списке поддерживаемых нет

PROFILES = [
    {"id": "claude", "title": "Claude", "short": "Claude",
     "about": "Anthropic — как сейчас: подписка или ключ сервера. Работают коннекторы claude.ai",
     "blocked": NOT_FOR_ANTHROPIC},
    {"id": "openrouter", "title": "OpenRouter", "short": "OpenRouter", "key": "openrouter",
     "base_url": "https://openrouter.ai/api",
     "main": "anthropic/claude-sonnet-5.5", "fast": "anthropic/claude-haiku-5.5",
     "key_url": "https://openrouter.ai/settings/keys", "oauth": True,     # вход в одно касание (openrouter.py)
     "about": "Один ключ — сотни моделей, оплата по факту. По умолчанию — Claude Sonnet и Haiku через OpenRouter",
     "hint": "id модели из каталога openrouter.ai/models. Надёжно работают только модели Anthropic — "
             "с другими Claude Code может ошибаться",
     "env": {"CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1"},
     "blocked": NOT_FOR_ANTHROPIC},                 # по умолчанию — модели Anthropic через OpenRouter
    {"id": "zai", "title": "GLM (Z.ai)", "short": "GLM", "key": "zai",
     "base_url": "https://api.z.ai/api/anthropic", "main": "glm-5.3[1m]", "fast": "glm-5.3-flash[1m]",
     "long_context": True,                       # «[1m]» — по документации Z.ai
     "key_url": "https://z.ai/manage-apikey/apikey-list",
     "about": "GLM от Z.ai: длинный контекст, недорого. Картинки не понимает",
     "env": {"API_TIMEOUT_MS": "3000000", "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "1000000",
             "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
     "blocked": UNSUPPORTED},
    {"id": "deepseek", "title": "DeepSeek", "short": "DeepSeek", "key": "deepseek",
     "base_url": "https://api.deepseek.com/anthropic", "main": "deepseek-v4-pro[1m]", "fast": "deepseek-flash",
     "long_context": True,                       # «[1m]» — по документации DeepSeek
     "key_url": "https://platform.deepseek.com/api_keys",
     "about": "DeepSeek V4: быстро и очень дёшево. Основная — V4 Pro, быстрая — Flash",
     "hint": "в документации DeepSeek основная по умолчанию — deepseek-flash[1m] (быстрее и дешевле)",
     "env": {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "786432"},
     "blocked": UNSUPPORTED},
]
BY_ID = {p["id"]: p for p in PROFILES}
SETTINGS = re.compile(r"/profiles/([a-z0-9-]+)\.json$")
MODEL = re.compile(r"^[\w./:@~\[\]-]{1,120}$")


def allowed(profile: str, region: str = "") -> bool:
    """Можно ли этому поставщику принимать трафик из страны ``region``. Неизвестный профиль — нельзя.

    Есть ``regions`` — только они; иначе — всё, кроме ``blocked``. Регион не задан — всё, что явно не запрещено."""
    p = BY_ID.get(profile or "claude")
    if not p:
        return False
    region = (region or "").strip().upper()
    if p.get("regions"):
        return region in p["regions"]
    return region not in p.get("blocked", ())


def has_key(profile: str, keys: dict | None = None) -> bool:
    """Есть ли чем запустить профиль: «Claude» — всегда (подписка или ключ сервера), остальным нужен ключ."""
    p = BY_ID.get(profile or "claude")
    if not p:
        return False
    if not p.get("key"):
        return True
    return bool((providers.load_keys() if keys is None else keys).get(p["key"]))


def profiles_dir() -> Path:
    return config_dir() / "profiles"


def models_of(p: dict, state: dict) -> tuple[str, str]:
    """Основная и быстрая модель профиля: ваш выбор из панели или значение по умолчанию."""
    own = (state.get("model_profiles") or {}).get(p["id"]) or {}
    main, fast = own.get("main") or p.get("main", ""), own.get("fast") or p.get("fast", "")
    if not p.get("long_context"):                # «[1m]» — режим 1M контекста Claude Code; кто его не знает — без него
        main, fast = main.removesuffix("[1m]"), fast.removesuffix("[1m]")
    return main, fast


def env_of(p: dict, key: str, state: dict) -> dict:
    main, fast = models_of(p, state)
    env = {"ANTHROPIC_BASE_URL": p["base_url"], "ANTHROPIC_AUTH_TOKEN": key, "ANTHROPIC_API_KEY": ""}
    if main:
        env.update(ANTHROPIC_MODEL=main, ANTHROPIC_DEFAULT_OPUS_MODEL=main, ANTHROPIC_DEFAULT_SONNET_MODEL=main)
    if fast:
        env.update(ANTHROPIC_DEFAULT_HAIKU_MODEL=fast, CLAUDE_CODE_SUBAGENT_MODEL=fast)
    return {**env, **p.get("env", {})}


def with_home(cmd: str, home: Path | None) -> str:
    """Своя папка Claude Code человека (вход, MCP, журналы) — переменной перед командой; владелец (None) — как было."""
    return f"CLAUDE_CONFIG_DIR={shlex.quote(str(home))} {cmd}" if home else cmd


def command(base: str, profile: str, state: dict, home: Path | None = None) -> str:
    """Команда запуска Claude Code в профиле. Для «claude» — как раньше; иначе файл настроек с ключом (0600).
    ``home`` — папка Claude Code человека (``people.claude_dir``)."""
    if profile in ("", "claude"):
        return with_home(base, home)
    p = BY_ID.get(profile)
    if not p:
        raise ValueError("нет такого профиля")
    key = providers.load_keys().get(p["key"])
    if not key:
        raise ValueError(f"нет ключа {p['title']} — добавьте его в «Интеграции» → «Модели»")
    f = profiles_dir() / f"{profile}.json"
    write_private(f, json.dumps({"env": env_of(p, key, state)}, ensure_ascii=False))
    return with_home(f"{base} --settings {shlex.quote(str(f))}", home)


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
