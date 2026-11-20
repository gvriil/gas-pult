"""Владелец 20.11: «внутри закреплённых, панели, чатов — двигать между собой; проекты — ставить приоритет».
Порядок свой у каждого человека, на сервере (projects.json → order), одинаков на всех устройствах."""
from pathlib import Path

import pytest

from gas_pult import projects

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")


def test_order_is_per_person_and_validated(tmp_path):
    st = projects.Store(tmp_path / projects.FILE, str(tmp_path))
    assert st.set_order("owner", "proj", ["Pb", "Pa", " "]) == ["Pb", "Pa"]
    st.set_order("2", "p:shop", ["S1", "S2"])
    d = st.read()
    assert projects.order_of(d, "owner") == {"proj": ["Pb", "Pa"]}
    assert projects.order_of(d, "2") == {"p:shop": ["S1", "S2"]} and projects.order_of(d, "3") == {}
    for bad in ("", "x", "p:", "p:../../etc", "proj;rm"):
        with pytest.raises(ValueError):
            st.set_order("owner", bad, ["a"])
    st.set_order("owner", "proj", [])                                  # пусто — порядок по умолчанию
    assert projects.order_of(st.read(), "owner") == {}


def test_ui_orders_groups_and_moves():
    for grp in ('ordBy("pins"', 'ordBy("proj"', 'ordBy("chats"', 'ordBy("p:" + p.id'):
        assert grp in INDEX, grp
    assert 'api("/api/order", { grp, ids: keys })' in INDEX
    assert '{ label: "Поднять выше", icon: "up", run: () => orderMove(row, -1) }' in INDEX
    assert "if (NAV.drag) return;" in INDEX                            # во время перетаскивания список не трогаем
    js = (WEB / "js/order.js").read_text(encoding="utf-8")
    assert "export function arm(" in js and "export function drag(" in js and "saveOrder(grp, keys)" in js
