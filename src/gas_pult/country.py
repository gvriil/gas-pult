"""Страна человека — по трём признакам: выбор, код номера телефона, IP (локальная база GeoIP).

1. **Выбор.** При первом входе (после условий использования) человек сам выбирает страну: кнопками частых или кодом
   ISO 3166-1 из двух букв.
2. **Телефон.** В Telegram — кнопка «Поделиться номером» (``request_contact``). Берём только код страны номера
   (``phone_country``); сам номер не храним — только HMAC-SHA256 с солью установки (``<data>/country_salt``, 0600,
   создаётся один раз и в git не попадает). В панели номер не подтверждается — только в боте.
3. **IP.** При каждом входе в панель (и не реже раза в ``IP_EVERY`` на запросах) — страна адреса клиента по локальной
   базе db-ip lite (``<data>/geoip/dbip-country-lite.csv[.gz]``), без внешних запросов с данными человека. IP не
   храним — только код страны и время. Базы нет — признак «нет данных»: по нему не блокируем, владелец видит отметку.
   В боте IP недоступен: Telegram его не передаёт.

Что доступно — ровно то, что разрешено поставщиком **для каждой** страны из признаков (``models.allowed``).
Признаки расходятся — пересечение (то, что разрешено для всех) и одна строка владельцам (``notice``).
Страна не выбрана — недоступно ничего; к странам человека всегда добавляется страна сервера (``check_set``).

Запись человека: ``{"chosen", "phone_cc", "phone_hash", "phone_at", "ip_cc", "ip_at", "mismatch"}``
(хранит ``People.set_country``). База GeoIP: «IP Geolocation by DB-IP» (https://db-ip.com), лицензия CC BY 4.0;
загружается только командой владельца ``gas-pult geoip update``.
"""

from __future__ import annotations

import bisect
import gzip
import hashlib
import hmac
import ipaddress
import re
import secrets
import threading
import time
import urllib.request
from array import array
from pathlib import Path

from gas_pult.config import write_private

DENY = "Этот сервис недоступен в вашей стране по условиям поставщика"
IP_EVERY = 600                  # страна по IP на запросах панели — не чаще раза в 10 минут на человека
ATTRIBUTION = "IP Geolocation by DB-IP"
ATTRIBUTION_URL = "https://db-ip.com"
GEOIP_URL = "https://download.db-ip.com/free/dbip-country-lite-{ym}.csv.gz"
GEOIP_FILES = ("dbip-country-lite.csv.gz", "dbip-country-lite.csv")
LOCAL = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10",
                                           "fc00::/7")]

# ISO 3166-1 alpha-2 (и XK — Косово, его используют db-ip и операторы связи)
_ISO = """
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC
CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD
GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH
KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW
MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC
SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY
UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW XK
"""
ISO = frozenset(_ISO.split())

# Названия по-русски — для частых; остальные страны показываем кодом (их вводят кодом из двух букв).
NAMES = {
    "NL": "Нидерланды", "DE": "Германия", "GB": "Великобритания", "FR": "Франция", "ES": "Испания", "IT": "Италия",
    "PT": "Португалия", "PL": "Польша", "CZ": "Чехия", "AT": "Австрия", "BE": "Бельгия", "CH": "Швейцария",
    "SE": "Швеция", "FI": "Финляндия", "NO": "Норвегия", "DK": "Дания", "IE": "Ирландия", "GR": "Греция",
    "CY": "Кипр", "EE": "Эстония", "LV": "Латвия", "LT": "Литва", "RS": "Сербия", "ME": "Черногория",
    "TR": "Турция", "GE": "Грузия", "AM": "Армения", "AZ": "Азербайджан", "KZ": "Казахстан", "UZ": "Узбекистан",
    "KG": "Киргизия", "UA": "Украина", "MD": "Молдова", "IL": "Израиль", "AE": "ОАЭ", "TH": "Таиланд",
    "ID": "Индонезия", "VN": "Вьетнам", "IN": "Индия", "JP": "Япония", "KR": "Южная Корея", "SG": "Сингапур",
    "US": "США", "CA": "Канада", "MX": "Мексика", "BR": "Бразилия", "AR": "Аргентина", "AU": "Австралия",
    "RU": "Россия", "BY": "Беларусь", "CN": "Китай", "HK": "Гонконг", "IR": "Иран",
}
# Кнопки выбора — частые у людей пульта; любая другая страна — кодом.
COMMON = ("NL", "DE", "GB", "FR", "ES", "PT", "PL", "CY", "RS", "TR", "GE", "AM", "KZ", "AE", "IL", "US", "RU", "BY")

# Коды телефонов (E.164) → страна. Коды без префиксных пересечений, поэтому ищем самый длинный (3 → 2 → 1 цифра).
# Общие коды: +1 (NANP) — «US/CA», +7 — RU, кроме +7 6xx / 7xx (KZ). Неоднозначный код — все варианты: при проверке
# поставщик должен разрешать каждую страну (самая строгая трактовка).
PHONE = {
    "1": "US/CA", "20": "EG", "211": "SS", "212": "MA", "213": "DZ", "216": "TN", "218": "LY", "220": "GM",
    "221": "SN", "222": "MR", "223": "ML", "224": "GN", "225": "CI", "226": "BF", "227": "NE", "228": "TG",
    "229": "BJ", "230": "MU", "231": "LR", "232": "SL", "233": "GH", "234": "NG", "235": "TD", "236": "CF",
    "237": "CM", "238": "CV", "239": "ST", "240": "GQ", "241": "GA", "242": "CG", "243": "CD", "244": "AO",
    "245": "GW", "246": "IO", "248": "SC", "249": "SD", "250": "RW", "251": "ET", "252": "SO", "253": "DJ",
    "254": "KE", "255": "TZ", "256": "UG", "257": "BI", "258": "MZ", "260": "ZM", "261": "MG", "262": "RE/YT",
    "263": "ZW", "264": "NA", "265": "MW", "266": "LS", "267": "BW", "268": "SZ", "269": "KM", "27": "ZA",
    "290": "SH", "291": "ER", "297": "AW", "298": "FO", "299": "GL",
    "30": "GR", "31": "NL", "32": "BE", "33": "FR", "34": "ES", "350": "GI", "351": "PT", "352": "LU", "353": "IE",
    "354": "IS", "355": "AL", "356": "MT", "357": "CY", "358": "FI", "359": "BG", "36": "HU", "370": "LT",
    "371": "LV", "372": "EE", "373": "MD", "374": "AM", "375": "BY", "376": "AD", "377": "MC", "378": "SM",
    "380": "UA", "381": "RS", "382": "ME", "383": "XK", "385": "HR", "386": "SI", "387": "BA", "389": "MK",
    "39": "IT", "40": "RO", "41": "CH", "420": "CZ", "421": "SK", "423": "LI", "43": "AT", "44": "GB", "45": "DK",
    "46": "SE", "47": "NO", "48": "PL", "49": "DE",
    "500": "FK", "501": "BZ", "502": "GT", "503": "SV", "504": "HN", "505": "NI", "506": "CR", "507": "PA",
    "508": "PM", "509": "HT", "51": "PE", "52": "MX", "53": "CU", "54": "AR", "55": "BR", "56": "CL", "57": "CO",
    "58": "VE", "590": "GP", "591": "BO", "592": "GY", "593": "EC", "594": "GF", "595": "PY", "596": "MQ",
    "597": "SR", "598": "UY", "599": "CW",
    "60": "MY", "61": "AU", "62": "ID", "63": "PH", "64": "NZ", "65": "SG", "66": "TH", "670": "TL", "672": "NF",
    "673": "BN", "674": "NR", "675": "PG", "676": "TO", "677": "SB", "678": "VU", "679": "FJ", "680": "PW",
    "681": "WF", "682": "CK", "683": "NU", "685": "WS", "686": "KI", "687": "NC", "688": "TV", "689": "PF",
    "690": "TK", "691": "FM", "692": "MH",
    "81": "JP", "82": "KR", "84": "VN", "850": "KP", "852": "HK", "853": "MO", "855": "KH", "856": "LA", "86": "CN",
    "880": "BD", "886": "TW",
    "90": "TR", "91": "IN", "92": "PK", "93": "AF", "94": "LK", "95": "MM", "960": "MV", "961": "LB", "962": "JO",
    "963": "SY", "964": "IQ", "965": "KW", "966": "SA", "967": "YE", "968": "OM", "970": "PS", "971": "AE",
    "972": "IL", "973": "BH", "974": "QA", "975": "BT", "976": "MN", "977": "NP", "98": "IR", "992": "TJ",
    "993": "TM", "994": "AZ", "995": "GE", "996": "KG", "998": "UZ",
}


def norm(code) -> str:
    """Код страны из ввода человека → ISO из двух букв или «» (не страна)."""
    c = str(code or "").strip().upper()
    return c if c in ISO else ""


def name(code: str) -> str:
    return NAMES.get(code, code)


def codes(x) -> set[str]:
    """«US/CA», «NL», {"NL"}, None → множество кодов."""
    if not x:
        return set()
    if isinstance(x, str):
        return {c for c in re.split(r"[/,\s]+", x.upper()) if c}
    return {str(c).upper() for c in x if c}


# ---------- телефон ----------
def phone_country(e164: str) -> str:
    """Номер в международном виде (+31…, 0031…, 31…) → код страны («NL», «US/CA») или «» (неизвестный код)."""
    d = re.sub(r"\D", "", str(e164 or ""))
    d = d[2:] if d.startswith("00") else d
    if not d:
        return ""
    if d[0] == "7":
        return "KZ" if d[1:2] in ("6", "7") else "RU"
    return next((PHONE[d[:n]] for n in (3, 2, 1) if d[:n] in PHONE), "")


def salt(data: Path) -> bytes:
    """Соль установки для хеша номеров: создаётся один раз (0600), дальше читается. В git не попадает."""
    f = Path(data) / "country_salt"
    with _salt_lock:
        try:
            s = f.read_text().strip()
        except OSError:
            s = ""
        if len(s) < 32:
            s = secrets.token_hex(32)
            write_private(f, s + "\n")
    return bytes.fromhex(s)


_salt_lock = threading.Lock()


def phone_hash(e164: str, key: bytes) -> str:
    return hmac.new(key, re.sub(r"\D", "", str(e164 or "")).lstrip("0").encode(), hashlib.sha256).hexdigest()


def phone_record(e164: str, data: Path) -> dict:
    """Что храним о номере: хеш с солью, код страны и время. Сам номер — нигде."""
    return {"phone_hash": phone_hash(e164, salt(data)), "phone_cc": phone_country(e164), "phone_at": int(time.time())}


# ---------- три признака ----------
def signals(rec: dict | None) -> list[set[str]]:
    rec = rec or {}
    return [s for s in (codes(rec.get("chosen")), codes(rec.get("phone_cc")), codes(rec.get("ip_cc"))) if s]


def effective(rec: dict | None) -> set[str]:
    """Все страны из имеющихся признаков. Сервис доступен, только если поставщик разрешает каждую."""
    return set().union(*signals(rec))


def is_mismatch(rec: dict | None) -> bool:
    """Признаки расходятся: какие-то два не сходятся ни в одной стране («US/CA» и «CA» — сходятся)."""
    s = signals(rec)
    return any(not (a & b) for i, a in enumerate(s) for b in s[i + 1:])


def check_set(rec: dict | None, region: str = "") -> set[str]:
    """Страны для проверки поставщика: страна не выбрана — пусто (недоступно ничего); иначе признаки и страна
    сервера (``region`` из config.toml)."""
    if not norm((rec or {}).get("chosen")):
        return set()
    return effective(rec) | codes(region)


def public(rec: dict | None) -> dict:
    """Для панели и «Людей»: коды стран и время, без хеша номера."""
    rec = rec or {}
    return {"chosen": rec.get("chosen", ""), "phone_cc": rec.get("phone_cc", ""), "phone": bool(rec.get("phone_hash")),
            "phone_at": rec.get("phone_at"), "ip_cc": rec.get("ip_cc", ""), "ip_at": rec.get("ip_at"),
            "mismatch": bool(rec.get("mismatch")), "effective": sorted(effective(rec))}


def notice(who: str, uid, rec: dict) -> str:
    """Строка владельцам о расхождении: имя/ID и коды стран — без номера и IP."""
    return (f"⚠️ Страна не сходится: {who} (ID {uid}) — выбор {rec.get('chosen') or '—'}, номер "
            f"{rec.get('phone_cc') or '—'}, IP {rec.get('ip_cc') or 'нет данных'}. Доступно только то, что "
            "поставщики разрешают для всех этих стран.")


# ---------- GeoIP: локальная база db-ip lite ----------
class GeoIP:
    """Страна по IP из CSV db-ip lite (``ip_from,ip_to,cc``; IPv4 и IPv6). Файл читается один раз в отсортированные
    массивы и ищется ``bisect``; поменялся файл (``geoip update``) — перечитывается. Без внешних запросов."""

    def __init__(self, folder: Path):
        self.folder, self.lock = Path(folder), threading.Lock()
        self.stamp = None
        self.v4 = (array("L"), array("L"), array("H"))
        self.v6: tuple[list, list, array] = ([], [], array("H"))
        self.ccs: list[str] = []

    def path(self) -> Path | None:
        return next((self.folder / n for n in GEOIP_FILES if (self.folder / n).is_file()), None)

    def available(self) -> bool:
        return self.path() is not None

    def info(self) -> dict:
        p = self.path()
        return {"geoip": bool(p), "geoip_at": int(p.stat().st_mtime) if p else None,
                "attribution": ATTRIBUTION, "attribution_url": ATTRIBUTION_URL}

    def _load(self):
        p = self.path()
        stamp = (str(p), p.stat().st_mtime, p.stat().st_size) if p else None
        if stamp == self.stamp:
            return
        v4, v6, ccs, idx = ([], [], []), ([], [], []), [], {}
        if p:
            opener = gzip.open if p.suffix == ".gz" else open
            with opener(p, "rt", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    parts = line.strip().strip("﻿").split(",")
                    if len(parts) < 3:
                        continue
                    cc = parts[2].strip().strip('"').upper()
                    try:
                        a, b = ipaddress.ip_address(parts[0].strip('"')), ipaddress.ip_address(parts[1].strip('"'))
                    except ValueError:
                        continue                                  # заголовок или мусор
                    if cc not in idx:
                        idx[cc] = len(ccs)
                        ccs.append(cc)
                    t = v4 if a.version == 4 else v6
                    t[0].append(int(a))
                    t[1].append(int(b))
                    t[2].append(idx[cc])
        for t in (v4, v6):                                        # база отсортирована, но не полагаемся
            order = sorted(range(len(t[0])), key=t[0].__getitem__)
            t[0][:], t[1][:], t[2][:] = [t[0][i] for i in order], [t[1][i] for i in order], [t[2][i] for i in order]
        self.v4 = (array("L", v4[0]), array("L", v4[1]), array("H", v4[2]))
        self.v6 = (v6[0], v6[1], array("H", v6[2]))
        self.ccs, self.stamp = ccs, stamp

    def lookup(self, ip: str) -> str | None:
        """Код страны или ``None`` — нет базы, адрес частный/локальный или его нет в базе («нет данных»)."""
        try:
            a = ipaddress.ip_address(str(ip or "").strip().strip("[]"))
        except ValueError:
            return None
        if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
            a = a.ipv4_mapped
        if a.is_loopback or a.is_link_local or a.is_multicast or a.is_unspecified or any(a in n for n in LOCAL):
            return None                                           # своя сеть — страны у неё нет
        with self.lock:
            self._load()
            starts, ends, cc = self.v4 if a.version == 4 else self.v6
            i = bisect.bisect_right(starts, int(a)) - 1
            if i < 0 or int(a) > ends[i]:
                return None
            code = self.ccs[cc[i]]
        return code if code in ISO else None                       # «ZZ» и прочее — нет данных


def update(folder: Path, opener=urllib.request.urlopen, today=None) -> Path:
    """Скачать свежую базу db-ip lite (только по команде владельца ``gas-pult geoip update``). Файла этого месяца
    ещё нет — берём прошлый. Пишем во временный файл и подменяем целиком, проверив, что это gzip с CSV."""
    t = today or time.gmtime()
    y, m = t.tm_year, t.tm_mon
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    last = None
    for _ in range(2):
        url = GEOIP_URL.format(ym=f"{y:04d}-{m:02d}")
        tmp = folder / ".dbip-download.tmp"
        try:
            with opener(urllib.request.Request(url, headers={"User-Agent": "gas-pult"}), timeout=120) as r, \
                    open(tmp, "wb") as out:
                while chunk := r.read(1 << 16):
                    out.write(chunk)
            with gzip.open(tmp, "rt", encoding="utf-8") as fh:
                if len(fh.readline().split(",")) < 3:
                    raise ValueError("это не база db-ip")
            dest = folder / GEOIP_FILES[0]
            tmp.replace(dest)
            (folder / GEOIP_FILES[1]).unlink(missing_ok=True)       # старый несжатый — чтобы читался новый
            return dest
        except (OSError, ValueError) as e:
            last = e
            tmp.unlink(missing_ok=True)
            y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    raise RuntimeError(f"не скачалось: {last}")
