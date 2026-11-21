"""R13 (аудит 21.11, группа A): пульт читает журнал окна через адаптер агента (``harness.of(w)``), а не напрямую
через ``transcripts`` — у окна Pi (OpenCode, Hermes) название, превью, модель, статус, лента команд и удаление чата
берутся из его журнала. У Claude Code поведение то же: адаптер ``ClaudeCode`` вызывает те же функции."""

from pathlib import Path

import pytest

from gas_pult import activity, commands, harness, transcripts, webapp
from gas_pult.config import Config

SID = "11111111-2222-3333-4444-555555555555"
PI_FILE = Path("/нет/pi-журнал.jsonl")


@pytest.fixture
def pi(monkeypatch):
    """Адаптер Pi с поддельным журналом: что спросили — записываем."""
    h = harness.HARNESSES["pi"]
    calls = []

    def log(name, value):
        def f(*a, **k):
            calls.append((name, a, k))
            return value
        return f
    monkeypatch.setattr(h, "journal", log("journal", PI_FILE), raising=False)
    feed = [{"role": "assistant", "text": "Готово.\n```bash\nls -la\n```", "ts": 2},
            {"role": "user", "text": "  Собери   отчёт  ", "ts": 1}]
    monkeypatch.setattr(h, "history", log("history", (feed, False)), raising=False)
    monkeypatch.setattr(h, "preview", log("preview", "Pi: читаю файлы"), raising=False)
    monkeypatch.setattr(h, "last_model", log("last_model", "glm-4.6"), raising=False)
    monkeypatch.setattr(h, "last_answer", log("last_answer", "ответ Pi"), raising=False)
    monkeypatch.setattr(h, "revision", log("revision", "pi-rev-1"), raising=False)
    monkeypatch.setattr(h, "status", log("status", {"phase": "done", "text": "Pi закончил"}), raising=False)
    return h, calls


@pytest.fixture
def no_claude(monkeypatch):
    """Журнал Claude Code для окна Pi трогать нельзя."""
    for name in ("current", "preview", "last_model", "history", "revision", "last_answer"):
        monkeypatch.setattr(transcripts, name, lambda *a, _n=name, **k: pytest.fail(f"transcripts.{_n} у окна Pi"))


def panel(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    return webapp.Panel(Config(token="1:T", owners=[1]))


def test_chat_title_pi_first_user_message(tmp_path, monkeypatch, pi, no_claude):     # webapp.py chat_title
    p = panel(tmp_path, monkeypatch)
    assert p.chat_title({}, "/w", None, SID, pi[0]) == "Собери отчёт"
    assert p.chat_title({"sessions": {SID: {"title": "Своё"}}}, "/w", None, SID, pi[0]) == "Своё"


def test_chat_title_claude_unchanged(tmp_path, monkeypatch):
    p = panel(tmp_path, monkeypatch)
    monkeypatch.setattr(transcripts, "current", lambda path, home, sid: Path("/c.jsonl"))
    monkeypatch.setattr(webapp.projects, "title_of", lambda f: "из summary")
    assert p.chat_title({}, "/w", None, SID) == "из summary"


def test_open_sids_legacy_window_uses_its_harness(tmp_path, monkeypatch, pi, no_claude):   # webapp.py open_sids
    p = panel(tmp_path, monkeypatch)
    monkeypatch.setattr(p, "project_data", lambda *a, **k: {})
    monkeypatch.setattr(p.projects, "of_path", lambda d, path: "p1")
    monkeypatch.setattr(p.tmux, "windows", lambda: [{"id": "@5", "path": "/w", "harness": "pi"}])
    assert p.open_sids({"id": "p1"}) == ({}, {str(PI_FILE)})


def test_window_journal_uses_its_harness(tmp_path, monkeypatch, pi, no_claude):        # webapp.py window_journal
    p = panel(tmp_path, monkeypatch)
    monkeypatch.setattr(p.tmux, "windows", lambda: [])
    assert p.window_journal({"id": "@5", "path": "/w", "harness": "pi", "sid": SID}) == PI_FILE
    assert p.window_journal({"id": "@5", "path": "/w", "harness": "pi"}) == PI_FILE
    assert [c[0] for c in pi[1]] == ["journal", "journal"]


def test_model_of_pi_raw_claude_pretty(tmp_path, monkeypatch, pi):                    # webapp.py model_of
    p = panel(tmp_path, monkeypatch)
    assert p.model_of("/w", "r1", None, SID, pi[0]) == "glm-4.6"                      # без model_title Claude
    monkeypatch.setattr(transcripts, "last_model", lambda path, home=None, sid="": "claude-opus-5-5")
    monkeypatch.setattr(transcripts, "model_title", lambda m: "Opus 5.5" if m == "claude-opus-5-5" else m)
    assert p.model_of("/w", "r1", None, SID) == "Opus 5.5"                            # Claude Code — как раньше


def test_preview_uses_harness(tmp_path, monkeypatch, pi, no_claude):                   # webapp.py preview
    p = panel(tmp_path, monkeypatch)
    assert p.preview("/w", "r1", None, SID, pi[0]) == "Pi: читаю файлы"


def test_commands_collect_reads_pi_feed(tmp_path, pi, no_claude):                     # commands.py _collect
    j = commands.Journal(tmp_path / "cmds.json")
    w = {"id": "@5", "name": "pi-1", "path": "/w", "harness": "pi", "sid": SID}
    assert j.collect([w], lambda cmd: "local") is True
    assert any("ls -la" in str(x) for x in j.load()["items"].values())
    assert {c[0] for c in pi[1]} >= {"revision", "history"}


def test_tgbiz_answer_goes_through_claude_adapter(monkeypatch):                       # tgbiz_bot.py answer
    from gas_pult import config, tgbiz_bot, tmux
    seen = {}
    monkeypatch.setattr(config, "load", lambda: Config(token="1:T", owners=[1]))
    monkeypatch.setattr(tmux, "Tmux", lambda *a, **k: object())

    class Acts:
        def status(self, path, home, sid, h=None):
            seen["h"] = h.name
            return {"phase": "done"}
    monkeypatch.setattr(activity, "Journal", Acts)
    cc = harness.HARNESSES["claude"]
    monkeypatch.setattr(cc, "last_answer", lambda path, home=None, sid="": "ответ", raising=False)
    monkeypatch.setattr(cc, "revision", lambda path, home=None, sid="": "rev", raising=False)
    assert tgbiz_bot._journalist().answer("/w", SID) == (True, "ответ", "rev")
    assert seen["h"] == "claude"


def test_activity_status_pi_from_its_journal(pi, no_claude):                          # activity.py status
    st = activity.Journal().status("/w", None, SID, pi[0])
    assert st == {"phase": "done", "text": "Pi закончил"}
    assert [c[0] for c in pi[1]] == ["journal", "status"]


def test_activity_status_claude_unchanged(monkeypatch):
    monkeypatch.setattr(transcripts, "current", lambda path, home, sid: None)
    assert activity.Journal().status("/w", None, SID, harness.of(None))["phase"] == activity.parse([])["phase"]
    assert activity.Journal().status("/w")["phase"] == activity.parse([])["phase"]
