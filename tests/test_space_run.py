"""«Выполнить» и терминал пульта закрыты для сессий пространств: команда из ответа агента клиента не должна идти от
пользователя пульта вне песочницы пространства (аудит 42, раздел «Треки», В5)."""

import pytest

from gas_pult import commands, webapp
from gas_pult.commands import Commands, in_space
from gas_pult.config import Config


@pytest.fixture
def troot(monkeypatch, tmp_path):
    r = tmp_path / "tenants"
    (r / "acme/home/projects/x").mkdir(parents=True)
    monkeypatch.setenv("GAS_PULT_TENANTS_ROOT", str(r))
    return r


def test_in_space_by_mark_and_path(troot, tmp_path):
    assert in_space({"space": "acme", "path": "/tmp"})
    assert in_space({"path": str(troot / "acme/home/projects/x")})
    assert in_space({"cwd": str(troot)})
    assert not in_space({"path": str(tmp_path / "tenants-other")})       # соседняя папка с похожим именем — не она
    assert not in_space({"path": "/tmp"}) and not in_space({})


@pytest.fixture
def panel(monkeypatch, tmp_path, troot):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    cmds = [{"i": 0, "cmd": "ls", "kind": "local", "danger": False, "sha": "aaa"},
            {"i": 1, "cmd": "keepassxc-cli ls db", "kind": "tty", "danger": False, "sha": "bbb"}]
    monkeypatch.setattr(p, "commands", lambda w: cmds)
    ran = []
    monkeypatch.setattr(webapp, "execute", lambda cmd, cwd: ran.append(cmd) or (0, 0.1, "ok"))
    monkeypatch.setattr(webapp.termwin, "open_window", lambda *a: ran.append("term") or "@9")
    p.ran = ran
    return p


def test_panel_run_and_term_refused_in_space(panel, troot):
    for w in ({"id": "@2", "path": "/tmp", "space": "acme"}, {"id": "@3", "path": str(troot / "acme")}):
        with pytest.raises(PermissionError, match="пространства"):
            panel.run(w, 0, "aaa", True)
        with pytest.raises(PermissionError, match="пространства"):
            panel.term_run(w, 1, "bbb", True)
    assert panel.ran == []
    assert panel.run({"id": "@1", "path": "/tmp"}, 0, "aaa", False)["code"] == 0     # у владельца — как раньше


def test_journal_run_and_term_refused_in_space(panel, troot, monkeypatch):
    p = str(troot / "acme/home/projects/x")
    items = {"s1": {"id": "s1", "cmd": "ls", "kind": "local", "danger": False, "path": p, "ts": "1", "n": 0,
                    "done": None},
             "s2": {"id": "s2", "cmd": "ssh host", "kind": "tty", "danger": False, "path": p, "ts": "2", "n": 0,
                    "done": None}}
    panel.journal.save({"items": items, "revs": {}})
    with pytest.raises(PermissionError):
        panel.command_run("s1", True)
    with pytest.raises(PermissionError):
        panel.command_term("s2", True)
    assert panel.ran == [] and panel.journal.get("s1")["done"] is None


def test_bot_offer_has_no_run_button_for_space(tmp_path, troot):
    c, sent = Commands("h", tmp_path / "cmds.json", [], [], platform="linux"), []
    send = lambda text, **kw: sent.append((text, kw))  # noqa: E731
    c.offer({"name": "w", "path": "/tmp", "space": "acme"}, "```bash\necho привет\n```", send, lambda rows: rows)
    assert len(sent) == 1 and "reply_markup" not in sent[0][1] and "агент пространства" in sent[0][0]


def test_bot_run_refuses_stored_space_command(tmp_path, troot, monkeypatch):
    c, sent = Commands("h", tmp_path / "cmds.json", [], [], platform="linux"), []
    c._save({"x1": {"cmd": "echo hi", "cwd": str(troot / "acme"), "win": "w", "ts": 0}})
    monkeypatch.setattr(commands, "execute", lambda *a: pytest.fail("не должна выполняться"))
    c.run("x1", True, lambda text, **kw: sent.append(text), lambda rows: rows)
    assert "пространства" in sent[-1]
