"""Одноразовые приглашения тестировщиков (задача 31): ссылка ``/invite/<код>`` на 24 часа.

Приглашение привязано к демо-пространству и роли. Человек открывает ссылку → экран входа панели с пометкой
«приглашение в …» → «Войти через Telegram» → в боте «Start» → доступ выдаётся сразу (без кнопки владельца), владельцу
приходит уведомление. Код работает один раз; хранится только его хеш (``invites.json``, 0600). Отзыв —
``gas-pult invite revoke <код>`` (или первые знаки кода из ``gas-pult invite list``).

Лёгкий вход (задача 34): у того же приглашения есть **короткий код** вида ``PLANETA-482157`` (слово — из названия
пространства латиницей или нейтральное, цифры 2–9; ни 0/O, ни 1/I) — его можно продиктовать или ввести на экране
входа. Ссылка и короткий код — одно приглашение: сработал один — сгорели оба. Вход по ним без Telegram заводит
«гостя» (``people.add_guest``). **Ссылка для входа на другое устройство** — то же приглашение с полем ``uid``: вместо
нового человека — сессия уже существующего (выпускает владелец или сам человек). Перебор кодов — ``Misses``.

Приглашения v2 (владелец 17.11: «не одноразово — тестировать на телефоне и компьютере»): срок ссылки — ``TTLS``
(24 ч … год), число входов — ``uses`` (1, N или 0 — без лимита, пока не вышел срок), срок доступа человека —
``access`` дней (0 — бессрочно; пишется человеку в ``access_until``, «Люди» → продлить), ``plan`` — задел на подписку
(trial / pilot / paid; оплаты пока нет). Старые записи без ``uses`` — одноразовые, как раньше.

Одна ссылка = вход (владелец 17.11, отзыв тестировщика: «я рассчитываю на обычную ссылку — нажал — сработало»).
Владелец пишет имя человека (``name``; нет — «Гость»). Человек нажимает ссылку → «Здравствуйте, <имя>!» → «Начать» →
внутри: без кода, без имени, без Telegram. После первого входа приглашение привязано к человеку (``uid``): та же
ссылка на других устройствах (``uses``, по умолчанию 3) — тот же человек, а не новый гость. Владельцу — сообщение о
каждом устройстве. Вход — только нажатием: превью ссылки в мессенджере (GET) вход не тратит.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
import unicodedata
from pathlib import Path

from gas_pult import tenants
from gas_pult.config import data_dir, write_private

TTL = 24 * 3600
TTLS = {"1d": 86400, "7d": 7 * 86400, "30d": 30 * 86400, "90d": 90 * 86400, "365d": 365 * 86400}
ACCESS = (0, 1, 7, 30, 60, 90, 365)          # дней доступа человека после входа; 0 — бессрочно
PLANS = ("", "trial", "pilot", "paid")       # задел на подписку: только пометка, без оплаты
MAX_USES = 1000
ROLES = ("member", "viewer")
CODE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
HINT = 6                                     # первые знаки кода — чтобы узнать приглашение в списке и отозвать
DIGITS = "23456789"                          # без 0 и 1: их путают с O и I
SHORT_DIGITS = 6                             # 8^6 = 262 144 варианта на слово — перебор упирается в Misses
WORDS = ("RAKETA", "KASKAD", "VESNA", "ZVEZDA", "KAKTUS", "MAYAK", "PLANETA", "PARUS", "KUPAVA", "SKAZKA")
TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                    ["A", "B", "V", "G", "D", "E", "E", "ZH", "Z", "I", "Y", "K", "L", "M", "N", "O", "P", "R", "S",
                     "T", "U", "F", "KH", "TS", "CH", "SH", "SCH", "", "Y", "", "E", "YU", "YA"], strict=True))
_lock = threading.Lock()


def store() -> Path:
    return data_dir() / "invites.json"


def _h(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _load() -> dict:
    try:
        d = json.loads(store().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d: dict):
    write_private(store(), json.dumps(d, ensure_ascii=False))


def state(rec: dict, now: float | None = None) -> str:
    now = time.time() if now is None else now
    if rec.get("revoked"):
        return "revoked"
    if "uses" in rec:                         # v2: входов N (0 — без лимита)
        if rec["uses"] and rec.get("n", 0) >= rec["uses"]:
            return "used"
    elif rec.get("used"):
        return "used"
    return "expired" if now >= rec.get("exp", 0) else "active"


def word_of(tenant: str) -> str:
    """Первое слово короткого кода: из названия пространства (кириллица — латиницей) или его имени; если в слове есть
    O или I (их путают с 0 и 1) или оно короче 3 букв — нейтральное слово."""
    t = tenants.load(tenant) if tenants.enabled() else None
    for src in ((t or {}).get("title") or "", tenant):
        first = next(iter(re.split(r"[^\w]+", str(src).lower())), "")
        latin = "".join(TRANSLIT.get(ch, ch) for ch in first)
        latin = unicodedata.normalize("NFKD", latin).encode("ascii", "ignore").decode().upper()
        latin = re.sub(r"[^A-Z]", "", latin)[:10]
        if len(latin) >= 3 and not set(latin) & set("OI"):
            return latin
    return WORDS[secrets.randbelow(len(WORDS))]


def short_code(tenant: str) -> str:
    return word_of(tenant) + "-" + "".join(secrets.choice(DIGITS) for _ in range(SHORT_DIGITS))


def norm_short(code: str) -> str:
    """Короткий код как его ввёл человек → вид для сравнения: заглавные, без пробелов и дефисов."""
    return re.sub(r"[^A-Z0-9]", "", str(code or "").upper())[:24]


def new(tenant: str, role: str = "member", ttl: int = TTL, by: int | None = None, uid: int | None = None,
        uses: int = 1, access: int = 0, plan: str = "", name: str | None = None) -> dict:
    """Новое приглашение: {code, short, hint}. Коды показываются один раз — в файле только хеши.

    ``uid`` — ссылка для входа на другое устройство уже существующего человека (а не новый тестировщик).
    ``uses`` — сколько входов (0 — без лимита до конца срока), ``access`` — дней доступа человека (0 — бессрочно),
    ``plan`` — пометка подписки."""
    tenant = tenants.check_slug(tenant)
    if role not in ROLES:
        raise ValueError("роль: member (участник) или viewer (наблюдатель)")
    if int(ttl) > TTLS["365d"]:
        raise ValueError("срок ссылки — не больше года")
    if not 0 <= int(uses) <= MAX_USES:
        raise ValueError(f"входов — от 1 до {MAX_USES} или 0 (без лимита)")
    if int(access) not in ACCESS:
        raise ValueError("срок доступа: " + ", ".join(str(x) for x in ACCESS) + " дней (0 — бессрочно)")
    if plan not in PLANS:
        raise ValueError("план: trial, pilot или paid")
    while (code := secrets.token_urlsafe(18)).startswith("-"):    # «-» в начале — CLI примет код за ключ (revoke)
        pass
    short, now = short_code(tenant), time.time()
    with _lock:
        d = {k: v for k, v in _load().items() if now - v.get("exp", 0) < 30 * 86400}   # месяц после срока — чистим
        d[_h(code)] = {"tenant": tenant, "role": role, "created": int(now), "exp": int(now + ttl),
                       "hint": code[:HINT], "short": _h("s:" + norm_short(short)), "used": None, "revoked": False,
                       "uses": int(uses), "n": 0, **({"access": int(access)} if access else {}),
                       **({"plan": plan} if plan else {}),
                       **({"name": " ".join(str(name).split())[:60] or "Гость"} if name is not None else {}),
                       **({"by": int(by)} if by else {}), **({"uid": int(uid)} if uid is not None else {})}
        _save(d)
    return {"code": code, "short": short, "hint": code[:HINT]}


def create(tenant: str, role: str = "member", ttl: int = TTL, by: int | None = None) -> str:
    """Новое приглашение; возвращает код ссылки (показывается один раз — в файле только хеш)."""
    return new(tenant, role, ttl, by)["code"]


def _find(d: dict, code: str, short: bool = True) -> str | None:
    """Ключ записи по коду ссылки или (``short``) по короткому коду. Короткий код угадать проще — его принимают только
    места с ограничением попыток (``Misses``)."""
    code = str(code or "").strip()
    if CODE.match(code) and _h(code) in d:
        return _h(code)
    if not short:
        return None
    s = norm_short(code)
    if len(s) < 5:
        return None
    hs = _h("s:" + s)
    return next((k for k, v in d.items() if v.get("short") == hs), None)


def check(code: str, short: bool = True) -> dict | None:
    """Действующее приглашение (не использовано, не отозвано, срок не вышел) — по коду ссылки или (``short``)
    короткому; иначе None."""
    d = _load()
    k = _find(d, code, short)
    return d[k] if k and state(d[k]) == "active" else None


def redeem(code: str, uid: int, bind: bool = False) -> dict | None:
    """Использовать приглашение (один раз — и ссылка, и короткий код): запись помечается, возвращается
    {tenant, role, title?, uid?}; иначе None."""
    with _lock:
        d = _load()
        k = _find(d, code)
        rec = d.get(k) if k else None
        if not rec or state(rec) != "active":
            return None
        rec.update(used=int(uid), used_at=int(time.time()), n=rec.get("n", 0) + 1)
        if bind and "uid" not in rec:             # одна ссылка: следующие устройства — тот же человек
            rec["uid"], rec["person"] = int(uid), True
        _save(d)
    return {"tenant": rec["tenant"], "role": rec["role"], **({"uid": rec["uid"]} if "uid" in rec else {}),
            "access": rec.get("access", 0), "plan": rec.get("plan", "")}


def until_of(inv: dict, now: float | None = None) -> int | None:
    """Доступ человека по приглашению — до какого времени (``access`` дней), None — бессрочно."""
    days = int(inv.get("access") or 0)
    return int((time.time() if now is None else now) + days * 86400) if days else None


def drop_for(uid: int) -> int:
    """Отозвать все действующие ссылки для входа человека ``uid`` (его отключили). Возвращает, сколько."""
    n = 0
    with _lock:
        d = _load()
        for v in d.values():
            if v.get("uid") == int(uid) and state(v) == "active":
                v["revoked"], n = True, n + 1
        if n:
            _save(d)
    return n


def revoke(code_or_hint: str) -> str:
    """Отозвать по коду или по первым знакам (из списка). Возвращает первые знаки отозванного."""
    x = str(code_or_hint or "").strip()
    if len(x) < HINT:
        raise ValueError(f"укажите код или хотя бы {HINT} первых знаков")
    with _lock:
        d = _load()
        k = _find(d, x)                              # код ссылки или короткий код — точно; иначе первые знаки
        keys = [k] if k else [k for k, v in d.items() if v.get("hint") == x[:HINT]]
        if len(keys) != 1:
            raise ValueError("такого приглашения нет" if not keys else "несколько совпадений — укажите код целиком")
        d[keys[0]]["revoked"] = True
        _save(d)
        return d[keys[0]]["hint"]


def listing() -> list[dict]:
    now = time.time()
    return sorted(({"hint": v.get("hint", ""), "tenant": v.get("tenant", ""), "role": v.get("role", ""),
                    "state": state(v, now), "exp": v.get("exp", 0), "used": v.get("used"),
                    "uses": v.get("uses", 1), "n": v.get("n", 1 if v.get("used") else 0),
                    "access": v.get("access", 0), "plan": v.get("plan", ""),
                    "kind": "device" if "uid" in v and not v.get("person") else "invite",
                    "name": v.get("name", "")}
                   for v in _load().values()), key=lambda x: -x["exp"])


class Misses:
    """Перебор кодов на экране входа: с одного IP — не больше ``per_ip`` неверных попыток за ``window`` секунд,
    со всех вместе — не больше ``total`` (иначе короткий код можно было бы перебрать с разных адресов). Только в
    памяти: перезапуск панели счётчики обнуляет, а коды живут не дольше суток."""

    def __init__(self, per_ip: int = 5, window: int = 600, total: int = 30):
        self.per_ip, self.window, self.total = per_ip, window, total
        self.lock, self.seen = threading.Lock(), {}

    def _fresh(self, now: float):
        for ip in list(self.seen):
            self.seen[ip] = [t for t in self.seen[ip] if now - t < self.window]
            if not self.seen[ip]:
                del self.seen[ip]

    def blocked(self, ip: str) -> int:
        """0 — можно пробовать; иначе через сколько секунд."""
        now = time.time()
        with self.lock:
            self._fresh(now)
            mine = self.seen.get(ip, [])
            every = sorted(t for ts in self.seen.values() for t in ts)
            if len(mine) >= self.per_ip:
                return int(mine[0] + self.window - now) + 1
            if len(every) >= self.total:
                return int(every[0] + self.window - now) + 1
        return 0

    def miss(self, ip: str):
        with self.lock:
            self.seen.setdefault(ip, []).append(time.time())
