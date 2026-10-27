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
