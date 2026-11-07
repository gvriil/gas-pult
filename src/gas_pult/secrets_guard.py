"""Секреты — не к модели (задача 44): ключи, токены и пароли заменяются «[скрыт: тип]» до того, как их увидит модель.

Работает хуками Claude Code (команда из ``settings.json`` папки Claude — ``CLAUDE_CONFIG_DIR``):

- ``UserPromptSubmit`` — в сообщении человека секрет: сообщение **не отправляется** (Claude Code 2.1 не даёт хуку
  заменить текст сообщения — только остановить его), человек видит «Убрал ключ …: положите его в «Интеграции» и
  отправьте сообщение без ключа». ``suppressOriginalPrompt`` — текст с ключом не попадает в запись разговора.
- ``PreToolUse`` — чтение ``.env*`` (Read, Grep, команды Bash) закрыто; ``.env.example`` (и ``.sample``, ``.template``)
  — открыт.
- ``PostToolUse`` — в выводе любого инструмента секреты и значения из ``.env*`` текущей папки заменяются заглушкой
  (``updatedToolOutput``: та же форма ответа, строки — без секретов).

Файл самодостаточный — только стандартная библиотека и ни одного импорта из ``gas_pult``: ``install`` копирует его в
``<папка Claude>/hooks/`` (пространства не видят домашнюю папку владельца — ``ProtectHome``). Значение секрета хук
никуда не пишет: ни в вывод, ни в журнал — только тип.

Правила (``RULES``) общие с панелью: ``index.html`` держит их копию в ``<script id="secretRules">`` и проверяет поле
ввода до отправки; тест сверяет, что копия та же. Регулярные выражения — в общем подмножестве Python и JavaScript:
без именованных групп и флагов внутри выражения. ``g`` — 0: секрет — всё совпадение; 2: группы (начало)(секрет)(конец).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sys
import time
from pathlib import Path

SCRIPT = "gas-pult-secrets.py"           # имя копии в <папка Claude>/hooks/
TAG = "gas-pult-secrets"                 # по нему install узнаёт свои записи в settings.json
EVENTS = {"UserPromptSubmit": None, "PreToolUse": "Read|Grep|Bash|NotebookRead", "PostToolUse": "*"}
KEYS_PLACE = "«Интеграции» панели пульта"
ALLOWED_ENV = (".env.example", ".env.sample", ".env.template", ".env.dist")

# Имя переменной с секретом: …_KEY, …TOKEN, …SECRET, …PASSWORD (и PASSWD, PWD, PASS, CREDENTIALS), apikey.
_NAME = (r"[A-Za-z0-9_.\-]*(?:[_.\-](?:key|pass|pwd|credentials?)|apikey|token|secret|password|passwd)"
         r"[0-9]*")
# Не секрет: заглушки и переменные — ${X}, $X, <…>, […], ***, your-…, xxx, changeme, example, true/false, число.
_NOT_VALUE = (r"(?!\$|<|\[|\*{3}|%|\{|your[_\-]|xxx|changeme|change[_\-]me|example|placeholder|dummy|redacted|"
              r"none(?![A-Za-z0-9_])|null(?![A-Za-z0-9_])|true(?![A-Za-z0-9_])|false(?![A-Za-z0-9_])|"
              r"[0-9]+(?![^\s\"'`,;]))")

RULES = [
    {"id": "pem", "label": "приватный ключ", "g": 0, "flags": "",
     "re": r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----[\s\S]*?(?:-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----|$)"},
    {"id": "anthropic", "label": "ключ Anthropic", "g": 0, "flags": "",
     "re": r"(?<![A-Za-z0-9_\-])sk-ant-[A-Za-z0-9_\-]{20,}"},
    {"id": "openrouter", "label": "ключ OpenRouter", "g": 0, "flags": "",
     "re": r"(?<![A-Za-z0-9_\-])sk-or-(?:v1-)?[A-Za-z0-9]{32,}"},
    {"id": "openai", "label": "ключ OpenAI", "g": 0, "flags": "",
     "re": r"(?<![A-Za-z0-9_\-])sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}"},
    {"id": "github", "label": "токен GitHub", "g": 0, "flags": "",
     "re": r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"},
    {"id": "gitlab", "label": "токен GitLab", "g": 0, "flags": "",
     "re": r"(?<![A-Za-z0-9_\-])gl(?:pat|dt|rt|cbt|ptt|ft|imt|agent|oas)-[A-Za-z0-9_\-]{20,}"},
    {"id": "telegram", "label": "токен Telegram-бота", "g": 0, "flags": "",
     "re": r"(?<![A-Za-z0-9_])[0-9]{6,12}:AA[A-Za-z0-9_\-]{30,}"},
    {"id": "aws", "label": "ключ AWS", "g": 0, "flags": "",
     "re": r"(?<![A-Za-z0-9])(?:AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}(?![A-Za-z0-9])"},
    {"id": "google", "label": "ключ Google", "g": 0, "flags": "",
     "re": r"(?<![A-Za-z0-9_\-])(?:AIza[A-Za-z0-9_\-]{35}|GOCSPX-[A-Za-z0-9_\-]{20,})"},
    {"id": "slack", "label": "токен Slack", "g": 0, "flags": "",
     "re": r"(?<![A-Za-z0-9_\-])(?:xox[abposre]-[A-Za-z0-9\-]{10,}|https://hooks\.slack\.com/services/[A-Za-z0-9/_\-]+)"},
    {"id": "stripe", "label": "ключ Stripe", "g": 0, "flags": "",
     "re": r"(?<![A-Za-z0-9_])(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"},
    {"id": "jwt", "label": "токен JWT", "g": 0, "flags": "",
     "re": r"(?<![A-Za-z0-9_\-])eyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"},
    {"id": "url", "label": "пароль в адресе", "g": 2, "flags": "i",
     "re": r"([a-z][a-z0-9+.\-]*://[^\s:/@'\"`]+:)([^\s@/'\"`]+)(@)"},
    {"id": "bearer", "label": "токен в заголовке", "g": 2, "flags": "i",
     "re": r"((?:authorization|bearer|token)[\"']?\s*[:=]?\s*[\"']?(?:bearer|token|basic)\s+)"
           r"([A-Za-z0-9._~+/\-]{16,}=*)()"},
    {"id": "assign_q", "label": "значение секретной переменной", "g": 2, "flags": "i",
     "re": r"((?:^|[^A-Za-z0-9_.\-])" + _NAME + r"[\"']?\s*(?::=|=>|=|:)\s*[\"'])" + _NOT_VALUE
           + r"([^\s\"'`]{6,})([\"'])"},
    {"id": "assign", "label": "значение секретной переменной", "g": 2, "flags": "i",
     "re": r"((?:^|[^A-Za-z0-9_.\-])" + _NAME + r"\s*(?::=|=|:)[ \t]*)" + _NOT_VALUE
           + r"(?![A-Za-z_.\-]+(?![^\s,;]))([^\s\"'`,;()\[\]{}<>]{6,})(?![^\s,;])()"},
]
_COMPILED = [(r, re.compile(r["re"], re.I if "i" in r["flags"] else 0)) for r in RULES]


def mask(label: str) -> str:
    return f"[скрыт: {label}]"


def redact(text: str, env_values=()) -> tuple[str, list[str]]:
    """Текст без секретов и список найденных типов (без повторов, в порядке правил). Значения нигде не остаются."""
    if not isinstance(text, str) or not text:
        return text, []
    found: list[str] = []
    for rule, rx in _COMPILED:
        if rule["g"]:
            new = rx.sub(lambda m, lb=rule["label"]: m.group(1) + mask(lb) + (m.group(3) or ""), text)
        else:
            new = rx.sub(mask(rule["label"]), text)
        if new != text:
            if rule["label"] not in found:
                found.append(rule["label"])
            text = new
    hit = False
    for v in sorted(set(env_values), key=len, reverse=True):
        rx = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(v) + r"(?![A-Za-z0-9_])")
        new = rx.sub(mask("значение из .env"), text)
        if new != text:
            hit, text = True, new
    if hit:
        found.append("значение из .env")
    return text, found


def find(text: str, env_values=()) -> list[str]:
    return redact(text, env_values)[1]


# ---------- файлы .env ----------
def is_env_file(name: str) -> bool:
    """Закрытый файл: имя начинается с «.env» (``.env``, ``.env.local``, ``.envrc``), кроме шаблонов."""
    n = os.path.basename(str(name).rstrip("/")).lower()
    return n.startswith(".env") and n not in ALLOWED_ENV


_SECRET_NAME = re.compile(r"(?:^|_)(?:key|token|secret|password|passwd|pwd|pass|salt|credentials?)$|apikey$|secret",
                          re.I)
_PLAIN = re.compile(r"^(?:true|false|yes|no|on|off|none|null|localhost|[0-9.:]+|/.*|\./.*|~/.*)$", re.I)


def env_pairs(text: str):
    for line in text.lstrip("\ufeff").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, eq, val = line.partition("=")
        if not eq:
            continue
        val = val.strip()
        quoted = len(val) >= 2 and val[0] == val[-1] and val[0] in "'\""
        val = val[1:-1] if quoted else re.sub(r"\s+#.*$", "", val)
        yield name.strip(), val


def env_values(cwd) -> list[str]:
    """Значения из файлов ``.env*`` папки (кроме шаблонов), которые стоит прятать: у переменной с «секретным»
    именем — любое от 6 знаков, у остальных — только похожее на сгенерированный ключ (16+ знаков, буквы и цифры)."""
    out, templates = set(), set()
    try:
        names = os.listdir(cwd or ".")
    except OSError:
        return []
    for n in names:
        if not n.lower().startswith(".env"):
            continue
        p = os.path.join(cwd, n)
        try:
            if not os.path.isfile(p) or os.path.getsize(p) > 256 * 1024:
                continue
            with open(p, encoding="utf-8", errors="replace") as f:
                pairs = list(env_pairs(f.read()))
        except OSError:
            continue
        if n.lower() in ALLOWED_ENV:
            templates.update(v for _, v in pairs)
            continue
        for k, v in pairs:
            if len(v) < 6 or _PLAIN.match(v):
                continue
            generated = len(v) >= 16 and re.search(r"[A-Za-z]", v) and re.search(r"[0-9]", v) and " " not in v
            if _SECRET_NAME.search(k) or generated:
                out.add(v)
    return sorted(out - templates)


_ENV_TOKEN = re.compile(r"(?:^|[\s/'\"=<:])(\.env[A-Za-z0-9_.\-]*)(?=$|[\s'\";|&>)])", re.I)


def env_in_command(cmd: str) -> str | None:
    """Имя закрытого файла .env, если команда Bash его касается (``ls`` — можно: видно только имена)."""
    if re.match(r"\s*ls(?:\s|$)", cmd or "") and not re.search(r"[;&|`$]", cmd):
        return None
    for m in _ENV_TOKEN.finditer(cmd or ""):
        if is_env_file(m.group(1)):
            return m.group(1)
    return None


def env_target(tool: str, inp: dict) -> str | None:
    """Какой закрытый файл .env пытается прочитать инструмент (или None)."""
    inp = inp if isinstance(inp, dict) else {}
    if tool in ("Read", "NotebookRead"):
        p = inp.get("file_path") or inp.get("notebook_path") or ""
        return os.path.basename(p) if p and is_env_file(p) else None
    if tool == "Grep":
        for k in ("path", "glob"):
            v = str(inp.get(k) or "")
            if v and is_env_file(v.replace("*", "x")) and not v.lower().endswith(ALLOWED_ENV):
                return os.path.basename(v)
        return None
    if tool == "Bash":
        return env_in_command(str(inp.get("command") or ""))
    return None


# ---------- хук ----------
def scrub(obj, env):
    """Та же форма, строки — без секретов. Возвращает (новое, типы)."""
    found: list[str] = []
    if isinstance(obj, str):
        return redact(obj, env)
    if isinstance(obj, list):
        out = []
        for x in obj:
            y, t = scrub(x, env)
            out.append(y)
            found += t
        return out, found
    if isinstance(obj, dict):
        out = {}
        for k, x in obj.items():
            y, t = scrub(x, env)
            out[k] = y
            found += t
        return out, found
    return obj, found


def _uniq(xs):
    return list(dict.fromkeys(xs))


def prompt_reason(types) -> str:
    return (f"Убрал ключ: в сообщении {', '.join(types)}. Сообщение не отправлено — модель ключа не видела. "
            f"Положите ключ в {KEYS_PLACE}: там он хранится на сервере и модели не показывается. Отправьте "
            "сообщение ещё раз без ключа.")


def handle(data: dict) -> dict | None:
    """Ответ хука на событие Claude Code (JSON со стандартного ввода) — или None: ничего не менять."""
    ev = data.get("hook_event_name")
    cwd = data.get("cwd") or os.getcwd()
    if ev == "UserPromptSubmit":
        types = find(str(data.get("prompt") or ""), env_values(cwd))
        if not types:
            return None
        return {"decision": "block", "reason": prompt_reason(types),
                "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "suppressOriginalPrompt": True}}
    if ev == "PreToolUse":
        name = env_target(str(data.get("tool_name") or ""), data.get("tool_input") or {})
        if not name:
            return None
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": (f"Файл {name} закрыт: в нём секреты (защита пульта). Список переменных — в "
                                         ".env.example; значение спросите у человека, а сам ключ он положит в "
                                         f"{KEYS_PLACE}. Если команда нужна (например, скопировать шаблон в .env), "
                                         "попросите человека выполнить её самому.")}}
    if ev == "PostToolUse":
        resp = data.get("tool_response")
        new, types = scrub(resp, env_values(cwd))
        if not types:
            return None
        types = _uniq(types)
        return {"hookSpecificOutput": {
            "hookEventName": "PostToolUse", "updatedToolOutput": new,
            "additionalContext": (f"В выводе инструмента скрыто: {', '.join(types)} (защита пульта). Значения не "
                                  "нужны: ссылайтесь на имя переменной, сам ключ человек кладёт в "
                                  f"{KEYS_PLACE}.")}}
    return None


def hook_main(stdin=None, stdout=None) -> int:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    try:
        data = json.loads(stdin.read() or "{}")
    except ValueError:
        print("gas-pult-secrets: на входе не JSON", file=sys.stderr)
        return 0
    try:
        out = handle(data if isinstance(data, dict) else {})
    except Exception as e:                              # хук не должен ломать сессию; значение в ошибку не попадает
        print(f"gas-pult-secrets: ошибка {type(e).__name__}", file=sys.stderr)
        return 0
    if out:
        stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


# ---------- установка в папку Claude ----------
def _ours(group: dict) -> bool:
    return any(TAG in str(h.get("command", "")) for h in group.get("hooks", []) if isinstance(h, dict))


def wanted_hooks(script: Path, python: str) -> dict:
    cmd = f"{shlex.quote(python)} {shlex.quote(str(script))} hook"
    out = {}
    for ev, matcher in EVENTS.items():
        g = {"hooks": [{"type": "command", "command": cmd, "timeout": 20}]}
        if matcher:
            g = {"matcher": matcher, **g}
        out[ev] = [g]
    return out


def merge(settings: dict, hooks: dict | None) -> dict:
    """settings.json с нашими хуками (или без них, если ``hooks`` None); чужие записи — как были."""
    s = json.loads(json.dumps(settings))
    cur = s.get("hooks") if isinstance(s.get("hooks"), dict) else {}
    for ev in set(cur) | set(hooks or {}):
        groups = [g for g in (cur.get(ev) or []) if not (isinstance(g, dict) and _ours(g))]
        groups += (hooks or {}).get(ev, [])
        if groups:
            cur[ev] = groups
        else:
            cur.pop(ev, None)
    if cur:
        s["hooks"] = cur
    else:
        s.pop("hooks", None)
    return s


def _write(path: Path, text: str, mode: int):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def install(config_dir, python: str | None = None, remove: bool = False, out=print) -> dict:
    """Поставить (или убрать) хуки в ``<config_dir>/settings.json``; скрипт — копией в ``<config_dir>/hooks/``.

    Идемпотентно: второй запуск ничего не меняет. Перед правкой settings.json — бэкап рядом
    (``settings.json.bak-<время>``). Чужие хуки и настройки сохраняются. Возвращает {changed, backup, script}."""
    d = Path(config_dir).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    script = d / "hooks" / SCRIPT
    sfile = d / "settings.json"
    try:
        raw = sfile.read_text(encoding="utf-8")
        settings = json.loads(raw) if raw.strip() else {}
    except FileNotFoundError:
        raw, settings = "", {}
    if not isinstance(settings, dict):
        raise ValueError(f"{sfile}: не объект JSON — не трогаю")
    res = {"changed": False, "backup": None, "script": str(script)}
    if remove:
        new = merge(settings, None)
        if script.exists():
            script.unlink()
            res["changed"] = True
    else:
        script.parent.mkdir(exist_ok=True)
        body = Path(__file__).read_text(encoding="utf-8")
        if not script.exists() or script.read_text(encoding="utf-8") != body:
            _write(script, body, 0o644)
            res["changed"] = True
        new = merge(settings, wanted_hooks(script, python or sys.executable))
    if new != settings:
        if raw:
            bak = sfile.with_name(f"settings.json.bak-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(sfile, bak)
            res["backup"] = str(bak)
        _write(sfile, json.dumps(new, ensure_ascii=False, indent=2) + "\n", 0o600 if not raw else
               (sfile.stat().st_mode & 0o777))
        res["changed"] = True
    if out:
        what = "убраны" if remove else "на месте"
        out(f"Скрытие секретов {what}: {sfile}" + (f" (бэкап {res['backup']})" if res["backup"] else "")
            + ("" if res["changed"] else " — без изменений"))
    return res


def installed(config_dir) -> bool:
    """Стоят ли наши хуки в ``<config_dir>/settings.json`` и есть ли скрипт."""
    d = Path(config_dir).expanduser()
    try:
        s = json.loads((d / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    hooks = s.get("hooks") if isinstance(s, dict) else None
    ok = isinstance(hooks, dict) and all(any(isinstance(g, dict) and _ours(g) for g in hooks.get(ev) or [])
                                         for ev in EVENTS)
    return ok and (d / "hooks" / SCRIPT).is_file()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["hook"]:
        return hook_main()
    if argv[:1] == ["check"]:                           # проверить текст со стандартного ввода: только типы
        types = find(sys.stdin.read(), env_values(os.getcwd()))
        print(", ".join(types) if types else "секретов не найдено")
        return 1 if types else 0
    print("gas-pult-secrets: hook | check  (установка — gas-pult secrets install)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
