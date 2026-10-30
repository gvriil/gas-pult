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


def test_own_models_override_defaults_and_empty_means_claude_names(cfgdir):
    providers.save_key("openrouter", "sk-or-v1-0123456789abcdef")
    st = {"model_profiles": models.set_models({}, "openrouter", "openrouter/auto", "")}
    models.command("claude", "openrouter", st)
    env = json.loads((cfgdir / "profiles" / "openrouter.json").read_text())["env"]
    assert env["ANTHROPIC_MODEL"] == "openrouter/auto" and "ANTHROPIC_DEFAULT_HAIKU_MODEL" not in env
    models.command("claude", "openrouter", {})                # по умолчанию — явные модели Claude, не «как повезёт»
    env = json.loads((cfgdir / "profiles" / "openrouter.json").read_text())["env"]
    assert env["ANTHROPIC_MODEL"] == "anthropic/claude-sonnet-5.5"
    assert env["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api"
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "anthropic/claude-haiku-5.5"
    st = {"model_profiles": models.set_models({}, "openrouter", "", "")}
    models.command("claude", "openrouter", st)              # пустые поля — модели Claude по их обычным именам
    env = json.loads((cfgdir / "profiles" / "openrouter.json").read_text())["env"]
    assert "ANTHROPIC_MODEL" not in env


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
