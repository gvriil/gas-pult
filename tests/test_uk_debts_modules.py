"""«УК-старт», вторая очередь: «Долги и суды», «Проверки жилинспекции», «Сверка раскрытия в ГИС ЖКХ» и расписание
«N-й рабочий день месяца». Пени, госпошлина, рабочие дни до срока предписания, сверка раскрытия — юнит-тестами.
Живой tmux и настоящий claude не нужны."""

import importlib.util
import json
import re
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from gas_pult import bot, modules
from gas_pult.config import Config

INDUSTRY = "Управляющие компании — «УК-старт»"
NEW = {"uk-debts": {"receivables", "documents", "deadlines", "reminders"},
       "uk-inspections": {"documents", "deadlines", "reminders"},
       "uk-gis-disclosure": {"deadlines"}}
BASE = modules.builtin_dir()
WORKDAYS = BASE / "_common" / "deadlines" / "skills" / "workdays"


@pytest.fixture(autouse=True)
def own_config(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))


def load(mid: str, skill: str, name: str):
    if str(WORKDAYS) not in sys.path:                    # в пространстве workdays лежит рядом в .claude/skills/
        sys.path.insert(0, str(WORKDAYS))
    spec = importlib.util.spec_from_file_location(name, BASE / mid / "skills" / skill / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def data(mid: str, name: str) -> Path:
    return BASE / mid / "data" / name


def calendar():
    w = load("uk-inspections", "order-watch", "order_check").workdays
    return w.load([WORKDAYS / "calendar-ru.csv"])


# ---------- модули ----------
def test_new_modules_in_uk_industry():
    errors = []
    by = {m["id"]: m for m in modules.catalog(errors)}
    assert errors == []
    uk = {m["id"] for m in by.values() if m["industry"] == INDUSTRY}
    assert set(NEW) <= uk and {"uk-requests", "uk-emergency", "uk-morning"} <= uk
    for mid, uses in NEW.items():
        m = by[mid]
        assert {u["id"] for u in m["uses"]} == uses, mid
        assert m["data_sources"] and m["decisions"] and m["schedule"], mid
        assert all(s["kind"] == "client_export" for s in m["data_sources"]), mid     # без скрейпинга и входа в кабинеты
        text = modules.claude_md(m)
        assert "AskUserQuestion" in text and "{{" not in text and "## Откуда данные" in text, mid
        assert "{{" not in m["description"] and all("{{" not in s["prompt"] for s in m["schedule"]), mid
        assert "RU-MODELS.md" in text and "152-ФЗ" in text and "GigaChat" in text, mid
        assert "RU-MODELS.md" in m["description"], mid
        assert "02.11.2026" in text and "КонсультантПлюс" in text, mid               # дата сверки первоисточников
        assert len(m["title"]) + len(m["about"]) < 170, mid                         # /modules в боте < 4096 знаков


def test_debts_rules_lawyer_signs_and_steps_need_yes():
    text = (BASE / "uk-debts" / "CLAUDE.md").read_text(encoding="utf-8")
    for s in ("ст. 155", "ст. 124", "ст. 333.19", "230-ФЗ", "подписывает юрист", "только после «Да»",
              "исковом порядке", "банк данных исполнительных производств"):
        assert s in text, s
    m = modules.get("uk-debts")
    assert {"remind_after_days", "claim_after_days", "order_after_days", "order_max_sum"} <= set(m["settings"])
    for name in ("claim.md", "court-order.md"):
        assert (BASE / "uk-debts" / "templates" / name).read_text(encoding="utf-8").splitlines()[1].startswith(
            "ЧЕРНОВИК — подписывает юрист")


def test_inspections_and_disclosure_rules():
    text = (BASE / "uk-inspections" / "CLAUDE.md").read_text(encoding="utf-8")
    for s in ("248-ФЗ", "ст. 19.5", "ст. 7.23.3", "Просить продление", "подписывает"):
        assert s in text, s
    gis = (BASE / "uk-gis-disclosure" / "CLAUDE.md").read_text(encoding="utf-8")
    for s in ("ст. 161", "209-ФЗ", "Поручить", "входит в личный кабинет ГИС ЖКХ"):
        assert s in gis, s
    morning = modules.get("uk-morning")
    assert morning["settings"]["disclosure"].startswith("../uk-gis-disclosure/")
    assert morning["settings"]["orders"].startswith("../uk-inspections/")


def test_create_workspaces_copy_scripts(tmp_path):
    root = tmp_path / "projects"
    p = modules.create("uk-debts", root)
    for s in ("penalty-calc", "court-order", "debt-ladder", "case-watch", "debt-steps", "claim-draft",
              "workdays", "reminder-batch"):
        assert (p / ".claude" / "skills" / s / "SKILL.md").is_file(), s
    for f in ("key_rate.csv", "penalty_rules.csv", "cases.csv", "charges.csv", "payments.csv", "debtors.csv"):
        assert (p / "data" / f).is_file(), f
    r = subprocess.run([sys.executable, ".claude/skills/penalty-calc/penalty.py", "--charges", "data/charges.csv",
                        "--payments", "data/payments.csv", "--rates", "data/key_rate.csv", "--rules",
                        "data/penalty_rules.csv", "--on", "2026-11-02"], cwd=p, capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0, r.stderr
    assert "КонсультантПлюс" in r.stdout and "ЛС-000-01: долг" in r.stderr
    q = modules.create("uk-inspections", root)
    r = subprocess.run([sys.executable, ".claude/skills/order-watch/order_check.py", "--orders", "data/orders.csv",
                        "--on", "2026-11-02"], cwd=q, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "готовить отчёт" in r.stdout and "нет фото и актов" in r.stdout
    g = modules.create("uk-gis-disclosure", root)
    r = subprocess.run([sys.executable, ".claude/skills/disclosure-check/disclosure_check.py", "--checklist",
                        "data/disclosure_checklist.csv", "--export", "data/gis_export.csv", "--houses",
                        "data/houses.csv", "--on", "2026-11-02"], cwd=g, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "не размещено" in r.stdout


def test_examples_are_fake():
    """Примеры — выдуманные: «УК Пример», дома «Дом N», лицевые счета ЛС-000-NN, суды и ОСП «(пример)»."""
    phone = re.compile(r"\+7[\s(-]*\d[\d\s()-]{6,}\d")
    for mid in NEW:
        for f in (BASE / mid).rglob("*"):
            if not f.is_file() or f.suffix not in {".csv", ".md", ".toml", ".txt"}:
                continue
            text = f.read_text(encoding="utf-8")
            for org in re.findall(r"(?:ООО|ИП|АО) «([^»]+)»", text):
                assert "Пример" in org, (f, org)
            for x in re.findall(r"ЛС-[\d-]+", text):
                assert re.fullmatch(r"ЛС-000-\d\d", x), (f, x)
            for x in re.findall(r"судебного участка № (\d+)", text):
                assert set(x) == {"0"}, (f, x)
            assert not phone.findall(text) or all("900 000-00" in x for x in phone.findall(text)), f


# ---------- пени ----------
RATES = [(date(2025, 1, 1), Decimal(21)), (date(2026, 6, 1), Decimal(18))]


def test_penalty_shares_30_90_boundaries():
    pc = load("uk-debts", "penalty-calc", "penalty")
    due = date(2026, 1, 10)
    assert pc.accrue(Decimal(1000), due, date(2026, 2, 9), Decimal(21), []) == 0            # 30-й день — без пеней
    assert pc.accrue(Decimal(1000), due, date(2026, 2, 10), Decimal(21), []) == Decimal("0.70")   # 31-й: 1/300
    assert pc.accrue(Decimal(1000), due, date(2026, 4, 10), Decimal(21), []) == Decimal("42.00")  # 31–90: 60 дн.
    assert pc.accrue(Decimal(1000), due, date(2026, 4, 11), Decimal(21), []) == Decimal("43.62")  # 91-й: 1/130
    assert pc.share(30) == 0 and pc.share(31) == pc.share(90) == Decimal(1) / 300 and pc.share(91) == Decimal(1) / 130


def test_penalty_rate_on_payment_day_and_calc_day():
    pc = load("uk-debts", "penalty-calc", "penalty")
    charges = [{"лс": "ЛС-000-01", "период": "2026-01", "начислено": "1000", "срок_оплаты": ""}]
    pays = [{"лс": "ЛС-000-01", "дата": "2026-02-10", "сумма": "400", "период": ""}]
    rows = pc.account(charges, pays, date(2026, 6, 1), RATES, [])
    r = rows[0]
    assert r["срок_оплаты"] == "2026-02-10" and r["остаток"] == "600" and r["оплачено"] == "400"
    # 400 оплачено в срок — без пеней; 600 не оплачено — по ставке на дату расчёта (18 %, а не 21 %)
    assert Decimal(r["пени"]) == pc.accrue(Decimal(600), date(2026, 2, 10), date(2026, 6, 1), Decimal(18), [])
    late = pc.account(charges, [{"лс": "ЛС-000-01", "дата": "2026-05-20", "сумма": "1000", "период": ""}],
                      date(2026, 11, 2), RATES, [])[0]
    assert late["остаток"] == "0" and late["дней_просрочки"] == 0
    assert Decimal(late["пени"]) == pc.accrue(Decimal(1000), date(2026, 2, 10), date(2026, 5, 20), Decimal(21), [])


def test_penalty_moratorium_and_cap():
    pc = load("uk-debts", "penalty-calc", "penalty")
    due = date(2026, 1, 10)
    full = pc.accrue(Decimal(1000), due, date(2026, 4, 10), Decimal(21), [])
    mor = [(date(2026, 2, 10), date(2026, 2, 19), "мораторий", Decimal(0))]          # 10 дней моратория
    assert pc.accrue(Decimal(1000), due, date(2026, 4, 10), Decimal(21), mor) == full - Decimal("7.00")
    cap = [(date(2026, 1, 1), date(2026, 12, 31), "ставка_не_выше", Decimal("9.5"))]
    assert pc.accrue(Decimal(1000), due, date(2026, 4, 10), Decimal(21), cap) == Decimal("19.00")  # 60 × 9,5/300
    old = [(date(2026, 2, 10), date(2026, 2, 19), "мораторий", Decimal(0), date(2026, 1, 1))]   # только старый долг
    assert pc.accrue(Decimal(1000), due, date(2026, 4, 10), Decimal(21), old) == full
    assert pc.accrue(Decimal(1000), date(2025, 12, 10), date(2026, 3, 10), Decimal(21), old) < pc.accrue(
        Decimal(1000), date(2025, 12, 10), date(2026, 3, 10), Decimal(21), [])
    with pytest.raises(ValueError, match="неизвестное правило"):
        pc.rules_from([{"с": "2026-01-01", "по": "2026-01-02", "правило": "скидка", "значение": "1"}])
    with pytest.raises(LookupError, match="нет ставки"):
        pc.rate_on(date(2020, 1, 1), RATES)


def test_penalty_payment_goes_to_oldest_debt():
    pc = load("uk-debts", "penalty-calc", "penalty")
    charges = [{"лс": "x", "период": p, "начислено": "100"} for p in ("2026-02", "2026-01", "2026-03")]
    got = pc.allocate(charges, [{"дата": "2026-04-01", "сумма": "150", "период": ""},
                                {"дата": "2026-04-02", "сумма": "100", "период": "2026-03"}])
    assert got["2026-01"] == [(date(2026, 4, 1), Decimal(100))]
    assert got["2026-02"] == [(date(2026, 4, 1), Decimal(50))]
    assert got["2026-03"] == [(date(2026, 4, 2), Decimal(100))]
    assert pc.default_due("2026-01") == date(2026, 2, 10)                    # до 177-ФЗ — до 10-го
    assert pc.default_due("2026-02") == date(2026, 3, 15)                    # 177-ФЗ: с февраля 2026 — до 15-го
    assert pc.default_due("2026-12") == date(2027, 1, 15) and pc.default_due("2026-12", 20) == date(2027, 1, 20)


def test_penalty_example_data_and_rules():
    pc = load("uk-debts", "penalty-calc", "penalty")
    rates = pc.rates_from(pc.read(data("uk-debts", "key_rate.csv")))
    rules = pc.rules_from(pc.read(data("uk-debts", "penalty_rules.csv")))
    assert rates[0][0] <= date(2022, 2, 28) and rates[-1][0] <= date(2026, 11, 2)
    assert any(k == "мораторий" and a == date(2020, 4, 6) for a, _, k, *_ in rules)
    assert any(k == "ставка_не_выше" and v == Decimal("9.5") and b == date(2026, 12, 31) for _, b, k, v, *_ in rules)
    assert any(k == "мораторий" and x and x[0] == date(2022, 4, 1) for _, _, k, _, *x in rules)   # ПП № 497
    rows = pc.account([c for c in pc.read(data("uk-debts", "charges.csv")) if c["лс"] == "ЛС-000-01"],
                      [p for p in pc.read(data("uk-debts", "payments.csv")) if p["лс"] == "ЛС-000-01"],
                      date(2026, 11, 2), rates, rules)
    assert rows[0]["остаток"] == "0.00" and Decimal(rows[1]["остаток"]) == Decimal("1800.00")
    assert sum(Decimal(r["остаток"]) for r in rows) == Decimal("35400.00")
    assert all(Decimal(r["пени"]) >= 0 for r in rows) and Decimal(rows[1]["пени"]) > 0


# ---------- госпошлина ----------
@pytest.mark.parametrize("price, claim, order", [
    (45_000, 4_000, 2_000), (100_000, 4_000, 2_000), (200_000, 7_000, 3_500), (300_000, 10_000, 5_000),
    (450_000, 13_750, 6_875), (500_000, 15_000, 7_500), (1_000_000, 25_000, 12_500),
])
def test_court_duty_scale(price, claim, order):
    d = load("uk-debts", "court-order", "duty")
    assert d.claim(Decimal(price)) == claim and d.order(Decimal(price)) == order


def test_court_duty_rounding_and_cap():
    d = load("uk-debts", "court-order", "duty")
    assert d.claim(Decimal("100100.50")) == 4_003                     # 4 000 + 3 % × 100,50 = 4 003,015 → 4 003
    assert d.claim(Decimal(10) ** 9) == 900_000                       # не более 900 000
    with pytest.raises(ValueError):
        d.claim(Decimal(0))


# ---------- предписания: рабочие дни ----------
def test_order_report_date_workdays():
    oc = load("uk-inspections", "order-watch", "order_check")
    cal = calendar()
    assert oc.back(date(2026, 11, 10), 5, cal) == date(2026, 11, 2)   # 4 ноября — праздник
    assert oc.back(date(2026, 11, 20), 5, cal) == date(2026, 11, 13)  # выходные не считаются
    assert oc.workdays.left(date(2026, 11, 20), date(2026, 11, 13), cal) == 5
    assert oc.back(date(2027, 1, 12), 2, cal) == date(2026, 12, 30)   # 31.12 и каникулы


def test_order_stages(tmp_path):
    oc = load("uk-inspections", "order-watch", "order_check")
    cal = calendar()
    row = {"предписание": "П-0/2026", "пункт": "1", "дом": "Дом 1", "исполнитель": "И", "статус": "открыт"}
    rows = [row | {"срок": "2026-12-15"}, row | {"пункт": "2", "срок": "2026-11-10"},
            row | {"пункт": "3", "срок": "2026-11-02"}, row | {"пункт": "4", "срок": "2026-10-30"},
            row | {"пункт": "5", "срок": "2026-11-12"},
            row | {"пункт": "6", "срок": "2026-11-10", "статус": "выполнен"}]
    (tmp_path / "П-0-2026" / "2").mkdir(parents=True)
    (tmp_path / "П-0-2026" / "2" / "акт.pdf").write_bytes(b"%PDF")
    (tmp_path / "П-0-2026" / "2" / "README.md").write_text("не считается")
    got = {r["пункт"]: r for r in oc.check(rows, date(2026, 11, 2), cal, 5, 3, tmp_path)}
    assert "6" not in got
    assert got["1"]["stage"] == "в работе"
    assert got["2"]["stage"] == "готовить отчёт" and got["2"]["files"] == 1
    assert got["3"]["stage"] == "СРОК СЕГОДНЯ" and got["4"]["stage"] == "ПРОСРОЧЕНО"
    assert got["5"]["stage"] == "напомнить исполнителю" and got["5"]["left"] == 7
    assert [r["пункт"] for r in oc.check(rows, date(2026, 11, 2), cal, 5, 3, tmp_path)][:2] == ["4", "3"]


# ---------- расписание «N-й рабочий день месяца» ----------
HEAD = 'title = "Т"\nindustry = "Пробная"\nabout = "x"\n'


def write(base: Path, mid: str, toml: str):
    d = base / mid
    d.mkdir(parents=True)
    (d / "module.toml").write_text(toml, encoding="utf-8")
    (d / "CLAUDE.md").write_text("# Роль\n", encoding="utf-8")


def test_nth_workday_by_calendar():
    cal = modules.work_calendar()
    assert modules.nth_workday(2026, 11, 1, cal) == date(2026, 11, 2)      # 1 ноября — воскресенье
    assert modules.nth_workday(2026, 11, 2, cal) == date(2026, 11, 3)
    assert modules.nth_workday(2026, 11, 3, cal) == date(2026, 11, 5)      # 4 ноября — праздник
    assert modules.nth_workday(2027, 1, 1, cal) == date(2027, 1, 11)       # каникулы
    assert modules.nth_workday(2030, 1, 1, cal) == date(2030, 1, 1)        # нет календаря на год — пн–пт
    assert modules.nth_workday(2026, 2, 25, cal) is None


def test_workday_schedule_parse_and_errors(tmp_path):
    base = tmp_path / "cfg" / "modules"
    write(base, "monthly", HEAD + '[[schedule]]\nworkday = 1\nat = "09:00"\nprompt = "сверка"\n')
    write(base, "bad-wd", HEAD + '[[schedule]]\nworkday = 11\nat = "09:00"\nprompt = "p"\n')
    write(base, "both", HEAD + '[[schedule]]\nworkday = 1\nevery = 10\nprompt = "p"\n')
    errors = []
    by = {m["id"]: m for m in modules.catalog(errors)}
    s = by["monthly"]["schedule"][0]
    assert s["workday"] == 1 and s["when"] == "09:00, 1-й рабочий день месяца" and s["title"] == s["when"]
    assert "bad-wd" not in by and "both" not in by
    assert "от 1 до 10" in "\n".join(errors) and "либо every, либо workday" in "\n".join(errors)
    gis = by["uk-gis-disclosure"]["schedule"][0]
    assert gis["workday"] == 1 and "рабочий день месяца" in gis["when"]


def test_workday_schedule_due_once_a_month(tmp_path):
    base = tmp_path / "cfg" / "modules"
    write(base, "monthly", HEAD + '[[schedule]]\nworkday = 1\nat = "09:00"\nprompt = "сверка"\n'
                                  '[[schedule]]\nat = "09:00"\nprompt = "каждый день"\n')
    root = tmp_path / "projects"
    p = modules.create("monthly", root)
    mark = json.loads((p / modules.MARK).read_text())
    mark["created"] = int(datetime(2026, 10, 1).timestamp())
    (p / modules.MARK).write_text(json.dumps(mark))
    sch = modules.Schedule(tmp_path / "modules.json")

    def prompts(now):
        return [item["prompt"] for _, _, item in sch.due([root], now)]
    assert prompts(datetime(2026, 11, 1, 9, 0)) == ["каждый день"]                   # воскресенье 1-го — не рабочий
    assert sorted(prompts(datetime(2026, 11, 2, 9, 5))) == ["каждый день", "сверка"]  # 1-й рабочий — оба, раздельно
    assert prompts(datetime(2026, 11, 2, 10, 0)) == []                                 # не дважды
    assert prompts(datetime(2026, 11, 3, 9, 0)) == ["каждый день"]
    assert "сверка" in prompts(datetime(2026, 12, 1, 9, 0))
    assert "сверка" not in prompts(datetime(2027, 1, 4, 9, 0))                        # каникулы
    assert "сверка" in prompts(datetime(2027, 1, 11, 11, 30))                          # догоняем до 3 часов


def test_bot_shows_monthly_without_weekdays(tmp_path):
    p = bot.Pult(Config(token="1:T", owners=[1], project_roots=[str(tmp_path / "projects")]))
    text = p.module_text(modules.get("uk-gis-disclosure"))
    assert "1-й рабочий день месяца —" in text and "по будням" not in text


# ---------- сверка раскрытия в ГИС ЖКХ ----------
def test_disclosure_example():
    dc = load("uk-gis-disclosure", "disclosure-check", "disclosure_check")
    rows = dc.check(dc.read(data("uk-gis-disclosure", "disclosure_checklist.csv")),
                    dc.read(data("uk-gis-disclosure", "gis_export.csv")),
                    dc.read(data("uk-gis-disclosure", "houses.csv")), date(2026, 11, 2))
    states = {r["состояние"] for r in rows}
    assert "не размещено" in states and "размещено с опозданием" in states
    assert all(r["состояние"] != "размещено" for r in rows)                           # в итог — только проблемы
