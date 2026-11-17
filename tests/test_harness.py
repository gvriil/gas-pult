"""Провайдер сессий (R13): интерфейс и адаптер Claude Code — поведение то же, что у transcripts/tmux напрямую."""

import json
import sys

import pytest

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


@pytest.mark.skipif(sys.platform != "linux", reason="id сессии Pi — из /proc/<pid>/environ: только Linux")
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
    with pytest.raises(ValueError, match="/model"):                       # другой поставщик — модель меняется в Pi
        webapp.Panel.restart(p, {"id": "@9", "mark": "pi", "path": "/p", "profile": ""}, "deepseek")
    p.close = lambda w: "закрыто"
    p.focus = type("F", (), {"move": lambda self, a, b: None})()
    made.clear()
    sid = "33333333-3333-4333-8333-333333333333"
    r = webapp.Panel.restart(p, {"id": "@9", "mark": "pi", "path": "/p", "name": "pi-1", "sid": sid}, "claude")
    cmd, k = made[0]                                                       # «Перезапустить» окна Pi — снова Pi
    assert r == {"id": "@9"} and k["mark"] == "pi" and cmd.endswith(f"--session-id {sid}")


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
def _pi_rows(*msgs):
    rows = [{"type": "session", "version": 3, "id": "s", "timestamp": "2026-11-15T10:00:00.000Z", "cwd": "/p"}]
    for n, m in enumerate(msgs):
        rows.append({"type": "message", "id": f"m{n}", "timestamp": f"2026-11-15T10:00:{n:02d}.000Z", "message": m})
    return rows


def test_pi_status_phases_and_answers(tmp_path):
    from gas_pult import pi_journal
    user = {"role": "user", "content": [{"type": "text", "text": "Сколько файлов?"}]}
    call = {"role": "assistant", "stopReason": "toolUse", "content": [
        {"type": "thinking", "thinking": "…"}, {"type": "toolCall", "id": "c1", "name": "bash",
                                               "arguments": {"command": "ls -la"}}]}
    res = {"role": "toolResult", "toolCallId": "c1", "content": [{"type": "text", "text": "total 0"}]}
    end = {"role": "assistant", "stopReason": "stop", "content": [{"type": "text", "text": "Файлов нет."}]}
    f = tmp_path / "s.jsonl"

    def at(*msgs):
        f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in _pi_rows(*msgs)) + "\n")
        return pi_journal.status(f)
    assert pi_journal.status(None)["phase"] == "idle"
    assert at(user)["phase"] == "started"
    s = at(user, call)
    assert s["phase"] == "working" and s["tool"] == "bash" and "ls -la" in s["text"]
    assert at(user, call, res)["phase"] == "thinking"
    s = at(user, call, res, end)
    assert s["phase"] == "done" and s["said"] > 0
    assert pi_journal.answers(f) == ["Файлов нет."]
    at(user, call, res, end, user)
    assert pi_journal.answers(f) == ["Файлов нет."] and pi_journal.status(f)["phase"] == "started"


def test_bot_sends_only_new_pi_answers(tmp_path, monkeypatch):
    from gas_pult import bot
    root = tmp_path / "sessions"
    pi = harness.Pi(root=root)
    monkeypatch.setitem(harness.HARNESSES, "pi", pi)
    sid = "11111111-1111-4111-8111-111111111111"
    user = {"role": "user", "content": "вопрос"}
    end = lambda t: {"role": "assistant", "stopReason": "stop", "content": [{"type": "text", "text": t}]}  # noqa: E731
    f = _pi_journal(root, rows=_pi_rows(user, end("старый ответ")), sid=sid)
    p = bot.Pult.__new__(bot.Pult)
    sent = []
    p.deliver = lambda w, text: sent.append(text)
    p.broadcast = lambda text: sent.append("!" + text)
    w = {"id": "@5", "name": "pi-1", "path": "/home/u/proj", "harness": "pi", "sid": sid}
    p.pi_answers([w], {})
    assert sent == []                                                      # старое не пересылаем
    with open(f, "a") as fh:
        for r in _pi_rows(user, end("новый ответ"))[1:]:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    p.pi_answers([w], {})
    assert sent == ["новый ответ"]
    p.pi_answers([w], {})
    assert sent == ["новый ответ"]                                         # без повторов


def test_bot_activity_uses_pi_journal(tmp_path, monkeypatch):
    from gas_pult import bot
    root = tmp_path / "sessions"
    monkeypatch.setitem(harness.HARNESSES, "pi", harness.Pi(root=root))
    sid = "11111111-1111-4111-8111-111111111111"
    _pi_journal(root, rows=_pi_rows({"role": "user", "content": "x"}), sid=sid)
    p = bot.Pult.__new__(bot.Pult)
    p.screen_state = lambda wid: {}
    p.sends = type("S", (), {"get": lambda self, wid: None})()
    seen = {}
    monkeypatch.setattr(bot.activity, "combine", lambda j, rec, scr, **k: seen.setdefault("j", j))
    p.activity({"id": "@5", "path": "/home/u/proj", "harness": "pi", "sid": sid})
    assert seen["j"]["phase"] == "started"


def test_send_to_pi_skips_claude_prompt_wait(monkeypatch):
    """Владелец 15.11: «Pi не работает, не отвечает» — пульт ждал на экране Pi приглашение Claude «❯» 40 с и
    отвечал «окно не готово к вводу» (400), текст не уходил."""
    from gas_pult import bot
    p = bot.Pult.__new__(bot.Pult)
    shots = []
    p.tmux = type("T", (), {"window": lambda self, wid: {"id": wid, "harness": "pi", "cmd": "pi", "mark": "pi"},
                            "screen": lambda self, wid, n=15: shots.append(wid) or ["Pi", "> "]})()
    p.ready_for_text("@21")                                                # сразу, без ожидания «❯»
    assert shots == []
    p.tmux = type("T", (), {"window": lambda self, wid: {"id": wid, "harness": "claude", "cmd": "claude"},
                            "screen": lambda self, wid, n=15: shots.append(wid) or ["❯ "]})()
    p.ready_for_text("@1")                                                 # Claude — как раньше, по экрану
    assert shots == ["@1"]


def test_bot_sends_first_pi_answer_of_new_window(tmp_path, monkeypatch):
    """Живая проверка 15.11: окно Pi открыли, Pi ответил за 3 с между взглядами бота — ответ терялся как «старый»."""
    import time as _t

    from gas_pult import bot
    root = tmp_path / "sessions"
    monkeypatch.setitem(harness.HARNESSES, "pi", harness.Pi(root=root))
    sid = "11111111-1111-4111-8111-111111111111"
    now = _t.strftime("%Y-%m-%dT%H:%M:%S.000Z", _t.gmtime())
    rows = [{"type": "session", "id": "s", "timestamp": now, "cwd": "/p"},
            {"type": "message", "timestamp": now, "message": {"role": "user", "content": "вопрос"}},
            {"type": "message", "timestamp": now, "message": {"role": "assistant", "stopReason": "stop",
                                                              "content": [{"type": "text", "text": "Зелёного."}]}}]
    _pi_journal(root, rows=rows, sid=sid)
    p = bot.Pult.__new__(bot.Pult)
    p.pi_start = _t.time() - 60                                            # бот запущен минуту назад
    sent = []
    p.deliver = lambda w, text: sent.append(text)
    p.pi_answers([{"id": "@5", "name": "pi-1", "path": "/home/u/proj", "harness": "pi", "sid": sid}], {})
    assert sent == ["Зелёного."]
def test_fcc_free_profile(tmp_path, monkeypatch):
    """«Бесплатно (FCC)»: ключ — токен прокси из файла; служба не слушает — профиль не готов, команда — отказ."""
    from gas_pult import models
    p = dict(models.BY_ID["fcc"])
    tok = tmp_path / "proxy.token"
    tok.write_text("t0ken\n")
    monkeypatch.setitem(models.BY_ID, "fcc", {**p, "local_token": str(tok)})
    monkeypatch.setattr(models, "profiles_dir", lambda: tmp_path / "profiles")
    monkeypatch.setattr(models, "local_up", lambda p: False)
    assert not models.has_gateway("fcc", {})
    import pytest
    with pytest.raises(ValueError, match="не запущена"):
        models.command("claude", "fcc", {})
    monkeypatch.setattr(models, "local_up", lambda p: True)
    cmd = models.command("claude", "fcc", {})
    env = json.loads((tmp_path / "profiles" / "fcc.json").read_text())["env"]
    assert "--settings" in cmd and env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8082"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "t0ken" and env["ANTHROPIC_MODEL"].endswith(":free")
    pub = next(x for x in models.public({}) if x["id"] == "fcc")
    assert pub["needs_key"] is False and "не для клиентских данных" in pub["about"] and not pub["not_ready"]


def test_pi_usage_like_pi_footer(tmp_path):
    """Владелец 15.11: у окна Pi нижняя строка показывала лимиты Claude. Теперь — как у Pi: ↑ input, ↓ output, $."""
    from gas_pult import pi_journal
    store = tmp_path / "models-store.json"
    store.write_text(json.dumps({"deepseek": {"models": [{"id": "deepseek-v4-flash", "contextWindow": 1000000}]}}))
    pi_journal._windows.clear()
    a = {"role": "assistant", "provider": "deepseek", "model": "deepseek-v4-flash", "stopReason": "stop",
         "content": [{"type": "text", "text": "x"}],
         "usage": {"input": 1843, "output": 149, "cacheRead": 4992, "cacheWrite": 0, "cost": {"total": 0.0032424}}}
    b = {**a, "usage": {"input": 134, "output": 65, "cacheRead": 6912, "cacheWrite": 0, "cost": {"total": 0.0007384}}}
    f = tmp_path / "s.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in _pi_rows({"role": "user", "content": "q"}, a, b)) + "\n")
    u = pi_journal.usage(f, store)
    assert (u["in"], u["out"], u["read"], u["cost"]) == (1977, 214, 11904, 0.004)
    assert u["ctx"] == 134 + 6912 + 65 and u["window"] == 1000000 and u["used"] == 0.7
    assert u["provider"] == "deepseek" and u["model"] == "deepseek-v4-flash" and u["at"] > 0
    assert pi_journal.usage(None)["used"] is None


def test_panel_pi_row_has_own_status_line(tmp_path, monkeypatch):
    from gas_pult import pi_journal, webapp
    root = tmp_path / "sessions"
    monkeypatch.setitem(harness.HARNESSES, "pi", harness.Pi(root=root))
    monkeypatch.setattr(pi_journal, "window_of", lambda p, m, store=None: 1000000)
    sid = "11111111-1111-4111-8111-111111111111"
    a = {"role": "assistant", "provider": "deepseek", "model": "deepseek-v4-pro", "stopReason": "toolUse",
         "content": [{"type": "toolCall", "id": "c", "name": "bash", "arguments": {"command": "ls"}}],
         "usage": {"input": 9000, "output": 1000, "cacheRead": 0, "cacheWrite": 0, "cost": {"total": 0.01}}}
    _pi_journal(root, rows=_pi_rows({"role": "user", "content": "q"}, a), sid=sid)
    p = webapp.Panel.__new__(webapp.Panel)
    r = p.pi_row({"path": "/home/u/proj", "harness": "pi"}, sid)
    assert r["status"] == "busy" and r["model"] == "deepseek/deepseek-v4-pro" and r["context"] == 99
    assert r["usage"]["in"] == 9000 and r["usage"]["cost"] == 0.01


def test_pi_overlay_compose_and_launch(tmp_path, monkeypatch):
    from gas_pult import cli, pi_journal
    src = tmp_path / "profiles"
    src.mkdir()
    (src / "_core-short.md").write_text("# Свод\nвступление\n<!-- overlay -->\nГлавное: делай, что просят.\n")
    (src / "deepseek-v4.md").write_text("# DS\n<!-- overlay -->\n- не угадывай картинку\n<!-- /overlay -->\nхвост\n")
    text = pi_journal.compose_overlay(src, "deepseek-v4")
    assert text == "Главное: делай, что просят.\n\n- не угадывай картинку\n"     # свод первым, без вступлений
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(harness.Pi, "overlay", staticmethod(lambda: tmp_path / "cfg" / "pi" / "append.md"))
    cli.main(["pi", "overlay", "--from", str(src)])
    assert (tmp_path / "cfg" / "pi" / "append.md").read_text() == text
    fake = tmp_path / "pi"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("GAS_PULT_PI", str(fake))
    cmd = harness.HARNESSES["pi"].launch("11111111-1111-4111-8111-111111111111")
    assert f"--append-system-prompt {tmp_path / 'cfg' / 'pi' / 'append.md'}" in cmd
    import pytest
    with pytest.raises(SystemExit, match="нет ни"):
        cli.main(["pi", "overlay", "--from", str(tmp_path / "пусто")])


def test_ui_hides_claude_limits_for_other_agents():
    from pathlib import Path
    s = (Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html").read_text(encoding="utf-8")
    f = s[s.index("function sinfo(s) {"):]
    f = f[:f.index("\n}\n")]
    assert 'const other = s?.harness && s.harness !== "claude"' in f and "usageLine(s.usage)" in f
    assert "function usageLine(u)" in s
