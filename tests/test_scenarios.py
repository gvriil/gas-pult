"""«Примерочная» («Примерить на себя»): схема toml, отрасли с ролями, кнопки как в модулях, калькулятор (Python и JS,
без eval), честные подписи, публичные данные без путей, API и права, документация и демо панели."""

import json
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from websrc import web_source

from gas_pult import modules, scenarios, webapp, webauth
from gas_pult.config import Config

ROLES = {"carwash-owner", "uk-director"}
# TODO(итерация 2): сценарии этих отраслей — следующим PR; тогда список опустеет.
LATER = {"Бухгалтеры и юристы на аутсорсе", "Поставщики HoReCa", "Селлеры WB и Ozon", "Фитнес-клубы (семейные)"}


@pytest.fixture(autouse=True)
def dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()


def page() -> str:
    return web_source()


# ---------- каталог и схема ----------
def test_builtin_scenarios_load():
    errors = []
    cat = scenarios.catalog(errors)
    assert errors == [] and {s["id"] for s in cat} >= ROLES
    for s in cat:
        assert 3 <= len(s["timeline_steps"]) <= 5 and s["who"] and s["without"] and s["needs"] and s["first_step"]
        assert "не обещание" in s["calculator"]["assumptions_disclaimer"]


def test_every_industry_has_scenario():
    """У каждой отрасли каталога — роль, кроме явного списка на итерацию 2. «Общие» — не отрасль."""
    industries = {m["industry"] for m in modules.catalog()} - {"Общие"}
    covered = {i for s in scenarios.catalog() for i in s["industries"]}
    assert industries - LATER <= covered, (industries - LATER) - covered
    assert not covered & LATER, "сценарий появился — уберите отрасль из LATER"
    assert industries >= LATER, "в LATER — отрасль, которой больше нет в каталоге"


def test_modules_exist_and_buttons_as_in_module():
    by = {m["id"]: m for m in modules.catalog()}
    for s in scenarios.catalog():
        assert all(m in by for m in s["modules"]), s["id"]
        for st in s["timeline_steps"]:
            assert st["module"] in by and st["module"] in s["modules"]
            labels = [d["label"] for d in st["decisions"]]
            opts = [d["options"] for d in by[st["module"]]["decisions"]] + [
                x["buttons"] for x in by[st["module"]]["demo"]["telegram"]]
            assert labels and labels in opts, (s["id"], st["at"], labels)
            assert all(d["outcome_toast"] for d in st["decisions"])


def test_nothing_impossible_for_agent():
    """Поправки владельца: без камер и SMS; Яндекс и 2ГИС — ответ публикует человек; рассылки — с согласием;
    деньги подписаны честно; подключение — «Подключить», без «за 2 мин»; цифры помечены как пример."""
    for s in scenarios.catalog():
        blob = json.dumps(scenarios.public(s), ensure_ascii=False).lower()
        assert "камер" not in blob and "смс" not in blob
        assert "за 2 мин" not in blob and "журнал и откат" not in blob
        assert all("пример" in st["text"] for st in s["timeline_steps"])
        for st in s["timeline_steps"]:
            for d in st["decisions"]:
                if "яндекс" in d["outcome_toast"].lower():
                    assert "опубликуйте в кабинете" in d["outcome_toast"]
            if "рассыл" in st["text"].lower() or "реклам" in st["text"].lower():
                assert "соглас" in st["text"]
    assert any(x["caption"] == "оборот, не прибыль" for x in scenarios.benefit("carwash-owner")["lines"])
    assert any("не доп. доход" in x["caption"] for x in scenarios.benefit("uk-director")["lines"])
    for s in scenarios.catalog():                                                   # доли — редактируемые допущения
        assert any(x["assumption"] and x["unit"] == "%" for x in s["calculator"]["inputs"])


GOOD = """title = "Тест"
short = "коротко"
who = "кто"
industries = ["Автомойки и шиномонтаж (сеть)"]
modules = ["carwash-return"]
without = "без"
needs = ["выгрузка"]
first_step = "шаг"
[[timeline_steps]]
at = "08:00"
module = "carwash-return"
text = "раз"
[[timeline_steps]]
at = "09:00"
module = "carwash-return"
text = "два"
[[timeline_steps]]
at = "10:00"
module = "carwash-return"
text = "три"
[[timeline_steps.decisions]]
label = "Оставить"
outcome_toast = "ок"
[[timeline_steps.decisions]]
label = "Особое предложение"
outcome_toast = "ок"
[[timeline_steps.decisions]]
label = "Позже"
outcome_toast = "ок"
[calculator]
assumptions_disclaimer = "Оценка, не обещание."
[[calculator.inputs]]
id = "n"
title = "Число"
default = 10
min = 1
max = 100
about = "допущение"
[[calculator.formulas]]
title = "Польза"
unit = "ч"
of = ["n"]
low = 0.1
high = 0.2
about = "почему"
"""


def write(base: Path, name: str, text: str) -> Path:
    p = base / name
    p.write_text(text, encoding="utf-8")
    return p


@pytest.mark.parametrize("old,new,err", [
    ('modules = ["carwash-return"]', 'modules = ["no-such"]', "нет таких модулей"),
    ('label = "Позже"', 'label = "Потом"', "не совпадают ни с одним решением"),
    ('low = 0.1\nhigh = 0.2', 'low = 0.3\nhigh = 0.2', "low ≤ high"),
    ('of = ["n"]', "of = [\"__import__('os').system('x')\"]", "нет таких вводных"),
    ('of = ["n"]', 'of = "n * 2"', "of — список"),
    ('at = "08:00"', 'at = "8 утра"', "ЧЧ:ММ"),
    ('industries = ["Автомойки и шиномонтаж (сеть)"]', 'industries = ["Селлеры WB и Ozon"]', "из другой отрасли"),
    ('title = "Тест"', 'title = "Тест"\nformula = "n*2"', "неизвестные ключи"),
    ('[[timeline_steps]]\nat = "08:00"\nmodule = "carwash-return"\ntext = "раз"\n', '', "от 3 до 5 шагов"),
    ('assumptions_disclaimer = "Оценка, не обещание."', 'assumptions_disclaimer = "Точно будет."', "не обещание"),
    ('at = "08:00"\nmodule = "carwash-return"\ntext = "раз"', 'at = "08:00"\ntext = "раз"\n'
     '[[timeline_steps.decisions]]\nlabel = "Да"\noutcome_toast = "x"', "только у шага с модулем"),
])
def test_schema_errors_are_clear(tmp_path, old, new, err):
    assert scenarios.parse(write(tmp_path, "ok-role.toml", GOOD))["id"] == "ok-role"
    assert old in GOOD
    with pytest.raises(scenarios.ScenarioError, match=re.escape(err)) as e:
        scenarios.parse(write(tmp_path, "bad-role.toml", GOOD.replace(old, new, 1)))
    assert "bad-role.toml" in str(e.value)


def test_user_scenario_overrides_and_broken_is_skipped(tmp_path):
    d = tmp_path / "cfg" / "scenarios"
    d.mkdir(parents=True)
    write(d, "uk-director.toml", GOOD.replace("Тест", "Своя УК"))
    write(d, "broken.toml", "title = ")
    errors = []
    by = {s["id"]: s for s in scenarios.catalog(errors)}
    assert by["uk-director"]["title"] == "Своя УК" and "broken" not in by and "broken.toml" in errors[0]


# ---------- калькулятор ----------
def test_benefit_range_monotone_and_clamped():
    for s in scenarios.catalog():
        base = scenarios.benefit(s)
        assert base["lines"] and "не обещание" in base["disclaimer"]
        for ln in base["lines"]:
            assert 0 <= ln["low"] < ln["high"] and ln["text"].endswith(ln["unit"])     # диапазон, не одно число
        for x in s["calculator"]["inputs"]:
            more = scenarios.benefit(s, {x["id"]: x["default"] * 2})
            for a, b in zip(base["lines"], more["lines"], strict=True):
                assert b["low"] >= a["low"] and b["high"] >= a["high"], (s["id"], x["id"])
            assert scenarios.benefit(s, {x["id"]: x["max"] * 10})["inputs"][x["id"]] == x["max"]
            assert scenarios.benefit(s, {x["id"]: -5})["inputs"][x["id"]] == x["min"]
            for junk in ("", "abc", None, True, float("nan"), "1+1", "__import__('os')"):
                assert scenarios.benefit(s, {x["id"]: junk})["inputs"][x["id"]] == x["default"]


def test_benefit_known_values():
    """Заранее посчитанные значения: поменялась формула — поменяйте и benefitCalc в index.html."""
    lines = scenarios.benefit("carwash-owner")["lines"]
    assert [(x["low"], x["high"]) for x in lines] == [(5, 7), (24, 36), (34000, 50000)]
    assert lines[2]["text"] == "34 000–50 000 ₽ в месяц"
    uk = scenarios.benefit("uk-director", {"debt": "1 000 000", "speed_share": "2,5"})
    assert uk["inputs"]["debt"] == 3000000 and uk["inputs"]["speed_share"] == 2.5          # «1 000 000» — не число
    assert [(x["low"], x["high"]) for x in uk["lines"]] == [(10, 14), (60000, 90000)]
    assert scenarios.fmt(1234567.25) == "1 234 567,3" and scenarios.fmt(0.5) == "0,5" and scenarios.fmt(12) == "12"


def js_block(text: str) -> str:
    m = re.search(r"/\* benefit:start.*?/\* benefit:end \*/", text, re.S)
    assert m, "в странице нет блока benefitCalc"
    return m.group(0)


def test_no_eval_anywhere():
    src = Path(scenarios.__file__).read_text(encoding="utf-8")
    assert not re.search(r"(?<![.\w])(eval|exec|compile)\(", src)
    assert not re.search(r"\beval\(|new Function|Function\(", js_block(page()))


CASES = [("carwash-owner", {}), ("carwash-owner", {"points": 7, "clients": "2350", "avg_check": "1250,5",
                                                    "return_share": "2,7", "minutes": 13}),
         ("uk-director", {"requests": 99999999, "late_share": "abc"}), ("uk-director", {"debt": 333333.33}),
         ("uk-director", {"requests": 0, "speed_share": 0.37})]


def test_js_matches_python():
    """Тот же расчёт в панели. Есть node — считает JS и сверяем с Python; нет — сверяем, что в JS те же операции,
    что в Python (округление, формат, ограничение границами), — без них числа разошлись бы."""
    block = js_block(page())
    for piece in ("Math.floor(v / r + 0.5) * r", "Math.floor(v * 10 + 0.5)", "Math.min(x.max, Math.max(x.min,",
                  "for (const k of l.of) base *= inp[k]", "rnd(base * l.low, l.round)", "rnd(base * l.high, l.round)"):
        assert piece in block, piece
    node = shutil.which("node")
    if not node:
        return
    data = [{"r": scenarios.public(scenarios.get(rid)), "v": v} for rid, v in CASES]
    script = block + "\nconst D = " + json.dumps(data, ensure_ascii=False) + ";\n" + \
        "console.log(JSON.stringify(D.map((x) => benefitCalc(x.r, x.v))));"
    run = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True, timeout=30)
    for (rid, v), js in zip(CASES, json.loads(run.stdout), strict=True):
        py = scenarios.benefit(rid, v)
        assert js["inputs"] == pytest.approx(py["inputs"])
        assert [(x["low"], x["high"], x["text"]) for x in js["lines"]] == \
            [(x["low"], x["high"], x["text"]) for x in py["lines"]], rid


# ---------- публичные данные, документация, демо панели ----------
def keys(x) -> set:
    if isinstance(x, dict):
        return set(x) | {k for v in x.values() for k in keys(v)}
    if isinstance(x, list):
        return {k for v in x for k in keys(v)}
    return set()


def test_public_has_no_paths():
    d = scenarios.api_data()
    blob = json.dumps(d, ensure_ascii=False)
    assert "path" not in keys(d)
    assert str(scenarios.builtin_dir()) not in blob and "/home" not in blob and "{{" not in blob
    s = next(x for x in d["scenarios"] if x["id"] == "carwash-owner")
    assert "«Центр»" in s["timeline_steps"][0]["text"] and s["timeline_steps"][0]["module_title"]


def test_docs_match_toml():
    doc = Path(__file__).resolve().parent.parent / "docs" / "SCENARIOS.md"
    assert doc.read_text(encoding="utf-8") == scenarios.markdown(), "пересоберите: python -m gas_pult.scenarios"


def test_demo_json_matches_toml():
    line = next(x for x in page().split("\n") if x.startswith(scenarios.DEMO_PREFIX))
    assert line == scenarios.demo_line(), "демо-данные панели устарели: python -m gas_pult.scenarios"


def test_panel_entries_and_sliders():
    p = page()
    assert "data-scn-home" in p and "data-scn-entry" in p and "data-scn-ind" in p    # главная, «Из модуля», отрасль
    assert 'params.get("view") === "scenarios"' in p
    assert 'type="range"' in p and "data-scn-range" in p                                   # калькулятор — ползунки
    assert "Подключить за" not in p


# ---------- API ----------
@pytest.fixture
def server():
    panel = webapp.Panel(Config(token="1:T", owners=[1], region="NL"))
    panel.people.add(2, "member")
    panel.people.add(3, "viewer")
    for uid in (1, 2, 3):
        panel.people.accept(uid)
        panel.people.set_country(uid, chosen="NL")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield panel, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def call(base, path, token="", body=None):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={token}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def test_api_scenarios_rights(server, tmp_path):
    panel, base = server
    owner, member, viewer = (panel.auth.issue(u) for u in (1, 2, 3))
    assert call(base, "/api/scenarios")[0] == 401                                  # без входа — нет
    for tok in (owner, member, viewer):                                            # смотреть может и наблюдатель
        code, d = call(base, "/api/scenarios", tok)
        assert code == 200 and {s["id"] for s in d["scenarios"]} >= ROLES and d["errors"] == []
    (tmp_path / "cfg" / "scenarios").mkdir(parents=True)
    write(tmp_path / "cfg" / "scenarios", "broken.toml", "title = ")
    assert call(base, "/api/scenarios", owner)[1]["errors"]                        # ошибки — только владельцу
    assert call(base, "/api/scenarios", viewer)[1]["errors"] == []
