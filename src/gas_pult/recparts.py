"""Запись по кускам (владелец 22.11: «запись обрывается, когда телефон блокируют, — теряется»).

Панель шлёт куски MediaRecorder каждые ~10 с: ``POST /api/rec/chunk?id=<сеанс>&seg=<отрезок>&seq=<номер>``. Сервер
складывает их в ``<данные>/rec-parts/<сеанс>/`` (0700, файлы 0600) и собирает одну запись по порядку. Повтор того же
куска (связь моргнула — панель отправила ещё раз) не дублирует. Отрезок — один MediaRecorder: после обрыва
(блокировка, звонок) панель начинает новый отрезок в том же сеансе; у каждого отрезка свой заголовок файла, поэтому
распознаются они по отдельности, а текст склеивается (``webapp.Panel.rec_finish``).

Сеанс принадлежит тому, кто его начал (``uid`` и пространство): чужой сеанс — ``LookupError`` (как «нет такого»).
Общий размер сеанса — не больше ``MAX`` (тот же лимит, что у тела запроса). Брошенные сеансы — прочь через ``KEEP``.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import shutil
import threading
import time
from pathlib import Path

from gas_pult.config import write_private

RID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
MAX = 50 << 20                       # как MAX_BODY панели: голосовое — до 50 МБ
SEGS, SEQS = 50, 2000                # отрезков на сеанс (обрывов) и кусков на отрезок (~5,5 ч по 10 с)
KEEP = 2 * 86400                     # брошенный сеанс (не нажали «Стоп» и не вернулись) — двое суток


class Parts:
    def __init__(self, root: Path, clock=time.time):
        self.root, self.clock, self.lock = Path(root), clock, threading.Lock()

    def _dir(self, rid: str) -> Path:
        if not RID.match(str(rid or "")):
            raise ValueError("неверный сеанс записи")
        return self.root / rid

    @staticmethod
    def _meta(d: Path) -> dict:
        try:
            m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            return m if isinstance(m, dict) else {}
        except (OSError, ValueError):
            return {}

    def _own(self, d: Path, owner: str) -> dict:
        m = self._meta(d)
        if not m or m.get("owner") != owner:
            raise LookupError("записи нет")                 # чужой сеанс не отличаем от несуществующего
        return m

    def clean(self):
        old = self.clock() - KEEP
        with contextlib.suppress(OSError):
            for d in self.root.iterdir():
                if d.is_dir() and self._meta(d).get("at", 0) < old:
                    shutil.rmtree(d, ignore_errors=True)

    def add(self, owner: str, rid: str, seg: int, seq: int, data: bytes, ctype: str = "") -> dict:
        """Кусок ``seq`` отрезка ``seg``: (новый или повтор) → {seg, seq, have, bytes, dup}."""
        d = self._dir(rid)
        if not (0 <= seg < SEGS and 0 <= seq < SEQS):
            raise ValueError("неверный номер куска")
        if not data:
            raise ValueError("пустой кусок")
        with self.lock:
            if d.exists():
                m = self._own(d, owner)
            else:
                self.clean()
                d.mkdir(parents=True, mode=0o700)
                m = {"owner": owner, "at": self.clock(), "ctype": ctype.split(";")[0][:60], "parts": {}, "bytes": 0}
            key = f"{seg}.{seq}"
            h = hashlib.sha256(data).hexdigest()
            dup = key in m["parts"]
            if not dup:
                if m["bytes"] + len(data) > MAX:
                    raise ValueError("запись больше 50 МБ — остановите её и начните новую")
                f = d / f"{seg:03d}-{seq:05d}.part"
                f.write_bytes(data)
                f.chmod(0o600)
                m["parts"][key] = {"n": len(data), "h": h}
                m["bytes"] += len(data)
            m["at"] = self.clock()
            write_private(d / "meta.json", json.dumps(m))
            return {"seg": seg, "seq": seq, "have": len(m["parts"]), "bytes": m["bytes"], "dup": dup}

    def status(self, owner: str, rid: str) -> dict:
        m = self._own(self._dir(rid), owner)
        segs = sorted({int(k.split(".")[0]) for k in m["parts"]})
        return {"have": len(m["parts"]), "bytes": m["bytes"], "segs": segs, "ctype": m.get("ctype", ""),
                "missing": self.missing(m)}

    @staticmethod
    def missing(m: dict) -> list[str]:
        """Пропуски внутри отрезков («сег.номер»): куски, которые панель ещё не дослала."""
        by: dict[int, set[int]] = {}
        for k in m.get("parts", {}):
            s, q = (int(x) for x in k.split("."))
            by.setdefault(s, set()).add(q)
        return [f"{s}.{q}" for s, qs in sorted(by.items()) for q in range(max(qs) + 1) if q not in qs]

    def assemble(self, owner: str, rid: str) -> tuple[list[bytes], str]:
        """Запись по отрезкам: [байты отрезка 0, отрезка 1, …] и тип. Пропуск куска — ``ValueError`` со списком."""
        d = self._dir(rid)
        with self.lock:
            m = self._own(d, owner)
            if gaps := self.missing(m):
                raise ValueError("не хватает кусков записи: " + ", ".join(gaps[:10]))
            segs: dict[int, list[tuple[int, Path]]] = {}
            for k in m["parts"]:
                s, q = (int(x) for x in k.split("."))
                segs.setdefault(s, []).append((q, d / f"{s:03d}-{q:05d}.part"))
            out = [b"".join(p.read_bytes() for _, p in sorted(xs)) for _, xs in sorted(segs.items())]
        if not out:
            raise ValueError("запись пустая")
        return out, m.get("ctype", "")

    def drop(self, owner: str, rid: str) -> bool:
        d = self._dir(rid)
        with self.lock:
            self._own(d, owner)
            shutil.rmtree(d, ignore_errors=True)
        return True
