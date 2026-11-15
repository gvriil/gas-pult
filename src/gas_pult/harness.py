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

from gas_pult import pi_journal, transcripts


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

    def launch(self, sid: str, resume: bool = False) -> str:
        """Команда окна: id сессии — в окружении (Pi меняет имя процесса — аргументов в /proc не видно) и в
        ``--session-id`` (Pi открывает эту сессию или создаёт её: новое окно и «Продолжить» — одной командой)."""
        b = self.binary()
        if not b:
            raise ValueError("Pi на сервере не установлен")
        sid = pi_journal.valid_sid(sid)
        provider, _, model = self.MODEL.partition("/")
        cmd = f"env GAS_PULT_SID={sid} {shlex.quote(b)}" if sid else shlex.quote(b)
        cmd += f" --provider {shlex.quote(provider)} --model {shlex.quote(model)}" if model else ""
        return cmd + (self.resume_args(sid) if resume else self.new_args(sid))

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

    def new_args(self, sid):
        sid = pi_journal.valid_sid(sid)
        return f" --session-id {sid}" if sid else ""

    def resume_args(self, sid):
        sid = pi_journal.valid_sid(sid)
        return f" --session-id {sid}" if sid else " --continue"


HARNESSES: dict[str, Harness] = {h.name: h for h in (ClaudeCode(), Pi())}
DEFAULT = "claude"


def is_agent(w: dict | None) -> bool:
    """В окне работает агент (любой harness). Окна без поля ``harness`` — по прежнему признаку ``cmd == "claude"``."""
    return bool(w) and bool(w.get("harness") or w.get("cmd") == "claude")


def detect(argv: list[str]) -> Harness | None:
    """Какой агент запущен этим процессом (argv); не агент — None."""
    return next((h for h in HARNESSES.values() if h.matches(argv)), None)


def available() -> list[dict]:
    """Агенты для нового окна (кроме Claude Code — он есть всегда): установлены на сервере."""
    pi = HARNESSES["pi"]
    return [{"id": "pi", "title": "Pi", "model": pi.MODEL}] if pi.binary() else []


def of(w: dict | None) -> Harness:
    """Адаптер окна по полю ``harness``; окна без поля (старые ответы, тесты) — Claude Code, как раньше."""
    return HARNESSES.get((w or {}).get("harness") or DEFAULT) or HARNESSES[DEFAULT]
