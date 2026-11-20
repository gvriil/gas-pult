"""Уведомления на телефон и компьютер (Web Push) — без сторонних библиотек.

Владелец 20.11: «чтобы все уведомления приходили на телефон; главное — понятно, управляемо, как включается и
отключается». Раньше «пуш» был только из открытой вкладки панели. Теперь сервер сам будит браузер:

- ключи VAPID (P-256) и подпись ES256 — системным ``openssl`` (ядро пульта — только стандартная библиотека);
  ключ — ``<data>/push/vapid.pem`` (0600);
- пуш без содержимого (RFC 8030 + RFC 8292): служебный файл ``/sw.js`` по сигналу забирает текст с сервера
  (``/api/push/last``, по куке входа) и показывает уведомление — шифровать содержимое не нужно;
- подписки — у каждого свои (``uid``), ``<data>/push/subs.json`` (0600); адрес подписки — только у известных
  служб пуша (Google, Mozilla, Apple, Microsoft): сервер не ходит по чужим адресам;
- служба ответила 404/410 — подписка устарела, удаляем.
iPhone: пуш получает только панель, добавленная на экран «Домой» (iOS 16.4+).
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PUSH_HOSTS = ("fcm.googleapis.com", "updates.push.services.mozilla.com", "push.services.mozilla.com",
              ".push.apple.com", ".notify.windows.com")
INBOX_MAX = 30
INBOX_AGE = 3600                       # сообщение для показа живёт час: дальше служебный файл его не покажет


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Служба пуша ответила 3xx — не идём дальше: иначе сервер ушёл бы по чужому адресу (обход allowed_endpoint)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(_NoRedirect)


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def der_to_raw(sig: bytes) -> bytes:
    """Подпись ECDSA из DER (SEQUENCE{INTEGER r, INTEGER s}) — в 64 байта r‖s, как требует JWS ES256."""
    if len(sig) < 8 or sig[0] != 0x30:
        raise ValueError("подпись не DER")
    i = 2 if sig[1] < 0x80 else 2 + (sig[1] & 0x7F)
    out = b""
    for _ in range(2):
        if sig[i] != 0x02:
            raise ValueError("подпись не DER")
        n = sig[i + 1]
        v = sig[i + 2:i + 2 + n].lstrip(b"\0")
        out += v.rjust(32, b"\0")
        i += 2 + n
    return out


def allowed_endpoint(url: str) -> bool:
    u = urllib.parse.urlparse(url or "")
    h = (u.hostname or "").lower()
    return u.scheme == "https" and any(h == x.lstrip(".") or (x.startswith(".") and h.endswith(x)) for x in PUSH_HOSTS)


def ep_id(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()[:16]


class Hub:
    """Подписки, ключи и короткий «ящик» сообщений каждого человека."""

    def __init__(self, folder: Path, openssl: str = "openssl"):
        self.dir, self.openssl = Path(folder), openssl
        self.lock = threading.Lock()

    # ---------- ключи ----------
    @property
    def key_file(self) -> Path:
        return self.dir / "vapid.pem"

    def ensure_key(self) -> Path:
        with self.lock:
            if not self.key_file.exists():
                self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                tmp = self.key_file.with_suffix(".tmp")
                subprocess.run([self.openssl, "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(tmp)],
                               check=True, capture_output=True, timeout=20)
                os.chmod(tmp, 0o600)
                tmp.replace(self.key_file)
        return self.key_file

    def public_key(self) -> str:
        """Открытый ключ (65 байт, несжатая точка) в base64url — браузер подписывается им (applicationServerKey)."""
        der = subprocess.run([self.openssl, "ec", "-in", str(self.ensure_key()), "-pubout", "-outform", "DER"],
                             check=True, capture_output=True, timeout=20).stdout
        return b64u(der[-65:])

    def jwt(self, aud: str, sub: str, now: float | None = None) -> str:
        head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
        body = b64u(json.dumps({"aud": aud, "exp": int((now or time.time()) + 12 * 3600), "sub": sub},
                               separators=(",", ":")).encode())
        data = f"{head}.{body}".encode()
        sig = subprocess.run([self.openssl, "dgst", "-sha256", "-sign", str(self.ensure_key())], input=data,
                             check=True, capture_output=True, timeout=20).stdout
        return f"{head}.{body}.{b64u(der_to_raw(sig))}"

    # ---------- хранилище ----------
    def _load(self, name: str) -> dict:
        try:
            return json.loads((self.dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, name: str, d: dict):
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        f = self.dir / name
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(f)

    def add(self, uid, sub: dict, label: str = "", origin: str = "") -> dict:
        ep = str((sub or {}).get("endpoint") or "")
        if not allowed_endpoint(ep):
            raise ValueError("адрес подписки не похож на службу уведомлений браузера")
        with self.lock:
            d = self._load("subs.json")
            mine = [x for x in d.get(str(uid), []) if x["endpoint"] != ep]
            rec = {"endpoint": ep, "label": (label or "Устройство")[:60], "origin": origin[:200],
                   "created": int(time.time()), "ok": None}
            d[str(uid)] = [*mine, rec][-10:]                 # не больше 10 устройств у человека
            self._save("subs.json", d)
        return {"id": ep_id(ep), "label": rec["label"]}

    def remove(self, uid, dev: str) -> bool:
        with self.lock:
            d = self._load("subs.json")
            was = d.get(str(uid), [])
            left = [x for x in was if ep_id(x["endpoint"]) != dev and x["endpoint"] != dev]
            d[str(uid)] = left
            self._save("subs.json", d)
        return len(left) != len(was)

    def devices(self, uid) -> list[dict]:
        return [{"id": ep_id(x["endpoint"]), "label": x.get("label") or "Устройство", "created": x.get("created"),
                 "ok": x.get("ok")} for x in self._load("subs.json").get(str(uid), [])]

    # ---------- отправка ----------
    def notify(self, uid, title: str, body: str = "", w: str = "", wait: bool = False) -> int:
        """Положить сообщение в ящик человека и разбудить все его устройства. Возвращает число устройств."""
        item = {"id": b64u(os.urandom(9)), "t": int(time.time()), "title": title[:120], "body": body[:300], "w": w}
        with self.lock:
            box = self._load("inbox.json")
            box[str(uid)] = [*box.get(str(uid), []), item][-INBOX_MAX:]
            self._save("inbox.json", box)
        subs = self._load("subs.json").get(str(uid), [])
        if not subs:
            return 0
        t = threading.Thread(target=self._send_all, args=(uid, subs), daemon=True)
        t.start()
        if wait:
            t.join(30)
        return len(subs)

    def _send_all(self, uid, subs: list[dict]):
        for s in subs:
            code = self.send(s)
            with self.lock:
                d = self._load("subs.json")
                cur = d.get(str(uid), [])
                if code in (404, 410):                    # подписка устарела — убрать
                    d[str(uid)] = [x for x in cur if x["endpoint"] != s["endpoint"]]
                else:
                    for x in cur:
                        if x["endpoint"] == s["endpoint"]:
                            x["ok"] = code is not None and 200 <= code < 300
                self._save("subs.json", d)

    def send(self, s: dict) -> int | None:
        """Пуш без содержимого. Код ответа службы или None (нет связи)."""
        ep = s["endpoint"]
        if not allowed_endpoint(ep):
            return None
        u = urllib.parse.urlparse(ep)
        try:
            tok = self.jwt(f"{u.scheme}://{u.netloc}", s.get("origin") or "mailto:push@localhost")
            req = urllib.request.Request(ep, data=b"", method="POST", headers={
                "TTL": "3600", "Urgency": "high", "Content-Length": "0",
                "Authorization": f"vapid t={tok}, k={self.public_key()}"})
            with OPENER.open(req, timeout=15) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
        except (OSError, subprocess.SubprocessError, ValueError):
            return None

    def pending(self, uid, dev: str = "") -> list[dict]:
        """Что показать устройству: свежие сообщения, которых это устройство ещё не забирало."""
        now = time.time()
        with self.lock:
            box = self._load("inbox.json").get(str(uid), [])
            seen = self._load("seen.json")
            k = f"{uid}:{dev}"
            last = seen.get(k, 0)
            old = set(seen.get(k + ":ids", []))
            out = [x for x in box if x["t"] >= last and now - x["t"] < INBOX_AGE and x["id"] not in old]
            if out:
                seen[k] = max(x["t"] for x in out)
                seen[k + ":ids"] = [x["id"] for x in box if x["t"] >= seen[k]]
                with contextlib.suppress(OSError):
                    self._save("seen.json", seen)
        return out[-3:]
