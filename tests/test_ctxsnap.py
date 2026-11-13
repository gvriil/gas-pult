"""Модель, усилие, % контекста и лимиты подписки — из снимка строки статуса (задание штаба 13.11, #179 P2.10).

Источник — ``~/.cache/claude-ctx/<session_id>.json`` (пишет ``~/.claude/statusline.py``); экран не разбираем."""

import json
import os
import time
from pathlib import Path

from test_project_chats import OPEN, call
from test_project_chats import server as server

from gas_pult import ctxsnap

INDEX = (Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html").read_text(encoding="utf-8")
SID = "52450695-0788-4599-b449-d8b62208a418"


def snap(d: Path, sid: str, **kw):
    raw = {"session_id": sid, "model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5"},
           "effort": {"level": "medium"},
           "context_window": {"used_percentage": 26, "remaining_percentage": 74, "context_window_size": 1000000},
           "rate_limits": {"five_hour": {"used_percentage": 21, "resets_at": time.time() + 3600},
                           "seven_day": {"used_percentage": 91, "resets_at": time.time() + 86400}},
           "cost": {"total_cost_usd": 7.5}, "workspace": {"current_dir": "/home/x"}, "effort_fallback": "high"}
    raw.update(kw)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sid}.json").write_text(json.dumps(raw))
    return raw


def test_read_and_parse(tmp_path):
    snap(tmp_path, SID)
    s = ctxsnap.read(SID, tmp_path)
    assert s["model"] == "Opus 5.5" and s["effort"] == "medium" and s["used"] == 26 and not s["effort_guess"]
    assert s["limits"]["five_hour"]["used"] == 21 and s["limits"]["seven_day"]["used"] == 91
    assert "cost" not in s and "workspace" not in s                  # пути и деньги панели не нужны


def test_effort_fallback_and_bad_input(tmp_path):
    snap(tmp_path, SID, effort=None)
    s = ctxsnap.read(SID, tmp_path)
    assert s["effort"] == "high" and s["effort_guess"]               # из настроек — с пометкой «?»
    assert ctxsnap.read("../../etc/passwd", tmp_path) is None        # только UUID
    assert ctxsnap.read("11111111-1111-4111-8111-111111111111", tmp_path) is None
    (tmp_path / f"{SID}.json").write_text("{битый")
    assert ctxsnap.read(SID, tmp_path) is None
    (tmp_path / f"{SID}.json").write_text(json.dumps({"context_window": {"used_percentage": "много"}}))
    assert ctxsnap.read(SID, tmp_path)["used"] is None


def test_limits_freshest_and_not_expired(tmp_path):
    old = "22222222-2222-4222-8222-222222222222"
    snap(tmp_path, old, rate_limits={"five_hour": {"used_percentage": 5, "resets_at": time.time() + 99}})
    os.utime(tmp_path / f"{old}.json", (time.time() - 600, time.time() - 600))
    snap(tmp_path, SID)
    L = ctxsnap.limits(tmp_path)
    assert L["limits"]["five_hour"]["used"] == 21                    # самый свежий снимок
    snap(tmp_path, SID, rate_limits={"five_hour": {"used_percentage": 99, "resets_at": time.time() - 5}})
    os.utime(tmp_path / f"{old}.json", (time.time() - 600, time.time() - 600))
    assert ctxsnap.limits(tmp_path) is None                          # сброс прошёл — устаревшее не показываем
    assert ctxsnap.limits(tmp_path / "нет") is None


def test_sessions_api_fields(server, monkeypatch, tmp_path):
    p, base, *_ = server
    monkeypatch.setenv("GAS_PULT_CTX_DIR", str(tmp_path / "ctx"))
    snap(tmp_path / "ctx", OPEN)
    code, d = call(base, "/api/sessions", tok=p.auth.issue(1))
    s = next(x for x in d["sessions"] if x["id"] == "@1")
    assert code == 200 and s["model"] == "Opus 5.5" and s["effort"] == "medium" and s["context"] == 74   # свободно %
    assert d["limits"]["limits"]["seven_day"]["used"] == 91
    code, d = call(base, "/api/sessions", tok=p.auth.issue(2))      # участник — лимиты владельца не видит
    assert code == 200 and d["limits"] is None


def test_ui_shows_line_under_input():
    assert 'id="sinfo"' in INDEX and "function sinfo(s)" in INDEX and "sinfo(s);" in INDEX
    assert "limitsInfo = d.limits" in INDEX and "resetAt(" in INDEX
