"""«Документы» (GAS-16, слой 2: RAG ступень А): FTS5 по папке — цитата, файл и место; новые и удалённые файлы
индексируются сами; форматы txt, docx, xlsx; MCP по stdio."""

import io
import json
import zipfile

import pytest

from gas_pult import mcp
from gas_pult.connectors import docs_mcp


@pytest.fixture
def docs(tmp_path, monkeypatch):
    d = tmp_path / "Документы"
    d.mkdir()
    monkeypatch.setenv("GAS_DOCS_DIRS", str(d))
    monkeypatch.setenv("GAS_DOCS_INDEX", str(tmp_path / "idx.sqlite"))
    return d


def docx(path, paras):
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paras)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="x"><w:body>{body}</w:body></w:document>')


def test_find_with_quote_file_and_place(docs, tmp_path):
    (docs / "договоры").mkdir()
    docx(docs / "договоры" / "поставка.docx",
         ["Договор поставки № 7", "Срок оплаты — 14 банковских дней с даты счёта."])
    (docs / "прайс.csv").write_text("товар;цена\nкофе;450\nчай;300\n", encoding="utf-8")
    (docs / ".скрытый.txt").write_text("срок оплаты секрет", encoding="utf-8")
    r = docs_mcp.search("какой срок оплаты по договору")
    assert r["hits"] and r["hits"][0]["file"] == "договоры/поставка.docx" and r["hits"][0]["place"].startswith("абзацы")
    assert "«" in r["hits"][0]["quote"] and "оплат" in r["hits"][0]["quote"].lower()
    assert all(".скрытый" not in h["file"] for h in r["hits"])
    assert docs_mcp.search("цена чая")["hits"][0]["file"] == "прайс.csv"
    assert (tmp_path / "idx.sqlite").stat().st_mode & 0o777 == 0o600


def test_new_changed_removed_files_reindexed(docs):
    f = docs / "заметка.md"
    f.write_text("встреча с поставщиком во вторник", encoding="utf-8")
    assert docs_mcp.search("поставщиком")["hits"]
    f.write_text("встреча перенесена на пятницу", encoding="utf-8")
    import os
    os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 5))
    assert not docs_mcp.search("вторник")["hits"] and docs_mcp.search("пятницу")["hits"]
    f.unlink()
    r = docs_mcp.search("пятницу")
    assert not r["hits"] and "не нашлось" in r["note"] and r["files_indexed"] == 0


def test_xlsx_and_stem(docs):
    with zipfile.ZipFile(docs / "склад.xlsx", "w") as z:
        z.writestr("xl/sharedStrings.xml", "<sst><si><t>Остатки молока</t></si></sst>")
        z.writestr("xl/worksheets/sheet1.xml",
                   '<worksheet><c r="A1" t="s"><v>0</v></c><c r="B1"><v>42</v></c></worksheet>')
    h = docs_mcp.search("остаток молоко")["hits"]
    assert h and h[0]["file"] == "склад.xlsx" and h[0]["place"].startswith("лист 1")


def test_mcp_stdio(docs):
    (docs / "a.txt").write_text("гарантия двенадцать месяцев", encoding="utf-8")
    inp = io.StringIO("\n".join(json.dumps(m) for m in (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "find_in_docs", "arguments": {"query": "гарантия"}}})) + "\n")
    out = io.StringIO()
    docs_mcp._core.serve(docs_mcp.SERVER, inp, out)
    res = [json.loads(x) for x in out.getvalue().splitlines()]
    assert {t["name"] for t in res[1]["result"]["tools"]} == {"find_in_docs", "docs_status"}
    assert "a.txt" in res[2]["result"]["content"][0]["text"] and not res[2]["result"]["isError"]


def test_preset_builtin_config(tmp_path, monkeypatch):
    p = next(x for x in mcp.PRESETS if x["id"] == "docs")
    monkeypatch.setattr(mcp, "secrets_dir", lambda home: tmp_path)
    cfg = mcp.builtin(p, "docs", {"folder": str(tmp_path / "Мои документы")}, None)
    assert cfg["args"] == [str(mcp.DOCS_SERVER)] and cfg["env"]["GAS_DOCS_DIRS"].endswith("Мои документы")
    assert (tmp_path / "Мои документы").is_dir() and cfg["env"]["GAS_DOCS_INDEX"].endswith("docs.docs.sqlite")
    with pytest.raises(ValueError):
        mcp.builtin(p, "docs", {"folder": "../etc"}, None)
