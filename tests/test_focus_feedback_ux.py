"""Отзывы тестировщика по фокус-чату 22.11: фразы-подсказки ставятся в поле, «Копировать» у кода и образца текста,
«Файл получен» в ленте и пометка агенту для файла любого типа без подписи. Сценарий в браузере —
tests/e2e/nextq_files_demo.py."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from gas_pult import transcripts, uploads

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "gas_pult" / "web"
PAGE = (WEB / "index.html").read_text(encoding="utf-8")
NQ = (WEB / "js" / "nextq.js").read_text(encoding="utf-8")


# ---------- 3. файл без подписи: пометка агенту для любого типа ----------
@pytest.mark.parametrize("name", ["отчёт.pdf", "договор.docx", "клиенты.xlsx", "запись.mp4", "архив.zip", "README"])
def test_bare_document_gets_file_note(name):
    t = uploads.mark_bare(f"Посмотри файл.\n\nФайл из панели: /in/{name}")
    assert t.startswith("Человек прислал файл без подписи. Посмотри его и свяжи с последним вопросом.")
    assert t.endswith(f"\n\nФайл из панели: /in/{name}")
    assert uploads.shown(t) == f"Посмотри файл.\n\nФайл из панели: /in/{name}"


def test_mixed_and_captioned_files():
    mixed = uploads.mark_bare("Файл из панели: /a.png\nФайл из Telegram: /b.pdf")
    assert mixed.startswith("Человек прислал файлы без подписи. Посмотри их")
    cap = "Сверь с прошлым месяцем\n\nФайл из панели: /in/клиенты.xlsx"
    assert uploads.mark_bare(cap) == cap                            # с подписью — подпись и строка о файле, как есть
    assert uploads.mark_bare("(файл загружается…)\n\nФайл из панели: /in/x.pdf").startswith("Человек прислал файл")


def test_feed_keeps_file_line_for_document():
    marked = uploads.mark_bare("Посмотри файл.\n\nФайл из панели: /in/отчёт.pdf")
    feed = transcripts._Feed()
    feed.line(json.dumps({"type": "user", "timestamp": "2026-11-23T10:00:00Z",
                          "message": {"role": "user", "content": marked}}).encode())
    assert feed.items[-1]["text"] == "Посмотри файл.\n\nФайл из панели: /in/отчёт.pdf"


def test_bot_takes_any_media_and_names_video():
    src = (ROOT / "src" / "gas_pult" / "bot.py").read_text(encoding="utf-8")
    assert 'm.get("video_note")' in src and 'or m.get("animation")' in src
    assert 'dflt = "photo.jpg" if m.get("photo") else "file" if m.get("document") else "video.mp4"' in src
    assert 'uploads.mark_bare(f"{t or uploads.DEFAULT}\\n\\nФайл из Telegram: {path}")' in src


def test_feed_shows_file_received_not_path():
    body = PAGE[PAGE.index("function fileTxt("):PAGE.index("function userMsg(")]
    assert '"Снимок получен" : "Файл получен"' in body and 'body === "Посмотри файл."' in body
    assert 'data-path="${esc(p)}"' in body and 'p.split("/").pop()' in body       # в ленте — имя, путь — в атрибуте
    assert "Файл загружается…" in body
    assert PAGE.count('<div class="bubble">${fileTxt(') == 5      # ваше, неотправленное, простой режим ×2, прошлый чат
    assert '<div class="bubble">${esc(m.text)}</div>' not in PAGE
    media = (WEB / "js" / "media.js").read_text(encoding="utf-8")
    assert 'querySelectorAll("[data-path]")' in media                 # миниатюры — и по пути из атрибута


# ---------- 2. «Копировать» у кода и образца текста ----------
def test_copy_on_code_and_quote_with_label():
    assert 'root.querySelectorAll(".md pre, .md > blockquote")' in PAGE
    assert '${ic("copy", "s16")}<span>${esc(copyLbl())}</span></button>`' in PAGE   # подпись видна, не только значок
    assert 'querySelector("pre, blockquote")' in PAGE
    assert ".md .codebox > pre { margin: 0; padding-top: 36px; }" in PAGE.replace(".codebox > pre, ", "")


# ---------- 1. фразы-подсказки: в поле, не отправка ----------
def test_next_phrases_insert_not_send():
    assert '<div class="nextq" data-key="nq:${lastAi}"></div>' in PAGE
    assert 'part("nextq").then((x) => x.paint(s, m?.text || ""))' in PAGE
    assert "nextQ(box, hist.at(-1));" in PAGE and "nextQ(box, SIM.hist.at(-1));" in PAGE
    click = NQ[NQ.index('document.addEventListener("click"'):NQ.index("// Вид")]
    assert "sendText" not in click and "/api/send" not in click and "inp.focus()" in click
    assert "setSelectionRange(inp.value.length, inp.value.length)" in click
    assert "Можно спросить:" in NQ and "Нажмите фразу — она встанет в поле, отправьте." in NQ
    assert 'ic("edit", "s16")' in NQ


def test_phrases_parser_in_node(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("нет node")
    js = tmp_path / "t.mjs"
    head = "globalThis.document = { addEventListener() {}, getElementById() { return 1; } };\n" \
        + "const m = await import(" + json.dumps((WEB / "js" / "nextq.js").as_uri()) + ");\n"
    js.write_text(head + """
const r = [m.phrases('Можно спросить:\\n- «Сколько дублей нашлось?»\\n- Покажи список?\\n- просто пункт'),
  m.phrases('Итог: «не фраза»\\n- «вопрос?»'), m.phrases('```\\nСпросите:\\n- «код?»\\n```'),
  m.phrases('Например, напишите «Первая» или «Вторая»'),
  m.phrases('Можно спросить:\\n- «1?»\\n- «2?»\\n- «3?»\\n- «4?»\\n- «5?»')];
console.log(JSON.stringify(r));""", encoding="utf-8")
    out = subprocess.run([node, str(js)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout)
    assert r[0] == ["Сколько дублей нашлось?", "Покажи список?"]
    assert r[1] == ["вопрос?"] and r[2] == [] and r[3] == ["Первая", "Вторая"]
    assert r[4] == []                                     # короче 3 знаков — не фразы


def test_core_size_and_demo():
    assert len((WEB / "index.html").read_bytes()) < 770000
    demo = (WEB / "js" / "demo.js").read_text(encoding="utf-8")
    assert 'params.get("nq")' in demo and "/home/u/drive/demo/" in demo


def test_e2e_nextq_files_demo():
    import importlib.util
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    spec = importlib.util.spec_from_file_location("nq_demo", ROOT / "tests" / "e2e" / "nextq_files_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo&dev")
    finally:
        srv.shutdown()
