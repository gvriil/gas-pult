"""Российские модели (GigaChat, YandexGPT) — профили через шлюз клиента; страны — только RU. Без сети и без tmux."""

import json
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import fallback, models, providers

RU = ("gigachat", "yandexgpt")
OTHERS = ("claude", "openrouter", "zai", "deepseek")
GW = "https://gw.example.test:8090"


@pytest.fixture
def cfgdir(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path))
    return tmp_path


def test_ru_gets_only_ru_profiles():
    for cs in ("RU", {"RU"}, "ru"):
        assert {p["id"] for p in models.PROFILES if models.allowed(p["id"], cs)} == set(RU)
    for p in OTHERS:                                     # Claude, OpenRouter, GLM, DeepSeek для России — как были
        assert not models.allowed(p, "RU")


@pytest.mark.parametrize("cs", ["NL", "DE", "KZ", "US/CA", "BY", {"RU", "NL"}, {"RU", "KZ"}, ""])
def test_ru_profiles_only_for_russia(cs):
    for p in RU:                       # RU и ещё страна (номер +7, сервер в NL) — каждая должна быть разрешена: нет
        assert not models.allowed(p, cs)


def test_nl_unchanged():
    assert models.allowed("claude", "NL") and models.allowed("zai", "NL") and models.allowed("deepseek", "NL")


def test_profile_without_gateway_is_clear_error_not_country(cfgdir):
    providers.save_key("gigachat", "gw-secret-key-0123456789")
    with pytest.raises(ValueError, match="не задан адрес шлюза GigaChat") as e:
        models.command("claude", "gigachat", {})
    assert models.DENY not in str(e.value) and "RU-MODELS.md" in str(e.value)
    assert not models.has_gateway("gigachat", {}) and models.has_gateway("zai", {})


def test_gateway_without_key(cfgdir):
    st = {"model_profiles": models.set_models({}, "yandexgpt", "", "", GW)}
    with pytest.raises(ValueError, match="нет ключа"):
        models.command("claude", "yandexgpt", st)


def test_command_uses_client_gateway(cfgdir):
    providers.save_key("gigachat", "gw-secret-key-0123456789")
    st = {"model_profiles": models.set_models({}, "gigachat", "", "", GW + "/")}
    cmd = models.command("claude", "gigachat", st)
    f = cfgdir / "profiles" / "gigachat.json"
    assert cmd == f"claude --settings {f}" and "gw-secret" not in cmd and GW not in cmd
    env = json.loads(f.read_text())["env"]
    assert env["ANTHROPIC_BASE_URL"] == GW                        # слэш в конце убран
    assert env["ANTHROPIC_AUTH_TOKEN"] == "gw-secret-key-0123456789" and env["ANTHROPIC_API_KEY"] == ""
    assert env["ANTHROPIC_MODEL"] == "GigaChat-2-Max" and env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "GigaChat-2-Lite"
    assert env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"     # из сессии — только в шлюз


def test_no_builtin_gateway_address():
    for p in RU:
        assert not models.BY_ID[p].get("base_url") and models.BY_ID[p]["gateway"]
        assert models.BY_ID[p]["regions"] == {"RU"}


@pytest.mark.parametrize("bad", ["ftp://gw", "https://user:pass@gw.test", "https://gw.test/?key=1", "https://gw test",
                                 "javascript:alert(1)", "https://" + "a" * 250])
def test_gateway_url_validated(bad):
    with pytest.raises(ValueError, match="адрес шлюза"):
        models.set_models({}, "gigachat", "", "", bad)


def test_set_models_keeps_gateway_and_clears_on_empty():
    st = {"model_profiles": models.set_models({}, "gigachat", "", "", GW)}
    st = {"model_profiles": models.set_models(st, "gigachat", "GigaChat-2-Pro", "")}      # None — адрес не трогаем
    assert st["model_profiles"]["gigachat"] == {"main": "GigaChat-2-Pro", "fast": "", "base_url": GW}
    st = {"model_profiles": models.set_models(st, "gigachat", "", "", "")}
    assert "base_url" not in st["model_profiles"]["gigachat"]
    with pytest.raises(ValueError, match="только у поставщиков через шлюз"):
        models.set_models({}, "zai", "", "", GW)                  # у остальных адрес свой и не меняется


def test_public_fields_added(cfgdir):
    pub = {p["id"]: p for p in models.public({}, "RU")}
    g = pub["gigachat"]
    assert g["gateway"] and g["base_url"] == "" and "не задан адрес шлюза" in g["not_ready"] and g["regions"] == ["RU"]
    assert g["allowed"] and not pub["claude"]["allowed"] and pub["claude"]["denied"] == models.DENY
    assert pub["zai"]["gateway"] is False and pub["zai"]["not_ready"] == ""          # старые — как были


# ---------- запасные: для России — только разрешённые для России ----------
class FakeTmux:
    def __init__(self):
        self.calls = []

    def respawn(self, wid, path, cmd, mark="claude"):
        self.calls.append((wid, path, cmd, mark))


def err(code=529):
    return {"type": "assistant", "isApiErrorMessage": True, "apiErrorStatus": code,
            "timestamp": datetime.now(UTC).isoformat(),
            "message": {"content": [{"type": "text", "text": f"API Error: {code}"}]}}


@pytest.fixture
def sw(cfgdir):
    for k in ("openrouter", "deepseek", "zai", "gigachat", "yandexgpt"):
        providers.save_key(k, f"{k}-key-0123456789abcdef")
    state = {"fallback_chain": ["claude", "openrouter", "deepseek", "zai", "yandexgpt"],
             "model_profiles": models.set_models({}, "yandexgpt", "", "", GW)}
    said = []
    s = fallback.Switcher(FakeTmux(), lambda: state, "claude", "RU", say=said.append)
    s.st, s.said = state, said
    return s


def test_fallback_for_ru_never_goes_to_claude_or_others(sw):
    w = {"id": "@1", "name": "shop", "path": "/p/shop", "profile": "gigachat"}
    sw.seen("@1", err())
    line = sw.step(w, idle=True)
    assert line.endswith("переключена на YandexGPT (через шлюз)")
    assert [c[3] for c in sw.tmux.calls] == ["yandexgpt"]


def test_fallback_ru_without_gateway_skipped(sw):
    sw.st["model_profiles"] = {}
    w = {"id": "@1", "name": "shop", "path": "/p/shop", "profile": "gigachat"}
    sw.seen("@1", err())
    line = sw.step(w, idle=True)
    assert sw.tmux.calls == [] and "запасных нет" in line and "нет адреса шлюза" in line
    assert "Claude — не для страны RU" in line


def test_default_chain_for_ru_is_empty_choice():
    assert fallback.next_ok(fallback.chain_of({}), "gigachat", lambda p: models.allowed(p, "RU")) is None
    with pytest.raises(ValueError, match=models.DENY):
        fallback.validate(["gigachat", "claude"], "RU")
    assert fallback.validate(["gigachat", "yandexgpt"], "RU") == ["gigachat", "yandexgpt"]
    with pytest.raises(ValueError, match=models.DENY):
        fallback.validate(["gigachat"], "NL")


# ---------- панель ----------
@pytest.fixture
def panel_srv(monkeypatch, tmp_path):
    from gas_pult import webapp, webauth
    from gas_pult.config import Config
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    panel = webapp.Panel(Config(token="1:T", owners=[1], region="RU"))
    panel.people.accept(1)
    panel.people.set_country(1, chosen="RU")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(path, body=None):
        hdr = {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={panel.auth.issue(1)}"}
        req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None, hdr)
        with urllib.request.urlopen(req) as r:
            return json.load(r)

    yield panel, call
    srv.shutdown()


def test_panel_ru_owner_sees_only_ru_and_sets_gateway(panel_srv, monkeypatch):
    panel, call = panel_srv
    pub = {p["id"]: p for p in call("/api/meta")["profiles"]}
    assert {k for k, p in pub.items() if p["allowed"]} == set(RU)
    d = call("/api/models", {"profile": "gigachat", "main": "", "fast": "", "base_url": GW})
    assert {p["id"]: p for p in d["profiles"]}["gigachat"]["base_url"] == GW
    assert panel.pult.state()["model_profiles"]["gigachat"]["base_url"] == GW
    call("/api/keys", {"provider": "gigachat", "key": "gw-secret-key-0123456789"})
    assert "gw-secret" not in json.dumps(call("/api/meta"))
    monkeypatch.setattr(panel.pult, "projects", lambda: ["/tmp"])
    monkeypatch.setattr(panel, "need_claude", lambda: None)
    monkeypatch.setattr(panel.tmux, "windows", lambda: [])
    got = []
    monkeypatch.setattr(panel.tmux, "new_window", lambda name, path, cmd, **kw: got.append(cmd) or "@9")
    monkeypatch.setattr(panel, "mark_by", lambda *a: None)
    assert call("/api/new", {"i": 0, "profile": "gigachat"})["id"] == "@9"
    assert got[0].split(" --session-id ")[0].endswith("profiles/gigachat.json")   # свой журнал окна (задача 49)
    with pytest.raises(urllib.error.HTTPError) as e:              # Claude для России — отказ по стране, как было
        call("/api/new", {"i": 0, "profile": "claude"})
    assert e.value.code in (400, 403) and models.DENY in json.load(e.value)["error"]


def test_panel_ru_without_gateway_clear_message(panel_srv, monkeypatch):
    panel, call = panel_srv
    providers.save_key("yandexgpt", "gw-secret-key-0123456789")
    monkeypatch.setattr(panel.pult, "projects", lambda: ["/tmp"])
    monkeypatch.setattr(panel, "need_claude", lambda: None)
    monkeypatch.setattr(panel.tmux, "windows", lambda: [])
    monkeypatch.setattr(panel.tmux, "new_window", lambda *a, **kw: pytest.fail("окно открывать нельзя"))
    with pytest.raises(urllib.error.HTTPError) as e:
        call("/api/new", {"i": 0, "profile": "yandexgpt"})
    msg = json.load(e.value)["error"]
    assert e.value.code == 400 and "не задан адрес шлюза YandexGPT" in msg and models.DENY not in msg
