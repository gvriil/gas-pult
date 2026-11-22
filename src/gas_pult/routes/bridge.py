"""Маршруты области «Мост к браузеру» (MONOLITH-PLAN §3.2, шаг 7): компьютеры с мостом владельца (bridge/), журнал
действий, черновики «Ждут вашего Да», код пары, отключение, «Личные данные не уходят модели», «Да» / «Нет».

Ветки перенесены из ``webapp.H.get``/``H.post`` как есть: ``self`` — обработчик запроса (``webapp.H``), ``panel`` —
его ``Panel``. Права (``access.py``: ``OWNER_ONLY`` — все пути области; человеку пространства — нет, ``SPACE_OK``)
проверены до вызова — ``H.permit``. До входа (``do_GET``/``do_POST``: установка, ``/api/bridge/ws``, ``claim``,
``rpc``, ``code`` — токен устройства) — не здесь. Таблицы и подписи — ``routes/__init__.py``.
"""

from gas_pult import bridge


def bridge_devices(self, q: dict):
    """GET /api/bridge/devices — компьютеры с мостом к браузеру (только владелец)"""
    panel = self.panel
    on, names = set(panel.hub.online()), {x["id"]: x["name"] for x in panel.focus.listing()}
    return {"devices": [{**d, "online": d["id"] in on and panel.bridge_dev_ok(d),
                         **({"focus_name": names.get(d["focus"], "ссылка погасла")}
                            if d.get("focus") else {})}
                        for d in panel.devices.listing()]}


def bridge_log(self, q: dict):
    """GET /api/bridge/log — журнал действий по устройству (только владелец)"""
    panel = self.panel
    return {"log": panel.hub.history(str(q.get("id") or ""))}


def bridge_drafts(self, q: dict):
    """GET /api/bridge/drafts — что ждёт «Да» человека: кнопка, команда, запись на Маке"""
    panel = self.panel
    names = {d["id"]: d["name"] for d in panel.devices.listing()}
    said = lambda pid: panel.approvals.pending("", bridge.CONFIRM_SVC, pid)   # noqa: E731 — «Да» в памяти
    return {"drafts": [{**x, "device_name": names.get(x["device"], "компьютер")}
                       for x in bridge.drafts(said) if x["device"] in names]}


def bridge_pair(self, b: dict):
    """POST /api/bridge/pair — одноразовый код пары (10 мин) для моста на компьютере"""
    panel = self.panel
    return panel.devices.pair_code()


def bridge_revoke(self, b: dict):
    """POST /api/bridge/revoke"""
    panel = self.panel
    return {"ok": panel.devices.revoke(str(b.get("id") or ""))}


def bridge_private(self, b: dict):
    """POST /api/bridge/private — «Личные данные не уходят модели» для устройства"""
    panel = self.panel
    return {"ok": panel.devices.set_private(str(b.get("id") or ""), b.get("on") is not False)}


def bridge_confirm(self, b: dict):
    """POST /api/bridge/confirm — «Да» человека в панели — только в памяти (approvals.py)"""
    panel = self.panel
    self.same_origin()
    pid = str(b.get("id") or "")
    rec = bridge._core._load(bridge.CONFIRM_SVC, pid)
    panel.approvals.grant("", bridge.CONFIRM_SVC, pid, bridge._core._digest(rec["action"], rec["params"]))
    self.product("yes", via="bridge")
    return {"ok": True}


def bridge_reject(self, b: dict):
    """POST /api/bridge/reject — «Нет»: черновик убран, выполнить его нельзя"""
    bridge.reject(str(b.get("id") or ""))
    self.product("no", via="bridge")
    return {"ok": True}


GET = {"/api/bridge/devices": bridge_devices, "/api/bridge/log": bridge_log, "/api/bridge/drafts": bridge_drafts}
POST = {"/api/bridge/pair": bridge_pair, "/api/bridge/revoke": bridge_revoke, "/api/bridge/private": bridge_private,
        "/api/bridge/confirm": bridge_confirm, "/api/bridge/reject": bridge_reject}
