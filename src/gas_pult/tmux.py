"""Окна tmux: список, экран, вставка текста, новые окна с Claude Code."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import time

from gas_pult.models import profile_of


def is_claude(argv: list[str]) -> bool:
    """claude (нативный установщик), node …/@anthropic-ai/claude-code/cli.js (npm), bash /path/claude (обёртка)."""
    return any(os.path.basename(a) == "claude" or "/@anthropic-ai/claude-code/" in a for a in argv[:2])


class Tmux:
    def __init__(self, session: str):
        self.session = session

    def run(self, *args: str, input: str | None = None) -> str:
        return subprocess.run(["tmux", *args], capture_output=True, text=True, input=input).stdout

    def windows(self) -> list[dict]:
        out = self.run("list-windows", "-t", self.session, "-F", "#{window_id}\t#{window_index}\t#{window_name}\t"
                       "#{pane_current_command}\t#{pane_current_path}\t#{pane_tty}")
        ws = [dict(zip(("id", "idx", "name", "cmd", "path", "tty"), line.split("\t"), strict=False))
              for line in out.splitlines()]
        for w in ws:  # Claude может быть запущен через bash -c — смотрим все процессы терминала окна
            ps = subprocess.run(["ps", "-t", w.get("tty", "").removeprefix("/dev/"), "-o", "args="],
                                capture_output=True, text=True)
            claude = [p for p in (line.split() for line in ps.stdout.splitlines() if line.strip()) if is_claude(p)]
            if claude:
                w["cmd"] = "claude"
            w["profile"] = profile_of(claude[0]) if claude else ""   # у какого поставщика модели (models.py)
            w["channel"] = any("--channels" in p for p in claude)   # у окна свой Telegram — не дублируем
        return ws

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

    def ensure_session(self):
        if subprocess.run(["tmux", "has-session", "-t", self.session], capture_output=True).returncode == 0:
            return
        cmd = ["tmux", "new-session", "-d", "-s", self.session, "-c", os.path.expanduser("~")]
        if sys.platform == "linux" and shutil.which("systemd-run"):
            # сервер tmux — в своей группе systemd: иначе перезапуск службы пульта убьёт все окна
            cmd = ["systemd-run", "--user", "--scope", "--quiet", "--collect",
                   f"--unit=gas-pult-tmux-{int(time.time())}", *cmd]
        subprocess.run(cmd, check=True)

    def new_window(self, name: str, path: str, command: str) -> str:
        """Новое окно с командой (Claude); после её выхода остаётся шелл. Возвращает id окна."""
        self.ensure_session()
        shell = os.environ.get("SHELL", "/bin/bash")
        r = subprocess.run(["tmux", "new-window", "-P", "-F", "#{window_id}", "-t", f"{self.session}:",
                            "-n", name, "-c", path, f"{command}; exec {shlex.quote(shell)}"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "tmux new-window не сработал")
        return r.stdout.split()[0]
