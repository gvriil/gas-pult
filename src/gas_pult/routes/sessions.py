"""Маршруты области «Сессии и чат» (MONOLITH-PLAN §3.2, шаг 7): список сессий (опрос панели), бейджики первого
разговора и «Примерить на себя», фото в ленте, модель по умолчанию, строка статуса, экран окна и вопрос Claude
(``ask`` — карточка с вариантами, #464), подсказка, команды из ответа, «Шаги», переписка (``rev`` — журнал не менялся,
``team`` — сообщения команды), загрузка файла, новая сессия и папка, порядок и «Закрепить», оживить, закрыть,
«Сообщить по готовности», отправка (повтор, пустое, «Claude ждёт выбора» — 400 ``code=question``), «Отправить» ещё
раз, имя и название чата, активная в боте, уровень уведомлений, команда, модель и усилие, клавиша и пункт меню,
перезапуск.

Ветки перенесены из ``webapp.H.get``/``H.post`` как есть: ``self`` — обработчик запроса (``webapp.H``), ``panel`` —
его ``Panel``, ``build`` — версия страницы (``H.build``). Две ветки одного пути (``/api/new`` — в пространстве и нет,
``/api/active``, ``/api/model`` с ``keep``) — одна функция (``if path == P and X`` → ``if X``). Ветки после общего
``w = self.win(…)`` — ``GET_W``/``POST_W``: окно ищут ``H.get``/``H.post`` до вызова (нет — 404 «окна уже нет»,
остановлено — 404 со словами, как раньше). Общая часть ``post`` после ``self.win`` — своей долей в каждой функции,
как шла: «владелец пишет — тестировщик увидит» (``owner_seen``) — у ``/api/send``, ``/api/select``, ``/api/key``,
проверка страны поставщика (``panel.check``) — у них и у ``/api/command``, ``/api/model``. Загрузка — ``POST_RAW``
(тело читает сама, поток в файл). Права проверены до вызова — ``H.permit`` (``SPACE_OK``, ``OWNER_ONLY``,
``SLINK_NO``…), фокус- и демо-ссылка — ``H.focus_call`` (``FOCUS_*``, ``DEMO_*``, окно ссылки; демо-ответ
``Panel.demo_answer``, ``/api/sessions``, ``/api/media``, ``/api/close`` по ссылке — свои ветки ``H.focus_do``),
токен — ``H.v1_call``. Таблицы и подписи — ``routes/__init__.py``.
"""

import contextlib
import time
import urllib.parse

from gas_pult import (
    chatlog,
    ctxsnap,
    fallback,
    harness,
    humanize,
    notifylevel,
    scenarios,
    starters,
    steps,
    transcripts,
    webauth,
)
from gas_pult.access import NOTIFY_DONE
from gas_pult.commands import in_space
from gas_pult.panel.sessions import find_auth
from gas_pult.uploads import MAX_BODY, mark_bare, upload_log


def sessions_list(self, q: dict):
    """GET /api/sessions"""
    panel = self.panel
    build = self.build
    pool = self.pool()
    if self.space():                          # тестировщик: без имени сервера и событий владельца
        sp = panel.space_info(self.terms_uid()) or {}
        return {"sessions": panel.sessions(pool, self.pinner()), "host": sp.get("title", ""),
                "build": build,
                "now": time.time(), "cost": panel.cost_summary(pool), "fallback": [], "space": sp}
    with panel.tmux.all_spaces() if self.who()[1] in ("owner", "admin") else contextlib.nullcontext():
        ss = panel.sessions(pool, self.pinner())  # владелец: и окна пространств (группа «Пространства»)
    return {"sessions": ss, "host": panel.cfg.host, "build": build,
            "now": time.time(),                                   # часы сервера: «N назад» без сдвига
            "cost": panel.cost_summary(pool),
            # лимиты подписки (5 часов, неделя) и время сброса — учётка владельца, видит только он
            "limits": ctxsnap.limits() if self.who()[1] == "owner" else None,
            "tasks": panel.tasks.open_count() if self.who()[1] == "owner" else None,   # #203
            "fallback": [{k: x.get(k) for k in ("ts", "w", "text")}
                         for x in fallback.recent(panel.pult.state())]}


def starters_get(self, q: dict):
    """GET /api/starters — первый разговор: бейджики-сценарии (GAS-37)"""
    panel = self.panel
    return panel.starters_for(self.who()[1], bool(self.space()) or self.focused is not None,
                              self.space() or "", str(q.get("occ") or ""))


def scenarios_get(self, q: dict):
    """GET /api/scenarios — «Примерить на себя»: роли, день с агентом, польза"""
    errors: list[str] = []
    d = scenarios.api_data(errors)
    return {**d, "errors": errors if self.who()[1] == "owner" else []}


def media(self, q: dict):
    """GET /api/media — фото в ленте (16.11): картинки из inbox и с Диска"""
    panel = self.panel
    return panel.media(str(q.get("p") or ""))


def default_model_get(self, q: dict):
    """GET /api/model/default — владелец: модель Claude по умолчанию для новых сессий"""
    panel = self.panel
    return panel.default_model()


def activity(self, q: dict):
    """GET /api/activity — строка статуса чата: что агент делает сейчас"""
    panel = self.panel
    return panel.activity(str(q.get("w") or ""))


def last(self, q: dict, w: dict):
    """GET_W /api/last"""
    panel = self.panel
    return {"text": harness.of(w).last_answer(w["path"], panel.pult.home_of(w), w.get("sid") or "")}


def screen(self, q: dict, w: dict):
    """GET_W /api/screen"""
    panel = self.panel
    lines = panel.tmux.screen(w["id"], 60)
    return {"lines": lines[-40:], "auth": find_auth(lines), "login": self.login_of(w, lines),
            "ask": humanize.parse(lines, target=True)}     # карточка инструмента (#258), добавлено


def ask(self, q: dict, w: dict):
    """GET_W /api/ask — простой режим: вопрос Claude простыми словами и чипы"""
    panel = self.panel
    return {"ask": humanize.parse(panel.tmux.screen(w["id"], 60))}


def hint(self, q: dict, w: dict):
    """GET_W /api/hint"""
    panel = self.panel
    return {"hint": panel.tmux.hint(w["id"])}


def cmds(self, q: dict, w: dict):
    """GET_W /api/cmds"""
    panel = self.panel
    return {"cmds": panel.commands(w), "host": panel.cfg.host}


def steps_get(self, q: dict, w: dict):
    """GET_W /api/steps — «Шаги» (GAS-16, слой 7): сообщение → инструменты → ответ"""
    panel = self.panel
    if harness.of(w).name != "claude":
        return {"turns": [], "note": "шаги видны только у Claude Code"}
    f = transcripts.current(w["path"], panel.pult.home_of(w), w.get("sid") or "")
    return {"turns": steps.turns(f, q.get("q", ""))}


def history(self, q: dict, w: dict):
    """GET_W /api/history"""
    panel = self.panel
    before = int(q["before"]) if q.get("before", "").isdigit() else None
    sid = w.get("sid") or ""                   # окно со своим журналом — его переписка
    rev = harness.of(w).revision(w["path"], home := panel.pult.home_of(w), sid)
    team = panel.team_for(w) if before is None else []   # сообщения команды (teammsg.py) — добавлено
    if before is None and q.get("rev") and q["rev"] == rev:
        return {"same": True, "rev": rev, "team": team}   # журнал не менялся — переписку не пересчитываем
    items, more = harness.of(w).history(w["path"], 30, before, home=home, sid=sid)
    for it in items:                           # ошибка Claude Code — ещё и простыми словами (простой режим)
        if it.get("role") == "assistant" and (h := humanize.error(it.get("text") or "", strict=True)):
            it["human"] = h
    self.product_seen(items)
    return {"items": items, "more": more, "rev": rev, **({"team": team} if before is None else {})}


def upload(self):
    """POST /api/upload — поток в файл, не в память; ``w`` — проект на Диске"""
    panel = self.panel
    w = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query)).get("w", "")
    if w and self.focused and not panel.focus_owns(self.focused, w):
        w = ""                               # фокус-ссылка — только её сессия; чужая — в inbox
    if self.raw is not None:
        return {"path": panel.upload(self.headers.get("X-File-Name", "file"), self.raw, w=w)}
    n = int(self.headers.get("Content-Length", 0))
    if n > MAX_BODY:
        raise ValueError("слишком большой запрос")
    t0 = time.monotonic()
    out = {"path": panel.upload(self.headers.get("X-File-Name", "file"), self.rfile, size=n, w=w)}
    upload_log(n, time.monotonic() - t0, "focus" if self.focused else self.via())
    return out


def starter(self, b: dict):
    """POST /api/starter — нажали бейджик: текст агенту + замер (без текста)"""
    panel = self.panel
    sid = str(b.get("id", ""))[:40]
    panel.events.event("starter", "", starter=sid, w=str(b.get("w") or "")[:40])
    wid = str(b.get("w") or "")             # «добавь задачу» — только в чатах владельца (задачи — его)
    try:                                    # без tmux (macOS в CI, сбой) — бейджик всё равно работает
        win = next((x for x in panel.tmux.windows() if x["id"] == wid), None) if wid else None
    except OSError:
        win = None
    return {"prompt": starters.prompt(sid, tasks=self.who()[1] == "owner" and not (win and in_space(win)))}


def new(self, b: dict):
    """POST /api/new"""
    panel = self.panel
    if (slug := self.space()):
        return panel.new_in_space(slug, str(b.get("name", "")), str(b.get("effort") or ""))
    return panel.new(int(b.get("i", -1)), str(b.get("profile", "")), self.person(), self.terms_uid())


def default_model_set(self, b: dict):
    """POST /api/model/default — только явной настройкой — не из чата"""
    panel = self.panel
    return panel.default_model(str(b.get("model") or ""))


def route(self, b: dict):
    """POST /api/route — подсказка модели по первому сообщению (router.py)"""
    panel = self.panel
    return panel.route(str(b.get("text", ""))[:2000], self.terms_uid())


def order(self, b: dict):
    """POST /api/order — свой порядок: закреплённые, проекты, чаты (20.11)"""
    panel = self.panel
    ids = panel.projects.set_order(self.pinner(), str(b.get("grp") or ""), b.get("ids") or [])
    panel._proj = (0.0, {})
    return {"ok": True, "ids": ids}


def pin(self, b: dict):
    """POST /api/pin — «Закрепить» / «Открепить»: проект, сессия или чат"""
    panel = self.panel
    return panel.pin(self.pinner(), b.get("on", True) is not False, str(b.get("project") or ""),
                     str(b.get("w") or ""), str(b.get("id") or ""), str(b.get("sid") or ""))


def stopped_clear(self, b: dict):
    """POST /api/stopped/clear — «Убрать все остановленные» — окна, журналы остаются"""
    panel = self.panel
    return panel.clear_stopped()


def folder(self, b: dict):
    """POST /api/folder — «Новая папка» → сессия в ней (как 📁 в боте)"""
    panel = self.panel
    return panel.new_folder(str(b.get("name", "")), str(b.get("profile", "")), self.person(),
                            self.terms_uid())


def revive(self, b: dict):
    """POST /api/revive"""
    panel = self.panel
    return panel.revive(str(b.get("w", "")), self.terms_uid())


def close(self, b: dict):
    """POST /api/close — и остановленную: окно с оболочкой просто закрыть"""
    panel = self.panel
    w = panel.session_window(b.get("w"))
    if b.get("schedule"):                      # сессия модуля: оставить / приостановить / выключить
        panel.set_schedule(w["path"], str(b["schedule"]), self.terms_uid())
    r = panel.close_ex(w, force=True) if b.get("force") is True else panel.close_ex(w)   # + черновик
    if r["result"] == "закрыто":
        panel.focus.end_window(w["id"])        # фокус-ссылки этой сессии гаснут сразу
    return r


def notify_done(self, b: dict, w: dict):
    """POST_W NOTIFY_DONE — одно сообщение в бот, когда ход закончится (бот следит)"""
    panel = self.panel
    return {"result": panel.pult.ask_notify_done(w["id"], self.terms_uid())}


def send(self, b: dict, w: dict):
    """POST_W /api/send"""
    panel = self.panel
    helper = self.who()[1] in ("owner", "admin")
    if w.get("space") and helper:
        panel.owner_seen[w["id"]] = time.time()      # владелец пишет или отвечает — тестировщик увидит
    panel.check(w.get("profile") or "claude", self.terms_uid())   # сессия этого поставщика — для страны?
    text = mark_bare(str(b.get("text", "")).strip())   # файл без подписи — пометка агенту (uploads.py)
    if not text:
        raise ValueError("пустое сообщение")
    mid = str(b.get("id", ""))[:64]           # повтор после обрыва связи — не «тот же вопрос»
    panel.events.event("recv", mid, w=w["id"], src="focus" if self.focused is not None else "panel",
                       len=len(text), sha=chatlog.sha(text), dev=webauth.device(self.client()[1]),
                       via=self.via() + ("·pwa" if self.headers.get("X-Pult-Pwa") == "1" else ""))
    if (ago := panel.repeat.check(w["id"], text, mid=mid)) is not None:
        panel.events.event("repeat_stop", mid, w=w["id"], ago=ago)
        raise ValueError(f"Этот вопрос уже отправлен {max(1, ago // 60)} мин назад — ответ появится выше. "
                         "Нужно ещё раз — отправьте снова в течение 2 минут.")
    try:
        with panel.pult.via("focus" if self.focused is not None else "panel"):
            dup = panel.send(w, text if self.focused is None else      # человек по ссылке — пометка агенту
                             panel.focus.mark_guest(w["id"], self.focused, text), str(b.get("id", ""))[:64])
    except Exception as e:
        panel.events.event("send_error", mid, w=w["id"], err=f"{type(e).__name__}: {e}")
        raise
    panel.events.event("dup" if dup else "inserted", mid, w=w["id"])
    if not dup:
        self.product("send", via="focus" if self.focused is not None else "panel")
    panel.repeat.done(w["id"], text, mid=mid)
    return {"ok": True, "dup": dup}


def resend(self, b: dict, w: dict):
    """POST_W /api/resend — «Отправить» у строки «Не отправлено» — Enter после проверки"""
    panel = self.panel
    return {"result": panel.pult.push_enter(w["id"], str(b.get("sha", ""))[:12])}


def rename(self, b: dict, w: dict):
    """POST_W /api/rename"""
    panel = self.panel
    return {"name": panel.tmux.rename(w["id"], str(b.get("name", "")))}


def title(self, b: dict, w: dict):
    """POST_W /api/title — название чата (вторая часть), не имя окна; "" — авто"""
    panel = self.panel
    return panel.set_title(w, b.get("title"))


def active(self, b: dict, w: dict):
    """POST_W /api/active"""
    panel = self.panel
    if w.get("space"):
        raise ValueError("сессия демо-пространства не бывает активной в чате бота — откройте её в панели")
    panel.pult.set_state(active=w["id"])
    return {"ok": True}


def notify_level(self, b: dict, w: dict):
    """POST_W /api/notify/level — уровень уведомлений этой сессии (notifylevel.py)"""
    panel = self.panel
    lv = str(b.get("level") or "")
    panel.pult.set_state(notify_levels=notifylevel.updated(panel.pult.state(), w["id"], lv))
    return {"notify": notifylevel.level(panel.pult.state(), w["id"])}


def command(self, b: dict, w: dict):
    """POST_W /api/command"""
    panel = self.panel
    panel.check(w.get("profile") or "claude", self.terms_uid())   # сессия этого поставщика — для страны?
    return panel.command(w, int(b.get("i", -1)))


def model(self, b: dict, w: dict):
    """POST_W /api/model — только запомнить модель для перезапуска (``keep``) или модель — только этого чата
    (перезапуск с --model)"""
    panel = self.panel
    panel.check(w.get("profile") or "claude", self.terms_uid())   # сессия этого поставщика — для страны?
    if b.get("keep"):   # только запомнить модель для перезапуска — без перезапуска
        return panel.keep_model(w, str(b.get("name", "")))
    return panel.model(w, str(b.get("name", "")), self.terms_uid(),
                       effort=str(b["effort"]) if b.get("effort") is not None else None)


def effort(self, b: dict, w: dict):
    """POST_W /api/effort"""
    panel = self.panel
    return {"lines": panel.effort(w, str(b.get("level", "")))}


def key(self, b: dict, w: dict):
    """POST_W /api/key"""
    panel = self.panel
    helper = self.who()[1] in ("owner", "admin")
    if w.get("space") and helper:
        panel.owner_seen[w["id"]] = time.time()      # владелец пишет или отвечает — тестировщик увидит
    panel.check(w.get("profile") or "claude", self.terms_uid())   # сессия этого поставщика — для страны?
    self.product_pick(w, key=str(b.get("key", "")))
    return {"lines": panel.key(w, str(b.get("key", "")))}


def select(self, b: dict, w: dict):
    """POST_W /api/select"""
    panel = self.panel
    helper = self.who()[1] in ("owner", "admin")
    if w.get("space") and helper:
        panel.owner_seen[w["id"]] = time.time()      # владелец пишет или отвечает — тестировщик увидит
    panel.check(w.get("profile") or "claude", self.terms_uid())   # сессия этого поставщика — для страны?
    go = b.get("go", True) is not False            # go: false — только выделить пункт
    if go:
        self.product_pick(w, n=str(b.get("n", "")))
    return {"lines": panel.select(w, str(b.get("text", "")), str(b.get("n", "")), go)}


def restart(self, b: dict, w: dict):
    """POST_W /api/restart"""
    panel = self.panel
    if self.who()[1] == "admin" and str(b.get("profile", "")) not in ("", w.get("profile") or ""):
        raise ValueError("админ перезапускает сессию без смены модели: модель и расход — у владельца")
    return panel.restart(w, str(b.get("profile", "")), b.get("keep", True) is not False, self.terms_uid())


GET = {"/api/sessions": sessions_list, "/api/starters": starters_get, "/api/scenarios": scenarios_get,
       "/api/media": media, "/api/model/default": default_model_get, "/api/activity": activity}
GET_W = {"/api/last": last, "/api/screen": screen, "/api/ask": ask, "/api/hint": hint, "/api/cmds": cmds,
         "/api/steps": steps_get, "/api/history": history}
POST_RAW = {"/api/upload": upload}
POST = {"/api/starter": starter, "/api/new": new, "/api/model/default": default_model_set, "/api/route": route,
        "/api/order": order, "/api/pin": pin, "/api/stopped/clear": stopped_clear, "/api/folder": folder,
        "/api/revive": revive, "/api/close": close}
POST_W = {NOTIFY_DONE: notify_done, "/api/send": send, "/api/resend": resend, "/api/rename": rename,
          "/api/title": title, "/api/active": active, "/api/notify/level": notify_level, "/api/command": command,
          "/api/model": model, "/api/effort": effort, "/api/key": key, "/api/select": select, "/api/restart": restart}
