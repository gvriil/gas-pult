"""Интерфейс каналов: TelegramChannel с подменённым Api — нужные методы Bot API и разбор обновлений."""

from pathlib import Path

from gas_pult.channels import Attachment, Button, Channel, Incoming, TelegramChannel, buttons


class FakeApi:
    def __init__(self, results=None):
        self.calls = []
        self.results = results or {}

    def __call__(self, method, files=None, **kw):
        self.calls.append((method, files, kw))
        r = self.results.get(method)
        return r.pop(0) if isinstance(r, list) else r

    def download(self, file_id, dst_dir, name=None):
        self.calls.append(("download", None, {"file_id": file_id, "dst": dst_dir, "name": name}))
        return Path(dst_dir) / (name or "file")


def chan(**results):
    api = FakeApi(results)
    return TelegramChannel(api), api


def test_protocol_and_caps():
    ch, _ = chan()
    assert isinstance(ch, Channel)
    assert not isinstance(object(), Channel)
    assert ch.name == "telegram" and ch.caps.buttons and ch.caps.edit and ch.caps.voice and ch.caps.mini_app


def test_send_text_with_buttons():
    ch, api = chan(sendMessage={"message_id": 7})
    kb = [*buttons([[("Да", "ok:1"), ("Нет", "no:1")]]),
          [Button("Панель", web_app="https://example.org/"), Button("Сайт", url="https://example.org/a")]]
    assert ch.send_text(5, "Вопрос", kb) == 7
    method, files, kw = api.calls[0]
    assert method == "sendMessage" and files is None and kw["chat_id"] == 5 and kw["text"] == "Вопрос"
    assert kw["reply_markup"] == {"inline_keyboard": [
        [{"text": "Да", "callback_data": "ok:1"}, {"text": "Нет", "callback_data": "no:1"}],
        [{"text": "Панель", "web_app": {"url": "https://example.org/"}},
         {"text": "Сайт", "url": "https://example.org/a"}]]}


def test_send_text_plain_and_empty():
    ch, api = chan()
    assert ch.send_text(5, "") is None
    assert api.calls[0][2] == {"chat_id": 5, "text": "—"}        # без reply_markup; пустой текст Telegram не примет


def test_edit_answer_files_download(tmp_path):
    ch, api = chan()
    ch.edit_text(5, 9, "новое", buttons([[("↻", "r")]]))
    ch.answer("cb1")
    ch.answer("cb2", "Готово")
    ch.send_file(5, "answer.ogg", b"OGG", kind="voice")
    ch.send_file(5, "answer.mp3", b"MP3", kind="audio")
    ch.send_file(5, "output.txt", b"log")
    p = ch.download(Attachment("voice", "F1", "voice.ogg"), tmp_path)
    assert api.calls[0] == ("editMessageText", None, {"chat_id": 5, "message_id": 9, "text": "новое",
                            "reply_markup": {"inline_keyboard": [[{"text": "↻", "callback_data": "r"}]]}})
    assert api.calls[1] == ("answerCallbackQuery", None, {"callback_query_id": "cb1"})
    assert api.calls[2] == ("answerCallbackQuery", None, {"callback_query_id": "cb2", "text": "Готово"})
    assert api.calls[3] == ("sendVoice", {"voice": ("answer.ogg", b"OGG")}, {"chat_id": 5})
    assert api.calls[4] == ("sendAudio", {"audio": ("answer.mp3", b"MP3")}, {"chat_id": 5})
    assert api.calls[5] == ("sendDocument", {"document": ("output.txt", b"log")}, {"chat_id": 5})
    assert api.calls[6][2]["file_id"] == "F1" and p == tmp_path / "voice.ogg"


MSG = {"update_id": 10, "message": {"message_id": 3, "chat": {"id": 5}, "from": {"id": 5}, "text": "привет"}}
CB = {"update_id": 11, "callback_query": {"id": "q1", "from": {"id": 5}, "data": "sw:@1",
                                          "message": {"message_id": 4, "chat": {"id": 5}}}}
VOICE = {"update_id": 12, "message": {"message_id": 6, "chat": {"id": 5}, "from": {"id": 5},
                                      "voice": {"file_id": "V1", "duration": 2}}}
PHOTO = {"update_id": 13, "message": {"message_id": 8, "chat": {"id": 5}, "from": {"id": 5}, "caption": "что тут",
                                      "photo": [{"file_id": "small"}, {"file_id": "big"}]}}


def test_parse_message_callback_voice_photo():
    m = TelegramChannel.parse(MSG)
    assert m == Incoming("telegram", 5, 5, text="привет", message_id=3)
    c = TelegramChannel.parse(CB)
    assert (c.button, c.callback_id, c.chat, c.user, c.message_id, c.text) == ("sw:@1", "q1", 5, 5, 4, "")
    v = TelegramChannel.parse(VOICE)
    assert v.attachment == Attachment("voice", "V1") and v.text == ""
    p = TelegramChannel.parse(PHOTO)
    assert p.attachment == Attachment("photo", "big") and p.text == "что тут"
    assert TelegramChannel.parse({"update_id": 14, "edited_message": {}}) is None
    assert m.raw is MSG


def test_poll_moves_offset_and_skips_unknown():
    ch, api = chan(getUpdates=[[MSG, CB, {"update_id": 12, "edited_message": {}}], []])
    evs = ch.poll(timeout=30)
    assert [e.button or e.text for e in evs] == ["привет", "sw:@1"]
    assert api.calls[0] == ("getUpdates", None, {"timeout": 30})
    ch.poll()
    assert api.calls[1] == ("getUpdates", None, {"timeout": 60, "offset": 13})
