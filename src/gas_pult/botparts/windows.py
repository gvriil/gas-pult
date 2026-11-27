"""Окна бота: состояние, активное окно, готовность к тексту и доставка в окно (замки, перепроверка, сторож
черновиков), строка статуса и «Сообщить по готовности», названия чатов, открыть/закрыть окно, ответы в чаты и
подсказки Claude.

Часть класса ``bot.Pult`` (модульный монолит, docs/MONOLITH-PLAN.md п.3.3): методы перенесены как есть, ``self`` —
тот же ``Pult``. ``PANEL``, ``PROMPT``, ``free``, ``KEYS``, ``DEFAULTS``, ``escalate_rows`` живут здесь; ``bot.*`` —
те же имена.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from gas_pult import (
    activity,
    ago,
    chatlog,
    country,
    ctxsnap,
    deliveries,
    funnel,
    harness,
    humanize,
    models,
    people,
    projects,
    secrets_guard,
    setup,
    teammsg,
    transcripts,
)
from gas_pult.botparts.base import HINT, QUESTION, AwaitsChoice, Denied, NotReady
from gas_pult.botparts.telegram import MENU
from gas_pult.humanize import BUSY, DIALOG
from gas_pult.people import has_telegram
from gas_pult.telegram import TelegramError, kb
from gas_pult.tmux import is_ours as tmux_is_ours
from gas_pult.tmux import prompt_draft

# Меню и панели (/status, /model, /config, /usage…): Esc безопасен — закрываем, иначе текст уйдёт в меню и пропадёт.
PANEL = re.compile(r"^\s*" + HINT + r"Esc to (cancel|close|exit|go back)|Settings\s+Status\s+Config", re.I | re.M)
PROMPT = re.compile(r"^\s*❯(?!\s*\d\.)", re.M)


def free(scr: str) -> bool:
    """Окно свободно для Enter: не идёт ход (нет «esc to interrupt»), нет вопроса, меню или диалога."""
    return not (BUSY.search(scr) or DIALOG.search(scr) or QUESTION.search(scr) or PANEL.search(scr))


KEYS = [("1", "1"), ("2", "2"), ("3", "3"), ("↑", "Up"), ("↓", "Down"), ("⏎", "Enter"), ("Esc", "Escape")]
DEFAULTS = {"notify": "all", "voice_always": False}


def escalate_rows(wid: str, level: int) -> list:
    """Кнопки под строкой статуса бота: 12 с без изменений — проверить, 20 с — сообщить по готовности, 60 с —
    остановить (Esc, с подтверждением)."""
    rows = [[("🔄 Проверить статус", f"scr:{wid}")]] if level >= 1 else []
    if level >= 2:
        rows.append([("🔔 Сообщить по готовности", f"nd:{wid}")])
    if level >= 3:
        rows.append([("⏹ Остановить", f"stop:{wid}")])
    return rows


class WindowsPart:
    """Окна, доставка и строка статуса (примесь к ``Pult``)."""

    # ---------- состояние ----------
    def state(self) -> dict:
        try:
            return {**DEFAULTS, "voice": self.cfg.voice, **json.loads(self.state_file.read_text())}
        except (OSError, ValueError):
            return {**DEFAULTS, "voice": self.cfg.voice}

    def set_state(self, **kw):
        with self.lock:
            s = {**self.state(), **kw}
            self.state_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.state_file.write_text(json.dumps(s))

    def fallback_logged(self, entry: dict):
        """Переключение на запасной — в state.json (последние 20): панель показывает его строкой."""
        log = list(self.state().get("fallback_log") or [])[-19:]
        self.set_state(fallback_log=[*log, entry])

    # ---------- окна ----------
    def projects(self) -> list[str]:
        dirs = [self.home]
        for root in self.cfg.roots():
            dirs += sorted(str(p) for p in root.glob("*/") if p.is_dir())
        return dirs

    def short(self, path: str) -> str:
        return "домашняя (~)" if path == self.home else os.path.basename(path)

    def active(self) -> dict | None:
        w = self.tmux.window(self.state().get("active") or "")
        return w if w and harness.is_agent(w) else None

    def need_active(self, chat: int) -> dict | None:
        w = self.active()
        if not w:
            self.send(chat, "Активного окна с Claude нет — выбери в 🔀 Переключить или 🆕 Новая.", reply_markup=MENU)
        return w

    def wait_ready(self, wid: str, limit: int = 40) -> bool:
        """Свежий Claude грузится несколько секунд — ждём строку ввода."""
        for _ in range(limit):
            scr = "\n".join(self.tmux.screen(wid))
            if "❯" in scr or DIALOG.search(scr):
                return True
            time.sleep(1)
        return False

    def ready_for_text(self, wid: str, limit: int = 40):
        """Довести окно до строки ввода: меню закрыть (Esc), на вопрос — не отвечать, свежий Claude — дождаться."""
        w = self.tmux.window(wid)
        if w and not harness.is_agent(w) and w.get("mark"):     # Claude завершился — в окне оболочка, не печатаем
            raise NotReady("Claude в этом окне остановлен — текст в командную строку не отправляю. Перезапустите "
                           "сессию: в панели «Перезапустить» или 🆕 в той же папке")
        if w and harness.of(w).name != "claude":           # экран другого агента (Pi): «❯», меню и вопросы — не Claude;
            return                                          # Pi принимает ввод и во время хода (ставит в очередь)
        escapes = 0
        for _ in range(limit):
            scr = "\n".join(self.tmux.screen(wid, 15))
            if QUESTION.search(scr):
                raise AwaitsChoice("Claude ждёт ответа на вопрос в этом окне — ответьте на экране (1 2 3 или Esc), "
                               "потом пишите")
            if PANEL.search(scr) and not BUSY.search(scr):
                if escapes >= 3:
                    raise NotReady("в окне открыто меню Claude и не закрывается — откройте «Экран» и нажмите Esc")
                self.tmux.keys(wid, "Escape")
                escapes += 1
                time.sleep(0.8)
                continue
            if PROMPT.search(scr):
                return
            time.sleep(1)
        raise NotReady("окно не готово к вводу 40 секунд — посмотрите «Экран»")

    @contextmanager
    def hold(self, wid: str):
        """В окно пишет кто-то один. Бот и панель — разные процессы, поэтому замок — файл (flock), а не threading.Lock;
        снимается сам, когда файл закрыт, — даже если процесс упал. Не вкладывать: второй hold того же окна ждёт."""
        self.locks.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(self.locks / (re.sub(r"[^\w@-]", "_", wid) + ".lock"), "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            yield

    source = threading.local()  # откуда текст (``via``): panel, focus, scheduler… — для журнала доставок

    @contextmanager
    def via(self, src: str):
        """Источник следующих ``to_claude`` этого потока — без нового параметра у всех вызовов."""
        old = getattr(self.source, "v", "")
        self.source.v = src
        try:
            yield
        finally:
            self.source.v = old

    def economy_model(self, w: dict) -> bool:
        """Экономия до сброса недельного лимита (владелец 24.11: «преимущественно дешёвые, чтобы дотянуть до
        обновления»): неделя подписки ≥ 70 % — чат на Opus перед ходом человека переходит на Sonnet (``/model sonnet``
        в самом чате, без перезапуска), один раз; в ленте чата — пометка. Не трогаем: модель, закреплённую в пульте
        (``window_models``), чаты пространств и других агентов, занятый или спящий чат. True — перевели."""
        try:
            if w.get("sleep") or w.get("space") or (w.get("profile") or "claude") != "claude" \
                    or harness.of(w).name != "claude":
                return False
            wk = (ctxsnap.limits() or {}).get("week")
            if not wk or wk["used"] < ctxsnap.WARN:
                return False
            st = self.state()
            econ = st.get("window_econ") or {}
            if (st.get("window_models") or {}).get(w["id"]) or w["id"] in econ:
                return False                                # человек выбрал модель сам или уже переводили
            if "opus" not in str((ctxsnap.read(w.get("sid") or "") or {}).get("model") or "").lower():
                return False
            if BUSY.search("\n".join(self.tmux.screen(w["id"]))):
                return False                                # занят — переведём при следующем ходе
            self.run_slash(w["id"], "/model sonnet")
            self.set_state(window_econ={**econ, w["id"]: wk["resets_at"]})
            teammsg.TeamMsgs(self.cfg.data / teammsg.FILE).say(
                {"w": w["id"], "sid": w.get("sid") or ""},
                f"Экономия до {ctxsnap.day(wk['resets_at'])}: чат переведён на Sonnet — неделя подписки "
                f"{wk['used']} %. Вернуть Opus — выберите модель в чате.")
            return True
        except Exception as e:                               # экономия не должна мешать доставке сообщения
            print("экономия:", e, flush=True)
            return False

    def to_claude(self, w: dict, text: str, src: str = "") -> bool:
        """Текст в окно (вставка и Enter) — одно для бота, панели, фокус-ссылок и расписания. ``src`` — откуда
        (panel, focus, bot, scheduler…; пусто — бот, если действует человек из Telegram, иначе «pult»): пишется в журнал
        доставок ``sends.jsonl`` вместе с итогом вставки. После удачной вставки — перепроверка в фоне (``recheck``)."""
        uid = getattr(self.actor, "uid", None)             # из бота — человек; из панели и монитора — проверено там
        src = src or getattr(self.source, "v", "") or ("bot" if uid is not None else "pult")
        if uid is not None and not models.allowed(w.get("profile") or "claude", self.countries(uid)):
            raise Denied(country.DENY)
        if self.cost_paused(w["id"]):                       # пауза по расходу — пока владелец не решит
            raise NotReady("сессия на паузе по расходу — продолжить может владелец (кнопка в боте или в панели)")
        self.economy_model(w)                               # неделя ≥ 70 %: Opus → Sonnet перед ходом (24.11)
        sends = getattr(self, "sends", None)               # строка статуса: «Отправлено» → «Доставлено» (activity.py)
        deliv = getattr(self, "deliv", None)
        if sends:
            sends.sent(w["id"], text)
        if w.get("sleep"):                                  # спит (claude-sleep): не ждём «❯» — будим этим текстом
            with self.hold(w["id"]):
                self.tmux.wake(w["id"], text)
            if deliv:
                deliv.record(w["id"], src, text, res="woke")
            if sends:
                sends.delivered(w["id"])
            return True
        try:
            with self.hold(w["id"]):
                self.ready_for_text(w["id"])
                last = getattr(self.tmux, "last_paste", None)
                if last is not None:
                    last.r = None
                ok = self.tmux.paste(w["id"], text) is not False
                r = dict(getattr(last, "r", None) or {"ok": ok, "result": "sent" if ok else "stuck"})
                if deliv:
                    deliv.record(w["id"], src, text, res=r["result"], after=r.get("after"))
                if not r["ok"]:                                  # Enter не прошёл и после повторов
                    raise NotReady("текст остался в поле ввода сессии и не отправлен — откройте «Экран» и нажмите "
                                   "Enter или отправьте ещё раз")
        except Exception:
            if sends:
                sends.failed(w["id"])
            raise
        if sends:
            sends.delivered(w["id"])
        if deliv and self.RECHECK:
            threading.Thread(target=self.recheck_safe, args=(w, text, src), daemon=True).start()
        return True                                         # вставка прошла — «Доставлено в сессию»

    # ---------- перепроверка доставки: текст не остался в поле ввода? ----------
    RECHECK = (3.0, 10.0, 30.0)        # с после доставки; пусто — не перепроверять
    DRAFT_WAIT = 120.0                 # с: столько наш текст висит в поле ввода, прежде чем сторож монитора скажет
    DRAFT_WITHIN = 3600.0              # сторож узнаёт доставки пульта за последний час

    def recheck_safe(self, w: dict, text: str, src: str = ""):
        try:
            self.recheck(w, text, src)
        except Exception as e:                              # фоновая перепроверка не должна ронять процесс
            print("recheck:", e, flush=True)

    def recheck(self, w: dict, text: str, src: str = "", sleep=time.sleep) -> str:
        """Через 3, 10 и 30 с после доставки смотрим поле ввода окна. Там наш текст, а окно свободно (не идёт ход, нет
        вопроса или меню) — Enter ещё раз и запись «redelivered». Висит и через 30 с — «не отправлено»: строка статуса
        и одно сообщение владельцу с кнопкой «Отправить». В занятое окно и в диалог Enter вслепую не жмём.
        Итог: «gone» — ушёл, «unsent» — висит, «gone-window» — окна нет."""
        waited = 0.0
        last = len(self.RECHECK) - 1
        for i, at in enumerate(self.RECHECK):
            sleep(at - waited)
            waited = at
            try:
                left = self.tmux.draft(w["id"], dim=True)
                scr = "\n".join(self.tmux.screen(w["id"], 15))
            except (OSError, RuntimeError, subprocess.SubprocessError):
                return "gone-window"
            if not left or not tmux_is_ours(left, text):
                return "gone"
            if not free(scr):
                continue                                    # ход идёт или открыт вопрос — подождать
            if i == last:
                break
            with self.hold(w["id"]):
                self.tmux.keys(w["id"], "Enter")
            self.deliv.record(w["id"], src, text, res="redelivered", step=int(at))
        self.unsent(w, text, src)
        return "unsent"

    def unsent(self, w: dict, text: str, src: str = "", why: str = "") -> bool:
        """Наш текст висит в поле ввода: «не отправлено» в строке статуса и одна строка владельцу с кнопкой
        «Отправить» (жмёт Enter после проверки). Об одном тексте в одном окне говорим один раз."""
        h = deliveries.sha(text)
        if self.deliv.notified(w["id"], h):
            return False
        self.deliv.record(w["id"], src, text, res="unsent", why=why or None)
        if sends := getattr(self, "sends", None):
            sends.unsent(w["id"])
        try:
            self.broadcast(f"⚠️ «{w.get('name') or w['id']}»: сообщение не отправлено — висит в поле ввода "
                           f"({len(text)} знаков).", reply_markup=kb([[("⏎ Отправить", f"rs:{w['id']}:{h}")]]))
        except Exception as e:                              # Telegram недоступен — строка статуса всё равно есть
            print("unsent:", e, flush=True)
        return True

    def push_enter(self, wid: str, h: str = "", sleep=time.sleep) -> str:
        """Кнопка «Отправить» (бот, панель): Enter — только если в поле ввода наш текст и окно свободно."""
        w = self.tmux.window(wid)
        if not w or not harness.is_agent(w):
            return "Окна уже нет."
        left = self.tmux.draft(wid, dim=True)
        rec = self.deliv.match(wid, left, within=6 * 3600) if left else None
        if not rec or (h and rec.get("sha") != h):
            return "В поле ввода уже нет этого текста — нажимать нечего."
        if not free("\n".join(self.tmux.screen(wid, 15))):
            return "Сейчас в окне идёт ход или открыт вопрос — ответьте там или нажмите позже."
        with self.hold(wid):
            self.tmux.keys(wid, "Enter")
        sleep(1.5)
        left = self.tmux.draft(wid, dim=True)
        ok = not left or not deliveries.matches(left, rec)
        self.deliv.record(wid, "button", None, sha=rec.get("sha"), head=rec.get("head"),
                          res="redelivered" if ok else "unsent-again")
        if ok and (sends := getattr(self, "sends", None)):
            sends.delivered(wid)
        return "✅ Отправлено." if ok else "Не ушло и сейчас — откройте «Экран»: возможно, фокус не в поле ввода."

    def draft_watch(self, w: dict, lines: list[str], now: float | None = None) -> bool:
        """Сторож монитора (раз в 3 с): в поле ввода окна наш текст (доставка пульта за последний час), висит дольше
        ``DRAFT_WAIT`` и окно свободно — то же уведомление, что у перепроверки. Чужой черновик (человек печатает
        в окне сам) — не трогаем и не говорим. True — уведомили."""
        if getattr(self, "deliv", None) is None:
            return False
        if getattr(self, "drafts", None) is None:
            self.drafts = {}
        now = time.time() if now is None else now
        wid = w["id"]
        left = prompt_draft(lines, dim=True)
        rec = self.deliv.match(wid, left, self.DRAFT_WITHIN) if left else None
        if not rec:
            self.drafts.pop(wid, None)
            return False
        key, since = self.drafts.get(wid, ("", now))
        if key != rec["sha"]:
            self.drafts[wid] = (rec["sha"], now)
            return False
        if now - since < self.DRAFT_WAIT or not free("\n".join(lines[-15:])) or self.deliv.notified(wid, rec["sha"]):
            return False
        self.deliv.record(wid, "watch", None, sha=rec["sha"], head=rec["head"], len=rec.get("len"), res="unsent",
                          why="draft")
        if sends := getattr(self, "sends", None):
            sends.unsent(wid)
        try:
            self.broadcast(f"⚠️ «{w.get('name') or wid}»: сообщение не отправлено — висит в поле ввода "
                           f"({rec.get('len', '?')} знаков) больше {int(self.DRAFT_WAIT // 60)} мин.",
                           reply_markup=kb([[("⏎ Отправить", f"rs:{wid}:{rec['sha']}")]]))
        except Exception as e:
            print("draft watch:", e, flush=True)
        return True

    # ---------- строка статуса: что агент делает сейчас (activity.py) ----------
    FOLLOW_EVERY = 3.5          # с между правками служебного сообщения (лимиты Telegram на правки)
    ESCALATE = (12, 20, 60)     # с без хода и смены фазы: «Проверить статус» → «Сообщить по готовности» → «Остановить»
    NOTIFY_TTL = 3600           # «Сообщить по готовности» ждёт конца хода не дольше часа
    FOLLOW_MAX = 3600           # с: дольше часа не следим — строка остаётся последней известной

    def screen_state(self, wid: str) -> dict:
        """Экран окна для строки статуса: занят ли Claude, вопрос/меню, текст спиннера."""
        lines = self.tmux.screen(wid)
        scr = "\n".join(lines)
        busy = bool(BUSY.search(scr))
        return {"busy": busy, "dialog": bool(DIALOG.search(scr)), "spinner": activity.spinner(lines) if busy else "",
                "tokens": activity.tokens(lines) if busy else 0.0}

    def activity(self, w: dict, screen: dict | None = None) -> dict:
        """Статус окна: журнал (последний ход), запись об отправке и экран (``screen``; нет — читаем сами)."""
        h = harness.of(w)
        if h.name in harness.JOURNAL_ONLY:               # Pi, OpenCode, Hermes: статус хода — по их журналу
            j = h.status(h.journal(w["path"], sid=w.get("sid") or ""))
        else:
            j = self.acts.status(w["path"], self.home_of(w), w.get("sid") or "", harness.of(w))
        scr = screen if screen is not None else self.screen_state(w["id"])
        rec = self.sends.get(w["id"])
        if rec and rec.get("unsent_at") and not self.still_unsent(w["id"]):   # отправили руками или стёрли
            self.sends.taken(w["id"])
            rec = None
        return activity.combine(j, rec, scr, sends=self.sends, wid=w["id"])

    def still_unsent(self, wid: str) -> bool:
        """В поле ввода окна всё ещё текст из журнала доставок (за 6 ч)?"""
        try:
            left = self.tmux.draft(wid, dim=True)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            return False
        return bool(left) and self.deliv.match(wid, left, within=activity.UNSENT_KEEP) is not None

    def to_claude_live(self, chat: int, w: dict, text: str):
        """Сообщение человека в окно и одно служебное сообщение «⏳ Отправлено», которое бот правит по фазам.

        Ключ, токен или пароль в сообщении — в окно уходит текст с заглушкой «[скрыт: тип]» (``secrets_guard``),
        человеку — пояснение: модель значения не видела, ключ — в «Подключения», сообщение в Telegram — удалить."""
        text, found = secrets_guard.redact(text)
        if found:
            try:
                self.send(chat, f"🔒 Убрал из сообщения: {', '.join(found)} — модель значения не увидит, в сессию ушла "
                                "заглушка. Положите ключ в «Подключения» панели пульта, а это сообщение удалите из "
                                "Telegram: ключ остался в переписке.")
            except TelegramError as e:
                print("secrets:", e, flush=True)
        mid = None
        try:
            mid = self.send(chat, self.to_head(w) + activity.line({"phase": "sent"}), wid=w["id"]).get("message_id")
        except TelegramError as e:
            print("status:", e, flush=True)
        try:
            self.to_claude(w, text)
            self.product("send", chat, via="bot")
        except Exception:
            if mid:                                    # не дошло — служебное сообщение убрать, причину скажет handle
                try:
                    self.api("deleteMessage", chat_id=chat, message_id=mid)
                except TelegramError:
                    pass
            raise
        if mid:
            threading.Thread(target=self.follow, args=(chat, mid, w), daemon=True).start()

    def to_head(self, w: dict) -> str:
        """«→ [название чата] » перед строкой статуса: видно, в какой чат ушло сообщение (#178)."""
        return f"→ [{self.label(w)}] " if w.get("name") else ""

    def follow(self, chat: int, mid: int, w: dict, clock=time.time, sleep=time.sleep):
        """Правит одно сообщение по фазам — не чаще раза в ``FOLLOW_EVERY`` с и только когда текст изменился.
        Новое сообщение в то же окно — прежнее служебное убираем. Правка не удалась (сообщение удалено) — тихо стоп.
        «Ждёт вашего ответа» — вопрос присылает монитор (``show_dialog``), здесь — только строка."""
        key, token, t0 = (chat, w["id"]), object(), clock()
        with self.lock:
            old = self.following.get(key)
            self.following[key] = (token, mid)
        if old and old[1] != mid:
            try:
                self.api("deleteMessage", chat_id=chat, message_id=old[1])
            except TelegramError:
                pass
        head = self.to_head(w)
        shown, took, level = head + activity.line({"phase": "sent"}), False, 0
        prog, prog_at = "", t0                           # последняя смена фазы или шага — для эскалации
        try:
            while self.following.get(key, (None,))[0] is token and clock() - t0 < self.FOLLOW_MAX:
                sleep(self.FOLLOW_EVERY)
                if self.following.get(key, (None,))[0] is not token:
                    return
                try:
                    st = self.activity(w)
                except Exception as e:                   # журнал или экран не прочитались — попробуем в следующий раз
                    print("status:", e, flush=True)
                    continue
                now = clock()
                if (key2 := f"{st['phase']}|{st.get('text', '')}") != prog:
                    prog, prog_at = key2, now
                took = took or st["phase"] not in ("sent", "delivered", "queued", "stuck")
                end = took and st["phase"] in ("done", "idle")
                failed = st["phase"] == "failed"             # ход не начался за 5 мин — сбой, дальше не следим
                if end:
                    text = f"✅ Готово · {activity.elapsed(now - t0)}"
                elif failed:
                    text = f"⚠️ {st['text']}. Посмотрите экран: Esc — остановить, потом отправьте ещё раз"
                else:
                    since = st.get("since") or now               # таймер — шагом 5 с: меньше правок
                    text = activity.line({**st, "since": now - (now - since) // 5 * 5}, now, started=took)
                text = head + text
                lv = 0 if end or failed or st["phase"] in ("done", "idle", "waiting") else \
                    sum(now - prog_at >= x for x in self.ESCALATE)
                if (text != shown or lv != level) and self.pause_until <= now:
                    rows = escalate_rows(w["id"], lv)
                    if st["phase"] in ("stuck", "failed") and not rows:
                        rows = [[("📺 Экран", f"scr:{w['id']}")]]
                    kw = {"reply_markup": kb(rows)} if rows else {}
                    try:
                        self.api("editMessageText", chat_id=chat, message_id=mid, text=text, **kw)
                        shown, level = text, lv
                    except TelegramError as e:
                        if e.retry_after:
                            self.pause_until = time.time() + e.retry_after
                        elif "not modified" not in e.description:
                            return                       # удалили или править нельзя — тихо прекращаем
                if end or failed:
                    return
        finally:
            with self.lock:
                if self.following.get(key, (None,))[0] is token:
                    self.following.pop(key, None)

    # ---------- «Сообщить по готовности» (строка статуса панели и бота) ----------
    def ask_notify_done(self, wid: str, chat) -> str:
        """Запомнить в state.json (его видят и панель, и бот): кому написать, когда ход в окне закончится. Одно
        сообщение на человека, без повторов; следит монитор бота (``notify_done_check``)."""
        if chat is None:
            raise ValueError("не знаю, кому писать")
        if not has_telegram(chat):
            raise ValueError("у вас не привязан Telegram — «Настройки» → «Привязать Telegram»")
        with self.lock:
            nd = dict(self.state().get("notify_done") or {})
            rec = nd.get(wid) or {}
            to = sorted({int(x) for x in rec.get("to", [])} | {int(chat)})
            nd[wid] = {"to": to, "at": int(time.time())}
        self.set_state(notify_done=nd)
        return "Хорошо — пришлю одно сообщение в бот, когда ход закончится."

    def notify_done_check(self, ws: list[dict], screens: dict[str, str], st: dict, now: float | None = None):
        """Ход закончился (Claude был занят и освободился) или ждёт ответа — одно сообщение тем, кто просил, и запись
        удаляется. Окна нет или прошёл час — запись забывается молча."""
        nd = st.get("notify_done") or {}
        if not nd:
            return
        seen = self.__dict__.setdefault("nd_busy", set())     # окна, где после просьбы видели «занят» (в памяти)
        now, by_id, left, said = now or time.time(), {w["id"]: w for w in ws}, {}, []
        for wid, rec in nd.items():
            w, scr = by_id.get(wid), screens.get(wid, "")
            if not w or now - rec.get("at", 0) > self.NOTIFY_TTL:
                continue
            dialog, busy = bool(DIALOG.search(scr)), bool(BUSY.search(scr))
            if busy:
                seen.add(wid)
            if (busy or wid not in seen) and not dialog:
                left[wid] = rec
                continue
            seen.discard(wid)
            text = f"🔔 «{self.label(w)}»: " + ("ждёт вашего ответа" if dialog
                                                 else "ход закончен — ответ в панели и здесь")
            said += [(c, text) for c in rec.get("to", [])]
        if left != nd:
            self.set_state(notify_done=left)
        for chat, text in said:
            self.notify(chat, text)
        if said:
            self.push_owners(said[-1][1])

    def cost_paused(self, wid: str) -> bool:
        return getattr(self, "cfg", None) is not None and wid in (self.state().get("cost_paused") or {})

    def run_slash(self, wid: str, cmd: str) -> list[str]:
        """Слэш-команда как с клавиатуры — одна для бота и панели; через 2,5 с — экран (меню или ответ)."""
        with self.hold(wid):
            self.ready_for_text(wid)                   # открытое меню закрыть, на вопрос Claude — не печатать
            self.tmux.type(wid, cmd)
            time.sleep(0.3)
            self.tmux.keys(wid, "Enter")
        time.sleep(2.5)
        return self.tmux.screen(wid, 40)

    def slash(self, chat: int, w: dict, cmd: str):
        """Меню (/model, /mcp) монитор пришлёт сам, остальное — экраном; к /status — когда сессия менялась."""
        if not DIALOG.search("\n".join(self.run_slash(w["id"], cmd)[-25:])):
            when = ago.line(self.stamps(w)) if cmd == "/status" else ""
            wk = ctxsnap.week_text((ctxsnap.limits() or {}).get("week")) if cmd == "/status" else ""   # 24.11
            self.send_screen(chat, w, cmd + (f"\n🕓 {when}" if when else "") + (f"\n📊 {wk}" if wk else ""))

    def stamps(self, w: dict) -> dict:
        """Когда сессия менялась (ago.py): последний ход в журнале или смена экрана, ответ агента, ваше сообщение."""
        return ago.stamps(self.acts.status(w["path"], self.home_of(w), w.get("sid") or "", harness.of(w)),
                          self.changes.at(w["id"]))

    def screen_msg(self, w: dict, title: str) -> tuple[str, dict]:
        return (f"[{self.label(w)}] {title}\n\n" + "\n".join(self.tmux.screen(w["id"])),
                {"reply_markup": kb([[(t, f"key:{w['id']}|{k}") for t, k in KEYS]])})

    def send_screen(self, chat: int, w: dict, title: str):
        text, kw = self.screen_msg(w, title)
        self.send(chat, text, wid=w["id"], **kw)

    def project_window(self, path: str) -> dict | None:
        """Окно Claude, уже работающее в этой папке (правило: одно окно на проект)."""
        real = os.path.realpath(path)
        return next((w for w in self.tmux.windows()
                     if harness.is_agent(w) and os.path.realpath(w["path"]) == real), None)

    def folder_window(self, path: str) -> dict | None:
        """Любое окно этой папки (в том числе с остановленным Claude) — для запуска по расписанию в нём же."""
        real = os.path.realpath(path)
        return next((w for w in self.tmux.windows() if os.path.realpath(w["path"]) == real), None)

    def claude_dir(self, uid) -> Path | None:
        """Папка Claude Code человека для новых окон; владелец — None (``~/.claude``)."""
        return people.claude_dir(self.cfg.data, uid, self.cfg.owners)

    LABEL_TTL = 30.0

    def label(self, w: dict) -> str:
        """Название чата для человека (владелец 19.11: «номера убрать, оставлять смысловой контекст»): своё название
        (projects.json) → название по смыслу из журнала (projects.title_of, #317) → «Новый чат». Служебное имя окна
        (gas-pult-1835) человеку не показываем; маршрут ответа — по id окна (tgroutes), не по имени."""
        if not harness.is_agent(w):
            return "Терминал"                                # окно без агента — не «чат»
        cache = self.__dict__.setdefault("_labels", {})
        hit = cache.get(w.get("id"))
        if hit and time.time() - hit[0] < self.LABEL_TTL:
            return hit[1]
        sid, t = w.get("sid") or "", ""
        try:
            if sid:
                d = json.loads((self.cfg.data / projects.FILE).read_text(encoding="utf-8"))
                t = str(((d.get("sessions") or {}).get(sid) or {}).get("title") or "")
            if not t and harness.of(w).name == harness.DEFAULT:   # журнал по смыслу — только у Claude Code
                f = transcripts.current(w.get("path", ""), self.home_of(w), sid)
                t = projects.title_of(f) if f else ""
        except (OSError, ValueError, AttributeError):
            t = ""
        out = t if t and not projects.is_status(t) else "Новый чат"
        cache[w.get("id")] = (time.time(), out)
        return out

    def home_of(self, w: dict) -> Path | None:
        """Папка Claude Code окна: того, кто его открыл (``@gas_pult_by``), а не того, кто сейчас нажал."""
        return people.home_of(w, self.cfg.data)

    def open_session(self, chat: int, name: str, path: str, first: str | None = None):
        if not setup.installed(self.cfg.claude):
            return self.show_setup(chat)
        if w := self.project_window(path):
            self.set_state(active=w["id"])
            self.send(chat, f"↪️ В {self.short(path)} уже работает «{self.label(w)}» — пишу туда (одно окно на проект).")
            if first:
                self.to_claude(w, first)
            return
        uid = getattr(self.actor, "uid", None)
        if uid is not None and not models.allowed("claude", self.countries(uid)):
            return self.send(chat, country.DENY)
        try:
            home = self.claude_dir(chat)                # чат с ботом — личный: chat = Telegram ID того, кто открыл
            sid = str(uuid.uuid4())                     # свой журнал окна (--session-id, метка @gas_pult_sid)
            wid = self.tmux.new_window(name, path, models.with_home(self.cfg.claude, home) + f" --session-id {sid}",
                                       by=str(chat) if home else "", sid=sid)
            if uid is not None and not home:            # окно владельца — тоже с меткой: запасные по его странам
                self.tmux.run("set-option", "-w", "-t", wid, "@gas_pult_by", str(uid))
        except (RuntimeError, OSError) as e:
            return self.send(chat, f"Не вышло: {e}")
        self.set_state(active=wid)
        self.send(chat, f"✅ Окно «{name}» с Claude в {self.short(path)} — активно. Пиши сюда, ответы придут сами.")
        if first:
            time.sleep(3)
            if w := self.tmux.window(wid):
                self.to_claude(w, first)

    QUIT_WAIT, QUIT_STEP = 20.0, 0.5                # длинная переписка: Claude выходит дольше 4 с — ждём до 20 с

    def quit(self, w: dict) -> str:
        """Выйти из Claude штатно (/exit — переписка сохранится) и закрыть окно — одно для бота и панели.
        «closed» — закрыто; «background» — у сессии фоновые задачи, не закрываем; «busy» — Claude не вышел."""
        return self.quit_ex(w)["result"]

    def quit_ex(self, w: dict) -> dict:
        """То же, что ``quit``, плюс ``draft`` — неотправленный текст из поля ввода (Ctrl+C его стирает): его
        возвращаем, чтобы показать человеку, а не потерять молча. Выход ждём до ``QUIT_WAIT`` с, опрос — раз в
        ``QUIT_STEP`` с; Claude вышел, а окно с оболочкой осталось — окно закрываем."""
        with self.hold(w["id"]):
            try:
                draft = self.tmux.draft(w["id"])
            except (OSError, RuntimeError, subprocess.SubprocessError):
                draft = ""
            self.tmux.keys(w["id"], "C-c")
            self.tmux.type(w["id"], "/exit")
            self.tmux.keys(w["id"], "Enter")
            end = time.monotonic() + self.QUIT_WAIT
            while True:
                time.sleep(self.QUIT_STEP)
                cur = self.tmux.window(w["id"])
                if cur is None:                            # окно закрылось вместе с Claude
                    return {"result": "closed", "draft": draft}
                if "Enter to confirm" in "\n".join(self.tmux.screen(w["id"])):
                    self.tmux.keys(w["id"], "Escape")
                    return {"result": "background", "draft": draft}
                if not harness.is_agent(cur):
                    self.tmux.kill(w["id"])
                    return {"result": "closed", "draft": draft}
                if time.monotonic() >= end:
                    return {"result": "busy", "draft": draft}

    def close(self, chat: int, w: dict):
        if not harness.is_agent(w):
            self.tmux.kill(w["id"])
            return self.send(chat, f"«{self.label(w)}» завершена.")
        r = self.quit_ex(w)
        tail = f"\n\nЧерновик из поля ввода (не отправлен):\n{r['draft']}" if r["draft"] else ""
        force = kb([[("⛔ Закрыть принудительно", f"fclose:{w['id']}"), ("Нет", "noop:")]])
        if r["result"] == "background":
            return self.send(chat, f"«{self.label(w)}» не завершена: у сессии есть фоновые задачи, они бы "
                                   "остановились. Закрыть принудительно? Переписка останется в журнале." + tail,
                             reply_markup=force)
        if r["result"] == "busy":
            return self.send(chat, f"«{self.label(w)}»: Claude не вышел за {self.QUIT_WAIT:.0f} с (возможно, занят). "
                                   "Посмотри 📺 Экран или закрой принудительно." + tail, reply_markup=force)
        self.focus.end_window(w["id"])   # фокус-ссылки этой сессии гаснут
        self.send(chat, f"«{self.label(w)}» завершена." + tail)

    def remember(self, w: dict, text: str) -> int:
        with self.lock:
            self.counter += 1
            self.answers[self.counter] = (w["id"], text)
            for old in [k for k in self.answers if k <= self.counter - 100]:
                del self.answers[old]
            return self.counter

    def ev(self, name: str, mid: str = "", **kw):
        """Событие в журнал чата (chatlog); журнала нет (бот собран в тесте без __init__) — молча дальше."""
        if (log := getattr(self, "events", None)) is not None:
            log.event(name, mid, **kw)

    def product(self, ev: str, uid, **kw):
        """Событие продукта (funnel.py) от человека ``uid``; пространство — его (``people.tenant``). Воронки нет
        (бот собран в тесте без __init__) — молча дальше; ошибка воронки доставку не ломает."""
        fn = getattr(self, "funnel", None)
        if fn is None or uid is None:
            return
        try:
            sp = self.people.tenant(uid) or "" if getattr(self, "people", None) else ""
            if ev == "send":
                fn.send(uid, sp, **kw)
            elif ev == "first_reply":
                fn.replied(uid, sp, **kw)
            else:
                fn.event(ev, uid, sp, **kw)
        except Exception as e:  # аналитика не ломает работу пульта
            print("funnel:", e, flush=True)

    def product_pick(self, uid, wid: str, n: str = "", key: str = ""):
        """Ответ на вопрос агента кнопкой (номер пункта или клавиша): «Да» / «Нет» — событием продукта."""
        if getattr(self, "funnel", None) is None or (not n and key not in ("Enter", "Escape")):
            return
        try:
            yn = funnel.choice(humanize.parse(self.tmux.screen(wid, 60)), n=n, key=key)
        except Exception:
            return
        if yn:
            self.product(yn, uid, via="bot")

    # ---------- монитор: ответы и диалоги всех окон ----------
    def deliver(self, w: dict, text: str):
        n = self.remember(w, text)
        rows, msgs = [[("🔊", f"say:{n}"), ("✅ Да", f"yes:{w['id']}"), ("✏️ Ответить", f"act:{w['id']}")]], {}
        to = {chat: self.channels(chat, "answer") for chat in self.cfg.owners}
        for chat in self.cfg.owners:
            if "telegram" not in to[chat]:
                continue
            try:
                msgs[chat] = self.send_answer(chat, f"[{self.label(w)}]", text, wid=w["id"],
                                              reply_markup=kb(rows)).get("message_id")
                self.ev("answer_tg", w=w["id"], len=len(text), sha=chatlog.sha(text))
                self.product("first_reply", chat, via="bot")
            except TelegramError as e:
                print("send:", e, flush=True)
                self.ev("answer_tg_fail", w=w["id"], code=e.description[:60],
                                  err=str(e)[:120])
        self.hint_wait[w["id"]] = {"t": time.time(), "msgs": msgs, "rows": rows}
        for chat, ch in to.items():                              # ответ — и на телефон, если выбран
            if "push" in ch:
                self.push_one(chat, text, w["id"], title=self.label(w))
        self.cmds.offer(w, text, self.broadcast, kb)
        if self.state()["voice_always"]:
            for chat in self.cfg.owners:
                threading.Thread(target=self.say, args=(chat, text), daemon=True).start()

    def offer_hints(self):
        """Подсказка Claude появляется через секунды после ответа — дописываем к ответу кнопку «💡 …» (ждём 90 с)."""
        for wid, x in list(self.hint_wait.items()):
            if time.time() - x["t"] > 90:
                self.hint_wait.pop(wid, None)
                continue
            if not (h := self.tmux.hint(wid)):
                continue
            self.hint_wait.pop(wid, None)
            with self.lock:
                self.counter += 1
                n = self.counter
                self.hints[n] = (wid, h)
                for old in [k for k in self.hints if k <= n - 100]:
                    del self.hints[old]
            label = "💡 " + (h if len(h) <= 40 else h[:39].rstrip() + "…")
            for chat, mid in x["msgs"].items():
                try:
                    self.api("editMessageReplyMarkup", chat_id=chat, message_id=mid,
                             reply_markup=kb([*x["rows"], [(label, f"hint:{n}")]]))
                except TelegramError as e:
                    print("hint:", e, flush=True)
