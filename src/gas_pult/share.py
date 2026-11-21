"""«Поделиться» в Гаврилу (владелец 21.11: «фото, ссылкой, файлом — Гаврила должен быть в списке «Поделиться»»).

- Android (Chrome, установленное приложение): ``share_target`` в манифесте (``brand.manifest``) → POST ``/share``
  (multipart/form-data, кука входа). Файлы — потоком во ``inbox`` пульта (``Panel.upload``), без чтения в память.
- iPhone: Safari не умеет Web Share Target — «Быстрая команда» шлёт POST ``/api/share`` с заголовком
  ``Authorization: Bearer <токен устройства>``. Токен выпускает сам человек в «Настройки → Аккаунт и вход →
  Устройства для «Поделиться»»: показывается один раз, в файле — только хэш (как у моста к браузеру, bridge.py).
- Запись «поделились» — у человека своя: видит и разбирает только он (``uid`` — Telegram ID, как ``terms_uid``).
  Ничего не уходит в чат само: панель показывает шторку «Куда отправить», человек выбирает.

Файлы: ``shares.json`` и ``share_tokens.json`` в папке данных (0600).
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from pathlib import Path

MAX_TOTAL = 50 << 20                  # всё тело запроса — как у /api/upload (MAX_BODY)
MAX_FILES = 10
MAX_FIELD = 64 << 10                  # текст и ссылка — до 64 КБ
MAX_HEAD = 8 << 10                    # заголовки части multipart
CHUNK = 64 << 10
KEEP_DONE = 30 * 86400                # разобранные записи — 30 дней (файлы остаются во «Входящих»)
KEEP_MAX = 200                        # записей на человека
TOKENS_MAX = 10                       # устройств на человека
_ID = re.compile(r"^[A-Za-z0-9_-]{6,40}$")


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _clip(v, n: int) -> str:
    return str(v or "").replace("\r\n", "\n").strip()[:n]


class _Locked:
    """JSON-файл 0600 под замком: список записей."""

    def __init__(self, path: Path):
        self.path, self.lock = Path(path), threading.Lock()

    def _load(self) -> list[dict]:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return [x for x in d if isinstance(x, dict) and x.get("id")] if isinstance(d, list) else []
        except (OSError, ValueError):
            return []

    def _save(self, items: list[dict]):
        from gas_pult.config import write_private
        write_private(self.path, json.dumps(items, ensure_ascii=False))


class Store(_Locked):
    """Записи «поделились»: id, uid, когда, title/text/url, файлы [{name, path, size, type}], via, done."""

    def __init__(self, path: Path, clock=time.time):
        super().__init__(path)
        self.clock = clock

    def add(self, uid: int, title: str = "", text: str = "", url: str = "", files: list | None = None,
            via: str = "") -> dict:
        rec = {"id": secrets.token_urlsafe(9), "uid": int(uid), "at": self.clock(), "title": _clip(title, 300),
               "text": _clip(text, MAX_FIELD), "url": _clip(url, 2000), "files": list(files or []),
               "via": via[:20], "done": False}
        if not (rec["title"] or rec["text"] or rec["url"] or rec["files"]):
            raise ValueError("пустая запись: нет ни текста, ни ссылки, ни файла")
        with self.lock:
            now, items = self.clock(), self._load()
            items = [x for x in items if not (x.get("done") and now - float(x.get("at", 0)) > KEEP_DONE)]
            mine = [x for x in items if x.get("uid") == rec["uid"]]
            if len(mine) >= KEEP_MAX:                 # самые старые записи человека — из списка (файлы остаются)
                drop = {x["id"] for x in mine[: len(mine) - KEEP_MAX + 1]}
                items = [x for x in items if x["id"] not in drop]
            items.append(rec)
            self._save(items)
        return rec

    def mine(self, uid, open_only: bool = True) -> list[dict]:
        with self.lock:
            out = [x for x in self._load() if x.get("uid") == uid and not (open_only and x.get("done"))]
        return sorted(out, key=lambda x: -float(x.get("at", 0)))

    def pending(self, uid) -> int:
        return len(self.mine(uid)) if uid is not None else 0

    def get(self, uid, sid: str) -> dict:
        """Своя запись; чужая и несуществующая — одинаково «не найдена» (не подсказываем, что id есть)."""
        rec = next((x for x in self._load() if x.get("id") == sid), None) if _ID.match(str(sid or "")) else None
        if not rec or rec.get("uid") != uid:
            raise LookupError("запись не найдена")
        return rec

    def done(self, uid, sid: str) -> dict:
        with self.lock:
            items = self._load()
            rec = next((x for x in items if x.get("id") == sid and x.get("uid") == uid), None)
            if not rec:
                raise LookupError("запись не найдена")
            rec["done"] = True
            self._save(items)
        return {"ok": True}


class Tokens(_Locked):
    """Токены устройств для «Поделиться» (iPhone, «Быстрая команда»): id, uid, имя, хэш, когда создан и был."""

    def __init__(self, path: Path, clock=time.time):
        super().__init__(path)
        self.clock = clock

    def create(self, uid: int, name: str = "") -> dict:
        tok = "gps_" + secrets.token_urlsafe(32)
        rec = {"id": secrets.token_hex(6), "uid": int(uid), "name": _clip(name, 60) or "iPhone",
               "hash": _h(tok), "created": self.clock(), "seen": None}
        with self.lock:
            items = self._load()
            if sum(1 for x in items if x.get("uid") == rec["uid"]) >= TOKENS_MAX:
                raise ValueError(f"не больше {TOKENS_MAX} устройств — отзовите ненужное")
            items.append(rec)
            self._save(items)
        return {"id": rec["id"], "name": rec["name"], "token": tok}      # токен — один раз, дальше только хэш

    def mine(self, uid) -> list[dict]:
        return [{k: x.get(k) for k in ("id", "name", "created", "seen")} for x in self._load() if x.get("uid") == uid]

    def revoke(self, uid, tid: str) -> dict:
        with self.lock:
            items = self._load()
            left = [x for x in items if not (x.get("id") == tid and x.get("uid") == uid)]
            if len(left) == len(items):
                raise LookupError("устройство не найдено")
            self._save(left)
        return {"ok": True}

    def check(self, token: str) -> dict | None:
        """Запись токена или None. Сравнение хэшей — за постоянное время."""
        if not token or not token.startswith("gps_") or len(token) > 100:
            return None
        h = _h(token)
        with self.lock:
            items = self._load()
            rec = next((x for x in items if secrets.compare_digest(str(x.get("hash", "")), h)), None)
            if rec and (rec.get("seen") or 0) < self.clock() - 300:     # «был» — не чаще раза в 5 минут
                rec["seen"] = self.clock()
                self._save(items)
        return rec


def bearer(header: str) -> str:
    kind, _, tok = (header or "").strip().partition(" ")
    return tok.strip() if kind.lower() == "bearer" else ""


# ---------- multipart/form-data потоком (cgi убран в Python 3.13) ----------
class _Src:
    """Тело запроса ровно ``n`` байт: дальше не читаем (keep-alive)."""

    def __init__(self, f, n: int):
        self.f, self.left = f, n

    def read(self, k: int) -> bytes:
        k = min(k, self.left)
        if k <= 0:
            return b""
        b = self.f.read(k)
        if not b:
            raise ValueError("тело запроса пришло не целиком")
        self.left -= len(b)
        return b


class _Part:
    """Содержимое одной части до разделителя — для ``drive_inbox.save`` (читает, пока не вернём b"")."""

    def __init__(self, mp: Multipart):
        self.mp, self.end = mp, False

    def read(self, k: int = CHUNK) -> bytes:
        if self.end:
            return b""
        mp, d = self.mp, self.mp.delim
        k = max(1, k)
        mp.fill(k + len(d))
        i = mp.buf.find(d)
        if i == 0:
            self.end = True
            return b""
        if i > 0:
            n = min(k, i)
        else:
            if mp.eof:
                raise ValueError("тело запроса оборвалось посреди файла")
            n = min(k, len(mp.buf) - len(d) + 1)
        out = bytes(mp.buf[:n])
        del mp.buf[:n]
        return out

    def drain(self) -> int:
        n = 0
        while b := self.read(CHUNK):
            n += len(b)
        return n


class Multipart:
    """Разбор multipart/form-data из потока: поля — строками, файлы — потоками (``on_file``)."""

    def __init__(self, f, ctype: str, length: int):
        m = re.search(r'boundary="?([^";]{1,200})"?', ctype or "", re.I)
        if not ctype.lower().startswith("multipart/form-data") or not m:
            raise ValueError("ожидалась форма multipart/form-data")
        self.src, self.delim = _Src(f, length), b"\r\n--" + m.group(1).encode("latin-1")
        self.buf, self.eof = bytearray(b"\r\n"), False      # «\r\n» в начале — первый разделитель как остальные

    def fill(self, need: int):
        while len(self.buf) < need and not self.eof:
            b = self.src.read(CHUNK)
            if not b:
                self.eof = True
            else:
                self.buf += b

    def _headers(self) -> dict:
        while (i := self.buf.find(b"\r\n\r\n")) < 0:
            if len(self.buf) > MAX_HEAD or self.eof:
                raise ValueError("неверные заголовки части формы")
            self.fill(len(self.buf) + CHUNK)
        raw = bytes(self.buf[:i]).decode("utf-8", "replace")
        del self.buf[: i + 4]
        out = {}
        for line in raw.split("\r\n"):
            k, _, v = line.partition(":")
            out[k.strip().lower()] = v.strip()
        return out

    def parse(self, on_file) -> tuple[dict, list]:
        """→ (поля {имя: текст}, [итог ``on_file(поле, имя файла, тип, поток)``]). Пустые файлы — пропускаются."""
        fields, files, nfiles = {}, [], 0
        while True:
            self.fill(len(self.delim) + 2)
            i = self.buf.find(self.delim)
            if i < 0:
                if self.eof:
                    raise ValueError("в форме нет завершающего разделителя")
                del self.buf[: max(0, len(self.buf) - len(self.delim))]   # преамбула
                self.fill(len(self.buf) + CHUNK)
                continue
            del self.buf[: i + len(self.delim)]
            self.fill(2)
            if bytes(self.buf[:2]) == b"--":
                self.src.read(self.src.left)          # эпилог — дочитать (keep-alive), он в пределах длины
                return fields, files
            h = self._headers()
            cd = h.get("content-disposition", "")
            name = (re.search(r'(?:^|;)\s*name="([^"]*)"', cd) or [None, ""])[1]
            fn = re.search(r'filename="([^"]*)"', cd)
            body = _Part(self)
            if fn is None:
                data = bytearray()
                while b := body.read(CHUNK):
                    data += b
                    if len(data) > MAX_FIELD:
                        raise ValueError("поле формы больше 64 КБ")
                fields[name] = data.decode("utf-8", "replace")
                continue
            if not fn.group(1):                     # поле файла без файла (браузер шлёт пустую часть)
                body.drain()
                continue
            nfiles += 1
            if nfiles > MAX_FILES:
                raise ValueError(f"не больше {MAX_FILES} файлов за раз")
            got = on_file(name, fn.group(1), h.get("content-type", "application/octet-stream"), body)
            body.drain()
            if got:
                files.append(got)
