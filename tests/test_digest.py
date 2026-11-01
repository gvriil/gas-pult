"""Утренняя сводка «ждёт владельца»: что попадает, кнопки, «позже»/«закрыть», расписание, подтверждение слияния."""

import json
import subprocess
import time
from datetime import datetime

from gas_pult import bot, digest


def gh_reply(*prs):
    nodes = [{"number": n, "title": t, "url": f"https://x/{n}", "createdAt": created, "mergeable": m,
              "repository": {"nameWithOwner": "me/repo"},
              "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": ci} if ci else None}}]}}
             for n, t, created, ci, m in prs]
    return json.dumps({"data": {"search": {"nodes": nodes}}})


def test_prs_old_or_red_only(monkeypatch):
    now = datetime.fromisoformat("2026-11-01T09:00:00+00:00").timestamp()
    out = gh_reply((1, "свежий зелёный", "2026-10-31T20:00:00Z", "SUCCESS", "MERGEABLE"),
                   (2, "свежий красный", "2026-10-31T20:00:00Z", "FAILURE", "MERGEABLE"),
                   (3, "старый", "2026-10-28T10:00:00Z", "SUCCESS", "MERGEABLE"),
                   (4, "старый с конфликтом", "2026-10-20T10:00:00Z", "SUCCESS", "CONFLICTING"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, out, ""))
    got = {x["n"]: x for x in digest.prs("me", now)}
    assert set(got) == {2, 3, 4}
    assert not got[2]["ok"] and got[3]["ok"] and not got[4]["ok"]     # слить можно только зелёный без конфликта
    assert got[3]["age"] == 3


def test_handoff_waiting_yes_with_subitems(tmp_path):
    proj = tmp_path / "shop"
    proj.mkdir()
    (proj / "HANDOFF.md").write_text("# HANDOFF\n- Ждут «да» владельца:\n  - #5 — выкатить витрину;\n  - #6 — оплата.\n"
                                     "- Прошлое: выкачено по «да» владельца.\n")
    wt = tmp_path / "shop-wt"                                          # рабочая копия worktree — не штаб
    wt.mkdir()
    (wt / ".git").write_text("gitdir: ../shop/.git/worktrees/x")
    (wt / "HANDOFF.md").write_text("- Ждёт «да»: дубль\n")
    got = digest.handoffs([tmp_path])
    assert [x["project"] for x in got] == ["shop"]
    assert got[0]["text"] == "Ждут «да» владельца: #5 — выкатить витрину; #6 — оплата."


def test_later_and_close_hide_items(tmp_path):
    d = digest.Digest(tmp_path / "digest.json")
    a, b = {"kind": "yes", "key": "a"}, {"kind": "yes", "key": "b"}
    assert d.fresh([a, b], time.time()) == [a, b]
    d.snooze("a", digest.LATER)
    assert d.fresh([a, b], time.time()) == [b]
    assert d.fresh([a, b], time.time() + digest.LATER + 1) == [a, b]  # «позже» — вернулся в следующей сводке


def test_due_once_a_day(tmp_path):
    d = digest.Digest(tmp_path / "digest.json")
    assert not d.due("09:00", datetime(2026, 11, 1, 8, 59))
    assert d.due("09:00", datetime(2026, 11, 1, 9, 0))
    d.mark_sent("2026-11-01")
    assert not d.due("09:00", datetime(2026, 11, 1, 15, 0))
    assert d.due("09:00", datetime(2026, 11, 2, 9, 1))
    assert not d.due("", datetime(2026, 11, 2, 9, 1))                 # выключено


def test_render_buttons():
    text, kbd = digest.render([
        {"kind": "pr", "key": "p1", "repo": "me/r", "n": 7, "title": "T", "url": "https://x/7", "age": 3,
         "ci": "SUCCESS", "ok": True},
        {"kind": "pr", "key": "p2", "repo": "me/r", "n": 8, "title": "R", "url": "https://x/8", "age": 0,
         "ci": "FAILURE", "ok": False},
        {"kind": "win", "key": "w1", "id": "@1", "name": "shop-1"}])
    assert "CI красный" in text and "открыт 3 дн." in text and "Окно «shop-1»" in text
    rows = kbd["inline_keyboard"]
    assert rows[0][0]["callback_data"] == "dg:y:p1" and rows[1][0]["url"] == "https://x/8"   # красный — не слить
    assert all(len(r) == 3 for r in rows) and all(len(b.get("callback_data", "")) <= 64 for r in rows for b in r)


def make(tmp_path, monkeypatch):
    p = bot.Pult.__new__(bot.Pult)
    p.cfg = type("C", (), {"owners": [1]})()
    p.digest = digest.Digest(tmp_path / "digest.json")
    p.sent = []
    p.send = lambda chat, text, **kw: p.sent.append((text, kw))
    return p


def test_merge_needs_confirmation(tmp_path, monkeypatch):
    p = make(tmp_path, monkeypatch)
    x = {"kind": "pr", "key": "p1", "repo": "me/r", "n": 7, "title": "T", "url": "u", "age": 3, "ci": "SUCCESS",
         "ok": True}
    p.digest.fresh([x], time.time())
    merged = []
    monkeypatch.setattr(digest, "merge", lambda repo, n: merged.append((repo, n)) or "✅ Слито")
    p.on_digest(1, "y:p1")
    assert merged == [] and "Слить me/r#7" in p.sent[-1][0]            # первое касание — только вопрос
    p.on_digest(1, "Y:p1")
    assert merged == [("me/r", 7)]
    assert p.digest.fresh([x], time.time()) == []                     # слитый больше не показываем


def test_yes_goes_to_project_window(tmp_path, monkeypatch):
    p = make(tmp_path, monkeypatch)
    x = {"kind": "yes", "key": "h1", "project": "shop", "path": "/p/shop", "text": "Ждут «да»: #5"}
    p.digest.fresh([x], time.time())
    pasted = []
    p.project_window = lambda path: {"id": "@3", "name": "shop-1"} if path == "/p/shop" else None
    p.to_claude = lambda w, text: pasted.append((w["id"], text))
    p.on_digest(1, "Y:h1")
    assert pasted == [("@3", "Владелец отвечает «да» на пункт из HANDOFF.md: Ждут «да»: #5")]
