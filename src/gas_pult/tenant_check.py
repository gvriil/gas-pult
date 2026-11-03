"""Автотест изоляции пространств (задача 25, часть B): ``sudo bin/pult-tenant check <A> <B>``.

От имени пользователя пространства A выполняются попытки: прочитать файлы и папки B, домашнюю папку владельца и
его файлы, увидеть процессы B и прочитать их окружение (``/proc/<pid>/environ``), окружение процесса владельца,
подключиться к сокету tmux B. Каждая должна получить отказ. Контроль — A читает свою домашнюю папку: если и это
не вышло, проверка ничего не доказывает (ПРОВАЛ).

Два места, откуда пробуем:
- «окно A» — внутри песочницы службы tmux пространства A (``nsenter`` в её пространство имён монтирования, затем
  ``runuser``): ровно то, что видит Claude Code в окне A. Здесь процессы B не должны быть даже видны
  (``ProtectProc=invisible``).
- «права файлов» — просто ``runuser -u <A>`` без песочницы: права на файлы сами по себе. Видимость чужих процессов
  здесь обязательна, только если включён ``hidepid`` (``pult-tenant-setup hidepid``), иначе — ВНИМАНИЕ.

Итог — таблица ОК / ПРОВАЛ / ВНИМАНИЕ и код возврата: 0 — все обязательные попытки получили отказ, 1 — есть ПРОВАЛ,
2 — неверный вызов. Сама проба (``PROBE``) — небольшая программа на стандартной библиотеке: ничего не пишет.
"""

from __future__ import annotations

import json
import os
import pwd
import subprocess
import sys
import time
from pathlib import Path

from gas_pult import tenants

PROBE = r'''
import json, os, socket, sys


def probe(items):
    """[[вид, путь], …] → ["denied" | "allowed" | "error:<тип>", …]. Отказ — нет прав или пути не видно."""
    out = []
    for kind, path in items:
        try:
            if kind == "read":
                with open(path, "rb") as fh:
                    fh.read(1)
            elif kind == "list":
                os.listdir(path)
            elif kind == "connect":
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(3)
                try:
                    s.connect(path)
                finally:
                    s.close()
            elif kind == "see":
                if not os.path.exists(path):
                    raise FileNotFoundError(path)
            else:
                raise ValueError(kind)
            out.append("allowed")
        except (PermissionError, FileNotFoundError):
            out.append("denied")
        except Exception as e:                      # ConnectionRefused и прочее: путь достижим — это не отказ
            out.append("error:" + type(e).__name__)
    return out


if __name__ == "__main__":
    print(json.dumps(probe(json.loads(sys.argv[1]))))
'''

SANDBOX, PLAIN = "окно A", "права файлов"
OWNER_FILES = (".claude/.credentials.json", ".claude.json", ".config/gas-pult/token", ".config/gas-pult/secrets.json",
               ".ssh/id_ed25519", ".bashrc", ".profile")


def pids_of(uid: int, proc: Path = Path("/proc"), limit: int = 3) -> list[int]:
    """Процессы пользователя (по реальному uid из /proc/<pid>/status); root видит все."""
    out = []
    try:
        names = sorted((n for n in os.listdir(proc) if n.isdigit()), key=int)
    except OSError:
        return out
    for n in names:
        try:
            for line in (proc / n / "status").read_text().splitlines():
                if line.startswith("Uid:"):
                    if int(line.split()[1]) == uid:
                        out.append(int(n))
                    break
        except (OSError, ValueError, IndexError):
            continue
        if len(out) >= limit:
            break
    return out


def hidepid_on(mounts: Path = Path("/proc/mounts")) -> bool:
    try:
        for line in mounts.read_text().splitlines():
            f = line.split()
            if len(f) > 3 and f[1] == "/proc" and any(o in f[3].split(",") for o in
                                                       ("hidepid=invisible", "hidepid=2", "hidepid=noaccess",
                                                        "hidepid=1")):
                return True
    except OSError:
        pass
    return False


def targets(a: str, b: str, base_root: Path, owner_home: Path | None, b_pids: list[int], owner_pids: list[int],
            exists=os.path.exists) -> list[dict]:
    """Что пробуем из A. ``want`` — ожидаемый итог; ``see`` — строка про видимость процесса (обязательна не везде).
    Путь, которого нет и для root, — строка «не проверено» (``missing``): это ПРОВАЛ, а не тихий пропуск."""
    pa, pb = tenants.paths(a, base_root), tenants.paths(b, base_root)
    rows = [{"what": "контроль: A читает свою домашнюю папку", "kind": "list", "path": pa["home"],
             "want": "allowed"}]
    for what, kind, path in (
            ("список папки B", "list", pb["base"]),
            ("прочитать tenant.json B", "read", pb["meta"]),
            ("прочитать secrets.json B", "read", pb["secrets"]),
            ("прочитать audit.jsonl B", "read", pb["audit"]),
            ("список домашней папки B", "list", pb["home"]),
            ("список папки Claude B", "list", pb["claude"]),
            ("список журналов Claude B", "list", pb["config_claude_projects"]),
            ("подключиться к сокету tmux B", "connect", pb["socket"])):
        rows.append({"what": what, "kind": kind, "path": path, "want": "denied"})
    if owner_home:
        rows.append({"what": "список домашней папки владельца", "kind": "list", "path": owner_home,
                     "want": "denied"})
        for rel in OWNER_FILES:
            if exists(owner_home / rel):
                rows.append({"what": f"прочитать ~владельца/{rel}", "kind": "read", "path": owner_home / rel,
                             "want": "denied"})
    if not b_pids:
        rows.append({"what": "процессы B: ни одного не найдено", "kind": "see", "path": None, "want": "denied"})
    for pid in b_pids:
        rows.append({"what": f"увидеть процесс B {pid}", "kind": "see", "path": Path(f"/proc/{pid}"), "want": "denied",
                     "see": True})
        rows.append({"what": f"окружение процесса B {pid}", "kind": "read", "path": Path(f"/proc/{pid}/environ"),
                     "want": "denied"})
    for pid in owner_pids[:1]:
        rows.append({"what": f"окружение процесса владельца {pid}", "kind": "read",
                     "path": Path(f"/proc/{pid}/environ"), "want": "denied"})
    for r in rows:
        r["missing"] = r["path"] is None or (r["kind"] != "see" and not exists(r["path"]))
    return rows


def probe_argv(user: str, items: list, ns_pid: int | None = None, python: str = "/usr/bin/python3") -> list[str]:
    cmd = ["runuser", "-u", user, "--", python, "-I", "-c", PROBE, json.dumps(items)]
    return ["nsenter", "-t", str(ns_pid), "-m", "--", *cmd] if ns_pid else cmd


def run_probe(runner, argv: list[str], n: int) -> list[str] | str:
    """Результаты пробы или текст ошибки (тогда все её строки — ПРОВАЛ: проверить не удалось)."""
    try:
        r = runner(argv, capture_output=True, text=True, timeout=60, cwd="/")
    except (OSError, subprocess.SubprocessError) as e:
        return f"проба не запустилась: {e}"
    try:
        res = json.loads((r.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return f"проба не ответила (код {r.returncode}): {(r.stderr or '').strip()[:200]}"
    if not isinstance(res, list) or len(res) != n:
        return "проба ответила не то"
    return res


def verdicts(context: str, rows: list[dict], res: list[str] | str, see_required: bool) -> list[tuple]:
    """(место, попытка, итог, пояснение); итог — ОК / ПРОВАЛ / ВНИМАНИЕ."""
    out, live = [], [r for r in rows if not r["missing"]]
    for r in rows:
        if r["missing"]:
            out.append((context, r["what"], "ПРОВАЛ", "не проверено: цели нет — запустите пространство B"
                        if r["kind"] in ("see", "connect") else "не проверено: цели нет"))
    if isinstance(res, str):
        return out + [(context, r["what"], "ПРОВАЛ", res) for r in live]
    for r, got in zip(live, res, strict=True):
        if got == r["want"]:
            out.append((context, r["what"], "ОК", "отказ" if got == "denied" else "доступ есть"))
        elif r.get("see") and not see_required:
            out.append((context, r["what"], "ВНИМАНИЕ", "процесс виден: нет hidepid (pult-tenant-setup hidepid)"))
        elif r["want"] == "allowed":
            out.append((context, r["what"], "ПРОВАЛ", f"контроль не прошёл ({got}) — проверка ничего не доказывает"))
        else:
            out.append((context, r["what"], "ПРОВАЛ", "ДОСТУП ЕСТЬ" if got == "allowed" else got))
    return out


def table(a: str, b: str, rows: list[tuple]) -> str:
    w = max([len(r[1]) for r in rows] + [10])
    lines = [f"Проверка изоляции: из {a} к {b} и владельцу", f"{'Где':<13} {'Попытка':<{w}} {'Итог':<9} Пояснение"]
    lines += [f"{c:<13} {what:<{w}} {v:<9} {note}" for c, what, v, note in rows]
    fails = sum(r[2] == "ПРОВАЛ" for r in rows)
    warns = sum(r[2] == "ВНИМАНИЕ" for r in rows)
    lines.append(f"Итого: {len(rows)} попыток, ПРОВАЛ: {fails}, ВНИМАНИЕ: {warns} — "
                 + ("изоляция в порядке" if not fails else "ИЗОЛЯЦИЯ НАРУШЕНА или не проверена"))
    return "\n".join(lines)


def check(a: str, b: str, base_root: Path, owner_home: Path | None, runner=subprocess.run, service_pid=None,
          b_pids=None, owner_pids=None, hidepid: bool | None = None, exists=os.path.exists,
          out=print) -> int:
    """Проверка целиком; всё системное — параметрами (тесты подставляют моки). 0 — изоляция в порядке, 1 — нет."""
    a, b = tenants.check_slug(a), tenants.check_slug(b)
    if a == b:
        raise ValueError("нужны два разных пространства: check <A> <B>")
    ua = tenants.user_of(a)
    rows = targets(a, b, base_root, owner_home, list(b_pids or []), list(owner_pids or []), exists)
    items = [[r["kind"], str(r["path"])] for r in rows if not r["missing"]]
    result = []
    if service_pid:
        res = run_probe(runner, probe_argv(ua, items, service_pid), len(items))
        result += verdicts(SANDBOX, rows, res, see_required=True)
    else:
        result.append((SANDBOX, "служба tmux пространства A", "ПРОВАЛ",
                       f"не запущена — systemctl start {ua}.service и повторите"))
    res = run_probe(runner, probe_argv(ua, items), len(items))
    result += verdicts(PLAIN, rows, res, see_required=bool(hidepid))
    out(table(a, b, result))
    return 1 if any(r[2] == "ПРОВАЛ" for r in result) else 0


def main(base_root: Path, a: str, b: str, owner: str | None = None, runner=subprocess.run) -> int:
    """``pult-tenant check``: собирает с системы pid, домашнюю папку владельца и состояние hidepid, запускает
    ``check``. Если у B нет ни одного процесса — на время проверки запускается ``sleep`` от имени B."""
    try:
        a, b = tenants.check_slug(a), tenants.check_slug(b)
        owner = owner or os.environ.get("SUDO_USER") or ""
        home = Path(pwd.getpwnam(owner).pw_dir) if owner else None
        ub = pwd.getpwnam(tenants.user_of(b))
        owner_uid = pwd.getpwnam(owner).pw_uid if owner else None
    except (ValueError, KeyError) as e:
        print(f"Ошибка: {e if isinstance(e, ValueError) else f'нет пользователя {e}'}", file=sys.stderr)
        return 2
    if not owner:
        print("! не знаю владельца (--owner): его домашняя папка не проверяется", file=sys.stderr)
    svc = f"{tenants.user_of(a)}.service"
    main_pid = runner(["systemctl", "show", "-p", "MainPID", "--value", svc], capture_output=True, text=True).stdout
    service_pid = int(main_pid.strip()) if main_pid.strip().isdigit() and int(main_pid.strip()) > 0 else None
    temp = None
    b_pids = pids_of(ub.pw_uid)
    if not b_pids:
        temp = subprocess.Popen(["runuser", "-u", ub.pw_name, "--", "sleep", "60"])
        for _ in range(20):
            if b_pids := pids_of(ub.pw_uid):
                break
            time.sleep(0.1)
    try:
        return check(a, b, base_root, home, runner, service_pid, b_pids,
                     pids_of(owner_uid) if owner_uid is not None else [], hidepid_on())
    finally:
        if temp:
            temp.kill()
            temp.wait()
