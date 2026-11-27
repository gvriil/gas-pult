"""«Подписки и балансы» (GAS-60 Ф1): реестр сроков только на чтение; «осталось N дней», пороги 14/3/1, просроченное —
отдельно; строки без даты не прячутся; неделя Claude и расход; маршрут — только владельцу."""
import datetime as dt
import json

from gas_pult import access, deadlines

MD = """# Реестр

| Что | Где | Когда кончается | Сколько стоит | Баланс |
|---|---|---|---|---|
| **Сервер А** | бот | 24.11.2026 | 37 $ | **5,50 $** |
| Домен б | reg | 30.11.2026 | — | — |
| Хостинг в | x | 10.12.2026 | — | — |
| Касса г | x | 05.03.2027 | — | — |
| Кредиты д | x | — (предоплата) | — | 16 $ |

| Другая таблица | без колонки срока |
|---|---|
| не берём | — |
"""


def test_rows_levels_and_no_date_kept(tmp_path):
    f = tmp_path / "s.md"
    f.write_text(MD, encoding="utf-8")
    before = f.read_bytes()
    out = deadlines.items([str(f)], today=dt.date(2026, 11, 27))
    got = [(x["what"], x["days"], x["level"]) for x in out]
    assert got == [("Сервер А", -3, "over"), ("Домен б", 3, "d3"), ("Хостинг в", 13, "d14"),
                   ("Касса г", 98, "ok"), ("Кредиты д", None, "none")]
    assert out[0]["balance"] == "5,50 $" and f.read_bytes() == before          # только чтение
    assert deadlines.level(1) == "d1" and deadlines.level(0) == "d1"


def test_claude_week_and_cost(tmp_path):
    f = tmp_path / "claude-limits.json"
    f.write_text(json.dumps({"reset": 1795806000, "sent": ["pace", 70, 85]}), encoding="utf-8")
    assert deadlines.claude_week(f) == {"passed": 85, "reset": 1795806000}
    assert deadlines.claude_week(tmp_path / "нет.json") is None
    assert deadlines.cost("") == ""
    assert deadlines.cost("echo 'За 24 ч: $1.00'", now=1.0) == "За 24 ч: $1.00"


def test_missing_files_and_owner_only():
    assert deadlines.items(["/нет/такого.md"]) == []
    assert "/api/deadlines" in access.OWNER_ONLY
