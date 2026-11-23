"""Анкета клиента по ссылке (решение 0010; владелец 19.11: «не колхоз — мы цифровая компания: опросник клиенту —
HTML-анкета на нашей ссылке, с отметками… с подсказками и пониманием; прошёл — мы данные собрали и взяли в работу,
никаких разговоров»).

Пульт — верхний уровень: инструктаж → анкета → чат → **описание клиента**, по которому админка и сканер TGI
показывают клиенту только нужное (код один, различаются настройки). Этот модуль:

- **анкеты** — файлы JSON: пример в пакете (``forms/``), анкеты клиентов — в данных пульта (``<данные>/forms/``, в git
  не попадают). Формат: ``id``, ``title``, ``intro``, ``rules``, ``sections`` [``id``, ``title``, ``questions``
  [``id``, ``text``, ``type`` choice|number|text|photo, ``multi``, ``other``, ``options``, ``hint`` — «зачем
  спрашиваем», ``setting`` — «→ настройка» (человеку не показываем), ``key`` — путь в описании клиента,
  ``required``, ``placeholder``, ``unit``]], ``finish``;
- **ссылки** ``/q/<код>`` — личные, со сроком, без входа (как приглашения): хранится только хеш кода; черновик
  ответов — на сервере, вернулся — продолжил; после «Отправить» ссылка только показывает «Спасибо»;
- **ответы** — файл 0600 и **описание клиента** (JSON по ``key``) в ``<данные>/clients/``; владельцу — сообщение в бот
  с кратким итогом. LLM здесь нет: ответы — отметки, разбор — правилами (решение 0009).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
from importlib import resources
from pathlib import Path

from gas_pult.config import write_private

TYPES = ("choice", "number", "text", "photo")
CODE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,60}$")
DAYS = 14
TEST_MARK = re.compile(r"тест|test", re.I)
LIVE_REFUSED = ("боевая анкета клиента: проверяйте только на своей ссылке с «ТЕСТ» в имени клиента "
                "(onboarding.Links(...).new(форма, \"ТЕСТ …\"))")


def is_test(rec: dict) -> bool:
    """Тестовая ссылка — «ТЕСТ»/«test» в имени клиента (штаб 23.11: боевую анкету клиента заполнили проверкой)."""
    return bool(TEST_MARK.search(str((rec or {}).get("client") or "")))


def live_data(data: Path) -> bool:
    """Данные — боевые (``~/.local/share/gas-pult``), а не временная папка теста или демо."""
    try:
        return Path(data).resolve() == (Path.home() / ".local" / "share" / "gas-pult").resolve()
    except OSError:
        return False


def guard(data: Path, rec: dict, robot: bool):
    """Агент или e2e (``robot``) пишет в боевые данные — только в тестовую ссылку; иначе ``PermissionError``."""
    if robot and live_data(data) and not is_test(rec):
        raise PermissionError(LIVE_REFUSED)


def agent_env() -> bool:
    """Процесс запущен из сессии агента (Claude Code ставит ``CLAUDECODE=1``) или e2e (``GAS_PULT_E2E=1``)."""
    return os.environ.get("CLAUDECODE") == "1" or os.environ.get("GAS_PULT_E2E") == "1"
TEXT_MAX = 2000
OTHER_MAX = 300


def _h(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


# ---------- анкеты ----------
def check(form: dict) -> list[str]:
    """Ошибки формата анкеты (пусто — годится): уникальные id, типы, варианты у choice."""
    errs, seen = [], set()
    if not ID.match(str(form.get("id", ""))):
        errs.append("id анкеты — латиница, цифры, «-», «_», «.»")
    if not form.get("title"):
        errs.append("нет title")
    secs = form.get("sections")
    if not isinstance(secs, list) or not secs:
        return [*errs, "нет sections"]
    for s in secs:
        for q in s.get("questions") or []:
            qid = str(q.get("id", ""))
            if not ID.match(qid) or qid in seen:
                errs.append(f"вопрос «{qid}»: id пустой, неверный или повторяется")
            seen.add(qid)
            t = q.get("type", "choice")
            if t not in TYPES:
                errs.append(f"вопрос {qid}: type — один из {', '.join(TYPES)}")
            if t == "choice" and not (isinstance(q.get("options"), list) and q["options"]):
                errs.append(f"вопрос {qid}: у choice нужны options")
            if not q.get("text"):
                errs.append(f"вопрос {qid}: нет text")
    return errs


def forms(data: Path) -> dict[str, dict]:
    """Все годные анкеты: пример из пакета и анкеты клиентов из данных пульта (одинаковый id — берётся из данных)."""
    out: dict[str, dict] = {}
    files = [resources.files("gas_pult").joinpath("forms")]
    for base in files:
        for f in sorted(x for x in base.iterdir() if x.name.endswith(".json")):
            _add(out, f.read_text(encoding="utf-8"))
    d = Path(data) / "forms"
    if d.is_dir():
        for f in sorted(d.glob("*.json")):
            _add(out, f.read_text(encoding="utf-8"))
    return out


def _add(out: dict, text: str):
    try:
        form = json.loads(text)
    except ValueError:
        return
    if isinstance(form, dict) and not check(form):
        out[form["id"]] = form


def public(form: dict) -> dict:
    """Анкета для страницы: без «→ настройка» и служебных полей."""
    keep_q = ("id", "text", "type", "multi", "other", "options", "hint", "required", "placeholder", "unit")
    return {"id": form["id"], "title": form["title"], "intro": form.get("intro", ""), "rules": form.get("rules", []),
            "finish": form.get("finish", ""),
            "sections": [{"id": s.get("id", ""), "title": s.get("title", ""),
                          "questions": [{k: q[k] for k in keep_q if k in q} for q in s.get("questions") or []]}
                         for s in form["sections"]]}


def questions(form: dict) -> list[dict]:
    return [q for s in form["sections"] for q in s.get("questions") or []]


def clean(form: dict, answers) -> dict:
    """Ответы с клиента → только известные вопросы и допустимые значения: choice — варианты из списка (+ «свой
    вариант», если разрешён), number — число, text — до 2000 знаков. Остальное отбрасывается молча."""
    out: dict = {}
    if not isinstance(answers, dict):
        return out
    for q in questions(form):
        v = answers.get(q["id"])
        if v is None:
            continue
        t = q.get("type", "choice")
        if t == "choice":
            v = v if isinstance(v, dict) else {"pick": v}
            pick = v.get("pick")
            picks = pick if isinstance(pick, list) else [pick] if pick not in (None, "") else []
            picks = [p for p in picks if isinstance(p, str) and p in q["options"]]
            if not q.get("multi"):
                picks = picks[:1]
            other = " ".join(str(v.get("other") or "").split())[:OTHER_MAX] if q.get("other") else ""
            if picks or other:
                out[q["id"]] = {"pick": picks, **({"other": other} if other else {})}
        elif t == "number":
            try:
                n = float(str(v).replace(",", ".").replace(" ", ""))
            except ValueError:
                continue
            out[q["id"]] = int(n) if n.is_integer() else n
        else:
            text = str(v).strip()[:TEXT_MAX]
            if text:
                out[q["id"]] = text
    return out


def missing(form: dict, answers: dict) -> list[str]:
    """Обязательные вопросы без ответа — их тексты."""
    return [q["text"] for q in questions(form) if q.get("required") and q["id"] not in answers]


def profile(form: dict, answers: dict, client: str) -> dict:
    """Описание клиента для админки и сканера: ответ — по ``key`` (путь через точку), рядом — «→ настройка»."""
    out: dict = {"client": client, "form": form["id"], "at": int(time.time()), "settings": {}}
    for q in questions(form):
        if q["id"] not in answers:
            continue
        a = answers[q["id"]]
        val = (a["pick"] + ([a["other"]] if a.get("other") else [])) if isinstance(a, dict) else a
        if isinstance(val, list) and not q.get("multi") and q.get("type", "choice") == "choice":
            val = val[0] if len(val) == 1 else val
        node = out["settings"]
        parts = str(q.get("key") or q["id"]).split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = val
        if q.get("setting"):
            out.setdefault("notes", {})[q["id"]] = q["setting"]
    return out


def summary(form: dict, answers: dict, client: str, limit: int = 8) -> str:
    """Короткий итог для владельца в бот: кто, сколько ответов, первые ответы."""
    qs = questions(form)
    lines = [f"📋 Анкета «{form['title']}» — {client}: ответов {len(answers)} из {len(qs)}."]
    for q in qs:
        if q["id"] not in answers or len(lines) > limit:
            continue
        a = answers[q["id"]]
        text = ", ".join(a["pick"] + ([f"свой: {a['other']}"] if a.get("other") else [])) if isinstance(a, dict) \
            else str(a)
        lines.append(f"• {q['text'][:60]}: {text[:120]}")
    return "\n".join(lines)


# ---------- ссылки ----------
class Links:
    """Личные ссылки анкет: ``<данные>/forms-links.json`` (0600), ключ — хеш кода."""

    def __init__(self, data: Path):
        self.data, self.path, self.lock = Path(data), Path(data) / "forms-links.json", threading.Lock()

    def _load(self) -> dict:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, d: dict):
        write_private(self.path, json.dumps(d, ensure_ascii=False))

    def new(self, form_id: str, client: str, days: int = DAYS) -> dict:
        client = " ".join(str(client or "").split())[:80]
        if not client:
            raise ValueError("укажите, для кого анкета (имя клиента)")
        code, now = secrets.token_urlsafe(18), time.time()
        rid = secrets.token_hex(5)
        with self.lock:
            d = self._load()
            d[_h(code)] = {"id": rid, "form": form_id, "client": client, "created": int(now),
                           "exp": int(now + max(1, min(int(days), 90)) * 86400), "draft": {}, "sent": None}
            self._save(d)
        return {"code": code, "id": rid, "path": f"/q/{code}"}

    def get(self, code: str) -> dict | None:
        if not CODE.match(str(code or "")):
            return None
        rec = self._load().get(_h(code))
        if not rec or (not rec.get("sent") and time.time() > rec["exp"]):
            return None
        return rec

    def draft(self, code: str, answers: dict) -> dict:
        with self.lock:
            d = self._load()
            rec = d.get(_h(code))
            if not rec or rec.get("sent"):
                raise ValueError("анкета уже отправлена или ссылка устарела")
            guard(self.data, rec, agent_env())
            rec["draft"], rec["saved"] = answers, int(time.time())
            self._save(d)
        return rec

    def submit(self, code: str, answers: dict) -> dict:
        with self.lock:
            d = self._load()
            rec = d.get(_h(code))
            if not rec or rec.get("sent"):
                raise ValueError("анкета уже отправлена или ссылка устарела")
            guard(self.data, rec, agent_env())
            rec["draft"], rec["sent"] = answers, int(time.time())
            self._save(d)
        return rec

    def listing(self) -> list[dict]:
        """Для владельца: все ссылки без кодов — кому, какая анкета, срок, отправлена ли."""
        return sorted(({k: v for k, v in r.items() if k != "draft"} | {"answered": len(r.get("draft") or {})}
                       for r in self._load().values()), key=lambda r: -r["created"])

    def by_id(self, rid: str) -> dict | None:
        return next((r for r in self._load().values() if r["id"] == rid), None)


def store_answers(data: Path, form: dict, rec: dict, answers: dict) -> tuple[Path, Path]:
    """Ответы — ``<данные>/forms-answers/<id>.json``; описание клиента — ``<данные>/clients/<id>.json``; оба 0600."""
    a = Path(data) / "forms-answers" / f"{rec['id']}.json"
    p = Path(data) / "clients" / f"{rec['id']}.json"
    for d in (a.parent, p.parent):
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_private(a, json.dumps({"form": form["id"], "client": rec["client"], "at": rec["sent"], "answers": answers},
                                ensure_ascii=False, indent=1))
    write_private(p, json.dumps(profile(form, answers, rec["client"]), ensure_ascii=False, indent=1))
    return a, p
