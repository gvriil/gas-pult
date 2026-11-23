"""Термины в анкете (TGI через штаб, 23.11): необязательное ``glossary`` {"термин": "пояснение"} — проверка формата,
поиск терминов на странице /q/ (чистые функции блока «gloss:start … gloss:end» в web/q.html — считает node) и
сценарий в браузере — tests/e2e/forms_glossary_demo.py (Playwright; нет браузера — пропуск)."""

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from test_onboarding import FORM
from test_people_login import server  # noqa: F401

from gas_pult import onboarding

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "src/gas_pult/web/q.html").read_text(encoding="utf-8")
SCRIPT = PAGE[PAGE.index("<script>"):]
BLOCK = SCRIPT[SCRIPT.index("// gloss:start"):SCRIPT.index("// gloss:end")]


def form(glossary) -> dict:
    f = json.loads(json.dumps(FORM))
    f["glossary"] = glossary
    return f


def test_check_accepts_glossary():
    assert onboarding.check(FORM) == []                                       # без glossary — как раньше
    assert onboarding.check(form({"ОС": "Основные средства — то, что служит больше года."})) == []
    assert onboarding.check(form({"т" * 60: "п" * 300})) == []
    assert onboarding.check(form({f"t{i}": "x" for i in range(100)})) == []


@pytest.mark.parametrize("g, part", [
    (["ОС"], "словарь"),
    ("ОС", "словарь"),
    ({"": "пояснение"}, "пустой термин"),
    ({"  ": "пояснение"}, "пустой термин"),
    ({"т" * 61: "пояснение"}, "от 1 до 60 знаков"),
    ({"ОС": ""}, "нет пояснения"),
    ({"ОС": 5}, "нет пояснения"),
    ({"ОС": "п" * 301}, "301 знаков, можно до 300"),
    ({f"t{i}": "x" for i in range(101)}, "терминов 101, можно не больше 100"),
    ({"Учёт": "а", "учет": "б"}, "повторяется"),
])
def test_check_rejects_bad_glossary(g, part):
    errs = onboarding.check(form(g))
    assert errs and any(part in e for e in errs), errs


def test_bad_glossary_form_not_loaded_and_public_keeps_glossary(tmp_path):
    (tmp_path / "forms").mkdir()
    (tmp_path / "forms" / "bad.json").write_text(json.dumps({**form({"ОС": ""}), "id": "bad"}, ensure_ascii=False))
    (tmp_path / "forms" / "ok.json").write_text(json.dumps({**form({"ОС": "x"}), "id": "ok"}, ensure_ascii=False))
    fs = onboarding.forms(tmp_path)
    assert "ok" in fs and "bad" not in fs
    assert onboarding.public(fs["ok"])["glossary"] == {"ОС": "x"}
    assert "glossary" not in onboarding.public(FORM)                         # без glossary — ответ как раньше


TERMS = {"1С": "a", "1С: Бухгалтерия": "b", "ОС": "c", "метки": "d", "Wi-Fi": "e", "учёт": "f", "<b>x</b>": "g"}
CASES = [
    # целым словом: не внутри другого слова (кириллица — буквы, как и латиница)
    ("ОС и основные", [{"s": "ОС"}, " и основные"]),
    ("ГОСТ и РОС", ["ГОСТ и РОС"]),
    ("пометки, метки.", ["пометки, ", {"s": "метки"}, "."]),
    ("меткии", ["меткии"]),
    ("1С2", ["1С2"]),
    # длинный раньше короткого, вложенных совпадений нет
    ("в 1С: Бухгалтерия и 1С", ["в ", {"s": "1С: Бухгалтерия"}, " и ", {"s": "1С"}]),
    # регистр и «ё»/«е» не важны; в тексте — как написано
    ("Метки МЕТКИ ос", [{"s": "Метки"}, " ", {"s": "МЕТКИ"}, " ", {"s": "ос"}]),
    ("Учет и учёт", [{"s": "Учет"}, " и ", {"s": "учёт"}]),
    ("Wi-Fi.", [{"s": "Wi-Fi"}, "."]),
    ("<b>x</b>!", [{"s": "<b>x</b>"}, "!"]),                                  # разметка — просто текст
    ("", []),
]


def test_parts_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("нет node")
    script = BLOCK + f"\nconst T = glossTerms({json.dumps(TERMS, ensure_ascii=False)});\n" + \
        f"const C = {json.dumps([c for c, _ in CASES], ensure_ascii=False)};\n" + \
        "console.log(JSON.stringify({order: T.map((x) => x.t), got: C.map((c) => glossParts(c, T)" + \
        ".map((p) => typeof p === 'string' ? p : {s: p.s, t: T[p.i].t}))}));\n" + \
        "console.log(JSON.stringify(glossParts('ОС', glossTerms(null))));"
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True, timeout=30).stdout
    first, second = out.splitlines()
    d = json.loads(first)
    assert d["order"].index("1С: Бухгалтерия") < d["order"].index("1С")
    for (text, want), got in zip(CASES, d["got"], strict=True):
        assert [p if isinstance(p, str) else {"s": p["s"]} for p in got] == want, text
        assert "".join(p if isinstance(p, str) else p["s"] for p in got) == text   # текст не теряется
    assert d["got"][0][0]["t"] == "ОС"
    assert json.loads(second) == ["ОС"]                                        # без glossary — текст как есть


def test_page_builds_text_safely():
    gl = SCRIPT[SCRIPT.index("const gl = "):SCRIPT.index("function glPlace(")]
    assert "esc(p)" in gl and "esc(p.s)" in gl                                 # кусок и термин — экранированы
    assert "h.textContent = x.t; p.textContent = x.d;" in gl and "innerHTML" not in gl   # пояснение — только текст
    assert 'role="tooltip"' in PAGE and 'aria-live="polite"' in PAGE
    for piece in ('aria-expanded="false"', 'aria-controls="gltip"', 'setAttribute("aria-describedby", "gltip")'):
        assert piece in gl, piece
    for field in ("gl(F.intro)", "gl(r)", "gl(q.text)", "gl(q.hint)", "gl(o)"):
        assert field in SCRIPT, field
    assert "e.stopPropagation()" in SCRIPT and "}, true);" in SCRIPT          # термин — до выбора варианта


def test_e2e_glossary_in_browser(server, tmp_path):  # noqa: F811
    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    spec = importlib.util.spec_from_file_location("gl_demo", ROOT / "tests" / "e2e" / "forms_glossary_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    panel, base = server
    mod.run(base + mod.link(panel, mod.DEMO))
