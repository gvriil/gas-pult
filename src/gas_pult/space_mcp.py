"""Свои интеграции (MCP) демо-пространства из панели (GAS-38 (в)): у каждого пространства свои ключи и подключения.

Решение штаба 21.11: «у каждого пространства свои ключи и подключения, хранятся отдельно, чужие недоступны». Формат —
тот же, что у ``pult-tenant mcp`` (docs/TENANTS.md, шаг 4а): запись — в ``config/claude/.claude.json`` пространства
(``mcpServers``, её читает Claude Code пространства через ``CLAUDE_CONFIG_DIR``), файлы — в ``config/mcp/`` (0600,
владелец — пользователь пространства). Ключ сервиса по адресу — в заголовке записи ``.claude.json`` (как делает
``claude mcp add-json``), ключ веб-поиска — в файле ``config/mcp/<имя>.key``, в записи — только путь.

Пульт в пространство не пишет и его ``config/claude`` не читает: всё — командой от пользователя пространства
(``tmux run-shell`` в его tmux, как ``space_sessions.sh``). Данные с ключом в команду не попадают (её видно в списке
процессов): они уходят через стандартный ввод ``tmux load-buffer`` в буфер tmux пространства, команда забирает их
оттуда (``save-buffer``) и сразу удаляет буфер. В ответ команда печатает только имена, тип и адрес — без заголовков
и окружения; адрес панель сокращает до сервиса (в адресе бывает ключ).

Каталог — шаблоны владельца (``mcp.PRESETS``), которые работают в песочнице пространства без sudo: серверы по адресу
и веб-поиск (копия ``base_mcp.py`` — в ``config/mcp``). Нет: «Своя программа» (только владельцу), Диск через rclone
и «Документы» (ставит владелец: ``pult-tenant mcp``/``docs``), секрет клиента OAuth (хранилище ключей Claude Code).
"""

from __future__ import annotations

import json
import secrets
import shlex
import subprocess
import urllib.parse

from gas_pult import mcp, space_sessions, tenants

RESERVED = {"browser-local", "docs"}          # ставит владелец (pult-tenant bridge/docs): из панели не трогаем
TAG = "GPMCP:"

# Выполняется в пространстве (python3 пространства, только стандартная библиотека): на входе — JSON из буфера tmux.
SCRIPT = r"""
import json, os, sys, tempfile
p = json.load(sys.stdin)
cj, d, op, n = p["cj"], p["dir"], p["op"], p.get("name", "")
def out(x):
    print("GPMCP:" + json.dumps(x, ensure_ascii=False)); sys.exit(0)
def save(path, text):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".gp-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, 0o600); os.replace(tmp, path)
try:
    with open(cj, encoding="utf-8") as f:
        cfg = json.load(f)
except FileNotFoundError:
    cfg = {}
except ValueError:
    out({"error": "настройки Claude Code пространства не читаются — попросите владельца"})
if not isinstance(cfg, dict):
    out({"error": "настройки Claude Code пространства не читаются — попросите владельца"})
srv = cfg.get("mcpServers") if isinstance(cfg.get("mcpServers"), dict) else {}
if op == "add":
    if n in srv:
        out({"error": "интеграция с таким названием уже есть — сначала отключите её"})
    for fn, text in p["files"].items():
        save(os.path.join(d, fn), text)
    srv[n] = p["cfg"]; cfg["mcpServers"] = srv
    save(cj, json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
elif op == "remove":
    if n not in srv:
        out({"error": "такой интеграции нет — обновите список"})
    del srv[n]; cfg["mcpServers"] = srv
    save(cj, json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
    for fn in p["files"]:
        try:
            os.unlink(os.path.join(d, fn))
        except OSError:
            pass
out({"servers": [{"name": k, "type": str(v.get("type") or "stdio"), "url": str(v.get("url") or ""),
                  "command": os.path.basename(str(v.get("command") or ""))}
                 for k, v in srv.items() if isinstance(v, dict)]})
"""


def presets() -> list[dict]:
    """Каталог пространства: серверы по адресу и веб-поиск. Поле секрета клиента OAuth убрано (оно — в хранилище
    ключей Claude Code, его из панели в пространство не положить); шаблон, где оно обязательно, — не показываем."""
    out = []
    for p in mcp.PRESETS:
        if p["type"] != "http" and p.get("server") != "search":
            continue
        if any(f.get("oauth_secret") and not f.get("optional") for f in p["fields"]):
            continue
        out.append({**p, "fields": [f for f in p["fields"] if not f.get("oauth_secret")]})
    return out


def _paths(slug: str) -> dict:
    p = tenants.paths(slug)
    return {"cj": str(p["claude"] / ".claude.json"), "dir": str(p["config"] / "mcp")}


def _inner(tm) -> list[str]:
    """tmux пространства изнутри его песочницы: без ``sudo -n -u <user>`` — команда уже от его пользователя."""
    return tm.tmux[4:] if tm.tmux[:1] == ["sudo"] else list(tm.tmux)


def run(slug: str, payload: dict, timeout: int = 30) -> dict:
    """Команда в пространстве: данные — через буфер tmux (стандартный ввод), не в строке команды."""
    tm = tenants.tmux_of(slug)
    tm.ensure_session()
    buf = "gp-mcp-" + secrets.token_hex(8)
    data = json.dumps({**_paths(slug), **payload}, ensure_ascii=False)
    try:
        r = subprocess.run([*tm.tmux, "load-buffer", "-b", buf, "-"], input=data, capture_output=True, text=True,
                           timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError("пространство не ответило — попробуйте ещё раз")
        t = " ".join(shlex.quote(x) for x in _inner(tm))
        b = shlex.quote(buf)
        got = space_sessions.sh(slug, f"{t} save-buffer -b {b} - | python3 -c {shlex.quote(SCRIPT)}; r=$?; "
                                      f"{t} delete-buffer -b {b} 2>/dev/null; exit $r", timeout=timeout)
    finally:
        subprocess.run([*tm.tmux, "delete-buffer", "-b", buf], capture_output=True, timeout=10)
    line = next((x for x in reversed(got.splitlines()) if x.startswith(TAG)), "")
    try:
        res = json.loads(line[len(TAG):])
    except ValueError:
        raise RuntimeError("пространство не ответило — попробуйте ещё раз") from None
    if res.get("error"):
        raise ValueError(res["error"])
    return res


def public(rows: list[dict]) -> list[dict]:
    """Для панели: имя, тип и сервис (адрес — только схема и сервер: в адресе бывает ключ). Без заголовков и env."""
    out = []
    for x in rows:
        name = str(x.get("name") or "")
        u = urllib.parse.urlsplit(str(x.get("url") or ""))
        target = f"{u.scheme}://{u.hostname}" if u.scheme and u.hostname else str(x.get("command") or "")
        out.append({"name": name, "type": x.get("type") or "stdio", "target": target,
                    "removable": name not in RESERVED})
    return sorted(out, key=lambda x: x["name"])


def listing(slug: str) -> list[dict]:
    return public(run(slug, {"op": "list"})["servers"])


def add(slug: str, preset_id: str, name: str, values: dict) -> dict:
    """Подключить шаблон каталога в пространстве. Ключ — в его ``.claude.json`` (сервер по адресу) или в файл 0600
    ``config/mcp/<имя>.key`` (веб-поиск). В ответе ключа нет."""
    p = next((x for x in presets() if x["id"] == preset_id), None)
    if not p:
        raise ValueError("нет такого шаблона")
    if not mcp.NAME.match(name or ""):
        raise ValueError("имя: латиница в нижнем регистре, цифры, - или _ (2–41 знак)")
    if name in RESERVED:
        raise ValueError("это название занято — выберите другое")
    vals = mcp.values_of(p, values if isinstance(values, dict) else {})
    d = _paths(slug)["dir"]
    files: dict[str, str] = {}
    if p["type"] == "http":
        cfg = mcp.http_config(p, vals)
    else:                                              # веб-поиск: свой сервер пульта, копия — в config/mcp
        env, key = mcp.search_env(vals, f"{d}/{name}.key")
        files = {f"{name}.key": key + "\n", "base_mcp.py": mcp.BASE_SERVER.read_text(encoding="utf-8")}
        cfg = {"type": "stdio", "command": "/usr/bin/python3", "args": [f"{d}/base_mcp.py", "search"], "env": env}
    res = run(slug, {"op": "add", "name": name, "cfg": cfg, "files": files})
    return {"result": "подключено. " + (p["after"] or "Перезапустите открытые сессии — интеграция появится в них."),
            "servers": public(res["servers"])}


def remove(slug: str, name: str) -> dict:
    if not mcp.NAME.match(name or ""):
        raise ValueError("такой интеграции нет — обновите список")
    if name in RESERVED:
        raise ValueError("эту интеграцию подключил владелец — отключает тоже он")
    res = run(slug, {"op": "remove", "name": name, "files": [f"{name}.key"]})
    return {"result": "отключено", "servers": public(res["servers"])}
