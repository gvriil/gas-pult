"""Недельный лимит подписки рядом с расходом за сегодня и в /status (владелец 24.11: «показывать недельные лимиты —
а то мы невидимы»): уровень по порогам 70/85 %, темп — прогноз к сбросу или когда кончится."""
from pathlib import Path

from gas_pult import ctxsnap

DAY = 86400


def test_levels_and_pace():
    now = 1_000_000_000.0
    reset = now + 2 * DAY                                  # прошло 5 дней из 7
    w = ctxsnap.week({"used": 50, "resets_at": reset}, now)
    assert w["level"] == "ok" and w["proj"] == 70 and w["out_at"] is None     # 50 % за 5 дней → 70 % к сбросу
    w = ctxsnap.week({"used": 73, "resets_at": reset}, now)
    assert w["level"] == "warn" and w["proj"] == 102 and now < w["out_at"] < reset
    assert ctxsnap.week({"used": 90, "resets_at": reset}, now)["level"] == "bad"
    early = ctxsnap.week({"used": 1, "resets_at": now + 7 * DAY - 600}, now)    # первые минуты недели
    assert early["proj"] is None and early["level"] == "ok"
    assert ctxsnap.week(None) is None and ctxsnap.week({"used": None, "resets_at": reset}) is None


def test_text_for_bot():
    t = ctxsnap.week_text({"used": 71, "resets_at": 1_900_000_000, "level": "warn", "proj": 98, "out_at": None})
    assert t.startswith("Неделя 71 % · сброс ") and t.endswith("к сбросу ≈ 98 %")
    assert "кончится ≈" in ctxsnap.week_text({"used": 80, "resets_at": 1_900_000_000, "proj": 120,
                                               "out_at": 1_899_900_000})
    assert ctxsnap.week_text(None) == ""


def test_limits_carry_week(tmp_path):
    import json
    import time
    snap = {"rate_limits": {"seven_day": {"used_percentage": 72, "resets_at": time.time() + DAY}}}
    (tmp_path / "0e80a522-eb39-4ed8-a4bb-40620386452e.json").write_text(json.dumps(snap))
    L = ctxsnap.limits(tmp_path)
    assert L["week"]["used"] == 72 and L["week"]["level"] == "warn"


def test_panel_chip_and_model_label():
    page = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/index.html").read_text(encoding="utf-8")
    assert "function weekChip()" in page and "weekChip() + costSum()" in page
    assert '|| "Авто";' in page and '|| "Модель";' not in page
