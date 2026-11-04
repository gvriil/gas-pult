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

import base64
import contextlib
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from gas_pult import (
    ago,
    country,
    emailcode,
    fallback,
    helper,
    humanize,
    invites,
    models,
    modules,
    offer_report,
    offers,
    oidc,
    passkeys,
    personas,
    providers,
    scenarios,
    setup,
    spaces,
    tenants,
    terms,
    testers,
    transcripts,
    usage,
    voice,
    webauth,
)
from gas_pult.bot import BUSY, DIALOG, KEYS, PROMPTS, Pult
from gas_pult.commands import DANGER, FULL, TAIL, execute, extract
from gas_pult.config import Config
from gas_pult.mcp import CONNECTORS, CONNECTORS_URL, PRESETS, Mcp
from gas_pult.openrouter import CALLBACK, OpenRouter
from gas_pult.people import TITLES, People, allowed
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
STT_TIMEOUT = 85                                          # с; панель ждёт ответа 90 с
STT_EMPTY = "Ничего не расслышал — попробуйте ещё раз"   # распознавание вернуло пустой текст


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
        # окна владельца и демо-пространств (spaces.py): запрос тестировщика ограничен его пространством (scope)
        self.pult.tmux = spaces.Routed(self.pult.tmux)
        self.tmux = self.pult.tmux
        self.auth = webauth.Auth(cfg.data / "web_sessions.json")
        self.mcp = Mcp()
        self.openrouter = OpenRouter()
        self.people = People(cfg.data / "people.json", cfg.owners)
        self.team = personas.Team(cfg.data / "team.json")      # потолок возможностей сотрудников (экран «Команда»)
        self.logins = webauth.TgLogins(cfg.data / "tg_logins.json")
        self.email = emailcode.Service(cfg.email, self.people, cfg.data / "email_codes.json")   # вход по почте
        self.keys = passkeys.Passkeys(cfg.passkeys, self.people, cfg.data / "passkeys.json")    # Face ID / ключ
        self.oidc = oidc.Oidc({"google": cfg.google, "yandex": cfg.yandex}, self.people, cfg.data / "oidc.json",
                              base=lambda: self.public_url)                                # Google, Яндекс ID
        self._bot = ""
        self.public_url = ""                                 # адрес панели снаружи — для возврата после входа
        self.previews: dict[str, tuple[str, str]] = {}  # папка → (ревизия журнала, строка превью)
        self.model_cache: dict[tuple, tuple[str, str]] = {}  # (папка, папка Claude) → (ревизия, модель ответа)
        self.mod_sections: tuple[float, dict] = (0.0, {})    # модуль → разделы чата (sections_of)
        self.sent: dict[str, tuple[threading.Event, float]] = {}     # id сообщения → (вставка, когда): без повторов
        self.wins: tuple[float, dict] = (0.0, {})                   # окна Claude для строки статуса (кэш 3 с)
        self.screens: dict[str, tuple[float, dict]] = {}             # окно → (когда, экран): не чаще раза в 2 с
        self.journal = self.pult.journal                             # вкладка «Команды»: все команды всех сессий
        self.login = self.pult.login                                 # вход в Claude Code (setup.py) — общий с ботом
        self._setup: tuple[float, dict] = (0, {})
        self.geo = country.GeoIP(cfg.data / "geoip")                 # страна по IP — локальная база db-ip lite
        self.ip_seen: dict[int, tuple[float, str]] = {}              # кого и когда сверяли по IP (только в памяти)
        self.offer_demos = offers.Demos()                            # демо-сессии страниц предложений (в памяти)
        self.offer_misses = offers.Misses()                          # перебор кодов предложений — по IP
        self.offer_tg = offers.TgDemos(cfg.data / "offer_tg.json")   # «Попробовать в Telegram» — токены для бота
        # дежурный помощник «? Подсказать» (helper.py): карта экранов, ответы без модели
        self.helper = helper.Helper(cfg.data)
        self.help_anon = helper.Rate(30, 600)                        # помощник на экране входа — по IP
        self._mod_ids: tuple[float, frozenset] = (0.0, frozenset())
        self.owner_seen: dict[str, float] = {}                       # окно пространства → когда владелец подключился
        self.help_calls: dict[str, float] = {}                       # окно → когда тестировщик звал на помощь

    def setup_status(self, fresh: bool = False) -> dict:
        """Готов ли Claude Code (для мастера на главной); ``claude auth status`` — не чаще раза в 20 с."""
        if fresh or time.time() - self._setup[0] > 20:
            self._setup = (time.time(), setup.status(self.cfg.claude))
        login = self.login.read()
        return {**self._setup[1], "login": login if login.get("w") else None}

    def need_claude(self):
        if not setup.installed(self.cfg.claude):
            raise ValueError("Claude Code на сервере не установлен — главная → «Claude не готов» → «Инструкция»")

    def window(self, wid: str) -> dict | None:
        w = self.tmux.window(wid)
        return w if w and w["cmd"] == "claude" else None

    def sessions(self, pool: str | None = "owner") -> list[dict]:
        """``pool`` — чей расход показывать на карточках (``cost``): «owner» или ID участника; None — ничей."""
        st = self.pult.state()
        act, out, paused = st.get("active"), [], st.get("cost_paused") or {}
        for w in self.tmux.windows():
            def branch(path=w["path"]) -> str:
                return subprocess.run(["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"],
                                      capture_output=True, text=True).stdout.strip()
            if w.get("stopped"):                     # Claude завершился, в окне оболочка — «остановлена»
                out.append({"id": w["id"], "name": w["name"], "path": w["path"], "branch": branch(),
                            "status": "stopped", "context": None, "model": "", "active": w["id"] == act,
                            "channel": False, "profile": w["mark"] if w["mark"] in models.BY_ID else "claude",
                            "rev": "", "preview": "", "cost_paused": False, "cost": None,
                            **ago.stamps(self.pult.acts.status(w["path"], self.pult.home_of(w)))})
                continue
            if w["cmd"] != "claude":
                continue
            if not w.get("mark"):                    # окна до метки: помечаем, чтобы и они потом стали «остановлена»
                self.tmux.run("set-option", "-w", "-t", w["id"], "@gas_pult", w.get("profile") or "claude")
            lines = self.tmux.screen(w["id"], 40)
            scr = "\n".join(lines)
            home = self.pult.home_of(w)                       # папка Claude того, кто открыл окно
            # когда менялась (ago.py): последний ход в журнале или смена экрана; ответ агента, ваше сообщение
            when = ago.stamps(self.pult.acts.status(w["path"], home), self.pult.changes.look(w["id"], lines))
            ctx, mdl, rev = CONTEXT.search(scr), MODEL_LINE.search(scr), transcripts.revision(w["path"], home)
            out.append({"id": w["id"], "name": w["name"], "path": w["path"], "branch": branch(),
                        "status": "dialog" if DIALOG.search(scr) else "busy" if BUSY.search(scr) else "idle",
                        "context": int(ctx.group(1)) if ctx else None,
                        # на чём работает сессия: строка статуса «🤖 …», иначе — модель последнего ответа в журнале
                        "model": mdl.group(1).strip() if mdl else self.model_of(w["path"], rev, home),
                        "active": w["id"] == act, "channel": w["channel"], "profile": w.get("profile") or "claude",
                        "rev": rev,                                       # изменился журнал → «новый ответ»
                        "preview": self.preview(w["path"], rev, home),
                        "cost_paused": w["id"] in paused,                 # на паузе по расходу — видно всем
                        "cost": self.cost_of(w, pool, st),                # расход — только хозяину учётки
                        "agent": self.agent_of(w["path"]),                # простой режим: имя агента модуля
                        "sections": self.sections_of(w["path"]),          # разделы чата бизнес-ролей; [] — во всех
                        **self.space_fields(w),                           # окно демо-пространства (spaces.py)
                        **when})                                          # когда менялась (ago.py)
        return out

    OWNER_HERE = 15 * 60                                 # с: «Владелец подключился» видно тестировщику 15 минут

    def space_fields(self, w: dict) -> dict:
        """Окно пространства: имя и название пространства, был ли владелец (``owner_here`` — когда, иначе None)."""
        slug = w.get("space")
        if not slug:
            return {}
        t = tenants.load(slug) or {}
        seen = self.owner_seen.get(w["id"])
        return {"space": slug, "space_title": t.get("title") or slug,
                "owner_here": seen if seen and time.time() - seen < self.OWNER_HERE else None}

    def invite_info(self, code: str) -> dict:
        """Экран входа по приглашению: действует ли и в какое пространство (название — без путей и ролей)."""
        rec = invites.check(code)
        if not rec:
            return {"ok": False}
        t = tenants.load(rec["tenant"]) if tenants.enabled() else None
        return {"ok": True, "title": (t or {}).get("title") or rec["tenant"]}

    def call_help(self, uid, w: dict) -> dict:
        """«Позвать на помощь» из сессии пространства: владельцам — кто, сессия, последний вопрос агента и кнопка
        «Открыть сессию». Из одной сессии — не чаще раза в 5 минут."""
        slug = self.people.tenant(uid)
        if not slug or w.get("space") != slug:
            raise ValueError("позвать на помощь можно из сессии своего демо-пространства")
        if time.time() - self.help_calls.get(w["id"], 0) < testers.HELP_EVERY:
            raise ValueError("владелец уже получил сообщение — подождите несколько минут")
        self.help_calls[w["id"]] = time.time()
        person = next((p for p in self.people.list() if p["id"] == int(uid)), {"id": uid})
        text, kb = testers.help_message(person, slug, w, self.pult.panel_url())
        for chat in self.cfg.owners:
            try:
                self.pult.api("sendMessage", chat_id=chat, text=text, **({"reply_markup": kb} if kb else {}))
            except (TelegramError, OSError) as e:
                print("help:", e, file=sys.stderr, flush=True)
        return {"ok": True}

    def owner_join(self, w: dict) -> dict:
        """Владелец подключился к окну пространства (сам — «Подключиться» — или написал, ответил на вопрос)."""
        if not w.get("space"):
            raise ValueError("это не сессия демо-пространства")
        self.owner_seen[w["id"]] = time.time()
        return {"ok": True, "space": w["space"]}

    def space_task(self, slug: str, name: str, task: str) -> dict:
        """«Поставить задачу» владельцем: новая сессия в пространстве с понятным именем; первое сообщение —
        задание (уходит, когда Claude в окне готов принять текст). Тестировщик видит её у себя этой сессией."""
        slug, name, task = tenants.check_slug(slug), name.strip()[:60], task.strip()
        if not tenants.enabled() or not tenants.load(slug):
            raise ValueError("нет такого пространства")
        if not name:
            raise ValueError("назовите сессию — так её увидит тестировщик")
        wid = spaces.wid_of(slug, tenants.new_window(slug, name))
        self.owner_seen[wid] = time.time()
        if task:
            threading.Thread(target=self.first_message, args=(wid, task), daemon=True).start()
        return {"id": wid, "name": name}

    def first_message(self, wid: str, text: str, timeout: float = 90):
        """Дождаться Claude в новом окне и отправить первое сообщение (то же, что «Отправить» в панели)."""
        end, why = time.time() + timeout, "Claude не запустился"
        while time.time() < end:
            if w := self.window(wid):
                try:
                    self.pult.to_claude(w, text)
                    return True
                except Exception as e:                    # не готов ещё — пробуем, пока не выйдет время
                    why = str(e)
            time.sleep(2)
        print(f"задание в {wid} не отправлено: {why}", flush=True)
        return False

    def sections_of(self, path: str) -> list[str]:
        """Разделы (Поиск, Цифры, Бумаги, Общение) модуля пространства — по каталогу, раз в минуту."""
        mk = modules.mark_of(Path(path))
        if not mk:
            return []
        if time.time() - self.mod_sections[0] > 60:
            self.mod_sections = (time.time(), {m["id"]: m["sections"] for m in modules.catalog()})
        return list(self.mod_sections[1].get(str(mk.get("id")), []))

    def agent_of(self, path: str) -> str:
        """Название модуля, из которого создано пространство (простой режим зовёт агента так), иначе ""."""
        mk = modules.mark_of(Path(path))
        return str((mk or {}).get("title") or "")[:60]

    # ---------- расход (usage.py) ----------
    def cost_of(self, w: dict, pool: str | None, st: dict) -> dict | None:
        """Расход текущей сессии окна — если окно в пуле того, кто смотрит (чужие учётки не показываем)."""
        own_space = pool == "owner" and w.get("space")      # владелец видит расход пространств
        if pool is None or (self.pult.pool_of(w) != pool and not own_space):
            return None
        s = self.pult.meter.session(w["path"], self.pult.home_of(w))
        if not s:
            return None
        lim = usage.limits(st)["session"] if pool == "owner" and not own_space else None
        by = self.pult.opened_by(w)
        name = next((p.get("name") or (f"@{p['username']}" if p.get("username") else "")
                     for p in self.people.list() if p["id"] == by), "") if by else ""
        return {**usage.public(s["total"]), "today": usage.public(s["today"]), "session": s["id"][:8],
                "limit": None if lim is None else round(lim + (st.get("cost_extra") or {}).get(s["id"], 0.0), 2),
                "paused": (st.get("cost_paused") or {}).get(w["id"]) if pool == "owner" and not own_space else None,
                **({"by": {"id": by, "name": name}} if by else {})}

    def pool_home(self, pool: str):
        """Папка Claude Code пула: владелец — None (~/.claude); участник — его папка (не создаём, если её нет)."""
        if pool == "owner":
            return None
        if pool.startswith("space:"):                    # тестировщик: расход его пространства
            d = tenants.paths(pool.removeprefix("space:"))["claude"]
            return d if d.is_dir() else False
        d = self.cfg.data / "people" / pool / "claude"
        return d if d.is_dir() else False

    def cost_summary(self, pool: str | None) -> dict | None:
        """Итог пула за сегодня (по местному дню сервера) и, владельцу, лимиты и паузы."""
        if pool is None:
            return None
        home = self.pool_home(pool)
        day = usage.empty() if home is False else self.pult.meter.day(home)
        out = {"pool": "owner" if pool == "owner" else "own", "today": usage.public(day),
               "prices_checked": usage.PRICES_CHECKED, "prices_url": usage.PRICES_URL}
        if pool == "owner":
            st = self.pult.state()
            out |= {"limits": usage.limits(st), "paused": len(st.get("cost_paused") or {})}
        return out

    def cost_limits(self) -> dict:
        st = self.pult.state()
        return {"limits": usage.limits(st), "paused": st.get("cost_paused") or {},
                "prices_checked": usage.PRICES_CHECKED, "prices_url": usage.PRICES_URL}

    def set_cost_limits(self, b: dict) -> dict:
        """Лимиты из «Настроек»; сразу сверяем — снятые/поднятые лимиты снимают паузы, новые — ставят."""
        self.pult.set_state(cost_limits=usage.check_limits(b))
        self.pult.cost_watch(self.pult.state(), force=True)
        return self.cost_limits()

    def model_of(self, path: str, rev: str, home=None) -> str:
        """Модель последнего ответа из журнала — когда строка статуса её не показывает; кэш по ревизии журнала."""
        key = (path, str(home or ""))
        if self.model_cache.get(key, (None,))[0] != rev:      # (None,) — у нового окна журнала ещё нет (rev "")
            self.model_cache[key] = (rev, transcripts.model_title(transcripts.last_model(path, home=home)))
        return self.model_cache[key][1]

    def preview(self, path: str, rev: str, home=None) -> str:
        """Строка о последнем шаге сессии; пересчитывается, только когда журнал изменился."""
        key = f"{home}|{path}" if home else path
        if self.previews.get(key, (None,))[0] != rev:
            self.previews[key] = (rev, transcripts.preview(path, home=home))
        return self.previews[key][1]

    # ---------- страна человека (country.py) ----------
    def countries(self, uid) -> set[str]:
        """Страны, по которым проверяем поставщика для этого человека: признаки и страна сервера; не выбрана — пусто."""
        return country.check_set(self.people.country(uid), self.cfg.region)

    def check(self, profile: str, uid):
        """Поставщик не разрешён для какой-то из стран человека — отказ ровно этим текстом."""
        if not models.allowed(profile or "claude", self.countries(uid)):
            raise ValueError(country.DENY)

    def mark_by(self, wid: str, uid):
        """Чьё окно — для запасных (``fallback.Switcher``): по странам этого человека."""
        if uid is not None:
            self.tmux.run("set-option", "-w", "-t", wid, "@gas_pult_by", str(uid))

    def seen_ip(self, uid, ip: str, force: bool = False):
        """Страна по IP — при входе (``force``) и не чаще ``IP_EVERY`` на запросах. IP не храним — код и время."""
        if uid is None:
            return
        now, last = time.time(), self.ip_seen.get(uid)
        if not force and last and last[1] == ip and now - last[0] < country.IP_EVERY:
            return
        self.ip_seen[uid] = (now, ip)
        rec, tell = self.people.set_country(uid, ip_cc=self.geo.lookup(ip) or "", ip_at=int(now))
        if tell:
            self.tell_owners(uid, rec)

    def set_country(self, uid, code: str) -> dict:
        c = country.norm(code)
        if not c:
            raise ValueError("нет такой страны — нужен код из двух букв, например NL")
        rec, tell = self.people.set_country(uid, chosen=c)
        if tell:
            self.tell_owners(uid, rec)
        return self.country_info(uid)

    def tell_owners(self, uid, rec: dict):
        """Признаки страны разошлись — одна строка владельцам (имя/ID и коды стран, без номера и IP)."""
        p = next((x for x in self.people.list() if x["id"] == uid), {})
        line = country.notice(p.get("name") or (f"@{p['username']}" if p.get("username") else "человек"), uid, rec)
        for chat in self.cfg.owners:
            try:
                self.pult.api("sendMessage", chat_id=chat, text=line)
            except (TelegramError, OSError) as e:
                print("country:", e, file=sys.stderr, flush=True)

    def country_info(self, uid) -> dict:
        rec = self.people.country(uid)
        return {**country.public(rec), **self.geo.info(), "need": not country.norm(rec.get("chosen")),
                "server": (self.cfg.region or "").upper(), "check": sorted(self.countries(uid)),
                "options": [{"code": c, "name": country.name(c)} for c in country.COMMON], "bot": self._bot}

    def is_owner(self, uid) -> bool:
        try:
            return int(uid) in self.cfg.owners
        except (TypeError, ValueError):
            return False

    def ui(self, uid, role: str | None) -> dict:
        """Вид панели человека (``personas.view``): роль интерфейса, возможности, потолок, справочник.

        Владелец пульта — всегда «Моё пространство» с видом разработчика: экран выбора роли ему сам не показывается
        (``onboarded``), другой вид — только временный просмотр в панели («Демо и тесты»), на сервере не хранится."""
        rec = self.people.ui(uid)
        if self.is_owner(uid):
            rec = {**rec, "persona": personas.DEFAULT, "onboarded": True}
        if sp := self.space_info(uid):                 # тестировщик: вид — тот, что задан пространству
            rec = {**rec, "persona": sp["persona"], "onboarded": True}
        out = personas.view(rec, personas.access(role), self.team, uid, self.people.prefs(uid)["lang"])
        own = self.is_owner(uid)                       # fixed — что владелец у себя не прячет (иначе ушёл бы в чат)
        return {**out, "own_space": own, "fixed": sorted(personas.SPACE_FIXED) if own else [],
                **({"space": sp} if sp else {})}

    def space_info(self, uid) -> dict | None:
        """Пространство тестировщика для панели: имя, название, вид. Не тестировщик — None."""
        slug = self.people.tenant(uid)
        if not slug:
            return None
        t = tenants.load(slug) if tenants.enabled() else None
        return {"slug": slug, "title": (t or {}).get("title") or slug, "ready": t is not None,
                "persona": (t or {}).get("persona") or tenants.DEFAULT_PERSONA}

    def set_ui(self, uid, role: str | None, b: dict) -> dict:
        """Выбор человека: ``persona`` (сменить роль целиком), ``add`` ({cap: true|false}) — тумблеры. Простой режим
        (#80) следует за видом: бизнес-роли — чат, разработчик — прежний интерфейс."""
        add, persona = b.get("add"), None if b.get("persona") is None else str(b["persona"])
        owner = self.is_owner(uid)
        if self.people.tenant(uid):
            raise ValueError("вид панели в демо-пространстве задаёт владелец пульта")
        if owner and persona not in (None, personas.DEFAULT):
            raise ValueError("ваше пространство — всегда вид разработчика; посмотреть как бизнес — «Демо и тесты», "
                             "без сохранения")
        rec = personas.change(self.people.ui(uid), personas.access(role), self.team, uid, persona,
                              add if isinstance(add, dict) else None)
        if owner and personas.simple(personas.effective(personas.DEFAULT, rec.get("added"), rec.get("hidden"),
                                                         personas.ALL)):
            raise ValueError("в вашем пространстве сессии не прячутся — посмотреть без них можно в «Демо и тестах»")
        self.people.set_ui(uid, rec)
        out = self.ui(uid, role)
        if not owner:                                  # простой режим следует за выбором человека — не владельца
            self.people.set_prefs(uid, simple=out["simple"])
        return out

    def prefs(self, uid, role: str | None) -> dict:
        """Настройки панели; ``simple`` — по виду, если человек выбрал роль или владелец закрыл ему инженерное."""
        p, v = self.people.prefs(uid), self.ui(uid, role)
        if self.is_owner(uid):
            return {**p, "simple": False}              # владелец — всегда полный пульт в своём пространстве
        return {**p, "simple": v["simple"] if v["chosen"] or "cap.dev_sessions" not in v["ceiling"]
                else p["simple"]}

    def owner_space_fix(self):
        """Один раз при старте: у владельца вид не разработчика или простой режим — это не его выбор (так было после
        #82: экран выбора роли показывался и владельцу). Сбросить, прежние файлы — рядом с отметкой времени."""
        for o in self.cfg.owners:
            if self.people.ui(o).get("persona") in (None, personas.DEFAULT) and not self.people.prefs(o)["simple"]:
                continue
            stamp = time.strftime("%Y%m%d-%H%M%S")
            for f in (self.people.ui_store, self.people.prefs_store):
                if f.is_file():
                    bak = f.with_name(f"{f.name}.bak-{stamp}")
                    bak.write_bytes(f.read_bytes())
                    bak.chmod(0o600)
            self.people.set_ui(o, {**self.people.ui(o), "persona": personas.DEFAULT, "onboarded": True})
            self.people.set_prefs(o, simple=False)
            print(f"владелец: вид разработчика и полный режим восстановлены (бэкап *.bak-{stamp})", flush=True)

    def team_info(self) -> dict:
        """Экран «Команда»: общая политика для сотрудников и поправки по людям (только участники — staff)."""
        people = [{"id": p["id"], "name": p.get("name") or "", "username": p.get("username") or "",
                   **{f"own_{k}": v for k, v in self.team.person(p["id"]).items()},
                   "ceiling": sorted(self.team.ceiling(p["id"])), "sections": self.team.sections(p["id"])}
                  for p in self.people.list() if p.get("role") == "member"]
        return {**self.team.policy(), "people": people, "catalog": personas.catalog()}

    def people_list(self) -> list[dict]:
        """Люди для панели: страна — кодами и временем, без хеша номера."""
        return [{**p, "country": country.public(p.get("country"))} for p in self.people.list()]

    def personal(self, uid) -> bool:
        """Некоммерческие голоса (Silero) — только владельцу и только при ``personal_voices = true``."""
        try:
            return self.cfg.personal_voices and int(uid) in self.cfg.owners
        except (TypeError, ValueError):
            return False

    def meta(self, uid=None) -> dict:
        voices = catalog.installed(self.personal(uid))
        if sp := self.space_info(uid):                 # тестировщик: ни папок, ни имени сервера владельца
            return {"host": sp["title"], "tz": server_tz(), "commands": [t for t, _ in self.pult.command_list()],
                    "models": [], "keys": [{"label": t, "key": k} for t, k in KEYS + PANEL_KEYS], "profiles": [],
                    "projects": [], "voices": [{"id": v, "label": catalog.label(v)} for v in voices],
                    "voice": self.voice(voices), "space": sp}
        return {"host": self.cfg.host, "tz": server_tz(),
                "commands": [t for t, _ in self.pult.command_list()],
                "models": self.cfg.models,
                "keys": [{"label": t, "key": k} for t, k in KEYS + PANEL_KEYS],
                "profiles": models.public(self.pult.state(), None if uid is None else self.countries(uid)),
                "projects": [self.pult.short(p) for p in self.pult.projects()],
                "voices": [{"id": v, "label": catalog.label(v)} for v in voices],
                "voice": self.voice(voices)}

    def voice(self, voices: list[str] | None = None, personal: bool = False) -> str | None:
        """Голос из настроек, если он доступен этому человеку; иначе — первый доступный (Silero → Piper)."""
        voices = catalog.installed(personal) if voices is None else voices
        v = self.pult.state().get("voice")
        return v if v in voices else (voices[0] if voices else None)

    def login_methods(self) -> dict:
        """Способы входа для экрана входа (без входа): только «включено ли», без настроек."""
        return {"telegram": True, "owner_code": True, "email": self.email.enabled, "passkey": self.keys.enabled,
                **self.oidc.methods()}                                              # google, yandex

    def key_label(self, uid) -> str:
        """Подпись ключа в менеджере паролей устройства: имя человека, без Telegram ID."""
        p = next((x for x in self.people.list() if x["id"] == uid), {})
        who = p.get("name") or (f"@{p['username']}" if p.get("username") else "") or TITLES.get(p.get("role"), "")
        return f"Пульт {self.cfg.host} · {who}"

    def login_start(self, ip: str, ua: str) -> str:
        rid, code = self.auth.start()
        text = (f"🔐 Вход в панель gas-pult из браузера\n\nКод: {code}\n\nДействует 5 минут. "
                f"Откуда: {ip or '?'} · {ua[:80] or 'браузер'}.\nЕсли входите не вы — просто не вводите код.")
        for chat in self.cfg.owners:
            self.pult.api("sendMessage", chat_id=chat, text=text)
        return rid

    # ---------- предложения (offers.py): страница /offer/<код> без входа ----------
    def offer_country_ok(self, cc: str) -> bool:
        """Есть ли для страны хоть один поставщик моделей (с учётом страны сервера) — как при выборе страны."""
        cs = country.check_set({"chosen": cc}, self.cfg.region)
        return any(models.allowed(p["id"], cs) for p in models.PROFILES)

    def offer_wizard(self, o: dict, s: dict, b: dict) -> dict:
        """Шаги мастера «Подключить» до входа: условия, страна, модуль. В демо-сессии — только версия условий,
        код страны и id модуля (без ПДн); к владельцу уходят вместе с запросом доступа."""
        w, step = s["wizard"], str(b.get("step", ""))
        if step == "terms":
            if str(b.get("version", "")) != terms.VERSION:
                raise ValueError("условия обновились — обновите страницу")
            w["terms"] = terms.VERSION
        elif step == "country":
            cc = country.norm(b.get("code"))
            if not cc:
                raise ValueError("нет такой страны — нужен код из двух букв, например NL")
            if not self.offer_country_ok(cc):
                w.pop("country", None)
                raise ValueError(country.DENY)
            w["country"] = cc
        elif step == "module":
            mid = str(b.get("id", ""))
            if mid not in o["modules"]:
                raise ValueError("этого модуля нет в предложении")
            w["module"] = mid
        else:
            raise ValueError("нет такого шага")
        return {"wizard": w}

    def offer_login(self, o: dict, s: dict, ip: str, ua: str) -> dict:
        """Шаг «Войти через Telegram»: обычный вход (TgLogins) с пометкой предложения — владелец увидит, откуда
        человек и что он выбрал. Сессий не создаёт и модель не тратит: всё — после решения владельца."""
        w = s["wizard"]
        if w.get("terms") != terms.VERSION:
            raise ValueError("сначала примите условия использования")
        if not w.get("country"):
            raise ValueError("сначала выберите страну")
        if w.get("module") not in o["modules"]:
            raise ValueError("сначала выберите модуль")
        m = next((x for x in modules.catalog() if x["id"] == w["module"]), {"title": w["module"]})
        bot = self.offer_bot()
        rid, nonce = self.logins.start(ip, ua, offer={
            "business": o["business"], "hint": offers.hint(o["code"]), "module": w["module"],
            "module_title": m["title"], "country": w["country"], "terms": w["terms"]})
        return {"id": rid, "link": f"https://t.me/{bot}?start=login_{nonce}", "ttl": webauth.LOGIN_TTL}

    def offer_bot(self) -> str:
        """Имя бота для ссылок со страницы предложения; Telegram недоступен — понятная ошибка, без подробностей."""
        try:
            return self.bot_username()
        except (TelegramError, OSError, KeyError):
            raise ValueError("бот пульта сейчас недоступен — попробуйте через несколько минут") from None

    def offer_telegram(self, o: dict, mid: str, back: str) -> dict:
        """«Попробовать в Telegram»: короткоживущий токен (не код предложения) → ссылка на бота с ?start=demo_…"""
        if mid not in o["modules"]:
            raise ValueError("этого модуля нет в предложении")
        bot = self.offer_bot()
        tok = self.offer_tg.issue(o["code"], mid, back)
        return {"link": f"https://t.me/{bot}?start=demo_{tok}", "ttl": offers.TG_TTL}

    # ---------- помощник «?» (helper.py) ----------
    def module_ids(self) -> frozenset:
        """id модулей каталога — чтобы принимать от клиента только известные (кэш минуту)."""
        if time.time() - self._mod_ids[0] > 60:
            self._mod_ids = (time.time(), frozenset(m["id"] for m in modules.catalog()))
        return self._mod_ids[1]

    def help_ask(self, role: str, uid, b: dict) -> dict:
        """Вопрос вошедшего: роль — с сервера; от клиента — только экран, шаг, модуль и сам вопрос."""
        v = self.ui(uid, role)                         # вид — с сервера: чипы роли и переходы по возможностям
        return self.helper.ask(role, b.get("ctx"), str(b.get("q", "")), str(b.get("chip", "")),
                               who=[self.helper.who_key("u", uid)], extra={"module_ids": self.module_ids()},
                               lang=str(b.get("lang", "ru")),
                               ui={k: v[k] for k in ("persona", "caps", "ceiling")})

    def help_guest(self, o: dict, sid: str, ip: str, b: dict) -> dict:
        """Вопрос гостя предложения: только экраны страницы и мастера и публичное о модулях ЕГО предложения;
        частота — по cookie демо и по IP (хешами)."""
        cat = {m["id"]: m for m in modules.catalog()}
        mods = [{"id": x, "title": cat[x]["title"], "about": cat[x]["about"]} for x in o["modules"] if x in cat]
        return self.helper.ask("guest", b.get("ctx"), str(b.get("q", "")), str(b.get("chip", "")),
                               who=[self.helper.who_key("g", sid), self.helper.who_key("ip", ip)],
                               extra={"modules": mods})

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

    def activity(self, wid: str) -> dict:
        """Живая строка статуса окна (activity.py): опрос раз в 1,5 с из открытого чата — поэтому список окон
        кэшируется на 3 с (в нём ``ps`` по каждому окну), экран читается не чаще раза в 2 с, журнал — с хвоста."""
        self.tmux.target(wid)                        # окно не своего пространства — «окна нет» (кэш общий)
        now = time.time()
        if wid not in self.wins[1] or now - self.wins[0] > 3:
            self.wins = (now, {w["id"]: w for w in self.tmux.windows() if w["cmd"] == "claude"})
        if not (w := self.wins[1].get(wid)):
            raise LookupError("окна уже нет")
        scr = self.screens.get(wid)
        if not scr or now - scr[0] >= 2:
            scr = self.screens[wid] = (now, self.pult.screen_state(wid))
        home = self.pult.home_of(w)
        return {**self.pult.activity(w, scr[1]), "rev": transcripts.revision(w["path"], home)}

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

    def login_window(self, home=None) -> dict:
        """Окно для входа в MCP: активная сессия, если свободна, иначе любая свободная — только того же человека
        (``home`` — его папка Claude Code; вход сохранится у него, а не у хозяина чужого окна)."""
        mine = {w["id"] for w in self.tmux.windows() if self.pult.home_of(w) == home}
        sess = [s for s in self.sessions() if s["status"] == "idle" and s["id"] in mine]
        pick = next((s for s in sess if s["active"]), None) or (sess[0] if sess else None)
        if not pick:
            raise ValueError("нет свободной сессии Claude — откройте новую («Сессии» → ＋) и повторите"
                             if not home else "нет вашей свободной сессии Claude — откройте свою («Сессии» → ＋) "
                             "и повторите: вход сохранится в ваших интеграциях")
        return self.window(pick["id"])

    def mcp_login(self, name: str, home=None) -> dict:
        """Запуск входа в MCP-сервис из панели: /mcp → сервер → Authenticate → ссылка входа с экрана."""
        w = self.login_window(home)
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

    def mcp_finish(self, w: dict, url: str, name: str, home=None) -> str:
        """Адрес страницы после входа (http://localhost…/callback?code=…) → в поле «URL >» Claude Code."""
        if self.pult.home_of(w) != home:
            raise ValueError("это сессия другого человека — вход начните заново из своих «Интеграций»")
        u = urllib.parse.urlparse(url.strip())
        if u.scheme != "http" or u.hostname not in ("localhost", "127.0.0.1") or "code=" not in u.query:
            raise ValueError("нужен адрес страницы после входа: начинается с http://localhost и содержит code=")
        self.send(w, url.strip())
        time.sleep(4)
        self.tmux.keys(w["id"], "Escape")              # закрыть меню /mcp, вернуться к вводу
        time.sleep(1)
        self.tmux.keys(w["id"], "Escape")
        status = next((s for s in self.mcp.list(fresh=True, home=home) if s["name"] == name), None)
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

    def new(self, i: int, profile: str = "", person: int | None = None, uid=None) -> dict:
        """``person`` — Telegram ID участника: окно с его папкой Claude Code (вход, MCP); None — владелец.
        ``uid`` — кто нажал: по его странам проверяется поставщик и ставится метка окна для запасных."""
        if slug := self.tmux.scoped:                     # тестировщик: окно — только в его пространстве
            return self.new_in_space(slug)
        if uid is not None:
            self.check(profile, uid)                     # поставщик не для страны — отказ сразу
        dirs = self.pult.projects()
        if not 0 <= i < len(dirs):
            raise ValueError("список папок изменился — обновите панель")
        path = dirs[i]
        if w := self.pult.project_window(path):             # одно окно на проект: открываем уже работающее
            self.pult.set_state(active=w["id"])
            return {"id": w["id"], "existing": w["name"]}
        self.need_claude()
        base = os.path.basename(path) if path != self.pult.home else "home"
        home = self.pult.claude_dir(person) if person is not None else None
        cmd = models.command(self.cfg.claude, profile, self.pult.state(), home=home)
        wid = self.tmux.new_window(f"{base}-{time.strftime('%H%M')}", path, cmd, mark=profile or "claude",
                                   by=str(person) if home else "")
        if not home:
            self.mark_by(wid, uid)
        self.pult.set_state(active=wid)
        return {"id": wid}

    def new_in_space(self, slug: str, name: str = "") -> dict:
        """Новая сессия в демо-пространстве: ``tenants.new_window`` — от его пользователя Linux, в его папке, с его
        CLAUDE_CONFIG_DIR и моделью. Функция выключена (нет настройки) — понятный отказ."""
        if not tenants.enabled():
            raise ValueError("демо-пространство ещё не готово — владелец пульта включит его")
        raw = tenants.new_window(slug, name or f"{slug}-{time.strftime('%H%M')}")
        return {"id": spaces.wid_of(slug, raw)}

    # ---------- модули-агенты (modules.py) ----------
    def modules_list(self) -> dict:
        """Каталог модулей для «Новое пространство → Из модуля»: имя папки по умолчанию — свободное."""
        root, errors = self.pult.module_root(), []
        items = [{**modules.public(m), "folder": modules.free_name(root, m["id"]),
                  "existing": self.module_spaces(m["id"])} for m in modules.catalog(errors)]
        return {"modules": items, "root": self.pult.short(str(root)), "errors": errors}

    def module_spaces(self, mid: str) -> list[dict]:
        """Пространства модуля, которые уже есть: папка, последнее изменение, номер в списке папок (для /api/new),
        открытое окно — если есть."""
        dirs = self.pult.projects()
        out = []
        for x in modules.existing(self.pult.module_root(), mid):
            p = str(x["path"])
            w = self.pult.project_window(p)
            out.append({"folder": x["folder"], "path": self.pult.short(p), "changed": x["changed"],
                        "i": dirs.index(p) if p in dirs else None, "open": w["id"] if w else None})
        return out

    def module_create(self, mid: str, name: str, profile: str = "", person: int | None = None, uid=None,
                      lang: str = "", again: bool = False) -> dict:
        """Пространство из модуля: папка в первом корне проектов → сессия в ней (как «Новая сессия») → первое
        задание модуля, когда Claude будет готов. Проверки — до создания папки, чтобы не оставлять пустых.
        ``lang`` (ru, en) — из простого режима: язык ответов агента в настройках Claude Code пространства.
        Пространство этого модуля уже есть — без ``again`` (человек подтвердил «Создать ещё одно») не создаём."""
        if name:
            modules.check_name(name)                   # неверное имя — сразу, до вопроса «уже есть»
        if not again and (have := modules.existing(self.pult.module_root(), mid)):
            raise ValueError(f"пространство «{have[0]['folder']}» этого модуля уже есть — откройте его или "
                             "подтвердите «Создать ещё одно»")
        if uid is not None:
            self.check(profile, uid)
        self.need_claude()
        path = modules.create(mid, self.pult.module_root(), name, by=person, lang=lang)
        out = self.new(self.pult.projects().index(str(path)), profile, person, uid)
        self.pult.send_later(out["id"], modules.get(mid)["start"])
        return {**out, "path": self.pult.short(str(path)), "folder": path.name}

    def new_folder(self, name: str, profile: str = "", person: int | None = None, uid=None) -> dict:
        """«Новая папка» в панели — как 📁 в боте: папка в первом корне проектов, ``git init``, сессия в ней.
        Проверки страны/поставщика и Claude — до создания папки, чтобы не оставлять пустых."""
        if uid is not None:
            self.check(profile, uid)
        self.need_claude()
        try:
            path = self.pult.make_folder(name.strip().lower())
        except FileExistsError:                         # занято — не ошибка: предложим открыть существующую
            p = str(self.pult.module_root() / name.strip().lower())
            dirs, w = self.pult.projects(), self.pult.project_window(p)
            return {"exists": True, "folder": name.strip().lower(), "path": self.pult.short(p),
                    "i": dirs.index(p) if p in dirs else None, "open": w["id"] if w else None}
        out = self.new(self.pult.projects().index(str(path)), profile, person, uid)
        return {**out, "path": self.pult.short(str(path)), "folder": path.name}

    def revive(self, wid: str, uid=None) -> dict:
        """Остановленная сессия: Claude заново в том же окне, у того же поставщика, с продолжением разговора."""
        w = self.tmux.window(wid)
        if not w or not w.get("stopped"):
            raise ValueError("сессия не остановлена — перезапускать нечего")
        if w.get("space"):                              # окно пространства — его команда: свой PATH, профиль, ключ
            t = tenants.load(w["space"])
            if not t:
                raise ValueError("пространства уже нет")
            profile, cmd = w["mark"] or "claude", tenants.command(t)
            self.tmux.respawn(wid, w["path"], cmd + " --continue", mark=profile)
            return {"id": wid}
        profile = w["mark"] if w["mark"] in models.BY_ID else "claude"
        if uid is not None:
            self.check(profile, uid)
        self.need_claude()
        cmd = models.command(self.cfg.claude, profile, self.pult.state(), home=self.pult.home_of(w))  # нет ключа — тут
        self.tmux.respawn(wid, w["path"], cmd + " --continue", mark=profile)   # @gas_pult_by окна остаётся
        self.pult.set_state(active=wid)
        return {"id": wid}

    def restart(self, w: dict, profile: str, keep: bool = True, uid=None) -> dict:
        """Сменить поставщика: штатно закрыть окно и открыть в той же папке с другим профилем.

        ``keep`` — продолжить тот же разговор (``claude --continue``: новый поставщик получает всю переписку, контекст
        не теряется); иначе — чистый лист. Одно окно на проект, поэтому «последний разговор папки» — именно этот.
        """
        if uid is not None:
            self.check(profile, uid)                                          # не для страны — до закрытия
        home = self.pult.home_of(w)                    # папка того, кто открыл окно, а не того, кто нажал
        cmd = models.command(self.cfg.claude, profile, self.pult.state(), home=home)   # нет ключа — ошибка до закрытия
        cmd += " --continue" if keep else ""
        result = self.close(w)
        if result != "закрыто":
            raise ValueError(result)
        wid = self.tmux.new_window(w["name"], w["path"], cmd, mark=profile or "claude",
                                   by=w.get("by", "") if home else "")
        if not home:                                    # окно владельца: метка прежняя, иначе — кто нажал
            self.mark_by(wid, w.get("by") or uid)
        self.pult.set_state(active=wid)
        return {"id": wid}

    def close(self, w: dict) -> str:
        return self.close_ex(w)["result"]

    def close_ex(self, w: dict) -> dict:
        """Завершить сессию: текст итога и неотправленный черновик из поля ввода (если был) — панель его покажет."""
        r = self.pult.quit_ex(w)
        text = {"background": "не закрыл: у сессии есть фоновые задачи — решите в самом окне",
                "busy": "Claude не вышел за 20 с (возможно, занят) — посмотрите экран"}.get(r["result"], "закрыто")
        return {"result": text, "draft": r["draft"]}

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
        el, own = "elevenlabs" in keys, self.cfg.personal_voices        # настройки голоса — только владельцу
        return {"tts": st.get("tts_provider", "local") if el else "local",
                "stt": st.get("stt_provider", "local") if el else "local",
                "el_voice": st.get("el_voice"), "keys": keys,
                "local_voice": catalog.label(self.voice(personal=own) or ""),
                "fallback": self.fallback_note(), "voice": self.voice(personal=own),
                "local_voices": [{"id": v, "name": catalog.label(v)} for v in catalog.installed(own)]}

    def el_voices(self) -> list[dict]:
        key = providers.load_keys().get("elevenlabs")
        return providers.el_voices(key) if key else []

    def el_voice_name(self, vid: str | None) -> str:
        """Имя голоса ElevenLabs для карточки (список аккаунта — не чаще раза в 10 минут)."""
        t, voices = getattr(self, "_el_names", (0.0, []))
        if time.time() - t > 600:
            try:
                voices = self.el_voices()
            except providers.ProviderError:
                voices = []
            self._el_names = (time.time(), voices)
        return next((v["name"] for v in voices if v["id"] == vid), "")

    # ---------- карточки голосов: экран «Голос», шторка у ответа, /voice в боте ----------
    def voice_cards(self, owner: bool) -> dict:
        """Голоса, доступные этому человеку: ElevenLabs первой, затем локальные (``catalog.ORDER``). Silero — только
        владельцу при ``personal_voices``; не установленные — только владельцу. Выбирает — владелец."""
        personal = owner and self.cfg.personal_voices
        st, key = self.pult.state(), "elevenlabs" in providers.key_info()
        out = []
        if key or owner:
            vid = st.get("el_voice") if key else None
            out.append({"id": "elevenlabs", "name": (self.el_voice_name(vid) if vid else "") or "ElevenLabs",
                        "kind": "облачный", "ok": key, "why": "" if key else "нужен ключ ElevenLabs", "install": ""})
        out += catalog.cards(personal, owner)
        cur = "elevenlabs" if key and st.get("tts_provider") == "elevenlabs" else self.voice(personal=personal)
        # Голос без карточки (Piper: выбран раньше или запасной) — читает дальше; панель пишет, что это запасной.
        fb = catalog.label(cur) if cur and cur in catalog.FALLBACK else ""
        return {"cards": out, "current": cur, "can_choose": owner, "fallback": fb}

    def choose_voice(self, vid: str):
        self.pult.choose_voice(vid)                          # общее с ботом (/voice)

    def voice_preview(self, vid: str, owner: bool) -> bytes:
        return self.pult.voice_preview(vid, owner and self.cfg.personal_voices)[0]

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

    def set_models(self, profile: str, main: str, fast: str, base_url: str | None = None):
        """``base_url`` — адрес шлюза клиента (GigaChat, YandexGPT); ``None`` — не менять."""
        self.pult.set_state(model_profiles=models.set_models(self.pult.state(), profile, main, fast, base_url))

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
        if b.get("voice"):
            if b["voice"] not in catalog.selectable(self.cfg.personal_voices):  # настройки голоса — владельцу
                raise ValueError("этот голос не установлен: gas-pult voices install <имя>")
            upd["voice"] = str(b["voice"])
        self.pult.set_state(**upd)

    def voice_fallback(self, what: str, e: Exception):
        """ElevenLabs отказал — работаем локально и сообщаем: журнал службы и ``fallback`` в /api/providers."""
        note = f"ElevenLabs недоступен ({what}): {e} — переключился на локальный голос"
        print(note, file=sys.stderr, flush=True)
        self.last_fallback = (time.time(), note)

    def fallback_info(self, uid=None) -> dict:
        """Запасные для панели: цепочка поставщиков, страны, кто годится, последние переключения, голос (#53)."""
        cs = None if uid is None else self.countries(uid)
        return {**fallback.public(self.pult.state(), self.cfg.region, countries=cs), "voice_note": self.fallback_note()}

    def set_fallback(self, chain, uid=None) -> dict:
        cs = self.cfg.region if uid is None else self.countries(uid)
        self.pult.set_state(fallback_chain=fallback.validate(chain, cs))
        return self.fallback_info(uid)

    def fallback_note(self) -> str:
        t, note = getattr(self, "last_fallback", (0, ""))
        return note if time.time() - t < 3600 else ""

    def stt(self, data: bytes, ctype: str) -> str:
        """Голос из панели → текст. Пустая запись или пустой результат — понятная ошибка (400), не пустая строка."""
        if not data:
            raise ValueError(STT_EMPTY)
        ext = AUDIO_EXT.get(ctype.split(";")[0], "webm")
        if self.voice_settings()["stt"] == "elevenlabs":
            try:
                text = (providers.el_stt(providers.load_keys()["elevenlabs"], data, f"voice.{ext}") or "").strip()
                if not text:
                    raise ValueError(STT_EMPTY)
                return text
            except (providers.ProviderError, KeyError) as e:     # запасной путь — локальный whisper, молча не падаем
                self.voice_fallback("распознавание", e)
        path = self.cfg.data / "inbox" / f"web-{uuid.uuid4().hex}.{ext}"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(data)
        try:
            text = (voice.transcribe(path, self.cfg.whisper_model, timeout=STT_TIMEOUT) or "").strip()
        except subprocess.TimeoutExpired:            # панель ждёт 90 с — сервер сдаётся чуть раньше и говорит почему
            raise RuntimeError(f"распознавание не уложилось в {STT_TIMEOUT} с — длинная запись или сервер занят") \
                from None
        finally:
            path.unlink(missing_ok=True)                 # голос не храним
        if not text:
            raise ValueError(STT_EMPTY)
        return text

    def message(self, w: dict, i: int | None) -> str:
        home = self.pult.home_of(w)
        if i is None:
            return transcripts.last_answer(w["path"], home)
        items, _ = transcripts.history(w["path"], limit=1, before=i + 1, home=home)
        if not items or items[0]["i"] != i:
            raise ValueError("сообщение не найдено — обновите переписку")
        return items[0]["text"]

    def tts(self, w: dict, full: bool, msg: int | None = None, personal: bool = False) -> bytes:
        text = transcripts.clean(self.message(w, msg))
        text = (text if full else brief(text))[:3500]
        if not text:
            raise ValueError("нечего озвучивать")
        vs = self.voice_settings()
        if vs["tts"] == "elevenlabs":
            voice_id = vs["el_voice"] or next(iter(self.el_voices()), {}).get("id")
            if not voice_id:
                raise ValueError("в аккаунте ElevenLabs нет голосов")
            try:
                return providers.el_tts(providers.load_keys()["elevenlabs"], voice_id, text)
            except (providers.ProviderError, KeyError) as e:     # запасной путь — локальный голос
                self.voice_fallback("озвучка", e)
        v = self.voice(personal=personal)                # Silero — только владельцу лично, остальным — Piper
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
        for i, cmd in enumerate(extract(transcripts.last_answer(w["path"], self.pult.home_of(w)))):
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
        tri, to = self.triage(w["path"], w["id"], c["cmd"], code, out)
        self.journal.collect([w], self.pult.cmds.kind)               # та же отметка — во вкладке «Команды»
        self.journal.mark_cmd(w["path"], c["cmd"], self.done(code, secs, out, "panel", tri, to), out)
        return {"code": code, "seconds": round(secs), "out": out[-TAIL:], "cut": len(out) > TAIL,
                **({"full": out[-FULL:]} if len(out) > TAIL else {}), "triage": tri, "triage_to": to}

    def triage(self, path: str, wid: str, cmd: str, code, out: str) -> tuple[str, str]:
        """Упала — в сессию на разбор (одну ошибку — один раз); вставка — под замком окна, как обычное сообщение."""
        try:
            return self.pult.triage(path, wid, cmd, code, out, paste=lambda w, text: self.send(w, text))
        except Exception as e:                                      # разбор — не повод потерять итог выполнения
            print(f"gas-pult webapp: не отправил ошибку на разбор: {e}", flush=True)
            return "error", ""

    @staticmethod
    def done(code, secs: float, out: str, by: str, tri: str = "", to: str = "") -> dict:
        return {"code": code, "seconds": round(secs), "at": utc_now(), "by": by, "out": out[-TAIL:],
                "cut": len(out) > TAIL, "triage": tri, "triage_to": to}

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
        self.journal.update(cid, running=utc_now())                  # другим устройствам — «выполняется»
        try:
            code, secs, out = execute(c["cmd"], c["path"])
        except Exception:
            self.journal.update(cid, running=None)
            raise
        tri, to = self.triage(c["path"], c.get("wid", ""), c["cmd"], code, out)
        item = self.journal.update(cid, running=None, done=self.done(code, secs, out, "panel", tri, to))
        self.journal.save_output(cid, out)
        return {"item": item}

    def command_mark(self, cid: str, done: bool) -> dict:
        """«Отметить: сделано вручную» — отдельная пометка; итог настоящего запуска (done) не трогаем."""
        return {"item": self.journal.update(cid, manual={"at": utc_now()} if done else None)}


def server_tz() -> str:
    """Часовой пояс сервера (Europe/Amsterdam): панель показывает время в нём, где бы ни был телефон. Время в журналах
    Claude Code и пульта — UTC. Не нашли имя пояса — "" (панель покажет время телефона)."""
    if os.environ.get("TZ", "").count("/"):
        return os.environ["TZ"].lstrip(":")
    try:                                            # как timedatectl: системный пояс — ссылка /etc/localtime
        link = os.readlink("/etc/localtime")
        if "zoneinfo/" in link:
            return link.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    try:                                            # /etc/timezone бывает устаревшим — только запасной путь
        return Path("/etc/timezone").read_text().strip()
    except OSError:
        return ""


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

# Только владельцу: выполнение команд, закрытие сессий, ключи, модели, люди.
OWNER_ONLY = {"/api/run", "/api/commands/run", "/api/commands/mark", "/api/commands/output", "/api/close",
              "/api/restart", "/api/keys", "/api/keys/remove", "/api/providers", "/api/voice/choose",
              "/api/models", "/api/openrouter/start", "/api/openrouter/info", "/api/openrouter/models",
              "/api/people", "/api/people/role", "/api/people/remove", "/api/fallback", "/api/team",
              "/api/cost/limits", "/api/cost/decide",
              "/api/spaces", "/api/invite/new", "/api/space/task", "/api/space/connect",
              "/api/setup/status", "/api/setup/login", "/api/setup/code", "/api/setup/cancel"}
# Участнику и владельцу, в том числе чтение: интеграции — у каждого свои (его папка Claude Code), наблюдателю — нет.
MEMBER_ONLY = {"/api/mcp", "/api/mcp/connected"}
OWNER_PRESETS = {"stdio"}               # своя программа на сервере — только владельцу

# Вид панели (роль интерфейса и тумблеры возможностей) — своя настройка человека; потолок задаёт владелец.
PERSONA = "/api/persona"
# До согласия с условиями использования (terms.py) — только это; остальное API отвечает 403 с code="terms".
TERMS_FREE = {"/api/meta", "/api/terms", "/api/terms/accept", "/api/logout", "/api/help/ask", "/api/help/feedback",
              "/api/prefs", PERSONA}
# Помощник «? Подсказать» — любому вошедшему (и наблюдателю), а на экране входа — и до входа.
HELP_OPEN = ("/api/help/ask", "/api/help/feedback")
# Почта для входа и оповещений (emailcode.py) — своя у каждого вошедшего, в том числе у наблюдателя.
EMAIL_OWN = ("/api/email", "/api/email/bind", "/api/email/confirm", "/api/email/remove", "/api/email/options")
# Вход по почте и второй фактор — до входа (свои лимиты по адресу и IP).
EMAIL_LOGIN = ("/api/login/email/start", "/api/login/email/verify", "/api/login/2fa")
# Ключи входа (passkeys.py): свои у каждого вошедшего; вход по ключу — до входа (лимит по IP).
PASSKEY_OWN = ("/api/passkeys", "/api/passkeys/options", "/api/passkeys/add", "/api/passkeys/remove")
PASSKEY_LOGIN = ("/api/login/passkey/options", "/api/login/passkey/verify")
# Вход через Google и Яндекс ID (oidc.py): привязки — свои у каждого вошедшего; сам вход — переходами браузера.
OIDC_OWN = ("/api/oidc", "/api/oidc/link", "/api/oidc/unlink")
OIDC_PATH = re.compile(r"^/api/login/oidc/(google|yandex)/(start|back)$")
# «Сообщить по готовности» из строки статуса — и наблюдателю: только уведомление ему же в бот.
NOTIFY_DONE = "/api/notify-done"
# Отметки короткого тура (пройден / «Не сейчас») — настройка самого человека: менять может и наблюдатель.
TOUR = "/api/tour"
# До выбора страны (country.py) — ещё и выбор страны; остальное — 403 с code="country".
COUNTRY_FREE = TERMS_FREE | {"/api/country"}
# Тестировщик демо-пространства (задача 31): только это — и только с окнами своего пространства (spaces.Routed.scope).
# Остальное (папки и модули владельца, файлы, интеграции, ключи, люди, модели, расход владельца) — 403 code=space.
SPACE_OK = TERMS_FREE | {
    "/api/sessions", "/api/country", "/api/prefs", TOUR, "/api/activity", "/api/last", "/api/screen", "/api/ask",
    "/api/hint", "/api/history", "/api/tts", "/api/stt", "/api/voice/cards", "/api/scenarios", "/api/new",
    "/api/send", "/api/key", "/api/select", "/api/command", "/api/rename", "/api/help/call",
}
# Адрес клиента из заголовков прокси — только если запрос пришёл с этой машины (Caddy, cloudflared).
LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

# Страница предложения (offers.py): без входа, не индексируется, не кэшируется, ссылка не уходит в Referer.
NOINDEX = {"X-Robots-Tag": "noindex, nofollow, noarchive", "Referrer-Policy": "no-referrer",
           "X-Frame-Options": "DENY"}
INVITE_PATH = re.compile(r"^/invite/([A-Za-z0-9_-]{16,64})/?$")
OFFER_PATH = re.compile(r"^/(api/)?offer/([^/]{1,80})(?:/([a-z]{1,20}))?/?$")
ROBOTS = "User-agent: *\nDisallow: /offer/\nDisallow: /api/\n"
OFFER_404 = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             '<meta name="robots" content="noindex, nofollow, noarchive"><title>Страница не найдена</title>'
             '<body style="margin:0;padding:48px 24px;font:16px/1.5 system-ui,sans-serif;text-align:center">'
             '<h1 style="font-size:22px">Страница не найдена</h1><p>Ссылка неверна, устарела или отозвана.</p></body>')

# Страница после входа в OpenRouter: открывается во внешнем браузере, поэтому самодостаточная.
# Страница входа через Google и Яндекс ID: открывается во внешнем браузере, поэтому самодостаточная.
OIDC_PAGE = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             '<title>gas-pult · вход</title><body style="margin:0;padding:48px 24px;font:16px/1.5 system-ui,'
             'sans-serif;background:#F6F5F0;color:#181816;text-align:center"><h1 style="font:600 22px Georgia,serif">'
             '{title}</h1><p style="color:#6E6C65">{text}</p><p><a href="/" style="color:#181816">Открыть панель</a>'
             '</p></body>')
DONE_PAGE = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             '<title>gas-pult · OpenRouter</title><body style="margin:0;padding:48px 24px;font:16px/1.5 system-ui,'
             'sans-serif;background:#F6F5F0;color:#181816;text-align:center"><h1 style="font:600 22px Georgia,serif">'
             '{title}</h1><p style="color:#6E6C65">{text}</p></body>')


def handler(panel: Panel):
    page = resources.files("gas_pult").joinpath("web/index.html").read_bytes()
    build = hashlib.sha256(page).hexdigest()[:12]      # версия страницы: изменилась — панель предложит обновиться
    whatsnew = json.loads(resources.files("gas_pult").joinpath("web/whatsnew.json").read_text(encoding="utf-8"))
    offer_page = resources.files("gas_pult").joinpath("web/offer.html").read_bytes()
    help_map = resources.files("gas_pult").joinpath("web/help-map.json").read_bytes()   # карта для демо панели
    i18n = {f"/i18n/{x}.json": resources.files("gas_pult").joinpath(f"web/i18n/{x}.json").read_bytes()
            for x in ("ru", "en")}                       # словари простого режима и первого экрана — и до входа
    scripts = re.findall(rb"<script>(.*?)</script>", offer_page, re.S)
    hashes = " ".join("'sha256-" + base64.b64encode(hashlib.sha256(x).digest()).decode() + "'" for x in scripts)
    offer_csp = (f"default-src 'none'; script-src {hashes}; style-src 'unsafe-inline'; img-src 'self' data:; "
                 "connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'")

    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):     # без логов запросов: в них initData
            pass

        def reply(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8", cookie: str = "",
                  headers: dict | None = None):
            self.send_response(code)
            if cookie:
                self.send_header("Set-Cookie", cookie)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
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

        def person(self) -> int | None:
            """Telegram ID вошедшего, если это не владелец: его окна и интеграции — в его папке Claude Code."""
            _, role, uid = self.who()
            return None if role == "owner" or uid is None else uid

        def pool(self) -> str | None:
            """Чей расход видит вошедший: владелец — «owner», участник — свой ID, наблюдатель — ничей,
            тестировщик — его пространство."""
            _, role, uid = self.who()
            if slug := self.space():
                return f"space:{slug}"
            return "owner" if role == "owner" else str(uid) if role == "member" and uid is not None else None

        def home(self):
            """Папка Claude Code вошедшего (``people.claude_dir``); владелец — None (``~/.claude``)."""
            uid = self.person()
            return panel.pult.claude_dir(uid) if uid is not None else None

        def session(self) -> str:
            return webauth.cookie_value(self.headers.get("Cookie", ""))

        def space(self) -> str | None:
            """Демо-пространство тестировщика (``people.tenant``); владелец и обычные люди — None."""
            _, role, uid = self.who()
            return None if role == "owner" or uid is None else panel.people.tenant(uid)

        def terms_uid(self) -> int | None:
            """Чьё согласие с условиями проверять. Вход кодом владельцу (LEGACY) — первого владельца."""
            uid = self.who()[2]
            return (panel.cfg.owners or [None])[0] if uid == webauth.LEGACY else uid

        def permit(self, path: str, method: str) -> bool:
            """Не вошёл — 401 (панель покажет вход); не принял условия — 403 code=terms; не хватает роли — 403."""
            role = self.who()[1]
            if not role:
                self.json({"error": "нужен вход"}, 401)
                return False
            uid = self.terms_uid()
            panel.seen_ip(uid, self.client_ip())                   # страна по IP — не чаще раза в IP_EVERY
            if path not in TERMS_FREE and not panel.people.accepted(uid):
                self.json({"error": "сначала примите условия использования пульта", "code": "terms"}, 403)
                return False
            if path not in COUNTRY_FREE and not country.norm(panel.people.country(uid).get("chosen")):
                self.json({"error": "сначала выберите страну, из которой работаете", "code": "country"}, 403)
                return False
            if self.space() and path not in SPACE_OK:     # тестировщик — только своё пространство
                self.json({"error": "в демо-пространстве этого нет", "code": "space"}, 403)
                return False
            free = ("/api/logout", "/api/terms/accept", "/api/country", "/api/prefs", NOTIFY_DONE, TOUR, PERSONA,
                    *HELP_OPEN, *EMAIL_OWN, *PASSKEY_OWN, *OIDC_OWN)            # и наблюдателю
            need = ("owner" if path in OWNER_ONLY else
                    "member" if (method == "POST" and path not in free) or path in MEMBER_ONLY else "viewer")
            if not allowed(role, need):
                why = "это может только владелец" if need == "owner" else "у вас доступ только на просмотр"
                self.json({"error": why}, 403)
                return False
            cap = personas.PATH_CAP.get(path)               # потолок возможностей — это права, не только вид
            if cap and cap not in personas.ceiling(personas.access(role), panel.team, uid):
                self.json({"error": "этот раздел вам не открыл владелец пульта", "code": "cap", "cap": cap}, 403)
                return False
            return True

        def client_ip(self) -> str:
            """Адрес клиента. За обратным прокси на этой машине — из ``X-Forwarded-For`` (последний адрес: его дописал
            наш прокси, начало строки присылает сам клиент) или ``X-Real-IP``; с других адресов заголовкам не верим."""
            peer = self.client_address[0]
            if peer in LOOPBACK:
                xff = [x.strip() for x in self.headers.get("X-Forwarded-For", "").split(",") if x.strip()]
                if xff:
                    return xff[-1]
                if real := self.headers.get("X-Real-IP", "").strip():
                    return real
            return peer

        def client(self) -> tuple[str, str]:
            return self.client_ip(), self.headers.get("User-Agent", "")

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
            if url.path == "/help-map.json":            # демо панели (?demo) отвечает подсказками из карты сам
                return self.reply(200, help_map)
            if url.path in i18n:
                return self.reply(200, i18n[url.path])
            if url.path == "/robots.txt":
                return self.reply(200, ROBOTS.encode(), "text/plain; charset=utf-8")
            if m := INVITE_PATH.match(url.path):         # приглашение: на экран входа с кодом
                return self.reply(302, b"", "text/plain", headers={**NOINDEX, "Location": f"/?invite={m.group(1)}"})
            if url.path == "/api/invite":                # экран входа: «приглашение в …» — только для действующего
                return self.json(panel.invite_info(dict(urllib.parse.parse_qsl(url.query)).get("code", "")))
            if url.path.startswith(("/offer/", "/api/offer/")):     # предложение: без входа, только по коду
                return self.offer("GET", url.path)
            if not url.path.startswith("/api/"):
                return self.json({"error": "нет такой страницы"}, 404)
            q = dict(urllib.parse.parse_qsl(url.query))
            if url.path == "/api/login/tg":              # браузер ждёт подтверждения из Telegram (по своему rid)
                return self.dispatch(lambda: self.tg_poll(q))
            if url.path == "/api/login/methods":         # экран входа: какие способы включены на этом пульте
                return self.json(panel.login_methods())
            if m := OIDC_PATH.match(url.path):           # вход через Google / Яндекс ID: переходы браузера
                return self.oidc_step(m.group(1), m.group(2), q)
            if not self.permit(url.path, "GET"):
                return None
            with panel.tmux.scope(self.space()):
                self.dispatch(lambda: self.get(url.path, q))

        def get(self, path: str, q: dict):
            if path == "/api/sessions":
                pool = self.pool()
                if self.space():                          # тестировщик: без имени сервера и событий владельца
                    sp = panel.space_info(self.terms_uid()) or {}
                    return {"sessions": panel.sessions(pool), "host": sp.get("title", ""), "build": build,
                            "now": time.time(), "cost": panel.cost_summary(pool), "fallback": [], "space": sp}
                with panel.tmux.all_spaces() if self.who()[1] == "owner" else contextlib.nullcontext():
                    ss = panel.sessions(pool)                 # владелец: и окна пространств (группа «Пространства»)
                return {"sessions": ss, "host": panel.cfg.host, "build": build,
                        "now": time.time(),                                   # часы сервера: «N назад» без сдвига
                        "cost": panel.cost_summary(pool),
                        "fallback": [{k: x.get(k) for k in ("ts", "w", "text")}
                                     for x in fallback.recent(panel.pult.state())]}
            if path == "/api/meta":
                kind, role, uid = self.who()
                tu = self.terms_uid()
                cinfo = panel.country_info(tu)
                return {**panel.meta(tu), "via": kind, "role": role, "uid": uid, "build": build,
                        "whatsnew": whatsnew[:1], "prefs": panel.prefs(tu, role), "ui": panel.ui(tu, role),
                        "terms": {"version": terms.VERSION, "accepted": panel.people.accepted(tu)},
                        "country": {k: cinfo[k] for k in ("chosen", "need", "mismatch", "phone", "ip_cc", "check")}}
            if path == "/api/terms":
                return self.terms_info()
            if path == "/api/prefs":
                return panel.prefs(self.terms_uid(), self.who()[1])
            if path == PERSONA:
                return panel.ui(self.terms_uid(), self.who()[1])
            if path == "/api/team":
                return panel.team_info()
            if path == TOUR:                             # тур: пройден / «Не сейчас» — у каждого свой
                return panel.people.tour(self.terms_uid())
            if path == "/api/country":
                return panel.country_info(self.terms_uid())
            if path == "/api/email":
                return panel.email.info(self.terms_uid())
            if path == "/api/passkeys":
                return panel.keys.info(self.terms_uid())
            if path == "/api/oidc":
                return panel.oidc.info(self.terms_uid())
            if path == "/api/people":
                return {"people": panel.people_list(), **panel.geo.info()}
            if path == "/api/setup/status":
                return panel.setup_status(q.get("fresh") == "1")
            if path == "/api/mcp":
                home = self.home()
                return {"servers": panel.mcp.list(q.get("fresh") == "1", home=home),
                        "presets": [p for p in PRESETS if not home or p["id"] not in OWNER_PRESETS],
                        "connectors": CONNECTORS, "connectors_url": CONNECTORS_URL,
                        "personal": home is not None}          # список — свой у человека, не общий с владельцем
            if path == "/api/modules":
                return panel.modules_list()
            if path == "/api/scenarios":                 # «Примерить на себя»: роли, день с агентом, польза
                errors: list[str] = []
                d = scenarios.api_data(errors)
                return {**d, "errors": errors if self.who()[1] == "owner" else []}
            if path == "/api/mcp/connected":
                c = next((x for x in CONNECTORS if x["id"] == q.get("id")), None)
                if not c:
                    raise LookupError("нет такого сервиса")
                s = panel.mcp.connected(c["match"], self.home())
                return {"found": bool(s), "ok": bool(s and s["ok"]), "state": s["state"] if s else ""}
            if path == "/api/openrouter/info":
                return panel.openrouter_info()
            if path == "/api/openrouter/models":
                return {"models": panel.openrouter.models()}
            if path == "/api/fallback":
                return panel.fallback_info(self.terms_uid())
            if path == "/api/cost/limits":
                return panel.cost_limits()
            if path == "/api/providers":
                vs = panel.voice_settings()
                return {**vs, "el_voices": panel.el_voices() if "elevenlabs" in vs["keys"] else []}
            if path == "/api/commands":
                return panel.command_log(self.who()[1] == "owner")
            if path == "/api/commands/output":
                out = panel.journal.output(q.get("id", ""))
                if out is None:
                    raise LookupError("вывода этой команды уже нет")
                return {"out": out}
            if path == "/api/voice/cards":
                return panel.voice_cards(self.who()[1] == "owner")
            if path == "/api/voice/preview":
                return ("audio/mpeg", panel.voice_preview(q.get("id", ""), self.who()[1] == "owner"))
            if path == "/api/spaces":                    # владелец: пространства для «Поставить задачу»
                return tenants.status(check=True)
            if path == "/api/activity":                  # строка статуса чата: что агент делает сейчас
                return panel.activity(str(q.get("w") or ""))
            w = self.win(q.get("w"))
            if path == "/api/last":
                return {"text": transcripts.last_answer(w["path"], panel.pult.home_of(w))}
            if path == "/api/screen":
                lines = panel.tmux.screen(w["id"], 60)
                return {"lines": lines[-40:], "auth": find_auth(lines)}
            if path == "/api/ask":                        # простой режим: вопрос Claude простыми словами и чипы
                return {"ask": humanize.parse(panel.tmux.screen(w["id"], 60))}
            if path == "/api/hint":
                return {"hint": panel.tmux.hint(w["id"])}
            if path == "/api/cmds":
                return {"cmds": panel.commands(w), "host": panel.cfg.host}
            if path == "/api/tts":
                msg = int(q["msg"]) if q.get("msg", "").isdigit() else None
                return ("audio/mpeg", panel.tts(w, q.get("full") == "1", msg,
                                                 panel.cfg.personal_voices and self.who()[1] == "owner"))
            if path == "/api/history":
                before = int(q["before"]) if q.get("before", "").isdigit() else None
                rev = transcripts.revision(w["path"], home := panel.pult.home_of(w))
                if before is None and q.get("rev") and q["rev"] == rev:
                    return {"same": True, "rev": rev}          # журнал не менялся — переписку не пересчитываем
                items, more = transcripts.history(w["path"], 30, before, home=home)
                for it in items:                           # ошибка Claude Code — ещё и простыми словами (простой режим)
                    if it.get("role") == "assistant" and (h := humanize.error(it.get("text") or "", strict=True)):
                        it["human"] = h
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
            if path in PASSKEY_LOGIN:
                if not panel.keys.enabled:
                    return self.json({"error": "вход по ключу выключен на этом пульте", "code": "off"}, 503)
                return self.dispatch(lambda: self.passkey_login(path))
            if path in EMAIL_LOGIN:
                if not panel.email.enabled:
                    return self.json({"error": "вход по почте выключен на этом пульте", "code": "off"}, 503)
                return self.dispatch(lambda: self.email_login(path))
            if path.startswith("/api/offer/"):
                return self.offer("POST", path)
            if path in HELP_OPEN and not self.who()[1]:   # экран входа: подсказки только по нему
                return self.dispatch(lambda: self.help_anon(path))
            if not path.startswith("/api/") or not self.permit(path, "POST"):
                return None if path.startswith("/api/") else self.json({"error": "нет такой страницы"}, 404)
            with panel.tmux.scope(self.space()):
                self.dispatch(lambda: self.post(path))

        def help_anon(self, path: str):
            if not panel.help_anon.ok(self.client_ip()):
                raise ValueError("слишком много вопросов — подождите несколько минут")
            b = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 4096)) or b"{}")
            if path.endswith("/feedback"):
                return panel.helper.feedback(str(b.get("id", "")), b.get("useful"), str(b.get("action", "")), "anon")
            return panel.helper.ask("anon", b.get("ctx"), str(b.get("q", "")), str(b.get("chip", "")),
                                    who=[panel.helper.who_key("ip", self.client_ip())])

        def tg_start(self):
            b = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 4096)) or b"{}")
            code = str((b if isinstance(b, dict) else {}).get("invite") or "")
            if code and not invites.check(code):
                raise ValueError("приглашение недействительно: истёк срок, уже использовано или отозвано")
            rid, nonce = panel.logins.start(*self.client(), invite=code)
            return {"id": rid, "link": f"https://t.me/{panel.bot_username()}?start=login_{nonce}",
                    "ttl": webauth.LOGIN_TTL}

        def tg_poll(self, q: dict):
            state, uid = panel.logins.poll(q.get("id", ""))
            if state == "ok":
                if panel.email.wants_second(uid):                           # второй фактор: код ещё и на почту
                    return panel.email.second_start(uid, self.client_ip())
                panel.seen_ip(uid, self.client_ip(), force=True)            # вход — сверяем страну по IP
                return ("cookie", webauth.set_cookie(panel.auth.issue(uid, self.client()[1])), {"state": "ok"})
            return {"state": state}

        def passkey_login(self, path: str):
            """Вход по ключу: опции (одноразовый вызов) → ответ устройства → сессия (или второй фактор с почты)."""
            b = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 65536)) or b"{}")
            if not isinstance(b, dict):
                raise ValueError("ожидался объект")
            ip, ua = self.client()
            if path == "/api/login/passkey/options":
                return panel.keys.login_options(ip)
            uid = panel.keys.login_verify(str(b.get("id", "")), b.get("credential"), ip)
            if panel.email.wants_second(uid):
                return panel.email.second_start(uid, ip)
            panel.seen_ip(uid, ip, force=True)
            return ("cookie", webauth.set_cookie(panel.auth.issue(uid, ua)), {"state": "ok"})

        def email_login(self, path: str):
            """Вход по коду на почту и второй фактор. Тело — не больше 4 КБ: адрес и код."""
            b = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 4096)) or b"{}")
            if not isinstance(b, dict):
                raise ValueError("ожидался объект")
            ip, ua = self.client()
            if path == "/api/login/email/start":
                return panel.email.login_start(b.get("email"), ip)
            if path == "/api/login/email/verify":
                uid = panel.email.login_verify(b.get("email"), b.get("code"), ip)
            else:
                uid = panel.email.second_verify(str(b.get("id", "")), b.get("code"), ip)
            panel.seen_ip(uid, ip, force=True)
            return ("cookie", webauth.set_cookie(panel.auth.issue(uid, ua)), {"state": "ok"})

        def oidc_page(self, code: int, title: str, text: str, cookies: tuple[str, ...] = ()):
            self.send_response(code)
            for c in cookies:
                self.send_header("Set-Cookie", c)
            body = OIDC_PAGE.format(title=escape(title), text=escape(text)).encode()
            for k, v in {**NOINDEX, "Content-Type": "text/html; charset=utf-8", "Content-Length": str(len(body)),
                         "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def go(self, location: str, cookies: tuple[str, ...] = ()):
            self.send_response(303 if location.startswith("/") else 302)
            for c in cookies:
                self.send_header("Set-Cookie", c)
            for k, v in {**NOINDEX, "Location": location, "Content-Length": "0", "Cache-Control": "no-store"}.items():
                self.send_header(k, v)
            self.end_headers()

        def oidc_step(self, p: str, step: str, q: dict):
            """Вход через Google / Яндекс ID: start → сайт провайдера → back → сессия (или второй фактор, или привязка).
            Это переходы браузера, поэтому ответы — переадресации и короткие страницы, а не JSON."""
            title = oidc.PROVIDERS[p]["title"]
            if not panel.oidc.enabled(p):
                return self.oidc_page(503, "Вход выключен", f"Вход через {title} на этом пульте выключен.")
            ip, ua = self.client()
            drop = oidc.set_cookie("", 0)
            try:
                if step == "start":
                    url, browser = panel.oidc.start(p, ip, str(q.get("link", ""))[:64])
                    return self.go(url, (oidc.set_cookie(browser),))
                r = panel.oidc.finish(p, q, oidc.cookie_value(self.headers.get("Cookie", "")), ip)
            except emailcode.LimitError as e:
                return self.oidc_page(429, "Слишком часто", str(e))
            except (ValueError, RuntimeError) as e:
                return self.oidc_page(400, "Не получилось", str(e), (drop,))
            if r["mode"] == "link":
                return self.oidc_page(200, f"{title} привязан",
                                      f"Теперь на экране входа можно нажать «Войти через {title}». "
                                      "Эту вкладку можно закрыть.", (drop,))
            uid = r["uid"]
            if panel.email.wants_second(uid):                       # второй фактор: код ещё и на почту
                d = panel.email.second_start(uid, ip)
                frag = urllib.parse.urlencode({"2fa": d["id"], "to": d["to"]})
                return self.go(f"/#{frag}", (drop,))                 # номер — во фрагменте: на сервер он не уходит
            panel.seen_ip(uid, ip, force=True)
            return self.go("/", (drop, webauth.set_cookie(panel.auth.issue(uid, ua))))

        def login(self):
            b = json.loads(self.body() or b"{}")
            token = panel.auth.verify(str(b.get("id", "")), str(b.get("code", "")), self.client()[1])
            panel.seen_ip((panel.cfg.owners or [None])[0], self.client_ip(), force=True)   # вход кодом — владелец
            return ("cookie", webauth.set_cookie(token), {"ok": True})

        # ---------- страница предложения: без входа, ничего из панели ----------
        def offer_reply(self, code: int, data, page: bool = False, cookie: str = "", csp: str = ""):
            h = dict(NOINDEX, **({"Content-Security-Policy": csp} if csp else {}))
            if page:
                return self.reply(code, data, "text/html; charset=utf-8", cookie, h)
            return self.reply(code, json.dumps(data, ensure_ascii=False).encode(), cookie=cookie, headers=h)

        def offer_cookie(self, sid: str, age: int = offers.DEMO_TTL) -> str:
            host = self.headers.get("Host", "").split(":")[0]
            secure = (self.client_address[0] in LOOPBACK and self.headers.get("X-Forwarded-Proto") == "https") or \
                host not in ("127.0.0.1", "localhost", "::1", "")
            flags = "; HttpOnly; SameSite=Lax" + ("; Secure" if secure else "")
            return f"{offers.COOKIE}={sid}; Path=/; Max-Age={age}" + flags

        def offer_sid(self) -> str:
            for part in self.headers.get("Cookie", "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == offers.COOKIE:
                    return v
            return ""

        def offer(self, method: str, path: str):
            """``/offer/<код>`` — страница; ``/api/offer/<код>[/действие]`` — её данные. Неизвестный, отозванный и
            просроченный код — один и тот же 404; перебор кодов с одного IP — 429 на любые коды."""
            m, ip = OFFER_PATH.match(path), self.client_ip()
            api = path.startswith("/api/")
            if panel.offer_misses.blocked(ip):
                body = {"error": "слишком много запросов — подождите 10 минут"}
                return self.offer_reply(429, OFFER_404.encode() if not api else body, page=not api)
            o = offers.load(m.group(2)) if m and bool(m.group(1)) == api else None
            if not o or (not api and (method != "GET" or m.group(3))):
                if not o:
                    panel.offer_misses.miss(ip)
                return self.offer_reply(404, OFFER_404.encode() if not api else {"error": "нет такой страницы"},
                                        page=not api)
            if not api:
                return self.offer_reply(200, offer_page, page=True, csp=offer_csp)
            sid, cookie = self.offer_sid(), ""
            s = panel.offer_demos.get(sid, o["code"])
            if not s:
                sid = panel.offer_demos.new(o["code"])
                s, cookie = panel.offer_demos.get(sid, o["code"]), self.offer_cookie(sid)
            act = m.group(3) or ""
            try:
                out = self.offer_act(method, act, o, s, sid)
            except KeyError:
                return self.offer_reply(404, {"error": "нет такого метода"}, cookie=cookie)
            except (ValueError, TelegramError, OSError) as e:
                return self.offer_reply(400, {"error": str(e) or "ошибка"}, cookie=cookie)
            if act == "forget":
                cookie = self.offer_cookie("", 0)
            return self.offer_reply(200, out, cookie=cookie)

        def offer_act(self, method: str, act: str, o: dict, s: dict, sid: str):
            if method == "GET" and act == "":
                bot = bool(panel._bot) or bool(panel.cfg.token)
                return {**offers.page(o), "bot": bot,
                        "session": {"reports": list(s["reports"].values()), "wizard": s["wizard"],
                                    "ttl": max(0, int(s["exp"] - time.time()))}}
            if method != "POST":
                raise KeyError
            if act == "upload":
                n = int(self.headers.get("Content-Length", 0) or 0)
                if n > offer_report.MAX_BYTES:
                    left = min(n, 4 * offer_report.MAX_BYTES)             # дочитать (не храня), чтобы ответ дошёл
                    while left > 0 and (chunk := self.rfile.read(min(left, 1 << 16))):
                        left -= len(chunk)
                    self.close_connection = True
                    raise ValueError(f"Файл больше {offer_report.MAX_BYTES >> 20} МБ — выгрузите период покороче.")
                if not panel.offer_demos.upload_ok(s):
                    raise ValueError("слишком много загрузок — подождите 10 минут")
                data = self.rfile.read(n)
                try:
                    mapping = json.loads(self.headers.get("X-Offer-Map", "")[:2000] or "null")
                except ValueError:
                    mapping = None
                rep = offer_report.build(data, self.headers.get("X-Offer-Kind", ""),
                                         mapping if isinstance(mapping, dict) else None)
                del data                                                  # байты файла дальше не нужны
                return rep if rep.get("error") else panel.offer_demos.put_report(s, rep)
            b = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 4096)) or b"{}")
            if not isinstance(b, dict):
                raise ValueError("ожидался объект")
            if act == "forget":                                           # «Удалить мои данные»
                panel.offer_demos.drop(sid)
                return {"ok": True}
            if act == "wizard":
                return panel.offer_wizard(o, s, b)
            if act == "login":
                return panel.offer_login(o, s, *self.client())
            if act == "help":                                             # помощник гостя: только его страница
                return panel.help_guest(o, sid, self.client_ip(), b)
            if act == "helpfb":
                return panel.helper.feedback(str(b.get("id", "")), b.get("useful"), str(b.get("action", "")), "guest")
            if act == "telegram":
                base = panel.public_url or ""
                return panel.offer_telegram(o, str(b.get("module", "")), f"{base}/offer/{o['code']}" if base else "")
            raise KeyError

        def terms_info(self) -> dict:
            rec = panel.people.terms(self.terms_uid()) or {}
            return {"version": terms.VERSION, "title": terms.TITLE, "points": list(terms.POINTS), "url": terms.URL,
                    "accepted": rec.get("version") == terms.VERSION, "at": rec.get("at")}

        def post(self, path: str):
            if path == "/api/upload":
                return {"path": panel.upload(self.headers.get("X-File-Name", "file"), self.body())}
            if path == "/api/stt":
                before = panel.fallback_note()
                text = panel.stt(self.body(), self.headers.get("Content-Type", ""))
                now = panel.fallback_note()
                return {"text": text, "fallback": now if now and now != before else ""}
            b = json.loads(self.body() or b"{}")
            if path == "/api/prefs":                       # простой режим и язык — у каждого свои
                lang, uid, role = b.get("lang"), self.terms_uid(), self.who()[1]
                if b.get("simple") is True and panel.is_owner(uid):
                    raise ValueError("ваше пространство — всегда полный пульт; простой режим — в «Демо и тестах»")
                if b.get("simple") is not None and not panel.is_owner(uid):   # прежний переключатель — смена роли
                    cur = panel.ui(uid, role)["persona"]
                    want = b.get("simple") is True
                    if want != (cur in personas.SIMPLE):
                        panel.set_ui(uid, role, {"persona": "business_owner" if want else "developer"})
                p = panel.people.set_prefs(uid, None if b.get("simple") is None else b.get("simple") is True,
                                           None if lang is None else str(lang))
                return {**p, "simple": panel.prefs(uid, role)["simple"]}
            if path == PERSONA:
                return panel.set_ui(self.terms_uid(), self.who()[1], b if isinstance(b, dict) else {})
            if path == "/api/team":
                uid = b.get("id")
                caps, secs = b.get("caps"), b.get("sections")
                if uid is not None and int(uid) not in [p["id"] for p in panel.team_info()["people"]]:
                    raise ValueError("это не сотрудник пульта")
                panel.team.set(caps if isinstance(caps, list) else None, secs if isinstance(secs, list) else None,
                               None if uid is None else int(uid), b.get("reset") is True)
                return panel.team_info()
            if path == "/api/terms/accept":
                if str(b.get("version", "")) != terms.VERSION:
                    raise ValueError("условия обновились — прочитайте новую версию")
                panel.people.accept(self.terms_uid(), terms.VERSION)
                return self.terms_info()
            if path == "/api/country":
                return panel.set_country(self.terms_uid(), str(b.get("code", "")))
            if path == TOUR:
                return panel.people.set_tour(self.terms_uid(), str(b.get("tour", "")), str(b.get("state", "")))
            if path == "/api/passkeys/options":
                uid = self.terms_uid()
                return panel.keys.register_options(uid, panel.key_label(uid), self.client_ip())
            if path == "/api/passkeys/add":
                return {"keys": panel.keys.register_verify(self.terms_uid(), str(b.get("id", "")), b.get("credential"),
                                                           str(b.get("name", "")), self.client_ip())}
            if path == "/api/passkeys/remove":
                return {"keys": panel.keys.remove(self.terms_uid(), str(b.get("id", "")))}
            if path == "/api/oidc/link":                   # ссылка на привязку — открыть в браузере (и из Telegram)
                p = str(b.get("provider", ""))
                ticket = panel.oidc.ticket(self.terms_uid(), p, self.client_ip())
                return {"url": f"/api/login/oidc/{p}/start?link={ticket}"}
            if path == "/api/oidc/unlink":
                return panel.oidc.unlink(self.terms_uid(), str(b.get("provider", "")))
            if path == "/api/email/bind":
                return panel.email.bind_start(self.terms_uid(), b.get("email"), self.client_ip())
            if path == "/api/email/confirm":
                return panel.email.bind_confirm(self.terms_uid(), b.get("email"), b.get("code"))
            if path == "/api/email/remove":
                return panel.email.unbind(self.terms_uid())
            if path == "/api/email/options":
                return panel.email.options(self.terms_uid(), b.get("second_factor"), b.get("notify"))
            if path == "/api/help/ask":                    # роль — с сервера, не от клиента
                return panel.help_ask(self.who()[1], self.terms_uid(), b if isinstance(b, dict) else {})
            if path == "/api/help/feedback":
                return panel.helper.feedback(str(b.get("id", "")), b.get("useful"), str(b.get("action", "")),
                                             self.who()[1])
            if path == "/api/commands/run":
                return panel.command_run(str(b.get("id", "")), bool(b.get("confirmed")))
            if path == "/api/commands/mark":
                return panel.command_mark(str(b.get("id", "")), b.get("done", True) is not False)
            if path == "/api/people/role":
                panel.set_role(int(b.get("id", 0)), str(b.get("role", "")))
                return {"people": panel.people_list(), **panel.geo.info()}
            if path == "/api/people/remove":
                panel.people.remove(int(b.get("id", 0)))
                panel.team.forget(int(b.get("id", 0)))
                return {"people": panel.people_list(), **panel.geo.info()}
            if path == "/api/logout":
                panel.auth.logout(self.session())
                return ("cookie", webauth.set_cookie("", 0), {"ok": True})
            if path == "/api/mcp/add":
                home, preset = self.home(), str(b.get("preset", ""))
                if home and preset in OWNER_PRESETS:
                    raise ValueError("свою программу на сервере подключает только владелец")
                return {"result": panel.mcp.add(preset, str(b.get("name", "")), b.get("values") or {}, home=home)}
            if path == "/api/mcp/remove":
                return {"result": panel.mcp.remove(str(b.get("name", "")), home=self.home())}
            if path == "/api/keys":
                return panel.set_key(str(b.get("provider", "")), str(b.get("key", "")))
            if path == "/api/keys/remove":
                panel.remove_key(str(b.get("provider", "")))
                return {"ok": True}
            if path == "/api/providers":
                panel.set_providers(b)
                return {"ok": True}
            if path == "/api/voice/choose":
                panel.choose_voice(str(b.get("id", "")))
                return panel.voice_cards(True)
            if path == "/api/mcp/login":
                return panel.mcp_login(str(b.get("name", "")), self.home())
            if path == "/api/setup/login":                  # окно входа и ссылка с экрана (до 20 с)
                return panel.login.start()
            if path == "/api/setup/code":
                r = panel.login.send_code(str(b.get("code", "")))
                panel._setup = (0, {})
                return r
            if path == "/api/setup/cancel":
                panel.login.cancel()
                return {"ok": True}
            if path == "/api/new":
                return panel.new(int(b.get("i", -1)), str(b.get("profile", "")), self.person(), self.terms_uid())
            if path == "/api/folder":                     # «Новая папка» → сессия в ней (как 📁 в боте)
                return panel.new_folder(str(b.get("name", "")), str(b.get("profile", "")), self.person(),
                                        self.terms_uid())
            if path == "/api/modules/create":
                return panel.module_create(str(b.get("id", "")), str(b.get("name", "")), str(b.get("profile", "")),
                                           self.person(), self.terms_uid(), str(b.get("lang", "")),
                                           b.get("again") is True)
            if path == "/api/openrouter/start":
                base = panel.public_url or f"https://{self.headers.get('Host', '')}"
                return {"url": panel.openrouter.start(base)}
            if path == "/api/fallback":
                return panel.set_fallback(b.get("chain"), self.terms_uid())
            if path == "/api/cost/limits":
                return panel.set_cost_limits(b)
            if path == "/api/cost/decide":                  # пауза по расходу: «go» — продолжить, «stop» — оставить
                return {"result": panel.pult.cost_decide(str(b.get("w", "")), str(b.get("act", ""))),
                        **panel.cost_limits()}
            if path == "/api/models":
                url = b.get("base_url")
                panel.set_models(str(b.get("profile", "")), str(b.get("main", "")), str(b.get("fast", "")),
                                 None if url is None else str(url))
                return {"profiles": models.public(panel.pult.state(), panel.countries(self.terms_uid()))}
            if path == "/api/revive":
                return panel.revive(str(b.get("w", "")), self.terms_uid())
            if path == "/api/invite/new":                  # владелец: ссылка-приглашение тестировщику
                code = invites.create(str(b.get("space", "")), str(b.get("role") or "member"), by=self.terms_uid())
                return {"path": f"/invite/{code}", "ttl": invites.TTL}
            if path == "/api/space/task":
                return panel.space_task(str(b.get("space", "")), str(b.get("name", "")), str(b.get("task", "")))
            w = self.win(b.get("w"))
            if path == "/api/space/connect":
                return panel.owner_join(w)
            if path == "/api/help/call":                    # тестировщик: «Позвать на помощь» — владельцу в бот
                return panel.call_help(self.terms_uid(), w)
            if w.get("space") and self.who()[1] == "owner" and path in ("/api/send", "/api/select", "/api/key"):
                panel.owner_seen[w["id"]] = time.time()      # владелец пишет или отвечает — тестировщик увидит
            if path == NOTIFY_DONE:                       # одно сообщение в бот, когда ход закончится (бот следит)
                return {"result": panel.pult.ask_notify_done(w["id"], self.terms_uid())}
            if path in ("/api/send", "/api/command", "/api/select", "/api/key", "/api/model"):
                panel.check(w.get("profile") or "claude", self.terms_uid())   # сессия этого поставщика — для страны?
            if path == "/api/send":
                text = str(b.get("text", "")).strip()
                if not text:
                    raise ValueError("пустое сообщение")
                return {"ok": True, "dup": panel.send(w, text, str(b.get("id", ""))[:64])}
            if path == "/api/rename":
                return {"name": panel.tmux.rename(w["id"], str(b.get("name", "")))}
            if path == "/api/active" and w.get("space"):
                raise ValueError("сессия демо-пространства не бывает активной в чате бота — откройте её в панели")
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
                return {"result": panel.mcp_finish(w, str(b.get("url", "")), str(b.get("name", "")), self.home())}
            if path == "/api/close":
                return panel.close_ex(w)                   # {result, draft}: черновик не теряется молча
            if path == "/api/restart":
                return panel.restart(w, str(b.get("profile", "")), b.get("keep", True) is not False, self.terms_uid())
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
            except emailcode.LimitError as e:
                return self.json({"error": str(e), "retry": e.retry}, 429)
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
    """Кнопка «📱 Панель» каждому. Ошибка у одного (например, «user not found» — человек не открывал бота)
    не мешает остальным: печатаем и идём дальше."""
    for chat in owners:
        try:
            api("setChatMenuButton", chat_id=chat,
                menu_button={"type": "web_app", "text": "📱 Панель", "web_app": {"url": url}})
        except TelegramError as e:
            print(f"menu: {chat}: {e}", flush=True)


def serve(cfg: Config, port: int = 8765, use_tunnel: bool = False, url: str | None = None):
    panel = Panel(cfg)
    panel.owner_space_fix()                         # вид владельца — его выбор, не чужой (см. owner_space_fix)
    menu_for = cfg.owners + [p["id"] for p in panel.people.list() if p["role"] != "owner"]   # кнопка «📱 Панель»
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler(panel))

    def learn_bot():                                       # имя бота — для ссылки «подтвердите номер в боте»
        panel.geo.lookup("192.0.2.1")                      # и база GeoIP — в память заранее, не на первом входе
        try:
            panel.bot_username()
        except (TelegramError, OSError, KeyError) as e:
            print("bot:", e, flush=True)
    threading.Thread(target=learn_bot, daemon=True).start()

    def sweep():                                           # отчёты демо-страниц — удалить точно в срок
        while True:
            time.sleep(60)
            panel.offer_demos.sweep()
    threading.Thread(target=sweep, daemon=True).start()
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
