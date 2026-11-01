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
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources

from gas_pult import models, providers, transcripts, voice, webauth
from gas_pult.bot import BUSY, DIALOG, KEYS, PROMPTS, Pult
from gas_pult.commands import DANGER, TAIL, Journal, execute, extract
from gas_pult.config import Config
from gas_pult.mcp import CONNECTORS, CONNECTORS_URL, PRESETS, Mcp
from gas_pult.openrouter import CALLBACK, OpenRouter
from gas_pult.people import People, allowed
from gas_pult.telegram import Api, TelegramError
from gas_pult.voice import catalog

MAX_AGE = 24 * 3600                     # initData старше суток не принимаем
MAX_BODY = 50 << 20                     # голосовое и файлы — до 50 МБ
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
EFFORTS = ("auto", "low", "medium", "high", "xhigh", "max")   # /effort <уровень> — Claude Code принимает аргументом
PANEL_KEYS = [("Ctrl+C", "C-c")]                     # прервать зависшую команду (в боте этой клавиши нет)
CONTEXT = re.compile(r"left [\d.]+k? \((\d+)%\)")
MODEL_LINE = re.compile(r"🤖 ([^·│\n]{2,40}?)\s*·")     # строка статуса: «🤖 Opus 5.5 · effort …»
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


AUTH_WITH = re.compile(r"Authenticating with (.+?)[….]*\s*$")
URL_TAIL = re.compile(r"^\s+([A-Za-z0-9%&=_.~:/?#+\-]+)\s*$")


def find_auth(lines: list[str]) -> dict | None:
    """Вход в MCP-сервис на экране Claude Code: название и полная ссылка (продолжение ссылки — следующими строками)."""
    service = next((m.group(1).strip() for line in lines if (m := AUTH_WITH.search(line))), None)
    for i, line in enumerate(lines):
        if m := re.search(r"https://\S*(authorize|oauth)\S*", line):
            url = m.group(0)
            for nxt in lines[i + 1:]:
                if not (t := URL_TAIL.match(nxt)):
                    break
                url += t.group(1)
            return {"service": service or "сервис", "url": url,
                    "paste": any("paste the URL" in x or "URL >" in x for x in lines)}
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
        self.auth = webauth.Auth(cfg.data / "web_sessions.json")
        self.mcp = Mcp()
        self.openrouter = OpenRouter()
        self.people = People(cfg.data / "people.json", cfg.owners)
        self.logins = webauth.TgLogins(cfg.data / "tg_logins.json")
        self._bot = ""
        self.public_url = ""                                 # адрес панели снаружи — для возврата после входа
        self.previews: dict[str, tuple[str, str]] = {}  # папка → (ревизия журнала, строка превью)
        self.sent: dict[str, tuple[threading.Event, float]] = {}     # id сообщения → (вставка, когда): без повторов
        self.journal = Journal(cfg.data / "commands-log.json")       # вкладка «Команды»: все команды всех сессий

    def window(self, wid: str) -> dict | None:
        w = self.tmux.window(wid)
        return w if w and w["cmd"] == "claude" else None

    def sessions(self) -> list[dict]:
        act, out = self.pult.state().get("active"), []
        for w in self.tmux.windows():
            def branch(path=w["path"]) -> str:
                return subprocess.run(["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"],
                                      capture_output=True, text=True).stdout.strip()
            if w.get("stopped"):                     # Claude завершился, в окне оболочка — «остановлена»
                out.append({"id": w["id"], "name": w["name"], "path": w["path"], "branch": branch(),
                            "status": "stopped", "context": None, "model": "", "active": w["id"] == act,
                            "channel": False, "profile": w["mark"] if w["mark"] in models.BY_ID else "claude",
                            "rev": "", "preview": ""})
                continue
            if w["cmd"] != "claude":
                continue
            if not w.get("mark"):                    # окна до метки: помечаем, чтобы и они потом стали «остановлена»
                self.tmux.run("set-option", "-w", "-t", w["id"], "@gas_pult", w.get("profile") or "claude")
            scr = "\n".join(self.tmux.screen(w["id"], 40))
            ctx, mdl = CONTEXT.search(scr), MODEL_LINE.search(scr)
            out.append({"id": w["id"], "name": w["name"], "path": w["path"], "branch": branch(),
                        "status": "dialog" if DIALOG.search(scr) else "busy" if BUSY.search(scr) else "idle",
                        "context": int(ctx.group(1)) if ctx else None,
                        "model": mdl.group(1).strip() if mdl else "",             # на чём реально работает сессия
                        "active": w["id"] == act, "channel": w["channel"], "profile": w.get("profile") or "claude",
                        "rev": (rev := transcripts.revision(w["path"])),   # изменился журнал → «новый ответ»
                        "preview": self.preview(w["path"], rev)})
        return out

    def preview(self, path: str, rev: str) -> str:
        """Строка о последнем шаге сессии; пересчитывается, только когда журнал изменился."""
        if self.previews.get(path, ("",))[0] != rev:
            self.previews[path] = (rev, transcripts.preview(path))
        return self.previews[path][1]

    def meta(self) -> dict:
        voices = catalog.installed()
        return {"host": self.cfg.host,
                "commands": [t for t, _ in self.pult.command_list()],
                "models": self.cfg.models,
                "keys": [{"label": t, "key": k} for t, k in KEYS + PANEL_KEYS],
                "profiles": models.public(self.pult.state()),
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
    def send(self, w: dict, text: str, mid: str = "") -> bool:
        """mid — id сообщения от браузера. Связь телефона рвётся, пока текст вставляется, и браузер повторяет запрос:
        с тем же id второй раз не вставляем (ответ True — «уже было»). Повтор, пришедший во время первой вставки, ждёт
        её исхода; не удалась — пробует сам."""
        if mid:
            with self.pult.lock:
                now = time.time()
                for k in [k for k, (_, t) in self.sent.items() if now - t > 900]:
                    del self.sent[k]
                ev, first = self.sent.get(mid, (None, 0))[0], mid not in self.sent
                if first:
                    ev = threading.Event()
                    self.sent[mid] = (ev, now)
            if not first:
                ev.wait(120)
                return True if mid in self.sent else self.send(w, text, mid)
        try:
            self.pult.to_claude(w, text)               # под замком окна — общим с ботом (flock)
        except Exception:
            with self.pult.lock:
                self.sent.pop(mid, None)
            raise
        finally:
            if mid:
                ev.set()
        return False

    def slash(self, w: dict, cmd: str) -> list[str]:
        return self.pult.run_slash(w["id"], cmd)

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

    def effort(self, w: dict, level: str) -> list[str]:
        if level not in EFFORTS:
            raise ValueError("такого уровня усилий нет")
        return self.slash(w, f"/effort {level}")

    def model(self, w: dict, name: str) -> list[str]:
        if name not in self.cfg.models and name != "":
            raise ValueError("такой модели нет в настройках (models)")
        return self.slash(w, f"/model {name}".strip())

    def key(self, w: dict, key: str) -> list[str]:
        if key not in {k for _, k in KEYS + PANEL_KEYS} and not re.fullmatch(r"[1-9]", key):   # цифры — пункты
            raise ValueError("неизвестная клавиша")
        self.tmux.keys(w["id"], key)
        time.sleep(1)
        return self.tmux.screen(w["id"], 40)

    def login_window(self) -> dict:
        """Окно для входа в MCP: активная сессия, если свободна, иначе любая свободная."""
        sess = [s for s in self.sessions() if s["status"] == "idle"]
        pick = next((s for s in sess if s["active"]), None) or (sess[0] if sess else None)
        if not pick:
            raise ValueError("нет свободной сессии Claude — откройте новую («Сессии» → ＋) и повторите")
        return self.window(pick["id"])

    def mcp_login(self, name: str) -> dict:
        """Запуск входа в MCP-сервис из панели: /mcp → сервер → Authenticate → ссылка входа с экрана."""
        w = self.login_window()
        self.slash(w, "/mcp")
        self.select(w, name)
        self.select(w, "Authenticate")
        for _ in range(15):
            lines = self.tmux.screen(w["id"], 60)
            if auth := find_auth(lines):
                return {"w": w["id"], "session": w["name"], **auth}
            time.sleep(1)
        self.tmux.keys(w["id"], "Escape")
        raise ValueError("Claude Code не показал ссылку входа — откройте сессию и проверьте «Экран»")

    def mcp_finish(self, w: dict, url: str, name: str) -> str:
        """Адрес страницы после входа (http://localhost…/callback?code=…) → в поле «URL >» Claude Code."""
        u = urllib.parse.urlparse(url.strip())
        if u.scheme != "http" or u.hostname not in ("localhost", "127.0.0.1") or "code=" not in u.query:
            raise ValueError("нужен адрес страницы после входа: начинается с http://localhost и содержит code=")
        self.send(w, url.strip())
        time.sleep(4)
        self.tmux.keys(w["id"], "Escape")              # закрыть меню /mcp, вернуться к вводу
        time.sleep(1)
        self.tmux.keys(w["id"], "Escape")
        status = next((s for s in self.mcp.list(fresh=True) if s["name"] == name), None)
        if status and status["ok"]:
            return f"✔ {name} подключён"
        return f"вход не подтвердился: {status['state'] if status else 'сервер не найден'} — попробуйте ещё раз"

    def select(self, w: dict, target: str, n: str = "", go: bool = True) -> list[str]:
        """Пункт меню: двигаем ❯ стрелками до строки с этим текстом (или номером n) и жмём Enter; go=False — только
        выделить. Цифрой не выбираем — не всякое меню Claude её принимает. Выше меню бывают прошлые сообщения с «❯»
        и «1. …» — номер ищем снизу (меню внизу экрана), а выделение — ближайшее к пункту."""
        target = target.strip()[:200]
        with self.pult.hold(w["id"]):
            for _ in range(30):
                lines = self.tmux.screen(w["id"], 60)
                if n.isdigit():
                    num = re.compile(rf"^\s*(❯\s*)?{int(n)}\.\s")
                    tgt = next((i for i in reversed(range(len(lines))) if num.match(lines[i])), None)
                    sel = next((i for i in reversed(range(len(lines))) if re.match(r"^\s*❯\s*\d+\.\s", lines[i])), None)
                else:
                    tgt = next((i for i, x in enumerate(lines) if target and target in x), None)
                    marks = [i for i, x in enumerate(lines) if "❯" in x]
                    sel = min(marks, key=lambda i: abs(i - tgt)) if marks and tgt is not None else None
                if sel is None or tgt is None:
                    raise ValueError("пункт не найден на экране — обновите экран")
                if sel == tgt:
                    if not go:
                        return lines[-40:]
                    self.tmux.keys(w["id"], "Enter")
                    time.sleep(1.5)
                    return self.tmux.screen(w["id"], 40)
                self.tmux.keys(w["id"], "Down" if tgt > sel else "Up")
                time.sleep(0.25)
        raise ValueError("не получилось выбрать этот пункт — выберите стрелками ↑ ↓ и ⏎")

    def new(self, i: int, profile: str = "") -> dict:
        dirs = self.pult.projects()
        if not 0 <= i < len(dirs):
            raise ValueError("список папок изменился — обновите панель")
        path = dirs[i]
        if w := self.pult.project_window(path):             # одно окно на проект: открываем уже работающее
            self.pult.set_state(active=w["id"])
            return {"id": w["id"], "existing": w["name"]}
        base = os.path.basename(path) if path != self.pult.home else "home"
        cmd = models.command(self.cfg.claude, profile, self.pult.state())
        wid = self.tmux.new_window(f"{base}-{time.strftime('%H%M')}", path, cmd, mark=profile or "claude")
        self.pult.set_state(active=wid)
        return {"id": wid}

    def revive(self, wid: str) -> dict:
        """Остановленная сессия: Claude заново в том же окне, у того же поставщика, с продолжением разговора."""
        w = self.tmux.window(wid)
        if not w or not w.get("stopped"):
            raise ValueError("сессия не остановлена — перезапускать нечего")
        profile = w["mark"] if w["mark"] in models.BY_ID else "claude"
        cmd = models.command(self.cfg.claude, profile, self.pult.state()) + " --continue"   # нет ключа — ошибка здесь
        self.tmux.respawn(wid, w["path"], cmd, mark=profile)
        self.pult.set_state(active=wid)
        return {"id": wid}

    def restart(self, w: dict, profile: str, keep: bool = True) -> dict:
        """Сменить поставщика: штатно закрыть окно и открыть в той же папке с другим профилем.

        ``keep`` — продолжить тот же разговор (``claude --continue``: новый поставщик получает всю переписку, контекст
        не теряется); иначе — чистый лист. Одно окно на проект, поэтому «последний разговор папки» — именно этот.
        """
        cmd = models.command(self.cfg.claude, profile, self.pult.state())    # нет ключа — ошибка до закрытия
        cmd += " --continue" if keep else ""
        result = self.close(w)
        if result != "закрыто":
            raise ValueError(result)
        wid = self.tmux.new_window(w["name"], w["path"], cmd, mark=profile or "claude")
        self.pult.set_state(active=wid)
        return {"id": wid}

    def close(self, w: dict) -> str:
        return {"background": "не закрыл: у сессии есть фоновые задачи — решите в самом окне",
                "busy": "Claude не вышел (возможно, занят) — посмотрите экран"}.get(self.pult.quit(w), "закрыто")

    def upload(self, name: str, data: bytes) -> str:
        """Файл из панели → inbox пульта; Claude получает путь (как файлы из чата бота)."""
        safe = re.sub(r"[^\w.\-]+", "_", os.path.basename(urllib.parse.unquote(name)))[-80:].lstrip(".") or "file"
        d = self.cfg.data / "inbox"
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = d / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}-{safe}"
        path.write_bytes(data)
        path.chmod(0o600)
        return str(path)

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

    def set_key(self, provider: str, key: str) -> dict:
        key = key.strip()
        if provider in {p.get("key") for p in models.PROFILES} - {None}:
            if len(key) < 16 or any(c.isspace() for c in key):
                raise ValueError(f"это не похоже на ключ {providers.NAMES[provider]} — скопируйте его целиком")
            checked = providers.check_model_key(provider, key)   # неверный ключ сюда не дойдёт
            providers.save_key(provider, key)
            return {"checked": checked}
        if provider != "elevenlabs":
            raise ValueError("такого поставщика нет")
        if len(key) < 20:
            raise ValueError("это не похоже на ключ ElevenLabs — скопируйте его целиком")
        voices = providers.el_voices(key)                 # проверка: неверный ключ сюда не дойдёт
        providers.save_key(provider, key)
        if voices and not self.pult.state().get("el_voice"):
            self.pult.set_state(el_voice=voices[0]["id"])
        return {"voices": voices}

    def remove_key(self, provider: str):
        providers.save_key(provider, None)
        if provider == "elevenlabs":                         # голос возвращается на сервер; модели не трогаем
            self.pult.set_state(tts_provider="local", stt_provider="local")

    def bot_username(self) -> str:
        if not self._bot:
            self._bot = self.pult.api("getMe")["username"]
        return self._bot

    def set_role(self, uid: int, role: str):
        p = next((x for x in self.people.list() if x["id"] == uid), None)
        if not p or p["role"] == "owner":
            raise ValueError("такого человека нет в списке")
        self.people.add(uid, role, p.get("name", ""), p.get("username", ""))

    def openrouter_done(self, code: str, state: str):
        """Возврат из OpenRouter после «Authorize»: код → ключ → secrets.json (как ключ, вставленный вручную)."""
        providers.save_key("openrouter", self.openrouter.finish(code, state))

    def openrouter_info(self) -> dict:
        key = providers.load_keys().get("openrouter")
        return {"key": False} if not key else {"key": True, **self.openrouter.info(key)}

    def set_models(self, profile: str, main: str, fast: str):
        self.pult.set_state(model_profiles=models.set_models(self.pult.state(), profile, main, fast))

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

    def message(self, w: dict, i: int | None) -> str:
        if i is None:
            return transcripts.last_answer(w["path"])
        items, _ = transcripts.history(w["path"], limit=1, before=i + 1)
        if not items or items[0]["i"] != i:
            raise ValueError("сообщение не найдено — обновите переписку")
        return items[0]["text"]

    def tts(self, w: dict, full: bool, msg: int | None = None) -> bytes:
        text = transcripts.clean(self.message(w, msg))
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
            raise ValueError("эту команду выполняйте вручную: " + {"sudo": "sudo вне разрешённого списка",
                             "tty": "она спросит пароль"}.get(c["kind"], "она для другой машины"))
        if c["danger"] and not confirmed:
            return {"confirm": True}
        code, secs, out = execute(c["cmd"], w["path"])
        return {"code": code, "seconds": round(secs), "out": out[-TAIL:], "cut": len(out) > TAIL}

    # ---------- вкладка «Команды»: все команды из ответов всех сессий (время — UTC, как в транскрипте) ----------
    def command_log(self, can_run: bool) -> dict:
        wins = [w for w in self.tmux.windows() if w["cmd"] == "claude"]
        self.journal.collect(wins, self.pult.cmds.kind)
        items = self.journal.items()
        if not can_run:
            items = [{k: v for k, v in c.items() if k != "path"} for c in items]   # папки сервера — только владельцу
        return {"items": items, "host": self.cfg.host}

    def command_run(self, cid: str, confirmed: bool) -> dict:
        c = self.journal.get(cid)
        if not c:
            raise LookupError("команды уже нет в списке")
        if c["kind"] != "local":
            raise ValueError("эту команду выполняйте вручную: " + {"sudo": "sudo вне разрешённого списка",
                             "tty": "она спросит пароль"}.get(c["kind"], "она для другой машины"))
        if c["danger"] and not confirmed:
            return {"confirm": True}
        code, secs, out = execute(c["cmd"], c["path"])
        done = {"code": code, "seconds": round(secs), "at": utc_now(), "by": "panel",
                "out": out[-TAIL:], "cut": len(out) > TAIL}
        return {"item": self.journal.mark(cid, done)}

    def command_mark(self, cid: str, done: bool) -> dict:
        mark = {"code": None, "seconds": 0, "at": utc_now(), "by": "hand", "out": ""}
        return {"item": self.journal.mark(cid, mark if done else None)}


def utc_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime())


# Сервис-воркер: только клик по уведомлению — открыть панель на нужной сессии. Ни кэша, ни фоновых запросов.
SW_JS = """self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const id = e.notification.data && e.notification.data.id;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((cs) => {
    if (cs[0]) { cs[0].focus(); cs[0].postMessage({ open: id }); return null; }
    return self.clients.openWindow("/");
  }));
});
"""

# Только владельцу: выполнение команд, закрытие сессий, ключи, интеграции, модели, люди.
OWNER_ONLY = {"/api/run", "/api/commands/run", "/api/commands/mark", "/api/close", "/api/restart", "/api/keys",
              "/api/keys/remove", "/api/providers",
              "/api/models", "/api/mcp", "/api/mcp/add", "/api/mcp/remove", "/api/mcp/login", "/api/mcp/finish",
              "/api/mcp/connected", "/api/openrouter/start", "/api/openrouter/info", "/api/openrouter/models",
              "/api/people", "/api/people/role", "/api/people/remove"}

# Страница после входа в OpenRouter: открывается во внешнем браузере, поэтому самодостаточная.
DONE_PAGE = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             '<title>gas-pult · OpenRouter</title><body style="margin:0;padding:48px 24px;font:16px/1.5 system-ui,'
             'sans-serif;background:#F6F5F0;color:#181816;text-align:center"><h1 style="font:600 22px Georgia,serif">'
             '{title}</h1><p style="color:#6E6C65">{text}</p></body>')


def handler(panel: Panel):
    page = resources.files("gas_pult").joinpath("web/index.html").read_bytes()
    build = hashlib.sha256(page).hexdigest()[:12]      # версия страницы: изменилась — панель предложит обновиться
    whatsnew = json.loads(resources.files("gas_pult").joinpath("web/whatsnew.json").read_text(encoding="utf-8"))

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

        def who(self) -> tuple[str, str | None, int | None]:
            """(откуда: «telegram» / «browser» / "", роль, Telegram ID). Роль — на каждый запрос, из people.json."""
            user = verify(self.headers.get("X-Telegram-Init-Data", ""), panel.cfg.token)
            if user and (role := panel.people.role(user.get("id"))):
                return "telegram", role, int(user["id"])
            uid = panel.auth.uid(self.session())
            if uid is None:
                return "", None, None
            role = "owner" if uid == webauth.LEGACY else panel.people.role(uid)
            return ("browser", role, uid) if role else ("", None, None)

        def via(self) -> str:
            return self.who()[0]

        def session(self) -> str:
            return webauth.cookie_value(self.headers.get("Cookie", ""))

        def permit(self, path: str, method: str) -> bool:
            """Не вошёл — 401 (панель покажет вход); не хватает роли — 403 с причиной."""
            role = self.who()[1]
            if not role:
                self.json({"error": "нужен вход"}, 401)
                return False
            need = ("owner" if path in OWNER_ONLY else
                    "member" if method == "POST" and path != "/api/logout" else "viewer")
            if allowed(role, need):
                return True
            why = "это может только владелец" if need == "owner" else "у вас доступ только на просмотр"
            self.json({"error": why}, 403)
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
                t = panel.tmux.window(str(wid or ""))
                raise LookupError("Claude в этой сессии остановлен — текст в командную строку не отправляю. "
                                  "Нажмите «Перезапустить»" if t and t.get("stopped") else "окна уже нет")
            return w

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path in ("/", "/index.html"):
                return self.reply(200, page, "text/html; charset=utf-8")
            if url.path == "/sw.js":                    # служебный файл уведомлений браузера (должен лежать в корне)
                return self.reply(200, SW_JS.encode(), "text/javascript; charset=utf-8")
            if url.path == CALLBACK:                    # возврат из OpenRouter: без входа, по одноразовому state
                return self.openrouter_back(dict(urllib.parse.parse_qsl(url.query)))
            if not url.path.startswith("/api/"):
                return self.json({"error": "нет такой страницы"}, 404)
            q = dict(urllib.parse.parse_qsl(url.query))
            if url.path == "/api/login/tg":              # браузер ждёт подтверждения из Telegram (по своему rid)
                return self.dispatch(lambda: self.tg_poll(q))
            if not self.permit(url.path, "GET"):
                return None
            self.dispatch(lambda: self.get(url.path, q))

        def get(self, path: str, q: dict):
            if path == "/api/sessions":
                return {"sessions": panel.sessions(), "host": panel.cfg.host, "build": build}
            if path == "/api/meta":
                kind, role, uid = self.who()
                return {**panel.meta(), "via": kind, "role": role, "uid": uid, "build": build, "whatsnew": whatsnew[:1]}
            if path == "/api/people":
                return {"people": panel.people.list()}
            if path == "/api/mcp":
                return {"servers": panel.mcp.list(q.get("fresh") == "1"), "presets": PRESETS,
                        "connectors": CONNECTORS, "connectors_url": CONNECTORS_URL}
            if path == "/api/mcp/connected":
                c = next((x for x in CONNECTORS if x["id"] == q.get("id")), None)
                if not c:
                    raise LookupError("нет такого сервиса")
                s = panel.mcp.connected(c["match"])
                return {"found": bool(s), "ok": bool(s and s["ok"]), "state": s["state"] if s else ""}
            if path == "/api/openrouter/info":
                return panel.openrouter_info()
            if path == "/api/openrouter/models":
                return {"models": panel.openrouter.models()}
            if path == "/api/providers":
                vs = panel.voice_settings()
                return {**vs, "el_voices": panel.el_voices() if "elevenlabs" in vs["keys"] else []}
            if path == "/api/commands":
                return panel.command_log(self.who()[1] == "owner")
            w = self.win(q.get("w"))
            if path == "/api/last":
                return {"text": transcripts.last_answer(w["path"])}
            if path == "/api/screen":
                lines = panel.tmux.screen(w["id"], 60)
                return {"lines": lines[-40:], "auth": find_auth(lines)}
            if path == "/api/hint":
                return {"hint": panel.tmux.hint(w["id"])}
            if path == "/api/cmds":
                return {"cmds": panel.commands(w), "host": panel.cfg.host}
            if path == "/api/tts":
                msg = int(q["msg"]) if q.get("msg", "").isdigit() else None
                return ("audio/mpeg", panel.tts(w, q.get("full") == "1", msg))
            if path == "/api/history":
                before = int(q["before"]) if q.get("before", "").isdigit() else None
                rev = transcripts.revision(w["path"])
                if before is None and q.get("rev") and q["rev"] == rev:
                    return {"same": True, "rev": rev}          # журнал не менялся — переписку не пересчитываем
                items, more = transcripts.history(w["path"], 30, before)
                return {"items": items, "more": more, "rev": rev}
            raise KeyError

        def openrouter_back(self, q: dict):
            try:
                panel.openrouter_done(q.get("code", ""), q.get("state", ""))
                title, text = "Ключ OpenRouter сохранён", "Вернитесь в панель — ключ на месте. Вкладку можно закрыть."
            except ValueError as e:
                title, text = "Не получилось", str(e)
            done = DONE_PAGE.format(title=escape(title), text=escape(text))
            self.reply(200, done.encode(), "text/html; charset=utf-8")

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/api/login/start":
                return self.dispatch(lambda: {"id": panel.login_start(*self.client())})
            if path == "/api/login/verify":
                return self.dispatch(self.login)
            if path == "/api/login/tg":
                return self.dispatch(self.tg_start)
            if not path.startswith("/api/") or not self.permit(path, "POST"):
                return None if path.startswith("/api/") else self.json({"error": "нет такой страницы"}, 404)
            self.dispatch(lambda: self.post(path))

        def tg_start(self):
            rid, nonce = panel.logins.start(*self.client())
            return {"id": rid, "link": f"https://t.me/{panel.bot_username()}?start=login_{nonce}",
                    "ttl": webauth.LOGIN_TTL}

        def tg_poll(self, q: dict):
            state, uid = panel.logins.poll(q.get("id", ""))
            if state == "ok":
                return ("cookie", webauth.set_cookie(panel.auth.issue(uid, self.client()[1])), {"state": "ok"})
            return {"state": state}

        def login(self):
            b = json.loads(self.body() or b"{}")
            token = panel.auth.verify(str(b.get("id", "")), str(b.get("code", "")), self.client()[1])
            return ("cookie", webauth.set_cookie(token), {"ok": True})

        def post(self, path: str):
            if path == "/api/upload":
                return {"path": panel.upload(self.headers.get("X-File-Name", "file"), self.body())}
            if path == "/api/stt":
                return {"text": panel.stt(self.body(), self.headers.get("Content-Type", ""))}
            b = json.loads(self.body() or b"{}")
            if path == "/api/commands/run":
                return panel.command_run(str(b.get("id", "")), bool(b.get("confirmed")))
            if path == "/api/commands/mark":
                return panel.command_mark(str(b.get("id", "")), b.get("done", True) is not False)
            if path == "/api/people/role":
                panel.set_role(int(b.get("id", 0)), str(b.get("role", "")))
                return {"people": panel.people.list()}
            if path == "/api/people/remove":
                panel.people.remove(int(b.get("id", 0)))
                return {"people": panel.people.list()}
            if path == "/api/logout":
                panel.auth.logout(self.session())
                return ("cookie", webauth.set_cookie("", 0), {"ok": True})
            if path == "/api/mcp/add":
                return {"result": panel.mcp.add(str(b.get("preset", "")), str(b.get("name", "")),
                                                b.get("values") or {})}
            if path == "/api/mcp/remove":
                return {"result": panel.mcp.remove(str(b.get("name", "")))}
            if path == "/api/keys":
                return panel.set_key(str(b.get("provider", "")), str(b.get("key", "")))
            if path == "/api/keys/remove":
                panel.remove_key(str(b.get("provider", "")))
                return {"ok": True}
            if path == "/api/providers":
                panel.set_providers(b)
                return {"ok": True}
            if path == "/api/mcp/login":
                return panel.mcp_login(str(b.get("name", "")))
            if path == "/api/new":
                return panel.new(int(b.get("i", -1)), str(b.get("profile", "")))
            if path == "/api/openrouter/start":
                base = panel.public_url or f"https://{self.headers.get('Host', '')}"
                return {"url": panel.openrouter.start(base)}
            if path == "/api/models":
                panel.set_models(str(b.get("profile", "")), str(b.get("main", "")), str(b.get("fast", "")))
                return {"profiles": models.public(panel.pult.state())}
            w = self.win(b.get("w"))
            if path == "/api/send":
                text = str(b.get("text", "")).strip()
                if not text:
                    raise ValueError("пустое сообщение")
                return {"ok": True, "dup": panel.send(w, text, str(b.get("id", ""))[:64])}
            if path == "/api/rename":
                return {"name": panel.tmux.rename(w["id"], str(b.get("name", "")))}
            if path == "/api/active":
                panel.pult.set_state(active=w["id"])
                return {"ok": True}
            if path == "/api/command":
                return panel.command(w, int(b.get("i", -1)))
            if path == "/api/model":
                return {"lines": panel.model(w, str(b.get("name", "")))}
            if path == "/api/effort":
                return {"lines": panel.effort(w, str(b.get("level", "")))}
            if path == "/api/key":
                return {"lines": panel.key(w, str(b.get("key", "")))}
            if path == "/api/select":
                go = b.get("go", True) is not False            # go: false — только выделить пункт
                return {"lines": panel.select(w, str(b.get("text", "")), str(b.get("n", "")), go)}
            if path == "/api/mcp/finish":
                return {"result": panel.mcp_finish(w, str(b.get("url", "")), str(b.get("name", "")))}
            if path == "/api/close":
                return {"result": panel.close(w)}
            if path == "/api/revive":
                return panel.revive(str(b.get("w", "")))
            if path == "/api/restart":
                return panel.restart(w, str(b.get("profile", "")), b.get("keep", True) is not False)
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
    panel = Panel(cfg)
    menu_for = cfg.owners + [p["id"] for p in panel.people.list() if p["role"] != "owner"]   # кнопка «📱 Панель»
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler(panel))
    proc = None
    if use_tunnel:
        proc, url = tunnel(port)
    if url:
        panel.public_url = url
        try:
            set_menu(Api(cfg.token), menu_for, url)
        except TelegramError as e:
            print("menu:", e, flush=True)
    print(f"gas-pult webapp: http://127.0.0.1:{port}" + (f" → {url} · кнопка «📱 Панель» в меню бота" if url else ""),
          flush=True)
    try:
        srv.serve_forever()
    finally:
        if proc:
            proc.terminate()
