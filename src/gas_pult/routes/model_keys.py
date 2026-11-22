"""Маршруты области «Модели, ключи, расход» (MONOLITH-PLAN §3.2, шаг 7): вход в Claude Code (setup.py, logins.py),
ключи поставщиков и голоса, OpenRouter, запасная цепочка моделей, автотест поставщиков, лимиты и расход, воронка.

Ветки перенесены из ``webapp.H.get``/``H.post`` как есть: ``self`` — обработчик запроса (``webapp.H``), ``panel`` —
его ``Panel``. Права (``access.py``: ``OWNER_ONLY`` — ключи, модели, вход, лимиты, ``/api/spend``; ``SELFTEST``,
``FUNNEL``; через ``/api/v1`` — ``V1_NEVER`` для ключей и ``/api/providers``) проверены до вызова — ``H.permit``.
Значения ключей в ответах не возвращаются. Таблицы и подписи — ``routes/__init__.py``.
"""

from gas_pult import balance, funnel, logins, models, selftest, spend, tenants, webauth
from gas_pult.access import SELFTEST
from gas_pult.commands import in_space


def setup_status(self, q: dict):
    """GET /api/setup/status"""
    panel = self.panel
    return panel.setup_status(q.get("fresh") == "1")


def openrouter_info(self, q: dict):
    """GET /api/openrouter/info"""
    panel = self.panel
    return panel.openrouter_info()


def openrouter_models(self, q: dict):
    """GET /api/openrouter/models"""
    panel = self.panel
    return {"models": panel.openrouter.models()}


def fallback_get(self, q: dict):
    """GET /api/fallback"""
    panel = self.panel
    return panel.fallback_info(self.terms_uid())


def selftest_get(self, q: dict):
    """GET /api/selftest"""
    panel = self.panel
    return selftest.public(panel.cfg.data, panel.pult.state())


def cost_limits(self, q: dict):
    """GET /api/cost/limits"""
    panel = self.panel
    return panel.cost_limits()


def spend_get(self, q: dict):
    """GET /api/spend — расход по ценам API за период (spend.py) — только владельцу"""
    return spend.summary(q.get("period", "today"))


def providers_get(self, q: dict):
    """GET /api/providers"""
    panel = self.panel
    vs = panel.voice_settings()
    return {**vs, "el_voices": panel.el_voices() if "elevenlabs" in vs["keys"] else []}


def funnel_get(self, q: dict):
    """GET /api/funnel — воронка продукта: вход → первый ответ → «Да» (funnel.py)"""
    panel = self.panel
    if (u := self.who()[2]) not in (None, webauth.LEGACY) and panel.people.tenant(u):
        raise ValueError("воронка — только владельцу пульта")
    days = int(q["days"]) if q.get("days", "").isdigit() else 30
    sp = tenants.check_slug(q["space"]) if q.get("space") else None
    return funnel.report(panel.funnel.read(), min(days, 400), sp)


def keys_set(self, b: dict):
    """POST /api/keys"""
    panel = self.panel
    return panel.set_key(str(b.get("provider", "")), str(b.get("key", "")))


def keys_remove(self, b: dict):
    """POST /api/keys/remove"""
    panel = self.panel
    panel.remove_key(str(b.get("provider", "")))
    return {"ok": True}


def providers_set(self, b: dict):
    """POST /api/providers"""
    panel = self.panel
    panel.set_providers(b)
    return {"ok": True}


def setup_login(self, b: dict):
    """POST /api/setup/login — окно входа и ссылка с экрана (до 20 с)"""
    panel = self.panel
    return panel.login.start()


def setup_code(self, b: dict):
    """POST /api/setup/code"""
    panel = self.panel
    r = panel.login.send_code(str(b.get("code", "")))
    panel._setup = (0, {})
    return r


def login_code(self, b: dict):
    """POST /api/login/code — шторка «Нужен вход»: код или адрес — в окно, одной строкой"""
    panel = self.panel
    w = self.win(b.get("w"))
    if in_space(w):
        raise PermissionError("окно пространства — вход только из него самого")
    panel.tmux.paste(w["id"], logins.clean_code(b.get("code")))   # код в журналы не пишем
    return {"ok": True}


def login_check(self, b: dict):
    """POST /api/login/check"""
    panel = self.panel
    return panel.login_check(self.win(b.get("w")), str(b.get("kind") or ""), self.home())


def setup_cancel(self, b: dict):
    """POST /api/setup/cancel"""
    panel = self.panel
    panel.login.cancel()
    return {"ok": True}


def balance_clear(self, b: dict):
    """POST /api/balance/clear — «Я пополнил» — снова предлагать поставщика"""
    panel = self.panel
    st = panel.pult.state()
    panel.pult.set_state(no_balance=balance.clear(st, str(b.get("profile", ""))))
    return {"ok": True}


def openrouter_start(self, b: dict):
    """POST /api/openrouter/start"""
    panel = self.panel
    base = panel.public_url or f"https://{self.headers.get('Host', '')}"
    return {"url": panel.openrouter.start(base)}


def fallback_set(self, b: dict):
    """POST /api/fallback"""
    panel = self.panel
    return panel.set_fallback(b.get("chain"), self.terms_uid())


def selftest_run(self, b: dict):
    """POST /api/selftest — «Проверить сейчас» — в фоне, итог — GET"""
    panel = self.panel
    started = selftest.start(panel.cfg.data, panel.pult.state())
    return {"started": started, **selftest.public(panel.cfg.data, panel.pult.state())}


def cost_limits_set(self, b: dict):
    """POST /api/cost/limits"""
    panel = self.panel
    return panel.set_cost_limits(b)


def cost_decide(self, b: dict):
    """POST /api/cost/decide — пауза по расходу: «go» — продолжить, «stop» — оставить"""
    panel = self.panel
    return {"result": panel.pult.cost_decide(str(b.get("w", "")), str(b.get("act", ""))),
            **panel.cost_limits()}


def models_set(self, b: dict):
    """POST /api/models"""
    panel = self.panel
    url = b.get("base_url")
    panel.set_models(str(b.get("profile", "")), str(b.get("main", "")), str(b.get("fast", "")),
                     None if url is None else str(url))
    return {"profiles": models.public(panel.pult.state(), panel.countries(self.terms_uid()))}


GET = {"/api/setup/status": setup_status, "/api/openrouter/info": openrouter_info,
       "/api/openrouter/models": openrouter_models, "/api/fallback": fallback_get, SELFTEST: selftest_get,
       "/api/cost/limits": cost_limits, "/api/spend": spend_get, "/api/providers": providers_get,
       "/api/funnel": funnel_get}
POST = {"/api/keys": keys_set, "/api/keys/remove": keys_remove, "/api/providers": providers_set,
        "/api/setup/login": setup_login, "/api/setup/code": setup_code, "/api/login/code": login_code,
        "/api/login/check": login_check, "/api/setup/cancel": setup_cancel, "/api/balance/clear": balance_clear,
        "/api/openrouter/start": openrouter_start, "/api/fallback": fallback_set, SELFTEST: selftest_run,
        "/api/cost/limits": cost_limits_set, "/api/cost/decide": cost_decide, "/api/models": models_set}
