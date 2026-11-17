"""Роль «админ» (владелец 17.11: «права приглашать людей, поддерживать пульт и пользователей»; границы — записка
https://docs.google.com/document/d/1Y4ItdaQ-3e_883E79mPYbxIOWDtXIHFadiYUtm1LI9c). Может: люди, приглашения,
пространства, продление доступа, перезапуск без смены модели. Не может: ключи, деньги, команды на сервере, роль
«админ», менять других админов."""

from test_easy_login import OWNER, dirs, guest_ready, req, web  # noqa: F401 — фикстуры и помощники того же сервера

from gas_pult import invites, people

ADMIN, MEMBER, OTHER_ADMIN = 7401, 7402, 7403


def setup(p):
    for uid, role in ((ADMIN, "admin"), (MEMBER, "member"), (OTHER_ADMIN, "admin")):
        p.people.add(uid, role, f"u{uid}")
        guest_ready(p, uid)
    return p.auth.issue(ADMIN)


def test_admin_can_people_and_invites(web):  # noqa: F811
    p, base = web
    tok = setup(p)
    assert people.allowed("admin", "member") and not people.allowed("admin", "owner")
    st, _, d = req(base, "/api/people", token=tok)
    assert st == 200 and any(x["id"] == MEMBER for x in d["people"])
    assert req(base, "/api/people/role", {"id": MEMBER, "role": "viewer"}, tok)[0] == 200
    assert p.people.role(MEMBER) == "viewer"
    assert req(base, "/api/people/access", {"id": MEMBER, "days": 30}, tok)[0] == 200
    assert next(x for x in p.people.list() if x["id"] == MEMBER)["access_until"] > 0
    st, _, d = req(base, "/api/invite/new", {"space": "demo", "name": "Алексей", "ttl": "7d", "uses": 3}, tok)
    assert st == 200 and invites.check(d["path"].rsplit("/", 1)[1])
    assert req(base, "/api/spaces", token=tok)[0] == 200


def test_admin_limits(web):  # noqa: F811
    p, base = web
    tok = setup(p)
    st, _, d = req(base, "/api/people/role", {"id": MEMBER, "role": "admin"}, tok)
    assert st == 400 and "только владелец" in d["error"]                   # админа выдаёт только владелец
    assert req(base, "/api/people/role", {"id": OTHER_ADMIN, "role": "member"}, tok)[0] == 400
    assert req(base, "/api/people/remove", {"id": OTHER_ADMIN}, tok)[0] == 400
    assert p.people.role(OTHER_ADMIN) == "admin"
    assert req(base, "/api/people/role", {"id": OWNER, "role": "member"}, tok)[0] == 400
    for path in ("/api/keys", "/api/cost/limits", "/api/run", "/api/models", "/api/space/budget/add",
                 "/api/tasks/add", "/api/bridge/pair", "/api/team"):
        st, _, d = req(base, path, {}, tok)
        assert st == 403 and "только владелец" in d["error"], path
    assert req(base, "/api/people/remove", {"id": MEMBER}, tok)[0] == 200    # участника — может
    assert p.people.role(MEMBER) is None


def test_owner_grants_admin_only_to_telegram_people(web):  # noqa: F811
    p, base = web
    owner = p.auth.issue(OWNER)
    p.people.add(MEMBER, "member", "m")
    assert req(base, "/api/people/role", {"id": MEMBER, "role": "admin"}, owner)[0] == 200
    assert p.people.role(MEMBER) == "admin"
    g = p.people.add_guest("Гость", "member", "demo")
    st, _, d = req(base, "/api/people/role", {"id": g, "role": "admin"}, owner)
    assert st == 400 and "Telegram" in d["error"]
    assert req(base, "/api/people/role", {"id": MEMBER, "role": "member"}, owner)[0] == 200   # владелец снимает
