"""Служба бота Telegram Business (решение владельца 16.11: «1 да»): одна точка чтения апдейтов, журнал 7 дней,
команды владельца в личке (/заметка, голосовое — локальный ASR)."""

import json
import os
import time

import pytest

from gas_pult import tgbiz_bot
from gas_pult.connectors import tgbiz_mcp

OWNER, STRANGER = 111, 999


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(tgbiz_bot, "ROOT", tmp_path / "tgbiz")
    monkeypatch.setattr(tgbiz_mcp, "STATE", tmp_path / "tgbiz")
    return tmp_path / "tgbiz"


class FakeApi:
    def __init__(self, batches):
        self.batches, self.calls, self.sent = list(batches), [], []

    def __call__(self, method, **p):
        self.calls.append((method, p))
        if method == "getUpdates":
            return self.batches.pop(0) if self.batches else []
        if method == "sendMessage":
            self.sent.append((p["chat_id"], p["text"]))
        return {}


def msg(uid, text=None, **kw):
    return {"message_id": 1, "chat": {"id": uid, "type": "private"}, "from": {"id": uid}, **({"text": text} if text
            is not None else {}), **kw}


def test_journal_append_read_prune(state):
    tgbiz_bot.append([{"update_id": 1}], now=1000.0)
    tgbiz_bot.append([{"update_id": 2}], now=1000.0 + tgbiz_bot.KEEP - 10)
    assert oct(tgbiz_bot.journal().stat().st_mode)[-3:] == "600"
    now = 1000.0 + tgbiz_bot.KEEP + 5
    assert [u["update_id"] for u in tgbiz_bot.read(now=now)] == [2]          # старше 7 дней — не отдаём
    assert tgbiz_bot.prune(now=now) == 1 and len(tgbiz_bot.journal().read_text().splitlines()) == 1


def test_poll_offset_journal_and_owner_commands(state):
    notes = []
    biz = {"update_id": 10, "business_message": {"message_id": 5, "chat": {"id": 7}, "text": "клиент"}}
    api = FakeApi([[biz, {"update_id": 11, "message": msg(OWNER, "/заметка Пётр платит в пятницу\n12 000")},
                    {"update_id": 12, "message": msg(STRANGER, "/заметка взлом")}]])
    bot = tgbiz_bot.Bot(api, [OWNER], save_note=lambda p: notes.append(p) or {"saved": "local", "remind": "токен…"},
                        stt=lambda fid: "")
    assert bot.poll() == 3 and bot.offset == 13
    assert [u["update_id"] for u in tgbiz_bot.read()] == [10, 11, 12]          # всё — в журнал
    assert notes == [{"title": "Пётр платит в пятницу", "text": "Пётр платит в пятницу\n12 000",
                      "source": "команда владельца в боте", "tags": [], "origin": "Личка бота"}]
    assert [c for c, _ in api.sent] == [OWNER] and "Сохранил заметку в файл" in api.sent[0][1]   # чужому — тишина
    bot.poll()
    assert api.calls[-1][1]["offset"] == 13 and tgbiz_bot.alive()


def test_voice_is_local_and_help(state):
    api = FakeApi([[{"update_id": 1, "message": msg(OWNER, voice={"file_id": "F1", "duration": 3})},
                    {"update_id": 2, "message": msg(OWNER, "привет")}]])
    bot = tgbiz_bot.Bot(api, [OWNER], save_note=None, stt=lambda fid: "встреча во вторник" if fid == "F1" else "")
    bot.poll()
    assert "Распознал:\n\nвстреча во вторник" in api.sent[0][1] and "/заметка" in api.sent[1][1]


def test_connector_reads_journal_when_service_alive(state, monkeypatch):
    biz = {"update_id": 10, "business_message": {"message_id": 5, "chat": {"id": 7}, "text": "клиент"}}
    tgbiz_bot.append([biz, {"update_id": 11, "message": msg(OWNER, "лично")}])
    monkeypatch.setattr(tgbiz_mcp, "_api", lambda *a, **k: pytest.fail("служба жива — Telegram не трогаем"))
    state.mkdir(parents=True, exist_ok=True)
    (state / "alive").touch()
    assert tgbiz_mcp._updates() == [biz]                                         # только бизнес-апдейты
    old = time.time() - 600
    os.utime(state / "alive", (old, old))                                        # служба не отвечает 10 мин
    monkeypatch.setattr(tgbiz_mcp, "_api", lambda *a, **k: [{"update_id": 99}])
    assert tgbiz_mcp._updates() == [{"update_id": 99}]                           # как раньше — напрямую
    assert json.loads(tgbiz_bot.journal().read_text().splitlines()[0])["update"] == biz


def test_connector_alive_service_without_journal_is_empty(state, monkeypatch):
    """Живая проверка 16.11: служба запущена, апдейтов ещё не было — коннектор шёл в getUpdates и получал 409."""
    state.mkdir(parents=True, exist_ok=True)
    (state / "alive").touch()
    monkeypatch.setattr(tgbiz_mcp, "_api", lambda *a, **k: pytest.fail("служба жива — Telegram не трогаем"))
    assert tgbiz_mcp._updates() == []

class FakeClaude:
    """Окно Claude: вставки копятся, ответ задаёт тест (готов?, текст, отпечаток журнала)."""

    def __init__(self):
        self.pasted, self.open, self.ans = [], True, (False, "", "")

    def open_window(self, name, path):
        return "@77", "11111111-1111-4111-8111-111111111111"

    def paste(self, wid, text):
        self.pasted.append(text)
        return True


def test_journalist_mode(state, tmp_path, monkeypatch):
    """Решение владельца 16.11 («2 Claude»): /журналист → окно Claude со скиллом zhurnalist; сообщения и голос — в окно;
    законченный ответ Claude — в бот один раз; /стоп — выйти. Черновик — на Диск владельца."""
    monkeypatch.setattr(tgbiz_bot, "DRAFTS", tmp_path / "drive" / "Статьи" / "черновики")
    monkeypatch.setattr(tgbiz_bot, "WORK", tmp_path / "work")
    c = FakeClaude()
    j = tgbiz_bot.Journalist(c.open_window, c.paste, lambda path, sid: c.ans, lambda wid: c.open)
    api = FakeApi([[{"update_id": 1, "message": msg(OWNER, "/журналист как мы убрали очереди в автомойке")}],
                   [{"update_id": 2, "message": msg(OWNER, "1) клиенты — владельцы моек")}],
                   [{"update_id": 3, "message": msg(OWNER, voice={"file_id": "V"})}],
                   [], [], [{"update_id": 4, "message": msg(OWNER, "/стоп")}]])
    bot = tgbiz_bot.Bot(api, [OWNER], save_note=None, stt=lambda fid: "очередь была 40 минут", journalist=j)
    bot.poll()
    assert (tmp_path / "drive" / "Статьи" / "черновики").is_dir()
    assert "Используй скилл zhurnalist" in c.pasted[0] and "автомойке" in c.pasted[0] and "«да»" in c.pasted[0]
    assert "Режим «журналист»" in api.sent[-1][1]
    bot.poll()                                                             # текст владельца — в окно, без ответа бота
    assert c.pasted[-1] == "1) клиенты — владельцы моек" and len(api.sent) == 1
    bot.poll()                                                             # голос — расшифровка в окно
    assert c.pasted[-1] == "очередь была 40 минут" and "передал журналисту" in api.sent[-1][1]
    assert [p for m, p in api.calls if m == "getUpdates"][-1]["timeout"] == 3   # ждём Claude — опрос короткий
    c.ans = (True, "1. Сколько моек?\n2. Какая выручка?", "rev-1")
    bot.poll()
    assert api.sent[-1] == (OWNER, "1. Сколько моек?\n2. Какая выручка?")
    n = len(api.sent)
    bot.poll()
    assert len(api.sent) == n                                              # тот же ответ — второй раз не шлём
    bot.poll()
    assert "Вышел из режима" in api.sent[-1][1] and not j.state()


def test_journalist_window_closed(state, tmp_path, monkeypatch):
    monkeypatch.setattr(tgbiz_bot, "DRAFTS", tmp_path / "d")
    monkeypatch.setattr(tgbiz_bot, "WORK", tmp_path / "w")
    c = FakeClaude()
    j = tgbiz_bot.Journalist(c.open_window, c.paste, lambda path, sid: c.ans, lambda wid: c.open)
    j.start(OWNER, "тема")
    c.open = False
    assert j.relay() == (OWNER, "Окно журналиста закрыто — режим выключен.") and not j.state()
