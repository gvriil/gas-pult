import threading
import time
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import openrouter as orr
from gas_pult import webapp
from gas_pult.config import Config


def test_start_link_has_pkce_and_state():
    o = orr.OpenRouter()
    url = o.start("https://pult.example.com:8443/")
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    assert url.startswith(orr.AUTH + "?") and q["callback_url"] == "https://pult.example.com:8443/openrouter/callback"
    assert q["code_challenge_method"] == "S256" and q["key_label"] == "gas-pult"
    verifier, _ = o.pending[q["state"]]
    assert q["code_challenge"] == orr.challenge(verifier) and "=" not in q["code_challenge"]


def test_finish_exchanges_code_once(monkeypatch):
    o, sent = orr.OpenRouter(), []
    monkeypatch.setattr(orr, "_http",
                        lambda url, body=None, key=None: sent.append((url, body)) or {"key": "sk-or-v1-x"})
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(o.start("https://p")).query))["state"]
    assert o.finish("CODE", state) == "sk-or-v1-x"
    assert sent[0][0] == orr.EXCHANGE and sent[0][1]["code"] == "CODE" and sent[0][1]["code_verifier"]
    with pytest.raises(ValueError, match="устарела"):
        o.finish("CODE", state)                               # state одноразовый


def test_finish_rejects_unknown_and_expired(monkeypatch):
    o = orr.OpenRouter()
    with pytest.raises(ValueError):
        o.finish("CODE", "guess")
    o.pending["old"] = ("v", time.time() - orr.TTL - 1)
    with pytest.raises(ValueError, match="устарела"):
        o.finish("CODE", "old")


def test_models_catalog(monkeypatch):
    data = {"data": [{"id": "anthropic/claude-sonnet-5.5", "name": "Claude Sonnet 5.5", "context_length": 1000000,
                      "pricing": {"prompt": "0.000003", "completion": "0.000015"}},
                     {"id": "anthropic/claude-sonnet-5.5:batch", "name": "batch"}]}
    monkeypatch.setattr(orr, "_http", lambda url, body=None, key=None: data)
    assert orr.OpenRouter().models() == [{"id": "anthropic/claude-sonnet-5.5", "name": "Claude Sonnet 5.5",
                                          "ctx": 1000000, "in": 3.0, "out": 15.0}]


def test_callback_page_works_without_login_and_saves_key(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    panel = webapp.Panel(Config(token="1:T", owners=[1]))
    saved = {}
    monkeypatch.setattr(webapp.providers, "save_key", lambda p, k: saved.__setitem__(p, k))
    monkeypatch.setattr(orr, "_http", lambda url, body=None, key=None: {"key": "sk-or-v1-from-oauth"})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        bad = urllib.request.urlopen(base + "/openrouter/callback?code=X&state=<script>").read().decode()
        assert "Не получилось" in bad and "<script>" not in bad and saved == {}
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(panel.openrouter.start(base)).query))["state"]
        ok = urllib.request.urlopen(base + f"/openrouter/callback?code=X&state={state}").read().decode()
        assert "сохранён" in ok and saved == {"openrouter": "sk-or-v1-from-oauth"} and "sk-or" not in ok
        with pytest.raises(urllib.error.HTTPError):           # остальной API без входа закрыт
            urllib.request.urlopen(base + "/api/openrouter/info")
    finally:
        srv.shutdown()
