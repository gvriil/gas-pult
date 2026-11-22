"""Мессенджеры «как пользователь» (решение владельца 22.11, вариант А — человек решает сам): Telegram, Signal, WhatsApp.

Устройство (docs/MESSENGERS.md):
- каждый мост — отдельный процесс ``python -m gas_pult.messengers.host <svc>`` с unix-сокетом ``host.sock`` в папке
  данных человека; запускается по первому запросу и сам выключается после ``IDLE`` секунд без запросов;
- внешние программы — Telethon (Python), signal-cli, Node + Baileys — ставит человек сам (команды — в ``need_install``);
- перед первым запуском — выбор человека (``consent``): Telegram — экран согласия по п. 1.5 условий Telegram API,
  Signal и WhatsApp — экран «Неофициальный способ… Решаете вы». Без записи выбора мост не стартует (``spawn``);
- читать — свободно; отправить людям — только черновиком (``connectors/_core.propose``) и после «Да» в панели:
  у моста нет операции «отправить текст», есть только ``apply <id черновика>`` (``_core.take_confirmed``);
- сессии, ключи и входящие — файлы 0600 в папке 0700 (``root``); в ответы API, журнал и git они не попадают.
MAX не подключается: вход пользователем запрещён соглашением (п. 4.3.7, 4.4) — в каталоге только строка.
Только стандартная библиотека.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

IDLE = 600                                   # 10 минут без запросов — мост выключается
INBOX_MAX = 500                              # строк во входящих на диске (старое отрезается)
SRC = Path(__file__).resolve().parents[2]    # папка src: PYTHONPATH процесса моста
TELETHON = "telethon==1.45.0"
BAILEYS = "@whiskeysockets/baileys@7.0.0-rc14"
SIGNAL_CLI = "0.14.10"

# Каталог: что показывает панель. ``risk`` — экран «Неофициальный способ», ``consent`` — экран согласия Telegram.
CATALOG = [
    {"id": "telegram", "title": "Telegram", "about": "Ваш аккаунт: читать чаты, отвечать — после вашего «Да»",
     "how": "Вход по номеру и коду. Нужны api_id и api_hash — свои, с my.telegram.org", "kind": "consent"},
    {"id": "signal", "title": "Signal", "about": "Связанное устройство: читать, отвечать — после вашего «Да»",
     "how": "QR-код — сканируете телефоном, как Signal Desktop", "kind": "risk"},
    {"id": "whatsapp", "title": "WhatsApp", "about": "Связанное устройство: читать, отвечать — после вашего «Да»",
     "how": "QR-код — сканируете телефоном, как WhatsApp Web", "kind": "risk"},
    {"id": "max", "title": "MAX", "about": "Только бот организации", "kind": "off",
     "how": "Вход своим аккаунтом запрещён соглашением MAX (п. 4.3.7, 4.4). Бот организации — Bot API MAX."},
]
SERVICES = ("telegram", "signal", "whatsapp")
TITLES = {c["id"]: c["title"] for c in CATALOG}

# Тексты экранов выбора: версия — в записи выбора (поменяли текст — человек решает заново).
CONSENT_TEXT = {
    "telegram": ("Модель будет читать переписку в чатах, которые вы откроете ей. По условиям Telegram для ИИ "
                 "(п. 1.5 Telegram API Terms) нужно явное согласие собеседников этого чата — спросите их. "
                 "Отправить сообщение модель может только черновиком и только после вашего «Да» в панели."),
    "signal": ("Неофициальный способ. Нарушает условия Signal. Номер могут заблокировать. Лучше отдельный номер. "
               "Решаете вы."),
    "whatsapp": ("Неофициальный способ. Нарушает условия WhatsApp. Номер могут заблокировать. Лучше отдельный номер. "
                 "Решаете вы."),
}
CONSENT_VER = "2026-11-22"
_CHAT = re.compile(r"^[\w@.:+-]{1,80}$")


class ConsentRequired(RuntimeError):
    """Человек не сделал выбор на экране предупреждения — мост не стартует."""


class NotInstalled(RuntimeError):
    """Нет внешней программы (Telethon, signal-cli, Node + Baileys) — панель показывает команду установки."""


class BridgeError(RuntimeError):
    """Мост не ответил или ответил ошибкой — понятный текст для человека."""


# ---------- папки и файлы ----------
def root() -> Path:
    """Папка данных мостов этого человека: ``GAS_MSG_DIR`` или ``<данные пульта>/messengers`` (0700).
    Человек пространства запускает всё от себя — у него своя домашняя папка и своя папка данных."""
    env = os.environ.get("GAS_MSG_DIR")
    if env:
        d = Path(env).expanduser()
    else:
        from gas_pult import config
        d = config.data_dir() / "messengers"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    d.chmod(0o700)
    return d


def svc_dir(svc: str) -> Path:
    if svc not in SERVICES:
        raise ValueError("нет такого мессенджера")
    d = root() / svc
    d.mkdir(exist_ok=True, mode=0o700)
    d.chmod(0o700)
    return d


def write_private(path: Path, text: str) -> None:
    """Файл сразу 0600 и подмена целиком (как ``config.write_private``)."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def mask(who: str) -> str:
    """Номер или имя для экрана: «+7 *** ***-45-67» — последние 4 знака, остальное скрыто."""
    s = re.sub(r"\s", "", str(who or ""))
    return ("*** " + s[-4:]) if len(s) > 4 else "***"


# ---------- выбор человека ----------
def consent(svc: str, by, accepted: bool) -> dict:
    """Записать выбор человека: время, кто, версия текста. «Отмена» — запись снимается, мост останавливается."""
    f = svc_dir(svc) / "consent.json"
    if not accepted:
        f.unlink(missing_ok=True)
        stop(svc)
        return {"ok": True, "consented": False}
    rec = {"svc": svc, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "by": str(by or ""), "ver": CONSENT_VER,
           "text": CONSENT_TEXT[svc]}
    write_private(f, json.dumps(rec, ensure_ascii=False, indent=1))
    return {"ok": True, "consented": True, "at": rec["at"]}


def consented(svc: str) -> dict | None:
    rec = read_json(svc_dir(svc) / "consent.json")
    return rec if isinstance(rec, dict) and rec.get("ver") == CONSENT_VER else None


# ---------- внешние программы ----------
def telethon_python() -> str:
    """Python с Telethon: ``GAS_MSG_TELETHON_PY``, свой venv в папке данных или этот же Python (если пакет есть)."""
    env = os.environ.get("GAS_MSG_TELETHON_PY")
    if env:
        return env
    own = root() / "telegram" / "venv" / "bin" / "python"
    if own.is_file():
        return str(own)
    if importlib.util.find_spec("telethon"):
        return sys.executable
    return ""


def signal_bin() -> str:
    env = os.environ.get("GAS_MSG_SIGNAL_CLI")
    if env:
        return env
    own = root() / "signal" / "bin" / "signal-cli"
    return str(own) if own.is_file() else (shutil.which("signal-cli") or "")


def node() -> str:
    return os.environ.get("GAS_MSG_NODE") or shutil.which("node") or ""


def baileys_dir() -> Path:
    return root() / "whatsapp" / "node"


def need_install(svc: str) -> dict | None:
    """Что поставить, если программы нет: {what, cmd}. Ставит человек сам (решение владельца: не автоматически)."""
    d = root() / svc
    if svc == "telegram" and not telethon_python():
        return {"what": "Telethon (Python)", "cmd": f"python3 -m venv {d}/venv && {d}/venv/bin/pip install {TELETHON}"}
    if svc == "signal" and not signal_bin():
        url = (f"https://github.com/AsamK/signal-cli/releases/download/v{SIGNAL_CLI}/"
               f"signal-cli-{SIGNAL_CLI}-Linux-native.tar.gz")
        return {"what": f"signal-cli {SIGNAL_CLI}",
                "cmd": f"mkdir -p {d}/bin && curl -fsSL {url} | tar xz -C {d}/bin"}
    if svc == "whatsapp":
        if not node():
            return {"what": "Node.js 20+", "cmd": "https://nodejs.org/en/download — затем снова откройте этот экран"}
        if not (baileys_dir() / "node_modules" / "@whiskeysockets" / "baileys").is_dir():
            b = baileys_dir()
            return {"what": f"Baileys {BAILEYS.rsplit('@', 1)[1]}",
                    "cmd": (f"mkdir -p {b} && cd {b} && echo '{{\"private\":true,\"type\":\"module\"}}' > package.json"
                            f" && npm install --no-audit --no-fund --omit=dev --ignore-scripts {BAILEYS}")}
    return None


# ---------- процесс моста ----------
def sock_path(svc: str) -> Path:
    return svc_dir(svc) / "host.sock"


def _talk(sock: Path, req: dict, timeout: float) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(str(sock))
        s.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    try:
        out = json.loads(buf or b"{}")
    except ValueError:
        raise BridgeError("мост ответил непонятно") from None
    if isinstance(out, dict) and out.get("error"):
        raise BridgeError(str(out["error"]))
    return out if isinstance(out, dict) else {}


def running(svc: str) -> bool:
    """Мост запущен? Без запуска: пробуем ``ping`` по сокету."""
    p = sock_path(svc)
    if not p.exists():
        return False
    try:
        _talk(p, {"op": "ping"}, 2)
        return True
    except (OSError, BridgeError):
        return False


def command(svc: str) -> list[str]:
    py = telethon_python() if svc == "telegram" else sys.executable
    return [py or sys.executable, "-m", "gas_pult.messengers.host", svc]


def spawn(svc: str, wait: float = 15.0) -> None:
    """Запустить мост. Без записанного выбора человека — ``ConsentRequired``; без программы — ``NotInstalled``."""
    if not consented(svc):
        raise ConsentRequired("сначала выбор на экране предупреждения: «Подключить» или «Отмена»")
    miss = need_install(svc)
    if miss:
        raise NotInstalled(f"нужно установить {miss['what']}")
    d = svc_dir(svc)
    env = {**os.environ, "GAS_MSG_DIR": str(root()),
           "PYTHONPATH": os.pathsep.join(x for x in (str(SRC), os.environ.get("PYTHONPATH", "")) if x)}
    log = os.open(d / "host.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        subprocess.Popen(command(svc), cwd=d, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         start_new_session=True)
    finally:
        os.close(log)
    until = time.monotonic() + wait
    while time.monotonic() < until:
        if running(svc):
            return
        time.sleep(0.1)
    raise BridgeError("мост не запустился — подробности в host.log в папке данных моста")


def call(svc: str, op: str, timeout: float = 30.0, start: bool = True, **args) -> dict:
    """Запрос к мосту; моста нет — запустить (если ``start``). Ответ — dict; ошибка — ``BridgeError``."""
    p = sock_path(svc)
    try:
        return _talk(p, {"op": op, **args}, timeout)
    except (FileNotFoundError, ConnectionRefusedError):
        if not start:
            raise BridgeError("мост не запущен") from None
    spawn(svc)
    try:
        return _talk(p, {"op": op, **args}, timeout)
    except OSError as e:
        raise BridgeError(f"мост не отвечает: {e}") from None


def stop(svc: str) -> None:
    try:
        _talk(sock_path(svc), {"op": "stop"}, 3)
    except (OSError, BridgeError):
        pass


# ---------- состояние для панели: без секретов ----------
def account(svc: str) -> dict | None:
    rec = read_json(svc_dir(svc) / "account.json")
    return rec if isinstance(rec, dict) and rec.get("connected") else None


def state(svc: str) -> dict:
    c, acc = consented(svc), account(svc)
    out = {"id": svc, "title": TITLES[svc], "consented": bool(c), "consent_at": (c or {}).get("at", ""),
           "connected": bool(acc), "who": (acc or {}).get("who", ""), "running": running(svc),
           "install": need_install(svc), "text": CONSENT_TEXT[svc]}
    if svc == "telegram":
        out["api"] = (svc_dir(svc) / "api.json").is_file()
        out["allowed"] = len(allowed(svc))
    return out


def states() -> dict:
    return {"catalog": CATALOG, "services": [state(s) for s in SERVICES], "idle": IDLE}


def save_tg_api(api_id: str, api_hash: str) -> None:
    """api_id и api_hash человека (my.telegram.org) — в файл 0600; обратно не возвращаются."""
    api_id, api_hash = str(api_id or "").strip(), str(api_hash or "").strip()
    if not re.fullmatch(r"\d{3,12}", api_id):
        raise ValueError("api_id — число со страницы my.telegram.org → API development tools")
    if not re.fullmatch(r"[0-9a-f]{32}", api_hash):
        raise ValueError("api_hash — 32 знака (цифры и буквы a–f) с той же страницы")
    write_private(svc_dir("telegram") / "api.json", json.dumps({"api_id": int(api_id), "api_hash": api_hash}))


def disconnect(svc: str) -> dict:
    """«Отключить»: остановить мост и стереть сессию, ключи и входящие (выбор человека — тоже)."""
    stop(svc)
    d = svc_dir(svc)
    for name in ("account.json", "api.json", "consent.json", "inbox.jsonl", "allowed.json", "tg.session",
                 "tg.session-journal"):
        (d / name).unlink(missing_ok=True)
    for sub in ("auth", "data"):                      # WhatsApp — файлы входа Baileys, Signal — данные signal-cli
        if (d / sub).is_dir() and not (d / sub).is_symlink():
            shutil.rmtree(d / sub, ignore_errors=True)
    return {"ok": True}


# ---------- какие чаты открыты модели (Telegram, п. 1.5: согласие — по конкретному чату) ----------
def allowed(svc: str) -> list[str]:
    d = read_json(svc_dir(svc) / "allowed.json", [])
    return [str(x) for x in d if _CHAT.match(str(x))] if isinstance(d, list) else []


def set_allowed(svc: str, chats: list) -> list[str]:
    ids = [str(x) for x in chats or [] if _CHAT.match(str(x))][:200]
    write_private(svc_dir(svc) / "allowed.json", json.dumps(ids))
    return ids


# ---------- входящие: файл 0600 в папке моста ----------
def inbox_append(d: Path, items: list[dict]) -> None:
    if not items:
        return
    f = d / "inbox.jsonl"
    try:
        lines = f.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    lines += [json.dumps(x, ensure_ascii=False) for x in items]
    write_private(f, "\n".join(lines[-INBOX_MAX:]) + "\n")


def inbox_read(d: Path, since: float = 0, chat: str = "") -> list[dict]:
    out = []
    try:
        lines = (d / "inbox.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            x = json.loads(line)
        except ValueError:
            continue
        if isinstance(x, dict) and float(x.get("ts") or 0) >= since and (not chat or str(x.get("chat")) == chat):
            out.append(x)
    return out


def recent(since: float, timeout: float = 12.0) -> tuple[list[dict], list[dict]]:
    """Для «Сегодня» (brief.py): входящие подключённых мостов с ``since`` и состояние каждого. Модель не участвует."""
    items, status = [], []
    for svc in SERVICES:
        try:
            if not (consented(svc) and account(svc)):
                continue
            got = call(svc, "inbox", timeout=timeout, since=since).get("items") or []
            items += [{**x, "svc": svc} for x in got if isinstance(x, dict)]
            status.append({"id": "msg:" + svc, "label": TITLES[svc], "state": "ok"})
        except (BridgeError, ConsentRequired, NotInstalled, OSError, ValueError) as e:
            status.append({"id": "msg:" + svc, "label": TITLES[svc], "state": "error", "note": str(e)[:200]})
    return items, status


def connected() -> list[str]:
    return [s for s in SERVICES if consented(s) and account(s)]
