"""Демо-пространства: приглашения и вход по приглашению, тестировщики («Позвать на помощь», бюджет, задача от
владельца), пространство в панели, первый вход и сессии пространства (закрыть, продолжить, удалить, вернуть).

Часть класса ``webapp.Panel`` (модульный монолит, docs/MONOLITH-PLAN.md п.3.1): методы перенесены как есть, ``self`` —
тот же ``Panel``.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from datetime import date, timedelta

from gas_pult import (
    country,
    emailcode,
    focus,
    harness,
    invites,
    qr,
    repos,
    space_budget,
    space_sessions,
    spaces,
    tenants,
    testers,
    usage,
    webauth,
)
from gas_pult.humanize import BUSY
from gas_pult.people import TITLES
from gas_pult.telegram import TelegramError


class SpacesPart:
    """Пространства, тестировщики, приглашения, вход по приглашению, сессии пространства (примесь к ``Panel``)."""

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

    def invite_info(self, code: str, short: bool = False) -> dict:
        """Экран входа по приглашению: действует ли и в какое пространство (название — без путей и ролей).
        ``guest`` — можно войти без Telegram (только именем); ``kind=device`` — ссылка для входа на другое устройство
        уже существующего человека (имя не спрашиваем)."""
        rec = invites.check(code, short)            # короткий код — только из invite_check (с лимитом попыток)
        if not rec:
            return {"ok": False}
        t = tenants.load(rec["tenant"]) if tenants.enabled() else None
        out = {"ok": True, "title": (t or {}).get("title") or rec["tenant"], "guest": tenants.enabled(),
               "kind": "device" if "uid" in rec and not rec.get("person") else "invite"}
        if "name" in rec or rec.get("person"):         # одна ссылка: «Здравствуйте, <имя>!» → «Начать»
            p = next((x for x in self.people.list() if x["id"] == rec.get("uid")), {}) if "uid" in rec else {}
            out["welcome"], out["name"] = True, rec.get("name") or p.get("name") or "Гость"
        elif "uid" in rec:
            p = next((x for x in self.people.list() if x["id"] == rec["uid"]), {})
            out["name"] = p.get("name") or ""
        return out

    def invite_check(self, code: str, ip: str) -> dict:
        """Короткий код с экрана входа («Есть код приглашения?»): не больше 5 промахов с IP за 10 минут."""
        self.invite_guard(ip)
        info = self.invite_info(code, short=True)
        if not info["ok"] or not info["guest"]:
            self.invite_miss(code, ip)
        return info

    def invite_guard(self, ip: str):
        if not tenants.enabled():
            raise ValueError("вход по приглашению на этом пульте выключен")
        if wait := self.invite_misses.blocked(ip):
            raise emailcode.LimitError(f"слишком много неверных кодов — попробуйте через {max(1, wait // 60)} мин.",
                                       wait)

    def invite_miss(self, code: str, ip: str):
        self.invite_misses.miss(ip)
        emailcode.log("invite_failed", ip=ip, hint=invites.norm_short(code)[:3] + "…" if code else "")
        raise ValueError("Код не подошёл: проверьте буквы и цифры. Код работает один раз и 24 часа — если он уже "
                         "использован, попросите новый.")

    def invite_enter(self, code: str, name: str, ip: str, ua: str) -> int:
        """Вход по ссылке или короткому коду без Telegram. Приглашение — новый гость (имя → сразу панель);
        ссылка для входа на другое устройство — сессия того, кому её выпустили. Код сгорает."""
        self.invite_guard(ip)
        rec = invites.check(code)
        if not rec:
            self.invite_miss(code, ip)
        dev = webauth.device(ua)
        if "uid" in rec:                                      # другое устройство: тот же человек
            uid = int(rec["uid"])
            if not self.people.role(uid) or not invites.redeem(code, uid):
                self.invite_miss(code, ip)
            how = "с нового устройства по ссылке-приглашению" if rec.get("person") else \
                "по ссылке для входа на другое устройство"
        else:
            name = rec.get("name") or name                    # одна ссылка: имя дал владелец (или «Гость»)
            name = " ".join(str(name or "").split())[:60]
            if not name:
                raise ValueError("Напишите, как вас зовут — так вас увидит владелец пульта")
            uid = self.people.add_guest(name, rec["role"], rec["tenant"], until=invites.until_of(rec),
                                        plan=rec.get("plan", ""))
            if not invites.redeem(code, uid, bind="uses" in rec):   # v2: ссылка привязывается к человеку
                self.people.remove(uid)
                self.invite_miss(code, ip)
            how = "по приглашению, без Telegram"
            self.space_welcome(uid, rec["tenant"])
        self.people.seen(uid, dev)
        p = next((x for x in self.people.list() if x["id"] == uid), {})
        emailcode.log("invite_ok", uid=uid, ip=ip, hint=rec.get("hint", ""), kind="device" if "uid" in rec else "guest")
        t = tenants.load(rec["tenant"]) or {}
        text = (f"🎟 {p.get('name') or 'Гость'} вошёл {how} — пространство «{t.get('title') or rec['tenant']}», "
                f"{TITLES.get(p.get('role'), '')}.\nУстройство: {dev} · {time.strftime('%d.%m %H:%M')}.\n"
                "Убрать — «Настройки» → «Люди» → «Отключить»: все его входы гаснут сразу.")
        for chat in self.cfg.owners:
            try:
                self.pult.api("sendMessage", chat_id=chat, text=text)
            except (TelegramError, OSError) as e:
                print("invite:", e, file=sys.stderr, flush=True)
        return uid

    def device_link(self, uid: int, by) -> dict:
        """Ссылка для входа на другое устройство: одноразовая, 24 часа; выпускает сам человек или владелец."""
        role = self.people.role(uid)
        if not role or role == "owner":
            raise ValueError("ссылку для входа можно выпустить только человеку из «Людей»")
        slug = self.people.tenant(uid)
        if not slug or not tenants.enabled():
            raise ValueError("ссылка для входа — для тестировщиков демо-пространства")
        inv = invites.new(slug, role, by=by, uid=int(uid))
        return {"path": f"/invite/{inv['code']}", "code": inv["short"], "ttl": invites.TTL}

    def invite_qr(self, url: str, owner: bool, uid) -> bytes:
        """PNG с QR ссылки ``…/invite/<код>``: только для действующего приглашения; не владельцу — только своей ссылки
        для входа на другое устройство."""
        m = re.match(r"^https?://[A-Za-z0-9.:\[\]-]{1,200}/invite/([A-Za-z0-9_-]{16,64})$", url)
        rec = invites.check(m.group(1), short=False) if m else None
        if not rec or (not owner and rec.get("uid") != uid):
            raise LookupError("приглашения нет: истёк срок, оно использовано или отозвано")
        return qr.png_of(url)

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
        if rid := focus.rid_of(uid):                       # по ссылке на пространство — её название (GAS-38)
            person = {"id": uid, "name": f"Гость по ссылке «{(self.focus._load().get(rid) or {}).get('name', '')}»"}
        text, kb = testers.help_message(person, slug, w, self.pult.panel_url())
        for chat in self.cfg.owners:
            try:
                self.pult.api("sendMessage", chat_id=chat, text=text, **({"reply_markup": kb} if kb else {}))
            except (TelegramError, OSError) as e:
                print("help:", e, file=sys.stderr, flush=True)
        return {"ok": True}

    def space_budget(self, slug: str, fresh: bool = False) -> dict | None:
        """Запас пространства на период (space_budget.py): норма × дни + пополнения, расход по дням (журналы, цены
        API; на подписке — оценка). Бюджета нет — None. Кэш 10 с: список сессий спрашивает часто."""
        hit = self.budget_cache.get(slug)
        if hit and not fresh and time.time() - hit[0] < 10:
            return hit[1]
        t = tenants.load(slug) or {}
        cfg = t.get("budget")
        if not cfg:
            return None
        today = date.today()
        first, _ = space_budget.period(cfg, today)
        home = tenants.paths(slug)["claude"]
        accs = self.pult.meter.days(home, first.isoformat(), detail=True) if home.is_dir() else {}
        seen = {d: round(x["usd"], 4) for d, x in accs.items()}
        spent = space_budget.remember(slug, seen, first)     # максимум записанного: прошлые дни не уменьшаются
        b = space_budget.state(cfg, spent, today, space_budget.extra(slug, first),
                               estimate=(t.get("profile") or "") == "claude",
                               source=usage.source(usage.merge(*accs.values())))
        b["text"] = space_budget.text(b)
        self.budget_cache[slug] = (time.time(), b)
        return b

    def budget_watch(self, slug: str, b: dict):
        """Владельцу — на 80% и 100% запаса (раз за период; после пополнения — заново) и при потолке дня (раз в день);
        с кнопкой «+ добавить»."""
        t = tenants.load(slug) or {}
        title = t.get("title") or slug
        end = date.fromisoformat(b["end"]).strftime("%d.%m")
        msgs = []
        if (x := space_budget.warn_due(slug, b)) is not None:
            if x >= 1:
                msgs.append(f"💸 Запас пространства «{title}» исчерпан: ${b['spent']:.2f} из ${b['reserve']:.2f} "
                            f"(период до {end}). Тестировщик не может писать агенту до нового периода или пополнения.")
            else:
                msgs.append(f"⚠️ Пространство «{title}» потратило {round(b['pct'] * 100)}% запаса: ${b['spent']:.2f} "
                            f"из ${b['reserve']:.2f} (период до {end}). {b['text'][0].upper() + b['text'][1:]}.")
        today = time.strftime("%Y-%m-%d")
        if b["reason"] == "day" and self.budget_told.get(slug) != today:
            self.budget_told[slug] = today
            msgs.append(f"⏸ Пространство «{title}» дошло до потолка дня: ${b['today']:.2f} из ${b['day_cap']:.2f}. "
                        "Тестировщик продолжит завтра — или пополните запас.")
        kb = {"inline_keyboard": [[{"text": "➕ Добавить", "callback_data": f"bt:{slug}"}]]}
        for text in msgs:
            for chat in self.cfg.owners:
                try:
                    self.pult.api("sendMessage", chat_id=chat, text=text, reply_markup=kb)
                except (TelegramError, OSError) as e:
                    print("budget:", e, file=sys.stderr, flush=True)

    def check_budget(self, slug: str):
        """Тестировщик пишет, отвечает или открывает сессию: запас периода исчерпан (или потолок дня) — отказ
        (ValueError) с понятным текстом; владельцу — сообщения (budget_watch)."""
        b = self.space_budget(slug, fresh=True)
        if not b:
            return
        self.budget_watch(slug, b)
        if not b["over"]:
            return
        if b["reason"] == "day":
            raise ValueError(f"На сегодня потрачен потолок дня (${b['today']:.2f} из ${b['day_cap']:.2f}). Завтра "
                             "можно продолжить — владелец получил сообщение.")
        nxt = (date.fromisoformat(b["end"]) + timedelta(days=1)).strftime("%d.%m")
        raise ValueError(f"Запас пространства на период исчерпан (${b['spent']:.2f} из ${b['reserve']:.2f}). Владелец "
                         f"получил сообщение и может пополнить запас; новый период — с {nxt}.")

    def budget_add(self, slug: str, usd: float, by: int | None = None) -> dict:
        """«+ добавить» из панели владельца: пополнить запас текущего периода."""
        t = tenants.load(slug) or {}
        if not t.get("budget"):
            raise ValueError("у пространства нет бюджета — sudo bin/pult-tenant create <slug> --budget <USD>")
        first, _ = space_budget.period(t["budget"], date.today())
        space_budget.top_up(slug, usd, first, by)
        return self.space_budget(slug, fresh=True)

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
        wid = self.new_in_space(slug, name)["id"]       # своя папка, как у сессий тестировщика
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
                    with self.pult.via("panel"):
                        self.pult.to_claude(w, text)
                    return True
                except Exception as e:                    # не готов ещё — пробуем, пока не выйдет время
                    why = str(e)
            time.sleep(2)
        print(f"задание в {wid} не отправлено: {why}", flush=True)
        return False

    # терминал и расход пространству — открыты (владелец 20.11: «весь функционал, чтобы не было вырезано»; GAS-38):
    # терминал — за «режимом разработчика» и только своё пространство, расход — бюджет пространства, не владельца
    SPACE_HIDE = frozenset({"cap.audit_journal"})

    def space_info(self, uid) -> dict | None:
        """Пространство тестировщика для панели: имя, название, вид. Не тестировщик — None."""
        slug = self.people.tenant(uid)
        if not slug:
            return None
        t = tenants.load(slug) if tenants.enabled() else None
        return {"slug": slug, "title": (t or {}).get("title") or slug, "ready": t is not None,
                "persona": (t or {}).get("persona") or tenants.DEFAULT_PERSONA}

    FIRST_PROJECT = "Мой проект"

    def space_welcome(self, uid: int, slug: str, accept: bool = True):
        """Вход по приглашению в пространство — сразу внутри (владелец 19.11: «онбординг простой — не спрашивать ни про
        страну, ни про что: если человек по ссылке попал — он уже проверен; он должен сразу начинать пользоваться»):
        условия отмечены приглашением владельца, страна — юрисдикция пространства (нет — регион сервера), первая
        сессия «Мой проект» — если в пространстве ещё нет ни одной. Сбой сессии не мешает входу."""
        t = tenants.load(slug) or {}
        if accept:                                      # ссылка «для клиента» — соглашается сам (terms_line)
            self.people.accept(uid)
        code = country.norm(t.get("jurisdiction")) or country.norm(self.cfg.region) or "NL"
        self.people.set_country(uid, chosen=code)
        try:
            with self.tmux.all_spaces():
                if not self.space_windows(slug) and not space_sessions.listing(slug):
                    self.new_in_space(slug, self.FIRST_PROJECT)
        except Exception as e:                          # sudo, tmux, диск — вход всё равно состоялся
            print(f"пространство {slug}: первая сессия не открылась: {e}", file=sys.stderr, flush=True)

    # ---------- сессии пространства: закрыть, продолжить, удалить в корзину (space_sessions.py) ----------
    def space_windows(self, slug: str) -> list[dict]:
        return [w for w in self.tmux.windows() if w.get("space") == slug]

    def space_list(self, slug: str) -> dict:
        """Закрытые сессии (папки без окна) и корзина — для «Закрытые» в панели тестировщика."""
        open_paths = {w.get("path", "") for w in self.space_windows(slug)} | space_sessions.open_paths(slug)
        drafts = self.space_drafts().get(slug, {})
        closed = [{**x, "draft": bool(drafts.get(x["folder"]))} for x in space_sessions.closed(slug, open_paths)]
        return {"closed": [{k: v for k, v in x.items() if k != "path"} for x in closed],
                "trash": space_sessions.trash_list(slug), "keep_days": space_sessions.KEEP_DAYS}

    def space_drafts(self) -> dict:
        try:
            return json.loads((self.cfg.data / "space-drafts.json").read_text())
        except (OSError, ValueError):
            return {}

    def space_draft_set(self, slug: str, folder: str, text: str):
        d = self.space_drafts()
        if text:
            d.setdefault(slug, {})[folder] = text[:20000]
        else:
            d.get(slug, {}).pop(folder, None)
        webauth.write_private(self.cfg.data / "space-drafts.json", json.dumps(d, ensure_ascii=False))

    def space_close(self, slug: str, wid: str, force: bool = False) -> dict:
        """«Закрыть»: агент выходит штатно, окно закрывается; папка, файлы и разговор остаются. Агент работает —
        без ``force`` не закрываем (``busy``: панель спросит «прервать работу?»). Черновик из поля — сохраняем."""
        w = self.tmux.window(wid)
        if not w or w.get("space") != slug:
            raise LookupError("окна уже нет")
        folder = os.path.basename(w.get("path", ""))
        if not harness.is_agent(w):                          # Claude уже вышел — окно с оболочкой просто закрыть
            self.tmux.kill(wid)
            return {"result": "closed", "folder": folder, "draft": ""}
        if not force and BUSY.search("\n".join(self.tmux.screen(wid, 40))):
            return {"result": "busy", "folder": folder}
        r = self.pult.quit_ex(w)
        if r["result"] == "busy" and force:               # не вышел за 20 с — закрываем окно (разговор в журнале)
            self.tmux.kill(wid)
            r["result"] = "closed"
        if r.get("draft"):
            self.space_draft_set(slug, folder, r["draft"])
        return {"result": r["result"], "folder": folder, "draft": r.get("draft", "")}

    def space_resume(self, slug: str, folder: str) -> dict:
        """«Продолжить»: окно в папке сессии — ``claude --continue`` (тот же разговор); черновик — обратно в поле."""
        path = space_sessions.check_folder(slug, folder)
        if any(w.get("path") == str(path) for w in self.space_windows(slug)) or space_sessions.is_open(slug, path):
            raise ValueError("эта сессия уже открыта")
        if folder not in {x["folder"] for x in space_sessions.listing(slug)}:
            raise LookupError("нет такой сессии")
        args = "--continue" if space_sessions.has_history(slug, path) else ""
        args = (repos.flags(self.pult.state(), str(path)) + " " + args).strip()   # подключённые репозитории
        raw = tenants.new_window(slug, folder, str(path), args=args)
        draft = self.space_drafts().get(slug, {}).get(folder, "")
        if draft:
            self.space_draft_set(slug, folder, "")
        return {"id": spaces.wid_of(slug, raw), "draft": draft, "continued": bool(args)}

    def space_delete(self, slug: str, folder: str, confirm: str) -> dict:
        """«Удалить»: только закрытую сессию и только с именем во втором подтверждении — в корзину на KEEP_DAYS."""
        path = space_sessions.check_folder(slug, folder)
        if confirm != folder:
            raise ValueError("для удаления введите имя сессии точно")
        if any(w.get("path") == str(path) for w in self.space_windows(slug)) or space_sessions.is_open(slug, path):
            raise ValueError("сессия открыта — сначала закройте её")
        out = space_sessions.trash(slug, folder)
        self.space_draft_set(slug, folder, "")
        return {**out, "keep_days": space_sessions.KEEP_DAYS}

    def space_restore(self, slug: str, tid: str) -> dict:
        return {"folder": space_sessions.restore(slug, tid)}
