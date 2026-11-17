"""Автопамять проекта в окнах Pi, OpenCode, Hermes (владелец 17.11, приоритет №1): пульт собирает MEMORY.md и файлы
по ссылкам из папки памяти проекта в файл 0600 и отдаёт агенту его способом."""

import json
import shlex
from pathlib import Path

from gas_pult import agent_memory, harness


def mem_home(tmp_path, path="/srv/shop"):
    home = tmp_path / "claude"
    d = home / "projects" / agent_memory.claude_key(path) / "memory"
    d.mkdir(parents=True)
    (d / "MEMORY.md").write_text("- [Ссылки](links.md) — только Google Диск\n- [Чужое](../../secret.md)\n")
    (d / "links.md").write_text("Ссылки владельцу — Google Диск.")
    (home / "projects" / "secret.md").write_text("не из папки памяти")
    return home


def test_collect_only_own_folder_and_limit(tmp_path):
    home = mem_home(tmp_path)
    t = agent_memory.collect("/srv/shop", home)
    assert "### links.md" in t and "Google Диск" in t and "не из папки памяти" not in t
    assert agent_memory.collect("/srv/other", home) == ""
    assert agent_memory.collect("/srv/shop", home, limit=20).endswith("(память обрезана: больше лимита)")
    assert agent_memory.claude_key("/home/u/projects/gas-pult") == "-home-u-projects-gas-pult"


def test_launch_gives_memory_to_each_agent(tmp_path, monkeypatch):
    home = mem_home(tmp_path)
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(cfg))
    monkeypatch.setattr(agent_memory, "memory_dir", lambda path, h=None: (home / "projects"
                                                                          / agent_memory.claude_key(path) / "memory"))
    oc, hm, pi = harness.OpenCode(tmp_path / "no.db"), harness.Hermes(tmp_path / "no.db"), harness.Pi()
    oc.binary = lambda: "/usr/bin/opencode"
    hm.binary = lambda: "/usr/bin/hermes"
    monkeypatch.setattr(pi, "binary", lambda: "/usr/bin/pi")
    c = shlex.split(oc.launch("", path="/srv/shop"))
    assert c[0] == "env" and c[1].startswith("OPENCODE_CONFIG_CONTENT=") and c[2] == "/usr/bin/opencode"
    f = json.loads(c[1].split("=", 1)[1])["instructions"][0]
    assert "Google Диск" in Path(f).read_text(encoding="utf-8")
    assert oct((cfg / "agents").stat().st_mode)[-3:] == "700" and oct(Path(f).stat().st_mode)[-3:] == "600"
    h = shlex.split(hm.launch("", resume=True, path="/srv/shop"))
    assert h[1] == f"GAS_PULT_MEMORY_FILE={f}" and h[-1] == "-c"
    p = pi.launch("11111111-1111-4111-8111-111111111111", path="/srv/shop")
    assert f"--append-system-prompt {f}" in p                              # правила + память — одним файлом
    assert oc.launch("", path="/srv/nomemory") == "/usr/bin/opencode"      # памяти нет — как раньше
