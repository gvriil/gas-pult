"""Политика обработки персональных данных: версия, флаг «опубликовано» и данные оператора (аудит 24.11).

Страница ``/privacy`` (``web/privacy.html``, русский и английский) — черновик: пока владелец не скажет «да»,
``PUBLISHED = False`` и наверху видна плашка «Черновик — не опубликовано». Опубликовать — ``PUBLISHED = True`` в
пулл-реквесте, после проверки текста юристом (места для юриста — комментарии «сверить у юриста» в шаблоне и
``docs/PRIVACY.md``).

Версия и дата — одно место: ``VERSION`` (``ГГГГ-ММ-ДД``). Поменяли смысл политики — новая дата: согласие спросят
заново (анкета /q/ и фокус-ссылка проверяют согласие на текущую версию, ``consents.has_doc``).

Оператор — НЕ в репозитории (репозиторий публичный): имя, ИНН, ОГРНИП, адрес, почта, телефон — из файла
``<каталог настроек>/operator.toml`` (``config.config_dir``, ``GAS_PULT_CONFIG_DIR``), вне git. Нет файла или поля —
на странице «[ЗАПОЛНИТЬ]». Формат — ``docs/PRIVACY.md``. Только стандартная библиотека.
"""

from __future__ import annotations

import html
import tomllib
from pathlib import Path

from gas_pult import terms
from gas_pult.config import config_dir

VERSION = "2026-11-24"                 # поменяли смысл политики — новая дата
PUBLISHED = False                      # «да» владельца после проверки юристом — True (плашка «Черновик» исчезнет)
FILE = "operator.toml"
FIELDS = ("name", "inn", "ogrnip", "address", "email", "phone")
FILL = "[ЗАПОЛНИТЬ]"
FIELD_MAX = 300                        # предохранитель: длина одного поля в файле оператора


def operator(cfg: Path | None = None) -> dict[str, str]:
    """Данные оператора из ``operator.toml``: только известные поля, строки; нет файла, поля или файл с ошибкой —
    пустая строка (страница покажет «[ЗАПОЛНИТЬ]»)."""
    path = Path(cfg or config_dir()) / FILE
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    sec = raw.get("operator") if isinstance(raw.get("operator"), dict) else raw   # поля в корне или в [operator]
    return {k: " ".join(str(sec.get(k) or "").split())[:FIELD_MAX] for k in FIELDS}


def page(raw: bytes, cfg: Path | None = None) -> bytes:
    """Страница ``/privacy``: версия, дата, плашка черновика и данные оператора (экранированы; нет — «[ЗАПОЛНИТЬ]»).
    Хеш согласия считается от этих байтов (``terms.sha256``) — с тем текстом, что видел человек."""
    op = operator(cfg)
    fill = '<mark class="fill">' + FILL + "</mark>"
    extra = {f"OP_{k.upper()}": html.escape(v) if v else fill for k, v in op.items()}
    extra["DRAFT_HIDDEN"] = " hidden" if PUBLISHED else ""
    return terms.fill(raw, VERSION, extra)
