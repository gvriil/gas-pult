"""Монитор бота: ответы и вопросы окон, лимиты подписки, автоархив, расход, сводки и брифинг, предохранитель цепочек,
автотест поставщиков, сбои панели и красный CI (alerts.py).

Часть класса ``bot.Pult`` (модульный монолит, docs/MONOLITH-PLAN.md п.3.3): методы перенесены как есть, ``self`` —
тот же ``Pult``. ``NOISE`` и ``dialog_hash`` живут здесь; ``bot.NOISE``, ``bot.dialog_hash`` — те же имена.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import threading
import time
from datetime import datetime

from gas_pult import (
    alerts,
    brief,
    chainfuse,
    ctxsnap,
    digest,
    fallback,
    features,
    harness,
    humanize,
    limitretry,
    notifylevel,
    selftest,
    transcripts,
    usage,
)
from gas_pult import tmux as tmux_mod
from gas_pult.botparts.base import QUESTION, Denied, NotReady
from gas_pult.humanize import BUSY, DIALOG
from gas_pult.telegram import TelegramError, kb

# Строка статуса и таймеры меняются каждые секунды — в отпечаток меню их не берём, иначе «изменение» без конца.
NOISE = re.compile(r"🤖|ctx used|⏵⏵|esc to interrupt|^\s*[✻✶✳✢·*]\s", re.I)


def dialog_hash(scr: str) -> str:
    return hashlib.md5("\n".join(x for x in scr.splitlines() if not NOISE.search(x)).encode()).hexdigest()



def ask_title(scr: str) -> str:
    """Первая строка сообщения о вопросе: вопрос агента словами (владелец 24.11: «варианты видно, а вопроса не видно»),
    иначе — «Claude ждёт выбора:»."""
    try:
        a = humanize.parse(scr)
    except Exception:                                   # разбор экрана не должен ломать уведомление
        a = None
    if a and a.get("kind") == "question" and a.get("title_ru"):
        return "❓ " + (f"{a['header']}: " if a.get("header") else "") + a["title_ru"]
    return "Claude ждёт выбора:"

class MonitorPart:
    """Монитор, лимиты, автоархив, расход, сводки, брифинг, предохранитель, автотест (примесь к ``Pult``)."""

    def show_dialog(self, w: dict, scr: str, shown: dict):
        """Открытое меню/вопрос = одно сообщение каждому владельцу; изменилось — правим его, без новых уведомлений."""
        h, ep, now = dialog_hash(scr), shown.get(w["id"]), time.time()
        if ep and (ep["hash"] == h or now - ep["t"] < 4):
            return
        text, kw = self.screen_msg(w, ask_title(scr))
        msgs = ep["msgs"] if ep else {}
        for chat in self.cfg.owners:
            ch = self.channels(chat, "dialog")
            if "push" in ch and not ep:                          # новый вопрос — и на телефон
                self.push_one(chat, f"«{self.label(w)}» ждёт вашего выбора", w["id"], title=self.label(w))
            if "telegram" not in ch:
                continue
            try:
                if chat in msgs:
                    try:
                        self.api("editMessageText", chat_id=chat, message_id=msgs[chat], text=text[:4000], **kw)
                        continue
                    except TelegramError as e:
                        if "not modified" in e.description:
                            continue                     # то же самое — ничего не делаем; иначе (удалили) — заново
                msgs[chat] = self.send(chat, text, wid=w["id"], **kw).get("message_id")
            except TelegramError as e:
                print("send:", e, flush=True)
        shown[w["id"]] = {"msgs": msgs, "hash": h, "t": now}

    TRUST_EVERY = 10.0

    def trust_auto(self, w: dict, scr: str) -> bool:
        """Вопрос Claude Code «доверять файлам этой папки? 1. Да 2. Нет» — человеку его не показываем (владелец и
        Алексей 20.11: «выбор 1/2/3 обычный пользователь видеть не должен»): папка окна — папка, которую пульт сам
        открыл для этого человека, поэтому отвечаем «Да» (Enter на пункте 1). Раньше отвечал только поток при
        создании окна и только 30 с — при перезапуске, пробуждении и медленном старте вопрос оставался на экране.
        В журнал чата — событие ``trust_auto``: админ видит, что произошло."""
        keys = tmux_mod.trust_keys(scr)
        if not keys:
            return False
        last = self.__dict__.setdefault("_trust_at", {})
        if time.time() - last.get(w["id"], 0) < self.TRUST_EVERY:   # Enter уже нажат — ждём, пока экран сменится
            return True
        last[w["id"]] = time.time()
        for k in keys:                                  # Claude Code 2.1.330: курсор — на «No, exit», сначала вниз
            self.tmux.keys(w["id"], k)
        self.ev("trust_auto", w=w["id"], path=w.get("path", ""), keys=len(keys))
        return True

    def monitor(self):
        tail, turns, shown = transcripts.Tail(time.time()), {}, {}
        while True:
            try:
                self.after_pause()
                st = self.state()
                ws = [w for w in self.tmux.windows() if harness.is_agent(w) and not w["channel"]]
                by_path: dict[tuple, list[dict]] = {}   # окна в одной папке пишут в общий каталог транскриптов
                for w in ws:                            # (у человека со своей папкой Claude — свой каталог)
                    by_path.setdefault((w["path"], self.home_of(w)), []).append(w)
                for (path, home), group in by_path.items():
                    # журнал окна со своей меткой (--session-id) — этому окну; остальные — окну без метки (старый
                    # способ: активному из них или первому), а если таких нет — активному или первому в папке
                    sids = {v: x for x in group if (v := transcripts.valid_sid(x.get("sid")))}
                    legacy = [x for x in group if not transcripts.valid_sid(x.get("sid"))]
                    pick = legacy or group
                    w0 = next((x for x in pick if x["id"] == st.get("active")), pick[0])
                    files, got = transcripts.transcripts(path, home), {}
                    tail.watch(f"{home}|{path}" if home else path, files)    # старое не пересылаем
                    for f in files:
                        w = sids.get(f.stem, w0)
                        for e in tail.read(f):
                            self.fallback.seen(w["id"], e)      # ошибка API поставщика — ждём остановки окна
                            if text := turns.setdefault(f, transcripts.Turns()).feed(e):
                                got.setdefault(w["id"], (w, []))[1].append(text)
                    for w, texts in got.values():
                        if not notifylevel.wants(st, w["id"], "answer"):    # уровень окна: «все» — с ответами
                            continue
                        if len(texts) > self.BURST:            # пачка за 3 с — сбой, а не переписка
                            self.broadcast(f"[{self.label(w)}] пропущено ответов: {len(texts) - 1} — они в панели. "
                                           "Последний:", kind="answer")
                        for text in texts[-1:] if len(texts) > self.BURST else texts:
                            self.deliver(w, text)
                self.pi_answers([w for w in ws if harness.of(w).name in harness.JOURNAL_ONLY], st)
                screens: dict[str, str] = {}
                for w in ws:
                    quiet = not notifylevel.wants(st, w["id"], "dialog")   # «тихо» — и вопросы не шлём
                    lines = self.tmux.screen(w["id"])
                    scr = screens[w["id"]] = "\n".join(lines)
                    if self.trust_auto(w, scr):                 # «доверять папке?» — пульт отвечает сам (20.11)
                        continue
                    self.changes.look(w["id"], lines)
                    self.draft_watch(w, lines)                  # наш текст висит в поле ввода дольше 2 мин?
                    if w["id"] in self.fallback.pending:        # сессия стоит на ошибке, человек не набирает
                        idle = not BUSY.search(scr) and not DIALOG.search(scr)
                        self.fallback.step(w, idle and not fallback.typing(lines, self.tmux.hint(w["id"])))
                    if not DIALOG.search(scr):
                        shown.pop(w["id"], None)
                    elif not quiet:
                        self.show_dialog(w, scr, shown)
                self.notify_done_check(ws, screens, st)
                self.retry_tick(ws, screens, st)
                self.auto_close_tick()
                self.offer_hints()
                self.cost_watch(st)
                self.fail_tick()                        # признак жизни и сводка сбоев панели (alerts.py)
            except Exception as e:
                print("monitor:", self.api.redact(e), flush=True)
            time.sleep(3)

    ERR_EVERY = 300                                     # с: новые server_error и js_error — смотрим раз в 5 минут
    CI_EVERY = 600                                      # с: CI main через gh — раз в 10 минут

    def fail_tick(self, now: float | None = None):
        """Отметка ``heartbeat-bot`` (не чаще раза в минуту) и сводка сбоев панели владельцу: не чаще раза в
        30 минут на класс, без текстов и персональных данных (alerts.py, docs/ALERTS.md)."""
        cfg = getattr(self, "cfg", None)
        if cfg is None or not getattr(cfg, "data", None):      # заготовка бота в тестах — без папки данных
            return
        now = time.time() if now is None else now
        alerts.beat(cfg.data, "bot", now)
        if now - getattr(self, "errs_at", 0) < self.ERR_EVERY:
            return
        self.errs_at = now
        for text in alerts.Watch(self.cfg.data).errors(self.events, now):
            self.broadcast(text, kind="error")
        for text in alerts.Watch(self.cfg.data).connectors(self.events, now):   # коннектор потерял вход (connwatch)
            self.broadcast(text, kind="error")

    def ci_tick(self, now: float | None = None):
        """CI ``main`` красный дольше часа — одно сообщение владельцу, не чаще раза в 6 часов (alerts.py)."""
        now = time.time() if now is None else now
        if now - getattr(self, "ci_at", 0) < self.CI_EVERY:
            return
        self.ci_at = now
        if text := alerts.Watch(self.cfg.data).ci(alerts.main_ci(now=now), now):
            self.broadcast(text, kind="error", disable_web_page_preview=True)

    def pi_answers(self, ws: list[dict], st: dict):
        """Ответы окон Pi, OpenCode и Hermes — в Telegram, как ответы Claude Code (у Claude их ловит ``Tail``/``Turns``
        по журналам ``~/.claude``; у этих — свой журнал). Первый взгляд — только запоминаем: старое не пересылаем."""
        seen = self.__dict__.setdefault("pi_seen", {})
        start = self.__dict__.setdefault("pi_start", time.time())   # ответы до запуска бота — старые, не пересылаем
        for w in ws:
            h = harness.of(w)
            f = h.journal(w["path"], sid=w.get("sid") or "")
            if not f:
                continue
            at = h.answers_at(f)
            got = [t for _, t in at]
            # первый взгляд: старое — только написанное до запуска бота (окно открыли и Pi ответил за 3 с между
            # взглядами — первый ответ новый, его шлём; раньше считался «старым» и терялся)
            n = seen.get(str(f), sum(ts and ts < start - 5 for ts, _ in at))
            seen[str(f)] = len(got)
            if len(got) <= n or not notifylevel.wants(st, w["id"], "answer"):
                continue
            new = got[n:]
            if len(new) > self.BURST:
                self.broadcast(f"[{self.label(w)}] пропущено ответов: {len(new) - 1} — они в панели. Последний:",
                               kind="answer")
                new = new[-1:]
            for text in new:
                self.deliver(w, text)

    # ---------- один повтор после лимита подписки (limitretry.py, #189 п. 6) ----------
    def limit_wait(self, w: dict, text: str):
        """Окно встало на лимите подписки, запасных нет: один повтор на время сброса (запись на окно — одна)."""
        now = time.time()
        at = limitretry.reset_at(text, ctxsnap.limits(), now)
        if not at:
            return self.broadcast(f"⏳ [{self.label(w)}] упёрлась в лимит подписки; когда он сбросится — не знаю, "
                                  "напишите «продолжай» сами.")
        if at - now > limitretry.MAX_WAIT:
            return self.broadcast(f"⏳ [{self.label(w)}] упёрлась в лимит подписки до {limitretry.hhmm(at, now)} — это "
                                  "дольше 6 часов, сама не продолжу.")
        self.set_state(limit_retries=limitretry.schedule(self.state(), w["id"], self.label(w), at, now))
        self.broadcast(f"⏳ [{self.label(w)}] упёрлась в лимит подписки. Продолжу сама в {limitretry.hhmm(at, now)} — "
                       "один раз; напишете в сессию раньше — повтор снимется.",
                       reply_markup=kb([[("Не продолжать", f"rc:{w['id']}")]]))

    def retry_tick(self, ws: list[dict], screens: dict, st: dict):
        """Пора: окно свободно и человек сам не писал после остановки — «продолжай»; окна нет или писали — снять."""
        due = limitretry.due(st)
        if not due:
            return
        by, humans = {w["id"]: w for w in ws}, [r for r in self.deliv.recent(limitretry.MAX_WAIT + 3600)
                                                 if r.get("src") in ("panel", "bot", "focus")]
        for wid, r in due:
            w = by.get(wid)
            if w and any(h.get("w") == wid and h.get("ts", 0) > r["since"] for h in humans):
                w = None                                    # человек уже написал сам — повтор не нужен
            if w:
                scr = screens.get(wid, "")
                if BUSY.search(scr) or DIALOG.search(scr):
                    continue                                # занята — подождём следующего обхода
                try:
                    with self.via("retry"):
                        self.to_claude(w, limitretry.TEXT)
                    self.broadcast(f"▶️ [{self.label(w)}] лимит подписки обновился — написал «продолжай».")
                except Exception as e:                       # окно не готово — сказать, повтор снимаем
                    self.broadcast(f"⏳ [{r.get('name', wid)}] продолжить после лимита не вышло: {e}")
            self.set_state(limit_retries=limitretry.cancel(self.state(), wid))
    # ---------- автоархив: сессии без активности N дней закрываются (#189 п. 12, по умолчанию — никогда) ----------
    AUTO_CLOSE_EVERY = 600      # с между проверками

    def auto_close_tick(self, now: float | None = None) -> list[str]:
        """Окна без активности дольше ``auto_close_days`` закрыть: Claude выходит штатно, переписка — в журнале
        («Завершённые» проекта, «Продолжить»). Не трогаем: активное окно бота, окна пространств, окна с фоновыми
        задачами или занятые. Возвращает имена закрытых."""
        days = int(getattr(getattr(self, "cfg", None), "auto_close_days", 0) or 0)   # заготовки в тестах — без cfg
        now = time.time() if now is None else now
        if days <= 0 or now - getattr(self, "_ac_at", 0) < self.AUTO_CLOSE_EVERY:
            return []
        self._ac_at = now
        st, closed = self.state(), []
        for w in self.tmux.windows():
            if w.get("space") or w["id"] == st.get("active") or not (harness.is_agent(w) or w.get("stopped")):
                continue
            changed = self.stamps(w).get("changed")
            if not changed or now - changed < days * 86400:
                continue                                    # неизвестно, когда менялась, — не трогаем
            if w.get("stopped") or w.get("sleep"):          # Claude уже не работает — окно просто закрыть
                self.tmux.kill(w["id"])
            else:
                scr = "\n".join(self.tmux.screen(w["id"]))
                if BUSY.search(scr) or DIALOG.search(scr):
                    continue
                if self.quit_ex(w)["result"] != "closed":
                    continue                                # фоновые задачи или не вышла — оставляем
            self.focus.end_window(w["id"])
            closed.append(self.label(w))                    # человеку — название, не имя окна
        if closed:
            self.broadcast(f"🗄 Закрыты сессии без активности дольше {days} дн.: {', '.join(closed)}. Переписка — "
                           "в «Завершённых» проекта, «Продолжить» её поднимет.")
        return closed

    # ---------- расход: лимиты на сессию и на день (usage.py) ----------
    def pool_of(self, w: dict) -> str:
        """Чей расход: «owner» — учётка владельца (и окна, открытые на ней участником); иначе ID участника со своей
        папкой Claude Code. Чужие учётки в пул владельца не попадают."""
        if w.get("space"):                                  # окно демо-пространства (панель, spaces.py)
            return f"space:{w['space']}"
        return "owner" if self.home_of(w) is None else str(w.get("by"))

    def opened_by(self, w: dict) -> int | None:
        """Кто открыл окно на учётке владельца, если это не владелец (пометка на карточке)."""
        by = str(w.get("by") or "")
        return int(by) if by.isdigit() and int(by) not in self.cfg.owners and self.home_of(w) is None else None

    def cost_sessions(self, ws: list[dict] | None = None, today: str | None = None) -> list[dict]:
        """Окна Claude пула владельца с расходом текущей сессии — для проверки лимитов."""
        out = []
        for w in ws if ws is not None else self.tmux.windows():
            if not harness.is_agent(w) or self.pool_of(w) != "owner":
                continue
            s = self.meter.session(w["path"], None, today, w.get("sid") or "")
            if s:
                pub = usage.public(s["total"])
                out.append({"w": w["id"], "name": self.label(w), "sid": s["id"], "usd": pub["usd"],
                            "src": pub["cost_source"]})
        return out

    def cost_watch(self, st: dict, force: bool = False):
        """Раз в 10 с: лимиты заданы — сверить расход; превышение — Esc в занятое окно, пауза, один вопрос владельцу.
        Лимитов нет и пауз нет — ничего не читаем (поведение пульта прежнее)."""
        lim = usage.limits(st)
        if not force and (time.time() - self.cost_at < 10 or (not any(lim.values()) and not st.get("cost_paused"))):
            return
        self.cost_at = time.time()
        today = datetime.now().date().isoformat()
        sessions = self.cost_sessions(today=today)
        day = self.meter.day(None, today) if lim["day"] else usage.empty()
        upd, new = usage.watch(st, sessions, day["usd"], today)
        if upd != {k: st.get(k) or {} for k in upd}:
            self.set_state(**upd)
        for p in new:
            self.cost_pause(p)

    def cost_pause(self, p: dict):
        """Новая пауза: занятое окно — Esc (прервать ход; на вопрос Claude не отвечаем), владельцу — вопрос."""
        scr = "\n".join(self.tmux.screen(p["w"], 15))
        if BUSY.search(scr) and not QUESTION.search(scr):
            self.tmux.keys(p["w"], "Escape")
            paused = dict(self.state().get("cost_paused") or {})
            if p["w"] in paused:
                paused[p["w"]]["interrupted"] = True
                self.set_state(cost_paused=paused)
        # письмо и телефон — через ту же точку доставки (notifyroute.py): кто включил почту, получит письмо
        self.broadcast(usage.question(p), kind="dialog",
                       reply_markup=kb([[("▶️ Продолжить, +лимит", f"cost:go:{p['w']}"),
                                         ("⏹ Остановить", f"cost:stop:{p['w']}")]]))

    def cost_decide(self, wid: str, act: str) -> str:
        """Решение владельца (кнопка в боте или в панели) → state.json. «Продолжить» — окна, где ход прервали Esc,
        просим продолжить. Ответ — строка для человека."""
        st = self.state()
        before = dict(st.get("cost_paused") or {})
        upd, p = usage.decide(st, wid, act, datetime.now().date().isoformat())
        self.set_state(**upd)
        name = p.get("name") or wid
        if act == "stop":
            return f"⏹ «{name}» остаётся на паузе по расходу. Снять — «Продолжить» или новый лимит в настройках панели."
        resumed = 0
        for x, rec in before.items():
            if x in upd["cost_paused"] or not rec.get("interrupted") or not (w := self.tmux.window(x)):
                continue
            try:
                self.to_claude(w, "Продолжай с того места, где остановился.")
                resumed += 1
            except (NotReady, Denied) as e:
                print("cost:", e, flush=True)
        return f"▶️ «{name}»: пауза снята, лимит увеличен." + (" Claude продолжает." if resumed else "")

    # ---------- утренняя сводка «ждёт владельца» ----------
    def digest_items(self) -> list[dict]:
        items = []
        if self.cfg.digest_github:
            try:
                items += digest.prs(self.cfg.digest_github, time.time())
            except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as e:
                print("digest:", e, flush=True)
        for w in self.tmux.windows():
            claude = harness.is_agent(w) and harness.of(w).name == "claude"     # диалог — экран Claude Code
            if claude and DIALOG.search("\n".join(self.tmux.screen(w["id"]))):
                items.append({"kind": "win", "key": digest.key("win", w["id"]), "id": w["id"], "name": self.label(w)})
        return items + digest.handoffs(self.cfg.roots())

    def send_digest(self, chat: int | None = None):
        """Сводка сейчас: в чат (команда /digest) или всем владельцам (по расписанию; пусто — молчим)."""
        items = self.digest.fresh(self.digest_items(), time.time())
        if not items:
            return chat and self.send(chat, "☀️ Ничего не ждёт вашего решения.")
        text, kbd = digest.render(items)
        return self.send(chat, text, reply_markup=kbd) if chat else self.broadcast(text, kind="brief", reply_markup=kbd)

    # ---------- утренний брифинг первого лица (brief.py, GAS-18) ----------
    def brief_now(self, now: datetime | None = None, uid: int | None = None) -> dict:
        """Брифинг человека по его выбору источников; решения — пункты сводки и письма (кнопки dg:…)."""
        now = now or datetime.now()
        sel = brief.chosen(self.brief_prefs.get(uid or self.cfg.owners[0]), brief.available(self.cfg))
        return brief.collect(self.cfg, sel=sel, digest_items=self.digest_items(), tasks_list=self.tasks.list(),
                             now=now, night=self.alerts.night(now),
                             fresh=lambda xs: self.digest.fresh(xs, now.timestamp()))

    def send_brief(self, chat: int | None = None):
        """Брифинг: текстом, затем решения по одному с «Да / Нет / Позже» и «📱 Открыть в пульте».
        ``chat`` — кому (команда /brief или расписание этого владельца); без него — всем владельцам."""
        if not chat:
            return [self.send_brief(c) for c in self.cfg.owners][-1:] or None
        b = self.brief_now(uid=chat)
        self.alerts.new([r["key"] for r in brief.hot(b)], time.time(), woke=False)   # показали — ночью не будить
        panel = self.panel_url("brief")
        for c in [chat]:
            try:
                self.send(c, brief.telegram(b), parse_mode="HTML", disable_web_page_preview=True,
                          **({"reply_markup": {"inline_keyboard": [[{"text": "📱 Открыть в пульте",
                                                                     "web_app": {"url": panel}}]]}}
                             if panel and not b["decisions"] else {}))
                for i, r in enumerate(b["decisions"], 1):
                    text, kbd = brief.decision_msg(i, r, panel)
                    self.send(c, text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=kbd)
            except TelegramError as e:
                print("brief:", e, flush=True)
        return b

    def check_urgent(self, now: datetime):
        """Вне утра — только срочное (деньги, безопасность, срыв срока: ``notifylevel.wakes``), каждое — один раз."""
        b = self.brief_now(now)
        new = set(self.alerts.new([r["key"] for r in brief.hot(b)], now.timestamp()))
        for r in brief.hot(b):
            if r["key"] in new:
                text, kbd = brief.decision_msg(1, r, self.panel_url("brief"))
                self.broadcast("🚨 Срочно:" + text[2:], kind="brief", parse_mode="HTML", disable_web_page_preview=True,
                               reply_markup=kbd)

    def send_features(self, now: datetime):
        """Раз в месяц: что в панели не открывали 30 дней и что в ходу — владельцам и файлом usage-ГГГГ-ММ.md."""
        r = features.report(features.Uses(self.cfg.data / "features.json"), now.timestamp(),
                            month=features.previous(now))
        path = features.write(self.cfg.data, r)
        self.broadcast(features.telegram(r, path), kind="brief")

    def morning_tick(self, now: datetime):
        """Утро — одно сообщение: брифинг по расписанию каждого владельца (время, дни, пояс — его выбор; по
        умолчанию ``brief_at`` по рабочим дням) или прежняя сводка, если ``brief_at = ""``; вне утра — срочное."""
        sent = False
        if self.cfg.brief_at:
            for uid in self.cfg.owners:
                rec = self.brief_prefs.get(uid)
                if day := brief.due(brief.schedule(rec, self.cfg.brief_at), now, rec.get("sent", "")):
                    self.brief_prefs.mark_sent(uid, day)         # сначала отметка — не слать дважды
                    self.send_brief(uid)
                    sent = True
        if self.digest.due(self.cfg.brief_at or self.cfg.digest_at, now):
            self.digest.mark_sent(now.strftime("%Y-%m-%d"))
            if not self.cfg.brief_at:
                self.send_digest()
            self.send_testers()                                  # и сводка по тестировщикам (п. 8 задачи 31)
        elif not sent and self.cfg.brief_at and now.timestamp() - getattr(self, "urgent_at", 0) >= brief.URGENT_EVERY:
            self.urgent_at = now.timestamp()                     # правило тишины: срочное — раз в полчаса
            self.check_urgent(now)

    # ---------- предохранитель цепочек (GAS-25 п.3, chainfuse.py) ----------
    FUSE_EVERY, FUSE_QUIET = 60, 1800            # с: как часто смотреть; одну пару второй раз — не раньше чем через

    def fuse_tick(self, now: float):
        """Пинг-понг двух окон без человека — Escape в окно-получатель, штабу — текст в его окно (если он не в паре),
        и задача пульта «ждёт вас» (срочно и важно) со ссылкой на окна."""
        ws = {w["id"]: w for w in self.tmux.windows() if harness.of(w).name == "claude"}
        if len(ws) < 2:
            return
        since = now - chainfuse.GAP * (chainfuse.LIMIT + 2)
        human = {r.get("sha") for r in self.deliv.recent(now - since + 60) if r.get("src") in chainfuse.HUMAN_SRC}
        events = []
        for w in ws.values():
            f = transcripts.current(w["path"], sid=w.get("sid") or "")
            if f:
                events += chainfuse.read_events(f, w["id"], since, human)
        quiet = getattr(self, "fuse_quiet", {})
        self.fuse_quiet = quiet
        for c in chainfuse.detect(events):
            key = "|".join(sorted((c["a"], c["b"])))
            if now - quiet.get(key, 0) < self.FUSE_QUIET:
                continue
            quiet[key] = now
            a, b = ws.get(c["a"], {}), ws.get(c["b"], {})
            names = f"«{a.get('name', c['a'])}» ({c['a']}) и «{b.get('name', c['b'])}» ({c['b']})"
            self.tmux.keys(c["last"], "Escape")                  # прервать ход получателя; отправителя не трогаем
            text = (f"Предохранитель цепочек: окна {names} пишут друг другу по кругу — {c['n']} сообщений подряд, "
                    f"каждое меньше чем через {chainfuse.GAP // 60} мин, без человека. Ход в {c['last']} прерван "
                    "(Escape). Посмотрите, что они делают.")
            print("цепочка:", names, c["n"], flush=True)
            self.ev("chain_stop", w=c["last"], pair=key, n=c["n"])
            shtab = [w for w in ws.values() if str(w.get("name", "")).startswith("shtap")]
            if shtab and shtab[0]["id"] not in (c["a"], c["b"]):
                try:
                    self.to_claude(shtab[0], text, src="fuse")
                except Exception as e:                           # штаб занят — задача ниже всё равно будет
                    print("цепочка → штаб:", e, flush=True)
            try:
                self.tasks.add({"title": f"Цепочка агентов: {names}", "kind": "other", "status": "waiting", "q": 1,
                                "next": "открыть окна и решить, продолжать ли", "chat": c["last"]}, by="pult")
            except (ValueError, KeyError) as e:
                print("цепочка → задача:", e, flush=True)

    def digest_loop(self):
        while True:
            try:
                now = datetime.now()
                self.morning_tick(now)
                if now.timestamp() - getattr(self, "slept_at", 0) >= tmux_mod.SLEEP_EVERY:   # ждут ответа — спать
                    self.slept_at = now.timestamp()
                    tmux_mod.sleep_waiting(self.cfg.sleep_after_min)
                if now.timestamp() - getattr(self, "fused_at", 0) >= self.FUSE_EVERY:    # цепочки агентов
                    self.fused_at = now.timestamp()
                    try:
                        self.fuse_tick(now.timestamp())
                    except Exception as e:                       # предохранитель не мешает утру и отчётам
                        print("цепочки:", e, flush=True)
                try:
                    self.ci_tick(now.timestamp())                # красный main — владельцу (alerts.py)
                except Exception as e:
                    print("ci main:", e, flush=True)
                if features.due(self.cfg.data, now):             # 1-го числа — отчёт по функциям панели
                    features.mark_sent(self.cfg.data, now)
                    self.send_features(now)
            except Exception as e:
                print("digest:", self.api.redact(e), flush=True)
            time.sleep(60)

    # ---------- автотест поставщиков (selftest.py): раз в сутки и /selftest ----------
    def selftest_loop(self):
        """Раз в сутки — проверка всех поставщиков с ключом; что-то не прошло — одна строка владельцам."""
        time.sleep(300)                                   # не в первые минуты после запуска
        while True:
            try:
                if selftest.due(self.cfg.data, self.state()):
                    d = selftest.run_all(self.cfg.data, self.state())
                    if any(not all((r.get("checks") or {}).values()) for r in (d.get("results") or {}).values()):
                        self.broadcast(selftest.summary(self.cfg.data, self.state()))
            except Exception as e:
                print("selftest:", self.api.redact(e), flush=True)
            time.sleep(600)

    def on_selftest(self, chat: int):
        if selftest.running(selftest.load(self.cfg.data)):
            return self.send(chat, "Проверка уже идёт — итог появится в «Настройки» → «Поставщики» панели.")
        self.send(chat, "🧪 Проверяю поставщиков с ключом — пара минут, короткий запрос к каждому…")

        def go():
            selftest.run_all(self.cfg.data, self.state())
            self.send(chat, selftest.summary(self.cfg.data, self.state()))
        threading.Thread(target=go, daemon=True).start()
        return None

    def on_digest(self, chat: int, arg: str):
        """dg:y — «да» (PR и «да» штабу — с подтверждением dg:Y), dg:c — закрыть, dg:l — позже."""
        act, _, k = arg.partition(":")
        x, send = self.digest.item(k), self.to(chat)
        if not x:
            return send("Этот пункт уже не в сводке — пришлите /digest.")
        if act == "c":
            self.digest.snooze(k, digest.GONE)
            brief.log(self.cfg.data, chat, k, "no", x["kind"], "убрано на месяц")
            self.product("no", chat, via="digest")
            return send("Убрал из сводок на месяц.")
        if act == "l":
            self.digest.snooze(k, digest.LATER)
            brief.log(self.cfg.data, chat, k, "later", x["kind"], "до следующего брифинга")
            return send("Напомню в следующей сводке.")
        if x["kind"] == "mail":                            # письмо: «Да» — открыть его (отправки отсюда нет)
            return send(f"Письмо: {x['url']}" if x.get("url") else f"Письмо в ящике {x['box']}: «{x['subject']}».")
        if x["kind"] == "win":
            w = self.tmux.window(x["id"])
            return self.send_screen(chat, w, "Claude ждёт ответа:") if w else send("Этого окна уже нет.")
        if act == "y":
            ask = (f"Слить {x['repo']}#{x['n']} «{x['title']}»?" if x["kind"] == "pr"
                   else f"Передать «да» в окно {x['project']}: {x['text']}?")
            return send(ask,
                        reply_markup=kb([[("✅ Да", f"dg:Y:{k}"), ("Нет", "noop")]]))
        if x["kind"] == "pr":
            send(done := digest.merge(x["repo"], x["n"]))
        elif w := self.project_window(x["path"]):
            self.to_claude(w, f"Владелец отвечает «да» на пункт из HANDOFF.md: {x['text']}")
            send(done := f"Передал «да» в «{self.label(w)}».")
        else:
            return send(f"Окна с Claude в {x['project']} нет — откройте сессию (🆕 Новая) и повторите.")
        self.digest.snooze(k, digest.GONE)
        brief.log(self.cfg.data, chat, k, "yes", x["kind"], done)
        self.product("yes", chat, via="digest")
