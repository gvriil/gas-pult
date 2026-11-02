"""Простой выбор голоса: карточки (панель), «Послушать» с кешем на сервере, выбор одним нажатием, /voice в боте."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import bot, providers, voice, webapp, webauth
from gas_pult.config import Config
from gas_pult.voice import catalog


@pytest.fixture
def voices(monkeypatch, tmp_path):
    """Установлены Piper «Ирина», «Дмитрий» и модель Silero; ключа ElevenLabs нет; синтез — подменён."""
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(catalog, "has", lambda m: True)
    monkeypatch.setattr(catalog, "piper_model", lambda n: tmp_path / f"{n}.onnx")
    monkeypatch.setattr(catalog, "silero_model", lambda: tmp_path / "silero.pt")
    for f in ("irina.onnx", "dmitri.onnx", "silero.pt"):
        (tmp_path / f).write_bytes(b"x")
    calls = []

    def synth(v, text, out, timeout=300):
        calls.append((v, text, out.suffix))
        out.write_bytes(f"{v}{out.suffix}".encode())

    monkeypatch.setattr(voice, "synth", synth)
    el = [{"id": "e1", "name": "Rachel"}, {"id": "e2", "name": "Ася"}]
    monkeypatch.setattr(providers, "el_voices", lambda key: el)
    return calls


def make_panel(flag: bool) -> webapp.Panel:
    p = webapp.Panel(Config(token="1:T", owners=[1], personal_voices=flag))
    p.pult.set_state(voice="xenia")                      # голос по умолчанию у владельца — Ксения
    return p


def ids(d):
    return [c["id"] for c in d["cards"]]


def test_cards_owner_with_flag(voices):
    d = make_panel(True).voice_cards(owner=True)
    assert ids(d) == ["elevenlabs", "xenia", "baya", "aidar", "eugene", "kseniya"]      # Piper в выборе нет
    by = {c["id"]: c for c in d["cards"]}
    assert by["elevenlabs"]["ok"] is False and by["elevenlabs"]["why"] == "нужен ключ ElevenLabs"
    assert by["xenia"]["name"] == "Ксения" and by["xenia"]["kind"] == "женский" and by["aidar"]["kind"] == "мужской"
    assert all(by[n]["demo"] is True for n in catalog.SILERO)                           # некоммерческие — «демо»
    assert d["current"] == "xenia" and d["can_choose"] is True and d["fallback"] == ""


def test_cards_silero_not_installed_owner_sees_install(voices, tmp_path):
    (tmp_path / "silero.pt").unlink()
    d = make_panel(True).voice_cards(owner=True)
    by = {c["id"]: c for c in d["cards"]}
    assert by["xenia"]["ok"] is False and by["xenia"]["install"] == "gas-pult voices install xenia"
    assert d["current"] == "irina" and d["fallback"] == "Ирина"   # Ксении нет — читает запасной Piper


def test_cards_owner_without_flag_has_no_silero(voices):
    d = make_panel(False).voice_cards(owner=True)
    assert ids(d) == ["elevenlabs"]                       # ни Silero (нет personal_voices), ни Piper
    assert d["current"] == "irina" and d["fallback"] == "Ирина"   # Ксения недоступна — читает запасной Piper


def test_cards_member_only_installed_listen_only(voices):
    p = make_panel(True)
    d = p.voice_cards(owner=False)
    assert ids(d) == []                                    # ни Silero, ни Piper, ни ElevenLabs без ключа
    assert d["can_choose"] is False and d["current"] == "irina" and d["fallback"] == "Ирина"
    providers.save_key("elevenlabs", "k" * 24)
    assert ids(p.voice_cards(owner=False))[0] == "elevenlabs"


def test_preview_cached_and_silero_denied_to_member(voices):
    p = make_panel(True)
    assert p.voice_preview("xenia", owner=True) == b"xenia.mp3"
    assert p.voice_preview("xenia", owner=True) == b"xenia.mp3"
    assert voices == [("xenia", catalog.PREVIEW, ".mp3")]  # второй раз — из кеша, без синтеза
    assert (p.cfg.data / "voice-preview" / "xenia.mp3").exists()
    with pytest.raises(ValueError):
        p.voice_preview("xenia", owner=False)              # Silero участнику — нет, даже из кеша
    with pytest.raises(ValueError):
        make_panel(False).voice_preview("baya", owner=True)   # и владельцу без personal_voices
    assert p.voice_preview("irina", owner=False) == b"irina.mp3"


def test_preview_elevenlabs_cached_by_voice_id(voices, monkeypatch):
    p = make_panel(True)
    providers.save_key("elevenlabs", "k" * 24)
    sent = []
    monkeypatch.setattr(providers, "el_tts", lambda key, vid, text: sent.append(vid) or b"el-" + vid.encode())
    assert p.voice_preview("elevenlabs", owner=True) == b"el-e1"
    assert p.voice_preview("elevenlabs", owner=True) == b"el-e1"
    p.pult.set_state(el_voice="e2")
    assert p.voice_preview("elevenlabs", owner=True) == b"el-e2"
    assert sent == ["e1", "e2"]                            # в ElevenLabs — только при первом прослушивании голоса


def test_choose_sets_provider_and_voice(voices):
    p = make_panel(True)
    with pytest.raises(ValueError, match="ключ ElevenLabs"):
        p.choose_voice("elevenlabs")
    with pytest.raises(ValueError, match="больше не выбирается"):
        p.choose_voice("irina")                            # Piper — только запасной
    with pytest.raises(ValueError, match="не установлен"):
        p.choose_voice("nobody")
    providers.save_key("elevenlabs", "k" * 24)
    p.choose_voice("elevenlabs")
    st = p.pult.state()
    assert st["tts_provider"] == "elevenlabs" and st["el_voice"] == "e1" and st["voice"] == "xenia"
    d = p.voice_cards(owner=True)
    assert d["current"] == "elevenlabs" and d["cards"][0]["name"] == "Rachel"
    p.choose_voice("baya")
    st = p.pult.state()
    assert st["tts_provider"] == "local" and st["voice"] == "baya" and p.voice_cards(owner=True)["current"] == "baya"


def call(base, path, body=None, token=""):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={token}"})
    try:
        with urllib.request.urlopen(req) as r:
            data = r.read()
            return r.status, json.loads(data) if r.headers.get_content_type() == "application/json" else data
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


@pytest.fixture
def server(voices):
    panel = make_panel(True)
    panel.people.add(2, "member")
    for uid in (1, 2):
        panel.people.accept(uid)
        panel.people.set_country(uid, chosen="NL")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield panel, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_api_cards_preview_choose(server):
    panel, base = server
    owner, member = panel.auth.issue(1), panel.auth.issue(2)
    assert call(base, "/api/voice/cards", None, owner)[1]["current"] == "xenia"
    assert ids(call(base, "/api/voice/cards", None, member)[1]) == []
    assert call(base, "/api/voice/preview?id=xenia", None, owner) == (200, b"xenia.mp3")
    assert call(base, "/api/voice/preview?id=xenia", None, member)[0] == 400       # Silero участнику — отказ
    assert call(base, "/api/voice/preview?id=irina", None, member) == (200, b"irina.mp3")
    assert call(base, "/api/voice/choose", {"id": "irina"}, member)[0] == 403       # выбирает владелец
    code, d = call(base, "/api/voice/choose", {"id": "aidar"}, owner)
    assert code == 200 and d["current"] == "aidar" and panel.pult.state()["voice"] == "aidar"
    assert "local_voices" in call(base, "/api/providers", None, owner)[1]          # старые поля на месте


@pytest.fixture
def pult(voices, tmp_path):
    p = bot.Pult(Config(token="1:T", owners=[1], personal_voices=True))
    p.set_state(voice="xenia")
    p.sent, p.calls = [], []
    p.send = lambda chat, text, **kw: p.sent.append((text, kw))
    p.api = lambda method, **kw: p.calls.append((method, kw)) or {}
    return p


def buttons(markup) -> list[list[tuple[str, str]]]:
    return [[(b["text"], b["callback_data"]) for b in row] for row in markup["inline_keyboard"]]


def test_bot_voice_grid_and_choose(pult):
    p = pult
    p.on_message({"chat": {"id": 1}, "from": {"id": 1}, "text": "/voice"})
    text, kw = p.sent[-1]
    rows = buttons(kw["reply_markup"])
    assert "Ксения" in text and rows[0] == [("ElevenLabs — нужен ключ", "vi:elevenlabs")]
    assert rows[1] == [("▶ Ксения", "vp:xenia"), ("✅ Ксения · женский · демо", "vs:xenia")]
    assert [r[0][1] for r in rows[1:]] == ["vp:" + v for v in catalog.ORDER]      # только Silero, без Piper
    assert not any("Ирина" in t for r in rows for t, _ in r)
    q = {"id": "q", "from": {"id": 1}, "message": {"chat": {"id": 1}, "message_id": 5}, "data": "vs:aidar"}
    p.on_callback(q)
    assert p.state()["voice"] == "aidar" and p.state()["tts_provider"] == "local"
    method, kw = p.calls[-1]
    assert method == "editMessageText" and kw["message_id"] == 5
    assert ("✅ Айдар · мужской · демо", "vs:aidar") in [r[1] for r in buttons(kw["reply_markup"]) if len(r) == 2]


def test_bot_voice_preview_sends_cached_voice(pult, voices):
    p = pult
    q = {"id": "q", "from": {"id": 1}, "message": {"chat": {"id": 1}, "message_id": 5}, "data": "vp:xenia"}
    p.on_callback(q)
    p.on_callback(q)
    sends = [kw for m, kw in p.calls if m == "sendVoice"]
    assert len(sends) == 2 and sends[0]["files"]["voice"][1] == b"xenia.ogg"
    assert voices == [("xenia", catalog.PREVIEW, ".ogg")]    # синтез — один раз, дальше из кеша


def test_previously_chosen_piper_keeps_reading(voices):
    """Голос Piper, выбранный раньше, в выборе не виден, но озвучка им продолжается — в панели и в боте."""
    p = make_panel(True)
    p.pult.set_state(voice="irina")
    p.message = lambda w, i: "Готово, всё проверил."
    assert p.tts({}, True, personal=True) == b"irina.mp3"
    d = p.voice_cards(owner=True)
    assert d["current"] == "irina" and d["fallback"] == "Ирина" and "irina" not in ids(d)
    b = bot.Pult(Config(token="1:T", owners=[1], personal_voices=True))
    b.set_state(voice="irina")
    b.api = lambda method, **kw: {}
    b.say(1, "Готово.")
    assert voices[-1][0] == "irina"
    assert "запасной голос сервера (Ирина)" in b.voice_text()


def test_no_personal_no_elevenlabs_still_speaks(voices):
    """Без personal_voices и без ключа ElevenLabs карточек нет, но озвучка идёт запасным Piper (и в боте)."""
    p = make_panel(False)                                  # выбрана Ксения, но Silero недоступна
    p.message = lambda w, i: "Ответ."
    assert p.tts({}, False) == b"irina.mp3"
    b = bot.Pult(Config(token="1:T", owners=[1], personal_voices=False))
    b.set_state(voice="xenia")
    sent = []
    b.send = lambda chat, text, **kw: sent.append(text)
    b.api = lambda method, **kw: {}
    b.say(1, "Ответ.")
    assert voices[-1][0] == "irina" and not sent           # не «голос не установлен», а тихий запасной


def test_stt_empty_and_timeout_are_clear_errors(voices, monkeypatch):
    import subprocess
    p = make_panel(False)
    monkeypatch.setattr(voice, "transcribe", lambda path, model, timeout=300: "  ")
    with pytest.raises(ValueError, match="Ничего не расслышал"):
        p.stt(b"audio", "audio/webm")
    with pytest.raises(ValueError, match="Ничего не расслышал"):
        p.stt(b"", "audio/webm")                           # пустая запись — до whisper не доходит

    def slow(path, model, timeout=300):
        raise subprocess.TimeoutExpired("whisper", timeout)
    monkeypatch.setattr(voice, "transcribe", slow)
    with pytest.raises(RuntimeError, match="не уложилось"):
        p.stt(b"audio", "audio/webm")
    monkeypatch.setattr(voice, "transcribe", lambda path, model, timeout=300: " Привет ")
    assert p.stt(b"audio", "audio/webm") == "Привет"
    assert not list((p.cfg.data / "inbox").glob("web-*"))  # голос не храним


def test_api_stt_empty_returns_400_with_message(server, monkeypatch):
    panel, base = server
    monkeypatch.setattr(voice, "transcribe", lambda path, model, timeout=300: "")
    req = urllib.request.Request(base + "/api/stt", b"audio", {"Content-Type": "audio/webm",
                                                              "Cookie": f"{webauth.COOKIE}={panel.auth.issue(1)}"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 400 and json.load(e.value)["error"] == "Ничего не расслышал — попробуйте ещё раз"
