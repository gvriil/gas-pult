"""Журнал читается кусками (штаб 23.11: разбор журнала в 170 МБ целиком занимал ~360 МБ — панель упала по OOM):
результат тот же, что при чтении целиком, на любой границе куска; недописанная строка ждёт конца записи."""

import json

from gas_pult import transcripts as t


def _rec(i, role):
    if role == "user":
        return {"type": "user", "message": {"role": "user", "content": f"вопрос {i} " + "я" * (i * 7)},
                "timestamp": f"2026-11-23T10:{i:02d}:00Z"}
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": f"ответ {i}"}]},
            "timestamp": f"2026-11-23T10:{i:02d}:30Z"}


def _items(path, block):
    fd = t._Feed()
    fd.BLOCK = block
    fd.update(path)
    return fd


def test_chunks_equal_whole(tmp_path):
    f = tmp_path / "s.jsonl"
    recs = [_rec(i, r) for i in range(20) for r in ("user", "assistant")]
    f.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in recs))
    whole = _items(f, 1 << 30)
    assert len(whole.items) == 40
    for block in (1, 7, 64, 333):
        fd = _items(f, block)
        assert fd.items == whole.items and fd.offset == whole.offset == f.stat().st_size and fd.tail == whole.tail


def test_partial_last_line_waits(tmp_path):
    f = tmp_path / "s.jsonl"
    line = json.dumps(_rec(1, "user"), ensure_ascii=False)
    f.write_text(json.dumps(_rec(0, "user"), ensure_ascii=False) + "\n" + line[:20])
    fd = _items(f, 5)
    assert len(fd.items) == 1 and fd.offset < f.stat().st_size
    with open(f, "a") as fh:
        fh.write(line[20:])                              # запись дописана, перевода строки ещё нет — целый JSON
    fd.update(f)
    assert len(fd.items) == 2 and fd.offset == f.stat().st_size
    with open(f, "a") as fh:
        fh.write("\n" + json.dumps(_rec(2, "assistant"), ensure_ascii=False) + "\n")
    fd.update(f)
    assert [x["role"] for x in fd.items] == ["user", "user", "assistant"]
