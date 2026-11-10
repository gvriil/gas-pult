"""«Нужен вход» на экране окна: что просит экран — ссылка, одноразовый код, куда вставить ответ.

Образцы — экраны Claude Code (``claude auth login`` и вход в MCP-сервис из ``/mcp``), ``gh auth login`` (код
устройства и github.com/login/device) и другие входы «по коду устройства» (откройте адрес, введите XXXX-XXXX).
Ссылка, перенесённая по ширине окна, собирается из продолжения следующими строками.

Показываем только при паре «ссылка + слово входа» (login, sign in, device, authorize, oauth, one-time code, paste
code): просто ссылка в ответе Claude шторку не вызывает. Смотрим только низ экрана — запрос входа всегда там.
Только стандартная библиотека.
"""

from __future__ import annotations

import re

TAIL_LINES = 30
URL = re.compile(r"https://[^\s<>\"'`]+")
URL_TAIL = re.compile(r"^\s*([A-Za-z0-9%&=_.~:/?#+\-]+)\s*$")
WORD = re.compile(r"\b(log\s?-?in|sign\s?-?in|device|authori[sz]e|authori[sz]ation|oauth|one-time code|user code"
                  r"|verification code|enter the code|paste\s+(the\s+)?(authorization\s+)?code|code here)\b", re.I)
URL_WORD = re.compile(r"login|signin|sign-in|device|authori[sz]e|oauth", re.I)
# Одноразовый код, который человек вводит на странице: «XXXX-XXXX» (GitHub, Microsoft и т. п.)
ONE_TIME = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b")
ONE_TIME_CTX = re.compile(r"one-time code|user code|enter the code|verification code|device code|код", re.I)
# Экран ждёт ввода в окно: код со страницы (Claude Code) или адрес страницы после входа (MCP, «URL >»)
ASKS_CODE = re.compile(r"paste\s+(the\s+)?(authorization\s+)?code|code\s+here|enter\s+(the\s+)?authorization\s+code",
                       re.I)
ASKS_URL = re.compile(r"paste the URL|URL\s*>", re.I)
AUTH_WITH = re.compile(r"Authenticating with (.+?)[….]*\s*$")
CLAUDE_URL = re.compile(r"https://(claude\.ai|claude\.com|console\.anthropic\.com)/\S*oauth", re.I)
GH_DEVICE = re.compile(r"https://github\.com/login/device", re.I)


def _url(lines: list[str]) -> str:
    """Ссылка входа — ближайшая к низу экрана (с продолжением следующими строками); нет такой — последняя любая."""
    found: list[str] = []
    for i, line in enumerate(lines):
        for m in URL.finditer(line):
            url, prev = m.group(0), line
            if prev.rstrip().endswith(url):     # ссылка до конца строки — хвост мог уйти на следующие
                for nxt in lines[i + 1:]:
                    if not (t := URL_TAIL.match(nxt)) or WORD.search(nxt) or len(prev.rstrip()) < 40:
                        break
                    url, prev = url + t.group(1), nxt
            found.append(url.rstrip(".,)»\"'"))
    return next((u for u in reversed(found) if URL_WORD.search(u)), found[-1] if found else "")


def detect(lines: list[str]) -> dict | None:
    """Экран окна → ``{kind, service, url, code, wants}`` или None.

    kind: ``claude`` (вход в Claude Code), ``mcp`` (вход в MCP-сервис из /mcp), ``gh`` (GitHub CLI), ``device``
    (вход по коду устройства), ``url`` (просто ссылка входа). code — одноразовый код для страницы (его человек
    копирует), wants — что окно ждёт обратно: ``code`` (код со страницы), ``url`` (адрес после входа) или ""."""
    lines = [str(x) for x in (lines or [])][-TAIL_LINES:]
    url = _url(lines)
    if not url:
        return None
    text = "\n".join(lines)
    if not (WORD.search(text) or URL_WORD.search(url)):
        return None
    code = ""
    for line in lines:
        if (m := ONE_TIME.search(line)) and ONE_TIME_CTX.search(line):
            code = m.group(1)
    wants = "code" if ASKS_CODE.search(text) else "url" if ASKS_URL.search(text) else ""
    service = next((m.group(1).strip() for line in lines if (m := AUTH_WITH.search(line))), "")
    if GH_DEVICE.match(url) or (re.search(r"\bgh auth\b|GitHub CLI|github\.com", text) and code):
        kind, service = "gh", "GitHub"
    elif CLAUDE_URL.match(url):
        kind, service = "claude", "Claude"
    elif service or (re.search(r"/authorize|oauth", url, re.I) and wants == "url"):
        kind, service = "mcp", service or "сервис"
    elif code:
        kind = "device"
    else:
        kind = "url"
    if not service:
        service = re.sub(r"^www\.", "", url.split("/")[2]) if url.count("/") >= 2 else "сервис"
    return {"kind": kind, "service": service[:80], "url": url[:2048], "code": code, "wants": wants}


CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")
CODE_MAX = 512


def clean_code(code) -> str:
    """Код или адрес для окна: одна строка до 512 знаков, без управляющих символов; пробелы по краям — прочь."""
    s = str(code if code is not None else "").strip()
    if not s:
        raise ValueError("пустой код — скопируйте его со страницы входа")
    if len(s) > CODE_MAX:
        raise ValueError(f"код длиннее {CODE_MAX} знаков — это не код входа")
    if CTRL.search(s):
        raise ValueError("код — одна строка без переводов строки и управляющих символов")
    return s
