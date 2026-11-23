"""Буфер обмена «Браузера» вживую (владелец 23.11: «почини буфер обмена в браузере, чтобы работал»).

    python tests/e2e/desktop_clipboard_live.py [папка для снимков]

Свой стенд, живой стол не трогаем: свободный дисплей Xvnc (с 70) с теми же флагами буфера, что у рабочего стола
(-SendCutText=1 -AcceptCutText=1), на нём Chrome с полем textarea, websockify отдаёт панель и noVNC из системы.
Панель — демо, экран — настоящий noVNC (``deskShow({demo: false})``). Проверяем:
- Ctrl+V над экраном: текст из буфера устройства (кириллица и латиница) — ровно он в поле на столе; без разрешения
  на чтение буфера (событие paste);
- ⌘+V и ⌘+A, ⌘+C с Mac — как Ctrl на столе;
- копия на столе (Ctrl+A, Ctrl+C) — сразу в буфере устройства;
- телефон 390: кнопка «Вставить» внизу; браузер не дал прочитать буфер — поле «Буфер» и «Вставить на стол»;
  «Ctrl+C» из ряда клавиш — копия в «Буфер» и «Скопировать»; WebKit — где можно.
После себя стенд останавливается по своим PID (не по имени процесса).
"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "src" / "gas_pult" / "web"
NOVNC = Path("/usr/share/novnc")
CYR = "Привет, мир! Ёж 123 €"
LAT = "Hello, world! 123"
PAGE = ('<!doctype html><meta charset="utf-8"><title>clip-test</title>'
        '<textarea id="t" style="width:90vw;height:40vh;font-size:28px" autofocus></textarea>')
CHROMES = ("google-chrome", "chromium", "chromium-browser")


def chrome() -> str | None:
    return next((shutil.which(c) for c in CHROMES if shutil.which(c)), None)


def ready() -> str:
    """Пусто — стенд можно поднять; иначе — чего не хватает."""
    for b in ("Xvnc", "websockify"):
        if not shutil.which(b):
            return f"нет {b}"
    if not chrome():
        return "нет Chrome/Chromium"
    if not (NOVNC / "core" / "rfb.js").exists():
        return "нет noVNC в /usr/share/novnc"
    try:
        import playwright  # noqa: F401
    except ImportError:
        return "нет playwright"
    return ""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def free_display() -> int:
    for n in range(70, 100):
        if not Path(f"/tmp/.X11-unix/X{n}").exists() and not Path(f"/tmp/.X{n}-lock").exists():
            return n
    raise RuntimeError("нет свободного дисплея 70–99")


def wait_port(port: int, sec: float = 10) -> None:
    end = time.time() + sec
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), 0.3).close()
            return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"порт {port} не открылся")


class Stand:
    """Xvnc + Chrome + websockify; останавливаются только свои процессы (Popen) и только свой дисплей."""

    def __enter__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="desk-clip-"))
        self.procs: list[subprocess.Popen] = []
        web = self.tmp / "web"
        web.mkdir()
        for f in WEB.iterdir():
            (web / f.name).symlink_to(f)
        (web / "desktop").symlink_to(NOVNC)
        (self.tmp / "ta.html").write_text(PAGE, encoding="utf-8")
        self.disp, self.rfb, self.ws, self.cdp = free_display(), free_port(), free_port(), free_port()
        log = open(self.tmp / "log.txt", "w")
        run = lambda cmd, **kw: self.procs.append(subprocess.Popen(cmd, stdout=log, stderr=log, **kw))  # noqa: E731
        run(["Xvnc", f":{self.disp}", "-geometry", "1280x800", "-depth", "24", "-nolisten", "tcp", "-localhost",
             "-rfbport", str(self.rfb), "-SecurityTypes", "None", "-AlwaysShared", "-AcceptSetDesktopSize=1",
             "-SendCutText=1", "-AcceptCutText=1"])
        wait_port(self.rfb)
        run([chrome(), f"--user-data-dir={self.tmp / 'chrome'}", f"--remote-debugging-port={self.cdp}",
             "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--window-position=0,0",
             "--window-size=1280,800", (self.tmp / "ta.html").as_uri()], env={**os.environ, "DISPLAY": f":{self.disp}"})
        run(["websockify", "--web", str(web), f"127.0.0.1:{self.ws}", f"127.0.0.1:{self.rfb}"])
        wait_port(self.ws)
        wait_port(self.cdp, 20)
        return self

    def __exit__(self, *a):
        for p in reversed(self.procs):
            p.terminate()
        for p in reversed(self.procs):
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(5)
        shutil.rmtree(self.tmp, ignore_errors=True)


def run(st: Stand, shots: Path | None = None) -> list[str]:
    from playwright.sync_api import sync_playwright

    fails: list[str] = []
    errs: list[str] = []
    base = f"http://127.0.0.1:{st.ws}/index.html?demo"

    def check(name, got, want):
        if got != want:
            fails.append(f"{name}: ждали {want!r}, получили {got!r}")
        print(("ok  " if got == want else "FAIL") + f" {name}: {got!r}")

    with sync_playwright() as p:
        srv = p.chromium.connect_over_cdp(f"http://127.0.0.1:{st.cdp}")
        sp = next(pg for c in srv.contexts for pg in c.pages if "ta.html" in pg.url)
        sval = lambda: sp.evaluate("document.getElementById('t').value")  # noqa: E731

        def sset(v=""):
            sp.evaluate("v => { const t = document.getElementById('t'); t.value = v; t.focus(); t.select(); }", v)

        def until(fn, want, sec=5.0):
            end = time.time() + sec
            while time.time() < end and fn() != want:
                time.sleep(0.15)
            return fn()

        def open_panel(br, dev=None, perms=(), mac=False):
            dev = {k: v for k, v in (dev or {"viewport": {"width": 1366, "height": 860}}).items()
                   if k != "default_browser_type"}
            ctx = br.new_context(**dev, permissions=list(perms)) if perms else br.new_context(**dev)
            if mac:
                ctx.add_init_script("Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' })")
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("console", lambda m: m.type == "error" and "404" not in m.text
                                   and "interactive-widget" not in m.text and errs.append(m.text))
            pg.goto(base)
            pg.wait_for_function("window.deskShow || typeof part === 'function'")
            pg.evaluate("(async () => { if (!window.deskShow) await part('desktop'); deskShow({demo: false}); })()")
            pg.wait_for_function("document.querySelector('.desk-st')?.textContent === 'на связи'", timeout=15000)
            time.sleep(0.8)
            return ctx, pg

        def shot(pg, name):
            if shots:
                pg.screenshot(path=str(shots / f"{name}.png"))

        cr = p.chromium.launch()
        # 1. Компьютер: Ctrl+V без разрешения на чтение буфера (только событие paste), затем копия со стола
        ctx, pg = open_panel(cr, perms=["clipboard-write"])
        cv = pg.locator(".desk-view canvas").first
        for name, text in (("Ctrl+V кириллица", CYR), ("Ctrl+V латиница", LAT)):
            sset()
            pg.evaluate("t => navigator.clipboard.writeText(t)", text)
            cv.click(position={"x": 300, "y": 120})
            sset()
            pg.keyboard.press("Control+v")
            check(name, until(sval, text), text)
        shot(pg, "1-ctrl-v-1366")
        ctx.grant_permissions(["clipboard-read", "clipboard-write"])
        pg.evaluate("navigator.clipboard.writeText('старое')")
        sset(CYR)
        pg.keyboard.press("Control+c")
        clip = lambda: pg.evaluate("navigator.clipboard.readText()")  # noqa: E731
        check("Ctrl+C со стола → буфер устройства", until(clip, CYR), CYR)
        shot(pg, "2-ctrl-c-1366")
        ctx.close()

        # 2. Mac: ⌘+V, ⌘+C — как Ctrl на столе
        ctx, pg = open_panel(cr, perms=["clipboard-read", "clipboard-write"], mac=True)
        cv = pg.locator(".desk-view canvas").first
        cv.click(position={"x": 300, "y": 120})
        sset()
        pg.evaluate("t => navigator.clipboard.writeText(t)", CYR)
        pg.keyboard.press("Meta+v")
        check("⌘+V (Mac)", until(sval, CYR), CYR)
        pg.evaluate("navigator.clipboard.writeText('старое')")
        sset(LAT)
        pg.keyboard.press("Meta+c")
        check("⌘+C (Mac)", until(lambda: pg.evaluate("navigator.clipboard.readText()"), LAT), LAT)
        ctx.close()

        # 3. Телефон 390 (Chromium): кнопка «Вставить»; без разрешения — поле «Буфер»
        phone = p.devices["iPhone 13"]
        ctx, pg = open_panel(cr, dev=phone, perms=["clipboard-read", "clipboard-write"])
        sset()
        pg.evaluate("t => navigator.clipboard.writeText(t)", CYR)
        pg.click(".desk-dock [data-desk=paste]")
        check("телефон: кнопка «Вставить»", until(sval, CYR), CYR)
        pg.wait_for_timeout(300)
        shot(pg, "3-paste-button-390")
        ctx.close()
        ctx, pg = open_panel(cr, dev=phone)
        sset()
        pg.click(".desk-dock [data-desk=paste]")
        pg.wait_for_selector(".desk-clip-in:visible")
        pg.fill(".desk-clip-in", LAT)
        shot(pg, "4-paste-fallback-390")
        pg.click("[data-desk=clip-paste]")
        check("телефон без разрешения: поле → «Вставить на стол»", until(sval, LAT), LAT)
        ctx.close()

        # 4. WebKit 390: «Вставить» (чтение буфера в WebKit Playwright не даёт — запасное поле), «Ctrl+C» из ряда клавиш
        try:
            wk = p.webkit.launch()
        except Exception as e:
            print(f"--   WebKit не запустился: {e}")
            wk = None
        if wk:
            ctx, pg = open_panel(wk, dev=phone)
            sset()
            pg.click(".desk-dock [data-desk=paste]")
            pg.wait_for_selector(".desk-clip-in:visible", timeout=8000)
            pg.fill(".desk-clip-in", CYR)
            pg.click("[data-desk=clip-paste]")
            check("WebKit 390: поле → «Вставить на стол»", until(sval, CYR), CYR)
            sset(LAT)
            if not pg.locator(".desk-keys:visible").count():
                pg.click(".desk-dock [data-desk=keys]")
            pg.click(".desk-keys [data-key=c]")
            pg.wait_for_selector(".desk-clip-out:visible", timeout=8000)
            check("WebKit 390: копия со стола в «Буфере»", pg.inner_text(".desk-clip-text"), LAT)
            shot(pg, "5-webkit-copy-390")
            ctx.close()
            wk.close()
        cr.close()
    fails += [f"консоль: {e}" for e in errs]
    return fails


if __name__ == "__main__":
    why = ready()
    if why:
        sys.exit(f"пропуск: {why}")
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    with Stand() as st:
        bad = run(st, out)
    print("\n".join(bad) or "всё ок")
    sys.exit(1 if bad else 0)
