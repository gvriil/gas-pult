import pytest

from gas_pult import config


@pytest.fixture(autouse=True)
def dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("GAS_PULT_TOKEN", raising=False)
    return tmp_path


def test_save_and_load_roundtrip():
    path = config.save([42], "123:ABC", session="work", commands=[["▶️ Старт", "/start"]])
    assert (path.parent / "token").stat().st_mode & 0o777 == 0o600
    cfg = config.load()
    assert cfg.owners == [42] and cfg.token == "123:ABC" and cfg.session == "work"
    assert cfg.commands == [["▶️ Старт", "/start"]]


def test_save_keeps_existing_keys():
    config.save([1], "t", host="box")
    config.save([2])
    cfg = config.load()
    assert cfg.owners == [2] and cfg.host == "box"


def test_env_token_wins(monkeypatch):
    config.save([1], "file-token")
    monkeypatch.setenv("GAS_PULT_TOKEN", "env-token")
    assert config.load().token == "env-token"


@pytest.mark.parametrize("body, msg", [
    ("", "owners"),
    ('owners = [1]\ncolour = "red"\n', "Неизвестные"),
    ('owners = [1]\ntask_pattern = "("\n', "регулярное"),
])
def test_bad_config(dirs, body, msg):
    d = dirs / "cfg"
    d.mkdir()
    (d / "config.toml").write_text(body)
    (d / "token").write_text("t")
    with pytest.raises(config.ConfigError, match=msg):
        config.load()


def test_missing_config():
    with pytest.raises(config.ConfigError, match="init"):
        config.load()
