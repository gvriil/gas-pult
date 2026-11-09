"""«Фокус» вживую (задача 41): настоящий сервер панели, настоящий tmux, два браузера — два устройства.

    python tests/e2e/focus_live.py [папка-для-снимков]

Нужны Playwright и Chrome. Ничего боевого не трогает: панель — в отдельном процессе с временными HOME,
GAS_PULT_DATA_DIR, GAS_PULT_CONFIG_DIR и своим сервером tmux (``GAS_PULT_TMUX_SOCKET``, короткий сокет в /tmp);
«Claude» в окнах — подставной скрипт ``claude`` (пишет ответ в журнал ``~/.claude/projects`` временного HOME),
Telegram — подмена ``telegram.Api`` (запросы пишутся в файл, в сеть не уходят). Вход владельца — сессия браузера
(``webauth``), как после входа кодом.

Сценарий:
  (а) владелец: меню сессии → «Фокус-ссылка» — ссылка ``…/#focus=<токен>``, «Отправить себе в Telegram» (подмена);
  (б) устройство A по ссылке без входа — только эта сессия; устройство B той же ссылкой — «Ссылка не действует»;
      с cookie фокуса API другой сессии, список людей, фокус-ссылки, ключи, создание сессии — 403;
  (в) на устройстве A: сообщение и ответ, файл, интеграции, уровень усилий, модель (перезапуск чата);
  (е) перезапуск сессии владельцем (смена поставщика) — ссылка переезжает на новое окно;
  (д) «Настройки» → «Фокус-ссылки» → «Отозвать» — устройство видит «Ссылка не действует» (410);
  (г) новая ссылка, «Завершить» на устройстве — «Сессия завершена», окно закрыто, повторное открытие — 410;
  (ж) токен не появляется ни в адресе запросов, ни в Referer (журнал запросов сервера — как журнал Caddy).
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

FAKE_CLAUDE = r'''#!/usr/bin/env python3
"""Подставной Claude Code для проверки панели: приглашение «❯», ответ — в журнал, как у настоящего."""
import datetime, json, os, re, signal, sys, uuid
args = sys.argv[1:]
if args[:2] == ["mcp", "list"]:
    print("Checking MCP server health...\n\ndocs-e2e: https://example.invalid/mcp (HTTP) - ✔ Connected")
    sys.exit(0)
if args[:1] == ["--version"]:
    print("2.0.0 (Claude Code)")
    sys.exit(0)
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "max"}))
    sys.exit(0)
if not sys.stdin.isatty():                       # прочие вызовы без терминала (не окно сессии) — сразу выйти
    sys.exit(0)
signal.signal(signal.SIGINT, signal.SIG_IGN)
model = args[args.index("--model") + 1] if "--model" in args else "default"
d = os.path.join(os.environ["HOME"], ".claude", "projects", re.sub(r"[^A-Za-z0-9]", "-", os.getcwd()))
os.makedirs(d, exist_ok=True)
old = sorted((os.path.join(d, f) for f in os.listdir(d) if f.endswith(".jsonl")), key=os.path.getmtime)
log = old[-1] if "--continue" in args and old else os.path.join(d, uuid.uuid4().hex + ".jsonl")
if "--session-id" in args:                       # свой журнал окна, как у настоящего (``open_in``)
    log = os.path.join(d, args[args.index("--session-id") + 1] + ".jsonl")
def put(kind, content):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    with open(log, "a") as f:
        f.write(json.dumps({"type": kind, "timestamp": ts, "message": {"role": kind, "content": content}}) + "\n")
print(f"fake claude · model {model}")
while True:
    sys.stdout.write("❯ ")
    sys.stdout.flush()
    line = sys.stdin.readline()
    if not line:
        break
    text = re.sub(r"\x1b\[20[01]~", "", line).strip()
    if not text:
        continue
    if text == "/exit":
        break
    if text.startswith("/effort"):
        print(f"Set effort level to {text.split()[-1]}")
        continue
    put("user", text)
    put("assistant", [{"type": "text", "text": f"Ответ ({model}): {text}"}])
    print(f"Ответ ({model}): {text}")
'''


def serve(root: Path, port: int):
    """Процесс панели (временный HOME уже в окружении): окна «shop» и «other», вход владельца, подмена Telegram."""
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
                 project_roots=[str(home / "projects")], models=["opus", "sonnet", "haiku"])
    p = webapp.Panel(cfg)
    assert p.tmux.socket == os.environ["GAS_PULT_TMUX_SOCKET"]
    p.people.accept(1)
    p.people.set_country(1, chosen="NL")
    wins = {}
    for name in ("shop", "other"):
        d = home / "projects" / name
        d.mkdir(parents=True, exist_ok=True)
        wins[name] = p.tmux.new_window(name, str(d), claude)
    for _ in range(50):
        if all(w["cmd"] == "claude" for w in p.tmux.windows() if w["id"] in wins.values()):
            break
        time.sleep(0.2)
    access = open(root / "access.log", "a")  # noqa: SIM115 — живёт, пока работает сервер

    class Logged(webapp.handler(p)):
        def log_request(self, code="-", size="-"):    # как журнал Caddy: адрес и заголовки, без cookie
            hs = {k: v for k, v in self.headers.items() if k.lower() not in ("cookie", "x-telegram-init-data")}
            access.write(json.dumps({"uri": self.path, "status": code, "headers": hs}, ensure_ascii=False) + "\n")
            access.flush()

    srv = ThreadingHTTPServer(("127.0.0.1", port), Logged)
    (root / "ready.json").write_text(json.dumps({"cookie": {"name": webauth.COOKIE, "value": p.auth.issue(1)},
                                                 "wins": wins}))
    srv.serve_forever()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(root: Path, port: int) -> tuple[subprocess.Popen, dict]:
    bin_dir, home = root / "bin", root / "home"
    bin_dir.mkdir()
    home.mkdir()
    (bin_dir / "claude").write_text(FAKE_CLAUDE)
    (bin_dir / "claude").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE")}
    env.update(HOME=str(home), PATH=f"{bin_dir}:{env.get('PATH', '/usr/bin:/bin')}", PYTHONPATH=str(ROOT / "src"),
               GAS_PULT_TMUX_SOCKET=str(root / "s"), GAS_PULT_DATA_DIR=str(root / "data"),
               GAS_PULT_CONFIG_DIR=str(root / "cfg"), SHELL="/bin/sh", TZ="Europe/Amsterdam")
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


FETCH = """async ([path, body]) => { const r = await fetch(path, { method: body ? "POST" : "GET",
  headers: { "X-Gp-Focus": "1", "Content-Type": "application/json" }, credentials: "same-origin",
  body: body ? JSON.stringify(body) : undefined }); return [r.status, await r.json().catch(() => ({}))]; }"""


def run(shots: str = ""):
    from playwright.sync_api import sync_playwright

    root = Path(tempfile.mkdtemp(prefix="gp-", dir="/tmp"))      # короткий путь: сокет tmux помещается
    assert len(str(root / "s")) < 100
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc, ready = start(root, port)
    shop, other = ready["wins"]["shop"], ready["wins"]["other"]
    errs: list[str] = []
    done: list[str] = []
    tokens: list[str] = []

    def log(step):
        done.append(step)
        print("ok:", step, flush=True)

    def tg_sent() -> list[dict]:
        f = root / "telegram.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(channel="chrome", headless=True)

            def device(mobile: bool):
                kw = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True} if mobile \
                    else {"viewport": {"width": 1366, "height": 860}}
                return br.new_context(**kw)

            def page(ctx, url):
                pg = ctx.new_page()
                pg.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text
                      and errs.append(m.text))   # 403/410 — ожидаемые ответы сервера
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.on("dialog", lambda d: d.accept())
                pg.goto(url)
                return pg

            def sheet_click(pg, text):
                pg.locator(".sheet button", has_text=text).first.click()

            # ---------- (а) владелец выпускает ссылку ----------
            owner = device(False)
            owner.add_cookies([{**ready["cookie"], "url": base}])
            po = page(owner, base + "/")
            po.wait_for_function(f"sessions.some((s) => s.id === {json.dumps(shop)})", timeout=15000)

            def new_link() -> str:
                po.evaluate("document.querySelectorAll('.sheet-bg').forEach((b) => b.remove())")
                po.evaluate(f"sessionSheet({json.dumps(shop)})")
                sheet_click(po, "Фокус-ссылка")
                po.wait_for_selector("#focusUrl")
                url = po.inner_text("#focusUrl")
                assert url.startswith(base + "/#focus="), url
                tokens.append(url.split("#focus=")[1])
                return url

            url = new_link()
            sheet_click(po, "Отправить себе в Telegram")
            po.wait_for_timeout(800)
            msg = [m for m in tg_sent() if m["method"] == "sendMessage"]
            assert msg and url in msg[-1]["text"] and msg[-1]["chat_id"] == 1, msg
            log("(а) владелец выпустил ссылку, «Отправить себе» ушло в подмену Telegram")
            po.evaluate("document.querySelectorAll('.sheet-bg').forEach((b) => b.remove())")

            # ---------- (б) устройство A по ссылке; устройство B — отказ ----------
            a = device(True)
            pa = page(a, url)
            pa.wait_for_selector("#session:not([hidden])", timeout=15000)
            assert pa.evaluate("document.body.classList.contains('focus')")
            assert "focus=" + tokens[0] not in pa.url, "токен остался в адресе страницы"
            assert pa.evaluate("sessions.map((s) => s.id)") == [shop]
            assert any(c["name"] == "gp_focus" for c in a.cookies()), "нет cookie фокуса"
            b = device(False)
            pb = page(b, url)
            pb.wait_for_selector("#focusEnd", timeout=10000)
            assert "другом устройстве" in pb.inner_text("#focusEnd")
            for path, body in ((f"/api/history?w={other}", None), (f"/api/screen?w={other}", None),
                               ("/api/send", {"w": other, "text": "чужое"}), ("/api/key", {"w": other, "key": "Enter"}),
                               ("/api/new", {"i": 0}), ("/api/people", None), ("/api/focus/list", None),
                               ("/api/focus/new", {"w": shop, "base": base}),
                               ("/api/keys", {"provider": "x", "key": "y"}),
                               ("/api/rename", {"w": shop, "name": "x"}), ("/api/active", {"w": shop}),
                               ("/api/mcp/add", {"preset": "http"}), ("/api/tty", None), ("/api/term", None)):
                code, d = pa.evaluate(FETCH, [path, body])
                assert code == 403 and d.get("code") == "focus_scope", (path, code, d)
            code, d = pa.evaluate(FETCH, ["/api/sessions", None])
            assert code == 200 and [x["id"] for x in d["sessions"]] == [shop], d
            code, d = pa.evaluate("""async () => { const r = await fetch("/api/sessions");
              return [r.status, await r.json()]; }""")
            assert code == 403, (code, d)                  # cookie фокуса без заголовка — не вход в пульт
            log("(б) устройство A — только эта сессия; B — «на другом устройстве»; чужое API — 403")

            # ---------- (в) чат, файл, интеграции, усилия, модель ----------
            if pa.locator("#focusEnd").count():
                raise AssertionError("устройство A погасло: " + pa.inner_text("#focusEnd"))
            pa.fill("#input", "привет из фокуса")
            pa.click("#send")
            pa.wait_for_selector("text=Ответ (default): привет из фокуса", timeout=20000)
            pa.set_input_files("#fFile", files=[{"name": "заметка.txt", "mimeType": "text/plain", "buffer": b"e2e"}])
            pa.wait_for_timeout(1500)
            pa.fill("#input", "посмотри файл")
            pa.click("#send")
            pa.wait_for_selector("text=/Ответ \\(default\\): .*inbox/", timeout=20000)
            inbox = list((root / "data" / "inbox").glob("*.txt"))
            assert inbox and inbox[0].read_bytes() == b"e2e", inbox
            pa.click("#menuBtn")
            pa.click("#menu [data-act=mcp]")
            pa.wait_for_selector(".sheet >> text=docs-e2e", timeout=15000)
            pa.evaluate("document.querySelectorAll('.sheet-bg').forEach((b) => b.remove())")
            code, d = pa.evaluate(FETCH, ["/api/effort", {"w": shop, "level": "high"}])
            assert code == 200 and any("effort level to high" in x for x in d["lines"]), d
            pa.click("#menuBtn")
            pa.click("#menu [data-act=models]")
            sheet_click(pa, "sonnet")
            pa.wait_for_function(f"current && current !== {json.dumps(shop)}", timeout=40000)
            moved = pa.evaluate("current")
            pa.fill("#input", "после смены модели")
            pa.click("#send")
            pa.wait_for_selector("text=Ответ (sonnet): после смены модели", timeout=20000)
            assert pa.locator("text=Ответ (default): привет из фокуса").count() >= 1, "разговор не продолжился"
            log(f"(в) чат, файл, интеграции, усилия, модель — работают; модель перезапустила окно {shop} → {moved}")

            # ---------- (е) перезапуск владельцем — ссылка за сессией ----------
            po.reload()
            po.wait_for_function(f"sessions.some((s) => s.id === {json.dumps(moved)})", timeout=15000)
            again = po.evaluate("""async (w) => { const r = await fetch("/api/restart", { method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ w, profile: "claude", keep: true }) });
              return (await r.json()).id; }""", moved)                 # как «Перезапустить» у владельца
            assert again and again != moved, again
            pa.wait_for_function(f"current === {json.dumps(again)}", timeout=20000)
            code, d = pa.evaluate(FETCH, ["/api/history?w=" + again, None])
            assert code == 200, (code, d)
            assert pa.evaluate(FETCH, ["/api/history?w=" + moved, None])[0] == 403
            pa.fill("#input", "после перезапуска")
            pa.click("#send")
            pa.wait_for_selector("text=Ответ (sonnet): после перезапуска", timeout=20000)
            log(f"(е) перезапуск владельцем: ссылка переехала {moved} → {again}, устройство A — в новом окне")

            # ---------- (д) «Отозвать» в настройках ----------
            po.evaluate("document.querySelectorAll('.sheet-bg').forEach((b) => b.remove()); focusList()")
            po.wait_for_selector(".sheet >> text=Действующие ссылки")
            sheet_click(po, "shop")
            po.wait_for_selector("text=Ссылка отозвана", timeout=5000)
            pa.wait_for_selector("#focusEnd", timeout=10000)
            assert "отозвал" in pa.inner_text("#focusEnd")
            code, d = pa.evaluate(FETCH, ["/api/sessions", None])
            assert code == 410 and d.get("code") == "focus_gone", (code, d)
            log("(д) «Отозвать» в «Фокус-ссылках»: устройство — «Ссылка не действует», API — 410")

            # ---------- (г) «Завершить» на устройстве ----------
            po.evaluate("document.querySelectorAll('.sheet-bg').forEach((b) => b.remove())")
            po.wait_for_function(f"sessions.some((s) => s.id === {json.dumps(again)})", timeout=15000)
            shop = again
            url2 = new_link()
            po.evaluate("document.querySelectorAll('.sheet-bg').forEach((b) => b.remove())")
            a2 = device(True)
            pc = page(a2, url2)
            pc.wait_for_selector("#session:not([hidden])", timeout=15000)
            pc.click("#menuBtn")
            pc.click("#menu [data-act=close]")
            pc.wait_for_selector("#focusEnd", timeout=40000)
            assert "Сессия завершена" in pc.inner_text("#focusEnd")
            code, d = pc.evaluate(FETCH, ["/api/sessions", None])
            assert code == 410, (code, d)
            pd = page(a2, url2)                            # повторное открытие на том же устройстве
            pd.wait_for_selector("#focusEnd", timeout=10000)
            assert "Сессия завершена" in pd.inner_text("#focusEnd")
            code, d = pd.evaluate("""async (t) => { const r = await fetch("/api/focus/open", { method: "POST",
              headers: { "X-Gp-Focus": "1", "Content-Type": "application/json" }, body: JSON.stringify({ token: t }) });
              return [r.status, await r.json()]; }""", tokens[-1])
            assert code == 410 and "Сессия завершена" in d["error"], (code, d)
            po.reload()
            po.wait_for_function("start.done || sessions.length", timeout=15000)
            po.wait_for_timeout(1500)
            assert shop not in po.evaluate("sessions.map((s) => s.id)"), "окно не закрыто"
            if shots:
                pd.screenshot(path=f"{shots}/focus-live-end.png")
            log("(г) «Завершить» на устройстве: окно закрыто, «Сессия завершена», повторное открытие — 410")

            # ---------- (ж) токены не в журнале запросов ----------
            raw = (root / "access.log").read_text()
            assert raw.count("\n") > 20, "журнал запросов пуст"
            for t in tokens:
                assert t not in raw, "токен фокус-ссылки попал в журнал запросов"
            assert "focus=" not in raw.replace('"/?focus"', "")
            log(f"(ж) {len(tokens)} токена нет в журнале запросов ({raw.count(chr(10))} строк: адрес и заголовки)")
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
    if sys.argv[1:2] == ["--serve"]:
        serve(Path(sys.argv[2]), int(sys.argv[3]))
    else:
        run(sys.argv[1] if len(sys.argv) > 1 else "")
        print("focus_live ok")
