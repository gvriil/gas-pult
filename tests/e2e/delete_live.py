"""«Удалить» сессию и чат вживую: настоящий сервер панели, свой tmux, подставной Claude, браузер.

    python tests/e2e/delete_live.py [папка-для-снимков]

Нужны Playwright и Chrome. Ничего боевого не трогает: панель — отдельный процесс с временными HOME,
GAS_PULT_DATA_DIR, GAS_PULT_CONFIG_DIR и своим сервером tmux (``GAS_PULT_TMUX_SOCKET``, короткий сокет в /tmp);
«Claude» — подставной скрипт (как в focus_live.py, но с ``--session-id``/``--resume``: журнал — ``<id>.jsonl``).

Сценарий (телефон 390 и компьютер 1366, светлая и тёмная тема):
  (а) остановленная сессия (Claude вышел, в окне оболочка) → «Завершить сессию» — окно закрыто (было: 404);
  (б) работающая сессия → «⋯» → «Удалить» → подтверждение → «Удалено»: окна нет, журнал — в корзине пульта,
      после обновления страницы карточка не возвращается и в «Завершённых» проекта чата нет;
  (в) завершённый чат проекта → «⋯» → «Удалить» — пропал из «Завершённых»;
  (г) перезапуск панели (та же папка данных) — удалённое не вернулось;
  (д) «Настройки» → «Корзина чатов» → нажать чат — «Вернуть»: журнал на месте, чат снова в «Завершённых».
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from focus_live import FAKE_CLAUDE, free_port  # noqa: E402

# журнал — по --session-id / --resume (как у настоящего Claude Code), иначе — новый uuid
FAKE = FAKE_CLAUDE.replace(
    'log = old[-1] if "--continue" in args and old else os.path.join(d, uuid.uuid4().hex + ".jsonl")',
    'sid = next((args[i + 1] for i, a in enumerate(args[:-1]) if a in ("--session-id", "--resume")), "")\n'
    'log = os.path.join(d, (sid or str(uuid.uuid4())) + ".jsonl") if sid or "--continue" not in args or not old '
    'else old[-1]')
assert FAKE != FAKE_CLAUDE


def serve(root: Path, port: int):
    """Панель: окна «shop» (работает), «other» (будет остановлена); завершённый чат «old» в журналах shop."""
    from gas_pult import telegram, transcripts, webapp, webauth
    from gas_pult.config import Config

    telegram.Api.__call__ = lambda self, method, files=None, **params: {"message_id": 1, "ok": True}
    home = Path(os.environ["HOME"])
    claude = str(root / "bin" / "claude")
    cfg = Config(token="1:" + "e2e", owners=[1], session="main", claude=claude, host="e2e",
                 project_roots=[str(home / "projects")])
    p = webapp.Panel(cfg)
    p.people.accept(1)
    p.people.set_country(1, chosen="NL")
    ready = root / "ready.json"
    if not ready.exists():                                   # первый запуск — окна и журналы; второй — только панель
        wins = {}
        for name in ("shop", "other"):
            d = home / "projects" / name
            d.mkdir(parents=True, exist_ok=True)
            sid = str(uuid.uuid4())
            wins[name] = p.tmux.new_window(name, str(d), f"{claude} --session-id {sid}", sid=sid)
            wins[name + "_sid"] = sid
        old = str(uuid.uuid4())
        jd = transcripts.project_dir(str(home / "projects" / "shop"))
        jd.mkdir(parents=True, exist_ok=True)
        (jd / f"{old}.jsonl").write_text(json.dumps({"type": "user", "timestamp": "2026-11-01T10:00:00.000Z",
                                                     "message": {"role": "user", "content": "Старый отчёт"}},
                                                    ensure_ascii=False) + "\n")
        os.utime(jd / f"{old}.jsonl", (time.time() - 86400, time.time() - 86400))
        wins["old_sid"] = old
        for _ in range(50):
            if all(w["cmd"] == "claude" for w in p.tmux.windows()):
                break
            time.sleep(0.2)
        data = {"cookie": {"name": webauth.COOKIE, "value": p.auth.issue(1)}, "wins": wins}
    else:
        data = {**json.loads(ready.read_text()), "cookie": {"name": webauth.COOKIE, "value": p.auth.issue(1)}}
    srv = ThreadingHTTPServer(("127.0.0.1", port), webapp.handler(p))
    (root / "ready.tmp").write_text(json.dumps(data))
    os.replace(root / "ready.tmp", ready)
    (root / "up").write_text(str(port))
    srv.serve_forever()


def start(root: Path, port: int) -> tuple[subprocess.Popen, dict]:
    bin_dir, home = root / "bin", root / "home"
    if not bin_dir.exists():
        bin_dir.mkdir()
        home.mkdir()
        (bin_dir / "claude").write_text(FAKE)
        (bin_dir / "claude").chmod(0o755)
    (root / "up").unlink(missing_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE")}
    env.update(HOME=str(home), PATH=f"{bin_dir}:{env.get('PATH', '/usr/bin:/bin')}", PYTHONPATH=str(ROOT / "src"),
               GAS_PULT_TMUX_SOCKET=str(root / "s"), GAS_PULT_DATA_DIR=str(root / "data"),
               GAS_PULT_CONFIG_DIR=str(root / "cfg"), SHELL="/bin/sh", TZ="Europe/Amsterdam")
    env.pop("GAS_PULT_TOKEN", None)
    proc = subprocess.Popen([sys.executable, __file__, "--serve", str(root), str(port)], env=env, cwd=str(root))
    for _ in range(150):
        if (root / "up").exists():
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
    w = ready["wins"]
    home = root / "home"
    jdir = home / ".claude" / "projects"
    tmux = ["tmux", "-S", str(root / "s")]
    errs: list[str] = []

    def log(step):
        print("ok:", step, flush=True)

    def journal(sid) -> list[Path]:
        return list(jdir.glob(f"*/{sid}.jsonl"))

    def windows() -> list[str]:
        out = subprocess.run([*tmux, "list-windows", "-a", "-F", "#{window_id}"], capture_output=True, text=True)
        return out.stdout.split()

    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(channel="chrome", headless=True)

            def page(width, theme):
                kw = {"viewport": {"width": width, "height": 844}}
                if width < 600:
                    kw.update(is_mobile=True, has_touch=True)
                ctx = br.new_context(**kw, color_scheme=theme)
                ctx.add_cookies([{**ready["cookie"], "url": base}])
                pg = ctx.new_page()
                pg.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text
                      and errs.append(m.text))
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.on("dialog", lambda d: d.accept())              # «Удалить …?» — да
                pg.goto(base + "/?theme=" + theme)
                ok = "typeof meta !== 'undefined' && meta && typeof sessions !== 'undefined'"
                pg.wait_for_function(ok, timeout=15000)
                return pg

            def shot(pg, name):
                if shots:
                    pg.screenshot(path=os.path.join(shots, name + ".png"))

            def sheet_click(pg, text):
                pg.locator(".sheet button", has_text=text).first.click()

            # (а) остановленная сессия → «Завершить сессию»
            pg = page(390, "light")
            pg.wait_for_function("sessions.length === 2", timeout=15000)
            subprocess.run([*tmux, "send-keys", "-t", w["other"], "/exit", "Enter"])
            pg.wait_for_function(f"sessions.some((s) => s.id === {json.dumps(w['other'])} && s.status === 'stopped')",
                                 timeout=15000)
            pg.evaluate(f"sessionSheet({json.dumps(w['other'])})")
            shot(pg, "a-menu-390-light")
            sheet_click(pg, "Завершить сессию")
            pg.wait_for_function(f"!sessions.some((s) => s.id === {json.dumps(w['other'])})", timeout=15000)
            assert w["other"] not in windows()
            log("(а) остановленная сессия: «Завершить» закрыло окно")

            # (б) работающая сессия → «Удалить»
            code = pg.evaluate("""async (w) => (await fetch("/api/send", { method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ w, text: "разговор для удаления" }) })).status""", w["shop"])
            assert code == 200, code
            for _ in range(50):
                if journal(w["shop_sid"]):
                    break
                time.sleep(0.2)
            assert journal(w["shop_sid"]), "подставной Claude не записал журнал"
            pg.evaluate(f"sessionSheet({json.dumps(w['shop'])})")
            sheet_click(pg, "Удалить")
            pg.wait_for_selector(".sheet h3:text('Удалено')", timeout=30000)
            shot(pg, "b-deleted-390-light")
            assert "в корзине" in pg.inner_text(".sheet")
            assert w["shop"] not in windows() and not journal(w["shop_sid"])
            trash = list((root / "data" / "trash" / "chats").glob(f"*__{w['shop_sid']}/{w['shop_sid']}.jsonl"))
            assert trash, "журнала нет в корзине"
            pg.reload()
            pg.wait_for_function("typeof meta !== 'undefined' && meta && projData", timeout=15000)
            assert not pg.evaluate(f"sessions.some((s) => s.id === {json.dumps(w['shop'])})")
            pid = pg.evaluate("projData.projects.find((p) => p.folder === 'shop').id")
            pg.evaluate(f"setMode('projects'); openProject({json.dumps(pid)}, 'done')")
            pg.wait_for_selector(".card.dchat", timeout=15000)
            assert pg.locator(f".card[data-chat='{w['shop_sid']}']").count() == 0
            assert pg.locator(f".card[data-chat='{w['old_sid']}']").count() == 1
            shot(pg, "b-done-390-light")
            log("(б) «Удалить»: окно закрыто, журнал в корзине, после обновления не вернулся")

            # (в) завершённый чат → «Удалить»
            pg.click(f".card[data-chat='{w['old_sid']}'] [data-chat-more]")
            sheet_click(pg, "Удалить")
            pg.wait_for_selector(".sheet h3:text('Удалено')", timeout=15000)
            pg.evaluate("document.querySelectorAll('.sheet-bg').forEach((b) => b.remove())")
            gone = f"!document.querySelector(\".card[data-chat='{w['old_sid']}']\")"
            pg.wait_for_function(gone, timeout=10000)
            assert not journal(w["old_sid"])
            log("(в) завершённый чат удалён из «Завершённых»")
            pg.context.close()

            # (г) перезапуск панели
            proc.terminate()
            proc.wait(10)
            proc, ready = start(root, port)
            pg = page(1366, "dark")
            pg.wait_for_function("projData", timeout=15000)
            pg.evaluate(f"setMode('projects'); openProject({json.dumps(pid)}, 'done')")
            pg.wait_for_selector("#projChats .empty, #projChats .card", timeout=15000)
            pg.wait_for_function("projDone", timeout=10000)
            assert pg.locator(".card.dchat").count() == 0
            log("(г) после перезапуска панели удалённое не вернулось")

            # (д) «Корзина чатов» → «Вернуть»
            pg.click("#settingsBtn")
            sheet_click(pg, "Корзина чатов")
            pg.wait_for_selector(".sheet >> text=Удалённые", timeout=10000)
            shot(pg, "d-trash-1366-dark")
            sheet_click(pg, "Старый отчёт")
            pg.wait_for_selector(".toast >> text=Вернул", timeout=10000)
            pg.wait_for_selector(f".card[data-chat='{w['old_sid']}']", timeout=10000)
            assert journal(w["old_sid"])
            shot(pg, "d-restored-1366-dark")
            log("(д) «Вернуть»: журнал на месте, чат снова в «Завершённых»")
            pg.context.close()
            for width, theme in ((390, "dark"), (1366, "light")):          # вид шторки «Корзина» — в обеих темах
                pg = page(width, theme)
                pg.evaluate("chatTrash()")
                pg.wait_for_selector(".sheet >> text=Корзина чатов", timeout=10000)
                shot(pg, f"e-trash-{width}-{theme}")
                pg.context.close()
            br.close()
        assert not errs, errs
        print("готово: удаление работает, ошибок в консоли нет")
    finally:
        proc.kill()
        subprocess.run([*tmux, "kill-server"], capture_output=True)
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--serve"]:
        serve(Path(sys.argv[2]), int(sys.argv[3]))
    else:
        run(sys.argv[1] if len(sys.argv) > 1 else "")
