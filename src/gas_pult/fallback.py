"""Запасные: поставщик или интеграция не отвечает — пульт сам переходит на запасной и говорит об этом одной строкой.

Общее правило (голос — с #53, модели — здесь):
- цепочка — упорядоченный список замен (``Chain``); ``next_ok`` берёт первую подходящую, кроме уже упавших;
- подходящая — разрешена для стран человека, чьё это окно (``@gas_pult_by``, иначе владельца; ``country.py``), и есть
  чем запустить (ключ); запрещённая для этих стран — не берётся никогда, даже если других нет: тогда не
  переключаемся, а сообщаем;
- о переключении — одна строка: в Telegram владельцам и в панель (``fallback_log`` в state.json).

Модели. Цепочка поставщиков — ``fallback_chain`` в ``state.json`` пульта (меняется в панели: «Интеграции» →
«Модели» → «Запасные»); не задана — ``["claude"]``, базовый Claude последним запасным. Пустой список — не
переключать. Отказ виден в транскрипте Claude Code: запись ``isApiErrorMessage`` (Claude Code пишет её, когда сам
перестал повторять запрос) — ``classify_entry``. Монитор бота (``Switcher``) ждёт, пока сессия остановится на ошибке
(не идёт ответ, нет вопроса, человек ничего не набирает), и перезапускает это же окно у следующего поставщика с
``--continue`` — разговор продолжается с того же места.

Защита от петли: окно переключается не чаще раза в ``COOLDOWN`` (5 минут); упавшие поставщики окна помнятся ``FORGET`` и
обратно не выбираются; список исчерпан — одна строка «запасных нет» (и снова не раньше ``COOLDOWN``).

Голос (#53): ElevenLabs → локальные Piper / whisper — цепочка ``VOICE`` для показа в панели; само переключение — в
``webapp.Panel.stt/tts`` как было.

Замены нет: MCP-серверы и коннекторы claude.ai (у каждого своя работа), Telegram-бот, GitHub в утренней сводке.
"""

from __future__ import annotations

import re
import time
from datetime import datetime

from gas_pult import models, providers, transcripts

DEFAULT_CHAIN = ["claude"]
KINDS = {"auth": "нет доступа", "rate": "лимит", "server": "сбой сервера", "timeout": "нет связи"}
VOICE = {"tts": ["ElevenLabs", "На сервере · Piper"], "stt": ["ElevenLabs Scribe", "На сервере · whisper"]}

# Код ответа — только рядом со словами «API Error», «status», «HTTP», «code»: голое «401» в тексте — не ошибка.
STATUS = re.compile(r"(?:API Error|status(?:\s*code)?|HTTP(?:/[\d.]+)?|code)\W{0,3}([1-5]\d\d)\b", re.I)
PATTERNS = [
    ("auth", re.compile(r"authentication_error|permission_error|invalid[ _-]?(?:x-)?api[ _-]?key|"
                        r"OAuth token (?:has )?expired|token (?:has )?expired|Please run /login|"
                        r"credit balance is too low|insufficient[ _](?:credits|quota|balance)|"
                        r"account[ _](?:is[ _])?on[ _]hold|"
                        r"billing_error|unauthori[sz]ed", re.I)),
    ("rate", re.compile(r"rate[ _-]?limit|too many requests|usage limit|hit your limit|quota exceeded", re.I)),
    ("server", re.compile(r"overloaded|internal server error|service unavailable|bad gateway|\bapi_error\b|"
                          r"server_error", re.I)),
    ("timeout", re.compile(r"timed? ?out|ETIMEDOUT|ECONNREFUSED|ECONNRESET|ENOTFOUND|EAI_AGAIN|connection error|"
                           r"fetch failed|socket hang up|unable to connect|network error", re.I)),
]
# Поле ``error`` записи транскрипта (Claude Code) → вид отказа. ``invalid_request`` (нет модели, плохой запрос) —
# ошибка настройки, а не отказ поставщика: не переключаем.
ERROR_FIELD = {"authentication_failed": "auth", "authentication_error": "auth", "permission_error": "auth",
               "billing_error": "auth", "account_on_hold": "auth", "rate_limit": "rate", "rate_limit_error": "rate",
               "overloaded": "server", "overloaded_error": "server", "server_error": "server", "api_error": "server",
               "timeout": "timeout", "connection_error": "timeout"}


def kind_of_status(code: int | None) -> str | None:
    if code in (401, 402, 403):
        return "auth"
    if code == 429:
        return "rate"
    if code in (408, 504):
        return "timeout"
    if code and 500 <= code <= 599:
        return "server"
    return None


def status_of(text: str) -> int | None:
    m = STATUS.search(text or "")
    return int(m.group(1)) if m else None


def classify_error(text: str) -> str | None:
    """Текст ошибки API → ``auth`` (ключ, оплата, доступ) | ``rate`` (лимит) | ``server`` (5xx, перегрузка) |
    ``timeout`` (нет ответа, нет связи) | ``None`` (не отказ поставщика)."""
    if kind := kind_of_status(status_of(text)):
        return kind
    for kind, rx in PATTERNS:
        if rx.search(text or ""):
            return kind
    return None


def classify_entry(e: dict) -> tuple[str, int | None] | None:
    """Запись транскрипта Claude Code → (вид отказа, код) или ``None``. Только записи-ошибки API основной сессии
    (``isApiErrorMessage``); текст разговора, где упоминается «API Error: 401», — не отказ."""
    if not e.get("isApiErrorMessage") or e.get("isSidechain"):
        return None
    code = e.get("apiErrorStatus") if isinstance(e.get("apiErrorStatus"), int) else None
    text = transcripts.text_of((e.get("message") or {}).get("content"))
    code = code or status_of(text)
    if code in (400, 404, 413, 422):                     # плохой запрос, нет модели — настройка, не отказ
        return None
    kind = kind_of_status(code) or ERROR_FIELD.get(str(e.get("error") or "")) or classify_error(text)
    return (kind, code) if kind else None


def why(kind: str, code: int | None) -> str:
    return str(code) if code else KINDS.get(kind, kind)


def name(profile: str) -> str:
    return models.BY_ID.get(profile, {}).get("title", profile)


# ---------- цепочка ----------
class Chain(list):
    """Упорядоченный список замен без повторов и неизвестных."""

    def __init__(self, items=(), known=None):
        known = models.BY_ID if known is None else known
        out: list[str] = []
        for x in items or ():
            if x in known and x not in out:
                out.append(x)
        super().__init__(out)

    def after(self, failed: str) -> list[str]:
        """Кандидаты по порядку: за упавшим — следующие, потом с начала; сам упавший — никогда."""
        if failed in self:
            i = self.index(failed)
            return [*self[i + 1:], *self[:i]]
        return list(self)


def chain_of(state: dict) -> Chain:
    raw = state.get("fallback_chain")
    return Chain(DEFAULT_CHAIN if raw is None else raw)


def next_ok(chain, failed: str, allowed=lambda p: True, tried=()) -> str | None:
    """Следующий запасной после ``failed``: подходит (``allowed``) и ещё не падал (``tried``); нет — ``None``."""
    return next((p for p in Chain(chain).after(failed) if p not in tried and allowed(p)), None)


def where(countries) -> str:
    cs = sorted(models.countries_of(countries))
    return ", ".join(cs) if cs else "—"


def reason(profile: str, countries, keys: dict) -> str:
    """Почему профиль не годится в запасные: «» — годится. ``countries`` — страна или набор стран."""
    if not models.allowed(profile, countries):
        return f"не для страны {where(countries)}"
    if not models.has_key(profile, keys):
        return "нет ключа"
    return ""


def validate(items, countries) -> list[str]:
    """Цепочка из панели: только известные профили, без повторов; запрещённый для стран — ошибка."""
    if not isinstance(items, list) or not all(isinstance(x, str) for x in items):
        raise ValueError("цепочка — список поставщиков")
    bad = [x for x in items if x not in models.BY_ID]
    if bad:
        raise ValueError(f"нет такого поставщика: {bad[0][:30]}")
    for x in items:
        if not models.allowed(x, countries):
            raise ValueError(f"{name(x)}: {models.DENY} ({where(countries)})")
    return list(Chain(items))


def recent(state: dict, secs: int = 900, now: float | None = None) -> list[dict]:
    """Переключения за последние ``secs`` секунд — панель показывает каждое один раз строкой."""
    now = time.time() if now is None else now
    return [x for x in state.get("fallback_log") or [] if now - float(x.get("ts") or 0) < secs]


def public(state: dict, region: str, keys: dict | None = None, countries=None) -> dict:
    """Для панели: цепочка, все поставщики с пометкой «годится / почему нет», последние переключения. ``countries`` —
    страны, по которым проверяем (нет — страна сервера ``region``)."""
    keys = providers.load_keys() if keys is None else keys
    cs = region if countries is None else countries
    return {"chain": list(chain_of(state)), "region": (region or "").upper(),
            "countries": sorted(models.countries_of(cs)),
            "options": [{"id": p["id"], "title": p["title"], "why": reason(p["id"], cs, keys),
                         "denied": not models.allowed(p["id"], cs)} for p in models.PROFILES],
            "log": list(state.get("fallback_log") or [])[-10:], "voice": VOICE}


# ---------- монитор: отказ в окне → запасной ----------
def ts_of(e: dict) -> float:
    try:
        return datetime.fromisoformat(str(e.get("timestamp", "")).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


PROMPT_LINE = re.compile(r"^[\s│|]*[❯>][\s ]?(.*?)[\s│|]*$")


def typing(lines: list[str], hint: str = "") -> bool:
    """Человек что-то набирает в строке ввода Claude Code (не пусто и не бледная подсказка) — не мешаем."""
    for line in reversed(lines[-15:]):
        if m := PROMPT_LINE.match(line):
            text = " ".join(m.group(1).split())
            return bool(text) and text != " ".join((hint or "").split()) and not re.match(r"\d\.\s", text)
    return False


class Switcher:
    """Отказ поставщика в окне → то же окно у следующего запасного с ``--continue`` и одна строка человеку."""

    COOLDOWN = 300          # не чаще раза на окно за 5 минут
    FORGET = 3600           # упавшие поставщики окна помнятся час
    STALE = 300             # ошибка старше 5 минут (старый журнал, повтор истории после --continue) — не повод

    def __init__(self, tmux, state, base: str, region: str = "", say=print, log=None, keys=None, clock=time.time,
                 countries=None):
        self.tmux, self.state, self.base, self.region = tmux, state, base, (region or "").upper()
        # страны человека, чьё окно (``countries(w) -> set``); не задано — только страна сервера
        self.countries = countries
        self.say, self.log = say, log or (lambda entry: None)
        self.keys = keys or providers.load_keys
        self.clock = clock
        self.pending: dict[str, dict] = {}      # окно → последняя ошибка, ждём, пока сессия остановится
        self.windows: dict[str, dict] = {}      # окно → {"t": когда действовали, "tried": {профиль: когда упал}}

    def seen(self, wid: str, e: dict):
        """Каждая новая запись транскрипта окна: ошибка API — запомнить; нормальный ход или новый запрос — забыть."""
        if e.get("isSidechain"):
            return
        if hit := classify_entry(e):
            now, t = self.clock(), ts_of(e)
            last = self.windows.get(wid, {}).get("t", 0)
            if (t and now - t > self.STALE) or (t and t <= last):
                return
            self.pending[wid] = {"kind": hit[0], "code": hit[1], "t": now}
        elif e.get("type") == "assistant" or (e.get("type") == "user" and transcripts.is_real_prompt(e)):
            self.pending.pop(wid, None)

    def step(self, w: dict, idle: bool) -> str | None:
        """Обход монитора: есть ошибка и сессия стоит на ней (``idle``) — действуем. Возвращает отправленную строку."""
        p = self.pending.get(w["id"])
        if not p or not idle:
            return None
        if self.clock() - self.windows.get(w["id"], {}).get("t", 0) < self.COOLDOWN:
            return None                          # только что переключали — подождём; ошибка не забыта
        del self.pending[w["id"]]
        return self.act(w, p["kind"], p["code"])

    def act(self, w: dict, kind: str, code: int | None, region=None) -> str | None:
        now, wid = self.clock(), w["id"]
        if region is None:
            region = self.countries(w) if self.countries else self.region
        mem = self.windows.setdefault(wid, {"t": 0, "tried": {}})
        failed = w.get("profile") or "claude"
        mem["tried"] = {p: t for p, t in mem["tried"].items() if now - t < self.FORGET}
        mem["tried"][failed] = now
        mem["t"] = now
        st, keys = self.state(), self.keys()
        chain = chain_of(st)
        head = f"Поставщик {name(failed)} не отвечает ({why(kind, code)})"
        nxt = next_ok(chain, failed, lambda p: not reason(p, region, keys), mem["tried"])
        if not nxt:
            skipped = [f"{name(p)} — {r}" for p in chain.after(failed) if p not in mem["tried"]
                       and (r := reason(p, region, keys))]
            line = f"{head} — запасных нет" + (f" ({'; '.join(skipped)})" if skipped else "") + \
                   f", сессия «{w['name']}» ждёт"
            return self.tell(w, line, failed, "", kind, code)
        try:
            cmd = models.command(self.base, nxt, st) + " --continue"
            self.tmux.respawn(wid, w["path"], cmd, mark=nxt)
        except (ValueError, RuntimeError) as e:
            return self.tell(w, f"{head} — переключить сессию «{w['name']}» на {name(nxt)} не вышло: {e}",
                             failed, "", kind, code)
        return self.tell(w, f"{head} — сессия «{w['name']}» переключена на {name(nxt)}", failed, nxt, kind, code)

    def tell(self, w: dict, line: str, failed: str, to: str, kind: str, code) -> str:
        self.log({"ts": self.clock(), "t": time.strftime("%Y-%m-%d %H:%M", time.localtime(self.clock())), "w": w["id"],
                  "name": w["name"], "from": failed, "to": to, "kind": kind, "code": code, "text": line})
        self.say(line)
        return line
