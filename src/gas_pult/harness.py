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

from pathlib import Path

from gas_pult import transcripts


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
        return transcripts.last_answer(path, home=home, sid=sid)

    def revision(self, path, home=None, sid=""):
        return transcripts.revision(path, home=home, sid=sid)

    def new_args(self, sid):
        sid = transcripts.valid_sid(sid)
        return f" --session-id {sid}" if sid else ""

    def resume_args(self, sid):
        return transcripts.resume_args(sid)


HARNESSES: dict[str, Harness] = {h.name: h for h in (ClaudeCode(),)}
DEFAULT = "claude"


def detect(argv: list[str]) -> Harness | None:
    """Какой агент запущен этим процессом (argv); не агент — None."""
    return next((h for h in HARNESSES.values() if h.matches(argv)), None)


def of(w: dict | None) -> Harness:
    """Адаптер окна по полю ``harness``; окна без поля (старые ответы, тесты) — Claude Code, как раньше."""
    return HARNESSES.get((w or {}).get("harness") or DEFAULT) or HARNESSES[DEFAULT]
