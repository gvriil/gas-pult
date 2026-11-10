"""Ссылки в ответах Claude: найти адреса (и без схемы) и сделать их нажимаемыми в Telegram.

Правила те же, что у панели (блок «link:start … link:end» в web/index.html, сверка — tests/test_chat_links.py):
только http(s); адрес без схемы (pult.example.su/x, claude.ai/…) — домен с известной зоной, ссылка на https://;
file.py, 1.2.3, v2.0, почта — не адреса; хвостовая пунктуация («.», «,», «)», «»») — не часть адреса.

Telegram сам находит адреса в простом тексте, но не внутри <code>/<pre> и не всякий адрес без схемы. Поэтому ответ
уходит HTML: текст экранирован, `код` — <code>, а адрес из него вынесен ссылкой; блок ```…``` — <pre>, а под ним —
строка «Ссылки: …» с адресами из блока. ``messages`` режет такой HTML на сообщения до 4096 знаков, не ломая теги.
"""

import html
import re

TLD = ("ru|su|com|net|org|io|ai|dev|app|me|co|рф|info|biz|xyz|tech|pro|site|online|cloud|page|tv|eu|de|uk|us|kz|by|"
       "ua|uz|gg|fm|club|shop|store|space|link|news|blog|team|tools|chat")
_LN = r"[^\W_]"                       # буква или цифра (в JS — \p{L}\p{N})
URL_RE = re.compile(r"\bhttps?://[^\s<>\"'`]+|(?:" + _LN + r"(?:" + _LN + r"|-){0,62}\.)+(?:" + TLD + r")(?!" + _LN
                    + r"|[_-]|\." + _LN + r")(?::\d{1,5})?(?:[/?#][^\s<>\"'`]*)?", re.I)
BEFORE = re.compile(r"[^\W]|[@./\\-]")
LIMIT = 4000                          # лимит Telegram — 4096; запас на «[окно]» и сущности
MAX_LINKS = 10                        # строка «Ссылки: …» под блоком кода — не больше


def trim(u: str) -> str:
    """Хвост «.», «,», «!», «?»… и непарная закрывающая скобка — не адрес."""
    while True:
        c = u[-1:]
        unbalanced = any(c == b and u.count(b) > u.count(a) for a, b in ("()", "[]", "{}"))
        if (c and c in ".,;:!?…»”’") or unbalanced:
            u = u[:-1]
        else:
            return u


def _href(u: str) -> str:
    from urllib.parse import urlsplit
    try:
        x = urlsplit(u)
    except ValueError:
        return ""
    return u if x.scheme.lower() in ("http", "https") and x.hostname else ""


def parts(text: str, code: bool = False) -> list:
    """Python-двойник linkParts панели: ``["см. ", {"url": "a.ru/x", "href": "https://a.ru/x"}, "."]``.
    ``code`` — текст из кода: адрес без схемы — только с путём, портом или поддоменом («self.app» — не адрес)."""
    out, last = [], 0
    for m in URL_RE.finditer(text):
        bare = not re.match(r"https?:", m.group(0), re.I)
        if bare and m.start() and BEFORE.match(text[m.start() - 1]):
            continue
        u = trim(m.group(0))
        href = _href("https://" + u if bare else u)
        if bare and code and not re.search(r"[/:]|\..*\.", u):
            continue
        if not href:
            continue
        if m.start() > last:
            out.append(text[last:m.start()])
        out.append({"url": u, "href": href})
        last = m.start() + len(u)
    if last < len(text):
        out.append(text[last:])
    return out


def _a(p: dict) -> str:
    return f'<a href="{html.escape(p["href"], quote=True)}">{html.escape(p["url"], quote=False)}</a>'


def _text(s: str, code: bool = False) -> str:
    """Строка → HTML: адреса — <a>, в коде — <code>, адрес из кода — вынесен из <code> ссылкой."""
    out = []
    for p in parts(s, code):
        if isinstance(p, dict):
            out.append(_a(p))
        elif p:
            out.append(f"<code>{html.escape(p, quote=False)}</code>" if code else html.escape(p, quote=False))
    return "".join(out)


INLINE = re.compile(r"`([^`\n]+)`")
FENCE = re.compile(r"^\s*```")


def _line(s: str) -> str:
    out, last = [], 0
    for m in INLINE.finditer(s):
        out.append(_text(s[last:m.start()]))
        out.append(_text(m.group(1), code=True))
        last = m.end()
    out.append(_text(s[last:]))
    return "".join(out)


def _units(text: str):
    """Ответ по строкам: ("t", строка) · ("pre", [строки блока]) · ("links", [адреса из блока])."""
    code, links = None, []
    for ln in str(text).split("\n"):
        if FENCE.match(ln):
            if code is None:
                code = []
                continue
            yield "pre", code
            if links:
                yield "links", links[:MAX_LINKS]
            code, links = None, []
            continue
        if code is None:
            yield "t", ln
            continue
        code.append(ln)
        for p in parts(ln, code=True):
            if isinstance(p, dict) and p["href"] not in {x["href"] for x in links}:
                links.append(p)
    if code is not None:                  # блок не закрыт — до конца ответа он код
        yield "pre", code
        if links:
            yield "links", links[:MAX_LINKS]


def _plain(raw: str, limit: int) -> list[str]:
    """Строка длиннее сообщения — без разметки, кусками (экранирование растит текст не больше чем в 5 раз)."""
    n = max(1, limit // 5)
    return [html.escape(raw[i:i + n], quote=False) for i in range(0, len(raw), n)] or [""]


def _pieces(text: str, limit: int) -> list[str]:
    """Цельные куски HTML (каждый не длиннее limit): строка текста, блок <pre> или его часть, строка «Ссылки»."""
    out = []
    for kind, v in _units(text):
        if kind == "t":
            h = _line(v)
            out += [h] if len(h) <= limit else _plain(v, limit)
        elif kind == "links":
            h = "Ссылки: " + ", ".join(_a(p) for p in v)
            out += [h] if len(h) <= limit else _plain("Ссылки: " + ", ".join(p["url"] for p in v), limit)
        else:
            cur: list[str] = []
            for ln in v:
                for e in ([html.escape(ln, quote=False)] if len(ln) * 5 <= limit - 11 else _plain(ln, limit - 11)):
                    if cur and len("\n".join(cur)) + 1 + len(e) > limit - 11:
                        out.append("<pre>" + "\n".join(cur) + "</pre>")
                        cur = []
                    cur.append(e)
            out.append("<pre>" + "\n".join(cur) + "</pre>")
    return out


def answer_html(text: str) -> str:
    """Ответ Claude (markdown как есть) → HTML для Telegram (parse_mode=HTML), одной строкой."""
    return "\n".join(_pieces(text, 10 ** 9))


def messages(text: str, head: str = "", limit: int = LIMIT) -> list[str]:
    """Ответ → сообщения Telegram (HTML) не длиннее limit; разрез — только между цельными кусками, теги не рвутся.
    ``head`` — заголовок («[окно]»), простой текст: экранируется здесь."""
    pieces = ([html.escape(head, quote=False)] if head else []) + _pieces(text, limit)
    out, cur = [], ""
    for p in pieces:
        if cur and len(cur) + 1 + len(p) > limit:
            out.append(cur)
            cur = p
        else:
            cur = cur + "\n" + p if cur else p
    if cur or not out:
        out.append(cur or "—")
    return out
