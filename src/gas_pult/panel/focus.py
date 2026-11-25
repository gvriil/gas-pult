"""Фокус-ссылки: ссылка на сессию, на проект, демо-ссылка (ответ гостя на вопрос Claude), «Ссылка на пространство»,
проверка ссылки и её окна, «Отправить себе в Telegram»; мост компьютера для фокус-пользователя и мост пространства
(``bridge_*``, ``bridge_space*``) — чьи устройства видит агент окна.

Часть класса ``webapp.Panel`` (модульный монолит, docs/MONOLITH-PLAN.md п.3.1): методы перенесены как есть, ``self`` —
тот же ``Panel``.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import re
import secrets
import threading
import time
from typing import ClassVar

from gas_pult import focus, harness, qr, tenants
from gas_pult.humanize import DIALOG


class FocusPart:
    """Фокус-ссылки, демо-ссылка, ссылка на пространство и мост (примесь к ``Panel``)."""

    FOCUS_BASE = re.compile(r"^https?://[A-Za-z0-9.:\[\]-]{1,200}$")

    def focus_new(self, wid: str, by, base: str, proj: str = "", mode: str = "") -> dict:
        """«Фокус-ссылка» из меню сессии (владелец): ссылка ``…/#focus=<токен>`` — токен показывается один раз.
        ``proj`` — «Фокус-ссылка на проект» из меню проекта: все его сессии, окна у ссылки нет.
        ``mode="demo"`` — «Демо-ссылка»: несколько устройств, только просмотр и выбор вариантов (focus.py)."""
        if mode not in ("", focus.DEMO):
            raise ValueError("неизвестный вид ссылки")
        if proj:
            p = self.project(proj)
            w = {"id": "", "path": p["path"], "name": p["name"]}
        else:
            with self.tmux.all_spaces():
                w = self.tmux.window(str(wid or ""))
            if not w:
                raise LookupError("окна уже нет")
        base = (self.public_url or base or "").rstrip("/")
        if not self.FOCUS_BASE.match(base):
            raise ValueError("не знаю адрес панели снаружи — откройте панель по её адресу и повторите")
        f = self.focus.new(w, by, proj=proj or None, mode=mode)
        return {"url": f"{base}/#focus={f['token']}", "id": f["id"], "exp": f["exp"], "name": w["name"],
                "proj": proj or None, **({"mode": focus.DEMO, "max": focus.DEMO_MAX} if mode else {})}

    def focus_space(self, slug: str, by, base: str, ttl: str = "7d", limit: int = 3, rights: str = "full",
                    name: str = "", audience: str = "client") -> dict:
        """«Ссылка на пространство» (владелец, GAS-38): полная панель пространства ``slug`` — как у его тестировщика.
        Срок ``ttl`` (``focus.SPACE_TTLS``), устройств ``limit`` (1, 3, 0 — без ограничения), права «full» / «read»."""
        slug = tenants.check_slug(slug)
        t = tenants.load(slug) if tenants.enabled() else None
        if t is None:
            raise LookupError("пространства нет")
        if ttl not in focus.SPACE_TTLS:
            raise ValueError("срок: 1h, 1d, 7d, 30d или none")
        if limit not in focus.SPACE_MAX:
            raise ValueError("устройств: 1, 3 или 0 — без ограничения")
        if rights not in ("full", "read"):
            raise ValueError("права: full или read")
        if audience not in ("client", "self"):
            raise ValueError("для кого: client или self")
        base = (self.public_url or base or "").rstrip("/")
        if not self.FOCUS_BASE.match(base):
            raise ValueError("не знаю адрес панели снаружи — откройте панель по её адресу и повторите")
        title = str(name or "").strip()[:60] or t.get("title") or slug
        f = self.focus.new({"id": "", "path": "", "name": title, "space": slug}, by, ttl=focus.SPACE_TTLS[ttl],
                           mode=focus.SPACE, limit=limit, rights=rights, audience=audience)
        return {"url": f"{base}/#focus={f['token']}", "id": f["id"], "exp": f["exp"], "name": title, "space": slug,
                "space_title": t.get("title") or slug, "mode": focus.SPACE, "max": limit, "rights": rights,
                "forever": ttl == "none", "audience": audience}

    def focus_device(self, rid: str, base: str) -> dict:
        """«Открыть на другом устройстве» (владелец 22.11): одноразовая ссылка той же записи на 15 минут и её QR —
        для устройства, открытого по ссылке (своя запись), и для владельца (по запросу доступа). Мест нет — 409."""
        base = (self.public_url or base or "").rstrip("/")
        if not self.FOCUS_BASE.match(base):
            raise ValueError("не знаю адрес панели снаружи — откройте панель по её адресу и повторите")
        f = self.focus.add_device(rid)
        url = f"{base}/#focus={f['token']}"
        png = base64.b64encode(qr.png_of(url, 6)).decode()
        return {"url": url, "exp": f["exp"], "used": f["used"], "max": f["max"], "qr": "data:image/png;base64," + png}

    ASK_WHY: ClassVar[dict] = {
        "nodevice": "открыли адрес без ключа (без полной ссылки)", "limit": "все места для устройств заняты",
        "expired": "срок ссылки вышел", "revoked": "ссылку отозвали", "bad": "ссылка не найдена",
        "closed": "чат завершён"}

    def focus_ask(self, token: str, rid: str, why: str, note: str, device: str) -> dict:
        """«Попросить доступ» со страницы без действующей ссылки (до входа): запрос — владельцам (``broadcast``) с
        кнопкой в панель. Запись ссылки — по токену (если он ещё в странице) или по id, который эта страница запомнила
        раньше; без них — только текст человека и вид устройства. Ответ всегда один и тот же: по нему нельзя
        проверить, есть ли ссылка с таким id."""
        hint = str(rid or "")
        rid = self.focus.rid_by_token(token) if token else ""
        if not rid and re.fullmatch(r"[0-9a-f]{12}", hint):
            rid = hint
        if not rid and not str(note or "").strip():
            raise ValueError("напишите, кто вы или о какой ссылке речь — владельцу нужно понять, кому ответить")
        a = self.focus.ask(rid, why, note, device)
        base = (self.public_url or self.pult.panel_url() or "").split("?")[0].rstrip("/")
        lines = ["🔑 Просят доступ по фокус-ссылке" + (f" «{a['name']}»" if a["name"] else "") + ".",
                 f"Почему: {self.ASK_WHY.get(a['why'], 'ссылка не открылась')}.",
                 *([f"Пишет: «{a['note']}»"] if a["note"] else []),
                 *([f"Устройство: {a['device']}"] if a["device"] else []),
                 "Ссылка не определена — выберите её в «Настройки» → «Фокус-ссылки» или создайте новую."
                 if not a["rid"] else "Добавьте устройство — панель покажет ссылку и QR; перешлите их человеку."]
        kb = None
        if base and self.FOCUS_BASE.match(base):
            url = f"{base}/?focusask={a['id']}"
            kb = {"inline_keyboard": [[{"text": "Добавить устройство", "web_app": {"url": url + "&do=add"}},
                                       {"text": "Новая ссылка", "web_app": {"url": url + "&do=new"}}]]}
        with contextlib.suppress(Exception):
            self.pult.broadcast("\n".join(lines), kind="people", **({"reply_markup": kb} if kb else {}))
        return {"ok": True}

    def focus_sessions(self, rec: dict) -> list[dict]:
        """Сессии, видимые по ссылке: одна её сессия или окна её проекта, открытые по этой ссылке (``focus_wins``), —
        и окна, которые агент открыл из них (``focus_spawned``). Окна владельца в той же папке не видны (штаб 25.11)."""
        kids = self.focus_spawned(rec)
        if rec.get("proj"):
            mine = self.focus_wins(rec)
            return [s for s in self.sessions(None) if not s.get("space")
                    and ((s.get("project") == rec["proj"] and s["id"] in mine) or s["id"] in kids)]
        return [s for s in self.sessions(None) if s["id"] == rec["w"] or s["id"] in kids]

    def focus_wins(self, rec: dict, wins: list[dict] | None = None) -> set[str]:
        """Окна, открытые по ссылке на проект: метка окна ``@gas_pult_focus`` = id ссылки (ставит новый чат и
        «Продолжить» по ссылке). Метка живёт с окном: окно с тем же номером после перезапуска tmux — без неё.
        Демо-ссылка — показ клиенту чатов владельца: все окна проекта, как раньше."""
        rid = str(rec.get("id") or "")
        try:
            wins = self.tmux.windows() if wins is None else wins
        except (OSError, LookupError):
            return set()
        if focus.Focus.whole_project(rec):               # демо и личная ссылка владельца — весь проект
            pd = self.project_data()
            return {w["id"] for w in wins if not w.get("space") and self.project_of(pd, w) == rec["proj"]}
        return {w["id"] for w in wins if rid and not w.get("space") and focus.Focus.owns_window(rec, w)}

    def focus_adopt_new(self, path: str, wid: str, sid: str) -> list[str]:
        """Окно, открытое в папке проекта, у которого есть живые ссылки людей, — сразу видно этим ссылкам (владелец
        25.11: «новые окна, которые владелец открывает в проекте клиента, не терялись для его ссылки»). Разговор окна —
        в ``sids`` каждой ссылки (виден и после закрытия, «Продолжить»), метка окна — их id. Только окна Claude с id
        разговора (не оболочка); ссылки владельца (owner_link), демо и пространства — не трогаем. Сбой — молча."""
        sid = str(sid or "")
        if not sid or not path:
            return []
        try:
            pid = self.projects.of_path(self.project_data(), path)
            if not pid:
                return []
            rids = [k for k, v in self.focus._load().items() if v.get("proj") == pid and focus.Focus.live(v)
                    and not focus.Focus.whole_project(v) and not v.get("space")]
            for rid in rids:
                self.focus.add_chat(rid, sid)
            if rids:
                self.tmux.set_focus(wid, " ".join(rids))
            return rids
        except (OSError, LookupError, ValueError):
            return []

    SPAWN_DEPTH = 4                         # окно из окна из окна…: дальше — не ищем (и цикл опций не крутим вечно)

    def focus_spawned(self, rec: dict) -> set[str]:
        """Окна, открытые из окон ссылки (владелец 23.11): агент её чата вынес задачу в новое окно — в любой папке, —
        и оно видно по той же ссылке. Родитель окна — опция ``@gas_pult_from`` (``spawned.py``, ставит хук tmux).
        Только окна владельца: окна пространств — свой сервер tmux, по ссылке владельца не видны никогда. Ссылки на
        пространство и на протокол — без них. Права не шире: только окна-потомки окон самой ссылки."""
        if rec.get("space") or rec.get("mode") in (focus.SPACE, focus.MEETING):
            return set()
        try:
            wins = [w for w in self.tmux.windows() if not w.get("space")]
        except (OSError, LookupError):
            return set()
        kids: dict[str, list[str]] = {}
        for w in wins:
            if (p := w.get("from")) and p != w["id"]:
                kids.setdefault(p, []).append(w["id"])
        if not kids:
            return set()
        base = self.focus_wins(rec, wins) if rec.get("proj") else ({rec["w"]} if rec.get("w") else set())
        seen, edge = set(base), set(base)
        for _ in range(self.SPAWN_DEPTH):
            edge = {k for p in edge for k in kids.get(p, ()) if k not in seen}
            if not edge:
                break
            seen |= edge
        return seen - base

    def bridge_dev_ok(self, dev: dict | None) -> bool:
        """Устройство моста работает: владельца — всегда; фокус-пользователя — пока жива его ссылка с «Браузер»."""
        return bool(dev) and (not dev.get("focus") or self.focus.browser_ok(dev["focus"]))

    def bridge_allowed(self, window: str) -> set[str]:
        """Устройства для агента окна ``window``: окно фокус-ссылки с «Браузер» — только устройства этой ссылки;
        любое другое окно (и без окна) — только устройства владельца. Чужое устройство агенту не видно."""
        devs = self.devices.listing()
        links = [r for r in ({**v, "id": k} for k, v in self.focus._load().items())
                 if r.get("browser") and focus.Focus.live(r) and not r.get("space")] if window else []
        # окна пространств — свой сервер tmux, их номера (@3) совпадают с окнами владельца: такие ссылки — только
        # через мост пространства (bridge_space)
        mine = {r["id"] for r in links if self.focus_owns(r, window)}
        if mine:
            return {d["id"] for d in devs if d.get("focus") in mine}
        return {d["id"] for d in devs if not d.get("focus")}

    def bridge_space(self, token: str) -> str:
        """Пространство по токену его моста (``pult-tenant bridge``): хэш в ``<папка>/bridge.sha256``; нет — ""."""
        if not token or not tenants.enabled():
            return ""
        h = hashlib.sha256(token.encode()).hexdigest()
        for slug in tenants.slugs():
            try:
                want = (tenants.paths(slug)["base"] / "bridge.sha256").read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if want and secrets.compare_digest(want, h):
                return slug
        return ""

    def bridge_space_allowed(self, slug: str) -> set[str]:
        """Устройства для агента пространства: только фокус-ссылок этого пространства с «Браузер»."""
        rids = {k for k, v in self.focus._load().items()
                if v.get("space") == slug and v.get("browser") and focus.Focus.live(v)}
        return {d["id"] for d in self.devices.listing() if d.get("focus") in rids}

    def focus_bridge(self, rec: dict, path: str, b: dict) -> dict:
        """Фокус-пользователь и его компьютер: список своих устройств, код пары, отзыв. Только если владелец разрешил
        «Браузер» для этой ссылки; чужие устройства (владельца, других ссылок) не видны и не отзываются."""
        if not rec.get("browser"):
            raise focus.Denied("владелец не разрешил подключать браузер по этой ссылке")
        mine = [d for d in self.devices.listing() if d.get("focus") == rec["id"]]
        if path == "/api/focus/bridge/pair":
            return self.devices.pair_code(focus=rec["id"])
        if path == "/api/focus/bridge/revoke":
            did = str(b.get("id") or "")
            if did not in {d["id"] for d in mine}:
                raise focus.Denied("это устройство не из вашей ссылки")
            return {"ok": self.devices.revoke(did)}
        if path == "/api/focus/bridge/private":          # свой компьютер: «Личные данные не уходят модели»
            did = str(b.get("id") or "")
            if did not in {d["id"] for d in mine}:
                raise focus.Denied("это устройство не из вашей ссылки")
            return {"ok": self.devices.set_private(did, b.get("on") is not False)}
        on = set(self.hub.online())
        return {"devices": [{**d, "online": d["id"] in on} for d in mine]}

    def focus_owns(self, rec: dict, wid: str) -> bool:
        """Окно ``wid`` — из этой ссылки: её сессия; у ссылки на проект — окно проекта, открытое по ней (метка
        ``@gas_pult_focus``); и окна, открытые из них агентом (``focus_spawned``)."""
        if not wid:
            return False
        if not rec.get("proj"):
            return wid == rec["w"] or wid in self.focus_spawned(rec)
        with self.tmux.all_spaces():
            w = self.tmux.window(wid)
        if not w or w.get("space"):
            return False
        mine = focus.Focus.whole_project(rec) or focus.Focus.owns_window(rec, w)   # демо, владелец — весь проект
        return (mine and self.project_of(self.project_data(), w) == rec["proj"]) or wid in self.focus_spawned(rec)

    def focus_token(self, url: str) -> dict:
        """Действующая ссылка по адресу ``…/#focus=<токен>`` (для QR и «Отправить себе»)."""
        m = re.match(r"^https?://[A-Za-z0-9.:\[\]-]{1,200}/#focus=([A-Za-z0-9_-]{24,64})$", str(url or ""))
        rec = self.focus.check_token(m.group(1)) if m else None
        if not rec:
            raise LookupError("фокус-ссылка не действует: сессия завершена, ссылку отозвали или вышел срок")
        return rec

    def focus_send(self, url: str, chat) -> dict:
        """«Отправить себе в Telegram»: ссылка — сообщением в чат владельца с ботом (как в «Избранное»)."""
        rec = self.focus_token(url)
        if not chat or int(chat) < 0:
            raise ValueError("не знаю ваш чат с ботом — войдите в панель через Telegram")
        till = time.strftime("%d.%m %H:%M", time.localtime(rec["exp"]))
        if focus.Focus.is_demo(rec):
            text = (f"🎬 Демо-ссылка на «{rec['name']}»\n\nДля показа: открывается на нескольких устройствах (до "
                    f"{focus.DEMO_MAX}), только просмотр и выбор вариантов в вопросах Claude — писать, загружать файлы "
                    f"и менять настройки по ней нельзя. Действует до {till}. Отозвать — «Настройки» → «Фокус-ссылки»."
                    f"\n\n{url}")
        elif rec.get("proj"):
            text = (f"🎯 Фокус-ссылка на проект «{rec['name']}»\n\nОткройте на нужном устройстве — там будут все "
                    f"сессии этого проекта и новая сессия в нём, без остального пульта. Первое открытие привязывает "
                    f"устройство. Ссылка действует до {till}. Отозвать — «Настройки» → «Фокус-ссылки».\n\n{url}")
        else:
            text = (f"🎯 Фокус-ссылка на сессию «{rec['name']}»\n\nОткройте на нужном устройстве — там будет только "
                    f"чат этой сессии, без остального пульта. Первое открытие привязывает устройство. Ссылка гаснет, "
                    f"когда сессию завершат, и не позже {till}. Отозвать — «Настройки» → «Фокус-ссылки».\n\n{url}")
        self.pult.api("sendMessage", chat_id=int(chat), text=text, link_preview_options={"is_disabled": True},
                      reply_markup={"inline_keyboard": [[{"text": "Открыть в браузере", "url": url}],
                                                        [{"text": "Открыть в Telegram", "web_app": {"url": url}}]]})
        return {"ok": True}

    def focus_rec(self, cookie: str) -> dict:
        """Запрос из фокуса: действующая ссылка этого устройства и живое окно её сессии; иначе ``focus.Gone``.
        Окна нет (сессию завершили из панели или бота) — ссылка гаснет сразу."""
        rec = self.focus.by_cookie(cookie)
        if focus.Focus.is_meeting(rec):                     # ссылка на протокол: окна нет, живёт до срока и отзыва
            return rec
        if rec.get("mode") == focus.SPACE:                   # ссылка на пространство — полная панель, не режим фокуса
            raise focus.Gone("Это ссылка на пространство — откройте её ещё раз.")
        if rec.get("proj"):                                  # ссылка на проект: живёт, пока есть проект и срок
            if rec["proj"] not in self.project_data()["projects"]:
                self.focus.end(rec["id"])
                raise focus.Gone("Проект удалён.")
            return rec
        with self.tmux.scope(rec.get("space")):
            w = self.tmux.window(rec["w"])
            if not w or w.get("path") != rec.get("path"):   # перезапустили из бота — то же окно папки (одно на проект)
                w = next((x for x in self.tmux.windows() if x.get("path") == rec.get("path")
                          and (harness.is_agent(x) or x.get("stopped"))), None)
                if w:
                    self.focus.move(rec["w"], w["id"])
                    rec = {**rec, "w": w["id"]}
        if not w:
            # перезапуск (модель, поставщик — из фокуса, из панели или из бота) закрывает окно раньше, чем открывает
            # новое: между ними окна нет. Гасим ссылку, только если окна нет дольше ``focus.GRACE``; «Завершить»
            # гасит её сразу (``end_window``)
            first = self.focus_gap.setdefault(rec["id"], time.time())
            if time.time() - first < focus.GRACE:
                raise focus.Wait("сессия перезапускается — подождите несколько секунд")
            self.focus_gap.pop(rec["id"], None)
            self.focus.end(rec["id"])
            raise focus.Gone("Чат завершён.")
        self.focus_gap.pop(rec["id"], None)
        return rec

    DEMO_KEYS = frozenset({"Up", "Down", "Enter"})   # демо-ссылка: клавиши — только чтобы выбрать пункт меню
    DEMO_GAP = 3                            # с: после ответа гостя остальные нажатия — «уже ответили»
    DEMO_ANSWERED = 30                      # с: вопроса уже нет, но ответили недавно — «уже ответили», не «нельзя»

    def demo_answer(self, wid: str, go: bool, fn):
        """Ответ гостя демо-ссылки на вопрос Claude: только когда на экране окна вопрос или меню (``DIALOG``); гости
        жмут одновременно — первый ответ проходит, остальным «уже ответили» (409). Нет вопроса — 403."""
        lock = self.demo_locks.setdefault(wid, threading.Lock())
        with lock:
            last = self.demo_done.get(wid, 0.0)
            if go and time.time() - last < self.DEMO_GAP:
                raise focus.Denied("Уже ответили — вариант выбрали на другом устройстве.", "answered", 409)
            if not DIALOG.search("\n".join(self.tmux.screen(wid, 60))):
                if time.time() - last < self.DEMO_ANSWERED:
                    raise focus.Denied("Уже ответили — вариант выбрали на другом устройстве.", "answered", 409)
                raise focus.Denied("по демо-ссылке можно только выбрать вариант, когда Claude задаёт вопрос")
            out = fn()
            if go:
                self.demo_done[wid] = time.time()
            return out
