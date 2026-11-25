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
    assert brand.wordmark() == 'Лад<span class="e">э</span>я' and brand.wordmark("Ladeya") == brand.WORDMARK_EN
    assert brand.E_COLOR == {"light": "#E8421C", "dark": "#FF5A2D", "light_small": "#C2361A"}


def test_red_e_everywhere_in_ready_markup():
    """Владелец 25.11: «делай э в интерфейсе красного цвета везде». Готовая страница (как её отдаёт сервер) — ни одного
    «Ладэ…» без обёртки в тексте; <title>, атрибуты (meta, og) и скрипты — исключения, там окраска невозможна."""
    from gas_pult import webapp  # noqa: F401 — страницу собирает handler; здесь — та же функция на исходнике
    page = brand.paint_html((ROOT / "src/gas_pult/web/index.html").read_text(encoding="utf-8"))
    text = re.sub(r"<(script|style|title|textarea)\b[^>]*>.*?</\1\s*>|<!--.*?-->|<[^>]*>", " ", page, flags=re.S | re.I)
    assert not brand.WORD.search(text), brand.WORD.search(text)
    assert brand.paint_html("<p>Команда Ладэи и Ладэю</p><title>Ладэя</title>") == \
        '<p>Команда Лад<span class="e">э</span>и и Лад<span class="e">э</span>ю</p><title>Ладэя</title>'
    assert brand.paint_html('<meta content="Ладэя">') == '<meta content="Ладэя">'
    assert brand.paint_html(brand.paint_html("<b>Ладэя</b>")) == '<b>Лад<span class="e">э</span>я</b>'   # не дважды
    look = (ROOT / "src/gas_pult/web/js/look.js").read_text(encoding="utf-8")
    assert "splitText" in look and "MutationObserver" in look        # новый текст в панели — окрашивается сам


def test_wordmark_by_language_ru_c_en_b():
    """Владелец 25.11: «B и C в зависимости от выбранного языка». RU (C) — «Ладэя», «э» красная; EN (B) — «ladeya»
    строчными (CSS), «e» красная и зеркальная; в разметке и при копировании — «Ladeya», aria-label — «Ladeya»."""
    assert brand.wordmark("Ладэя") == 'Лад<span class="e">э</span>я'
    en = brand.wordmark("Ladeya")
    assert en == brand.WORDMARK_EN and 'aria-label="Ladeya"' in en and re.sub(r"<[^>]+>", "", en) == "Ladeya"
    assert '<span class="em">e</span>' in en and brand.wordmark("Botsmith") == "Botsmith"
    look = (ROOT / "src/gas_pult/web/js/look.js").read_text(encoding="utf-8")
    assert brand.WORDMARK_EN in look                                         # одна разметка на сервере и в панели
    assert ".wm-en { text-transform: lowercase; }" in look and "transform: scaleX(-1)" in look
    login = (ROOT / "src/gas_pult/web/js/loginlook.js").read_text(encoding="utf-8")
    assert brand.WORDMARK_EN in login and "scaleX(-1)" in login
