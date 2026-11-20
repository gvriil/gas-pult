"""Таблица отладочного (владелец 20.11): терминал — только тем, кому нужен. Владелец — как был; участник без
явного «добавить» — без «Экрана терминала»; интерфейс прячет вкладки, >_, клавиши, «Команды» и «Выполнить»."""
from pathlib import Path

from gas_pult import webapp
from gas_pult.config import Config

INDEX = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/index.html").read_text(encoding="utf-8")


def test_member_has_no_terminal_by_default_owner_keeps_it():
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    p.people.add(2, "member")
    assert "cap.dev_terminal" in p.ui(1, "owner")["caps"]
    assert "cap.dev_terminal" not in p.ui(2, "member")["caps"]
    p.people.set_ui(2, {**p.people.ui(2), "added": ["cap.dev_terminal"]})   # включили явно — есть
    assert "cap.dev_terminal" in p.ui(2, "member")["caps"]


def test_css_hides_debug_without_terminal_capability():
    for sel in ("#tabsBar", "#screenBtn", "#keys", "#menu [data-act=commands]", "#homeSeg [data-v=commands]",
                "[data-run]", "[data-crun]"):
        assert f"body.nocap-dev_terminal {sel}" in INDEX, sel
