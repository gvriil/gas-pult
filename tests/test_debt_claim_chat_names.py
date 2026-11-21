"""Сценарии под роль (штаб, из разговора владельца 20.11): бухгалтерия → «Напомнить должнику» → досудебная претензия
по шаблону с пометкой «не юридическая консультация», письмо — только после «Да». Названия чатов — по смыслу: кто, что,
сумма или срок («Долг: ООО Ромашка — 46 000 ₽, счёт за ноябрь, срок прошёл»), командой агента ``gas-pult title``."""
import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from gas_pult import projects, starters

SRC = Path(__file__).resolve().parents[1] / "src"


def test_debt_reminder_prompt_has_claim_template_and_yes_rule():
    p = starters.prompt("debt-reminder")
    assert "gas-pult title \"Долг: <кто> — <сумма>, <за что>, <срок прошёл или когда>\"" in p
    assert "досудебную претензию" in p and "ПРЕТЕНЗИЯ (досудебная)" in p
    assert "Не юридическая консультация" in p and "только после моего «Да»" in p
    assert p.rstrip().endswith("«Да / Нет / Позже».")


def test_every_starter_names_chat_by_meaning():
    for s in starters.load():
        if s.get("connect"):
            continue
        p = starters.prompt(s["id"])
        assert "gas-pult title" in p and "без кодов" in p, s["id"]


def test_template_lookup_is_safe():
    assert starters.template("pretrial-claim").startswith("Не юридическая консультация")
    for bad in ("../starters", "нет-такого", "a/b"):
        with pytest.raises(LookupError):
            starters.template(bad)


def run_title(tmp_path, *args, sid=None):
    import os
    env = {**os.environ, "PYTHONPATH": str(SRC), "GAS_PULT_DATA_DIR": str(tmp_path / "data")}
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    if sid:
        env["CLAUDE_CODE_SESSION_ID"] = sid
    return subprocess.run([sys.executable, "-m", "gas_pult", "title", *args], capture_output=True, text=True,
                          env=env, cwd=tmp_path, timeout=60)


def test_agent_names_its_chat(tmp_path):
    (tmp_path / "data").mkdir()
    sid = str(uuid.uuid4())
    r = run_title(tmp_path, "Долг:", "ООО Ромашка —", "46 000 ₽, счёт за ноябрь, срок прошёл", sid=sid)
    assert r.returncode == 0, r.stderr
    assert "Чат назван" in r.stdout
    d = json.loads((tmp_path / "data" / projects.FILE).read_text(encoding="utf-8"))
    assert d["sessions"][sid]["title"] == "Долг: ООО Ромашка — 46 000 ₽, счёт за ноябрь, срок прошёл"


def test_title_needs_session_and_text(tmp_path):
    (tmp_path / "data").mkdir()
    r = run_title(tmp_path, "Долг")
    assert r.returncode != 0 and "Не знаю, какой это чат" in r.stderr
    r = run_title(tmp_path, sid=str(uuid.uuid4()))
    assert r.returncode != 0 and "Название пустое" in r.stderr
    r = run_title(tmp_path, "x", sid="../../etc")                     # не id разговора
    assert r.returncode != 0
