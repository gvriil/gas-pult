import io
import json
import urllib.error

import pytest

from gas_pult import providers


@pytest.fixture(autouse=True)
def cfgdir(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path))
    return tmp_path


def test_key_saved_private_and_masked(cfgdir):
    providers.save_key("elevenlabs", "sk_1234567890abcdefWXYZ")
    f = cfgdir / "secrets.json"
    assert f.stat().st_mode & 0o777 == 0o600
    assert providers.key_info() == {"elevenlabs": {"set": True, "tail": "…WXYZ"}}
    providers.save_key("elevenlabs", None)
    assert providers.key_info() == {}


def test_el_voices_and_bad_key(monkeypatch):
    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(providers.urllib.request, "urlopen",
                        lambda req, timeout: R(json.dumps({"voices": [{"voice_id": "v1", "name": "Ася"}]}).encode()))
    assert providers.el_voices("k" * 32) == [{"id": "v1", "name": "Ася"}]

    def deny(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(providers.urllib.request, "urlopen", deny)
    with pytest.raises(providers.ProviderError, match="ключ не подошёл"):
        providers.el_voices("bad")


def test_tts_falls_back_to_local_when_elevenlabs_fails(monkeypatch, tmp_path):
    """ElevenLabs отказал — озвучка уходит в локальный голос, а не в ошибку."""
    from gas_pult import providers, webapp

    panel = webapp.Panel.__new__(webapp.Panel)
    monkeypatch.setattr(panel, "message", lambda w, i: "Привет", raising=False)
    monkeypatch.setattr(panel, "voice_settings", lambda: {"tts": "elevenlabs", "el_voice": "v1"}, raising=False)
    monkeypatch.setattr(panel, "voice", lambda **kw: "irina", raising=False)
    panel.cfg = type("C", (), {"data": tmp_path})()

    def boom(*a):
        raise providers.ProviderError("ElevenLabs недоступен")

    monkeypatch.setattr(providers, "el_tts", boom)
    monkeypatch.setattr(providers, "load_keys", lambda: {"elevenlabs": "k"})
    monkeypatch.setattr(webapp.voice, "synth", lambda v, text, out: out.write_bytes(b"mp3"))
    assert panel.tts({}, True) == b"mp3"
    assert "переключился на локальный" in panel.fallback_note()


def test_silero_only_for_owner_with_personal_voices(monkeypatch, tmp_path):
    """Silero (лицензия некоммерческая) — владельцу при personal_voices = true; остальным и по умолчанию — нет."""
    from gas_pult import webapp
    from gas_pult.voice import catalog

    monkeypatch.setattr(catalog, "has", lambda m: True)
    monkeypatch.setattr(catalog, "piper_model", lambda n: tmp_path / "piper.onnx")
    monkeypatch.setattr(catalog, "silero_model", lambda: tmp_path / "silero.pt")
    (tmp_path / "piper.onnx").write_bytes(b"x")
    (tmp_path / "silero.pt").write_bytes(b"x")
    assert "xenia" not in catalog.installed() and "xenia" in catalog.installed(personal=True)

    panel = webapp.Panel.__new__(webapp.Panel)
    panel.pult = type("P", (), {"state": lambda self: {"voice": "xenia"}})()
    for flag, uid, seen in ((True, 1, True), (True, 2, False), (False, 1, False)):
        panel.cfg = type("C", (), {"personal_voices": flag, "owners": [1]})()
        own = panel.personal(uid)
        assert ("xenia" in catalog.installed(own)) is seen
        assert panel.voice(personal=own) == ("xenia" if seen else "irina")   # выбран Silero — остальным Piper


def test_personal_voices_config_is_bool(monkeypatch, tmp_path):
    from gas_pult import config

    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path))
    (tmp_path / "token").write_text("1:T\n")
    (tmp_path / "config.toml").write_text('owners = [1]\npersonal_voices = "да"\n')
    with pytest.raises(config.ConfigError, match="personal_voices"):
        config.load()
    (tmp_path / "config.toml").write_text("owners = [1]\npersonal_voices = true\n")
    assert config.load().personal_voices is True
    (tmp_path / "config.toml").write_text("owners = [1]\n")
    assert config.load().personal_voices is False
