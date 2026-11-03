"""Роли интерфейса: права (access_role) отдельно, вид панели (ui_persona) отдельно.

- **access_role** — права, их проверяет сервер на каждый запрос. Это прежние роли пульта (``people.py``) под новыми
  именами: владелец → ``owner``, участник → ``staff``, наблюдатель → ``guest``.
- **ui_persona** — только вид: какие экраны и кнопки показать. Пять пресетов — ``PERSONAS``. Сменить можно в любой
  момент, данные (сессии, история, подключения) не трогаются.
- **Возможности** ``cap.*`` — атомарные флаги вида (``CAPS``). Человек может добавить себе возможность из чужого
  пресета или скрыть свою.

Итог — одна формула (``effective``)::

    (пресет роли ∪ добавленные) − скрытые, ∩ потолок по access_role

Потолок (``ceiling``): владельцу — всё; сотруднику — то, что разрешил владелец на экране «Команда» (общая политика и
поправка на конкретного человека; пока владелец ничего не задал — всё, как было до ролей); гостю — постоянный набор
``GUEST``. Потолок — это и есть права: сервер не отдаёт сотруднику API возможностей вне потолка (``CAP_PATHS``),
даже если панель их как-то покажет. Скрытая или не добавленная *в виде* возможность сервер не закрывает —
это только вид.

Хранение: вид человека — поле ``ui: {persona, added, hidden, onboarded, at}`` (``people.py``: у человека из
people.json — в его записи, у владельцев — ``<data>/ui.json``). Политика для сотрудников — ``<data>/team.json`` (0600):
``{"staff_caps": [...], "sections": [...], "people": {"<id>": {"caps": [...], "sections": [...]}}}``.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from gas_pult.config import write_private

# Возможности по порядку показа. ``ready`` — у возможности уже есть экран в панели; без экрана тумблер виден, но
# помечен «готовится» и ничего не открывает. ``dev`` — инженерная (её нет у бизнес-ролей по умолчанию).
CAPS: dict[str, dict] = {
    "cap.four_tabs": {"ru": "4 раздела бизнеса: Поиск, Цифры, Бумаги, Общение",
                      "en": "4 business sections: Search, Numbers, Papers, Messages", "ready": True},
    "cap.approvals_yes_no": {"ru": "Карточки «Ждут вашего Да» наверху", "en": "“Waiting for your Yes” cards on top",
                             "ready": True},
    "cap.scenarios_try": {"ru": "Примерочная: сценарии и калькулятор", "en": "Try-on: scenarios and calculator",
                          "ready": True},
    "cap.assistant_guide": {"ru": "Помощник «Подсказать» на каждом экране", "en": "“Help me” assistant on every screen",
                            "ready": True},
    "cap.pm_tasks_deadlines": {"ru": "Доска задач, сроков и отчётов", "en": "Tasks, deadlines and reports board",
                               "ready": False},
    "cap.audit_journal": {"ru": "Журнал действий и откат", "en": "Action log and undo", "ready": False},
    "cap.sandbox_safe": {"ru": "Учебная песочница с уроками", "en": "Practice sandbox with lessons", "ready": False},
    "cap.dev_sessions": {"ru": "Сессии, папки и ветки", "en": "Sessions, folders and branches", "ready": True,
                         "dev": True},
    "cap.dev_terminal": {"ru": "Экран терминала и клавиши", "en": "Terminal screen and keys", "ready": True,
                         "dev": True},
    "cap.dev_models_mcp": {"ru": "Модели, ключи и подключения (MCP)", "en": "Models, keys and connections (MCP)",
                           "ready": True, "dev": True},
    "cap.dev_cost_tokens": {"ru": "Подробный расход: токены и стоимость", "en": "Detailed usage: tokens and cost",
                            "ready": True, "dev": True},
}
ALL = frozenset(CAPS)

# Пресеты пяти ролей (решение 02.11, раздел 6.2: «ВКЛ» в таблице). Помощник у разработчика включён: его текущий
# интерфейс с пилюлей «Подсказать» не меняется.
PERSONAS: dict[str, dict] = {
    "business_owner": {"ru": "Владелец или директор бизнеса", "en": "Business owner or director",
                       "sub_ru": "Выручка, документы и клиенты; решения — кнопкой «Да», без сложных настроек.",
                       "sub_en": "Revenue, documents and clients; decisions with one “Yes”, no complex settings.",
                       "caps": ("cap.four_tabs", "cap.approvals_yes_no", "cap.scenarios_try", "cap.assistant_guide")},
    "point_admin": {"ru": "Сотрудник или администратор точки", "en": "Staff member or site administrator",
                    "sub_ru": "Заявки, расписание, клиенты и документы на точке.",
                    "sub_en": "Requests, schedule, clients and documents on site.",
                    "caps": ("cap.four_tabs", "cap.approvals_yes_no", "cap.assistant_guide")},
    "project_manager": {"ru": "Руковожу проектами и задачами", "en": "I manage projects and tasks",
                        "sub_ru": "Сроки, поручения помощникам, отчёты и журнал.",
                        "sub_en": "Deadlines, assignments to assistants, reports and the log.",
                        "caps": ("cap.approvals_yes_no", "cap.assistant_guide", "cap.pm_tasks_deadlines",
                                 "cap.audit_journal")},
    "student": {"ru": "Учусь или хочу примерить", "en": "I'm learning or want to try",
                "sub_ru": "Безопасно попробовать на готовых примерах.",
                "sub_en": "Try safely on ready-made examples.",
                "caps": ("cap.four_tabs", "cap.approvals_yes_no", "cap.scenarios_try", "cap.assistant_guide",
                         "cap.sandbox_safe")},
    "developer": {"ru": "Разработчик или инженер", "en": "Developer or engineer",
                  "sub_ru": "Сессии, терминал, модели, подключения и расход — как сейчас.",
                  "sub_en": "Sessions, terminal, models, connections and usage — as now.",
                  "caps": ("cap.approvals_yes_no", "cap.assistant_guide", "cap.audit_journal", "cap.dev_sessions",
                           "cap.dev_terminal", "cap.dev_models_mcp", "cap.dev_cost_tokens")},
}
DEFAULT = "developer"                   # нет выбора — прежний полный интерфейс
SIMPLE = ("business_owner", "point_admin", "student")   # простой режим из #80
SPACE_FIXED = frozenset({"cap.dev_sessions"})          # «Моё пространство» владельца: всегда с сессиями

# Права пульта → access_role.
ACCESS = {"owner": "owner", "member": "staff", "viewer": "guest"}
# Гость смотрит, но инженерные настройки ему не нужны (модели и MCP наблюдателю закрыты и раньше).
GUEST = ALL - {"cap.dev_models_mcp"}

# Разделы «4 раздела бизнеса» — чипы-фильтры над чатом.
SECTIONS = {"search": {"ru": "Поиск", "en": "Search"}, "analytics": {"ru": "Цифры", "en": "Numbers"},
            "docs": {"ru": "Бумаги", "en": "Papers"}, "comms": {"ru": "Общение", "en": "Messages"}}

# Какие запросы API относятся к возможности. Сервер не пускает к ним того, у кого возможности нет в *потолке*.
CAP_PATHS = {
    "cap.dev_terminal": ("/api/screen", "/api/hint"),
    "cap.dev_models_mcp": ("/api/model", "/api/effort", "/api/mcp", "/api/mcp/add", "/api/mcp/remove",
                           "/api/mcp/login", "/api/mcp/finish", "/api/mcp/connected"),
    "cap.dev_sessions": ("/api/folder", "/api/rename", "/api/cmds", "/api/command"),
}
PATH_CAP = {p: c for c, ps in CAP_PATHS.items() for p in ps}


def access(role: str | None) -> str | None:
    return ACCESS.get(role or "")


def norm(caps) -> set[str]:
    """Только известные возможности (мусор из файла или запроса молча отбрасывается)."""
    return {c for c in caps or () if c in CAPS} if isinstance(caps, (list, tuple, set, frozenset)) else set()


def preset(persona: str) -> set[str]:
    return set(PERSONAS.get(persona, PERSONAS[DEFAULT])["caps"])


def effective(persona: str, added, hidden, ceiling) -> set[str]:
    """(пресет роли ∪ добавленные) − скрытые, ∩ потолок по access_role."""
    return ((preset(persona) | norm(added)) - norm(hidden)) & set(ceiling)


def simple(caps) -> bool:
    """Простой (чат) интерфейс — когда нет инженерного списка сессий."""
    return "cap.dev_sessions" not in caps


def catalog(lang: str = "ru") -> dict:
    """Справочник для панели: возможности, роли и разделы на нужном языке."""
    en = lang == "en"
    return {"caps": [{"id": c, "title": v["en" if en else "ru"], "ready": v["ready"], "dev": bool(v.get("dev"))}
                     for c, v in CAPS.items()],
            "personas": [{"id": p, "title": v["en" if en else "ru"], "sub": v["sub_en" if en else "sub_ru"],
                          "caps": list(v["caps"]), "simple": p in SIMPLE} for p, v in PERSONAS.items()],
            "sections": [{"id": s, "title": v["en" if en else "ru"]} for s, v in SECTIONS.items()]}


class Team:
    """Политика владельца для сотрудников (``<data>/team.json``): потолок возможностей и разделы."""

    def __init__(self, store: Path):
        self.store, self.lock = store, threading.Lock()

    def load(self) -> dict:
        try:
            d = json.loads(self.store.read_text())
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def policy(self) -> dict:
        """Общая политика: ``staff_caps`` (None — владелец не задавал: всё) и ``sections``."""
        d = self.load()
        caps = d.get("staff_caps")
        return {"staff_caps": sorted(norm(caps)) if isinstance(caps, list) else None,
                "sections": [s for s in SECTIONS if s in (d.get("sections") or SECTIONS)]}

    def person(self, uid) -> dict:
        rec = (self.load().get("people") or {}).get(str(uid)) or {}
        return {"caps": sorted(norm(rec["caps"])) if isinstance(rec.get("caps"), list) else None,
                "sections": [s for s in SECTIONS if s in rec["sections"]]
                if isinstance(rec.get("sections"), list) else None}

    def ceiling(self, uid) -> set[str]:
        """Потолок сотрудника: его поправка, иначе общая политика, иначе — всё."""
        own, pol = self.person(uid)["caps"], self.policy()["staff_caps"]
        return set(own if own is not None else pol if pol is not None else ALL)

    def sections(self, uid) -> list[str]:
        own = self.person(uid)["sections"]
        return own if own is not None else self.policy()["sections"]

    def set(self, caps=None, sections=None, uid=None, reset: bool = False):
        """Задать потолок (``caps``) и разделы — общие или для человека ``uid``; ``reset`` — убрать поправку."""
        for x, known in ((caps, CAPS), (sections, SECTIONS)):
            if x is not None and (not isinstance(x, list) or any(c not in known for c in x)):
                raise ValueError("неизвестная возможность или раздел")
        with self.lock:
            d = self.load()
            if uid is None:
                if caps is not None:
                    d["staff_caps"] = sorted(set(caps))
                if sections is not None:
                    d["sections"] = [s for s in SECTIONS if s in sections]
            else:
                people = d.setdefault("people", {})
                if reset:
                    people.pop(str(int(uid)), None)
                else:
                    rec = people.setdefault(str(int(uid)), {})
                    if caps is not None:
                        rec["caps"] = sorted(set(caps))
                    if sections is not None:
                        rec["sections"] = [s for s in SECTIONS if s in sections]
            write_private(self.store, json.dumps(d, ensure_ascii=False))

    def forget(self, uid):
        with self.lock:
            d = self.load()
            if (d.get("people") or {}).pop(str(int(uid)), None) is not None:
                write_private(self.store, json.dumps(d, ensure_ascii=False))


def ceiling(access_role: str | None, team: Team, uid) -> set[str]:
    if access_role == "owner":
        return set(ALL)
    if access_role == "staff":
        return team.ceiling(uid)
    if access_role == "guest":
        return set(GUEST)
    return set()


def view(rec: dict, access_role: str | None, team: Team, uid, lang: str = "ru") -> dict:
    """Всё, что нужно панели о виде человека: роль, добавленное/скрытое, потолок и итог."""
    persona = rec.get("persona") if rec.get("persona") in PERSONAS else DEFAULT
    added, hidden = sorted(norm(rec.get("added"))), sorted(norm(rec.get("hidden")))
    ceil = ceiling(access_role, team, uid)
    caps = effective(persona, added, hidden, ceil)
    sections = list(SECTIONS) if access_role == "owner" else team.sections(uid) if access_role == "staff" else \
        list(SECTIONS)
    return {"persona": persona, "chosen": rec.get("persona") in PERSONAS, "onboarded": rec.get("onboarded") is True,
            "added": added, "hidden": hidden, "access": access_role, "ceiling": sorted(ceil),
            "caps": sorted(caps), "simple": simple(caps), "sections": sections,
            "can_team": access_role == "owner", "catalog": catalog(lang)}


def change(rec: dict, access_role: str | None, team: Team, uid, persona=None, add=None, hide=None) -> dict:
    """Новая запись вида после выбора человека. Добавить можно только то, что в потолке."""
    out = {k: rec[k] for k in ("persona", "added", "hidden", "onboarded") if k in rec}
    if persona is not None:
        if persona not in PERSONAS:
            raise ValueError("нет такой роли")
        out["persona"], out["onboarded"] = persona, True
        out["added"], out["hidden"] = [], []    # «сменить роль целиком» — свои добавления и скрытия с нуля
    ceil = ceiling(access_role, team, uid)
    added, hidden = norm(out.get("added")), norm(out.get("hidden"))
    for c, on in (add or {}).items():
        if c not in CAPS:
            raise ValueError("нет такой возможности")
        if on and c not in ceil:
            raise PermissionError("эту возможность вам не разрешил владелец пульта")
        (added.add if on else added.discard)(c)
        (hidden.discard if on else hidden.add)(c)
    for c in hide or ():
        if c in CAPS:
            hidden.add(c)
            added.discard(c)
    base = preset(out.get("persona") or DEFAULT)
    out["added"] = sorted(added - base)          # в пресете и так есть — не храним
    out["hidden"] = sorted(hidden & base)        # скрывать есть смысл только своё
    return out
