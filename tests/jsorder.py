"""Порядок скриптов панели (разбиение на модули): при загрузке верхний уровень файла не трогает функцию из более
позднего файла.

В одном <script> объявления функций «всплывают» — вызвать функцию, объявленную ниже, можно. Разнесли код по файлам —
функции следующего файла при выполнении предыдущего ещё нет: ReferenceError при загрузке. Здесь — статическая
проверка: для каждого оператора верхнего уровня (кроме объявлений функций и стрелок) собираются имена, которые он
трогает сразу, и транзитивно — через тела функций. Тела стрелок и function-выражений не считаются — выполнятся,
когда их вызовут (обработчики, поля объектов), — кроме переданных в forEach/map/…/new Promise, сразу вызванных и
продолжений then/catch/finally (обещание может быть уже выполнено — продолжение пойдёт раньше следующего файла).
Обработчик-имя (addEventListener("x", f), .onx = f, setTimeout(f)) должен быть уже объявлен. Имя функции из более
позднего файла — ошибка.

    python3 tests/jsorder.py src/gas_pult/web    — порядок: <script src="/js/…"> и встроенные <script> из index.html

Разбор грубый (строки, шаблоны, комментарии, регулярки вырезаются; верхний уровень — строки без отступа, как
принято в коде панели). Ложное срабатывание лучше пропуска: при сомнении — перенести объявление раньше.
"""
import re
import sys
from pathlib import Path

KW_BEFORE_REGEX = {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw", "instanceof",
                   "yield", "await"}


def strip(src: str) -> str:
    """Строки, шаблоны (кроме ${…}), комментарии, регулярки → пробелы той же длины (переводы строк сохраняются)."""
    out = list(src)
    i, n = 0, len(src)
    stack = []          # для шаблонов: глубина фигурных скобок
    last = ""           # последний значимый токен (для регулярок)

    def blank(a, b):
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "
    while i < n:
        c = src[i]
        if c == "/" and src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
            continue
        if c == "/" and src.startswith("/*", i):
            j = src.find("*/", i + 2) + 2
            blank(i, j)
            i = j
            continue
        if c in "'\"":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            blank(i + 1, j)
            i = j + 1
            last = "str"
            continue
        if c == "`" or (c == "}" and stack and stack[-1] == 0):
            if c == "}":
                stack.pop()
            j = i + 1
            while j < n and src[j] != "`" and not src.startswith("${", j):
                j += 2 if src[j] == "\\" else 1
            blank(i + 1, j)
            if j < n and src[j] == "`":
                i = j + 1
                last = "str"
            else:
                stack.append(0)
                i = j + 2
                last = "("
            continue
        if c == "/" and (last in ("", "(", ",", "=", ":", "[", "!", "&", "|", "?", "{", "}", ";", "+", "-", "*", "%",
                                  "<", ">", "~", "^") or last in KW_BEFORE_REGEX):
            j = i + 1
            cls = False
            while j < n and (src[j] != "/" or cls):
                if src[j] == "\\":
                    j += 1
                elif src[j] == "[":
                    cls = True
                elif src[j] == "]":
                    cls = False
                elif src[j] == "\n":
                    break
                j += 1
            blank(i + 1, j)
            i = j + 1
            last = "str"
            continue
        if c == "{" and stack:
            stack[-1] += 1
        elif c == "}" and stack:
            stack[-1] -= 1
        if c.isalnum() or c in "_$":
            m = re.match(r"[\w$]+", src[i:])
            last = m.group(0)
            i += len(last)
            continue
        if not c.isspace():
            last = c
        i += 1
    return "".join(out)


def items(text: str):
    """Верхний уровень: [(первая строка, вид, имя, текст)]; вид — fn (function / const стрелка) или run."""
    lines = text.split("\n")
    res, cur = [], None
    for k, ln in enumerate(lines):
        if ln and not ln[0].isspace() and ln[0] not in "}])":
            if cur:
                res.append(cur)
            cur = [k, ln]
        elif cur:
            cur[1] += "\n" + ln
    if cur:
        res.append(cur)
    out = []
    for k, t in res:
        m = re.match(r"(?:async\s+)?function\*?\s+([\w$]+)", t)
        if m:
            out.append((k, "fn", m.group(1), t))
            continue
        m = re.match(r"(?:const|let|var)\s+([\w$]+)\s*=\s*(?:async\s+)?(?:\([^()]*\)|[\w$]+)\s*=>", t)
        if m:
            out.append((k, "fn", m.group(1), t))
            continue
        m = re.match(r"class\s+([\w$]+)", t)
        out.append((k, "cls" if m else "run", m.group(1) if m else "", t))
    return out


# обработчики — выполнятся позже (событие, таймер). then/catch/finally сюда не входят: обещание может быть уже
# выполнено, и его продолжение пойдёт сразу после текущего файла — раньше следующего.
DEFER = re.compile(r"(addEventListener\s*\(|\.on\w+\s*=|setTimeout\s*\(|setInterval\s*\(|"
                   r"requestAnimationFrame\s*\(|Observer\s*\(|onEvent\??\.?\s*\(|onClick\s*\()")


# сразу выполняемые обратные вызовы; then/catch/finally — продолжение уже выполненного обещания идёт до следующего файла
SYNC_CB = re.compile(r"(?:\.(?:forEach|map|filter|find|findIndex|findLast|some|every|reduce|reduceRight|flatMap|sort"
                     r"|then|catch|finally)"
                     r"|\bArray\.from|\bnew Promise)\s*\(\s*(?:[^(),]*,\s*)?$")


def _body_end(t: str, k: int) -> int:
    """Конец тела функции, начинающегося в k: {…} или выражение стрелки до , ) ] } ; на нулевой глубине."""
    while k < len(t) and t[k] in " \t\n":
        k += 1
    if k < len(t) and t[k] == "{":
        d = 0
        while k < len(t):
            d += {"{": 1, "}": -1}.get(t[k], 0)
            k += 1
            if d == 0:
                return k
        return k
    d = 0
    while k < len(t):
        ch = t[k]
        if ch in "([{":
            d += 1
        elif ch in ")]}":
            if d == 0:
                return k
            d -= 1
        elif ch in ",;" and d == 0:
            return k
        k += 1
    return k


def fn_body(t: str) -> str:
    """Тело объявления: после «) {» у function / class, после «=>» у стрелки."""
    m = re.search(r"=>\s*|\)\s*\{|\bclass\b[^{]*\{", t)
    return t[m.end():] if m else t


def eager_part(t: str) -> str:
    """Оставить то, что выполнится сразу: тела стрелок и function-выражений убираются (они выполнятся, когда их
    вызовут), кроме переданных в синхронные forEach/map/filter/…/then/new Promise и сразу вызванных (IIFE). Имя
    функции, переданное обработчиком (addEventListener, on…=, setTimeout…), — ``__REF__имя``: должна быть объявлена,
    тело — позже."""
    out, i = [], 0
    fn = re.compile(r"(\((?:[^()]|\([^()]*\))*\)|[A-Za-z_$][\w$]*)\s*=>|\bfunction\b\s*[\w$]*\s*\([^)]*\)\s*(?=\{)")
    while True:
        m = fn.search(t, i)
        if not m:
            break
        head = t[:m.start()]
        body_at = m.end()
        end = _body_end(t, body_at)
        iife = head.rstrip().endswith("(") and t[end:end + 3].lstrip().startswith(")(")
        if SYNC_CB.search(head) or iife:
            out.append(t[i:body_at])          # тело выполнится сразу — разбирать дальше как обычный код
            i = body_at
            continue
        out.append(t[i:m.start()])
        i = end
    out.append(t[i:])
    t = "".join(out)
    # обработчик-имя: …addEventListener("x", имя …) / .onx = имя / setTimeout(имя, …)
    t = re.sub(r"(" + DEFER.pattern + r")(\s*(?:\"[^\"]*\"\s*,|'[^']*'\s*,)?\s*)([A-Za-z_$][\w$]*)(?=\s*[,);\n])",
               lambda m: m.group(1) + m.group(m.lastindex - 1) + "__REF__" + m.group(m.lastindex), t)
    return t


def refs(t: str) -> set:
    t = re.sub(r"(?<=[.])\s*[\w$]+", "", t)            # свойства после точки
    t = re.sub(r"[\w$]+(?=\s*:(?!:))", "", t)          # ключи объектов (грубо)
    return set(re.findall(r"(?<![\w$.])[A-Za-z_$][\w$]*", t))


def scripts(web: Path):
    page = (web / "index.html").read_text(encoding="utf-8")
    seq = []
    for m in re.finditer(r'<script(?: src="/(js/[\w/.-]+)")?>(.*?)</script>', page, re.S):
        if m.group(1):
            seq.append((m.group(1), (web / m.group(1)).read_text(encoding="utf-8")))
        elif m.group(2).strip() and not m.group(2).lstrip().startswith(("{", "[")):
            seq.append(("index.html<script>", m.group(2)))
    return seq


def check(web: Path):
    seq = scripts(web)
    decl = {}                    # имя функции → (номер файла, текст тела)
    order = []
    for fi, (name, src) in enumerate(seq):
        s = strip(src)
        its = items(s)
        order.append((name, its))
        for k, kind, nm, t in its:
            if kind in ("fn", "cls"):
                decl.setdefault(nm, (fi, eager_part(fn_body(t)), name, k))
    bad = []
    for fi, (name, its) in enumerate(order):
        for k, kind, nm, t in its:
            if kind == "fn":
                continue
            todo, seen = list(refs(eager_part(t)) - {nm}), set()
            while todo:
                r = todo.pop()
                if r.startswith("__REF__"):          # только ссылка на обработчик — объявлена ли к этому моменту
                    r = r[7:]
                    if r in decl and decl[r][0] > fi:
                        bad.append(f"{name}:{k + 1}: обработчик {r} ({decl[r][2]}:{decl[r][3] + 1}) — объявлен позже")
                    continue
                if r in seen or r not in decl:
                    continue
                seen.add(r)
                dfi, body, dname, dk = decl[r]
                if dfi > fi:
                    bad.append(f"{name}:{k + 1}: верхний уровень → {r} ({dname}:{dk + 1}) — объявлена позже")
                else:
                    todo += list(refs(body) - {r})
    return bad


if __name__ == "__main__":
    b = check(Path(sys.argv[1]))
    print("\n".join(b) or "ok: верхний уровень не трогает функции из более поздних файлов")
