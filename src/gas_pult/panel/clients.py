"""Верхний уровень (решение 0010): анкета клиента, описание клиента, «Что здесь умеет», бейджики и сценарии.

Часть класса ``webapp.Panel`` (модульный монолит, docs/MONOLITH-PLAN.md п.3.1): методы перенесены как есть, ``self`` —
тот же ``Panel``.
"""

from __future__ import annotations

import json
import sys

from gas_pult import helper, onboarding, starters, tenants
from gas_pult.telegram import TelegramError


class ClientsPart:
    """Анкета клиента, описание клиента, бейджики первого разговора (примесь к ``Panel``)."""

    # ---------- анкета клиента по ссылке (решение 0010, onboarding.py) ----------
    def anketa(self, code: str) -> tuple[dict, dict]:
        rec = self.forms_links.get(code)
        form = onboarding.forms(self.cfg.data).get(rec["form"]) if rec else None
        if not rec or not form:
            raise LookupError("ссылка не найдена или устарела")
        return rec, form

    def anketa_submit(self, code: str, answers) -> dict:
        rec, form = self.anketa(code)
        answers = onboarding.clean(form, answers)
        if miss := onboarding.missing(form, answers):
            raise ValueError("Ответьте, пожалуйста, на обязательные вопросы: " + "; ".join(miss[:3]))
        rec = self.forms_links.submit(code, answers)
        onboarding.store_answers(self.cfg.data, form, rec, answers)
        text = onboarding.summary(form, answers, rec["client"]) + "\nВсе ответы — панель → «Анкеты клиентов»."
        for chat in self.cfg.owners:                      # владельцу — сразу: «прошёл — взяли в работу»
            try:
                self.pult.api("sendMessage", chat_id=chat, text=text)
            except (TelegramError, OSError) as e:
                print(f"анкета: сообщение владельцу: {e}", file=sys.stderr, flush=True)
        return {"ok": True}

    def anketa_answers(self, rid: str) -> dict:
        """Владельцу: ответы анкеты по id ссылки — текстом вопросов, и описание клиента."""
        rec = self.forms_links.by_id(rid)
        if not rec:
            raise LookupError("нет такой анкеты")
        form = onboarding.forms(self.cfg.data).get(rec["form"])
        ans = rec.get("draft") or {}
        rows = [{"q": q["text"], "a": (", ".join(ans[q["id"]]["pick"] + ([f"свой: {ans[q['id']]['other']}"]
                                       if ans[q["id"]].get("other") else [])) if isinstance(ans[q["id"]], dict)
                                       else str(ans[q["id"]])) if q["id"] in ans else "—"}
                for q in (onboarding.questions(form) if form else [])]
        prof = self.cfg.data / "clients" / f"{rid}.json"
        return {"client": rec["client"], "form": rec["form"], "sent": rec.get("sent"), "rows": rows,
                "profile": json.loads(prof.read_text()) if prof.exists() else None}

    ABOUT_MAX = 900                                     # знаков ≈ 60 с речи: «Что здесь умеет» — коротко

    def about_text(self, screen: str) -> str:
        """«Что здесь умеет» (владелец 19.11: «у каждой сессии возможность посмотреть тур или сразу прослушать»): текст
        экрана из карты помощника (``help/screens.toml``) — название, зачем, шаги. Только из карты, не от клиента."""
        s = helper.the_map()["screens"].get(str(screen))
        if not s:
            raise LookupError("для этого экрана описания нет")
        steps = " ".join(f"{i}. {x}" for i, x in enumerate(s.get("steps") or [], 1))
        return f"{s['title']}. {s.get('purpose', '')} {steps}".strip()[:self.ABOUT_MAX]

    def starters_for(self, role: str | None, space: bool, slug: str = "", occ: str = "") -> dict:
        """Бейджики первого разговора: что подключено — почта (ящики коннектора), календарь (файлы календарей),
        документы. ``occ`` — ответ на «Чем вы занимаетесь?» (владелец 19.11): тогда 3–4 сценария под занятие."""
        from gas_pult.connectors import calendar_mcp, mail_mcp
        if space:                                      # пространство и фокус: только свои подключения, не владельца
            have = {"docs"} if slug and (tenants.load(slug) or {}).get("docs") else set()
        else:
            have = {"mail"} if mail_mcp.boxes() else set()
            if calendar_mcp.calendars():
                have.add("calendar")
            for x in self.mcp._cached(None)[1]:            # кэш `claude mcp list`: без ожидания
                if "docs_mcp" in str(x.get("target", "")):
                    have.add("docs")
                if "mcp.vkusvill.ru" in str(x.get("target", "")):   # ВкусВилл (#327)
                    have.add("vkusvill")
        own = starters.for_occupation(occ, have, role, space) if occ else []
        return {"starters": own or starters.listing(have, role, space), "occ": occ if own else "",
                "occupations": starters.occupations() if role not in (None, "viewer") else []}
