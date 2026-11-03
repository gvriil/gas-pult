"""Предложения GASTECH бизнесу: страница ``/offer/<код>`` с живым демо модулей и мастером подключения.

Предложение — файл ``<config>/offers/<код>.toml`` (0600, вне репозитория; пример — ``templates/offers/example.toml``).
Код — ``secrets.token_urlsafe(18)`` (24 знака), неугадываемый; создаёт его только ``gas-pult offer new``. Отзыв —
``gas-pult offer revoke``: файл уходит в ``offers/revoked/``, страница отвечает тем же 404, что и на чужой код.

Здесь же:

- ``load`` — предложение по коду (нет, отозвано, просрочено, битое — одинаково None);
- ``page`` — данные для страницы: только то, что ей нужно (без кода, путей, заметок);
- ``demo`` — выдуманные, «похожие на его» данные: детерминированно из полей предложения (отрасль, точки, суммы);
- ``scenario`` — сценарий демо в Telegram (3–4 сообщения с кнопками) — из ``[[demo.telegram]]`` модуля или по умолчанию;
- ``Misses`` — ограничение перебора кодов по IP; ``Demos`` — демо-сессии страницы в памяти (TTL 30 минут);
- ``TgDemos`` — короткоживущие токены «Попробовать в Telegram» (файл без ПДн — его читает и бот).
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
import re
import secrets
import threading
import time
import tomllib
from datetime import date, datetime, timedelta
from importlib import resources
from pathlib import Path

from gas_pult import modules
from gas_pult.config import config_dir, write_private

CODE = re.compile(r"^[A-Za-z0-9_-]{24,64}$")
TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,40}$")
DEMO_TTL = 30 * 60                  # демо-сессия страницы и загруженные отчёты — 30 минут
TG_TTL = 3600                       # токен «Попробовать в Telegram» — час
TG_STARTS = 10                      # сколько раз можно запустить сценарий по одному токену
MISS_LIMIT = (20, 600)              # неизвестных кодов с одного IP — не больше 20 за 10 минут
UPLOADS = (20, 600)                 # загрузок в одной демо-сессии — не больше 20 за 10 минут
MAX_SESSIONS = 500
COOKIE = "gp_offer"
KEYS = {"business", "industry", "pains", "modules", "expires", "note", "demo", "created"}
DEMO_KEYS = {"points", "point_word", "avg_check", "daily_revenue", "items", "clients", "city"}

INDUSTRIES = {
    "carwash": {"title": "Автомойки и шиномонтаж", "point_word": "филиал", "points": ["Север", "Центр", "Юг"],
                "avg_check": 1400, "daily_revenue": 60000, "clients": 1500,
                "items": ["Мойка кузова", "Комплекс", "Химчистка салона", "Шиномонтаж"]},
    "fitness": {"title": "Фитнес-клубы", "point_word": "клуб", "points": ["Центр", "Север"], "avg_check": 24000,
                "daily_revenue": 150000, "clients": 2400,
                "items": ["Карта 12 месяцев", "Карта 3 месяца", "Персональная тренировка", "Детская секция"]},
    "horeca": {"title": "Поставки для HoReCa", "point_word": "склад", "points": ["Основной склад"],
               "avg_check": 18000, "daily_revenue": 260000, "clients": 140,
               "items": ["Овощи и зелень", "Молочная продукция", "Мясо и птица", "Бакалея"]},
    "uk": {"title": "Управляющие компании", "point_word": "дом", "points": ["Примерная, 1", "Примерная, 3",
                                                                        "Тестовая, 12"],
           "avg_check": 3200, "daily_revenue": 90000, "clients": 900,
           "items": ["Протечка", "Не работает лифт", "Уборка подъезда", "Перерасчёт"]},
    "sellers": {"title": "Селлеры WB и Ozon", "point_word": "площадка", "points": ["Wildberries", "Ozon"],
                "avg_check": 1300, "daily_revenue": 180000, "clients": 5000,
                "items": ["Органайзер (демо)", "Термокружка (демо)", "Чехол (демо)", "Лампа (демо)"]},
    "services": {"title": "Услуги", "point_word": "точка", "points": ["Центр", "Север"], "avg_check": 2500,
                 "daily_revenue": 50000, "clients": 800, "items": ["Услуга А", "Услуга Б", "Услуга В"]},
}
INDUSTRIES["generic"] = INDUSTRIES["services"]

# Как модуль показываем в демо, если в его module.toml нет [demo] kind: сводка цифр, напоминание или заявка.
KIND_BY_ID = [("summary", r"morning|numbers|kpi|stock|prices|night"),
              ("reminder", r"return|lapsed|renewal|receivab|kids|tax|alert|harvest|reorder|debt|reminder"),
              ("request", r"request|emergency|order|lead|primary|deadline|draft|review|inspection")]


class OfferError(ValueError):
    """Ошибка в файле предложения — текст для владельца (CLI)."""


def offers_dir() -> Path:
    return config_dir() / "offers"


def new_code() -> str:
    """24 знака из [A-Za-z0-9_-] (144 бита случайности); не с «-» — чтобы код не путался с ключом командной строки."""
    while (code := secrets.token_urlsafe(18)).startswith("-"):
        pass
    return code


def hint(code: str) -> str:
    """Код в сообщениях владельцу — не целиком: первые 4 знака."""
    return code[:4] + "…"


# ---------- файл предложения ----------
def _list_str(v, where: str, lo: int, hi: int, size: int = 200) -> list[str]:
    if not isinstance(v, list) or not lo <= len(v) <= hi or not all(isinstance(x, str) and x.strip() for x in v):
        raise OfferError(f"{where} — список из {lo}–{hi} строк")
    if any(len(x) > size for x in v):
        raise OfferError(f"{where} — строки не длиннее {size} знаков")
    return [x.strip() for x in v]


def parse(raw: dict, check_modules: bool = True) -> dict:
    """Словарь из toml → проверенное предложение. Ошибка — OfferError с понятным текстом."""
    unknown = set(raw) - KEYS
    if unknown:
        raise OfferError("неизвестные ключи: " + ", ".join(sorted(unknown)))
    business = raw.get("business")
    if not isinstance(business, str) or not business.strip() or len(business) > 80:
        raise OfferError("business — имя бизнеса, строка до 80 знаков")
    industry = raw.get("industry", "generic")
    if industry not in INDUSTRIES:
        raise OfferError("industry — одно из: " + ", ".join(INDUSTRIES))
    pains = _list_str(raw.get("pains", []), "pains (что болит)", 1, 6)
    mods = _list_str(raw.get("modules", []), "modules (id модулей)", 1, 3, 41)
    if check_modules:
        known = {m["id"] for m in modules.catalog()}
        if bad := [m for m in mods if m not in known]:
            raise OfferError("нет таких модулей: " + ", ".join(bad) + " — список: панель → «Из модуля» или /modules")
    expires = raw.get("expires", "")
    if isinstance(expires, date):
        expires = expires.isoformat()
    if expires and (not isinstance(expires, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", expires)):
        raise OfferError("expires — дата ГГГГ-ММ-ДД (последний день, когда ссылка работает)")
    d = raw.get("demo", {})
    if not isinstance(d, dict) or set(d) - DEMO_KEYS:
        raise OfferError("[demo] — ключи: " + ", ".join(sorted(DEMO_KEYS)))
    base = INDUSTRIES[industry]
    demo = {"points": _list_str(d.get("points", base["points"]), "demo.points", 1, 8, 40),
            "point_word": str(d.get("point_word", base["point_word"]))[:20],
            "items": _list_str(d.get("items", base["items"]), "demo.items", 1, 8, 60),
            "city": str(d.get("city", ""))[:40]}
    for k in ("avg_check", "daily_revenue", "clients"):
        v = d.get(k, base[k])
        if not isinstance(v, int) or isinstance(v, bool) or not 0 < v < 10 ** 9:
            raise OfferError(f"demo.{k} — целое число больше нуля")
        demo[k] = v
    return {"business": business.strip(), "industry": industry, "pains": pains, "modules": mods,
            "expires": expires or "", "demo": demo}


def path_of(code: str) -> Path | None:
    return offers_dir() / f"{code}.toml" if CODE.match(code or "") else None


def load(code: str, today: date | None = None) -> dict | None:
    """Действующее предложение по коду; нет, отозвано, просрочено или файл битый — None (одинаково)."""
    p = path_of(code)
    if not p or not p.is_file():
        return None
    try:
        o = parse(tomllib.loads(p.read_text(encoding="utf-8")), check_modules=False)
    except (OSError, tomllib.TOMLDecodeError, OfferError, UnicodeDecodeError):
        return None
    if o["expires"] and (today or date.today()).isoformat() > o["expires"]:
        return None
    return {**o, "code": code}


def example_text() -> str:
    return resources.files("gas_pult").joinpath("templates/offers/example.toml").read_text(encoding="utf-8")


def create(text: str, name: str = "", expires: str = "") -> tuple[str, Path]:
    """Новое предложение из текста toml (шаблона): проверка → новый код → ``offers/<код>.toml`` (0600)."""
    if name:
        line = "business = " + json.dumps(name.strip(), ensure_ascii=False)
        text, n = re.subn(r"(?m)^business\s*=.*$", lambda _: line, text, count=1)
        if not n:
            text = line + "\n" + text
    if expires:
        text = re.sub(r"(?m)^expires\s*=.*\n?", "", text)
        text = f'expires = "{expires}"\n' + text
    try:
        parse(tomllib.loads(text))
    except tomllib.TOMLDecodeError as e:
        raise OfferError(f"ошибка в toml: {e}") from None
    code = new_code()
    p = offers_dir() / f"{code}.toml"
    offers_dir().mkdir(parents=True, exist_ok=True, mode=0o700)
    write_private(p, f"# Предложение GASTECH · создано {time.strftime('%Y-%m-%d %H:%M')} · gas-pult offer\n" + text)
    return code, p


def listing() -> list[dict]:
    out = []
    for p in sorted(offers_dir().glob("*.toml")) if offers_dir().is_dir() else []:
        code = p.stem
        try:
            o = parse(tomllib.loads(p.read_text(encoding="utf-8")), check_modules=False)
            state = "просрочено" if o["expires"] and date.today().isoformat() > o["expires"] else "действует"
            out.append({"code": code, "business": o["business"], "expires": o["expires"], "state": state,
                        "modules": o["modules"]})
        except (OSError, tomllib.TOMLDecodeError, OfferError, UnicodeDecodeError) as e:
            out.append({"code": code, "business": "?", "expires": "", "state": f"ошибка: {e}", "modules": []})
    return out


def revoke(code: str) -> Path:
    p = path_of(code)
    if not p or not p.is_file():
        raise OfferError("нет такого предложения")
    d = offers_dir() / "revoked"
    d.mkdir(exist_ok=True, mode=0o700)
    dst = d / p.name
    p.replace(dst)
    return dst


# ---------- выдуманные данные ----------
def _rng(o: dict, salt: str = "") -> random.Random:
    seed = hashlib.sha256((o["business"] + "|" + o["industry"] + "|" + salt).encode()).hexdigest()
    return random.Random(int(seed[:16], 16))


def _money(v: float) -> str:
    return f"{round(v):,}".replace(",", " ") + " ₽"


def kind_of(m: dict) -> str:
    k = (m.get("demo") or {}).get("kind")
    if k:
        return k
    return next((kind for kind, pat in KIND_BY_ID if re.search(pat, m["id"])), "summary")


NAMES = ["Анна", "Ирина", "Олег", "Мария", "Сергей", "Дмитрий", "Елена", "Павел"]


def what_next(option: str, ctx: dict) -> str:
    """Что произошло бы по кнопке — словами, без действий."""
    o = option.lower().strip()
    n, point = ctx.get("n", 0), ctx.get("point", "")
    if re.search(r"отправ|пачк", ctx.get("q", "").lower()) and o in ("да", "нет"):
        o = "отправить" if o == "да" else "не отправлять"
    if o == "нет":
        return "Агент ничего не сделает и запишет ответ в историю."
    if re.search(r"позже|не сейчас|ничего|не отправ|отложить", o):
        return "Агент ничего не отправит и напомнит завтра в то же время."
    if re.search(r"в порядке|отметить|уже", o):
        return "Агент запишет решение в историю и не будет беспокоить по этому пункту."
    if re.search(r"отправ|напомн|всем|пачк|рассыл", o):
        return (f"В рабочем режиме сообщения ушли бы {n} клиентам — только тем, кто дал согласие, через ваш канал. "
                "Сейчас ничего не отправлено." if n else
                "В рабочем режиме агент отправил бы сообщение через ваш канал. Сейчас ничего не отправлено.")
    if re.search(r"подробн|разобрать|показать|список", o):
        return (f"Агент прислал бы разбор: что изменилось{(' в «' + point + '»') if point else ''}, почему, и 2–3 "
                "варианта действий с цифрами — без внешних действий.")
    if re.search(r"измен|правк|другое", o):
        return "Агент попросил бы уточнить, что поменять, и прислал бы новый черновик на «Да»."
    if re.search(r"стоп|претенз", o):
        return "Агент подготовил бы документ по шаблону и показал вам. Отправляете вы — после «Да»."
    return f"Агент выполнил бы «{option}» в рабочем пространстве и прислал результат сюда — до любых внешних действий."


def _template(m: dict, values: dict) -> str:
    """Пример сообщения клиенту — из первого шаблона модуля (templates/*.md); нет — общий текст."""
    folder = Path(m.get("path", "")) / "templates"
    files = sorted(folder.glob("*.md")) if folder.is_dir() else []
    pref = [f for f in files if re.search(r"return|soft|overdue|remind|general", f.name)] or files
    text = ""
    if pref:
        try:
            text = pref[0].read_text(encoding="utf-8")
        except OSError:
            text = ""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)                  # переносы строк внутри абзаца — пробелом
    if not text:
        text = "{имя}, добрый день! Давно не видели вас в «{филиал}». Будем рады снова — ответьте на это сообщение."
    text = re.sub(r"\{([^{}\n]{1,30})\}", lambda x: str(values.get(x.group(1), "…")), text)
    return text[:700]


def demo_module(o: dict, m: dict) -> dict:
    """Демо одного модуля на выдуманных данных: карточка (сводка / напоминание / заявка) и вопрос агента."""
    r, d = _rng(o, m["id"]), o["demo"]
    kind = kind_of(m)
    point = d["points"][r.randrange(len(d["points"]))]
    day = (date.today() - timedelta(days=1)).strftime("%d.%m")
    out: dict = {"kind": kind}
    if kind == "summary":
        rows, worst = [], None
        for p in d["points"]:
            plan = d["daily_revenue"] * r.uniform(0.8, 1.2)
            fact = plan * r.uniform(0.82, 1.12)
            checks = max(1, round(fact / (d["avg_check"] * r.uniform(0.9, 1.1))))
            dev = 100 * (fact - plan) / plan
            rows.append({"point": p, "fact": _money(fact), "plan": _money(plan), "checks": checks,
                         "avg": _money(fact / checks), "dev": f"{'+' if dev >= 0 else '−'}{abs(dev):.0f} %",
                         "bad": dev < -5})
            if worst is None or dev < worst[1]:
                worst = (p, dev)
        out["summary"] = {"title": f"Утренние цифры за {day}", "point_word": d["point_word"], "rows": rows,
                          "top": f"Главное отклонение: {d['point_word']} «{worst[0]}» — {worst[1]:+.0f} % к плану"
                          .replace("-", "−")}
        point = worst[0]
    elif kind == "reminder":
        n = max(3, round(d["clients"] * r.uniform(0.02, 0.05)))
        name = NAMES[r.randrange(len(NAMES))]
        vals = {"имя": name, "филиал": point, "клуб": point, "сумма": f"{round(d['avg_check'] * 3):,}"
                .replace(",", " "), "документ": "УПД № 101 (демо)", "дата_документа": day,
                "сегодня": date.today().strftime("%d.%m"), "дата": day, "карта_по": "31.03", "дней": 30}
        out["reminder"] = {"to": f"{name} (демо)", "text": _template(m, vals), "n": n,
                           "ask": f"Отправить пачку из {n}?"}
        out["n"] = n
    elif "review" in m["id"]:
        item = d["items"][r.randrange(len(d["items"]))]
        out["request"] = {"title": "Новый отзыв", "text": f"★★★☆☆ «{item} — хорошо, но ждали в очереди 20 минут» · "
                          f"{d['point_word']} «{point}»", "who": f"{NAMES[r.randrange(len(NAMES))]} (демо)",
                          "via": "карты"}
    else:
        item = d["items"][r.randrange(len(d["items"]))]
        out["request"] = {"title": "Новая заявка", "text": f"{item} · {d['point_word']} «{point}» · завтра "
                          f"{r.choice(['10:30', '12:00', '15:30', '18:00'])}",
                          "who": f"{NAMES[r.randrange(len(NAMES))]} (демо)", "via": r.choice(["сайт", "Telegram",
                                                                                              "телефон"])}
    dec = (m.get("decisions") or [{}])[0]
    if dec.get("question"):
        q = re.sub(r"<[^<>]{1,30}>", lambda x: point if "дом" in x.group() or "филиал" in x.group() else "…",
                   dec["question"])
        q = re.sub(r"\s*\([^()]*\)\s*$", "", q)                      # пояснение для агента в скобках — не клиенту
        n = out.get("n") or max(3, round(d["clients"] * 0.03))
        q = re.sub(r"\b[NM]\b", str(n), q)
        ctx = {"n": n if kind == "reminder" or re.search(r"пачк", q) else 0, "point": point, "q": q}
        out["question"] = {"text": q, "options": [{"label": x, "next": what_next(x, ctx)} for x in dec["options"]]}
    return out


def page(o: dict) -> dict:
    """Всё, что нужно странице предложения: без кода, путей, заметок и служебных полей."""
    from gas_pult import country, offer_report, terms

    cat = {m["id"]: m for m in modules.catalog()}
    mods = []
    for mid in o["modules"]:
        m = cat.get(mid)
        if not m:
            continue
        mods.append({"id": m["id"], "title": m["title"], "about": m["about"], "industry": m["industry"],
                     "decisions": [{"question": x["question"], "options": x["options"]} for x in m["decisions"]],
                     "demo": demo_module(o, m)})
    return {"business": o["business"], "industry": INDUSTRIES[o["industry"]]["title"], "pains": o["pains"],
            "expires": o["expires"], "modules": mods, "scenario": role_for(o),
            "terms": {"version": terms.VERSION, "title": terms.TITLE, "points": list(terms.POINTS), "url": terms.URL},
            "countries": [{"code": c, "name": country.name(c)} for c in country.COMMON],
            "upload": {"max_mb": offer_report.MAX_BYTES >> 20, "max_rows": offer_report.MAX_ROWS,
                       "ttl_min": DEMO_TTL // 60, "kinds": offer_report.KINDS}}


# ---------- сценарий отрасли и калькулятор пользы (как в «Примерочной», scenarios.py) ----------
# Вводные калькулятора из [demo] предложения: число точек — сколько их в предложении, средний чек и клиенты — как есть.
FROM_DEMO = {"points": lambda d: len(d["points"]), "avg_check": lambda d: d["avg_check"],
             "clients": lambda d: d["clients"]}


def role_for(o: dict) -> dict | None:
    """Роль «Примерочной» для страницы предложения: та, где больше всего модулей предложения (нет общих — None).
    Значения калькулятора по умолчанию — из [demo] (в границах ползунка), имя и первая точка — из предложения.
    Только данные и расчёт по формулам из toml — без модели."""
    from gas_pult import scenarios

    best = None
    for s in scenarios.catalog():
        n = len(set(s["modules"]) & set(o["modules"]))
        if n and (best is None or n > best[0]):
            best = (n, s)
    if not best:
        return None
    s = copy.deepcopy(best[1])
    for x in s["calculator"]["inputs"]:
        if x["id"] in FROM_DEMO:
            x["default"] = min(x["max"], max(x["min"], FROM_DEMO[x["id"]](o["demo"])))
    s["demo"] = {**s["demo"], "business": o["business"], "point": o["demo"]["points"][0]}
    out = scenarios.public(s)
    return {k: out[k] for k in ("id", "title", "short", "who", "without", "modules", "timeline_steps", "calculator",
                                "needs", "first_step") if k in out}


# ---------- сценарий демо в Telegram ----------
def _fill(text: str, ctx: dict) -> str:
    for k, v in ctx.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def scenario(o: dict, m: dict) -> list[dict]:
    """3–4 сообщения: [{text, buttons: [(подпись, что произошло бы)]}]. Из ``[[demo.telegram]]`` модуля — с
    подстановкой {{business}}, {{industry}}, {{point}}, {{n}}; секции нет — заявка → напоминание → цифры → вопрос."""
    full = {**m, "id": m["id"].replace("review", "rv")}                # в сценарии — заявка, а не отзыв
    parts = {k: demo_module(o, {**full, "demo": {"kind": k}}) for k in ("request", "reminder", "summary")}
    n = parts["reminder"].get("n", 0)
    s = parts["summary"]["summary"]
    ctx = {"business": o["business"], "industry": INDUSTRIES[o["industry"]]["title"],
           "point": o["demo"]["points"][0], "n": n}
    own = (m.get("demo") or {}).get("telegram") or []
    if own:
        return [{"text": _fill(x["text"], ctx),
                 "buttons": [(_fill(b, ctx)[:40], _fill(a, ctx)) for b, a in zip(x["buttons"], x["replies"],
                                                                                 strict=False)]}
                for x in own]
    rq, rm = parts["request"]["request"], parts["reminder"]["reminder"]
    steps = [
        {"text": f"📥 {rq['title']} (демо) · {o['business']}\n\n{rq['text']}\nКлиент: {rq['who']} · через {rq['via']}",
         "buttons": [("Принять", "В рабочем режиме агент подтвердил бы запись клиенту и поставил её в расписание. "
                                 "Сейчас ничего не отправлено."),
                     ("Предложить другое время", "Агент предложил бы клиенту два свободных окна и дождался ответа.")]},
        {"text": f"💬 Напоминание клиенту (демо)\n\n{rm['text']}\n\n{rm['ask']}",
         "buttons": [("Отправить", what_next("Отправить", {"n": n})),
                     ("Показать список", f"Агент показал бы {n} клиентов: имя, последний визит, точка — в отчётах "
                                         "имена маскируются."),
                     ("Не сейчас", what_next("Не сейчас", {}))]},
        {"text": f"📊 {s['title']} (демо)\n\n" + "\n".join(
            f"• {x['point']}: {x['fact']} (план {x['plan']}, {x['dev']}), средний чек {x['avg']}" for x in s["rows"])
            + f"\n\n{s['top']}", "buttons": []},
    ]
    q = demo_module(o, m).get("question")
    if q:
        steps.append({"text": f"❓ Вопрос агента (демо)\n\n{q['text']}",
                      "buttons": [(x["label"][:40], x["next"]) for x in q["options"]]})
    return steps


# ---------- защита и состояние ----------
class Misses:
    """Неизвестные коды с одного IP: больше ``MISS_LIMIT`` за окно — IP получает 429 на любые коды до конца окна."""

    def __init__(self, limit: tuple[int, int] = MISS_LIMIT):
        self.limit, self.seen, self.lock = limit, {}, threading.Lock()

    def blocked(self, ip: str) -> bool:
        now = time.time()
        with self.lock:
            hits = [t for t in self.seen.get(ip, []) if now - t < self.limit[1]]
            self.seen[ip] = hits
            if not hits:
                self.seen.pop(ip, None)
            return len(hits) >= self.limit[0]

    def miss(self, ip: str):
        with self.lock:
            self.seen.setdefault(ip, []).append(time.time())
            if len(self.seen) > 5000:                     # память не растёт без конца
                self.seen = dict(list(self.seen.items())[-2500:])


class Demos:
    """Демо-сессии страницы предложения — только в памяти процесса панели. Ключ — SHA-256 от значения cookie.
    В сессии: шаги мастера (без ПДн) и отчёты по загрузкам (агрегаты и маскированные строки) до ``exp``."""

    def __init__(self, ttl: int = DEMO_TTL):
        self.ttl, self.items, self.lock = ttl, {}, threading.Lock()

    @staticmethod
    def _h(sid: str) -> str:
        return hashlib.sha256((sid or "").encode()).hexdigest()

    def sweep(self):
        now = time.time()
        with self.lock:
            for k in [k for k, v in self.items.items() if v["exp"] < now]:
                del self.items[k]
            for v in self.items.values():
                v["reports"] = {k: r for k, r in v["reports"].items() if r["exp"] >= now}

    def get(self, sid: str, code: str) -> dict | None:
        self.sweep()
        s = self.items.get(self._h(sid))
        return s if s and s["code"] == code else None

    def new(self, code: str) -> str:
        self.sweep()
        sid = secrets.token_urlsafe(24)
        with self.lock:
            if len(self.items) >= MAX_SESSIONS:                # самые старые — первыми
                for k in sorted(self.items, key=lambda k: self.items[k]["exp"])[: MAX_SESSIONS // 10]:
                    del self.items[k]
            self.items[self._h(sid)] = {"code": code, "exp": time.time() + self.ttl, "reports": {}, "wizard": {},
                                        "uploads": []}
        return sid

    def touch(self, s: dict):
        s["exp"] = time.time() + self.ttl

    def upload_ok(self, s: dict) -> bool:
        now = time.time()
        s["uploads"] = [t for t in s["uploads"] if now - t < UPLOADS[1]]
        if len(s["uploads"]) >= UPLOADS[0]:
            return False
        s["uploads"].append(now)
        return True

    def put_report(self, s: dict, rep: dict) -> dict:
        now = time.time()
        rep = {**rep, "at": int(now), "exp": int(now + self.ttl)}
        s["reports"][rep["kind"]] = rep
        self.touch(s)
        return rep

    def drop(self, sid: str):
        with self.lock:
            self.items.pop(self._h(sid), None)


class TgDemos:
    """Токены «Попробовать в Telegram»: токен → предложение, модуль, срок, сколько раз запускали. Файл 0600
    ``<data>/offer_tg.json`` — его пишет панель и читает бот. Людей здесь нет: ни ID, ни имён."""

    def __init__(self, store: Path):
        self.store, self.lock = store, threading.Lock()

    def _load(self) -> dict:
        try:
            d = json.loads(self.store.read_text())
        except (OSError, ValueError):
            return {}
        now = time.time()
        return {k: v for k, v in d.items() if isinstance(v, dict) and v.get("exp", 0) > now}

    def _save(self, d: dict):
        write_private(self.store, json.dumps(d))

    def issue(self, code: str, module: str, back: str = "") -> str:
        tok = secrets.token_urlsafe(18)
        with self.lock:
            d = self._load()
            if len(d) >= 200:
                raise ValueError("слишком много демо сразу — попробуйте через несколько минут")
            d[tok] = {"code": code, "module": module, "exp": time.time() + TG_TTL, "starts": 0, "back": back[:200]}
            self._save(d)
        return tok

    def get(self, tok: str) -> dict | None:
        if not TOKEN.match(tok or ""):
            return None
        return self._load().get(tok)

    def start(self, tok: str) -> dict | None:
        """Запуск сценария: не больше ``TG_STARTS`` раз на токен; иначе None («демо закончилось»)."""
        if not TOKEN.match(tok or ""):
            return None
        with self.lock:
            d = self._load()
            rec = d.get(tok)
            if not rec or rec["starts"] >= TG_STARTS:
                return None
            rec["starts"] += 1
            self._save(d)
        return rec


def expires_text(o: dict) -> str:
    if not o.get("expires"):
        return ""
    return datetime.strptime(o["expires"], "%Y-%m-%d").strftime("%d.%m.%Y")
