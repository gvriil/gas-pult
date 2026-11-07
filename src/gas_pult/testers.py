"""Тестировщики демо-пространств: «Позвать на помощь» и сводка за день владельцу (задача 31, п. 7–8).

- ``help_message`` — что получает владелец, когда тестировщик нажал «Позвать на помощь» в панели или написал /help
  боту: кто, какое пространство, какая сессия, последний вопрос агента (меню на экране — простыми словами; нет — конец
  последнего ответа) и кнопка «Открыть сессию» (панель сразу на этой сессии).
- ``report`` — раз в день (вместе с утренней сводкой) и по /testers: по каждому пространству с тестировщиками — что
  делали (их сообщения за сутки), где застряли (агент ждёт ответа), какие ошибки (служебные строки Claude Code в
  ответах), сколько потратили (расход папки Claude пространства за сегодня).

Окна читаются через tmux пространства (``tenants.tmux_of``), журналы — из его папки Claude (группа ``pult-ro``).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from gas_pult import humanize, tenants, transcripts, usage
from gas_pult.spaces import wid_of

QUESTION_MAX = 400
HELP_EVERY = 300                       # с: один зов на помощь из одной сессии — не чаще раза в 5 минут


def testers(ppl) -> dict[str, list[dict]]:
    """Пространство → люди-тестировщики (из people.json)."""
    out: dict[str, list[dict]] = {}
    for p in ppl.list():
        if p.get("tenant") and p.get("role") in ("member", "viewer"):
            out.setdefault(p["tenant"], []).append(p)
    return out


def who(p: dict) -> str:
    return p.get("name") or (f"@{p['username']}" if p.get("username") else str(p.get("id", "")))


def windows(slug: str) -> list[dict]:
    """Окна Claude пространства с номерами панели (``t:<slug>:@N``); пространство недоступно — []."""
    try:
        ws = tenants.tmux_of(slug).windows()
    except OSError:
        return []
    return [{**w, "raw": w["id"], "id": wid_of(slug, w["id"]), "space": slug}
            for w in ws if w.get("cmd") == "claude" or w.get("stopped")]


def question(slug: str, w: dict) -> str:
    """Последний вопрос агента: меню/вопрос на экране — его заголовок и варианты; иначе — конец последнего ответа."""
    try:
        lines = tenants.tmux_of(slug).screen(w["raw"], 60)
    except OSError:
        lines = []
    ask = humanize.parse(lines) if lines else None
    if ask:
        opts = " / ".join(o.get("label_ru") or o.get("text", "") for o in ask["options"] if o.get("key") != "details")
        return cut(f"{ask['title_ru']}" + (f" ({opts})" if opts else ""), QUESTION_MAX)
    home = tenants.paths(slug)["claude"]
    text = transcripts.last_answer(w["path"], home) if w.get("path") else ""
    return cut(text.strip().split("\n\n")[-1] if text else "", QUESTION_MAX)


def cut(text: str, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def help_message(person: dict, slug: str, w: dict | None, panel_url: str = "") -> tuple[str, dict | None]:
    """(текст владельцу, кнопки). ``w`` — окно, откуда звали (None — из бота без сессии)."""
    t = tenants.load(slug) or {}
    lines = [f"🆘 {who(person)} зовёт на помощь — пространство «{t.get('title') or slug}»."]
    if w:
        lines.append(f"Сессия: «{w.get('name', '')}»")
        if q := question(slug, w):
            lines.append(f"Последний вопрос агента: {q}")
    else:
        lines.append("Сессий в пространстве нет — человек ещё не начал.")
    kb = None
    if panel_url:
        url = panel_url + ("&" if "?" in panel_url else "?") + (f"session={w['id']}" if w else "view=sessions")
        label = "📱 Открыть сессию" if w else "📱 Открыть панель"
        kb = {"inline_keyboard": [[{"text": label, "web_app": {"url": url}}]]}
    return "\n".join(lines), kb


def pick(ws: list[dict]) -> dict | None:
    """Из бота (/help) — сессия, где агент ждёт ответа, иначе самая свежая по журналу."""
    if not ws:
        return None
    home_ok = [w for w in ws if not w.get("stopped")] or ws
    return max(home_ok, key=lambda w: transcripts.revision(w.get("path", ""), tenants.paths(w["space"])["claude"]))


def report(ppl, meter, now: float | None = None, hours: int = 24) -> str:
    """Сводка по тестировщикам за ``hours`` часов; тестировщиков нет — пусто."""
    who_by = testers(ppl)
    if not who_by:
        return ""
    now = time.time() if now is None else now
    since = datetime.fromtimestamp(now, UTC) - timedelta(hours=hours)   # журналы Claude — время UTC
    since_ts = since.strftime("%Y-%m-%d %H:%M")
    out = [f"🧪 Тестировщики за {hours} ч"]
    for slug, ppl_ in sorted(who_by.items()):
        t = tenants.load(slug) or {}
        home = tenants.paths(slug)["claude"]
        block = [f"\n«{t.get('title') or slug}» — {', '.join(who(p) for p in ppl_)}"]
        did, errors, stuck, n = [], [], [], 0
        for w in windows(slug):
            items, _ = transcripts.history(w.get("path", ""), 200, home=home) if w.get("path") else ([], False)
            fresh = [x for x in items if str(x.get("ts", "")) >= since_ts]
            mine = [x for x in fresh if x["role"] == "user"]
            if mine:
                n += len(mine)
                did.append(f"«{w.get('name', '')}»: " + "; ".join(cut(x["text"], 80) for x in mine[:3])
                           + (f" (+{len(mine) - 3})" if len(mine) > 3 else ""))
            for x in fresh:
                if x["role"] == "assistant" and (e := humanize.error(x.get("text") or "", strict=True)):
                    errors.append(f"«{w.get('name', '')}»: {e['ru']}")
            try:
                ask = humanize.parse(tenants.tmux_of(slug).screen(w["raw"], 60))
            except OSError:
                ask = None
            if ask:
                stuck.append(f"«{w.get('name', '')}» ждёт ответа: {cut(ask['title_ru'], 120)}")
        day = usage.public(meter.day(home)) if home.is_dir() else None
        if not did and not stuck and not errors:
            block.append("  ничего не делали")
        else:
            block.append(f"  Что делали ({n} сообщ.):" if did else "  Сообщений не было.")
            block += [f"   • {x}" for x in did[:6]]
            if stuck:
                block.append("  Где застряли:")
                block += [f"   • {x}" for x in stuck[:5]]
            if errors:
                block.append(f"  Ошибки ({len(errors)}):")
                block += [f"   • {x}" for x in dict.fromkeys(errors)][:5]
        if day and day.get("total"):
            usd = day.get("usd")
            est = " (оценка)" if day.get("cost_source") == "estimate" else ""
            block.append(f"  Потрачено сегодня: {'$' + format(usd, '.2f') + est if usd is not None else 'цена ?'}"
                         f" · {day['total']} токенов")
        out += block
    return "\n".join(out)
