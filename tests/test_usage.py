"""Расход сессий (usage.py): журналы, цены, пулы, лимиты и пауза.

Журналы — во временной папке с выдуманными путями; живой tmux и настоящий claude не трогаются (методы подменены)."""

import contextlib
import json
import re
import threading
import urllib.error
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import bot, usage, webapp, webauth
from gas_pult.config import Config

OWNER, MEMBER, VIEWER = 1001, 1002, 1003
TODAY = date.today().isoformat()
NOW = f"{TODAY}T12:00:00Z"


def answer(mid, model="claude-opus-5-5", ts=NOW, side=False, **u):
    usage_ = {"input_tokens": 10, "output_tokens": 100, "cache_creation_input_tokens": 0,
              "cache_read_input_tokens": 0, **u}
    return {"type": "assistant", "timestamp": ts, "isSidechain": side, "requestId": f"req_{mid}",
            "message": {"id": mid, "model": model, "role": "assistant", "content": [], "usage": usage_}}


def write(f, *entries, mode="w"):
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, mode) as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")


def folder(projects, path):
    return projects / re.sub(r"[^A-Za-z0-9]", "-", path)


# ---------- цены ----------

def test_model_key_and_prices():
    assert usage.model_key("anthropic/claude-haiku-5.5") == "claude-haiku-5-5"      # OpenRouter
    assert usage.model_key("claude-opus-5-5[1m]") == "claude-opus-5-5"
    assert usage.model_key("claude-opus-5-20260101") == "claude-opus-5"
    assert usage.model_key("glm-5.3") == "glm-5.3"
    # Opus 5.5: $4 ввод, $20 вывод, $0.20 чтение кэша; запись кэша 5 мин — ×1.25, 1 ч — ×2
    u = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000,
         "cache_creation_input_tokens": 2_000_000,
         "cache_creation": {"ephemeral_5m_input_tokens": 1_000_000, "ephemeral_1h_input_tokens": 1_000_000}}
    assert usage.cost("claude-opus-5-5", u) == pytest.approx(4 + 20 + 0.2 + 5 + 8)
    assert usage.cost("claude-opus-5-5", {**u, "speed": "fast"}) == pytest.approx(2 * (4 + 20 + 0.2 + 5 + 8))
    # без разбивки — вся запись кэша по 5 минутам
    assert usage.cost("claude-sonnet-5-5", {"cache_creation_input_tokens": 1_000_000}) == pytest.approx(2.5)


def test_haiku_long_prompt_and_unknown_model():
    short = {"input_tokens": 100_000, "output_tokens": 1_000_000}
    assert usage.cost("claude-haiku-5-5", short) == pytest.approx(0.01 + 0.5)
    long = {"input_tokens": 100_001, "output_tokens": 1_000_000}
    assert usage.cost("claude-haiku-5-5", long) == pytest.approx(100_001 * 0.5 / 1e6 + 2.5)
    assert usage.cost("glm-5.3", short) is None and usage.cost("claude-unknown-9", short) is None
    acc = usage.add(usage.empty(), usage.tokens(short), None)
    pub = usage.public(acc)
    assert pub["usd"] is None and pub["unknown"] and pub["tokens"]["out"] == 1_000_000   # токены есть, цены нет


# ---------- журналы ----------

def test_duplicate_ids_counted_once_and_cache_tokens(tmp_path):
    f = tmp_path / "p" / "s1.jsonl"
    write(f, answer("m1", output_tokens=50), answer("m1", output_tokens=50),          # одно сообщение — три строки
          answer("m1", output_tokens=80, cache_read_input_tokens=1000, cache_creation_input_tokens=200),
          {"type": "user", "message": {"content": "привет"}},
          answer("m2", model="<synthetic>"))                                         # служебные — не считаем
    m = usage.Meter(tmp_path)
    t = m.read(f).total
    assert (t["in"], t["out"], t["cr"], t["cw"]) == (10, 80, 1000, 200)
    want = (10 * 4 + 80 * 20 + 1000 * 0.2 + 200 * 4 * 1.25) / 1e6
    assert t["usd"] == pytest.approx(want)


def test_incremental_read_by_offset(tmp_path, monkeypatch):
    f = tmp_path / "p" / "s1.jsonl"
    write(f, answer("m1"))
    m = usage.Meter(tmp_path)
    assert m.read(f).total["out"] == 100
    reads = []
    real = open

    def spy(path, mode="r", *a, **k):
        fh = real(path, mode, *a, **k)
        if "b" in mode:
            orig = fh.read
            fh.read = lambda n=-1: reads.append(n) or orig(n)
        return fh
    monkeypatch.setattr("builtins.open", spy)
    assert m.read(f).total["out"] == 100 and reads == []                 # не изменился — не читаем
    with real(f, "a") as fh:
        fh.write(json.dumps(answer("m2", output_tokens=7)) + "\n" + '{"type": "assist')   # недописанная строка
    assert m.read(f).total["out"] == 107
    assert reads and reads[-1] < f.stat().st_size                         # дочитали только хвост
    with real(f, "a") as fh:
        fh.write('ant"}\n')
    assert m.read(f).total["out"] == 107


def test_session_with_subagents_and_day(tmp_path):
    proj = folder(tmp_path, "/srv/demo")
    main = proj / "s1.jsonl"
    write(main, answer("a1", ts="2020-01-01T10:00:00Z"), answer("a2"))
    write(proj / "s1" / "subagents" / "agent-x.jsonl", answer("b1", model="claude-haiku-5-5", side=True))
    m = usage.Meter(tmp_path)
    s = m.session("/srv/demo")
    assert s["id"] == "s1" and s["total"]["out"] == 300 and s["today"]["out"] == 200   # старая запись — не сегодня
    assert s["model"] == "Opus 5.5"
    write(folder(tmp_path, "/srv/other") / "s9.jsonl", answer("c1", output_tokens=1))   # сессия вне пульта
    assert m.day(fresh=True)["out"] == 201


# ---------- пулы: чужие учётки в общий пул не собираем ----------

@pytest.fixture
def panel(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    p = webapp.Panel(Config(token="1:T", owners=[OWNER]))
    p.people.add(MEMBER, "member", "Алекс")
    p.people.add(VIEWER, "viewer")
    for uid in (OWNER, MEMBER, VIEWER):
        p.people.accept(uid)
        p.people.set_country(uid, chosen="NL")
    owner_projects = tmp_path / "owner" / "projects"
    p.pult.meter = usage.Meter(owner_projects)
    monkeypatch.setattr(bot.Pult.actor, "uid", None, raising=False)    # кто действует — от прошлых тестов не тянем
    state = {}
    monkeypatch.setattr(p.pult, "state", lambda: {**bot.DEFAULTS, **state})
    monkeypatch.setattr(p.pult, "set_state", lambda **kw: state.update(kw))
    member_home = p.pult.claude_dir(MEMBER)
    write(folder(owner_projects, "/srv/a") / "o1.jsonl", answer("o1", output_tokens=1000))
    write(folder(owner_projects, "/srv/b") / "o2.jsonl", answer("o2", output_tokens=2000))
    write(folder(member_home / "projects", "/srv/c") / "m1.jsonl", answer("m1", output_tokens=4000))
    wins = [{"id": "@1", "name": "a", "path": "/srv/a", "cmd": "claude", "mark": "claude", "by": str(OWNER)},
            {"id": "@2", "name": "b", "path": "/srv/b", "cmd": "claude", "mark": "claude", "by": str(MEMBER)},
            {"id": "@3", "name": "c", "path": "/srv/c", "cmd": "claude", "mark": "claude", "by": str(MEMBER)}]
    # @2 участник открыл на учётке владельца (общая сессия папки), @3 — на своей папке Claude
    monkeypatch.setattr(p.pult, "home_of", lambda w: member_home if w["id"] == "@3" else None)
    for t in (p.tmux, p.pult.tmux):
        monkeypatch.setattr(t, "windows", lambda: [dict(w, channel=False, profile="claude") for w in wins])
        monkeypatch.setattr(t, "window", lambda wid: next((dict(w) for w in wins if w["id"] == wid), None))
        monkeypatch.setattr(t, "screen", lambda wid, n=25: ["esc to interrupt"] if wid == "@1" else ["❯ "])
        monkeypatch.setattr(t, "run", lambda *a, **k: "")
    monkeypatch.setattr(webapp.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "main"})())
    p.state = state
    return p


def test_pools_split_owner_and_member(panel):
    own = {s["id"]: s for s in panel.sessions("owner")}
    assert own["@1"]["cost"]["tokens"]["out"] == 1000 and own["@2"]["cost"]["tokens"]["out"] == 2000
    assert own["@2"]["cost"]["by"] == {"id": MEMBER, "name": "Алекс"}       # открыл участник на учётке владельца
    assert own["@3"]["cost"] is None                                       # учётка участника — не владельцу
    mine = {s["id"]: s for s in panel.sessions(str(MEMBER))}
    assert mine["@3"]["cost"]["tokens"]["out"] == 4000
    assert mine["@1"]["cost"] is None and mine["@2"]["cost"] is None       # расход владельца участнику не виден
    assert all(s["cost"] is None for s in panel.sessions(None))            # наблюдателю — ничей
    assert panel.cost_summary("owner")["today"]["tokens"]["out"] == 3000   # участника в пуле владельца нет
    assert panel.cost_summary(str(MEMBER))["today"]["tokens"]["out"] == 4000
    assert "limits" not in panel.cost_summary(str(MEMBER))


# ---------- лимиты ----------

def test_limits_off_by_default_nothing_happens(panel, monkeypatch):
    sent = []
    monkeypatch.setattr(panel.pult, "broadcast", lambda text, **kw: sent.append(text))
    panel.pult.cost_watch(panel.pult.state(), force=True)
    assert sent == [] and not panel.state.get("cost_paused")
    assert usage.limits({}) == {"session": None, "day": None}


def test_session_limit_pauses_once_and_blocks_text(panel, monkeypatch):
    sent, keys = [], []
    monkeypatch.setattr(panel.pult, "broadcast", lambda text, **kw: sent.append((text, kw)))
    monkeypatch.setattr(panel.pult.tmux, "keys", lambda wid, *k: keys.append((wid, k)))
    # @1: 1000 ответа Opus 5.5 = 10*4/1e6 + 1000*20/1e6 ≈ $0.02; лимит сессии $0.01
    panel.state["cost_limits"] = {"session": 0.01}
    for _ in range(3):                                                     # три обхода монитора — один вопрос
        panel.pult.cost_watch(panel.pult.state(), force=True)
    assert set(panel.state["cost_paused"]) == {"@1", "@2"} and len(sent) == 2
    text, kw = next(x for x in sent if "«a»" in x[0])
    assert "$0.02" in text and "$0.01" in text
    data = [b["callback_data"] for b in kw["reply_markup"]["inline_keyboard"][0]]
    assert data == ["cost:go:@1", "cost:stop:@1"]
    assert keys == [("@1", ("Escape",))]                                   # занятое окно — Esc, свободное — нет
    assert panel.state["cost_paused"]["@1"]["interrupted"]
    with pytest.raises(bot.NotReady, match="паузе по расходу"):
        panel.pult.to_claude(panel.tmux.window("@1"), "ещё")
    s = {x["id"]: x for x in panel.sessions("owner")}
    assert s["@1"]["cost_paused"] and s["@1"]["cost"]["paused"]["kind"] == "session"


def test_day_limit_once_only_owner_pool(panel, monkeypatch):
    sent = []
    monkeypatch.setattr(panel.pult, "broadcast", lambda text, **kw: sent.append(text))
    monkeypatch.setattr(panel.pult.tmux, "keys", lambda *a: None)
    panel.state["cost_limits"] = {"day": 0.05}            # пул владельца: 3000 вывода ≈ $0.06; участник — отдельно
    for _ in range(2):
        panel.pult.cost_watch(panel.pult.state(), force=True)
    assert set(panel.state["cost_paused"]) == {"@1", "@2"} and len(sent) == 2   # @3 — учётка участника
    assert all("за сегодня" in t for t in sent)


def test_buttons_continue_and_stop(panel, monkeypatch):
    sent, pasted = [], []
    monkeypatch.setattr(panel.pult, "broadcast", lambda text, **kw: sent.append(text))
    monkeypatch.setattr(panel.pult.tmux, "keys", lambda *a: None)
    monkeypatch.setattr(panel.pult, "hold", lambda wid: contextlib.nullcontext())
    monkeypatch.setattr(panel.pult, "ready_for_text", lambda wid: None)
    monkeypatch.setattr(panel.pult.tmux, "paste", lambda wid, text: pasted.append((wid, text)))
    panel.state["cost_limits"] = {"session": 0.01}
    panel.pult.cost_watch(panel.pult.state(), force=True)
    assert "остаётся на паузе" in panel.pult.cost_decide("@2", "stop")
    panel.pult.cost_watch(panel.pult.state(), force=True)
    assert panel.state["cost_paused"]["@2"]["state"] == "stopped" and len(sent) == 2   # после «Остановить» не спамим
    msg = panel.pult.cost_decide("@1", "go")
    assert "пауза снята" in msg and "@1" not in panel.state["cost_paused"]
    assert pasted == [("@1", "Продолжай с того места, где остановился.")]   # ход прерывали — просим продолжить
    sid = next(iter(panel.state["cost_extra"]))
    assert panel.state["cost_extra"][sid] >= 0.01
    panel.pult.cost_watch(panel.pult.state(), force=True)
    assert "@1" not in panel.state["cost_paused"] and len(sent) == 2       # лимит поднят — снова не спрашиваем
    with pytest.raises(LookupError):
        panel.pult.cost_decide("@1", "go")
    panel.state["cost_limits"] = {}                                        # лимиты сняли — паузы снимаются
    panel.pult.cost_watch(panel.pult.state(), force=True)
    assert panel.state["cost_paused"] == {}


def test_bot_callback_cost(panel, monkeypatch):
    out = []
    p = panel.pult
    monkeypatch.setattr(p, "api", lambda *a, **k: {})
    monkeypatch.setattr(p, "send", lambda chat, text, **kw: out.append(text) or {})
    monkeypatch.setattr(p, "broadcast", lambda text, **kw: None)
    monkeypatch.setattr(p.tmux, "keys", lambda *a: None)
    panel.state["cost_limits"] = {"session": 0.01}
    p.cost_watch(p.state(), force=True)
    q = {"id": "1", "from": {"id": OWNER}, "message": {"chat": {"id": OWNER}}, "data": "cost:stop:@2"}
    p.on_callback(q)
    assert "остаётся на паузе" in out[-1]
    p.on_callback({**q, "from": {"id": MEMBER}, "data": "cost:go:@2"})     # не владелец — кнопка не работает
    assert panel.state["cost_paused"]["@2"]["state"] == "stopped"


def test_check_limits_values():
    assert usage.check_limits({"session": "2,5", "day": ""}) == {"session": 2.5, "day": None}
    with pytest.raises(ValueError):
        usage.check_limits({"day": "много"})
    with pytest.raises(ValueError):
        usage.check_limits({"day": -1})


# ---------- API ----------

def call(base, path, body=None, token=""):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={token}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r), ""
    except urllib.error.HTTPError as e:
        return e.code, json.load(e), ""


def test_api_limits_owner_only(panel):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        owner, member = panel.auth.issue(OWNER), panel.auth.issue(MEMBER)
        assert call(base, "/api/cost/limits", {"session": 3, "day": 10}, member)[0] == 403
        assert call(base, "/api/cost/limits", None, member)[0] == 403
        assert call(base, "/api/cost/decide", {"w": "@1", "act": "go"}, member)[0] == 403
        code, d, _ = call(base, "/api/cost/limits", {"session": 3, "day": 10}, owner)
        assert code == 200 and d["limits"] == {"session": 3.0, "day": 10.0}
        code, d, _ = call(base, "/api/sessions", None, member)
        assert code == 200 and d["cost"]["pool"] == "own" and "limits" not in d["cost"]
        code, d, _ = call(base, "/api/sessions", None, owner)
        assert code == 200 and d["cost"]["limits"]["day"] == 10.0 and d["cost"]["today"]["usd"] > 0
    finally:
        srv.shutdown()


def test_fresh_window_without_journal_and_owner_mark(panel, tmp_path):
    from gas_pult import people
    assert panel.model_of("/srv/none", "") == "" and panel.preview("/srv/none", "") == ""   # журнала ещё нет
    # окно владельца помечено его ID (для запасных), но своей папки у владельца нет — это учётка владельца
    assert people.home_of({"by": str(OWNER)}, tmp_path / "data") is None
    data = tmp_path / "data"
    assert people.home_of({"by": str(MEMBER)}, data) == data / "people" / str(MEMBER) / "claude"
