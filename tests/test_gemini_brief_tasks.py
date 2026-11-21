"""Gemini 21.11, топ-15 №14: в Брифинге и Задачах — без строк разработки ([У]: PR GitHub, HANDOFF.md, «Выполнить
команду»); «Да» — сдержанная; на ПК Задачи — правой шторкой 400 px."""
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web/js"


def test_brief():
    js = (WEB / "brief.js").read_text(encoding="utf-8")
    assert 'const devOnly = (r) => !dev() && ["github", "handoff"].includes(r.source?.kind);' in js
    assert "b.decisions = (b.decisions || []).filter((r) => !devOnly(r));" in js
    # «Да» — компактная основная (владелец 21.11, «Сегодня» с первого взгляда): не на всю ширину;
    # «Нет / Позже / В чат» — тихие
    assert '<button class="btn sm" data-a="yes">Да</button>' in js
    assert ".brief .acts .btn { flex: none; width: auto;" in js
    assert ".brief .dec .acts .btn.quiet { background: transparent;" in js
    assert "/* Gemini №14: без грязной заливки */" in js


def test_tasks():
    js = (WEB / "tasks.js").read_text(encoding="utf-8")
    assert 'const mine = (t) => dev() || t.kind !== "command";' in js and "TASKS.filter(mine)" in js
    assert ".sheet-bg.side .sheet { width: 400px;" in js and 'if (split()) bg.classList.add("side")' in js
