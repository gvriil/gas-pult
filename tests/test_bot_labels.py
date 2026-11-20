"""Бот называет чат по смыслу, а не служебным именем окна.

Владелец 19.11: «номера убрать, оставлять смысловой контекст».
"""
import json

from gas_pult import bot, projects


def pult(tmp_path):
    p = bot.Pult.__new__(bot.Pult)
    p.cfg = type("C", (), {"data": tmp_path})()
    p.home_of = lambda w: None
    return p


def test_own_title_wins(tmp_path):
    (tmp_path / projects.FILE).write_text(json.dumps({"sessions": {"s1": {"title": "План продаж"}}}), encoding="utf-8")
    assert pult(tmp_path).label(
        {"id": "@1", "name": "gas-pult-1835", "sid": "s1", "cmd": "claude", "path": "/x"}) == "План продаж"


def test_no_title_is_new_chat_not_window_name(tmp_path, monkeypatch):
    monkeypatch.setattr(bot.transcripts, "current", lambda *a: None)
    assert pult(tmp_path).label(
        {"id": "@2", "name": "gas-pult-1835", "sid": "", "cmd": "claude", "path": "/x"}) == "Новый чат"


def test_status_title_is_hidden(tmp_path):
    status = "Ожидание ответа"
    (tmp_path / projects.FILE).write_text(json.dumps({"sessions": {"s3": {"title": status}}}), encoding="utf-8")
    if projects.is_status(status):
        assert pult(tmp_path).label(
        {"id": "@3", "name": "shtap-1", "sid": "s3", "cmd": "claude", "path": "/x"}) == "Новый чат"


def test_no_window_name_in_bot_texts():
    from pathlib import Path
    src = Path(bot.__file__).read_text(encoding="utf-8")
    shown = [ln for ln in src.splitlines() if ("{w['name']}" in ln or '{w["name"]}' in ln)]
    assert shown == [], shown


def test_terminal_is_not_a_chat(tmp_path):
    assert pult(tmp_path).label(
        {"id": "@4", "name": "bash-0904", "cmd": "bash", "path": "/x"}) == "Терминал"


class Tm:
    def __init__(self, ws):
        self.ws = ws

    def windows(self):
        return self.ws

    def window(self, wid):
        return next((w for w in self.ws if w["id"] == wid), None)


def test_reply_by_head_never_guesses_between_same_labels(tmp_path):
    """Две сессии без названия — обе «Новый чат»: ответ на «[Новый чат] …» без карты маршрутов не угадывает окно."""
    p = pult(tmp_path)
    p.tmux = Tm([{"id": "@1", "name": "a-1", "cmd": "claude", "path": "/a"},
                 {"id": "@2", "name": "b-2", "cmd": "claude", "path": "/b"}])
    p.label = lambda w: "Новый чат"
    rt = {"message_id": 5, "from": {"is_bot": True}, "text": "[Новый чат] ответ"}
    assert p.reply_target(1, {"reply_to_message": rt}) is None
    rt["text"] = "[b-2] старое сообщение"                  # старые сообщения с именем окна — по точному имени
    assert p.reply_target(1, {"reply_to_message": rt})["id"] == "@2"


def test_rename_sets_chat_title_not_window_name(tmp_path):
    p = pult(tmp_path)
    p.home = str(tmp_path)
    sid = "0f3c8a2e-1111-4222-8333-444455556666"
    p.tmux = Tm([{"id": "@1", "name": "gas-pult-1835", "cmd": "claude", "path": str(tmp_path), "sid": sid}])
    got = []
    p.send = lambda chat, text, **k: got.append(text)
    p.rename(1, "@1", "  План   продаж ")
    assert got == ["✏️ Теперь чат называется «План продаж»."]
    d = json.loads((tmp_path / projects.FILE).read_text(encoding="utf-8"))
    assert d["sessions"][sid]["title"] == "План продаж"
    assert p.label(p.tmux.ws[0]) == "План продаж"
