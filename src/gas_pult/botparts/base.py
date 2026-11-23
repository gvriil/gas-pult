"""Общее для частей ``Pult``: ошибки «окно не готово» и признак вопроса Claude на экране.

Перенесены из ``bot.py`` как есть (модульный монолит, docs/MONOLITH-PLAN.md п.3.3): ими пользуются и ``bot``, и
``botparts/*``, а части не импортируют ``bot``. ``bot.NotReady``, ``bot.AwaitsChoice``, ``bot.Denied``, ``bot.HINT``,
``bot.QUESTION`` — те же объекты.
"""

from __future__ import annotations

import re

HINT = r"(?:[^·\n]{1,40}·\s*)*"          # подсказки внизу меню могут идти после других: «↑/↓ to navigate · Enter to …»
# Готовность окна к тексту. Вопрос Claude (разрешение, выбор пункта): Esc там значит «нет» — за человека не отвечаем.
QUESTION = re.compile(r"^\s*Do you (want|trust)|^\s*Review your answers\s*$|^\s*" + HINT + r"Enter to (confirm|select)",
                      re.M)                       # «Review your answers» — сводка ответов без подсказки внизу (22.11)


class NotReady(RuntimeError):
    """Окно не готово принять текст — сообщение не вставляем вслепую, а говорим человеку почему."""


class AwaitsChoice(NotReady):
    """Claude ждёт выбора пункта (вопрос с вариантами, разрешение): текст не вставляем. Панель по ``code`` не
    показывает ошибку, а подсвечивает кнопки вариантов и оставляет текст в поле (22.11)."""
    code = "question"


class Denied(RuntimeError):
    """Поставщик окна не разрешён для стран человека — отвечаем ровно ``country.DENY``."""
