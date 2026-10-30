"""Поставщики голоса и ключи API: локально (Piper/Silero + faster-whisper) или ElevenLabs.

Ключи — ``~/.config/gas-pult/secrets.json`` (права 0600), наружу отдаются только последние 4 символа.
Выбор поставщика — в ``state.json`` пульта: ``tts_provider``, ``stt_provider``, ``el_voice``.
С ElevenLabs текст ответов (озвучка) и голосовые (распознавание) уходят в ElevenLabs — панель об этом пишет.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from gas_pult.config import config_dir

EL_API = "https://api.elevenlabs.io/v1"
EL_TTS_MODEL = "eleven_multilingual_v2"     # русский поддерживается
EL_STT_MODEL = "scribe_v1"
TIMEOUT = 120


def secrets_file() -> Path:
    return config_dir() / "secrets.json"


def load_keys() -> dict:
    try:
        return json.loads(secrets_file().read_text())
    except (OSError, ValueError):
        return {}


def save_key(provider: str, key: str | None):
    d = load_keys()
    if key:
        d[provider] = key
    else:
        d.pop(provider, None)
    f = secrets_file()
    f.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    f.touch(mode=0o600, exist_ok=True)
    f.chmod(0o600)
    f.write_text(json.dumps(d))


def key_info() -> dict:
    return {p: {"set": True, "tail": "…" + k[-4:]} for p, k in load_keys().items() if k}


class ProviderError(Exception):
    pass


def _el(path: str, key: str, body: bytes | None = None, ctype: str | None = None, accept: str = "application/json"):
    headers = {"xi-api-key": key, "Accept": accept}
    if ctype:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(EL_API + path, body, headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        if e.code in (401, 403) or "invalid_api_key" in detail:
            raise ProviderError("ElevenLabs: ключ не подошёл — скопируйте его целиком заново "
                                "(или у ключа нет прав Text to Speech / Speech to Text / Voices)") from None
        if e.code == 429:
            raise ProviderError("ElevenLabs: исчерпан лимит тарифа или слишком много запросов") from None
        raise ProviderError(f"ElevenLabs: ошибка {e.code} {detail[:200]}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise ProviderError(f"ElevenLabs недоступен: {e}") from None
    return json.loads(data) if accept == "application/json" else data


# Проверка ключа поставщика моделей бесплатным служебным запросом (без генерации): адрес → чем проверяем.
CHECK = {"openrouter": "https://openrouter.ai/api/v1/key", "deepseek": "https://api.deepseek.com/user/balance"}
NAMES = {"openrouter": "OpenRouter", "zai": "Z.ai", "deepseek": "DeepSeek", "elevenlabs": "ElevenLabs"}


def check_model_key(provider: str, key: str) -> bool:
    """True — ключ проверен; False — проверить нечем (Z.ai, сеть, другой ответ): проверится при запуске сессии."""
    url = CHECK.get(provider)
    if not url:
        return False
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20):
            return True
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise ProviderError(f"{NAMES[provider]}: ключ не подошёл — скопируйте его целиком заново") from None
        return False
    except (urllib.error.URLError, TimeoutError):
        return False


def el_voices(key: str) -> list[dict]:
    """Голоса аккаунта — заодно проверка ключа."""
    return [{"id": v["voice_id"], "name": v.get("name", v["voice_id"])} for v in _el("/voices", key).get("voices", [])]


def el_tts(key: str, voice_id: str, text: str) -> bytes:
    body = json.dumps({"text": text, "model_id": EL_TTS_MODEL}).encode()
    return _el(f"/text-to-speech/{voice_id}?output_format=mp3_44100_128", key, body, "application/json", "audio/mpeg")


def el_stt(key: str, audio: bytes, filename: str) -> str:
    b = uuid.uuid4().hex
    body = b"".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                    for k, v in (("model_id", EL_STT_MODEL), ("language_code", "rus")))
    body += (f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
             "Content-Type: application/octet-stream\r\n\r\n").encode() + audio + f"\r\n--{b}--\r\n".encode()
    return str(_el("/speech-to-text", key, body, f"multipart/form-data; boundary={b}").get("text", "")).strip()
