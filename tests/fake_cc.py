#!/usr/bin/env python3
"""Подставное поле ввода Claude Code для проверок доставки (тесты и e2e) — запускается в своём tmux, не в боевом.

Рисует то, что пульт видит в окне настоящего Claude Code: переписку, рамку ─, строку «❯ текст» (черновик —
в цвете 38;5;246, как в окне владельца 10.11), нижнюю рамку, три строки статуса и под ними панель фоновых агентов,
где выбранная строка помечена тем же «❯» (так Claude Code рисует выбранный пункт любого списка). Принимает вставку
в скобках (ESC[200~ … ESC[201~) и Enter.

Режим — первая строка файла ``FAKE_CC_CTL`` (читается на каждую клавишу, тест меняет его на ходу):
  normal      — Enter отправляет текст (строка «got: …» в переписке и в файле ``FAKE_CC_LOG``);
  panel       — фокус в панели агентов: Enter уходит туда, текст остаётся в поле ввода (потерянный Enter);
  busy        — идёт ход («esc to interrupt»): Enter ставит текст в очередь, поле пустеет;
  drop1       — первый Enter после вставки теряется (Claude Code ещё разбирает вставку), дальше — как normal;
  dim         — поле ввода не в фокусе и рисуется бледным (ESC[2m): Enter теряется, текст остаётся;
  return      — идёт ход: Enter ставит текст в очередь, через 2 с ход прерывается и Claude Code возвращает текст
                из очереди в поле ввода (дальше — normal);
  return-panel — то же, но после возврата фокус в панели агентов (дальше — panel): текст так и висит.
"""

import os
import re
import select
import sys
import termios
import time
import tty

CTL = os.environ.get("FAKE_CC_CTL", "")
LOG = os.environ.get("FAKE_CC_LOG", "")
W = 70
RULE = "\x1b[38;5;244m" + "─" * W + "\x1b[39m"


def set_mode(m: str):
    with open(CTL, "w") as f:
        f.write(m + "\n")


def mode() -> str:
    try:
        with open(CTL) as f:
            return (f.readline().strip() or "normal")
    except OSError:
        return "normal"


class Screen:
    def __init__(self):
        self.lines: list[str] = ["\x1b[1m✻ fake Claude Code\x1b[22m", ""]
        self.buf = ""
        self.dropped = False
        self.back: tuple[float, str, str] | None = None     # (когда, текст, режим после) — возврат из очереди

    def draw(self):
        m = mode()
        out = ["\x1b[H\x1b[2J"]
        out += [x + "\r\n" for x in self.lines[-8:]]
        if m in ("busy", "return", "return-panel"):
            out.append("\x1b[38;5;174m✶ Работает… (12s · esc to interrupt)\x1b[39m\r\n")
        out.append("\r\n" + RULE + "\r\n")
        if not self.buf:
            out.append("❯ \x1b[7m \x1b[27m\x1b[2mTry \"fix lint errors\"\x1b[22m\r\n")
        elif m == "dim":
            out.append("❯ \x1b[2m" + self.buf + "\x1b[22m\r\n")
        else:
            out.append("❯ \x1b[38;5;246m" + self.buf + "\x1b[39m\x1b[7m \x1b[27m\r\n")
        out.append(RULE + "\r\n")
        out.append("  \x1b[38;5;246m⏵⏵ accept edits on (shift+tab to cycle)\x1b[39m\r\n")
        out.append("  \x1b[38;5;246mgas-pult · main · Opus\x1b[39m\r\n")
        out.append("  \x1b[38;5;246m3 background tasks · ↓ to manage\x1b[39m\r\n")
        sel = "❯" if m == "panel" else " "
        out.append(f"{sel}● main\x1b[38;5;246m  ход\x1b[39m\r\n")
        out.append(" ◯ general-purpose\x1b[38;5;246m  Исследует доставку\x1b[39m")
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    def enter(self):
        m = mode()
        if not self.buf or m in ("panel", "dim"):
            return
        if m == "drop1" and not self.dropped:
            self.dropped = True
            return
        text, self.buf = self.buf, ""
        if m in ("return", "return-panel"):
            self.back = (time.time() + 2, text, "normal" if m == "return" else "panel")
        if m in ("busy", "return", "return-panel"):
            self.lines.append("\x1b[2m❯ " + text + " (в очереди)\x1b[22m")
            return
        self.lines += ["\x1b[48;5;237m❯ " + text + "\x1b[49m", "● got: " + text, ""]
        if LOG:
            with open(LOG, "a") as f:
                f.write(text.replace("\n", " ") + "\n")


def main():
    scr = Screen()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    sys.stdout.write("\x1b[?2004h")                 # просим вставку в скобках, как настоящий Claude Code
    try:
        scr.draw()
        pending = b""
        while True:
            if scr.back and time.time() >= scr.back[0]:          # ход прерван — текст из очереди снова в поле
                _, scr.buf, after = scr.back
                scr.back = None
                set_mode(after)
                scr.draw()
            if not select.select([fd], [], [], 0.2)[0]:
                continue
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            pending += chunk
            while pending:
                if pending.startswith(b"\x1b[200~"):
                    end = pending.find(b"\x1b[201~")
                    if end < 0:
                        break                       # вставка ещё не вся — дочитать
                    scr.buf += pending[6:end].decode(errors="replace").replace("\r", "\n")
                    pending = pending[end + 6:]
                elif pending[:1] in (b"\r", b"\n"):
                    pending = pending[1:]
                    scr.enter()
                elif pending[:1] == b"\x03":
                    return
                elif pending[:1] == b"\x1b":
                    pending = re.sub(rb"^\x1b(\[[0-9;]*[A-Za-z~]?)?", b"", pending, count=1)
                elif pending[:1] == b"\x7f":
                    pending, scr.buf = pending[1:], scr.buf[:-1]
                else:
                    n = 1
                    while n < len(pending) and pending[n:n + 1] not in (b"\r", b"\n", b"\x1b", b"\x03", b"\x7f"):
                        n += 1
                    scr.buf += pending[:n].decode(errors="replace")
                    pending = pending[n:]
            scr.draw()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


if __name__ == "__main__":
    main()
