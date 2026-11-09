"""Окна tmux: список, экран, вставка текста, новые окна с Claude Code."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from gas_pult.models import profile_of

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def live_sid(pid: int | str, proc: str = "/proc") -> str:
    """id сессии, которую ведёт работающий процесс Claude Code: он сам пишет ``<папка Claude>/sessions/<pid>.json``
    с ``sessionId`` (и меняет его после ``/clear`` и ``/resume``). Папка Claude — из окружения процесса
    (``CLAUDE_CONFIG_DIR``, иначе ``$HOME/.claude``). Это точнее метки окна и «последнего журнала папки»: рядом в той
    же папке пишут другие окна и плановые запуски — их журнал оказывался «свежее», и окно показывало чужую переписку.
    Не прочитать (чужой пользователь, процесс завершился, старый Claude Code) — ""."""
    try:
        raw = Path(f"{proc}/{int(pid)}/environ").read_bytes().decode(errors="replace")
        env = dict(x.split("=", 1) for x in raw.split("\0") if "=" in x)
    except (OSError, ValueError):
        return ""
    base = env.get("CLAUDE_CONFIG_DIR") or (env.get("HOME", "") and os.path.join(env["HOME"], ".claude"))
    if not base:
        return ""
    try:
        sid = str(json.loads((Path(base) / "sessions" / f"{int(pid)}.json").read_text()).get("sessionId") or "")
    except (OSError, ValueError, AttributeError):
        return ""
    return sid if UUID.match(sid) else ""


def is_claude(argv: list[str]) -> bool:
    """claude (нативный установщик), node …/@anthropic-ai/claude-code/cli.js (npm), bash /path/claude (обёртка)."""
    return any(os.path.basename(a) == "claude" or "/@anthropic-ai/claude-code/" in a for a in argv[:2])


SHELLS = {"bash", "zsh", "sh", "fish", "dash", "ksh"}


ANSI = re.compile(r"\x1b\[[0-9;]*m")
HINT = re.compile(r"❯[\s\u00a0]*\x1b\[2m(.*?)(?:\x1b\[|$)")


def prompt_hint(lines: list[str]) -> str:
    """Подсказка Claude Code в строке ввода: бледный текст (ESC[2m) сразу после «❯» в последней строке ввода.
    Общие заглушки вида «Try "…"» — не подсказка."""
    for raw in reversed(lines[-20:]):
        if not ANSI.sub("", raw).lstrip().startswith("❯"):
            continue
        m = HINT.search(raw)
        text = " ".join(m.group(1).split()) if m else ""
        return "" if not text or text.startswith('Try "') else text[:300]
    return ""


BOX = re.compile(r"^[\s─━═╭╮╰╯│┃]*$")              # рамка поля ввода Claude Code (линии без текста)


def prompt_draft(lines: list[str]) -> str:
    """Неотправленный текст в поле ввода Claude Code: обычный (не бледный) текст после «❯» в последнем поле ввода и
    его продолжение до нижней рамки. Бледный текст сразу после «❯» — подсказка или заглушка, не черновик."""
    for i in range(len(lines) - 1, max(-1, len(lines) - 40), -1):
        raw = lines[i]
        plain = ANSI.sub("", raw)
        if not plain.lstrip().lstrip("│┃ ").startswith("❯"):
            continue
        after = raw.split("❯", 1)[1].lstrip(" \u00a0")
        if after.startswith("\x1b[2m") or not ANSI.sub("", after).strip():
            return ""
        out = [ANSI.sub("", after).rstrip(" │┃")]
        for nxt in lines[i + 1:]:
            t = ANSI.sub("", nxt)
            if BOX.match(t) or not t.strip():
                break
            out.append(t.strip(" │┃"))
        return "\n".join(x.rstrip() for x in out).strip()[:4000]
    return ""


def window_name(name: str) -> str:
    """Имя сессии (окна tmux): 1–40 знаков, без «:» и «.» — в tmux это разделители цели (сессия:окно.панель)."""
    name = " ".join(str(name).split())
    if not name or len(name) > 40 or re.search(r"[:.]", name):
        raise ValueError("имя — от 1 до 40 знаков, без «:» и «.»")
    return name


class Tmux:
    def __init__(self, session: str, socket: str = "", user: str = "", home: str = "", tmux: str = "tmux"):
        """``socket`` (или ``GAS_PULT_TMUX_SOCKET``) — свой сервер tmux по пути сокета (``tmux -S``): тесты и проверки
        работают только с ним и не видят боевой сервер. Пусто — сервер tmux по умолчанию.

        ``user`` — окна пространства (``tenants.py``): каждая команда tmux идёт как ``sudo -n -u <user> <tmux> -S
        <socket>``, ``home`` — папка, где открывается сессия, оболочка — /bin/bash. Без ``user`` всё как раньше."""
        self.session = session
        self.socket = socket or os.environ.get("GAS_PULT_TMUX_SOCKET", "")
        self.user, self.home = user, home
        self.tmux = ["tmux", "-S", self.socket] if self.socket else ["tmux"]
        if user:
            if not socket:
                raise ValueError("у пространства должен быть свой сокет tmux")
            self.tmux = ["sudo", "-n", "-u", user, tmux, "-S", socket]

    def run(self, *args: str, input: str | None = None) -> str:
        return subprocess.run([*self.tmux, *args], capture_output=True, text=True, input=input).stdout

    def windows(self) -> list[dict]:
        out = self.run("list-windows", "-t", self.session, "-F", "#{window_id}\t#{window_index}\t#{window_name}\t"
                       "#{pane_current_command}\t#{pane_current_path}\t#{pane_tty}\t#{@gas_pult}\t#{@gas_pult_by}\t"
                       "#{@gas_pult_sid}")
        # sid — id сессии Claude Code (``--session-id``): у окна свой журнал, а не «последний в папке»
        ws = [dict(zip(("id", "idx", "name", "cmd", "path", "tty", "mark", "by", "sid"), line.split("\t"),
                       strict=False)) for line in out.splitlines()]
        for w in ws:  # Claude может быть запущен через bash -c — смотрим все процессы терминала окна
            # -ww: без него ps режет строку до 80 знаков, и длинный путь к Claude (npm: node …/cli.js) не узнаётся
            ps = subprocess.run(["ps", "-ww", "-t", w.get("tty", "").removeprefix("/dev/"), "-o", "pid=,args="],
                                capture_output=True, text=True)
            procs = [p for p in (line.split() for line in ps.stdout.splitlines() if line.strip()) if len(p) > 1]
            claude = [p[1:] for p in procs if is_claude(p[1:])]
            # журнал окна — по самому процессу Claude (sessions/<pid>.json), а не по метке или «последнему в папке»
            live = next((sid for p in procs if is_claude(p[1:]) and (sid := live_sid(p[0]))), "")
            if live:
                w["tag"], w["sid"], w["live"] = w.get("sid", ""), live, True
            if claude:
                w["cmd"] = "claude"
            w["profile"] = profile_of(claude[0]) if claude else ""   # у какого поставщика модели (models.py)
            w["channel"] = any("--channels" in p for p in claude)   # у окна свой Telegram — не дублируем
            # окно открыл пульт (метка — поставщик), а Claude в нём завершился и осталась оболочка — «остановлена»
            w["stopped"] = not claude and bool(w.get("mark")) and w["cmd"] in SHELLS
        return ws

    def draft(self, wid: str) -> str:
        """Неотправленный текст в поле ввода окна (``prompt_draft``); нет — пусто."""
        return prompt_draft(self.run("capture-pane", "-p", "-e", "-J", "-t", wid).splitlines())

    def hint(self, wid: str) -> str:
        """Что Claude Code предлагает написать следующим (бледный текст в строке ввода); нет — пусто."""
        return prompt_hint(self.run("capture-pane", "-p", "-e", "-J", "-t", wid).splitlines())

    def rename(self, wid: str, name: str) -> str:
        """Переименовать окно. Снимок claude-restore берёт имя из tmux — новое имя переживёт перезапуск."""
        name = window_name(name)
        r = subprocess.run([*self.tmux, "rename-window", "-t", wid, name], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "tmux rename-window не сработал")
        return name

    def window(self, wid: str) -> dict | None:
        return next((w for w in self.windows() if w["id"] == wid), None)

    def screen(self, wid: str, n: int = 25) -> list[str]:
        # -J склеивает строки, перенесённые по ширине окна (длинные ссылки, пути) — читаются целиком
        out = self.run("capture-pane", "-p", "-J", "-t", wid)
        return [line.rstrip() for line in out.splitlines() if line.strip()][-n:]

    def paste(self, wid: str, text: str):
        """Bracketed paste: многострочный текст не отправится раньше времени; Enter — отдельно."""
        self.run("load-buffer", "-b", "gas-pult", "-", input=text)
        self.run("paste-buffer", "-p", "-d", "-b", "gas-pult", "-t", wid)
        time.sleep(0.5)
        self.keys(wid, "Enter")

    def type(self, wid: str, text: str):
        self.run("send-keys", "-t", wid, "-l", text)

    def keys(self, wid: str, *keys: str):
        self.run("send-keys", "-t", wid, *keys)

    def kill(self, wid: str):
        self.run("kill-window", "-t", wid)

    def shell(self) -> str:
        """Оболочка после выхода Claude: у пространства — /bin/bash (у его пользователя входа нет), иначе $SHELL."""
        return "/bin/bash" if self.user else os.environ.get("SHELL", "/bin/bash")

    def ensure_session(self):
        if subprocess.run([*self.tmux, "has-session", "-t", self.session], capture_output=True).returncode == 0:
            return
        cmd = [*self.tmux, "new-session", "-d", "-s", self.session, "-c", self.home or os.path.expanduser("~")]
        if sys.platform == "linux" and shutil.which("systemd-run") and not self.socket:
            # сервер tmux — в своей группе systemd: иначе перезапуск службы пульта убьёт все окна
            cmd = ["systemd-run", "--user", "--scope", "--quiet", "--collect",
                   f"--unit=gas-pult-tmux-{int(time.time())}", *cmd]
        subprocess.run(cmd, check=True)

    def new_window(self, name: str, path: str, command: str, mark: str = "claude", by: str = "", sid: str = "") -> str:
        """Новое окно с командой (Claude); после её выхода остаётся шелл. Возвращает id окна.

        ``mark`` (поставщик модели) пишется в опцию окна ``@gas_pult``: по ней видно, что окно — сессия пульта, даже
        когда Claude в нём завершился (тогда сессия «остановлена», а не пропадает). ``by`` — Telegram ID человека,
        открывшего окно со своей папкой Claude Code (``@gas_pult_by``); пусто — окно владельца."""
        self.ensure_session()
        shell = self.shell()
        r = subprocess.run([*self.tmux, "new-window", "-P", "-F", "#{window_id}", "-t", f"{self.session}:",
                            "-n", name, "-c", path, f"{command}; exec {shlex.quote(shell)}"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "tmux new-window не сработал")
        wid = r.stdout.split()[0]
        self.run("set-option", "-w", "-t", wid, "@gas_pult", mark or "claude")
        if by:
            self.run("set-option", "-w", "-t", wid, "@gas_pult_by", str(by))
        if sid:
            self.set_sid(wid, sid)
        return wid

    def set_sid(self, wid: str, sid: str):
        """Метка окна ``@gas_pult_sid`` — id сессии Claude Code, чей журнал читать; пусто — снять (старый способ)."""
        if sid:
            self.run("set-option", "-w", "-t", wid, "@gas_pult_sid", sid)
        else:
            self.run("set-option", "-w", "-u", "-t", wid, "@gas_pult_sid")

    def respawn(self, wid: str, path: str, command: str, mark: str = "claude", sid: str | None = None):
        """Запустить Claude заново в том же окне (то же имя и id): оболочку — закрыть, команду — запустить."""
        shell = self.shell()
        r = subprocess.run([*self.tmux, "respawn-window", "-k", "-t", wid, "-c", path,
                            f"{command}; exec {shlex.quote(shell)}"], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "tmux respawn-window не сработал")
        self.run("set-option", "-w", "-t", wid, "@gas_pult", mark or "claude")
        if sid is not None:                              # None — метку окна не трогаем
            self.set_sid(wid, sid)
