"""Gemini 21.11, топ-15 №3: шапка чата на телефоне — «≡ · Название · ⋯»; нажатие на название не открывает второй
список чатов (дубль боковой панели); «куда пишете» у поля — панель чатов. «Подсказать» — первым пунктом «⋯»."""
from pathlib import Path

PAGE = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/index.html").read_text(encoding="utf-8")


def test_header():
    assert '<button class="icon" id="chatMoreBtn" aria-label="Действия с чатом"></button>' in PAGE
    assert "body.in-chat:not(.split):not(.focus) #chatMoreBtn { display: grid; }" in PAGE
    assert "body.in-chat:not(.split):not(.focus) #helpBtn, body.in-chat:not(.split):not(.focus) #settingsBtn," in PAGE
    assert 'document.body.classList.toggle("in-chat", v === "session");' in PAGE


def test_no_second_list():
    title = PAGE[PAGE.index('$("title").onclick'):].split("\n")[0]
    assert "else if (FOCUS) openSwitcher();" in title                 # только фокус-ссылка на проект
    target = PAGE[PAGE.index('$("target").onclick'):].split("\n")[0]
    assert "FOCUS ? openSwitcher() : split() ? navSearch(true) : navOpen(true)" in target
    assert '{ label: "Подсказать", icon: "help", run: () => $("helpBtn").click() }' in PAGE
