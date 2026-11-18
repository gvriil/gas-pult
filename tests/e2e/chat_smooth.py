"""Плавный чат (GAS-29, владелец 18.11: «чтобы не было дёргания; сначала короткий кусок, потом перескакивает в
длинное — единая среда, даже если под капотом кусочками»).

Ход Claude дописывается в журнал по блоку, панель опрашивает его раз в 3 с — один ответ приходит кусками. Замер
по кадрам (requestAnimationFrame) в демо, телефон 390×844 и компьютер 1366×844:

  (а) внизу, ответ растёт кусками — скачок прокрутки за кадр, скачок низа последнего ответа на экране, пузырь —
      тот же узел (не пересоздаётся), лента доезжает до низа;
  (б) человек читает выше — место чтения не сдвигается ни на кадр, внизу «новое ↓»;
  (в) открытие сессии, разметка (marked) приходит с задержкой сети — ответ не перерисовывается из простого текста
      в разметку на глазах («короткий → длинный»);
  CLS (layout-shift) по всем сценариям.

Запуск: python tests/e2e/chat_smooth.py "http://127.0.0.1:<порт>/?demo" [--report]
"""
import asyncio
import json
import sys
from itertools import pairwise

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8797/?demo"

# кусок за куском — как блоки одного хода в журнале: абзац, список, код, таблица, вывод
CHUNKS = [
    "Смотрю, что происходит со сборкой.",
    "Нашёл причину: тест падает на пустом списке.\n\n- первое — список окон пуст;\n- второе — функция не ждёт tmux;"
    "\n- третье — проверка времени в UTC.",
    "Исправил так:\n\n```python\ndef windows(tmux):\n    out = tmux.run('list-windows')\n"
    "    return [w for w in out if w]\n```",
    "| файл | строк |\n|---|---|\n| tmuxctl.py | 12 |\n| webapp.py | 3 |",
    "Запустил тесты ещё раз. " + "Все проверки прошли, сборка зелёная. " * 6,
    "Что дальше:\n\n1. выложить;\n2. проверить на телефоне;\n3. записать в журнал.",
]

INSTR = """() => { const m = window.__m = { f: [], cls: 0, on: true, anchor: null };
  new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) m.cls += e.value; })
    .observe({ type: 'layout-shift' });
  const tick = () => { const ai = document.querySelectorAll('#content .msg.ai:not(.skel)'), last = ai[ai.length - 1];
    const r = last?.getBoundingClientRect();
    const a = m.anchor && document.querySelector(`#content .msg[data-i="${m.anchor}"]`);
    m.f.push({ st: Math.round(SC.scrollTop), h: r ? Math.round(r.height) : 0, top: r ? Math.round(r.top) : null,
      node: last ? (last.__n ||= Math.random()) : 0, a: a ? Math.round(a.getBoundingClientRect().top) : null });
    if (m.on) requestAnimationFrame(tick); };
  requestAnimationFrame(tick); }"""


def jumps(fr, key):
    xs = [f[key] for f in fr if f[key] is not None]
    return max((abs(b - a) for a, b in pairwise(xs)), default=0)


async def grow(pg, i):
    """Следующий кусок ответа — в журнал (демо), опрос журнала, как liveChat раз в 3 с."""
    await pg.evaluate("""(t) => { const m = demoApi.h.at(-1); m.text += '\\n\\n' + t; return liveChat(); }""",
                      CHUNKS[i])
    await pg.wait_for_timeout(900)


async def open_chat(b, w, slow_md=0):
    pg = await b.new_page(viewport={"width": w, "height": 844})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    if slow_md:                                      # медленная сеть к CDN разметки
        async def late(route):
            await asyncio.sleep(slow_md / 1000)
            await route.continue_()
        await pg.route("**/cdnjs.cloudflare.com/**", late)
    await pg.add_init_script(INSTR.replace("() => {", "addEventListener('DOMContentLoaded', () => {", 1)
                             .rstrip("}") + "}); ")
    await pg.goto(BASE + "&open=@1&theme=light")
    return pg, errs


async def at_bottom(b, w):
    pg, errs = await open_chat(b, w)
    await pg.wait_for_timeout(1500)
    # пока Claude пишет, команд из ответа нет — у демо они есть всегда (экран высотой с телефон), уберём
    await pg.evaluate("""async () => { window.renderCmds = async () => {};
      document.querySelector('#content .cmds')?.replaceChildren();
      demoApi.h.push({ i: demoApi.h.at(-1).i + 1, role: 'user', text: 'Почини сборку', ts: '2026-11-18 10:00' },
        { i: demoApi.h.at(-1).i + 2, role: 'assistant', text: 'Начинаю.', ts: '2026-11-18 10:00' });
      await liveChat(); }""")
    await pg.wait_for_timeout(1200)
    await pg.evaluate("() => $('toBottom').click()")   # человек внизу, у последнего ответа
    await pg.wait_for_timeout(1200)
    await pg.evaluate("() => { __m.f = []; __m.cls = 0; }")
    for i in range(len(CHUNKS)):
        await grow(pg, i)
    fr = await pg.evaluate("() => __m.f")
    cls = await pg.evaluate("() => __m.cls")
    end = await pg.evaluate("() => atEnd(30)")
    # длинный кусок (три экрана) за один опрос: лента не пролетает его — начало куска на экране, внизу «новое ↓»
    await pg.evaluate("""() => { __m.f = []; const m = demoApi.h.at(-1);
      m.text += '\\n\\nДЛИННЫЙ КУСОК. ' + 'Подробный разбор каждого шага сборки. '.repeat(260); return liveChat(); }""")
    await pg.wait_for_timeout(1500)
    big = await pg.evaluate("""() => { const p = [...document.querySelectorAll('#content .msg.ai .md p')]
      .find((e) => e.textContent.startsWith('ДЛИННЫЙ КУСОК'));
      const r = p.getBoundingClientRect(), s = SC.getBoundingClientRect();
      return { start_visible: r.top >= s.top && r.top < s.bottom, at_end: atEnd(30),
               new_badge: $('toBottom').classList.contains('new') && !$('toBottom').hidden } }""")
    big["scroll_jump"] = jumps(await pg.evaluate("() => __m.f"), "st")
    await pg.close()
    return {"scroll_jump": jumps(fr, "st"), "top_jump": jumps(fr, "top"), "height_jump": jumps(fr, "h"),
            "nodes": len({f["node"] for f in fr if f["node"]}), "cls": round(cls, 4), "at_end": end, "big": big,
            "errs": errs}


async def reading_above(b, w):
    pg, errs = await open_chat(b, w)
    await pg.wait_for_timeout(1500)
    await pg.evaluate("""async () => { demoApi.h.push({ i: demoApi.h.at(-1).i + 1, role: 'assistant', text: 'Начинаю.',
      ts: '2026-11-18 10:00' }); await liveChat(); }""")
    await pg.wait_for_timeout(800)
    await pg.mouse.move(195, 400)
    await pg.mouse.wheel(0, -60)                     # человек сам тронул ленту и читает выше
    await pg.wait_for_timeout(300)
    await pg.evaluate("""() => { const el = document.querySelectorAll('#content .msg')[1]; el.scrollIntoView();
      SC.scrollTop -= 40; __m.anchor = el.dataset.i; }""")
    await pg.wait_for_timeout(500)
    await pg.evaluate("() => { __m.f = []; __m.cls = 0; }")
    for i in range(len(CHUNKS)):
        await grow(pg, i)
    fr = await pg.evaluate("() => __m.f")
    cls = await pg.evaluate("() => __m.cls")
    new = await pg.evaluate("() => $('toBottom').classList.contains('new') && !$('toBottom').hidden")
    await pg.close()
    return {"anchor_jump": jumps(fr, "a"), "cls": round(cls, 4), "new_badge": new, "errs": errs}


async def open_slow_md(b, w):
    """Разметка приходит через 1,2 с после открытия: сколько раз последний ответ меняет высоту на глазах."""
    pg, errs = await open_chat(b, w, slow_md=1200)
    await pg.wait_for_timeout(3500)
    fr = await pg.evaluate("() => __m.f")
    cls = await pg.evaluate("() => __m.cls")
    md = await pg.evaluate("() => !!document.querySelector('#content .msg.ai .md ul, #content .msg.ai .md table')")
    await pg.close()
    hs = [f["h"] for f in fr if f["h"]]
    changes = sum(1 for a, b2 in pairwise(hs) if abs(b2 - a) > 4)
    return {"height_changes": changes, "height_jump": jumps([f for f in fr if f["h"]], "h"), "cls": round(cls, 4),
            "md": md, "errs": errs}


async def measure():
    out = {}
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", headless=True)
        for w in (390, 1366):
            out[w] = {"bottom": await at_bottom(b, w), "above": await reading_above(b, w),
                      "open": await open_slow_md(b, w)}
        await b.close()
    return out


def check(out):
    for w, r in out.items():
        bt, ab, op = r["bottom"], r["above"], r["open"]
        assert bt["nodes"] == 1, (w, "растущий ответ пересоздаётся", bt)
        assert bt["at_end"], (w, "лента не доехала до низа", bt)
        assert bt["scroll_jump"] <= 60 and bt["top_jump"] <= 60, (w, "скачок прокрутки за кадр", bt)
        assert bt["height_jump"] <= 60, (w, "ответ вырос рывком", bt)
        bg = bt["big"]
        assert bg["start_visible"] and not bg["at_end"] and bg["new_badge"], (w, "длинный кусок пролетел", bg)
        assert bg["scroll_jump"] <= 120, (w, "длинный кусок — скачок", bg)
        assert ab["anchor_jump"] <= 2 and ab["new_badge"], (w, "место чтения сдвинулось или нет «новое ↓»", ab)
        if op["md"]:                                 # без сети к CDN разметки нет вовсе — сравнивать нечего
            assert op["height_changes"] == 0, (w, "ответ перерисовался на глазах", op)
        for k in ("bottom", "above", "open"):
            assert r[k]["cls"] < 0.05, (w, k, "CLS", r[k])
            assert not r[k]["errs"], (w, k, r[k]["errs"])


def run(base: str, report: bool = False):
    global BASE
    BASE = base
    out = asyncio.run(measure())
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if not report:
        check(out)
        print("chat_smooth: ок (390, 1366)")
    return out


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else BASE, "--report" in sys.argv)
