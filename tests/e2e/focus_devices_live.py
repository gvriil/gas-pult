"""Фокус-ссылка на нескольких устройствах вживую (владелец 22.11) — на трёх движках браузера.

    python tests/e2e/focus_devices_live.py chromium|firefox|webkit [папка-для-снимков]

Сбой, который проверяем: на телефоне ссылка открылась, на компьютере открыли адрес «/?focus» без токена (страница
убирает его из адреса) — и видели глухое «Ссылка не действует». Панель — настоящий сервер с временными папками и
своим tmux (``focus_live.start``: подставной Claude, Telegram — в файл). Устройства — отдельные контексты браузера
(свои cookie).

  (1) устройство 1 (телефон) открывает ссылку с токеном — чат; токена в адресе нет; на экране «На другом устройстве»;
  (2) «Открыть на другом устройстве» → одноразовая ссылка → устройство 2 (компьютер) открывает чат по ней;
  (3) устройство 3 открывает «/?focus» без токена — экран «Нужна полная ссылка» и «Попросить доступ» → запрос ушёл
      владельцу (подмена Telegram), человеку — «Запрос отправлен владельцу»;
  (4) третье место занимает основная ссылка; устройство 4 — экран «Все места заняты» с «Попросить доступ»;
      «Открыть на другом устройстве» на устройстве 1 — «Все места заняты», ссылку не выдаёт;
  (5) одноразовая ссылка второй раз не открывается.

Движки: chromium (он же Edge и Chrome), firefox, webkit (Safari; телефон — мобильный вид). У Firefox нет
мобильного режима Playwright (``is_mobile``) — телефон у него только шириной 390.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import _onebrowser  # noqa: F401  — e2e с браузером по одному на сервер (tests/heavy_lock.py)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from focus_live import agree, free_port, start

ENGINES = ("chromium", "firefox", "webkit")


def run(engine: str = "chromium", shots: str = "") -> list[str]:
    from playwright.sync_api import sync_playwright

    root = Path(tempfile.mkdtemp(prefix="gp-", dir="/tmp"))      # короткий путь: сокет tmux помещается
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc, ready = start(root, port)
    shop = ready["wins"]["shop"]
    errs: list[str] = []
    done: list[str] = []

    def log(step):
        done.append(step)
        print(f"ok [{engine}]:", step, flush=True)

    def tg_sent() -> list[dict]:
        f = root / "telegram.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    try:
        with sync_playwright() as pw:
            br = getattr(pw, engine).launch(headless=True)

            def unsecure(ctx, route):
                """WebKit не шлёт cookie с «Secure» на http://127.0.0.1 (Safari у людей — по https): в проверке
                снимаем только этот флаг у cookie фокуса; остальное — ответ сервера как есть. ``route.fetch`` кладёт
                исходную cookie в контекст — её убираем, браузер получит ту же без «Secure»."""
                r = route.fetch()
                ctx.clear_cookies(name="gp_focus")
                h = {k: v for k, v in r.headers.items() if k.lower() != "set-cookie"}
                if r.headers.get("set-cookie"):
                    h["set-cookie"] = r.headers["set-cookie"].replace("; Secure", "")
                route.fulfill(response=r, headers=h)

            def device(mobile: bool):
                # WebKit: запросы через service worker страницы мимо ``route`` — для подмены флага SW выключен
                sw = {"service_workers": "block"} if engine == "webkit" else {}
                if not mobile:
                    ctx = br.new_context(viewport={"width": 1366, "height": 860}, **sw)
                else:
                    kw = {"viewport": {"width": 390, "height": 844}, **sw}
                    if engine != "firefox":                   # у Firefox в Playwright нет мобильного режима
                        kw.update(is_mobile=True, has_touch=True)
                    ctx = br.new_context(**kw)
                if engine == "webkit":
                    ctx.route("**/api/focus/open", lambda route, _req, c=ctx: unsecure(c, route))
                return ctx

            def page(ctx, url):
                pg = ctx.new_page()
                pg.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text
                      and "status of 410" not in m.text and "interactive-widget" not in m.text   # Safari: мета-тег
                      and errs.append(f"{engine}: {m.text}"))
                pg.on("pageerror", lambda e: errs.append(f"{engine}: {e}"))
                pg.goto(url)
                agree(pg, url)
                return pg

            def shot(pg, name):
                if shots:
                    pg.screenshot(path=f"{shots}/e2e-{engine}-{name}.png")

            # владелец выпускает ссылку (как «Создать фокус-ссылку» в меню чата)
            owner = device(False)
            owner.add_cookies([{**ready["cookie"], "url": base}])
            po = owner.new_page()
            po.goto(base + "/api/meta")
            code, d = po.evaluate("""async ([w, base]) => { const r = await fetch("/api/focus/new", { method: "POST",
              headers: { "Content-Type": "application/json" }, body: JSON.stringify({ w, base }) });
              return [r.status, await r.json()]; }""", [shop, base])
            assert code == 200 and "/#focus=" in d["url"], (code, d)
            url = d["url"]

            # (1) устройство 1 — телефон
            d1 = device(True)
            p1 = page(d1, url)
            p1.wait_for_selector("#session:not([hidden])", timeout=20000)
            assert "#focus=" not in p1.url and p1.url.endswith("?focus"), p1.url
            mark = p1.evaluate("localStorage.getItem('gp.focus')")
            assert mark and json.loads(mark)["id"], mark
            p1.wait_for_selector("[data-fdev]", timeout=10000)
            shot(p1, "1-phone")
            log("(1) устройство 1 открыло ссылку; токена в адресе нет; «На другом устройстве» на экране")

            # (2) «Открыть на другом устройстве» → устройство 2
            p1.click("[data-fdev]")
            p1.wait_for_selector("#fdUrl", timeout=10000)
            extra = p1.inner_text("#fdUrl")
            assert extra.startswith(base + "/#focus=") and extra != url, extra
            assert p1.locator(".sheet img.focus-qr").get_attribute("src").startswith("data:image/png")
            assert "1 из 3" in p1.inner_text(".sheet")
            shot(p1, "2-qr")
            p1.evaluate("document.querySelectorAll('.sheet-bg').forEach((b) => b.remove())")
            d2 = device(False)
            p2 = page(d2, extra)
            p2.wait_for_selector("#session:not([hidden])", timeout=20000)
            assert p2.evaluate("sessions.map((s) => s.id)") == [shop]
            log("(2) «Открыть на другом устройстве» — QR и ссылка; устройство 2 открыло чат")

            # (3) «/?focus» без токена на новом устройстве
            d3 = device(False)
            p3 = page(d3, base + "/?focus")
            p3.wait_for_selector("#focusEnd[data-why=nodevice]", timeout=15000)
            assert "Нужна полная ссылка" in p3.inner_text("#focusEnd")
            shot(p3, "3-nodevice")
            p3.click("[data-fd-open]")
            p3.fill("#fdNote", "Ольга, ноутбук")
            p3.click("[data-fd-send]")
            p3.wait_for_selector("text=Запрос отправлен владельцу", timeout=10000)
            sent = [m for m in tg_sent() if m["method"] == "sendMessage" and "Просят доступ" in m.get("text", "")]
            assert sent and "Ольга, ноутбук" in sent[-1]["text"], sent
            log("(3) «/?focus» без токена — «Нужна полная ссылка»; «Попросить доступ» ушёл владельцу")

            # (4) третье место — основной ссылкой; четвёртое — «Все места заняты»
            p3b = page(d3, url)
            p3b.wait_for_selector("#session:not([hidden]), #focusEnd", timeout=20000)
            assert not p3b.locator("#focusEnd").count(), p3b.inner_text("#focusEnd")
            d4 = device(True)
            p4 = page(d4, url)
            p4.wait_for_selector("#focusEnd[data-why=limit]", timeout=15000)
            assert "Все места" in p4.inner_text("#focusEnd") and p4.locator("[data-fd-open]").count() == 1
            shot(p4, "4-limit")
            p1.click("[data-fdev]")
            p1.wait_for_selector(".sheet >> text=Все места заняты", timeout=10000)
            log("(4) сверх 3 устройств — «Все места заняты»; новая ссылка для устройства не выдаётся")

            # (5) одноразовая ссылка — второй раз нет
            p5 = page(device(False), extra)
            p5.wait_for_selector("#focusEnd[data-why]", timeout=15000)
            assert p5.get_attribute("#focusEnd", "data-why") == "bad", p5.get_attribute("#focusEnd", "data-why")
            log("(5) одноразовая ссылка второй раз не открывается")
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
    run(sys.argv[1] if len(sys.argv) > 1 else "chromium", sys.argv[2] if len(sys.argv) > 2 else "")
    print("focus_devices_live ok")
