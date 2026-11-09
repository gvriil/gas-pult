"""Текст ответа → то, что синтез произносит по-русски: ссылки — словом «ссылка», числа — словами,
латинские названия — русскими буквами.

Silero (голоса владельца) цифры и латиницу пропускает молча, Piper читает их неровно — поэтому числа и латиницу
переводим в слова здесь, на стандартной библиотеке. ElevenLabs латиницу читает сам — для него её можно оставить
(``latin=True``). Разумный минимум, не полный нормализатор: целые, десятичные, проценты, даты ДД.ММ(.ГГГГ),
время ЧЧ:ММ, порядковые «5-й»/«1-го», род для «одна минута / две недели», сокращения «мин», «ч», «дн.».
"""

from __future__ import annotations

import re

# ---------- ссылки и пути ----------
EXT = ("py|pyc|js|mjs|ts|tsx|jsx|html|htm|css|md|json|jsonl|toml|yaml|yml|txt|sh|bash|log|ini|cfg|conf|env|"
       "service|timer|go|rs|java|kt|swift|rb|php|c|h|cpp|hpp|sql|csv|tsv|pdf|png|jpg|jpeg|gif|svg|webp|mp3|"
       "wav|ogg|mp4|zip|tar|gz|docx|xlsx|pptx|lock|patch|diff|kdbx")
TLD = "ru|su|com|org|net|io|dev|ai|app|me|info|рф|tech|cloud|so|sh|co"
_MDLINK = re.compile(r"!?\[([^\]]*)\]\(([^)\s]*)[^)]*\)")
_URL = re.compile(r"(?:\b(?:https?|ftp|wss?|file)://|\bwww\.)[^\s<>«»\"')\]]+", re.I)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_DOMAIN = re.compile(rf"(?<![\w/@.])(?:[a-z0-9-]+\.)+(?:{TLD})\b(?:/[^\s<>«»\"')\]]*)?(?![\w.])", re.I)
_SEG = r"[\w.@+-]"
_PATH = re.compile(                                   # ~/a/b, /etc/x, ./x, a/b/c.py:12, a/b.py
    rf"(?<![\w/~.])(?:(?:~|\.{{1,2}})?/(?:{_SEG}+/)*{_SEG}*|{_SEG}+(?:/{_SEG}+)+/?)(?::(\d+))?(?::\d+)?(?![\w/])")
_FILE = re.compile(rf"(?<![\w/.])([\w-]+(?:\.[\w-]+)*)\.(?:{EXT})(?::(\d+))?(?::\d+)?(?![\w])", re.I)


def _looks_link(s: str) -> bool:
    return bool(_URL.fullmatch(s.strip()) or _DOMAIN.fullmatch(s.strip()) or s.strip().startswith(("/", "~/", "./")))


def _path(m: re.Match) -> str:
    raw, line = m.group(0), m.group(1)
    body = raw.split(":")[0].rstrip("/")
    if body.count("/") == 1 and not body.startswith(("/", "~", ".")) and "." not in body:
        return raw                                    # «и/или», «TCP/IP» — не путь
    name = body.rsplit("/", 1)[-1]
    if not name or name in ("~", ".", ".."):
        return " папка "
    m2 = re.fullmatch(rf"(.+?)\.(?:{EXT})", name, re.I)
    if m2:
        out = " файл " + _words(m2.group(1))
    elif raw.rstrip(":0123456789").endswith("/") or "." not in name:
        out = " папка " + _words(name)
    else:
        out = " файл " + _words(name)
    return out + (f", строка {line} " if line else " ")


def _file(m: re.Match) -> str:
    return " файл " + _words(m.group(1)) + (f", строка {m.group(2)} " if m.group(2) else " ")


def _words(name: str) -> str:
    return re.sub(r"[_.-]+", " ", name).strip()


def links(text: str) -> str:
    """Ссылки не читаем: «ссылка»; подпись markdown-ссылки — читаем, если это не сам адрес. Пути — по имени файла."""
    text = _MDLINK.sub(lambda m: " ссылка " if not m.group(1).strip() or _looks_link(m.group(1))
                       else m.group(1), text)
    text = _URL.sub(" ссылка ", text)
    text = _EMAIL.sub(" адрес почты ", text)
    text = _DOMAIN.sub(" ссылка ", text)
    text = _PATH.sub(_path, text)
    return _FILE.sub(_file, text)


# ---------- числа ----------
UNITS = ["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять", "десять",
         "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать", "семнадцать",
         "восемнадцать", "девятнадцать"]
TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"]
SCALES = [(10 ** 9, ("миллиард", "миллиарда", "миллиардов"), False), (10 ** 6, ("миллион", "миллиона", "миллионов"),
          False), (1000, ("тысяча", "тысячи", "тысяч"), True)]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября",
          "декабря"]
# Порядковые: основа последнего слова; «-ой» под ударением — у второго, шестого, седьмого, восьмого, сорокового.
ORD_UNITS = ["", "перв", "втор", "трет", "четвёрт", "пят", "шест", "седьм", "восьм", "девят", "десят", "одиннадцат",
             "двенадцат", "тринадцат", "четырнадцат", "пятнадцат", "шестнадцат", "семнадцат", "восемнадцат",
             "девятнадцат"]
ORD_TENS = ["", "", "двадцат", "тридцат", "сороков", "пятидесят", "шестидесят", "семидесят", "восьмидесят",
            "девяност"]
ORD_HUNDREDS = ["", "сот", "двухсот", "трёхсот", "четырёхсот", "пятисот", "шестисот", "семисот", "восьмисот",
                "девятисот"]
ORD_THOUSANDS = {1: "тысячн", 2: "двухтысячн", 3: "трёхтысячн"}
STRESSED = {"втор", "шест", "седьм", "восьм", "сороков"}
# Слова женского рода после числа: «одна минута», «две недели», «двадцать одна строка».
FEM = re.compile(r"(?:минут|секунд|недел|строк|ошибк|ошибок|сесси|задач|кнопк|верси|тысяч|копе|ссылк|страниц|"
                 r"команд|папк|запис|программ|модел|стро[кч]|част|причин|правк|вкладк|функци|ветк|машин|"
                 r"шторк|кнопок|целых|десят|сотых|ночь|ноч)", re.I)


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _triple(n: int, fem: bool) -> list[str]:
    out = [HUNDREDS[n // 100]] if n >= 100 else []
    n %= 100
    if n >= 20:
        out.append(TENS[n // 10])
        n %= 10
    if n or not out:
        out.append({1: "одна", 2: "две"}.get(n, UNITS[n]) if fem else UNITS[n])
    return [w for w in out if w]


def cardinal(n: int, fem: bool = False) -> str:
    """Целое словами: 21 → «двадцать один», ``fem`` — «двадцать одна»."""
    if n < 0:
        return "минус " + cardinal(-n, fem)
    if n == 0:
        return "ноль"
    if n >= 10 ** 12:
        return " ".join(UNITS[int(d)] for d in str(n))
    out = []
    for size, forms, female in SCALES:
        if n >= size:
            k = n // size
            out += ([] if k == 1 and female else _triple(k, female)) + [plural(k, *forms)]   # «тысяча двести»
            n %= size
    if n:
        out += _triple(n, fem)
    return " ".join(out)


def _ord_end(stem: str, end: str) -> str:
    if stem == "трет":
        return "трет" + {"й": "ий", "я": "ья", "е": "ье", "го": "ьего", "м": "ьем", "ю": "ью", "х": "ьих",
                         "му": "ьему"}.get(end, "ий")
    return stem + {"й": "ой" if stem in STRESSED else "ый", "я": "ая", "е": "ое", "го": "ого", "м": "ом", "ю": "ую",
                   "х": "ых", "му": "ому"}.get(end, "ый")


def ordinal(n: int, end: str = "й") -> str:
    """Порядковое: (5, «го») → «пятого», (2026, «го») → «две тысячи двадцать шестого»."""
    if n <= 0 or n >= 10 ** 6:
        return cardinal(n)
    if n % 1000 == 0:
        k = n // 1000
        return _ord_end(ORD_THOUSANDS[k], end) if k in ORD_THOUSANDS else cardinal(n)
    head, low = n - n % 100, n % 100
    if low == 0:                                    # 100, 300, 1200
        head, stem = n - n % 1000, ORD_HUNDREDS[n % 1000 // 100]
    elif low < 20:
        stem = ORD_UNITS[low]
    elif low % 10 == 0:
        stem = ORD_TENS[low // 10]
    else:
        head, stem = n - n % 10, ORD_UNITS[low % 10]
    return ((cardinal(head) + " ") if head else "") + _ord_end(stem, end)


def decimal(whole: str, frac: str) -> str:
    """«1,5» → «одна целая пять десятых»; больше трёх знаков после запятой — по цифрам."""
    w = int(whole)
    if len(frac) > 3:
        return cardinal(w) + " точка " + " ".join(UNITS[int(d)] for d in frac)
    f = int(frac)
    den = {1: ("десятая", "десятых"), 2: ("сотая", "сотых"), 3: ("тысячная", "тысячных")}[len(frac)]
    return (f"{cardinal(w, True)} {plural(w, 'целая', 'целых', 'целых')} "
            f"{cardinal(f, True)} {den[0] if plural(f, 1, 2, 2) == 1 else den[1]}")


ABBR = {                                             # сокращение после числа → (одна, две, пять), женский род
    "мин": (("минута", "минуты", "минут"), True), "сек": (("секунда", "секунды", "секунд"), True),
    "ч": (("час", "часа", "часов"), False), "дн": (("день", "дня", "дней"), False),
    "мс": (("миллисекунда", "миллисекунды", "миллисекунд"), True),
    "кб": (("килобайт", "килобайта", "килобайт"), False), "мб": (("мегабайт", "мегабайта", "мегабайт"), False),
    "гб": (("гигабайт", "гигабайта", "гигабайт"), False), "тб": (("терабайт", "терабайта", "терабайт"), False),
    "kb": (("килобайт", "килобайта", "килобайт"), False), "mb": (("мегабайт", "мегабайта", "мегабайт"), False),
    "gb": (("гигабайт", "гигабайта", "гигабайт"), False),
    "руб": (("рубль", "рубля", "рублей"), False), "₽": (("рубль", "рубля", "рублей"), False),
    "$": (("доллар", "доллара", "долларов"), False), "€": (("евро", "евро", "евро"), False),
    "шт": (("штука", "штуки", "штук"), True), "км": (("километр", "километра", "километров"), False),
}
_ABBR = "|".join(sorted((re.escape(k) for k in ABBR), key=len, reverse=True))
_N = r"(?<![\w.,:])"                                  # число не продолжает слово, версию или дробь


def _num_word(m: re.Match) -> str:
    n = int(m.group(1).replace(" ", "").replace("\u00a0", "").replace("\u202f", ""))
    nxt = m.group(2) or ""
    return cardinal(n, bool(FEM.match(nxt.strip()))) + nxt


def numbers(text: str) -> str:
    """Числа словами. Порядок важен: сначала даты, время, версии и дроби — потом целые."""
    t = text
    t = re.sub(rf"{_PREP}(?<![\d.])(\d{{1,2}})\.(\d{{2}})\.(\d{{4}})(?![\d.])", lambda m: _date(m, int(m.group(4))), t,
               flags=re.I)
    t = re.sub(r"\b(\d+(?:\.\d+){2,})\b", lambda m: " точка ".join(cardinal(int(x)) for x in m.group(1).split(".")), t)
    t = re.sub(r"(?<=\d)(?:s|с)(?![\wа-яё])", " сек", t)          # «56.7s», «3с» — секунды
    t = re.sub(rf"{_PREP}(?<![\d.,])(\d{{1,2}})\.(\d{{2}})(?![\d])(?!\.\d)", lambda m: _date(m, None), t, flags=re.I)
    t = re.sub(r"(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])", _time, t)
    t = re.sub(r"(?<![\w.,])(\d{3,4})(\s+)(год|года|году|годом|гг?\.)(?!\w)",
               lambda m: ordinal(int(m.group(1)), {"год": "й", "года": "го", "году": "м", "годом": "м"}
                                 .get(m.group(3), "го")) + m.group(2) + {"г.": "года", "гг.": "годов"}
               .get(m.group(3), m.group(3)), t)
    t = re.sub(r"(?<![\w.,])(\d+)-(й|я|е|го|му|м|ю|х|ого|ый|ий|ая|ое)(?!\w)",
               lambda m: ordinal(int(m.group(1)), {"ого": "го", "ый": "й", "ий": "й", "ая": "я", "ое": "е"}
                                 .get(m.group(2), m.group(2))), t)
    t = re.sub(rf"{_N}(\d+)[.,](\d+)(?![\d.,]\d)(\s*%|\s*(?:{_ABBR})(?:\.|(?![\wа-яё])))?", _dec_unit, t,
               flags=re.I)
    t = re.sub(rf"{_N}(\d{{1,3}}(?:[ \u00a0\u202f]\d{{3}})+|\d+)\s*%",
               lambda m: _count(int(re.sub(r"\D", "", m.group(1))), ("процент", "процента", "процентов"), False), t)
    t = re.sub(rf"{_N}(\d{{1,3}}(?:[ \u00a0\u202f]\d{{3}})+|\d+)\s*({_ABBR})(?:\.|(?![\wа-яё]))",
               lambda m: _count(int(re.sub(r"\D", "", m.group(1))), *ABBR[m.group(2).lower()]), t, flags=re.I)
    t = re.sub(r"[№#]\s*(\d+)", r"номер \1", t)
    t = re.sub(r"(?<![\w.,-])[-−](\d)", r"минус \1", t)
    t = re.sub(r"(\d)\s*[-–—]\s*(\d)", r"\1 — \2", t)
    return re.sub(rf"{_N}(\d{{1,3}}(?:[ \u00a0\u202f]\d{{3}})+|\d+)(?![\d])(\s*[\wа-яё]*)", _num_word, t)


def _dec_unit(m: re.Match) -> str:
    unit = (m.group(3) or "").strip().rstrip(".").lower()
    word = "процента" if unit == "%" else ABBR[unit][0][1] if unit in ABBR else ""
    return decimal(m.group(1), m.group(2)) + (" " + word if word else "")


def _count(n: int, forms: tuple[str, str, str], fem: bool) -> str:
    return f"{cardinal(n, fem)} {plural(n, *forms)}"


_PREP = r"(?:\b(до|с|со|после|от|около|к|ко)\s+)?"          # «до 09.11» → «до девятого ноября»
CASE = {"к": "му", "ко": "му"}


def _date(m: re.Match, year: int | None) -> str:
    prep = m.group(1)
    d, mo = int(m.group(2)), int(m.group(3))
    lead = prep + " " if prep else ""
    if not (1 <= d <= 31 and 1 <= mo <= 12):
        return lead + (decimal(m.group(2), m.group(3)) if year is None else m.group(0)[len(lead):])
    out = f"{lead}{ordinal(d, CASE.get((prep or '').lower(), 'го') if prep else 'е')} {MONTHS[mo - 1]}"
    return out + (f" {ordinal(year, 'го')} года" if year else "")


def _time(m: re.Match) -> str:
    h, mi = int(m.group(1)), int(m.group(2))
    tail = "ноль-ноль" if mi == 0 else (f"ноль {cardinal(mi, True)}" if mi < 10 else cardinal(mi, True))
    return f"{cardinal(h)} {tail}"


# ---------- латиница ----------
WORDS = {                                            # частые названия — как их говорят по-русски
    "github": "гитхаб", "gitlab": "гитлаб", "git": "гит", "claude": "клод", "anthropic": "антропик",
    "pr": "пи-ар", "prs": "пи-ары", "api": "эй-пи-ай", "ci": "си-ай", "cd": "си-ди", "url": "ю-ар-эл",
    "telegram": "телеграм", "python": "пайтон", "pytest": "пайтест", "ruff": "рафф", "tmux": "ти-макс",
    "linux": "линукс", "ubuntu": "убунту", "docker": "докер", "mac": "мак", "macos": "мак-ос", "ios": "ай-ос",
    "ok": "окей", "okay": "окей", "json": "джейсон", "html": "эйч-ти-эм-эл", "css": "си-эс-эс",
    "javascript": "джаваскрипт", "typescript": "тайпскрипт", "js": "джей-эс", "ssh": "эс-эс-эйч",
    "vpn": "ви-пи-эн", "elevenlabs": "элевен лабс", "silero": "силеро", "piper": "пайпер", "notion": "ноушн",
    "linear": "линеар", "google": "гугл", "chrome": "хром", "iphone": "айфон", "android": "андроид",
    "commit": "коммит", "commits": "коммиты", "push": "пуш", "merge": "мёрдж", "main": "мейн", "branch": "бранч",
    "deploy": "деплой", "e2e": "и-ту-и", "openrouter": "опенроутер", "deepseek": "дипсик", "glm": "джи-эл-эм",
    "opus": "опус", "sonnet": "соннет", "haiku": "хайку", "mcp": "эм-си-пи", "caddy": "кэдди", "npm": "эн-пи-эм",
    "id": "ай-ди", "ai": "эй-ай", "ui": "ю-ай", "ux": "ю-экс", "tts": "ти-ти-эс", "stt": "эс-ти-ти",
    "dns": "ди-эн-эс", "ip": "ай-пи", "http": "эйч-ти-ти-пи", "https": "эйч-ти-ти-пи-эс", "pdf": "пи-ди-эф",
    "cli": "си-эл-ай", "sql": "эс-кью-эл", "wifi": "вай-фай", "email": "имейл", "readme": "ридми",
    "changelog": "ченджлог", "handoff": "хэндофф", "code": "код", "app": "апп", "mini": "мини", "web": "веб",
    "webapp": "вебапп", "bot": "бот", "panel": "панель", "pult": "пульт", "gas": "гас", "server": "сервер",
    "token": "токен", "tokens": "токены", "the": "зе", "and": "энд", "of": "оф", "to": "ту", "for": "фор",
    "with": "виз", "safari": "сафари", "firefox": "файрфокс", "windows": "виндоус", "playwright": "плейрайт",
    "linkedin": "линкедин", "youtube": "ютуб", "whatsapp": "ватсап", "openai": "опен эй-ай", "gpt": "джи-пи-ти",
    "chatgpt": "чат джи-пи-ти", "gemini": "джемини", "codex": "кодекс", "xray": "икс-рэй", "nginx": "энджинкс",
    "systemd": "систем-ди", "cron": "крон", "yandex": "яндекс", "ozon": "озон", "wildberries": "вайлдберриз",
    "todo": "ту-ду", "faq": "эф-эй-кью", "sdk": "эс-ди-кей", "oauth": "о-аут", "passkey": "пасски",
    "passkeys": "пасски", "keepassxc": "кипасс", "pass": "пасс", "gpg": "джи-пи-джи", "stdlib": "стдлиб",
}
LETTERS = {"a": "эй", "b": "би", "c": "си", "d": "ди", "e": "и", "f": "эф", "g": "джи", "h": "эйч", "i": "ай",
           "j": "джей", "k": "кей", "l": "эл", "m": "эм", "n": "эн", "o": "оу", "p": "пи", "q": "кью", "r": "ар",
           "s": "эс", "t": "ти", "u": "ю", "v": "ви", "w": "дабл-ю", "x": "икс", "y": "уай", "z": "зед"}
DIGRAPHS = [("tion", "шн"), ("sch", "ш"), ("sh", "ш"), ("ch", "ч"), ("th", "т"), ("ph", "ф"), ("kh", "х"),
            ("zh", "ж"), ("ts", "ц"), ("ck", "к"), ("qu", "кв"), ("oo", "у"), ("ee", "и"), ("ea", "и"),
            ("ou", "ау"), ("ai", "ей"), ("ay", "ей"), ("ey", "ей"), ("oa", "о"), ("ya", "я"), ("yu", "ю"),
            ("yo", "ё"), ("ye", "е"), ("x", "кс"), ("w", "в"), ("j", "дж"), ("q", "к")]
SINGLE = dict(zip("abdefghiklmnoprstuvz", "абдефгхиклмнопрстувз", strict=True))


def _translit(w: str) -> str:
    low = w.lower()
    if low in WORDS:
        return WORDS[low]
    if (w.isupper() and len(w) <= 4) or len(w) == 1:   # PR, SSH, «X» — по буквам
        return "-".join(LETTERS.get(c, c) for c in low)
    out, i = [], 0
    if len(low) > 3 and low.endswith("e") and low[-2] not in "aeiouy":
        low = low[:-1]                                # немая «e» на конце: «make» → «мейк» не выйдет, но «code» → «код»
    while i < len(low):
        for a, b in DIGRAPHS:
            if low.startswith(a, i):
                out.append(b)
                i += len(a)
                break
        else:
            c = low[i]
            if c == "c":
                out.append("с" if low[i + 1:i + 2] in ("e", "i", "y") else "к")
            elif c == "y":
                out.append("й" if i == 0 else "и")
            elif c == "e" and i == 0:
                out.append("э")
            else:
                out.append(SINGLE.get(c, c))
            i += 1
    return "".join(out)


def _latin_word(m: re.Match) -> str:
    w = m.group(0)
    if w.lower() in WORDS:
        return WORDS[w.lower()]
    parts = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+", w)   # CamelCase и «gpt4» — по частям
    return " ".join(p if p.isdigit() else _translit(p) for p in parts) if len(parts) > 1 else _translit(w)


def latin(text: str) -> str:
    """Латинские слова — русскими буквами: словарь частых, затем общий транслит; сокращения — по буквам."""
    for phrase, said in (("claude code", "клод код"), ("mini app", "мини апп"), ("pull request", "пулл реквест"),
                         ("open source", "опен сорс")):
        text = re.sub(rf"\b{phrase}\b", said, text, flags=re.I)
    return re.sub(r"(?<![\w])[A-Za-z][A-Za-z0-9]*(?:'[a-z]+)?", _latin_word, text)


def speakable(text: str, latin_ok: bool = False) -> str:
    """Готовый к синтезу текст. ``latin_ok`` — синтез сам читает латиницу (ElevenLabs): её не трогаем."""
    t = re.sub(r"\be2e\b", "и-ту-и" if not latin_ok else "e2e", links(text), flags=re.I)
    t = re.sub(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b", " хеш ", t)   # хеши коммитов не читаем
    t = re.sub(r"\bv(\d)", r"версия \1", t)
    t = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z]{2})", " ", t) if not latin_ok else t
    t = numbers(t)
    if not latin_ok:
        t = latin(t)
    t = re.sub(r"\b(файл|папка|ссылка)(\s+\1)+\b", r"\1", t, flags=re.I)   # «файл ~/x.py» → не «файл файл»
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r" +([,.;:!?])", r"\1", t).strip()
