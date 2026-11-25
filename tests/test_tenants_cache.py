"""Кэш пространств по подписи файлов (замер 24.11: обход и чтение описаний на каждый /api/sessions — очередь при
100 клиентах). Любое изменение — новое пространство, правка tenant.json или budget.json — видно сразу;
копия не портит кэш."""
import json
import os

from gas_pult import tenants


def test_cache_sees_changes(tmp_path):
    root = tmp_path / "t"
    root.mkdir()
    (root / tenants.MARKER).write_text(json.dumps({"tmux": "/usr/bin/tmux"}))
    (root / "sp0001").mkdir()
    (root / "sp0001" / tenants.META).write_text(json.dumps({"title": "А"}))
    assert tenants.slugs(root) == ["sp0001"]
    (root / "sp0002").mkdir()                                # новое пространство — папка изменилась
    assert tenants.slugs(root) == ["sp0001", "sp0002"]
    a = tenants.load("sp0001", root)
    a["title"] = "испорчено"                                 # вызывающий меняет копию — кэш цел
    assert tenants.load("sp0001", root)["title"] == "А"
    f = root / "sp0001" / tenants.META
    f.write_text(json.dumps({"title": "Б"}))
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 1000))
    assert tenants.load("sp0001", root)["title"] == "Б"
    assert tenants.marker(root)["tmux"] == "/usr/bin/tmux"
    (root / tenants.MARKER).unlink()
    assert tenants.marker(root) is None
