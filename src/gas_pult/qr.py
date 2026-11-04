"""QR-код без внешних зависимостей: байтовый режим, коррекция ошибок M, версии 1–10 (до 213 байт — ссылка
приглашения помещается с запасом), выбор маски по штрафам стандарта. Картинка — PNG через ``zlib``/``struct``.

Алгоритм (Рид — Соломон в GF(256), размещение модулей, формат и версия, штрафы масок) — по «QR Code generator
library» Project Nayuki (https://www.nayuki.io/page/qr-code-generator-library, лицензия MIT, © Project Nayuki);
код переписан компактно под одну задачу. Стандарт — ISO/IEC 18004.
"""

from __future__ import annotations

import struct
import zlib

# версия → (кодовых слов коррекции на блок, [число блоков с данными по n слов, …]) для уровня M
_M = {1: (10, [(1, 16)]), 2: (16, [(1, 28)]), 3: (26, [(1, 44)]), 4: (18, [(2, 32)]), 5: (24, [(2, 43)]),
      6: (16, [(4, 27)]), 7: (18, [(4, 31)]), 8: (22, [(2, 38), (2, 39)]), 9: (22, [(3, 36), (2, 37)]),
      10: (26, [(4, 43), (1, 44)])}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
          9: [6, 26, 46], 10: [6, 28, 50]}
_MASKS = (lambda r, c: (r + c) % 2 == 0, lambda r, c: r % 2 == 0, lambda r, c: c % 3 == 0,
          lambda r, c: (r + c) % 3 == 0, lambda r, c: (r // 2 + c // 3) % 2 == 0,
          lambda r, c: r * c % 2 + r * c % 3 == 0, lambda r, c: (r * c % 2 + r * c % 3) % 2 == 0,
          lambda r, c: ((r + c) % 2 + r * c % 3) % 2 == 0)
EC_M = 0b00                                     # биты уровня M в формате


def capacity(version: int) -> int:
    """Сколько байт помещается в версию (байтовый режим, уровень M)."""
    data = sum(n * k for n, k in _M[version][1])
    return (data * 8 - 4 - (8 if version < 10 else 16)) // 8


def _mul(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _divisor(degree: int) -> list[int]:
    out, root = [0] * (degree - 1) + [1], 1
    for _ in range(degree):
        for j in range(degree):
            out[j] = _mul(out[j], root)
            if j + 1 < degree:
                out[j] ^= out[j + 1]
        root = _mul(root, 2)
    return out


def _ecc(data: list[int], div: list[int]) -> list[int]:
    out = [0] * len(div)
    for b in data:
        f = b ^ out.pop(0)
        out.append(0)
        for i, c in enumerate(div):
            out[i] ^= _mul(c, f)
    return out


def _codewords(data: bytes, version: int) -> list[int]:
    """Биты данных → кодовые слова с коррекцией, перемешанные по блокам."""
    ec, groups = _M[version]
    total = sum(n * k for n, k in groups)
    bits: list[int] = []

    def put(v: int, n: int):
        bits.extend((v >> i) & 1 for i in reversed(range(n)))
    put(0b0100, 4)
    put(len(data), 8 if version < 10 else 16)
    for b in data:
        put(b, 8)
    put(0, min(4, total * 8 - len(bits)))
    put(0, -len(bits) % 8)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(words) < total:
        words.append(pad)
        pad ^= 0xEC ^ 0x11
    blocks, at, div = [], 0, _divisor(ec)
    for n, k in groups:
        for _ in range(n):
            blocks.append((words[at:at + k], _ecc(words[at:at + k], div)))
            at += k
    out = [b[0][i] for i in range(max(len(b[0]) for b in blocks)) for b in blocks if i < len(b[0])]
    return out + [b[1][i] for i in range(ec) for b in blocks]


class Qr:
    def __init__(self, version: int):
        self.version, self.size = version, version * 4 + 17
        self.m = [[False] * self.size for _ in range(self.size)]
        self.fn = [[False] * self.size for _ in range(self.size)]

    def set(self, x: int, y: int, dark: bool):
        self.m[y][x], self.fn[y][x] = dark, True

    def functions(self):
        s = self.size
        for i in range(s):                                    # линии синхронизации
            self.set(6, i, i % 2 == 0)
            self.set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (s - 4, 3), (3, s - 4)):       # поисковые узоры с белой рамкой
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < s and 0 <= y < s:
                        self.set(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = _ALIGN[self.version]
        for i, a in enumerate(pos):                           # выравнивающие узоры
            for j, b in enumerate(pos):
                if (i, j) in ((0, 0), (0, len(pos) - 1), (len(pos) - 1, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set(a + dx, b + dy, max(abs(dx), abs(dy)) != 1)
        self.format(0)
        if self.version >= 7:                                 # блоки версии
            rem = self.version
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.version << 12 | rem
            for i in range(18):
                bit, a, b = (bits >> i) & 1 == 1, s - 11 + i % 3, i // 3
                self.set(a, b, bit)
                self.set(b, a, bit)

    def format(self, mask: int):
        data = EC_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits, s = (data << 10 | rem) ^ 0x5412, self.size

        def bit(i: int) -> bool:
            return (bits >> i) & 1 == 1
        for i in range(6):
            self.set(8, i, bit(i))
        self.set(8, 7, bit(6))
        self.set(8, 8, bit(7))
        self.set(7, 8, bit(8))
        for i in range(9, 15):
            self.set(14 - i, 8, bit(i))
        for i in range(8):
            self.set(s - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set(8, s - 15 + i, bit(i))
        self.set(8, s - 8, True)                              # тёмный модуль

    def place(self, words: list[int]):
        s, i, n = self.size, 0, len(words) * 8
        for right in range(s - 1, 0, -2):
            if right <= 6:
                right -= 1
            up = ((right + 1) & 2) == 0
            for vert in range(s):
                y = s - 1 - vert if up else vert
                for j in range(2):
                    x = right - j
                    if not self.fn[y][x] and i < n:
                        self.m[y][x] = (words[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1

    def apply(self, mask: int):
        f = _MASKS[mask]
        for y in range(self.size):
            for x in range(self.size):
                if not self.fn[y][x] and f(y, x):
                    self.m[y][x] = not self.m[y][x]

    def penalty(self) -> int:
        """Штрафы стандарта: ряды одного цвета, квадраты 2×2, узоры как у поисковых, доля тёмных."""
        s, m, p = self.size, self.m, 0
        lines = m + [[m[y][x] for y in range(s)] for x in range(s)]
        for row in lines:
            run, prev = 0, None
            for v in row:
                run = run + 1 if v == prev else 1
                prev = v
                if run == 5:
                    p += 3
                elif run > 5:
                    p += 1
            txt = "".join("1" if v else "0" for v in row)
            for pat in ("10111010000", "00001011101"):
                start = txt.find(pat)
                while start != -1:
                    p += 40
                    start = txt.find(pat, start + 1)
        for y in range(s - 1):
            for x in range(s - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    p += 3
        dark = sum(map(sum, m))
        k = (abs(dark * 20 - s * s * 10) + s * s - 1) // (s * s) - 1
        return p + max(k, 0) * 10


def encode(text: str | bytes, mask: int | None = None) -> list[list[bool]]:
    """Матрица модулей (True — тёмный) для наименьшей подходящей версии 1–10. ``mask`` — для проверок."""
    data = text.encode() if isinstance(text, str) else bytes(text)
    version = next((v for v in _M if capacity(v) >= len(data)), None)
    if version is None:
        raise ValueError(f"слишком длинный текст для QR: {len(data)} байт (не больше {capacity(10)})")
    words = _codewords(data, version)
    best = None
    for k in range(8) if mask is None else (mask,):
        q = Qr(version)
        q.functions()
        q.place(words)
        q.apply(k)
        q.format(k)
        score = q.penalty()
        if best is None or score < best[0]:
            best = (score, q)
    return best[1].m


def png(matrix: list[list[bool]], scale: int = 8, border: int = 4) -> bytes:
    """PNG в оттенках серого (8 бит): тёмные модули — чёрные, фон и тихая зона — белые."""
    n = len(matrix) + 2 * border
    rows = []
    for y in range(n):
        my = y - border
        line = bytearray()
        for x in range(n):
            mx = x - border
            dark = 0 <= my < len(matrix) and 0 <= mx < len(matrix) and matrix[my][mx]
            line += (b"\x00" if dark else b"\xff") * scale
        rows.extend([b"\x00" + bytes(line)] * scale)       # фильтр 0 у каждой строки

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    w = n * scale
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, w, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def png_of(text: str, scale: int = 8) -> bytes:
    return png(encode(text), scale)
