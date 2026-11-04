"""Изолированные демо-пространства (задача 25): что видит пульт.

Пространство — отдельный пользователь Linux ``pult_t_<slug>`` (дефисы в имени — «_») и папка
``/srv/pult/tenants/<slug>/`` на своём образе ext4 (дисковый лимит), свой сервер tmux (служба systemd в своём slice с
лимитами памяти, процессора и числа процессов) и своя папка Claude Code. Создаёт, бэкапит и удаляет пространства
владелец — скриптом ``bin/pult-tenant`` через sudo (``tenant_admin.py``); подробно — ``docs/TENANTS.md``.

Пульт с пространством только работает: окна — ``sudo -n -u pult_t_<slug> tmux -S <сокет>`` (``tmux.Tmux(user=…)``),
описание и журналы — на чтение через группу ``pult-ro``. Без настройки (``bin/pult-tenant-setup``: правило sudo и
отметка ``<root>/.enabled``) функция выключена — ``enabled()`` ложно, пульт работает как раньше.

Модель: по умолчанию — профиль с ключом API (OpenRouter, GLM, DeepSeek; для юрисдикции RU — только российские профили,
те же правила стран, что в ``models.allowed``). Подписка владельца в пространство не копируется; вход в Claude внутри —
только вручную владельцем (``pult-tenant login``), с предупреждением ``LOGIN_WARNING``.

API для экрана пространств (часть C): ``status()`` — включено ли и список (``public``), ``tmux_of`` и ``new_window`` —
как пульт открывает окно в пространстве, ``command`` — команда запуска Claude Code в нём.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

from gas_pult import models, personas
from gas_pult.tmux import Tmux

ROOT = "/srv/pult/tenants"
PREFIX = "pult_t_"
SLUG = re.compile(r"^[a-z][a-z0-9-]{0,22}[a-z0-9]$")   # 2–24 знака: имя пользователя pult_t_… — до 31
MARKER = ".enabled"                                     # пишет pult-tenant-setup: правило sudo на месте
META = "tenant.json"
BUDGET = "budget.json"
GROUP_RO = "pult-ro"                                    # пульт читает описание и журналы пространств
GROUP_TENANTS = "pult-tenants"                          # все пользователи пространств: им пульт — sudo -u
DEFAULT_PERSONA = "business_owner"
DEFAULT_BUDGET = 3.0                                    # USD в день
JURISDICTION = re.compile(r"^[A-Z]{2}$")
LOGIN_WARNING = ("Вход в Claude в пространстве — только для ваших тестов. Подписка Claude — личная (условия "
                 "Consumer): не давайте её клиентам и не копируйте её токены в пространства. Для демо — профиль с "
                 "ключом API.")
READY_TTL = 60                                          # секунд: как часто заново проверять sudo
SUDO_TIMEOUT = 5

# Устройство папки пространства: путь → (права, чья группа). «own» — личная группа пользователя пространства,
# GROUP_RO — пульт читает. Всё остальное — только пользователь пространства.
LAYOUT = {
    "home": (0o700, "own"),
    "config": (0o710, GROUP_RO),
    "config/claude": (0o710, GROUP_RO),                 # CLAUDE_CONFIG_DIR: вход и настройки — не для пульта
    "config/claude/projects": (0o2750, GROUP_RO),       # журналы сессий: расход и ответы читает пульт
    "config/profiles": (0o700, "own"),                  # файлы настроек профилей с ключом (0600)
    "run": (0o700, "own"),
    "run/tmux": (0o700, "own"),
    "tmp": (0o700, "own"),
    "data": (0o700, "own"),
    "inbox": (0o700, "own"),
    "trash": (0o700, "own"),
    "usage": (0o2750, GROUP_RO),
}

_ready: dict[str, tuple[float, bool]] = {}


def root() -> Path:
    return Path(os.environ.get("GAS_PULT_TENANTS_ROOT") or ROOT)


def check_slug(slug) -> str:
    """Имя пространства: латиница в нижнем регистре, цифры, дефис; 2–24 знака, начинается с буквы."""
    slug = str(slug or "")
    if not SLUG.match(slug) or "--" in slug:
        raise ValueError("имя пространства — 2–24 знака: латиница a–z, цифры и дефис, начинается с буквы")
    return slug


def user_of(slug: str) -> str:
    """Пользователь Linux пространства; он же имя slice и службы (дефис в имени юнита systemd — уровень вложенности)."""
    return PREFIX + check_slug(slug).replace("-", "_")


def paths(slug: str, base_root: Path | None = None) -> dict[str, Path]:
    base = (base_root or root()) / check_slug(slug)
    p = {k.replace("/", "_"): base / k for k in LAYOUT}
    return p | {"base": base, "claude": base / "config/claude", "socket": base / "run/tmux/default",
                "secrets": base / "secrets.json", "audit": base / "audit.jsonl", "budget": base / BUDGET,
                "meta": base / META}


def marker(base_root: Path | None = None) -> dict | None:
    """Отметка настройки (``pult-tenant-setup install``): владелец, путь к tmux. Нет или не читается — None."""
    try:
        m = json.loads(((base_root or root()) / MARKER).read_text())
    except (OSError, ValueError):
        return None
    return m if isinstance(m, dict) else None


def enabled(base_root: Path | None = None) -> bool:
    """Включена ли функция: настройка сделана (отметка на месте). Без неё пульт работает как раньше."""
    return marker(base_root) is not None


def tmux_bin(base_root: Path | None = None) -> str:
    """Тот путь к tmux, что разрешён в правиле sudo (из отметки)."""
    return str((marker(base_root) or {}).get("tmux") or "/usr/bin/tmux")


def ready(slug: str, base_root: Path | None = None, runner=None, now=time.monotonic) -> bool:
    """Пускает ли sudo пульт в пространство без пароля: ``sudo -n -u <user> tmux -S <сокет> -V`` (ничего не меняет,
    только печатает версию). Ответ кэшируется на ``READY_TTL`` секунд. Нет отметки или sudo — ложно, без вызова."""
    if not enabled(base_root):
        return False
    key = f"{base_root or root()}/{slug}"
    if (c := _ready.get(key)) and now() - c[0] < READY_TTL:
        return c[1]
    cmd = ["sudo", "-n", "-u", user_of(slug), tmux_bin(base_root), "-S", str(paths(slug, base_root)["socket"]), "-V"]
    try:
        r = (runner or subprocess.run)(cmd, capture_output=True, text=True, timeout=SUDO_TIMEOUT,
                                       stdin=subprocess.DEVNULL)
        ok = r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    _ready[key] = (now(), ok)
    return ok


def load(slug: str, base_root: Path | None = None) -> dict | None:
    """Описание пространства (``tenant.json``, пишет ``pult-tenant``); бюджет — из ``budget.json``."""
    p = paths(slug, base_root)
    try:
        meta = json.loads(p["meta"].read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict):
        return None
    try:
        budget = float(json.loads(p["budget"].read_text()).get("daily_usd"))
    except (OSError, ValueError, TypeError, AttributeError):
        budget = None
    return meta | {"slug": slug, "budget_usd": budget}


def slugs(base_root: Path | None = None) -> list[str]:
    try:
        names = sorted(os.listdir(base_root or root()))
    except OSError:
        return []
    return [n for n in names if SLUG.match(n) and "--" not in n]


def api_profiles(jurisdiction: str = "") -> list[str]:
    """Профили с ключом API, разрешённые в юрисдикции (``models.allowed``): RU — только российские (через шлюз).
    Без юрисдикции — все профили с ключом, кроме российских."""
    j = (jurisdiction or "").upper()
    ids = [p["id"] for p in models.PROFILES if p.get("key")]
    if j:
        return [i for i in ids if models.allowed(i, j)]
    return [i for i in ids if not models.BY_ID[i].get("gateway")]


def default_profile(jurisdiction: str = "") -> str:
    ok = api_profiles(jurisdiction)
    if not ok:
        raise ValueError(f"нет профилей с ключом API для юрисдикции {jurisdiction}")
    return ok[0]


def check_jurisdiction(j) -> str:
    j = str(j or "").strip().upper()
    if j and not JURISDICTION.match(j):
        raise ValueError("юрисдикция — код страны из двух букв (RU, NL…) или пусто")
    return j


def check_profile(profile: str, jurisdiction: str = "", login: bool = False) -> str:
    """Профиль модели пространства. С ключом API — из ``api_profiles``; «claude» (подписка) — только после ручного
    входа владельца (``login``) и там, где Claude разрешён по стране."""
    j = check_jurisdiction(jurisdiction)
    if profile == "claude":
        if not login:
            raise ValueError("Claude в пространстве — только после ручного входа владельца (pult-tenant login). "
                             + LOGIN_WARNING)
        if j and not models.allowed("claude", j):
            raise ValueError(f"Claude недоступен для юрисдикции {j}")
        return profile
    if profile not in api_profiles(j):
        allowed = ", ".join(api_profiles(j)) or "—"
        raise ValueError(f"профиль {profile!r} не подходит для юрисдикции {j or '—'}; можно: {allowed}")
    return profile


def check_persona(persona: str) -> str:
    if persona not in personas.PERSONAS:
        raise ValueError(f"нет такой роли интерфейса: {persona}; есть: {', '.join(personas.PERSONAS)}")
    return persona


def public(t: dict, is_ready: bool | None = None) -> dict:
    """Пространство для панели: без путей к секретам. ``ready`` — пускает ли sudo (None — не проверяли)."""
    out = {"slug": t["slug"], "title": t.get("title") or t["slug"], "jurisdiction": t.get("jurisdiction", ""),
           "persona": t.get("persona") or DEFAULT_PERSONA, "profile": t.get("profile", ""),
           "budget_usd": t.get("budget_usd"), "user": user_of(t["slug"]), "claude_login": bool(t.get("claude_login"))}
    if out["claude_login"]:
        out["warning"] = LOGIN_WARNING
    if is_ready is not None:
        out["ready"] = is_ready
    return out


def status(base_root: Path | None = None, check: bool = False, runner=None) -> dict:
    """Для экрана пространств: ``enabled`` и список. Выключено — пустой список, ни одного вызова sudo.
    ``check`` — проверить sudo для каждого (поле ``ready``)."""
    if not enabled(base_root):
        return {"enabled": False, "tenants": []}
    out = []
    for s in slugs(base_root):
        if t := load(s, base_root):
            out.append(public(t, ready(s, base_root, runner) if check else None))
    return {"enabled": True, "tenants": out}


def tmux_of(slug: str, session: str = "main", base_root: Path | None = None) -> Tmux:
    """tmux пространства: все команды — ``sudo -n -u <user> <tmux> -S <сокет>``; сессия — в его домашней папке."""
    p = paths(slug, base_root)
    return Tmux(session, socket=str(p["socket"]), user=user_of(slug), home=str(p["home"]), tmux=tmux_bin(base_root))


def path_env(slug: str, base_root: Path | None = None) -> str:
    """PATH пространства: Claude Code ставится в его ``home/.local/bin``. Тот же PATH — у службы tmux пространства."""
    return f"{paths(slug, base_root)['home']}/.local/bin:/usr/local/bin:/usr/bin:/bin"


def command(t: dict, base: str = "claude", base_root: Path | None = None) -> str:
    """Команда запуска Claude Code в пространстве: своя папка Claude и файл настроек профиля с ключом (его пишет
    ``pult-tenant key`` в ``config/profiles/<id>.json``, 0600). «claude» — только после ручного входа владельца.

    Сначала — ``export PATH=<home>/.local/bin:…``: окно получает окружение клиента tmux, а это ``sudo`` с его
    ``secure_path`` без папки пространства — без этого «claude: command not found». ``export`` — чтобы тот же PATH
    был у программ, которые запускает Claude, и у оболочки, что остаётся в окне после его выхода."""
    p = paths(t["slug"], base_root)
    profile = check_profile(t.get("profile") or default_profile(t.get("jurisdiction", "")),
                            t.get("jurisdiction", ""), bool(t.get("claude_login")))
    if profile != "claude":
        base = f"{base} --settings {shlex.quote(str(p['config_profiles'] / f'{profile}.json'))}"
    return f"export PATH={shlex.quote(path_env(t['slug'], base_root))}; {models.with_home(base, p['claude'])}"


def new_window(slug: str, name: str, path: str = "", session: str = "main", base_root: Path | None = None) -> str:
    """Открыть окно с Claude Code в пространстве. Выключено или sudo не пускает — ошибка, окно не открывается."""
    if not enabled(base_root):
        raise RuntimeError("пространства выключены: не сделана настройка (bin/pult-tenant-setup)")
    t = load(slug, base_root)
    if not t:
        raise RuntimeError(f"нет пространства {slug}")
    if not ready(slug, base_root):
        raise RuntimeError(f"sudo не пускает пульт в пространство {slug} — см. docs/TENANTS.md, «Проверка»")
    tm = tmux_of(slug, session, base_root)
    cmd = command(t, base_root=base_root)
    return tm.new_window(name, path or str(paths(slug, base_root)["home"]), cmd, mark=t.get("profile") or "claude")
