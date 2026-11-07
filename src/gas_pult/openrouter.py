"""OpenRouter: вход в одно касание (OAuth PKCE), состояние ключа и каталог моделей.

Вход: панель открывает ``openrouter.ai/auth`` с ``code_challenge`` (S256) и ``state``; человек входит в OpenRouter и
нажимает «Authorize»; OpenRouter возвращает браузер на ``<панель>/openrouter/callback?code=…&state=…``; сервер меняет
код на ключ (``POST /api/v1/auth/keys`` с ``code_verifier``) и сохраняет его как обычный ключ (secrets.json, 0600).
Ключ не проходит через браузер. ``state`` одноразовый, живёт 10 минут и выдаётся только владельцу панели —
без него обратный адрес ничего не делает.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from gas_pult import providers

AUTH = "https://openrouter.ai/auth"
EXCHANGE = "https://openrouter.ai/api/v1/auth/keys"
KEY_INFO = "https://openrouter.ai/api/v1/key"
MODELS = "https://openrouter.ai/api/v1/models"
TTL = 600                    # код OpenRouter живёт 10 минут — ссылка входа столько же
CALLBACK = "/openrouter/callback"


def _http(url: str, body: dict | None = None, key: str | None = None) -> dict:
    headers = {"Accept": "application/json", "User-Agent": "gas-pult"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data, headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        raise ValueError({401: "ключ не подошёл", 403: "код входа неверный или устарел — войдите ещё раз"}
                         .get(e.code, f"ошибка {e.code} {detail}")) from None
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise ValueError(f"OpenRouter недоступен: {e}") from None


def _per_million(v) -> float | None:
    return round(float(v) * 1e6, 2) if v not in (None, "") else None


def challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


class OpenRouter:
    def __init__(self):
        self.lock = threading.Lock()
        self.pending: dict[str, tuple[str, float]] = {}      # state → (code_verifier, когда выдан)
        self.catalog: tuple[float, list[dict]] = (0, [])

    def start(self, base_url: str) -> str:
        """Ссылка на вход в OpenRouter; после «Authorize» браузер вернётся на ``base_url`` + CALLBACK."""
        verifier, state = secrets.token_urlsafe(64), secrets.token_urlsafe(24)
        with self.lock:
            now = time.time()
            self.pending = {s: v for s, v in self.pending.items() if now - v[1] < TTL}
            self.pending[state] = (verifier, now)
        return AUTH + "?" + urllib.parse.urlencode({
            "callback_url": base_url.rstrip("/") + CALLBACK, "code_challenge": challenge(verifier),
            "code_challenge_method": "S256", "state": state, "key_label": "gas-pult"})

    def finish(self, code: str, state: str) -> str:
        """Код из обратного адреса → ключ OpenRouter. ``state`` гасится сразу — второй раз не сработает."""
        with self.lock:
            item = self.pending.pop(state, None)
        if not item or time.time() - item[1] > TTL:
            raise ValueError("ссылка входа устарела — нажмите «Войти через OpenRouter» ещё раз")
        if not code:
            raise ValueError("OpenRouter не прислал код — вход отменён?")
        key = _http(EXCHANGE, {"code": code, "code_verifier": item[0], "code_challenge_method": "S256"}).get("key")
        if not key:
            raise ValueError("OpenRouter не выдал ключ — попробуйте ещё раз")
        return key

    @staticmethod
    def info(key: str) -> dict:
        """Состояние ключа: подпись, расход, лимит и остаток (в долларах) — без секретов."""
        d = _http(KEY_INFO, key=key).get("data") or {}
        return {k: d.get(k) for k in ("label", "usage", "usage_monthly", "limit", "limit_remaining", "is_free_tier")}

    def models(self) -> list[dict]:
        """Каталог моделей OpenRouter (публичный, без ключа), кэш на час: id, название, контекст, цена за 1 млн."""
        with self.lock:
            if time.time() - self.catalog[0] < 3600 and self.catalog[1]:
                return self.catalog[1]
        out = []
        for m in _http(MODELS).get("data", []):
            if m.get("id", "").endswith(":batch"):
                continue                                    # пакетные варианты для интерактивной работы не нужны
            price = m.get("pricing") or {}
            out.append({"id": m["id"], "name": m.get("name", m["id"]), "ctx": m.get("context_length"),
                        "in": _per_million(price.get("prompt")), "out": _per_million(price.get("completion"))})
        with self.lock:
            self.catalog = (time.time(), out)
        return out


# ---------- фактическая цена ответов (задача 51) ----------
# Claude Code пишет в журнал у ответа OpenRouter ``requestId`` = id генерации («gen-<unix-время>-…»; в потоке
# ``claude -p`` — ``request_id``). По нему ``GET /api/v1/generation?id=…`` отдаёт ``total_cost`` — сколько списано
# за этот ответ. Это точнее оценки по токенам (замер 07.11: у DeepSeek V4 Pro оценка втрое ниже счёта) и делится
# по сессиям, в отличие от общего расхода ключа (``/api/v1/key``). Статистика появляется не сразу (несколько секунд —
# 404), поэтому спрашиваем в фоне с повторами; ответ не меняется — кэш на диске (``openrouter-costs.json``, 0600).
GENERATION = "https://openrouter.ai/api/v1/generation"
GEN_ID = re.compile(r"^gen-(\d{9,11})-[A-Za-z0-9]{6,64}$")


class NotYet(Exception):
    """Генерация ещё не посчитана (404) — спросить позже."""


class Billing:
    """Цена ответов OpenRouter по id генерации: кэш (память + диск) и фоновая докачка, без блокировки читателя.

    ``lookup(gen)`` — сразу из кэша: («provider», USD) или («wait», None) — поставлено в очередь, или («», None) —
    узнать не вышло (сдались). Узнали — ``on_cost(gen, usd | None)`` из фонового потока."""

    TIMEOUT = 10                 # с на запрос
    BATCH = 20                   # запросов за проход
    TRIES = 12                   # повторов до «не вышло» (~1,5 часа с ростом паузы)
    KEEP_DAYS = 120              # дольше в кэше не храним (по времени в id генерации)

    def __init__(self, path: Path | None = None, key=None, fetch=None, on_cost=None, autostart: bool = True):
        self.path = path
        self.key = key or (lambda: providers.load_keys().get("openrouter"))
        self.fetch = fetch or self._fetch
        self.on_cost = on_cost
        self.autostart = autostart
        self.known: dict[str, float | None] = {}
        self.queue: dict[str, list[float]] = {}          # gen → [когда спросить, сколько раз спрашивали]
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.mtime = -1.0
        self.hold = 0.0                                  # ключ не подошёл — пауза до этого времени

    def file(self) -> Path:
        if self.path is None:
            from gas_pult.config import data_dir
            self.path = data_dir() / "openrouter-costs.json"
        return self.path

    def _load(self) -> list[str]:
        """Подхватить кэш с диска (его пишет и другой процесс пульта); вернуть gen из очереди, что там нашлись."""
        try:
            m = self.file().stat().st_mtime
            if m == self.mtime:
                return []
            d = json.loads(self.file().read_text())
            self.mtime = m
        except (OSError, ValueError):
            return []
        got = []
        for g, v in (d if isinstance(d, dict) else {}).items():
            if g not in self.known and (v is None or isinstance(v, (int, float))):
                self.known[g] = v
                if g in self.queue:
                    got.append(g)
                    del self.queue[g]
        return got

    def _save(self):
        from gas_pult.config import write_private
        edge = time.time() - self.KEEP_DAYS * 86400
        keep = {g: v for g, v in self.known.items() if (m := GEN_ID.match(g)) and int(m.group(1)) >= edge}
        try:
            self.file().parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            write_private(self.file(), json.dumps(keep))
            self.mtime = self.file().stat().st_mtime
        except OSError:
            pass

    def lookup(self, gen: str) -> tuple[str, float | None]:
        if not GEN_ID.match(gen or ""):
            return "", None
        with self.lock:
            if gen not in self.known and not self.queue:
                self._load()
            if gen in self.known:
                v = self.known[gen]
                return ("provider", v) if v is not None else ("", None)
            self.queue.setdefault(gen, [time.time() + 3, 0])     # статистика появляется через пару секунд
            start = self.autostart and (self.thread is None or not self.thread.is_alive())
            if start:
                self.thread = threading.Thread(target=self._run, name="openrouter-billing", daemon=True)
        if start:
            self.thread.start()
        return "wait", None

    def _run(self):
        while True:
            with self.lock:
                if not self.queue:
                    self.thread = None
                    return
            self.step()
            time.sleep(2)

    def step(self, now: float | None = None) -> dict[str, float | None]:
        """Один проход очереди: до BATCH запросов, чьё время пришло. Возвращает узнанное {gen: usd | None}."""
        now = time.time() if now is None else now
        with self.lock:
            done: dict[str, float | None] = {g: self.known[g] for g in self._load()}
            due = [g for g, (at, _) in self.queue.items() if at <= now][:self.BATCH]
        key = self.key() if due and now >= self.hold else None
        if due and not key:                               # ключа нет или не подошёл — ждём, повторы не тратим
            with self.lock:
                for g in due:
                    if g in self.queue:
                        self.queue[g][0] = now + 300
            due = []
        fetched = False
        for g in due:
            try:
                usd: float | None = self.fetch(g, key)
            except NotYet:
                with self.lock:
                    q = self.queue.get(g)
                    if q is not None:
                        q[1] += 1
                        if q[1] < self.TRIES:
                            q[0] = now + min(600, 5 * 2 ** q[1])
                            continue
                usd = None                                # так и не появилась — «не вышло»
            except PermissionError:
                self.hold = now + 600
                with self.lock:
                    for x in due:
                        if x in self.queue:
                            self.queue[x][0] = self.hold
                break
            except (OSError, ValueError):                 # сеть, таймаут, странный ответ — позже, как «ещё нет»
                with self.lock:
                    if (q := self.queue.get(g)) is not None:
                        q[1] += 1
                        if q[1] < self.TRIES:
                            q[0] = now + min(600, 5 * 2 ** q[1])
                            continue
                usd = None
            with self.lock:
                self.known[g] = usd
                self.queue.pop(g, None)
            done[g] = usd
            fetched = True
        if fetched:
            with self.lock:
                self._save()
        for g, usd in done.items():
            if self.on_cost:
                self.on_cost(g, usd)
        return done

    def _fetch(self, gen: str, key: str) -> float:
        """Цена одной генерации; ключ — только в заголовке (в ошибки и журналы не попадает)."""
        req = urllib.request.Request(GENERATION + "?" + urllib.parse.urlencode({"id": gen}),
                                     headers={"Authorization": f"Bearer {key}", "Accept": "application/json",
                                              "User-Agent": "gas-pult"})
        try:
            with urllib.request.urlopen(req, timeout=self.TIMEOUT) as r:
                d = json.load(r).get("data") or {}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NotYet from None
            if e.code in (401, 403):
                raise PermissionError(e.code) from None
            raise OSError(f"OpenRouter: ошибка {e.code}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise OSError("OpenRouter недоступен") from e
        v = d.get("total_cost")
        if not isinstance(v, (int, float)):
            raise NotYet
        return float(v)
