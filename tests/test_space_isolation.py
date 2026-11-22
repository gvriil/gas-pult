"""Изоляция пространств (разбор архитектуры 22.11): человек пространства A не видит и не меняет данных пространства B
и владельца — по каждому пути API, открытому человеку пространства (``access.SPACE_OK``), и по ``/api/v1`` с токеном
пространства.

Люди всех пространств лежат в одном ``people.json`` (поле ``tenant``), поэтому проверяем не только окна, но и людей:
имя и Telegram ID человека пространства B и владельца не должны попасть ни в один ответ человеку A.

Как устроено:
- мир — фикстура ``world`` из ``test_tenant_testers`` (пространства demo и other, тестировщик TESTER в demo);
- в пространстве other и у владельца раскладываем «чужое» с метками ``ZQ…``: человек, файлы, проект, переписка в окне,
  задача, фокус-ссылка, токен API, подписка на уведомления, распознавание голоса, приглашение, черновики коннекторов;
- перебираем опись API (``api_spec.scan``): каждый путь из ``SPACE_OK`` и каждый ``/api/v1/…`` — запросами, где каждое
  поле входа заполнено идентификатором other или владельца (``FOREIGN``);
- проверяем: в ответе нет ни одной метки и ни одного чужого Telegram ID; ответы 5xx нет; после всего перебора чужое
  состояние (файлы, окна, люди, задачи, ссылки, токены, подписки, черновики) — то же, что до.
- путь, который в тестовом мире не проверить, — в ``NOT_CHECKED`` с причиной; новый путь в ``SPACE_OK`` без проверки
  и без причины — падение теста (не молча).
"""

import hashlib
import json
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request

import pytest
from test_tenant_testers import MEMBER, OWNER, TESTER, call, open_tester_session, q, wait, world  # noqa: F401

from gas_pult import access, api_spec, drafts, invites, spaces, tenants

OTHER = 990000000004                         # человек пространства other (длинный ID — не спутать с числами ответа)
OTHER_NAME = "Анна ZQ-чужая"
MEMBER_NAME = "ZQ-участник-владельца"
MARKS = ("ZQ-",)                              # всё «чужое» помечено так; в запросах эти строки не отправляем

# Пути SPACE_OK, которые перебором не проверить, — с причиной (тест падает, если путь не здесь и не проверен).
NOT_CHECKED = {
    access.STT_STREAM: "WebSocket (служба T-one) — нет в тестовом мире; чужих id на входе нет",
    "/api/stt": "тело — запись голоса; чужих id на входе нет (распознавание чужого — /api/stt/job, проверен)",
    "/api/rec/chunk": "тело — кусок записи; сеанс — только свой (recparts): /api/rec/status проверен",
    "/api/space/upload": "multipart; путь папки — только из окна своего пространства (test_tenant_testers: файлы)",
    "/api/help/ask": "вызов модели-помощника (сеть); чужих id на входе нет",
    "/api/feedback": "отзыв уходит в задачи штаба (внешний канал); чужих id на входе нет",
    "/api/tts/about": "синтез речи текста подсказки; чужих id на входе нет",
    "/api/logout": "проверен отдельно (test_logout_ends_only_own_session): в переборе выключил бы вход тестировщика",
}


def sha(p) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def tree(d) -> dict:
    return {str(p.relative_to(d)): sha(p) for p in sorted(d.rglob("*")) if p.is_file()}


class FakeDrafts:
    """Черновики коннекторов без программы моста: по пространству (None — владелец)."""

    def __init__(self):
        self.items = {None: [{"svc": "gmail", "id": "0000000000a1", "text": "ZQ-черновик-владельца", "pane": ""}],
                      "other": [{"svc": "gmail", "id": "0000000000b2", "text": "ZQ-черновик-чужой", "pane": ""}],
                      "demo": []}
        self.rejected: list = []
        self.slugs: set = set()                   # чьё хранилище черновиков открывали

    def __call__(self, slug, *args):
        slug = slug or None
        self.slugs.add(slug)
        if args[0] == "list":
            return {"drafts": [dict(x) for x in self.items.get(slug, [])]}
        hit = any(x["svc"] == args[1] and x["id"] == args[2] for x in self.items.get(slug, []))
        if not hit:
            return {"error": "черновика нет"}
        if args[0] == "no":
            self.rejected.append((slug, args[1], args[2]))
        return {"ok": True, "digest": "d" * 16}


@pytest.fixture
def iso(world, monkeypatch, tmp_path):   # noqa: F811
    w, p = world, world["p"]
    root = w["root"]
    p.people.add(OTHER, "member", OTHER_NAME, tenant="other")
    p.people.add(MEMBER, "member", MEMBER_NAME)
    p.people.accept(OTHER)
    p.people.set_country(OTHER, chosen="NL")
    # файлы и проект пространства other, файл в папке проекта владельца
    (root / "other/home/ZQ-secret.txt").write_text("ZQ-содержимое-чужое")
    (root / "other/home/projects/ZQproj").mkdir(parents=True)
    (root / "other/home/projects/ZQproj/CLAUDE.md").write_text("ZQ-инструкции-чужие")
    owner_dir = tmp_path / "projects" / "secret"
    (owner_dir / "ZQ-owner.txt").write_text("ZQ-содержимое-владельца")
    # переписка в окне other: метка на экране его окна
    other_raw = spaces.split(w["other_w"])[1]
    subprocess.run(["tmux", "-S", w["socks"]["other"], "send-keys", "-t", other_raw, "-l", "ZQ-переписка-чужая"],
                   check=True)
    subprocess.run(["tmux", "-S", w["socks"]["other"], "send-keys", "-t", other_raw, "Enter"], check=True)
    # задача владельца, фокус-ссылки на окна владельца и other
    task = p.tasks.add({"title": "ZQ-задача-владельца", "next": "ZQ-дальше"})
    f_owner = p.focus.new(p.tmux.window(w["owner_w"]), OWNER)
    f_other = p.focus.new(p.tmux.window(w["other_w"]), OWNER)
    # токен API человека other; токен тестировщика — для /api/v1
    tok_other = p.api_tokens.create(OTHER, "other", "ZQ-токен-чужой", write=True)
    tok_mine = p.api_tokens.create(TESTER, "demo", "Мой", write=True)
    # подписка на уведомления, распознавание голоса, приглашение (вход на другое устройство) — человека other
    dev = p.push.add(OTHER, {"endpoint": "https://fcm.googleapis.com/fcm/send/zq-other"}, label="ZQ-телефон-чужой")
    p.stt_jobs["0123456789abcdef"] = {"state": "done", "uid": OTHER, "at": 0, "file": "x.ogg", "cloud": False,
                                      "text": "ZQ-распознано-чужое"}
    inv = invites.new("other", "member", by=OWNER, uid=OTHER)
    rid, code = p.auth.confirm_start(w["tok"][TESTER])      # код подтверждения введён: «Да» и терминал — до обработчика
    p.auth.confirm_verify(w["tok"][TESTER], rid, code)
    fake = FakeDrafts()
    monkeypatch.setattr(drafts, "_run", fake)
    monkeypatch.setattr(p, "tts_warm", lambda *a, **k: {"ok": True})    # синтез речи — не про права
    owner_pid = next((x.get("id") for x in call(w, "/api/projects", who=OWNER)[1].get("projects", [])), "")
    assert wait(lambda: "ZQ-переписка-чужая" in "\n".join(tenants.tmux_of("other").screen(other_raw, 20)))
    w.update(task=task, f_owner=f_owner, f_other=f_other, tok_other=tok_other, tok_mine=tok_mine, dev=dev, inv=inv,
             drafts=fake, owner_dir=owner_dir, owner_pid=owner_pid, other_raw=other_raw)
    return w


def foreign(w) -> dict[str, list]:
    """Поле входа → чужие значения (пространства other и владельца). Остальные поля — безобидное «1»."""
    other_home = w["root"] / "other" / "home"
    return {
        "w": [w["other_w"], w["owner_w"], f"t:other:{w['other_raw']}", w["other_raw"]],
        "id": [w["task"]["id"], w["f_owner"]["id"], w["f_other"]["id"], w["tok_other"]["id"], w["dev"]["id"],
               "0123456789abcdef", "0000000000b2", "0000000000a1", "s:other:ZQproj", w["owner_pid"] or "secret",
               str(OTHER), str(OWNER)],
        "sid": ["0123456789abcdef", "../../other"],
        "f": ["../ZQ-secret.txt", "../../other/home/ZQ-secret.txt", str(other_home / "ZQ-secret.txt"),
              str(w["owner_dir"] / "ZQ-owner.txt")],
        "folder": ["ZQproj", "../../other/home/projects/ZQproj", "projects/ZQproj"],
        "confirm": ["ZQproj"],
        "path": [str(other_home), str(w["owner_dir"])],
        "u": [f"https://example.org/invite/{w['inv']['code']}"],
        "dev": [w["dev"]["id"]],
        "svc": ["gmail"],
        "sub": [{"endpoint": "https://fcm.googleapis.com/fcm/send/zq-other"}],   # подписка человека other
        "space": ["other"],
        "slug": ["other"],
        "uid": [OTHER, OWNER],
        "repo": ["octocat/Hello-World"],
        "i": [0],
        "key": ["Enter"],
        "text": ["x"],
        "name": ["x"],
        "title": ["x"],
        "force": [True],
    }


def snapshot(w) -> dict:
    """Чужое состояние: всё, что человек demo не должен поменять."""
    p = w["p"]
    keep = ("role", "name", "tenant", "username", "terms", "country", "email")
    people = {x["id"]: {k: x.get(k) for k in keep} for x in p.people.list() if x["id"] != TESTER}
    return {
        "other_files": tree(w["root"] / "other"),
        "owner_files": tree(w["owner_dir"]),
        "other_windows": sorted((x["id"], x["name"]) for x in tenants.tmux_of("other").windows()),
        "owner_windows": sorted((x["id"], x["name"]) for x in w["own"].windows()),
        "people": people,
        "tasks": p.tasks.list(),
        "focus": p.focus.listing(),
        "tokens": p.api_tokens.mine(OTHER, "other") + p.api_tokens.mine(OWNER, ""),
        "push": p.push.devices(OTHER),
        "stt": dict(p.stt_jobs["0123456789abcdef"]),
        "invite": bool(invites.check(w["inv"]["code"], short=False)),
        "drafts_rejected": list(w["drafts"].rejected),
        "approvals": dict(getattr(p.approvals, "given", {}) or {}),
    }


UID_RE = re.compile(rf"(?<![\d.]){OTHER}(?![\d.])|(?<![\d.]){OWNER}(?![\d.])|(?<![\d.]){MEMBER}(?![\d.])")


def leaks(body) -> list[str]:
    s = json.dumps(body, ensure_ascii=False)
    out = [m for m in MARKS if m in s] + UID_RE.findall(s)
    for name in (OTHER_NAME, MEMBER_NAME, "other-1", "owner-secret"):
        if name in s:
            out.append(name)
    return out


def variants(fields: list[str], pool: dict[str, list]) -> list[dict]:
    """Запросы перебора: n-й запрос берёт n-е чужое значение каждого поля (по кругу) + ``space``/``slug``/``uid``."""
    fs = list(dict.fromkeys([*fields, "space", "slug", "uid"]))
    n = max(len(pool.get(f, ["1"])) for f in fs)
    return [{f: pool.get(f, ["1"])[i % len(pool.get(f, ["1"]))] for f in fs} for i in range(n)]


def request(w, method, path, data, headers) -> tuple[int, object]:
    if method == "GET":
        url = w["base"] + path + "?" + urllib.parse.urlencode({k: v for k, v in data.items()})
        req = urllib.request.Request(url, headers=headers)
    else:
        req = urllib.request.Request(w["base"] + path, json.dumps(data).encode(),
                                     {**headers, "Content-Type": "application/json", "Origin": w["base"]})
    try:
        r = urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        r = e
    raw = r.read()
    try:
        return r.code, json.loads(raw or b"{}")
    except ValueError:
        return r.code, {"raw": len(raw)}


def cookie_of(w) -> dict:
    from gas_pult import webauth
    return {"Cookie": f"{webauth.COOKIE}={w['tok'][TESTER]}"}


# Ожидание по пути: какие коды допустимы, когда все поля входа — чужие. Пути без таблицы — любой код < 500 (но без
# меток и без изменения чужого). «окна нет» — 404; чужой id — 404/400; путь только своего — 200 со своим.
WIN = {404}
EXPECT = {
    "/api/activity": WIN, "/api/ask": WIN, "/api/hint": WIN, "/api/history": WIN, "/api/last": WIN,
    "/api/screen": WIN, "/api/tts": WIN, "/api/send": WIN, "/api/resend": WIN | {400}, "/api/key": WIN,
    "/api/select": WIN, "/api/command": WIN, "/api/rename": WIN, "/api/title": WIN, "/api/starter": WIN | {400},
    "/api/steps": WIN, "/api/help/call": WIN, "/api/space/files": WIN, "/api/space/download": WIN,
    "/api/space/close": WIN | {400}, "/api/repos/add": WIN | {400, 403}, "/api/repos/remove": WIN | {400, 403},
    "/api/tty": {403, 404}, "/api/tty/type": {403, 404}, "/api/tty/key": {403, 404}, "/api/tty/size": {403, 404},
    "/api/project": {404, 400}, "/api/project/sessions": {404, 400}, "/api/project/history": {404, 400},
    "/api/project/session": {404, 400}, "/api/project/resume": {404, 400},
    "/api/space/resume": {400, 404}, "/api/space/delete": {400, 404}, "/api/space/restore": {400, 404},
    "/api/drafts/yes": {400, 404}, "/api/drafts/no": {400, 404},
    "/api/apitokens/revoke": {400, 404}, "/api/stt/job": {404}, "/api/stt/retry": {404},
    "/api/rec/status": {200, 400, 404}, "/api/rec/finish": {400, 404}, "/api/rec/drop": {200, 400, 404},
    "/api/invite/qr": {404}, "/api/push/unsubscribe": {200, 400}, "/api/passkeys/remove": {400, 404},
}


def routes() -> dict[str, dict]:
    return api_spec.scan()


def test_every_space_path_is_probed_or_explained():
    """Опись и SPACE_OK согласованы: каждый путь пространства есть в описи; не проверяемые — с причиной."""
    spec = routes()
    assert not access.SPACE_OK - set(spec)
    assert set(NOT_CHECKED) <= access.SPACE_OK
    assert all(NOT_CHECKED.values())


def test_space_a_cannot_read_or_change_space_b(iso):
    w = iso
    mine = open_tester_session(w)
    pool = foreign(w)
    before = snapshot(w)
    spec = routes()
    seen: dict[tuple[str, str], set[int]] = {}
    bad: list = []
    for path in sorted(access.SPACE_OK - set(NOT_CHECKED)):
        for method in sorted(spec[path]["methods"]):
            for data in variants(spec[path]["in"], pool):
                code, body = request(w, method, path, data, cookie_of(w))
                seen.setdefault((path, method), set()).add(code)
                if code >= 500 or leaks(body):
                    bad.append((method, path, data, code, leaks(body) or body))
                want = EXPECT.get(path)
                if want and code not in want and code != 403:
                    bad.append((method, path, data, code, "ожидали " + str(sorted(want)), body))
    assert not bad, "\n".join(map(repr, bad))
    # каждый путь пространства прошёл перебор (кроме NOT_CHECKED с причиной)
    assert {p for p, _ in seen} == access.SPACE_OK - set(NOT_CHECKED)
    assert w["drafts"].slugs == {"demo"}                 # черновики other и владельца не открывались вовсе
    after = snapshot(w)
    for k in before:
        assert before[k] == after[k], k
    # своё по-прежнему работает: перебор не сломал вход и окно тестировщика
    assert [s["id"] for s in call(w, "/api/sessions")[1]["sessions"] if s["id"] == mine] == [mine]


def test_people_of_other_space_not_in_any_listing(iso):
    """Люди: /api/people закрыт; meta, sessions, projects, черновики, токены, подписки — без людей other и владельца.
    Владельческие сводки (задачи, расход, воронка, «Поделиться», люди) — 403 code=space."""
    w = iso
    open_tester_session(w)
    for path in ("/api/meta", "/api/sessions", "/api/projects", "/api/drafts", "/api/apitokens", "/api/push/devices",
                 "/api/space/sessions", "/api/space/mcp", "/api/scenarios", "/api/voice/cards", "/api/prefs",
                 "/api/persona", "/api/terms", "/api/passkeys", "/api/starters", "/api/notify/prefs"):
        code, body = call(w, path)
        assert code == 200, (path, code, body)
        assert not leaks(body), (path, leaks(body))
    for path in ("/api/people", "/api/tasks", "/api/spend", "/api/funnel", "/api/spaces", "/api/focus/list",
                 "/api/share/list", "/api/team", "/api/q/list", "/api/meetings"):
        code, body = call(w, path)
        assert code in (403, 404), (path, code)
        assert not leaks(body), path
    # черновики: только своего пространства (у demo их нет), чужое «Нет» — не доходит до other
    assert call(w, "/api/drafts")[1]["drafts"] == []
    # токены: только свои; чужой токен отозвать нельзя
    assert [x["name"] for x in call(w, "/api/apitokens")[1].get("tokens", [])] == ["Мой"]


def test_every_owner_path_is_closed_to_space(iso):
    """Всё, чего нет в SPACE_OK (и что не открыто до входа), человеку пространства — 403, без данных."""
    w = iso
    spec = routes()
    bad = []
    for path, r in sorted(spec.items()):
        if path in access.SPACE_OK or r.get("v1") or "{" in path or path.startswith(("/api/focus/bridge", "/api/mt")):
            continue
        for method in sorted(set(r["methods"]) - set(r["open"])):
            code, body = request(w, method, path, {"space": "other", "w": w["other_w"], "id": w["task"]["id"]},
                                 cookie_of(w))
            if code != 403 or leaks(body):
                bad.append((method, path, code, leaks(body) or body))
    assert not bad, "\n".join(map(repr, bad))


def bearer(tok) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def test_v1_token_of_space_sees_only_its_space(iso):
    """/api/v1 с токеном человека demo: все пути описи — с чужими id → без чужих данных; задачи владельца — 403."""
    w = iso
    mine = open_tester_session(w)
    pool = foreign(w)
    before = snapshot(w)
    bad = []
    for path, r in sorted(routes().items()):
        if not r.get("v1"):
            continue
        for method in sorted(r["methods"]):
            for data in variants(r["in"], pool):
                code, body = request(w, method, path, data, bearer(w["tok_mine"]["token"]))
                if code >= 500 or leaks(body):
                    bad.append((method, path, data, code, leaks(body) or body))
                if r["v1"] in ("/api/tasks", "/api/tasks/add", "/api/tasks/update") and code != 403:
                    bad.append((method, path, code, "задачи владельца — только 403"))
    assert not bad, "\n".join(map(repr, bad))
    after = snapshot(w)
    for k in before:
        assert before[k] == after[k], k
    code, d = request(w, "GET", "/api/v1/sessions", {}, bearer(w["tok_mine"]["token"]))
    assert code == 200 and [s["id"] for s in d["sessions"]] == [mine]
    # и в обратную сторону: токен other не видит окна demo
    code, d = request(w, "GET", "/api/v1/sessions", {}, bearer(w["tok_other"]["token"]))
    assert code == 200 and {s["id"] for s in d["sessions"]} == {w["other_w"]}
    code, d = request(w, "GET", "/api/v1/history", {"w": mine}, bearer(w["tok_other"]["token"]))
    assert code == 404, (code, d)


def test_push_subscribe_not_dict_is_400(iso):
    """Перебор нашёл: ``sub`` строкой ронял обработчик (AttributeError, соединение без ответа) — теперь 400."""
    code, body = call(iso, "/api/push/subscribe", {"sub": "1"})
    assert code == 400 and "подписки" in body["error"]


def test_logout_ends_only_own_session(iso):
    w = iso
    assert call(w, "/api/logout", {})[0] == 200
    assert call(w, "/api/sessions")[0] == 401
    assert call(w, "/api/sessions", who=OWNER)[0] == 200
