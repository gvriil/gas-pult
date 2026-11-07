"""Живая строка статуса сессии: что агент делает сейчас — по хвосту журнала Claude Code и экрану окна.

Фазы (поле ``phase``):

- ``sent`` — «Отправлено»: пульт вставляет текст в окно;
- ``delivered`` — «Доставлено в сессию»: вставка прошла, ход ещё не начался;
- ``queued`` — прошло 20 с, нового хода нет, а окно занято прошлой задачей — «сообщение в очереди»;
- ``stuck`` — прошло 20 с, нового хода нет и окно свободно — «не видно реакции» (кнопка «Экран»);
- ``started`` — «Взял в работу»: в журнале новый запрос, Claude ещё ничего не сделал;
- ``working`` — выполняет инструмент: «Читает файл X», «Выполняет команду …» (``tool`` — имя инструмента);
- ``thinking`` — «Думает…»: ход идёт, инструмента сейчас нет;
- ``waiting`` — «Ждёт вашего ответа»: вопрос или меню на экране (кнопка «Ответить»);
- ``done`` — «Готово»; ``idle`` — ничего не происходит.

``since`` — с какого момента (Unix-время) идёт фаза: от него панель и бот считают таймер «12 с».
Только стандартная библиотека; журнал читается с хвоста, разбор кэшируется по (файл, размер, время).
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

from gas_pult import transcripts

TAIL = 262144                     # байт хвоста журнала: последнего хода хватает с запасом
NO_REACTION = 20                  # с после «Доставлено» без нового хода — честно сказать почему
KEEP = 900                        # с: запись об отправке живёт 15 минут
STALE = 15                        # с: журнал говорит «ход идёт», а экран — «свободно» дольше этого — ход прерван

TEXTS = {"sent": "Отправлено", "delivered": "Доставлено в сессию", "started": "Взял в работу",
         "thinking": "Думает…", "waiting": "Ждёт вашего ответа", "done": "Готово", "idle": "",
         "queued": "Занят предыдущей задачей — в очереди",
         "stuck": "Не видно реакции — показать экран?"}
ACTIVE = {"sent", "delivered", "started", "working", "thinking", "queued"}     # ход идёт или вот-вот начнётся

# ---------- маскировка: в строке статуса не должно быть секретов ----------
SECRET_KEY = r"[A-Za-z0-9_.-]*(?:token|secret|passw(?:or)?d|pass|pwd|api[_-]?key|apikey|auth|credential|cookie|" \
             r"session|private|key)[A-Za-z0-9_.-]*"
MASKS = [
    (re.compile(r"(://)[^/\s:@]+:[^/\s@]+@"), r"\1***@"),                                   # https://user:pass@
    (re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 ***"),        # Authorization: Bearer …
    (re.compile(r"(?i)(" + SECRET_KEY + r")(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)"), r"\1\2***"),   # token=…, KEY: …
    (re.compile(r"\b([A-Z][A-Z0-9_]{2,})=(\"[^\"]*\"|'[^']*'|\S+)"), r"\1=***"),           # ENV_VAR=… перед командой
    (re.compile(r"(?i)(--?[a-z-]*(?:token|secret|password|passwd|key|auth)[a-z-]*)(\s+|=)(\S+)"), r"\1\2***"),
    (re.compile(r"\b(?:sk|pk|rk|ghp|gho|ghs|github_pat|xox[abposr]|glpat|AKIA|AIza)[-_A-Za-z0-9]{8,}"), "***"),
    (re.compile(r"\b(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[A-Za-z])[A-Za-z0-9_\-]{32,}\b"), "***"),   # длинные ключи
    (re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}"), "***"),                                    # токен бота Telegram
]


def mask(text: str) -> str:
    """Скрыть то, что похоже на секрет: значения после ``token=``/``KEY=``, пароли в адресах, длинные ключи."""
    for rx, repl in MASKS:
        text = rx.sub(repl, text)
    return text


def clip(text: str, limit: int = 40) -> str:
    """Одна строка, не длиннее ``limit`` знаков (с «…»)."""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def base(path: str) -> str:
    return clip(Path(str(path).rstrip("/")).name or str(path), 48)


def domain(url: str) -> str:
    """Только домен ссылки: путь и параметры могут содержать ключи."""
    try:
        host = urllib.parse.urlsplit(str(url).strip()).hostname or ""
    except ValueError:
        host = ""
    return host.removeprefix("www.") or "сайт"


def mcp_server(name: str) -> str:
    """mcp__claude_ai_Notion__notion-search → «Notion»; mcp__github__get_me → «github»."""
    server = name.split("__")[1] if name.count("__") >= 2 else name.removeprefix("mcp__")
    server = re.sub(r"^(claude_ai_|plugin_[a-z0-9-]+_)", "", server)
    return clip(server.replace("_", " ").strip() or "сервисом", 30)


def describe(name: str, arg: dict | None) -> str:
    """Инструмент Claude Code и его входные данные → что агент делает, человеческими словами."""
    a = arg if isinstance(arg, dict) else {}
    if name == "Read":
        return f"Читает файл {base(a.get('file_path', ''))}"
    if name in ("Edit", "MultiEdit"):
        return f"Правит файл {base(a.get('file_path', ''))}"
    if name == "Write":
        return f"Создаёт файл {base(a.get('file_path', ''))}"
    if name == "NotebookEdit":
        return f"Правит файл {base(a.get('notebook_path') or a.get('file_path', ''))}"
    if name in ("Grep", "Glob"):
        return f"Ищет в коде: {clip(mask(str(a.get('pattern', ''))), 40)}"
    if name == "WebSearch":
        return f"Ищет в интернете: {clip(mask(str(a.get('query', ''))), 50)}"
    if name == "WebFetch":
        return f"Открывает ссылку {domain(a.get('url', ''))}"
    if name in ("Bash", "PowerShell"):
        what = a.get("description") or a.get("command") or ""
        return f"Выполняет команду: {clip(mask(str(what)), 50)}" if what else "Выполняет команду"
    if name in ("Task", "Agent"):
        what = a.get("description") or ""
        return f"Запустил помощника: {clip(mask(str(what)), 40)}" if what else "Запустил помощника"
    if name in ("TodoWrite", "TaskCreate", "TaskUpdate"):
        return "Обновляет план"
    if name in ("AskUserQuestion", "ExitPlanMode"):
        return TEXTS["waiting"]
    if name == "Skill":
        return f"Использует навык {clip(str(a.get('skill', '')), 30)}".strip()
    if name.startswith("mcp__"):
        return f"Работает с {mcp_server(name)}"
    return f"Работает: {clip(name, 30)}"


# ---------- разбор журнала ----------
def stamp(ts: str) -> float:
    """ISO-время журнала («2026-11-02T10:00:00.123Z») → Unix-время; не разобрали — 0."""
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _blocks(e: dict) -> list[dict]:
    c = (e.get("message") or {}).get("content")
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def parse(entries, subagent: dict | None = None) -> dict:
    """Записи журнала (по порядку) → статус последнего хода.

    Ответ: ``phase`` (working, thinking, waiting, started, done, idle), ``text``, ``tool``, ``since``;
    служебные ``turn`` (когда начался ход), ``last`` (время последней записи), ``said`` (последний текст агента),
    ``prompt`` (отпечаток запроса),
    ``queued`` (сколько сообщений ждёт в очереди Claude Code). ``subagent`` — статус помощника (его журнал), если он
    сейчас работает: добавляется к «Запустил помощника».
    """
    turn = last = enq = picked = said = 0.0
    prompt, done, queued, state = "", True, 0, "idle"
    open_tools: dict[str, tuple[str, dict, float]] = {}
    for e in entries:
        if not isinstance(e, dict) or e.get("isSidechain"):
            continue
        kind, ts = e.get("type"), stamp(e.get("timestamp", ""))
        # сообщение, отправленное во время хода, Claude Code ставит в очередь (enqueue) и забирает по ходу работы
        # (remove/dequeue + attachment queued_command) или следующим ходом
        if kind == "queue-operation":
            op = e.get("operation")
            if op == "enqueue":
                queued, enq = queued + 1, ts or enq
            elif op in ("dequeue", "remove"):
                queued, picked = max(0, queued - 1), ts or picked
            continue
        if kind == "attachment" and (e.get("attachment") or {}).get("type") == "queued_command":
            picked = max(picked, ts)
            continue
        if kind == "system" and e.get("subtype") == "turn_duration":
            done, state, open_tools = True, "done", {}
            last = ts or last
            continue
        if kind == "user":
            blocks = _blocks(e)
            results = [b.get("tool_use_id") for b in blocks if b.get("type") == "tool_result"]
            if results:
                for r in results:
                    open_tools.pop(r, None)
                last, state = ts or last, "thinking"
                continue
            text = transcripts.text_of((e.get("message") or {}).get("content")).strip()
            if text.startswith("[Request interrupted"):
                done, state, open_tools, last = True, "done", {}, ts or last
                continue
            if transcripts.is_real_prompt(e):
                turn = last = ts or last
                prompt = fingerprint(text)
                done, state, open_tools = False, "started", {}
            continue
        if kind != "assistant":
            continue
        last = ts or last
        msg = e.get("message") or {}
        blocks = _blocks(e)
        for b in blocks:
            if b.get("type") == "tool_use":
                open_tools[str(b.get("id"))] = (str(b.get("name", "")), b.get("input") or {}, ts)
                state = "tool"
            elif b.get("type") in ("thinking", "redacted_thinking"):
                state = "thinking"
            elif b.get("type") == "text":
                state, said = "text", ts or said
        done = False
        # конец хода: end_turn у записи с текстом (у «размышления» того же ответа stop_reason тоже end_turn)
        kinds = {b.get("type") for b in blocks}
        if msg.get("stop_reason") in ("end_turn", "stop_sequence") and kinds - {"thinking"} and "tool_use" not in kinds:
            done, state, open_tools = True, "done", {}
    out = {"turn": turn, "last": last, "said": said, "prompt": prompt, "queued": queued, "enq": enq, "picked": picked,
           "tool": ""}
    if not turn and not last:
        return {**out, "phase": "idle", "text": "", "since": 0.0}
    if done:
        return {**out, "phase": "done", "text": TEXTS["done"], "since": last}
    if open_tools:
        name, arg, ts = list(open_tools.values())[-1]
        text = describe(name, arg)
        phase = "waiting" if name in ("AskUserQuestion", "ExitPlanMode") else "working"
        if name in ("Task", "Agent") and subagent and subagent.get("phase") == "working":
            text = clip(f"{text} · {subagent['text']}", 90)
        return {**out, "phase": phase, "text": text, "tool": name, "since": ts or last}
    if state == "started":
        return {**out, "phase": "started", "text": TEXTS["started"], "since": turn}
    return {**out, "phase": "thinking", "text": TEXTS["thinking"], "since": last}


def fingerprint(text: str) -> str:
    """Отпечаток текста запроса: сравнить «наше ли это сообщение», не храня сам текст."""
    norm = " ".join(transcripts.PASTED.sub("", str(text)).split())
    return hashlib.sha1(norm.encode()).hexdigest()[:12]


def read_tail(f: Path, tail: int = TAIL) -> list[dict]:
    with open(f, "rb") as fh:
        start = max(0, fh.seek(0, 2) - tail)
        fh.seek(start)
        lines = fh.read().decode("utf-8", "replace").splitlines()[1 if start else 0:]   # первая — обрывок
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


class Journal:
    """Разбор хвоста журнала с кэшем по (файл, размер, время): опрос раз в 1,5 с не перечитывает файл зря."""

    def __init__(self):
        self.cache: dict[str, tuple[tuple, dict]] = {}
        self.lock = threading.Lock()

    def _parsed(self, f: Path, sub: dict | None = None) -> dict:
        st = f.stat()
        key = (st.st_size, st.st_mtime_ns, json.dumps(sub, sort_keys=True) if sub else "")
        with self.lock:
            hit = self.cache.get(str(f))
            if hit and hit[0] == key:
                return hit[1]
        res = parse(read_tail(f), sub)
        with self.lock:
            if len(self.cache) > 200:
                self.cache.clear()
            self.cache[str(f)] = (key, res)
        return res

    def status(self, path: str, home: Path | None = None, sid: str = "") -> dict:
        """Статус журнала сессии: окно с ``sid`` — его журнал, иначе последний журнал папки ``path`` (у участника — в
        его папке Claude ``home``)."""
        f = transcripts.current(path, home, sid)
        if not f:
            return parse([])
        sub = None
        subs = sorted((f.with_suffix("") / "subagents").glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        if subs and time.time() - subs[-1].stat().st_mtime < 120:   # помощник пишет сейчас — что он делает
            s = self._parsed(subs[-1])
            sub = {"phase": s["phase"], "text": s["text"]} if s["phase"] == "working" else None
        return self._parsed(f, sub)


# ---------- экран ----------
SPINNER = re.compile(r"^\s*[✻✶✳✢✽·*●]\s+([A-Za-zА-Яа-яЁё][\w\s'-]{0,30}?(?:…|\.\.\.))")
TIMER = re.compile(r"\((\d+[smh](?:\s*\d+[sm])?)\b")


def spinner(lines: list[str]) -> str:
    """Текст спиннера Claude Code с экрана: «✻ Pondering… (12s · esc to interrupt)» → «Pondering… · 12s»."""
    for line in reversed(lines[-15:]):
        if m := SPINNER.search(line):
            word = m.group(1).strip()
            t = TIMER.search(line)
            return clip(word + (f" · {t.group(1)}" if t else ""), 40)
    return ""


# ---------- фазы до хода: отправлено → доставлено → взял в работу ----------
class Sends:
    """Что и когда отправили в окно (только в памяти процесса): фазы до того, как ход появится в журнале."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.items: dict[str, dict] = {}
        self.lock = threading.Lock()

    def sent(self, wid: str, text: str) -> dict:
        now = self.clock()
        with self.lock:
            for k in [k for k, v in self.items.items() if now - v["sent_at"] > KEEP]:
                del self.items[k]
            rec = {"sent_at": now, "hash": fingerprint(text), "delivered_at": None}
            self.items[wid] = rec
            return rec

    def delivered(self, wid: str):
        with self.lock:
            if rec := self.items.get(wid):
                rec["delivered_at"] = self.clock()

    def failed(self, wid: str):
        with self.lock:
            self.items.pop(wid, None)

    def get(self, wid: str) -> dict | None:
        with self.lock:
            rec = self.items.get(wid)
            if rec and self.clock() - rec["sent_at"] > KEEP:
                self.items.pop(wid, None)
                return None
            return dict(rec) if rec else None

    def taken(self, wid: str):
        with self.lock:
            self.items.pop(wid, None)


def combine(journal: dict, rec: dict | None = None, screen: dict | None = None,
            now: float | None = None, sends: Sends | None = None, wid: str = "") -> dict:
    """Журнал + запись об отправке + экран → статус для панели и бота.

    ``screen``: ``{"busy": bool, "dialog": bool, "spinner": str}`` — экран окна (может не быть).
    ``sends``/``wid`` — если запрос уже в журнале, запись об отправке снимается (дальше — только журнал).
    """
    now = time.time() if now is None else now
    scr = screen or {}
    res = {k: journal.get(k) for k in ("phase", "text", "tool", "since")}
    res["queued"] = journal.get("queued", 0)
    if rec:
        sent = rec["sent_at"]
        # ход начался после отправки (часы журнала и пульта — одной машины; 2 с — на запись строки)
        took = (journal.get("turn", 0) >= sent - 2 or journal.get("picked", 0) >= sent - 2
                or (rec["hash"] and journal.get("prompt") == rec["hash"] and journal.get("turn", 0) >= sent - 60))
        if took:
            if sends is not None and wid:
                sends.taken(wid)
            rec = None
        elif not rec.get("delivered_at"):
            res |= {"phase": "sent", "text": TEXTS["sent"], "tool": "", "since": sent}
        elif journal.get("enq", 0) >= sent - 2 and journal.get("queued", 0) > 0:     # Claude Code поставил в очередь
            res |= {"phase": "queued", "text": TEXTS["queued"], "tool": "", "since": journal["enq"]}
        elif now - rec["delivered_at"] < NO_REACTION:
            res |= {"phase": "delivered", "text": TEXTS["delivered"], "tool": "", "since": rec["delivered_at"]}
        else:
            busy = scr.get("busy") or journal.get("phase") in ("working", "thinking", "started") \
                or journal.get("queued", 0) > 0
            phase = "queued" if busy else "stuck"
            res |= {"phase": phase, "text": TEXTS[phase], "tool": "", "since": rec["delivered_at"],
                    "action": "screen" if phase == "stuck" else ""}
    if scr.get("dialog"):                          # вопрос или меню на экране — главное, что нужно знать
        return {**res, "phase": "waiting", "text": TEXTS["waiting"], "tool": "", "action": "answer",
                "since": res.get("since") or now, "spinner": ""}
    if res["phase"] == "waiting":
        res["action"] = "answer"
    # журнал говорит «ход идёт», а на экране давно нет «esc to interrupt» — ход прерван (Esc, сбой поставщика)
    if (not rec and screen is not None and res["phase"] in ("working", "thinking", "started") and not scr.get("busy")
            and now - (journal.get("last") or 0) > STALE):
        res |= {"phase": "done", "text": TEXTS["done"], "tool": "", "since": journal.get("last") or now}
    res["spinner"] = scr.get("spinner", "") if res["phase"] in ("working", "thinking", "started") else ""
    res.setdefault("action", "")
    res["now"] = now
    return res


def elapsed(sec: float) -> str:
    """12 → «12 с», 75 → «1 мин 15 с», 3700 → «1 ч 1 мин»."""
    sec = max(0, int(sec))
    if sec < 60:
        return f"{sec} с"
    if sec < 3600:
        return f"{sec // 60} мин" + (f" {sec % 60} с" if sec % 60 else "")
    return f"{sec // 3600} ч {sec % 3600 // 60} мин"


ICON = {"sent": "⏳", "delivered": "📨", "started": "✅", "working": "⚙️", "thinking": "💭", "queued": "🕓",
        "stuck": "⚠️", "waiting": "⏸", "done": "✅", "idle": "✅"}


def line(st: dict, now: float | None = None, started: bool = False) -> str:
    """Одна строка для бота: «✅ Взял в работу · Читает файл X · 12 с»."""
    now = time.time() if now is None else now
    phase = st.get("phase") or "idle"
    parts = [st.get("text") or TEXTS.get(phase) or "Готово"]
    if started and phase in ("working", "thinking"):
        parts.insert(0, TEXTS["started"])
    if st.get("spinner"):
        parts.append(f"({st['spinner']})")
    if phase in ACTIVE and st.get("since"):
        parts.append(elapsed(now - st["since"]))
    if phase == "waiting":
        parts.append("ответьте в сообщении с вопросом")
    icon = ICON["started"] if started and phase in ("working", "thinking") else ICON.get(phase, "•")
    return f"{icon} " + " · ".join(p for p in parts if p)
