"""Роутер моделей (GAS-16, слой 6 «кэш и роутер»; владелец 17.11: «примени всё на вооружение»).

Тип задачи — по первому сообщению нового чата (ключевые слова, без вызова модели) → основная модель и запасная по
правилам штаба ``portfolio-hq/harness/profiles/routing.md`` (замер 17 моделей, 17.11.2026). Пульт только
**подсказывает**: в «Новом чате» над полем — «Подходит: Haiku — рутина в браузере»; нажал — чат запустится с ней.
Сам ничего не переключает: модель и расход решает человек.

Запасная — через OpenRouter, только если профиль готов (ключ есть). Данные Google и личные данные — только модели,
которые на них не учатся (Google API Limited Use): запасной у этого типа нет, если нет API Anthropic.

Кэш одинаковых вопросов — ``Repeat``: тот же длинный текст в ту же сессию за ``REPEAT_MIN`` минут не уходит сразу
(ответ уже выше) — пульт предупреждает; повторная отправка в течение ``CONFIRM_S`` секунд уходит.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time

# (id, название, слова, основная (профиль, модель), запасная (профиль, модель) | None, почему)
RULES = [
    ("google", "данные Google и личные данные",
     r"google|гугл|диск[аеу]?\b|drive|таблиц|календар|gmail|почт|паспорт|снилс|персональн|личн\w+ данн",
     ("claude", "haiku"), None,
     "Limited Use: только поставщики, которые не учатся на данных; DeepSeek напрямую и «:free» — нельзя"),
    ("code", "код", r"\bкод|функци|баг|ошибк\w* в|тест|рефактор|python|javascript|typescript|\bsql\b|\bapi\b|"
                    r"репозитор|pull request|\bpr\b|commit|деплой|сборк",
     ("claude", "sonnet"), ("openrouter", "deepseek/deepseek-v4-flash-0731"),
     "Sonnet — сильнее в коде; V4 Flash 17/18 за $0.06"),
    ("explore", "разведка сайта, разбор сбоя", r"разбер|почему не|не работает|сломал|сбой|упал|разведк|"
                                                 r"незнаком\w* сайт|выясни|расследу",
     ("claude", "sonnet"), ("openrouter", "openai/gpt-6.1-terra"), "разведка — по силе модели: 24/24 и 16/16"),
    ("browser", "рутина в браузере", r"браузер|сайт|страниц|зайди|открой|заполни|форм[ауы]|кликни|авито|озон|"
                                     r"wildberries|скачай|выгрузи",
     ("claude", "haiku"), ("openrouter", "xiaomi/mimo-v2.6-flash"), "80/80 и 16/16, ≈ $0.04 за 8 задач"),
    ("text", "длинный текст, сводка", r"свод|кратк|перескаж|резюм|протокол|статью|текст|перевед|письмо|"
                                      r"отчёт|отчет|расшифров",
     ("claude", "haiku"), ("openrouter", "tencent/hy3"), "Haiku 17/18; hy3 не нарушает политику в ответе клиенту"),
]
_RX = [(r[0], re.compile(r[2], re.I)) for r in RULES]
BY_ID = {r[0]: r for r in RULES}
NAMES = {"haiku": "Haiku 5.5", "sonnet": "Sonnet 5.5"}


def classify(text: str) -> str | None:
    """Тип задачи по тексту: первое правило по порядку (данные Google — раньше всех: это ограничение, а не вкус)."""
    t = str(text or "")
    return next((rid for rid, rx in _RX if rx.search(t)), None)


def route(text: str, ready: set[str] | frozenset[str]) -> dict | None:
    """Подсказка: {type, title, profile, model, name, fallback?, why} или None (тип не понятен / нечего предложить).
    ``ready`` — профили, готовые к запуску (ключ есть, страна разрешена, баланс)."""
    rid = classify(text)
    if not rid:
        return None
    _, title, _, main, fb, why = BY_ID[rid]
    pick = main if main[0] in ready else fb if fb and fb[0] in ready else None
    if not pick:
        return None
    out = {"type": rid, "title": title, "profile": pick[0], "model": pick[1],
           "name": NAMES.get(pick[1], pick[1].split("/")[-1]), "why": why}
    if pick == main and fb and fb[0] in ready:
        out["fallback"] = {"profile": fb[0], "model": fb[1], "name": fb[1].split("/")[-1]}
    return out


MODEL_RX = re.compile(r"^[A-Za-z0-9._:/\[\]-]{1,80}$")


def valid_model(m: str) -> str:
    m = str(m or "").strip()
    if m and not MODEL_RX.match(m):
        raise ValueError("непонятное имя модели")
    return m


REPEAT_MIN = 10          # тот же вопрос в ту же сессию — подождать ответа выше
CONFIRM_S = 120          # повторная отправка после предупреждения — уходит
MIN_LEN = 40             # короткие («да», «продолжай») повторяются честно — не трогаем


class Repeat:
    """Кэш одинаковых вопросов: только хэши текста и время, в памяти."""

    def __init__(self):
        self.lock, self.sent, self.warned = threading.Lock(), {}, {}

    @staticmethod
    def _key(wid: str, text: str) -> str:
        return wid + ":" + hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest()[:24]

    def check(self, wid: str, text: str, now: float | None = None, mid: str = "") -> int | None:
        """Сколько секунд назад был тот же вопрос (и предупреждения ещё не было) — или None: можно отправлять.
        ``mid`` — id сообщения браузера: повтор того же запроса после обрыва связи — не «тот же вопрос»."""
        if len(text.strip()) < MIN_LEN:
            return None
        now = time.time() if now is None else now
        k = self._key(wid, text)
        with self.lock:
            for x in [x for x, (t, _) in self.sent.items() if now - t > REPEAT_MIN * 60]:
                del self.sent[x]
            for x in [x for x, t in self.warned.items() if now - t > CONFIRM_S]:
                del self.warned[x]
            if k in self.sent and mid and self.sent[k][1] == mid:
                return None
            if k in self.warned:                     # человек повторил после предупреждения — отправляем
                del self.warned[k]
                return None
            if k in self.sent:
                self.warned[k] = now
                return int(now - self.sent[k][0])
        return None

    def done(self, wid: str, text: str, now: float | None = None, mid: str = ""):
        if len(text.strip()) >= MIN_LEN:
            with self.lock:
                self.sent[self._key(wid, text)] = (time.time() if now is None else now, mid)
