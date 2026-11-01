"""Запасные поставщики: распознавание отказа, выбор с учётом региона и ключей, защита от петли, переключение, API.

Образцы ошибок выдуманы по формату транскриптов Claude Code; ни сети, ни tmux, ни настоящего claude."""

import json
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import fallback, models


@pytest.mark.parametrize("text, kind", [
    ('API Error: 401 {"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}}', "auth"),
    ("Invalid API key · Please run /login", "auth"),
    ("Credit balance is too low", "auth"),
    ("Your account is on hold and can't use Claude Code.", "auth"),
    ('API Error: 429 {"error":{"type":"rate_limit_error","message":"Number of request tokens exceeded"}}', "rate"),
    ("Claude AI usage limit reached|1767225600", "rate"),
    ('API Error: 529 {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}', "server"),
    ("API Error: 502 Bad Gateway", "server"),
    ("API Error: 500 Internal server error", "server"),
    ("API Error: 503 Service Unavailable", "server"),
    ("API Error: Request timed out.", "timeout"),
    ("API Error: Connection error. (ECONNREFUSED)", "timeout"),
    ("fetch failed: getaddrinfo ENOTFOUND api.example.com", "timeout"),
    ("API Error: 504 Gateway Timeout", "timeout"),
    ("Готово, тесты зелёные", None),
    ("ошибка 401 в логах сайта — разберу", None),          # голое число — не отказ поставщика
])
def test_classify_error(text, kind):
    assert fallback.classify_error(text) == kind


def entry(text, status=None, error=None, ts=None, **kw):
    ts = ts or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {"type": "assistant", "isApiErrorMessage": True, "error": error, "apiErrorStatus": status,
            "timestamp": ts, "message": {"model": "<synthetic>", "role": "assistant", "stop_reason": "stop_sequence",
                                         "content": [{"type": "text", "text": text}]}, **kw}


def test_classify_entry_only_api_errors_of_main_session():
    assert fallback.classify_entry(entry("API Error: 429 rate_limit", 429, "rate_limit")) == ("rate", 429)
    assert fallback.classify_entry(entry("Your account is on hold", None, "account_on_hold")) == ("auth", None)
    assert fallback.classify_entry(entry("There's an issue with the selected model", 404, "invalid_request")) is None
    assert fallback.classify_entry(entry("API Error: 529", 529, isSidechain=True)) is None
    plain = {"type": "assistant", "message": {"content": [{"type": "text", "text": "API Error: 401 — так выглядит"}]}}
    assert fallback.classify_entry(plain) is None       # текст разговора про ошибку — не ошибка


def test_regions():
    assert not models.allowed("claude", "RU") and not models.allowed("openrouter", "ru")
    assert models.allowed("claude", "NL") and models.allowed("claude", "")
    assert not models.allowed("zai", "RU") and models.allowed("zai", "NL")
    assert not models.allowed("nope", "NL")


def test_chain_and_next_ok():
    c = fallback.Chain(["openrouter", "claude", "openrouter", "bogus", "zai"])
    assert c == ["openrouter", "claude", "zai"]
    assert c.after("claude") == ["zai", "openrouter"] and c.after("deepseek") == c
    assert fallback.next_ok(c, "openrouter") == "claude"
    assert fallback.next_ok(c, "openrouter", lambda p: p != "claude") == "zai"
    assert fallback.next_ok(c, "openrouter", tried={"claude", "zai"}) is None
    assert fallback.chain_of({}) == ["claude"] and fallback.chain_of({"fallback_chain": []}) == []


def test_validate_refuses_region_forbidden():
    assert fallback.validate(["openrouter", "claude", "claude"], "NL") == ["openrouter", "claude"]
    with pytest.raises(ValueError, match="региона RU"):
        fallback.validate(["claude"], "RU")
    with pytest.raises(ValueError, match="нет такого"):
        fallback.validate(["x"], "NL")


class FakeTmux:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def respawn(self, wid, path, cmd, mark="claude"):
        if self.fail:
            raise RuntimeError("tmux respawn-window не сработал")
        self.calls.append((wid, path, cmd, mark))


@pytest.fixture
def sw(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path))
    from gas_pult import providers
    providers.save_key("openrouter", "k1")
    providers.save_key("deepseek", "k2")
    state = {"fallback_chain": ["deepseek", "claude"]}
    said, logged, now = [], [], [datetime.now(UTC).timestamp()]
    s = fallback.Switcher(FakeTmux(), lambda: state, "claude", "NL", say=said.append, log=logged.append,
                          clock=lambda: now[0])
    s.st, s.said, s.logged, s.now = state, said, logged, now
    return s


W = {"id": "@1", "name": "shop", "path": "/p/shop", "profile": "openrouter"}


def test_switch_respawns_with_continue_and_says_one_line(sw):
    sw.seen("@1", entry("API Error: 429 rate_limit", 429, "rate_limit"))
    assert sw.step(W, idle=False) is None and sw.tmux.calls == []       # идёт ответ / человек набирает — ждём
    line = sw.step(W, idle=True)
    assert line == "Поставщик OpenRouter не отвечает (429) — сессия «shop» переключена на DeepSeek"
    wid, path, cmd, mark = sw.tmux.calls[0]
    assert (wid, path, mark) == ("@1", "/p/shop", "deepseek")
    assert cmd.startswith("claude --settings ") and cmd.endswith("deepseek.json --continue") and "k2" not in cmd
    assert sw.said == [line] and sw.logged[0]["from"] == "openrouter" and sw.logged[0]["to"] == "deepseek"


def test_normal_turn_after_error_cancels(sw):
    sw.seen("@1", entry("API Error: Request timed out."))
    sw.seen("@1", {"type": "assistant", "message": {"content": [{"type": "text", "text": "ок"}]}})
    assert sw.step(W, idle=True) is None and sw.tmux.calls == []


def test_stale_error_ignored(sw):
    sw.seen("@1", entry("API Error: 529", 529, ts="2020-01-01T00:00:00Z"))
    assert "@1" not in sw.pending


def test_no_loop_cooldown_and_no_return_to_failed(sw):
    sw.seen("@1", entry("API Error: 529", 529))
    sw.step(W, idle=True)                                             # openrouter → deepseek
    on_ds = {**W, "profile": "deepseek"}
    sw.now[0] += 10
    sw.seen("@1", entry("API Error: 401 authentication_error", 401,
                        ts=datetime.fromtimestamp(sw.now[0], UTC).isoformat()))
    assert sw.step(on_ds, idle=True) is None and len(sw.tmux.calls) == 1   # только что переключали — ждём
    sw.now[0] += sw.COOLDOWN
    assert sw.step(on_ds, idle=True).endswith("переключена на Claude")   # deepseek → claude, не назад на openrouter
    assert sw.tmux.calls[-1][2:] == ("claude --continue", "claude")
    sw.now[0] += sw.COOLDOWN + 1
    sw.seen("@1", entry("API Error: 529", 529, ts=datetime.fromtimestamp(sw.now[0], UTC).isoformat()))
    line = sw.step({**W, "profile": "claude"}, idle=True)
    assert "запасных нет" in line and len(sw.tmux.calls) == 2


def test_region_forbidden_fallback_is_not_used(sw):
    sw.region = "RU"
    sw.st["fallback_chain"] = ["claude"]
    sw.seen("@1", entry("API Error: 429", 429))
    line = sw.step({**W, "profile": "zai"}, idle=True)
    assert sw.tmux.calls == [] and "запасных нет (Claude — не для региона RU)" in line


def test_missing_key_skipped(sw):
    sw.st["fallback_chain"] = ["zai", "claude"]                       # ключа Z.ai нет
    sw.seen("@1", entry("API Error: 503", 503))
    assert sw.step(W, idle=True).endswith("переключена на Claude")


def test_respawn_failure_reported(sw):
    sw.tmux.fail = True
    sw.seen("@1", entry("API Error: 503", 503))
    assert "не вышло" in sw.step(W, idle=True)


def test_typing_detection():
    assert fallback.typing(["─────", "❯ пишу ответ", "─────"])
    assert not fallback.typing(["─────", "❯ ", "─────"])
    assert not fallback.typing(["❯ run the tests"], hint="run the tests")       # бледная подсказка — не ввод
    assert not fallback.typing(["❯ 1. Yes", "  2. No"])                         # меню, не ввод


def test_api_fallback_owner_only(monkeypatch, tmp_path):
    from gas_pult import webapp, webauth
    from gas_pult.config import Config
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    panel = webapp.Panel(Config(token="1:T", owners=[1], region="NL"))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/api/fallback"

    def call(body=None, uid=1):
        hdr = {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={panel.auth.issue(uid)}"}
        req = urllib.request.Request(base, json.dumps(body).encode() if body is not None else None, hdr)
        with urllib.request.urlopen(req) as r:
            return json.load(r)

    try:
        d = call()
        assert d["chain"] == ["claude"] and d["region"] == "NL" and d["voice"]["tts"][0] == "ElevenLabs"
        assert {o["id"]: o["why"] for o in d["options"]}["openrouter"] == "нет ключа"
        assert call({"chain": ["deepseek", "claude"]})["chain"] == ["deepseek", "claude"]
        assert panel.pult.state()["fallback_chain"] == ["deepseek", "claude"]
        with pytest.raises(urllib.error.HTTPError) as e:
            call({"chain": ["nope"]})
        assert e.value.code == 400
        panel.people.add(2, "member")
        with pytest.raises(urllib.error.HTTPError) as e:
            call(uid=2)
        assert e.value.code == 403
    finally:
        srv.shutdown()


def test_bot_wiring_one_line_to_owners_and_log_for_panel(monkeypatch, tmp_path):
    from gas_pult import bot
    from gas_pult.config import Config
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    p = bot.Pult(Config(token="1:T", owners=[1, 2], region="NL"))
    sent, spawned = [], []
    monkeypatch.setattr(p, "send", lambda chat, text, **kw: sent.append((chat, text)) or {})
    monkeypatch.setattr(p.tmux, "respawn", lambda wid, path, cmd, mark="claude": spawned.append((cmd, mark)))
    p.fallback.seen("@1", entry("API Error: 529 overloaded_error", 529))
    p.fallback.step({"id": "@1", "name": "x", "path": "/p/x", "profile": "zai"}, idle=True)
    assert spawned == [("claude --continue", "claude")]
    assert [c for c, _ in sent] == [1, 2] and sent[0][1].endswith("сессия «x» переключена на Claude")
    assert fallback.recent(p.state())[0]["w"] == "@1"
