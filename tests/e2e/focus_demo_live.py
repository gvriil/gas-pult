"""Демо-ссылка вживую: настоящий сервер панели, свой tmux, подставной Claude, два браузера — два устройства гостей.

    python tests/e2e/focus_demo_live.py [папка-для-снимков]

Нужны Playwright и Chrome. Ничего боевого не трогает: панель — отдельный процесс (``focus_live.start``: временные
HOME, GAS_PULT_DATA_DIR, GAS_PULT_CONFIG_DIR, свой сервер tmux по короткому сокету, подставной ``claude``).

Сценарий:
  (а) владелец: панель чатов → «⋯» проекта «shop» → «Создать демо-ссылку» — ссылка ``…/#focus=<токен>``;
  (б) телефон (390, светлая) и компьютер (1366, тёмная) открывают одну ссылку — оба видят сессию проекта; поля ввода
      нет, вместо него плашка «Демо — только просмотр и выбор вариантов», под шапкой «Демо до ДД.ММ»; в меню — только
      «Прослушать» и «Обновить»; текст, файлы, модель, завершение — 403;
  (в) Claude задаёт вопрос — на телефоне кнопки вариантов, выбор проходит, Claude получает ответ; компьютер жмёт
      после — «Уже ответили» (409), в окно ничего не уходит;
  (г) «Настройки» → «Фокус-ссылки»: пометка «Демо» и «2 устройства»;
  (д) «Отозвать» — оба устройства видят «Ссылка не действует».
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from focus_live import FETCH, free_port, start

OWNER_FETCH = """async ([path, body]) => { const r = await fetch(path, { method: body ? "POST" : "GET",
  headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  return [r.status, await r.json().catch(() => ({}))]; }"""


def run(shots: str = ""):
    from playwright.sync_api import sync_playwright

    root = Path(tempfile.mkdtemp(prefix="gp-", dir="/tmp"))
    assert len(str(root / "s")) < 100
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc, ready = start(root, port)
    shop = ready["wins"]["shop"]
    errs: list[str] = []
    done: list[str] = []

    def log(step):
        done.append(step)
        print("ok:", step, flush=True)

    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(channel="chrome", headless=True)

            def device(mobile: bool, dark=False):
                kw = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True} if mobile \
                    else {"viewport": {"width": 1366, "height": 860}}
                return br.new_context(color_scheme="dark" if dark else "light", **kw)

            def page(ctx, url):
                pg = ctx.new_page()
                pg.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text
                      and errs.append(m.text))      # 403/409 — ожидаемые ответы сервера
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.on("dialog", lambda d: d.accept())
                pg.goto(url)
                return pg

            # ---------- (а) владелец: «⋯» проекта → «Создать демо-ссылку» ----------
            owner = device(False)
            owner.add_cookies([{**ready["cookie"], "url": base}])
            po = page(owner, base + "/")
            po.wait_for_function("projData?.projects?.length >= 2", timeout=20000)
            pid = po.evaluate("projData.projects.find((p) => p.folder === 'shop').id")
            po.wait_for_selector(f'#navList [data-np="{pid}"]', timeout=10000)
            row = po.locator(f'#navList [data-np="{pid}"]')
            row.hover()
            row.locator("[data-nmore]").click()
            po.locator(".pop button", has_text="Создать демо-ссылку").click()
            po.wait_for_selector("#focusUrl")
            assert po.locator(".sheet h3", has_text="Демо-ссылка").count() == 1
            assert "нескольких устройствах" in po.inner_text(".sheet .note")
            url = po.inner_text("#focusUrl")
            assert url.startswith(base + "/#focus="), url
            if shots:
                po.screenshot(path=f"{shots}/demo-link-owner-1366.png")
            po.locator(".sheet [data-close]").click()
            log("(а) «⋯» проекта → «Создать демо-ссылку»: ссылка выпущена")

            # ---------- (б) два устройства по одной ссылке: только просмотр ----------
            pa = page(device(True), url)
            pb = page(device(False, dark=True), url.replace("/#focus=", "/?theme=dark#focus="))
            till = time.strftime("%d.%m", time.localtime(time.time() + 7 * 86400 - 60))
            for pg in (pa, pb):
                pg.wait_for_selector("#session:not([hidden])", timeout=15000)
                pg.wait_for_selector("#focusExp:not([hidden])", timeout=10000)
                assert pg.evaluate("document.body.classList.contains('focus-demo')")
                assert pg.evaluate("sessions.map((s) => s.id)") == [shop]
                assert f"Демо до {till}" in pg.inner_text("#focusExp"), pg.inner_text("#focusExp")
                assert pg.is_visible("#demoNote") and "только просмотр и выбор вариантов" in pg.inner_text("#demoNote")
                assert not pg.is_visible("#input") and not pg.is_visible("#mic") and not pg.is_visible("#plus")
                pg.click("#menuBtn")
                acts = pg.evaluate("[...document.querySelectorAll('#menu button')].filter((b) => "
                                   "getComputedStyle(b).display !== 'none' && !b.hidden).map((b) => b.dataset.act)")
                # «Сессии» — шторка сессий проекта
                assert set(acts) <= {"say", "sayfull", "refresh", "switch"} and "refresh" in acts, acts
                pg.click("#menuBtn")
                for path, body in (("/api/send", {"w": shop, "text": "чужой текст"}), ("/api/model",
                                   {"w": shop, "name": "opus"}), ("/api/close", {"w": shop}),
                                   ("/api/effort", {"w": shop, "level": "high"}), ("/api/upload", {}),
                                   ("/api/project/session", {"id": pid}), ("/api/mcp", None),
                                   ("/api/key", {"w": shop, "key": "Escape"}),
                                   ("/api/select", {"w": shop, "text": "", "n": "1"})):
                    code, d = pg.evaluate(FETCH, [path, body])
                    assert code == 403 and d.get("code") == "focus_scope", (path, code, d)
            assert pb.evaluate("document.documentElement.dataset.theme") == "dark"
            if shots:
                pa.screenshot(path=f"{shots}/demo-390-light.png")
                pb.screenshot(path=f"{shots}/demo-1366-dark.png")
            log("(б) оба устройства видят сессию, поля ввода нет, плашка демо; текст, файлы, модель — 403")

            # ---------- (в) вопрос Claude: кнопка на телефоне работает, второе устройство — «уже ответили» ----------
            code, d = po.evaluate(OWNER_FETCH, ["/api/send", {"w": shop, "text": "задай вопрос"}])
            assert code == 200, d
            pa.wait_for_selector("#ask button[data-n='1']", timeout=20000)
            pb.wait_for_selector("#ask button[data-n='1']", timeout=20000)
            if shots:
                pa.screenshot(path=f"{shots}/demo-ask-390.png")
            pa.wait_for_selector("#ask button[data-n='1'].sel", timeout=5000)   # ❯ на первом — касание выбирает
            pa.click("#ask button[data-n='1']")
            pa.wait_for_selector("text=Выбрано: Первый", timeout=20000)
            code, d = pb.evaluate(FETCH, ["/api/select", {"w": shop, "text": "", "n": "2"}])
            assert code == 409 and d.get("code") == "answered", (code, d)
            pb.wait_for_selector("text=Выбрано: Первый", timeout=20000)
            log("(в) вопрос Claude: выбор с телефона прошёл, второе устройство — «Уже ответили»")

            # ---------- (г) список ссылок у владельца: «Демо», два устройства ----------
            code, d = po.evaluate(OWNER_FETCH, ["/api/focus/list", None])
            demo = [x for x in d["links"] if x.get("mode") == "demo"]
            assert len(demo) == 1 and demo[0]["devices"] == 2, d
            po.evaluate("focusList()")
            po.wait_for_selector(".sheet button:has-text('Демо · Проект')", timeout=5000)
            assert "2 устройства" in po.inner_text(".sheet")
            if shots:
                po.screenshot(path=f"{shots}/demo-list-1366.png")
            log("(г) «Фокус-ссылки»: пометка «Демо» и «2 устройства»")

            # ---------- (д) «Отозвать» — оба устройства отключены ----------
            po.locator(".sheet button", has_text="Демо · Проект").click()        # подтверждение — confirm(), принято
            for pg in (pa, pb):
                pg.wait_for_selector("#focusEnd", timeout=20000)
                assert "Ссылка не действует" in pg.inner_text("#focusEnd")
            if shots:
                pa.screenshot(path=f"{shots}/demo-revoked-390.png")
            log("(д) «Отозвать» — оба устройства: «Ссылка не действует»")
            br.close()
    finally:
        proc.terminate()
        proc.wait(5)
        subprocess.run(["tmux", "-S", str(root / "s"), "kill-server"], capture_output=True)
        if os.environ.get("GP_KEEP"):
            print("папка проверки:", root)
        else:
            shutil.rmtree(root, ignore_errors=True)
    assert not errs, f"ошибки консоли: {errs}"
    return done


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "")
    print("focus_demo_live ok")
