"""Отраслевые модули: каталог по отраслям, общие блоки через uses, источники данных, обезличенные примеры,
рабочие дни РФ и расписание «каждые N минут». Живой tmux и настоящий claude не нужны."""

import importlib.util
import json
import re
from datetime import date, datetime
from pathlib import Path

import pytest

from gas_pult import bot, modules
from gas_pult.config import Config

INDUSTRIES = {
    "Селлеры WB и Ozon": {"wb-ozon-reviews", "wb-ozon-stock", "wb-ozon-prices"},
    "Бухгалтеры и юристы на аутсорсе": {"acc-primary", "acc-deadlines", "law-drafts"},
    "Поставщики HoReCa": {"horeca-orders", "horeca-reorder", "horeca-harvest", "horeca-receivables"},
    "Управляющие компании — «УК-старт»": {"uk-requests", "uk-emergency", "uk-morning"},
    "Автомойки и шиномонтаж (сеть)": {"carwash-tire-season", "carwash-return", "carwash-reviews", "carwash-fleet",
                                      "carwash-morning"},
    "Фитнес-клубы (семейные)": {"fitness-renewals", "fitness-lapsed", "fitness-leads", "fitness-tax-installments",
                                "fitness-kids", "fitness-morning"},
}
ONE_PER_INDUSTRY = ("wb-ozon-reviews", "acc-primary", "horeca-receivables", "uk-requests", "carwash-fleet",
                    "fitness-tax-installments")
RU_ONLY = {"uk-requests", "uk-emergency", "uk-morning"}
WORKDAYS = modules.builtin_dir() / "_common" / "deadlines" / "skills" / "workdays"


@pytest.fixture(autouse=True)
def own_config(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))


def industry_modules() -> list[dict]:
    ids = set().union(*INDUSTRIES.values())
    return [m for m in modules.catalog() if m["id"] in ids]


def test_catalog_groups_industries():
    errors = []
    cat = modules.catalog(errors)
    assert errors == []
    got = {}
    for m in cat:
        got.setdefault(m["industry"], set()).add(m["id"])
    for industry, ids in INDUSTRIES.items():
        # Модулей в отрасли — от 3 до 6: у фитнес-клубов шесть задач владельца (продления, «пропал», заявки,
        # вычет и рассрочки, детское, утренние цифры) — каждая отдельным пространством со своим расписанием.
        assert got[industry] == ids and 3 <= len(ids) <= 6
    order = list(dict.fromkeys(m["industry"] for m in cat))           # группы идут подряд, «Общие» — первыми
    assert order[0] == "Общие" and len(order) == len(set(order))


def test_uses_sources_decisions():
    known = modules.blocks()
    assert {"reminders", "reviews", "receivables", "documents", "deadlines"} <= set(known)
    for b in known.values():                                          # общие блоки наполнены, а не заготовки
        assert len(b["skills"]) >= 1 and len(b["rules"]) > 400 and "Заготовка" not in b["rules"]
    for m in industry_modules():
        assert m["data_sources"], m["id"]
        assert all(u["id"] in known for u in m["uses"])
        assert m["decisions"], m["id"]
        text = modules.claude_md(m)
        assert "AskUserQuestion" in text and "{{" not in text and "## Откуда данные" in text, m["id"]
        for s in m["schedule"]:
            assert "{{" not in s["prompt"]
    used = {u["id"] for m in industry_modules() for u in m["uses"]}
    assert used == set(known)                                         # каждый общий блок кто-то подключает


def test_ru_modules_require_russian_model_and_checked_dates():
    for m in industry_modules():
        if m["id"] in RU_ONLY:
            text = (Path(m["path"]) / "CLAUDE.md").read_text(encoding="utf-8")
            assert "RU-MODELS.md" in text and "152-ФЗ" in text and "GigaChat" in text, m["id"]
            assert "RU-MODELS.md" in m["description"]
    for mid in ("uk-requests", "uk-emergency"):
        text = (modules.builtin_dir() / mid / "CLAUDE.md").read_text(encoding="utf-8")
        assert "02.11.2026" in text and "КонсультантПлюс" in text and "№ 416" in text
    cal = (modules.builtin_dir() / "acc-deadlines" / "data" / "tax-calendar.csv").read_text(encoding="utf-8")
    assert cal.splitlines()[0].endswith(",сверено") and all(r.endswith(",2026-11-02") for r in cal.splitlines()[1:])


@pytest.mark.parametrize("mid", ONE_PER_INDUSTRY)
def test_create_workspace_copies_common_skills(mid, tmp_path):
    m = modules.get(mid)
    p = modules.create(mid, tmp_path / "projects")
    text = (p / "CLAUDE.md").read_text(encoding="utf-8")
    known = modules.blocks()
    for u in m["uses"]:
        assert f"## Общий блок: {known[u['id']]['title']}" in text
        for s in known[u["id"]]["skills"]:
            assert (p / ".claude" / "skills" / s / "SKILL.md").is_file()
    assert (p / "data").is_dir() and not (p / "module.toml").exists() and "{{" not in text
    assert modules.mark_of(p)["id"] == mid


def test_workdays_script_copied_and_runs(tmp_path):
    p = modules.create("uk-requests", tmp_path / "projects")
    assert (p / ".claude" / "skills" / "workdays" / "workdays.py").is_file()
    assert (p / ".claude" / "skills" / "workdays" / "calendar-ru.csv").is_file()


def test_example_data_is_fake():
    """Примеры данных обезличены: телефоны +7 900 000-00-xx, почта @example.com, ИНН и счета — нули."""
    phone = re.compile(r"\+7[\s(-]*\d[\d\s()-]{6,}\d")
    email = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
    digits = re.compile(r"(?<![\d-])\d{10,20}(?![\d-])")
    for f in modules.builtin_dir().rglob("*"):
        if not f.is_file() or f.suffix not in {".csv", ".md", ".txt", ".toml"}:
            continue
        text = f.read_text(encoding="utf-8")
        for x in phone.findall(text):
            assert re.fullmatch(r"\+7 900 000-00-\d\d", x.strip()), (f, x)
        for x in email.finditer(text):
            assert x.group(0).endswith(("@example.com", "@anthropic.com")), (f, x.group(0))
        for x in digits.findall(text):
            assert set(x) == {"0"}, (f, x)


def load_workdays():
    spec = importlib.util.spec_from_file_location("workdays", WORKDAYS / "workdays.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_workdays_calendar():
    w = load_workdays()
    cal = w.load([WORKDAYS / "calendar-ru.csv"])
    assert {2026, 2027} <= w.years(cal)
    assert not w.is_workday(date(2026, 11, 4), cal) and w.is_workday(date(2027, 2, 20), cal)   # праздник; суббота
    assert w.add(date(2026, 11, 2), 10, cal) == date(2026, 11, 17)         # 4 ноября не считается
    assert w.add(date(2026, 10, 28), 3, cal) == date(2026, 11, 2)
    assert w.add(date(2026, 12, 30), 1, cal) == date(2027, 1, 11)          # 31.12 и каникулы
    assert w.next_workday(date(2026, 11, 28), cal) == date(2026, 11, 30)
    assert w.left(date(2026, 11, 17), date(2026, 11, 2), cal) == 10
    assert w.left(date(2026, 11, 2), date(2026, 11, 2), cal) == 0
    assert w.left(date(2026, 10, 30), date(2026, 11, 2), cal) == -1
    with pytest.raises(w.NoCalendar, match="2030"):
        w.add(date(2030, 1, 1), 1, cal)


def test_tax_calendar_dates_are_workdays():
    w = load_workdays()
    cal = w.load([WORKDAYS / "calendar-ru.csv"])
    rows = (modules.builtin_dir() / "acc-deadlines" / "data" / "tax-calendar.csv").read_text().splitlines()[1:]
    for r in rows:
        assert w.is_workday(date.fromisoformat(r[:10]), cal), r            # ст. 6.1 НК РФ: перенос уже учтён


# ---------- расписание «каждые N минут» ----------
EVERY = 'title = "Т"\nindustry = "Пробная"\nabout = "x"\n'


def write(base: Path, mid: str, toml: str):
    d = base / mid
    d.mkdir(parents=True)
    (d / "module.toml").write_text(toml, encoding="utf-8")
    (d / "CLAUDE.md").write_text("# Роль\n", encoding="utf-8")


def test_every_schedule_parse_and_errors(tmp_path):
    base = tmp_path / "cfg" / "modules"
    write(base, "tick", EVERY + '[[schedule]]\nevery = 10\nat = "08:00"\nuntil = "20:00"\nprompt = "проверь"\n')
    write(base, "bad-every", EVERY + '[[schedule]]\nevery = 3\nprompt = "p"\n')
    write(base, "bad-until", EVERY + '[[schedule]]\nevery = 10\nuntil = "25:00"\nprompt = "p"\n')
    errors = []
    by = {m["id"]: m for m in modules.catalog(errors)}
    s = by["tick"]["schedule"][0]
    assert s["every"] == 10 and s["when"] == "каждые 10 мин, 08:00–20:00" and s["title"] == s["when"]
    assert "bad-every" not in by and "bad-until" not in by
    assert "от 5 до 240" in "\n".join(errors) and "25:00" in "\n".join(errors)
    em = by["uk-emergency"]["schedule"][0]
    assert em["every"] == 10 and em["when"] == "каждые 10 мин" and em["at"] == "00:00"


def test_every_schedule_due_once_per_slot(tmp_path):
    base = tmp_path / "cfg" / "modules"
    write(base, "tick", EVERY + '[[schedule]]\nevery = 10\nat = "08:00"\nuntil = "20:00"\nprompt = "проверь"\n')
    root = tmp_path / "projects"
    p = modules.create("tick", root)
    mark = json.loads((p / modules.MARK).read_text())
    mark["created"] = int(datetime(2026, 11, 1, 12, 0).timestamp())
    (p / modules.MARK).write_text(json.dumps(mark))
    sch = modules.Schedule(tmp_path / "modules.json")
    assert sch.due([root], datetime(2026, 11, 2, 7, 59)) == []                    # до окна
    assert len(sch.due([root], datetime(2026, 11, 2, 8, 0))) == 1
    assert sch.due([root], datetime(2026, 11, 2, 8, 9)) == []                     # тот же отрезок
    assert len(sch.due([root], datetime(2026, 11, 2, 8, 10))) == 1
    assert len(sch.due([root], datetime(2026, 11, 2, 9, 47))) == 1                # пропуски не догоняем — один раз
    assert sch.due([root], datetime(2026, 11, 2, 9, 49)) == []
    assert sch.due([root], datetime(2026, 11, 2, 20, 5)) == []                    # после окна
    assert len(sch.due([root], datetime(2026, 11, 3, 8, 1))) == 1                 # новый день
    q = modules.create("uk-emergency", root)                      # создано сейчас — ждём следующий отрезок
    now = datetime.now()
    assert all(f != q for f, _, _ in sch.due([root], now))


# ---------- бот ----------
@pytest.fixture
def pult(tmp_path, monkeypatch):
    p = bot.Pult(Config(token="1:T", owners=[1], project_roots=[str(tmp_path / "projects")]))
    p.sent = []
    p.send = lambda chat, text, **kw: p.sent.append((text, kw))
    p.broadcast = lambda text, **kw: p.sent.append((text, kw))
    p.api = lambda method, **kw: {}
    return p


def buttons(kw) -> list[tuple[str, str]]:
    return [(b["text"], b["callback_data"]) for row in kw["reply_markup"]["inline_keyboard"] for b in row]


def test_bot_modules_grouped_by_industry(pult):
    """/modules: «Общие» модули сразу, отрасли — кнопками; по нажатию — модули отрасли (два шага, до 4096 знаков)."""
    pult.show_modules(1)
    text, kw = pult.sent[-1]
    assert len(text) < 4096
    assert "▪️ Общие" in text and "Ночная смена" in text and "Заказ из мессенджера" not in text
    groups = {t[3:]: d for t, d in buttons(kw) if d.startswith("md:g:")}
    assert set(groups) == set(INDUSTRIES)
    for industry, ids in INDUSTRIES.items():
        assert f"▪️ {industry} — {len(ids)}" in pult.sent[0][0]
        pult.on_module(1, groups[industry][3:])
        text, kw = pult.sent[-1]
        assert len(text) < 4096 and text.startswith(f"🧩 {industry}")
        assert {d[5:] for _, d in buttons(kw) if d.startswith("md:v:")} == ids
        assert ("‹ Все отрасли", "md:list:") in buttons(kw)
    pult.on_module(1, "g:99")                                               # каталог поменялся — снова список
    assert "Отрасли:" in pult.sent[-1][0]


def test_bot_catalog_fits_telegram_with_twice_the_modules(pult, monkeypatch):
    real = modules.catalog()
    double = real + [m | {"id": m["id"] + "-x", "title": m["title"] + " (копия)"} for m in real]
    monkeypatch.setattr(modules, "catalog", lambda errors=None: sorted(
        double, key=lambda m: (m["industry"] != "Общие", m["industry"], m["title"])))
    pult.show_modules(1)
    texts = [pult.sent[-1][0]]
    for _, d in buttons(pult.sent[-1][1]):
        if d.startswith("md:g:"):
            pult.on_module(1, d[3:])
            texts.append(pult.sent[-1][0])
    assert len(texts) == len(INDUSTRIES) + 1 and all(len(t) < 4096 for t in texts)
    assert bot._clip("а\n" * 3000).endswith("\n…") and len(bot._clip("а\n" * 3000)) <= 4000


def test_bot_every_busy_window_is_quiet(pult, tmp_path):
    root = tmp_path / "projects"
    folder = modules.create("uk-emergency", root)
    mark = json.loads((folder / modules.MARK).read_text())
    mark["created"] = 0
    (folder / modules.MARK).write_text(json.dumps(mark))
    pult.project_window = lambda path: {"id": "@7"}

    def busy(w, text):
        raise bot.NotReady("окно занято вопросом")
    pult.to_claude = busy
    pult.module_tick(datetime(2026, 11, 2, 3, 0))
    assert pult.sent == []                                                       # «каждые 10 мин» — без шума владельцам
    text = pult.module_text(modules.get("uk-emergency"))
    assert "каждые 10 мин каждый день" in text
