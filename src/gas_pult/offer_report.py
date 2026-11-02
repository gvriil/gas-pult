"""«Загрузите выгрузку — получите отчёт за 2 минуты»: сводка по CSV/XLSX без модели (страница предложения).

Три вида выгрузки: **продажи** (дата, сумма, точка, позиция), **клиенты** (кто, когда был последний раз, сколько
визитов — или журнал визитов) и **должники** (кто, сколько, срок оплаты или дни просрочки). Вид и столбцы угадываются
по заголовкам (``guess``), человек может выбрать их вручную (``kind``, ``mapping``).

Всё — в памяти и только стандартной библиотекой: файл не пишется на диск, модель не вызывается. На выходе — агрегаты
и маскированные строки (``mask``: «Иван П.»); телефоны, ИНН и почта не попадают в отчёт никогда.

XLSX читается ``zipfile`` + ``xml.etree`` с защитой: лимит числа файлов архива и распакованного размера (zip-бомба),
DOCTYPE/ENTITY запрещены (внешние сущности и «миллиард смехов»), берётся только первый лист.
"""

from __future__ import annotations

import csv
import io
import re
import time
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from xml.etree import ElementTree as ET

MAX_BYTES = 5 << 20                 # загрузка — до 5 МБ
MAX_ROWS = 50_000
MAX_COLS = 60
MAX_CELL = 300
XLSX_MAX_FILES = 300                # файлов в архиве XLSX
XLSX_MAX_MEMBER = 25 << 20          # один файл архива после распаковки
XLSX_MAX_TOTAL = 60 << 20           # весь архив после распаковки

KINDS = {"sales": "Продажи", "clients": "Клиенты", "debtors": "Должники"}
ROLE_TITLES = {
    "date": "Дата", "amount": "Сумма", "point": "Точка / филиал", "item": "Позиция / услуга", "qty": "Количество",
    "client": "Клиент", "last_visit": "Последний визит", "visits": "Число визитов", "debt": "Долг / остаток",
    "paid": "Оплачено", "due": "Срок оплаты", "overdue": "Дней просрочки",
}
# Какие столбцы нужны виду: (обязательные — хотя бы один из каждой группы, необязательные)
NEEDS = {
    "sales": ([("amount",)], ["date", "point", "item", "qty"]),
    "clients": ([("client",), ("last_visit", "date")], ["visits", "amount", "point"]),
    "debtors": ([("client",), ("debt", "amount")], ["paid", "due", "overdue", "date"]),
}
# Персональные и лишние столбцы: угадываются, чтобы не принять их за имя или сумму, но в отчёт не идут никогда.
PRIVATE = ("phone", "inn", "email")

# Роль → шаблоны заголовка по приоритету. Порядок ролей важен: «дата последнего визита» — last_visit, а не date.
PATTERNS: list[tuple[str, list[str]]] = [
    ("phone", [r"телеф", r"phone", r"^тел\b", r"моб"]),
    ("inn", [r"\bинн\b", r"\binn\b", r"\bкпп\b", r"\bогрн"]),
    ("email", [r"mail", r"почт"]),
    ("last_visit", [r"последн", r"last.?visit", r"last.?order", r"last.?purchase"]),
    ("due", [r"срок.*оплат", r"оплатить до", r"due", r"^срок"]),
    ("overdue", [r"просроч", r"overdue", r"дней долга"]),
    ("paid", [r"^оплачено", r"оплачен", r"\bpaid\b"]),
    ("debt", [r"долг", r"задолж", r"к оплате", r"остаток", r"сальдо", r"debt", r"balance"]),
    ("date", [r"^дата", r"\bdate\b", r"^день$", r"^период", r"^время"]),
    ("visits", [r"(кол|числ|колич)\w* (визит|посещ|покуп|заказ)", r"^визит", r"^посещ", r"^покупок", r"visits",
                r"orders"]),
    ("qty", [r"^кол\w* ?во", r"количеств", r"\bqty\b", r"quantity", r"^шт"]),
    ("amount", [r"сумм", r"выручк", r"итог", r"amount", r"total", r"revenue", r"стоимост", r"оборот", r"^цена",
                r"price"]),
    ("point", [r"филиал", r"точк", r"магазин", r"клуб", r"салон", r"branch", r"store", r"локац", r"подразд",
               r"склад", r"площадк", r"объект"]),
    ("item", [r"товар", r"услуг", r"позиц", r"наимен", r"номенкл", r"product", r"item", r"service", r"sku",
              r"артикул", r"^вид"]),
    ("client", [r"фио", r"^имя", r"\bname\b", r"клиент", r"покупател", r"контрагент", r"customer", r"client",
                r"должник", r"плательщ", r"абонент", r"участник", r"ресторан", r"житель"]),
]


class ReportError(ValueError):
    """Понятная ошибка для человека (без содержимого файла)."""


# ---------- чтение ----------
def read_table(data: bytes) -> tuple[list[str], list[list[str]]]:
    """Байты загрузки → (заголовки, строки). Вид файла — по содержимому, не по имени."""
    if not data:
        raise ReportError("Файл пустой.")
    if len(data) > MAX_BYTES:
        raise ReportError(f"Файл больше {MAX_BYTES >> 20} МБ — выгрузите период покороче.")
    if data[:4] == b"PK\x03\x04":
        rows = read_xlsx(data)
    elif data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ReportError("Это старый формат Excel (.xls) — сохраните как .xlsx или CSV.")
    else:
        rows = read_csv(data)
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise ReportError("В файле нет данных.")
    head, body = rows[0], rows[1:]
    if len(body) > MAX_ROWS:
        raise ReportError(f"Больше {MAX_ROWS:,} строк — выгрузите период покороче.".replace(",", " "))
    width = min(MAX_COLS, max(len(r) for r in rows))
    head = [(head[i].strip() if i < len(head) else "") or f"Столбец {i + 1}" for i in range(width)]
    body = [[(r[i].strip()[:MAX_CELL] if i < len(r) else "") for i in range(width)] for r in body]
    if not body:
        raise ReportError("В файле только заголовок — нет строк с данными.")
    return head, body


def _decode(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    if b"\x00" in data[:4096]:
        raise ReportError("Нужен CSV или XLSX — этот файл не похож ни на один из них.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1251", errors="replace")


def read_csv(data: bytes) -> list[list[str]]:
    text = _decode(data)
    sample = text[:8192]
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        first = sample.splitlines()[0] if sample else ""
        delim = max(";,\t|", key=first.count)
    try:
        return [row for row in csv.reader(io.StringIO(text), delimiter=delim)][: MAX_ROWS + 2]
    except csv.Error:
        raise ReportError("Не получилось прочитать CSV — проверьте разделитель и кавычки.") from None


def _ln(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _member(z: zipfile.ZipFile, name: str) -> bytes:
    try:
        with z.open(name) as f:
            b = f.read(XLSX_MAX_MEMBER + 1)
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError, EOFError):
        raise ReportError("Файл XLSX повреждён — откройте его в Excel и сохраните заново.") from None
    if len(b) > XLSX_MAX_MEMBER:
        raise ReportError("Лист XLSX слишком большой после распаковки — выгрузите период покороче.")
    return b


def _xml(b: bytes) -> ET.Element:
    if re.search(rb"<!(DOCTYPE|ENTITY)", b, re.I):
        raise ReportError("Файл XLSX с подозрительной разметкой (DOCTYPE/ENTITY) — не открываю.")
    try:
        return ET.fromstring(b)
    except ET.ParseError:
        raise ReportError("Файл XLSX повреждён — откройте его в Excel и сохраните заново.") from None


def _col(ref: str) -> int:
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def read_xlsx(data: bytes) -> list[list[str]]:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError):
        raise ReportError("Файл XLSX повреждён — откройте его в Excel и сохраните заново.") from None
    infos = z.infolist()
    if len(infos) > XLSX_MAX_FILES:
        raise ReportError("В архиве XLSX слишком много файлов — это не похоже на обычную таблицу.")
    if sum(i.file_size for i in infos) > XLSX_MAX_TOTAL:
        raise ReportError("Файл XLSX слишком большой после распаковки — выгрузите период покороче.")
    names = {i.filename for i in infos}
    if "xl/workbook.xml" not in names:
        raise ReportError("Это архив, но не таблица XLSX.")
    sheet = _first_sheet(z, names)
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        for si in _xml(_member(z, "xl/sharedStrings.xml")):
            if _ln(si.tag) == "si":
                shared.append(_si_text(si))
    root = _xml(_member(z, sheet))
    rows: list[list[str]] = []
    for row in root.iter():
        if _ln(row.tag) != "row":
            continue
        if len(rows) > MAX_ROWS + 1:
            raise ReportError(f"Больше {MAX_ROWS:,} строк — выгрузите период покороче.".replace(",", " "))
        cells: dict[int, str] = {}
        for c in row:
            if _ln(c.tag) != "c":
                continue
            i = _col(c.get("r", "")) if c.get("r") else len(cells)
            if not 0 <= i < MAX_COLS:
                continue
            t, v = c.get("t", ""), None
            for x in c:
                if _ln(x.tag) == "v":
                    v = x.text or ""
                elif _ln(x.tag) == "is":
                    v = "".join(y.text or "" for y in x.iter() if _ln(y.tag) == "t")
            if v is None:
                continue
            if t == "s":
                try:
                    v = shared[int(v)]
                except (ValueError, IndexError):
                    v = ""
            elif t == "b":
                v = "да" if v == "1" else "нет"
            cells[i] = v
        rows.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
    return rows


def _si_text(si: ET.Element) -> str:
    """Текст общей строки: <t> или куски <r><t>; подсказки чтения (<rPh>) пропускаем."""
    out = []
    for x in si:
        if _ln(x.tag) == "t":
            out.append(x.text or "")
        elif _ln(x.tag) == "r":
            out += [y.text or "" for y in x if _ln(y.tag) == "t"]
    return "".join(out)


def _first_sheet(z: zipfile.ZipFile, names: set[str]) -> str:
    """Первый лист книги по workbook.xml и его связям; не вышло — sheet1.xml / первый по номеру."""
    try:
        wb = _xml(_member(z, "xl/workbook.xml"))
        first = next(e for e in wb.iter() if _ln(e.tag) == "sheet")
        rid = next(v for k, v in first.attrib.items() if _ln(k) == "id")
        rels = _xml(_member(z, "xl/_rels/workbook.xml.rels"))
        target = next(e.get("Target", "") for e in rels.iter() if e.get("Id") == rid)
        path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        if path in names:
            return path
    except (StopIteration, KeyError):
        pass
    sheets = sorted((n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)),
                    key=lambda n: int(re.search(r"\d+", n.rsplit("/", 1)[1]).group()))
    if not sheets:
        raise ReportError("В файле XLSX нет листов.")
    return sheets[0]


# ---------- значения ----------
def num(s: str) -> float | None:
    """«1 234,50 ₽», «1,234.50», «-500» → число; не число — None."""
    s = re.sub(r"[\s  ₽$€]|руб\.?|р\.", "", str(s or ""), flags=re.I)
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%Y/%m/%d", "%Y.%m.%d", "%m/%d/%Y")


def to_date(s: str) -> date | None:
    s = str(s or "").strip()
    if not s:
        return None
    head = re.split(r"[ T]", s, maxsplit=1)[0]
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(head, f).date()
        except ValueError:
            continue
    v = num(s)
    if v is not None and 20000 <= v <= 80000:                   # дата Excel — число дней с 30.12.1899
        return date(1899, 12, 30) + timedelta(days=int(v))
    return None


def norm_head(h: str) -> str:
    return re.sub(r"[^a-zа-я0-9]+", " ", h.lower().replace("ё", "е")).strip()


def guess(head: list[str]) -> dict[str, int]:
    """Заголовки → {роль: номер столбца}. Каждый столбец — одной роли."""
    heads = [norm_head(h) for h in head]
    taken: set[int] = set()
    out: dict[str, int] = {}
    for role, pats in PATTERNS:
        for p in pats:
            hit = next((i for i, h in enumerate(heads) if i not in taken and re.search(p, h)), None)
            if hit is not None:
                out[role] = hit
                taken.add(hit)
                break
    return out


def guess_kind(m: dict[str, int]) -> str:
    if {"debt", "due", "overdue"} & m.keys() and "client" in m:
        return "debtors"
    if {"last_visit", "visits"} & m.keys() and "client" in m:
        return "clients"
    if "amount" in m and ("point" in m or "item" in m or "client" not in m):
        return "sales"
    if "client" in m and "date" in m:
        return "clients"
    if "amount" in m:
        return "sales"
    return ""


def missing(kind: str, m: dict[str, int]) -> list[str]:
    need, _ = NEEDS[kind]
    return [" или ".join(ROLE_TITLES[r] for r in g) for g in need if not any(r in m for r in g)]


# ---------- маскировка ----------
ORG = re.compile(r"^(ООО|АО|ПАО|ЗАО|ОАО|НАО|АНО|НКО|ГУП|МУП|ТСЖ|ЖСК|ТСН|ФГУП|LLC|Ltd|GmbH)\b", re.I)
WORD = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё'’-]*")
PATRONYMIC = re.compile(r"(вич|вна|ична|инична|кызы|оглы)$", re.I)


def mask(name: str, n: int) -> str:
    """Имя для отчёта: «Иван Петров» → «Иван П.», «Петров Иван Иванович» → «Иван П.». Юрлицо — как есть (коротко).
    Похоже на телефон, почту или номер — «Клиент №n»."""
    s = " ".join(str(name or "").split())[:80]
    if not s or re.search(r"\d{4,}", s) or "@" in s:
        return f"Клиент №{n}"
    if ORG.match(s):
        return s[:40]
    prefix = ""
    if re.match(r"^ИП\s", s, re.I):
        prefix, s = "ИП ", s[3:]
    w = WORD.findall(s)
    if not w:
        return f"Клиент №{n}"
    if len(w) >= 3 and PATRONYMIC.search(w[2]):
        first, last = w[1], w[0]
    else:
        first, last = w[0], (w[1] if len(w) > 1 else "")
    return prefix + first + (f" {last[0].upper()}." if last else "")


# ---------- формат ----------
def money(v: float) -> str:
    return f"{round(v):,}".replace(",", " ") + " ₽"


def count(v: float) -> str:
    return f"{round(v):,}".replace(",", " ")


def pct(a: float, b: float) -> str:
    return f"{round(100 * a / b)} %" if b else "—"


def ddmm(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def change(cur: float, prev: float) -> str:
    if not prev:
        return "—"
    v = 100 * (cur - prev) / prev
    return f"{'+' if v >= 0 else '−'}{abs(v):.0f} %"


# ---------- сводки ----------
def _cell(r: list[str], m: dict[str, int], role: str) -> str:
    i = m.get(role)
    return r[i] if i is not None and i < len(r) else ""


def sales(rows: list[list[str]], m: dict[str, int]) -> dict:
    data, skipped = [], 0
    for r in rows:
        a = num(_cell(r, m, "amount"))
        if a is None:
            skipped += 1
            continue
        q = num(_cell(r, m, "qty")) if "qty" in m else None
        data.append((to_date(_cell(r, m, "date")), a, _cell(r, m, "point"), _cell(r, m, "item"), q))
    if not data:
        raise ReportError("Не нашёл ни одной суммы — выберите столбец «Сумма» вручную.")
    total = sum(x[1] for x in data)
    cards = [{"label": "Выручка", "value": money(total)}, {"label": "Продаж (строк)", "value": count(len(data))},
             {"label": "Средний чек", "value": money(total / len(data))}]
    tables, notes = [], []
    dated = [x for x in data if x[0]]
    if dated:
        d0, d1 = min(x[0] for x in dated), max(x[0] for x in dated)
        span = (d1 - d0).days
        unit, key = (("день", lambda d: d) if span <= 31 else
                     ("неделя", lambda d: d - timedelta(days=d.weekday())) if span <= 180 else
                     ("месяц", lambda d: d.replace(day=1)))
        per: dict[date, list[float]] = defaultdict(list)
        for x in dated:
            per[key(x[0])].append(x[1])
        keys = sorted(per)
        label = {"день": lambda d: d.strftime("%d.%m"), "неделя": lambda d: "с " + d.strftime("%d.%m"),
                 "месяц": lambda d: d.strftime("%m.%Y")}[unit]
        tables.append({"title": f"По периодам ({unit})", "head": ["Период", "Выручка", "Продаж", "Средний чек"],
                       "rows": [[label(k), money(sum(per[k])), count(len(per[k])), money(sum(per[k]) / len(per[k]))]
                                for k in keys[-12:]]})
        cards.append({"label": "Период", "value": f"{ddmm(d0)} – {ddmm(d1)}"})
        if len(keys) >= 2:
            cur, prev = sum(per[keys[-1]]), sum(per[keys[-2]])
            word = {"день": "к предыдущему дню", "неделя": "к предыдущей неделе", "месяц": "к предыдущему месяцу"}
            cards.append({"label": "Динамика", "value": change(cur, prev), "note": word[unit] + " (последний период "
                          "может быть неполным)"})
    else:
        notes.append("Дат нет или не распознаны — без разбивки по периодам.")
    if "point" in m:
        by: dict[str, list[float]] = defaultdict(list)
        for x in data:
            by[x[2] or "—"].append(x[1])
        top = sorted(by.items(), key=lambda kv: -sum(kv[1]))[:10]
        tables.append({"title": "По точкам", "head": ["Точка", "Выручка", "Доля", "Средний чек"],
                       "rows": [[k[:60], money(sum(v)), pct(sum(v), total), money(sum(v) / len(v))] for k, v in top]})
    if "item" in m:
        it: dict[str, list] = defaultdict(lambda: [0.0, 0.0])
        for x in data:
            it[x[3] or "—"][0] += x[1]
            it[x[3] or "—"][1] += x[4] if x[4] is not None else 1
        top = sorted(it.items(), key=lambda kv: -kv[1][0])[:5]
        tables.append({"title": "Топ позиций", "head": ["Позиция", "Выручка", "Доля", "Кол-во"],
                       "rows": [[k[:60], money(v[0]), pct(v[0], total), count(v[1])] for k, v in top]})
    if skipped:
        notes.append(f"Строк без суммы пропущено: {skipped}.")
    return {"cards": cards, "tables": tables, "notes": notes}


def clients(rows: list[list[str]], m: dict[str, int]) -> dict:
    """Клиенты: по строке на клиента (последний визит, визитов) или журнал визитов (клиент, дата)."""
    per: dict[str, dict] = {}
    per_row = "last_visit" in m
    for r in rows:
        who = _cell(r, m, "client").strip()
        d = to_date(_cell(r, m, "last_visit" if per_row else "date"))
        if not who or not d:
            continue
        c = per.setdefault(who, {"last": d, "visits": 0, "sum": 0.0})
        c["last"] = max(c["last"], d)
        c["visits"] += int(num(_cell(r, m, "visits")) or 0) if per_row and "visits" in m else (0 if per_row else 1)
        c["sum"] += num(_cell(r, m, "amount")) or 0.0
    if not per:
        raise ReportError("Не нашёл клиентов с датами — выберите столбцы «Клиент» и «Последний визит» (или «Дата»).")
    ref = max(c["last"] for c in per.values())
    edges = [("до 30 дней", 0, 30), ("31–45 дней", 31, 45), ("46–60 дней", 46, 60), ("больше 60 дней", 61, 10 ** 6)]
    days = {k: (ref - c["last"]).days for k, c in per.items()}
    n = len(per)
    buckets = [[t, count(sum(1 for v in days.values() if lo <= v <= hi)),
                pct(sum(1 for v in days.values() if lo <= v <= hi), n)] for t, lo, hi in edges]
    known_visits = not per_row or "visits" in m
    repeat = sum(1 for c in per.values() if c["visits"] >= 2)
    lapsed = [k for k, v in days.items() if v > 45]
    cards = [{"label": "Клиентов", "value": count(n)},
             {"label": "Давно не были (45+ дней)", "value": count(len(lapsed)), "note": pct(len(lapsed), n)}]
    if known_visits:
        cards.append({"label": "Повторные (2+ визита)", "value": count(repeat), "note": pct(repeat, n)})
    cards.append({"label": "На дату", "value": ddmm(ref), "note": "последняя запись в файле"})
    order = {k: i + 1 for i, k in enumerate(per)}
    back = sorted(lapsed, key=lambda k: (-per[k]["visits"], days[k]))[:5]
    tables = [{"title": "Сколько дней не были", "head": ["Давность", "Клиентов", "Доля"], "rows": buckets}]
    if back:
        tables.append({"title": "Кого вернуть первыми", "head": ["Клиент", "Последний визит", "Визитов"],
                       "rows": [[mask(k, order[k]), ddmm(per[k]["last"]),
                                 count(per[k]["visits"]) if known_visits else "—"] for k in back]})
    notes = [f"Напоминание «ждём вас» в рабочем режиме — пачкой из {len(lapsed)} сообщений и только тем, кто дал "
             "согласие на рассылку; отправляет человек после «Да»."] if lapsed else []
    return {"cards": cards, "tables": tables, "notes": notes, "batch": len(lapsed)}


def debtors(rows: list[list[str]], m: dict[str, int], today: date | None = None) -> dict:
    today = today or date.today()
    per: dict[str, dict] = {}
    for r in rows:
        who = _cell(r, m, "client").strip()
        if "debt" in m:
            d = num(_cell(r, m, "debt"))
        else:
            a = num(_cell(r, m, "amount"))
            d = None if a is None else a - (num(_cell(r, m, "paid")) or 0.0)
        if not who or not d or d <= 0:
            continue
        od = None
        if "overdue" in m:
            v = num(_cell(r, m, "overdue"))
            od = int(v) if v is not None else None
        elif "due" in m and (due := to_date(_cell(r, m, "due"))):
            od = (today - due).days
        c = per.setdefault(who, {"sum": 0.0, "od": None, "over": 0.0, "docs": 0})
        c["sum"] += d
        c["docs"] += 1
        if od is not None:
            c["od"] = od if c["od"] is None else max(c["od"], od)
            if od > 0:
                c["over"] += d
    if not per:
        raise ReportError("Не нашёл долгов — выберите столбцы «Клиент» и «Долг» (или «Сумма» и «Оплачено»).")
    total = sum(c["sum"] for c in per.values())
    known = any(c["od"] is not None for c in per.values())
    cards = [{"label": "Должны всего", "value": money(total)}, {"label": "Должников", "value": count(len(per))}]
    tables, notes = [], []
    if known:
        over = sum(c["over"] for c in per.values())
        over30 = sum(c["sum"] for c in per.values() if (c["od"] or 0) > 30)
        cards += [{"label": "Просрочено", "value": money(over), "note": pct(over, total)},
                  {"label": "Больше 30 дней", "value": money(over30), "note": pct(over30, total)}]
        edges = [("срок не наступил", -10 ** 6, 0), ("1–30 дней", 1, 30), ("31–60 дней", 31, 60),
                 ("61–90 дней", 61, 90), ("больше 90 дней", 91, 10 ** 6)]
        rows_b = []
        for t, lo, hi in edges:
            sel = [c for c in per.values() if c["od"] is not None and lo <= c["od"] <= hi]
            rows_b.append([t, money(sum(c["sum"] for c in sel)), count(len(sel))])
        if nod := [c for c in per.values() if c["od"] is None]:
            rows_b.append(["без срока", money(sum(c["sum"] for c in nod)), count(len(nod))])
        tables.append({"title": "По просрочке (по самой старой у должника)",
                       "head": ["Просрочка", "Сумма", "Должников"], "rows": rows_b})
        notes.append(f"Просрочка — на сегодня, {ddmm(today)}.")
    else:
        notes.append("Нет срока оплаты или дней просрочки — только суммы. Выберите столбец «Срок оплаты» вручную, "
                     "если он есть.")
    order = {k: i + 1 for i, k in enumerate(per)}
    top = sorted(per.items(), key=lambda kv: -kv[1]["sum"])[:5]
    tables.append({"title": "Топ-5 должников", "head": ["Должник", "Сумма", "Просрочка"],
                   "rows": [[mask(k, order[k]), money(c["sum"]),
                             (f"{c['od']} дн." if c["od"] and c["od"] > 0 else "нет") if c["od"] is not None else "—"]
                            for k, c in top]})
    late = sum(1 for c in per.values() if (c["od"] or 0) > 0)
    if late:
        notes.append(f"Напоминание об оплате в рабочем режиме — пачкой из {late} писем по лестнице (вежливо → "
                     "претензия); отправляет человек после «Да».")
    return {"cards": cards, "tables": tables, "notes": notes, "batch": late}


def build(data: bytes, kind: str = "", mapping: dict | None = None, today: date | None = None) -> dict:
    """Байты выгрузки → сводка. ``kind`` и ``mapping`` ({роль: номер столбца}) — выбор человека; пусто — угадываем."""
    t0 = time.monotonic()
    head, rows = read_table(data)
    auto = guess(head)
    m = dict(auto)
    if mapping:
        m = {}
        for role, i in mapping.items():
            if role in ROLE_TITLES and isinstance(i, int) and 0 <= i < len(head):
                m[role] = i
        for role in PRIVATE:                                  # личные столбцы — всегда помечены как личные
            if role in auto and auto[role] not in m.values():
                m[role] = auto[role]
    kind = kind if kind in KINDS else guess_kind(m)
    if not kind:
        raise ReportError("Не понял, что в файле: выберите тип выгрузки и столбцы вручную.")
    if miss := missing(kind, m):
        out = {"error": "Не хватает столбцов: " + "; ".join(miss) + ". Выберите их вручную."}
        return {**out, **_frame(kind, head, rows, m)}
    body = sales(rows, m) if kind == "sales" else clients(rows, m) if kind == "clients" else debtors(rows, m, today)
    return {**_frame(kind, head, rows, m), **body, "took_ms": round(1000 * (time.monotonic() - t0))}


def _frame(kind: str, head: list[str], rows: list, m: dict[str, int]) -> dict:
    need, opt = NEEDS[kind]
    roles = [r for g in need for r in g] + opt
    return {"kind": kind, "kind_title": KINDS[kind], "rows": len(rows), "columns": [h[:60] for h in head],
            "mapping": {r: i for r, i in m.items() if r in ROLE_TITLES},
            "private": sorted({head[i][:60] for r, i in m.items() if r in PRIVATE}),
            "roles": [{"id": r, "title": ROLE_TITLES[r]} for r in dict.fromkeys(roles)]}
