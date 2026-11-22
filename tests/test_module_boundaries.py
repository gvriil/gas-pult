"""Границы модулей (модульный монолит, docs/MONOLITH-PLAN.md п.2): кто кого не импортирует.

Разбор — ``ast`` по ``src/gas_pult`` без запуска кода; учитываются и импорты внутри функций. Для ``bot``, ``people``,
``access``, ``webauth`` запрет и через посредника: ``bot → x → webapp`` — тоже нарушение.
Правила:
- ``bot`` не знает о панели (``webapp``): бот и панель — два входа в одно ядро;
- ``people``, ``access``, ``webauth`` (люди, права, вход) — нижний слой: не импортируют ни ``bot``, ни ``webapp``;
- ``connectors/*`` — отдельные процессы MCP: только свой ``_core`` и стандартная библиотека, ядро пульта — нет.
Интерфейс панели (``web/``) — не Python, здесь не проверяется.

Нарушение «как есть» — в ``KNOWN`` с причиной и задачей: новое не появится, старое видно до починки.
"""

import ast
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "src" / "gas_pult"

# (модуль, кого импортирует) → почему так и какая задача уберёт. Пусто — нарушений нет (22.11).
KNOWN: dict[tuple[str, str], str] = {}


def mod_name(path: Path) -> str:
    rel = path.relative_to(PKG.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def modules() -> dict[str, Path]:
    return {mod_name(p): p for p in PKG.rglob("*.py")}


def imports(name: str, path: Path, known: set[str]) -> set[str]:
    """Что модуль импортирует: внутренние — полным именем (``gas_pult.x``), внешние — верхним (``json``)."""
    is_pkg = path.name == "__init__.py"
    base = name.split(".") if is_pkg else name.split(".")[:-1]
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for a in node.names:
                top = a.name.split(".")[0]
                sib = ".".join([*base, a.name])           # connectors: «import _core» при запуске файлом
                out.add(a.name if top == "gas_pult" else sib if sib in known else top)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                root = ".".join(base[:len(base) - node.level + 1])
                src = f"{root}.{node.module}" if node.module else root
            else:
                src = node.module or ""
            if not src.startswith("gas_pult"):
                out.add(src.split(".")[0])
                continue
            for a in node.names:                          # from gas_pult import bot — это модуль bot
                sub = f"{src}.{a.name}"
                out.add(sub if sub in known else src)
    return out


def graph() -> dict[str, set[str]]:
    mods = modules()
    return {n: imports(n, p, set(mods)) for n, p in mods.items()}


def reach(g: dict[str, set[str]], who: str) -> set[str]:
    """Все внутренние модули, до которых ``who`` доходит импортами (напрямую и через других)."""
    seen: set[str] = set()
    todo = [who]
    while todo:
        for t in g.get(todo.pop(), ()):
            if t in g and t not in seen:
                seen.add(t)
                todo.append(t)
    return seen


def hits(g: dict[str, set[str]], who: str, banned: set[str]) -> set[tuple[str, str]]:
    return {(who, t) for t in reach(g, who) if t in banned}


def violations() -> set[tuple[str, str]]:
    g = graph()
    bad = hits(g, "gas_pult.bot", {"gas_pult.webapp"})
    for low in ("gas_pult.people", "gas_pult.access", "gas_pult.webauth"):
        bad |= hits(g, low, {"gas_pult.bot", "gas_pult.webapp"})
    std = set(sys.stdlib_module_names) | {"__future__"}
    for name, deps in g.items():
        if not name.startswith("gas_pult.connectors"):
            continue
        ok = {"gas_pult.connectors", "gas_pult.connectors._core"}
        bad |= {(name, d) for d in deps if d not in ok and d not in std}
    return bad


def test_graph_sees_known_imports():
    """Сам разбор работает: известные импорты видны (иначе тест границ молча ничего не ловит)."""
    g = graph()
    assert "gas_pult.people" in g["gas_pult.bot"]
    assert "gas_pult.webauth" in g["gas_pult.bot"]
    assert "gas_pult.connectors._core" in g["gas_pult.connectors.mail_mcp"]
    assert "gas_pult.access" in g["gas_pult.webapp"]


def test_rule_catches_violation():
    """Правило срабатывает: и прямой импорт, и через посредника."""
    g = {"gas_pult.bot": {"gas_pult.x"}, "gas_pult.x": {"gas_pult.webapp"}, "gas_pult.webapp": set()}
    assert hits(g, "gas_pult.bot", {"gas_pult.webapp"}) == {("gas_pult.bot", "gas_pult.webapp")}


def test_no_new_boundary_violations():
    new = violations() - set(KNOWN)
    assert not new, "новые нарушения границ модулей (см. docstring): " + ", ".join(f"{a} → {b}" for a, b in sorted(new))


def test_known_exceptions_still_needed():
    """Починили — уберите из KNOWN, чтобы исключение не прикрыло новое такое же нарушение."""
    gone = set(KNOWN) - violations()
    assert not gone, "уже не нарушения — уберите из KNOWN: " + ", ".join(f"{a} → {b}" for a, b in sorted(gone))
