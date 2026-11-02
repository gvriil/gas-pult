"""Отрасль «Автомойки и шиномонтаж (сеть)»: пять модулей, общие блоки, согласия, скрипты распределения пика,
сверки автопарков и утренних цифр. Живой tmux и настоящий claude не нужны."""

import importlib.util
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from gas_pult import modules

INDUSTRY = "Автомойки и шиномонтаж (сеть)"
IDS = {"carwash-tire-season", "carwash-return", "carwash-reviews", "carwash-fleet", "carwash-morning"}
USES = {"carwash-tire-season": {"reminders"}, "carwash-return": {"reminders"}, "carwash-reviews": {"reviews"},
        "carwash-fleet": {"documents", "receivables", "deadlines", "reminders"}, "carwash-morning": set()}
BASE = modules.builtin_dir()


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


def test_five_modules_one_industry():
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
        assert "{{" not in m["description"] and "{{" not in m["about"], mid
        assert all("{{" not in d["question"] for d in m["decisions"]), mid
        assert "RU-MODELS.md" in text and "152-ФЗ" in text, mid      # клиенты в РФ — российская модель
        assert len(m["title"]) + len(m["about"]) < 170, mid           # список /modules в боте — меньше 4096 знаков


def test_rules_consent_and_sources():
    season = (BASE / "carwash-tire-season" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "018/2011" in season and "№ 877" in season and "02.11.2026" in season and "КонсультантПлюс" in season
    assert "ст. 18 ФЗ «О рекламе»" in season and "+5…+7 °C" in season
    ret = (BASE / "carwash-return" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "согласие_реклама = да" in ret and "{{min_gap_days}}" in ret
    rev = (BASE / "carwash-reviews" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "управляющему филиала" in rev and "updateReply" in rev and "человек публикует" in rev
    fleet = (BASE / "carwash-fleet" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Стоп-обслуживание" in fleet and "только после «Да»" in fleet


def test_no_real_companies_in_examples():
    """Примеры — выдуманные: «Пример», «Филиал …», госномера с нулями, телефоны +7 900 000-00-xx."""
    plate = re.compile(r"\b[АВЕКМНОРСТУХABEKMHOPCTYX]\d{3}[АВЕКМНОРСТУХABEKMHOPCTYX]{2}\d{2,3}\b")
    for mid in IDS:
        for f in (BASE / mid).rglob("*.csv"):
            text = f.read_text(encoding="utf-8")
            for x in plate.findall(text):
                assert x[1:4] == "000" and x[6:] in {"00", "000"}, (f, x)
            for org in re.findall(r"(?:ООО|ИП|АО) «([^»]+)»", text):
                assert "Пример" in org, (f, org)


def test_create_workspace_copies_scripts(tmp_path):
    p = modules.create("carwash-tire-season", tmp_path / "projects")
    assert (p / ".claude" / "skills" / "peak-spread" / "peak_spread.py").is_file()
    assert (p / ".claude" / "skills" / "reminder-batch" / "SKILL.md").is_file()
    q = modules.create("carwash-fleet", tmp_path / "projects")
    for s in ("fleet-reconcile", "fleet-month-close", "workdays", "document-draft", "stop-shipment", "reminder-send"):
        assert (q / ".claude" / "skills" / s / "SKILL.md").is_file(), s
    r = subprocess.run([sys.executable, ".claude/skills/fleet-reconcile/fleet_check.py", "--contracts",
                        "data/fleet_contracts.csv", "--washes", "data/fleet_washes.csv", "--month", "2026-10"],
                       cwd=q, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "АП-01/2026" in r.stdout and "Х000ХХ00" in r.stderr


# ---------- распределение пика ----------
def test_peak_spread_example():
    ps = load("carwash-tire-season", "peak-spread", "peak_spread")
    rows, total = ps.plan(ps.read(data("carwash-tire-season", "clients.csv")),
                          ps.read(data("carwash-tire-season", "slots.csv")),
                          ps.read(data("carwash-tire-season", "branches.csv")),
                          date(2026, 11, 16), date(2026, 11, 18), 0.85, date(2026, 11, 2))
    by = {r["id"]: r for r in rows}
    assert set(by) == {"1", "2", "3", "4", "8"}    # 5 — нет согласия на рекламу, 6 — отписка, 7 — нет согласия
    assert by["1"]["сегмент"] == "хранение" and by["1"]["филиал"] == "Филиал Север"
    assert by["1"]["дата"] == "2026-11-18"                    # 16 и 17 Север загружен выше 85 %
    assert by["4"]["сегмент"] == "прошлый" and by["4"]["филиал"] == "Филиал Центр"   # Север перегружен — соседний
    assert total["пропущено"]["нет согласия или отписка"] == 3
    slots = [(r["филиал"], r["дата"], r["время"], r["пост"]) for r in rows]
    assert len(slots) == len(set(slots))                      # слот — одному клиенту


def board(ps, spec: dict[str, tuple[int, int]]) -> list[dict]:
    """spec: филиал → (всего слотов, занято) на один день."""
    out = []
    for b, (n, busy) in spec.items():
        out += [{"филиал": b, "дата": "2026-11-20", "время": f"{10 + i}:00", "пост": "1",
                 "занят": "да" if i < busy else "нет"} for i in range(n)]
    return out


def client(cid: str, **kw) -> dict:
    c = {"id": cid, "имя": f"Клиент {cid}", "хранение_шин": "нет", "филиал_хранения": "", "договор_хранения": "",
         "последний_шиномонтаж": "2026-04-01", "филиал_последний": "А", "согласие_уведомления": "да",
         "согласие_реклама": "да", "отписка": "нет"}
    return c | kw


BRANCHES = [{"филиал": "А", "соседний": "Б"}, {"филиал": "Б", "соседний": "А"}]


def test_peak_spread_storage_overflow_goes_to_neighbor_with_note():
    ps = load("carwash-tire-season", "peak-spread", "peak_spread")
    clients = [client(str(i), хранение_шин="да", филиал_хранения="А", договор_хранения=f"Х-{i}") for i in range(3)]
    rows, _ = ps.plan(clients, board(ps, {"А": (4, 2), "Б": (4, 0)}), BRANCHES, date(2026, 11, 20),
                      date(2026, 11, 20), 0.75, date(2026, 11, 2))
    assert [r["филиал"] for r in rows] == ["А", "Б", "Б"]       # в А только до 75 %: 3 из 4
    assert rows[0]["примечание"] == "" and "перевозка шин" in rows[1]["примечание"]


def test_peak_spread_past_clients_balance_and_consent():
    ps = load("carwash-tire-season", "peak-spread", "peak_spread")
    clients = [client(str(i)) for i in range(4)] + [client("x", согласие_реклама="нет"),
                                                     client("old", последний_шиномонтаж="2024-04-01")]
    rows, total = ps.plan(clients, board(ps, {"А": (4, 2), "Б": (4, 0)}), BRANCHES, date(2026, 11, 20),
                          date(2026, 11, 20), 1.0, date(2026, 11, 2))
    got = [r["филиал"] for r in rows]
    assert got.count("Б") >= 2 and len(got) == 4               # менее загруженный — первым
    assert total["пропущено"]["нет согласия или отписка"] == 2
    assert total["загрузка_после"]["А"] <= 1 and total["загрузка_после"]["Б"] <= 1


def test_peak_spread_no_slot_is_question():
    ps = load("carwash-tire-season", "peak-spread", "peak_spread")
    rows, total = ps.plan([client("1")], board(ps, {"А": (2, 2), "Б": (1, 1)}), BRANCHES, date(2026, 11, 20),
                          date(2026, 11, 20), 1.0, date(2026, 11, 2))
    assert rows[0]["филиал"] == "" and "вопрос человеку" in rows[0]["примечание"]
    assert total["пропущено"]["нет слота"] == 1


# ---------- автопарки ----------
def test_fleet_reconcile_example():
    fc = load("carwash-fleet", "fleet-reconcile", "fleet_check")
    r = fc.reconcile(fc.read(data("carwash-fleet", "fleet_contracts.csv")),
                     fc.read(data("carwash-fleet", "fleet_washes.csv")), "2026-10")
    by = {c["договор"]: c for c in r["contracts"]}
    taxi = by["АП-01/2026"]
    assert taxi["моек"] == 8 and taxi["в_лимите"] == 6 and taxi["сверх"] == 2   # латинская «A000AA00» — тот же номер
    assert taxi["к_счёту"] == "4200.00" and taxi["сверх_сумма_вопрос"] == "1800.00"
    assert by["АП-02/2026"]["сверх"] == 0 and by["АП-02/2026"]["к_счёту"] == "1600.00"
    assert by["АП-03/2026"]["лимит"] == "без лимита" and by["АП-03/2026"]["при_стопе"] == 1
    assert [w["госномер"] for w in r["unknown"]] == ["Х000ХХ00"]                # чужой номер — вопрос человеку


def test_fleet_plate_normalization():
    fc = load("carwash-fleet", "fleet-reconcile", "fleet_check")
    assert fc.plate(" a 000 aa 00 ") == fc.plate("А000АА00")
    assert fc.plate("Х000ХХ000") != fc.plate("Х000ХХ00")


# ---------- утренние цифры ----------
def test_branch_kpi_example():
    bk = load("carwash-morning", "branch-kpi", "branch_kpi")
    r = bk.report(bk.read(data("carwash-morning", "shifts.csv")), bk.read(data("carwash-morning", "branches.csv")),
                  bk.read(data("carwash-morning", "plan.csv")), "2026-11-01", 5)
    north = {x["показатель"]: x for x in r["day"] if x["филиал"] == "Филиал Север"}
    assert north["выручка"]["факт"] == 52800 and north["выручка"]["откл_проц"] == -12.0
    assert north["загрузка_проц"]["факт"] == 58.9                          # 33 пост-ч / (4 поста × 14 ч)
    assert north["средний_чек"]["факт"] == 1320 and north["допродажи_проц"]["факт"] == 11.9
    assert [(x["филиал"], x["показатель"]) for x in r["top"]][:2] == [("Филиал Юг", "допродажи_проц"),
                                                                     ("Филиал Север", "допродажи_проц")]
    assert len(r["top"]) <= 3 and r["missing"] == []


def test_branch_kpi_missing_and_no_plan():
    bk = load("carwash-morning", "branch-kpi", "branch_kpi")
    branches = [{"филиал": b, "постов": "2", "часов_работы": "10"} for b in ("А", "Б")]
    shifts = [{"дата": "2026-11-02", "филиал": "А", "выручка": "1000", "чеков": "0", "допродажи": "0",
               "занято_пост_ч": "5"},
              {"дата": "2026-11-01", "филиал": "А", "выручка": "3000", "чеков": "2", "допродажи": "300",
               "занято_пост_ч": "15"}]
    r = bk.report(shifts, branches, [], "2026-11-02", 5)
    assert r["missing"] == ["Б"] and r["top"] == []                          # нет плана — отклонений нет
    day = {x["показатель"]: x for x in r["day"]}
    assert day["средний_чек"]["факт"] == 0 and day["загрузка_проц"]["факт"] == 25.0   # деление на 0 — без падения
    mtd = {x["показатель"]: x for x in r["mtd"]}
    assert mtd["выручка"]["факт"] == 2000 and mtd["загрузка_проц"]["факт"] == 50.0
