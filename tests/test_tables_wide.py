"""Владелец 21.11: «таблицы не красиво открываются и то что экран только по центру». Ячейки таблицы наследовали
overflow-wrap: anywhere пузыря ответа — колонка сжималась до букв («Об/раз»); лента на широком экране — 760 px."""
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/index.html").read_text(encoding="utf-8")


def test_table_cells_do_not_break_words():
    assert ".md th, .md td { overflow-wrap: normal; word-break: normal; }" in HTML
    assert ".md td a, .md th a { overflow-wrap: anywhere; }" in HTML        # длинные ссылки — переносятся
    assert ".md .tbl { overflow-x: auto;" in HTML                           # шире ленты — прокрутка, не сжатие


def test_wide_screen_lane_wider_text_readable():
    assert "body.split #session, body.split .dock > *, body.split .tabsbar .seg { max-width: 1120px; }" in HTML
    assert "body.split .chat .ai .md > :is(p, ul, ol, h1, h2, h3, h4, blockquote) { max-width: 780px; }" in HTML
