"""Корзина чатов чистится сама: запись старше 30 дней удаляется окончательно (журнал и папка субагентов), за 3 дня
список предупреждает. Время подменено — ничего не ждём; живой tmux и Claude не нужны."""

import time
import types

import pytest
from test_project_chats import NEW, OLD, OPEN, call
from test_project_chats import server as server

from gas_pult import chat_trash

DAY = 86400
T0 = 1_800_000_000


def clock(monkeypatch, t):
    monkeypatch.setattr(chat_trash, "time", types.SimpleNamespace(time=lambda: t, strftime=time.strftime))


def journal(folder, sid, sub=True):
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f"{sid}.jsonl"
    f.write_text("{}\n")
    if sub:
        (folder / sid).mkdir()
        (folder / sid / "agent.jsonl").write_text("{}\n")
    return f


def test_purge_after_30_days_with_subagents(tmp_path, monkeypatch):
    data, j = tmp_path / "data", tmp_path / "j"
    clock(monkeypatch, T0)
    old = chat_trash.put(data, journal(j, OPEN), "Старый", "p1")
    clock(monkeypatch, T0 + 10 * DAY)
    young = chat_trash.put(data, journal(j, NEW), "Свежий", "p1")
    assert old["purge_at"] == T0 + 30 * DAY and old["days_left"] == 30 and not old["warn"]
    # 26,5 дня: осталось 3,5 → 4 дня, ещё без предупреждения; 27,5 дня — 3 дня, предупреждение
    first = {x["id"]: x for x in chat_trash.listing(data, T0 + 26.5 * DAY)}[old["id"]]
    assert first["days_left"] == 4 and not first["warn"]
    near = {x["id"]: x for x in chat_trash.listing(data, T0 + 27.5 * DAY)}
    assert near[old["id"]]["days_left"] == 3 and near[old["id"]]["warn"]
    assert near[young["id"]]["days_left"] == 13 and not near[young["id"]]["warn"]
    assert chat_trash.listing(data, T0 + 29.9 * DAY)[1]["days_left"] == 1
    assert chat_trash.purge(data, T0 + 30 * DAY - 1) == []                  # за секунду до срока — на месте
    assert chat_trash.purge(data, T0 + 30 * DAY) == [old["id"]]
    assert not (chat_trash.base(data) / old["id"]).exists()                 # журнал и папка субагентов — стёрты
    assert [x["id"] for x in chat_trash.listing(data, T0 + 30 * DAY)] == [young["id"]]
    with pytest.raises(LookupError):
        chat_trash.restore(data, old["id"])
    assert (chat_trash.base(data) / young["id"] / NEW / "agent.jsonl").exists()
    assert not (j / f"{OPEN}.jsonl").exists()                               # из прежнего места ничего не вернулось


def test_purge_touches_only_trash_records(tmp_path, monkeypatch):
    """Чужое в папке корзины (не наш id, без meta.json, ссылка) — не трогаем."""
    data = tmp_path / "data"
    clock(monkeypatch, T0)
    chat_trash.put(data, journal(tmp_path / "j", OLD, sub=False))
    root = chat_trash.base(data)
    (root / "заметки").mkdir()
    (root / "20200101-000000__00000000-0000-4000-8000-000000000000").mkdir()   # наш вид, но без meta.json
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("x")
    (root / "20200101-000000__00000000-0000-4000-8000-000000000001").symlink_to(outside)
    assert len(chat_trash.purge(data, T0 + 400 * DAY)) == 1
    assert (root / "заметки").is_dir() and (outside / "keep.txt").exists()
    assert (root / "20200101-000000__00000000-0000-4000-8000-000000000000").is_dir()


def test_panel_tick_hourly_and_api_warns(server, monkeypatch):
    p, base, _wins, pid, shop = server
    tok = p.auth.issue(1)
    folder = shop.parent / "_trash_src"
    clock(monkeypatch, T0)
    a = chat_trash.put(p.cfg.data, journal(folder, OPEN), "Скоро уйдёт", pid)
    clock(monkeypatch, T0 + 5 * DAY)
    b = chat_trash.put(p.cfg.data, journal(folder, OLD), "Ещё полежит", pid)
    # фоновый цикл: первый вызов — сразу, следующий — не раньше чем через час
    assert p.trash_tick(T0 + 30 * DAY - 60) == []                           # ещё не срок
    assert p.trash_tick(T0 + 30 * DAY + 60) == []                           # срок вышел, но час не прошёл
    clock(monkeypatch, T0 + 28 * DAY)                                       # API считает «сейчас» по chat_trash.time
    tr = {x["id"]: x for x in call(base, "/api/chat/trash", tok=tok)[1]["trash"]}
    assert tr[a["id"]]["warn"] and tr[a["id"]]["days_left"] == 2 and tr[a["id"]]["purge_at"] == T0 + 30 * DAY
    assert not tr[b["id"]]["warn"] and tr[b["id"]]["days_left"] == 7
    assert call(base, "/api/chat/trash", tok=tok)[1]["keep_days"] == 30
    assert p.trash_tick(T0 + 30 * DAY + 3540) == [a["id"]]                  # час прошёл — стёрта только старая
    p._trash_at = 0.0
    assert p.trash_tick(T0 + 30 * DAY + 3600) == []                         # больше ничего старше 30 дней
    # перед показом корзины просроченное стирается и не показывается, даже если тик ещё не дошёл
    clock(monkeypatch, T0 + 35 * DAY)
    assert call(base, "/api/chat/trash", tok=tok)[1]["trash"] == []
    assert not (chat_trash.base(p.cfg.data) / b["id"]).exists()
