"""Провайдер сессий: пульт ведёт окна любого агента (harness), не только Claude Code (R13, аудит 15.11).

Решение владельца 15.11: «да, Pi основной» — пульт должен видеть и вести сессии Pi и OpenCode так же, как Claude Code.
Всё, что зависит от программы агента, — за этим интерфейсом:

- ``matches(argv)`` — процесс этого агента в окне tmux;
- ``live_sid(pid)`` — какую сессию ведёт работающий процесс;
- ``journal(path, sid)`` — файл журнала сессии; ``history`` / ``preview`` / ``last_model`` / ``last_answer`` /
  ``revision`` — лента и строка о сессии из журнала;
- ``new_args(sid)`` / ``resume_args(sid)`` — аргументы запуска: новая сессия со своим id и «Продолжить».

Адаптер ``claude`` — текущее поведение без изменений: он только вызывает ``transcripts`` и ``tmux``. Окно агента
получает поле ``harness`` (имя адаптера; ``""`` — агента нет). Адаптеры Pi и OpenCode — следующими шагами.
"""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path

from gas_pult import agent_dbs, agent_memory, pi_journal, transcripts


class Harness:
    """Агент в окне tmux. Методы по умолчанию — «ничего не знаю»: окно видно, ленты нет."""

    name = ""
    title = ""

    def matches(self, argv: list[str]) -> bool:
        return False

    def live_sid(self, pid) -> str:
        return ""

    def journal(self, path: str, home: Path | None = None, sid: str = "") -> Path | None:
        return None

    def history(self, path: str, limit: int = 30, before: int | None = None, home: Path | None = None,
                sid: str = "", file: Path | None = None) -> tuple[list[dict], bool]:
        return [], False

    def preview(self, path: str, home: Path | None = None, sid: str = "") -> str:
        return ""

    def last_model(self, path: str, home: Path | None = None, sid: str = "") -> str:
        return ""

    def last_answer(self, path: str, home: Path | None = None, sid: str = "") -> str:
        return ""

    def revision(self, path: str, home: Path | None = None, sid: str = "") -> str:
        return ""

    # Окна без экрана Claude Code (Pi, OpenCode, Hermes): статус хода, расход и ответы — из своего журнала
    def status(self, f) -> dict:
        return {"phase": "idle"}

    def usage(self, f) -> dict:
        return {"provider": "", "model": "", "used": None}

    def answers_at(self, f) -> list:
        return []

    def new_args(self, sid: str) -> str:
        return ""

    def resume_args(self, sid: str) -> str:
        return ""


class ClaudeCode(Harness):
    """Claude Code: журналы ``~/.claude/projects/<папка>/<id>.jsonl``, сессия процесса — ``sessions/<pid>.json``."""

    name = "claude"
    title = "Claude Code"

    def matches(self, argv):
        from gas_pult.tmux import is_claude
        return is_claude(argv)

    def live_sid(self, pid):
        from gas_pult.tmux import live_sid
        return live_sid(pid)

    def journal(self, path, home=None, sid=""):
        return transcripts.current(path, home, sid)

    def history(self, path, limit=30, before=None, home=None, sid="", file=None):
        return transcripts.history(path, limit, before, home=home, sid=sid, file=file)

    def preview(self, path, home=None, sid=""):
        return transcripts.preview(path, home=home, sid=sid)

    def last_model(self, path, home=None, sid=""):
        return transcripts.last_model(path, home=home, sid=sid)

    def last_answer(self, path, home=None, sid=""):
        return transcripts.last_answer(path, home, sid)

    def revision(self, path, home=None, sid=""):
        return transcripts.revision(path, home, sid)

    def new_args(self, sid):
        sid = transcripts.valid_sid(sid)
        return f" --session-id {sid}" if sid else ""

    def resume_args(self, sid):
        return transcripts.resume_args(sid)


class Pi(Harness):
    """Pi (основной запасной агент): процесс ``pi`` (node …/pi-coding-agent/…/cli.js), журналы
    ``~/.pi/agent/sessions/--<путь>--/*_<id>.jsonl``. Пульт запускает Pi с ``--session-id <id>``: Pi открывает эту
    сессию или создаёт её — один и тот же аргумент для нового окна и для «Продолжить»."""

    name = "pi"
    title = "Pi"

    def __init__(self, root: Path | None = None):
        self.root = root

    def matches(self, argv):
        return any(os.path.basename(a) == "pi" or "/pi-coding-agent/" in a for a in argv[:2])

    # Модель окна Pi по умолчанию — DeepSeek V4 Pro (решение владельца 15.11: «Pi основной»); ключи — в ~/.pi (штаб)
    MODEL = os.environ.get("GAS_PULT_PI_MODEL", "deepseek/deepseek-v4-pro")
    COUNTRY_AS = "deepseek"                       # правила стран — как у поставщика модели (models.allowed)

    def binary(self) -> str:
        for p in (os.environ.get("GAS_PULT_PI", ""), shutil.which("pi") or "",
                  str(Path.home() / ".local/share/pi/node_modules/.bin/pi")):
            if p and os.access(p, os.X_OK):
                return p
        return ""

    def launch(self, sid: str, resume: bool = False, path: str = "") -> str:
        """Команда окна: id сессии — в окружении (Pi меняет имя процесса — аргументов в /proc не видно) и в
        ``--session-id`` (Pi открывает эту сессию или создаёт её: новое окно и «Продолжить» — одной командой).
        ``path`` — папка окна: к добавке правил — автопамять её проекта (``agent_memory``)."""
        b = self.binary()
        if not b:
            raise ValueError("Pi на сервере не установлен")
        sid = pi_journal.valid_sid(sid)
        provider, _, model = self.MODEL.partition("/")
        cmd = f"env GAS_PULT_SID={sid} {shlex.quote(b)}" if sid else shlex.quote(b)
        cmd += f" --provider {shlex.quote(provider)} --model {shlex.quote(model)}" if model else ""
        ov = self.overlay()
        base = ov.read_text(encoding="utf-8") if ov.is_file() else ""
        mem = agent_memory.overlay(path, base) if path else None      # правила + память проекта — одним файлом
        if mem or ov.is_file():                       # оверлей правил к системному промпту (gas-pult pi overlay)
            cmd += f" --append-system-prompt {shlex.quote(str(mem or ov))}"
        return cmd + (self.resume_args(sid) if resume else self.new_args(sid))

    @staticmethod
    def overlay() -> Path:
        """Добавка к системному промпту окон Pi: свод главных правил и оверлей модели (собирает ``gas-pult pi
        overlay``). Владелец 15.11 о Pi: «решает за меня, долгие циклы инструментов» — правила короче и строже."""
        from gas_pult.config import config_dir
        return config_dir() / "pi" / "append.md"

    def live_sid(self, pid):
        """Сессия процесса Pi: ``GAS_PULT_SID`` из окружения (окна пульта), иначе ``--session-id`` в аргументах."""
        try:
            env = Path(f"/proc/{int(pid)}/environ").read_bytes().decode(errors="replace").split("\0")
            sid = next((x.split("=", 1)[1] for x in env if x.startswith("GAS_PULT_SID=")), "")
            if sid := pi_journal.valid_sid(sid):
                return sid
            argv = Path(f"/proc/{int(pid)}/cmdline").read_bytes().decode(errors="replace").split("\0")
        except (OSError, ValueError):
            return ""
        return pi_journal.session_arg(argv)

    def journal(self, path, home=None, sid=""):
        return pi_journal.current(path, self.root, sid)        # ``home`` — папка Claude Code, у Pi своя

    def history(self, path, limit=30, before=None, home=None, sid="", file=None):
        return pi_journal.history(file or self.journal(path, home, sid), limit, before)

    def preview(self, path, home=None, sid=""):
        f = self.journal(path, home, sid)
        items = pi_journal.parse(f)[0] if f else []
        return transcripts._line(items[-1]["text"]) if items else ""

    def last_model(self, path, home=None, sid=""):
        f = self.journal(path, home, sid)
        return pi_journal.parse(f)[1] if f else ""

    def last_answer(self, path, home=None, sid=""):
        f = self.journal(path, home, sid)
        items = pi_journal.parse(f)[0] if f else []
        return next((x["text"] for x in reversed(items) if x["role"] == "assistant"), "")

    def revision(self, path, home=None, sid=""):
        f = self.journal(path, home, sid)
        if not f:
            return ""
        st = f.stat()
        return f"{f.stem[-8:]}-{st.st_size}-{st.st_mtime_ns}"

    def status(self, f):
        return pi_journal.status(f)

    def usage(self, f):
        return pi_journal.usage(f)

    def answers_at(self, f):
        return pi_journal.answers_at(f) if f else []

    def new_args(self, sid):
        sid = pi_journal.valid_sid(sid)
        return f" --session-id {sid}" if sid else ""

    def resume_args(self, sid):
        sid = pi_journal.valid_sid(sid)
        return f" --session-id {sid}" if sid else " --continue"


class _DbAgent(Harness):
    """Агент с журналом в SQLite (OpenCode, Hermes): id сессии программа создаёт сама — журнал окна — сессия с этим
    id или самая свежая сессия папки окна. Модель и ключи — из настроек самой программы (``~/.config/opencode``,
    ``~/.hermes``), пульт их не меняет."""

    BIN = ""
    store: agent_dbs.OpenCodeDB | agent_dbs.HermesDB

    def binary(self) -> str:
        for p in (os.environ.get(f"GAS_PULT_{self.name.upper()}", ""), shutil.which(self.BIN) or "",
                  str(Path.home() / ".local/bin" / self.BIN)):
            if p and os.access(p, os.X_OK):
                return p
        return ""

    def matches(self, argv):
        return any(os.path.basename(a) == self.BIN for a in argv[:2])

    def journal(self, path, home=None, sid=""):
        return self.store.ref(path, sid)

    def _rows(self, path, sid="", ref=None):
        ref = ref or self.journal(path, sid=sid)
        return self.store.rows(ref) if ref else []

    def history(self, path, limit=30, before=None, home=None, sid="", file=None):
        items = agent_dbs.items(self._rows(path, sid, file))
        end = len(items) if before is None else max(0, min(before, len(items)))
        start = max(0, end - limit)
        return [{**it, "i": n} for n, it in enumerate(items[start:end], start)], start > 0

    def preview(self, path, home=None, sid=""):
        items = agent_dbs.items(self._rows(path, sid))
        return transcripts._line(items[-1]["text"]) if items else ""

    def last_model(self, path, home=None, sid=""):
        return agent_dbs.last_model(self._rows(path, sid))

    def last_answer(self, path, home=None, sid=""):
        items = agent_dbs.items(self._rows(path, sid))
        return next((x["text"] for x in reversed(items) if x["role"] == "assistant"), "")

    def revision(self, path, home=None, sid=""):
        ref = self.journal(path, sid=sid)
        return self.store.revision(ref) if ref else ""

    def status(self, f):
        return agent_dbs.status(self.store.rows(f)) if f else {"phase": "idle"}

    def usage(self, f):
        model = agent_dbs.last_model(self.store.rows(f)) if f else ""
        provider, _, name = model.partition("/")
        return {"provider": provider if name else "", "model": name or provider, "used": None}

    def answers_at(self, f):
        return agent_dbs.answers_at(self.store.rows(f)) if f else []

    def live_sid(self, pid):
        return ""                                     # id видно только в журнале — по папке окна

    def memory_env(self, f: Path) -> str:
        return ""

    def launch(self, sid: str, resume: bool = False, path: str = "") -> str:
        b = self.binary()
        if not b:
            raise ValueError(f"{self.title} на сервере не установлен")
        mem = agent_memory.overlay(path) if path else None             # автопамять проекта папки окна
        env = self.memory_env(mem) if mem else ""
        args = self.resume_args(sid) if resume else self.new_args(sid)
        return (f"env {env} " if env else "") + shlex.quote(b) + args

    def new_args(self, sid):
        return ""


class OpenCode(_DbAgent):
    """OpenCode: ``opencode`` в папке окна; «Продолжить» — ``-s <id>`` или последняя сессия папки (``-c``)."""
    name, title, BIN = "opencode", "OpenCode", "opencode"
    COUNTRY_AS = "openrouter"

    def __init__(self, db: Path | None = None):
        self.store = agent_dbs.OpenCodeDB(db)

    def memory_env(self, f):
        import json
        return "OPENCODE_CONFIG_CONTENT=" + shlex.quote(json.dumps({"instructions": [str(f)]}))

    def resume_args(self, sid):
        sid = agent_dbs.valid_sid(sid)
        return f" -s {shlex.quote(sid)}" if sid else " -c"


class Hermes(_DbAgent):
    """Hermes: ``hermes`` в папке окна (постоянный дом ``~/.hermes``: правила, скиллы, MCP — штаб, mcp-install.sh);
    «Продолжить» — ``--resume <id>`` или последняя сессия папки (``-c``)."""
    name, title, BIN = "hermes", "Hermes", "hermes"
    COUNTRY_AS = "openrouter"

    def __init__(self, db: Path | None = None):
        self.store = agent_dbs.HermesDB(db)

    def memory_env(self, f):
        return "GAS_PULT_MEMORY_FILE=" + shlex.quote(str(f))     # обёртка hermes (штаб) дописывает к оверлею

    def resume_args(self, sid):
        sid = agent_dbs.valid_sid(sid)
        return f" --resume {shlex.quote(sid)}" if sid else " -c"


HARNESSES: dict[str, Harness] = {h.name: h for h in (ClaudeCode(), Pi(), OpenCode(), Hermes())}
JOURNAL_ONLY = ("pi", "opencode", "hermes")         # статус и ответы — из журнала агента, не из экрана Claude Code
DEFAULT = "claude"


def is_agent(w: dict | None) -> bool:
    """В окне работает агент (любой harness). Окна без поля ``harness`` — по прежнему признаку ``cmd == "claude"``."""
    return bool(w) and bool(w.get("harness") or w.get("cmd") == "claude")


def detect(argv: list[str]) -> Harness | None:
    """Какой агент запущен этим процессом (argv); не агент — None."""
    return next((h for h in HARNESSES.values() if h.matches(argv)), None)


def available() -> list[dict]:
    """Агенты для нового окна (кроме Claude Code — он есть всегда): установлены на сервере."""
    out = []
    for name in JOURNAL_ONLY:
        h = HARNESSES[name]
        if h.binary():
            out.append({"id": name, "title": h.title, "model": getattr(h, "MODEL", "")})
    return out


def of(w: dict | None) -> Harness:
    """Адаптер окна по полю ``harness``; окна без поля (старые ответы, тесты) — Claude Code, как раньше."""
    return HARNESSES.get((w or {}).get("harness") or DEFAULT) or HARNESSES[DEFAULT]
