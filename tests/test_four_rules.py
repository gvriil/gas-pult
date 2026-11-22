"""tools/four_rules.py — проверка «4 правил» (docs/FOUR-RULES.md): работает на текущем дереве, JSON валиден,
ОШИБКА даёт код 1, ПРЕДУПРЕЖДЕНИЕ — нет. pytest внутри не запускается (``--no-tests``): ключевые тесты и так
идут в общем прогоне, а сам скрипт с тестами — отдельным заданием CI."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "four_rules.py"


def _mod():
    spec = importlib.util.spec_from_file_location("four_rules", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), "--no-tests", *args], cwd=ROOT, capture_output=True,
                          text=True, timeout=300)


def test_current_tree_json_valid_and_no_errors():
    r = _run("--json")
    rep = json.loads(r.stdout)
    assert r.returncode == 0, [c for c in rep["checks"] if c["level"] == "error"]
    assert rep["ok"] is True and rep["errors"] == 0
    assert {c["rule"] for c in rep["checks"]} == {1, 2, 3, 4}
    for c in rep["checks"]:
        assert c["level"] in ("ok", "warn", "error") and c["item"] and isinstance(c["details"], list)


def test_table_output():
    r = _run()
    assert r.returncode == 0
    assert r.stdout.startswith("| Правило | Пункт | Итог | Где |")
    assert "ошибок 0" in r.stdout


def test_float_in_billing_is_error(tmp_path):
    m = _mod()
    b = tmp_path / "src" / "gas_pult" / "billing"
    b.mkdir(parents=True)
    (b / "money.py").write_text("def ok(now: float, x):\n    return isinstance(x, float)\n", encoding="utf-8")
    assert m.check_billing_float(tmp_path)["level"] == "ok"
    (b / "bad.py").write_text("def tax(x):\n    return float(x) * 0.2\n", encoding="utf-8")
    row = m.check_billing_float(tmp_path)
    assert row["level"] == "error" and row["details"] == ["src/gas_pult/billing/bad.py:2"] * 2


def test_warnings_do_not_fail_errors_do():
    m = _mod()
    warn = m.item(1, "x", m.WARN)
    err = m.item(4, "y", m.ERR)
    assert m.report([warn])["ok"] is True
    assert m.report([warn, err])["ok"] is False


def test_size_and_store_debt_listed(tmp_path):
    m = _mod()
    pkg = tmp_path / "src" / "gas_pult"
    pkg.mkdir(parents=True)
    (pkg / "big.py").write_text("x = 1\n" * (m.MAX_LINES + 1), encoding="utf-8")
    (pkg / "store.py").write_text("write_private(p, s)\n", encoding="utf-8")
    (pkg / "own.py").write_text("from x import write_private\nwrite_private(p, s)\n", encoding="utf-8")
    assert m.check_sizes(tmp_path)["details"] == [f"src/gas_pult/big.py: {m.MAX_LINES + 1}"]
    row = m.check_store(tmp_path)
    assert row["level"] == "warn" and row["details"] == ["src/gas_pult/own.py: 1"]
