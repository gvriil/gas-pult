"""Репозитории GitHub в живой сессии (задача 43): «Добавить репозиторий» — без перезапуска Claude Code.

- **Сессия владельца**: ``git clone`` в первый корень проектов (``~/projects/<имя>``); папка уже есть — вместо клона
  ``git pull --ff-only``. Список репозиториев — ``gh api user/repos`` (вход ``gh`` владельца).
- **Сессия пространства**: клон в ``<пространство>/home/projects/<имя>`` — от пользователя пространства, в его
  песочнице (``space_sessions.sh``: ``sudo`` пускает пульт только в tmux), токеном GitHub **этого** пространства.
  Токен пульт не видит вообще: его читает маленькая программа уже внутри пространства — из ``secrets.json``
  пространства (ключ ``github``, кладёт владелец: ``pult-tenant key <имя> github``) или из интеграции GitHub его
  Claude Code (``.claude.json`` → ``mcpServers`` → заголовок ``Authorization: Bearer …``). В git он попадает только
  переменными окружения на время команды (``GIT_CONFIG_COUNT``/``KEY``/``VALUE`` → ``http.extraHeader``): не в
  аргументах командной строки, не в адресе remote, не в ``.git/config`` и не в выводе.

Затем в живую сессию уходит ``/add-dir <путь>``; список подключённых хранится в ``state.json`` (``add_dirs``: папка
сессии → пути) — при перезапуске и «Продолжить» (``--continue``) каждый передаётся как ``--add-dir``. «Отключить»
только убирает путь из списка: папка с репозиторием остаётся.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

STATE = "add_dirs"                       # state.json: {папка сессии: [пути репозиториев]}
TOKEN_URL = "https://github.com/settings/personal-access-tokens/new"
OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
LINK = re.compile(r"^(?:https?://)?(?:www\.)?github\.com[/:]([^/\s]+)/([^/\s?#]+?)(?:\.git)?/?(?:[?#].*)?$")
SSH = re.compile(r"^git@github\.com:([^/\s]+)/([^/\s]+?)(?:\.git)?$")
SHORT = re.compile(r"^([^/\s]+)/([^/\s]+?)(?:\.git)?$")
# вывод git и GitHub человеку — без того, что похоже на токен (на всякий случай: токен туда попадать не должен)
SECRET = re.compile(r"(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{8,}|(?i:authorization:\s*\S+(?:\s+\S+)?)")
LIST_TIMEOUT = 40
FETCH_TIMEOUT = 300
NO_TOKEN = "GP_NO_TOKEN"


class NoToken(ValueError):
    """У пространства нет токена GitHub: ``hint`` — где его взять и куда положить."""

    def __init__(self, slug: str):
        self.hint = hint(slug)
        super().__init__(self.hint["text"])


def hint(slug: str) -> dict:
    return {"text": "У этого пространства нет токена GitHub — клонировать закрытые репозитории и показать их список "
                    "нечем.",
            "steps": ["Создайте fine-grained токен на GitHub: доступ — только к нужным репозиториям, права "
                      "Contents: Read (для пуша — Read and write), Metadata: Read.",
                      f"Владелец пульта кладёт его в интеграции пространства: pult-tenant key {slug} github (токен — "
                      "со стандартного ввода, ляжет в secrets.json пространства), — или подключает интеграцию GitHub "
                      "в Claude Code этого пространства.",
                      "Открытый репозиторий можно добавить и без токена — вставьте ссылку."],
            "url": TOKEN_URL}


def scrub(text: str) -> str:
    return SECRET.sub("***", str(text or ""))


def parse(src: str) -> tuple[str, str]:
    """Ссылка или «владелец/имя» → («владелец/имя», имя). Только github.com."""
    s = str(src or "").strip()
    m = LINK.match(s) or SSH.match(s) or (SHORT.match(s) if "://" not in s and ":" not in s else None)
    if not m:
        raise ValueError("нужна ссылка на репозиторий GitHub (https://github.com/владелец/имя) или «владелец/имя»")
    owner, name = m.group(1), m.group(2)
    if not OWNER.match(owner) or not NAME.match(name) or name.startswith(".") or name in (".", ".."):
        raise ValueError("такого имени репозитория на GitHub не бывает")
    return f"{owner}/{name}", name


def clone_url(full: str) -> str:
    return f"https://github.com/{full}.git"


# ---------- список подключённых в state.json ----------
def of(st: dict, path: str) -> list[str]:
    return [str(x) for x in ((st.get(STATE) or {}).get(str(path)) or []) if x]


def flags(st: dict, path: str) -> str:
    """`` --add-dir <путь>`` для каждого подключённого — к команде claude при перезапуске и «Продолжить»."""
    return "".join(f" --add-dir {shlex.quote(d)}" for d in of(st, path))


def added(st: dict, path: str, d: str) -> dict:
    m = {k: list(v) for k, v in (st.get(STATE) or {}).items()}
    cur = m.setdefault(str(path), [])
    if d not in cur:
        cur.append(d)
    return m


def removed(st: dict, path: str, d: str) -> dict:
    m = {k: [x for x in v if x != d] for k, v in (st.get(STATE) or {}).items()}
    return {k: v for k, v in m.items() if v}


def public(paths: list[str]) -> list[dict]:
    return [{"path": p, "name": os.path.basename(p.rstrip("/")) or p} for p in paths]


def _rows(data) -> list[dict]:
    if not isinstance(data, list):
        raise RuntimeError("GitHub ответил непонятно — вставьте ссылку на репозиторий")
    return [{"full": str(x.get("full_name") or ""), "private": bool(x.get("private")),
             "about": str(x.get("description") or "")[:200]}
            for x in data if isinstance(x, dict) and x.get("full_name")]


# ---------- владелец ----------
def _owner_env() -> dict:
    """Без вопросов в терминале; вход — тот, что у git владельца, плюс ``gh`` как помощник входа, если он есть."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if shutil.which("gh"):
        env |= {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "credential.https://github.com.helper",
                "GIT_CONFIG_VALUE_0": "!gh auth git-credential"}
    return env


def owner_list(run=subprocess.run) -> list[dict]:
    try:
        r = run(["gh", "api", "user/repos?per_page=100&sort=updated"], capture_output=True, text=True,
                timeout=LIST_TIMEOUT, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise RuntimeError("на сервере нет gh — вставьте ссылку на репозиторий") from None
    if r.returncode != 0:
        raise RuntimeError("gh не показал репозитории (нет входа? gh auth login) — вставьте ссылку")
    try:
        return _rows(json.loads(r.stdout or "[]"))
    except ValueError:
        raise RuntimeError("gh ответил непонятно — вставьте ссылку на репозиторий") from None


def _same(origin: str, full: str) -> bool:
    o = origin.strip().lower().removesuffix("/").removesuffix(".git")
    return o.endswith("github.com/" + full.lower()) or o.endswith("github.com:" + full.lower())


def owner_fetch(full: str, root: Path, run=subprocess.run) -> tuple[str, str]:
    """Клон в ``root/<имя>`` или ``pull --ff-only``, если там уже этот репозиторий. → (путь, «clone» | «pull»)."""
    full, name = parse(full)
    dest = Path(root) / name
    env = _owner_env()

    def git(*args: str) -> subprocess.CompletedProcess:
        return run(["git", *args], capture_output=True, text=True, timeout=FETCH_TIMEOUT, env=env,
                   stdin=subprocess.DEVNULL)

    if dest.exists():
        if not (dest / ".git").exists():
            raise ValueError(f"папка {name} уже есть, и это не репозиторий git — переименуйте её или выберите другую")
        r = git("-C", str(dest), "remote", "get-url", "origin")
        if r.returncode != 0 or not _same(r.stdout, full):
            raise ValueError(f"в папке {name} другой репозиторий — {full} туда не клонирую")
        r, act = git("-C", str(dest), "pull", "--ff-only", "-q"), "pull"
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        r, act = git("clone", "-q", "--", clone_url(full), str(dest)), "clone"
    if r.returncode != 0:
        raise RuntimeError(_why(r.stderr or r.stdout, act))
    return str(dest), act


def _why(out: str, act: str) -> str:
    lines = [x.strip() for x in scrub(out).splitlines() if x.strip()]
    last = " ".join(lines[-2:])[:300]
    if "not possible to fast-forward" in out.lower() or "diverg" in out.lower():
        return "pull --ff-only не прошёл: в папке свои изменения или ветки разошлись — разберитесь в сессии"
    if "authentication" in out.lower() or "could not read username" in out.lower() or "not found" in out.lower():
        return "GitHub не пустил: репозиторий закрытый или его нет, а токена с доступом к нему нет"
    return (("клонировать" if act == "clone" else "обновить") + " не вышло: " + last) if last else "не вышло"


# ---------- пространство: всё — от его пользователя, токен читается внутри ----------
# Программа внутри пространства: токен из secrets.json (ключ github) или из интеграции GitHub его Claude Code.
# Режим «token» печатает токен в подстановку оболочки (не в вывод run-shell), «list» — сам ходит в API GitHub.
TOKEN_PY = r"""
import json, sys, urllib.request, urllib.error
def load(p):
    try:
        with open(p) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}
t = str(load(sys.argv[1]).get("github") or "").strip()
if not t:
    for s in (load(sys.argv[2]).get("mcpServers") or {}).values():
        s = s if isinstance(s, dict) else {}
        h = str((s.get("headers") or {}).get("Authorization") or "")
        if "github" in str(s.get("url") or "") and h.lower().startswith("bearer "):
            t = h[7:].strip()
            break
if sys.argv[3] == "token":
    print(t)
    sys.exit(0)
if not t:
    print("GP_NO_TOKEN")
    sys.exit(4)
q = urllib.request.Request("https://api.github.com/user/repos?per_page=100&sort=updated",
                           headers={"Authorization": "Bearer " + t, "Accept": "application/vnd.github+json",
                                    "User-Agent": "gas-pult"})
try:
    with urllib.request.urlopen(q, timeout=25) as r:
        d = json.load(r)
except urllib.error.HTTPError as e:
    print("GP_NO_TOKEN" if e.code in (401, 403) else "GP_HTTP %d" % e.code)
    sys.exit(5)
except Exception as e:
    print("GP_NET " + type(e).__name__)
    sys.exit(6)
print(json.dumps([{"full_name": x.get("full_name"), "private": x.get("private"), "description": x.get("description")}
                  for x in d if isinstance(x, dict)]))
"""


def _token_cmd(slug: str, mode: str) -> str:
    from gas_pult import tenants
    p = tenants.paths(slug)
    q = shlex.quote
    return f"python3 -I -c {q(TOKEN_PY)} {q(str(p['secrets']))} {q(str(p['claude'] / '.claude.json'))} {mode}"


def fetch_script(slug: str, full: str, dest: str) -> str:
    """Сценарий оболочки для пространства. Токена в нём нет — только программа, которая прочтёт его на месте;
    в git он уходит переменной окружения (``http.extraHeader``), не аргументом и не адресом remote."""
    q = shlex.quote
    url, root = clone_url(full), os.path.dirname(dest)
    return (f"T=$({_token_cmd(slug, 'token')}); "
            # без токена — только открытые репозитории
            'if [ -n "$T" ]; then H=$(printf "x-access-token:%s" "$T" | base64 -w0); T=; '
            "export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=http.https://github.com/.extraheader "
            'GIT_CONFIG_VALUE_0="Authorization: Basic $H"; H=; fi; '
            f"export GIT_TERMINAL_PROMPT=0; D={q(dest)}; "
            'if [ -d "$D/.git" ]; then '
            f'o=$(git -C "$D" remote get-url origin 2>/dev/null | tr A-Z a-z); '
            f'case "$o" in *github.com/{q(full.lower())}|*github.com/{q(full.lower())}.git) ;; '
            '*) echo GP_OTHER; exit 5;; esac; '
            'git -C "$D" pull --ff-only -q && echo GP_PULLED; '
            'elif [ -e "$D" ]; then echo GP_BUSY; exit 5; '
            f'else mkdir -p {q(root)} && git clone -q -- {q(url)} "$D" && echo GP_CLONED; fi')


def space_fetch(slug: str, full: str, sh=None) -> tuple[str, str]:
    from gas_pult import space_sessions
    full, name = parse(full)
    dest = str(space_sessions.projects(slug) / name)
    try:
        out = (sh or space_sessions.sh)(slug, fetch_script(slug, full, dest), FETCH_TIMEOUT)
    except RuntimeError as e:
        msg = str(e)
        if "GP_OTHER" in msg:
            raise ValueError(f"в папке {name} другой репозиторий — {full} туда не клонирую") from None
        if "GP_BUSY" in msg:
            raise ValueError(f"папка {name} уже есть, и это не репозиторий git — выберите другой") from None
        low = msg.lower()
        if "authentication" in low or "could not read username" in low or "not found" in low:
            raise NoToken(slug) from None
        raise RuntimeError(_why(msg, "clone")) from None
    return dest, "pull" if "GP_PULLED" in out else "clone"


def space_list(slug: str, sh=None) -> list[dict]:
    from gas_pult import space_sessions
    try:
        out = (sh or space_sessions.sh)(slug, _token_cmd(slug, "list"), LIST_TIMEOUT)
    except RuntimeError as e:
        if NO_TOKEN in str(e):
            raise NoToken(slug) from None
        raise RuntimeError("GitHub не ответил — вставьте ссылку на репозиторий") from None
    line = next((x for x in reversed(out.strip().splitlines()) if x.startswith("[")), "")
    try:
        return _rows(json.loads(line))
    except ValueError:
        raise RuntimeError("GitHub ответил непонятно — вставьте ссылку на репозиторий") from None
