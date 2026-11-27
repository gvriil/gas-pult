"""Имя нового окна — уникальное: два окна одной папки за минуту не получают одно имя (22.11, «Перенести в проект…»)."""
import time
from types import SimpleNamespace

from gas_pult.panel.sessions import SessionsPart


def panel(names):
    return SimpleNamespace(tmux=SimpleNamespace(windows=lambda: [{"name": n} for n in names]))


def test_free_name_kept_when_free():
    name = f"proj-{time.strftime('%H%M')}"
    assert SessionsPart.free_wname(panel(["other-0000"]), "proj") == name


def test_taken_name_gets_suffix():
    name = f"proj-{time.strftime('%H%M')}"
    assert SessionsPart.free_wname(panel([name]), "proj") == f"{name}-2"
    assert SessionsPart.free_wname(panel([name, f"{name}-2"]), "proj") == f"{name}-3"


def test_tmux_error_falls_back_to_plain_name():
    def boom():
        raise OSError("нет tmux")
    p = SimpleNamespace(tmux=SimpleNamespace(windows=boom))
    assert SessionsPart.free_wname(p, "proj") == f"proj-{time.strftime('%H%M')}"
