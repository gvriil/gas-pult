"""Команды из ответов Claude → отдельные сообщения с кнопкой «▶️ Выполнить на <хост>».

- Блок ```bash / ```sh / ``` без языка = команда; блоки-промпты (проза) пропускаются.
- Команды для другой машины (macOS-пути на Linux и наоборот, свои шаблоны из ``foreign``) — без кнопки.
- Команды, которые спрашивают пароль (pass, gpg, ssh-add, read -s …), — без кнопки: у ▶️ нет терминала.
- sudo — только из списка ``sudo_allow`` (и только если у пользователя настроен sudo без пароля).
- Опасное (rm -r, push --force, DROP, reboot …) — второе подтверждение.
- Выполнение: ``bash -o pipefail -lc`` в папке окна (упавший ``curl … | bash`` не покажет «код 0»), без stdin,
  таймаут 10 минут; похожее на токены в выводе маскируется.
- ``Journal`` — вкладка «Команды» панели: все команды из ответов всех сессий одним списком, с пометкой
  «выполнено» и кодом выхода; хранится на сервере (``commands-log.json``), переживает перезапуск и закрытие окна.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from gas_pult import people, transcripts

FENCE = re.compile(r"```([\w+-]*)[ \t]*\n(.*?)```", re.S)
SHELL = {"", "bash", "sh", "shell", "zsh", "console"}
ON_LINUX_FOREIGN = [r"/Users/", r"\bbrew\b", r"\blaunchctl\b", r"\bpbcopy\b", r"\bosascript\b", r"\bcaffeinate\b",
                    r"~/\.zshrc"]
ON_MAC_FOREIGN = [r"\bapt(-get)?\s", r"\bsystemctl\b", r"\bjournalctl\b", r"/home/\w+"]
TTY = re.compile(r"(^|[;&|(]\s*)(pass(\s+show)?\s|gpg\s+(--passwd|--edit-key|-d\b|--decrypt)|ssh-add\b|passwd\b|"
                 r"su\s|keepassxc-cli\s|read\s+-\w*s)")   # спросит пароль — у кнопки ▶️ нет терминала
DANGER = re.compile(r"\brm\s+-\w*[rf]|\bgit\s+(push\b.*(--force|\s-f\b)|reset\s+--hard|clean\s+-\w*f)|\bdrop\s+"
                    r"(table|schema|database)\b|\btruncate\b|\breboot\b|\bshutdown\b|\bmkfs|\bdd\s+if=|--apply\b|"
                    r"--write\b|--force\b|\bkill(all)?\b", re.I)
SECRET = re.compile(r"eyJ[\w-]{20,}\.[\w-]{10,}\.[\w-]{10,}|\b\d{8,10}:AA[\w-]{30,}|\bgh[pousr]_\w{20,}|"
                    r"\bsk-[\w-]{20,}|(?i:(password|passwd|token|secret|api[_-]?key)\s*[=:]\s*)\S{6,}")
TIMEOUT = 600
TAIL = 3300
FULL = 1_000_000                            # весь вывод для «Копировать» — до 1 МБ (с конца)
FAIL_LINES = 60                             # столько последних строк вывода уходит в сессию на разбор


def blocks(text: str) -> list[tuple[str, str]]:
    """Команды ответа с пояснением «для чего»: [(команда, пояснение)]."""
    out = []
    for m in FENCE.finditer(text):
        lang, body = m.group(1), m.group(2)
        if lang.lower() not in SHELL:
            continue
        lines = [re.sub(r"^!\s+", "", line) for line in body.strip().splitlines()]   # префикс «!» Claude Code
        prose = sum(1 for line in lines if re.search(r"[А-Яа-яЁё]{4,}\s+[А-Яа-яЁё]{4,}", line)
                    and not line.lstrip().startswith("#"))
        if not lines or len("\n".join(lines)) > 3000 or (not lang and prose > len(lines) / 3):
            continue                     # промпт и прочая проза — не команда
        cmd = "\n".join(lines)
        out.append((cmd, about(cmd, text[:m.start()])))
    return out


def extract(text: str) -> list[str]:
    return [cmd for cmd, _ in blocks(text)]


def about(cmd: str, before: str) -> str:
    """Для чего команда: первая строка-комментарий «# …» в блоке, иначе строка текста перед блоком."""
    for line in cmd.splitlines():
        if line.strip().startswith("#") and not line.startswith("#!"):
            return line.strip().lstrip("#").strip()[:160]
        if line.strip():
            break
    for line in reversed(before.rstrip().splitlines()):
        line = re.sub(r"[*_`]+|^\s*(?:[-*+]|\d+[.)])\s+|^#+\s*", "", line).strip().rstrip(":").strip()
        if line.startswith("```"):
            break
        if line:
            return line[:160]
    return ""


def triage_text(cmd: str, code, out: str) -> str:
    """Сообщение в сессию, откуда пришла команда: команда упала — разобрать и предложить исправление."""
    tail = "\n".join(out.splitlines()[-FAIL_LINES:])[-8000:] or "(вывода нет)"
    return (f"Команда упала — разбери и предложи исправление:\n\n```bash\n{cmd}\n```\n\n"
            f"Код выхода: {code}. Последние строки вывода:\n\n```\n{tail}\n```")


def fail_key(path: str, cmd: str, code, out: str) -> str:
    """Отпечаток ошибки: та же команда, тот же код, тот же хвост вывода — та же ошибка."""
    tail = "\n".join(out.splitlines()[-FAIL_LINES:])
    return hashlib.sha256(f"{path}|{cmd}|{code}|{tail}".encode()).hexdigest()[:16]


def mask(out: str) -> str:
    return SECRET.sub(lambda m: (m.group(1) + "=" if m.group(1) else "") + "•••", out)


def execute(cmd: str, cwd: str | None) -> tuple[int | str, float, str]:
    """Выполнить команду: (код возврата или «timeout», секунды, вывод с замаскированными секретами)."""
    cmd = re.sub(r"(^|[;&|]\s*)sudo\s+(?!-n\b)", r"\1sudo -n ", cmd, flags=re.M)   # sudo не ждёт пароль
    t0 = time.time()
    try:
        r = subprocess.run(["bash", "-o", "pipefail", "-lc", cmd], cwd=cwd if cwd and os.path.isdir(cwd) else None,
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT)
        out, code = (r.stdout + ("\n" + r.stderr if r.stderr else "")).strip(), r.returncode
    except subprocess.TimeoutExpired:
        out, code = f"прервано: дольше {TIMEOUT // 60} минут", "timeout"
    return code, time.time() - t0, mask(out)


class Commands:
    def __init__(self, host: str, store: Path, sudo_allow: list[str], foreign: list[str], platform: str = sys.platform,
                 on_done=None, on_start=None):
        self.host, self.store = host, store
        self.on_start = on_start            # (команда, папка) — «выполняется» во вкладке «Команды»
        self.on_done = on_done              # (команда, папка, код, секунды, вывод) — отметить во вкладке «Команды»
        self.sudo_ok = re.compile(r"^\s*sudo\s+(-n\s+)?(" + "|".join(f"(?:{p})" for p in sudo_allow) + ")"
                                  if sudo_allow else r"(?!)")
        base = ON_MAC_FOREIGN if platform == "darwin" else ON_LINUX_FOREIGN
        self.foreign = re.compile("|".join(base + foreign))

    def kind(self, cmd: str) -> str:
        if self.foreign.search(cmd):
            return "foreign"
        if TTY.search(cmd):
            return "tty"
        sudo = [line for line in cmd.splitlines() if re.search(r"(^|[;&|]\s*)sudo\s", line)]
        if any(not self.sudo_ok.match(line) for line in sudo):
            return "sudo"
        return "local"

    def _load(self) -> dict:
        try:
            return json.loads(self.store.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, d: dict):
        self.store.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        keep = dict(sorted(d.items(), key=lambda kv: kv[1]["ts"])[-200:])
        self.store.write_text(json.dumps(keep, ensure_ascii=False))
        self.store.chmod(0o600)

    def offer(self, w: dict, text: str, send, kb):
        """Каждая команда ответа — своим сообщением; send/kb — функции пульта."""
        cmds = extract(text)
        if not cmds:
            return
        d = self._load()
        for i, cmd in enumerate(cmds, 1):
            k = self.kind(cmd)
            head = f"[{html.escape(w['name'])}] команда {i}/{len(cmds)}"
            body = f'<pre><code class="language-bash">{html.escape(cmd)}</code></pre>'
            if k == "foreign":
                send(f"{head} · 💻 для другой машины — нажми, чтобы скопировать\n{body}", parse_mode="HTML")
            elif k == "tty":
                send(f"{head} · ⌨️ спросит пароль — только в терминале, кнопкой не выполнится\n{body}",
                     parse_mode="HTML")
            elif k == "sudo":
                send(f"{head} · 🔐 sudo вне разрешённого списка — только вручную\n{body}", parse_mode="HTML")
            else:
                cid = uuid.uuid4().hex[:10]
                d[cid] = {"cmd": cmd, "cwd": w["path"], "win": w["name"], "ts": time.time()}
                folder = html.escape(os.path.basename(w["path"]) or "~")
                send(f"{head} · 🖥 {html.escape(self.host)}, папка {folder}\n{body}", parse_mode="HTML",
                     reply_markup=kb([[(f"▶️ Выполнить на {self.host}", f"run:{cid}")]]))
        self._save(d)

    def run(self, cid: str, confirmed: bool, send, kb, send_file=None):
        c = self._load().get(cid)
        if not c:
            return send("Эта команда уже забыта — попроси Claude прислать её снова.")
        if DANGER.search(c["cmd"]) and not confirmed:
            return send(f"⚠️ Команда меняет или удаляет данные:\n<pre>{html.escape(c['cmd'][:1500])}</pre>",
                        parse_mode="HTML",
                        reply_markup=kb([[("⚠️ Да, выполнить", f"runok:{cid}"), ("Отмена", "noop:")]]))
        send(f"⏳ [{html.escape(c['win'])}] выполняю…", parse_mode="HTML")
        if self.on_start:
            try:
                self.on_start(c["cmd"], c["cwd"])
            except Exception as e:
                print(f"gas-pult: перед выполнением команды: {e}", file=sys.stderr)
        code, secs, out = execute(c["cmd"], c["cwd"])
        note = ""
        if self.on_done:
            try:
                r = self.on_done(c["cmd"], c["cwd"], code, secs, out)
                note = r if isinstance(r, str) else ""
            except Exception as e:          # отметка и разбор — не повод потерять итог выполнения
                print(f"gas-pult: после выполнения команды: {e}", file=sys.stderr)
        tail = out[-TAIL:]
        mark = "✅" if code == 0 else "❌"
        cut = len(out) > TAIL
        send(f"{mark} код {code} · {secs:.0f} с" + (" · показан конец вывода, весь — файлом ниже" if cut and send_file
                                                     else " · показан конец вывода" if cut else "")
             + (f"\n<pre>{html.escape(tail)}</pre>" if tail else " · вывода нет")
             + (f"\n{html.escape(note)}" if note else ""), parse_mode="HTML")
        if cut and send_file:               # весь вывод — файлом: в сообщение не влезает, а скопировать нужно целиком
            send_file("output.txt", out[-FULL:].encode())


class Journal:
    """Все команды из ответов всех сессий — вкладка «Команды» панели (новые сверху).

    Ключ команды — отпечаток (папка, время ответа, текст): одна и та же команда в разных ответах — разные строки.
    Транскрипт папки перечитывается, только когда он изменился (``transcripts.revision``).
    """

    KEEP = 400

    def __init__(self, store: Path):
        self.store = store
        self.lock = threading.Lock()         # панель многопоточная: сбор и отметка не затирают друг друга

    @contextlib.contextmanager
    def locked(self):
        """Поток панели и процесс бота пишут один файл — блокировка и в процессе, и между процессами (flock)."""
        self.store.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.lock, open(self.store.with_suffix(".lock"), "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            yield

    def load(self) -> dict:
        try:
            d = json.loads(self.store.read_text())
            return {"items": d.get("items", {}), "revs": d.get("revs", {}), "triaged": d.get("triaged", {})}
        except (OSError, ValueError, AttributeError):
            return {"items": {}, "revs": {}, "triaged": {}}

    def save(self, d: dict):
        self.store.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        items = dict(sorted(d["items"].items(), key=lambda kv: (kv[1]["ts"], kv[1]["n"]))[-self.KEEP:])
        tmp = self.store.with_suffix(".tmp")
        triaged = dict(sorted(d.get("triaged", {}).items(), key=lambda kv: kv[1])[-500:])
        tmp.write_text(json.dumps({"items": items, "revs": d["revs"], "triaged": triaged}, ensure_ascii=False))
        tmp.chmod(0o600)
        tmp.replace(self.store)

    def collect(self, windows: list[dict], kind) -> bool:
        """Добавить команды из свежих ответов окон; kind(cmd) → local/foreign/tty/sudo. Изменилось ли что-то."""
        with self.locked():
            return self._collect(windows, kind)

    def _collect(self, windows: list[dict], kind) -> bool:
        d, changed = self.load(), False
        for w in windows:
            rev = transcripts.revision(w["path"], people.home_of(w))
            if not rev or d["revs"].get(w["path"]) == rev:
                continue
            d["revs"][w["path"]], changed = rev, True
            items, _ = transcripts.history(w["path"], 80, home=people.home_of(w))
            for m in items:
                if m["role"] != "assistant":
                    continue
                for n, (cmd, why) in enumerate(blocks(m["text"])):
                    cid = hashlib.sha256(f"{w['path']}|{m['ts']}|{n}|{cmd}".encode()).hexdigest()[:12]
                    if cid not in d["items"]:
                        d["items"][cid] = {"id": cid, "cmd": cmd, "about": why, "win": w["name"], "wid": w["id"],
                                           "path": w["path"], "ts": m["ts"], "n": n, "kind": kind(cmd),
                                           "danger": bool(DANGER.search(cmd)), "done": None}
        if changed:
            self.save(d)
        return changed

    @staticmethod
    def status(c: dict) -> dict:
        """Честный статус: ``done`` — только настоящий запуск через пульт; ``manual`` — отметка «сделано вручную»;
        ``running`` — выполняется сейчас (UTC, когда начали). Старая отметка вручную (done.by=hand) — в ``manual``."""
        c = dict(c)
        if (c.get("done") or {}).get("by") == "hand":
            c["manual"], c["done"] = {"at": c["done"].get("at", "")}, None
        c.setdefault("manual", None)
        c.setdefault("running", None)
        return c

    def items(self) -> list[dict]:
        return sorted((self.status(c) for c in self.load()["items"].values()), key=lambda x: (x["ts"], x["n"]),
                      reverse=True)

    def get(self, cid: str) -> dict | None:
        c = self.load()["items"].get(cid)
        return self.status(c) if c else None

    def update(self, cid: str, **fields) -> dict:
        """Поменять поля команды (running, done, manual) — под замком; вернуть команду со статусом."""
        with self.locked():
            d = self.load()
            c = d["items"].get(cid)
            if not c:
                raise LookupError("команды уже нет в списке")
            c.update(self.status(c))
            c.update(fields)
            self.save(d)
            return dict(c)

    def flag_cmd(self, path: str, cmd: str, **fields) -> str | None:
        """Самая свежая такая команда этой папки (её запускают кнопкой ▶️ в боте) — поменять поля; её id."""
        with self.locked():
            d = self.load()
            same = sorted((c for c in d["items"].values() if c["path"] == path and c["cmd"] == cmd),
                          key=lambda c: (c.get("done") is None, c["ts"], c["n"]))
            if not same:
                return None
            same[-1].update(fields)
            self.save(d)
            return same[-1]["id"]

    def triage_once(self, key: str) -> bool:
        """Эту ошибку ещё не отправляли на разбор — запомнить и вернуть True; уже отправляли — False."""
        with self.locked():
            d = self.load()
            if key in d["triaged"]:
                return False
            d["triaged"][key] = time.time()
            self.save(d)
            return True

    def forget_triage(self, key: str):
        """Отправить не вышло (окно закрыто, Claude ждёт ответа) — пусть следующий запуск попробует снова."""
        with self.locked():
            d = self.load()
            if d["triaged"].pop(key, None) is not None:
                self.save(d)

    def save_output(self, cid: str, out: str):
        """Весь вывод команды — отдельным файлом (в журнале — только хвост): для «Копировать вывод»."""
        folder = self.store.parent / "outputs"
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        f = folder / f"{cid}.txt"
        f.write_text(out[-FULL:])
        f.chmod(0o600)
        old = time.time() - 30 * 86400
        for x in folder.glob("*.txt"):          # старше месяца — убрать
            if x.stat().st_mtime < old:
                x.unlink(missing_ok=True)

    def output(self, cid: str) -> str | None:
        if not re.fullmatch(r"[0-9A-Za-z_-]{1,40}", cid):           # только имя файла, без «../»
            return None
        try:
            return (self.store.parent / "outputs" / f"{cid}.txt").read_text()
        except OSError:
            return None

    def mark_cmd(self, path: str, cmd: str, done: dict, out: str | None = None) -> bool:
        """Отметить выполненной самую свежую такую команду этой папки (кнопка ▶️ в боте). Нашлась ли."""
        with self.locked():
            d = self.load()
            same = sorted((c for c in d["items"].values() if c["path"] == path and c["cmd"] == cmd),
                          key=lambda c: (c["done"] is None, c["ts"], c["n"]))
            if not same:
                return False
            same[-1]["done"], same[-1]["running"] = done, None
            self.save(d)
        if out is not None:
            self.save_output(same[-1]["id"], out)
        return True

    def mark(self, cid: str, done: dict | None) -> dict:
        with self.locked():
            d = self.load()
            c = d["items"].get(cid)
            if not c:
                raise LookupError("команды уже нет в списке")
            c["done"] = done
            self.save(d)
            return c
