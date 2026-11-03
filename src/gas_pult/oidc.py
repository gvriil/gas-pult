"""Вход через Google и Яндекс ID — authorization code flow + PKCE (S256), только стандартная библиотека.

**Выключено без настроек.** ``[google]`` / ``[yandex]`` в config.toml: ``client_id``, ``client_secret`` (или
``gas-pult oidc secret google`` → ``secrets.json`` 0600) и адрес возврата (``redirect_uri`` или ``--url`` панели).
Чего-то нет — кнопки нет, API отвечает «выключено».

**Только вход, никаких данных.** Google — ``openid email profile`` (без Gmail и Drive: такие права требуют проверки
приложения Google); Яндекс — ``login:email``. Токены провайдера не сохраняются: после проверки они выбрасываются.

**Правила:**

- ``state`` — одноразовый, живёт 10 минут, на сервере только его SHA-256; к нему привязаны PKCE-``code_verifier``,
  ``nonce`` (Google), ``redirect_uri`` и cookie этого браузера ``gp_oidc`` (SameSite=Lax) — чужой браузер код
  не обменяет (защита от подмены входа);
- Google: ``id_token`` проверяется полностью — подпись RS256 по ключам Google (JWKS, PKCS#1 v1.5 на ``pow``),
  ``iss``, ``aud``, ``azp``, ``exp``, ``iat``, ``nonce``;
- Яндекс ID — не OIDC: id и адрес — из ``login.yandex.ru/info`` по access token;
- войти можно только человеку **с ролью**: по явной привязке (``sub`` → человек, из «Настроек» после входа) или по
  совпадению подтверждённого адреса провайдера с адресом, подтверждённым в пульте кодом (``people.by_email``).
  Google — только при ``email_verified``; Яндекс — только адрес на домене Яндекса (у внешних адресов признака
  подтверждения API не отдаёт). Новых людей вход не заводит;
- ответ одинаковый для «нет такого человека», «адрес не подтверждён» и «нет роли» — адреса не перебрать;
- начало входа и привязки — не больше 20 раз за 10 минут с одного IP;
- журнал — строки ``auth: oidc_…`` без токенов и кодов; адрес — только как ``i***@example.com``.

Привязки — ``<data>/oidc.json`` (0600, атомарная запись) рядом с почтой. Подробно — docs/AUTH.md.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from gas_pult import providers
from gas_pult.config import write_private
from gas_pult.emailcode import LimitError, log, mask, normalize

STATE_TTL = 600
TICKET_TTL = 300                        # одноразовый билет привязки из «Настроек»
START_LIMIT = (20, 600)                 # начал входа и привязки с одного IP — за 10 минут
JWKS_TTL = 3600
SKEW = 120                              # расхождение часов, секунд
TIMEOUT = 15
COOKIE = "gp_oidc"
MIN_RSA_BITS = 2048

PROVIDERS = {
    "google": {
        "title": "Google",
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "jwks": "https://www.googleapis.com/oauth2/v3/certs",
        "issuers": ("https://accounts.google.com", "accounts.google.com"),
        "scope": "openid email profile",
    },
    "yandex": {
        "title": "Яндекс ID",
        "authorize": "https://oauth.yandex.ru/authorize",
        "token": "https://oauth.yandex.ru/token",
        "info": "https://login.yandex.ru/info?format=json",
        "scope": "login:email",
    },
}
# Адреса, которые принадлежат аккаунту Яндекса по построению (ящик на Яндексе) — их можно сверять с пультом.
YANDEX_DOMAINS = ("yandex.ru", "ya.ru", "yandex.com", "yandex.by", "yandex.kz", "yandex.ua", "yandex.com.tr",
                  "narod.ru")
SAME_ANSWER = ("Не получилось войти: этот аккаунт не привязан к пульту. Войдите через Telegram и привяжите его "
               "в «Настройках» → «Способы входа».")
EXPIRED = "Время на вход истекло — начните заново с экрана входа."
# DigestInfo SHA-256 (RFC 8017, 9.2, примечание 1) — то, что лежит внутри подписи PKCS#1 v1.5 перед хешем.
SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def secret_key(provider: str) -> str:
    return f"oidc_{provider}"


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64url(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def pkce() -> tuple[str, str]:
    """(code_verifier, code_challenge S256) — RFC 7636."""
    verifier = secrets.token_urlsafe(48)
    return verifier, b64url(hashlib.sha256(verifier.encode()).digest())


# ---------- подпись RS256 ----------
def rsa_verify(n: int, e: int, message: bytes, sig: bytes) -> bool:
    """RSASSA-PKCS1-v1_5 с SHA-256 (RFC 8017, 8.2.2): s^e mod n и сравнение с эталонным EM целиком."""
    k = (n.bit_length() + 7) // 8
    if n.bit_length() < MIN_RSA_BITS or e < 3 or e % 2 == 0 or len(sig) != k:
        return False
    s = int.from_bytes(sig, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    t = SHA256_PREFIX + hashlib.sha256(message).digest()
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(em, expected)


def parse_jwks(doc) -> dict[str, tuple[int, int]]:
    """kid → (n, e) для ключей RSA с подписью (``use`` нет или ``sig``)."""
    out = {}
    for k in (doc or {}).get("keys", []) if isinstance(doc, dict) else []:
        if not isinstance(k, dict) or k.get("kty") != "RSA" or k.get("use", "sig") != "sig":
            continue
        if k.get("alg", "RS256") != "RS256" or not k.get("kid"):
            continue
        try:
            out[str(k["kid"])] = (int.from_bytes(unb64url(k["n"]), "big"), int.from_bytes(unb64url(k["e"]), "big"))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def verify_id_token(token: str, keys: Callable[[str], tuple[int, int] | None], client_id: str, nonce: str,
                    issuers: tuple[str, ...], now: float) -> dict:
    """Проверка id_token (OIDC Core 3.1.3.7): RS256 по ключу ``kid``, iss, aud, azp, exp, iat, nonce.
    Не сошлось — ValueError."""
    parts = str(token or "").split(".")
    if len(parts) != 3:
        raise ValueError("id_token: не JWT")
    try:
        header, claims, sig = json.loads(unb64url(parts[0])), json.loads(unb64url(parts[1])), unb64url(parts[2])
    except (ValueError, TypeError):
        raise ValueError("id_token: не разбирается") from None
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise ValueError("id_token: не разбирается")
    if header.get("alg") != "RS256":                         # ни «none», ни HS256 с открытым ключом вместо секрета
        raise ValueError("id_token: алгоритм не RS256")
    key = keys(str(header.get("kid") or ""))
    if not key or not rsa_verify(key[0], key[1], f"{parts[0]}.{parts[1]}".encode(), sig):
        raise ValueError("id_token: подпись не сходится")
    if claims.get("iss") not in issuers:
        raise ValueError("id_token: чужой iss")
    aud = claims.get("aud")
    if (aud != client_id) if isinstance(aud, str) else (not isinstance(aud, list) or client_id not in aud):
        raise ValueError("id_token: чужой aud")
    if ((isinstance(aud, list) and len(aud) > 1) or "azp" in claims) and claims.get("azp") != client_id:
        raise ValueError("id_token: чужой azp")
    try:
        exp, iat = float(claims["exp"]), float(claims.get("iat", now))
    except (KeyError, TypeError, ValueError):
        raise ValueError("id_token: нет exp") from None
    if exp + SKEW < now or iat - SKEW > now:
        raise ValueError("id_token: просрочен")
    if not nonce or not hmac.compare_digest(str(claims.get("nonce") or "").encode(), nonce.encode()):
        raise ValueError("id_token: чужой nonce")
    if not claims.get("sub"):
        raise ValueError("id_token: нет sub")
    return claims


# ---------- сеть ----------
def http(url: str, data: dict | None = None, headers: dict | None = None) -> dict:
    """HTTPS-запрос с проверкой сертификата, ответ — JSON. Ошибка провайдера — ValueError без подробностей."""
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"Accept": "application/json", "User-Agent": "gas-pult",
                                                          **(headers or {})})
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl.create_default_context()) as r:
            out = json.loads(r.read(1 << 20))
    except urllib.error.HTTPError as e:
        raise ValueError(f"провайдер ответил {e.code}") from None
    except (OSError, ValueError) as e:
        raise ValueError(f"нет ответа провайдера: {type(e).__name__}") from None
    if not isinstance(out, dict):
        raise ValueError("провайдер ответил не JSON-объектом")
    return out


class Oidc:
    """Вход через Google и Яндекс ID. ``sections`` — {"google": {...}, "yandex": {...}} из config.toml;
    ``base`` — адрес панели снаружи (для redirect_uri по умолчанию); ``fetch`` — подменяется в тестах."""

    def __init__(self, sections: dict | None, people, store: Path, base: Callable[[], str] = lambda: "",
                 clock: Callable[[], float] = time.time, fetch: Callable[..., dict] = http):
        self.sections = {p: dict((sections or {}).get(p) or {}) for p in PROVIDERS}
        self.people, self.store, self.base, self.clock, self.fetch = people, store, base, clock, fetch
        self.lock = threading.Lock()
        self.jwks: tuple[float, dict] = (0.0, {})

    # ---------- настройки ----------
    def settings(self, p: str) -> dict | None:
        """client_id, secret, redirect_uri — или None (выключено)."""
        if p not in PROVIDERS:
            return None
        s = self.sections[p]
        cid = str(s.get("client_id") or "")
        secret = str(s.get("client_secret") or providers.load_keys().get(secret_key(p)) or "")
        base = (self.base() or "").rstrip("/")
        redirect = str(s.get("redirect_uri") or (f"{base}/api/login/oidc/{p}/back" if base else ""))
        if not (cid and secret and redirect.startswith(("https://", "http://127.0.0.1", "http://localhost"))):
            return None
        return {"client_id": cid, "secret": secret, "redirect_uri": redirect}

    def enabled(self, p: str) -> bool:
        return self.settings(p) is not None

    def methods(self) -> dict:
        return {p: self.enabled(p) for p in PROVIDERS}

    def need(self, p: str) -> dict:
        if p not in PROVIDERS:
            raise LookupError("нет такого способа входа")
        if not (s := self.settings(p)):
            raise RuntimeError(f"вход через {PROVIDERS[p]['title']} не настроен — владелец включает его в "
                               f"config.toml ([{p}])")
        return s

    # ---------- файл ----------
    def _load(self) -> dict:
        try:
            d = json.loads(self.store.read_text())
        except (OSError, ValueError):
            d = {}
        d = d if isinstance(d, dict) else {}
        now = self.clock()
        return {"links": d.get("links") or {},
                "states": {k: v for k, v in (d.get("states") or {}).items() if v.get("exp", 0) > now},
                "tickets": {k: v for k, v in (d.get("tickets") or {}).items() if v.get("exp", 0) > now},
                "starts": {k: [t for t in v if now - t < START_LIMIT[1]] for k, v in (d.get("starts") or {}).items()}}

    def _save(self, d: dict):
        d["starts"] = {k: v for k, v in d["starts"].items() if v}
        write_private(self.store, json.dumps(d, ensure_ascii=False))

    def _limit(self, d: dict, ip: str):
        now = self.clock()
        starts = d["starts"].setdefault(_h("ip:" + ip), [])
        if len(starts) >= START_LIMIT[0]:
            log("oidc_rate_limited", ip=ip)
            raise LimitError("Слишком много попыток входа — подождите 10 минут.",
                             int(START_LIMIT[1] - (now - starts[0])) + 1)
        starts.append(now)

    # ---------- начало: адрес провайдера ----------
    def ticket(self, uid: int, p: str, ip: str = "") -> str:
        """Одноразовый билет привязки для вошедшего человека: ссылка ``…/start?link=<билет>`` откроет привязку в любом
        браузере (в Telegram — во внешнем), но только один раз и 5 минут."""
        self.need(p)
        if not self.people.role(uid):
            raise ValueError("Доступа к пульту больше нет.")
        tok = secrets.token_urlsafe(24)
        with self.lock:
            d = self._load()
            self._limit(d, ip)
            d["tickets"][_h(tok)] = {"uid": int(uid), "p": p, "exp": self.clock() + TICKET_TTL}
            self._save(d)
        return tok

    def start(self, p: str, ip: str = "", link: str = "") -> tuple[str, str]:
        """(адрес провайдера для переадресации, значение cookie ``gp_oidc`` этого браузера)."""
        s = self.need(p)
        cfg = PROVIDERS[p]
        state, browser, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        verifier, challenge = pkce()
        with self.lock:
            d = self._load()
            uid = None
            if link:
                t = d["tickets"].pop(_h(str(link)), None)
                if not t or t.get("p") != p:
                    self._save(d)
                    raise ValueError("Ссылка для привязки устарела — нажмите «Привязать» в «Настройках» ещё раз.")
                uid = int(t["uid"])
            else:
                self._limit(d, ip)
            d["states"][_h(state)] = {"p": p, "verifier": verifier, "nonce": nonce, "browser": _h(browser),
                                      "redirect_uri": s["redirect_uri"], "exp": self.clock() + STATE_TTL,
                                      "mode": "link" if uid is not None else "login", "uid": uid}
            self._save(d)
        q = {"response_type": "code", "client_id": s["client_id"], "redirect_uri": s["redirect_uri"],
             "scope": cfg["scope"], "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
        if p == "google":
            q |= {"nonce": nonce, "prompt": "select_account"}
        else:
            q |= {"force_confirm": "yes"}                      # Яндекс: дать выбрать аккаунт
        log("oidc_start", provider=p, mode="link" if link else "login", ip=ip)
        return f"{cfg['authorize']}?{urllib.parse.urlencode(q)}", browser

    # ---------- возврат: код → токен → кто это ----------
    def _key(self, kid: str) -> tuple[int, int] | None:
        ts, keys = self.jwks
        if kid not in keys or self.clock() - ts > JWKS_TTL:   # ключи Google меняются — неизвестный kid → перечитать
            keys = parse_jwks(self.fetch(PROVIDERS["google"]["jwks"]))
            self.jwks = (self.clock(), keys)
        return keys.get(kid)

    def identity(self, p: str, st: dict, code: str, s: dict) -> dict:
        """{sub, email, verified} от провайдера. Ошибка — ValueError."""
        tok = self.fetch(PROVIDERS[p]["token"], {
            "grant_type": "authorization_code", "code": code, "redirect_uri": st["redirect_uri"],
            "client_id": s["client_id"], "client_secret": s["secret"], "code_verifier": st["verifier"]})
        if p == "google":
            c = verify_id_token(str(tok.get("id_token") or ""), self._key, s["client_id"], st["nonce"],
                                PROVIDERS[p]["issuers"], self.clock())
            v = c.get("email_verified")
            return {"sub": str(c["sub"]), "email": normalize(c.get("email")) or "",
                    "verified": v is True or str(v).lower() == "true"}
        access = str(tok.get("access_token") or "")
        if not access:
            raise ValueError("Яндекс не выдал токен")
        info = self.fetch(PROVIDERS[p]["info"], None, {"Authorization": f"OAuth {access}"})
        if str(info.get("client_id") or s["client_id"]) != s["client_id"]:
            raise ValueError("токен Яндекса выдан другому приложению")
        if not info.get("id"):
            raise ValueError("Яндекс не прислал id")
        email = normalize(info.get("default_email")) or ""
        return {"sub": str(info["id"]), "email": email, "verified": email.rpartition("@")[2] in YANDEX_DOMAINS}

    def finish(self, p: str, q: dict, browser: str, ip: str = "") -> dict:
        """Возврат от провайдера → {"mode": "login"|"link", "uid", "provider"}.
        Не вышло — ValueError с текстом для человека."""
        s = self.need(p)
        with self.lock:
            d = self._load()
            st = d["states"].pop(_h(str(q.get("state") or "")), None)      # одноразово — даже при ошибке ниже
            self._save(d)
        if not st or st.get("p") != p or not browser or not hmac.compare_digest(st["browser"], _h(browser)):
            log("oidc_failed", provider=p, ip=ip, why="state")
            raise ValueError(EXPIRED)
        if st["redirect_uri"] != s["redirect_uri"]:                   # настройки поменялись посреди входа
            log("oidc_failed", provider=p, ip=ip, why="redirect_uri")
            raise ValueError(EXPIRED)
        if q.get("error") or not q.get("code"):
            log("oidc_failed", provider=p, ip=ip, why=str(q.get("error") or "no_code")[:40])
            raise ValueError("Вход отменён — можно попробовать ещё раз.")
        try:
            who = self.identity(p, st, str(q["code"])[:2048], s)
        except (ValueError, KeyError, TypeError) as e:
            log("oidc_failed", provider=p, ip=ip, why=str(e)[:60])
            raise ValueError(f"Не удалось проверить вход у {PROVIDERS[p]['title']} — попробуйте ещё раз.") from None
        key = f"{p}:{who['sub']}"
        if st["mode"] == "link":
            return self._link(p, key, int(st["uid"]), who, ip)
        uid = (self._load()["links"].get(key) or {}).get("uid")
        how = "link"
        if uid is None and who["verified"] and who["email"]:
            uid, how = self.people.by_email(who["email"]), "email"
        if uid is None or not self.people.role(uid):
            log("oidc_login_failed", provider=p, ip=ip, to=mask(who["email"]),
                why="no_person" if uid is None else "no_role")
            raise ValueError(SAME_ANSWER)
        log("oidc_login_ok", provider=p, uid=uid, ip=ip, by=how)
        return {"mode": "login", "uid": int(uid), "provider": p}

    def _link(self, p: str, key: str, uid: int, who: dict, ip: str) -> dict:
        if not self.people.role(uid):
            raise ValueError("Доступа к пульту больше нет.")
        with self.lock:
            d = self._load()
            other = (d["links"].get(key) or {}).get("uid")
            if other is not None and other != uid:
                log("oidc_link_failed", provider=p, uid=uid, ip=ip, why="taken")
                raise ValueError(f"Этот аккаунт {PROVIDERS[p]['title']} уже привязан к другому человеку пульта.")
            d["links"] = {k: v for k, v in d["links"].items() if not (k.startswith(p + ":") and v["uid"] == uid)}
            d["links"][key] = {"uid": uid, "email": mask(who["email"]), "at": int(self.clock())}
            self._save(d)
        log("oidc_linked", provider=p, uid=uid, ip=ip)
        return {"mode": "link", "uid": uid, "provider": p}

    # ---------- «Настройки» → «Способы входа» ----------
    def info(self, uid) -> dict:
        links = self._load()["links"]
        mine = {k.partition(":")[0]: v for k, v in links.items() if v.get("uid") == int(uid)}
        return {p: {"enabled": self.enabled(p), "title": PROVIDERS[p]["title"], "linked": p in mine,
                    "email": mine.get(p, {}).get("email", ""), "at": mine.get(p, {}).get("at")} for p in PROVIDERS}

    def unlink(self, uid, p: str) -> dict:
        if p not in PROVIDERS:
            raise LookupError("нет такого способа входа")
        with self.lock:
            d = self._load()
            d["links"] = {k: v for k, v in d["links"].items() if not (k.startswith(p + ":") and v["uid"] == int(uid))}
            self._save(d)
        log("oidc_unlinked", provider=p, uid=uid)
        return self.info(uid)


def set_cookie(value: str, max_age: int = STATE_TTL) -> str:
    """Cookie браузера для одного входа: Lax — её должен прислать возврат с сайта провайдера (Strict не пришлёт)."""
    return f"{COOKIE}={value}; Path=/api/login/oidc/; Max-Age={max_age}; HttpOnly; Secure; SameSite=Lax"


def cookie_value(header: str) -> str:
    for part in (header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE:
            return v
    return ""
