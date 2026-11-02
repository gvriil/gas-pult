"""Вход по ключу доступа (passkey, WebAuthn): Face ID, отпечаток или PIN устройства вместо кода.

**Необязательная функция.** Проверку подписей (COSE, CBOR, authenticatorData) делает пакет ``webauthn`` (py_webauthn,
Duo Labs, BSD-3-Clause) — он ставится отдельно: ``pip install "gas-pult[passkeys]"``. Импорт — ленивый: без пакета или
без ``rp_id`` и ``origin`` в секции ``[passkeys]`` config.toml функция выключена — кнопки нет, API отвечает «выключено»,
остальной пульт работает как раньше.

**Правила** (как у входа по ключу в других проектах GASTECH):

- ключ — discoverable (``residentKey: required``), личность проверяет устройство (``userVerification: required``),
  ``attestation: none``;
- в устройство уходит случайный ``user_handle`` (32 байта), не Telegram ID и не имя; один на человека, общий для всех
  его ключей;
- вызов (challenge) живёт на сервере 5 минут и одноразовый: снимается при первой же проверке, у каждой церемонии свой
  номер (браузер знает только его);
- начало регистрации и входа — не больше 20 раз за 10 минут с одного IP;
- ``sign_count`` сверяется (откат счётчика — отказ) и сохраняется;
- несколько ключей на человека, у каждого — название; добавить и удалить — только из «Настроек» вошедшего человека;
- журнал — строки ``auth: passkey_…`` (регистрация, вход, удаление, неудачи) без ключей и вызовов.

Ключи — ``<data>/passkeys.json`` (0600, атомарная запись): id ключа, открытый ключ, счётчик, user_handle, uid, название,
даты. Секретов там нет: закрытый ключ остаётся в устройстве. Подробно — docs/AUTH.md.
"""

from __future__ import annotations

import base64
import hashlib
import importlib
import importlib.util
import json
import secrets
import threading
import time
from collections.abc import Callable
from pathlib import Path

from gas_pult.config import write_private
from gas_pult.emailcode import LimitError, log

CHALLENGE_TTL = 300
START_LIMIT = (20, 600)                 # начал регистрации и входа с одного IP — за 10 минут
MAX_KEYS = 10                           # ключей на человека
PACKAGE = "webauthn"


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64url(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def package_ok() -> bool:
    """Установлен ли пакет webauthn (без импорта — он тянет cryptography)."""
    try:
        return importlib.util.find_spec(PACKAGE) is not None
    except (ImportError, ValueError):
        return False


def _wa():
    """Ленивый импорт: модуль пульта грузится и без пакета."""
    return importlib.import_module(PACKAGE)


def origins(section: dict) -> list[str]:
    o = section.get("origin") or []
    return [o] if isinstance(o, str) else [str(x) for x in o]


class Passkeys:
    def __init__(self, section: dict | None, people, store: Path, clock: Callable[[], float] = time.time):
        self.section, self.people, self.store, self.clock = dict(section or {}), people, store, clock
        self.lock = threading.Lock()

    # ---------- настройки ----------
    @property
    def rp_id(self) -> str:
        return str(self.section.get("rp_id") or "")

    @property
    def enabled(self) -> bool:
        return bool(self.rp_id and origins(self.section)) and package_ok()

    def need(self):
        if not (self.rp_id and origins(self.section)):
            raise RuntimeError("вход по ключу не настроен — владелец задаёт rp_id и origin в [passkeys] config.toml")
        if not package_ok():
            raise RuntimeError("вход по ключу выключен: на сервере нет пакета webauthn "
                               "(pip install \"gas-pult[passkeys]\")")

    # ---------- файл ----------
    def _load(self) -> dict:
        try:
            d = json.loads(self.store.read_text())
        except (OSError, ValueError):
            d = {}
        now = self.clock()
        return {"creds": d.get("creds") or {}, "handles": d.get("handles") or {},
                "challenges": {k: v for k, v in (d.get("challenges") or {}).items() if v.get("exp", 0) > now},
                "starts": {k: [t for t in v if now - t < START_LIMIT[1]] for k, v in (d.get("starts") or {}).items()}}

    def _save(self, d: dict):
        d["starts"] = {k: v for k, v in d["starts"].items() if v}
        write_private(self.store, json.dumps(d))

    def _begin(self, d: dict, ip: str, kind: str, challenge: bytes, **extra) -> str:
        """Лимит по IP и новый одноразовый вызов; браузеру — только номер церемонии."""
        now = self.clock()
        starts = d["starts"].setdefault(_h("ip:" + ip), [])
        if len(starts) >= START_LIMIT[0]:
            log("passkey_rate_limited", kind=kind, ip=ip)
            raise LimitError("Слишком много попыток — подождите 10 минут.", int(START_LIMIT[1] - (now - starts[0])) + 1)
        starts.append(now)
        cid = secrets.token_urlsafe(24)
        d["challenges"][_h(cid)] = {"challenge": b64url(challenge), "exp": now + CHALLENGE_TTL, "kind": kind, **extra}
        return cid

    def _take(self, d: dict, cid: str, kind: str) -> dict:
        """Одноразово: вызов снимается при первой же проверке (и при чужом виде церемонии тоже)."""
        st = d["challenges"].pop(_h(str(cid or "")), None)
        if not st or st.get("kind") != kind:
            raise ValueError("Время на подтверждение истекло — попробуйте ещё раз.")
        return st

    # ---------- регистрация (из настроек вошедшего) ----------
    def register_options(self, uid: int, label: str = "", ip: str = "") -> dict:
        self.need()
        wa = _wa()
        from webauthn.helpers.structs import (
            AttestationConveyancePreference,
            AuthenticatorSelectionCriteria,
            PublicKeyCredentialDescriptor,
            ResidentKeyRequirement,
            UserVerificationRequirement,
        )

        uid = int(uid)
        with self.lock:
            d = self._load()
            mine = [k for k, c in d["creds"].items() if c["uid"] == uid]
            if len(mine) >= MAX_KEYS:
                raise ValueError(f"Ключей уже {MAX_KEYS} — удалите ненужный.")
            handle = d["handles"].get(str(uid)) or b64url(secrets.token_bytes(32))
            name = (label or "").strip()[:60] or "Пульт gas-pult"
            opts = wa.generate_registration_options(
                rp_id=self.rp_id, rp_name=str(self.section.get("rp_name") or "gas-pult"),
                user_id=unb64url(handle), user_name=name, user_display_name=name,
                attestation=AttestationConveyancePreference.NONE,
                authenticator_selection=AuthenticatorSelectionCriteria(
                    resident_key=ResidentKeyRequirement.REQUIRED,
                    user_verification=UserVerificationRequirement.REQUIRED),
                exclude_credentials=[PublicKeyCredentialDescriptor(id=unb64url(k)) for k in mine],
                timeout=CHALLENGE_TTL * 1000)
            cid = self._begin(d, ip, "reg", opts.challenge, uid=uid, handle=handle)
            self._save(d)
        return {"id": cid, "options": json.loads(wa.options_to_json(opts))}

    def register_verify(self, uid: int, cid: str, credential, name: str = "", ip: str = "") -> list[dict]:
        self.need()
        wa = _wa()
        from webauthn.helpers.exceptions import InvalidRegistrationResponse

        uid = int(uid)
        with self.lock:
            d = self._load()
            st = self._take(d, cid, "reg")
            self._save(d)                                         # вызов снят — повтор того же ответа не пройдёт
        if st.get("uid") != uid:
            raise ValueError("Время на подтверждение истекло — попробуйте ещё раз.")
        try:
            v = wa.verify_registration_response(
                credential=credential, expected_challenge=unb64url(st["challenge"]), expected_rp_id=self.rp_id,
                expected_origin=origins(self.section), require_user_verification=True)
        except (InvalidRegistrationResponse, KeyError, TypeError, ValueError) as e:
            log("passkey_register_failed", uid=uid, ip=ip, why=type(e).__name__)
            raise ValueError("Не удалось сохранить ключ — попробуйте ещё раз.") from None
        cred_id = b64url(v.credential_id)
        resp = credential.get("response") if isinstance(credential, dict) else None
        transports = (resp.get("transports") if isinstance(resp, dict) else None) or []
        with self.lock:
            d = self._load()
            if cred_id in d["creds"]:
                raise ValueError("Этот ключ уже сохранён.")
            d["handles"][str(uid)] = st["handle"]
            now = int(self.clock())
            d["creds"][cred_id] = {"uid": uid, "public_key": b64url(v.credential_public_key),
                                   "sign_count": int(v.sign_count), "user_handle": st["handle"],
                                   "name": (name or "").strip()[:40] or "Ключ входа", "created": now, "last_used": None,
                                   "transports": [t for t in transports if isinstance(t, str)][:8]}
            self._save(d)
        log("passkey_registered", uid=uid, ip=ip)
        return self.list(uid)

    # ---------- вход (без входа) ----------
    def login_options(self, ip: str = "") -> dict:
        self.need()
        wa = _wa()
        from webauthn.helpers.structs import UserVerificationRequirement

        opts = wa.generate_authentication_options(
            rp_id=self.rp_id, user_verification=UserVerificationRequirement.REQUIRED, timeout=CHALLENGE_TTL * 1000)
        with self.lock:
            d = self._load()
            cid = self._begin(d, ip, "auth", opts.challenge)
            self._save(d)
        return {"id": cid, "options": json.loads(wa.options_to_json(opts))}

    def login_verify(self, cid: str, credential, ip: str = "") -> int:
        self.need()
        wa = _wa()
        from webauthn.helpers.exceptions import InvalidAuthenticationResponse

        with self.lock:
            d = self._load()
            st = self._take(d, cid, "auth")
            self._save(d)
        cred = credential if isinstance(credential, dict) else {}
        key = str(cred.get("id") or "")
        stored = d["creds"].get(key)
        if not stored:
            log("passkey_login_failed", ip=ip, why="unknown")
            raise ValueError("Этот ключ пульту неизвестен — добавьте его в «Настройках» после входа.")
        handle = (cred.get("response") or {}).get("userHandle")
        if handle and handle != stored["user_handle"]:
            log("passkey_login_failed", uid=stored["uid"], ip=ip, why="handle")
            raise ValueError("Не удалось войти по ключу.")
        if not self.people.role(stored["uid"]):
            log("passkey_login_failed", uid=stored["uid"], ip=ip, why="no_role")
            raise ValueError("Доступа к пульту больше нет.")
        try:
            v = wa.verify_authentication_response(
                credential=cred, expected_challenge=unb64url(st["challenge"]), expected_rp_id=self.rp_id,
                expected_origin=origins(self.section), credential_public_key=unb64url(stored["public_key"]),
                credential_current_sign_count=int(stored["sign_count"]), require_user_verification=True)
        except (InvalidAuthenticationResponse, KeyError, TypeError, ValueError) as e:
            log("passkey_login_failed", uid=stored["uid"], ip=ip, why=type(e).__name__)
            raise ValueError("Не удалось войти по ключу.") from None
        with self.lock:
            d = self._load()
            if key in d["creds"]:
                d["creds"][key].update(sign_count=int(v.new_sign_count), last_used=int(self.clock()))
                self._save(d)
        log("passkey_login_ok", uid=stored["uid"], ip=ip)
        return int(stored["uid"])

    # ---------- список и удаление ----------
    def list(self, uid) -> list[dict]:
        d = self._load()
        return sorted(({"id": k, "name": c["name"], "created": c["created"], "last_used": c.get("last_used")}
                       for k, c in d["creds"].items() if c["uid"] == int(uid)), key=lambda x: x["created"])

    def remove(self, uid, cred_id: str) -> list[dict]:
        with self.lock:
            d = self._load()
            c = d["creds"].get(str(cred_id))
            if not c or c["uid"] != int(uid):
                raise LookupError("такого ключа нет")
            d["creds"].pop(str(cred_id))
            self._save(d)
        log("passkey_removed", uid=uid)
        return self.list(uid)

    def info(self, uid) -> dict:
        return {"enabled": self.enabled, "keys": self.list(uid)}
