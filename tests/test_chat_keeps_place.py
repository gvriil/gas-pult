"""P0 09.11: переписка не пропадает, когда Claude заканчивает ход, и открывается на последнем сообщении; время —
в поясе зрителя. Сценарий — в браузере (tests/e2e/chat_keeps_place.py); без Playwright или Chrome — пропуск."""

import importlib.util
import shutil
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import webapp


def test_e2e_chat_keeps_place():
    pytest.importorskip("playwright.async_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    web = Path(webapp.__file__).resolve().parent / "web"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(web)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    e2e = Path(__file__).parent / "e2e" / "chat_keeps_place.py"
    spec = importlib.util.spec_from_file_location("chat_keeps_place", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()


def test_journal_id_in_revision_is_first_part():
    """Фронт отличает другой разговор по первой части rev (journalOf): формат transcripts.revision это и даёт."""
    from gas_pult import transcripts
    src = (Path(webapp.__file__).parent / "web" / "index.html").read_text()
    assert 'const journalOf = (rev) => String(rev || "").split("-")[0];' in src
    assert 'f"{f.stem[:8]}-{st.st_size}-{st.st_mtime_ns}"' in Path(transcripts.__file__).read_text()
