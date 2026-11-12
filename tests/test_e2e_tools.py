"""Инструменты эталонного прогона для разбиения пульта на модули (tests/e2e/run_all.py, measure_load.py,
miniapp_demo.py, smoke_demo.py): список сценариев, таблица замеров, Mini App — в браузере, если он есть."""

import importlib.util
import shutil
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

E2E = Path(__file__).resolve().parent / "e2e"
WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"


def load(name: str):
    sys.path.insert(0, str(E2E))
    spec = importlib.util.spec_from_file_location(name, E2E / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_run_all_takes_every_scenario_but_tools():
    names = load("run_all").scenarios()
    for tool in ("run_all", "measure_load", "demo_server", "ago_check"):
        assert tool not in names
    for must in ("miniapp_demo", "smoke_demo", "chat_keeps_place", "delivery_live", "notices_demo"):
        assert must in names
    on_disk = {p.stem for p in E2E.glob("*.py")} - {"run_all", "measure_load", "demo_server", "ago_check"}
    assert set(names) == on_disk                        # новый сценарий попадает в эталон сам


def test_measure_table_shows_before_after():
    m = load("measure_load")
    row = {k: 1.0 for k in m.KEYS} | {"own_bytes": 2048.0, "hit": 900.0}
    md = m.table({"390 home cold": row}, {"390 home cold": row | {"hit": 1000.0}})
    assert md.splitlines()[0].startswith("| сценарий | FCP")
    assert "1000 → 900" in md and "2.0 → 2.0" in md


def test_e2e_miniapp_in_browser():
    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        load("miniapp_demo").run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
