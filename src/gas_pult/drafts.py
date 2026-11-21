"""Черновики действий коннекторов в «Ждут вашего Да» (штаб 21.11): МойСклад, Битрикс24, WB, Ozon, почта, календарь.

Коннектор (``connectors/_core.propose``) ничего не пишет в сервис: он кладёт черновик в папку подтверждений
``~/.local/state/gas-pult/confirm/<svc>/<id>.json`` того, от чьего имени работает (владелец или пользователь
пространства). Выполнить черновик коннектор может, только когда рядом лежит ``<id>.ok`` с отпечатком ровно этого
черновика (``_core.take_confirmed``). Раньше ``.ok`` ставила только команда ``<svc>_mcp.py confirm <id>``; теперь —
кнопки «Да» / «Нет» в панели.

Изоляция: владелец видит и подтверждает только свои черновики (своя домашняя папка), человек пространства — только
свои: пульт в пространство не пишет, всё — одной программой от пользователя пространства (``space_sessions.sh``,
как ``space_mcp``). Пространство берётся из входа (``Handler.space``), а не из запроса. id и имя сервиса — по
шаблону, в команду — через ``shlex.quote``.

«Нет» — черновик переименовывается в ``<id>.rejected``: выполнить его уже нельзя, след остаётся.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys

from gas_pult import space_sessions, tenants

TAG = "GPDRAFT:"
SVC = re.compile(r"^[a-z0-9_-]{1,24}$")
ID = re.compile(r"^[0-9a-f]{12}$")
LIMIT = 50

# Выполняется от того, чьи черновики (python3, только стандартная библиотека). Аргументы: op [svc id].
SCRIPT = r"""
import json, os, re, sys
from pathlib import Path
a = sys.argv[1:] + ["", "", ""]
op, svc, pid = a[0], a[1], a[2]
root = Path(os.environ.get("GAS_CONFIRM_DIR") or Path.home() / ".local/state/gas-pult/confirm").expanduser()
SVC, ID = re.compile(r"^[a-z0-9_-]{1,24}$"), re.compile(r"^[0-9a-f]{12}$")
def out(x):
    print("GPDRAFT:" + json.dumps(x, ensure_ascii=False)); sys.exit(0)
if op == "list":
    items = []
    for f in sorted(root.glob("*/*.json"), key=lambda p: p.stat().st_mtime):
        d = f.parent.name
        if not SVC.match(d) or not ID.match(f.stem) or (f.parent / (f.stem + ".ok")).exists():
            continue
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items.append({"id": f.stem, "svc": d, "action": str(r.get("action", ""))[:80],
                      "summary": str(r.get("summary", ""))[:600], "created": str(r.get("created", ""))[:40],
                      "pane": str(r.get("pane", ""))[:12]})
    out({"drafts": items[-50:]})
if not SVC.match(svc) or not ID.match(pid):
    out({"error": "неверный черновик"})
f = root / svc / (pid + ".json")
if f.is_symlink() or not f.is_file():
    out({"error": "черновик не найден или уже выполнен"})
if op == "yes":
    try:
        r = json.loads(f.read_text(encoding="utf-8"))
        dg = str(r["digest"])
    except (OSError, ValueError, KeyError):
        out({"error": "черновик повреждён"})
    ok = root / svc / (pid + ".ok")
    ok.write_text(dg, encoding="utf-8")
    ok.chmod(0o600)
    out({"ok": True})
if op == "no":
    f.rename(f.with_suffix(".rejected"))
    out({"ok": True})
out({"error": "неизвестное действие"})
"""


def _parse(text: str) -> dict:
    for line in reversed((text or "").splitlines()):
        if line.startswith(TAG):
            return json.loads(line[len(TAG):])
    raise RuntimeError("черновики не прочитались — попробуйте ещё раз")


def _run(slug: str | None, *args: str) -> dict:
    """Владелец — своей программой; пространство — от пользователя пространства (его домашняя папка)."""
    if slug:                               # папка подтверждений — в домашней папке пространства, как у коннекторов
        home = shlex.quote(str(tenants.paths(slug)["home"]))
        cmd = (f"env -u GAS_CONFIRM_DIR HOME={home} python3 -I -c " + shlex.quote(SCRIPT)
               + "".join(" " + shlex.quote(a) for a in args))
        return _parse(space_sessions.sh(slug, cmd))
    r = subprocess.run([sys.executable, "-I", "-c", SCRIPT, *args], capture_output=True, text=True, timeout=20)
    return _parse(r.stdout)


def _check(svc: str, pid: str) -> None:
    if not SVC.match(str(svc or "")) or not ID.match(str(pid or "")):
        raise ValueError("неверный черновик")


def pending(slug: str | None, chat_of=None) -> list[dict]:
    """Черновики, ждущие «Да». ``chat_of(pane)`` → id окна чата, откуда пришёл черновик (или None)."""
    items = _run(slug, "list").get("drafts", [])[-LIMIT:]
    for x in items:
        pane = x.pop("pane", "")
        x["w"] = (chat_of(pane) if chat_of and re.fullmatch(r"%\d+", pane or "") else None) or None
    return items


def decide(slug: str | None, svc: str, pid: str, yes: bool) -> dict:
    """«Да» — отметка ровно этого черновика (коннектор выполнит его при следующем вызове); «Нет» — отказ."""
    _check(svc, pid)
    r = _run(slug, "yes" if yes else "no", svc, pid)
    if r.get("error"):
        raise ValueError(r["error"])
    return {"ok": True}


def chat_of(tm, pane: str, slug: str | None = None) -> str | None:
    """Окно чата, из которого пришёл черновик: панель «Вернуться в чат». Только окна сессии пульта этого человека."""
    if not re.fullmatch(r"%\d+", pane or ""):
        return None
    raw = (tm.run("display-message", "-p", "-t", pane, "#{window_id}") or "").strip()
    if not re.fullmatch(r"@\d+", raw) or raw not in {w["id"] for w in tm.windows()}:
        return None
    return f"t:{slug}:{raw}" if slug else raw
