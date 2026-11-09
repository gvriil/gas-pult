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


def test_history_pairs_turns(tmp_path, monkeypatch):
    monkeypatch.setattr(t, "CLAUDE_PROJECTS", tmp_path)
    d = t.project_dir("/home/u/p")
    d.mkdir(parents=True)
    rows = [{"type": "user", "message": {"content": "привет"}, "timestamp": "2026-10-29T10:00:00"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "а"}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "б"}], "stop_reason": "end_turn"}},
            {"type": "assistant", "isSidechain": True, "message": {"content": [{"type": "text", "text": "суб"}]}},
            {"type": "user", "message": {"content": "ещё"}, "timestamp": "2026-10-29T10:05:00"}]
    (d / "s.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    items, more = t.history("/home/u/p")
    assert [(x["role"], x["text"]) for x in items] == [("user", "привет"), ("assistant", "а\n\nб"), ("user", "ещё")]
    assert not more and items[1]["i"] == 1
    items, more = t.history("/home/u/p", limit=1, before=2)
    assert [x["i"] for x in items] == [1] and more


def test_history_shows_queued_messages(tmp_path, monkeypatch):
    monkeypatch.setattr(t, "CLAUDE_PROJECTS", tmp_path)
    d = t.project_dir("/home/u/q")
    d.mkdir(parents=True)
    pasted = '<pasted_content id="x">\nа ещё вот\n</pasted_content id="x">'
    rows = [{"type": "user", "message": {"content": "сделай"}, "timestamp": "2026-10-29T10:00:00"},
            {"type": "queue-operation", "operation": "enqueue", "content": pasted},
            {"type": "attachment", "attachment": {"type": "queued_command", "prompt": pasted}},
            {"type": "queue-operation", "operation": "enqueue", "content": "и это"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "готово"}],
                                              "stop_reason": "end_turn"}}]
    (d / "s.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    items, _ = t.history("/home/u/q")
    assert [(x["text"], x.get("queued")) for x in items if x["role"] == "user"] == \
        [("сделай", None), ("а ещё вот", "read"), ("и это", "wait")]


def test_history_no_service_bubbles_and_queue_settles(tmp_path, monkeypatch):
    """Ревью 09.11, п. 3: уведомления агентов и задач, письма других сессий, сводка после /compact — не пузыри
    человека; ``dequeue`` и ``remove`` закрывают «в очереди» — вечных «в очереди» нет."""
    monkeypatch.setattr(t, "CLAUDE_PROJECTS", tmp_path)
    d = t.project_dir("/home/u/j")
    d.mkdir(parents=True)
    note = "<task-notification><task-id>x1</task-id><status>completed</status></task-notification>"
    letter = "<agent-message from=\"other\">готово</agent-message>"

    def q(op, content=None):
        return {"type": "queue-operation", "operation": op, **({"content": content} if content is not None else {})}

    def att(prompt, mode="prompt"):
        return {"type": "attachment", "attachment": {"type": "queued_command", "prompt": prompt, "commandMode": mode}}

    def u(text, **kw):
        return {"type": "user", "message": {"content": text}, **kw}

    def a(text):
        return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}

    rows = [u("сделай отчёт"), a("делаю"),
            q("enqueue", letter), q("enqueue", note), q("dequeue"), u("Another Claude session …", isMeta=True),
            a("принял письмо"),                                                  # письмо — не пузырь человека
            q("dequeue"), u(note), a("агент закончил"),                          # уведомление взято ходом
            q("enqueue", "и ещё таблицу"), q("dequeue"), u("и ещё таблицу"), a("таблица"),   # очередь → обычный ход
            q("enqueue", "добавь итог"), q("remove", "добавь итог"), att("добавь итог"), a("итог добавлен"),
            q("enqueue", note), q("remove", note), att(note, "task-notification"), a("второй агент тоже"),
            q("enqueue", "/loop 10m проверь"), q("dequeue"), u("<command-message>loop</command-message>"),
            u("служебный текст навыка", isMeta=True), a("проверил"),
            u("<artifact-content-authored-by-others/>\nсводка", isCompactSummary=True),
            u("This session is being continued from a previous conversation…", isCompactSummary=True),
            q("enqueue", "последний вопрос")]
    (d / "s.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
    items, _ = t.history("/home/u/j")
    assert [(x["role"], x["text"], x.get("queued")) for x in items] == [
        ("user", "сделай отчёт", None), ("assistant", "делаю", None),
        ("assistant", "принял письмо", None),                                    # после вставки — свой пузырь
        ("assistant", "агент закончил", None),
        ("user", "и ещё таблицу", None), ("assistant", "таблица", None),
        ("user", "добавь итог", "read"), ("assistant", "итог добавлен", None),
        ("assistant", "второй агент тоже", None),
        ("assistant", "проверил", None),
        ("user", "последний вопрос", "wait")]                                    # ещё правда в очереди
    assert not any("<" in x["text"] for x in items)


def test_service_texts_are_not_prompts():
    for text in ("<task-notification>x</task-notification>", "<agent-message>x</agent-message>",
                 "<system-reminder>x</system-reminder>", "<command-name>/clear</command-name>",
                 "<local-command-stdout>ok</local-command-stdout>", "<bash-input>ls</bash-input>",
                 "<artifact-content-authored-by-others/>\nx", "  <some-new-tag>x</some-new-tag>"):
        assert t.is_service(text) and not t.is_real_prompt({"message": {"content": text}}), text
    for text in ("привет", "<pasted_content id=\"1\">x</pasted_content>", "<b>жирный</b> текст", "a <x-y> b"):
        assert not t.is_service(text) and t.is_real_prompt({"message": {"content": text}}), text
    assert not t.is_real_prompt({"message": {"content": "сводка"}, "isCompactSummary": True})


def test_revision_changes_when_transcript_grows(tmp_path, monkeypatch):
    monkeypatch.setattr(t, "CLAUDE_PROJECTS", tmp_path)
    d = t.project_dir("/home/u/r")
    d.mkdir(parents=True)
    assert t.revision("/home/u/r") == ""
    f = d / "s.jsonl"
    f.write_text('{"type":"user","message":{"content":"а"}}\n')
    r1 = t.revision("/home/u/r")
    with open(f, "a") as fh:
        fh.write('{"type":"user","message":{"content":"б"}}\n')
    assert t.revision("/home/u/r") != r1


def test_preview_shows_last_answer_action_or_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(t, "CLAUDE_PROJECTS", tmp_path)
    d = t.project_dir("/home/u/v")
    d.mkdir(parents=True)
    f = d / "s.jsonl"
    assert t.preview("/home/u/v") == ""
    rows = [user("почини тесты"),
            assistant("## ✅ Готово: **тесты** зелёные\n\nподробности", "end_turn")]
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert t.preview("/home/u/v") == "Готово: тесты зелёные"
    use = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "npm test", "description": "Запуск тестов"}}]}}
    with open(f, "a") as fh:
        fh.write(json.dumps(user("а теперь сборку")) + "\n")
    assert t.preview("/home/u/v") == "Вы: а теперь сборку"
    with open(f, "a") as fh:
        fh.write(json.dumps(use) + "\n")
    assert t.preview("/home/u/v") == "Команда: Запуск тестов"


def test_preview_keeps_urls_and_skips_interrupts(tmp_path, monkeypatch):
    monkeypatch.setattr(t, "CLAUDE_PROJECTS", tmp_path)
    d = t.project_dir("/home/u/w")
    d.mkdir(parents=True)
    rows = [assistant("- Отчёт: https://github.com/o/r/issues/1#issuecomment-5 и [PR](https://x/y)", "end_turn"),
            user("[Request interrupted by user]")]
    (d / "s.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert t.preview("/home/u/w") == "Отчёт: https://github.com/o/r/issues/1#issuecomment-5 и PR"


def line(n):
    return json.dumps({"n": n}) + "\n"


def test_old_journal_is_not_replayed_even_if_touched(tmp_path):
    """31.10: у старых журналов на 11–18 МБ сменилось время изменения — бот переслал всю переписку (429)."""
    f = tmp_path / "old.jsonl"
    f.write_text("".join(line(i) for i in range(10000)))    # больше «свежего» порога
    tail = t.Tail(started=0)                                 # монитор запущен «давно»: файл новее запуска
    f.chmod(0o600)
    tail.watch("p", [f])
    assert list(tail.read(f)) == []
    with open(f, "a") as fh:
        fh.write(line("новое"))
    assert list(tail.read(f)) == [{"n": "новое"}]


def test_new_session_in_watched_folder_is_read_from_start(tmp_path):
    tail = t.Tail(started=0)
    tail.watch("p", [])
    f = tmp_path / "new.jsonl"
    f.write_text(line(1) + line(2))
    tail.watch("p", [f])
    assert list(tail.read(f)) == [{"n": 1}, {"n": 2}]


def test_small_fresh_journal_on_first_look_is_read_from_start(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text(line(1))
    tail = t.Tail(started=0)
    tail.watch("p", [f])                                     # окно открыли вместе с сессией — первый ответ не теряем
    assert list(tail.read(f)) == [{"n": 1}]


def test_replaced_or_truncated_journal_is_not_replayed(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text(line(1))
    tail = t.Tail(started=9e9)
    tail.watch("p", [f])
    new = tmp_path / "s.tmp"
    new.write_text("".join(line(i) for i in range(50)))
    new.replace(f)                                           # подменили целиком
    assert list(tail.read(f)) == []
    f.write_text("")                                         # укоротили
    assert list(tail.read(f)) == []
    with open(f, "a") as fh:
        fh.write(line("дальше"))
    assert list(tail.read(f)) == [{"n": "дальше"}]


def test_last_model_from_journal(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(t, "CLAUDE_PROJECTS", tmp_path)
    d = t.project_dir("/srv/x")
    d.mkdir(parents=True)
    rows = [{"type": "assistant", "message": {"model": "claude-sonnet-4-5-20250929", "content": "a"}},
            {"type": "assistant", "isSidechain": True, "message": {"model": "claude-haiku-4-5", "content": "b"}},
            {"type": "assistant", "message": {"model": "claude-opus-5-5", "content": "c"}},
            {"type": "assistant", "message": {"model": "<synthetic>", "content": "d"}},
            {"type": "user", "message": {"content": "e"}}]
    (d / "s.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert t.last_model("/srv/x") == "claude-opus-5-5"             # субагент и служебные ответы — мимо
    assert t.model_title("claude-opus-5-5") == "Opus 5.5"
    assert t.model_title("claude-sonnet-4-5-20250929") == "Sonnet 4.5"
    assert t.model_title("claude-haiku-5-5") == "Haiku 5.5"
    assert t.model_title("glm-5.3") == "glm-5.3"
    assert t.last_model("/srv/none") == ""
