"""Название продукта, которое видит человек (владелец 25.11: «Ладея» по-русски, «Ladeya» по-английски, бренд —
«Ладея by Botsmith»; прежнее «Гаврила» / «Gavrila» снято). Здесь — единственное место: сервер подставляет его в
страницу (``<meta name="application-name">``, ``<title>``), манифест для экрана «Домой», письма, уведомления и сообщения
бота. Падежи — ``FORMS``. Код, пакет, пути, службы и адреса остаются ``gas-pult``/«пульт» (docs/BRAND.md).
Знак (``web/brand/``) — прежний, пока штаб не сделает новый; в демо и у гостя — только текст «Ладея» и «by Botsmith»."""

import re

APP_NAME_EN = "Ladeya"             # латиницей: английский интерфейс, адрес, логотип
APP_NAME_RU = "Ладея"              # русский интерфейс (в русских строках — без латиницы, humanize.LATIN_OK)
NAME, NAME_RU = APP_NAME_EN, APP_NAME_RU   # прежние имена констант — их читает код
DEFAULT = APP_NAME_RU              # так записано в web/index.html — сервер меняет его на NAME_RU, если они разные
BY = "by Botsmith"                 # строка бренда: «Ладея by Botsmith», «Ladeya by Botsmith»
FORMS = {"им": "Ладея", "род": "Ладеи", "дат": "Ладее", "вин": "Ладею", "твор": "Ладеей", "пр": "Ладее"}
OLD = ("Гаврилой", "Гаврилы", "Гавриле", "Гаврилу", "Гаврила", "Gavrila")   # прежнее имя — для теста


FILES_DIR = "web/brand/"   # знак и значки: gavrila-mark.svg (currentColor), -small (≤ 24 px), png — экран «Домой»
MARK = FILES_DIR + "gavrila-mark.svg"
LOCKUP = FILES_DIR + "gavrila-lockup.svg"
# адрес → (файл в web/brand/, тип): прежние адреса значков (GAS-20) сохранены, браузеры и iPhone их уже знают
ICONS = {"/brand/gavrila-mark.svg": ("gavrila-mark.svg", "image/svg+xml"),   # знак в панели — CSS mask
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
# Вариант страницы — только на /?demo и /?brand=botsmith: «Ладея» + «by Botsmith», без знака, своя строка под ним.
BS_NAME = "Botsmith"
BS_TAGLINE = "Личный ИИ-помощник и цифровой сотрудник"          # framewatcher 25.11, для М.Видео
BS_GRAD = ("linear-gradient(90deg,#2f5a09,#4a7f12)", "linear-gradient(90deg,#8bc34a,#9ccc65)")   # светлая, тёмная
ICONS["/brand/botsmith-icon.svg"] = ("botsmith-icon.svg", "image/svg+xml")
BS_CSS = ('<style id="bsBrand">.gmark{display:none!important}'            # знак пока текстовый (25.11)
          '.brand-text::after{content:" ' + BY + '";font-size:12px;font-weight:500;letter-spacing:0;'
          '-webkit-text-fill-color:var(--text-secondary);color:var(--text-secondary);margin-left:6px}'
          '.nav-h h2{flex:none;font-size:calc(17px * var(--fz, 1))}'
          '.nmark{width:22px;height:22px}.tmark{width:24px;height:24px}.lmark{width:44px;height:44px}'
          '#brandSub{font-size:0}#brandSub::after{content:"' + BS_TAGLINE + '";font-size:12px}'
          ':is(body:has(#login:not([hidden])),body:has(#home:not([hidden]))) #subtitle span{font-size:0}'
          ':is(body:has(#login:not([hidden])),body:has(#home:not([hidden]))) #subtitle span::after{content:"'
          + BS_TAGLINE + '";font-size:12px;white-space:normal}'
          ':root{--brand:' + BS_GRAD[0] + '!important}'                  # название — цвет Botsmith, не градиент панели
          '@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--brand:' + BS_GRAD[1] + '!important}}'
          ':root[data-theme=dark]{--brand:' + BS_GRAD[1] + '!important}</style>')


def botsmith_text(s: str) -> str:
    """Демо и вход гостя (владелец 25.11): название — «Ладея» (не Botsmith), строка под ним — ``BS_TAGLINE``."""
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
