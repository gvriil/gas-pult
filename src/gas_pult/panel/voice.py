"""Голос панели: настройки, карточки голосов, распознавание (и фоновое), озвучка.

Часть класса ``webapp.Panel`` (модульный монолит, docs/MONOLITH-PLAN.md п.3.1): методы перенесены как есть, ``self`` —
тот же ``Panel``. Константы и помощники модуля ``webapp`` (``STT_*``, ``brief`` …) реэкспортируются оттуда.
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from gas_pult import asr, harness, providers, speech, transcripts, voice
from gas_pult.voice import catalog

AUDIO_EXT = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav"}
STT_TIMEOUT = 85                                          # с; панель ждёт ответа 90 с
STT_JOB_TIMEOUT = 40 * 60                                 # с: фоновое распознавание длинной записи (GAS-34)
STT_KEEP_DAYS = 7                                         # нераспознанная запись хранится, чтобы повторить
STT_EMPTY = "Ничего не расслышал — попробуйте ещё раз"   # распознавание вернуло пустой текст
EL_PAUSE = 600                                            # ElevenLabs отказал — столько секунд к нему не ходим


HEAD_CHARS = 240             # начало озвучки: первые предложения, не длиннее (служба синтезирует их за ~0,3 с)


def head_of(text: str, limit: int = HEAD_CHARS) -> str:
    """Первые предложения текста, вместе не длиннее ``limit``; одно длинное — до пробела перед ``limit``."""
    out = ""
    for s in re.split(r"(?<=[.!?…])\s+|\n+", text.strip()):
        s = s.strip()
        if not s:
            continue
        if out and len(out) + 1 + len(s) > limit:
            break
        out = f"{out} {s}".strip()
        if len(out) >= limit // 2:
            break
    if len(out) > limit:
        cut = out.rfind(" ", 0, limit)
        out = out[:cut if cut > 0 else limit]
    return out


def brief(text: str, limit: int = 700) -> str:
    """«Кратко» для озвучки: первые абзацы до ~700 знаков — в наших ответах там вывод.

    Сюда приходит текст после ``transcripts.clean``: пустые строки там уже схлопнуты в один перенос, поэтому делим
    по любому переносу. Раньше делили по пустой строке — весь ответ был одним «абзацем», и «кратко» звучало целиком.
    Первый абзац длиннее лимита режем по концу предложения (нет его — по пробелу)."""
    out = ""
    for para in re.split(r"\n+", text.strip()):
        if not (para := para.strip()):
            continue
        if out and len(out) + len(para) + 1 > limit:
            break
        if len(para) > limit:                        # сюда попадаем только с пустым out
            end = max(para.rfind(c, 0, limit) for c in ".!?…")
            if end < limit // 3:
                sp = para.rfind(" ", 0, limit)
                end = (sp if sp > 0 else limit) - 1
            out = para[:end + 1]
            break
        out += para + "\n"
    return out.strip()


class VoicePart:
    """Голос: настройки, карточки, распознавание, озвучка (примесь к ``Panel``)."""

    def voice(self, voices: list[str] | None = None, personal: bool = False) -> str | None:
        """Голос из настроек, если он доступен этому человеку; иначе — первый доступный (Silero → Piper)."""
        voices = catalog.installed(personal) if voices is None else voices
        v = self.pult.state().get("voice")
        return v if v in voices else (voices[0] if voices else None)

    # ---------- голос: локально или ElevenLabs ----------
    def voice_settings(self) -> dict:
        st, keys = self.pult.state(), providers.key_info()
        el, own = "elevenlabs" in keys, self.cfg.personal_voices        # настройки голоса — только владельцу
        return {"tts": st.get("tts_provider", "local") if el else "local",
                "stt": st.get("stt_provider", "local") if el else "local",
                "el_voice": st.get("el_voice"), "keys": keys,
                "local_voice": catalog.label(self.voice(personal=own) or ""),
                "fallback": self.fallback_note(), "voice": self.voice(personal=own),
                "local_voices": [{"id": v, "name": catalog.label(v)} for v in catalog.installed(own)]}

    def el_voices(self) -> list[dict]:
        key = providers.load_keys().get("elevenlabs")
        return providers.el_voices(key) if key else []

    def el_voice_name(self, vid: str | None) -> str:
        """Имя голоса ElevenLabs для карточки (список аккаунта — не чаще раза в 10 минут)."""
        t, voices = getattr(self, "_el_names", (0.0, []))
        if time.time() - t > 600:
            try:
                voices = self.el_voices()
            except providers.ProviderError:
                voices = []
            self._el_names = (time.time(), voices)
        return next((v["name"] for v in voices if v["id"] == vid), "")

    # ---------- карточки голосов: экран «Голос», шторка у ответа, /voice в боте ----------
    def voice_cards(self, owner: bool, cloud: bool = True) -> dict:
        """Голоса, доступные этому человеку: ElevenLabs первой, затем локальные (``catalog.ORDER``). Silero — только
        владельцу при ``personal_voices``; не установленные — только владельцу. Выбирает — владелец.
        ``cloud=False`` — тестировщик пространства: только локальные (ключ ElevenLabs — владельца)."""
        personal = owner and self.cfg.personal_voices
        st, key = self.pult.state(), cloud and "elevenlabs" in providers.key_info()
        out = []
        if cloud and (key or owner):
            vid = st.get("el_voice") if key else None
            out.append({"id": "elevenlabs", "name": (self.el_voice_name(vid) if vid else "") or "ElevenLabs",
                        "kind": "облачный", "ok": key, "why": "" if key else "нужен ключ ElevenLabs", "install": ""})
        out += catalog.cards(personal, owner)
        cur = "elevenlabs" if key and st.get("tts_provider") == "elevenlabs" else self.voice(personal=personal)
        # Голос без карточки (Piper: выбран раньше или запасной) — читает дальше; панель пишет, что это запасной.
        fb = catalog.label(cur) if cur and cur in catalog.FALLBACK else ""
        return {"cards": out, "current": cur, "can_choose": owner, "fallback": fb}

    def choose_voice(self, vid: str):
        self.pult.choose_voice(vid)                          # общее с ботом (/voice)

    def voice_preview(self, vid: str, owner: bool) -> bytes:
        return self.pult.voice_preview(vid, owner and self.cfg.personal_voices)[0]

    def set_providers(self, b: dict):
        el = "elevenlabs" in providers.key_info()
        upd = {}
        for k in ("tts", "stt"):
            if k in b:
                if b[k] not in ("local", "elevenlabs") or (b[k] == "elevenlabs" and not el):
                    raise ValueError("сначала сохраните ключ ElevenLabs")
                upd[f"{k}_provider"] = b[k]
        if b.get("el_voice"):
            upd["el_voice"] = str(b["el_voice"])
        if b.get("voice"):
            if b["voice"] not in catalog.selectable(self.cfg.personal_voices):  # настройки голоса — владельцу
                raise ValueError("этот голос не установлен: gas-pult voices install <имя>")
            upd["voice"] = str(b["voice"])
        self.pult.set_state(**upd)

    def voice_fallback(self, what: str, e: Exception):
        """ElevenLabs отказал — работаем локально и сообщаем: журнал службы и ``fallback`` в /api/providers.
        Отказ сервиса (лимит, ключ, сеть) запоминаем на ``EL_PAUSE`` с: каждая следующая запись не ждёт ответа
        ElevenLabs (до ``providers.TIMEOUT`` = 2 мин при зависшей сети), а сразу идёт локально."""
        note = f"ElevenLabs недоступен ({what}): {e} — переключился на локальный голос"
        print(note, file=sys.stderr, flush=True)
        self.last_fallback = (time.time(), note)
        if isinstance(e, providers.ProviderError):
            self.el_pause_until = time.time() + EL_PAUSE

    def el_ok(self) -> bool:
        """ElevenLabs не отказывал последние ``EL_PAUSE`` с (см. ``voice_fallback``)."""
        return time.time() >= getattr(self, "el_pause_until", 0.0)

    def fallback_note(self) -> str:
        t, note = getattr(self, "last_fallback", (0, ""))
        return note if time.time() - t < 3600 else ""

    def stt(self, data: bytes, ctype: str, cloud: bool = True) -> str:
        """Голос из панели → текст. Пустая запись или пустой результат — понятная ошибка (400), не пустая строка."""
        if not data:
            raise ValueError(STT_EMPTY)
        ext = AUDIO_EXT.get(ctype.split(";")[0], "webm")
        if cloud and self.voice_settings()["stt"] == "elevenlabs" and self.el_ok():
            try:
                text = (providers.el_stt(providers.load_keys()["elevenlabs"], data, f"voice.{ext}") or "").strip()
                if not text:
                    raise ValueError(STT_EMPTY)
                return text
            except (providers.ProviderError, KeyError) as e:     # запасной путь — локальный whisper, молча не падаем
                self.voice_fallback("распознавание", e)
        path = self.cfg.data / "inbox" / f"web-{uuid.uuid4().hex}.{ext}"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(data)
        try:                                             # служба T-one, нет её — whisper (voice.transcribe_any)
            text = (voice.transcribe_any(path, self.cfg.whisper_model, STT_TIMEOUT, self.cfg.data) or "").strip()
        except subprocess.TimeoutExpired:            # панель ждёт 90 с — сервер сдаётся чуть раньше и говорит почему
            raise RuntimeError(f"распознавание не уложилось в {STT_TIMEOUT} с — длинная запись или сервер занят") \
                from None
        finally:
            path.unlink(missing_ok=True)                 # голос не храним
        if not text:
            raise ValueError(STT_EMPTY)
        return text

    # ---------- фоновое распознавание: запись не теряется (GAS-34, владелец 18.11) ----------
    # Запись сначала ложится на сервер (``voice-keep``, 0600), потом распознаётся в фоне без лимита 90 с; панель
    # опрашивает ``/api/stt/job``. Готово — файл удаляется; не вышло — остаётся на ``STT_KEEP_DAYS`` дней для повтора.
    def _keep_dir(self) -> Path:
        d = self.cfg.data / "voice-keep"
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        return d

    def stt_keep_stream(self, src, n: int, ctype: str) -> str:
        """Запись больше предела распознавания — на диск по кускам (не в память), чтобы не пропала. Имя файла."""
        f = self._keep_dir() / f"big-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}." \
            f"{AUDIO_EXT.get(ctype.split(';')[0], 'webm')}"
        with f.open("wb") as out:
            f.chmod(0o600)
            left = n
            while left > 0 and (chunk := src.read(min(left, 1 << 20))):
                out.write(chunk)
                left -= len(chunk)
        self.events.event("stt_keep_big", "stt:" + f.stem, bytes=n - left)
        return f.name

    def stt_job(self, data: bytes | list[bytes], ctype: str, uid, cloud: bool = True) -> dict:
        """``data`` — запись или её отрезки (запись по кускам после обрыва: у отрезка свой заголовок файла —
        распознаём по отдельности, текст склеиваем)."""
        segs = [x for x in (data if isinstance(data, list) else [data]) if x]
        if not segs:
            raise ValueError(STT_EMPTY)
        ext = AUDIO_EXT.get(ctype.split(";")[0], "webm")
        d, jid = self._keep_dir(), uuid.uuid4().hex[:16]
        old = time.time() - STT_KEEP_DAYS * 86400
        for f in d.iterdir():                             # старые нераспознанные — прочь
            if f.stat().st_mtime < old:
                f.unlink(missing_ok=True)
        names = []
        for i, x in enumerate(segs):
            f = d / (f"{jid}.{ext}" if not i else f"{jid}-{i}.{ext}")
            f.write_bytes(x)
            f.chmod(0o600)
            names.append(f.name)
        self.stt_jobs[jid] = {"state": "work", "uid": uid, "at": time.time(), "file": names[0], "cloud": cloud,
                              **({"files": names} if len(names) > 1 else {})}
        self.events.event("stt_start", "stt:" + jid, bytes=sum(map(len, segs)))
        threading.Thread(target=self._stt_run, args=(jid,), daemon=True, name=f"stt-{jid}").start()
        return {"job": jid}

    def _stt_run(self, jid: str):
        job = self.stt_jobs[jid]
        fs = [self._keep_dir() / n for n in job.get("files") or [job["file"]]]
        f = fs[0]
        before = self.fallback_note()
        try:
            parts = []
            for x in fs:                                  # отрезки записи (после обрыва) — по отдельности
                parts.append(self._stt_file(x, job["cloud"]))
            text = " ".join(t for t in parts if t).strip()
            if not text:
                raise ValueError(STT_EMPTY)
            now = self.fallback_note()
            for x in fs:
                x.unlink(missing_ok=True)                 # текст есть — голос не храним
            fb = now if now and now != before else ""
            self.events.event("stt_done", "stt:" + jid, secs=round(time.time() - job["at"], 1), len=len(text),
                              fallback=bool(fb))
            job.update(state="done", text=text, fallback=fb)      # последним: панель видит «готово» — файла уже нет
        except Exception as e:                            # запись остаётся: «Повторить» возьмёт её с сервера
            job.update(state="fail", error=str(e) or type(e).__name__, kept=f.exists())
            self.events.event("stt_fail", "stt:" + jid, secs=round(time.time() - job["at"], 1), err=type(e).__name__)
            print(f"распознавание {jid}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)

    def _stt_file(self, f: Path, cloud: bool) -> str:
        text = ""
        if cloud and self.voice_settings()["stt"] == "elevenlabs" and self.el_ok():
            try:
                ext = f.suffix.lstrip(".")
                text = (providers.el_stt(providers.load_keys()["elevenlabs"], f.read_bytes(), f"voice.{ext}")
                        or "").strip()
            except (providers.ProviderError, KeyError) as e:
                self.voice_fallback("распознавание", e)
        return text or (voice.transcribe_any(f, self.cfg.whisper_model, STT_JOB_TIMEOUT, self.cfg.data) or "").strip()

    def rec_finish(self, owner: str, rid: str, uid, cloud: bool = True) -> dict:
        """«Стоп» записи по кускам: куски с сервера — в фоновое распознавание (как ``/api/stt?job=1``); сеанс — прочь.
        Не хватает куска — ``ValueError`` (панель дошлёт и повторит или отправит запись целиком)."""
        segs, ctype = self.recparts.assemble(owner, rid)
        out = self.stt_job(segs, ctype, uid, cloud)
        self.recparts.drop(owner, rid)
        return {**out, "segs": len(segs)}

    def stt_job_get(self, jid: str, uid) -> dict:
        job = self.stt_jobs.get(str(jid))
        if not job or job["uid"] != uid:
            raise LookupError("распознавания нет — запишите ещё раз")
        out = {"state": job["state"], "sec": round(time.time() - job["at"])}
        out.update({k: job[k] for k in ("text", "error", "fallback", "kept") if k in job})
        return out

    def stt_retry(self, jid: str, uid) -> dict:
        job = self.stt_jobs.get(str(jid))
        if not job or job["uid"] != uid or job["state"] != "fail" or not (self._keep_dir() / job["file"]).exists():
            raise LookupError("записи для повтора нет")
        job.update(state="work", at=time.time())
        for k in ("error", "kept"):
            job.pop(k, None)
        threading.Thread(target=self._stt_run, args=(jid,), daemon=True, name=f"stt-{jid}").start()
        return {"job": jid}

    def stt_stream(self, rate: int) -> asr.Stream:
        """Поток в службу распознавания; её нет или занята — ``asr.Unavailable`` (панель уйдёт на ``/api/stt``).
        Служба ушла после простоя — поднимаем её (до ``asr.START_WAIT`` с; звук панель копит, пока нет ``ready``)."""
        asr.ensure_service(self.cfg.data)
        return asr.Stream(rate, partials=True, path=asr.socket_path(self.cfg.data))

    def message(self, w: dict, i: int | None) -> str:
        home, sid = self.pult.home_of(w), w.get("sid") or ""
        if i is None:
            return harness.of(w).last_answer(w["path"], home, sid)
        items, _ = harness.of(w).history(w["path"], limit=1, before=i + 1, home=home, sid=sid)
        if not items or items[0]["i"] != i:
            raise ValueError("сообщение не найдено — обновите переписку")
        return items[0]["text"]

    def tts(self, w: dict, full: bool, msg: int | None = None, personal: bool = False, cloud: bool = True,
            head: bool = False) -> bytes:
        """``head`` — только начало ответа (первые предложения): панель играет его сразу, пока готовится весь
        ответ, — первый звук через доли секунды, а не после синтеза всего текста (#190)."""
        text = transcripts.clean(self.message(w, msg))
        text = (text if full else brief(text))[:3500]   # «кратко» (full=0) — для старых панелей; новая шлёт full=1
        if head:
            text = head_of(text)
        if not text:
            raise ValueError("нечего озвучивать")
        return self.tts_text(text, personal, cloud)

    def tts_text(self, text: str, personal: bool = False, cloud: bool = True) -> bytes:
        """Озвучить готовый текст: ElevenLabs (если выбран и отвечает) или локальный голос."""
        vs = self.voice_settings()
        el = cloud and vs["tts"] == "elevenlabs" and self.el_ok()
        text = speech.speakable(text, latin_ok=el)      # числа словами; латиница — ElevenLabs читает сам
        if el:
            voice_id = vs["el_voice"] or next(iter(self.el_voices()), {}).get("id")
            if not voice_id:
                raise ValueError("в аккаунте ElevenLabs нет голосов")
            try:
                return providers.el_tts(providers.load_keys()["elevenlabs"], voice_id, text)
            except (providers.ProviderError, KeyError) as e:     # запасной путь — локальный голос
                self.voice_fallback("озвучка", e)
        v = self.voice(personal=personal)                # Silero — только владельцу лично, остальным — Piper
        if not v:
            raise ValueError("голоса не установлены: gas-pult voices install irina")
        out = self.cfg.data / f"web-{uuid.uuid4().hex}.mp3"
        try:
            voice.synth(v, text, out)
            return out.read_bytes()
        finally:
            out.unlink(missing_ok=True)

    def tts_warm(self, personal: bool = False) -> dict:
        """Человек открыл сессию — поднять службу озвучки и загрузить голос заранее (в фоне, ответ сразу)."""
        vs = self.voice_settings()
        if vs["tts"] == "elevenlabs" and self.el_ok():
            return {"ok": True, "voice": "elevenlabs"}
        v = self.voice(personal=personal)
        if v:
            voice.warm(v, self.cfg.data)
        return {"ok": bool(v), "voice": v or ""}
