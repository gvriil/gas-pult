import pytest

from gas_pult import webapp
from gas_pult.config import Config


@pytest.fixture
def panel(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    cmds = [{"i": 0, "cmd": "ls", "kind": "local", "danger": False, "sha": "aaa"},
            {"i": 1, "cmd": "rm -rf build", "kind": "local", "danger": True, "sha": "bbb"},
            {"i": 2, "cmd": "brew install x", "kind": "foreign", "danger": False, "sha": "ccc"}]
    monkeypatch.setattr(p, "commands", lambda w: cmds)
    monkeypatch.setattr(webapp, "execute", lambda cmd, cwd: (0, 0.1, f"ran {cmd}"))
    return p


W = {"id": "@1", "path": "/tmp"}


def test_run_ok(panel):
    assert panel.run(W, 0, "aaa", False) == {"code": 0, "seconds": 0, "out": "ran ls", "cut": False}


def test_run_rejects_changed_answer(panel):
    with pytest.raises(ValueError, match="изменился"):
        panel.run(W, 0, "zzz", False)          # отпечаток не совпал — браузер не подсунет свою команду


def test_run_danger_needs_confirm(panel):
    assert panel.run(W, 1, "bbb", False) == {"confirm": True}
    assert panel.run(W, 1, "bbb", True)["out"] == "ran rm -rf build"


def test_run_foreign_refused(panel):
    with pytest.raises(ValueError, match="вручную"):
        panel.run(W, 2, "ccc", True)
