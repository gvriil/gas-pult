"""Проверка «4 правил» (docs/FOUR-RULES.md): что из чек-листа проверяется машиной.

Запуск из корня репозитория::

    python tools/four_rules.py              # таблица «правило · пункт · итог · где»
    python tools/four_rules.py --json       # то же для ночной проверки (JSON в stdout)
    python tools/four_rules.py --no-tests   # без запуска pytest (быстро: только разбор кода)

Итог пункта: OK, ПРЕДУПРЕЖДЕНИЕ (ход работ — долг виден, CI не ломает), ОШИБКА (правило нарушено).
Код выхода 1 — только если есть ОШИБКА. Только стандартная библиотека; код пульта не импортируется и не меняется
(сверка API и тесты — отдельными процессами).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OK, WARN, ERR = "OK", "ПРЕДУПРЕЖДЕНИЕ", "ОШИБКА"
LEVEL = {OK: "ok", WARN: "warn", ERR: "error"}
MAX_LINES = 800                                     # цель docs/MONOLITH-PLAN.md п.2: ни одного файла больше ~800
STORE_OK = {"store.py", "config.py", "sqlstore.py"}  # где запись файла — своя работа модуля (слой хранения)

# Ключевые тесты: правило → [(файл, что доказывает)]. Нет файла — ОШИБКА, кроме помеченных «в PR».
KEY_TESTS = {
    1: [("tests/test_store.py", "хранилища JSON: замок, атомарная запись, версия схемы"),
        ("tests/test_sqlstore.py", "SQLite: режимы json/dual/sqlite, откат")],
    2: [("tests/test_module_boundaries.py", "границы модулей: кто кого не импортирует"),
        ("tests/test_billing_boundary.py", "платежи — отдельный модуль, панель — только через billing.api")],
    3: [("tests/test_api_spec.py", "опись API совпадает с кодом"),
        ("tests/test_api_v1.py", "/api/v1 с токенами для внешних систем (1С, CRM)")],
    4: [("tests/test_billing.py", "платежи: центы, журнал только с добавлением, подпись вебхука, идемпотентность"),
        ("tests/test_funnel.py", "аналитика событий: воронка вход → ответ → «Да»")],
}
PENDING = {"tests/test_api_v1.py": "/api/v1 ещё в PR"}  # нет файла — ПРЕДУПРЕЖДЕНИЕ, а не ОШИБКА


def item(rule: int, name: str, status: str, where: str = "", details=None) -> dict:
    return {"rule": rule, "item": name, "status": status, "level": LEVEL[status], "where": where,
            "details": details or []}


def py_files(root: Path):
    yield from sorted((root / "src" / "gas_pult").rglob("*.py"))


def rel(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix()


def parse(p: Path):
    try:
        return ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
    except (SyntaxError, UnicodeDecodeError):
        return None


# ── правило 1: фундамент ─────────────────────────────────────────────────────────────────────────────────────────


def check_sizes(root: Path) -> dict:
    big = []
    for p in py_files(root):
        n = sum(1 for _ in p.open(encoding="utf-8", errors="replace"))
        if n > MAX_LINES:
            big.append((n, rel(root, p)))
    big.sort(reverse=True)
    if not big:
        return item(1, f"файлы Python ≤ {MAX_LINES} строк", OK, "src/gas_pult")
    return item(1, f"файлы Python ≤ {MAX_LINES} строк", WARN, "docs/MONOLITH-PLAN.md",
                [f"{path}: {n}" for n, path in big])


def writes_outside_store(root: Path) -> list[str]:
    """Файлы, которые сами зовут ``write_private`` (запись мимо ``store``): долг перехода на общий слой."""
    out = []
    for p in py_files(root):
        if p.name in STORE_OK and p.parent.name == "gas_pult":
            continue
        tree = parse(p)
        if tree is None:
            continue
        n = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
                n += name == "write_private"
        if n:
            out.append(f"{rel(root, p)}: {n}")
    return out


def check_store(root: Path) -> dict:
    if not (root / "src/gas_pult/store.py").exists():
        return item(1, "хранилища JSON — через store", ERR, "src/gas_pult/store.py", ["нет общего слоя хранения"])
    rest = writes_outside_store(root)
    if not rest:
        return item(1, "хранилища JSON — через store", OK, "src/gas_pult/store.py")
    return item(1, "хранилища JSON — через store", WARN, "write_private вне store/config/sqlstore", rest)


def check_ci(root: Path) -> dict:
    ci = root / ".github/workflows/ci.yml"
    text = ci.read_text(encoding="utf-8") if ci.exists() else ""
    miss = [w for w in ("ruff check", "pytest", "tools/four_rules.py") if w not in text]
    return item(1, "CI: ruff, pytest и эта проверка", ERR if miss else OK, ".github/workflows/ci.yml",
                [f"нет шага: {w}" for w in miss])


# ── правило 2: модульный монолит ─────────────────────────────────────────────────────────────────────────────────


def check_known_violations(root: Path) -> dict:
    """``KNOWN`` в тесте границ — нарушения «как есть»: пусто — OK, есть — долг (ПРЕДУПРЕЖДЕНИЕ)."""
    p = root / "tests/test_module_boundaries.py"
    tree = parse(p) if p.exists() else None
    if tree is None:
        return item(2, "границы модулей: известных нарушений нет", ERR, rel(root, p), ["нет теста границ"])
    for node in tree.body:
        target = node.target if isinstance(node, ast.AnnAssign) else (
            node.targets[0] if isinstance(node, ast.Assign) else None)
        if isinstance(target, ast.Name) and target.id == "KNOWN" and isinstance(node.value, ast.Dict):
            keys = [ast.unparse(k) for k in node.value.keys if k is not None]
            return item(2, "границы модулей: известных нарушений нет", WARN if keys else OK,
                        "tests/test_module_boundaries.py: KNOWN", keys)
    return item(2, "границы модулей: известных нарушений нет", ERR, "tests/test_module_boundaries.py",
                ["не найден словарь KNOWN"])


# ── правило 3: API с первого дня ─────────────────────────────────────────────────────────────────────────────────


def check_api_spec(root: Path) -> dict:
    spec = root / "docs/openapi.json"
    try:
        json.loads(spec.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return item(3, "опись API совпадает с кодом", ERR, "docs/openapi.json", [f"не читается: {e}"])
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [str(root / "src"), os.environ.get("PYTHONPATH")])))
    r = subprocess.run([sys.executable, "-m", "gas_pult.api_spec", "--check"], cwd=root, env=env,
                       capture_output=True, text=True, timeout=120)
    out = [s for s in (r.stdout + r.stderr).strip().splitlines() if s][-5:]
    return item(3, "опись API совпадает с кодом", OK if r.returncode == 0 else ERR,
                "python -m gas_pult.api_spec --check", out if r.returncode else [])


# ── правило 4: экономить с умом (не на деньгах) ──────────────────────────────────────────────────────────────────


def float_uses(root: Path) -> list[str]:
    """В ``billing`` нет вычислений во float: литералов ``1.5`` и вызовов ``float(…)``.

    Аннотации (``now: float`` — время) и ``isinstance(x, float)`` (отказ на входе) — не вычисления, не считаются.
    """
    out = []
    for p in sorted((root / "src/gas_pult/billing").rglob("*.py")):
        tree = parse(p)
        if tree is None:
            out.append(f"{rel(root, p)}: не разбирается")
            continue
        for node in ast.walk(tree):
            bad = (isinstance(node, ast.Constant) and isinstance(node.value, float)) or (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float")
            if bad:
                out.append(f"{rel(root, p)}:{node.lineno}")
    return out


def check_billing_float(root: Path) -> dict:
    if not (root / "src/gas_pult/billing").is_dir():
        return item(4, "платежи: деньги без float", ERR, "src/gas_pult/billing", ["нет модуля платежей"])
    bad = float_uses(root)
    return item(4, "платежи: деньги без float", ERR if bad else OK, "src/gas_pult/billing", bad)


def check_journal_append_only(root: Path) -> dict:
    p = root / "src/gas_pult/billing/store.py"
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    miss = [t for t in ("BEFORE UPDATE ON journal", "BEFORE DELETE ON journal") if t not in text]
    return item(4, "платежи: журнал только с добавлением", ERR if miss else OK,
                "src/gas_pult/billing/store.py + tests/test_billing.py::test_journal_append_only",
                [f"нет триггера: {t}" for t in miss])


# ── ключевые тесты ───────────────────────────────────────────────────────────────────────────────────────────────


def run_pytest(root: Path, files: list[str]) -> dict[str, tuple[int, int]] | str:
    """Один запуск pytest на все файлы → {файл: (прошло, упало)}; строка — почему не запустился."""
    with tempfile.TemporaryDirectory() as d:
        xml = Path(d) / "r.xml"
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [str(root / "src"),
                                                                         os.environ.get("PYTHONPATH")])))
        try:
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}",
                                *files], cwd=root, env=env, capture_output=True, text=True, timeout=1200)
        except subprocess.TimeoutExpired:
            return "pytest не уложился в 20 минут"
        if not xml.exists():
            return "pytest не запустился: " + ((r.stdout + r.stderr).strip().splitlines() or ["?"])[-1]
        res = {f: [0, 0] for f in files}
        mods = {f: f.removesuffix(".py").replace("/", ".") for f in files}
        for tc in ET.parse(xml).iter("testcase"):
            cls = tc.get("classname", "")
            for f, m in mods.items():
                if cls == m or cls.startswith(m + "."):
                    failed = any(c.tag in ("failure", "error") for c in tc)
                    res[f][1 if failed else 0] += 1
        return {f: (a, b) for f, (a, b) in res.items()}


def check_tests(root: Path, run: bool) -> list[dict]:
    rows, present = [], []
    for rule, tests in KEY_TESTS.items():
        for f, what in tests:
            what = "тест: " + what
            if (root / f).exists():
                present.append((rule, f, what))
            elif f in PENDING:
                rows.append(item(rule, what, WARN, f, [f"нет файла: {PENDING[f]}"]))
            else:
                rows.append(item(rule, what, ERR, f, ["нет файла"]))
    if not run:
        return rows + [item(rule, what, OK, f, ["тест есть; не запускался (--no-tests)"]) for rule, f, what in present]
    res = run_pytest(root, [f for _, f, _ in present]) if present else {}
    for rule, f, what in present:
        if isinstance(res, str):
            rows.append(item(rule, what, ERR, f, [res]))
            continue
        passed, failed = res[f]
        if failed or not passed:
            rows.append(item(rule, what, ERR, f, [f"прошло {passed}, упало {failed}"]))
        else:
            rows.append(item(rule, what, OK, f, [f"прошло {passed}"]))
    return rows


# ── сборка и вывод ───────────────────────────────────────────────────────────────────────────────────────────────

RULES = {1: "MVP на фундаменте", 2: "модульный монолит", 3: "API с первого дня", 4: "экономить с умом"}


def collect(root: Path = ROOT, run_tests: bool = True) -> list[dict]:
    rows = [check_sizes(root), check_store(root), check_ci(root), check_known_violations(root),
            check_api_spec(root), check_billing_float(root), check_journal_append_only(root),
            *check_tests(root, run_tests)]
    return sorted(rows, key=lambda r: r["rule"])


def report(rows: list[dict]) -> dict:
    n = {lvl: sum(r["level"] == lvl for r in rows) for lvl in LEVEL.values()}
    return {"ok": n["error"] == 0, "errors": n["error"], "warnings": n["warn"], "passed": n["ok"],
            "rules": {str(k): v for k, v in RULES.items()}, "checks": rows}


def table(rows: list[dict]) -> str:
    lines = ["| Правило | Пункт | Итог | Где |", "|---|---|---|---|"]
    for r in rows:
        where = r["where"]
        d = r["details"]
        if d and r["level"] != "ok":
            where += " — " + "; ".join(d[:4]) + (f"; ещё {len(d) - 4}" if len(d) > 4 else "")
        lines.append(f"| {r['rule']}. {RULES[r['rule']]} | {r['item']} | {r['status']} | {where} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Проверка 4 правил (docs/FOUR-RULES.md)")
    ap.add_argument("--json", action="store_true", help="JSON для ночной проверки")
    ap.add_argument("--no-tests", action="store_true", help="не запускать pytest")
    ap.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    rep = report(collect(a.root.resolve(), not a.no_tests))
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print(table(rep["checks"]))
        print(f"\nOK {rep['passed']} · предупреждений {rep['warnings']} · ошибок {rep['errors']}")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
