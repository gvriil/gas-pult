"""Граница модуля платежей: billing не импортирует бота и панель; панель импортирует только billing.api;
права на пути billing — в access (только владелец, изменения — с кодом подтверждения)."""

import ast
from pathlib import Path

from gas_pult import access
from gas_pult.billing import api

SRC = Path(__file__).resolve().parents[1] / "src" / "gas_pult"
FORBIDDEN = {"bot", "webapp", "telegram", "tmux", "panel", "access", "people", "config"}


def imports(path: Path) -> set[str]:
    out = set()
    for n in ast.walk(ast.parse(path.read_text())):
        if isinstance(n, ast.ImportFrom):
            mod = ("." * n.level) + (n.module or "")
            out |= {f"{mod}.{a.name}" if n.module else f"{mod}{a.name}" for a in n.names} | {mod}
        elif isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
    return out


def test_billing_imports_nothing_of_pult():
    for f in (SRC / "billing").glob("*.py"):
        for m in imports(f):
            parts = m.lstrip(".").split(".")
            assert not (m.startswith("gas_pult") and parts[1:2] and parts[1] != "billing"), (f.name, m)
            assert not (set(parts) & FORBIDDEN), (f.name, m)


def test_webapp_uses_only_billing_api():
    used = {m for m in imports(SRC / "webapp.py") if "billing" in m}
    assert used == {"gas_pult.billing", "gas_pult.billing.api"}, used
    for f in SRC.glob("*.py"):                                   # никто, кроме панели, не тянет billing напрямую
        if f.name != "webapp.py":
            assert not {m for m in imports(f) if "billing" in m and m.startswith("gas_pult")}, f.name


def test_paths_owner_only_and_confirm():
    assert set(api.PATHS) == {*access.BILLING_GET, *access.BILLING_POST}
    assert set(api.PATHS) <= access.OWNER_ONLY and not set(api.PATHS) & access.ADMIN_OK
    assert set(api.POST) <= access.CONFIRM
