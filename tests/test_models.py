import json

import pytest

from gas_pult import models, providers


@pytest.fixture
def cfgdir(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path))
    return tmp_path


def test_claude_profile_starts_as_before(cfgdir):
    assert models.command("claude", "claude", {}) == "claude"
    assert models.command("claude --foo", "", {}) == "claude --foo"


def test_profile_needs_key(cfgdir):
    with pytest.raises(ValueError, match="нет ключа"):
        models.command("claude", "zai", {})
    with pytest.raises(ValueError):
        models.command("claude", "nope", {})


def test_profile_settings_file_has_key_and_models(cfgdir):
    providers.save_key("zai", "zai-secret-key-123456")
    cmd = models.command("claude", "zai", {})
    f = cfgdir / "profiles" / "zai.json"
    assert cmd == f"claude --settings {f}" and "zai-secret-key" not in cmd       # ключа нет в командной строке
    assert f.stat().st_mode & 0o777 == 0o600
    env = json.loads(f.read_text())["env"]
    assert env["ANTHROPIC_BASE_URL"] == "https://api.z.ai/api/anthropic"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "zai-secret-key-123456" and env["ANTHROPIC_API_KEY"] == ""
    assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == env["ANTHROPIC_MODEL"] == "glm-5.3[1m]"
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "glm-5.3-flash[1m]"


def test_own_models_override_defaults_and_empty_means_provider_default(cfgdir):
    providers.save_key("openrouter", "sk-or-v1-0123456789abcdef")
    st = {"model_profiles": models.set_models({}, "openrouter", "openrouter/auto", "")}
    models.command("claude", "openrouter", st)
    env = json.loads((cfgdir / "profiles" / "openrouter.json").read_text())["env"]
    assert env["ANTHROPIC_MODEL"] == "openrouter/auto"
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "anthropic/claude-haiku-5.5"   # быстрая пустая — по умолчанию
    assert env["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api"

def test_set_models_validates(cfgdir):
    with pytest.raises(ValueError):
        models.set_models({}, "zai", "glm; rm -rf /", "")
    with pytest.raises(ValueError):
        models.set_models({}, "claude", "x", "")


def test_profile_of_reads_process_args():
    assert models.profile_of(["claude", "--settings", "/home/u/.config/gas-pult/profiles/deepseek.json"]) == "deepseek"
    assert models.profile_of(["claude"]) == "claude"
    assert models.profile_of(["claude", "--settings", "/tmp/profiles/evil.json"]) == "claude"


def test_public_hides_keys(cfgdir):
    providers.save_key("deepseek", "sk-deepseek-secret-abcdef")
    pub = {p["id"]: p for p in models.public({})}
    assert "secret" not in json.dumps(pub)
    assert pub["deepseek"]["key"]["tail"] == "…cdef" and pub["claude"]["needs_key"] is False


def test_full_role_mapping_for_third_party(cfgdir):
    providers.save_key("zai", "zai-secret-key-123456")
    models.command("claude", "zai", {})
    env = json.loads((cfgdir / "profiles" / "zai.json").read_text())["env"]
    main, fast = "glm-5.3[1m]", "glm-5.3-flash[1m]"          # [1m] у Z.ai — по их документации
    roles = ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL")
    assert [env[k] for k in roles] == [main] * 3
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == env["CLAUDE_CODE_SUBAGENT_MODEL"] == fast


def test_long_context_suffix_only_where_supported(cfgdir):
    st = {"model_profiles": models.set_models({}, "openrouter", "anthropic/claude-opus-5.5[1m]", "")}
    assert models.models_of(models.BY_ID["openrouter"], st)[0] == "anthropic/claude-opus-5.5"
    assert models.models_of(models.BY_ID["deepseek"], {})[0] == "deepseek-v4-pro[1m]"


def test_private_files_are_0600_and_atomic(cfgdir):
    secrets = cfgdir / "secrets.json"
    secrets.write_text("{}")
    secrets.chmod(0o644)                                       # остался «как попало» — станет 0600
    providers.save_key("deepseek", "sk-deepseek-secret-abcdef")
    models.command("claude", "deepseek", {})
    for f in (secrets, cfgdir / "profiles" / "deepseek.json"):
        assert f.stat().st_mode & 0o777 == 0o600
    assert not [p for p in cfgdir.rglob("*.tmp")]               # временных файлов не осталось


def test_restart_without_key_is_refused_before_touching_window(cfgdir, monkeypatch, tmp_path):
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    from gas_pult import webapp, webauth
    from gas_pult.config import Config
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    panel = webapp.Panel(Config(token="1:T", owners=[1]))
    touched = []
    monkeypatch.setattr(panel, "window", lambda wid: {"id": wid, "name": "w", "path": "/tmp"})
    monkeypatch.setattr(panel, "close", lambda w: touched.append("close") or "закрыто")
    monkeypatch.setattr(panel.tmux, "new_window", lambda *a, **kw: touched.append("new") or "@9")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    token = panel.auth.issue(1)
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/api/restart",
                                     json.dumps({"w": "@1", "profile": "zai"}).encode(),
                                     {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={token}"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        assert e.value.code == 400 and "нет ключа" in json.load(e.value)["error"]
        assert touched == []                                  # окно не закрывали и не открывали
    finally:
        srv.shutdown()


def test_keys_never_leak_to_api_state_or_argv(cfgdir, monkeypatch, tmp_path):
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    from gas_pult import webapp, webauth
    from gas_pult.config import Config
    secret = "sk-or-v1-TOPSECRET-0123456789"
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    providers.save_key("openrouter", secret)
    panel = webapp.Panel(Config(token="1:T", owners=[1]))
    monkeypatch.setattr(panel.tmux, "windows", lambda: [])
    cmd = models.command("claude", "openrouter", panel.pult.state())
    panel.set_models("openrouter", "anthropic/claude-sonnet-5.5", "")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    token, base = panel.auth.issue(1), f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        for path in ("/api/meta", "/api/providers", "/api/sessions", "/api/people"):
            req = urllib.request.Request(base + path, headers={"Cookie": f"{webauth.COOKIE}={token}"})
            body = urllib.request.urlopen(req).read().decode()
            assert secret not in body and "TOPSECRET" not in body, path
    finally:
        srv.shutdown()
    assert secret not in cmd                                       # не в командной строке
    assert secret not in (tmp_path / "data" / "state.json").read_text()   # не в state.json
