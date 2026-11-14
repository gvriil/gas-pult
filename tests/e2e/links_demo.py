"""Ссылки в переписке (задача 33; Playwright — pytest запускает, только если есть браузер).

    python tests/e2e/links_demo.py http://127.0.0.1:8797/?demo

В ленту подкладываются сообщения с опасными и неудобными адресами (полный режим ``?demo&open=@1`` и простой
``&simple=1``, ширина 390 и 1366, светлая и тёмная тема): нажимаемые — только http(s), с target и rel; адрес без схемы
(«pult.example.su/x») — на https://, а file.py, 1.2.3, v2.0, почта — текст; ссылки есть и в `коде`, в блоке кода, в
свёрнутом длинном коде и в «Терминал» — текст кода тот же, «Копировать» блока даёт чистый текст; ни одного обработчика
on*, <script> и javascript:; длинный адрес не раздвигает ленту. Нажатие — openLink; долгое нажатие (и в коде) — меню
«Открыть · Копировать · Поделиться»; без navigator.share «Поделиться» копирует. Консоль без ошибок.
"""

import sys

LONG = "https://example.com/" + "a" * 30 + "/" + "b" * 400 + "?q=" + "c" * 200

TERM = "\n".join(["$ curl -sI https://term.example/health", "HTTP/2 200", "$ ls -la", "total 8",
                  "-rw-r--r-- 1 u u 10 file.py", "$ echo pult.example.su/term"])
LONGCODE = "\n".join(f"step {i}: open https://longcode.example/{i}" for i in range(20))

USER = ("javascript:alert(1) и data:text/html,<script>alert(2)</script> <script>alert(3)</script> "
        'https://x.example/"onmouseover=alert(4) x " https://q.example/a\'b '
        "см. https://dot.example/path. и (https://paren.example/x) и https://wiki.example/A_(b) "
        "&lt;https://ent.example/?a=1&amp;b=2&gt; " + LONG)

AI = ("Ссылка [док](https://doc.example/guide) и [плохая](javascript:alert(5)) и [данные](data:text/html,x) "
      "и [почта](mailto:a@b.example) и голая https://bare.example/p?x=1&y=2.\n\n"
      "Сущности: &lt;https://ent2.example/?a=1&amp;b=2&gt; и &quot;https://ent3.example/&quot;\n\n"
      "Код: `https://code.example/inline` и `curl pult.example.su/api` и `self.app` и\n\n"
      "```\ncurl https://code.example/block\n```\n\n"
      "Без схемы: pult.example.su/x. и (claude.ai/code/abc), не адреса: file.py 1.2.3 v2.0 a.b a@mail.ru\n\n"
      "```\n" + LONGCODE + "\n```\n\n"
      "<a href=\"javascript:alert(6)\" onmouseover=\"alert(7)\">тег</a> <img src=x onerror=alert(8)>\n\n" + LONG)

FAKE_TG = """window.__opened = [];
const noop = new Proxy(function () {},
  { get: (t, k) => (typeof k === "symbol" ? undefined : noop), apply: () => undefined });
window.Telegram = { WebApp: new Proxy({ initDataUnsafe: {}, platform: "android", version: "8.0", themeParams: {},
  openLink: (u) => window.__opened.push(u) },
  { get: (t, k) => (k === "initData" ? (window.__tgOn ? "demo" : "")
    : k in t ? t[k] : typeof k === "string" ? noop : undefined) }) };"""

MENU = "b => b.map((x) => [x.innerText, x.getBoundingClientRect().height, !!x.querySelector('svg.i')])"

INJECT = """([mode, user, ai, term]) => {
  window.__alerts = 0; window.alert = () => { window.__alerts++; };
  const items = [{ i: 901, role: "user", text: user, ts: "2026-11-04 10:00" },
                 { i: 902, role: "assistant", text: ai, ts: "2026-11-04 10:01" }];
  if (mode === "full") items.push({ i: 903, role: "user", text: "Вот вывод:\\n" + term, ts: "2026-11-04 10:02" });
  if (mode === "simple") { SIM.hist = items; sRender(); } else { hist = items; renderChat(); }
}"""

CHECK = """(sel) => {
  const box = document.querySelector(sel), links = [...box.querySelectorAll(".msg .bubble a")];
  const all = [...box.querySelectorAll(".msg *")];
  return {
    links: links.map((a) => ({ href: a.getAttribute("href"), text: a.textContent, target: a.target, rel: a.rel,
                               cls: a.className })),
    onattr: all.filter((e) => [...e.attributes].some((x) => /^on/i.test(x.name))).map((e) => e.outerHTML.slice(0, 80)),
    scripts: box.querySelectorAll("script").length,
    jsHref: all.filter((e) => /^\\s*(javascript|data):/i.test(e.getAttribute("href") || e.getAttribute("src") || ""))
      .length,
    codeLinks: [...box.querySelectorAll("code a, pre a")].map((a) => a.getAttribute("href")),
    codeText: [...box.querySelectorAll("code, pre")].map((c) => c.textContent).join(" "),
    userText: box.querySelector(".msg.me .bubble").textContent,
    aiLinks: [...box.querySelectorAll(".msg.ai .bubble a.clink")].map((a) => [a.textContent, a.getAttribute("href")]),
    logLinks: [...box.querySelectorAll(".log pre a.clink")].map((a) => a.getAttribute("href")),
    logText: [...box.querySelectorAll(".log pre")].map((p) => p.textContent).join("\\n"),
    overflow: document.documentElement.scrollWidth - innerWidth,
    longW: Math.max(...links.filter((a) => a.textContent.length > 500).map((a) => a.getBoundingClientRect().right)),
    alerts: window.__alerts, vw: innerWidth,
  };
}"""


def check(r: dict, where: str, long_url: str):
    hrefs = [x["href"] for x in r["links"]]
    assert all(h.startswith(("http://", "https://")) for h in hrefs), f"{where}: не http(s) {hrefs}"
    assert all(x["target"] == "_blank" and x["rel"] == "noopener noreferrer" and x["cls"] == "clink"
               for x in r["links"]), f"{where}: нет target/rel {r['links']}"
    assert not r["onattr"] and not r["scripts"] and not r["jsHref"] and not r["alerts"], f"{where}: XSS {r}"
    texts = [x["text"] for x in r["links"]]
    assert "https://dot.example/path" in texts, f"{where}: точка в ссылке {texts}"
    assert "https://paren.example/x" in texts and "https://wiki.example/A_(b)" in texts, f"{where}: скобки {texts}"
    assert "https://x.example/" in texts and not any("onmouseover" in h for h in hrefs), f"{where}: кавычка {texts}"
    assert "https://q.example/a" in texts, f"{where}: апостроф {texts}"
    # Человек сам набрал «&amp;» — так и показываем, разметкой это не становится; в ответе агента markdown их раскрыл.
    assert any(t.startswith("https://ent.example/?a=1&amp;b=2") for t in texts), f"{where}: сущности {texts}"
    assert "https://ent2.example/?a=1&b=2" in texts, f"{where}: сущности в ответе {texts}"
    assert long_url in texts, f"{where}: длинная ссылка"
    assert "javascript:alert(1)" in r["userText"] and "<script>alert(3)</script>" in r["userText"], \
        f"{where}: текст человека потерялся или стал разметкой"
    assert r["overflow"] <= 1 and r["longW"] <= r["vw"], f"{where}: длинная ссылка раздвинула страницу {r}"


def run(base: str):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for mode, q, sel in (("full", "open=@1", "#content"), ("simple", "simple=1", "#sFeed")):
            for dev, theme in (("phone", "light"), ("pc", "dark"), ("phone", "dark"), ("pc", "light")):
                where = f"{mode} {dev} {theme}"
                kw = {"viewport": {"width": 1366, "height": 860}} if dev == "pc" else \
                    {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
                ctx = br.new_context(**kw)
                ctx.grant_permissions(["clipboard-read", "clipboard-write"])
                pg = ctx.new_page()
                pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.goto(f"{base}{sep}{q}&theme={theme}&noscroll")
                pg.wait_for_selector(sel + " .msg", timeout=8000)
                # разметка (marked, DOMPurify) приходит с CDN после первого показа — до неё ответ простым текстом
                # и сущности не раскрыты; проверяем уже с разметкой (14.11: тест падал через раз)
                pg.wait_for_function("() => mdReady()", timeout=15000)
                if mode == "full":                   # демо-ответ: ссылка из текста — нажимаемая, из кода — нет
                    demo = pg.eval_on_selector_all(sel + " .msg.ai a.clink", "a => a.map((x) => x.href)")
                    assert any(h.endswith("/docs/MINI_APP.md") for h in demo), f"{where}: демо без ссылки {demo}"
                    assert any("pult.example.com" in h for h in demo), f"{where}: нет ссылки из блока кода {demo}"
                pg.evaluate(INJECT, [mode, USER, AI, TERM])
                r = pg.evaluate(CHECK, sel)
                check(r, where, LONG)
                hrefs = [x["href"] for x in r["links"]]
                assert "https://doc.example/guide" in hrefs and "https://bare.example/p?x=1&y=2" in hrefs, \
                    f"{where}: ссылки ответа {hrefs}"
                assert "curl https://code.example/block" in r["codeText"], f"{where}: текст кода {r['codeText'][:200]}"
                assert "`curl pult.example.su/api`" not in r["codeText"] and "curl pult.example.su/api" in r["codeText"]
                for h in ("https://code.example/inline", "https://code.example/block", "https://pult.example.su/api",
                          "https://longcode.example/7"):
                    assert h in r["codeLinks"], f"{where}: в коде нет ссылки {h} {r['codeLinks']}"
                assert not any("self.app" in h for h in r["codeLinks"]), f"{where}: self.app — не сайт"
                pairs = dict(r["aiLinks"])
                assert pairs.get("pult.example.su/x") == "https://pult.example.su/x", f"{where}: без схемы {pairs}"
                assert pairs.get("claude.ai/code/abc") == "https://claude.ai/code/abc", f"{where}: скобка {pairs}"
                assert not any(t in pairs for t in ("file.py", "1.2.3", "v2.0", "a.b", "mail.ru")), f"{where}: {pairs}"
                if mode == "full":                   # свёрнутый длинный код и «Терминал» — тоже со ссылками
                    assert "step 7: open https://longcode.example/7" in r["logText"], f"{where}: свёрнутый код"
                    assert "https://term.example/health" in r["logLinks"] and "https://pult.example.su/term" in \
                        r["logLinks"], f"{where}: терминал {r['logLinks']}"
                ai_text = pg.inner_text(sel + " .msg.ai .bubble")
                assert "плохая" in ai_text and "данные" in ai_text and "почта" in ai_text, f"{where}: подпись пропала"
                pg.wait_for_timeout(150)
                # Нажатие на ссылку в блоке кода — openLink (перехвачен), а не выделение или копирование.
                pg.evaluate("() => { window.__clicked = [];"
                            " window.openLink = (h) => (window.__clicked.push(h), true); }")
                ca = pg.locator(sel + ' .msg.ai .codebox pre a.clink[href="https://code.example/block"]')
                ca.scroll_into_view_if_needed()
                ca.click()
                assert pg.evaluate("window.__clicked") == ["https://code.example/block"], f"{where}: клик в коде"
                # «Копировать» блока — чистый текст, без разметки ссылки.
                pg.locator(sel + " .msg.ai .codebox .ccopy").first.click()
                pg.wait_for_timeout(200)
                clip = pg.evaluate("() => navigator.clipboard.readText().catch(() => '')")
                assert clip == "curl https://code.example/block", f"{where}: копирование блока {clip!r}"
                # Долгое нажатие на ссылку в коде — то же меню, адрес — в пункте «Копировать».
                box = ca.bounding_box()
                pg.mouse.move(box["x"] + 4, box["y"] + box["height"] / 2)
                pg.mouse.down()
                pg.wait_for_selector(".sheet-bg .sheet", timeout=3000)
                pg.mouse.up()
                items = pg.eval_on_selector_all(".sheet-bg .sheet button[data-i]", MENU)
                assert len(items) == 3 and "https://code.example/block" in items[1][0], f"{where}: меню в коде {items}"
                pg.click(".sheet-bg .sheet button[data-i='1']")
                pg.wait_for_timeout(200)
                clip = pg.evaluate("() => navigator.clipboard.readText().catch(() => '')")
                assert clip == "https://code.example/block", f"{where}: «Копировать ссылку» {clip!r}"
                pg.wait_for_selector(".sheet-bg", state="detached", timeout=3000)
                pg.wait_for_timeout(900)                 # меню не чаще раза в 0,8 с (linkMenuAt)
                # Долгое нажатие на ссылку — меню; «Поделиться» без navigator.share — копирует и говорит об этом.
                pg.evaluate("() => Object.defineProperty(navigator, 'share', { value: undefined, configurable: true })")
                a = pg.locator(sel + ' .msg.me a.clink[href="https://dot.example/path"]')
                a.scroll_into_view_if_needed()
                box = a.bounding_box()
                pg.mouse.move(box["x"] + 4, box["y"] + box["height"] / 2)
                pg.mouse.down()
                pg.wait_for_selector(".sheet-bg .sheet", timeout=3000)       # держим, пока не откроется меню
                pg.mouse.up()
                items = pg.eval_on_selector_all(".sheet-bg .sheet button[data-i]", MENU)
                assert len(items) == 3 and all(h >= 44 and svg for _, h, svg in items), f"{where}: меню {items}"
                assert "https://dot.example/path" in items[1][0], f"{where}: адрес в меню {items}"
                assert pg.get_attribute(".sheet-bg", "data-help") == "sheet.link"
                wide = pg.evaluate("document.documentElement.scrollWidth - innerWidth")
                assert wide <= 1, f"{where}: меню шире экрана"
                pg.click(".sheet-bg .sheet button[data-i='2']")
                pg.wait_for_selector(".toast", timeout=3000)
                toast = pg.evaluate("() => document.querySelector('.toast')?.textContent || ''")
                clip = pg.evaluate("() => navigator.clipboard.readText().catch(() => '')")
                assert clip == "https://dot.example/path", f"{where}: «Поделиться» не скопировал: {clip!r}"
                assert toast, f"{where}: нет сообщения о копировании"
                assert not pg.query_selector(".sheet-bg"), f"{where}: меню не закрылось"
                ctx.close()
        # Mini App: ссылка открывается через Telegram.WebApp.openLink, новая вкладка не появляется. Скрипт Telegram
        # подменён заглушкой; initData «появляется» после загрузки демо — иначе панель пошла бы входить через Telegram.
        ctx = br.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        ctx.route("https://telegram.org/js/telegram-web-app.js",
                  lambda r: r.fulfill(body=FAKE_TG, content_type="text/javascript"))
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"{base}{sep}open=@1&noscroll")
        pg.wait_for_selector("#content .msg.ai a.clink", timeout=8000)
        pg.evaluate("window.__tgOn = true")
        n = len(ctx.pages)
        pg.click('#content .msg.ai a.clink[href$="/docs/MINI_APP.md"]')
        pg.wait_for_timeout(400)
        opened = pg.evaluate("window.__opened")
        assert opened and opened[0].endswith("/docs/MINI_APP.md"), f"Telegram: openLink не вызван {opened}"
        assert len(ctx.pages) == n, "Telegram: открылась вкладка вместо openLink"
        ctx.close()
        br.close()
    assert not errs, f"ошибки в консоли: {errs[:5]}"


if __name__ == "__main__":
    run(sys.argv[1])
    print("ok")
