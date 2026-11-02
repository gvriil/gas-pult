"""Дежурный помощник: пилюля «? Подсказать» на каждом экране панели и на странице предложения (docs/HELPER.md).

Итерация 1 — без модели (0 ₽). Знания — карта экранов ``help/screens.toml`` (экран → назначение, шаги, частые
вопросы, куда дальше): подсказки-чипы отвечают прямо из карты, свободный вопрос — простым ранжированием слов по карте
(и, сотрудникам, по docs/MODULES.md, OFFERS.md, ONBOARDING-BUSINESS.md). Ответ — коротко и обязательно с действиями
«Перейти: …»: только id из карты (``[[action]]``), сервер сверяет каждый с картой и ролью; в панели их открывает
``go(id)``. Умные ответы модели, «❓ Помощь» в боте и сводка «где путаются» — следующие итерации.

Контекст экрана от клиента — недоверенный: принимаются только id экрана из карты, шаг, id модуля из каталога или
предложения (``sanitize``); роль — с сервера. Гость предложения видит только экраны своей страницы и мастера.
Журнал вопросов ``<data>/help-log.jsonl`` (0600) — без ПДн: телефоны, почта, ИНН, ОГРН, номера карт, СНИЛС
маскируются (``mask``); свободный текст гостя не пишется — только экран и короткий хеш вопроса; нет Telegram ID, IP,
кода предложения и cookie; хранится 90 дней.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import threading
import time
import tomllib
from collections import Counter
from datetime import datetime, timedelta
from importlib import resources
from pathlib import Path

from gas_pult import country
from gas_pult.config import write_private

ROLES = ("owner", "member", "viewer", "guest", "anon")
STAFF = ("owner", "member", "viewer")
WHERE = ("panel", "offer")
WHAT, WHAT_Q = "what", "Что здесь делать?"
WHAT_Q_EN = "What can I do here?"
SIMPLE = "simple."              # экраны простого режима: тексты и на английском (поля *_en) — обязательно
LANGS = ("ru", "en")
ACTION = re.compile(r"^go:[a-z0-9][a-z0-9.\-]{0,40}$")
SCREEN = re.compile(r"^[a-z][a-z0-9.\-]{0,40}$")
STEP = re.compile(r"^[a-z0-9\-]{0,24}$")

MAX_Q = 500                      # вопрос — до 500 знаков (дальше режем)
MAX_TEXT = 700                   # ответ — до 700 знаков
MAX_ACTIONS = 3
KEEP_DAYS = 90                   # журнал вопросов — 90 дней

STOP = frozenset(re.split(r"\s+", """как что где это для или при чем чего если надо нужно можно мне меня мой моя
мои есть был быть там тут здесь так такой какой какая какие почему зачем когда кто его она они вас вам ваш наш нас все
всё уже еще ещё тоже только просто очень the and for how what"""))


class MapError(ValueError):
    """Карта экранов сломана: текст — что и где поправить."""


# ---------- карта экранов ----------
def _list(v, where: str, item=str) -> list:
    if not isinstance(v, list) or not all(isinstance(x, item) for x in v):
        raise MapError(f"{where}: ожидался список")
    return v


def parse_map(raw: dict) -> dict:
    """Словарь из TOML → проверенная карта: действия, общие вопросы, экраны. Ссылки — только на существующее."""
    actions: dict[str, dict] = {}
    for a in _list(raw.get("action", []), "[[action]]", dict):
        aid = a.get("id", "")
        if not ACTION.match(aid) or aid in actions:
            raise MapError(f"[[action]] {aid!r}: id вида go:экран, без повторов")
        roles = _list(a.get("roles", []), f"{aid}.roles")
        if not roles or set(roles) - set(ROLES):
            raise MapError(f"{aid}: roles — из {', '.join(ROLES)}")
        actions[aid] = {"id": aid, "title": str(a.get("title") or aid), "roles": roles}
        if a.get("title_en"):
            actions[aid]["title_en"] = str(a["title_en"])

    def faq(x: dict, where: str, need_roles: bool) -> dict:
        fid = str(x.get("id", ""))
        if not re.match(r"^[a-z][a-z0-9\-]{0,20}$", fid) or fid == WHAT:
            raise MapError(f"{where}: faq id — латиница и дефис, не «{WHAT}»")
        if not str(x.get("q", "")).strip() or not str(x.get("a", "")).strip():
            raise MapError(f"{where} {fid}: нужны q и a")
        acts = _list(x.get("actions", []), f"{where} {fid}.actions")
        if bad := [a for a in acts if a not in actions]:
            raise MapError(f"{where} {fid}: нет таких действий: {', '.join(bad)}")
        roles = _list(x.get("roles", []), f"{where} {fid}.roles")
        if need_roles and (not roles or set(roles) - set(ROLES)):
            raise MapError(f"{where} {fid}: roles — из {', '.join(ROLES)}")
        out = {"id": fid, "q": x["q"].strip(), "a": x["a"].strip(), "actions": acts, "roles": roles}
        if x.get("q_en") or x.get("a_en"):
            out |= {"q_en": str(x.get("q_en", "")).strip(), "a_en": str(x.get("a_en", "")).strip()}
        return out

    common = [faq(x, "[[faq]]", True) for x in _list(raw.get("faq", []), "[[faq]]", dict)]
    screens: dict[str, dict] = {}
    for s in _list(raw.get("screen", []), "[[screen]]", dict):
        sid = s.get("id", "")
        if not SCREEN.match(sid) or sid in screens:
            raise MapError(f"[[screen]] {sid!r}: id — латиница, точка, дефис, без повторов")
        if s.get("where") not in WHERE:
            raise MapError(f"{sid}: where — одно из {', '.join(WHERE)}")
        roles = _list(s.get("roles", []), f"{sid}.roles")
        if not roles or set(roles) - set(ROLES):
            raise MapError(f"{sid}: roles — из {', '.join(ROLES)}")
        if ("guest" in roles) != (s["where"] == "offer") or ("guest" in roles and len(roles) > 1):
            raise MapError(f"{sid}: гость — только на экранах страницы предложения, и только он")
        for k in ("title", "purpose"):
            if not str(s.get(k, "")).strip():
                raise MapError(f"{sid}: нужно поле {k}")
        local = [faq(x, sid, False) for x in _list(s.get("faq", []), f"{sid}.faq", dict)]
        nxt = _list(s.get("next", []), f"{sid}.next")
        if bad := [a for a in nxt if a not in actions]:
            raise MapError(f"{sid}: next — нет таких действий: {', '.join(bad)}")
        for a in nxt + [x for f in local for x in f["actions"]]:
            if not set(actions[a]["roles"]) & set(roles):
                raise MapError(f"{sid}: действие {a} недоступно ни одной роли экрана")
        chips = _list(s.get("chips", []), f"{sid}.chips")
        known = {f["id"] for f in local} | {f["id"] for f in common if set(f["roles"]) & set(roles)}
        if bad := [c for c in chips if c not in known]:
            raise MapError(f"{sid}: chips — нет таких вопросов: {', '.join(bad)}")
        screens[sid] = {"id": sid, "where": s["where"], "title": s["title"].strip(), "roles": roles,
                        "purpose": s["purpose"].strip(), "steps": _list(s.get("steps", []), f"{sid}.steps"),
                        "next": nxt, "chips": chips, "faq": local}
        if sid.startswith(SIMPLE) or "title_en" in s:   # простой режим и первый экран: всё и на английском
            for k in ("title_en", "purpose_en"):
                if not str(s.get(k, "")).strip():
                    raise MapError(f"{sid}: экрану простого режима нужно поле {k}")
            steps_en = _list(s.get("steps_en", []), f"{sid}.steps_en")
            if len(steps_en) != len(screens[sid]["steps"]):
                raise MapError(f"{sid}: steps_en — столько же шагов, сколько steps")
            if bad := [f["id"] for f in local if not f.get("q_en") or not f.get("a_en")]:
                raise MapError(f"{sid}: вопросам простого режима нужны q_en и a_en: {', '.join(bad)}")
            if bad := [c for c in chips if c not in {f["id"] for f in local}]:
                raise MapError(f"{sid}: чипы простого режима — только свои вопросы экрана: {', '.join(bad)}")
            if bad := [a for a in nxt + [x for f in local for x in f["actions"]] if not actions[a].get("title_en")]:
                raise MapError(f"{sid}: переходам простого режима нужен title_en: {', '.join(bad)}")
            screens[sid] |= {"title_en": s["title_en"].strip(), "purpose_en": s["purpose_en"].strip(),
                             "steps_en": steps_en}
    return {"version": raw.get("version", 1), "actions": actions, "faq": common, "screens": screens}


@functools.cache
def the_map() -> dict:
    text = resources.files("gas_pult").joinpath("help/screens.toml").read_text(encoding="utf-8")
    return parse_map(tomllib.loads(text))


def screens_for(role: str, m: dict | None = None) -> dict[str, dict]:
    m = m or the_map()
    return {k: s for k, s in m["screens"].items() if role in s["roles"]}


def action_ok(aid: str, role: str, m: dict | None = None) -> bool:
    a = (m or the_map())["actions"].get(aid)
    return bool(a) and role in a["roles"]


def default_screen(role: str) -> str:
    return {"anon": "login", "guest": "offer.top"}.get(role, "home.sessions")


def faq_for(sid: str, role: str, m: dict | None = None) -> list[dict]:
    """Вопросы экрана: свои, затем общие для роли (свой с тем же id важнее)."""
    m = m or the_map()
    s = m["screens"][sid]
    own = [f for f in s["faq"] if not f["roles"] or role in f["roles"]]
    ids = {f["id"] for f in own}
    return own + [f for f in m["faq"] if role in f["roles"] and f["id"] not in ids]


def bilingual(sid: str, m: dict | None = None) -> bool:
    """Экран с текстами и на английском (простой режим, первый экран): ответы — только из таких экранов."""
    return "title_en" in (m or the_map())["screens"][sid]


def english(sid: str, lang: str) -> bool:
    """Отвечать ли по-английски: язык en и у экрана есть английские тексты (у экранов полного режима их нет)."""
    return lang == "en" and bilingual(sid)


def chips_for(sid: str, role: str, m: dict | None = None, lang: str = "ru") -> list[dict]:
    m = m or the_map()
    by = {f["id"]: f for f in faq_for(sid, role, m)}
    en = english(sid, lang)
    return [{"id": WHAT, "label": WHAT_Q_EN if en else WHAT_Q}] + [
        {"id": c, "label": by[c]["q_en"] if en else by[c]["q"]} for c in m["screens"][sid]["chips"] if c in by]


def actions_public(ids, role: str, m: dict | None = None, en: bool = False) -> list[dict]:
    """id действий → [{id, title}]: только из карты и для роли, без повторов, не больше MAX_ACTIONS."""
    m = m or the_map()
    out: list[dict] = []
    for a in ids:
        if isinstance(a, str) and action_ok(a, role, m) and all(x["id"] != a for x in out):
            x = m["actions"][a]
            out.append({"id": a, "title": x.get("title_en", x["title"]) if en else x["title"]})
    return out[:MAX_ACTIONS]


def export_json(m: dict | None = None) -> str:
    """Карта для демо панели (``web/help-map.json``): то же содержимое, что TOML, — тест сверяет их."""
    return json.dumps(m or the_map(), ensure_ascii=False, indent=1, sort_keys=True) + "\n"


# ---------- контекст экрана от клиента ----------
def _clip(s, n: int) -> str:
    s = re.sub(r"[\x00-\x1f\x7f<>`{}\[\]]", " ", str(s or ""))
    return re.sub(r"\s+", " ", s).strip()[:n]


def sanitize(ctx, role: str, modules_ok: set[str] | frozenset = frozenset()) -> dict:
    """Только известные поля: экран — id из карты для этой роли (иначе экран по умолчанию), шаг — короткий id,
    модуль — из каталога или предложения. Заголовок и кнопки (что видно на экране) — только сотрудникам, обрезанные."""
    ctx = ctx if isinstance(ctx, dict) else {}
    own = screens_for(role)
    sid = str(ctx.get("screen", ""))
    if sid not in own:
        sid = default_screen(role)
    step = str(ctx.get("step", ""))
    out = {"screen": sid, "step": step if STEP.match(step) else "",
           "module": str(ctx.get("module", "")) if str(ctx.get("module", "")) in modules_ok else ""}
    if role in STAFF:
        out["title"] = _clip(ctx.get("title"), 80)
        btns = ctx.get("buttons") if isinstance(ctx.get("buttons"), list) else []
        out["buttons"] = [b for b in (_clip(x, 40) for x in btns[:12]) if b]
    return out


# ---------- поиск по карте и docs ----------
def words(text: str) -> list[str]:
    ws = re.findall(r"[а-яa-z0-9]+", str(text).lower().replace("ё", "е"))
    return [w[:5] if len(w) > 5 else w for w in ws if len(w) > 2 and w not in STOP]


def rank(question: str, entries: list[dict]) -> list[tuple[float, dict]]:
    """Простое ранжирование: общие основы слов (первые 5 букв) с весом редкости, деленные на длину записи."""
    q = set(words(question))
    if not q:
        return []
    docs = [(e, set(words(e["text"]))) for e in entries]
    n = len(docs) or 1
    df = Counter(w for _, ws in docs for w in ws)
    out = []
    for e, ws in docs:
        hit = q & ws
        if hit:
            score = sum(math.log(1 + n / df[w]) for w in hit) / math.sqrt(1 + len(ws) / 40) * e.get("w", 1.0)
            out.append((score, e))
    return sorted(out, key=lambda x: -x[0])


DOCS = {"MODULES.md": ("owner", "member", "viewer"), "ONBOARDING-BUSINESS.md": ("owner",), "OFFERS.md": ("owner",)}


def docs_dir() -> Path | None:
    d = Path(__file__).resolve().parents[2] / "docs"
    return d if d.is_dir() else None


def clean_doc(text: str) -> str:
    """Отрывок docs для ответа: без блоков кода, команд, путей и ссылок — только текст."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`[^`]*[/~.$][^`]*`", " ", text)            # `путь`, `команда --флаг`, `файл.toml`
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[|*_>#]+|-{3,}", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@functools.cache
def doc_sections(name: str) -> tuple[dict, ...]:
    d = docs_dir()
    try:
        text = (d / name).read_text(encoding="utf-8") if d else ""
    except OSError:
        return ()
    out = []
    for part in re.split(r"(?m)^##\s+", text)[1:]:
        title, _, body = part.partition("\n")
        body = clean_doc(body)
        if body:
            out.append({"title": clean_doc(title), "body": body[:1200], "doc": name})
    return tuple(out)


def docs_for(role: str) -> list[dict]:
    return [s for name, roles in DOCS.items() if role in roles for s in doc_sections(name)]


# ---------- журнал: маскировка ----------
def mask(q: str) -> str:
    """Вопрос сотрудника для журнала — без ПДн: ссылки, почта, коды и ключи, телефоны, ИНН, ОГРН, номера карт, СНИЛС
    (любые номера от 4 цифр, в том числе с пробелами и дефисами); ≤200 знаков. Имена регулярками не ищем — это
    ненадёжно; свободный текст гостя в журнал не пишется вовсе (``qhash``)."""
    q = re.sub(r"\s+", " ", str(q or "")).strip()[:600]
    q = re.sub(r"https?://\S+|\bwww\.\S+", "[ссылка]", q)
    q = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[почта]", q)
    q = re.sub(r"[A-Za-z0-9_\-]{16,}", "[код]", q)            # коды ссылок, токены, ключи
    q = re.sub(r"\+?\d[\d\s().\-]{2,}\d", lambda x: "[номер]" if len(re.sub(r"\D", "", x.group(0))) >= 4
               else x.group(0), q)                          # телефон, ИНН, ОГРН, карта, СНИЛС
    q = re.sub(r"\d{4,}", "[номер]", q)
    return q[:200]


def qhash(q: str) -> str:
    """Кластер вопроса гостя: хеш основ слов (порядок и регистр не важны) — одинаковые вопросы видно, текст — нет."""
    return hashlib.sha256(" ".join(sorted(set(words(q)))).encode()).hexdigest()[:10]


def shorten(text: str, n: int = MAX_TEXT) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= n:
        return text
    cut = text[:n]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[:end + 1] if end > n // 2 else cut.rstrip() + "…").strip()


# ---------- частота вопросов ----------
class Rate:
    """Не больше ``n`` запросов за ``window`` секунд на ключ (в памяти)."""

    def __init__(self, n: int, window: int):
        self.n, self.window, self.hits, self.lock = n, window, {}, threading.Lock()

    def ok(self, key: str, now: float | None = None) -> bool:
        now = now or time.time()
        with self.lock:
            if len(self.hits) > 5000:
                self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] < self.window}
            h = [t for t in self.hits.get(key, []) if now - t < self.window]
            if len(h) >= self.n:
                self.hits[key] = h
                return False
            self.hits[key] = [*h, now]
            return True


# ---------- журнал вопросов ----------
class Log:
    """``<data>/help-log.jsonl`` (0600): «ask» — вопрос (экран, шаг, роль, чип или свободный; сотрудника —
    маскированный текст, гостя — только хеш), предложенные действия; «fb» — 👍/👎, «click» — нажатое действие.
    Без ID, IP, кодов и cookie.
    Записи старше 90 дней удаляются раз в сутки при записи."""

    def __init__(self, path: Path):
        self.path, self.lock, self.purged = path, threading.Lock(), ""

    @staticmethod
    def stamp(now: float | None = None) -> str:
        return datetime.fromtimestamp(now or time.time()).strftime("%Y-%m-%d %H:%M")

    def write(self, rec: dict, now: float | None = None):
        rec = {"t": self.stamp(now), **rec}
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            os.chmod(self.path, 0o600)
            today = rec["t"][:10]
            if self.purged != today:
                self.purged = today
                self.purge(now)

    def purge(self, now: float | None = None):
        cut = (datetime.fromtimestamp(now or time.time()) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d %H:%M")
        keep = [x for x in self.read() if x.get("t", "") >= cut]
        write_private(self.path, "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in keep))

    def read(self) -> list[dict]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                x = json.loads(line)
            except ValueError:
                continue
            if isinstance(x, dict):
                out.append(x)
        return out


class Helper:
    """Помощник одного процесса (панель): ответы из карты, журнал, ограничение частоты."""

    def __init__(self, data: Path):
        self.data = Path(data)
        self.log = Log(self.data / "help-log.jsonl")
        self.rate = Rate(60, 600)                       # вопросов с одного ключа — 60 за 10 минут

    def who_key(self, kind: str, value) -> str:
        """Ключ частоты — HMAC с солью установки: ни ID, ни IP, ни cookie в памяти помощника открыто не лежат."""
        return kind + ":" + hmac.new(country.salt(self.data), f"{kind}:{value}".encode(),
                                     hashlib.sha256).hexdigest()[:20]

    def simple(self, role: str, sid: str, chip: str, question: str, en: bool) -> dict:
        """Экран простого режима (и первый экран): ответы только из вопросов таких же экранов, на языке человека —
        без технических экранов, docs и терминов."""
        m = the_map()
        s = m["screens"][sid]
        sfx = "_en" if en else ""
        if chip == WHAT or (not chip and not question.strip()):
            steps = " ".join(f"{i}) {x}" for i, x in enumerate(s["steps" + sfx], 1))
            return {"text": shorten(f"{s['purpose' + sfx]} {steps}".strip()), "actions": s["next"], "source": "screen"}
        own = [f for f in s["faq"] if not f["roles"] or role in f["roles"]]
        if chip and (f := next((x for x in own if x["id"] == chip), None)):
            return {"text": f["a" + sfx], "actions": f["actions"] or s["next"], "source": "faq"}
        entries = [{"text": f"{f['q' + sfx]} {f['a' + sfx]}", "w": 1.6 if o["id"] == sid else 0.9, "faq": f}
                   for o in screens_for(role, m).values() if bilingual(o["id"], m)
                   for f in o["faq"] if not f["roles"] or role in f["roles"]]
        if hits := rank(question, entries):
            f = hits[0][1]["faq"]
            return {"text": f["a" + sfx], "actions": f["actions"] or s["next"], "source": "faq"}
        none = "No exact answer in the tips. On this screen: " if en else \
            "Точного ответа в подсказках нет. На этом экране: "
        return {"text": shorten(none + s["purpose" + sfx]), "actions": s["next"], "source": "none"}

    def offline(self, role: str, sid: str, chip: str, question: str, extra: dict | None = None,
                lang: str = "ru") -> dict:
        m = the_map()
        s = m["screens"][sid]
        if bilingual(sid, m):
            return self.simple(role, sid, chip, question, english(sid, lang))
        fq = faq_for(sid, role, m)
        if chip == WHAT or (not chip and not question.strip()):
            steps = " ".join(f"{i}) {x}" for i, x in enumerate(s["steps"], 1))
            return {"text": shorten(f"{s['purpose']} {steps}".strip()), "actions": s["next"], "source": "screen"}
        if chip:
            f = next((x for x in fq if x["id"] == chip), None)
            if f:
                return {"text": f["a"], "actions": f["actions"] or s["next"], "source": "faq"}
        entries = [{"kind": "faq", "text": f"{f['q']} {f['a']}", "w": 1.6, "faq": f} for f in fq]
        seen = {f["id"] for f in fq}                   # вопросы с других экранов этой роли — чуть ниже своих
        for other in screens_for(role, m).values():
            if other["id"] == sid or other["where"] != s["where"]:
                continue
            for f in other["faq"]:
                if f["id"] not in seen and (not f["roles"] or role in f["roles"]):
                    entries.append({"kind": "faq", "text": f"{f['q']} {f['a']}", "w": 0.9, "faq": f})
            entries.append({"kind": "screen", "text": f"{other['title']} {other['purpose']}", "w": 0.8,
                            "screen": other})
        entries += [{"kind": "doc", "text": f"{d['title']} {d['body']}", "w": 0.6, "doc": d} for d in docs_for(role)]
        for mod in (extra or {}).get("modules", []):
            entries.append({"kind": "module", "text": f"{mod['title']} {mod.get('about', '')}", "w": 1.0, "mod": mod})
        hits = rank(question, entries)
        if hits:
            e = hits[0][1]
            if e["kind"] == "faq":
                return {"text": e["faq"]["a"], "actions": e["faq"]["actions"] or s["next"], "source": "faq"}
            if e["kind"] == "screen":
                o = e["screen"]
                act = [a for a in m["actions"] if a.removeprefix("go:") == o["id"]] + o["next"]
                return {"text": shorten(f"Это экран «{o['title']}»: {o['purpose']}"), "actions": act,
                        "source": "screen"}
            if e["kind"] == "module":
                mod = e["mod"]
                return {"text": shorten(f"«{mod['title']}» — {mod.get('about', '')}"), "actions": s["next"],
                        "source": "module"}
            d = e["doc"]
            return {"text": shorten(f"{d['title']}: {d['body']}", 420), "actions": s["next"], "source": "doc"}
        return {"text": shorten(f"Точного ответа в подсказках нет. На этом экране: {s['purpose']}"),
                "actions": s["next"], "source": "none"}

    def ask(self, role: str, ctx=None, question: str = "", chip: str = "", who: list[str] | tuple = (),
            extra: dict | None = None, now: float | None = None, lang: str = "ru") -> dict:
        """Ответ помощника: {id, screen, title, text, actions [{id, title}], chips, mode: "offline"}.
        ``extra`` — гостю: модули его предложения ({id, title, about}); сотрудникам — ``module_ids`` каталога.
        ``lang`` — язык человека: на экранах простого режима ответ, чипы и переходы — на нём."""
        lang = lang if lang in LANGS else "ru"
        if role not in ROLES:
            raise ValueError("нет такой роли")
        m = the_map()
        mods = {x["id"] for x in (extra or {}).get("modules", [])} if role == "guest" else (
            frozenset((extra or {}).get("module_ids", ())))
        ctx = sanitize(ctx, role, mods)
        sid = ctx["screen"]
        question = re.sub(r"\s+", " ", str(question or "")).strip()[:MAX_Q]
        chip = str(chip or "")
        if chip and chip not in {c["id"] for c in chips_for(sid, role, m)}:
            chip = ""
        if not self.rate.ok(who[0] if who else f"{role}:anon", now):
            raise ValueError("слишком много вопросов — подождите несколько минут")
        off = self.offline(role, sid, chip, question, extra, lang)
        en = english(sid, lang)
        acts = actions_public(off["actions"], role, m, en) or actions_public(m["screens"][sid]["next"], role, m, en)
        rid = secrets.token_urlsafe(8)
        free = bool(question and not chip)
        self.log.write({"kind": "ask", "id": rid, "screen": sid, "step": ctx["step"], "role": role,
                        "chip": chip or ("free" if question else WHAT),
                        "q": mask(question) if free and role != "guest" else "",
                        "qh": qhash(question) if free else "", "actions": [a["id"] for a in acts]}, now)
        s = m["screens"][sid]
        return {"id": rid, "screen": sid, "title": s["title_en"] if en else s["title"], "text": off["text"],
                "actions": acts, "chips": chips_for(sid, role, m, lang), "mode": "offline"}

    def feedback(self, rid: str, useful=None, action: str = "", role: str = ""):
        if not re.match(r"^[A-Za-z0-9_\-]{6,20}$", str(rid or "")):
            raise ValueError("нет такого ответа")
        if useful is not None:
            self.log.write({"kind": "fb", "id": rid, "useful": bool(useful)})
        if action:
            if not ACTION.match(action) or (role and not action_ok(action, role)):
                raise ValueError("нет такого действия")
            self.log.write({"kind": "click", "id": rid, "action": action})
        return {"ok": True}


if __name__ == "__main__":                      # python -m gas_pult.helper — обновить web/help-map.json после правки
    out = Path(__file__).with_name("web") / "help-map.json"
    out.write_text(export_json(), encoding="utf-8")
    print(f"карта: {len(the_map()['screens'])} экранов, {len(the_map()['actions'])} действий → {out}")
