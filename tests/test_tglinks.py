"""Ссылки в ответах Claude для Telegram (tglinks): HTML с нажимаемыми адресами — и без схемы, и из `кода`; под блоком
кода — «Ссылки: …»; экранирование; разрез на сообщения до 4096 без порванных тегов; бот шлёт HTML, а если Telegram
не разобрал разметку — тот же ответ текстом."""

import re
from html.parser import HTMLParser

import pytest

from gas_pult import bot, tglinks
from gas_pult.telegram import TelegramError

ALLOWED = {"a", "code", "pre"}


class Check(HTMLParser):
    """Разметка — только <a href>, <code>, <pre>; теги парные и без вложенности в код."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.text, self.hrefs = [], [], []

    def handle_starttag(self, tag, attrs):
        assert tag in ALLOWED, tag
        assert not ({"code", "pre"} & set(self.stack)), f"{tag} внутри кода"   # Telegram не вкладывает в код
        if tag == "a":
            assert [k for k, _ in attrs] == ["href"]
            self.hrefs.append(dict(attrs)["href"])
        self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack and self.stack.pop() == tag, tag

    def handle_data(self, data):
        self.text.append(data)


def parse(h: str) -> Check:
    c = Check()
    c.feed(h)
    c.close()
    assert not c.stack, c.stack
    return c


def test_bare_and_trailing_punctuation():
    h = tglinks.answer_html("см. pult.example.su:8443/x. и (claude.ai/code/abc), file.py 1.2.3 v2.0 a.b a@mail.ru")
    c = parse(h)
    assert c.hrefs == ["https://pult.example.su:8443/x", "https://claude.ai/code/abc"]
    assert '<a href="https://pult.example.su:8443/x">pult.example.su:8443/x</a>. и (' in h
    assert "file.py 1.2.3 v2.0 a.b a@mail.ru" in h


def test_inline_code_url_taken_out_of_code():
    h = tglinks.answer_html("Открой `https://a.ru/b` и `curl pult.example.su/api?x=1&y=2` и `self.app`")
    c = parse(h)
    assert c.hrefs == ["https://a.ru/b", "https://pult.example.su/api?x=1&y=2"]
    assert '<code>curl </code><a href="https://pult.example.su/api?x=1&amp;y=2">' in h
    assert "<code>self.app</code>" in h                                       # атрибут в коде — не сайт


def test_code_block_stays_code_and_links_below():
    text = "Вот:\n```bash\ncurl https://x.com/a?b=1&c=<2>\nopen site.ru/x\ncurl https://x.com/a?b=1&c=<2>\n```\nконец"
    h = tglinks.answer_html(text)
    c = parse(h)
    assert "<pre>curl https://x.com/a?b=1&amp;c=&lt;2&gt;\nopen site.ru/x\ncurl" in h     # код — текстом, как есть
    links = h.split("</pre>\n", 1)[1].split("\n")[0]
    assert links.startswith("Ссылки: ")
    assert c.hrefs == ["https://x.com/a?b=1&c=", "https://site.ru/x"]       # без повторов; «<» — граница адреса
    assert h.endswith("\nконец")


def test_unclosed_block_and_escaping():
    h = tglinks.answer_html('<b>жирный</b> & "кавычки" javascript:alert(1)\n```\nhttps://e.com/"onmouseover=x')
    c = parse(h)
    assert "&lt;b&gt;жирный&lt;/b&gt; &amp; \"кавычки\" javascript:alert(1)" in h
    assert c.hrefs == ["https://e.com/"]                                    # кавычка — конец адреса
    assert all(x.startswith("https://") for x in c.hrefs)


def test_split_keeps_tags_whole():
    body = "\n".join(f"строка {i} https://a.ru/{i}?q=1&r=<2>" for i in range(300))
    text = "Начало pult.example.su/x\n```\n" + body + "\n```\n" + "слово site.ru/y " * 1500 + "\n" + "я" * 9000
    msgs = tglinks.messages(text, "[окно <1>]")
    assert len(msgs) > 3 and all(len(m) <= tglinks.LIMIT for m in msgs)
    assert msgs[0].startswith("[окно &lt;1&gt;]\n")
    for m in msgs:
        parse(m)                                                            # каждое сообщение — целый HTML
    joined = "".join("".join(parse(m).text) for m in msgs)
    assert joined.count("строка ") == 300 and joined.count("я") >= 9000


def test_short_answer_one_message():
    assert tglinks.messages("ок") == ["ок"]
    assert tglinks.messages("", "[w]") == ["[w]\n"]


def make_pult(fail: str = ""):
    p = bot.Pult.__new__(bot.Pult)
    p.calls = []

    def api(method, **kw):
        p.calls.append(kw)
        if fail and kw.get("parse_mode") == "HTML":
            raise TelegramError("sendMessage", fail)
        return {"message_id": len(p.calls)}

    p.api = api
    return p


def test_bot_sends_html_with_buttons_on_last():
    p = make_pult()
    text = "Готово: claude.ai/code/x\n```\n" + "\n".join(f"echo https://a.ru/{i}" for i in range(400)) + "\n```"
    r = p.send_answer(1, "[w]", text, reply_markup="KB")
    assert len(p.calls) > 1 and r == {"message_id": len(p.calls)}
    assert all(c["parse_mode"] == "HTML" and len(c["text"]) <= 4096 for c in p.calls)
    assert [("reply_markup" in c) for c in p.calls] == [False] * (len(p.calls) - 1) + [True]
    assert '<a href="https://claude.ai/code/x">' in p.calls[0]["text"]


def test_bot_falls_back_to_plain_text():
    p = make_pult("Bad Request: can't parse entities: unexpected end tag")
    p.send_answer(1, "[w]", "текст site.ru", reply_markup="KB")
    assert p.calls[-1] == {"chat_id": 1, "text": "[w]\nтекст site.ru", "reply_markup": "KB"}
    p = make_pult("Bad Request: chat not found")
    with pytest.raises(TelegramError):
        p.send_answer(1, "[w]", "текст")


def test_deliver_uses_html():
    src = open(bot.__file__, encoding="utf-8").read()
    body = src[src.index("    def deliver("):src.index("    def offer_hints(")]
    assert re.search(r"self\.send_answer\(chat, f\"\[\{w\['name'\]\}\]\", text", body)
