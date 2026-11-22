"""Люди в панели: страна человека, владелец и вид панели (``ui``, ``set_ui``, ``prefs``), «Команда» и список людей,
роли и срок доступа, отключение человека, вход через Telegram, подписи ключей входа и код подтверждения команд.

Часть класса ``webapp.Panel`` (модульный монолит, docs/MONOLITH-PLAN.md п.3.1): методы перенесены как есть, ``self`` —
тот же ``Panel``.
"""

from __future__ import annotations

import contextlib
import sys
import time

from gas_pult import country, emailcode, harness, invites, models, personas, tenants, webauth
from gas_pult.people import STAFF_ROLES, TITLES
from gas_pult.telegram import TelegramError


class PeoplePart:
    """Страна, люди, вид панели, вход через Telegram и ключи входа (примесь к ``Panel``)."""

    def forget_person(self, uid: int):
        """Отключить человека: роль, сессии браузера и его ссылки для входа — сразу."""
        self.people.remove(uid)
        self.team.forget(uid)
        self.auth.drop(uid)
        invites.drop_for(uid)

    # ---------- страна человека (country.py) ----------
    def countries(self, uid) -> set[str]:
        """Страны, по которым проверяем поставщика для этого человека: признаки и страна сервера; не выбрана — пусто."""
        return country.check_set(self.people.country(uid), self.cfg.region)

    def check(self, profile: str, uid):
        """Поставщик не разрешён для какой-то из стран человека — отказ ровно этим текстом."""
        if profile in harness.JOURNAL_ONLY:              # Pi, OpenCode, Hermes — по правилам поставщика их модели
            profile = harness.HARNESSES[profile].COUNTRY_AS
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
        return {**country.public(rec), **self.geo.info(), "need": False,                     # 20.11: не спрашиваем
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
        access = personas.access(role)
        if sp := self.space_info(uid):
            # тестировщик пространства — та же панель пульта, что у владельца, без его функций (владелец 19.11:
            # «интерфейс должен быть точно такой же, как у нас в пульте, только без заморочек»): сессии и проекты,
            # терминал (за «режимом разработчика», только своё пространство) и расход (бюджет пространства) — открыты
            # (владелец 20.11, GAS-38); журнал — нет; модели и MCP — по потолку гостя (закрыты)
            rec = {**rec, "persona": personas.DEFAULT, "onboarded": True, "added": [],
                   "hidden": sorted(self.SPACE_HIDE)}
            access = "guest"
        elif not self.is_owner(uid) and "cap.dev_terminal" not in (rec.get("added") or []):
            # терминал — только тем, кому нужен (владелец и Алексей 20.11): у участника без явного «добавить» — нет;
            # включить — «Настройки» → «Возможности панели» (владелец задаёт потолок в «Команде»)
            rec = {**rec, "hidden": sorted({*(rec.get("hidden") or []), "cap.dev_terminal"})}
        out = personas.view(rec, access, self.team, uid, self.people.prefs(uid)["lang"])
        own = self.is_owner(uid)                       # fixed — что владелец у себя не прячет (иначе ушёл бы в чат)
        return {**out, "own_space": own, "fixed": sorted(personas.SPACE_FIXED) if own else [],
                **({"space": sp} if sp else {})}

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
        if self.is_owner(uid) or self.people.tenant(uid):
            return {**p, "simple": False}              # владелец и тестировщик пространства — полный пульт (19.11)
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

    def login_methods(self) -> dict:
        """Способы входа для экрана входа (без входа): только «включено ли», без настроек."""
        return {"telegram": True, "owner_code": True, "email": self.email.enabled, "passkey": self.keys.enabled,
                "invite": tenants.enabled(),                                         # «Есть код приглашения?»
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

    def confirm_start(self, token: str, uid: int, ip: str, ua: str) -> dict:
        """Код подтверждения команд для сессии браузера (``CONFIRM``). Канал: почта, если человек включил второй
        фактор (не тот же Telegram, что и вход), иначе — сообщение бота в его Telegram (вход кодом — владельцам)."""
        rid, code = self.auth.confirm_start(token)
        who = (self.cfg.owners or [None])[0] if uid == webauth.LEGACY else uid
        where = f"{ip or '?'} · {webauth.device(ua)}"
        if who is not None and self.email.wants_second(who):
            addr = self.people.email(who)["address"]
            subject, text = emailcode.code_text(code, f"подтверждения команд на сервере (вход: {where})")
            self.email.deliver(addr, subject, text)
            emailcode.log("confirm_sent", uid=who, ip=ip)
            return {"id": rid, "via": "email", "to": emailcode.mask(addr), "ttl": webauth.CONFIRM_TTL}
        text = (f"🔐 Подтверждение команд на сервере\n\nКод: {code}\n\nДействует 10 минут. Вход: {where}.\n"
                "Новый вход в панель просит выполнять команды и писать в терминал. Если это не вы — не вводите код: "
                "без него с этого входа команды не выполнятся.")
        # код — всегда прямым сообщением бота, мимо каналов уведомлений (их выбор на код не влияет); закрепляем его,
        # чтобы зеркало сессий в том же чате не утопило код (21.11: владелец не нашёл четыре дошедших кода)
        where, pins, sent, err = self.bot_where(), [], 0, None
        for chat in (self.cfg.owners if uid == webauth.LEGACY else [uid]):
            try:                       # владелец, не открывший бота («user not found»), не мешает остальным
                mid = self.pult.api("sendMessage", chat_id=chat, text=text, reply_markup={"inline_keyboard": [[
                    {"text": "✅ Подтвердить вход", "callback_data": "cf:" + rid}]]}).get("message_id")
            except (TelegramError, OSError) as e:
                err = e
                continue
            sent += 1
            if mid:
                with contextlib.suppress(TelegramError, OSError):
                    self.pult.api("pinChatMessage", chat_id=chat, message_id=mid, disable_notification=True)
                    pins.append((chat, mid))
        if not sent:
            raise RuntimeError(f"бот не смог прислать код: {err}" if err else "некому прислать код")
        self.tg_confirm.offer(rid, token, uid)          # кнопка «✅ Подтвердить вход» — без ввода цифр
        self.confirm_pins[rid] = pins
        return {"id": rid, "via": "telegram", "to": "Telegram", "ttl": webauth.CONFIRM_TTL,
                "at": int(time.time()), **where}

    def bot_where(self) -> dict:
        """Где искать код: имя чата с ботом (как в списке чатов Telegram) и ссылка на бота; Telegram недоступен —
        пусто."""
        if not self._bot_name:
            with contextlib.suppress(TelegramError, OSError, KeyError):
                me = self.pult.api("getMe")
                self._bot, self._bot_name = me["username"], me.get("first_name") or me["username"]
        return {"chat": self._bot_name, "bot": self._bot} if self._bot_name else {}

    def confirm_done(self, rid: str):
        """Код подтверждён — снять закреп с его сообщений."""
        for chat, mid in self.confirm_pins.pop(rid, []):
            with contextlib.suppress(TelegramError, OSError):
                self.pult.api("unpinChatMessage", chat_id=chat, message_id=mid)

    def admin_may(self, uid: int, by: str | None) -> dict:
        """Человек из списка, которого может менять ``by``: владелец — любого, кроме владельца; админ — только
        участников и наблюдателей (не других админов и не владельца)."""
        p = next((x for x in self.people.list() if x["id"] == uid), None)
        if not p or p["role"] == "owner":
            raise ValueError("такого человека нет в списке")
        if by != "owner" and p["role"] not in STAFF_ROLES:
            raise ValueError("админа меняет только владелец")
        return p

    def set_role(self, uid: int, role: str, by: str | None = "owner"):
        p = self.admin_may(uid, by)
        if by != "owner" and role not in STAFF_ROLES:
            raise ValueError("роль «админ» выдаёт только владелец")
        if role == "admin" and (p.get("kind") == "guest" or p.get("tenant")):
            raise ValueError("админ — только человек с Telegram и без демо-пространства")
        self.people.add(uid, role, p.get("name", ""), p.get("username", ""))

    def set_access(self, uid: int, days: int, by: str | None = "owner"):
        """Продлить доступ человека: на ``days`` дней от сейчас (0 — бессрочно)."""
        p = self.admin_may(uid, by)
        if days not in invites.ACCESS:
            raise ValueError("срок доступа: " + ", ".join(str(x) for x in invites.ACCESS) + " дней (0 — бессрочно)")
        self.people.add(uid, p["role"], p.get("name", ""), p.get("username", ""),
                        until=int(time.time() + days * 86400) if days else 0)
