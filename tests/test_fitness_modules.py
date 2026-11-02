"""Отрасль «Фитнес-клубы (семейные)»: шесть модулей, общие блоки, согласия (152-ФЗ, ст. 18 ФЗ «О рекламе»), данные
детей, налоговый вычет со ссылками и датой сверки; скрипты продлений, «пропал», заявок, вычета, рассрочек, перехода
по возрасту и утренних цифр. Живой tmux и настоящий claude не нужны."""

import importlib.util
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from gas_pult import modules

INDUSTRY = "Фитнес-клубы (семейные)"
USES = {"fitness-renewals": {"reminders"}, "fitness-lapsed": {"reminders"}, "fitness-leads": {"reminders"},
        "fitness-tax-installments": {"documents", "receivables", "deadlines", "reminders"},
        "fitness-kids": {"reminders"}, "fitness-morning": set()}
IDS = set(USES)
BASE = modules.builtin_dir()
# Реальные сети и бренды фитнеса — в примерах их быть не должно (список не полный, только самые заметные).
BRANDS = ("world class", "x-fit", "xfit", "fitness house", "spirit", "ddx", "alex fitness", "encore", "зебра",
          "территория фитнеса", "фитнес-хаус", "ворлд класс", "crocus fitness", "c.i.t.y.", "pride club")


@pytest.fixture(autouse=True)
def own_config(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))


def load(mid: str, skill: str, name: str):
    spec = importlib.util.spec_from_file_location(name, BASE / mid / "skills" / skill / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def data(mid: str, name: str) -> Path:
    return BASE / mid / "data" / name


def test_six_modules_one_industry():
    errors = []
    by = {m["id"]: m for m in modules.catalog(errors)}
    assert errors == []
    assert {m["id"] for m in by.values() if m["industry"] == INDUSTRY} == IDS
    for mid in IDS:
        m = by[mid]
        assert {u["id"] for u in m["uses"]} == USES[mid], mid
        assert m["data_sources"] and m["decisions"] and m["schedule"], mid
        assert {s["kind"] for s in m["data_sources"]} == {"client_export", "official_api"}, mid
        text = modules.claude_md(m)
        assert "AskUserQuestion" in text and "{{" not in text and "## Откуда данные" in text, mid
        assert "{{" not in m["description"] and "{{" not in m["about"] and "{{" not in m["start"], mid
        assert all("{{" not in d["question"] and "{{" not in d["when"] for d in m["decisions"]), mid
        assert all("{{" not in s["prompt"] and "{{" not in s["title"] for s in m["schedule"]), mid
        assert "RU-MODELS.md" in text and "152-ФЗ" in text and "GigaChat" in text, mid   # клиенты в РФ
        assert "RU-MODELS.md" in m["description"], mid
        assert len(m["title"]) + len(m["about"]) < 110, mid           # /modules в боте — меньше 4096 знаков


def test_schedule_and_settings():
    by = {m["id"]: m for m in modules.catalog()}
    assert by["fitness-morning"]["schedule"][0]["at"] == "08:00"
    leads = by["fitness-leads"]["schedule"]
    assert leads[0]["every"] == 15 and leads[0]["when"] == "каждые 15 мин"     # заявки — и ночью
    assert by["fitness-renewals"]["schedule"][1]["title"] == "Точки касания до конца карты"
    raw = modules.parse(BASE / "fitness-leads")
    assert "auto_reply = нет" in raw["description"]                              # по умолчанию выключено


def test_rules_consent_children_tax():
    ren = (BASE / "fitness-renewals" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "согласие_реклама = да" in ren and "ст. 18 ФЗ «О рекламе»" in ren and "{{allowed_discount}}" in ren
    lapsed = (BASE / "fitness-lapsed" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "ст. 32 Закона РФ «О защите прав потребителей»" in lapsed and "администратор" in lapsed
    leads = (BASE / "fitness-leads" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "data/price.md" in leads and "dev.vk.com" in leads and "не проверялась" in leads
    kids = (BASE / "fitness-kids" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "законного представителя" in kids and "ст. 9 152-ФЗ" in kids and "Писать ребёнку" in kids
    tax = (BASE / "fitness-tax-installments" / "CLAUDE.md").read_text(encoding="utf-8")
    for s in ("пп. 7 п. 1 ст. 219 НК РФ", "№ 2466-р", "№ ЕД-7-11/756@", "КНД 1151160", "425-ФЗ", "150 000 ₽",
              "02.11.2026", "сверять ежегодно", "nalog.gov.ru", "КонсультантПлюс"):
        assert s in tax, s
    assert "Блокировка карты" in tax and "после «Да»" in tax


def test_examples_are_fake():
    """Примеры — выдуманные: «(пример)», «Филиал …», без реальных сетей; ИНН — нули (общая проверка — в
    test_industry_modules)."""
    for mid in IDS:
        for f in (BASE / mid).rglob("*"):
            if not f.is_file() or f.suffix not in {".csv", ".md", ".toml", ".py"}:
                continue
            text = f.read_text(encoding="utf-8")
            low = text.lower()
            for b in BRANDS:
                assert b not in low, (f, b)
            for org in re.findall(r"(?:ООО|ИП|АО|Клуб|клуб) «([^»]+)»", text):
                assert "Пример" in org or "{" in org, (f, org)


def test_create_workspace_copies_scripts(tmp_path):
    root = tmp_path / "projects"
    p = modules.create("fitness-tax-installments", root)
    for s in ("tax-certificate", "installments", "workdays", "document-draft", "debt-steps", "reminder-batch"):
        assert (p / ".claude" / "skills" / s / "SKILL.md").is_file(), s
    r = subprocess.run([sys.executable, ".claude/skills/tax-certificate/tax_check.py", "--in-list", "2025,2026"],
                       cwd=p, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "1,да,36000.00" in r.stdout
    q = modules.create("fitness-renewals", root)
    r = subprocess.run([sys.executable, ".claude/skills/renewal-risk/renewal_risk.py", "--today", "2026-11-02"],
                       cwd=q, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "Мария (пример)" in r.stderr
    for mid, script in (("fitness-lapsed", "lapsed-segment/lapsed.py"), ("fitness-leads", "lead-slots/lead_slots.py"),
                        ("fitness-kids", "age-transition/age_transition.py"),
                        ("fitness-morning", "club-kpi/club_kpi.py")):
        w = modules.create(mid, root)
        assert (w / ".claude" / "skills" / script).is_file(), mid
        assert "{{" not in (w / "CLAUDE.md").read_text(encoding="utf-8")


# ---------- продления ----------
def test_renewal_points():
    rr = load("fitness-renewals", "renewal-risk", "renewal_risk")
    pts = rr.parse_points("7, 60,30")
    assert pts == [60, 30, 7]
    assert [rr.stage(d, pts) for d in (90, 61, 60, 45, 31, 30, 20, 8, 7, 1, 0, -1)] == \
        [None, None, 60, 60, 60, 30, 30, 30, 7, 7, 7, None]
    with pytest.raises(ValueError):
        rr.parse_points("")


def test_renewal_example():
    rr = load("fitness-renewals", "renewal-risk", "renewal_risk")
    r = rr.plan(rr.read(data("fitness-renewals", "members.csv")), rr.read(data("fitness-renewals", "visits.csv")),
                date(2026, 11, 2), [60, 30, 7], 30)
    by = {t["id"]: t for t in r["touches"]}
    assert set(by) == {"1", "3", "4"}                 # 2 — в семейном, 5 — отписка, 6 — рано, 7 — карта кончилась
    assert by["1"]["точка"] == 60 and by["1"]["семья"] == "1,2" and by["1"]["предложение"].startswith("семейное")
    assert by["3"]["точка"] == 30 and by["3"]["предложение"] == ""        # нет согласия на рекламу — только срок
    assert by["4"]["точка"] == 7 and "поменьше" in by["4"]["предложение"]
    assert r["skipped"] == {"в семейном сообщении плательщику": 1, "нет согласия на уведомления или отписка": 1}
    assert [x["имя"] for x in r["risk"]] == ["Елена (пример)", "Мария (пример)", "Пётр (пример)"]
    assert all(x["риск"] == "высокий" for x in r["risk"])


def member(cid: str, end: str, **kw) -> dict:
    m = {"id": cid, "имя": f"Участник {cid}", "family_id": "", "плательщик": "да", "тип_карты": "Безлимит 12 мес.",
         "филиал": "А", "карта_по": end, "согласие_уведомления": "да", "согласие_реклама": "да", "отписка": "нет",
         "точки_отправлены": "", "без_ответа": "0"}
    return m | kw


def test_renewal_risk_scoring_and_sent_points():
    rr = load("fitness-renewals", "renewal-risk", "renewal_risk")
    today = date(2026, 11, 2)
    visits = [{"дата": f"2026-10-{d:02d}", "клиент_id": "1"} for d in (20, 22, 25, 27, 29)] + \
             [{"дата": "2026-09-10", "клиент_id": "2"}, {"дата": "2026-09-12", "клиент_id": "2"},
              {"дата": "2026-10-20", "клиент_id": "2"}]
    st = rr.visit_stats(visits, "2", today)
    assert (st["за_30"], st["прошлые_30"]) == (1, 2)
    score, level, why = rr.risk(member("2", "2026-11-25"), st, today)
    assert (score, level) == (3, "средний") and "вдвое" in why[0]               # 2 → 1 (+2), 23 дня (+1)
    assert rr.risk(member("2", "2026-11-25", без_ответа="1"), st, today)[:2] == (4, "высокий")
    assert rr.risk(member("1", "2027-06-01"), rr.visit_stats(visits, "1", today), today)[1] == "низкий"
    r = rr.plan([member("1", "2026-12-01", точки_отправлены="60;30")], visits, today, [60, 30, 7])
    assert r["touches"] == []                                                    # точка 30 уже была
    r = rr.plan([member("1", "2026-12-01", согласие_уведомления="нет")], visits, today, [60, 30, 7])
    assert r["touches"] == [] and r["skipped"] == {"нет согласия на уведомления или отписка": 1}


def test_renewal_family_window():
    rr = load("fitness-renewals", "renewal-risk", "renewal_risk")
    today = date(2026, 11, 2)
    ms = [member("1", "2026-12-01", family_id="F", плательщик="нет"), member("2", "2026-12-20", family_id="F"),
          member("3", "2027-04-01", family_id="G"), member("4", "2026-12-05", family_id="G")]
    fam = rr.families(ms, today, 30)
    assert set(fam) == {"F"}                                   # у G карты кончаются далеко друг от друга
    r = rr.plan(ms, [], today, [60, 30, 7], 30)
    assert [t["id"] for t in r["touches"]] == ["2", "4"]       # семье F — одно сообщение плательщику (2)


# ---------- «пропал» ----------
def test_lapsed_example():
    lp = load("fitness-lapsed", "lapsed-segment", "lapsed")
    r = lp.segment(lp.read(data("fitness-lapsed", "members.csv")), lp.read(data("fitness-lapsed", "visits.csv")),
                   date(2026, 11, 2), 14, 21, 14, lp.parse_freeze("12 мес.:30;6 мес.:14;3 мес.:7"))
    assert [(x["id"], x["дней"], x["заморозка_дней"]) for x in r["soft"]] == [("2", 16, 30), ("8", 18, 7)]
    assert [x["id"] for x in r["call"]] == ["6", "4"]          # ни разу не был — первым; 28 дней
    assert r["call"][1]["заморозка_дней"] == 20                 # 30 − 10 использовано
    assert r["skipped"] == {"писали меньше 14 дней назад": 1, "нет согласия на уведомления или отписка": 1}


def test_lapsed_thresholds_and_freeze():
    lp = load("fitness-lapsed", "lapsed-segment", "lapsed")
    rules = lp.parse_freeze("12 мес.:30;6 мес.:14")
    assert rules == {"12 мес.": 30, "6 мес.": 14}
    assert lp.freeze_left({"тип_карты": "Дневная 6 мес.", "заморозка_использовано": "20"}, rules) == 0
    assert lp.freeze_left({"тип_карты": "Разовое", "заморозка_использовано": ""}, rules) == 0
    m = {"id": "1", "имя": "У", "тип_карты": "12 мес.", "филиал": "А", "карта_по": "2027-01-01",
         "согласие_уведомления": "да", "отписка": "нет", "последнее_сообщение": ""}
    for days, where in ((13, None), (14, "soft"), (21, "soft"), (22, "call")):
        last = date.fromordinal(date(2026, 11, 2).toordinal() - days).isoformat()
        r = lp.segment([m], [{"дата": last, "клиент_id": "1"}], date(2026, 11, 2), 14, 21, 14, rules)
        got = "soft" if r["soft"] else "call" if r["call"] else None
        assert got == where, days


# ---------- заявки ----------
def test_lead_slots_night_reply():
    ls = load("fitness-leads", "lead-slots", "lead_slots")
    leads = {x["id"]: x for x in ls.read(data("fitness-leads", "leads.csv"))}
    slots = ls.read(data("fitness-leads", "slots.csv"))
    now = datetime(2026, 11, 2, 1, 30)
    assert ls.is_night(now) and not ls.is_night(datetime(2026, 11, 2, 12, 0))
    r = ls.propose(leads["3"], slots, now, 3, 10)                # интерес пуст — оба вида
    exc = [(s["филиал"], s["дата"], s["время"]) for s in r["экскурсия"]]
    assert exc[0] == ("Филиал Центр", "2026-11-02", "12:00")    # 10:00 занят, Север 08:00 — раньше 11:30
    assert exc[-1][0] == "Филиал Север"                          # сначала филиал заявки
    assert [s["время"] for s in r["вводная"]][:2] == ["19:00", "11:00"]   # 3 ноября 9:00 — занят
    r = ls.propose(leads["4"], slots, now, 3, 10)
    assert list(r) == ["экскурсия"] and r["экскурсия"][0]["филиал"] == "Филиал Север"


def test_lead_slots_no_free_and_warm_list():
    ls = load("fitness-leads", "lead-slots", "lead_slots")
    full = [{"филиал": "А", "дата": "2026-11-03", "время": "10:00", "вид": "экскурсия", "мест": "2", "занято": "2"}]
    assert ls.propose({"интерес": "экскурсия", "филиал": "А"}, full, datetime(2026, 11, 2, 23, 0)) == {"экскурсия": []}
    w = ls.warm(ls.read(data("fitness-leads", "leads.csv")), datetime(2026, 11, 2, 8, 30), 24)
    # 5 — отказ, 6 — старше суток; сначала новые без ответа (ночные), потом без записи, потом записанные
    assert [(x["id"], x["ночью"]) for x in w] == [("4", "да"), ("3", "да"), ("2", ""), ("1", "")]


# ---------- налоговый вычет и рассрочки ----------
def test_inn_checksum():
    tc = load("fitness-tax-installments", "tax-certificate", "tax_check")
    assert tc.inn_ok("000000000000")
    d = [1, 2, 3, 4, 5, 6, 7, 8, 9, 1]                # выдуманный ИНН: контрольные числа считаем здесь же
    d.append(sum(w * x for w, x in zip(tc.W11, d, strict=True)) % 11 % 10)
    d.append(sum(w * x for w, x in zip(tc.W12, d, strict=True)) % 11 % 10)
    good = "".join(map(str, d))
    bad = good[:-1] + str((d[-1] + 1) % 10)
    assert tc.inn_ok(good) and not tc.inn_ok(bad)
    assert not tc.inn_ok("0" * 11) and not tc.inn_ok("0" * 11 + "a")


def test_tax_check_example():
    tc = load("fitness-tax-installments", "tax-certificate", "tax_check")
    pays = tc.read(data("fitness-tax-installments", "payments.csv"))
    res = {r["id"]: tc.check(r, pays, {2025, 2026}) for r in tc.read(data("fitness-tax-installments",
                                                                         "tax_requests.csv"))}
    assert res["1"]["ok"] and res["1"]["сумма"] == "36000.00" and res["1"]["не_по_перечню"] == "4500.00"
    assert res["2"]["ok"] and res["2"]["сумма"] == "36000.00"                       # ребёнок 10 лет
    assert not res["3"]["ok"] and len(res["3"]["problems"]) == 3                     # ИНН, нет в перечне, нет оплат
    assert res["4"]["problems"] == ["за родителей — только расходы с 2026 года"]
    assert "19 лет" in res["5"]["problems"][0]


def test_tax_check_rules():
    tc = load("fitness-tax-installments", "tax-certificate", "tax_check")
    pay = [{"дата": "2026-03-01", "клиент_id": "1", "сумма": "1000", "по_перечню": "да"}]
    base = {"id": "x", "клиент_id": "1", "инн": "000000000000", "год": "2026", "за_кого": "сам"}
    assert tc.check(base, pay, {2026})["ok"]
    assert "нет в перечне" in tc.check(base, pay, {2025})["problems"][0]
    kid = base | {"за_кого": "ребёнок", "фио_за_кого": "Р", "дата_рождения_за_кого": "2005-01-01"}
    assert not tc.check(kid, pay, {2026})["ok"]                                     # 21 год, не очно
    assert tc.check(kid | {"очно": "да"}, pay, {2026})["ok"]                         # до 24 при очном обучении
    parent = base | {"за_кого": "родитель", "фио_за_кого": "Р", "пенсионер": "да"}
    assert tc.check(parent, pay, {2026})["ok"]
    assert not tc.check(parent | {"пенсионер": "нет"}, pay, {2026})["ok"]
    old = base | {"год": "2021"}
    assert any("2022" in p for p in tc.check(old, [], {2021})["problems"])
    assert not tc.check(base | {"за_кого": "сосед"}, pay, {2026})["ok"]


def test_installments_example():
    ins = load("fitness-tax-installments", "installments", "installments")
    r = ins.report(ins.read(data("fitness-tax-installments", "installments.csv")), date(2026, 11, 2), 3)
    assert [x["договор"] for x in r["скоро"]] == ["Р-01/2026"] and [x["договор"] for x in r["сегодня"]] == ["Р-02/2026"]
    assert [(x["договор"], x["корзина"], x["долг"]) for x in r["просрочен"]] == [
        ("Р-04/2026", "61–90", "7000.00"), ("Р-03/2026", "1–30", "3000.00")]        # частичная оплата — остаток
    assert r["итого_просрочено"] == "10000.00"
    assert [ins.bucket(d) for d in (1, 30, 31, 60, 61, 90, 91)] == ["1–30", "1–30", "31–60", "31–60", "61–90",
                                                                    "61–90", "больше 90"]


# ---------- детское направление ----------
def test_age_and_leap_birthday():
    at = load("fitness-kids", "age-transition", "age_transition")
    assert at.age(date(2019, 12, 15), date(2026, 12, 14)) == 6 and at.age(date(2019, 12, 15), date(2026, 12, 15)) == 7
    leap = date(2016, 2, 29)
    assert at.age(leap, date(2027, 2, 28)) == 10 and at.age(leap, date(2027, 3, 1)) == 11
    assert at.birthday(leap, 11) == date(2027, 3, 1) and at.birthday(leap, 12) == date(2028, 2, 29)


def test_age_transition_example():
    at = load("fitness-kids", "age-transition", "age_transition")
    r = at.transitions(at.read(data("fitness-kids", "children.csv")), at.read(data("fitness-kids", "groups.csv")),
                       date(2026, 11, 2), 60)
    assert [(x["id"], x["с"]) for x in r["move"]] == [("4", "2026-11-20"), ("1", "2026-12-15")]
    assert r["move"][0]["варианты"] == []                                           # гимнастики 13+ нет — вопрос
    assert r["move"][1]["варианты"] == ["Плавание 7–10 (Центр)", "Плавание 7–10 (Север)"]   # сначала свой филиал
    assert r["skipped"] == [{"id": "6", "почему": "нет согласия родителя на обработку данных ребёнка"}]


def test_age_transition_younger_than_group():
    at = load("fitness-kids", "age-transition", "age_transition")
    groups = [{"группа": "7–10", "направление": "п", "возраст_от": "7", "возраст_до": "10", "филиал": "А"},
              {"группа": "4–6", "направление": "п", "возраст_от": "4", "возраст_до": "6", "филиал": "Б"}]
    kid = {"id": "1", "имя": "Р", "дата_рождения": "2021-01-01", "группа": "7–10", "согласие_родителя": "да"}
    r = at.transitions([kid], groups, date(2026, 11, 2), 60)
    assert r["move"][0]["почему"].startswith("младше группы") and r["move"][0]["варианты"] == ["4–6"]


# ---------- утренние цифры ----------
def test_club_kpi_example():
    ck = load("fitness-morning", "club-kpi", "club_kpi")
    r = ck.report(ck.read(data("fitness-morning", "sales.csv")), ck.read(data("fitness-morning", "plan.csv")),
                  ck.read(data("fitness-morning", "classes.csv")), "2026-11-01", 10, 40, 95)
    c = {x["показатель"]: x for x in r["day"] if x["филиал"] == "Филиал Центр"}
    assert c["новые_карт"]["план"] == 2.0 and c["новые_карт"]["откл_проц"] == -50.0      # 60 в месяц / 30 дней
    assert c["выручка"]["факт"] == 125000 and c["выручка"]["откл_проц"] == 25.0
    assert [(x["филиал"], x["показатель"]) for x in r["top"]] == [
        ("Филиал Север", "новые_карт"), ("Филиал Центр", "новые_карт"), ("Филиал Центр", "продления_карт")]
    load_ = {x["филиал"]: x for x in r["load"]}
    assert load_["Филиал Центр"]["загрузка_проц"] == 65.8 and load_["Филиал Север"]["загрузка_проц"] == 50.0
    assert {x["занятие"] for x in r["full"]} == {"Йога", "Сайкл"}
    assert {x["занятие"] for x in r["empty"]} == {"Аквааэробика", "Стретчинг"}      # Пилатес 40 % — не пустое


def test_club_kpi_mtd_and_missing():
    ck = load("fitness-morning", "club-kpi", "club_kpi")
    plan = [{"месяц": "2026-02", "филиал": "А", "новые_карт": "28", "продления_карт": "", "выручка": "280000"}]
    sales = [{"дата": "2026-02-01", "филиал": "А", "вид": "новая", "карт": "3", "сумма": "30000"},
             {"дата": "2026-02-02", "филиал": "А", "вид": "продление", "карт": "1", "сумма": "10000"},
             {"дата": "2026-01-31", "филиал": "А", "вид": "новая", "карт": "9", "сумма": "90000"}]
    r = ck.report(sales, plan, [], "2026-02-02", 10)
    mtd = {x["показатель"]: x for x in r["mtd"]}
    assert mtd["новые_карт"]["план"] == 2.0 and mtd["новые_карт"]["факт"] == 3          # 28 / 28 дней × 2
    assert mtd["продления_карт"]["план"] is None and mtd["продления_карт"]["откл_проц"] is None
    assert mtd["выручка"]["откл_проц"] == 100.0
    assert r["no_classes"] == ["А"] and r["load"] == []
