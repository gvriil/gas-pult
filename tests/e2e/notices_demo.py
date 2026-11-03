"""Всплывающее не закрывает поле ввода (задача 26; Playwright — pytest запускает, только если есть браузер).

    python tests/e2e/notices_demo.py http://127.0.0.1:8797/?demo [папка-для-скриншотов]

Телефон 390×844 с открытой клавиатурой (visualViewport подменён: видимая область на 336 px ниже) и без неё, ПК 1366;
полный режим (``?demo&open=@1``) и простой (``&simple=1``), светлая и тёмная тема. На экране сразу всё всплывающее:
«Есть новая версия» (``&upd=1``), «Нет связи» (``&offline=1``), тост, предложение тура (``&tour=1``),
кнопка «к последнему», мини-плеер, полоса демо, шторка помощника. Ни один прямоугольник не пересекается с полем
ввода и нижней панелью (#dock / .s-dock). Каждый элемент из реестров NOTICES и ABOVE_DOCK в index.html обязан
здесь проверяться — новый всплывающий элемент без проверки тест не пропустит. «Позже» прячет строку обновления;
черновик в поле ввода переживает «Обновить». Консоль без ошибок.
"""

import json
import re
import sys
from pathlib import Path

INDEX = Path(__file__).resolve().parents[2] / "src" / "gas_pult" / "web" / "index.html"
KB = 336                                                     # высота клавиатуры iPhone, px

# Клавиатура: в безголовом Chrome её нет — подменяем visualViewport, как его видит панель на iPhone (innerHeight тот же,
# видимая область ниже). window.__kb(px) открывает и закрывает её с событием resize, как настоящая.
FAKE_KB = """(() => {
  const et = new EventTarget(); let kb = 0;
  const vv = { get width() { return innerWidth; }, get height() { return innerHeight - kb; },
               offsetTop: 0, offsetLeft: 0, pageTop: 0, pageLeft: 0, scale: 1,
               addEventListener: et.addEventListener.bind(et),
               removeEventListener: et.removeEventListener.bind(et), dispatchEvent: et.dispatchEvent.bind(et) };
  Object.defineProperty(window, "visualViewport", { get: () => vv, configurable: true });
  window.__kb = (px) => { kb = px; et.dispatchEvent(new Event("resize")); };
})();"""

# Показать всё всплывающее разом. Что появляется само (новая версия, тур, полоса демо), — ждём; что зависит от времени
# или действий (нет связи 15 с, тост, озвучка, прокрутка вверх) — включаем так же, как это делает сама панель.
SHOW_ALL = """async (simple) => {
  const $ = (id) => document.getElementById(id);
  if (!simple) {
    lastOk = Date.now() - 20000;                       // с &offline=1 сервер «молчит» — через секунду «Нет связи»
    voice = { w: current, name: "сессия", msg: null, state: "pause" }; $("mini").hidden = false;
    $("mini").className = "voice mini pause"; $("mini").innerHTML = voiceInner(true); placeMini();
    $("toBottom").hidden = false;
  }
  toast("Сообщение доставлено — проверка тоста", 60000);
  await new Promise((ok) => setTimeout(ok, 1300));
}"""

RECTS = """(sels) => {
  const vis = (el) => { const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return s.display !== "none" && s.visibility !== "hidden" && r.width > 0 && r.height > 0; };
  // Внутри зоны уведомлений видна только часть, что влезла в зону (overflow: hidden) — её и меряем.
  const z = document.getElementById("notices").getBoundingClientRect(), out = {};
  for (const sel of sels) out[sel] = [...document.querySelectorAll(sel)].filter(vis).map((el) => {
    const r = el.getBoundingClientRect();
    if (!el.closest("#notices")) return [r.left, r.top, r.right, r.bottom];
    const c = [Math.max(r.left, z.left), Math.max(r.top, z.top),
               Math.min(r.right, z.right), Math.min(r.bottom, z.bottom)];
    return c[2] > c[0] && c[3] > c[1] ? c : null;
  }).filter(Boolean);
  return out;
}"""


def registry(name: str) -> list[str]:
    m = re.search(rf"^const {name} = (\[.*?\]);", INDEX.read_text(encoding="utf-8"), re.M)
    assert m, f"нет реестра {name} в index.html"
    return json.loads(m.group(1))


# Что проверяем в каждом режиме: элементы реестров (+ полоса демо и сама шторка помощника) против поля ввода и дока.
FULL = {"guard": ["#composer", "#input", "#mic", "#dock"],
        "float": ["#updateBar", "#net", ".toast", ".tour-offer", ".tobottom", ".mini", "#demoBar"]}
SIMPLE = {"guard": ["#sComp", "#sInput", "#sSend", ".s-dock"],
          "float": ["#updateBar", ".toast", "#sDemo"]}
MUST_SHOW = {"full": ["#updateBar", "#net", ".toast", ".tour-offer", ".tobottom", ".mini", "#demoBar"],
             "simple": ["#updateBar", ".toast", "#sDemo"]}


def cross(a, b) -> bool:
    return a[0] < b[2] - 0.5 and b[0] < a[2] - 0.5 and a[1] < b[3] - 0.5 and b[1] < a[3] - 0.5


def check(pg, mode: str, where: str, kb: bool = False):
    spec = FULL if mode == "full" else SIMPLE
    r = pg.evaluate(RECTS, spec["guard"] + spec["float"] + [".help-bg", "#notices"])
    for sel in MUST_SHOW[mode]:
        if kb and sel == ".tour-offer":                       # клавиатура открыта — предложение тура ждёт
            assert not r[sel], f"{where}: предложение тура на экране, пока человек пишет"
            continue
        assert r[sel], f"{where}: {sel} не на экране — проверка ничего не проверила"
    for g in spec["guard"]:
        assert r[g], f"{where}: нет {g}"
        for f in spec["float"] + [".help-bg", "#notices"]:
            for box in r[f]:
                assert not cross(box, r[g][0]), f"{where}: {f} {box} перекрывает {g} {r[g][0]}"


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    # Каждый зарегистрированный всплывающий элемент обязан проверяться здесь.
    covered = set(FULL["float"]) | set(SIMPLE["float"]) | {".help-bg"}
    missing = (set(registry("NOTICES")) | set(registry("ABOVE_DOCK"))) - covered
    assert not missing, f"новые всплывающие элементы без проверки в браузере: {missing}"

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for mode in ("full", "simple"):
            for w, h in ((390, 844), (1366, 860)):
                for theme in ("light", "dark"):
                    for kb in ((0, KB) if w == 390 else (0,)):
                        where = f"{mode} {w}×{h} {theme}{' клавиатура' if kb else ''}"
                        pg = br.new_page(viewport={"width": w, "height": h})
                        pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
                        pg.on("pageerror", lambda e: errs.append(str(e)))
                        pg.add_init_script(FAKE_KB)
                        q = "open=@1&tour=1&offline=1" if mode == "full" else "simple=1"
                        pg.goto(f"{base}{sep}{q}&upd=1&theme={theme}")
                        pg.wait_for_selector("#updateBar:not([hidden])", timeout=8000)
                        if mode == "full":
                            pg.wait_for_selector(".tour-offer", timeout=8000)
                        pg.evaluate(SHOW_ALL, mode == "simple")
                        if kb:
                            pg.click("#input" if mode == "full" else "#sInput")
                            pg.evaluate(f"__kb({kb})")
                        pg.wait_for_timeout(400)
                        check(pg, mode, where, bool(kb))
                        if shots:
                            pg.screenshot(path=f"{shots}/notices-{mode}-{w}-{theme}{'-kb' if kb else ''}.png")
                        # Шторка помощника поверх экрана — над нижней панелью.
                        pg.click("#helpBtn" if mode == "full" else "#sHelp")
                        pg.wait_for_selector(".help-bg .sheet", timeout=5000)
                        pg.wait_for_timeout(300)
                        r = pg.evaluate(RECTS, [".help-bg"])
                        assert r[".help-bg"], f"{where}: шторка помощника не открылась"
                        check(pg, mode, where + " + помощник", bool(kb))
                        if shots:
                            pg.screenshot(path=f"{shots}/notices-{mode}-{w}-{theme}{'-kb' if kb else ''}-help.png")
                        pg.close()

        # «Позже» прячет строку; «Обновить» перезагружает и возвращает черновик.
        for mode in ("full", "simple"):
            pg = br.new_page(viewport={"width": 390, "height": 844})
            pg.on("pageerror", lambda e: errs.append(str(e)))
            q = "open=@1" if mode == "full" else "simple=1"
            pg.goto(f"{base}{sep}{q}&upd=1")
            pg.wait_for_selector("#updateBar:not([hidden])", timeout=8000)
            pg.click("#updLater")
            assert pg.is_hidden("#updateBar"), f"{mode}: «Позже» не спрятала строку"
            pg.wait_for_timeout(3500)                            # следующий опрос сервера не возвращает её
            assert pg.is_hidden("#updateBar"), f"{mode}: строка вернулась после «Позже»"
            inp = "#input" if mode == "full" else "#sInput"
            pg.fill(inp, "черновик, который нельзя потерять")
            # С черновиком панель сама не перезагружается — даже после возврата из фона.
            pg.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            pg.wait_for_timeout(500)
            assert pg.input_value(inp) == "черновик, который нельзя потерять", f"{mode}: черновик пропал"
            with pg.expect_navigation():
                pg.evaluate("reloadPanel()")                      # то же, что «Обновить»
            pg.wait_for_selector(inp + ":visible", timeout=8000)
            pg.wait_for_function(f"document.querySelector('{inp}').value !== ''", timeout=8000)
            assert pg.input_value(inp) == "черновик, который нельзя потерять", f"{mode}: черновик не вернулся"
            # Пустое поле, ничего не открыто, панель вернулась из фона — перезагрузилась сама.
            pg.fill(inp, "")
            pg.evaluate("UPD.found = true")
            with pg.expect_navigation(timeout=5000):
                pg.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            pg.close()
        br.close()
    assert not errs, f"ошибки в консоли: {errs[:5]}"


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
    print("ok")
