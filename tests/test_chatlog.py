"""GAS-31 (урезанно; владелец 19.11: «логирование всех процессов чата, чтобы заниматься отладкой»): один журнал
chat-events.jsonl — путь сообщения по id, без текста, 0600, 30 дней; устройство и вход; ошибки JS браузера."""

import json
import stat
import time

from test_people_login import call, server  # noqa: F401 — тот же сервер панели

from gas_pult import chatlog


def test_log_no_text_0600_and_prune(tmp_path):
    t = [time.time() - 40 * 86400]
    log = chatlog.Log(tmp_path / "ev.jsonl", clock=lambda: t[0])
    log.event("recv", "m-old", len=5)
    t[0] = time.time()
    log.pruned = 0                                                         # «сутки прошли» — срез старых
    log.event("recv", "m1", w="@1", len=4, sha=chatlog.sha("тест"), note="x" * 500)
    rows = [json.loads(x) for x in (tmp_path / "ev.jsonl").read_text().splitlines()]
    assert [r["mid"] for r in rows] == ["m1"]                              # старше 30 дней — срезано
    assert len(rows[0]["note"]) == chatlog.FIELD_MAX and "тест" not in json.dumps(rows, ensure_ascii=False)
    assert stat.S_IMODE((tmp_path / "ev.jsonl").stat().st_mode) == 0o600
    assert log.trail("m1")[0]["ev"] == "recv"


def test_send_path_logged_by_id(server):  # noqa: F811
    panel, base = server
    owner = panel.auth.issue(1)
    q = "Посчитай выручку за ноябрь по всем магазинам и пришли таблицу"
    call(base, "/api/send", {"w": "@1", "text": q, "id": "m-77"}, owner)
    call(base, "/api/send", {"w": "@1", "text": q, "id": "m-78"}, owner)       # тот же вопрос — стоп кэша
    evs = [r["ev"] for r in panel.events.trail("m-77")]
    assert evs == ["recv", "inserted"]
    rec = panel.events.trail("m-77")[0]
    assert rec["w"] == "@1" and rec["len"] == len(q) and rec["dev"] and rec["via"] and "text" not in rec
    assert [r["ev"] for r in panel.events.trail("m-78")] == ["recv", "repeat_stop"]
    member = panel.auth.issue(3)                                                 # наблюдатель тоже шлёт ошибки JS
    assert call(base, "/api/clientlog", {"kind": "js", "msg": "x is undefined", "at": "index.html:10",
                                         "screen": "session"}, member)[0] == 200
    err = [r for r in map(json.loads, panel.events.path.read_text().splitlines()) if r["ev"] == "js_error"]
    assert err and err[0]["msg"] == "x is undefined" and err[0]["screen"] == "session"


def test_bot_answer_events(tmp_path):
    """Ответ ушёл в Telegram / не ушёл (с кодом) — в журнал; бот без журнала (собран в тесте) не падает."""
    from gas_pult import bot
    p = bot.Pult.__new__(bot.Pult)
    p.ev("answer_tg", w="@1")                                               # журнала нет — молча
    p.events = chatlog.Log(tmp_path / "ev.jsonl")
    p.ev("answer_tg_fail", w="@1", code="Bad Request: chat not found")
    r = json.loads((tmp_path / "ev.jsonl").read_text())
    assert r["ev"] == "answer_tg_fail" and r["code"].startswith("Bad Request")
