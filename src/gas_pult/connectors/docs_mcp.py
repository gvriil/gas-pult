#!/usr/bin/env python3
"""«Документы» — поиск по своим файлам (GAS-16, слой 2: RAG, ступень А; владелец 17.11: «возьми и примени всё»).

Агент отвечает по договору, а не выдумывает: инструмент ``find_in_docs`` находит в папке «Документы» нужные места и
отдаёт цитату, файл и место (страница PDF, строки текста, лист таблицы). Ступень А — полнотекстовый поиск sqlite FTS5
(BM25, русский и английский; грубый стемминг — по началу слова), без новых пакетов и без модели: память — десятки МБ
на время запроса. Ступень Б (смысловой поиск эмбеддингами) — отдельно, после замера памяти на сервере.

Папки — ``GAS_DOCS_DIRS`` (через «:»; по умолчанию ``~/Документы``): на сервере или смонтированный Google Диск
(``~/drive/...``, rclone — данные Google под Limited Use: текст уходит только модели, которая на нём не учится).
Индекс — ``GAS_DOCS_INDEX`` (по умолчанию ``~/.local/state/gas-pult/docs-index.sqlite``, 0600). Новые и изменённые
файлы индексируются сами перед каждым поиском (по времени изменения и размеру), удалённые — убираются.

Форматы: txt, md, csv, tsv, json, log, html, docx, xlsx, odt, pdf (``pdftotext``, если есть). Только чтение.
Один файл, только стандартная библиотека; запуск ``python3 docs_mcp.py`` (MCP по stdio) или ``… index`` (обновить
индекс и напечатать итог).
"""

from __future__ import annotations

import html
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
from pathlib import Path

try:
    import _core  # запуск файлом: python3 docs_mcp.py
except ImportError:  # импорт в тестах
    from . import _core

SVC = "docs"
TEXT = {".txt", ".md", ".csv", ".tsv", ".json", ".log", ".html", ".htm"}
ZIPPED = {".docx", ".xlsx", ".odt"}
EXTS = TEXT | ZIPPED | {".pdf"}
MAX_FILE = 25 * 1024 * 1024        # больше — не индексируем (видео, архивы под видом документа)
CHUNK = 900                        # знаков во фрагменте
BUDGET = 20.0                      # с на обновление индекса перед поиском; остальное — в следующий раз
LIMIT = 8


def dirs() -> list[Path]:
    raw = os.environ.get("GAS_DOCS_DIRS") or str(Path.home() / "Документы")
    return [Path(os.path.expanduser(x)) for x in raw.split(os.pathsep) if x.strip()]


def index_path() -> Path:
    return Path(os.path.expanduser(os.environ.get("GAS_DOCS_INDEX")
                                   or "~/.local/state/gas-pult/docs-index.sqlite"))


def db() -> sqlite3.Connection:
    p = index_path()
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    new = not p.exists()
    c = sqlite3.connect(p)
    if new:
        p.chmod(0o600)
    c.execute("create table if not exists files (path text primary key, mtime real, size integer, at real)")
    c.execute("create virtual table if not exists chunks using fts5(path unindexed, place unindexed, text, "
              "tokenize = 'unicode61 remove_diacritics 2')")
    return c


# ---------- текст из файлов: [(место, текст)] ----------
def _xml_text(raw: bytes, tags: tuple[str, ...]) -> list[str]:
    s = raw.decode("utf-8", "replace")
    out, cur = [], []
    for m in re.finditer(r"<(/?)([\w:]+)[^>]*?(/?)>|([^<]+)", s):
        close, tag, self_close, text = m.group(1), m.group(2), m.group(3), m.group(4)
        if text:
            cur.append(html.unescape(text))
        elif tag in tags and (close or self_close):
            if "".join(cur).strip():
                out.append("".join(cur).strip())
            cur = []
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


def extract(f: Path) -> list[tuple[str, str]]:
    ext = f.suffix.lower()
    if ext in TEXT:
        t = f.read_text(encoding="utf-8", errors="replace")
        if ext in (".html", ".htm"):
            t = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", t)))
        lines, out, buf, start = t.splitlines(), [], [], 1
        for i, line in enumerate(lines, 1):
            buf.append(line)
            if sum(len(x) for x in buf) >= CHUNK:
                out.append((f"строки {start}–{i}", "\n".join(buf)))
                buf, start = [], i + 1
        if buf:
            out.append((f"строки {start}–{len(lines)}", "\n".join(buf)))
        return out
    if ext in ZIPPED:
        with zipfile.ZipFile(f) as z:
            if ext == ".docx":
                paras = _xml_text(z.read("word/document.xml"), ("w:p",))
                return _group(paras, "абзацы")
            if ext == ".odt":
                return _group(_xml_text(z.read("content.xml"), ("text:p", "text:h")), "абзацы")
            shared = _xml_text(z.read("xl/sharedStrings.xml"), ("si",)) if "xl/sharedStrings.xml" in z.namelist() \
                else []
            out = []
            for n in sorted(x for x in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", x)):
                s = z.read(n).decode("utf-8", "replace")
                cells = []
                for m in re.finditer(r"<c ([^>]*)>(?:<f>.*?</f>)?<v>([^<]*)</v>", s):
                    v, shared_cell = m.group(2), ' t="s"' in " " + m.group(1)
                    cells.append(shared[int(v)] if shared_cell and v.isdigit() and int(v) < len(shared) else v)
                sheet = "лист " + re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)
                out += [(sheet, t) for _, t in _group(cells, "")]
            return out
    if ext == ".pdf" and (exe := shutil.which("pdftotext")):
        r = subprocess.run([exe, "-layout", str(f), "-"], capture_output=True, timeout=120)
        pages = r.stdout.decode("utf-8", "replace").split("\f")
        return [(f"стр. {i}", p) for i, p in enumerate(pages, 1) if p.strip()]
    return []


def _group(parts: list[str], what: str) -> list[tuple[str, str]]:
    out, buf, start = [], [], 1
    for i, p in enumerate(parts, 1):
        buf.append(p)
        if sum(len(x) for x in buf) >= CHUNK:
            out.append((f"{what} {start}–{i}".strip(), "\n".join(buf)))
            buf, start = [], i + 1
    if buf:
        out.append((f"{what} {start}–{len(parts)}".strip(), "\n".join(buf)))
    return out


# ---------- индекс ----------
def _files() -> list[Path]:
    out = []
    for d in dirs():
        if not d.is_dir():
            continue
        root = d.resolve()
        for f in d.rglob("*"):
            if any(x.startswith(".") for x in f.relative_to(d).parts):
                continue
            try:
                if f.suffix.lower() in EXTS and f.is_file() and f.resolve().is_relative_to(root):
                    out.append(f)
            except OSError:
                continue
    return out


def update(budget: float = BUDGET) -> dict:
    """Новые и изменённые файлы — в индекс, удалённые — из него. Возвращает сколько файлов и что сделано."""
    t0, c = time.time(), db()
    have = {r[0]: (r[1], r[2]) for r in c.execute("select path, mtime, size from files")}
    seen, added, skipped = set(), 0, 0
    for f in _files():
        key = str(f)
        seen.add(key)
        try:
            st = f.stat()
        except OSError:
            continue
        if have.get(key) == (st.st_mtime, st.st_size):
            continue
        if time.time() - t0 > budget:
            skipped += 1
            continue
        c.execute("delete from chunks where path = ?", (key,))
        try:
            parts = extract(f) if st.st_size <= MAX_FILE else []
        except (OSError, zipfile.BadZipFile, KeyError, subprocess.SubprocessError, ValueError):
            parts = []
        c.executemany("insert into chunks (path, place, text) values (?, ?, ?)", [(key, p, t) for p, t in parts])
        c.execute("insert or replace into files values (?, ?, ?, ?)", (key, st.st_mtime, st.st_size, time.time()))
        added += 1
    gone = [k for k in have if k not in seen]
    for k in gone:
        c.execute("delete from chunks where path = ?", (k,))
        c.execute("delete from files where path = ?", (k,))
    c.commit()
    n = c.execute("select count(*) from files").fetchone()[0]
    c.close()
    return {"files": n, "updated": added, "removed": len(gone), "later": skipped}


WORD = re.compile(r"[\w-]{2,}", re.U)
STOP = frozenset({"на", "в", "во", "и", "по", "для", "с", "со", "о", "об", "к", "ко", "у", "за", "из", "от", "до",
                  "как",
                  "что", "это", "мне", "мой", "моя", "наш", "какой", "какая", "какие", "где", "когда", "есть", "или",
                  "не", "ли", "же", "бы", "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "what"})


def fts_query(q: str, any_word: bool = False) -> str:
    """Запрос человека → FTS5: каждое слово — по началу (грубый стемминг: «договора» найдёт «договор»)."""
    every = [w.lower() for w in WORD.findall(q)]
    words = [w for w in every if w not in STOP][:12] or every[:12]
    terms = []
    for w in words:
        stem = w[:max(4, len(w) - 2)] if len(w) > 5 else w
        terms.append(f'"{stem}"*')
    return (" OR " if any_word else " AND ").join(terms)


def search(q: str, limit: int = LIMIT) -> dict:
    if not q or not WORD.search(q):
        raise _core.ToolError("напишите, что искать: слово или фразу")
    state = update()
    c = db()
    rows = []
    for any_word in (False, True):
        expr = fts_query(q, any_word)
        rows = c.execute("select path, place, snippet(chunks, 2, '«', '»', '…', 24) from chunks where chunks "
                         "match ? order by bm25(chunks) limit ?",
                         (expr, max(1, min(int(limit), 20)))).fetchall()
        if rows:
            break
    c.close()
    base = [str(d) for d in dirs()]
    hits = []
    for path, place, snip in rows:
        rel = next((os.path.relpath(path, b) for b in base if path.startswith(b.rstrip("/") + "/")), path)
        hits.append({"file": rel, "path": path, "place": place, "quote": " ".join(snip.split())})
    return {"query": q, "hits": hits, "files_indexed": state["files"],
            "note": "" if hits else "в документах не нашлось — скажите человеку честно, не придумывайте"}


def find_in_docs(a: dict) -> dict:
    return search(str(a.get("query", "")), a.get("limit") or LIMIT)


def docs_status(a: dict) -> dict:
    st = update()
    return {"folders": [{"path": str(d), "exists": d.is_dir()} for d in dirs()], **st,
            "pdf": bool(shutil.which("pdftotext"))}


SERVER = {
    "name": "gas-pult-docs",
    "instructions": "Поиск по документам человека (договоры, инструкции, прайсы). Отвечая по документам, сначала "
                    "вызови find_in_docs и цитируй найденное: «цитата» — файл, место. Не нашлось — так и скажи.",
    "tools": [
        {"name": "find_in_docs", "fn": find_in_docs,
         "description": "Найти в папке «Документы»: вернёт до 8 мест с цитатой, файлом и местом (страница, строки, "
                        "лист). Ищет по словам (начало слова), сначала все слова, потом любое.",
         "inputSchema": {"type": "object", "required": ["query"], "properties": {
             "query": {"type": "string", "description": "что искать: слова или фраза"},
             "limit": {"type": "integer", "description": "сколько мест вернуть, до 20"}}}},
        {"name": "docs_status", "fn": docs_status,
         "description": "Какие папки подключены, сколько файлов в индексе; обновить индекс.",
         "inputSchema": {"type": "object", "properties": {}}},
    ],
}


if __name__ == "__main__":
    if sys.argv[1:] == ["index"]:
        print(update(budget=3600))
        sys.exit(0)
    sys.exit(_core.main(SERVER, SVC))
