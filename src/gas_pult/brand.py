"""Название продукта, которое видит человек (владелец 25.11: «Ладэя» по-русски — с «э», «Ladeya» по-английски, бренд —
«Ладэя by Botsmith»; прежнее «Гаврила» / «Gavrila» и написание «Ладея» сняты). Здесь — единственное место: сервер
подставляет его в страницу (``<meta name="application-name">``, ``<title>``), манифест для экрана «Домой», письма,
уведомления и сообщения бота. Падежи — ``FORMS``. Код, пакет, пути, службы и адреса остаются ``gas-pult``/«пульт»
(docs/BRAND.md).
Знак — арфа в технике гравюры (владелец 26.11): корпус режут светлые штрихи к свету, струны с разрывами, 7-я красная
целая. Лесенка (``tools/harp_engraving.py``): ≥96 px — ``ladeya-mark``, 48–95 — ``-m``, 24–47 — ``-small`` (силуэт и
5 тонких струн), 16–23 — ``favicon`` (силуэт и красная струна); ≥192 — ``-xl`` (значки и превью).
Знак-название — антиква: «ЛАДЭЯ» с красной «Э» и «LADEYA» с красной зеркальной «E» (``web/brand/wordmark-*.svg``),
по языку интерфейса.
Знак-название (владелец 25.11): там, где название стоит как знак (шапка, вход, демо, тур, карточки, картинки), буква «э»
красная — ``wordmark()``; в обычном тексте, ``<title>`` и манифесте — без окраски."""

import re

APP_NAME_EN = "Ladeya"             # латиницей: английский интерфейс, адрес, логотип
APP_NAME_RU = "Ладэя"              # русский интерфейс (в русских строках — без латиницы, humanize.LATIN_OK)
NAME, NAME_RU = APP_NAME_EN, APP_NAME_RU   # прежние имена констант — их читает код
DEFAULT = APP_NAME_RU              # так записано в web/index.html — сервер меняет его на NAME_RU, если они разные
BY = "by Botsmith"                 # строка бренда: «Ладэя by Botsmith», «Ladeya by Botsmith»
FORMS = {"им": "Ладэя", "род": "Ладэи", "дат": "Ладэе", "вин": "Ладэю", "твор": "Ладэей", "пр": "Ладэе"}   # без окраски
OLD_E = ("Ладеей", "Ладея", "Ладеи", "Ладее", "Ладею")   # написание через «е» (до 25.11) — для теста
# «э» знака: светлая (крупно, заливка), тёмная, мелкий текст на светлом (AA)
E_COLOR = {"light": "#E8421C", "dark": "#FF5A2D", "light_small": "#C2361A"}


# «э» в названии — красная ВЕЗДЕ в интерфейсе (владелец 25.11: «делай э в интерфейсе красного цвета везде»), в любом
# падеже. Исключения, где окраска невозможна: <title>, манифест, og, текстовые уведомления Telegram и пуши, письма.
WORD = re.compile(r"(?<![А-Яа-яЁё])(Лад)(э)(?=(?:я|и|е|ю|ей)(?![А-Яа-яЁё]))")
_NO_PAINT = re.compile(r"<(script|style|title|textarea)\b[^>]*>.*?</\1\s*>|<!--.*?-->|<[^>]*>", re.S | re.I)


def paint_html(html: str) -> str:
    """Готовая разметка: в тексте (не в тегах, атрибутах, <title>, <script>, <style>, <textarea>) каждое «Ладэ…» →
    «Лад<span class="e">э</span>…». Цвет — CSS панели (.e). Уже обёрнутое не трогаем: внутри «Лад<span» нет «Ладэ»."""
    out, at = [], 0
    for m in _NO_PAINT.finditer(html):
        out.append(WORD.sub(r'\1<span class="e">\2</span>', html[at:m.start()]))
        out.append(m.group(0))
        at = m.end()
    out.append(WORD.sub(r'\1<span class="e">\2</span>', html[at:]))
    return "".join(out)


WORDMARK_RU = '<span class="wm wm-ru" role="img" aria-label="Ладэя"></span>'    # «ЛАДЭЯ», красная «Э» (26.11)
WORDMARK_EN = '<span class="wm wm-en" role="img" aria-label="Ladeya"></span>'   # «LADEYA», красная зеркальная «E»


def wordmark(name: str = APP_NAME_RU) -> str:
    """Знак-название в HTML по языку (владелец 26.11): антиква картинкой (web/brand/wordmark-*.svg, стили — js/look.js),
    название — в aria-label. Любое другое слово — без изменений. Только в знаке-названии; в тексте — обычное слово."""
    return {APP_NAME_RU: WORDMARK_RU, APP_NAME_EN: WORDMARK_EN}.get(name, name)
OLD = ("Гаврилой", "Гаврилы", "Гавриле", "Гаврилу", "Гаврила", "Gavrila")   # прежнее имя — для теста


FILES_DIR = "web/brand/"   # знак и значки: gavrila-mark.svg (currentColor), -small (≤ 24 px), png — экран «Домой»
MARK = FILES_DIR + "ladeya-mark.svg"
MARK_DARK = FILES_DIR + "ladeya-mark-dark.svg"
APP_ICON = FILES_DIR + "ladeya-app-icon.svg"
LOCKUP = FILES_DIR + "gavrila-lockup.svg"
# адрес → (файл в web/brand/, тип): прежние адреса значков (GAS-20) сохранены, браузеры и iPhone их уже знают
ICONS = {"/brand/gavrila-mark.svg": ("gavrila-mark.svg", "image/svg+xml"),   # прежний знак — старые кэши
         "/brand/ladeya-mark.svg": ("ladeya-mark.svg", "image/svg+xml"),     # знак-арфа в панели: светлая тема
         "/brand/ladeya-mark-dark.svg": ("ladeya-mark-dark.svg", "image/svg+xml"),   # тёмная тема
         **{f"/brand/{n}.svg": (f"{n}.svg", "image/svg+xml") for n in (       # 16–32 px и знак-название (26.11)
             "ladeya-mark-small", "ladeya-mark-small-dark", "ladeya-mark-m", "ladeya-mark-m-dark",
             "ladeya-mark-xl", "ladeya-mark-xl-dark",
             "wordmark-ru", "wordmark-ru-dark", "wordmark-en",
             "wordmark-en-dark")},
         "/favicon.svg": ("favicon.svg", "image/svg+xml"), "/favicon-32.png": ("favicon-32.png", "image/png"),
         "/favicon-32-dark.png": ("favicon-32-dark.png", "image/png"),
         "/apple-touch-icon.png": ("apple-touch-180.png", "image/png"),
         "/icon-192.png": ("icon-192.png", "image/png"), "/icon-512.png": ("icon-512.png", "image/png"),
         "/favicon.ico": ("favicon-32.png", "image/png"),       # /favicon.ico браузеры просят сами — PNG понимают
         # владелец 21.11 «миниатюра для PWA — с лого»: превью ссылки, maskable для Android (tools/brand_images.py)
         "/og.png": ("og-1200x630.png", "image/png"), "/icon-maskable-512.png": ("icon-maskable-512.png", "image/png")}
# экраны запуска iOS (apple-touch-startup-image): CSS-ширина, высота, плотность — светлый и тёмный
IPHONES = ((440, 956, 3), (430, 932, 3), (428, 926, 3), (402, 874, 3), (393, 852, 3), (390, 844, 3), (375, 812, 3),
           (375, 667, 2))
ICONS.update({f"/splash-{w}x{h}-{t}.png": (f"splash-{w}x{h}-{t}.png", "image/png")
              for w, h, _ in IPHONES for t in ("light", "dark")})
TAGLINE = "Агент делает рутину — вы подтверждаете «Да». Ответы в телефоне, голосом и кнопкой."

# Демо и вход для гостей — бренд Botsmith (владелец 24.11: «и из демо тоже… поставь botsmith»; строка — как в питче).
# Вариант страницы — только на /?demo и /?brand=botsmith: «Ладэя» + «by Botsmith», без знака, своя строка под ним.
BS_NAME = "Botsmith"
BS_TAGLINE = "Личный ИИ-помощник и цифровой сотрудник"          # framewatcher 25.11, для М.Видео
BS_GRAD = ("linear-gradient(90deg,#111111,#111111)", "linear-gradient(90deg,#F4F4F2,#F4F4F2)")   # цвет знака
ICONS["/brand/botsmith-icon.svg"] = ("botsmith-icon.svg", "image/svg+xml")
BS_CSS = ('<style id="bsBrand">'
          '.brand-text::after{content:" ' + BY + '";font-size:12px;font-weight:500;letter-spacing:0;'
          '-webkit-text-fill-color:var(--text-secondary);color:var(--text-secondary);margin-left:6px}'
          '.nav-h h2{flex:none;font-size:calc(17px * var(--fz, 1))}'
          '#brandSub{font-size:0}#brandSub::after{content:"' + BS_TAGLINE + '";font-size:12px}'
          ':is(body:has(#login:not([hidden])),body:has(#home:not([hidden]))) #subtitle span{font-size:0}'
          ':is(body:has(#login:not([hidden])),body:has(#home:not([hidden]))) #subtitle span::after{content:"'
          + BS_TAGLINE + '";font-size:12px;white-space:normal}'
          '@media (max-width:520px){#subtitle span::after{content:none!important}#subtitle{display:none}'
          '#title.brand-text::after{content:none}}'   # 390: в шапке — только название
          ':root{--brand:' + BS_GRAD[0] + '!important}'                  # название — цвет Botsmith, не градиент панели
          '@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--brand:' + BS_GRAD[1] + '!important}}'
          ':root[data-theme=dark]{--brand:' + BS_GRAD[1] + '!important}</style>')


def botsmith_text(s: str) -> str:
    """Демо и вход гостя (владелец 25.11): название — «Ладэя» (не Botsmith), строка под ним — ``BS_TAGLINE``."""
    return s.replace(TAGLINE, BS_TAGLINE)


def botsmith_page(page: bytes) -> bytes:
    """Страница панели в бренде Botsmith: название во всех формах, знак, значок вкладки, превью ссылки, строка под
    логотипом. Скрипты страницы те же — меняются только тексты и стили."""
    s = botsmith_text(page.decode("utf-8"))
    s = s.replace("import(`/js/${name}.js`)", "import(`/js/${name}.js?brand=botsmith`)")   # части — тоже Botsmith
    s = s.replace(TAGLINE, BS_TAGLINE).replace('href="/favicon.svg"', 'href="/brand/botsmith-icon.svg"')
    s = re.sub(r'<meta property="og:image[^>]*>', "", s)            # превью — прежний знак; своего у демо пока нет
    return s.replace("</head>", BS_CSS + "</head>", 1).encode("utf-8")


def head_tags() -> str:
    """Превью ссылки (Telegram, iMessage, WhatsApp), цвет панели браузера по теме и экраны запуска iOS.
    ``__ORIGIN__`` сервер заменяет на адрес панели из запроса (превью требует полный адрес картинки)."""
    og = (f'<meta name="description" content="{TAGLINE}"><meta property="og:type" content="website">'
          f'<meta property="og:site_name" content="{DEFAULT}"><meta property="og:title" content="{DEFAULT}">'
          f'<meta property="og:description" content="{TAGLINE}"><meta property="og:url" content="__ORIGIN__/">'
          '<meta property="og:image" content="__ORIGIN__/og.png"><meta property="og:image:width" content="1200">'
          '<meta property="og:image:height" content="630"><meta name="twitter:card" content="summary_large_image">'
          '<meta name="twitter:image" content="__ORIGIN__/og.png">'
          '<meta name="theme-color" content="#FFFFFF" media="(prefers-color-scheme: light)">'
          '<meta name="theme-color" content="#111214" media="(prefers-color-scheme: dark)">')
    splash = "".join(
        f'<link rel="apple-touch-startup-image" href="/splash-{w}x{h}-{t}.png" media="(device-width: {w}px) and '
        f'(device-height: {h}px) and (-webkit-device-pixel-ratio: {r}) and (orientation: portrait) and '
        f'(prefers-color-scheme: {t})">' for w, h, r in IPHONES for t in ("light", "dark"))
    return og + splash


FOCUS_START = "/?focus"                 # фокус-ссылка на экране «Домой»: открывается снова фокус, а не вход в пульт


def manifest(name: str = NAME_RU, focus: bool = False) -> dict:
    """Манифест веб-приложения: экран «Домой» и уведомления на iPhone (iOS 16.4+ — только у такого приложения).

    ``focus`` (владелец 22.11: «фокус-ссылку на экран Домой — ошибка»): значок открывает ``/?focus`` — устройство
    узнаётся по cookie фокуса (iOS 17.2+ копирует cookie в приложение с экрана «Домой»), без входа в пульт.
    Токена в манифесте нет. «Поделиться» (share_target) фокусу не положено — его нет."""
    if focus:
        m = manifest(name)
        m.pop("share_target", None)
        return {**m, "id": FOCUS_START, "start_url": FOCUS_START}
    return {"name": name, "short_name": name, "start_url": "/", "scope": "/", "display": "standalone",
            "background_color": "#FFFFFF", "theme_color": "#FFFFFF", "lang": "ru",
            "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                      {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                      {"src": "/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
                      {"src": "/apple-touch-icon.png", "sizes": "180x180", "type": "image/png"},
                      {"src": "/favicon.svg", "sizes": "any", "type": "image/svg+xml"}],
            # «Поделиться» на Android (Chrome, установленное приложение; share.py): фото, ссылка, файл → POST /share.
            # iPhone (Safari) share_target не поддерживает — там «Быстрая команда» и /api/share.
            "share_target": {"action": "/share", "method": "POST", "enctype": "multipart/form-data",
                             "params": {"title": "title", "text": "text", "url": "url",
                                        "files": [{"name": "files", "accept": ["image/*", "video/*", "audio/*",
                                                                               "application/pdf", "text/*", "*/*"]}]}}}
