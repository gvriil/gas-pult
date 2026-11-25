"""Владелец 25.11: продукт — «Ладэя» / «Ladeya» (by Botsmith); «Гаврила» в том, что видит человек, не встречается.

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
    assert (brand.APP_NAME_RU, brand.APP_NAME_EN, brand.BY) == ("Ладэя", "Ladeya", "by Botsmith")
    assert brand.FORMS["род"] == "Ладэи" and brand.FORMS["вин"] == "Ладэю" and brand.FORMS["твор"] == "Ладэей"
    assert all(OLD.search(w) for w in brand.OLD)


OLD_E = re.compile(r"(?<![А-Яа-яЁё])Ладе(я|и|ю|е|ей)(?![А-Яа-яЁё])")     # «Ладея» через «е» — до 25.11


def test_ladeya_with_e_nowhere_user_facing():
    """Владелец 25.11: «Ладэя» — с «э». Прежнее написание через «е» не встречается в том, что видит человек.
    Исключения — те же (история, правила) и слово-обращение протоколов: распознавание речи пишет и так, и так."""
    bad = []
    for p in files():
        rel = p.relative_to(ROOT).as_posix()
        if rel in SKIP or rel.startswith(SKIP_DIRS):
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if OLD_E.search(line) and not (rel == "src/gas_pult/meetings.py" and "распознавание" in line):
                bad.append(f"{rel}:{n}: {line.strip()[:80]}")
    assert not bad, "\n".join(bad[:20])


def test_wordmark_red_e_only_as_mark():
    assert brand.APP_NAME_RU == "Ладэя" and brand.FORMS["вин"] == "Ладэю" and brand.APP_NAME_EN == "Ladeya"
    assert brand.wordmark() == 'Лад<span class="e">э</span>я' and brand.wordmark("Ladeya") == "Ladeya"
    assert brand.E_COLOR == {"light": "#E8421C", "dark": "#FF5A2D", "light_small": "#C2361A"}
