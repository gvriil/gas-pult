#!/usr/bin/env python3
"""Базовые интеграции пульта для любой модели (задача 48, ADR-0002): свой MCP-сервер по stdio.

Один файл, только стандартная библиотека Python, без пакета gas_pult: его можно скопировать в пространство и запускать
``python3 base_mcp.py search`` или ``python3 base_mcp.py drive``. Claude Code — MCP-клиент сам, поэтому инструменты
одинаково видны сессии на Claude, GLM, DeepSeek и любой другой модели.

**search** — поиск в интернете (``web_search``). Сервис — ``GAS_SEARCH_ENGINE``: ``yandex`` (Yandex Search API),
``brave``, ``tavily``, ``exa``. Ключ — в файле ``GAS_SEARCH_KEY_FILE`` (0600; в настройках Claude Code только путь),
для Яндекса ещё ``GAS_SEARCH_FOLDER`` (ID каталога Yandex Cloud). ``GAS_SEARCH_BASE`` — другой адрес API (тесты).

**drive** — файлы Google Диска через rclone, без коннекторов claude.ai: ``drive_list``, ``drive_download``,
``drive_upload``. ``RCLONE_CONFIG`` — свой rclone.conf человека или пространства, ``GAS_DRIVE_REMOTE`` — имя
удалённого диска в нём (по умолчанию ``gdrive``), ``GAS_DRIVE_RCLONE`` — путь к rclone, ``GAS_DRIVE_DIR`` — папка, куда
можно скачивать и откуда загружать (по умолчанию — папка сессии). Пути в этой папке — только относительные, без ``..``
и без выхода по ссылкам наружу.

Протокол — JSON-RPC 2.0 построчно (MCP stdio): ``initialize``, ``tools/list``, ``tools/call``, ``ping``. Ключи не
пишутся ни в ответы, ни в stderr.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

VERSION = "1"
PROTOCOL = "2025-06-18"
HTTP_TIMEOUT = 25
RCLONE_TIMEOUT = 600
MAX_RESULTS = 10
SNIPPET = 600

ENGINES = {
    "yandex": "https://searchapi.api.cloud.yandex.net",
    "brave": "https://api.search.brave.com",
    "tavily": "https://api.tavily.com",
    "exa": "https://api.exa.ai",
}


TAVILY_COUNTRY = {"ru": "russia", "us": "united states", "gb": "united kingdom", "de": "germany", "nl": "netherlands",
                  "kz": "kazakhstan", "by": "belarus", "ua": "ukraine", "fr": "france"}


class ToolError(Exception):
    """Понятная ошибка инструмента: уходит модели как текст с ``isError``."""


# ---------- поиск ----------
def _key() -> str:
    f = os.environ.get("GAS_SEARCH_KEY_FILE", "")
    if f:
        try:
            return Path(f).read_text(encoding="utf-8").strip()
        except OSError:
            raise ToolError("нет файла ключа поиска — подключите «Веб-поиск» заново в «Интеграциях» панели") from None
    return os.environ.get("GAS_SEARCH_KEY", "").strip()


def _hide(text: str, key: str) -> str:
    return text.replace(key, "***") if key else text


def _http(url: str, key: str, headers: dict, body: dict | None = None) -> bytes:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Accept": "application/json", "User-Agent": "gas-pult-mcp/1",
                                          **({"Content-Type": "application/json"} if data else {}), **headers})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        detail = e.read(300).decode("utf-8", "replace")
        hint = " — проверьте ключ" if e.code in (401, 403) else " — лимит запросов, подождите" if e.code == 429 else ""
        raise ToolError(_hide(f"сервис поиска ответил {e.code}{hint}: {detail}", key)) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ToolError(_hide(f"сервис поиска недоступен: {getattr(e, 'reason', e)}", key)) from None


def _cut(s, n: int = SNIPPET) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def _yandex_xml(raw: bytes) -> list[dict]:
    """Ответ Yandex Search API в формате XML (как у Яндекс.XML): group → doc → url, title, passages."""
    out = []
    root = ET.fromstring(raw)
    err = root.find(".//error")
    if err is not None and not root.findall(".//doc"):
        text = "".join(err.itertext()).strip()
        if err.get("code") == "15":                         # «ничего не нашлось»
            return []
        raise ToolError(f"Яндекс: {text or 'ошибка поиска'}")
    for doc in root.iter("doc"):
        passages = [" ".join(p.itertext()) for p in doc.iter("passage")]
        head = doc.find("headline")
        snippet = " … ".join(passages) or ("".join(head.itertext()) if head is not None else "")
        title = doc.find("title")
        out.append({"title": "".join(title.itertext()) if title is not None else "",
                    "url": (doc.findtext("url") or "").strip(), "snippet": snippet})
    return out


def search(query: str, n: int = 5, region: str = "") -> list[dict]:
    engine = os.environ.get("GAS_SEARCH_ENGINE", "yandex").lower()
    if engine not in ENGINES:
        raise ToolError(f"неизвестный сервис поиска «{engine}»: {', '.join(ENGINES)}")
    key = _key()
    if not key:
        raise ToolError("нет ключа поиска — подключите «Веб-поиск» в «Интеграциях» панели")
    base = (os.environ.get("GAS_SEARCH_BASE") or ENGINES[engine]).rstrip("/")
    n = max(1, min(int(n or 5), MAX_RESULTS))
    if engine == "brave":
        q = {"q": query, "count": n}
        if region:
            q["country"] = region.upper()
        if re.search("[а-яё]", query, re.I):
            q["search_lang"] = "ru"
        d = json.loads(_http(f"{base}/res/v1/web/search?{urllib.parse.urlencode(q)}", key,
                             {"X-Subscription-Token": key}))
        rows = [{"title": x.get("title"), "url": x.get("url"),
                 "snippet": " … ".join([x.get("description") or "", *(x.get("extra_snippets") or [])[:2]])}
                for x in ((d.get("web") or {}).get("results") or [])]
    elif engine == "tavily":
        body = {"query": query, "max_results": n, "search_depth": "basic"}
        if country := TAVILY_COUNTRY.get(region.lower()):  # Tavily ждёт полное английское имя страны
            body["country"] = country
        d = json.loads(_http(f"{base}/search", key, {"Authorization": f"Bearer {key}"}, body))
        rows = [{"title": x.get("title"), "url": x.get("url"), "snippet": x.get("content")}
                for x in d.get("results") or []]
    elif engine == "exa":
        body = {"query": query, "numResults": n, "type": "auto",
                "contents": {"highlights": {"numSentences": 3}, "text": {"maxCharacters": SNIPPET}}}
        if region:
            body["userLocation"] = region.upper()
        d = json.loads(_http(f"{base}/search", key, {"x-api-key": key}, body))
        rows = [{"title": x.get("title"), "url": x.get("url"),
                 "snippet": " … ".join(x.get("highlights") or []) or x.get("text")} for x in d.get("results") or []]
    else:                                                    # yandex
        folder = os.environ.get("GAS_SEARCH_FOLDER", "").strip()
        if not folder:
            raise ToolError("для Яндекса нужен ID каталога Yandex Cloud — подключите «Веб-поиск» заново")
        ru = region.lower() in ("ru", "")
        body = {"query": {"searchType": "SEARCH_TYPE_RU" if ru else "SEARCH_TYPE_COM", "queryText": query,
                          "familyMode": "FAMILY_MODE_MODERATE"},
                "groupSpec": {"groupMode": "GROUP_MODE_DEEP", "groupsOnPage": str(n), "docsInGroup": "1"},
                "maxPassages": "3", "l10n": "LOCALIZATION_RU",
                **({"region": "225"} if ru else {}), "folderId": folder, "responseFormat": "FORMAT_XML"}
        d = json.loads(_http(f"{base}/v2/web/search", key, {"Authorization": f"Api-Key {key}"}, body))
        try:
            rows = _yandex_xml(base64.b64decode(d.get("rawData") or ""))
        except (ValueError, ET.ParseError):
            raise ToolError("Яндекс вернул непонятный ответ") from None
    return [{"title": _cut(r["title"], 200), "url": str(r["url"] or ""), "snippet": _cut(r["snippet"])}
            for r in rows if r.get("url")][:n]


def tool_search(a: dict) -> str:
    q = str(a.get("query") or "").strip()
    if not q:
        raise ToolError("пустой запрос")
    rows = search(q[:400], a.get("max_results") or 5, str(a.get("region") or ""))
    if not rows:
        return f"По запросу «{q}» ничего не нашлось."
    engine = os.environ.get("GAS_SEARCH_ENGINE", "yandex")
    return f"Поиск ({engine}): «{q}»\n\n" + "\n\n".join(
        f"{i}. {r['title']}\n{r['url']}\n{r['snippet']}" for i, r in enumerate(rows, 1))


# ---------- Google Диск через rclone ----------
def _base() -> Path:
    return Path(os.environ.get("GAS_DRIVE_DIR") or os.getcwd()).resolve()


def local_path(rel: str, must_exist: bool = False) -> Path:
    """Путь внутри папки пространства: относительный, без «..», ссылки раскрыты и тоже ведут внутрь."""
    rel = str(rel or "").strip()
    if not rel or rel.startswith(("/", "~", "\\")) or re.match(r"^[A-Za-z]:", rel):
        raise ToolError("путь — относительно папки сессии, например «docs/отчёт.pdf»")
    parts = Path(rel).parts
    if ".." in parts or any("\x00" in p for p in parts):
        raise ToolError("выходить из папки сессии («..») нельзя")
    base = _base()
    p = (base / rel).resolve()
    if p != base and base not in p.parents:
        raise ToolError("путь ведёт за пределы папки сессии")
    if must_exist and not p.is_file():
        raise ToolError(f"нет файла «{rel}» в папке сессии")
    return p


def remote_path(path: str) -> str:
    path = str(path or "").strip().strip("/")
    if "\x00" in path or ".." in Path(path).parts:
        raise ToolError("путь на Диске — без «..»")
    remote = os.environ.get("GAS_DRIVE_REMOTE", "gdrive").rstrip(":")
    return f"{remote}:{path}"


def rclone(*args: str) -> str:
    exe = os.environ.get("GAS_DRIVE_RCLONE") or "rclone"
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=RCLONE_TIMEOUT,
                           stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise ToolError("rclone не установлен на сервере") from None
    except subprocess.TimeoutExpired:
        raise ToolError(f"rclone не ответил за {RCLONE_TIMEOUT} с") from None
    if r.returncode != 0:
        lines = [x for x in (r.stderr or "").splitlines() if x.strip()]
        msg = lines[-1] if lines else f"код {r.returncode}"
        msg = re.sub(r'("?(access_token|refresh_token|token)"?\s*[:=]\s*)\S+', r"\1***", msg)
        if "didn't find section" in msg:
            msg = "Диск не настроен — подключите «Google Диск (rclone)» в «Интеграциях» панели"
        raise ToolError(f"rclone: {msg[-400:]}")
    return r.stdout


def tool_list(a: dict) -> str:
    path = str(a.get("path") or "")
    limit = max(1, min(int(a.get("limit") or 20), 200))
    order = str(a.get("order") or "recent")
    args = ["lsjson", remote_path(path), "--max-depth", "1", "--no-mimetype"]
    if a.get("recursive"):
        args[3] = "4"
        args.append("--files-only")
    try:
        items = json.loads(rclone(*args) or "[]")
    except ValueError:
        raise ToolError("rclone вернул непонятный список") from None
    if order == "name":
        items.sort(key=lambda x: (not x.get("IsDir"), str(x.get("Path", "")).lower()))
    else:
        items.sort(key=lambda x: str(x.get("ModTime", "")), reverse=True)
    if not items:
        return f"Папка «{path or '/'}» на Диске пуста."
    rows = [f"{'[папка] ' if x.get('IsDir') else ''}{(path.strip('/') + '/' if path.strip('/') else '')}{x.get('Path')}"
            f" · {str(x.get('ModTime', ''))[:16].replace('T', ' ')}"
            + ("" if x.get("IsDir") else f" · {x.get('Size', 0)} байт") for x in items[:limit]]
    more = f"\n… и ещё {len(items) - limit}" if len(items) > limit else ""
    return f"Диск «{path or '/'}» ({'сначала новые' if order != 'name' else 'по имени'}):\n" + "\n".join(rows) + more


def tool_download(a: dict) -> str:
    src = str(a.get("path") or "").strip().strip("/")
    if not src:
        raise ToolError("укажите путь файла на Диске (из drive_list)")
    dest_rel = str(a.get("to") or "").strip() or Path(src).name
    dest = local_path(dest_rel)
    if dest.is_dir():
        dest = local_path(str(Path(dest_rel) / Path(src).name))
    dest.parent.mkdir(parents=True, exist_ok=True)
    rclone("copyto", remote_path(src), str(dest))
    if not dest.exists():                                    # документ Google — скачан с расширением формата
        found = sorted(dest.parent.glob(dest.name + ".*")) or sorted(dest.parent.glob(dest.stem + ".*"))
        dest = found[0] if found else dest
    rel = dest.relative_to(_base()) if dest.exists() else dest_rel
    size = dest.stat().st_size if dest.exists() else 0
    return f"Скачано: Диск «{src}» → «{rel}» ({size} байт) в папке сессии."


def tool_upload(a: dict) -> str:
    src = local_path(str(a.get("path") or ""), must_exist=True)
    folder = str(a.get("folder") or "").strip().strip("/")
    target = f"{folder}/{src.name}" if folder else src.name
    rclone("copyto", str(src), remote_path(target))
    return f"Загружено: «{src.relative_to(_base())}» → Диск «{target}»."


# ---------- протокол MCP ----------
SERVERS = {
    "search": {
        "name": "gas-pult-search",
        "instructions": "Поиск в интернете для любой модели: web_search возвращает заголовки, адреса и выдержки. "
                        "Страницу целиком читайте WebFetch по адресу из выдачи.",
        "tools": [{
            "name": "web_search",
            "description": "Поиск в интернете (хорошо понимает русский). Возвращает до 10 результатов: "
                           "заголовок, адрес, выдержка. Для подробностей открой адрес инструментом WebFetch.",
            "inputSchema": {"type": "object", "properties": {
                "query": {"type": "string", "description": "Поисковый запрос"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS, "default": 5},
                "region": {"type": "string", "description": "Код страны, например ru или us (необязательно)"}},
                "required": ["query"]},
            "fn": tool_search}],
    },
    "drive": {
        "name": "gas-pult-drive",
        "instructions": "Google Диск через rclone: список, скачать в папку сессии, загрузить из неё. Пути в папке "
                        "сессии — относительные.",
        "tools": [
            {"name": "drive_list",
             "description": "Список файлов и папок на Google Диске. order=recent — сначала новые (по умолчанию), "
                            "name — по имени. recursive=true — файлы и во вложенных папках (до 4 уровней).",
             "inputSchema": {"type": "object", "properties": {
                 "path": {"type": "string", "description": "Папка на Диске; пусто — корень «Мой диск»"},
                 "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20},
                 "order": {"type": "string", "enum": ["recent", "name"], "default": "recent"},
                 "recursive": {"type": "boolean", "default": False}}},
             "fn": tool_list},
            {"name": "drive_download",
             "description": "Скачать файл с Диска в папку сессии. Документы Google сохраняются как docx/xlsx/pptx.",
             "inputSchema": {"type": "object", "properties": {
                 "path": {"type": "string", "description": "Путь файла на Диске, как в drive_list"},
                 "to": {"type": "string", "description": "Куда в папке сессии (относительно); пусто — имя файла"}},
                 "required": ["path"]},
             "fn": tool_download},
            {"name": "drive_upload",
             "description": "Загрузить файл из папки сессии на Диск (в указанную папку; есть файл с тем же "
                            "именем — заменит его).",
             "inputSchema": {"type": "object", "properties": {
                 "path": {"type": "string", "description": "Файл в папке сессии (относительный путь)"},
                 "folder": {"type": "string", "description": "Папка на Диске; пусто — корень"}},
                 "required": ["path"]},
             "fn": tool_upload}],
    },
}


def handle(server: dict, msg: dict) -> dict | None:
    mid, method = msg.get("id"), msg.get("method", "")
    if mid is None:                                          # уведомление (notifications/initialized и др.)
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if method == "initialize":
        ver = str((msg.get("params") or {}).get("protocolVersion") or PROTOCOL)
        return ok({"protocolVersion": ver, "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": server["name"], "version": VERSION},
                   "instructions": server["instructions"]})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [{k: v for k, v in t.items() if k != "fn"} for t in server["tools"]]})
    if method == "tools/call":
        p = msg.get("params") or {}
        tool = next((t for t in server["tools"] if t["name"] == p.get("name")), None)
        if not tool:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "нет такого инструмента"}}
        try:
            text, err = tool["fn"](p.get("arguments") or {}), False
        except ToolError as e:
            text, err = str(e), True
        except (ValueError, TypeError) as e:
            text, err = f"неверные параметры: {e}", True
        return ok({"content": [{"type": "text", "text": text}], "isError": err})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"метод не поддерживается: {method}"}}


def serve(kind: str, inp=None, out=None):
    server = SERVERS[kind]
    inp, out = inp or sys.stdin, out or sys.stdout
    for line in inp:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "не JSON"}}
        else:
            resp = handle(server, msg) if isinstance(msg, dict) else None
        if resp is not None:
            out.write(json.dumps(resp, ensure_ascii=False) + "\n")
            out.flush()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in SERVERS:
        print(f"использование: base_mcp.py {{{'|'.join(SERVERS)}}}", file=sys.stderr)
        return 2
    serve(argv[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
