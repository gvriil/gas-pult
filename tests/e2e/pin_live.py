"""«Закрепить» вживую: настоящий сервер панели, свой tmux, подставной Claude, два устройства — телефон и компьютер.

    python tests/e2e/pin_live.py [папка-для-снимков]

Нужны Playwright и Chrome. Ничего боевого не трогает: панель — отдельный процесс (``focus_live.start``: временные
HOME, GAS_PULT_DATA_DIR, GAS_PULT_CONFIG_DIR, свой сервер tmux по короткому сокету, подставной ``claude``).

Сценарий:
  (а) телефон (390, светлая): долгое нажатие на проекте «other» → «Закрепить»; компьютер (1366, тёмная) после
      обновления видит его первым в группе «Закреплённые»;
  (б) компьютер: «⋯» сессии «shop» → «Закрепить»; телефон на вкладке «Сессии» видит её первой;
  (в) перезапуск окна (смена поставщика с продолжением) — сессия по-прежнему закреплена;
  (г) перезапуск панели — закрепления на месте (``projects.json``);
  (д) «Открепить» на телефоне — у компьютера группы «Закреплённые» больше нет.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import focus_live
from focus_live import free_port, start

READY = "typeof meta !== 'undefined' && meta && typeof view !== 'undefined'"   # панель загрузилась


def again(root: Path, port: int) -> subprocess.Popen:
    """Второй запуск панели на тех же HOME и данных (``start`` создаёт папки заново — здесь они уже есть)."""
    home, bin_dir = root / "home", root / "bin"
    env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE", "GAS_PULT_TOKEN")}
    env.update(HOME=str(home), PATH=f"{bin_dir}:{env.get('PATH', '/usr/bin:/bin')}",
               PYTHONPATH=str(Path(focus_live.ROOT) / "src"), GAS_PULT_TMUX_SOCKET=str(root / "s"),
               GAS_PULT_DATA_DIR=str(root / "data"), GAS_PULT_CONFIG_DIR=str(root / "cfg"), SHELL="/bin/sh",
               TZ="Europe/Amsterdam")
    proc = subprocess.Popen([sys.executable, focus_live.__file__, "--serve", str(root), str(port)], env=env,
                            cwd=str(root))
    for _ in range(150):
        if (root / "ready.json").exists():
            return proc
        if proc.poll() is not None:
            raise RuntimeError("панель не запустилась")
        time.sleep(0.1)
    proc.kill()
    raise RuntimeError("панель не ответила за 15 с")


def run(shots: str = ""):
    from playwright.sync_api import sync_playwright

    root = Path(tempfile.mkdtemp(prefix="gp-", dir="/tmp"))
    assert len(str(root / "s")) < 100
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc, ready = start(root, port)
    shop = ready["wins"]["shop"]
    errs: list[str] = []

    def log(step):
        print("ok:", step, flush=True)

    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(channel="chrome", headless=True)

            def device(mobile: bool, theme: str):
                kw = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True} if mobile \
                    else {"viewport": {"width": 1366, "height": 860}}
                ctx = br.new_context(**kw)
                ctx.add_cookies([{**ready["cookie"], "url": base}])
                pg = ctx.new_page()
                pg.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text
                      and errs.append(m.text))
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.goto(f"{base}/?theme={theme}")
                home(pg)
                return pg

            def home(pg):                               # телефон открывает последнюю сессию — к списку проектов
                pg.wait_for_function(READY, timeout=15000)
                pg.wait_for_timeout(600)
                pg.evaluate("if (view === 'session') back()")
                pg.wait_for_selector("#projectsView .card[data-proj]", timeout=15000)

            def shot(pg, name):
                if shots:
                    pg.screenshot(path=os.path.join(shots, name + ".png"))

            def sheet_click(pg, text):
                pg.locator(".sheet button", has_text=text).first.click()

            def first_proj(pg) -> str:
                return pg.evaluate("projData.projects.find((p) => p.id === "
                                   "document.querySelector('#projList .card[data-proj]').dataset.proj).folder")

            phone, pc = device(True, "light"), device(False, "dark")

            # (а) долгое нажатие на проекте на телефоне
            card = phone.locator("#projList .card[data-proj]", has_text="other").first
            card.scroll_into_view_if_needed()
            box = card.bounding_box()
            x, y = box["x"] + 80, box["y"] + 20
            phone.evaluate("""([x, y]) => document.elementFromPoint(x, y).dispatchEvent(new PointerEvent("pointerdown",
              { bubbles: true, clientX: x, clientY: y, pointerType: "touch" }))""", [x, y])
            phone.wait_for_selector(".sheet h3:text('other')", timeout=3000)
            sheet_click(phone, "Закрепить")
            phone.wait_for_selector(".toast >> text=Закреплено", timeout=5000)
            phone.wait_for_function("document.querySelector('#projList .pin-h')", timeout=5000)
            assert first_proj(phone) == "other"
            shot(phone, "a-phone-390-light")
            pc.evaluate("refresh()")
            pc.wait_for_function("document.querySelector('#projList .pin-h')", timeout=10000)
            assert first_proj(pc) == "other"
            shot(pc, "a-pc-1366-dark")
            log("(а) телефон закрепил проект долгим нажатием — компьютер видит его наверху")

            # (б) «⋯» сессии на компьютере
            pc.click("#homeSeg button[data-v=sessions]")
            pc.wait_for_selector("#sessionsView .card[data-id]", timeout=10000)
            pc.locator(f"#sessionsView .card[data-id='{shop}'] [data-more-s]").first.click()
            sheet_click(pc, "Закрепить")
            pc.wait_for_function(f"document.querySelector('#sessionsView .card[data-id]').dataset.id === '{shop}'",
                                 timeout=10000)
            phone.click("#homeSeg button[data-v=sessions]")
            phone.wait_for_function(f"document.querySelector('#sessionsView .card[data-id]')?.dataset.id === '{shop}'"
                                    " && document.querySelector('#sessionsView .pin-h')", timeout=10000)
            shot(phone, "b-phone-390-light")
            shot(pc, "b-pc-1366-dark")
            log("(б) компьютер закрепил сессию — на телефоне она первой, в «Закреплённых»")

            # (в) перезапуск окна
            new = pc.evaluate("""async (w) => (await (await fetch("/api/restart", { method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ w, profile: "claude", keep: true }) })).json()).id""", shop)
            assert new and new != shop, new
            pc.evaluate("refresh()")
            pc.wait_for_function(f"sessions.some((s) => s.id === '{new}' && s.pinned)", timeout=15000)
            log(f"(в) перезапуск окна {shop} → {new}: сессия по-прежнему закреплена")

            # (г) перезапуск панели
            proc.terminate()
            proc.wait(10)
            (root / "ready.json").unlink()
            proc = again(root, port)                    # тот же HOME и данные; окна — старые плюс два новых
            pc.reload()
            pc.wait_for_function(f"sessions.some((s) => s.id === '{new}' && s.pinned)", timeout=15000)
            data = json.loads((root / "data" / "projects.json").read_text())
            mine = data.get("pins", {}).get("owner", {})          # закрепления — свои у каждого: здесь владельца
            assert mine.get("projects") and mine.get("chats"), data
            log("(г) после перезапуска панели закрепления на месте")

            # (д) «Открепить» на телефоне
            phone.reload()                              # вкладка «Сессии» запомнилась — список сессий
            phone.wait_for_function(READY, timeout=15000)
            phone.wait_for_timeout(600)
            phone.evaluate("if (view === 'session') back()")
            phone.wait_for_selector("#sessionsView .card[data-id]", timeout=10000)
            phone.evaluate(f"sessionSheet('{new}')")
            sheet_click(phone, "Открепить")
            phone.wait_for_selector(".toast >> text=Откреплено", timeout=5000)
            pc.evaluate("refresh()")
            pc.wait_for_function("!document.querySelector('#sessionsView .pin-h')", timeout=10000)
            log("(д) «Открепить» на телефоне — у компьютера группы нет")
            br.close()
        assert not errs, errs
        print("готово: закрепление работает на двух устройствах, ошибок в консоли нет")
    finally:
        proc.kill()
        subprocess.run(["tmux", "-S", str(root / "s"), "kill-server"], capture_output=True)
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "")
