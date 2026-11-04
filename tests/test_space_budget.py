"""Бюджет пространства — запас на период (задача 35): перерасход в будни, компенсация в выходные, конец периода,
новый период, потолок дня, старый budget.json, пополнения и сообщения владельцу на 80% / 100%."""

from datetime import date, timedelta

import pytest

from gas_pult import space_budget as sb

MON = date(2026, 11, 2)                                   # понедельник; период 30 дней — со 2.11 по 1.12


def cfg(**kw):
    return sb.config({"daily_usd": 4, "period_days": 30, "start": MON.isoformat(), **kw})


def week(spent_by_weekday, first=MON, weeks=1):
    """{день: USD}: будни — по списку (пн…пт), выходные — 0."""
    out = {}
    for w in range(weeks):
        for i in range(7):
            d = first + timedelta(days=7 * w + i)
            out[d.isoformat()] = spent_by_weekday[i] if i < 5 else 0.0
    return out


def test_overspend_on_weekdays_is_fine_while_reserve_lasts():
    c = cfg()
    spent = {(MON + timedelta(days=i)).isoformat(): 9.0 for i in range(5)}     # пн–пт по $9 при норме $4
    b = sb.state(c, spent, MON + timedelta(days=4))
    assert b["reserve"] == 120 and b["spent"] == 45 and b["left"] == 75 and b["today"] == 9
    assert not b["over"] and b["reason"] == ""                                   # жёсткого лимита дня нет
    assert b["end"] == "2026-12-01" and b["pace"] == 9.0
    assert b["enough_until"] == (MON + timedelta(days=4 + 8)).isoformat()      # $75 / $9 в день ≈ 8 дней
    assert not b["enough_all"]


def test_weekend_compensates():
    c = cfg()
    spent = week([9, 9, 9, 9, 9])                                                # выходные — по нулям
    b = sb.state(c, spent, MON + timedelta(days=6))
    assert b["spent"] == 45 and b["left"] == 75 and b["pace"] == round(45 / 7, 2)
    # тот же расход, но через неделю нулей темп ниже — хватает до конца периода
    b = sb.state(c, spent, MON + timedelta(days=13))
    assert b["pace"] == round(45 / 14, 2) and b["enough_all"] and b["enough_until"] == b["end"]


def test_unspent_stays_in_reserve():
    c = cfg()
    b = sb.state(c, {MON.isoformat(): 1.0}, MON + timedelta(days=9))            # 10 дней почти без трат
    assert b["left"] == 119 and b["enough_all"] and not b["over"]


def test_period_end_and_stop():
    c = cfg()
    spent = {(MON + timedelta(days=i)).isoformat(): 6.0 for i in range(20)}    # 20 дней по $6 = $120
    b = sb.state(c, spent, MON + timedelta(days=19))
    assert b["over"] and b["reason"] == "period" and b["left"] == 0 and b["pct"] == 1.0
    assert b["enough_until"] == (MON + timedelta(days=19)).isoformat() and not b["enough_all"]


def test_new_period_starts_full():
    c = cfg()
    spent = {(MON + timedelta(days=i)).isoformat(): 6.0 for i in range(30)}    # весь прошлый период — перерасход
    nxt = MON + timedelta(days=30)
    b = sb.state(c, spent, nxt)
    assert b["start"] == nxt.isoformat() and b["end"] == (nxt + timedelta(days=29)).isoformat()
    assert b["spent"] == 0 and b["left"] == 120 and not b["over"]
    assert sb.period(c, MON + timedelta(days=65)) == (MON + timedelta(days=60), MON + timedelta(days=89))


def test_day_cap_optional():
    assert sb.state(cfg(), {MON.isoformat(): 30.0}, MON)["over"] is False      # по умолчанию потолка дня нет
    b = sb.state(cfg(day_cap_x=3), {MON.isoformat(): 12.0}, MON)
    assert b["over"] and b["reason"] == "day" and b["day_cap"] == 12
    assert not sb.state(cfg(day_cap_x=3), {MON.isoformat(): 12.0}, MON + timedelta(days=1))["over"]   # назавтра — можно


def test_legacy_budget_json():
    c = sb.config({"daily_usd": 3}, fallback_start=MON)                         # старый вид: только норма
    assert c == {"daily": 3.0, "period_days": 30, "start": MON, "day_cap_x": None}
    assert sb.state(c, {}, MON)["reserve"] == 90
    assert sb.config(None) is None and sb.config({"daily_usd": "x"}) is None


def test_text_for_people():
    b = sb.state(cfg(), {MON.isoformat(): 2.5}, MON)
    t = sb.text(b)
    assert t.startswith("сегодня $2.50 · в запасе $117.50 до 01.12 · норма $4.00/день; при нынешнем темпе хватит")
    assert "до конца периода" in t
    assert "оценка" in sb.text({**b, "estimate": True})


def test_top_up_warn_and_remember(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    c = cfg()
    first, _ = sb.period(c, MON)
    # расход по дням — максимум увиденного: журнал удалили (сессия в корзине) — расход не уменьшается
    assert sb.remember("demo", {MON.isoformat(): 5.0}, first) == {MON.isoformat(): 5.0}
    assert sb.remember("demo", {MON.isoformat(): 1.0}, first) == {MON.isoformat(): 5.0}
    assert sb.remember("demo", {"2026-10-01": 9.0}, first) == {MON.isoformat(): 5.0}   # прошлый период — не храним
    # 80% → одно сообщение, повтор — нет; 100% — ещё одно
    b = sb.state(c, {MON.isoformat(): 100.0}, MON)
    assert sb.warn_due("demo", b) == 0.8 and sb.warn_due("demo", b) is None
    b = sb.state(c, {MON.isoformat(): 120.0}, MON)
    assert sb.warn_due("demo", b) == 1.0 and sb.warn_due("demo", b) is None
    # пополнили — запас больше, тестировщик снова может работать; пороги считаются заново
    assert sb.top_up("demo", 28, first, by=1) == 28
    b = sb.state(c, {MON.isoformat(): 120.0}, MON, sb.extra("demo", first))
    assert b["reserve"] == 148 and not b["over"] and sb.warn_due("demo", b) == 0.8
    assert sb.extra("demo", first + timedelta(days=30)) == 0                        # пополнение — только этого периода
    with pytest.raises(ValueError):
        sb.top_up("demo", 0, first)
    assert (tmp_path / "space-budget" / "demo.json").stat().st_mode & 0o777 == 0o600


def test_bot_add_button(tmp_path, monkeypatch):
    """«➕ Добавить» в сообщении владельцу: варианты (неделя нормы, две, $10) → пополнение запаса периода."""
    import json
    from types import SimpleNamespace

    from gas_pult import bot, tenants
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    root = tmp_path / "tenants"
    monkeypatch.setenv("GAS_PULT_TENANTS_ROOT", str(root))
    (root / "demo").mkdir(parents=True)
    (root / "demo" / tenants.META).write_text(json.dumps({"title": "Демо"}))
    (root / "demo" / tenants.BUDGET).write_text(json.dumps({"daily_usd": 4, "start": date.today().isoformat()}))
    sent = []
    f = SimpleNamespace(send=lambda chat, text, **kw: sent.append((text, kw)))
    bot.Pult.budget_offer(f, 1, "demo")
    rows = sent[-1][1]["reply_markup"]["inline_keyboard"]
    assert [r[0]["callback_data"] for r in rows] == ["ba:demo:28", "ba:demo:56", "ba:demo:10"]
    bot.Pult.budget_add(f, 1, "demo:28", 1)
    assert "пополнен на $28" in sent[-1][0]
    first, _ = sb.period(tenants.load("demo")["budget"], date.today())
    assert sb.extra("demo", first) == 28
    bot.Pult.budget_add(f, 1, "../x:28", 1)
    assert "нет бюджета" in sent[-1][0]
