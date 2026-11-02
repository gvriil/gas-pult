"""Сценарии «Примерить на себя»: роль → день с агентом → польза в цифрах (docs/SCENARIOS.md).

Сценарий — файл ``templates/scenarios/<роль>.toml`` в пакете (встроенные) или ``<config>/scenarios/<роль>.toml``
(свои; одноимённый свой заменяет встроенный). Формат — TOML, а не YAML: ядро пульта — только стандартная
библиотека, ``tomllib`` в ней есть, парсера YAML нет (так же устроены модули).

В файле: кто вы и что болит, модули (id из каталога ``modules.py``), «день с агентом» — 3–5 моментов со временем,
сообщением агента и кнопками-решениями **ровно как в модуле** (варианты из ``[[decisions]]`` или
``[[demo.telegram]]``), что было бы без агента, вводные и строки «пользы» — декларативно: коэффициенты × вводные,
без выражений и без eval; что нужно от клиента и первый шаг.

Здесь же: проверка схемы с понятными ошибками, расчёт пользы ``benefit`` (тот же, что в панели и на странице
предложения — функция ``benefitCalc`` в index.html и offer.html, тест сверяет), ``public`` — для панели, страницы
предложения и бота (без путей), ``telegram_page`` — страница сценария одним сообщением бота, ``for_offer`` — сценарий
отрасли предложения с цифрами из его ``[demo]``, ``help_snippets`` — короткие «где польза» для помощника.

``python -m gas_pult.scenarios`` (из клона репозитория) пересобирает docs/SCENARIOS.md и демо-данные панели.
"""

from __future__ import annotations

import copy
import json
import math
import re
import tomllib
from importlib import resources
from pathlib import Path

from gas_pult import modules
from gas_pult.config import config_dir

ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")      # id роли = имя файла; короткий — влезает в callback_data
AT = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
VAR = re.compile(r"^[a-z][a-z0-9_]{0,19}$")
OFFER_FIELDS = ("points", "clients", "avg_check", "daily_revenue")    # что берём из [demo] предложения
NOTE = "Оценка, не обещание: считаем по допущениям, точные цифры покажет пилот на ваших данных за 4 недели."
DEMO_MARK = "данные выдуманы для демонстрации"
KEYS = {"title", "short", "who", "industries", "offer", "modules", "without", "needs", "first_step", "demo",
        "moments", "inputs", "benefit", "note"}


class ScenarioError(ValueError):
    """Ошибка в файле сценария — текст для человека, по-русски (какой файл, какое поле)."""


def builtin_dir() -> Path:
    return Path(str(resources.files("gas_pult").joinpath("templates/scenarios")))


def user_dir() -> Path:
    return config_dir() / "scenarios"


# ---------- проверка схемы ----------
def _str(raw: dict, key: str, where: str, need: bool = True, size: int = 1500) -> str:
    v = raw.get(key, "")
    if not isinstance(v, str) or (need and not v.strip()):
        raise ScenarioError(f"{where}: поле «{key}» — " + ("обязательная строка" if need else "строка"))
    if len(v) > size:
        raise ScenarioError(f"{where}: поле «{key}» — не длиннее {size} знаков")
    return v.strip()


def _strs(raw: dict, key: str, where: str, lo: int, hi: int, size: int = 300) -> list[str]:
    v = raw.get(key, [])
    if not isinstance(v, list) or not lo <= len(v) <= hi or not all(isinstance(x, str) and x.strip() for x in v):
        raise ScenarioError(f"{where}: «{key}» — список из {lo}–{hi} строк")
    if any(len(x) > size for x in v):
        raise ScenarioError(f"{where}: «{key}» — строки не длиннее {size} знаков")
    return [x.strip() for x in v]


def _num(raw: dict, key: str, where: str, need: bool = True, default: float = 0) -> float:
    v = raw.get(key, None if need else default)
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
        raise ScenarioError(f"{where}: «{key}» — число")
    return v


def _options(m: dict) -> list[list[str]]:
    """Какие наборы кнопок есть у модуля: варианты каждого решения и кнопки каждого сообщения [[demo.telegram]]."""
    return [d["options"] for d in m["decisions"]] + [x["buttons"] for x in m["demo"]["telegram"] if x["buttons"]]


def _moment(x, where: str, mods: dict, own: list[str]) -> dict:
    if not isinstance(x, dict) or set(x) - {"at", "day", "module", "text", "buttons"}:
        raise ScenarioError(f"{where}: [[moments]] — поля at, day, module, text, [[moments.buttons]]")
    at = _str(x, "at", where)
    if not AT.match(at):
        raise ScenarioError(f"{where}: at = \"{at}\" — время ЧЧ:ММ, например \"08:00\"")
    mid = _str(x, "module", where, need=False)
    if mid and mid not in own:
        raise ScenarioError(f"{where}: момент {at} — модуль «{mid}» не из списка modules этой роли")
    btns = x.get("buttons", [])
    if not isinstance(btns, list) or len(btns) > 4:
        raise ScenarioError(f"{where}: момент {at} — до 4 кнопок [[moments.buttons]]")
    out = []
    for b in btns:
        if not isinstance(b, dict) or set(b) - {"label", "result"}:
            raise ScenarioError(f"{where}: момент {at} — у кнопки поля label и result")
        out.append({"label": _str(b, "label", where, size=40), "result": _str(b, "result", where, size=500)})
    labels = [b["label"] for b in out]
    if mid and labels and labels not in _options(mods[mid]):
        raise ScenarioError(f"{where}: момент {at} — кнопки {labels} не совпадают ни с одним решением модуля «{mid}»; "
                            f"есть: {_options(mods[mid])}")
    if not mid and labels:
        raise ScenarioError(f"{where}: момент {at} — кнопки-решения только у момента с модулем (module = \"…\")")
    return {"at": at, "day": _str(x, "day", where, need=False, size=60), "module": mid,
            "text": _str(x, "text", where, size=1200), "buttons": out}


def _input(x, where: str) -> dict:
    if not isinstance(x, dict) or set(x) - {"id", "title", "unit", "default", "min", "max", "step", "about", "offer"}:
        raise ScenarioError(f"{where}: [[inputs]] — поля id, title, unit, default, min, max, step, about, offer")
    iid = _str(x, "id", where)
    if not VAR.match(iid):
        raise ScenarioError(f"{where}: inputs id «{iid}» — латиница в нижнем регистре, цифры, «_»")
    lo, hi, d = _num(x, "min", where), _num(x, "max", where), _num(x, "default", where)
    step = _num(x, "step", where, need=False, default=1)
    if not 0 < lo <= d <= hi or step <= 0:
        raise ScenarioError(f"{where}: вводная «{iid}» — нужно 0 < min ≤ default ≤ max и step > 0")
    off = _str(x, "offer", where, need=False)
    if off and off not in OFFER_FIELDS:
        raise ScenarioError(f"{where}: вводная «{iid}»: offer — одно из {', '.join(OFFER_FIELDS)}")
    return {"id": iid, "title": _str(x, "title", where, size=80), "unit": _str(x, "unit", where, need=False, size=30),
            "default": d, "min": lo, "max": hi, "step": step, "about": _str(x, "about", where, size=400),
            "offer": off}


def _line(x, where: str, ids: set[str]) -> dict:
    """Строка пользы: значение = (произведение вводных из ``of``) × коэффициент; low и high — диапазон."""
    if not isinstance(x, dict) or set(x) - {"title", "unit", "of", "low", "high", "round", "about"}:
        raise ScenarioError(f"{where}: [[benefit]] — поля title, unit, of, low, high, round, about")
    title = _str(x, "title", where, size=80)
    of = x.get("of", [])
    if not isinstance(of, list) or len(of) > 3 or not all(isinstance(k, str) for k in of):
        raise ScenarioError(f"{where}: польза «{title}»: of — список до 3 id вводных")
    if bad := [k for k in of if k not in ids]:
        raise ScenarioError(f"{where}: польза «{title}»: нет таких вводных {bad} — есть {sorted(ids)}")
    lo, hi = _num(x, "low", where), _num(x, "high", where)
    rnd = _num(x, "round", where, need=False, default=1)
    if not 0 <= lo <= hi or rnd <= 0:
        raise ScenarioError(f"{where}: польза «{title}» — нужно 0 ≤ low ≤ high и round > 0")
    return {"title": title, "unit": _str(x, "unit", where, size=40), "of": list(of), "low": lo, "high": hi,
            "round": rnd, "about": _str(x, "about", where, size=500)}


def parse(path: Path, mods: dict[str, dict] | None = None) -> dict:
    """Файл сценария → словарь; ошибка — ScenarioError (какой файл, какое поле). ``mods`` — каталог модулей."""
    from gas_pult.offers import INDUSTRIES

    rid, where = path.stem, f"сценарий {path.name}"
    if not ID.match(rid):
        raise ScenarioError(f"{where}: имя файла — id роли: латиница в нижнем регистре, цифры, дефис (2–31 знак)")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise ScenarioError(f"{where}: файл не читается") from None
    except tomllib.TOMLDecodeError as e:
        raise ScenarioError(f"{where}: ошибка в toml — {e}") from None
    if unknown := set(raw) - KEYS - {"id"}:
        raise ScenarioError(f"{where}: неизвестные ключи {sorted(unknown)}")
    if raw.get("id", rid) != rid:
        raise ScenarioError(f"{where}: id — как имя файла")
    mods = {m["id"]: m for m in modules.catalog()} if mods is None else mods
    own = _strs(raw, "modules", where, 1, 6, 41)
    if bad := [m for m in own if m not in mods]:
        raise ScenarioError(f"{where}: нет таких модулей {bad} — список: панель → «Из модуля» или /modules")
    inds = _strs(raw, "industries", where, 1, 3, 80)
    known = {m["industry"] for m in mods.values()}
    if bad := [i for i in inds if i not in known]:
        raise ScenarioError(f"{where}: industries {bad} — нет такой отрасли в каталоге модулей")
    if bad := [m for m in own if mods[m]["industry"] not in [*inds, "Общие"]]:
        raise ScenarioError(f"{where}: модули {bad} — из другой отрасли, чем industries роли")
    offer = raw.get("offer", [])
    if not isinstance(offer, list) or not all(isinstance(x, str) and x in INDUSTRIES for x in offer):
        raise ScenarioError(f"{where}: offer — список отраслей предложения: {', '.join(INDUSTRIES)}")
    demo = raw.get("demo", {})
    if not isinstance(demo, dict) or set(demo) - {"business", "point"}:
        raise ScenarioError(f"{where}: [demo] — ключи business и point (выдуманные)")
    moments = raw.get("moments", [])
    if not isinstance(moments, list) or not 3 <= len(moments) <= 5:
        raise ScenarioError(f"{where}: «день с агентом» — от 3 до 5 моментов [[moments]]")
    ms = [_moment(x, where, mods, own) for x in moments]
    if [x["at"] for x in ms if not x["day"]] != sorted(x["at"] for x in ms if not x["day"]):
        raise ScenarioError(f"{where}: моменты — по порядку времени")
    raw_in = raw.get("inputs", [])
    if not isinstance(raw_in, list) or not 1 <= len(raw_in) <= 5:
        raise ScenarioError(f"{where}: вводные — от 1 до 5 [[inputs]]")
    inputs = [_input(x, where) for x in raw_in]
    ids = {x["id"] for x in inputs}
    if len(ids) != len(inputs):
        raise ScenarioError(f"{where}: id вводных повторяются")
    raw_b = raw.get("benefit", [])
    if not isinstance(raw_b, list) or not 1 <= len(raw_b) <= 5:
        raise ScenarioError(f"{where}: польза — от 1 до 5 строк [[benefit]]")
    return {
        "id": rid, "title": _str(raw, "title", where, size=60), "short": _str(raw, "short", where, size=160),
        "who": _str(raw, "who", where, size=600), "industries": inds, "offer": offer, "modules": own,
        "without": _str(raw, "without", where, size=900), "needs": _strs(raw, "needs", where, 1, 6),
        "first_step": _str(raw, "first_step", where, size=400),
        "demo": {"business": str(demo.get("business", "«Пример»"))[:60], "point": str(demo.get("point", "Центр"))[:40]},
        "moments": ms, "inputs": inputs, "benefit": [_line(x, where, ids) for x in raw_b],
        "note": _str(raw, "note", where, need=False, size=300) or NOTE, "path": str(path),
    }


def catalog(errors: list[str] | None = None) -> list[dict]:
    """Все роли: встроенные и свои. Битый сценарий пропускаем, текст ошибки — в ``errors``."""
    mods = {m["id"]: m for m in modules.catalog()}
    found: dict[str, dict] = {}
    for base in (builtin_dir(), user_dir()):
        for p in sorted(base.glob("*.toml")) if base.is_dir() else []:
            try:
                s = parse(p, mods)
            except ScenarioError as e:
                if errors is not None:
                    errors.append(str(e))
                continue
            found[s["id"]] = s
    order = list(dict.fromkeys(m["industry"] for m in mods.values() if m["industry"] != "Общие"))
    rank = {g: i for i, g in enumerate(order)}
    return sorted(found.values(), key=lambda s: (rank.get(s["industries"][0], len(rank)), not s["offer"], s["id"]))


def get(rid: str) -> dict:
    s = next((x for x in catalog() if x["id"] == rid), None)
    if not s:
        raise LookupError("нет такой роли — обновите список")
    return s


# ---------- польза: тот же расчёт, что benefitCalc в index.html и offer.html ----------
def _value(v, default: float) -> float:
    if isinstance(v, bool):
        return default
    if isinstance(v, str):
        v = v.strip().replace(",", ".")
        if not v:
            return default
        try:
            v = float(v)
        except ValueError:
            return default
    if not isinstance(v, int | float) or not math.isfinite(v):
        return default
    return v


def _round(v: float, r: float) -> float:
    return math.floor(v / r + 0.5) * r


def fmt(v: float) -> str:
    """Число по-русски: 12 500, 4,5 (одна десятичная, без «,0»)."""
    t = math.floor(v * 10 + 0.5)
    whole, tenth = t // 10, t % 10
    return f"{whole:,}".replace(",", " ") + (f",{tenth}" if tenth else "")


def benefit(role: dict | str, inputs: dict | None = None) -> dict:
    """Оценка пользы: вводные (нет или мусор — по умолчанию, вне границ — к границе) → строки с диапазоном low–high.
    Только умножение вводных на коэффициенты из toml: ни выражений, ни eval."""
    s = get(role) if isinstance(role, str) else role
    inputs = inputs or {}
    inp = {x["id"]: min(x["max"], max(x["min"], _value(inputs.get(x["id"]), x["default"]))) for x in s["inputs"]}
    lines = []
    for ln in s["benefit"]:
        base = 1
        for k in ln["of"]:
            base *= inp[k]
        lo, hi = _round(base * ln["low"], ln["round"]), _round(base * ln["high"], ln["round"])
        text = (f"≈ {fmt(lo)}" if lo == hi else f"{fmt(lo)}–{fmt(hi)}") + f" {ln['unit']}"
        lines.append({"title": ln["title"], "unit": ln["unit"], "low": lo, "high": hi, "text": text,
                      "about": ln["about"]})
    return {"inputs": inp, "lines": lines, "note": s["note"]}


# ---------- для панели, предложения, бота и помощника ----------
def _fill(text: str, ctx: dict) -> str:
    for k, v in ctx.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def public(s: dict, ctx: dict | None = None) -> dict:
    """Сценарий без пути и служебного (``offer``): плейсхолдеры {{business}}, {{point}}, {{<вводная>}} — из ``ctx``
    (по умолчанию — выдуманные из [demo] роли); ``ctx["inputs"]`` — новые значения вводных по умолчанию."""
    ctx = ctx or {}
    out = copy.deepcopy({k: v for k, v in s.items() if k not in ("path", "offer")})
    for x in out["inputs"]:
        x.pop("offer", None)
        if (v := (ctx.get("inputs") or {}).get(x["id"])) is not None:
            x["default"] = min(x["max"], max(x["min"], _value(v, x["default"])))
    vals = {"business": ctx.get("business") or s["demo"]["business"], "point": ctx.get("point") or s["demo"]["point"],
            **{x["id"]: fmt(x["default"]) for x in out["inputs"]}}
    for k in ("who", "without", "first_step"):
        out[k] = _fill(out[k], vals)
    out["needs"] = [_fill(x, vals) for x in out["needs"]]
    titles = {m["id"]: m for m in modules.catalog()}
    out["modules"] = [{"id": m, "title": titles[m]["title"], "industry": titles[m]["industry"]}
                      for m in s["modules"] if m in titles]
    for mo in out["moments"]:
        mo["text"] = _fill(mo["text"], vals)
        mo["module_title"] = titles[mo["module"]]["title"] if mo["module"] in titles else ""
        for b in mo["buttons"]:
            b["result"] = _fill(b["result"], vals)
    out["demo"] = {"business": vals["business"], "point": vals["point"]}
    out["benefit_default"] = benefit(out)["lines"]
    return out


def api_data(errors: list[str] | None = None) -> dict:
    """Ответ ``GET /api/scenarios``: роли для панели (и для её демо — тот же JSON, тест сверяет)."""
    return {"scenarios": [public(s) for s in catalog(errors)], "note": NOTE}


def for_industry(industry: str) -> dict | None:
    """Первая роль отрасли каталога (для «Как это выглядит в работе» у отрасли)."""
    return next((s for s in catalog() if industry in s["industries"]), None)


def for_offer(o: dict) -> dict | None:
    """Сценарий для страницы предложения: роль его отрасли (больше общих модулей — лучше), цифры — из [demo]."""
    cands = [s for s in catalog() if o.get("industry") in s["offer"]]
    if not cands:
        return None
    s = max(cands, key=lambda x: len(set(x["modules"]) & set(o.get("modules", []))))   # при равенстве — первая
    d = o.get("demo") or {}
    src = {"points": len(d.get("points") or []) or None, "clients": d.get("clients"), "avg_check": d.get("avg_check"),
           "daily_revenue": d.get("daily_revenue")}
    vals = {x["id"]: src[x["offer"]] for x in s["inputs"] if x["offer"] and src.get(x["offer"])}
    return public(s, {"business": o.get("business"), "point": (d.get("points") or [None])[0], "inputs": vals})


def help_snippets(role: str | None = None, industry: str | None = None) -> list[str]:
    """Короткие «где мне польза» для помощника (задача 19): по роли, по отрасли или по всем. Без внутреннего —
    только то, что видит человек в «Примерить на себя»; цифры — оценка по умолчанию, с пометкой."""
    out = []
    for s in catalog():
        if (role and s["id"] != role) or (industry and industry not in s["industries"]):
            continue
        p = public(s)
        mods = ", ".join(f"«{m['title']}»" for m in p["modules"])
        gain = "; ".join(f"{x['title'].lower()} — {x['text']}" for x in p["benefit_default"])
        out.append(f"{p['title']}: {p['short']} Модули: {mods}. Польза (оценка при значениях по умолчанию, не "
                   f"обещание): {gain}. Первый шаг: {p['first_step']} Подробно — «Примерить на себя».")
    return out


def pages(s: dict) -> int:
    """Страниц в боте: вступление, моменты дня, итог с пользой."""
    return len(s["moments"]) + 2


def telegram_page(s: dict, page: int, pressed: int | None = None) -> tuple[str, list[list[tuple[str, str]]]]:
    """Страница сценария одним сообщением бота: текст и кнопки ``(подпись, код)``; код — ``"<стр>"`` (перейти)
    или ``"<стр>:<кнопка>"`` (нажали решение). Бот дописывает к коду свой префикс (``sc:<роль>:`` или ``dm:…``).
    ``s`` — уже ``public`` (с подставленными цифрами)."""
    n = len(s["moments"])
    page = max(0, min(page, n + 1))
    if page == 0:
        mods = "\n".join(f"• {m['title']}" for m in s["modules"])
        text = (f"🎭 {s['title']}\n\n{s['who']}\n\nМодули:\n{mods}\n\nДальше — день с агентом: {n} моментов, кнопки "
                f"нажимаются. Цифры и имена выдуманы — {DEMO_MARK}.")
        return text, [[("Начать день ›", "1")]]
    if page <= n:
        mo = s["moments"][page - 1]
        head = f"🕗 {mo['at']}" + (f" · {mo['day']}" if mo["day"] else "") + (
            f" · {mo['module_title']}" if mo.get("module_title") else "")
        text = f"{head}\n\n{mo['text']}"
        if pressed is not None and 0 <= pressed < len(mo["buttons"]):
            b = mo["buttons"][pressed]
            text += f"\n\n↪️ «{b['label']}»: {b['result']}"
        text += f"\n\n— момент {page} из {n} · демо, ничего не отправлено"
        rows = [[(("✓ " if j == pressed else "") + b["label"], f"{page}:{j}")] for j, b in enumerate(mo["buttons"])]
        rows.append([("‹ Назад", str(page - 1)), ("Дальше ›", str(page + 1))])
        return text, rows
    gain = "\n".join(f"• {x['title']}: {x['text']}" for x in s["benefit_default"])
    assume = "\n".join(f"• {x['title']} — {fmt(x['default'])} {x['unit']}".rstrip() for x in s["inputs"])
    needs = "\n".join(f"• {x}" for x in s["needs"])
    text = (f"🎭 {s['title']} · итог дня\n\nБез агента: {s['without']}\n\n📈 Ваша польза — оценка:\n{gain}\n\n"
            f"Допущения (поменять — в панели, «Примерить на себя»):\n{assume}\n{s['note']}\n\n"
            f"Что нужно от вас:\n{needs}\n\nПервый шаг: {s['first_step']}")
    return text, [[("‹ Назад", str(n))], [("🔁 Сначала", "0")]]


# ---------- документация и демо-данные панели ----------
def markdown() -> str:
    """docs/SCENARIOS.md — из toml (тест сверяет: правьте toml и запускайте ``python -m gas_pult.scenarios``)."""
    out = [
        "# Сценарии «Примерить на себя»", "",
        "<!-- Файл собирается из src/gas_pult/templates/scenarios/*.toml: python -m gas_pult.scenarios -->", "",
        "Роль → «день с агентом» → польза в цифрах. Человек выбирает свою роль и видит, как агент работал бы у него: "
        "сообщения со временем, кнопки-решения ровно как в модулях, что было бы без агента и оценку пользы с "
        "допущениями, которые можно поправить под себя. Где это видно: панель → «Примерить на себя» (главная, «Новая "
        "сессия → Из модуля», у отрасли в каталоге «Как это выглядит в работе»), страница предложения `/offer/<код>` "
        "(блок «Как это выглядит у вас» с цифрами из `[demo]` предложения), бот — `/scenarios`.", "",
        f"**Польза — оценка с допущениями.** {NOTE} Цифры и имена в сценариях выдуманы; допущения — общие рыночные "
        "оценки и здравый смысл, без данных конкретных клиентов.", "",
        "## Как добавить роль", "",
        "1. Файл `src/gas_pult/templates/scenarios/<роль>.toml` (id роли — имя файла: латиница, цифры, дефис, до 31 "
        "знака) или свой — `~/.config/gas-pult/scenarios/<роль>.toml`.",
        "2. Поля: `title`, `short`, `who` (кто вы и что болит, 2–3 строки), `industries` (отрасли каталога модулей), "
        "`offer` (отрасли предложения: carwash, fitness, horeca, uk, sellers, services), `modules` (id из каталога), "
        "`without`, `needs`, `first_step`, `[demo]` (выдуманные business и point).",
        "3. `[[moments]]` — 3–5 моментов: `at` (ЧЧ:ММ), `day` (необязательно), `module`, `text` и "
        "`[[moments.buttons]]` (`label`, `result`). Подписи кнопок — **ровно** варианты одного решения модуля "
        "(`[[decisions]]` options) или кнопки его `[[demo.telegram]]`: иначе сценарий не загрузится.",
        "4. `[[inputs]]` — вводные (`id`, `title`, `unit`, `default`, `min`, `max`, `step`, `about` — откуда "
        "допущение, `offer` — какое поле `[demo]` предложения подставить: points, clients, avg_check, daily_revenue).",
        "5. `[[benefit]]` — строки пользы: `of` — id вводных, `low`/`high` — коэффициенты, значение = произведение "
        "вводных × коэффициент, `round` — шаг округления, `about` — допущение словами. Без выражений и eval.",
        "6. Плейсхолдеры в текстах: `{{business}}`, `{{point}}`, `{{<id вводной>}}`.",
        "7. `python -m gas_pult.scenarios` — пересобрать этот файл и демо-данные панели; проверка — "
        "`pytest tests/test_scenarios.py`.",
        "", "## Роли", "",
    ]
    out += [f"- [{s['title']}](#{s['id']}) — {s['short']}" for s in catalog()]
    for s0 in catalog():
        s = public(s0)
        out += ["", f'<a id="{s["id"]}"></a>', "", f"### {s['title']}", "",
                f"Отрасль: {', '.join(s['industries'])} · модули: "
                + ", ".join(f"`{m['id']}` «{m['title']}»" for m in s["modules"]), "",
                "**Кто вы и что болит.** " + s["who"], "", "**День с агентом** (демо-данные):", ""]
        for mo in s["moments"]:
            when = mo["at"] + (f", {mo['day']}" if mo["day"] else "")
            text = mo["text"].replace("\n", " ")
            out.append(f"- **{when}**" + (f" · {mo['module_title']}" if mo["module_title"] else "") + f" — {text}")
            out += [f"  - «{b['label']}» → {b['result']}" for b in mo["buttons"]]
        out += ["", "**Что было бы без агента.** " + s["without"], "",
                "**Польза в цифрах** (оценка при значениях по умолчанию):", ""]
        out += [f"- {x['title']}: {x['text']}. {x['about']}" for x in s["benefit_default"]]
        out += ["", "Вводные по умолчанию:", ""]
        out += [f"- {x['title']} — {fmt(x['default'])} {x['unit']}".rstrip() + f". {x['about']}" for x in s["inputs"]]
        out += ["", "**Что нужно от клиента:**", ""] + [f"- {x}" for x in s["needs"]]
        out += ["", "**Первый шаг.** " + s["first_step"]]
    return "\n".join(out) + "\n"


DEMO_PREFIX = '  R["/api/scenarios"] = '


def demo_line() -> str:
    """Строка демо-данных в index.html (``?demo``): тот же JSON, что отдаёт ``GET /api/scenarios``."""
    return DEMO_PREFIX + json.dumps(api_data(), ensure_ascii=False, separators=(",", ":")) + ";"


def main():
    """Из клона репозитория: пересобрать docs/SCENARIOS.md и демо-данные в index.html."""
    pkg = Path(__file__).parent
    doc = pkg.parent.parent / "docs" / "SCENARIOS.md"
    doc.write_text(markdown(), encoding="utf-8")
    page = pkg / "web" / "index.html"
    lines = page.read_text(encoding="utf-8").split("\n")
    i = next(i for i, x in enumerate(lines) if x.startswith(DEMO_PREFIX))
    lines[i] = demo_line()
    page.write_text("\n".join(lines), encoding="utf-8")
    print(f"обновлены {doc} и {page}")


if __name__ == "__main__":
    main()
