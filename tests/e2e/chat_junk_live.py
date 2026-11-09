"""Лента без служебного мусора (ревью 09.11, п. 3): настоящий сервер панели на синтетическом журнале, браузер.

    python tests/e2e/chat_junk_live.py [папка-для-снимков]

Нужны Playwright и Chrome. Ничего боевого не трогает: панель — отдельный процесс с временными HOME,
GAS_PULT_DATA_DIR и GAS_PULT_CONFIG_DIR; tmux не нужен — окно подменено, журнал Claude Code — синтетический.

В журнале окна, как у штаба: уведомления фоновых агентов (``<task-notification>``) и письма других сессий
(``<agent-message>``) — через очередь Claude Code (``enqueue`` → ``dequeue``/``remove``), сообщение, взятое из
очереди следующим ходом, сообщение, прочитанное по ходу работы, ``/loop`` из очереди, сводка после ``/compact``.

Проверки (390 и 1366, светлая и тёмная, консоль без ошибок):
  (а) в ленте 11 пузырей: 3 сообщения человека и 8 ответов — ни одного с сырыми ``<task-notification>``,
      ``<agent-message>``, ``<command-…>``, ``<artifact-content…>``;
  (б) «в очереди» — ни у одного (всё взято), «прочитано по ходу работы» — у одного.
На ``main`` до исправления падает на (а): 15 пузырей (8 «человека»), из них 4 служебных и 3 «в очереди».
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SID = "bbbbbbbb-0000-4000-8000-000000000001"
NOTE = "<task-notification><task-id>x1</task-id><status>completed</status><summary>Агент закончил</summary>" \
       "</task-notification>"
LETTER = '<agent-message from="other">Готово, PR открыт</agent-message>'


def rows() -> list[dict]:
    t0 = time.time() - 3600

    def at(k):
        return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t0 + k * 60))

    def q(k, op, content=None):
        return {"type": "queue-operation", "operation": op, "timestamp": at(k),
                **({"content": content} if content is not None else {})}

    def u(k, text, **kw):
        return {"type": "user", "timestamp": at(k), "message": {"role": "user", "content": text}, **kw}

    def a(k, text):
        return {"type": "assistant", "timestamp": at(k),
                "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}

    def att(k, prompt, mode="prompt"):
        return {"type": "attachment", "timestamp": at(k),
                "attachment": {"type": "queued_command", "prompt": prompt, "commandMode": mode}}

    return [u(0, "Собери отчёт по продажам"), a(1, "Запустил двух агентов, жду."),
            q(2, "enqueue", LETTER), q(2, "enqueue", NOTE), q(3, "dequeue"),
            u(3, "Another Claude session sent a message", isMeta=True), a(4, "Письмо принял: PR открыт."),
            q(4, "dequeue"), u(4, NOTE), a(5, "Первый агент закончил."),
            q(6, "enqueue", "И добавь итог по месяцам"), q(7, "dequeue"), u(7, "И добавь итог по месяцам"),
            a(8, "Итог по месяцам добавлен."),
            q(9, "enqueue", "Без НДС"), q(10, "remove", "Без НДС"), att(10, "Без НДС"), a(11, "Пересчитал без НДС."),
            q(12, "enqueue", NOTE.replace("x1", "x2")), q(12, "remove", NOTE.replace("x1", "x2")),
            att(12, NOTE.replace("x1", "x2"), "task-notification"), a(13, "Второй агент тоже закончил."),
            q(14, "enqueue", "/loop 10m проверь почту"), q(14, "dequeue"),
            u(14, "<command-message>loop</command-message>\n<command-name>/loop</command-name>"),
            u(14, "текст навыка", isMeta=True), a(15, "Почту проверил — новых писем нет."),
            u(16, "<artifact-content-authored-by-others/>\nсводка", isCompactSummary=True,
              isVisibleInTranscriptOnly=True),
            a(17, "Продолжаю после сжатия.")]


class Wins:
    """Подмена tmux: одно окно Claude «отчёт» со своим журналом."""
    session = "main"
    scoped = None
    socket = ""

    def __init__(self, wins):
        self.wins = wins

    def windows(self):
        return [dict(w) for w in self.wins]

    def window(self, wid):
        return next((dict(w) for w in self.wins if w["id"] == wid), None)

    def screen(self, wid, n=25):
        return ["❯ "]

    def run(self, *a, **k):
        return ""

    def all_spaces(self):
        return contextlib.nullcontext()

    @contextlib.contextmanager
    def scope(self, slug):
        yield

    def __getattr__(self, name):                         # прочее (ввод, клавиши, метки) — ничего не делает
        return lambda *a, **k: ""


def serve(root: Path, port: int):
    from http.server import ThreadingHTTPServer

    from gas_pult import transcripts, webapp, webauth
    from gas_pult.config import Config

    home = Path(os.environ["HOME"])
    work = home / "projects" / "report"
    work.mkdir(parents=True, exist_ok=True)
    d = transcripts.project_dir(str(work))
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{SID}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows()))
    cfg = Config(token="1:" + "e2e", owners=[1], session="main", host="e2e", project_roots=[str(home / "projects")])
    p = webapp.Panel(cfg)
    p.people.accept(1)
    p.people.set_country(1, chosen="NL")
    wins = Wins([{"id": "@1", "name": "отчёт", "cmd": "claude", "mark": "claude", "path": str(work), "by": "",
                  "sid": SID, "live": True, "tag": SID, "channel": False, "profile": "claude"}])
    p.tmux = wins
    p.pult.tmux = wins
    p.need_claude = lambda: None
    srv = ThreadingHTTPServer(("127.0.0.1", port), webapp.handler(p))
    (root / "ready.json").write_text(json.dumps({"cookie": {"name": webauth.COOKIE, "value": p.auth.issue(1)}}))
    srv.serve_forever()


def free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(root: Path, port: int) -> tuple[subprocess.Popen, dict]:
    home = root / "home"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE", "GAS_PULT_TOKEN")}
    env.update(HOME=str(home), PYTHONPATH=str(ROOT / "src"), GAS_PULT_DATA_DIR=str(root / "data"),
               GAS_PULT_CONFIG_DIR=str(root / "cfg"), GAS_PULT_TMUX_SOCKET=str(root / "s"), TZ="Europe/Amsterdam")
    proc = subprocess.Popen([sys.executable, __file__, "--serve", str(root), str(port)], env=env, cwd=str(root))
    for _ in range(150):
        if (root / "ready.json").exists():
            return proc, json.loads((root / "ready.json").read_text())
        if proc.poll() is not None:
            raise RuntimeError("панель не запустилась")
        time.sleep(0.1)
    proc.kill()
    raise RuntimeError("панель не ответила за 15 с")


READY = "typeof meta !== 'undefined' && meta && typeof view !== 'undefined'"
JUNK = ("<task-notification", "<agent-message", "<command-", "<artifact-content", "task-id")


def run(shots: str = ""):
    from playwright.sync_api import sync_playwright

    root = Path(tempfile.mkdtemp(prefix="gp-", dir="/tmp"))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc, ready = start(root, port)
    errs: list[str] = []
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(channel="chrome", headless=True)
            for mobile, theme in ((True, "light"), (False, "dark"), (True, "dark"), (False, "light")):
                kw = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True} if mobile \
                    else {"viewport": {"width": 1366, "height": 860}}
                tag = f"{390 if mobile else 1366}-{theme}"
                ctx = br.new_context(**kw)
                ctx.add_cookies([{**ready["cookie"], "url": base}])
                pg = ctx.new_page()
                pg.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text
                      and errs.append(m.text))
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.goto(f"{base}/?theme={theme}")
                pg.wait_for_function(READY, timeout=15000)
                pg.wait_for_timeout(600)
                pg.evaluate("if (!(view === 'session' && current === '@1')) openSession('@1')")
                pg.wait_for_selector("#content.chat .msg", state="attached", timeout=8000)
                pg.wait_for_timeout(500)
                msgs = pg.eval_on_selector_all("#content.chat .msg", """els => els.map((e) => ({
                    me: e.classList.contains('me'), text: e.innerText, state: e.querySelector('.state')?.innerText || ''
                }))""")
                junk = [m["text"][:60] for m in msgs if any(j in m["text"] for j in JUNK)]
                waiting = [m["text"][:60] for m in msgs if "в очереди" in m["state"]]
                read = [m for m in msgs if "прочитано по ходу работы" in m["state"]]
                me = sum(m["me"] for m in msgs)
                print(f"{tag}: пузырей {len(msgs)} (человек {me}), служебных {len(junk)}, «в очереди» {len(waiting)}",
                      flush=True)
                if shots:
                    pg.screenshot(path=f"{shots}/chat-{tag}.png", full_page=True)
                assert not junk, f"(а) служебные пузыри: {junk}"
                assert not waiting, f"(б) вечные «в очереди»: {waiting}"
                assert (len(msgs), me, len(read)) == (11, 3, 1), f"(а) пузыри: {len(msgs)}, человек {me}, " \
                                                                 f"прочитано по ходу {len(read)}"
                ctx.close()
            br.close()
    finally:
        proc.kill()
        shutil.rmtree(root, ignore_errors=True)
    assert not errs, errs
    print("лента вживую: ок — без служебных пузырей и вечных «в очереди» (390/1366, светлая/тёмная)")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--serve"]:
        serve(Path(sys.argv[2]), int(sys.argv[3]))
    else:
        run(sys.argv[1] if len(sys.argv) > 1 else "")
