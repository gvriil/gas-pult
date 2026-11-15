"""Провайдер сессий (R13): интерфейс и адаптер Claude Code — поведение то же, что у transcripts/tmux напрямую."""

import json

from gas_pult import harness, tmux, transcripts


def test_detect_claude_and_unknown():
    assert harness.detect(["claude", "--resume", "x"]).name == "claude"
    assert harness.detect(["node", "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js"]).name == "claude"
    assert harness.detect(["bash"]) is None and harness.detect(["vim", "claude.md"]) is None


def test_of_defaults_to_claude():
    assert harness.of(None).name == "claude" and harness.of({}).name == "claude"
    assert harness.of({"harness": "claude"}) is harness.HARNESSES["claude"]
    assert harness.of({"harness": "нет-такого"}).name == "claude"


def test_claude_adapter_same_as_transcripts(tmp_path):
    path, sid = "/home/u/proj", "11111111-1111-4111-8111-111111111111"
    d = transcripts.project_dir(path, tmp_path)
    d.mkdir(parents=True)
    rows = [{"type": "user", "message": {"role": "user", "content": "Привет"}, "timestamp": "2026-11-15T10:00:00Z"},
            {"type": "assistant", "message": {"role": "assistant", "model": "claude-opus-5-5",
                                              "content": [{"type": "text", "text": "Готово."}]},
             "timestamp": "2026-11-15T10:00:05Z"}]
    (d / f"{sid}.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    h = harness.of({"harness": "claude"})
    assert h.journal(path, tmp_path, sid) == transcripts.current(path, tmp_path, sid)
    assert h.history(path, home=tmp_path, sid=sid) == transcripts.history(path, home=tmp_path, sid=sid)
    assert h.preview(path, tmp_path, sid) == transcripts.preview(path, home=tmp_path, sid=sid)
    assert h.last_model(path, tmp_path, sid) == transcripts.last_model(path, home=tmp_path, sid=sid)
    assert h.last_answer(path, tmp_path, sid) == transcripts.last_answer(path, home=tmp_path, sid=sid)
    assert h.revision(path, tmp_path, sid) == transcripts.revision(path, home=tmp_path, sid=sid)
    assert h.resume_args(sid) == f" --resume {sid}" and h.resume_args("") == " --continue"
    assert h.new_args(sid) == f" --session-id {sid}" and h.new_args("не-id") == ""


def test_window_gets_harness_field():
    import inspect
    src = inspect.getsource(tmux.Tmux._windows)
    assert 'w["harness"] = "claude" if claude else ""' in src            # поле только добавлено, логика окна та же


PI_ROWS = [
    {"type": "session", "version": 3, "id": "s1", "timestamp": "2026-11-15T10:00:00.000Z", "cwd": "/home/u/proj"},
    {"type": "message", "id": "a0", "parentId": None, "timestamp": "2026-11-15T10:00:00.000Z",
     "message": {"role": "system", "content": "", "sections": {"preamble": "You are…"}}},
    {"type": "message", "id": "a1", "parentId": "a0", "timestamp": "2026-11-15T10:00:01.000Z",
     "message": {"role": "user", "content": "Сделай отчёт"}},
    {"type": "message", "id": "a2", "parentId": "a1", "timestamp": "2026-11-15T10:00:02.000Z",
     "message": {"role": "assistant", "model": "deepseek-v4-pro", "content": [
         {"type": "thinking", "thinking": "думаю"}, {"type": "text", "text": "Начинаю."},
         {"type": "toolCall", "id": "c1", "name": "bash", "arguments": {"command": "ls"}}]}},
    {"type": "message", "id": "a3", "parentId": "a2", "timestamp": "2026-11-15T10:00:03.000Z",
     "message": {"role": "toolResult", "toolCallId": "c1", "toolName": "bash", "content": [{"type": "text",
                                                                                              "text": "a b"}]}},
    {"type": "model_change", "id": "a4", "parentId": "a3", "timestamp": "2026-11-15T10:00:04.000Z",
     "provider": "x", "modelId": "y"},
    {"type": "message", "id": "a5", "parentId": "a4", "timestamp": "2026-11-15T10:00:05.000Z",
     "message": {"role": "assistant", "model": "deepseek-v4-pro",
                 "content": [{"type": "text", "text": "Готово: **2** файла."}]}},
    {"type": "message", "id": "a6", "parentId": "a5", "timestamp": "2026-11-15T10:00:06.000Z",
     "message": {"role": "custom", "content": "служебное"}},
]


def _pi_journal(root, path="/home/u/proj", sid="11111111-1111-4111-8111-111111111111", rows=PI_ROWS):
    from gas_pult import pi_journal
    d = pi_journal.project_dir(path, root)
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"2026-11-15T10-00-00-000Z_{sid}.jsonl"
    f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\nне json\n")
    return f


def test_pi_journal_dir_name(tmp_path):
    from gas_pult import pi_journal
    assert pi_journal.project_dir("/home/u/my proj", tmp_path).name == "--home-u-my proj--"


def test_pi_adapter_reads_feed(tmp_path):
    sid = "11111111-1111-4111-8111-111111111111"
    f = _pi_journal(tmp_path)
    h = harness.Pi(root=tmp_path)
    assert h.journal("/home/u/proj", sid=sid) == f and h.journal("/home/u/proj") == f
    items, more = h.history("/home/u/proj", sid=sid)
    assert not more and [(x["role"], x["text"]) for x in items] == [
        ("user", "Сделай отчёт"), ("assistant", "Начинаю.\n\nГотово: **2** файла.")]   # ход — одним ответом
    assert items[0]["ts"] == "2026-11-15 10:00" and items[1]["i"] == 1
    assert h.last_model("/home/u/proj", sid=sid) == "deepseek-v4-pro"
    assert h.last_answer("/home/u/proj", sid=sid).endswith("файла.")
    assert h.preview("/home/u/proj", sid=sid) == "Начинаю."
    r = h.revision("/home/u/proj", sid=sid)
    with open(f, "a") as fh:
        fh.write(json.dumps({"type": "message", "timestamp": "2026-11-15T10:01:00Z",
                             "message": {"role": "user", "content": [{"type": "text", "text": "Ещё"}]}}) + "\n")
    assert h.revision("/home/u/proj", sid=sid) != r
    assert h.history("/home/u/proj", sid=sid)[0][-1]["text"] == "Ещё"
    assert h.history("/home/u/proj", limit=1, sid=sid)[1] is True
    assert h.journal("/home/u/other") is None and h.history("/home/u/other") == ([], False)


def test_pi_detect_args_and_live_sid(tmp_path):
    pi = harness.HARNESSES["pi"]
    assert harness.detect(["/home/u/.local/share/pi/node_modules/.bin/pi", "--session-id", "x1"]).name == "pi"
    assert harness.detect(["node", "/x/@earendil-works/pi-coding-agent/dist/bundle/cli.js"]).name == "pi"
    assert harness.detect(["pip", "install"]) is None
    sid = "11111111-1111-4111-8111-111111111111"
    assert pi.new_args(sid) == pi.resume_args(sid) == f" --session-id {sid}"
    assert pi.resume_args("") == " --continue" and pi.new_args("-bad") == ""
    from gas_pult import pi_journal
    assert pi_journal.session_arg(["pi", "--session-id", sid]) == sid
    assert pi_journal.session_arg(["pi", f"--session-id={sid}"]) == sid and pi_journal.session_arg(["pi"]) == ""
    import os
    assert pi.live_sid(os.getpid()) == ""                                   # pytest — не Pi


def test_tmux_detects_pi_window(monkeypatch):
    import inspect
    src = inspect.getsource(tmux.Tmux._windows)
    assert "harness.detect(p[1:])" in src and 'w["stopped"] = not w["harness"]' in src


def test_pi_launch_and_env_sid(monkeypatch, tmp_path):
    import os
    import subprocess
    import sys
    pi = harness.HARNESSES["pi"]
    fake = tmp_path / "pi"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setenv("GAS_PULT_PI", str(fake))
    sid = "11111111-1111-4111-8111-111111111111"
    cmd = pi.launch(sid)
    assert cmd.startswith(f"env GAS_PULT_SID={sid} {fake} --provider deepseek --model deepseek-v4-pro")
    assert cmd.endswith(f" --session-id {sid}") and pi.launch(sid, resume=True).endswith(f" --session-id {sid}")
    assert harness.available() == [{"id": "pi", "title": "Pi", "model": "deepseek/deepseek-v4-pro"}]
    p = subprocess.Popen([sys.executable, "-c", "import time; print('ok', flush=True); time.sleep(5)"],
                         env={**os.environ, "GAS_PULT_SID": sid}, stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "ok"                         # процесс уже запущен (после exec)
        assert pi.live_sid(p.pid) == sid                                   # Pi меняет имя процесса — id из окружения
    finally:
        p.kill()
    monkeypatch.setenv("GAS_PULT_PI", str(tmp_path / "нет"))
    monkeypatch.setattr(harness.shutil, "which", lambda n: None)
    monkeypatch.setattr(harness.Path, "home", lambda: tmp_path)
    assert harness.available() == []
    import pytest
    with pytest.raises(ValueError, match="не установлен"):
        pi.launch(sid)


def test_panel_opens_and_revives_pi_window(monkeypatch, tmp_path):
    from gas_pult import webapp
    fake = tmp_path / "pi"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("GAS_PULT_PI", str(fake))
    made, resp = [], []
    t = type("T", (), {"new_window": lambda self, name, path, cmd, **k: made.append((cmd, k)) or "@9",
                       "respawn": lambda self, wid, path, cmd, mark="": resp.append((cmd, mark)),
                       "window": lambda self, wid: {"id": wid, "path": "/p", "mark": "pi", "stopped": True,
                                                    "sid": "22222222-2222-4222-8222-222222222222"}})()
    p = webapp.Panel.__new__(webapp.Panel)
    p.tmux = t
    p.pult = type("P", (), {"home": "/home/u"})()
    p.mark_by = lambda wid, uid: None
    p.check = lambda profile, uid: None
    r = webapp.Panel.open_in(p, "/home/u/proj", "pi", uid=1)
    cmd, k = made[0]
    assert r["id"] == "@9" and k["mark"] == "pi" and k["sid"] == r["sid"] and f"GAS_PULT_SID={r['sid']}" in cmd
    webapp.Panel.revive(p, "@9", uid=None)
    assert resp[0][1] == "pi" and resp[0][0].endswith("--session-id 22222222-2222-4222-8222-222222222222")
    import pytest
    with pytest.raises(ValueError, match="/model"):
        webapp.Panel.restart(p, {"id": "@9", "mark": "pi", "path": "/p"}, "claude")


def test_pi_country_rule_is_deepseek(monkeypatch):
    from gas_pult import webapp
    seen = []
    monkeypatch.setattr(webapp.models, "allowed", lambda prof, c: seen.append(prof) or True)
    p = webapp.Panel.__new__(webapp.Panel)
    p.countries = lambda uid: ["NL"]
    webapp.Panel.check(p, "pi", 1)
    assert seen == ["deepseek"]


def test_ui_offers_pi_in_model_pick():
    from pathlib import Path
    web = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
    s = (web / "index.html").read_text(encoding="utf-8")
    f = s[s.index("function pickProfile("):]
    f = f[:f.index("\n}\n")]
    assert "meta.agents" in f and '" — другой агент"' in f and "ready.length + agents.length < 2" in f
    assert 'profile === "pi" ? "Запускаю Pi…"' in s
    assert 'agents: [{ id: "pi"' in (web / "js" / "demo.js").read_text(encoding="utf-8")
