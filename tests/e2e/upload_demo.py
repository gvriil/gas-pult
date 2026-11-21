"""Загрузка фото (владелец 15.11: «почему так долго загружается фото … оптимизировать»; Playwright).

    python tests/e2e/upload_demo.py http://127.0.0.1:8797/?demo

Узкое место — сеть телефона (223 КБ шли 52 с). Проверяем: фото 3000×2000 PNG сжимается на устройстве до ≤1920 px JPEG
(байт меньше в разы), на значке файла — проценты загрузки, «Отправить» сразу (не «подождите»): сообщение в переписке
«(файл загружается…)», путь подставляется по готовности. Оригинал — через «Файл» (пункта «Фото без сжатия» нет
с 21.11, Gemini №9). Телефон 390 с медленной сетью.
"""

import sys

MAKE = """async () => { const c = Object.assign(document.createElement('canvas'), {width: 3000, height: 2000});
  const g = c.getContext('2d'); const d = g.createImageData(3000, 2000);     // «фото»: плавные переходы + шум
  for (let y = 0, i = 0; y < 2000; y++) for (let x = 0; x < 3000; x++, i += 4) {
    const n = (i * 2654435761 >>> 28) & 15;
    d.data[i] = (x / 12 + n) & 255; d.data[i + 1] = (y / 8 + n) & 255;
    d.data[i + 2] = ((x + y) / 20) & 255; d.data[i + 3] = 255; }
  g.putImageData(d, 0, 0); const b = await new Promise((ok) => c.toBlob(ok, 'image/png'));
  return Array.from(new Uint8Array(await b.arrayBuffer())); }"""


def run(base: str):
    from playwright.sync_api import sync_playwright

    sep = "&" if "?" in base else "?"
    errs: list[str] = []
    with sync_playwright() as p:
        br = p.chromium.launch()
        ctx = br.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        cdp = ctx.new_cdp_session(pg)
        cdp.send("Network.enable")
        cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 300,
                                                      "downloadThroughput": 50_000, "uploadThroughput": 8_000})
        pg.goto(f"{base}{sep}open=@1&noscroll")
        pg.wait_for_selector("#content .msg", timeout=60000)
        png = bytes(pg.evaluate(MAKE))
        pg.set_input_files("#fPhoto", files=[{"name": "screen.png", "mimeType": "image/png", "buffer": png}])
        pg.wait_for_function("window.__demoUploads?.length === 1", timeout=20000)
        sent = pg.evaluate("window.__demoUploads[0]")
        assert sent < len(png) / 3, f"не сжато: {len(png)} → {sent}"
        pg.wait_for_function("/\\.jpg · \\d+ %/.test(document.getElementById('attach').innerText)", timeout=5000)
        pg.fill("#input", "Что на фото?")
        pg.evaluate("() => { sendText(); }")                       # сразу, не дожидаясь загрузки
        assert "Подождите" not in pg.inner_text("body")
        pg.wait_for_function("pending.some((p) => p.text.includes('файл загружается'))", timeout=3000)
        pg.wait_for_function("pending.length === 0 || pending.every((p) => p.text.includes('Файл из панели:'))",
                             timeout=20000)
        # «Файл» — оригинал без сжатия
        pg.set_input_files("#fFile", files=[{"name": "orig.png", "mimeType": "image/png", "buffer": png}])
        pg.wait_for_function("window.__demoUploads.length === 2", timeout=20000)
        assert pg.evaluate("window.__demoUploads[1]") == len(png), "«Файл» сжал"
        print(f"ok: {len(png) // 1024} КБ PNG → {sent // 1024} КБ JPEG; сообщение ушло, не дожидаясь загрузки")
        br.close()
    assert not errs, f"ошибки: {errs}"


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo")
