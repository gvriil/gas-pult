"""Скрипт замера пользы (docs/PRODUCT.md): ходы агентов и доля сообщений через пульт — по журналам, без оценок."""

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "measure", Path(__file__).resolve().parents[1] / "tools" / "measure-agent-hours.py")
measure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measure)


def iso(h, m=0):
    return datetime(2026, 11, 10, h, m, tzinfo=UTC).isoformat().replace("+00:00", "Z")


def test_turns_hours_and_share(tmp_path, capsys):
    proj = tmp_path / "claude" / "p"
    proj.mkdir(parents=True)
    rows = [{"type": "user", "timestamp": iso(10), "message": {"content": "сделай"}},
            {"type": "assistant", "timestamp": iso(10, 1)},
            {"type": "user", "timestamp": iso(10, 2), "message": {"content": [{"type": "tool_result"}]}},
            {"type": "assistant", "timestamp": iso(10, 20)},                       # ход 20 мин — долгий
            {"type": "user", "timestamp": iso(11), "message": {"content": [{"type": "text", "text": "ещё"}]}},
            {"type": "assistant", "timestamp": iso(11, 2)},                        # ход 2 мин
            {"type": "user", "timestamp": iso(12), "isMeta": True, "message": {"content": "служебное"}},
            {"type": "assistant", "timestamp": iso(12, 1), "isSidechain": True}]
    (proj / "s.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (proj / "b.jsonl").write_text("\n".join(json.dumps({**r, "entrypoint": "sdk-cli"}) for r in rows[:2]) + "\n")
    t0 = datetime(2026, 11, 10, 9, tzinfo=UTC).timestamp()
    sends = tmp_path / "sends.jsonl"
    sends.write_text("\n".join(json.dumps({"ts": t0 + 3600 * i, "src": s})
                               for i, s in enumerate(("panel", "pult", "bot"))) + "\n")
    ts = measure.turns(str(tmp_path / "claude"), t0, t0 + 86400)
    inter = [x for x in ts if not x[2]]
    assert sorted(round(d / 60) for _, d, _ in inter) == [2, 20]               # tool_result — не новый ход
    assert len([x for x in ts if x[2]]) == 1                                    # плановый — отдельно
    assert measure.main(["--end", "2026-11-11", "--days", "2", "--claude", str(tmp_path / "claude"),
                         "--sends", str(sends)]) == 0
    out = capsys.readouterr().out
    assert "Ходов агентов (по сообщению человека): 2" in out and "ходов дольше 5 мин: 1" in out
    assert "через пульт 2 (100 %)" in out                                       # «pult» (сам пульт) — не человек
