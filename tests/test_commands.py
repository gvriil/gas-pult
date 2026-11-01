from gas_pult.commands import DANGER, Commands, extract, mask
from gas_pult.config import SUDO_ALLOW


def cmds(tmp_path, platform="linux", **kw):
    return Commands("box", tmp_path / "cmds.json", kw.get("sudo", SUDO_ALLOW), kw.get("foreign", []), platform)


def test_extract_shell_blocks_only():
    text = "Сделай так:\n```bash\nls -la\n```\n```python\nprint(1)\n```\n```\ngit status\n```"
    assert extract(text) == ["ls -la", "git status"]


def test_extract_skips_prose_blocks():
    text = "```\nПрочитай описание задачи и составь подробный план работы\nпотом приступай к реализации\n```"
    assert extract(text) == []


def test_kind(tmp_path):
    c = cmds(tmp_path)
    assert c.kind("ls ~/projects") == "local"
    assert c.kind("brew install jq") == "foreign"
    assert c.kind("sudo apt install -y jq") == "local"
    assert c.kind("sudo rm -rf /") == "sudo"


def test_kind_on_mac_flips_foreign(tmp_path):
    c = cmds(tmp_path, platform="darwin")
    assert c.kind("brew install jq") == "local"
    assert c.kind("sudo systemctl restart nginx") == "foreign"


def test_custom_foreign_and_empty_sudo(tmp_path):
    c = cmds(tmp_path, sudo=[], foreign=[r"\bssh\s+prod\b"])
    assert c.kind("ssh prod uptime") == "foreign"
    assert c.kind("sudo apt update") == "sudo"


def test_danger():
    assert DANGER.search("rm -rf build")
    assert DANGER.search("git push --force origin main")
    assert not DANGER.search("git push origin main")


def test_mask_secrets():
    out = mask("token=abcdef123456 and 123456789:AA" + "x" * 33)
    assert "abcdef123456" not in out and "AAxxx" not in out


def test_offer_and_run(tmp_path):
    c, sent = cmds(tmp_path), []
    send = lambda text, **kw: sent.append((text, kw))  # noqa: E731
    kb = lambda rows: rows  # noqa: E731
    c.offer({"name": "w", "path": str(tmp_path)}, "```bash\necho привет\n```", send, kb)
    cid = sent[-1][1]["reply_markup"][0][0][1].split(":")[1]
    c.run(cid, False, send, kb)
    assert "✅ код 0" in sent[-1][0] and "привет" in sent[-1][0]
    assert (tmp_path / "cmds.json").stat().st_mode & 0o777 == 0o600


def test_execute_pipefail_reports_failure():
    from gas_pult.commands import execute
    code, _, _ = execute("false | cat", None)
    assert code != 0                         # без pipefail было бы 0 — ложный «✅»
    code, _, out = execute("echo token=abcdef123456", None)
    assert code == 0 and "abcdef123456" not in out


def test_password_commands_have_no_button(tmp_path):
    c = cmds(tmp_path)
    for cmd in ("pass show work/db >/dev/null", "gpg --passwd ABCD", "ssh-add ~/.ssh/id_ed25519",
                "read -rsp 'Токен: ' T"):
        assert c.kind(cmd) == "tty", cmd
    assert c.kind("git log --oneline") == "local"


def test_about_from_comment_or_text_before():
    from gas_pult.commands import blocks
    text = ("Проверим службу:\n\n```bash\nsystemctl --user status gas-pult\n```\n\n"
            "```bash\n# перезапуск панели\nsystemctl --user restart gas-pult-webapp\n```\n"
            "1. **Обновите код:**\n```\ngit pull --ff-only\n```")
    assert [why for _, why in blocks(text)] == ["Проверим службу", "перезапуск панели", "Обновите код"]


def _transcript(tmp_path, monkeypatch, folder, answers):
    import json

    from gas_pult import transcripts
    monkeypatch.setattr(transcripts, "CLAUDE_PROJECTS", tmp_path / "projects")
    d = transcripts.project_dir(folder)
    d.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, a in enumerate(answers):
        ts = f"2026-11-01T10:{i:02d}:00Z"
        lines.append({"type": "user", "timestamp": ts, "message": {"content": f"вопрос {i}"}})
        lines.append({"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "text", "text": a}]}})
    (d / "s.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n")


def test_journal_collects_all_sessions_newest_first_and_survives_restart(tmp_path, monkeypatch):
    from gas_pult.commands import Journal
    _transcript(tmp_path, monkeypatch, "/srv/a", ["Смотрим:\n```bash\nls -la\n```", "```bash\nuptime\n```"])
    _transcript(tmp_path, monkeypatch, "/srv/b", ["```\n# место на диске\ndf -h\n```"])
    wins = [{"id": "@1", "name": "alpha", "path": "/srv/a"}, {"id": "@2", "name": "beta", "path": "/srv/b"}]
    j = Journal(tmp_path / "log.json")
    assert j.collect(wins, lambda c: "local")
    assert [(c["win"], c["cmd"], c["about"]) for c in j.items()] == [
        ("alpha", "uptime", ""), ("alpha", "ls -la", "Смотрим"), ("beta", "# место на диске\ndf -h", "место на диске")]
    assert not j.collect(wins, lambda c: "local")            # журнал не менялся — не перечитываем
    cid = j.items()[0]["id"]
    j.mark(cid, {"code": 0})
    again = Journal(tmp_path / "log.json")                    # перезапуск панели
    assert again.get(cid)["done"] == {"code": 0} and len(again.items()) == 3


def test_journal_keeps_commands_of_closed_window(tmp_path, monkeypatch):
    from gas_pult.commands import Journal
    _transcript(tmp_path, monkeypatch, "/srv/a", ["```bash\nls\n```"])
    j = Journal(tmp_path / "log.json")
    j.collect([{"id": "@1", "name": "alpha", "path": "/srv/a"}], lambda c: "local")
    j.collect([], lambda c: "local")                          # окно закрыли
    assert [c["cmd"] for c in j.items()] == ["ls"]


def test_bot_run_marks_command_in_panel_log(tmp_path, monkeypatch):
    from gas_pult import commands
    from gas_pult.commands import Commands, Journal
    _transcript(tmp_path, monkeypatch, "/srv/a", ["```bash\nls\n```", "```bash\nls\n```"])
    j = Journal(tmp_path / "log.json")
    wins = [{"id": "@1", "name": "alpha", "path": "/srv/a"}]

    def done(cmd, path, code, secs, out):
        j.collect(wins, lambda c: "local")                    # панель этот ответ ещё не видела
        j.mark_cmd(path, cmd, {"code": code, "by": "bot"})

    c = Commands("h", tmp_path / "cmds.json", [], [], platform="linux", on_done=done)
    monkeypatch.setattr(commands, "execute", lambda cmd, cwd: (2, 0.1, "boom"))
    c.offer({"name": "alpha", "path": "/srv/a"}, "```bash\nls\n```", lambda *a, **k: None, lambda rows: rows)
    cid = next(iter(c._load()))
    c.run(cid, False, lambda *a, **k: None, lambda rows: rows)
    marked = [x for x in j.items() if x["done"]]
    assert len(marked) == 1 and marked[0]["done"] == {"code": 2, "by": "bot"}
    assert marked[0]["ts"] == max(x["ts"] for x in j.items())      # отмечена самая свежая из одинаковых
    assert not j.mark_cmd("/srv/other", "ls", {"code": 0})


def test_mark_failure_does_not_lose_result(tmp_path, monkeypatch):
    from gas_pult import commands
    from gas_pult.commands import Commands

    def bad(*a):
        raise OSError("диск")
    c = Commands("h", tmp_path / "cmds.json", [], [], platform="linux", on_done=bad)
    monkeypatch.setattr(commands, "execute", lambda cmd, cwd: (0, 0.1, "ok"))
    c.offer({"name": "a", "path": "/tmp"}, "```bash\nls\n```", lambda *a, **k: None, lambda rows: rows)
    sent = []
    c.run(next(iter(c._load())), False, lambda text, **k: sent.append(text), lambda rows: rows)
    assert any("код 0" in t for t in sent)
