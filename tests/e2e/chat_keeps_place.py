"""Переписка не «пропадает» и открывается с конца (P0 09.11: «слушаю и иду по тексту, а текст пропал, осталось
последнее сообщение от 16:58»; «когда открывается — должна быть не начало переписки, а самый конец»).

Сценарий в демо (?demo&open=@1), телефон 390 и компьютер 1366:
- открыл сессию — последнее сообщение видно внизу;
- время сообщения — в поясе зрителя (как строка статуса): сегодня «ЧЧ:ММ», без даты;
- подгрузил ранние («Показать ранее»), прокрутил к ним, Claude закончил ход (busy → свободна, loadContent) и пришло
  новое сообщение — ранние на месте, место чтения не сдвинулось, внизу «новое ↓»;
- журнал окна сменился (другой id в rev) — переписка заново, с конца.

Запуск: /tmp/gp-venv/bin/python tests/e2e/chat_keeps_place.py "http://127.0.0.1:<порт>/?demo" [папка-снимков]
"""
import asyncio
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright

BASE, SHOTS = "http://127.0.0.1:8797/?demo", ""

LAST = """() => { const ms = [...document.querySelectorAll('#content .msg')]; const last = ms.at(-1);
  return {n: ms.length, lastIn: atEnd(8),     // лента в самом низу: под последним ответом — только его команды и статус
  when: last.querySelector('.when')?.innerText || ''} }"""


async def scenario(b, w):
    pg = await b.new_page(viewport={"width": w, "height": 844}, timezone_id="Asia/Yekaterinburg")
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.goto(BASE + "&open=@1&theme=light")
    await pg.wait_for_timeout(1500)
    await pg.evaluate("""async () => {     // длинная переписка: 70 сообщений, длинные ответы — есть что листать
      demoApi.h = Array.from({ length: 70 }, (_, i) => ({ i, role: i % 2 ? 'assistant' : 'user', ts: '2026-11-09 13:' +
        String(i % 60).padStart(2, '0'), text: (i % 2 ? 'Ответ ' : 'Вопрос ') + i + '. ' +
        'Длинный текст. '.repeat(i % 2 ? 40 : 3) }));
      hist = []; await loadContent(); }""")
    await pg.wait_for_timeout(800)
    st = await pg.evaluate(LAST)
    assert st["lastIn"], ("открыл — последнее сообщение не видно", w, st)
    when = r"(вчера )?\d\d:\d\d|\d\d\.\d\d(\.\d{4})? \d\d:\d\d"
    assert re.fullmatch(when, st["when"]), ("формат времени", st["when"])
    # ранние сообщения и чтение выше
    await pg.locator("#older").click()
    await pg.wait_for_timeout(600)
    n0 = await pg.evaluate("() => hist.length")
    assert n0 > 30, ("ранние не подгрузились", n0)
    await pg.mouse.move(195, 400)                  # человек сам тронул ленту (колесо / палец) — и читает 20-е сообщение
    await pg.mouse.wheel(0, -50)
    await pg.evaluate("() => document.querySelectorAll('#content .msg')[20].scrollIntoView()")
    await pg.wait_for_timeout(500)
    VIS = """() => { const t = SC.getBoundingClientRect().top;
      const ms = [...document.querySelectorAll('#content .msg')];
      const el = ms.find((e) => e.getBoundingClientRect().bottom > t + 1); if (!el) return ["нет", 0];
      return [el.innerText.slice(0, 40), Math.round(el.getBoundingClientRect().top)] }"""
    y0 = await pg.evaluate(VIS)
    # Claude закончил ход: новое сообщение в журнале и loadContent (как refresh при busy → свободна)
    await pg.evaluate("""async () => { demoApi.h.push({ i: demoApi.h.at(-1).i + 1, role: 'assistant',
      text: 'Новый ответ после хода', ts: new Date().toISOString().slice(0, 16).replace('T', ' ') });
      await loadContent(); }""")
    await pg.wait_for_timeout(600)
    n1, last = await pg.evaluate("() => [hist.length, hist.at(-1).text]")
    y1 = await pg.evaluate(VIS)
    assert n1 == n0 + 1 and last == "Новый ответ после хода", ("ранние сообщения пропали", n0, n1, last)
    assert y1[0] == y0[0] and abs(y1[1] - y0[1]) < 6, ("место чтения сдвинулось", y0, y1)
    assert await pg.evaluate("() => $('toBottom').classList.contains('new')"), "нет «новое ↓»"
    # время нового сообщения — сегодня, «ЧЧ:ММ» в поясе зрителя (Екатеринбург, UTC+5), а не сервера
    want = datetime.now(ZoneInfo("Asia/Yekaterinburg")).strftime("%H:%M")
    got = await pg.evaluate("() => [...document.querySelectorAll('#content .msg')].at(-1)"
                            ".querySelector('.when').innerText")
    assert got == want, ("время не в поясе зрителя", got, want)
    # другой журнал у окна — заново и с конца
    await pg.evaluate("""async () => { histRev = 'aaaaaaaa-1-1'; await loadContent(); }""")
    await pg.wait_for_timeout(800)
    st = await pg.evaluate(LAST)
    assert st["lastIn"] and await pg.evaluate("() => hist.length") <= 30, ("смена журнала: не с конца", st)
    if SHOTS:
        await pg.screenshot(path=f"{SHOTS}/chat-keeps-place-{w}.png")
    assert not errs, errs
    await pg.close()


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", headless=True)
        for w in (390, 1366):
            await scenario(b, w)
        await b.close()
    print("chat_keeps_place: ок (390, 1366)")


def run(base: str, shots: str = ""):
    global BASE, SHOTS
    BASE, SHOTS = base, shots
    asyncio.run(main())


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else BASE, sys.argv[2] if len(sys.argv) > 2 else "")
