"""Общее ядро коннекторов пульта к сервисам бизнеса (контракт — docs/CONNECTORS.md).

Только стандартная библиотека, как ``base_mcp.py``: коннектор — один файл ``connectors/<svc>_mcp.py`` рядом с этим,
запускается ``python3 <svc>_mcp.py`` (тогда ``import _core``) или импортируется в тестах (``from . import _core``).

Что здесь:
- ``read_secret`` — ключ из файла ``~/.config/gastech-mcp/<svc>.token`` (0600) или из пути в ``GAS_<SVC>_KEY_FILE``;
- ``hide`` / ``secret_values`` — ключ (и все строковые значения JSON-файла ключа) не попадает в ответы и stderr;
- ``http`` — запрос к API: понятные ошибки 401/403/404/429, троттлинг под лимиты вендора, адрес подменяется
  ``GAS_<SVC>_BASE`` (песочница, тесты);
- ``propose`` / ``take_confirmed`` — запись только через черновик и «Да» человека в панели: «Да» хранит служба
  панели в памяти, коннектор спрашивает её перед выполнением (``approvals.py``); отметки на диске не в счёт;
- ``serve`` / ``main`` — MCP по stdio (JSON-RPC 2.0 построчно: initialize, tools/list, tools/call, ping).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

VERSION = "1"
PROTOCOL = "2025-06-18"
HTTP_TIMEOUT = 25
SECRETS_DIR = Path.home() / ".config/gastech-mcp"
CONFIRM_DIR = Path.home() / ".local/state/gas-pult/confirm"
_ID = re.compile(r"^[0-9a-f]{12}$")


class ToolError(Exception):
    """Понятная ошибка инструмента: уходит модели как текст с ``isError``."""


# ---------- секреты ----------
def read_secret(svc: str) -> str:
    """Содержимое файла ключа. Путь — ``GAS_<SVC>_KEY_FILE`` или ``~/.config/gastech-mcp/<svc>.token``."""
    p = Path(os.environ.get(f"GAS_{svc.upper()}_KEY_FILE") or SECRETS_DIR / f"{svc}.token").expanduser()
    try:
        raw = p.read_text(encoding="utf-8").strip()
    except OSError:
        raise ToolError(f"нет файла ключа {p.name} — положите его в {p.parent} (права 0600), "
                        f"см. docs/connectors/{svc}.md") from None
    if not raw:
        raise ToolError(f"файл ключа {p.name} пустой")
    return raw


def secret_values(raw: str) -> list[str]:
    """Что прятать: сам файл и, если это JSON, все его строковые значения (client_id, api_key, refresh_token…)."""
    out = [raw]
    try:
        data = json.loads(raw)
    except ValueError:
        return out
    if isinstance(data, dict):
        out += [str(v) for v in data.values() if isinstance(v, (str, int)) and len(str(v)) >= 6]
    return out


def hide(text: str, *keys: str) -> str:
    for k in sorted({k for k in keys if k and len(k) >= 4}, key=len, reverse=True):
        text = text.replace(k, "***")
    return text


# ---------- HTTP ----------
class Throttle:
    """Не больше ``n`` запросов за ``per`` секунд (скользящее окно): лимиты вендора, напр. МойСклад 45/3 с."""

    def __init__(self, n: int, per: float):
        self.n, self.per, self.t, self.lock = n, per, deque(), threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            while self.t and now - self.t[0] >= self.per:
                self.t.popleft()
            if len(self.t) >= self.n:
                time.sleep(self.per - (now - self.t[0]))
                self.t.popleft()
            self.t.append(time.monotonic())


def base_url(svc: str, default: str) -> str:
    return (os.environ.get(f"GAS_{svc.upper()}_BASE") or default).rstrip("/")


def _unzip(raw: bytes, headers) -> bytes:
    """Ответ в gzip (МойСклад отдаёт только так и требует ``Accept-Encoding: gzip``) — распаковать."""
    if raw and (headers.get("Content-Encoding") or "").lower() == "gzip":
        try:
            return gzip.decompress(raw)
        except (OSError, EOFError):
            return b""
    return raw


def http(method: str, url: str, *, headers: dict | None = None, body=None, query: dict | None = None,
         keys: list[str] | tuple = (), throttle: Throttle | None = None, service: str = "сервис"):
    """Запрос с JSON. Возвращает разобранный JSON (или текст, если не JSON). Ошибки — ToolError без ключа."""
    if query:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method.upper(), headers={
        "Accept": "application/json", "User-Agent": "gas-pult-connector/1",
        **({"Content-Type": "application/json"} if data is not None else {}), **(headers or {})})
    if throttle:
        throttle.wait()
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            raw = _unzip(r.read(), r.headers)
    except urllib.error.HTTPError as e:
        # сначала скрыть ключ, потом резать: иначе ключ на границе обреза утёк бы кусками
        detail = hide(_unzip(e.read(), e.headers).decode("utf-8", "replace"), *keys)[:300]
        hint = {401: " — ключ не подходит или истёк", 403: " — у ключа нет прав на это",
                404: " — не найдено", 429: " — лимит запросов, подождите"}.get(e.code, "")
        if e.code == 429 and e.headers.get("Retry-After"):
            hint += f" {e.headers['Retry-After']} с"
        raise ToolError(hide(f"{service} ответил {e.code}{hint}: {detail}", *keys)) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ToolError(hide(f"{service} недоступен: {getattr(e, 'reason', e)}", *keys)) from None
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")


# ---------- запись: черновик → подтверждение человека → выполнение ----------
def _digest(action: str, params: dict) -> str:
    return hashlib.sha256(json.dumps([action, params], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _dir(svc: str) -> Path:
    d = Path(os.environ.get("GAS_CONFIRM_DIR") or CONFIRM_DIR).expanduser() / svc
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def propose(svc: str, action: str, params: dict, summary: str) -> dict:
    """Черновик операции. Ничего не пишет в сервис: возвращает id, который человек подтверждает в пульте."""
    pid = secrets.token_hex(6)
    rec = {"id": pid, "svc": svc, "action": action, "params": params, "summary": summary,
           "digest": _digest(action, params), "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "pane": os.environ.get("TMUX_PANE", "")}     # из какого чата: панель покажет «Да» и вернёт туда (drafts.py)
    f = _dir(svc) / f"{pid}.json"
    f.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    f.chmod(0o600)
    return {"id": pid, "action": action, "params": params, "summary": summary,
            "status": "черновик: ждёт подтверждения человеком в пульте; затем вызовите apply с этим id"}


CONFIRM_ONLY_PANEL = "подтверждение — только кнопкой «Да» в панели Ладеи (черновик виден в «Ждут вашего «Да»»)"


def confirm(svc: str, pid: str) -> None:
    """Раньше — «Да» файлом ``.ok`` (команда или пульт). Убрано (штаб 22.11): агент от того же пользователя Linux
    мог вызвать это сам. «Да» — только в панели, сессией человека (``approvals.py``)."""
    raise ToolError(CONFIRM_ONLY_PANEL)


def _panel_ok(svc: str, pid: str, digest: str) -> bool:
    """Спросить службу панели: человек нажал «Да» ровно на этот черновик? Одноразово. Пространство — своим токеном
    моста (``GAS_PULT_BRIDGE_TOKEN_FILE``), владелец — ``bridge-local.token`` из папки данных пульта."""
    url = os.environ.get("GAS_PULT_PANEL_URL", "http://127.0.0.1:8765").rstrip("/") + "/api/drafts/check"
    space = os.environ.get("GAS_PULT_BRIDGE_TOKEN_FILE", "")
    own = os.environ.get("GAS_PULT_LOCAL_TOKEN_FILE") or str(
        Path(os.environ.get("GAS_PULT_DATA_DIR") or Path.home() / ".local/share/gas-pult") / "bridge-local.token")
    try:
        tok = Path(space or own).read_text(encoding="utf-8").strip()
    except OSError:
        return False
    head = {"Content-Type": "application/json", ("X-GP-Space-Token" if space else "X-GP-Local"): tok}
    req = urllib.request.Request(url, json.dumps({"svc": svc, "id": pid, "digest": digest}).encode(), head)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read() or b"{}").get("ok") is True
    except (OSError, ValueError):
        return False


def _load(svc: str, pid: str) -> dict:
    if not _ID.match(str(pid)):
        raise ToolError("неверный id черновика")
    f = _dir(svc) / f"{pid}.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ToolError("черновик не найден (или уже выполнен)") from None


def take_confirmed(svc: str, pid: str, need_flag: bool = True, approve=None) -> dict:
    """Черновик к выполнению — только если запись включена (``GAS_<SVC>_WRITE=1``) и человек подтвердил ровно его.
    Одноразово: после выдачи черновик помечается выполненным. ``need_flag=False`` — без флага записи: мост на Маке
    (запись включает сам человек разрешением macOS, каждое действие — его «Да»). ``approve(svc, id, отпечаток)`` —
    проверка «Да» в том же процессе (мост в службе панели); без неё — запрос к службе панели."""
    if need_flag and os.environ.get(f"GAS_{svc.upper()}_WRITE", "0") != "1":
        raise ToolError(f"запись выключена (GAS_{svc.upper()}_WRITE=0): коннектор работает только на чтение")
    rec = _load(svc, pid)
    dg = _digest(rec["action"], rec["params"])
    if not (approve or _panel_ok)(svc, pid, dg):
        raise ToolError("нет подтверждения человека для этого черновика — покажите его человеку: «Да» — в панели "
                        "Ладеи («Ждут вашего «Да»»). Отметки на диске и команды подтверждения не действуют")
    d = _dir(svc)
    (d / f"{pid}.json").rename(d / f"{pid}.done")
    return rec


# ---------- MCP по stdio ----------
def _text(v) -> str:
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=1)


def handle(server: dict, msg: dict) -> dict | None:
    mid, method = msg.get("id"), msg.get("method", "")
    if mid is None:
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
            text, err = _text(tool["fn"](p.get("arguments") or {})), False
        except ToolError as e:
            text, err = str(e), True
        except (ValueError, TypeError, KeyError) as e:
            text, err = f"неверные параметры или неожиданный ответ сервиса: {e}", True
        try:
            keys = server.get("keys", list)()
        except ToolError:
            keys = []
        return ok({"content": [{"type": "text", "text": hide(text, *keys)}], "isError": err})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"метод не поддерживается: {method}"}}


def serve(server: dict, inp=None, out=None):
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


def main(server: dict, svc: str, argv: list[str] | None = None) -> int:
    """Без аргументов — MCP-сервер. ``confirm`` больше нет: «Да» — только в панели."""
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["confirm"]:                     # убрано (штаб 22.11): «Да» — только в панели
        print(CONFIRM_ONLY_PANEL, file=sys.stderr)
        return 2
    if argv:
        print(f"использование: {svc}_mcp.py (без аргументов — MCP-сервер)", file=sys.stderr)
        return 2
    serve(server)
    return 0
