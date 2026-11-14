"""«Примерочная» («Примерить на себя»): роль → день с агентом → калькулятор пользы (docs/SCENARIOS.md).

Сценарий — файл ``templates/scenarios/<роль>.toml`` в пакете (встроенные) или ``<config>/scenarios/<роль>.toml``
(свои; одноимённый свой заменяет встроенный). Формат — TOML, а не YAML: ядро пульта — только стандартная библиотека,
``tomllib`` в ней есть, парсера YAML нет.

Схема: кто вы и что болит, модули (id из каталога ``modules.py``), ``[[timeline_steps]]`` — 3–5 моментов дня со
временем и сообщением агента, у момента — ``[[timeline_steps.decisions]]``: кнопки **ровно как в модуле** (варианты
одного его решения или кнопки ``[[demo.telegram]]``) и ``outcome_toast`` — что произошло бы; ``[calculator]`` —
вводные (``inputs``; доли и минуты — редактируемые допущения), ``formulas`` — декларативно: произведение вводных ×
коэффициент, диапазон low–high, без выражений и без eval; ``assumptions_disclaimer``.

Здесь же: проверка схемы с понятными ошибками, ``benefit`` — расчёт (тот же, что ``benefitCalc`` в index.html, тест
сверяет), ``public`` — для панели (без путей). ``python -m gas_pult.scenarios`` (из клона репозитория) пересобирает
docs/SCENARIOS.md и демо-данные панели.
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

ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")      # id роли = имя файла
AT = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
VAR = re.compile(r"^[a-z][a-z0-9_]{0,19}$")
KEYS = {"title", "short", "who", "industries", "modules", "without", "needs", "first_step", "demo",
        "timeline_steps", "calculator"}


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
    """Наборы кнопок модуля: варианты каждого решения и кнопки каждого сообщения [[demo.telegram]]."""
    return [d["options"] for d in m["decisions"]] + [x["buttons"] for x in m["demo"]["telegram"] if x["buttons"]]


def _step(x, where: str, mods: dict, own: list[str]) -> dict:
    if not isinstance(x, dict) or set(x) - {"at", "day", "module", "text", "decisions"}:
        raise ScenarioError(f"{where}: [[timeline_steps]] — поля at, day, module, text, [[timeline_steps.decisions]]")
    at = _str(x, "at", where)
    if not AT.match(at):
        raise ScenarioError(f"{where}: at = \"{at}\" — время ЧЧ:ММ, например \"08:00\"")
    mid = _str(x, "module", where, need=False)
    if mid and mid not in own:
        raise ScenarioError(f"{where}: шаг {at} — модуль «{mid}» не из списка modules этой роли")
    decs = x.get("decisions", [])
    if not isinstance(decs, list) or len(decs) > 4:
        raise ScenarioError(f"{where}: шаг {at} — до 4 кнопок [[timeline_steps.decisions]]")
    out = []
    for d in decs:
        if not isinstance(d, dict) or set(d) - {"label", "outcome_toast"}:
            raise ScenarioError(f"{where}: шаг {at} — у кнопки поля label и outcome_toast")
        out.append({"label": _str(d, "label", where, size=40),
                    "outcome_toast": _str(d, "outcome_toast", where, size=500)})
    labels = [d["label"] for d in out]
    if mid and labels and labels not in _options(mods[mid]):
        raise ScenarioError(f"{where}: шаг {at} — кнопки {labels} не совпадают ни с одним решением модуля «{mid}»; "
                            f"есть: {_options(mods[mid])}")
    if not mid and labels:
        raise ScenarioError(f"{where}: шаг {at} — кнопки-решения только у шага с модулем (module = \"…\")")
    return {"at": at, "day": _str(x, "day", where, need=False, size=60), "module": mid,
            "text": _str(x, "text", where, size=1200), "decisions": out}


def _input(x, where: str) -> dict:
    if not isinstance(x, dict) or set(x) - {"id", "title", "unit", "default", "min", "max", "step", "about",
                                            "assumption"}:
        raise ScenarioError(f"{where}: [[calculator.inputs]] — поля id, title, unit, default, min, max, step, about, "
                            "assumption")
    iid = _str(x, "id", where)
    if not VAR.match(iid):
        raise ScenarioError(f"{where}: inputs id «{iid}» — латиница в нижнем регистре, цифры, «_»")
    lo, hi, d = _num(x, "min", where), _num(x, "max", where), _num(x, "default", where)
    step = _num(x, "step", where, need=False, default=1)
    if not 0 < lo <= d <= hi or step <= 0:
        raise ScenarioError(f"{where}: вводная «{iid}» — нужно 0 < min ≤ default ≤ max и step > 0")
    return {"id": iid, "title": _str(x, "title", where, size=80), "unit": _str(x, "unit", where, need=False, size=30),
            "default": d, "min": lo, "max": hi, "step": step, "about": _str(x, "about", where, size=400),
            "assumption": x.get("assumption", False) is True}


def _formula(x, where: str, ids: set[str]) -> dict:
    """Строка калькулятора: значение = (произведение вводных из ``of``) × коэффициент; low и high — диапазон."""
    if not isinstance(x, dict) or set(x) - {"title", "caption", "unit", "of", "low", "high", "round", "about"}:
        raise ScenarioError(f"{where}: [[calculator.formulas]] — поля title, caption, unit, of, low, high, round, "
                            "about")
    title = _str(x, "title", where, size=80)
    of = x.get("of", [])
    if not isinstance(of, list) or len(of) > 4 or not all(isinstance(k, str) for k in of):
        raise ScenarioError(f"{where}: формула «{title}»: of — список до 4 id вводных")
    if bad := [k for k in of if k not in ids]:
        raise ScenarioError(f"{where}: формула «{title}»: нет таких вводных {bad} — есть {sorted(ids)}")
    lo, hi = _num(x, "low", where), _num(x, "high", where)
    rnd = _num(x, "round", where, need=False, default=1)
    if not 0 <= lo <= hi or rnd <= 0:
        raise ScenarioError(f"{where}: формула «{title}» — нужно 0 ≤ low ≤ high и round > 0")
    return {"title": title, "caption": _str(x, "caption", where, need=False, size=60),
            "unit": _str(x, "unit", where, size=40), "of": list(of), "low": lo, "high": hi, "round": rnd,
            "about": _str(x, "about", where, size=500)}


def _calculator(raw, where: str) -> dict:
    if not isinstance(raw, dict) or set(raw) - {"inputs", "formulas", "assumptions_disclaimer"}:
        raise ScenarioError(f"{where}: [calculator] — assumptions_disclaimer, [[calculator.inputs]], "
                            "[[calculator.formulas]]")
    ins = raw.get("inputs", [])
    if not isinstance(ins, list) or not 1 <= len(ins) <= 6:
        raise ScenarioError(f"{where}: калькулятор — от 1 до 6 [[calculator.inputs]]")
    inputs = [_input(x, where) for x in ins]
    ids = {x["id"] for x in inputs}
    if len(ids) != len(inputs):
        raise ScenarioError(f"{where}: id вводных повторяются")
    fs = raw.get("formulas", [])
    if not isinstance(fs, list) or not 1 <= len(fs) <= 5:
        raise ScenarioError(f"{where}: калькулятор — от 1 до 5 [[calculator.formulas]]")
    disc = _str(raw, "assumptions_disclaimer", where, size=600)
    if "не обещание" not in disc:
        raise ScenarioError(f"{where}: assumptions_disclaimer — со словами «не обещание»: польза — оценка")
    return {"inputs": inputs, "formulas": [_formula(x, where, ids) for x in fs], "assumptions_disclaimer": disc}


def parse(path: Path, mods: dict[str, dict] | None = None) -> dict:
    """Файл сценария → словарь; ошибка — ScenarioError (какой файл, какое поле). ``mods`` — каталог модулей."""
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
    if bad := [i for i in inds if i not in {m["industry"] for m in mods.values()}]:
        raise ScenarioError(f"{where}: industries {bad} — нет такой отрасли в каталоге модулей")
    if bad := [m for m in own if mods[m]["industry"] not in [*inds, "Общие"]]:
        raise ScenarioError(f"{where}: модули {bad} — из другой отрасли, чем industries роли")
    demo = raw.get("demo", {})
    if not isinstance(demo, dict) or set(demo) - {"business", "point"}:
        raise ScenarioError(f"{where}: [demo] — ключи business и point (выдуманные)")
    steps = raw.get("timeline_steps", [])
    if not isinstance(steps, list) or not 3 <= len(steps) <= 5:
        raise ScenarioError(f"{where}: «день с агентом» — от 3 до 5 шагов [[timeline_steps]]")
    ts = [_step(x, where, mods, own) for x in steps]
    plain = [x["at"] for x in ts if not x["day"]]
    if plain != sorted(plain):
        raise ScenarioError(f"{where}: шаги дня — по порядку времени")
    return {
        "id": rid, "title": _str(raw, "title", where, size=60), "short": _str(raw, "short", where, size=160),
        "who": _str(raw, "who", where, size=600), "industries": inds, "modules": own,
        "without": _str(raw, "without", where, size=900), "needs": _strs(raw, "needs", where, 1, 6),
        "first_step": _str(raw, "first_step", where, size=400),
        "demo": {"business": str(demo.get("business", "«Пример»"))[:60], "point": str(demo.get("point", "Центр"))[:40]},
        "timeline_steps": ts, "calculator": _calculator(raw.get("calculator"), where), "path": str(path),
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
    return sorted(found.values(), key=lambda s: (rank.get(s["industries"][0], len(rank)), s["id"]))


def get(rid: str) -> dict:
    s = next((x for x in catalog() if x["id"] == rid), None)
    if not s:
        raise LookupError("нет такой роли — обновите список")
    return s


# ---------- калькулятор: тот же расчёт, что benefitCalc в index.html ----------
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
    """Калькулятор: вводные (нет или мусор — по умолчанию, вне границ — к границе) → строки с диапазоном low–high.
    Только умножение вводных на коэффициенты из toml: ни выражений, ни eval."""
    s = get(role) if isinstance(role, str) else role
    calc, inputs = s["calculator"], inputs or {}
    inp = {x["id"]: min(x["max"], max(x["min"], _value(inputs.get(x["id"]), x["default"]))) for x in calc["inputs"]}
    lines = []
    for f in calc["formulas"]:
        base = 1
        for k in f["of"]:
            base *= inp[k]
        lo, hi = _round(base * f["low"], f["round"]), _round(base * f["high"], f["round"])
        text = (f"≈ {fmt(lo)}" if lo == hi else f"{fmt(lo)}–{fmt(hi)}") + f" {f['unit']}"
        lines.append({"title": f["title"], "caption": f["caption"], "unit": f["unit"], "low": lo, "high": hi,
                      "text": text, "about": f["about"]})
    return {"inputs": inp, "lines": lines, "disclaimer": calc["assumptions_disclaimer"]}


# ---------- для панели ----------
def _fill(text: str, ctx: dict) -> str:
    for k, v in ctx.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def public(s: dict) -> dict:
    """Сценарий для панели: без пути; {{business}}, {{point}}, {{<вводная>}} подставлены (выдуманные из [demo]),
    к шагам — название модуля."""
    out = copy.deepcopy({k: v for k, v in s.items() if k != "path"})
    vals = {**out["demo"], **{x["id"]: fmt(x["default"]) for x in out["calculator"]["inputs"]}}
    for k in ("who", "without", "first_step"):
        out[k] = _fill(out[k], vals)
    out["needs"] = [_fill(x, vals) for x in out["needs"]]
    titles = {m["id"]: m for m in modules.catalog()}
    out["modules"] = [{"id": m, "title": titles[m]["title"]} for m in s["modules"] if m in titles]
    for st in out["timeline_steps"]:
        st["text"] = _fill(st["text"], vals)
        st["module_title"] = titles[st["module"]]["title"] if st["module"] in titles else ""
        for d in st["decisions"]:
            d["outcome_toast"] = _fill(d["outcome_toast"], vals)
    return out


def api_data(errors: list[str] | None = None) -> dict:
    """Ответ ``GET /api/scenarios``: роли для панели (и для её демо — тот же JSON, тест сверяет)."""
    return {"scenarios": [public(s) for s in catalog(errors)]}


# ---------- документация и демо-данные панели ----------
def markdown() -> str:
    """docs/SCENARIOS.md — из toml (тест сверяет: правьте toml и запускайте ``python -m gas_pult.scenarios``)."""
    out = [
        "# «Примерочная»: сценарии «Примерить на себя»", "",
        "<!-- Файл собирается из src/gas_pult/templates/scenarios/*.toml: python -m gas_pult.scenarios -->", "",
        "Путь «понял → примерил → подключил». Человек выбирает свою роль и проходит день с агентом: сообщения со "
        "временем и кнопки-решения ровно как в модулях (нажатие показывает, что произошло бы, — ничего не "
        "выполняется), что было бы без агента и калькулятор пользы с допущениями, которые можно поправить под себя; "
        "в конце — «Подключить»: пространство из модуля. Где в панели: «Примерить на себя» под списком сессий, в "
        "«Новая сессия → Из модуля» и у отрасли в каталоге модулей — «Как это выглядит в работе». Данные — `GET "
        "/api/scenarios` (смотреть может и наблюдатель).", "",
        "**Польза — оценка, не обещание.** Доли и минуты — редактируемые допущения, видны рядом с результатом; "
        "диапазон — ±20 % вокруг допущения. «Оборот» — выручка, не прибыль; деньги по долгам УК — ускорение сбора, а "
        "не дополнительный доход. Все имена, адреса и цифры в сценариях — выдуманный пример.", "",
        "**Без невозможного для агента.** Отзывы публикуются через API только в Google (Business Profile); для Яндекс "
        "Карт и 2ГИС публичного API ответов нет — агент готовит текст, публикуете вы в кабинете. SMS-канала в пульте "
        "нет: сообщения — бот в Telegram или почта, без канала — черновики в `outbox/`. Рассылки — только тем, кто дал "
        "согласие; рекламные — с учётом ст. 18 ФЗ «О рекламе». Погода — только через подключаемый источник прогноза "
        "(нужна интеграция).", "",
        "Сейчас две роли (итерация 1): владелец сети автомоек и директор УК. Остальные отрасли каталога — следующей "
        "итерацией (список ожидаемых — в `tests/test_scenarios.py`).", "",
        "## Как добавить роль", "",
        "Формат — TOML, а не YAML: ядро пульта — только стандартная библиотека, `tomllib` в ней есть.", "",
        "1. Файл `src/gas_pult/templates/scenarios/<роль>.toml` (id роли — имя файла: латиница, цифры, дефис, до 31 "
        "знака) или свой — `~/.config/gas-pult/scenarios/<роль>.toml`.",
        "2. Поля: `title`, `short`, `who` (кто вы и что болит, 2–3 строки), `industries` (отрасли каталога модулей), "
        "`modules` (id из каталога), `without`, `needs`, `first_step`, `[demo]` (выдуманные `business` и `point`).",
        "3. `[[timeline_steps]]` — 3–5 шагов дня: `at` (ЧЧ:ММ), `day` (необязательно), `module`, `text` и "
        "`[[timeline_steps.decisions]]` (`label`, `outcome_toast` — что произошло бы). Подписи кнопок — **ровно** "
        "варианты одного решения модуля (`[[decisions]]` options) или кнопки его `[[demo.telegram]]`: иначе сценарий "
        "не загрузится.",
        "4. `[calculator]`: `assumptions_disclaimer` (со словами «не обещание»); `[[calculator.inputs]]` — `id`, "
        "`title`, `unit`, `default`, `min`, `max`, `step`, `about`, `assumption = true` у долей и минут; "
        "`[[calculator.formulas]]` — `title`, `caption` (например, «оборот, не прибыль»), `unit`, `of` (id вводных), "
        "`low`/`high` (коэффициенты: значение = произведение вводных × коэффициент), `round`, `about`. Без выражений "
        "и eval.",
        "5. Плейсхолдеры в текстах: `{{business}}`, `{{point}}`, `{{<id вводной>}}`.",
        "6. `python -m gas_pult.scenarios` — пересобрать этот файл и демо-данные панели; проверка — "
        "`pytest tests/test_scenarios.py`.",
        "", "## Роли", "",
    ]
    out += [f"- [{s['title']}](#{s['id']}) — {s['short']}" for s in catalog()]
    for s0 in catalog():
        s = public(s0)
        calc = s["calculator"]
        out += ["", f'<a id="{s["id"]}"></a>', "", f"### {s['title']}", "",
                f"Отрасль: {', '.join(s['industries'])} · модули: "
                + ", ".join(f"`{m['id']}` «{m['title']}»" for m in s["modules"]), "",
                "**Кто вы и что болит.** " + s["who"], "", "**День с агентом** (пример):", ""]
        for st in s["timeline_steps"]:
            when = st["at"] + (f", {st['day']}" if st["day"] else "")
            text = st["text"].replace("\n", " ")
            out.append(f"- **{when}**" + (f" · {st['module_title']}" if st["module_title"] else "") + f" — {text}")
            out += [f"  - «{d['label']}» → {d['outcome_toast']}" for d in st["decisions"]]
        out += ["", "**Что было бы без агента.** " + s["without"], "",
                "**Калькулятор** (при значениях по умолчанию):", ""]
        out += [f"- {x['title']}" + (f" ({x['caption']})" if x["caption"] else "") + f": {x['text']}. {x['about']}"
                for x in benefit(s)["lines"]]
        out += ["", "Вводные и допущения по умолчанию:", ""]
        out += [f"- {x['title']} — {fmt(x['default'])} {x['unit']}".rstrip()
                + (" (допущение)" if x["assumption"] else "") + f". {x['about']}" for x in calc["inputs"]]
        out += ["", calc["assumptions_disclaimer"], "", "**Что нужно от клиента:**", ""]
        out += [f"- {x}" for x in s["needs"]]
        out += ["", "**Первый шаг.** " + s["first_step"]]
    return "\n".join(out) + "\n"


DEMO_PREFIX = '  R["/api/scenarios"] = '


def demo_line() -> str:
    """Строка демо-данных в web/js/demo.js (``?demo``): тот же JSON, что отдаёт ``GET /api/scenarios``."""
    return DEMO_PREFIX + json.dumps(api_data(), ensure_ascii=False, separators=(",", ":")) + ";"


def main():
    """Из клона репозитория: пересобрать docs/SCENARIOS.md и демо-данные панели (web/js/demo.js, #191)."""
    pkg = Path(__file__).parent
    doc = pkg.parent.parent / "docs" / "SCENARIOS.md"
    doc.write_text(markdown(), encoding="utf-8")
    page = pkg / "web" / "js" / "demo.js"
    lines = page.read_text(encoding="utf-8").split("\n")
    i = next(i for i, x in enumerate(lines) if x.startswith(DEMO_PREFIX))
    lines[i] = demo_line()
    page.write_text("\n".join(lines), encoding="utf-8")
    print(f"обновлены {doc} и {page}")


if __name__ == "__main__":
    main()
