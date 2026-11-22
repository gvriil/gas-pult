"""Заглушка службы панели для тестов коннекторов: «Да» человека (approvals.py) без настоящей панели.

Коннектор перед выполнением спрашивает панель ``POST /api/drafts/check`` (``_core._panel_ok``). Здесь — маленький
HTTP-сервер: отвечает «да» один раз на черновик, на который тест дал «Да» (``grant``), и только с верным секретом
(как ``bridge-local.token`` владельца). Отметки на диске и команды ``confirm`` — не действуют (это и проверяем).
"""

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_grants: set[tuple[str, str]] = set()
_token = secrets.token_hex(16)
_url = ""
_lock = threading.Lock()


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path != "/api/drafts/check" or self.headers.get("X-GP-Local") != _token:
            self.send_response(403)
            self.end_headers()
            return
        key = (str(b.get("svc")), str(b.get("id")))
        with _lock:
            ok = key in _grants
            _grants.discard(key)
        raw = json.dumps({"ok": ok}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _start() -> str:
    global _url
    with _lock:
        if not _url:
            srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            _url = f"http://127.0.0.1:{srv.server_address[1]}"
    return _url


def env(tmp_path) -> dict:
    """Окружение коннектора: папка черновиков, адрес заглушки и секрет владельца (файл 0600)."""
    tok = tmp_path / "bridge-local.token"
    tok.write_text(_token)
    tok.chmod(0o600)
    return {"GAS_CONFIRM_DIR": str(tmp_path / "confirm"), "GAS_PULT_PANEL_URL": _start(),
            "GAS_PULT_LOCAL_TOKEN_FILE": str(tok)}


def grant(svc: str, pid: str) -> None:
    """Человек нажал «Да» в панели на этот черновик (одноразово)."""
    with _lock:
        _grants.add((svc, str(pid)))
