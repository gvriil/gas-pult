"""GAS-38 (а): терминал в пространстве клиента — как у владельца (за «режимом разработчика»), только окна своего
пространства; командная строка там — песочница пространства (свой пользователь Linux). Чужие окна — 404."""
import time

import pytest

from gas_pult import spaces, tenants, webauth
from tests.test_tenant_testers import TESTER, call, open_tester_session, q, world  # noqa: F401


def confirmed(w):
    """Ввод в терминал — после кода подтверждения, как у владельца (webapp.CONFIRM)."""
    assert w["p"].auth.confirm_hash(webauth._h(w["tok"][TESTER]))


def test_tester_terminal_own_window(world):  # noqa: F811
    w = world
    confirmed(w)
    wid = open_tester_session(w)
    code, d = call(w, f"/api/tty?w={q(wid)}")
    assert code == 200 and d["w"] == wid, d
    assert call(w, "/api/tty/type", {"w": wid, "text": "привет"})[0] == 200
    raw = spaces.split(wid)[1]
    for _ in range(20):
        if "привет" in "\n".join(tenants.tmux_of("demo").screen(raw, 40)):
            break
        time.sleep(0.2)
    assert "привет" in "\n".join(tenants.tmux_of("demo").screen(raw, 40))


@pytest.mark.parametrize("target", ["owner", "other"])
def test_tester_terminal_foreign_window_404(world, target):  # noqa: F811
    w = world
    confirmed(w)
    open_tester_session(w)
    wid = w["owner_w"] if target == "owner" else w["other_w"]
    assert call(w, f"/api/tty?w={q(wid)}")[0] == 404
    for path, body in (("/api/tty/type", {"text": "rm -rf ~"}), ("/api/tty/key", {"key": "Enter"}),
                       ("/api/tty/size", {"cols": 80, "rows": 24})):
        code, d = call(w, path, {"w": wid, **body})
        assert code == 404, (path, code, d)
    tm = w["own"] if target == "owner" else tenants.tmux_of("other")
    time.sleep(0.4)
    assert "rm -rf" not in "\n".join(tm.screen(spaces.split(wid)[1], 60))


def test_tester_cost_is_own_space_budget_not_owner(world):  # noqa: F811
    """GAS-38 (б): расход клиенту — его пространства (запас и сегодня), лимиты подписки владельца — никогда."""
    w = world
    open_tester_session(w)
    c = call(w, "/api/sessions")[1]["cost"]
    assert c["pool"] == "own" and "budget" in c and "limits" not in c and "paused" not in c
    assert "limits" in call(w, "/api/sessions", who=7101)[1]["cost"]          # у владельца — как раньше
