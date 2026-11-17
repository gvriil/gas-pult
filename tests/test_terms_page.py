"""Пользовательское соглашение простым языком (владелец 17.11): /terms — без входа, RU и EN, дата редакции, пометка
«до проверки юристом», правила поставщиков, данные и секреты, без цен; ссылки — с экрана согласия, из мастера
«Подключить компьютер» и из README."""

import urllib.request
from pathlib import Path

from test_project_chats import server as server

ROOT = Path(__file__).resolve().parents[1]


def test_terms_page_public_and_complete(server):
    _p, base, *_ = server
    with urllib.request.urlopen(base + "/terms", timeout=10) as r:          # без cookie и initData
        assert r.status == 200 and r.headers.get_content_type() == "text/html"
        html = r.read().decode("utf-8")
    for need in ("Редакция от 17 ноября 2026", "До проверки юристом", "Revision of 17 November 2026",
                 "Not yet reviewed by a lawyer", "свой ключ или своя подписка", "Не передавайте свой вход",
                 "Данные и секреты", "Кто видит", "Ограничение ответственности", "Limitation of liability",
                 'id="ru"', 'id="en"'):
        assert need in html, need
    assert "₽" not in html and "$" not in html and "€" not in html                # цен нет до утверждения


def test_links_to_terms():
    web = ROOT / "src" / "gas_pult" / "web"
    assert 'href="/terms"' in (web / "index.html").read_text(encoding="utf-8")
    assert 'href="/terms"' in (web / "js" / "bridge.js").read_text(encoding="utf-8")
    assert "terms.html" in (ROOT / "README.md").read_text(encoding="utf-8")
