"""Модули-агенты: готовое рабочее пространство под задачу или отрасль — одна папка без кода.

Модуль — папка ``templates/modules/<id>/`` в пакете (встроенные) или ``<config>/modules/<id>/`` (свои, отраслевые;
одноимённый свой модуль заменяет встроенный). В папке:

- ``module.toml`` — название, отрасль, для чего, интеграции, расписание, решения, настройки (формат — docs/MODULES.md);
- ``CLAUDE.md`` — роль и правила агента; ``{{ключ}}`` заменяется значением из ``[settings]``;
- ``skills/<имя>/SKILL.md`` — навыки Claude Code, копируются в ``.claude/skills/``;
- ``settings.json`` — разрешения Claude Code для пространства, копируется в ``.claude/settings.json``;
- всё остальное (``data/``, ``templates/``, ``PLAN.md``…) копируется в пространство как есть.

Общие блоки — ``templates/modules/_common/<id>/`` (и ``<config>/modules/_common/<id>/``): ``block.toml`` (title, about),
``RULES.md`` (фрагмент правил) и ``skills/``. В каталоге их нет; модуль подключает их полем ``uses = ["reviews"]`` —
при создании пространства навыки блока копируются в ``.claude/skills/``, правила дописываются в CLAUDE.md разделом.
Папки, имя которых начинается с «_», модулями не считаются.

Пространство — новая папка в первом корне ``project_roots`` с отметкой ``.gas-pult-module`` (id, версия, кто создал):
по ней пульт находит пространства для расписания. Существующая папка не перезаписывается никогда.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import time
import tomllib
from datetime import date, datetime, timedelta
from importlib import resources
from pathlib import Path

from gas_pult.config import config_dir
from gas_pult.mcp import CONNECTORS, PRESETS
from gas_pult.personas import SECTIONS

MARK = ".gas-pult-module"                         # отметка пространства: из какого модуля, версия, кто создал
MARK_OFF = ".gas-pult-module.off"                 # прежний ручной способ выключить расписание — читается как off
SCHEDULE_STATES = ("on", "paused", "off")         # поле schedule в отметке: работает / на паузе / выключено навсегда
ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")      # id модуля и имя папки: латиница, цифры, дефис
AT = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
CATCH_UP = 3 * 3600                               # пульт был выключен в назначенное время — догоняем не позже 3 ч
EVERY = (5, 240)                                  # [[schedule]] every: каждые 5–240 минут
WORKDAY = (1, 10)                                 # [[schedule]] workday: N-й рабочий день месяца, 1–10
CALENDAR = "deadlines/skills/workdays/calendar-ru.csv"   # производственный календарь РФ — из общего блока
SKIP = {"module.toml", "skills", "settings.json", "__pycache__", ".DS_Store"}
DEFAULT_START = "Прочитай CLAUDE.md этой папки и коротко скажи, что тебе нужно от меня, чтобы начать работу."
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
# Откуда модуль берёт данные — только официальные API и выгрузки самого клиента (правило владельца): без парсинга
# личных кабинетов, чужих сайтов и купленных баз.
SOURCE_KINDS = {"official_api": "официальный API", "client_export": "выгрузка клиента"}
COMMON = "_common"


class ModuleError(ValueError):
    """Ошибка в module.toml или при создании пространства — текст для человека, по-русски."""


def builtin_dir() -> Path:
    return Path(str(resources.files("gas_pult").joinpath("templates/modules")))


def user_dir() -> Path:
    return config_dir() / "modules"


def _source(x, where: str) -> dict:
    if not isinstance(x, dict):
        raise ModuleError(f"{where}: [[data_sources]] — таблица с полями title, kind")
    kind = _str(x, "kind", where)
    if kind not in SOURCE_KINDS:
        raise ModuleError(f"{where}: data_sources kind = \"{kind}\" — только official_api (официальный API) "
                          "или client_export (выгрузка клиента)")
    return {"title": _str(x, "title", where), "kind": kind, "kind_title": SOURCE_KINDS[kind],
            "about": _str(x, "about", where, need=False)}


def blocks() -> dict[str, dict]:
    """Общие блоки (``_common/<id>``): id → {id, title, about, rules, skills, path}. Свой блок заменяет встроенный."""
    out: dict[str, dict] = {}
    for base in (builtin_dir() / COMMON, user_dir() / COMMON):
        for d in sorted(base.iterdir()) if base.is_dir() else []:
            if not d.is_dir() or not ID.match(d.name):
                continue
            where = f"общий блок {d.name}"
            try:
                raw = tomllib.loads((d / "block.toml").read_text(encoding="utf-8"))
                rules = (d / "RULES.md").read_text(encoding="utf-8").strip()
            except OSError:
                raise ModuleError(f"{where}: нужны block.toml и RULES.md") from None
            except tomllib.TOMLDecodeError as e:
                raise ModuleError(f"{where}: ошибка в block.toml — {e}") from None
            out[d.name] = {"id": d.name, "title": _str(raw, "title", where), "about": _str(raw, "about", where),
                           "rules": rules, "skills": sorted(p.parent.name for p in (d / "skills").glob("*/SKILL.md")),
                           "path": str(d)}
    return out


def _str(raw: dict, key: str, where: str, need: bool = True) -> str:
    v = raw.get(key, "")
    if not isinstance(v, str) or (need and not v.strip()):
        raise ModuleError(f"{where}: поле «{key}» — " + ("обязательная строка" if need else "строка"))
    return v.strip()


def _integration(x, where: str) -> dict:
    if not isinstance(x, dict):
        raise ModuleError(f"{where}: [[integrations]] — таблица с полями id, why")
    iid = _str(x, "id", where)
    known = next((c for c in CONNECTORS if c["id"] == iid), None)
    preset = next((p for p in PRESETS if p["id"] == iid), None) if not known else None
    title = x.get("title") or (known or preset or {}).get("title") or ""
    if not isinstance(title, str) or not title:
        raise ModuleError(f"{where}: у интеграции «{iid}» нет в пульте шаблона — укажите title")
    out = {"id": iid, "title": title, "why": _str(x, "why", where, need=False),
           "optional": bool(x.get("optional", False)),
           "kind": "connector" if known else "preset" if preset else "manual"}
    if known:
        out["match"] = known["match"]
    if not out["optional"] and out["kind"] == "manual":
        out["how"] = _str(x, "how", where)       # без шаблона пульта — как подключить, словами
    elif "how" in x:
        out["how"] = _str(x, "how", where, need=False)
    return out


def _schedule(x, where: str, settings: dict) -> dict:
    if not isinstance(x, dict):
        raise ModuleError(f"{where}: [[schedule]] — таблица с полями at, prompt")
    every = x.get("every", 0)
    if not isinstance(every, int) or isinstance(every, bool) or (every and not EVERY[0] <= every <= EVERY[1]):
        raise ModuleError(f"{where}: every — каждые N минут, целое число от {EVERY[0]} до {EVERY[1]}")
    workday = x.get("workday", 0)
    if not isinstance(workday, int) or isinstance(workday, bool) or (
            workday and not WORKDAY[0] <= workday <= WORKDAY[1]):
        raise ModuleError(f"{where}: workday — N-й рабочий день месяца, целое число от {WORKDAY[0]} до {WORKDAY[1]}")
    if workday and every:
        raise ModuleError(f"{where}: в одном пункте расписания — либо every, либо workday")
    at = _str(x, "at", where, need=not every) or "00:00"
    until = _str(x, "until", where, need=False) or "23:59"
    for t in (at, until):
        if not AT.match(t):
            raise ModuleError(f"{where}: расписание at/until = \"{t}\" — нужно время ЧЧ:ММ, например \"08:00\"")
    days = x.get("days", [1, 2, 3, 4, 5] if workday else [1, 2, 3, 4, 5, 6, 7])
    if not isinstance(days, list) or not days or not all(isinstance(d, int) and 1 <= d <= 7 for d in days):
        raise ModuleError(f"{where}: days — дни недели числами 1–7 (1 — понедельник), например [1, 2, 3, 4, 5]")
    when = at if not every else f"каждые {every} мин" + ("" if (at, until) == ("00:00", "23:59") else f", {at}–{until}")
    out = {"at": at, "days": sorted(set(days)), "title": _str(x, "title", where, need=False) or when,
           "prompt": fill(_str(x, "prompt", where), settings), "when": when}
    if every:                                    # проверка по кругу (аварийные заявки): каждые N минут в окне at–until
        out |= {"every": every, "until": until}
    if workday:                                  # раз в месяц: N-й рабочий день по производственному календарю РФ
        out |= {"workday": workday, "when": f"{at}, {workday}-й рабочий день месяца", "days": [1, 2, 3, 4, 5]}
        out["title"] = _str(x, "title", where, need=False) or out["when"]
    return out


def work_calendar() -> dict[date, bool]:
    """Особые дни производственного календаря РФ (дата → рабочий ли) из общего блока deadlines; свой блок
    (``<config>/modules/_common/``) перекрывает встроенный. Нет файла — пустой словарь (тогда рабочие — пн–пт)."""
    out: dict[date, bool] = {}
    for p in (builtin_dir() / COMMON / CALENDAR, user_dir() / COMMON / CALENDAR):
        try:
            with p.open(encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    out[date.fromisoformat(row["дата"].strip())] = row["вид"].strip() == "рабочий"
        except (OSError, KeyError, ValueError):
            continue
    return out


def nth_workday(year: int, month: int, n: int, cal: dict[date, bool]) -> date | None:
    """N-й рабочий день месяца. Года нет в календаре — рабочие дни пн–пт (без праздников); столько рабочих дней
    в месяце нет — None."""
    known = any(d.year == year for d in cal)
    d = date(year, month, 1)
    while d.month == month:
        if cal.get(d, d.isoweekday() < 6) if known else d.isoweekday() < 6:
            n -= 1
            if n == 0:
                return d
        d += timedelta(days=1)
    return None


def _decision(x, where: str) -> dict:
    if not isinstance(x, dict):
        raise ModuleError(f"{where}: [[decisions]] — таблица с полями question, options")
    opts = x.get("options", ["Да", "Нет"])
    if not isinstance(opts, list) or not 2 <= len(opts) <= 4 or not all(isinstance(o, str) and o for o in opts):
        raise ModuleError(f"{where}: options — от 2 до 4 вариантов строками (кнопки в Telegram и панели)")
    return {"question": _str(x, "question", where), "options": opts, "when": _str(x, "when", where, need=False)}


DEMO_KINDS = ("summary", "reminder", "request")


def _demo(raw, where: str) -> dict:
    """[demo] — необязательная секция для страницы предложения и демо в Telegram (docs/OFFERS.md):
    ``kind`` — как показывать модуль; ``[[demo.telegram]]`` — 3–4 сообщения сценария: text, buttons, replies."""
    if not isinstance(raw, dict) or set(raw) - {"kind", "telegram"}:
        raise ModuleError(f"{where}: [demo] — ключи kind и [[demo.telegram]]")
    kind = raw.get("kind", "")
    if kind and kind not in DEMO_KINDS:
        raise ModuleError(f"{where}: demo.kind — одно из: {', '.join(DEMO_KINDS)}")
    steps = raw.get("telegram", [])
    if not isinstance(steps, list) or len(steps) > 6:
        raise ModuleError(f"{where}: [[demo.telegram]] — до 6 сообщений")
    out = []
    for x in steps:
        if not isinstance(x, dict) or set(x) - {"text", "buttons", "replies"}:
            raise ModuleError(f"{where}: [[demo.telegram]] — поля text, buttons, replies")
        text, buttons, replies = _str(x, "text", where), x.get("buttons", []), x.get("replies", [])
        if (not isinstance(buttons, list) or not isinstance(replies, list) or len(buttons) != len(replies)
                or len(buttons) > 4 or not all(isinstance(b, str) and 0 < len(b) <= 40 for b in buttons)
                or not all(isinstance(a, str) and a.strip() for a in replies)):
            raise ModuleError(f"{where}: demo.telegram — buttons (до 4, до 40 знаков) и replies — списки одной длины")
        if len(text) > 1500:
            raise ModuleError(f"{where}: demo.telegram text — не длиннее 1500 знаков")
        out.append({"text": text, "buttons": buttons, "replies": replies})
    return {"kind": kind, "telegram": out}


def fill(text: str, settings: dict) -> str:
    """``{{ключ}}`` → значение из [settings]; незнакомые ``{{…}}`` остаются как есть."""
    for k, v in settings.items():
        text = text.replace("{{" + k + "}}", "да" if v is True else "нет" if v is False else str(v))
    return text


def parse(folder: Path) -> dict:
    """module.toml → словарь модуля; ошибка — ModuleError с понятным текстом (какая папка, какое поле)."""
    where = f"модуль {folder.name}"
    try:
        raw = tomllib.loads((folder / "module.toml").read_text(encoding="utf-8"))
    except OSError:
        raise ModuleError(f"{where}: нет файла module.toml") from None
    except tomllib.TOMLDecodeError as e:
        raise ModuleError(f"{where}: ошибка в module.toml — {e}") from None
    mid = raw.get("id", folder.name)
    if mid != folder.name or not ID.match(str(mid)):
        raise ModuleError(f"{where}: id — как имя папки, латиница в нижнем регистре, цифры, дефис (2–41 знак)")
    if not (folder / "CLAUDE.md").is_file():
        raise ModuleError(f"{where}: нет CLAUDE.md — роли и правил агента")
    settings = raw.get("settings", {})
    if not isinstance(settings, dict) or not all(isinstance(v, str | int | float | bool) for v in settings.values()):
        raise ModuleError(f"{where}: [settings] — простые значения: строка, число, true/false")
    lists = {}
    for key in ("integrations", "schedule", "decisions"):
        v = raw.get(key, [])
        if not isinstance(v, list):
            raise ModuleError(f"{where}: {key} — список таблиц [[{key}]]")
        lists[key] = v
    uses = raw.get("uses", [])
    if not isinstance(uses, list) or not all(isinstance(u, str) for u in uses):
        raise ModuleError(f"{where}: uses — список id общих блоков, например [\"reviews\"]")
    known = blocks() if uses else {}
    for u in uses:
        if u not in known:
            raise ModuleError(f"{where}: в uses нет такого общего блока «{u}» — есть: "
                              + (", ".join(sorted(known)) or "никаких"))
    sections = raw.get("sections", [])                  # разделы чата бизнес-ролей (personas.SECTIONS); нет — во всех
    if not isinstance(sections, list) or any(x not in SECTIONS for x in sections):
        raise ModuleError(f"{where}: sections — список из {', '.join(SECTIONS)}")
    sources = raw.get("data_sources", [])
    if not isinstance(sources, list):
        raise ModuleError(f"{where}: data_sources — список таблиц [[data_sources]]")
    skills = sorted({p.parent.name for p in (folder / "skills").glob("*/SKILL.md")}
                    | {s for u in uses for s in known[u]["skills"]})
    return {
        "id": mid, "version": str(raw.get("version", "1")), "title": _str(raw, "title", where),
        "industry": _str(raw, "industry", where), "about": _str(raw, "about", where),
        "sections": [x for x in SECTIONS if x in sections],
        "description": fill(_str(raw, "description", where, need=False), settings),
        "start": fill(_str(raw, "start", where, need=False) or DEFAULT_START, settings),
        "integrations": [_integration(x, where) for x in lists["integrations"]],
        "schedule": [_schedule(x, where, settings) for x in lists["schedule"]],
        "decisions": [_decision(x, where) for x in lists["decisions"]],
        "data_sources": [_source(x, where) for x in sources],
        "demo": _demo(raw.get("demo", {}), where),
        "uses": [{"id": u, "title": known[u]["title"], "about": known[u]["about"]} for u in uses],
        "settings": settings, "skills": skills,
        "files": sorted(p.name + ("/" if p.is_dir() else "") for p in folder.iterdir() if p.name not in SKIP),
        "path": str(folder),
    }


def catalog(errors: list[str] | None = None) -> list[dict]:
    """Все модули: встроенные и свои (``<config>/modules``). Битый модуль пропускаем, текст ошибки — в ``errors``."""
    found: dict[str, dict] = {}
    for base in (builtin_dir(), user_dir()):
        for d in sorted(base.iterdir()) if base.is_dir() else []:
            if d.name.startswith("_") or not (d / "module.toml").is_file():
                continue
            try:
                m = parse(d)
            except ModuleError as e:
                if errors is not None:
                    errors.append(str(e))
                continue
            found[m["id"]] = m
    return sorted(found.values(), key=lambda m: (m["industry"] != "Общие", m["industry"], m["title"]))


def get(mid: str) -> dict:
    m = next((x for x in catalog() if x["id"] == mid), None)
    if not m:
        raise LookupError("нет такого модуля — обновите список")
    return m


def public(m: dict) -> dict:
    """Модуль для панели и бота: без пути на диске."""
    return {k: v for k, v in m.items() if k != "path"}


def free_name(root: Path, base: str) -> str:
    """Имя папки по умолчанию: ``<id>``, занято — ``<id>-2``, ``<id>-3``…"""
    if not (root / base).exists():
        return base
    n = 2
    while (root / f"{base}-{n}").exists():
        n += 1
    return f"{base}-{n}"


def check_name(name: str) -> str:
    name = (name or "").strip().lower()
    if not ID.match(name):
        raise ModuleError("имя папки: латиница в нижнем регистре, цифры, дефис (2–41 знак), без «/» и «..»")
    return name


# Язык ответов агента пространства (простой режим панели): официальная настройка Claude Code ``language`` в
# ``.claude/settings.json`` («Preferred language for Claude responses»), а не просьба в CLAUDE.md.
LANGUAGE = {"ru": "russian", "en": "english"}


def create(mid: str, root: Path, name: str = "", by: int | None = None, lang: str = "") -> Path:
    """Новое пространство из модуля: папка ``root/name`` с CLAUDE.md, .claude/skills, примером данных и отметкой.
    Папка уже есть — отказ (ничего не трогаем). git init — чтобы любое изменение агента можно было откатить.
    ``lang`` (ru, en) — язык ответов агента: ``language`` в настройках Claude Code пространства."""
    m = get(mid)
    src = Path(m["path"])
    name = check_name(name or free_name(root, mid))
    dst = root / name
    if dst.exists() or dst.is_symlink():
        raise ModuleError(f"папка {name} уже есть — выберите другое имя")
    root.mkdir(parents=True, exist_ok=True)
    dst.mkdir()
    try:
        for p in sorted(src.iterdir()):
            if p.name in SKIP:
                continue
            if p.is_dir():
                shutil.copytree(p, dst / p.name, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
            elif p.name == "CLAUDE.md":
                (dst / p.name).write_text(claude_md(m), encoding="utf-8")
            else:
                shutil.copy2(p, dst / p.name)
        if (src / "skills").is_dir():
            shutil.copytree(src / "skills", dst / ".claude" / "skills",
                            ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
        common = blocks() if m["uses"] else {}
        for u in m["uses"]:
            sk = Path(common[u["id"]]["path"]) / "skills"
            if sk.is_dir():
                shutil.copytree(sk, dst / ".claude" / "skills", dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
        if (src / "settings.json").is_file():
            (dst / ".claude").mkdir(exist_ok=True)
            shutil.copy2(src / "settings.json", dst / ".claude" / "settings.json")
        if lang in LANGUAGE:
            sf = dst / ".claude" / "settings.json"
            sf.parent.mkdir(exist_ok=True)
            try:
                st = json.loads(sf.read_text(encoding="utf-8")) if sf.is_file() else {}
            except ValueError:
                st = {}
            st = st if isinstance(st, dict) else {}
            st["language"] = LANGUAGE[lang]
            sf.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        mark = {"id": m["id"], "version": m["version"], "title": m["title"], "created": int(time.time())}
        if by is not None:
            mark["by"] = by
        (dst / MARK).write_text(json.dumps(mark, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    except OSError:
        shutil.rmtree(dst, ignore_errors=True)           # наполовину созданное — убираем: имя снова свободно
        raise
    try:
        subprocess.run(["git", "init", "-q", "-b", "main", str(dst)], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        pass                                             # без git пространство работает, только без истории правок
    return dst


def claude_md(m: dict) -> str:
    """CLAUDE.md пространства: правила модуля и разделы общих блоков из ``uses``; ``{{ключ}}`` — из [settings]."""
    text = (Path(m["path"]) / "CLAUDE.md").read_text(encoding="utf-8").rstrip() + "\n"
    common = blocks() if m["uses"] else {}
    for u in m["uses"]:
        b = common[u["id"]]
        text += f"\n## Общий блок: {b['title']}\n\n{b['rules']}\n"
    if m["data_sources"]:
        text += ("\n## Откуда данные\n\nТолько эти источники — официальные API и выгрузки самого клиента. "
                 "Не собирай данные с сайтов, из личных кабинетов в обход API и из купленных баз.\n\n"
                 + "".join(f"- {s['title']} — {s['kind_title']}" + (f": {s['about']}" if s["about"] else "") + "\n"
                           for s in m["data_sources"]))
    return fill(text, m["settings"])


def mark_of(folder: Path) -> dict | None:
    """Отметка пространства. ``schedule``: on (по умолчанию) / paused / off; ``.gas-pult-module.off`` — off."""
    for name, off in ((MARK, False), (MARK_OFF, True)):
        try:
            d = json.loads((folder / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get("id"):
            st = "off" if off else d.get("schedule")
            return {**d, "schedule": st if st in SCHEDULE_STATES else "on"}
    return None


def set_schedule(folder: Path, state: str) -> dict:
    """Расписание пространства: on / paused / off — в отметке (``.off`` переводится в обычную отметку)."""
    if state not in SCHEDULE_STATES:
        raise ValueError("расписание: on, paused или off")
    mk = mark_of(folder)
    if not mk:
        raise ValueError("эта папка — не пространство из модуля")
    mk["schedule"] = state
    tmp = folder / f"{MARK}.tmp"
    tmp.write_text(json.dumps(mk, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(folder / MARK)
    (folder / MARK_OFF).unlink(missing_ok=True)
    return mk


def schedule_text(m: dict) -> str:
    """«по будням 10:00, 17:00» — расписание модуля одной строкой (пункты с одинаковыми днями — вместе)."""
    groups: dict[str, list[str]] = {}
    for it in m.get("schedule") or []:
        if it.get("every"):
            key, at = days_text(it["days"]), f"{it['at']}–{it['until']} каждые {it['every']} мин"
        elif it.get("workday"):
            key, at = f"{it['workday']}-й рабочий день месяца", it["at"]
        else:
            key, at = days_text(it["days"]), it["at"]
        groups.setdefault(key, []).append(at)
    return "; ".join(f"{k} {', '.join(v)}" for k, v in groups.items())


def next_run(m: dict, now: datetime, cal=None) -> datetime | None:
    """Ближайший запуск по расписанию модуля после ``now`` (в пределах 40 дней)."""
    best = None
    for it in m.get("schedule") or []:
        hh, mm = int(it["at"][:2]), int(it["at"][3:])
        for d in range(0, 40):
            day = (now + timedelta(days=d)).replace(hour=hh, minute=mm, second=0, microsecond=0)
            if it.get("workday"):
                cal = work_calendar() if cal is None else cal
                if nth_workday(day.year, day.month, it["workday"], cal) != day.date():
                    continue
            elif day.isoweekday() not in it["days"]:
                continue
            if it.get("every") and d == 0 and it["at"] <= now.strftime("%H:%M") <= it["until"]:
                day = now + timedelta(minutes=it["every"] - (now.minute % it["every"]))
            elif day <= now:
                continue
            best = day if best is None or day < best else best
            break
    return best


def workspaces(roots: list[Path]) -> list[tuple[Path, dict]]:
    """Пространства из модулей в корнях проектов: (папка, отметка)."""
    out = []
    for root in roots:
        for d in sorted(root.iterdir()) if root.is_dir() else []:
            if d.is_dir() and (mk := mark_of(d)):
                out.append((d, mk))
    return out


def changed_at(folder: Path) -> float:
    """Последнее изменение пространства: сама папка и её файлы первого уровня (без обхода всего дерева)."""
    ts = [folder.stat().st_mtime]
    try:
        ts += [p.stat().st_mtime for p in folder.iterdir()]
    except OSError:
        pass
    return max(ts)


def existing(root: Path, mid: str) -> list[dict]:
    """Уже созданные пространства модуля ``mid`` в корне — свежие первыми: [{folder, path, changed}]. Чтобы не
    плодить ``<id>-2``, ``<id>-3``: панель и бот сначала предлагают открыть существующее."""
    out = [{"folder": d.name, "path": d, "changed": int(changed_at(d))}
           for d, mk in workspaces([root]) if mk.get("id") == mid]
    return sorted(out, key=lambda x: -x["changed"])


def days_text(days: list[int]) -> str:
    if days == list(range(1, 8)):
        return "каждый день"
    if days == list(range(1, 6)):
        return "по будням"
    return ", ".join(WEEKDAYS[d - 1] for d in days)


class Schedule:
    """Когда что отправляли: ``modules.json`` — ключ «папка|время» → дата. Логика как у утренней сводки
    (``digest.Digest.due``): время наступило, а сегодня ещё не было; плюс не догоняем позже ``CATCH_UP``."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict:
        try:
            d = json.loads(self.path.read_text())
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self, st: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False))
        tmp.replace(self.path)

    def due(self, roots: list[Path], now: datetime) -> list[tuple[Path, dict, dict]]:
        """Что отправить сейчас: (папка, модуль, пункт расписания). Сразу отмечает отправленным — не дважды.
        Пространство создано позже назначенного времени или пульт был выключен дольше CATCH_UP — сегодня пропускаем."""
        st, today, out = self.load(), now.strftime("%Y-%m-%d"), []
        by_id, cal = {m["id"]: m for m in catalog()}, None
        for folder, mk in workspaces(roots):
            if mk.get("schedule", "on") != "on":       # на паузе или выключено — не открываем и не пишем
                continue
            m = by_id.get(mk["id"])
            for item in (m or {}).get("schedule", []):
                if item.get("every"):
                    if hit := self._every(st, folder, mk, item, now):
                        out.append((folder, m, hit))
                    continue
                k = f"{folder}|{item['at']}" + (f"|{item['workday']}wd" if item.get("workday") else "")
                if st.get(k) == today or now.strftime("%H:%M") < item["at"]:
                    continue
                if item.get("workday"):                  # раз в месяц: сегодня — N-й рабочий день?
                    cal = work_calendar() if cal is None else cal
                    if nth_workday(now.year, now.month, item["workday"], cal) != now.date():
                        continue
                elif now.isoweekday() not in item["days"]:
                    continue
                st[k] = today
                at = now.replace(hour=int(item["at"][:2]), minute=int(item["at"][3:]), second=0, microsecond=0)
                created = mk.get("created", 0)
                if (now - at).total_seconds() <= CATCH_UP and not (isinstance(created, int | float)
                                                                   and created > at.timestamp()):
                    out.append((folder, m, item))
        if out or st != self.load():
            self.save(st)
        return out

    @staticmethod
    def _every(st: dict, folder: Path, mk: dict, item: dict, now: datetime) -> dict | None:
        """Пункт «каждые N минут» в окне at–until: один раз на отрезок; пропущенные отрезки не догоняем — только
        текущий. Пространство создано позже начала отрезка — ждём следующий."""
        hm = now.strftime("%H:%M")
        if now.isoweekday() not in item["days"] or not item["at"] <= hm <= item["until"]:
            return None
        start = now.replace(hour=int(item["at"][:2]), minute=int(item["at"][3:]), second=0, microsecond=0)
        slot = int((now - start).total_seconds() // 60) // item["every"]
        k, v = f"{folder}|{item['at']}/{item['every']}", f"{now:%Y-%m-%d}#{slot}"
        if st.get(k) == v:
            return None
        st[k] = v
        begin = start.timestamp() + slot * item["every"] * 60
        created = mk.get("created", 0)
        return None if isinstance(created, int | float) and created > begin else item
