"""Профили моделей: у какого поставщика работает сессия Claude Code.

Claude Code говорит с любым Anthropic-совместимым API: адрес — ``ANTHROPIC_BASE_URL``, ключ —
``ANTHROPIC_AUTH_TOKEN``, модели ролей — ``ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL`` (устаревший
``ANTHROPIC_SMALL_FAST_MODEL`` заменён на ``…HAIKU…``). Профиль — такой набор переменных.

Сессия профиля запускается ``claude --settings <config>/profiles/<id>.json``: ключ лежит в файле 0600 на сервере,
в командной строке и в tmux его нет. Профиль окна виден по аргументам процесса (``profile_of``), отдельно
не хранится. «Claude» — обычный запуск, как раньше (подписка или ключ сервера), без ``--settings``.

Значения по умолчанию — из документации поставщиков (октябрь 2026); названия моделей меняются, поэтому основную
и быструю модель можно поменять в панели (хранятся в ``state.json`` пульта, ключи — в ``secrets.json``).

Страны (ISO 3166-1, две буквы): у профиля ``regions`` — список разрешённых (allowlist) там, где у поставщика есть
официальный список, и ``blocked`` — запреты и санкционные страны. ``allowed(profile, countries)`` — разрешён, только
если разрешён для **каждой** страны набора (страны человека по трём признакам и страна сервера, ``country.py``);
пустой набор — не разрешено ничего (страна неизвестна). Подробно — ``docs/COMPLIANCE.md``.
"""

from __future__ import annotations

import json
import re
import shlex
from itertools import pairwise
from pathlib import Path

from gas_pult import providers
from gas_pult.config import config_dir, write_private

# Санкционные страны: запрещены у всех поставщиков (Z.ai и DeepSeek запрещают санкционные регионы без перечня;
# Z.ai называет Иран, КНДР, Кубу и регионы Украины — их по коду страны не отличить, см. COMPLIANCE.md).
UNSUPPORTED = ("RU", "BY", "KP", "IR", "SY", "CU")
NOT_FOR_ANTHROPIC = (*UNSUPPORTED, "CN", "HK", "MO")      # Anthropic: Китая в списке поддерживаемых нет

# Anthropic — Supported Regions Policy, https://www.anthropic.com/supported-countries, сверено 01.11.2026
# (на странице 185 стран, «действует с 12.11.2026»). Одна страница для claude.ai, Claude Code и API. Страна не в
# списке — не поддерживается. Украина — кроме Крыма, Донецкой, Херсонской, Луганской и Запорожской областей
# (по коду страны их не отличить — см. COMPLIANCE.md).
_ANTHROPIC_LISTED = """
AL DZ AD AO AG AR AM AU AT AZ BS BH BD BB BE BZ BJ BT BO BA BW BR BN BG BF BI CV KH CM CA CF TD CL CO KM CG CD CR
CI HR CY CZ DK DJ DM DO EC EG SV GQ ER EE SZ ET FJ FI FR GA GM GE DE GH GR GD GT GN GW GY HT HN HU IS IN ID IQ IE
IL IT JM JP JO KZ KE KI KW KG LA LV LB LS LR LY LI LT LU MG MW MY MV ML MT MH MR MU MX FM MD MC MN ME MA MZ NA NR
NP NL NZ NI NE NG MK NO OM PK PW PS PA PG PY PE PH PL PT QA RO RW KN LC VC WS SM ST SA SN RS SC SL SG SK SI SO SB
ZA KR SS ES LK SD SR SE CH TW TJ TZ TH TL TG TO TT TN TR TM TV UG UA AE GB US UY UZ VU VA VN ZM ZW
"""
ANTHROPIC_LISTED = frozenset(_ANTHROPIC_LISTED.split())
# «Территории и зависимые территории страны из списка тоже поддерживаются (например, Пуэрто-Рико — США)».
TERRITORIES = {
    "US": "PR GU VI AS MP UM", "FR": "GF GP MQ RE YT PM BL MF NC PF WF TF", "NL": "AW CW SX BQ", "DK": "GL FO",
    "GB": "GI BM KY VG AI MS TC FK SH IO GS PN GG JE IM", "AU": "CX CC NF HM", "NZ": "CK NU TK", "NO": "SJ BV",
    "FI": "AX",
}
ANTHROPIC = ANTHROPIC_LISTED | {t for k, v in TERRITORIES.items() if k in ANTHROPIC_LISTED for t in v.split()}
DENY = "Этот сервис недоступен в вашей стране по условиям поставщика"

PROFILES = [
    {"id": "claude", "title": "Claude", "short": "Claude",
     "about": "Anthropic — как сейчас: подписка или ключ сервера. Работают коннекторы claude.ai",
     "regions": ANTHROPIC, "blocked": NOT_FOR_ANTHROPIC},
    {"id": "openrouter", "title": "OpenRouter", "short": "OpenRouter", "key": "openrouter",
     "base_url": "https://openrouter.ai/api",
     "main": "anthropic/claude-sonnet-5.5", "fast": "anthropic/claude-haiku-5.5",
     "key_url": "https://openrouter.ai/settings/keys", "oauth": True,     # вход в одно касание (openrouter.py)
     "about": "Один ключ — сотни моделей, оплата по факту. По умолчанию — Claude Sonnet и Haiku через OpenRouter",
     "hint": "id модели из каталога openrouter.ai/models. Надёжно работают только модели Anthropic — "
             "с другими Claude Code может ошибаться",
     "env": {"CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1"},
     # своего списка стран у OpenRouter нет: по умолчанию — модели Anthropic, значит, список Anthropic (у OpenAI и
     # Gemini списки шире — для их моделей через OpenRouter список Anthropic строже, а не мягче)
     "regions": ANTHROPIC, "blocked": NOT_FOR_ANTHROPIC},
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


def countries_of(x) -> set[str]:
    """«NL», {"NL", "DE"}, «US/CA», "" → множество кодов стран."""
    if not x:
        return set()
    if isinstance(x, str):
        return {c for c in re.split(r"[/,\s]+", x.strip().upper()) if c}
    return {str(c).strip().upper() for c in x if c}


def allowed(profile: str, countries="") -> bool:
    """Разрешён ли поставщик для **каждой** страны набора (строка — одна страна). Неизвестный профиль или пустой
    набор (страна неизвестна) — нельзя. Есть ``regions`` — страна должна быть в нём; ``blocked`` — нельзя никогда."""
    p = BY_ID.get(profile or "claude")
    cs = countries_of(countries)
    if not p or not cs:
        return False
    return all(c not in p.get("blocked", ()) and (not p.get("regions") or c in p["regions"]) for c in cs)


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


def public(state: dict, countries=None) -> list[dict]:
    """Профили для панели: без ключей — только «ключ есть», хвост и модели. ``countries`` — страны человека: поле
    ``allowed`` (недоступный — с пометкой ``denied``, текст отказа)."""
    keys = providers.key_info()
    out = []
    for p in PROFILES:
        main, fast = models_of(p, state) if p.get("key") else ("", "")
        out.append({k: p[k] for k in ("id", "title", "short", "about") if k in p}
                   | {"needs_key": bool(p.get("key")), "key": keys.get(p.get("key", "")),
                      "key_url": p.get("key_url", ""), "hint": p.get("hint", ""), "oauth": bool(p.get("oauth")),
                      "main": main, "fast": fast, "default_main": p.get("main", ""),
                      "default_fast": p.get("fast", "")})
        if countries is not None:
            ok = allowed(p["id"], countries)
            out[-1] |= {"allowed": ok, "denied": "" if ok else DENY}
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
