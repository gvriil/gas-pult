"""Исходник интерфейса панели одним текстом — для тестов, которые читают его как строку.

Интерфейс переезжает из одного index.html в web/css/*.css и web/js/*.js (разбиение пульта на модули). Тесты ищут
функции и стили по тексту и режут его «от функции A до функции B» — поэтому ``web_source()`` собирает страницу
обратно: на месте ``<link rel="stylesheet" href="/css/….css">`` — ``<style>`` с содержимым файла, на месте
``<script … src="/js/….js"></script>`` — ``<script>`` с содержимым, в порядке подключения; соседние блоки (файлы
подключены подряд, строка за строкой) сливаются в один. Так перенос «байт в байт» собирается ровно в прежний
index.html — это и проверяется после каждого шага переезда. Пока файлов нет, это и есть index.html. Файл, не
подключённый в index.html, тоже попадает в текст (в конец) — чтобы тест его видел.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
LINK = re.compile(r'<link\b[^>]*\bhref="/(css/[\w./-]+?\.css)"[^>]*>')
SCRIPT = re.compile(r'<script\b[^>]*\bsrc="/(js/[\w./-]+?\.js)"[^>]*>\s*</script>')


def web_files() -> list[Path]:
    """Все web/css/**/*.css и web/js/**/*.js."""
    return sorted([*WEB.glob("css/**/*.css"), *WEB.glob("js/**/*.js")])


@cache
def web_source(web: Path = WEB) -> str:
    page = (web / "index.html").read_text(encoding="utf-8")
    used: set[str] = set()

    def inline(tag: str):
        def put(m: re.Match) -> str:
            used.add(m[1])
            return f"<{tag}>\x01\n" + (web / m[1]).read_text(encoding="utf-8") + f"\x02</{tag}>"   # метки: из файла
        return put
    page = SCRIPT.sub(inline("script"), LINK.sub(inline("style"), page))
    for tag in ("style", "script"):                 # сливаются только два подставленных блока подряд
        page = page.replace(f"\x02</{tag}>\n<{tag}>\x01\n", "")
    page = page.replace("\x01", "").replace("\x02", "")
    rest = [p for p in [*sorted(web.glob("css/**/*.css")), *sorted(web.glob("js/**/*.js"))]
            if p.relative_to(web).as_posix() not in used]
    return page + "".join(f"\n<!-- {p.relative_to(web).as_posix()} -->\n" + p.read_text(encoding="utf-8")
                          for p in rest)
