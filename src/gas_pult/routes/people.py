"""Маршруты области «Люди и вход» (MONOLITH-PLAN §3.2, шаг 7): условия, вид и язык панели (``/api/prefs``,
«роль» ``/api/persona``, тур, страна), «Команда» и люди (роли, доступ, удаление), приглашения и вход на другое
устройство, привязка Telegram, почты, ключей входа (passkeys) и Google / Яндекс ID, код подтверждения нового входа,
помощник и «Позвать на помощь», ошибки JS и отметки функций, «Выйти».

Ветки перенесены из ``webapp.H.get``/``H.post`` как есть: ``self`` — обработчик запроса (``webapp.H``), ``panel`` —
его ``Panel``. Две ветки ``/api/logout`` — одна функция (``if path == P and X`` → ``if X``). Права проверены до
вызова — ``H.permit`` (вход, условия ``TERMS_FREE``, ``SLINK_NO``, ``SPACE_OK``, роль: ``OWNER_ONLY``/``ADMIN_OK`` и
список ``free`` — POST и наблюдателю, потолок ``PATH_CAP``), фокус-ссылка — ``H.focus_call`` (``/api/meta`` и
``/api/logout`` по ссылке — свои ветки ``H.focus_do``). Подтверждение кодом (``CONFIRM_API``) — ``POST_P``: только
вход из браузера — проверка внутри, как была; «Позвать на помощь» — ``POST_W`` (ветка шла после
``w = self.win(b.get("w"))``). Сам вход — до ``permit``, в ``do_GET``/``do_POST`` (не здесь): ``/api/login/*``
(Telegram, код, ключ, почта, OIDC), ``/api/invite`` и ``/api/invite/check|enter``, помощник без входа
(``HELP_OPEN``). ``/api/meta`` — в цепочке: ему нужны ``whatsnew`` (замыкание ``handler``) и ``desktop_up``
(``webapp``, тесты подменяют его там). Ответ с cookie — ``("cookie", Set-Cookie, тело)``, как в цепочке
(``H.dispatch``). Таблицы и подписи — ``routes/__init__.py``.
"""

from gas_pult import focus, invites, personas, terms, webauth
from gas_pult.access import CONFIRM_API, FEEDBACK, PERSONA, SLINK, TOUR, USES
from gas_pult.people import is_guest


def terms_get(self, q: dict):
    """GET /api/terms"""
    return self.terms_info()


def prefs_get(self, q: dict):
    """GET /api/prefs"""
    panel = self.panel
    return panel.prefs(self.terms_uid(), self.who()[1])


def persona_get(self, q: dict):
    """GET /api/persona — вид панели: роль, разделы (PERSONA)"""
    panel = self.panel
    return panel.ui(self.terms_uid(), self.who()[1])


def team_get(self, q: dict):
    """GET /api/team"""
    panel = self.panel
    return panel.team_info()


def tour_get(self, q: dict):
    """GET /api/tour — тур: пройден / «Не сейчас» — у каждого свой"""
    panel = self.panel
    return panel.people.tour(self.terms_uid())


def country_get(self, q: dict):
    """GET /api/country"""
    panel = self.panel
    return panel.country_info(self.terms_uid())


def email_get(self, q: dict):
    """GET /api/email"""
    panel = self.panel
    return panel.email.info(self.terms_uid())


def passkeys_get(self, q: dict):
    """GET /api/passkeys"""
    panel = self.panel
    return panel.keys.info(self.terms_uid())


def oidc_get(self, q: dict):
    """GET /api/oidc"""
    panel = self.panel
    return panel.oidc.info(self.terms_uid())


def people_get(self, q: dict):
    """GET /api/people"""
    panel = self.panel
    return {"people": panel.people_list(), **panel.geo.info()}


def invite_qr(self, q: dict):
    """GET /api/invite/qr — QR ссылки приглашения: владельцу — любой, человеку — своей"""
    panel = self.panel
    return ("image/png", panel.invite_qr(str(q.get("u") or ""), self.who()[1] in ("owner", "admin"),
                                         self.terms_uid()))


def clientlog(self, b: dict):
    """POST /api/clientlog — ошибка JS в браузере (GAS-31): тип, экран, место"""
    panel = self.panel
    panel.events.event("js_error", str(b.get("mid") or ""), kind=str(b.get("kind") or "")[:40],
                       msg=str(b.get("msg") or "")[:160], at=str(b.get("at") or "")[:120],
                       screen=str(b.get("screen") or "")[:40], dev=webauth.device(self.client()[1]))
    return {"ok": True}


def uses(self, b: dict):
    """POST /api/uses — открытые функции панели: id, не чаще раза в минуту"""
    panel = self.panel
    return {"n": panel.uses.record(b.get("ids") if isinstance(b.get("ids"), list) else [])}


def prefs_set(self, b: dict):
    """POST /api/prefs — простой режим и язык — у каждого свои"""
    panel = self.panel
    lang, uid, role = b.get("lang"), self.terms_uid(), self.who()[1]
    if b.get("simple") is True and panel.is_owner(uid):
        raise ValueError("ваше пространство — всегда полный пульт; простой режим — в «Демо и тестах»")
    if b.get("simple") is not None and not panel.is_owner(uid):   # прежний переключатель — смена роли
        cur = panel.ui(uid, role)["persona"]
        want = b.get("simple") is True
        if want != (cur in personas.SIMPLE):
            panel.set_ui(uid, role, {"persona": "business_owner" if want else "developer"})
    rate = b.get("rate")
    if rate is not None and (isinstance(rate, bool) or not isinstance(rate, int | float)):
        raise ValueError("скорость — 1, 1.25, 1.5 или 2")
    p = panel.people.set_prefs(uid, None if b.get("simple") is None else b.get("simple") is True,
                               None if lang is None else str(lang), None if rate is None else float(rate))
    return {**p, "simple": panel.prefs(uid, role)["simple"]}


def persona_set(self, b: dict):
    """POST /api/persona (PERSONA)"""
    panel = self.panel
    return panel.set_ui(self.terms_uid(), self.who()[1], b if isinstance(b, dict) else {})


def team_set(self, b: dict):
    """POST /api/team"""
    panel = self.panel
    uid = b.get("id")
    caps, secs = b.get("caps"), b.get("sections")
    if uid is not None and int(uid) not in [p["id"] for p in panel.team_info()["people"]]:
        raise ValueError("это не сотрудник пульта")
    panel.team.set(caps if isinstance(caps, list) else None, secs if isinstance(secs, list) else None,
                   None if uid is None else int(uid), b.get("reset") is True)
    return panel.team_info()


def terms_accept(self, b: dict):
    """POST /api/terms/accept"""
    panel = self.panel
    if str(b.get("version", "")) != terms.VERSION:
        raise ValueError("условия обновились — прочитайте новую версию")
    panel.people.accept(self.terms_uid(), terms.VERSION)
    return self.terms_info()


def country_set(self, b: dict):
    """POST /api/country"""
    panel = self.panel
    return panel.set_country(self.terms_uid(), str(b.get("code", "")))


def feedback(self, b: dict):
    """POST /api/feedback — «Отзыв» (feedback.py): текст и снимок → задачи штаба"""
    panel = self.panel
    return panel.feedback_add(self.who(), b)


def tour_set(self, b: dict):
    """POST /api/tour (TOUR)"""
    panel = self.panel
    return panel.people.set_tour(self.terms_uid(), str(b.get("tour", "")), str(b.get("state", "")))


def passkeys_options(self, b: dict):
    """POST /api/passkeys/options"""
    panel = self.panel
    uid = self.terms_uid()
    return panel.keys.register_options(uid, panel.key_label(uid), self.client_ip())


def passkeys_add(self, b: dict):
    """POST /api/passkeys/add"""
    panel = self.panel
    return {"keys": panel.keys.register_verify(self.terms_uid(), str(b.get("id", "")), b.get("credential"),
                                               str(b.get("name", "")), self.client_ip())}


def passkeys_remove(self, b: dict):
    """POST /api/passkeys/remove"""
    panel = self.panel
    return {"keys": panel.keys.remove(self.terms_uid(), str(b.get("id", "")))}


def oidc_link(self, b: dict):
    """POST /api/oidc/link — ссылка на привязку — открыть в браузере (и из Telegram)"""
    panel = self.panel
    p = str(b.get("provider", ""))
    ticket = panel.oidc.ticket(self.terms_uid(), p, self.client_ip())
    return {"url": f"/api/login/oidc/{p}/start?link={ticket}"}


def oidc_unlink(self, b: dict):
    """POST /api/oidc/unlink"""
    panel = self.panel
    return panel.oidc.unlink(self.terms_uid(), str(b.get("provider", "")))


def email_bind(self, b: dict):
    """POST /api/email/bind"""
    panel = self.panel
    return panel.email.bind_start(self.terms_uid(), b.get("email"), self.client_ip())


def email_confirm(self, b: dict):
    """POST /api/email/confirm"""
    panel = self.panel
    return panel.email.bind_confirm(self.terms_uid(), b.get("email"), b.get("code"))


def email_remove(self, b: dict):
    """POST /api/email/remove"""
    panel = self.panel
    return panel.email.unbind(self.terms_uid())


def email_options(self, b: dict):
    """POST /api/email/options"""
    panel = self.panel
    return panel.email.options(self.terms_uid(), b.get("second_factor"), b.get("notify"))


def help_ask(self, b: dict):
    """POST /api/help/ask — роль — с сервера, не от клиента"""
    panel = self.panel
    return panel.help_ask(self.who()[1], self.terms_uid(), b if isinstance(b, dict) else {})


def help_feedback(self, b: dict):
    """POST /api/help/feedback"""
    panel = self.panel
    return panel.helper.feedback(str(b.get("id", "")), b.get("useful"), str(b.get("action", "")),
                                 "member" if self.who()[1] == "admin" else self.who()[1])


def confirm(self, path: str, b: dict):
    """POST_P /api/confirm/start|check|verify (CONFIRM_API) — подтверждение кодом — только сессии браузера"""
    panel = self.panel
    if self.via() != "browser":
        raise ValueError("подтверждение кодом — для входа из браузера")
    if path == "/api/confirm/start":
        return panel.confirm_start(self.session(), self.who()[2], *self.client())
    if path == "/api/confirm/check":          # нажали «✅ Подтвердить вход» в боте — экран закрывается сам
        return {"ok": not panel.auth.needs_confirm(self.session())}
    panel.auth.confirm_verify(self.session(), str(b.get("id", "")), str(b.get("code", "")))
    panel.confirm_done(str(b.get("id", "")))
    return {"ok": True}


def people_role(self, b: dict):
    """POST /api/people/role"""
    panel = self.panel
    panel.set_role(int(b.get("id", 0)), str(b.get("role", "")), by=self.who()[1])
    return {"people": panel.people_list(), **panel.geo.info()}


def people_remove(self, b: dict):
    """POST /api/people/remove"""
    panel = self.panel
    panel.admin_may(int(b.get("id", 0)), self.who()[1])
    panel.forget_person(int(b.get("id", 0)))
    return {"people": panel.people_list(), **panel.geo.info()}


def people_access(self, b: dict):
    """POST /api/people/access — продлить доступ: дней (0 — бессрочно)"""
    panel = self.panel
    panel.set_access(int(b.get("id", 0)), int(b.get("days", 0)), by=self.who()[1])
    return {"people": panel.people_list(), **panel.geo.info()}


def logout(self, b: dict):
    """POST /api/logout — «Выйти»: вход стирается (cookie сессии); по ссылке на пространство — её cookie"""
    panel = self.panel
    if self.via() == SLINK:   # ссылка на пространство: cookie стираем, ссылка живёт
        gone = f"{focus.COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict"
        return ("cookie", gone, {"ok": True})
    panel.auth.logout(self.session())
    return ("cookie", webauth.set_cookie("", 0), {"ok": True})


def invite_new(self, b: dict):
    """POST /api/invite/new — владелец: ссылка, короткий код и QR — одно приглашение"""
    ttl = invites.TTLS.get(str(b.get("ttl") or "1d"))
    if not ttl:
        raise ValueError("срок ссылки: " + ", ".join(invites.TTLS))
    inv = invites.new(str(b.get("space", "")), str(b.get("role") or "member"), ttl=ttl, by=self.terms_uid(),
                      uses=int(b.get("uses", 1)), access=int(b.get("access", 0)),
                      plan=str(b.get("plan") or ""), name=str(b.get("name") or ""))
    return {"path": f"/invite/{inv['code']}", "code": inv["short"], "hint": inv["hint"], "ttl": ttl,
            "uses": int(b.get("uses", 1)), "access": int(b.get("access", 0))}


def invite_device(self, b: dict):
    """POST /api/invite/device — ссылка для входа на другое устройство: себе или владелец"""
    panel = self.panel
    role = self.who()[1]
    if role in ("owner", "admin") and b.get("id") is not None:   # админ — только участникам и наблюдателям
        target = panel.admin_may(int(b["id"]), role)["id"]
    else:
        target = self.terms_uid()
    return panel.device_link(target, self.terms_uid())


def link_tg(self, b: dict):
    """POST /api/link/tg — гость: «Привязать Telegram» — ссылка на бота"""
    panel = self.panel
    uid = self.terms_uid()
    if not is_guest(uid):
        raise ValueError("Telegram у вас уже привязан")
    rid, nonce = panel.logins.start(*self.client(), link=uid)
    return {"id": rid, "link": f"https://t.me/{panel.bot_username()}?start=login_{nonce}",
            "ttl": webauth.LOGIN_TTL}


def help_call(self, b: dict, w: dict):
    """POST_W /api/help/call — тестировщик: «Позвать на помощь» — владельцу в бот"""
    panel = self.panel
    return panel.call_help(self.terms_uid(), w)


GET = {"/api/terms": terms_get, "/api/prefs": prefs_get, PERSONA: persona_get, "/api/team": team_get, TOUR: tour_get,
       "/api/country": country_get, "/api/email": email_get, "/api/passkeys": passkeys_get, "/api/oidc": oidc_get,
       "/api/people": people_get, "/api/invite/qr": invite_qr}
POST = {"/api/clientlog": clientlog, USES: uses, "/api/prefs": prefs_set, PERSONA: persona_set, "/api/team": team_set,
        "/api/terms/accept": terms_accept, "/api/country": country_set, FEEDBACK: feedback, TOUR: tour_set,
        "/api/passkeys/options": passkeys_options, "/api/passkeys/add": passkeys_add,
        "/api/passkeys/remove": passkeys_remove, "/api/oidc/link": oidc_link, "/api/oidc/unlink": oidc_unlink,
        "/api/email/bind": email_bind, "/api/email/confirm": email_confirm, "/api/email/remove": email_remove,
        "/api/email/options": email_options, "/api/help/ask": help_ask, "/api/help/feedback": help_feedback,
        "/api/people/role": people_role, "/api/people/remove": people_remove, "/api/people/access": people_access,
        "/api/logout": logout, "/api/invite/new": invite_new, "/api/invite/device": invite_device,
        "/api/link/tg": link_tg}
POST_P = {CONFIRM_API: confirm}
POST_W = {"/api/help/call": help_call}
