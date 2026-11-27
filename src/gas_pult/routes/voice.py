"""Маршруты области «голос» (MONOLITH-PLAN §3.2, шаг 7): озвучка, распознавание, запись по кускам, выбор голоса.

Ветки перенесены из ``webapp.H.get``/``H.post`` как есть: ``self`` — обработчик запроса (``webapp.H``), ``panel`` —
его ``Panel``. Права (``access.py``: ``SPACE_OK``, ``FOCUS_*``, ``OWNER_ONLY`` для ``/api/voice/choose``) проверены
до вызова — ``H.permit`` или ``H.focus_call``. Таблицы и подписи — ``routes/__init__.py``.
"""

import urllib.parse

from gas_pult.uploads import KEEP_CAP, MAX_VOICE


def tts_about(self, q: dict):
    """GET /api/tts/about — «Что здесь умеет» — голосом (текст из карты помощника)"""
    panel = self.panel
    return ("audio/mpeg", panel.tts_text(panel.about_text(q.get("screen", "")),
                                         panel.cfg.personal_voices and self.who()[1] == "owner",
                                         cloud=not self.space()))


def rec_status(self, q: dict):
    """GET /api/rec/status — запись по кускам: что уже на сервере (после обрыва)"""
    panel = self.panel
    return panel.recparts.status(self.rec_owner(), str(q.get("id", "")))


def stt_job(self, q: dict):
    """GET /api/stt/job — фоновое распознавание: состояние и текст (GAS-34)"""
    panel = self.panel
    return panel.stt_job_get(q.get("id", ""), self.terms_uid())


def voice_cards(self, q: dict):
    """GET /api/voice/cards"""
    panel = self.panel
    return panel.voice_cards(self.who()[1] == "owner", cloud=not self.space())


def voice_preview(self, q: dict):
    """GET /api/voice/preview"""
    panel = self.panel
    return ("audio/mpeg", panel.voice_preview(q.get("id", ""), self.who()[1] == "owner"))


def tts(self, q: dict, w: dict):
    """GET_W /api/tts"""
    panel = self.panel
    msg = int(q["msg"]) if q.get("msg", "").isdigit() else None
    return ("audio/mpeg", panel.tts(w, q.get("full") == "1", msg,
                                     panel.cfg.personal_voices and self.who()[1] == "owner",
                                     cloud=not self.space(), head=q.get("head") == "1"))


def tts_warm(self, q: dict, w: dict):
    """GET_W /api/tts/warm — открыли сессию — голос загрузится заранее (#190)"""
    panel = self.panel
    return panel.tts_warm(panel.cfg.personal_voices and self.who()[1] == "owner")


def rec_chunk(self):
    """POST_RAW /api/rec/chunk — кусок записи (~10 с): не теряется при блокировке"""
    panel = self.panel
    rq = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
    try:
        seg, seq = int(rq.get("seg", 0)), int(rq.get("seq", -1))
    except ValueError:
        raise ValueError("неверный номер куска") from None
    return panel.recparts.add(self.rec_owner(), str(rq.get("id", "")), seg, seq, self.body(),
                              self.headers.get("Content-Type", ""))


def stt(self):
    """POST_RAW /api/stt — запись голоса → текст: сразу или фоново (``?job=1``, GAS-34)"""
    panel = self.panel
    if "job=1" in urllib.parse.urlparse(self.path).query:   # фоново, GAS-34
        n, ctype = int(self.headers.get("Content-Length", 0) or 0), self.headers.get("Content-Type", "")
        if self.raw is None and n > MAX_VOICE:                 # запись не теряем: сначала на диск, потом причина
            name = panel.stt_keep_stream(self.rfile, min(n, KEEP_CAP), ctype)
            raise ValueError(f"запись {n >> 20} МБ длиннее предела распознавания {MAX_VOICE >> 20} МБ — сохранена на "
                             f"сервере ({name}); разбейте на части или скачайте и пришлите файлом")
        return panel.stt_job(self.body(MAX_VOICE), ctype, self.terms_uid(), cloud=not self.space())
    before = panel.fallback_note()
    text = panel.stt(self.body(), self.headers.get("Content-Type", ""), cloud=not self.space())
    now = panel.fallback_note()
    return {"text": text, "fallback": now if now and now != before else ""}


def rec_finish(self, b: dict):
    """POST /api/rec/finish — «Стоп»: куски с сервера — в распознавание"""
    panel = self.panel
    return panel.rec_finish(self.rec_owner(), str(b.get("id", "")), self.terms_uid(),
                            cloud=not self.space())


def rec_drop(self, b: dict):
    """POST /api/rec/drop — «Отменить запись»: куски — прочь"""
    panel = self.panel
    return {"ok": panel.recparts.drop(self.rec_owner(), str(b.get("id", "")))}


def stt_retry(self, b: dict):
    """POST /api/stt/retry — повтор нераспознанной записи — с сервера (GAS-34)"""
    panel = self.panel
    return panel.stt_retry(str(b.get("id", "")), self.terms_uid())


def voice_choose(self, b: dict):
    """POST /api/voice/choose"""
    panel = self.panel
    panel.choose_voice(str(b.get("id", "")))
    return panel.voice_cards(True)


GET = {"/api/tts/about": tts_about, "/api/rec/status": rec_status, "/api/stt/job": stt_job,
       "/api/voice/cards": voice_cards, "/api/voice/preview": voice_preview}
GET_W = {"/api/tts": tts, "/api/tts/warm": tts_warm}
POST_RAW = {"/api/rec/chunk": rec_chunk, "/api/stt": stt}
POST = {"/api/rec/finish": rec_finish, "/api/rec/drop": rec_drop, "/api/stt/retry": stt_retry,
        "/api/voice/choose": voice_choose}
