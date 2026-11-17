"""OpenCode и Hermes окном в пульте (владелец 17.11): журналы в SQLite читаются только на чтение — лента, модель,
статус хода, ответы для Telegram; новое окно и «Продолжить» — своей командой; без id — сессия папки окна."""

import json
import sqlite3

from gas_pult import agent_dbs, harness


def oc_db(path, d="/srv/shop"):
    c = sqlite3.connect(path)
    c.execute("create table session (id text, project_id text, workspace_id text, parent_id text, slug text,"
              " directory text, path text, title text, version text, time_updated integer)")
    c.execute("create table message (id text, session_id text, time_created integer, time_updated integer, data text)")
    c.execute("create table part (id text, message_id text, session_id text, time_created integer,"
              " time_updated integer, data text)")
    c.execute("insert into session values ('ses_old0000001',0,0,null,'','/srv/shop','','',0,1)")
    c.execute("insert into session values ('ses_new0000002',0,0,null,'',?, '','',0,2)", (d,))
    msgs = [("m1", {"role": "user", "time": {"created": 1794900000000}}, [{"type": "text", "text": "привет"}]),
            ("m2", {"role": "assistant", "time": {"created": 1794900005000, "completed": 1794900009000},
                    "providerID": "openrouter", "modelID": "deepseek/deepseek-v4-pro", "finish": "stop"},
             [{"type": "reasoning", "text": "думаю"}, {"type": "text", "text": "Готово"}]),
            ("m3", {"role": "user", "time": {"created": 1794900100000}}, [{"type": "text", "text": "ещё"}])]
    for n, (mid, m, parts) in enumerate(msgs):
        c.execute("insert into message values (?,?,?,?,?)", (mid, "ses_new0000002", n, n, json.dumps(m)))
        for k, pt in enumerate(parts):
            c.execute("insert into part values (?,?,?,?,?,?)", (f"{mid}p{k}", mid, "ses_new0000002", n, n,
                                                                 json.dumps(pt)))
    c.commit()
    c.close()


def hermes_db(path):
    c = sqlite3.connect(path)
    c.execute("create table sessions (id text, cwd text, model text, parent_session_id text, started_at real,"
              " last_activity_at real, transcript_revision integer, message_count integer)")
    c.execute("create table messages (id integer primary key, session_id text, role text, content text,"
              " timestamp real, finish_reason text)")
    c.execute("insert into sessions values ('local-abc123', '/srv/shop', 'openrouter/glm-5.3', null, 1, 2, 7, 3)")
    for role, txt, ts, fin in (("user", "привет", 1794900000, None), ("tool", "{}", 1794900001, None),
                               ("assistant", "Готово", 1794900005, "stop")):
        c.execute("insert into messages (session_id, role, content, timestamp, finish_reason) values (?,?,?,?,?)",
                  ("local-abc123", role, txt, ts, fin))
    c.commit()
    c.close()


def test_opencode_journal(tmp_path):
    db = tmp_path / "opencode.db"
    oc_db(db)
    oc = harness.OpenCode(db)
    ref = oc.journal("/srv/shop")
    assert ref.sid == "ses_new0000002"                                   # самая свежая сессия папки
    items, more = oc.history("/srv/shop")
    assert [(x["role"], x["text"]) for x in items] == [("user", "привет"), ("assistant", "Готово"), ("user", "ещё")]
    assert not more and "думаю" not in json.dumps(items)                  # рассуждения — не в ленту
    assert oc.last_model("/srv/shop") == "openrouter/deepseek/deepseek-v4-pro"
    assert oc.status(ref) == {"phase": "working"}                         # последним — вопрос человека
    assert [t for _, t in oc.answers_at(ref)] == ["Готово"]
    assert oc.revision("/srv/shop") and oc.journal("/nowhere") is None
    assert oc.launch.__self__ is oc
    oc.binary = lambda: "/usr/bin/opencode"
    assert oc.launch("", resume=True) == "/usr/bin/opencode -c"
    assert oc.launch("ses_new0000002", resume=True) == "/usr/bin/opencode -s ses_new0000002"
    assert oc.launch("") == "/usr/bin/opencode"


def test_hermes_journal(tmp_path):
    db = tmp_path / "state.db"
    hermes_db(db)
    hm = harness.Hermes(db)
    ref = hm.journal("/srv/shop")
    items, _ = hm.history("/srv/shop")
    assert [(x["role"], x["text"]) for x in items] == [("user", "привет"), ("assistant", "Готово")]   # без tool
    assert hm.status(ref) == {"phase": "done"} and hm.answers_at(ref)[0][1] == "Готово"
    assert hm.usage(ref) == {"provider": "openrouter", "model": "glm-5.3", "used": None}
    hm.binary = lambda: "/usr/bin/hermes"
    assert hm.launch("local-abc123", resume=True) == "/usr/bin/hermes --resume local-abc123"
    assert hm.launch("", resume=True) == "/usr/bin/hermes -c"


def test_detect_and_safe_sid():
    assert harness.detect(["/usr/bin/python3", "/home/u/.local/bin/hermes"]).name == "hermes"
    assert harness.detect(["/home/u/.local/bin/opencode"]).name == "opencode"
    assert agent_dbs.valid_sid("x; rm -rf /") == "" and agent_dbs.valid_sid("ses_e329e5d7dffe4") == "ses_e329e5d7dffe4"
    assert set(harness.JOURNAL_ONLY) == {"pi", "opencode", "hermes"}
