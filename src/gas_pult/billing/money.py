"""Деньги — только целые центы (минимальные единицы валюты). Никаких float: ``float`` на входе — ошибка.

Округление — всегда явно: функции, где оно возможно, требуют ``rounding`` (константы ``decimal``). Где округлять
нельзя (ввод суммы человеком), ``to_minor`` без ``rounding`` отказывает на лишних знаках.
"""

from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation

# ISO 4217: код → число знаков после запятой. Список — то, что нужно сейчас; новая валюта — строкой сюда.
MINOR = {"EUR": 2, "USD": 2, "GBP": 2, "CHF": 2, "CAD": 2, "AUD": 2, "SEK": 2, "NOK": 2, "DKK": 2, "PLN": 2,
         "CZK": 2, "RUB": 2, "JPY": 0, "KRW": 0, "BHD": 3, "KWD": 3}
MAX_MINOR = 10**12                     # потолок суммы одной строки и счёта: 10 млрд в валюте с двумя знаками
ROUNDINGS = {"half_even": ROUND_HALF_EVEN, "half_up": ROUND_HALF_UP}   # имена — для API и журнала


def currency(code: str) -> str:
    """Код валюты ISO 4217 из списка ``MINOR`` (верхний регистр) или ``ValueError``."""
    c = str(code or "").strip().upper()
    if c not in MINOR:
        raise ValueError("валюта не из списка ISO 4217 пульта: " + (c or "пусто"))
    return c


def _dec(value) -> Decimal:
    if isinstance(value, float):
        raise TypeError("суммы — не float: передайте строку, int или Decimal")
    if isinstance(value, bool):
        raise TypeError("сумма — не bool")
    try:
        d = Decimal(str(value).strip().replace(",", ".")) if not isinstance(value, Decimal) else value
    except InvalidOperation:
        raise ValueError("сумма не числом: " + str(value)[:40]) from None
    if not d.is_finite():
        raise ValueError("сумма не числом")
    return d


def to_minor(value, code: str, rounding: str | None = None) -> int:
    """Сумма в валюте («12.34», Decimal, int) → целые минимальные единицы. Без ``rounding`` лишние знаки — ошибка."""
    q = Decimal(1).scaleb(-MINOR[currency(code)])
    d = _dec(value)
    if rounding is None:
        if d != d.quantize(q):
            raise ValueError(f"в {currency(code)} не больше {MINOR[currency(code)]} знаков после запятой")
        r = d.quantize(q)
    else:
        r = d.quantize(q, rounding=ROUNDINGS[rounding])
    n = int(r.scaleb(MINOR[currency(code)]))
    return check(n)


def check(n, *, signed: bool = False) -> int:
    """Целые центы в пределах ``MAX_MINOR``; ``signed`` разрешает минус (встречные записи журнала)."""
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError("сумма в центах — только int")
    if (n < 0 and not signed) or abs(n) > MAX_MINOR:
        raise ValueError("сумма вне пределов")
    return n


def percent(amount: int, basis_points: int, rounding: str) -> int:
    """Доля суммы: ``basis_points`` — сотые доли процента (2000 = 20 %). Округление — явно, до целого цента."""
    check(amount, signed=True)
    if isinstance(basis_points, bool) or not isinstance(basis_points, int):
        raise TypeError("доля — int в сотых долях процента")
    return int((Decimal(amount) * basis_points / 10000).quantize(Decimal(1), rounding=ROUNDINGS[rounding]))


def line(qty: int, unit: int) -> int:
    """Строка счёта: количество × цена за единицу, оба целые; переполнение — ошибка."""
    if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0 or qty > 100000:
        raise ValueError("количество — целое от 1 до 100000")
    return check(qty * check(unit))


def fmt(n: int, code: str) -> str:
    """Человеку: 123456, EUR → «1234.56 EUR»; без float."""
    k = MINOR[currency(code)]
    s = str(Decimal(check(n, signed=True)).scaleb(-k).quantize(Decimal(1).scaleb(-k)))
    return f"{s} {currency(code)}"
