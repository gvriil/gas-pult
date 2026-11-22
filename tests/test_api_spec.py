"""Опись API (``gas_pult.api_spec``): пути из кода и описания совпадают, документы собраны генератором."""

import json
from pathlib import Path

from gas_pult import access, api_spec, personas

DOCS = Path(__file__).resolve().parents[1] / "docs"


def test_every_route_described_and_back():
    code = {p for p, r in api_spec.scan().items() if not r.get("v1")}   # /api/v1/… — описание исходного пути
    descr = set(api_spec.DESCR)
    assert not code - descr, "новые пути без описания — допишите api_spec.DESCR: " + ", ".join(sorted(code - descr))
    assert not descr - code, "описаны пути, которых в коде нет — уберите из DESCR: " + ", ".join(sorted(descr - code))


def test_access_tables_name_real_routes():
    """Каждый путь из таблиц прав — настоящий маршрут (таблица не держит мёртвых строк)."""
    named = set(personas.PATH_CAP)
    for v in vars(access).values():
        if isinstance(v, str) and v.startswith("/api/") and not v.endswith("/"):   # V1_PREFIX — префикс, не путь
            named.add(v)
        elif isinstance(v, (set, tuple, frozenset)) and all(isinstance(x, str) for x in v):
            named |= {x for x in v if x.startswith("/api/")}
        elif isinstance(v, dict) and all(isinstance(x, tuple) for x in v.values()):    # V1_GET / V1_POST: группа → пути
            named |= {x for xs in v.values() for x in xs}
    assert named - set(api_spec.scan()) == set()


def test_docs_in_sync():
    for path, text in api_spec.outputs().items():
        assert (DOCS / path.name).read_text(encoding="utf-8") == text, \
            f"{path.name} устарел — обновите: python -m gas_pult.api_spec"


def test_check_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(api_spec, "DOCS", tmp_path)
    assert api_spec.main(["--check"]) == 1                        # файлов нет — расхождение
    assert api_spec.main([]) == 0 and (tmp_path / "API.md").exists()
    assert api_spec.main(["--check"]) == 0


def test_roles_follow_access_tables():
    es = {(e["path"], e["method"]): e for e in api_spec.entries()}
    assert es["/api/run", "POST"]["role"] == "owner" and "CONFIRM" in es["/api/run", "POST"]["tags"]
    assert es["/api/people", "GET"]["role"] == "admin"
    assert es["/api/send", "POST"]["role"] == "member" and "BUDGET" in es["/api/send", "POST"]["tags"]
    assert es["/api/meta", "GET"]["role"] == "viewer" and "TERMS_FREE" in es["/api/meta", "GET"]["tags"]
    assert es["/api/prefs", "POST"]["role"] == "viewer"           # личная настройка — и наблюдателю
    assert es["/api/mcp", "GET"]["role"] == "member"              # MEMBER_ONLY — и на чтение
    assert es["/api/login/start", "POST"]["role"] == "open"
    assert es["/api/help/ask", "POST"]["role"] == "viewer" and "и до входа" in es["/api/help/ask", "POST"]["tags"]
    assert es["/api/focus/bridge/pair", "POST"]["role"] == "focus"
    assert es["/api/q/{code}", "GET"]["role"] == "open" and es["/api/q/list", "GET"]["role"] == "owner"
    assert es["/api/login/oidc/{provider}/{step}", "GET"]["role"] == "open"
    assert es["/api/v1/sessions", "GET"]["role"] == "token" and "v1:sessions" in es["/api/v1/sessions", "GET"]["tags"]
    assert es["/api/v1/send", "POST"]["role"] == "token" and "/api/send" in es["/api/v1/send", "POST"]["summary"]
    tok = es["/api/apitokens/new", "POST"]
    assert tok["role"] == "member" and "SLINK_NO" in tok["tags"]
    assert es["/api/history", "GET"]["in"][:2] == ["w", "before"]  # окно сессии — из общего w = self.win(…)


def test_scan_sees_new_branch():
    src = '''
class H:
    def get(self, path, q):
        w = self.win(q.get("w"))
        if path == "/api/x":
            return {"a": q.get("b")}
        if path in ("/api/y", "/api/z"):
            return panel.y()
    def post(self, path):
        if path == "/api/x":
            return {}
'''
    r = api_spec.scan(src)
    assert set(r) == {"/api/x", "/api/y", "/api/z"}
    assert r["/api/x"]["methods"] == ["GET", "POST"] and r["/api/x"]["in"] == ["w", "b"] and r["/api/x"]["out"] == ["a"]
    assert r["/api/y"]["calls"] == ["Panel.y"]


def test_scan_sees_route_tables(tmp_path):
    """Таблицы ``routes/*.py`` — как ветки цепочки: метод по таблице, поля из тела функции, ``GET_W`` — окно ``w``."""
    f = tmp_path / "area.py"
    f.write_text('''
def a(self, q, w):
    return {"x": q.get("y")}
def b(self, b):
    return panel.z(b.get("id"))
GET_W = {"/api/a": a}
POST = {"/api/b": b, "/api/c": b}
''', encoding="utf-8")
    r = api_spec.scan("class H:\n    pass\n", routes=[f])
    assert set(r) == {"/api/a", "/api/b", "/api/c"}
    assert r["/api/a"]["methods"] == ["GET"] and r["/api/a"]["in"] == ["w", "y"] and r["/api/a"]["out"] == ["x"]
    assert r["/api/b"]["methods"] == ["POST"] and r["/api/b"]["in"] == ["id"] and r["/api/b"]["calls"] == ["Panel.z"]
    assert not r["/api/b"]["focus_only"] and r["/api/b"]["open"] == []


def test_openapi_shape():
    doc = json.loads(api_spec.openapi_json())
    assert doc["openapi"] == "3.1.0"
    ops = [op for item in doc["paths"].values() for op in item.values()]
    assert len(ops) == len(api_spec.entries())
    ids = [op["operationId"] for op in ops]
    assert len(ids) == len(set(ids))
    assert all("200" in op["responses"] and op["summary"] for op in ops)
    assert doc["paths"]["/api/q/{code}"]["get"]["parameters"][0] == {
        "name": "code", "in": "path", "required": True, "schema": {"type": "string"}}
