"""Простой режим панели: словари ru/en, белый список латиницы, настройки человека на сервере, /api/prefs и /api/ask,
язык ответов агента для новых пространств, полный режим без флага — прежний.

Видимый текст на экране проверяет Playwright (tests/e2e/simple_mode.py: ?demo&simple=1 и &lang=en, 390/820/1366,
светлая и тёмная тема). Здесь — то же правило статически: словари, демо-переписка и разбор демо-экранов; строки
интерфейса простого режима берутся только из словаря (T("…")), их ключи есть в обоих словарях."""

import importlib.util
import json
import re
import shutil
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

import pytest

from gas_pult import humanize, modules, webapp, webauth
from gas_pult.config import Config
from gas_pult.people import People

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "gas_pult" / "web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
RU = json.loads((WEB / "i18n" / "ru.json").read_text(encoding="utf-8"))
EN = json.loads((WEB / "i18n" / "en.json").read_text(encoding="utf-8"))
E2E = ROOT / "tests" / "e2e" / "simple_mode.py"


def e2e():
    spec = importlib.util.spec_from_file_location("simple_mode", E2E)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()


# ---------- словари ----------
def test_dictionaries_have_same_keys_and_no_empty():
    assert RU.keys() == EN.keys()
    assert all(isinstance(v, str) and v.strip() for v in [*RU.values(), *EN.values()])
    for k in RU:                                              # подстановки {n} — одинаковые в обоих языках
        assert set(re.findall(r"\{\w+\}", RU[k])) == set(re.findall(r"\{\w+\}", EN[k])), k


def test_no_foreign_letters_in_dictionaries():
    s = e2e().strangers
    bare = lambda v: re.sub(r"\{\w+\}", "", v)            # noqa: E731 — подстановки {n} на экран не попадают
    for k, v in RU.items():
        assert not s(bare(v), "ru"), (k, v)                   # в русском — латиница только из белого списка
    for k, v in EN.items():
        assert not s(bare(v), "en"), (k, v)                   # в английском — ни одной кириллической буквы
    assert s("Откройте Settings", "ru") == ["Settings"] and s("Open Настройки", "en") == ["Настройки"]
    assert not s("Отзывы WB и Ozon в Telegram", "ru") and not s("Русский", "en")


def test_whitelist_is_one_place():
    assert "Claude" in humanize.LATIN_OK and "Ozon" in humanize.LATIN_OK and "English" in humanize.LATIN_OK
    assert humanize.CYRILLIC_OK == ("Русский",)
    assert "LATIN_OK" in E2E.read_text(encoding="utf-8")      # Playwright-проверка берёт его же


def test_humanize_keys_exist_in_both_dictionaries():
    keys = {f"ask.{k}.{x}" for k, _, _ in humanize.DIALOGS for x in ("title", "detail")}
    keys |= {f"ask.{k}.{x}" for k in ("question", "continue", "unknown") for x in ("title", "detail")}
    keys |= {f"opt.{k}.{x}" for k, _, _ in humanize.OPTIONS for x in ("label", "note")}
    keys |= {f"opt.{k}.label" for k in ("yes-other", "allow", "deny", "details", "continue")} | {"opt.yes-other.note"}
    keys |= {f"err.{k}" for k, _ in humanize.ERRORS}
    keys |= {f"status.{k}" for k in {*humanize.TOOLS.values(), "service", "works", *humanize.PHASES} - {"working"}}
    assert keys <= RU.keys(), keys - RU.keys()


def test_panel_uses_only_known_keys():
    used = set(re.findall(r"\bT\(\"([a-z0-9.\-_]+)\"", INDEX)) | set(re.findall(r"\bLL?\(\"([a-z0-9.\-_]+)\"", INDEX))
    used |= set(re.findall(r'data-l="([a-z0-9.\-_]+)"', INDEX))
    used = {k for k in used if not k.endswith(".")}           # T("status." + …) — ключ собирается из частей
    assert used and used <= RU.keys(), used - RU.keys()
    for prefix in ("status.", "s.status.", "set.lang.", "set.theme."):   # ключи, собранные в коде из частей
        assert any(k.startswith(prefix) for k in RU)


def test_simple_screen_has_no_hardcoded_text():
    html = INDEX[INDEX.index('<div id="simple" hidden>'):INDEX.index("<script", INDEX.index('<div id="simple"'))]
    body = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    assert not re.sub(r"<[^>]+>", "", body).strip()           # все строки — из словаря при запуске
    js = INDEX[INDEX.index("// ---------- простой режим"):INDEX.index("function simpleDemoText")]
    js = re.sub(r"^const SIMPLE_DEMO = [^\n]*$", "", js, flags=re.M)        # разбор демо-экранов — свой тест
    js = re.sub(r"//[^\n]*|/\*.*?\*/", "", js, flags=re.S)
    js = re.sub(r"\bL{1,2}\(\"[^\"]+\", \"[^\"]+\"\)", "", js)       # запасные русские строки полного режима
    js = re.sub(r'toast\(on \? "[^"]+"', "", js)                      # ошибка включения — из полного режима
    js = js.replace('"Русский"', "").replace('"English"', "")       # запасные подписи переключателя
    assert not re.search(r"[А-Яа-яЁё]", js), re.search(r".{40}[А-Яа-яЁё].{40}", js)


def test_tool_map_same_in_panel_and_server():
    m = re.search(r"^const SIMPLE_TOOL = (\{.*\});$", INDEX, re.M)
    assert json.loads(m.group(1)) == humanize.TOOLS
    ph = re.search(r"^const SIMPLE_PH = (\[.*\]);$", INDEX, re.M)
    assert tuple(json.loads(ph.group(1))) == humanize.PHASES


def test_demo_questions_in_sync_and_human():
    m = re.search(r"^const SIMPLE_DEMO = (\{.*\});$", INDEX, re.M)
    assert m and m.group(1) == humanize.demo_json(), "словарь изменился — обновите: python -m gas_pult.humanize"
    demo = json.loads(m.group(1))
    s = e2e().strangers
    for kind in ("bash", "edit", "unknown"):
        a = demo[kind]
        ru = " ".join([a["title_ru"], a["detail_ru"], *(o["label_ru"] + " " + o["note_ru"] for o in a["options"])])
        en = " ".join([a["title_en"], a["detail_en"], *(o["label_en"] + " " + o["note_en"] for o in a["options"])])
        assert not s(ru, "ru") and not s(en, "en"), kind


def test_demo_conversation_has_no_foreign_letters():
    js = INDEX[INDEX.index("function simpleDemoText"):INDEX.index("function simpleDemoHist")]
    en, ru = re.findall(r"\? \{(.*?)\}\s*: \{(.*?)\};", js, re.S)[0]
    s = e2e().strangers
    ru, en = (x.replace("\\n", " ") for x in (ru, en))      # переводы строк в строках JS
    assert not s(re.sub(r"\b(ask|reply|ask2|answer):", "", ru), "ru") and not s(en, "en")


def test_full_mode_untouched_without_flag():
    # простой режим запускается только по настройке человека — иначе прежний start() полного режима
    assert INDEX.count("return simpleStart()") == 1
    assert "if (simplePrefs(meta).simple) return simpleStart();" in INDEX
    assert re.search(r'body\.simple-on #scroller', INDEX)    # полный экран прячется только классом простого
    assert People(Path("/nonexistent/people.json"), [1]).prefs(1) == {"simple": False, "lang": "ru", "saved": False}


# ---------- настройки человека ----------
def test_prefs_per_person(tmp_path):
    p = People(tmp_path / "people.json", [1])
    assert p.prefs(1) == {"simple": False, "lang": "ru", "saved": False}
    assert p.set_prefs(1, simple=True) == {"simple": True, "lang": "ru", "saved": True}
    assert (tmp_path / "prefs.json").stat().st_mode & 0o777 == 0o600               # владелец — рядом, 0600
    p.add(2, "member", "Иван")
    p.set_prefs(2, lang="en")
    assert p.prefs(2) == {"simple": False, "lang": "en", "saved": True} and p.prefs(1)["simple"] is True
    assert json.loads((tmp_path / "people.json").read_text())["2"]["prefs"]["lang"] == "en"
    p.add(2, "viewer", "Иван")                                # смена роли настройки не сбрасывает
    assert p.prefs(2)["lang"] == "en"
    with pytest.raises(ValueError):
        p.set_prefs(2, lang="de")
    p.remove(2)
    assert p.prefs(2)["saved"] is False


# ---------- сервер: /api/prefs, /api/ask, словари, ошибки в переписке ----------
@pytest.fixture
def server(monkeypatch):
    panel = webapp.Panel(Config(token="1:T", owners=[1], region="NL"))
    panel.people.add(2, "member", "Иван")
    panel.people.add(3, "viewer", "Анна")
    for uid in (1, 2, 3):
        panel.people.accept(uid)
        panel.people.set_country(uid, chosen="NL")
    screen = {"lines": humanize.DEMO_SCREENS["bash"]}
    monkeypatch.setattr(panel, "window", lambda wid: {"id": wid, "name": "x", "path": "/tmp/x", "profile": "claude"}
                        if wid == "@1" else None)
    monkeypatch.setattr(panel.tmux, "screen", lambda wid, n=40: screen["lines"])
    monkeypatch.setattr(panel.tmux, "window", lambda wid: None)       # окна нет — без настоящего tmux (macOS в CI)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield panel, f"http://127.0.0.1:{srv.server_address[1]}", screen
    srv.shutdown()


def call(base, path, body=None, token=""):
    h = {"Cookie": f"{webauth.COOKIE}={token}" if token else ""}
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None, h)
    try:
        r = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        r = e
    return (r.status if hasattr(r, "status") else r.code), json.loads(r.read() or b"{}")


def test_prefs_api(server):
    panel, base, _ = server
    owner, member, viewer = panel.auth.issue(1), panel.auth.issue(2), panel.auth.issue(3)
    st, d = call(base, "/api/meta", token=member)
    assert st == 200 and d["prefs"] == {"simple": False, "lang": "ru", "saved": False}   # по умолчанию — как раньше
    assert call(base, "/api/prefs", {"simple": True, "lang": "en"}, member) == (
        200, {"simple": True, "lang": "en", "saved": True})
    assert call(base, "/api/prefs", {"simple": True}, viewer)[0] == 200                     # и наблюдателю — своё
    assert call(base, "/api/meta", token=owner)[1]["prefs"]["simple"] is False             # у каждого своё
    assert call(base, "/api/prefs", token=member)[1]["lang"] == "en"
    assert call(base, "/api/prefs", {"lang": "de"}, member)[0] == 400
    assert call(base, "/api/prefs", {"lang": "en"})[0] == 401                                # без входа — нет


def test_dictionaries_served_without_login(server):
    _, base, _ = server
    for lang, d in (("ru", RU), ("en", EN)):
        assert call(base, f"/i18n/{lang}.json") == (200, d)
    assert call(base, "/i18n/de.json")[0] == 404
    assert resources.files("gas_pult").joinpath("web/i18n/ru.json").is_file()


def test_ask_api(server):
    panel, base, screen = server
    viewer = panel.auth.issue(3)
    st, d = call(base, "/api/ask?w=@1", token=viewer)
    assert st == 200 and d["ask"]["kind"] == "bash" and d["ask"]["options"][0]["send"] == {"n": "1"}
    screen["lines"] = ["● Готово", "", "❯ "]
    assert call(base, "/api/ask?w=@1", token=viewer) == (200, {"ask": None})
    assert call(base, "/api/ask?w=@9", token=viewer)[0] == 404


def test_history_errors_humanized(server, monkeypatch):
    panel, base, _ = server
    items = [{"i": 1, "role": "user", "text": "Привет", "ts": "t"},
             {"i": 2, "role": "assistant", "text": "API Error: 529 Overloaded", "ts": "t"},
             {"i": 3, "role": "assistant", "text": "Готово", "ts": "t"}]
    monkeypatch.setattr(webapp.transcripts, "history", lambda *a, **k: ([dict(x) for x in items], False))
    monkeypatch.setattr(webapp.transcripts, "revision", lambda *a, **k: "r1")
    st, d = call(base, "/api/history?w=@1", token=panel.auth.issue(2))
    assert st == 200 and d["items"][1]["human"]["key"] == "overloaded" and "human" not in d["items"][2]
    assert d["items"][1]["text"] == items[1]["text"]                            # исходный текст — как был


# ---------- язык ответов агента: настройка Claude Code language в новом пространстве ----------
def test_module_space_language(tmp_path):
    mid = modules.catalog()[0]["id"]
    ru = modules.create(mid, tmp_path, "space-ru", lang="ru")
    assert json.loads((ru / ".claude" / "settings.json").read_text())["language"] == "russian"
    en = modules.create(mid, tmp_path, "space-en", lang="en")
    st = json.loads((en / ".claude" / "settings.json").read_text())
    assert st["language"] == "english"
    src = Path(modules.get(mid)["path"]) / "settings.json"
    if src.is_file():                                         # настройки модуля сохраняются, язык — добавкой
        assert {k: v for k, v in st.items() if k != "language"} == json.loads(src.read_text())
    plain = modules.create(mid, tmp_path, "space-x")
    assert "language" not in json.loads((plain / ".claude" / "settings.json").read_text() or "{}") \
        if (plain / ".claude" / "settings.json").is_file() else True
    shutil.rmtree(tmp_path, ignore_errors=True)


# ---------- видимый текст в браузере (если Playwright есть) ----------
def test_e2e_visible_text_in_browser():
    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        e2e().run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
