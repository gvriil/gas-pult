import re

from websrc import web_source

# Функция верхнего уровня в обычном <script> становится свойством window. Назвали её «open» — сломали window.open
# (в браузере «Войти через Telegram» открывало «сессию» с адресом ссылки). Такие имена занимать нельзя.
WINDOW_NAMES = {"open", "close", "stop", "print", "alert", "confirm", "prompt", "focus", "blur", "find", "scroll",
                "scrollTo", "scrollBy", "moveTo", "postMessage", "fetch", "name", "status", "length", "top", "parent",
                "self", "frames", "origin", "history", "location", "event", "external", "screen", "navigator"}


def test_page_does_not_shadow_window_api():
    page = web_source()
    script = page[page.index("<script>\n"):]
    declared = set(re.findall(r"^(?:async\s+)?function\s+(\w+)\s*\(", script, re.M))
    declared |= set(re.findall(r"^(?:let|const|var)\s+(\w+)\s*=", script, re.M))
    assert not declared & WINDOW_NAMES, declared & WINDOW_NAMES


def test_sessions_opened_by_name_not_bare_open():
    page = web_source()
    script = page[page.index("<script>\n"):]
    assert not re.findall(r"(?<![.\w])open\(", script)            # открыть сессию — openSession(), ссылку — openUrl()


def test_only_the_feed_scrolls():
    # Прокручивался документ — и на iPhone «закреплённое» поле ввода ездило вместе с текстом и клавиатурой.
    # Листается только лента #scroller; документ стоит на месте.
    page = web_source()
    script = page[page.index("<script>\n"):]
    assert re.search(r"^\s*html \{[^}]*overflow: hidden", page, re.M)
    assert 'id="scroller"' in page
    assert "document.body.scrollHeight" not in script
    assert not re.findall(r"^addEventListener\(\"scroll\"", script, re.M)
