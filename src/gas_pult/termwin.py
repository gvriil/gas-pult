"""Команде нужен ввод — окно терминала панели вместо «▶️ Выполнить» (задача 47).

«▶️ Выполнить» запускает команду без терминала: stdin закрыт, ``sudo`` — с ``-n``. Команда, которая спрашивает пароль
(мастер-пароль KeePassXC, sudo, ssh, passwd, ``read -s`` …), там упадёт или зависнет. Поэтому:

- ``needs_input(cmd)`` — распознаватель: ``keepassxc-cli`` (в том числе через ``sudo``/``env``/полный путь),
  ``sudo`` без ``-n`` (кроме разрешённых без пароля — ``sudo_ok``), ``ssh``/``scp``/``ssh-add``, ``passwd``, ``su``,
  ``gpg``, ``read -s``/``read -p`` и явные просьбы ввести пароль в тексте команды;
- такую команду пульт не выполняет вслепую, а открывает окно tmux ``gp-term`` в папке сессии и запускает её там;
  пароль вводят в этом окне — в панели в браузере (поле ввода уходит прямо в окно через буфер tmux, который сразу
  удаляется; в аргументы процессов не попадает) или в терминале (Termius). В Telegram (бот, Mini App) пароль не
  вводится.

Секреты на сервере — KeePassXC и файлы 0600 в ``~/.config/<сервис>/``; пульт их не хранит и не читает.
"""

from __future__ import annotations

import os
import re
import secrets
import shlex
from pathlib import Path

WINDOW = "gp-term"
# программы, которые спрашивают пароль или подтверждение с клавиатуры
ASKS = {"keepassxc-cli", "keepassxc.cli", "passwd", "su", "ssh", "ssh-add", "ssh-copy-id", "ssh-keygen", "scp", "sftp",
        "gpg", "gpg2", "pass", "kinit", "htpasswd"}
# обёртки: настоящая программа — дальше (sudo -u x …, env A=1 …, timeout 5 …)
WRAPS = {"sudo", "doas", "env", "command", "builtin", "exec", "nohup", "time", "nice", "ionice", "stdbuf", "timeout",
         "xargs", "then", "do", "else", "if", "while", "until", "!"}
OPT_ARG = {"sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U", "-T"}, "doas": {"-u", "-C"},
           "env": {"-u", "-C", "-S"}, "timeout": {"-s", "-k"}, "nice": {"-n"}, "ionice": {"-c", "-n", "-p"},
           "xargs": {"-I", "-n", "-P", "-d", "-L", "-s", "-E", "-a"}}
SEG = re.compile(r"\|\||&&|\$\(|[;|&\n(`{]")
ASSIGN = re.compile(r"^[A-Za-z_]\w*=")
KEEPASS = re.compile(r"(?<![\w.-])keepassxc[-.]cli\b")
PROMPT = re.compile(r"(?:введите|ввести|вводите|спросит|запросит|попросит|запрос(?:ит)?)\s+(?:\S+\s+){0,2}?"
                    r"(?:мастер-)?парол|enter\s+(?:the\s+|your\s+)?(?:master\s+)?(?:password|passphrase|pin)\b"
                    r"|\b(?:password|passphrase|пароль)\s*:\s*['\"]", re.I)
KEYS = {"C-c", "C-d", "Enter"}


def segments(cmd: str) -> list[tuple[str, list[str], str]]:
    """Простые команды строки: (программа, аргументы, sudo-часть). sudo-часть — текст от ``sudo``/``doas`` до конца
    простой команды, если программа запущена через них, иначе пусто. Без полного разбора оболочки — достаточно,
    чтобы найти программу за ``sudo``/``env``/полным путём."""
    out = []
    for seg in SEG.split(str(cmd or "")):
        toks, i, sudo = seg.split(), 0, ""
        while i < len(toks) and ASSIGN.match(toks[i]):
            i += 1
        while i < len(toks):
            name = os.path.basename(toks[i])
            if name not in WRAPS:
                break
            if name in ("sudo", "doas") and not sudo:
                sudo = " ".join(toks[i:])
            i += 1
            while i < len(toks) and (toks[i].startswith("-") or (name == "env" and ASSIGN.match(toks[i]))):
                i += 2 if toks[i] in OPT_ARG.get(name, ()) else 1
            if name == "timeout" and i < len(toks) and toks[i][:1].isdigit():
                i += 1                                         # timeout 5 prog — длительность
        if i < len(toks):
            out.append((os.path.basename(toks[i]).strip("'\""), toks[i + 1:], sudo))
        elif sudo:
            out.append(("", [], sudo))                         # «sudo -v», «sudo -s» — тоже спросит пароль
    return out


def sudo_asks(text: str) -> bool:
    """``sudo``/``doas`` без ``-n`` (``--non-interactive``) — спросит пароль."""
    toks = text.split()
    if not toks or os.path.basename(toks[0]) not in ("sudo", "doas"):
        return False
    name, i = os.path.basename(toks[0]), 1
    while i < len(toks) and toks[i].startswith("-"):
        t = toks[i]
        if t in ("-n", "--non-interactive") or (not t.startswith("--") and t[1:].isalpha() and "n" in t[1:]):
            return False
        i += 2 if t in OPT_ARG[name] else 1
    return True


def needs_input(cmd: str, sudo_ok=None) -> bool:
    """Команде нужен ввод с клавиатуры (пароль) — выполнять её только в окне терминала.

    ``sudo_ok(text)`` — sudo этой команды разрешён без пароля (``sudo_allow`` в конфиге): тогда пульт сам добавит
    ``-n``, и ввод не нужен."""
    cmd = str(cmd or "")
    if KEEPASS.search(cmd) or PROMPT.search(cmd):
        return True
    for prog, args, sudo in segments(cmd):
        if prog in ASKS:
            return True
        if prog == "read" and any(re.match(r"^-\w*[sp]", a) for a in args):
            return True
        if sudo and sudo_asks(sudo) and not (sudo_ok and sudo_ok(sudo)):
            return True
    return False


# ---------- окно терминала: открыть, показать, ввести, закрыть ----------
def _ours(tmux, wid: str) -> dict:
    w = tmux.window(wid)
    if not w or w.get("name") != WINDOW:
        raise LookupError("окна терминала уже нет — откройте команду в терминале ещё раз")
    return w


def open_window(tmux, cmd: str, cwd: str | None) -> str:
    """Новое окно ``gp-term`` в папке сессии: команда запускается в нём, после неё — код выхода и «Enter — закрыть».
    Возвращает id окна."""
    if not str(cmd or "").strip():
        raise ValueError("пустая команда")
    if hasattr(tmux, "ensure_session"):
        tmux.ensure_session()
    path = cwd if cwd and os.path.isdir(cwd) else str(Path.home())
    script = (f"{cmd}\nrc=$?; printf '\\n— готово, код %s. Enter — закрыть окно.\\n' \"$rc\"; read -r _")
    out = tmux.run("new-window", "-P", "-F", "#{window_id}", "-t", f"{tmux.session}:", "-n", WINDOW, "-c", path,
                   "bash -l -c " + shlex.quote(script))
    if not out.strip():
        raise RuntimeError("tmux не открыл окно терминала")
    return out.split()[0]


def screen(tmux, wid: str, n: int = 60) -> dict:
    """Что сейчас в окне терминала; окна уже нет — ``alive: false``."""
    w = tmux.window(wid)
    if not w or w.get("name") != WINDOW:
        return {"lines": [], "alive": False}
    return {"lines": tmux.screen(wid, n), "alive": True}


def type_line(tmux, wid: str, text: str):
    """Строку (пароль) — в окно ``gp-term`` (и только в него) через буфер tmux, который сразу удаляется, и Enter.
    Нигде не сохраняется и не попадает в аргументы процессов."""
    _ours(tmux, wid)
    if "\n" in text or "\r" in text:
        raise ValueError("одной строкой")
    if text:
        paste(tmux, wid, text)
    tmux.run("send-keys", "-t", wid, "Enter")


def paste(tmux, wid: str, text: str, bracket: bool = False):
    """Текст — в окно через именованный буфер tmux: в буфер — из stdin (аргументы процессов видно в /proc), вставка
    с ``-d`` удаляет буфер сразу, ``delete-buffer`` — на случай ошибки. ``bracket`` — вставка в скобках (``-p``):
    многострочный текст не выполнится построчно. Окно пространства — через его сервер tmux (``resolve``)."""
    tm, raw = resolve(tmux, wid)
    buf = "gp-term-" + secrets.token_hex(6)
    try:
        tm.run("load-buffer", "-b", buf, "-", input=text)
        tm.run("paste-buffer", "-d", *(("-p",) if bracket else ()), "-b", buf, "-t", raw)
    finally:
        try:
            tm.run("delete-buffer", "-b", buf)
        except Exception:                              # уже удалён paste-buffer -d — так и должно быть
            pass


def key(tmux, wid: str, k: str):
    if k not in KEYS:
        raise ValueError("такой клавиши нет")
    _ours(tmux, wid)
    tmux.run("send-keys", "-t", wid, k)


def close(tmux, wid: str):
    _ours(tmux, wid)
    tmux.run("kill-window", "-t", wid)


# ---------- живой терминал в панели (задача 50): клавиши, вся история, поиск ----------
# Окно сессии или gp-term: ввод текста и клавиш прямо в окно и история tmux целиком (с подгрузкой страницами).
# Кто может — решает панель (webapp.py: режим разработчика, окна пространств и gp-term — только владельцу).
# Ввод не пишется ни в какие логи; вывод истории — через маскировку секретов.
TTY_KEYS = {"Up", "Down", "Left", "Right", "Escape", "Tab", "BTab", "Enter", "BSpace", "DC", "Home", "End",
            "PPage", "NPage", "Space", "C-c", "C-d", "C-z", "C-l", "C-r", "C-a", "C-e", "C-u", "C-k", "C-w", "C-p",
            "C-n", "C-o", "C-t", "C-b", "C-f", "C-g", "C-y", "M-Enter", "S-Tab"}
OWNER_KEYS = {"C-z"}            # Ctrl+Z уводит Claude в фон, и окно становится командной строкой — только владельцу
PAGE = 500                      # строк окна за один запрос «выше»
MAX_ROWS = 20_000               # глубже — не отдаём: последние 20 тысяч строк истории окна
LINE_MAX = 2000                 # длинная строка обрезается (склеенные -J переносы)
TEXT_MAX = 8000                 # за один ввод
CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")   # управляющие знаки из текста — не вводим (кроме \t и \n)
INFO = "#{history_size}\t#{history_limit}\t#{pane_height}\t#{pane_start_time}\t#{pane_dead}\t#{alternate_on}"


def resolve(tmux, wid: str):
    """(tmux, номер окна в нём): окно пространства ``t:<slug>:@N`` — его сервер tmux и ``@N``
    (``spaces.Routed``), иначе — как есть."""
    target = getattr(tmux, "target", None)
    t = target(wid) if callable(target) else tmux
    own = getattr(t, "own", None)
    if callable(own) and hasattr(t, "tm"):
        return t.tm, own(wid)
    return t, wid


def mask(text: str) -> str:
    """Секреты в выводе — как в «Выполнить» (``commands.mask``) и в сессиях (``secrets_guard.redact``)."""
    from gas_pult import commands, secrets_guard
    return commands.mask(secrets_guard.redact(text)[0])


def tty_type(tmux, wid: str, text: str):
    """Текст — в окно как есть (без Enter): через буфер tmux, не в аргументах. Многострочный — вставкой в скобках."""
    text = CTRL.sub("", str(text or "").replace("\r\n", "\n").replace("\r", "\n"))
    if not text:
        raise ValueError("пустой ввод")
    if len(text) > TEXT_MAX:
        raise ValueError(f"за один раз — до {TEXT_MAX} знаков")
    paste(tmux, wid, text, bracket="\n" in text)


def tty_key(tmux, wid: str, k: str, owner: bool = True):
    """Клавиша — только из белого списка имён tmux (``TTY_KEYS``); Ctrl+Z — только владельцу."""
    if k not in TTY_KEYS or (k in OWNER_KEYS and not owner):
        raise ValueError("такой клавиши нет")
    tm, raw = resolve(tmux, wid)
    tm.run("send-keys", "-t", raw, k)


def _num(x, default=0) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _capture(tm, raw: str, a: int, b: int) -> list[str]:
    """Строки окна с ``y = a`` по ``y = b`` включительно: переносы по ширине склеены, секреты замаскированы."""
    out = tm.run("capture-pane", "-p", "-J", "-S", str(a), "-E", str(b), "-t", raw)
    lines = [x.rstrip()[:LINE_MAX] for x in mask(out).split("\n")]
    if out.endswith("\n") and lines and lines[-1] == "":
        lines.pop()
    return lines


def history(tmux, wid: str, start=None, end=None, everything: bool = False) -> dict:
    """История окна в строках tmux: строка ``r`` (от 0 — самой старой в истории) — это ``y = r - history_size``.

    Без параметров — последние ``PAGE`` строк (с видимым экраном); ``start`` — от этой строки до конца (живой хвост
    после прокрутки вверх); ``end`` — страница выше этой строки (``everything`` — всё выше неё, для поиска);
    только ``everything`` — вся доступная история. Глубже ``MAX_ROWS`` от конца не отдаём.

    ``cut`` — сколько первых строк ответа уже ушло в историю (выше экрана) и больше не меняется; остальные — экран,
    его панель перерисовывает целиком при каждом опросе."""
    tm, raw = resolve(tmux, wid)
    info = tm.run("display-message", "-p", "-t", raw, INFO).strip().split("\t")
    if len(info) < 3 or not info[0].isdigit():
        return {"alive": False, "lines": [], "start": 0, "end": 0, "total": 0}
    hs, limit, height = _num(info[0]), _num(info[1]), _num(info[2])
    total = hs + height
    floor = max(0, total - MAX_ROWS)
    if end is not None:
        hi = min(max(_num(end), floor), total)
        lo = floor if everything else max(floor, hi - PAGE)
    elif everything:
        lo, hi = floor, total
    elif start is not None:
        lo, hi = min(max(_num(start), floor), total), total
    else:
        lo, hi = max(floor, total - PAGE), total
    old = _capture(tm, raw, lo - hs, min(hi, hs) - 1 - hs) if lo < min(hi, hs) else []
    scr = _capture(tm, raw, max(lo, hs) - hs, hi - 1 - hs) if max(lo, hs) < hi else []
    if hi == total:                                  # пустой низ экрана под курсором — не нужен
        while scr and not scr[-1]:
            scr.pop()
    return {"alive": True, "lines": old + scr, "cut": len(old), "start": lo, "end": hi, "total": total,
            "floor": floor, "history": hs, "limit": limit, "height": height,
            "since": _num(info[3] if len(info) > 3 else 0), "dead": (info[4:5] or [""])[0] == "1",
            "alt": (info[5:6] or [""])[0] == "1"}
