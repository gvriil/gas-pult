"""Владелец 25.11: продукт — «Ладея» / «Ladeya» (by Botsmith); «Гаврила» в том, что видит человек, не встречается.

Проверяем всё, что уходит человеку: панель (web/: страницы, части, словари, «Что нового»), код сервера и бота (строки
писем, уведомлений, сообщений), документы для клиентов и README. Исключения — ниже: прежнее имя хранит только
``brand.OLD`` (чтобы тест знал, что искать); история (CHANGELOG, аудиты) и тесты не переписываются.
"""
import re
from pathlib import Path

from gas_pult import brand

ROOT = Path(__file__).resolve().parents[1]
OLD = re.compile(r"Гаврил|Gavril")                    # имена файлов знака — строчными (gavrila-mark.svg) — не трогаем
SKIP = {"src/gas_pult/brand.py", "CHANGELOG.md", "docs/BRAND.md"}   # brand.OLD; правило «не писать»
SKIP_DIRS = ("docs/audit/",)                           # протоколы аудитов — история


def files():
    for base in ("src", "docs", "help"):
        for p in (ROOT / base).rglob("*"):
            if p.is_file() and p.suffix in {".py", ".js", ".html", ".json", ".md", ".txt", ".svg", ".toml"}:
                yield p
    for name in ("README.md", "CONTRIBUTING.md", "GEMINI.md"):
        if (ROOT / name).is_file():
            yield ROOT / name


def test_old_name_nowhere_user_facing():
    bad = []
    for p in files():
        rel = p.relative_to(ROOT).as_posix()
        if rel in SKIP or rel.startswith(SKIP_DIRS):
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if OLD.search(line):
                bad.append(f"{rel}:{n}: {line.strip()[:80]}")
    assert not bad, "\n".join(bad[:20])


def test_one_place_and_forms():
    assert (brand.APP_NAME_RU, brand.APP_NAME_EN, brand.BY) == ("Ладея", "Ladeya", "by Botsmith")
    assert brand.FORMS["род"] == "Ладеи" and brand.FORMS["вин"] == "Ладею" and brand.FORMS["твор"] == "Ладеей"
    assert all(OLD.search(w) for w in brand.OLD)
