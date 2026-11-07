"""Расход сессий Claude Code: токены и деньги из журналов, лимиты на сессию и на день, пауза при превышении.

Журнал (``<папка Claude>/projects/<папка-проекта>/<сессия>.jsonl``, субагенты — ``<сессия>/subagents/*.jsonl``):
в записях ``type: "assistant"`` — ``message.model``, ``message.usage`` (ввод, вывод, запись и чтение кэша) и
``message.id``. Одно сообщение Claude Code пишет несколькими строками с одним ``id`` — считаем один раз (у повтора
с большими числами добавляем разницу). Файлы читаются по смещению, как ``transcripts.Tail``: каждые несколько
секунд дочитываются только новые строки.

Деньги — по поставщику ответа (``provider_of``, задача 51): Claude Code чужих моделей не знает и считает их по
тарифам Anthropic, поэтому его цене (``costUSD``) не верим и считаем сами, с источником цены (``cost_source``):
- ``anthropic`` — модели Claude напрямую: прайс API Anthropic (``PRICES``). У подписки Pro/Max счёта за токены нет —
  для неё это «сколько стоило бы по API»;
- ``provider`` — OpenRouter (id модели «поставщик/модель», ``requestId`` «gen-…»): фактическое списание за каждый
  ответ (``openrouter.Billing``, фоном); пока счёт не пришёл — ответ «ждёт цены» (``pending``);
- ``estimate`` — Z.ai (glm-…) и DeepSeek (deepseek-…): токены × тариф поставщика (``models.PROVIDER_PRICES``),
  в панели и боте — «оценка».
Остальные модели (шлюзы GigaChat, YandexGPT, неизвестные id) — токены есть, цена неизвестна: не выдумываем.

Пулы: «чужие учётки в общий пул не собираем». Пул — папка Claude Code (``people.home_of``): владелец — ``~/.claude``
(в нём и окна, которые участник открыл на учётке владельца, — с пометкой, кто открыл), участник со своей папкой —
свой пул. Дневной итог и дневной лимит — по пулу владельца; участник видит только свой расход.

Лимиты (state.json, ``cost_limits``) задаёт владелец; по умолчанию выключены. Превышение — окно на паузе
(``cost_paused``): текущий ход прерывается (Esc), новые сообщения в окно не отправляются, владельцу — один вопрос
«Продолжить, +лимит / Остановить». Решения — ``decide``; логика лимитов — чистые функции над state.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import date, datetime
from pathlib import Path

from gas_pult import models

# Прайс API Anthropic, USD за 1 млн токенов: (ввод, вывод, чтение кэша). Запись кэша — от цены ввода:
# 5 минут — ×1,25, 1 час — ×2. Быстрый режим (usage.speed = "fast") — ×2.
# Источник: https://platform.claude.com/docs/en/about-claude/pricing — сверено по справке Claude API (кэш
# от 06.10.2026) 02.11.2026. Цены меняются — сверяйте при выходе новых моделей; модели нет в списке — «цена неизвестна».
PRICES_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
PRICES_CHECKED = "2026-11-02"
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-fable-5-1": (10.0, 50.0, 0.25), "claude-mythos-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.0), "claude-mythos-5": (10.0, 50.0, 1.0),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50), "claude-opus-4-8": (5.0, 25.0, 0.50),
    "claude-opus-4-7": (5.0, 25.0, 0.50), "claude-opus-4-6": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20), "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-sonnet-4-6": (3.0, 15.0, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.01), "claude-haiku-4-5": (1.0, 5.0, 0.10),
}
# Длинный запрос — другая цена: Haiku 5.5 при запросе больше 100 тыс. токенов — $0,50 / $2,50.
LONG: dict[str, tuple[int, tuple[float, float, float]]] = {"claude-haiku-5-5": (100_000, (0.50, 2.50, 0.05))}
WRITE_5M, WRITE_1H, FAST = 1.25, 2.0, 2.0
MODEL_ID = re.compile(r"claude-(fable|mythos|opus|sonnet|haiku)-(\d+)(?:[.-](\d{1,2}))?(?!\d)")
KINDS = ("in", "out", "cw", "cr")               # ввод, вывод, запись кэша, чтение кэша
SOURCES = ("anthropic", "provider", "estimate", "wait")   # откуда цена ответа; «wait» — ждём счёт OpenRouter


def provider_of(model: str, request_id: str = "") -> str:
    """Чей ответ — по id модели из журнала: «openrouter» (id «поставщик/модель» или генерация «gen-…»), «zai»
    (glm-…), «deepseek» (deepseek-…), «anthropic» (claude-…); иначе «» (шлюз, неизвестная модель)."""
    m = (model or "").strip().lower()
    if str(request_id or "").startswith("gen-") or "/" in m:
        return "openrouter"
    if m.startswith("glm"):
        return "zai"
    if m.startswith("deepseek"):
        return "deepseek"
    return "anthropic" if MODEL_ID.search(m) else ""


def model_key(model: str) -> str:
    """id модели из журнала → ключ прайса: «anthropic/claude-haiku-5.5», «claude-opus-5-5[1m]»,
    «claude-sonnet-4-6-20260101» → «claude-haiku-5-5», «claude-opus-5-5», «claude-sonnet-4-6». Не Claude — как есть."""
    m = MODEL_ID.search((model or "").lower())
    if not m:
        return (model or "").strip()
    return f"claude-{m.group(1)}-{m.group(2)}" + (f"-{m.group(3)}" if m.group(3) else "")


def tokens(u: dict) -> dict:
    """usage из журнала → {in, out, cw, cr} и разбивка записи кэша (5 минут / 1 час)."""
    def n(x) -> int:
        try:
            return max(0, int(x or 0))
        except (TypeError, ValueError):
            return 0
    cw = n(u.get("cache_creation_input_tokens"))
    split = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
    h1 = min(cw, n(split.get("ephemeral_1h_input_tokens")))
    return {"in": n(u.get("input_tokens")), "out": n(u.get("output_tokens")), "cw": cw,
            "cr": n(u.get("cache_read_input_tokens")), "cw1h": h1}


def cost(model: str, u: dict) -> float | None:
    """Цена одного ответа в USD; модели нет в прайсе — None (цена неизвестна)."""
    key = model_key(model)
    p = PRICES.get(key)
    if not p:
        return None
    t = tokens(u)
    if key in LONG and t["in"] + t["cw"] + t["cr"] > LONG[key][0]:
        p = LONG[key][1]
    inp, out, read = p
    x = FAST if u.get("speed") == "fast" else 1.0
    write = (t["cw"] - t["cw1h"]) * inp * WRITE_5M + t["cw1h"] * inp * WRITE_1H
    return x * (t["in"] * inp + t["out"] * out + t["cr"] * read + write) / 1e6


def empty() -> dict:
    return {"in": 0, "out": 0, "cw": 0, "cr": 0, "usd": 0.0, "unpriced": 0, **{f"n_{s}": 0 for s in SOURCES}}


def add(acc: dict, t: dict, usd: float | None, sign: int = 1, src: str = "") -> dict:
    """Прибавить токены и деньги; ответы без цены — счётчиком ``unpriced`` (их токены в сумме есть). ``src`` —
    источник цены ответа (``SOURCES``): счётчик ``n_<src>``."""
    for k in KINDS:
        acc[k] += sign * t.get(k, 0)
    if usd is None:
        acc["unpriced"] += sign
    else:
        acc["usd"] += sign * usd
    if src:
        acc[f"n_{src}"] = acc.get(f"n_{src}", 0) + sign
    return acc


def merge(*xs: dict) -> dict:
    out = empty()
    for x in xs:
        for k in (*KINDS, "unpriced", *(f"n_{s}" for s in SOURCES)):
            out[k] += x.get(k, 0)
        out["usd"] += x.get("usd", 0.0)
    return out


def source(x: dict) -> str | None:
    """Источник цены итога: есть хоть одна оценка — «estimate»; иначе счёт поставщика — «provider»; иначе прайс
    Anthropic — «anthropic»; цен нет — None."""
    if x.get("n_estimate"):
        return "estimate"
    if x.get("n_provider") or x.get("n_wait"):
        return "provider"
    return "anthropic" if x.get("n_anthropic") else None


def public(x: dict) -> dict:
    """Для панели: токены, деньги (None — цена неизвестна для всех ответов) и есть ли ответы без цены. Добавлено
    (задача 51): ``cost_source`` — откуда цена («anthropic» | «provider» | «estimate» | None), ``pending`` — сколько
    ответов OpenRouter ещё ждут счёта."""
    total = sum(x[k] for k in KINDS)
    priced = x["usd"] > 0 or not x["unpriced"]
    return {"tokens": {k: x[k] for k in KINDS}, "total": total,
            "usd": round(x["usd"], 4) if priced else None, "unknown": x["unpriced"] > 0,
            "cost_source": source(x), "pending": max(0, x.get("n_wait", 0))}


def local_day(ts: str) -> str:
    """Время из журнала (UTC, ISO) → день по местному времени сервера: «2026-11-02»."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().date().isoformat()
    except (ValueError, AttributeError):
        return date.today().isoformat()


def short(n: int) -> str:
    """12 345 → «12k», 1 234 567 → «1.2M» — токены на карточке и в боте."""
    if n >= 1_000_000:
        return f"{n / 1e6:.1f}M"
    return f"{n / 1e3:.0f}k" if n >= 1000 else str(n)


def money(x: float | None) -> str:
    return "цена неизвестна" if x is None else f"${x:.2f}"


class File:
    """Расход одного журнала: смещение, итог и по дням; уже посчитанные сообщения (id → день и токены)."""

    __slots__ = ("days", "ino", "model", "msgs", "off", "total")

    def __init__(self, ino: int):
        self.off, self.ino, self.total, self.days, self.msgs, self.model = 0, ino, empty(), {}, {}, ""


class Meter:
    """Дочитывает журналы и копит расход. Один на процесс (бот или панель); потокобезопасен."""

    DAY_EVERY = 10                                    # с: обход всех журналов пула за день — не чаще

    def __init__(self, projects: Path | None = None, billing=None):
        self.root = projects                          # папка projects владельца (тесты — своя); None — ~/.claude
        self.files: dict[Path, File] = {}
        self.seen: dict[str, Path] = {}               # id сообщения → журнал, где его уже посчитали
        self.lock = threading.Lock()
        self._day: dict[str, tuple[float, str, dict]] = {}   # пул → (когда, день, итог)
        self._billing = billing                       # счёт OpenRouter (openrouter.Billing); None — создать при нужде
        self.waiting: dict[str, set[tuple[Path, str]]] = {}  # id генерации → (журнал, id сообщения), ждут цены

    @property
    def billing(self):
        if self._billing is None:
            from gas_pult import openrouter
            self._billing = openrouter.Billing(on_cost=self.settle)
        elif getattr(self._billing, "on_cost", 0) is None:
            self._billing.on_cost = self.settle
        return self._billing

    def price(self, model: str, u: dict, t: dict, rid: str, ts: str) -> tuple[float | None, str]:
        """Цена ответа и её источник (``SOURCES``; «» — цены нет). Цену Claude Code (costUSD) не берём."""
        prov = provider_of(model, rid)
        if prov == "anthropic":
            usd = cost(model, {**u, "input_tokens": t["in"], "output_tokens": t["out"],
                               "cache_creation_input_tokens": t["cw"], "cache_read_input_tokens": t["cr"]})
            return usd, "anthropic" if usd is not None else ""
        if prov == "openrouter":
            src, usd = self.billing.lookup(rid)
            return usd, src
        if prov in models.PROVIDER_PRICES:
            usd = models.estimate(prov, model, t, ts)
            return usd, "estimate" if usd is not None else ""
        return None, ""

    def settle(self, gen: str, usd: float | None):
        """Пришёл счёт OpenRouter за ответ (из фонового потока): «ждёт цены» → цена (или «цена неизвестна»)."""
        with self.lock:
            for f, mid in self.waiting.pop(gen, ()):
                rec = self.files.get(f)
                entry = rec.msgs.get(mid) if rec else None
                if not entry or entry[3] != "wait":
                    continue
                day, t = entry[0], entry[1]
                src = "provider" if usd is not None else ""
                for acc in (rec.total, rec.days.setdefault(day, empty())):
                    add(acc, {}, None, -1, "wait")
                    add(acc, {}, usd, 1, src)
                rec.msgs[mid] = (day, t, usd, src)
            self._day.clear()

    def projects(self, home: Path | None) -> Path:
        if home:
            return Path(home) / "projects"
        if self.root:
            return self.root
        from gas_pult import transcripts
        return transcripts.CLAUDE_PROJECTS

    def read(self, f: Path) -> File:
        """Дочитать новые целые строки журнала; подменили или укоротили — считаем заново."""
        st = f.stat()
        rec = self.files.get(f)
        if rec is None or rec.ino != st.st_ino or st.st_size < rec.off:
            if rec is not None:
                self.forget(f, rec)
            rec = self.files[f] = File(st.st_ino)
        if st.st_size == rec.off:
            return rec
        with open(f, "rb") as fh:
            fh.seek(rec.off)
            chunk = fh.read(st.st_size - rec.off)
        cut = chunk.rfind(b"\n") + 1
        rec.off += cut
        for line in chunk[:cut].splitlines():
            if b'"usage"' not in line or b'"assistant"' not in line:      # быстрый отсев: большинство строк — не ответы
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            self.feed(f, rec, e)
        return rec

    def feed(self, f: Path, rec: File, e: dict):
        if e.get("type") != "assistant":
            return
        msg = e.get("message") or {}
        u, model = msg.get("usage"), str(msg.get("model") or "")
        if not isinstance(u, dict) or model.startswith("<"):         # «<synthetic>» — служебные, не модель
            return
        mid = str(msg.get("id") or e.get("requestId") or e.get("uuid") or "")
        if mid and self.seen.get(mid, f) != f:                       # уже посчитан в другом журнале (продолжение)
            return
        t = tokens(u)
        rid = str(e.get("requestId") or e.get("request_id") or "")
        ts = str(e.get("timestamp") or "")
        old = rec.msgs.get(mid) if mid else None
        if old:                                                      # повтор строки: добавляем только рост
            day, prev, pusd, psrc = old
            if all(t[k] <= prev[k] for k in KINDS):
                return
            t = {**t, **{k: max(t[k], prev[k]) for k in KINDS}}
            add(rec.total, prev, pusd, -1, psrc)                     # убираем ровно то, что добавили в прошлый раз
            add(rec.days.setdefault(day, empty()), prev, pusd, -1, psrc)
        else:
            day = local_day(ts)
        usd, src = self.price(model, u, t, rid, ts)
        if src == "wait" and not mid:                               # не к чему привязать счёт — цена неизвестна
            src = ""
        add(rec.total, t, usd, 1, src)
        add(rec.days.setdefault(day, empty()), t, usd, 1, src)
        if mid:
            rec.msgs[mid] = (day, {k: t[k] for k in KINDS}, usd, src)
            self.seen[mid] = f
            if src == "wait":
                self.waiting.setdefault(rid, set()).add((f, mid))
        rec.model = model

    def forget(self, f: Path, rec: File):
        for mid in rec.msgs:
            if self.seen.get(mid) == f:
                del self.seen[mid]

    @staticmethod
    def session_files(main: Path) -> list[Path]:
        """Журнал сессии и её субагентов."""
        return [main, *sorted((main.parent / main.stem / "subagents").glob("*.jsonl"))]

    def session(self, path: str, home: Path | None = None, today: str | None = None, sid: str = "") -> dict | None:
        """Расход сессии (журнал + субагенты): итог, за сегодня, id сессии, модель. ``sid`` — свой журнал окна
        (``--session-id``); без него — последний журнал папки."""
        from gas_pult import transcripts
        d = self.projects(home) / re.sub(r"[^A-Za-z0-9]", "-", path)
        try:
            if sid := transcripts.valid_sid(sid):
                main = d / f"{sid}.jsonl"
                if not main.exists():
                    return None
            else:
                files = sorted(d.glob("*.jsonl"))
                if not files:
                    return None
                main = max(files, key=lambda p: p.stat().st_mtime)
        except OSError:
            return None
        today = today or date.today().isoformat()
        with self.lock:
            recs = []
            for f in self.session_files(main):
                try:
                    recs.append(self.read(f))
                except OSError:
                    continue
            total = merge(*(r.total for r in recs))
            day = merge(*(r.days.get(today, empty()) for r in recs))
        model = recs[0].model if recs else ""
        return {"id": main.stem, "total": total, "today": day, "model": transcripts.model_title(model_key(model))
                if model else ""}

    def day(self, home: Path | None = None, today: str | None = None, fresh: bool = False) -> dict:
        """Расход пула за день: все журналы пула (и сессии вне пульта), изменённые сегодня, — записи этого дня."""
        today = today or date.today().isoformat()
        key = str(home or "")
        with self.lock:
            hit = self._day.get(key)
            if hit and not fresh and hit[1] == today and time.time() - hit[0] < self.DAY_EVERY:
                return hit[2]
            root = self.projects(home)
            since = time.mktime(date.fromisoformat(today).timetuple())
            acc = empty()
            try:
                files = [*root.glob("*/*.jsonl"), *root.glob("*/*/subagents/*.jsonl")]
            except OSError:
                files = []
            for f in files:
                try:
                    if f.stat().st_mtime < since and f not in self.files:
                        continue
                    acc = merge(acc, self.read(f).days.get(today, empty()))
                except OSError:
                    continue
            self._day[key] = (time.time(), today, acc)
            return acc


    def days(self, home: Path | None, since: str, detail: bool = False) -> dict:
        """Расход пула в USD по дням начиная с ``since`` («ГГГГ-ММ-ДД»): все журналы, изменённые с этого дня.
        ``detail`` — итоги дней целиком (токены, источник цены), а не только USD."""
        start = time.mktime(date.fromisoformat(since).timetuple())
        out: dict[str, dict] = {}
        with self.lock:
            root = self.projects(home)
            try:
                files = [*root.glob("*/*.jsonl"), *root.glob("*/*/subagents/*.jsonl")]
            except OSError:
                files = []
            for f in files:
                try:
                    if f.stat().st_mtime < start and f not in self.files:
                        continue
                    for day, acc in self.read(f).days.items():
                        if day >= since:
                            out[day] = merge(out.get(day, empty()), acc)
                except OSError:
                    continue
        if detail:
            return out
        return {d: round(x["usd"], 4) for d, x in out.items()}


# ---------- лимиты и пауза: чистые функции над state.json ----------

def limits(state: dict) -> dict:
    """{"session": USD | None, "day": USD | None} — None или 0 — лимит выключен."""
    raw = state.get("cost_limits") or {}
    out = {}
    for k in ("session", "day"):
        try:
            v = float(raw.get(k) or 0)
        except (TypeError, ValueError):
            v = 0.0
        out[k] = v if v > 0 else None
    return out


def check_limits(value) -> dict:
    """Лимиты из панели → для state.json; пусто или 0 — выключен. Не число или меньше нуля — ошибка."""
    out = {}
    for k in ("session", "day"):
        v = (value or {}).get(k)
        if v in (None, "", 0, "0"):
            out[k] = None
            continue
        try:
            x = round(float(str(v).replace(",", ".")), 2)
        except ValueError:
            raise ValueError("лимит — число в долларах, например 5 или 2.5") from None
        if x < 0 or x > 100_000:
            raise ValueError("лимит — от 0 до 100 000 долларов")
        out[k] = x or None
    return out


def watch(state: dict, sessions: list[dict], day_usd: float, today: str) -> tuple[dict, list[dict]]:
    """Проверка лимитов. ``sessions`` — окна пула владельца: {w, name, sid, usd}; ``day_usd`` — итог пула за день.

    Возвращает (обновления state.json, новые паузы). Одна пауза — один вопрос: окно уже на паузе — не повторяем.
    Расход снова в пределах (владелец поднял лимит, новый день, новая сессия в окне) — пауза снимается; окна нет —
    его пауза забывается. Лимиты выключены — пауз нет."""
    lim = limits(state)
    old = state.get("cost_paused") or {}
    extra = state.get("cost_extra") or {}                           # «+лимит» по сессии: id сессии → USD
    day_cap = None if lim["day"] is None else lim["day"] + (state.get("cost_day_extra") or {}).get(today, 0.0)
    paused, new = {}, []
    for s in sessions:
        cap = None if lim["session"] is None else lim["session"] + extra.get(s["sid"], 0.0)
        if cap is not None and s.get("usd") is not None and s["usd"] >= cap:   # цена неизвестна — не по сессии
            rec = {"kind": "session", "spent": round(s["usd"], 4), "limit": round(cap, 2), "sid": s["sid"]}
        elif day_cap is not None and day_usd >= day_cap:
            rec = {"kind": "day", "spent": round(day_usd, 4), "limit": round(day_cap, 2)}
        else:
            continue                                                # в пределах — паузы нет (или снимается)
        if (p := old.get(s["w"])) and p.get("kind") == rec["kind"]:
            paused[s["w"]] = p                                      # уже спросили — не повторяем
            continue
        rec |= {"name": s.get("name", ""), "at": int(time.time()), "day": today, "state": "ask"}
        if rec["kind"] == "session" and s.get("src") == "estimate":
            rec["src"] = "estimate"                                 # Z.ai, DeepSeek: потрачено — оценка
        paused[s["w"]] = rec
        new.append({"w": s["w"], **rec})
    sids = {s["sid"] for s in sessions}
    return {"cost_paused": paused, "cost_extra": {k: v for k, v in extra.items() if k in sids}}, new


def decide(state: dict, wid: str, act: str, today: str) -> tuple[dict, dict]:
    """Решение владельца по паузе окна: «go» — продолжить, лимит +ещё один шаг; «stop» — оставить на паузе
    без новых вопросов. Возвращает (обновления state.json, запись паузы)."""
    paused = dict(state.get("cost_paused") or {})
    p = paused.get(wid)
    if not p:
        raise LookupError("эта сессия уже не на паузе")
    lim = limits(state)
    if act == "stop":
        paused[wid] = {**p, "state": "stopped"}
        return {"cost_paused": paused}, paused[wid]
    if act != "go":
        raise ValueError("решение: продолжить или остановить")
    upd: dict = {}
    if p["kind"] == "session":
        extra = dict(state.get("cost_extra") or {})
        step = lim["session"] or 0.0
        # новый потолок — на шаг выше того, что уже потрачено (а не только прежнего лимита)
        while lim["session"] is not None and lim["session"] + extra.get(p["sid"], 0.0) <= p["spent"]:
            extra[p["sid"]] = extra.get(p["sid"], 0.0) + step
            if step <= 0:
                break
        upd["cost_extra"] = extra
        del paused[wid]
    else:
        de = dict(state.get("cost_day_extra") or {})
        cur = de.get(today, 0.0)
        step = lim["day"] or 0.0
        while lim["day"] is not None and lim["day"] + cur <= p["spent"] and step > 0:
            cur += step
        upd["cost_day_extra"] = {today: cur}                        # прошлые дни не храним
        paused = {k: v for k, v in paused.items() if v.get("kind") != "day"}   # день — для всех окон пула
    upd["cost_paused"] = paused
    return upd, p


def question(p: dict) -> str:
    """Текст вопроса владельцу о паузе."""
    what = "за сегодня по вашей учётке" if p["kind"] == "day" else "в этой сессии"
    est = " по оценке" if p.get("src") == "estimate" else ""
    return (f"💰 Сессия «{p.get('name') or p.get('w', '')}» на паузе: {what} потрачено{est} ${p['spent']:.2f} "
            f"(лимит ${p['limit']:.2f}). Продолжить?")
