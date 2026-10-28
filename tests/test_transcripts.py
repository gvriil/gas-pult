import json

from gas_pult import transcripts as t


def user(text):
    return {"type": "user", "message": {"content": text}}


def assistant(text, stop=None):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}], "stop_reason": stop}}


def test_turn_collects_until_end_turn():
    turns = t.Turns()
    assert turns.feed(user("привет")) is None
    assert turns.feed(assistant("Смотрю файлы.", "tool_use")) is None
    assert turns.feed({"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}) is None
    assert turns.feed(assistant("Готово.", "end_turn")) == "Смотрю файлы.\n\nГотово."


def test_empty_and_dot_turns_are_dropped():
    turns = t.Turns()
    assert turns.feed(assistant(".", "end_turn")) is None
    assert turns.feed(assistant("", "end_turn")) is None


def test_sidechain_ignored_and_new_prompt_resets():
    turns = t.Turns()
    turns.feed(assistant("черновик", "tool_use"))
    assert turns.feed({**assistant("субагент", "end_turn"), "isSidechain": True}) is None
    turns.feed(user("новый вопрос"))
    assert turns.feed(assistant("ответ", "end_turn")) == "ответ"


def test_is_real_prompt():
    assert t.is_real_prompt(user("сделай"))
    assert not t.is_real_prompt(user("<system-reminder>x</system-reminder>"))
    assert not t.is_real_prompt({**user("x"), "isMeta": True})


def test_clean_for_speech():
    md = "# Итог\n\n**Готово**: [док](https://x.y)\n\n```bash\nls\n```\n| a | b |\n|---|---|"
    out = t.clean(md)
    assert "Блок кода пропущен" in out and "док" in out
    assert "https" not in out and "**" not in out and "---" not in out


def test_tail_reads_only_complete_lines(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text(json.dumps({"a": 1}) + "\n" + '{"b":')
    tail = t.Tail()
    tail.track(f, from_start=True)
    assert list(tail.read(f)) == [{"a": 1}]
    with open(f, "a") as fh:
        fh.write(" 2}\n")
    assert list(tail.read(f)) == [{"b": 2}]


def test_last_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(t, "CLAUDE_PROJECTS", tmp_path)
    d = t.project_dir("/home/u/proj")
    d.mkdir(parents=True)
    rows = [user("раз"), assistant("первый", "end_turn"), user("два"), assistant("а", "tool_use"),
            assistant("б", "end_turn")]
    (d / "x.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert t.last_answer("/home/u/proj") == "а\n\nб"


def test_clean_drops_emoji_and_backslashes():
    out = t.clean("Чего нет: кнопки «▶️ Выполнить» и 🔊 озвучки \\ ✅")
    assert "▶" not in out and "🔊" not in out and "\\" not in out and "✅" not in out
    assert "Выполнить" in out and "озвучки" in out
