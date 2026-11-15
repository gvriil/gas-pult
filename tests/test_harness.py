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
