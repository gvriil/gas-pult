"""Изоляция (GAS-38): пространство или участник кладёт в свою папку журналов ссылку на чужой файл (журнал
владельца, ключи) — пульт такой «журнал» не читает и не показывает."""
import uuid

from gas_pult import transcripts


def test_link_outside_home_is_not_a_journal(tmp_path):
    home = tmp_path / "space" / "config" / "claude"
    d = transcripts.project_dir("/srv/x/home/projects/a", home)
    d.mkdir(parents=True)
    secret = tmp_path / "owner" / "chat.jsonl"
    secret.parent.mkdir()
    secret.write_text('{"type":"user","message":{"content":"секрет владельца"}}\n')
    sid = str(uuid.uuid4())
    (d / f"{sid}.jsonl").symlink_to(secret)
    assert transcripts.current("/srv/x/home/projects/a", home, sid) is None        # по id окна
    assert transcripts.current("/srv/x/home/projects/a", home) is None             # «последний журнал папки»
    own = d / f"{uuid.uuid4()}.jsonl"
    own.write_text('{"type":"user","message":{"content":"своё"}}\n')
    assert transcripts.current("/srv/x/home/projects/a", home) == own               # свой журнал — как раньше


def test_owner_without_home_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(transcripts, "CLAUDE_PROJECTS", tmp_path / "projects")
    d = transcripts.project_dir("/p/a")
    d.mkdir(parents=True)
    f = d / f"{uuid.uuid4()}.jsonl"
    f.write_text("{}\n")
    assert transcripts.current("/p/a") == f


def test_project_chats_skip_member_links(tmp_path):
    from gas_pult import projects
    home = tmp_path / "people" / "7" / "claude"
    d = transcripts.project_dir("/p/a", home)
    d.mkdir(parents=True)
    secret = tmp_path / "owner.jsonl"
    secret.write_text("{}\n")
    (d / f"{uuid.uuid4()}.jsonl").symlink_to(secret)
    own = d / f"{uuid.uuid4()}.jsonl"
    own.write_text("{}\n")
    assert projects.session_files(["/p/a"], [home]) == [own]
