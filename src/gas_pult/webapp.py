"""Mini App: пульт внутри Telegram — те же возможности, что у бота, на одном экране.

Сессии и их статусы, последний ответ и экран, поле ввода (текст и диктовка клавиатуры), голосовое
(распознаётся и встаёт в поле — проверить перед отправкой), озвучка ответа, команды ⚡, выбор модели,
клавиши диалога 1/2/3/↑/↓/⏎/Esc, новая сессия и закрытие.

Сервер — стандартная библиотека. Запрос к ``/api`` пускается, если он подписан Telegram (``initData``) владельцем
из ``owners`` или пришёл из браузера с сессией, открытой одноразовым кодом из Telegram (``webauth``).
MCP-серверы Claude Code (``mcp``), ключи API и поставщики голоса (``providers``), «▶️ Выполнить» для команд
из последнего ответа: команду берёт сервер из ответа Claude (браузер присылает только её номер и отпечаток).

    gas-pult webapp [--port 8765] [--tunnel | --url https://…]

``--tunnel`` поднимает временный HTTPS-адрес Cloudflare (нужен ``cloudflared``), ``--url`` — постоянный адрес
перед этим сервером. В обоих случаях в меню бота у владельцев появляется кнопка «📱 Панель».
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources

from gas_pult import providers, transcripts, voice, webauth
from gas_pult.bot import BUSY, DIALOG, KEYS, PROMPTS, Pult
from gas_pult.commands import DANGER, TAIL, execute, extract
from gas_pult.config import Config
from gas_pult.mcp import PRESETS, Mcp
from gas_pult.telegram import Api, TelegramError
from gas_pult.voice import catalog

MAX_AGE = 24 * 3600                     # initData старше суток не принимаем
MAX_BODY = 16 << 20                     # голосовое до 16 МБ
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
CONTEXT = re.compile(r"left [\d.]+k? \((\d+)%\)")
AUDIO_EXT = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav"}


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


def brief(text: str, limit: int = 700) -> str:
    """«Кратко» для озвучки: первые абзацы до ~700 знаков — в наших ответах там вывод."""
    out = ""
    for para in re.split(r"\n\s*\n", text.strip()):
        if out and len(out) + len(para) > limit:
            break
        out += para + "\n\n"
    return out.strip()


class Panel:
    """Действия панели поверх того же tmux и state.json, что у бота (окна, активное, голос)."""

    def __init__(self, cfg: Config):
        self.cfg, self.pult = cfg, Pult(cfg)
        self.tmux = self.pult.tmux
        self.locks: dict[str, threading.Lock] = {}      # одно окно — одна вставка за раз
        self.auth = webauth.Auth(cfg.data / "web_sessions.json")
        self.mcp = Mcp()

    def lock(self, wid: str) -> threading.Lock:
        with self.pult.lock:
            return self.locks.setdefault(wid, threading.Lock())

    def window(self, wid: str) -> dict | None:
        w = self.tmux.window(wid)
        return w if w and w["cmd"] == "claude" else None

    def sessions(self) -> list[dict]:
        act, out = self.pult.state().get("active"), []
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

    def meta(self) -> dict:
        voices = catalog.installed()
        return {"host": self.cfg.host,
                "commands": [t for t, _ in self.pult.command_list()],
                "models": self.cfg.models,
                "keys": [{"label": t, "key": k} for t, k in KEYS],
                "projects": [self.pult.short(p) for p in self.pult.projects()],
                "voices": [{"id": v, "label": catalog.label(v)} for v in voices],
                "voice": self.voice(voices)}

    def voice(self, voices: list[str] | None = None) -> str | None:
        voices = catalog.installed() if voices is None else voices
        v = self.pult.state().get("voice")
        return v if v in voices else (voices[0] if voices else None)

    def login_start(self, ip: str, ua: str) -> str:
        rid, code = self.auth.start()
        text = (f"🔐 Вход в панель gas-pult из браузера\n\nКод: {code}\n\nДействует 5 минут. "
                f"Откуда: {ip or '?'} · {ua[:80] or 'браузер'}.\nЕсли входите не вы — просто не вводите код.")
        for chat in self.cfg.owners:
            self.pult.api("sendMessage", chat_id=chat, text=text)
        return rid

    # ---------- действия ----------
    def send(self, w: dict, text: str):
        with self.lock(w["id"]):
            self.pult.to_claude(w, text)

    def slash(self, w: dict, cmd: str) -> list[str]:
        with self.lock(w["id"]):
            self.pult.wait_ready(w["id"])
            self.tmux.type(w["id"], cmd)
            time.sleep(0.3)
            self.tmux.keys(w["id"], "Enter")
        time.sleep(2.5)
        return self.tmux.screen(w["id"], 40)

    def command(self, w: dict, i: int) -> dict:
        cmds = self.pult.command_list()
        if not 0 <= i < len(cmds):
            raise ValueError("команда устарела — обновите панель")
        cmd = cmds[i][1]
        if cmd == "models":
            return {"models": self.cfg.models}
        if cmd in PROMPTS:
            self.send(w, PROMPTS[cmd])
            return {"sent": True}
        if cmd.startswith("/"):
            return {"lines": self.slash(w, cmd)}
        self.send(w, cmd)
        return {"sent": True}

    def model(self, w: dict, name: str) -> list[str]:
        if name not in self.cfg.models and name != "":
            raise ValueError("такой модели нет в настройках (models)")
        return self.slash(w, f"/model {name}".strip())

    def key(self, w: dict, key: str) -> list[str]:
        if key not in {k for _, k in KEYS} and not re.fullmatch(r"[1-9]", key):   # цифры — пункты диалога
            raise ValueError("неизвестная клавиша")
        self.tmux.keys(w["id"], key)
        time.sleep(1)
        return self.tmux.screen(w["id"], 40)

    def new(self, i: int) -> str:
        dirs = self.pult.projects()
        if not 0 <= i < len(dirs):
            raise ValueError("список папок изменился — обновите панель")
        path = dirs[i]
        base = os.path.basename(path) if path != self.pult.home else "home"
        wid = self.tmux.new_window(f"{base}-{time.strftime('%H%M')}", path, self.cfg.claude)
        self.pult.set_state(active=wid)
        return wid

    def close(self, w: dict) -> str:
        with self.lock(w["id"]):
            self.tmux.keys(w["id"], "C-c")
            self.tmux.type(w["id"], "/exit")
            self.tmux.keys(w["id"], "Enter")
            time.sleep(4)
            if "Enter to confirm" in "\n".join(self.tmux.screen(w["id"])):
                self.tmux.keys(w["id"], "Escape")
                return "не закрыл: у сессии есть фоновые задачи — решите в самом окне"
            if (self.tmux.window(w["id"]) or w)["cmd"] == "claude":
                return "Claude не вышел (возможно, занят) — посмотрите экран"
            self.tmux.kill(w["id"])
            return "закрыто"

    # ---------- голос: локально или ElevenLabs ----------
    def voice_settings(self) -> dict:
        st, keys = self.pult.state(), providers.key_info()
        el = "elevenlabs" in keys
        return {"tts": st.get("tts_provider", "local") if el else "local",
                "stt": st.get("stt_provider", "local") if el else "local",
                "el_voice": st.get("el_voice"), "keys": keys, "local_voice": catalog.label(self.voice() or "")}

    def el_voices(self) -> list[dict]:
        key = providers.load_keys().get("elevenlabs")
        return providers.el_voices(key) if key else []

    def set_key(self, provider: str, key: str) -> list[dict]:
        if provider != "elevenlabs":
            raise ValueError("пока поддерживается только ElevenLabs")
        key = key.strip()
        if len(key) < 20:
            raise ValueError("это не похоже на ключ ElevenLabs — скопируйте его целиком")
        voices = providers.el_voices(key)                 # проверка: неверный ключ сюда не дойдёт
        providers.save_key(provider, key)
        if voices and not self.pult.state().get("el_voice"):
            self.pult.set_state(el_voice=voices[0]["id"])
        return voices

    def remove_key(self, provider: str):
        providers.save_key(provider, None)
        self.pult.set_state(tts_provider="local", stt_provider="local")

    def set_providers(self, b: dict):
        el = "elevenlabs" in providers.key_info()
        upd = {}
        for k in ("tts", "stt"):
            if k in b:
                if b[k] not in ("local", "elevenlabs") or (b[k] == "elevenlabs" and not el):
                    raise ValueError("сначала сохраните ключ ElevenLabs")
                upd[f"{k}_provider"] = b[k]
        if b.get("el_voice"):
            upd["el_voice"] = str(b["el_voice"])
        self.pult.set_state(**upd)

    def stt(self, data: bytes, ctype: str) -> str:
        ext = AUDIO_EXT.get(ctype.split(";")[0], "webm")
        if self.voice_settings()["stt"] == "elevenlabs":
            return providers.el_stt(providers.load_keys()["elevenlabs"], data, f"voice.{ext}")
        path = self.cfg.data / "inbox" / f"web-{uuid.uuid4().hex}.{ext}"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(data)
        try:
            return voice.transcribe(path, self.cfg.whisper_model)
        finally:
            path.unlink(missing_ok=True)                 # голос не храним

    def tts(self, w: dict, full: bool) -> bytes:
        text = transcripts.clean(transcripts.last_answer(w["path"]))
        text = (text if full else brief(text))[:3500]
        if not text:
            raise ValueError("нечего озвучивать")
        vs = self.voice_settings()
        if vs["tts"] == "elevenlabs":
            voice_id = vs["el_voice"] or next(iter(self.el_voices()), {}).get("id")
            if not voice_id:
                raise ValueError("в аккаунте ElevenLabs нет голосов")
            return providers.el_tts(providers.load_keys()["elevenlabs"], voice_id, text)
        v = self.voice()
        if not v:
            raise ValueError("голоса не установлены: gas-pult voices install irina")
        out = self.cfg.data / f"web-{uuid.uuid4().hex}.mp3"
        try:
            voice.synth(v, text, out)
            return out.read_bytes()
        finally:
            out.unlink(missing_ok=True)


    # ---------- ▶️ команды из последнего ответа ----------
    def commands(self, w: dict) -> list[dict]:
        out = []
        for i, cmd in enumerate(extract(transcripts.last_answer(w["path"]))):
            kind = self.pult.cmds.kind(cmd)
            out.append({"i": i, "cmd": cmd, "kind": kind, "danger": bool(DANGER.search(cmd)),
                        "sha": hashlib.sha256(cmd.encode()).hexdigest()[:12]})
        return out

    def run(self, w: dict, i: int, sha: str, confirmed: bool) -> dict:
        c = next((x for x in self.commands(w) if x["i"] == i and x["sha"] == sha), None)
        if not c:
            raise ValueError("ответ Claude изменился — обновите вкладку «Ответ»")
        if c["kind"] != "local":
            raise ValueError("эту команду выполняйте вручную: " +
                             ("sudo вне разрешённого списка" if c["kind"] == "sudo" else "она для другой машины"))
        if c["danger"] and not confirmed:
            return {"confirm": True}
        code, secs, out = execute(c["cmd"], w["path"])
        return {"code": code, "seconds": round(secs), "out": out[-TAIL:], "cut": len(out) > TAIL}


def handler(panel: Panel):
    page = resources.files("gas_pult").joinpath("web/index.html").read_bytes()

    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):     # без логов запросов: в них initData
            pass

        def reply(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8", cookie: str = ""):
            self.send_response(code)
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def json(self, data, code: int = 200):
            self.reply(code, json.dumps(data, ensure_ascii=False).encode())

        def via(self) -> str:
            """Кто спрашивает: «telegram» (подпись владельца), «browser» (сессия по коду) или ""."""
            user = verify(self.headers.get("X-Telegram-Init-Data", ""), panel.cfg.token)
            if user and user.get("id") in panel.cfg.owners:
                return "telegram"
            return "browser" if panel.auth.check(self.session()) else ""

        def session(self) -> str:
            return webauth.cookie_value(self.headers.get("Cookie", ""))

        def owner(self) -> bool:
            if self.via():
                return True
            self.json({"error": "нет доступа"}, 403)
            return False

        def client(self) -> tuple[str, str]:
            ip = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
            return ip, self.headers.get("User-Agent", "")

        def body(self) -> bytes:
            n = int(self.headers.get("Content-Length", 0))
            if n > MAX_BODY:
                raise ValueError("слишком большой запрос")
            return self.rfile.read(n)

        def win(self, wid) -> dict:
            if not (w := panel.window(str(wid or ""))):
                raise LookupError("окна уже нет")
            return w

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path in ("/", "/index.html"):
                return self.reply(200, page, "text/html; charset=utf-8")
            if not url.path.startswith("/api/"):
                return self.json({"error": "нет такой страницы"}, 404)
            if not self.owner():
                return None
            q = dict(urllib.parse.parse_qsl(url.query))
            self.dispatch(lambda: self.get(url.path, q))

        def get(self, path: str, q: dict):
            if path == "/api/sessions":
                return {"sessions": panel.sessions(), "host": panel.cfg.host}
            if path == "/api/meta":
                return {**panel.meta(), "via": self.via()}
            if path == "/api/mcp":
                return {"servers": panel.mcp.list(q.get("fresh") == "1"), "presets": PRESETS}
            if path == "/api/providers":
                vs = panel.voice_settings()
                return {**vs, "el_voices": panel.el_voices() if "elevenlabs" in vs["keys"] else []}
            w = self.win(q.get("w"))
            if path == "/api/last":
                return {"text": transcripts.last_answer(w["path"])}
            if path == "/api/screen":
                return {"lines": panel.tmux.screen(w["id"], 40)}
            if path == "/api/cmds":
                return {"cmds": panel.commands(w), "host": panel.cfg.host}
            if path == "/api/tts":
                return ("audio/mpeg", panel.tts(w, q.get("full") == "1"))
            raise KeyError

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/api/login/start":
                return self.dispatch(lambda: {"id": panel.login_start(*self.client())})
            if path == "/api/login/verify":
                return self.dispatch(self.login)
            if not path.startswith("/api/") or not self.owner():
                return None if path.startswith("/api/") else self.json({"error": "нет такой страницы"}, 404)
            self.dispatch(lambda: self.post(path))

        def login(self):
            b = json.loads(self.body() or b"{}")
            token = panel.auth.verify(str(b.get("id", "")), str(b.get("code", "")), self.client()[1])
            return ("cookie", webauth.set_cookie(token), {"ok": True})

        def post(self, path: str):
            if path == "/api/stt":
                return {"text": panel.stt(self.body(), self.headers.get("Content-Type", ""))}
            b = json.loads(self.body() or b"{}")
            if path == "/api/logout":
                panel.auth.logout(self.session())
                return ("cookie", webauth.set_cookie("", 0), {"ok": True})
            if path == "/api/mcp/add":
                return {"result": panel.mcp.add(str(b.get("preset", "")), str(b.get("name", "")),
                                                b.get("values") or {})}
            if path == "/api/mcp/remove":
                return {"result": panel.mcp.remove(str(b.get("name", "")))}
            if path == "/api/keys":
                return {"voices": panel.set_key(str(b.get("provider", "")), str(b.get("key", "")))}
            if path == "/api/keys/remove":
                panel.remove_key(str(b.get("provider", "")))
                return {"ok": True}
            if path == "/api/providers":
                panel.set_providers(b)
                return {"ok": True}
            if path == "/api/new":
                return {"id": panel.new(int(b.get("i", -1)))}
            w = self.win(b.get("w"))
            if path == "/api/send":
                text = str(b.get("text", "")).strip()
                if not text:
                    raise ValueError("пустое сообщение")
                panel.send(w, text)
                return {"ok": True}
            if path == "/api/active":
                panel.pult.set_state(active=w["id"])
                return {"ok": True}
            if path == "/api/command":
                return panel.command(w, int(b.get("i", -1)))
            if path == "/api/model":
                return {"lines": panel.model(w, str(b.get("name", "")))}
            if path == "/api/key":
                return {"lines": panel.key(w, str(b.get("key", "")))}
            if path == "/api/close":
                return {"result": panel.close(w)}
            if path == "/api/run":
                return panel.run(w, int(b.get("i", -1)), str(b.get("sha", "")), bool(b.get("confirmed")))
            raise KeyError

        def dispatch(self, fn):
            try:
                out = fn()
            except KeyError:
                return self.json({"error": "нет такого метода"}, 404)
            except LookupError as e:
                return self.json({"error": str(e)}, 404)
            except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired, providers.ProviderError) as e:
                return self.json({"error": str(e) or "ошибка"}, 400)
            if isinstance(out, tuple) and out[0] == "cookie":
                return self.reply(200, json.dumps(out[2], ensure_ascii=False).encode(), cookie=out[1])
            if isinstance(out, tuple):
                return self.reply(200, out[1], out[0])
            return self.json(out)

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
