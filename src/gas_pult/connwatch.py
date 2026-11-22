"""Сторож входа коннекторов (решение владельца 22.11, фаза 1 из трёх; docs/CONNECTORS.md, «Автовход»).

Коннектор (MCP-сервер, плагин) потерял вход — система входит заново сама; от владельца — самое большее одно окно с
уже заполненными полями. Фаза 1 (здесь): **обнаружение, квитанции, задачи владельцу, заготовка базы паролей**.
Фазы 2–3 (нажать «Разрешить» в Chrome агента, подставить пароль из базы) — потом, через ``relogin``.

- ``collect`` — статус коннекторов по harness: Claude Code (и FCC — тот же ``claude`` и та же папка) — разбор
  ``claude mcp list``; Pi — ``pi mcp list --json``; OpenCode — разбор ``opencode mcp list`` (формат сверен с
  программой 1.x: «✓ имя connected», «⚠ имя needs authentication», «✗ имя failed»). Hermes — не проверяется:
  ``hermes mcp list`` показывает только «включён в настройках», а не связь (отказавший сервер там «✓ enabled»).
- ``watch`` — сравнение с прошлым разом (``<данные>/connwatch_state.json``): переход в needs_auth / failed —
  событие ``connector_down`` (только harness, имя, состояние — без текстов ошибок), ``relogin``; нельзя
  автоматически — задача «ждёт вас» (одна на коннектор). Восстановился — ``connector_up`` и задача закрыта.
  Квитанцию владельцу шлёт бот по этим событиям (``alerts.Watch.connectors``) — одну на переход.
- ``units`` / ``install`` — systemd user timer раз в 30 минут, служба oneshot (постоянного процесса нет).
- ``vault_init`` / ``vault_get`` — отдельная база паролей коннекторов ``connectors.kdbx`` с ключ-файлом без
  мастер-пароля (её читает только пульт; агентам путь закрыт ``secrets_guard``). Значение не пишется никуда.

Никогда: обход 2FA и капчи, ввод пароля Google и Telegram — только живая сессия человека.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from gas_pult import config, store

RUN = subprocess.run                     # тесты подменяют: без настоящих claude, pi, opencode и keepassxc-cli
TIMEOUT = 180                            # с: claude mcp list проверяет все серверы — бывает минута и больше
STATES = ("ok", "needs_auth", "failed", "unknown")
DOWN = ("needs_auth", "failed")
# плагины без входа владельцу не нужны (22.11); browser-local — мост к компьютеру (выключен компьютер — не потеря
# входа, его видно в «Настройки → Компьютеры»); plugin:telegram — канал бота есть только в сессиях, запущенных с ним
DEFAULT_EXCLUDE = ("plugin:design:*", "plugin:gitlab:*", "browser-local", "plugin:telegram:*")
TITLES = {"claude": "Claude Code", "pi": "Pi", "opencode": "OpenCode", "hermes": "Hermes"}
NOT_CHECKED = {
    "hermes": "hermes mcp list показывает только «включён в настройках» (✓ enabled), а не связь: отказавший сервер "
              "там тоже «✓ enabled»; машиночитаемого вывода нет",
}
UNIT = "gas-pult-connwatch"


# ---------- разбор вывода ----------
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_CLAUDE = re.compile(r"^(?P<name>\S.*?): (?P<transport>.*?) - (?P<icon>[✔✓✘✗!-]) (?P<status>.+)$")


def _detail(s: str) -> str:
    """Текст ошибки — без секретов (``secrets_guard.redact``) и не длиннее 200 знаков."""
    from gas_pult import secrets_guard

    return secrets_guard.redact(" ".join(str(s or "").split()))[0][:200]


def _item(harness: str, name: str, state: str, detail: str = "") -> dict:
    return {"harness": harness, "name": name, "state": state, "detail": _detail(detail)}


def parse_claude(text: str) -> list[dict]:
    """``claude mcp list``: «имя: адрес - ✔ Connected» · «! Needs authentication» · «✘ Failed to connect — …» ·
    «- Not configured» (последнее — unknown: не настроен, а не потерял вход)."""
    out = []
    for line in str(text or "").splitlines():
        m = _CLAUDE.match(line.strip())
        if not m:
            continue
        icon, status = m["icon"], m["status"].strip()
        low = status.lower()
        if icon in "✔✓" and low.startswith("connected"):
            state, detail = "ok", ""
        elif "needs authentication" in low or "needs auth" in low:
            state, detail = "needs_auth", ""
        elif icon in "✘✗" or low.startswith("failed"):
            state, detail = "failed", re.sub(r"^failed to connect\s*[—–-]?\s*", "", status, flags=re.I)
        else:
            state, detail = "unknown", status
        out.append(_item("claude", m["name"].strip(), state, detail))
    return out


def parse_pi(text: str) -> list[dict]:
    """``pi mcp list --json``: {"servers": [{name, enabled, state, error?}]}; state — connected · needs-auth ·
    failed · disabled · connecting · pending."""
    try:
        d = json.loads(text or "{}")
    except ValueError:
        return []
    out = []
    for s in d.get("servers") or [] if isinstance(d, dict) else []:
        if not isinstance(s, dict) or not s.get("name"):
            continue
        st = str(s.get("state") or "")
        state = {"connected": "ok", "needs-auth": "needs_auth", "needs_auth": "needs_auth",
                 "failed": "failed", "error": "failed"}.get(st, "unknown")
        if s.get("enabled") is False:
            state = "unknown"
        out.append(_item("pi", str(s["name"]), state, s.get("error") or ("" if state != "unknown" else st)))
    return out


_OC_HEAD = re.compile(r"^[●○◆◇│\s]*[✓✔⚠✗✘○]\s+(?P<name>\S+)\s+(?P<status>connected|disabled|needs authentication|"
                      r"needs client registration|failed|not initialized)\b")
_OC_STATE = {"connected": "ok", "needs authentication": "needs_auth", "needs client registration": "needs_auth",
             "failed": "failed"}


def parse_opencode(text: str) -> list[dict]:
    """``opencode mcp list`` (только текст, с цветом): «●  ✓ github connected», под ним «│  <ошибка>» (без серого
    цвета) и «│  <адрес>» (серым). Ошибка — в detail; адрес не берём."""
    lines = str(text or "").splitlines()
    out = []
    for i, raw in enumerate(lines):
        m = _OC_HEAD.match(_ANSI.sub("", raw))
        if not m:
            continue
        state = _OC_STATE.get(m["status"], "unknown")
        detail = m["status"] if state == "unknown" else ""
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if state == "failed" and "\x1b[90m" not in nxt:
            detail = _ANSI.sub("", nxt).strip(" │\t")
        out.append(_item("opencode", m["name"], state, detail))
    return out


HARNESS = {   # команда, разбор; рабочая папка — домашняя (серверы проекта не смешиваем)
    "claude": (["claude", "mcp", "list"], parse_claude),
    "pi": (["pi", "mcp", "list", "--json"], parse_pi),
    "opencode": (["opencode", "mcp", "list"], parse_opencode),
}


def _which(cmd: str) -> bool:
    from shutil import which

    return which(cmd) is not None


def check(harness: str, run=None, which=_which) -> list[dict]:
    """Коннекторы одного harness. Программы нет, не ответила, вывод не разобран — одна строка «*» с причиной."""
    if harness in NOT_CHECKED:
        return [_item(harness, "*", "unknown", "не проверяется: " + NOT_CHECKED[harness])]
    cmd, parse = HARNESS[harness]
    if not which(cmd[0]):
        return [_item(harness, "*", "unknown", f"{cmd[0]} не установлен")]
    try:
        r = (run or RUN)(cmd, capture_output=True, text=True, timeout=TIMEOUT, cwd=str(Path.home()),
                         stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return [_item(harness, "*", "unknown", f"{' '.join(cmd)}: {type(e).__name__}")]
    items = parse(r.stdout or "")
    if not items:
        return [_item(harness, "*", "unknown", f"{' '.join(cmd)}: код {r.returncode}, вывод не разобран")]
    return items


def collect(harnesses=("claude", "pi", "opencode", "hermes"), run=None, which=_which) -> list[dict]:
    """Все harness параллельно (claude mcp list идёт до минуты): [{harness, name, state, detail}]."""
    with ThreadPoolExecutor(max_workers=len(harnesses) or 1) as ex:
        parts = list(ex.map(lambda h: check(h, run, which), harnesses))
    return [x for p in parts for x in p]


# ---------- исключения ----------
def excludes(cfg_dir: Path | None = None) -> list[str]:
    """Шаблоны имён, которые не проверяем: ``DEFAULT_EXCLUDE`` и ``exclude = [...]`` из
    ``<config>/connwatch.toml`` (шаблоны fnmatch; «harness/имя» — только для одного harness)."""
    pats = list(DEFAULT_EXCLUDE)
    p = Path(cfg_dir or config.config_dir()) / "connwatch.toml"
    try:
        raw = tomllib.loads(p.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        raw = {}
    pats += [str(x) for x in raw.get("exclude") or [] if str(x).strip()]
    return pats


def excluded(item: dict, pats) -> bool:
    for p in pats:
        h, sep, n = p.partition("/")
        if sep and h in TITLES:
            if h == item["harness"] and fnmatch.fnmatchcase(item["name"], n):
                return True
        elif fnmatch.fnmatchcase(item["name"], p):
            return True
    return False


# ---------- автовход: точка расширения ----------
@dataclass
class Result:
    done: bool                 # вошёл сам (фазы 2–3); False — нужен человек
    why: str = ""              # почему не сам
    hint: str = ""             # что нажать человеку — одна строка


def hint(c: dict) -> str:
    """Что сделать человеку, чтобы войти заново: одна строка, без технических слов там, где можно."""
    name, h, down = c["name"], c["harness"], c["state"]
    if down == "failed":
        cmd = {"claude": "в окне Claude Code — /mcp", "pi": "pi mcp list", "opencode": "opencode mcp list"}.get(h)
        return (f"Сервер «{name}» не запускается." + (f" Проверьте: {cmd}." if cmd else "")
                + (f" Ошибка: {c['detail']}" if c.get("detail") else ""))
    if h == "claude" and name.startswith("claude.ai "):
        return f"Откройте claude.ai → Настройки → Коннекторы → «{name[10:]}» → Подключить"
    if h == "claude":
        return f"В окне Claude Code наберите /mcp → «{name}» → Authenticate и нажмите «Разрешить» в браузере"
    if h == "pi":
        return f"В терминале: pi mcp login {name} — и нажмите «Разрешить» в браузере"
    if h == "opencode":
        return f"В терминале: opencode mcp auth {name} — и нажмите «Разрешить» в браузере"
    return f"Войдите в «{name}» заново"


def relogin(c: dict) -> Result:
    """Войти заново без человека. Фаза 1: автоматически нельзя ничего — задача владельцу с готовой подсказкой.
    Фаза 2 — нажать «Разрешить» в Chrome агента (CDP), фаза 3 — пароль из ``vault_get``. Обход 2FA и капчи, пароли
    Google и Telegram — никогда."""
    return Result(False, "автовход пока не умеет (фаза 1): нужен человек", hint(c))


# ---------- сравнение с прошлым разом ----------
def key(c: dict) -> str:
    return f"{c['harness']}:{c['name']}"


def task_title(c: dict) -> str:
    return f"Войти заново: {c['name']} ({TITLES.get(c['harness'], c['harness'])})"[:200]


class Watch:
    """``<данные>/connwatch_state.json``: {"conns": {harness:имя: {state, task?, since}}, "checked": время}."""

    def __init__(self, data: Path, clock=time.time, relogin_fn=None):
        self.data = Path(data)
        self.path = self.data / "connwatch_state.json"
        self.clock = clock
        self.relogin = relogin_fn or relogin

    def _tasks(self):
        from gas_pult import tasks

        return tasks.Tasks(self.data / "tasks.json")

    def _events(self):
        from gas_pult import chatlog

        return chatlog.Log(self.data / "chat-events.jsonl", clock=self.clock)

    def _open_task(self, t, c: dict, tid: str, text: str) -> str:
        """Одна открытая задача на коннектор: есть (по id или заголовку) — обновить подсказку, нет — завести."""
        cur = t.get(tid) if tid else None
        if not cur or cur.get("status") == "done":
            cur = next((x for x in t.list() if x.get("title") == task_title(c) and x.get("status") != "done"), None)
        if cur:
            t.update(cur["id"], {"next": text, "status": "waiting"})
            return cur["id"]
        return t.add({"title": task_title(c), "kind": "other", "status": "waiting", "next": text,
                      "urgent": "yes", "important": "yes"}, by="сторож коннекторов")["id"]

    @staticmethod
    def _close_task(t, tid: str):
        if not tid:
            return
        try:
            if (x := t.get(tid)) and x.get("status") != "done":
                t.update(tid, {"status": "done"})
        except (LookupError, ValueError):
            pass

    def run(self, items: list[dict], pats=(), dry: bool = False) -> list[str]:
        """Переходы и действия. ``dry`` — только сказать, что было бы: ни состояния, ни событий, ни задач."""
        now = self.clock()
        st = store.load_json(self.path)
        conns = st.setdefault("conns", {})
        checked = {c["harness"] for c in items if c["name"] != "*"}
        seen, out = set(), []
        t = ev = None
        if not dry:
            t, ev = self._tasks(), self._events()
        for c in items:
            if c["name"] == "*" or excluded(c, pats):
                continue
            k = key(c)
            seen.add(k)
            prev = conns.get(k) or {}
            was = prev.get("state") in DOWN
            if c["state"] == "unknown":
                continue                                             # не знаем — прошлое состояние не трогаем
            if c["state"] in DOWN and not was:
                r = self.relogin(c)
                if r.done:
                    out.append(f"{k}: {c['state']} → вошёл автоматически")
                    if not dry:
                        conns[k] = {"state": c["state"], "since": now}
                    continue
                out.append(f"{k}: {c['state']} → событие connector_down, задача «{task_title(c)}»: {r.hint}")
                if not dry:
                    ev.event("connector_down", harness=c["harness"], name=c["name"][:80], state=c["state"])
                    tid = self._open_task(t, c, prev.get("task", ""), r.hint)
                    conns[k] = {"state": c["state"], "task": tid, "since": now}
            elif c["state"] in DOWN:
                if not dry:
                    conns[k] = {**prev, "state": c["state"]}
            elif was:
                out.append(f"{k}: снова ok → событие connector_up, задача закрыта")
                if not dry:
                    ev.event("connector_up", harness=c["harness"], name=c["name"][:80], state="ok")
                    self._close_task(t, prev.get("task", ""))
                    conns[k] = {"state": "ok", "since": now}
            elif not dry and prev.get("state") != "ok":
                conns[k] = {"state": "ok", "since": now}
        for k in [k for k in conns if k.split(":", 1)[0] in checked and k not in seen]:
            out.append(f"{k}: больше нет в списке — забыл" + (", задача закрыта" if conns[k].get("task") else ""))
            if not dry:
                self._close_task(t, conns[k].get("task", ""))
                conns.pop(k)
        if not dry:
            st["checked"] = now
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            store.save_json(self.path, st)
        return out


def receipt(evs: list[dict]) -> str:
    """Квитанция владельцу по событиям ``connector_down`` / ``connector_up`` — одно сообщение на пачку."""
    lines = []
    for e in evs:
        who = f"«{str(e.get('name') or '?')[:80]}» ({TITLES.get(e.get('harness'), e.get('harness') or '?')})"
        if e.get("ev") == "connector_up":
            lines.append(f"✓ Коннектор {who} снова на связи — вошёл заново, задача закрыта.")
        elif e.get("state") == "failed":
            lines.append(f"⚠ Коннектор {who} не запускается — задача в «Ждут вас».")
        else:
            lines.append(f"⚠ Коннектор {who} потерял вход — что нажать, в задаче «Ждут вас».")
    return "\n".join(lines)


# ---------- systemd: таймер раз в 30 минут, служба oneshot ----------
def _src_path() -> str:
    """Запуск из исходников (рядом .git) — PYTHONPATH на них: служба видит ту же версию, что бот."""
    src = Path(__file__).resolve().parents[1]
    return str(src) if (src.parent / ".git").exists() else ""


def units(python: str | None = None, path_env: str | None = None, src: str | None = None) -> dict[str, str]:
    """Тексты ``gas-pult-connwatch.service`` и ``.timer``."""
    python = python or sys.executable
    src = _src_path() if src is None else src
    path_env = path_env or os.pathsep.join(dict.fromkeys([str(Path(python).parent), str(Path.home() / ".local/bin"),
                                                          "/usr/local/bin", "/usr/bin", "/bin"]))
    env = f"Environment=PATH={path_env}\n" + (f"Environment=PYTHONPATH={src}\n" if src else "")
    service = f"""[Unit]
Description=gas-pult — проверка входа коннекторов (MCP)
After=network-online.target

[Service]
Type=oneshot
ExecStart={python} -m gas_pult connectors watch
{env}WorkingDirectory=%h
Nice=10
TimeoutStartSec=900
"""
    timer = f"""[Unit]
Description=gas-pult — проверка входа коннекторов раз в 30 минут

[Timer]
OnBootSec=10min
OnUnitActiveSec=30min
RandomizedDelaySec=2min
Unit={UNIT}.service

[Install]
WantedBy=timers.target
"""
    return {f"{UNIT}.service": service, f"{UNIT}.timer": timer}


def install(remove: bool = False, run=None, home: Path | None = None) -> list[str]:
    """Поставить (или убрать) таймер в ``~/.config/systemd/user``. Возвращает записанные файлы."""
    run = run or RUN
    d = Path(home or Path.home()) / ".config/systemd/user"
    timer = f"{UNIT}.timer"
    if remove:
        run(["systemctl", "--user", "disable", "--now", timer], capture_output=True)
        for n in units():
            (d / n).unlink(missing_ok=True)
        run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        return []
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for n, text in units().items():
        (d / n).write_text(text, encoding="utf-8")
        out.append(str(d / n))
    run(["systemctl", "--user", "daemon-reload"], check=True)
    run(["systemctl", "--user", "enable", "--now", timer], check=True)
    return out


# ---------- база паролей коннекторов ----------
def vault_paths() -> tuple[Path, Path]:
    """(база, ключ-файл): ``<данные>/connectors.kdbx`` и ``<config>/connectors.key``."""
    return config.data_dir() / "connectors.kdbx", config.config_dir() / "connectors.key"


def vault_init(run=None) -> str:
    """Создать базу с ключ-файлом без мастер-пароля (keepassxc-cli 2.7: ``db-create --set-key-file``, без ``-p``
    пароль не ставится; ключ-файла нет — keepassxc-cli создаёт его сам). База уже есть — ничего не делать."""
    db, kf = vault_paths()
    if db.exists():
        return f"база уже есть: {db} — ничего не менял"
    db.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    kf.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        r = (run or RUN)(["keepassxc-cli", "db-create", "-q", "--set-key-file", str(kf), str(db)],
                         capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise RuntimeError("keepassxc-cli не установлен") from None
    if r.returncode != 0 or not db.exists():
        raise RuntimeError(f"keepassxc-cli db-create: код {r.returncode}")
    for p in (db, kf):
        if p.exists():
            os.chmod(p, 0o600)
    return f"база создана: {db} · ключ-файл: {kf} (0600, без мастер-пароля)"


def vault_get(entry: str, run=None) -> str | None:
    """Пароль записи ``entry`` (например «claude/notion»). Нет базы, записи или keepassxc-cli — None.
    Значение не логируется и не попадает в события: только возвращается вызывающему."""
    db, kf = vault_paths()
    if not (db.exists() and kf.exists()) or not entry:
        return None
    try:
        r = (run or RUN)(["keepassxc-cli", "show", "-q", "-s", "-a", "password", "--no-password", "-k", str(kf),
                          str(db), entry], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    val = (r.stdout or "").rstrip("\n")
    return val or None
