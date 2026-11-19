"""Предохранитель цепочек (GAS-25 п.3): пинг-понг двух окон > 8 раз, шаг ≤ 2 мин, без человека — цепочка."""

import json

from gas_pult import chainfuse as cf


def pingpong(n, a="@1", b="@2", step=30, t0=1000.0):
    return [(t0 + i * step, a if i % 2 == 0 else b, "agent") for i in range(n)]


def test_ping_pong_over_limit_found():
    r = cf.detect(pingpong(9))
    assert len(r) == 1 and {r[0]["a"], r[0]["b"]} == {"@1", "@2"} and r[0]["n"] == 9 and r[0]["last"] == "@1"


def test_not_chain_cases():
    assert cf.detect(pingpong(8)) == []                                   # 8 — ещё не цепочка
    assert cf.detect(pingpong(12, step=200)) == []                         # медленно — обычная работа
    one_way = [(1000.0 + i * 10, "@2", "agent") for i in range(20)]        # поручения в одну сторону
    assert cf.detect(one_way) == []
    ev = [*pingpong(12), (1000.0 + 4 * 30 + 5, "@2", "human")]             # человек вмешался посреди
    assert cf.detect(ev) == []
    three = [(1000.0 + i * 10, ("@1", "@2", "@3")[i % 3], "agent") for i in range(15)]   # не пара
    assert cf.detect(three) == []


def test_read_events_peer_and_pult_insert(tmp_path):
    from gas_pult import deliveries
    f = tmp_path / "s.jsonl"
    rows = [{"type": "user", "timestamp": "2026-11-19T10:00:00Z", "origin": {"kind": "peer", "name": "shtap-1"},
             "isMeta": True, "message": {"content": "письмо"}},
            {"type": "user", "timestamp": "2026-11-19T10:00:30Z", "message": {"content": "сделай отчёт"}},
            {"type": "user", "timestamp": "2026-11-19T10:01:00Z", "message": {"content": "вставка tmux"}},
            {"type": "assistant", "timestamp": "2026-11-19T10:01:10Z", "message": {"content": "ok"}}]
    f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
    ev = cf.read_events(f, "@5", 0, {deliveries.sha("сделай отчёт")})
    assert [k for _, _, k in ev] == ["agent", "human", "agent"]


def test_bot_fuse_tick_escape_shtab_and_task(tmp_path, monkeypatch):
    """Пинг-понг @1↔@2 → Escape получателю, текст штабу (он не в паре), задача «ждёт вас» Q1; второй раз — тишина."""
    from gas_pult import bot, deliveries, harness, tasks, transcripts

    class H:
        name = "claude"
    p = bot.Pult.__new__(bot.Pult)
    wins = [{"id": "@1", "name": "shop", "path": "/a"}, {"id": "@2", "name": "site", "path": "/b"},
            {"id": "@9", "name": "shtap-47", "path": "/s"}]
    keys, said = [], []
    p.tmux = type("T", (), {"windows": lambda self: wins, "keys": lambda self, w, *k: keys.append((w, k))})()
    p.deliv = deliveries.Log(tmp_path / "sends.jsonl")
    p.tasks = tasks.Tasks(tmp_path / "tasks.json")
    p.to_claude = lambda w, text, src="": said.append((w["id"], src))
    monkeypatch.setattr(harness, "of", lambda w: H())
    monkeypatch.setattr(transcripts, "current", lambda path, sid="": tmp_path / path.strip("/"))
    now = 100000.0
    monkeypatch.setattr(cf, "read_events", lambda f, wid, since, human: [
        e for e in pingpong(10, t0=now - 400) if e[1] == wid])
    p.fuse_tick(now)
    assert keys == [("@2", ("Escape",))] and said == [("@9", "fuse")]
    t = p.tasks.list()[0]
    assert t["status"] == "waiting" and "shop" in t["title"] and t.get("urgent") and t.get("important")
    p.fuse_tick(now + 60)
    assert len(keys) == 1 and len(p.tasks.list()) == 1                   # та же пара — не раньше чем через 30 мин
