"""«Проекты» ведут в тот чат (ревью 09.11, п. 2): настоящий сервер панели на синтетических журналах, браузер.

    python tests/e2e/projects_live.py [папка-для-снимков]

Нужны Playwright и Chrome. Ничего боевого не трогает: панель — отдельный процесс с временными HOME,
GAS_PULT_DATA_DIR и GAS_PULT_CONFIG_DIR; tmux не нужен — окна подменены (одно окно «штаб»), журналы Claude Code —
синтетические, во временном HOME.

Журналы проекта «shtab»:
  A — окно «штаб»: первое сообщение «Да», Claude Code назвал чат «Keep alive в tmux» (запись ``ai-title``);
  B — завершённый «Harness»: последнее сообщение сутки назад, но файл дописан 5 минут назад (продолжили и закрыли);
  C — завершённый «Отчёт за неделю»: последнее сообщение 3 часа назад, файл — 6 часов назад;
  D — плановый запуск ``claude -p`` (``entrypoint`` = ``sdk-cli``) минуту назад — не чат проекта.

Проверки (390 и 1366, светлая и тёмная):
  (а) карточка проекта — имя окна и название чата: «штаб · «Keep alive в tmux»» (было «Да»);
  (б) «Активные»: карточка подписана именем окна «штаб», название чата — второй строкой; нажатие открывает это окно;
  (в) «Завершённые» — по последнему сообщению: C, затем B; запуска D нет (было D, B, C);
  (г) нажатие на первый завершённый — открывается переписка C.
На ``main`` до исправления падает на (а).
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
A, B, C, D = ("aaaaaaaa-0000-4000-8000-00000000000" + x for x in "abcd")


def iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def journal(d: Path, sid: str, entries: list[dict], said: float, mtime: float, entry: str = "cli"):
    now = time.time()
    rows = []
    for e in entries:
        if e.get("type") in ("user", "assistant"):
            e = {**e, "timestamp": iso(now - said), "entrypoint": entry, "sessionId": sid}
        rows.append(json.dumps(e, ensure_ascii=False))
    f = d / f"{sid}.jsonl"
    f.write_text("\n".join(rows) + "\n", encoding="utf-8")
    os.utime(f, (now - mtime, now - mtime))


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def ai(text):
    return {"type": "assistant", "message": {"role": "assistant", "stop_reason": "end_turn",
                                             "content": [{"type": "text", "text": text}]}}


class Wins:
    """Подмена tmux: одно окно Claude «штаб» в папке проекта, со своим журналом A."""
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

    def set_sid(self, wid, sid):
        for w in self.wins:
            if w["id"] == wid:
                w["sid"] = sid

    def all_spaces(self):
        return contextlib.nullcontext()

    @contextlib.contextmanager
    def scope(self, slug):
        yield

    def __getattr__(self, name):                         # прочее (ввод, клавиши) — ничего не делает
        return lambda *a, **k: ""


def serve(root: Path, port: int):
    from http.server import ThreadingHTTPServer

    from gas_pult import webapp, webauth
    from gas_pult.config import Config

    home = Path(os.environ["HOME"])
    shtab = home / "projects" / "shtab"
    shtab.mkdir(parents=True, exist_ok=True)
    from gas_pult import transcripts
    d = transcripts.project_dir(str(shtab))
    d.mkdir(parents=True, exist_ok=True)
    journal(d, A, [user("Да"), ai("Держу сессию живой."), {"type": "ai-title", "aiTitle": "Keep alive в tmux"}],
            said=120, mtime=30)
    journal(d, B, [user("Почини harness"), ai("Починил."), {"type": "ai-title", "aiTitle": "Harness: тесты"},
                   {"type": "permission-mode", "permissionMode": "default"}], said=86400, mtime=300)
    journal(d, C, [user("Собери отчёт за неделю"), ai("Готово."),
                   {"type": "ai-title", "aiTitle": "Отчёт за неделю"}], said=3 * 3600, mtime=6 * 3600)
    journal(d, D, [{"type": "queue-operation", "operation": "enqueue", "content": "Плановая задача штаба"},
                   user("Плановая задача штаба"), ai("Сделано по расписанию.")], said=60, mtime=60,
            entry="sdk-cli")

    cfg = Config(token="1:" + "e2e", owners=[1], session="main", host="e2e", project_roots=[str(home / "projects")])
    p = webapp.Panel(cfg)
    p.people.accept(1)
    p.people.set_country(1, chosen="NL")
    wins = Wins([{"id": "@1", "name": "штаб", "cmd": "claude", "mark": "claude", "path": str(shtab), "by": "",
                  "sid": A, "channel": False, "profile": "claude"}])
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
                pg.evaluate("if (view === 'session') back()")
                pg.wait_for_selector("#projectsView .card[data-proj]", timeout=15000)
                card = pg.locator("#projList .card[data-proj]", has_text="shtab").first
                meta = card.locator(".meta").first.inner_text()
                assert meta == "штаб · «Keep alive в tmux»", f"(а) карточка проекта: {meta!r}"
                if shots:
                    pg.screenshot(path=f"{shots}/a-projects-{tag}.png")
                card.click()
                pg.wait_for_selector("#projChats .card[data-id='@1']", timeout=5000)
                act = pg.locator("#projChats .card[data-id='@1']")
                name, sub = act.locator(".name").inner_text(), act.locator(".ctitle").inner_text()
                assert name == "штаб" and sub == "«Keep alive в tmux»", f"(б) активная: {name!r} / {sub!r}"
                if shots:
                    pg.screenshot(path=f"{shots}/b-active-{tag}.png")
                pg.click("#projSeg button[data-pt=done]")
                pg.wait_for_selector("#projChats .card[data-chat]", timeout=5000)
                order = pg.eval_on_selector_all("#projChats .card[data-chat] .name",
                                                "els => els.map((e) => e.textContent.trim())")
                assert order == ["Отчёт за неделю", "Harness: тесты"], f"(в) «Завершённые»: {order}"
                if shots:
                    pg.screenshot(path=f"{shots}/c-done-{tag}.png")
                pg.click("#projChats .card[data-chat] .name >> nth=0")
                pg.wait_for_selector(".chatv .bubble", timeout=5000)
                text = pg.inner_text(".chatv")
                assert "Собери отчёт за неделю" in text and "Почини harness" not in text, "(г) открылся не тот чат"
                pg.click(".chatv [data-close]")
                pg.click("#projSeg button[data-pt=active]")
                pg.click("#projChats .card[data-id='@1'] .name")
                pg.wait_for_function("view === 'session' && current === '@1'", timeout=5000)
                ctx.close()
                print(f"ok: {tag}", flush=True)
            br.close()
    finally:
        proc.kill()
        shutil.rmtree(root, ignore_errors=True)
    assert not errs, errs
    print("проекты вживую: ок — карточки ведут в тот чат, «Завершённые» по последнему сообщению (390/1366)")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--serve"]:
        serve(Path(sys.argv[2]), int(sys.argv[3]))
    else:
        run(sys.argv[1] if len(sys.argv) > 1 else "")
