"""Владелец 20.11: «контекст 92 %, а договаривались сжимать автоматически». Окна пульта стартуют с
CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=80 (tmux -e): Claude Code сжимает разговор на 80 % окна авто-сжатия, а не около 967K."""
import subprocess

from gas_pult import tmux


def test_new_and_respawn_windows_get_autocompact_env(monkeypatch):
    runs = []

    def fake(args, **kw):
        runs.append(args)
        return subprocess.CompletedProcess(args, 0, "@9\n", "")
    monkeypatch.setattr(tmux.subprocess, "run", fake)
    monkeypatch.setattr(tmux, "make_room", lambda: None)
    t = tmux.Tmux("main")
    monkeypatch.setattr(t, "ensure_session", lambda: None)
    monkeypatch.setattr(t, "watch_trust", lambda wid: None)
    t.new_window("w", "/tmp", "claude")
    t.respawn("@9", "/tmp", "claude --continue")
    for verb in ("new-window", "respawn-window"):
        a = next(r for r in runs if verb in r)
        i = a.index("-e")
        assert a[i + 1] == "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=80", a
        assert a[-1].startswith("claude")                          # команда — последней, без префикса переменной
