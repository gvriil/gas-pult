"""Фокус на проект вживую: настоящий сервер панели, свой tmux, подставной Claude, браузер — устройство по ссылке.

    python tests/e2e/focus_project_live.py [папка-для-снимков]

Нужны Playwright и Chrome. Ничего боевого не трогает: панель — отдельный процесс (``focus_live.start``: временные
HOME, GAS_PULT_DATA_DIR, GAS_PULT_CONFIG_DIR, свой сервер tmux по короткому сокету, подставной ``claude``;
окна «shop» и «other» — в папках двух проектов).

Сценарий:
  (а) владелец: панель чатов → «⋯» проекта «shop» → «Создать фокус-ссылку на проект» — ссылка ``…/#focus=<токен>``;
  (б) телефон (390, светлая) по ссылке: видны только сессии «shop», под шапкой — проект и «Вход действует до ДД.ММ
      (через 7 дн.)»; API проекта «other», его окна, список проектов, люди — 403;
  (в) шторка проекта → «Новая сессия в проекте» — новое окно в папке «shop», сообщение уходит и приходит ответ;
  (г) «Завершить» одну сессию — ссылка живёт, устройство переходит в другую сессию проекта;
  (д) до конца срока меньше двух дней — «Перезайти через 2 дня» (заметно); компьютер (1366, тёмная) по второй
      ссылке — то же, без ошибок консоли;
  (е) старая ссылка на одну сессию — как раньше: только её окно, проект закрыт (403).
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
from focus_live import FETCH, free_port, start


def run(shots: str = ""):
    from playwright.sync_api import sync_playwright

    root = Path(tempfile.mkdtemp(prefix="gp-", dir="/tmp"))
    assert len(str(root / "s")) < 100
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc, ready = start(root, port)
    shop, other = ready["wins"]["shop"], ready["wins"]["other"]
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
                      and errs.append(m.text))      # 403 — ожидаемые ответы сервера
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.on("dialog", lambda d: d.accept())
                pg.goto(url)
                return pg

            # ---------- (а) владелец: «⋯» проекта → «Фокус-ссылка на проект» ----------
            owner = device(False)
            owner.add_cookies([{**ready["cookie"], "url": base}])
            po = page(owner, base + "/")
            po.wait_for_function("projData?.projects?.length >= 2", timeout=20000)
            pid = po.evaluate("projData.projects.find((p) => p.folder === 'shop').id")
            oid = po.evaluate("projData.projects.find((p) => p.folder === 'other').id")
            po.wait_for_selector(f'#navList [data-np="{pid}"]', timeout=10000)
            row = po.locator(f'#navList [data-np="{pid}"]')
            row.hover()
            row.locator("[data-nmore]").click()
            po.locator(".pop button", has_text="Создать фокус-ссылку на проект").click()
            po.wait_for_selector("#focusUrl")
            h3 = po.locator(".sheet h3")
            assert h3.filter(has_text="Фокус-ссылка на проект").count() == 1, h3.all_inner_texts()
            url = po.inner_text("#focusUrl")
            assert url.startswith(base + "/#focus="), url
            log("(а) «⋯» проекта → «Фокус-ссылка на проект»: ссылка выпущена")

            def proj_link() -> str:
                code, d = po.evaluate("""async (pid) => { const r = await fetch("/api/focus/new", { method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ proj: pid, base: location.origin }) });
                  return [r.status, await r.json()]; }""", pid)
                assert code == 200 and d["proj"] == pid, (code, d)
                return d["url"]

            # ---------- (б) телефон по ссылке: только проект «shop» ----------
            a = device(True)
            pa = page(a, url)
            pa.wait_for_selector("#session:not([hidden])", timeout=15000)
            pa.wait_for_selector("#focusExp:not([hidden])", timeout=10000)
            assert pa.evaluate("document.body.classList.contains('focus-proj')")
            assert pa.evaluate("sessions.map((s) => s.id)") == [shop]
            exp = pa.inner_text("#focusExp")
            till = time.strftime("%d.%m", time.localtime(time.time() + 7 * 86400 - 60))
            assert "shop" in exp and f"Вход действует до {till} (через 7 дн.)" in exp, exp
            for path, body in ((f"/api/project?id={oid}", None), (f"/api/project/sessions?id={oid}", None),
                               ("/api/project/session", {"id": oid}), (f"/api/history?w={other}", None),
                               ("/api/send", {"w": other, "text": "чужое"}), ("/api/projects", None),
                               ("/api/people", None), ("/api/new", {"i": 0}), ("/api/focus/list", None),
                               ("/api/focus/new", {"proj": pid, "base": base})):
                code, d = pa.evaluate(FETCH, [path, body])
                assert code == 403 and d.get("code") == "focus_scope", (path, code, d)
            assert pa.evaluate(FETCH, [f"/api/project?id={pid}", None])[0] == 200
            if shots:
                pa.screenshot(path=f"{shots}/focus-proj-390.png")
            log(f"(б) телефон: только сессии проекта, срок «{exp.splitlines()[-1]}»; чужой проект — 403")

            # ---------- (в) «Новая сессия в проекте» ----------
            pa.click("#focusExp [data-fproj]")
            pa.wait_for_selector(".sheet h3:has-text('Проект')")
            sheet = pa.inner_text(".sheet")
            assert "shop" in sheet and "other" not in sheet, sheet
            if shots:
                pa.screenshot(path=f"{shots}/focus-proj-sheet-390.png")
            pa.locator(".sheet button", has_text="Новая сессия в проекте").click()
            pa.wait_for_function(f"current && current !== {json.dumps(shop)}", timeout=30000)
            fresh = pa.evaluate("current")
            pa.wait_for_function(f"sessions.length === 2 && sessions.some((s) => s.id === {json.dumps(fresh)})",
                                 timeout=20000)
            for _ in range(60):                       # подставной Claude готов принять ввод
                if pa.evaluate(FETCH, ["/api/screen?w=" + fresh, None])[1].get("lines", [""])[-1:] != [""]:
                    break
                time.sleep(0.3)
            pa.fill("#input", "привет в новой сессии")
            pa.click("#send")
            pa.wait_for_selector("text=Ответ (default): привет в новой сессии", timeout=30000)
            code, d = pa.evaluate(FETCH, ["/api/sessions", None])
            assert sorted(x["id"] for x in d["sessions"]) == sorted([shop, fresh]) and \
                all(x["project"] == pid for x in d["sessions"]), d
            log(f"(в) «Новая сессия в проекте» → окно {fresh} в папке проекта, ответ пришёл")

            # ---------- (г) «Завершить» одну сессию — ссылка живёт ----------
            code, d = pa.evaluate(FETCH, ["/api/close", {"w": fresh}])
            assert code == 200 and d["result"] == "закрыто", d
            pa.wait_for_function(f"current === {json.dumps(shop)}", timeout=20000)
            assert not pa.locator("#focusEnd").count()
            assert pa.evaluate(FETCH, ["/api/sessions", None])[0] == 200
            log("(г) «Завершить» одну сессию: ссылка на проект жива, устройство — в другой сессии проекта")

            # ---------- (д) меньше двух дней — заметно; компьютер, тёмная тема ----------
            url2 = proj_link()
            f = root / "data" / "focus.json"
            data = json.loads(f.read_text())
            for rec in data.values():
                if rec.get("proj") == pid:
                    rec["exp"] = int(time.time() + 1.5 * 86400)
            f.write_text(json.dumps(data))
            pa.reload()
            pa.wait_for_selector("#focusExp.soon", timeout=15000)
            assert "Перезайти через 2 дня" in pa.inner_text("#focusExp"), pa.inner_text("#focusExp")
            if shots:
                pa.screenshot(path=f"{shots}/focus-proj-soon-390.png")
            c = device(False, dark=True)
            pc = page(c, url2.replace("/#focus=", "/?theme=dark#focus="))
            pc.wait_for_selector("#focusExp.soon", timeout=15000)
            pc.wait_for_selector("#content .msg, #content .empty:not(:has-text('загружаю'))", timeout=15000)
            assert pc.evaluate("document.documentElement.dataset.theme") == "dark"
            assert pc.evaluate("sessions.map((s) => s.id)") == [shop]
            if shots:
                pc.screenshot(path=f"{shots}/focus-proj-1366-dark.png")
            log("(д) за два дня до конца — «Перезайти через 2 дня»; компьютер 1366, тёмная — то же")

            # ---------- (е) старая ссылка на одну сессию — как раньше ----------
            code, d = po.evaluate("""async (w) => { const r = await fetch("/api/focus/new", { method: "POST",
              headers: { "Content-Type": "application/json" }, body: JSON.stringify({ w, base: location.origin }) });
              return [r.status, await r.json()]; }""", other)
            assert code == 200 and not d.get("proj"), d
            e = device(True)
            pe = page(e, d["url"])
            pe.wait_for_selector("#session:not([hidden])", timeout=15000)
            assert pe.evaluate("sessions.map((s) => s.id)") == [other]
            assert not pe.evaluate("document.body.classList.contains('focus-proj')")
            assert "Вход действует до" in pe.inner_text("#focusExp")
            for path, body in ((f"/api/project?id={oid}", None), ("/api/project/session", {"id": oid})):
                code, r = pe.evaluate(FETCH, [path, body])
                assert code == 403 and r.get("code") == "focus_scope", (path, code, r)
            log("(е) ссылка на одну сессию — как раньше: только её окно, проект — 403")
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
    print("focus_project_live ok")
