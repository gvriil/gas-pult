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
