"""Мастер первого запуска: установлен ли Claude Code, выполнен ли вход, есть ли ключи поставщиков — и вход из пульта.

Бот и панель стартуют и без Claude Code: ``status()`` говорит, чего не хватает, ``Login`` проводит вход.

Вход — ``claude auth login`` (подписка Claude, как ``/login`` внутри Claude Code) в отдельном окне tmux: учётные данные
ложатся в каталог конфигурации Claude, и с ними работают все сессии пульта. ``claude setup-token`` не подходит:
он только печатает долгоживущий токен, который потом нужно положить в переменную окружения каждой сессии
(это запасной путь — в ``docs/SETUP-CLAUDE.md``). Окно — в своей сессии tmux ``<сессия>-setup`` с меткой ``login``:
пульт видит только окна основной сессии, поэтому окно входа не становится «сессией» ни в боте, ни в панели.
Окно ищется по метке, так что бот и панель (разные процессы) ведут один и тот же вход.

``config_dir`` (``CLAUDE_CONFIG_DIR``) и ``env`` (добавочные переменные) — чтобы потом вести вход в отдельную папку
конфигурации каждого человека. По умолчанию — как сейчас: окружение процесса пульта.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from gas_pult import providers
from gas_pult.tmux import Tmux

DOC_URL = "https://github.com/gvriil/gas-pult/blob/main/docs/SETUP-CLAUDE.md"
INSTALL_URL = "https://docs.claude.com/en/docs/claude-code/setup"
MARK = "login"                                   # метка окна входа (@gas_pult) — не поставщик модели
WINDOW = "claude-login"
TIMEOUT = 15
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Код со страницы входа: «буквы-цифры#буквы-цифры» и родственные; пробелов и переводов строки не бывает.
CODE = re.compile(r"^[A-Za-z0-9#_.~+/=-]{4,512}$")
URL = re.compile(r"https://\S+")
URL_TAIL = re.compile(r"^\s*([A-Za-z0-9%&=_.~:/?#+-]+)\s*$")
ASKS_CODE = re.compile(r"paste\s+(the\s+)?(authorization\s+)?code|enter\s+(the\s+)?(authorization\s+)?code"
                       r"|code\s+here|authorization\s+code", re.I)
DONE = re.compile(r"login successful|logged in as|successfully (logged|signed) in", re.I)
ERROR = re.compile(r"\b(error|failed|invalid|expired)\b", re.I)


def executable(claude: str = "claude") -> str:
    """Первое слово команды запуска (``cfg.claude`` бывает «claude --какой-то-флаг»)."""
    try:
        return (shlex.split(claude) or ["claude"])[0]
    except ValueError:
        return "claude"


def installed(claude: str = "claude") -> str | None:
    """Полный путь к Claude Code или None."""
    return shutil.which(executable(claude))


def _env(config_dir: str | os.PathLike | None, env: dict | None) -> dict:
    e = {**os.environ, **(env or {})}
    if config_dir:
        e["CLAUDE_CONFIG_DIR"] = str(config_dir)
    return e


def version(exe: str) -> str:
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (r.stdout.strip().splitlines() or [""])[0][:80]


def auth(exe: str, config_dir=None, env: dict | None = None) -> dict:
    """Выполнен ли вход — без сети: ``claude auth status --json``. Старый Claude без этой команды — по признакам:
    ключ в окружении или файл учётных данных в каталоге конфигурации. ``logged_in``: True / False / None (неизвестно).
    Почту и организацию не отдаём — в панели и боте они ни к чему."""
    e = _env(config_dir, env)
    try:
        r = subprocess.run([exe, "auth", "status", "--json"], capture_output=True, text=True, timeout=TIMEOUT, env=e)
        d = json.loads(r.stdout)
        if isinstance(d, dict) and "loggedIn" in d:
            return {"logged_in": bool(d["loggedIn"]), "method": str(d.get("authMethod") or ""),
                    "provider": str(d.get("apiProvider") or ""), "plan": str(d.get("subscriptionType") or ""),
                    "how": "claude auth status"}
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"):
        if e.get(var):
            return {"logged_in": True, "method": var, "provider": "", "plan": "", "how": "переменная окружения"}
    base = Path(e.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    if (base / ".credentials.json").exists():
        return {"logged_in": True, "method": "claude.ai", "provider": "", "plan": "", "how": "файл учётных данных"}
    return {"logged_in": None, "method": "", "provider": "", "plan": "", "how": "не удалось проверить"}


def status(claude: str = "claude", config_dir=None, env: dict | None = None) -> dict:
    """Что готово. ``ready`` — Claude Code установлен и вход не провален (неизвестно — не мешаем работать).
    ``checks`` — строки для «Проверки» в боте, панели и ``gas-pult doctor``: (название, хорошо, что сделать)."""
    path = installed(claude)
    ver = version(path) if path else ""
    au = auth(path, config_dir, env) if path else {"logged_in": False, "method": "", "provider": "", "plan": "",
                                                    "how": ""}
    keys = sorted(k for k in providers.key_info() if k != "elevenlabs")      # ключи моделей, не голоса
    checks = [("tmux", bool(shutil.which("tmux")), "sudo apt install tmux / brew install tmux"),
              (f"Claude Code{' ' + ver if ver else ''}", bool(path), f"установите: {INSTALL_URL}")]
    if path:
        login = {True: f"вход выполнен ({au['method'] or 'есть'})", False: "вход не выполнен",
                 None: "вход: не удалось проверить"}[au["logged_in"]]
        checks.append((login, au["logged_in"] is not False, "«Войти в Claude» в боте или панели"))
    checks.append(("ключи поставщиков: " + (", ".join(providers.NAMES.get(k, k) for k in keys) or "нет"), True, ""))
    return {"ready": bool(path) and au["logged_in"] is not False,
            "claude": {"installed": bool(path), "path": path or "", "version": ver},
            "auth": au, "keys": keys, "doc": DOC_URL, "install": INSTALL_URL,
            "checks": [{"name": n, "ok": ok, "hint": "" if ok else h} for n, ok, h in checks]}


def text(st: dict) -> str:
    """«Проверка» коротко — для бота."""
    return "\n".join(("✅ " if c["ok"] else "❌ ") + c["name"] + (f" — {c['hint']}" if c["hint"] else "")
                     for c in st["checks"])


def parse(lines: list[str]) -> dict:
    """Экран ``claude auth login``: ссылка входа (продолжение — следующими строками), просит ли код, успех, ошибка."""
    url = ""
    for i, line in enumerate(lines):
        if m := URL.search(line):
            url, prev = m.group(0), line
            for nxt in lines[i + 1:]:      # перенос по ширине окна: строка кончается ссылкой, следующая — её хвост
                if len(prev.rstrip()) < 60 or not prev.rstrip().endswith(url[-20:]):
                    break
                if not (t := URL_TAIL.match(nxt)) or ASKS_CODE.search(nxt):
                    break
                url, prev = url + t.group(1), nxt
            if re.search(r"oauth|authorize|login", url, re.I):
                break
    url = url.rstrip(".,)»\"'")
    err = next((x.strip() for x in reversed(lines) if ERROR.search(x)), "")
    return {"url": url, "code": any(ASKS_CODE.search(x) for x in lines),
            "done": any(DONE.search(x) for x in lines), "error": err[:300]}


class Login:
    """Вход в Claude Code через окно tmux: start → ссылка человеку → send_code(код) → finish."""

    def __init__(self, session: str, claude: str = "claude", config_dir=None, env: dict | None = None,
                 tmux: Tmux | None = None, home: str = ""):
        self.tmux = tmux or Tmux(f"{session}-setup")
        self.claude, self.config_dir, self.env = claude, config_dir, dict(env or {})
        self.home = home or os.path.expanduser("~")

    def command(self) -> str:
        pre = {**self.env, **({"CLAUDE_CONFIG_DIR": str(self.config_dir)} if self.config_dir else {})}
        for k in pre:
            if not ENV_NAME.match(k):
                raise ValueError(f"имя переменной: {k!r}")
        env = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in pre.items())
        return (f"env {env} " if env else "") + f"{shlex.quote(executable(self.claude))} auth login"

    def window(self) -> dict | None:
        try:
            return next((w for w in self.tmux.windows() if w.get("mark") == MARK), None)
        except OSError:                              # tmux не установлен — окна входа нет
            return None

    def read(self) -> dict:
        w = self.window()
        if not w:
            return {"active": False, "url": "", "code": False, "done": False, "error": "", "lines": []}
        lines = self.tmux.screen(w["id"], 60)
        return {"active": w["cmd"] == "claude", "w": w["id"], **parse(lines), "lines": lines[-15:]}

    def start(self, wait: int = 20) -> dict:
        """Окно входа (уже открытое — то же) и ссылка с экрана. Claude Code не установлен — ошибка сразу."""
        if not installed(self.claude):
            raise RuntimeError(f"Claude Code не установлен — {INSTALL_URL}")
        w = self.window()
        if w and w["cmd"] != "claude":              # прошлый вход закончился — окно с оболочкой больше не нужно
            self.tmux.kill(w["id"])
            w = None
        if not w:
            self.tmux.new_window(WINDOW, self.home, self.command(), mark=MARK)
        st = self.read()
        for i in range(wait):
            if st["url"] or st["done"] or (i >= 3 and not st["active"]):     # Claude вышел сразу — ошибка на экране
                break
            time.sleep(1)
            st = self.read()
        return st

    def send_code(self, code: str, wait: int = 20) -> dict:
        """Код со страницы входа — в окно (вставка и Enter); ждём итога и проверяем вход."""
        code = "".join(str(code).split())
        if not CODE.match(code):
            raise ValueError("это не похоже на код входа: скопируйте его со страницы целиком")
        w = self.window()
        if not w or w["cmd"] != "claude":
            raise LookupError("окна входа нет — нажмите «Войти в Claude» ещё раз")
        self.tmux.paste(w["id"], code)
        st = self.read()
        for _ in range(wait):
            if st["done"] or not st["active"]:
                break
            time.sleep(1)
            st = self.read()
        return self.finish(st)

    def finish(self, st: dict | None = None) -> dict:
        """Вход подтвердился — окно закрываем; нет — оставляем: человек посмотрит экран или повторит код."""
        st = st or self.read()
        au = auth(installed(self.claude) or executable(self.claude), self.config_dir, self.env)
        ok = au["logged_in"] is True
        if ok and (w := self.window()):
            self.tmux.kill(w["id"])
        return {**st, "ok": ok, "auth": au}

    def cancel(self):
        if w := self.window():
            self.tmux.kill(w["id"])
