"""Mini App: панель сессий внутри Telegram — статусы, последний ответ, экран, выбор активной сессии.

Сервер — стандартная библиотека. Каждый запрос к ``/api`` подписан Telegram (``initData``) и пускается только
для ``owners``. Команды отсюда не выполняются: панель только смотрит и переключает активное окно.

    gas-pult webapp [--port 8765] [--tunnel | --url https://…]

``--tunnel`` поднимает временный HTTPS-адрес Cloudflare (нужен ``cloudflared``), ``--url`` — постоянный адрес
перед этим сервером. В обоих случаях в меню бота у владельцев появляется кнопка «📱 Панель».
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources

from gas_pult import transcripts
from gas_pult.bot import BUSY, DIALOG
from gas_pult.config import Config
from gas_pult.telegram import Api, TelegramError
from gas_pult.tmux import Tmux

MAX_AGE = 24 * 3600                     # initData старше суток не принимаем
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
CONTEXT = re.compile(r"left [\d.]+k? \((\d+)%\)")


def verify(init_data: str, token: str, now: float | None = None) -> dict | None:
    """Проверка подписи Telegram Mini App: возвращает пользователя или None."""
    pairs = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    got = pairs.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    want = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not got or not hmac.compare_digest(got, want):
        return None
    if (now or time.time()) - int(pairs.get("auth_date", 0)) > MAX_AGE:
        return None
    try:
        return json.loads(pairs.get("user", ""))
    except ValueError:
        return None


class Panel:
    def __init__(self, cfg: Config):
        self.cfg, self.tmux, self.lock = cfg, Tmux(cfg.session), threading.Lock()
        self.state_file = cfg.data / "state.json"

    def active(self) -> str:
        try:
            return json.loads(self.state_file.read_text()).get("active", "")
        except (OSError, ValueError):
            return ""

    def set_active(self, wid: str):
        with self.lock:                  # тот же state.json, что у бота: остальные ключи не трогаем
            try:
                s = json.loads(self.state_file.read_text())
            except (OSError, ValueError):
                s = {}
            s["active"] = wid
            self.state_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.state_file.write_text(json.dumps(s))

    def sessions(self) -> list[dict]:
        act, out = self.active(), []
        for w in self.tmux.windows():
            if w["cmd"] != "claude":
                continue
            scr = "\n".join(self.tmux.screen(w["id"], 40))
            ctx = CONTEXT.search(scr)
            branch = subprocess.run(["git", "-C", w["path"], "rev-parse", "--abbrev-ref", "HEAD"],
                                    capture_output=True, text=True).stdout.strip()
            out.append({"id": w["id"], "name": w["name"], "path": w["path"], "branch": branch,
                        "status": "dialog" if DIALOG.search(scr) else "busy" if BUSY.search(scr) else "idle",
                        "context": int(ctx.group(1)) if ctx else None,
                        "active": w["id"] == act, "channel": w["channel"]})
        return out

    def window(self, wid: str) -> dict | None:
        w = self.tmux.window(wid)
        return w if w and w["cmd"] == "claude" else None


def handler(panel: Panel):
    page = resources.files("gas_pult").joinpath("web/index.html").read_bytes()

    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):     # без логов запросов: в них initData
            pass

        def reply(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def json(self, data, code: int = 200):
            self.reply(code, json.dumps(data, ensure_ascii=False).encode())

        def owner(self) -> bool:
            user = verify(self.headers.get("X-Telegram-Init-Data", ""), panel.cfg.token)
            if not user or user.get("id") not in panel.cfg.owners:
                self.json({"error": "нет доступа"}, 403)
                return False
            return True

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path in ("/", "/index.html"):
                return self.reply(200, page, "text/html; charset=utf-8")
            if not url.path.startswith("/api/") or not self.owner():
                return None if url.path.startswith("/api/") else self.json({"error": "нет такой страницы"}, 404)
            q = dict(urllib.parse.parse_qsl(url.query))
            if url.path == "/api/sessions":
                return self.json({"sessions": panel.sessions(), "host": panel.cfg.host})
            w = panel.window(q.get("w", ""))
            if not w:
                return self.json({"error": "окна уже нет"}, 404)
            if url.path == "/api/last":
                return self.json({"text": transcripts.last_answer(w["path"])})
            if url.path == "/api/screen":
                return self.json({"lines": panel.tmux.screen(w["id"], 40)})
            return self.json({"error": "нет такого метода"}, 404)

        def do_POST(self):
            if self.path != "/api/active" or not self.owner():
                return None if self.path == "/api/active" else self.json({"error": "нет такого метода"}, 404)
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 4096)))
            except ValueError:
                return self.json({"error": "плохой запрос"}, 400)
            if not panel.window(str(body.get("w", ""))):
                return self.json({"error": "окна уже нет"}, 404)
            panel.set_active(body["w"])
            return self.json({"ok": True})

    return H


def tunnel(port: int) -> tuple[subprocess.Popen, str]:
    """Временный HTTPS-адрес Cloudflare (без аккаунта); адрес меняется при каждом запуске."""
    p = subprocess.Popen(["cloudflared", "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    deadline = time.time() + 60
    for line in p.stderr:
        if m := TUNNEL_URL.search(line):
            threading.Thread(target=lambda: [None for _ in p.stderr], daemon=True).start()   # читаем дальше
            return p, m.group(0)
        if time.time() > deadline:
            break
    p.kill()
    raise RuntimeError("cloudflared не выдал адрес за минуту")


def set_menu(api: Api, owners: list[int], url: str):
    for chat in owners:
        api("setChatMenuButton", chat_id=chat,
            menu_button={"type": "web_app", "text": "📱 Панель", "web_app": {"url": url}})


def serve(cfg: Config, port: int = 8765, use_tunnel: bool = False, url: str | None = None):
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler(Panel(cfg)))
    proc = None
    if use_tunnel:
        proc, url = tunnel(port)
    if url:
        try:
            set_menu(Api(cfg.token), cfg.owners, url)
        except TelegramError as e:
            print("menu:", e, flush=True)
    print(f"gas-pult webapp: http://127.0.0.1:{port}" + (f" → {url} · кнопка «📱 Панель» в меню бота" if url else ""),
          flush=True)
    try:
        srv.serve_forever()
    finally:
        if proc:
            proc.terminate()
