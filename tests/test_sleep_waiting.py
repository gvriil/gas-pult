"""GAS-25 п.2: сессия, которая ждёт ответа дольше sleep_after_min минут, засыпает — claude-sleep auto с этим порогом
(он сам не трогает занятые и «не усыплять»); 0 — выключено; claude-sleep нет — ничего."""

from gas_pult import tmux


def test_sleep_waiting_runs_auto_with_threshold(monkeypatch):
    calls = []
    monkeypatch.setattr(tmux, "sleeper", lambda: "/usr/bin/claude-sleep")
    def popen(args, env, **kw):
        calls.append((args, env["CLAUDE_SLEEP_HOURS"]))
    monkeypatch.setattr(tmux.subprocess, "Popen", popen)
    assert tmux.sleep_waiting(30) and calls == [(["/usr/bin/claude-sleep", "auto"], "0.500")]
    assert not tmux.sleep_waiting(0)
    monkeypatch.setattr(tmux, "sleeper", lambda: "")
    assert not tmux.sleep_waiting(30) and len(calls) == 1


def test_config_default_and_example():
    from pathlib import Path

    from gas_pult.config import Config
    assert Config(token="1:T", owners=[1]).sleep_after_min == 0     # владелец 24.11: чаты не спят
    assert "sleep_after_min = 0" in (Path(__file__).resolve().parents[1] / "config.example.toml").read_text()
