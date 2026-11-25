"""Протоколы встреч (GAS-36, MVP; владелец 19.11: «быстро и лучше практик»; исследование штаба —
portfolio-hq/products/meeting-notes-research-2026-11-19.md).

Встреча — куски из любого канала (голосовое, аудиофайл из Диктофона iPhone через «Поделиться», текст), склеенные в
одну. Перед первой записью — напоминание о согласии участников (без отметки «Предупредил» встреча не начинается).
«Готово» — расшифровка (и аудио) ложатся в папку на Диске клиента ``Встречи/ГГГГ-ММ-ДД ЧЧ-ММ встреча`` (Диска нет —
локально в данных пульта, с пометкой); агент в чате «Встречи» делает протокол по формату и предлагает действия:
разослать участникам, в календарь, в заметки — каждое только после «Да». Запись в браузере при заблокированном
экране не обещаем: для длинной встречи — Диктофон iPhone и файл.

Хранение состояния — ``<данные>/meetings.json`` (0600): только открытые встречи по чату, тексты кусков.

**Поручения вслух** (владелец 20.11): во время записи человек говорит «Клод, запиши …» — фрагмент становится отдельным
пунктом-поручением протокола (дословно, с отметкой времени); «Клод, … отправь …» — агент готовит черновик отправки,
отправка — только после «Да». Слова-обращения: Клод, Клауд, Claude, Ладея (так их пишет распознавание речи).
"""

from __future__ import annotations

import contextlib
import html
import itertools
import json
import re
import shutil
import subprocess
import threading
import time
import wave
from pathlib import Path

from gas_pult.config import write_private

CONTINUE_H = 3                 # встреча открыта дольше — новый кусок спрашивает «продолжение или новая»
CONSENT = ("Перед записью предупредите участников, например: «Я записываю встречу, чтобы сделать протокол». "
           "Для длинной встречи включите Диктофон iPhone и пришлите файл сюда («Поделиться» → Telegram → бот): "
           "запись в браузере при заблокированном экране может остановиться.")


class Store:
    def __init__(self, path: Path, clock=time.time):
        self.path, self.clock, self.lock = Path(path), clock, threading.Lock()

    def _load(self) -> dict:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, d: dict):
        write_private(self.path, json.dumps(d, ensure_ascii=False))

    def current(self, chat) -> dict | None:
        return self._load().get(str(chat))

    def open(self, chat) -> dict:
        """Новая встреча (согласие отмечено — «Предупредил»)."""
        now = self.clock()
        m = {"id": time.strftime("%Y%m%d-%H%M%S", time.localtime(now)), "started": now, "consent": True,
             "pieces": [], "files": []}
        with self.lock:
            d = self._load()
            d[str(chat)] = m
            self._save(d)
        return m

    def stale(self, chat) -> bool:
        m = self.current(chat)
        return bool(m) and self.clock() - m["started"] > CONTINUE_H * 3600

    def add(self, chat, text: str, kind: str, file: str = "") -> dict:
        with self.lock:
            d = self._load()
            m = d.get(str(chat))
            if not m:
                raise LookupError("встречи нет — начните: «Протокол встречи»")
            m["pieces"].append({"at": self.clock(), "kind": kind, "text": text.strip()})
            if file:
                m["files"].append(file)
            self._save(d)
        return m

    def close(self, chat) -> dict | None:
        with self.lock:
            d = self._load()
            m = d.pop(str(chat), None)
            self._save(d)
        return m


def transcript(m: dict) -> str:
    """Расшифровка встречи: куски по порядку, с отметкой времени от начала."""
    out = []
    for p in m["pieces"]:
        mm = int((p["at"] - m["started"]) // 60)
        out.append(f"[{mm // 60:02d}:{mm % 60:02d}] ({p['kind']}) {p['text']}")
    return "\n\n".join(out)


WAKE = r"(?:клод|клауд|claude|ладе[яюие]|гаврил[аы]?)"   # прежнее имя — для старых записей
# обращение → «запиши» или «отправь» → текст до конца фразы (точка, «!», «?», перевод строки)
CMD = re.compile(WAKE + r"[\s,:—–-]+(запиши|отправь)\b[\s,:—–-]*(.*?)(?=[.!?…](?:\s|$)|\n|$)", re.I | re.S)
SEND = re.compile(r"[\s,]*(?:и\s+)?отправь\b", re.I)


def commands(m: dict) -> list[dict]:
    """Поручения вслух: [{at: "ЧЧ:ММ" от начала, kind: note | send, text}] — по порядку."""
    out = []
    for p in m.get("pieces", []):
        mm = int((p["at"] - m["started"]) // 60)
        for verb, text in CMD.findall(p.get("text", "")):
            text = text.strip(" ,:—–-")
            kind = "send" if verb.lower() == "отправь" or SEND.search(text) else "note"
            text = SEND.sub("", text).strip(" ,:—–-") if verb.lower() == "запиши" else text
            if text:
                out.append({"at": f"{mm // 60:02d}:{mm % 60:02d}", "kind": kind, "text": text})
    return out


def commands_md(cmds: list[dict]) -> str:
    """Файл «поручения.md» рядом с расшифровкой: что сказали записать и что — отправить (после «Да»)."""
    head = "# Поручения, сказанные вслух\n\n«Отправить» — только черновик; отправка — после «Да».\n"
    return head + "\n".join(f"- [{c['at']}] {'Отправить' if c['kind'] == 'send' else 'Записать'}: {c['text']}"
                             for c in cmds) + "\n"


def folder_for(m: dict, drive: Path | None, data: Path) -> tuple[Path, bool]:
    """Папка встречи: на Диске клиента ``Встречи/ГГГГ-ММ-ДД ЧЧ-ММ встреча`` или локально. (папка, на Диске ли)."""
    name = time.strftime("%Y-%m-%d %H-%M", time.localtime(m["started"])) + " встреча"
    if drive and drive.is_dir():
        return drive / "Встречи" / name, True
    return data / "meetings" / name, False


def save(m: dict, drive: Path | None, data: Path) -> tuple[Path, bool]:
    """Расшифровка — в папку встречи; аудио — туда же и с сервера прочь, когда папка на Диске. Рядом — «встреча.json»
    пульта: начало и длительность записи (по ней проверяем главы оглавления)."""
    d, on_drive = folder_for(m, drive, data)
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    (d / "расшифровка.txt").write_text(transcript(m) + "\n", encoding="utf-8")
    if cmds := commands(m):
        (d / "поручения.md").write_text(commands_md(cmds), encoding="utf-8")
    for f in m.get("files", []):
        src = Path(f)
        if src.is_file():
            dst = d / re.sub(r"[^\w.\- ]", "_", src.name)
            (shutil.move if on_drive else shutil.copy2)(str(src), dst)
    a = audio_file(d)
    dur = audio_seconds(a) if a else None
    if dur is None and m.get("pieces"):                   # записи нет — длительность по кускам текста
        dur = max(0.0, m["pieces"][-1]["at"] - m["started"]) or None
    (d / META).write_text(json.dumps({"id": m.get("id"), "started": m["started"], "dur": dur,
                                      "pieces": len(m.get("pieces", []))}, ensure_ascii=False), encoding="utf-8")
    return d, on_drive


def prompt(folder: Path, on_drive: bool, cmds: list[dict] | None = None, dur: float | None = None) -> str:
    """Задание агенту в чате «Встречи»: протокол по формату, потом действия — каждое после «Да»."""
    where = "на Диске" if on_drive else "на сервере (Диск не подключён — скажите об этом в итоге)"
    said = ""
    if cmds:
        said = ("\nПоручения, сказанные вслух («Клод, запиши / отправь»), — отдельным разделом «Поручения» в начале "
                "протокола, дословно, с отметкой времени; не теряй и не перефразируй:\n"
                + "\n".join(f"- [{c['at']}] {'Отправить' if c['kind'] == 'send' else 'Записать'}: {c['text']}"
                             for c in cmds)
                + "\nДля «Отправить» подготовь черновик (кому, текст) и спроси «Да / Нет / Позже» — сам не отправляй.")
    head = said.lstrip("\n") + ("\n\n" if said else "")
    length = (f"{int(dur)} с ({int(dur) // 60} мин {int(dur) % 60:02d} с)" if dur
              else "неизвестна — оцени по расшифровке")
    return head + (f"Протокол встречи. Расшифровка: «{folder / 'расшифровка.txt'}» ({where}). Сделай протокол простым "
            "языком и сохрани рядом как «протокол.md»:\n1. Тема и дата.\n2. Участники — предложи по тексту и спроси "
            "меня вопросом с вариантами, кого отметить.\n3. Решения — по пунктам, с отметкой времени.\n4. Открытые "
            "вопросы.\n5. Задачи: что, кто, срок — последним разделом «Что сделать».\n"
            f"Рядом сохрани «{JSON_NAME}» — оглавление и задачи для панели, строго JSON без пояснений:\n"
            '{"gist": "главная мысль встречи одной фразой, до 140 знаков", '
            '"chapters": [{"start": 0, "end": 300, "topic": "тема главы"}], '
            '"actions": [{"what": "что сделать", "who": "кто", "due": "ГГГГ-ММ-ДД или пусто"}]}\n'
            f"Главы — 3–12 тем по порядку; start и end — секунды от начала записи, по возрастанию, без наложений, в "
            f"пределах длительности записи: {length}. Нет точных отметок в расшифровке — оцени по доле текста. "
            "actions — те же пункты, что в «Что сделать».\n"
            "Потом спроси вопросом с вариантами, что сделать: «Разослать "
            "участникам» (черновик письма), «В календарь» (следующая встреча и сроки, если календарь подключён), "
            "«В заметки» (Apple через мост, Notion или Диск — что подключено), «Сохранить». Письма, события и "
            "заметки — только после моего «Да».")


# ---------- протокол в панели (владелец 22.11: «уровня Plaud»): оглавление, плеер, «Что сделать», карточка ----------
# Главы, главную мысль и задачи пишет агент в «протокол.json» рядом с «протокол.md» (формат — в ``prompt``). Пульт
# доверяет файлу не больше, чем тексту: разбор с проверкой, плохие главы и пункты отбрасываются молча.

JSON_NAME = "протокол.json"
META = "встреча.json"
AUDIO = {".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg", ".m4a": "audio/mp4", ".mp4": "audio/mp4",
         ".mp3": "audio/mpeg", ".wav": "audio/wav", ".webm": "audio/webm", ".aac": "audio/aac"}
AUDIO_MAX = 150 * 1024 * 1024           # больше — слушать на Диске: панель качает запись целиком
CHAPTERS_MAX, ACTIONS_MAX = 30, 40
ID = re.compile(r"^\d{8}-\d{4}$")       # id протокола в панели — из имени папки «ГГГГ-ММ-ДД ЧЧ-ММ встреча»
NAME = re.compile(r"^(\d{4})-(\d{2})-(\d{2}) (\d{2})-(\d{2}) встреча$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def mid_of(name: str) -> str | None:
    m = NAME.match(name)
    return "{}{}{}-{}{}".format(*m.groups()) if m else None


def roots(drive: Path | None, data: Path) -> list[Path]:
    """Где лежат встречи: Диск клиента (``Встречи``), потом данные пульта — как в ``folder_for``."""
    out = [drive / "Встречи"] if drive and drive.is_dir() else []
    return [*out, data / "meetings"]


def folders(drive: Path | None, data: Path) -> dict[str, Path]:
    """Все папки встреч: {id: папка}. Одинаковый id на Диске и локально — берём Диск."""
    out: dict[str, Path] = {}
    for r in roots(drive, data):
        with contextlib.suppress(OSError):
            for p in r.iterdir():
                if (mid := mid_of(p.name)) and p.is_dir() and mid not in out:
                    out[mid] = p
    return out


def find(mid: str, drive: Path | None, data: Path) -> Path:
    """Папка протокола по id; id — только «ГГГГММДД-ЧЧММ», путь из запроса не берём."""
    if not ID.match(str(mid or "")):
        raise LookupError("нет такого протокола")
    p = folders(drive, data).get(mid)
    if not p:
        raise LookupError("нет такого протокола")
    return p


def audio_file(folder: Path) -> Path | None:
    """Запись встречи: самый большой аудиофайл папки (кусков бывает несколько — оглавление по главному)."""
    try:
        xs = [p for p in folder.iterdir() if p.suffix.lower() in AUDIO and p.is_file()]
    except OSError:
        return None
    return max(xs, key=lambda p: p.stat().st_size) if xs else None


def audio_seconds(path: Path) -> float | None:
    """Длительность записи: wav — стандартной библиотекой, остальное — ffprobe, если он есть; иначе None."""
    if path.suffix.lower() == ".wav":
        with contextlib.suppress(OSError, wave.Error, EOFError), wave.open(str(path)) as w:
            return round(w.getnframes() / float(w.getframerate() or 1), 1)
    if probe := shutil.which("ffprobe"):
        with contextlib.suppress(OSError, ValueError, subprocess.SubprocessError):
            out = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                  str(path)], capture_output=True, text=True, timeout=20).stdout.strip()
            return round(float(out), 1) if out else None
    return None


def seconds(v) -> float | None:
    """Секунды из числа или «ММ:СС» / «ЧЧ:ММ:СС»; чепуха — None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return float(v) if v == v and 0 <= v < 10 ** 6 else None
    m = re.fullmatch(r"\s*(?:(\d{1,2}):)?(\d{1,3}):([0-5]\d)(?:\.\d+)?\s*", str(v or ""))
    if not m:
        return None
    h, mm, ss = (int(x or 0) for x in m.groups())
    return float(h * 3600 + mm * 60 + ss)


def _text(v, n: int) -> str:
    return " ".join(str(v or "").split())[:n] if isinstance(v, str | int | float) and not isinstance(v, bool) else ""


def parse_chapters(raw, dur: float | None) -> list[dict]:
    """Главы [{start, end, topic}] с проверкой: время по возрастанию, без наложений, в пределах длительности (если
    известна). Плохая глава отбрасывается; нет конца — до начала следующей или до конца записи."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for c in raw[:100]:
        if not isinstance(c, dict):
            continue
        start, end, topic = seconds(c.get("start")), seconds(c.get("end")), _text(c.get("topic"), 120)
        if start is None or not topic or (dur and start >= dur):
            continue
        if end is not None and (end <= start or (dur and end > dur + 1)):
            continue
        if out and (start <= out[-1]["start"] or (out[-1]["end"] is not None and start < out[-1]["end"] - 1)):
            continue
        out.append({"start": start, "end": end, "topic": topic})
        if len(out) >= CHAPTERS_MAX:
            break
    for a, b in itertools.pairwise(out):
        if a["end"] is None:
            a["end"] = b["start"]
    if out and out[-1]["end"] is None:
        out[-1]["end"] = dur if dur else None
    return out


def parse_actions(raw) -> list[dict]:
    """«Что сделать» [{what, who, due}]: без «что» пункт отбрасывается; срок — ГГГГ-ММ-ДД (в задачу) или текстом."""
    if not isinstance(raw, list):
        return []
    out = []
    for a in raw[:100]:
        if isinstance(a, str):
            a = {"what": a}
        if not isinstance(a, dict) or not (what := _text(a.get("what"), 300)):
            continue
        due = _text(a.get("due"), 40)
        out.append({"what": what, "who": _text(a.get("who"), 80), "due": due if DATE.match(due) else "",
                    **({"when": due} if due and not DATE.match(due) else {})})
        if len(out) >= ACTIONS_MAX:
            break
    return out


def _read(p: Path, n: int = 2_000_000) -> str:
    try:
        with p.open(encoding="utf-8", errors="replace") as f:
            return f.read(n)
    except OSError:
        return ""


def _meta(folder: Path) -> dict:
    with contextlib.suppress(ValueError):
        d = json.loads(_read(folder / META, 10_000) or "{}")
        return d if isinstance(d, dict) else {}
    return {}


def title_of(md: str, started: float | None) -> str:
    """Тема — первый заголовок протокола; нет — «Встреча 22 ноября»."""
    for line in md.splitlines()[:30]:
        if line.startswith("#") and (t := line.lstrip("#").strip(" *")):
            return t[:120]
    return "Встреча " + (time.strftime("%d.%m.%Y", time.localtime(started)) if started else "")


def started_of(folder: Path, meta: dict) -> float | None:
    if isinstance(meta.get("started"), int | float):
        return float(meta["started"])
    m = NAME.match(folder.name)
    return time.mktime(time.strptime(" ".join(m.groups()), "%Y %m %d %H %M")) if m else None


def view(folder: Path, full: bool = True) -> dict:
    """Протокол для панели: тема, дата, длительность, главная мысль, главы, «Что сделать», текст, есть ли запись.
    Только содержимое папки встречи — путей сервера в ответе нет."""
    meta, md = _meta(folder), _read(folder / "протокол.md")
    try:
        data = json.loads(_read(folder / JSON_NAME, 500_000) or "{}")
    except ValueError:
        data = {}
    data = data if isinstance(data, dict) else {}
    a = audio_file(folder)
    dur = meta.get("dur") if isinstance(meta.get("dur"), int | float) and meta["dur"] > 0 else None
    started = started_of(folder, meta)
    out = {"id": mid_of(folder.name), "title": title_of(md, started), "started": started, "dur": dur,
           "gist": _text(data.get("gist"), 200), "ready": bool(md), "audio": bool(a),
           "chapters": parse_chapters(data.get("chapters"), dur), "actions": parse_actions(data.get("actions"))}
    if full:
        out["md"] = md
        if not md:
            out["transcript"] = _read(folder / "расшифровка.txt", 200_000)
    return out


def listing(drive: Path | None, data: Path) -> list[dict]:
    """Протоколы для панели — новые сверху: без текста, только то, что нужно строке списка."""
    out = [view(p, full=False) for p in folders(drive, data).values()]
    return sorted(out, key=lambda x: -(x["started"] or 0))


def audio(folder: Path) -> tuple[str, bytes]:
    a = audio_file(folder)
    if not a:
        raise LookupError("записи нет — только текст")
    if a.stat().st_size > AUDIO_MAX:
        raise ValueError("запись больше 150 МБ — откройте её на Диске")
    return AUDIO[a.suffix.lower()], a.read_bytes()


def clock(s: float | None) -> str:
    if s is None:
        return ""
    s = int(s)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября",
          "декабря")


def _wrap(text: str, width: int, lines: int) -> list[str]:
    words, out, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) <= width:
            cur = f"{cur} {w}" if cur else w
            continue
        if cur:
            out.append(cur)
        cur = w[:width]
        if len(out) == lines:
            break
    if cur and len(out) < lines:
        out.append(cur)
    if len(out) == lines and " ".join(out) != " ".join(words):
        out[-1] = out[-1][: width - 1].rstrip(" ,.;:—-") + "…"
    return out


def card_svg(v: dict, mark: str = "") -> str:
    """Карточка-превью для пересылки (1200×630): главная мысль, тема, дата, длительность, знак Ладеи. SVG собран на
    сервере без зависимостей; весь текст экранирован. ``mark`` — содержимое brand/gavrila-mark.svg."""
    e = html.escape
    when = ""
    if v.get("started"):
        t = time.localtime(v["started"])
        when = f"{t.tm_mday} {MONTHS[t.tm_mon - 1]} {t.tm_year}"
    dur = v.get("dur")
    meta = " · ".join(x for x in (when, f"{round(dur / 60)} мин" if dur else "",
                                  f"глав: {len(v['chapters'])}" if v.get("chapters") else "") if x)
    gist = v.get("gist") or v.get("title") or "Протокол встречи"
    big = _wrap(gist, 30, 4)
    y0 = 250 - (len(big) - 1) * 30
    lines = "".join(f'<tspan x="80" y="{y0 + i * 66}">{e(s)}</tspan>' for i, s in enumerate(big))
    title = _wrap(v.get("title") or "", 60, 1)
    m = re.search(r"<svg[^>]*viewBox=\"([^\"]+)\"[^>]*>(.*)</svg>", mark or "", re.S)
    logo = (f'<svg x="1040" y="64" width="80" height="218" viewBox="{e(m.group(1))}" color="#2563EB">'
            f"{m.group(2)}</svg>") if m else ""
    font = "font-family=\"system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif\""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">'
            f'<rect width="1200" height="630" rx="0" fill="#FFFFFF"/>'
            f'<rect x="0" y="0" width="16" height="630" fill="#2563EB"/>'
            f'<text x="80" y="100" {font} font-size="28" font-weight="600" fill="#2563EB">Протокол встречи</text>'
            f'<text {font} font-size="54" font-weight="700" fill="#111827">{lines}</text>'
            + (f'<text x="80" y="500" {font} font-size="30" fill="#4B5563">{e(title[0])}</text>' if title else "")
            + f'<text x="80" y="560" {font} font-size="28" fill="#5F6672">{e(meta)}</text>'
            f"{logo}"
            f'<text x="1120" y="580" text-anchor="end" {font} font-size="24" font-weight="600" fill="#111827">'
            f"Ладея</text></svg>")


def saved_dur(folder: Path) -> float | None:
    """Длительность записи из «встреча.json» (пишет ``save``) — для задания агенту."""
    d = _meta(folder).get("dur")
    return float(d) if isinstance(d, int | float) and d > 0 else None
