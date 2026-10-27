from gas_pult.voice.text import chunks


def test_short_text_is_one_chunk():
    assert chunks("Раз. Два! Три?") == ["Раз. Два! Три?"]


def test_chunks_respect_limit():
    text = " ".join(["Это предложение для проверки нарезки."] * 60)
    parts = chunks(text, limit=200)
    assert all(len(p) <= 200 for p in parts)
    assert " ".join(parts).split() == text.split()


def test_long_word_without_spaces_is_cut():
    parts = chunks("а" * 450, limit=200)
    assert [len(p) for p in parts] == [200, 200, 50]


def test_empty():
    assert chunks("  \n\n ") == []
