"""Приглашения v2 (владелец 17.11): многоразовые (телефон и компьютер), срок ссылки на выбор, срок доступа человека,
пометка плана — задел на подписку. Старые записи без «uses» — одноразовые, как раньше."""

import time

import pytest

from gas_pult import invites, people


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(invites.tenants, "check_slug", lambda s: s)
    monkeypatch.setattr(invites.tenants, "enabled", lambda: False)
    monkeypatch.setattr(invites, "store", lambda: tmp_path / "invites.json")
    return tmp_path


def test_uses_n_and_unlimited(env):
    c3 = invites.new("demo", uses=3, ttl=invites.TTLS["7d"])["code"]
    assert [bool(invites.redeem(c3, u)) for u in (1, 2, 3, 4)] == [True, True, True, False]
    c0 = invites.new("demo", uses=0)["code"]
    assert all(invites.redeem(c0, u) for u in range(10)) and invites.check(c0)       # без лимита — до конца срока
    row = next(x for x in invites.listing() if x["uses"] == 3)
    assert row["n"] == 3 and row["state"] == "used"


def test_access_and_plan(env):
    code = invites.new("demo", access=30, plan="trial")["code"]
    inv = invites.redeem(code, 1)
    assert inv["access"] == 30 and inv["plan"] == "trial"
    assert abs(invites.until_of(inv, now=1000) - (1000 + 30 * 86400)) == 0
    assert invites.until_of({"access": 0}) is None


def test_validation(env):
    for kw in ({"uses": -1}, {"uses": 5000}, {"access": 13}, {"plan": "gold"}, {"ttl": 400 * 86400}):
        with pytest.raises(ValueError):
            invites.new("demo", **kw)


def test_legacy_record_single_use(env):
    rec = {"tenant": "demo", "role": "member", "exp": time.time() + 99, "used": None}
    assert invites.state(rec) == "active"
    assert invites.state({**rec, "used": 5}) == "used"


def test_person_access_until(tmp_path):
    ps = people.People(tmp_path / "people.json", owners=[1])
    ps.add(10, "member", "Тест", until=int(time.time()) + 100, plan="pilot")
    assert ps.role(10) == "member"
    ps.add(11, "member", "Старый", until=int(time.time()) - 1)
    assert ps.role(11) is None                                            # срок вышел — доступа нет
    ps.add(11, "member", until=0)                                         # продлить бессрочно
    assert ps.role(11) == "member"
    ps.add(10, "viewer")                                                  # смена роли срок не сбрасывает
    rec = next(x for x in ps.list() if x["id"] == 10)
    assert rec["plan"] == "pilot" and rec["access_until"] > time.time()
    g = ps.add_guest("Гость", "member", "demo", until=int(time.time()) - 1)
    assert ps.role(g) is None
