"""Доставка вживую: настоящий сервер панели, свой tmux, подставное поле ввода Claude Code (``tests/fake_cc.py``).

    python tests/e2e/delivery_live.py [папка-для-снимков]

Ничего боевого не трогает: панель — отдельный процесс с временными HOME, GAS_PULT_DATA_DIR, GAS_PULT_CONFIG_DIR и своим
сервером tmux (``GAS_PULT_TMUX_SOCKET``, короткий сокет в /tmp); Telegram — подмена ``telegram.Api`` (запросы — в файл).

Сценарий (режим подставного окна — файл ``ctl``):
  (а) окно занято (идёт ход): «Отправить» из панели — текст встал в очередь, поле пустое; журнал доставок — без текста;
  (б) потерянный Enter: ход прерван, Claude Code вернул текст из очереди в поле ввода — перепроверка через 3 с жмёт
      Enter, текст отправлен, в журнале «redelivered», владельцу ничего не пишем;
  (в) застрял: после возврата фокус в панели агентов, Enter не доходит — через 30 с плашка «Не отправлено — текст
      в поле ввода» с кнопкой «Отправить» и одно сообщение владельцу с кнопкой; фокус вернулся — «Отправить» в панели
      отправляет текст, плашка уходит.
Ширина 390 и 1366, светлая и тёмная тема; снимки — в папку из аргумента.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAKE = ROOT / "tests" / "fake_cc.py"
TEXT1 = "Проверь сборку, пока идёт ход"
TEXT2 = "Полоса — проекты, вход только владельцу, «Выполнить» из фокуса убрать"
TEXT3 = "Третье: это сообщение застрянет, пока фокус в панели агентов"


def serve(root: Path, port: int):
    from gas_pult import telegram, webapp, webauth
    from gas_pult.config import Config

    tg = root / "telegram.jsonl"

    def fake_api(self, method, files=None, **params):        # Telegram: в файл, не в сеть
        with open(tg, "a") as f:
            f.write(json.dumps({"method": method, **params}, ensure_ascii=False) + "\n")
        return {"message_id": 1, "username": "e2e_bot", "ok": True}
    telegram.Api.__call__ = fake_api

    home = Path(os.environ["HOME"])
    claude = str(root / "bin" / "claude")
    cfg = Config(token="1:" + "e2e", owners=[1], session="main", claude=claude, host="e2e",
                 project_roots=[str(home / "projects")])
    p = webapp.Panel(cfg)
    assert p.tmux.socket == os.environ["GAS_PULT_TMUX_SOCKET"]
    p.people.accept(1)
    p.people.set_country(1, chosen="NL")
    d = home / "projects" / "shop"
    d.mkdir(parents=True, exist_ok=True)
    wid = p.tmux.new_window("shop", str(d), claude)
    for _ in range(50):
        if any(w["cmd"] == "claude" for w in p.tmux.windows() if w["id"] == wid):
            break
        time.sleep(0.2)
    srv = ThreadingHTTPServer(("127.0.0.1", port), webapp.handler(p))
    (root / "ready.json").write_text(json.dumps({"cookie": {"name": webauth.COOKIE, "value": p.auth.issue(1)},
                                                 "w": wid}))
    srv.serve_forever()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(root: Path, port: int):
    bin_dir, home = root / "bin", root / "home"
    bin_dir.mkdir()
    home.mkdir()
    shutil.copy(FAKE, bin_dir / "claude")                 # имя «claude» — пульт узнаёт окно Claude Code
    (bin_dir / "claude").chmod(0o755)
    (root / "ctl").write_text("normal\n")
    env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE")}
    env.update(HOME=str(home), PATH=f"{bin_dir}:{env.get('PATH', '/usr/bin:/bin')}", PYTHONPATH=str(ROOT / "src"),
               GAS_PULT_TMUX_SOCKET=str(root / "s"), GAS_PULT_DATA_DIR=str(root / "data"),
               GAS_PULT_CONFIG_DIR=str(root / "cfg"), SHELL="/bin/sh", FAKE_CC_CTL=str(root / "ctl"),
               FAKE_CC_LOG=str(root / "got.log"))
    env.pop("GAS_PULT_TOKEN", None)
    proc = subprocess.Popen([sys.executable, __file__, "--serve", str(root), str(port)], env=env, cwd=str(root))
    for _ in range(150):
        if (root / "ready.json").exists():
            return proc, json.loads((root / "ready.json").read_text())
        if proc.poll() is not None:
            raise RuntimeError("панель не запустилась")
        time.sleep(0.1)
    proc.kill()
    raise RuntimeError("панель не ответила за 15 с")


def run(shots: str = ""):
    from playwright.sync_api import sync_playwright

    root = Path(tempfile.mkdtemp(prefix="gp-", dir="/tmp"))
    assert len(str(root / "s")) < 100
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc, ready = start(root, port)
    wid = ready["w"]
    errs: list[str] = []

    def mode(m: str):
        (root / "ctl").write_text(m + "\n")

    def got() -> list[str]:
        f = root / "got.log"
        return f.read_text().splitlines() if f.exists() else []

    def journal() -> list[dict]:
        f = root / "data" / "sends.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def tg() -> list[dict]:
        f = root / "telegram.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def shot(pg, name):
        if shots:
            Path(shots).mkdir(parents=True, exist_ok=True)
            pg.screenshot(path=str(Path(shots) / f"delivery-{name}.png"))

    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(channel="chrome", headless=True)
            ctx = br.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            ctx.add_cookies([{**ready["cookie"], "url": base}])
            pg = ctx.new_page()
            pg.on("console", lambda m: m.type == "error" and "favicon.ico" not in m.location.get("url", "")
                  and errs.append(f"{m.text} @ {m.location.get('url', '')}"))
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/")
            pg.wait_for_function(f"sessions.some((s) => s.id === {json.dumps(wid)})", timeout=15000)
            pg.evaluate(f"openSession({json.dumps(wid)})")
            pg.wait_for_selector("#input", timeout=10000)

            # (а) занятое окно: текст в очереди, поле пустое
            mode("busy")
            pg.fill("#input", TEXT1)
            pg.click("#send")
            time.sleep(4)
            j = journal()
            assert j and j[-1]["src"] == "panel" and j[-1]["res"] == "sent" and j[-1]["after"] == "empty", j
            raw = (root / "data" / "sends.jsonl").read_text()
            assert TEXT1 not in raw and "Проверь" not in raw, "в журнале доставок оказался текст"
            assert os.stat(root / "data" / "sends.jsonl").st_mode & 0o777 == 0o600
            print("ok: (а) занятое окно — в очереди, журнал без текста, 0600", flush=True)

            # (б) ход прерван, текст вернулся в поле — перепроверка дожимает
            mode("return")
            pg.fill("#input", TEXT2)
            pg.click("#send")
            end = time.time() + 15
            while time.time() < end and TEXT2 not in got():
                time.sleep(0.3)
            assert TEXT2 in got(), ("перепроверка не дожала", journal())
            assert any(r["res"] == "redelivered" for r in journal()), journal()
            assert not [m for m in tg() if m["method"] == "sendMessage"], tg()
            print("ok: (б) текст вернулся в поле — через 3 с Enter ещё раз, отправлен; владельцу не писали", flush=True)

            # (в) застрял: фокус в панели агентов
            mode("return-panel")
            pg.fill("#input", TEXT3)
            pg.click("#send")
            pg.wait_for_selector("#act [data-actbtn=enter]", timeout=45000)
            assert "Не отправлено" in pg.inner_text("#act"), pg.inner_text("#act")
            assert TEXT3 not in got()
            msgs = [m for m in tg() if m["method"] == "sendMessage"]
            assert len(msgs) == 1 and "не отправлено" in msgs[0]["text"] and TEXT3 not in msgs[0]["text"], msgs
            btn = msgs[0]["reply_markup"]["inline_keyboard"][0][0]
            assert btn["callback_data"].startswith(f"rs:{wid}:"), btn
            for theme in ("light", "dark"):
                for wdt in (390, 1366):
                    pg.set_viewport_size({"width": wdt, "height": 844 if wdt == 390 else 860})
                    pg.evaluate(f"document.documentElement.dataset.theme = {json.dumps(theme)}")
                    pg.wait_for_timeout(200)
                    shot(pg, f"unsent-{wdt}-{theme}")
            print("ok: (в) через 30 с — плашка «Не отправлено» с кнопкой и одно сообщение владельцу", flush=True)
            mode("normal")                                 # фокус вернулся в поле ввода
            pg.click("#act [data-actbtn=enter]")
            end = time.time() + 10
            while time.time() < end and TEXT3 not in got():
                time.sleep(0.3)
            assert TEXT3 in got(), journal()
            pg.wait_for_function("!document.querySelector('#act [data-actbtn=enter]')", timeout=10000)
            print("ok: (в) «Отправить» в панели — текст ушёл, плашка исчезла", flush=True)
            assert not errs, errs
            br.close()
    finally:
        proc.kill()
        subprocess.run(["tmux", "-S", str(root / "s"), "kill-server"], capture_output=True)
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--serve"]:
        serve(Path(sys.argv[2]), int(sys.argv[3]))
    else:
        run(sys.argv[1] if len(sys.argv) > 1 else "")
        print("delivery_live ok")
