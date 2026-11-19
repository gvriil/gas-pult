"""«Шаги» (GAS-16, слой 7): сообщение → инструменты → ответ из журнала Claude Code; секреты скрыты; поиск."""

import json

from gas_pult import steps, webapp


def jl(path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return path


def test_turns_tools_results_answer_and_search(tmp_path):
    f = jl(tmp_path / "s.jsonl", [
        {"type": "user", "timestamp": "2026-11-19T10:00:00Z", "message": {"role": "user", "content": "проверь сборку"}},
        {"type": "assistant", "timestamp": "2026-11-19T10:00:02Z", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Bash",
             "input": {"command": "npm test", "description": "тесты"}}]}},
        {"type": "user", "timestamp": "2026-11-19T10:00:09Z", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True,
             "content": "FAIL token=abcdefghijklmnop1234"}]}},
        {"type": "assistant", "timestamp": "2026-11-19T10:00:12Z", "message": {"content": [
            {"type": "text", "text": "Один тест упал — чиню."}]}},
        {"type": "user", "timestamp": "2026-11-19T10:01:00Z", "message": {"role": "user", "content": "спасибо"}},
    ])
    t = steps.turns(f)
    assert [x["prompt"] for x in t] == ["спасибо", "проверь сборку"]                  # новые сверху
    first = t[1]
    assert first["answer"] == "Один тест упал — чиню." and first["dur"] == 12
    st = first["steps"][0]
    assert st["what"] == "Выполняет команду: тесты" and st["ok"] is False and st["dur"] == 7
    assert "abcdefghijklmnop1234" not in st["out"]                                    # секрет скрыт
    assert [x["prompt"] for x in steps.turns(f, "FAIL")] == ["проверь сборку"]
    assert steps.turns(f, "нет такого") == [] and steps.turns(None) == []


def test_api_and_roles():
    assert "/api/steps" in webapp.SPACE_OK and "/api/steps" not in webapp.FOCUS_GET
