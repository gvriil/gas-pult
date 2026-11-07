"""Слепые проверяющие (задача 45): агенты Claude Code, которые видят только требование и результат.

Исходники — ``templates/agents/`` пакета: определения агентов (``*.md``) и сторож (``slepaya_proverka_storozh.py`` —
хук PreToolUse из определения агента: читать можно только пути из задания, правила и память закрыты). Раскладка в
папку Claude Code (``.claude`` пространства модуля или ``CLAUDE_CONFIG_DIR`` демо-пространства):

- ``agents/<имя>.md`` — определения агентов;
- ``hooks/slepaya_proverka_storozh.py`` — сторож.

Раскладка идемпотентна: совпадающий файл не переписывается, свой файл человека с другим именем не трогается.
Демо-пространства получают их из ``tenant_admin`` (владелец, через sudo), пространства модулей — при создании
(``modules.create``).
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

GUARD = "slepaya_proverka_storozh.py"
# Что видит человек в панели: id агента → (название, для чего). Порядок — порядок показа.
AGENTS = {
    "slepaya-proverka": ("Слепая проверка",
                         "Смотрит на готовую работу глазами заказчика: видит только требование и результат, "
                         "отвечает «принято» или «не принято» и адресом у каждой находки."),
    "slepaya-proverka-dokumentov": ("Проверка документов как налоговая или банк",
                                    "Документы бухгалтера или юриста глазами инспектора ФНС или банка "
                                    "по 115-ФЗ — до отправки."),
}


def source_dir() -> Path:
    return Path(str(resources.files("gas_pult").joinpath("templates/agents")))


def files() -> dict[str, str]:
    """Путь внутри папки Claude Code → текст файла."""
    src = source_dir()
    out = {f"agents/{a}.md": (src / f"{a}.md").read_text(encoding="utf-8") for a in AGENTS}
    out[f"hooks/{GUARD}"] = (src / GUARD).read_text(encoding="utf-8")
    return out


def mode_of(rel: str) -> int:
    return 0o755 if rel.endswith(".py") else 0o644


def install(claude_dir: Path) -> list[str]:
    """Разложить агентов и сторожа в папку Claude Code. Возвращает, что записано заново (пусто — всё уже на месте)."""
    done = []
    for rel, text in files().items():
        p = Path(claude_dir) / rel
        if p.is_file() and not p.is_symlink() and p.read_text(encoding="utf-8", errors="replace") == text:
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.is_symlink():
            p.unlink()
        tmp = p.with_name(f".{p.name}.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.chmod(mode_of(rel))
        tmp.replace(p)
        done.append(rel)
    return done


def public() -> list[dict]:
    """Для панели: [{id, title, about}]."""
    return [{"id": a, "title": t, "about": ab} for a, (t, ab) in AGENTS.items()]
