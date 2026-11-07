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
        buf = "gp-term-" + secrets.token_hex(6)           # не в аргументах команды (их видно в /proc) — через stdin
        try:
            tmux.run("load-buffer", "-b", buf, "-", input=text)
            tmux.run("paste-buffer", "-d", "-b", buf, "-t", wid)  # -d: буфер удаляется сразу после вставки
        finally:
            try:
                tmux.run("delete-buffer", "-b", buf)
            except Exception:                              # уже удалён paste-buffer -d — так и должно быть
                pass
    tmux.run("send-keys", "-t", wid, "Enter")


def key(tmux, wid: str, k: str):
    if k not in KEYS:
        raise ValueError("такой клавиши нет")
    _ours(tmux, wid)
    tmux.run("send-keys", "-t", wid, k)


def close(tmux, wid: str):
    _ours(tmux, wid)
    tmux.run("kill-window", "-t", wid)
