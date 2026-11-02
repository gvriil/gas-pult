"""Сценарии «Примерить на себя»: схема toml, покрытие отраслей, кнопки как в модулях, расчёт пользы (Python и JS),
публичные данные без путей, API и права, блок на странице предложения, /scenarios в боте и демо предложения."""

import json
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from importlib import resources
from pathlib import Path

import pytest

from gas_pult import bot, modules, offers, scenarios, webapp, webauth
from gas_pult.config import Config

ROLES = {"carwash-owner", "carwash-branch", "fitness-manager", "fitness-director", "uk-director", "uk-dispatcher",
         "horeca-supplier", "seller", "accountant", "developer"}


@pytest.fixture(autouse=True)
def dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()


def page(name: str) -> str:
    return resources.files("gas_pult").joinpath(f"web/{name}").read_text(encoding="utf-8")


# ---------- каталог и схема ----------
def test_builtin_scenarios_load():
    errors = []
    cat = scenarios.catalog(errors)
    assert errors == [] and ROLES <= {s["id"] for s in cat}
    for s in cat:
        assert 3 <= len(s["moments"]) <= 5 and s["who"] and s["without"] and s["needs"] and s["first_step"]


def test_every_industry_has_scenario():
    """У каждой отрасли каталога модулей есть роль. «Общие» — не отрасль, а общие модули (у них — роль разработчика)."""
    industries = {m["industry"] for m in modules.catalog()} - {"Общие"}
    covered = {i for s in scenarios.catalog() for i in s["industries"]}
    assert industries <= covered, industries - covered


def test_modules_exist_and_buttons_as_in_module():
    by = {m["id"]: m for m in modules.catalog()}
    for s in scenarios.catalog():
        assert all(m in by for m in s["modules"]), s["id"]
        for mo in s["moments"]:
            if mo["module"]:
                assert mo["module"] in by and mo["module"] in s["modules"]
                labels = [b["label"] for b in mo["buttons"]]
                opts = [d["options"] for d in by[mo["module"]]["decisions"]] + [
                    x["buttons"] for x in by[mo["module"]]["demo"]["telegram"]]
                assert not labels or labels in opts, (s["id"], mo["at"], labels)
                assert all(b["result"] for b in mo["buttons"])
            else:
                assert mo["buttons"] == []


GOOD = """title = "Тест"
short = "коротко"
who = "кто"
industries = ["Автомойки и шиномонтаж (сеть)"]
modules = ["carwash-return"]
without = "без"
needs = ["выгрузка"]
first_step = "шаг"
[[moments]]
at = "08:00"
text = "раз"
[[moments]]
at = "09:00"
text = "два"
[[moments]]
at = "10:00"
module = "carwash-return"
text = "три"
[[moments.buttons]]
label = "Оставить"
result = "ок"
[[moments.buttons]]
label = "Особое предложение"
result = "ок"
[[moments.buttons]]
label = "Позже"
result = "ок"
[[inputs]]
id = "n"
title = "Число"
default = 10
min = 1
max = 100
about = "допущение"
[[benefit]]
title = "Польза"
unit = "ч"
of = ["n"]
low = 0.1
high = 0.2
about = "почему"
"""


def write(tmp_path, name, text) -> Path:
    p = tmp_path / name
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
    ('[[moments]]\nat = "08:00"\ntext = "раз"\n', '', "от 3 до 5 моментов"),
    ('at = "08:00"\ntext = "раз"', 'at = "08:00"\ntext = "раз"\n[[moments.buttons]]\nlabel = "Да"\nresult = "x"',
     "только у момента с модулем"),
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
    write(d, "seller.toml", GOOD.replace("Тест", "Свой селлер"))
    write(d, "broken.toml", "title = ")
    errors = []
    by = {s["id"]: s for s in scenarios.catalog(errors)}
    assert by["seller"]["title"] == "Свой селлер" and "broken" not in by and "broken.toml" in errors[0]


# ---------- польза ----------
def test_benefit_range_monotone_and_clamped():
    for s in scenarios.catalog():
        base = scenarios.benefit(s)
        assert base["lines"] and "не обещание" in base["note"]
        for ln in base["lines"]:
            assert 0 <= ln["low"] <= ln["high"] and ln["text"].endswith(ln["unit"])
        for x in s["inputs"]:
            for v in (x["min"], x["default"], x["max"]):
                assert x["min"] <= scenarios.benefit(s, {x["id"]: v})["inputs"][x["id"]] <= x["max"]
            more = scenarios.benefit(s, {x["id"]: x["default"] * 2})
            for a, b in zip(base["lines"], more["lines"], strict=True):
                assert b["low"] >= a["low"] and b["high"] >= a["high"], (s["id"], x["id"])
            assert scenarios.benefit(s, {x["id"]: x["max"] * 10})["inputs"][x["id"]] == x["max"]
            assert scenarios.benefit(s, {x["id"]: -5})["inputs"][x["id"]] == x["min"]
            for junk in ("", "abc", None, True, float("nan"), "1+1", "__import__('os')"):
                assert scenarios.benefit(s, {x["id"]: junk})["inputs"][x["id"]] == x["default"]


def test_benefit_known_values():
    """Заранее посчитанные значения: если формула поменялась — тест скажет, что поменять и в JS."""
    lines = scenarios.benefit("carwash-owner")["lines"]
    assert [(x["low"], x["high"]) for x in lines] == [(4.5, 9), (15, 45), (21000, 63000), (1.5, 3)]
    assert lines[2]["text"] == "21 000–63 000 ₽ в месяц" and lines[0]["text"] == "4,5–9 ч в неделю"
    got = scenarios.benefit("carwash-owner", {"points": "7", "clients": "2 000", "avg_check": "1250,5"})
    assert got["inputs"] == {"points": 7.0, "clients": 1500, "avg_check": 1250.5}        # «2 000» — не число
    assert scenarios.fmt(1234567.25) == "1 234 567,3" and scenarios.fmt(0.5) == "0,5" and scenarios.fmt(12) == "12"


def test_no_eval_anywhere():
    src = Path(scenarios.__file__).read_text(encoding="utf-8")
    assert not re.search(r"(?<![.\w])(eval|exec|compile)\(", src)
    for name in ("index.html", "offer.html"):
        block = js_block(page(name))
        assert not re.search(r"\beval\(|new Function|Function\(", block)


def js_block(text: str) -> str:
    m = re.search(r"/\* benefit:start.*?/\* benefit:end \*/", text, re.S)
    assert m, "в странице нет блока benefitCalc"
    return m.group(0)


CASES = [("carwash-owner", {}), ("carwash-owner", {"points": 7, "clients": "2350", "avg_check": "1250,5"}),
         ("fitness-manager", {"members": 99999999, "leads": "abc"}), ("seller", {"daily_revenue": 333333.33}),
         ("accountant", {"clients": 3, "docs": 17, "rate": 999}), ("uk-director", {"houses": 0})]


def test_js_matches_python():
    """Тот же расчёт в панели и на странице предложения: блоки одинаковые, а node (если есть) считает как Python."""
    assert js_block(page("index.html")) == js_block(page("offer.html"))
    node = shutil.which("node")
    if not node:
        pytest.skip("нет node — сверка JS только по тексту блока")
    data = [{"r": scenarios.public(scenarios.get(rid)), "v": v} for rid, v in CASES]
    script = js_block(page("index.html")) + "\nconst D = " + json.dumps(data, ensure_ascii=False) + ";\n" + \
        "console.log(JSON.stringify(D.map((x) => benefitCalc(x.r, x.v))));"
    out = json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True, timeout=30).stdout)
    for (rid, v), js in zip(CASES, out, strict=True):
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


def test_public_has_no_paths_or_internal():
    d = scenarios.api_data()
    blob = json.dumps(d, ensure_ascii=False)
    assert not {"path", "offer"} & keys(d)
    assert str(scenarios.builtin_dir()) not in blob and "/home" not in blob and "{{" not in blob
    s = next(x for x in d["scenarios"] if x["id"] == "carwash-owner")
    assert s["demo"]["point"] in s["moments"][0]["text"] and s["modules"][0]["title"]


def test_docs_match_toml():
    doc = Path(__file__).resolve().parent.parent / "docs" / "SCENARIOS.md"
    if not doc.is_file():
        pytest.skip("нет docs/ (пакет без репозитория)")
    assert doc.read_text(encoding="utf-8") == scenarios.markdown(), "пересоберите: python -m gas_pult.scenarios"
    for s in scenarios.catalog():
        assert f"### {s['title']}" in doc.read_text(encoding="utf-8")


def test_demo_json_matches_toml():
    line = next(x for x in page("index.html").split("\n") if x.startswith(scenarios.DEMO_PREFIX))
    assert line == scenarios.demo_line(), "демо-данные панели устарели: python -m gas_pult.scenarios"


def test_help_snippets():
    one = scenarios.help_snippets("seller")
    assert len(one) == 1 and "Селлер" in one[0] and "не обещание" in one[0] and "₽ в месяц" in one[0]
    ind = scenarios.help_snippets(industry="Управляющие компании — «УК-старт»")
    assert len(ind) == 2 and len(scenarios.help_snippets()) == len(scenarios.catalog())
    assert not any("{{" in x or "/home" in x or "path" in x for x in scenarios.help_snippets())


# ---------- панель ----------
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


def test_api_scenarios_rights(server):
    panel, base = server
    owner, member, viewer = (panel.auth.issue(u) for u in (1, 2, 3))
    assert call(base, "/api/scenarios")[0] == 401                                  # без входа — нет
    for tok in (owner, member, viewer):                                            # смотреть может и наблюдатель
        code, d = call(base, "/api/scenarios", tok)
        assert code == 200 and ROLES <= {s["id"] for s in d["scenarios"]} and d["errors"] == []
    assert call(base, "/api/scenarios", viewer, {})[0] in (403, 404)               # POST — нет такого действия


# ---------- страница предложения ----------
def make(text=None) -> str:
    return offers.create(text or offers.example_text())[0]


def test_offer_block_uses_offer_numbers_and_hides_internal(server):
    _, base = server
    code = make()
    st, d = call(base, f"/api/offer/{code}")
    s = d["scenario"]
    assert st == 200 and s["id"] == "carwash-owner"
    assert s["demo"] == {"business": "Автомойка «Пример»", "point": "Север"}
    ins = {x["id"]: x["default"] for x in s["inputs"]}
    assert ins == {"points": 3, "clients": 1500, "avg_check": 1400}                 # из [demo] предложения
    assert "Автомойка «Пример»" in s["moments"][0]["text"] and "«Север»" in s["moments"][0]["text"]
    blob = json.dumps(d, ensure_ascii=False)
    assert not {"path", "offer"} & keys(s) and code not in blob and "/home" not in blob and "{{" not in blob
    big = make(offers.example_text().replace("avg_check = 1400", "avg_check = 2100")
               .replace('points = ["Север", "Центр", "Юг"]', 'points = ["А", "Б", "В", "Г", "Д"]'))
    s2 = call(base, f"/api/offer/{big}")[1]["scenario"]
    assert {x["id"]: x["default"] for x in s2["inputs"]}["points"] == 5
    assert s2["benefit_default"][2]["low"] == 32000                                 # 1500 × 2100 × 1 %, по 1000
    other = make(offers.example_text().replace('industry = "carwash"', 'industry = "services"'))
    assert call(base, f"/api/offer/{other}")[1]["scenario"] is None                # нет роли — нет блока


def test_offer_role_by_industry_and_modules():
    o = {**offers.parse({"business": "УК Тест", "industry": "uk", "pains": ["x"], "modules": ["uk-emergency"]},
                        check_modules=False), "code": "c"}
    assert scenarios.for_offer(o)["id"] == "uk-dispatcher"                         # больше общих модулей
    o["modules"] = ["uk-debts"]
    assert scenarios.for_offer(o)["id"] == "uk-director"


# ---------- бот ----------
@pytest.fixture
def pult(tmp_path):
    p = bot.Pult(Config(token="1:T", owners=[1], project_roots=[str(tmp_path / "projects")]))
    p.calls = []

    def api(method, **kw):
        p.calls.append((method, kw))
        return {"message_id": 5} if method == "sendMessage" else {}
    p.api = api

    class NoTmux:
        def __getattr__(self, name):
            raise AssertionError(f"tmux.{name} в сценарии — нельзя")
    p.tmux = NoTmux()
    for uid in (1, 2):
        p.people.accept(uid)
        p.people.set_country(uid, chosen="NL")
    return p


def cbs(markup) -> list[str]:
    return [b["callback_data"] for row in markup["inline_keyboard"] for b in row if "callback_data" in b]


def press(p, uid, data, mid=5):
    p.calls.clear()
    p.handle({"update_id": 1, "callback_query": {"id": "q", "from": {"id": uid},
                                                 "message": {"chat": {"id": uid}, "message_id": mid}, "data": data}})
    return [(m, kw) for m, kw in p.calls if m in ("sendMessage", "editMessageText")]


def test_bot_scenarios_one_message_edited_in_place(pult):
    p = pult
    p.handle({"update_id": 1, "message": {"chat": {"id": 1}, "from": {"id": 1}, "text": "/scenarios"}})
    sent = [kw for m, kw in p.calls if m == "sendMessage"]
    assert len(sent) == 1 and "Примерить на себя" in sent[0]["text"]
    first = cbs(sent[0]["reply_markup"])
    assert {f"sc:{r}:0" for r in ROLES} <= set(first)
    for rid in sorted(ROLES):
        s = scenarios.public(scenarios.get(rid))
        page, seen = f"sc:{rid}:0", 0
        while True:
            out = press(p, 1, page)
            assert [m for m, _ in out] == ["editMessageText"]                       # только правка того же сообщения
            kw = out[0][1]
            assert kw["message_id"] == 5 and kw["chat_id"] == 1 and len(kw["text"]) <= 4096
            datas = cbs(kw["reply_markup"])
            assert all(len(d.encode()) <= 64 for d in datas), datas
            pressable = [d for d in datas if d.count(":") == 3]
            for d in pressable:                                                     # кнопки-решения — последствие
                kw2 = press(p, 1, d)[0][1]
                mo = s["moments"][int(d.split(":")[2]) - 1]
                assert "↪️" in kw2["text"] and mo["buttons"][int(d.split(":")[3])]["result"] in kw2["text"]
            nxt = [d for d in datas if d.startswith(f"sc:{rid}:") and d.count(":") == 2
                   and int(d.split(":")[2]) == int(page.split(":")[2]) + 1]
            if not nxt:
                break
            page, seen = nxt[0], seen + 1
        assert seen == len(s["moments"]) + 1                                       # вступление → моменты → итог
        assert "не обещание" in kw["text"] and "Первый шаг" in kw["text"]
        assert {f"md:v:{m['id']}" for m in s["modules"]} <= set(datas) and "sc:list" in datas
    assert press(p, 1, "sc:no-such:3")[0][0] == "editMessageText"                  # роли нет — список ролей


def test_bot_scenarios_owner_only(pult):
    p = pult
    p.people.add(2, "member")
    p.people.accept(2)
    p.people.set_country(2, chosen="NL")
    assert not p.admitted({"update_id": 1, "message": {"chat": {"id": 9}, "from": {"id": 9}, "text": "/scenarios"}})
    assert not p.admitted({"update_id": 1, "callback_query": {"id": "q", "from": {"id": 9}, "data": "sc:seller:1"}})
    assert press(p, 2, "sc:seller:1") == []                                         # участнику кнопки бота — нет


def test_offer_demo_in_telegram_shows_scenario_isolated(pult, tmp_path):
    p = pult
    code = make()
    tok = p.offer_tg.issue(code, "carwash-return", "https://pult.example/offer/" + code)
    stranger = {"id": 777, "first_name": "Гость"}
    start = {"update_id": 1, "message": {"chat": {"id": 777}, "from": stranger, "text": f"/start demo_{tok}"}}
    assert p.admitted(start)
    p.handle(start)
    step = 0
    while True:                                                                   # демо модуля до конца
        out = press(p, 777, f"dm:{tok}:{step}:n")
        last = out[-1][1]
        if f"dm:{tok}:f:c" in cbs(last["reply_markup"]):
            break
        step += 1
        assert step < 6
    assert f"dm:{tok}:s0:" in cbs(last["reply_markup"])
    page = f"dm:{tok}:s0:"
    for _ in range(10):
        upd = {"update_id": 2, "callback_query": {"id": "q", "from": stranger,
                                                  "message": {"chat": {"id": 777}, "message_id": 9}, "data": page}}
        assert p.admitted(upd)
        out = press(p, 777, page, mid=9)
        assert [m for m, _ in out] == ["editMessageText"] and out[0][1]["message_id"] == 9
        datas = cbs(out[0][1]["reply_markup"])
        assert all(len(d.encode()) <= 64 and d.startswith(f"dm:{tok}:") for d in datas)
        assert not any(d.startswith(("sc:", "md:")) for d in datas)                # ни ролей, ни модулей пульта
        nxt = [d for d in datas if re.fullmatch(rf"dm:{re.escape(tok)}:s\d+:", d)
               and int(d.split(":")[2][1:]) > int(page.split(":")[2][1:])]
        if not nxt:
            break
        page = nxt[0]
    text = out[0][1]["text"]
    assert "Автомойка «Пример»" in text or "не обещание" in text
    assert f"dm:{tok}:f:c" in datas and p.people.role(777) is None
    for upd in ({"text": "/scenarios"}, {"text": "/modules"}, {"text": "/start"}):
        assert not p.admitted({"update_id": 3, "message": {"chat": {"id": 777}, "from": stranger, **upd}})
    assert not p.admitted({"update_id": 4, "callback_query": {"id": "q", "from": stranger, "data": "sc:seller:0"}})
    offers.revoke(code)
    out = press(p, 777, f"dm:{tok}:s1:", mid=9)
    assert out[-1][1]["text"] == bot.DEMO_GONE
