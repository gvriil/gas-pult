"""Анкета клиента по ссылке (решение 0010; владелец 19.11: «не колхоз — мы цифровая компания: опросник клиенту —
HTML-анкета на нашей ссылке, с отметками… с подсказками и пониманием; прошёл — мы данные собрали и взяли в работу,
никаких разговоров»).

Пульт — верхний уровень: инструктаж → анкета → чат → **описание клиента**, по которому админка и сканер TGI
показывают клиенту только нужное (код один, различаются настройки). Этот модуль:

- **анкеты** — файлы JSON: пример в пакете (``forms/``), анкеты клиентов — в данных пульта (``<данные>/forms/``, в git
  не попадают). Формат: ``id``, ``title``, ``intro``, ``rules``, ``sections`` [``id``, ``title``, ``questions``
  [``id``, ``text``, ``type`` choice|number|text|photo, ``multi``, ``other``, ``options``, ``hint`` — «зачем
  спрашиваем», ``setting`` — «→ настройка» (человеку не показываем), ``key`` — путь в описании клиента,
  ``required``, ``placeholder``, ``unit``]], ``finish``, ``glossary`` — необязательный словарь
  ``{"термин": "пояснение"}`` (TGI 23.11: на странице термин подчёркнут, нажатие — пояснение в 1–2 предложения;
  термин — до 60 знаков, пояснение — до 300, терминов — до 100; ищется в ``intro``, ``rules``, ``text``, ``hint`` и
  ``options`` целым словом, без учёта регистра и разницы «е»/«ё», длинные — раньше коротких);
- **ссылки** ``/q/<код>`` — личные, со сроком, без входа (как приглашения): хранится только хеш кода; черновик
  ответов — на сервере, вернулся — продолжил; после «Отправить» ссылка только показывает «Спасибо»;
- **ответы** — файл 0600 и **описание клиента** (JSON по ``key``) в ``<данные>/clients/``; владельцу — сообщение в бот
  с кратким итогом. LLM здесь нет: ответы — отметки, разбор — правилами (решение 0009).
"""

from __future__ import annotations

import hashlib
import html
import json
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
TEXT_MAX = 2000
OTHER_MAX = 300
ALIAS = re.compile(r"^[a-z0-9][a-z0-9-]{1,14}$")   # короткое имя ссылки: /q/med (адрес для людей, 23.11)
# Бренд страницы анкеты (владелец 23.11: анкета клиента Botsmith — без «Гаврилы» и pult). gavrila — страница как была.
BOTSMITH_MARK = ('<svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true">'
                 '<rect width="32" height="32" rx="7" fill="#3a6b0b"/>'
                 '<path d="M10 9v14h7a4 4 0 0 0 0-8h-7m7 0a3.5 3.5 0 0 0 0-6h-7" fill="none" '
                 'stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>')
BRANDS = {
    "gavrila": None,
    "botsmith": {"name": "Botsmith", "site": "botsmith.ru", "accent": "#3a6b0b", "accent_dark": "#9ccc65",
                 "soft": "#eef5e6", "soft_dark": "#22301a", "mark": BOTSMITH_MARK,
                 "icon": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect "
                         "width='32' height='32' rx='7' fill='%233a6b0b'/%3E%3Cpath d='M10 9v14h7a4 4 0 0 0 0-8h-7m7 "
                         "0a3.5 3.5 0 0 0 0-6h-7' fill='none' stroke='%23fff' stroke-width='2.6' "
                         "stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E"},
}
GLOSS_MAX, TERM_MAX, NOTE_MAX = 100, 60, 300      # glossary: терминов, знаков в термине, знаков в пояснении


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
    if form.get("brand", "gavrila") not in BRANDS:
        errs.append(f"brand — один из {', '.join(BRANDS)}")
    return errs + _check_glossary(form.get("glossary"))


def brand_of(form: dict, rec: dict | None = None) -> str:
    """Бренд страницы: у ссылки (``rec["brand"]``) важнее, чем у анкеты (``form["brand"]``); по умолчанию gavrila."""
    b = (rec or {}).get("brand") or (form or {}).get("brand") or "gavrila"
    return b if b in BRANDS else "gavrila"


def page(raw: bytes, form: dict, rec: dict | None = None) -> bytes:
    """Страница анкеты в бренде ссылки: заголовок, og:title, значок, шапка и подвал. Скрипты те же (CSP по хешам)."""
    b = BRANDS[brand_of(form, rec)]
    if not b:
        return raw
    t = html.escape(f"{form.get('title') or 'Анкета'} — {b['name']}")
    head = (f'<title>{t}</title>\n<meta property="og:title" content="{t}">\n'
            f'<meta property="og:site_name" content="{b["name"]}">\n<link rel="icon" href="{b["icon"]}">')
    css = (f"<style>:root{{--accent:{b['accent']};--accent-soft:{b['soft']}}}"
           "@media (prefers-color-scheme: dark){:root{"
           f"--accent:{b['accent_dark']};--accent-soft:{b['soft_dark']}}}}}"
           ".brandbar{display:flex;align-items:center;gap:10px;max-width:680px;margin:0 auto;padding:14px 16px 0;"
           "font-weight:700;font-size:18px;letter-spacing:-.01em}.brandbar svg{flex:none;border-radius:7px}"
           ".brandfoot{max-width:680px;margin:0 auto;padding:0 16px calc(24px + env(safe-area-inset-bottom));"
           "color:var(--muted);font-size:14px}.brandfoot a{color:inherit}</style>")
    bar = f'<header class="brandbar">{b["mark"]}<span>{b["name"]}</span></header>'
    foot = f'<footer class="brandfoot">{b["name"]} · <a href="https://{b["site"]}/">{b["site"]}</a></footer>'
    out = raw.decode("utf-8").replace("<title>Анкета</title>", head, 1).replace("</head>", css + "\n</head>", 1)
    out = out.replace("<body>", "<body>\n" + bar, 1)
    return out.replace("</body>", foot + "\n</body>", 1).encode("utf-8")


def _check_glossary(g) -> list[str]:
    """glossary — необязательный ``{"термин": "пояснение"}``: только строки, без повторов (регистр не важен)."""
    if g is None:
        return []
    if not isinstance(g, dict):
        return ['glossary — словарь вида {"термин": "пояснение"}']
    errs, seen = [], set()
    if len(g) > GLOSS_MAX:
        errs.append(f"glossary: терминов {len(g)}, можно не больше {GLOSS_MAX}")
    for t, d in g.items():
        name = str(t).strip()
        if not isinstance(t, str) or not 1 <= len(name) <= TERM_MAX:
            errs.append(f"glossary: термин «{name[:TERM_MAX]}…» — от 1 до {TERM_MAX} знаков" if name else
                        "glossary: пустой термин")
            continue
        low = name.lower().replace("ё", "е")
        if low in seen:
            errs.append(f"glossary: термин «{name}» повторяется (регистр и «ё» не различаются)")
        seen.add(low)
        if not isinstance(d, str) or not d.strip():
            errs.append(f"glossary: у термина «{name}» нет пояснения — нужен текст")
        elif len(d.strip()) > NOTE_MAX:
            errs.append(f"glossary: пояснение к «{name}» — {len(d.strip())} знаков, можно до {NOTE_MAX}")
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
            "finish": form.get("finish", ""), **({"glossary": form["glossary"]} if form.get("glossary") else {}),
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

    @staticmethod
    def _key(d: dict, code: str) -> str | None:
        """Ключ записи: личный код (хеш) или короткое имя ссылки (``alias``)."""
        code = str(code or "")
        if CODE.match(code):
            return _h(code)
        if ALIAS.match(code):
            return next((k for k, v in d.items() if v.get("alias") == code), None)
        return None

    def get(self, code: str) -> dict | None:
        d = self._load()
        rec = d.get(self._key(d, code) or "")
        if not rec or (not rec.get("sent") and time.time() > rec["exp"]):
            return None
        return rec

    def draft(self, code: str, answers: dict) -> dict:
        with self.lock:
            d = self._load()
            rec = d.get(self._key(d, code) or "")
            if not rec or rec.get("sent"):
                raise ValueError("анкета уже отправлена или ссылка устарела")
            rec["draft"], rec["saved"] = answers, int(time.time())
            self._save(d)
        return rec

    def submit(self, code: str, answers: dict) -> dict:
        with self.lock:
            d = self._load()
            rec = d.get(self._key(d, code) or "")
            if not rec or rec.get("sent"):
                raise ValueError("анкета уже отправлена или ссылка устарела")
            rec["draft"], rec["sent"] = answers, int(time.time())
            self._save(d)
        return rec

    def style(self, rid: str, alias: str | None = None, brand: str | None = None) -> dict:
        """Владельцу: короткое имя ссылки (``/q/<alias>``; пусто — убрать) и бренд страницы. Имя — уникальное."""
        with self.lock:
            d = self._load()
            rec = next((r for r in d.values() if r["id"] == rid), None)
            if not rec:
                raise LookupError("нет такой ссылки")
            if alias is not None:
                if alias and not ALIAS.match(alias):
                    raise ValueError("короткое имя — 2–15 знаков: латиница, цифры, «-»")
                if alias in ("new", "list", "answers"):
                    raise ValueError(f"имя «{alias}» занято панелью")
                if alias and any(r.get("alias") == alias and r is not rec for r in d.values()):
                    raise ValueError(f"имя «{alias}» уже занято")
                rec["alias"] = alias or None
            if brand is not None:
                if brand not in BRANDS:
                    raise ValueError(f"бренд — один из {', '.join(BRANDS)}")
                rec["brand"] = brand
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
