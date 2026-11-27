"""Голос бота: озвучка ответов и выбор голоса (/voice и ⚙️ Настройки).

Часть класса ``bot.Pult`` (модульный монолит, docs/MONOLITH-PLAN.md п.3.3): методы перенесены как есть, ``self`` —
тот же ``Pult``. Пакет называется ``botparts``, а не ``bot``: пакет ``gas_pult/bot/`` заслонил бы модуль ``bot.py``.
"""

from __future__ import annotations

import uuid

from gas_pult import providers, speech, transcripts, voice
from gas_pult.telegram import TelegramError, kb
from gas_pult.voice import catalog


class VoicePart:
    """Озвучка ответов и выбор голоса (примесь к ``Pult``)."""

    # ---------- голос ----------
    def say(self, chat: int, text: str):
        clean = speech.speakable(transcripts.clean(text)[:3500])   # ~3–4 минуты речи; числа и латиница — словами
        if not clean:
            return
        v, have = self.state()["voice"], catalog.installed(self.cfg.personal_voices)   # бот — только владельцам
        if v not in have:                                # выбранный недоступен — тихо читаем запасным (Piper)
            if not have:
                return self.send(chat, f"Голос «{catalog.label(v)}» не установлен: gas-pult voices install {v}")
            v = have[0]
        base = self.cfg.data / f"out-{uuid.uuid4().hex}"
        try:
            if not self.state().get("audio_only"):
                try:
                    voice.synth(v, clean, base.with_suffix(".ogg"))
                    data = base.with_suffix(".ogg").read_bytes()
                    return self.api("sendVoice", chat_id=chat, files={"voice": ("answer.ogg", data)})
                except TelegramError as e:  # приватность Telegram запрещает голосовые → аудиофайл
                    if "VOICE_MESSAGES_FORBIDDEN" not in e.description:
                        raise
                    self.set_state(audio_only=True)
            voice.synth(v, clean, base.with_suffix(".mp3"))
            self.api("sendAudio", chat_id=chat, title="Ответ Claude", performer="gas-pult",
                     files={"audio": ("answer.mp3", base.with_suffix(".mp3").read_bytes())})
        finally:
            for ext in (".ogg", ".mp3"):
                base.with_suffix(ext).unlink(missing_ok=True)

    # ---------- выбор голоса: /voice и ⚙️ Настройки (карточки — как на экране «Голос» панели) ----------
    def el_voice_id(self) -> str | None:
        """Голос ElevenLabs: выбранный или первый из аккаунта."""
        key = providers.load_keys().get("elevenlabs")
        if not key:
            return None
        return self.state().get("el_voice") or next(iter(providers.el_voices(key)), {}).get("id")

    def choose_voice(self, vid: str):
        """Выбор карточкой — одно действие: локальный голос — ``tts_provider=local`` и ``voice``; ElevenLabs —
        ``tts_provider=elevenlabs`` (голос ElevenLabs — выбранный раньше или первый из аккаунта)."""
        if vid == "elevenlabs":
            if "elevenlabs" not in providers.key_info():
                raise ValueError("нужен ключ ElevenLabs — панель → Подключения → Ключи API")
            upd = {"tts_provider": "elevenlabs"}
            if not self.state().get("el_voice") and (first := self.el_voice_id()):
                upd["el_voice"] = first
            return self.set_state(**upd)
        if vid in catalog.FALLBACK:                       # Piper — только запасной синтез, в выборе его нет
            raise ValueError(f"«{catalog.label(vid)}» больше не выбирается — выберите голос из списка")
        if vid not in catalog.selectable(self.cfg.personal_voices):           # выбирает владелец
            raise ValueError(f"этот голос не установлен: gas-pult voices install {vid}")
        self.set_state(tts_provider="local", voice=vid)

    def voice_preview(self, vid: str, personal: bool, ext: str = "mp3") -> tuple[bytes, str]:
        """«Послушать»: фраза из кеша ``<data>/voice-preview`` → (данные, расширение). Silero — только при
        ``personal`` (владельцу при ``personal_voices``); ElevenLabs — всегда mp3, запрос — только в первый раз."""
        cache = self.cfg.data / "voice-preview"
        if vid == "elevenlabs":
            key = providers.load_keys().get("elevenlabs")
            if not key or not (el := self.el_voice_id()):
                raise ValueError("нужен ключ ElevenLabs")
            return voice.preview(cache, vid, el=(key, el)), "mp3"
        if vid not in catalog.installed(personal):
            raise ValueError("этот голос недоступен")
        return voice.preview(cache, vid, ext), ext

    def current_voice(self) -> str:
        s = self.state()
        return "elevenlabs" if s.get("tts_provider") == "elevenlabs" and "elevenlabs" in providers.key_info() \
            else s["voice"]

    def voice_rows(self) -> list:
        """Сетка: на голос — «▶ имя» (послушать) и «✅ имя · пол» (выбрать); не установленные — одной кнопкой."""
        cur, rows = self.current_voice(), []
        if "elevenlabs" in providers.key_info():
            rows.append([("▶ ElevenLabs", "vp:elevenlabs"), (("✅ " if cur == "elevenlabs" else "") + "ElevenLabs",
                                                             "vs:elevenlabs")])
        else:
            rows.append([("ElevenLabs — нужен ключ", "vi:elevenlabs")])
        for c in catalog.cards(self.cfg.personal_voices, owner=True):
            if c["ok"]:
                demo = " · демо" if c.get("demo") else ""
                rows.append([(f"▶ {c['name']}", f"vp:{c['id']}"),
                             (("✅ " if c["id"] == cur else "") + f"{c['name']} · {c['kind']}{demo}", f"vs:{c['id']}")])
            else:
                rows.append([(f"⬇ {c['name']} — не установлен", f"vi:{c['id']}")])
        return rows

    def voice_text(self) -> str:
        cur, s = self.current_voice(), self.state()
        if cur == "elevenlabs":
            line = f"🗣 Голос: ElevenLabs (озвучка в панели); голосовые бота — {catalog.label(s['voice'])}"
        elif cur in catalog.FALLBACK or cur not in catalog.installed(self.cfg.personal_voices):
            have = catalog.installed(self.cfg.personal_voices)
            v = cur if cur in have else (have[0] if have else cur)
            line = f"🗣 Голос: запасной голос сервера ({catalog.label(v)}) — выберите голос ниже"
        else:
            line = f"🗣 Голос: {catalog.label(cur)}"
        return line + "\n▶ — послушать, имя — выбрать." + (
            "\n«Демо» — голоса с некоммерческой лицензией, только для показа." if self.cfg.personal_voices else "")

    def show_voice(self, chat: int, q: dict | None = None):
        """/voice. Из кнопки — обновляем то же сообщение (галочка переезжает), иначе — новое."""
        text, markup = self.voice_text(), kb(self.voice_rows())
        msg = (q or {}).get("message") or {}
        if msg.get("message_id"):
            try:
                return self.api("editMessageText", chat_id=chat, message_id=msg["message_id"], text=text,
                                reply_markup=markup)
            except TelegramError:
                pass
        self.send(chat, text, reply_markup=markup)

    def on_voice(self, chat: int, kind: str, vid: str, q: dict):
        if kind == "vi":
            if vid == "elevenlabs":
                return self.send(chat, "Ключ ElevenLabs — в панели: Подключения → Голос → Ключи API.")
            return self.send(chat, f"«{catalog.label(vid)}» не установлен. На сервере: gas-pult voices install {vid}")
        if kind == "vs":
            try:
                self.choose_voice(vid)
            except ValueError as e:
                return self.send(chat, str(e))
            return self.show_voice(chat, q)
        ext = "mp3" if self.state().get("audio_only") else "ogg"
        try:
            data, ext = self.voice_preview(vid, self.cfg.personal_voices, ext)
        except (ValueError, RuntimeError, OSError, providers.ProviderError) as e:
            return self.send(chat, f"Не получилось послушать: {e}")
        name = "ElevenLabs" if vid == "elevenlabs" else catalog.label(vid)
        if ext == "ogg":
            try:
                return self.api("sendVoice", chat_id=chat, caption=name, files={"voice": (f"{vid}.ogg", data)})
            except TelegramError as e:      # приватность Telegram запрещает голосовые → дальше аудиофайлом
                if "VOICE_MESSAGES_FORBIDDEN" not in e.description:
                    raise
                self.set_state(audio_only=True)
                return self.on_voice(chat, kind, vid, q)
        self.api("sendAudio", chat_id=chat, title=name, performer="gas-pult", files={"audio": (f"{vid}.mp3", data)})
