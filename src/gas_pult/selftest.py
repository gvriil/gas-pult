"""Автотест профилей моделей (задача 38): раз в сутки и по кнопке «Проверить сейчас».

Для каждого поставщика с ключом (и адресом шлюза, если он нужен) — один короткий ``claude -p`` во временной папке
со своим ``CLAUDE.md`` (кодовое слово) и файлом ``probe.txt`` (случайная строка). Проверяем четыре вещи:

- ``memory`` — модель назвала кодовое слово из ``CLAUDE.md`` (правила проекта доходят до модели);
- ``tools`` — Claude Code отдал модели список инструментов (событие ``init`` в ``stream-json``);
- ``tool`` — модель вызвала Read и вернула строку из ``probe.txt`` (её не угадать — значит, вызов настоящий);
- ``webfetch`` — модель вызвала WebFetch, инструмент вернул страницу без ошибки, в ответе — её заголовок.

Затраты минимальные: один запрос в несколько ходов (``--max-turns``), потолок ``--max-budget-usd``, без MCP-серверов
(``--strict-mcp-config``), без хуков и настроек пользователя (``--setting-sources project,local``), без журнала сессии
(``--no-session-persistence``). Ключ — в файле настроек профиля (``models.command``), в аргументах его нет.
Итог — ``<data>/selftest.json``: когда, что прошло, что нет; панель показывает его в «Настройки» → «Поставщики».
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from gas_pult import models
from gas_pult.config import write_private

CHECKS = ("memory", "tools", "tool", "webfetch")
DAY = 24 * 3600
STALE = 30 * 60                     # «идёт проверка» дольше получаса — процесс умер, начинаем заново
TIMEOUT = 240                       # с на одного поставщика
MAX_TURNS = 6
MAX_USD = "0.50"
FETCH_URL = "https://example.com/"
FETCH_TITLE = "Example Domain"
WORDS = ("кедр", "янтарь", "маяк", "гранат", "ольха", "сокол", "бархан", "ирис")
PROMPT = f"""Это автоматическая проверка пульта. Сделай по шагам и ответь ровно тремя строками, без пояснений:
CODEWORD: <кодовое слово из CLAUDE.md этой папки>
FILE: <содержимое файла probe.txt в этой папке — прочитай его инструментом Read>
FETCH: <заголовок страницы {FETCH_URL} — получи его инструментом WebFetch>"""
LINE = re.compile(r"^[\s*>`_-]*(CODEWORD|FILE|FETCH)[\s*_`]*:\s*(.*?)[\s*_`]*$", re.M | re.I)
_lock = threading.Lock()


def path(data: Path) -> Path:
    return data / "selftest.json"


def load(data: Path) -> dict:
    try:
        d = json.loads(path(data).read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data: Path, d: dict):
    write_private(path(data), json.dumps(d, ensure_ascii=False))


def targets(state: dict, keys: dict | None = None) -> list[str]:
    """Кого проверять: поставщики с ключом и (у шлюзов) адресом. «Claude» — подписка владельца, не проверяем."""
    return [p["id"] for p in models.PROFILES if p.get("key") and models.has_key(p["id"], keys)
            and models.has_gateway(p["id"], state)]


def running(d: dict, now: float | None = None) -> bool:
    return bool(d.get("running")) and (now or time.time()) - d["running"] < STALE


def due(data: Path, state: dict, now: float | None = None, keys: dict | None = None) -> bool:
    """Пора ли суточной проверке: есть кого проверять, сейчас не идёт, прошлой не было сутки."""
    now = now or time.time()
    d = load(data)
    return bool(targets(state, keys)) and not running(d, now) and now - d.get("t", 0) >= DAY


def parse(out: str) -> dict:
    """``stream-json`` Claude Code → инструменты, вызовы, ошибки инструментов, итоговый текст, расход."""
    r = {"tools": [], "calls": [], "errors": [], "text": "", "cost": None, "error": ""}
    ids: dict[str, str] = {}
    for line in out.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        if e.get("type") == "system" and e.get("subtype") == "init":
            r["tools"] = [str(t) for t in e.get("tools") or []]
        for c in ((e.get("message") or {}).get("content") or []) if e.get("type") in ("assistant", "user") else []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use":
                r["calls"].append(str(c.get("name", "")))
                ids[str(c.get("id", ""))] = str(c.get("name", ""))
            elif c.get("type") == "tool_result" and c.get("is_error"):
                r["errors"].append(ids.get(str(c.get("tool_use_id", "")), "?"))
        if e.get("type") == "result":
            r["text"] = str(e.get("result") or "")
            r["cost"] = e.get("total_cost_usd")
            if e.get("is_error") or e.get("subtype") not in (None, "success"):
                r["error"] = str(e.get("result") or e.get("subtype") or "ошибка")[:200]
    return r


def judge(r: dict, word: str, token: str) -> dict:
    """Что прошло: кодовое слово, список инструментов, настоящий вызов Read, WebFetch без ошибки."""
    ans = {m.group(1).upper(): m.group(2).strip() for m in LINE.finditer(r["text"])}
    return {"memory": word.lower() in ans.get("CODEWORD", "").lower(),
            "tools": len(r["tools"]) >= 3 and "Read" in r["tools"],
            "tool": "Read" in r["calls"] and "Read" not in r["errors"] and token in ans.get("FILE", ""),
            "webfetch": "WebFetch" in r["calls"] and "WebFetch" not in r["errors"]
                        and FETCH_TITLE.lower() in ans.get("FETCH", "").lower()}


def run_one(profile: str, state: dict, run=subprocess.run, base: str = "claude") -> dict:
    """Один поставщик: временная папка с CLAUDE.md и probe.txt → ``claude -p`` → итог по четырём проверкам."""
    t0 = time.time()
    word, token = secrets.choice(WORDS) + str(secrets.randbelow(900) + 100), secrets.token_hex(6)
    out = {"t": int(t0), "checks": dict.fromkeys(CHECKS, False), "error": "", "cost": None, "secs": 0,
           "websearch_tool": False}
    work = Path(tempfile.mkdtemp(prefix="gp-selftest-"))
    try:
        (work / "CLAUDE.md").write_text(f"# Проверка пульта\n\nКодовое слово проекта: {word}\n", encoding="utf-8")
        (work / "probe.txt").write_text(token + "\n", encoding="utf-8")
        try:
            cmd = shlex.split(models.command(base, profile, state))
        except ValueError as e:
            return out | {"error": str(e)[:200]}
        cmd += ["-p", "--output-format", "stream-json", "--verbose", "--max-turns", str(MAX_TURNS),
                "--max-budget-usd", MAX_USD, "--no-session-persistence", "--strict-mcp-config",
                "--setting-sources", "project,local",
                "--allowedTools", f"Read,WebFetch(domain:{FETCH_URL.split('/')[2]})"]
        try:
            p = run(cmd, input=PROMPT, capture_output=True, text=True, timeout=TIMEOUT, cwd=str(work),
                    env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
        except FileNotFoundError:
            return out | {"error": "Claude Code не установлен"}
        except subprocess.TimeoutExpired:
            return out | {"error": f"нет ответа за {TIMEOUT} с", "secs": int(time.time() - t0)}
        r = parse(p.stdout or "")
        err = r["error"] or ("" if p.returncode == 0 else
                             ((p.stderr or "").strip().splitlines() or [f"код {p.returncode}"])[-1][:200])
        return out | {"checks": judge(r, word, token), "error": err, "cost": r["cost"],
                      "secs": int(time.time() - t0), "websearch_tool": "WebSearch" in r["tools"]}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_all(data: Path, state: dict, run=subprocess.run, only: list[str] | None = None) -> dict:
    """Проверить всех (или ``only``); одновременно — одна проверка (замок в процессе и отметка в файле для бота и
    панели). Уже идёт — вернуть как есть."""
    with _lock:
        d = load(data)
        if running(d):
            return d
        d["running"] = int(time.time())
        save(data, d)
    res = dict(d.get("results") or {})
    final = {**{k: v for k, v in d.items() if k != "running"}, "results": res}
    try:
        for pid in only or targets(state):
            res[pid] = run_one(pid, state, run)
            save(data, {**d, "results": res})            # панель видит прогресс по одному
        final["t"] = int(time.time())
    finally:
        save(data, final)                                # и при сбое: снять «идёт», сохранить сделанное
    return final


def start(data: Path, state: dict, run=subprocess.run) -> bool:
    """«Проверить сейчас» — в фоне; False — проверка уже идёт."""
    if running(load(data)):
        return False
    threading.Thread(target=run_all, args=(data, state, run), daemon=True).start()
    return True


def public(data: Path, state: dict) -> dict:
    """Для панели: когда, идёт ли, по каждому поставщику с ключом — итог (или «ещё не проверялся»)."""
    d = load(data)
    res = d.get("results") or {}
    out = []
    for pid in targets(state):
        p = models.BY_ID[pid]
        r = res.get(pid) or {}
        out.append({"id": pid, "title": p["title"], "t": r.get("t"), "checks": r.get("checks") or {},
                    "ok": bool(r) and all((r.get("checks") or {}).get(c) for c in CHECKS),
                    "error": r.get("error", ""), "cost": r.get("cost"), "secs": r.get("secs"),
                    "websearch_tool": bool(r.get("websearch_tool"))})
    return {"t": d.get("t"), "running": running(d), "checks": list(CHECKS), "every": DAY, "profiles": out}


NAMES = {"memory": "правила из CLAUDE.md", "tools": "список инструментов", "tool": "вызов инструмента",
         "webfetch": "WebFetch"}


def summary(data: Path, state: dict) -> str:
    """Текст для бота: по строке на поставщика."""
    d = public(data, state)
    if not d["profiles"]:
        return "Проверять некого: нет ключей других поставщиков («Интеграции» → «Модели»)."
    lines = ["🧪 Проверка поставщиков:"]
    for p in d["profiles"]:
        if not p["t"]:
            lines.append(f"• {p['title']}: ещё не проверялся")
            continue
        bad = [NAMES[c] for c in CHECKS if not p["checks"].get(c)]
        lines.append(f"• {p['title']}: " + ("✅ всё работает" if not bad else "❌ не прошло: " + ", ".join(bad))
                     + (f" ({p['error']})" if p["error"] else ""))
    return "\n".join(lines)
