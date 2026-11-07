"""«#ревью» в боте: отчёт владельца — файлом в inbox для разбора, не в сессию (задача 52)."""

import stat
from datetime import datetime

import pytest

from gas_pult import bot, review_inbox
from gas_pult.config import Config, data_dir

OWNER, OTHER = 1, 2


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def pult(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    sent, files = [], {}

    class FakeApi:
        def __init__(self, token):
            pass

        def __call__(self, method, **kw):
            sent.append((method, kw))
            return {"message_id": len(sent)}

        def download(self, file_id, dst_dir, name=None):
            dst_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = dst_dir / f"x-{name}"
            path.write_bytes(files[file_id])
            return path

        def redact(self, e):
            return str(e)

    monkeypatch.setattr(bot, "Api", FakeApi)
    p = bot.Pult(Config(token="1:T", owners=[OWNER]))
    clock, now = Clock(), {"v": datetime(2026, 11, 7, 10, 5)}
    p.reviews.clock, p.reviews.now = clock, lambda: now["v"]
    to_session = []
    p.to_claude_live = lambda chat, w, text: to_session.append(text)
    p.need_active = lambda chat: {"id": "@1", "name": "w"}
    p.files, p.clock, p.when, p.to_session, p.sent = files, clock, now, to_session, sent
    return p


def msg(text=None, uid=OWNER, mid=10, **kw):
    m = {"chat": {"id": uid}, "from": {"id": uid}, "message_id": mid, **kw}
    if text is not None:
        m["text"] = text
    return m


def inbox():
    return data_dir() / "inbox"


def reviews():
    return sorted(inbox().glob("*ревью*"))


def texts(p):
    return [kw.get("text") for meth, kw in p.sent if meth == "sendMessage"]


def test_text_saved_not_sent_to_session(pult):
    pult.on_message(msg("#ревью\nНаходка 1: нет тестов на X.\nНаходка 2: …"))
    [f] = reviews()
    assert f.name == "ревью-2026-11-07-1005.md"
    body = f.read_text()
    assert body.startswith("# Ревью 2026-11-07 10:05")
    assert "- Дата: 2026-11-07 10:05" in body and "- Переслано от: —" in body
    assert body.endswith("Находка 1: нет тестов на X.\nНаходка 2: …\n")
    assert "#ревью" not in body.split("---", 1)[1]
    assert pult.to_session == []
    assert texts(pult) == ["принято, разберу в 14:00"]


@pytest.mark.parametrize("label", ["#Ревью ", "#РЕВЬЮ:", "  #ревью\n\n", "#ревью — "])
def test_label_case_and_spacing(pult, label):
    pult.on_message(msg(label + "текст отчёта"))
    [f] = reviews()
    assert f.read_text().endswith("\n---\n\nтекст отчёта\n")
    assert pult.to_session == []


@pytest.mark.parametrize("text", ["ревью без решётки", "смотри #ревью в середине", "#ревьюшка", "#review x"])
def test_without_label_goes_to_session(pult, text):
    pult.on_message(msg(text))
    assert reviews() == [] and pult.to_session


def test_forwarded_message_with_label(pult):
    origin = {"type": "user", "sender_user": {"id": 777, "first_name": "Отчёт", "username": "some_bot"}, "date": 1}
    pult.on_message(msg("#ревью итог недели", forward_origin=origin))
    body = reviews()[0].read_text()
    assert "- Переслано от: Отчёт (@some_bot)" in body and "(пересланное)" in body
    assert "777" not in body                                   # Telegram ID в файл не попадает
    assert pult.to_session == []


def test_caption_of_text_document_included(pult):
    pult.files["F1"] = "# Отчёт\nпункт 1".encode()
    pult.on_message(msg(caption="#Ревью от ChatGPT",
                        document={"file_id": "F1", "file_name": "report.md", "mime_type": "text/markdown"}))
    [f] = reviews()
    body = f.read_text()
    assert "от ChatGPT\n\n# Отчёт\nпункт 1" in body and "- Вложения: " in body
    att = list((inbox() / review_inbox.ATT_DIR).iterdir())
    assert len(att) == 1 and stat.S_IMODE(att[0].stat().st_mode) == 0o600
    assert pult.to_session == []


def test_caption_of_photo_keeps_path(pult):
    pult.files["P"] = b"\x89PNG"
    pult.on_message(msg(caption="#ревью скрин", photo=[{"file_id": "P"}]))
    body = reviews()[0].read_text()
    assert "скрин" in body and "review-att" in body and pult.to_session == []


def test_not_owner_is_not_captured(pult):
    pult.people.role = lambda uid: "member"
    pult.on_message(msg("#ревью чужой отчёт", uid=OTHER))
    assert reviews() == []


def test_same_minute_suffix(pult):
    for i in range(3):
        pult.clock.t += 100                                    # новые посылки, не продолжение
        pult.on_message(msg(f"#ревью {i}", mid=10 + i))
    assert [f.name for f in reviews()] == ["ревью-2026-11-07-1005-2.md", "ревью-2026-11-07-1005-3.md",
                                           "ревью-2026-11-07-1005.md"]


def test_permissions(pult):
    pult.on_message(msg("#ревью секретный разбор"))
    assert stat.S_IMODE(inbox().stat().st_mode) == 0o700
    assert stat.S_IMODE(reviews()[0].stat().st_mode) == 0o600
    assert not list(inbox().glob(".review-*"))                 # временных файлов не осталось


def test_existing_inbox_tightened(pult):
    inbox().mkdir(parents=True, mode=0o755)
    inbox().chmod(0o755)
    pult.on_message(msg("#ревью x"))
    assert stat.S_IMODE(inbox().stat().st_mode) == 0o700


@pytest.mark.parametrize(("hm", "word"), [((0, 0), "в 14:00"), ((13, 59), "в 14:00"), ((14, 0), "в 21:00"),
                                          ((20, 59), "в 21:00"), ((21, 0), "завтра в 14:00"),
                                          ((23, 30), "завтра в 14:00")])
def test_reply_by_time(pult, hm, word):
    pult.when["v"] = datetime(2026, 11, 7, *hm)
    pult.on_message(msg("#ревью x"))
    assert texts(pult) == [f"принято, разберу {word}"]


def test_long_split_text_is_glued(pult):
    a, b = "А" * 4000, "Б" * 1200
    pult.on_message(msg("#ревью " + a, mid=10))
    pult.clock.t += 2
    pult.on_message(msg(b, mid=11))                            # Telegram разрезал вставленный текст
    pult.clock.t += 2
    pult.on_message(msg("а это уже в сессию", mid=12))         # предыдущая часть короткая — цепочка кончилась
    [f] = reviews()
    assert f.read_text().endswith(a + "\n\n" + b + "\n") and "- Частей: 2" in f.read_text()
    assert pult.to_session == ["а это уже в сессию"]
    assert len(texts(pult)) == 1                               # «принято» — один раз


def test_label_then_forwards_are_glued(pult):
    o = {"type": "channel", "chat": {"id": -100, "title": "Ревью-канал"}, "date": 1}
    pult.on_message(msg("#ревью", mid=20))                     # комментарий к пересылке приходит первым
    for i, part in enumerate(["часть 1", "часть 2"]):
        pult.clock.t += 1
        pult.on_message(msg(part, mid=21 + i, forward_origin=o))
    body = reviews()[0].read_text()
    assert body.endswith("часть 1\n\nчасть 2\n") and "- Переслано от: Ревью-канал" in body
    assert pult.to_session == []


def test_glue_stops_after_pause_and_on_commands(pult):
    pult.on_message(msg("#ревью", mid=30))
    pult.clock.t += review_inbox.GLUE + 1
    pult.on_message(msg("обычное сообщение", mid=31))
    assert pult.to_session == ["обычное сообщение"]
    pult.on_message(msg("#ревью " + "x" * 4000, mid=32))
    pult.on_message(msg("/digest", mid=33))
    pult.on_message(msg("y", mid=34))
    assert pult.to_session == ["обычное сообщение", "y"]


def test_parts_ordered_by_message_id(pult):
    o = {"type": "hidden_user", "sender_user_name": "Кто-то", "date": 1}
    pult.on_message(msg("#ревью", mid=40))
    pult.on_message(msg("второе", mid=42, forward_origin=o))
    pult.on_message(msg("первое", mid=41, forward_origin=o))
    assert reviews()[0].read_text().endswith("первое\n\nвторое\n")


def test_report_not_logged(pult, capsys):
    pult.on_message(msg("#ревью секретная-находка-42"))
    out = capsys.readouterr()
    assert "секретная-находка-42" not in out.out + out.err
