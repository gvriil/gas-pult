"""Черновики действий коннекторов в «Ждут вашего Да» (drafts.py, штаб 21.11).

Настоящие серверы tmux пространств (фикстура ``world`` из tests/test_tenant_testers.py). Проверяем изоляцию:
владелец видит и подтверждает только свои черновики, человек пространства — только своего пространства (чужое
пространство и черновики владельца — нет), участник без пространства — ничего; «Да» ставит отметку ровно этому
черновику — коннектор выполняет его (``_core.take_confirmed``), «Нет» — выполнить уже нельзя; плохие id и имена
сервиса не доходят до файлов; «Да» свежей сессии браузера — только после кода.
"""

import json
import os
import time

import pytest
from test_tenant_testers import MEMBER, OWNER, TESTER, call, world  # noqa: F401

from gas_pult import drafts, webauth
from gas_pult.connectors import _core

CONF = ".local/state/gas-pult/confirm"


def old_sessions(w):
    """«Да» — как команда на сервере: сессии старше суток, чтобы не спрашивать код (его проверяет свой тест)."""
    a = w["p"].auth
    d = a._load() if hasattr(a, "_load") else None
    if d is None:
        pytest.skip("нет хранилища сессий")
    for tok in w["tok"].values():
        if (h := webauth._h(tok)) in d:
            d[h]["created"] = time.time() - webauth.CONFIRM_FRESH - 60
    a._save(d)


def put(dirpath, svc, summary, params=None, pane=""):
    """Черновик как от коннектора (тот же формат, что ``_core.propose``) в папке подтверждений ``dirpath``."""
    old = os.environ.get("GAS_CONFIRM_DIR")
    os.environ["GAS_CONFIRM_DIR"] = str(dirpath)
    try:
        if pane:
            os.environ["TMUX_PANE"] = pane
        d = _core.propose(svc, "create_order", params or {"sum": 100}, summary)
    finally:
        os.environ.pop("TMUX_PANE", None)
        if old is None:
            os.environ.pop("GAS_CONFIRM_DIR", None)
        else:
            os.environ["GAS_CONFIRM_DIR"] = old
    return d["id"]


@pytest.fixture
def three(world, tmp_path, monkeypatch):  # noqa: F811
    """Черновики у владельца, в своём пространстве тестировщика (demo) и в чужом (other)."""
    w = world
    own = tmp_path / "owner-confirm"
    monkeypatch.setenv("GAS_CONFIRM_DIR", str(own))            # владелец — своя папка (не настоящая домашняя)
    ids = {"owner": put(own, "moysklad", "Заказ владельца"),
           "demo": put(w["root"] / "demo/home" / CONF, "moysklad", "Заказ пространства demo"),
           "other": put(w["root"] / "other/home" / CONF, "ozon", "Чужой заказ")}
    old_sessions(w)
    return w, own, ids


def test_each_sees_only_own(three):
    w, _own, ids = three
    code, d = call(w, "/api/drafts", who=TESTER)
    assert code == 200 and [x["id"] for x in d["drafts"]] == [ids["demo"]], d
    assert d["drafts"][0]["summary"] == "Заказ пространства demo" and d["drafts"][0]["svc"] == "moysklad"
    assert "params" not in d["drafts"][0] and "digest" not in d["drafts"][0]
    code, d = call(w, "/api/drafts", who=OWNER)
    assert code == 200 and [x["id"] for x in d["drafts"]] == [ids["owner"]], d
    code, d = call(w, "/api/drafts", who=MEMBER)
    assert code != 200 and "drafts" not in d


def test_tester_yes_confirms_exactly_own_draft(three, monkeypatch, tmp_path):
    """«Да» тестировщика — в памяти панели (не файлом); коннектор пространства спрашивает панель своим токеном
    моста и выполняет ровно этот черновик, один раз."""
    w, _own, ids = three
    demo = w["root"] / "demo/home" / CONF
    code, d = call(w, "/api/drafts/yes", {"svc": "moysklad", "id": ids["demo"]}, who=TESTER)
    assert code == 200 and d == {"ok": True}, d
    assert not list(demo.rglob("*.ok"))                         # на диске «Да» нет
    code, d = call(w, "/api/drafts", who=TESTER)
    assert code == 200 and d["drafts"] == []                    # уже «Да» — снова не показываем
    tok = space_token(w, "demo", tmp_path)
    monkeypatch.setenv("GAS_CONFIRM_DIR", str(demo))
    monkeypatch.setenv("GAS_PULT_PANEL_URL", w["base"])
    monkeypatch.setenv("GAS_PULT_BRIDGE_TOKEN_FILE", str(tok))
    rec = _core.take_confirmed("moysklad", ids["demo"], need_flag=False)
    assert rec["summary"] == "Заказ пространства demo"


def space_token(w, slug, tmp_path):
    """Токен моста пространства (как ``pult-tenant bridge``): у пульта — только хэш, у пространства — файл."""
    import hashlib
    t = "space-token-" + slug
    (w["root"] / slug / "bridge.sha256").write_text(hashlib.sha256(t.encode()).hexdigest())
    f = tmp_path / f"{slug}.token"
    f.write_text(t)
    return f


def test_no_cross_space_or_owner(three):
    w, own, ids = three
    # тестировщик — по id владельца и чужого пространства: черновика «нет», отметок не появилось
    for svc, pid in (("moysklad", ids["owner"]), ("ozon", ids["other"])):
        code, d = call(w, "/api/drafts/yes", {"svc": svc, "id": pid}, who=TESTER)
        assert code != 200 and "не найден" in json.dumps(d, ensure_ascii=False), d
    # владелец — по id пространства: у него такого нет
    code, d = call(w, "/api/drafts/yes", {"svc": "moysklad", "id": ids["demo"]}, who=OWNER)
    assert code != 200
    code, d = call(w, "/api/drafts/no", {"svc": "moysklad", "id": ids["owner"]}, who=MEMBER)
    assert code != 200
    oks = [p for p in w["root"].rglob("*.ok")] + list(own.rglob("*.ok"))
    assert oks == [], oks
    assert (own / "moysklad" / f"{ids['owner']}.json").is_file()


def test_owner_no_rejects(three):
    w, own, ids = three
    code, d = call(w, "/api/drafts/no", {"svc": "moysklad", "id": ids["owner"]}, who=OWNER)
    assert code == 200
    assert (own / "moysklad" / f"{ids['owner']}.rejected").is_file()
    assert not (own / "moysklad" / f"{ids['owner']}.json").exists()
    with pytest.raises(_core.ToolError):
        os.environ["GAS_CONFIRM_DIR"] = str(own)
        _core.take_confirmed("moysklad", ids["owner"], need_flag=False)
    code, d = call(w, "/api/drafts", who=OWNER)
    assert d["drafts"] == []


@pytest.mark.parametrize("svc,pid", [("../moysklad", "0123456789ab"), ("moysklad", "../../x"),
                                     ("moysklad", "0123456789AB"), ("moy sklad", "0123456789ab"),
                                     ("moysklad", "0123456789ab; rm -rf ~")])
def test_bad_ids_refused(three, svc, pid):
    w = three[0]
    code, d = call(w, "/api/drafts/yes", {"svc": svc, "id": pid}, who=TESTER)
    assert code != 200 and "неверный черновик" in json.dumps(d, ensure_ascii=False), d


def test_yes_is_confirm_protected():
    from gas_pult import access
    assert "/api/drafts/yes" in access.CONFIRM and set(access.DRAFTS) <= access.SPACE_OK
    assert "/api/drafts/no" not in access.CONFIRM


def test_digest_matches_core(tmp_path, monkeypatch):
    """Отпечаток, который панель берёт для «Да», — тот же, что проверит коннектор (``_core._digest``)."""
    monkeypatch.setenv("GAS_CONFIRM_DIR", str(tmp_path))
    pid = put(tmp_path, "bitrix24", "Сделка", {"title": "Х", "sum": 5})
    rec = json.loads((tmp_path / "bitrix24" / f"{pid}.json").read_text())
    assert drafts.digest(None, "bitrix24", pid) == _core._digest(rec["action"], rec["params"])


def test_tampered_params_not_executed(tmp_path, monkeypatch):
    """Подменили параметры после «Да» — коннектор не выполнит: отпечаток не сходится."""
    from gas_pult import approvals
    monkeypatch.setenv("GAS_CONFIRM_DIR", str(tmp_path))
    ap = approvals.Approvals()
    pid = put(tmp_path, "wildberries", "Цена 100")
    ap.grant("", "wildberries", pid, drafts.digest(None, "wildberries", pid))
    f = tmp_path / "wildberries" / f"{pid}.json"
    rec = json.loads(f.read_text())
    rec["params"] = {"sum": 1}
    f.write_text(json.dumps(rec))
    with pytest.raises(_core.ToolError):
        _core.take_confirmed("wildberries", pid, need_flag=False, approve=lambda s, i, d: ap.take("", s, i, d))


def test_origin_chat_pane(three):
    """Черновик помнит окно чата (TMUX_PANE): панель вернёт в этот чат; чужая панель — не чат."""
    w, _own, ids = three
    from gas_pult import tenants
    tm = tenants.tmux_of("demo")
    wid = tm.new_window("demo-drafts", str(w["root"] / "demo/home"), "sleep 600")
    pane = tm.run("display-message", "-p", "-t", wid, "#{pane_id}").strip()
    pid = put(w["root"] / "demo/home" / CONF, "ozon", "Из чата", pane=pane)
    _code, d = call(w, "/api/drafts", who=TESTER)
    got = {x["id"]: x["w"] for x in d["drafts"]}
    assert got[pid] == f"t:demo:{wid}" and got[ids["demo"]] is None
    assert drafts.chat_of(tm, "%999999", "demo") is None and drafts.chat_of(tm, "@1;ls", "demo") is None


def test_panel_cards_wired():
    """Карточки — часть js/drafts.js (не в ядре); «Да» уходит в чат, откуда черновик; в фокус-ссылке — нет."""
    from pathlib import Path
    web = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
    js, page = (web / "js/drafts.js").read_text(), (web / "index.html").read_text()
    assert 'api("/api/drafts/yes"' in js and 'api("/api/drafts/no"' in js and 'api("/api/send", { w: d.w' in js
    assert "data-drf-yes" in js and "data-drf-edit" in js and "data-drf-no" in js
    assert 'SIM.drf ??= await part("drafts")' in page and "!FOCUS && meta?.role !== \"viewer\"" in page
